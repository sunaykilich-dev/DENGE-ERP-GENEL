"""Operasyonel ayarlar: DB `settings` tablosu + varsayılanlar.

Brief §4.7 madde 6'nın şartı budur: "tüm oranlar sabit kod değil, ayarlardan
değiştirilebilir parametre olmalı". Vergi oranları, eşikler ve entegrasyon
kimlik bilgileri koda gömülmez; buradaki varsayılanlarla başlar, admin
arayüzünden değiştirilir. Arka plan işleri her turda yeniden okur — değişiklik
için süreç yeniden başlatmak gerekmez.

DİKKAT — vergi oranları: aşağıdaki değerler başlangıç varsayılanıdır ve
CANLIYA ÇIKMADAN ÖNCE MALİ MÜŞAVİRE TEYİT ETTİRİLMELİDİR. Özellikle gider
pusulası stopajı işin niteliğine göre değişir. Hak ediş satırı oluşurken
kullanılan oran satırın içine dondurulur (plan §3.3/2), böylece oran sonradan
değişse bile geçmiş dökümler değişmez.
"""

import ipaddress
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto
from app.models import Setting
from app.models.teknik_servis import SERVIS_TURLERI

# DB'de düz metin saklanmaması gereken kimlik bilgileri — set_many şifreler,
# get/get_all çözer, API katmanı arayüze maskeler.
SENSITIVE_KEYS = {
    "platform_api_key",
    "operator_api_key",
    "smtp_password",
    "webhook_signing_key",
}

