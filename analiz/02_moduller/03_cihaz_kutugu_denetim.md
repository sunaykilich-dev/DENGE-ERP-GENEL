# M03 — Güvenlik Cihaz Kütüğü — Bağımsız Denetim

> **Denetlenen:** `analiz/02_moduller/03_cihaz_kutugu_tasarim.md` (M03-01 … M03-13)
> **Kaynak:** V1.20.1 salt okunur (`kaynak/V1_20_1_orijinal/DengeERP.Api`); koda dokunulmadı.
> **Tarih:** 21.10.2026 · **Yöntem:** Her "mevcut durum" iddiası koddan tek tek doğrulandı. Kullanıcı kararlarına (kapsam yalnız teknik servis; öncelik c → b → a; Logo/Flowick kapsam dışı; rol önerileri VARSAYIM) uygunluk ve aşırı mühendislik açısından sınandı.

---

## 1. Özet

| Madde | Karar | Öncelik | Kısa gerekçe |
|---|---|---|---|
| M03-01 Seed MERGE kütüğü eziyor | **DEĞİŞTİR** | P1 · KRİTİK | İddia doğru. Ancak aynı sorun `MaintenanceContracts` MERGE'ünde de var (V15_Seed.sql:2437-2441) ve kapsama alınmalı. |
| M03-02 Detay kartı + geçmiş | **KABUL** | P1 | Projenin ana sorusu bu. Detay/geçmiş ucu gerçekten yok. |
| M03-03 Garanti + sözleşme bağı | **DEĞİŞTİR** | P2 | Gerekli, ama kabul (3) mevcut koda uymuyor. Garanti verisi bugün yok, kural bilinmiyor. |
| M03-04 Yaşam döngüsü | **DEĞİŞTİR** | P2 | Gerekli ama fazla geniş. "Serviste-Arızalı" elle tutulursa bayatlar. "Taşıma" ayrı özellik değil. Müdür onay akışı fazla. |
| M03-05 KPI seti | **DEĞİŞTİR** | P3 | Dört maddeye bağımlı. Model bazlı oran normalizasyon olmadan anlamsız. |
| M03-06 CRUD | **KABUL** (notlarla) | P1 | Doğru. Kütük bugün yalnız SQL ile düzeltilebiliyor. |
| M03-07 Audit | **KABUL** | P1 | M03-06 ile aynı sürümde çıkması zorunlu. |
| M03-08 Saha düzeltmesi kütüğe dönmüyor | **DEĞİŞTİR** | P2 | Hata gerçek. Ayrı öneri tablosu gereksiz; fark, bakım kaleminden türetilebilir. |
| M03-09 Bakım eşleşmesi | **DEĞİŞTİR** | P1 | Hata gerçek. "Sıralama kayar" iddiası abartılı. Planlı Bakım modülüyle tek sahiplik gerekli. |
| M03-10 Tarih/tip/model normalizasyonu | **DEĞİŞTİR** | P2 | Tarih dönüşümü gerekli. "Tip farkı bakım eşleşmesini bozuyor" iddiası **yanlış**. Model eşanlam tablosu fazla. |
| M03-11 Veri kalitesi ekranı | **DEĞİŞTİR** | P2 | Gerekli. "Birleştir" işlemi daraltılmalı, sayımlar canlı DB'ye bağlanmalı. |
| M03-12 Sayfalama + Excel | **DEĞİŞTİR** | P2 | Girişte yükleme ve export gerekli. Sunucu sayfalaması 1.324 satır için acil değil. |
| M03-13 İzin ayrıştırma | **DEĞİŞTİR** | P2 | İddia doğru, ama KRİTİK değil (iç kullanıcıya sınırlı sızıntı). `devices.export` gereksiz. |

**Eklenen maddeler:** M03-D01 (canlı DB kütük profili, P1), M03-D02 (normalize seri ile eşleşme, P2), M03-D03 (sözleşme ucu izin açığı, P2).

---

## 2. Madde madde değerlendirme

