# M12 — Raporlama ve Yönetsel KPI: Bağımsız Denetim

> **Denetlenen belge:** `analiz/02_moduller/12_raporlama_tasarim.md` (M12-01 … M12-16)
> **Kaynak:** V1.20.1 (salt okunur). `P.cs` = `Program.cs`, `Ops.cs` = `OpsSuite.cs`, `app.js` = `wwwroot/app.js`.
> **Tarih:** 21.10.2026
> **Yöntem:** Her maddenin "mevcut durum" iddiası kaynak kodda satır satır kontrol edildi. Ayrıca diğer modül tasarımlarıyla (M01, M05, M09, M10, M11, M14) çakışmalar arandı.
> **Uygulanan kullanıcı kararları:** yalnız teknik servis; öncelik (c) → (b) → (a); Logo/Flowick kapsam dışı; roller varsayım; seri no metin; fiyat/maliyet API'de gizli; süre kaydı yoksa "eksik"; tahmini süre gerçek süre yerine kullanılmaz; teknoloji yığını korunur, artımlı geliştirme.

---

## 1. Özet

| Madde | Karar | Öncelik | Kısa gerekçe |
|---|---|---|---|
| M12-01 Tek rapor motoru | DEĞİŞTİR | P2 | Gerekli ama önce "bugünkü KPI'larla birebir eşlik" adımı; parametre doğrulaması eklenmeli |
| M12-02 Native PivotTable | DEĞİŞTİR | P2 | Kullanıcının açık talebi; M12-01'i beklememeli, M12-10 ile tek kütüphane geçişi |
| M12-03 SLA/gecikme raporu | DEĞİŞTİR | P2 | **M10-07 ile mükerrer**; alan adları ve bekleme kuralı M10-01/M10-03 ile çelişiyor |
| M12-04 Tekrar arıza | DEĞİŞTİR | P2 | **M10-04 ile çelişen ikinci tanım**; rapor M10-04 işaretini okumalı |
| M12-05 Bakım tamamlama | KABUL | P2 | İddialar doğru; `MaintenancePlans.CompletedAt` zaten var |
| M12-06 Dönem karşılaştırma/trend | DEĞİŞTİR | P3 | Kapsam daraltılmalı; yeniden açılan işlerde geçmiş sayı değişir |
| M12-07 Parça kullanımı | RET | P3 | **M11-07 ile mükerrer** ve M11-07 daha doğru (net çıkış) |
| M12-08 Eksik kırılımlar | DEĞİŞTİR | P2 | Müşteri kırılımı M14-12 ile çakışıyor; ekranda personel tablosu zaten var |
| M12-09 Hesaplama hataları | DEĞİŞTİR | P1 | Hatalar gerçek; (a)(c)(d) hemen yapılabilir, (b) M12-12'ye bağlı |
| M12-10 Excel hücre tipleri | KABUL | P1 | Doğrulandı; "seri no metin" kararını çıktı dosyasında ihlal ediyor |
| M12-11 Durum grupları | DEĞİŞTİR | P1 | Doğru, ancak tasarımın kataloğu **POC birimi durumlarını unutuyor** |
| M12-12 Zaman damgaları | DEĞİŞTİR | P1 | **M01-09 ve M10-01 ile aynı alanı üçüncü kez ekliyor**; "ilk/son çözüm" çelişkisi |
| M12-13 Lokasyon ayrımı | DEĞİŞTİR | P1 | PB formu `Location` **ve** `Description` alanlarını eziyor: **KRİTİK veri kaybı** (M14-07 ile tek iş) |
| M12-14 Veri Kalitesi sayfası | DEĞİŞTİR | P2 | Müşteri adı normalizasyonu M14'ün işi; burada yalnız M14 fonksiyonu kullanılmalı |
| M12-15 SQL'de süzme | DEĞİŞTİR | P2 | Doğru; tasarım `worklogs` çağrısı yapan 3 yeri atlamış |
| M12-16 Kişi bazlı veri izni | DEĞİŞTİR | P2 | Doğru; ayrı log tablosu yerine ortak denetim kaydı (A1-16/M13) |

