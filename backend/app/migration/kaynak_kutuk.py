"""Güvenlik cihaz kütüğü kaynağı: V1.20.1 `dbo.SecurityDevices` dökümü (TS-172).

Döküm `teknik_servis/sql/goc_01_SecurityDevices.sql` ile üretilir (CSV,
UTF-8, seri no METİN). SSMS'ten xlsx olarak alınmış döküm de okunur
(`kutuk_profil.tablo_dosyasi_oku`): profil ölçümü ile göç aynı dosyayı okusun.
Salt okunur: kaynağa yazılmaz.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.migration.kutuk_profil import tablo_dosyasi_oku
from app.migration.servis_kaynak import KaynakDizini

KAYNAK_TABLO = "SecurityDevices"

# Göçün ihtiyaç duyduğu kolonlar; dökümde biri yoksa göç başlamaz (eksik
# kolon "hepsi boş" diye sessizce yüklenmesin).
GEREKLI_KOLONLAR = (
    "SecurityDeviceId",
    "SourceKey",
    "DeviceType",
    "Brand",
    "Model",
    "SerialNo",
    "CustomerName",
    "Location",
    "DeliveryDateText",
    "IsActive",
)


def kutuk_satirlari(kaynak: KaynakDizini | Path) -> list[dict[str, Any]]:
    """Dizin verilirse `SecurityDevices.csv`, dosya verilirse o dosya (csv/xlsx)."""
    if isinstance(kaynak, KaynakDizini):
        satirlar = kaynak.tablo(KAYNAK_TABLO)
    else:
        satirlar = [
            {k: (None if v is None or str(v).strip() == "" else v) for k, v in s.items()}
            for s in tablo_dosyasi_oku(kaynak)
        ]
    if satirlar:
        eksik = [k for k in GEREKLI_KOLONLAR if k not in satirlar[0]]
        if eksik:
            from app.migration.servis_kaynak import KaynakHatasi

            raise KaynakHatasi(f"{KAYNAK_TABLO} dökümünde kolon yok: {', '.join(eksik)}")
    return satirlar
