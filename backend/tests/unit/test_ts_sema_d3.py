"""Teknik servis Dalga 3 şema iskeletinin tek-kaynak sözleşmeleri (TS-180).

Makine durum kümesi = CHECK değer kümesi (aynı tuple); e-posta kodları SLA
bildirim kodlarının alt kümesi; MESAI takvimi revizyonu zincirde YOK (KD-23)
ve eşleme revizyonu doğrudan bildirim revizyonuna bağlı; yeni toplayan kanca
(`atama_uyarilari`) değer döndürür ve kayıt sırasını korur.
"""

import importlib.util
from pathlib import Path

from app.models.egitim import ServiceCompetencyRequirement
from app.models.servis_kiralama import KIRALIK_SAYIM_DURUMLARI
from app.models.teknik_servis import (
    EPOSTA_ANLIK_KODLAR,
    EPOSTA_AZAMI_DENEME,
    EPOSTA_DURUMLARI,
    EPOSTA_TURLERI,
    SERVIS_TURLERI,
    SLA_UYARI_KODLARI,
    ServiceMailOutbox,
)
from app.services import statemachine as sm
from app.services.teknik_servis import kancalar

SURUMLER = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _rev(dosya_on_eki: str):
    yol = next(SURUMLER.glob(f"{dosya_on_eki}_*.py"))
    spec = importlib.util.spec_from_file_location(yol.stem, yol)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_kiralik_sayim_makinesi_check_kumesiyle_ayni() -> None:
    assert sm.MAKINELER["kiralik_sayim"] is sm.KIRALIK_SAYIM
    assert sm.KIRALIK_SAYIM.durumlar == frozenset(KIRALIK_SAYIM_DURUMLARI)
    assert sm.KIRALIK_SAYIM.terminaller == frozenset({"ONAYLANDI", "IPTAL"})


def test_eposta_sozlukleri() -> None:
    assert set(EPOSTA_ANLIK_KODLAR) <= set(SLA_UYARI_KODLARI)
    assert EPOSTA_TURLERI == ("ANLIK", "GUNLUK_OZET")
    assert "BEKLIYOR" in EPOSTA_DURUMLARI
    kisit = {c.name: str(c.sqltext) for c in ServiceMailOutbox.__table__.constraints if c.name}
    assert f"<= {EPOSTA_AZAMI_DENEME}" in kisit["ck_smo_deneme"]


def test_yetkinlik_eslemesi_tur_check_servis_turleriyle_ayni() -> None:
    kisit = {
        c.name: str(c.sqltext)
        for c in ServiceCompetencyRequirement.__table__.constraints
        if c.name == "ck_scr_tur"
    }["ck_scr_tur"]
    for tur in SERVIS_TURLERI:
        assert f"'{tur}'" in kisit, tur
    migration = _rev("d3a000000004")
    # f1a000000001 (KARARLAR 2026-11-04, TASIMA) `ck_scr_tur`'u yeniden kurdu:
    # güncel liste o migration'dadır; d3a000000004 tarihsel listedir.
    assert set(migration._SERVIS_TURLERI) | {"TASIMA"} == set(SERVIS_TURLERI)
    assert set(_rev("f1a000000001").YENI_TURLER) == set(SERVIS_TURLERI)


def test_zincir_mesai_revizyonu_atlandi() -> None:
    """KD-23: MESAI kararı yok → `d3a000000003` yok, 004 → 002'ye bağlı."""
    assert not list(SURUMLER.glob("d3a000000003_*.py"))
    assert _rev("d3a000000001").down_revision == "d2a000000007"
    assert _rev("d3a000000002").down_revision == "d3a000000001"
    assert _rev("d3a000000004").down_revision == "d3a000000002"


async def test_atama_uyarilari_toplar_ve_sirayi_korur() -> None:
    assert await kancalar.atama_uyarilari(None, None, [1, 2]) == []

    async def birinci(_db, _so, kimlikler):
        assert kimlikler == (1, 2)
        return ["A"]

    async def ikinci(_db, _so, _kimlikler):
        return None

    async def ucuncu(_db, _so, _kimlikler):
        return ["B", "C"]

    try:
        for fn in (birinci, ikinci, ucuncu):
            kancalar.kaydet("atama_uyarilari", fn)
        assert await kancalar.atama_uyarilari(None, None, iter([1, 2])) == ["A", "B", "C"]
    finally:
        for fn in (birinci, ikinci, ucuncu):
            kancalar._KAYIT["atama_uyarilari"].remove(fn)


def test_dalga3_modulleri_paket_sirasinda() -> None:
    kaynak = (
        Path(kancalar.__file__).with_name("__init__.py").read_text(encoding="utf-8").splitlines()
    )

    def sira(modul: str) -> int:
        return next(
            i
            for i, s in enumerate(kaynak)
            if s.startswith(f"from app.services.teknik_servis import {modul} ")
        )

    assert sira("veri_kalitesi") < sira("rapor_tanimlari") < sira("rapor_motoru")
    assert sira("rapor_tanimlari") < sira("eposta")
