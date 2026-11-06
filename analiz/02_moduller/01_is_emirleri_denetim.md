# M01 — Ana Panel, İş Havuzu ve İş Emirleri — Bağımsız Denetim

> **Tarih:** 21 Ekim 2026 · **Denetlenen:** `01_is_emirleri_tasarim.md` (M01-01 … M01-18)
> **Kaynak:** V1.20.1, salt okunur. Kaynak koda dokunulmadı.
> **Kısaltmalar:** `P.cs` = Program.cs, `Ops.cs` = OpsSuite.cs, `upd.sql` = Database/DengeERP_Update.sql.
> **Öncelik:** P1 = iş akışını durduruyor ya da veri doğruluğunu bozuyor · P2 = operasyon kalitesini artırıyor · P3 = sonraya bırakılabilir.

## 1. Genel değerlendirme

Tasarımcının mevcut durum tespitleri **büyük ölçüde doğru**. Kodu okuyarak şunları kendim doğruladım:

- `PATCH status` serbest metin kabul ediyor. İzin kontrolü `edit || close` (P.cs:477). `ClosedAt` yalnız `Kapatıldı` olduğunda doluyor ve yeniden açılınca temizlenmiyor (P.cs:525-528).
- Tekil plan durumu kontrol etmiyor ve geçmişe `OldStatus=NULL` yazıyor (P.cs:754-757). Toplu planda bu kontrol var (P.cs:682).
- Tekil atama kapalı işe yapılabiliyor ve geçmişe yazılmıyor (P.cs:545-570).
- Hold/release `WorkOrderStatusLogs`'a yazmıyor. İkinci aktif bekleme açılabiliyor. Release, birden çok aktif satırda `ExecuteScalar` ile rastgele birinin `PreviousStatus` değerini alıyor (Ops.cs:130-159).
- KPI uyuşmazlıkları gerçek. "Sahada" kutusu `Sahada+İşlemde` sayıyor (app.js:220), liste yalnız `Sahada` açıyor (app.js:243). "Açık Bakım" sayısı `reportIsOpen` ile, listesi `isOpen` ile hesaplanıyor; `isOpen` Tamamlandı'yı açık sayıyor (app.js:131, 248).
- Teknisyen kapsamı `RoleName=="Teknisyen"` ve ad metniyle belirleniyor (P.cs:3398-3400, 3499-3500).
- PDF ASCII dönüşümü (P.cs:3573-3575, 3630-3636) ve Excel'deki 10 durumluk dizi (P.cs:3684) doğrulandı.

**Tasarımcının kaçırdığı ya da yanlış yazdığı noktalar:**

