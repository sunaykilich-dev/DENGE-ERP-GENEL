# Kararlar — 2026-11-20: saha ulaşımı, barkod/karekod, yönlendirme, izin, sicil

Kaynak: kullanıcının 2026-11-20 tarihli 7 maddelik isteği. Kullanıcı "soru sorma,
tüm sorularını onaylıyorum" dediği için belirsiz noktalar aşağıda gerekçesiyle
karara bağlandı. Hepsi deneme dalında (erp/deneme); main'e alma kullanıcı kararıyla.

## 1. Saha işinde ulaşım ve araç km

- **Kapsam:** GÜVENLİK ve HABERLEŞME birimlerinin saha işleri (kategori ATÖLYE
  olmayan işler). Diğer birimlerde ve atölye işlerinde istenmez.
- **Ulaşım türü:** Şirket aracı, Uçak, Metro, Otobüs. Kullanıcı "uçak veya metro"
  dedi; şehirlerarası otobüs de sahada sık kullanıldığı için eklendi.
- **Araç seçimi:**
  - Şirket aracı seçilirse plaka servis araçları listesinden seçilir; elle yazılmaz.
  - Planlamada araç atanmışsa önerilir; teknisyen değiştirebilir.
- **İşleme alırken (İŞLEMDE):** ulaşım türü zorunlu. Şirket aracında plaka ve
  başlangıç km de zorunlu. Başlangıç km olarak aracın son bilinen km'si önerilir.
- **Tamamlarken:** şirket aracında son km zorunlu ve başlangıç km'den küçük olamaz.
  - Kullanıcının "işi kapatırken" dediği adım, teknisyenin sonucu girdiği
    "tamamlama" adımıdır. Kapatma müdürün onay adımıdır ve teknisyen yapmaz.
  - İş İŞLEMDE'ye hiç girmeden tamamlanırsa ulaşım ve iki km birlikte istenir.
  - Girilen son km aracın "son km"si olur.
- **Eski işler:** kural yalnız bundan sonraki durum geçişlerinde uygulanır.
- **Ayar:** `servis_saha_ulasim_zorunlu` (varsayılan açık).

## 2. Kiralamada barkodla hazırlık ve iade doğrulama