**Eklenen maddeler:** M12-D01 (rapor test veri seti ve KPI regresyon testi), M12-D02 (Atölye kategorisi ve iptal atölye işinin açık sayılması), M12-D03 (yeniden açılan iş göstergesi).

**KRİTİK işareti:** Tasarım "bu modülde KRİTİK açık yok" diyor. Buna **katılmıyorum**. PB bakım formu kaydı (`P.cs:2519`) iş emrinin `Location` alanını cihaz bölgesiyle, `Description` alanını yapılan işle geri dönüşsüz eziyor. Bu kalıcı **veri kaybıdır**. M14-07 bunu zaten KRİTİK işaretlemiş; M12-13 bu düzeltmeyi M14-07'ye bırakmalı ve öncelik sırasından bağımsız ilk sürüme alınmalı.

---

## 2. Doğrulanan mevcut durum (kanıt özeti)

- `GET /api/reports/worklogs` (P.cs:2181-2189): `LoadTimeLogsAsync` tablonun tamamını okur (P.cs:3424-3439), yalnız kullanıcı kapsamıyla süzer. **Tarih sınırı yok.** `WorkNote` ve `LocationNote` dahil döner. Doğru.
- Ön yüz bu ucu **beş yerde** çağırıyor: app.js:142 (`loadCore`), 1449, 1654, 1661, 1985. Tasarım yalnız 142 ve 1985'i yazmış.
- Excel (P.cs:3641-3737) ve ekran (app.js:1097-1186) ayrı kodla hesaplanıyor. Bugün tanımlar büyük ölçüde **eşit** (Tamamlanan = Tamamlandı/Kapatıldı; tarih esası mantığı aynı). Yani "farklı sayı" bugün kanıtlanmış bir hata değil, **bakım riski**dir. M12-01 bu yüzden P1 değil P2.
- `MakeSheet` (P.cs:3760-3762): yalnız rakamdan oluşan, `0` ile başlamayan ve 18 karakterden kısa değer sayı hücresine dönüşüyor. 16-17 haneli seri no'lar Excel'in 15 anlamlı hane sınırı yüzünden bozuluyor. Tarihler `ToString("dd.MM.yyyy HH:mm")` ile metin (P.cs:3678, 3703). Doğru.
- `ClosedAt` yalnız `Kapatıldı`'da yazılıyor (P.cs:527, 2761), yeniden açılışta temizlenmiyor. PB formu `@Done=1` ise yazıyor, değilse `NULL` yapıyor (P.cs:2520). Doğru.
- `IsClosingStatus` `Çözüldü`'yü içeriyor (P.cs:2808); `reportIsOpen` (app.js:128) ve `Ops.Open` (Ops.cs:8) açık sayıyor; ana panel `isOpen` `Tamamlandı`'yı açık sayıyor (app.js:131). Doğru. **Ek bulgu:** `Çözüldü` ön yüzdeki durum listelerinde yok (app.js:30-31); yalnız API ile oluşabilir. Asıl görünür çelişki `Tamamlandı`'dır.
- **Ek bulgu:** POC birimi ayrı durum listesi kullanıyor: `İnceleniyor`, `Telefonla Destek`, `Uzaktan Müdahale`, `Yerinde Müdahale` (app.js:31, 1614). Tasarımın §2.2-2 kataloğunda bunlar yok.
- **Ek bulgu:** Durum değiştiren her uç `WorkOrderStatusLogs`'a yazmıyor: atölye PUT (P.cs:2757-2772) ve bekleme/serbest bırakma (Ops.cs:140, 156) log yazmıyor. M12-12'nin geçmiş doldurma scripti bu yüzden atölye çözümlerini kaçırır.
- **Ek bulgu:** Atölye kaydı `İptal` yapılınca iş emri `Atölyede` olur (P.cs:2754, `_ => "Atölyede"`; app.js:673 listesinde `İptal` var). İptal edilmiş atölye işleri raporda **açık** ve zamanla **geciken** görünür.
- **Ek bulgu:** Atölye kaydında `completionDate` alanı var (app.js:739). PB cihaz kalemlerinde `MaintenanceDeviceItems.CompletedAt` var (P.cs:2517). Bunlar geçmiş doldurma için `ClosedAt`'tan daha iyi kaynaklardır.
- `MaintenancePlans.CompletedAt` yalnız tüm cihaz kalemleri `Tamamlandı` olunca yazılıyor (P.cs:2539-2543). Bakım tamamlama raporu bunu doğrudan kullanabilir.
- `ServicePartMovements` iş emrine bağlı `Giriş` hareketini de kabul ediyor (Ops.cs:188-212). Finans sorgusu bunu iade gibi düşüyor (Ops.cs:225). Yalnız `Çıkış` saymak yanlış olur.
- Rol şablonları (P.cs:3921-3935): `reports.view` ve `reports.export` Muhasebe ve Genel Koordinatör'de var; Şef'te yalnız `reports.view`. Doğru.
- Test projesi yok; yalnız `DengeERP.Api.csproj` var. Tasarımdaki birçok "otomatik testle doğrulanır" kriteri bugün çalıştırılamaz.

