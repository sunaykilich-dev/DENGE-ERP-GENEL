# M07 — Teklif ve İş Bazlı Maliyet / Finansal Görünürlük: Gereksinim Tasarımı

> **Sürüm tabanı:** DengeERP V1.20.1 (salt okunur kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Tarih:** 21.10.2026
> **Kapsam:** Kalemli teklif, PDF, e-posta gönderimi, onay akışı, iş emri bağlantısı, `finance.prices.view` ile API seviyesinde gizleme, süre × tarife + parça maliyeti, tahmini fark.
> **Kapsam dışı:** Logo CRM / Flowick entegrasyonu, fatura/muhasebe kaydı, bordro. Satış departmanının genel satış teklifleri de kapsam dışıdır; burada yalnızca **teknik servis teklifi** ele alınır.
> **Öncelik sırası (kullanıcı kararı):** önce (c) yeni özellik, sonra (b) mevcut eksikler, en son (a) güvenlik. Veri kaybı veya sızıntısı yaratan açıklar yine de **KRİTİK** diye işaretlenir. Bu modülde KRİTİK düzeyde açık bulunmadı; gerekçesi §3.3'te.

---

## 1. Mevcut durum (kod taraması)

### 1.1 API uçları

| Uç | Dosya:satır | İzin kontrolü | Gözlem |
|---|---|---|---|
| `GET /api/offers` | Program.cs:790-798 | `offers.view` + birim filtresi (bellekte) | Tüm teklifler tutarlarıyla döner. `finance.prices.view` kontrolü yok. `LoadOffersAsync` tüm tabloyu okuyor (3520-3539). |
| `POST /api/offers` | Program.cs:800-859 | `offers.create` + `UnitAllowed(request.UnitCode)` | `TKL-YYYYMM-####` numarası (814-821). Kalemler için doğrulama yok: negatif adet/fiyat, %100 üstü iskonto, rastgele KDV kabul ediliyor. `WorkOrderId` için varlık, birim ve erişim kontrolü yok. |
| `PATCH /api/offers/{id}/status` | Program.cs:861-881 | Yalnızca `offers.approve` | **Birim kontrolü yok.** Durum geçiş kuralı yok: her durumdan her duruma geçilebiliyor (Gönderildi → Taslak dahil). Hazırlayan kendi teklifini onaylayabiliyor. Geçmiş tutulmuyor. |
| `GET /api/offers/{id}/pdf` | Program.cs:883-893 | `offers.view` + birim | `BuildSimpleOfferPdf` (3573-3627) kullanılıyor. |
| `POST /api/offers/{id}/send` | Program.cs:895-958 | `offers.send` + birim + durum `Onaylandı` | SMTP ayarı `appsettings` içinde (909-930). Hata durumunda `ex.Message` hem istemciye hem `EmailLogs`'a yazılıyor (933-957). Gönderimden sonra durum `Müşteriye Gönderildi` oluyor, bu yüzden **yeniden gönderim engelleniyor** (904). |
| `GET /api/ops/finance` | OpsSuite.cs:214-236 | `finance.prices.view` **ve** `reports.view` | İş başına gelir, malzeme, işçilik, diğer, toplam, fark. Tarih filtresi yok; tüm iş emirleri hesaplanıyor. |
| `PUT /api/ops/finance/rate` | OpsSuite.cs:237-245 | `finance.prices.view` + `finance.costs.manage` + birim | Birim saatlik iç maliyeti **üzerine yazılıyor**; geçmiş tutulmuyor. |
| `PUT /api/ops/finance/{id}` | OpsSuite.cs:246-258 | `finance.prices.view` + `finance.costs.manage` + iş erişimi | Gelir ve diğer maliyet elle giriliyor. Değişiklik geçmişi yok; yalnızca son `UpdatedBy` tutuluyor. |
| `GET /api/ops/stock` | OpsSuite.cs:160-176 | `warehouse.view` | `cost` alanı `finance.prices.view` yoksa `null` (173). **Doğru uygulanmış.** |
| `POST /api/ops/stock/part` | OpsSuite.cs:177-187 | `warehouse.manage`; maliyet > 0 ise `finance.costs.manage` | Doğru. |
| `POST /api/ops/stock/movement` | OpsSuite.cs:188-213 | `warehouse.manage` | Çıkışta iş emri zorunlu. Hareket satırına `UnitCost` o anki değerle yazılıyor (206-211); bu iyi bir uygulama, maliyet geçmişi korunuyor. |
| Bakım sözleşmeleri | Program.cs:2329-2333 | `finance.prices.view` yoksa ücret alanları `null` | Doğru. |

### 1.2 Hesap kuralları

- **Teklif toplamı** (Program.cs:3504-3518): satır = adet × birim fiyat; iskonto = satır × %; KDV = (satır − iskonto) × %. Yuvarlama yalnızca toplamlarda yapılıyor, satır bazında yapılmıyor. Para birimi sabit TL.
- **İşçilik** (OpsSuite.cs:229-231): `Σ WorkOrderTimeLogs.Minutes / 60 × OpsLaborRates[iş emrinin birimi]`. Mola kayıtları `WorkOrderTimeLogs`'a yazılmıyor (Program.cs:2037), dolayısıyla molalar işçiliğe girmiyor; bu doğru. İptal edilen kayıtlar `IsVoided=0` filtresiyle dışarıda kalıyor (3432).
- **Malzeme** (OpsSuite.cs:224-228): `Σ Çıkış × UnitCost − Σ Giriş(iş emrine bağlı iade) × UnitCost`.
- **Fark** = gelir − (malzeme + işçilik + diğer) (232-234). Ekranda "resmi kârlılık değildir" uyarısı var (ops120.js:19).
- **Sorun:** Süre kaydı olmayan iş için `hours=0`, `labor=0` hesaplanıyor. Gelir girilmemiş iş için `revenue=0` ve fark negatif çıkıyor. Bu, "süre kaydı yoksa 'eksik' denir, 0 değil" kararına aykırı.

### 1.3 Tablolar

| Tablo | Script | Not |
|---|---|---|
| `Offers` | Database/DengeERP_Update.sql:189-213 | Revizyon, iptal nedeni, kabul/ret tarihi, para birimi ve hazırlayanın onaya gönderme kaydı yok. |
| `OfferItems` | DengeERP_Update.sql:216-230 | Kalem türü (parça/hizmet), katalog bağlantısı ve satır toplamı yok. `ON DELETE CASCADE` var, ancak silme ucu yok. |
| `EmailLogs` | DengeERP_Update.sql:233-247 | Gönderilen PDF'in hangi revizyon olduğu tutulmuyor. |
| `OpsLaborRates` | Database/ZZ_V120_Operations.sql:26-30 | Birim başına tek satır, geçerlilik tarihi yok. |
| `OpsWorkFinancials` | ZZ_V120_Operations.sql:32-33 | İş başına tek satır gelir/diğer maliyet, geçmiş yok. |
| `ServicePartCatalog` / `ServicePartMovements` | ZZ_V120_Operations.sql:17-24 | Hareket bazında maliyet anlık görüntüsü var. |

### 1.4 Ön yüz

| Ekran / işlev | Dosya:satır |
|---|---|
| Menü: "Teklif Yönetimi" (`offers.view`), "Maliyet Analizi" (`finance.prices.view` + `reports.view`), "Muhasebe" (`accounting.view`) | app.js:194, 185, 199 |
| Teklif listesi (PDF / Onayla / Mail Gönder) | app.js:1208-1215 |
| Muhasebe teklif görünümü (yalnızca liste, toplam) | app.js:1275-1278 |
| İş emri detayında "Bu İş İçin Teklif Oluştur" | app.js:1627, 1675 |
| Yeni teklif modalı + kalem satırları (yalnızca istemci tarafında `min=0`) | app.js:1880-1893 |
| Kiralamadan teklif kısayolu | app.js:1977 |
| PDF, onay ve gönder bağlamaları (alıcı `prompt` ile soruluyor) | app.js:1980-1982 |
| İş emri sonuç seçeneklerinde "Teklif Sunulacak" | app.js:603 |
| Maliyet analizi ekranı (ilk 350 satır), tarife düzenleme ve iş bazlı düzenleme `prompt` ile | ops120.js:15-21, 56, 93-99 |
| Stok iç maliyet sütunu `finance.prices.view` ile | ops120.js:13 |

**Eksik ekranlar:** teklif detay/düzenleme, ret/iptal, revizyon, iş emri detayında bağlı tekliflerin listesi, teklif filtreleri, maliyet analizinde tarih/birim filtresi ve dışa aktarma.

### 1.5 Rol varsayılanları (Program.cs:3921-3935)

| Rol | offers.view | create | approve | send | finance.prices.view | finance.costs.manage |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Admin | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Üst Yönetim / TS Müdürü / TS Müdür Yrd. | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Genel Koordinatör | ✓ | – | ✓ | – | – | – |
| Operasyon Uzmanı | ✓ | ✓ | – | – | – | – |
| Şef | ✓ | ✓ | – | – | – | – |
| Muhasebe | ✓ | – | ✓ | – | – | – |
| Kiralama Operasyon | ✓ | ✓ | – | – | – | – |
| Teknisyen / Depo / İK | – | – | – | – | – | – |

**Gözlem:** `finance.costs.manage` yalnızca Admin'de var; tarife ve gelir girişini pratikte yalnızca Admin yapabiliyor. `finance.prices.view` yetkisi olmayan Şef, Operasyon Uzmanı, Muhasebe ve Genel Koordinatör `GET /api/offers` üzerinden teklif tutarlarını görüyor. Bunun kasıtlı olup olmadığı soru olarak §5'te yer alıyor.

### 1.6 Test durumu

PILOT_V120_KURULUM_VE_TEST.txt:38-39'daki "finance.prices.view olmayan kişi 403 almalı" ve "gerçek teknisyen saatiyle maliyet" maddeleri işaretlenmemiş. Teklif modülü için yalnızca "teklif oluşturulur, PDF indirilir" (PILOT_KURULUM.txt:118) adımı tanımlı. **Canlı doğrulama yok.**

---

## 2. Olması gereken (Denge Elektronik teknik servis için hedef kurgu)

### 2.1 Roller

Organizasyon şeması henüz gelmedi; aşağıdaki rol dağılımı **varsayımdır**.

| Rol (varsayım) | Yaptığı iş | İzin |
|---|---|---|
| Şef / Operasyon Uzmanı | Arızadan sonra parça + işçilik teklifini hazırlar ve onaya gönderir. | `offers.view`, `offers.create` |
| TS Müdürü / Müdür Yrd. | Teklifi onaylar veya geri çevirir; hazırlayanla aynı kişi olamaz. | `offers.approve` |
| Onaylı teklifi gönderen kişi | Müşteriye e-posta ile gönderir, yeniden gönderir, müşteri yanıtını (kabul/ret) işler. | `offers.send` |
| Muhasebe | Kabul edilen teklifleri ve iş bazlı geliri görür, faturaya yönlendirir. | `offers.view`, `accounting.view`, isteğe bağlı `finance.prices.view` |
| Maliyet sorumlusu (Müdür veya Muhasebe, kişiye özel) | Birim saatlik iç maliyeti ve iş bazlı diğer maliyetleri girer. | `finance.prices.view` + `finance.costs.manage` |
| Teknisyen / Depo | Fiyat ve maliyet görmez. Parça çıkışı ve süre kaydı yaparak maliyete **veri sağlar**. | – |

### 2.2 Teklif yaşam döngüsü

```text
Taslak ──(onaya gönder)──► Onay Bekliyor ──(onayla)──► Onaylandı ──(e-posta / elle "gönderildi")──► Müşteriye Gönderildi
   ▲                           │(geri çevir + neden)                                                     │
   └───────────────────────────┘                                                ┌────────────────────────┼─────────────────┐
                                                                                ▼                        ▼                 ▼
                                                                         Kabul Edildi            Reddedildi(+neden)   Süresi Doldu (otomatik)
Her durumdan (Kabul hariç) ──► İptal (+neden)
Gönderilmiş teklifte değişiklik ──► yeni revizyon (R1, R2 …); eski revizyon "Revize Edildi" olur, salt okunur kalır
```

Temel kurallar:

- Yalnızca Taslak durumundaki teklif düzenlenebilir.
- Onaydan sonra fiyat değişirse yeni revizyon açılır.
- Hazırlayan kişi kendi teklifini onaylayamaz.
- Kabul edilen teklif, bağlı iş emrinin gelirine kaynak olur.
- Durum değişikliğinin tamamı kim/ne zaman/neden bilgisiyle tutulur.

### 2.3 Tutulacak veriler (artımlı ekleme)

- **Teklif başlığı:** revizyon no, kök teklif, müşteri irtibat kişisi, hazırlayan / onaya gönderen / onaylayan / gönderen, kabul/ret/iptal tarihi ve nedeni, son geçerlilik.
- **Kalem:** tür (Parça / İşçilik / Hizmet / Diğer), isteğe bağlı parça katalog bağlantısı, satır net toplamı (yuvarlanmış).
- **Durum geçmişi tablosu.**
- **Tarifeler:** geçerlilik başlangıç tarihli birim saatlik iç maliyet.
- **İş finansalı:** gelir kaynağı (Teklif / Elle / Sözleşme) ve değişiklik geçmişi.

### 2.4 Raporlar ve KPI'lar (az ama işe yarar)

1. **Bekleyen teklifler:** onay bekleyen ve müşteri yanıtı bekleyen teklifler; kaç gündür beklediği ve tutarı. Süresi 3 gün içinde dolacaklar ayrıca işaretlenir.
2. **Teklif dönüşümü (dönem, birim):** gönderilen / kabul / ret / süresi dolan adet ve tutar, kabul oranı, gönderimden yanıta ortalama gün, ret nedeni dağılımı.
3. **İş bazlı tahmini fark (dönem = kapanış tarihi):** gelir, malzeme, işçilik, diğer, fark. **Veri tamlığı** sütunları: süre kaydı eksik, gelir kaydı yok. Bunlar birim, iş türü (günlük servis / planlı bakım) ve müşteri kırılımında verilir.
4. **Veri kalitesi göstergesi:** kapanmış işlerde süre kaydı eksik iş oranı ve parça çıkışı olmayan ama "parça kullanıldı" notu bulunan işler (isteğe bağlı).

### 2.5 Doğrulamalar

- Adet > 0.
- Birim fiyat ≥ 0.
- İskonto 0–100.
- KDV yalnızca tanımlı oranlardan (varsayılan 0 / 1 / 10 / 20).
- Açıklama 1–500 karakter.
- En az 1, en çok 200 kalem.
- Müşteri adı zorunlu.
- E-posta biçimi geçerli.
- Geçerlilik tarihi bugünden önce olamaz.
- `WorkOrderId` verilmişse iş emri var olmalı, kullanıcının erişebildiği iş emirlerinden olmalı ve birimi teklif birimiyle aynı olmalı.
- Tutarlar sunucuda yeniden hesaplanır; istemciden gelen toplam kullanılmaz (bu kural bugün de uygulanıyor).

---

## 3. Fark listesi (mevcut → olması gereken)

Sıralama kullanıcı önceliğine göredir: önce YENİ, sonra EKSİK / HATA / VERİ, en son GÜVENLİK.

### M07-01 — Teklif düzenleme ve revizyon [YENİ] (M)
- **Açıklama:** `PUT /api/offers/{id}` ile yalnızca Taslak durumundaki teklif düzenlenebilir. `POST /api/offers/{id}/revise` gönderilmiş veya onaylanmış teklifin kalemlerini yeni revizyon olarak kopyalar: numara `TKL-202610-0007-R1` biçiminde olur, eskisi "Revize Edildi" durumuna geçer ve salt okunur kalır. Teklif detay ekranında revizyon zinciri gösterilir.
- **Gerekçe:** Bugün teklif oluşturulduktan sonra değiştirilemiyor. Müşteri pazarlığı veya parça değişikliğinde yeni teklif açılıyor ve iz kayboluyor.
- **Mevcut durum:** Yalnızca POST var (Program.cs:800-859); düzenleme/silme ucu ve ekranı yok (app.js:1886-1893).
- **Kabul kriterleri:**
  1. Taslak teklifte kalem fiyatı değiştirilince toplamlar sunucuda yeniden hesaplanır.
  2. Onay Bekliyor veya sonraki durumdaki teklife PUT isteği 409 döner.
  3. Revize edilen teklif yeni numarayla Taslak olarak açılır, eski revizyon "Revize Edildi" olur ve düzenlenemez.
  4. Detayda R0→R1→R2 zinciri görünür.
- **Roller:** hazırlayan `offers.create`; revizyon açmak için `offers.create`.
- **Veri değişikliği:** `Offers.RevisionNo INT DEFAULT 0`, `Offers.RootOfferId BIGINT NULL`, `Offers.UpdatedAt`.
- **Bağımlılık:** M07-02.

### M07-02 — Onay akışı ve durum geçiş kuralları [EKSİK] (M)
- **Açıklama:** §2.2'deki durum makinesi sunucuda uygulanır. Ayrı uçlar açılır: `submit` (onaya gönder, `offers.create`), `approve` / `return` (geri çevirme nedeni zorunlu, `offers.approve`), `customer-response` (Kabul / Ret + neden, `offers.send`), `cancel` (neden zorunlu). "Süresi Doldu" durumu, `ValidUntil` geçmişse ve teklif Müşteriye Gönderildi durumundaysa okuma sırasında hesaplanır. Hazırlayan ile onaylayan aynı kullanıcı olamaz (Admin hariç; bu istisna da loglanır). Ekranda her durum için yalnızca geçerli butonlar gösterilir.
- **Gerekçe:** Bugün herhangi bir durumdan herhangi bir duruma geçilebiliyor. Gönderilmiş bir teklif Taslak'a çekilebiliyor, Kabul/Ret butonu yok ve kimin onayladığı dışında hiçbir geçiş izlenmiyor.
- **Mevcut durum:** Program.cs:861-881 (izin verilen durum listesi var, geçiş kuralı yok); app.js:1214'te yalnızca "Onayla" ve "Mail Gönder" butonları var.
- **Kabul kriterleri:**
  1. Taslak → Kabul Edildi isteği 409 döner.
  2. Hazırlayanın kendi teklifini onaylama isteği 403 döner.
  3. Geri çevirme ve ret işlemlerinde neden boşsa 400 döner.
  4. `ValidUntil` dünü gösteren ve Müşteriye Gönderildi durumundaki teklif listede "Süresi Doldu" görünür.
  5. Her geçiş `OfferStatusHistory` tablosuna kullanıcı, zaman, eski/yeni durum ve neden ile yazılır ve detay ekranında listelenir.
- **Roller:** `offers.create`, `offers.approve`, `offers.send`.
- **Veri değişikliği:** Yeni tablo `OfferStatusHistory(OfferStatusHistoryId, OfferId, FromStatus, ToStatus, Reason, UserId, ChangedAt)`. `Offers` tablosuna `SubmittedByUserId`, `SubmittedAt`, `ClosedReason`, `CustomerRespondedAt` eklenir.
- **Bağımlılık:** –

### M07-03 — Teklif ↔ iş emri bağlantısı [YENİ] (S)
- **Açıklama:**
  - İş emri detayında "Teklifler" bölümü yer alır (no, revizyon, durum, tutar; tutar yalnızca `offers.view` sahibine görünür).
  - İş emri sonucu "Teklif Sunulacak" seçilince teklif oluşturma kısayolu önerilir.
  - Teklif onaya gönderildiğinde iş emri isteğe bağlı olarak "Teklif / Müşteri onayı" nedeniyle bekletilir (mevcut `/api/ops/workorders/{id}/hold` mantığı kullanılır).
  - Teklif kabul edilince bu bekleme otomatik kaldırılır; ret durumunda bekleme kalır ve şefe ERP içi uyarı düşer.
- **Gerekçe:** Teknik serviste en sık bekleme nedeni müşteri onayıdır. Bugün teklif ile iş emri arasında yalnızca tek yönlü bir `WorkOrderId` alanı var; iş emri ekranı bağlı teklifi göstermiyor.
- **Mevcut durum:** app.js:1627 (yalnızca oluşturma butonu), app.js:603 (sonuç seçeneği), OpsSuite.cs:130-159 (bekleme mekanizması).
- **Kabul kriterleri:**
  1. Bir iş emrine bağlı iki teklif varsa iş emri detayında ikisi de görünür.
  2. "Beklet" seçeneği işaretli teklif onaya gönderildiğinde iş emri durumu Beklemede olur ve bekleme nedeni "Teklif onayı" görünür.
  3. Teklif kabul edilince iş emri önceki durumuna döner.
  4. `offers.view` yetkisi olmayan kullanıcının iş emri detayında teklif tutarı görünmez ve API'de tutar alanı yer almaz.
- **Roller:** `workorders.view`, `offers.view`, `offers.create`.
- **Veri değişikliği:** `Offers.HoldsWorkOrder BIT DEFAULT 0`. `OpsHolds` kaydına `OfferId` bağlantısı (NULL olabilir).
- **Bağımlılık:** M07-02, M07-08.

### M07-04 — Kabul edilen teklifin iş gelirine aktarılması [YENİ] (S)
- **Açıklama:** Teklif "Kabul Edildi" olduğunda bağlı iş emrinin `OpsWorkFinancials.Revenue` alanı, teklifin **KDV hariç net tutarı** ile önerilir/doldurulur ve gelir kaynağı "Teklif TKL-…" olarak işaretlenir. Aynı iş emrine birden fazla kabul edilmiş teklif varsa net tutarlar toplanır. Elle değiştirmek mümkündür, ancak not zorunludur ve kaynak "Elle" olur.
- **Gerekçe:** Bugün gelir yalnızca `prompt` ile elle giriliyor (ops120.js:93-99). Teklif ile gelir arasında bağ olmadığından tahmini fark büyük ölçüde boş veya tutarsız kalıyor.
- **Mevcut durum:** OpsSuite.cs:246-258; teklif ile `OpsWorkFinancials` arasında hiçbir bağ yok.
- **Kabul kriterleri:**
  1. 10.000 TL + %20 KDV'li teklif kabul edilince Maliyet Analizi'nde gelir 10.000,00 TL görünür ve kaynak "Teklif" olur.
  2. Gelir elle değiştirilirken not boşsa 400 döner.
  3. Teklif iptal edilir veya revize edilirse "Teklif" kaynaklı gelir otomatik geri alınır; değişiklik M07-09 geçmişine düşer.
- **Roller:** sistem otomatik yapar; elle değişiklik `finance.costs.manage`.
- **Veri değişikliği:** `OpsWorkFinancials.RevenueSource NVARCHAR(20)` (Teklif / Elle / Sözleşme) ve `OpsWorkFinancials.RevenueOfferIds NVARCHAR(200)`, ya da daha temizi bir bağlantı tablosu.
- **Bağımlılık:** M07-02. Planlı bakım geliri için §5, soru 3.

### M07-05 — Kurumsal ve eksiksiz teklif PDF'i [HATA] (M)
- **Açıklama:** PDF Türkçe karakter destekli gömülü fontla üretilir. Tüm kalemler çok sayfalı tablo olarak basılır; her satırda satır net tutarı yer alır. Başlıkta firma bilgisi ve logo, revizyon no, hazırlayan/onaylayan, ödeme/teslim/garanti şartları ve geçerlilik; altta sayfa no bulunur. KDV oranı bazında KDV dökümü verilir. Gönderilen PDF'in özet değeri (SHA-256) loglanır.
- **Gerekçe:**
  - **Hata 1:** `offer.Items.Take(15)` (Program.cs:3588) 16. ve sonraki kalemleri PDF'ten **sessizce düşürüyor**, oysa toplamlar tüm kalemleri içeriyor. Müşteri toplamı tutmayan bir belge alıyor.
  - **Hata 2:** `ToAscii` (Program.cs:3629-3636) Türkçe karakterleri bozuyor (İ→I, ş→s, diğer karakterler "?").
  - **Hata 3:** Tek sayfa ve sabit satır aralığı; uzun açıklama sayfa dışına taşıyor.
- **Mevcut durum:** Program.cs:3573-3627, el yazımı PDF 1.4 + Helvetica. CHANGELOG_PILOT_V1.txt:36 kurumsal şablonu açık iş olarak listeliyor.
- **Kabul kriterleri:**
  1. 40 kalemli teklifin PDF'inde 40 kalemin tamamı vardır ve satır toplamlarının toplamı "Ara Toplam − İskonto" ile kuruşu kuruşuna eşittir.
  2. "Şişli İletişim Çözümleri – Güç Kaynağı" metni PDF'te aynen okunur.
  3. PDF bir PDF doğrulayıcıdan (örneğin `qpdf --check`) hatasız geçer.
  4. 500 karakterlik açıklama sarılarak basılır ve sayfa dışına taşmaz.
- **Roller:** `offers.view`.
- **Veri değişikliği:** Firma bilgisi ve şartlar için ayar kaydı (`AppSettings` tablosu veya `appsettings` bölümü). `EmailLogs.PdfSha256`.
- **Bağımlılık:** PDF kütüphanesi seçimi (§5, soru 6).

### M07-06 — E-posta gönderiminin tamamlanması [EKSİK] (S)
- **Açıklama:**
  - "Müşteriye Gönderildi" durumundaki teklif yeniden gönderilebilir (örneğin müşteri e-postayı kaybetti).
  - Alıcı adresi sunucuda doğrulanır; en çok 3 adres virgülle girilebilir.
  - Gönderen kullanıcı ve hazırlayan BCC/CC'ye eklenir.
  - Gönderim geçmişi teklif detayında listelenir (kime, ne zaman, kim, sonuç).
  - Hata durumunda istemciye genel bir mesaj döner; teknik ayrıntı yalnızca sunucu loguna yazılır.
  - E-posta gövdesine revizyon no ve geçerlilik tarihi eklenir.
  - **SMTP yoksa:** "Elle gönderildi olarak işaretle" seçeneği ile Onaylandı → Müşteriye Gönderildi geçişi yapılır ve kanal (e-posta dışı / elden / WhatsApp) not olarak tutulur.
- **Gerekçe:** Bugün tek gönderim hakkı var (Program.cs:904). SMTP henüz kurulmadığı için akış pratikte "Onaylandı" durumunda takılıyor. `ex.Message` hem kullanıcıya hem DB'ye yazılıyor (936, 957).
- **Mevcut durum:** Program.cs:895-958; app.js:1982 (`prompt` ile alıcı).
- **Kabul kriterleri:**
  1. Gönderilmiş teklif ikinci kez gönderilebilir ve `EmailLogs` tablosunda 2 kayıt oluşur.
  2. `abc@` adresi 400 döner.
  3. SMTP hatasında yanıt gövdesinde sunucu adı veya istisna metni geçmez.
  4. SMTP ayarı yokken "Elle gönderildi" işlemi durumu değiştirir ve geçmişe "Kanal: Elden" olarak düşer.
- **Roller:** `offers.send`.
- **Veri değişikliği:** `EmailLogs.Channel NVARCHAR(30)`, `EmailLogs.PdfSha256`.
- **Bağımlılık:** M07-02. SMTP bilgilerini İT sağlayacak.

### M07-07 — Teklif kaydında sunucu tarafı doğrulama [HATA] (S)
- **Açıklama:** §2.5'teki doğrulamalar `POST` ve `PUT` uçlarında uygulanır. `WorkOrderId` için varlık, kullanıcının erişebildiği iş emri olması (`FilterWorkOrdersForUser`) ve birim eşleşmesi kontrol edilir. Satır net tutarı satır bazında 2 haneye yuvarlanır ve toplamlar yuvarlanmış satırların toplamı olur; böylece PDF satırları ile toplam arasındaki kuruş farkı ortadan kalkar.
- **Gerekçe:** İstemcideki `min=0` atlanabilir. API bugün negatif adet, %150 iskonto, %37 KDV ve başka birimin veya erişilemeyen bir iş emrinin ID'sini kabul ediyor (Program.cs:806-855).
- **Mevcut durum:** Yalnızca "en az bir kalem" kontrolü var (806).
- **Kabul kriterleri:** Aşağıdaki isteklerin her biri 400 veya 403 döner ve hiçbir kayıt oluşmaz:
  1. `quantity:-1`
  2. `discountPercent:150`
  3. `vatPercent:37`
  4. Boş açıklama
  5. Erişilemeyen birimdeki iş emrinin ID'si
  6. Var olmayan `workOrderId`

  Ayrıca 3 × 33,333 TL'lik kalemde satır toplamı ve genel toplam tutarlı yuvarlanır.
- **Roller:** `offers.create`.
- **Veri değişikliği:** `OfferItems.LineNet DECIMAL(18,2)`. İsteğe bağlı CHECK kısıtları: `Quantity > 0`, `DiscountPercent BETWEEN 0 AND 100`.
- **Bağımlılık:** –

### M07-08 — Teklif listesi: filtre, detay ve bekleyen teklif takibi [EKSİK] (S)
- **Açıklama:**
  - Teklif listesine durum, birim, müşteri, tarih aralığı ve "yanıt bekleyen" filtreleri eklenir.
  - Teklif detayı (kalemler, revizyonlar, durum ve gönderim geçmişi) açılır.
  - "Bekleyen teklifler" kutusu: onay bekleyen + müşteri yanıtı bekleyen adet ve tutar, en eski bekleme günü. Geçerliliği 3 gün içinde dolacak teklifler için ERP içi uyarı (mevcut `/api/ops/overview` uyarı yapısına eklenir).
  - Liste API'si SQL tarafında birim ve tarih filtresi uygular; bugünkü gibi tüm tabloyu belleğe almaz.
- **Gerekçe:** Bugün tek, filtresiz bir liste var (app.js:1208-1215). Takip edilmeyen teklif hem gelir kaybı hem de iş emrinin uzun süre beklemesi demek.
- **Mevcut durum:** Program.cs:790-798 ve 3520-3539.
- **Kabul kriterleri:**
  1. "Müşteriye Gönderildi + son 30 gün" filtresi yalnızca uyan kayıtları getirir.
  2. Geçerliliği 2 gün sonra dolacak teklif için operasyon merkezinde "Teklif süresi doluyor" uyarısı görünür.
  3. Kullanıcının yetkisi olmayan birimin teklifi hiçbir filtre kombinasyonunda dönmez.
- **Roller:** `offers.view`.
- **Veri değişikliği:** `Offers(Status, UnitCode, CreatedAt)` indeksi.
- **Bağımlılık:** M07-02.

### M07-09 — Maliyet analizinde eksik veri ayrımı ("eksik", 0 değil) [VERİ] (S)
- **Açıklama:** `/api/ops/finance` her iş için `hours=null` ve `laborStatus="Süre kaydı eksik"` döner; böyle işlerde işçilik "—" gösterilir. Gelir girilmemiş işte `revenue=null`, `revenueStatus="Gelir kaydı yok"` olur ve **fark hesaplanmaz** ("Hesaplanamadı" yazılır). Ekran toplamları, eksik kayıtlı işleri ayrı bir sayaçla gösterir ("12 işte süre eksik, toplama dahil değil"). Tahmini süre hiçbir koşulda yerine konmaz.
- **Gerekçe:** Bugün süre kaydı olmayan iş 0 TL işçilikle, gelir girilmemiş iş ise negatif farkla görünüyor (OpsSuite.cs:229-234). Bu, "süre kaydı yoksa eksik denir, 0 değil" kararına aykırı ve yöneticiyi yanlış "zarar" sonucuna götürür. Planlı bakım işlerinin neredeyse tamamı gelirsiz göründüğü için toplu "zarar" izlenimi yaratır.
- **Mevcut durum:** OpsSuite.cs:224-235; ops120.js:18-21.
- **Kabul kriterleri:**
  1. Hiç `WorkOrderTimeLogs` kaydı olmayan kapalı iş, listede "Süre kaydı eksik" görünür ve API'de `labor:null` döner.
  2. Geliri olmayan işte `margin:null` döner.
  3. Ekrandaki "Fark" toplamı yalnızca geliri ve süresi tam olan işleri içerir; dışarıda kalan işlerin sayısı yanında yazılır.
- **Roller:** `finance.prices.view` + `reports.view`.
- **Veri değişikliği:** Yok (hesap değişikliği).
- **Bağımlılık:** –

### M07-10 — Saatlik iç maliyet tarifesinin geçerlilik tarihli tutulması [VERİ] (S)
- **Açıklama:** `OpsLaborRates` geçerlilik başlangıç tarihli satırlara dönüştürülür. İşçilik, her süre kaydının `StartedAt` tarihinde geçerli olan tarife ile hesaplanır. Tarife değişikliği kim/ne zaman bilgisiyle saklanır ve geçmişe dönük tarih girilemez (Admin hariç, gerekçeli).
- **Gerekçe:** Bugün tarife güncellemesi `UPDATE … SET HourlyCost` (OpsSuite.cs:242) ile yapılıyor. Tarife değişince **geçmiş tüm işlerin işçilik maliyeti ve farkı geriye dönük değişiyor** ve önceki raporlar yeniden üretilemiyor. Parça tarafında bu sorun yok, çünkü hareket satırında maliyet saklanıyor.
- **Mevcut durum:** ZZ_V120_Operations.sql:26-30; OpsSuite.cs:222-223, 231, 237-245.
- **Kabul kriterleri:**
  1. 1 Ekim'de 500 TL/sa, 1 Kasım'da 600 TL/sa tanımlanırsa Ekim'deki 2 saatlik kayıt 1.000 TL, Kasım'daki 2 saatlik kayıt 1.200 TL hesaplanır.
  2. Kasım tarifesi girildikten sonra Ekim raporu değişmez.
  3. Tarife geçmişi ekranında kullanıcı ve tarih görünür.
- **Roller:** `finance.prices.view` + `finance.costs.manage`.
- **Veri değişikliği:** Yeni tablo `OpsLaborRateHistory(UnitCode, ValidFrom DATE, HourlyCost, CreatedBy, CreatedAt)`; mevcut değerler `ValidFrom = 2026-01-01` (varsayım) olarak taşınır.
- **Bağımlılık:** –

### M07-11 — Maliyet analizi: dönem/birim/iş türü filtresi, özet ve dışa aktarma [EKSİK] (M)
- **Açıklama:**
  - `/api/ops/finance` uç noktasına `start`/`end` (kapanış tarihi; varsayılan son 30 gün), `unit`, `type` (günlük servis / planlı bakım) ve `onlyClosed` parametreleri eklenir.
  - Ekranda birim, iş türü ve müşteri kırılımında özet tablo; satırda iş emrine gidiş.
  - Excel/CSV dışa aktarma `finance.prices.view` + `reports.export` gerektirir.
  - Ekrandaki 350 satır sınırı yerine sayfalama kullanılır.
- **Gerekçe:** Bugün tüm zamanların bütün işleri tek listede hesaplanıyor (OpsSuite.cs:218), ekran yalnızca ilk 350 satırı gösteriyor (ops120.js:21) ve dışa aktarma yok. Yönetimin "geçen ay Haberleşme servis işlerinde fark ne?" sorusu cevaplanamıyor.
- **Mevcut durum:** OpsSuite.cs:214-236; ops120.js:15-21.
- **Kabul kriterleri:**
  1. `start=2026-10-01&end=2026-10-31&unit=Haberleşme&type=servis` yalnızca o kapsamdaki kapanmış işleri döndürür.
  2. Özet satırındaki toplam, detay satırlarının toplamına eşittir.
  3. `reports.export` yetkisi olmayan kullanıcıya dışa aktarma 403 döner.
  4. `finance.prices.view` yetkisi olmayan kullanıcıya hem ekran hem dışa aktarma 403 döner.
  5. Dışa aktarılan dosyada M07-09'daki eksik veri işaretleri yer alır.
- **Roller:** `reports.view`, `reports.export`, `finance.prices.view`.
- **Veri değişikliği:** Yok.
- **Bağımlılık:** M07-09.

### M07-12 — Teklif dönüşüm ve bekleyen teklif raporu [YENİ] (S)
- **Açıklama:** Dönem ve birim bazında gönderilen / kabul / ret / süresi dolan teklif adet ve tutarı (KDV hariç), kabul oranı, gönderimden yanıta ortalama gün, ret nedeni dağılımı ve en uzun bekleyen 20 teklif raporlanır. Mevcut Excel raporuna "Teklifler" sayfası olarak eklenir.
- **Gerekçe:** Teknik servis yönetimi hangi tekliflerin geri döndüğünü ve hangilerinin unutulduğunu bugün göremiyor.
- **Mevcut durum:** Yok. Muhasebe görünümü yalnızca durum listesi (app.js:1275-1278).
- **Kabul kriterleri:**
  1. Örnek veri: 10 gönderilen, 6 kabul, 2 ret, 2 süresi dolan. Bu veride kabul oranı %60, ret nedenleri 2 kayıt olarak görünür.
  2. Revize edilen teklif yalnızca son revizyonuyla sayılır ve çift sayılmaz.
  3. Birim yetkisi dışındaki teklifler rapora girmez.
- **Roller:** `reports.view` + `offers.view`; tutar sütunları için kullanıcının cevabına göre (§5, soru 1).
- **Veri değişikliği:** Yok (M07-02 verisi kullanılır).
- **Bağımlılık:** M07-02.

### M07-13 — Gelir ve maliyet değişiklik geçmişi [VERİ] (S)
- **Açıklama:** `OpsWorkFinancials` üzerindeki her değişiklik (gelir, diğer maliyet, gelir kaynağı) eski ve yeni değer, kullanıcı, zaman ve not ile `OpsWorkFinancialsHistory` tablosuna yazılır. İş bazlı maliyet satırında "geçmiş" bağlantısı bulunur.
- **Gerekçe:** Bugün yalnızca son `UpdatedBy` ve `UpdatedAt` tutuluyor (OpsSuite.cs:253). Kimin, hangi değeri, neden değiştirdiği izlenemiyor; finansal veride bu bir denetim boşluğu.
- **Mevcut durum:** ZZ_V120_Operations.sql:32-33.
- **Kabul kriterleri:**
  1. Bir işin geliri 3 kez değiştirildiğinde geçmişte 3 kayıt ve her kayıtta eski → yeni değer görünür.
  2. Geçmiş, `finance.prices.view` yetkisi olmayan kullanıcıya 403 döner.
- **Roller:** `finance.prices.view` (görme), `finance.costs.manage` (değiştirme).
- **Veri değişikliği:** Yeni tablo `OpsWorkFinancialsHistory`.
- **Bağımlılık:** M07-04 ile birlikte yapılması önerilir.

### M07-14 — Teklif durum değişikliğinde birim/erişim kontrolü [GÜVENLİK] (S)
- **Açıklama:** `PATCH /api/offers/{id}/status` ve M07-02'deki tüm yeni durum uçlarında teklif yüklenir ve `UnitAllowed(user, offer.UnitCode)` kontrol edilir; erişim yoksa 404 döner (varlık sızdırılmaz).
- **Gerekçe:** Bugün yalnızca `offers.approve` kontrol ediliyor (Program.cs:865). Örneğin yalnızca "Haberleşme" birimine yetkili bir onaylayıcı, ID tahmin ederek Güvenlik Sistemleri teklifini onaylayabiliyor, reddedebiliyor veya Taslak'a çekebiliyor. Veri silinmiyor, ancak bütünlük ve yetki ihlali var. KRİTİK sayılmadı: kayıt kaybı veya fiyat sızıntısı yaratmıyor.
- **Mevcut durum:** Program.cs:861-881.
- **Kabul kriterleri:** `AllowedUnits=Haberleşme` olan kullanıcı Güvenlik Sistemleri birimindeki bir teklifin durumunu değiştirmeye çalıştığında 404 alır ve teklif durumu değişmez.
- **Roller:** `offers.approve`, `offers.send`, `offers.create`.
- **Veri değişikliği:** Yok.
- **Bağımlılık:** –

### M07-15 — Fiyat/maliyet sızıntısı için otomatik API yetki testleri [GÜVENLİK] (M)
- **Açıklama:** Bir test projesi (xUnit + `WebApplicationFactory` + test DB) ile şu senaryolar otomatikleştirilir:
  1. `finance.prices.view` yetkisi olmayan kullanıcıda `/api/ops/finance` → 403, `/api/ops/stock` → `cost:null`, bakım sözleşmelerinde ücret alanları `null`, M07-03'teki iş emri teklif özeti → tutar alanı yok.
  2. `finance.costs.manage` yetkisi olmayan kullanıcıda `PUT /api/ops/finance/*` → 403.
  3. Teklif tutarlarının hangi izinle görüneceği §5 soru 1'in cevabına göre test edilir.
  4. Yetki değiştirildiğinde mevcut oturumda etkinin ne zaman başladığı test edilir. Oturum bellekte tutulduğu için yetki değişikliği oturuma yansımayabilir; bu davranış oturum modülüyle birlikte doğrulanır.
- **Gerekçe:** Proje kararı fiyat/maliyetin **API seviyesinde** gizlenmesi. Bu kural PILOT_V120 test listesinde (satır 38) işaretlenmemiş, kanıt yok. Yeni uçlar (M07-03, M07-11, M07-12) eklendikçe sızıntı riski artar.
- **Mevcut durum:** Test projesi yok.
- **Kabul kriterleri:** Testler CI veya yerelde `dotnet test` ile çalışır. Yukarıdaki her senaryo ayrı bir test olarak geçer. Bir uca bilerek `cost` alanı eklenince ilgili test kırmızıya döner.
- **Roller:** –
- **Veri değişikliği:** Test veritabanı seed'i (fiyat yetkili ve yetkisiz iki kullanıcı).
- **Bağımlılık:** Güvenlik/altyapı modülündeki test projesi kararı.

### M07-16 — E-posta ve SMTP sır yönetimi [GÜVENLİK] (S)
- **Açıklama:** SMTP kullanıcı adı ve parolası `appsettings.json` yerine ortam değişkeninden okunur (Linux'ta `/etc/dengeerp/dengeerp.env`). Gönderim uç noktasına kullanıcı başına hız sınırı konur (örneğin dakikada 10). Alıcı alanı, teklifin müşteri e-postası veya kullanıcının açıkça girdiği adreslerle sınırlıdır ve her gönderim loglanır.
- **Gerekçe:** Program.cs:928-930 parolayı yapılandırma dosyasından okuyor; bu dosya ZIP ile dağıtılıyor. Gönderim ucu şirket adına herhangi bir adrese PDF ekli e-posta gönderebiliyor.
- **Mevcut durum:** Program.cs:909-931.
- **Kabul kriterleri:**
  1. `appsettings.json` içinde SMTP parolası yoktur ve uygulama env değişkeniyle gönderim yapar.
  2. Aynı kullanıcıdan 1 dakikada 11. gönderim 429 döner.
- **Roller:** `offers.send`.
- **Veri değişikliği:** Yok.
- **Bağımlılık:** M07-06, İT (SMTP hesabı).

### 3.1 Bilinçli olarak eklenmeyenler

- **Satış fiyat listesi / ürün kataloğundan otomatik fiyat:** fiyat politikası bilinmiyor (§5, soru 5). Cevap gelmeden yapılmaz.
- **Kişi (teknisyen) bazlı saatlik maliyet:** bordro verisi gerektirir. "Zaman takibi bordro değildir" kararı gereği birim bazlı iç tarife korunur.
- **Döviz kuru, e-fatura/e-arşiv, muhasebe fişi:** kapsam dışı (muhasebe entegrasyonu).
- **Müşteri portalında çevrimiçi onay / e-imza:** küçük-orta ölçekte e-posta + elle "Kabul" işaretleme yeterli.

### 3.2 Önerilen uygulama sırası

1. M07-07 + M07-14 (küçük, temel; diğerlerinin önkoşulu)
2. M07-02 (durum makinesi)
3. M07-01 (revizyon)
4. M07-03 + M07-04 (iş emri bağlantısı ve gelir aktarımı)
5. M07-08 + M07-12 (takip ve rapor)
6. M07-05 (PDF)
7. M07-06 + M07-16 (e-posta)
8. M07-09 + M07-10 + M07-13 (maliyet doğruluğu)
9. M07-11 (maliyet raporu)
10. M07-15 (testler, her adımda genişletilir)

Kullanıcının "önce yeni özellik" önceliğine uyulmuştur. Ancak M07-07 ve M07-14 küçük olduğu ve yeni akışın doğru çalışması için gerektiği için başa alınmıştır.

### 3.3 KRİTİK değerlendirmesi

- `/api/ops/finance` ve tarife/gelir uçları `finance.prices.view` kontrol ediyor (OpsSuite.cs:217, 240, 249).
- Stok maliyeti (173) ve bakım ücreti (Program.cs:2329-2333) alan bazında gizleniyor.
- Teklif tutarlarının `offers.view` sahiplerine görünmesi, iş kuralı netleşmeden "sızıntı" sayılamaz (§5, soru 1).
- Birim kontrolü olmayan durum değişikliği (M07-14) bir bütünlük sorunudur, veri kaybı değildir.

Bu nedenle bu modülde **KRİTİK** işaretli madde yoktur. Soru 1'in cevabı "teklif tutarı da yalnızca `finance.prices.view` ile görülmeli" olursa, `GET /api/offers`, PDF ve muhasebe görünümü **KRİTİK** sızıntıya döner ve M07-15 kapsamında öne alınmalıdır.

---

## 4. Varsayımlar

1. Rol dağılımı (hazırlayan Şef/Operasyon, onaylayan Müdür/Müdür Yrd., maliyet girişini kişiye özel yetkili biri yapar) organizasyon şeması gelene kadar varsayımdır.
2. Teklif para birimi TL'dir; KDV oranları 0/1/10/20.
3. Teklif gelirden aktarılırken **KDV hariç net tutar** kullanılır.
4. İşçilik maliyetine yol, saha, bekleme, uzaktan destek, atölye ve test süreleri dahildir, mola dahil değildir (mevcut kod da böyle).
5. Mevcut `OpsLaborRates` değerleri tarife geçmişine `2026-01-01` başlangıç tarihiyle taşınır.
6. Tüm geliştirmeler mevcut .NET 10 minimal API + SQL Server + vanilla JS yapısında, idempotent SQL scriptleriyle (`ZZ_V12x_*.sql`) artımlı yapılır.

## 5. Kullanıcıya sorulacaklar

1. **Teklif tutarlarını kim görmeli?** Bugün `offers.view` yetkisi olan herkes (Şef, Operasyon Uzmanı, Muhasebe, Genel Koordinatör, Kiralama Operasyon) teklif tutarlarını görüyor. Teklif fiyatı "müşteriye verilen satış fiyatı" olarak bu kişilere açık mı kalsın, yoksa `finance.prices.view` yetkisine mi bağlansın? İkinci seçenekte Şef ve Operasyon Uzmanı fiyatsız teklif hazırlayamaz.
2. **Onay kuralı:** Tek kademeli onay (Müdür / Müdür Yrd.) yeterli mi? Belli bir tutarın üzerinde (örneğin 100.000 TL) ya da belli bir iskonto oranının üzerinde ikinci onay (Üst Yönetim) gerekir mi? Muhasebe ve Genel Koordinatörün varsayılan `offers.approve` yetkisi kalsın mı?
3. **Planlı bakım geliri:** Bakım sözleşme bedeli PB iş emirlerine dağıtılsın mı (örneğin yıllık bedel ÷ cihaz sayısı ÷ yıllık bakım sayısı)? Yoksa planlı bakım işlerinde fark "gelir tanımsız" olarak mı kalsın?
4. **Para birimi:** Teknik servis tekliflerinde USD/EUR fiyat (ithal yedek parça) kullanılıyor mu? Kullanılıyorsa teklif dövizli mi tutulmalı, kur hangi kaynaktan alınmalı?
5. **Fiyat kaynağı:** Standart servis/işçilik satış fiyat listesi var mı? Varsa teklif kalemleri bu listeden seçilsin mi, yoksa fiyat her seferinde elle mi girilsin?
6. **PDF şablonu:** Kullanılacak logo, firma unvanı, adres, vergi dairesi/no, ödeme, teslim ve garanti şartları metinleri ile varsa örnek bir mevcut teklif belgesi paylaşılabilir mi? PDF için açık kaynak bir kütüphane (örneğin QuestPDF Community veya PdfSharp) kullanmamıza onay var mı? Lisans şartları İT ile kontrol edilmeli.
7. **E-posta:** Teklif hangi kurumsal adresten gidecek (örneğin teknikservis@…)? SMTP hesabı İT'den ne zaman alınabilir? SMTP gelene kadar "elle gönderildi" işaretleme yeterli mi?
8. **Birim saatlik iç maliyet:** Tarifeyi kim belirleyecek ve girecek? Birim bazında tek tarife (bugünkü yapı) yeterli mi, yoksa şef/teknisyen gibi kademe ayrımı istenir mi? Kademe ayrımı bordro verisine yaklaşır; şu anki kararla çelişebilir.
9. **Teklifsiz işlerde gelir:** Teklif verilmeden yapılan ve faturalanan işlerde (garanti dışı küçük onarım vb.) geliri kim, ne zaman girecek? Muhasebe mi, şef mi?
