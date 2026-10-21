"""Servis işinin silinemez olay geçmişi ve iş notu (E01-04, TS-022).

İSKELET (D0-S) — uygulama D1-B paketinindir.

`service_order_events` yalnız eklenir (DB tetikleyicisi `trg_soe_salt_ekleme`
UPDATE/DELETE'i reddeder). `ozet` ve `veri` KİŞİSEL VERİ İÇERMEZ: tetikleyici
yüzünden KVKK anonimleştirmesi bu satırları temizleyemez. `olay_yaz`
irtibat adı/telefonu ve imzalayan adı taşıyan anahtarları reddeder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, ServiceOrderEvent, User

# `veri` sözlüğünde YASAK anahtarlar (kişisel veri).
KISISEL_VERI_ANAHTARLARI = frozenset(
    {"iletisim_ad", "iletisim_telefon", "imzalayan_ad", "imzalayan_unvan", "telefon", "ad_soyad"}
)


async def olay_yaz(
    db: AsyncSession,
    so: ServiceOrder,
    olay_turu: str,
    ozet: str,
    *,
    user: User | None,
    clock: Clock,
    eski_durum: str | None = None,
    yeni_durum: str | None = None,
    veri: dict[str, Any] | None = None,
) -> ServiceOrderEvent:
    """Olay ekler (`olusma_zamani = clock.now()`); kişisel veri anahtarı → ValueError."""
    raise NotImplementedError("gecmis.olay_yaz: D1-B paketi (TS-022) uygular")


async def not_ekle(
    db: AsyncSession, so: ServiceOrder, metin: str, *, user: User, clock: Clock
) -> ServiceOrderEvent:
    """İş notu = NOT olayı."""
    raise NotImplementedError("gecmis.not_ekle: D1-B paketi (TS-022) uygular")


async def gecmis_listesi(db: AsyncSession, so: ServiceOrder) -> list[ServiceOrderEvent]:
    """Olaylar zaman sırasıyla."""
    raise NotImplementedError("gecmis.gecmis_listesi: D1-B paketi (TS-022) uygular")
