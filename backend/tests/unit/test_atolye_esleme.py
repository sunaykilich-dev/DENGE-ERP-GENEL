"""Atölye ↔ servis işi eşlemesinin meta-testi (TS-090; E05 §3.2, kontrol B1).

E01 durum adları ya da makinesi değişirse bu test kırılır ve eşleme TEK
yerde (`atolye.SERVIS_DURUMU`) düzeltilir — sessiz sapma imkânsız.
"""

import pytest

from app.models.servis_atolye import ATOLYE_DURUMLARI
from app.models.teknik_servis import SERVIS_DURUMLARI
from app.services.statemachine import ATOLYE, SERVIS_IS_EMRI
from app.services.teknik_servis import atolye, is_emirleri


def test_her_atolye_durumunun_eslemesi_var() -> None:
    assert set(atolye.SERVIS_DURUMU) == set(ATOLYE_DURUMLARI)


def test_eslenen_hedefler_servis_makinesinde() -> None:
    assert set(atolye.SERVIS_DURUMU.values()) <= set(SERVIS_DURUMLARI)
    assert set(atolye.SERVIS_DURUMU.values()) <= SERVIS_IS_EMRI.durumlar


@pytest.mark.parametrize(
    ("kaynak", "hedef"),
    sorted((k, h) for k, hs in ATOLYE.gecisler.items() for h in hs),
)
def test_her_atolye_gecisi_servis_isinde_izinli(kaynak: str, hedef: str) -> None:
    a = atolye.SERVIS_DURUMU[kaynak]
    b = atolye.SERVIS_DURUMU[hedef]
    if a == b == "BEKLEMEDE":
        # Bekleme nedeni değişimi: önce bitir (→ ATOLYEDE), sonra yeniden beklet.
        assert SERVIS_IS_EMRI.izinli_mi("BEKLEMEDE", "ATOLYEDE")
        assert SERVIS_IS_EMRI.izinli_mi("ATOLYEDE", "BEKLEMEDE")
        return
    assert a == b or SERVIS_IS_EMRI.izinli_mi(a, b), (kaynak, hedef, a, b)


def test_kabulde_servis_isi_atolyeye_gecebilir() -> None:
    assert "MUSTERI_TALEBI" in SERVIS_IS_EMRI.baslangiclar
    assert SERVIS_IS_EMRI.izinli_mi("MUSTERI_TALEBI", atolye.SERVIS_DURUMU["KABUL_EDILDI"])


def test_bekleme_durumlarinin_nedeni_tanimli() -> None:
    beklemeler = {d for d, s in atolye.SERVIS_DURUMU.items() if s == "BEKLEMEDE"}
    assert beklemeler == set(atolye.BEKLEME_NEDENI)
    # E05 kontrol B3: PARCA değil MALZEME; DIS_SERVIS E01 kataloğunda.
    assert set(atolye.BEKLEME_NEDENI.values()) == {"MUSTERI_ONAYI", "MALZEME", "DIS_SERVIS"}


def test_atolye_kaynagi_eslenen_hedefleri_surebilir() -> None:
    hedefler = set(atolye.SERVIS_DURUMU.values())
    assert hedefler <= is_emirleri.UC_HEDEFLERI["atolye"] | is_emirleri.UC_HEDEFLERI["bekleme"]


def test_geri_almalar_makinede_ve_servis_isini_etkilemez() -> None:
    for kaynak, hedef in atolye.GERI_ALMALAR:
        assert ATOLYE.izinli_mi(kaynak, hedef)
        assert atolye.SERVIS_DURUMU[kaynak] == atolye.SERVIS_DURUMU[hedef]


def test_terminaller_servis_isinde_kapali() -> None:
    assert atolye.SERVIS_DURUMU["TESLIM_EDILDI"] == "TAMAMLANDI"
    assert atolye.SERVIS_DURUMU["IPTAL"] == "IPTAL"
    assert ATOLYE.terminaller == {"TESLIM_EDILDI", "IPTAL"}


def test_olay_yasak_anahtarlari_kisisel_alanlari_kapsar() -> None:
    assert atolye.KISISEL_ALANLAR <= atolye.OLAY_YASAK_ANAHTARLAR