---

## 3. Madde madde değerlendirme

### M12-01 · Tek KPI/rapor motoru — **DEĞİŞTİR · P2**
- **Doğrulama:** İki kod yolu iddiası doğru (app.js:1097-1186; P.cs:3641-3709; Ops.cs:102-105). Ancak bugün tanımlar eşit; somut sayı farkı gösterilmemiş.
- **Gereklilik:** Gerekli. M12-15 (sunucuda süzme) ve M12-16 (kişi verisini gizleme) sunucu tarafı hesap olmadan yapılamaz: istemciye ham süre kaydı gittiği sürece gizleme mümkün değildir.
- **Sorun:** L efor ve yeni KPI'larla aynı adımda yapılırsa regresyon riski yüksek. §2.5'teki doğrulamalar (bilinmeyen `dateField/kind/unit/status` → 400, 24 ay sınırı) hiçbir maddeye bağlanmamış.
- **Düzeltilmiş hali:** Bkz. JSON `revised`. İki aşama: (1) bugünkü ekran KPI'larının sunucuya birebir taşınması (eşlik testi), (2) yeni KPI'lar. Parametre doğrulaması bu maddeye eklenir. D01 test veri setine bağlanır.

### M12-02 · Native PivotTable — **DEĞİŞTİR · P2**
- **Doğrulama:** Doğru. P.cs:3644 ve 3670'te "PivotTable değildir" notu var. Proje belgesi §7.2 ve §14-Öncelik 3 açık talebi doğruluyor.
- **Sorun:** M12-01'e (L) bağlanınca kullanıcının açık talebi gereksiz yere gecikir. Mevcut `BuildWorkOrderXlsx` verisiyle de ham veri sayfası ve pivot üretilebilir. M12-10 elle yazılan OpenXML'de bir kez, kütüphaneye geçişte bir kez daha yapılırsa çift iş olur.
- **Düzeltilmiş hali:** S4 kararı (ClosedXML, MIT) önce alınır. Kütüphane geçişi tüm kitabı kapsar ve M12-10 bu geçişte yapılır. M12-01'e bağımlılık kaldırılır, sonra M12-01 aynı yazıcıyı kullanır.

### M12-03 · SLA ve gecikme raporu — **DEĞİŞTİR · P2**
- **Doğrulama:** Ops.cs:87 ve 102'deki `CreatedAt + SLA` hesabı, PB dahil olması ve beklemenin düşülmemesi doğru. `OpsSlaTargets` Kritik = 12 saat (ZZ_V120_Operations.sql:5) doğru.
- **Çakışma:** M10-07 "SLA, bekleme ve tekrar arıza raporu (ekran + Excel)" maddesiyle **aynı iş**. Ayrıca alan adları çelişiyor: tasarım `SlaDueAt` diyor, M10-01 `ResolveDueAt/ResolvedAt/PausedMinutes/SlaResult/DelayReason` tanımlıyor.
- **Kural çelişkisi:** Kabul kriteri (2) her 3 saatlik beklemeyi düşüyor. M10-03'e göre yalnız `PausesSla=1` olan (müşteri kaynaklı) beklemeler düşülür. M10-02 mesai takvimi gelirse 12 saat de takvim saati olmaktan çıkar.
- **Eksik:** §7.1 "gecikme nedenleri" istiyor; M10-01'deki `DelayReason` dağılımı rapora eklenmemiş.
- **Düzeltilmiş hali:** M10-07 ile tek madde. Kurallar ve alanlar M10'da, ekran/Excel sunumu M12 motorunda.

