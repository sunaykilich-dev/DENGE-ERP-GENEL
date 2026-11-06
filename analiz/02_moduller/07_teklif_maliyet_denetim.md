# M07 — Teklif ve İş Bazlı Maliyet / Finansal Görünürlük: Bağımsız Denetim

> **Denetlenen belge:** `analiz/02_moduller/07_teklif_maliyet_tasarim.md`
> **Kaynak:** `kaynak/V1_20_1_orijinal/DengeERP.Api` (salt okunur; hiçbir dosya değiştirilmedi)
> **Tarih:** 21.10.2026
> **Yöntem:** Tasarımdaki her "mevcut durum" iddiası ilgili satır okunarak doğrulandı. Her madde kullanıcı kararlarıyla (kapsam: yalnızca teknik servis; öncelik c→b→a; Logo/Flowick kapsam dışı; fiyat/maliyet API'de gizli; süre kaydı yoksa "eksik", 0 değil) karşılaştırıldı.

---

## 1. Özet

| Sonuç | Adet | Maddeler |
|---|---|---|
| KABUL | 3 | M07-10, M07-13, M07-14 |
| DEĞİŞTİR | 13 | M07-01, 02, 03, 04, 05, 06, 07, 08, 09, 11, 12, 15, 16 |
| RET | 0 | – |
| Eklenen madde | 5 | M07-D01 … M07-D05 |

Tasarım genel olarak kodla tutarlı ve kod satır referansları büyük ölçüde doğru. Ana sorunlar şunlar:

1. **Tüm "403 döner" kabul kriterleri bugünkü kodla sağlanamaz.** Program.cs içinde `AddAuthentication` yok, ancak uçlar `Results.Forbid()` döndürüyor. ASP.NET Core'da kimlik doğrulama servisi kayıtlı değilken `ForbidResult` `IAuthenticationService` bulamaz ve **500** üretir. Tasarımcı bunu görmemiş; M07-D01 olarak eklendi.
2. **İşçilik tarifesi varsayılan olarak 0.** `OpsLaborRates` birimleri yalnızca UnitCode ile, `HourlyCost DEFAULT 0` olarak eklenmiş (ZZ_V120_Operations.sql:27-29). Ayrıca `rates.GetValueOrDefault(w.UnitCode)` (OpsSuite.cs:231) tarifesi tanımsız birime sessizce 0 uygular. Bugün bütün işçilik maliyeti 0 görünüyor. Bu, "eksik ≠ 0" kararının tasarımda atlanan ikinci yüzü (M07-D02).
3. **"Gelir yok" ile "ücretsiz/garanti iş" ayrılamıyor.** `OpsWorkFinancials.Revenue NOT NULL DEFAULT 0` (ZZ_V120_Operations.sql:33). M07-09 bu ayrım olmadan uygulanırsa garanti kapsamındaki işler sürekli "Hesaplanamadı" görünür (M07-D03).
4. **M07-03'teki "iş emri sonucu 'Teklif Sunulacak'" tanımı yanlış yere bağlanmış.** Bu değer iş emrinin değil, planlı bakım formundaki cihaz satırının sonucu (`MaintenanceDeviceItems.ServiceResult`, Program.cs:2457; app.js:603 bakım formu). "1 cihaz = 1 PB iş emri" kararı nedeniyle teklif yine PB iş emrine bağlanabilir, ancak tetik noktası bakım formudur.
5. **M07-16'nın gerekçesi bugün için doğru değil.** `appsettings.json` içindeki `Email:Password` boş. Ortam değişkeni mekanizması (`/etc/dengeerp/dengeerp.env`, `Email__Password`) .NET yapılandırmasında kod değişikliği gerekmeden zaten çalışıyor. Asıl risk, Program.cs:912'deki hata mesajının IT'yi parolayı `appsettings.json`'a yazmaya yönlendirmesi.
6. Birkaç maddede gereğinden fazla mühendislik var: PDF SHA-256, sayfalama, SQL tarafı filtre, ayrı dönüşüm raporu. Teklif hacmi küçük olduğundan (teknik servis, 5 birim) bunlar P3'e indirildi veya sadeleştirildi.

**KRİTİK değerlendirmesi:** Tasarımcıya katılıyorum: bu modülde veri kaybı veya fiyat sızıntısı düzeyinde KRİTİK açık yok. Tek koşullu istisna şu: kullanıcı §5 soru 1'e "teklif tutarı da yalnızca `finance.prices.view` ile görülsün" derse, `GET /api/offers` (Program.cs:790-798), PDF ve Muhasebe görünümü (app.js:1276-1277) KRİTİK sızıntı olur. Bu durumda `app.js:146`'da uygulama açılışında **tüm teklifler tutarlarıyla** yüklendiği de unutulmamalıdır.

---

## 2. Madde bazında kararlar

### M07-01 — Teklif düzenleme ve revizyon → **DEĞİŞTİR, P2**
- **Doğrulama:** Doğru. Yalnızca `POST /api/offers` var (Program.cs:800-859). PUT/DELETE ucu ve düzenleme ekranı yok.
- **Değerlendirme:** Taslak düzenleme gerekli, çünkü bugün yazım hatası için yeni teklif açmak gerekiyor. Revizyon zinciri faydalı, ancak `RootOfferId` ile R0→R1→R2 ağacı küçük bir ekip için ağır kaçabilir. Hangi durumlardan revizyon açılabileceği de belirsiz.
- **Düzeltilmiş tanım:**
  - `PUT /api/offers/{id}` yalnızca Taslak durumunda çalışır. Kalem ekleme, silme ve değiştirme yapılır; toplamlar sunucuda yeniden hesaplanır; M07-07 doğrulamaları uygulanır.
  - Geri çevrilen teklif (M07-02 `return`) Taslak'a döner ve aynı numarayla düzenlenir; revizyon açılmaz.
  - `POST /api/offers/{id}/revise` yalnızca **Müşteriye Gönderildi** veya **Reddedildi** durumunda çalışır. Kabul Edildi, İptal ve Revize Edildi durumlarında 409 döner.
  - Revizyon, kalemleri kopyalayıp `ParentOfferId` ve `RevisionNo` ile yeni Taslak açar. Numara `TKL-YYYYMM-####-R{n}` olur ve eski kayıt "Revize Edildi" durumuna geçer.
  - Detay ekranında önceki ve sonraki revizyon bağlantıları gösterilir. Tam ağaç görünümü gerekmez.
  - **Veri:** `Offers.RevisionNo INT NOT NULL DEFAULT 0`, `Offers.ParentOfferId BIGINT NULL`, `Offers.UpdatedAt`, `Offers.UpdatedByUserId`.
  - **Kabul:** Taslakta fiyat değişince toplam sunucuda yeniden hesaplanır. Onay Bekliyor, Onaylandı veya Kabul Edildi durumundaki teklife PUT isteği 409 döner. Kabul Edildi teklife revise isteği 409 döner. R1 açılınca R0 "Revize Edildi" olur ve PUT isteği 409 döner.

### M07-02 — Onay akışı ve durum geçiş kuralları → **DEĞİŞTİR, P1**
- **Doğrulama:** Doğru ve tasarımda belirtilenden daha ağır.
  - `PATCH /status` (Program.cs:861-881) yalnızca `offers.approve` kontrol ediyor. İzin listesinde `Müşteriye Gönderildi` yok, `Kabul Edildi` var.
  - Arayüz "Onayla" butonunu doğrudan **Taslak** durumunda da gösteriyor (app.js:1214). Bu yüzden "Onay Bekliyor" adımı fiilen kullanılmıyor.
  - `offers.create` sahibi Şef ve Operasyon Uzmanı teklifi **onaya gönderemiyor**: bunun için buton ve yetki yok. Akış bugün bu noktada bloke.
- **Değerlendirme:** Modülün çekirdeği, P1.
  - "Hazırlayan kendi teklifini onaylayamaz" kuralı organizasyon şeması gelmeden kesin kural olarak konmamalı. Küçük birimlerde müdür kendi teklifini hazırlayıp onaylayabilir. Kural ayarla açılıp kapanabilir olmalı; varsayılan değer varsayımdır.
  - Muhasebe ve Genel Koordinatör'ün `offers.approve` yetkisi (Program.cs:3927, 3931) teknik servis onayı için muhtemelen fazladır. Bu madde varsayım olarak §5 soru 2'ye bağlanmalı.
- **Düzeltilmiş tanım:**
  - Mevcut tanım korunur.
  - "Hazırlayan onaylayamaz" kuralı `OfferSelfApprovalBlocked` ayarına bağlanır (varsayılan: açık, varsayım). Admin istisnası geçmişe "öz-onay" notuyla yazılır.
  - Eski `PATCH /status` ucu kaldırılır veya yalnızca yeni geçiş tablosunu çağıran ince bir sarmalayıcı olur.
  - Teklif detay ekranı (kalemler, durum geçmişi, geçerli butonlar) bu maddeye dahil edilir; M07-08'den buraya taşınır.
  - Kabul kriterlerindeki "403", M07-D01 tamamlanmadan sağlanamaz.
  - **Kabul:** Taslak→Kabul isteği 409 döner. Ayar açıkken öz-onay 403 döner. Geri çevirme veya ret işleminde neden boşsa 400 döner. Şef rolü "Onaya Gönder" butonunu görür ve kullanabilir. Her geçiş `OfferStatusHistory` tablosunda kullanıcı, zaman, eski/yeni durum ve nedenle görünür. ValidUntil geçmiş ve gönderilmiş teklif "Süresi Doldu" olarak hesaplanır.

### M07-03 — Teklif ↔ iş emri bağlantısı ve teklif beklemesi → **DEĞİŞTİR, P2**
- **Doğrulama:** Kısmen doğru.
  - app.js:1627 yalnızca oluşturma butonu; OpsSuite.cs:130-159 bekleme mekanizması: doğru.
  - **Yanlış:** app.js:603 bir iş emri sonucu değil, planlı bakım formundaki **cihaz satırı** sonucu (`MaintenanceDeviceItems.ServiceResult`, Program.cs:2457).
  - Bekleme ucu `operations.manage` veya `workorders.edit` istiyor (OpsSuite.cs:133). Teklif hazırlayan Operasyon Uzmanı'nda ikisi de yok; otomatik bekletme bu kullanıcıda yetki hatasına düşer.
  - `release` ucu iş emrindeki **tüm** aktif beklemeleri kapatıyor (OpsSuite.cs:152-153). Teklif kabulü, örneğin "malzeme bekleniyor" gibi başka nedenli bir beklemeyi de kaldırabilir.
- **Düzeltilmiş tanım:**
  - İş emri detayında bağlı teklifler listelenir: no, revizyon, durum. Tutar alanı API'de yalnızca §5 soru 1'de belirlenen izinle döner.
  - **Bakım formunda** cihaz sonucu "Teklif Sunulacak" kaydedilince, `offers.create` sahibi kullanıcıya o PB iş emrine bağlı teklif kısayolu gösterilir.
  - Teklif onaya gönderilirken "iş emrini beklet" seçilirse bekleme **sistem işlemi** olarak açılır (kullanıcının `workorders.edit` yetkisi aranmaz, `offers.create` yeterlidir). Bekleme `OpsHolds.OfferId` ile işaretlenir.
  - Kabulde yalnızca `OfferId` eşleşen bekleme kapatılır. Başka aktif bekleme varsa iş emri Beklemede kalır.
  - Ret veya iptalde bekleme kalır ve iş emrinin birim şefine ERP içi uyarı düşer.
  - Bağımlılık M07-08 değil, M07-02'dir.
  - **Kabul:** İki bağlı teklif iş emri detayında görünür. Operasyon Uzmanı "Beklet" seçerek onaya gönderdiğinde iş emri Beklemede olur. Aynı iş emrinde ayrıca "Malzeme" beklemesi varsa teklif kabulünde iş emri Beklemede kalır. Fiyat izni olmayan kullanıcıda API yanıtında tutar alanı yoktur.

### M07-04 — Kabul edilen teklifin iş gelirine aktarılması → **DEĞİŞTİR, P2**
- **Doğrulama:** Doğru. Teklif ile `OpsWorkFinancials` arasında bağ yok (OpsSuite.cs:246-258).
- **Değerlendirme:** Gelir girişi bugün yalnızca Admin'de bulunan `finance.costs.manage` ile ve `prompt` üzerinden yapılıyor. Bu nedenle gelir pratikte hiç girilmeyecek; otomatik aktarım tahmini farkı anlamlı kılan tek gerçekçi yol. Ancak üç eksik var:
  - (a) Daha önce **elle** girilmiş gelirin üzerine yazılıp yazılmayacağı tanımsız.
  - (b) `Revenue NOT NULL DEFAULT 0` olduğu için "gelir yok" durumu ayrıştırılamıyor (M07-D03).
  - (c) Tasarım metni geçmişi "M07-09" diye anıyor; doğru madde M07-13.
- **Düzeltilmiş tanım:**
  - Teklif Kabul Edildi olunca bağlı iş emrinin geliri, iş emrine bağlı ve kabul edilmiş tekliflerin **KDV hariç net** toplamıyla doldurulur; `RevenueSource='Teklif'` olur.
  - Elle girilmiş gelir varsa (`RevenueSource='Elle'`) **üzerine yazılmaz**. Bunun yerine maliyet ekranında "Teklif tutarı elle girilen gelirden farklı" uyarısı gösterilir.
  - İptal veya revizyonda yalnızca teklif kaynaklı tutar yeniden hesaplanır.
  - İş emrine bağlı olmayan teklifler (kiralama vb.) aktarılmaz.
  - Bağlantı için ayrı tablo yerine `Offers.WorkOrderId` ve durum filtresiyle hesaplama yeterlidir. Ek bağlantı tablosu gerekmez.
  - **Veri:** `OpsWorkFinancials.RevenueSource NVARCHAR(20) NULL`. `Revenue` NULL olabilir hale getirilir (M07-D03).
  - **Kabul:** 10.000 TL + %20 KDV'li teklif kabul edilince gelir 10.000,00 TL olur ve kaynak "Teklif" görünür. Elle gelir varken teklif kabul edilirse elle değer korunur ve uyarı görünür. Teklif iptal edilince teklif kaynaklı gelir geri alınır ve M07-13 geçmişine yazılır.

### M07-05 — Kurumsal ve eksiksiz teklif PDF'i → **DEĞİŞTİR, P1 (hata kısmı) / P2 (kurumsal şablon)**
- **Doğrulama:** Üç hata da doğrulandı:
  - `offer.Items.Take(15)` (Program.cs:3588) 16. ve sonraki kalemleri düşürüyor, oysa toplamlar tüm kalemleri içeriyor.
  - `ToAscii` (3629-3636) Türkçe karakterleri dönüştürüyor, diğer ASCII dışı karakterleri "?" yapıyor. "–" işareti de "?" olur.
  - Tek sayfa yapısı (`/Count 1`, 3605) ve satır kaydırma yok.
- **Değerlendirme:** Müşteriye toplamı tutmayan belge gitmesi veri doğruluğu hatasıdır, P1. Logo, şartlar ve KDV dökümü kurumsal kalite işidir, P2. `PdfSha256` aşırı mühendislik; e-imza veya hukuki ispat gereksinimi yok, P3 veya çıkarılmalı.
  - Kütüphane notu: QuestPDF Community lisansı yıllık cirosu 1 milyon USD altındaki şirketler için ücretsizdir; Denge Elektronik büyük olasılıkla bu sınırın üstündedir ve ücretli lisans gerekir. **PDFsharp/MigraDoc (MIT)** lisans riski olmadan aynı işi görür. Karar İT ile verilmeli.
- **Düzeltilmiş tanım:**
  - **P1:** Tüm kalemler basılır; kalem sayısı fazlaysa yeni sayfaya geçilir. Gömülü TrueType fontla Türkçe karakterler korunur. Uzun açıklamalar satır sarılarak basılır. Her satırda satır net tutarı yer alır. Sayfa altında "Sayfa x/y" bulunur.
  - **P2:** Firma unvanı, adres, vergi bilgisi ve logo; revizyon no; hazırlayan ve onaylayan; ödeme, teslim ve garanti şartları (ayardan okunur); KDV oranı bazında döküm.
  - **P3:** PDF özet değeri (hash) loglama.
  - **Kabul:** 40 kalemli teklifte 40 kalemin tamamı basılır ve satır net toplamı "Ara Toplam − İskonto" ile kuruşu kuruşuna eşittir. "Şişli İletişim Çözümleri – Güç Kaynağı" metni metin olarak kopyalandığında aynen gelir. 500 karakterlik açıklama sayfa dışına taşmaz. PDF `qpdf --check` kontrolünden geçer.

### M07-06 — E-posta gönderiminin tamamlanması → **DEĞİŞTİR, P1 ("Elle gönderildi") / P2 (diğerleri)**
- **Doğrulama:** Doğru.
  - Gönderim yalnızca `Onaylandı` durumunda yapılabiliyor (904).
  - `ex.Message` hem DB'ye (936, 950) hem `Results.Problem(detail: error)` ile istemciye gidiyor (957).
  - SMTP yokken 400 dönüyor (911-912); bu nedenle akış "Onaylandı"da kalıyor ve M07-02'deki müşteri yanıtı adımına hiç geçilemiyor.
- **Değerlendirme:** SMTP olmadan "Elle gönderildi / elden teslim" işaretleme olmadan akış ilerleyemez; bu kısım P1. Yeniden gönderim, en fazla 3 adres, CC ve gönderim geçmişi P2. `PdfSha256` çıkarılır.
- **Düzeltilmiş tanım:**
  - **P1:** `POST /api/offers/{id}/mark-sent` (`offers.send`) yalnızca Onaylandı durumunda çalışır. Kanal (Elden / Kargo / Başka e-posta / WhatsApp) ve not zorunludur. Durum Müşteriye Gönderildi olur, `EmailLogs` tablosuna `Channel` ile kayıt düşer.
  - **P2:** Müşteriye Gönderildi durumunda yeniden gönderim yapılabilir. Alıcı sunucuda `MailAddress` ile doğrulanır; en fazla 3 adres kabul edilir. Gönderen kullanıcı CC'ye eklenir. Hata durumunda istemciye genel mesaj döner; ayrıntı yalnızca sunucu loguna yazılır. Gönderim geçmişi detayda görünür.
  - **Veri:** `EmailLogs.Channel NVARCHAR(30)`.
  - **Kabul:** SMTP ayarı yokken "Elle gönderildi" işlemi durumu değiştirir ve geçmişte kanal görünür. Kanal boşsa 400 döner. İkinci e-posta gönderimi `EmailLogs` tablosunda ikinci kaydı oluşturur. `abc@` adresi 400 döner. SMTP hatasında yanıtta istisna metni bulunmaz.

### M07-07 — Sunucu tarafı doğrulama ve satır yuvarlama → **DEĞİŞTİR (küçük ek), P1**
- **Doğrulama:** Doğru. Yalnızca "en az bir kalem" kontrolü var (806). Ek bulgular:
  - `Description` ve `CustomerName` JSON'da `null` gelirse NOT NULL sütuna yazılırken SQL istisnası, yani 500 oluşur.
  - `ValidUntil` geçmiş tarih olarak girilebiliyor.
  - Başka birimin iş emrine bağlanan teklif, listede o iş emrinin numarasını gösteriyor (`LoadOffersAsync` JOIN, 3526-3528). Küçük bir bilgi sızıntısı.
- **Düzeltilmiş tanım:**
  - Mevcut kurallar korunur: adet > 0 ve ≤ 100.000; fiyat ≥ 0; iskonto 0–100; KDV yalnızca 0/1/10/20; açıklama 1–500 karakter; 1–200 kalem; müşteri adı 1–200 karakter; e-posta biçimi geçerli.
  - Ek kurallar: `null` alanlar 500 değil 400 döner. `ValidUntil` bugünden önce olamaz.
  - `WorkOrderId` verilmişse iş emri var olmalı ve `CanAccessWorkOrderAsync` kontrolünden geçmelidir; iş emri birimi teklif birimiyle aynı olmalıdır.
  - Satır net tutarı satır bazında yuvarlanır; toplamlar yuvarlanmış satırlardan oluşur.
  - CHECK kısıtları eklenmeden önce mevcut veride ihlal sorgusu çalıştırılır. İhlal varsa kısıt `WITH NOCHECK` ile eklenir ve ihlaller raporlanır.
  - **Kabul:** `quantity:-1`, `discountPercent:150`, `vatPercent:37`, `description:null`, geçmiş `validUntil`, erişilemeyen birimin iş emri ve var olmayan `workOrderId` isteklerinin her biri 400 veya 403 döner, hiçbiri 500 dönmez ve kayıt oluşmaz. 3 × 33,333 TL'lik kalemde satır toplamı ile genel toplam tutarlıdır.

### M07-08 — Liste filtreleri, detay ve bekleyen teklif takibi → **DEĞİŞTİR, P2**
- **Doğrulama:** Doğru. Liste filtresiz (app.js:1208-1215); `LoadOffersAsync` tüm tabloyu okuyor (3520-3539).
- **Değerlendirme:** Teknik servis teklif hacmi yılda birkaç yüz ile birkaç bin arasında olacaktır. SQL tarafında filtreleme ve indeks şu an gerekli değil, P3. Detay ekranı M07-02'ye taşındı. Bekleyen teklif kutusu ve süre dolumu uyarısı operasyon için değerli, P2.
- **Düzeltilmiş tanım:**
  - Teklif listesine durum, birim, müşteri metni, tarih aralığı ve "yanıt bekleyen" filtreleri eklenir. İstemci tarafında filtrelemek yeterlidir.
  - Operasyon merkezinde "Bekleyen teklifler" kutusu gösterilir: onay bekleyen ve müşteri yanıtı bekleyen adet, en eski bekleme günü. Tutar yalnızca §5 soru 1'deki izinle görünür.
  - Geçerliliği 3 gün içinde dolacak teklifler mevcut `AuxiliaryAlerts` yapısına eklenir.
  - **P3:** SQL tarafı filtre ve `Offers(Status, UnitCode, CreatedAt)` indeksi.
  - **Kabul:** "Müşteriye Gönderildi + son 30 gün" filtresi yalnızca uyan kayıtları gösterir. 2 gün sonra dolacak teklif için operasyon merkezinde uyarı çıkar. Yetkisiz birimin teklifi API yanıtında hiç yer almaz.

### M07-09 — Maliyet analizinde eksik veri ayrımı → **DEĞİŞTİR (kapsam genişletme), P1**
- **Doğrulama:** Doğru. Süre kaydı olmayan iş `hours=0, labor=0`, geliri olmayan iş `revenue=0` ve negatif fark gösteriyor (OpsSuite.cs:224-234).
- **Değerlendirme:** Kullanıcı kararıyla doğrudan çelişen bir veri doğruluğu hatası, P1. Ancak tasarım iki 0 kaynağını atlamış:
  - (1) Tarife tanımsız veya 0: varsayılan seed değeri 0 ve `GetValueOrDefault` (M07-D02).
  - (2) Garanti veya ücretsiz iş ile gelir girilmemiş iş arasında ayrım yok (M07-D03).
  - Ayrıca liste, açık (kapanmamış) işleri de içeriyor. Açık işte gelir ve maliyetin eksik olması normaldir; bunlar "eksik" diye toplu uyarı üretmemeli.
- **Düzeltilmiş tanım:**
  - `/api/ops/finance` her iş için `laborStatus` döner: `Tam` / `Süre kaydı eksik` / `Tarife tanımsız`. Son ikisinde `labor=null` olur.
  - `revenueStatus` döner: `Teklif` / `Elle` / `Ücretsiz-Garanti` / `Gelir kaydı yok`. "Gelir kaydı yok" ise `revenue=null` ve `margin=null` olur.
  - Ekran toplamlarına yalnızca verisi tam olan işler girer. Dışarıda kalan iş sayısı neden bazında gösterilir.
  - Varsayılan görünüm yalnızca kapanmış işleri içerir.
  - Tahmini süre hiçbir koşulda gerçek süre yerine kullanılmaz.
  - **Kabul:** Süre kaydı olmayan kapalı işte `labor:null` ve "Süre kaydı eksik" görünür. Tarifesi 0 olan birimde `labor:null` ve "Tarife tanımsız" görünür. Gelir kaydı olmayan işte `margin:null` döner. Ücretsiz/garanti işaretli işte gelir 0 kabul edilir ve fark hesaplanır. Fark toplamı yalnızca tam işleri içerir.

### M07-10 — Saatlik iç maliyet tarifesinin geçerlilik tarihli tutulması → **KABUL, P2**
- **Doğrulama:** Doğru. Tarife `UPDATE … SET HourlyCost` ile güncelleniyor (OpsSuite.cs:242), tabloda geçmiş yok.
- **Not:** Bugün tüm tarifeler 0 olduğundan geriye dönük bozulma henüz yaşanmadı. Tarifeler **ilk kez girilmeden önce** bu yapı kurulursa taşıma sorunu da olmaz. Tarihi bilinmeyen eski tarifeler için `2026-01-01` varsayımı gerekmez; yalnızca 0'dan farklı mevcut değerler taşınır.

### M07-11 — Maliyet analizi filtre, özet ve dışa aktarma → **DEĞİŞTİR, P2 (filtre + özet) / P3 (dışa aktarma)**
- **Doğrulama:** Doğru. Tarih filtresi yok; tüm iş emirlerinin parasal verisi hesaplanıyor (OpsSuite.cs:224-227); ekranda `r.slice(0,350)` var (ops120.js:21).
- **Değerlendirme:** Dönem ve birim filtresi yönetim sorusunu cevaplamak için gerekli. Filtre geldikten sonra sayfalama gereksiz. Dışa aktarma faydalı ama acil değil; mevcut `/api/ops/export.csv` deseni kopyalanarak küçük bir işle yapılabilir.
- **Düzeltilmiş tanım:**
  - `start`/`end` (kapanış tarihi; varsayılan içinde bulunulan ay), `unit` ve `type` (servis / planlı bakım) parametreleri eklenir.
  - Birim ve iş türü kırılımında özet gösterilir: gelir, malzeme, işçilik, diğer, fark, eksik veri sayısı.
  - Müşteri kırılımı P3'tür; müşteri ana tablosu olmadığı için serbest metinle gruplama güvenilmez.
  - 350 satır sınırı kaldırılır; filtre sonucu tamamen gösterilir.
  - **P3:** CSV dışa aktarma `finance.prices.view` + `reports.export` gerektirir ve eksik veri durum sütunlarını içerir.
  - **Kabul:** Ekim + Haberleşme + servis filtresi yalnızca o kapsamdaki kapanmış işleri getirir. Özet toplamı detay toplamına eşittir. `finance.prices.view` yetkisi olmayan kullanıcı 403 alır (M07-D01 sonrasında).

### M07-12 — Teklif dönüşüm ve bekleyen teklif raporu → **DEĞİŞTİR, P3**
- **Doğrulama:** Doğru, böyle bir rapor yok.
- **Değerlendirme:** Operasyonel ihtiyaç ("unutulan teklif") M07-08'deki bekleyen teklif kutusuyla karşılanıyor. Dönüşüm oranı, ortalama yanıt günü ve ret nedeni dağılımı yönetim KPI'sı; M07-02 verisi birikmeden anlamlı olmaz. Yapılabilir, ancak sonra.
- **Düzeltilmiş tanım:** Mevcut Excel raporuna "Teklifler" sayfası eklenir. Dönem ve birim bazında gönderilen, kabul, ret ve süresi dolan teklif adedi ile kabul oranı verilir. Ret nedeni dağılımı yalnızca neden verisi olan kayıtlarla hesaplanır. Revize edilen teklif yalnızca son revizyonuyla sayılır. Tutar sütunları §5 soru 1'deki izne bağlıdır. M07-02 en az 2–3 ay çalıştıktan sonra yapılır.

### M07-13 — Gelir ve maliyet değişiklik geçmişi → **KABUL, P2**
- **Doğrulama:** Doğru. Yalnızca son `UpdatedBy` ve `UpdatedAt` tutuluyor (OpsSuite.cs:253); sistemde genel bir denetim (audit) tablosu yok.
- **Not:** M07-04'teki otomatik gelir ve geri alma işlemleri bu geçmiş olmadan izlenemez; M07-04 ile aynı sürümde yapılmalı. Güvenlik modülü genel bir audit tablosu önerirse bu madde o tabloya yazılarak uygulanabilir.

### M07-14 — Teklif durum değişikliğinde birim/erişim kontrolü → **KABUL, P1**
- **Doğrulama:** Doğru. Program.cs:865'te yalnızca `Can(user,"offers.approve")` var; teklif yüklenmiyor ve `UnitAllowed` kontrol edilmiyor. PDF (890) ve gönderim (903) uçlarında bu kontrol var.
- **Not:** KRİTİK olmaması doğru. Ancak `ApprovedByUserId` ve `ApprovedAt` başka birimin kullanıcısı tarafından ezilebildiği için onay kaydı bütünlüğü bozuluyor. Birkaç satırlık bir iş ve M07-02'nin önkoşulu; P1.

### M07-15 — Fiyat/maliyet sızıntısı için otomatik API yetki testleri → **DEĞİŞTİR, P2**
- **Doğrulama:** Doğru. Test projesi yok. PILOT_V120_KURULUM_VE_TEST.txt:38 maddesi işaretlenmemiş.
- **Değerlendirme:** Kullanıcı sırasına göre güvenlik en son geliyor, ancak "fiyat API seviyesinde gizli" bir proje kararı ve bugün kanıtı yok. Ayrıca bu testler M07-D01'deki 403→500 hatasını ilk çalıştırmada yakalar. Tam `WebApplicationFactory` altyapısı Program.cs'nin tek dosya yapısında (statik yardımcılar, `sessions` sözlüğü) zahmetli olabilir.
- **Düzeltilmiş tanım:**
  - İlk aşamada yerel test SQL veritabanına karşı çalışan bir xUnit + `HttpClient` duman testi seti yazılır. Test seed'inde fiyat yetkili ve yetkisiz iki kullanıcı bulunur.
  - Senaryolar: `/api/ops/finance` 403; `/api/ops/stock` `cost:null`; bakım sözleşmesi ücret alanları `null`; `PUT /api/ops/finance/*` 403; durum ucunda başka birim isteği 404.
  - Teklif tutarı senaryosu §5 soru 1'in cevabından sonra eklenir.
  - "Açık oturuma yetki değişikliğinin etkisi" bu modülden çıkarılır ve oturum/güvenlik modülüne bırakılır.
  - **Kabul:** `dotnet test` ile her senaryo ayrı test olarak geçer. Bir uca bilerek `cost` alanı eklenince ilgili test kırmızıya döner.

### M07-16 — SMTP sır yönetimi ve gönderim hız sınırı → **DEĞİŞTİR, P3**
- **Doğrulama:** **Gerekçe kısmen yanlış.** `appsettings.json` içindeki `Email:Password` alanı boş. .NET yapılandırması `Email__Password` ortam değişkenini kod değişikliği olmadan zaten okur. Linux kurulumunda 0600 izinli `dengeerp.env` dosyası mevcut (linux/README_KURULUM_TR.md:45), ancak `dengeerp.env.example` dosyasında Email satırları yok. Gerçek risk, Program.cs:912'deki mesajın IT'yi parolayı `appsettings.json`'a yazmaya yönlendirmesi.
- **Düzeltilmiş tanım:**
  - `dengeerp.env.example` dosyasına `Email__SmtpHost`, `Email__SmtpPort`, `Email__From`, `Email__Username` ve `Email__Password` satırları eklenir.
  - Program.cs:912'deki mesaj "e-posta ayarları sunucu ortam dosyasında tanımlanmalı" şeklinde değiştirilir. IT kurulum belgesine not eklenir.
  - Gönderim ucuna .NET yerleşik `RateLimiter` ile kullanıcı başına dakikada 10 sınırı konur.
  - **Kabul:** Dağıtım ZIP'indeki `appsettings.json` içinde SMTP parolası bulunmaz ve gönderim env değişkeniyle çalışır. Aynı kullanıcının 1 dakika içindeki 11. gönderimi 429 döner.

---

## 3. Tasarımcının kaçırdığı maddeler

### M07-D01 — `Results.Forbid()` kimlik doğrulama şeması olmadan 500 üretiyor [HATA] (S) — P1
- **Mevcut durum:** Program.cs'de `AddAuthentication` veya `AddAuthorization` yok (arama sonucu boş). Yine de teklif uçları (794, 804, 805, 865, 887, 890, 899, 903) ve OpsSuite uçları (217, 240, 249, 250 vb.) `Results.Forbid()` döndürüyor. ASP.NET Core'da `ForbidResult` `HttpContext.ForbidAsync()` çağırır; `IAuthenticationService` kayıtlı değilse `InvalidOperationException` fırlar ve istemci 500 alır.
- **Etkisi:** Yetkisiz kullanıcıya veri gitmez (istek yine reddedilir), ancak:
  - Tasarımdaki tüm "403 döner" kabul kriterleri ve PILOT_V120:38 test maddesi bu haliyle sağlanamaz.
  - Loglar sahte "sunucu hatası" kayıtlarıyla dolar.
  - Ön yüz kullanıcıya "yetkiniz yok" yerine genel hata gösterir.
- **Öneri:** Tek bir `Forbidden()` yardımcısı tanımlanır: `Results.Json(new{message="Bu işlem için yetkiniz yok."}, statusCode:403)`. Tüm `Results.Forbid()` çağrıları bununla değiştirilir. Bu iş güvenlik/altyapı modülünde de çıkabilir; tek yerde yapılmalı.
- **Kabul:** `offers.view` yetkisi olmayan kullanıcı `GET /api/offers` için 403 ve JSON mesaj alır. Sunucu logunda `InvalidOperationException` oluşmaz.
- **Roller:** Tüm roller. **Veri:** Yok. **Bağımlılık:** –

### M07-D02 — İşçilik tarifesi tanımsız veya 0 iken işçiliğin sessizce 0 hesaplanması [VERİ] (S) — P1
- **Mevcut durum:** `OpsLaborRates` 5 birim için yalnızca UnitCode ile oluşturulmuş; `HourlyCost DEFAULT 0` (ZZ_V120_Operations.sql:27-29). Hesapta `rates.GetValueOrDefault(w.UnitCode)` kullanılıyor (OpsSuite.cs:231). Tarifesi girilmemiş veya listede olmayan birimlerde tüm işçilik 0 TL çıkıyor.
- **Gerekçe:** "Eksik ≠ 0" kararının ikinci ihlali. Bugün sistemdeki işçilik maliyetinin tamamı 0 ve fark olduğundan yüksek görünüyor. M07-09 bunu kapsamadığı için düzeltme sonrasında da yanlış "kâr" görüntüsü sürer.
- **Öneri:**
  - Tarife 0 veya tanımsızsa `labor=null`, `laborStatus="Tarife tanımsız"` döner.
  - Maliyet Analizi ekranının üstünde "X birimde tarife tanımlı değil" uyarısı gösterilir.
  - Tarifesi 0 olan birim, `finance.costs.manage` sahibine ERP içi uyarı olarak gösterilir.
- **Kabul:** Haberleşme tarifesi 0 iken 3 saatlik süre kaydı olan iş için API `labor:null` ve "Tarife tanımsız" döner. Bu iş fark toplamına girmez.
- **Roller:** `finance.prices.view` + `reports.view`; tarife girişi `finance.costs.manage`. **Veri:** Yok. **Bağımlılık:** M07-09 ile birlikte.

### M07-D03 — "Gelir girilmedi" ile "ücretsiz / garanti iş" ayrımı [VERİ] (S) — P1
- **Mevcut durum:** `OpsWorkFinancials.Revenue DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK(Revenue>=0)` (ZZ_V120_Operations.sql:33). Yalnızca "diğer maliyet" girilen işte de gelir 0 olarak kaydediliyor. Garanti kapsamındaki veya sözleşme dahilindeki gerçek 0 gelir, girilmemiş gelirden ayrılamıyor.
- **Gerekçe:** Teknik serviste garanti ve sözleşme kapsamı işler sık görülür. M07-09 bu ayrım olmadan uygulanırsa iki sonuç olur: ya bu işler sonsuza kadar "Gelir kaydı yok" görünür, ya da yeniden 0 kabul edilip karar ihlal edilir.
- **Öneri:**
  - `Revenue` NULL olabilir hale getirilir; mevcut satırlarda `Revenue=0` ve `Notes` boşsa değer NULL'a çevrilir (taşıma scripti).
  - `RevenueSource` alanına `Ücretsiz-Garanti` değeri eklenir; bu seçenek not zorunluluğuyla girilir.
  - Planlı bakım için §5 soru 3 cevaplanana kadar PB işleri "Sözleşme kapsamı — gelir dağıtılmadı" olarak ayrı sayılır.
- **Kabul:** Yalnızca diğer maliyet girilen işte gelir "Gelir kaydı yok" görünür. "Ücretsiz-Garanti" işaretli işte gelir 0 kabul edilir ve fark hesaplanır. Not boşsa 400 döner.
- **Roller:** `finance.costs.manage`. **Veri:** `OpsWorkFinancials.Revenue` NULL olabilir; `RevenueSource`. **Bağımlılık:** M07-04 ve M07-09 ile birlikte.

### M07-D04 — "Teklif Sunulacak" sonucu verilen ancak teklifi açılmamış bakım kayıtlarının takibi [EKSİK] (S) — P2
- **Mevcut durum:** Planlı bakım formunda cihaz sonucu "Teklif Sunulacak" seçilebiliyor (Program.cs:2457; app.js:603). Bu sonuç hiçbir teklif kaydına bağlanmıyor ve takip edilmiyor.
- **Gerekçe:** Sahada teknisyen "teklif sunulacak" diyor, ancak ofiste teklifin açılıp açılmadığı kontrol edilmiyor. Bu doğrudan gelir kaybı ve cihazın arızalı kalması demek. M07-03 kısayolu yalnızca o anda ekranda olan kullanıcıya yardım eder; sonradan takip sağlamaz.
- **Öneri:** Operasyon merkezine "Teklif bekleyen bakım bulguları" uyarısı eklenir. Kural: `ServiceResult='Teklif Sunulacak'` olan ve aynı iş emrine bağlı, İptal dışında bir teklifi bulunmayan kayıtlar, form kaydından 2 iş günü sonra birim şefine ve `offers.create` sahiplerine uyarı olarak düşer. Uyarı listesinde iş emri, cihaz, seri no ve tarih yer alır.
- **Kabul:** Sonucu "Teklif Sunulacak" olan ve 2 gün geçmiş PB kaydı uyarıda görünür. Aynı iş emrine teklif açılınca uyarı kalkar. Kullanıcı yalnızca yetkili olduğu birimin kayıtlarını görür.
- **Roller:** `offers.create`, `workorders.view`, `maintenance.view`. **Veri:** Yok (sorgu). **Bağımlılık:** M07-03.

### M07-D05 — Kabul edilmiş ve tamamlanmış işlerin "faturaya iletildi" işareti [YENİ] (S) — P3
- **Mevcut durum:** Muhasebe görünümü yalnızca teklif listesi (app.js:1275-1277). Kabul edilen teklifin işi kapandıktan sonra faturalamaya iletilip iletilmediği izlenmiyor.
- **Gerekçe:** Teknik servis sorumluluğu işin kapanıp muhasebeye devredilmesiyle biter. Devir izlenmezse kabul edilmiş ve yapılmış iş faturalanmadan kalabilir. Bu madde muhasebe kaydı veya Logo entegrasyonu **değildir**; yalnızca teknik servisten muhasebeye devir işaretidir. Kapsam kararıyla uyumludur.
- **Öneri:**
  - Muhasebe görünümüne "Faturaya hazır" listesi eklenir: Kabul Edildi teklifi olan ve iş emri kapanmış kayıtlar.
  - `accounting.view` sahibi "Faturaya iletildi" işareti koyar; isteğe bağlı olarak serbest metin fatura numarası girer.
  - Listede 7 günden uzun bekleyen kayıtlar vurgulanır.
- **Kabul:** Kabul edilmiş teklifi olan iş kapanınca listede görünür. İşaretlenince listeden düşer ve kim ile ne zaman bilgisi görünür. `accounting.view` yetkisi olmayan kullanıcı 403 alır.
- **Roller:** `accounting.view` (varsayım: Muhasebe rolü). **Veri:** `Offers.InvoiceForwardedAt`, `InvoiceForwardedBy`, `InvoiceRef NVARCHAR(50) NULL`. **Bağımlılık:** M07-02.

---

## 4. Önerilen uygulama sırası (denetim sonrası)

1. **Temel düzeltmeler (küçük, diğerlerinin önkoşulu):** M07-D01, M07-14, M07-07
2. **Akışın çalışması (P1):** M07-02 (detay ekranı dahil), M07-06'nın "Elle gönderildi" kısmı, M07-05'in hata kısmı
3. **Veri doğruluğu (P1):** M07-09 + M07-D02 + M07-D03
4. **Bağlantı ve takip (P2):** M07-01, M07-03, M07-D04, M07-04 + M07-13, M07-08
5. **Maliyet raporu ve tarife (P2):** M07-10 (tarifeler ilk kez girilmeden önce), M07-11 filtre ve özet, M07-15 duman testleri
6. **Sonra (P3):** M07-05 kurumsal şablon ek kısımları, M07-06 kalan kısımlar, M07-11 dışa aktarma, M07-12, M07-16, M07-D05

Kullanıcının "önce yeni özellik" önceliği korunmuştur. 1. ve 3. adımlardaki maddeler "güvenlik" değil, yeni akışın doğru çalışması ve veri doğruluğu için zorunlu olduğundan öne alınmıştır.

## 5. Varsayımlar ve açık sorular (tasarımdakilere ek)

- Öz-onay yasağı, Muhasebe ve Genel Koordinatör'ün `offers.approve` yetkisi ve "Faturaya iletildi" işaretini Muhasebe'nin koyması **varsayımdır**; organizasyon şeması gelince doğrulanmalıdır.
- §5 soru 1 (teklif tutarını kim görür) M07-03, M07-08, M07-12 ve M07-15'in kabul kriterlerini doğrudan belirler. Bu soru **ilk** cevaplanması gereken sorudur.
- PDF kütüphanesi için lisans riski düşük olan PDFsharp/MigraDoc (MIT) önerilir; QuestPDF ciro eşiği nedeniyle ücretli lisans gerektirebilir. Karar İT ile verilmelidir.
- `Results.Forbid()` → 500 bulgusu statik okumaya dayanır; ilk yerel derleme ve testte bir istekle doğrulanmalıdır.
