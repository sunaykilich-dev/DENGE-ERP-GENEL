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

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto
from app.models import Setting

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
    "iskonto_onay_esigi_yuzde": 10.0,  # üstü satış müdürü onayına düşer
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
}

# Admin arayüzünden düzenlenebilir anahtarların beyaz listesi = DEFAULTS anahtarları.


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


async def set_many(db: AsyncSession, values: dict[str, Any], user_id: int | None) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(f"Bilinmeyen ayar: {key}")
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
