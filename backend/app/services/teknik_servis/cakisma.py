"""Plan çakışma motoru — tek kaynak (E02-15, E02-10, TS-045).

İSKELET (D0-S) — uygulama D1-D paketinindir.

409 gövdesi `{detail, kod: 'PLAN_CAKISMA', cakismalar}`; `servis.planla`
gerekçeyle geçebilir. Kapsam dışı çakışan iş maskelenir. Eşzamanlılık için
gün sıralı advisory lock. Şef yalnız `sahaya_gidiyor` ise çakışmaya girer;
müsaitlik blokları (`service_unavailability`) da çakışmadır.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.services.teknik_servis.kancalar import ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User

CAKISMA_KODU = "PLAN_CAKISMA"


@dataclass(frozen=True)
class Cakisma:
    user_id: int
    baslangic: datetime
    bitis: datetime
    tur: str  # PLAN | MUSAITLIK
    so_no: str | None  # kapsam dışıysa None (maskeli)


class PlanCakismasi(ServisHatasi):
    """Çakışma → 409 + `cakismalar` listesi."""

    def __init__(self, mesaj: str, cakismalar: Sequence[Cakisma]) -> None:
        super().__init__(mesaj)
        self.cakismalar = list(cakismalar)


async def cakismalari_bul(
    db: AsyncSession,
    user_idler: Sequence[int],
    baslangic: datetime,
    bitis: datetime,
    *,
    goren: User,
    haric_plan_id: int | None = None,
) -> list[Cakisma]:
    raise NotImplementedError("cakisma.cakismalari_bul: D1-D paketi (TS-045) uygular")
