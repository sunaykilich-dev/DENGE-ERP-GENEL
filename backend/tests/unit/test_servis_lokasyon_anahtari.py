"""Lokasyon anahtarı: havuz, toplu plan, ziyaret ve raporun TEK gruplama kuralı.

E02 `tr_normkey`, E12 `unvan_anahtari`, E09 başka bir bileşim kullanınca aynı
iş üç ekranda üç ayrı gruba düşüyordu (E14 kontrol B11). Kural tek fonksiyonda
ve burada kilitli: adresi olan kayıt adresle, adresi olmayan müşteri + ham
lokasyon metniyle gruplanır; hiçbir şeyi olmayan kayıt GRUPLANMAZ.
"""

from types import SimpleNamespace

from app.services.teknik_servis.ana_veri import lokasyon_anahtari


def _is(**kw):
    taban = {
        "birim": "GUVENLIK",
        "address_id": None,
        "customer_id": None,
        "location_raw": None,
        "customer_name_raw": None,
    }
    taban.update(kw)
    return SimpleNamespace(**taban)


def test_adresli_kayit_adresle_gruplanir():
    a = _is(address_id=7, customer_id=1, location_raw="AKYAKA AVM")
    b = _is(address_id=7, customer_id=1, location_raw="AKYAKA PARK AVM")
    assert lokasyon_anahtari(a) == lokasyon_anahtari(b) == ("GUVENLIK", "L", 7)


def test_bosluk_ve_buyuk_kucuk_harf_ayni_anahtar():
    a = _is(customer_id=3, location_raw="Akyaka  AVM")
    b = _is(customer_id=3, location_raw="AKYAKA AVM")
    assert lokasyon_anahtari(a) == lokasyon_anahtari(b)
    assert lokasyon_anahtari(a)[:3] == ("GUVENLIK", "M", 3)


def test_farkli_musteri_ayni_metin_ayri_grup():
    a = _is(customer_id=3, location_raw="Merkez Depo")
    b = _is(customer_id=4, location_raw="Merkez Depo")
    assert lokasyon_anahtari(a) != lokasyon_anahtari(b)


def test_adressiz_ve_metinsiz_kayit_gruplanmaz():
    assert lokasyon_anahtari(_is(customer_id=3)) is None
    assert lokasyon_anahtari(_is(customer_id=3, location_raw="   ")) is None
    assert lokasyon_anahtari(_is()) is None


def test_musterisi_eslesmemis_kayit_ham_metinle():
    a = _is(customer_name_raw="G4S Güvenlik", location_raw="Akyaka  AVM")
    b = _is(customer_name_raw="G4S GÜVENLİK", location_raw="AKYAKA AVM")
    assert lokasyon_anahtari(a) == lokasyon_anahtari(b)
    assert lokasyon_anahtari(a)[1] == "E"


def test_birim_on_eki_ayirir():
    a = _is(address_id=7)
    b = _is(address_id=7, birim="HABERLESME")
    assert lokasyon_anahtari(a) != lokasyon_anahtari(b)


def test_sozluk_ve_diger_alan_adlari():
    """Sözleşme `account_id` + `site_name_raw`, kiralama `lokasyon_metni` taşır."""
    sozlesme = {"birim": "GUVENLIK", "account_id": 5, "site_name_raw": "Akyaka AVM"}
    is_kaydi = _is(customer_id=5, location_raw="AKYAKA  AVM")
    assert lokasyon_anahtari(sozlesme) == lokasyon_anahtari(is_kaydi)
