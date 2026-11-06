# M04 — Planlı Bakım ve Dijital Servis Formu: Bağımsız Denetim

> **Denetlenen belge:** `analiz/02_moduller/04_planli_bakim_tasarim.md` (14 madde, M04-01 … M04-14)
> **Kaynak:** `kaynak/V1_20_1_orijinal/DengeERP.Api` (salt okunur, değiştirilmedi)
> **Tarih:** 21.10.2026 · **Kapsam:** yalnızca teknik servis
> **Öncelik ölçeği:** P1 = iş akışını durduruyor veya veri doğruluğunu bozuyor · P2 = operasyonel kalite · P3 = sonraya bırakılabilir
> **Rol önerileri:** Organizasyon şeması gelmediği için tüm rol ve izin önerileri **varsayımdır**.

---

## 1. Özet

| Karar | Adet | Maddeler |
|---|---|---|
| KABUL | 1 | M04-10 |
| DEĞİŞTİR | 13 | M04-01, 02, 03, 04, 05, 06, 07, 08, 09, 11, 12, 13, 14 |
| RET | 0 | — |
| Eklenen madde | 3 | M04-D01, M04-D02, M04-D03 |

Tasarımcının "mevcut durum" iddialarının çok büyük bölümü kodla birebir doğrulandı (satır numaraları doğru). Ancak:

- **M04-02'nin kabul kriteri 3 yanlış.** KENTPARK'ın yıllık frekansı 1, `CompletedCount` değeri 1 (Seed:2434). Bu yüzden 2026'da bu sözleşme için hiç PB üretilmiyor. "Mevcut 11 X-Ray PB" diye bir kayıt yok.
- **Ayrıştırılamayan dördüncü bir sözleşme atlanmış.** BAKIM-0029 SEGATECH'in ürün metni "7 ADET KAPI DEDEKTÖRÜ" (Seed:2375). Regex, sayı ile tür arasında "ADET" kelimesi olduğu için bu metni eşleştiremiyor. Sonuç olarak 7 cihaz için sessizce 0 PB üretiliyor.
- **M04-13'teki "önceden açılmış formların madde metni korunur" kriteri zaten sağlanıyor.** Madde metni üretim anında `MaintenanceDeviceChecks.CheckLabel` alanına kopyalanıyor (Program.cs:3047-3049). Ayrıca 87 sözleşmenin tamamı yalnızca X-Ray ve kapı dedektörü içeriyor, yani "diğer cihaz türleri" için şu an veri yok.
- **M04-07, PDF için `BuildSimpleOfferPdf` fonksiyonunu temel gösteriyor, ama bu fonksiyon işe uygun değil.** Fonksiyon metni ASCII'ye çeviriyor (Türkçe karakterleri siliyor), tek sayfa üretiyor ve görsel desteklemiyor (Program.cs:3573-3600). İmza görseli ve Türkçe metin bu yolla basılamaz.
- **Kritik bir açık kaçırılmış (M04-D01).** PB iş emri, genel durum ucundan "İptal" yapılarak bakım döngüsünün dışına çıkarılabiliyor. Bu durum sözleşmenin sonraki bütün dönemlerini kilitliyor.
- **İkinci bir seed sorunu kaçırılmış (M04-D03).** Cihaz kütüğü seed MERGE'ü de (Seed:2337-2340) seri no, konum ve aktiflik alanlarını her kurulumda ezer. M04-09 ve M04-10'un kütüğe yazacağı her şey geri alınır.

---

## 2. Madde madde değerlendirme

### M04-01 · DEĞİŞTİR · P1 — Yıl devrinde dönemlerin "tamamlandı" sayılması

**Doğrulama:** İddia doğru.
- `year = today.Year` (Program.cs:2898) ve `completed = Min(CompletedCount, Frequency)` (:2924).
- Plan upsert'te `@Completed = seq <= completed` (:2950).
- Bir dönem kapandığında `CompletedCount` bir artıyor ve hiç sıfırlanmıyor (:2546).
- Sözleşme listesi yalnızca `PlanYear = YEAR(GETDATE())` planlarını gösteriyor (:2309).
- Seed MERGE büyük olan sayacı koruyor (Seed:2440).

