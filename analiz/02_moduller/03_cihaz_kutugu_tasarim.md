# M03 — Güvenlik Cihaz Kütüğü — Gereksinim Tasarımı

> **Kaynak sürüm:** V1.20.1 (salt okunur inceleme: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Hazırlayan:** Modül alt ajanı (gereksinim tasarımcısı) · **Tarih:** 21.10.2026
> **Kapsam:** X-Ray, kapı tipi metal dedektörü ve diğer güvenlik cihazları; seri no, müşteri/lokasyon, garanti, cihaz yaşam döngüsü ve geçmişi, CRUD.
> **Bağlı kararlar:** 1 cihaz = 1 PB iş emri · seri no metin (baştaki sıfırlar, `-`, `.`, `/` korunur) · seri no uydurulmaz · fiyat/maliyet API seviyesinde gizlenir · Logo CRM / Flowick kapsam dışı · rol önerileri VARSAYIM (organizasyon şeması bekleniyor).
> **Kısaltmalar:** `P.cs` = `Program.cs`, `V15S.sql` = `Database/DengeERP_V15_Schema.sql`, `V15Seed.sql` = `Database/DengeERP_V15_Seed.sql`, `V17S.sql` = `Database/DengeERP_V17_Schema.sql`, `upd.sql` = `Database/DengeERP_Update.sql`, `Ops.cs` = `OpsSuite.cs`.

---

## 1. Mevcut durum (kodda ne var?)

### 1.1 API uçları

| Uç | Satır | Ne yapıyor | Not |
|---|---|---|---|
| `GET /api/security/devices?q&brand&type&model` | P.cs:2232-2285 | `IsActive=1` cihazları döndürür; seri no/müşteri/lokasyon/model üzerinde `LIKE` arama | **Tek uç.** Ekleme/düzenleme/pasife alma/detay/geçmiş/export **yok**. Sayfalama yok; tüm kütük (≈1.324 satır) tek seferde döner. |
| `GET /api/workorders/{id}/site-suggestion` | P.cs:619-647 | Planlamada saha bilgisini önerir: bakım kalemindeki `SecurityDeviceId` veya **müşteri adı + seri no metin eşleşmesi** ile kütükten lokasyon/irtibat alır | Kütüğün tek "tüketici" ucu (bakım dışı). |
| `POST /api/maintenance/plans/{planId}/devices/initialize` → `EnsureIndividualMaintenanceWorkOrdersAsync` | P.cs:2379-2400, 2990-3070 | Sözleşmenin `ProductsText` metninden regex ile adet çıkarır ("9 X-RAY, 8 KAPI DEDEKTÖRÜ"), kütükten **`CustomerName` birebir eşit** ve tip `LIKE` olan cihazları `SecurityDeviceId` sırasıyla eşler; eksik kalanlar seri no'suz kalem olur | Eşleştirme **müşteri adının metin olarak birebir aynı yazılmasına** ve sıralamaya bağlı (P.cs:3010-3016, 3032). |
| `GET/POST /api/maintenance/workorders/{id}/form` | P.cs:2403-2560 | Cihaz bakım formu; kütükten marka/model okur, kaydederken seri no/bölgeyi **yalnızca** `MaintenanceDeviceItems` ve `WorkOrders` tablolarına yazar | Sahada düzeltilen seri/bölge **kütüğe geri yazılmaz**; `SecurityDeviceId` boşsa bağlanmaz (P.cs:2513-2521). |
| `GET /api/ops/overview` → tekrar arıza | Ops.cs:93-96 | Tekrar arızayı `WorkOrderDevices.SerialNo` metin gruplamasıyla bulur | Kütükle ilişki yok; cihaz kimliği yerine serbest metin. |

### 1.2 Tablolar

**`dbo.SecurityDevices`** (V15S.sql:3-25) — 16 kolon:
`SecurityDeviceId BIGINT PK`, `SourceKey NVARCHAR(80) UNIQUE` (Excel satır anahtarı, ör. `XRAY-00002-1`), `SourceRowNo`, `DeviceType NVARCHAR(100) NOT NULL`, `Brand`, `Model`, `ProductRaw`, `SerialNo NVARCHAR(200) NULL`, `CustomerName`, `Location`, `ContactName`, `DeliveryDateText NVARCHAR(100)`, `InstallStatus`, `Notes`, `IsActive`, `ImportedAt`.
- İndeks: `IX_SecurityDevices_Search (DeviceType,Brand,Model,SerialNo)` (V15S.sql:27-28).
- **Yok:** garanti tarihleri, kurulum tarihi (DATE), bakım sözleşmesi bağlantısı, cihaz durumu (yaşam döngüsü), bölge/kat, şehir/ilçe, `CreatedAt/UpdatedAt/UpdatedBy`, değişiklik geçmişi, seri no tekilliği.

**İlişkili tablolar:**
- `dbo.MaintenanceDeviceItems` (V17S.sql:4-19): `SecurityDeviceId BIGINT NULL` **FK var** → kütükle tek gerçek ilişki planlı bakım kalemleri.
- `dbo.WorkOrderDevices` (upd.sql:67-81): yalnızca `SerialNo/ProductName/Brand/Model` metni, **kütüğe FK yok** (M01-16 ile ele alınıyor).
- `dbo.WorkshopTickets` (V15S.sql:78-127): Haberleşme atölyesinde `WarrantyStartDate/EndDate/Status` var; güvenlik kütüğünde bunun karşılığı yok.

### 1.3 Ön yüz (`wwwroot/app.js`)
- Menü: `Güvenlik Cihaz Kütüğü` yalnız `devices.view` + birim `Güvenlik Sistemleri` ile görünür (app.js:189).
- Veri, **girişte tüm kütük** olarak yüklenir (app.js:152) — kütük ekranı açılmasa bile.
- `securityDevicesPage()` (app.js:540-565): 4 KPI (Toplam, X-Ray, Kapı Dedektörü, Seri No Mevcut), tip/marka/model açılır listeleri, istemci tarafı arama, ilk 1.000 satır tablosu.
- Tablo kolonları: Tip, Marka, Model, Seri No, Müşteri, Lokasyon, İlgili Kişi, Kurulum. **Satır tıklanamaz**; detay kartı, düzenleme butonu, yeni cihaz butonu, Excel aktarımı yok.
- Ekrandaki not: "Kaynak X-Ray / güvenlik cihaz kütüğü sisteme aktarıldı." (app.js:561) — modül fiilen **salt okunur bir Excel görüntüsü**.

### 1.4 İzinler
- `devices.view` = "Güvenlik Cihaz Kütüğünü Görüntüle" (P.cs:3905). **Yazma izni (`devices.manage`) tanımlı değil.**
- Uç `devices.view` **veya** `workorders.view` ile açılıyor (P.cs:2236). `workorders.view` rol şablonunda Muhasebe, Depo, Kiralama Operasyon'da da var (P.cs:3931-3933) → bu roller menüde görmese de API'den tüm kütüğü (müşteri irtibat adlarıyla) çekebilir.
- `UnitAllowed` → `AllowedUnits` boşsa tüm birimler (P.cs:2807).

### 1.5 Veri durumu (seed dosyasından; canlı SQL ile **doğrulanmadı**)
`V15Seed.sql` üç `MERGE` bloğu ile 1.324 satır yükler. Tip dağılımı: **X-Ray 985, Kapı Dedektörü 240, Diğer Güvenlik Cihazı 99**. Ayrıştırılabilen 1.193 satır üzerinde:

| Bulgu | Adet | Etki |
|---|---:|---|
| Seri no boş | 96 | Bakım eşleşmesi ve tekrar arıza analizi yapılamaz |
| Aynı seri no birden fazla satırda | 38 seri / 96 satır | Hangi kaydın gerçek olduğu belirsiz |
| `DeliveryDateText` Excel gün sayısı olarak metin (ör. `44083`) | 1.137 | Tarih olarak kullanılamaz; garanti/yaş hesabı yapılamaz |
| `DeliveryDateText` geçersiz (`00.00.2015`) | 1 | — |
| `Location` boş | 299 | Planlama önerisi boş gelir |
| `InstallStatus` boş | 940 | Cihazın sahada kurulu olup olmadığı bilinmiyor |
| Farklı müşteri adı | 505 | Bakım sözleşmesi (87) ile birebir ad eşleşmesi zayıf |
| Farklı model metni | 193 | `SC-5030 A` / `SC 5030 A` gibi yazım farkları |
| Marka "Diğer" | 81 | Sınıflandırma eksik |

### 1.6 Kanıtlı sorunlar
1. **Seed her DB kurulumunda kütüğü ezer** (V15Seed.sql:1360-1364): `WHEN MATCHED THEN UPDATE SET SerialNo=…, CustomerName=…, IsActive=1`. `RunDatabaseSetupOnStartup=true` ile her açılışta (P.cs:26-31) ve her sürüm geçişinde yeniden uygulanır. Ekrandan yapılacak her düzeltme/pasife alma **sessizce geri alınır**. Bugün varsayılan `false` (appsettings.json:20), ancak her migration'da bilinçli olarak `true` yapılıyor (linux/dengeerp.env.example:10).
2. **Sahadaki gerçek seri no kütüğe dönmüyor** (P.cs:2513-2521): teknisyen formda doğru seri no'yu girse de `SecurityDevices` eski/boş kalır; bir sonraki bakım dönemi aynı hatalı veriden üretilir.
3. **Bakım eşleşmesi kırılgan** (P.cs:3010-3016, 3032): müşteri adı birebir eşit olmalı; sıralama `SecurityDeviceId`'ye göre — kütükte bir cihaz pasife alınırsa veya yeni cihaz eklenirse sonraki dönemde "#3 numaralı cihaz" başka seri no'ya kayabilir.
4. **Tip adı tutarsız:** kütükte `Kapı Dedektörü`, bakım kalemlerinde `Kapı Tipi Metal Dedektörü` (P.cs:2994); ekran KPI'ı birebir `'Kapı Dedektörü'` sayar (app.js:551).

---

## 2. Olması gereken (Denge Elektronik teknik servis çalışma sistemi)

### 2.1 Roller ve sorumluluklar (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol | Kütükte ne yapar | İzin |
|---|---|---|
| Teknisyen | Cihazı arar, detay kartını ve geçmişini görür; sahada seri no / bölge düzeltmesi **önerir** | `devices.view` |
| Şef (Güvenlik Sistemleri) | Düzeltme önerilerini onaylar, cihaz ekler/düzenler, sözleşmeye cihaz bağlar | `devices.view`, `devices.manage` |
| Operasyon Uzmanı | Cihazı arayıp iş emri açar; müşteri/irtibat bilgisini günceller | `devices.view` (+ ihtiyaca göre `devices.manage`) |
| Teknik Servis Müdürü / Yardımcısı | Hepsi + pasife alma/hurdaya ayırma, veri kalitesi ekranı, export | `devices.manage`, `devices.export` |
| Muhasebe / Depo / Kiralama | Varsayılan olarak **görmez** (ihtiyaç halinde kişi bazında `devices.view`) | — |

### 2.2 Tutulacak veriler (mevcut tabloya kolon ekleyerek; yeniden yazım yok)
- **Kimlik:** Cihaz tipi (kontrollü liste), marka, model, seri no (metin, normalize edilmiş arama kopyası ayrıca).
- **Konum:** Müşteri, tesis/lokasyon, şehir, ilçe, **cihaz bölgesi** (ör. "B Kapısı Giriş", "Kargo Kabul"), saha irtibatı.
- **Tarihler:** Teslim tarihi (DATE), kurulum/devreye alma tarihi (DATE), garanti başlangıç/bitiş (DATE), garanti kaynağı.
- **Sözleşme:** Bağlı bakım sözleşmesi (`MaintenanceContractId`).
- **Yaşam döngüsü durumu:** Kurulu-Aktif / Serviste-Arızalı / Depoda / Devre Dışı / Hurdaya Ayrıldı / Bilinmiyor.
- **Denetim:** Oluşturan/güncelleyen kullanıcı ve zaman; alan bazlı değişiklik geçmişi.
- **Geçmiş (hesaplanan, ayrı tutulmaz):** planlı bakımlar, iş emirleri, uygunsuz kontrol maddeleri, kullanılan yedek parçalar, tekrar arıza sayısı.

### 2.3 Cihaz yaşam döngüsü (durumlar)
```text
Depoda ──(sevk/kurulum)──► Kurulu-Aktif ◄──(onarım bitti)── Serviste-Arızalı
                               │   ▲                               ▲
                               │   └──────(arıza iş emri)──────────┘
                               ├──(müşteri değişimi / taşıma)──► Kurulu-Aktif (yeni müşteri/lokasyon, geçmiş korunur)
                               └──(sökme)──► Devre Dışı ──(onay)──► Hurdaya Ayrıldı
Bilinmiyor = mevcut Excel aktarımından gelen, sahada doğrulanmamış kayıt
```
Kural: Durum değişikliği gerekçe ve tarih ile geçmişe yazılır; **Devre Dışı / Hurdaya Ayrıldı** cihazdan yeni PB iş emri üretilmez; kayıt **asla fiziksel silinmez**.

### 2.4 Raporlar / KPI'lar (az ama işe yarar)
1. **Kütük veri kalitesi:** seri no eksik, mükerrer seri no, lokasyon eksik, sözleşmeye bağlı olmayan kurulu cihaz, durumu "Bilinmiyor" olan cihaz sayısı (hedef: aydan aya düşmesi).
2. **Bakım kapsamı:** sözleşmeli cihaz başına bu yılki tamamlanan bakım / planlanan bakım; son bakımı 12 aydan eski kurulu cihazlar.
3. **Garanti:** garantisi önümüzdeki 60 gün içinde bitecek cihazlar; garantideyken açılmış arıza iş emirleri.
4. **Tekrar arıza:** son 90 günde ≥2 arıza iş emri olan cihazlar; model bazında arıza sayısı / kurulu cihaz sayısı.

### 2.5 Doğrulamalar
- Seri no: `Trim`; iç boşluk, harf/rakam, `- . /` korunur; **baştaki sıfırlar silinmez**; en fazla 200 karakter. Arama ve tekillik kontrolünde büyük/küçük harf duyarsız.
- Aynı **tip + marka + seri no** ile ikinci aktif kayıt engellenir (gerekçe ile "farklı cihaz olduğunu onaylıyorum" seçeneği yalnız `devices.manage`).
- Seri no boş kayıt açılabilir ama "Seri no eksik" etiketi alır; **seri no uydurulmaz**.
- Garanti bitiş ≥ başlangıç; kurulum tarihi gelecekte olamaz.
- Devre Dışı/Hurdaya cihaz açık iş emrine bağlıysa uyarı verilir.

---

## 3. Fark listesi (maddeler)

**Uygulama sırası önerisi** (kullanıcı önceliği c → b → a; veri kaybı yaratan madde KRİTİK olarak öne alındı):

| Sıra | Madde | Tür | Öncelik notu |
|---|---|---|---|
| 0 | M03-01 Seed'in kütüğü ezmesi | VERİ | **KRİTİK** — CRUD'dan önce zorunlu |
| 1 | M03-02 Cihaz detay kartı ve geçmiş | YENİ | c |
| 2 | M03-03 Garanti ve sözleşme bağlantısı | YENİ | c |
| 3 | M03-04 Yaşam döngüsü durumu | YENİ | c |
| 4 | M03-05 Kütük KPI/rapor seti | YENİ | c |
| 5 | M03-06 Cihaz ekle/düzenle/pasife al | EKSİK | b |
| 6 | M03-07 Değişiklik geçmişi (audit) | EKSİK | b (M03-06 ile birlikte) |
| 7 | M03-08 Sahadan kütüğe düzeltme önerisi | HATA | b |
| 8 | M03-09 Bakım eşleşmesinin cihaz kimliğine bağlanması | HATA | b |
| 9 | M03-10 Teslim tarihi dönüşümü + tip/model normalizasyonu | VERİ | b |
| 10 | M03-11 Veri kalitesi / mükerrer seri no ekranı | VERİ | b |
| 11 | M03-12 Sunucu tarafı arama, sayfalama, Excel | EKSİK | b |
| 12 | M03-13 Kütük izinlerinin ayrıştırılması | GÜVENLİK | a |

> Not: M03-02 (detay kartı) salt okunur olduğu için M03-06'dan önce yapılabilir; M03-03/M03-04 ise veri girişini gerektirdiğinden pratikte M03-06/M03-07 ile aynı sürümde çıkmalıdır.

---

### M03-01 · VERİ · **KRİTİK** · Seed MERGE'ün kütük düzeltmelerini ezmesi
- **Açıklama:** `V15Seed.sql` içindeki `WHEN MATCHED THEN UPDATE` dalı kaldırılmalı (yalnız `WHEN NOT MATCHED THEN INSERT`) veya seed, `dbo.SchemaVersions` benzeri bir "uygulandı" kaydıyla tek seferlik yapılmalı. Ayrıca `IsActive=1` zorlaması kaldırılmalı.
- **Neden:** Kütük düzenlenebilir hale geldiğinde (M03-06) her migration/yeniden kurulum, düzeltilen seri no'ları, müşteri taşımalarını ve pasife alınan cihazları **sessizce eski Excel değerine döndürür** → veri kaybı. Bugün sorun görünmüyor çünkü ekrandan yazma yok.
- **Mevcut:** V15Seed.sql:1360-1366 (ve aynı yapı 1786-1792, 2199-2205, 2336-2342); çalıştırma P.cs:26-31.
- **Kabul:** (1) Bir cihazın seri no'su SQL'de değiştirilip `RunDatabaseSetupOnStartup=true` ile uygulama yeniden başlatıldığında değer korunur. (2) `IsActive=0` yapılan kayıt yeniden başlatmada `0` kalır. (3) Boş veritabanında seed yine 1.324 satırı yükler. (4) Seed iki kez çalıştırıldığında satır sayısı değişmez.
- **Roller:** Yok (altyapı).
- **Veri:** Script değişikliği; şema değişikliği yok (isteğe bağlı `SchemaVersions` tablosu).
- **Efor:** S · **Bağımlılık:** Yok (M03-06'nın ön koşulu).

### M03-02 · YENİ · Cihaz detay kartı ve birleşik cihaz geçmişi
- **Açıklama:** Kütükte satıra tıklayınca açılan kart: kimlik/konum/garanti/sözleşme bilgileri + zaman çizelgesi: (a) planlı bakımlar (`MaintenanceDeviceItems` → PB no, tarih, sonuç, uygunsuz kontrol maddeleri), (b) bu cihaza bağlı arıza/servis iş emirleri (M01-16 sonrası `WorkOrderDevices.SecurityDeviceId`; öncesinde seri no eşleşmesi "metin eşleşmesi" etiketiyle), (c) kullanılan yedek parçalar (V1.20 stok hareketlerinden iş emri üzerinden), (d) kütük değişiklikleri (M03-07). Kartta "Bu cihaz için iş emri aç" kısayolu (müşteri/lokasyon/seri önceden dolu).
- **Neden:** Projenin ana sorusu "hangi müşterinin hangi lokasyonundaki hangi seri numaralı cihaza ne yapıldı?" bugün cevaplanamıyor; kütük yalnız düz tablo (app.js:562).
- **Mevcut:** Detay ucu ve ekranı yok; yalnız `GET /api/security/devices` (P.cs:2232).
- **Kabul:** (1) `GET /api/security/devices/{id}` cihaz bilgisini, `GET /api/security/devices/{id}/history` tarih sıralı olayları döndürür. (2) Bir PB iş emri kapatıldığında (P.cs:2445) ilgili cihazın geçmişinde PB no, tarih, servis sonucu ve uygunsuz maddeler görünür. (3) Süre kaydı olmayan iş "süre kaydı eksik" gösterir, 0 saat göstermez. (4) Fiyat/maliyet alanları `finance.prices.view` olmayan kullanıcıya API cevabında **hiç** yer almaz. (5) Kullanıcının `AllowedUnits`'i Güvenlik Sistemleri'ni kapsamıyorsa 403.
- **Roller:** `devices.view`; iş emri açma kısayolu `workorders.create`.
- **Veri:** Yeni tablo yok (sorgu); M03-07 tablosunu okur.
- **Efor:** M · **Bağımlılık:** M01-16 (iş emri ↔ cihaz bağı) tam fayda için; M03-07 (değişiklik olayları).

### M03-03 · YENİ · Garanti ve bakım sözleşmesi bağlantısı
- **Açıklama:** Cihaza garanti başlangıç/bitiş tarihi ve garanti kaynağı (Satış / Uzatılmış Garanti / Bilinmiyor) eklenir; hesaplanan **Garanti Durumu** (Garantide / Garanti Bitti / Bilinmiyor) listede ve detayda görünür. Cihaz, bir `MaintenanceContracts` kaydına bağlanabilir (Bakım Sözleşmeli / Sözleşmesiz). Arıza iş emri açılırken seçilen cihazın garanti ve sözleşme durumu iş emri ekranında rozet olarak gösterilir.
- **Neden:** Servisin ücretli mi, garanti kapsamında mı, sözleşme kapsamında mı olduğu her arızada sorulan ilk soru; belge §5.3 "garanti durumu cihazla ilişkilendirilmeli" diyor; Haberleşme atölyesinde bu alanlar var (V15S.sql:108-110), güvenlik kütüğünde yok.
- **Mevcut:** `SecurityDevices`'te garanti/sözleşme kolonu yok (V15S.sql:5-23).
- **Kabul:** (1) Garanti bitişi bugünden önce olan cihaz "Garanti Bitti", tarihi boş olan "Bilinmiyor" görünür (boş tarih "garantide" sayılmaz). (2) Bitiş < başlangıç girilirse 400 döner. (3) Cihaz bir sözleşmeye bağlandığında sözleşme ekranındaki cihaz sayısı artar ve cihaz detayında sözleşme adı görünür. (4) Garanti/sözleşme bilgisi iş emri detayında seri no eşleşen cihaz için gösterilir. (5) Sözleşme bedeli bu ekranlarda `finance.prices.view` yoksa API'de dönmez (mevcut P.cs:2329-2333 kuralı korunur).
- **Roller:** Görüntüleme `devices.view`; düzenleme `devices.manage`.
- **Veri:** `SecurityDevices` ADD `WarrantyStartDate DATE NULL`, `WarrantyEndDate DATE NULL`, `WarrantySource NVARCHAR(50) NULL`, `MaintenanceContractId BIGINT NULL FK → MaintenanceContracts`.
- **Efor:** M · **Bağımlılık:** M03-06 (düzenleme ekranı), M03-01.

### M03-04 · YENİ · Cihaz yaşam döngüsü durumu ve taşıma
- **Açıklama:** `LifecycleStatus` alanı (Kurulu-Aktif / Serviste-Arızalı / Depoda / Devre Dışı / Hurdaya Ayrıldı / Bilinmiyor) ve kurulum tarihi. Mevcut `InstallStatus` değerleri (`KURULDU`→Kurulu-Aktif, `GÖNDERİLDİ`→Depoda değil "Sevk Edildi/Bilinmiyor", boş→Bilinmiyor) tek seferlik dönüştürülür; eski metin korunur. "Müşteri/lokasyon değiştir" işlemi kaydı silmeden yeni müşteri/lokasyonu yazar, eskisini geçmişe bırakır. Devre Dışı/Hurdaya cihazlar planlı bakım üretiminden çıkarılır.
- **Neden:** Sökülmüş veya hurdaya çıkmış cihaz için PB iş emri üretilmesi boş ziyaret ve yanlış bakım KPI'ı demek; bugün `InstallStatus` 940 kayıtta boş ve serbest metin.
- **Mevcut:** `InstallStatus NVARCHAR(100)` serbest metin (V15S.sql:19); bakım üretimi yalnız `IsActive=1` filtreler (P.cs:3011).
- **Kabul:** (1) Durum değişikliği gerekçe olmadan kaydedilemez ve M03-07 geçmişine yazılır. (2) `Devre Dışı` cihaz, bağlı sözleşmenin bir sonraki dönem cihaz iş emirlerinde yer almaz; mevcut açık iş emri silinmez, uyarı verilir. (3) Taşıma sonrası cihazın eski bakım/iş emri geçmişi detay kartında aynen görünür. (4) `Hurdaya Ayrıldı` yalnız `devices.manage` + müdür onayı (VARSAYIM) ile yapılabilir ve geri alınamaz değil, gerekçeli geri alınabilir.
- **Roller:** `devices.manage`; hurdaya ayırma için (VARSAYIM) Teknik Servis Müdürü/Yardımcısı.
- **Veri:** `SecurityDevices` ADD `LifecycleStatus NVARCHAR(30) NOT NULL DEFAULT N'Bilinmiyor'`, `InstallDate DATE NULL`, `City NVARCHAR(100) NULL`, `District NVARCHAR(100) NULL`, `Zone NVARCHAR(250) NULL`; dönüşüm scripti.
- **Efor:** M · **Bağımlılık:** M03-06, M03-07.

### M03-05 · YENİ · Kütük KPI ve rapor seti (cihaz bazlı)
- **Açıklama:** Kütük ekranının üstündeki KPI'lar tıklanabilir hale gelir ve şu kırılımlar eklenir: (a) Kurulu cihaz / sözleşmeli cihaz / sözleşmesiz kurulu cihaz, (b) son bakımı 12 aydan eski sözleşmeli cihaz, (c) garantisi 60 gün içinde bitecek cihaz, (d) son 90 günde ≥2 arıza iş emri olan cihaz, (e) model bazında arıza iş emri sayısı / kurulu adet. Her KPI tıklanınca ilgili filtrelenmiş cihaz listesi açılır (V1.8'deki tıklanabilir KPI davranışı).
- **Neden:** Yönetimin "hangi cihazlar sorunlu, hangi bakım kaçtı, hangi müşteriye garanti bitiş/teklif fırsatı var" sorularına cihaz düzeyinde cevap; mevcut 4 KPI (app.js:553) yalnız sayım.
- **Mevcut:** Statik 4 KPI, tıklanamaz; tekrar arıza yalnız operasyon merkezinde seri metniyle (Ops.cs:93-96).
- **Kabul:** (1) Her KPI sayısı, tıklanınca açılan listedeki satır sayısıyla birebir aynıdır. (2) (d) listesi yalnız planlı bakım dışı iş emirlerini sayar. (3) Sayım sunucuda yapılır (`GET /api/security/devices/kpi`). (4) Seri no'su olmayan cihazlar tekrar arıza listesine "seri no eksik" etiketiyle hiç girmez (yanlış eşleşme yapılmaz).
- **Roller:** `devices.view`; rapor export `devices.export` (M03-12).
- **Veri:** Yok (M03-03, M03-04 alanlarını kullanır).
- **Efor:** M · **Bağımlılık:** M03-02, M03-03, M03-04, M01-16.

### M03-06 · EKSİK · Cihaz ekleme, düzenleme ve pasife alma (CRUD)
- **Açıklama:** `POST /api/security/devices`, `PUT /api/security/devices/{id}`, `PUT /api/security/devices/{id}/status` (aktif/pasif — **fiziksel silme yok**). Ön yüzde "Yeni Cihaz" butonu, satırda "Düzenle". Elle eklenen kayıtlar `SourceKey = MAN-{yyyyMMdd}-{id}` gibi sistem üretimli anahtar alır (mevcut UNIQUE NOT NULL kısıtı korunur). Eşzamanlı düzenlemeye karşı `RowVersion` kontrolü.
- **Neden:** Yeni kurulan cihazlar, sahada bulunan eksik cihazlar ve yanlış müşteri/seri kayıtları bugün yalnız SQL ile düzeltilebiliyor; kütük sürekli eskiyor (CHANGELOG_PILOT_V1.txt:31 bunu açık iş olarak listeliyor).
- **Mevcut:** Yalnız GET (P.cs:2232-2285); `devices.manage` izni yok (P.cs:3905).
- **Kabul:** (1) `devices.manage` olmayan kullanıcı POST/PUT çağırdığında 403. (2) Seri no `00123/A-7` girildiğinde aynen (baştaki sıfırlar dahil) kaydedilir ve geri okunur. (3) Aynı tip+marka+seri no ile ikinci aktif kayıt 409 döner; `devices.manage` ve gerekçe ile "farklı cihaz" onayı verilirse kaydedilir. (4) Seri no boş kayıt kaydedilir ve listede "Seri no eksik" görünür. (5) Pasife alınan cihaz varsayılan listede görünmez, "pasifleri göster" filtresiyle görünür; geçmişi korunur. (6) İki kullanıcı aynı kaydı aynı anda düzenlerse ikinci kayıt 409 alır. (7) Her değişiklik M03-07 geçmişine yazılır.
- **Roller:** `devices.manage` (yeni izin). VARSAYIM: Şef, Teknik Servis Müdürü/Yardımcısı, Üst Yönetim rol şablonlarına eklenir; mevcut kullanıcılara otomatik dağıtılmaz (belge §8.1 kuralı).
- **Veri:** `SecurityDevices` ADD `CreatedAt`, `CreatedByUserId INT NULL`, `UpdatedAt`, `UpdatedByUserId INT NULL`, `RowVersion ROWVERSION`, `SerialNoNormalized AS UPPER(LTRIM(RTRIM(SerialNo))) PERSISTED` + filtreli indeks; `Catalog.Permissions`'a `devices.manage`.
- **Efor:** M · **Bağımlılık:** M03-01 (ön koşul), M03-07 (aynı sürümde).

### M03-07 · EKSİK · Kütük değişiklik geçmişi (audit)
- **Açıklama:** `SecurityDeviceHistory` tablosu: cihaz, olay türü (Oluşturma / Alan Değişikliği / Durum Değişikliği / Taşıma / Sahadan Düzeltme / Birleştirme), alan adı, eski değer, yeni değer, gerekçe, kullanıcı (kimlik + ad), zaman. Tüm yazma uçları aynı transaction içinde geçmiş satırı yazar.
- **Neden:** Seri no ve müşteri değişiklikleri bakım/garanti/tekrar arıza sonuçlarını değiştirir; kimin neyi neden değiştirdiği bilinmeden kütüğe güvenilemez. Proje genelinde audit yok (envanter gözlem 3).
- **Mevcut:** Yok.
- **Kabul:** (1) Bir cihazın seri no'su değiştirildiğinde geçmişte eski/yeni değer, kullanıcı ve zaman görünür. (2) Geçmiş satırları API ile düzenlenemez/silinemez (yalnız INSERT). (3) Yazma başarısız olursa geçmiş satırı da oluşmaz (transaction). (4) Detay kartında (M03-02) geçmiş tarih sırasıyla listelenir.
- **Roller:** Okuma `devices.view`; yazma yalnız sistem.
- **Veri:** Yeni tablo `dbo.SecurityDeviceHistory(SecurityDeviceHistoryId BIGINT PK, SecurityDeviceId BIGINT FK, EventType, FieldName, OldValue NVARCHAR(1000), NewValue NVARCHAR(1000), Reason NVARCHAR(500), UserId INT, UserName NVARCHAR(150), CreatedAt DATETIME2)` + `IX(SecurityDeviceId, CreatedAt)`.
- **Efor:** S · **Bağımlılık:** M03-06 ile birlikte.

### M03-08 · HATA · Sahada düzeltilen seri no / bölge kütüğe dönmüyor
- **Açıklama:** PB bakım formu kapatılırken (P.cs:2494-2534): (a) kalemin `SecurityDeviceId`'si boşsa, aynı müşterinin aktif kütüğünde normalize seri no eşleşmesi aranır; tek eşleşme varsa kalem cihaza bağlanır. (b) Teknisyenin girdiği seri no/bölge kütükteki değerden farklıysa veya kütükte cihaz yoksa, **kütüğü doğrudan değiştirmeden** "Kütük düzeltme önerisi" oluşturulur. (c) Şef/`devices.manage` önerileri tek ekranda onaylar/reddeder; onayda kütük güncellenir ve M03-07'ye "Sahadan Düzeltme" olarak yazılır.
- **Neden:** Teknisyen doğru seri no'yu sahada görüyor ama kütük eski kalıyor; bir sonraki dönem aynı hatalı/boş seri no ile iş emri üretiliyor (P.cs:3032-3043). 96 seri no'suz kaydın tamamlanmasının en ucuz yolu saha.
- **Mevcut:** Form yalnız `MaintenanceDeviceItems` ve `WorkOrders`'ı günceller (P.cs:2513-2521).
- **Kabul:** (1) Kütükte seri no'su boş olan cihazın PB formu `ABC-001` ile kapatıldığında, kütük değişmez ve onay listesinde 1 öneri görünür. (2) Öneri onaylandığında kütük seri no'su `ABC-001` olur, geçmişte teknisyen + onaylayan görünür. (3) Kütükte zaten aynı seri no'lu başka aktif cihaz varsa öneri "çakışma" etiketiyle gelir ve otomatik onaylanamaz. (4) Teknisyen (`devices.manage` yok) kütüğü doğrudan değiştiremez.
- **Roller:** Öneri: `workorders.close`/`maintenance.manage`; onay: `devices.manage`.
- **Veri:** Yeni tablo `dbo.SecurityDeviceChangeRequests(Id, SecurityDeviceId NULL, MaintenanceDeviceItemId NULL, WorkOrderId, ProposedSerialNo, ProposedZone, ProposedLocation, Status [Bekliyor/Onaylandı/Reddedildi], RequestedBy, RequestedAt, DecidedBy, DecidedAt, DecisionNote)`.
- **Efor:** M · **Bağımlılık:** M03-06, M03-07.

### M03-09 · HATA · Planlı bakım cihaz eşleşmesinin cihaz kimliğine bağlanması
- **Açıklama:** Bakım dönemi cihaz kalemleri üretilirken, öncelik sırası: (1) sözleşmeye bağlı (`SecurityDevices.MaintenanceContractId`, M03-03) aktif ve Devre Dışı olmayan cihazlar, (2) bir önceki dönemde aynı sözleşmede bakımı yapılmış `SecurityDeviceId`'ler, (3) ancak hiçbiri yoksa bugünkü müşteri adı + tip eşleşmesi ve `ProductsText` adedi. Bağlı cihaz sayısı `ProductsText` adedinden farklıysa üretim öncesi uyarı gösterilir (sessizce fazla/eksik iş emri açılmaz).
- **Neden:** Bugün eşleşme müşteri adının birebir yazımına ve `SecurityDeviceId` sırasına bağlı (P.cs:3010-3016, 3032); 505 farklı müşteri adı ile 87 sözleşme arasında yazım farkları seri no'suz PB iş emri üretiyor; kütüğe cihaz eklenince sıralama kayıyor.
- **Mevcut:** `EnsureIndividualMaintenanceWorkOrdersAsync` (P.cs:2990-3070).
- **Kabul:** (1) Sözleşmeye 17 cihaz bağlı AKYAKA AVM örneğinde yeni dönem için tam 17 ayrı PB iş emri, her biri doğru `SecurityDeviceId` ve seri no ile oluşur. (2) Kütüğe aynı müşteri adına yeni cihaz eklenmesi, önceki dönemin cihaz–sıra eşleşmesini değiştirmez. (3) Bağlı cihaz 16, `ProductsText` 17 ise ekranda "1 cihaz kütükte bağlı değil" uyarısı çıkar; kullanıcı onaylamadan seri no'suz kalem üretilmez. (4) Mevcut (önceden üretilmiş) kalemler ve PB numaraları değişmez/silinmez.
- **Roller:** `maintenance.manage`.
- **Veri:** M03-03'teki `MaintenanceContractId`; ek kolon yok. Tek seferlik "sözleşme–cihaz eşleştirme" ekranı/scripti (önerilen eşleşme, şef onayı).
- **Efor:** M · **Bağımlılık:** M03-03. (Planlı Bakım modülü tasarımıyla koordine edilmeli.)

### M03-10 · VERİ · Teslim tarihinin tarihe dönüştürülmesi ve tip/marka/model normalizasyonu
- **Açıklama:** (a) `DeliveryDateText` içindeki 5 haneli Excel gün sayıları (`44083` → 1899-12-30 + n gün) yeni `DeliveryDate DATE` kolonuna dönüştürülür; dönüştürülemeyenler (`00.00.2015`, boş) `NULL` + metin korunur. (b) Cihaz tipi kontrollü liste olur: `X-Ray`, `Kapı Tipi Metal Dedektörü`, `Diğer Güvenlik Cihazı` (+ kullanıcı onayıyla eklenecek alt tipler); kütükteki `Kapı Dedektörü` ile bakım kalemindeki `Kapı Tipi Metal Dedektörü` (P.cs:2994) tek ada indirilir; ekran KPI'ı (app.js:551) buna göre düzelir. (c) Model yazım farkları (`SC-5030 A` / `SC 5030 A`) için bir model eşanlam tablosu ile normalize model adı; orijinal metin `ProductRaw`'da kalır.
- **Neden:** 1.137 kayıtta teslim tarihi okunamaz durumda → garanti ve cihaz yaşı hesaplanamaz; tip adı farkı KPI ve bakım eşleşmesinde hata kaynağı; 193 model metni model bazlı arıza analizini bozuyor.
- **Mevcut:** `DeliveryDateText NVARCHAR(100)` (V15S.sql:18); seed değerleri V15Seed.sql.
- **Kabul:** (1) `44083` değeri `2020-09-09` olarak `DeliveryDate`'e yazılır (SSMS ile 5 örnek kayıt elle doğrulanır). (2) Dönüşüm scripti iki kez çalıştırıldığında sonuç değişmez. (3) `DeliveryDateText` hiçbir kayıtta silinmez. (4) Dönüşüm sonrası kütük ekranındaki "Kapı Tipi Metal Dedektörü" sayısı = SQL'de bu tipteki aktif kayıt sayısı. (5) Model filtresinde `SC 5030 A` seçildiğinde her iki yazımdaki cihazlar gelir.
- **Roller:** Script (İT/geliştirici); model eşanlam bakımı `devices.manage`.
- **Veri:** `SecurityDevices` ADD `DeliveryDate DATE NULL`, `ModelNormalized NVARCHAR(250) NULL`; yeni `dbo.SecurityDeviceModelAliases(Alias, CanonicalModel, Brand)`; tek seferlik UPDATE scripti (yedek sonrası).
- **Efor:** M · **Bağımlılık:** M03-01; canlıda uygulama öncesi `.bak` + `RESTORE VERIFYONLY`.

### M03-11 · VERİ · Veri kalitesi ekranı: mükerrer / eksik seri no, eksik lokasyon
- **Açıklama:** `devices.manage` için "Kütük Veri Kalitesi" sekmesi: (a) normalize seri no'su aynı olan aktif kayıt grupları (seed'de 38 seri / 96 satır), (b) seri no'su boş cihazlar (96), (c) lokasyonu boş cihazlar (299), (d) sözleşmesi olan müşterinin sözleşmeye bağlanmamış kurulu cihazları. Mükerrer grupta "Birleştir" (biri ana kayıt kalır, diğeri pasif + `MergedIntoDeviceId`, bakım kalemleri ana kayda taşınır) ve "Farklı cihaz olarak işaretle" işlemleri.
- **Neden:** Mükerrer seri no ile hangi cihaza bakım yapıldığı belirsiz; belge §14 "veri kalitesi: şehir/bölge/seri no" açık iş olarak listeliyor.
- **Mevcut:** Yok; yalnız "Seri No Mevcut" sayacı (app.js:552).
- **Kabul:** (1) Ekrandaki mükerrer grup sayısı, SSMS'te `GROUP BY SerialNoNormalized HAVING COUNT(*)>1` (aktif kayıtlar) sonucuyla aynıdır. (2) Birleştirme sonrası pasif kaydın `MaintenanceDeviceItems` satırları ana kayda bağlıdır; hiçbir PB iş emri silinmez. (3) "Farklı cihaz" olarak işaretlenen grup listeden düşer ve gerekçesi geçmişte kalır. (4) Her işlem M03-07'ye yazılır.
- **Roller:** `devices.manage`.
- **Veri:** `SecurityDevices` ADD `MergedIntoDeviceId BIGINT NULL`, `DuplicateAcknowledged BIT NOT NULL DEFAULT 0`.
- **Efor:** M · **Bağımlılık:** M03-06, M03-07.