DEFAULTS: dict[str, Any] = {
    # --- Vergi ve kesinti (§4.7 madde 6) — mali müşavir teyidi şart ---------
    "kdv_oran_varsayilan": 0.20,
    "stopaj_smm_oran": 0.20,  # serbest meslek makbuzu gelir vergisi stopajı
    "damga_vergisi_oran": 0.00759,  # binde 7,59
    "stopaj_gider_pusulasi_oran": 0.10,  # işin niteliğine göre değişir — TEYİT ET
    # --- Satış / teklif ----------------------------------------------------
    # İskonto yetkisi (KARARLAR 2026-11-09 S1.1): rol koduna göre üst limit
    # (yüzde). "DIGER" = tabloda olmayan roller; eski tek genel eşiğin
    # (`iskonto_onay_esigi_yuzde`, migration fcsatis00001 ile kaldırıldı)
    # değeri buraya taşındı. Kişi limiti (`users.iskonto_limiti_yuzde`) rol
    # limitinin yerine geçer. Limitin üstü satış müdürü onayına, satış müdürü
    # limitinin üstü Genel Müdür/ADMIN onayına düşer (`services/iskonto.py`).
    "iskonto_rol_limitleri": {"SATIS": 10, "SATIS_DESTEK": 5, "SATIS_MUDURU": 25, "DIGER": 10},
    "teklif_varsayilan_gecerlilik_gun": 15,
    # Standart ticari şartlar metni — henüz hazır değil (plan §8).
    "teklif_ticari_sartlar": "",
    # --- Şirket künyesi (plan §8 madde 5) ---------------------------------
    # Teklif ve hak ediş PDF'lerinin başlığı. Eksikse belge yine üretilir ama
    # alanlar makul varsayılanla basılır — sessizce yanlış bilgi basmaktansa
    # bilinen adresi basmak doğrudur; resmî unvan/VKN girilince değişir.
    "firma_unvan": "",
    "firma_adres": "",
    "firma_telefon": "",
    "firma_eposta": "",
    "firma_vkn": "",
    "firma_vergi_dairesi": "",
    "firma_mersis": "",
    "firma_kep": "",
    # --- Cihaz / stok ------------------------------------------------------
    "varsayilan_garanti_ay": 24,
    "bayi_stok_yaslanma_gun": 90,  # bayide bekleyen stok uyarısı
    # --- Hat ---------------------------------------------------------------
    "kota_uyari_yuzde_1": 80,
    "kota_uyari_yuzde_2": 100,
    "atil_hat_gun": 30,  # bu kadar gündür veri yok → atıl
    "hat_taahhut_uyari_gun": 60,  # taahhüt bitişine bu kadar kala uyar
    # --- Abonelik / tahsilat -----------------------------------------------
    "abonelik_yenileme_hatirlatma_gun": 30,
    "odeme_gecikme_uyari_gun": 30,  # "X gündür ödemedi" tetikleyicisi
    # --- KVKK ---------------------------------------------------------------
    # Hareketsiz müşteri kaydının saklama süresi (yıl). Süre dolunca kayıt
    # OTOMATİK silinmez; anonimleştirme listesine düşer, karar insana ait.
    "kvkk_saklama_yili": 10,
    # --- Muhasebe dışa aktarım ---------------------------------------------
    "muhasebe_sablonu": "logo",  # kolon düzeni şablonu
    # --- Takip platformu entegrasyonu (plan §3.7 kısıtlı mod) --------------
    "platform_base_url": "",
    "platform_api_key": "",
    # fleet-platform'da vehicles.device_id UNIQUE olduğu sürece False kalır:
    # ERP yalnız birincil takip cihazını platforma bağlar, kameraları bağlamaz.
    # Platform vehicle_devices tablosunu ekleyince True yapılır ve bekleyen
    # outbox kayıtları otomatik oynatılır.
    "platform_coklu_cihaz_destegi": False,
    "webhook_signing_key": "",
    # --- Operatör (Türk Telekom %98,4 — tek adaptör) -----------------------
    "operator_adaptor": "mock",  # mock | turk_telekom
    "operator_api_key": "",
    # --- Bildirim ----------------------------------------------------------
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    # =======================================================================
    # TEKNİK SERVİS (plan §1.9, KD-16) — tüm anahtarlar Dalga 0'da TEK seferde.
    # Modüller burayı sonradan düzenlemez; yeni anahtar şema paketine taleptir.
    # =======================================================================
    # --- Teknik servis --------------------------------------------------------
    # ALINAMADI+neden de onay kaydı sayılır; saha bloke olmaz (KD-19).
    "servis_onay_zorunlu_turler": ["PB"],
    # KARARLAR 2026-11-05 §9: açıkken iş kapanışı iki aşamalı — önce ekip
    # liderinin kalite onayı, sonra `servis.son_onay` (müdür) kapatır.
    "servis_kapanis_onay_zinciri": False,
    "servis_toplu_atama_ust_sinir": 150,  # toplu atama/plan; 151 → 422
    "servis_ek_silme_saat": 24,
    "servis_kapsam_son_is_gun": 30,
    "servis_plan_varsayilan_sure_dk": 60,
    "servis_bolge_oneri_gun": 3,
    "servis_plan_bekleyen_uyari_gun": 3,
    "hesap_dogrulanmamis_uyari_gun": 7,
    # Dalga 1 bütünleştirme ayar talebi (D1-F; önceden kod sabitiydi).
    "bakim_sozlesme_bitis_uyari_gun": 60,
    # --- Ekipman / bakım ------------------------------------------------------
    "servis_varsayilan_garanti_ay": 24,
    "servis_garanti_uyari_gun": 30,
    "servis_kpi_bakim_gecikme_ay": 12,
    "ekipman_tekrar_ariza_gun": 90,
    "ekipman_tekrar_ariza_esik": 2,
    "bakim_on_acilis_gun": 30,
    "bakim_tolerans_gun": 30,
    # Sözleşme–ekipman eşleştirmesi %100 olunca açılır (TS-063, KD-21).
    "bakim_otomatik_uretim": False,
    # --- Saha / zaman ---------------------------------------------------------
    "zaman_manuel_geri_gun": 2,
    "zaman_manuel_gerekce_esik_dk": 30,
    "zaman_geri_alma_dk": 5,
    "zaman_asgari_bolum_dk": 1,
    "zaman_uzun_sayac_uyari_saat": 10,
    "zaman_gecikmeli_manuel_saat": 24,
    "zaman_rapor_varsayilan_gun": 31,
    # --- SLA / operasyon ------------------------------------------------------
    # ISO zaman; boşken SLA damgalanmaz (göç sonrası uyarı fırtınası önlemi, KD-22).
    "servis_sla_yururluk_at": None,
    "servis_sla_risk_yuzde": 80,
    "servis_tekrar_ariza_gun": 30,
    "servis_uyari_uretimi_acik": True,
    "servis_uyari_saklama_gun": 90,
    "servis_eposta_acik": False,
    "servis_eposta_deneme": 3,
    "servis_gunluk_ozet_saati": "07:30",
    # Faz A (TS-200, M5.1/M5.4): MESAI takvimli SLA'nın mesai penceresi (yerel
    # saat, hafta içi; tatiller fark etmez). Bitiş başlangıçtan sonra olmalı.
    "servis_mesai_baslangic": "08:30",
    "servis_mesai_bitis": "18:00",
    # Operasyon Merkezi (2026-11-18): tayinsiz iş bu kadar MESAİ dakikası
    # bekleyince "gecikti" olur ve TAYIN_GECIKTI bildirimi/e-postası üretilir.
    "servis_tayin_suresi_kritik_dk": 10,
    "servis_tayin_suresi_dk": 30,
    # --- Atölye / kiralama ----------------------------------------------------
    "atolye_tekrar_gelis_gun": 90,
    "atolye_teslim_alinmayan_uyari_gun": 30,
    "kiralama_kontrol_uyari_gun": 7,
    # --- Teklif ---------------------------------------------------------------
    "teklif_oz_onay_yasak": True,
    "teklif_takip_uyari_gun": 3,
    "teklif_sunulacak_uyari_is_gunu": 2,
    # Kullanıcı başına dakikada en çok e-posta teklif gönderimi (TS-215, E07-25).
    "teklif_gonderim_dakika_limiti": 10,
    # --- Ekler (TS-218) -------------------------------------------------------
    # Canlı türlerde (hesap, cihaz, ürün, RMA...) içerik/magic-byte denetimi.
    # Kapalı = KURU KOŞU: uyuşmazlık reddedilmez, denetim satırı yazılır;
    # `GET /api/ekler/icerik-denetimi` raporu temizse açılır.
    "ek_icerik_denetimi_canli_turler": False,
    # --- Erişim gözden geçirme / raporlar (TS-214, E12) -------------------------
    # "Uzun süredir girişsiz" eşiği (gün); güvenlik sabiti değil (E13-16).
    "erisim_girissiz_gun": 60,
    # Servis/bakım Excel'lerinin satır üst sınırı. Aralık sınırı (24 ay) kod
    # sabitidir (`panel.RAPOR_AZAMI_AY`, E12-08): eşzamanlı süzgeç doğrulaması
    # ayar okuyamaz ve sınırın gevşetilmesi sorgu maliyetini büyütür.
    "servis_rapor_excel_azami_satir": 50_000,
    # --- Erişim yeri (G3.8, KARARLAR 2026-10-28 §7 Faz A/8) -------------------
    # Ofis ağı CIDR listesi (ör. ["10.10.0.0/16", "88.255.1.20/32"]). `yalniz_ofis`
    # işaretli roller (varsayılan muhasebe) yalnız bu ağlardan girer ve istek
    # atar. BOŞ = kısıt yok (kurulum günü kimse kilitlenmesin). İstemci IP'si
    # uvicorn'un `--proxy-headers --forwarded-allow-ips` ayarıyla çözülür;
    # uygulama X-Forwarded-For'a kendisi bakmaz (güvenilmeyen başlık).
    "ofis_ag_listesi": [],
    # --- Eğitim ---------------------------------------------------------------
    "egitim_gozlem_basari_esigi_yuzde": 85,
    "egitim_rozet_sari_esigi_yuzde": 65,
    "egitim_duzeltici_termin_gun": 14,
    "egitim_belge_uyari_gun": 30,
    "egitim_plan_uyari_gun": 7,
    "egitim_toplu_plan_ust_sinir": 300,
    "egitim_takip_pencere_gun": 7,
}

