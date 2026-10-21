"""Teklif iş kuralları: versiyonlama, hesaplama, onay ve karar."""

import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Product, Quote, QuoteLine, QuoteVersion
from app.models.quote import KALEM_TIPLERI
from app.services import settings as ayar_svc

KURUS = Decimal("0.01")


def yuvarla(d: Decimal) -> Decimal:
    return d.quantize(KURUS, rounding=ROUND_HALF_UP)


class TeklifKilitli(Exception):
    """Gönderilmiş versiyon değiştirilemez; revizyon yeni versiyon açar."""


def kalem_topla(qty: Decimal, unit_price: Decimal, discount_pct: Decimal) -> Decimal:
    """İskonto kalem bazında uygulanır."""
    brut = Decimal(str(qty)) * Decimal(str(unit_price))
    return yuvarla(brut * (Decimal("1") - Decimal(str(discount_pct)) / Decimal("100")))


async def versiyon_hesapla(db: AsyncSession, versiyon: QuoteVersion) -> QuoteVersion:
    """Kalemlerden versiyon toplamlarını yeniden hesaplar.

    KDV kalem bazında hesaplanır (oranlar kalemde dondurulmuştur); tek bir
    genel oran uygulamak farklı KDV'li kalemleri olan teklifleri bozardı.
    """
    kalemler = (
        await db.scalars(select(QuoteLine).where(QuoteLine.version_id == versiyon.id))
    ).all()

    ara = Decimal("0")
    iskonto = Decimal("0")
    kdv = Decimal("0")
    en_yuksek_iskonto = Decimal("0")

    for k in kalemler:
        brut = Decimal(str(k.qty)) * Decimal(str(k.unit_price))
        net = kalem_topla(k.qty, k.unit_price, k.discount_pct)
        k.line_total = net
        ara += brut
        iskonto += brut - net
        kdv += yuvarla(net * Decimal(str(k.vat_rate)))
        en_yuksek_iskonto = max(en_yuksek_iskonto, Decimal(str(k.discount_pct)))

    versiyon.subtotal = yuvarla(ara)
    versiyon.discount_total = yuvarla(iskonto)
    versiyon.vat_total = yuvarla(kdv)
    versiyon.grand_total = yuvarla(ara - iskonto + kdv)
    versiyon.max_discount_pct = en_yuksek_iskonto
    await db.flush()
    return versiyon


async def onay_gerekiyor_mu(db: AsyncSession, versiyon: QuoteVersion) -> bool:
    """Eşik üstü iskonto satış müdürü onayına düşer (brief §4.9)."""
    esik = Decimal(str(await ayar_svc.get(db, "iskonto_onay_esigi_yuzde")))
    return Decimal(str(versiyon.max_discount_pct)) > esik


async def yeni_versiyon(
    db: AsyncSession, teklif: Quote, *, clock: Clock, kaynak: QuoteVersion | None = None
) -> QuoteVersion:
    """Yeni versiyon açar; öncekini KİLİTLER ve kalemleri kopyalar.

    Kopyalama fiyatları da taşır — revizyon yaparken ürün kartındaki güncel
    fiyat değil, müşteriye gösterilen fiyat esastır.
    """
    son_no = (
        await db.scalar(
            select(func.coalesce(func.max(QuoteVersion.version_no), 0)).where(
                QuoteVersion.quote_id == teklif.id
            )
        )
        or 0
    )
    if kaynak is not None:
        kaynak.is_locked = True

    gecerlilik_gun = int(await ayar_svc.get(db, "teklif_varsayilan_gecerlilik_gun"))
    yeni = QuoteVersion(
        quote_id=teklif.id,
        version_no=son_no + 1,
        currency=kaynak.currency if kaynak else "TRY",
        fx_rate=kaynak.fx_rate if kaynak else None,
        fx_date=kaynak.fx_date if kaynak else None,
        fx_source=kaynak.fx_source if kaynak else None,
        valid_until=(clock.now().date() + timedelta(days=gecerlilik_gun)),
        public_token=secrets.token_urlsafe(24),
    )
    db.add(yeni)
    await db.flush()

    if kaynak is not None:
        for k in (
            await db.scalars(select(QuoteLine).where(QuoteLine.version_id == kaynak.id))
        ).all():
            db.add(
                QuoteLine(
                    version_id=yeni.id,
                    item_type=k.item_type,
                    product_id=k.product_id,
                    description=k.description,
                    qty=k.qty,
                    unit_price=k.unit_price,
                    discount_pct=k.discount_pct,
                    vat_rate=k.vat_rate,
                    sort_order=k.sort_order,
                )
            )
        await db.flush()
        await versiyon_hesapla(db, yeni)

    teklif.current_version_id = yeni.id
    await db.flush()
    return yeni


