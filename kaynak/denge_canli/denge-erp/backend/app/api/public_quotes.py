"""Müşterinin oturumsuz gördüğü teklif sayfası (brief §4.9 online kabul).

Bu yönlendirici KİMLİK DOĞRULAMASI İSTEMEZ; erişim yalnız jetona dayanır.
Bu yüzden üç kural var:

1. Jeton tahmin edilemez olmalı (`secrets.token_urlsafe(24)`).
2. Dönen veri müşterinin göremeyeceği hiçbir alanı içermemeli — maliyet,
   iç notlar, diğer müşteriler, teklif sahibi kullanıcı.
3. Süresi dolmuş veya kararı verilmiş teklifte karar UÇU KAPALIDIR.

Yerel kurulumda bu sayfa dışarıdan erişilemez; ekip kararı elle işaretler
(`/api/teklifler/{id}/karar`). Veri modeli ve uçlar hazır olduğu için
sunucuya çıkıldığında ek iş gerekmez.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import ClockDep, DbDep, client_ip
from app.models import Account, Quote, QuoteVersion
from app.services import audit
from app.services import quotes as svc

router = APIRouter(prefix="/api/public/teklif", tags=["teklif (public)"])

Jeton = Annotated[str, Path(min_length=16, max_length=64)]


class AcikKalem(BaseModel):
    description: str
    qty: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    vat_rate: Decimal
    line_total: Decimal


class AcikTeklif(BaseModel):
    """Müşteriye gösterilen alanlar — başka hiçbir şey."""

    quote_no: str
    title: str | None
    musteri: str
    version_no: int
    currency: str
    valid_until: date | None
    subtotal: Decimal
    discount_total: Decimal
    vat_total: Decimal
    grand_total: Decimal
    kalemler: list[AcikKalem]
    durum: str
    karar_verilebilir: bool


async def _versiyon_bul(db: DbDep, token: str) -> tuple[Quote, QuoteVersion]:
    v = await db.scalar(
        select(QuoteVersion)
        .where(QuoteVersion.public_token == token)
        .options(selectinload(QuoteVersion.lines))
    )
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı veya bağlantı geçersiz")
    t = await db.get(Quote, v.quote_id)
    if t is None or t.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    return t, v


def _karar_verilebilir(t: Quote, v: QuoteVersion, bugun: date) -> bool:
    if v.accepted_at or v.rejected_at:
        return False
    if t.status in ("KABUL", "RED", "SIPARISE_DONUSTU", "SURESI_DOLDU"):
        return False
    if v.valid_until and v.valid_until < bugun:
        return False
    return v.sent_at is not None


@router.get("/{token}", response_model=AcikTeklif)
async def goruntule(token: Jeton, request: Request, db: DbDep, clock: ClockDep) -> AcikTeklif:
    """Teklifi gösterir ve İLK görüntülenmeyi kaydeder (açılma takibi)."""
    t, v = await _versiyon_bul(db, token)
    # HENÜZ GÖNDERİLMEMİŞ teklif dışarı açılmaz. `sent_at` kontrolü yoktu:
    # onaysız, iskontosu tartışılan bir TASLAK teklifin tutarları oturum
    # açmadan okunabiliyordu (karar verilemiyordu ama fiyatlar görünüyordu).
    if v.sent_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    musteri = await db.get(Account, t.customer_id)

    if v.viewed_at is None:
        v.viewed_at = clock.now()
        if t.status == "GONDERILDI":
            t.status = "GORUNTULENDI"
        await audit.log(
            db,
            "quotes",
            "goruntulendi",
            entity_id=t.id,
            new_value={"versiyon": v.version_no},
            ip=client_ip(request),
        )
        await db.commit()

    return AcikTeklif(
        quote_no=t.quote_no,
        title=t.title,
        musteri=musteri.title if musteri else "",
        version_no=v.version_no,
        currency=v.currency,
        valid_until=v.valid_until,
        subtotal=v.subtotal,
        discount_total=v.discount_total,
        vat_total=v.vat_total,
        grand_total=v.grand_total,
        kalemler=[
            AcikKalem(
                description=k.description,
                qty=k.qty,
                unit_price=k.unit_price,
                discount_pct=k.discount_pct,
                vat_rate=k.vat_rate,
                line_total=k.line_total,
            )
            for k in sorted(v.lines, key=lambda x: (x.sort_order, x.id))
        ],
        durum=t.status,
        karar_verilebilir=_karar_verilebilir(t, v, clock.now().date()),
    )


class AcikKararIn(BaseModel):
    kabul: bool
    red_nedeni: str | None = Field(default=None, max_length=300)


@router.post("/{token}/karar", response_model=AcikTeklif)
async def karar(
    token: Jeton, payload: AcikKararIn, request: Request, db: DbDep, clock: ClockDep
) -> AcikTeklif:
    """Müşterinin kabul/red kaydı. Tarih, saat ve kanal saklanır."""
    t, v = await _versiyon_bul(db, token)
    if not _karar_verilebilir(t, v, clock.now().date()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu teklif için karar verilemez (süresi dolmuş, henüz gönderilmemiş "
            "veya daha önce yanıtlanmış olabilir).",
        )
    if not payload.kabul and not payload.red_nedeni:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Red nedeni seçilmelidir")

    await svc.karar_ver(
        db,
        v,
        kabul=payload.kabul,
        clock=clock,
        kanal="LINK",
        red_nedeni=payload.red_nedeni,
    )
    await audit.log(
        db,
        "quotes",
        "karar",
        entity_id=t.id,
        new_value={"kabul": payload.kabul, "kanal": "LINK", "neden": payload.red_nedeni},
        ip=client_ip(request),
    )
    await db.commit()
    return await goruntule(token, request, db, clock)
