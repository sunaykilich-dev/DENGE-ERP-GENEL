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
    # KARARLAR 2026-11-09 S1.4 (G5.5 kademeli onay): satış müdürünün kendi
    # limitini aşan iskonto Genel Müdür'e ya da ADMIN'e gider. Genel Müdür
    # rolü yok; bu izin ona kişi istisnası/özel rolle verilir (ADMIN'de hazır).
    "teklif.iskonto_ust_onay": (
        "Teklif",
        "Satış müdürü limitini aşan iskontoyu onaylar (Genel Müdür kademesi)",
    ),
    # S2.2: "Tekliflerim" görünümünün satışçı kırılımı (satış müdürü).
    "teklif.ekip_ozet": ("Teklif", "Teklif sonuçlarını satışçı kırılımıyla görür"),
    # S3.1: satış rolleri servis işi AÇAMAZ; yalnız tekliften keşif ister
    # (dar izin; iş PLANLAMADA doğar, planlamayı birim şefi yapar).
    "teklif.kesif_iste": ("Teklif", "Tekliften bağlı KEŞİF servis işi ister"),
    # S4.1: kabul edilen teklif ya da siparişten kurulum/teslimat işi.
    "teklif.servis_isi_ac": (
        "Teklif",
        "Kabul edilen teklif ya da siparişten bağlı KURULUM/TESLİMAT işi açar",
    ),
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
    # 2026-11-09: teknisyen menüsü sadeleşti. Ana panel, servis paneli,
    # planlama panosu ve takip/KPI listeleri ekip yönetimi ekranlarıdır;
    # saha teknisyeni kendi işini "Benim İşlerim"den yürütür.
    "takip.gor": (
        "Teknik Servis",
        "Ana panel, servis paneli, planlama panosu ve takip listelerini görür",
    ),
    "servis.yaz": (
        "Teknik Servis",
        "Servis işi açar; not, ek, seri, irtibat girer; müşteri/lokasyon seçer",
    ),
    "servis.planla": (
        "Teknik Servis",
        "Plan yapar, ekip tayin eder, toplu plan/tayin, erteleme, müsaitlik; "
        "çakışmayı gerekçeyle geçer",
    ),
    "servis.tamamla": ("Teknik Servis", "Sonuç girer ve işi TAMAMLANDI yapar"),
    "servis.kapat": (
        "Teknik Servis",
        "Kapatır, iptal eder; kapalı işte gerekçeli düzeltme yapar",
    ),
    # Faz A (D3.4, G4.6): tamamlanan işin kalite onayı. İşte tayinli ya da
    # süre kaydı olan kişi onaylayamaz (görevler ayrılığı, servis katmanında).
    "servis.kalite_onay": (
        "Teknik Servis",
        "Tamamlanan işe kalite onayı verir (kendi çalıştığı işe veremez)",
    ),
    "servis.uzaktan_coz": ("Teknik Servis", "Açılışta telefonla/uzaktan çözüldü kaydı açar"),
    # KARARLAR 2026-11-05 §9: iki aşamalı kapanış (`servis_kapanis_onay_zinciri`)
    # açıkken iş, ekip liderinin kalite onayından SONRA yalnız bu izinle kapanır.
    "servis.son_onay": (
        "Teknik Servis",
        "Ekip lideri onayından sonra işe son onayı verip kapatır (iki aşamalı kapanış)",
    ),
    # Rol testi B3 (KARARLAR 2026-11-04 §6.5): satış destek satılan cihazın
    # kurulum takibini yapar. `servis.yaz` (her tür iş, not, ek) yerine yalnız
    # KURULUM işi açma izni — en az yetki.
    "servis.kurulum_ac": (
        "Teknik Servis",
        "Satılan cihaz için yalnız KURULUM türünde servis işi açar",
    ),
    # Rol testi B5 (KARARLAR 2026-11-04 §6.11): talep listesi/göç aktarımında
    # asıl bildirim tarihi korunur (7 gün sınırı yok); SLA ölçülmez (GECIS).
    "servis.gecis_kaydi": (
        "Teknik Servis",
        "Geçiş/içe aktarma kaydı açar: eski bildirim tarihi korunur, SLA ölçülmez",
    ),
    "servis.tanim": ("Teknik Servis", "Arıza nedeni kataloğunu düzenler"),
    "servis.arac_yaz": ("Teknik Servis", "Servis araç havuzunu yönetir"),
    # Adı bilerek `.gor` ile bitmez: YONETIM'in otomatik salt-okunur kümesine
    # girmesin (KVKK en az erişim).
    "servis.irtibat_gor": (
        "Teknik Servis",
        "Saha yetkilisi, telefon ve açık adresi görür (tayin edildiği işte izinsiz de görür)",
    ),
    # --- Ana veri (hesap genişletmesi) ------------------------------------------
    "lokasyon.yaz": (
        "Hesaplar",
        "Var olan müşteriye tesis/lokasyon ve lokasyon irtibatı açar, düzenler",
    ),
    # G10.2 (KARARLAR 2026-10-28 §5, Faz A/5): müşteri KARTINI yalnız Müşteri
    # İlişkileri / satış destek / muhasebe / yöneticiler açar-değiştirir. TS
    # operasyon kayıt açarken müşteriyi SEÇER; listede yoksa kart talebi
    # bırakır. Eskiden hızlı müşteri `lokasyon.yaz` ile açılıyordu ve bu izin
    # bütün saha/operasyon rollerinde vardı. Mobilite tarafı Hesaplar ekranında
    # `hesap.yaz` ile kart açar (değişmedi); TS uçları ikisinden birini kabul
    # eder (`api/teknik_servis_ana_veri.py`).
    "hesap.kart_yaz": (
        "Hesaplar",
        "Teknik servisten hızlı müşteri kartı açar ve kart künyesini (unvan, il, "
        "telefon, e-posta, cari kodu) düzeltir",
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
    # Rol testi B4 (KARARLAR 2026-11-04 §6.5): operasyon kargoyla gelen cihazı
    # atölyeye KABUL eder; teşhis/onarım/teslim `atolye.yaz`'da kalır.
    "atolye.kabul": ("Atölye", "Atölye kabul kaydı açar (tekli ve toplu kabul)"),
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
    # Kullanıcı isteği 2026-11-09: teknisyen depodan amir onayıyla parça ister.
    "parca.talep_onay": (
        "Yedek Parça",
        "Kendi biriminin teknisyenlerinin depo parça taleplerini onaylar ya da reddeder",
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
    # --- İK Bordro ve Belgeler (KARARLAR 2026-10-28 §11) ------------------------------
    # Adları `.gor` ile BİTMEZ: `_READ_ONLY_ALL` (YONETIM) bütün `.gor`'ları alır
    # ve bordro varsayılan gizlidir. Kişinin KENDİ belgesi izne bağlı değildir
    # (kimliğe bağlıdır): rolü ne olursa olsun herkes kendi bordrosunu görür.
    "bordro.yonet": (
        "İK Belgeleri",
        "Bordro gönderir; bordroları, onay ve itiraz durumunu görür (gizli)",
    ),
    "ik_belge.yonet": (
        "İK Belgeleri",
        "Form/talimat/taahhütname şablonu tanımlar, personele gönderir, imzayı takip eder",
    ),
    # --- Ana Panel (KARARLAR 2026-11-09 S8.3, G7.3) ---------------------------------
    # Kişisel düzen izne bağlı DEĞİLDİR (S8.1: herkes kendi panelini düzenler;
    # bileşenler ayrıca kendi veri izinleriyle süzülür). Rolün VARSAYILAN
    # düzenini yalnız yönetici belirler; `.gor` ile bitmez → YONETIM'e inmez.
    "panel.yonet": (
        "Ana Panel",
        "Rollerin varsayılan Ana Panel düzenini belirler (kendi göremediği bileşeni ekleyemez)",
    ),
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
    # KARARLAR 2026-11-04 §1-2: Set Bariyer (Kurulum/Toplama/Taşıma), DENGE ELEKTRONİK.
    "BARIYER": "Set Bariyer",
}

# --- Şirketler (KARARLAR 2026-11-04 §1) -----------------------------------------
# Üç şirket tek sistemi kullanır; ayrım anahtarı BİRİMDİR (her birim bir şirkete
# ait, `birim_sirketleri`). Kodlar KALICIDIR ve ön yüzle sözleşmedir. Sıra =
# şirket seçicideki sıra. DB'deki `sirketler` tablosu bu sözlükten doldurulur
# (migration f1a000000001 + `seeds.dev.sync_sirketler`).
SIRKETLER: dict[str, str] = {
    "TELEKOM": "DENGE TELEKOM",
    "ELEKTRONIK": "DENGE ELEKTRONİK",
    "MOBILITE": "DENGE MOBİLİTE",
}
# Canlı mobilite modülü (cihaz, hat, araç, iş emri, hak ediş ...) yalnız bu
# şirket etkinken açılır (`api/deps.mobilite_sirketi_gerekli`).
MOBILITE_SIRKETI = "MOBILITE"
# Varsayılan birim → şirket eşlemesi (karar varsayımı). Yalnız ilk dolumda
# kullanılır; sonrasında tek kaynak `birim_sirketleri` tablosudur.
VARSAYILAN_BIRIM_SIRKETLERI: dict[str, str] = {
    "HABERLESME": "TELEKOM",
    "POC": "TELEKOM",
    "GUVENLIK": "ELEKTRONIK",
    "BARIYER": "ELEKTRONIK",
    "MOBILITE": "MOBILITE",
    "ARAC_TAKIP": "MOBILITE",
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
# Rol düzenleme ekranında AYRICA işaretlenen hassas izinler (2026-11-09):
# kişisel veri, ücret/maliyet ve sistem yönetimi. Yönetici bunları bilerek
# vermeli; ekran uyarı rozeti çizer. Tek kaynak burası (`/api/izinler` döner).
HASSAS_IZINLER = YUKSEK_YETKILI_IZINLER | {
    "maliyet.gor",
    "maliyet.yaz",
    "bordro.yonet",
    "ik_belge.yonet",
    "personel.yaz",
    "personel.cikis",
    "servis.irtibat_gor",
    "tahsilat.gor",
}

# Süreli vekâletle verilemeyecek izinler (Dalga 4, TS-213; `api/vekalet.py`
# 403 + `yetki.ret` denetimi). Yüksek yetki, fiyat/maliyet, hak ediş onay/ödeme,
# tahsilat ve teklif onayı "birkaç günlüğüne" devredilmez; `vekalet.ver` de
# zincirleme devri önlemek için kapalıdır.
VEKALETE_KAPALI = YUKSEK_YETKILI_IZINLER | {
    "maliyet.gor",
    "maliyet.yaz",
    "teklif.onayla",
    "teklif.iskonto_ust_onay",
    "hakedis.onayla",
    "hakedis.ode",
    "tahsilat.yaz",
    "vekalet.ver",
    # Bordro gizlidir (G10.8 maaş); "birkaç günlüğüne" başkasına açılmaz.
    "bordro.yonet",
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
            "teklif.kesif_iste",
            "teklif.servis_isi_ac",
            "siparis.gor",
            "siparis.yaz",
            "abonelik.gor",
            "rma.gor",
            "rapor.gor",
            # Rol testi tur 2 (6_satis Y8/O12, KARARLAR 2026-11-04 §7.8): kendi
            # müşterilerinin servis işlerini (teklif bekleyen sonuçlar dahil)
            # OKUR; kapsam `kapsam._is_kosulu` KENDI_MUSTERILERI (müşteri sahibi
            # ∧ etkin şirket). Yazma, irtibat tam görünümü ve maliyet yok.
            "servis.gor",
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
            "teklif.ekip_ozet",
            "teklif.kesif_iste",
            "teklif.servis_isi_ac",
            "siparis.gor",
            "siparis.yaz",
            "abonelik.gor",
            "abonelik.yaz",
            "rma.gor",
            "rapor.gor",
            "rapor.disaaktar",
            "maliyet.gor",
            # S8.3: satış rollerinin varsayılan Ana Panel düzeni.
            "panel.yonet",
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
    # KARARLAR 2026-11-04 §3: görünen ad "Finans Uzmanı" (kod ve yalnız ofis
    # kısıtı aynı; seed özelleştirilmemiş rolün adını eşitler).
    # `maliyet.gor` YOK (G4.4: "Muhasebe Uzmanı görmez"; rol testi tur 2 Y7,
    # KARARLAR 2026-11-04 §7.7). Fatura devri tutarı `teklif.gor` ile görünür
    # (gelir/teklif tutarı maliyet değildir — `fatura_devri.tutar_gorur_mu`).
    "MUHASEBE_DESTEK": (
        "Finans Uzmanı",
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
        ),
        SCOPE_ALL,
    ),
    "YONETIM": ("Yönetim (salt okunur)", _READ_ONLY_ALL + ("maliyet.gor",), SCOPE_ALL),
    # --- Teknik servis rolleri (plan §1.4) -----------------------------------
    # Mobilite `TEKNIK_SERVIS` rolü AYRIDIR ve değişmez (isemri.onayla → hak
    # ediş). Servis rollerinde `hesap.yaz`, `isemri.*`, `hakedis.*`,
    # `tahsilat.*`, `rapor.gor`, `rapor.disaaktar`, `maliyet.yaz` YOK (unit
    # testle kilitli): servis personeli IBAN/VKN düzenlemez (KD-07), mobilite
    # finans Excel'ine erişmez (KD-06), fiyat varsayılan gizli (KD-11).
    # Tek istisna: TS Yöneticisi `maliyet.gor` (G4.4 maliyet görenler listesi;
    # rol testi tur 2 O6, KARARLAR 2026-11-04 §7.7) — iş maliyeti, bakım ücreti.
    "SERVIS_YONETICI": (
        "Teknik Servis Müdürü",
        (
            "maliyet.gor",
            "servis.gor",
            "servis.yaz",
            "servis.planla",
            "servis.tamamla",
            "servis.kapat",
            "servis.kalite_onay",
            "servis.son_onay",
            "servis.uzaktan_coz",
            "servis.tanim",
            "servis.arac_yaz",
            "servis.irtibat_gor",
            "servis.gecis_kaydi",
            "hesap.gor",
            "lokasyon.yaz",
            "hesap.kart_yaz",
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
            "parca.talep_onay",
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
            # S8.3: servis rollerinin varsayılan Ana Panel düzeni.
            "panel.yonet",
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
            "servis.kalite_onay",
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
            "parca.talep_onay",
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
    # Rol testi (KARARLAR 2026-11-04 §6.5): operasyon listede olmayan müşteriyi
    # hızlı kartla açar (`hesap.kart_yaz`; kart doğrulanmamış doğar, benzer kayıt
    # uyarısı korunur, doğrulama `hesap.birlestir`'de) ve atölye kabulü yapar
    # (`atolye.kabul`; teşhis/onarım `atolye.yaz` değil).
    "SERVIS_OPERASYON": (
        "Teknik Servis Operasyon Uzmanı",
        (
            "servis.gor",
            "servis.yaz",
            "servis.uzaktan_coz",
            "hesap.gor",
            "hesap.kart_yaz",
            "lokasyon.yaz",
            "atolye.gor",
            "atolye.kabul",
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
    # `urun.gor` YOK (2026-11-09): Ürün Kataloğu satışın ekranı; teknisyen
    # parçayı `parca.gor` ile (yedek parça listesi) seçer.
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
            "bordro.yonet",
            "ik_belge.yonet",
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
    # --- KARARLAR 2026-11-04 §3: yeni roller -----------------------------------
    # Saha Sorumlusu: sahadaki işleri açar, izler, günceller; zaman kaydı ve
    # ek/fotoğraf (`servis.yaz`). Tayin (`servis.planla`), kalite onayı,
    # tamamlama/kapatma ve maliyet YOK. Müşteriyi seçer, kart açmaz (G10.2).
    "SAHA_SORUMLUSU": (
        "Saha Sorumlusu",
        (
            "servis.gor",
            "servis.yaz",
            "servis.irtibat_gor",
            "hesap.gor",
            "lokasyon.yaz",
            "urun.gor",
            "cihaz.gor",
            "ekipman.gor",
            "zaman.yaz",
            "operasyon.gor",
            "egitim.kendim",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_OWN_UNITS,
    ),
    # Satış Destek: teklif/sipariş hazırlar; servis kayıtlarını ve atölye
    # teşhisini (arıza tespit sonucu) OKUR. G10.2: müşteri kartını satış destek
    # açar/düzeltir (`hesap.kart_yaz`; mobilite `hesap.yaz` değil). Maliyet,
    # teklif iç onayı ve iskonto onayı YOK. Rol testi (KARARLAR 2026-11-04
    # §6.5): satılan cihazların kurulum takibi — ekipman (KURULUM_BEKLIYOR) ve
    # tesis açar, yalnız KURULUM işi açar (`servis.kurulum_ac`; `servis.yaz` yok).
    "SATIS_DESTEK": (
        "Satış Destek",
        (
            "teklif.gor",
            "teklif.yaz",
            "teklif.kesif_iste",
            "teklif.servis_isi_ac",
            "siparis.gor",
            "siparis.yaz",
            "servis.gor",
            "servis.kurulum_ac",
            "atolye.gor",
            "ekipman.gor",
            "ekipman.yaz",
            "hesap.gor",
            "hesap.kart_yaz",
            "lokasyon.yaz",
            "urun.gor",
            "cihaz.gor",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_OWN_UNITS,
    ),
    # Finans Yöneticisi: maliyet/fiyat görür, servis fatura devrini işaretler
    # (`tahsilat.yaz`), hak ediş dökümünü onaylar, raporları alır. `maliyet.yaz`
    # (tarife girişi) yalnız ADMIN'de kalır (KD-11); yüksek yetkili izin yok.
    "FINANS_YONETICI": (
        "Finans Yöneticisi",
        (
            "maliyet.gor",
            "tahsilat.gor",
            "tahsilat.yaz",
            "hakedis.gor",
            "hakedis.onayla",
            "hakedis.ode",
            "teklif.gor",
            "siparis.gor",
            "abonelik.gor",
            "satinalma.gor",
            "isemri.gor",
            "servis.gor",
            "bakim.gor",
            "kiralama.gor",
            "hesap.gor",
            "hesap.kart_yaz",
            "urun.gor",
            "cihaz.gor",
            "rapor.gor",
            "rapor.disaaktar",
            "servis_rapor.gor",
            "servis_rapor.disaaktar",
            "gorev.gor",
            "gorev.yaz",
        ),
        SCOPE_ALL,
    ),
}

# `takip.gor` (2026-11-09): `servis.gor` taşıyan her rolde VAR, saha
# teknisyeninde YOK. Elle her role yazılsaydı yeni rol eklenirken unutulurdu;
# kural burada tek yerde. Canlıda özelleştirilmiş rollere migration
# fbb000000001 aynı kuralla ekler.
TAKIP_IZNI_OLMAYAN_ROLLER = frozenset({"SERVIS_TEKNISYEN"})
for _kod, (_ad, _izinler, _kapsam) in list(ROLES.items()):
    if "servis.gor" in _izinler and _kod not in TAKIP_IZNI_OLMAYAN_ROLLER:
        ROLES[_kod] = (_ad, (*_izinler, "takip.gor"), _kapsam)
del _kod, _ad, _izinler, _kapsam

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
    "SAHA_SORUMLUSU",
)
# Şirket geneli roller (KARARLAR 2026-11-04 §3). Servis rolü DEĞİLLER: satış
# destek birimsiz (satış) teklif de hazırlar, finans mobilite hak edişini onaylar.
GENEL_ROLLER = ("SATIS_DESTEK", "FINANS_YONETICI")


# --- Erişim yeri kısıtı (G3.8, KARARLAR 2026-10-28 §7 Faz A/8) ------------------
# Bu rollerin kullanıcıları yalnız ofis ağından (ayar `ofis_ag_listesi`, CIDR
# listesi) giriş yapar ve istek atar; liste BOŞSA kısıt uygulanmaz (kurulum
# günü kimse kilitlenmesin). İzin değil ROL NİTELİĞİDİR (`roles.yalniz_ofis`):
# izin olsaydı ADMIN (bütün izinler) ve YONETIM (bütün `.gor`) de kendiliğinden
# kısıtlanır, kişiye istisnayla "kaldırılabilir" bir yetki gibi görünürdü.
# Seed yalnız özelleştirilmemiş sistem rollerinde eşitler; yönetici rol
# ekranından istediği role açıp kapatabilir. Saha rolleri her yerden girer.
# FINANS_YONETICI (rol testi tur 2 O10, KARARLAR 2026-11-04 §7.18): G3.8 ve Faz
# A/8 "muhasebe rollerine yalnız ofis ağından"; iş analizi §5.9/5 senaryosu
# finans yöneticisinin ofis dışı girişinin reddini bekler.
YALNIZ_OFIS_ROLLERI = frozenset({"MUHASEBE_DESTEK", "FINANS_YONETICI"})


def permissions_of(role_code: str) -> tuple[str, ...]:
    return ROLES[role_code][1]
