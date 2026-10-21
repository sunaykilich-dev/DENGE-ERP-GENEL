"""Seri numarası, ünvan anahtarı ve il adı normalizasyonu (TS-011).

Üç modülün (servis işi, kütük, atölye) seri tanımı üç ayrı biçimdeydi
(E03-D01): biri iç boşluğu teke indiriyor, biri Türkçe büyük harf yapıyor,
biri yalnız kırpıyordu. Türkçe klavyede küçük yazılan "i" Türkçe büyük harfte
"İ" olur ve sahadaki etiketteki ASCII "I" ile hiç eşleşmezdi: aynı cihazın
geçmişi iki ayrı cihaz gibi görünüyordu. Bu dosya TEK fonksiyonun sözleşmesini
kilitler.
"""

import pytest

from app.services.normalize import (
    IL_ADLARI,
    il_normalize,
    normalize_seri,
    tr_normkey,
    unvan_anahtari,
)


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        (" abc-i01 ", "ABC-I01"),
        ("SC  5030", "SC 5030"),
        (" 00ab  12/3 ", "00AB 12/3"),
        ("ıiİI", "IIII"),
        ("seri\tno\n7", "SERI NO 7"),
        ("çöşüğ-1", "COSUG-1"),
        ("", ""),
        (None, ""),
        (12345, "12345"),
    ],
)
def test_normalize_seri_kurallari(ham, beklenen) -> None:
    assert normalize_seri(ham) == beklenen


def test_bastaki_sifir_ve_isaretler_korunur() -> None:
    """`00123` ile `123`, `AB-1` ile `AB1` FARKLI cihazlardır."""
    assert normalize_seri("00123") != normalize_seri("123")
    assert normalize_seri("AB-1") != normalize_seri("AB1")
    assert normalize_seri("AB.1/2") == "AB.1/2"


def test_normalize_seri_idempotent() -> None:
    for ham in (" abc-i01 ", "SC  5030", "çöşüğ", "x y  z"):
        bir = normalize_seri(ham)
        assert normalize_seri(bir) == bir


def test_unvan_anahtari_ekleri_ve_noktalamayi_atar() -> None:
    a = unvan_anahtari("G4S ELEKTRONİK SİSTEMLERİ A.Ş.")
    b = unvan_anahtari("G4S Elektronik Sistemleri Anonim Şirketi")
    assert a == b == "g4s elektronik sistemleri"
    assert unvan_anahtari("ABC İnşaat San. ve Tic. Ltd. Şti.") == "abc insaat"
    assert unvan_anahtari("Akyaka  AVM") == unvan_anahtari("AKYAKA AVM") == "akyaka avm"


def test_unvan_anahtari_ad_icindeki_kelimelere_dokunmaz() -> None:
    # "AS" yalnız SONDA ek sayılır; "Ticaretgen" bir kelimedir, "tic" değil.
    assert unvan_anahtari("AS Elektrik") == "as elektrik"
    assert unvan_anahtari("Ticaretgen AŞ") == "ticaretgen"


def test_unvan_anahtari_yalniz_ekse_bos_donmez() -> None:
    assert unvan_anahtari("A.Ş.") != ""
    assert unvan_anahtari(None) == ""


def test_tr_normkey_degismedi() -> None:
    """`title_key` ve mobilite araması `tr_normkey`'e bağlı: davranışı aynen kalır."""
    assert tr_normkey("G4S A.Ş.") == "g4s a.s."
    assert tr_normkey("İZMİR OTOFOM") == "izmir otofom"


def test_il_listesi_81_il_ve_tekil() -> None:
    assert len(IL_ADLARI) == 81
    assert len({tr_normkey(i) for i in IL_ADLARI}) == 81


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        ("ISTANBUL", "İstanbul"),
        ("istanbul ", "İstanbul"),
        ("İSTANBUL", "İstanbul"),
        ("34", "İstanbul"),
        ("06", "Ankara"),
        ("81", "Düzce"),
        ("igdir", "Iğdır"),
        ("K.Maraş", "Kahramanmaraş"),
        ("afyon", "Afyonkarahisar"),
        ("ŞANLIURFA", "Şanlıurfa"),
    ],
)
def test_il_normalize_taninan(ham, beklenen) -> None:
    assert il_normalize(ham) == beklenen


@pytest.mark.parametrize("ham", ["", None, "Kadıköy", "82", "0", "Atlantis"])
def test_il_normalize_taninmayan_none(ham) -> None:
    assert il_normalize(ham) is None
