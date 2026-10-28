"""Teknik servis sözlüklerinin TEK kaynak olduğunu kilitler (plan §1.7, TS-013).

Modül belgeleri aynı kavramı farklı adlarla yazmıştı: birim kodları iki yerde
(CHECK için `models.rbac`, etiket için `permissions`), saha rolleri iki yerde,
servis türü ayarlarda ve modelde, ek sahibi türleri dört ayrı yapıda. Bu
kopyalardan biri sessizce ayrışırsa CHECK kısıtı ekranın gösterdiği bir değeri
reddeder ya da ek ucu "bilinmeyen kayıt türü" der. Ayrışma derleme anında
değil, canlıda ilk kullanımda görünürdü; bu dosya onu testte görünür kılar.
"""

import pytest

from app import permissions
from app.api import attachments as ek_api
from app.models import attachment as ek_model
from app.models import rbac, teknik_servis, user
from app.services import settings as ayar
from app.services.statemachine import MAKINELER, SERVIS_IS_EMRI
from app.services.teknik_servis import ek_kapsam, is_emirleri


def _katalog(ad: str):
    """Paralel paketin (D0-A, permissions.py) henüz eklemediği sabit → atla.

    Sabit geldiği anda test kendiliğinden zorlayıcı olur; atlama sessiz
    değil, gerekçesiyle raporda görünür.
    """
    if not hasattr(permissions, ad):
        pytest.skip(f"permissions.{ad} henüz tanımlı değil (D0-A teslimi bekleniyor)")
    return getattr(permissions, ad)


# --- Birim, saha rolü, ayrılış nedeni -------------------------------------------


def test_birim_kodlari_izin_katalogundakiyle_ayni() -> None:
    assert tuple(_katalog("BIRIMLER")) == rbac.BIRIM_KODLARI


def test_saha_rolleri_ve_ayrilis_nedenleri_ayni() -> None:
    assert tuple(_katalog("SAHA_ROLLERI")) == user.SAHA_ROLLERI
    assert tuple(_katalog("AYRILIS_NEDENLERI")) == user.AYRILIS_NEDENLERI


def test_atanabilir_saha_rolleri_saha_rollerinin_alt_kumesi() -> None:
    atanabilir = set(_katalog("ATANABILIR_SAHA_ROLLERI"))
    assert atanabilir <= set(user.SAHA_ROLLERI)
    assert "OFIS" not in atanabilir and "YOK" not in atanabilir


def test_kapsam_sabitleri_tanimli() -> None:
    kapsamlar = set(permissions.SCOPES)
    assert {"TUMU", "KENDI_MUSTERILERI"} <= kapsamlar
    if "KENDI_BIRIMI" not in kapsamlar:
        pytest.skip("Birim kapsamları henüz SCOPES'ta değil (D0-A)")
    assert {"KENDI_BIRIMI", "KENDI_ISLERI"} <= kapsamlar


# --- Servis işi sözlükleri --------------------------------------------------------


def test_durumlar_makineyle_ayni() -> None:
    assert SERVIS_IS_EMRI.durumlar == frozenset(teknik_servis.SERVIS_DURUMLARI)
    assert MAKINELER["servis_is_emri"] is SERVIS_IS_EMRI
    # KARGODA ve TEST_KONTROL bilinçli olarak YOK (KD-13).
    assert not {"KARGODA", "TEST_KONTROL"} & set(teknik_servis.SERVIS_DURUMLARI)


def test_durum_gruplari_tutarli() -> None:
    g = teknik_servis.DURUM_GRUPLARI
    tum = frozenset(teknik_servis.SERVIS_DURUMLARI)
    assert g["ACIK"] | g["KAPALI"] == tum and not g["ACIK"] & g["KAPALI"]
    assert g["COZULDU"] <= g["KAPALI"]
    assert g["SAHA"] <= g["ACIK"]
    assert g["SAYAC_ACILABILIR"] == g["ACIK"] - {"BEKLEMEDE"}
    assert SERVIS_IS_EMRI.terminaller <= g["KAPALI"]


