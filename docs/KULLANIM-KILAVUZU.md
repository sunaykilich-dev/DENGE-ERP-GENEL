# Denge ERP — Kullanım Kılavuzu

Bu belge ERP'yi günlük kullanan ekip içindir. Kurulum ve sunucu işleri
[deploy/KURULUM.md](../deploy/KURULUM.md) dosyasındadır.

ERP'nin cevaplamak için var olduğu soru şudur:

> **Bu IMEI şu an nerede, kimde, hangi araçta, hattı ne, kim taktı, bu ay
> kime ne kadar ödenecek?**

Eskiden bu soru üç ayrı yerden (hak ediş uygulaması, takip platformu, Excel)
bile cevaplanamıyordu. Aşağıdaki her ekran bu zincirin bir halkasıdır.

---

## 1. Giriş, roller ve görebildikleriniz

Menüde yalnız **yetkiniz olan** kalemler görünür. Bir modülü görmüyorsanız
eksik olan yetkidir, modül değil. Yetki isteğinizi sistem yöneticisine iletin.

| Rol | Ne yapar | Maliyet görür mü |
|---|---|---|
| Sistem Yöneticisi | Her şey; kullanıcı, parametre, KVKK | Evet |
| Satış Temsilcisi | Teklif, sipariş, müşteri — **yalnız kendi müşterileri** | Hayır |
| Satış Müdürü | Satışın tamamı + iskonto onayı | Evet |
| Depo / Lojistik | Stok, transfer, sevkiyat, zimmet | Hayır |
| Teknik Servis | RMA, garanti, cihaz durumu | Hayır |
| Montaj Noktası Koordinatörü | İş emri, hak ediş hazırlığı | Hayır |
| Hat (SIM) Sorumlusu | Hat, paket, taahhüt, kota | Hayır |
| Muhasebe Destek | Hak ediş, tahsilat, dışa aktarım | Evet |
| Yönetim | Her şeyi görür, hiçbir şeyi değiştirmez | Evet |

Bu dokuz rol kurulumla gelir; **düzenlenebilir** ve yenisi tanımlanabilir
(§7). Tek bir kişi için rolün dışına çıkmak gerekirse izin istisnası verilir.

**Maliyet ve alış fiyatı alanları varsayılan olarak gizlidir.** Yetkisiz
kullanıcıda bu alanlar "—" ya da "gizli" görünür; rapor Excel'lerinde de boş
gelir.

**Aynı kaydı iki kişi aynı anda değiştiremez.** Siz ekranı açıkken başkası
kaydettiyse "Bu kaydı siz görüntülerken başka biri değiştirdi" uyarısı çıkar.
Sayfayı yenileyip değişikliğinizi tekrar uygulayın — bu uyarı, sizin
yazdığınızın sessizce kaybolmasını engeller.

### Üst bardaki arama kutusu

IMEI, plaka, ICCID, şase ya da firma adının bir parçasını yazın. Türkçe
karakterler ve büyük/küçük harf önemsizdir; `İSTANBUL` ile `istanbul` aynı
sonucu verir. En çok kullanılan özellik budur, öğrenmesi de en kolayı.

---

## 2. Günlük akışlar

### 2.1 Bir montaj kaydetmek (İş Emirleri)

İş emri = **bir ziyaret**: araç + tarih + montaj noktası. Bir ziyarette
birden fazla cihaz takılmış olabilir (araçların %97'sinde birden fazla cihaz
var) — her cihaz ayrı bir **kalem**dir.

1. **İş Emirleri → Yeni**
2. Araç (plaka), montaj noktası, tarih, kilometre, blokaj bilgisi
3. Her cihaz için bir kalem: IMEI/seri no, işlem (takıldı / söküldü /
   değişti), **ödenebilirlik**
4. Kaydedince cihaz–araç dönemi otomatik açılır; aynı cihazın önceki açık
   dönemi kapanır.

> **Ödenebilirlik ayrı bir karardır.** Tamamlanan iş hak edişe otomatik
> GİRMEZ. Geçmiş veride işlerin %22,8'i ödenmemiş; sebebi kalemde yazılı
> olmalı ki ay sonunda tartışma çıkmasın.

