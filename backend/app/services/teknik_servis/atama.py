"""Kimlik bazlı çoklu atama, tek sorumlu, toplu atama, ekip senkronu (E01-12, TS-025).

İSKELET (D0-S) — uygulama D1-B paketinindir. İmzalar sabittir: D1-D
(planlama) ve D1-G (zaman) bu fonksiyonları çağırır / kancalarına yazar.

Akış (`ata` ve `toplu_ata` aynı kuralı paylaşır):
1. atanabilirlik = TS-009 ölçütü (aktif, ayrılmamış, saha rolü
   SEF/TEKNISYEN/STAJYER, birim üyesi; girişsiz personel atanabilir);
2. çıkan kişiler için `kancalar.ekip_degisiyor` (açık sayaç → 409, HİÇBİR
   iş değişmez);
3. satırlar yazılır (silinmez; çıkan `removed_at` alır), ATAMA olayı;
4. `kancalar.ekip_degisti` (aktif planda EKIP_DEGISIMI satırı).
Toplu atama üst sınırı `servis_toplu_atama_ust_sinir` (150; 151 → 422).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, ServiceOrderAssignment, User


@dataclass(frozen=True)
class AtamaSatiri:
    """Bir kişinin işteki rolü. `is_lead` yalnız TEKNISYEN'de."""

    user_id: int
    rol: str  # SEF | TEKNISYEN
    is_lead: bool = False


TopluAtamaModu = Literal["EKLE", "DEGISTIR"]


async def ata(
    db: AsyncSession,
    so: ServiceOrder,
    atamalar: Sequence[AtamaSatiri],
    *,
    user: User,
    clock: Clock,
) -> list[ServiceOrderAssignment]:
    """İşin ekibini verilen listeye eşitler (çıkanlar pasiflenir)."""
    raise NotImplementedError("atama.ata: D1-B paketi (TS-025) uygular")


async def toplu_ata(
    db: AsyncSession,
    is_idler: Sequence[int],
    atamalar: Sequence[AtamaSatiri],
    *,
    mod: TopluAtamaModu,
    user: User,
    clock: Clock,
) -> list[ServiceOrder]:
    """Çok işe aynı ekip; tek transaction, kural ihlalinde hiçbir iş değişmez."""
    raise NotImplementedError("atama.toplu_ata: D1-B paketi (TS-025) uygular")


async def aktif_ekip(db: AsyncSession, so: ServiceOrder) -> list[ServiceOrderAssignment]:
    """`removed_at IS NULL` atamalar."""
    raise NotImplementedError("atama.aktif_ekip: D1-B paketi (TS-025) uygular")
