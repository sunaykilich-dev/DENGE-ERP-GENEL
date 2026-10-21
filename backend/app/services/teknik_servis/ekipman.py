"""Kurulu ekipman kütüğü: tek yazma kapısı, geçmiş, seri eşleşmesi (E03, TS-050…057).

İSKELET (D0-S) — uygulama D1-E paketinindir.

Bütün modüller (atölye bul-veya-aç dahil) yalnız `olustur/guncelle` çağırır
(E03-D02): mükerrer anahtarı (tip, marka anahtarı, seri anahtarı) + advisory
lock → 409, `duplicate_ack_reason` ile geçilir; denetim izi irtibat
alanlarında ayrı `is_personal_data=True` satırı. Durum yalnız
`SERVIS_EKIPMANI` makinesiyle. Seri eşleşmesi yalnız `normalize_seri` ile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from app.services.teknik_servis.kancalar import ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceEquipment, User


class EkipmanHatasi(ServisHatasi):
    """Ekipman kural ihlali → 409."""


@dataclass
class EkipmanGirdisi:
    birim: str
    equipment_type: str
    account_id: int | None = None
    address_id: int | None = None
    contact_id: int | None = None
    product_id: int | None = None
    brand: str | None = None
    model: str | None = None
    serial_no: str | None = None
    zone: str | None = None
    install_date: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    warranty_source: str | None = None
    lifecycle_status: str = "BILINMIYOR"
    duplicate_ack_reason: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Eslesme:
    durum: Literal["TEK", "BELIRSIZ", "YOK"]
    ekipman_id: int | None = None


async def olustur(
    db: AsyncSession, girdi: EkipmanGirdisi, *, user: User, clock: Clock
) -> ServiceEquipment:
    raise NotImplementedError("ekipman.olustur: D1-E paketi (TS-050) uygular")


async def guncelle(
    db: AsyncSession, ekipman: ServiceEquipment, degisiklikler: dict, *, user: User, clock: Clock
) -> ServiceEquipment:
    raise NotImplementedError("ekipman.guncelle: D1-E paketi (TS-050) uygular")


async def durum_degistir(
    db: AsyncSession,
    ekipman: ServiceEquipment,
    hedef: str,
    *,
    gerekce: str | None,
    tarih: date | None,
    clock: Clock,
    user: User,
) -> ServiceEquipment:
    raise NotImplementedError("ekipman.durum_degistir: D1-E paketi (TS-055) uygular")


async def seri_ile_bul(
    db: AsyncSession, ham_seri: str, *, account_id: int | None = None
) -> Eslesme:
    raise NotImplementedError("ekipman.seri_ile_bul: D1-E paketi (TS-054) uygular")


async def gecmis(db: AsyncSession, ekipman: ServiceEquipment, user: User) -> list[dict[str, Any]]:
    """Birleşik geçmiş (servis işi, bakım; Dalga 2'de atölye/parça). Tek fonksiyon."""
    raise NotImplementedError("ekipman.gecmis: D1-E paketi (TS-052) uygular")