KENTPARK (frekans 1, sayaç 1, dönem 01.09.2026–01.09.2027) gibi sözleşmeler 2027'de doğrudan "tamamlandı" yazılır.

**Ek sorun:** Seed'deki `CompletedCount` değerlerinin bir kısmı önceki sözleşme dönemine ait. Örneğin PİAZZA İSTANBUL'un dönemi 15.01.2025–15.01.2026 ve sayacı 1 (Seed:2349). Bu değer 2026 takvim yılının 1. bakımını şimdiden "tamamlandı" yapıyor olabilir. Yani hata 2027'yi beklemeden bugün de veri bozuyor olabilir.

**Neden değiştirildi:** "Sözleşme dönemi" anahtarı ancak M04-03 ve M04-D02 ile oluşacak başlangıç/bitiş tarihlerine dayanabilir. Madde iki adıma bölünmeli. Böylece kritik düzeltme L eforlu sözleşme CRUD'unu beklemez.

**Düzeltilmiş tanım:**
- **Adım 1 (hemen, S/M):**
  - Tamamlanan adet `MaintenancePlans` (IsCompleted=1) üzerinden ve ilgili dönem için sayılır.
  - `CompletedCount` yalnızca göç yılının (2026) plan satırları oluşturulurken başlangıç değeri olarak kullanılır. Sonraki yıllara uygulanmaz.
  - Sözleşme listesi, yıl filtresi olmadan en eski açık planı gösterir.
- **Adım 2 (M04-04 ile):** Dönem anahtarı takvim yılından sözleşme dönemine geçirilir.

**Kabul kriterlerine eklenecekler:**
- 4) Göç scripti mevcut 2026 plan satırlarını değiştirmez. `CompletedCount > 0` olan sözleşmeler M04-D02 teyit listesinde ayrıca görünür.

### M04-02 · DEĞİŞTİR · P1 — Ayrıştırılamayan sözleşmelerin sessizce atlanması

**Doğrulama:** Mekanizma doğru.
- Regex (:2990), `counts.Count == 0` ise `return 0` (:2999), `AnnualFrequency > 0` filtresi (:2907).
- KENTPARK yalnızca **kısmi** eşleşiyor: X-Ray okunuyor, kapı okunmuyor. Kısmi eşleşme `Count == 0` koşuluna da girmediği için hiçbir uyarı üretmez.

**Hatalı noktalar:**
- KENTPARK sayacı 1/1 olduğu için 2026'da hiç üretim yapılmıyor. Kabul 3'teki "mevcut 11 X-Ray PB tekrar açılmaz" ifadesi gerçek veriyle test edilemez.
- SEGATECH ("7 ADET KAPI DEDEKTÖRÜ", Seed:2375) atlanmış. Frekansı 1, sayacı 0. Ocak 2026'da 7 PB üretilmesi gerekirken hiç üretilmedi.

**Atlanan ek risk:**
- Cihaz adedi 0 veya 500'den büyükse `InvalidOperationException` fırlatılıyor (:2996). Bu kontrol transaction başlamadan önce yapılıyor.
- Hata yakalanmadığı için üretim döngüsünün tamamı yarıda kalır.
- Başlangıçta hata yeniden fırlatılır (:36-39) ve **servis hiç açılmaz**.

**Düzeltilmiş tanım:**
- `generate-due` (ve başlangıç üretimi) şu biçimde yanıt döner: `{generated, skipped:[{contractId, sourceKey, customer, reason}]}`.
- Atlama gerekçeleri:
  - frekans tanımsız/0
  - cihaz adedi okunamadı
  - **metinde tanınmayan cihaz ifadesi kaldı (kısmi eşleşme)**
  - adet aralık dışı
  - sözleşme süresi dolmuş (M04-D02 sonrası)
- Tek sözleşmenin hatası üretimin geri kalanını ve uygulamanın açılışını durdurmaz. Hata yakalanır ve `skipped` listesine yazılır.
- Regex, "N ADET KAPI DEDEKTÖRÜ" ve "DEDEKTÖÜ" gibi bilinen varyasyonlar için genişletilmez. Bu kayıtlar teyit listesine düşer, çünkü kaynağı teyit edilmemiş adet uydurulmamalı.
- Bakım sayfasında kırmızı uyarı kutusu gösterilir.

