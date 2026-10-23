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

Teknik servis modülleriyle sekiz rol daha gelir. Hiçbirinde mobilite iş emri,
hak ediş, tahsilat ya da maliyet yetkisi yoktur; "Teknik Servis" (mobilite
RMA/garanti rolü) bunlardan ayrıdır ve aynen kalır.

| Rol | Ne yapar | Gördüğü kayıtlar |
|---|---|---|
| Teknik Servis Müdürü | Servis işinin tamamı, tanımlar, bakım, atölye, kiralama, parça, eğitim, personel, servis raporları | Tüm birimler |
| Teknik Servis Şefi | Planlama, onay, kapatma, bakım onayı, servis raporları | Kendi birimleri |
| Teknik Servis Operasyon Uzmanı | İş açma, uzaktan çözüm, kiralama kaydı | Kendi birimleri |
| Servis Teknisyeni | Benim İşlerim: sayaç, sonuç, fotoğraf, parça kullanımı | Yalnız kendisine atanmış işler |
| Atölye Kabul / Usta | Atölye kabulü, onarım, teslim | Kendi birimleri |
| Servis Deposu / Yedek Parça | Parça stoğu, transfer, sayım, talepler | Kendi birimleri |
| Kiralama Deposu | Kiralık envanter, tahsis, sevk, iade | Kendi birimleri |
| İnsan Kaynakları / Eğitim | Personel, işten çıkış, eğitim ve belge | Tüm birimler |

"Birim" Güvenlik, Haberleşme, POC, Mobilite, Araç Takip gibi iş kollarıdır;
kişinin birimleri **Personel** kartında verilir (§11.8, §12.2). Servis
modülleri önce pilot birimde (Güvenlik) açılır; servis rolü olmayan
kullanıcının menüsü değişmez.

Bu roller kurulumla gelir; **düzenlenebilir** ve yenisi tanımlanabilir
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
işlemleri yumuşaktır (`is_deleted`); kayıt kaybolmaz. Denetim satırının
kendisi **silinemez ve değiştirilemez** — veritabanı da reddeder, yönetici
dahil (§13.1).

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

- **Ayrı mobil saha uygulaması yok** — mobilite montajları ofisten girilir,
  kanıt dosya ekidir. Teknik servis teknisyeni ise aynı ERP'yi telefondan
  **Benim İşlerim** ekranıyla kullanır (aşağıda); kurulacak ayrı uygulama,
  çevrimdışı çalışma ve GPS konum kaydı yoktur.
- **Konsinye yok** — bayi satışı peşindir.
- **Genel muhasebe yok** — resmî defter Logo'dadır; ERP tahsilat takibi yapar
  ve Logo kolon düzeninde Excel üretir.
- **Müşteri portalı yok** — müşteri yalnız kendi teklif bağlantısını görür.
- **Takip platformuna otomatik aktivasyon yok** — montaj tamamlanınca
  platformda **elle** aktive edilir. Platform tarafı yazıldığında bu
  kendiliğinden devreye girer; ERP o ana kadar bekleyen işlemleri biriktirir,
  atmaz.

### 10.1 Benim İşlerim — teknisyenin telefon ekranı (teknik servis)

Menü: **Teknik Servis → Benim İşlerim** (`zaman.yaz` izni). Saha teknisyeni
giriş yaptığında doğrudan bu ekran açılır. Telefonda tarayıcıdan kullanılır;
ayrı uygulama yoktur.

- **İşlerim:** size atanmış açık işler Geciken / Bugün / Yarın / Sonraki günler /
  Plansız gruplarında. Aynı gün aynı tesise gidilecek işler tek **ziyaret
  kartında** toplanır (ör. 17 cihazlık bakım); her iş ayrı açılır. Şef ve
  müdür "Tümü (birimim)" görünümüne de geçebilir.
