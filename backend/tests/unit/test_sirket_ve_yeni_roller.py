"""KARARLAR 2026-11-04: şirket sözlüğü, Set Bariyer, Taşıma, yeni roller — DB gerektirmez."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.rbac import BIRIM_KODLARI, SIRKET_KODLARI
from app.permissions import (
    BIRIMLER,
    MOBILITE_SIRKETI,
    ROLES,
    SCOPE_ALL,
    SCOPE_OWN_UNITS,
    SIRKETLER,
    VARSAYILAN_BIRIM_SIRKETLERI,
    YALNIZ_OFIS_ROLLERI,
    YUKSEK_YETKILI_IZINLER,
)

_YOL = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _goc():
    dosya = next(_YOL.glob("f1a000000001_*.py"))
    spec = importlib.util.spec_from_file_location("sirket_goc", dosya)
    modul = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(modul)
    return modul


# --- Migration ---------------------------------------------------------------------


def test_migration_zinciri() -> None:
    goc = _goc()
    assert goc.revision == "f1a000000001"
    assert goc.down_revision == "e1a000000003"


def test_migration_sozlukleri_kodla_ayni() -> None:
    """Migration CHECK listeleri elle yazıldı; model/izin sözlüğü değişip
    migration unutulursa şema ile servis kuralı ayrışır."""
    from app.models.teknik_servis import SERVIS_TURLERI

    goc = _goc()
    assert tuple(goc.YENI_BIRIMLER) == BIRIM_KODLARI
    # fcsatis00001 (KARARLAR 2026-11-09 S4.1) TESLIMAT'ı ekledi.
    assert set(goc.YENI_TURLER) | {"TESLIMAT"} == set(SERVIS_TURLERI)
    assert dict(goc.SIRKETLER) == SIRKETLER
    assert dict(goc.BIRIM_SIRKETLERI) == VARSAYILAN_BIRIM_SIRKETLERI


def test_migration_butun_birim_kisitlarini_kapsar() -> None:
    """Modeldeki her `ck_*_birim` kısıtı migration listesinde (BARIYER eksik kalmasın)."""
    from sqlalchemy import CheckConstraint

    import app.models  # noqa: F401
    from app.db import Base

    modelde = {
        (t.name, c.name)
        for t in Base.metadata.sorted_tables
        for c in t.constraints
        if isinstance(c, CheckConstraint)
        and c.name
        and c.name.endswith("_birim")
        and c.name not in ("ck_products_birim", "ck_svceq_cihaz_birim")
        and t.name != "birim_sirketleri"
    }
    goc = _goc()
    assert {(t, ad) for t, ad, _ in goc.BIRIM_KISITLARI} == modelde


# --- Sözlükler ---------------------------------------------------------------------


def test_sirket_sozlugu_ve_birim_eslemesi() -> None:
    assert SIRKETLER == {
        "TELEKOM": "DENGE TELEKOM",
        "ELEKTRONIK": "DENGE ELEKTRONİK",
        "MOBILITE": "DENGE MOBİLİTE",
    }
    assert tuple(SIRKETLER) == SIRKET_KODLARI
    assert MOBILITE_SIRKETI == "MOBILITE"
    assert set(VARSAYILAN_BIRIM_SIRKETLERI) == set(BIRIMLER)
    assert VARSAYILAN_BIRIM_SIRKETLERI == {
        "HABERLESME": "TELEKOM",
        "POC": "TELEKOM",
        "GUVENLIK": "ELEKTRONIK",
        "BARIYER": "ELEKTRONIK",
        "MOBILITE": "MOBILITE",
        "ARAC_TAKIP": "MOBILITE",
    }


def test_bariyer_birimi() -> None:
    assert BIRIMLER["BARIYER"] == "Set Bariyer"
    assert "BARIYER" in BIRIM_KODLARI


def test_tasima_turu_kurulum_toplama_gibi() -> None:
    from app.models.teknik_servis import SERVIS_TURLERI
    from app.services.teknik_servis import is_emirleri, onay

    assert "TASIMA" in SERVIS_TURLERI
    assert is_emirleri.TUR_ADLARI["TASIMA"] == "Taşıma"
    assert onay.SERVIS_TURU_ADLARI["TASIMA"] == "Taşıma"
    assert is_emirleri.TUR_KURALLARI["TASIMA"] == is_emirleri.TUR_KURALLARI["KURULUM"]
    assert is_emirleri.TUR_KURALLARI["TASIMA"] == is_emirleri.TUR_KURALLARI["TOPLAMA"]
    assert set(is_emirleri.TUR_ADLARI) == set(SERVIS_TURLERI)
    assert set(onay.SERVIS_TURU_ADLARI) == set(SERVIS_TURLERI)


# --- Roller ------------------------------------------------------------------------


def test_saha_sorumlusu_izin_kilidi() -> None:
    """Tayin yok, kalite onayı yok, maliyet yok; kendi birimi (karar §3)."""
    ad, izinler, kapsam = ROLES["SAHA_SORUMLUSU"]
    assert ad == "Saha Sorumlusu"
    assert kapsam == SCOPE_OWN_UNITS
    assert {"servis.gor", "servis.yaz", "zaman.yaz"} <= set(izinler)
    yasak = {
        "servis.planla",
        "servis.kalite_onay",
        "servis.kapat",
        "maliyet.gor",
        "maliyet.yaz",
        "hesap.kart_yaz",
        "hesap.yaz",
    }
    assert yasak & set(izinler) == set()


def test_satis_destek_izin_kilidi() -> None:
    ad, izinler, kapsam = ROLES["SATIS_DESTEK"]
    assert ad == "Satış Destek"
    assert kapsam == SCOPE_OWN_UNITS
    assert {"teklif.gor", "teklif.yaz", "siparis.gor", "siparis.yaz", "servis.gor"} <= set(izinler)
    # Servis kayıtlarını ve atölye teşhisini OKUR, yazmaz; maliyet ve onay yok.
    assert "atolye.gor" in izinler
    yasak = {
        "servis.yaz",
        "servis.planla",
        "atolye.yaz",
        "maliyet.gor",
        "teklif.onayla",
        "teklif.iskonto_onayla",
        "hesap.yaz",
    }
    assert yasak & set(izinler) == set()


def test_finans_yoneticisi_izin_kilidi() -> None:
    ad, izinler, kapsam = ROLES["FINANS_YONETICI"]
    assert ad == "Finans Yöneticisi"
    assert kapsam == SCOPE_ALL
    assert {
        "maliyet.gor",
        "tahsilat.gor",
        "tahsilat.yaz",
        "rapor.gor",
        "servis_rapor.gor",
        "servis_rapor.disaaktar",
    } <= set(izinler)
    # Tarife/maliyet girişi yalnız ADMIN (KD-11); yüksek yetki yok.
    assert "maliyet.yaz" not in izinler
    assert YUKSEK_YETKILI_IZINLER & set(izinler) == set()


def test_finans_uzmani_adi_ve_ofis_kisiti() -> None:
    assert ROLES["MUHASEBE_DESTEK"][0] == "Finans Uzmanı"
    assert "MUHASEBE_DESTEK" in YALNIZ_OFIS_ROLLERI


# --- Şirket servis yardımcıları (saf) ------------------------------------------------


@pytest.mark.sirket_ayrimi
def test_baglanmamis_kullanici_fail_closed() -> None:
    from app.services import sirketler

    kisi = SimpleNamespace()
    assert sirketler.etkin_birimler(kisi) == frozenset()
    assert not sirketler.mobilite_acik_mi(kisi)
    assert not sirketler.birim_etkin_sirkette_mi(kisi, "GUVENLIK")
    # Bilinçli süzgeçsiz sahte kullanıcı
    assert sirketler.etkin_birimler(SimpleNamespace(_sirket_birimleri=None)) is None


@pytest.mark.sirket_ayrimi
def test_varsayilan_sirket_sirasi() -> None:
    from app.services import sirketler

    kat = [
        sirketler.SirketKaydi("TELEKOM", "DENGE TELEKOM", ("HABERLESME", "POC")),
        sirketler.SirketKaydi("ELEKTRONIK", "DENGE ELEKTRONİK", ("BARIYER", "GUVENLIK")),
        sirketler.SirketKaydi("MOBILITE", "DENGE MOBİLİTE", ("ARAC_TAKIP", "MOBILITE")),
    ]

    def kisi(rol, uyelik, birincil=None):
        return SimpleNamespace(
            role=SimpleNamespace(code=rol),
            sirket_kodlari=uyelik,
            birincil_birim=birincil,
        )

    # Birincil birimin şirketi önce
    assert sirketler.varsayilan_sirket(kisi("X", ["TELEKOM", "ELEKTRONIK"], "GUVENLIK"), kat) == (
        "ELEKTRONIK"
    )
    # Birimsiz çok şirketli: canlı mobilite önce
    assert sirketler.varsayilan_sirket(kisi("X", sorted(SIRKETLER)), kat) == "MOBILITE"
    # Tek şirket
    assert sirketler.varsayilan_sirket(kisi("X", ["TELEKOM"]), kat) == "TELEKOM"
    # Üyelik yok → None (fail-closed); ADMIN üyeliksiz de hepsini seçer
    assert sirketler.varsayilan_sirket(kisi("X", []), kat) is None
    assert sirketler.uye_sirketler(kisi("ADMIN", []), kat) == ["TELEKOM", "ELEKTRONIK", "MOBILITE"]