Montaj kanıtı (fotoğraf, form) iş emrine **dosya eki** olarak yüklenir.

### 2.2 Ay sonu hak edişi (Hak Ediş)

1. **Hak Ediş → Dönem seç** (`2026-09`) → *Dökümleri oluştur*
   Her montaj noktası için bir döküm çıkar; ödenebilir kalemler satıra döner,
   ziyaret başına bir `YOL_KM` satırı eklenir.
2. Kesinti gerekiyorsa satır olarak girin (negatif katkı).
3. **Onaya gönder** → yetkili onaylar → **PDF'i e-postala**.
4. Ödeme yapılınca **Ödeme kaydet** (tarih, tutar, dekont) → döküm `ODENDI`
   olur ve **satırlar kilitlenir**.

> **Kapanmış dönem değişmez.** Hata bulunursa eski satır düzeltilmez;
> düzeltme **sonraki döneme ayrı bir satır** olarak girer (gerekçesiyle).
> Kilidi kırmanın yolu yoktur — denetim izi ancak böyle anlamını korur.

Dönem, işin tarihinden **bağımsızdır**: Mart'ta yapılan bir iş Nisan hak
edişinde ödenmiş olabilir. `settlement_period` ödemeyi, `completed_at` işi
gösterir.

### 2.3 Teklif → sipariş → sevkiyat

1. **Teklifler → Yeni**: müşteri, kalemler, iskonto, geçerlilik tarihi.
   – İskonto eşiği aşılırsa teklif `ONAY_BEKLIYOR` olur; satış müdürü
   onaylamadan gönderilemez.
2. **Gönder**: PDF üretilir, e-postayla gider, müşteriye özel bir bağlantı
   oluşur. Müşteri bağlantıyı açtığında teklif `GORUNTULENDI` olur.
3. Müşteri bağlantıdan **kabul** ya da **red** (nedeniyle) işaretler; karar
   tarih-saatiyle kaydedilir. Telefonla gelen kararı ekip elle işaretler.
4. **Siparişe dönüştür** → IMEI **rezervasyonu** (adet değil, tek tek cihaz:
   "bu IMEI kime söz verildi" baştan bellidir) → **sevkiyat** rezervasyonu
   tüketir ve stok konumunu değiştirir.

Fiyat, KDV ve iskonto belgeye **dondurulur**: parametreler sonradan değişse
de gönderilmiş teklif değişmez.

### 2.4 Abonelik ve tahsilat

- **Abonelikler**: sözleşme, periyot, taahhüt, yenileme. Ücret **tarihlidir**;
  zam geçmişi bozulmaz.
- Aylık tahakkuk **hesaplanır, saklanmaz** — aynı dönem her zaman aynı sonucu
  verir. `Tahakkuk → Excel` ile alınır.
- Ay ortası başlayan/biten abonelikte **gün bazlı kıst** uygulanır. Tam ay
  aktifse oran uygulanmaz (31/31 çarpımı kuruş kaydırırdı).
- **Tahsilat**: hangi abonelik/sipariş için ne zaman ne kadar ödendi.
  Hesap bazında bakiye = ERP'nin bildiği tahakkuk − tahsilat.

> Buradaki bakiye **resmî cari hesap değildir** — o Logo'dadır. Bu rakam
> tahsilat takibi içindir ve ekranda da böyle yazar.

Gecikenler listesi abonelik **askıya almayı önerir, kendiliğinden yapmaz**:
ödeme banka ekstresine ERP'den önce düşer ve çalışan bir müşterinin takibini
yanlışlıkla kesmek, gecikmiş tahsilattan pahalıya gelir.

### 2.5 Toplu zam (Abonelikler → Toplu fiyat güncelleme)

**Önizle → onayla → bildir.** Ölçütler partiye yazılır ve uygulama anında
yeniden okunur. **Taahhütlü sözleşmeler otomatik hariç tutulur.** Yürürlüğe
girmemiş bir parti bütünüyle geri alınabilir; yürürlüğe girmiş parti geri
alınamaz.

### 2.6 Hatlar (SIM)