**Düzeltilmiş kabul kriterleri:**
1. Seed verisiyle çalışan üretimde SEGATECH "kapı dedektörü adedi okunamadı", KENTPARK "metinde tanınmayan ifade: KAPI DEDEKTÖÜ", Ziraat ve Sanko "frekans tanımsız" gerekçesiyle listelenir.
2. Test verisinde ürün metni "600 X-RAY" olan bir sözleşme varken uygulama açılır, diğer sözleşmeler için üretim tamamlanır, bu sözleşme `skipped` listesinde görünür.
3. Sayacı 0 olan test sözleşmesinde metin "11 X-RAY 8 KAPI DEDEKTÖÜ" iken 11 PB açılır ve uyarı verilir. Metin düzeltildikten sonra 8 yeni PB açılır, mevcut 11 PB tekrar açılmaz.

### M04-03 · DEĞİŞTİR · P1 — Sözleşme yönetimi (CRUD)

**Doğrulama:**
- Yazma ucu yok, yalnızca GET var (:2288-2345).
- Alanlar serbest metin.
- Seed MERGE `IsActive=1` yazıyor (Seed:2441).
- Bu ezme yalnızca `RunDatabaseSetupOnStartup=true` olduğunda gerçekleşiyor (:26-34).

**Neden değiştirildi:**
1. Seed sorunu iki tabloyu (sözleşme ve cihaz kütüğü) birlikte etkiliyor ve S efor ile bağımsız çözülebiliyor. Bu yüzden bu maddeden çıkarılıp **M04-D03** olarak ayrıldı.
2. Kapsam için iki model birden ("kütükten cihaz seçimi veya tür+adet") ilk sürümde gereksiz karmaşıklık. İlk sürüm yalnızca **tür+adet** satırlarıyla yapılmalı. Cihaz kimliğiyle bağlantı M04-09 ile kurulur.
3. P1 öncelik: yeni ve yenilenen sözleşmeler bugün yalnızca SQL ile girilebiliyor. Bu, pilotta iş akışını durduruyor.

**Düzeltilmiş tanım:**
- Sözleşme ekle, düzenle, pasifle. Alanlar: müşteri, saha adresi, başlangıç/bitiş tarihi, yıllık adet, isteğe bağlı sabit aylar, sorumlu şef, durum.
- Cihaz kapsamı `MaintenanceContractDevices(ContractId, DeviceType, Quantity)` tablosunda tutulur.
- Üretim, kapsam satırı olan sözleşmede `ProductsText` yerine bu satırları kullanır. Satırı olmayan eski kayıtlar M04-02 yoluyla regex ile devam eder.
- Ücret alanları yalnızca `finance.prices.view` sahibi tarafından görülür ve yazılır.
- İzin önerisi [varsayım]: `maintenance.contracts.manage`.

Kabul kriterleri 1, 3 ve 4 aynen kalır. Kabul 2 M04-D03'e taşındı.

### M04-04 · DEĞİŞTİR · P1 (parçalı) — Dönem takvimi ve önizlemeli üretim

**Doğrulama:**
- Ocaktan eşit aralık hesaplanıyor (:2928-2930).
- `TargetDate` her çalıştırmada eziliyor (:2941).
- Her kapanışta global üretim tetikleniyor (:536-540).
- `CreatedByUserId` NULL (:3086).

Tüm iddialar doğru.

**Atlanan ek risk:** :536-540'taki çağrılar transaction commit edildikten **sonra** çalışıyor. Üretim bir istisna atarsa (bkz. M04-02), durum zaten kaydedilmiş olduğu halde istemci 500 hatası alır. Kullanıcı tekrar dener. Ayrıca bu üretim, Güvenlik Sistemleri dışındaki birimlerin iş emri kapanışlarında da çalışır.