### M12-04 · Tekrar arıza ve tekrar ziyaret — **DEĞİŞTİR · P2**
- **Doğrulama:** Ops.cs:93-96 seri metniyle, pencere ve iptal ayrımı olmadan, en çok 25 satır sayıyor. Doğru.
- **Çakışma:** M10-04 tekrar arızayı **iş açılışında** işaretliyor (`IsRepeat`, `RepeatOfWorkOrderId`, şef onayı "Aynı arıza / Farklı arıza / Kullanıcı hatası") ve oranı yalnız "Aynı arıza" ile hesaplıyor. M12-04 ise rapor anında, onaysız ikinci bir tanım hesaplıyor. İki ekranda iki farklı oran çıkar; bu, M12-01'in "tek tanım" ilkesine ters.
- **Eksik:** Aynı iş emrinin `Tekrar Açıldı` ile yeniden açılması yeni iş emri olmadığı için hiçbir tanıma girmiyor (bkz. D03).
- **Düzeltilmiş hali:** Rapor M10-04 alanlarını okur. Rapor anında hesap yalnız M10-04 öncesi geçmiş veri için "onaysız (otomatik)" etiketiyle ayrı satırdadır. Tekrar ziyaret (K07) bu maddede kalır.

### M12-05 · Planlı bakım tamamlama — **KABUL · P2**
- **Doğrulama:** P.cs:3682 yalnız iş emri listesi üretiyor; `MaintenancePlans`, `MaintenanceDeviceItems`, `MaintenanceDeviceChecks` rapora bağlı değil. Doğru. "1 cihaz = 1 PB iş emri" kararıyla uyumlu: sayım `MaintenanceDeviceItems.WorkOrderId` üzerinden yapılmalı. `GeneratedWorkOrderId` ilk cihaz iş emridir (P.cs:3095), ayrı bir ana iş değildir.
- **Not:** "Zamanında/gecikmeli" için `MaintenancePlans.CompletedAt` (P.cs:2542) doğrudan kullanılabilir. Gecikme toleransı (S5) ve M10-10 "vadesi geçen bakım" tanımı aynı olmalı. Sözleşme tutarını dışarıda bırakması fiyat kararıyla uyumlu.

### M12-06 · Dönem karşılaştırma ve 12 aylık trend — **DEĞİŞTİR · P3**
- **Doğrulama:** Ekranda tek dönem var; Aylık Özet kohort sayıyor. Doğru.
- **Sorun:** "Snapshot gerekmez; geçmiş açık sayısı zaman damgalarından kurulur" iddiası, M12-12'nin "yeniden açılışta `CompletedAt` temizlenir" kuralıyla birlikte **yanlış sonuç** verir: Eylül'de çözülüp Kasım'da yeniden açılan iş, Eylül sonu "açık" sayısına geriye dönük eklenir. Ayrıca SLA ve tekrar arıza trendi M10/M12-03/M12-04 bitmeden anlamsız.
- **Düzeltilmiş hali:** İlk adım önceki dönem karşılaştırması + 12 aylık gelen/çözülen/kişi-saat tablosu. Dönem sonu açık sayısı `WorkOrderStatusLogs` aralıklarından kurulur ya da "geçmiş değerler sonradan değişebilir" notu yazılır. SLA/tekrar arıza trendi sonraki dilime.