### M03-01 · DEĞİŞTİR · P1 (KRİTİK)
**Doğrulama:**
- `V15_Seed.sql:1360-1366`: `WHEN MATCHED THEN UPDATE SET … SerialNo=s.SerialNo, CustomerName=s.CustomerName, … IsActive=1`. Aynı yapı 1786-1792, 2199-2205 ve 2336-2342'de de var. **Doğru.**
- `Program.cs:26-31`: setup açıkken `Database/*.sql` dosya adı sırasıyla uygulanıyor. Seed (`DengeERP_V15_Seed.sql`) her seferinde yeniden çalışıyor. **Doğru.**

**Tasarımcının kaçırdığı:** `V15_Seed.sql:2437-2441`'deki `MaintenanceContracts` MERGE'ü de `CustomerName`, `ProductsText`, `AnnualFrequency`, `ContractTotal` alanlarını ve `IsActive=1`'i her kurulumda ezer. M03-03 ve M03-09 cihazı sözleşmeye bağlıyor ve PB üretimi `ProductsText` adedine dayanıyor. Bu yüzden sözleşme tarafı ezilirse:
- pasife alınmış (iptal) bir sözleşme yeniden aktifleşir,
- startup'ta `EnsureMaintenancePlansAndWorkOrdersAsync` (P.cs:34) bu sözleşme için PB üretebilir.

Bu da aynı sınıfta, sessiz bir veri bozulmasıdır.

**Revize:** Dört `SecurityDevices` MERGE'ünde ve `MaintenanceContracts` MERGE'ünde `WHEN MATCHED` dalı kaldırılır; yalnız `WHEN NOT MATCHED THEN INSERT` kalır. `IsActive=1` zorlaması da kaldırılır. Kabul: tasarımdaki 4 kriter, artı (5) `IsActive=0` yapılan sözleşme setup=true ile yeniden başlatmadan sonra 0 kalır ve PB üretilmez. Değişiklik ilk CRUD sürümünden **önce** canlıya çıkmalıdır.

### M03-02 · KABUL · P1
**Doğrulama:**
- Tek uç `GET /api/security/devices` (P.cs:2232-2285).
- `app.js:562` satırları tıklanamaz.
- Detay/geçmiş ucu yok.

`ServicePartMovements.WorkOrderId` (ZZ_V120_Operations.sql:24) var, yani parça geçmişi iş emri üzerinden kurulabilir. Belge §5.3 "cihaz geçmişi, bakımlar, iş emirleri ve garanti durumu cihazla ilişkilendirilmeli" diyor. Belgedeki ana soru da bu maddeyle cevaplanıyor.

**Notlar:**
- `ServicePartMovements.UnitCost` fiyat/maliyettir. `finance.prices.view` (veya `finance.costs.manage`) yoksa cevapta yer almamalıdır. Kabul (4) bunu kapsıyor; test listesine açıkça yazılmalı.
- M01-16 gelene kadar arıza iş emirleri seri no metniyle eşleşir. Bu satırlar "metin eşleşmesi" etiketiyle gösterilmelidir. Tasarımda var, korunmalı.
- Garanti/sözleşme alanları M03-03 gelene kadar "Bilinmiyor" görünür. Bu kart M03-03'ü beklememeli.

### M03-03 · DEĞİŞTİR · P2
**Doğrulama:** `SecurityDevices`'te garanti ve sözleşme kolonu yok (V15_Schema.sql:5-23). Atölyede garanti alanları var. **Doğru.**

**Sorunlar:**
1. Kabul (3) "sözleşme ekranındaki cihaz sayısı artar" mevcut koda uymuyor. `/api/maintenance/contracts` içindeki `DeviceCount` (P.cs:2301), **bakım planının** `MaintenanceDeviceItems` adedidir, bağlı kütük cihazı sayısı değildir. İki sayı karıştırılırsa yanlış KPI çıkar.
2. Bugün garanti verisi **hiç yok**. Garanti süresi kuralı da belirsiz (tasarım §4 soru 2). Maddenin değeri, garanti kuralı netleşip toplu doldurma yapılınca ortaya çıkar.
3. İş emri rozeti, arıza iş emrinin cihaza bağlı olmasını (M01-16) gerektirir. Bağımlılık eksik yazılmış.