**Neden değiştirildi:** Madde öncelik açısından ikiye bölünmeli:
- **4a (P1, S):** Global üretim, iş emri kapanışından kaldırılır. Üretilen PB'ye `CreatedByUserId` olarak tetikleyen kullanıcı yazılır. Başlangıç üretimi yalnızca açık bir ayarla çalışır.
- **4b (P2, M):**
  - Hedef tarih sözleşme başlangıcından veya sabit aylardan hesaplanır.
  - Elle verilen tarih gerekçeyle korunur.
  - Önizleme ve üretim kaydı tutulur.
  - Ön açılış günü kullanılır. Kod bugün `nextTarget > today` kontrolüyle tam hedef gününde açıyor; N gün önce açmak için bu koşul değişmeli.

Ön açılış ve tolerans günleri S4 yanıtına bağlı bir ayar olmalı. 30 gün varsayımdır. Kabul kriterleri aynen geçerlidir. Kriter 4 ve 5, 4a'ya aittir.

### M04-05 · DEĞİŞTİR · P2 — Uygunsuzluk aksiyon takibi

**Doğrulama:**
- Uygunsuzlukta "Tamamlandı" engeli var (:2503-2504) ve iş emri Beklemede'ye geçiyor (:2512).
- Not kolonu yok (V18:32-44).
- Form, `OpsHolds` kaydı oluşturmadan durumu doğrudan "Beklemede" yapıyor. Bu yüzden operasyon ekranında bekleme nedeni boş görünür.

**Neden değiştirildi:** Tasarım fazla mühendislik içeriyor:
- 5 aksiyon türü
- Otomatik arıza iş emri açılması
- PB'nin yeniden değerlendirilmesi akışı
- M04-08'e zorunlu bağımlılık

Ayrıca S1 (uygunsuzlukta dönem "yapıldı" sayılır mı?) yanıtlanmadan aksiyon kapanış kuralı netleşmez.

**Düzeltilmiş tanım:**
1. **S efor:** Uygunsuz ve Kontrol Edilemedi maddelerde not zorunlu olur (`CheckNote`). Form Beklemede'ye geçerken mevcut `OpsHolds` altyapısına "Uygunsuzluk" nedeniyle kayıt açılır.
2. **M efor:** Basit bir aksiyon tablosu kurulur. Alanlar: madde, tür (yerinde giderildi / teklif / arıza iş emri / müşteri kaynaklı), sorumlu, hedef tarih, bağlı iş emri/teklif, kapanış notu ve kapatan kişi.
   - Arıza iş emri **otomatik açılmaz**. "Bağlı arıza iş emri aç" butonu, seri ve müşteri alanları önceden dolu bir iş emri formu açar.
   - M04-08'e bağımlılık kaldırılır.

**Kabul kriterleri:** 1, 2, 4 ve 5 aynen kalır. Kriter 3 "buton ile açılan iş emri karşılıklı bağlı görünür" olarak değişir.

### M04-06 · DEĞİŞTİR · P2 — Müşteri onayı ve imza

**Doğrulama:** Onay alanı ve tablosu yok, iddia doğru.
- Projede dosya ve görsel saklama altyapısı **yok**. `IFormFile` ya da varbinary kullanımı bulunmuyor.
- İmza görseli ve kağıt form fotoğrafı için ayrıca bir depolama kararı gerekir: DB'de varbinary mı, sunucuda dosya mı? Linux kurulumundaki yedekleme ve KVKK saklama süresi de bu karara dahil.

**Neden değiştirildi:** S2 ve S3 yanıtlanmadan onay zorunlu yapılırsa, sahada müşteri yetkilisi bulunmadığında kapanışlar bloke olur. Madde iki adıma bölünmeli:
- **Adım 1:** Onaylayan ad-soyad, unvan ve yöntem tutulur. Yöntemler: "ekranda imza", "kağıt form imzalandı (form no)" ve "imtina + gerekçe". Zaman sunucudan alınır. Tek onay, aynı ziyaretteki birden çok forma bağlanabilir.
- **Adım 2:** Depolama kararı verildikten sonra imza görseli ve fotoğraf eklenir.

Onayın zorunluluğu bir ayar olmalıdır.

### M04-07 · DEĞİŞTİR · P2 — Basılı form eşlemesi ve çıktı

**Doğrulama:** Form çıktısı yok, iddia doğru.