- **İş kartı:** adres (Haritada aç yalnız dokununca), saha yetkilisi (telefona
  dokununca arar), seri, plan ve ulaşım notu, süre durumu, fotoğraf ekleme
  (kamera açılır), Sonuç Gir ve bakım işinde Bakım Formu. Fiyat görünmez.
- **Sayaç:** "Yola Çıktım" yol süresini, "Sahaya Vardım" saha süresini başlatır
  ve işin durumunu kendiliğinden Yola Çıkıldı / Sahada yapar. Açık sayaç
  varken Mola, Bekleme (neden seçilir), Devam, Sonraki Cihaza Geç ve Bitir
  çıkar. Saat **sunucudan** alınır; telefon saati yanlış olsa da süre doğrudur.
  - Bir kişinin aynı anda tek sayacı olur; başka işte sayaç açıkken yenisi
    başlamaz ("Önce açık sayacı bitirin: SRV-…").
  - **Mola kişi-saate girmez.** Sahada beklemek (Bekleme) kişi-saate girer ama
    işi beklemeye almaz.
  - Yanlış başlattıysanız ilk **5 dakikada** "Yanlış başlattım" ile geri alın.
  - Sayacı kapatmayı unuttuysanız **Unuttum** ile gerçek bitiş saatini ve
    gerekçeyi girin; kayıt "düzeltilmiş" olarak işaretlenir. Sayaç kendiliğinden
    kapanmaz; 10 saati aşan ya da dünden kalan sayaç şefe ve size uyarı verir.
  - Açık sayaçlı iş tamamlanamaz ve iptal edilemez; açık sayaçlı kişi ekipten
    çıkarılamaz. Önce sayacı bitirin.
- **Bugünüm:** günün bölümleri, toplam kişi-saat (mola ayrı ve hariç) ve gün
  sonunda **süre kaydı eksik** işler. Eksik işte "Elle gir" ile süreyi
  sonradan girersiniz. Kayıt yoksa ekranda "Süre kaydı eksik" yazar, **0 dk
  yazılmaz**.
- **Elle süre:** kendi adınıza en çok 2 gün geriye girebilirsiniz; bitişi 30
  dakikadan eski kayıtta gerekçe zorunludur. Daha eskisini ve başkası adına
  kaydı şef/müdür (`servis.planla`) girer; yanlış kaydı da gerekçeyle iptal
  eder (kayıt silinmez, iptal olarak görünür).
- **Bağlantı yoksa** düğmeler kilitlenir: "Bağlantı yok — süreyi sonra elle
  girin". Çevrimdışı basış biriktirilmez.

## 11. Teknik servis — Dalga 2 ekranları

> Menü kalemleri yalnız izni olan kullanıcıya görünür; mobilite
> kullanıcısının menüsü değişmez.

### 11.1 Operasyon Merkezi ve SLA

Menü: **Teknik Servis → Operasyon Merkezi** (`operasyon.gor`). SLA tanımları
ve bekleme nedeni kataloğu **Servis Tanımları** ekranındadır
(`operasyon.yonet`). SLA hedefi işe açılışta damgalanır; SLA durumu yalnız
sunucuda hesaplanır.

- **SLA politikası:** varsayılan çözüm hedefleri KRİTİK 12, YÜKSEK 24,
  NORMAL 72 saattir (7/24). Hedef, SLA yürürlük anı ayarı girildikten sonra
  açılan işlere damgalanır; planlı bakım ve atölye işleri SLA dışıdır (PB'de
  vade ayı görünür). İş beklemesi (müşteri onayı, malzeme gibi) hedefi ileri
  alır; personel beklemesi almaz. Öncelik ya da tür değişince hedef yeniden
  damgalanır. Sonuç işin ilk *Tamamlandı* anında donar.
- **Operasyon Merkezi:** üstteki sayaçlar tıklanınca aynı sayıda satırlık
  listeyi SLA sırasıyla açar; birim ve öncelik süzülür. Toplu atama ve toplu
  plan servis işleri ekranındaki aynı işlemlerdir. *Personel iş yükü*
  sekmesinde çalışılan dakika yalnız `servis_rapor.personel` sahibine görünür.
