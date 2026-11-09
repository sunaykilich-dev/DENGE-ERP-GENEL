"""Teknik servis uyarılarının kayıt defteri ve toplayıcısı (plan §1.11, E01-18).

Canlı uyarı merkezi (`services/uyarilar.py`) uyarıyı SAKLAMAZ, HESAPLAR ve
izne tabi tutar. Teknik servis on bir alanda uyarı üretecek (servis,
planlama, bakım, zaman, atölye, kiralama, parça, teklif, eğitim, SLA, ana
veri); her biri `uyarilar.py`'ye kendi `if user.has(...)` bloğunu yazsaydı o
dosya her dalgada beş paketin aynı anda düzenlediği bir dosya olurdu. Bunun
yerine canlı toplayıcı TEK satırla buraya devreder, modüller de kendi
dosyalarının sonunda `kaydet(alan, izin, fn)` çağırır.

**Kurallar (her uyarı fonksiyonu için):**
- İmza: `async fn(db, user, clock) -> list[Uyari]`; saat yalnız `clock`.
- İzin kapısı burada da uygulanır (`izin` verilmezse kayıt reddedilir), ama
  fonksiyon BİRİM/İŞ KAPSAMINI kendisi uygular (`s/kapsam.py`): uyarı sayısı
  bir sızıntıdır — başka birimin geciken işi sayıya girmemeli.
- `adet == 0` olan uyarı gösterilmez (canlı davranış).

Çağrı sırası `ALANLAR` sırasıdır, aynı alanda kayıt sırasıdır; böylece zildeki
liste her ortamda aynı sırada görünür.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

ALANLAR = (
    "servis",
    "planlama",
    "bakim",
    "zaman",
    "atolye",
    "kiralama",
    "parca",
    "teklif",
    "egitim",
    "sla",
    "ana_veri",
    "personel",
)

UyariFn = Callable[["AsyncSession", "User", "Clock"], Awaitable[list[Uyari]]]

_KAYIT: dict[str, list[tuple[tuple[str, ...], UyariFn]]] = {a: [] for a in ALANLAR}

# Kanca kaydetmeyen ama uyarı kaydeden ortak yardımcı modüller. Paket
# `__init__` bunları import etmez (bkz. orada); toplayıcı ilk çağrıda yükler.
# Dosya henüz yoksa (paralel paket teslim edilmedi) atlanır; varsa import
# hatası GİZLENMEZ.
_YARDIMCI_MODULLER = (
    "app.services.teknik_servis.ana_veri",
    "app.services.teknik_servis.personel",
    "app.services.teknik_servis.sahada_parca",
)
_yuklendi = False


def kaydet(alan: str, izin: str | tuple[str, ...], fn: UyariFn) -> UyariFn:
    """Uyarı fonksiyonunu kaydeder. `izin` tek kod ya da "herhangi biri" demeti."""
    if alan not in _KAYIT:
        raise ValueError(f"Bilinmeyen uyarı alanı: {alan}")
    izinler = (izin,) if isinstance(izin, str) else tuple(izin)
    if not izinler:
        raise ValueError("Uyarı kaydı izinsiz olamaz (izne tabi olmayan uyarı sızıntıdır)")
    if all(f is not fn for _, f in _KAYIT[alan]):
        _KAYIT[alan].append((izinler, fn))
    return fn


def kayitlar() -> dict[str, list[tuple[tuple[str, ...], UyariFn]]]:
    """Salt okunur görünüm (testler ve tanılama için)."""
    return {a: list(k) for a, k in _KAYIT.items()}


def _modulleri_yukle() -> None:
    global _yuklendi
    if _yuklendi:
        return
    importlib.import_module("app.services.teknik_servis")
    for ad in _YARDIMCI_MODULLER:
        if importlib.util.find_spec(ad) is not None:
            importlib.import_module(ad)
    _yuklendi = True


async def topla(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Kullanıcının GÖREBİLECEĞİ teknik servis uyarıları (izin + kapsam)."""
    _modulleri_yukle()
    sonuc: list[Uyari] = []
    for alan in ALANLAR:
        for izinler, fn in _KAYIT[alan]:
            if not any(user.has(i) for i in izinler):
                continue
            sonuc.extend(u for u in await fn(db, user, clock) if u.adet > 0)
    return sonuc
