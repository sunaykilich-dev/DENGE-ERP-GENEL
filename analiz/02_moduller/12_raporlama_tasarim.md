# M12 — Raporlama ve Yönetsel KPI: Gereksinim Tasarımı

> **Sürüm tabanı:** V1.20.1 (salt okunur kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Belge tarihi:** 21.10.2026
> **Kapsam:** Yalnız teknik servis (günlük servis/arıza, planlı bakım, atölye işleri). Satış, muhasebe ve İK raporları kapsam dışıdır.
> **Kısaltmalar:** `P.cs` = `Program.cs`, `Ops.cs` = `OpsSuite.cs`, `app.js` = `wwwroot/app.js`. Satır numaraları V1.20.1 kaynağına göredir.
> **Öncelik kuralı (kullanıcı kararı):** (c) yeni özellik → (b) mevcut eksik/hata → (a) güvenlik/üretim hazırlığı. Fark listesi bu sırayla verilmiştir.

---

## 1. Mevcut durum (kodda ne var?)

### 1.1 API uçları

| Uç | Yer | İzin | Ne yapar |
|---|---|---|---|
| `GET /api/reports/worklogs` | P.cs:2181-2189 | `reports.view` | Kullanıcının görebildiği iş emirlerinin **tüm** gerçek süre kayıtlarını döner. Tarih sınırı ve sayfalama yoktur. |
| `GET /api/reports/workorders.xlsx` | P.cs:2191-2229 | `reports.export` | 8 sayfalı Excel üretir. Filtreler: `start`, `end`, `dateField` (created/plan/closed), `kind`, `unit`, `status`, `workType`, `person`, `chief`, `customer`. |
| `GET /api/ops/overview` | Ops.cs:76-110 | `dashboard.view` | Operasyon Merkezi sayaçları, geciken işler, personel iş yükü, tekrar arıza listesi, uyarılar. |
| `GET /api/ops/export.csv` | Ops.cs:259-265 | `reports.export` | 8 sütunlu düz iş emri CSV'si. |
| `GET /api/ops/finance` | Ops.cs:214-236 | `finance.prices.view` + `reports.view` | İş bazlı gelir/maliyet. Maliyet modülüne aittir (M07), bu belgede yalnız kesişim noktası olarak geçer. |
| `GET /api/timetracking/summary` | P.cs:1908-1927 | `workorders.view` | Aktif sayaçlar ve süre kayıtları. Yönetici görünümü `reports.view` ile açılır. |

### 1.2 Veri kaynakları (tablolar)

Raporlama modülünün kendine ait tablosu yoktur. Her istekte aşağıdaki kaynaklardan bellekte hesap yapılır:

- `WorkOrders`, `WorkOrderAssignments` (şef/teknisyen **isim metni**), `WorkOrderPlans` (son aktif plan ve saha alanları), `WorkOrderDevices` (seri listesi). Hepsi `LoadWorkOrdersAsync` (P.cs:3441-3493) ile **tablonun tamamı** okunarak yüklenir.
- `WorkOrderTimeLogs`: `LoadTimeLogsAsync` (P.cs:3424-3439) tabloyu yine tamamen okur. `IsVoided=0` kayıtları alır. Dakika değeri `DATEDIFF(SECOND)/60` ile hesaplanır.
- Mola: canlı sayaçta `Mola / Ara` faaliyeti `WorkOrderTimeLogs`'a yazılmaz (P.cs:2037, 2076). Böylece kişi-saate girmez. Bu, kullanıcı kararıyla uyumludur.
- `OpsSlaTargets`, `OpsHolds` (Ops.cs:13-25): SLA hedefi ve açık bekleme kayıtları.
- Rapor bunları **kullanmıyor:** `WorkOrderStatusLogs` (durum geçmişi), `MaintenancePlans` / `MaintenanceContracts` / `MaintenanceDeviceItems` / `MaintenanceDeviceChecks` (bakım dönemi ve checklist sonuçları), `ServicePartMovements` (parça kullanımı).

### 1.3 Ön yüz (`app.js`)

- Menü: `Raporlar` öğesi `reports.view` ile görünür (app.js:196).
- Filtre durumu `state.reportFilters` içinde tutulur (app.js:70). Sayfa `reportsPage()` ile çizilir (app.js:1187-1206). Hazır tarih düğmeleri: Bugün, Bu Hafta, Bu Ay, Tüm Tarihler (app.js:1988-1996).
- Sonuçlar `renderReportResults()` ile üretilir (app.js:1158-1186). Ekranda şunlar bulunur:
  - Özet KPI'lar: Toplam, Açık Günlük Servis, Açık PB, Tamamlanan, Plan Bekleyen, Kritik Açık.
  - Gerçek süre KPI'ları: kişi-saat, süresi girilen iş, aktif teknisyen, saha, yol, "Süre Kaydı Olmayan".
  - Üç süre pivotu: teknisyen, müşteri/lokasyon, ay/birim.
  - Süre hareketleri (ilk 200 satır).
  - İki çapraz özet: birim/kategori ve ay/durum.
  - Personel iş yükü ve filtrelenmiş iş emirleri (ilk 150 satır).
- **Bütün hesaplar tarayıcıda yapılıyor.** `loadCore()`, `reports.view` sahibi her kullanıcı için oturum açılışında tüm süre kayıtlarını indirir (app.js:142).
- Excel düğmesi sunucudaki ayrı bir C# hesabını çağırır (app.js:1997-2001). Yani **ekran ve Excel iki ayrı kod yoluyla** hesaplanır.

### 1.4 Excel çıktısı (`BuildWorkOrderXlsx`, P.cs:3641-3737)

| # | Sayfa | İçerik | Gözlem |
|---|---|---|---|
| 1 | Yönetim Özeti | Toplamlar, kişi-saat, saha/yol/bekleme, süre kaydı eksik iş | Açıklama satırları doğru ve dürüst: "PivotTable nesnesi değildir" (P.cs:3670). |
| 2 | Günlük Servis | 30 sütunlu iş emri detayı | Tarihler **metin** (P.cs:3678). |
| 3 | Planlı Bakım | Aynı şablon | Bakım dönemi, checklist ve uygunsuzluk bilgisi yok. |
| 4 | Birim Durum | Birim × kategori: toplam, açık, tamamlanan, kritik | Beklemede veya geciken sütunu yok. |
| 5 | Aylık Özet | Ay × kategori: açılan, tamamlanan, kritik | "Tamamlanan" bir kohort sayısıdır, o ay kapananların sayısı değildir (bkz. M12-09). |
| 6 | Personel KPI | Teknisyen × faaliyet kişi-saat | Yalnız süre kaydı olan kişiler listelenir. |
| 7 | Süre Hareketleri | Süre kayıtlarının tamamı | Tarihler metin. |
| 8 | Müşteri Lokasyon | Müşteri/şehir/lokasyon/teknisyen kişi-saat | Gruplama anahtarı teknisyenin serbest notu (`LocationNote`), bkz. M12-13. |

- Excel, `System.IO.Compression` ile elle yazılan OpenXML'dir. Ek kütüphane kullanılmaz. Başlık satırı dondurulur ve otomatik filtre eklenir (P.cs:3739-3774).
- Sayısal hücre tespiti, değerin metnine bakarak yapılır (P.cs:3760-3762). Seri no, telefon ve müşteri adı gibi yalnız rakamdan oluşan metinler **sayı hücresine** dönüşür (bkz. M12-10).
- Native `PivotTable`, `pivotCache` veya Excel Tablosu (ListObject) **yoktur**.

### 1.5 İş kuralları (mevcut)

- Kategori ayrımı: `WorkOrderNo` "PB-" ile başlıyorsa veya `WorkType = "Planlı Bakım"` ise iş planlı bakım sayılır, aksi halde günlük servis (P.cs:3638-3639; Ops.cs:9; app.js:127). Atölye işleri günlük servise dahil edilir.
- Kişi-saat yalnız gerçek başlangıç-bitiş kayıtlarından hesaplanır. Tahmini süre kullanılmaz (P.cs:3667). Bu, kullanıcı kararıyla uyumludur.
- Tarih filtresi:
  - İş emirlerinde seçilen esasa (açılış/plan/kapanış) uygulanır.
  - Süre kayıtlarında faaliyetin başlangıç tarihine uygulanır (P.cs:2216-2225).
  - Gece yarısını aşan kayıt bütünüyle başlangıç gününe yazılır.
- "Tamamlanan" = `Tamamlandı` veya `Kapatıldı` (P.cs:3650; app.js:129). "Açık" = bu ikisi ve `İptal` dışındaki her durum (app.js:128; Ops.cs:8).
- Gecikme hesabı yalnız Operasyon Merkezi'nde yapılır: `CreatedAt + SLA saati < şimdi` (Ops.cs:87). Planlı bakım işleri de bu hesaba girer.
- Tekrar arıza hesabı yalnız Operasyon Merkezi'nde yapılır: son N gün içindeki ya da açık durumdaki planlı bakım dışı işlerde aynı seri no birden fazla geçiyorsa (Ops.cs:93-96). Zaman penceresi, kapanış sırası ve iptal ayrımı yoktur.

### 1.6 İzinler (mevcut rol şablonları, P.cs:3921-3935)

| İzin | Sahip roller |
|---|---|
| `reports.view` | Üst Yönetim, Teknik Servis Müdürü, Müdür Yardımcısı, Genel Koordinatör, **Şef**, Muhasebe |
| `reports.export` | Üst Yönetim, Müdür, Müdür Yardımcısı, Genel Koordinatör, Muhasebe (**Şef yok**) |

Kapsam filtresi `FilterWorkOrdersForUser` ile uygulanır (P.cs:3495-3502):
- `AllowedUnits` boşsa kullanıcı tüm birimleri görür.
- "Teknisyen" rolü yalnız kendi adının geçtiği işleri görür (isim eşleşmesi).

### 1.7 Kanıtlı sorunlar (özet; ayrıntı bölüm 3'te)

1. Ekran (JS) ve Excel (C#) aynı KPI'yı iki ayrı kodla hesaplıyor. Tanım kayması riski var, örneğin aynı filtrede farklı sayılar çıkabilir.
2. "Süre kaydı eksik" sayısı tarih filtresinden etkileniyor. Seçilen dönemin dışında süre kaydı olan iş "eksik" görünüyor. Henüz başlamamış açık işler ve iptal işler de "eksik" sayılıyor (P.cs:3666, 3678; app.js:1175).
3. `ClosedAt` yalnız `Kapatıldı` durumunda dolduruluyor (P.cs:527, 2761). `Tamamlandı` veya `Çözüldü` olan iş kapanış tarihine göre raporlanamıyor.
4. `Çözüldü` sunucuda kapanış durumu sayılıyor (P.cs:2808), raporda ise "açık" görünüyor (app.js:128).
5. Seri no gibi yalnız rakamdan oluşan metinler Excel'de sayıya çevriliyor. 15 haneden uzun değerlerde son haneler kayboluyor (P.cs:3762, `value.Length<18`).
6. Planlı bakım bakım formu kaydedilince iş emrinin `Location` alanına cihaz bölgesi yazılıyor (P.cs:2519). Müşteri/lokasyon kırılımı bozuluyor.
7. SLA, gecikme, tekrar arıza ve bakım tamamlama verisi rapor ve Excel'de yok. Bunlar yalnız anlık Operasyon Merkezi'nde var ve PB gecikmesi orada yanlış hesaplanıyor (A4-21).
8. Native PivotTable yok (proje belgesi §7.2'deki açık talep).

---

## 2. Olması gereken (Denge Elektronik teknik servisi için)

### 2.1 Roller ve sorumluluklar (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol (varsayım) | Ne görür / ne yapar | İzin |
|---|---|---|
| Üst Yönetim, Teknik Servis Müdürü / Yardımcısı | Tüm birimler, tüm KPI'lar, trend, Excel (pivot dahil), veri kalitesi sayfası | `reports.view`, `reports.export`, `reports.personnel` (yeni) |
| Birim Şefi | Kendi birim(ler)i: günlük/haftalık operasyon, ekip kişi-saati, süre kaydı eksik işler, tekrar arıza, bakım tamamlama | `reports.view` + `reports.personnel`, kendi birimi için `reports.export` (karar §4-S1) |
| Genel Koordinatör, Muhasebe | Kurum geneli **toplam** göstergeler. Kişi bazlı süre ve not detayı görmezler (KVKK; karar §4-S2). | `reports.view`, `reports.export` |
| Teknisyen | Rapor menüsü yok. Kendi günlük özeti Saha Zaman modülünde verilir (M09-04). | — |
| Fiyat/maliyet | Standart raporda fiyat/maliyet **hiç yok**. Maliyet raporu M07-11 kapsamındadır ve `finance.prices.view` API'de kontrol edilir. | `finance.prices.view` |

### 2.2 Rapor ilkeleri (veri doğruluğu kuralları)

1. **Tek tanım, tek hesap:**
   - Her KPI sunucuda bir kez tanımlanır.
   - Ekran, Excel ve Operasyon Merkezi aynı hesap fonksiyonunu kullanır.
   - Aynı filtrede ekrandaki sayı ile Excel'deki sayı birebir eşittir.
2. **Durum grupları tek katalogdan gelir:**
   - Grup *Açık*: Müşteri Talebi, Planlamada, Planlandı, Yola Çıkıldı, Sahada, İşlemde, Atölyede, Kargoda, Beklemede, Test / Kontrol, Tekrar Açıldı.
   - Grup *Çözüldü*: Tamamlandı, Çözüldü, Kapatıldı.
   - Grup *İptal*: İptal.
   - Katalog dışı bir durum "Tanımsız durum" olarak ayrı sayılır, hiçbir gruba sessizce eklenmez.
3. **Zaman damgaları:**
   - *Çözüm anı* (`CompletedAt`): işin ilk kez Çözüldü grubuna geçtiği an. SLA ve çözüm süresi bununla ölçülür.
   - *Kapanış anı* (`ClosedAt`): `Kapatıldı`. İdari kapanış için kullanılır.
   - İş yeniden açılırsa ikisi de temizlenir, ikinci çözümde yeniden yazılır.
4. **Akış ve stok ayrımı:**
   - "Gelen" sayısı açılış tarihine, "Çözülen" sayısı çözüm tarihine göre sayılır.
   - "Açık (dönem sonu)" = açılışı dönem sonundan önce olan, çözüm ve iptal anı dönem sonundan sonra olan (ya da hiç olmayan) işler.
   - Bu üç sayı **tarih esası seçiminden bağımsızdır**. Tarih esası seçimi yalnız detay listesini süzer.
5. **Eksik veri sıfır yazılmaz:**
   - Süre kaydı, kapanış zamanı, seri no veya cihaz eşleşmesi yoksa ilgili ölçü "eksik" ya da "ölçülemedi" olarak ayrı satırda gösterilir.
   - Bu işler oranın paydasına girmez.
   - Tahmini süre, gerçek süre yerine hiçbir yerde kullanılmaz (kullanıcı kararı).
6. **Kişi-saat:**
   - Yalnız iptal edilmemiş gerçek kayıtlar sayılır. Mola hariçtir.
   - İki kişi 2'şer saat çalışırsa 4 kişi-saat olur.
   - Rapor bordro veya mesai puantajı değildir. Ekran ve Excel'de bu not yazılı durur.
7. **Kategori:** Günlük Servis, Planlı Bakım ve Atölye her yerde ayrı satır veya sütundur. Planlı bakım işleri günlük servis gecikme ve tekrar arıza oranlarını şişirmez.
8. **Planlı bakım gecikmesi SLA saatine göre değil, bakım hedef dönemine göre ölçülür:** `MaintenancePlans.TargetDate`'in ay sonu geçmiş ve iş kapanmamışsa gecikmiş sayılır (A4-21 ile uyumlu).

### 2.3 KPI kataloğu (az ama işe yarar)

| Kod | KPI | Tanım | Kırılım | Kimin için |
|---|---|---|---|---|
| K01 | Gelen iş | Dönemde açılan iş emri (kategori ayrı) | birim, iş türü, müşteri, şehir, öncelik | Müdür, Şef |
| K02 | Çözülen iş | Dönemde `CompletedAt` olan iş | birim, şef, teknisyen | Müdür, Şef |
| K03 | Açık iş (dönem sonu) ve yaş dağılımı | §2.2-4'teki tanım; yaş grupları 0-2 / 3-7 / 8-14 / 15-30 / 30+ gün | birim, şef, durum, bekleme nedeni | Müdür, Şef |
| K04 | SLA uyumu (günlük servis) | Çözülen servis işlerinde hedef içinde çözülen / SLA hedefi tanımlı çözülen. Bekleme süresi düşülür. | birim, öncelik, şef, müşteri | Müdür |
| K05 | Çözüm süresi | Medyan ve ortalama (saat; takvim saati, bekleme hariç) | birim, öncelik, iş türü | Müdür |
| K06 | Geciken açık servis işi | SLA hedefi aşılmış açık servis işi (PB hariç) | birim, şef, bekleme nedeni | Şef (günlük) |
| K07 | Tek ziyarette çözüm | Çözülen servis işlerinde, saha çalışması kaydı olan farklı gün sayısı 1 olanlar / saha kaydı olanlar. Kaydı olmayan "eksik" sayılır. | teknisyen, iş türü | Müdür, Şef |
| K08 | Tekrar arıza | Dönemde çözülen servis/atölye işlerinden, çözümden sonraki N gün içinde (varsayılan 30) aynı cihaz için yeni servis işi açılanların oranı | teknisyen, müşteri, marka/model | Müdür, Şef |
| K09 | PB dönem tamamlama | Dönemdeki cihaz PB iş emirlerinden tamamlananların oranı; dönem durumu | müşteri/sözleşme, ay, şef | Müdür, Şef |
| K10 | PB zamanında tamamlama | Hedef dönem içinde tamamlanan dönem / vadesi dolmuş dönem | ay, müşteri | Müdür |
| K11 | Uygunsuz cihaz | Uygunsuz veya kontrol edilemeyen madde içeren cihaz formu sayısı ve en sık 5 madde | müşteri, cihaz tipi | Şef |
| K12 | Kişi-saat | Faaliyet kırılımlı toplam (saha, yol, bekleme, uzaktan, atölye, test, diğer) | teknisyen, şef/ekip, müşteri, birim, ay | Müdür, Şef |
| K13 | İş başına kişi-saat | Süre kaydı olan çözülmüş işlerde medyan kişi-saat | iş türü, cihaz tipi | Müdür (tahmini süre kalibrasyonu) |
| K14 | Süre kaydı eksik iş | Çözülen grubunda olup **hiçbir tarihte** geçerli süre kaydı bulunmayan iş | teknisyen, şef | Şef (günlük), Müdür |
| K15 | Bekleme nedenleri | Dönemde açılan bekleme sayısı ve toplam bekleme saati | neden, birim | Müdür |

Bu katalogda olmayan ama başka modüllerde tanımlanan raporlar şunlardır: Plan uyumu (M02-07), maliyet (M07-11), eğitim etkinliği (M08-07), zaman verisi disiplini (M09-07), cihaz kütüğü KPI'ları (M03-05). Bu raporlar M12-01'deki ortak rapor altyapısını (filtre modeli ve Excel yazıcı) kullanır.

### 2.4 Hedef Excel kitabı

Okunabilir sayfalar (mevcut 8 sayfa korunur ve düzeltilir) + yeni sayfalar + pivot için ham veri:

1. **Yönetim Özeti**: Dönem/önceki dönem karşılaştırması eklenir.
2. Günlük Servis
3. Planlı Bakım
4. Birim Durum
5. Aylık Özet: Açılan ve çözülen ayrı sayılır.
6. Personel KPI (yalnız `reports.personnel` ile)
7. Süre Hareketleri (yalnız `reports.personnel` ile)
8. Müşteri Lokasyon
9. **SLA ve Gecikme** (yeni)
10. **Tekrar Arıza** (yeni)
11. **Bakım Tamamlama** (yeni)
12. **Veri Kalitesi** (yeni)
13. **Tanımlar**: Her KPI'nın tanımı, tarih esası ve "bordro değildir" notu.
14. `Veri_IsEmirleri` ve `Veri_Sureler`: Excel Tablosu; tipli tarih ve sayı hücreleri içerir.
15. `Pivot_*`: Native PivotTable'lar; dosya açılınca yenilenir.

### 2.5 Doğrulamalar

- `start > end` → 400 (mevcut). Dönem en fazla 24 ay olabilir. Daha uzun dönem için yalnız aylık özet üretilir.
- Bilinmeyen `dateField`, `kind`, `unit` veya `status` değeri → 400. Şu an bu değerler sessizce "tümü" sayılıyor.
- Kullanıcının yetkisi olmayan birim istenirse → 403. Şu an sonuç sessizce boş dönüyor.
- `repeatDays` parametresi 7–180 aralığında olmalıdır.
- Her rapor yanıtında `generatedAt`, uygulanan filtreler ve kapsam ("Birimler: …") bulunur. Excel'de aynı bilgi Özet sayfasının başında yazılıdır.

---

## 3. Fark listesi (maddeler)

> **KRİTİK değerlendirmesi:** Bu modülde veritabanında veri kaybına veya yetkisiz finans/maliyet sızıntısına yol açan bir açık bulunmadı. Standart raporda fiyat/maliyet yok; `ops/finance` iki izinle korunuyor. M12-10 (Excel'de seri no bozulması) **yüksek önemli** bir hatadır. Bozulma yalnız çıktı dosyasında olur, kaynak veri sağlamdır. Bu yüzden KRİTİK olarak işaretlenmedi.
>
> **Uygulama notu:** M12-09, M12-10 ve M12-11 küçük ve hızlı düzeltmelerdir. Yeni raporlar (M12-03…M12-06) bunların doğruluğuna dayandığı için, öncelik sırası (c→b) korunarak ilk dilime eklenmeleri önerilir.

### (c) Yeni özellikler

#### M12-01 · YENİ · Sunucu tarafı tek KPI/rapor motoru ve ortak rapor altyapısı
- **Açıklama:**
  - `ReportService` (Program.cs dışında ayrı bir dosya, örneğin `Reports.cs`) eklenir. Filtre modeli `ReportFilter` olur ve mevcut 10 filtre ile `repeatDays` alanını içerir.
  - KPI hesapları §2.3 kataloğundaki tanımlarla burada yazılır.
  - Yeni uç: `GET /api/reports/summary?...` Ekranın ihtiyaç duyduğu toplamları, çapraz tabloları ve ilk N detay satırını döner.
  - Excel (`workorders.xlsx`) aynı servisten beslenir. Ekran artık hesap yapmaz, yalnız çizer.
  - Ortak `ExcelWriter` yardımcısı diğer modüllerin raporlarında da kullanılır (M02-07, M07-11, M08-07).
  - Her KPI'nın Türkçe tanımı tek sözlükte tutulur. Ekranda ⓘ ipucu, Excel'de "Tanımlar" sayfası olarak gösterilir.
- **Gerekçe:** Bugün aynı KPI iki dilde iki kez yazılmış: app.js:1097-1186 ve P.cs:3641-3709. Tanımlar ayrıştıkça yönetici ekranda ve Excel'de farklı sayı görür. Rapor güveni "veri doğruluğu" hedefinin temelidir.
- **Mevcut:** Ekran hesapları app.js:1158-1186. Excel hesapları P.cs:3648-3709. Ops sayaçları Ops.cs:102-105 ayrı bir üçüncü yoldur.
- **Kabul kriterleri:**
  1. Test veri setinde (en az 40 iş emri; 3 birim; servis/PB/atölye; Tamamlandı, Kapatıldı, İptal, Beklemede) 6 farklı filtre kombinasyonu için `summary` uç toplamları ile Excel "Yönetim Özeti" değerleri birebir eşittir. Bu, otomatik testle doğrulanır.
  2. app.js'te KPI hesaplayan fonksiyon kalmaz (`reportFilteredRows`, `reportTimePivot` vb. kaldırılır veya yalnız çizime indirgenir).
  3. Her KPI kutusunun ⓘ metni "Tanımlar" sayfasındaki metinle aynıdır.
  4. Yanıt `generatedAt` ve uygulanan kapsamı içerir.
- **Roller / izinler:** `reports.view` (summary), `reports.export` (Excel). Kapsam: mevcut `FilterWorkOrdersForUser`.
- **Veri değişikliği:** Yok.
- **Efor:** L
- **Bağımlılık:** M12-11 (durum grupları), M12-12 (zaman damgaları)

#### M12-02 · YENİ · Native Excel PivotTable ve tipli ham veri sayfaları
- **Açıklama:**
  - Excel'e iki ham veri sayfası eklenir: `Veri_IsEmirleri` (1 satır = 1 iş emri) ve `Veri_Sureler` (1 satır = 1 süre kaydı).
  - İkisi de Excel **Tablosu** (ListObject) olarak yazılır. Tarihler gerçek tarih hücresi, süreler sayı, seri no, telefon ve iş emri no **metin** olur.
  - Bu tablolar üzerine 3 native PivotTable kurulur. Hepsinde `refreshOnLoad=1` ayarlanır; dosya açılınca güncellenir:
    - (a) Birim × Durum Grubu × Kategori: iş sayısı
    - (b) Ay (açılış tarihi gruplu) × Kategori: gelen/çözülen
    - (c) Teknisyen × Faaliyet: kişi-saat
  - Mevcut "pivot benzeri" okunabilir sayfalar korunur. Başlıklarına "hazır özet" notu eklenir, pivot sayfaları "Pivot_" önekiyle ayrılır.
  - Elle OpenXML yazmak yerine MIT lisanslı bir NuGet kütüphanesi önerilir: ClosedXML (pivot desteği var) veya Microsoft `DocumentFormat.OpenXml`. Teknoloji yığını değişmez, yalnız bağımlılık eklenir (karar §4-S4).
- **Gerekçe:**
  - Kullanıcının açık talebi var (proje belgesi §7.2 ve §14-Öncelik 3).
  - Yönetici "kendi kırılımını" Excel'de sürükle-bırak ile kurabilir. Bu, her yeni soru için kod değişikliği ihtiyacını azaltır.
  - Bugün tarihler metin olduğu için kullanıcının elle kurduğu pivot bile ay gruplaması yapamıyor.
- **Mevcut:** P.cs:3644 ve 3670 "PivotTable değildir" notunu içeriyor. Elle yazılan OpenXML (P.cs:3711-3735) Tablo veya pivot üretmiyor. Tarihler metin (P.cs:3678, 3703).
- **Kabul kriterleri:**
  1. Dosya Excel 2016+ / Microsoft 365 masaüstünde "onarım" uyarısı olmadan açılır. Pivot sayfasında *PivotTable Alanları* bölmesi gelir.
  2. Pivot (c)'de toplam kişi-saat, "Yönetim Özeti" sayfasındaki kişi-saat ile eşittir.
  3. Pivot (b)'de açılış tarihi alanı Ay/Yıl olarak gruplanabilir.
  4. `Veri_IsEmirleri` sayfasında `0012345` seri no'su `0012345` olarak görünür. 18 haneli `123456789012345678` aynen görünür.
  5. Filtre ile 0 satır dönen raporda pivot sayfası hata vermez ve "Kayıt yok" yazar.
  6. LibreOffice Calc'ta dosya hatasız açılır. Pivot yenilemesi LibreOffice'te garanti edilmez; bu sınır "Tanımlar" sayfasında yazılıdır.
- **Roller / izinler:** `reports.export`. `Veri_Sureler` sayfası ve pivot (c) yalnız `reports.personnel` ile eklenir (M12-16).
- **Veri değişikliği:** Yok (yalnız NuGet bağımlılığı).
- **Efor:** M
- **Bağımlılık:** M12-01, M12-10

#### M12-03 · YENİ · SLA ve gecikme raporu (günlük servis)
- **Açıklama:** Ekranda yeni bir sekme ve Excel'de "SLA ve Gecikme" sayfası eklenir. İçerik:
  - (1) Çözülen servis işlerinde SLA uyumu (K04) ve çözüm süresi medyan/ortalama (K05): birim × öncelik, şef ve müşteri kırılımlı.
  - (2) Geciken açık servis işleri (K06): yaş grubu, aşım saati, bekleme nedeni.
  - (3) Bekleme nedenleri (K15): adet ve toplam saat.
  - Planlı bakım işleri bu sayfada **yer almaz**. PB gecikmesi M12-05'te ölçülür.
  - SLA hedefi, bekleme süresi düşümü ve `SlaDueAt` hesabı Operasyon Merkezi/SLA modülünde yapılır (A4-21). Bu madde o hesabı **okur ve raporlar**.
- **Gerekçe:**
  - Yönetimin ana sorusu "işler neden gecikti" (proje belgesi §1). Bugün yalnız anlık açık işin gecikmesi görülebiliyor. Kapanmış işin hedefe uyup uymadığı hiçbir yerde ölçülmüyor.
  - Ayrıca PB işleri ayın başında toplu açıldığı için 72 saat sonra "Geciken" görünüyor ve gerçek gecikmeyi gizliyor.
- **Mevcut:** Ops.cs:87 ve 102 (`CreatedAt + SLA`, bekleme düşülmüyor, PB dahil). Raporda ve Excel'de SLA yok. PB işleri `Normal` öncelikle açılıyor (P.cs:3086).
- **Kabul kriterleri:**
  1. Kritik öncelikli (hedef 12 saat) servis işi 10 saatte çözülürse "uyumlu" sayılır.
  2. 14 saatte çözülen ama 3 saat `OpsHolds` beklemesi olan iş, 11 saat üzerinden "uyumlu" sayılır.
  3. `CompletedAt` boş olan çözülmüş iş paydaya girmez. "Çözüm zamanı eksik: n" satırında sayılır.
  4. İptal işler paydaya girmez.
  5. PB-YYYYMM-#### numaralı hiçbir iş bu sayfada geçmez.
  6. Ekrandaki "Geciken" sayısı Operasyon Merkezi'ndeki "Geciken (servis)" sayısıyla aynı veride aynıdır.
- **Roller / izinler:** `reports.view` / `reports.export`. Şef kendi birimini görür.
- **Veri değişikliği:** Yok. SLA modülünün eklediği `SlaDueAt` ve bekleme süresi alanları kullanılır.
- **Efor:** M
- **Bağımlılık:** M12-01, M12-12; Operasyon/SLA modülünde A4-21 düzeltmesi

#### M12-04 · YENİ · Tekrar arıza ve tekrar ziyaret raporu
- **Açıklama:**
  - **Tekrar arıza (K08):** Bir servis veya atölye işi çözüldükten sonraki `repeatDays` gün içinde (varsayılan 30) **aynı cihaz** için yeni bir servis/atölye işi açılmışsa, *önceki* iş "tekrar arızalı" sayılır. Cihaz eşleşmesi önce `SecurityDeviceId` ile yapılır (M01-16/M03-09). Bu kimlik yoksa normalize seri no kullanılır: büyük harf ve kenar boşluğu temizliği uygulanır, baştaki sıfırlar korunur.
  - **Tekrar ziyaret (K07):** Bir iş emrinde "Saha Çalışması" kaydı olan farklı takvim günü sayısı 2 veya daha fazlaysa iş tekrar ziyaret sayılır.
  - Ekranda ve Excel'de "Tekrar Arıza" sayfası olur. Kırılımlar: önceki işte çalışan teknisyen, müşteri, marka/model, birim. Her satırda iki iş emri numarası ve aradaki gün sayısı görünür.
- **Gerekçe:**
  - Proje belgesi §1'de "aynı arıza tekrarlandı mı" sorusu var. Tekrar arıza, servis kalitesinin en doğrudan ölçüsüdür.
  - Mevcut hesap (Ops.cs:93-96) aynı anda açık iki işi, iptal edilmiş işi ve aylar arayla açılmış işi aynı şekilde "tekrar" sayıyor. Hangi işin tekrara yol açtığı ve kimin çalıştığı görünmüyor.
- **Mevcut:** Ops.cs:93-96 (seri metniyle, pencere yok, en çok 25 satır, yalnız ekranda). Raporda veya Excel'de yok.
- **Kabul kriterleri:**
  1. İş A 01.10'da çözülür, aynı seri için İş B 20.10'da açılır → A "tekrar arızalı", aradaki gün sayısı 19.
  2. İş B 15.11'de açılırsa (45 gün) → A tekrar arıza **değildir**.
  3. A ve B aynı anda açıksa → "mükerrer kayıt şüphesi" listesine düşer, tekrar arıza sayılmaz.
  4. İptal edilen iş ne tetikleyici ne de tekrar sayılır.
  5. PB iş emirleri tetikleyici değildir.
  6. Seri no'su ve cihaz kimliği olmayan iş oranın paydasına girmez, "Cihaz eşleştirilemedi: n" satırında sayılır.
  7. Çözümü son `repeatDays` günde olan işler "gözlem süresi dolmadı" olarak ayrı gösterilir ve oranın paydasına girmez.
  8. 3 haftalık örnek veride 2 tekrar ziyaret ve 1 tekrar arıza elle sayılır; rapor aynı sonucu verir.
- **Roller / izinler:** `reports.view`. Teknisyen kırılımı yalnız `reports.personnel` ile görünür.
- **Veri değişikliği:** Yok.
- **Efor:** M
- **Bağımlılık:** M12-01, M12-12; cihaz kimliği için M01-16 / M03-09 (yoksa seri no ile çalışır)

#### M12-05 · YENİ · Planlı bakım tamamlama raporu (sözleşme/dönem bazlı)
- **Açıklama:** "Bakım Tamamlama" ekran sekmesi ve Excel sayfası eklenir. Bir satır = bir sözleşme bakım dönemi (`MaintenancePlans`). Sütunlar:
  - müşteri, yıl, dönem no / yıllık frekans, hedef ay
  - cihaz iş emri sayısı, tamamlanan, uygunsuz/beklemede, açık
  - % tamamlama (K09)
  - dönem durumu: *Tamamlandı (zamanında)*, *Tamamlandı (gecikmeli)*, *Açık – süresi var*, *Açık – gecikmiş*
  - gecikme günü
  - Alt tablolar: en sık uygunsuz 5 checklist maddesi (K11) ve süre kaydı eksik PB işleri.
  - Gecikme, hedef ayın son gününe göre ölçülür. Tolerans bir karar konusudur (§4-S5).
- **Gerekçe:** Yönetimin "planlı bakımlardan hangileri yapılmadı, bakım başına hangi cihazlar tamamlandı" sorusu (proje belgesi §1) bugün raporda cevaplanmıyor. "Planlı Bakım" sayfası yalnız iş emri listesidir ve dönem/sözleşme bağlamı yoktur. KPI tanımları M04 §2.5 ile ortaktır. Bu madde onları rapor ve Excel'e taşır.
- **Mevcut:** P.cs:3682 (yalnız iş emri listesi). `MaintenancePlans`, `MaintenanceDeviceItems` ve `MaintenanceDeviceChecks` rapora bağlı değil.
- **Kabul kriterleri:**
  1. AKYAKA AVM senaryosu: 17 cihaz iş emri var; 15'i Kapatıldı, 1'i uygunsuz (Beklemede), 1'i Planlandı. Dönem satırı "%88,2 (15/17) – Açık", açık sütunu 2 gösterir.
  2. 17/17 olunca dönem "Tamamlandı" olur. Son cihazın kapanış tarihi hedef ay sonundan sonraysa "gecikmeli" yazar.
  3. Uygunsuz madde tablosundaki sayı, `MaintenanceDeviceChecks`'teki "Uygunsuz" + "Kontrol Edilemedi" sonuçlarının SQL ile sayılmasıyla aynıdır.
  4. PB işleri hiçbir SLA/gecikme sayısında 72 saat kuralına göre görünmez.
- **Roller / izinler:** `reports.view` + `maintenance.view` (ikisi birlikte). Sözleşme tutarı (`ContractTotal`, `Total2026`) bu raporda **yer almaz**.
- **Veri değişikliği:** Yok.
- **Efor:** M
- **Bağımlılık:** M12-01; M04'teki dönem/tamamlanma düzeltmeleri

#### M12-06 · YENİ · Dönem karşılaştırma ve 12 aylık trend
- **Açıklama:**
  - Yönetim Özeti'nde seçilen dönemin yanında **önceki eşit dönem** gösterilir (bu ay / geçen ay, bu hafta / geçen hafta) ve fark yazılır (±n, ±%).
  - Ayrıca son 12 ay için aylık trend tablosu ve basit çizgi grafik verilir: gelen, çözülen, dönem sonu açık (K01-K03), SLA uyumu (K04), kişi-saat (K12), tekrar arıza oranı (K08). Hepsi kategori ayrımlıdır.
  - Hazır düğmeler "Bugün / Bu Hafta / Bu Ay" yanına "Geçen Ay" ve "Son 12 Ay" eklenir.
- **Gerekçe:** Yönetici "iyiye mi gidiyoruz?" sorusunu tek sayıdan cevaplayamaz. Haftalık/aylık yönetim toplantısının çıktısı budur. Ek tablo gerekmez: açık iş sayısı geçmiş için `CreatedAt` / `CompletedAt` / `CancelledAt` üzerinden yeniden kurulur.
- **Mevcut:** Ekranda yalnız tek dönem var (app.js:1162, 1171-1175). "Aylık Özet" sayfası yalnız kohort sayıyor (P.cs:3690-3694).
- **Kabul kriterleri:**
  1. Ekim'de 30 gelen, Eylül'de 25 gelen iş varsa "+5 (+%20)" yazar.
  2. 12 aylık tabloda her ayın "dönem sonu açık" değeri, o ayın son günü süzgeci ile elle hesaplanan değerle aynıdır.
  3. Önceki dönemde hiç kayıt yoksa yüzde yerine "—" yazar, "+∞" veya hata çıkmaz.
  4. Excel "Yönetim Özeti"nde de iki dönem yan yana bulunur.
- **Roller / izinler:** `reports.view`.
- **Veri değişikliği:** Yok (M12-12 alanlarını kullanır).
- **Efor:** M
- **Bağımlılık:** M12-01, M12-12

#### M12-07 · YENİ · İş emri bazlı parça kullanımı sayfası
- **Açıklama:**
  - Excel'e ve ekrana "Parça Kullanımı" sayfası eklenir. Kaynak `ServicePartMovements`'teki `Çıkış` hareketleridir (iş emrine bağlı). Sütunlar: iş emri, kategori, müşteri, cihaz/seri, parça kodu ve adı, adet, tarih.
  - Özet tablolarda en çok kullanılan 10 parça ve parça × marka/model gösterilir.
  - **Birim maliyet ve tutar sütunları yalnız `finance.prices.view` sahibine API'den döner.** Diğer kullanıcılar için alan hiç gönderilmez; yalnız gizlenmesi yetmez.
- **Gerekçe:** Proje belgesi §1'deki "hangi yedek parçalar kullanıldı" sorusu ve §7.1'deki "malzeme giriş/çıkışı". Tekrar arıza analizini de besler: aynı modelde aynı parça tekrar değişiyor mu?
- **Mevcut:** Parça hareketleri yalnız stok ekranında görülüyor (Ops.cs:160-213). Raporda yok. Bakım formundaki parça bilgisi serbest metin (P.cs:2515, A4-22).
- **Kabul kriterleri:**
  1. 3 iş emrine toplam 5 çıkış hareketi girilmişse sayfada 5 satır vardır ve adet toplamı SQL toplamıyla eşittir.
  2. `finance.prices.view` olmayan hesapla `summary` yanıtında `unitCost` / `amount` alanı **bulunmaz**. Bu, otomatik API testiyle doğrulanır.
  3. Bakım formundaki serbest metin parça bilgisi bu sayfada "stok hareketine bağlı değil" etiketiyle ayrı listelenir, adet toplamına girmez.
- **Roller / izinler:** `reports.view` (+ `finance.prices.view` tutar için).
- **Veri değişikliği:** Yok.
- **Efor:** S
- **Bağımlılık:** M12-01; yedek parça modülünde bakım formu → stok çıkışı bağı (A4-22)

### (b) Mevcut modülün eksikleri ve hataları

#### M12-08 · EKSİK · Eksik kırılımlar: şef, müşteri (iş bazlı), şehir, öncelik, çözüm şekli
- **Açıklama:** Rapor filtre çubuğuna ve çapraz tablolara şu kırılımlar eklenir:
  - (1) **Şef bazında:** iş sayısı, çözülen, açık, geciken, ekip kişi-saati.
  - (2) **Müşteri bazında iş sayısı ve kategori:** Mevcut "Müşteri Lokasyon" yalnız süre kaydı olan işleri gösterir; süre kaydı olmayan müşteri işleri hiç görünmez.
  - (3) **Şehir ve öncelik:** filtre ve kırılım olarak.
  - (4) **Çözüm şekli:** telefon, uzaktan, yerinde, atölye (M01-02 alanı geldiğinde).
  - Teknisyen ve şef filtreleri serbest metin "içerir" araması yerine **personel listesinden seçim** olur. Kimlik bazlı atama gelince (M01-10) kimlikle eşleşir. Bugün "Ali" araması "Ali Veli" ve "Aliye"yi birlikte getiriyor.
- **Gerekçe:** Proje belgesi §7.1'deki kırılım listesi (birim, şef, teknisyen, müşteri, lokasyon, iş türü...) tam karşılanmıyor. Şef kırılımı yalnız filtre olarak var, çapraz tablo yok.
- **Mevcut:**
  - Şef yalnız metin filtresi (P.cs:2203; app.js:1106).
  - Müşteri tablosu yalnız süre kaydından üretiliyor (P.cs:3705-3709; app.js:1178).
  - Şehir ve öncelik filtresi yok (app.js:1193-1203).
  - Metin `Contains` araması (P.cs:2211; app.js:1105).
- **Kabul kriterleri:**
  1. Süre kaydı olmayan 3 işi bulunan müşteri, müşteri tablosunda "3 iş / kişi-saat: eksik" olarak görünür.
  2. Şef tablosunda şeflerin iş sayıları toplamı + "Şef atanmamış" satırı = filtrelenen iş sayısı.
  3. "Ali Veli" seçildiğinde "Aliye Kaya"nın işleri gelmez.
  4. Şehir filtresi `SiteCity` boş olan işleri "Şehir belirtilmemiş" altında gösterir, sessizce düşürmez.
- **Roller / izinler:** `reports.view`. Teknisyen ve şef kişi kırılımı `reports.personnel` ile.
- **Veri değişikliği:** Yok.
- **Efor:** M
- **Bağımlılık:** M12-01; M01-10 (kimlik), M01-02 (çözüm şekli)

#### M12-09 · HATA · Rapor hesaplama hataları (süre kaydı eksik, aylık özet, personel listesi)
- **Açıklama:** Dört hesap düzeltilir:
  - (a) **"Süre kaydı eksik" tanımı:**
    - Bugün iş, yalnız *seçilen dönemdeki* süre kayıtlarına bakılarak "eksik" sayılıyor. Dönem dışında kaydı olan iş yanlışlıkla eksik görünüyor.
    - Henüz başlamamış açık işler ve iptal işler de eksik sayılıyor.
    - Yeni tanım (K14): Çözülen grubundaki işler arasında, **hiçbir tarihte** geçerli süre kaydı olmayanlar. Açık ama "Sahada/İşlemde" durumunda olup kaydı olmayan iş ayrı bir uyarı satırında gösterilir.
    - Satır bazlı "SÜRE KAYDI YOK" etiketi de aynı tanımı kullanır.
  - (b) **Aylık Özet:**
    - "Tamamlanan İş" sütunu bugün "o ay açılıp şu an tamamlanmış" iş sayısını gösteriyor.
    - Yeni hali "Açılan (açılış ayı)" ve "Çözülen (çözüm ayı)" olarak iki bağımsız sayı olur.
    - Seçilen tarih esası bu sayfayı etkilemez.
  - (c) **Personel KPI:**
    - Bugün yalnız süre kaydı olan kişiler listeleniyor.
    - Atanmış işi olan ama kaydı olmayan teknisyen de listelenir. Sütunlar: atanan iş, çözülen iş, süre kaydı eksik iş.
  - (d) **Yönetim Özeti tutarlılığı:** "Toplam = Açık + Çözülen + İptal + Tanımsız durum" eşitliği her zaman sağlanır.
- **Gerekçe:**
  - Yanlış "eksik" sayısı teknisyene haksız disiplin baskısı yaratır, gerçek eksikleri de gizler.
  - Kohort sayısı "ekimde kaç iş kapattık" sorusuna yanlış cevap verir.
  - Hepsi kullanıcının "rapor veri doğruluğu" önceliğine doğrudan dokunuyor.
- **Mevcut:**
  - (a) P.cs:3651, 3666, 3678; app.js:1166, 1175.
  - (b) P.cs:3690-3693.
  - (c) P.cs:3696-3700 (yalnız `logs.GroupBy`).
  - (d) Bugün Özet'te iptal ve tanımsız durum satırı yok (P.cs:3655-3660).
- **Kabul kriterleri:**
  1. 20.09'da 3 saat süre kaydı olan, 05.10'da kapatılan iş, Ekim filtresinde (açılış esası) "eksik" **sayılmaz**.
  2. `Müşteri Talebi` durumundaki kaydı olmayan iş "eksik" sayılmaz. `İptal` iş de sayılmaz.
  3. 15.09'da açılıp 03.10'da çözülen iş Aylık Özet'te Eylül "Açılan" ve Ekim "Çözülen" sütunlarında görünür.
  4. Hiç süre kaydı olmayan ama 4 işe atanmış teknisyen Personel KPI'da "atanan 4, kişi-saat: eksik" olarak görünür. Kişi-saati 0 yazılmaz.
  5. Özet toplam eşitliği otomatik testle doğrulanır.
- **Roller / izinler:** —
- **Veri değişikliği:** Yok.
- **Efor:** S (M12-01 öncesi mevcut koda uygulanabilir)
- **Bağımlılık:** M12-11, M12-12

#### M12-10 · HATA · Excel hücre tipleri: seri no / telefon sayıya dönüşüyor, tarihler metin
- **Açıklama:**
  - `MakeSheet` bugün hücre tipini **değere bakarak** tahmin ediyor. `0` ile başlamayan, yalnız rakamdan oluşan ve 18 karakterden kısa her değer sayı hücresine dönüşüyor.
  - Sonuçlar:
    - 16-17 haneli seri no'larda Excel 15 hane sınırı yüzünden **son haneler değişir**.
    - Rakamlı seri no ve telefonlar bilimsel gösterime (`1,23457E+15`) düşebilir.
    - Rakamdan oluşan müşteri veya lokasyon adı sayıya döner.
  - Düzeltme: Her sayfa için **sütun şeması** (metin / tamsayı / ondalık / tarih / tarih-saat) tanımlanır. Hücre tipi şemadan gelir. Seri no, iş emri no, telefon, araç plakası ve rota numarası her zaman metindir.
  - Tarih sütunları gerçek Excel tarihi olarak yazılır (`numFmt` `dd.mm.yyyy` / `dd.mm.yyyy hh:mm`).
- **Gerekçe:** Kullanıcı kararı "seri no metin; baştaki sıfırlar ve özel karakterler korunmalı" çıktı dosyasında ihlal ediliyor. Excel'den alınan seri no ile sahadaki cihaz eşleşmiyor. Metin tarihler sıralamayı bozuyor (`02.11.2026` < `15.10.2026`).
- **Mevcut:** P.cs:3760-3762 (değer koklama), P.cs:3678 ve 3703 (`ToString("dd.MM.yyyy")`).
- **Kabul kriterleri:**
  1. Seri no `1234567890123456789`, `0012345`, `12-34/5`, `00A1` ve `123456` Excel'de birebir aynı görünür; hepsi metin hücresidir.
  2. `05321234567` ve `5321234567` telefonları metindir.
  3. "Açılış" sütunu Excel'de tarih filtresiyle "Ekim 2026" seçilebilir ve doğru sıralanır.
  4. Kişi-saat sütunları sayıdır ve `TOPLA` ile toplanabilir.
- **Roller / izinler:** —
- **Veri değişikliği:** Yok.
- **Efor:** S
- **Bağımlılık:** —

#### M12-11 · HATA · Durum grupları dağınık ve çelişkili
- **Açıklama:**
  - Açık, tamamlandı ve iptal grupları tek bir sunucu kataloğundan okunur. Bu katalog M01-09'da tanımlanan durum kataloğudur, rapor yalnız grup bilgisini kullanır.
  - Bugünkü çelişkiler:
    - `Çözüldü` sunucuda kapanış durumu (P.cs:2808), raporda ve Ops'ta açık (app.js:128; Ops.cs:8).
    - Ana panel `isOpen` fonksiyonu `Tamamlandı`'yı açık sayıyor (app.js:131), rapor kapalı sayıyor (app.js:128).
    - Excel'in durum listesinde `Yola Çıkıldı`, `Kargoda`, `Test / Kontrol` ve `Tekrar Açıldı` yok (P.cs:3684). Liste kullanılmıyor ama yanıltıcı.
    - `PATCH status` her metni kabul ettiği için katalog dışı durum oluşabiliyor (A3-07).
  - Katalog dışı durumlu iş raporda "Tanımsız durum" olarak görünür ve Veri Kalitesi sayfasına düşer.
- **Gerekçe:** Aynı iş ana panelde açık, raporda kapalı görünüyor. Yönetici "hangisi doğru" sorusuyla karşılaşıyor ve sistemin güvenilirliği zayıflıyor.
- **Mevcut:** app.js:30, 128-131; P.cs:2808, 3650, 3684; Ops.cs:8.
- **Kabul kriterleri:**
  1. `Tamamlandı`, `Çözüldü` ve `Kapatıldı` işler ana panel, Operasyon Merkezi, rapor ekranı ve Excel'de aynı grupta sayılır.
  2. Durumu `Iptal` (noktasız I) olan test kaydı "Tanımsız durum: 1" olarak görünür, açık sayılmaz.
  3. Kod tabanında durum grup listesi yalnız bir yerde tanımlıdır; grep ile doğrulanır.
- **Roller / izinler:** —
- **Veri değişikliği:** Yok (M01-09'un kataloğu).
- **Efor:** S
- **Bağımlılık:** M01-09

#### M12-12 · VERİ · Çözüm/kapanış/iptal zaman damgaları ve geçmiş verinin doldurulması
- **Açıklama:**
  - `WorkOrders` tablosuna `CompletedAt DATETIME2 NULL` (ilk çözüm anı) ve `CancelledAt DATETIME2 NULL` eklenir.
  - `ClosedAt`, yalnız `Kapatıldı` geçişinde değil, tüm uçlarda tutarlı yazılır. Durum uçları, atölye PUT'u, PB formu ve bekleme/serbest bırakma uçlarının hepsi aynı yardımcı fonksiyonu kullanır.
  - Yeniden açılışta bu alanlar temizlenir (M01-09).
  - **Geçmiş doldurma scripti** (idempotent, yalnız NULL alanları doldurur):
    - `WorkOrderStatusLogs`'tan her iş için ilk Çözüldü grubu geçişi `CompletedAt` olur.
    - İptal geçişi `CancelledAt` olur.
    - Log yoksa ve iş kapalıysa `ClosedAt` kullanılır.
    - O da yoksa alan boş bırakılır ve Veri Kalitesi'nde "çözüm zamanı eksik" olarak listelenir. Tahmini tarih **uydurulmaz**.
- **Gerekçe:** Çözülen iş sayısı (K02), SLA (K04), çözüm süresi (K05), tekrar arıza (K08) ve dönem sonu açık sayısı (K03) güvenilir bir zaman damgası olmadan hesaplanamaz. Bugün `Tamamlandı` olan iş "Kapanış Tarihi" esaslı raporda hiç görünmüyor.
- **Mevcut:**
  - `ClosedAt` yalnız `Kapatıldı`'da yazılıyor (P.cs:527, 2761) ve yeniden açılışta temizlenmiyor.
  - PB formu ayrıca yazıyor (P.cs:2520).
  - `İptal` için tarih alanı yok.
- **Kabul kriterleri:**
  1. Script iki kez çalıştırıldığında ikinci çalıştırma 0 satır değiştirir.
  2. Script sonrasında Çözüldü grubundaki her iş için ya `CompletedAt` doludur ya da iş Veri Kalitesi listesindedir.
  3. `Tamamlandı`'ya çekilen yeni iş "Kapanış/Çözüm tarihi" esaslı raporda o gün görünür.
  4. `Tekrar Açıldı` → `Tamamlandı` geçişinde `CompletedAt` ikinci çözüm anıdır.
  5. Script öncesinde `.bak` yedeği alınır (değişmez kural).
- **Roller / izinler:** —
- **Veri değişikliği:** `WorkOrders` ADD `CompletedAt`, `CancelledAt`. Geçmiş doldurma SQL scripti (`ZZ_V12x_ReportTimestamps.sql`).
- **Efor:** M
- **Bağımlılık:** M01-09

#### M12-13 · VERİ · Lokasyon kavramlarının ayrılması (tesis, cihaz bölgesi, teknisyen notu)
- **Açıklama:** Raporda üç ayrı alan olur:
  - **Tesis/Lokasyon:** öncelik sırasıyla plandaki `SiteName`, iş emrinin `Location` alanı, bakım sözleşmesinin adresi.
  - **Cihaz bölgesi:** PB'de `MaintenanceDeviceItems.Zone`.
  - **Teknisyen konum notu:** süre kaydındaki `LocationNote`.
  - "Müşteri Lokasyon" kırılımı yalnız *Tesis* alanıyla gruplanır.
  - PB formu kaydı iş emrinin `Location` alanını cihaz bölgesiyle **ezmez**. Bölge yalnız `MaintenanceDeviceItems.Zone`'a yazılır (`Description` için de aynı kural).
- **Gerekçe:**
  - Bugün teknisyenin serbest yazdığı not ("giriş kapısı", "Giriş Kapısı ", "B blok") gruplama anahtarı olduğu için aynı müşteri onlarca satıra bölünüyor.
  - PB formu, iş emrinin lokasyonunu cihaz bölgesiyle değiştiriyor. Bu yüzden "hangi müşterinin hangi lokasyonunda" sorusu cevaplanamıyor.
- **Mevcut:**
  - P.cs:3706 (`t.LocationNote ?? SiteName ?? Location` ile gruplama).
  - P.cs:2519 (`Location=COALESCE(@Zone,Location)`, `Description=COALESCE(@Work,...)`).
  - P.cs:3088 (PB iş emri ilk açılışta da `Location` = envanter bölgesi veya adres).
  - app.js:1178.
- **Kabul kriterleri:**
  1. Aynı müşterinin 5 PB cihazı farklı bölgelerdeyse "Müşteri Lokasyon" tablosunda **tek** tesis satırı vardır; bölgeler ayrı sütunda listelenir.
  2. PB formu "Bölge: Giriş Kapısı" ile kaydedildikten sonra iş emrinin `Location` alanı değişmez.
  3. Geçmiş veride PB işlerinin `Location` alanı, `MaintenanceDeviceItems.Zone` ile aynıysa rapor bunu tesis değil bölge olarak sayar. Tesis için sözleşme adresi kullanılır.
- **Roller / izinler:** —
- **Veri değişikliği:** Kolon eklenmez. PB formu UPDATE sorgusu değişir. Geçmiş satırlar için rapor tarafında öncelik kuralı uygulanır; veri ezilmez.
- **Efor:** S
- **Bağımlılık:** M04 bakım formu uçları; M03-08 (bölgenin kütüğe dönmesi)

#### M12-14 · VERİ · Veri Kalitesi sayfası (rapor güvenilirlik göstergesi)
- **Açıklama:** Ekranda bir sekme ve Excel'de "Veri Kalitesi" sayfası eklenir. Her kontrolün sayısı ve listesi verilir; listedeki iş emri numarası tıklanınca iş açılır. Kontroller:
  - (1) Süre kaydı eksik çözülmüş iş (K14)
  - (2) Çözüm/kapanış zamanı eksik çözülmüş iş
  - (3) Seri no zorunlu iş türünde seri no'su boş iş (`WorkTypeRules`)
  - (4) Tesis/şehir bilgisi boş iş
  - (5) Teknisyen atanmadan çözülmüş iş
  - (6) Tanımsız durumlu iş
  - (7) Müşteri adı yazım varyantları: büyük/küçük harf, Türkçe karakter, boşluk ve noktalama farkı ile "A.Ş./AŞ/Anonim Şirketi" eşleştirmesi; aynı normalize ada sahip farklı yazımlar gruplanır
  - (8) Cihaz eşleştirilemeyen servis işi (tekrar arıza paydası dışında kalanlar)
  - Yönetim Özeti'nin üstünde "Bu raporda n iş emrinde eksik veri var" uyarısı ve sayfaya bağlantı bulunur.
- **Gerekçe:**
  - Müşteri, cihaz ve personel ana verisi bugün serbest metin (envanter gözlemi 7).
  - Raporların doğruluğu veri girişine bağlı. Yöneticinin bir sayıya ne kadar güveneceğini bilmesi ve şefin eksikleri günlük kapatabilmesi için eksikler görünür olmalı.
  - Proje belgesi §14-Öncelik 2'de "veri kalitesi" açık iş olarak geçiyor.
- **Mevcut:** Yalnız "Süre Kaydı Eksik İş" sayısı var (P.cs:3666) ve o da hatalı (M12-09).
- **Kabul kriterleri:**
  1. Test verisine "ABC Lojistik A.Ş.", "ABC LOJİSTİK AŞ" ve "Abc Lojistik  A.Ş" kayıtları girilirse (7) numaralı kontrolde tek grup altında 3 yazım görünür.
  2. Her kontrolün sayısı listesindeki satır sayısıyla aynıdır.
  3. Şef yalnız kendi biriminin eksiklerini görür.
  4. Sayfa hiçbir veriyi otomatik düzeltmez; yalnız listeler.
- **Roller / izinler:** `reports.view` (birim kapsamıyla).
- **Veri değişikliği:** Yok.
- **Efor:** M
- **Bağımlılık:** M12-01, M12-09, M12-11, M12-12

#### M12-15 · EKSİK · Rapor sorgularının SQL'de süzülmesi; açılışta tüm süre kayıtlarının indirilmesinin kaldırılması
- **Açıklama:**
  - Rapor servisi iş emirlerini ve süre kayıtlarını SQL `WHERE` ile filtreler: tarih aralığı, birim, kategori ve kullanıcı kapsamı. Tablonun tamamı belleğe alınmaz.
  - `GET /api/reports/worklogs` tarih aralığı parametresi alır; varsayılan son 31 gündür.
  - `loadCore()` artık oturum açılışında süre kayıtlarını indirmez (app.js:142). Rapor sayfası açıldığında `summary` çağrılır.
  - Gerekli indeksler eklenir: `WorkOrderTimeLogs(StartedAt) INCLUDE(...)`, `WorkOrders(CreatedAt)`, `WorkOrders(CompletedAt)`.
- **Gerekçe:**
  - Süre kayıtları her gün birikiyor ve `reports.view` sahibi her kullanıcı her girişte hepsini indiriyor.
  - Linux sunucuda eşzamanlı birkaç şef raporu açtığında bellek ve süre sorunu doğar (A1-20, A2).
  - Bu madde M09-15 ile aynı yükleme fonksiyonlarına dokunur, birlikte yapılmalıdır.
- **Mevcut:** P.cs:3424-3439, 3441-3493 (tam tablo okuma); P.cs:2186-2188; app.js:142, 1985.
- **Kabul kriterleri:**
  1. 20.000 iş emri ve 100.000 süre kaydı içeren test veritabanında bir aylık rapor ekranı 3 saniyede, Excel 10 saniyede oluşur.
  2. Oturum açılışında ağ sekmesinde `/api/reports/worklogs` isteği görünmez.
  3. SQL'e taşıma sonrasında M12-01'in 6 filtre kombinasyonu testi aynı sonuçları verir (regresyon testi).
- **Roller / izinler:** —
- **Veri değişikliği:** Yalnız indeksler (idempotent script).
- **Efor:** M
- **Bağımlılık:** M12-01; M09-15

### (a) Güvenlik / üretime hazırlık

#### M12-16 · GÜVENLİK · Kişi bazlı rapor verisinin ayrı izne bağlanması ve dışa aktarım kaydı
- **Açıklama:**
  - (1) Yeni izin `reports.personnel` ("Personel bazlı süre ve performans raporlarını gör") eklenir. Bu izin olmadan:
    - API kişi kırılımlarını (`Personel KPI`, `Süre Hareketleri`, teknisyen bazlı tekrar arıza, teknisyen notları ve konum notları) **döndürmez**.
    - Excel bu sayfaları **içermez**.
    - Toplam kişi-saat görünmeye devam eder.
    - Rol şablonlarına eklenir (Müdür, Müdür Yrd., Üst Yönetim, Şef). Mevcut özel profillere otomatik dağıtılmaz (mevcut karar).
  - (2) Saha yetkilisi adı ve telefonu standart Excel'den çıkarılır. Yalnız "Saha detaylı" seçeneğiyle ve `workorders.plan` sahibine verilir.
  - (3) Her dışa aktarım için kayıt tutulur: `ReportExportLogs(UserId, ExportedAt, Endpoint, FiltersJson, RowCount, IncludedSheets)`. Kayıtlar yönetici ekranında listelenir.
  - (4) Rapor uçları, kullanıcının `AllowedUnits` kapsamı dışındaki bir birim filtresine 403 döner. Şu an sessizce boş sonuç dönüyor.
  - (5) Standart rapor uçlarının hiçbir yanıtında fiyat, maliyet, gelir veya sözleşme tutarı alanı bulunmaz. Bu, otomatik testle güvenceye alınır.
- **Gerekçe:**
  - Kişi bazlı süre, konum notu ve not alanları çalışan kişisel verisidir (KVKK; A1-15). Bugün Muhasebe ve Genel Koordinatör rol şablonları da bu verileri Excel ile indirebiliyor.
  - Dışa aktarımın kaydı yok (A1-16).
  - Fiyat/maliyetin API'de gizlenmesi kullanıcı kararıdır.
- **Mevcut:** P.cs:2181-2229 (yalnız `reports.view` / `reports.export`); P.cs:3676 (saha telefonu ve yetkili sütunları); P.cs:3931 (Muhasebe `reports.export`). Dışa aktarım logu yok.
- **Kabul kriterleri:**
  1. `reports.personnel` olmayan Muhasebe hesabıyla indirilen Excel'de "Personel KPI" ve "Süre Hareketleri" sayfaları yoktur; `summary` yanıtında `technicianName` alanı bulunmaz.
  2. Her Excel/CSV indirmesi `ReportExportLogs`'a doğru filtre JSON'u ve satır sayısıyla yazılır.
  3. Yalnız "Haberleşme" birimine yetkili şef `unit=Güvenlik Sistemleri` ile istek atarsa 403 alır.
  4. Rol × uç otomatik testinde: fiyat izni olmayan 4 rol için `summary` ve `xlsx` yanıtlarında `unitCost`, `amount`, `revenue` ve `ContractTotal` metinleri geçmez.
- **Roller / izinler:** Yeni `reports.personnel`. Gerekirse `reports.export.detail` (saha irtibatı; karar §4-S2).
- **Veri değişikliği:** Yeni tablo `dbo.ReportExportLogs`. `Catalog.PermissionCatalog` ve `RoleDefaults` güncellemesi.
- **Efor:** M
- **Bağımlılık:** M12-01; genel denetim izi altyapısı (A1-16)

---

### 3.1 Bilinçli olarak eklenmeyenler

- **Zamanlanmış e-posta raporu** eklenmedi: E-posta altyapısı hazır değil (proje belgesi §5.10). Ayrıca indirme kaydı ve yetki ayrımı önce gelmeli. Altyapı hazır olunca M12-01 servisiyle kolayca eklenebilir.
- **Ayrı BI aracı (Power BI vb.)** önerilmedi: Kullanıcı kararı teknolojinin korunmasıdır. Native pivot (M12-02) yönetimin ihtiyacını karşılar.
- **Teknisyen puanlama/sıralama ("en verimli teknisyen")** eklenmedi: Zaman kaydı bordro değildir ve veri disiplini henüz oturmadı. Kişi-saati kişi karşılaştırma puanına çevirmek yanıltıcı olur. Kişi kırılımı yalnız iş yükü ve veri eksikliği görünürlüğü için verilir.
- **Logo CRM / Flowick'ten veri çekmek** kapsam dışıdır (kullanıcı kararı).

### 3.2 Önerilen uygulama sırası (artımlı)

| Dilim | Maddeler | Not |
|---|---|---|
| 1 | M12-10, M12-11, M12-09, M12-12 | Küçük doğruluk düzeltmeleri ve zaman damgaları. Yeni raporların temeli. |
| 2 | M12-01, M12-03, M12-05 | Tek motor; SLA/gecikme ve bakım tamamlama (en çok sorulan iki yönetim sorusu) |
| 3 | M12-02, M12-04, M12-06 | Native pivot, tekrar arıza, trend |
| 4 | M12-08, M12-13, M12-14, M12-07 | Kırılımlar, lokasyon, veri kalitesi, parça |
| 5 | M12-15, M12-16 | Performans ve kişisel veri/denetim; Linux üretimine geçmeden önce |

---

## 4. Kullanıcıya sorulacaklar (benim karar veremeyeceğim konular)

- **S1 — Şefin Excel yetkisi:** Şef bugün raporu görüyor ama Excel indiremiyor (`reports.export` yok). Şef kendi birimi için Excel alabilsin mi?
- **S2 — Kişi bazlı veri kimde?** Personel bazlı kişi-saat ve süre hareketlerini kimler görmeli? Önerim: Müdür, Müdür Yrd., Üst Yönetim ve kendi ekibi için Şef. Genel Koordinatör ve Muhasebe yalnız toplamları görür. Saha yetkilisi adı ve telefonu Excel'de kalmalı mı?
- **S3 — "Kapanış" anı:** SLA ve "çözülen iş" için teknisyenin işi `Tamamlandı` yaptığı an mı esas alınsın (önerim), yoksa şefin `Kapatıldı` onayı mı?
- **S4 — Excel kütüphanesi ve sürüm:** Native PivotTable için MIT lisanslı bir NuGet kütüphanesi (ClosedXML veya Microsoft OpenXML SDK) eklenmesi uygun mu? Yönetim Excel'i hangi sürümde açıyor (Microsoft 365 / 2016 / LibreOffice)?
- **S5 — Planlı bakım gecikme toleransı:** Bakım dönemi hedef ayın sonunda mı gecikmiş sayılsın, yoksa bir tolerans mı olsun (örneğin +15 gün)? Bu değer sözleşmeye göre değişiyor mu?
- **S6 — Tekrar arıza penceresi:** Kaç gün içinde aynı cihaza tekrar servis açılırsa "tekrar arıza" sayılsın? Önerim 30 gün. Birime göre farklı mı olmalı (Haberleşme atölyesi / Güvenlik)?
- **S7 — Atölye kategorisi:** Haberleşme atölye işleri raporda "Günlük Servis" içinde mi kalsın, yoksa üçüncü bir kategori (Atölye) olarak mı ayrılsın? Önerim: ayrı.
- **S8 — Hafta ve dönem tanımı:** Hafta Pazartesi başlıyor (mevcut kod böyle). Yönetim raporları takvim ayı ile mi, yoksa farklı bir kesim günüyle mi (ör. ayın 25'i) çalışıyor?
- **S9 — Yönetim toplantısında hangi 5 sayı?** §2.3'teki 15 KPI'dan Yönetim Özeti'nin en üstünde hangi 5'inin duracağını yönetim seçmeli. Önerim: Gelen, Çözülen, Geciken servis, PB dönem tamamlama, Süre kaydı eksik.

---

## 5. Varsayımlar

1. Rol ve sorumluluk dağılımı kod içindeki rol şablonlarından (P.cs:3921-3935) türetildi. Organizasyon şeması gelince §2.1 yeniden doğrulanacak.
2. SLA hedefinin hesaplanması (bekleme düşümü, PB ayrımı, `SlaDueAt`) Operasyon Merkezi/SLA modülünde yapılacak. Bu modül yalnız okuyup raporlayacak.
3. Durum kataloğu (M01-09), kimlik bazlı atama (M01-10) ve cihaz–iş emri bağı (M01-16/M03-09) ilgili modüllerde yapılacak. Bu belge onları kullanır, onlar gelene kadar metin eşleşmesiyle (açıkça "eşleştirilemedi" ayrımıyla) çalışır.
4. Gece yarısını aşan süre kaydı başlangıç gününe yazılmaya devam eder (mevcut davranış). Bölmek gerekirse ayrıca karar verilir.
5. SLA "takvim saati" ile ölçülür. Mesai ve tatil takvimi bazlı SLA ileriki sürüme bırakılmıştır (proje belgesi §5.10).
6. Pilot veri hacmi küçük-orta ölçek kabul edildi (yılda birkaç bin iş emri, onbinlerce süre kaydı). M12-15'teki performans hedefleri bu ölçeğin birkaç katına göre konuldu.
7. Kaynak satır sayıları (ör. 1.324 cihaz, 87 sözleşme) canlı SQL'de doğrulanmadı. Raporların kabul testleri ayrı test verisiyle yapılacak.