### M12-07 · Parça kullanımı sayfası — **RET · P3**
- **Doğrulama:** Mevcut durum doğru. Ancak M11-07 "Parça tüketim raporu ve iş emri/cihaz bazlı parça geçmişi" aynı ihtiyacı daha doğru tanımlıyor: net çıkış = çıkış − iade − ters kayıt; servis/PB ayrı; tutar yalnız `finance.prices.view` ile.
- **Hata:** M12-07 yalnız `Çıkış` sayıyor. Oysa iş emrine bağlı `Giriş` (iade) hareketi mümkün (Ops.cs:188-212) ve finans hesabı bunu düşüyor (Ops.cs:225). Adet toplamı fazla çıkar.
- **Öneri:** Madde silinir. M11-07 M12-01'in filtre modelini ve Excel yazıcısını kullanır. Parça × marka/model kırılımı M11-07'ye not olarak eklenir.

### M12-08 · Eksik kırılımlar — **DEĞİŞTİR · P2**
- **Doğrulama:** Şef yalnız metin filtresi (P.cs:2203; app.js:1106), `Contains` araması (P.cs:2211; app.js:1105) ve müşteri tablosunun yalnız süre kaydından üretilmesi (P.cs:3705-3709; app.js:1178) doğru. Şehir/öncelik filtresi yok, doğru.
- **Düzeltme:** Ekranda "Personel İş Yükü" tablosu (app.js:1146-1154) zaten süre kaydı olmayan atanmış teknisyenleri atanan/tamamlanan sayılarıyla listeliyor; eksik olan Excel tarafı.
- **Çakışma:** Müşteri/lokasyon kırılımı M14-12'nin konusu (`CustomerId/SiteId` ile gruplama). M12-08 müşteri kırılımını M14 kimliğine bağlamalı, metin varsayımı yalnız geçiş dönemi için olmalı.
- **Ara çözüm:** "Ali" aramasının "Aliye"yi getirmesi M01-10'u beklemeden düzeltilebilir: `AssignedStaff` virgülle bölünüp **tam eşleşme** yapılır (zaten `FilterWorkOrdersForUser` böyle yapıyor, P.cs:3500).

### M12-09 · Hesaplama hataları — **DEĞİŞTİR · P1**
- **Doğrulama:** (a) P.cs:3651, 3666 ve 3678 süre kaydını yalnız seçili dönem kayıtlarından arıyor; açık ve iptal işler de "eksik" sayılıyor. Doğru. (b) P.cs:3690-3693 kohort sayıyor. Doğru. (c) Excel Personel KPI yalnız `logs.GroupBy` (P.cs:3697). Doğru. Ekranda karşılığı zaten var (app.js:1146). (d) Özet'te İptal ve tanımsız satırı yok (P.cs:3655-3660). Doğru.
- **Önem:** Yanlış "eksik" sayısı kullanıcının "süre kaydı yoksa eksik denir" kararını tersinden bozuyor: eksik olmayanı eksik gösteriyor. Veri doğruluğu → P1.
- **Bağımlılık düzeltmesi:** (a), (c), (d) bugünkü kodda hemen yapılabilir. Yalnız (b)'nin "Çözülen (çözüm ayı)" sütunu M12-12'ye bağlı. O gelene kadar sütun "Kapatılan (ClosedAt ayı)" adıyla ve açıklama notuyla verilir.

### M12-10 · Excel hücre tipleri — **KABUL · P1**
- **Doğrulama:** P.cs:3761-3762 değer koklaması ve P.cs:3678/3703 metin tarihler doğru. 16-17 haneli rakamsal seri no'lar ve `5321234567` gibi telefonlar sayıya dönüşüyor.
- **Not:** Kullanıcının "seri no metin" kararının çıktıda ihlali → P1. S4 kararı çıkarsa M12-02 kütüphane geçişiyle birlikte yapılır; çıkmazsa mevcut `MakeSheet`'e sütun şeması eklenerek S eforla yapılır.

### M12-11 · Durum grupları — **DEĞİŞTİR · P1**
- **Doğrulama:** app.js:128 ile 131 ve Ops.cs:8 ile P.cs:2808 çelişkileri doğru. P.cs:3684'teki `statuses` dizisi tanımlı ama hiç kullanılmıyor (ölü kod).
- **Hata:** Tasarımın §2.2-2 kataloğu POC birimi durumlarını (`İnceleniyor`, `Telefonla Destek`, `Uzaktan Müdahale`, `Yerinde Müdahale`; app.js:31) içermiyor. Bu haliyle uygulanırsa POC işleri "Tanımsız durum" olarak raporlanır. `Çözüldü` arayüzde yok; katalogda kalması M01-09 kararına bağlı.
- **Düzeltilmiş hali:** Bkz. JSON `revised`.

