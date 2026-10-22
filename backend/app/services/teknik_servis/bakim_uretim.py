"""PB üretim motoru (E04-06/07/08, TS-062).

**1 cihaz × 1 dönem = 1 PB.** Kalem başına PB şu ifadeyle eklenir:
`INSERT ... ON CONFLICT (contract_item_id, maintenance_period_id) WHERE
tur='PB' AND NOT is_deleted DO NOTHING RETURNING id`. Hedef kısmi tekil
İNDEKS olduğu için `ON CONSTRAINT` kullanılamaz (E04 kontrol #1); indeks
çıkarımı (`index_where`) kullanılır. Form ve madde satırları yalnız PB
gerçekten eklendiyse (RETURNING) açılır. Aynı tur iki kez koşunca 0 yeni PB;
worker yeniden denemesi bu sayede güvenlidir. Kapsam dışı onayıyla IPTAL
edilmiş PB satırı silinmediği için o cihaz–dönem yeniden ÜRETİLMEZ.

**Var olan çift önceden sorgulanır**, sonra eklenir: PB numarası sequence'ten
alındığı için çatışan her ekleme bir numara yakardı. Sorgu ile ekleme
arasındaki yarışı `ON CONFLICT` kapatır.

**Tek hata turu durdurmaz:** her sözleşme kendi SAVEPOINT'inde üretilir;
bozuk sözleşme gerekçesiyle `skipped`'e düşer (SURESI_DOLMUS, EKIPMAN_YOK,
SABLON_YOK, TEYIT_BEKLIYOR, PASIF, HATA), diğerleri üretilir.

**Önizleme = aynı `uret()`**, dış SAVEPOINT içinde koşar ve geri alınır:
ikinci bir "ne üretilecek" hesabı yazılsaydı önizleme ile gerçek üretim
ayrışırdı. Bedel: önizlemede çekilen sequence numaraları geri dönmez
(numara serisinde boşluk; `numara.py` aynı bedeli kabul ediyor).

Yalnız `equipment_id` dolu ve `pb_uygun` kalemde PB üretilir; ekipmansız kalem
"adet farkı" (EKIPMAN_YOK) olarak raporlanır — uydurma cihaz açılmaz.
Worker `bakim_otomatik_uretim=False` iken üretmez; elle üretim `bakim.yaz`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    Account,
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenanceForm,
    MaintenanceFormCheck,
    MaintenanceGenerationRun,
    MaintenancePeriod,
    ServiceEquipment,
    ServiceOrder,
    ServiceOrderSerial,
)
from app.services import settings as ayar_svc
from app.services.teknik_servis import bakim, bakim_sablonlari, gecmis, kancalar, numara
from app.services.teknik_servis.bakim import BakimKapsamDisi, yerel_gece
from app.services.teknik_servis.is_emirleri import tur_kategorisi
from app.services.teknik_servis.yerel_zaman import yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

logger = logging.getLogger("denge.bakim")

ATLAMA_NEDENLERI = (
    "SURESI_DOLMUS",
    "EKIPMAN_YOK",
    "SABLON_YOK",
    "TEYIT_BEKLIYOR",
    "PASIF",
    "TASLAK",
    "HATA",
)
_NEDEN_METNI = {
    "SURESI_DOLMUS": "Sözleşmenin süresi dolmuş; yeni dönem PB'si üretilmez",
    "TEYIT_BEKLIYOR": "Sözleşme teyit bekliyor; tarih/kapsam teyit edilmeden PB üretilmez",
    "PASIF": "Sözleşme pasif",
    "TASLAK": "Sözleşme taslak; aktifleştirilmeden PB üretilmez",
}


@dataclass
class UretimSonucu:
    run: MaintenanceGenerationRun
    uretilen: list[dict[str, Any]] = field(default_factory=list)
    atlanan: list[dict[str, Any]] = field(default_factory=list)


def _atla(
    sozlesme: MaintenanceContract, musteri: str | None, kod: str, neden: str | None = None
) -> dict[str, Any]:
    return {
        "contract_id": sozlesme.id,
        "contract_no": sozlesme.contract_no,
        "source_ref": sozlesme.source_ref,
        "musteri": musteri,
        "neden_kodu": kod,
        "neden": neden or _NEDEN_METNI.get(kod, kod),
    }


def _kalem_gecerli_mi(kalem: MaintenanceContractItem, donem: MaintenancePeriod, simdi) -> bool:
    """Kalem dönemde kapsamda mı: hedef gününden önce kapanmamış ve yürürlüğe
    girmiş (sonradan eklenen kalem açık dönemin PB'sine katılır)."""
    hedef_an = yerel_gece(donem.target_date)
    if kalem.valid_to is not None and kalem.valid_to <= hedef_an:
        return False
    return kalem.valid_from is None or kalem.valid_from <= max(hedef_an, simdi)


async def _pb_ekle(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    donem: MaintenancePeriod,
    kalem: MaintenanceContractItem,
    ekipman: ServiceEquipment,
    *,
    user: User | None,
    clock: Clock,
) -> ServiceOrder | None:
    """Tek PB (+ seri, form, maddeler, OLUSTUR olayı). Çatışmada None."""
    sablon = bakim_sablonlari.sablon(kalem.equipment_type)
    if sablon is None:  # pragma: no cover - FK bütünlüğü
        raise BakimKapsamDisi("Kayıt bulunamadı")
    tur_adi = bakim_sablonlari.CIHAZ_TURU_ADLARI.get(kalem.equipment_type, kalem.equipment_type)
    degerler = {
        "so_no": await numara.belge_no(db, "service_order_no_seq", "PB", donem.target_date),
        "birim": sozlesme.birim,
        "tur": "PB",
        "kategori": tur_kategorisi("PB"),
        "status": "PLANLAMADA",
        "customer_id": sozlesme.account_id,
        "address_id": sozlesme.address_id,
        "contact_id": sozlesme.contact_id,
        "talep_kanali": "BAKIM_OTOMATIK",
        "konu": (
            f"Planlı bakım {sozlesme.contract_no} — {tur_adi} #{kalem.sira} "
            f"({donem.target_date:%d.%m.%Y})"
        )[:200],
        "equipment_id": ekipman.id,
        "contract_item_id": kalem.id,
        "maintenance_period_id": donem.id,
        "coverage_status": "SOZLESMELI",
        "coverage_snapshot": {
            "contract_id": sozlesme.id,
            "contract_no": sozlesme.contract_no,
            "kalem_id": kalem.id,
            "donem_id": donem.id,
            "hedef": donem.target_date.isoformat(),
        },
        "created_by": user.id if user else None,
        "updated_by": user.id if user else None,
    }
    stmt = (
        pg_insert(ServiceOrder)
        .values(**degerler)
        .on_conflict_do_nothing(
            index_elements=[ServiceOrder.contract_item_id, ServiceOrder.maintenance_period_id],
            index_where=text("tur = 'PB' AND NOT is_deleted"),
        )
        .returning(ServiceOrder.id)
    )
    so_id = await db.scalar(stmt)
    if so_id is None:
        return None
    so = await db.get(ServiceOrder, so_id)
    if so is None:  # pragma: no cover - FK bütünlüğü
        raise BakimKapsamDisi("Kayıt bulunamadı")
    if ekipman.serial_no and ekipman.serial_no.strip():
        db.add(
            ServiceOrderSerial(
                service_order_id=so.id,
                seri_no=ekipman.serial_no,
                seri_norm="",  # ORM olayı normalize eder
                created_by=user.id if user else None,
            )
        )
    form = MaintenanceForm(
        service_order_id=so.id,
        template_code=kalem.equipment_type,
        template_version=sablon.surum,
        zone=ekipman.zone,
        created_by=user.id if user else None,
        updated_by=user.id if user else None,
    )
    db.add(form)
    await db.flush()
    for sira, madde in enumerate(sablon.maddeler, start=1):
        db.add(
            MaintenanceFormCheck(
                form_id=form.id, check_code=madde.kod, label=madde.etiket, sira=sira
            )
        )
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "OLUSTUR",
        f"Planlı bakım işi üretildi ({sozlesme.contract_no}, dönem hedefi "
        f"{donem.target_date:%d.%m.%Y})",
        user=user,
        clock=clock,
        yeni_durum=so.status,
        veri={"contract_id": sozlesme.id, "donem_id": donem.id, "kalem_id": kalem.id},
    )
    await kancalar.is_olusturuldu(db, so, clock)
    return so