# Admin arayüzünden düzenlenebilir anahtarların beyaz listesi = DEFAULTS anahtarları.

# --- Değer doğrulaması (yalnız teknik servis anahtarları) -----------------------
#
# `set_many` canlıda değer DOĞRULAMIYOR: arayüzden "abc" yazılan bir eşik
# sessizce kaydediliyor ve onu okuyan kod ilk karşılaştırmada patlıyordu.
# Teknik servis anahtarları için sınır tablosu eklendi; mevcut anahtarların
# davranışı DEĞİŞMEZ (KD-16). Tip kodları:
#   "tam"   → tam sayı, [alt, ust] kapalı aralık (bool kabul edilmez)
#   "bool"  → True/False
#   "liste" → metin listesi; `alt` izinli değerler kümesi (None: serbest)
#   "saat"  → "SS:DD" metni
#   "zaman" → ISO 8601 saat dilimli zaman ya da None/boş (kapalı)
#   "rol_limitleri" → {rol kodu: yüzde}; değer [alt, ust], kod büyük harf
#                  (DIGER = tabloda olmayan roller); kanonik: sayı, 2 hane
#   "cidr_liste" → IPv4/IPv6 ağ listesi ("10.0.0.0/8", tek adres "1.2.3.4");
#                  kanonik biçime çevrilir, tekrarlar atılır
# Süre sınırları (15–1440 dk plan, 18 saat zaman bölümü, 62 gün takvim)
# ayar değil kod sabitidir; burada yer almaz.
AYAR_SINIRLARI: dict[str, tuple[str, Any, Any]] = {
    # İzinli değerler servis türü sözlüğünün KENDİSİ (kopya değil).
    "servis_onay_zorunlu_turler": ("liste", frozenset(SERVIS_TURLERI), None),
    "servis_kapanis_onay_zinciri": ("bool", None, None),
    "servis_toplu_atama_ust_sinir": ("tam", 1, 1000),
    "servis_ek_silme_saat": ("tam", 0, 720),
    "servis_kapsam_son_is_gun": ("tam", 1, 365),
    "servis_plan_varsayilan_sure_dk": ("tam", 15, 1440),
    "servis_bolge_oneri_gun": ("tam", 0, 30),
    "servis_plan_bekleyen_uyari_gun": ("tam", 1, 90),
    "hesap_dogrulanmamis_uyari_gun": ("tam", 1, 365),
    "bakim_sozlesme_bitis_uyari_gun": ("tam", 1, 365),
    "servis_varsayilan_garanti_ay": ("tam", 0, 120),
    "servis_garanti_uyari_gun": ("tam", 1, 365),
    "servis_kpi_bakim_gecikme_ay": ("tam", 1, 60),
    "ekipman_tekrar_ariza_gun": ("tam", 1, 730),
    "ekipman_tekrar_ariza_esik": ("tam", 2, 50),
    "bakim_on_acilis_gun": ("tam", 0, 180),
    "bakim_tolerans_gun": ("tam", 0, 180),
    "bakim_otomatik_uretim": ("bool", None, None),
    "zaman_manuel_geri_gun": ("tam", 0, 31),
    "zaman_manuel_gerekce_esik_dk": ("tam", 1, 1440),
    "zaman_geri_alma_dk": ("tam", 0, 60),
    "zaman_asgari_bolum_dk": ("tam", 1, 60),
    "zaman_uzun_sayac_uyari_saat": ("tam", 1, 24),
    "zaman_gecikmeli_manuel_saat": ("tam", 1, 720),
    "zaman_rapor_varsayilan_gun": ("tam", 1, 366),
    "servis_sla_yururluk_at": ("zaman", None, None),
    "servis_sla_risk_yuzde": ("tam", 1, 99),
    "servis_tekrar_ariza_gun": ("tam", 1, 365),
    "servis_uyari_uretimi_acik": ("bool", None, None),
    "servis_uyari_saklama_gun": ("tam", 7, 3650),
    "servis_eposta_acik": ("bool", None, None),
    "servis_eposta_deneme": ("tam", 1, 10),
    "servis_gunluk_ozet_saati": ("saat", None, None),
    "servis_mesai_baslangic": ("saat", None, None),
    "servis_mesai_bitis": ("saat", None, None),
    "servis_tayin_suresi_kritik_dk": ("tam", 1, 480),
    "servis_tayin_suresi_dk": ("tam", 1, 480),
    "atolye_tekrar_gelis_gun": ("tam", 1, 730),
    "atolye_teslim_alinmayan_uyari_gun": ("tam", 1, 365),
    "kiralama_kontrol_uyari_gun": ("tam", 1, 365),
    "teklif_oz_onay_yasak": ("bool", None, None),
    "teklif_takip_uyari_gun": ("tam", 1, 90),
    "teklif_sunulacak_uyari_is_gunu": ("tam", 1, 30),
    "teklif_gonderim_dakika_limiti": ("tam", 1, 100),
    "iskonto_rol_limitleri": ("rol_limitleri", 0, 100),
    "ek_icerik_denetimi_canli_turler": ("bool", None, None),
    "erisim_girissiz_gun": ("tam", 7, 365),
    "servis_rapor_excel_azami_satir": ("tam", 1_000, 100_000),
    "ofis_ag_listesi": ("cidr_liste", None, None),
    "egitim_gozlem_basari_esigi_yuzde": ("tam", 1, 100),
    "egitim_rozet_sari_esigi_yuzde": ("tam", 1, 100),
    "egitim_duzeltici_termin_gun": ("tam", 1, 365),
    "egitim_belge_uyari_gun": ("tam", 1, 365),
    "egitim_plan_uyari_gun": ("tam", 1, 90),
    "egitim_toplu_plan_ust_sinir": ("tam", 1, 2000),
    "egitim_takip_pencere_gun": ("tam", 1, 90),
}