- **Bildirimler:** SLA uyarıları kalıcıdır ve rozet sayısı anlık hesaplanır;
  *Görüldü* işareti kişiseldir.
- **SLA kartı:** servis işi detayındaki etiket ve **SLA kartı** düğmesi
  hedefleri, ilk müdahaleyi ve tekrar arıza adayını gösterir. SLA'sı aşılmış
  işte *gecikme nedeni*, tekrar arıza adayı işte *kök neden teyidi*
  girilmeden iş **Kapatıldı**'ya geçemez; bu bilgi SLA kartından girilir.
  Benim İşlerim ekranında da aynı etiket görünür.

### 11.2 Atölye

Menü: **Teknik Servis → Atölye** (`atolye.gor`, yazma `atolye.yaz`). Her
atölye kaydı bir cihaz ve bir servis işidir; tamir bedeli yalnız maliyet
yetkisi olana görünür (ekranda, Excel'de ve PDF'te).

- **Kabul:** müşteri, cihaz (kütükten seçilir ya da tip + marka + seri ile
  bulunur/açılır), şikâyet ve aksesuarlar girilir. Kabul anı ve durum
  sunucudan gelir. Aynı cihazın açık atölye kaydı varsa kabul reddedilir;
  aynı seriyle birden çok kayıtlı cihaz varsa aday listesinden seçilir.
  Garanti durumu kabulde hesaplanıp dondurulur. *Toplu kabul* aynı
  müşteriden birden çok cihazı tek fişle alır; bir cihaz hatalıysa hiçbiri
  kaydedilmez.
- **Akış:** Kabul → Teşhis (arıza nedeni katalogdan) → gerekiyorsa Onay
  bekliyor (müşteri onayı; bağlı teklifin kabulü onay sayılır) → Onarım →
  Test → Teslime hazır → Teslim edildi. Test *Kaldı* ise teslime
  geçilemez. Teslimde aksesuarlar tek tek işaretlenir; eksik varsa açıklama
  zorunludur. Teslimle servis işi tamamlanır.
- Atölye işinde servis işleri ekranındaki genel durum/bekleme/iptal
  düğmeleri çalışmaz; işlemler atölye ekranından yapılır. Kabul fişi ve
  teslim tutanağı PDF'tir; imzalı tarama servis işinin eki olarak yüklenir.
- **Kiralık cihaz:** kiralamadan arızalı dönen cihaz, dönüş kontrolünde
  *Atölye kaydı aç* seçilirse kiracı adına "Kiralama takip" kaydıyla
  atölyeye girer; atölye teslimi cihazı son deposuna *Kontrolde* döndürür.
- Teslim alan ve onaylayan adları KVKK anonimleştirmesinde silinir.

### 11.3 Kiralama ve kiralık envanter

Menü: **Teknik Servis → Kiralamalar / Kiralık Envanter** (`kiralama.gor`).
Kiralık cihazlar mobilite stoğundan ayrı izlenir; kiralama depoları mobilite
depo listesinde görünmez. Mobilite ve Araç Takip birimlerinde kiralama yoktur.
Kiralama bedeli ERP'de tutulmaz; ekranlarda ve tutanakta fiyat yer almaz.

**Kiralamalar.** Üstteki kutular (Talep, Planlı, Hazırlanıyor, Kirada,
Geciken iade, Eksik tahsis) tıklanınca aynı sayıdaki listeyi açar.
*Yeni kiralama* (`kiralama.yaz`): birim, müşteri/lokasyon, başlangıç ve iade
tarihi, kalemler (yalnız birimin kiralama kataloğundaki ürünler; kalem
satırında seçilen tarihler için müsait adet görünür) ve müşterinin irtibat
kişileri girilir. Kayıt **Talep** olarak açılır ve stok ayırmaz.

Aşamalar sırasıyla kiralama kartındaki düğmelerle ilerler; durum elle
değiştirilmez:

1. **Planla** — tarih aralığında yeterli müsait adet yoksa "X adet eksik"
   uyarısıyla reddedilir.
2. **Tahsis** (`kiralama.envanter`) — seri takipli üründe depodaki *Hazır*
   cihazlar tek tek, toplu üründe depo + adet seçilir. Kısmi tahsis
   yapılabilir; kalem adedi aşılamaz, aynı cihaz tarihi çakışan iki
   kiralamaya verilemez. İlk tahsisle kiralama *Hazırlanıyor* olur. Sevk
   edilmemiş tahsis *Çöz* ile geri bırakılır.
3. **Sevk et** (`kiralama.asama`) — ilk sevkte her kalem tamamen tahsisli
   olmalıdır; sonradan eklenen tahsisler *Ek sevk* ile gönderilir.
4. **Aşama gir** — Kurulum yapıldı / Devreye alındı / Toplandı. Kurulum ya da
   toplama servis işi tamamlandığında kartta önerilen aşama görünür; onay
   yine aşama yetkilisindedir.
5. **İade al** — her tahsis için *Depoya iade* (cihaz seçilen depoya
   *Kontrolde* girer), *Kayıp* ya da *Müşteride (not)*. Kurulumlu
   kiralamada son iadeden önce *Toplandı* girilmelidir. Bütün cihazlar
   dönünce kiralama *Depoya alındı* olur; **Kapat** ile kapanır.

Yanlış girilen son aşama *Son aşamayı geri al* ile gerekçe yazılarak geri
alınır (ters hareket yazılır, kayıt silinmez; kapanmış/iptal kiralamada
yapılamaz). Sevk edilmemiş kiralama gerekçeyle iptal edilir, tahsisler
çözülür. *Servis işleri* sekmesinden kurulum/toplama işi açılır
(`kiralama.yaz` + `servis.yaz`; aynı türde ikinci açık iş açılamaz).
*Teslim tutanağı* ve *İade tutanağı* fiyatsız PDF'tir; sevkten önce
"TASLAK" filigranı taşır.

**Kiralık Envanter.** *Seri cihazlar* sekmesinde cihazlar durum (Hazır,
Kontrolde, Hazır değil, Kirada, Kayıp, Atölyede, Hurda) ve depoya göre
süzülür; *Uzun süredir kontrolde* kutusu uyarı listesini açar. Cihaz
kartında seri no, eksik notu ve not düzeltilir; durum, depo ve ürün
yalnız işlemlerle değişir. Seçili cihazlar için *Dönüş kontrolü*
(Uygun → Hazır; Eksik/Arızalı → Hazır değil, açıklama zorunlu),
*Transfer*, *Bulundu* (kayıp cihaz depoya *Kontrolde* döner) ve
*Hurdaya ayır* (gerekçeli çıkış) yapılır. Seri takipsiz ürünler için aynı
işlemler üst sağdaki düğmelerle ürün + depo + adet girilerek yapılır.
*Excel'den toplu giriş* önce önizleme gösterir, hiçbir şey yazmaz; onayda
yalnız hatasız satırlar yazılır, dosya arada değiştiyse işlem reddedilir.
Hareket defteri silinmez ve düzenlenmez. *Kiralama kataloğu* sekmesinde
ürünler birime bağlanır ya da pasifleştirilir; IMEI'li ürün kataloğa
alınamaz, envanteri olan ürünün seri takibi ürün kartında değiştirilemez.

### 11.4 Yedek parça

Menü: **Teknik Servis → Yedek Parça** (`parca.gor`). Parça çıkışı açık servis
işine yapılır; düzeltme silme değil ters kayıttır.

- **Sekmeler:** Stok, Hareketler (belge no ile arama, Excel), Talepler,
  Sayım, İş Emri Parçaları, Depolar (depo tanımı `sistem.ayar`). Üstteki
  kutular tıklanınca aynı sayıda satırlık listeyi açar.
