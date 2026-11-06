# M04 — Planlı Bakım ve Dijital Servis Formu: Gereksinim Tasarımı

> **Sürüm tabanı:** V1.20.1 (salt okunur kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Tarih:** 21.10.2026 · **Kapsam:** yalnızca teknik servis (Güvenlik Sistemleri birimi planlı bakımları)
> **Öncelik kuralı:** (c) yeni özellik → (b) mevcut eksik → (a) güvenlik/üretime hazırlık. Veri kaybı/sızıntısı yaratan maddeler öncelikten bağımsız **KRİTİK** olarak işaretlenmiştir.
> **Değişmeyen kararlar:** 1 cihaz = 1 PB iş emri · seri no metin · fiyat/maliyet API'de gizli · süre kaydı yoksa "eksik", 0 değil · tahmini süre gerçek süre yerine kullanılmaz · mola kişi-saate dahil değil · teknoloji yığını korunur, artımlı geliştirme.
> **Not:** Organizasyon şeması henüz gelmedi; bu belgedeki rol dağılımları **varsayımdır** ([V] ile işaretli).

---

## 1. Mevcut durum (koddan çıkarılan)

### 1.1 Veri modeli

| Tablo | Kaynak | Önemli alanlar | Gözlem |
|---|---|---|---|
| `MaintenanceContracts` | `Database/DengeERP_V15_Schema.sql:31-52` | CustomerName, CurrentAddress, **ProductsText** (serbest metin, "4 X-RAY 9 KAPI DEDEKTÖRÜ"), FrequencyText, AnnualFrequency, MaintenanceFeeText, **PeriodText** (serbest metin), **CompletedCount** (yıl bilgisi yok), ContractTotal, **Total2026** (yıl sabit kolon) | Sözleşme başlangıç/bitiş tarihi kolon olarak yok; cihaz kapsamı metinden regex ile çıkarılıyor. |
| `MaintenancePlans` | `V15_Schema.sql:54-76` | PlanYear, SequenceNo, TargetDate, IsCompleted, GeneratedWorkOrderId; UQ(Contract,Year,Seq) | Plan **takvim yılına** bağlı, sözleşme dönemine değil. |
| `MaintenanceDeviceItems` | `V17_Schema.sql:1-21`, `V18_DeviceWorkOrders.sql:3-28` | DeviceType, DeviceOrdinal, SerialNo, Zone, Status (Bekliyor/Tamamlandı), PerformedWork, SpareParts (metin), ServiceResult, CompletedBy (**ad metni**), WorkOrderId (unique) | Cihaz kütüğüne (`SecurityDeviceId`) bağ isteğe bağlı ve sıra numarasıyla eşleniyor. |
| `MaintenanceDeviceChecks` | `V18_DeviceWorkOrders.sql:30-46` | CheckCode, CheckLabel, CheckResult, CheckedBy (**ad metni**), CheckedAt | **Madde bazında not/ölçüm alanı yok**; her kayıtta üzerine yazılıyor (geçmiş yok). |
| `WorkTypeRules` (Planlı Bakım) | `V15_Schema.sql:136-144` | SerialRequiredOnClose=1 | |
| Seed | `DengeERP_V15_Seed.sql:~2340-2443` | 87 sözleşme MERGE | `WHEN MATCHED` tüm alanları ezip `IsActive=1` yapıyor (`:2437-2441`). |

Müşteri imzası/onayı, form PDF'i, uygunsuzluk aksiyonu, cihaz bakım geçmişi için **tablo yok**.

### 1.2 API uçları

| Uç | Satır | İzin | Ne yapar |
|---|---|---|---|
| `GET /api/maintenance/contracts` | `Program.cs:2288-2345` | maintenance.view **veya** workorders.view + birim "Güvenlik Sistemleri" | Aktif sözleşmeler + **yalnızca içinde bulunulan yılın** ilk açık planı (`:2309`). Ücret alanları `finance.prices.view` yoksa `null` (`:2329-2333`) — doğru. |
| `POST /api/maintenance/generate-due` | `:2347-2356` | maintenance.manage **veya** workorders.plan | Tüm sözleşmeler için plan + vadesi gelen PB iş emri üretir. Önizleme/log yok. |
| `GET /api/maintenance/plans/{planId}/devices` | `:2360-2376` | maintenance.view / workorders.view | Dönemin cihaz satırları + PB numaraları. |
| `POST /api/maintenance/plans/{planId}/devices/initialize` | `:2379-2400` | maintenance.manage | Eksik cihaz iş emirlerini tamamlar (idempotent). |
| `GET /api/maintenance/workorders/{id}/form` | `:2403-2443` | workorders.view / maintenance.view + `CanAccessWorkOrderAsync` | Form + kontrol maddeleri. |
| `POST /api/maintenance/workorders/{id}/form` | `:2445-2557` | workorders.close / maintenance.manage + erişim | Taslak / tamamla. Doğrulamalar: sonuç listesi (`:2457`), açık sayaç engeli (`:2496-2499`), seri/bölge/not/sonuç zorunlu (`:2500-2501`), "Bekliyor" madde kalmamalı (`:2502`), "Tamamlandı" için tüm maddeler Uygun (`:2503-2504`), dönem içi seri tekrarı (`:2505-2509`). Tamamlanmayan sonuç → iş emri **Beklemede** (`:2512`). Tüm cihazlar tamamlanınca dönem kapanır ve `CompletedCount` bir kez artar (`:2539-2551`). |
| `PATCH /api/workorders/{id}/status` | `:473-543` | — | Cihaz PB iş emri bu uçtan kapatılamaz (`:510-513`), kapalı PB tekrar açılamaz (`:500-503`). **Her kapanışta tüm sözleşmeler için üretim tetiklenir** (`:536-540`). |
| Başlangıçta üretim | `:26-34` | — | `RunDatabaseSetupOnStartup=true` ise seed + plan/iş emri üretimi çalışır. |

### 1.3 İş kuralları (motor)

- `EnsureMaintenancePlansAndWorkOrdersAsync` (`Program.cs:2894-2982`): her aktif sözleşme için **içinde bulunulan takvim yılı**na `AnnualFrequency` kadar plan yazar; hedef ay = `1 + floor((seq-1)*12/frekans)` ayının 1'i (`:2928-2930`); `seq <= CompletedCount` olan planları **tamamlandı** işaretler (`:2950`); sıradaki plan hedefi bugünden ileride değilse cihaz iş emirlerini üretir (`:2954-2978`). Hedef tarih her çalıştırmada yeniden yazılır (`:2940-2944`).
- `EnsureIndividualMaintenanceWorkOrdersAsync` (`:2986-3102`): `ProductsText` içinden regex ile X-Ray / kapı dedektörü adedi çıkarır (`:2990`); eşleşme yoksa **sessizce 0** döner (`:2999`); kütükten aynı `CustomerName` cihazlarını Id sırasıyla alıp **sıra numarasıyla** eşler (`:3010-3016`, `:3032`); her cihaz için `PB-{hedefYYYYMM}-####` iş emri açar, durum "Müşteri Talebi", oluşturan kullanıcı NULL (`:3076-3092`).
- Kontrol şablonu kodda sabit: X-Ray **11** madde, kapı dedektörü **10** madde (`:3105-3134`) — belgedeki karar ile uyumlu. Diğer cihaz türleri (el tipi, araç altı vb.) için şablon yok.
- `CompleteMaintenanceFromWorkOrderAsync` (`:3136-3175`): V1.7 "ana PB" mirası; cihaz bazlı akışta fiilen devre dışı.
- Teknisyen erişimi: rol adı "Teknisyen" ise yalnızca **ad metni** eşleşen atamalar (`:3385-3401`).
- Rapor ayrımı: `PB-` öneki veya WorkType "Planlı Bakım" (`:3638-3639`).

### 1.4 Ön yüz (`wwwroot/app.js`)

- Menü "Planlı Bakımlar" (`:190`), sözleşmeler `state.maintenanceContracts` (`:153`).
- `maintenancePage()` (`:660-669`): sözleşme tablosu, "Vadesi Gelen Cihaz İş Emirlerini Oluştur" butonu (`:664`, tetik `:1958`), KPI kutuları, ücret sütunu yalnızca `finance.prices.view` ile.
- `openMaintenanceDevices()` (`:567-596`): dönemin cihaz iş emirleri listesi, "Eksik cihaz iş emirlerini oluştur".
- `openMaintenanceForm()` (`:598-658`): seri no, bölge, adres (bilgi), kontrol listesi (Uygun onay kutusu + 4 durumlu seçim), "tümünü uygun işaretle" (onaylı), yapılan işlem, yedek parça (metin), teknisyen notu, servis sonucu, taslak/tamamla.
- İş emri detayından forma geçiş (`:1622`); takvimde aynı lokasyon tek ziyaret kartı (`:463-477`).
- Yazdırma/PDF, müşteri onayı, imza, fotoğraf: **yok**.

### 1.5 İzinler

`maintenance.view`, `maintenance.manage` (`Program.cs:3907-3908`). Şef: view+manage (`:3929`); Teknisyen: maintenance izni yok, formu `workorders.close` ile kaydeder; Operasyon Uzmanı ve Genel Koordinatör: view.

---

## 2. Olması gereken (hedef tasarım)

### 2.1 Roller ve sorumluluklar [V]

| Rol | Bu modüldeki işi | İzin (mevcut / **öneri**) |
|---|---|---|
| Teknik Servis Müdürü / Yardımcısı | Sözleşmeyi aktif/pasif yapar, aylık bakım uyum raporunu izler, kapalı formu gerekçeli yeniden açmayı onaylar | maintenance.manage, **maintenance.contracts.manage**, **maintenance.reopen**, reports.view |
| Güvenlik Sistemleri Şefi | Vadesi gelen bakımları üretir/önizler, aynı lokasyonu toplu planlar, uygunsuzluk aksiyonlarına sorumlu atar, cihaz kapsam dışı bırakma talebini onaylar | maintenance.view/manage, workorders.plan/assign |
| Teknisyen | Atandığı PB iş emrinde formu doldurur, müşteri onayını alır, uygunsuzluğu kaydeder | workorders.view/close (yalnızca kendi işleri) |
| Operasyon Uzmanı | Müşteri randevusu, saha irtibatı, uygunsuzluktan doğan teklif talebini başlatır | maintenance.view, offers.create |
| Depo | Bakımda kullanılan parçanın stok çıkışını onaylar | warehouse.manage |
| Üst yönetim | Sözleşme yerine getirme oranı, geciken bakım, tekrar eden uygunsuzluk | reports.view |

### 2.2 Tutulması gereken veriler

1. **Sözleşme:** müşteri, saha/lokasyon, başlangıç–bitiş tarihi, yıllık bakım adedi, (isteğe bağlı) sabit bakım ayları, cihaz kapsamı (kütükten cihaz listesi veya tür+adet), sorumlu şef, durum (Taslak/Aktif/Pasif/Süresi Doldu), ücret alanları (yalnızca `finance.prices.view`).
2. **Bakım dönemi:** sözleşme dönemi içindeki sıra no, hedef tarih, tolerans penceresi, üretilme zamanı/üreten, kapanış zamanı, kapanış türü (Tamamlandı / Kısmi – kapsam dışı cihaz var).
3. **Cihaz bakım kaydı (PB iş emri):** kütükteki cihaza **kimlikle** bağlı; seri no, bölge, kontrol sonuçları + madde notu, yapılan işlem, parça, sonuç, başlangıç/bitiş (zaman kayıtlarından), müşteri onayı.
4. **Ziyaret anlık görüntüsü:** her "tamamla" denemesinde kontrol sonuçlarının değişmez kopyası (ilk ziyarette uygunsuz → ikinci ziyarette uygun izi kaybolmamalı).
5. **Uygunsuzluk aksiyonu:** kaynak madde, açıklama, aksiyon türü, sorumlu, hedef tarih, bağlı iş emri/teklif, kapanış kanıtı.
6. **Müşteri onayı:** onaylayan ad-soyad, unvan, zaman (sunucu), yöntem (ekranda imza / imzalı kağıt form fotoğrafı / imzadan imtina + gerekçe), imza görseli.

### 2.3 Durum akışı (cihaz PB iş emri)

```text
Müşteri Talebi (üretildi) → Planlandı → Sahada
   → [Form tamamla]
       ├─ tüm maddeler Uygun + müşteri onayı → Kapatıldı (cihaz Tamamlandı)
       ├─ Uygunsuz / Kontrol Edilemedi var   → Beklemede (aksiyon açık) → aksiyonlar kapanınca yeniden kontrol → Kapatıldı
       └─ cihaz yok / sökülmüş / erişim verilmedi → "Kapsam Dışı" talebi → Şef onayı → dönemden düşülür (raporda ayrı)
Bakım dönemi: tüm cihazlar Tamamlandı veya onaylı Kapsam Dışı ⇒ dönem kapanır (bir kez sayılır)
```

### 2.4 Doğrulamalar

- Tamamlama: seri no, bölge, not, sonuç, tüm maddeler değerlendirilmiş (mevcut) **+** Uygunsuz/Kontrol Edilemedi maddelerde açıklama zorunlu **+** müşteri onay bloğu dolu (veya imtina gerekçesi) **+** açık sayaç yok (mevcut).
- Seri no metin, baştaki sıfırlar korunur; aynı seri aynı dönemde iki cihazda olamaz (mevcut) ve kütükte başka müşteride aktifse uyarı verilir.
- Süre kaydı yoksa kapanış engellenmez ama formda ve raporda **"süre kaydı eksik"** yazar; tahmini süre gösterilmez.
- Kapalı form değiştirilemez; yalnızca `maintenance.reopen` sahibi gerekçe yazarak açar, işlem iz kaydına düşer.

### 2.5 Raporlar / KPI

| KPI | Tanım |
|---|---|
| Bakım uyum oranı | Hedef tarih + tolerans içinde kapanan dönem / vadesi gelen dönem (ay, şef, müşteri kırılımı) |
| Geciken bakım listesi | Hedef tarihi geçmiş, kapanmamış dönemler; gecikme günü, açık cihaz sayısı |
| Sözleşme yerine getirme | Sözleşme dönemi içinde yapılan / taahhüt edilen bakım adedi |
| Uygunsuzluk oranı | Uygunsuz madde içeren cihaz formu / toplam form; en sık uygunsuz maddeler |
| Açık aksiyon yaşı | Açık uygunsuzluk aksiyonlarının gün dağılımı, sorumluya göre |
| Onaysız kapanış | Müşteri onayı imtina ile kapanan form sayısı |
| Süre kaydı eksik PB | Zaman kaydı olmayan kapalı PB iş emri sayısı |

---

## 3. Fark listesi (mevcut → olması gereken)

Sıralama: önce **KRİTİK** veri maddeleri (öncelikten bağımsız), ardından kullanıcı önceliği c → b → a.

### KRİTİK

#### M04-01 · VERİ/HATA · KRİTİK — Yıl devrinde bakım dönemleri yanlışlıkla "tamamlandı" sayılıyor
- **Mevcut:** `CompletedCount` yıl bilgisi taşımıyor (`V15_Schema.sql:44`) ve sıfırlanmıyor. Plan üretimi `DateTime.Today.Year` ile yeni yıl planı açarken `seq <= CompletedCount` olanları doğrudan tamamlandı yazıyor (`Program.cs:2897-2898, 2924, 2950`). Sözleşme ekranı yalnızca içinde bulunulan yılın planlarını gösteriyor (`:2309`).
- **Sonuç:** 1 Ocak 2027'den sonraki ilk çalıştırmada, 2026'da 3/3 bakımı yapılmış sözleşmenin 2027 bakımlarının **tamamı** tamamlandı işaretlenir, hiç iş emri üretilmez; 2026'dan açık kalan dönem ve PB'ler bakım ekranından kaybolur. Bu, sessiz taahhüt kaybıdır.
- **Olması gereken:** Tamamlanan adet `MaintenancePlans` üzerinden **sözleşme dönemi** bazında hesaplanmalı; `CompletedCount` yalnızca ilk aktarım için "başlangıç değeri" olarak kullanılmalı; önceki yıldan açık kalan dönemler listede kalmalı.
- **Kabul:** (1) Test DB'de sistem tarihi 02.01.2027 iken üretim çalıştırıldığında, 2026'da 3/3 tamamlanmış bir sözleşmenin 2027 planlarının hiçbiri `IsCompleted=1` olmaz. (2) 2026'dan açık kalan bir dönem 2027'de sözleşme ekranında "gecikmiş" olarak görünür. (3) Aynı üretim iki kez çalıştırıldığında yeni iş emri sayısı ikinci seferde 0'dır.
- **Efor:** M

#### M04-02 · VERİ · KRİTİK — Ürün metni ayrıştırılamayan sözleşmeler sessizce bakım üretmiyor
- **Mevcut:** Cihaz adedi `ProductsText` regex'i ile çıkarılıyor (`Program.cs:2990`), eşleşme yoksa uyarısız `return 0` (`:2999`). Seed'de örnekler: BAKIM-0088 KENTPARK "11 X-RAY 8 KAPI DEDEKTÖÜ" (yazım hatası → **8 kapı dedektörü için hiç PB açılmaz**), BAKIM-0085 Ziraat Bankası (alanlar kaymış, frekans 0), BAKIM-0086 Sanko (frekans 0) (`DengeERP_V15_Seed.sql` ilgili satırlar). Frekansı 0 olanlar `AnnualFrequency>0` filtresiyle hiç görünmüyor (`:2907`).
- **Olması gereken:** Üretim, oluşturamadığı her sözleşme için gerekçeli bir **"Üretilemeyen sözleşmeler"** listesi döndürmeli ve ekranda göstermeli; regex sonucu ile metindeki toplam adet karşılaştırılmalı. Kalıcı çözüm M04-03'teki yapısal cihaz kapsamıdır.
- **Kabul:** (1) `generate-due` yanıtı `{generated, skipped:[{contract, reason}]}` içerir; KENTPARK "kapı dedektörü adedi okunamadı", Ziraat/Sanko "bakım frekansı tanımsız" gerekçesiyle listelenir. (2) Bakım sayfasında bu sözleşmeler kırmızı uyarıyla görünür. (3) Veri düzeltilince ikinci üretimde KENTPARK için 8 yeni PB açılır, mevcut 11 X-Ray PB tekrar açılmaz.
- **Efor:** S

### (c) Yeni modül / özellikler

#### M04-03 · YENİ — Bakım sözleşmesi yönetimi (ekle / düzenle / pasifle, yapısal cihaz kapsamı)
- **Mevcut:** Sözleşmeler yalnızca seed SQL ile geliyor; ekranda düzenleme yok. Başlangıç/bitiş tarihi serbest metin (`PeriodText`), cihaz kapsamı serbest metin. Seed MERGE her kurulum çalıştırmasında alanları ezip `IsActive=1` yapıyor (`DengeERP_V15_Seed.sql:2437-2441`) — ekrandan yapılacak değişiklikleri geri alır, pasif sözleşmeyi yeniden aktif eder.
- **Olması gereken:** `maintenance.contracts.manage` [öneri] ile sözleşme CRUD: müşteri, saha adresi, başlangıç/bitiş tarihi, yıllık adet, isteğe bağlı sabit aylar ("5. ve 11. ay"), sorumlu şef, durum. Cihaz kapsamı: kütükten (`SecurityDevices`) cihaz seçimi veya tür+adet satırı (X-Ray, Kapı Tipi Metal Dedektörü, Diğer). Ücret alanları yalnızca `finance.prices.view` ile görünür/düzenlenir. Seed MERGE'ün `WHEN MATCHED` kısmı yalnızca kaynağı seed olan ve ekrandan hiç düzenlenmemiş kayıtları güncelleyecek şekilde sınırlanır.
- **Kabul:** (1) Yeni sözleşme 2 X-Ray + 3 kapı ile kaydedilip üretim çalıştırılınca 5 PB oluşur. (2) Ekrandan pasiflenen sözleşme, `RunDatabaseSetupOnStartup=true` ile yeniden başlatmadan sonra pasif kalır. (3) `finance.prices.view` olmayan kullanıcının API yanıtında ücret alanları `null`dır ve ücret gönderse bile kaydedilmez (403 veya yok sayma). (4) Bitiş tarihi geçmiş sözleşme için yeni dönem üretilmez.
- **Efor:** L

#### M04-04 · YENİ — Sözleşme dönemine dayalı plan takvimi ve önizlemeli üretim
- **Mevcut:** Hedef tarih ocaktan başlayan eşit aralıklı ay başları (`Program.cs:2928-2930`), sözleşme başlangıcı yok sayılıyor (ör. İstanbul Optimum 01.06.2026 başlangıçlı, ilk hedef Ocak 2026 hesaplanıyor). Hedef tarih her çalıştırmada yeniden yazılıyor (`:2940-2944`), elle değiştirilemez. Üretim önizlemesiz; her iş emri kapanışında tüm sözleşmeler için tetikleniyor (`:536-540`); kimin ne ürettiği kaydedilmiyor, iş emri `CreatedByUserId` NULL (`:3086`).
- **Olması gereken:** Hedef tarihler sözleşme başlangıcından (veya sabit aylardan) hesaplanır; şef hedef tarihi gerekçeyle değiştirebilir ve değişiklik korunur. "Vadesi gelenleri üret" önce **önizleme** gösterir (sözleşme, dönem, cihaz sayısı, PB sayısı), onayla üretir; üretim kaydı (kim, ne zaman, kaç) tutulur. Üretim, hedef tarihten **N gün önce** (öneri 30) açılır. İş emri kapanışındaki otomatik global üretim kaldırılır (veya yalnızca ilgili sözleşmeye daraltılır).
- **Kabul:** (1) 01.06.2026 başlangıçlı, yılda 3 bakımlı sözleşmenin hedefleri Haz/Eki 2026 ve Şub 2027 olur. (2) Şefin Eki → Kas olarak değiştirdiği hedef, uygulama yeniden başlatılınca ve üretim tekrar çalışınca Kas kalır. (3) Önizleme çağrısı veritabanında hiçbir satır oluşturmaz. (4) Normal bir arıza iş emri kapatıldığında yeni PB oluşmaz. (5) Üretilen PB'lerin oluşturan kullanıcısı üretimi onaylayan kişidir.
- **Bağımlılık:** M04-01, M04-03
- **Efor:** M

#### M04-05 · YENİ — Uygunsuzluk aksiyon takibi
- **Mevcut:** Uygunsuz/Kontrol Edilemedi madde varsa sonuç "Tamamlandı" seçilemiyor ve iş emri Beklemede kalıyor (`Program.cs:2503-2504, 2512`) — karar ile uyumlu. Ancak maddeye açıklama yazılamıyor (`MaintenanceDeviceChecks` tablosunda not kolonu yok), sorumlu/hedef tarih yok, teklif veya arıza iş emrine bağ yok; Beklemede iş emrinin neden beklediği yalnızca genel nottan anlaşılıyor.
- **Olması gereken:** Uygunsuz veya Kontrol Edilemedi her madde için açıklama zorunlu. Form tamamlanınca her biri için otomatik bir **aksiyon kaydı** açılır: aksiyon türü (yerinde giderildi / parça bekleniyor / teklif sunulacak / arıza iş emri açılacak / müşteri kaynaklı – müşteriye bildirildi), sorumlu (şef atar), hedef tarih, bağlı iş emri veya teklif no, kapanış notu. "Arıza iş emri açılacak" seçilirse aynı cihaz/seri ile bağlı günlük servis iş emri açılır. Aksiyonlar kapanınca teknisyen PB formunda ilgili maddeleri yeniden değerlendirir ve kapatır. Mevcut bekleme nedeni altyapısı (`OpsSuite.cs:130`) "Uygunsuzluk aksiyonu" nedeniyle beslenir.
- **Kabul:** (1) Bir maddesi Uygunsuz ve açıklaması boş form 400 döner. (2) 2 uygunsuz maddeli form tamamlanınca 2 açık aksiyon oluşur, iş emri Beklemede olur ve bekleme nedeni görünür. (3) "Arıza iş emri açılacak" aksiyonu aynı seri no ile bağlı yeni bir servis iş emri oluşturur ve PB formundan bu iş emrine gidilebilir. (4) Açık aksiyon varken PB "Tamamlandı" ile kapatılamaz. (5) Açık aksiyonlar listesi sorumlu ve gün yaşı ile filtrelenebilir.
- **Bağımlılık:** M04-08 (ziyaret geçmişi)
- **Efor:** M

#### M04-06 · YENİ — Müşteri onayı ve imza
- **Mevcut:** Formda müşteri onayı/imza alanı ve tablosu yok (`app.js:604-630`, `V18_DeviceWorkOrders.sql`). Basılı formdaki "onay" bölümünün dijital karşılığı yok.
- **Olması gereken:** Form tamamlanırken onay bloğu: onaylayan ad-soyad, unvan, yöntem (ekranda parmakla imza / imzalı basılı formun fotoğrafı / müşteri imzadan imtina etti + gerekçe), zaman damgası sunucudan. Aynı ziyaretteki birden çok cihaz formu **tek imzayla** onaylanabilir (aynı müşteri + lokasyon + gün; takvimdeki tek ziyaret kartıyla uyumlu). İmza görseli kişisel veri sayılır; yalnızca iş emrini görme yetkisi olanlar görür.
- **Kabul:** (1) Onay bloğu boşken "Tamamla" 400 döner. (2) 17 cihazlık ziyarette tek imza 17 forma bağlanır ve her formun PDF'inde görünür. (3) İmtina seçildiğinde gerekçe zorunludur ve raporda "onaysız kapanış" olarak sayılır. (4) İmza zamanı istemci saatinden değil sunucudan gelir. (5) Atanmamış teknisyen başka işin imza görselini API'den alamaz (403).
- **Efor:** M

#### M04-07 · YENİ — Basılı Teknik Servis Formu eşlemesi ve PDF çıktısı
- **Mevcut:** Basılı form alanlarının dijital karşılıkları kısmen var; başlangıç/bitiş saati, servis türü, onay yok; çıktı alınamıyor. Teklif için hazır basit PDF üretimi var (`Program.cs:883-892`, `BuildSimpleOfferPdf`).

| Basılı form alanı | Dijital karşılık | Durum |
|---|---|---|
| Firma / adres | WorkOrders.CustomerName, MaintenanceContracts.CurrentAddress | Var |
| Başlangıç / bitiş saati | — (`WorkOrderLiveSessions` / zaman kayıtlarından türetilmeli) | **Yok** |
| Servis türü | WorkType "Planlı Bakım" | Var, formda gösterilmiyor |
| Ürün / marka-model / seri no | DeviceType, SecurityDevices.Brand/Model, SerialNo | Var |
| Kullanılan parçalar | SpareParts (serbest metin) | Kısmen (M04-10) |
| Yapılan işlem | PerformedWork | Var |
| Sonuç | ServiceResult | Var |
| Onay / imza | — | **Yok** (M04-06) |

- **Olması gereken:** `GET /api/maintenance/workorders/{id}/form.pdf` ve ziyaret bazında toplu PDF. Başlangıç/bitiş saatleri o iş emrinin gerçek zaman kayıtlarından alınır; kayıt yoksa **"süre kaydı eksik"** yazılır (tahmini süre veya 0 yazılmaz). Fiyat/maliyet alanı PDF'e girmez.
- **Kabul:** (1) Kapalı bir PB için PDF; firma, adres, cihaz, seri, bölge, 11/10 kontrol sonucu, yapılan işlem, parçalar, sonuç, teknisyen(ler), başlangıç/bitiş ve imzayı içerir. (2) Zaman kaydı olmayan iş emrinin PDF'inde saat alanında "süre kaydı eksik" yazar. (3) PDF ucu form ucu ile aynı yetki ve erişim kontrolünü uygular. (4) Basılı formdaki her alan eşleme tablosunda karşılığı ile işaretlenmiş olarak kullanıcıya onaylatılır.
- **Bağımlılık:** M04-06; basılı formun güncel örneği (Soru S5)
- **Efor:** M

### (b) Mevcut modülün eksikleri

#### M04-08 · VERİ/EKSİK — Ziyaret geçmişi: kontrol sonuçlarının üzerine yazılması
- **Mevcut:** Her kayıtta `MaintenanceDeviceChecks` satırları güncelleniyor (`Program.cs:2481-2493`); ilk ziyarette Uygunsuz bulunan maddenin, ikinci ziyarette Uygun yapılınca izi kalmıyor. `CheckedBy`/`CompletedBy` ad metni (`:2484, 2516`).
- **Olması gereken:** Her "tamamla" denemesi (sonuç ne olursa olsun) değişmez bir **ziyaret kaydı** oluşturur: ziyaret no, tarih, teknisyen kullanıcı kimliği, madde sonuçları ve notlarının kopyası, sonuç. Form ekranı ziyaret geçmişini gösterir.
- **Kabul:** (1) Uygunsuz ile kaydedilen, sonra Uygun ile kapatılan cihazda 2 ziyaret kaydı bulunur ve ilki Uygunsuz sonucunu korur. (2) Ziyaret kayıtları API'de güncellenemez/silinemez. (3) Ziyaret kaydındaki teknisyen, kullanıcı kimliği (UserId) ile tutulur.
- **Efor:** M

#### M04-09 · EKSİK — Cihaz kütüğüne bağlama ve cihaz bakım geçmişi
- **Mevcut:** PB satırı kütükteki cihaza, aynı müşteri adının Id sıralı listesindeki **sıra numarasıyla** eşleniyor (`Program.cs:3010-3016, 3032`); teknisyenin girdiği seri/bölge kütüğe yazılmıyor ve sonraki dönemde yine kütükten (boş/eski) geliyor. Cihaz geçmişi ucu yok (yalnızca liste `:2232`).
- **Olması gereken:** Formda girilen seri no kütükte aranır: bulunursa `SecurityDeviceId` bağlanır; bulunamazsa "kütüğe yeni cihaz olarak ekle" önerisi (şef onayıyla). Onaylı seri/bölge kütüğe yazılır; sonraki dönemin PB'si sıra numarasıyla değil **cihaz kimliğiyle** üretilir. Cihaz kartında: tüm PB'ler, ziyaret sonuçları, açık aksiyonlar, bağlı arıza iş emirleri.
- **Kabul:** (1) 1. dönemde seri "00A-123/4" girilip kapanan cihaz, 2. dönemde aynı seri ve bölgeyle önceden dolu gelir; baştaki sıfırlar korunur. (2) Kütüğe yeni bir cihaz eklenmesi önceki dönem eşleşmelerini değiştirmez. (3) `GET /api/security/devices/{id}/history` cihazın PB ve servis kayıtlarını tarih sırasıyla döner, birim yetkisi uygulanır. (4) Kütükte başka müşteride aktif bir seri girildiğinde uyarı gösterilir.
- **Efor:** M

#### M04-10 · EKSİK — Cihazın dönem dışı bırakılması (sökülmüş / erişim yok / müşteri iptali)
- **Mevcut:** Sonuç "Servis İptal" seçilince iş emri Beklemede, cihaz Bekliyor kalıyor (`Program.cs:2457, 2511-2512`); dönem ancak tüm cihazlar Tamamlandı olunca kapanıyor (`:2539-2541`). Sökülmüş bir cihaz yüzünden dönem ve sözleşme sayacı sonsuza kadar açık kalır.
- **Olması gereken:** Teknisyen "Kapsam dışı / yapılamadı" talebini gerekçe türüyle (cihaz sökülmüş, müşteri erişim vermedi, cihaz başka yere taşınmış, müşteri iptal etti) açar; şef onaylarsa cihaz o dönemden düşülür, dönem diğer cihazlar tamamlanınca **"Kısmi"** olarak kapanır; "cihaz sökülmüş" onayında kütükte cihaz pasiflenmesi önerilir.
- **Kabul:** (1) 3 cihazlı dönemde 2 cihaz Tamamlandı + 1 cihaz onaylı kapsam dışı olunca dönem kapanır ve sayaç bir kez artar. (2) Onaylanmamış talep dönemi kapatmaz. (3) Raporda kısmi dönem ve kapsam dışı cihaz gerekçesiyle ayrı görünür. (4) Talebi açan kişi kendi talebini onaylayamaz.
- **Efor:** S

#### M04-11 · EKSİK — Yedek parçanın stok kaydına bağlanması
- **Mevcut:** Formda parça serbest metin (`V18_DeviceWorkOrders.sql:12-13`, `app.js:623`); V1.20 stok modülünde iş emrine bağlı çıkış var ama yalnızca `warehouse.manage` ile (`OpsSuite.cs:188-213`), teknisyen kullanamıyor.
- **Olması gereken:** Formda parça katalogdan seçilir (adet ile); serbest metin "katalogda yok" durumu için kalır. Seçilen satırlar **parça kullanım talebi** olarak depoya düşer, depo onaylayınca mevcut stok hareketi ucu ile çıkış yapılır. Maliyet/fiyat teknisyene gösterilmez.
- **Kabul:** (1) Teknisyen formda 2 adet katalog parçası seçip kaydedince depo ekranında bekleyen talep görünür, stok değişmez. (2) Depo onayından sonra stok 2 azalır ve hareket PB iş emrine bağlıdır. (3) Teknisyenin form API yanıtında birim maliyet alanı yoktur. (4) Stok yetersizse onay reddedilir, form kapanışı engellenmez ama "parça stok çıkışı bekliyor" uyarısı kalır.
- **Efor:** M

#### M04-12 · EKSİK — Planlı bakım KPI'ları ve rapor sayfası
- **Mevcut:** Bakım sayfasında sözleşme sayısı, vadesi gelen, açık/tamamlanan PB (`app.js:665`); Excel'de "Planlı Bakım" sayfası iş emri listesi düzeyinde (`Program.cs:3648-3692`). Uyum oranı, gecikme günü, uygunsuzluk oranı yok.
- **Olması gereken:** §2.5'teki KPI'lar bakım ekranında (tıklanabilir kutular, mevcut KPI desenine uygun) ve Excel "Planlı Bakım" sayfasında; ay/şef/müşteri filtresi. Süre kaydı olmayan PB'ler "süre kaydı eksik" sayılır, 0 saat yazılmaz.
- **Kabul:** (1) Örnek veride 10 vadesi gelen dönemin 7'si tolerans içinde kapandıysa uyum oranı %70 görünür ve kutuya tıklayınca 3 geciken dönem listelenir. (2) Excel'de uygunsuzluk oranı ve en sık 5 uygunsuz madde vardır. (3) Zaman kaydı olmayan kapalı PB sayısı ayrı satırdadır. (4) Ücret/maliyet içeren hiçbir alan `finance.prices.view` olmadan raporda yer almaz.
- **Bağımlılık:** M04-01, M04-04, M04-05
- **Efor:** M

#### M04-13 · EKSİK — Diğer güvenlik cihazı türleri için kontrol şablonu
- **Mevcut:** Şablon kodda sabit ve yalnızca X-Ray (11) ile kapı dedektörü (10) (`Program.cs:3105-3134`); regex yalnızca bu iki türü tanıyor (`:2990`). El tipi dedektör, araç altı arama vb. sözleşmede olsa bile PB üretilmiyor.
- **Olması gereken:** Şablonlar tabloya taşınır (tür, madde kodu, metin, sıra, sürüm); mevcut 11/10 madde aynen veri olarak aktarılır. Yeni tür için şablon `maintenance.manage` ile eklenir; mevcut formlar oluşturuldukları sürümü korur. Şablonu olmayan tür için PB üretilmez ve M04-02 listesinde "şablon yok" olarak görünür.
- **Kabul:** (1) Taşıma sonrası yeni X-Ray formunda aynı 11 madde, kapıda aynı 10 madde çıkar. (2) Bir maddenin metni değiştirildiğinde önceden açılmış formların madde metni değişmez. (3) "El Tipi Dedektör" şablonu eklenip sözleşmeye 2 adet eklenince 2 PB üretilir.
- **Efor:** M

### (a) Güvenlik / üretime hazırlık

#### M04-14 · GÜVENLİK — Form kayıtlarında kimlik, kapalı formun gerekçeli yeniden açılması
- **Mevcut:** `CheckedBy`, `CompletedBy` ve teknisyen erişimi **ad metniyle** (`Program.cs:2488, 2530, 3398-3400`); aynı adlı iki kişi birbirinin formunu görebilir/kaydedebilir, ad değişince geçmiş kopar. Rol adı tam "Teknisyen" değilse (ör. kişiye özel rol) erişim kısıtı tamamen kalkıyor (`:3398`). Kapalı form hiçbir yoldan açılamıyor (`:2473`) — hatalı kapanış ancak SQL ile düzeltilebilir, bu da iz bırakmaz. `GET /api/maintenance/contracts` yalnızca `workorders.view` olan teknisyene de tüm müşteri/adres listesini veriyor (`:2292`).
- **Olması gereken:** Kontrol, tamamlama, imza ve ziyaret kayıtları kullanıcı kimliği (UserId) ile; ad yalnızca gösterim. Teknisyen kısıtı rol adına değil "yalnızca kendi işleri" iznine/bayrağına dayanır. `maintenance.reopen` [öneri] ile gerekçeli yeniden açma; önceki hali ziyaret kaydında korunur, durum geçmişine yazılır. Sözleşme listesi `maintenance.view` gerektirir.
- **Kabul:** (1) Aynı ad soyadlı iki teknisyen hesabından, atanmamış olan form uçlarından 403 alır. (2) Rol adı "Teknisyen (Kıdemli)" olan ama kısıt bayrağı açık kullanıcı yalnızca kendi işlerini görür. (3) `maintenance.reopen` olmayan kullanıcı kapalı formu açamaz; olan kullanıcı gerekçesiz açamaz; açma işlemi geçmişte kim/ne zaman/gerekçe ile görünür. (4) Yalnızca `workorders.view` sahibi `GET /api/maintenance/contracts` çağrısında 403 alır.
- **Efor:** M

---

## 4. Kapsam dışı bırakılanlar (bilinçli)

- Logo CRM / Flowick entegrasyonu (kullanıcı kararı).
- Otomatik e-posta/SMS ile müşteriye form gönderimi (genel bildirim altyapısı yok; ayrı modül).
- Çevrimdışı form doldurma (mobil modülün konusu).
- Bakım ücretinin faturalanması / muhasebe.
- Fotoğraf yükleme genel altyapısı: yalnızca M04-06'daki imzalı form fotoğrafı için gerekli; genel kanıt fotoğrafı istenirse ayrı madde açılır (Soru S6).

## 5. Varsayımlar

1. Rol dağılımları (§2.1) organizasyon şeması gelene kadar varsayımdır.
2. Planlı bakım yalnızca Güvenlik Sistemleri biriminde yürür (kod da bunu sabitliyor).
3. Sözleşme dönemi = sözleşme başlangıç–bitiş tarihi; takvim yılı değil.
4. Üretim tolerans ve ön açılış süresi için 30 gün varsayılmıştır; kullanıcı onayı gerekir.
5. Aynı ziyaretteki birden çok cihaz için tek müşteri imzası kabul edilebilir.
6. İmza görseli KVKK kapsamında kişisel veridir; saklama süresi şirket politikasıyla belirlenecektir.
7. X-Ray 11 / kapı 10 madde metinleri koddaki haliyle doğru kabul edilmiştir; basılı form karşılaştırması sonrası değişebilir.

## 6. Kullanıcıya sorular

- **S1.** Uygunsuzluk bulunan ama bakımı fiilen yapılmış cihazda, **sözleşme bakım dönemi** "yapıldı" sayılsın mı (müşteriye karşı taahhüt yerine getirildi), yoksa uygunsuzluk aksiyonu kapanana kadar dönem açık mı kalsın? (Şu an açık kalıyor.)
- **S2.** Müşteri imzası her PB kapanışında **zorunlu** mu? İmza yerine imzalı kağıt formun fotoğrafı ya da "müşteri imzadan imtina etti" ile kapanmaya izin verilsin mi?
- **S3.** Bir ziyarette 17 cihaz bakımı yapıldığında müşteri **tek imza** atsın mı, yoksa her cihaz formu ayrı imzalansın mı?
- **S4.** Bakım hedef tarihleri sözleşme başlangıcından eşit aralıkla mı hesaplansın, yoksa müşteriyle belirli aylar mı kararlaştırılıyor? Hedef tarihten kaç gün önce iş emri açılsın, kaç gün gecikme "geç" sayılsın?
- **S5.** Güncel **basılı Teknik Servis Formu** örneğini (tarama/fotoğraf) paylaşabilir misiniz? PDF çıktısının o formla birebir aynı düzende olması gerekiyor mu, yoksa alanların bulunması yeterli mi?
- **S6.** X-Ray ve kapı dedektörü kontrol maddeleri (11/10) son hali mi? Radyasyon kaçak ölçümü gibi **ölçüm değeri** kaydedilmesi gereken maddeler var mı? Formda fotoğraf kanıtı istiyor musunuz?
- **S7.** El tipi dedektör, araç altı arama aynası vb. başka cihaz türleri için de bakım sözleşmesi var mı?
- **S8.** Sözleşme ekleme/düzenleme ve pasifleme yetkisi kimde olmalı (Teknik Servis Müdürü, Şef, Satış/Operasyon)?
- **S9.** Mevcut 87 sözleşmenin başlangıç/bitiş tarihleri ve cihaz adetleri güncel mi? KENTPARK (8 kapı dedektörü okunamıyor), Ziraat Bankası ve Sanko kayıtlarının doğru değerlerini kim teyit edecek?
- **S10.** Bakımda kullanılan parçanın stoktan düşmesi depo onayıyla mı olmalı, yoksa teknisyenin girişi doğrudan stoktan düşsün mü?