def test_tur_kurallari_tum_turleri_kapsar() -> None:
    assert set(is_emirleri.TUR_KURALLARI) == set(teknik_servis.SERVIS_TURLERI)
    for tur, kural in is_emirleri.TUR_KURALLARI.items():
        assert kural.kategori in teknik_servis.SERVIS_KATEGORILERI, tur
        # SLA yalnız günlük serviste ölçülür (plan §1.7).
        assert kural.sla_olculur == (kural.kategori == "GUNLUK_SERVIS"), tur


def test_uc_hedefleri_gecerli_durumlar() -> None:
    tum = set(teknik_servis.SERVIS_DURUMLARI)
    for kaynak, hedefler in is_emirleri.UC_HEDEFLERI.items():
        assert hedefler <= tum, kaynak
    # TAMAMLANDI yalnız sonuç/uzaktan/atölye/bakım formu; KAPATILDI yalnız kapat.
    tamamlayan = {k for k, h in is_emirleri.UC_HEDEFLERI.items() if "TAMAMLANDI" in h}
    assert tamamlayan == {"sonuc", "uzaktan", "atolye", "bakim_formu"}
    kapatan = {k for k, h in is_emirleri.UC_HEDEFLERI.items() if "KAPATILDI" in h}
    assert kapatan == {"kapat"}


def test_zaman_faaliyetleri_iscilik_icermez_ve_mola_haric() -> None:
    assert "ISCILIK" not in teknik_servis.ZAMAN_FAALIYETLERI  # KD-24
    assert teknik_servis.KISI_SAATE_DAHIL == frozenset(teknik_servis.ZAMAN_FAALIYETLERI) - {"MOLA"}
    assert set(teknik_servis.SAHA_AKIS.values()) <= set(teknik_servis.ZAMAN_FAALIYETLERI)


def test_bekleme_nedeni_tohumu() -> None:
    kodlar = [k[0] for k in teknik_servis.VARSAYILAN_BEKLEME_NEDENLERI]
    assert len(kodlar) == len(set(kodlar))
    sla = {k[0] for k in teknik_servis.VARSAYILAN_BEKLEME_NEDENLERI if k[2]}
    assert sla == {"MUSTERI_ONAYI", "TEKLIF", "MUSTERI_ERISIMI"}


# --- Ayarlar ---------------------------------------------------------------------

_PLAN_1_9 = {
    "servis_onay_zorunlu_turler", "servis_toplu_atama_ust_sinir", "servis_ek_silme_saat",
    "servis_kapsam_son_is_gun", "servis_plan_varsayilan_sure_dk", "servis_bolge_oneri_gun",
    "servis_plan_bekleyen_uyari_gun", "hesap_dogrulanmamis_uyari_gun",
    "servis_varsayilan_garanti_ay", "servis_garanti_uyari_gun", "servis_kpi_bakim_gecikme_ay",
    "ekipman_tekrar_ariza_gun", "ekipman_tekrar_ariza_esik", "bakim_on_acilis_gun",
    "bakim_tolerans_gun", "bakim_otomatik_uretim", "zaman_manuel_geri_gun",
    "zaman_manuel_gerekce_esik_dk", "zaman_geri_alma_dk", "zaman_asgari_bolum_dk",
    "zaman_uzun_sayac_uyari_saat", "zaman_gecikmeli_manuel_saat", "zaman_rapor_varsayilan_gun",
    "servis_sla_yururluk_at", "servis_sla_risk_yuzde", "servis_tekrar_ariza_gun",
    "servis_uyari_uretimi_acik", "servis_uyari_saklama_gun", "servis_eposta_acik",
    "servis_eposta_deneme", "servis_gunluk_ozet_saati", "atolye_tekrar_gelis_gun",
    "atolye_teslim_alinmayan_uyari_gun", "kiralama_kontrol_uyari_gun", "teklif_oz_onay_yasak",
    "teklif_takip_uyari_gun", "teklif_sunulacak_uyari_is_gunu",
    "egitim_gozlem_basari_esigi_yuzde", "egitim_rozet_sari_esigi_yuzde",
    "egitim_duzeltici_termin_gun", "egitim_belge_uyari_gun", "egitim_plan_uyari_gun",
    "egitim_toplu_plan_ust_sinir", "egitim_takip_pencere_gun",
}  # fmt: skip

