"""Servis Paneli ve TEK KPI tanım kaydı (E01-14, TS-035).

İSKELET (D0-S) — uygulama D1-C paketinindir.

Her KPI kutusunun sayısı = `/api/teknik-servis/isler?kpi=<kod>` listesinin
`X-Toplam-Kayit` başlığı (sayı = liste). Kutu ve liste AYNI süzgeç
fonksiyonunu kullanır; Operasyon Merkezi (Dalga 2) ve raporlar (Dalga 3) bu
kaydı genişletir. Mobilite `PanelPage` değişmez.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User


@dataclass(frozen=True)
class KpiTanimi:
    """`KpiKutusu` bileşeninin beslendiği tanım: `{kod, baslik, tanim, deger, yol}`."""

    kod: str
    baslik: str
    tanim: str
    # (stmt, user, clock) -> stmt: listeye ve sayıya aynı süzgeç uygulanır.
    suzgec: Callable[..., Select[Any]]
    izin: str = "servis.gor"


# D1-C doldurur (açık, bugün planlı, atölyede, beklemede, geciken ...).
KPI_TANIMLARI: dict[str, KpiTanimi] = {}


async def panel_ozeti(
    db: AsyncSession, user: User, clock: Clock, *, donem: str | None = None
) -> list[dict[str, Any]]:
    raise NotImplementedError("panel.panel_ozeti: D1-C paketi (TS-035) uygular")


def kpi_suzgeci(kod: str) -> KpiTanimi:
    """`/isler?kpi=` için tanım; bilinmeyen kod → ValueError (400)."""
    raise NotImplementedError("panel.kpi_suzgeci: D1-C paketi (TS-035) uygular")