Hat maliyeti tek bir sayı değildir: tarife + veri paketi + APN. İndirim
**taahhüde bağlıdır** ve bitişinde maliyet birkaç katına çıkar. Hatlar ekranındaki
**Taahhüdü bitenler** düğmesiyle bu listeyi düzenli kontrol edin — yüzlerce hat aynı
anda pahalılaşabilir.

### 2.7 RMA / Servis

Kayıt açılırken garanti durumu hesaplanır ve **karara dondurulur**: garanti
tarihi sonradan düzeltilse bile açılmış kaydın kararı değişmez.

Üç değer vardır: **garanti içi**, **garanti dışı**, **belirsiz**. "Belirsiz",
cihazın ilk aktivasyon tarihinin bilinmediği anlamına gelir — ücret kararını
elle verirsiniz. Garanti içi kayda müşteri bedeli yazılamaz.

Değişimde araç, hat ve müşteri bağı yeni IMEI'ye taşınır; eski–yeni ilişkisi
saklanır ve model bazında arıza oranı buna dayanır.

### 2.8 Satın alma ve ithalat

- Sipariş → **mal kabul** (IMEI listesi stoğa girer) → kısmi teslim.
- İthalat dosyası verilirse cihazlar **ITHALATTA** doğar: gümrükteki mal
  fiziksel olarak stokta değildir ve rezerve edilebilir görünmemelidir.
- **Landed cost** dağıtım anahtarı seçilir: tutar / adet / ağırlık. Navlun
  ağırlıkla, gümrük vergisi mal bedeliyle, müşavirlik adetle orantılıdır.
  Yuvarlama artığı son cihaza yazılır; **dosya toplamı = cihaz maliyetleri
  toplamı**.
- **BTK**: ithal cihaz `BEKLIYOR`, yurt içi alım `GEREKMIYOR` doğar. Bekleyen
  listesi ve BTK'ya sunulacak Excel bu ekrandadır.

---

## 3. Toplu içe aktarma (İçe Aktarma)

Excel/CSV ile toplu veri girişi. **Dokuz profil** vardır:

| Profil | Ne aktarır |
|---|---|
| Hesap | Müşteri, bayi, montaj noktası, tedarikçi (e-posta, IBAN dahil) |
| Cihaz | Toplu IMEI / seri no |
| Hat | Toplu SIM (ICCID, MSISDN, paket, taahhüt) |
| Araç | Plaka, şase, müşteri |
| Tarife | Montaj noktası tarifeleri (tarihli) |
| Abonelik | Sözleşme ve ücret |
| Cihaz–Hat | **IMEI ↔ SIM eşleştirmesi** |
| Cihaz–Araç | **Montaj geçmişi** (IMEI ↔ plaka, tarihli) |
| Cihaz zimmet | Kimde/nerede (konum ve sahiplik geçmişi) |

Akış her zaman aynı: **oku → önizle → uygula.**

- **Dosya yüklemek hiçbir şey yazmaz.** Önce okunur ve doğrulanır; ne
  gireceğini, neyin hata verdiğini ve neyin zaten kayıtlı olduğunu
  gördükten sonra onaylarsınız.
- Başlık satırı sayfanın herhangi bir yerinde olabilir (bazı tedarikçi
  dosyalarında 9. satırdadır).
- **Boş şablon indirilebilir** — sütun adlarını tahmin etmeyin.
- Hatalı satırlar **karantina raporuna** düşer; rapor ham sütunları taşır.
  Excel'de düzeltip aynı ekrandan geri yükleyin.
- Aynı dosyayı ikinci kez uygulamak yeni satır üretmez.
- Karar verilmeyen çakışmalı satır **atlanır**; üzerine yazılmasını
  istiyorsanız satırda "Güncelle" seçin.

> **Montaj içe aktarımı hak ediş satırı ÜRETMEZ.** Geçmiş montaj verisini
> yüklemek para hesaplamaz; hak ediş yalnız iş emri akışından doğar.

---

## 4. Raporlar ve panel

**Panel** ("/"): sahadaki/stoktaki cihaz, ayın montajı, stok değeri, MRR/ARR,
churn, bekleyen teklif ve hak ediş; altında ödemesi gecikenler ve yaklaşan
yenilemeler.

