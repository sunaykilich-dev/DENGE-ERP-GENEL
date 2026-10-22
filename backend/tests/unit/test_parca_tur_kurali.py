"""Yedek parça defteri: tür kuralı ↔ şema, az stok tek fonksiyon, tek yazıcı (TS-130, TS-135)."""

import re
from pathlib import Path

import pytest

from app.models import StockMovement
from app.models.stock import SERVIS_HAREKET_TURLERI, SERVIS_HAREKET_YONU
from app.services.teknik_servis import parca

APP = Path(__file__).resolve().parents[2] / "app"


def _kisit(ad: str) -> str:
    for k in StockMovement.__table__.constraints:
        if k.name == ad:
            return str(k.sqltext)
    raise AssertionError(f"kısıt yok: {ad}")


def test_tur_kurali_check_ile_ayni() -> None:
    """Yazıcının kullandığı tür → (neden, işaret) tablosu şemadaki CHECK'in kaynağı."""
    ifade = _kisit("ck_stok_hareket_tur_yon")
    for tur, (neden, isaret) in SERVIS_HAREKET_YONU.items():
        kosul = "qty > 0" if isaret > 0 else "qty < 0"
        assert f"(hareket_turu = '{tur}' AND reason = '{neden}' AND {kosul})" in ifade
    assert "hareket_turu = 'TERS_KAYIT' AND reversal_of_id IS NOT NULL" in ifade
    assert set(SERVIS_HAREKET_YONU) | {"TERS_KAYIT"} == set(SERVIS_HAREKET_TURLERI)


def test_tur_adlari_tam() -> None:
    assert set(parca.HAREKET_TURU_ADLARI) == set(SERVIS_HAREKET_TURLERI)


@pytest.mark.parametrize(
    ("toplam", "asgari", "beklenen"),
    [
        (0, None, "YOK"),
        (-1, 3, "YOK"),
        (0, 3, "YOK"),
        (2, 3, "AZ"),
        (3, 3, "YETERLI"),
        (5, 3, "YETERLI"),
        (1, 0, "YETERLI"),
        (1, None, "YETERLI"),
    ],
)
def test_stok_durumu(toplam, asgari, beklenen) -> None:
    assert parca.stok_durumu(toplam, asgari) == beklenen


def test_durum_ifadesi_ayni_esikler() -> None:
    """SQL karşılığı aynı eşikleri taşır (DB eşitliği entegrasyon testinde)."""
    from sqlalchemy import literal
    from sqlalchemy.dialects import postgresql

    metin = str(
        parca.durum_ifadesi(literal(1), literal(2)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "YOK" in metin and "AZ" in metin and "YETERLI" in metin


def test_servis_defterine_tek_yazici() -> None:
    """`StockMovement(` yalnız canlı `services/stock.py` ve `teknik_servis/parca.py`'de
    kurulur (E11-01 kabul 1)."""
    bulunan = sorted(
        str(p.relative_to(APP)).replace("\\", "/")
        for p in APP.rglob("*.py")
        if re.search(r"(?<!class )\bStockMovement\(", p.read_text(encoding="utf-8"))
    )
    assert bulunan == ["services/stock.py", "services/teknik_servis/parca.py"]


def test_parca_saati_yalniz_clock() -> None:
    metin = (APP / "services/teknik_servis/parca.py").read_text(encoding="utf-8")
    assert "datetime.now" not in metin and "date.today" not in metin


def test_kanca_ve_uyari_kayitli() -> None:
    import app.services.teknik_servis  # noqa: F401
    from app.services.teknik_servis import kancalar
    from app.services.teknik_servis import uyarilar as ts_uyarilar

    assert parca.talepleri_kapat in kancalar.kayitlilar("durum_degisti")
    kayit = ts_uyarilar.kayitlar()["parca"]
    assert (("parca.yonet",), parca.az_stok_uyarisi) in kayit
    assert (("parca.kullan",), parca.parca_geldi_uyarisi) in kayit