class AyarHatasi(KeyError):
    """Ayar değeri sınır dışı ya da tipi yanlış.

    `KeyError`'dan türer çünkü parametre ucu (`api/settings_api.py`)
    `set_many`'nin `KeyError`'ını zaten 400'e çeviriyor; ayrı sınıf o dosyaya
    dokunmadan doğru yanıt kodunu verir. `str()` mesajı tırnaksız döner
    (KeyError'ın varsayılanı anahtarı tırnak içinde yazardı).
    """

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


_SAAT_KALIBI = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_ROL_KALIBI = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")


def ayar_dogrula(key: str, value: Any) -> Any:
    """`AYAR_SINIRLARI`'ndaki anahtarın değerini doğrular, kanonik hâlini döner.

    Sınır tablosunda olmayan anahtar olduğu gibi döner (eski davranış).
    """
    sinir = AYAR_SINIRLARI.get(key)
    if sinir is None:
        return value
    tip, alt, ust = sinir
    if tip == "tam":
        if isinstance(value, bool) or not isinstance(value, int):
            raise AyarHatasi(f"{key}: tam sayı olmalı")
        if not alt <= value <= ust:
            raise AyarHatasi(f"{key}: {alt} ile {ust} arasında olmalı")
        return value
    if tip == "bool":
        if not isinstance(value, bool):
            raise AyarHatasi(f"{key}: evet/hayır (true/false) olmalı")
        return value
    if tip == "liste":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise AyarHatasi(f"{key}: metin listesi olmalı")
        if alt is not None:
            yabanci = sorted(set(value) - set(alt))
            if yabanci:
                raise AyarHatasi(f"{key}: bilinmeyen değer(ler): {', '.join(yabanci)}")
        return list(dict.fromkeys(value))
    if tip == "saat":
        if not isinstance(value, str) or not _SAAT_KALIBI.match(value):
            raise AyarHatasi(f"{key}: SS:DD biçiminde olmalı (ör. 07:30)")
        return value
    if tip == "zaman":
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise AyarHatasi(f"{key}: ISO 8601 zaman olmalı")
        try:
            an = datetime.fromisoformat(value)
        except ValueError as exc:
            raise AyarHatasi(
                f"{key}: ISO 8601 zaman olmalı (ör. 2026-11-01T00:00:00+03:00)"
            ) from exc
        if an.tzinfo is None:
            # Saat dilimsiz an hangi ana denk geldiği belirsiz: SLA yürürlüğü
            # 3 saat kayardı.
            raise AyarHatasi(f"{key}: saat dilimi belirtilmeli (ör. +03:00)")
        return an.isoformat()
    if tip == "rol_limitleri":
        if not isinstance(value, dict) or not value:
            raise AyarHatasi(f"{key}: rol koduna göre yüzde tablosu olmalı")
        tablo: dict[str, float] = {}
        for rol, oran in value.items():
            if not isinstance(rol, str) or not _ROL_KALIBI.match(rol):
                raise AyarHatasi(f"{key}: geçersiz rol kodu '{rol}'")
            if isinstance(oran, bool) or not isinstance(oran, int | float):
                raise AyarHatasi(f"{key}: {rol} için yüzde sayı olmalı")
            if not alt <= oran <= ust:
                raise AyarHatasi(f"{key}: {rol} limiti {alt} ile {ust} arasında olmalı")
            tablo[rol] = round(float(oran), 2)
        return tablo
    if tip == "cidr_liste":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise AyarHatasi(f"{key}: ağ (CIDR) listesi olmalı")
        aglar: list[str] = []
        for v in value:
            try:
                aglar.append(str(ipaddress.ip_network(v.strip(), strict=False)))
            except ValueError as exc:
                raise AyarHatasi(f"{key}: geçersiz ağ '{v}' (ör. 10.10.0.0/16)") from exc
        return list(dict.fromkeys(aglar))
    raise AyarHatasi(f"{key}: tanımsız ayar tipi {tip}")  # pragma: no cover - tablo hatası


