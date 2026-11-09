"""Sipariş belgeleri: sipariş onayı PDF'i ve muhasebe devri (KARARLAR 2026-11-09 S4.4, S6).

* **Sipariş onayı** müşteriye "siparişinizi aldık" belgesidir; TASLAK ve
  İPTAL siparişte basılmaz (409). Fiyatlıdır: sipariş fiyatı `siparis.gor`
  sahibine sipariş ekranında zaten açık. Maliyet basılmaz.
* **Muhasebe devri** servis işlerindeki fatura devri kalıbıdır (`fatura_devri`):
  toplu işaret bütündür, geri alma gerekçe ister, her adım denetime yazılır.
  Uygun sipariş: TASLAK/İPTAL olmayan ve henüz devredilmemiş.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models import Account, Irsaliye, Order, OrderLine, User
from app.services import audit
from app.services.belgeler import _sade, ayar_haritasi, firma_bilgisi
from app.services.pdf import tl

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

ONAY_BASILMAZ = ("TASLAK", "IPTAL")
DEVRE_UYGUN_DEGIL = ("TASLAK", "IPTAL")
AZAMI_TOPLU = 200
NOT_UZUNLUGU = 300


class SiparisBelgeHatasi(ValueError):
    def __init__(self, mesaj: str, *, sorunlu: list[int] | None = None) -> None:
        super().__init__(mesaj)
        self.sorunlu = sorunlu or []


class SiparisBelgeGirdiHatasi(ValueError):
    pass


def kapsam_kosulu(stmt: Select, user: User) -> Select:
    if user.role.scope == "KENDI_MUSTERILERI":
        stmt = stmt.where(Order.owner_id == user.id)
    return stmt


# --- Sipariş onayı PDF ---------------------------------------------------------------


async def onay_baglami(db: AsyncSession, siparis: Order) -> dict[str, Any]:
    from app.services.irsaliye import _alici_adresi

    if siparis.status in ONAY_BASILMAZ:
        raise SiparisBelgeHatasi(
            f"{siparis.status} durumundaki sipariş için onay belgesi basılmaz."
        )
    musteri = await db.get(Account, siparis.customer_id)
    sahip = await db.get(User, siparis.owner_id) if siparis.owner_id else None
    kalemler = (
        await db.scalars(
            select(OrderLine)
            .where(OrderLine.order_id == siparis.id)
            .order_by(OrderLine.sort_order, OrderLine.id)
        )
    ).all()
    para = "₺" if siparis.currency == "TRY" else siparis.currency
    return {
        "siparis": siparis,
        "musteri": musteri,
        "adres": await _alici_adresi(db, siparis.customer_id),
        "hazirlayan": sahip.full_name if sahip else "—",
        "tarih": siparis.order_date.strftime("%d.%m.%Y"),
        "istenen_tarih": siparis.requested_date.strftime("%d.%m.%Y")
        if siparis.requested_date
        else None,
        "para": para,
        "kur": tl(siparis.fx_rate) if siparis.fx_rate else None,
        "kalemler": [
            {
                "description": k.description,
                "qty": _sade(k.qty),
                "unit_price": tl(k.unit_price),
                "discount_pct": _sade(k.discount_pct),
                "iskonto_var": Decimal(str(k.discount_pct)) > 0,
                "vat_pct": _sade(Decimal(str(k.vat_rate)) * 100),
                "line_total": tl(k.line_total),
            }
            for k in kalemler
        ],
        "toplam": {
            "ara": tl(siparis.subtotal),
            "iskonto": tl(siparis.discount_total),
            "iskonto_var": Decimal(str(siparis.discount_total)) > 0,
            "kdv": tl(siparis.vat_total),
            "genel": tl(siparis.grand_total),
        },
        "notlar": siparis.notes,
        "firma": firma_bilgisi(await ayar_haritasi(db)),
    }


async def onay_pdf(db: AsyncSession, siparis: Order) -> bytes:
    from app.services.pdf import pdf_uret_async

    return await pdf_uret_async("siparis_onayi.html", **await onay_baglami(db, siparis))


# --- Muhasebe devri -----------------------------------------------------------------


@dataclass
class DevirSuzgeci:
    devir: str = "bekleyen"  # bekleyen | devredildi
    musteri_id: int | None = None
    donem: str | None = None  # YYYY-AA (sipariş tarihi)


def devir_sorgusu(user: User, s: DevirSuzgeci) -> Select:
    from app.services.irsaliye import donem_araligi

    stmt = select(Order).where(Order.is_deleted.is_(False))
    if s.devir == "bekleyen":
        stmt = stmt.where(
            Order.status.not_in(DEVRE_UYGUN_DEGIL), Order.muhasebe_devri_at.is_(None)
        ).order_by(Order.order_date, Order.id)
    elif s.devir == "devredildi":
        stmt = stmt.where(Order.muhasebe_devri_at.is_not(None)).order_by(
            Order.muhasebe_devri_at.desc(), Order.id
        )
    else:
        raise SiparisBelgeGirdiHatasi(f"Bilinmeyen devir durumu: {s.devir}")
    if s.musteri_id is not None:
        stmt = stmt.where(Order.customer_id == s.musteri_id)
    if s.donem:
        bas, bit = donem_araligi(s.donem)
        stmt = stmt.where(Order.order_date >= bas, Order.order_date < bit)
    return kapsam_kosulu(stmt, user)


def _not(deger: str | None) -> str | None:
    metin = (deger or "").strip() or None
    if metin is not None and len(metin) > NOT_UZUNLUGU:
        raise SiparisBelgeGirdiHatasi(f"Not en çok {NOT_UZUNLUGU} karakter olabilir")
    return metin


async def devret(
    db: AsyncSession,
    user: User,
    idler: list[int],
    *,
    not_: str | None,
    clock: Clock,
    ip: str | None = None,
) -> list[int]:
    temiz = sorted({int(i) for i in idler})
    if not temiz:
        raise SiparisBelgeGirdiHatasi("En az bir sipariş seçilmeli")
    if len(temiz) > AZAMI_TOPLU:
        raise SiparisBelgeGirdiHatasi(f"Tek seferde en çok {AZAMI_TOPLU} kayıt işaretlenebilir")
    metin = _not(not_)
    kayitlar = (
        await db.scalars(
            kapsam_kosulu(
                select(Order).where(Order.id.in_(temiz), Order.is_deleted.is_(False)), user
            ).with_for_update()
        )
    ).all()
    uygun = {
        o.id: o
        for o in kayitlar
        if o.status not in DEVRE_UYGUN_DEGIL and o.muhasebe_devri_at is None
    }
    sorunlu = [i for i in temiz if i not in uygun]
    if sorunlu:
        raise SiparisBelgeHatasi(
            "Seçilen siparişlerin bazıları devre uygun değil (taslak, iptal, zaten "
            "devredilmiş ya da bulunamadı); hiçbiri işaretlenmedi",
            sorunlu=sorunlu,
        )
    simdi = clock.now()
    for i in temiz:
        o = uygun[i]
        o.muhasebe_devri_at = simdi
        o.muhasebe_devri_by = user.id
        o.muhasebe_notu = metin
        o.updated_by = user.id
        await audit.log(
            db,
            "orders",
            "muhasebe.devredildi",
            entity_id=o.id,
            new_value={"no": o.order_no, "not": metin},
            user_id=user.id,
            ip=ip,
        )
    await db.flush()
    return temiz


async def devri_geri_al(
    db: AsyncSession, user: User, siparis: Order, *, gerekce: str, ip: str | None = None
) -> Order:
    metin = _not(gerekce)
    if metin is None:
        raise SiparisBelgeGirdiHatasi("Geri alma gerekçesi zorunlu")
    if siparis.muhasebe_devri_at is None:
        raise SiparisBelgeHatasi("Sipariş muhasebeye devredilmemiş", sorunlu=[siparis.id])
    eski = {
        "muhasebe_devri_at": siparis.muhasebe_devri_at.isoformat(),
        "muhasebe_devri_by": siparis.muhasebe_devri_by,
        "muhasebe_notu": siparis.muhasebe_notu,
    }
    siparis.muhasebe_devri_at = None
    siparis.muhasebe_devri_by = None
    siparis.muhasebe_notu = None
    siparis.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        "orders",
        "muhasebe.geri_al",
        entity_id=siparis.id,
        old_value=eski,
        new_value={"no": siparis.order_no, "gerekce": metin},
        user_id=user.id,
        ip=ip,
    )
    return siparis


async def irsaliye_ozetleri(db: AsyncSession, order_id: int) -> list[dict[str, Any]]:
    return [
        {
            "id": i.id,
            "irsaliye_no": i.irsaliye_no,
            "durum": i.durum,
            "duzenleme_tarihi": i.duzenleme_tarihi,
            "transfer_id": i.transfer_id,
        }
        for i in (
            await db.scalars(
                select(Irsaliye).where(Irsaliye.order_id == order_id).order_by(Irsaliye.id)
            )
        ).all()
    ]