### M03-12 · EKSİK · Sunucu tarafı arama/sayfalama ve Excel dışa aktarım
- **Açıklama:** `GET /api/security/devices` `page/pageSize`, `status`, `customer`, `contractId`, `warranty` filtreleri alır; toplam sayı döner. Kütük **girişte değil**, ekran açılınca yüklenir. `GET /api/security/devices.xlsx` aynı filtrelerle Excel üretir (yetkiye göre sözleşme bedeli yok).
- **Neden:** Her girişte tüm kütüğün (≈1.324 satır, büyüyecek) her kullanıcıya inmesi (app.js:152) mobil teknisyen görünümünde yavaşlık; ekran 1.000 satırda kesiliyor (app.js:562-563); müşteriye/İT'ye cihaz listesi vermek için export yok.
- **Mevcut:** Filtresiz toplu liste (P.cs:2247-2259), istemci tarafı filtre (app.js:546-549).
- **Kabul:** (1) Giriş sırasında `/api/security/devices` çağrılmaz (tarayıcı ağ sekmesinde doğrulanır). (2) 50'lik sayfada toplam sayı ve sayfa geçişi doğru çalışır; arama sonucu 1.000'den fazla olsa da tüm sayfalar gezilebilir. (3) Excel, ekrandaki filtreyle aynı satır sayısını içerir; seri no hücreleri metin biçiminde (baştaki sıfırlar korunur). (4) `devices.export` yoksa Excel ucu 403.
- **Roller:** `devices.view`; export `devices.export` (yeni) veya mevcut `reports.export` (karar §4).
- **Veri:** Yok (indeks: `SerialNoNormalized`, `CustomerName`).
- **Efor:** M · **Bağımlılık:** M03-06 (normalize seri kolonu).

