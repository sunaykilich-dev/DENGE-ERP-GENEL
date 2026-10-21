"""Müşteri onayı (tekil + ziyaret grubu) ve servis formu PDF bağlamı (E01-08, E04-15/16, TS-036).

İSKELET (D0-S) — uygulama D1-C paketinindir.

Onay DEĞİŞMEZ; yenisi eskisini `gecersiz_kilan_id` ile geçersiz kılar. İmza
mevcut `IMZA` ek türüyle. Ziyaret onayı: aynı müşteri + adres + gün (aksi 409),
tek transaction'da `onay_grubu`. PDF fiyatsız; PDF bağlamı bu modüldedir
(KD-18), `belgeler.py` yalnız `firma_bilgisi()` için çağrılır.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceApproval, ServiceOrder, User


@dataclass
class OnayGirdisi:
    tur: str  # IMZA | SOZLU | BASILI_FORM | ALINAMADI
    imzalayan_ad: str | None = None
    imzalayan_unvan: str | None = None
    ek_id: int | None = None
    eksik_nedeni: str | None = None


async def onay_al(
    db: AsyncSession, so: ServiceOrder, girdi: OnayGirdisi, *, user: User, clock: Clock
) -> ServiceApproval:
    raise NotImplementedError("onay.onay_al: D1-C paketi (TS-036) uygular")


async def ziyaret_onayi(
    db: AsyncSession, is_idler: Sequence[int], girdi: OnayGirdisi, *, user: User, clock: Clock
) -> list[ServiceApproval]:
    raise NotImplementedError("onay.ziyaret_onayi: D1-C paketi (TS-036) uygular")


async def onay_zorunlu_mu(db: AsyncSession, so: ServiceOrder) -> bool:
    """`servis_onay_zorunlu_turler` ayarına göre (varsayılan ["PB"])."""
    raise NotImplementedError("onay.onay_zorunlu_mu: D1-C paketi (TS-036) uygular")


async def servis_formu_baglami(db: AsyncSession, so: ServiceOrder) -> dict[str, Any]:
    """`templates/servis_formu.html` bağlamı (fiyatsız)."""
    raise NotImplementedError("onay.servis_formu_baglami: D1-C paketi (TS-036) uygular")


async def ziyaret_formu_baglami(db: AsyncSession, is_idler: Sequence[int]) -> dict[str, Any]:
    raise NotImplementedError("onay.ziyaret_formu_baglami: D1-C paketi (TS-036) uygular")
