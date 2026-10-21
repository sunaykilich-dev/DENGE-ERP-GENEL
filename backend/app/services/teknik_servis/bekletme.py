"""Servis işi bekletme akışı ve bekleme nedeni kataloğu (E01-05, E10-03, TS-023).

İSKELET (D0-S) — uygulama D1-B paketinindir.

Tek aktif bekleme (`uq_hold_aktif`). Neden katalog tablosudur
(`service_hold_reasons`, FK): katalog dışı/pasif neden 400, `sadece_sistem`
neden kullanıcıdan 400, `aciklama_zorunlu` ise açıklama şart. `sla_durdurur`
açılışta katalogdan dondurulur. BEKLEMEDE dışına HER geçişte aktif bekleme
aynı transaction'da kapanır (`aktif_beklemeyi_kapat` → `durum_degisti`
kancası; D1-B kaydeder).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceHold, ServiceHoldReason, ServiceOrder, User


async def beklet(
    db: AsyncSession,
    so: ServiceOrder,
    neden: str,
    *,
    user: User | None,
    clock: Clock,
    aciklama: str | None = None,
    beklenen_bitis_at: datetime | None = None,
    sistem: bool = False,
) -> ServiceHold:
    """İşi BEKLEMEDE'ye alır (`durum_degistir(kaynak='bekleme')`).
    `sistem=True` yalnız servis fonksiyonları içindir (ör. BAKIM_UYGUNSUZLUK)."""
    raise NotImplementedError("bekletme.beklet: D1-B paketi (TS-023) uygular")


async def beklemeyi_bitir(
    db: AsyncSession, so: ServiceOrder, *, user: User | None, clock: Clock, not_: str | None = None
) -> ServiceHold:
    """Beklemeyi kapatır, `onceki_durum`'a döner; `sure_dk` yazılır."""
    raise NotImplementedError("bekletme.beklemeyi_bitir: D1-B paketi (TS-023) uygular")


async def aktif_beklemeyi_kapat(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası: BEKLEMEDE'den `beklemeyi_bitir` dışı bir yolla
    çıkılırsa aktif beklemeyi `otomatik_kapandi=True` ile kapatır."""
    raise NotImplementedError("bekletme.aktif_beklemeyi_kapat: D1-B paketi (TS-023) uygular")


async def bekleme_gecmisi(db: AsyncSession, so: ServiceOrder) -> list[ServiceHold]:
    raise NotImplementedError("bekletme.bekleme_gecmisi: D1-B paketi (TS-023) uygular")


async def neden_katalogu(
    db: AsyncSession, *, yalniz_secilebilir: bool = True
) -> list[ServiceHoldReason]:
    """Ekranda seçilebilir nedenler (aktif ve `sadece_sistem=false`)."""
    raise NotImplementedError("bekletme.neden_katalogu: D1-B paketi (TS-023) uygular")