### M12-12 · Zaman damgaları — **DEĞİŞTİR · P1**
- **Doğrulama:** `ClosedAt` davranışı doğru (P.cs:527, 2520, 2761). İptal tarihi yok, doğru.
- **Çakışma:** Aynı kavram üç modülde ayrı ayrı ekleniyor: M01-09 kabul (5) `ClosedAt/CompletedAt` temizliği; M10-01 `ResolvedAt` ("ilk Tamamlandı/Kapatıldı geçişi"); M10-15 aynı geçmiş doldurma scripti. İki ayrı kolon ve iki script kabul edilemez.
- **İç çelişki:** Açıklama "`CompletedAt` = ilk çözüm anı" diyor, kabul (4) "ikinci çözüm anı" diyor.
- **Geçmiş doldurma riski:** Atölye PUT ve bekleme uçları durum logu yazmıyor. Yalnız loga dayanan script atölye çözümlerini kaçırır. Daha iyi kaynaklar var: `WorkshopTickets` tamamlanma tarihi ve PB için `MaintenanceDeviceItems.CompletedAt`.
- **Düzeltilmiş hali:** Bkz. JSON `revised`. Tek alan seti M01-09'da tanımlanır, tek geçmiş doldurma scripti olur (M10-15 ile birleşik). Anlam netleşir: çözüm anı = son çözüm (dönem sonu açık hesabı için); SLA sonucu ilk çözümde damgalanır (M10-01 `SlaResult`) ve değişmez.

### M12-13 · Lokasyon kavramları — **DEĞİŞTİR · P1 (kod düzeltmesi KRİTİK)**
- **Doğrulama:** P.cs:2519 `Location=COALESCE(@Zone,Location)` **ve** `Description=COALESCE(@Work,Description)` doğru. PB açılışındaki `Location = bölge ?? adres` (P.cs:3088) doğru. Gruplama `LocationNote ?? SiteName ?? Location` (P.cs:3706) doğru.
- **Değerlendirme:** Tasarım bunu rapor sorunu sayıyor, oysa her bakım formu kaydında iş emrinin orijinal lokasyonu ve açıklaması (dönem/hedef tarih metni, P.cs:3090) **geri dönüşsüz kayboluyor**. Bu bir veri kaybıdır. M14-07 aynı düzeltmeyi KRİTİK işaretlemiş.
- **Düzeltilmiş hali:** UPDATE düzeltmesi M14-07'de tek iş olarak, öncelik sırasından bağımsız hemen yapılır (`Description` dahil). M12-13 yalnız rapor tarafı öncelik kuralını ve "tesis/bölge/not" ayrımını taşır.

### M12-14 · Veri Kalitesi sayfası — **DEĞİŞTİR · P2**
- **Doğrulama:** Yalnız tek ve hatalı bir "eksik" sayısı var (P.cs:3666). Doğru. `WorkTypeRules.SerialRequiredOnClose` mevcut (P.cs:520-522); kontrol (3) uygulanabilir.
- **Çakışma:** Kontrol (7) müşteri adı varyantları M14-03/M14-09'un normalizasyon ve eşleştirme işiyle aynı. İki ayrı normalizasyon fonksiyonu iki farklı grup üretir. Kontrol (1) M09-07 "zaman verisi disiplini" ile örtüşüyor.
- **Düzeltilmiş hali:** (7) yalnız M14'ün ortak normalizasyon fonksiyonunu çağırır; M14 gelince "ana veriye eşleşmemiş iş" sayısına dönüşür. (1) M09-07 ile aynı tanımı kullanır. Sayfa yalnız listeler (kabul 4 korunur).

