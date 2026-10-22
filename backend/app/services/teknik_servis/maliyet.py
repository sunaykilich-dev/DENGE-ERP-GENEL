"""İş bazlı maliyet ve gelir: tarife, işçilik, parça maliyeti, analiz (E07).

Maddeler: TS-145 (gelir/diğer maliyet, NULL ≠ 0, fatura kilidi), TS-146 (eksik
veri ayrımı, işçilik tarifesi), TS-147 (kabul edilen teklifin gelire aktarımı,
PB bulgusu düzeltici işi), TS-149 (analiz). Doldurdu: D2-E.

**Tek kaynak `is_finansi_toplu`:** iş detayı, analiz satırı, birim × tür özeti
ve KPI kutuları aynı hesaptan toplanır; özet toplamı detayın tam satırlarının
toplamıdır (E07-21).

**Eksik veri 0 değildir (E07-10/11):**
- İşçilik = MOLA hariç (`KISI_SAATE_DAHIL`, E09 sözlüğü — `ISCILIK` yok, KD-24)
  iptal edilmemiş KAPALI bölümlerin süresi × bölümün YEREL başlangıç
  tarihinde geçerli birim tarifesi. Bölüm yoksa, açık bölüm varsa ya da
  atanmış teknisyenlerden birinin bölümü yoksa (zaman modülünün KISMI'si)
  `SURE_EKSIK`; bölümlerden birinin tarifesi yoksa işin TAMAMI `TARIFE_EKSIK`
  (kısmi toplam verilmez). Tahmini süre hiçbir koşulda yerine konmaz.
- Malzeme = servis defterindeki net çıkış (`CIKIS_SERVIS − IADE_SERVIS`, ters
  kayıtlar dahil) × hareket anında dondurulan `unit_cost` (E11, KD-25). Hareket
  yoksa 0 ve tamdır (`YOK`); maliyeti NULL olan hareket varsa `MALIYET_EKSIK`.
- Gelir satırı yoksa ya da NULL ise "gelir kaydı yok"; PB işinde gelir yoksa
  "sözleşme kapsamı" (sözleşme bedeli işlere dağıtılmaz, K9) — fark
  hesaplanmaz ve ayrı sayaçta gösterilir.
- `fark` yalnız bütün bileşenler tamsa hesaplanır; toplamlara yalnız tam işler
  girer, eksikler ayrı sayaçlarda döner.

**Fatura kilidi (E07-D04):** `fatura_iletildi_at` doluyken gelir, diğer
maliyet, teklif gelir aktarımı (ikinci kabul ya da iptal) 409'dur.

**PB bulgusu teklifi (kontrol K9 çözümü, TS-147):** bakım (PB) işine bağlı
kalem KABUL'de PB işine gelir YAZMAZ; PB'ye `DEVAM` ilişkili düzeltici servis
işi (PLANSIZ_BAKIM) açılır ve gelir o işe aktarılır. PB işi yalnız teklifin
kaynağı kalır; bakım ziyaretinin işçiliği henüz yapılmamış düzeltmenin
geliriyle karşılaştırılmaz.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import exists, func, or_, select

from app.models import (
    Account,
    AuditLog,
    Quote,
    QuoteLine,
    QuoteVersion,
    ServiceHold,
    ServiceLaborRate,
    ServiceOrder,
    ServiceOrderEvent,
    ServiceTimeEntry,
    StockMovement,
    User,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.servis_maliyet import GELIR_KAYNAKLARI, MALIYET_DURUMLARI, ServiceOrderFinancial
from app.models.teknik_servis import DURUM_GRUPLARI, KISI_SAATE_DAHIL
from app.services import audit
from app.services.quotes import yuvarla
from app.services.teknik_servis import kapsam
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun, yerel_gun_araligi
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

__all__ = ["GELIR_KAYNAKLARI", "MALIYET_DURUMLARI"]


class MaliyetHatasi(ServisHatasi):
    """Maliyet kuralı ihlali (fatura kilidi, çakışan tarife ...) → 409."""


class MaliyetGirdiHatasi(ServisGirdiHatasi):
    """Girdi hatası (eksik not, geçmiş tarih yetkisi ...) → 400."""


FATURA_KILIDI_MESAJI = "İş faturaya iletildi; önce devri geri alın"
# Maliyetin hesaplandığı işler: çözülmüş (TAMAMLANDI/KAPATILDI) işler.
ANALIZ_DURUMLARI = DURUM_GRUPLARI["COZULDU"]
# Analiz KPI/süzgeç kodları (satır bayraklarından; birbirini dışlamaz).
ANALIZ_SUZGECLERI = (
    "TAM",
    "SURE_EKSIK",
    "TARIFE_EKSIK",
    "MALIYET_EKSIK",
    "GELIR_YOK",
    "SOZLESME_KAPSAMI",
)
ELLE_KAYNAKLAR = ("ELLE", "UCRETSIZ_GARANTI", "SOZLESME")
NOT_UZUNLUGU = 1000
AZAMI_AY = 12
DUZELTICI_TUR = "PLANSIZ_BAKIM"
_GELIR_EYLEMI = {
    "ELLE": "gelir.elle",
    "UCRETSIZ_GARANTI": "gelir.ucretsiz",
    "SOZLESME": "gelir.sozlesme",
    "TEKLIF": "gelir.teklif",
    "YOK": "gelir.temizle",
}


# --- İşçilik tarifesi (TS-146, E07-20) -----------------------------------------------


def tarife_gecerli_mi(tarife: ServiceLaborRate, gun: date) -> bool:
    """Yarı açık aralık `[valid_from, valid_to)`; `valid_to = valid_from` boş aralık."""
    return tarife.valid_from <= gun and (tarife.valid_to is None or gun < tarife.valid_to)


async def tarifeler(
    db: AsyncSession, user: User, birim: str | None = None
) -> list[ServiceLaborRate]:
    """Kullanıcının birimlerinin tarifeleri (TUMU: hepsi), yeni → eski."""
    if birim is not None and birim not in BIRIM_KODLARI:
        raise MaliyetGirdiHatasi(f"Bilinmeyen birim: {birim}")
    stmt = select(ServiceLaborRate).order_by(
        ServiceLaborRate.birim, ServiceLaborRate.valid_from.desc(), ServiceLaborRate.id.desc()
    )
    stmt = kapsam.kapsam_birim(stmt, user, ServiceLaborRate.birim, birimsiz_gorunur=False)
    if birim is not None:
        stmt = stmt.where(ServiceLaborRate.birim == birim)
    return list((await db.scalars(stmt)).all())


async def tarife_ekle(
    db: AsyncSession,
    *,
    birim: str,
    valid_from: date,
    hourly_cost: Decimal,
    gerekce: str | None,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceLaborRate:
    """Yeni tarife; aynı birimin açık satırı `valid_to = valid_from` ile kapanır.

    - birim kapsam dışı → `kapsam` (API 404);
    - geçmiş tarih yalnız `sistem.ayar` + gerekçe (aksi 400; kapatılmış dönemin
      analizi geriye dönük değişir, ekranda uyarılır);
    - başlangıcı açık satırınkinden önce/eşit → 409; çakışma (`ex_`) → 409.
    """
    if birim not in BIRIM_KODLARI:
        raise MaliyetGirdiHatasi(f"Bilinmeyen birim: {birim}")
    if kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        raise LookupError("Birim bulunamadı")
    if hourly_cost is None or Decimal(str(hourly_cost)) <= 0:
        raise MaliyetGirdiHatasi("Saatlik maliyet sıfırdan büyük olmalı")
    gerekce = (gerekce or "").strip() or None
    if gerekce is not None and len(gerekce) > 300:
        raise MaliyetGirdiHatasi("Gerekçe en çok 300 karakter olabilir")
    bugun = yerel_bugun(clock)
    if valid_from < bugun:
        if not user.has("sistem.ayar"):
            raise MaliyetGirdiHatasi(
                "Geçmiş tarihli tarife yalnız sistem ayarı yetkisiyle ve gerekçeyle girilir"
            )
        if gerekce is None:
            raise MaliyetGirdiHatasi("Geçmiş tarihli tarifede gerekçe zorunlu")
    acik = await db.scalar(
        select(ServiceLaborRate).where(
            ServiceLaborRate.birim == birim, ServiceLaborRate.valid_to.is_(None)
        )
    )
    if acik is not None:
        if valid_from <= acik.valid_from:
            raise MaliyetHatasi(
                f"Yeni tarife açık tarifenin başlangıcından ({acik.valid_from:%d.%m.%Y}) "
                "sonra başlamalı"
            )
        acik.valid_to = valid_from
        acik.updated_by = user.id
        await audit.log_change(db, acik, "tarife.kapat", user_id=user.id, ip=ip)
        await db.flush()
    yeni = ServiceLaborRate(
        birim=birim,
        valid_from=valid_from,
        hourly_cost=yuvarla(Decimal(str(hourly_cost))),
        gerekce=gerekce,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(yeni)
    await db.flush()
    await audit.log(
        db,
        "service_labor_rates",
        "tarife.ekle",
        entity_id=yeni.id,
        new_value={
            "birim": birim,
            "valid_from": valid_from.isoformat(),
            "hourly_cost": str(yeni.hourly_cost),
            "not": gerekce,
        },
        user_id=user.id,
        ip=ip,
    )
    return yeni


async def tarife_kapat(
    db: AsyncSession,
    tarife: ServiceLaborRate,
    *,
    gerekce: str | None,
    version: int,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceLaborRate:
    """Henüz başlamamış (hatalı ileri tarihli) tarifeyi `valid_to = valid_from`
    ile kapatır; silme yok (B8). Öncülünü bu tarife kapatmışsa öncül yeniden
    açılır (boşluk kalmasın)."""
    gerekce = (gerekce or "").strip()
    if len(gerekce) < 5:
        raise MaliyetGirdiHatasi("Kapatma gerekçesi en az 5 karakter olmalı")
    if version != tarife.version:
        raise MaliyetHatasi("Tarife başka biri tarafından değiştirildi; yenileyin")
    if tarife.valid_from <= yerel_bugun(clock):
        raise MaliyetHatasi("Yalnız henüz başlamamış tarife kapatılabilir")
    if tarife.valid_to is not None and tarife.valid_to == tarife.valid_from:
        raise MaliyetHatasi("Tarife zaten kapatılmış")
    oncul = await db.scalar(
        select(ServiceLaborRate).where(
            ServiceLaborRate.birim == tarife.birim,
            ServiceLaborRate.valid_to == tarife.valid_from,
            ServiceLaborRate.id != tarife.id,
        )
    )
    tarife.valid_to = tarife.valid_from
    tarife.gerekce = gerekce[:300]
    tarife.updated_by = user.id
    await audit.log_change(db, tarife, "tarife.kapat", user_id=user.id, ip=ip)
    await db.flush()
    if oncul is not None:
        sonraki = await db.scalar(
            select(func.count()).where(
                ServiceLaborRate.birim == tarife.birim,
                ServiceLaborRate.valid_from > tarife.valid_from,
                or_(
                    ServiceLaborRate.valid_to.is_(None),
                    ServiceLaborRate.valid_to > ServiceLaborRate.valid_from,
                ),
            )
        )
        if not sonraki:
            oncul.valid_to = None
            oncul.updated_by = user.id
            await audit.log_change(db, oncul, "tarife.yeniden_ac", user_id=user.id, ip=ip)
            await db.flush()
    return tarife


# --- İş finansı (TS-145/146) ---------------------------------------------------------


@dataclass
class IsFinansi:
    so_id: int
    sure_dk: int | None
    iscilik: Decimal | None
    iscilik_durumu: str  # TAM | SURE_EKSIK | TARIFE_EKSIK
    malzeme: Decimal | None
    malzeme_durumu: str  # TAM | YOK | MALIYET_EKSIK
    diger: Decimal  # NULL → 0 (tam sayılır)
    diger_maliyet: Decimal | None  # ham değer (ekranda "—")
    gelir: Decimal | None
    gelir_kaynagi: str | None
    gelir_durumu: str  # KAYIT_YOK | SOZLESME_KAPSAMI | TEKLIF | ELLE | SOZLESME | UCRETSIZ_GARANTI
    fark: Decimal | None
    fark_durumu: str  # HESAPLANDI | HESAPLANAMADI
    durum: (
        str  # özet: TAM | SURE_EKSIK | TARIFE_EKSIK | MALIYET_EKSIK | GELIR_YOK | SOZLESME_KAPSAMI
    )
    fatura_iletildi_at: datetime | None
    finans_version: int | None

    def sozluk(self) -> dict[str, Any]:
        return asdict(self)

    def suzgec_mi(self, kod: str) -> bool:
        if kod == "TAM":
            return self.fark is not None
        if kod == "SURE_EKSIK":
            return self.iscilik_durumu == "SURE_EKSIK"
        if kod == "TARIFE_EKSIK":
            return self.iscilik_durumu == "TARIFE_EKSIK"
        if kod == "MALIYET_EKSIK":
            return self.malzeme_durumu == "MALIYET_EKSIK"
        if kod == "GELIR_YOK":
            return self.gelir_durumu == "KAYIT_YOK"
        if kod == "SOZLESME_KAPSAMI":
            return self.gelir_durumu == "SOZLESME_KAPSAMI"
        return False


def _ozet_durumu(iscilik_durumu: str, malzeme_durumu: str, gelir_durumu: str) -> str:
    if iscilik_durumu != "TAM":
        return iscilik_durumu
    if malzeme_durumu == "MALIYET_EKSIK":
        return "MALIYET_EKSIK"
    if gelir_durumu == "KAYIT_YOK":
        return "GELIR_YOK"
    if gelir_durumu == "SOZLESME_KAPSAMI":
        return "SOZLESME_KAPSAMI"
    return "TAM"


async def is_finansi_toplu(db: AsyncSession, so_idler: list[int]) -> dict[int, IsFinansi]:
    """İş başına finans; toplu sorgu (N+1 yok). Saat bilgisi kayıtlardan gelir."""
    from app.services.teknik_servis import zaman

    idler = sorted({int(i) for i in so_idler})
    if not idler:
        return {}
    isler = {
        so_id: (birim, tur)
        for so_id, birim, tur in (
            await db.execute(
                select(ServiceOrder.id, ServiceOrder.birim, ServiceOrder.tur).where(
                    ServiceOrder.id.in_(idler)
                )
            )
        ).all()
    }
    # İşçilik: kişi-saate dahil, iptal edilmemiş bölümler.
    bolumler = (
        await db.execute(
            select(
                ServiceTimeEntry.service_order_id,
                ServiceTimeEntry.started_at,
                ServiceTimeEntry.ended_at,
            ).where(
                ServiceTimeEntry.service_order_id.in_(idler),
                zaman.gecerli_bolum(),
                ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
            )
        )
    ).all()
    sure_ozetleri = await zaman.sure_ozeti_toplu(db, idler)
    birimler = {b for b, _ in isler.values()}
    tarife_listesi: dict[str, list[ServiceLaborRate]] = defaultdict(list)
    for t in (
        await db.scalars(select(ServiceLaborRate).where(ServiceLaborRate.birim.in_(birimler)))
    ).all():
        tarife_listesi[t.birim].append(t)

    sure_sn: dict[int, float] = defaultdict(float)
    iscilik_tl: dict[int, Decimal] = defaultdict(Decimal)
    tarifesiz: set[int] = set()
    acik: set[int] = set()
    bolum_var: set[int] = set()
    for so_id, bas, bit in bolumler:
        bolum_var.add(so_id)
        if bit is None:
            acik.add(so_id)
            continue
        saniye = (bit - bas).total_seconds()
        sure_sn[so_id] += saniye
        gun = yerel_gun(bas)
        birim = isler[so_id][0]
        tarife = next((t for t in tarife_listesi[birim] if tarife_gecerli_mi(t, gun)), None)
        if tarife is None:
            tarifesiz.add(so_id)
            continue
        iscilik_tl[so_id] += Decimal(str(saniye)) / Decimal("3600") * tarife.hourly_cost

    # Malzeme: servis defterinin işe yazılan hareketleri (ters kayıt dahil).
    malzeme_tl: dict[int, Decimal] = defaultdict(Decimal)
    malzeme_eksik: set[int] = set()
    malzeme_var: set[int] = set()
    for so_id, adet, birim_maliyet in (
        await db.execute(
            select(
                StockMovement.service_order_id, StockMovement.qty, StockMovement.unit_cost
            ).where(
                StockMovement.service_order_id.in_(idler),
                StockMovement.hareket_turu.in_(("CIKIS_SERVIS", "IADE_SERVIS", "TERS_KAYIT")),
            )
        )
    ).all():
        malzeme_var.add(so_id)
        if birim_maliyet is None:
            malzeme_eksik.add(so_id)
            continue
        # Çıkış eksi adetlidir: maliyet = −adet × birim maliyet (iade düşer).
        malzeme_tl[so_id] += -Decimal(int(adet)) * Decimal(str(birim_maliyet))

    finanslar = {
        f.service_order_id: f
        for f in (
            await db.scalars(
                select(ServiceOrderFinancial).where(
                    ServiceOrderFinancial.service_order_id.in_(idler)
                )
            )
        ).all()
    }

    sonuc: dict[int, IsFinansi] = {}
    for so_id in idler:
        if so_id not in isler:
            continue
        _, tur = isler[so_id]
        ozet = sure_ozetleri.get(so_id)
        sure_eksik = (
            so_id not in bolum_var
            or so_id in acik
            or ozet is None
            or ozet.kisi_saat_dk is None
            or ozet.sure_durumu in ("EKSIK", "KISMI")
        )
        if sure_eksik:
            iscilik, iscilik_durumu = None, "SURE_EKSIK"
        elif so_id in tarifesiz:
            iscilik, iscilik_durumu = None, "TARIFE_EKSIK"
        else:
            iscilik, iscilik_durumu = yuvarla(iscilik_tl[so_id]), "TAM"
        if so_id in malzeme_eksik:
            malzeme, malzeme_durumu = None, "MALIYET_EKSIK"
        elif so_id in malzeme_var:
            malzeme, malzeme_durumu = yuvarla(malzeme_tl[so_id]), "TAM"
        else:
            malzeme, malzeme_durumu = Decimal("0.00"), "YOK"
        fin = finanslar.get(so_id)
        diger_ham = fin.diger_maliyet if fin is not None else None
        diger = Decimal(str(diger_ham)) if diger_ham is not None else Decimal("0.00")
        gelir = fin.gelir if fin is not None else None
        kaynak = fin.gelir_kaynagi if fin is not None else None
        if gelir is None:
            gelir_durumu = "SOZLESME_KAPSAMI" if tur == "PB" else "KAYIT_YOK"
        else:
            gelir_durumu = kaynak or "ELLE"
        fark = None
        if iscilik is not None and malzeme is not None and gelir is not None:
            fark = yuvarla(Decimal(str(gelir)) - (malzeme + iscilik + diger))
        sonuc[so_id] = IsFinansi(
            so_id=so_id,
            sure_dk=round(sure_sn[so_id] / 60) if so_id in bolum_var and not sure_eksik else None,
            iscilik=iscilik,
            iscilik_durumu=iscilik_durumu,
            malzeme=malzeme,
            malzeme_durumu=malzeme_durumu,
            diger=yuvarla(diger),
            diger_maliyet=diger_ham,
            gelir=gelir,
            gelir_kaynagi=kaynak,
            gelir_durumu=gelir_durumu,
            fark=fark,
            fark_durumu="HESAPLANDI" if fark is not None else "HESAPLANAMADI",
            durum=_ozet_durumu(iscilik_durumu, malzeme_durumu, gelir_durumu),
            fatura_iletildi_at=fin.fatura_iletildi_at if fin is not None else None,
            finans_version=fin.version if fin is not None else None,
        )
    return sonuc


async def is_finansi(db: AsyncSession, so: Any, clock: Clock | None = None) -> dict[str, Any]:
    """Tek kaynak: işçilik + malzeme + diğer, durum TAM/SURE_EKSIK/MALIYET_EKSIK/TARIFE_EKSIK."""
    return (await is_finansi_toplu(db, [so.id]))[so.id].sozluk()


# --- Gelir / diğer maliyet yazımı (TS-145) ---------------------------------------------


async def _finans(db: AsyncSession, so_id: int) -> ServiceOrderFinancial | None:
    return await db.scalar(
        select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so_id)
    )


async def _finans_ac(db: AsyncSession, so_id: int, user_id: int | None) -> ServiceOrderFinancial:
    """Satır ilk yazımda açılır (boş); eşzamanlı ikinci açılış `uq_sof_is` → 409."""
    fin = await _finans(db, so_id)
    if fin is None:
        fin = ServiceOrderFinancial(service_order_id=so_id, created_by=user_id, updated_by=user_id)
        db.add(fin)
        await db.flush()
    return fin


def _kilit(fin: ServiceOrderFinancial | None) -> None:
    if fin is not None and fin.fatura_iletildi_at is not None:
        raise MaliyetHatasi(FATURA_KILIDI_MESAJI)


def _metin(deger: str | None, ad: str) -> str | None:
    metin = (deger or "").strip() or None
    if metin is not None and len(metin) > NOT_UZUNLUGU:
        raise MaliyetGirdiHatasi(f"{ad} en çok {NOT_UZUNLUGU} karakter olabilir")
    return metin


async def gelir_yaz(
    db: AsyncSession,
    so: Any,
    veri: Any,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceOrderFinancial | None:
    """`maliyet.yaz`; NULL ≠ 0; fatura devrinden sonra 409; log_change.

    `veri`: `kaynak` (ELLE | UCRETSIZ_GARANTI | SOZLESME | TEKLIF | YOK),
    `tutar`, `not_`, `version`. UCRETSIZ_GARANTI tutarı 0'a zorlar; ELLE ve
    UCRETSIZ_GARANTI notsuz 400 (DB `ck_` ikinci savunma). TEKLIF = elle
    girişi bırakıp kabul edilmiş tekliflerin tutarına dön; YOK = kaydı sil
    (gelir girilmedi). Doğrulama yazmadan ÖNCE: reddedilen istek denetim izi
    bırakmaz (E07-17 kabul 3).
    """
    kaynak = veri.kaynak
    tutar = veri.tutar
    not_ = _metin(veri.not_, "Not")
    if kaynak not in (*ELLE_KAYNAKLAR, "TEKLIF", "YOK"):
        raise MaliyetGirdiHatasi(f"Bilinmeyen gelir kaynağı: {kaynak}")
    if kaynak == "UCRETSIZ_GARANTI":
        tutar = Decimal("0")
    if kaynak in ("ELLE", "SOZLESME"):
        if tutar is None:
            raise MaliyetGirdiHatasi("Gelir tutarı zorunlu")
        if Decimal(str(tutar)) < 0:
            raise MaliyetGirdiHatasi("Gelir eksi olamaz")
    if kaynak in ("ELLE", "UCRETSIZ_GARANTI") and not_ is None:
        raise MaliyetGirdiHatasi("Elle ve ücretsiz-garanti gelirinde not zorunlu")
    fin = await _finans(db, so.id)
    _kilit(fin)
    if fin is not None and veri.version is not None and veri.version != fin.version:
        raise MaliyetHatasi("Kayıt başka biri tarafından değiştirildi; yenileyin")
    if kaynak == "TEKLIF":
        tutar_, adlar = await _teklif_geliri(db, so.id)
        if fin is None and tutar_ is None:
            return None
        fin = await _finans_ac(db, so.id, user.id)
        fin.gelir = tutar_
        fin.gelir_kaynagi = "TEKLIF" if tutar_ is not None else None
        fin.gelir_notu = ("Kabul edilen teklif: " + ", ".join(adlar)) if adlar else None
    elif kaynak == "YOK":
        if fin is None:
            return None
        fin.gelir = None
        fin.gelir_kaynagi = None
        fin.gelir_notu = not_
    else:
        fin = await _finans_ac(db, so.id, user.id)
        fin.gelir = yuvarla(Decimal(str(tutar)))
        fin.gelir_kaynagi = kaynak
        fin.gelir_notu = not_
    fin.updated_by = user.id
    await audit.log_change(db, fin, _GELIR_EYLEMI[kaynak], user_id=user.id, ip=ip)
    await db.flush()
    return fin


async def diger_maliyet_yaz(
    db: AsyncSession,
    so: Any,
    *,
    tutar: Decimal | None,
    not_: str | None,
    version: int | None,
    user: User,
    ip: str | None = None,
) -> ServiceOrderFinancial | None:
    """Diğer maliyet (konaklama, dış hizmet ...). Tutar varsa not zorunlu."""
    not_ = _metin(not_, "Not")
    if tutar is not None and Decimal(str(tutar)) < 0:
        raise MaliyetGirdiHatasi("Diğer maliyet eksi olamaz")
    if tutar is not None and not_ is None:
        raise MaliyetGirdiHatasi("Diğer maliyette açıklama zorunlu")
    fin = await _finans(db, so.id)
    _kilit(fin)
    if fin is not None and version is not None and version != fin.version:
        raise MaliyetHatasi("Kayıt başka biri tarafından değiştirildi; yenileyin")
    if fin is None and tutar is None:
        return None
    fin = await _finans_ac(db, so.id, user.id)
    fin.diger_maliyet = yuvarla(Decimal(str(tutar))) if tutar is not None else None
    fin.diger_maliyet_notu = not_ if tutar is not None else None
    fin.updated_by = user.id
    await audit.log_change(db, fin, "diger.guncelle", user_id=user.id, ip=ip)
    await db.flush()
    return fin


async def gelir_gecmisi(db: AsyncSession, so: Any) -> list[dict[str, Any]]:
    """Gelir/maliyet değişiklik geçmişi (E07-17) — ayrı tablo yok, `audit_logs`."""
    fin = await _finans(db, so.id)
    if fin is None:
        return []
    satirlar = (
        await db.execute(
            select(AuditLog, User.full_name)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(
                AuditLog.entity == "service_order_financials",
                AuditLog.entity_id == str(fin.id),
            )
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    ).all()
    return [
        {
            "zaman": k.created_at,
            "eylem": k.action,
            "kullanici": ad if k.user_id else None,
            "eski": k.old_value or {},
            "yeni": k.new_value or {},
        }
        for k, ad in satirlar
    ]


# --- Teklif → gelir (TS-147, E07-16) -----------------------------------------------------


async def duzeltici_bul(db: AsyncSession, teklif_id: int, pb_id: int) -> int | None:
    """Teklif + PB işi için açılmış düzeltici iş (TEKLIF olayının işareti)."""
    return await db.scalar(
        select(ServiceOrderEvent.service_order_id)
        .where(
            ServiceOrderEvent.olay_turu == "TEKLIF",
            ServiceOrderEvent.veri["kaynak_teklif_id"].astext == str(teklif_id),
            ServiceOrderEvent.veri["pb_is_id"].astext == str(pb_id),
        )
        .limit(1)
    )


async def _kalem_isleri(db: AsyncSession, t: Quote) -> list[tuple[int, Decimal]]:
    """Güncel sürümün (kalemin ham iş kimliği, TL net) çiftleri."""
    v = await db.get(QuoteVersion, t.current_version_id) if t.current_version_id else None
    if v is None:
        return []
    kur = Decimal("1")
    if v.currency != "TRY":
        kur = Decimal(str(v.fx_rate)) if v.fx_rate is not None else Decimal("1")
    sonuc = []
    for k in (await db.scalars(select(QuoteLine).where(QuoteLine.version_id == v.id))).all():
        so_id = k.service_order_id or t.service_order_id
        if so_id is not None:
            sonuc.append((so_id, Decimal(str(k.line_total)) * kur))
    return sonuc


async def teklif_hedefleri(db: AsyncSession, t: Quote) -> dict[int, Decimal]:
    """Teklifin gelirinin düştüğü işler: kalem işi (yoksa teklifin işi); PB
    işi ise onun düzeltici işi (varsa). KDV hariç, iskonto sonrası, TL."""
    hedefler: dict[int, Decimal] = defaultdict(Decimal)
    turler: dict[int, str] = {}
    for so_id, tutar in await _kalem_isleri(db, t):
        if so_id not in turler:
            turler[so_id] = (
                await db.scalar(select(ServiceOrder.tur).where(ServiceOrder.id == so_id)) or ""
            )
        hedef = so_id
        if turler[so_id] == "PB":
            hedef = await duzeltici_bul(db, t.id, so_id) or so_id
        hedefler[hedef] += tutar
    return dict(hedefler)


async def _teklif_geliri(db: AsyncSession, so_id: int) -> tuple[Decimal | None, list[str]]:
    """İşin TEKLIF kaynaklı geliri: KABUL durumundaki birimli tekliflerin
    güncel sürüm kalemlerinden bu işe düşen net TL toplamı. Kabul yoksa None."""
    adaylar_isler = {so_id}
    pb_id = await db.scalar(
        select(ServiceOrderEvent.veri["pb_is_id"].astext)
        .where(
            ServiceOrderEvent.service_order_id == so_id,
            ServiceOrderEvent.olay_turu == "TEKLIF",
            ServiceOrderEvent.veri.has_key("kaynak_teklif_id"),
        )
        .limit(1)
    )
    if pb_id:
        adaylar_isler.add(int(pb_id))
    teklifler = (
        await db.scalars(
            select(Quote)
            .where(
                Quote.is_deleted.is_(False),
                Quote.birim.is_not(None),
                Quote.status == "KABUL",
                or_(
                    Quote.service_order_id.in_(adaylar_isler),
                    exists().where(
                        QuoteLine.version_id == Quote.current_version_id,
                        QuoteLine.service_order_id.in_(adaylar_isler),
                    ),
                ),
            )
            .order_by(Quote.id)
        )
    ).all()
    toplam = Decimal("0")
    adlar: list[str] = []
    for t in teklifler:
        pay = (await teklif_hedefleri(db, t)).get(so_id)
        if pay is not None:
            toplam += pay
            adlar.append(t.quote_no)
    return (yuvarla(toplam) if adlar else None), adlar


async def fatura_kilidi_dogrula(db: AsyncSession, t: Quote) -> None:
    """Teklifin gelirinin düştüğü işlerden biri faturaya iletildiyse 409 (E07-D04)."""
    hedefler = await teklif_hedefleri(db, t)
    if not hedefler:
        return
    kilitli = await db.scalar(
        select(func.count()).where(
            ServiceOrderFinancial.service_order_id.in_(list(hedefler)),
            ServiceOrderFinancial.fatura_iletildi_at.is_not(None),
        )
    )
    if kilitli:
        raise MaliyetHatasi(FATURA_KILIDI_MESAJI)


async def gelir_aktar(
    db: AsyncSession, teklif: Any, *, user: User | None, clock: Clock, ip: str | None = None
) -> list[str]:
    """Kabul (ya da iptal) sonrası teklifin dokunduğu işlerin TEKLIF gelirini
    BAŞTAN hesaplar. Elle/ücretsiz/sözleşme geliri KORUNUR, uyarı döner.
    Satış teklifinde çağrılmaz. Public link kararında `user=None` (audit
    `user_id=None`)."""
    if teklif.birim is None:
        return []
    uyarilar: list[str] = []
    user_id = user.id if user is not None else None
    for so_id in sorted(await teklif_hedefleri(db, teklif)):
        fin = await _finans(db, so_id)
        _kilit(fin)
        tutar, adlar = await _teklif_geliri(db, so_id)
        if fin is not None and fin.gelir_kaynagi in ELLE_KAYNAKLAR:
            if tutar is not None:
                no = await db.scalar(select(ServiceOrder.so_no).where(ServiceOrder.id == so_id))
                uyarilar.append(
                    f"{no}: elle girilmiş gelir korundu; kabul edilen teklif tutarı: {tutar} TL"
                )
            continue
        if fin is None and tutar is None:
            continue
        fin = await _finans_ac(db, so_id, user_id)
        fin.gelir = tutar
        fin.gelir_kaynagi = "TEKLIF" if tutar is not None else None
        fin.gelir_notu = ("Kabul edilen teklif: " + ", ".join(adlar)) if adlar else None
        fin.updated_by = user_id
        await audit.log_change(db, fin, "gelir.teklif", user_id=user_id, ip=ip)
        await db.flush()
    return uyarilar


async def duzeltici_isleri_ac(
    db: AsyncSession, t: Quote, *, user: User | None, clock: Clock
) -> list[str]:
    """Kabul edilen bulgu teklifinde PB'ye bağlı her iş için `DEVAM` ilişkili
    düzeltici servis işi açar (yoksa). Gelir `gelir_aktar` ile oraya gider."""
    from app.services.teknik_servis import gecmis, is_emirleri

    uyarilar: list[str] = []
    ham_isler = {so_id for so_id, _ in await _kalem_isleri(db, t)}
    for so_id in sorted(ham_isler):
        pb = await db.get(ServiceOrder, so_id)
        if pb is None or pb.tur != "PB" or pb.is_deleted:
            continue
        if await duzeltici_bul(db, t.id, pb.id) is not None:
            continue
        seriler = [s.seri_no for s in await is_emirleri.aktif_seriler(db, pb)]
        try:
            yeni = await is_emirleri.olustur(
                db,
                is_emirleri.ServisIsiGirdisi(
                    birim=pb.birim,
                    tur=DUZELTICI_TUR,
                    konu=f"Bakım bulgusu düzeltmesi — {t.quote_no}"[:200],
                    customer_id=pb.customer_id,
                    address_id=pb.address_id,
                    contact_id=pb.contact_id,
                    seriler=seriler,
                    equipment_id=pb.equipment_id,
                    iliskili_is_id=pb.id,
                    iliski_turu="DEVAM",
                ),
                user=user,
                clock=clock,
                baslangic_durumu="PLANLAMADA",
            )
        except (ServisHatasi, ServisGirdiHatasi) as exc:
            uyarilar.append(f"{pb.so_no} için düzeltici iş açılamadı: {exc}")
            continue
        await gecmis.olay_yaz(
            db,
            yeni,
            "TEKLIF",
            f"Kabul edilen bakım bulgusu teklifinden açıldı: {t.quote_no}",
            user=user,
            clock=clock,
            veri={"kaynak_teklif_id": t.id, "pb_is_id": pb.id, "quote_no": t.quote_no},
        )
        await gecmis.olay_yaz(
            db,
            pb,
            "TEKLIF",
            f"Bulgu teklifi {t.quote_no} kabul edildi; düzeltici iş: {yeni.so_no}",
            user=user,
            clock=clock,
            veri={"teklif_id": t.id, "duzeltici_is_id": yeni.id},
        )
    return uyarilar


# --- Analiz (TS-149, E07-21) -------------------------------------------------------------


@dataclass
class AnalizFiltresi:
    baslangic: date
    bitis: date
    birim: str | None = None
    tur: str | None = None
    musteri_id: int | None = None
    durum: str | None = None


def donem_araligi(
    donem: str | None, baslangic: date | None, bitis: date | None
) -> tuple[date, date]:
    """`YYYY-AA` ya da başlangıç/bitiş; zorunlu, en çok 12 ay (13 → 400)."""
    if donem:
        try:
            yil, ay = (int(p) for p in donem.split("-"))
            bas = date(yil, ay, 1)
        except (ValueError, TypeError) as exc:
            raise MaliyetGirdiHatasi("Dönem YYYY-AA biçiminde olmalı") from exc
        bit = (bas + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return bas, bit
    if baslangic is None or bitis is None:
        raise MaliyetGirdiHatasi("Dönem ya da başlangıç/bitiş tarihi zorunlu")
    if baslangic > bitis:
        raise MaliyetGirdiHatasi("Başlangıç bitişten sonra olamaz")
    ay_sayisi = (bitis.year * 12 + bitis.month) - (baslangic.year * 12 + baslangic.month) + 1
    if ay_sayisi > AZAMI_AY:
        raise MaliyetGirdiHatasi(f"Dönem en çok {AZAMI_AY} ay olabilir")
    return baslangic, bitis


def _kapanis_ani():
    return func.coalesce(ServiceOrder.completed_at, ServiceOrder.closed_at)


async def analiz(db: AsyncSession, user: User, f: AnalizFiltresi) -> dict[str, Any]:
    """Dönemde çözülmüş (TAMAMLANDI/KAPATILDI) işler; kapsam `kapsam_isler`.

    Sayfalama ve satır sınırı yok (denetçi reddi); dönem sorgu boyutunu sınırlar.
    Özet (birim × tür) ve genel toplam AYNI `is_finansi_toplu` çıktısından;
    tutar toplamları yalnız tam (`fark` dolu) satırlardan.
    """
    if f.birim is not None and f.birim not in BIRIM_KODLARI:
        raise MaliyetGirdiHatasi(f"Bilinmeyen birim: {f.birim}")
    if f.durum is not None and f.durum not in ANALIZ_SUZGECLERI:
        raise MaliyetGirdiHatasi(f"Bilinmeyen durum: {f.durum}")
    bas = yerel_gun_araligi(f.baslangic)[0]
    bit = yerel_gun_araligi(f.bitis)[1]
    stmt = (
        select(
            ServiceOrder.id,
            ServiceOrder.so_no,
            ServiceOrder.birim,
            ServiceOrder.tur,
            ServiceOrder.customer_id,
            Account.title,
            _kapanis_ani(),
        )
        .outerjoin(Account, Account.id == ServiceOrder.customer_id)
        .where(
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.status.in_(sorted(ANALIZ_DURUMLARI)),
            _kapanis_ani() >= bas,
            _kapanis_ani() < bit,
        )
        .order_by(_kapanis_ani(), ServiceOrder.id)
    )
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    if f.birim:
        stmt = stmt.where(ServiceOrder.birim == f.birim)
    if f.tur:
        stmt = stmt.where(ServiceOrder.tur == f.tur)
    if f.musteri_id:
        stmt = stmt.where(ServiceOrder.customer_id == f.musteri_id)
    isler = (await db.execute(stmt)).all()
    finanslar = await is_finansi_toplu(db, [r[0] for r in isler])

    satirlar: list[dict[str, Any]] = []
    for so_id, so_no, birim, tur, musteri_id, musteri, kapanis in isler:
        fin = finanslar[so_id]
        if f.durum and not fin.suzgec_mi(f.durum):
            continue
        satirlar.append(
            {
                **fin.sozluk(),
                "so_no": so_no,
                "birim": birim,
                "tur": tur,
                "musteri_id": musteri_id,
                "musteri": musteri,
                "kapanis_tarihi": yerel_gun(kapanis) if kapanis else None,
            }
        )
    return {
        "baslangic": f.baslangic,
        "bitis": f.bitis,
        "satirlar": satirlar,
        "ozet": _ozetle(satirlar, anahtarlar=("birim", "tur")),
        "genel": _ozetle(satirlar, anahtarlar=())[0] if satirlar else _bos_ozet({}),
    }


_TUTARLAR = ("gelir", "malzeme", "iscilik", "diger", "fark")


def _bos_ozet(anahtar: dict[str, Any]) -> dict[str, Any]:
    return {
        **anahtar,
        "adet": 0,
        "tam_adet": 0,
        **{a: Decimal("0.00") for a in _TUTARLAR},
        "sure_eksik": 0,
        "tarife_eksik": 0,
        "maliyet_eksik": 0,
        "gelir_yok": 0,
        "sozlesme_kapsami": 0,
    }


def _ozetle(satirlar: list[dict[str, Any]], *, anahtarlar: tuple[str, ...]) -> list[dict[str, Any]]:
    gruplar: dict[tuple, dict[str, Any]] = {}
    for s in satirlar:
        anahtar = tuple(s[a] for a in anahtarlar)
        g = gruplar.setdefault(anahtar, _bos_ozet(dict(zip(anahtarlar, anahtar, strict=True))))
        g["adet"] += 1
        if s["fark"] is not None:
            g["tam_adet"] += 1
            for a in _TUTARLAR:
                g[a] += Decimal(str(s[a]))
        g["sure_eksik"] += s["iscilik_durumu"] == "SURE_EKSIK"
        g["tarife_eksik"] += s["iscilik_durumu"] == "TARIFE_EKSIK"
        g["maliyet_eksik"] += s["malzeme_durumu"] == "MALIYET_EKSIK"
        g["gelir_yok"] += s["gelir_durumu"] == "KAYIT_YOK"
        g["sozlesme_kapsami"] += s["gelir_durumu"] == "SOZLESME_KAPSAMI"
    for g in gruplar.values():
        for a in _TUTARLAR:
            g[a] = yuvarla(g[a])
    return [gruplar[k] for k in sorted(gruplar, key=lambda x: tuple(str(p) for p in x))]


# --- Uyarılar (E07-11/15/18) ---------------------------------------------------------------


def is_gunu_ekle(gun: date, adet: int) -> date:
    """Hafta sonunu atlayarak iş günü ekler (resmî tatil ilk sürümde yok, K12)."""
    sonuc = gun
    while adet > 0:
        sonuc += timedelta(days=1)
        if sonuc.weekday() < 5:
            adet -= 1
    return sonuc


async def teklif_sunulacak_isler(db: AsyncSession, user: User, clock: Clock) -> list[int]:
    """Aktif TEKLIF beklemesi var, `quote_id` boş, iptal olmayan teklifi yok ve
    N iş günü geçmiş işler (E07-15; kontrol: `service_results` tarihinden değil)."""
    from app.services import settings as ayar_svc

    gun = int(await ayar_svc.get(db, "teklif_sunulacak_uyari_is_gunu"))
    teklif_var = or_(
        exists().where(
            Quote.service_order_id == ServiceOrder.id,
            Quote.status != "IPTAL",
            Quote.is_deleted.is_(False),
        ),
        exists().where(
            QuoteLine.service_order_id == ServiceOrder.id,
            QuoteLine.version_id == Quote.current_version_id,
            Quote.status != "IPTAL",
            Quote.is_deleted.is_(False),
        ),
    )
    stmt = (
        select(ServiceOrder.id, ServiceHold.started_at)
        .join(ServiceHold, ServiceHold.service_order_id == ServiceOrder.id)
        .where(
            ServiceOrder.is_deleted.is_(False),
            ServiceHold.released_at.is_(None),
            ServiceHold.neden == "TEKLIF",
            ServiceHold.quote_id.is_(None),
            ~teklif_var,
        )
    )
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    bugun = yerel_bugun(clock)
    return [
        so_id
        for so_id, bas in (await db.execute(stmt)).all()
        if is_gunu_ekle(yerel_gun(bas), gun) <= bugun
    ]


async def teklif_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Teklif alanı: süresi yaklaşan birimli teklif, onay bekleyen, teklif sunulacak iş."""
    from app.services import quotes as teklif_svc
    from app.services import settings as ayar_svc

    sonuc: list[Uyari] = []
    bugun = yerel_bugun(clock)
    takip = int(await ayar_svc.get(db, "teklif_takip_uyari_gun"))

    async def _say(kod: str) -> int:
        f = teklif_svc.TeklifFiltresi(tur="SERVIS", kpi=kod)
        stmt = teklif_svc.liste_sorgusu(user, f, bugun, takip).order_by(None).subquery()
        return int(await db.scalar(select(func.count()).select_from(stmt)) or 0)

    sonuc.append(
        Uyari(
            kod="teklif.suresi_yaklasan",
            baslik=f"Süresi {takip} gün içinde dolacak servis teklifi",
            adet=await _say("suresi_yaklasan"),
            yol="/teklifler?tur=SERVIS&kpi=suresi_yaklasan",
            onem="uyari",
        )
    )
    if user.has("teklif.onayla"):
        sonuc.append(
            Uyari(
                kod="teklif.onay_bekleyen",
                baslik="İç onay bekleyen servis teklifi",
                adet=await _say("onay_bekleyen"),
                yol="/teklifler?tur=SERVIS&kpi=onay_bekleyen",
            )
        )
    if user.has("servis.gor"):
        gun = int(await ayar_svc.get(db, "teklif_sunulacak_uyari_is_gunu"))
        sonuc.append(
            Uyari(
                kod="teklif.sunulacak",
                baslik="Teklif sunulacak ama teklifi açılmamış iş",
                adet=len(await teklif_sunulacak_isler(db, user, clock)),
                yol="/servis-isleri?teklif_bekleyen=1",
                onem="uyari",
                aciklama=f"TEKLIF beklemesi {gun} iş gününü geçti, teklif bağlanmadı",
            )
        )
    return sonuc