### M03-13 · GÜVENLİK · Kütük izinlerinin ayrıştırılması
- **Açıklama:** (a) `GET /api/security/devices` yalnız `devices.view` ile açılsın; `workorders.view` yeterli olmasın (iş emri ekranındaki cihaz bilgisi kendi ucu üzerinden gelir). (b) Yazma uçları `devices.manage`, export `devices.export`. (c) Birim kontrolü: `AllowedUnits` boş kullanıcının tüm birimleri görmesi kütük için de geçerli; proje geneli karar (envanter gözlem 5) ile uyumlu düzeltilmeli. (d) İrtibat kişisi adı/telefonu (eklenirse) yalnız `devices.view` sahiplerine dönsün.
- **Neden:** Bugün Muhasebe, Depo ve Kiralama Operasyon rolleri menüde kütüğü görmese de API'den tüm müşteri–cihaz–irtibat listesini çekebiliyor (P.cs:2236, 3931-3933). Kritik veri kaybı değil, ancak müşteri bilgisi sızıntısı (KVKK) riski.
- **Mevcut:** P.cs:2236-2237.
- **Kabul:** (1) Yalnız `workorders.view` izni olan test kullanıcısı `GET /api/security/devices` çağırdığında 403 alır. (2) `devices.view` olan Teknisyen 200 alır, POST/PUT'ta 403 alır. (3) Yetki değişikliği oturum yenilemeden sonra geçerli olur ve test listesine eklenir.
- **Roller:** Tüm roller (rol şablonu güncellemesi; mevcut kullanıcılara otomatik dağıtım yok).
- **Veri:** `Catalog.Permissions`'a `devices.manage`, `devices.export`.
- **Efor:** S · **Bağımlılık:** Yok (M03-06 ile aynı sürümde yapılması önerilir).

