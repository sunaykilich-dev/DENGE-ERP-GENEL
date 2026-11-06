# A2 — Mimari ve Kod Kalitesi Denetimi (DengeERP V1.20.1)

> **Tarih:** 21 Ekim 2026
> **Kapsam:** `kaynak/V1_20_1_orijinal/DengeERP.Api` — `Program.cs` (3.937 satır), `OpsSuite.cs` (280 satır), `wwwroot/app.js` (234 KB), `wwwroot/ops120.js`, `Database/*.sql`, `linux/` dağıtım dosyaları.
> **Yöntem:** Kod satır satır okunarak doğrulandı. Kaynak koda dokunulmadı. Derleme/çalıştırma yapılmadı. Çalışma zamanı davranışına dair çıkarımlar "doğrulanmadı" diye işaretlendi.
> **Önceliklendirme notu:** Kullanıcı kararı gereği iş sırası (c) yeni modül → (b) mevcut modül eksikleri → (a) güvenlik/üretim. Bu raporda önem derecesi **etkiye** göre verildi; veri kaybı/sızıntısı yaratanlar karara uygun olarak **KRİTİK** işaretlendi. Uygulama sırası önerisi en sonda c→b→a sırasına göre verilmiştir.

---

## 1. Özet

DengeERP V1.20.1, işlevsel olarak zengin ama **yapısal olarak tek parça** bir pilottur. Backend, 70 uç noktanın tamamını tek `Program.cs` dosyasında üst düzey lambda'lar olarak tanımlar (V1.20'deki 12 uç `OpsSuite.cs`'e ayrılmış; bu iyi bir ilk örnek). Ön yüz tek bir 234 KB `app.js` dosyasıdır (2.047 satır, en uzun satır 1.860 karakter, 147 üst düzey fonksiyon, tek global `state`).

**Güçlü yanlar (korunmalı):**
- İncelenen tüm SQL sorguları parametreli; dinamik SQL yalnızca sabit parçalardan/parametre adlarından üretiliyor (`ReadBulkTargetsAsync` Program.cs:3319-3336).
- Çok adımlı yazmaların çoğu tek transaction içinde (iş emri açma, toplu atama/plan, kiralama kompozisyonu, bakım formu).
- Canlı zaman sayacı, envanter tahsisi ve stok hareketi `Serializable` + `UPDLOCK,HOLDLOCK` + filtreli unique index ile doğru korunmuş (Program.cs:1942-1982, 1384-1433; OpsSuite.cs:194-212; ZZ_V114:27, ZZ_V112:68).
- CSV enjeksiyon koruması (Program.cs:1725, OpsSuite.cs:66-70), PBKDF2 parola hash'i.

**Ana sorunlar:**
1. **Kurulum betiği yanlış veritabanına yazabilir** (`USE DengeERP;`) — DengeERP_TEST hedeflenirken canlı adlı DB değişir (KRİTİK).
2. **Fiyat maskelemesi merkezi değil**; atölye tamir tutarı ve teklif fiyatları `finance.prices.view` olmadan API'den dönüyor (KRİTİK — kullanıcı kararı ihlali).
3. **Bakım planında yıl devri hatası**: 2027'ye geçildiğinde planlar "tamamlanmış" doğabilir (YÜKSEK).
4. **İş emri kapatma, commit sonrası tüm bakım üretimini senkron tetikliyor**; hata olursa kullanıcı hata görür ama durum kaydedilmiştir (YÜKSEK).
5. **Üç farklı saat kaynağı** (uygulama `DateTime.Now`, SQL `SYSDATETIME`, tarayıcı UTC `toISOString`) — tarih kayması hataları kodda kesin (YÜKSEK).
6. **Kişi kimliği isim metni** ile eşleşiyor (atama, süre, çakışma, teknisyen erişimi) (YÜKSEK).
7. **Durum makinesi yok**; aynı iş kuralı (kapatma koşulları, durum geçmişi) bazı yollarla atlanabiliyor (YÜKSEK).
8. **Sayfalama yok, tüm tablo belleğe yükleniyor**; tek kaydı doğrulamak için bile tüm iş emirleri okunuyor (YÜKSEK).
9. **Tekrar eden kod ve test edilemezlik**: kimlik/izin kalıbı 67 kez, `new SqlConnection` 70 kez, numara üretimi 6 kopya; test projesi yok (YÜKSEK).

**Öneri:** Tam yeniden yazım değil; mevcut `OpsSuite.Map(...)` kalıbını örnek alarak **davranışı değiştirmeden** dosyalara bölme, ortak kesişen kaygıları (kimlik/izin filtresi, saat, numara, durum geçişi, fiyat maskesi) tek yere toplama ve önce karakterizasyon testleri ekleme (Bölüm 4).

---

## 2. Bulgular tablosu (önem sırasıyla)

