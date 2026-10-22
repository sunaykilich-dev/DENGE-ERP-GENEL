"""Bakım kontrol şablonları — ilk sürümde KOD SABİTİ (E04, TS-062/064).

Madde kodları ve metinleri eski sistemden AYNEN taşındı
(`DengeERP.Api/Program.cs:3105-3133`, `MaintenanceCheckTemplate`): sahadaki
teknisyen ve müşteri formu aynı cümleleri görmeye alışkın, eski PB
raporları da bu kodlarla (XR_*, MD_*) sorgulanıyor.

**Neden tablo değil:** kullanıcı yeni şablon ya da ölçüm alanı istemedi
(E04 S6/S7); tabloya taşıma E04-22 ile ertelendi. PB üretiminde maddeler
forma KOPYALANIR (`maintenance_form_checks.label`): şablon sonradan değişse
de eski formun metni değişmez. Şablon değişirse `surum` artırılır; form hangi
sürümle açıldığını `template_version`'da taşır.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KontrolMaddesi:
    kod: str
    etiket: str


@dataclass(frozen=True)
class KontrolSablonu:
    surum: int
    maddeler: tuple[KontrolMaddesi, ...]


def _sablon(surum: int, *maddeler: tuple[str, str]) -> KontrolSablonu:
    return KontrolSablonu(surum, tuple(KontrolMaddesi(k, e) for k, e in maddeler))


# Anahtar = `maintenance_contract_items.equipment_type` (XRAY, KAPI_DEDEKTORU).
KONTROL_SABLONLARI: dict[str, KontrolSablonu] = {
    "XRAY": _sablon(
        1,
        ("XR_EXT", "Gövde, kapaklar, koruyucu muhafazalar ve mekanik sabitlemeler kontrol edildi"),
        ("XR_CURTAIN", "Giriş/çıkış kurşun perdeleri ve fiziksel bütünlük kontrol edildi"),
        ("XR_ESTOP", "Acil durdurma sistemi ve güvenli duruş işlevi kontrol edildi"),
        ("XR_INTERLOCK", "Kapak emniyet kilitleri ve interlock uyarıları kontrol edildi"),
        ("XR_BELT", "Konveyör bandı, tahrik ve yön kontrolü yapıldı"),
        ("XR_IMG", "Ekran görüntüsü, görüntü kalitesi ve operatör fonksiyonları kontrol edildi"),
        ("XR_TEST", "Uygun test parçasıyla algılama/performans kontrolü yapıldı"),
        ("XR_LIGHT", "İkaz lambaları, sesli uyarılar ve durum göstergeleri kontrol edildi"),
        ("XR_CLEAN", "Cihaz dış yüzeyi ve erişilebilir alan temizliği tamamlandı"),
        ("XR_FAULT", "Hata kayıtları, kablo/konnektör görünür durumları kontrol edildi"),
        (
            "XR_SAFETY",
            "Yetkili prosedüre göre radyasyon güvenliği/kaçak kontrol kayıtları değerlendirildi",
        ),
    ),
    "KAPI_DEDEKTORU": _sablon(
        1,
        ("MD_EXT", "Panel, gövde, üst bağlantı ve sabitlemeler kontrol edildi"),
        ("MD_POWER", "Enerji beslemesi, kablo ve konnektörlerin görünür durumu kontrol edildi"),
        ("MD_BOOT", "Cihaz açılışı ve kendi kendini test sonuçları kontrol edildi"),
        ("MD_ALARM", "Sesli alarm, ışıklı uyarı ve alarm göstergeleri kontrol edildi"),
        ("MD_ZONES", "Algılama bölgeleri ve bölgesel alarm göstergeleri kontrol edildi"),
        ("MD_TEST", "Standart test nesnesiyle geçiş ve algılama testi yapıldı"),
        ("MD_SENS", "Hassasiyet/ayarların yetkili konfigürasyona uygunluğu kontrol edildi"),
        ("MD_COUNTER", "Varsa geçiş/sayaç ve günlük işlevleri kontrol edildi"),
        ("MD_FALSE", "Çevresel etkileşim ve yanlış alarm davranışı gözlendi"),
        ("MD_CLEAN", "Panel yüzey temizliği ve fiziksel durum kontrolü tamamlandı"),
    ),
}

# Ekranda gösterilen tür adları (tek kaynak; ön yüz bunu API'den okur).
CIHAZ_TURU_ADLARI: dict[str, str] = {"XRAY": "X-Ray", "KAPI_DEDEKTORU": "Kapı Dedektörü"}


def sablon(equipment_type: str) -> KontrolSablonu | None:
    """Türün şablonu; yoksa None (üretim `SABLON_YOK` gerekçesiyle atlar)."""
    return KONTROL_SABLONLARI.get(equipment_type)