### M12-15 · SQL'de süzme — **DEĞİŞTİR · P2**
- **Doğrulama:** Tam tablo okumaları doğru (P.cs:3424-3439, 3441-3493). Ancak `worklogs` çağrısı 5 yerde (app.js:142, 1449, 1654, 1661, 1985). `/api/ops/overview` ve `/api/ops/finance` de tüm süre kayıtlarını okuyor (Ops.cs:82, 218).
- **Düzeltilmiş hali:** Kabul kriterine "rapor sayfası dışında hiçbir yerde `/api/reports/worklogs` çağrılmaz" eklenir. Ops uçları M10/M09-15 kapsamında aynı yardımcıya geçer. Linux geçişinden önce bitirilmesi gerekir (§14-Öncelik 1).

### M12-16 · Kişi bazlı rapor verisi ve dışa aktarım kaydı — **DEĞİŞTİR · P2**
- **Doğrulama:** P.cs:2181-2229 yalnız `reports.view/export` kontrol ediyor; Excel saha yetkilisi/telefonu içeriyor (P.cs:3676); Muhasebe ve Genel Koordinatör `reports.export` sahibi (P.cs:3927, 3931); `worklogs` teknisyen notu ve konum notu döndürüyor. Doğru.
- **KRİTİK mi?** Fiyat/maliyet sızıntısı yok; veri kaybı yok. Kişisel veri (KVKK) yetki fazlası var ama kullanıcı tanımına göre KRİTİK değil. Kullanıcı sırası gereği (a) grubunda kalır. Ancak Linux üretimine geçmeden önce kapanmalıdır.
- **Sorun:** Ayrı `ReportExportLogs` tablosu, A1-16/M13'teki ortak denetim izi altyapısıyla mükerrer. `reports.personnel` dağılımı organizasyon şemasına bağlı (varsayım). Saha irtibatı kişisel verisi M14-13 ile ortak ele alınmalı.
- **Düzeltilmiş hali:** Bkz. JSON `revised`.

---

## 4. Eklenen maddeler

### M12-D01 · EKSİK · Rapor doğrulama test veri seti ve otomatik KPI regresyon testi (M)
- **Neden:** M12-01, 03, 04, 05, 09, 11, 12 ve 16'nın kabul kriterleri "en az 40 iş emri", "AKYAKA 17 cihaz", "otomatik testle doğrulanır" gibi ifadeler içeriyor, ama hiçbir madde bu veri setini ve testi üretmiyor. Kullanıcı test verisi kararını bize bıraktı. Repoda test projesi yok.
- **Mevcut:** Yalnız `DengeERP.Api.csproj`; `TEST_SONUCLARI_V120.txt` elle test.
- **Kabul:** (1) İdempotent `ZZ_TEST_ReportSeed.sql` yalnız `DengeERP_TEST` veritabanında çalışır; üretim veritabanı adıyla çalıştırılırsa durur. (2) Seed şunları içerir: 3 birim; servis/PB/atölye; tüm durum grupları + bir `Iptal` (tanımsız) kaydı; POC durumları; yeniden açılmış iş; süre kaydı dönem dışında olan iş; 16-18 haneli ve `0` ile başlayan seri no; 17 cihazlı AKYAKA bakım dönemi; iş emrine bağlı çıkış ve iade hareketi. (3) Beklenen sonuçlar elle hesaplanmış bir tabloda tutulur. Test, `summary` ve Excel değerlerini bu tabloyla karşılaştırır. (4) Test, M07/M13 ile ortak `DengeERP.Tests` projesinde çalışır.

### M12-D02 · HATA/EKSİK · Atölye kategorisi ayrımı ve iptal edilen atölye işinin "açık" sayılması (S)
- **Neden:** Tasarım ilkesi §2.2-7 "Günlük Servis, Planlı Bakım ve Atölye her yerde ayrı" diyor. Ancak hiçbir madde bunu uygulamıyor; `IsReportMaintenance` ikili (P.cs:3638-3639). Ayrıca atölye kaydı `İptal` yapılınca iş emri `Atölyede` oluyor (P.cs:2754). Bu iş raporda açık, Operasyon Merkezi'nde geciken görünüyor.
- **Kabul:** (1) Kategori, sunucuda tek fonksiyonla belirlenir: PB → Planlı Bakım; `WorkshopTickets` kaydı olan → Atölye; diğerleri → Günlük Servis (S7 kararı "ayrı" ise). (2) Atölye kaydı `İptal` olunca iş emri `İptal` olur ve raporda açık sayılmaz. Eşleme düzeltmesi M05-01 ile aynı iş olarak yapılır; mevcut kayıtlar için önce yalnız listeleyen sorgu çalışır. (3) Atölye işleri tekrar arıza paydasında servisle birlikte, kişi-saatte ayrı sütunda görünür.