- **Çıkış ve iade:** stok yetmezse çıkış reddedilir (stok eksiye düşmez);
  kapalı işe çıkış yapılamaz. İade, işe yapılan net çıkışı aşamaz. Servis
  işi detayının **Parçalar** sekmesi, bakım formu ve atölye kaydı aynı
  parça bölümünü gösterir. Maliyet sütunları yalnız `maliyet.gor` sahibine
  görünür.
- **Transfer ve sayım:** transfer iki depoyu birlikte yazar. Sayım açıldığı
  anın stoğunu saklar; onay anında stok değişmişse fark gösterilir ve
  onaylayan değişimi kabul eder. Onaylanmayan sayım stoğu değiştirmez.
- **Parça talebi:** işe parça talebi açılırken iş *Malzeme* beklemesine
  alınabilir; talepten sonraki çıkışla talep karşılanır ve bekleme biter. İş
  kapanınca açık talepler iptal olur.
- **Açılış stoğu:** **İçe Aktarma** ekranındaki "Parça açılış stoğu"
  profiliyle yüklenir; hatalı tek satır varsa hiçbir satır yazılmaz.
- Mobilite stok ekranları servis ve kiralama depolarını göstermez.

### 11.5 Servis teklifi ve maliyet

Servis teklifleri **Teklifler** ekranında birimli teklif olarak durur (iç
onaydan geçer); maliyet ve gelir **Teknik Servis → Servis Maliyet**
ekranındadır (`maliyet.gor`).

- **Servis teklifi:** servis işi detayındaki **Teklif hazırla** düğmesi
  teklif formunu işin müşterisi ve adresiyle açar. Birimli teklif önce iç
  onaya gönderilir (hazırlayan kendi teklifini onaylayamaz), onaydan sonra
  e-postayla (en çok 3 alıcı, gönderene kopya) ya da *Elle gönderildi*
  (kanal + not) olarak gönderilir. Servis teklifi siparişe dönüşmez; satış
  panel ve raporlarında sayılmaz. Kabul edilen teklifin KDV hariç tutarı
  işin geliri olarak yazılır.
- **Servis Maliyet:** dönem/birim/tür/müşteri süzgeci, eksik veri kutuları
  (süre eksik, tarife eksik, maliyet eksik) ve birim × tür özeti. Gelir
  girilmemiş iş ile ücretsiz (garanti) iş ayrı tutulur. Fatura devrinden
  sonra gelir değiştirilemez. *İşçilik tarifeleri* sekmesinde tarife eklenir;
  geçmiş tarihli tarife `sistem.ayar` ve gerekçe ister. Analiz sekmesi
  `servis_rapor.gor` da ister.

### 11.6 Eğitim ve Gelişim Kartım

Menü: **İnsan Kaynakları → Eğitim ve Gelişim** (`egitim.gor`) ve **Gelişim
Kartım** (`egitim.kendim`). Kayıt ve düzeltme `egitim.yaz`, saha gözlemi ve
yetkinlik değerlendirmesi `egitim.gozlem`, not/kanıt gibi kişisel ayrıntılar
`egitim.detay` ister. Kişi listesi yalnız kapsamınızdaki personeli gösterir.

- **Özet:** üstteki kutular tıklanınca aynı sayıda satırlık listeyi açar.
  Henüz verisi olmayan kutu (ör. hiç belge girilmemişse) "0" olarak değil,
  hiç gösterilmez.
- **Katalog ve yıllık plan:** kurs ve kriterler silinmez, pasiflenir; pasif
  kursa plan veya oturum açılamaz. Toplu plan aynı kişi + kurs + yıl için ikinci
  plan üretmez; iptal edilen planın yerine yenisi açılabilir. Erteleme eski
  tarihi saklar. Plan listesi Excel olarak indirilebilir (indirme denetime
  yazılır).
