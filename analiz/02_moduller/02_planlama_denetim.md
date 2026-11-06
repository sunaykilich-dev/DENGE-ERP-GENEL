# M02 — Planlama Takvimi ve Toplu Atama: Bağımsız Denetim Raporu

> **Tarih:** 21 Ekim 2026 · **Denetlenen belge:** `02_planlama_tasarim.md` · **Baz kod:** V1.20.1 (`kaynak/V1_20_1_orijinal/DengeERP.Api`, salt okunur; kaynak koda dokunulmadı)
> **Yöntem:** Her maddenin "mevcut durum" iddiası `Program.cs`, `OpsSuite.cs`, `wwwroot/app.js`, `wwwroot/ops120.js` ve `Database/*.sql` üzerinden satır satır kontrol edildi. Kullanıcı kararlarıyla (yalnızca teknik servis; c → b → a önceliği; Logo/Flowick kapsam dışı; 1 cihaz = 1 PB iş emri; tahmini süre gerçek süre değildir; süre kaydı yoksa "eksik"; artımlı geliştirme) çelişki arandı.
> **Öncelik ölçeği:** P1 = iş akışını bloke eden veya veri doğruluğunu bozan · P2 = operasyonel kalite · P3 = sonra.

---

## 1. Özet

| Karar | Adet | Maddeler |
|---|---|---|
| KABUL | 6 | M02-02, M02-11, M02-12, M02-14, M02-15, M02-04 (P3) |
| DEĞİŞTİR | 9 | M02-01, M02-03, M02-05, M02-06, M02-07, M02-08, M02-09, M02-10, M02-13 |
| RET | 0 | — |
| Eklenen | 4 | M02-D01 … M02-D04 |

