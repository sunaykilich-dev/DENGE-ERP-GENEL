# M11 — Yedek Parça ve Servis Stoğu: Gereksinim Tasarımı

Kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api/` (V1.20.1). Kaynak kod salt okunur; bu belge yalnızca analizdir.
Tarih: 2026-10-21. Kapsam: yalnızca teknik servis. Logo CRM / Flowick entegrasyonu kapsam dışı.
Öncelik sırası (kullanıcı kararı): **(c) yeni özellik → (b) mevcut eksikler → (a) güvenlik/üretime hazırlık**. Veri kaybı veya sızıntısı yaratan açık bulunursa ayrıca **KRİTİK** diye işaretlenir. Bu modülde KRİTİK açık **bulunmadı** (bkz. 1.5).

Geçerli kararlar: 1 cihaz = 1 PB iş emri; seri no metin olarak tutulur; fiyat/maliyet API seviyesinde gizlenir; kiralık cihaz envanteri ile servis yedek parça stoğu **ayrı iş mantıkları** olarak izlenir (Proje Geçmişi §5.11).

---

## 1. Mevcut durum (kodda ne var)

### 1.1 Veri modeli (SQL, `Database/ZZ_V120_Operations.sql`)

| Tablo | Satır | Not |
|---|---|---|
| `ServicePartCatalog` | 17-18 | `PartId`, `Code` (UNIQUE, 80), `Name` (200), `Unit` (varsayılan `Adet`), `MinimumQty` DECIMAL(18,3), `UnitCost` DECIMAL(18,2). **`IsActive`, birim (UnitCode), kategori, marka/model uyumu, üretici parça no, barkod yok.** |
| `ServiceStockBalances` | 20-21 | PK (PartId, WarehouseId), `Quantity` `CHECK(Quantity>=0)`: negatif stok veritabanı seviyesinde de engelli. |
| `ServicePartMovements` | 23-24 | `Kind` yalnızca `Giriş` / `Çıkış`; `WorkOrderId` NULL olabilir; `UnitCost` hareket anındaki katalog maliyetinin kopyası; `CreatedBy`, `CreatedAt`. **Belge no, açıklama, karşı depo, ters kayıt referansı yok.** |
| `RentalWarehouses` | `ZZ_V112_RentalInventoryOperations.sql:36-49` | Yedek parça stoğu **kiralama depolarını** (DEPO-1/2/3) kullanıyor (FK: `ZZ_V120:21,24`). Servise özel depo veya araç stoğu kavramı yok. |

Script'ler uygulama açılışında alfabetik sırayla çalışıyor (`Program.cs:30`).

### 1.2 API uçları (`OpsSuite.cs`, `Program.cs:2778`'de bağlanıyor)

| Uç | Satır | İzin | Ne yapar |
|---|---|---|---|
| `GET /api/ops/stock` | 160-176 | `warehouse.view` | Aktif depolar + katalog×bakiye listesi (LEFT JOIN: parça birden çok depoda varsa birden çok satır; hiç bakiyesi yoksa depo adı “Kayıt bekliyor”). `cost` yalnızca `finance.prices.view` ile döner (173). Birim (`UnitAllowed`) filtresi yok. |
| `POST /api/ops/stock/part` | 177-187 | `warehouse.manage` (+ maliyet > 0 ise `finance.costs.manage`, 181) | Yeni parça. Birim sabit `Adet` (185). Kod tekrarında UNIQUE ihlali → işlenmemiş SQL istisnası (500). **Düzenleme / pasifleştirme ucu yok.** |
| `POST /api/ops/stock/movement` | 188-213 | `warehouse.manage` | `Giriş`/`Çıkış`; miktar 0 < q ≤ 100000 (191); çıkışta iş emri zorunlu (192); iş emrine erişim `filterOrders` ile (193); `Serializable` + `UPDLOCK,HOLDLOCK` (194, 199); bakiye < 0 ise “Stok yetersiz.” (202); bakiye + hareket aynı işlemde (203-212). İş emrinin **durumu kontrol edilmiyor**. |
| Uyarılar (`AuxiliaryAlerts`) | 42-49 | `warehouse.view` | Parçanın **tüm depolardaki toplamı** `MinimumQty` altındaysa “Düşük stok” uyarısı (Operasyon Merkezi → Uyarılar). |
| `GET /api/ops/finance` | 224-228 | `finance.prices.view` + `reports.view` | İş emri malzeme maliyeti = Σ(Çıkış × UnitCost) − Σ(Giriş-ile-iş-emri × UnitCost). Yani iş emrine bağlı “Giriş” **örtük iade** sayılıyor. |

Hareket geçmişini listeleyen **hiçbir GET ucu yok**; bir iş emrinde hangi parçanın kullanıldığı hiçbir ekranda görünmüyor (yalnızca finans ekranındaki toplam TL).

İzinler: `warehouse.view` “Depo Modülünü Gör”, `warehouse.manage` “Yedek Parça Stoklarını Yönet” (`Program.cs:3895-3896`). Rol şablonlarında (`Program.cs:3921-3935`) **`warehouse.manage` yalnızca Admin'de (`*`) var**; `Depo` rolü yalnızca `warehouse.view` (3932); Üst Yönetim / Müdür / Müdür Yrd. yalnızca `warehouse.view`; Teknisyen ve Şef'te stokla ilgili hiçbir izin yok (3929-3930).

Depo adı değişikliği `PUT /api/rentals/warehouses/{id}` `rentals.edit` ile yapılıyor (`Program.cs:1322-1332`) ve servis stok depolarının adını da değiştiriyor.

### 1.3 Ön yüz

- Menü “Yedek Parça” → `stock120` yalnızca `warehouse.view` ile (`app.js:184`); ayrıca kiralama “Depo” menüsü (`app.js:198`). Başlık “Yedek Parça Stokları” (`app.js:204`). Yönlendirme `app.js:1570, 1906, 1909`.
- Ekran `ops120.js:10-14`: tek tablo (ID, Kod, Ürün, Depo, Stok, Minimum, Durum, [İç Maliyet]). Durum rozeti **depo satırı bazında** `quantity < minimum` (13). Arama, filtre, depo seçimi yok.
- “+ Parça Tanımla” (`ops120.js:78-83`) ve “Stok Giriş / Çıkış” (`ops120.js:84-92`) ardışık `prompt()` pencereleri; kullanıcı **Parça ID, Depo ID (1/2/3) ve İş Emri ID**'yi (iş emri numarası değil, iç kimlik) elle yazıyor.
- Planlı bakım dijital formunda “Kullanılan Yedek Parçalar (varsa)” **serbest metin** (`app.js:623`, kaydetme `app.js:647`; API `Program.cs:2411-2429, 2452, 2515-2526`, istek kaydı `Program.cs:3820`). Bu metin stoğa bağlı değil: teknisyen formda parça yazar, depo ayrıca hareket girer → çift kayıt ve tutarsızlık.
- Haberleşme atölyesi kaydında da parça bilgisi yalnızca serbest metin (`RepairInfo`); stoğa bağ yok.

### 1.4 Doğru çalışan kurallar

- Negatif stok engeli: hem API (`OpsSuite.cs:202`) hem DB `CHECK` (`ZZ_V120:21`).
- Eşzamanlı çıkışta yarış durumu engelli (`Serializable` + `UPDLOCK,HOLDLOCK`).
- Çıkış iş emrine bağlı olmak zorunda ve kullanıcının göremediği iş emrine çıkış yapılamıyor.
- Maliyet alanı API'de `finance.prices.view` olmadan `null` (A1 denetiminde de “uygun” bulundu).
- Hareketler silinemiyor/değiştirilemiyor (uç yok) ve `CreatedBy` tutuluyor.

### 1.5 Tespit edilen hatalar ve boşluklar (özet; ayrıntı bölüm 3'te)

1. **Teknisyen parça kullanımını kaydedemiyor**: çıkış yalnızca `warehouse.manage` ile mümkün ve bu izin hiçbir rol şablonunda yok. Uygulamada yalnızca Admin stok hareketi yapabiliyor.
2. **Hareket geçmişi görüntülenemiyor**: GET ucu yok. Changelog'daki “hareket geçmişi” iddiası arayüzde karşılanmıyor.
3. **Kapalı / iptal iş emrine çıkış yapılabiliyor** (A3-18 ile aynı bulgu).
4. **İade / düzeltme yok**: yanlış girilen hareket geri alınamıyor; iş emrine bağlı “Giriş” örtük iade sayılıyor ama çıkışı aşan iade de kabul ediliyor, iş emri malzeme maliyeti eksiye düşebiliyor.
5. **Depolar arası transfer ve sayım (stok düzeltme) yok**: kayıp/hasarlı parça düşmek için tek yol sahte bir iş emrine çıkış yapmak.
6. **Katalog düzenlenemiyor / pasife alınamıyor**; kod tekrarında 500 hatası.
7. **Az stok durumu ekranda ve uyarıda farklı hesaplanıyor**: ekran depo satırı bazında, uyarı toplam bazında.
8. **“Adet” birimli parçada ondalık miktar** (ör. 1,5) kabul ediliyor.
9. Bakım formu ve atölyede parça serbest metin; stokla bağlantısız.
10. Ekran `prompt()` ile ID yazdırıyor; hata riski yüksek, mobilde pratik değil.

KRİTİK sınıfında açık yok: maliyet sızıntısı yok, negatif stok engeli DB'de de var, hareketler silinemiyor.

---

## 2. Olması gereken (Denge Elektronik çalışma modeli)

### 2.1 Roller (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol | Bu modülde ne yapar | Önerilen izinler |
|---|---|---|
| Teknisyen | Kendi atandığı **açık** iş emrine parça kullanımı ve iade girer; iş emri için parça talebi açar; stok miktarını görür (maliyeti görmez). | `warehouse.view`, **yeni** `stock.use` |
| Şef | Teknisyen gibi; birimindeki işlerin parça kullanımını görür/düzeltir (ters kayıt). | `warehouse.view`, `stock.use` |
| Depo sorumlusu | Katalog, mal kabul (giriş), transfer, sayım, düzeltme, parça taleplerini karşılama. | `warehouse.view`, `warehouse.manage` |
| Teknik Servis Müdürü / Yrd. | Görür, sayım farkını onaylar, raporları alır. Maliyeti `finance.prices.view` ile görür. | `warehouse.view`, `reports.view`, (isteğe bağlı `warehouse.manage`) |
| Muhasebe | Tüketim ve maliyet raporu (salt okuma). | `warehouse.view`, `reports.view`, `finance.prices.view` |

Yetki kişi bazında değiştirilebilir kalır; yukarıdakiler yalnızca rol şablonu önerisidir.

### 2.2 Tutulacak veriler

- **Parça kartı:** kod (tekil), ad, birim (Adet/Metre/Takım/Litre…; birim tam sayı mı ondalık mı), kategori, ilgili teknik birim (Güvenlik / Haberleşme / …, boş = ortak), uyumlu marka/model (serbest metin), üretici parça no (isteğe bağlı), aktif/pasif, iç birim maliyet (yetkili).
- **Depo bazında minimum** (az stok eşiği) ve bakiye.
- **Hareket defteri** (değiştirilemez): tür (`Giriş`, `Çıkış`, `İade`, `Transfer Çıkış`, `Transfer Giriş`, `Sayım Farkı`, `Ters Kayıt`, `Açılış`), parça, depo, miktar, birim maliyet anlık kopyası, iş emri (çıkış/iade için zorunlu), belge no (irsaliye/fiş), açıklama/gerekçe, ters kaydedilen hareketin kimliği, kaydeden, zaman.
- **Parça talebi:** iş emri, parça (veya katalogda yoksa serbest tanım), miktar, talep eden, durum (Açık / Karşılandı / İptal), karşılayan hareket.
- **Sayım:** depo, başlangıç/bitiş, sayan, her parça için sistem miktarı (anlık görüntü), sayılan miktar, fark, onaylayan.

### 2.3 Akışlar

1. **Mal kabul:** Depo → Giriş (depo, parça, miktar, belge no). Bakiye artar.
2. **İş emrine kullanım (ana akış):** Teknisyen iş emri detayında “Kullanılan Parçalar” bölümünden parça + depo + miktar seçer → Çıkış. Yalnızca açık (Kapatıldı/Tamamlandı/İptal olmayan) iş emrine. Stok yetmezse reddedilir ve “Parça talebi aç / Malzeme bekleniyor olarak beklet” seçeneği sunulur.
3. **İade:** Kullanılmayan parça aynı iş emrinden iade edilir; iade miktarı o iş emrine o parçadan yapılan net çıkışı aşamaz.
4. **Ters kayıt (düzeltme):** Yanlış hareket silinmez; karşı yönde, gerekçeli ve orijinaline bağlı bir kayıt atılır. Bir hareket yalnızca bir kez ters kaydedilebilir.
5. **Transfer:** Depo A → Depo B tek işlemde iki hareket.
6. **Sayım:** Depo seçilir, sistem miktarları anlık alınır, sayılan miktarlar girilir, farklar gerekçeyle “Sayım Farkı” hareketi olarak onaylanınca bakiyeye yansır.
7. **Parça talebi ↔ bekleme:** Talep açıldığında iş emri isteğe bağlı olarak mevcut “Beklemede / Malzeme Bekleniyor” akışına (`/api/ops/workorders/{id}/hold`) alınır; ilgili parçanın girişi yapıldığında talep sahibine ERP içi uyarı düşer.
8. **Planlı bakım formu:** Serbest metin alanı yerine (veya yanında) iş emrinin yapılandırılmış parça listesi gösterilir; basılı servis formu çıktısındaki “kullanılan parçalar” stok hareketlerinden gelir.

### 2.4 Raporlar / KPI'lar

- Az stok listesi (depo bazında + toplam), sıfır stoklu aktif parçalar.
- Dönemsel parça tüketimi: parça × ay, birim, müşteri, iş türü (günlük servis / planlı bakım ayrı).
- İş emri başına kullanılan parçalar; cihaz seri no / model bazında parça geçmişi (iş emrindeki seri üzerinden).
- Malzeme nedeniyle bekleyen işler ve ortalama bekleme süresi (açık parça talepleri).
- Sayım doğruluğu: sayım farkı adedi / tutarı (tutar yalnızca yetkiliye).
- Hareket defteri dışa aktarımı (CSV/Excel), maliyet sütunu yalnızca `finance.prices.view` ile.

### 2.5 Doğrulamalar

- Bakiye hiçbir koşulda < 0 olamaz (mevcut, korunacak).
- Tam sayı birimlerde ondalık miktar reddedilir.
- Çıkış/iade yalnızca kullanıcının erişebildiği **açık** iş emrine.
- İade ≤ net çıkış; ters kayıt tek sefer; transferde kaynak = hedef olamaz.
- Pasif parçaya yeni giriş/çıkış yapılamaz (iade ve ters kayıt hariç).
- Parça kodu tekrarı 409 + anlaşılır mesaj döndürür.
- Hareket kaydı güncellenemez/silinemez.
- `Σ hareket = bakiye` (parça × depo) her zaman sağlanır; sapma raporlanır.

---

## 3. Fark listesi (öncelik sırasıyla)

> Etiketler: **YENİ** (yok, eklenecek), **EKSİK** (var ama yetersiz), **HATA** (yanlış davranış), **GÜVENLİK**, **VERİ**. Efor: S (≤1 gün), M (2-4 gün), L (≥1 hafta).

### (c) Yeni özellikler

#### M11-01 — YENİ — İş emri detayında “Kullanılan Parçalar” ve teknisyen parça kullanımı (L)
- **Açıklama:** İş emri detayına parça kullanım bölümü: parça arama (kod/ad), depo seçimi, miktar, not. Yeni uçlar `GET /api/workorders/{id}/parts` (hareketler + net miktar) ve `POST /api/workorders/{id}/parts` (Çıkış). Yeni izin `stock.use`; `warehouse.manage` olmadan da kullanılabilir. Teknisyen yalnızca kendisine atanmış işe kayıt girer (ad eşleşmesi yerine kullanıcı kimliği hazır olduğunda kimlikle; o zamana kadar mevcut `filterOrders` kuralı). Maliyet alanları `finance.prices.view` olmadan dönmez.
- **Gerekçe:** “Hangi yedek parçalar kullanıldı?” sorusu (Proje Geçmişi §1) bugün cevaplanamıyor; parça kullanımını sahadaki kişi girmezse depodaki kayıt geç ve eksik olur.
- **Mevcut:** Çıkış yalnızca `OpsSuite.cs:188-213` üzerinden, `warehouse.manage` ile; hiçbir rolde bu izin yok (`Program.cs:3921-3935`). İş emri ekranında parça bölümü yok.
- **Kabul:** (1) `stock.use` sahibi teknisyen açık iş emrine 2 adet parça çıkışı yapar; bakiye 2 azalır, iş emri detayında satır görünür. (2) Aynı kullanıcı `Kapatıldı` iş emrine çıkış denediğinde 400. (3) Stoktan fazla miktar 400 “Stok yetersiz”. (4) `finance.prices.view` olmayan hesapla `GET /api/workorders/{id}/parts` yanıtında maliyet alanı yok. (5) `stock.use` olmayan hesap 403.
- **Roller/izin:** Teknisyen, Şef (`stock.use`, `warehouse.view`).
- **Veri:** Yeni izin anahtarı; `ServicePartMovements`'a `Note NVARCHAR(500) NULL`.
- **Bağımlılık:** M11-14 (kapalı işe çıkış engeli) aynı uçta uygulanmalı.

#### M11-02 — YENİ — İade ve ters kayıt (düzeltme) (M)
- **Açıklama:** `İade` türü (iş emrinden depoya) ve `Ters Kayıt` türü (herhangi bir hareketin gerekçeli tersine çevrilmesi, `ReversalOfMovementId` ile). Hareketler asla silinmez.
- **Gerekçe:** Bugün yanlış girilen bir hareket düzeltilemiyor; sahada kullanılmayan parça depoya geri alınamıyor (yalnızca örtük “Giriş+İş emri”).
- **Mevcut:** `Kind` yalnızca `Giriş`/`Çıkış` (`ZZ_V120:24`, `OpsSuite.cs:191`); iş emrine bağlı giriş finans hesabında örtük iade (`OpsSuite.cs:225`).
- **Kabul:** (1) 3 adet çıkış yapılan işe 1 adet iade → net 2, bakiye +1. (2) Aynı işe 3 adet daha iade → 400 (net çıkışı aşamaz). (3) Bir hareket ters kaydedilince bakiye eski hâline döner; aynı hareket ikinci kez ters kaydedilemez (400). (4) Ters kayıt gerekçesiz reddedilir. (5) Finans ekranındaki iş emri malzeme tutarı iade sonrası düşer, eksiye inmez.
- **Roller/izin:** İade: `stock.use`; ters kayıt: `warehouse.manage`.
- **Veri:** `Kind` CHECK genişletme; `ReversalOfMovementId BIGINT NULL` + filtreli UNIQUE indeks; `Note`.
- **Bağımlılık:** M11-01.

#### M11-03 — YENİ — Hareket geçmişi ekranı ve API (M)
- **Açıklama:** `GET /api/ops/stock/movements?partId&warehouseId&workOrderId&from&to&kind` (sayfalı) ve “Hareketler” sekmesi; CSV dışa aktarım (`reports.export`). İş emri numarası ve kaydeden ad gösterilir.
- **Gerekçe:** Changelog'da vaat edilen “hareket geçmişi” arayüzde yok; denetim ve hata ayıklama imkânsız.
- **Mevcut:** Hareketler yalnızca yazılıyor (`OpsSuite.cs:206`), okunan tek yer finans toplamı (`OpsSuite.cs:224-228`).
- **Kabul:** (1) Parça filtresiyle yalnızca o parçanın hareketleri, tarih sırasıyla gelir. (2) Kullanıcının göremediği birimdeki iş emrine bağlı hareketler listede yer almaz. (3) `UnitCost` yalnızca `finance.prices.view` ile döner. (4) CSV'de formül enjeksiyonu koruması (mevcut `Csv()` yardımcı fonksiyonu) uygulanır.
- **Roller/izin:** `warehouse.view`; dışa aktarım `reports.export`.
- **Veri:** Yok (indeks: `ServicePartMovements(PartId, WarehouseId, CreatedAt)`, `(WorkOrderId)`).
- **Bağımlılık:** —

#### M11-04 — YENİ — Depolar arası transfer (S)
- **Açıklama:** `POST /api/ops/stock/transfer` (parça, kaynak depo, hedef depo, miktar, not) tek işlemde `Transfer Çıkış` + `Transfer Giriş`.
- **Gerekçe:** Depo 1-3 arasında parça taşınması bugün ancak sahte çıkış/giriş ile yapılabiliyor (çıkış iş emri istediği için fiilen yapılamıyor).
- **Mevcut:** Yok.
- **Kabul:** (1) 5 adetlik transfer sonrası kaynak −5, hedef +5, iki hareket aynı `TransferGroupId` ile. (2) Kaynakta yetersiz stok → 400, hiçbir bakiye değişmez. (3) Kaynak = hedef → 400.
- **Roller/izin:** `warehouse.manage`.
- **Veri:** `Kind` CHECK genişletme; `TransferGroupId UNIQUEIDENTIFIER NULL`.
- **Bağımlılık:** —

#### M11-05 — YENİ — Stok sayımı (M)
- **Açıklama:** Depo bazında sayım oturumu: başlat (sistem miktarlarını anlık kaydet) → sayılan miktarları gir (ekrandan veya CSV) → farkları gör → gerekçeyle onayla → `Sayım Farkı` hareketleri. Sayım sırasında yapılan hareketler onay ekranında uyarı olarak gösterilir.
- **Gerekçe:** Kayıp/hasarlı/fazla parça bugün sisteme yansıtılamıyor; zamanla bakiye gerçeklikten kopar ve az stok uyarısı güvenilmez olur.
- **Mevcut:** Yok; çıkış iş emri zorunlu olduğu için düzeltme imkânı da yok (`OpsSuite.cs:192`).
- **Kabul:** (1) Sistem 10, sayılan 8 → onay sonrası bakiye 8, `Sayım Farkı −2` hareketi, gerekçe ve onaylayan kayıtlı. (2) Onaylanmamış sayım bakiyeyi değiştirmez. (3) Aynı depoda aynı anda iki açık sayım başlatılamaz. (4) Sayım raporu fark adedini gösterir; tutar yalnızca `finance.prices.view` ile.
- **Roller/izin:** Sayım girişi `warehouse.manage`; onay için VARSAYIM: aynı izin (ayrı onay izni gerekiyorsa bkz. Sorular).
- **Veri:** `ServiceStockCounts` (başlık), `ServiceStockCountLines` (PartId, SystemQty, CountedQty).
- **Bağımlılık:** M11-02 (Kind genişletme).

#### M11-06 — YENİ — Parça talebi ve “Malzeme bekleniyor” bağlantısı (M)
- **Açıklama:** İş emrinden parça talebi (katalogdaki parça veya serbest tanım + miktar). Depo ekranında açık talepler listesi. Talep açılırken isteğe bağlı olarak iş emri mevcut bekleme akışına “Malzeme Bekleniyor” nedeniyle alınır. Talep edilen parçanın girişi yapılınca talep sahibine ERP içi uyarı; çıkış yapılınca talep “Karşılandı”.
- **Gerekçe:** Malzeme nedeniyle geciken işler (Proje Geçmişi §5.10 bekleme nedenleri) bugün hangi parçayı beklediğini bilmiyor; depo hangi işin neyi beklediğini göremiyor.
- **Mevcut:** Bekleme nedeni serbest metin (`OpsSuite.cs:130-145`, `ops120.js:73`); parça ile bağ yok.
- **Kabul:** (1) Teknisyen talep açar, depo listesinde görünür. (2) İlgili parçaya giriş yapıldığında talep sahibinin Uyarılar sekmesinde “Parça geldi” uyarısı çıkar. (3) Aynı iş emrine o parçadan çıkış yapılınca talep otomatik “Karşılandı”. (4) İş emri iptal/kapandığında açık talepler “İptal” olur. (5) Rapor: açık talep sayısı ve ortalama bekleme günü.
- **Roller/izin:** Talep `stock.use`; karşılama `warehouse.manage`.
- **Veri:** `ServicePartRequests`.
- **Bağımlılık:** M11-01.

#### M11-07 — YENİ — Parça tüketim raporu ve iş emri/cihaz bazlı parça geçmişi (M)
- **Açıklama:** Rapor ekranı + Excel sayfası: parça × ay tüketimi, birim/müşteri/iş türü kırılımı (günlük servis ve planlı bakım ayrı), iş emri başına parçalar, seri no bazında parça geçmişi (iş emrindeki seri üzerinden). Mevcut 8 sayfalı Excel'e “Malzeme Hareketleri” sayfası.
- **Gerekçe:** Proje Geçmişi §7.1 “Malzeme giriş/çıkışı ve kayıtlı maliyetler” rapor kırılımı istiyor; bugün yok.
- **Mevcut:** Yalnızca finans ekranında iş başına malzeme TL toplamı (`OpsSuite.cs:224-234`).
- **Kabul:** (1) Seçilen ayda bir parçanın raporlanan toplam çıkışı, hareket defterindeki net çıkış (çıkış − iade − ters kayıt) ile birebir aynı. (2) Planlı bakım ve günlük servis ayrı sütunlarda. (3) Tutar sütunları yalnızca `finance.prices.view` ile; aksi hâlde Excel'de sütun hiç yok. (4) Hiç parça kullanılmamış iş “0 parça” olarak gösterilir; parça bilgisi yalnızca serbest metinde olan eski bakım formları “yapılandırılmamış kayıt” olarak ayrı işaretlenir.
- **Roller/izin:** `reports.view`, `reports.export`, maliyet için `finance.prices.view`.
- **Veri:** Yok.
- **Bağımlılık:** M11-01, M11-02.

### (b) Mevcut modül eksikleri ve hatalar

#### M11-08 — EKSİK — Parça kartı düzenleme, pasifleştirme ve birim (M)
- **Açıklama:** `PUT /api/ops/stock/part/{id}` (ad, birim, kategori, teknik birim, uyumlu model, üretici no, minimum, aktif/pasif); maliyet değişikliği yalnızca `finance.costs.manage` + `finance.prices.view`. Birim listesi ve “ondalık izinli mi” bayrağı. Kod tekrarı 409 + Türkçe mesaj. Parça silinmez, pasife alınır.
- **Gerekçe:** Yanlış yazılan parça adı veya minimum değer bugün düzeltilemiyor; kullanılmayan parça listeden çıkarılamıyor.
- **Mevcut:** Yalnızca INSERT (`OpsSuite.cs:177-187`), birim sabit `Adet` (185), tekrar kodda 500.
- **Kabul:** (1) Ad/minimum güncellenir, listede görünür. (2) Pasif parçaya giriş/çıkış 400; iade ve ters kayıt çalışır. (3) Aynı kodla ikinci parça → 409 “Bu parça kodu zaten kayıtlı.” (4) `finance.costs.manage` olmayan kullanıcı maliyet alanı gönderirse 403. (5) Pasif parçalar varsayılan listede gizli, “pasifleri göster” ile görünür.
- **Roller/izin:** `warehouse.manage` (+ maliyet için `finance.costs.manage`).
- **Veri:** `ServicePartCatalog`'a `IsActive BIT NOT NULL DEFAULT 1`, `Category`, `UnitCode NULL`, `CompatibleModels`, `ManufacturerPartNo`, `AllowFraction BIT DEFAULT 0`, `UpdatedBy/UpdatedAt`.
- **Bağımlılık:** —

#### M11-09 — EKSİK — Stok ekranını form tabanlı ve aranabilir hâle getirme (M)
- **Açıklama:** `prompt()` zinciri yerine modal formlar (mevcut app.js modal kalıbı): parça açılır arama, depo açılır listesi, iş emri **numarasıyla** arama. Stok listesi: arama, depo filtresi, “yalnızca az stok” filtresi, parça başına toplam + depo kırılımı. Mobil teknisyen panelinden (`mobile120`) iş emrine parça ekleme erişilebilir.
- **Gerekçe:** Kullanıcıdan iç ID yazması isteniyor (`ops120.js:85-89`); yanlış depoya/işe hareket riski yüksek ve sahada telefonla kullanılamaz.
- **Mevcut:** `ops120.js:10-14, 78-92`.
- **Kabul:** (1) Hiçbir stok işleminde kullanıcı sayısal ID yazmaz. (2) İş emri “IE-…”/“PB-…” numarasının bir kısmı yazılınca eşleşen açık işler listelenir. (3) 375 px genişlikte form yatay kaydırma olmadan kullanılır. (4) Az stok filtresi, Uyarılar sekmesindeki düşük stok sayısıyla aynı sayıda parça gösterir (M11-10 ile).
- **Roller/izin:** Mevcut izinler.
- **Veri:** Yok.
- **Bağımlılık:** M11-01, M11-10.

#### M11-10 — HATA — Az stok durumu ekranda depo bazında, uyarıda toplam bazında (S)
- **Açıklama:** Minimum eşiği **depo bazında** tanımlanabilir olsun (`ServiceStockMinimums(PartId, WarehouseId, MinimumQty)`); tanımlı değilse parça kartındaki toplam minimum kullanılır. Ekran rozeti ve uyarı **aynı fonksiyonla** hesaplanır. Hiç bakiyesi olmayan parça “Stok yok” olarak gösterilir (bugün “Kayıt bekliyor” adlı sahte depo).
- **Gerekçe:** Bugün parça Depo 1'de 5, Depo 2'de 0 ve minimum 3 ise ekran Depo 2 satırını “Azaldı” gösterir ama uyarı çıkmaz; yöneticiye çelişkili bilgi gider.
- **Mevcut:** Ekran `ops120.js:13` (`quantity < minimum`, satır bazında); uyarı `OpsSuite.cs:44-46` (toplam); “Kayıt bekliyor” `OpsSuite.cs:168`.
- **Kabul:** (1) Yukarıdaki örnekte ekran ve uyarı aynı sonucu verir. (2) Depo minimumu tanımlıysa uyarı mesajında depo adı yer alır. (3) Minimum 0 olan parça için uyarı üretilmez.
- **Roller/izin:** —
- **Veri:** `ServiceStockMinimums` (isteğe bağlı tablo).
- **Bağımlılık:** —

#### M11-11 — EKSİK — Giriş hareketinde belge no, açıklama ve giriş maliyeti (S)
- **Açıklama:** Girişte `DocumentNo` (irsaliye/fiş), `Note` ve (yetkiliyse) bu girişin birim maliyeti. Maliyet yöntemi kullanıcı kararına bağlı (bkz. Sorular); karar verilene kadar katalog maliyeti kullanılmaya devam eder ve girişte maliyet alanı yalnızca bilgi olarak saklanır.
- **Gerekçe:** Hangi parçanın hangi irsaliyeyle geldiği izlenemiyor; sayım farklarında geriye iz sürülemiyor.
- **Mevcut:** `MovementRequest` yalnızca parça/depo/iş emri/tür/miktar (`OpsSuite.cs:277`).
- **Kabul:** (1) Belge no ile girilen giriş, hareket geçmişinde belge no ile aranabilir. (2) `finance.costs.manage` olmayan kullanıcı maliyet gönderirse 403. (3) Belge no 50, not 500 karakterle sınırlı; aşımda 400.
- **Roller/izin:** `warehouse.manage`.
- **Veri:** `ServicePartMovements`'a `DocumentNo NVARCHAR(50) NULL`, `Note NVARCHAR(500) NULL`, `EntryUnitCost DECIMAL(18,2) NULL`.
- **Bağımlılık:** —

#### M11-12 — EKSİK — Rol şablonlarında stok izinleri (S)
- **Açıklama:** Yeni `stock.use` izni kataloğa eklenir. Şablon önerisi (VARSAYIM): Depo → `warehouse.manage`; Teknisyen, Şef → `warehouse.view` + `stock.use`; Teknik Servis Müdürü/Yrd. → `warehouse.view` (mevcut) + isteğe bağlı `warehouse.manage`. Mevcut kullanıcı profillerine otomatik dağıtılmaz (Proje Geçmişi §8.1); yönetici kişi bazında verir. Kullanıcı ekranında izin açıklamaları Türkçe ve anlaşılır.
- **Gerekçe:** Bugün `warehouse.manage` yalnızca Admin'de; modül fiilen yalnızca Admin tarafından kullanılabilir.
- **Mevcut:** `Program.cs:3895-3896, 3921-3935`.
- **Kabul:** (1) “Depo” şablonuyla yeni açılan kullanıcı giriş/transfer/sayım yapabilir. (2) “Teknisyen” şablonuyla açılan kullanıcı iş emrine parça kullanımı girebilir, katalog/giriş yapamaz (403). (3) Mevcut kullanıcıların izinleri yükseltme sonrası değişmemiştir (SQL'de önce/sonra karşılaştırma).
- **Roller/izin:** Tüm roller.
- **Veri:** Yeni izin anahtarı.
- **Bağımlılık:** M11-01.

#### M11-13 — EKSİK — Bakım formu ve atölye kaydında yapılandırılmış parça listesi (M)
- **Açıklama:** Planlı bakım dijital formunda “Kullanılan Yedek Parçalar” serbest metninin yanına iş emrinin stok hareketlerinden gelen parça listesi ve “Parça ekle” düğmesi (M11-01 bileşeni). Serbest metin alanı “Ek not / katalogda olmayan parça” olarak kalır. Haberleşme atölyesi kaydı bir iş emrine bağlıysa aynı bileşen görünür. Basılı servis formu çıktısında parça listesi stok hareketlerinden gelir.
- **Gerekçe:** Bugün teknisyen formda parçayı yazar, depo ayrıca hareket girer → çift kayıt ve tutarsızlık.
- **Mevcut:** `app.js:623, 647`; `Program.cs:2411-2429, 2515-2526, 3820`.
- **Kabul:** (1) PB iş emri formunda “Parça ekle” ile girilen parça bakiyeden düşer ve formda listelenir. (2) Form tamamlandıktan (iş kapandıktan) sonra parça eklenemez. (3) Eski serbest metin değerleri kaybolmaz, “Not” olarak görünür.
- **Roller/izin:** `stock.use`.
- **Veri:** Yok (mevcut `SpareParts` kolonu korunur).
- **Bağımlılık:** M11-01, M11-14.

#### M11-14 — HATA — Kapalı/iptal iş emrine stok çıkışı yapılabiliyor (S)
- **Açıklama:** Çıkış (ve yeni iade dışı tüm iş emrine bağlı hareketler) yalnızca durumu `Kapatıldı`, `Tamamlandı`, `İptal` olmayan iş emrine. Kapanmış işe sonradan parça yazmak gerekirse yalnızca `warehouse.manage` sahibi, zorunlu gerekçeyle yapabilir.
- **Gerekçe:** Kapalı işe sonradan malzeme yazılması iş maliyetini ve tüketim raporunu geriye dönük değiştirir (A3-18).
- **Mevcut:** `OpsSuite.cs:193` yalnızca erişim kontrolü yapıyor, durum kontrolü yok.
- **Kabul:** (1) `Kapatıldı` iş emrine `stock.use` ile çıkış → 400 “Kapalı iş emrine parça yazılamaz.” (2) `warehouse.manage` + gerekçe ile → başarılı, hareket notunda gerekçe. (3) Gerekçesiz → 400.
- **Roller/izin:** `stock.use`, `warehouse.manage`.
- **Veri:** Yok.
- **Bağımlılık:** —

#### M11-15 — HATA — İş emrine bağlı “Giriş” örtük iade sayılıyor ve sınırsız (S)
- **Açıklama:** M11-02 gelene kadar: iş emrine bağlı `Giriş` reddedilir **veya** o iş emrinde o parçanın net çıkışı ile sınırlandırılır. M11-02 sonrası iş emrine bağlı iade yalnızca `İade` türüyle yapılır.
- **Gerekçe:** Bugün 1 adet çıkış yapılan işe 10 adet “Giriş” yazılabilir; stok sahte artar, iş malzeme maliyeti eksiye düşer (`OpsSuite.cs:225`).
- **Mevcut:** `OpsSuite.cs:191-193` (yalnızca çıkışta iş emri zorunlu; girişte iş emri kontrolsüz kabul).
- **Kabul:** (1) Net çıkışı 1 olan işe 2 adet iş-emirli giriş → 400. (2) Finans ekranında hiçbir işin malzeme tutarı negatif değil (SQL kontrol sorgusu 0 satır).
- **Roller/izin:** —
- **Veri:** Yok.
- **Bağımlılık:** —

#### M11-16 — HATA — “Adet” birimli parçada ondalık miktar kabul ediliyor (S)
- **Açıklama:** Parçanın birimi ondalığa izin vermiyorsa (`AllowFraction=0`) tam sayı dışı miktar reddedilir. Ekranda sayı alanı birime göre `step` alır.
- **Gerekçe:** “1,5 adet konnektör” gibi hatalı kayıtlar sayım farkı üretir.
- **Mevcut:** `OpsSuite.cs:191` yalnızca aralık kontrolü; kolon DECIMAL(18,3).
- **Kabul:** (1) Adet biriminde 1.5 → 400. (2) Metre biriminde (`AllowFraction=1`) 1.5 → kabul.
- **Roller/izin:** —
- **Veri:** M11-08'deki `AllowFraction`.
- **Bağımlılık:** M11-08.

### (a) Veri bütünlüğü, güvenlik ve üretime hazırlık

#### M11-17 — VERİ — Açılış stoğu yükleme ve bakiye–hareket mutabakatı (M)
- **Açıklama:** (1) Canlıya geçişte mevcut fiziksel stok CSV ile `Açılış` hareketi olarak yüklenir (parça kodu, depo kodu, miktar); bilinmeyen kod/depo satır bazında raporlanır, hiçbir satır kısmi yüklenmez. (2) Mutabakat sorgusu/ucu: her (parça, depo) için `Σ hareket` ile `ServiceStockBalances.Quantity` karşılaştırması; fark varsa yönetim ekranında uyarı.
- **Gerekçe:** Bakiye tablosu ile hareket defteri ayrı tutuluyor; doğrudan SQL müdahalesi veya gelecekteki bir hata farkı sessizce oluşturabilir (A3-18). Gerçek stok sisteme hiç yüklenmemişse uyarılar anlamsızdır.
- **Mevcut:** Mutabakat yok; açılış için tek yol tek tek `Giriş`.
- **Kabul:** (1) 200 satırlık CSV yüklenir; bakiye toplamı CSV toplamına eşit. (2) Bir satırda bilinmeyen kod varsa hiçbir satır yüklenmez, hatalı satır numarası raporlanır. (3) Test DB'de bir bakiye SQL ile elle değiştirildiğinde mutabakat raporu o (parça, depo) çiftini gösterir. (4) Normal kullanım sonrası mutabakat 0 fark.
- **Roller/izin:** Yükleme `warehouse.manage`; mutabakat raporu `warehouse.view`.
- **Veri:** `Kind` CHECK'e `Açılış`.
- **Bağımlılık:** M11-02 (Kind genişletme).

#### M11-18 — VERİ — Eski serbest metin parça kayıtlarının korunması (S)
- **Açıklama:** `MaintenanceDeviceItems.SpareParts` (ve atölye `RepairInfo`) metinleri otomatik olarak stok hareketine dönüştürülmez (geriye dönük stok düşümü yaratır); raporlarda “yapılandırılmamış parça notu” olarak ayrı gösterilir.
- **Gerekçe:** Geçmiş veriyi bozmadan yeni yapıya geçiş; geriye dönük sahte stok hareketi üretmemek.
- **Mevcut:** `Program.cs:2411-2429` (okuma), `2515-2526` (yazma).
- **Kabul:** (1) Yükseltme sonrası eski metinler değişmeden okunur. (2) Yükseltme betiği `ServicePartMovements`'a satır eklemez (önce/sonra satır sayısı aynı).
- **Roller/izin:** —
- **Veri:** Yok.
- **Bağımlılık:** M11-07, M11-13.

#### M11-19 — GÜVENLİK — Hareket defterinin değiştirilemezliği, depo adı yetkisi ve maliyet görünürlüğü (S)
- **Açıklama:** (1) `ServicePartMovements` için UPDATE/DELETE yapan uç eklenmeyeceği kabul testine yazılır; uygulama SQL kullanıcısında bu tabloya DELETE/UPDATE izni kaldırılması İT ile değerlendirilir. (2) Depo adı değişikliği (`PUT /api/rentals/warehouses/{id}`) servis stok depolarını da etkilediği için `rentals.edit` **ve** `warehouse.manage` ya da yalnızca `warehouse.manage` istenir (karar: Sorular). (3) Yeni tüm stok uçlarında (M11-01, 03, 05, 07) `UnitCost`/tutar alanları `finance.prices.view` olmadan **yanıtta hiç yer almaz**; otomatik testle doğrulanır. (4) Parça kartında maliyet gönderimi `finance.costs.manage` **ve** `finance.prices.view` ister (bugün görmeden yazabiliyor, `OpsSuite.cs:181`).
- **Gerekçe:** Stok hareketleri maliyet ve tüketim raporunun temelidir; sessiz değişiklik veri bütünlüğünü bozar. Maliyet gizliliği kullanıcı kararıdır.
- **Mevcut:** Hareketler için güncelleme ucu yok (iyi); depo adı `Program.cs:1326`; maliyet kontrolü `OpsSuite.cs:173, 181`.
- **Kabul:** (1) `finance.prices.view` olmayan hesapla tüm stok GET uçlarının JSON yanıtında `cost`/`unitCost`/`amount` anahtarı bulunmaz. (2) `warehouse.manage` olmayan kullanıcı depo adını değiştiremez (403). (3) Kod taramasında `ServicePartMovements` üzerinde UPDATE/DELETE içeren SQL yoktur.
- **Roller/izin:** —
- **Veri:** Yok (isteğe bağlı DB izin ayarı).
- **Bağımlılık:** —

---

## 4. Kullanıcıya sorulması gerekenler

1. **Araç / teknisyen stoğu var mı?** Teknisyenlerin araçlarında sürekli parça bulunuyor mu? Varsa her araç (veya teknisyen) ayrı bir “depo” olarak tanımlanmalı ve sahadaki kullanım o depodan düşmeli.
2. **Depolar ortak mı?** Yedek parça stoğu, kiralama ile aynı Depo 1/2/3 fiziksel alanlarında mı tutuluyor, yoksa servis için ayrı depo tanımları mı gerekli?
3. **Parçalar birime göre ayrı mı?** Güvenlik Sistemleri ve Haberleşme aynı parça havuzunu mu kullanıyor, yoksa her birim yalnızca kendi parçalarını mı görmeli?
4. **Seri numaralı yedek parça var mı?** (Ör. telsiz anakartı, X-Ray jeneratör modülü.) Varsa bu parçalar seri bazlı izlenmeli mi (hangi cihaza hangi seri takıldı)?
5. **Maliyet yöntemi:** İç maliyet “son alış fiyatı” mı, “ağırlıklı ortalama” mı, yoksa “sabit katalog maliyeti” (bugünkü) mi olsun?
6. **Asıl stok kaydı hangi sistemde?** Muhasebe/satın alma tarafında başka bir stok kaydı (ör. Logo) varsa DengeERP'deki servis stoğu “asıl kayıt” mı, yoksa yalnızca servis içi izleme mi? (Entegrasyon kapsam dışı; yalnızca çift kayıt sorumluluğunu belirlemek için.)
7. **Sayım farkını kim onaylar?** Depo sorumlusu tek başına mı, yoksa Teknik Servis Müdürü onayı mı gerekli? Ayrı bir onay izni isteniyor mu?
8. **Kapanmış işe sonradan parça yazmaya** izin verilsin mi (gerekçeyle, yalnızca depo yetkilisi), yoksa tamamen yasak mı?
9. **Parça talebi akışı** isteniyor mu (M11-06), yoksa bugünkü gibi telefon/WhatsApp ile mi devam edilecek?
10. **Depo adlarını kim değiştirebilir?** Kiralama ekibi mi, depo sorumlusu mu, ikisi de mi?
11. **Açılış stoğu:** Mevcut fiziksel stok listesi Excel'de var mı? Canlıya geçişten önce tam sayım yapılacak mı?

## 5. Varsayımlar

- Rol önerileri organizasyon şeması gelmeden yapılmıştır; tümü VARSAYIM'dır.
- Kiralık cihaz envanteri (M06) ile servis yedek parça stoğu ayrı tablolarda kalır; bu belge yalnızca servis stoğunu kapsar.
- Satın alma siparişi, tedarikçi kartı, faturalama ve müşteriye parça satışı kapsam dışıdır (teknik servis dışı).
- Teknisyen ↔ kullanıcı kimlik bağlantısı (isim metni yerine kimlik) iş emirleri modülünde (M01) çözülür; bu modül o çözümü kullanır.
- Maliyet değerleri “iç maliyet / tahmini” niteliğindedir, resmi muhasebe kaydı değildir.
