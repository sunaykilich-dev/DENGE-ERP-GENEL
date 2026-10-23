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
    # --- Teknik Servis: servis işleri -----------------------------------------
    # Teknik servis izinleri (plan §1.3). Mevcut kodlar DEĞİŞMEZ; mobilite
    # `TEKNIK_SERVIS` rolü montaj/onay rolü olarak kalır ve bunları almaz.
    "servis.gor": (
        "Teknik Servis",
        "Servis işlerini, planı ve servis panelini görür (kapsamı kadar)",
    ),
    "servis.yaz": (
        "Teknik Servis",
        "Servis işi açar; not, ek, seri, irtibat girer; müşteri/lokasyon seçer",
    ),
    "servis.planla": (
        "Teknik Servis",
        "Plan ve ekip atar, toplu plan/atama, erteleme, müsaitlik; çakışmayı gerekçeyle geçer",
    ),
    "servis.tamamla": ("Teknik Servis", "Sonuç girer ve işi TAMAMLANDI yapar"),
    "servis.kapat": (
        "Teknik Servis",
        "Kapatır, iptal eder, yeniden açar; kapalı işte gerekçeli düzeltme yapar",
    ),
    "servis.uzaktan_coz": ("Teknik Servis", "Açılışta telefonla/uzaktan çözüldü kaydı açar"),
    "servis.tanim": ("Teknik Servis", "Arıza nedeni kataloğunu düzenler"),
    "servis.arac_yaz": ("Teknik Servis", "Servis araç havuzunu yönetir"),
    # Adı bilerek `.gor` ile bitmez: YONETIM'in otomatik salt-okunur kümesine
    # girmesin (KVKK en az erişim).
    "servis.irtibat_gor": (
        "Teknik Servis",
        "Saha yetkilisi, telefon ve açık adresi görür (atandığı işte izinsiz de görür)",
    ),
    # --- Ana veri (hesap genişletmesi) ------------------------------------------
    "lokasyon.yaz": (
        "Hesaplar",
        "Tesis/lokasyon ve lokasyon irtibatı açar, düzenler; hızlı müşteri ekler",
    ),
    "hesap.birlestir": (
        "Hesaplar",
        "Hesap/lokasyon birleştirir, takma ad ve eşleştirme dosyası uygular, "
        "hızlı açılanı doğrular",
    ),
    # --- Servis ekipmanı -------------------------------------------------------
    "ekipman.gor": ("Servis Ekipmanı", "Kurulu ekipman kütüğünü, kartı ve geçmişi görür"),
    "ekipman.yaz": (
        "Servis Ekipmanı",
        "Ekipman ekler, düzenler, durumunu değiştirir, birleştirir, saha farkını uygular",
    ),
    # --- Planlı bakım ----------------------------------------------------------
    "bakim.gor": (
        "Planlı Bakım",
        "Bakım sözleşmesi, dönem, uygunsuzluk ve bakım KPI'larını görür",
    ),
    "bakim.yaz": (
        "Planlı Bakım",
        "Sözleşme ve kapsamı yönetir, PB üretir, hedef tarihi gerekçeyle değiştirir",
    ),
    "bakim.onayla": (
        "Planlı Bakım",
        "Kapsam dışı talebine karar verir, uygunsuzluk aksiyonu atar ve kapatır",
    ),
    # --- Atölye -----------------------------------------------------------------
    "atolye.gor": ("Atölye", "Atölye kayıtlarını, seri geçmişini ve fişleri görür"),
    "atolye.yaz": (
        "Atölye",
        "Kabul, teşhis, onarım, test, onay, aksesuar, teslim ve kargo girer",
    ),
    # --- Kiralama ----------------------------------------------------------------
    "kiralama.gor": ("Kiralama", "Kiralamaları ve kiralık envanteri görür"),
    "kiralama.yaz": (
        "Kiralama",
        "Kiralama talebi, kalem, irtibat, tarih girer; planlar, iptal eder, kapatır",
    ),
    "kiralama.envanter": (
        "Kiralama",
        "Kiralık envanter girişi, transfer, tahsis, dönüş kontrolü, sayım ve katalog",
    ),
    "kiralama.asama": (
        "Kiralama",
        "Sevk, iade, kurulum/toplama aşamaları, saha değişimi ve geri alma",
    ),
    # --- Teklif / maliyet -------------------------------------------------------
    "teklif.onayla": (
        "Teklif",
        "Birimli servis teklifini iç onaydan geçirir/geri çevirir; kabul edileni iptal eder",
    ),
    # Yalnız ADMIN rolünde; ihtiyaç sahibine kişi bazlı gerekçeli istisna (KD-11).
    "maliyet.yaz": ("Özel", "Birim işçilik tarifesi, iş geliri ve diğer maliyet girer"),
    # --- Saha / zaman ---------------------------------------------------------------
    "zaman.yaz": (
        "Saha / Zaman",
        "Kendi sayacını yönetir, sınırlı geriye manuel kayıt, unuttum ve geri alma",
    ),
    # --- Operasyon / SLA -----------------------------------------------------------
    "operasyon.gor": (
        "Operasyon",
        "Operasyon Merkezi sayaçlarını, SLA listesini ve iş yükünü görür",
    ),
    "operasyon.yonet": (
        "Operasyon",
        "SLA politikası, mesai takvimi, tatil ve bekleme nedeni kataloğunu yönetir",
    ),
    # --- Yedek parça ------------------------------------------------------------
    "parca.gor": ("Yedek Parça", "Servis depolarındaki parça stoğunu ve hareketleri görür"),
    "parca.kullan": (
        "Yedek Parça",
        "Açık servis işine parça çıkışı/iadesi ve parça talebi yapar",
    ),
    "parca.yonet": (
        "Yedek Parça",
        "Giriş, transfer, zayi, ters kayıt, sayım ve onayı, açılış stoğu, "
        "parça kartı stok alanları",
    ),
    # --- Eğitim ---------------------------------------------------------------------
    "egitim.gor": ("Eğitim", "Eğitim özeti, plan, katalog ve skorları görür"),
    "egitim.detay": (
        "Eğitim",
        "Gözlem notu, madde puanı, aksiyon planı, yetkinlik kanıtı ve belge no görür",
    ),
    "egitim.yaz": (
        "Eğitim",
        "Katalog, toplu plan, erteleme/iptal, oturum, katılım, belge ve yetkinlik kataloğu",
    ),
    "egitim.gozlem": ("Eğitim", "Saha gözlemi ve yetkinlik değerlendirmesi girer"),
    "egitim.kendim": ("Eğitim", "Kendi gelişim kartını görür ve gözleme 'Gördüm' onayı verir"),
    # --- Servis raporları ---------------------------------------------------------
    # `rapor.gor/rapor.disaaktar` servis rollerine VERİLMEZ: `rapor.disaaktar`
    # mobilite hak ediş/finans Excel'lerini kapsamsız açıyor (KD-06, E12-D01).
    "servis_rapor.gor": (
        "Servis Raporları",
        "Teknik servis raporları, KPI ve zaman takibi ekranını görür",
    ),
    "servis_rapor.disaaktar": ("Servis Raporları", "Teknik servis Excel dışa aktarımlarını alır"),
    "servis_rapor.personel": (
        "Servis Raporları",
        "Kişi bazlı süre, teknisyen notu, konum notu ve saha irtibatı kırılımlarını görür",
    ),
    # --- Personel ---------------------------------------------------------------------
    "personel.gor": ("Personel", "Personel kartlarını ve birim üyeliğini görür (kapsamı kadar)"),
    "personel.yaz": (
        "Personel",
        "Personel kartı, birim üyeliği, saha rolü, girişsiz personel açar/düzenler",
    ),
    "personel.cikis": ("Personel", "İşten çıkış akışını çalıştırır"),
    # Dalga 4 (TS-213, E13-15): kendi kalıcı izinlerinin alt kümesini en fazla
    # 30 günlüğüne kapsamındaki personele devreder. Kendisi vekâlete kapalıdır.
    "vekalet.ver": ("Personel", "Süreli vekâlet verir ve iptal eder"),
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

