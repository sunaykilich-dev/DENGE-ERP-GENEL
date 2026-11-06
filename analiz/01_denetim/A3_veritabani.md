# A3 — Veritabanı ve Veri Bütünlüğü Denetimi (DengeERP V1.20.1)

> **Tarih:** 21 Ekim 2026
> **Kapsam:** `kaynak/V1_20_1_orijinal/DengeERP.Api/Database/*.sql` (11 script), `Program.cs`, `OpsSuite.cs`, ilgili `wwwroot` parçaları, `linux/` kurulum/geri dönüş scriptleri.
> **Yöntem:** Kod ve SQL okunarak doğrulandı. Canlı SQL Server'a bağlanılmadı; bu nedenle "canlı veritabanında şu an ne var" sorusu **doğrulanmadı** olarak işaretlenmiştir. Kaynak koda dokunulmadı.
> **Öncelik notu:** Kullanıcı kararı gereği öncelik sırası (c) yeni özellik → (b) modül eksikleri → (a) güvenlik/üretime hazırlık. Buna rağmen veri kaybı veya veri sızıntısı üretebilen maddeler **KRİTİK** olarak işaretlenmiştir.

---

## 1. Özet

DengeERP'nin veri katmanı, pilot için beklenenden daha disiplinli birkaç parça içeriyor: **tek aktif sayaç** (`UX_LiveSessions_OneActivePerUser`), **negatif stok engeli** (`CHECK(Quantity>=0)` + Serializable işlem), **1 cihaz = 1 PB iş emri** (`UX_MDI_WorkOrderId` + `UQ_MDI_PlanTypeOrdinal`), **tek açık bekletme** (`UX_OpsHolds_Open`) ve süre kaydı geçerlilik kısıtı (`CK_WorkOrderTimeLogs_ValidTimes`) **veritabanı seviyesinde** garanti altında. Numara üretimi (`UPDLOCK,HOLDLOCK`) ve bakım dönemi sayacının tek kez artırılması (`IsCompleted=0` + `@@ROWCOUNT`) doğru kurulmuş.

Buna karşılık üç alan üretime geçişi doğrudan riske sokuyor:

1. **Migration altyapısı yok.** Sürüm tablosu yok; 11 script ve 300 KB'lık seed her kurulumda baştan çalıştırılıyor, işlem (transaction) yok, sıralama dosya adı hilesine (`ZZ_` öneki) dayanıyor ve `DengeERP_Update.sql` ilk satırında **`USE DengeERP;`** ile veritabanını sabit kodluyor. Linux'ta `DengeERP_TEST`'e bağlanan kurulum, bu dosyanın tamamını **başka bir veritabanına** uygulayabiliyor (A3-01).
2. **Planlı bakım sayacı yıl devrinde sıfırlanmıyor.** `MaintenanceContracts.CompletedCount` takvim yılından bağımsız; **1 Ocak 2027'de** sayacı dolu olan sözleşmelerin 2027 planları "tamamlandı" olarak oluşturulacak ve hiç PB iş emri üretilmeyecek (A3-02). Sessiz ve tarihe bağlı bir arıza.
3. **İlişkilerin önemli kısmı serbest metin.** Teknisyen/şef ataması, erişim filtresi, süre kayıtları ve çakışma kontrolü kişinin **ad-soyad metni** üzerinden; müşteri/lokasyon ana verisi yok; bakım sözleşmesi ↔ cihaz kütüğü eşleşmesi `CustomerName` metin eşitliğine dayanıyor (A3-03, A3-10).

Geri dönüş planı yalnızca uygulama kodunu kapsıyor; SQL için "yedekten dön" dışında yol yok ve geri yükleme testi kanıtlanmamış (A3-06).

**Sayısal görünüm:** 2 KRİTİK · 7 YÜKSEK · 9 ORTA · 4 DÜŞÜK = 22 bulgu.

---

## 2. Bulgular tablosu (önem sırasıyla)

| ID | Önem | Başlık | Konum |
|---|---|---|---|
| A3-01 | KRİTİK | `DengeERP_Update.sql` veritabanı adını sabit kodluyor (`USE DengeERP`) — test kurulumu yanlış DB'ye yazabilir | `Database/DengeERP_Update.sql:1`, `Program.cs:30,3257-3268` |
| A3-02 | KRİTİK | Bakım sözleşmesi sayacı yıl devrinde sıfırlanmıyor; 2027 bakımları sessizce "tamamlandı" sayılacak | `Program.cs:2897-2898,2924,2950,2546,3168` |
| A3-03 | YÜKSEK | Kimlik ilişkileri ad-soyad metni ile kuruluyor (atama, erişim, süre kaydı, personel eşlemesi) | `Program.cs:3341,3400,3500,1945,2041,2120,2140,266-268`; `DengeERP_Update.sql:39,428-432` |
| A3-04 | YÜKSEK | Şema sürüm takibi yok; tüm scriptler ve seed her seferinde, işlemsiz ve kültüre bağlı alfabetik sırayla çalışıyor | `Program.cs:26-41,30,3257-3269` |
| A3-05 | YÜKSEK | Seed `MERGE ... WHEN MATCHED` kullanıcı düzeltmelerinin üzerine yazıyor, pasif kayıtları diriltiyor | `DengeERP_V15_Seed.sql:1361-1364,1787-1790,2200-2203,2337-2340,2437-2441`; `DengeERP_Update.sql:137,305` |
| A3-06 | YÜKSEK | SQL için geri dönüş planı yok; geri yükleme testi kanıtlanmamış | `linux/04_geri_don.sh:18`, `linux/SQL_HAZIRLIK_YEDEK.sql`, `PILOT_V120_KURULUM_VE_TEST.txt:44` |
| A3-07 | YÜKSEK | İş emri durumu serbest metin; "İptal" kontrolleri atlıyor ve bakım dönemini kalıcı kilitliyor | `Program.cs:473-531,2808,2539-2551,2954-2965` |
| A3-08 | YÜKSEK | Bakım formu kaydı iş emrinin asıl `Location` ve `Description` alanlarının üzerine yazıyor | `Program.cs:2519-2521` |
| A3-09 | YÜKSEK | Kiralamada seri no tekilliği yalnızca envanter yolunda; metin seri alanları ve iptal/kapanış çift tahsise açık | `Program.cs:1170-1196,3233,1280-1285`; `ZZ_V112...sql:67-68` |
| A3-10 | ORTA | Müşteri / lokasyon / sözleşme ana verisi yok; cihaz ↔ sözleşme eşleşmesi metin eşitliği + sıra numarası | `Program.cs:3010-3016,3032,632-634`; `DengeERP_V15_Schema.sql:15,37` |
| A3-11 | ORTA | Kullanıcı/personel kimliği tutan kolonların çoğunda foreign key yok | Ayrıntıda liste |
| A3-12 | ORTA | Durum / öncelik / sonuç alanlarında `CHECK` kısıtı yok; `Priority` ↔ `OpsSlaTargets` ilişkisiz | `DengeERP_Update.sql:17-18,199,331`; `ZZ_V112...sql:59`; `DengeERP_V17_Schema.sql:11` |
| A3-13 | ORTA | Bekletme (hold) işlemleri durum geçmişine yazılmıyor; durum ile hold tablosu ayrışabiliyor | `OpsSuite.cs:138-157`; `Program.cs:525-531` |
| A3-14 | ORTA | "Tek aktif plan" DB'de garanti değil; tekil planlama kapalı işi yeniden "Planlandı" yapıyor; kaynak çakışması sunucuda yok | `Program.cs:722-761`; `DengeERP_Update.sql:254-255` |
| A3-15 | ORTA | Zaman kaynağı karışık: uygulama saati, SQL saati ve tarayıcı UTC değeri aynı kolonlara yazılıyor | `Program.cs:386,1959,2126,3076`; `app.js:5,697,739` |
| A3-16 | ORTA | Süre kaydı olmayan iş "0 dk / 0 TL işçilik" olarak raporlanıyor ("eksik" değil) | `OpsSuite.cs:88,230-234` |
| A3-17 | ORTA | `RowVersion` kolonu var ama hiç kullanılmıyor; eşzamanlı güncellemede son yazan kazanır | `DengeERP_Update.sql:21`; `Program.cs:484-531` |
| A3-18 | ORTA | Stok bakiyesi ile hareket defteri arasında mutabakat yok; kapalı/iptal işe çıkış yapılabiliyor | `OpsSuite.cs:188-213`; `ZZ_V120_Operations.sql:20-24` |
| A3-19 | DÜŞÜK | Sık sorgulanan FK / filtre kolonlarında index eksikleri | Ayrıntıda liste |
| A3-20 | DÜŞÜK | İsimsiz constraint'ler, koşullu blok içindeki index'ler, her çalışmada tekrarlanan `ALTER COLUMN` | `DengeERP_Update.sql:17-21,163-167`; `ZZ_V110...sql:7`; `ZZ_V112...sql:7-9`; `ZZ_V113...sql:30,47,125` |
| A3-21 | DÜŞÜK | Numara üretimi 9999'da taşıyor (SRV/KIR), ay öneki uygulama saatine bağlı | `Program.cs:386-393,1098-1105` |
| A3-22 | DÜŞÜK | Tarih ve tutarlar metin olarak saklanıyor (Excel seri tarihi `'42721'`, dönem metni) | `DengeERP_V15_Schema.sql:18,40-43`; `DengeERP_V15_Seed.sql:6` vb. |