> "Stok değeri 0" ile "maliyeti girilmemiş" **ayrı** gösterilir. İkisini aynı
> saymak stoğu olduğundan değersiz gösterirdi.

**Raporlar** sekmelerinde: montaj noktası performansı, müşteri geliri,
hareketsiz stok, bayi stoğu, teklif dönüşümü, MRR/churn, cihaz ömür boyu.
Her rapor aynı veriden **Excel** olarak da alınır — ekranda gördüğünüz ile
indirdiğiniz rakam aynıdır.

Birkaç okuma notu:

- **Teklif dönüşümü**: cevap bekleyen teklifler paydaya girmez. Onları
  "kaybedilmiş" saymak oranı haksız yere kötü gösterirdi.
- **Cihaz ömür boyu**: tek seferlik maliyeti kaç ayda çıkardığını söyler.
  Aylık marj sıfır ya da eksiyse cihaz kendini **hiç** amorti etmiyordur.
- **Arıza oranı** (RMA ekranında): payda o modeldeki **toplam** cihazdır.
  Yalnız arıza sayısı listelemek çok satan modeli haksız yere kötü gösterirdi.

---

## 5. KVKK

Yalnız sistem yöneticisi görür. Üç sekme:

- **Veri bulma** — bir kişiye ait tüm kayıtlar (unvan, ad, telefon, e-posta
  ya da plakadan). Talep sahibine verilecek döküm Excel olarak alınır.
  **Bu aramanın kendisi de kişisel veri erişimidir ve loglanır.**
- **Saklama süresi** — süresi dolmuş, hareketsiz müşteri hesapları
  **listelenir**. Otomatik hiçbir şey silinmez; karar insana aittir.
- **Erişim logu** — kişisel veriyi kimin, ne zaman, hangi amaçla gördüğü.

### Anonimleştirme

Silme talebinde kayıt **silinmez, anonimleştirilir**. Kaydı silmek iş
geçmişini de silerdi: bir aracın hangi cihazı taşıdığı ticari kayıttır.

- Maskelenen: unvan, telefon, e-posta, VKN, IBAN, kişi adları, plaka, şase.
- Korunan: cihaz zaman çizelgesi, iş emirleri, hak ediş kayıtları.
- **Geri alınamaz.** Gerekçe (silme talebi referansı) ve onay kutusu
  zorunludur; işlemi yapan kullanıcı denetim izine yazılır.

---

## 6. Görevler (pano)

**Görevler** ekranı bir kanban panosudur: kolonlar ve kolonlara dizilmiş
kartlar. Kart sürüklenerek kolon değiştirir.

### Pano

Birden çok pano açabilirsiniz — "Montaj Planı", "Ay Sonu Kapanışı", "Satış
Takibi" gibi. Yeni pano açıldığında **Yapılacak / Devam ediyor / Bitti**
kolonları hazır gelir; **Kolon ekle** ile yenisini ekler, boş bir kolonu
başlığındaki **×** ile kaldırırsınız.

Bir kolona **kart sınırı** koyabilirsiniz. Sınır aşıldığında iş engellenmez,
kolonda "iş yığılıyor" uyarısı çıkar: sert kural işi durdurur, uyarı
düşündürür.

**Bitiş kolonu** yeşil rozetle işaretlidir. Kart oraya ilk düştüğünde
tamamlanma tarihi damgalanır ve kartın üstü çizilir. Kart geri çekilse bile
"ne zaman bitmişti" bilgisi kalır.

Biten panoyu **silmeyin, arşivleyin**. Arşiv listeden kaldırır ama kartları ve
geçmişi korur; **Arşivi göster** düğmesiyle geri çağırır, **Arşivden çıkar**
ile listeye alırsınız.

**Sil** düğmesi yalnız BOŞ panoda çalışır ve geri alınamaz. Kartlı pano
silinemez: o işlerin geçmişini de silerdi.

### Kart

İki yol var:

- **Hızlı:** kolonun altındaki kutuya başlık yazıp Enter. Sonra karta tıklayıp
  ayrıntıyı doldurursunuz.
- **Tam:** kolon başlığındaki **+** düğmesi bütün alanlarla bir pencere açar.