- **Barkod okuyucu:** klavye gibi çalışan (okuttuğunu yazıp Enter'a basan)
  okuyucular desteklenir; ek sürücü gerekmez.
- **Hazırlık (tahsis penceresi):**
  - Seri no okutulunca o kalemin HAZIR cihazı seçime eklenir.
  - Okutulan / istenen adet yan yana gösterilir; eksik ya da fazla uyarı verir.
- **İade doğrulama:**
  - "Barkodla iade kontrolü" penceresinde dönen cihazlar okutulur.
  - Sunucu, sevk edilmiş ve henüz dönmemiş seri cihazlarla karşılaştırır.
    Eksik, fazla ya da başka kiralamaya ait cihaz varsa açıklama zorunludur.
  - Seri numarası olmayan ek ekipman için gelen adet girilir. Eksik adet için de
    açıklama zorunludur.
  - Sonuç kiralama geçmişine yazılır; eksik/yanlış sayıları denetim izine gider.
  - İade penceresi bu sonuca göre doldurulur: okunan cihaz "İade alındı", okunmayan "Müşteride"
    kalır ve açıklama nota yazılır. Kayıp kararını kullanıcı satırda verir.

## 3. Xray kapı ve bariyer: cihaza özgü karekod

- **Karekod:** her kiralık cihaza değişmez bir etiket kodu verilir. Karekod bu
  kodla ERP'deki "Etiket" sayfasının adresini taşır. Etiket sayfası yazdırılıp
  cihaza yapıştırılır.
- **Teslim okutma:**
  - Telefonun kamerasıyla okutulan sayfa (giriş gerekir) cihazı ve bulunduğu
    kiralamayı gösterir.
  - "Gidişte teslim alındı" ya da "Dönüşte teslim alındı" düğmesiyle teslim kapatılır.
- **Kim, ne zaman:** tahsis satırına kim, ne zaman ve hangi yönde teslim aldı
  yazılır; kiralama geçmişine de işlenir.
- **Kapsam:** etiket her kiralık cihazda üretilebilir. Kullanıcı Xray kapı ve
  bariyer için istedi; diğer birimler kullanmak zorunda değildir.

## 4. Telsiz teknik servisinde seri okutma

- **Atölye kabul formu:** seri alanı okuyucuyla doldurulabilir. Enter formu
  göndermez, yalnız seriyi ekler.
- **Kargo / teslim öncesi seri okutma:** yalnız onarımı bitmiş
  (TESLİME HAZIR) cihaz kargoya ya da teslime çıkar; bu kural zaten vardı.
  - Telsiz birimlerinde (HABERLEŞME, POC) kargoya verirken ve teslim ederken
    cihaz seri numaraları yeniden okutulur.
  - Okutulan seri kayıttakinden farklıysa ya da eksikse açıklama zorunludur;
    açıklama teslim notuna eklenir.

## 5–6. Satış ve kiralama talebinin teknik servis müdürüne yönlendirilmesi

- **Yönlendirme kaydı:** her yönlendirme ayrı bir kayıttır.
  - Durumu MÜDÜRDE → BİRİMDE olur.
  - Hedefi bir servis işi (satıştan doğan kurulum/teslimat) ya da bir kiralamadır.
- **Satış:**
  - Onaylı teklif ya da siparişten iş açılınca yönlendirme kendiliğinden
    MÜDÜRDE olarak oluşur.
  - Satışçı açarken sözleşme / taahhüt ayrıntılarını yazar; bu metin
    yönlendirmede ve işte görünür.
- **Kiralama:**
  - Müşteri talebi onaylanınca ("Talebi onayla ve teknik servise yönlendir",
    `kiralama.yaz`) yönlendirme MÜDÜRDE olarak oluşur.
  - Kiralama durumu değişmez; onay ayrı bir damgadır.
- **Müdürün yönlendirmesi:**
  - Teknik servis müdürü (yeni izin `servis.yonlendir`: SERVIS_YONETICI, ADMIN)
    "Yönlendirmeler" ekranında birimin yöneticisini/şefini seçip yönlendirir.
    Bu kişi o birimde üye olmalı ve `servis.planla` izni olmalı.
  - Şef kendisine yönlendirilenleri aynı ekranda görür.
- **Planlama kilitlenmez:** yönlendirme planlamayı engellemez. G1.9 (fazla onay
  adımı olmasın) gereği yeni bir zorunlu onay kapısı eklenmedi.
  - İş planlanınca ya da kiralama TALEP'ten çıkınca yönlendirme listede
    "planlandı" görünür ve açık listeden düşer.

## 7. Personel izin talebi

- **Talebi giren:** personel kendi talebini girer (İnsan Kaynakları › İzin
  Talepleri). İK (`izin.yonet`) başkası adına girebilir ve hepsini görür.
- **Zorunlu alanlar:** izin türü, başlangıç ve bitiş tarihi, **vekil** (izinde
  yerine bakacak personel), **izinde bulunacağı il** ve **iletişim numarası**.
  - Vekil talep sahibinin kendisi olamaz ve aktif personel olmalıdır.
  - "Tayin" sözcüğü İK ekranlarında kullanılmaz; ekranda "vekil" denir.
- **Onay zinciri:** birim şefi → teknik müdür → GMY. KARARLAR 2026-10-28
  G2.9'a göre onaycı, org şemasındaki yöneticidir.
  - Personelin yöneticisi birinci onaycıdır (şef). Onun yöneticisi ikinci
    onaycıdır (müdür), onunki üçüncü onaycıdır (GMY).
  - Zincir kısaysa olan kadarıyla ilerler. Yöneticisi tanımlı olmayan
    personelin talebi alınmaz ve ekranda neden yazılır.
- **Bildirim:**
  - Sıra gelen onaycıya ERP'de bildirim gider. E-posta yapılandırılmışsa
    "Onayla / Reddet" düğmeli e-posta da gider.
  - Düğme tek kullanımlık bir bağlantıdır. Bağlantı karar sayfasını açar; karar,
    sayfadaki onay düğmesiyle verilir. Böylece e-posta tarayıcılarının
    bağlantıyı açması kendiliğinden onay sayılmaz.
- **Son onaydan sonra:** talep ONAYLANDI olur.
  - İK e-posta adresine (ayar `ik_eposta`) özet gider; talep sahibine de bilgi
    gider.
  - Planlamada personelin müsaitliğine "İzin" bloğu düşer; çakışan blok varsa
    atlanır.
- **Red:** herhangi bir basamakta red talebi bitirir. Gerekçe zorunludur.
- **24 saat kuralı:**
  - Sırası gelen onaycı 24 saat içinde karar vermezse basamak "süre aşımı"
    olur ve talep bir sonraki yöneticiye geçer.
  - Son basamaktaysa, o onaycının yöneticisine yeni bir basamak eklenir.
  - Yönetici yoksa talep bekler ve İK'ya bildirilir.
  - Arka plan görevi `izin-yukseltme` 15 dakikada bir çalışır. Süre
    `izin_onay_sure_saat` ayarıyla değiştirilebilir.

## 8. Sicil numarası

- **Biçim:** sicil numarası şirket geçmişine (işe giriş tarihine, eşitse kayıt
  sırasına) göre verilir. Sicil numarası olmayan personel en eskiden başlayarak
  numaralanır. Var olan sicil numaraları değiştirilmez.
  - Sayı 4 haneli sıfır dolgulu yazılır (0001).
  - Önek `sicil_onek` ayarıyla eklenebilir (varsayılan boş).
- **Otomatik ilerleme:** yeni personel açılırken sicil boş bırakılırsa en büyük
  sayısal sicilin bir fazlası verilir. Ayrılıp yeniden giren personel yeni kayıt
  açılırsa yeni numara alır.
- **Toplu numaralama:** "Sicil numarala" önce önizleme gösterir, onaylanınca
  uygular.
- **Yetki:** personel veri girişi `personel.yaz` iznindedir ve bu izin İK
  rolünde vardır.
  - Teknik servis müdürünün bu izni mevcut işleyiş için korunur: birim, ekip
    ve yönetici ataması bu izne bağlı.
  - Yalnız İK'ya bırakılmak istenirse Rol ekranından kaldırılabilir.

## Ekranlar ve uygulama notları

| Madde | Ekran | Sunucu ucu |
|---|---|---|
| §1 | Benim İşlerim › iş kartı ve Servis İşleri › iş ayrıntısı: "İşleme al" ve yerinde tamamlama öncesi ulaşım penceresi | `GET/PUT /api/teknik-servis/isler/{id}/ulasim` |
| §2 | Kiralamalar › Tahsis (barkodla cihaz ekleme), İade al › "Barkodla iade kontrolü" | `POST /api/kiralama/{id}/iade-kontrol` |
| §3 | Kiralık Envanter › cihaz kartı › "Karekod etiketi"; telefondan `/etiket/<kod>` | `POST /api/kiralama/envanter/{id}/etiket`, `GET/POST /api/kiralama/etiket/{kod}[/teslim]` |
| §4 | Atölye kabul formu (seri alanı okuyucuyla), Atölye durum penceresi (kargoya ver / teslim et) | `POST /api/teknik-servis/atolye/{so_id}/durum` (`teslim.okutulan_seriler`) |
| §5–6 | Servis İşleri › Yönlendirmeler; satış iş açma formunda "Sözleşme / taahhüt ayrıntıları"; kiralama kartında "Talebi onayla, teknik servise yönlendir" | `/api/teknik-servis/yonlendirmeler`, `POST /api/kiralama/{id}/talep-onay` |
| §7 | İnsan Kaynakları › İzin Talepleri (Taleplerim / Onayımda / Tüm talepler); e-posta bağlantısı `/izin-karar/<anahtar>` (oturumsuz) | `/api/izin`, `/api/public/izin/{anahtar}` |
| §8 | Personel › Liste menüsü › "Sicil numarala"; yeni personelde sicil boşsa otomatik | `GET /api/personel/sicil/sonraki`, `POST /api/personel/sicil/numarala` |

- Migration: `fch000000001` (`fcg000000001`'e bağlı).
- Yeni izinler: `servis.yonlendir` (SERVIS_YONETICI, ADMIN) ve `izin.yonet` (IK, ADMIN). Arayüzden özelleştirilmiş rollere kendiliğinden inmez; Rol ekranından eklenir.
- Yeni ayarlar:
  - `servis_saha_ulasim_zorunlu` (açık)
  - `atolye_teslim_seri_okutma` (açık)
  - `izin_onay_sure_saat` (24)
  - `ik_eposta` (boş: İK'ya e-posta gitmez, ERP'de görünür)
  - `sicil_onek` (boş)
- Arka plan görevi: `izin-yukseltme`, 15 dakikada bir (`python -m app.worker`).
- Uyarı merkezi: onayımı bekleyen izin ve yönlendirme bekleyen talepler sayılır.

## Ekler — 2026-11-25 (kullanıcı isteği)

| Konu | Karar | Gerekçe |
|---|---|---|
| Plaka | Şirket aracında plaka listeden seçilir **ya da elle yazılır** (`service_orders.arac_plaka`, fci000000001). Havuzdaki bir plakayla (boşluk/büyük-küçük harf farkı gözetmeden) eşleşen metin o araca bağlanır. | Araç havuzu henüz eksiksiz değil; plaka yüzünden iş durmasın. |
| Araç km | Şimdilik **zorunlu değil**: `servis_saha_km_zorunlu` ayarı (varsayılan kapalı). Girilirse son km başlangıçtan küçük olamaz. Ulaşım türü ve şirket aracında plaka zorunluluğu sürer. | Kullanıcı: "km şimdilik zorunlu istemesin, ileride düzenleyeceğiz" — ayarı açmak yeter. |
| Güvenlik personeli | `app.seeds.personel_ice_aktar` komutu: CSV'den kişi açar (`ad.soyad` kullanıcı adı, birincil birim, yönetici bağı), geçici parolaları yalnız çıktı dosyasına yazar; `--parola-yenile` var olanlara yeni geçici parola verir. Kişi listesi ve parolalar `.yerel_gizli/` altında, depoda değil. Takım lideri `SERVIS_SEF` (saha rolü ŞEF), diğerleri `SERVIS_TEKNISYEN`; teknisyenlerin yöneticisi takım lideri (izin zinciri). | KVKK: kişi adı/parola koda girmez. Komut canlıda da aynen çalışır. |
| Sicil | İçe aktarmada sicil verilmez. | Sicil işe giriş tarihine göre sıralanır (§8); tarih bilinmeden numara vermek sırayı bozar. Tarihler girilince "Sicil numarala". |
| Onay bölümü | İş Emri Onayı'na yalnız **TAMAMLANDI** işler düşer (kalite/son onay bekleyen). Kapatılmış iş — kalite onayı verilmeden kapanmış olsa bile — onay bölümünde görünmez. Toplu seçim/onay (2026-11-17) aynen. | Eskiden "kalite onayı bekleyen" koşulu kapanmış işleri de onaya düşürüyordu. |
| Kapanan İşler | Servis İşleri › Tüm Servis İşleri'nin altında **Kapanan İşler** (`/kapanan-isler`, `kpi=kapanan_isler`), birim sekmeli, PB hariç, `servis.gor`. | Kullanıcı: kapanan işler onaydan ayrı, servis işlerinin altında ayrı bölüm. |
