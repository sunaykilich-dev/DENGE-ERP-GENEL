"""Sözleşme karar tarihinden bakım takvimi ve yıllık takvim görünümü.

Kullanıcı isteği (2026-11-05): "sözleşme karar tarihini vereceğim; yılda kaç
kere ise bakımların hangi ayda yapılacağını hesaplayıp planlama için kayıtları
otomatik aç." Var olan dönem/PB motoru (`bakim.donemleri_hesapla`,
`bakim_uretim`) korunur; bu modül yalnız karar tarihini o motora bağlar.

Kararlar (gerekçeli, `analiz/soru_formu/KARARLAR_2026-10-28.md` §8):

- **Karar tarihi = sözleşme başlangıcı.** `valid_from` karar gününün yerel
  gece yarısı olur. Bitiş verilmezse karar + `sure_ay` (varsayılan 12 ay).
- **Bakım ayları mevcut kuralla:** sabit ay yoksa başlangıçtan eşit aralık
  (`12 / yıllık adet` ay; 15.01 + 3/yıl → 15.01, 15.05, 15.09). Sabit aylar
  verilirse o aylar. Ayrı bir hesap yazılmaz; tek kaynak `bakim.donem_plani`.
- **Geçmiş dönemler:** karar tarihi geçmişteyse, güncel döngüden ÖNCEKİ açık
  dönemler sistem öncesi sayılır ve `GOC_BASLANGIC` ile kapanır (raporlarda
  tamamlama oranına girmez). Güncel döngüde hedefi geçmiş dönemlerden en eski
  `yapilan_adet` kadarı da `GOC_BASLANGIC` ile kapanır (Excel'deki "YAPILAN
  BAKIM ADEDİ"). Kalanlar açık kalır: gerçekten yapılmadıysa gecikmiş görünür
  ve PB'si açılır. Önizleme bu sayıyı ayrıca gösterir ki toplu girişte
  yanlışlıkla yığınla gecikmiş iş açılmasın.
- **Aktifleştirme:** TASLAK / TEYIT_BEKLIYOR sözleşme varsayılan olarak AKTIF'e
  alınır; tesis çakışması kuralı aynen işler (onay gerekirse satır hatası).
- **PB işleri hemen açılmaz:** her dönemin PB'leri hedeften
  `bakim_on_acilis_gun` gün önce `pb-uretimi` görevince açılır (cihaz başına 1
  PB). Yanıt her dönem için açılış gününü ve ilk turda açılacak PB sayısını
  verir. Otomatik görev `bakim_otomatik_uretim` açıkken çalışır.
- **Toplu giriş tek tek SAVEPOINT'te:** bir satırın hatası diğerlerini
  durdurmaz. Önizleme aynı kodu dış SAVEPOINT'te koşturup geri alır (ikinci
  bir "ne olacak" hesabı yazılmaz; `bakim_uretim.onizle` ile aynı desen).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models import (
    Account,
    Address,
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceOrder,
)
from app.models.servis_bakim import DONEM_SAYILAN_KAPANISLAR
from app.services import audit
from app.services import settings as ayar_svc
from app.services.statemachine import IzinsizGecis
from app.services.teknik_servis import bakim
from app.services.teknik_servis.bakim import BakimKapsamDisi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

VARSAYILAN_SURE_AY = 12
AZAMI_SURE_AY = 120
AZAMI_TOPLU_SATIR = 500

# Dönem takvim durumları (yanıt ve arayüz rozetleri aynı kodları kullanır).
SISTEM_ONCESI = "SISTEM_ONCESI"  # GOC_BASLANGIC ile kapandı
KAPANDI = "KAPANDI"  # sistemde kapandı (TAMAMLANDI/KISMI/YAPILAMADI)
PB_ACIK = "PB_ACIK"  # PB işleri açıldı
GECIKMIS = "GECIKMIS"  # hedef geçti, PB yok (ilk turda açılır)
ILK_TURDA = "ILK_TURDA"  # açılış penceresi geldi, ilk turda açılır
ILERIDE = "ILERIDE"  # açılış günü gelecekte
TASLAK_PLAN = "TASLAK_PLAN"  # sözleşme aktif değil; yalnız hesap


@dataclass
class KararGirdisi:
    karar_tarihi: date
    sure_ay: int | None = None
    bitis: date | None = None
    yillik_adet: int | None = None
    sabit_aylar: list[int] | None = None
    yapilan_adet: int | None = None
    aktiflestir: bool = True


_SATIR_HATALARI = (
    ServisHatasi,
    ServisGirdiHatasi,
    BakimKapsamDisi,
    IzinsizGecis,
    PermissionError,
)


def _hata_metni(exc: Exception) -> str:
    if isinstance(exc, BakimKapsamDisi):
        return "Sözleşme bulunamadı"
    return str(exc)


def _bitis(girdi: KararGirdisi) -> date:
    if girdi.bitis is not None:
        if girdi.bitis <= girdi.karar_tarihi:
            raise ServisGirdiHatasi("Bitiş tarihi karar tarihinden sonra olmalı")
        return girdi.bitis
    sure = girdi.sure_ay if girdi.sure_ay is not None else VARSAYILAN_SURE_AY
    if not 1 <= sure <= AZAMI_SURE_AY:
        raise ServisGirdiHatasi(f"Sözleşme süresi 1 ile {AZAMI_SURE_AY} ay arasında olmalı")
    return bakim.ay_ekle(girdi.karar_tarihi, sure)


async def karar_uygula(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    girdi: KararGirdisi,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> dict[str, Any]:
    """Karar tarihini sözleşmeye işler, dönemleri hesaplar, geçmişi kapatır.

    Dönüş: `takvim_ozeti` (sözleşmenin dönem takvimi + kaç PB açılacağı).
    """
    if girdi.yapilan_adet is not None and girdi.yapilan_adet < 0:
        raise ServisGirdiHatasi("Yapılan bakım adedi negatif olamaz")
    bitis = _bitis(girdi)
    degisiklik: dict[str, Any] = {
        "valid_from": bakim.yerel_gece(girdi.karar_tarihi),
        "valid_to": bakim.yerel_gece(bitis),
    }
    if girdi.yillik_adet is not None:
        degisiklik["annual_frequency"] = girdi.yillik_adet
        if (
            girdi.sabit_aylar is None
            and sozlesme.fixed_months
            and (len(sozlesme.fixed_months) != girdi.yillik_adet)
        ):
            # Adet değişti, eski sabit aylar artık tutmuyor → eşit aralığa dön.
            degisiklik["fixed_months"] = None
    if girdi.sabit_aylar is not None:
        degisiklik["fixed_months"] = sorted(girdi.sabit_aylar) or None
    if (degisiklik.get("annual_frequency") or sozlesme.annual_frequency) is None:
        raise ServisGirdiHatasi("Yıllık bakım adedi girilmemiş; karar tarihiyle birlikte verin")

    await bakim.sozlesme_guncelle(db, sozlesme, degisiklik, user=user, clock=clock, ip=ip)
    eski_karar = sozlesme.decision_date
    if eski_karar != girdi.karar_tarihi:
        sozlesme.decision_date = girdi.karar_tarihi
        sozlesme.updated_by = user.id
        await audit.log(
            db,
            "maintenance_contracts",
            "bakim.sozlesme.karar_tarihi",
            entity_id=sozlesme.id,
            old_value={"decision_date": eski_karar.isoformat() if eski_karar else None},
            new_value={
                "decision_date": girdi.karar_tarihi.isoformat(),
                "bitis": bitis.isoformat(),
                "yapilan_adet": girdi.yapilan_adet,
            },
            user_id=user.id,
            ip=ip,
        )
        await db.flush()

    if girdi.aktiflestir and sozlesme.status in ("TASLAK", "TEYIT_BEKLIYOR"):
        await bakim.durum_degistir(db, sozlesme, "AKTIF", user=user, clock=clock, ip=ip)

    kapanan = 0
    if sozlesme.status == "AKTIF":
        donemler = await bakim.donemleri_hesapla(db, sozlesme, clock)
        kapanan = await _gecmisi_kapat(db, sozlesme, donemler, girdi.yapilan_adet, clock, user, ip)
    ozet = await takvim_ozeti(db, sozlesme, clock)
    ozet["sistem_oncesi_kapanan"] = kapanan
    return ozet


async def _pbli_donemler(db: AsyncSession, donem_idleri: list[int]) -> dict[int, tuple[int, int]]:
    """dönem → (toplam PB, açık PB)."""
    if not donem_idleri:
        return {}
    satirlar = (
        await db.execute(
            select(
                ServiceOrder.maintenance_period_id,
                func.count(),
                func.count().filter(ServiceOrder.status.in_(sorted(bakim._ACIK))),
            )
            .where(
                ServiceOrder.tur == "PB",
                ServiceOrder.is_deleted.is_(False),
                ServiceOrder.maintenance_period_id.in_(donem_idleri),
            )
            .group_by(ServiceOrder.maintenance_period_id)
        )
    ).all()
    return {d: (int(t), int(a)) for d, t, a in satirlar}


async def _gecmisi_kapat(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    donemler: list[MaintenancePeriod],
    yapilan_adet: int | None,
    clock: Clock,
    user: User,
    ip: str | None,
) -> int:
    bugun = yerel_bugun(clock)
    pbli = await _pbli_donemler(db, [d.id for d in donemler])
    acik_gecmis = [
        d for d in donemler if d.closed_at is None and d.target_date < bugun and d.id not in pbli
    ]
    if not acik_gecmis:
        return 0
    dongu = bakim.guncel_dongu(list({d.cycle_start for d in donemler}), clock.now())
    onceki = [d for d in acik_gecmis if dongu is None or d.cycle_start < dongu]
    guncel = sorted(
        (d for d in acik_gecmis if d not in onceki), key=lambda d: (d.target_date, d.sequence_no)
    )
    # `yapilan_adet` güncel döngüdeki TOPLAM yapılan sayısıdır: daha önce sayılan
    # kapanışlar düşülür ki aynı giriş tekrarlanınca yeni dönem kapanmasın.
    sayilan = sum(
        1
        for d in donemler
        if dongu is not None
        and d.cycle_start == dongu
        and d.closing_kind in DONEM_SAYILAN_KAPANISLAR
    )
    kapat = onceki + guncel[: max((yapilan_adet or 0) - sayilan, 0)]
    for d in kapat:
        d.closed_at = clock.now()
        d.closing_kind = "GOC_BASLANGIC"
    if kapat:
        await audit.log(
            db,
            "maintenance_contracts",
            "bakim.donem.sistem_oncesi_kapat",
            entity_id=sozlesme.id,
            new_value={
                "donemler": [d.target_date.isoformat() for d in kapat],
                "yapilan_adet": yapilan_adet,
            },
            user_id=user.id,
            ip=ip,
        )
        await db.flush()
    return len(kapat)


async def _cihaz_sayilari(
    db: AsyncSession, sozlesme_idleri: list[int]
) -> dict[int, tuple[int, int]]:
    """sözleşme → (açık kalem, ekipmana bağlı kalem)."""
    if not sozlesme_idleri:
        return {}
    satirlar = (
        await db.execute(
            select(
                MaintenanceContractItem.contract_id,
                func.count(),
                func.count(MaintenanceContractItem.equipment_id),
            )
            .where(
                MaintenanceContractItem.contract_id.in_(sozlesme_idleri),
                MaintenanceContractItem.is_deleted.is_(False),
                MaintenanceContractItem.valid_to.is_(None),
            )
            .group_by(MaintenanceContractItem.contract_id)
        )
    ).all()
    return {s: (int(t), int(b)) for s, t, b in satirlar}


def _donem_durumu(
    d: MaintenancePeriod, pb: tuple[int, int] | None, bugun: date, on_acilis: int
) -> str:
    if d.closed_at is not None:
        return SISTEM_ONCESI if d.closing_kind == "GOC_BASLANGIC" else KAPANDI
    if pb and pb[0]:
        return PB_ACIK
    if d.target_date < bugun:
        return GECIKMIS
    if d.target_date - timedelta(days=on_acilis) <= bugun:
        return ILK_TURDA
    return ILERIDE


async def takvim_ozeti(
    db: AsyncSession, sozlesme: MaintenanceContract, clock: Clock
) -> dict[str, Any]:
    """Tek sözleşmenin dönem takvimi. Aktif değilse DB'ye yazmadan saf plan."""
    bugun = yerel_bugun(clock)
    on_acilis = int(await ayar_svc.get(db, "bakim_on_acilis_gun") or 0)
    toplam, bagli = (await _cihaz_sayilari(db, [sozlesme.id])).get(sozlesme.id, (0, 0))
    donem_satirlari: list[dict[str, Any]] = []
    if sozlesme.status == "AKTIF":
        donemler = (
            await db.scalars(
                select(MaintenancePeriod)
                .where(
                    MaintenancePeriod.contract_id == sozlesme.id,
                    MaintenancePeriod.is_deleted.is_(False),
                )
                .order_by(MaintenancePeriod.target_date, MaintenancePeriod.sequence_no)
            )
        ).all()
        pbler = await _pbli_donemler(db, [d.id for d in donemler])
        for d in donemler:
            durum = _donem_durumu(d, pbler.get(d.id), bugun, on_acilis)
            donem_satirlari.append(
                {
                    "donem_id": d.id,
                    "dongu_baslangici": yerel_gun(d.cycle_start).isoformat(),
                    "sira": d.sequence_no,
                    "hedef": d.target_date.isoformat(),
                    "ay": d.target_date.strftime("%Y-%m"),
                    "pb_acilis": max(d.target_date - timedelta(days=on_acilis), bugun).isoformat()
                    if durum in (ILERIDE, ILK_TURDA, GECIKMIS)
                    else None,
                    "durum": durum,
                    "pb_sayisi": (pbler.get(d.id) or (0, 0))[0],
                }
            )
    elif sozlesme.valid_from and sozlesme.valid_to and sozlesme.annual_frequency:
        plan = bakim.donem_plani(
            yerel_gun(sozlesme.valid_from),
            yerel_gun(sozlesme.valid_to),
            sozlesme.annual_frequency,
            sozlesme.fixed_months,
        )
        for dongu, sira, hedef in plan:
            donem_satirlari.append(
                {
                    "donem_id": None,
                    "dongu_baslangici": dongu.isoformat(),
                    "sira": sira,
                    "hedef": hedef.isoformat(),
                    "ay": hedef.strftime("%Y-%m"),
                    "pb_acilis": None,
                    "durum": TASLAK_PLAN,
                    "pb_sayisi": 0,
                }
            )
    ilk_tur_donem = sum(1 for s in donem_satirlari if s["durum"] in (GECIKMIS, ILK_TURDA))
    return {
        "sozlesme_id": sozlesme.id,
        "contract_no": sozlesme.contract_no,
        "status": sozlesme.status,
        "karar_tarihi": sozlesme.decision_date.isoformat() if sozlesme.decision_date else None,
        "baslangic": yerel_gun(sozlesme.valid_from).isoformat() if sozlesme.valid_from else None,
        "bitis": yerel_gun(sozlesme.valid_to).isoformat() if sozlesme.valid_to else None,
        "annual_frequency": sozlesme.annual_frequency,
        "fixed_months": sozlesme.fixed_months,
        "cihaz_sayisi": toplam,
        "eslesen_cihaz": bagli,
        "on_acilis_gun": on_acilis,
        "donemler": donem_satirlari,
        "gecikmis_donem": sum(1 for s in donem_satirlari if s["durum"] == GECIKMIS),
        # Cihaz başına 1 PB: ilk üretim turunda açılacak iş sayısı (yalnız bağlı cihaz).
        "ilk_turda_pb": ilk_tur_donem * bagli,
    }


