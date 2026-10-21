"""Kapanış sonucu, çözüm kanalı, arıza nedeni kataloğu, açılışta çözüldü (E01-06, TS-024).

İSKELET (D0-S) — uygulama D1-B paketinindir.

Sonuçsuz TAMAMLANDI yok (409); `cozum_kanali` NOT NULL. Teknisyen yalnız
TAMAMLANDI yapar (KAPATILDI `servis.kapat`). `servis.uzaktan_coz` tek
istekte açılış + TAMAMLANDI (iki olay). Arıza nedeni birim bazlıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceFaultReason, ServiceOrder, ServiceResult, User
    from app.services.teknik_servis.is_emirleri import ServisIsiGirdisi


@dataclass
class SonucGirdisi:
    sonuc: str
    cozum_kanali: str
    yapilan_islem: str
    ariza_nedeni_id: int | None = None
    saha_seri_no: str | None = None
    saha_bolge: str | None = None
    sure_eksik_onay: bool = False


async def sonuc_gir(
    db: AsyncSession, so: ServiceOrder, girdi: SonucGirdisi, *, user: User, clock: Clock
) -> ServiceResult:
    """Sonuç yazar; COZULDU ise `durum_degistir(TAMAMLANDI, kaynak='sonuc')`."""
    raise NotImplementedError("sonuc.sonuc_gir: D1-B paketi (TS-024) uygular")


async def uzaktan_coz(
    db: AsyncSession,
    girdi: ServisIsiGirdisi,
    sonuc: SonucGirdisi,
    *,
    user: User,
    clock: Clock,
) -> ServiceOrder:
    """Açılışta telefonla/uzaktan çözüldü: aç + TAMAMLANDI (`kaynak='uzaktan'`)."""
    raise NotImplementedError("sonuc.uzaktan_coz: D1-B paketi (TS-024) uygular")


async def gecerli_sonuc(db: AsyncSession, so: ServiceOrder) -> ServiceResult | None:
    """Geçersiz kılınmamış son sonuç."""
    raise NotImplementedError("sonuc.gecerli_sonuc: D1-B paketi (TS-024) uygular")


async def ariza_nedenleri(
    db: AsyncSession, birim: str, *, yalniz_aktif: bool = True
) -> list[ServiceFaultReason]:
    raise NotImplementedError("sonuc.ariza_nedenleri: D1-B paketi (TS-024) uygular")