---

## 3. Bulgu ayrıntıları ve öneriler

### A3-01 — KRİTİK — `USE DengeERP` sabit kodlu; test kurulumu yanlış veritabanına yazabilir

**Konum:** `Database/DengeERP_Update.sql:1-2`, çalıştırıcı `Program.cs:30-31` ve `Program.cs:3257-3268`.

**Kanıt:**
- `DengeERP_Update.sql` ilk batch'i `USE DengeERP;`.
- `ApplySchemaAsync` her dosya için **tek bağlantı** açıp batch'leri sırayla aynı bağlantıda çalıştırıyor (`Program.cs:3262-3267`). `USE` bağlantının veritabanı bağlamını değiştirdiği için bu dosyanın sonraki tüm batch'leri `DengeERP` üzerinde çalışır.
- Linux hedefinde bağlantı dizesi `Database=DengeERP_TEST` (`linux/dengeerp.env.example:8`). `dengeerp.env.example:9-10` boş test DB ilklendirmesi için `RunDatabaseSetupOnStartup=true` yapılmasını tarif ediyor.

**Etki (iki senaryo):**
1. `DengeERP_TEST` ile aynı SQL instance üzerinde `DengeERP` (üretim/pilot) varsa ve SQL kullanıcısının orada yetkisi varsa: `WorkTypeRules` ve `RentalProducts` üzerine `MERGE` (mevcut ayarların üzerine yazar), `Personnel` tablosuna ekleme, `ErpUsers`–`Personnel` ad eşlemesi **üretim veritabanına** uygulanır. **Veri değişikliği yanlış hedefte olur.**
2. `DengeERP` yoksa: script hata verir, servis başlamaz (`Program.cs:36-40` `throw`). Daha kötüsü: boş test DB'de `WorkOrders` hiç oluşmaz, sonraki scriptler FK hatasıyla düşer.

Not: Bayrak varsayılan olarak `false` (`appsettings.json:20`, `dengeerp.env.example:4`) ve `02_yayinla.sh:11-13` açıkken yayını reddediyor. Bu nedenle risk **yalnızca İT'nin ilklendirme için bayrağı açtığı anda** gerçekleşir; ama tarif edilen prosedür tam olarak budur.

**Öneri:**
- `DengeERP_Update.sql:1-2` satırlarını bir sonraki sürümde kaldırın (orijinal kaynağa dokunmadan, yeni sürüm kopyasında). Veritabanı bağlamı yalnızca bağlantı dizesinden gelmeli.
- Çalıştırıcıya ön kontrol ekleyin: script metninde `^\s*USE\s+` geçiyorsa reddet; her batch öncesi `SELECT DB_NAME()` beklenen adla eşleşmiyorsa durdur.
- İT'ye yazılı not: test ve üretim veritabanları **ayrı instance**'ta olsun; uygulama SQL kullanıcısının üretim DB'de hiçbir yetkisi olmasın.

---

### A3-02 — KRİTİK — Bakım sözleşmesi sayacı yıl devrinde sıfırlanmıyor (zaman ayarlı arıza: 1 Ocak 2027)

**Konum:** `Program.cs:2894-2982` (`EnsureMaintenancePlansAndWorkOrdersAsync`), sayaç artışları `Program.cs:2546-2547` ve `Program.cs:3167-3169`.

**Kanıt:**
- Plan yılı her zaman `DateTime.Today.Year` (`Program.cs:2897-2898`).
- `completed = Min(CompletedCount, AnnualFrequency)` sözleşme satırından okunuyor (`:2924`); plan satırı `IsCompleted = (seq <= completed)` ile **o yıl için** oluşturuluyor (`:2935-2936,2950`).
- `CompletedCount` hiçbir yerde yıl bazında sıfırlanmıyor. Kodda yalnızca artırılıyor (`Grep: CompletedCount` → sadece `:2546` ve `:3168`). Seed de mevcut değerden küçüğe indirmiyor (`DengeERP_V15_Seed.sql:2440`).
- İş emri yalnızca `nextSeq = completed + 1 <= AnnualFrequency` için üretiliyor (`:2954-2955`).

**Etki:** 2026'da tüm bakımları tamamlanmış (ör. `CompletedCount = AnnualFrequency`) bir sözleşme için 1 Ocak 2027'den sonraki ilk tetiklemede (her iş emri kapanışında `Program.cs:539` veya kurulumda) 2027 planlarının **hepsi tamamlanmış olarak** eklenir ve **hiç PB iş emri oluşmaz**. Kısmen tamamlanmışlarda 2027'nin ilk N dönemi atlanır. 2026'dan sarkan bir PB iş emri 2027'de kapatılırsa sayaç 2027 adına artar. Belgedeki "vadesi gelen bakımların otomatik iş emri üretimi" kuralı (Proje belgesi §5.4) sessizce bozulur. Sözleşme dönemi (`PeriodText`, ör. `01.09.2025-01.09.2026`) takvim yılıyla örtüşmediği için 2026 içinde de dönem hesabı yanlış (A3-22 ile bağlantılı).