Kartın alanları: **konu başlığı, açıklama, ilgili kişiler (birden fazla),
etiketler, termin (deadline), öncelik** ve isterseniz bir **ERP kaydı**.

Termin geçmişse ve kart bitmemişse tarih **kırmızı** görünür.

Yorumlar **düzenlenemez ve silinemez** — "neden böyle karar verildi"
sorusunun cevabı çoğu zaman orada duruyor.

### İlgili kişiler ve etiketler

Bir karta **birden fazla kişi** eklenebilir: bir montajda koordinatör,
tekniker ve satış temsilcisi aynı anda ilgili olabiliyor.

**Etiketler pano başına** tanımlıdır. Yeni pano Trello'daki gibi altı adsız
renkle gelir; üstteki **Etiketler** düğmesinden adlandırır, rengini
değiştirir ya da yenisini eklersiniz. Ad zorunlu değil — adsız etiket yalnız
renk olarak durur. Etiketi silmek kartlardan düşürür, **kartları silmez**.

### Kartı bir ERP kaydına bağlamak

Kart tek başına da durabilir ("Vergi levhalarını topla"), bir kayda da
bağlanabilir: iş emri, teklif, sipariş, RMA, hesap, cihaz, araç, hat ya da
hak ediş dökümü. Bağlamak için kart panelindeki **Kayıt tipi** ve **Kayıt no**
alanlarını doldurun.

Bağlı kartta kaydın adı mavi bir etiket olarak görünür ve tıklanınca o kayda
gider. Kaynak kayıt sonradan silinmişse etiket **kırmızı** olur ve "kaynak
kayıt silinmiş" der — kart kaybolmaz, durumu söyler.

Ters yönde de çalışır: hesap kartındaki **Görevler** sekmesi o hesaba bağlı
görevleri listeler ve oradan yeni görev eklenebilir.

### Kim görür

`gorev.gor` izni olan panoları görür, `gorev.yaz` izni olan değiştirir.
Yönetim rolü panoları görür ama değiştiremez.

**Dikkat:** pano kayıt kapsamına bakmaz. "Yalnız kendi müşterileri"
kapsamındaki bir satış temsilcisi, başkasının müşterisine bağlı bir kartın
BAŞLIĞINI görebilir. Kaydın kendisini açamaz — kayıt ekranları kendi
kontrolünü yapar — ama kart başlığına müşteri adı yazarken bunu bilin.

---

## 7. Kullanıcılar, roller ve izinler

**Kullanıcılar** ekranında iki sekme var: *Kullanıcılar* ve *Roller*.

### Yeni kullanıcı açarken

Rol seçtiğiniz anda altta **erişebileceği sayfalar** ve **izin verilen
aksiyonlar** listelenir. Rol seçimini kör yapmayın: burada gördüğünüz, o
kişinin ilk günden yapabileceklerinin tamamıdır.

"Yalnız kendi müşterileri" kapsamındaki bir rolde (Satış Temsilcisi) kullanıcı,
temsilcisi olmadığı hesapları ve onlara bağlı araç, cihaz, iş emrini hiç
göremez — menü açık olsa bile liste boş gelir.

### Rolü düzenlemek

*Roller* sekmesinde **Düzenle** ile rolün adını, kapsamını ve izinlerini
değiştirebilir, **Yeni rol** ile kendi rolünüzü tanımlayabilirsiniz (örn.
"Bölge Müdürü").

Üç şeyi bilerek yapın:

1. **Rol değişikliği o roldeki HERKESİ etkiler.** Pencere kaç kişi olduğunu
   önden söyler.
2. **Açık oturumlar düşer.** Eski yetkiyle açılmış bir oturum yeni kısıtı
   görmezdi; etkilenen kullanıcılar yeniden giriş yapar.
3. **Düzenlediğiniz rol bir daha kendiliğinden güncellenmez.** Sürüm
   yükseltmesiyle gelen YENİ izinler o role inmez; sunucu günlüğüne uyarı
   düşer ve izni buradan elle vermeniz gerekir.

Sistem rolleri silinemez (kod onları yeniden açar), kullanıcısı olan özel rol
de silinemez — önce o kişileri başka bir role taşıyın.

### Tek bir kişi için istisna

