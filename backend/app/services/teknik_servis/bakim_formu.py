"""Dijital bakım formu, PB koruması, dönem kapanışı, kapsam dışı (E04, TS-064…068).

İSKELET (D0-S) — uygulama D1-F paketinindir. Kanca KAYDI bu dosyanın
sonunda D1-F tarafından yapılır:
`kancalar.kaydet("durum_dogrula", pb_gecis_dogrula)`,
`kancalar.kaydet("durum_degisti", donem_kapanisini_guncelle)`.

PB'de TAMAMLANDI yalnız `tamamla()` (`kaynak='bakim_formu'`), IPTAL yalnız
kapsam dışı onayı (`kaynak='kapsam_disi'`); diğer yollar 409 ve Kapsam Dışı
yolunu gösteren mesaj. Her başarılı tamamlamada değişmez
`maintenance_visits` satırı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import (
        MaintenanceExclusionRequest,
        MaintenanceForm,
        MaintenanceNonconformity,
        ServiceOrder,
        User,
    )


async def pb_gecis_dogrula(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası (yalnız tur='PB')."""
    raise NotImplementedError("bakim_formu.pb_gecis_dogrula: D1-F paketi (TS-065) uygular")


async def donem_kapanisini_guncelle(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası: dönem kapanışı (idempotent, geri açabilir)."""
    raise NotImplementedError("bakim_formu.donem_kapanisini_guncelle: D1-F paketi uygular")


async def form_getir(db: AsyncSession, so: ServiceOrder) -> MaintenanceForm:
    raise NotImplementedError("bakim_formu.form_getir: D1-F paketi (TS-064) uygular")


async def form_kaydet(
    db: AsyncSession, form: MaintenanceForm, degisiklikler: dict, *, user: User, clock: Clock
) -> MaintenanceForm:
    raise NotImplementedError("bakim_formu.form_kaydet: D1-F paketi (TS-064) uygular")


async def tamamla(
    db: AsyncSession, form: MaintenanceForm, *, user: User, clock: Clock
) -> MaintenanceForm:
    raise NotImplementedError("bakim_formu.tamamla: D1-F paketi (TS-064) uygular")


async def kapsam_disi_talep(
    db: AsyncSession, so: ServiceOrder, neden: str, aciklama: str, *, user: User, clock: Clock
) -> MaintenanceExclusionRequest:
    raise NotImplementedError("bakim_formu.kapsam_disi_talep: D1-F paketi (TS-066) uygular")


async def kapsam_disi_karar(
    db: AsyncSession,
    talep: MaintenanceExclusionRequest,
    onay: bool,
    *,
    not_: str | None,
    user: User,
    clock: Clock,
) -> MaintenanceExclusionRequest:
    raise NotImplementedError("bakim_formu.kapsam_disi_karar: D1-F paketi (TS-066) uygular")


async def uygunsuzluk_kapat(
    db: AsyncSession, kayit: MaintenanceNonconformity, not_: str, *, user: User, clock: Clock
) -> MaintenanceNonconformity:
    raise NotImplementedError("bakim_formu.uygunsuzluk_kapat: D1-F paketi (TS-067) uygular")