# Dalga 1 bütünleştirmesinde onaylanan ayar talepleri (eskiden kod sabiti).
_DALGA1_EKLERI = {"bakim_sozlesme_bitis_uyari_gun"}
# Dalga 4 (D4-B): teklif gönderim hız sınırı (TS-215), ek içerik denetimi (TS-218);
# bütünleştirme: erişim gözden geçirme eşiği (TS-214), servis Excel satır sınırı.
_DALGA4_EKLERI = {
    "teklif_gonderim_dakika_limiti",
    "ek_icerik_denetimi_canli_turler",
    "erisim_girissiz_gun",
    "servis_rapor_excel_azami_satir",
}

# Faz A (TS-200, M5.1/M5.4): MESAI takvimli SLA'nın mesai penceresi.
_FAZ_A_EKLERI = {"servis_mesai_baslangic", "servis_mesai_bitis"}


def test_plan_ayar_anahtarlarinin_hepsi_var_ve_sinirli() -> None:
    beklenen = _PLAN_1_9 | _DALGA1_EKLERI | _DALGA4_EKLERI | _FAZ_A_EKLERI
    assert beklenen <= set(ayar.DEFAULTS)
    # Her yeni anahtar sınır tablosunda; tablo yalnız yeni anahtarları kapsar.
    assert set(ayar.AYAR_SINIRLARI) == beklenen


def test_varsayilanlar_kendi_sinirindan_gecer() -> None:
    for anahtar in ayar.AYAR_SINIRLARI:
        ayar.ayar_dogrula(anahtar, ayar.DEFAULTS[anahtar])


def test_yayin_bayraklari_kapali_baslar() -> None:
    """R1 devreye alma: otomatik PB, SLA ve e-posta kapalı (plan §5.1/7)."""
    assert ayar.DEFAULTS["bakim_otomatik_uretim"] is False
    assert ayar.DEFAULTS["servis_sla_yururluk_at"] is None
    assert ayar.DEFAULTS["servis_eposta_acik"] is False
    assert ayar.DEFAULTS["servis_onay_zorunlu_turler"] == ["PB"]  # KD-19
    assert set(ayar.DEFAULTS["servis_onay_zorunlu_turler"]) <= set(teknik_servis.SERVIS_TURLERI)


# --- Ek sahipleri: dört yapı -----------------------------------------------------


def test_ek_sahibi_yapilari_esit() -> None:
    """EK_SAHIPLERI, SAHIP_IZNI, _SAHIP_TABLOSU ve kapsam kayıt defteri.

    Canlı türlerin `_SAHIP_TABLOSU` eşlemesi tarihsel olarak eksik/fazla
    (varlık kontrolü opsiyonel); teknik servis türlerinde ise dördü de ZORUNLU.
    """
    sahipler = set(ek_model.EK_SAHIPLERI)
    assert sahipler == set(ek_api.SAHIP_IZNI)
    ts = sahipler & ek_kapsam.KAPSAM_ZORUNLU
    # Dalga 0/1 sahipleri + Dalga 2 kiralama (D2-S); eğitim sahipleri D2-F ile
    # eklendikçe küme büyür (KAPSAM_ZORUNLU'nun alt kümesi kalır).
    assert {
        "service_orders",
        "service_equipment",
        "maintenance_contracts",
        "addresses",
        "rentals",
        "rental_assets",
    } <= ts
    for entity in ts:
        assert ek_api._SAHIP_TABLOSU.get(entity) == entity
    # Kayıtlı kapsam fonksiyonu olan her tür gerçekten bir ek sahibi.
    assert set(ek_kapsam.SAHIP_KAPSAMLARI) <= sahipler
    assert "accounts" in ek_kapsam.SAHIP_KAPSAMLARI


def test_ek_turleri() -> None:
    turler = set(ek_model.EK_TURLERI)
    assert {
        "SERVIS_ONCESI", "SERVIS_SONRASI", "SERVIS_FORMU", "BAKIM_FORMU",
        "GOZLEM_FOTOGRAFI", "DUZELTICI_KANIT", "SERTIFIKA", "IMZA",
    } <= turler  # fmt: skip
    assert "MUSTERI_IMZASI" not in turler  # canlı IMZA kullanılır
    assert len(ek_model.EK_TURLERI) == len(turler)
    assert all(len(t) <= 30 for t in turler)  # attachments.kind String(30)