# --- Teknik servis birimleri (kod -> Türkçe ad) -------------------------------
# Kodlar KALICIDIR: bütün `ck_*_birim` kısıtları aynı kümeyi taşır
# (`models.rbac.BIRIM_KODLARI`; modeller bu dosyayı import etmez). İki yerin
# aynı kod kümesini taşıdığı `tests/unit/test_permissions.py` ile kilitli.
BIRIMLER: dict[str, str] = {
    "GUVENLIK": "Güvenlik Sistemleri",
    "HABERLESME": "Haberleşme",
    "POC": "POC",
    "MOBILITE": "Mobilite",
    "ARAC_TAKIP": "Araç Takip",
}

# --- Kayıt bazlı kapsam -------------------------------------------------------
SCOPE_ALL = "TUMU"
SCOPE_OWN_CUSTOMERS = "KENDI_MUSTERILERI"
# Teknik servis kapsamları (plan §1.2). Canlı yardımcılar (`kapsam_musteri`,
# `kapsam_disinda_mi`, `scope_filter`) yalnız KENDI_MUSTERILERI'ne baktığı
# için bu iki kapsam canlı ekranlarda (hesap, cihaz, hat, mobilite iş emri)
# TUMU gibi davranır — bilinçli: canlı akış değişmez. Servis kayıtlarında
# kısıt `services/teknik_servis/kapsam.py`'dedir.
SCOPE_OWN_UNITS = "KENDI_BIRIMI"
SCOPE_OWN_JOBS = "KENDI_ISLERI"
SCOPES = (SCOPE_ALL, SCOPE_OWN_CUSTOMERS, SCOPE_OWN_UNITS, SCOPE_OWN_JOBS)
# Birim üyeliği (`user_units`) ZORUNLU olan kapsamlar: üyeliği olmayan
# kullanıcı hiçbir servis kaydı görmez (fail-closed, KD-04).
BIRIM_KAPSAMLARI = (SCOPE_OWN_UNITS, SCOPE_OWN_JOBS)