- **Oturum ve katılım:** ileri tarihli oturum açılamaz. Katılım işlenince
  kişinin o kurstaki en eski açık planı tamamlanır; "katılmadı" düzeltmesi planı
  yeniden açar. Toplu katılım tablosunda tek bir hatalı satır varsa hiçbir satır
  yazılmaz ve hatalı satır gösterilir. Katılımı olan oturum silinemez.
- **Saha gözlemi:** servis işinin **Saha Gözlemleri** sekmesinden de açılır;
  birim işten alınır, kişi kendi kendini gözleyemez. Puan ve sonuç sunucuda
  hesaplanır: kritik maddede 0 → KRİTİK, gerekçeli "gözlenmedi" → EKSİK GÖZLEM,
  %85 ve üstü → BAŞARILI, altı → GELİŞİM GEREKLİ. KRİTİK sonuç bir düzeltici
  faaliyet açar; kişinin aynı kurstaki kritik maddeleri tam puan aldığı sonraki
  gözlem faaliyeti kendiliğinden kapatır, elle kapanış kanıt ister.
- **Takip ve belgeler:** 30/60/90 gün takipleri ve süresi dolan belgeler hem
  ekranda hem uyarılarda aynı sayıyla görünür; uyarılar birim kapsamına göre
  süzülür.
- **Gelişim Kartım:** teknisyen yalnız kendi planlarını, gözlemlerini (not ve
  aksiyon planı dahil) ve eklerini görür; gözleme "Gördüm" onayı verir. Onay
  geri alınamaz.

### 11.7 Ana veri kalitesi ve eski sistem verisi

Menü: **Teknik Servis → Ana Veri Kalitesi** (`hesap.birlestir`). Eski
sistemden gelen serbest metin müşteri/lokasyon eşleştirmesi burada onaylanır.

- Ekran kaynak bazında eşleşmemiş kayıt sayılarını ve aday listesini
  (Excel) gösterir. Sistem yalnız kesin eşleşmeyi (takma ad, tek hesaba düşen
  unvan) kendisi bağlar; iki hesaba düşen ad ve benzer adlar yalnız öneridir.
- Aday listesi Excel'de `Onay=E` işaretlenip **İçe Aktarma** ekranındaki
  "Müşteri eşleştirme" profiliyle yüklenir; onaylanan satır hesaba takma ad
  ekler. Aynı dosya ikinci kez yüklenince hiçbir şey değişmez.
- Eski zaman kayıtlarındaki personel adları "Ad eşleme" profiliyle (İK
  onayı, `personel.yaz`) kullanıcılara bağlanır. Bakım sözleşmesi teyidi ve
  servis işleri göç profilleri `sistem.goc` ister; göç adımları
  `deploy/KURULUM.md` EK G'dedir.

### 11.8 İşten çıkış ve personel KVKK

Menü: **Personel** kartında **İşten çıkış** (`personel.cikis`).

- Önce önizleme gösterilir: kişinin açık servis işleri, açık sayacı, oturum
  sayısı, eğitim planları ve düzeltici faaliyetleri. Önizleme hiçbir şey
  yazmaz.
- Onayda tek işlemle giriş kapatılır, oturumlar düşer, kişi açık işlerin
  ekiplerinden çıkarılır (atama silinmez, sonlandırılır). İş durumları
  değişmez; sorumlusu kalmayan iş "Atanmamış" listesine düşer. Kişi kendini
  çıkaramaz; son yönetici çıkarılamaz.
- **Açık sayaç kapatılmaz:** uyarı merkezine kritik uyarı düşer ve görev
  panosunda inceleme kartı açılır; o işte kişi sayaç kapanınca ekipten
  çıkarılır.
- Ayrılmış personel `kvkk.yonet` ile **KVKK anonimleştir** penceresinden
  (açık onay + gerekçe) anonimleştirilir: not, e-posta ve iki adımlı giriş
  sırrı temizlenir; ad iş geçmişi için kalır.

## 12. Teknik servis — Dalga 3: e-posta bildirimi, Ekibim, terimler

### 12.1 SLA e-posta bildirimi