async def _sozlesme_uret(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    sonuc: UretimSonucu,
    *,
    musteri: str | None,
    user: User | None,
    clock: Clock,
    on_acilis: int,
    donem_id: int | None,
) -> None:
    simdi = clock.now()
    bugun = yerel_bugun(clock)
    donemler = await bakim.donemleri_hesapla(db, sozlesme, clock)
    if donem_id is not None:
        # Eksik PB tamamlama: şef dönemi açıkça seçti, vade penceresi aranmaz.
        vadeli = [d for d in donemler if d.id == donem_id and d.closed_at is None]
    else:
        vadeli = [
            d
            for d in donemler
            if d.closed_at is None and d.target_date - timedelta(days=on_acilis) <= bugun
        ]
    if not vadeli:
        return
    kalemler = await bakim.acik_kalemler(db, sozlesme.id)
    # Dönemde açılmış PB'si olan kapalı kalemler de "var" sayılır; burada
    # yalnız açık kalemlere yeni PB açılır.
    mevcut = set(
        (
            await db.execute(
                select(ServiceOrder.contract_item_id, ServiceOrder.maintenance_period_id).where(
                    ServiceOrder.tur == "PB",
                    ServiceOrder.is_deleted.is_(False),
                    ServiceOrder.maintenance_period_id.in_([d.id for d in vadeli]),
                )
            )
        ).all()
    )
    ekipmanlar = {
        e.id: e
        for e in (
            await db.scalars(
                select(ServiceEquipment).where(
                    ServiceEquipment.id.in_([k.equipment_id for k in kalemler if k.equipment_id])
                )
            )
        ).all()
    }
    ekipmansiz = 0
    sablonsuz: set[str] = set()
    for donem in vadeli:
        for kalem in kalemler:
            if not kalem.pb_uygun or not _kalem_gecerli_mi(kalem, donem, simdi):
                continue
            if (kalem.id, donem.id) in mevcut:
                continue
            if bakim_sablonlari.sablon(kalem.equipment_type) is None:
                sablonsuz.add(kalem.equipment_type)
                continue
            ekipman = ekipmanlar.get(kalem.equipment_id) if kalem.equipment_id else None
            if ekipman is None or ekipman.is_deleted:
                ekipmansiz += 1
                continue
            so = await _pb_ekle(db, sozlesme, donem, kalem, ekipman, user=user, clock=clock)
            if so is None:
                continue
            if donem.generation_run_id is None:
                donem.generation_run_id = sonuc.run.id
            sonuc.uretilen.append(
                {
                    "contract_id": sozlesme.id,
                    "contract_no": sozlesme.contract_no,
                    "musteri": musteri,
                    "donem_id": donem.id,
                    "hedef": donem.target_date.isoformat(),
                    "so_id": so.id,
                    "so_no": so.so_no,
                    "kalem_id": kalem.id,
                }
            )
    await db.flush()
    if ekipmansiz:
        sonuc.atlanan.append(
            _atla(
                sozlesme,
                musteri,
                "EKIPMAN_YOK",
                f"{ekipmansiz} cihaz-dönem için kalem ekipmana bağlı değil (adet farkı); "
                "eşleştirme ekranından bağlayın",
            )
        )
    for tur in sorted(sablonsuz):
        sonuc.atlanan.append(
            _atla(sozlesme, musteri, "SABLON_YOK", f"{tur} türü için kontrol şablonu yok")
        )