async def _sozlesme_bul(
    db: AsyncSession, user: User, sozlesme_id: int | None, contract_no: str | None
) -> MaintenanceContract:
    if sozlesme_id is None:
        no = (contract_no or "").strip()
        if not no:
            raise ServisGirdiHatasi("Sözleşme kimliği ya da numarası verilmeli")
        sozlesme_id = await db.scalar(
            select(MaintenanceContract.id).where(
                MaintenanceContract.contract_no == no, MaintenanceContract.is_deleted.is_(False)
            )
        )
        if sozlesme_id is None:
            raise BakimKapsamDisi("Sözleşme bulunamadı")
    return await bakim.kapsamli_sozlesme(db, user, sozlesme_id, kilitle=True)


async def toplu_uygula(
    db: AsyncSession,
    satirlar: list[tuple[int | None, str | None, KararGirdisi]],
    *,
    user: User,
    clock: Clock,
    onizleme: bool,
    ip: str | None = None,
) -> dict[str, Any]:
    """Her satır kendi SAVEPOINT'inde; `onizleme` iken her şey geri alınır."""
    if not satirlar:
        raise ServisGirdiHatasi("En az bir satır gönderin")
    if len(satirlar) > AZAMI_TOPLU_SATIR:
        raise ServisGirdiHatasi(f"Bir seferde en çok {AZAMI_TOPLU_SATIR} sözleşme")
    dis = await db.begin_nested() if onizleme else None
    sonuc: list[dict[str, Any]] = []
    try:
        for sira, (sozlesme_id, contract_no, girdi) in enumerate(satirlar, start=1):
            try:
                async with db.begin_nested():
                    sozlesme = await _sozlesme_bul(db, user, sozlesme_id, contract_no)
                    ozet = await karar_uygula(db, sozlesme, girdi, user=user, clock=clock, ip=ip)
                    musteri = (
                        await db.get(Account, sozlesme.account_id) if sozlesme.account_id else None
                    )
                    tesis = (
                        await db.get(Address, sozlesme.address_id) if sozlesme.address_id else None
                    )
                    ozet["musteri"] = musteri.title if musteri else sozlesme.customer_name_raw
                    ozet["tesis"] = (
                        (tesis.site_name or tesis.label) if tesis else sozlesme.site_name_raw
                    )
                    sonuc.append({"sira": sira, "sonuc": "TAMAM", "hata": None, **ozet})
            except _SATIR_HATALARI as exc:
                hata = _hata_metni(exc)
                veri = getattr(exc, "veri", None)
                if isinstance(veri, dict) and veri.get("kod"):
                    hata = f"{hata} ({veri['kod']})"
                sonuc.append(
                    {
                        "sira": sira,
                        "sonuc": "HATA",
                        "hata": hata,
                        "sozlesme_id": sozlesme_id,
                        "contract_no": contract_no,
                    }
                )
    finally:
        if dis is not None:
            await dis.rollback()
    tamam = [s for s in sonuc if s["sonuc"] == "TAMAM"]
    return {
        "onizleme": onizleme,
        "satirlar": sonuc,
        "ozet": {
            "tamam": len(tamam),
            "hata": len(sonuc) - len(tamam),
            "donem": sum(len(s["donemler"]) for s in tamam),
            "ilk_turda_pb": sum(s["ilk_turda_pb"] for s in tamam),
            "gecikmis_donem": sum(s["gecikmis_donem"] for s in tamam),
            "sistem_oncesi_kapanan": sum(s["sistem_oncesi_kapanan"] for s in tamam),
        },
    }


