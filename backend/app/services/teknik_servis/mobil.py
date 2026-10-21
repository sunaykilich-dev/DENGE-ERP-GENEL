"""Benim İşlerim: teknisyenin tek mobil ekranı ve "Bugünüm" özeti (E09-04/05, TS-077/078).

İSKELET (D0-S) — uygulama D1-G paketinindir (Dalga 2'de SLA bloğu D2-G).

Tek uç (`GET /api/teknik-servis/benim-islerim`), tek sayfa; ayrı
"Ziyaretlerim" yok. Gün yerel (Europe/Istanbul). Çevrimdışı yok.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User


async def benim_islerim(
    db: AsyncSession, user: User, clock: Clock, *, gun: date | None = None
) -> dict[str, Any]:
    """Bugün/Yarın planlı işler, kart verisi, aktif sayaç bandı, `sunucu_zamani`."""
    raise NotImplementedError("mobil.benim_islerim: D1-G paketi (TS-077) uygular")


async def bugunum(db: AsyncSession, user: User, clock: Clock) -> dict[str, Any]:
    """Gün özeti ve gün sonu süre eksik listesi."""
    raise NotImplementedError("mobil.bugunum: D1-G paketi (TS-078) uygular")
