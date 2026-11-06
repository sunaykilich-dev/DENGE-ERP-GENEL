"""Normalizasyon — tuzakların tamamı gerçek dosyalardan alındı."""

import pytest

from app.services.normalize import (
    clean_cell,
    iccid_luhn_ok,
    normalize_iban,
    normalize_iccid,
    normalize_msisdn,
    normalize_plate,
    normalize_tax_no,
    parse_decimal,
    tr_normkey,
    validate_imei,
)


class TestTurkceAnahtar:
    def test_buyuk_i_dogru_katlanir(self):
        """`"Cihaz Imei No".lower()` Türkçe'de 'ımei' verir ve /imei/ tutmaz.
        Bu gerçek hata mevcut uygulamada IMEI sütununun hiç okunmamasına
        yol açmıştı."""
        assert tr_normkey("Cihaz Imei No") == "cihaz imei no"
        assert "imei" in tr_normkey("Cihaz Imei No")
        assert "imei" in tr_normkey("CİHAZ İMEİ NO")

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("İZMİR OTOFOM", "izmir otofom"),
            ("ANTALYA RAMAZAN ÇULLU", "ANTALYA RAMAZAN CULLU"),
            ("GÜREK OTO- ŞENOL GÜREK", "gurek oto- senol gurek"),
            ("L300 BLK.", "l300 blk."),
        ],
    )
    def test_ayni_kayda_duser(self, a, b):
        assert tr_normkey(a) == tr_normkey(b)

    def test_bosluklar_sadelestirilir(self):
        assert tr_normkey("  ENS   ELEKTRONİK  ") == "ens elektronik"


class TestDolguIsaretleri:
    @pytest.mark.parametrize(
        "girdi",
        ["…...........", "......", "*****", "-", "?", "??", "İSTENMEDİ", "YOK", "", "  "],
    )
    def test_dolgu_bosa_iner(self, girdi):
        assert clean_cell(girdi) == ""

    def test_gercek_deger_korunur(self):
        assert clean_cell("  BB06882PAG00032 ") == "BB06882PAG00032"
        assert clean_cell(861100063834630) == "861100063834630"


class TestImei:
    def test_gecerli(self):
        assert validate_imei("861100063834630") == "861100063834630"
        assert validate_imei(861100063834630) == "861100063834630"

    def test_bilimsel_gosterim_onarilmaz_hata_verir(self):
        """Excel'in bozduğu değer gerçek veri kaybıdır; sessizce 'düzeltmek'
        yanlış IMEI üretir. Net hata + kaynak sütunu metin yapma talimatı."""
        with pytest.raises(ValueError, match="metin yapın"):
            validate_imei("8.63071E+14")

    def test_eksik_hane(self):
        with pytest.raises(ValueError, match="15 hane"):
            validate_imei("86110006383")

    def test_imeisv_17_hane_reddedilir(self):
        with pytest.raises(ValueError, match="15 hane"):
            validate_imei("35320135953390519")


class TestPlaka:
    @pytest.mark.parametrize(
        ("girdi", "beklenen"),
        [
            ("34 FRR 233", "34FRR233"),
            ("34frr233", "34FRR233"),
            ("06 EZM 301", "06EZM301"),
            ("27-S-4948", "27S4948"),
            ("34 GCF 742", "34GCF742"),
        ],
    )
    def test_gecerli(self, girdi, beklenen):
        assert normalize_plate(girdi) == beklenen

    @pytest.mark.parametrize("girdi", ["1480728", "99ABC123", "ABC123"])
    def test_gecersiz(self, girdi):
        with pytest.raises(ValueError):
            normalize_plate(girdi)


class TestMaliAlanlar:
    def test_vkn_ve_tckn(self):
        assert normalize_tax_no("1234567890") == "1234567890"
        assert normalize_tax_no("123 456 789 01") == "12345678901"

    def test_gecersiz_uzunluk(self):
        with pytest.raises(ValueError, match="10, TCKN 11"):
            normalize_tax_no("12345")

    def test_iban_dogrulanir(self):
        assert normalize_iban("TR33 0006 1005 1978 6457 8413 26") == "TR330006100519786457841326"

    def test_iban_saglamasi_tutmazsa_reddedilir(self):
        """Hak ediş ödeme listesi bu alandan üretilir; biçim kontrolü yetmez."""
        with pytest.raises(ValueError, match="sağlaması"):
            normalize_iban("TR330006100519786457841327")

    def test_tr_ve_en_sayi_bicimi(self):
        assert parse_decimal("1.250,50") == 1250.50
        assert parse_decimal("1,250.50") == 1250.50
        assert parse_decimal("350") == 350.0
        assert parse_decimal(2750) == 2750.0


class TestHat:
    def test_msisdn_e164(self):
        assert normalize_msisdn("0501 811 65 20") == "+905018116520"
        assert normalize_msisdn("5018116520") == "+905018116520"
        assert normalize_msisdn("905018116520") == "+905018116520"

    def test_iccid_19_ve_20_hane_kabul_edilir(self):
        assert normalize_iccid("8990011234567890123") == "8990011234567890123"
        assert normalize_iccid("8990 0112 3456 7890 1231") == "89900112345678901231"

    def test_iccid_hane_sayisi_zorlanir(self):
        with pytest.raises(ValueError, match="19 veya 20"):
            normalize_iccid("89900112345")

    def test_luhn_saglamasi_uyari_seviyesinde(self):
        """Operatörler 19 haneli (sağlamasız) ICCID de basıyor; katı davranmak
        gerçek hattı sisteme sokmamak olurdu. Sağlama ayrı sorulur."""
        assert iccid_luhn_ok("89900112345678901231") is True
        assert iccid_luhn_ok("89900112345678901232") is False
        # 19 hanelide sağlama hanesi yok → şüphe üretilmez
        assert iccid_luhn_ok("8990011234567890123") is True

    def test_rakam_olmayan_degerde_hata_atmaz(self):
        """Gerileme testi: göç ICCID bilinmediğinde `MSISDN:+90…` yer tutucusu
        yazıyor ve bu dizge TAM 20 KARAKTER. Sağlama fonksiyonu `int()` ile
        patlayınca tek bir böyle satır bütün hat listesini 500 yapıyordu.
        Sağlama sorusunun cevabı "hayır"dır, istisna değil."""
        assert iccid_luhn_ok("MSISDN:+905014693254") is False
        assert iccid_luhn_ok("ABCDEFGHIJKLMNOPQRST") is False