### M12-D03 · EKSİK · Yeniden açılan iş göstergesi (S)
- **Neden:** M12-04 yalnız **yeni** iş emri açılmasını tekrar arıza sayıyor. Aynı iş emrinin `Tekrar Açıldı` ile yeniden açılması (app.js:30'da durum var) hiçbir KPI'ya girmiyor. Servis kalitesinin ikinci doğrudan ölçüsü kayboluyor. M01-09 `ReopenCount` ekliyor ama hiçbir rapor onu okumuyor.
- **Kabul:** (1) Dönemde çözülen işlerden, çözümden sonra yeniden açılanların sayısı ve oranı (`WorkOrderStatusLogs` veya `ReopenCount`). (2) Liste: iş no, ilk çözüm, yeniden açılış, aradaki gün, gerekçe (M01-09). (3) PB işleri ayrı satırda. (4) Yeniden açılan iş M12-04'te "tekrar arıza" olarak ikinci kez sayılmaz.

---

## 5. Uygulama sırası önerisi (düzeltilmiş)

| Dilim | Maddeler | Not |
|---|---|---|
| 0 (hemen, bağımsız) | M14-07 (M12-13'ün kod kısmı) | KRİTİK veri kaybı |
| 1 | M12-10, M12-11, M12-09 (a,c,d), M12-D01, M12-D02 | Küçük doğruluk düzeltmeleri + test verisi |
| 2 | M12-12 (M01-09/M10-01/M10-15 ile tek iş), M12-09 (b), M12-02 | Zaman damgası; kullanıcının açık talebi olan pivot |
| 3 | M12-01, M12-05, M12-03 (M10-07 ile), M12-04 (M10-04 ile) | Tek motor ve yönetim soruları |
| 4 | M12-08, M12-13 (rapor kısmı), M12-14, M12-D03, M12-06 | Kırılım, veri kalitesi, trend |
| 5 | M12-15, M12-16 | Linux üretimine geçmeden önce zorunlu |

## 6. Denetçi notları
- Tasarım genel olarak kanıta dayalı ve satır referansları büyük ölçüde doğru. Ana zayıflık **modüller arası mükerrerlik**: M10-01/07/15, M10-04, M11-07, M14-07/09/12 ve M01-09 ile aynı işler ikinci kez tanımlanmış. Uygulama planında her kavramın tek sahibi olmalı: kural ve alan ilgili modülde, sunum M12 motorunda.
- Kullanıcı kararlarıyla doğrudan çelişki yok. Tahmini süre kullanılmıyor, "eksik" ilkesi korunuyor, fiyat API'de gizleniyor, teknoloji yığını korunuyor. Tek yeni bağımlılık (ClosedXML) için S4 onayı gerekli.
- §3.1'deki "teknisyen puanlaması yapılmaz" kararı yerinde. Kişi kırılımı yalnız iş yükü ve veri eksikliği görünürlüğü içindir.
- Rol önerileri (özellikle `reports.personnel` dağılımı ve Şef'e `reports.export`) **varsayımdır**; organizasyon şeması gelince doğrulanmalıdır.
- Geçmiş dönem raporlarının sonradan değişmesi (geç girilen süre kaydı, yeniden açılan iş) yönetim toplantısında güveni zedeleyebilir. Şimdilik her çıktıda `generatedAt` yazılması yeterli. "Ay kapanışı / yayınlanmış rapor arşivi" ihtiyacı yönetim talep ederse sonra değerlendirilmelidir.