Menü: sağ üstteki kullanıcı menüsü → **Bildirim tercihleri** (`servis.gor`).

- İki seçenek vardır: **anlık e-posta** (bir işin SLA çözüm hedefi aşıldığında
  ya da müdahale hedefi geçtiğinde) ve **günlük özet** (her gün ayarlanan
  saatte; varsayılan 07:30). İkisi de başlangıçta kapalıdır.
- Yalnız görme yetkiniz olan işlerin e-postası gelir; biriminiz değişirse
  sonraki e-postalar yeni kapsamınızla hesaplanır. Aynı bildirim size bir kez
  gönderilir.
- E-postada iş no, birim, müşteri unvanı, öncelik, hedef, durum ve ERP
  bağlantısı vardır. **Fiyat, tutar ve iletişim telefonu yer almaz.**
- Hesabınızda e-posta adresi yoksa e-posta gönderilmez (adres Kullanıcılar
  ekranından sistem yöneticisi tarafından girilir).
- Eski sistemden aktarılmış (geriye dönük SLA damgalı) işler için e-posta
  gönderilmez.

Yönetici ayarları: **Operasyon Merkezi → E-posta kutusu** sekmesi
(`operasyon.yonet`).

- Servis e-postası sistem genelinde buradan açılır/kapatılır (ilk kurulumda
  kapalıdır), günlük özet saati ve deneme sınırı (varsayılan 3) seçilir.
- SMTP sunucusu **Parametreler → Bildirim (e-posta)** bölümünde tanımlıdır.
  SMTP tanımlı değilken e-postalar kutuda *Bekliyor* olarak kalır ve deneme
  sayılmaz; tanımlanınca kendiliğinden gönderilir.
- Gönderilemeyen e-posta deneme sınırına ulaşınca *Başarısız* olur; *Son
  hata* sütununda yalnız hata türü ve sunucu:port görünür (parola ya da
  kullanıcı adı asla yazılmaz).
- Kutudaki alıcı adresi kişisel veridir: gönderilmiş/başarısız satırlar 90
  gün (SLA bildirim saklama süresi) sonra, ayrılan personelin satırları hemen
  silinir. Kapanmış bir bildirimin henüz gönderilmemiş e-postası gönderilmez.
- Mesai takvimli SLA bu sürümde yoktur; SLA süreleri 7/24 işler.

### 12.2 Ekibim ve yönetici

Menü: **Personel**.

- Personel kartında **Yönetici** alanı `personel.yaz` ile seçilir. Kişi
  kendisinin ya da kendi astının (dolaylı da olsa) astı yapılamaz; ayrılmış
  personel yönetici seçilemez.
- Listede **Ekibim** işaretlenince yalnız size doğrudan bağlı, çalışan
  personel görünür; *sayaç açık* etiketi kişinin şu an sayacının açık
  olduğunu gösterir.
- **Ekibim yalnız bir süzgeçtir, yetki vermez:** size bağlı olsa da
  biriminiz dışındaki kişi listede görünmez. Yöneticisi kapsamınız dışında
  olan kişide yönetici "Kapsam dışı kişi" olarak görünür.

### 12.3 "Planlı Bakım" ile mobilite "Bakım" iş emri

- **Planlı Bakım** (menü: *Teknik Servis → Planlı Bakım*, iş türü *PB*):
  bakım sözleşmesine bağlı periyodik teknik servis işidir; Servis Paneli ve
  servis raporlarında bu adla geçer.
- Mobilite **İş Emirleri** ekranındaki *BAKIM* işlem tipi araç takip
  cihazlarının saha bakımıdır; hak ediş ve mobilite raporlarında eskisi gibi
  sayılır. İkisi ayrı kayıtlardır ve birbirinin sayılarına karışmaz.

## 13. Dalga 4: güvenlik ve canlıya geçiş

### 13.1 Denetim izi değiştirilemez

