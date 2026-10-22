"""Teknik servis kodu mobilite hak ediş/cihaz zincirine YAZMAZ (TS-028, KD-01).

`services/teknik_servis/` altındaki hiçbir modül mobilite iş emri, hak ediş,
ödeme, araç ve cihaz-araç geçmişi modellerini import etmez; cihaz (`devices`)
yalnız OKUNABİLİR (Mobilite/Araç Takip seri eşleşmesi, TS-193) — `Device(`
kurucusu, `insert/update/delete(Device...)` ya da cihaz durum servisi
çağrısı yasaktır. Statik tarama: yeni bir paket bu kuralı bozarsa kırmızı.
"""

import ast
import re
from pathlib import Path

import app.services.teknik_servis as paket

KOK = Path(paket.__file__).parent

YASAK_MODELLER = frozenset(
    {
        "WorkOrder",
        "WorkOrderItem",
        "DeviceVehicleAssignment",
        "PartnerSettlement",
        "PartnerTariff",
        "SettlementLine",
        "SettlementDispute",
        "Payment",
        "Vehicle",
        "DeviceStatusHistory",
    }
)
YASAK_MODULLER = frozenset(
    {
        "app.services.workorders",
        "app.services.settlements",
        "app.services.devices",
        "app.services.assignments",
        "app.models.workorder",
        "app.models.settlement",
        "app.models.vehicle",
    }
)
CIHAZ_YAZMA = re.compile(r"\b(?:insert|update|delete)\(\s*Device\b|\bDevice\(")


def _dosyalar():
    return sorted(p for p in KOK.rglob("*.py"))


def test_tarama_dosya_buluyor() -> None:
    adlar = {p.name for p in _dosyalar()}
    assert {"is_emirleri.py", "atama.py", "bekletme.py", "sonuc.py", "gecmis.py"} <= adlar


def test_mobilite_yazma_modelleri_import_edilmez() -> None:
    ihlaller = []
    for yol in _dosyalar():
        agac = ast.parse(yol.read_text(encoding="utf-8"))
        for dugum in ast.walk(agac):
            if isinstance(dugum, ast.ImportFrom):
                modul = dugum.module or ""
                if modul in YASAK_MODULLER:
                    ihlaller.append(f"{yol.name}: from {modul}")
                for ad in dugum.names:
                    if ad.name in YASAK_MODELLER:
                        ihlaller.append(f"{yol.name}: {ad.name}")
            elif isinstance(dugum, ast.Import):
                for ad in dugum.names:
                    if ad.name in YASAK_MODULLER:
                        ihlaller.append(f"{yol.name}: import {ad.name}")
    assert not ihlaller, "Teknik servis mobilite zincirine bağlanmamalı:\n" + "\n".join(ihlaller)


def test_cihaz_tablosuna_yazma_yok() -> None:
    ihlaller = [
        f"{yol.name}: {eslesme.group(0)}"
        for yol in _dosyalar()
        for eslesme in CIHAZ_YAZMA.finditer(yol.read_text(encoding="utf-8"))
    ]
    assert not ihlaller, "devices yalnız okunur:\n" + "\n".join(ihlaller)
