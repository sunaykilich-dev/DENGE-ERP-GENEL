"""Ana Panel bileşen kaydı (KARARLAR 2026-11-09 S8) — saf kurallar.

Kayıt tek kaynaktır: izinler katalogda olmalı, sistem varsayılanı bugünkü
paneli taşımalı, ön yüz her bileşeni aynı kodla çizebilmeli. `suz`/`dogrula`
izinsiz ve bilinmeyen bileşeni düşürür/reddeder.
"""

import re
from pathlib import Path

import pytest

from app.permissions import PERMISSIONS, ROLES, permissions_of
from app.services import ana_panel_duzeni as d

FRONTEND_KAYDI = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "pages" / "anaPanel" / "kayit.tsx"
)


def _izin(*kodlar: str):
    return lambda k: k in kodlar


def test_bilesenler_yalniz_katalogdaki_izinlere_baglanir() -> None:
    for b in d.BILESENLER:
        assert b.izinler, b.kod
        assert set(b.izinler) <= set(PERMISSIONS), b.kod
        assert b.varsayilan_boyut in d.BOYUTLAR, b.kod
        assert b.tur in ("gosterge", "kart"), b.kod
    kodlar = [b.kod for b in d.BILESENLER]
    assert len(kodlar) == len(set(kodlar))


def test_sistem_varsayilani_bugunku_panel_ve_kayitta() -> None:
    kodlar = [k for k, _ in d.SISTEM_VARSAYILANI]
    assert set(kodlar) <= set(d.BILESEN_HARITASI)
    # Bugünkü düzen: 8 gösterge, 4 kart, 5 grafik; satış bileşeni yok.
    assert kodlar[:8] == [
        "kpi_acik_is",
        "kpi_planli_bakim",
        "kpi_acil_ariza",
        "kpi_poc_acik",
        "kpi_sla_riski",
        "kpi_sahadaki_ekip",
        "kpi_askida",
        "kpi_bekleyen_onay",
    ]
    assert "tekliflerim" not in kodlar
    assert dict(d.SISTEM_VARSAYILANI)["aktif_isler"] == d.GENIS


def test_planlanan_satis_bilesenleri_kayitta_degil() -> None:
    """Uç yokken kataloğa konmaz (boş kart çizilmesin)."""
    assert not set(d.PLANLANAN_BILESENLER) & set(d.BILESEN_HARITASI)


def test_panel_yonet_yalniz_yonetici_rollerinde() -> None:
    sahipler = {r for r in ROLES if d.ROL_DUZENI_IZNI in permissions_of(r)}
    assert sahipler == {"ADMIN", "SERVIS_YONETICI", "SATIS_MUDURU"}
    assert d.ROL_DUZENI_IZNI not in permissions_of("YONETIM")


def test_suz_izinsiz_bilinmeyen_ve_tekrari_dusurur() -> None:
    kayit = [
        {"kod": "aktif_isler", "boyut": "DAR", "gorunur": True},
        {"kod": "ekip_durumu", "boyut": "DAR"},  # operasyon.gor yok
        {"kod": "eski_bilesen", "boyut": "DAR"},  # kayıttan kalkmış
        {"kod": "aktif_isler", "boyut": "GENIS"},  # tekrar
        {"kod": "grafik_durum", "boyut": "DEV", "gorunur": False},  # bozuk boyut
        "bozuk",
    ]
    assert d.suz(kayit, _izin("servis.gor")) == [
        {"kod": "aktif_isler", "boyut": "DAR", "gorunur": True},
        {"kod": "grafik_durum", "boyut": "DAR", "gorunur": False},
    ]


def test_sistem_varsayilani_izinle_suzulur_bos_kalirsa_izinliler_gelir() -> None:
    teknisyen = d.sistem_varsayilani(_izin("servis.gor"))
    assert "ekip_durumu" not in {o["kod"] for o in teknisyen}
    assert len(teknisyen) == len(d.SISTEM_VARSAYILANI) - 1
    satis = d.sistem_varsayilani(_izin("teklif.gor"))
    assert satis == [{"kod": "tekliflerim", "boyut": "DAR", "gorunur": True}]
    assert d.sistem_varsayilani(_izin("hat.gor")) == []


def test_dogrula_hatalari() -> None:
    izin = _izin("servis.gor")
    with pytest.raises(d.DuzenHatasi):
        d.dogrula([{"kod": "yok", "boyut": "DAR"}], izin, kime="yetkiniz")
    with pytest.raises(d.DuzenHatasi):
        d.dogrula([{"kod": "aktif_isler", "boyut": "DAR"}] * 2, izin, kime="yetkiniz")
    with pytest.raises(d.DuzenYetkiHatasi):
        d.dogrula([{"kod": "tekliflerim", "boyut": "DAR"}], izin, kime="yetkiniz")
    assert d.dogrula(
        [{"kod": "aktif_isler", "boyut": "GENIS", "gorunur": False}], izin, kime=""
    ) == [{"kod": "aktif_isler", "boyut": "GENIS", "gorunur": False}]


def test_on_yuz_her_bilesen_icin_cizim_tasir() -> None:
    """Sunucu kataloğa koyduğu her bileşeni ön yüz aynı kodla çizebilmeli."""
    if not FRONTEND_KAYDI.is_file():
        pytest.skip("frontend/src yok (yalnız backend)")
    metin = FRONTEND_KAYDI.read_text(encoding="utf-8")
    eksik = [b.kod for b in d.BILESENLER if not re.search(rf"\b{b.kod}\s*:", metin)]
    assert not eksik, f"Ön yüzde çizimi olmayan bileşen: {eksik}"
