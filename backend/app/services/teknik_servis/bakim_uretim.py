"""PB üretim motoru (E04-06/07/08, TS-062).

İSKELET (D0-S) — uygulama D1-F paketinindir.

Kalem başına bir PB: `INSERT ... ON CONFLICT (contract_item_id,
maintenance_period_id) WHERE tur='PB' AND NOT is_deleted DO NOTHING
RETURNING id` (kısmi tekil İNDEKS olduğu için `ON CONSTRAINT` kullanılamaz).
Aynı tur iki kez koşunca 0 yeni PB. Yalnız `equipment_id` dolu ve `pb_uygun`
kalem. Atlananlar gerekçeyle `maintenance_generation_runs.skipped`'a.
Worker `bakim_otomatik_uretim=False` iken çalışmaz; önizleme SAVEPOINT içinde
aynı `uret()`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import MaintenanceGenerationRun, User

ATLAMA_NEDENLERI = ("SURESI_DOLMUS", "EKIPMAN_YOK", "SABLON_YOK", "TEYIT_BEKLIYOR", "PASIF")


async def uret(
    db: AsyncSession, clock: Clock, user: User | None = None, tetik: str = "WORKER"
) -> MaintenanceGenerationRun:
    raise NotImplementedError("bakim_uretim.uret: D1-F paketi (TS-062) uygular")


async def onizle(db: AsyncSession, clock: Clock, user: User) -> dict[str, Any]:
    raise NotImplementedError("bakim_uretim.onizle: D1-F paketi (TS-062) uygular")


async def pb_uretimi_gorevi(db: AsyncSession, clock: Clock) -> str:
    """Worker görevi `pb-uretimi` (imza `worker.Gorev`: özet metni döner)."""
    raise NotImplementedError("bakim_uretim.pb_uretimi_gorevi: D1-F paketi (TS-062) uygular")