def _decode(key: str, value: Any) -> Any:
    return crypto.decrypt(value) if key in SENSITIVE_KEYS and isinstance(value, str) else value


async def get_all(db: AsyncSession) -> dict[str, Any]:
    """Gerçek (çözülmüş) değerleri döner — dahili kullanım için. Arayüze servis
    eden API katmanı hassas alanları maskeler."""
    rows = (await db.scalars(select(Setting))).all()
    merged = dict(DEFAULTS)
    merged.update({r.key: _decode(r.key, r.value) for r in rows if r.key in DEFAULTS})
    return merged


async def get(db: AsyncSession, key: str) -> Any:
    if key not in DEFAULTS:
        raise KeyError(f"Bilinmeyen ayar: {key}")
    row = await db.get(Setting, key)
    return _decode(key, row.value) if row is not None else DEFAULTS[key]


_MESAI_ANAHTARLARI = ("servis_mesai_baslangic", "servis_mesai_bitis")


async def _mesai_penceresi_dogrula(db: AsyncSession, degerler: dict[str, Any]) -> None:
    """İki anahtarlı kural: mesai bitişi başlangıçtan SONRA olmalı.

    Tek anahtar gönderildiğinde diğerinin geçerli değeri DB'den okunur; aksi
    halde "18:00 → 07:00" tek tek kaydedilip ters pencere oluşabilirdi.
    """
    if not any(k in degerler for k in _MESAI_ANAHTARLARI):
        return
    bas = degerler.get(_MESAI_ANAHTARLARI[0]) or await get(db, _MESAI_ANAHTARLARI[0])
    bit = degerler.get(_MESAI_ANAHTARLARI[1]) or await get(db, _MESAI_ANAHTARLARI[1])
    b_s, b_d = (int(x) for x in str(bas).split(":"))
    t_s, t_d = (int(x) for x in str(bit).split(":"))
    if b_s * 60 + b_d >= t_s * 60 + t_d:
        raise AyarHatasi("servis_mesai_bitis: mesai bitişi başlangıçtan sonra olmalı")


async def set_many(db: AsyncSession, values: dict[str, Any], user_id: int | None) -> None:
    # Önce HEPSİ doğrulanır, sonra yazılır: üçüncü anahtar hatalıyken ilk
    # ikisinin oturuma yazılmış kalması yarım güncelleme demekti.
    dogrulanmis: dict[str, Any] = {}
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(f"Bilinmeyen ayar: {key}")
        dogrulanmis[key] = ayar_dogrula(key, value)
    await _mesai_penceresi_dogrula(db, dogrulanmis)
    for key, value in dogrulanmis.items():
        stored = (
            crypto.encrypt(value) if key in SENSITIVE_KEYS and isinstance(value, str) else value
        )
        row = await db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=stored, updated_by=user_id))
        else:
            row.value = stored
            row.updated_by = user_id
    await db.flush()
