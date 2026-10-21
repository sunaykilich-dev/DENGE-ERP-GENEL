"""İzin kataloğu ve rol tanımları — saf sabitler, DB bağımlılığı yok.

Seed betiği bu katalogdan `permissions` ve `role_permissions` tablolarını
doldurur; API katmanı `require_permission(...)` ile aynı kodları kullanır.
Tek kaynak burasıdır — yeni bir izin eklemek isteyen önce buraya ekler.

Maliyet görünürlüğü (`maliyet.gor`) bilinçli olarak ayrı bir izindir ve
VARSAYILAN OLARAK KAPALIDIR: brief §3 "maliyet ve alış fiyatları sadece
yetkili rollerde görünür" diyor. "Varsayılan açık, bazılarında gizle"
tasarımı güvenlik açısından yanlış olurdu.
"""

# --- İzinler: kod -> (modül, açıklama) ---------------------------------------
PERMISSIONS: dict[str, tuple[str, str]] = {
    # Hesaplar / CRM
    "hesap.gor": ("Hesaplar", "Müşteri, bayi, montaj noktası, tedarikçi kayıtlarını görür"),
    "hesap.yaz": ("Hesaplar", "Hesap açar, düzenler"),
    # Ürün kataloğu
    "urun.gor": ("Katalog", "Ürünleri ve paketleri görür"),
    "urun.yaz": ("Katalog", "Ürün, paket ve fiyat listesi düzenler"),
    # Cihaz / stok
    "cihaz.gor": ("Cihaz", "Cihaz kartı, durum ve geçmişini görür"),
    "cihaz.yaz": ("Cihaz", "Cihaz kaydı açar, durum değiştirir"),
    "cihaz.transfer": ("Cihaz", "Depo/bayi/teknisyen transferi yapar"),
    # SIM / hat
    "hat.gor": ("Hat", "Hat kartı, paket ve kullanım bilgisini görür"),
    "hat.yaz": ("Hat", "Hat kaydı açar, paket ve eşleşme değiştirir"),
    "hat.senkron": ("Hat", "Operatör senkronunu elle tetikler"),
    # Araç
    "arac.gor": ("Araç", "Araç kartı ve cihaz geçmişini görür"),
    "arac.yaz": ("Araç", "Araç kaydı açar, düzenler"),
    # İş emri
    "isemri.gor": ("İş Emri", "İş emirlerini görür"),
    "isemri.yaz": ("İş Emri", "İş emri açar, düzenler, tamamlar"),
    "isemri.onayla": ("İş Emri", "Tamamlanan işi onaylar — hak edişe bu onayla girer"),
    # Hak ediş
    "hakedis.gor": ("Hak Ediş", "Hak ediş satırlarını ve dökümleri görür"),
    "hakedis.yaz": ("Hak Ediş", "Tarife tanımlar, kesinti girer, itiraz kaydeder"),
    "hakedis.onayla": ("Hak Ediş", "Ay sonu dökümünü onaylar"),
    "hakedis.ode": ("Hak Ediş", "Ödeme kaydı girer, dökümü ÖDENDİ'ye çeker"),
    # Teklif
    "teklif.gor": ("Teklif", "Teklifleri görür"),
    "teklif.yaz": ("Teklif", "Teklif hazırlar, revize eder, gönderir"),
    "teklif.iskonto_onayla": ("Teklif", "Eşik üstü iskontoyu onaylar"),
    # Sipariş
    "siparis.gor": ("Sipariş", "Siparişleri görür"),
    "siparis.yaz": ("Sipariş", "Sipariş açar, sevkiyat yapar"),
    # Abonelik
    "abonelik.gor": ("Abonelik", "Sözleşme ve abonelikleri görür"),
    "abonelik.yaz": ("Abonelik", "Abonelik açar, yeniler, iptal eder, toplu zam uygular"),
    # RMA
    "rma.gor": ("RMA", "Servis kayıtlarını görür"),
    "rma.yaz": ("RMA", "RMA açar, çözümler"),
    # Satın alma
    "satinalma.gor": ("Satın Alma", "Satın alma ve ithalat dosyalarını görür"),
    "satinalma.yaz": ("Satın Alma", "Satın alma siparişi ve ithalat dosyası girer"),
    # Tahsilat
    "tahsilat.gor": ("Tahsilat", "Ödeme kayıtlarını ve hesap bakiyesini görür"),
    "tahsilat.yaz": ("Tahsilat", "Tahsilat kaydı girer"),
    # Rapor
    "rapor.gor": ("Rapor", "Raporları ve yönetim dashboard'unu görür"),
    "rapor.disaaktar": ("Rapor", "Excel/CSV dışa aktarır"),
    # Görev panosu
    "gorev.gor": ("Görevler", "Görev panolarını ve kartları görür"),
    "gorev.yaz": ("Görevler", "Pano, kolon ve kart açar, düzenler, taşır"),
    # Özel görünürlük
    "maliyet.gor": ("Özel", "Maliyet, alış fiyatı ve marj alanlarını görür"),
    # Sistem
    "sistem.kullanici": ("Sistem", "Kullanıcı ve rol yönetir"),
    "sistem.ayar": ("Sistem", "Parametreleri ve entegrasyon ayarlarını yönetir"),
    "sistem.denetim": ("Sistem", "Denetim izini görüntüler"),
    "kvkk.yonet": (
        "Sistem",
        "Kişisel veri erişim logunu görür, silme talebi işler, anonimleştirir",
    ),
    "sistem.goc": ("Sistem", "Veri göçü çalıştırır, karantinayı yönetir"),
}

