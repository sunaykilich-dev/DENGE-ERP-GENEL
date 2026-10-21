"""Toplu fiyat güncelleme: önizle → uygula → bildir.

Kural: **önizlemenin gösterdiği ile uygulanan aynı olmalı.** Bu yüzden
kriterler partiye yazılır ve uygulama aşaması onları yeniden okur; arayüzden
ikinci kez kriter göndermek, arada değişmiş bir filtreyle sessizce başka bir
kümeye zam yapmak demekti.

Hariç tutma nedenleri açıkça raporlanır. "142 abonelikten 118'ine uygulandı"
cümlesi, kalan 24'ün neden atlandığı görünmeden işe yaramaz.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, PriceBatch, Subscription
from app.models.pricing import ZAM_YONTEMLERI
from app.services import subscriptions as abonelik_svc
from app.services.quotes import yuvarla

# Zam yalnız yürüyen sözleşmelere uygulanır.
ZAMLANABILIR_DURUMLAR = ("AKTIF", "ASKIDA")


class ZamHatasi(ValueError):
    """Toplu fiyat güncelleme kurallarına aykırı işlem."""


def yeni_fiyat(
    mevcut: Decimal, *, yontem: str, deger: Decimal, yuvarlama: Decimal = Decimal("0.01")
) -> Decimal:
    """Tek bir aboneliğin yeni ücretini hesaplar.

    `yuvarlama` adımı 1 ise tam TL'ye, 0.01 ise kuruşa yuvarlanır. Zam
    listesi ekipçe okunacağı için tam TL çoğu zaman tercih edilir.
    """
    if yontem not in ZAM_YONTEMLERI:
        raise ZamHatasi(f"Zam yöntemi {ZAM_YONTEMLERI} içinden olmalı")
    mevcut = Decimal(str(mevcut))
    deger = Decimal(str(deger))

    if yontem == "YUZDE":
        ham = mevcut * (Decimal("1") + deger / Decimal("100"))
    elif yontem == "TUTAR":
        ham = mevcut + deger
    else:
        ham = deger

    if ham < 0:
        raise ZamHatasi("Yeni ücret negatif olamaz")
    adim = Decimal(str(yuvarlama or "0.01"))
    if adim <= 0:
        adim = Decimal("0.01")
    return (ham / adim).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * adim


def _kriter_sorgusu(kriterler: dict):
    stmt = select(Subscription).where(
        Subscription.is_deleted.is_(False),
        Subscription.status.in_(ZAMLANABILIR_DURUMLAR),
    )
    if kriterler.get("customer_ids"):
        stmt = stmt.where(Subscription.customer_id.in_(kriterler["customer_ids"]))
    if kriterler.get("product_ids"):
        stmt = stmt.where(Subscription.product_id.in_(kriterler["product_ids"]))
    if kriterler.get("billing_periods"):
        stmt = stmt.where(Subscription.billing_period.in_(kriterler["billing_periods"]))
    if kriterler.get("subscription_ids"):
        stmt = stmt.where(Subscription.id.in_(kriterler["subscription_ids"]))
    if kriterler.get("baslangic_once"):
        stmt = stmt.where(
            Subscription.start_date <= date.fromisoformat(kriterler["baslangic_once"])
        )
    return stmt.order_by(Subscription.subscription_no)


async def onizle(
    db: AsyncSession,
    *,
    kriterler: dict,
    yontem: str,
    deger: Decimal,
    valid_from: date,
    yuvarlama: Decimal = Decimal("0.01"),
) -> dict:
    """Zammın kime ne yapacağını YAZMADAN gösterir."""
    abonelikler = (await db.scalars(_kriter_sorgusu(kriterler))).all()
    unvanlar = {
        h.id: h.title
        for h in (
            await db.scalars(
                select(Account).where(Account.id.in_([a.customer_id for a in abonelikler] or [0]))
            )
        ).all()
    }

    etkilenen: list[dict] = []
    haric: list[dict] = []
    mrr_delta = Decimal("0")

    for a in abonelikler:
        # Taahhüt, indirimin karşılığıdır; süresi içinde bozulamaz.
        if a.commitment_end_date and a.commitment_end_date >= valid_from:
            haric.append(
                {
                    "subscription_id": a.id,
                    "subscription_no": a.subscription_no,
                    "customer_title": unvanlar.get(a.customer_id),
                    "neden": f"Taahhüt {a.commitment_end_date:%d.%m.%Y} tarihine kadar sürüyor",
                }
            )
            continue

        fiyat = await abonelik_svc.gecerli_fiyat(db, a.id, max(valid_from, a.start_date))
        if fiyat is None:
            haric.append(
                {
                    "subscription_id": a.id,
                    "subscription_no": a.subscription_no,
                    "customer_title": unvanlar.get(a.customer_id),
                    "neden": "Bu tarihte geçerli ücret kaydı yok",
                }
            )
            continue
        if fiyat.valid_from >= valid_from:
            haric.append(
                {
                    "subscription_id": a.id,
                    "subscription_no": a.subscription_no,
                    "customer_title": unvanlar.get(a.customer_id),
                    "neden": (
                        f"Ücreti zaten {fiyat.valid_from:%d.%m.%Y} tarihinden itibaren güncellenmiş"
                    ),
                }
            )
            continue

        eski = Decimal(str(fiyat.unit_price))
        yeni = yeni_fiyat(eski, yontem=yontem, deger=deger, yuvarlama=yuvarlama)
        if yeni == eski:
            haric.append(
                {
                    "subscription_id": a.id,
                    "subscription_no": a.subscription_no,
                    "customer_title": unvanlar.get(a.customer_id),
                    "neden": "Ücret değişmiyor",
                }
            )
            continue

        fark = abonelik_svc.aylik_tutar(yeni, a.billing_period) - abonelik_svc.aylik_tutar(
            eski, a.billing_period
        )
        mrr_delta += fark
        etkilenen.append(
            {
                "subscription_id": a.id,
                "subscription_no": a.subscription_no,
                "customer_id": a.customer_id,
                "customer_title": unvanlar.get(a.customer_id),
                "billing_period": a.billing_period,
                "eski_fiyat": eski,
                "yeni_fiyat": yeni,
                "fark": yuvarla(yeni - eski),
                "mrr_farki": yuvarla(fark),
                "status": a.status,
            }
        )

    return {
        "etkilenen": etkilenen,
        "haric": haric,
        "etkilenen_sayisi": len(etkilenen),
        "haric_sayisi": len(haric),
        "mrr_delta": yuvarla(mrr_delta),
    }


async def uygula(
    db: AsyncSession,
    parti: PriceBatch,
    *,
    clock: Clock,
    user_id: int | None = None,
) -> dict:
    """Partiyi uygular: ücret dönemi açar, MRR olayı yazar.

    Önizleme partinin KENDİ kriterlerinden yeniden üretilir; arayüzden gelen
    ikinci bir kriter kümesine güvenilmez.
    """
    if parti.status != "TASLAK":
        raise ZamHatasi(f"{parti.status} durumundaki parti yeniden uygulanamaz.")

    sonuc = await onizle(
        db,
        kriterler=parti.criteria or {},
        yontem=parti.method,
        deger=Decimal(str(parti.value)),
        valid_from=parti.valid_from,
        yuvarlama=Decimal(str(parti.round_to)),
    )

    for satir in sonuc["etkilenen"]:
        abonelik = await db.get(Subscription, satir["subscription_id"])
        await abonelik_svc.fiyat_yaz(
            db,
            abonelik,
            unit_price=satir["yeni_fiyat"],
            valid_from=parti.valid_from,
            neden=f"Toplu güncelleme: {parti.title}",
            batch_id=parti.id,
            user_id=user_id,
        )
        if abonelik.status == "AKTIF":
            yeni_mrr = abonelik_svc.aylik_tutar(satir["yeni_fiyat"], abonelik.billing_period)
            onceki = await abonelik_svc.mrr_simdiki(db, abonelik.id)
            await abonelik_svc.olay_yaz(
                db,
                abonelik,
                tip="ARTIS" if yeni_mrr >= onceki else "AZALIS",
                tarih=parti.valid_from,
                yeni_mrr=yeni_mrr,
                neden=f"Toplu güncelleme: {parti.title}",
                batch_id=parti.id,
                user_id=user_id,
            )

    parti.status = "UYGULANDI"
    parti.applied_at = clock.now()
    parti.applied_by = user_id
    parti.affected_count = sonuc["etkilenen_sayisi"]
    parti.excluded_count = sonuc["haric_sayisi"]
    parti.mrr_delta = sonuc["mrr_delta"]
    await db.flush()
    return sonuc


async def geri_al(
    db: AsyncSession, parti: PriceBatch, *, clock: Clock, user_id: int | None = None
) -> int:
    """Yürürlüğe GİRMEMİŞ bir partiyi bütünüyle geri alır.

    Yürürlük tarihi geçmişse geri alınmaz: o dönemin tahakkuku çıkmış
    olabilir ve geçmişi değiştirmek muhasebeyle ERP'yi ayrıştırırdı
    (plan §3.3/3 ile aynı disiplin). O durumda yeni bir parti açılır.
    """
    from app.models import SubscriptionEvent, SubscriptionPrice

    if parti.status != "UYGULANDI":
        raise ZamHatasi(f"{parti.status} durumundaki parti geri alınamaz.")
    if parti.valid_from <= clock.now().date():
        raise ZamHatasi(
            f"Zam {parti.valid_from:%d.%m.%Y} tarihinde yürürlüğe girdi; geri alınamaz. "
            "Düzeltme için ters yönde yeni bir parti açın."
        )

    satirlar = (
        await db.scalars(
            select(SubscriptionPrice).where(SubscriptionPrice.price_batch_id == parti.id)
        )
    ).all()
    for satir in satirlar:
        # Kapattığı önceki dönemi yeniden aç.
        onceki = await db.scalar(
            select(SubscriptionPrice).where(
                SubscriptionPrice.subscription_id == satir.subscription_id,
                SubscriptionPrice.valid_to == satir.valid_from,
            )
        )
        await db.delete(satir)
        await db.flush()
        if onceki is not None:
            onceki.valid_to = None
    # MRR olay zinciri de geri alınır; yoksa gelir raporu uygulanmamış bir
    # zammı göstermeye devam ederdi.
    for olay in (
        await db.scalars(
            select(SubscriptionEvent).where(SubscriptionEvent.price_batch_id == parti.id)
        )
    ).all():
        await db.delete(olay)
    await db.flush()

    parti.status = "GERI_ALINDI"
    parti.reverted_at = clock.now()
    await db.flush()
    return len(satirlar)
