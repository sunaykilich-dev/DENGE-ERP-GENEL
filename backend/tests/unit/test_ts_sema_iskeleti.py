"""Teknik servis şema iskeletinin tek-kaynak sözleşmeleri (TS-018).

Durum makinesi ile CHECK kısıtının değer kümesi AYNI tuple'dan gelmeli:
makinede olup CHECK'te olmayan bir durum 409 yerine anlamsız bir DB hatası,
CHECK'te olup makinede olmayan bir durum ise "ulaşılamayan durum" üretir.
"""

import pytest

from app.models.rbac import BIRIM_KODLARI, birim_check
from app.models.servis_bakim import BAKIM_SOZLESME_DURUMLARI
from app.models.servis_ekipman import EKIPMAN_DURUMLARI, model_anahtari
from app.models.teknik_servis import (
    DURUM_GRUPLARI,
    KISI_SAATE_DAHIL,
    SERVIS_DURUMLARI,
    SERVIS_KATEGORILERI,
    SERVIS_TURLERI,
    ZAMAN_FAALIYETLERI,
    durum_grubu,
)
from app.services.statemachine import BAKIM_SOZLESMESI, SERVIS_EKIPMANI, SERVIS_IS_EMRI
from app.services.teknik_servis import kancalar
from app.services.teknik_servis.is_emirleri import TUR_KURALLARI, UC_HEDEFLERI, tur_kategorisi


def test_makine_durumlari_check_kumesiyle_ayni() -> None:
    assert SERVIS_IS_EMRI.durumlar == frozenset(SERVIS_DURUMLARI)
    assert SERVIS_EKIPMANI.durumlar == frozenset(EKIPMAN_DURUMLARI)
    assert BAKIM_SOZLESMESI.durumlar == frozenset(BAKIM_SOZLESME_DURUMLARI)


def test_kargoda_ve_test_kontrol_servis_isi_durumu_degil() -> None:
    """KD-13: atölye ayrıntısı atölye kaydındadır."""
    assert "KARGODA" not in SERVIS_DURUMLARI
    assert "TEST_KONTROL" not in SERVIS_DURUMLARI


def test_iptal_terminal_kapanmis_is_yeniden_acilmaz() -> None:
    """M1.7 (Faz A): kapanmış iş yeniden açılmaz; bağlı yeni iş açılır."""
    assert SERVIS_IS_EMRI.sonraki("IPTAL") == frozenset()
    assert "TEKRAR_ACILDI" not in SERVIS_IS_EMRI.sonraki("TAMAMLANDI")
    assert SERVIS_IS_EMRI.sonraki("KAPATILDI") == frozenset()


def test_durum_gruplari() -> None:
    assert DURUM_GRUPLARI["ACIK"] | DURUM_GRUPLARI["KAPALI"] == frozenset(SERVIS_DURUMLARI)
    assert "BEKLEMEDE" not in DURUM_GRUPLARI["SAYAC_ACILABILIR"]
    assert durum_grubu("KAPATILDI") == "COZULDU"
    assert durum_grubu("IPTAL") == "IPTAL"
    assert durum_grubu("BEKLEMEDE") == "ACIK"


def test_tur_kurallari_her_turu_ve_kategoriyi_kapsar() -> None:
    assert set(TUR_KURALLARI) == set(SERVIS_TURLERI)
    assert {k.kategori for k in TUR_KURALLARI.values()} <= set(SERVIS_KATEGORILERI)
    assert tur_kategorisi("PB") == "PLANLI_BAKIM"
    # SLA yalnız günlük serviste ölçülür.
    assert {t for t, k in TUR_KURALLARI.items() if k.sla_olculur} == {
        "ARIZA",
        "PLANSIZ_BAKIM",
        "DESTEK",
    }


def test_uc_hedefleri_makinede_tanimli_durumlar() -> None:
    for kaynak, hedefler in UC_HEDEFLERI.items():
        assert hedefler <= frozenset(SERVIS_DURUMLARI), kaynak
    tamamlayanlar = {k for k, h in UC_HEDEFLERI.items() if "TAMAMLANDI" in h}
    assert tamamlayanlar == {"sonuc", "uzaktan", "atolye", "bakim_formu"}
    assert {k for k, h in UC_HEDEFLERI.items() if "KAPATILDI" in h} == {"kapat"}


def test_mola_kisi_saate_girmez() -> None:
    assert "MOLA" in ZAMAN_FAALIYETLERI
    assert "MOLA" not in KISI_SAATE_DAHIL
    assert "ISCILIK" not in ZAMAN_FAALIYETLERI  # KD-24


def test_birim_check_ifadesi() -> None:
    assert birim_check("birim") == (
        "birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')"
    )
    assert birim_check("birim", bos_olabilir=True).startswith("birim IS NULL OR ")
    assert len(BIRIM_KODLARI) == 5


def test_model_anahtari_bosluk_ve_tireyi_yok_sayar() -> None:
    assert model_anahtari("SC 5030 A") == model_anahtari("SC-5030 A")
    assert model_anahtari(None) is None


def test_bilinmeyen_kanca_adi_reddedilir() -> None:
    async def bos(*_a, **_k) -> None:
        return None

    with pytest.raises(ValueError, match="Bilinmeyen kanca"):
        kancalar.kaydet("durum_degisti_yanlis", bos)


async def test_kayitsiz_kanca_no_op_ve_kayit_sirasi() -> None:
    cagrilar: list[str] = []

    async def birinci(db, so, clock) -> None:
        cagrilar.append("1")

    async def ikinci(db, so, clock) -> None:
        cagrilar.append("2")

    onceki = kancalar.kayitlilar("oncelik_birim_degisti")
    try:
        # Gerçek kayıtlar (D2-G `sla.yeniden_damgala`) None argümanla çalışamaz: boşalt.
        kancalar._KAYIT["oncelik_birim_degisti"].clear()
        kancalar.kaydet("oncelik_birim_degisti", birinci)
        kancalar.kaydet("oncelik_birim_degisti", ikinci)
        kancalar.kaydet("oncelik_birim_degisti", birinci)  # ikinci kez eklenmez
        await kancalar.oncelik_birim_degisti(None, None, None)  # type: ignore[arg-type]
    finally:
        kancalar._KAYIT["oncelik_birim_degisti"][:] = list(onceki)
    assert cagrilar == ["1", "2"]