**Neden değiştirildi:**
- Önerilen sunucu PDF'i yaklaşımı yanlış temele dayanıyor. `BuildSimpleOfferPdf` Türkçe karakterleri ASCII'ye çeviriyor, tek sayfa üretiyor, en fazla 15 satır alıyor ve görsel desteklemiyor (:3573-3600).
- Yeni bir PDF kütüphanesi eklemek yerine, mevcut web arayüzünde **yazdırılabilir HTML form sayfası** (print CSS) üretilmeli. Kullanıcı bu sayfayı tarayıcıdan "PDF olarak kaydet" ile çıktı alır. Bu yaklaşım teknoloji yığınını korur ve imza görselini basabilir.
- M04-06'ya bağımlılık **zayıf**. Onay alanı boşsa "onay yok" yazılabilir. Bu madde M04-06'dan önce geliştirilebilir.
- S5 yanıtı (basılı formun örneği) gelmeden düzen kesinleşmez.

**Düzeltilmiş tanım:** `GET /api/maintenance/workorders/{id}/print` bir veri ucudur. Form ekranı bu verinin yazdırma görünümünü gösterir. Ziyaret bazında toplu çıktı da alınabilir.
- Başlangıç ve bitiş saatleri `WorkOrderLiveSessions` ile zaman kayıtlarından alınır. Kayıt yoksa "süre kaydı eksik" yazılır.
- Mola, kişi-saate dahil edilmez.
- Fiyat ve maliyet alanları çıktıya girmez.

Kabul kriterleri aynen kalır ("PDF" ifadesi "yazdırma çıktısı" olarak okunur).

### M04-08 · DEĞİŞTİR · P2 — Ziyaret geçmişi

**Doğrulama:** Doğru.
- UPDATE işlemi kontrol satırlarının üzerine yazıyor (:2483-2493).
- Kayıtta ad metni tutuluyor (:2488, :2530).

Bu durum kalite kanıtının kaybına yol açıyor, ancak iş akışını durdurmuyor. Öncelik P2.

**Neden değiştirildi:** Ziyaret kaydı her `Complete=true` çağrısında oluşturulmalı. Taslak kayıtta oluşturulmamalı, aksi halde gereksiz tekrar oluşur. Kontrol sonuçları ayrı bir tabloya yazılmalı.

İki tablo yerine tek bir `MaintenanceVisits` tablosu kullanılabilir. Bu tabloda kontrol sonuçları ve notlar JSON kolonunda (`ChecksJson`) tutulur. Bu, raporlama (M04-12 "en sık uygunsuz maddeler") için de yeterlidir, çünkü SQL Server `OPENJSON` destekliyor. Hangisinin seçileceği uygulama aşamasında kararlaştırılır.

Kabul kriterleri aynen kalır.

### M04-09 · DEĞİŞTİR · P2 — Kütüğe bağlama ve cihaz geçmişi

**Doğrulama:**
- Sıra numarasıyla eşleme yapılıyor (:3010-3016, :3032).
- Form kütüğe hiçbir şey yazmıyor.
- `/api/security/devices/{id}/history` ucu yok. Yalnızca liste ucu var (:2232).

Tüm iddialar doğru.

**Neden değiştirildi:**
1. Kütük seed MERGE'ü `SerialNo`, `Location` ve `IsActive=1` alanlarını yeniden yazıyor (Seed:2337-2340). M04-D03 tamamlanmadan "onaylı seri ve bölgeyi kütüğe yaz" adımı kalıcı olmaz. Bağımlılığa M04-D03 eklenmeli.
2. "SecurityDeviceId zorunlu hale getirilmeye çalışılır" ifadesi ölçülebilir değil. Yerine şu kural konmalı: "Yeni dönemin cihaz satırı, aynı sözleşmenin önceki dönemindeki satırın `SecurityDeviceId`, `SerialNo` ve `Zone` değerlerini devralır. Sıra eşleşmesi yalnızca ilk dönemde ve kütük bağlantısı yoksa kullanılır."
3. Kütüğe yeni cihaz ekleme önerisi ve şef onayı ikinci adıma bırakılmalı.

**Kabul kriterleri:** Aynen kalır. Ek kriter: 5) `RunDatabaseSetupOnStartup=true` ile yeniden başlatıldıktan sonra kütüğe yazılan seri ve bölge korunur.