# --- Personel sözlükleri (models.user ile aynı; tutarlılık unit testte) -------
SAHA_ROLLERI = ("SEF", "TEKNISYEN", "STAJYER", "OFIS", "YOK")
ATANABILIR_SAHA_ROLLERI = ("SEF", "TEKNISYEN", "STAJYER")
AYRILIS_NEDENLERI = ("ISTIFA", "FESIH", "EMEKLILIK", "SOZLESME_BITIMI", "DIGER")

# --- Yetki yükseltme önlemi (E13-01, TS-006) ----------------------------------
# Bu izinler YALNIZ ADMIN rolünde bulunur: özel role eklenemez, kişiye
# istisnayla verilemez. Eskiden `sistem.kullanici` sahibi başkasına
# `sistem.denetim` istisnası ya da ADMIN rolü verebiliyordu; kullanıcı
# yönetimi yetkisi böylece bütün yetkilere açılan bir kapıydı.
YUKSEK_YETKILI_IZINLER = frozenset(
    {"sistem.kullanici", "sistem.denetim", "sistem.ayar", "sistem.goc", "kvkk.yonet"}
)
# Süreli vekâletle verilemeyecek izinler (Dalga 4, TS-213; `api/vekalet.py`
# 403 + `yetki.ret` denetimi). Yüksek yetki, fiyat/maliyet, hak ediş onay/ödeme,
# tahsilat ve teklif onayı "birkaç günlüğüne" devredilmez; `vekalet.ver` de
# zincirleme devri önlemek için kapalıdır.
VEKALETE_KAPALI = YUKSEK_YETKILI_IZINLER | {
    "maliyet.gor",
    "maliyet.yaz",
    "teklif.onayla",
    "hakedis.onayla",
    "hakedis.ode",
    "tahsilat.yaz",
    "vekalet.ver",
}

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
    # --- Teknik servis rolleri (plan §1.4) -----------------------------------
    # Mobilite `TEKNIK_SERVIS` rolü AYRIDIR ve değişmez (isemri.onayla → hak
    # ediş). Servis rollerinde `hesap.yaz`, `isemri.*`, `hakedis.*`,
    # `tahsilat.*`, `rapor.gor`, `rapor.disaaktar`, `maliyet.*` YOK (unit
    # testle kilitli): servis personeli IBAN/VKN düzenlemez (KD-07), mobilite
    # finans Excel'ine erişmez (KD-06), fiyat varsayılan gizli (KD-11).
    "SERVIS_YONETICI": (
        "Teknik Servis Müdürü",
        (
            "servis.gor",
            "servis.yaz",
            "servis.planla",
            "servis.tamamla",
            "servis.kapat",
            "servis.uzaktan_coz",
            "servis.tanim",
            "servis.arac_yaz",
            "servis.irtibat_gor",
            "hesap.gor",
            "lokasyon.yaz",
            "hesap.birlestir",
            "urun.gor",
            "cihaz.gor",
            "rma.gor",
            "teklif.gor",
            "teklif.yaz",
            "teklif.onayla",
            "teklif.iskonto_onayla",
            "ekipman.gor",
            "ekipman.yaz",
            "bakim.gor",
            "bakim.yaz",
            "bakim.onayla",
            "atolye.gor",
            "atolye.yaz",
            "kiralama.gor",
            "kiralama.yaz",
            "kiralama.envanter",
            "kiralama.asama",
            "zaman.yaz",
            "operasyon.gor",
            "operasyon.yonet",
            "parca.gor",
            "parca.kullan",
            "parca.yonet",
            "egitim.gor",
            "egitim.detay",
            "egitim.yaz",
            "egitim.gozlem",
            "egitim.kendim",
            "personel.gor",
            "personel.yaz",
            "personel.cikis",
            "vekalet.ver",
            "servis_rapor.gor",
            "servis_rapor.disaaktar",
            "servis_rapor.personel",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_ALL,
    ),
    "SERVIS_SEF": (
        "Teknik Servis Şefi",
        (
            "servis.gor",
            "servis.yaz",
            "servis.planla",
            "servis.tamamla",
            "servis.kapat",
            "servis.uzaktan_coz",
            "servis.irtibat_gor",
            "hesap.gor",
            "lokasyon.yaz",
            "urun.gor",
            "cihaz.gor",
            "rma.gor",
            "teklif.gor",
            "teklif.yaz",
            "ekipman.gor",
            "ekipman.yaz",
            "bakim.gor",
            "bakim.yaz",
            "bakim.onayla",
            "atolye.gor",
            "atolye.yaz",
            "kiralama.gor",
            "kiralama.asama",
            "zaman.yaz",
            "operasyon.gor",
            "parca.gor",
            "parca.kullan",
            "egitim.gor",
            "egitim.detay",
            "egitim.gozlem",
            "egitim.kendim",
            "personel.gor",
            "servis_rapor.gor",
            "servis_rapor.disaaktar",
            "servis_rapor.personel",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_OWN_UNITS,
    ),
    "SERVIS_OPERASYON": (
        "Teknik Servis Operasyon Uzmanı",
        (
            "servis.gor",
            "servis.yaz",
            "servis.uzaktan_coz",
            "hesap.gor",
            "lokasyon.yaz",
            "urun.gor",
            "cihaz.gor",
            "kiralama.gor",
            "kiralama.yaz",
            "operasyon.gor",
            "egitim.kendim",
            "personel.gor",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_OWN_UNITS,
    ),
    # `hesap.gor` YOK (KD-09): müşteri/irtibat bilgisi servis işi detayında
    # gömülü döner; yeni kapsam canlı hesap ekranında TUMU gibi davranacağı
    # için izin verilseydi teknisyen bütün cari listesini görürdü.
    "SERVIS_TEKNISYEN": (
        "Servis Teknisyeni",
        (
            "servis.gor",
            "servis.yaz",
            "servis.tamamla",
            "servis.irtibat_gor",
            "urun.gor",
            "cihaz.gor",
            "ekipman.gor",
            "zaman.yaz",
            "parca.gor",
            "parca.kullan",
            "egitim.kendim",
            "gorev.gor",
        ),
        SCOPE_OWN_JOBS,
    ),
    "ATOLYE": (
        "Atölye Kabul / Usta",
        (
            "servis.gor",
            "servis.yaz",
            "servis.planla",
            "servis.tamamla",
            "lokasyon.yaz",
            "urun.gor",
            "cihaz.gor",
            "rma.gor",
            "ekipman.gor",
            "atolye.gor",
            "atolye.yaz",
            "kiralama.gor",
            "zaman.yaz",
            "parca.gor",
            "parca.kullan",
            "egitim.kendim",
            "gorev.gor",
        ),
        SCOPE_OWN_UNITS,
    ),
    "SERVIS_DEPO": (
        "Servis Deposu / Yedek Parça",
        (
            "parca.gor",
            "parca.kullan",
            "parca.yonet",
            "servis.gor",
            "urun.gor",
            "hesap.gor",
            "servis_rapor.gor",
            "servis_rapor.disaaktar",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_OWN_UNITS,
    ),
    "KIRALAMA_DEPO": (
        "Kiralama Deposu",
        (
            "kiralama.gor",
            "kiralama.envanter",
            "kiralama.asama",
            "hesap.gor",
            "urun.gor",
            "servis_rapor.gor",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_OWN_UNITS,
    ),
    "IK": (
        "İnsan Kaynakları / Eğitim",
        (
            "personel.gor",
            "personel.yaz",
            "personel.cikis",
            "egitim.gor",
            "egitim.detay",
            "egitim.yaz",
            "servis_rapor.gor",
            "servis_rapor.disaaktar",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_ALL,
    ),
}

# Teknik servis rolleri (Dalga 0). Unit testler "mobilite finans/yazma izni
# yok" kuralını bu küme üzerinden kilitler.
SERVIS_ROLLERI = (
    "SERVIS_YONETICI",
    "SERVIS_SEF",
    "SERVIS_OPERASYON",
    "SERVIS_TEKNISYEN",
    "ATOLYE",
    "SERVIS_DEPO",
    "KIRALAMA_DEPO",
    "IK",
)


def permissions_of(role_code: str) -> tuple[str, ...]:
    return ROLES[role_code][1]
