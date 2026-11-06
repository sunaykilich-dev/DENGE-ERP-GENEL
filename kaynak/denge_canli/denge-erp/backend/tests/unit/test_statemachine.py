"""Durum makinesi kuralları."""

import pytest

from app.services.statemachine import CIHAZ, HAT, MAKINELER, IzinsizGecis


@pytest.mark.parametrize("makine", MAKINELER.values(), ids=lambda m: m.ad)
class TestGenelKurallar:
    def test_her_duruma_ulasilabilir(self, makine):
        """Hiçbir geçişin hedefi olmayan durum = tasarım hatası ya da ölü tanım."""
        hedefler = set().union(*makine.gecisler.values())
        ulasilamayan = makine.durumlar - hedefler - makine.baslangiclar
        assert not ulasilamayan, f"{makine.ad}: ulaşılamayan durum {ulasilamayan}"

    def test_baslangic_durumu_tanimli(self, makine):
        """Giriş durumu olmayan makine, hiçbir kaydın doğamayacağı makinedir."""
        assert makine.baslangiclar
        assert makine.baslangiclar <= makine.durumlar

    def test_terminal_durumdan_cikis_yok(self, makine):
        for durum in makine.terminaller:
            assert makine.sonraki(durum) == frozenset()

    def test_ayni_duruma_gecis_reddedilir(self, makine):
        durum = next(iter(makine.gecisler))
        with pytest.raises(IzinsizGecis):
            makine.dogrula(durum, durum)

    def test_tanimsiz_hedefe_gecis_reddedilir(self, makine):
        durum = next(iter(makine.gecisler))
        with pytest.raises(IzinsizGecis):
            makine.dogrula(durum, "UYDURMA_DURUM")


class TestCihaz:
    def test_hurdadan_aktife_gecilemez(self):
        """Brief §4.2'nin açık örneği."""
        with pytest.raises(IzinsizGecis, match="terminal"):
            CIHAZ.dogrula("HURDA", "AKTIF")

    def test_montaj_akisi(self):
        for mevcut, hedef in (
            ("STOKTA", "TEST_EDILDI"),
            ("TEST_EDILDI", "REZERVE"),
            ("REZERVE", "SEVK_EDILDI"),
            ("SEVK_EDILDI", "MONTAJ_BEKLIYOR"),
            ("MONTAJ_BEKLIYOR", "AKTIF"),
        ):
            CIHAZ.dogrula(mevcut, hedef)

    def test_sok_tak_akisi(self):
        """Söküm → aynı müşterinin başka aracına doğrudan montaj (brief §7.3)."""
        CIHAZ.dogrula("AKTIF", "SOKULDU")
        CIHAZ.dogrula("SOKULDU", "AKTIF")
        CIHAZ.dogrula("SOKULDU", "YENIDEN_STOKTA")

    def test_ariza_akisi(self):
        for mevcut, hedef in (
            ("AKTIF", "ARIZALI"),
            ("ARIZALI", "RMA"),
            ("RMA", "TAMIRDE"),
            ("TAMIRDE", "YENIDEN_STOKTA"),
            ("YENIDEN_STOKTA", "STOKTA"),
        ):
            CIHAZ.dogrula(mevcut, hedef)

    def test_aktif_cihaz_dogrudan_stoga_donemez(self):
        """Önce sökülmeli — aksi halde cihaz-araç kaydı açık kalırdı."""
        with pytest.raises(IzinsizGecis):
            CIHAZ.dogrula("AKTIF", "STOKTA")

    def test_kayip_cihaz_bulunabilir(self):
        CIHAZ.dogrula("KAYIP_CALINTI", "STOKTA")

    def test_sonraki_secenekler_arayuz_icin(self):
        assert CIHAZ.sonraki("ARIZALI") == frozenset({"RMA", "HURDA"})


class TestEnKisaYol:
    """İçe aktarma, sahada takılı cihazı durum zincirini yürüyerek AKTİF'e
    alıyor; alana doğrudan atama geçmişi uydururdu."""

    def test_stoktan_aktife(self):
        assert CIHAZ.yol("STOKTA", "AKTIF") == ("SEVK_EDILDI", "AKTIF")

    def test_ayni_duruma_yol_bos(self):
        assert CIHAZ.yol("AKTIF", "AKTIF") == ()

    def test_terminalden_yol_yok(self):
        assert CIHAZ.yol("HURDA", "AKTIF") == ()

    def test_yolun_her_adimi_gecerli(self):
        mevcut = "STOKTA"
        for adim in CIHAZ.yol("STOKTA", "AKTIF"):
            CIHAZ.dogrula(mevcut, adim)
            mevcut = adim
        assert mevcut == "AKTIF"


class TestHat:
    def test_askiya_alma_ve_geri_acma(self):
        HAT.dogrula("AKTIF", "ASKIDA")
        HAT.dogrula("ASKIDA", "AKTIF")

    def test_iptal_terminaldir(self):
        with pytest.raises(IzinsizGecis):
            HAT.dogrula("IPTAL", "AKTIF")
