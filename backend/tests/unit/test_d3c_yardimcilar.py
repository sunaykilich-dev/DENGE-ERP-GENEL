"""D3-C saf yardımcıları (TS-188/191/192/193) — DB'siz."""

from datetime import UTC, date, datetime

from app.permissions import PERMISSIONS
from app.services.teknik_servis import ana_veri, ekipman, is_emirleri, rapor_kalite


def test_donem_metni() -> None:
    assert ana_veri.donem_metni(None, date(2026, 1, 1)) == "Dönem bilgisi yok"
    assert ana_veri.donem_metni(date(2026, 1, 1), date(2026, 12, 31)) == "01.01.2026–31.12.2026"
    # timestamptz Türkiye gününe çevrilir (UTC 21:30 = ertesi gün 00:30 İstanbul).
    an = datetime(2025, 12, 31, 21, 30, tzinfo=UTC)
    assert ana_veri.donem_metni(an, an).startswith("01.01.2026")


def test_kalite_kontrol_izinleri_katalogda() -> None:
    for k in rapor_kalite.KONTROLLER.values():
        assert k.grup in rapor_kalite.GRUPLAR
        assert set(k.izinler) <= set(PERMISSIONS), k.kod
        assert (k.sorgu is None) != (k.satirlar is None), k.kod
        assert k.sutunlar


def test_ekipman_kalite_kodlari() -> None:
    assert {"seri_eksik", "lokasyonsuz", "hesapsiz", "sozlesmesiz_kurulu", "mukerrer"} <= set(
        ekipman.KALITE_KODLARI
    )
    assert "mukerrer_grup" not in ekipman.KALITE_KODLARI  # grup listesi ayrı uçta
    assert {"bakim_gecikmis", "tekrar_ariza"} <= ekipman.KPI_KODLARI


def test_bolge_farki_turkce_katlama() -> None:
    assert not ekipman._bolge_farkli(None, "B Kapısı")
    assert not ekipman._bolge_farkli("b kapısı ", "B KAPISI")
    assert ekipman._bolge_farkli("A Kapısı", "B Kapısı")


def test_cihaz_anahtarlari() -> None:
    assert is_emirleri._cihaz_anahtarlari(None, None) == []
    assert is_emirleri._cihaz_anahtarlari("356938035643809", " ab-1 ") == [
        "356938035643809",
        "AB-1",
    ]
    assert set(is_emirleri.CIHAZ_KUTUGU_BIRIMLERI) == {"MOBILITE", "ARAC_TAKIP"}