Kullanıcı düzenleme penceresindeki **"Bu kullanıcıya özel istisnalar"**
bölümü, rolün üstüne biner: bir izni *ek olarak verir* ya da *geri alır*.
Her istisna **gerekçe ister** — aynı roldeki iki kişinin neden farklı şey
gördüğü altı ay sonra da okunabilmeli.

İstisnayla verilen izinler üstteki listede turuncu **istisna** etiketiyle
görünür. Kaydetmek o kullanıcının açık oturumlarını düşürür.

Kural: **önce rol, istisna son çare.** Birkaç kişide aynı istisna birikiyorsa
orada aslında yeni bir rol vardır.

Kimse **kendi** izinlerini değiştiremez; yönetici kendini kilitleyebilir ya da
sessizce yetkisini yükseltebilirdi.

### Kilitli hesap

Beş hatalı parola denemesi hesabı kilitler ve kilit **kendiliğinden açılmaz** —
listedeki **Kilidi aç** düğmesiyle yönetici açar. Süreli kilitte saldırgan
bekleyip kaldığı yerden devam edebilirdi.

---

## 8. Parametreler ve denetim izi

**Parametreler**: KDV, stopaj, damga oranları, iskonto onay eşiği, kota
uyarısı, garanti süresi, ödeme gecikme eşiği, KVKK saklama süresi, SMTP,
Logo dışa aktarım şablonu, şirket künyesi.

Oran değişikliği **geçmiş belgeleri etkilemez** — her belge kendi oranını
içinde saklar.

**Denetim İzi**: kim, ne zaman, hangi kaydı, neyden neye değiştirdi. Silme
işlemleri yumuşaktır (`is_deleted`); kayıt kaybolmaz.

---

## 9. Sık karşılaşılanlar

| Durum | Anlamı / yapılacak |
|---|---|
| "Bu kaydı başka biri değiştirdi" | Sayfayı yenileyin, değişikliğinizi tekrar uygulayın. Bu uyarı veri kaybını önler. |
| Menüde bir modül yok | Yetkiniz yok. Sistem yöneticisine başvurun. |
| Maliyet alanı "gizli" | `maliyet.gor` yetkiniz yok — yalnızca Yönetim, Satış Müdürü, Muhasebe ve Admin görür. |
| Cihaz kaydedilmiyor: "IMEI zorunlu" | Ürün kartı `IMEI` kimlik tipinde. Ek kameraların IMEI'si **yoktur**, onlar `SERI_NO` tipindedir. |
| Garanti durumu "belirsiz" | Cihazın ilk aktivasyon tarihi bilinmiyor. Ücret kararını elle verin. |
| Hak ediş satırı kilitli | Dönem `ODENDI`. Düzeltme sonraki döneme ayrı satır olarak girilir. |
| Teklif gönderilemiyor: iskonto | Eşik aşıldı; satış müdürü onayı gerekiyor. |
| Müşteri teklif linkini açamıyor | Bağlantı `PUBLIC_BASE_URL` üzerinden üretilir; sunucu adresi değiştiyse eski linkler çalışmaz. |
| İçe aktarmada "çakışma" | Kayıt zaten var. Satırda "Güncelle" seçmezseniz atlanır. |
| Excel'de IMEI `8.63071E+14` görünüyor | Excel'in bilimsel gösterimi. Sütunu **metin** yapın; ERP bu biçimi ayrıca tanır ve düzeltir. |

---

## 10. Neler kapsam dışı

Bunlar eksiklik değil, **karar**:

- **Mobil saha uygulaması yok** — işler ofisten girilir, kanıt dosya ekidir.
- **Konsinye yok** — bayi satışı peşindir.
- **Genel muhasebe yok** — resmî defter Logo'dadır; ERP tahsilat takibi yapar
  ve Logo kolon düzeninde Excel üretir.
- **Müşteri portalı yok** — müşteri yalnız kendi teklif bağlantısını görür.
- **Takip platformuna otomatik aktivasyon yok** — montaj tamamlanınca
  platformda **elle** aktive edilir. Platform tarafı yazıldığında bu
  kendiliğinden devreye girer; ERP o ana kadar bekleyen işlemleri biriktirir,
  atmaz.