---

## 4. Kullanıcıya sorulacaklar (benim karar veremeyeceğim konular)

1. **Tek doğru kaynak:** "X-RAY KÜTÜK" Excel'i hâlâ başka bir yerde (satış/depo) güncelleniyor mu? DengeERP kütüğü bundan sonra **tek doğru kayıt** mı olacak? (Evet ise Excel'den tekrar aktarım yapılmaz; M03-01 kesinleşir.)
2. **Garanti kuralı:** Garanti süresi ürün/marka bazında standart mı (ör. 24 ay), yoksa her satış/sözleşmede farklı mı? Garanti **teslim** tarihinden mi, **kurulum/devreye alma** tarihinden mi başlar? Toplu olarak "teslim + X ay" hesaplayarak doldurmamız kabul edilir mi?
3. **Kütüğü kim değiştirebilir?** `devices.manage` (ekle/düzenle/sözleşmeye bağla) hangi rollerde olmalı: yalnız Şef ve Müdür mü, Operasyon Uzmanı da mı? Hurdaya ayırma için ayrıca onay gerekiyor mu?
4. **"Diğer Güvenlik Cihazı" (99 kayıt):** Bunlar hangi cihazlar (el dedektörü, turnike, araç altı arama, kamera vb.)? Ayrı tip olarak mı izlenecek, bakım checklist'i gerekecek mi?
5. **Mükerrer seri no'lar (38 seri / 96 satır):** Aynı cihazın iki kez yazılması mı, yoksa farklı markada tesadüfi aynı numara mı? Temizliği kim yapacak (şef mi, depo mu)?
6. **Sözleşme–cihaz eşleştirmesi (87 sözleşme):** İlk eşleştirmeyi kim yapacak? Sistem önerecek, şef onaylayacak şekilde mi olsun?
7. **Kiralama cihazları:** Kiralamada kullanılan X-Ray/kapı dedektörleri (`RentalInventory`) de bu kütükte mi izlenmeli, yoksa kiralama envanteri ayrı mı kalmalı? (Şimdilik ayrı varsayıldı.)
8. **Haberleşme cihazları (telsiz):** Bu kütüğe girecek mi? (Şimdilik hayır; atölye kaydında kalır varsayıldı.)
9. **Excel izni:** Kütük dışa aktarımı için yeni `devices.export` izni mi açalım, yoksa mevcut `reports.export` yeterli mi?
10. **Müşteri ana kaydı:** Müşteri adları kütükte, sözleşmede ve iş emrinde serbest metin. Ortak bir müşteri/lokasyon ana tablosu (proje geneli karar) bu fazda yapılacak mı? Yapılmayacaksa M03-09 sözleşme bağlantısı ile ilerlenir.