### M04-10 · KABUL · P1 — Cihazın dönem dışı bırakılması

**Doğrulama:**
- "Servis İptal" sonucu iş emrini Beklemede'ye, cihazı Bekliyor'a çeviriyor (:2511-2512).
- Dönem yalnızca tüm cihazlar Tamamlandı olduğunda kapanıyor (:2539-2541).

**Önceliğin P1 olmasının nedeni:** Tasarımcının belirttiğinden daha ağır bir etki var. Sonraki dönem sıra numarası yalnızca `CompletedCount + 1` ile belirleniyor (:2954). Tek bir sökülmüş cihaz, **sözleşmenin o yılki sonraki bütün bakım dönemlerinin üretimini** durdurur.

Bu maddenin, M04-D01 ile engellenecek "İptal" yolunun meşru karşılığı olduğu not edilmeli. Kütük pasifleme M04-D03 olmadan kalıcı olmaz.

### M04-11 · DEĞİŞTİR · P3 — Yedek parçanın stoka bağlanması

**Doğrulama:**
- Parça alanı serbest metin.
- Stok çıkışı `warehouse.manage` gerektiriyor ve iş emrine bağlı (OpsSuite.cs:188-213).
- Stok listesi maliyeti zaten `finance.prices.view` ile gizliyor (:173).

**Neden değiştirildi:** Planlı bakımda parça kullanımı düşük hacimli ve serbest metin bugün işi durdurmuyor. S10 (depo onayı mı, doğrudan düşüm mü?) yanıtlanmamış. Ayrı bir talep tablosu ve onay akışı bu aşamada fazla.

**Düzeltilmiş tanım (P3):**
- Formda isteğe bağlı olarak katalogdan parça ve adet seçilir. Bu seçim yalnızca bilgi kaydıdır.
- Depo, mevcut `/api/ops/stock/movement` ucuyla PB iş emrine bağlı çıkış yapar. Depo ekranında "PB'de bildirilen ama stok çıkışı yapılmamış parçalar" listesi gösterilir.
- Onay akışı S10 yanıtına göre sonra eklenir.

### M04-12 · DEĞİŞTİR · P2 — KPI ve rapor

**Doğrulama:**
- Ekranda yalnızca sayılar var (app.js:665).
- Excel'de "Açık Planlı Bakım" sayısı ve iş emri listesi var (Program.cs:3659 ve devamı).

**Neden değiştirildi:** KPI'ların çoğu henüz yapılmamış maddelere (M04-05, 06, 08) bağlı. Madde iki adıma bölünmeli:
- **12a:** M04-01 ve M04-04a'dan hemen sonra yapılır. Kapsamı:
  - geciken dönem listesi (gecikme günü, açık cihaz sayısı)
  - uyum oranı
  - "süre kaydı eksik" kapalı PB sayısı

  Bu adım, yönetimin "hangi planlı bakımlar yapılmadı?" sorusunu doğrudan yanıtlar.
- **12b:** İlgili maddelerden sonra yapılır. Kapsamı: uygunsuzluk oranı, açık aksiyon yaşı, onaysız kapanış.

Kabul kriterleri adımlara bölünerek aynen kalır.

### M04-13 · DEĞİŞTİR · P3 — Kontrol şablonlarının veriye taşınması

**Doğrulama:** Şablon kodda sabit tanımlı (:3105-3134).

**Bulgular:**
- 87 sözleşmenin ürün metinlerinin **tamamı** yalnızca X-Ray ve kapı dedektörü içeriyor. "El tipi" ve "araç altı" gibi türler için veri yok.
- Kabul 2 ("eski formların madde metni değişmez") **zaten sağlanıyor**, çünkü `CheckLabel` üretim anında kopyalanıyor (:3047-3049).

**Neden değiştirildi:** S7 olumlu yanıtlanana kadar ertelenmeli. Ölçüm değeri gereksinimi (S6, örneğin radyasyon kaçak ölçümü) gelirse şablon tablosu o zaman `ValueType`/`Unit` alanlarıyla birlikte tasarlanmalı. Kabul 2 kriterden çıkarılmalı.