**Genel değerlendirme:** Tasarım raporu kodu büyük ölçüde doğru okumuş. Satır referanslarının hemen hepsi doğru. Hata iddiaları (M02-10, M02-11, M02-13'teki İ/ı farkı, M02-12'deki sabit `null` alanlar, M02-14'teki anonim `app.js`) kodda doğrulandı. Zayıf noktalar şunlar:

1. **Gerekçesi kısmen yanlış iki madde var.** M02-08'deki "adres/irtibat teknisyen ekranında görünmüyor" iddiası yanlış: iş emri detayı bu alanları zaten gösteriyor (`app.js` 1625). M02-10'daki "bakım sayacı tekrar tetiklenir" riski de `IsCompleted=0` korumasıyla büyük ölçüde engelleniyor (`Program.cs` 3145).
2. **Mevcut çakışma kuralındaki en büyük sahte çakışma kaynağı gözden kaçmış.** "Aynı şef" kuralı (`app.js` 402), bir birimde tek şef olduğu için örtüşen hemen her iş çiftini çakışma sayıyor. Tasarım bu kuralı genişletmeyi (şef↔teknisyen çapraz) öneriyor. Önce bu kural düzeltilmeli (M02-D01).
3. **Bazı maddeler mevcut kurallarla çelişiyor veya fazla mühendislik içeriyor.** M02-01 ziyareti `RouteGroupNo` ile taşıyor, ama takvim kartı `RouteGroupNo` ile değil birim+müşteri+saha+şehir ile gruplanıyor. M02-06 öneri panelindeki "ziyarete ekle" işlemi, toplu planlamanın aynı lokasyon kuralıyla çelişiyor. M02-09 çakışmayı yalnızca Müdür'ün geçebileceği sert bir 409'a bağlıyor; bu, isim metniyle çalışan bugünkü veride şeflerin günlük işini bloke eder. M02-05 eğitim oturumlarından saatlik blok üretmeyi öneriyor, ama `TrainingSessions` tablosunda başlangıç saati yok.
4. **Kapsam:** Hiçbir madde satış, muhasebe, İK iş takibi veya Logo/Flowick entegrasyonu önermiyor. M02-05'teki "İK girer" ifadesi kapsam kararıyla uyumlu olacak şekilde Şef/Müdür'e çekildi.

**Önerilen ilk dilim (V1.21, şema değişikliği yok veya çok az):** M02-10 → M02-11 → M02-D02 → M02-D01 → M02-12. Ardından kullanıcı önceliğine (c) uygun olarak M02-02 + M02-01 (ziyaret taşıma) gelir.

---

## 2. Madde bazında değerlendirme

### M02-01 · YENİ · Ziyaret bazında yeniden planlama — **DEĞİŞTİR · P2**

**Doğrulama:**
- `bulk-plan`, planlı işleri reddediyor (`Program.cs` 682). Ziyaret modalında yalnızca "Aç" düğmesi var (`app.js` 474–482). Bu iki iddia doğru.
- 17 işlik ziyareti kaydırmak bugün gerçekten 17 ayrı "Planla" işlemi gerektiriyor.

**Sorunlar:**
- **Takvim kartı RouteGroupNo ile gruplanmıyor.** `calendarDayVisits` kartı birim + müşteri + saha adı + şehir anahtarıyla oluşturuyor (`app.js` 446–448). Bir kartta farklı `TPL-` grupları, grupsuz tekli planlar veya `RTE-` gibi elle yazılmış gruplar olabilir. "Karttan RouteGroupNo ile taşı" tanımı bu yüzden belirsiz.
- **RouteGroupNo serbest metin.** Tekli plan formundaki "Rota Grubu" alanı serbest metin. Bu alan mevcut `TPL-` numarasıyla önceden doldurulmuş geliyor (`app.js` 1868, `Program.cs` 749). Bir iş tek başına başka güne alındığında da aynı TPL numarası üzerinde kalıyor. Bu durumda `PUT /visits/{routeGroupNo}` daha önce ayrılmış işi de habersizce taşır.

**Düzeltilmiş tanım:**
- Uç: `PUT /api/workorders/bulk-replan` (veya `/api/planning/visits/move`). Gövdede `workOrderIds` (karttaki işler), yeni tarih/saat/süre, ekip, araç ve zorunlu neden (M02-02) bulunur.
- Sunucu şunları doğrular:
  - Tüm işlerin aktif planı var.
  - Tüm işler aynı birimde.
  - Hiçbiri `Tamamlandı/Kapatıldı/İptal` değil. Değilse 400 döner ve iş emri numaraları listelenir.
- Mevcut `TPL-` grubu korunur. Grupsuz işlere yeni bir `TPL-` verilir.
- Tekli planda "Rota Grubu" alanı salt okunur yapılır. Tek iş ziyaretten ayrılırsa sunucu grup numarasını temizler.
- Durum korunur (M02-10 kuralı).
- İşlem tek transaction'da ve `ReadBulkTargetsAsync` ile aynı UPDLOCK yaklaşımıyla çalışır.

**Kabul kriterleri:**
1. 17 işlik kart tek işlemle taşınır.
2. Tek başına ayrılmış bir iş, aynı grup numarasını taşısa bile seçilmediyse taşınmaz.
3. Her iş emrinin durum günlüğüne eski/yeni tarih ve neden yazılır.
4. Hata olursa hiçbir satır değişmez.

---

### M02-02 · YENİ · Erteleme nedeni, planı geri alma, plan geçmişi — **KABUL · P2**

**Doğrulama:**
- `WorkOrderPlans` tablosunda planı yapan kişi ve neden alanı yok (`DengeERP_Update.sql` 50–63).
- Geri alma ucu yok.
- `PUT /plan`, durum günlüğüne `OldStatus=NULL` yazıyor (`Program.cs` 757).

Bunlar yönetimin "işler neden gecikti" sorusunun planlama ayağı ve "Planlandı" durumundan geri dönüşün tek yolu. Şema değişikliği idempotent ve küçük.

**Not:** `PreviousStatus` alanı kaydedilirken M02-10 kuralı uygulanmalı (ilerlemiş durum geri çekilmez). Geri alma sonrası durum, `OpsHolds` aktifse `Beklemede` olarak kalmalı.

---

### M02-03 · VERİ · Personel/araç ana verisiyle kimlik bazlı atama — **DEĞİŞTİR · P1 (1. adım) / P2 (2. adım)**

**Doğrulama:**
- Şef rolünde `personnel.view` ve `users.manage` izni yok (`Program.cs` 3929).
- `state.users` ve `state.personnel` yalnızca bu izinlerle yükleniyor (`app.js` 145, 151). Bu yüzden şefin atama listesi pratikte yalnızca koda gömülü `personnelFallback` dizisinden geliyor (`app.js` 23–28, 1604).
- Yeni işe giren personel kod değişmeden atanamıyor. Bu, iş akışını bloke eden bir sorun.
- Teknisyen görünürlüğü `FullName` metin eşleşmesine bağlı (`Program.cs` 3400, 3500).

**Sorun:** Madde tek parça ve L eforunda. İçinde hem acil kısım (liste kaynağı) hem de büyük kısım (FK'ler, araç tablosu, isim eşleştirme göçü) var.

**Düzeltilmiş tanım — iki adım:**

**1. adım (P1, S/M):**
- `GET /api/planning/resources?unit=` eklenir. `workorders.plan` veya `workorders.assign` sahibine açıktır.
- Döndürdüğü alanlar: `Personnel` tablosundaki aktif kayıtlar (`PersonnelId`, `FullName`, `Title`, `UnitCode`, `ErpUserId`) ve rolü Şef/Teknisyen olan aktif `ErpUsers`. Birim yetkisi (`UnitAllowed`) uygulanır.
- `selectedPersonnel` bu uca bağlanır ve `personnelFallback` silinir.
- Atamalar şimdilik isim metniyle kalır.

**2. adım (P2, M/L, Kullanıcı/Personel modülüne bağlı):**
- `WorkOrderAssignments.PersonnelId` eklenir.
- Teknisyen görünürlüğü `ErpUserId ↔ PersonnelId` eşleşmesine geçirilir.
- Eski isimler eşleştirilir; eşleşmeyenler raporlanır, tahmin yapılmaz.
- `Vehicles` tablosu (normalize plaka, UNIQUE) bu adımda eklenir. Araç sayısı ve zimmet kararı (tasarım §4 soru 3) bekleniyor.

**Kabul kriterleri:**
- **1. adım:** Şef, `personnel.view` izni olmadan kendi biriminin aktif personelini görür. Pasif personel listede çıkmaz. `app.js` içinde gerçek kişi adı kalmaz.
- **2. adım:** Teknisyen, adı farklı yazılsa da `PersonnelId` ile işlerini görür. Aynı plaka iki kez tanımlanamaz.

---

### M02-04 · YENİ · Kaynak (ekip) görünümü — **KABUL · P3**

**Doğrulama:** Takvim lokasyon odaklı (`app.js` 483–506). Kişi filtresi tek kişi seçtiriyor (`app.js` 528). İddia doğru.

**Değerlendirme:** "Kim boş" sorusu gerçek bir ihtiyaç. Ancak madde:
- M02-03'ün 2. adımına,
- kısmen M02-05'e (müsaitlik),
- ve M02-D01'e (şefin kaynak sayılıp sayılmadığı) bağımlı.

Bağımlılıklar bitmeden yapılırsa isim metniyle yanlış "boş" gösterir. İlk sürümde araç satırları ve müsaitlik işaretleri olmadan, yalnızca personel × gün ve "plan dk" ile yapılabilir.

---

### M02-05 · YENİ · Personel müsaitlik blokları — **DEĞİŞTİR · P3**

**Doğrulama:**
- Müsaitlik tablosu yok; bu iddia doğru.
- `TrainingSessions` tablosunda yalnızca `SessionDate` ve `DurationHours` var, başlangıç saati yok (`ZZ_V113_TrainingDevelopment.sql` 52–61).
- `TrainingAttendance.Attended` kaydı oturum **sonrasında** girilen bir katılım kaydı. Planlı katılımcı listesi değil.

Bu yüzden "eğitim katılımcısı o saatte eğitimde görünür" kriteri mevcut veriyle karşılanamaz.

"İzindeki teknisyene iş planlanması en yaygın plan hatasıdır" iddiası da kaynakta veya proje belgesinde kanıtlanmamış bir varsayım.

**Düzeltilmiş tanım:**
- `PersonnelAvailability` tablosu eklenir. Kayıt **Şef (kendi birimi) / Müdür** tarafından girilir. Kapsam yalnızca teknik servis olduğu için İK girişi bu fazda yok.
- Bu kayıt bordro değildir.
- Bloğa denk gelen atama ilk sürümde **uyarı** üretir. Gerekçe ile kaydedilebilir (M02-09 düzeltilmiş akışı).
- Eğitim entegrasyonu ayrı bir adımdır. Yalnızca katılımcısı önceden girilmiş oturumlar **gün bazlı** blok olarak okunur. Saatlik blok için eğitim modülüne başlangıç saati eklenmesi gerekir.

**Kabul kriterleri:**
1. İzin girilen personele o güne plan yapılınca uyarı ve gerekçe istenir.
2. Blok silinince uyarı kalkar.
3. Bloklar kişi-saat raporuna girmez.

---

### M02-06 · YENİ · Şehir/bölge bazlı havuz ve aynı bölge önerisi — **DEĞİŞTİR · P2**

**Doğrulama:**
- `WorkOrders` tablosunda şehir alanı yok. Şehir yalnızca `WorkOrderPlans.SiteCity` alanında var.
- Havuz müşteri + lokasyon + birim bazında gruplanıyor (`app.js` 371–384).

Proje belgesinin §14'ündeki öncelik 2 maddesiyle ("aynı bölgeye tekrar ziyaret") örtüşüyor.

**Sorunlar:**
- **Kabul (4) mevcut kuralla çelişiyor.** "Öneriden eklenen iş, ziyaretin tarihini, saatini ve ekibini alır" deniyor. Oysa toplu planlama aynı lokasyonu zorunlu tutuyor (`Program.cs` 677–681). Farklı lokasyondaki işe aynı saat ve ekip verilirse `isSameBulkVisit` kuralı bu işi aynı ziyaret saymaz (`app.js` 386–391) ve sahte çakışma çıkar.
- **Alan sahipliği çakışıyor.** `WorkOrders.City/District` alanının açılış formuna eklenmesi İş Emri modülünün (01) konusu. İki modülde ayrı ayrı tasarlanmamalı.

**Düzeltilmiş tanım:**
- Şehir/ilçe alanı İş Emri modülünde tanımlanır.
- Planlama bu alanı kullanır:
  - Havuz "Lokasyon / Şehir-İlçe" gruplaması arasında geçiş yapar.
  - Şehri boş olan işler "Şehir girilmemiş" grubunda toplanır.
- Ziyaret planlarken yan panel iki şeyi listeler: aynı ilçedeki plansız işler ve ±3 gün içindeki planlı ziyaretler.
- Panelden seçilen iş, **ayrı bir tekli plan** olarak kaydedilir: aynı gün ve ekip, başlangıç saati önceki ziyaretin bitişinden sonra olacak şekilde. Toplu ziyarete eklenmez.
- Eski kayıtların doldurulması tek seferlik bir scriptle yapılır. Yalnızca dolu `SiteCity/SiteDistrict` değerleri kullanılır.

---

### M02-07 · YENİ · Plan uyumu ve rota verimliliği raporu — **DEĞİŞTİR · P3**

**Doğrulama:** Kaynakta plan uyum metriği yok. Proje belgesinin §1'indeki "Şef hangi personele ne zaman atadı" ve "işler neden gecikti" soruları gerçek ihtiyaçlar.

**Sorunlar:**
- "Plan doluluğu" metriğinin paydası "müsait dakika". Bu değer çalışma saatleri tanımına (tasarım §4 soru 6, cevapsız) ve M02-05'e bağlı. Bugün hesaplanamaz.
- "Erteleme nedeni" kırılımı M02-02'den önceki kayıtlar için yok.

**Düzeltilmiş tanım — ilk sürüm şunları içerir:**
- plan bekleyen yaşı,
- plana uyum (ilk süre kaydının günü plan günüyle aynı mı; süre kaydı yoksa "süre kaydı eksik" ayrı satırda gösterilir ve paydaya girmez),
- erteleme sayısı ve nedeni (M02-02 sonrası kayıtlar için; öncekiler "neden kaydı yok"),
- ziyaret başına iş,
- 30 günde tekrar ziyaret.

"Plan doluluğu", çalışma saatleri ve müsaitlik tanımlanana kadar rapora konmaz.

**Kabul kriterleri:**
- Excel ile web toplamları eşleşir.
- Servis ve bakım ayrı raporlanır.
- Tahmini süre hiçbir sütunda gerçek süre olarak geçmez.

---

### M02-08 · EKSİK · Teknisyen "Bugünkü ziyaretlerim" ve ziyaret föyü — **DEĞİŞTİR · P2**

**Doğrulama:**
- `ops120.js` 7–8 yalnızca iş emri no, müşteri, şehir ve durumu gösteriyor. Sıralama ve gruplama yok; bu doğru.
- **Gerekçe kısmen yanlış.** İş emri detayı saha adresi, yetkili, telefon ve ulaşım notunu `workorders.view` sahibi herkese zaten gösteriyor (`app.js` 1625). Eksik olan şunlar:
  - plan tarihi/saatine göre sıralı ve ziyaret bazlı gruplu bir liste,
  - tıklanabilir `tel:` bağlantısı,
  - harita bağlantısı.

**Düzeltilmiş tanım:**
- Mobil iş listesi bugün/yarın planlı işleri saat sırasıyla ve ziyaret bazında gruplu gösterir.
- Kartta şunlar bulunur: adres, ilçe/şehir, yetkili, `tel:` bağlantısı, ulaşım notu, adres metniyle harita araması, cihaz/seri listesi.
- Planı olmayan açık işler ayrı bölümde listelenir.
- Yazdırılabilir föy P3'tür ve fiyat/maliyet alanı içermez.

**Kabul kriterleri:**
1. Teknisyen yalnızca kendine atanmış işleri saat sırasıyla görür.
2. Telefona dokununca arama başlar.
3. Her iş emri ayrı açılır.

---

### M02-09 · HATA · Çakışma kontrolünün sunucuya taşınması — **DEĞİŞTİR · P2**

**Doğrulama:**
- Kontrol yalnızca istemcide yapılıyor (`app.js` 392–406).
- Hesap, filtrelenmiş satırlar üzerinde çalışıyor (`app.js` 513). Birim filtresi seçilince birimler arası çakışma kayboluyor.
- Saati boş plan 09:00 / 60 dk olarak varsayılıyor (`app.js` 357–361).
- Sunucuda hiç kontrol yok (`Program.cs` 649–761).

Bu iddiaların hepsi doğru.

**Sorunlar:**
- **Sert 409 ve Müdür'e özel `planning.override` operasyonu bloke eder.** Atamalar isim metniyle tutuluyor ve şef kuralı bugün sahte çakışma üretiyor (bkz. M02-D01). Bu koşullarda sert red, şefin günlük planını Müdür onayına bağlar.
- **Şef↔teknisyen çapraz kontrolü yanlış kuralı genişletir.** Şefin sahaya gidip gitmediği bilinmiyor. Organizasyon şeması bekleniyor, bu bir varsayım.
- **Saati boş plan kuralının etkisi küçük.** Arayüz saati her zaman 09:00 varsayılanıyla gönderiyor (`app.js` 1868). Saati boş plan çoğunlukla eski veride var.

**Düzeltilmiş tanım:**
- `POST /api/planning/check` eklenir. `plan`, `bulk-plan` ve ziyaret taşıma uçları da aynı kontrolü kayıttan önce çalıştırır.
- Kurallar:
  - (a) Tüm birimler ve iş türleri dahil edilir.
  - (b) Kişi çakışması yalnızca **sahaya giden** kişiler arasında aranır: teknisyenler ve "sahaya gidiyor" işaretli şef (M02-D01).
  - (c) Plaka normalize edilerek karşılaştırılır (boşluk silinir, tr-TR büyük harf).
  - (d) Aynı `TPL-` ziyaretinin işleri birbirinin çakışması sayılmaz.
  - (e) Saati boş plan "saat belirsiz" uyarısı verir.
  - (f) Müsaitlik blokları M02-05 sonrası dahil edilir.
- Çakışma varsa API 409 ve çakışan işlerin listesini döner. İstemci, gerekçe girilip `confirmConflicts=true` gönderilince kaydeder. Gerekçe durum günlüğüne yazılır.
- Gerekçeyle geçme yetkisi varsayılan olarak `workorders.plan` sahibindedir. Sert engel istenirse `planning.override` izni sonra eklenir (kullanıcı kararı, tasarım §4 soru 1).
- Eş zamanlılık için plan tarihi bazında `sp_getapplock` kullanılır.

**Kabul kriterleri:**
1. Birimler arası çakışma API'de 409 döner.
2. Takvimdeki filtre değişse de çakışma işaretli kalır.
3. Aynı TPL ziyaretinin işleri kendi aralarında çakışma vermez.
4. Gerekçeli kayıt günlükte görünür.
5. Eş zamanlı iki çakışan istekten ikincisi 409 alır.

---

### M02-10 · HATA · KRİTİK (veri bütünlüğü) · Planlama kapalı/ilerlemiş işin durumunu geri çekiyor — **DEĞİŞTİR · P1**

**Doğrulama — doğru olan iddialar:**
- `PUT /plan` durumu koşulsuz `Planlandı` yapıyor ve durum kontrolü yok (`Program.cs` 754).
- İş tablosundaki "Planla" düğmesi her durumda görünüyor (`app.js` 328).
- `bulk-plan`, `Sahada/Atölyede/Beklemede` durumundaki plansız işi `Planlandı` yapıyor (`Program.cs` 712).
- `/assignments` ucunda kapalı iş kontrolü yok (`Program.cs` 545–570).
- Durum ekranındaki PB koruması (`Program.cs` 502–503) bu yoldan atlatılıyor.

**Denetçinin ek bulguları:**
- İş emri detayındaki **"Planı Aç / Düzenle"** düğmesi de durumdan bağımsız görünüyor (`app.js` 1625).
- Yeniden "Planlandı" olan PB iş emrinin durum listesinden `Kapatıldı` seçeneği filtreleniyor (`app.js` 1626). İş arayüzden tekrar kapatılamaz hale gelebilir ve açık iş sayısını kalıcı şişirir.
- Aktif bekleme kaydı (`OpsHolds`) olan bir iş planlanınca durum `Planlandı` oluyor, ama bekleme kaydı açık kalıyor. Sonraki "bekleme kaldır" işlemi `AND Status=N'Beklemede'` koşulu yüzünden durumu geri yüklemiyor (`OpsSuite.cs` 156). "Beklemede" uyarısı da açık kalıyor.

**Düzeltilecek gerekçe:** "Bakım sayacı tekrar tetiklenir" riski büyük ölçüde yok. `CompleteMaintenanceFromWorkOrderAsync` yalnızca `IsCompleted=0` plan üzerinde çalışıyor (`Program.cs` 3145). Asıl zarar açık iş, SLA ve KPI sayılarının bozulması ve PB işinin kilitlenmesi.

**Düzeltilmiş kabul kriterleri:**
1. `Tamamlandı/Kapatıldı/İptal` durumundaki işe `PUT /plan` ve `PUT /assignments` 400 döner; veritabanı değişmez.
2. Tablodaki "Planla" ve detaydaki "Planı Aç / Düzenle" düğmeleri bu durumlarda gizlenir.
3. Planlama durumu yalnızca `Müşteri Talebi` ve `Planlandı` için `Planlandı` yapar. `Sahada/Atölyede/Beklemede` durumunda yalnızca plan güncellenir, durum korunur. Bu kural `bulk-plan` için de geçerlidir.
4. Durum günlüğüne gerçek eski durum yazılır.
5. Tespit sorgusu pilot veride çalıştırılır. Etkilenen kayıtlar listelenir, otomatik düzeltme yapılmaz. Sorgu şu kayıtları bulur:
   - `ClosedAt` dolu ama durumu `Kapatıldı` olmayan kayıtlar,
   - durum günlüğünde `Kapatıldı`dan sonra `OldStatus` NULL olan bir `Planlandı` satırı bulunan kayıtlar.

---

### M02-11 · HATA · Tekli planlamada atama + plan atomik değil; doğrulama eksik — **KABUL · P1**

**Doğrulama:**
- `openPlan` önce `/assignments`, sonra `/plan` çağırıyor (`app.js` 1873–1874). Atama ayrı transaction'da commit edildiği için plan hatasında yarım kayıt kalır.
- `PlanRequest` üzerinde tarih ve süre doğrulaması yok (`Program.cs` 722–752). JSON'da tarih gönderilmezse `default(DateOnly)` = 0001-01-01 kaydedilir.
- Plan izni olup atama izni olmayan özel profil, ilk çağrıda 403 aldığı için planı kaydedemiyor. Rol şablonlarında iki izin birlikte geliyor, ama izinler kişi bazında değiştirilebiliyor.

Efor küçük; M02-10 ile aynı dilimde yapılmalı.

---

### M02-12 · EKSİK · Saha önerisinin önceki planlardan beslenmesi — **KABUL · P2**

**Doğrulama:**
- `site-suggestion` şehir, ilçe, telefon ve ulaşım notu alanlarını sabit `null` döndürüyor (`Program.cs` 643–645).
- İstemci yalnızca boş alanları dolduruyor (`app.js` 1810–1813); bu doğru davranış korunmalı.
- Aynı iş emrinin yeniden planlanmasında form mevcut plandan zaten dolu geliyor (`app.js` 1800). Kazanç asıl olarak **yeni** iş emirlerinde (sonraki bakım dönemi, aynı AVM'ye yeni arıza).

**Not:** Eşleşme anahtarı M02-13'teki aynı normalizasyonu kullanmalı.

---

### M02-13 · VERİ · Toplu planlama lokasyon eşleşmesinin güçlendirilmesi — **DEĞİŞTİR · P2**

**Doğrulama:**
- İstemci `toLocaleLowerCase('tr-TR')` kullanıyor (`app.js` 373), sunucu `Trim` + `OrdinalIgnoreCase` (`Program.cs` 677–681).
- Örnek: "İSTANBUL" ile "istanbul" istemcide aynı grupta görünür, sunucuda reddedilir. İ/ı uyumsuzluğu gerçek bir hata.
- İç boşluklar her iki tarafta da normalize edilmiyor.

**Sorun:** (b) maddesi ("lokasyonu toplu eşitle") için bugün iş emrinin müşteri ve lokasyonunu düzenleyen bir uç yok (`PUT /api/workorders/{id}` bulunmuyor). Bu iş S eforunda değil. Ayrıca İş Emri modülü ve müşteri/lokasyon ana verisi konusu.

**Düzeltilmiş tanım:**
- (a) Sunucu ve istemcide aynı normalizasyon kullanılır: `Trim`, çoklu boşluğu teke indirme, `tr-TR` küçük harf. Sunucuda `CultureInfo("tr-TR")` ile yapılır. Gerekirse `WorkOrders.LocationKey` kalıcı hesaplanmış kolonu eklenir.
- (b) Toplu lokasyon düzeltme İş Emri modülüne devredilir.

**Kabul kriterleri:**
1. "Akyaka  AVM" ile "AKYAKA AVM" aynı grupta toplanır.
2. İ/ı içeren müşteri adıyla istemcide aynı grupta görünen işler sunucuda reddedilmez.

---

### M02-14 · GÜVENLİK · Gerçek personel adlarının anonim statik dosyada yayınlanması — **KABUL · P2**

**Doğrulama:** `app.js` 23–28 gerçek ad-soyad ve birim eşlemesi içeriyor. `UseStaticFiles` (`Program.cs` 15–16) bu dosyayı oturum açmadan sunuyor. İddia doğru.

**Değerlendirme:** İletişim bilgisi içermediği için KRİTİK değil; tasarımcının yaklaşımı doğru. M02-03'ün 1. adımıyla aynı değişiklik olduğu için P2 olarak birlikte yapılmalı.

---

### M02-15 · GÜVENLİK · Saha irtibat bilgisinin geniş dağıtımı — **KABUL · P3**

**Doğrulama:** `GET /api/workorders`, `LoadWorkOrdersAsync` içindeki tüm saha alanlarını `workorders.view` sahibi herkese döndürüyor (`Program.cs` 359–368, 3453–3454). Depo, Muhasebe ve Genel Koordinatör rolleri bu izne sahip (`Program.cs` 3927–3932).

**Değerlendirme:** KVKK açısından geçerli. Kullanıcı önceliğinde (a) grubunda; veri kaybına yol açmadığı için P3. Hangi rolün iş gereği bu alanları göreceği (ör. Depo sevkiyat için adres isteyebilir) kullanıcıya sorulmalı (tasarım §4 soru 8).

---

## 3. Tasarımcının kaçırdığı maddeler

### M02-D01 · HATA · "Aynı şef" çakışma kuralı sahte çakışma üretiyor — **P2 · S**

- **Mevcut durum:** `planningConflictIds`, saatleri örtüşen iki işte şef aynıysa bunu çakışma sayıyor (`app.js` 402). Gömülü listede her birimin tek şefi var. Ertuğrul Çakır hem Haberleşme hem POC şefi, Serkan Doğan hem Mobilite hem Araç Takip şefi (`app.js` 24–28). Sonuç olarak bir birimde saatleri örtüşen ve şefi atanmış hemen her iş çifti "çakışmalı" görünüyor. Bu da "Çakışmalı iş" KPI'ını (`app.js` 522) şişiriyor.
- **Neden gerekli:** Sahte çakışma gerçek çakışmayı gizler ve uyarının ciddiye alınmasını engeller. M02-09 bu kuralı sunucuya taşırsa ve sert 409 uygularsa planlama bloke olur.
- **Öneri:**
  - Şef ataması varsayılan olarak "sorumlu" kabul edilir ve kişi çakışmasına girmez.
  - Plan formuna "Şef sahaya gidiyor" seçeneği eklenir. Seçilirse şef de kaynak sayılır.
  - İlk adımda saklama yöntemi `WorkOrderAssignments` içinde ayrı rol veya bir bayrak olabilir.
- **Kabul kriterleri:**
  1. Aynı şefin, saatleri örtüşen ve farklı teknisyenlere atanmış iki işi çakışma vermez.
  2. Şef "sahaya gidiyor" işaretliyse çakışma verir.
  3. KPI yalnızca gerçek çakışmaları sayar.
- **Roller:** Şef, Müdür. Şefin sahaya çıkıp çıkmadığı organizasyon şeması gelince doğrulanacak bir varsayım.

### M02-D02 · VERİ · Aktif plan tekilliği garanti edilmiyor — **P2 · S**

- **Mevcut durum:**
  - `IX_WorkOrderPlans_Active` benzersiz değil (`DengeERP_Update.sql` 254–255).
  - `PUT /plan`, iş emri satırını kilitlemeden "pasifleştir + ekle" yapıyor (`Program.cs` 730–752).
  - Aynı işe eş zamanlı iki kayıt gelirse iki `IsActive=1` satırı oluşabilir.
  - `LoadWorkOrdersAsync` `TOP 1 ... ORDER BY WorkOrderPlanId DESC` ile bunu gizliyor (`Program.cs` 3460).
- **Neden gerekli:** M02-02 (geri alma, plan geçmişi) ve M02-07 (erteleme sayısı = plan satırı sayısı) birden fazla aktif satır olduğunda yanlış sonuç verir.
- **Öneri:**
  1. Önce tespit sorgusu çalıştırılır: `SELECT WorkOrderId FROM dbo.WorkOrderPlans WHERE IsActive=1 GROUP BY WorkOrderId HAVING COUNT(*)>1`.
  2. Bulunan kayıtlar raporlanır; otomatik düzeltme yapılmaz.
  3. Ardından benzersiz filtreli indeks eklenir: `UX_WorkOrderPlans_OneActive ON (WorkOrderId) WHERE IsActive=1`. Script idempotent olur.
  4. `PUT /plan` iş emri satırını `UPDLOCK` ile okur.
- **Kabul kriterleri:**
  1. Aynı işe eş zamanlı iki plan isteğinden sonra en fazla bir aktif satır bulunur.
  2. Mevcut çift kayıtlar listelenir.

### M02-D03 · EKSİK · Takvim tüm iş emri tablosunu her yüklemede çekiyor — **P3 · M**

- **Mevcut durum:**
  - `GET /api/workorders` tarih aralığı almıyor.
  - Her satır için 3 alt sorgu (`STRING_AGG` ile atama ve seri) ve `OUTER APPLY` ile aktif plan okunuyor (`Program.cs` 3446–3462).
  - Takvim, havuz ve çakışma hesabının hepsi istemcide bu tam liste üzerinde çalışıyor.
- **Neden gerekli:** 1 cihaz = 1 PB iş emri kararı ile kütükteki 1.324 cihazın yıllık bakım frekansı birleşince iş emri sayısı her yıl binlerce artar. Her kullanıcı ve her yenileme tam tabloyu çeker. Bu, pilotun üretime geçişinde performans riski.
- **Öneri:** Mevcut uç korunur ve yeni bir uç eklenir: `GET /api/planning/calendar?from=&to=&unit=`. Yalnızca seçilen aralıktaki planlı işleri ve plansız açık işleri döndürür; çakışma bilgisi sunucuda hesaplanır (M02-09).
- **Kabul kriterleri:**
  1. Hafta görünümü yalnızca o haftanın planlı işlerini ve havuzu yükler.
  2. 10.000 iş emri içeren test verisiyle takvim açılışı kabul edilebilir sürede kalır. Eşik İT ile belirlenir.

### M02-D04 · EKSİK · Kapatılan iş takvimden düşüyor; geçmiş günler eksik görünüyor — **P3 · S**

- **Mevcut durum:** `planningFilteredRows`, `isOpen` filtresiyle `Kapatıldı` ve `İptal` işleri takvimden çıkarıyor (`app.js` 131, 364).
- **Sonuçlar:**
  - Kapatılan iş planlandığı günün kartından kayboluyor.
  - "Bugün planlı" ve "Bu hafta" KPI'ları gün içinde düşüyor.
  - Şef geçen haftanın gerçekleşen ziyaretlerini takvimde göremiyor.
  - Tasarımın M02-10 maddesindeki "takvimde kapalı iş salt okunur açılır" kriteri de bugün karşılanamaz, çünkü kapalı iş takvimde hiç görünmüyor.
- **Öneri:**
  - Takvimde planlı ama kapanmış işler soluk ve salt okunur kart olarak gösterilir. Çakışma hesabına girmez.
  - Havuz ve çakışma yalnızca açık işlerle hesaplanır.
  - KPI'lar "planlı" ve "tamamlanan" olarak ayrılır.
- **Kabul kriterleri:**
  1. Kapatılan iş plan gününde soluk kartla görünür ve "Planla" düğmesi göstermez.
  2. Çakışma sayısına dahil edilmez.

---

## 4. Önerilen sıralama (denetçi görüşü)

Kullanıcının c → b → a önceliğine uyuldu. Veri bütünlüğünü bozan maddeler önce gelir.

| Dilim | Maddeler | Gerekçe |
|---|---|---|
| V1.21 (hemen) | **M02-10 (KRİTİK)**, M02-11, M02-D02, M02-03 1. adım + M02-14, M02-D01, M02-12 | Veri bütünlüğü, gömülü listenin kaldırılması ve sahte çakışmanın düzeltilmesi. Şema değişikliği yalnızca filtreli indeks. |
| V1.22 (yeni özellik) | M02-02, M02-01 (düzeltilmiş), M02-08 (düzeltilmiş), M02-13 (a) | Ziyaret taşıma, erteleme nedeni ve teknisyen ziyaret listesi. |
| V1.23 | M02-09 (uyarı + gerekçe modeli), M02-06 (düzeltilmiş, İş Emri modülüyle birlikte) | Sunucu çakışması ve bölge önerisi. |
| V1.24+ | M02-03 2. adım, M02-05, M02-04, M02-07, M02-D03, M02-D04, M02-15 | Kimlik bazlı kaynak modeli, müsaitlik, ekip görünümü, rapor ve performans. |

## 5. Kullanıcıya iletilecek ek sorular (tasarımın §4 listesine ek)

1. Birim şefleri sahaya bizzat çıkıyor mu, yoksa atama yalnızca sorumluluk mu ifade ediyor? Cevap M02-D01 ve M02-09'u belirler.
2. Çakışma durumunda sistem kaydı **engellesin mi**, yoksa **gerekçe isteyip izin mi versin**? Denetçi önerisi: başlangıçta gerekçeli izin.
