"""Tahsilat ve hesap bakiyesi.

**ERP muhasebenin yerini almaz.** Resmî cari hesap Logo'da durur; buradaki
bakiye "ERP'nin bildiği tahakkuk eksi kaydedilen tahsilat"tır ve tek bir işe
yarar: *"şu müşteri X gündür ödemedi, aboneliğini askıya alalım mı"* sorusuna
cevap vermek. Bu ayrım arayüzde de yazılıdır — aksi halde ekip iki farklı
bakiyeyi karşılaştırıp hangisinin doğru olduğunu tartışırdı.

Tahakkuk kaynağı iki kalem:
- **Abonelik:** açılıştan bugüne kadarki tamamlanmış dönemlerin kıst tutarı
  (içinde bulunulan ay, henüz tamamlanmadığı için sayılmaz).
- **Sipariş:** SEVK EDİLMİŞ siparişlerin genel toplamı. Taslak veya
  onaylanmış ama sevk edilmemiş sipariş borç doğurmaz.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, Order, Payment, Subscription
from app.services import settings as ayar_svc
from app.services import subscriptions as abonelik_svc
from app.services.quotes import yuvarla

# Borç doğuran sipariş durumları — sevk edilmemiş sipariş fatura değildir.
BORC_DOGURAN_SIPARIS = ("KISMI_SEVK", "SEVK_EDILDI", "TAMAMLANDI")


def _onceki_donemler(baslangic: date, bugun: date) -> list[str]:
    """Başlangıçtan İÇİNDE BULUNULAN AYA KADAR (hariç) dönem listesi."""
    donemler: list[str] = []
    yil, ay = baslangic.year, baslangic.month
    while (yil, ay) < (bugun.year, bugun.month):
        donemler.append(f"{yil:04d}-{ay:02d}")
        ay += 1
        if ay > 12:
            yil, ay = yil + 1, 1
    return donemler


async def abonelik_tahakkuklari(db: AsyncSession, clock: Clock) -> dict[int, Decimal]:
    """Tüm müşterilerin kapanmış dönem abonelik tahakkumu (KDV dahil).

    Dönemler TEK seferde taranır. Müşteri başına ayrı ayrı hesaplamak,
    geciken listesini müşteri × dönem × abonelik kadar sorguya çıkarırdı.
    """
    ilk = await db.scalar(
        select(func.min(Subscription.start_date)).where(
            Subscription.is_deleted.is_(False), Subscription.status != "TASLAK"
        )
    )
    if ilk is None:
        return {}

    toplam: dict[int, Decimal] = {}
    for donem in _onceki_donemler(ilk, clock.now().date()):
        for satir in await abonelik_svc.donem_tahakkuku(db, donem):
            mid = satir["customer_id"]
            toplam[mid] = toplam.get(mid, Decimal("0")) + satir["toplam"]
    return {k: yuvarla(v) for k, v in toplam.items()}


async def abonelik_tahakkuku(db: AsyncSession, account_id: int, clock: Clock) -> Decimal:
    return (await abonelik_tahakkuklari(db, clock)).get(account_id, Decimal("0"))


async def siparis_tahakkuku(db: AsyncSession, account_id: int) -> Decimal:
    toplam = await db.scalar(
        select(func.coalesce(func.sum(Order.grand_total), 0)).where(
            Order.customer_id == account_id,
            Order.is_deleted.is_(False),
            Order.status.in_(BORC_DOGURAN_SIPARIS),
        )
    )
    return yuvarla(Decimal(str(toplam or 0)))


async def tahsilat_toplami(db: AsyncSession, account_id: int, *, yon: str) -> Decimal:
    toplam = await db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.account_id == account_id, Payment.direction == yon
        )
    )
    return yuvarla(Decimal(str(toplam or 0)))


async def bakiye(
    db: AsyncSession,
    account_id: int,
    clock: Clock,
    *,
    abonelik_toplamlari: dict[int, Decimal] | None = None,
) -> dict:
    """Bir hesabın ERP tarafındaki alacak/borç özeti.

    Pozitif `musteri_bakiye` = müşteri borçlu. Pozitif `ortak_bakiye` =
    Denge montaj noktasına borçlu (hak ediş ödenmemiş).
    """
    from app.models import PartnerSettlement

    hesap = await db.get(Account, account_id)
    if hesap is None:
        raise ValueError(f"Hesap bulunamadı: {account_id}")

    abonelik = (
        abonelik_toplamlari
        if abonelik_toplamlari is not None
        else await abonelik_tahakkuklari(db, clock)
    ).get(account_id, Decimal("0"))
    siparis = await siparis_tahakkuku(db, account_id)
    tahsil = await tahsilat_toplami(db, account_id, yon="GELEN")

    hakedis = await db.scalar(
        select(func.coalesce(func.sum(PartnerSettlement.net_payable), 0)).where(
            PartnerSettlement.partner_id == account_id,
            PartnerSettlement.status.in_(("ONAYLANDI", "ODEME_BEKLIYOR", "ODENDI")),
        )
    )
    odenen = await tahsilat_toplami(db, account_id, yon="GIDEN")

    son_tahsilat = await db.scalar(
        select(func.max(Payment.paid_at)).where(
            Payment.account_id == account_id, Payment.direction == "GELEN"
        )
    )

    return {
        "account_id": account_id,
        "title": hesap.title,
        "abonelik_tahakkuk": abonelik,
        "siparis_tahakkuk": siparis,
        "tahsil_edilen": tahsil,
        "musteri_bakiye": yuvarla(abonelik + siparis - tahsil),
        "hakedis_tahakkuk": yuvarla(Decimal(str(hakedis or 0))),
        "hakedis_odenen": odenen,
        "ortak_bakiye": yuvarla(Decimal(str(hakedis or 0)) - odenen),
        "son_tahsilat": son_tahsilat,
    }


async def gecikenler(db: AsyncSession, clock: Clock, *, gun: int | None = None) -> list[dict]:
    """Borcu olup uzun süredir ödeme yapmayan müşteriler.

    Askıya alma ÖNERİLİR, otomatik yapılmaz: ödeme banka ekstresine
    ERP'den önce düşer ve çalışan bir müşterinin takibini yanlışlıkla
    kesmek, gecikmiş tahsilattan pahalıya gelir.
    """
    esik = gun if gun is not None else int(await ayar_svc.get(db, "odeme_gecikme_uyari_gun"))
    bugun = clock.now().date()

    musteriler = (
        await db.scalars(
            select(Subscription.customer_id)
            .where(
                Subscription.is_deleted.is_(False),
                Subscription.status.in_(("AKTIF", "ASKIDA")),
            )
            .distinct()
        )
    ).all()

    tahakkuklar = await abonelik_tahakkuklari(db, clock)
    sonuc: list[dict] = []
    for account_id in musteriler:
        b = await bakiye(db, account_id, clock, abonelik_toplamlari=tahakkuklar)
        if b["musteri_bakiye"] <= 0:
            continue
        son = b["son_tahsilat"]
        gecen = (bugun - son).days if son else None
        if son is not None and gecen < esik:
            continue

        abonelikler = (
            await db.scalars(
                select(Subscription).where(
                    Subscription.customer_id == account_id,
                    Subscription.is_deleted.is_(False),
                    Subscription.status == "AKTIF",
                )
            )
        ).all()
        sonuc.append(
            {
                **b,
                "gecen_gun": gecen,
                "esik_gun": esik,
                "aktif_abonelik": len(abonelikler),
                # Otomatik askıya alma yalnız açıkça işaretlenmiş sözleşmelerde
                # önerilir; gerisinde karar ekibindir.
                "askiya_alma_onerilen": [
                    {"id": a.id, "no": a.subscription_no, "otomatik": a.auto_suspend_on_debt}
                    for a in abonelikler
                ],
            }
        )
    sonuc.sort(key=lambda x: x["musteri_bakiye"], reverse=True)
    return sonuc