## 5. Varsayımlar
- Rol–izin eşlemeleri organizasyon şeması gelene kadar VARSAYIMdır (§2.1).
- Kütük sayıları (`1.324`, `96`, `38/96`, `299`, `505`, `193`) **seed SQL dosyasından** çıkarıldı (ayrıştırılabilen 1.193 satır üzerinden; tip dağılımı 1.324 satırın tamamından); canlı SQL'de sonradan değişmiş olabilir — SSMS ile doğrulanmalı.
- Kiralama envanteri ve Haberleşme atölye cihazları bu modül kapsamı dışında tutuldu.
- Müşteri ana tablosu bu modülde önerilmedi; mevcut serbest metin `CustomerName` korunur, sözleşme bağlantısı (M03-03) ile ilerlenir.
- `WorkOrderDevices` ↔ kütük bağlantısı M01-16'da tanımlıdır; not: `SecurityDevices.SecurityDeviceId` **BIGINT** olduğundan M01-16'daki FK kolonu da `BIGINT` olmalıdır (M01-16 metninde `INT` yazıyor).
- Tüm şema değişiklikleri mevcut idempotent script düzeninde (`IF COL_LENGTH ... IS NULL ALTER TABLE ...`) yeni bir `ZZ_V121_*.sql` dosyasıyla, yedek alındıktan sonra uygulanır.