async def urun_kaleminden(
    db: AsyncSession, product_id: int, qty: Decimal, *, iskonto: Decimal = Decimal("0")
) -> dict:
    """Ürün kartından kalem verisi üretir; fiyat ve KDV DONDURULUR."""
    urun = await db.get(Product, product_id)
    if urun is None:
        raise ValueError(f"Ürün bulunamadı: {product_id}")
    varsayilan_kdv = Decimal(str(await ayar_svc.get(db, "kdv_oran_varsayilan")))
    return {
        "item_type": "URUN",
        "product_id": urun.id,
        "description": urun.name,
        "qty": qty,
        "unit_price": Decimal(str(urun.list_price or 0)),
        "discount_pct": iskonto,
        "vat_rate": Decimal(str(urun.vat_rate)) if urun.vat_rate else varsayilan_kdv,
    }


async def kalem_alanlari(
    db: AsyncSession,
    *,
    item_type: str,
    product_id: int | None,
    description: str | None,
    qty: Decimal,
    unit_price: Decimal | None,
    discount_pct: Decimal,
    vat_rate: Decimal | None,
) -> dict:
    """Bir belge kaleminin DONDURULACAK alanlarını üretir.

    Teklif ve sipariş kalemleri aynı kurallara tabi (plan §3.3/2), bu yüzden
    tek yerde durur: ürün kartı varsayılanları taban alınır, elle verilen
    değerler onu geçersiz kılar, ürünsüz kalemde açıklama ve fiyat zorunludur.
    """
    if item_type not in KALEM_TIPLERI:
        raise ValueError(f"Kalem tipi {KALEM_TIPLERI} içinden olmalı")

    if product_id:
        veri = await urun_kaleminden(db, product_id, qty, iskonto=discount_pct)
        veri["item_type"] = item_type
        if unit_price is not None:
            veri["unit_price"] = unit_price
        if description:
            veri["description"] = description
        if vat_rate is not None:
            veri["vat_rate"] = vat_rate
        return veri

    if unit_price is None or not description:
        raise ValueError("Ürünsüz kalemde açıklama ve birim fiyat zorunludur")
    varsayilan_kdv = Decimal(str(await ayar_svc.get(db, "kdv_oran_varsayilan")))
    return {
        "item_type": item_type,
        "product_id": None,
        "description": description,
        "qty": qty,
        "unit_price": unit_price,
        "discount_pct": discount_pct,
        "vat_rate": vat_rate if vat_rate is not None else varsayilan_kdv,
    }


async def suresi_dolanlari_isaretle(db: AsyncSession, clock: Clock) -> int:
    """Geçerlilik tarihi geçen teklifleri SURESI_DOLDU yapar.

    Kabul edilmiş veya siparişe dönmüş teklifler etkilenmez — geçmişe dönük
    bir süre dolması, tamamlanmış işi geçersiz göstermek olurdu.
    """
    bugun = clock.now().date()
    teklifler = (
        await db.execute(
            select(Quote, QuoteVersion)
            .join(QuoteVersion, QuoteVersion.id == Quote.current_version_id)
            .where(
                Quote.is_deleted.is_(False),
                Quote.status.in_(("GONDERILDI", "GORUNTULENDI", "REVIZE_EDILDI")),
                QuoteVersion.valid_until.is_not(None),
                QuoteVersion.valid_until < bugun,
            )
        )
    ).all()
    for teklif, _ in teklifler:
        teklif.status = "SURESI_DOLDU"
    await db.flush()
    return len(teklifler)


async def karar_ver(
    db: AsyncSession,
    versiyon: QuoteVersion,
    *,
    kabul: bool,
    clock: Clock,
    kanal: str,
    red_nedeni: str | None = None,
) -> Quote:
    """Kabul veya red kaydeder.

    `kanal` LİNK ise müşteri kendi tıkladı, ELLE ise ekip işaretledi — ikisi
    aynı kanıt değeri taşımaz, bu yüzden ayrı tutulur.
    """
    simdi = clock.now()
    teklif = await db.get(Quote, versiyon.quote_id)
    if kabul:
        versiyon.accepted_at = simdi
        teklif.status = "KABUL"
    else:
        versiyon.rejected_at = simdi
        versiyon.reject_reason = red_nedeni
        teklif.status = "RED"
        teklif.lost_reason = red_nedeni
    versiyon.decision_channel = kanal
    versiyon.is_locked = True
    await db.flush()
    return teklif


def public_url(taban: str, token: str) -> str:
    return f"{taban.rstrip('/')}/teklif/{token}"