**Revize:** Kolonlar aynen eklenir: `WarrantyStartDate`, `WarrantyEndDate`, `WarrantySource`, `MaintenanceContractId` (FK). Ek olarak:
- Kabul (3) şöyle olur: "Sözleşme listesinde ayrı bir 'Bağlı cihaz' sayısı gösterilir; bakım planı `DeviceCount` değeri değişmez."
- Toplu garanti doldurma, kullanıcı garanti kuralını onayladıktan sonra tek seferlik script ile yapılır (teslim + X ay, `WarrantySource='Hesaplandı'`).
- İş emri rozeti M01-16'ya bağlanır.
- Kabul (1), (2) ve (5) korunur.

### M03-04 · DEĞİŞTİR · P2
**Doğrulama:**
- `InstallStatus` serbest metin (V15_Schema.sql:19).
- PB üretimi yalnız `IsActive=1` ile süzülüyor (P.cs:3011). **Doğru.**

**Sorunlar:**
1. **"Serviste-Arızalı" elle tutulan durum olmamalı.** Açık arıza iş emri olan cihazdan türetilmelidir. Elle tutulursa iş emri kapanınca bayat kalır.
2. **"Taşıma" ayrı bir özellik değildir.** Müşteri/lokasyon düzenlemesidir ve M03-06 + M03-07 ile zaten karşılanır; geçmiş audit'te kalır.
3. **İki adımlı "müdür onayı" fazla.** Organizasyon şeması bile yok. İzin + zorunlu gerekçe yeterlidir.
4. **`IsActive` ile `LifecycleStatus` çakışıyor.** Tanım net olmalı: `IsActive` = kayıt geçerli mi (mükerrer/hatalı kayıt pasifi); `LifecycleStatus` = cihazın fiziksel durumu.
5. City/District, proje geneli müşteri/lokasyon ana verisi kararına (envanter gözlem 7) bağlı. `Zone` ise sahadan gelen bölge (M03-08) için faydalı.

**Revize:**
- `LifecycleStatus` değerleri: Kurulu / Sevk Edildi-Kurulum Bekliyor / Devre Dışı (Söküldü) / Hurdaya Ayrıldı / Bilinmiyor. "Serviste" rozeti açık arıza iş emrinden hesaplanır.
- Eklenecek alanlar: `InstallDate`, `Zone`, `City` (opsiyonel, tahmin edilmez). District eklenmez; müşteri/lokasyon ana veri kararına bırakılır.
- Devre Dışı ve Hurdaya Ayrıldı cihazlar PB üretiminden çıkarılır; açık işler silinmez, uyarı verilir.
- Hurdaya ayırma `devices.manage` + gerekçe ile tek adımda yapılır ve gerekçeyle geri alınabilir. (VARSAYIM: Müdür/Yardımcısı.)
- Ayrı "taşıma" ekranı yok.

### M03-05 · DEĞİŞTİR · P3
**Doğrulama:**
- KPI'lar statik (app.js:550-553).
- Tekrar arıza, `WorkOrders.SerialNumbers` metniyle ve yalnız PB dışı işlerde hesaplanıyor (Ops.cs:93-96). **Doğru.**

**Sorun:** Madde M03-02, M03-03, M03-04 ve M01-16'ya bağlı. Model bazlı arıza oranı, model normalizasyonu (M03-10) olmadan yanıltıcı olur. Veri kalitesi sayaçları zaten M03-11'de.