Denetim kaydı yazıldıktan sonra **silinemez, değiştirilemez**; bunu artık
yalnız uygulama değil veritabanı da reddeder. Tek istisna KVKK
anonimleştirmesidir: kişisel veri içeren denetim satırında eski/yeni değer
"silindi" işaretiyle maskelenir, satırın kendisi (kim, ne zaman, hangi
kayıt) kalır. Silinen bir kullanıcının denetim satırları da kalır; yalnız
"kim" alanı boşalır.

### 13.2 Süreli vekâlet

İzinli olmadığınız bir süre için yetkilerinizin bir kısmını başka birine
**süreli** devredebilirsiniz (`vekalet.ver`; Teknik Servis Müdürü ve sistem
yöneticisi). Vekâlet, alıcının **Personel** kartındaki "Vekâletler" bölümünden
verilir ve iptal edilir.

- Vekâletin başlangıcı ve bitişi zorunludur; en çok **30 gün** sürer. Bitiş
  anında kendiliğinden düşer, ayrıca geri almak gerekmez; erken iptal
  edilebilir. Kendinize vekâlet veremezsiniz.
- Yalnız **kendi kalıcı izinlerinizden** devredebilirsiniz; size vekâletle
  gelmiş bir izni başkasına devredemezsiniz. Bazı izinler (kullanıcı/rol
  yönetimi, KVKK gibi) vekâlete kapalıdır; denenirse reddedilir ve denetime
  yazılır.
- Kişi işten ayrıldığında ona verilen ve onun verdiği vekâletler o anda biter.
- Vekâlet başlayınca ya da bitince alıcının açık oturumu düşer; yeniden
  giriş yaptığında yeni yetkisiyle açılır.
- Kalıcı istisnalar (§7 "Tek bir kişi için istisna") ayrıdır ve aynen
  çalışır; vekâlet onları silmez.

### 13.3 Parola ve giriş

- Yöneticinin size verdiği ya da sıfırladığı parola **geçicidir**: 72 saat
  içinde ve yalnız bir kez girişte geçerlidir. Girişte "Parola değiştir"
  ekranı açılır; kendi parolanızı belirlemeden uygulamaya geçilmez.
- Yeni parola en az 10 karakter olmalı, kullanıcı adınızı ya da adınızı
  içermemelidir. Parolanızı sonradan da değiştirebilirsiniz; değiştirince
  diğer cihazlardaki oturumlarınız kapanır.
- Art arda hatalı girişte hesap kilitlenir. Giriş ekranı kilitli hesapla
  yanlış parolayı ayırmaz (aynı mesaj); giremiyorsanız yöneticinize başvurun.
- Yönetici, **Kullanıcılar → Erişim gözden geçirme** sekmesinden hassas
  yetkili, rolünden farklı, uzun süredir girmeyen ve kilitli hesapları
  görür; gözden geçirdiğini işaretler (işaret denetime yazılır).

### 13.4 Sürüm yükseltmesinden sonra ne değişir

- Servis rolü olmayan kullanıcı için ERP **değişmez**: menü, mobilite iş
  emirleri, hak ediş tutarları ve raporlar aynıdır. Yükseltme öncesi ve
  sonrası hak ediş toplamı kuruşu kuruşuna denetlenir.
- Servis modülleri önce **Güvenlik** biriminde açılır; diğer birimler
  sırayla (Haberleşme/POC, sonra Mobilite/Araç Takip) eski sistemden
  aktarılarak eklenir. Eski sistemden gelen işlerin numarası korunur; SLA'ları
  "ölçülemedi" görünür.
- İlk günlerde otomatik planlı bakım üretimi ve servis e-postası **kapalıdır**;
  yönetici açtığında başlar (§11.1, §12.1).
- Bir sorun çıkar da önceki sürüme dönülürse, yükseltmeden sonra girilen
  servis kayıtları geri alınır. Bu yüzden ilk gün yalnız pilot birim çalışır
  ve yedek saatlik alınır; o gün girdiğiniz kayıtları kâğıt/e-posta ile de
  not edin.