| ID | Önem | Başlık | Konum (dosya:satır) |
|---|---|---|---|
| A2-01 | KRİTİK | Şema betiği `USE DengeERP;` ile hedef DB'yi değiştiriyor | Database/DengeERP_Update.sql:1; Program.cs:26-31, 3257-3269 |
| A2-02 | KRİTİK | Fiyat/ücret maskelemesi merkezi değil; atölye tutarı ve teklif fiyatları yetkisiz rollere dönüyor | Program.cs:2560-2626 (2599), 790-798, 883-893, 3520-3539 |
| A2-03 | YÜKSEK | Bakım planı yıl devri: `CompletedCount` yıl bazlı değil, yeni yıl planları tamamlanmış doğuyor | Program.cs:2894-2982 (2924, 2950) |
| A2-04 | YÜKSEK | İş emri kapatma sonrası transaction dışı, ağır ve hataya açık bakım üretimi | Program.cs:533-540, 2894-3102, 3136-3175 |
| A2-05 | YÜKSEK | Saat dilimi: üç farklı saat kaynağı, UTC/yerel karışımı | app.js:5, 697, 739, 870; Program.cs:386, 814, 1098, 1443, 2126, 2643, 2677, 2863, 2897; OpsSuite.cs:28, 83, 87, 101-104; linux/dengeerp.service |
| A2-06 | YÜKSEK | Kişi kimliği isim metniyle eşleştiriliyor | Program.cs:1945, 1962, 2041, 2120, 2135, 2140, 3391-3400, 3499-3500; OpsSuite.cs:89 |
| A2-07 | YÜKSEK | Durum makinesi yok; kapatma kuralları ve durum geçmişi farklı yollarla atlanabiliyor | Program.cs:473-543, 722-761, 2746-2772, 2808; OpsSuite.cs:130-159; app.js:30-31 |
| A2-08 | YÜKSEK | Sayfalama yok; tüm tablo yükleme, bellek içi filtre, O(n·m) döngüler | Program.cs:3441-3493, 1908-1927, 2181-2229, 3677, 2232-2285; OpsSuite.cs:80-82, 114, 135, 150, 193, 218-234, 250; app.js:137-155, 392-406 |
| A2-09 | YÜKSEK | Tek dosya backend, tekrar eden kod, test edilemez yapı | Program.cs genel (70 uç); 386/814/1098/2643/2677/3076; 1936/1997/2122/3695; 3638, OpsSuite.cs:9, app.js:127, 408 |
| A2-10 | ORTA | Hata yönetimi: global yakalayıcı/loglama yok, doğrulanmayan girdiler 500 üretiyor | Program.cs:38, 63, 76, 370-414; OpsSuite.cs:138-143, 180, 191, 241, 251; Properties/launchSettings.json; app.js:96-106 |
| A2-11 | ORTA | Eşzamanlılık: `RowVersion` var ama kullanılmıyor; son yazan kazanır | DengeERP_Update.sql:21; Program.cs:484-487, 545-570, 1140-1198, 1834-1860, 2707-2776 |
| A2-12 | ORTA | Migration sürüm takibi yok; betikler her açılışta yeniden çalışıp yetki/veri eziyor | Program.cs:26-35; DengeERP_V15_Schema.sql:147-170; DengeERP_V15_Seed.sql:2436-2443; DengeERP_Update.sql:428-432 |
| A2-13 | ORTA | Süre kaydı olmayan iş "0" olarak raporlanıyor / maliyete giriyor | Program.cs:3678; OpsSuite.cs:82, 88, 230-234 |
| A2-14 | ORTA | Excel dışa aktarımında seri no/telefon sayısal hücreye dönüşüyor | Program.cs:3759-3766 |
| A2-15 | ORTA | Ön yüz: tek dosya, global durum, kural/katalog kopyaları, sunucuda olmayan çakışma kontrolü | app.js:1-155, 9-31, 23-28, 135, 392-406; ops120.js:2-59, 102; Program.cs:649-761, 3380-3382 |
| A2-16 | ORTA | Oturumlar bellek içi ve süresiz (mimari boyut) | Program.cs:21, 94-96, 2821-2825 |
| A2-17 | ORTA | Kiralamada iki doğruluk kaynağı: serbest `Status` ve aşama geçmişi; aşama sırası denetlenmiyor | Program.cs:1140-1198, 1436-1482 |
| A2-18 | DÜŞÜK | Belge numarası üretimi 6 kopya; 9999 taşması yalnızca PB'de denetleniyor | Program.cs:386-393, 814-821, 1098-1105, 2643-2650, 2677-2684, 3076-3082 |
| A2-19 | DÜŞÜK | Yapılandırma istek içinde okunuyor; e-posta istek içinde senkron gönderiliyor | Program.cs:909-937 |

---

## 3. Bulgu ayrıntıları ve öneriler

### A2-01 — KRİTİK — Şema betiği `USE DengeERP;` ile hedef veritabanını değiştiriyor

**Konum:** `Database/DengeERP_Update.sql:1`; çalıştıran kod `Program.cs:26-31` ve `ApplySchemaAsync` `Program.cs:3257-3269`.

**Ne oluyor (kodla doğrulandı):**
- `RunDatabaseSetupOnStartup=true` olduğunda `Database/*.sql` dosyaları ada göre sıralanıp (`OrderBy(Path.GetFileName)`) her biri **kendi bağlantısında** çalıştırılır. Alfabetik sırada ilk dosya `DengeERP_Update.sql`'dir.
- Bu dosyanın ilk satırı `USE DengeERP;`. `ApplySchemaAsync` `GO` ile böldüğü batch'leri aynı bağlantıda sırayla çalıştırdığı için, dosyanın geri kalanı bağlantı dizesindeki veritabanında (Linux kurulumunda `DengeERP_TEST`, `linux/dengeerp.env.example:8`) **değil**, `DengeERP` adlı veritabanında çalışır.
- Dosyanın içinde tablo oluşturma, personel ekleme (`INSERT INTO dbo.Personnel ... DengeERP_Update.sql:422-425`) ve `UPDATE p SET ErpUserId=...` (`DengeERP_Update.sql:428-432`) bulunur.

**Etki:** İT, test kopyası ile aynı SQL örneğinde canlı `DengeERP` veritabanı varken ve SQL hesabının oraya yazma yetkisi varken bayrağı açarsa, **canlı veritabanına istem dışı yazma** olur; test DB'si ise yarım şema ile kalır. Canlı DB yoksa servis açılışta hata verir. Belgedeki "canlı Windows SQL'e farkında olmadan migration yok" kuralını kod düzeyinde bozabilir. Linux kurulum belgesi bayrağın `false` kalmasını söylediği için risk şu an **koşullu**dur (doğrulanmadı: İT'nin SQL hesabının hangi DB'lere yetkisi olduğu bilinmiyor).

**Öneri (artımlı):**
1. `DengeERP_Update.sql:1` satırını kaldırın (veritabanı seçimi bağlantı dizesinden gelmeli).
2. `ApplySchemaAsync` içinde `^\s*USE\s+` içeren batch'leri reddedin ve başlangıçta `SELECT DB_NAME()` sonucunu yapılandırmadaki beklenen adla (`DengeERP:ExpectedDatabaseName`) karşılaştırın; eşleşmezse açılmayın.
3. A2-12'deki sürüm tablosuyla birleştirin.

---

### A2-02 — KRİTİK — Fiyat/ücret maskelemesi merkezi değil; API sızıntısı var

**Kullanıcı kararı:** "Fiyat/maliyet API seviyesinde gizlenmeli" (proje belgesi §5.7, §8.1).

**Doğru uygulanan yerler (karşılaştırma için):** bakım sözleşmesi ücretleri `Program.cs:2329-2333`, yedek parça iç maliyeti `OpsSuite.cs:173`, finans ekranı `OpsSuite.cs:217`.

**Sızan yerler (kodla doğrulandı):**
- `GET /api/workshop/tickets` (`Program.cs:2560-2626`), `repairAmount` alanını (`Program.cs:2599`) **hiçbir izin kontrolü olmadan** döndürüyor. Erişim için `workshop.view` veya `workorders.view` yeterli; varsayılan **Teknisyen** rolünde `workshop.view` var (`Program.cs:3930`) ama `finance.prices.view` yok.
- `GET /api/offers` (`Program.cs:790-798` → `LoadOffersAsync` `3520-3539`) ara toplam, iskonto, KDV ve genel toplamı `offers.view` ile döndürüyor. `GET /api/offers/{id}/pdf` (`883-893`) birim fiyatları içeren PDF'i aynı izinle veriyor. Varsayılan **Operasyon Uzmanı, Şef, Genel Koordinatör, Kiralama Operasyon** rollerinde `offers.view` var, `finance.prices.view` yok (`Program.cs:3927-3933`).
- `PATCH /api/offers/{id}/status` (`Program.cs:861-881`) birim (`UnitAllowed`) kontrolü yapmıyor; başka birimin teklifi onaylanabilir.

