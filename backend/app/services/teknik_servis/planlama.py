"""Plan yazımı: tekli/toplu plan, geri alma, yeniden plan, saha önerisi (E02, TS-040…048).

İSKELET (D0-S) — uygulama D1-D paketinindir.

Tek aktif plan (`uq_svcplan_aktif`); plan satırı silinmez, yenisiyle değişir.
MUSTERI_TALEBI/PLANLAMADA/TEKRAR_ACILDI → PLANLANDI (`kaynak='planla'`);
saha/atölye/bekleme durumunda yalnız plan güncellenir, durum geri çekilmez;
kapalı işte 409. Ekip ataması `atama.ata` ile (tek kaynak); plan üyeleri
`ekip_degisti` kancasıyla senkron tutulur.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, ServicePlan, ServiceVisit, User
    from app.services.teknik_servis.atama import AtamaSatiri


@dataclass
class PlanGirdisi:
    plan_date: date
    duration_min: int
    start_time: time | None = None
    ekip: list[AtamaSatiri] = field(default_factory=list)
    sahaya_giden_sefler: list[int] = field(default_factory=list)
    vehicle_id: int | None = None
    site_area: str | None = None
    site_note: str | None = None
    plan_note: str | None = None
    change_reason: str | None = None
    change_note: str | None = None
    conflict_override_note: str | None = None
    beklenen_aktif_plan_id: int | None = None


async def planla(
    db: AsyncSession, so: ServiceOrder, girdi: PlanGirdisi, *, user: User, clock: Clock
) -> ServicePlan:
    raise NotImplementedError("planlama.planla: D1-D paketi (TS-040/041) uygular")


async def plani_geri_al(
    db: AsyncSession,
    so: ServiceOrder,
    neden: str,
    *,
    not_: str | None,
    user: User,
    clock: Clock,
) -> ServicePlan:
    """PLANLANDI → PLANLAMADA (`kaynak='plan_geri_al'`); nedensiz 409."""
    raise NotImplementedError("planlama.plani_geri_al: D1-D paketi (TS-044) uygular")


async def toplu_planla(
    db: AsyncSession, is_idler: Sequence[int], girdi: PlanGirdisi, *, user: User, clock: Clock
) -> ServiceVisit:
    """Aynı birim + müşteri + lokasyon, plansız işler → tek ziyaret."""
    raise NotImplementedError("planlama.toplu_planla: D1-D paketi (TS-043) uygular")


async def yeniden_planla(
    db: AsyncSession, is_idler: Sequence[int], girdi: PlanGirdisi, *, user: User, clock: Clock
) -> list[ServicePlan]:
    raise NotImplementedError("planlama.yeniden_planla: D1-D paketi (TS-046) uygular")


async def ekip_degisti(db: AsyncSession, so: ServiceOrder, yeni_ekip: Sequence[Any]) -> None:
    """`ekip_degisti` kancası: aktif planda EKIP_DEGISIMI satırı (D1-D kaydeder)."""
    raise NotImplementedError("planlama.ekip_degisti: D1-D paketi (TS-025/041) uygular")


async def plan_gecmisi(db: AsyncSession, so: ServiceOrder) -> list[ServicePlan]:
    raise NotImplementedError("planlama.plan_gecmisi: D1-D paketi (TS-044) uygular")


async def saha_onerisi(db: AsyncSession, so: ServiceOrder, user: User) -> dict[str, Any] | None:
    """Aynı müşteri + lokasyonun son planından saha alanı önerisi."""
    raise NotImplementedError("planlama.saha_onerisi: D1-D paketi (TS-047) uygular")