async def tarife_eksik_birimler(db: AsyncSession, user: User, clock: Clock) -> list[str]:
    """Kullanıcının birimlerinden bugün geçerli işçilik tarifesi olmayanlar."""
    bugun = yerel_bugun(clock)
    birimler = sorted(
        b for b in BIRIM_KODLARI if not kapsam.birim_disinda_mi(user, b, birimsiz_gorunur=False)
    )
    if not birimler:
        return []
    tanimli = set(
        (
            await db.scalars(
                select(ServiceLaborRate.birim).where(
                    ServiceLaborRate.birim.in_(birimler),
                    ServiceLaborRate.valid_from <= bugun,
                    or_(ServiceLaborRate.valid_to.is_(None), ServiceLaborRate.valid_to > bugun),
                )
            )
        ).all()
    )
    return [b for b in birimler if b not in tanimli]


async def tarife_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """İşçilik tarifesi tanımsız birim (E07-11; birim kapsamlı). Yalnız maliyet
    ve servis raporu görenlere (menü ile aynı izin çifti)."""
    if not (user.has("maliyet.gor") and user.has("servis_rapor.gor")):
        return []
    eksik = await tarife_eksik_birimler(db, user, clock)
    return [
        Uyari(
            kod="maliyet.tarife_eksik",
            baslik="İşçilik tarifesi tanımsız birim",
            adet=len(eksik),
            yol="/servis-maliyet?sekme=tarifeler",
            onem="uyari",
            aciklama=", ".join(eksik),
        )
    ]


ts_uyarilar.kaydet("teklif", "teklif.gor", teklif_uyarilari)
ts_uyarilar.kaydet("teklif", "maliyet.gor", tarife_uyarilari)
