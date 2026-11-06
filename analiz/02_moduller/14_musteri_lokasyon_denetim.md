# M14 — Müşteri, Lokasyon ve Sözleşme Ana Verisi · Bağımsız Denetim

> **Denetlenen:** `analiz/02_moduller/14_musteri_lokasyon_tasarim.md` (14 madde)
> **Kaynak:** `kaynak/V1_20_1_orijinal/DengeERP.Api` (salt okunur incelendi, değişiklik yapılmadı)
> **Tarih:** 21.10.2026 · Kapsam: yalnız teknik servis · Rol önerileri varsayımdır.

## 1. Genel değerlendirme

Tasarım genel olarak **doğru teşhis** koyuyor: müşteri/lokasyon/irtibat ana tablosu yok, her modül serbest metin tutuyor ve bakım üretimi cihazları yanlış kolon üzerinden arıyor. Kod referanslarının büyük çoğunluğu doğrulandı. Ancak dört noktada düzeltme gerekiyor:

1. **M14-07 "KRİTİK (veri kaybı)" etiketi abartılı, kabul kriteri 3 yanlış.** Satır gerçekten hatalı (`Program.cs:2519`). Ancak ezilen lokasyon değeri cihaz kütüğünden veya sözleşmeden yeniden türetilebiliyor. Asıl operasyonel zarar başka yerde: havuzdaki toplu planlama gruplaması (`app.js:371-374`, `customerName+location+unitCode`) bozuluyor. Aynı UPDATE ayrıca `Description` alanını da eziyor (`COALESCE(@Work,Description)`); tasarımcı bunu kaçırmış. Excel "Müşteri Lokasyon" sayfası zaten `t.LocationNote ?? SiteName ?? Location` ve **teknisyen adı** ile grupluyor (`Program.cs:3706`). Bu yüzden yalnız 2519 düzeltilince "aynı tesis tek satır" sonucu çıkmaz.
2. **M14-10'da yetki hatası var.** Teknisyen rolünde `workorders.edit` bulunuyor (`Program.cs:3930`). Önerilen tasarımla teknisyen iş emrinin müşterisini değiştirebilir hâle gelir.
3. **Teknisyene `customers.view` verilmesi KVKK açısından geniş.** Bu izin tüm müşteri/irtibat listesini açar. Teknisyen irtibatı yalnız atandığı iş emri üzerinden görmeli.
4. **M14-12 ile M10 (Raporlama/Operasyon) çakışıyor.** Tekrar arıza, ortalama çözüm süresi ve kişi-saat KPI'ları M10'un işidir. M14 yalnız gruplama boyutunu (CustomerId/SiteId), filtreyi ve veri kalitesi göstergesini sağlamalı.

Ek olarak tasarımcı bazı küçük, bağımsız ve hemen yapılabilecek düzeltmeleri büyük ana veri işine bağlamış: müşteri adı doğrulaması, PB üretiminde cari unvanın lokasyona yazılması, saha önerisinde `siteAddress` olarak cari unvanın dönmesi. Bunlar ana veri beklemeden yapılabilir.

## 2. Madde bazında kararlar

