"""Planlama takvimi, plansız havuz, planlama KPI'ları ve uyarıları (E02-05/06, TS-042/049).

İSKELET (D0-S) — uygulama D1-D paketinindir.

Tarih aralığı ≤ 62 gün (kod sabiti). Havuz gruplaması yalnız
`ana_veri.lokasyon_anahtari` ile. KPI sayısı = liste. KENDI_ISLERI teknisyeni
yalnız kendi işlerini görür.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

TAKVIM_AZAMI_GUN = 62


async def takvim(
    db: AsyncSession,
    user: User,
    clock: Clock,
    baslangic: date,
    bitis: date,
    *,
    birim: str | None = None,
) -> list[dict[str, Any]]:
    raise NotImplementedError("takvim.takvim: D1-D paketi (TS-042) uygular")


async def havuz(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    gruplama: str = "lokasyon",
    birim: str | None = None,
) -> list[dict[str, Any]]:
    raise NotImplementedError("takvim.havuz: D1-D paketi (TS-042) uygular")


async def planlama_kpi(
    db: AsyncSession, user: User, clock: Clock, gun: date, *, birim: str | None = None
) -> list[dict[str, Any]]:
    raise NotImplementedError("takvim.planlama_kpi: D1-D paketi (TS-042) uygular")


async def planlama_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Any]:
    """`s/uyarilar.py` toplayıcısının çağırdığı planlama uyarıları (birim kapsamlı)."""
    return []