**Not / iş kararı gerekiyor:** Teklif modülünde fiyat görmek bazı roller için işin doğası olabilir. Bu, "teklif hazırlayan kişi fiyatı görür mü?" sorusuyla kullanıcıya sorulmalı. Atölye tamir tutarı için ise kararla açık bir çelişki var.

**Kök neden (mimari):** Maskeleme her uçta elle, satır içi yapılıyor; merkezi bir "fiyat alanı" kavramı yok. Yeni modüller (c) eklendikçe aynı hata tekrar edecektir.

**Öneri:**
1. `Security/PriceMask.cs` gibi tek bir yardımcı: `decimal? Price(SessionUser u, decimal? v) => Can(u,"finance.prices.view") ? v : null;` ve tüm fiyat alanları bunun üzerinden.
2. Atölye listesinde `repairAmount` için hemen bu kontrol.
3. Teklif uçları için iş kararı sonrası: ya `offers.view` + `finance.prices.view` birlikte gereksin ya da fiyatsız teklif listesi dönülsün.
4. Her fiyat içeren uç için "yetkisiz kullanıcıda alan null" entegrasyon testi (Bölüm 4, Adım 0).

---

### A2-03 — YÜKSEK — Bakım planı yıl devri hatası

**Konum:** `EnsureMaintenancePlansAndWorkOrdersAsync`, `Program.cs:2894-2982`.

**Ne oluyor (kodla doğrulandı):**
- `year = DateTime.Today.Year` (`2897-2898`); her sözleşme için `completed = CompletedCount` (`2924`) ve o yılın planları `@Completed = seq <= completed` ile oluşturulur/güncellenir (`2950`).
- `MaintenanceContracts.CompletedCount` **yıl bazlı değildir**; artırıldığı yerler `Program.cs:2546`, `3168` ve seed MERGE (`DengeERP_V15_Seed.sql:2440`, yalnızca büyüteni alır). Kodda hiçbir yerde yıl başında sıfırlanmıyor (`CompletedCount=0` araması sonuç vermedi).

**Etki (çıkarım, doğrulanmadı — henüz yıl devri yaşanmadı):** 1 Ocak 2027'den sonraki ilk çağrıda (her iş emri kapanışında çağrıldığı için, bkz. A2-04) 2026'da 4/4 bakımı tamamlanmış bir sözleşmenin 2027 planlarının dördü de `IsCompleted=1, CompletedAt=şimdi` olarak yaratılır; `nextSeq > Frequency` olduğu için (`2954-2955`) **o yıl hiç PB iş emri üretilmez**. Kısmen tamamlananlarda ilk N dönem atlanır. Planlı bakım yapılmadığı halde "yapıldı" görünür.

**Öneri:** `CompletedCount`'u saklanan sayaç olmaktan çıkarıp ilgili yılın `MaintenancePlans` satırlarından türetin (`COUNT(*) WHERE PlanYear=@Year AND IsCompleted=1`). Geçiş için: sözleşmeye `CompletedCountYear` kolonu eklenip yalnızca o yıla eşitse kullanılması. Bu fonksiyon için yıl parametreli birim testi (2026→2027 senaryosu) yazılmalı.

---

### A2-04 — YÜKSEK — İş emri kapatma sonrası transaction dışı ve ağır bakım üretimi

**Konum:** `PATCH /api/workorders/{id}/status`, `Program.cs:533-540`.

**Ne oluyor (kodla doğrulandı):**
```csharp
await InsertStatusLogAsync(...); await transaction.CommitAsync();
if (IsClosingStatus(request.Status))
{
    await CompleteMaintenanceFromWorkOrderAsync(connectionString, id);
    await EnsureMaintenancePlansAndWorkOrdersAsync(connectionString);
}
```
- Durum değişikliği **commit edildikten sonra**, ayrı bağlantı/transaction'larla iki işlem daha yapılıyor. `EnsureIndividualMaintenanceWorkOrdersAsync` cihaz adedi geçersizse `InvalidOperationException` fırlatır (`2996`); PB numara taşmasında da fırlatır (`3081`). Bu durumda kullanıcı **500 hatası** görür ama iş emri zaten kapanmıştır; tekrar denemeler farklı sonuç verir.
- Herhangi bir (bakımla ilgisiz) iş emrinin kapanması, **tüm aktif sözleşmeler** için plan upsert'i (`2922-2952`, sözleşme × frekans kadar tek tek SQL) ve vadesi gelenler için cihaz bazında üretim çalıştırır. Üretim döngüsünde cihaz başına 1 SELECT + 10-11 `IF NOT EXISTS ... INSERT` kontrol satırı + 1 bağlama UPDATE yapılır (`3017-3098`) — klasik N+1. AKYAKA örneğinde (17 cihaz) yalnızca bir plan için ~220 gidiş-dönüş.
- Bu döngü `Serializable` transaction içinde ve `WorkOrders WITH(UPDLOCK,HOLDLOCK)` aralık kilidiyle numara alıyor (`3000`, `3077-3078`); süre uzadıkça diğer kullanıcıların iş emri açması/kapatması bloklanır (doğrulanmadı: gerçek yükte ölçülmedi).
- Aynı tetikleme `/api/maintenance/generate-due` (`2347-2356`) ile manuel olarak da mevcut.

**Öneri:**
1. Kapatma isteğinden üretimi ayırın: bakım üretimi yalnızca (a) `generate-due` ile manuel ve (b) günde bir çalışan `BackgroundService` (`PeriodicTimer`) ile yapılsın.
2. `CompleteMaintenanceFromWorkOrderAsync` gerekiyorsa aynı transaction içine alınsın.
3. Kontrol listesi satırlarını tek `INSERT ... SELECT ... WHERE NOT EXISTS` ile küme bazlı ekleyin (cihaz başına 11 sorgu yerine 1).

---

### A2-05 — YÜKSEK — Saat dilimi: üç farklı saat kaynağı

