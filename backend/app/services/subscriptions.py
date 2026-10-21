"""Abonelik iş kuralları: tarihli ücret, kıst hesap, aylık tahakkuk, MRR.

Kıst (pro-rata) kuralı: **dönemdeki aktif gün / dönemdeki toplam gün.**
Tam ay aktifse orantı hiç uygulanmaz, aylık tutar aynen yazılır — 30/31
çarpanı tam aylarda kuruş kaymasına yol açardı.

Askıya alınan günler tahakkuktan DÜŞER ve askı aralıkları `subscription_events`
üzerinden çıkarılır; ayrı bir askı tablosu, aynı bilgiyi iki yerde tutmak
olurdu.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Account,
    Subscription,
    SubscriptionEvent,
    SubscriptionPrice,
)
from app.models.subscription import PERIYOT_AY
from app.services.quotes import yuvarla
from app.services.statemachine import ABONELIK


class AbonelikHatasi(ValueError):
    """Abonelik kurallarına aykırı işlem."""


# --- Dönem ve tutar yardımcıları ---------------------------------------------


def donem_araligi(donem: str) -> tuple[date, date]:
    """'2026-03' → (2026-03-01, 2026-03-31)."""
    yil, ay = (int(p) for p in donem.split("-"))
    return date(yil, ay, 1), date(yil, ay, calendar.monthrange(yil, ay)[1])


def aylik_tutar(unit_price: Decimal, billing_period: str) -> Decimal:
    """Fatura periyodunu aylık yinelenen gelire normalize eder."""
    ay = PERIYOT_AY.get(billing_period)
    if ay is None:
        raise AbonelikHatasi(f"Bilinmeyen fatura periyodu: {billing_period}")
    return yuvarla(Decimal(str(unit_price)) / Decimal(ay))


def _kesisim_gun(a1: date, a2: date, b1: date, b2: date) -> int:
    """İki kapalı tarih aralığının kesişimindeki gün sayısı."""
    bas, son = max(a1, b1), min(a2, b2)
    return (son - bas).days + 1 if son >= bas else 0


# --- Tarihli ücret ------------------------------------------------------------


async def gecerli_fiyat(
    db: AsyncSession, subscription_id: int, tarih: date
) -> SubscriptionPrice | None:
    return await db.scalar(
        select(SubscriptionPrice).where(
            SubscriptionPrice.subscription_id == subscription_id,
            SubscriptionPrice.valid_from <= tarih,
            (SubscriptionPrice.valid_to.is_(None)) | (SubscriptionPrice.valid_to > tarih),
        )
    )


async def fiyat_yaz(
    db: AsyncSession,
    abonelik: Subscription,
    *,
    unit_price: Decimal,
    valid_from: date,
    neden: str | None = None,
    batch_id: int | None = None,
    user_id: int | None = None,
) -> SubscriptionPrice:
    """Yeni ücret dönemi açar; açık dönemi kapatır.

    Geçmişe dönük fiyat yazılamaz: tahakkuku çıkmış bir ayı sonradan
    değiştirmek, muhasebeyle ERP'yi ayrıştırırdı (plan §3.3/3 ile aynı
    disiplin).
    """
    acik = await db.scalar(
        select(SubscriptionPrice).where(
            SubscriptionPrice.subscription_id == abonelik.id,
            SubscriptionPrice.valid_to.is_(None),
        )
    )
    if acik is not None:
        if valid_from <= acik.valid_from:
            raise AbonelikHatasi(
                f"Yeni ücret {acik.valid_from:%d.%m.%Y} tarihli mevcut ücretten sonra başlamalı."
            )
        acik.valid_to = valid_from

    kayit = SubscriptionPrice(
        subscription_id=abonelik.id,
        unit_price=Decimal(str(unit_price)),
        valid_from=valid_from,
        change_reason=neden,
        price_batch_id=batch_id,
        created_by=user_id,
    )
    db.add(kayit)
    await db.flush()
    return kayit


# --- MRR olayları -------------------------------------------------------------


async def mrr_simdiki(db: AsyncSession, subscription_id: int) -> Decimal:
    """Bu aboneliğin olay kayıtlarına göre güncel MRR katkısı."""
    son = await db.scalar(
        select(SubscriptionEvent.mrr_after)
        .where(SubscriptionEvent.subscription_id == subscription_id)
        .order_by(SubscriptionEvent.event_date.desc(), SubscriptionEvent.id.desc())
        .limit(1)
    )
    return Decimal(str(son or 0))


async def olay_yaz(
    db: AsyncSession,
    abonelik: Subscription,
    *,
    tip: str,
    tarih: date,
    yeni_mrr: Decimal,
    neden: str | None = None,
    batch_id: int | None = None,
    user_id: int | None = None,
) -> SubscriptionEvent:
    """MRR olayı kaydeder — 'bu ay MRR neden değişti' sorusunun satırı."""
    onceki = await mrr_simdiki(db, abonelik.id)
    yeni_mrr = yuvarla(Decimal(str(yeni_mrr)))
    olay = SubscriptionEvent(
        subscription_id=abonelik.id,
        customer_id=abonelik.customer_id,
        event_type=tip,
        event_date=tarih,
        mrr_before=onceki,
        mrr_after=yeni_mrr,
        mrr_delta=yuvarla(yeni_mrr - onceki),
        reason=neden,
        price_batch_id=batch_id,
        created_by=user_id,
    )
    db.add(olay)
    await db.flush()
    return olay


# --- Yaşam döngüsü ------------------------------------------------------------


async def numara_uret(db: AsyncSession, clock: Clock) -> str:
    sira = (
        await db.scalar(select(Subscription.id).order_by(Subscription.id.desc()).limit(1)) or 0
    ) + 1
    return f"ABN{clock.now():%Y}-{sira:05d}"


async def durum_degistir(
    db: AsyncSession,
    abonelik: Subscription,
    hedef: str,
    *,
    clock: Clock,
    tarih: date | None = None,
    neden: str | None = None,
    user_id: int | None = None,
) -> Subscription:
    """Tek geçiş yolu: kural kontrolü + MRR olayı birlikte yazılır.

    Durum alanına doğrudan atama yapılırsa MRR olay zinciri kopar ve churn
    raporu sessizce yanlışlanır.
    """
    ABONELIK.dogrula(abonelik.status, hedef)
    gun = tarih or clock.now().date()

    if hedef == "AKTIF":
        fiyat = await gecerli_fiyat(db, abonelik.id, gun)
        if fiyat is None:
            raise AbonelikHatasi("Abonelik ücreti tanımlanmadan aktifleştirilemez.")
        yeni_mrr = aylik_tutar(fiyat.unit_price, abonelik.billing_period)
        tip = "GERI_DONUS" if abonelik.status in ("ASKIDA", "SONA_ERDI") else "YENI"
        abonelik.suspended_at = None
    elif hedef == "ASKIDA":
        yeni_mrr, tip = Decimal("0"), "ASKI"
        abonelik.suspended_at = clock.now()
    elif hedef == "IPTAL":
        if not neden:
            raise AbonelikHatasi("İptal nedeni zorunlu — churn analizi buna dayanır.")
        yeni_mrr, tip = Decimal("0"), "IPTAL"
        abonelik.cancelled_at = clock.now()
        abonelik.cancel_reason = neden
        if abonelik.end_date is None or abonelik.end_date > gun:
            abonelik.end_date = gun
    else:  # SONA_ERDI
        yeni_mrr, tip = Decimal("0"), "SONA_ERDI"
        if abonelik.end_date is None or abonelik.end_date > gun:
            abonelik.end_date = gun

    abonelik.status = hedef
    await olay_yaz(
        db, abonelik, tip=tip, tarih=gun, yeni_mrr=yeni_mrr, neden=neden, user_id=user_id
    )
    await db.flush()
    return abonelik


async def yenile(
    db: AsyncSession,
    abonelik: Subscription,
    *,
    clock: Clock,
    ay: int | None = None,
    user_id: int | None = None,
) -> Subscription:
    """Sözleşmeyi uzatır — bitiş tarihini ileri atar, durum değişmez."""
    if abonelik.status not in ("AKTIF", "ASKIDA"):
        raise AbonelikHatasi(f"{abonelik.status} durumundaki abonelik yenilenemez.")
    if abonelik.renewal_type == "YOK":
        raise AbonelikHatasi("Bu sözleşme yenilemeye kapalı.")

    sure = ay or abonelik.renewal_months
    temel = abonelik.end_date or clock.now().date()
    yil, toplam_ay = divmod(temel.month - 1 + sure, 12)
    hedef_ay = toplam_ay + 1
    hedef_yil = temel.year + yil
    gun = min(temel.day, calendar.monthrange(hedef_yil, hedef_ay)[1])
    abonelik.end_date = date(hedef_yil, hedef_ay, gun)
    await db.flush()
    return abonelik


async def yenilenecekler(db: AsyncSession, clock: Clock, *, gun: int = 30) -> list[dict]:
    """Bitişine `gun` kalan aktif abonelikler — yenileme hatırlatması."""
    bugun = clock.now().date()
    sinir = date.fromordinal(bugun.toordinal() + gun)
    satirlar = (
        await db.execute(
            select(Subscription, Account.title)
            .join(Account, Account.id == Subscription.customer_id)
            .where(
                Subscription.is_deleted.is_(False),
                Subscription.status.in_(("AKTIF", "ASKIDA")),
                Subscription.end_date.is_not(None),
                Subscription.end_date <= sinir,
            )
            .order_by(Subscription.end_date)
        )
    ).all()
    return [
        {
            "subscription_id": s.id,
            "subscription_no": s.subscription_no,
            "customer_id": s.customer_id,
            "customer_title": unvan,
            "end_date": s.end_date,
            "kalan_gun": (s.end_date - bugun).days,
            "renewal_type": s.renewal_type,
            "status": s.status,
        }
        for s, unvan in satirlar
    ]


# --- Kıst hesap ve aylık tahakkuk ---------------------------------------------


async def _askida_gunler(
    db: AsyncSession, subscription_id: int, donem_bas: date, donem_son: date
) -> int:
    """Dönem içinde askıda geçen gün sayısı — ASKI/GERI_DONUS olaylarından.

    Dönem başında zaten askıdaysa (önceki bir ASKI olayı açık kalmışsa)
    dönemin başından itibaren sayılır.
    """
    olaylar = (
        await db.scalars(
            select(SubscriptionEvent)
            .where(
                SubscriptionEvent.subscription_id == subscription_id,
                SubscriptionEvent.event_type.in_(("ASKI", "GERI_DONUS")),
                SubscriptionEvent.event_date <= donem_son,
            )
            .order_by(SubscriptionEvent.event_date, SubscriptionEvent.id)
        )
    ).all()

    gun = 0
    aski_baslangic: date | None = None
    for o in olaylar:
        if o.event_type == "ASKI" and aski_baslangic is None:
            aski_baslangic = o.event_date
        elif o.event_type == "GERI_DONUS" and aski_baslangic is not None:
            gun += _kesisim_gun(
                aski_baslangic, o.event_date - timedelta(days=1), donem_bas, donem_son
            )
            aski_baslangic = None
    if aski_baslangic is not None:
        gun += _kesisim_gun(aski_baslangic, donem_son, donem_bas, donem_son)
    return gun


def kist_tutar(aylik: Decimal, *, donem_bas: date, donem_son: date, aktif_gun: int) -> Decimal:
    """Gün bazlı kıst. Tam ay aktifse orantı UYGULANMAZ."""
    ay_gun = (donem_son - donem_bas).days + 1
    if aktif_gun <= 0:
        return Decimal("0")
    if aktif_gun >= ay_gun:
        return yuvarla(Decimal(str(aylik)))
    return yuvarla(Decimal(str(aylik)) * Decimal(aktif_gun) / Decimal(ay_gun))


async def donem_tahakkuku(db: AsyncSession, donem: str) -> list[dict]:
    """Bir ayın abonelik tahakkuk listesi — Logo'ya aktarılacak satırlar.

    Hesaplanır, saklanmaz: ücret geçmişi ve olay kayıtları tarihli olduğu
    için aynı dönem her zaman aynı sonucu verir. Muhasebenin kaydı Logo'da
    durur; ERP'nin ikinci bir 'kapanmış tahakkuk' defteri tutması, iki
    kaynağın er geç ayrışması demekti.
    """
    donem_bas, donem_son = donem_araligi(donem)
    ay_gun = (donem_son - donem_bas).days + 1

    satirlar = (
        await db.execute(
            select(Subscription, Account.title)
            .join(Account, Account.id == Subscription.customer_id)
            .where(
                Subscription.is_deleted.is_(False),
                Subscription.status != "TASLAK",
                Subscription.start_date <= donem_son,
                (Subscription.end_date.is_(None)) | (Subscription.end_date >= donem_bas),
            )
            .order_by(Account.title, Subscription.subscription_no)
        )
    ).all()

    sonuc: list[dict] = []
    for s, unvan in satirlar:
        kapsam = _kesisim_gun(s.start_date, s.end_date or donem_son, donem_bas, donem_son)
        if kapsam <= 0:
            continue
        askida = await _askida_gunler(db, s.id, donem_bas, donem_son)
        aktif_gun = max(0, kapsam - askida)
        if aktif_gun <= 0:
            continue

        fiyat = await gecerli_fiyat(db, s.id, max(s.start_date, donem_bas))
        if fiyat is None:
            continue
        aylik = aylik_tutar(fiyat.unit_price, s.billing_period)
        tutar = kist_tutar(aylik, donem_bas=donem_bas, donem_son=donem_son, aktif_gun=aktif_gun)
        kdv = yuvarla(tutar * Decimal(str(s.vat_rate)))
        sonuc.append(
            {
                "donem": donem,
                "subscription_id": s.id,
                "subscription_no": s.subscription_no,
                "customer_id": s.customer_id,
                "customer_title": unvan,
                "vehicle_id": s.vehicle_id,
                "device_id": s.device_id,
                "title": s.title,
                "billing_period": s.billing_period,
                "birim_fiyat": Decimal(str(fiyat.unit_price)),
                "aylik_tutar": aylik,
                "aktif_gun": aktif_gun,
                "donem_gun": ay_gun,
                "kist": aktif_gun < ay_gun,
                "tutar": tutar,
                "kdv_orani": Decimal(str(s.vat_rate)),
                "kdv": kdv,
                "toplam": yuvarla(tutar + kdv),
                "currency": s.currency,
            }
        )
    return sonuc


# --- MRR ve churn -------------------------------------------------------------


async def mrr(db: AsyncSession, tarih: date) -> Decimal:
    """Verilen tarihteki aylık yinelenen gelir — olay toplamı."""
    toplam = await db.scalar(
        select(func.coalesce(func.sum(SubscriptionEvent.mrr_delta), 0)).where(
            SubscriptionEvent.event_date <= tarih
        )
    )
    return yuvarla(Decimal(str(toplam or 0)))


async def mrr_hareketi(db: AsyncSession, donem: str) -> dict:
    """Dönem içindeki MRR değişiminin olay tipine göre dökümü.

    'Bu ay MRR neden düştü' sorusu bu tabloyla cevaplanır.
    """
    donem_bas, donem_son = donem_araligi(donem)
    bas_mrr = await mrr(db, date.fromordinal(donem_bas.toordinal() - 1))

    satirlar = (
        await db.execute(
            select(
                SubscriptionEvent.event_type,
                func.count().label("adet"),
                func.coalesce(func.sum(SubscriptionEvent.mrr_delta), 0).label("delta"),
            )
            .where(
                SubscriptionEvent.event_date >= donem_bas,
                SubscriptionEvent.event_date <= donem_son,
            )
            .group_by(SubscriptionEvent.event_type)
        )
    ).all()

    hareket = {
        tip: {"adet": adet, "delta": yuvarla(Decimal(str(delta)))} for tip, adet, delta in satirlar
    }
    kayip = sum(
        (hareket.get(t, {}).get("delta", Decimal("0")) for t in ("IPTAL", "SONA_ERDI", "ASKI")),
        Decimal("0"),
    )
    return {
        "donem": donem,
        "baslangic_mrr": bas_mrr,
        "bitis_mrr": await mrr(db, donem_son),
        "hareket": hareket,
        # Churn oranı dönem başı MRR'a göre; dönem başı sıfırsa tanımsızdır.
        "churn_yuzde": (yuvarla(-kayip / bas_mrr * Decimal("100")) if bas_mrr > 0 else None),
    }