**Öneri (artımlı):**
1. **Acil (Aralık 2026'dan önce):** Sayacı yıl bazlı türetin. `CompletedCount` yerine `SELECT COUNT(*) FROM MaintenancePlans WHERE MaintenanceContractId=@Id AND PlanYear=@Year AND IsCompleted=1` kullanın; `CompletedCount` yalnızca seed başlangıç değeri olarak ilk yıla uygulansın.
2. Kalıcı: `MaintenanceContracts` tablosuna `ContractStart DATE`, `ContractEnd DATE` ekleyin (`PeriodText`'ten bir kerelik dönüştürülerek, dönüştürülemeyenler "kontrol gerekli" listesine); plan dönemlerini sözleşme tarihlerinden üretin.
3. Test: sistem saatini 2027-01-02'ye alan bir entegrasyon testi ile "tamamlanmış sözleşme 2027'de yeni PB üretiyor mu" senaryosu.

---

### A3-03 — YÜKSEK — Kimlik ilişkileri ad-soyad metni ile kuruluyor

**Konum ve kanıt:**
- Atama tablosu yalnızca isim tutuyor: `WorkOrderAssignments.AssignedName NVARCHAR(150)` (`DengeERP_Update.sql:39`), kullanıcı veya personel FK'si yok; ekleme `Program.cs:3341-3346`.
- Teknisyen erişim filtresi isimle: `CanAccessWorkOrderAsync` (`Program.cs:3398-3400`) ve `FilterWorkOrdersForUser` (`Program.cs:3499-3500`) `user.FullName`'i virgülle ayrılmış `STRING_AGG` listesinde arıyor.
- Canlı sayaç başlatma yetkisi isimle (`Program.cs:1945`); süre çakışma kontrolü isimle (`Program.cs:1962,2041,2140,2146`); manuel süre kaydında teknisyen adı istekten geliyor (`Program.cs:2120`). Buna karşın `WorkOrderLiveSessions` `TechnicianUserId` ile tutuluyor (`ZZ_V114...sql:8`). **İki farklı kimlik anahtarı** aynı kural için kullanılıyor.
- Kullanıcı adı-soyadı serbestçe değiştirilebiliyor (`Program.cs:266-268`) ve `ErpUsers.FullName` benzersiz değil (`DengeERP_Update.sql:149`).
- Personel ↔ kullanıcı eşlemesi kurulumda `FullName` eşitliğiyle yapılıyor (`DengeERP_Update.sql:428-432`); `Personnel.ErpUserId` için benzersiz kısıt yok; `Personnel.ManagerName` hiyerarşisi de metin (`:358`).

**Etki:**
- **Sızıntı:** Aynı ad-soyadlı iki kullanıcı veya yönetici tarafından başka birinin adına yeniden adlandırılan bir "Teknisyen" hesabı, o kişiye atanmış tüm iş emirlerini, süre kayıtlarını ve canlı sayaç yetkisini devralır. Bu bir veri sızıntısıdır. Gerçekleşme olasılığı düşük olduğu için KRİTİK değil YÜKSEK olarak işaretlendi.
- **Kopukluk:** Ad değişikliğinde (evlilik, yazım düzeltmesi) geçmiş atamalar ve süreler kişiden kopar; kişi-saat ve personel KPI raporları bölünür. Adında virgül bulunan bir kayıt `Split(',')` mantığını bozar.

**Öneri (artımlı, mevcut kolonlar korunarak):**
1. `WorkOrderAssignments`'a `ErpUserId INT NULL` (FK → `ErpUsers`) ve `PersonnelId BIGINT NULL` (FK → `Personnel`) ekleyin; yeni atamalarda zorunlu doldurun, `AssignedName` görüntüleme amaçlı anlık kopya olarak kalsın.
2. Erişim filtresini ve süre çakışma kontrolünü `ErpUserId` üzerine taşıyın. `WorkOrderTimeLogs`'a `TechnicianUserId` ekleyin.
3. Geçmiş veri için bir kerelik eşleme scripti hazırlayın; eşleşmeyen isimler "manuel eşleme bekliyor" raporuna düşsün.
4. `Personnel.ErpUserId` için filtreli benzersiz index (`WHERE ErpUserId IS NOT NULL`) ekleyin.

*Varsayım:* Organizasyon şeması gelince "bir kullanıcı = bir personel" kuralının geçerliliği teyit edilmeli.

---

### A3-04 — YÜKSEK — Şema sürüm takibi yok; migration sırası kırılgan

**Konum:** `Program.cs:26-41` (tetikleme), `:30` (sıralama), `:3257-3269` (çalıştırıcı).

**Kanıt:**
- Uygulanan scriptleri kaydeden tablo yok (`__SchemaVersions` benzeri hiçbir yapı; tüm `Database/*.sql` ve `Program.cs` tarandı).
- Bayrak açıkken klasördeki **tüm** `.sql` dosyaları, 309 KB'lık seed dahil, her başlatmada yeniden çalışır.
- Sıralama `OrderBy(Path.GetFileName)`: varsayılan **kültüre duyarlı** karşılaştırıcı (ordinal değil). Mevcut 11 dosya için sonuç doğru (`DengeERP_Update` < `DengeERP_V15_Schema` < `DengeERP_V15_Seed` < `DengeERP_V17_Schema` < `DengeERP_V18_...` < `ZZ_V110` ... `ZZ_V120`). Ancak doğruluk, `ZZ_` önekiyle yapılmış bir isimlendirme hilesine dayanıyor. `ZZ_V19_...` gibi bir ad `ZZ_V110`'dan sonra sıralanır.
- Dosya başına transaction yok: bir batch hata verirse önceki batch'ler kalıcı olur, sonrakiler çalışmaz. Kısmen uygulanmış bir şema ortaya çıkar.
- Scriptlerin bir kısmı farklı tarihlerde, farklı paketlerle Windows pilota otomatik uygulandı (`PILOT_V120_KURULUM_VE_TEST.txt:44`: "ILK ACILISTA SQL MIGRATION OTOMATIK UYGULANIR"; `PILOT_KURULUM.txt`). Canlı pilot veritabanının hangi script sürümüne denk geldiği **bilinmiyor** (doğrulanmadı).

**Öneri:**
1. `dbo.SchemaVersions(ScriptName NVARCHAR(200) PK, Sha256 CHAR(64), AppliedAt DATETIME2, AppliedBy NVARCHAR(128), AppVersion NVARCHAR(30))` tablosu ekleyin.
2. Çalıştırıcı şunları yapsın: ordinal sıralama (`StringComparer.Ordinal`); yalnızca kayıtlı olmayan scriptleri çalıştırma; kayıtlı scriptin hash'i değiştiyse durma; her dosyayı bir transaction içinde çalıştırma (DDL SQL Server'da transaction içinde çalışabilir).
3. Yeni scriptler için sıfır dolgulu numaralı ad standardı: `0001_baslangic.sql`, `0002_...`, ... Mevcut 11 dosya "baseline" olarak bir kerede kaydedilsin.
4. Seed dosyalarını şemadan ayırın (`seed/` klasörü). Seed'ler yalnızca boş DB'de veya açık komutla çalışsın (bkz. A3-05).
5. İlk adım olarak **canlı pilot DB'nin şema envanterini** çıkarın (tablo/kolon/index/constraint listesi) ve scriptlerin ürettiği şema ile karşılaştırın. Bu, Linux test DB'sine geçişten önce yapılmalı.

Bu öneri büyük bir yeniden yazım değildir. DbUp gibi küçük bir kütüphane veya ~60 satırlık kendi çalıştırıcınız yeterlidir.

---

### A3-05 — YÜKSEK — Seed `MERGE` kullanıcı düzeltmelerinin üzerine yazıyor ve pasif kayıtları diriltiyor

**Konum:**
- `SecurityDevices`: `DengeERP_V15_Seed.sql:1361-1364` (ve aynı kalıp `:1787-1790`, `:2200-2203`, `:2337-2340`). `WHEN MATCHED` ile `SerialNo`, `CustomerName`, `Location`, `ContactName`... alanları ve `IsActive=1` yeniden yazılıyor.
- `MaintenanceContracts`: `DengeERP_V15_Seed.sql:2437-2441`. `CustomerName`, `AnnualFrequency`, `PeriodText`, tutarlar ve `IsActive=1` yeniden yazılıyor (`CompletedCount` korunuyor).
- `WorkTypeRules`: `DengeERP_Update.sql:137` (seri no zorunluluğu ayarları ve `IsActive=1`).
- `RentalProducts`: `DengeERP_Update.sql:305` (ürün adı, `RequiresSerial`, `IsActive=1`).

**Etki:** Seri numarası düzeltilmiş bir cihaz, pasife alınmış bir sözleşme veya kapatılmış bir iş türü kuralı, kurulum her çalıştığında Excel'deki ilk haline döner. Windows pilotta V1.20'ye kadar migration her açılışta otomatik çalışıyordu (`PILOT_V120_KURULUM_VE_TEST.txt:44`). Pilot süresince SSMS'ten yapılmış düzeltmelerin geri alınmış olabileceği **doğrulanmadı**, ancak kod buna izin veriyor. Ayrıca `RentalProducts.RequiresSerial` değeri değişirse mevcut envanter kuralları geriye dönük olarak değişir.

Not: Uygulamada `SecurityDevices` ve `MaintenanceContracts` için düzenleme ucu yok (`Grep: UPDATE dbo.SecurityDevices` → yok). Bu yüzden düzeltmeler bugün ancak SSMS üzerinden yapılabiliyor; bu da sorunu sessiz kılıyor.

**Öneri:**
- Seed `MERGE`'lerini **yalnızca `WHEN NOT MATCHED THEN INSERT`** olacak şekilde değiştirin. Güncelleme gerekiyorsa ayrı, tek seferlik, sürümlü veri düzeltme scripti kullanın.
- `IsActive=1` atamasını seed'den tamamen kaldırın.
- Cihaz kütüğü ve sözleşmeler için uygulama içi düzenleme ekranı (b-öncelik) ve değişiklik geçmişi tablosu ekleyin.

---

### A3-06 — YÜKSEK — SQL için geri dönüş planı yok; geri yükleme testi kanıtlanmamış

**Konum:** `linux/04_geri_don.sh:1-18` (yalnızca `/opt/dengeerp/current` sembolik bağını eski sürüme çevirir; `:18` "VERITABANI GERİ YUKLEMESİ YAPMAZ"), `linux/02_yayinla.sh:40-58` (sağlık kontrolü başarısızsa yalnızca kodu geri alır), `linux/SQL_HAZIRLIK_YEDEK.sql` (manuel `COPY_ONLY` yedek + `VERIFYONLY`).

**Kanıt / değerlendirme:**
- Scriptlerin tamamı "ileri yönlü, ekleyici". Hiçbir `down` / geri alma scripti yok.
- Ekleyici şema sayesinde **eski kod yeni şemayla genellikle çalışır** (yeni tablolar/kolonlar nullable). Bu olumlu bir özelliktir. Ancak yeni sürümün ürettiği veri (ör. PB cihaz kalemleri, bekletme kayıtları, stok hareketleri) eski sürümde görünmez veya tutarsız görünür.
- Migration öncesi yedek alma uygulama tarafından zorunlu tutulmuyor; prosedür insan disiplinine dayanıyor.
- Proje belgesi §8.2 ve §14 "restore testi" yapılmadığını açıkça belirtiyor. `RESTORE VERIFYONLY` geri yüklemenin yerini tutmaz.
- RPO (kabul edilebilir veri kaybı süresi) ve RTO (dönüş süresi) tanımlı değil. Düzenli (zamanlanmış) yedek politikası paket içinde yok.

**Öneri:**
1. Her sürüm için yazılı "SQL geri dönüş kartı": hangi scriptler eklendi, eski kodla uyumlu mu, geri dönüşte yedekten mi dönülecek, yoksa "ileri düzeltme" mi yapılacak.
2. Migration çalıştırıcısı, bayrak açıkken önce `BACKUP DATABASE ... WITH COPY_ONLY, CHECKSUM` alsın veya en azından son yedeğin 1 saatten yeni olduğunu `msdb.dbo.backupset` üzerinden doğrulasın; değilse dursun.
3. İT ile birlikte **gerçek geri yükleme tatbikatı**: `.bak` → `DengeERP_RESTORE_TEST` → uygulama bağlanıp `/api/health` + temel ekran testleri. Sonucu proje belgesine yazın.
4. Zamanlanmış tam + fark/log yedek politikası (Recovery model kararı İT ile).

---

### A3-07 — YÜKSEK — İş emri durumu serbest metin; "İptal" kontrolleri atlıyor ve bakım dönemini kilitliyor

**Konum:** `Program.cs:473-543` (durum güncelleme), `:2808` (`IsClosingStatus` = Tamamlandı / Kapatıldı / Çözüldü), `:2539-2551` (plan tamamlama), `:2954-2965` (sonraki dönem üretimi).

**Kanıt:**
- `PATCH /api/workorders/{id}/status` gelen `request.Status` değerini **beyaz liste kontrolü olmadan** yazıyor (`:525-531`). Kiralama ucunda böyle bir liste var (`:1146-1147`), iş emrinde yok. Veritabanında da `CHECK` yok (A3-12).
- "İptal" kapanış durumu sayılmadığı için açık canlı sayaç kontrolü (`:504-509`), cihaz bakım formu zorunluluğu (`:510-513`) ve seri no kuralı (`:520-522`) **atlanıyor**. Sonuç: İptal edilmiş işte açık kalan sayaçlar oluşabilir.
- Bir cihaz PB iş emri "İptal"e çekilirse ilgili `MaintenanceDeviceItems.Status` "Bekliyor" kalır. Plan yalnızca **tüm** kalemler "Tamamlandı" olduğunda kapanıyor (`:2539-2541`). Sözleşme sayacı artmadığı için sonraki dönem (`nextSeq`) **hiç üretilmez** (`:2954`).
- "Çözüldü" kapanış sayılıyor ama `ClosedAt` yalnızca "Kapatıldı" için doluyor (`:527`). SLA/kapanış raporlarında "Çözüldü" işlerin kapanış zamanı boş kalıyor.

**Öneri:**
- İş emri durumları için tek kaynak liste (C# sabiti + `CHECK` kısıtı veya `WorkOrderStatuses` referans tablosu) ve izinli geçiş matrisi.
- "İptal"i kapanış benzeri durum olarak ele alın (açık sayaç kontrolü). PB cihaz işi iptalinde kalemi `Status='İptal'` yapın ve plan tamamlama koşulunu "tamamlandı veya gerekçeli iptal" olarak güncelleyin. Gerekçe zorunlu olsun.
- `ClosedAt` tüm kapanış durumlarında dolsun.

---

### A3-08 — YÜKSEK — Bakım formu iş emrinin asıl lokasyon ve açıklamasının üzerine yazıyor

**Konum:** `Program.cs:2519-2521`.

```sql
UPDATE dbo.WorkOrders SET SerialNo=COALESCE(@Serial,SerialNo),Location=COALESCE(@Zone,Location),Description=COALESCE(@Work,Description), ...
```

**Etki:** PB iş emrinin `Location` alanı (müşteri tesisi/adres; `:3088`) teknisyenin girdiği **cihaz bölgesi** ("Giriş A", "Kargo kabul" vb.) ile kalıcı olarak değiştiriliyor. Önceki değer hiçbir yerde saklanmıyor (status log yalnızca durum yazıyor). Sonuçlar:
- Toplu planlama "aynı müşteri + aynı lokasyon" eşitliği ister (`:677-681`). Form taslak olarak bile kaydedilse (`Complete=false`), o iş artık aynı ziyaret grubuna giremez.
- Lokasyon bazlı raporlar ve tekrar ziyaret analizi bölünür.
- `Description` alanındaki "x/y bakım dönemi, hedef tarih" bilgisi (`:3090`) kaybolur.

**Öneri:** Bölge ve yapılan iş zaten `MaintenanceDeviceItems.Zone/PerformedWork` alanlarında saklanıyor. `WorkOrders` güncellemesinden `Location` ve `Description` atamalarını kaldırın. Geçmiş kayıtlar için `WorkOrderPlans.SiteName` ve `SecurityDevices.Location` üzerinden bir kerelik düzeltme raporu çıkarın (otomatik geri yazma yapmadan önce örnekleyin).

---

### A3-09 — YÜKSEK — Kiralamada çift tahsis koruması yalnızca envanter yolunda

**Konum:** `ZZ_V112_RentalInventoryOperations.sql:62,67-68`; `Program.cs:1170-1196`, `:1280-1285`, `:3233`, `:1376-1434`, `:1436-1482`.

**Doğru olan:** `RentalInventory.RentalOrderItemId` tek kolonlu FK olduğu için bir envanter satırı aynı anda tek kaleme bağlanabilir. Atama Serializable işlem ve `UPDLOCK,HOLDLOCK` ile yapılıyor (`:1384,1402`). "Aynı seri iki kiralamaya" kuralı **envanter üzerinden** DB seviyesinde korunuyor.

**Eksikler:**
1. **Seri tekilliği ürün bazında:** `UX_RentalInventory_ProductSerial (RentalProductId, SerialNo)` (`:67-68`). Aynı fiziksel seri iki farklı ürün kodu altında envantere girilebilir.
2. **Metin seri alanları kontrolsüz:** `RentalOrders.SerialNumbers` (`PUT /api/rentals/{id}`, `:1170,1189`) ve `RentalOrderItems.SerialNumbers` (`:3233`, `:1285`) serbest metin olarak yazılıyor; tekillik kontrolü yok. Aşama geçmişindeki `SerialSnapshot` bu metinden alınıyor (`:1459`). Ekranda ve geçmişte görünen seri listesi envanterle çelişebilir; aynı seri iki aktif kiralamanın metninde yer alabilir.
3. **İptal/kapanış envanteri serbest bırakmıyor:** Durum "İptal" veya "Kapandı" yapılınca (`:1174-1196`) bağlı envanter satırlarına dokunulmuyor. "Hazır" durumda atanmış cihazlar iptal edilmiş kiralamada kilitli kalır; "Kirada" olanlar "Depoya Alındı" aşaması girilmeden serbest kalmaz.
4. Envanter düzenleme ucunda "atanmış mı" kontrolü işlem dışında (`:1355-1366`). Kontrol ile güncelleme arasında eşzamanlı bir atama araya girebilir (düşük olasılık).

**Öneri:**
- Seri tekilliğini ürün bağımsız hale getirin: normalize edilmiş seri (`UPPER(LTRIM(RTRIM()))` hesaplanmış kolon) üzerinde filtreli benzersiz index. Mevcut çakışmaları önce raporlayın.
- Metin seri alanlarını salt okunur türetilmiş alan yapın (envanter atamasından üretilsin) veya yazımda envanterle doğrulayın.
- İptal/kapanışta: "Hazır" atamaları otomatik serbest bırakın, "Kirada" olan varsa kapanışı engelleyin.

---

### A3-10 — ORTA — Müşteri / lokasyon / sözleşme ana verisi yok; metinle eşleşme

**Konum:** `WorkOrders.CustomerName/Location` (`DengeERP_Update.sql:12-14`), `SecurityDevices.CustomerName/Location` (`DengeERP_V15_Schema.sql:15-16`), `MaintenanceContracts.CustomerName` (`:37`); eşleşme `Program.cs:3010-3016` ve `:632-634`.

**Kanıt:**
- Bakım iş emri üretimi, cihaz kütüğünü `SecurityDevices.CustomerName = MaintenanceContracts.CustomerName` **tam metin eşitliği** ile buluyor (`:3011`). Seed'de sözleşme adı ile cihaz kütüğündeki müşteri adı farklı yazılmış örnekler var (ör. `BAKIM-0066`: `MEGA AVM` / `CITY'S AVM`, `DengeERP_V15_Seed.sql:2418`). Eşleşmeyen sözleşmelerde PB iş emirleri **seri numarasız ve bölgesiz** üretilir. Bu "seri uydurmama" kuralına uygun ama cihaz geçmişi kurulamaz.
- Cihazın PB kalemine bağlanması **sıra numarasıyla** yapılıyor (`inventory[ordinal-1]`, `:3032`). Kütüğe cihaz eklenir veya pasife alınırsa bir sonraki dönemde "X-Ray #2" farklı bir fiziksel cihaza karşılık gelebilir. Cihaz bazlı bakım geçmişi dönemler arasında kayabilir.
- `MaintenanceDeviceItems.SecurityDeviceId` nullable ve formda girilen seri ile kütük arasında geri bağ yok.

**Öneri (artımlı):**
1. `Customers` (Id, Ad, VergiNo NULL, Aktif) ve `CustomerSites` (Id, CustomerId, Ad, İl, İlçe, Adres) tabloları; mevcut tablolara nullable `CustomerId` / `SiteId` kolonları. Metin alanlar anlık kopya olarak kalsın.
2. `MaintenanceContracts`'a `CustomerId`/`SiteId`; cihaz eşleşmesi bu anahtarlarla yapılsın.
3. PB kalemleri sıra numarası yerine `SecurityDeviceId` ile eşlensin; formda girilen seri kütükteki seriden farklıysa "kütük düzeltme önerisi" üretilsin.
4. Bir kerelik tekilleştirme çalışması: farklı yazılmış müşteri adlarını listeleyen sorgu + insan onayı.

Logo CRM entegrasyonu kapsam dışı olduğu için ana veri DengeERP içinde tutulmalıdır.

---

### A3-11 — ORTA — Kimlik tutan kolonların çoğunda foreign key yok

Kod okunarak doğrulanan FK'siz kolonlar:

| Tablo.Kolon | Tanım yeri | Not |
|---|---|---|
| `WorkOrderStatusLogs.ChangedByUserId` | `DengeERP_Update.sql:93` | Denetim izi; kullanıcı silinirse/yanlış id yazılırsa doğrulanamaz |
| `Offers.CreatedByUserId`, `ApprovedByUserId` | `DengeERP_Update.sql:206,208` | Onay izi |
| `EmailLogs.SentByUserId` | `DengeERP_Update.sql:243` | |
| `WorkOrders.CreatedByUserId` (eski) | `DengeERP_Update.sql:19,163-166` | Eski `AppUsers` kimliği; `Program.cs:3448` `COALESCE(CreatedByErpUserId, CreatedByUserId)` ile **iki farklı kimlik uzayını** tek alanda birleştiriyor. Eski FK'nin canlı DB'de durup durmadığı **doğrulanmadı** |
| `WorkOrderTimeLogs.CreatedByUserId` | `ZZ_V110...sql:14` | |
| `WorkOrderLiveSessions.CancelledByUserId`, `ResultTimeLogId` | `ZZ_V114...sql:16-17` | Sayaç ↔ süre kaydı bağı FK'siz |
| `WorkOrderAssignments.AssignedName`, `MaintenanceDeviceItems.CompletedBy`, `MaintenanceDeviceChecks.CheckedBy`, `WorkshopTickets.AssignedTo`, `RentalOrders.ResponsibleName`, `TrainingSessions.TrainerName`, `TrainingObservations.ObserverName`, `PersonnelCompetencies.AssessedBy`, `Personnel.ManagerName` | çeşitli | Kişi **metinle** tutuluyor (A3-03) |
| `*.UnitCode` (WorkOrders, OpsLaborRates, TrainingCourses, ...) | çeşitli | Birim referans tablosu yok; `Catalog.AllUnits` yalnızca kodda |
| `WorkOrders.Priority` ↔ `OpsSlaTargets.Priority` | `DengeERP_Update.sql:17`, `ZZ_V120...sql:3` | Bilinmeyen öncelik sessizce 72 saate düşüyor (`OpsSuite.cs:31,87`) |

**Öneri:** Önce mevcut veride yetim (orphan) kayıt sorgusu çalıştırın. Ardından `WITH CHECK` ile FK'leri ekleyin; yetim kayıt varsa önce `WITH NOCHECK` ile ekleyip temizleyin. `Units` küçük referans tablosu ekleyin.

---

### A3-12 — ORTA — Durum / öncelik / sonuç alanlarında `CHECK` kısıtı yok

**Konum:** `WorkOrders.Status`, `Priority` (`DengeERP_Update.sql:17-18`), `Offers.Status` (`:199`), `RentalOrders.Status` (`:331`), `RentalInventory.ConditionStatus` (`ZZ_V112...sql:59`), `MaintenanceDeviceItems.Status`, `ServiceResult` (`DengeERP_V17_Schema.sql:11`, `DengeERP_V18...sql:15-16`), `TrainingPlans.Status` (`ZZ_V113...sql:41`).

**Değerlendirme:** Değer listeleri yalnızca uygulamada (bazı uçlarda) kontrol ediliyor; iş emri durumunda hiç kontrol yok (A3-07). Raporlar ve operasyon merkezi tam metin eşitliği kullanıyor (`OpsSuite.cs:8`). Tek karakterlik bir yazım farkı (ör. "Iptal" / "İptal") işi açık işler arasında sonsuza kadar bırakır.

Olumlu: `WorkOrderTimeLogs.ActivityType` (`ZZ_V110...sql:21`), `WorkOrderLiveSessions.ActivityType` (`ZZ_V114...sql:19-21`), `ServicePartMovements.Kind` (`ZZ_V120...sql:24`), puan aralıkları (`ZZ_V113`) için `CHECK` var. Bu desen diğer alanlara da uygulanmalı.

**Öneri:** Önce `SELECT Status, COUNT(*) ... GROUP BY Status` ile mevcut değerleri çıkarın, aykırıları düzeltin, sonra `CHECK` ekleyin. Uzun vadede durumlar için referans tablo ve FK kullanın.

---

### A3-13 — ORTA — Bekletme işlemleri durum geçmişine yazılmıyor; durum ile hold tablosu ayrışabiliyor

**Konum:** `OpsSuite.cs:138-144` (hold), `:152-158` (release); `Program.cs:525-531` (genel durum güncelleme).

**Kanıt:** Hold/release `WorkOrders.Status` değerini değiştiriyor ama `WorkOrderStatusLogs`'a satır eklemiyor. `Program.cs:3349` `InsertStatusLogAsync` OpsSuite'te çağrılmıyor. Genel durum ucu açık hold'u kontrol etmiyor: hold açıkken durum "Sahada" yapılırsa hold açık kalır; release ise yalnızca `Status='Beklemede'` iken önceki durumu geri yükler (`:156`). Bakım formu da durumu "Beklemede" yapıyor (`Program.cs:2512`) ama hold kaydı açmıyor. Yani "Beklemede" iki farklı kaynaktan geliyor ve bekleme nedeni raporları eksik kalıyor. Eşzamanlı iki hold isteğinde filtreli benzersiz index (`UX_OpsHolds_Open`) ikinciyi reddeder; ancak hata yakalanmadığı için kullanıcı 500 görür.

**Öneri:** Hold/release işlemlerinde aynı transaction içinde `InsertStatusLogAsync` çağrısı yapın. Durum ucunda açık hold varsa ya otomatik release edin ya da engelleyin. Bakım formundaki "Beklemede" geçişi gerekçeli hold kaydı açsın. 2601/2627 hatalarını 409 olarak döndürün.

---

### A3-14 — ORTA — "Tek aktif plan" DB'de garanti değil; kapalı iş yeniden planlanabiliyor; kaynak çakışması sunucuda yok

**Konum:** `Program.cs:722-761` (tekil plan), `:649-720` (toplu plan); `DengeERP_Update.sql:254-255` (benzersiz olmayan index).

**Kanıt:**
- `WorkOrderPlans` için `(WorkOrderId) WHERE IsActive=1` benzersiz index yok. Tekil plan ucu deaktive + ekleme işlemini kilitsiz yapıyor. Hiç aktif planı olmayan bir işe eşzamanlı iki istek gelirse iki aktif plan oluşur. Okuma `TOP 1 ... ORDER BY WorkOrderPlanId DESC` ile maskeleniyor (`:3458-3460`).
- Tekil plan ucu iş emrinin durumunu kontrol etmeden `Status='Planlandı'` yazıyor (`:754`). **Kapatılmış veya iptal edilmiş bir iş yeniden açılmış olur** ve `ClosedAt` dolu kalır. Toplu plan bunu engelliyor (`:682`), tekil plan engellemiyor.
- Şef/teknisyen/araç çakışması yalnızca arayüzde rozet olarak gösteriliyor (`app.js:531`); sunucuda kontrol yok (`Grep: çakış` → plan uçlarında yok). Proje belgesi §5.2'deki "çakışma denetlensin" kuralı API seviyesinde sağlanmıyor.
- Atamalarda da benzersizlik yok: eşzamanlı atama aynı kişiyi iki kez aktif ekleyebilir.

**Öneri:** Filtreli benzersiz index `UX_WorkOrderPlans_Active ON WorkOrderPlans(WorkOrderId) WHERE IsActive=1` ekleyin (önce mevcut çiftleri temizleyin). Tekil planda kapalı/iptal durum kontrolü ekleyin. Sunucu tarafında çakışma kontrolü ekleyin: aynı kişi/araç için zaman aralığı kesişimi uyarı veya engel olsun, "aynı RouteGroupNo" istisnası korunsun. `WorkOrderAssignments(WorkOrderId, AssignedName/ErpUserId) WHERE IsActive=1` için benzersiz index ekleyin.

---

### A3-15 — ORTA — Zaman kaynağı karışık

**Konum ve kanıt:**
- Uygulama saati: iş emri/kiralama/PB numara öneki `DateTime.Now` (`Program.cs:386,1098`), PB hedef ayı `DateTime.Today` (`:2897`), manuel süre kaydında "gelecek tarih" kontrolü `DateTime.Now` (`:2126`).
- SQL saati: canlı sayaç başlangıç/bitiş `SYSDATETIME()` (`:1959,2021`), tüm `CreatedAt` varsayılanları.
- Tarayıcı UTC'si: atölye `completionDate = new Date().toISOString()` (`app.js:739`) UTC değeri saat dilimi bilgisi olmayan `DATETIME2` kolona yazılıyor (Türkiye'de 3 saat geri). `entryDate` varsayılanı da UTC gösteriyor (`app.js:697`). `todayIso()` 00:00–03:00 arasında önceki günü veriyor (`app.js:5`).
- Linux geçişinde uygulama sunucusu (Ubuntu, varsayılan genellikle UTC) ve SQL sunucusu farklı saat dilimlerinde olursa: numara ayı, SLA gecikmesi (`OpsSuite.cs:28-31` `DateTime.Now` ile `CreatedAt` = SQL saati karşılaştırması), manuel/canlı süre çakışma kontrolleri ve "gelecek tarih" doğrulaması kayar.

**Öneri:** Tek kural: sunucu tarafı zamanları SQL'den (`SYSDATETIME()`) veya açık `Europe/Istanbul` dönüşümüyle üretin. İstemciden gelen tarih-saatler yerel `datetime-local` biçiminde kalsın; `toISOString()` kullanımını kaldırın. İT kontrol listesine "uygulama ve SQL sunucusu saat dilimi = Europe/Istanbul" maddesini ekleyin. Uzun vadede `datetimeoffset` kullanmayı değerlendirin.

---

### A3-16 — ORTA — Süre kaydı olmayan iş "0" olarak raporlanıyor

**Konum:** `OpsSuite.cs:88` (`recordedMinutes = minutes.GetValueOrDefault(id, 0)`), `OpsSuite.cs:230-234` (`hours = Sum(...)` → 0, `labor = 0`, `margin = Revenue − total`); gösterim `ops120.js:21`.

**Etki:** Kullanıcı kararıyla çelişiyor: "süre kaydı yoksa 'eksik' denir, 0 değil". Süre kaydı olmayan işlerde işçilik maliyeti 0 TL görünüyor ve **tahmini fark (marj) şişiyor**. Operasyon merkezinde de kayıtsız iş, 0 dakika çalışılmış iş gibi görünüyor.

**Öneri:** API kayıt yoksa `null` döndürsün (`recordedMinutes: null`, `labor: null`, `timeDataStatus: "Eksik"`). Arayüz "Süre kaydı eksik" etiketi göstersin. Marj hesabı eksik işlerde "hesaplanamadı" olsun. Kapanmış ama süre kaydı olmayan işler için ayrı bir veri kalitesi listesi oluşturun.

---

### A3-17 — ORTA — `RowVersion` kullanılmıyor; eşzamanlı güncellemede son yazan kazanır

**Konum:** `WorkOrders.RowVersion ROWVERSION` (`DengeERP_Update.sql:21`). Kodda hiç okunmuyor ve karşılaştırılmıyor (`Grep: RowVersion` → `.cs` içinde sonuç yok).

**Etki:** İki kullanıcı aynı işi aynı anda güncellediğinde (durum, seri, plan, kiralama formu) ikinci yazan, birinciyi habersizce ezer. Durum ucu eski durumu kilitsiz okuduğu için (`Program.cs:484-497`) durum geçmişindeki `OldStatus` yanlış yazılabilir. Kiralama formu tüm alanları birlikte yazıyor (`:1174-1181`).

**Öneri:** Okuma uçlarında `RowVersion` değerini (base64) döndürün; güncelleme uçlarında `WHERE WorkOrderId=@Id AND RowVersion=@Rv` kullanın, etkilenen satır 0 ise 409 dönün. `RentalOrders` için de `ROWVERSION` kolonu ekleyin. Durum ucunda okuma `WITH (UPDLOCK)` ile yapılsın.

---

### A3-18 — ORTA — Stok bakiyesi ile hareket defteri arasında mutabakat yok

**Konum:** `ZZ_V120_Operations.sql:20-24`; `OpsSuite.cs:188-213`.

**Doğru olan:** Negatif stok **DB seviyesinde** engelleniyor (`ServiceStockBalances.Quantity CHECK(Quantity>=0)`) ve uygulama Serializable + `UPDLOCK,HOLDLOCK` kullanıyor. Çıkışta iş emri zorunlu.

**Eksikler:**
- Bakiye, uygulamada hesaplanan değerle **üzerine yazılıyor** (`SET Quantity=@Qty`, `:204`). Hareket tablosundan türetilmiyor. SSMS'ten yapılan bir düzeltme veya ileride eklenecek başka bir uç defterle bakiyeyi ayrıştırabilir. Bunu yakalayacak bir kontrol yok.
- Çıkışın bağlandığı iş emrinin durumu kontrol edilmiyor; kapalı veya iptal edilmiş işe parça çıkışı yapılabiliyor (`:193`).
- Aynı parça kodu tekrar girilirse `UNIQUE` ihlali yakalanmıyor ve kullanıcıya 500 dönüyor (`:182-186`).
- Servis yedek parça stoğu, kiralama depo tablosunu (`RentalWarehouses`) paylaşıyor. Proje belgesi §5.11 iki iş mantığının ayrı izlenmesini istiyor. Bugün sorun değil, ama depo pasife alma gibi işlemler iki modülü birlikte etkiler.

**Öneri:** Günlük mutabakat sorgusu (`SUM(Giriş) − SUM(Çıkış)` = bakiye) ve fark raporu ekleyin. Bakiye güncellemesini `UPDATE ... SET Quantity = Quantity + @Delta` biçimine çevirin. Kapalı işe çıkışı engelleyin veya gerekçe zorunlu kılın. 2627 hatasını 409 olarak döndürün.

---

### A3-19 — DÜŞÜK — Index eksikleri

Pilot hacminde (binlerce satır) performans sorunu beklenmiyor. Kayıt sayısı büyüdükçe aşağıdaki tam tarama noktaları belirginleşir:

| Sorgu | Konum | Önerilen index |
|---|---|---|
| Durum geçmişi `WHERE WorkOrderId=@Id ORDER BY StatusLogId DESC` | `Program.cs:773-775` | `WorkOrderStatusLogs(WorkOrderId, StatusLogId DESC)` |
| `MaintenancePlans WHERE GeneratedWorkOrderId=@Id` | `Program.cs:514,517,3142-3145` | `MaintenancePlans(GeneratedWorkOrderId)` |
| `RentalInventory WHERE RentalOrderItemId=@Id` | `Program.cs:1214,1393,1413,1422,3215` | `RentalInventory(RentalOrderItemId)` |
| `ServicePartMovements WHERE WorkOrderId=...` (iş başına alt sorgu) | `OpsSuite.cs:225-226` | `ServicePartMovements(WorkOrderId) INCLUDE(Kind,Quantity,UnitCost)` |
| `SecurityDevices WHERE CustomerName=@Customer` | `Program.cs:3010-3011` | `SecurityDevices(CustomerName) INCLUDE(DeviceType,SerialNo,Location,IsActive)` |
| `WorkOrderLiveSessions WHERE TechnicianName=@Name AND EndedAt IS NULL` | `Program.cs:2139-2140` | Kimlik `UserId`'ye taşınınca gereksizleşir (A3-03) |
| `OfferItems(OfferId)`, `TrainingAttendance(PersonnelId)`, `TrainingPlans(PersonnelId)` | şema | FK index'leri |

Ayrıca `LoadWorkOrdersAsync` (`Program.cs:3441-3462`) her istekte **tüm** iş emirlerini ve alt sorgularını yüklüyor; `LoadTimeLogsAsync` (`:3424-3432`) da tüm süre kayıtlarını. Veri bütünlüğü sorunu değil ama ölçek riski. Filtreli sorgulara geçiş (b-öncelik) önerilir.

---

### A3-20 — DÜŞÜK — İsimsiz constraint'ler ve idempotency boşlukları

- `DEFAULT`, `CHECK` ve satır içi `REFERENCES` tanımlarının çoğu isimsiz (ör. `DengeERP_Update.sql:17-21`, `ZZ_V110...sql:7`, `ZZ_V112...sql:7-9,58`, `ZZ_V120...sql` tamamı). SQL Server rastgele adlar (`DF__WorkOrder__Prior__3B75D760` gibi) üretir. Bu adlar test ve canlı ortamda farklı olur; ileride bu kısıtları değiştirecek migration'lar dinamik ad araması yapmak zorunda kalır.
- `ZZ_V113_TrainingDevelopment.sql:30,47,125`: index'ler `IF OBJECT_ID(...) IS NULL` bloğunun **içinde**. Tablo var ama index yoksa (kısmi uygulama) index hiç oluşmaz.
- `DengeERP_Update.sql:163-167`: `ALTER COLUMN CreatedByUserId INT NULL` her çalışmada koşulsuz çalışır (şema kilidi alır).
- `DengeERP_Update.sql:428-432`: personel-kullanıcı ad eşlemesi her kurulumda yeniden yapılır (A3-03).

**Öneri:** Yeni scriptlerde tüm constraint'leri adlandırın. Index'leri ayrı `IF NOT EXISTS (sys.indexes)` bloklarında oluşturun. Koşulsuz `ALTER` ifadelerini `sys.columns.is_nullable` kontrolüne bağlayın.

---

### A3-21 — DÜŞÜK — Numara üretiminde 9999 taşması

**Konum:** `Program.cs:386-393` (SRV), `:1098-1105` (KIR); karşılaştırma için PB'de koruma var (`:3081`).

**Değerlendirme:** Kilitleme doğru (`UPDLOCK,HOLDLOCK`, `WorkOrderNo` üzerinde UNIQUE index var). Ancak `RIGHT(No,4)` ile 10.000. kayıtta `SRV-202610-10000` → sağdaki 4 hane `0000` → sıradaki numara `0001` → UNIQUE ihlali → ay sonuna kadar yeni kayıt açılamaz. Aylık 10.000 servis kaydı bugün gerçekçi değil; risk düşük. Ay öneki uygulama saatine bağlı (A3-15).

**Öneri:** PB'deki `>9999` korumasını SRV/KIR'a da ekleyin veya `SEQUENCE` nesnesine geçin.

---

### A3-22 — DÜŞÜK — Tarih ve tutarlar metin olarak saklanıyor

**Konum:** `SecurityDevices.DeliveryDateText` (`DengeERP_V15_Schema.sql:18`; seed'de Excel seri değerleri, ör. `N'42721'` `DengeERP_V15_Seed.sql:6`, ve `N'00.00.2015'`), `MaintenanceContracts.FrequencyText/MaintenanceFeeText/PeriodText` (`:40-43`; seed'de `N'17.02.2026-17.02-2027'`, `N'2100 USD + KDV'` gibi değerler).

**Etki:** Garanti bitişi, sözleşme dönemi ve döviz cinsi hesaplanamıyor. Bu durum A3-02'deki dönem sorununu doğrudan besliyor. `Total2026` gibi yıla adı verilmiş kolon (`:46`) 2027'de anlamsızlaşır.

**Öneri:** `DeliveryDate DATE NULL`, `ContractStart/End DATE NULL`, `FeeAmount DECIMAL`, `FeeCurrency CHAR(3)` kolonlarını ekleyin. Bir kerelik dönüştürme scripti yazın: Excel seri sayısı → tarih, `dd.MM.yyyy` → tarih, dönüştürülemeyen → `NULL` + "kontrol gerekli" listesi. Metin kolonları kaynak olarak kalsın. `Total2026` yerine yıl bazlı ayrı tablo kullanın.

---

## 4. Kullanıcının özel sorularına kısa cevaplar

| Soru | Cevap | Dayanak |
|---|---|---|
| Tek aktif sayaç DB seviyesinde mi? | **Evet.** Filtreli benzersiz index `UX_LiveSessions_OneActivePerUser (TechnicianUserId) WHERE EndedAt IS NULL`. Uygulama 2601/2627'yi 409'a çeviriyor. | `ZZ_V114...sql:26-29`; `Program.cs:1979-1981` |
| Süre kayıtlarında çakışma DB seviyesinde mi? | **Hayır.** Uygulamada, Serializable işlemle ve **ad metni** üzerinden kontrol ediliyor. Geçerlilik (`Ended>Started`, ≤18 sa) DB'de `CHECK` ile korunuyor. | `ZZ_V110...sql:20`; `Program.cs:2039-2045,2144-2151` |
| Mola kişi-saate dahil mi? | **Hayır**, doğru. Mola süre kaydına dönüşmüyor; süre tablosunun `CHECK` listesinde "Mola / Ara" yok. | `Program.cs:2037`; `ZZ_V110...sql:21` |
| Negatif stok DB seviyesinde mi? | **Evet.** `CHECK(Quantity>=0)` + Serializable + `UPDLOCK,HOLDLOCK`. Defter-bakiye mutabakatı yok (A3-18). | `ZZ_V120...sql:21`; `OpsSuite.cs:194-202` |
| Çift tahsis (kiralama) DB seviyesinde mi? | **Kısmen.** Envanter satırı tek kaleme bağlanabiliyor (tek FK kolonu); seri tekilliği ürün bazında. Metin seri alanları ve iptal akışı korumasız (A3-09). | `ZZ_V112...sql:62,67-68` |
| 1 cihaz = 1 PB iş emri DB seviyesinde mi? | **Evet.** `UX_MDI_WorkOrderId` + `UQ_MDI_PlanTypeOrdinal`. Dönem içi seri tekrar kontrolü yalnızca uygulamada ve yalnızca kapanışta yapılıyor. | `DengeERP_V18...sql:24-28`; `DengeERP_V17_Schema.sql:18`; `Program.cs:2505-2509` |
| Bakım sayacı bir kez mi artıyor? | **Evet (yeni yol):** `IsCompleted=0` + `@@ROWCOUNT=1`. Eski yol (`CompleteMaintenanceFromWorkOrderAsync`) kilitsiz okuyup koşulsuz güncelliyor; eşzamanlı kapanışta çift artış teorik olarak mümkün (doğrulanmadı, düşük olasılık). **Yıl devri hatası ayrı (A3-02).** | `Program.cs:2542-2550`; `:3142-3173` |
| Migration sırası? | Kültüre duyarlı alfabetik; mevcut 11 dosyada doğru sonuç veriyor ama `ZZ_` önekine bağlı (A3-04). | `Program.cs:30` |
| Sürüm takibi tablosu? | **Yok** (A3-04). | — |
| Geri dönüş planı? | Yalnızca kod; SQL için yedekten dönüş, test edilmemiş (A3-06). | `linux/04_geri_don.sh:18` |
| Fiyat/maliyet sızıntısı (DB açısından)? | Stok listesinde `UnitCost` yetkiye göre gizleniyor; finans uçları `finance.prices.view` istiyor. Ayrıntılı API denetimi güvenlik raporunun konusu. | `OpsSuite.cs:173,217,240,249` |

---

## 5. Önerilen artımlı yol haritası (veritabanı açısından)

Kullanıcının öncelik sırası (c → b → a) gözetilerek, ama veri kaybı riskleri öne alınarak:

**Hemen (yeni özellik geliştirmeye başlamadan, 1–2 gün):**
1. A3-02: Yıl bazlı tamamlanma sayımı (Aralık 2026'dan önce mutlaka).
2. A3-01: `USE DengeERP` satırının kaldırılması + `DB_NAME()` ön kontrolü.
3. A3-08: Bakım formunun `Location`/`Description` üzerine yazmasının kaldırılması.
4. Canlı pilot DB'nin şema envanteri ve script çıktısıyla karşılaştırılması (A3-04 madde 5).

**Yeni modül/özellik çalışmalarıyla birlikte (c):**
5. A3-04: `SchemaVersions` tablosu + ordinal, işlemli çalıştırıcı. Her yeni özellik bundan sonra numaralı script ile gelsin.
6. A3-10: `Customers` / `CustomerSites` ana verisi (yeni özelliklerin çoğu buna dayanacak).
7. A3-03: Atama ve süre kayıtlarında `ErpUserId`.

**Mevcut modül eksikleri (b):**
8. A3-07, A3-12: Durum referansı + `CHECK` + geçiş matrisi.
9. A3-09, A3-14, A3-13, A3-16, A3-18: İş kuralı tutarlılığı düzeltmeleri.
10. A3-22: Tarih/tutar kolonlarının tiplenmesi.

**Üretime hazırlık (a):**
11. A3-06: Geri yükleme tatbikatı, yedek politikası, sürüm başına SQL geri dönüş kartı.
12. A3-05: Seed'lerin yalnızca ekleme yapacak hale getirilmesi.
13. A3-15, A3-17, A3-19, A3-20, A3-21, A3-11.

---

## 6. Doğrulanamayanlar ve açık sorular

- **Canlı Windows pilot veritabanının gerçek şeması** (hangi scriptlerin hangi sürümünün uygulandığı, eski `AppUsers` FK'sinin varlığı, `WorkOrders` kolon sayısı) kaynak koddan çıkarılamaz. SSMS ile envanter alınmalı.
- Windows pilotta seed'in her açılışta tekrar çalışması sırasında SSMS'ten yapılmış bir düzeltmenin geri alınıp alınmadığı **doğrulanmadı**.
- Mevcut veride çift aktif plan, aynı adlı kullanıcı, yetim kayıt ve geçersiz durum değeri olup olmadığı **doğrulanmadı**. Aşağıdaki sorgular salt okunur olarak önerilir:

```sql
-- Çift aktif plan
SELECT WorkOrderId, COUNT(*) FROM dbo.WorkOrderPlans WHERE IsActive=1 GROUP BY WorkOrderId HAVING COUNT(*)>1;
-- Aynı ad-soyadlı kullanıcılar
SELECT FullName, COUNT(*) FROM dbo.ErpUsers GROUP BY FullName HAVING COUNT(*)>1;
-- Atanmış ama kullanıcı/personel karşılığı olmayan isimler
SELECT DISTINCT a.AssignedName FROM dbo.WorkOrderAssignments a
WHERE a.IsActive=1 AND NOT EXISTS (SELECT 1 FROM dbo.ErpUsers u WHERE u.FullName=a.AssignedName);
-- İş emri durum değerleri
SELECT Status, COUNT(*) FROM dbo.WorkOrders GROUP BY Status ORDER BY 2 DESC;
-- 2026 bakım sayacı durumu (A3-02 etki ölçümü)
SELECT MaintenanceContractId, CustomerName, AnnualFrequency, CompletedCount
FROM dbo.MaintenanceContracts WHERE IsActive=1 AND AnnualFrequency>0 AND CompletedCount>0;
-- Sözleşme ↔ cihaz kütüğü eşleşmeyenler (A3-10)
SELECT c.SourceKey, c.CustomerName FROM dbo.MaintenanceContracts c
WHERE c.IsActive=1 AND NOT EXISTS (SELECT 1 FROM dbo.SecurityDevices d WHERE d.IsActive=1 AND d.CustomerName=c.CustomerName);
-- PB işlerinde ezilmiş lokasyon adayı (A3-08)
SELECT w.WorkOrderNo, w.Location, i.Zone FROM dbo.WorkOrders w JOIN dbo.MaintenanceDeviceItems i ON i.WorkOrderId=w.WorkOrderId
WHERE w.Location = i.Zone;
```

- Rol/yetki önerileri bu raporun konusu değil. Organizasyon şeması gelmediği için A3-03'teki "bir kullanıcı = bir personel" kuralı **varsayımdır**.
