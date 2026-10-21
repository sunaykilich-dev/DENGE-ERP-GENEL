"""Saha zaman kaydı: sayaç, manuel kayıt, düzeltme, süre özeti (E09, TS-070…076).

İSKELET (D0-S) — uygulama D1-G paketinindir. Kanca KAYDI bu dosyanın
sonunda D1-G tarafından yapılır:
`kancalar.kaydet("durum_dogrula", acik_sayac_dogrula)`,
`kancalar.kaydet("ekip_degisiyor", acik_sayac_cikarma_dogrula)`.

Kayıt yoksa süre "eksik"tir, 0 DEĞİL (`kisi_saat_dk=None`, `sure_durumu=EKSIK`);
`or 0` / `coalesce(...,0)` yasak. Mola kişi-saate girmez. Çakışma yazmadan
önce sorgulanır ve okunur mesaj verilir; EXCLUDE yarışta son savunmadır.
GECIS: kapat → flush → ekle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.services.teknik_servis.kancalar import ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, ServiceTimeEntry, User


class ZamanHatasi(ServisHatasi):
    """Zaman kaydı kural ihlali → 409 (açık mesaj: hangi sayaç, hangi iş)."""


@dataclass
class ManuelKayitGirdisi:
    faaliyet: str
    started_at: datetime
    ended_at: datetime
    user_id: int | None = None  # başkası adına: servis.planla
    bekleme_nedeni: str | None = None
    gerekce: str | None = None
    konum_notu: str | None = None
    aciklama: str | None = None


@dataclass(frozen=True)
class SureOzeti:
    """Tek kaynak süre özeti; kayıt yoksa `kisi_saat_dk=None`."""

    kisi_saat_dk: int | None
    sure_durumu: str  # TAM | KISMI | EKSIK | BEKLENMIYOR
    eksik_kisiler: tuple[str, ...] = ()


async def baslat(
    db: AsyncSession,
    so: ServiceOrder,
    faaliyet: str,
    *,
    user: User,
    clock: Clock,
    konum_notu: str | None = None,
) -> ServiceTimeEntry:
    raise NotImplementedError("zaman.baslat: D1-G paketi (TS-071) uygular")


async def bitir(
    db: AsyncSession, bolum: ServiceTimeEntry, *, user: User, clock: Clock
) -> ServiceTimeEntry:
    raise NotImplementedError("zaman.bitir: D1-G paketi (TS-071) uygular")


async def gecis(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    yeni_faaliyet: str,
    *,
    user: User,
    clock: Clock,
    hedef_is: ServiceOrder | None = None,
) -> ServiceTimeEntry:
    """Faaliyet değiştir / mola / devam / sonraki işe taşı (kapat → flush → ekle)."""
    raise NotImplementedError("zaman.gecis: D1-G paketi (TS-071/074) uygular")


async def manuel_kaydet(
    db: AsyncSession, so: ServiceOrder, girdi: ManuelKayitGirdisi, user: User, clock: Clock
) -> ServiceTimeEntry:
    raise NotImplementedError("zaman.manuel_kaydet: D1-G paketi (TS-070) uygular")


async def unuttum(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    gercek_bitis: datetime,
    gerekce: str,
    *,
    user: User,
    clock: Clock,
) -> ServiceTimeEntry:
    raise NotImplementedError("zaman.unuttum: D1-G paketi (TS-072) uygular")


async def kaydi_iptal_et(
    db: AsyncSession, kayit: ServiceTimeEntry, gerekce: str | None, user: User, clock: Clock
) -> ServiceTimeEntry:
    raise NotImplementedError("zaman.kaydi_iptal_et: D1-G paketi (TS-072) uygular")


async def acik_sayac_dogrula(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası: TAMAMLANDI/IPTAL'de açık sayaç → 409."""
    raise NotImplementedError("zaman.acik_sayac_dogrula: D1-G paketi (TS-073) uygular")


async def acik_sayac_cikarma_dogrula(
    db: AsyncSession, so: ServiceOrder, cikan_user_ids: Sequence[int]
) -> None:
    """`ekip_degisiyor` kancası: açık sayaçlı kişiyi ekipten çıkarma → 409."""
    raise NotImplementedError("zaman.acik_sayac_cikarma_dogrula: D1-G paketi (TS-073) uygular")


async def sure_ozeti_toplu(db: AsyncSession, so_idler: Sequence[int]) -> dict[int, SureOzeti]:
    raise NotImplementedError("zaman.sure_ozeti_toplu: D1-G paketi (TS-075) uygular")


def sure_eksik_ifadesi() -> ColumnElement[bool]:
    """SQL tarafı "süre eksik" ifadesi — Python tanımıyla eşit (parametrik test)."""
    raise NotImplementedError("zaman.sure_eksik_ifadesi: D1-G paketi (TS-075) uygular")


async def zaman_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Any]:
    """Uzun açık sayaç vb. (`s/uyarilar.py` toplar; birim kapsamlı)."""
    return []