1. **Durum yazan ikinci bir kapı var.** `PUT /api/workshop/tickets/{id}` (P.cs:2707-2776) iş emrinin `Status`, `CustomerName`, `Subject` ve `SerialNo` alanlarını doğrudan değiştiriyor. `Kapatıldı` dahil. Bu sırada `CanAccessWorkOrderAsync` kontrolü, açık sayaç kontrolü ve geçmiş kaydı yok. Varsayılan Teknisyen rolünde `workshop.manage` izni var (P.cs:3930). M01-09 yalnız `PATCH status` ucunu ele alırsa yaşam döngüsü bu kapıdan delinmeye devam eder. Ayrıca M01-08 ile yapılan düzeltmeyi bu uç ezer. → **M01-D01**
2. **Teknisyen rol şablonunda bugün `workorders.close` var** (P.cs:3930). İzinler kullanıcı satırında metin olarak saklanıyor (`ErpUsers.Permissions`, upd.sql:152). Tasarım "yeni izinler eski profillere otomatik dağıtılmaz" diyor. Bu durumda M01-09/M01-18'in "teknisyen Kapatıldı yaparsa 403" kabul kriteri, mevcut kullanıcılarda bir izin göçü yapılmadan sağlanamaz. → **M01-D02**
3. **Şef rolünde `workorders.create` yok** (P.cs:3929). M01-05'te "Şef: workorders.create" yazılmış; bu rol önerisi mevcut şablonla çelişiyor. **Operasyon Uzmanı rolünde `workorders.edit` yok** (P.cs:3928). Bu yüzden not ekleme (M01-06) ve düzeltme (M01-08) için yeni bir izin gerekir.
4. **"İlgili kişi/telefon yok" iddiası kısmen yanlış.** Plan kaydında `SiteContact` ve `SitePhone` alanları var (P.cs:697-701, Excel'de de çıkıyor, P.cs:3676). Eksik olan, bu bilgilerin **açılışta** alınması.
5. **"Süre kaydı eksik" kavramı Excel'de zaten var** (P.cs:3666, 3678: "SÜRE KAYDI YOK"). M01-11 bunu sıfırdan tasarlamak yerine aynı tanımı panele taşımalı.
6. Detay ekranındaki "Kaydet" iki ayrı istek gönderiyor (atama, sonra durum; app.js:1670-1671). Yalnız `assign` iznine sahip bir kullanıcıda atama kaydediliyor, ardından durum isteği 403 alıyor ve kullanıcı yarım kalmış bir kayıtla hata görüyor. Bu durum M01-15'e eklendi.
7. Tekil plan ucunda tarih ve süre doğrulaması yok (P.cs:722-752). Toplu planda bu doğrulama var (P.cs:657).

**KRİTİK kontrolü:** Bu modülde kendi başına **KRİTİK** (veri kaybı/dış sızıntı) bulgu yok; tasarımcının hükmüne katılıyorum. M01-D01, iç veri bütünlüğünü bozan **yüksek önemli** bir bulgudur, P1 olarak sınıflandırıldı.

**Kapsam uyumu:** Maddelerin hepsi teknik servis kapsamında. Logo/Flowick'e bağımlı madde yok. Kararlarla çelişen madde yok: seri no metin, süre "eksik" (0 değil), fiyat gizli, tahmini süre kullanılmıyor. Rol önerilerinin varsayım olarak işaretlenmesi doğru.

**Aşırı mühendislik riski:** M01-07 (`ServiceCategory` kolonunun kopyalanması), M01-16 (kütük FK'si), M01-17 (sunucu sayfalama) ve M01-18(d) (iletişim bilgisi maskeleme) bugünkü pilot hacminde erken. Bunlar sadeleştirildi ya da P3'e alındı.

## 2. Madde bazında kararlar

| ID | Karar | Öncelik | Kısa gerekçe |
|---|---|---|---|
| M01-01 | DEĞİŞTİR | P1 | Gerekli. Ancak "Tekrar Gidilecek / Teklif Sunulacak / Servise Alındı" sonuçları tamamlanma değildir; ziyaret sonucu olarak ayrılmalı |
| M01-02 | DEĞİŞTİR | P2 | Kanal alanı M01-01 formunun parçası olmalı. "Açılışta çözüldü" kısa yolu kullanıcı kararına bağlı; KPI kutusu M01-11'e taşınmalı |
| M01-03 | DEĞİŞTİR | P1 | Gerekli (kanıt). Dosya içeriği sunucuda doğrulanmalı, nginx 20 MB sınırı nedeniyle istek başına tek dosya gönderilmeli, KVKK erişim kuralı eklenmeli |
| M01-04 | DEĞİŞTİR | P2 | Gerekli (belge §6.1/§14). Parça listesi yedek parça modülüne bağımlı; ilk sürüm parçasız olabilir |
| M01-05 | DEĞİŞTİR | P2 | Rol hatası (Şef'te create izni yok). Plan kaydındaki SiteContact/SitePhone ile bağlanmalı. Müşteri+lokasyon eşleşmesi zayıf; ancak uyarı olarak kullanılmalı |
| M01-06 | KABUL | P1 | Birçok maddenin temeli. Kod iddiaları doğrulandı |
| M01-07 | DEĞİŞTİR | P2 | Gerekli ama sade yapılmalı: tek sunucu fonksiyonu ve `WorkTypeRules.Category` yeterli; iş başına kopya kolon yalnız düzeltme amaçlı |
| M01-08 | DEĞİŞTİR | P2 | Atölye ve PB kökenli işlerde kaynak kayıt ayrı, bunlar engellenmeli. RowVersion bugün listede dönmüyor |
| M01-09 | DEĞİŞTİR | P1 | Doğru ve gerekli. Tüm durum yazan uçları ve izin göçünü kapsamalı |
| M01-10 | DEĞİŞTİR | P1 | Doğru. `ErpUserId` atama tablosuna kopyalanmamalı; `Personnel.ErpUserId` (upd.sql:362) üzerinden türetilmeli |
| M01-11 | DEĞİŞTİR | P2 | Bağımlılıklar eksik (M01-01, M01-05, M01-12). Tekrar arıza KPI'sı karar gelene kadar Ops'taki tanımı kullanmalı |
| M01-12 | KABUL | P1 | Hata doğrulandı; küçük ve hızlı bir düzeltme |
| M01-13 | DEĞİŞTİR | P1 | Hata doğrulandı. Toplu planla aynı tarih/süre doğrulaması da eklenmeli |
| M01-14 | KABUL | P1 | Doğrulandı. Çift bekleme, release sonrasında durumun `Beklemede`'de kalmasına yol açabiliyor (veri bozulması) |
| M01-15 | DEĞİŞTİR | P2 | Doğrulandı. Kaydetme işlemi atomik olmalı ve izinler yarım kayıt üretmemeli |
| M01-16 | DEĞİŞTİR | P3 | Asıl değer, seri no karşılaştırmasının normalleştirilmesinde. FK cihaz kütüğü modülüne bırakılmalı |
| M01-17 | DEĞİŞTİR | P3 | Pilot hacminde erken. Varsayılan cevap değişirse istemci KPI'ları kırılır. Önce birim/teknisyen filtresi SQL'e taşınmalı |
| M01-18 | DEĞİŞTİR | P2 | (a)-(c) gerekli; (d) organizasyon şeması gelene kadar ertelenmeli. Atölye ucu da kapsama alınmalı |

### Düzeltilmiş tanımlar (DEĞİŞTİR)

**M01-01:** Kapanış formu iki parçaya ayrılır.

- **Ziyaret/işlem sonucu:** Saha veya atölye işleminden sonra girilir. Alanlar: yapılan işlem, sonuç (Çözüldü / Tekrar Gidilecek / Teklif Sunulacak / Servise Alındı / Çözülemedi) ve çözüm kanalı.
- **Tamamlanma:** `Tamamlandı`'ya yalnız "Çözüldü" ya da "Çözülemedi" sonucu varken geçilir. "Tekrar Gidilecek" sonucunda iş `Planlamada`'ya döner. "Teklif Sunulacak" sonucunda iş nedeni "Teklif" olan bir beklemeye girer (M01-14 ucu üzerinden).
- Arıza nedeni birim bazlı kısa bir listeden seçilir; "Diğer" seçilirse açıklama zorunludur.
- `CompletedAt` ve `CompletedByUserId` alanları M01-09 ile aynı sürümde gelir.

Kabul kriterleri:

1. Sonuç kaydı yokken `Tamamlandı` isteği 400 döner.
2. "Tekrar Gidilecek" sonucunda iş `Planlamada` olur ve geçmişe yazılır.
3. Excel Günlük Servis sayfasında yapılan işlem, arıza nedeni, sonuç ve tamamlanma zamanı kolonları çıkar.

**M01-02:** `ResolutionChannel` alanı (Telefonla / Uzaktan / Yerinde / Atölyede) M01-01 formunun zorunlu bir alanıdır. "Açılışta çözüldü" kısa yolu, kullanıcının §4/3 sorusunu yanıtlamasına bağlı isteğe bağlı bir alt maddedir. Onay gelirse `workorders.resolve_remote` (varsayım) izniyle tek istekte `Müşteri Talebi → Tamamlandı` akışı yapılır; kanal ve yapılan işlem zorunludur. Oran kutusu M01-11'de tanımlanır. POC'deki eski kapalı işler için tek seferlik eşleme scripti eşlenemeyen kayıt sayısını raporlar.

**M01-03:** Tasarımdaki kabul kriterlerine ek olarak:

1. Tür kontrolü uzantıyla yetinmez; dosyanın ilk baytları (magic bytes) da kontrol edilir.
2. İstek başına tek dosya gönderilir (nginx `client_max_body_size 20m`). İstemci fotoğrafları yüklemeden önce yaklaşık 2000 px boyuta küçültür.
3. HEIC dosyaları tarayıcıda görüntülenemeyebilir; bu dosyalar yalnız indirme olarak sunulur.
4. Dosya klasörü yedek scriptine eklenir ve geri yükleme testi yapılır.
5. Kişisel veri (yüz, plaka) içerebilecek eklere erişim yalnız iş ekibi ve yönetimle sınırlıdır (varsayım, KVKK).

**M01-04:** İlk sürüm şunları içerir: onay kaydı (imza / sözlü / alınamadı + neden) ve yazdırılabilir HTML servis formu. Formda firma, iş no, seri no, başlangıç-bitiş (yalnız gerçek süre kayıtlarından; kayıt yoksa "Süre kaydı eksik" yazılır), yapılan işlem, sonuç, onay ve imza görüntüsü bulunur. "Kullanılan parçalar" bölümü yedek parça modülündeki stok çıkışı hazır olduğunda eklenir; o zamana kadar boş bırakılmaz, "kayıt yok" yazılır. Onayın zorunlu olduğu iş türleri kullanıcı kararıyla `WorkTypeRules.ApprovalRequiredOnComplete` alanında tutulur; başlangıç değeri kapalıdır. Form fiyat içermez. Onay kaydı değiştirilemez.

**M01-05:** Açılışta talep kanalı, ilgili kişi, telefon ve `ReportedAt` alınır. Planlama ekranı `SiteContact` ve `SitePhone` alanlarını bu değerlerle ön doldurur. Mükerrer kontrolde:

- Açık bir işte aynı **normalleştirilmiş seri no** varsa API 409 döner ve iş no listesini verir; `force=true` gönderilirse kayıt açılır ve olay geçmişe yazılır.
- Aynı müşteri+lokasyon eşleşmesi yalnız bilgilendirme uyarısıdır (metin eşleşmesi zayıf olduğu için).

Roller: Operasyon Uzmanı `workorders.create` iznini kullanır. Şefin kayıt açması isteniyorsa rol şablonuna `workorders.create` eklenir (varsayım, organizasyon şemasıyla doğrulanacak).

**M01-07:** `WorkTypeRules` tablosuna `Category` kolonu eklenir. Sunucuda tek bir `GetCategory(row)` fonksiyonu yazılır ve API cevabına `category` alanı eklenir. app.js:127, Ops.cs:9 ve P.cs:3639'daki üç sezgisel hesap kaldırılır. `WorkOrders.ServiceCategory` yalnız elle düzeltme (override) için NULL olabilen bir kolondur. "Plansız Bakım" için başlangıç değeri "Günlük Servis"tir; kullanıcı onayına bağlıdır. Kabul kriterleri değişmez.

**M01-08:** Tasarımdaki kabul kriterlerine ek olarak:

1. Atölye kaydına bağlı iş emrinde müşteri/konu/seri alanları bu uçtan 400 döner ("Atölye kaydından düzeltin"), çünkü P.cs:2757-2772 bu alanları her güncellemede yeniden yazıyor.
2. PB işinde müşteri ve lokasyon sözleşmeden gelir; bu ucun kapsamı dışındadır.
3. `RowVersion`, `GET /api/workorders` cevabına eklenir.
4. Operasyon Uzmanı için yeni dar izin `workorders.edit_basic` (varsayım) tanımlanır, çünkü bu rolde `workorders.edit` yok.

**M01-09:** Geçiş tablosu tek bir sunucu fonksiyonunda (`TryTransition`) tanımlanır. Durum yazan **bütün** uçlar bu fonksiyonu kullanır:

- `PATCH status`
- tekil ve toplu plan
- hold/release
- `PUT /api/workshop/tickets/{id}` (bkz. M01-D01)
- bakım formu kapanışı

Ek kurallar:

- `IsClosingStatus` içindeki ölü `Çözüldü` değeri kaldırılır.
- POC'ye özgü durumlar (`İnceleniyor`, `Telefonla Destek`, `Uzaktan Müdahale`, `Yerinde Müdahale`) kataloğa ve geçiş tablosuna açıkça girer. Taşıma kararı verilene kadar bu durumlar açık durum sayılır.
- `Tamamlandı` olduğunda `CompletedAt` dolar. `Kapatıldı` olduğunda `ClosedAt` ve `ClosedByUserId` dolar. `Tekrar Açıldı` olduğunda bu alanlar NULL olur ve `ReopenCount` 1 artar.
- İzin göçü M01-D02 ile aynı sürümde yapılır.

Tasarımdaki 7 kabul kriteri geçerlidir. Bunlara iki kriter eklenir:

8. Atölye ucundan `Teslim Edildi` gönderildiğinde de geçmiş satırı yazılır ve açık sayaç kontrolü yapılır.
9. Kurulum sonrası mevcut teknisyen hesabıyla `Kapatıldı` isteği 403 döner.

**M01-10:** `WorkOrderAssignments` tablosuna `PersonnelId`, `IsLead`, `AssignedByUserId`, `AssignedAt` ve `RemovedAt` eklenir. `ErpUserId` kopyalanmaz; `Personnel.ErpUserId` alanına join yapılır. Erişim ve sayaç kontrolleri (P.cs:3398-3400, 3499-3500, 1943-1948, 2120) `ErpUserId` eşleşmesine geçer. Ad eşleşmesi yalnız `PersonnelId` boş olan eski kayıtlar için geçici yedek olarak kalır, göç raporu çıktıktan sonra kaldırılır. Atölye `AssignedTo` metni ve süre kaydı `TechnicianName` alanı ayrı maddelerde ele alınır. Kabul kriterleri değişmez.

**M01-11:** Bağımlılıklar M01-01, M01-05, M01-07 ve M01-12'dir. Kutular tek bir `kpiDefinitions` tanımından üretilir.

- "Süre kaydı eksik" kutusu Excel'deki tanımla aynıdır (P.cs:3666).
- "Geciken" kutusu Ops.cs:87'deki tanımı kullanır.
- "Tekrar arıza" kutusu, §4/7 kararı gelene kadar Ops.cs:93-96'daki tanımı gösterir.
- "Ortalama çözüm süresi" `ReportedAt` (yoksa `CreatedAt`, "tahmini" etiketiyle) ile `CompletedAt` arasından hesaplanır; `CompletedAt` boş olan iş hesaba girmez.

Tasarımdaki 4 kabul kriteri geçerlidir.

**M01-13:** Tasarımdaki 3 kabul kriterine ek olarak:

4. Tekil plan, toplu planla aynı doğrulamayı uygular: `PlanDate` dolu olmalı, süre 15-1440 dakika arasında olmalı.
5. Durum değişikliği M01-09'daki `TryTransition` fonksiyonundan geçer.

**M01-15:** "Kaydet" işlemi tek bir sunucu ucuna (ya da sırayla, değişen alan kadar isteğe) bağlanır. Durum değişmediyse `PATCH` isteği gönderilmez. Kullanıcının izni olmayan bölüm ekranda gösterilmez. Kabul kriterleri:

1. Durum değişmeden kaydedildiğinde yeni durum logu oluşmaz; "Atama değişti" satırı oluşur.
2. Not, "Not" olay türüyle yazılır.
3. Yalnız `workorders.assign` iznine sahip kullanıcı kaydettiğinde hata almaz ve atama kaydedilir.

**M01-16:** İlk adım ortak bir `NormalizeSerial` fonksiyonudur: trim, büyük harf, iç boşlukların teke indirilmesi; baştaki sıfırlar ve `/ - .` karakterleri korunur. Bu fonksiyon mükerrer kontrolünde (M01-05) ve tekrar arıza analizinde (Ops.cs:93-96) kullanılır. `SecurityDeviceId` bağlantısı cihaz kütüğü modülünün maddesidir ve oradan planlanır.

**M01-17:** İlk adım, `FilterWorkOrdersForUser` mantığının (birim ve teknisyen kapsamı) SQL `WHERE` koşuluna taşınmasıdır. Ardından isteğe bağlı `from`, `to`, `status` ve `q` parametreleri eklenir; parametresiz çağrı bugünkü gibi davranır. Varsayılan sınırlama (açık işler + 90 gün), KPI'lar sunucu tarafına taşındıktan sonra açılır. İndeksler aynı kalır.

**M01-18:** Kapsam şöyle olur:

- (a) Kapatma, iptal ve yeniden açma için ayrı izinler (M01-09).
- (b) `workorders.own_only` izni ve `ErpUserId` kapsamı (M01-10).
- (c) Detay, geçmiş, ek, süre kaydı ve **atölye ticket** uçları aynı `CanAccessWorkOrderAsync` fonksiyonunu kullanır.
- (d) Müşteri iletişim bilgisinin maskelenmesi organizasyon şeması gelene kadar P3'te bekler.

Kabul kriterlerine bir ekleme yapılır: `own_only` bayraklı kullanıcı, kendisine atanmamış atölye kaydını `PUT /api/workshop/tickets/{id}` ile güncelleyemez (403).

## 3. Eklenen maddeler

### M01-D01 · HATA · Atölye kaydı güncelleme ucu iş emri durumunu kontrolsüz değiştiriyor — P1

- **Mevcut durum:** P.cs:2707-2776. Uç `workshop.manage || workorders.edit` izniyle ve yalnız birim kontrolüyle çalışıyor. İş emrinin `Status` alanını `Kapatıldı` dahil bir eşleme tablosuyla değiştiriyor (2746-2755). `CustomerName`, `Subject` ve `SerialNo` alanlarını üzerine yazıyor. Bu sırada durum logu yazılmıyor, açık sayaç kontrolü ve seri no kuralı uygulanmıyor, `CanAccessWorkOrderAsync` çağrılmıyor ve kapalı iş yeniden açılabiliyor. Teknisyen şablonunda `workshop.manage` var (P.cs:3930).
- **Yapılacak:** Uç durum değişikliğini M01-09'daki `TryTransition` fonksiyonuyla yapar ve geçmişe yazar. İş emri alanlarını yalnız gerçekten değiştiyse günceller. İş erişim kontrolünü uygular.
- **Kabul kriterleri:**
  1. Atölye kaydı `Teslim Edildi` yapıldığında geçmişte satır oluşur.
  2. Açık sayaç varken 409 döner.
  3. Atanmamış teknisyen 403 alır.
  4. Kapalı işte `Yeni Kayıt` gönderilirse iş sessizce açılmaz; 400 döner ya da yetkili kullanıcının yeniden açma akışına yönlendirilir.

### M01-D02 · VERİ · Mevcut kullanıcı izinlerinin yeni anahtarlara göçü — P1

- **Mevcut durum:** İzinler `ErpUsers.Permissions` alanında metin olarak tutuluyor (upd.sql:152). Önceki göçler aynı şekilde yapılmış (V15_Schema.sql:148-168). Teknisyen şablonunda `workorders.close` var (P.cs:3930).
- **Yapılacak:** İdempotent bir `ZZ_V1xx_WorkOrderPermissions.sql` scripti yazılır. Script önce "kimde hangi izin kalkacak/eklenecek" önizleme raporu üretir, sonra şunları yapar:
  - Teknisyen rolündeki hesaplardan `workorders.close` kaldırılır, `workorders.complete` eklenir.
  - Şef ve müdürlere `workorders.reopen` ve `workorders.cancel` eklenir.
  - Özel profiller yalnız raporlanır, otomatik değiştirilmez.
- **Kabul kriterleri:**
  1. Script iki kez çalıştırıldığında sonuç aynıdır.
  2. Önizleme raporu üretilir.
  3. Göçten sonra teknisyen hesabıyla `Kapatıldı` isteği 403, `Tamamlandı` isteği 200 döner.

### M01-D03 · HATA · Kapalı veya iptal işte seri no değişikliği engellenmiyor ve geçmişe yazılmıyor — P2

- **Mevcut durum:** P.cs:432-471 durum kontrolü yapmıyor ve log yazmıyor; yalnız PB işini engelliyor. Kapandıktan sonra seri no değişirse cihaz geçmişi ve tekrar arıza analizi sessizce değişir.
- **Kabul kriterleri:**
  1. `Tamamlandı`, `Kapatıldı` ya da `İptal` durumundaki işte istek 400 döner. İstisna: `workorders.reopen` iznine sahip kullanıcı gerekçe girerek değiştirebilir.
  2. Her değişiklik eski→yeni değerle geçmişe yazılır (M01-06).

### M01-D04 · YENİ · Bağlı iş (mükerrer ve tekrar arıza bağlantısı) — P2

- **Mevcut durum:** İşler arasında ilişki tutulmuyor. M01-05'teki "mevcut işe not ekle / yine de aç" seçimi ve tekrar arıza KPI'sı bu bağlantıya ihtiyaç duyuyor.
- **Yapılacak:** `WorkOrders` tablosuna `RelatedWorkOrderId BIGINT NULL FK` ve `RelationType` (Mükerrer / Tekrar Arıza / Devam İşi) eklenir.
- **Kabul kriterleri:**
  1. Mükerrer uyarısı geçilerek açılan iş, ilgili işe bağlı olur.
  2. Detayda bağlı işler listelenir.
  3. Bir iş kendisine bağlanamaz.

Tasarımdaki §4/7 kararına bağlıdır.

### M01-D05 · EKSİK · İş emri modülü için otomatik API testleri ve tohum test verisi — P1

- **Mevcut durum:** Kabul kriterlerinin çoğu otomatik doğrulama istiyor: yetki 403 testleri, "kutu sayısı = liste sayısı", geçiş tablosu. Repoda otomatik test projesi yok; testler elle yürütülüyor (TEST_SONUCLARI_V120.txt). Kullanıcı test verisinin olacağını ve kararın bize bırakıldığını söyledi.
- **Yapılacak:**
  - `DengeERP.Tests` projesi (xUnit + `WebApplicationFactory`) ve ayrı bir test veritabanı.
  - Tohum veri: her birimden, her durumdan iş; 2 teknisyen (biri aynı adlı); 1 kapalı iş; 1 atölye işi; 1 PB işi.
  - Geçiş tablosu, yetki ve KPI eşitliği için en az 20 senaryo.
- **Kabul kriterleri:**
  1. Testler tek komutla (`dotnet test`) çalışır.
  2. Yerel ortamda geçer; GitHub'a geçildiğinde CI'da da çalışacak şekilde yapılandırılır.

## 4. Önerilen uygulama sırası

Kullanıcının öncelik sırası (c) yeni özellik → (b) mevcut eksikler → (a) güvenlik idi. Ancak yeni özelliklerin doğru veri üretebilmesi için önce bir temel sprinti gerekiyor.

1. **Temel sprinti (küçük, ön koşul):** M01-06, M01-12, M01-13, M01-14, M01-D05.
2. **(c) Yeni özellikler:** M01-01 (kanal alanıyla birlikte M01-02), M01-03, M01-05, M01-04.
3. **(b) Mevcut eksikler:**
   - M01-09 ile M01-D01 ve M01-D02 aynı sürümde yapılmalı. Ayrı yapılırsa yaşam döngüsü atölye ucundan delinmeye devam eder ve teknisyenler eski izinleriyle kapatmaya devam eder.
   - Ardından M01-10, M01-15, M01-07, M01-08, M01-11, M01-D03, M01-D04.
4. **(a) Güvenlik ve üretime hazırlık:** M01-18, ardından P3 maddeleri (M01-16, M01-17).

## 5. Denetçi notları

- Satır referanslarının hepsi kontrol edildi ve doğru çıktı.
- Tasarımın §4'teki 12 sorusu yerinde. Bunlara iki soru eklenmeli:
  1. Atölye kaydı `Teslim Edildi` olduğunda iş emri doğrudan `Kapatıldı` mı olsun, yoksa `Tamamlandı` olup şef mi kapatsın?
  2. Şef iş kaydı açabilsin mi?