async def uret_ayrintili(
    db: AsyncSession,
    clock: Clock,
    user: User | None = None,
    tetik: str = "WORKER",
    *,
    sozlesme_id: int | None = None,
    donem_id: int | None = None,
) -> UretimSonucu:
    """Vadesi gelen dönemlerin PB'lerini üretir; ayrıntılı sonuç döner.

    Vade: dönem kapanmamış ve `hedef - bakim_on_acilis_gun <= bugün` (yerel).
    `sozlesme_id`/`donem_id` verilirse yalnız onlar (eksik PB tamamlama).
    """
    on_acilis = int(await ayar_svc.get(db, "bakim_on_acilis_gun") or 0)
    run = MaintenanceGenerationRun(
        tetik=tetik,
        generated_count=0,
        skipped=[],
        parametreler={
            "on_acilis_gun": on_acilis,
            "bugun": yerel_bugun(clock).isoformat(),
            "sozlesme_id": sozlesme_id,
            "donem_id": donem_id,
        },
        created_by=user.id if user else None,
    )
    db.add(run)
    await db.flush()
    sonuc = UretimSonucu(run)
    stmt = select(MaintenanceContract, Account.title).outerjoin(
        Account, Account.id == MaintenanceContract.account_id
    )
    stmt = stmt.where(MaintenanceContract.is_deleted.is_(False))
    if sozlesme_id is not None:
        stmt = stmt.where(MaintenanceContract.id == sozlesme_id)
    else:
        stmt = stmt.where(MaintenanceContract.status.in_(("AKTIF", "TEYIT_BEKLIYOR")))
    if user is not None:
        # Elle üretim kullanıcının kapsamıyla sınırlı: birim şefi başka birimin
        # PB'sini üretemez ve atlanan listesinde başka birimin sözleşmesi görünmez.
        stmt = bakim.sozlesme_kapsami(stmt, user)
    simdi = clock.now()
    for sozlesme, musteri in (await db.execute(stmt.order_by(MaintenanceContract.id))).all():
        if sozlesme.status != "AKTIF":
            sonuc.atlanan.append(_atla(sozlesme, musteri, sozlesme.status))
            continue
        if sozlesme.valid_to is not None and sozlesme.valid_to <= simdi:
            sonuc.atlanan.append(_atla(sozlesme, musteri, "SURESI_DOLMUS"))
            continue
        try:
            async with db.begin_nested():
                await _sozlesme_uret(
                    db,
                    sozlesme,
                    sonuc,
                    musteri=musteri,
                    user=user,
                    clock=clock,
                    on_acilis=on_acilis,
                    donem_id=donem_id,
                )
        except Exception as exc:  # tek sözleşme turu durdurmaz (E04-06)
            logger.exception("PB üretimi sözleşmede hata: %s", sozlesme.contract_no)
            sonuc.uretilen = [u for u in sonuc.uretilen if u["contract_id"] != sozlesme.id]
            sonuc.atlanan.append(_atla(sozlesme, musteri, "HATA", f"Üretim hatası: {exc}"[:300]))
    run.generated_count = len(sonuc.uretilen)
    run.skipped = sonuc.atlanan
    await db.flush()
    return sonuc


