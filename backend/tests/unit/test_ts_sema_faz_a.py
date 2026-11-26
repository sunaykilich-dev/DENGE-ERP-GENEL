"""Faz A şeması (e1a000000001) ile model sözlüklerinin tutarlılığı.

Migration CHECK metinleri elle yazıldı; model tuple'ı ya da konum koşulu
değişip migration unutulursa şema ile servis kuralı ayrışır.
"""

import importlib.util
from pathlib import Path

from app.models.teknik_servis import KONUM_DURUMLARI, OLAY_TURLERI, _konum_kosulu
from app.services.teknik_servis import is_emirleri, zaman

_YOL = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _goc():
    dosya = next(_YOL.glob("e1a000000001_*.py"))
    spec = importlib.util.spec_from_file_location("faz_a_goc", dosya)
    modul = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(modul)
    return modul


def test_migration_zinciri() -> None:
    goc = _goc()
    assert goc.revision == "e1a000000001"
    assert goc.down_revision == "d4a000000002"


def test_olay_turleri_ve_konum_kosulu_ayni() -> None:
    goc = _goc()
    assert set(goc._YENI_OLAYLAR) == set(OLAY_TURLERI)
    for on in ("bas", "bit"):
        assert goc._konum_kosulu(on) == _konum_kosulu(on)
    assert KONUM_DURUMLARI == ("ALINDI", "ALINAMADI")


def test_tek_cihaz_yalniz_planli_bakimda() -> None:
    """M1.6 (tek cihaz) 2026-11-24 sahip kararıyla kalktı; yalnız PB 1 cihaz."""
    for tur, kural in is_emirleri.TUR_KURALLARI.items():
        assert kural.azami_seri == (1 if tur == "PB" else None), tur
    assert "yeniden_ac" not in is_emirleri.UC_HEDEFLERI


def test_konum_okumasi_gecersizse_alinamadi() -> None:
    assert zaman.KonumOkuma(41.0, 29.0).alindi
    assert not zaman.KonumOkuma(None, 29.0).alindi
    assert not zaman.KonumOkuma(91.0, 29.0).alindi
    assert not zaman.KonumOkuma(float("nan"), 29.0).alindi