### M04-14 · DEĞİŞTİR · P2 — Kullanıcı kimliği ve gerekçeli yeniden açma

**Doğrulama:**
- Kayıtlarda ad metni tutuluyor (:2488, :2530).
- Erişim kontrolü `RoleName == "Teknisyen"` ve ad eşleşmesiyle yapılıyor (:3398-3400).
- Kapalı form değiştirilemiyor (:2473).
- Sözleşme listesine erişmek için `workorders.view` yeterli (:2292).

Tüm iddialar doğru.

**Neden değiştirildi:**
- `CanAccessWorkOrderAsync` ve `WorkOrderAssignments.AssignedName` tüm iş emirlerinde ortak kullanılıyor. "Kendi işleri" bayrağı ve UserId ile atama **genel iş emri modülünün** maddesidir. Bu madde yalnızca ona bağımlılık olarak referans vermeli, aynı işi tekrar tasarlamamalı.
- Bu modüle özgü kalan işler:
  - form, kontrol ve ziyaret kayıtlarına `...ByUserId` alanları
  - `maintenance.reopen` [varsayım] ile gerekçeli yeniden açma
  - sözleşme listesinin `maintenance.view` iznine bağlanması

  Teknisyen adres bilgisini zaten form ucundan (`customerAddress`) alıyor, bu yüzden sözleşme listesine erişimi gerekmez.
- Yeniden açma işlemi kaydın önceki halini ziyaret kaydında (M04-08) korumalı ve sayacı geri almalı. Kapanmış bir dönem yeniden açılırsa `IsCompleted` ve `CompletedCount` tutarlı şekilde geri alınmalı. Bu kural kabul kriterlerine eklenmeli.

---

## 3. Tasarımcının kaçırdığı maddeler

### M04-D01 · HATA/VERİ · P1 — PB iş emrinin genel durum ucundan "İptal" ile bakım döngüsünün dışına çıkması

**Mevcut durum:**
- `PATCH /api/workorders/{id}/status` (Program.cs:473-543) gelen `Status` değerini bir izinli liste ile doğrulamıyor.
- Cihaz PB engelleri yalnızca `IsClosingStatus` için çalışıyor (:510-513), yani "Tamamlandı", "Kapatıldı" ve "Çözüldü" için (:2808). **"İptal" bu listede yok.**
- Arayüzdeki durum listesi "İptal" seçeneğini içeriyor (app.js:30).
- Teknisyen rolünde `workorders.edit` izni var (:3930).

**Sonuç:**
- PB iş emri "İptal" yapıldığında cihaz satırı "Bekliyor" olarak kalır ve dönem hiç kapanmaz.
- `CompletedCount` artmadığı için sözleşmenin sonraki dönemleri hiç üretilmez (:2954).
- Bu durum hiçbir uyarı vermez. Ayrıca "İptal" iş emri formdan yeniden kapatılabildiği için durum geçmişi de tutarsız hale gelir.

**Olması gereken:**
- Cihaz PB iş emirlerinde "İptal" ve izinli liste dışındaki durumlar reddedilir. Cihazı dönemden çıkarmanın tek yolu M04-10 olur.
- Genel uçta izinli durum listesi doğrulaması eklenir.
- Mevcut "İptal" PB'leri listeleyen bir tek seferlik kontrol sorgusu çalıştırılır.

**Kabul kriterleri:**
1. PB iş emrine `PATCH status=İptal` isteği 400 döner ve mesaj M04-10 yoluna yönlendirir.
2. Listede olmayan bir durum metni 400 döner.
3. Kontrol sorgusu, mevcut "İptal" durumundaki PB'leri ve bunların dönemlerini listeler.

**Efor:** S

### M04-D02 · VERİ · P1 — Mevcut 87 sözleşmenin yapısal alanlara göçü ve teyit listesi

**Mevcut durum:** `PeriodText` alanı tutarsız biçimlerde girilmiş:
- "5. VE 11. AYDA" (Seed:2355)
- "17.02.2026-17.02-2027" (:2427)
- "01.03.2026-01.03.2026" (:2429)
- Süresi dolmuş "18.11.2025-18.11.2025" (:2421)
- NULL (Ziraat, Sanko)

