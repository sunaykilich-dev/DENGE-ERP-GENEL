"""Teklif kapsamı/etkin durum ve maliyet yardımcılarının saf kuralları (D2-E).

DB gerektirmez; entegrasyon testlerinin dayandığı kuralları tek tek kilitler:
bilinmeyen kapsam = RED (E07-D05), alanlar arası yazma ayrımı (B4), hesaplanan
"süresi doldu" (K7), iş günü (K12), dönem sınırı (E07-21), KDV dökümü
(E07-08), boş tarife aralığı (B8).
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import Quote, QuoteLine, QuoteVersion, ServiceLaborRate
from app.services import quotes as svc
from app.services.teknik_servis import maliyet


def _kullanici(scope: str, code: str = "X", birimler=(), uid: int = 1):
    return SimpleNamespace(
        id=uid,
        role=SimpleNamespace(scope=scope, code=code),
        birimler=[SimpleNamespace(birim=b) for b in birimler],
    )


def _teklif(birim=None, owner_id=1, status="TASLAK"):
    return Quote(quote_no="TKF2026-00001", customer_id=1, birim=birim, owner_id=owner_id, status=status)


class TestKapsam:
    def test_bilinmeyen_kapsam_reddedilir(self):
        u = _kullanici("BILINMEYEN")
        assert svc.teklif_kapsam_disinda_mi(u, _teklif())
        assert svc.teklif_kapsam_disinda_mi(u, _teklif("GUVENLIK"))
        assert str(svc._kapsam_kosulu(u)) == "false"

    def test_kendi_birimi(self):
        u = _kullanici("KENDI_BIRIMI", "SERVIS_SEF", ["GUVENLIK"])
        assert not svc.teklif_kapsam_disinda_mi(u, _teklif("GUVENLIK"))
        assert svc.teklif_kapsam_disinda_mi(u, _teklif("HABERLESME"))
        # Birimsiz satış teklifi birimli kullanıcıya görünmez (E07-02).
        assert svc.teklif_kapsam_disinda_mi(u, _teklif(None))
        # Birimsiz kullanıcı hiçbir şey görmez (fail-closed).
        assert svc.teklif_kapsam_disinda_mi(_kullanici("KENDI_BIRIMI"), _teklif("GUVENLIK"))

    def test_kendi_isleri_de_birim_uyeligiyle(self):
        u = _kullanici("KENDI_ISLERI", "SERVIS_TEKNISYEN", ["GUVENLIK"])
        assert not svc.teklif_kapsam_disinda_mi(u, _teklif("GUVENLIK"))
        assert svc.teklif_kapsam_disinda_mi(u, _teklif(None))

    def test_kendi_musterileri_canli_kural(self):
        u = _kullanici("KENDI_MUSTERILERI", "SATIS", uid=7)
        assert not svc.teklif_kapsam_disinda_mi(u, _teklif(owner_id=7))
        assert svc.teklif_kapsam_disinda_mi(u, _teklif(owner_id=8))

    @pytest.mark.parametrize(
        ("rol", "birimler", "birimli", "beklenen"),
        [
            ("ADMIN", (), "GUVENLIK", True),
            ("ADMIN", (), None, True),
            ("SATIS_MUDURU", (), "GUVENLIK", False),
            ("SATIS_MUDURU", (), None, True),
            ("SERVIS_YONETICI", (), "GUVENLIK", True),
            ("SERVIS_YONETICI", (), None, False),
        ],
    )
    def test_alanlar_arasi_yazma(self, rol, birimler, birimli, beklenen):
        u = _kullanici("TUMU", rol, birimler)
        assert svc.teklif_yazilabilir_mi(u, _teklif(birimli)) is beklenen


class TestEtkinDurum:
    def test_suresi_dolan_hesaplanir(self):
        t = _teklif("GUVENLIK", status="GONDERILDI")
        v = QuoteVersion(valid_until=date(2026, 1, 1))
        assert svc.etkin_durum(t, v, date(2026, 1, 2)) == "SURESI_DOLDU"
        assert svc.etkin_durum(t, v, date(2026, 1, 1)) == "GONDERILDI"
        assert "KABUL" not in svc.sonraki_durumlar(t, v, date(2026, 1, 2))
        assert "KABUL" in svc.sonraki_durumlar(t, v, date(2026, 1, 1))

    def test_kabul_edilen_suresi_dolmaz_ve_satis_makinesiz(self):
        v = QuoteVersion(valid_until=date(2025, 1, 1))
        assert svc.etkin_durum(_teklif(status="KABUL"), v, date(2026, 1, 2)) == "KABUL"
        assert svc.sonraki_durumlar(_teklif(None, status="GONDERILDI"), v, date(2024, 1, 1)) == []

    def test_teklif_no_gosterim(self):
        t = _teklif()
        assert svc.teklif_no_gosterim(t, QuoteVersion(version_no=1)) == "TKF2026-00001"
        assert svc.teklif_no_gosterim(t, QuoteVersion(version_no=2)) == "TKF2026-00001-R1"


class TestKdvDokumu:
    def test_oran_bazinda_toplam_kalem_yuvarlamasiyla_ayni(self):
        kalemler = [
            QuoteLine(line_total=Decimal("33.33"), vat_rate=Decimal("0.20")),
            QuoteLine(line_total=Decimal("33.33"), vat_rate=Decimal("0.20")),
            QuoteLine(line_total=Decimal("10.05"), vat_rate=Decimal("0.10")),
        ]
        dokum = svc.kdv_dokumu(kalemler)
        assert [d["oran"] for d in dokum] == [Decimal("0.20"), Decimal("0.10")]
        assert dokum[0]["matrah"] == Decimal("66.66")
        # Kalem başına yuvarlama: 6.67 + 6.67 (tek seferde 13.33 olurdu).
        assert dokum[0]["kdv"] == Decimal("13.34")
        assert dokum[1]["kdv"] == Decimal("1.01")


class TestMaliyetYardimcilari:
    def test_is_gunu_hafta_sonunu_atlar(self):
        cuma = date(2026, 1, 2)
        assert cuma.weekday() == 4
        assert maliyet.is_gunu_ekle(cuma, 2) == date(2026, 1, 6)  # Salı
        assert maliyet.is_gunu_ekle(cuma, 1) == date(2026, 1, 5)  # Pazartesi

    def test_donem_araligi(self):
        assert maliyet.donem_araligi("2025-02", None, None) == (date(2025, 2, 1), date(2025, 2, 28))
        assert maliyet.donem_araligi(None, date(2025, 1, 1), date(2025, 12, 31))[1] == date(
            2025, 12, 31
        )
        for hatali in (
            ("2025-13", None, None),
            (None, None, None),
            (None, date(2025, 1, 1), date(2026, 1, 1)),
            (None, date(2025, 2, 1), date(2025, 1, 1)),
        ):
            with pytest.raises(maliyet.MaliyetGirdiHatasi):
                maliyet.donem_araligi(*hatali)

    def test_bos_aralik_hicbir_gunu_kapsamaz(self):
        kapali = ServiceLaborRate(valid_from=date(2026, 3, 1), valid_to=date(2026, 3, 1))
        acik = ServiceLaborRate(valid_from=date(2026, 3, 1), valid_to=None)
        assert not maliyet.tarife_gecerli_mi(kapali, date(2026, 3, 1))
        assert maliyet.tarife_gecerli_mi(acik, date(2026, 3, 1))
        assert not maliyet.tarife_gecerli_mi(acik, date(2026, 2, 28))

    def test_ozet_durumu_onceligi(self):
        assert maliyet._ozet_durumu("SURE_EKSIK", "MALIYET_EKSIK", "KAYIT_YOK") == "SURE_EKSIK"
        assert maliyet._ozet_durumu("TAM", "MALIYET_EKSIK", "KAYIT_YOK") == "MALIYET_EKSIK"
        assert maliyet._ozet_durumu("TAM", "YOK", "KAYIT_YOK") == "GELIR_YOK"
        assert maliyet._ozet_durumu("TAM", "YOK", "SOZLESME_KAPSAMI") == "SOZLESME_KAPSAMI"
        assert maliyet._ozet_durumu("TAM", "TAM", "ELLE") == "TAM"
