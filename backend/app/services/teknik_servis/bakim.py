"""Bakım sözleşmesi, kapsam, dönem modeli, eşleştirme (E04, TS-060/061/063/069).

Kapsam tür+adet girilir, kalem başına bir cihaz saklanır.

İSKELET (D0-S) — uygulama D1-F paketinindir.

Durum yalnız `BAKIM_SOZLESMESI` makinesiyle. Dönem sayacı saklanmaz.
Ücret ayrı uçtan (`maliyet.gor ∧ bakim.yaz`) yazılır ve `sees_cost` false
iken anahtar olarak dönmez. `bakim_otomatik_uretim` eşleştirme %100 olmadan
açılamaz (409).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.services.teknik_servis.kancalar import ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import MaintenanceContract, MaintenancePeriod, User


class BakimHatasi(ServisHatasi):
    """Bakım kural ihlali → 409."""


@dataclass
class SozlesmeGirdisi:
    birim: str
    account_id: int | None
    address_id: int | None = None
    contact_id: int | None = None
    responsible_user_id: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    annual_frequency: int | None = None
    fixed_months: list[int] | None = None
    # {"XRAY": 2, "KAPI_DEDEKTORU": 3}
    kapsam: dict[str, int] = field(default_factory=dict)
    notes: str | None = None


async def sozlesme_olustur(
    db: AsyncSession, girdi: SozlesmeGirdisi, *, user: User, clock: Clock
) -> MaintenanceContract:
    raise NotImplementedError("bakim.sozlesme_olustur: D1-F paketi (TS-060) uygular")


async def sozlesme_guncelle(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    degisiklikler: dict,
    *,
    user: User,
    clock: Clock,
) -> MaintenanceContract:
    raise NotImplementedError("bakim.sozlesme_guncelle: D1-F paketi (TS-060) uygular")


async def durum_degistir(
    db: AsyncSession, sozlesme: MaintenanceContract, hedef: str, *, user: User, clock: Clock
) -> MaintenanceContract:
    raise NotImplementedError("bakim.durum_degistir: D1-F paketi (TS-060) uygular")


async def donemleri_hesapla(
    db: AsyncSession, sozlesme: MaintenanceContract, clock: Clock
) -> list[MaintenancePeriod]:
    """Döngüden dönem satırları (idempotent)."""
    raise NotImplementedError("bakim.donemleri_hesapla: D1-F paketi (TS-061) uygular")


async def eslestirme_onerileri(
    db: AsyncSession, sozlesme: MaintenanceContract, user: User
) -> list[dict[str, Any]]:
    raise NotImplementedError("bakim.eslestirme_onerileri: D1-F paketi (TS-063) uygular")


async def bakim_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Any]:
    """`s/uyarilar.py` toplayıcısının çağırdığı bakım uyarıları (birim kapsamlı)."""
    return []
