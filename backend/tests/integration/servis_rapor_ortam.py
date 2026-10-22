"""Servis raporu testlerinin ortak kurulumu (TS-181…187, TS-201).

Altın set `tests/fixtures/servis_rapor_seed.py`'dedir; `fixtures/` dizini
pytest yoluna ekli olmadığı için yol buradan bir kez eklenir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))

import servis_rapor_seed  # noqa: E402

R = "/api/teknik-servis/raporlar"
DONEM = {"baslangic": "2026-03-01", "bitis": "2026-03-31"}
BEKLENEN: dict[str, Any] = json.loads(
    (_FIXTURES / "servis_rapor_beklenen.json").read_text(encoding="utf-8")
)
# Para alanı servis raporlarında hiç yer almaz (E07-23 anahtar listesinin özü).
PARA_ANAHTARLARI = frozenset(
    {
        "maliyet",
        "tutar",
        "fiyat",
        "unit_cost",
        "gelir",
        "birim_fiyat",
        "toplam_tutar",
        "iscilik_maliyeti",
    }
)


async def giris(client, username: str, password: str = "parola1234") -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def kullanicilar(db, kullanici_ac, birimli_kullanici_ac) -> dict[str, Any]:
    """mudur (SERVIS_YONETICI, TUMU), sef_g/sef_h (SERVIS_SEF), üç teknisyen,
    yonetim (YONETIM — personel izni yok), teknisyen rolü (rapor izni yok)."""
    k = {
        "mudur": await kullanici_ac("mudur", "SERVIS_YONETICI"),
        "yonetim": await kullanici_ac("yonetim", "YONETIM"),
        "satis": await kullanici_ac("satis", "SATIS"),
        "sef_g": await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF"),
        "sef_h": await birimli_kullanici_ac("sef_h", "SERVIS_SEF", ["HABERLESME"], saha_rolu="SEF"),
        "tek1": await birimli_kullanici_ac(
            "tek1", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "tek2": await birimli_kullanici_ac(
            "tek2", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "tek3": await birimli_kullanici_ac(
            "tek3", "SERVIS_TEKNISYEN", ["HABERLESME"], saha_rolu="TEKNISYEN"
        ),
    }
    for ad, tam_ad in (
        ("tek1", "Ali Veli"),
        ("tek2", "Aliye Kaya"),
        ("tek3", "Hasan Yıldız"),
        ("sef_g", "Selim Şef"),
    ):
        k[ad].full_name = tam_ad
    await db.commit()
    return k


async def altin_kur(db, kullanici_ac, birimli_kullanici_ac):
    k = await kullanicilar(db, kullanici_ac, birimli_kullanici_ac)
    return await servis_rapor_seed.kur(db, k), k


def para_anahtari_var(veri: Any) -> list[str]:
    """Yanıtta (iç içe) para anahtarı var mı — anahtar adı ile."""
    bulunan: list[str] = []
    if isinstance(veri, dict):
        for anahtar, deger in veri.items():
            if anahtar in PARA_ANAHTARLARI:
                bulunan.append(anahtar)
            bulunan += para_anahtari_var(deger)
    elif isinstance(veri, list):
        for deger in veri:
            bulunan += para_anahtari_var(deger)
    return bulunan


def anahtarlar(veri: Any) -> set[str]:
    sonuc: set[str] = set()
    if isinstance(veri, dict):
        for anahtar, deger in veri.items():
            sonuc.add(anahtar)
            sonuc |= anahtarlar(deger)
    elif isinstance(veri, list):
        for deger in veri:
            sonuc |= anahtarlar(deger)
    return sonuc