# --- Kayıt bazlı kapsam -------------------------------------------------------
SCOPE_ALL = "TUMU"
SCOPE_OWN_CUSTOMERS = "KENDI_MUSTERILERI"
SCOPES = (SCOPE_ALL, SCOPE_OWN_CUSTOMERS)

_READ_ONLY_ALL = tuple(c for c in PERMISSIONS if c.endswith(".gor")) + ("rapor.disaaktar",)

# --- Roller: kod -> (ad, izinler, varsayılan kapsam) -------------------------
# Brief §3'teki rol tablosu. "Saha Teknisyeni (mobil)" rolü yok — mobil saha
# uygulaması kapsam dışı, işler ofisten giriliyor.
ROLES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "ADMIN": ("Sistem Yöneticisi", tuple(PERMISSIONS), SCOPE_ALL),
    "SATIS": (
        "Satış Temsilcisi",
        (
            "gorev.gor",
            "gorev.yaz",
            "hesap.gor",
            "hesap.yaz",
            "urun.gor",
            "cihaz.gor",
            "hat.gor",
            "arac.gor",
            "arac.yaz",
            "isemri.gor",
            "teklif.gor",
            "teklif.yaz",
            "siparis.gor",
            "siparis.yaz",
            "abonelik.gor",
            "rma.gor",
            "rapor.gor",
        ),
        SCOPE_OWN_CUSTOMERS,  # yalnız kendi müşterilerini görür
    ),
    "SATIS_MUDURU": (
        "Satış Müdürü",
        (
            "gorev.gor",
            "gorev.yaz",
            "hesap.gor",
            "hesap.yaz",
            "urun.gor",
            "urun.yaz",
            "cihaz.gor",
            "hat.gor",
            "arac.gor",
            "arac.yaz",
            "isemri.gor",
            "teklif.gor",
            "teklif.yaz",
            "teklif.iskonto_onayla",
            "siparis.gor",
            "siparis.yaz",
            "abonelik.gor",
            "abonelik.yaz",
            "rma.gor",
            "rapor.gor",
            "rapor.disaaktar",
            "maliyet.gor",
        ),
        SCOPE_ALL,
    ),
    "DEPO": (
        "Depo / Lojistik",
        (
            "gorev.gor",
            "gorev.yaz",
            "hesap.gor",
            "urun.gor",
            "cihaz.gor",
            "cihaz.yaz",
            "cihaz.transfer",
            "hat.gor",
            "hat.yaz",
            "arac.gor",
            "isemri.gor",
            "satinalma.gor",
            "rapor.gor",
            "rapor.disaaktar",
        ),
        SCOPE_ALL,
    ),
    "TEKNIK_SERVIS": (
        "Teknik Servis",
        (
            "gorev.gor",
            "gorev.yaz",
            "hesap.gor",
            "urun.gor",
            "cihaz.gor",
            "cihaz.yaz",
            "hat.gor",
            "hat.yaz",
            "arac.gor",
            "arac.yaz",
            "isemri.gor",
            "isemri.yaz",
            "isemri.onayla",
            "rma.gor",
            "rma.yaz",
            "rapor.gor",
        ),
        SCOPE_ALL,
    ),
    "MONTAJ_KOORD": (
        "Montaj Noktası Koordinatörü",
        (
            "gorev.gor",
            "gorev.yaz",
            "hesap.gor",
            "hesap.yaz",
            "urun.gor",
            "cihaz.gor",
            "arac.gor",
            "isemri.gor",
            "isemri.yaz",
            "isemri.onayla",
            "hakedis.gor",
            "hakedis.yaz",
            "hakedis.onayla",
            "rapor.gor",
            "rapor.disaaktar",
        ),
        SCOPE_ALL,
    ),
    "HAT_SORUMLUSU": (
        "Hat (SIM) Sorumlusu",
        (
            "gorev.gor",
            "gorev.yaz",
            "hesap.gor",
            "urun.gor",
            "cihaz.gor",
            "hat.gor",
            "hat.yaz",
            "hat.senkron",
            "arac.gor",
            "rapor.gor",
            "rapor.disaaktar",
        ),
        SCOPE_ALL,
    ),
    "MUHASEBE_DESTEK": (
        "Muhasebe Destek",
        (
            "gorev.gor",
            "gorev.yaz",
            "hesap.gor",
            "urun.gor",
            "cihaz.gor",
            "hat.gor",
            "arac.gor",
            "isemri.gor",
            "hakedis.gor",
            "hakedis.ode",
            "teklif.gor",
            "siparis.gor",
            "abonelik.gor",
            "satinalma.gor",
            "tahsilat.gor",
            "tahsilat.yaz",
            "rapor.gor",
            "rapor.disaaktar",
            "maliyet.gor",
        ),
        SCOPE_ALL,
    ),
    "YONETIM": ("Yönetim (salt okunur)", _READ_ONLY_ALL + ("maliyet.gor",), SCOPE_ALL),
}


def permissions_of(role_code: str) -> tuple[str, ...]:
    return ROLES[role_code][1]
