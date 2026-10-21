"""Satın alma, mal kabul ve landed cost dağıtımı.

**Landed cost = (mal bedeli + tüm masraflar) / cihazlar.** Dağıtım anahtarı
masrafın cinsine göre seçilir: navlun ağırlıkla, gümrük vergisi mal bedeliyle,
müşavirlik adetle orantılıdır. Tek bir anahtar zorlamak, ağır ama ucuz bir
partiyle hafif ama pahalı bir partiyi aynı kefeye koymak olurdu.

**Yuvarlama artığı son cihaza yazılır.** 100 cihaza 1.000,01 TL dağıtınca
kuruşlar toplamı tutmaz; farkı sessizce kaybetmek yerine son satıra eklemek,
"dosya toplamı = cihaz maliyetleri toplamı" eşitliğini korur. Muhasebe bu
eşitliği kontrol eder.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Device,
    GoodsReceipt,
    ImportFile,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.services.normalize import validate_imei
from app.services.quotes import yuvarla

KURUS = Decimal("0.01")

MASRAF_ALANLARI = (
    "goods_value_try",
    "freight_try",
    "insurance_try",
    "customs_duty_try",
    "other_tax_try",
    "broker_fee_try",
    "inland_freight_try",
    "other_cost_try",
)


class SatinAlmaHatasi(ValueError):
    """Satın alma / ithalat kurallarına aykırı işlem."""


async def siparis_hesapla(db: AsyncSession, siparis: PurchaseOrder) -> PurchaseOrder:
    toplam = await db.scalar(
        select(
            func.coalesce(func.sum(PurchaseOrderLine.qty * PurchaseOrderLine.unit_price), 0)
        ).where(PurchaseOrderLine.purchase_order_id == siparis.id)
    )
    siparis.subtotal = yuvarla(Decimal(str(toplam or 0)))
    await db.flush()
    return siparis


async def numara_uret(db: AsyncSession, clock: Clock, model, onek: str) -> str:
    sira = (await db.scalar(select(model.id).order_by(model.id.desc()).limit(1)) or 0) + 1
    return f"{onek}{clock.now():%Y}-{sira:05d}"


def dosya_toplami(dosya: ImportFile) -> Decimal:
    return yuvarla(
        sum((Decimal(str(getattr(dosya, a) or 0)) for a in MASRAF_ALANLARI), Decimal("0"))
    )


async def mal_kabul(
    db: AsyncSession,
    siparis: PurchaseOrder,
    *,
    kalem: PurchaseOrderLine,
    kimlikler: list[str],
    clock: Clock,
    import_file_id: int | None = None,
    warehouse_id: int | None = None,
    user_id: int | None = None,
) -> GoodsReceipt:
    """IMEI listesini stoğa alır ve siparişin teslim adedini ilerletir.

    Cihaz durumu ithalat dosyası varsa `ITHALATTA`, yoksa doğrudan `STOKTA`
    açılır: gümrükteki mal fiziksel olarak stokta değildir ve rezerve
    edilebilir görünmemelidir.
    """
    if siparis.status in ("TASLAK", "IPTAL"):
        raise SatinAlmaHatasi(
            f"{siparis.status} durumundaki siparişte mal kabul yapılamaz; önce sipariş verin."
        )
    if not kimlikler:
        raise SatinAlmaHatasi("Mal kabulde kimlik listesi boş olamaz.")

    kalan = Decimal(str(kalem.qty)) - Decimal(str(kalem.qty_received or 0))
    if Decimal(len(kimlikler)) > kalan:
        raise SatinAlmaHatasi(
            f"Kalemde kalan adet {kalan:g}; {len(kimlikler)} cihaz kabul edilemez."
        )

    urun = await db.get(Product, kalem.product_id)
    if urun is None:
        raise SatinAlmaHatasi("Kalemin ürünü bulunamadı.")

    fis = GoodsReceipt(
        receipt_no=await numara_uret(db, clock, GoodsReceipt, "MK"),
        purchase_order_id=siparis.id,
        import_file_id=import_file_id,
        warehouse_id=warehouse_id,
        received_at=clock.now().date(),
        device_count=len(kimlikler),
        created_by=user_id,
    )
    db.add(fis)
    await db.flush()

    durum = "ITHALATTA" if import_file_id else "STOKTA"
    for ham in kimlikler:
        imei = seri = None
        if urun.identity_kind == "IMEI":
            try:
                imei = validate_imei(ham)
            except ValueError as exc:
                raise SatinAlmaHatasi(f"{ham}: {exc}") from exc
            var = await db.scalar(select(Device).where(Device.imei == imei))
        elif urun.identity_kind == "SERI_NO":
            seri = ham.strip()
            var = await db.scalar(select(Device).where(Device.serial_no == seri))
        else:
            raise SatinAlmaHatasi(
                f"{urun.code} ürünü kimlik taşımıyor; mal kabulde IMEI/seri no beklenmez."
            )
        if var is not None:
            raise SatinAlmaHatasi(f"{ham} sistemde zaten kayıtlı ({var.status}).")

        db.add(
            Device(
                imei=imei,
                serial_no=seri,
                identity_kind=urun.identity_kind,
                product_id=urun.id,
                status=durum,
                import_file_id=import_file_id,
                goods_receipt_id=fis.id,
                # BTK kaydı ithal cihazda gerekir; yurt içi alımda ürün
                # kartındaki belge zaten kapsıyor.
                btk_status="BEKLIYOR" if import_file_id else "GEREKMIYOR",
                created_by=user_id,
            )
        )

    kalem.qty_received = Decimal(str(kalem.qty_received or 0)) + Decimal(len(kimlikler))
    await db.flush()
    await durum_yenile(db, siparis)
    return fis


async def durum_yenile(db: AsyncSession, siparis: PurchaseOrder) -> str:
    toplam, alinan = (
        await db.execute(
            select(
                func.coalesce(func.sum(PurchaseOrderLine.qty), 0),
                func.coalesce(func.sum(PurchaseOrderLine.qty_received), 0),
            ).where(PurchaseOrderLine.purchase_order_id == siparis.id)
        )
    ).one()
    toplam, alinan = Decimal(str(toplam)), Decimal(str(alinan))

    if siparis.status in ("TASLAK", "IPTAL"):
        return siparis.status
    if alinan <= 0:
        yeni = "SIPARIS_VERILDI"
    elif alinan < toplam:
        yeni = "KISMI_TESLIM"
    else:
        yeni = "TESLIM_ALINDI"
    if siparis.status != yeni:
        siparis.status = yeni
        await db.flush()
    return siparis.status


# --- Landed cost --------------------------------------------------------------


async def landed_cost_dagit(
    db: AsyncSession,
    dosya: ImportFile,
    *,
    clock: Clock,
    user_id: int | None = None,
) -> dict:
    """Dosyadaki tüm masrafları cihazlara dağıtır ve `landed_cost_try` yazar.

    Yeniden çalıştırılabilir: dosya güncellendikten sonra tekrar çağrılırsa
    dağıtım baştan yapılır, eski değer üzerine yazılır.
    """
    cihazlar = (
        await db.scalars(
            select(Device)
            .where(Device.import_file_id == dosya.id, Device.is_deleted.is_(False))
            .order_by(Device.id)
        )
    ).all()
    if not cihazlar:
        raise SatinAlmaHatasi("Bu ithalat dosyasına bağlı cihaz yok; önce mal kabul yapın.")

    toplam = dosya_toplami(dosya)
    if toplam <= 0:
        raise SatinAlmaHatasi("Dosyada dağıtılacak masraf yok.")

    agirliklar = await _agirliklar(db, dosya, cihazlar)
    agirlik_toplami = sum(agirliklar.values(), Decimal("0"))
    if agirlik_toplami <= 0:
        # Ağırlık/tutar bilinmiyorsa adete düş — dağıtım yapmamak, maliyeti
        # hiç bilmemekten iyi değil.
        agirliklar = {c.id: Decimal("1") for c in cihazlar}
        agirlik_toplami = Decimal(len(cihazlar))

    dagitilan = Decimal("0")
    for i, cihaz in enumerate(cihazlar):
        if i == len(cihazlar) - 1:
            # Yuvarlama artığı son cihaza; dosya toplamı = cihazlar toplamı.
            pay = toplam - dagitilan
        else:
            pay = (toplam * agirliklar[cihaz.id] / agirlik_toplami).quantize(
                KURUS, rounding=ROUND_HALF_UP
            )
            dagitilan += pay
        cihaz.landed_cost_try = pay
        cihaz.updated_by = user_id

    dosya.allocated_at = clock.now().date()
    dosya.allocated_device_count = len(cihazlar)
    await db.flush()

    return {
        "dosya_toplami": toplam,
        "cihaz_sayisi": len(cihazlar),
        "anahtar": dosya.allocation_key,
        "birim_ortalama": yuvarla(toplam / Decimal(len(cihazlar))),
    }


async def _agirliklar(
    db: AsyncSession, dosya: ImportFile, cihazlar: list[Device]
) -> dict[int, Decimal]:
    """Dağıtım anahtarına göre cihaz başına ağırlık katsayısı."""
    anahtar = dosya.allocation_key or "TUTAR"
    if anahtar == "ADET":
        return {c.id: Decimal("1") for c in cihazlar}

    kalemler = (
        await db.scalars(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.purchase_order_id == dosya.purchase_order_id
            )
        )
    ).all()
    if not kalemler:
        return {c.id: Decimal("1") for c in cihazlar}

    if anahtar == "AGIRLIK":
        olcu = {k.product_id: Decimal(str(k.unit_weight_kg or 0)) for k in kalemler}
    else:  # TUTAR
        olcu = {k.product_id: Decimal(str(k.unit_price or 0)) for k in kalemler}

    return {c.id: olcu.get(c.product_id, Decimal("0")) for c in cihazlar}


# --- BTK ----------------------------------------------------------------------


async def btk_bekleyenler(db: AsyncSession) -> list[dict]:
    """BTK kaydı bekleyen cihazlar (brief §4.13)."""
    satirlar = (
        await db.execute(
            select(Device, Product, ImportFile)
            .join(Product, Product.id == Device.product_id)
            .outerjoin(ImportFile, ImportFile.id == Device.import_file_id)
            .where(Device.is_deleted.is_(False), Device.btk_status == "BEKLIYOR")
            .order_by(Device.id)
        )
    ).all()
    return [
        {
            "device_id": c.id,
            "imei": c.imei,
            "serial_no": c.serial_no,
            "urun_kodu": u.code,
            "urun_adi": u.name,
            "ce_belgesi": u.ce_document_ref,
            "tse_belgesi": u.tse_document_ref,
            "uygunluk_belgesi": u.conformity_document_ref,
            "ithalat_dosyasi": d.file_no if d else None,
            "gumruk_beyanname": d.customs_declaration_no if d else None,
        }
        for c, u, d in satirlar
    ]


async def btk_kaydet(
    db: AsyncSession,
    device_ids: list[int],
    *,
    referans: str | None,
    clock: Clock,
    user_id: int | None = None,
) -> int:
    """Seçilen cihazları BTK'da kayıtlı işaretler."""
    cihazlar = (
        await db.scalars(
            select(Device).where(Device.id.in_(device_ids), Device.is_deleted.is_(False))
        )
    ).all()
    bugun: date = clock.now().date()
    for c in cihazlar:
        c.btk_status = "KAYITLI"
        c.btk_registered_at = bugun
        c.btk_reference = referans
        c.updated_by = user_id
    await db.flush()
    return len(cihazlar)
