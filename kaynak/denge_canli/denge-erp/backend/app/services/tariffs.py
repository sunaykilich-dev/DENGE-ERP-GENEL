"""Tarihli tarife çözümlemesi.

Brief §4.7: "Tarifeler tarihlidir (fiyat değişince eski işler eski fiyattan
hesaplanır)." Çözümleme İŞİN TAMAMLANMA TARİHİNE bakar, bugüne değil.

Öncelik: montaj noktasına özel tarife > genel varsayılan tarife.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PartnerTariff

HERHANGI = "*"


async def tarife_bul(
    db: AsyncSession,
    *,
    partner_id: int | None,
    work_type: str,
    product_group: str | None,
    an: datetime,
) -> PartnerTariff | None:
    """O tarihte geçerli tarifeyi döndürür.

    Sıra: (noktaya özel, ürün grubu) → (noktaya özel, *) →
          (genel, ürün grubu)      → (genel, *)
    """
    gruplar = [g for g in (product_group, HERHANGI) if g]
    aday = (
        await db.scalars(
            select(PartnerTariff).where(
                or_(PartnerTariff.partner_id == partner_id, PartnerTariff.partner_id.is_(None)),
                PartnerTariff.work_type == work_type,
                PartnerTariff.product_group.in_(gruplar),
                PartnerTariff.valid_from <= an,
                or_(PartnerTariff.valid_to.is_(None), PartnerTariff.valid_to > an),
            )
        )
    ).all()
    if not aday:
        return None

    def oncelik(t: PartnerTariff) -> tuple[int, int]:
        return (
            0 if t.partner_id is not None else 1,
            gruplar.index(t.product_group) if t.product_group in gruplar else 99,
        )

    return min(aday, key=oncelik)


async def birim_fiyat(
    db: AsyncSession,
    *,
    partner_id: int | None,
    work_type: str,
    product_group: str | None,
    an: datetime,
) -> tuple[Decimal | None, str]:
    """(fiyat, kaynak). Tarife yoksa (None, 'YOK') — çağıran elle fiyat ister.

    Tarife BAĞLAYICI DEĞİLDİR: dönen fiyat yalnız öneridir, iş emri kaleminde
    elle değiştirilebilir. Gerçek veride aynı nokta + aynı iş tipinde
    250/350/400 TL var; tarifeyi zorlamak dökümü gerçek ödemeyle tutmaz
    hale getirirdi.
    """
    tarife = await tarife_bul(
        db, partner_id=partner_id, work_type=work_type, product_group=product_group, an=an
    )
    if tarife is None:
        return None, "YOK"
    return Decimal(str(tarife.unit_price)), "TARIFE"