async def uret(
    db: AsyncSession,
    clock: Clock,
    user: User | None = None,
    tetik: str = "WORKER",
    *,
    sozlesme_id: int | None = None,
    donem_id: int | None = None,
) -> MaintenanceGenerationRun:
    """`uret_ayrintili`'nin turu döndüren kısa biçimi (worker imzası)."""
    sonuc = await uret_ayrintili(db, clock, user, tetik, sozlesme_id=sozlesme_id, donem_id=donem_id)
    return sonuc.run


async def onizle(db: AsyncSession, clock: Clock, user: User) -> dict[str, Any]:
    """DB'YE YAZMAZ: aynı `uret()` dış SAVEPOINT'te koşar ve geri alınır."""
    nokta = await db.begin_nested()
    try:
        sonuc = await uret_ayrintili(db, clock, user, "ELLE")
        gruplar: dict[tuple[int, int], dict[str, Any]] = {}
        for u in sonuc.uretilen:
            g = gruplar.setdefault(
                (u["contract_id"], u["donem_id"]),
                {
                    "contract_id": u["contract_id"],
                    "contract_no": u["contract_no"],
                    "musteri": u["musteri"],
                    "donem_id": u["donem_id"],
                    "hedef": u["hedef"],
                    "pb_sayisi": 0,
                },
            )
            g["pb_sayisi"] += 1
        return {"uretilecek": list(gruplar.values()), "atlanacak": list(sonuc.atlanan)}
    finally:
        await nokta.rollback()


async def pb_uretimi_gorevi(db: AsyncSession, clock: Clock) -> str:
    """Worker görevi `pb-uretimi` (imza `worker.Gorev`: özet metni döner).

    Ayar her turda okunur: kapalıyken hiçbir şey yazmaz (R1 yayını
    `bakim_otomatik_uretim=False`, KD-21).
    """
    if not await ayar_svc.get(db, "bakim_otomatik_uretim"):
        return "otomatik PB üretimi kapalı (bakim_otomatik_uretim=False)"
    run = await uret(db, clock, None, "WORKER")
    return f"{run.generated_count} PB üretildi, {len(run.skipped or [])} sözleşme atlandı"
