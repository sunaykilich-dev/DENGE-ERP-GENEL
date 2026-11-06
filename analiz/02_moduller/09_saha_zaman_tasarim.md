# M09 — Saha / Zaman Takibi ve Mobil Teknisyen Görünümü — Gereksinim Tasarımı

> **Sürüm tabanı:** V1.20.1 (salt okunur kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Tarih:** 21.10.2026 · **Hazırlayan:** Modül gereksinim alt ajanı (M09)
> **Kısaltmalar:** `P.cs` = `Program.cs`, `Ops.cs` = `OpsSuite.cs`, `app.js` / `ops120.js` = `wwwroot` altı. Satır numaraları V1.20.1 içindir.
> **Uyulan kararlar:** Kapsam yalnızca teknik servis. Öncelik sırası: (c) yeni → (b) eksik → (a) güvenlik. Zaman takibi bordro değildir. Mola kişi-saate dahil edilmez. Tahmini süre gerçek süre yerine kullanılmaz. Süre kaydı yoksa "eksik" yazılır, 0 yazılmaz. Ekipteki her kişi süresini **kendi hesabından** tutar. Kapatılmayan sayacı yönetici gerekçe yazarak iptal eder. Açık sayaç varken iş kapatılamaz.

---

## 1. Mevcut durum (koddan çıkarıldı)

### 1.1 Veri modeli

| Tablo | Script | Amaç / önemli kolonlar | Notlar |
|---|---|---|---|
| `dbo.WorkOrderTimeLogs` | `Database/ZZ_V110_WorkOrderTimeLogs.sql:4-22` | Gerçekleşen süre: `WorkOrderId, TechnicianName, ActivityType, StartedAt, EndedAt, LocationNote, WorkNote, CreatedByUserId, CreatedByName, IsVoided, VoidedAt, VoidedByName` | Teknisyen **isim metniyle** tutuluyor; `TechnicianUserId` yok. Kaydın kaynağı (canlı/manuel) için kolon yok. Tek kayıt ≤ 1080 dk (CHECK). Faaliyet listesinde `Diğer` var, `Mola` yok. İptal (void) gerekçesi tutulmuyor. |
| `dbo.WorkOrderLiveSessions` | `Database/ZZ_V114_LiveTimeTracking.sql:4-23` | Canlı sayaç bölümleri: `TechnicianUserId` (FK ErpUsers), `ActivityType`, `StartedAt/EndedAt`, `StopReason`, `ResultTimeLogId`, `CancelledByUserId`, `CancelReason` | `UX_LiveSessions_OneActivePerUser` filtreli benzersiz indeks (satır 26-29): kişi başına **tek aktif sayaç** veritabanında da güvence altında. Mola bölümleri yalnızca bu tabloda kalıyor. |

### 1.2 API uçları

| Uç | Yer | Davranış | İzin |
|---|---|---|---|
| `GET /api/timetracking/summary` | P.cs:1908-1927 | Aktif sayaçlar, tamamlanmış süre kayıtları ve molalar. `reports.view` varsa ekibin tamamını, yoksa kişinin kendi kayıtlarını döner (kendi kayıtları **isimle** eşleştiriliyor, satır 1921). `serverTime = DateTime.Now` (uygulama sunucusunun saati). | `workorders.view` |
| `POST /api/workorders/{id}/live-timer/start` | P.cs:1929-1983 | Serializable transaction. Kontroller: kişi işe teknisyen olarak atanmış mı (isimle, 1943-1948); iş kapalı mı (`Tamamlandı/Kapatıldı/İptal`, 1953); kişinin başka aktif sayacı var mı (1955-1958); şu an elle girilmiş bir kayıtla çakışıyor mu (yalnızca **o an** kontrol ediliyor, 1960-1965). Başlangıç saati SQL `SYSDATETIME()`. | `workorders.view` + (`edit` veya `close`) |
| `POST .../live-timer/change` ve `.../finish` | P.cs:1985-2078 | Açık bölümü kapatır. Mola dışındaki faaliyetler `WorkOrderTimeLogs`'a yazılır (2037-2055); `change` aynı anda yeni bölümü açar (2065-2074). En kısa bölüm 1 dk (2022), en uzun 18 saat (2024). Bitişte elle girilmiş kayıtlarla tam aralık çakışma kontrolü yapılır (2039-2045). | aynı |
| `POST /api/timetracking/sessions/{sid}/cancel` | P.cs:2080-2102 | Açık sayaç gerekçe yazılarak iptal edilir; süre kaydı oluşmaz. Transaction kullanılmıyor. | `workorders.assign` **veya `users.manage`** |
| `GET /api/workorders/{id}/time-logs` | P.cs:2105-2113 | İşin süre kayıtları. Her çağrıda **tablonun tamamı** okunup bellekte süzülüyor. | `workorders.view` |
| `POST /api/workorders/{id}/time-logs` | P.cs:2114-2165 | Elle süre kaydı. Rol adı `Teknisyen` ise yalnızca kendi adına, başka rol ise istekte gelen isimle girilir (2120). Gelecek tarih kontrolü `DateTime.Now` ile yapılıyor (2126). Geriye dönük gün sınırı ve gerekçe zorunluluğu yok. Çalışan sayaç ve diğer kayıtlarla çakışma kontrolü var (2139-2151); mola bölümleriyle çakışma kontrolü yok. | `workorders.edit` veya `close` |
| `DELETE /api/workorders/{id}/time-logs/{logId}` | P.cs:2166-2180 | Kayıt silinmiyor, iptal olarak işaretleniyor. **Gerekçe istenmiyor.** | `workorders.assign` veya `users.manage` |
| `GET /api/reports/worklogs` | P.cs:2181-2189 | Rapor için tüm süre kayıtları | `reports.view` |
| `GET /api/reports/workorders.xlsx` | P.cs:2191-2229, 3641+ | Kişi-saat, faaliyet başlangıç tarihine göre süzülüyor. "Süre kaydı eksik iş" ve satır bazında "Süre Kaydı Durumu" var (3666, 3676). | `reports.export` |
| `PATCH /api/workorders/{id}/status` | P.cs:504-509 | Kapanış durumlarında (`Tamamlandı/Kapatıldı/Çözüldü`, P.cs:2808) açık sayaç varsa iş kapatılamaz. `İptal`'e geçişte bu kontrol yok. | — |
| Bakım formu kapanışı | P.cs:2496 | Açık sayaç varsa bakım formu kapatılamaz. | — |
| `PUT /api/workorders/{id}/assignments`, `PUT /api/workorders/bulk-assign` | P.cs:545-570, 573-614 | Atamalar devre dışı bırakılıp yeniden yazılıyor. Açık sayacı olan teknisyenin işten çıkarılması **kontrol edilmiyor**. | `workorders.assign` |
| Ops özeti / maliyet | Ops.cs:82-88, 222-234 | `recordedMinutes` kayıt yoksa **0** dönüyor (88). İşçilik maliyeti = süre × saatlik iç maliyet; süre kaydı yoksa işçilik **0** hesaplanıyor (230-231). | — |
| Ops uyarıları | Ops.cs:26-37, 38+ | SLA, yarınki plan, bekleme, düşük stok ve eğitim uyarıları var. **Unutulmuş/uzun süren sayaç uyarısı yok.** | — |

### 1.3 Ön yüz

| Ekran | Yer | İçerik |
|---|---|---|
| Menü | app.js:183, 195 | "Mobil İşler" (`mobile120`) ve "Saha / Zaman Takibi" (`timetracking`) menüleri; ikisi de `workorders.view` ile görünüyor. |
| İş emri içindeki sayaç kartı | app.js:1452-1467 | Faaliyet açılır listesi, bölge ve not alanı, "Sayacı Başlat / Faaliyeti Değiştir / Süreyi Bitir" düğmeleri. Mola ve devam için ayrı düğme yok; kullanıcı açılır listeden seçip "Değiştir"e basıyor. Kart, uzun iş emri penceresinin alt kısmında (app.js:1628). |
| Elle süre formu ve kayıt tablosu | app.js:1629-1664 | Teknisyen rolü yalnızca kendi adına girebiliyor; diğer roller atanmış herhangi bir teknisyeni seçebiliyor. İptal düğmesi gerekçe sormuyor. Kaydı kimin girdiği tabloda gösterilmiyor. |
| Saha / Zaman Takibi sayfası | app.js:1468-1514, 1537-1567 | "Benim Canlı Faaliyetim" bölümü, filtreli yönetim özeti (kişi-saat, saha, yol, bekleme, mola (hariç), farklı iş, aktif sayaç), yönetici için "Şu Anda Çalışan Ekipler" ve iptal düğmesi, personel bazında dağılım, ayrıntı tablosu (ilk 300 satır) ve istemcide CSV. |
| Geçen süre göstergesi | app.js:1439, 1516-1520 | Geçen süre **cihaz saatine** (`Date.now()`) göre hesaplanıyor ve 15 saniyede bir yenileniyor. Sunucudan gelen `serverTime` kullanılmıyor. |
| Mobil İşler | ops120.js:6-9 | Açık işlerin kart listesi: no, müşteri, şehir/lokasyon, durum ve "İşi Aç". Liste rol adı `Teknisyen` ise kişinin kendi işleriyle sınırlı, diğer rollerde tüm açık işler (en fazla 120). Sıralama ve gün gruplaması yok; adres, telefon ve harita bilgisi yok; aktif sayaç bandı yok. "İşi Aç" masaüstü penceresini açıyor. Çevrimdışı uyarısı var (offline yazma yok; bu bilinen bir karar). |
| Mobil CSS | ops120.css:7-8 | 850 px altında yatay menü çubuğu ve iki sütunlu ızgara. Bunun dışında mobile özel düzen yok. |

### 1.4 İş kuralları: kodda olanlar

- Kişi başına tek aktif sayaç (DB indeksi ve transaction): **var**.
- Başlangıç ve bitiş saati SQL sunucusundan alınıyor: **var** (canlı sayaçta). Elle girişte uygulama saati kullanılıyor.
- Mola kişi-saate dahil edilmiyor: **var** (molada `TimeLogs` kaydı oluşmuyor, P.cs:2037).
- Açık sayaçla iş kapatılamıyor: **var** (P.cs:506-509, 2496).
- Sayacı bitirmek işi kapatmıyor: **var**.
- Elle girilen kayıtla çakışma kontrolü: **var**, ama kişi isimle eşleştiriliyor ve sayaç başlarken yalnızca "o an" kontrol ediliyor.
- Yönetici gerekçe yazarak iptal edebiliyor: **var**. İptalden sonra doğru süre ayrı bir elle girişle yazılmak zorunda; iki kayıt birbirine bağlanmıyor.
- Raporlarda "süre kaydı eksik" gösterimi: Excel'de ve Raporlar ekranında **var** (P.cs:3666, app.js:1175). Ops ve maliyet ekranlarında **yok** (0 gösteriliyor).

---

## 2. Olması gereken (hedef tasarım)

### 2.1 Roller ve sorumluluklar (varsayım: organizasyon şeması henüz gelmedi)

| Rol (varsayım) | Bu modülde yaptığı iş |
|---|---|
| **Teknisyen** | Kendi işlerini mobilde görür. Kendi sayacını tek dokunuşla yönetir (Yola çıktım → Sahaya vardım → Bekleme/Mola → Devam → Bitir). Unuttuğu kısa süreyi sınırlı geçmiş için gerekçe yazarak elle girer. Gün sonunda kendi özetini görür. |
| **Şef** | Ekibin canlı durumunu izler (kim nerede, hangi faaliyette, ne zamandır). Unutulmuş sayacı gerekçe yazarak iptal edip düzeltir. Ekip adına elle kayıt girer (gerekçe zorunlu). Süre kaydı eksik işleri kapatmadan önce görür. |
| **Teknik Servis Müdürü / Yardımcısı** | Kişi-saat, faaliyet dağılımı, plan ile gerçekleşen arasındaki sapma ve veri disiplini KPI'larını birim ve şef bazında görür, dışa aktarır. |
| **İK / Muhasebe** | Bu modülde rolleri yok. Zaman verisi bordro değildir. `users.manage` yetkisi zaman kaydı iptal etmeye yetmemeli. |

Önerilen yeni izin anahtarları (mevcut karar gereği eski özel profillere otomatik dağıtılmaz):
- `timetracking.team.view`: ekibin canlı ve geçmiş kayıtlarını görme (bugün `reports.view` bu işi görüyor).
- `timetracking.manage`: sayaç iptali ve düzeltmesi, kayıt iptali, başka kişi adına elle kayıt.

### 2.2 Tutulması gereken veriler

- **Zaman bölümü (segment):** iş emri, kişi (**kullanıcı kimliği**; isim yalnızca gösterim için), faaliyet, başlangıç ve bitiş (sunucu saati), bölge, not, **kaynak** (`Canlı` / `Manuel` / `Yönetici Düzeltmesi`), giren kişi, giriş zamanı, manuel gerekçe, iptal bilgisi (kim, ne zaman, gerekçe).
- **Mola:** canlı oturum tablosunda kalır, raporda "hariç" diye gösterilir.
- **İş emri bazında türetilen alanlar** (hesaplanır, saklanmaz): ilk yola çıkış, ilk sahaya varış, son bitiş, toplam kişi-saat, faaliyet kırılımı, kayıt durumu (`Tam` / `Kısmi` / `Eksik`), tahmini süreyle sapma (yalnızca gerçek kaydı olan işlerde).

### 2.3 Akış (teknisyen gözüyle)

```text
Mobil "Benim İşlerim" (bugün / geciken / yarın, ziyaret bazında gruplu)
  → İş kartı: adres, saha yetkilisi, tel:, harita, cihaz/seri, plan notu
  → [Yola Çıktım]                    Yol / Ulaşım bölümü açılır
  → [Sahaya Vardım]                  Saha Çalışması (iş Planlandı ise → Sahada)
      ↔ [Beklemeye Al] (neden zorunlu) / [Mola] / [Devam] (moladan önceki faaliyete döner)
      ↔ [Sonraki Cihaza Geç]          aynı ziyaretteki başka iş emrine tek işlemde geçiş
  → [Bitir]                          bölüm kaydedilir; iş kapanışı ayrı adımdır
  → Gün sonu: "Bugünüm" özeti + eksik süre uyarısı
```

### 2.4 Doğrulamalar (hedef)

1. Kişi başına tek aktif sayaç (var, korunacak).
2. Aynı kişinin hiçbir iki gerçekleşen kaydı (canlı, manuel, mola dahil) çakışmaz. Kişi **kimlikle** belirlenir.
3. Elle kayıt: gelecek tarih olmaz (SQL saatine göre); teknisyen en fazla N gün geriye kayıt girer (varsayım: 2 gün), daha eskisi için `timetracking.manage` gerekir; gerekçe zorunludur.
4. Kapalı, iptal edilmiş veya çözülmüş işte sayaç başlatılmaz. Açık sayaç varken iş kapatılamaz ve iptal edilemez.
5. Açık sayacı olan kişi işten çıkarılamaz (önce sayaç bitirilmeli veya iptal edilmeli).
6. Kayıt iptali ve sayaç iptali gerekçesiz yapılamaz. Hepsi iz bırakır, hiçbir kayıt fiziksel olarak silinmez.

### 2.5 Raporlar ve KPI'lar (azı ama işe yarayanı)

| KPI | Tanım | Kimin için |
|---|---|---|
| Kişi-saat (faaliyet kırılımlı) | Saha, yol, bekleme, uzaktan, atölye ve test toplamı; mola ayrı ve hariç | Müdür, Şef |
| Süre kaydı eksik iş | Kapanmış veya sahada çalışılmış olup hiç gerçek süre kaydı olmayan iş sayısı ve listesi | Şef (günlük), Müdür |
| Canlı kayıt oranı | Canlı kaynaklı dakika ÷ toplam dakika. Dijital disiplinin ölçüsüdür. | Müdür |
| İptal edilen / unutulan sayaç | Dönem içindeki iptal edilmiş oturum sayısı, kişi bazında | Şef |
| Plan ile gerçek sapma | (Gerçek kişi-saat − tahmini süre). Yalnızca gerçek kaydı olan işlerde hesaplanır; kaydı olmayan iş "eksik" sayılır. | Müdür, Planlama |
| Sahaya varış zamanı | İlk "Saha Çalışması" başlangıcı. SLA müdahale ölçümüne veri sağlar. | Ops / SLA |

---

## 3. Fark listesi (öncelik sırası: YENİ → EKSİK/HATA/VERİ → GÜVENLİK)

> Kritik güvenlik veya veri kaybı açığı bu modülde **bulunmadı**. Zaman verisinin yanlış kişiye yazılması ve kilitlenen sayaç gibi veri bütünlüğü sorunları HATA/VERİ olarak işaretlendi.

### M09-01 · YENİ · Mobil "Benim İşlerim" ekranı ve tek sayfa iş kartı
- **Açıklama:** `mobile120` ekranı teknisyenin günlük çalışma ekranına dönüştürülür. Varsayılan liste **bana atanan** işlerdir (rol adına bakılmaz; şef ve müdür "Tümü" seçeneğine geçebilir). Liste Geciken / Bugün / Yarın gruplarına ayrılır ve plan saatine göre sıralanır. Aynı gün, müşteri ve lokasyondaki işler tek ziyaret kartında toplanır. Ekranın üstünde aktif sayaç bandı durur (faaliyet, iş no, geçen süre, Bitir). "İşi Aç" masaüstü penceresi yerine mobil iş kartını açar. Kartta adres, saha yetkilisi, `tel:` bağlantısı, adres metniyle harita araması, ulaşım notu, cihaz/seri, plan notu, sayaç düğmeleri (M09-02) ve Bakım Formu bağlantısı bulunur.
- **Gerekçe:** Teknisyen bugün sahada uzun masaüstü penceresinin en altındaki sayaca ulaşmak zorunda (app.js:1628). Ziyaret bilgileri WhatsApp ile iletiliyor. Sayaç ancak telefondan kolay kullanılabilirse gerçek veri üretir.
- **Mevcut:** ops120.js:6-9: sıralama, gruplama, adres/telefon ve sayaç bandı yok. Şef ve müdürde tüm açık işler listeleniyor.
- **Kabul:** (1) Teknisyen hesabıyla yalnızca kendisine atanmış açık işler gelir; Şef hesabıyla da varsayılan "bana atananlar"dır. (2) Bugünkü işler plan saatine göre sıralanır; plan tarihi geçmiş açık işler "Geciken" grubundadır. (3) Aynı ziyaretteki 17 PB iş emri tek kartta görünür; kart açılınca her iş emri ayrı seçilir. (4) Aktif sayaç varsa her mobil ekranın üstünde görünür ve oradan Bitir'e basılabilir. (5) 375 px genişlikte yatay kaydırma olmaz; ana düğmeler en az 44 px yüksekliktedir. (6) Kartta fiyat veya maliyet alanı bulunmaz.
- **Roller:** Teknisyen ve Şef (`workorders.view`).
- **Veri:** Yok (plan/saha alanları mevcut, `ZZ_V111_PlanSites.sql`).
- **Efor:** M · **Bağımlılık:** M02-08 ("Bugünkü ziyaretlerim") ile **tek ekran olarak** yapılmalı; M09-02.

### M09-02 · YENİ · Tek dokunuşla saha akış düğmeleri (Yola Çıktım / Sahaya Vardım / Bekleme / Mola / Devam / Bitir)
- **Açıklama:** Açılır liste ve "Faaliyeti Değiştir" yerine duruma göre değişen büyük düğmeler kullanılır. **Devam**, moladan önceki faaliyete döner; bunun için sunucuda `POST /live-timer/resume` ucu eklenir ve son mola dışı bölümün faaliyeti bulunur. **Beklemeye Al** için bekleme nedeni zorunludur (Malzeme / Müşteri / Erişim / Onay / Diğer + not). Masaüstündeki eski açılır liste "diğer faaliyetler" (Uzaktan Destek, Atölye, Test) için kalır.
- **Gerekçe:** Kararda tanımlanan "Yola çıktım → Sahadayım → Mola → Devam → Bitir" akışı bugün yalnızca açılır listeyle yapılabiliyor (app.js:1461-1464, 1504). Mola sonrasında hangi faaliyete dönüleceğini kullanıcı hatırlamak zorunda.
- **Mevcut:** `change` ucu var (P.cs:1985); `resume` ve bekleme nedeni yok.
- **Kabul:** (1) Sayaç yokken yalnızca "Yola Çıktım" ve "Sahaya Vardım" görünür. (2) Saha Çalışması → Mola → Devam sırası sonunda yeni bölüm Saha Çalışması olur. Mola `TimeLogs`'a yazılmaz, sonraki bölüm mola bitişinde başlar (boşluk ve çakışma olmaz). (3) Neden seçilmeden Bekleme başlatılırsa 400 döner. (4) Her geçişte önceki bölüm tek transaction içinde kaydedilir; ağ hatasında iki kez basılırsa ikinci istek 409 döner ve çift bölüm oluşmaz.
- **Roller:** Teknisyen (kendi oturumu).
- **Veri:** `WorkOrderLiveSessions` ve `WorkOrderTimeLogs` tablolarına `WaitReason NVARCHAR(40) NULL` eklenir (bekleme nedeni ayrıca not alanında da tutulabilir).
- **Efor:** M · **Bağımlılık:** —

### M09-03 · YENİ · Ziyaret içinde sonraki iş emrine geçiş (sayacı taşı)
- **Açıklama:** Aynı ziyaretteki (aynı gün, müşteri ve lokasyon ya da aynı `RouteGroupNo`) başka bir iş emrine geçmek için `POST /api/workorders/{id}/live-timer/move` eklenir. Bu uç mevcut bölümü kapatır ve hedef iş emrinde aynı (ya da seçilen) faaliyeti aynı saniyede başlatır. Mobil kartta "Sonraki Cihaza Geç" düğmesi olarak görünür.
- **Gerekçe:** 1 cihaz = 1 PB iş emri kararı nedeniyle bir AVM ziyaretinde 17 iş emri var. Bugün her cihaz için Bitir + yeni işi aç + Başlat gerekiyor ve 1 dakika kuralı (P.cs:2022) arada kayıp veya bekleme yaratıyor. Teknisyen bu zahmet yüzünden tek iş emrine toplu süre yazar ve cihaz bazlı süre bozulur.
- **Mevcut:** Yok.
- **Kabul:** (1) A işindeki bölümün bitiş saati, B işindeki bölümün başlangıç saatine eşittir (saniye düzeyinde). (2) Hedef iş farklı ziyarete aitse 400 döner. (3) Kişi hedef işe atanmamışsa 400 döner. (4) Hedef iş kapalıysa 400 döner. (5) İşlem yarıda kalırsa iki taraf da değişmez.
- **Roller:** Teknisyen.
- **Veri:** Yok.
- **Efor:** S–M · **Bağımlılık:** M09-02. Yol süresinin hangi iş emrine yazılacağı kullanıcıya sorulacak (§4 Soru 2).

### M09-04 · YENİ · Teknisyen "Bugünüm" özeti ve gün sonu eksik kontrolü
- **Açıklama:** Mobil ekranda "Bugünüm" sekmesi bulunur: bugünkü bölümler zaman çizelgesi olarak listelenir; kişi-saat, yol, saha ve bekleme toplamları ile mola (hariç) gösterilir. Ayrıca "Bugün işlem gördü ama süre kaydı yok" uyarısı verilir: bugün durumu değişmiş veya bakım formu güncellenmiş, ama kişinin bu işte hiç gerçek süresi olmayan işler listelenir ve her birinin yanında "elle gir" bağlantısı bulunur. Saat çizelgesindeki boşluklar yalnızca **bilgi** olarak gösterilir; bordro değildir.
- **Gerekçe:** Süre kaydı olmayan işler ancak ay sonu Excel'inde fark ediliyor. Eksik kayıt aynı gün kapatılırsa veri kalitesi artar.
- **Mevcut:** Sayfada yalnızca toplamlar var (app.js:1508). Gün bazında ve kişiye özel eksik listesi yok.
- **Kabul:** (1) Bugün iki bölümü (60 + 30 dk) ve bir molası (15 dk) olan teknisyende toplam 1 sa 30 dk, mola 15 dk (hariç) görünür. (2) Bugün durumunu "Tamamlandı" yaptığı ama süre kaydı olmayan iş "Süre kaydı eksik" diye listelenir; 0 dk yazılmaz. (3) Başka teknisyenin kayıtları görünmez.
- **Roller:** Teknisyen (kendisi), Şef (ekip görünümünde aynı liste).
- **Veri:** Yok.
- **Efor:** M · **Bağımlılık:** M09-13 (kimlikle eşleşme önerilir).

### M09-05 · YENİ · Unutulan sayaç uyarısı ve yönetici "iptal et ve düzelt" akışı
- **Açıklama:** (a) Ops uyarılarına "Uzun açık sayaç" türü eklenir: X saati aşan (varsayım 10 saat) veya gün değişmiş açık oturumlar. Uyarı Şef ve Müdüre gider, teknisyene de giriş yaptığında banner olarak gösterilir. (b) İptal penceresine isteğe bağlı "Gerçek bitiş saati" alanı eklenir. Doldurulursa oturum iptal edilir ve aynı transaction içinde `Kaynak = Yönetici Düzeltmesi` olan bir süre kaydı oluşur (başlangıç = oturum başlangıcı, bitiş = girilen saat, gerekçe = iptal gerekçesi). Bu kayıt iptal edilen oturuma bağlanır.
- **Gerekçe:** Kararda unutulan sayacın yönetici tarafından iptal edileceği yazıyor, ama bunu hatırlatan bir mekanizma yok (Ops.cs:26-37). İptal sonrasında doğru süre ayrı bir elle girişle yazılıyor ve iki kayıt arasındaki bağ kayboluyor (P.cs:2094-2101).
- **Mevcut:** İptal var. Uyarı ve düzeltme bağı yok.
- **Kabul:** (1) 10 saatten uzun açık oturum ops uyarısında görünür; uyarı onaylandıktan (ack) sonra aynı gün tekrar çıkmaz. (2) Gerçek bitiş saati girilerek yapılan iptalde süre kaydı oluşur ve kaynak "Yönetici Düzeltmesi" olur. Bitiş saati başlangıçtan önce veya şimdiden sonra ise 400 döner. (3) Düzeltilmiş kayıt kişinin diğer kayıtlarıyla çakışırsa 409 döner ve iptal de geri alınır. (4) Bitiş saati girilmezse bugünkü gibi yalnızca iptal yapılır.
- **Roller:** Şef ve Müdür (`timetracking.manage`; M09-15'e kadar `workorders.assign`).
- **Veri:** `WorkOrderTimeLogs` ADD `SourceType` (M09-08), `SourceSessionId BIGINT NULL`.
- **Efor:** M · **Bağımlılık:** M09-08.

### M09-06 · YENİ · İş emri zaman çizelgesi ve türetilmiş saha metrikleri
- **Açıklama:** İş emri ekranında ve Excel'de ilk yola çıkış, ilk sahaya varış, son bitiş, kişi bazlı kişi-saat, faaliyet kırılımı ve **kayıt durumu** (`Tam`: atanan herkesin kaydı var / `Kısmi`: atananların bir kısmının kaydı yok / `Eksik`: hiç kayıt yok) gösterilir. Tahmini süreyle sapma yalnızca kaydı olan işlerde hesaplanır. Bu değerler SLA modülünde "sahaya varış" verisi olarak kullanılabilir.
- **Gerekçe:** Yönetimin "personel gerçekte ne kadar yol/saha/bekleme kaydetti?" sorusunun cevabı iş emri düzeyinde tek bakışta görünmüyor. Çok teknisyenli işlerde bir kişinin süresi eksik kalırsa toplam yine dolu görünüyor.
- **Mevcut:** İş emrinde düz kayıt tablosu ve toplam var (app.js:1639-1640). Excel'de satır bazında "Süre Kaydı Durumu" var (P.cs:3676), ama kısmi durum ayrılmıyor.
- **Kabul:** (1) İki teknisyen atanmış ve yalnızca biri kayıt girmişse durum "Kısmi" olur. (2) Kaydı olmayan işte sapma hücresi boş kalır ve "eksik" yazar. (3) İlk varış, ilk "Saha Çalışması" bölümünün başlangıcıdır; bu bölüm yoksa boş kalır. (4) Excel ve ekran aynı değeri gösterir.
- **Roller:** Görüntüleme `workorders.view`; Excel `reports.export`.
- **Veri:** Yok (hesaplanır).
- **Efor:** M · **Bağımlılık:** M01-10 (atanan kişi listesi kimlikle), M09-13.

### M09-07 · YENİ · Zaman verisi disiplin raporu
- **Açıklama:** Saha / Zaman Takibi sayfasına ve Excel'e "Veri Disiplini" bölümü eklenir. Teknisyen ve şef bazında şunlar gösterilir: canlı kayıt oranı, manuel kayıt sayısı, manuel kaydın gecikmesi (giriş zamanı − bitiş), iptal edilen ve düzeltilen sayaç sayısı, süre kaydı eksik iş sayısı.
- **Gerekçe:** Yönetsel raporların güvenilirliği sahadaki dijital kayıt disiplinine bağlı (belge §6.1). Bunu ölçmeden kişi-saat raporuna güvenmek mümkün değil.
- **Mevcut:** Yok. Kaynak alanı olmadığı için bugün hesaplanamıyor da.
- **Kabul:** (1) 3 canlı (toplam 120 dk) ve 1 manuel (60 dk) kaydı olan kişide canlı oranı %66,7 görünür. (2) Bitişinden 2 gün sonra girilen manuel kayıt "gecikmeli" sayılır. (3) Filtreler (tarih, birim, kişi) mevcut sayfa filtreleriyle aynı çalışır.
- **Roller:** `timetracking.team.view` / `reports.view`.
- **Veri:** M09-08'deki `SourceType` alanını kullanır.
- **Efor:** S–M · **Bağımlılık:** M09-08.

### M09-08 · EKSİK / VERİ · Manuel kayıt kuralları: kaynak, gerekçe, geriye dönük sınır, iptal gerekçesi
- **Açıklama:** `WorkOrderTimeLogs` tablosuna `SourceType` (`Canlı` / `Manuel` / `Yönetici Düzeltmesi`), `ManualReason` ve `VoidReason` eklenir. Elle kayıtta gerekçe zorunludur (örnek: "Telefonun şarjı bitti", "Sinyal yoktu"). Teknisyen yalnızca son N gün (varsayım: 2) için kayıt girebilir; daha eskisi `timetracking.manage` ister. Kayıt iptalinde gerekçe zorunludur. Elle kayıt aynı kişinin **mola oturumlarıyla** da çakışmamalıdır. Kayıt tablosunda "Kaynak" ve "Giren" sütunları gösterilir. Mevcut kayıtlar: `ResultTimeLogId` ile bağlı olanlar `Canlı`, kalanlar `Manuel` olarak doldurulur.
- **Gerekçe:** Bugün aylar öncesine gerekçesiz kayıt girilebiliyor (P.cs:2124-2127). Kaydın kaynağı ayırt edilemiyor. Kayıt iptali gerekçesiz yapılıyor (P.cs:2166-2180). Manuel kayıt mola oturumuyla çakışabiliyor (P.cs:2139-2151 molaya bakmıyor).
- **Mevcut:** Yok.
- **Kabul:** (1) Gerekçesiz manuel kayıt 400 döner. (2) Teknisyen hesabıyla 3 gün önceye kayıt 403/400 döner; Şef hesabıyla aynı kayıt (gerekçeyle) kabul edilir. (3) Gerekçesiz iptal 400 döner; iptal edilen kaydın gerekçesi ekranda görünür. (4) 10:00-10:30 molası olan kişiye 10:15-11:00 manuel kayıt girilirse 409 döner. (5) Migration sonrasında canlı oturumdan oluşan kayıtların hepsi `Canlı` görünür.
- **Roller:** Teknisyen (kendi adına), Şef (`timetracking.manage`).
- **Veri:** `ALTER TABLE WorkOrderTimeLogs ADD SourceType NVARCHAR(20) NOT NULL DEFAULT N'Manuel', ManualReason NVARCHAR(300) NULL, VoidReason NVARCHAR(300) NULL` ve idempotent geri doldurma scripti (`ZZ_V12x_TimeLogSource.sql`). Uygulamadan önce `.bak` yedeği alınmalı.
- **Efor:** S–M · **Bağımlılık:** —

### M09-09 · EKSİK / HATA · Sayaç ile iş emri durumu arasındaki bağ
- **Açıklama:** (a) İşte ilk "Saha Çalışması" bölümü başladığında durum `Planlandı`/`Planlamada` ise otomatik olarak `Sahada` yapılır ve durum geçmişine "Canlı sayaç: sahaya varış" yazılır. (b) Sayaç başlatma engeli `IsClosingStatus` ile aynı listeyi kullanır ve **`Çözüldü`** de engellenir; şu an yalnızca `Tamamlandı/Kapatıldı/İptal` engelleniyor (P.cs:1953 ile P.cs:2808 tutarsız). (c) Açık sayacı olan iş **`İptal`** durumuna alınamaz (P.cs:504-509 bu durumu kontrol etmiyor).
- **Gerekçe:** Ana paneldeki "Sahada" sayısı bugün teknisyenin durumu elle değiştirmesine bağlı. Sayaç zaten bu bilgiyi üretiyor. İptal edilen işe süre yazılabilmesi raporu bozuyor.
- **Mevcut:** Bağ yok; tutarsızlık var.
- **Kabul:** (1) `Planlandı` durumundaki işte "Sahaya Vardım" → durum `Sahada` olur ve geçmişte tek satır görünür. `Beklemede` gibi diğer durumlar değişmez. (2) `Çözüldü` durumundaki işte sayaç başlatma 400 döner. (3) Açık sayaçlı işi `İptal`'e almak 409 döner.
- **Roller:** —
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** M01-09 (durum yaşam döngüsü; otomatik geçiş o tabloya uygun olmalı). (a) maddesi için kullanıcı onayı gerekiyor (§4 Soru 4).

### M09-10 · EKSİK · Teknisyenin yanlış başlattığı sayacı kısa süre içinde geri alması
- **Açıklama:** Teknisyen kendi açık oturumunu başlattıktan sonraki ilk 5 dakika içinde "Yanlış başlattım" seçeneğiyle iptal edebilir. Kişi-saat oluşmaz, oturum `StopReason = Kullanıcı Geri Aldı` ile saklanır ve disiplin raporunda (M09-07) sayılır. Faaliyet değiştirme ve bitirmedeki 1 dakika alt sınırı bu durum için uygulanmaz.
- **Gerekçe:** Bugün yanlış işte veya yanlış faaliyette başlatılan sayaç ya 1 dakika beklenip yanlış kayıt üretilerek ya da yönetici iptaliyle düzeltilebiliyor (P.cs:2022-2023, 2084).
- **Mevcut:** Yok.
- **Kabul:** (1) Başlatmadan 3 dk sonra geri alınan oturum `TimeLogs`'a yazılmaz. (2) 6. dakikada geri alma 400 döner. (3) Başka kişinin oturumu geri alınamaz (403).
- **Roller:** Teknisyen (kendi oturumu).
- **Veri:** Yok (`StopReason` metni).
- **Efor:** S · **Bağımlılık:** —

### M09-11 · HATA · Atama değişince açık sayaç sahibine kilitleniyor
- **Açıklama:** Tekil ve toplu atama uçları, açık sayacı olan teknisyeni işten çıkaran değişikliği 409 ile reddeder ve "Önce X kişisinin sayacını bitirin veya iptal edin" mesajı verir. Ayrıca `finish` ve `change` uçlarında oturum sahibinin kendi oturumunu bitirmesi, iş erişim kontrolüne (atama) takılmamalıdır.
- **Gerekçe:** Şef sayaç çalışırken teknisyeni işten çıkarırsa `CanAccessWorkOrderAsync` teknisyen rolü için atamaya bakıyor (P.cs:3398-3400). Bu durumda `finish` 403 döner (P.cs:1996). Ön yüzde de "atama yok" dalı Bitir düğmesini gizliyor (app.js:1460). Sayaç 18 saat sınırına kadar açık kalıyor ve kişi başka işte sayaç başlatamıyor.
- **Mevcut:** P.cs:545-570 ve 573-614'te kontrol yok.
- **Kabul:** (1) Açık sayaçlı teknisyeni atamadan çıkaran istek 409 döner ve atama değişmez. (2) (Veri tutarsızlığı nedeniyle) ataması kalkmış bir kişi kendi açık oturumunu `finish` ile bitirebilir ve süre kaydı oluşur. (3) Toplu atamada tek bir iş bile bu durumdaysa hiçbir iş değişmez.
- **Roller:** Şef (`workorders.assign`).
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** —

### M09-12 · HATA · Saat kaynağı tutarsızlığı (uygulama, SQL ve cihaz saati)
- **Açıklama:** Tüm "şimdi" kontrolleri SQL `SYSDATETIME()` ile yapılır: manuel kayıttaki gelecek kontrolü (P.cs:2126) ve `summary.serverTime` (P.cs:1926). İstemci, `serverTime` ile cihaz saati arasındaki farkı hesaplayıp geçen süre göstergesini (app.js:1439) bu farka göre düzeltir. Linux kurulum belgesine sunucu saat diliminin `Europe/Istanbul` olması ve NTP'nin açık olması gerektiği yazılır.
- **Gerekçe:** Linux hedefinde uygulama ve SQL farklı makinelerde (belge §3.3). Saat dilimi farkı manuel kayıtta 3 saatlik yanlış reddetme ya da kabul üretir. Telefon saati yanlışsa ekrandaki süre yanlış görünür (kaydedilen süre doğru olsa da teknisyen yanlış karar verir).
- **Mevcut:** Kaynaklar karışık.
- **Kabul:** (1) Uygulama sunucusunun saati 3 saat geri ayarlıyken, SQL saatine göre 1 saat sonraya biten manuel kayıt reddedilir. (2) Telefon saati 10 dk ileri olsa da ekrandaki geçen süre, sunucu kaydıyla en fazla 1 dk fark gösterir. (3) `03_dogrula.sh` saat dilimini kontrol eder ve yanlışsa uyarı verir.
- **Roller:** —
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** —

### M09-13 · VERİ · Zaman kayıtlarının kişi kimliğine bağlanması
- **Açıklama:** `WorkOrderTimeLogs` tablosuna `TechnicianUserId INT NULL` (ve M01-10 ile uyumlu olarak `PersonnelId`) eklenir. Çakışma kontrolleri, "kendi kayıtlarım" süzmesi (P.cs:1921), sayaç başlatmadaki atama kontrolü ve manuel kayıt bundan sonra kimlikle çalışır; isim yalnızca gösterim için kullanılır. Mevcut kayıtlar için isim → `ErpUsers.FullName` eşleştirme scripti yazılır. Eşleşmeyen veya birden fazla kişiyle eşleşen satırlar raporlanır ve metin olarak korunur.
- **Gerekçe:** Bugün çakışma kontrolü ve kişi raporları isim metnine dayanıyor (P.cs:1962, 2041, 2140, 2146). Ad değişikliği veya aynı adı taşıyan iki personel çift sayıma ya da yanlış engellemeye yol açar. Canlı oturum kimlik tutuyor ama süre kaydı tutmuyor.
- **Mevcut:** Yalnızca `WorkOrderLiveSessions.TechnicianUserId` var.
- **Kabul:** (1) Adı değiştirilen teknisyen eski kayıtlarını "Bugünüm"de görmeye devam eder. (2) Aynı adlı iki farklı kullanıcının aynı saatteki kayıtları birbirini engellemez. (3) Migration raporu eşleşen, eşleşmeyen ve çoklu eşleşen satır sayılarını verir ve hiçbir satır silinmez.
- **Roller:** —
- **Veri:** `ALTER TABLE` + indeks `IX_TimeLogs_UserStart(TechnicianUserId, StartedAt) INCLUDE(EndedAt, IsVoided)` + geri doldurma scripti. Yedek alınmadan uygulanmaz.
- **Efor:** M · **Bağımlılık:** M01-10 / M02-03 (kimlik bazlı atama).

### M09-14 · VERİ · Ops ve maliyet ekranlarında "0 saat" yerine "süre kaydı eksik"
- **Açıklama:** `recordedMinutes` kayıt yoksa `null` döner (Ops.cs:88) ve ekranda "Eksik" yazılır. Maliyet analizinde süre kaydı olmayan işin işçilik maliyeti 0 TL hesaplanmaz; "İşçilik: kayıt eksik" diye işaretlenir ve bu işler toplam fark hesabında ayrı sayılır (Ops.cs:230-234).
- **Gerekçe:** Karar: süre kaydı yoksa "eksik" denir, 0 denmez. Bugün maliyet ekranı kaydı olmayan işi işçiliksiz gösterip farkı olduğundan yüksek gösteriyor.
- **Mevcut:** Ops.cs:88 `GetValueOrDefault(...,0)`, Ops.cs:230-231.
- **Kabul:** (1) Süre kaydı olmayan iş ops listesinde "Eksik" görünür, "0 dk" görünmez. (2) Maliyet özetinde "İşçilik kaydı eksik iş: n" satırı bulunur. (3) Kaydı olan işlerin hesabı değişmez.
- **Roller:** Ops (`operations.manage`), maliyet (`finance.costs.manage` / `finance.prices.view`).
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** —

### M09-15 · EKSİK · Özet ve kayıt uçlarında tüm tablonun okunması
- **Açıklama:** `LoadTimeLogsAsync` ve `LoadLiveTimersAsync` (P.cs:3403-3439) her çağrıda tablonun tamamını okuyor. `summary` her iş emri açılışında çağrılıyor (app.js:1612). Bu uçlar SQL'de iş emri, kişi ve tarih aralığıyla süzülecek şekilde değiştirilir; `summary` varsayılan olarak son 31 günü döner, daha uzun dönem için tarih parametresi alır.
- **Gerekçe:** Kayıtlar her gün birikiyor. Birkaç ay içinde iş emri açmak ve mobil ekran yavaşlar; bu durum en çok mobil hatta hissedilir.
- **Mevcut:** Bellekte süzme yapılıyor.
- **Kabul:** (1) `GET /time-logs` yalnızca ilgili işin satırlarını SQL'den okur (sorgu planında `WorkOrderId` seek). (2) 100.000 süre kaydı olan test veritabanında `summary` 1 sn altında döner. (3) Dönen sonuç, eski uçla aynı filtrede birebir aynıdır.
- **Roller:** —
- **Veri:** İndeksler M09-13 ile birlikte.
- **Efor:** S–M · **Bağımlılık:** —

### M09-16 · GÜVENLİK · Zaman yönetimi yetkisinin ayrıştırılması
- **Açıklama:** Sayaç iptali (P.cs:2084) ve kayıt iptali (P.cs:2170) `users.manage` yetkisinden çıkarılır ve yeni `timetracking.manage` izni ile yönetilir. Ekip görünümü `reports.view` yerine `timetracking.team.view` ile verilir (P.cs:1915). Manuel kayıtta "başkası adına girebilir mi?" kararı rol adına (`RoleName == "Teknisyen"`, P.cs:2120 ve app.js:1632) göre değil, `timetracking.manage` iznine göre verilir. Rol şablonları güncellenir; yeni anahtarlar mevcut özel profillere otomatik dağıtılmaz.
- **Gerekçe:** İK rolü `users.manage` iznine sahip olduğu için (envanter §Roller) saha sayaçlarını iptal edebiliyor ve süre kayıtlarını geçersiz kılabiliyor. Rol adı farklı yazılmış bir teknisyen profili (ör. "Saha Teknisyeni") aynı işe atanmış başka kişiler adına süre girebiliyor.
- **Mevcut:** Yukarıdaki satırlar.
- **Kabul:** (1) Yalnızca `users.manage` iznine sahip hesapla sayaç iptali 403 döner. (2) Rol adı "Teknisyen" olmayan ama `timetracking.manage` izni de olmayan hesapla başkası adına manuel kayıt 403 döner. (3) Şef şablonu `timetracking.manage` ve `timetracking.team.view` içerir; Teknisyen şablonu ikisini de içermez. (4) Ekip görünümü olmayan hesap `summary`'de yalnızca kendi kayıtlarını alır.
- **Roller:** Şef, Müdür (yeni izinler); İK (yetki kaldırılıyor).
- **Veri:** `Catalog.RoleDefaults` / izin kataloğu güncellenir (P.cs:3921+).
- **Efor:** S–M · **Bağımlılık:** M01-18 (iş emri izin ayrıştırması) ile birlikte yapılması önerilir.

### Uygulama sırası önerisi

1. **Paket A (sahada hemen değer üretir):** M09-11, M09-09(b,c), M09-12, M09-02, M09-01, M09-03.
2. **Paket B (veri güvenilirliği):** M09-08, M09-13, M09-14, M09-10, M09-05.
3. **Paket C (yönetim görünürlüğü):** M09-04, M09-06, M09-07, M09-15.
4. **Paket D (yetki):** M09-16 (M01-18 ile birlikte).

> HATA maddeleri (M09-11, M09-12) küçük olduğu ve sahadaki yeni ekranın güvenilir çalışması bunlara bağlı olduğu için, (c)→(b)→(a) önceliğine rağmen Paket A'ya alındı.

---

## 4. Kullanıcıya sorulacaklar (benim karar veremeyeceğim konular)

1. **Hesap ve cihaz:** Sahadaki her teknisyenin kendine ait bir ERP hesabı ve internet erişimi olan bir telefonu var mı? (Ekipteki herkesin kendi süresini kendi hesabından tuttuğu karar buna dayanıyor. Hesabı olmayanların süresini şef elle mi girecek?)
2. **Toplu ziyarette yol ve bekleme süresi:** 17 cihazlık bir PB ziyaretinde yola çıkış ve bekleme süresi (a) ilk iş emrine mi yazılsın, (b) ziyaret düzeyinde ayrı bir "ziyaret süresi" kaydı mı olsun, yoksa (c) iş emirlerine eşit mi dağıtılsın? (c) seçilirse dağıtılan süre "dağıtılmış" diye işaretlenir ve gerçek süre gibi gösterilmez.
3. **Konum:** "Sahaya Vardım" düğmesine basıldığında telefonun konumu (GPS) kaydedilsin mi? KVKK aydınlatma metni ve açık rıza gerekir. Araç takip entegrasyonu ileride düşünülüyor.
4. **Otomatik durum:** İlk "Sahaya Vardım"da iş emri durumu `Planlandı`'dan `Sahada`'ya otomatik geçsin mi? (M09-09a)
5. **Geriye dönük manuel kayıt:** Teknisyen kaç gün geriye kayıt girebilsin (varsayım 2 gün)? Manuel kayıtlar şef onayına tabi olsun mu?
6. **Unutulan sayaç eşiği:** Uyarı kaç saatte verilsin (varsayım 10 saat) ve kime gitsin (şef, müdür ya da ikisi)?
7. **Günlük onay:** Şefin ekibin günlük süre kayıtlarını "kontrol edildi" diye kapatması istenir mi, yoksa bu gereksiz bir yük mü?
8. **Mesai dışı / nöbet:** Mesai dışı, hafta sonu ve gece çağrılarında çalışılan süre raporda ayrı gösterilsin mi? (Bordro değildir, yalnızca operasyon görünürlüğü içindir.)
9. **Çevrimdışı ihtiyacı:** Sinyalin olmadığı sahalar (bodrum katlar, X-Ray odaları, havaalanı güvenlik alanları) ne sıklıkta karşınıza çıkıyor? Offline kayıt ve senkronizasyon önceliği buna göre belirlenecek. Şimdilik yalnızca çevrimiçi çalışılıyor.
10. **Görünürlük:** Teknisyen aynı iş emrindeki ekip arkadaşlarının sürelerini görsün mü? (Şu an aynı işin tüm kayıtları görünüyor.)

## 5. Varsayımlar

- Roller kod şablonlarından (Teknisyen, Şef, Müdür) çıkarıldı. Organizasyon şeması gelince güncellenecek.
- Geriye dönük manuel kayıt sınırı 2 gün, unutulan sayaç eşiği 10 saat ve kendi sayacını geri alma süresi 5 dakika olarak önerildi; hepsi ayarlanabilir sabitlerdir.
- Mobil ekran çevrimiçi kalır; offline kapsam dışıdır (mevcut karar).
- Ekip adına tek sayaç **önerilmedi**; mevcut karar "herkes kendi hesabından" şeklindedir.
- Müşteri imzası/onayı ve servis kapanış formu iş emri modülünde ele alınıyor (M01-01, M01-04). Bu modül yalnızca mobil karttan oraya bağlantı verir.
