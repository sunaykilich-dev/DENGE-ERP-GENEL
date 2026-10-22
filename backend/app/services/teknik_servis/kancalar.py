"""Modüller arası tek bağlantı noktası: süreç içi kanca kayıt defteri (plan §1.8, KD-15).

**Neden:** Dalga 1'de yazılan servis işi çekirdeği (`is_emirleri`, `atama`,
`zaman`) sonraki dalgalarda (SLA, atölye, parça, kiralama) DÜZENLENMEDEN yeni
davranış kazanmalı. Çekirdek yalnız aşağıdaki kancaları çağırır; modüller
kendi dosyalarının EN ALTINDA `kaydet(...)` ile kaydolur ve
`services/teknik_servis/__init__.py` modülleri sabit sırayla import eder.
Böylece dosya sahipliği çakışmaz ve kayıt sırası (dolayısıyla çağrı sırası)
her ortamda aynıdır.

Kaydı olmayan kanca (ör. Dalga 1 yayınında SLA yok) çağrıldığında hiçbir şey
yapmaz. Kancalar ÇAĞIRANIN transaction'ında koşar (commit yok, yalnız
flush); bir kanca `ServisHatasi` atarsa API 409'a çevirir ve işlemin
tamamı geri alınır.

| Kanca | Çağıran (tek yer) |
|---|---|
| `durum_dogrula(db, so, hedef, kaynak)` | `is_emirleri.durum_degistir` (yazmadan önce) |
| `durum_degisti(db, so, onceki, hedef, kaynak, clock)` | aynı fonksiyon (yazdıktan sonra) |
| `is_olusturuldu(db, so, clock)` | `is_emirleri.olustur` |
| `ekip_degisiyor(db, so, cikan_user_ids)` | `atama.ata/toplu_ata`, `planlama.ekip_degisti` |
| `ekip_degisti(db, so, yeni_ekip, clock)` | `atama.ata/toplu_ata` |
| `oncelik_birim_degisti(db, so, clock)` | `is_emirleri.guncelle` |
| `zaman_bolumu_acildi(db, bolum)` | `zaman.baslat/gecis` |
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, ServiceTimeEntry

KANCALAR = (
    "durum_dogrula",
    "durum_degisti",
    "is_olusturuldu",
    "ekip_degisiyor",
    "ekip_degisti",
    "oncelik_birim_degisti",
    "zaman_bolumu_acildi",
)

KancaFn = Callable[..., Awaitable[None]]

_KAYIT: dict[str, list[KancaFn]] = {ad: [] for ad in KANCALAR}


class ServisHatasi(ValueError):
    """Teknik servis iş kuralı ihlali → API'de 409 (Türkçe mesajla).

    Bütün servis modüllerinin ve kancaların ortak hata sınıfı; modüller
    gerekirse bundan türetir (ör. `PlanCakismasi`). Girdi hatası (400) ayrı
    sınıftır: `ServisGirdiHatasi`.
    """


class ServisGirdiHatasi(ValueError):
    """Girdi doğrulama hatası (katalog dışı neden, geçmiş tarih ...) → 400."""


def kaydet(kanca: str, fn: KancaFn) -> KancaFn:
    """`fn`'i `kanca`ya kaydeder. Aynı fonksiyon iki kez kaydolmaz (modül
    yeniden import edilse bile çağrı çoğalmaz). Bilinmeyen kanca adı
    programlama hatasıdır → ValueError (yazım hatası sessizce no-op olmasın).
    """
    if kanca not in _KAYIT:
        raise ValueError(f"Bilinmeyen kanca: {kanca!r}. Geçerliler: {', '.join(KANCALAR)}")
    if fn not in _KAYIT[kanca]:
        _KAYIT[kanca].append(fn)
    return fn


def kayitlilar(kanca: str) -> tuple[KancaFn, ...]:
    """Kayıt sırasıyla kancaya bağlı fonksiyonlar (teşhis ve test için)."""
    if kanca not in _KAYIT:
        raise ValueError(f"Bilinmeyen kanca: {kanca!r}")
    return tuple(_KAYIT[kanca])


async def cagir(kanca: str, *args: Any, **kwargs: Any) -> None:
    """Kancaya kayıtlı fonksiyonları kayıt sırasıyla, aynı transaction'da çağırır."""
    for fn in kayitlilar(kanca):
        await fn(*args, **kwargs)


# --- Tipli çağrı noktaları (imzalar plan §1.8'de sabittir) ---------------------


async def durum_dogrula(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    await cagir("durum_dogrula", db, so, hedef, kaynak)


async def durum_degisti(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    await cagir("durum_degisti", db, so, onceki, hedef, kaynak, clock)


async def is_olusturuldu(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    await cagir("is_olusturuldu", db, so, clock)


async def ekip_degisiyor(db: AsyncSession, so: ServiceOrder, cikan_user_ids: Iterable[int]) -> None:
    await cagir("ekip_degisiyor", db, so, tuple(cikan_user_ids))


async def ekip_degisti(
    db: AsyncSession, so: ServiceOrder, yeni_ekip: Iterable[Any], clock: Clock
) -> None:
    """Dalga 2 (D2-S, Dalga 1 doğrulayıcı talebi): imza `clock` taşır.

    Kaydolanlar saati yalnız buradan okur; önceden planlama kancası zamanı
    atama satırlarının damgasından türetiyordu (dolaylı, kırılgan).
    """
    await cagir("ekip_degisti", db, so, tuple(yeni_ekip), clock)


async def oncelik_birim_degisti(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    """Dalga 2: imza `clock` taşır (SLA yeniden damgası DUZELTME olayını Clock'la
    yazar). Çağıran öncelik VEYA tür/kategori değişince çağırır."""
    await cagir("oncelik_birim_degisti", db, so, clock)


async def zaman_bolumu_acildi(db: AsyncSession, bolum: ServiceTimeEntry) -> None:
    await cagir("zaman_bolumu_acildi", db, bolum)
