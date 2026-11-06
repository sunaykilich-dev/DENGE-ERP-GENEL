# M02 — Planlama Takvimi ve Toplu Atama: Gereksinim Tasarımı

> **Tarih:** 21 Ekim 2026 · **Baz sürüm:** V1.20.1 (salt okunur kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Kapsam:** Gün/Hafta/Ay takvimi, plansız havuz, toplu planlama ve atama, şef/teknisyen/araç çakışması, kompakt ziyaret kartı, saha adresi ve irtibat bilgileri, rota/bölge verimliliği.
> **Uyulan kararlar:** Kapsam yalnızca teknik servis. Öncelik sırası (c) yeni özellik → (b) eksik → (a) güvenlik. 1 cihaz = 1 PB iş emri. Tahmini süre gerçek süre yerine kullanılmaz. Süre kaydı yoksa "eksik" yazılır. Logo/Flowick kapsam dışı. Teknoloji yığını korunur, geliştirme artımlı yapılır.
> **Not:** Rol önerileri, organizasyon şeması gelmeden yapılmış **varsayımlardır** (bkz. §5).

---

## 1. Mevcut durum (kod incelemesi)

### 1.1 API uçları (`Program.cs`)

| Uç | Satır | İzin | Ne yapıyor |
|---|---|---|---|
| `GET /api/workorders` | 359–368 | `workorders.view` | Tüm iş emirlerini plan ve saha alanlarıyla birlikte döndürür (`LoadWorkOrdersAsync` 3441–3492). Takvimin tek veri kaynağıdır; tarih aralığı filtresi yoktur, tüm tablo istemciye gelir. |
| `PUT /api/workorders/{id}/assignments` | 545–570 | `workorders.assign` | Aktif atamaları pasifleştirir; yeni şef ve teknisyen kayıtlarını **isim metni** olarak ekler. Kapalı iş emri kontrolü ve isim uzunluğu kontrolü yoktur. |
| `PUT /api/workorders/bulk-assign` | 573–614 | `workorders.assign` | En fazla 150 iş emri. Aynı birim ve açık durum zorunludur. Plana dokunmaz, durum günlüğüne not düşer. |
| `GET /api/workorders/{id}/site-suggestion` | 619–647 | `workorders.plan` | Saha önerisini cihaz kütüğünden ve bakım sözleşmesinden alır. `siteCity`, `siteDistrict`, `sitePhone` ve `siteDirections` **her zaman null** döner (643–645). |
| `PUT /api/workorders/bulk-plan` | 649–720 | `workorders.plan` + `workorders.assign` | Aynı müşteri, lokasyon ve birim olmalı (677–681), iş emri açık ve henüz plansız olmalı (682). Her iş emri için ayrı `WorkOrderPlans` satırı yazar ve ortak `RouteGroupNo = TPL-xxxx` atar. Durumu, önceki durum ne olursa olsun `Planlandı` yapar (712). Tek transaction içinde ve `UPDLOCK` ile çalışır (3326). **Sunucu tarafında çakışma kontrolü yoktur.** |
| `PUT /api/workorders/{id}/plan` | 722–761 | `workorders.plan` | Eski planı `IsActive=0` yapar, yenisini ekler ve durumu **koşulsuz** `Planlandı` yapar (754). Kapalı/iptal kontrolü, tarih/süre doğrulaması ve çakışma kontrolü yoktur. Durum günlüğüne `OldStatus=NULL` yazar (757). |
| `GET /api/personnel` | 1733–1768 | `personnel.view` | Personel listesi. Şef rolünde bu izin **yoktur** (3929). |

Yardımcılar: `ReadBulkTargetsAsync` 3319, `IsBulkClosedStatus` 3316, `ValidPlanSite` 3298 (yalnızca uzunluk kontrolü), `InsertAssignmentAsync` 3338, `CanAccessWorkOrderAsync` 3385–3401 (teknisyen erişimi `FullName` metin eşleşmesine bağlı), `FilterWorkOrdersForUser` 3495–3502. İstek kayıtları: `BulkPlanRequest` 3823, `PlanRequest` 3832, `PlanSiteFields` 3830.

### 1.2 Tablolar

- `dbo.WorkOrderPlans` (`Database/DengeERP_Update.sql` 48–64; saha kolonları `ZZ_V111_PlanSites.sql` 2–24): `PlanDate DATE NOT NULL`, `StartTime TIME NULL`, `EstimatedMinutes INT NULL`, `VehiclePlate NVARCHAR(30)`, `RouteGroupNo NVARCHAR(50)`, `PlanNote`, `IsActive`, `PlannedAt` ve 8 saha alanı (`SiteName/City/District/Address/Area/Contact/Phone/Directions`). **Planı yapan kişi, değişiklik nedeni ve iptal bilgisi tutulmaz.** Eski planlar `IsActive=0` olarak kalır. Bu, erteleme geçmişi için kullanılabilir ama nedeni kaydedilmez.
- `dbo.WorkOrderAssignments` (`DengeERP_Update.sql` 33–45): `AssignedName NVARCHAR(150)` serbest metin, `AssignmentRole` ('Şef'/'Teknisyen'). Personel veya kullanıcı kimliğine FK yoktur, atamayı yapan kişi de tutulmaz.
- Araç ana tablosu, personel müsaitlik/izin tablosu ve müşteri/lokasyon ana tablosu **yoktur**. Şehir yalnızca plan satırında (`SiteCity`) bulunur; `WorkOrders` tablosunda şehir yoktur.

### 1.3 Ön yüz (`wwwroot/app.js`)

| İşlev | Satır | Not |
|---|---|---|
| `planningPage` | 507–537 | KPI kutuları (bugün, hafta, toplam, çakışmalı, bekleyen), Servis/Bakım/Tümü sekmeleri, Gün/Hafta/Ay, birim ve personel filtresi, sağda havuz, arama. |
| `planningFilteredRows` | 363–369 | Birim, iş türü ve personel filtresi uygulanır. **Çakışma hesabı da bu filtrelenmiş liste üzerinde yapılır** (513). |
| `planningConflictIds` | 392–406 | Yalnızca istemcide çalışır. Aynı gün içinde saat örtüşmesine bakar. Kişi çakışması = teknisyen kesişimi **veya** aynı şef. Şef↔teknisyen çapraz kontrolü yoktur. Plaka birebir metin karşılaştırmasıyla eşlenir. Saat boşsa 09:00, süre boşsa 60 dk varsayılır (357–361). |
| `isSameBulkVisit` | 386–391 | Aynı `TPL-` grubundaki işler birbirinin çakışması sayılmaz (V1.9 kuralı). |
| `calendarDayVisits` / `visitGroupCard` / `openCalendarVisit` | 443–482 | Kompakt ziyaret kartının anahtarı birim + müşteri + saha + şehirdir. Kartta saat, adet, Bakım/Servis/Karma etiketi ve ekip gösterilir. Modalda alt iş emirleri ayrı ayrı listelenir. |
| `planningWeekView` / `planningMonthView` | 483–506 | Haftada gün başına 4, ayda 3 kart gösterilir; fazlası için "+N" ile gün görünümüne geçilir (1946). |
| `groupedWaitingJobs` / `planningWaitingGroupsHtml` | 375–441 | Havuz müşteri + lokasyon + birim bazında gruplanır. Lokasyonu olmayan iş toplu seçilemez. |
| `openBulkPlan` | 1819–1862 | Ortak tarih, saat, süre (1–8 sa), araç, şef, ekip, not ve saha formu. |
| `openPlan` | 1864–1878 | **Önce `/assignments`, sonra `/plan` olmak üzere iki ayrı çağrı yapar (1873–1874); işlem atomik değildir.** |
| `openBulkAssign` / atama seçimi | 1679–1748 | İş Emirleri ekranından aynı birimde toplu atama. |
| `selectedPersonnel` | 1593–1606 | Şef ve teknisyen listesi `state.users` (yalnızca `users.manage` ile yüklenir, 145), `state.personnel` (`personnel.view`, 151) ve **koda gömülü `personnelFallback`** (23–26, gerçek personel adları) birleştirilerek oluşturulur. |
| İş tablosundaki "Planla" düğmesi | 328 | `workorders.plan` izni olan herkese, **iş emrinin durumundan bağımsız olarak** gösterilir. |
| Mobil görünüm (`ops120.js` 6–9) | — | Teknisyenin açık işleri listelenir. Plan tarihine göre sıralama, ziyaret gruplaması, adres/telefon/ulaşım notu yoktur. |

### 1.4 İş kuralları (özet)

1. Toplu planlama aynı müşteri, aynı lokasyon (serbest metin, büyük/küçük harf duyarsız) ve aynı birimle sınırlıdır. Her cihaz kendi iş emrini korur.
2. Toplu planlama yalnızca daha önce planlanmamış işler için yapılabilir. Planlanmış bir ziyareti toplu taşımanın yolu yoktur.
3. Plan değiştirilince eski satır pasifleşir. Planı geri alıp işi havuza döndürme uç noktası yoktur.
4. Çakışma yalnızca görsel uyarıdır; kaydı engellemez ve sunucuda kontrol edilmez.
5. Teknisyen yalnızca isim metniyle atandığı işleri görür (`FilterWorkOrdersForUser`).
6. Bildirim gönderilmez; yarın planlı işler yalnızca ERP içinde uyarı olarak görünür (`OpsSuite.cs` 33).

---

## 2. Olması gereken: Denge Elektronik için planlama çalışma modeli

### 2.1 Roller ve sorumluluklar (varsayım: org şeması gelince doğrulanacak)

| Rol | Planlamadaki görevi | Gereken izinler |
|---|---|---|
| Operasyon Uzmanı | İş kaydını eksiksiz açar (müşteri, lokasyon, şehir, irtibat). Planlamaz. | `workorders.create` |
| Birim Şefi | Kendi biriminin havuzunu günlük boşaltır. Ziyaret oluşturur, ekip ve araç atar, erteler, geri alır. Çakışma uyarısını gerekçeyle geçebilir. | `workorders.plan`, `workorders.assign` (+ yeni `planning.override`) |
| Teknik Servis Müdürü / Yardımcısı | Birimler arası personel ve araç paylaşımına karar verir, plan uyum KPI'larını izler. | Şef izinleri + `reports.view` |
| Teknisyen | Kendi gün/hafta ziyaretlerini görür; adres, irtibat ve cihaz listesine erişir. Plan değiştiremez. | `workorders.view` |
| Üst Yönetim | Yalnızca KPI ve rapor görüntüler. | `reports.view` |

### 2.2 Tutulması gereken veriler

- **Ziyaret (saha ziyareti):** Mevcut `RouteGroupNo` mantığı korunur. Ziyaret = aynı gün, saat, ekip ve sahadaki iş emri grubudur. Ayrı bir tablo şart değildir; `RouteGroupNo` ziyaret kimliği olarak kullanılabilir.
- **Plan satırı:** Planı yapan kullanıcı, oluşturma zamanı, değişiklik türü (ilk plan / erteleme / ekip değişikliği / geri alma) ve neden (kod listesi + serbest not).
- **Kaynaklar:** Atanan personel `PersonnelId` ile kaydedilir (isim yedek olarak saklanabilir). Araç bir ana kayıttan seçilir (plaka, birim, aktiflik).
- **Müsaitlik:** Personelin izin, rapor, eğitim ve ofis görevi blokları (tarih ve saat aralığı, tür). Bordro amaçlı değildir.
- **Saha:** Şehir ve ilçe iş emri açılışında girilir. Plan saha alanları, aynı müşteri + lokasyon için bir sonraki planlamada öneri kaynağı olur.

### 2.3 Durum ve akış

```text
İş kaydı (Müşteri Talebi) → Havuz [plansız]
   → Planla (tekli / toplu ziyaret)  → Planlandı
        ↳ Ertele (neden zorunlu)      → Planlandı (yeni tarih, sayaç +1)
        ↳ Planı geri al (neden)       → önceki durum, havuza döner
   → Sahada / Atölyede / Beklemede (iş emri modülü)
   → Tamamlandı / Kapatıldı  → takvimde salt okunur, plan değiştirilemez
```

Kural: Planlama **ileriye doğru** durum değiştirebilir (Müşteri Talebi → Planlandı). Planlama, `Sahada/Atölyede/Beklemede` durumundaki işin durumunu geri çekmez; yalnızca plan bilgisini günceller. Planlama `Tamamlandı/Kapatıldı/İptal` durumundaki işe hiç uygulanamaz.

### 2.4 Doğrulamalar

- Plan tarihi zorunludur. Geçmiş tarih yalnızca uyarıyla kabul edilir. Süre 15–1440 dk aralığındadır.
- Personel, şef ve araç çakışması **sunucuda** hesaplanır; tüm birimler ve iş türleri dikkate alınır, şef↔teknisyen çapraz kontrol edilir. Çakışma varsa kayıt reddedilir. `planning.override` sahibi gerekçe yazarak geçebilir; gerekçe durum günlüğüne yazılır.
- Personel müsaitlik bloğuyla örtüşen atama da çakışma sayılır.
- Saati belirsiz plan ("gün içinde") çakışma hesabına sabit 09:00 olarak girmez; ayrı bir "saat belirsiz" uyarısı üretilir.

### 2.5 KPI ve raporlar (planlama modülüne ait olanlar)

| KPI | Tanım | Veri kaynağı |
|---|---|---|
| Plan bekleyen yaşı | Havuzdaki işin açılıştan bu yana geçen günü (birim/öncelik kırılımı) | `WorkOrders.CreatedAt`, aktif plan yok |
| Plana uyum oranı | İlk saha/yol süre kaydı plan günüyle aynı gün olan ziyaretlerin oranı. Süre kaydı yoksa **"süre kaydı eksik"** yazılır, uyumsuz sayılmaz. | `WorkOrderPlans` + `WorkOrderTimeLogs`/`LiveSessions` |
| Erteleme oranı ve nedenleri | Birden fazla plan satırı olan iş emirleri ve neden dağılımı | `WorkOrderPlans` (pasif satırlar + yeni neden alanı) |
| Ziyaret başına iş emri | Ortalama cihaz/iş sayısı (bakımda toplu ziyaret verimi) | `RouteGroupNo` |
| Tekrar ziyaret | Aynı müşteri + lokasyona 30 gün içinde birden fazla ayrı ziyaret | Plan + saha alanları |
| Ekip doluluk | Personel başına planlanan dakika ÷ müsait dakika. **Tahmini süre kullanılır ve "plan doluluğu" olarak etiketlenir; gerçek süre olarak sunulmaz.** | Plan + müsaitlik |

---

## 3. Fark analizi (madde listesi)

Sıralama kullanıcı önceliğine göredir: önce YENİ, sonra EKSİK/HATA/VERİ, en sonda GÜVENLİK. **KRİTİK** etiketi sıralamadan bağımsız olarak hemen ele alınmalıdır.

> **⚠ KRİTİK (veri bütünlüğü): M02-10.** Kapatılmış iş emri "Planla" ile yeniden `Planlandı` durumuna dönebiliyor. Öncelik sırasından bağımsız olarak ilk sürümde düzeltilmeli.

### M02-01 · YENİ · Ziyaret bazında yeniden planlama (taşı / ertele)
- **Açıklama:** Takvimdeki ziyaret kartından (`RouteGroupNo`) tüm alt iş emirlerinin tarihi, saati, ekibi ve aracı tek işlemde değiştirilebilmeli. Yeni uç: `PUT /api/planning/visits/{routeGroupNo}`. Ziyaret modalına "Ziyareti Taşı" düğmesi eklenir. Tek bir iş emri ziyaretten ayrılırsa ona yeni bir grup numarası verilir.
- **Gerekçe:** AKYAKA örneğinde 17 iş emri tek ziyaret olarak planlanıyor. Ziyaret bir gün kayınca bugün 17 ayrı "Tek Planla" işlemi gerekiyor, çünkü `bulk-plan` planlı işleri reddediyor (682).
- **Mevcut:** `app.js` 474–482 modalında yalnızca "Aç" var. `Program.cs` 682 planlı işleri reddediyor.
- **Kabul:** (1) 17 işlik ziyaret tek işlemle yeni tarihe taşınır; 17 aktif plan satırının tarihi değişir, `RouteGroupNo` aynı kalır. (2) Her iş emrinin durum günlüğüne "Ziyaret taşındı: eski → yeni, neden" yazılır. (3) Kapalı alt iş emri varsa işlem reddedilir ve bu iş emirleri listelenir. (4) İşlem tek transaction'dır; bir hata olursa hiçbir satır değişmez.
- **Roller:** Şef, Müdür (`workorders.plan` + `workorders.assign`).
- **Veri:** Şema değişmez; M02-02'deki neden alanlarını kullanır.
- **Efor:** M · **Bağımlılık:** M02-02, M02-09.

### M02-02 · YENİ · Erteleme nedeni, planı geri alma ve plan geçmişi
- **Açıklama:** Plan değişikliğinde neden seçimi zorunlu olmalı. Liste: Müşteri talebi, Personel yok, Araç yok, Malzeme bekleniyor, Hava/erişim, Önceki iş uzadı, Diğer. "Planı geri al" ile iş havuza döner ve durum önceki değerine çekilir. İş emri detayında plan geçmişi sekmesi bulunur.
- **Gerekçe:** Planlar neden kayıyor? Bu, yönetimin "işler neden gecikti" sorusunun planlama ayağıdır. Bugün yanlış planlanan bir işi havuza geri almak mümkün değil.
- **Mevcut:** `WorkOrderPlans` tablosunda neden ve yapan kişi alanı yok (`DengeERP_Update.sql` 50–63). Geri alma uç noktası yok. `Program.cs` 757 eski durumu NULL yazıyor.
- **Kabul:** (1) Aktif planı olan işte tarih değiştirilirken neden boşsa API 400 döner. (2) `DELETE /api/workorders/{id}/plan` çağrısından sonra iş havuzda görünür ve durum plan öncesindeki değerine döner (Müşteri Talebi/Beklemede). (3) Plan geçmişi tarih, saat, ekip, yapan kişi ve nedeni sırayla gösterir. (4) Kapalı işte geri alma reddedilir.
- **Roller:** Şef, Müdür. Geçmişi `workorders.view` sahibi görüntüleyebilir.
- **Veri:** `WorkOrderPlans` tablosuna `PlannedByUserId INT NULL`, `ChangeType NVARCHAR(30) NULL`, `ChangeReason NVARCHAR(50) NULL`, `ChangeNote NVARCHAR(500) NULL`, `CancelledAt DATETIME2 NULL`, `PreviousStatus NVARCHAR(50) NULL` kolonları eklenir (idempotent `ZZ_V121_...sql`). Eski satırlar NULL kalır ve raporda "neden kaydı yok" diye gösterilir.
- **Efor:** M · **Bağımlılık:** yok.

### M02-03 · VERİ · Personel ve araç ana verisiyle kimlik bazlı atama; gömülü isim listesinin kaldırılması
- **Açıklama:** Atama formlarındaki şef, teknisyen ve araç listeleri, `workorders.plan` veya `workorders.assign` sahibine açık yeni bir uçtan gelmeli: `GET /api/planning/resources?unit=` (aktif personel, ünvan, birim, `PersonnelId`, bağlı `ErpUserId`; aktif araçlar). Atamada `PersonnelId` kaydedilmeli. `AssignedName` geriye uyumluluk için kalabilir. `Vehicles` tablosu eklenmeli (plaka normalize edilmiş, birim, aktif). Teknisyen görünürlüğü (`FilterWorkOrdersForUser`, `CanAccessWorkOrderAsync`) `ErpUserId ↔ PersonnelId` eşleşmesine geçirilmeli.
- **Gerekçe:** Şef rolünde `personnel.view` ve `users.manage` izni olmadığı için (`Program.cs` 3929) liste pratikte koda gömülü `personnelFallback` dizisinden geliyor (`app.js` 23–26). Yeni giren veya ayrılan personel koda müdahale etmeden güncellenemiyor. Gömülü isim ile kullanıcının `FullName` değeri farklı yazılırsa teknisyen kendi işini göremiyor (`Program.cs` 3398–3400, 3499–3500). Plaka serbest metin olduğundan "34 ABC 123" ile "34ABC123" çakışmada eşleşmiyor.
- **Mevcut:** `app.js` 1593–1606 ve 23–26; `WorkOrderAssignments.AssignedName` metin (`DengeERP_Update.sql` 39).
- **Kabul:** (1) Şef rolündeki kullanıcı, `personnel.view` izni olmadan atama formunda kendi biriminin aktif personelini görür. (2) Personel pasife alınınca formdan düşer; mevcut atamaları raporda görünmeye devam eder. (3) `app.js` içinde gerçek kişi adı kalmaz. (4) Teknisyen, adı farklı yazılmış olsa bile `PersonnelId` ile bağlı olduğu işleri görür. (5) Aynı plaka farklı boşluk veya harf büyüklüğüyle iki kez tanımlanamaz.
- **Roller:** Şef, Müdür (okuma). Araç tanımı için `operations.manage` (varsayım).
- **Veri:** `Vehicles(VehicleId, Plate, PlateNormalized UNIQUE, UnitCode, IsActive, Notes)`; `WorkOrderAssignments.PersonnelId BIGINT NULL FK`; `WorkOrderPlans.VehicleId INT NULL FK`. Mevcut isimler `Personnel.FullName` ile eşleştirilir; eşleşmeyenler **eşleşmedi** listesinde raporlanır, otomatik tahmin yapılmaz.
- **Efor:** L · **Bağımlılık:** Kullanıcı/Personel modülü (personel ↔ kullanıcı bağlantısı).

### M02-04 · YENİ · Kaynak (ekip) görünümü
- **Açıklama:** Takvime dördüncü bir mod eklenir: satırlarda personel (ve araç), sütunlarda gün (hafta) veya saat (gün). Hücrede ziyaret kartı ve günlük planlı dakika gösterilir. Boş personel tek bakışta görünür.
- **Gerekçe:** Şefin günlük sorusu "kim boş, kimi nereye gönderirim" sorusudur. Bugünkü takvim lokasyon odaklı; kişi bazlı boşluğu görmek için personel filtresini tek tek değiştirmek gerekiyor.
- **Mevcut:** Yalnızca lokasyon odaklı Gün/Hafta/Ay görünümü (`app.js` 483–506) ve tek kişi filtresi (528) var.
- **Kabul:** (1) Hafta modunda birimdeki her aktif personel için bir satır oluşur; planı olmayan personel boş satır olarak görünür. (2) Hücrede o günün toplam planlı süresi "plan" etiketiyle gösterilir. (3) Çakışma ve müsaitlik bloğu (M02-05) hücrede işaretlenir. (4) Teknisyen rolü yalnızca kendi satırını görür.
- **Roller:** Şef, Müdür.
- **Veri:** Yok (M02-03 verisini kullanır).
- **Efor:** M · **Bağımlılık:** M02-03.

### M02-05 · YENİ · Personel müsaitlik blokları (izin / rapor / eğitim / ofis)
- **Açıklama:** Şef veya İK, personel için tarih ve saat aralığı ile tür girer. Eğitim modülündeki katılımcısı belli oturumlar otomatik blok olarak okunur. Planlama bu bloklarla çakışan atamayı çakışma olarak işaretler.
- **Gerekçe:** İzindeki teknisyene iş planlanması, sahada yapılan en yaygın plan hatasıdır. Bu kayıt **bordro veya puantaj değildir**; yalnızca planlama müsaitliğidir.
- **Mevcut:** İzin veya müsaitlik tablosu yok. `TrainingSessions` var (`ZZ_V113_TrainingDevelopment.sql` 52) ama planlamaya bağlı değil.
- **Kabul:** (1) 3 günlük izin girilen personel, bu tarihlere planlanınca sunucu çakışma döndürür. (2) Eğitim oturumu katılımcısı o saatlerde "eğitimde" olarak görünür. (3) Blok silinince çakışma kalkar. (4) Blokların raporlarda kişi-saat hesabına katılmadığı test edilir.
- **Roller:** Şef (kendi birimi), İK (tümü). Yeni izin: `planning.availability.manage` (varsayım).
- **Veri:** `PersonnelAvailability(Id, PersonnelId, StartAt, EndAt, Kind, Note, CreatedByUserId, CreatedAt, IsActive)`.
- **Efor:** M · **Bağımlılık:** M02-03, M02-09.

### M02-06 · YENİ · Şehir/bölge bazlı havuz ve "aynı bölgedeki işler" önerisi
- **Açıklama:** (a) İş emri açılışına şehir ve ilçe alanı eklenir (seçimli liste; boş bırakılabilir, tahmin yapılmaz). (b) Havuz "Lokasyon" ve "Şehir/İlçe" gruplamaları arasında geçiş yapabilir. (c) Bir ziyaret planlanırken aynı şehir ve ilçedeki diğer plansız işler ile ±3 gün içindeki planlı ziyaretler yan panelde önerilir ve tek tıkla aynı güne eklenebilir.
- **Gerekçe:** Belgedeki §14 öncelik 2 maddesi: "yakın tarihlerde aynı bölgeye tekrar ziyaret". GPS veya rota optimizasyonu olmadan, küçük bir servis firmasında en çok tasarruf sağlayan adım budur.
- **Mevcut:** Şehir yalnızca plan satırında (`SiteCity`) var. Havuz sadece müşteri + lokasyon + birim bazında gruplanıyor (`app.js` 371–384).
- **Kabul:** (1) Şehir alanı girilen yeni iş, havuzda şehir grubunda görünür. (2) Şehri boş olan işler "Şehir girilmemiş" grubunda toplanır. (3) İstanbul/Üsküdar'a ziyaret planlanırken aynı ilçedeki plansız işler öneri panelinde listelenir. (4) Öneriden eklenen iş, ziyaretin tarihini, saatini ve ekibini alır ama ayrı iş emri olarak kalır.
- **Roller:** Operasyon Uzmanı (şehir girişi), Şef (planlama).
- **Veri:** `WorkOrders.City NVARCHAR(100) NULL`, `WorkOrders.District NVARCHAR(120) NULL`. Eski kayıtlar, aktif planlarındaki `SiteCity/SiteDistrict` değerlerinden **yalnızca dolu olanlar** kullanılarak doldurulabilir (tek seferlik script, raporla).
- **Efor:** M · **Bağımlılık:** İş Emri modülü (açılış formu).

### M02-07 · YENİ · Plan uyumu ve rota verimliliği raporu
- **Açıklama:** Raporlara "Plan Uyumu" sayfası ve Excel sekmesi eklenir. İçerik: §2.5'teki KPI'lar (plan bekleyen yaşı, plana uyum, erteleme oranı ve nedeni, ziyaret başına iş, tekrar ziyaret, plan doluluğu). Kırılımlar: birim, şef, teknisyen, şehir, servis/bakım.
- **Gerekçe:** Yönetimin "şef kime ne zaman atadı, plan tuttu mu" sorusu bugün cevapsız. Mevcut rapor plan ve süreyi yan yana listeliyor ama uyumu ölçmüyor (`Program.cs` 3676).
- **Mevcut:** Plan uyum metriği yok (kaynakta "plan uyum" / "ertele" araması sonuç vermedi).
- **Kabul:** (1) Planı 22.10 olup ilk saha kaydı 22.10'da olan iş "uyumlu", 23.10'da olan "kaydı", hiç süre kaydı olmayan iş "süre kaydı eksik" olarak sayılır. Eksik kayıt oranın paydasına girmez; ayrı satırda gösterilir. (2) Tahmini süre hiçbir sütunda "gerçek süre" olarak geçmez. (3) Ay filtresiyle Excel indirilir ve web ekranındaki toplamlarla aynıdır. (4) Planlı bakım ve günlük servis ayrı satırlarda raporlanır.
- **Roller:** Müdür, Üst Yönetim, Şef (kendi birimi) — `reports.view` / `reports.export`.
- **Veri:** Yok (M02-02 nedenlerini kullanır).
- **Efor:** M · **Bağımlılık:** M02-02. Erteleme nedeni kırılımı için Saha Zaman modülü verisi gerekir.

### M02-08 · EKSİK · Teknisyen "Bugünkü ziyaretlerim" görünümü ve yazdırılabilir ziyaret föyü
- **Açıklama:** Mobil ve masaüstünde teknisyene bugün/yarın ziyaretleri saat sırasıyla ve ziyaret bazında gruplu gösterilir. Her ziyarette şunlar bulunur: açık adres, ilçe/şehir, saha yetkilisi, tıklanabilir telefon (`tel:`), ulaşım/otopark notu, harita araması bağlantısı (adres metniyle, API anahtarı gerekmez), cihaz ve seri listesi, plan notu. Şef için aynı içerik PDF veya yazdırılabilir ziyaret föyü olarak alınabilir.
- **Gerekçe:** Bugün sahaya adres ve irtibat bilgisi WhatsApp ile iletiliyor. Bu bilgiler plan formunda girilmesine rağmen (`ZZ_V111_PlanSites.sql`) teknisyen ekranında gösterilmiyor.
- **Mevcut:** `ops120.js` 7–8: sadece no, müşteri, şehir ve durum; sıralama ve gruplama yok.
- **Kabul:** (1) Teknisyen girişinde yalnızca kendine atanmış bugünkü ziyaretler saat sırasıyla listelenir. (2) Telefon alanına dokununca arama başlar. (3) Ziyaret açıldığında altındaki her iş emri ayrı açılır (bakım formu bağımsızdır). (4) Föy yazdırıldığında fiyat veya maliyet alanı **bulunmaz**.
- **Roller:** Teknisyen (görüntüleme), Şef (föy).
- **Veri:** Yok.
- **Efor:** S–M · **Bağımlılık:** M02-03 (kimlik bazlı görünürlük için önerilir, şart değil).

### M02-09 · EKSİK/HATA · Çakışma kontrolünün sunucuya taşınması ve kuralların tamamlanması
- **Açıklama:** Yeni uç `POST /api/planning/check` önizleme amaçlıdır. `plan`, `bulk-plan` ve ziyaret taşıma uçları da aynı kontrolü kayıttan önce çalıştırır. Kurallar:
  (a) Tüm birimler ve iş türleri üzerinden hesaplanır; ekrandaki filtreden etkilenmez.
  (b) Şef↔teknisyen çapraz kontrol yapılır (A işinde şef olan, B işinde teknisyen olabilir).
  (c) Araç, normalize edilmiş plakayla veya `VehicleId` ile karşılaştırılır.
  (d) Aynı `RouteGroupNo` içindeki işler birbirinin çakışması sayılmaz (mevcut V1.9 kuralı korunur).
  (e) Saati boş plan "saat belirsiz" uyarısı üretir; çakışma sayılmaz.
  (f) Müsaitlik blokları (M02-05) kontrole dahil edilir.
  (g) Çakışma varsa 409 döner ve çakışan iş emirleri listelenir. `planning.override` izni olan kullanıcı gerekçeyle kaydedebilir.
- **Gerekçe:** Bugün iki şef aynı teknisyeni aynı saate planlayabiliyor; uyarı yalnızca takvimi açan kişinin ekranında görünüyor. Birim filtresi seçilince birimler arası çakışma kayboluyor (`app.js` 513 filtrelenmiş `rows` üzerinde çalışıyor). Örnek: Ertuğrul Çakır hem Haberleşme hem POC şefi olduğu için (`app.js` 25–26) çakışması gizlenebilir. Saat girilmeyen planlar 09:00/60 dk varsayımıyla sahte çakışma üretiyor (357–361).
- **Mevcut:** Yalnızca `app.js` 392–406; sunucuda kontrol yok (`Program.cs` 649–761).
- **Kabul:** (1) Haberleşme işinde 10:00–12:00 atanan kişi, POC işinde 11:00'e atanmak istendiğinde API 409 döner. (2) Takvimde birim filtresi "POC" iken bu çakışma yine işaretli görünür. (3) Şef↔teknisyen çapraz örneği yakalanır. (4) Aynı TPL ziyaretinin 17 işi birbirine çakışma vermez. (5) `planning.override` sahibi gerekçe girerek kaydeder; gerekçe durum günlüğünde görünür. Override izni olmayan kullanıcı kaydedemez. (6) Eş zamanlı iki istekten yalnızca biri başarılı olur (transaction + kilit).
- **Roller:** Şef, Müdür. Yeni izin: `planning.override` (varsayım: yalnızca Müdür ve Müdür Yardımcısı).
- **Veri:** Performans için `WorkOrderPlans(PlanDate, IsActive)` indeksi eklenir.
- **Efor:** M · **Bağımlılık:** M02-03 (kimlik bazlı karşılaştırma için; ilk adım isim ile yapılabilir).

### M02-10 · HATA · ⚠ KRİTİK (veri bütünlüğü) · Planlama, kapalı veya ilerlemiş iş emrinin durumunu geri çekiyor
- **Açıklama:**
  (a) `PUT /api/workorders/{id}/plan` durumu koşulsuz `Planlandı` yapıyor (`Program.cs` 754). İş tablosundaki "Planla" düğmesi her durumda görünüyor (`app.js` 328). Sonuç: `Kapatıldı` veya `Tamamlandı` durumundaki iş, hatta kapatılmış PB bakım iş emri, `Planlandı` durumuna döner. `ClosedAt` dolu kalır ve raporlar tutarsızlaşır. Durum ekranındaki "kapatılmış cihaz bakım emri tekrar açılamaz" koruması (`Program.cs` 502–503) bu yoldan atlatılır.
  (b) `bulk-plan`, `Sahada/Atölyede/Beklemede` durumundaki plansız işi `Planlandı` durumuna çekiyor (712).
  (c) `assignments` uç noktası kapalı işte de atamayı değiştiriyor (545–570).
- **Gerekçe:** Kapalı işin açık görünmesi; açık iş, SLA, bakım tamamlama ve KPI sayılarını bozar. Bakım sayacının tekrar tetiklenme riski doğar.
- **Mevcut:** Yukarıdaki satırlar.
- **Kabul:** (1) `Kapatıldı/Tamamlandı/İptal` durumundaki işe `PUT /plan` ve `PUT /assignments` 400 döner; veritabanında değişiklik olmaz. (2) "Planla" düğmesi bu durumlarda gizlenir; takvimde kapalı iş salt okunur açılır. (3) `Sahada` durumundaki işin planı güncellenince durum `Sahada` kalır. (4) Durum günlüğüne gerçek eski durum yazılır (NULL değil). (5) SSMS kontrolü: `SELECT COUNT(*) FROM WorkOrders WHERE ClosedAt IS NOT NULL AND Status NOT IN (N'Kapatıldı')` sorgusu pilot verisinde çalıştırılır; varsa etkilenen kayıtlar raporlanır (otomatik düzeltme yapılmaz, kullanıcıya listelenir).
- **Roller:** Tümü (kural).
- **Veri:** Şema değişmez. Mevcut bozuk kayıtlar için tespit sorgusu çalıştırılır.
- **Efor:** S · **Bağımlılık:** yok — **ilk sürümde yapılmalı.**

### M02-11 · HATA · Tekli planlamada atama ve plan atomik değil; doğrulama eksik
- **Açıklama:** `openPlan` önce `/assignments`, sonra `/plan` çağırıyor (`app.js` 1873–1874). Atama başarılı olup plan başarısız olursa yarım kayıt kalır. `workorders.plan` izni olup `workorders.assign` izni olmayan kullanıcıda ilk çağrı 403 aldığı için plan hiç kaydedilemez. `PlanRequest` doğrulamasız: `PlanDate` gönderilmezse `0001-01-01` olarak kaydedilir; `EstimatedMinutes` için sınır yok (`Program.cs` 722–752). Çözüm: tek uç (`PUT /plan` gövdesine opsiyonel `chief/technicians` eklenir) ve tek transaction. Bulk-plan ile aynı doğrulamalar uygulanır.
- **Gerekçe:** Takvimdeki ekip bilgisinin plan bilgisiyle tutarsız kalması.
- **Mevcut:** Yukarıdaki satırlar.
- **Kabul:** (1) Plan kaydı hata verdiğinde atama da değişmemiş olur. (2) Tarihsiz istek 400 döner. (3) Süre 10 veya 2000 dk olarak gönderilince 400 döner. (4) Yalnızca `workorders.plan` izni olan kullanıcı, ekip alanı değişmediği sürece planı kaydedebilir. (5) 30'dan fazla teknisyen veya 150 karakterden uzun isim reddedilir.
- **Roller:** Şef.
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** M02-10 ile birlikte yapılması önerilir.

### M02-12 · EKSİK · Saha bilgisi önerisinin önceki planlardan beslenmesi
- **Açıklama:** `site-suggestion`, aynı müşteri + lokasyon (veya aynı cihaz) için **en son kaydedilmiş plan satırındaki** şehir, ilçe, adres, irtibat, telefon ve ulaşım notunu öncelikli öneri olarak döndürmeli. Kütük ve sözleşme bilgisi ikinci kaynak olur. Öneri kaynağı alan bazında gösterilir.
- **Gerekçe:** Bugün şehir, telefon ve ulaşım notu her zaman null dönüyor (`Program.cs` 643–645). Aynı AVM'ye her bakım döneminde aynı adres ve irtibat elle tekrar yazılıyor.
- **Mevcut:** `Program.cs` 619–647, `app.js` 1804–1817 (yalnızca boş alanları doldurur; bu davranış doğru ve korunmalı).
- **Kabul:** (1) Daha önce saha bilgisiyle planlanmış lokasyonda yeni plan formu 8 alanı da önerir. (2) Kullanıcının değiştirdiği alan öneriyle ezilmez. (3) Önceki kayıt yoksa alanlar boş kalır; tahmin yapılmaz.
- **Roller:** Şef.
- **Veri:** Yok (sorgu değişikliği).
- **Efor:** S · **Bağımlılık:** yok.

### M02-13 · VERİ · Toplu planlama için lokasyon metni eşleşmesinin güçlendirilmesi
- **Açıklama:** Toplu planlama anahtarı (müşteri + lokasyon + birim) serbest metindir. "AKYAKA AVM" ile "Akyaka Avm - Ana Giriş" ayrı gruplara düşer. Önerilenler: (a) karşılaştırmada çoklu boşluk ve Türkçe büyük/küçük harf normalizasyonu (sunucu ve istemci aynı fonksiyonu kullanır); (b) havuzda seçili işlerin müşteri ve lokasyon metnini toplu düzeltme ("lokasyonu eşitle", `workorders.edit` izniyle, günlüğe yazılır). Müşteri/lokasyon ana tablosu bu modülün kapsamı dışındadır ve ilgili modüle bırakılır.
- **Gerekçe:** Kütükten aktarılan 1.324 cihaz ve elle açılan işlerde yazım farkı kaçınılmazdır; toplu planlama bu yüzden fiilen bölünüyor.
- **Mevcut:** `Program.cs` 677–681 (`Trim` + `OrdinalIgnoreCase`), `app.js` 371–374 (`tr-TR` lower). İki tarafın normalizasyonu farklı; örneğin "İ/i" ayrımı sunucuda `OrdinalIgnoreCase` ile farklı sonuç verebilir.
- **Kabul:** (1) "Akyaka  AVM" ile "AKYAKA AVM" aynı grupta toplanır ve toplu planlanır. (2) İstemcide aynı grupta görünen işler sunucuda reddedilmez (İ/ı içeren müşteri adıyla test edilir). (3) Toplu lokasyon düzeltmesi her iş emrinin günlüğüne eski ve yeni değeri yazar.
- **Roller:** Şef (`workorders.edit`).
- **Veri:** Opsiyonel `WorkOrders.LocationKey` hesaplanmış kolonu.
- **Efor:** S · **Bağımlılık:** yok.

### M02-14 · GÜVENLİK · Gerçek personel adlarının anonim statik dosyada yayınlanması
- **Açıklama:** `app.js` 23–26'daki `personnelFallback`, gerçek ad-soyadları ve birimleri içeriyor. `UseStaticFiles` (`Program.cs` 15–16) bu dosyayı oturum açmadan ağdaki herkese sunuyor. M02-03 ile liste API'ye taşınınca bu dizi kaldırılmalı.
- **Gerekçe:** KVKK ve veri minimizasyonu. Kişi adı ile birim eşleşmesi kimlik doğrulaması olmadan erişilebilir durumda. Sızıntı sınırlıdır (iletişim bilgisi yok), bu yüzden KRİTİK sayılmadı.
- **Mevcut:** Yukarıdaki satırlar.
- **Kabul:** (1) Oturumsuz `GET /app.js` yanıtında personel adı geçmez (grep testi). (2) Atama formu personeli yalnızca yetkili API çağrısıyla alır.
- **Roller:** —
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** M02-03.

### M02-15 · GÜVENLİK · Saha irtibat bilgisinin iş emri listesinde gereğinden geniş dağıtımı
- **Açıklama:** `GET /api/workorders`, saha yetkilisi adı, telefonu ve açık adresi `workorders.view` izni olan herkese döndürüyor; Depo ve Muhasebe rolleri de dahil (`Program.cs` 3453–3454, 3929–3932). Öneri: saha irtibat alanları yalnızca `workorders.plan`, atanmış ekip ve Müdür rolleri için doldurulsun; diğer rollere alan boş dönsün (fiyat alanlarındaki "API seviyesinde gizleme" ilkesiyle aynı yaklaşım).
- **Gerekçe:** Müşteri çalışanlarının kişisel iletişim verileri (KVKK).
- **Mevcut:** Yukarıdaki satırlar.
- **Kabul:** (1) Depo rolündeki kullanıcının `/api/workorders` yanıtında `sitePhone` ve `siteContact` null döner. (2) Atanmış teknisyen ve Şef bu alanları görür.
- **Roller:** Depo, Muhasebe, Genel Koordinatör (kısıtlanır).
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** Kullanıcı/Yetki modülündeki alan bazlı gizleme yaklaşımı (kararı bkz. §4).

---

## 4. Kullanıcıya sorulması gerekenler

1. **Çakışma geçme yetkisi:** Çakışan bir planı gerekçeyle kaydetme (`planning.override`) kimde olsun: yalnızca Müdür/Müdür Yardımcısı mı, yoksa şefler de mi?
2. **Erteleme neden listesi:** Önerilen liste (Müşteri talebi, Personel yok, Araç yok, Malzeme bekleniyor, Hava/erişim, Önceki iş uzadı, Diğer) yeterli mi? Eklenecek veya çıkarılacak neden var mı?
3. **Araç havuzu:** Kaç araç var? Araçlar birime mi bağlı, ortak havuzda mı? Kişiye zimmetli araç var mı? Araç plakası zorunlu alan mı olmalı?
4. **Personel müsaitliği:** İzin ve rapor bilgisini kim girecek: şef mi, İK mı? Bu bilgi başka bir sistemde (bordro/İK yazılımı) zaten tutuluyor mu?
5. **Birimler arası personel paylaşımı:** Haberleşme ve POC gibi birimler aynı şefi veya teknisyeni paylaşıyor mu? Şef, başka birimin teknisyenini kendi işine atayabilmeli mi?
6. **Çalışma saatleri:** Standart saha mesaisi (örn. 08:30–18:00) ve hafta sonu planlaması var mı? Bu bilgi "saat belirsiz" planların ve doluluk oranının paydası için gerekiyor.
7. **Şehir/ilçe kapsamı:** Hizmet verilen iller hangileri? Seçim listesi tüm Türkiye mi olsun, yoksa kısa bir liste mi?
8. **Saha irtibat bilgisinin görünürlüğü (M02-15):** Depo ve Muhasebe rollerinin saha yetkilisi telefonunu görmesi iş gereği mi?
9. **Plana uyum tanımı:** "Uyumlu" için aynı gün yeterli mi, yoksa saat toleransı da (örn. ±2 saat) aranmalı mı?
10. **Mevcut bozuk kayıtlar (M02-10):** Tespit sorgusu kapalıyken yeniden "Planlandı" olmuş kayıt bulursa bu kayıtlar sizin onayınızla mı düzeltilecek?

---

## 5. Varsayımlar

- Rol-izin eşleşmeleri `Catalog.RoleDefaults` (`Program.cs` 3921–3934) temel alınarak önerilmiştir; organizasyon şeması gelince yeniden doğrulanacaktır.
- `RouteGroupNo`, ayrı bir ziyaret tablosuna gerek duyulmadan ziyaret kimliği olarak kullanılmaya devam edecektir.
- GPS, araç takip API'si ve otomatik rota optimizasyonu bu aşamanın kapsamında değildir. Bölge verimliliği şehir/ilçe gruplaması ve öneriyle sağlanır.
- Otomatik SMS/e-posta bildirimi bu modülde ele alınmamıştır; bildirim altyapısı ayrı bir konudur.
- Müşteri/lokasyon ana tablosu ayrı bir modülün konusudur. M02-13 bu tabloya geçilene kadarki ara çözümdür.
- Plan doluluğu tahmini süreyle hesaplanır ve açıkça "plan" etiketiyle sunulur; gerçek çalışma süresi yerine kullanılmaz.

## 6. Önerilen sürüm dilimleri (artımlı)

| Dilim | Maddeler | Not |
|---|---|---|
| V1.21 (hemen) | M02-10, M02-11, M02-12 | Küçük, riskli hataları kapatır; şema değişikliği yok |
| V1.22 | M02-02, M02-01, M02-09 (isim bazlı ilk adım), M02-08 | Ziyaret taşıma, erteleme nedeni, sunucu çakışması, teknisyen ziyaret ekranı |
| V1.23 | M02-03, M02-14, M02-05, M02-04 | Kimlik bazlı kaynak modeli, müsaitlik, ekip görünümü |
| V1.24 | M02-06, M02-07, M02-13, M02-15 | Bölge önerisi, plan uyum raporu, veri kalitesi, irtibat gizleme |