# =============================================================================
# Yıllık bakım takvimi (planlama görünümü)
# =============================================================================


async def yillik_takvim(
    db: AsyncSession, user: User, clock: Clock, *, yil: int, birim: str | None = None
) -> dict[str, Any]:
    """Aktif sözleşmelerin `yil` içindeki dönemleri: sözleşme (müşteri/tesis)
    satırı × 12 ay. Kapsam `bakim.donem_kapsami` (birim + müşteri)."""
    bas, bit = date(yil, 1, 1), date(yil + 1, 1, 1)
    stmt = (
        select(MaintenancePeriod, MaintenanceContract)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .where(
            MaintenancePeriod.is_deleted.is_(False),
            MaintenanceContract.is_deleted.is_(False),
            MaintenanceContract.status == "AKTIF",
            MaintenancePeriod.target_date >= bas,
            MaintenancePeriod.target_date < bit,
        )
    )
    if birim:
        stmt = stmt.where(MaintenanceContract.birim == birim)
    stmt = bakim.donem_kapsami(stmt, user).order_by(
        MaintenancePeriod.target_date, MaintenancePeriod.sequence_no
    )
    kayitlar = (await db.execute(stmt)).all()
    bugun = yerel_bugun(clock)
    on_acilis = int(await ayar_svc.get(db, "bakim_on_acilis_gun") or 0)
    pbler = await _pbli_donemler(db, [d.id for d, _ in kayitlar])
    sozlesmeler = {s.id: s for _, s in kayitlar}
    cihazlar = await _cihaz_sayilari(db, list(sozlesmeler))
    hesaplar = {
        a.id: a.title
        for a in (
            await db.scalars(
                select(Account).where(
                    Account.id.in_([s.account_id for s in sozlesmeler.values() if s.account_id])
                )
            )
        ).all()
    }
    tesisler = {
        a.id: a
        for a in (
            await db.scalars(
                select(Address).where(
                    Address.id.in_([s.address_id for s in sozlesmeler.values() if s.address_id])
                )
            )
        ).all()
    }
    satirlar: dict[int, dict[str, Any]] = {}
    aylar = [{"ay": m, "donem": 0, "cihaz": 0} for m in range(1, 13)]
    for d, s in kayitlar:
        satir = satirlar.get(s.id)
        if satir is None:
            tesis = tesisler.get(s.address_id) if s.address_id else None
            toplam, bagli = cihazlar.get(s.id, (0, 0))
            satir = satirlar[s.id] = {
                "sozlesme_id": s.id,
                "contract_no": s.contract_no,
                "birim": s.birim,
                "account_id": s.account_id,
                "musteri": hesaplar.get(s.account_id) or s.customer_name_raw,
                "address_id": s.address_id,
                "tesis": (tesis.site_name or tesis.label) if tesis else s.site_name_raw,
                "il": tesis.city if tesis else None,
                "karar_tarihi": s.decision_date.isoformat() if s.decision_date else None,
                "annual_frequency": s.annual_frequency,
                "cihaz_sayisi": toplam,
                "eslesen_cihaz": bagli,
                "aylar": {str(m): [] for m in range(1, 13)},
            }
        durum = _donem_durumu(d, pbler.get(d.id), bugun, on_acilis)
        satir["aylar"][str(d.target_date.month)].append(
            {
                "donem_id": d.id,
                "hedef": d.target_date.isoformat(),
                "durum": durum,
                "pb_sayisi": (pbler.get(d.id) or (0, 0))[0],
                "acik_pb": (pbler.get(d.id) or (0, 0))[1],
            }
        )
        ay = aylar[d.target_date.month - 1]
        ay["donem"] += 1
        ay["cihaz"] += satir["eslesen_cihaz"]
    sirali = sorted(
        satirlar.values(),
        key=lambda r: ((r["musteri"] or ""), (r["tesis"] or ""), r["contract_no"]),
    )
    return {"yil": yil, "on_acilis_gun": on_acilis, "aylar": aylar, "satirlar": sirali}
