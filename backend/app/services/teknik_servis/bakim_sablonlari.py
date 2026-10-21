"""Bakım kontrol şablonları — ilk sürümde KOD SABİTİ (E04, TS-062/064).

İSKELET (D0-S) — madde metinleri D1-F paketi tarafından eski koddan
(`Program.cs` bakım formu) aynen taşınır. Şablonun tabloya taşınması
ertelendi (E04-22). PB üretiminde maddeler forma KOPYALANIR; şablon sonradan
değişse de eski formun metni değişmez.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KontrolMaddesi:
    kod: str
    etiket: str


@dataclass(frozen=True)
class KontrolSablonu:
    surum: int
    maddeler: tuple[KontrolMaddesi, ...]


# Anahtar = `maintenance_contract_items.equipment_type` (XRAY, KAPI_DEDEKTORU).
KONTROL_SABLONLARI: dict[str, KontrolSablonu] = {}


def sablon(equipment_type: str) -> KontrolSablonu | None:
    """Türün şablonu; yoksa None (üretim `SABLON_YOK` gerekçesiyle atlar)."""
    return KONTROL_SABLONLARI.get(equipment_type)