Ayrıca:
- `CompletedCount` değerinin hangi döneme ait olduğu belirsiz (örneğin Piazza, :2349).
- Süresi dolmuş sözleşmeler (MNG KARGO) bugün de PB üretiyor.

Tasarımda bu konu yalnızca soru olarak (S9) geçiyor, bir madde olarak yer almıyor. Oysa M04-01, M04-03 ve M04-04 bu veriye bağımlı.

**Olması gereken:**
- Tek seferlik göç scripti `PeriodText` alanını StartDate/EndDate/FixedMonths alanlarına ayrıştırır, `ProductsText` alanını tür+adet satırlarına çevirir.
- Ayrıştırılamayan, çelişkili veya süresi dolmuş kayıtlar Excel'e alınabilen bir teyit listesine düşer.
- Kullanıcı teyit edene kadar bu kayıtlar üretimde M04-02 `skipped` listesinde görünür.

**Kabul kriterleri:**
1. Script iki kez çalıştırıldığında sonuç değişmez.
2. 87 kaydın her biri ya "ayrıştırıldı" ya da "teyit bekliyor (gerekçe)" durumundadır.
3. Bitiş tarihi geçmiş bir sözleşme için yeni PB üretilmez.

**Efor:** S

### M04-D03 · VERİ · P1 — Seed MERGE'lerinin ekrandan girilen veriyi ezmesi

**Mevcut durum:** `RunDatabaseSetupOnStartup=true` olduğunda bütün `*.sql` dosyaları her başlatmada yeniden uygulanıyor (Program.cs:26-34).
- Sözleşme MERGE'ü (Seed:2437-2441): tüm alanları ve `IsActive=1` değerini yazıyor.
- Cihaz kütüğü MERGE'ü (Seed:2337-2340): `SerialNo`, `Location`, `IsActive=1` değerlerini yazıyor.

**Sonuç:** M04-03, M04-09 ve M04-10'un yaptığı her düzenleme (pasifleme, seri ve bölge düzeltmesi) bir sonraki kurulum ya da güncellemede geri alınır. Bu sessiz bir veri kaybıdır.

**Olması gereken:**
- Seed yalnızca `WHEN NOT MATCHED` durumunda ekleme yapar, ya da bir `SeedApplied` işaret tablosu ile tek seferlik çalışır.
- Var olan satırlara bir daha dokunulmaz.

**Kabul kriterleri:** Ekrandan pasiflenen bir sözleşme ve seri numarası düzeltilen bir kütük cihazı, `RunDatabaseSetupOnStartup=true` ile iki kez yeniden başlatıldıktan sonra değişmeden kalır.

**Not:** Cihaz kütüğü tarafı, cihaz kütüğü modülüyle ortak bir maddedir.

**Efor:** S

---

## 4. Önerilen uygulama sırası

Kullanıcının öncelik sırası c → b → a. Veri kaybı ve iş akışı blokajı yaratan maddeler bu sıradan bağımsız olarak öne alınmıştır.

1. **Veri güvencesi (hepsi S/M, birlikte bir sürüm):** M04-D03 → M04-D01 → M04-02 → M04-01 (Adım 1) → M04-04a → M04-D02
2. **Yeni özellik (c):** M04-03 → M04-04b → M04-07 (yazdırma görünümü) → M04-06 (Adım 1)
3. **Mevcut eksik (b):** M04-10 (P1, bu grubun en başında) → M04-12a → M04-08 → M04-05 → M04-09 → M04-12b
4. **Güvenlik (a):** M04-14 (genel iş emri modülündeki "kendi işleri" maddesiyle birlikte)
5. **Sonraya (P3):** M04-11, M04-13

## 5. Kullanıcı soruları hakkında not

Tasarımın S1–S10 soruları yerinde. Şu maddeler bu yanıtlar gelmeden kesinleştirilmemeli:
- M04-05 → S1
- M04-06 → S2, S3
- M04-04b → S4
- M04-07 → S5
- M04-13 → S6, S7
- M04-D02 → S9
- M04-11 → S10

S9'a SEGATECH (BAKIM-0029) kaydı eklenmeli.