**Revize:** İlk sürümde yalnız iki KPI olur, her ikisi de tıklanabilir ve sunucuda hesaplanır:
- (b) son tamamlanan PB'si 12 aydan eski sözleşmeli cihaz,
- (d) 90 günde 2 veya daha fazla PB dışı iş emri olan cihaz (yalnız cihaz kimliği veya normalize seri ile; seri no'suz cihaz dahil edilmez).

"Garanti 60 gün" KPI'ı, garanti verisi dolduktan sonra eklenir. Model bazlı oran M03-10 sonrasına ertelenir.

### M03-06 · KABUL · P1
**Doğrulama:**
- Yalnız GET var.
- `devices.manage` izin kataloğunda yok (P.cs:3905).
- `SourceKey NOT NULL UNIQUE` (V15_Schema.sql:8). `MAN-…` anahtarı bu kısıtla uyumlu.

**Notlar (uygulama sırasında dikkat):**
- Seed'de 38 mükerrer seri grubu var. Bu yüzden `SerialNoNormalized` üzerindeki indeks **UNIQUE olamaz**. Tekillik uygulamada (409) kontrol edilir; indeks yalnız arama içindir.
- Normalize kuralı `UPPER(LTRIM(RTRIM(...)))` yeterli. İç boşluk, `-`, `.`, `/` ve baştaki sıfırlar **silinmez** (karar: seri no metin).
- Yeni `MAN-` kayıtları seed'in `WHEN NOT MATCHED` dalıyla çakışmaz. M03-01 önce çıkmalıdır.

### M03-07 · KABUL · P1
Projede audit yok (envanter gözlem 3). Bu yüzden kütüğe yazma açılırken audit de birlikte gelmeli. Tablo tasarımı yalın ve yerinde. `UserName` alanının kopyalanması, kullanıcı adı değişse bile geçmişin okunabilir kalması için doğru bir seçim.

### M03-08 · DEĞİŞTİR · P2
**Doğrulama:** P.cs:2513-2521 yalnız `MaintenanceDeviceItems` ve `WorkOrders` tablolarını güncelliyor. `SecurityDeviceId` boşsa bağlama yapılmıyor. **Hata gerçek.**

**Sorun:** Ayrı `SecurityDeviceChangeRequests` tablosu gereksiz. Önerinin verisi zaten bakım kaleminde duruyor:
- `MaintenanceDeviceItems.SerialNo/Zone`,
- `CompletedBy/CompletedAt`.

Kütükle fark, sorguyla türetilebilir.

**Revize:**
- (a) Form kapanışında `SecurityDeviceId` boşsa, aynı müşterinin aktif kütüğünde normalize seri ile **tek** eşleşme varsa kalem cihaza bağlanır. Birden fazla eşleşme varsa bağlanmaz.
- (b) M03-11 veri kalitesi ekranına "Sahadan gelen farklar" listesi eklenir. Liste, `MaintenanceDeviceItems` ile `SecurityDevices` arasında seri veya bölge farkı olan kalemleri ve kütüğe bağlanmamış kalemleri gösterir.
- (c) `devices.manage` sahibi "Kütüğe uygula / Yok say" der. Uygulamada kütük güncellenir ve M03-07'ye "Sahadan Düzeltme" kaydı düşer (teknisyen = `CompletedBy`, onaylayan = işlemi yapan). "Yok say" seçimi kalemde bir bayrakla (`KutukFarkiKapatildi BIT`) tutulur.
- Kabul (1)-(4) aynen geçerlidir. Yeni tablo yoktur.

### M03-09 · DEĞİŞTİR · P1
**Doğrulama:**
- P.cs:3010-3016: `CustomerName=@Customer` birebir eşitlik ve `ORDER BY SecurityDeviceId`.
- P.cs:3032: envanter yetmezse `(0,null,null)`, yani **sessizce** seri no'suz kalem üretiliyor. **Doğru.**

**Abartılı iddia:** "Yeni cihaz eklenince sıralama kayar" kısmen yanlış. Bir plan içindeki kalemler `(PlanId, Type, Ordinal)` ile bir kez üretilip yeniden okunuyor (P.cs:3019-3031); sonradan cihaz eklenmesi mevcut kalemi değiştirmiyor. Kayma yalnız **sonraki dönem** planında oluşur. Asıl zararlar şunlar:
- (i) müşteri adı yazım farkında hiç eşleşme olmaması,
- (ii) bir cihaz pasife alınınca kalan cihazların sessizce eksik eşlenmesi,
- (iii) seri no'suz kalem üretilmesi.

**Revize:**
- Öncelik sırası tasarımdaki gibi kalır: sözleşmeye bağlı cihaz → önceki dönem kalemlerinin `SecurityDeviceId`'leri → isim + tip.
- İkinci adım, M03-03'ün FK'sı gelmeden de uygulanabilir ve en ucuz iyileştirmedir. Bu yüzden ilk iş olarak çıkarılabilir.
- Kabul (1)-(4) korunur.
- **Planlı Bakım modülündeki eşdeğer madde ile tekilleştirilmeli.** Kod `EnsureIndividualMaintenanceWorkOrdersAsync` içinde ve tek modül sahiplenmeli (önerim: Planlı Bakım). Kütük tarafında yalnız `MaintenanceContractId` ve eşleştirme ekranı kalır.

### M03-10 · DEĞİŞTİR · P2
**Doğrulama:**
- `DeliveryDateText` metin (V15_Schema.sql:18). `44083` = 2020-09-09 hesabı doğru.
- KPI'ın `'Kapı Dedektörü'` birebir sayımı da doğru (app.js:551).

**Yanlış iddia:** "Tip adı farkı bakım eşleşmesinde hata kaynağı" doğru değil. PB üretimi tipi `UPPER(DeviceType) LIKE '%KAPI%' OR LIKE '%DEDEKT%'` ile eşliyor (P.cs:3012-3013), yani kütükteki `Kapı Dedektörü` sorunsuz eşleşiyor. Fark yalnız ekran/KPI ve rapor tutarlılığını etkiliyor.

**Aşırı mühendislik:** 193 model metni için ayrı `SecurityDeviceModelAliases` tablosu ve bakım ekranı bu aşamada fazla.

**Revize:**
- (a) `DeliveryDate DATE` dönüşümü aynen yapılır (idempotent; `DeliveryDateText` korunur; yedek + `RESTORE VERIFYONLY` sonrası).
- (b) Cihaz tipi tek seferlik UPDATE ile `Kapı Tipi Metal Dedektörü` adına indirilir (M03-01 sonrası, aksi halde seed geri yazar). Ekranda tip sabit listeden seçilir.
- (c) Model için alias tablosu yerine `ModelNormalized` kolonu kullanılır: büyük harf, `-` ve boşluk farkı giderilir. Hesap tek seferlik ve kayıt/düzenlemede yapılır; filtre bu kolondan beslenir. Orijinal metin `Model`/`ProductRaw`'da kalır.
- Kabul (1)-(5) korunur.

### M03-11 · DEĞİŞTİR · P2
**Doğrulama:** Ekranda yalnız "Seri No Mevcut" sayacı var (app.js:552). İhtiyaç gerçek; belge §14'te veri kalitesi açık iş olarak listeleniyor.

**Sorunlar:**
1. Rakamlar (38/96, 96, 299) seed'den çıkarılmış; canlı DB'de doğrulanmamış (bkz. M03-D01).
2. "Birleştir" işleminin bakım kalemlerini otomatik taşıması riskli. Aynı plan içinde iki kalem aynı cihaza düşebilir.

**Revize:**
- Ekranda dört liste olur: mükerrer, seri no'suz, lokasyonsuz, sözleşmesiz kurulu. Bunlara M03-08'deki "Sahadan gelen farklar" listesi eklenir.
- "Birleştir": ikincil kayıt pasif olur ve `MergedIntoDeviceId` alır. Bakım kalemleri ana kayda yalnız **aynı planda çakışma yoksa** taşınır; çakışma varsa işlem 409 ile durur. PB numaraları değişmez ve silinmez.
- "Farklı cihaz" işaretlemesi gerekçeyle yapılır.
- Kabul (1)-(4) korunur.

### M03-12 · DEĞİŞTİR · P2
**Doğrulama:**
- Girişte tüm kütük yükleniyor (app.js:152).
- Tablo ilk 1.000 satırda kesiliyor (app.js:562-563).
- Export yok. **Doğru.**

**Sorun:** 1.324 satır için tam sunucu tarafı sayfalama bu aşamada zorunlu değil. Asıl kazanç, girişte yüklememek ve filtreyi sunucuya taşımak.

**Revize:**
- (a) Kütük ekran açılınca yüklenir (S).
- (b) Mevcut uca `status`, `customer`, `contractId`, `includeInactive` filtreleri eklenir. 1.000 sınırı "daha fazla göster" ile aşılır. `page/pageSize` ileride eklenebilir.
- (c) `GET /api/security/devices.xlsx`, mevcut `/api/reports/workorders.xlsx` kalıbıyla yazılır. Seri no hücresi metin biçiminde olur. Yetki: `devices.view` **ve** mevcut `reports.export`; yeni `devices.export` izni açılmaz.
- Kabul (1), (3), (4) korunur. Kabul (2) "1.000'den fazla satır gezilebilir" olarak sadeleşir.

### M03-13 · DEĞİŞTİR · P2
**Doğrulama:**
- P.cs:2236 `devices.view || workorders.view`.
- Muhasebe, Depo ve Kiralama Operasyon şablonlarında `workorders.view` var (P.cs:3931-3933).
- `UnitAllowed` boş `AllowedUnits` ile her birime izin veriyor (P.cs:2807). Kullanıcı oluştururken boş liste tüm birimlere dönüşüyor (P.cs:216).
- Ön yüz bu uca yalnız `devices.view` ile gidiyor (app.js:152). Fallback kaldırılınca hiçbir ekran kırılmaz. **İddia doğru.**

**Önem derecesi:** Sızan veri müşteri adı, lokasyon ve irtibat **adı**; şirket içi kullanıcılara açık, veri kaybı yok. "KRİTİK" değil, P2.

**Revize:**
- (a) Uç yalnız `devices.view` ile açılır.
- (b) Yazma `devices.manage` ile yapılır. Export `reports.export` + `devices.view` ile yapılır (yeni `devices.export` açılmaz, bkz. M03-12).
- (c) `AllowedUnits` boş davranışı proje geneli güvenlik maddesine bırakılır; bu modülde ele alınmaz.
- Kabul (1)-(3) korunur. Aynı açığın `/api/maintenance/contracts` ucundaki karşılığı için bkz. M03-D03.

---

## 3. Eklenen maddeler

### M03-D01 · VERİ · Canlı/test DB'de kütük veri profili (salt okunur) — P1, efor S
- **Neden:** Tasarımdaki bütün sayılar seed dosyasından çıkarılmış ve canlıda doğrulanmamış: 1.324, 96 seri no'suz, 38/96 mükerrer, 299 lokasyonsuz, 940 durumu boş, 1.137 tarih. Pilotta SQL ile elle düzeltme yapılmış olabilir. M03-10 dönüşümü, M03-11 kabul kriterleri ve M03-09 eşleştirmesi bu sayılara dayanıyor.
- **Mevcut:** Yok. Tasarım §5 "SSMS ile doğrulanmalı" diyor ama madde olarak tanımlamamış.
- **İş:**
  1. `Database/` dışında tutulan, yalnız SELECT içeren bir `kutuk_profil.sql` yazılır. Startup'ta çalışmaz.
  2. Tip/marka dağılımı, seri no'suz, normalize mükerrer, lokasyonsuz, `DeliveryDateText` desen dağılımı, `SecurityDeviceId`'si boş PB kalemleri ve sözleşme–kütük müşteri adı eşleşme oranı çıkarılır.
  3. Sonuç M03-10 ve M03-11'den önce rapora yazılır.
- **Kabul:**
  1. Script hiçbir tabloyu değiştirmez.
  2. Çıktı sayıları tasarım tablosuyla karşılaştırılır; fark varsa M03-10/11 kabul rakamları güncellenir.
  3. `MaintenanceDeviceItems.SecurityDeviceId IS NULL` adedi raporlanır.
- **Roller:** Geliştirici/İT (DB okuma).

### M03-D02 · HATA · Kütük eşleşmelerinde normalize seri no kullanımı — P2, efor S
- **Neden:** Kütüğü kullanan diğer noktalar birebir metin eşitliğine bağlı. Bu yüzden boşluk veya büyük/küçük harf farkında öneri ve tekrar arıza kaçıyor.
  - Planlama sahası önerisi `sd2.CustomerName=w.CustomerName AND sd2.SerialNo=w.SerialNo` kullanıyor (P.cs:632-634).
  - Operasyon merkezi tekrar arızası seri metnini kırpıp büyük/küçük harf duyarsız grupluyor (Ops.cs:93-96), ama kütükle hiç ilişkilendirmiyor.
- **İş:** M03-06'daki `SerialNoNormalized` kolonu ve aynı normalize kuralı (C# tarafında tek yardımcı fonksiyon) bu iki noktada kullanılır. Site önerisinde müşteri adı eşitliği şartı, seri tekil eşleştiğinde gevşetilir. Tekrar arıza satırına cihaz kimliği eklenir.
- **Kabul:**
  1. `' abc-001 '` seri no'lu iş emrinde, kütükteki `ABC-001` cihazının lokasyonu önerilir.
  2. Aynı normalize seri birden fazla aktif cihazda varsa öneri verilmez ("belirsiz").
  3. Baştaki sıfırlar ve `-` `.` `/` karşılaştırmada korunur.
- **Bağımlılık:** M03-06.

### M03-D03 · GÜVENLİK · Bakım sözleşmeleri ucunda aynı izin açığı — P2, efor S
- **Neden:** `/api/maintenance/contracts`, `maintenance.view || workorders.view` ile açılıyor (P.cs:2292). M03-13'te kapatılan açığın aynısı bu uçta da var. Muhasebe, Depo ve Kiralama 87 sözleşmenin müşteri, adres ve ürün listesini çekebiliyor. Fiyatlar `finance.prices.view` ile gizleniyor (P.cs:2329-2333), adres ve müşteri bilgisi gizlenmiyor. M03-03 sözleşme–cihaz bağını açınca bu uç kütük verisine de kapı olacak.
- **İş:** Uç yalnız `maintenance.view` ile açılır. Ön yüzde bu uca giden çağrının da aynı izne bağlı olduğu doğrulanır.
- **Kabul:**
  1. Yalnız `workorders.view` sahibi kullanıcı 403 alır.
  2. `maintenance.view` sahibi Şef 200 alır; fiyat alanları `finance.prices.view` yoksa boş döner.
- **Roller:** Rol şablonu değişmez (Şef, Müdür, Operasyon Uzmanı, Genel Koordinatör'de `maintenance.view` var).

---

## 4. Önerilen uygulama sırası (kullanıcı önceliği c → b → a, kritikler önde)

| Sürüm | Maddeler | Not |
|---|---|---|
| V1.21-a | M03-01 (KRİTİK), M03-D01 | Önce veriyi koru, sonra gerçeği ölç. |
| V1.21-b | M03-02 (salt okunur kart), M03-06 + M03-07, M03-13, M03-D03 | Kart hemen değer üretir; CRUD audit'le birlikte çıkar. |
| V1.22 | M03-09 (önceki dönem ID'leri), M03-03, M03-04, M03-10 | Planlı Bakım modülüyle koordineli. |
| V1.23 | M03-08, M03-11, M03-12, M03-D02 | Veri kalitesi döngüsü. |
| Sonra | M03-05 | Veri dolduktan sonra. |

## 5. Denetçi notları
- Tasarımın kod referansları satır düzeyinde doğru çıktı. Önemli bir uydurma yok.
- İki iddia düzeltildi: tip farkının bakım eşleşmesini bozduğu (M03-10) ve sıralamanın plan içinde kaydığı (M03-09).
- Aşırı mühendislik görülen yerler sadeleştirildi: model alias tablosu, değişiklik öneri tablosu, iki adımlı hurda onayı, ayrı taşıma özelliği, yeni `devices.export` izni ve tam sayfalama.
- Bütün rol atamaları VARSAYIM olarak kalır; organizasyon şeması gelince güncellenecek.
- Kullanıcı kararlarıyla çelişen madde yok. Logo CRM / Flowick ve kiralama envanteri kapsam dışında tutulmuş, bu doğru.
- Kütük tasarımın kendisiyle ilgili olmayan iki gözlem:
  - Startup setup'ı açık olduğu sürece `EnsureMaintenancePlansAndWorkOrdersAsync` (P.cs:34) her açılışta çalışır. M03-04 durum filtresi bu yola da uygulanmalıdır.
  - Yeni şema scriptleri `ZZ_V121_*.sql` adıyla seed'den sonra çalışacağı için, tip/tarih dönüşümleri seed tarafından ezilmez; ancak bu, M03-01 düzeltmesi yapıldıktan sonra geçerlidir.
