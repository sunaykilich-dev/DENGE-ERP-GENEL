# M05 — Haberleşme Atölyesi: Gereksinim Tasarımı

> **Tarih:** 21 Ekim 2026 · **Sürüm tabanı:** V1.20.1 (salt okunur kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Kapsam:** Telsiz/haberleşme cihazlarının atölyeye kabulü, arıza teşhisi, onarım, test, teslim/kargo, aksesuar, garanti, iş emri bağlantısı ve atölye durum akışı.
> **Öncelik sırası (kullanıcı kararı):** (c) yeni özellik → (b) mevcut eksik/hata → (a) güvenlik/üretime hazırlık. Veri sızıntısı yaratan açık **KRİTİK** olarak işaretlenmiştir.
> **Kapsam dışı:** Logo CRM / Flowick entegrasyonu. Mevcut "Logo Form No" alanları yalnızca serbest metin olarak korunur.

---

## 1. Kodda mevcut durum

### 1.1 Veri modeli

| Öğe | Konum | Not |
|---|---|---|
| `dbo.WorkshopTickets` (41 kolon) | `Database/DengeERP_V15_Schema.sql:78-127` | Tek düz tablo. Firma/kişi/telefon/e-posta, giriş/tahmini bitiş/tamamlanma tarihi, servis türü, durum, `RepairAmount`, teslim alma/etme tipi, teslim alan/eden, kargo takip no, `AssignedTo` (isim metni), marka/model/seri, garanti başlangıç/bitiş/durum (metin), `Accessory1..5`, notlar, şikâyet, cihaz durumu, onarım bilgisi. |
| FK | `V15_Schema.sql:124-125` | `WorkOrderId → WorkOrders`, `CreatedByUserId → ErpUsers`. |
| İndeks | `V15_Schema.sql:130-131` | `IX_WorkshopTickets_Status (Status, EntryDate DESC)`. |
| Yetki dağıtımı | `V15_Schema.sql:162-170` | `workshop.view` 7 role, `workshop.manage` 5 role (Teknisyen dahil). |
| İş türü kuralı | `Database/DengeERP_Update.sql:126`, `Program.cs:3380-3382` | "Atölye" içeren iş türlerinde seri no açılışta ve kapanışta zorunlu (kural tablosunda yoksa varsayılan). |

Ayrı durum geçmişi, teşhis, aksesuar satırı, ek/fotoğraf, teslim tutanağı tablosu **yok**.

### 1.2 API uçları (`Program.cs`)

| Uç | Satır | Davranış |
|---|---|---|
| `GET /api/workshop/tickets` | 2560-2626 | `workshop.view` **veya** `workorders.view` + Haberleşme birimi. **Tüm** kayıtları döndürür (filtre, sayfalama, teknisyen kısıtı yok). `repairAmount` **fiyat izni kontrol edilmeden** döner (2599). |
| `POST /api/workshop/tickets` | 2628-2705 | `workshop.manage` **veya** `workorders.create`. Firma, servis türü, marka, seri no zorunlu. Tek transaction: `SRV-YYYYMM-####` iş emri (`WorkType='Atölye Teknik Servis'`, `Status='Atölyede'`) + `WorkOrderDevices` satırı + `AT-YYYYMM-####` atölye kaydı + durum logu. |
| `PUT /api/workshop/tickets/{id}` | 2707-2776 | `workshop.manage` **veya** `workorders.edit`. Tüm alanları ezer. Atölye durumu → iş emri durumu eşlemesi (2746-2755): Yeni Kayıt→Atölyede, Onarımda→İşlemde, Beklemede→Beklemede, Test / Kontrol→Test / Kontrol, Tamamlandı→Tamamlandı, Teslim Edildi→**Kapatıldı**, diğer (İptal dahil)→Atölyede. Durum logu **yazılmaz**. |
| Parametre bağlama | 2847-2892 | `EntryDate` boşsa `DateTime.Now` (2863). Liste değerleri sunucuda doğrulanmaz. |
| İstek kaydı | 3854-3862 | `WorkshopTicketRequest`. |
| İzin tanımları | 3909-3910, 3927-3930 | `workshop.view`, `workshop.manage`; rol şablonları. |

Atölye ile ilişkili diğer mevcut altyapılar:
- İş emri durum değiştirme `PATCH /api/workorders/{id}/status` (`Program.cs:473-543`): açık sayaç, seri no ve bakım kontrollerini yapar; **atölye kaydını güncellemez**.
- Canlı sayaç `POST /api/workorders/{id}/live-timer/start` (`Program.cs:1929`), "Atölye" ve "Test / Kontrol" faaliyetleri var; erişim `CanAccessWorkOrderAsync` (`Program.cs:3385-3400`) ile teknisyenin `WorkOrderAssignments` kaydına bağlı.
- Teknisyen iş emri filtresi `FilterWorkOrdersForUser` (`Program.cs:3495-3502`): teknisyen yalnızca `AssignedStaff` içinde adı geçen işleri görür.
- Bekletme/geri alma `OpsSuite.cs:130-159`, parça çıkışı `OpsSuite.cs:188-213` (iş emrine bağlı, negatif stok engeli). Parça maliyeti `finance.prices.view` ile gizleniyor (`OpsSuite.cs:173`).
- Teklif modülünde `WorkOrderId` bağlantısı ve PDF üretimi (`Program.cs:883-892`).

### 1.3 Ön yüz (`wwwroot/app.js`)

| Öğe | Satır |
|---|---|
| Haberleşme iş türleri ("Atölye Teknik Servis", "Kiradan Dönen El Telsizi Testi" vb.) | 11 |
| Marka, servis türü, durum, aksesuar sabit listeleri | 671-674 |
| Liste ekranı `workshopPage()` (tablo; filtre/arama yok) | 676-682 |
| Kayıt modalı `openWorkshopModal()` (4 kart: Firma, Kategori/Atama/Durum, Cihaz/Garanti/Aksesuar, Diğer) | 684-746 |
| Yeni kayıtta giriş tarihi `new Date().toISOString()` (UTC) | 697 |
| Kaydederken `completionDate` durum Tamamlandı/Teslim Edildi ise **her kayıtta** "şimdi" yapılır | 739 |
| Atanan kişi Haberleşme personelinden **isim** olarak seçilir | 687, 712 |
| Ana panel "Atölyede" KPI'ı yalnız `status==='Atölyede'` iş emirlerini sayar | 220, 244 |
| Menü/yükleme | 154, 191, 1577, 1965-1966 |

### 1.4 Mevcut iş kuralları (özet)
1. Bir atölye kaydı = bir cihaz = bir `SRV` iş emri (otomatik).
2. Seri no zorunlu, metin olarak saklanır.
3. Atölye durumu iş emri durumunu tek yönlü günceller; tersi yok.
4. "Teslim Edildi" iş emrini doğrudan `Kapatıldı` yapar ve iş emrinin kapanış kontrollerini atlar.

---

## 2. Olması gereken (hedef tasarım)

### 2.1 Roller (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol (varsayım) | Yaptığı iş | İzin |
|---|---|---|
| Kabul / Operasyon uzmanı | Cihazı kabul eder, aksesuar ve fiziksel durumu kaydeder, kabul fişi basar, teslim ve kargoyu kaydeder | `workshop.view`, `workshop.manage` |
| Atölye teknisyeni | Teşhis, onarım, parça kullanımı, test; yalnız kendine atanan kayıtlar | `workshop.view`, `workshop.manage` (kendi kayıtları) |
| Haberleşme TS şefi / yönetimi | Atama, öncelik, müşteri onay takibi, iptal/iade kararı, KPI izleme | `workshop.*`, `workshop.close` (önerilen) |
| Muhasebe / Yönetim | Tamir bedeli ve teklif tutarlarını görür | `finance.prices.view` |
| Depo | Parça çıkışı | `warehouse.manage` |

Önerilen tek yeni izin: **`workshop.close`** (teslim, iade, iptal). Diğer işlemler mevcut izinlerle yürür.

### 2.2 Durum akışı (önerilen)

```text
Kabul Edildi ──► Teşhiste ──► Onay Bekliyor* ──► Onarımda ──► Test / Kontrol ──► Teslime Hazır ──► Teslim Edildi
                     │              │                 │  ▲                               │
                     │              └─ Reddedildi ─┐  ▼  │                               └──► Kargoya Verildi ─► Teslim Edildi
                     │                             │ Parça Bekliyor
                     └─────── (onarılamaz) ────────┴──► Onarılmadan İade ──► Teslim Edildi
Her açık durumdan ──► İptal (gerekçe zorunlu, yalnız workshop.close)
* Yalnız garanti dışı / ücretli işlerde
```

İş emri eşlemesi: Kabul/Teşhis → `Atölyede`; Onay/Parça Bekliyor → `Beklemede` (OpsHolds kaydıyla); Onarımda → `İşlemde`; Test → `Test / Kontrol`; Teslime Hazır → `Tamamlandı`; Kargoya Verildi → `Kargoda`; Teslim Edildi → `Kapatıldı`; İptal → `İptal`.

### 2.3 Tutulacak veriler
- **Kabul:** kabul tipi (elden / kargo / kurye / sahadan teknisyen), kabul eden (kullanıcı kimliği), kabul zamanı (sunucu saati), fiziksel durum, müşteri şikâyeti, aksesuar satırları (tür, adet, not), isteğe bağlı fotoğraf.
- **Teşhis:** arıza kategorisi (sabit liste), teşhis notu, teşhis eden, teşhis zamanı, onarılabilir mi, tahmini bitiş.
- **Onarım:** yapılan işlem kategorisi + açıklama, kullanılan parçalar (mevcut stok hareketinden), süre (canlı sayaçtan; yoksa "süre kaydı eksik"), test sonucu.
- **Teslim:** teslim tipi, teslim alan kişi, teslim zamanı, kargo firması + takip no, iade edilen aksesuarlar.
- **Garanti:** başlangıç/bitiş, hesaplanan durum, Denge onarım garantisi (tekrar gelişte).
- **Ücret:** tamir bedeli / bağlı teklif (yalnız `finance.prices.view`).

### 2.4 Raporlar / KPI
- Açık atölye kayıtları duruma göre, bekleme günü (yaşlandırma: 0-3 / 4-7 / 8-14 / 15+ gün).
- Ortalama atölye çevrim süresi (Kabul → Teslime Hazır), iş günü değil takvim günü (SLA kararı ile uyumlu).
- Tahmini bitişi geçmiş kayıt sayısı.
- Tekrar gelen cihaz oranı (aynı seri no, son 90 gün).
- Marka/model/arıza kategorisi dağılımı.
- Teknisyen başına tamamlanan kayıt ve kayıtlı süre (süre kaydı olmayan kayıt "eksik" olarak ayrı sayılır).
- Onay bekleyen ücretli işler ve ret oranı.

### 2.5 Doğrulamalar
- Durum geçişleri sunucuda izinli geçiş tablosuna göre.
- Aynı seri no için açık (teslim edilmemiş/iptal edilmemiş) ikinci atölye kaydı açılamaz.
- Kapanışta (Teslim Edildi) iş emrinin kapanış kuralları uygulanır (açık sayaç yok, seri no var).
- Kargo seçilirse kargo firması ve takip no zorunlu.
- Garanti bitiş ≥ başlangıç; e-posta formatı; alan uzunlukları şema sınırlarıyla aynı.

---

## 3. Fark listesi

> Sıralama kullanıcı önceliğine göredir: önce YENİ, sonra EKSİK/HATA/VERİ, en son GÜVENLİK. **KRİTİK** etiketi sıradan bağımsızdır.

### M05-01 · YENİ · Atölye durum makinesi ve durum geçmişi tablosu — Efor: L
- **Açıklama:** §2.2'deki durum listesi ve izinli geçiş tablosu sunucuda tanımlanır. Yeni `POST /api/workshop/tickets/{id}/status` ucu (hedef durum + not). Her değişim `WorkshopTicketStatusLog` tablosuna (eski, yeni, kullanıcı kimliği, zaman, not) ve bağlı iş emrinin `WorkOrderStatusLog`'una yazılır. Durum alanı genel PUT'tan çıkarılır.
- **Neden:** Bugün durum serbest seçiliyor; "kaç gündür onay bekliyor", "ne zaman teste girdi" gibi soruların cevabı yok.
- **Mevcut:** `app.js:673` serbest liste; `Program.cs:2746-2755` eşleme; PUT log yazmıyor.
- **Kabul kriterleri:** (1) `Kabul Edildi → Teslim Edildi` doğrudan isteği 400 döner. (2) Geçerli her geçiş sonrası log tablosunda 1 satır oluşur. (3) Kayıt detayında zaman çizelgesi görünür. (4) İptal gerekçesiz gönderilirse 400.
- **Roller:** Teknisyen/kabul: ara geçişler (`workshop.manage`); Şef: İptal / Teslim (`workshop.close`).
- **Veri:** Yeni tablo `WorkshopTicketStatusLog`; `WorkshopTickets.Status` için mevcut değerlerin yeni listeye taşınması (Yeni Kayıt→Kabul Edildi, Onarımda→Onarımda, Tamamlandı→Teslime Hazır vb.).
- **Bağımlılık:** —

### M05-02 · YENİ · Yapılandırılmış teşhis ve onarım kaydı — Efor: M
- **Açıklama:** Teşhis bölümü: arıza kategorisi (sabit liste: Batarya/Şarj, Ekran/Tuş, Hoparlör/Mikrofon, Anten/RF, Yazılım/Programlama, Sıvı Teması, Fiziksel Hasar, Arıza Bulunamadı, Diğer), teşhis notu, teşhis eden (kullanıcı kimliği), teşhis zamanı, "onarılabilir mi". Onarım bölümü: yapılan işlem kategorisi + açıklama, test sonucu (Geçti/Kaldı).
- **Neden:** Marka/model bazında arıza dağılımı ve "arıza bulunamadı" oranı serbest metinden çıkarılamıyor.
- **Mevcut:** Yalnız serbest metin `DeviceCondition`, `RepairInfo` (`V15_Schema.sql:119-120`).
- **Kabul kriterleri:** (1) "Teşhiste"den çıkış için arıza kategorisi zorunlu. (2) "Test / Kontrol"den "Teslime Hazır"a geçiş test sonucu "Geçti" değilse reddedilir. (3) Arıza kategorisi rapor/Excel'de sütun olarak gelir.
- **Roller:** Teknisyen (`workshop.manage`).
- **Veri:** `WorkshopTickets`'a `FaultCategory`, `DiagnosisNote`, `DiagnosedByUserId`, `DiagnosedAt`, `IsRepairable`, `RepairCategory`, `TestResult` kolonları.
- **Bağımlılık:** M05-01

### M05-03 · YENİ · Ücretli onarımda müşteri onayı ve teklif bağlantısı — Efor: M
- **Açıklama:** Garanti dışı kayıtta teşhis sonrası "Onay Bekliyor" durumu; mevcut teklif modülünden `WorkOrderId` ile bağlı teklif oluşturma kısayolu; onay/ret kaydı (kanal: telefon/e-posta/yazılı, onaylayan kişi, zaman). Ret → "Onarılmadan İade". Onay beklerken iş emri `OpsHolds` "Müşteri onayı" nedeniyle bekletilir.
- **Neden:** Onaysız onarım ve tahsil edilemeyen işler küçük serviste en sık para kaybıdır; bekleme süresi atölye performansından ayrılmalı.
- **Mevcut:** Yalnız `RepairAmount` serbest tutar; teklif bağlantısı yok.
- **Kabul kriterleri:** (1) Garanti dışı kayıt onay kaydı olmadan "Onarımda"ya geçemez (garantili kayıtta bu adım atlanır). (2) Onay bekleyen kayıt operasyon merkezinde bekleme nedeni "Müşteri onayı" ile görünür. (3) Ret kaydedilince kayıt yalnız "Onarılmadan İade"ye geçebilir.
- **Roller:** Kabul/operasyon ve şef (`workshop.manage`, `offers.create`); tutarı görme `finance.prices.view`.
- **Veri:** `WorkshopApprovals` (TicketId, Decision, Channel, ApprovedByName, DecidedAt, OfferId NULL, UserId).
- **Bağımlılık:** M05-01, M05-07

### M05-04 · YENİ · Kabul fişi ve teslim tutanağı (PDF) — Efor: M
- **Açıklama:** Kabulde yazdırılabilir fiş: atölye no, iş emri no, firma/kişi, marka/model/seri, aksesuar listesi, fiziksel durum, şikâyet, tahmini bitiş, müşteri ve kabul eden imza alanı. Teslimde tutanak: yapılan işlem, test sonucu, iade edilen aksesuarlar, teslim alan. Fiyat yalnız `finance.prices.view` sahibinin çıktısında. Teklif PDF altyapısı (`Program.cs:883-892`) yeniden kullanılır.
- **Neden:** Basılı form ve WhatsApp ile yürüyen kabul/teslim, aksesuar ve hasar anlaşmazlıklarında kanıt üretmiyor.
- **Mevcut:** Yok.
- **Kabul kriterleri:** (1) `GET /api/workshop/tickets/{id}/receipt.pdf` ve `/delivery.pdf` 200 ve PDF döner. (2) Fiyat izni olmayan kullanıcının PDF'inde tutar alanı bulunmaz. (3) Seri no baştaki sıfırlarıyla aynen basılır.
- **Roller:** `workshop.view` (basma), fiyat satırı `finance.prices.view`.
- **Veri:** Yok (okuma).
- **Bağımlılık:** M05-05

### M05-05 · YENİ · Satır bazlı aksesuar kaydı ve teslimde karşılaştırma — Efor: M
- **Açıklama:** `Accessory1..5` yerine `WorkshopTicketAccessories` (tür, adet, not, kabulde alındı, teslimde iade edildi). Teslim adımında kabul listesi işaretlenir; eksik varsa açıklama zorunlu.
- **Neden:** 5 sabit kolon adet tutmuyor (2 batarya), teslimde "aksesuar eksik" itirazına karşı kayıt yok.
- **Mevcut:** `V15_Schema.sql:111-115`, `app.js:674, 722`.
- **Kabul kriterleri:** (1) Bir kayda 6+ aksesuar satırı eklenebilir, adet > 0 zorunlu. (2) Teslimde işaretlenmemiş aksesuar varsa açıklamasız "Teslim Edildi" 400 döner. (3) Eski `Accessory1..5` değerleri geçiş scriptiyle satırlara adet 1 olarak aktarılır, veri kaybı olmaz.
- **Roller:** Kabul/operasyon (`workshop.manage`).
- **Veri:** Yeni tablo + tek seferlik idempotent göç scripti; eski kolonlar bir sürüm boyunca salt okunur kalır.
- **Bağımlılık:** —

### M05-06 · YENİ · Seri no geçmişi, tekrar gelen cihaz ve açık kayıt engeli — Efor: M
- **Açıklama:** Kabul ekranında seri no girilince önceki atölye kayıtları (tarih, arıza, yapılan işlem) listelenir; son 90 günde onarılmış cihaz için "Tekrar geliş — onarım garantisi olabilir" uyarısı. Aynı seri no ile açık bir kayıt varsa yeni kayıt reddedilir.
- **Neden:** Tekrar arıza, kalite ve işçilik garantisi takibinin temeli; çift kayıt riskini engeller.
- **Mevcut:** Seri no aranmıyor; `POST` (2628) mükerrer kontrol yapmıyor.
- **Kabul kriterleri:** (1) Açık kaydı olan seri no ile POST 409 döner, mesajda mevcut atölye no yer alır. (2) `GET /api/workshop/devices/{serial}/history` önceki kayıtları tarih sırasıyla döner. (3) Karşılaştırma büyük/küçük harf ve baş/son boşluk duyarsız, baştaki sıfırlar korunur.
- **Roller:** `workshop.view`.
- **Veri:** `WorkshopTickets(SerialNo)` indeksi; `IsRepeatVisit` bayrağı.
- **Bağımlılık:** —

### M05-07 · YENİ · Garanti durumunun hesaplanması — Efor: S
- **Açıklama:** Garanti durumu serbest metin yerine sabit liste: Garantili / Garanti Dışı / Onarım Garantisi / Bilinmiyor. Başlangıç–bitiş tarihi girilmişse kabul tarihine göre sunucu hesaplar; tarih yoksa "Bilinmiyor" (varsayılan "Garanti Değil" yazılmaz).
- **Neden:** Varsayılan "Garanti Değil" (`app.js:721`) yanlış ücretlendirmeye yol açar; garanti oranı raporlanamıyor.
- **Mevcut:** `WarrantyStatus NVARCHAR` serbest (`V15_Schema.sql:110`).
- **Kabul kriterleri:** (1) Bitiş < kabul tarihi ise "Garanti Dışı" hesaplanır. (2) Bitiş < başlangıç 400 döner. (3) Tarih boşken durum "Bilinmiyor" kaydedilir.
- **Roller:** Kabul (`workshop.manage`).
- **Veri:** Mevcut kayıtlar için "Garanti Değil" → tarih yoksa "Bilinmiyor" dönüşümü (kullanıcı onayıyla).
- **Bağımlılık:** —

### M05-08 · YENİ · Atölye listesinde filtre/arama, yaşlandırma ve KPI — Efor: M
- **Açıklama:** Liste üstünde duruma göre tıklanabilir sayı kutuları, bekleme günü sütunu, tahmini bitişi geçen işaretleme; firma/seri no/atölye no/iş emri no araması; teknisyen ve marka filtresi. Raporlar ekranına §2.4 KPI'ları ve Excel sayfası.
- **Neden:** Şef "hangi telsiz kaç gündür atölyede" sorusunu bugün yanıtlayamıyor; liste filtresiz (`app.js:676-682`).
- **Mevcut:** Filtresiz tablo, yalnız kayıt sayısı rozeti.
- **Kabul kriterleri:** (1) 15+ gündür açık kayıt filtrelenebilir. (2) Çevrim süresi yalnız "Teslime Hazır" zaman damgası olan kayıtlardan hesaplanır; eksikler "süre kaydı eksik" olarak ayrı sayılır, 0 gün sayılmaz. (3) Excel çıktısı ekrandaki filtreyle aynı satırları içerir.
- **Roller:** `workshop.view`; Excel `reports.export`.
- **Veri:** Yok (M05-01 log tablosundan türetilir).
- **Bağımlılık:** M05-01

### M05-09 · YENİ · Teslim/kargo bilgisinin sabit listeye ve zorunluluk kurallarına bağlanması — Efor: S
- **Açıklama:** Kabul tipi ve teslim tipi sabit liste (Elden / Kargo / Kurye / Saha teslimi). Kargo seçilince kargo firması + takip no zorunlu; teslimde teslim alan kişi ve teslim zamanı zorunlu.
- **Neden:** Serbest metin (`app.js:707-711`) ile "kargoda kaç cihaz var" raporlanamıyor.
- **Mevcut:** `ReceiveType`, `DeliveryType`, `CargoTrackingNo` serbest metin.
- **Kabul kriterleri:** (1) Teslim tipi Kargo ve takip no boşsa "Kargoya Verildi" 400 döner. (2) Teslim alan boşken "Teslim Edildi" 400 döner.
- **Roller:** Kabul/operasyon (`workshop.manage`).
- **Veri:** `CargoCompany`, `DeliveredAt` kolonları.
- **Bağımlılık:** M05-01

### M05-10 · HATA · Atölye ataması iş emri atamasına yansımıyor — teknisyen kendi işini göremiyor, sayaç başlatamıyor — Efor: M
- **Açıklama:** `AssignedTo` isim metni yalnız atölye tablosunda tutuluyor; `WorkOrderAssignments`'a yazılmıyor. Teknisyen `FilterWorkOrdersForUser` (`Program.cs:3495-3502`) ve `CanAccessWorkOrderAsync` (`Program.cs:3385-3400`) nedeniyle bağlı iş emrini göremez, canlı sayaç başlatamaz (`Program.cs:1935`), parça çıkışı yapamaz (`OpsSuite.cs:193`). Atama, iş emri atamasıyla aynı kaynaktan yapılmalı.
- **Neden:** Atölye süresi ve parça tüketimi hiç kaydedilemiyor; "süre kaydı eksik" kalıcı hale geliyor.
- **Mevcut:** `Program.cs:2875`, `app.js:712`.
- **Kabul kriterleri:** (1) Atölye kaydında teknisyen seçilince `WorkOrderAssignments`'ta `AssignmentRole='Teknisyen'` aktif satır oluşur. (2) O teknisyen ile giriş yapıldığında iş emri listesinde kayıt görünür ve "Atölye" faaliyetiyle sayaç başlatılabilir. (3) Atama değişince eski atama pasif olur.
- **Roller:** Şef (`workorders.assign`) veya `workshop.manage`.
- **Veri:** Mevcut kayıtların `AssignedTo` değerleri için tek seferlik atama göçü.
- **Bağımlılık:** —

### M05-11 · HATA · Durum değişikliği iş emri tarihçesine yazılmıyor — Efor: S
- **Açıklama:** PUT ucunda iş emri durumu değişiyor ama `InsertStatusLogAsync` çağrılmıyor (yalnız oluşturmada: `Program.cs:2701`).
- **Neden:** İş emri tarihçesi ve SLA/gecikme hesapları atölye işlerinde eksik.
- **Mevcut:** `Program.cs:2757-2774`.
- **Kabul kriterleri:** Durum Onarımda yapılınca `/api/workorders/{id}/history` içinde `Atölyede → İşlemde` satırı ve kullanıcı adı görünür; durum değişmeyen kayıtta satır eklenmez.
- **Roller:** —
- **Veri:** Yok.
- **Bağımlılık:** M05-01 ile birlikte çözülebilir.

### M05-12 · HATA · "İptal" edilen atölye kaydının iş emri açık kalıyor — Efor: S
- **Açıklama:** Eşlemede İptal karşılığı yok; `_ => "Atölyede"` dalına düşüyor (`Program.cs:2754`). İptal kaydı panoda açık iş ve "Atölyede" olarak sayılmaya devam ediyor.
- **Mevcut:** `Program.cs:2746-2755`, `app.js:673`.
- **Kabul kriterleri:** Atölye kaydı İptal yapılınca bağlı iş emri `İptal` olur, Ana Panel "Atölyede" sayısı 1 azalır, gerekçe tarihçeye yazılır.
- **Roller:** `workshop.close` (önerilen).
- **Veri:** Mevcut verideki "İptal" atölye kayıtlarının iş emirlerini düzelten tek seferlik SQL (önce rapor, sonra kullanıcı onayıyla güncelleme).
- **Bağımlılık:** —

### M05-13 · HATA · Tarih/saat kayması ve tamamlanma tarihinin her kayıtta ezilmesi — Efor: S
- **Açıklama:** (a) Yeni kayıtta giriş tarihi `toISOString()` ile UTC gösteriliyor (`app.js:697`): Türkiye'de 3 saat geri kaydediliyor. (b) `completionDate` durum Tamamlandı/Teslim Edildi iken **her kaydetmede** "şimdi" yapılıyor (`app.js:739`), UTC olarak gönderiliyor. (c) PUT'ta `EntryDate` boşsa `DateTime.Now` yazılıyor (`Program.cs:2863`), kabul tarihi kaybolabiliyor.
- **Neden:** Çevrim süresi ve teslim KPI'ı yanlış hesaplanır; kabul tarihi sonradan değişebilir.
- **Kabul kriterleri:** (1) Saat 14:00'te açılan kayıt SQL'de 14:00 (yerel) görünür. (2) Tamamlanmış kayıt not eklenerek yeniden kaydedildiğinde `CompletionDate` değişmez. (3) PUT'ta `EntryDate` gönderilmezse mevcut değer korunur. (4) Tamamlanma ve teslim zamanı sunucu saatinden atanır.
- **Roller:** —
- **Veri:** Mevcut kayıtlarda kayma düzeltmesi yapılmaz (hangi kaydın etkilendiği bilinemez); yalnız rapora not düşülür.
- **Bağımlılık:** —

### M05-14 · VERİ · Seri no güncellemesi `WorkOrderDevices`'a yansımıyor — Efor: S
- **Açıklama:** PUT, `WorkOrders.SerialNo`'yu güncelliyor ancak açılışta yazılan `WorkOrderDevices` satırını güncellemiyor (`Program.cs:2669-2675` vs 2757-2772). İş emri durum ucu seri bilgisini önce `WorkOrderDevices`'tan okuyor (`Program.cs:486`).
- **Neden:** Cihaz geçmişi ve tekrar arıza analizi eski/yanlış seri no ile yapılır.
- **Kabul kriterleri:** Seri no `00A-12` → `00A-123` değiştirilince iş emri detayı, cihaz satırı ve tekrar arıza analizinde yalnız `00A-123` görünür; değişiklik tarihçeye yazılır.
- **Roller:** `workshop.manage`.
- **Veri:** Tutarsız mevcut kayıtları listeleyen kontrol sorgusu.
- **Bağımlılık:** —

### M05-15 · VERİ · İş emri ekranından yapılan durum değişikliği atölye kaydını güncellemiyor — Efor: M
- **Açıklama:** Atölye kaydına bağlı iş emri `PATCH /api/workorders/{id}/status` (`Program.cs:473`) veya `ops hold/release` (`OpsSuite.cs:130-159`) ile değiştirilebiliyor; atölye kaydı eski durumda kalıyor. Kural: atölye iş emrinin durumu yalnız atölye durum ucundan değişsin (genel uç bu iş türü için 409 + yönlendirme), bekletme atölye akışından tetiklensin.
- **Neden:** İki ekranda farklı durum, raporların çelişmesi.
- **Kabul kriterleri:** (1) `WorkType='Atölye Teknik Servis'` iş emrine genel status PATCH 409 ve "Atölye ekranından değiştirin" mesajı döner. (2) Atölye "Parça Bekliyor"a alındığında `OpsHolds`'ta aktif kayıt oluşur, çıkışta kapanır.
- **Roller:** —
- **Veri:** Mevcut tutarsız kayıtların listesi.
- **Bağımlılık:** M05-01

### M05-16 · EKSİK · Atölye kaydında kullanılan parça ve kayıtlı süre görünümü — Efor: M
- **Açıklama:** Atölye kaydı detayında bağlı iş emrinin parça çıkışları (`ServicePartMovements`) ve süre kayıtları gösterilir; kayıttan doğrudan parça çıkışı başlatılır. Süre kaydı yoksa "Süre kaydı eksik" yazılır, 0 saat yazılmaz. Parça maliyeti yalnız `finance.prices.view` ile.
- **Neden:** Atölye maliyeti ve teknisyen verimi bugün atölye ekranından görülemiyor.
- **Mevcut:** Altyapı var (`OpsSuite.cs:188-213`, `Program.cs:1929`), atölye ekranında bağlantı yok.
- **Kabul kriterleri:** (1) Atölye kaydından 2 parça çıkışı yapıldığında stok düşer ve kayıtta 2 satır görünür. (2) Süre kaydı olmayan kayıtta "Süre kaydı eksik" etiketi görünür. (3) Fiyat izni olmayan kullanıcıda maliyet sütunu API yanıtında `null`.
- **Roller:** Teknisyen (kendi atanmış kaydı), Depo (`warehouse.manage`).
- **Veri:** Yok.
- **Bağımlılık:** M05-10

### M05-17 · GÜVENLİK · **KRİTİK** — Tamir bedeli fiyat izni olmadan API'den dönüyor ve yazılabiliyor — Efor: S
- **Açıklama:** `GET /api/workshop/tickets` `repairAmount`'u her kullanıcıya döndürüyor (`Program.cs:2599`); `workorders.view` sahibi de bu uca erişebiliyor (`Program.cs:2564`). Teknisyen ve Operasyon Uzmanı (fiyat izni yok) tutarı görür; `workshop.manage` sahibi tutarı değiştirebilir. Kullanıcı kararı: fiyat/maliyet API seviyesinde gizlenmeli.
- **Kabul kriterleri:** (1) `finance.prices.view` olmayan kullanıcının GET yanıtında `repairAmount` `null`. (2) Aynı kullanıcı PUT ile tutar gönderirse mevcut tutar değişmez (yok sayılır veya 403). (3) Modalda tutar alanı bu kullanıcıya gösterilmez.
- **Roller:** `finance.prices.view`; tutar girişi için `finance.prices.view` + `workshop.manage`.
- **Veri:** Yok.
- **Bağımlılık:** —

### M05-18 · GÜVENLİK · Atölye PUT'u iş emri kapanış kontrollerini ve kayıt erişim kısıtını atlıyor — Efor: M
- **Açıklama:** (a) "Teslim Edildi" iş emrini `Kapatıldı` yapar ama açık sayaç kontrolü, `workorders.close` izni ve `CanAccessWorkOrderAsync` uygulanmaz (`Program.cs:2707-2776`; karşılaştır `Program.cs:504-523`). (b) GET ve PUT teknisyene **tüm** atölye kayıtlarını (müşteri telefon/e-posta dahil) açar; iş emri tarafındaki "teknisyen yalnız kendi işini görür" kuralıyla çelişir. (c) `workorders.create`/`workorders.edit` sahibi `workshop.manage` olmadan atölye kaydı açıp düzenleyebilir (`Program.cs:2632, 2711`).
- **Kabul kriterleri:** (1) Açık sayacı olan kayıt "Teslim Edildi" yapılamaz (409). (2) Teknisyen yalnız kendine atanmış kayıtları listeler; başkasının kaydına PUT 403. (3) Yalnız `workorders.edit` sahibi (workshop.manage yok) PUT 403 alır.
- **Roller:** `workshop.view`, `workshop.manage`, `workshop.close` (önerilen).
- **Veri:** Yok.
- **Bağımlılık:** M05-10

### M05-19 · GÜVENLİK · Sunucu tarafı girdi doğrulaması ve eşzamanlı düzenleme koruması — Efor: S
- **Açıklama:** Durum, servis türü, marka, kabul/teslim tipi listeleri sunucuda doğrulanmıyor; alan uzunlukları şemadan uzunsa SQL hatası (500) oluşuyor; e-posta formatı kontrol edilmiyor. PUT tüm alanları ezdiği için iki kişi aynı kaydı düzenlerse son yazan kazanır. `rowversion` ile çakışma tespiti eklenir.
- **Kabul kriterleri:** (1) 300 karakterlik firma adı 400 ve anlaşılır mesaj döner (500 değil). (2) Listede olmayan durum 400. (3) İki sekmede açılan kaydın ikinci kaydı 409 "Kayıt başka kullanıcı tarafından değiştirildi" döner.
- **Roller:** —
- **Veri:** `WorkshopTickets`'a `RowVer rowversion` kolonu.
- **Bağımlılık:** —

---

## 4. Varsayımlar
1. Rol eşlemesi (§2.1) organizasyon şeması gelene kadar varsayımdır; "Atölye teknisyeni" mevcut `Teknisyen` rolüyle, "Kabul" mevcut `Operasyon Uzmanı` rolüyle karşılanır kabul edildi.
2. Bir atölye kaydı = bir cihaz = bir iş emri kuralı korunur (PB kararıyla paralel). Toplu gelen cihazlar için ayrı kayıtlar açılır.
3. Atölye çevrim süresi takvim günüyle ölçülür (SLA tarafında çalışma takvimi motoru yok).
4. Müşteri ana verisi henüz yok; firma adı serbest metin kalır. Müşteri ana verisi gelirse atölye kaydı ona bağlanacak.
5. Logo Form No / Ana Servis Kaydı alanları kaldırılmaz, yalnız serbest metin referans olarak kalır.
6. Mevcut tablo ve veriler korunur; tüm şema değişiklikleri idempotent ek scriptlerle yapılır.

## 5. Kullanıcıya sorulacaklar
1. Garanti dışı onarımda müşteri onayı nasıl alınıyor (telefon, e-posta, imzalı teklif)? Belirli bir tutarın altında onaysız onarım yapılıyor mu?
2. Denge'nin kendi onarım garantisi var mı (ör. onarımdan sonra 3 ay)? Tekrar gelen cihazda bu süre kaç gün?
3. Üretici/distribütör servisine (Hytera, Aselsan vb.) gönderilen cihazlar ("Dış Servis") için RMA no, gönderim ve dönüş tarihi ayrıca izlenmeli mi?
4. "Kiradan Dönen El Telsizi Testi" ve "Setra - Kiralama Takip" işleri atölye kaydıyla mı, yoksa kiralama modülünün "kontrol" aşamasıyla mı izlenecek?
5. Bir firmadan tek seferde çok sayıda telsiz geldiğinde tek kabul fişi isteniyor mu? (Öneri: her cihaz ayrı kayıt, ortak "kabul grubu" numarası ve tek fiş.)
6. Kabul ve teslimde imza kâğıt üzerinde mi kalacak, yoksa ekranda imza / fotoğraf yüklemesi gerekli mi?
7. Teslim alınmayan cihazlar için bir süre politikası var mı (ör. 30 gün sonra hatırlatma, 90 gün sonra işlem)?
8. Tamir bedelini kim giriyor, faturalama için muhasebeye bir aktarım/liste gerekiyor mu?
9. Atölyede kaç kişi çalışıyor, atamayı kim yapıyor (şef mi, teknisyen kendisi mi alıyor)?
10. Mevcut "Garanti Değil" varsayılanıyla açılmış eski kayıtlar "Bilinmiyor"a çevrilsin mi, olduğu gibi mi kalsın?