| Id | Karar | Öncelik | Kısa gerekçe |
|---|---|---|---|
| M14-07 | DEĞİŞTİR | P1 | Hata gerçek. "KRİTİK veri kaybı" abartılı; Description ezilmesi eksik; kabul 3 yanlış |
| M14-01 | DEĞİŞTİR | P1 | Temel gerekli; teknisyen/muhasebe rol eşlemesi ve hızlı ekleme yetkisi düzeltilmeli |
| M14-02 | KABUL | P2 | Operasyonun en sık ihtiyacı; kriterler ölçülebilir |
| M14-04 | DEĞİŞTİR | P1 | Doğrulama düzeltmesi ayrılmalı (bağımlılıksız); toplu plan gruplaması eklenmeli |
| M14-03 | DEĞİŞTİR | P1 | Gerekli, ama ilk faz Güvenlik sözleşme+kütük ile sınırlı ve Excel tabanlı olmalı |
| M14-09 | KABUL | P2 | Eşleştirme sonrası kaçınılmaz; tek transaction + önizleme doğru |
| M14-11 | DEĞİŞTİR | P3 | Faydalı ama M03-03/M04-03'e bağımlı; `PeriodText` zaten var |
| M14-05 | DEĞİŞTİR | P2 | Fazlanmalı; atölye senkronunda tarihçe şartı eklenmeli |
| M14-06 | DEĞİŞTİR | P1 | Hata gerçek ve yanlış kolon kullanılıyor; ara düzeltme ana veri beklemeden yapılabilir |
| M14-08 | DEĞİŞTİR | P2 | Doğru; dönem çakışması için mevcut `PeriodText` kullanılmalı |
| M14-10 | DEĞİŞTİR | P2 | Yetki anahtarı yanlış (teknisyende `workorders.edit` var); PB işleri hariç tutulmalı |
| M14-12 | DEĞİŞTİR | P3 | M10 ile çakışıyor; M14 yalnız gruplama boyutu, filtre ve veri kalitesi |
| M14-14 | DEĞİŞTİR | P2 | Doğru; ayrıca `siteAddress = CurrentAddress` (cari unvan) hatası aynı uçta |
| M14-13 | DEĞİŞTİR | P2 | Denetim kaydı M14-01 ile aynı sürümde gelmeli; teknisyen erişimi daraltılmalı |

### M14-07 · DEĞİŞTİR · P1
**Doğrulama:** `Program.cs:2513-2521` aynı komutta `MaintenanceDeviceItems` ve `WorkOrders` güncelleniyor. `Location=COALESCE(@Zone,Location)` ve `Description=COALESCE(@Work,Description)` var. Taslak kayıtta (`Complete=false`) da çalışıyor. Bölgenin başlangıç değeri üretimde `SecurityDevices.Location` (`:3042`); form GET'te ise `COALESCE(i.Zone,sd.Location)` (`:2411`).
**Neden "KRİTİK" değil:** PB iş emrinin ilk lokasyonu `invRow.Item3 ?? address` (`:3088`) ile üretiliyor. Bu değer `MaintenanceDeviceItems.SecurityDeviceId → SecurityDevices.Location` veya sözleşme üzerinden yeniden türetilebilir. Kalıcı kayıp yalnız `Description`'daki "x/y bakım dönemi, hedef tarih" metnidir. Bu bir veri bütünlüğü hatasıdır, güvenlik/sızıntı değildir; yine de küçük olduğu için P1.
**Gerçek etki:** Havuzdaki toplu planlama anahtarı `customerName+location+unitCode` (`app.js:371-374`). Taslakta bölge girilen cihaz, aynı tesisin diğer işlerinden kopar. Operasyon merkezi (`OpsSuite.cs:85`) ve iş listeleri bölgeyi lokasyon gibi gösterir.
**Düzeltilmiş tanım:** Bakım formu uçlarında `WorkOrders.Location` ve `WorkOrders.Description` değiştirilmez. Bölge yalnız `MaintenanceDeviceItems.Zone`'a, yapılan iş yalnız `PerformedWork`'e yazılır. `SerialNo` senkronu korunur. Geçmiş için salt okunur bir listeleme sorgusu hazırlanır: `WorkOrders.Location = MaintenanceDeviceItems.Zone` olan PB işleri ile önerilen eski değer (kütükteki cihaz lokasyonu, yoksa sözleşme `CustomerName`). Güncelleme yedekten sonra, onayla ve ayrı çalıştırılır.
**Kabul:**
1. Bölgesi "X-Ray 3 / Giriş B" girilen taslak ve kapanış kaydında `WorkOrders.Location` ile `Description` değişmez; `Zone` ve `PerformedWork` yeni değeri alır.
2. Aynı tesisteki iki PB işinden birine bölge girildikten sonra ikisi havuzda hâlâ aynı toplu plan grubunda görünür.
3. Listeleme sorgusu hiçbir satırı değiştirmez.
4. Excel kriteri kaldırılır; rapor gruplaması M14-12/M10'da ele alınır.