**Gözlem:** Uygulama üç saat kullanıyor ve bunları karşılaştırıyor:
- **Uygulama sunucusu yerel saati** `DateTime.Now/Today` (Program.cs'te 14 yer; OpsSuite.cs:28, 48, 60, 83, 87, 101, 103-104).
- **SQL sunucusu saati** `SYSDATETIME()/GETDATE()` (tüm `CreatedAt/UpdatedAt/ClosedAt` varsayılanları; canlı sayaç `Program.cs:1959, 2021`; `Program.cs:2309`; `OpsSuite.cs:55`).
- **Tarayıcı**: `toISOString()` UTC döndürür.

**Kodla doğrulanan kesin hatalar (sunucu TZ'sinden bağımsız):**
- `app.js:5` `todayIso = () => new Date().toISOString().slice(0,10)` UTC tarih döndürür. Türkiye'de (UTC+3) 00:00–03:00 arasında **dünün tarihi** gelir; planlama takviminin başlangıcı (`app.js:79`) ve zaman filtresi bitişi (`app.js:59`) bir gün geride açılır. `app.js:870` "yarın" hesabı da aynı hataya sahip.
- `app.js:697` atölye giriş tarihi varsayılanı `new Date().toISOString().slice(0,16)` → `datetime-local` alanına **3 saat geri** değer yazılır ve bu değer kaydedilir.
- `app.js:739` tamamlanma tarihi `new Date().toISOString()` (sonu `Z`) olarak gönderilir; `System.Text.Json` bunu `DateTimeKind.Utc` olarak okur, SqlClient `datetime2`'ye UTC değeri olarak yazar; ekranda yerel saat gibi gösterilir → **3 saat erken** tamamlanma.

**Linux'a taşımada ortaya çıkacak hatalar (doğrulanmadı — sunucunun saat dilimi ayarı bilinmiyor):** `linux/dengeerp.service` `TZ` tanımlamıyor. Ubuntu sunucu UTC'de, SQL Server Türkiye saatinde ise:
- `Program.cs:2126` manuel süre kaydı "gelecek tarih" kontrolü UTC `DateTime.Now` ile yapılır; teknisyenin **son 3 saat içinde biten** gerçek çalışması reddedilir.
- `OpsSuite.cs:83, 87` SLA gecikmesi `CreatedAt` (SQL yerel) ile UTC `DateTime.Now` karşılaştırılır; işler **3 saat geç** "gecikti" olur; "bugün/yarın" sayaçları gece yarısı civarında kayar (`OpsSuite.cs:103-104`).
- `Program.cs:386, 814, 1098, 2643, 2677` numara öneki (`SRV-yyyyMM`) ay sonu/başı 3 saatlik pencerede yanlış aya düşer.
- `Program.cs:1443` kiralama aşama tarihi denetimi, `Program.cs:2897` bakım vadesi, `Program.cs:1926` ve `OpsSuite.cs:101` ekrana dönen sunucu saati.

**Öneri:**
1. **Hızlı:** `linux/dengeerp.service` içine `Environment=TZ=Europe/Istanbul`; Windows pilotta zaten yerel.
2. **Kalıcı:** .NET 8+ `TimeProvider` soyutlaması ile tek `IClock` (Europe/Istanbul), test edilebilir. İş kuralı için zaman ya hep SQL'den (`SYSDATETIME()` sorgu içinde) ya da hep uygulamadan alınsın; karışık kullanılmasın.
3. **İstemci:** `todayIso`'yu `new Date().toLocaleDateString('sv-SE')` (ops120.js:39'da zaten bu yöntem var) ile değiştirin; `datetime-local` için yerel biçimleyici; sunucuya `Z`'li değer göndermeyin.
4. İleride çok bölgeli kullanım düşünülürse `datetimeoffset`; şimdilik gerekli değil.

---

### A2-06 — YÜKSEK — Kişi kimliği isim metniyle eşleştiriliyor

**Konum (kodla doğrulandı):**
- Atamalar `WorkOrderAssignments.AssignedName` metni (`InsertAssignmentAsync` `Program.cs:3338-3347`).
- Teknisyen erişimi: `CanAccessWorkOrderAsync` (`3391-3400`) ve `FilterWorkOrdersForUser` (`3499-3500`) `user.FullName` ile virgülle birleştirilmiş isim listesini karşılaştırıyor.
- Canlı sayaç başlatma yetkisi `AssignedName=@Name` (`1945`); süre çakışma kontrolleri `TechnicianName=@Name` (`1962`, `2041`, `2140`, `2146`); manuel süre kaydında isim istekten geliyor (`2120`).
- Personel iş yükü raporu isim gruplaması (`OpsSuite.cs:89`), Excel kişi KPI (`Program.cs:3697`).

**Etki:**
- `PUT /api/users/{id}` (`245-319`) `FullName` değiştirebiliyor. İsim düzeltilen (ör. "Ali Kaya" → "Ali Kaya (GS)") teknisyen **atandığı işleri göremez**, sayacını başlatamaz; eski süreleri raporda ayrı kişi gibi görünür; çakışma kontrolü eski kayıtları görmez → **çift sayım** mümkün.
- Aynı adlı iki personel birbirinin işini ve süresini görür.
- Virgül içeren isim (`STRING_AGG(...,', ')` + `Split(',')`) eşleşmeyi bozar.
- Organizasyon şeması gelince rol/ekip ilişkisi kurulamaz.

**Öneri (artımlı, geriye uyumlu):**
1. `WorkOrderAssignments`, `WorkOrderTimeLogs` tablolarına `PersonnelId BIGINT NULL` (ve/veya `UserId INT NULL`) ekleyin; `Personnel.FullName` ile tek seferlik backfill.
2. Yeni kayıtlar id ile yazılsın; kontroller önce id, yoksa isim ile yapılsın (geçiş dönemi).
3. API sözleşmesi: `AssignmentRequest` içine `technicianIds` eklenip isim alanı geriye uyumluluk için kalsın.

---

### A2-07 — YÜKSEK — Durum makinesi yok; iş kuralları farklı yollarla atlanabiliyor

**Kodla doğrulanan durumlar:**
- `PATCH /api/workorders/{id}/status` (`473-543`) `request.Status` için **beyaz liste yok**; istemci herhangi bir metni durum olarak yazabilir. Kapanış koşulları yalnızca `IsClosingStatus` = `Tamamlandı|Kapatıldı|Çözüldü` (`2808`) için çalışır; UI'da `Çözüldü` yok, UI'daki `Tekrar Açıldı`, `Kargoda`, `Yola Çıkıldı` (`app.js:30-31`) sunucuda tanımsız.
- **Atölye güncelleme** (`PUT /api/workshop/tickets/{id}`, `2746-2772`) bağlı iş emrini doğrudan `Kapatıldı`/`Tamamlandı` yapıyor; **açık canlı sayaç kontrolü yok** (status ucunda var: `506-509`), seri no kuralı yok, `WorkOrderStatusLogs` kaydı yok. Teknisyen rolünde `workshop.manage` var (`3930`).
- **Bekletme/bırakma** (`OpsSuite.cs:130-159`) iş emri durumunu değiştiriyor ama **durum geçmişi yazmıyor**; teknisyenin aktif sayacı varken iş "Beklemede"ye alınabiliyor.
- **Tekil plan** (`722-761`) kapalı/iptal iş emrini de `Planlandı` yapar (toplu planda bu kontrol var: `682-683`); durum geçmişine `OldStatus=null` yazar (`757`).
- **Yeniden açma:** `ClosedAt` yalnızca kapanırken set ediliyor, açılınca sıfırlanmıyor (`527`, `2761`). Yeniden açılmış iş, Excel'de "kapanış tarihi" esaslı filtrede kapanmış gibi sayılır (`2207`).
- "Açık iş" tanımı üç farklı yerde farklı: `OpsSuite.cs:8` (`Tamamlandı` kapalı), `app.js:128` (kapalı), `app.js:131` `isOpen` (`Tamamlandı` açık).

**Öneri:** `Domain/WorkOrderStatus.cs` (izinli durumlar + izinli geçişler tablosu) ve `WorkOrderStatusService.ChangeAsync(conn, tx, id, newStatus, note, user)`:
- izinli geçiş denetimi, kapanış koşulları (canlı sayaç, bakım formu, seri kuralı), `ClosedAt` yönetimi, durum geçmişi tek yerde;
- status, atölye, bekletme, plan, bakım formu uçlarının hepsi bunu çağırsın;
- "açık/kapalı" tanımı sunucudan `/api/meta` ile istemciye verilsin.

---

### A2-08 — YÜKSEK — Sayfalama yok; tüm tablo yükleme ve bellek içi filtreleme

**Kodla doğrulandı:**
- `LoadWorkOrdersAsync` (`Program.cs:3441-3493`) **tüm** iş emirlerini, satır başına 3 bağıntılı alt sorgu + `OUTER APPLY` ile okur; filtre/sayfalama yok. Birim/teknisyen filtresi sonradan bellekte yapılır (`3495-3502`).
- Bu fonksiyon şu yollardan çağrılıyor: `/api/workorders` (365), `/api/timetracking/summary` (1913), `/api/reports/worklogs` (2186), `/api/reports/workorders.xlsx` (2197), ve `OpsSuite` üzerinden overview (80), ack (114), **hold (135), release (150), stok hareketi (193), finans güncelleme (250)**, CSV (263). Son dördü yalnızca **tek bir iş emrine erişim** doğrulamak için tüm tabloyu okuyor (zaten mevcut `CanAccessWorkOrderAsync` tek satırlık sorgu ile yapılabilir).
- Alarm onaylama (`OpsSuite.cs:111-121`) tek bir anahtarın geçerliliği için tüm uyarıları yeniden hesaplıyor.
- `LoadTimeLogsAsync` (`3424-3439`) tüm süre kayıtlarını okur; worklogs, xlsx, summary, ops overview, ops finance bunu tam yükler.
- **Giriş anında** (`app.js:137-155`) istemci 12'ye kadar isteği **sırayla** (`await` zinciri) yapar; sunucu tarafında bu, `LoadWorkOrdersAsync` 3 kez, `LoadTimeLogsAsync` 2 kez, `LoadLiveTimersAsync` 2 kez çalışması demektir.
- O(n·m) döngüler: Excel'de her iş emri için tüm loglar taranır (`Program.cs:3677`); finans ekranında aynı (`OpsSuite.cs:230`). İstemcide planlama çakışması O(n²) (`app.js:395`).
- Cihaz kütüğü (~1.324 satır) sayfasız döner (`Program.cs:2232-2285`); `LIKE '%..%'` ile 4 kolonda arama indeks kullanamaz.
- Birim kapsamı `CHARINDEX(N'|'+UnitCode+N'|', @Units)` ile yapılıyor (`1495`, `1722`) — indeks kullanılamaz (veri küçükken sorun değil).

**Etki (çıkarım):** Pilot hacminde (yüzlerce–birkaç bin iş emri) kabul edilebilir; 1 cihaz = 1 PB kararıyla PB iş emri sayısı her yıl sözleşme × frekans × cihaz kadar artar (ör. 1.324 cihaz × 2-4 = yılda 2.600-5.300 PB). 2-3 yılda her ekran açılışında on binlerce satır taşınır.

**Öneri (sırasıyla, davranışı bozmadan):**
1. Tek kayıt doğrulamalarında `CanAccessWorkOrderAsync` kullanın (OpsSuite.cs:135, 150, 193, 250).
2. `LoadWorkOrdersAsync(filter)` imzasına opsiyonel `from/to/status/unit/ids` parametreleri; eski çağrılar parametresiz çalışmaya devam eder.
3. Yeni `/api/workorders?openOnly=true&from=&to=&page=&pageSize=` (eski uç korunur); ön yüz liste ekranları kademeli geçer.
4. Logları `ToLookup(x=>x.WorkOrderId)` ile bir kez gruplayın (3677, OpsSuite 230).
5. `loadCore` bağımsız çağrıları `Promise.all` ile paralel yapsın; modül verileri ekran açılınca yüklensin (lazy).

---

### A2-09 — YÜKSEK — Tek dosya backend, tekrar eden kod, test edilemez yapı

**Ölçümler (kodla sayıldı):**
- `Program.cs`: 70 `app.Map*` ucu, 3.937 satır; tüm yardımcılar `static` yerel fonksiyon; bağlantı dizesi lambda kapanışı ile (`18`).
- Her uçta aynı giriş kalıbı: `GetCurrentUser(ctx, sessions)` **67 kez**, ardından `Can(...)`/`UnitAllowed(...)`.
- `new SqlConnection(` **70 kez**; okuyucu eşlemesi elle (`reader.IsDBNull(i) ? null : reader.GetString(i)` yüzlerce kez; ör. `2581-2624`).
- `AddWithValue` her yerde: parametre tipi/uzunluğu değerden çıkarılır (nvarchar uzunluğu değişken → plan önbelleği şişmesi; doğrulanmadı, SQL Server'da bilinen davranış).
- Kopyalar: belge numarası üretimi 6 yerde (A2-18); faaliyet türü listeleri 4 yerde (`1936`, `1997`, `2122`, `3695`) ve **birbirinden farklı** (canlı sayaçta `Mola / Ara`, manuelde `Diğer`); "bakım iş emri mi" kuralı 4 yerde (`Program.cs:3638`, `OpsSuite.cs:9`, `app.js:127`, `app.js:408`); seri zorunluluğu varsayılanı sunucu (`3380-3382`) ve istemci (`app.js:135`) **farklı**.
- `OpsSuite` aynı işlevleri delege ile alıyor (`Program.cs:2778-2779`) — doğru yönde bir ayrıştırma, ama yardımcıların kopyası (`P`, `Db`, `Maint`, `Open`) orada da var.
- Test projesi yok (tek `.csproj`); `TEST_SONUCLARI_V120.txt` yalnızca JS sözdizimi kontrolü ve ZIP bütünlüğü bildiriyor, .NET derlemesi bile o ortamda yapılamamış.

**Etki:** Her yeni modül (c) `Program.cs`'i büyütüyor; kural kopyaları birbirinden sapıyor (yukarıdaki farklar bunun kanıtı); regresyonu yakalayacak otomatik test yok; birden fazla geliştirici aynı dosyada çakışır (GitHub'a geçişte birleştirme çatışmaları).

**Öneri:** Bölüm 4'teki artımlı modülerleştirme planı.

---

### A2-10 — ORTA — Hata yönetimi ve gözlemlenebilirlik

**Kodla doğrulandı:**
- Global istisna yakalayıcı (`UseExceptionHandler`/`ProblemDetails`) yok; uygulama yalnızca başlangıç hatasını logluyor (`Program.cs:38`). Hiçbir uçta `ILogger` kullanımı yok.
- Windows pilot `Development` ortamında çalışıyor (`Properties/launchSettings.json`, proje belgesi §3.2). .NET minimal API'de Development'ta Developer Exception Page otomatik etkindir; işlenmeyen istisnada **yığın izi ve SQL ayrıntısı** ağdaki istemciye gider. İstemci `api()` (`app.js:96-106`) JSON değilse ham gövdeyi `alert` ile kullanıcıya gösterir.
- `/api/health` SQL hata metnini döndürüyor (`Program.cs:63`).
- Doğrulanmayan girdiler 500 üretiyor: `CreateWorkOrderRequest` alanları (`CustomerName`, `Subject`, `UnitCode`, `Priority`) boş/null kontrolü yapılmadan `AddWithValue`'a veriliyor (`Program.cs:370-414`) — null gelirse SqlException; `Priority` için beyaz liste yok. Login'de `request.Username.Trim()` null'da `NullReferenceException` (`76`). (C# nullable anotasyonları JSON bağlamada zorlanmaz.)
- İkinci kez "Beklet": `UX_OpsHolds_Open` filtreli unique index (`ZZ_V120_Operations.sql:12`) ihlali yakalanmıyor → 500 (`OpsSuite.cs:138-143`).
- `OpsSuite.cs:180, 191, 241, 251` mesajsız `BadRequest()`; kullanıcı "İşlem başarısız (400)" görür.

**Öneri:**
1. `app.UseExceptionHandler()` + `AddProblemDetails()`; SqlException 2601/2627 → 409, 547 → 400 eşlemesi tek middleware'de.
2. Endpoint grubu başına `ILogger<T>`; kimlik/durum değişiklikleri için yapılandırılmış log (A1 denetim izi ile birleşir).
3. İstek kayıtları için küçük bir `Validate()` yardımcısı (zorunlu alan, uzunluk, beyaz liste) — FluentValidation gerekmez.
4. Pilotta bile `ASPNETCORE_ENVIRONMENT=Production` (Linux env örneğinde zaten öyle: `linux/dengeerp.env.example:2`).

---

### A2-11 — ORTA — Eşzamanlılık: iyimser kilitleme yok

**Kodla doğrulandı:**
- `WorkOrders.RowVersion ROWVERSION` kolonu tanımlı (`DengeERP_Update.sql:21`) ama kodda hiç okunmuyor/kontrol edilmiyor.
- Tam kayıt üzerine yazan PUT'lar (kiralama `1140-1198`, atölye `2707-2776`, personel `1834-1860`) "son yazan kazanır"; iki kullanıcı aynı kaydı açıp kaydederse birinin değişikliği sessizce kaybolur.
- Durum değişikliğinde eski durum kilitsiz okunuyor (`484-487`); eşzamanlı iki değişiklikte durum geçmişindeki `OldStatus` gerçeği yansıtmayabilir.
- Tekil atama (`545-570`): "pasifleştir + ekle" iki eşzamanlı istekte çift aktif atama üretebilir (doğrulanmadı — kilit davranışına bağlı).

**Olumlu:** canlı sayaç, envanter tahsisi, stok hareketi ve bakım formu doğru kilitlenmiş (bkz. Özet).

**Öneri:** Güncelleme uçlarında `rowVersion` (base64) istemciye verilsin, PUT'ta `WHERE Id=@Id AND RowVersion=@Rv`; 0 satır → 409 "Kayıt başka kullanıcı tarafından değiştirildi". Okuyup-yazan akışlarda `WITH (UPDLOCK)`. Önce iş emri ve atölye, sonra kiralama.

---

### A2-12 — ORTA — Migration sürüm takibi yok; betikler her açılışta yeniden çalışıyor

**Kodla doğrulandı:** `RunDatabaseSetupOnStartup=true` iken tüm `.sql` dosyaları her açılışta yeniden çalışır (`Program.cs:30-31`); sürüm/çalıştırıldı tablosu yok. Betikler "idempotent" olsa da bazıları veri değiştiriyor:
- `DengeERP_V15_Schema.sql:147-170` rol adına göre `devices.view`, `maintenance.*`, `workshop.*` izinlerini **yeniden ekliyor**. Yöneticinin bilinçli olarak kaldırdığı izin bir sonraki açılışta geri gelir — belge §8.1 "Yeni yetkiler eski özel kullanıcı profillerine otomatik dağıtılmaz" kararına aykırı.
- `DengeERP_V15_Seed.sql:2436-2443` bakım sözleşmelerini MERGE ile seed değerlerine döndürür ve `IsActive=1` yapar (pasifleştirilen sözleşme geri gelir).
- `DengeERP_Update.sql:428-432` personel-kullanıcı bağlantısını **isim eşleşmesiyle** her seferinde kurar.

**Öneri:** Küçük bir `SchemaVersions(ScriptName, AppliedAt, Checksum)` tablosu ve her betiğin bir kez çalışması (DbUp kütüphanesi veya ~50 satırlık kendi çalıştırıcı). Seed ve yetki dağıtımı "bir kerelik veri betiği" olarak ayrılsın, açılışta çalışmasın. A2-01 ile birlikte yapılmalı.

---

### A2-13 — ORTA — Süre kaydı olmayan iş "0" olarak raporlanıyor

**Kullanıcı kararı:** "Süre kaydı yoksa 'eksik' denir, 0 değil."

**Kodla doğrulandı:**
- Excel iş emri sayfaları: `Hours(own)` log yokken `"0.00"` yazar ve `MakeSheet` bunu **sayısal** hücre yapar (`Program.cs:3678`, `3761`). Yanındaki "SÜRE KAYDI YOK" sütunu doğru, ama sayısal 0 Excel toplamlarına/pivotlarına girer.
- Finans ekranı: log yoksa `hours=0`, `labor=0`, `margin = gelir - (malzeme+diğer)` hesaplanır (`OpsSuite.cs:230-234`); işçilik maliyeti eksik olduğu halde **fark/kâr olduğundan yüksek** görünür.
- Operasyon özetinde `recordedMinutes` log yoksa 0 (`OpsSuite.cs:82, 88`).

**Öneri:** Bu alanlar `null` dönsün; Excel'de boş hücre + "EKSİK" metni; finans satırında `labor=null, margin=null, laborMissing=true` ve toplamlar "eksik kayıt sayısı" ile birlikte gösterilsin.

---

### A2-14 — ORTA — Excel'de seri no/telefon sayısal hücreye dönüşüyor

**Konum:** `MakeSheet`, `Program.cs:3759-3766`.

**Ne oluyor:** Bir hücre `decimal.TryParse` ile sayıya çevrilebiliyor, `0` ile başlamıyor ve 18 karakterden kısaysa **sayısal** hücre yazılıyor. "Seri No" (`3678`'de 16. sütun), "Saha Telefonu", iş emri dışındaki kimlik alanları da buna tabi. Sonuç:
- 16-17 haneli sayısal seri numaraları Excel'in 15 anlamlı hane sınırı nedeniyle **son haneleri kaybeder** (Excel davranışı; doğrulanmadı ama bilinen sınır).
- `12.50` gibi noktalı seri numaraları `12.5` olur.
- Belge kararı "seri no metin; baştaki sıfırlar korunmalı" ile çelişir (baştaki sıfır korunuyor, diğer durumlar korunmuyor).

**Öneri:** Sayısal sütunları başlık adına göre beyaz listeyle belirleyin ("Süre (dk)", "Gerçek Saat", sayaç sütunları); diğer tüm hücreler metin (`inlineStr`).

---

### A2-15 — ORTA — Ön yüz mimarisi

**Kodla doğrulandı:**
- `app.js` 234 KB, 2.047 satır, en uzun satır 1.860 karakter; 147 üst düzey fonksiyon; tek global `state` nesnesi (`app.js:34-84`); sayfalar şablon dizgeleriyle `innerHTML` üzerinden yeniden çiziliyor; 94 satır içi `onclick=`.
- XSS'e karşı `esc()` tutarlı kullanılıyor (455 çağrı) — olumlu; ancak her yeni şablonda unutulma riski var.
- `ops120.js`, `app.js`'in globallerine (`state`, `esc`, `api`, `can`, `render`, `reloadWork`, `statusBadge`, `money`) **örtük** bağımlı; yükleme sırası değişirse kırılır. 3 dakikalık yenileme `setInterval` (`ops120.js:102`) tüm sayfayı yeniden çizer (açık form/odak kaybı olabilir — doğrulanmadı).
- Sunucu katalogları istemcide kopya: birimler, iş türleri, sistemler, durumlar (`app.js:8-32`). Seri kuralı varsayılanı sunucudan farklı (`app.js:135` vs `Program.cs:3380-3382`).
- `personnelFallback` (`app.js:23-28`) **gerçek personel adlarını** statik ve kimlik doğrulamasız indirilebilen dosyada taşıyor (KVKK açısından küçük ama gereksiz ifşa).
- Şef/teknisyen/araç **çakışma kontrolü yalnızca istemcide** ve yalnızca kullanıcının gördüğü birimlerdeki işler arasında (`app.js:392-406`); sunucu plan uçlarında (`Program.cs:649-761`) çakışma denetimi yok. Belge §5.2 "çakışma denetlensin" kararı sunucuda karşılanmıyor.
- Giriş formunda kullanıcı adı varsayılanı `admin` (`app.js:162`).

**Öneri (derleme aracı eklemeden):**
1. Tarayıcının yerel ES modüllerini kullanın (`<script type="module">`): `core/api.js`, `core/state.js`, `core/format.js` (tarih yardımcıları — A2-05), sonra modül başına dosya (`workorders.js`, `planning.js`, `maintenance.js`, ...). İlk adımda `window.*` köprüsü ile `ops120.js` çalışmaya devam eder.
2. Kataloglar ve durum kuralları `/api/meta` üzerinden sunucudan gelsin; `personnelFallback` kaldırılıp `/api/personnel` (veya hafif bir `/api/meta/assignees`) kullanılsın.
3. Çakışma kontrolü sunucuya taşınsın (plan/bulk-plan uçlarında, uyarı veya engel olarak — iş kararı).
4. Satır içi `onclick` yerine olay delegasyonu (zaten `data-*` + `addEventListener` deseni kodda var).

---

### A2-16 — ORTA — Oturumlar bellek içi ve süresiz (mimari boyut)

**Konum:** `Program.cs:21` (`ConcurrentDictionary<string, SessionUser>`), `94-96`, `2821-2825`.

**Mimari etki:** Servis her yeniden başladığında (yeni sürüm, `systemd` restart, Windows'ta PowerShell kapanması) tüm kullanıcılar oturumdan düşer; canlı sayaç kullanan teknisyen sahada tekrar giriş yapmak zorunda kalır. Birden fazla sunucuya ölçeklenemez. Oturum deposu soyutlanmadığı için entegrasyon testinde taklit edilemez. Yetki değişince oturumlar elle güncelleniyor (`297-298`). Güvenlik boyutu (süre sonu, kilitleme) A1 raporunun konusudur.

**Öneri:** `ISessionStore` arayüzü + SQL tablosu (`Sessions(TokenHash, UserId, ExpiresAt, LastSeenAt)`) veya ASP.NET Core cookie kimlik doğrulaması + DataProtection anahtarlarının `/var/lib/dengeerp` altında kalıcı tutulması.

---

### A2-17 — ORTA — Kiralamada iki doğruluk kaynağı

**Kodla doğrulandı:** Kiralama kaydının `Status` alanı `PUT /api/rentals/{id}` ile serbestçe set ediliyor (`1146-1147`, `1192`); operasyon aşamaları ise `RentalStageHistory`'ye ayrıca yazılıyor (`1436-1482`) ve envanter durumunu değiştiriyor (`1465-1480`). İkisi birbirini güncellemiyor; aşama sırası (Sevk → Kurulum → Devreye Alma → Toplama → Depo) denetlenmiyor — "Sevk Edildi" olmadan "Depoya Alındı" girilebilir. Ayrıca `PUT` `Quantity` ve `SerialNumbers` alanlarını kalemlerden bağımsız yazıyor (`1177`), kalem toplamıyla tutarsızlık oluşabilir.

**Öneri:** `Status` aşama geçmişinden türetilsin (veya aşama kaydı durumu güncellesin); izinli aşama geçişleri A2-07'deki desenle tanımlansın; başlık `Quantity` yalnızca kalemlerden hesaplansın.

---

### A2-18 — DÜŞÜK — Belge numarası üretimi kopyaları

**Konum:** `SRV` `386-393` ve `2643-2650`; `TKL` `814-821`; `KIR` `1098-1105`; `AT` `2677-2684`; `PB` `3076-3082`.

Hepsi `MAX(TRY_CONVERT(INT,RIGHT(No,4)))+1` + `UPDLOCK,HOLDLOCK`. Doğru serileştiriyor ama 6 kopya; 9999 taşması yalnızca PB'de kontrol ediliyor. Ayda 10.000'i aşan SRV'de `RIGHT(...,4)` sıfırlanır ve unique ihlali 500 olur (hacim açısından olası değil — doğrulanmadı). Ayrıca `UPDLOCK,HOLDLOCK` ile `LIKE` aralık kilidi, aynı tabloya PB üretimi sürerken SRV açılışını bekletir (A2-04 ile bağlantılı).

**Öneri:** `NumberSequences(Prefix, Period, LastValue)` tablosu + tek `NextNumberAsync(conn, tx, prefix, period)` yardımcısı.

---

### A2-19 — DÜŞÜK — Yapılandırma ve e-posta gönderimi

**Konum:** `Program.cs:909-937`. SMTP ayarları her istekte `builder.Configuration`'dan okunuyor (Options deseni yok, başlangıçta doğrulanmıyor); e-posta istek içinde senkron gönderiliyor; gönderim başarılı olup log yazılamazsa (`939-953`) kayıt kaybolur. Belge bildirimlerin "hazır değil" olduğunu söylüyor; ileride bildirim modülü (c) eklenecekse bu desen temel alınmamalı.

**Öneri:** `EmailOptions` + `IEmailSender`; bildirimler için SQL tabanlı "outbox" tablosu + `BackgroundService` (kalıcı, yeniden denenebilir).

---

## 4. Artımlı modülerleştirme önerisi (tam yeniden yazım değil)

İlke: **davranışı değiştirmeden taşı → test et → sonra iyileştir.** Teknoloji yığını aynı kalır (.NET 10 minimal API + ADO.NET/SqlClient + vanilla JS). EF Core'a geçiş önerilmiyor; isteğe bağlı olarak yalnızca eşleme yükünü azaltmak için Dapper değerlendirilebilir.

### Adım 0 — Güvenlik ağı (1–2 gün; GitHub'a geçişle birlikte)
- `DengeERP.Tests` (xUnit) + `WebApplicationFactory<Program>`; `Program.cs` sonuna `public partial class Program {}`.
- Test SQL veritabanı (`DengeERP_DEV`, yerel SQL Express) + test verisi betiği.
- **Karakterizasyon testleri** (mevcut davranışı kayda alan): giriş; iş emri aç → planla → ata → durum → kapat; bakım formu kapatma; canlı sayaç başlat/değiştir/bitir; Excel indirme (tarihli/tarihsiz); fiyat alanlarının yetkisiz kullanıcıda null olması (A2-02).

### Adım 1 — Kesişen kaygıları toplama (davranış aynı)
- `Infrastructure/Sql.cs`: `OpenAsync()` bağlantı fabrikası, `Db()`, `reader.GetStringOrNull(i)` uzantıları.
- `Auth/EndpointFilters.cs`: `RouteGroupBuilder.RequireUser()` ve `.RequirePermission("x")` uç filtreleri → 67 tekrar kalkar; `SessionUser` `HttpContext.Items` üzerinden alınır.
- `Infrastructure/Clock.cs`: `TimeProvider` + Europe/Istanbul (A2-05).
- `Domain/Catalog.cs`: mevcut `Catalog` + faaliyet türleri + durumlar + "bakım mı/açık mı" kuralları tek yerde (A2-09); `/api/meta` bunları istemciye verir.

### Adım 2 — Uçları dosyalara bölme (kod kopyalanarak, davranış aynı)
`OpsSuite.Map(...)` deseni tüm modüllere uygulanır: `Endpoints/AuthEndpoints.cs`, `UserEndpoints.cs`, `WorkOrderEndpoints.cs`, `PlanningEndpoints.cs`, `MaintenanceEndpoints.cs`, `WorkshopEndpoints.cs`, `RentalEndpoints.cs`, `TrainingEndpoints.cs`, `PersonnelEndpoints.cs`, `TimeTrackingEndpoints.cs`, `ReportEndpoints.cs` (xlsx üretimi `Reports/XlsxWriter.cs`), `OfferEndpoints.cs`. `Program.cs` ~100 satıra iner. **Sıra:** önce (c) kapsamında genişletilecek modül — "dokunduğun modülü önce böl" kuralı.

### Adım 3 — Kural servisleri (davranış bilinçli değişir, testle)
- `WorkOrderStatusService` (A2-07), `NumberSequenceService` (A2-18), `PriceMask` (A2-02), `MaintenanceGenerator` + `BackgroundService` (A2-03, A2-04), kişi kimliği id'ye geçiş (A2-06).

### Adım 4 — Okuma tarafı
- Filtreli/sayfalı sorgular ve tek kayıt erişim kontrolleri (A2-08); eski uçlar bir süre korunur.

### Adım 5 — Ön yüz
- `app.js` → ES modülleri (A2-15); önce `core/*`, sonra yeni (c) modülleri doğrudan modül olarak; eski ekranlar dokunuldukça taşınır.

### Yeni modüller (c) için kural
Her yeni modül **doğduğu andan itibaren** yeni yapıda olsun: kendi `Endpoints/X.cs` dosyası, kendi sürümlü SQL betiği (A2-12), kendi JS modülü, en az bir entegrasyon testi. `Program.cs` ve `app.js`'e yeni uç/ekran eklenmesin.

---

## 5. Kullanıcı önceliğine (c → b → a) göre uygulama sırası önerisi

| Sıra | İş | Gerekçe |
|---|---|---|
| Hemen (küçük, kritik) | A2-01 `USE` satırı + DB adı denetimi; A2-02 atölye `repairAmount` maskesi; A2-05 `TZ` + `todayIso` düzeltmesi | Veri kaybı/sızıntısı ve kesin tarih hataları; her biri birkaç satır |
| (c) öncesi altyapı | Adım 0 (testler), Adım 1 (kesişen kaygılar), A2-12 sürüm tablosu | Yeni modüllerin üzerine kurulacağı zemin; olmadan her yeni modül borcu büyütür |
| (c) yeni modüller | Adım 2'yi modül modül; A2-07 durum servisi, A2-06 kimlik id'si (organizasyon şeması gelince) | Yeni özellikler bu servisleri kullanır |
| (b) mevcut eksikler | A2-03, A2-04, A2-13, A2-14, A2-17, sunucu tarafı plan çakışması (A2-15) | Mevcut modüllerin doğruluğu |
| (a) üretime hazırlık | A2-08 sayfalama, A2-10 hata/log, A2-11 RowVersion, A2-16 oturum deposu | Ölçek, işletim, güvenlik |

---

## 6. Doğrulanmamış / ayrıca teyit edilmesi gerekenler

- A2-01: İT'nin SQL hesabının `DengeERP` veritabanına yetkisi olup olmadığı ve test/canlı DB'nin aynı SQL örneğinde bulunup bulunmayacağı.
- A2-03: Yıl devri davranışı kod okumasıyla çıkarıldı; henüz canlı veride yaşanmadı. 2026→2027 senaryosu test DB'de saat ileri alınarak doğrulanmalı.
- A2-04: Kilit bekleme süreleri gerçek yükte ölçülmedi.
- A2-05: Linux sunucunun saat dilimi ayarı bilinmiyor; Windows pilotta sunucu tarafı TZ sorunu beklenmez (istemci tarafı hatalar yine geçerli).
- A2-10: Developer Exception Page'in ağ istemcisine yığın izi gösterdiği .NET'in Development varsayılan davranışına dayanır; pilotta canlı denenmedi.
- A2-11: Eşzamanlı tekil atamada çift aktif kayıt oluşması kilit zamanlamasına bağlıdır, denenmedi.
- A2-14: Excel'in 15 hane sınırı bilinen davranıştır; gerçek seri numaralarında bu uzunlukta sayısal seri olup olmadığı veriyle kontrol edilmeli.
- Derleme yapılmadı; satır numaraları `kaynak/V1_20_1_orijinal` kopyasına göredir.