### M14-01 · DEĞİŞTİR · P1
**Doğrulama:** Ana tablo yok (envanter §9, §57). İzin kataloğunda `customers.*` yok (`Program.cs:3875-3911`).
**Değişiklikler:**
- **Teknisyen:** `customers.view` verilmez. İrtibat bilgisini yalnız atandığı iş emri detayında görür (`CanAccessWorkOrderAsync` zaten var).
- **Muhasebe / Genel Koordinatör:** Teknik servis kapsamı dışında. Yalnız rapor için `customers.view` verilebilir, varsayım olarak işaretlenir.
- **Hızlı ekleme:** `workorders.create` sahibinin `customers.edit` olmadan "Doğrulanmamış" müşteri açabilmesi, M14-13'teki "her değişiklik denetim kaydına" kuralıyla birlikte tasarlanmalı. Hızlı ekleme ayrı bir uç olur (yalnız ad + il), denetim kaydı yazar ve yalnız `Doğrulandı=0` kayıt açabilir.
- **VKN tekilliği:** Yalnız `Durum=Aktif` kayıtlar arasında uygulanır. Birleştirilmiş kayıtlar hariç tutulur (filtreli benzersiz indeks).
- **Denetim:** `CustomerMasterAudit` tablosu aynı scriptte kurulur (M14-13'ten buraya alınır).

**Kabul:** Tasarımcının 7 kriteri geçerli. Ek: (8) `Teknisyen` rol şablonuyla `/api/customers` çağrısı 403 döner. (9) Hızlı ekleme ucu `Doğrulandı=0` dışında kayıt açamaz.

### M14-02 · KABUL · P2
Ekran yok; doğrulandı (index.html/app.js'de müşteri menüsü yok). Kriterler ölçülebilir ve fiyat gizlemenin API seviyesinde yapılması kararıyla uyumlu. Not: "Cihazlar" sekmesi M14-05 ile `SecurityDevices.SiteId` dolmadan boş görünür. Boş sekmede "eşleştirilmemiş" açıklaması gösterilmeli.

### M14-04 · DEĞİŞTİR · P1
**Doğrulama:** `Program.cs:370-404`: `CustomerName` için boş, trim veya uzunluk kontrolü yok. `null` gelirse `AddWithValue` parametresi eksik kalır ve 500 döner; `""` ya da `"   "` kaydedilir. Teklif ucunda da aynı durum var (`:831`). Kiralama (`:1059`) ve atölye (`:2635`, `:2714`) kontrol ediyor.
**Değişiklikler:**
- Müşteri adı doğrulaması bu maddeden çıkarılıp **M14-D01** olarak bağımlılıksız yapılır.
- Havuz/toplu planlama gruplaması (`app.js:371-374`) `siteId` doluysa onu, yoksa bugünkü metni kullanır.
- Toplu planda farklı `SiteId` uyarısı, mevcut `bulkLocationKey` davranışıyla tutarlı olmalı.

**Kabul:** Tasarımcının 1-3 ve 5-7 kriterleri geçerli. 4. kriter M14-D01'e taşınır. Ek: (8) Aynı `SiteId`'li ama farklı yazılmış iki iş havuzda aynı toplu plan grubunda görünür.

### M14-03 · DEĞİŞTİR · P1 (ilk faz)
**Doğrulama:** Seed'de sözleşme `AKYAKA AVM` (`DengeERP_V15_Seed.sql:2394`), kütükte `AKYAKA PARK AVM` (`:1252-1259`) var. Kütükte bu tesis için 8 X-Ray satırı bulunuyor, sözleşme ise 9 X-Ray ve 8 kapı diyor. "Eksik sayının açıkça yazılması" kriteri bu yüzden gerçekten gerekli.
**Aşırı mühendislik riski:** Yedi tabloyu birden kapsayan, güven düzeyli bir eşleştirme ekranı L+ efordur.
**Düzeltilmiş tanım (fazlı):**
- **Faz 1:** Yalnız `MaintenanceContracts` (87) ve `SecurityDevices` (Güvenlik). Salt okunur aday listesi Excel/CSV olarak dışa aktarılır. Kullanıcı Excel'de onaylar ve onaylı dosya içe aktarılır. İçe aktarma yalnız onaylı satırları `CustomerAliases`'a ve `SiteId`/`CustomerId`'ye yazar.
- **Faz 2:** `WorkOrders`, `WorkOrderPlans`, `Offers`, `RentalOrders`, `WorkshopTickets` için aynı yöntem. Ekranlı eşleştirme ancak Excel yöntemi yetersiz kalırsa yapılır.

**Kabul:** Tasarımcının 7 kriteri geçerli. Ek: (8) İçe aktarma dosyasındaki onaysız veya boş satır hiçbir tabloya yazılmaz. (9) İçe aktarma sonucu tablo bazında yazılan satır sayısını raporlar.

### M14-09 · KABUL · P2
Birleştirme, eşleştirme ve hızlı ekleme sonrası kaçınılmazdır. Transaction, önizleme ve denetim kaydı doğru. Kabul 3'ün JSON metni ("pasif hedef 400") tasarım dokümanındaki karışık ifadeden daha net; o hâliyle kalsın.

### M14-11 · DEĞİŞTİR · P3
**Doğrulama:** Tasarımcı dönem bilgisinin olmadığını söylüyor. Oysa `MaintenanceContracts.PeriodText` mevcut (`DengeERP_V15_Schema.sql:43`, örnek `'01.01.2026-31.12.2026'`). Garanti bilgisi M03-03 gelene kadar yok.
**Düzeltilmiş tanım:** İlk sürümde yalnız sözleşme durumu gösterilir: aktif sözleşme no ve `PeriodText`'ten ayrıştırılabilen dönem. Ayrıştırılamazsa "Dönem bilgisi yok" yazar. Son 30 günün işleri de gösterilir. Garanti satırı M03-03 sonrası eklenir. `CoverageStatus` anlık görüntüsü korunur. Tutar yok.
**Kabul:** Tasarımcının 4 kriteri geçerli. Ek: `PeriodText` ayrıştırılamayan sözleşmede "Sözleşmeli" yazılmaz.

### M14-05 · DEĞİŞTİR · P2
**Doğrulama:** Serbest metin kolonları doğrulandı (`:831`, `:1111-1124`, `:1176`, `:2688`, `:2759`). Atölye PUT ucu, `workshop.manage` ile `WorkOrders.CustomerName`'i **tarihçesiz** değiştiriyor (`:2711`, `:2757-2772`). Bu izin Teknisyen rolünde de var (`:3930`).
**Değişiklikler:**
- **Faz A:** `WorkOrders`, `WorkOrderPlans`, `MaintenanceContracts`, `SecurityDevices` (M14-06 için zorunlu).
- **Faz B:** `Offers`, `RentalOrders`/`RentalOrderContacts`, `WorkshopTickets`.
- Teklif iş emrinden açılıyorsa müşteri bilgisi **sunucuda** iş emrinden kopyalanır. Bugün bu yalnız istemcide yapılıyor.

**Kabul:** Tasarımcının 5 kriteri geçerli. Ek: (6) Atölye güncellemesi iş emri müşterisini değiştirdiğinde eski/yeni değer iş emri tarihçesine yazılır (M14-D02).

### M14-06 · DEĞİŞTİR · P1
**Doğrulama:** `Program.cs:3010-3016`: `SecurityDevices.CustomerName=@Customer`. Burada `@Customer` sözleşmenin `CustomerName`'i, yani **tesis**. Kütükte `CustomerName` satın alan firma, `Location` ise tesis (tasarım §1.6). Yani karşılaştırma **yanlış kolonla** yapılıyor. Ayrıca `:3088` cihaz yoksa lokasyona `address` yazıyor; `address` = `CurrentAddress` = cari unvan.
**Düzeltilmiş tanım (iki adım):**
- **Adım 1 (ana veri beklemeden, S):** Cihaz araması `SecurityDevices.Location = sözleşme.CustomerName OR SecurityDevices.CustomerName = sözleşme.CustomerName` ile yapılır (trim ve tr-TR büyük harf). Cihaz yoksa PB `Location` alanına `CurrentAddress` değil sözleşme `CustomerName`'i (tesis) yazılır. Üretim öncesi "eşleşen cihaz yok / eksik N" uyarısı verilir.
- **Adım 2:** Tasarımcının sırası uygulanır: doğrudan sözleşme–cihaz bağı (M03-09), sonra `SiteId`, sonra adım 1.

**Kabul:** Tasarımcının 4 kriteri geçerli. Ek: (5) Adım 1 sonrası `CustomerName`'i farklı ama `Location`'ı sözleşme adıyla aynı olan cihazlar PB kalemine bağlanır. (6) Hiçbir PB iş emrinin `Location`'ına `CurrentAddress` değeri yazılmaz.

### M14-08 · DEĞİŞTİR · P2
Tesis/cari karışıklığı doğrulandı (`:2386`, `:3088`, seed `:2394`). Mükerrer sözleşme tespitleri seed üzerinden yapılmış; canlı veride kullanıcı onayı şart (tasarım §5 soru 5).
**Değişiklik:** Dönem çakışması kontrolü M04-03'ü beklemeden `PeriodText` ayrıştırılarak yapılabilir. Ayrıştırılamazsa yalnız "aynı tesis adında birden çok aktif sözleşme" listelenir.
**Kabul:** Tasarımcının 3 kriteri geçerli. Ek: (4) Hiçbir sözleşme kaydı otomatik pasifleştirilmez veya silinmez; düzeltme listesi önce kullanıcıya sunulur.

### M14-10 · DEĞİŞTİR · P2
**Doğrulama:** Genel iş emri güncelleme ucu yok. `/api/workorders/{id}/history` var (`:763`). `InsertStatusLogAsync` aynı durumla not yazmayı destekliyor (`:609`).
**Hata:** `workorders.edit` Teknisyen ve Şef rollerinde var (`:3929-3930`). Önerilen yetkiyle teknisyen müşteri değiştirebilir.
**Düzeltilmiş tanım:** `PUT /api/workorders/{id}/customer`
- Açık işte `workorders.create` (Operasyon) veya `workorders.plan` (Şef) gerekir. Kapalı işte `customers.merge`.
- Gerekçe zorunlu. Eski/yeni değer tarihçeye yazılır.
- `WorkType='Planlı Bakım'` işlerde müşteri/lokasyon bu uçla değiştirilemez; kaynak sözleşmedir.

**Kabul:** Tasarımcının 4 kriteri geçerli. Ek: (5) Yalnız `workorders.edit`/`workorders.close` sahibi (Teknisyen) 403 alır. (6) PB işinde 400 döner.

### M14-12 · DEĞİŞTİR · P3
**Doğrulama:** `:2212` (Contains), `:3706` (gruplama: metin + `LocationNote` + teknisyen), `OpsSuite.cs:93` (seri no bazlı tekrar) doğrulandı.
**Değişiklik:** Tekrar arıza, ortalama çözüm süresi ve lokasyon kişi-saati M10'da tanımlanır. M14 yalnız şunları sağlar: (a) rapor/operasyon gruplamalarında `SiteId`/`CustomerId` boyutu ve "Eşleştirilmemiş: metin" etiketi, (b) müşteri/lokasyon seçimli filtre, (c) veri kalitesi göstergeleri.
**Kabul:** Tasarımcının 1, 5 ve 6. kriterleri burada kalır; 2-4 M10'a devredilir. "Süre kaydı eksik, 0 değil" kuralı M10'da korunur.

### M14-14 · DEĞİŞTİR · P2
**Doğrulama:** `:627` ve `:645` doğru; `siteContact = SecurityDevices.ContactName`. Aynı uçta `siteAddress = mc.CurrentAddress` (`:627`, `:644`); tasarımcının kendi bulgusuna göre bu değer **cari unvan**. Plan formunda "Açık Adres" kutusu firma unvanıyla ön dolar. Bu hata tasarımda kaçırılmış.
**Düzeltilmiş tanım:**
- `siteAddress` artık `CurrentAddress`'ten doldurulmaz. Lokasyon kaydı yoksa boş kalır.
- `siteContact` kütük `ContactName`'inden doldurulmaz. Kullanıcı teyidine kadar boş döner, sonra lokasyonun birincil irtibatından gelir.
- Kütük etiketi kullanıcı teyidiyle değişir. `ContactName` müşteri irtibatına aktarılmaz.

**Kabul:** Tasarımcının 3 kriteri geçerli. Ek: (4) Saha önerisi `siteAddress` alanında hiçbir zaman `MaintenanceContracts.CurrentAddress` değeri dönmez.

### M14-13 · DEĞİŞTİR · P2
Denetim kaydı yok (envanter gözlem 3). İrtibat kişisel veri, gerekçe doğru.
**Değişiklik:**
- `CustomerMasterAudit` M14-01 scriptinde kurulur; denetim yazımı M14-01 uçlarıyla aynı sürümde gelir. Sonradan eklenirse ilk aktarım dönemi kayıtsız kalır.
- Teknisyen `customers.view` almaz.
- Dışa aktarım `reports.export` ile yapılır ve denetim kaydı yazar.

**Kabul:** Tasarımcının 4 kriteri geçerli. Ek: (5) Hızlı ekleme ve eşleştirme içe aktarması da denetim kaydı üretir.

## 3. Eklenen maddeler (tasarımcının kaçırdıkları)

### M14-D01 · HATA · S · P1 — İş emri ve teklif açılışında müşteri adı doğrulaması
- **Mevcut:** `Program.cs:404` ve `:831`: `request.CustomerName` doğrudan yazılıyor. `null` gelirse SQL parametre hatası ve 500, `""`/boşluk ise kayıt açılıyor, trim yok. Kiralama (`:1059`) ve atölye (`:2635`) kontrol ediyor.
- **Tanım:** `POST /api/workorders` ve `POST /api/offers` için `CustomerName` trim edilir. Boş/boşluk olursa 400, 250 karakterden uzunsa 400 döner. Teklif `WorkOrderId` ile açılıyorsa müşteri adı sunucuda iş emrinden alınır.
- **Kabul:** (1) `customerName=null`, `""`, `"   "` için 400 ve Türkçe mesaj döner; 500 dönmez. (2) `"  ABC AVM  "` "ABC AVM" olarak kaydedilir. (3) 251 karakterde 400. (4) İş emrine bağlı teklifte istemcinin gönderdiği farklı ad yok sayılır.
- **Bağımlılık:** Yok; M14-01'i beklemez.

### M14-D02 · EKSİK · S · P2 — Atölye güncellemesinin iş emri müşterisini tarihçesiz değiştirmesi
- **Mevcut:** `Program.cs:2711` (`workshop.manage` veya `workorders.edit`), `:2757-2772`: `WorkOrders.CustomerName`, `Subject`, `Description`, `SerialNo` ve `Status` kayıt bırakmadan değişiyor. `workshop.manage` Teknisyen rolünde var (`:3930`).
- **Tanım:** Atölye güncellemesi iş emrinin müşteri adını veya seri nosunu değiştirdiğinde eski/yeni değer iş emri tarihçesine not olarak yazılır. `WorkshopTickets.CompanyName` değişikliği de aynı şekilde kaydedilir.
- **Kabul:** (1) Firma adı değiştirilen atölye kaydının bağlı iş emri `/history`'sinde eski ve yeni ad, kullanıcı ve zaman görünür. (2) Değişiklik yoksa tarihçe satırı oluşmaz.

### M14-D03 · VERİ · S · P1 — Canlı veritabanında salt okunur veri kalitesi ölçümü
- **Mevcut:** Tasarımdaki tüm sayılar (507 yazım, 87'de 1 eşleşme, 112 boş müşteri, ContactName dağılımı) **seed** dosyasından alınmış (tasarım §1.6, §6). Canlıda kullanıcılar düzeltme yapmış olabilir.
- **Tanım:** Yalnız `SELECT` içeren bir ölçüm scripti yazılır. Ölçülenler: farklı müşteri metni sayısı (tablo bazında), sözleşme–kütük eşleşmesi (`CustomerName` ve `Location` üzerinden ayrı ayrı), boş müşteri, `WorkOrders.Location = MaintenanceDeviceItems.Zone` olan PB işleri (M14-07 etkisi), şüpheli mükerrer sözleşmeler. M14-03 faz planı ve M14-06 adım 1'in etkisi bu sonuca göre kesinleşir.
- **Kabul:** (1) Script hiçbir tabloyu değiştirmez (yalnız SELECT; çalıştırma öncesi/sonrası satır sayıları aynı). (2) Çıktı SSMS'ten Excel'e kopyalanabilir tek sonuç kümeleri hâlindedir. (3) Test kopyasında da çalışır.

### M14-D04 · EKSİK · S · P2 — Havuz/toplu planlama ve takvim gruplamasının lokasyon kimliğine geçmesi
- **Mevcut:** `app.js:371-374` `bulkLocationKey` = `customerName + location + unitCode` metni. Takvimdeki kompakt ziyaret kartı (proje geçmişi §151) da aynı müşteri+lokasyon metnine dayanıyor. Yazım farkı varsa aynı tesis iki ayrı grup olur.
- **Tanım:** İş emri yanıtında `siteId` varsa gruplama anahtarı `siteId + unitCode` olur, yoksa bugünkü metin. Sunucuda toplu plan isteğinde (`/api/workorders/bulk-plan`) farklı `SiteId`'li işler gelirse uyarı/onay istenir.
- **Kabul:** (1) "AKYAKA AVM" ve "AKYAKA PARK AVM" yazımlı, aynı `SiteId`'li iki iş havuzda tek grupta görünür. (2) `SiteId` boş eski işler bugünkü gibi gruplanır. (3) Farklı `SiteId`'li işlerin toplu planı uyarı verir.
- **Bağımlılık:** M14-05 (faz A).

## 4. Önerilen uygulama sırası (kullanıcı önceliği c→b→a ile uyumlu)

1. **Hemen (küçük, bağımsız):** M14-07, M14-D01, M14-06 adım 1, M14-14 (`siteAddress`/`siteContact` boşaltma), M14-D03 ölçüm.
2. **c — yeni modül:** M14-01 (denetim tablosu dahil) → M14-05 faz A → M14-04 + M14-D04 → M14-02 → M14-03 faz 1 (Excel onaylı).
3. **b — eksikler:** M14-06 adım 2, M14-08, M14-09, M14-10, M14-D02, M14-05 faz B.
4. **Sonra:** M14-11, M14-12 (M10 ile birlikte), M14-13'ün dışa aktarım kısmı.

## 5. Varsayımlar ve açık sorular

- Rol eşlemeleri varsayımdır. Özellikle teknisyenin müşteri listesine erişmemesi bir öneridir; organizasyon şeması gelince teyit edilmeli.
- `SecurityDevices.ContactName`'in Denge personeli olduğu tahmini kullanıcı teyidi bekliyor (tasarım §5 soru 3).
- Seed dışı (canlı) veri görülmedi. Sayılar M14-D03 ile doğrulanmalı.
