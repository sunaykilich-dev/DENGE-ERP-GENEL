# M08 — Eğitim, Yetkinlik ve Personel Gelişimi — Gereksinim Tasarımı

> **Tarih:** 21 Ekim 2026 · **Kaynak sürüm:** V1.20.1 (salt okunur inceleme, kaynak koda dokunulmadı)
> **Kapsam:** Sadece teknik servis personeli (Güvenlik Sistemleri, Haberleşme, POC, Mobilite, Araç Takip). Logo CRM / Flowick kapsam dışı.
> **Öncelik sırası (kullanıcı kararı):** (c) yeni özellik → (b) mevcut eksikler → (a) güvenlik/üretime hazırlık. Kritik veri kaybı/sızıntısı varsa ayrıca "KRİTİK" yazılır.
> **Kısaltmalar:** `P.cs` = `DengeERP.Api/Program.cs`, `Ops.cs` = `OpsSuite.cs`, `app.js` = `wwwroot/app.js`, `V113.sql` = `Database/ZZ_V113_TrainingDevelopment.sql`.
> **Belgedeki temel ilke (§5.8):** Eğitim saati tek başarı ölçütü değildir; esas olan **eğitim öncesi ve sonrası saha davranışı**dır. Kritik İSG uygunsuzluğu ortalama puan içinde kaybolmamalıdır.

---

## 1. Mevcut durum (kodda ne var?)

### 1.1 API uçları

| Uç | Yer | Ne yapıyor | İzin |
|---|---|---|---|
| `GET /api/training/overview?year=` | P.cs:1485-1536 | Tek çağrıda personel, katalog, kriterler, yıl planı, önceki yılın tamamlanan planları (`carryoverPlans`), oturumlar, katılım, yetkinlik kataloğu, yetkinlik seviyeleri ve **Yıl-1..Yıl+1 arası tüm gözlemleri** döndürür. Birim kapsamı `Personnel.UnitCode` ile (P.cs:1495). Sayfalama yok. | `training.view` |
| `POST /api/training/courses` | P.cs:1538-1569 | Eğitim + 1–30 saha kontrol maddesi (satır başı `!` = kritik). Kod tekil. **Düzenleme / pasife alma ucu yok.** | `training.manage` + birim |
| `POST /api/training/plans/bulk` | P.cs:1571-1596 | ≤300 personele aynı eğitimi aynı yıl için atar; tekrar atama kayıt üretmez (UQ). **Erteleme / iptal / tarih değişikliği ucu yok.** | `training.manage` + birim |
| `POST /api/training/sessions` | P.cs:1598-1610 | Gerçekleşen oturum (tarih, eğitmen metni, süre, yer). **Kursun birimine yetki kontrolü yok; ileri tarihli oturum kabul ediliyor.** | `training.manage` |
| `POST /api/training/attendance` | P.cs:1612-1647 | Kişi bazında tek tek katılım + ön/son puan (MERGE). `Attended=1` ise **aynı yıl** planını `Tamamlandı` yapar (P.cs:1640-1642). Son puan ne olursa olsun plan tamamlanır. | `training.manage` + birim |
| `POST /api/training/competencies` | P.cs:1649-1666 | Kişi+yetkinlik için **MERGE ile üzerine yazar** (P.cs:1655-1659); önceki seviye ve kanıt kaybolur. `AssessedBy` = oturumdaki ad-soyad metni. | `training.manage` veya `training.observe` |
| `POST /api/training/observations` | P.cs:1668-1710 | Saha gözlemi: aşama 0/30/60/90, madde puanı -1(gözlenmedi)/0/1/2, puan = cevaplanan maddeler ortalaması %, kritik maddede `0` → `CriticalFailure=1` (P.cs:1688-1690). `WorkOrderId` opsiyonel, yalnızca FK kontrolü; **iş emrinin birimi veya personelin o işte atanmış olması kontrol edilmez.** Gözlemci = oturum adı metni. | `training.observe` veya `training.manage` |
| `GET /api/training/export.csv` | P.cs:1712-1731 | Yalnız yıllık plan + son "sonra" puanı CSV (BOM, formül enjeksiyonu korumalı). Gözlem/yetkinlik dışa aktarımı yok. | `training.view` + `training.export` |
| Ops uyarısı | Ops.cs:50-63 | 7 gün içinde vadesi gelen tamamlanmamış plan → "Bilgi" uyarısı. **30/60/90 gecikmesi ve kritik İSG uygunsuzluğu uyarı üretmez.** | `training.view` |

Yardımcı: `TrainingCanAccessPersonnelAsync` (P.cs:2796-2802) — personel aktif ve birimi kullanıcının biriminde mi? Birimsiz personeli yalnız Admin / tüm birim yetkili görür.

### 1.2 Tablolar (V113.sql)

- `TrainingCourses` (V113.sql:3-19): kod, başlık, kategori, birim, **neden / hedef davranış / başarı ölçütü (serbest metin)**, süre, zorunlu, aktif. **Sayısal geçme puanı, gözlem eşiği, yenileme periyodu yok.**
- `TrainingCriteria` (21-31): kurs başına kontrol maddesi, `IsCritical`, sıra. Pasif/versiyon alanı yok.
- `TrainingPlans` (33-48): personel+kurs+yıl tekil; durum varsayılan `Planlandı`, `CompletedAt`. Durum kataloğu/CHECK yok.
- `TrainingSessions` (50-62): `TrainerName` metin; katılımcı daveti/planlı oturum kavramı yok.
- `TrainingAttendance` (64-77): katılım, ön/son puan 0–100.
- `CompetencyCatalog` (79-89): kod, ad, birim, önerilen hedef 1–4, kritik. **Kursla ilişki yok; yönetim ucu yok (yalnız tohum).**
- `PersonnelCompetencies` (91-106): **kişi+yetkinlik başına tek satır (UQ)** → geçmiş tutulmuyor.
- `TrainingObservations` (108-126) + `TrainingObservationRatings` (128-136): gözlem başlığı + madde puanları. Düzeltici faaliyet yalnız serbest metin `ActionPlan`; sorumlu/termin/kapanış yok. Gözlemi personelin "gördüm" onayı yok.
- Tohum veri (138-201): 7 eğitim (İSG, iletişim, X-Ray, kapı dedektörü, telsiz, POC, mobilite), 29 kontrol maddesi (11 kritik), 8 yetkinlik.

### 1.3 Ön yüz (app.js)

- Menü: `training.view` ile "Eğitim / Personel Gelişimi" (app.js:197).
- Modül: app.js:1280-1434 — 7 sekme: Yönetim Özeti, Yıllık Plan, Eğitim Kataloğu, Katılım ve Sınav, Saha Gözlemi, Yetkinlik Matrisi, Bireysel Gelişim (app.js:1412-1413).
- **30/60/90 takip listesi tarayıcıda hesaplanır** (`trainingFollowUps`, app.js:1293-1305): tamamlanan plan tarihi + 30/60/90; aynı kişi+kurs+aşamada gözlem varsa "yapıldı". Sunucuda karşılığı yok, uyarıya dönmez.
- Yönetim Özeti KPI'ları (app.js:1316-1320): yıllık gerçekleşme %, **saha gözlem ortalaması %** (kritikli gözlemler ortalamaya karışır, ayrı kritik sayacı yok), hedef yetkinlik %, 30/60/90 geciken sayısı.
- Gözlem formu (app.js:1364-1379): iş emri seçimi `state.workOrders.slice(0,400)` — **personelden bağımsız, yalnız ilk 400 iş** (app.js:1372). Kritik madde "Gözlenmedi" seçilerek geçilebilir. Kritik `0` varsa yalnız `confirm()` uyarısı (app.js:1433).
- Katılım formu kişi kişi (app.js:1360); 15 kişilik eğitimde 15 ayrı kayıt.
- İş emri detay penceresinde (`openWorkOrder`) gözlem başlatma veya bağlı gözlemi görme **yok**.

### 1.4 İzinler

- `training.view`, `training.manage`, `training.observe`, `training.export` (P.cs:3890-3893).
- Rol varsayılanları (P.cs:3921-3935): Üst Yönetim / TS Müdürü / Müdür Yrd: dördü; Şef: view+observe; İK: view+manage+export; Genel Koordinatör: view+export; **Teknisyen: hiçbiri** → kendi gelişim kartını göremez.
- `training.view` sahibi kapsamındaki **tüm personelin gözlem notlarını, puanlarını, yetkinlik kanıtlarını** görür (ayrım yok).

### 1.5 Kanıtlı sorunlar

1. Yetkinlik değerlendirmesi üzerine yazılıyor (P.cs:1655-1659) → "eğitim sonrası gelişti mi?" sorusu geçmiş olmadan cevaplanamıyor.
2. Plan, sınav puanı 0 olsa bile katılımla `Tamamlandı` oluyor (P.cs:1638-1645).
3. İleri tarihli oturuma katılım girilirse plan bugünden `Tamamlandı` sayılıyor (oturum tarihi doğrulanmıyor, P.cs:1601).
4. Plan yılı ≠ oturum yılı ise (ör. 2026 planı Ocak 2027'de tamamlandı) plan hiç tamamlanmıyor (P.cs:1642).
5. Kritik İSG uygunsuzluğu yalnız bir bayrak; ortalama KPI'da kayboluyor, uyarı/aksiyon/yeniden gözlem zorunluluğu yok.
6. Oturum oluştururken kursun birimine yetki kontrolü yok (P.cs:1598-1610) — diğer uçlarda var.
7. Düzeltme imkânı yok: yanlış girilen kurs, plan, oturum, gözlem düzeltilemez veya iptal edilemez.

---

## 2. Olması gereken (Denge Elektronik teknik servis için)

### 2.1 Roller ve sorumluluklar (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol (mevcut rol adı) | Bu modülde yaptığı | İzinler |
|---|---|---|
| Teknik Servis Müdürü / Yardımcısı | Katalog ve yıllık planı onaylar; birimler arası raporları izler; kritik İSG düzeltici faaliyetini kapatma onayı verir. | view, manage, observe, export, (yeni) `training.view_detail` |
| İnsan Kaynakları | Katalog, yıllık plan, oturum, toplu katılım, belge/sertifika geçerlilik kayıtları. **Saha gözlemi yapmaz.** | view, manage, export, `training.view_detail` |
| Şef (birim) | Kendi birimindeki teknisyenlere saha gözlemi (iş emri üzerinden), yetkinlik değerlendirmesi, düzeltici faaliyet takibi. | view, observe, `training.view_detail` (kendi birimi) |
| Teknisyen | Kendi gelişim kartını görür, gözlemini "gördüm" diye onaylar ve yorum yazar. Başkasını göremez. | (yeni) `training.self` |
| Genel Koordinatör / Üst Yönetim | Özet KPI ve raporlar; kişi bazlı gözlem notlarına varsayılan olarak erişmez. | view, export |
| Eğitmen (iç/dış) | Sistem kullanıcısı olmak zorunda değil; oturumda ad olarak tutulur. | — |

### 2.2 Tutulacak veriler (artımlı; mevcut tablolara kolon / yanına tablo ekleyerek)

- **Katalog:** sınav geçme puanı (0–100), gözlem başarı eşiği (%), yenileme periyodu (ay; zorunlu/İSG için), geliştirdiği yetkinlik(ler), aktif/pasif; kriterlerde aktif/pasif (silme yok, geçmiş puanlar bozulmaz).
- **Plan:** durum kataloğu (Planlandı · Katıldı-Sınav Bekliyor · Tamamlandı · Başarısız-Tekrar · Ertelendi · İptal), erteleme/iptal gerekçesi, kim/ne zaman.
- **Belge/geçerlilik:** personel + kurs (veya belge türü) + veriliş tarihi + bitiş tarihi + belge no/açıklama.
- **Gözlem:** iş emri bağlantısı (kapsam doğrulanmış), gözlemci kullanıcı kimliği, sonuç (Başarılı / Gelişim Gerekli / Kritik), personel onayı (tarih + yorum), iptal (gerekçeli, soft).
- **Düzeltici faaliyet (kritik uygunsuzluk):** gözlem, kriter, açıklama, sorumlu, termin, durum (Açık / Kapatıldı), kapanış kanıtı, yeniden gözlem bağlantısı.
- **Yetkinlik geçmişi:** her değerlendirme ayrı satır (seviye, hedef, tarih, değerlendiren kullanıcı, kanıt, kaynak: gözlem/sınav/yönetici).

### 2.3 Akış

```
Katalog (neden / hedef davranış / eşik / kontrol maddeleri / yetkinlik)
   ↓
Yıllık plan (kişi × eğitim × hedef tarih)  ── ertele/iptal (gerekçeli)
   ↓
Oturum + toplu katılım + ön/son sınav
   ├─ son puan ≥ eşik (veya eşik yok) → Plan: Tamamlandı → 30/60/90 takip açılır
   └─ son puan < eşik → Plan: Başarısız-Tekrar
   ↓
Saha gözlemi (iş emrinden başlatılır, 0/30/60/90)
   ├─ kritik madde 0 → Gözlem: KRİTİK → Düzeltici faaliyet (sorumlu+termin) → uyarı (şef+müdür)
   │                   → yeniden gözlem başarılı + kanıt → faaliyet kapanır
   ├─ puan ≥ eşik ve kritik yok → Başarılı
   └─ diğer → Gelişim Gerekli (aksiyon planı)
   ↓
90. gün gözlemi başarılı → bağlı yetkinlik için "yeniden değerlendir" önerisi → yeni yetkinlik satırı (geçmiş korunur)
```

### 2.4 KPI ve raporlar (az ama işe yarar)

1. Yıllık plan gerçekleşme: zamanında / geç / açık (birim, şef, kişi).
2. Zorunlu eğitim ve belge uyumu: geçerli belgesi olan personel %, **süresi dolan / 30 gün içinde dolacak** liste.
3. 30/60/90 takip uyumu: zamanı gelen takiplerin kaçı yapıldı (geciken ayrı).
4. Saha gözlem başarı oranı: eşik üstü **ve** kritik yok sayılan gözlemler / tüm gözlemler (ortalama puan yalnız ikincil bilgi).
5. **Açık kritik İSG uygunsuzluğu**: sayı, en eski açık kaydın yaşı; ortalamadan bağımsız kutu.
6. Gelişim: aynı kişi+kurs için 0. gün → 90. gün gözlem puan farkı; ön/son sınav farkı.
7. Yetkinlik açığı: hedefin altındaki kişi-yetkinlik sayısı, kritik yetkinliklerde ayrı.
- Eğitim saati raporda yalnız bilgi olarak bulunur, başarı ölçütü olarak sunulmaz.

### 2.5 Doğrulamalar

- Kritik kontrol maddesi "Gözlenmedi" bırakılamaz; bırakılırsa gerekçe zorunlu ve gözlem sonucu "Eksik Gözlem" olur (başarılı sayılmaz).
- Gözlemci, gözlenen personel olamaz (kullanıcı ↔ personel bağlantısı üzerinden).
- Gözleme bağlanan iş emri, gözlemcinin birim kapsamında olmalı; personel o işte atanmış değilse uyarı (kimlik bazlı atama gelince engel).
- Oturum tarihi bugünden ileri olamaz (gerçekleşen oturum); planlı oturum ayrı durumdur.
- Yetkinlik seviyesi 1–4; hedef < mevcut ise uyarı. Kritik yetkinlikte kanıt metni zorunlu.
- Gözlem tarihi gelecekte olamaz; 30/60/90 aşaması, eğitimin tamamlanma tarihinden önce girilemez (uyarı).

---

## 3. Fark listesi (maddeler)

Sıralama: önce YENİ (c), sonra EKSİK/HATA/VERİ (b), en son GÜVENLİK (a).
**KRİTİK değerlendirmesi:** Bu modülde kendi başına KRİTİK seviyede sızıntı tespit edilmedi. M08-08 (yetkinlik geçmişinin üzerine yazılması) **tasarım gereği veri kaybıdır** ve (b) grubunun başında yapılmalıdır; ancak sistem dışına sızıntı olmadığı için KRİTİK etiketi verilmedi. Genel oturum/yetki açıkları (envanter "İlk gözlemler") bu modülü de etkiler.

### M08-01 · YENİ · Kritik İSG uygunsuzluğu için düzeltici faaliyet akışı
- **Açıklama:** Kritik maddede `0` alan her gözlem otomatik olarak bir **düzeltici faaliyet** kaydı açar: madde, açıklama, sorumlu (varsayılan: personelin şefi), termin (varsayılan 14 gün — bkz. §4), durum Açık/Kapatıldı. Kapatmak için (a) aynı kurs için kritik maddesi "Uygun" olan yeni bir gözlem veya (b) yetkili tarafından kanıt metni gerekir. Açık faaliyet ERP içi uyarı (Ops.cs alert) üretir; Yönetim Özeti'nde ayrı kutu.
- **Neden:** Belge §5.8: "kritik İSG uygunsuzluğu ortalama puan içinde kaybolmamalı". Bugün yalnız `CriticalFailure` bayrağı var; takip eden, kapanışı kanıtlanan bir akış yok.
- **Mevcut:** P.cs:1690 bayrak; app.js:1433 yalnız `confirm()`; Ops.cs:50-63 eğitim uyarısı sadece plan vadesi.
- **Kabul:** (1) Kritik maddede 0 içeren gözlem kaydedilince `TrainingCorrectiveActions`'da 1 açık kayıt oluşur (sorumlu+termin dolu). (2) `/api/ops/overview` uyarılarında "Kritik İSG uygunsuzluğu: <personel> / <madde>" görünür, birim kapsamına göre süzülür. (3) Kritik maddesi Uygun olan yeni gözlem girilince faaliyet otomatik "Kapatıldı" olur ve bağlantı tutulur. (4) Termini geçen açık faaliyet kırmızı uyarı olur. (5) Yönetim Özeti'nde "Açık kritik uygunsuzluk" sayısı ve tıklayınca liste; sayı = liste uzunluğu.
- **Roller:** Şef (sorumlu) — `training.observe`; Müdür — kapanış onayı `training.manage`.
- **Veri:** Yeni `TrainingCorrectiveActions(ActionId, ObservationId FK, CriterionId FK, PersonnelId, Description, ResponsibleUserId, DueDate, Status, ClosedAt, ClosedByUserId, ClosingObservationId NULL, ClosingEvidence)`.
- **Efor:** M · **Bağımlılık:** M08-13 (KPI düzeltmesi ile birlikte)

### M08-02 · YENİ · Saha gözlemini iş emrinden başlatma ve iş emrinde gösterme
- **Açıklama:** İş emri detay penceresine "Saha Gözlemi Yap" düğmesi (yalnız `training.observe`): iş emri, birim, atanmış teknisyenler önceden dolar; teknisyen ve kurs seçilir. İş emri detayında bağlı gözlemler (tarih, kişi, sonuç) listelenir. Gözlem formundaki iş emri seçimi sunucuda arama ile yapılır (ilk 400 sınırı kalkar). Sunucu, iş emrinin gözlemcinin birim kapsamında olduğunu doğrular; personel o işe atanmamışsa uyarı döner.
- **Neden:** Belge §5.8 "eğitimin gerçek sahada uygulanması için iş emrine bağlı saha gözlemi". Bugün bağlantı opsiyonel ve kopuk; şef sahadayken iş emrinden çıkıp ayrı modüle gitmek zorunda.
- **Mevcut:** app.js:1372 `state.workOrders.slice(0,400)`, personelden bağımsız; P.cs:1695 yalnız FK; `openWorkOrder` içinde gözlem yok.
- **Kabul:** (1) İş emri detayından açılan gözlem formunda iş emri no ve birim kilitli gelir. (2) Kaydedilen gözlem iş emri detayında görünür. (3) Başka birimin iş emri ile gözlem isteği 403 döner. (4) 400'den eski bir iş emri arama ile seçilebilir. (5) Atanmamış personel için kayıt yapılabilir ama yanıt `warning` içerir ve gözlemde "atama dışı" işareti tutulur.
- **Roller:** Şef — `training.observe` + `workorders.view`.
- **Veri:** `TrainingObservations` ADD `ObserverUserId INT NULL`, `OutsideAssignment BIT NOT NULL DEFAULT 0`.
- **Efor:** M · **Bağımlılık:** Atama doğrulaması için M01-10 (kimlik bazlı atama); o gelene kadar ad eşleşmesi ile uyarı.

### M08-03 · YENİ · Zorunlu eğitim / belge geçerlilik ve yenileme takibi
- **Açıklama:** Katalogda zorunlu eğitimlere "yenileme periyodu (ay)" alanı. Plan tamamlandığında geçerlilik bitişi hesaplanır; dış kurumdan alınan belgeler (ör. İSG temel eğitimi, yüksekte çalışma) elle girilebilir. Bitişe 30 gün kala ERP içi uyarı; "Süresi dolan / dolacak" listesi ve Yönetim Özeti'nde kutu. Süresi dolan zorunlu eğitim bir sonraki yıl planına önerilir (otomatik atama yok, yönetici onaylar).
- **Neden:** V1.13 changelog'u "yasal eğitim periyotları ayrı yönetilmelidir" diyor; teknik servis sahada İSG'ye bağlı çalışıyor ve bu takip Excel'e kalırsa modül yarım kalır.
- **Mevcut:** `TrainingCourses`'ta periyot alanı yok (V113.sql:3-19); belge kaydı tablosu yok.
- **Kabul:** (1) Yenileme periyodu 12 ay olan eğitimi 01.11.2026'da tamamlayan kişinin geçerlilik bitişi 01.11.2027 görünür. (2) Bitişe ≤30 gün kalan kayıt ops uyarısına düşer. (3) Elle girilen dış belge listede ve kişi kartında görünür. (4) "Süresi dolan" sayısı = tıklanınca açılan liste uzunluğu. (5) Sonraki yıl için öneri listesinden toplu plan oluşturulabilir; mevcut planlar tekrar oluşmaz.
- **Roller:** İK / Müdür — `training.manage`.
- **Veri:** `TrainingCourses` ADD `RenewalMonths INT NULL`; yeni `PersonnelCertificates(CertificateId, PersonnelId, CourseId NULL, CertificateName, IssuedOn, ValidUntil NULL, DocumentNo, Notes, CreatedByUserId, CreatedAt, IsCancelled)`.
- **Efor:** M · **Bağımlılık:** —

### M08-04 · YENİ · Atamada yetkinlik / belge uyarısı (engelleme değil)
- **Açıklama:** İş emrine veya toplu plana teknisyen atanırken, iş türü için tanımlı gerekli yetkinlik (ör. X-Ray PB → `XR` ≥ 3) veya zorunlu belge (İSG) yoksa/süresi dolmuşsa ekranda uyarı gösterilir; atama yapılabilir, uyarı ve atayan kişi geçmişe yazılır. Gerekli yetkinlik, birim + iş türü bazında basit bir eşleme tablosunda tutulur.
- **Neden:** Yetkinlik matrisinin operasyona etki etmesinin en ucuz yolu; seviye 1–2 teknisyenin tek başına X-Ray bakımına gönderilmesi görünür hale gelir.
- **Mevcut:** Atama uçları (P.cs:545-614, 649-761) yetkinliğe bakmaz; atamalar isim metni.
- **Kabul:** (1) `XR` seviyesi 2 olan teknisyen X-Ray PB işine atanınca yanıt `warnings` içerir, ekranda gösterilir, atama kaydedilir. (2) Belgesi geçerli ve seviyesi ≥ eşik olan kişide uyarı yoktur. (3) Uyarılı atamalar geçmişte "yetkinlik uyarısıyla atandı" notuyla görünür. (4) Eşleme tablosu boşsa hiçbir uyarı üretilmez (geriye uyumlu).
- **Roller:** Şef — `workorders.assign`; eşleme yönetimi `training.manage`.
- **Veri:** Yeni `WorkTypeCompetencyRequirements(UnitCode, WorkType, CompetencyId, MinLevel, RequiredCourseId NULL)`.
- **Efor:** M · **Bağımlılık:** M01-10 / M02-03 (kimlik bazlı atama), M08-03, M08-08.

### M08-05 · YENİ · Teknisyen için "Gelişim Kartım" ve gözlem onayı
- **Açıklama:** Personel kaydı `ErpUserId` ile bağlı kullanıcı, yalnız kendi kartını görür: planları, belgeleri ve geçerlilikleri, gözlemleri (madde puanlarıyla), yetkinlik geçmişi. Her gözlemde "Gördüm" onayı ve isteğe bağlı yorum.
- **Neden:** Gözlemin geliştirme aracı olması için kişinin geri bildirimi görmesi gerekir; bugün Teknisyen rolünde hiçbir eğitim izni yok (P.cs:3930). Onay kaydı itiraz/şeffaflık için kanıt olur.
- **Mevcut:** `Personnel.ErpUserId` var (DengeERP_Update.sql:362-366) ama eğitim modülünde kullanılmıyor.
- **Kabul:** (1) `training.self` sahibi `GET /api/training/me` ile yalnız kendi verisini alır; başka personel id'si ile istek 403. (2) Kartta gözlem madde puanları görünür. (3) "Gördüm" sonrası onay tarihi gözlem listesinde görünür; onay geri alınamaz. (4) ErpUserId bağlantısı olmayan kullanıcıya "personel kaydınız bağlı değil" mesajı döner.
- **Roller:** Teknisyen — yeni `training.self` (Teknisyen ve Şef rol varsayılanlarına eklenir; mevcut özel profiller otomatik değişmez).
- **Veri:** `TrainingObservations` ADD `AcknowledgedAt DATETIME2 NULL`, `EmployeeComment NVARCHAR(900) NULL`.
- **Efor:** S · **Bağımlılık:** —

### M08-06 · YENİ · Oturumda toplu katılım girişi
- **Açıklama:** Oturum ekranında, o kursun bu yıl planı olan personel listesi önerilir; tablo halinde katıldı/katılmadı, ön ve son puan tek seferde kaydedilir. Plana dahil olmayan kişi de eklenebilir.
- **Neden:** Bugün 15 kişilik eğitim 15 ayrı form gönderimi demek (app.js:1360); veri girişi aksar, plan tamamlama gecikir.
- **Mevcut:** `POST /api/training/attendance` tek kişi (P.cs:1612).
- **Kabul:** (1) 15 satırlık toplu kayıt tek istekte ve tek transaction'da yazılır; bir satır hatalıysa hiçbiri yazılmaz ve hatalı satır belirtilir. (2) Plan sahibi kişiler listede önceden gelir. (3) Mevcut tek kişilik uç çalışmaya devam eder.
- **Roller:** İK / Müdür — `training.manage`.
- **Veri:** Yok (mevcut tablo).
- **Efor:** S · **Bağımlılık:** M08-11 (tamamlama kuralı)

### M08-07 · YENİ · Eğitim etkinliği raporu ve Excel dışa aktarımı
- **Açıklama:** Kurs ve birim bazında: katılım, ön/son sınav ortalaması ve farkı, 0/30/60/90 gözlem başarı oranı ve ortalama puan eğrisi, kritik uygunsuzluk sayısı (açık/kapalı), 30/60/90 takip uyumu. Mevcut CSV'ye ek olarak çok sayfalı `.xlsx`: Plan, Katılım, Gözlemler (madde detayıyla), Yetkinlik Matrisi, Düzeltici Faaliyetler, Belgeler.
- **Neden:** Belgedeki ana soru: "Eğitim sonrasında teknisyenin sahadaki yetkinliği gelişti mi?" Bugün yalnız plan CSV'si var (P.cs:1712-1731).
- **Mevcut:** Gözlem/yetkinlik dışa aktarımı yok; ekranda kurs bazlı etkinlik görünümü yok.
- **Kabul:** (1) Bir kurs için 0. gün ortalaması 60, 90. gün ortalaması 85 olan örnek veride rapor "+25" gösterir. (2) Kritikli gözlemler başarı oranında başarısız sayılır. (3) Gözlemi olmayan aşama "veri yok" gösterilir, 0 gösterilmez. (4) Excel dosyası birim kapsamına göre süzülür; kapsam dışı personel satırı içermez. (5) Eğitim saati yalnız bilgi kolonu olarak bulunur.
- **Roller:** Müdür, İK, Genel Koordinatör — `training.export` (+ detay sayfaları için `training.view_detail`).
- **Veri:** Yok.
- **Efor:** M · **Bağımlılık:** M08-01, M08-08, M08-11, M08-17.

### M08-08 · VERİ · Yetkinlik değerlendirme geçmişi (üzerine yazma yerine yeni satır)
- **Açıklama:** Her değerlendirme `PersonnelCompetencyAssessments`'a yeni satır olarak eklenir (seviye, hedef, tarih, değerlendiren kullanıcı id, kanıt, kaynak: Gözlem/Sınav/Yönetici, ilgili gözlem id). `PersonnelCompetencies` "son durum" görünümü olarak kalır (geriye uyum). Mevcut satırlar ilk geçmiş kaydı olarak taşınır.
- **Neden:** Bugün MERGE ile önceki seviye ve kanıt siliniyor (P.cs:1655-1659); "gelişim" ölçülemiyor ve kim neyi değiştirdi denetlenemiyor. Tasarım gereği veri kaybı.
- **Mevcut:** `PersonnelCompetencies` kişi+yetkinlik tekil (V113.sql:104).
- **Kabul:** (1) Aynı kişi+yetkinlik için 2 → 3 değerlendirmesinden sonra geçmişte 2 satır, matriste son durum 3 görünür. (2) Göç scripti tekrar çalıştırılabilir ve mevcut satır sayısı kadar geçmiş kaydı oluşturur, çift oluşturmaz. (3) Kişi kartında yetkinlik zaman çizelgesi görünür. (4) `AssessedByUserId` dolu; isim metni yalnız gösterim için.
- **Roller:** Şef/Müdür — `training.observe` / `training.manage`.
- **Veri:** Yeni `PersonnelCompetencyAssessments(AssessmentId, PersonnelId, CompetencyId, CurrentLevel, TargetLevel, AssessedAt, AssessedByUserId, AssessedByName, Evidence, Source, ObservationId NULL, CreatedAt)`; idempotent göç.
- **Efor:** S · **Bağımlılık:** —

### M08-09 · EKSİK · Katalog, plan, oturum ve gözlem düzeltme / iptal
- **Açıklama:** Kurs düzenleme ve pasife alma; kriter ekleme ve pasife alma (puanlanmış kriter silinmez); plan hedef tarihini değiştirme, erteleme, iptal (gerekçe zorunlu); oturum düzeltme; gözlem iptali (gerekçeli, soft — raporlardan düşer, kayıt kalır). Tüm değişiklikler kim/ne zaman ile tutulur.
- **Neden:** Bugün yanlış girilen hiçbir kayıt düzeltilemiyor; kullanıcılar ya yanlış veriyle yaşayacak ya da SQL'e elle müdahale edecek.
- **Mevcut:** Yalnız POST uçları var (P.cs:1538-1710); `IsActive` alanı var ama ucu yok.
- **Kabul:** (1) Pasif kurs plan atama listesinde çıkmaz, geçmiş plan ve gözlemlerde görünür. (2) Puanlanmış kriter silinemez, pasife alınabilir; eski gözlemin puanı değişmez. (3) İptal edilen gözlem KPI ve raporlarda sayılmaz, kişi kartında "iptal — gerekçe" görünür. (4) Ertelenen plan durumu "Ertelendi", yeni hedef tarihle; geçmişte eski tarih görülebilir. (5) Gerekçesiz iptal 400 döner.
- **Roller:** İK/Müdür — `training.manage`; gözlem iptali gözlemci veya Müdür.
- **Veri:** `TrainingCriteria` ADD `IsActive`; `TrainingPlans` ADD `StatusReason`, `UpdatedByUserId`, `UpdatedAt`; `TrainingObservations` ADD `IsCancelled`, `CancelReason`, `CancelledByUserId`, `CancelledAt`; yeni `TrainingChangeLog(Entity, EntityId, Field, OldValue, NewValue, UserId, ChangedAt)`.
- **Efor:** M · **Bağımlılık:** —

### M08-10 · EKSİK · Yetkinlik kataloğu yönetimi ve kurs ↔ yetkinlik bağlantısı
- **Açıklama:** Yetkinlik ekleme/düzenleme/pasife alma ekranı; her kursa "geliştirdiği yetkinlik(ler)" bağlantısı. 90. gün gözlemi başarılı olunca kişinin ilgili yetkinliği için "yeniden değerlendir" görevi Şef'in listesine düşer (seviye otomatik artmaz).
- **Neden:** Yetkinlik kataloğu yalnız tohum verisiyle sabit (V113.sql:189-201); eğitim ile yetkinlik arasında bağ yok, matris eğitimden kopuk kalıyor.
- **Mevcut:** `CompetencyCatalog` için uç yok; kurs tablosunda yetkinlik alanı yok.
- **Kabul:** (1) Yeni yetkinlik ekranda eklenir ve matris formunda seçilebilir. (2) Kursa bağlı yetkinlik kurs kartında görünür. (3) 90. gün gözlemi "Başarılı" kaydedilince şefin "yeniden değerlendirilecek" listesinde 1 kayıt oluşur; değerlendirme yapılınca listeden düşer. (4) Seviye kendiliğinden değişmez.
- **Roller:** Müdür/İK — `training.manage`; Şef — `training.observe`.
- **Veri:** Yeni `TrainingCourseCompetencies(CourseId, CompetencyId)`; `CompetencyCatalog` ADD `IsActive`.
- **Efor:** M · **Bağımlılık:** M08-08.

### M08-11 · HATA · Plan tamamlama kuralları: sınav eşiği, ileri tarih, yıl uyumsuzluğu
- **Açıklama:** (a) Kursa sayısal sınav geçme puanı ve gözlem başarı eşiği alanı; eşik tanımlıysa son puan < eşik → plan "Başarısız-Tekrar", tamamlanmaz. (b) Gerçekleşen oturum tarihi bugünden ileri olamaz. (c) Katılım, aynı kişi+kurs için **en eski açık** planı yıldan bağımsız tamamlar (geç tamamlanan plan "Geç Tamamlandı" sayılır).
- **Neden:** Bugün son puanı 20 olan kişi "Tamamlandı" sayılıyor; ileri tarihli oturum planı bugünden kapatıyor; Ocak'ta yapılan geç eğitim önceki yılın planını hiç kapatmıyor. Gerçekleşme KPI'sı yanlış.
- **Mevcut:** P.cs:1601 (tarih kontrolü yok), P.cs:1638-1645 (katılım = tamamlandı, `PlanYear=YEAR(SessionDate)`), başarı ölçütü serbest metin (V113.sql:13).
- **Kabul:** (1) Eşik 70, son puan 60 → plan "Başarısız-Tekrar". (2) Eşik tanımsız kursta mevcut davranış korunur. (3) Yarın tarihli oturum isteği 400 döner. (4) 2026 planı Ocak 2027 oturumuyla tamamlanır ve raporda "geç" görünür. (5) Gözlem sonucu (Başarılı/Gelişim Gerekli/Kritik) sunucuda eşikle hesaplanıp kaydedilir.
- **Roller:** İK/Müdür — `training.manage`.
- **Veri:** `TrainingCourses` ADD `ExamPassScore INT NULL`, `ObservationPassPct DECIMAL(5,2) NULL`; `TrainingObservations` ADD `Result NVARCHAR(30)`.
- **Efor:** S · **Bağımlılık:** —

### M08-12 · EKSİK · 30/60/90 takibinin sunucuya alınması ve uyarı
- **Açıklama:** Takip listesi sunucuda hesaplanır (`GET /api/training/followups`); zamanı gelen ve geciken takipler Ops uyarılarına düşer, şef bazında süzülür. Takip, eğitimi tamamlamış kişiler için oluşur; gözlem iptal edilirse takip yeniden açılır.
- **Neden:** Bugün liste yalnız tarayıcıda, eğitim ekranı açılınca görünür (app.js:1293-1305); şef hatırlatma almıyor, 30/60/90 disiplini kişiye kalıyor.
- **Mevcut:** Ops.cs:50-63 yalnız plan vadesi uyarısı.
- **Kabul:** (1) 01.09'da tamamlanan eğitim için 01.10'da 30. gün takibi uyarıda görünür. (2) Gözlem girilince takip listeden ve uyarıdan düşer. (3) Uç ve ekran aynı sayıyı verir. (4) Başka birimin personeli uyarıda görünmez.
- **Roller:** Şef — `training.observe`; Müdür — `training.view`.
- **Veri:** Yok (hesaplanan görünüm).
- **Efor:** S · **Bağımlılık:** M08-09 (iptal), M08-11.

### M08-13 · HATA · Yönetim özetinde kritik uygunsuzluğun ortalamada kaybolması ve kritik maddenin atlanabilmesi
- **Açıklama:** "Saha Gözlem Uygunluğu" KPI'sı ortalama yerine **başarı oranı** (eşik üstü ve kritik yok) olur; ortalama ikincil bilgi. Kritik maddeler "Gözlenmedi" bırakılırsa gerekçe zorunlu ve sonuç "Eksik Gözlem". Kritik sayısı ayrı kutuda.
- **Neden:** Belge §5.8 kuralının doğrudan ihlali: 10 maddeden 9'u 2, kritik 1 madde 0 olan gözlem %90 puanla ortalamayı yükseltiyor (app.js:1310, 1318). Kritik madde -1 seçilerek geçilebiliyor (app.js:1363, P.cs:1673).
- **Mevcut:** Yukarıdaki satırlar.
- **Kabul:** (1) Örnek: 3 gözlem (%95, %90-kritik, %70) → başarı oranı 1/3, kritik kutusu 1. (2) Kritik madde -1 ve gerekçesiz gönderim 400 döner. (3) Kritikli gözlem rozetinde puan değil "KRİTİK" öne çıkar.
- **Roller:** —
- **Veri:** `TrainingObservationRatings` ADD `NotObservedReason NVARCHAR(300) NULL`.
- **Efor:** S · **Bağımlılık:** M08-11 (eşik), M08-01.

### M08-14 · HATA · Oturum oluşturmada birim yetkisi kontrolü eksik
- **Açıklama:** `POST /api/training/sessions` kursun `UnitCode`'una `UnitAllowed` kontrolü uygular (diğer uçlarla aynı).
- **Neden:** Birim kısıtlı bir `training.manage` sahibi başka birimin kursuna oturum açabiliyor; o birimin raporlarını etkiler.
- **Mevcut:** P.cs:1598-1610 (kontrol yok); karşılaştırma P.cs:1577-1580.
- **Kabul:** (1) Yalnız "Haberleşme" yetkili kullanıcının "Güvenlik Sistemleri" kursuna oturum isteği 403 döner. (2) Birimsiz (tüm birimler) kurs için istek kabul edilir.
- **Roller:** `training.manage`.
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** —

### M08-15 · VERİ · Gözlemci/değerlendiren kimliği ve öz-değerlendirme engeli
- **Açıklama:** `ObserverUserId`, `AssessedByUserId` kaydedilir (isim metni yalnız gösterim). Gözlemcinin bağlı personel kaydı gözlenen kişiyse istek reddedilir.
- **Neden:** Bugün gözlemci ve değerlendiren ad-soyad metni (P.cs:1662, 1696); ad değişince veya aynı ad iki kişide olunca raporlar bozulur. Şef kendi gözlemini/yetkinliğini girebilir.
- **Mevcut:** `ObserverName`, `AssessedBy` NVARCHAR (V113.sql:100, 116).
- **Kabul:** (1) Yeni gözlemde `ObserverUserId` dolu. (2) Gözlemci = gözlenen personel ise 400 "Kendi gözleminizi giremezsiniz". (3) Eski kayıtlar bozulmadan görüntülenir.
- **Roller:** `training.observe`.
- **Veri:** `TrainingObservations` ADD `ObserverUserId` (M08-02 ile ortak), `PersonnelCompetencies` / geçmiş tablosunda `AssessedByUserId`.
- **Efor:** S · **Bağımlılık:** M08-02, M08-08.

### M08-16 · EKSİK · Overview yükünün küçültülmesi
- **Açıklama:** `GET /api/training/overview` sekme bazlı uçlara bölünür (özet sayılar sunucuda; gözlem/katılım listeleri sayfalı). Gözlemler yalnız seçili yıl için döner.
- **Neden:** Tüm yılların gözlemleri, katılımları ve yetkinlikleri her sekme açılışında tarayıcıya gidiyor (P.cs:1503-1535); personel ve yıl arttıkça yavaşlar, ayrıca gereksiz kişisel veri tarayıcıya taşınır (M08-17).
- **Mevcut:** Tek uç, sayfalama yok.
- **Kabul:** (1) Yönetim Özeti sekmesi yalnız sayıları ve takip listesini alır. (2) Gözlem listesi 50'lik sayfalarla gelir. (3) KPI değerleri eski hesapla (M08-13 düzeltmesi sonrası) aynı çıkar.
- **Roller:** —
- **Veri:** Yok.
- **Efor:** M · **Bağımlılık:** M08-17 ile birlikte yapılmalı.

### M08-17 · GÜVENLİK · Kişisel performans verisine erişimin ayrıştırılması (KVKK)
- **Açıklama:** Yeni izin `training.view_detail`: gözlem notları, madde puanları, aksiyon planı, yetkinlik kanıtları yalnız bu izinle döner. `training.view` yalnız özet/plan/katılım görür. Şef detayları yalnız kendi biriminde görür (mevcut birim kapsamı). Teknisyen yalnız `training.self` ile kendi verisini görür (M08-05). Dışa aktarımın detay sayfaları da aynı izne bağlı.
- **Neden:** Bugün `training.view` sahibi (ör. Genel Koordinatör varsayılanı, P.cs:3927) kapsamındaki tüm personelin değerlendirme notlarını görüyor; bu, KVKK açısından "gerekli olan kadar" ilkesine aykırı. Sistem dışına sızıntı değil, bu yüzden KRİTİK değil.
- **Mevcut:** P.cs:1489, 1530-1534 tek izin, tüm alanlar.
- **Kabul:** (1) Yalnız `training.view` sahibi kullanıcının API yanıtında `notes`, `actionPlan`, `evidence` alanları **bulunmaz** (yalnız ekranda gizlemek yeterli değil). (2) `training.view_detail` verilince alanlar gelir. (3) Rol varsayılanları: Müdür/Yrd, İK, Şef → view_detail; Genel Koordinatör → yok (kullanıcı onayı, §4). (4) Mevcut özel profiller otomatik değişmez.
- **Roller:** Tüm eğitim izinleri.
- **Veri:** Yok (izin kataloğu P.cs:3890-3893'e ekleme).
- **Efor:** S · **Bağımlılık:** M08-16.

---

## 4. Kullanıcıya sorulacaklar (benim karar veremeyeceğim konular)

1. **Kritik İSG uygunsuzluğunda işlem:** Kritik uygunsuzluk açıkken teknisyen sahaya tek başına gönderilmeye devam edebilir mi (yalnız uyarı), yoksa ilgili iş türüne atama **engellensin** mi? Düzeltici faaliyet için varsayılan termin kaç gün olsun (önerim 14)?
2. **Kritik uygunsuzluğu kim kapatır?** Şirkette İSG uzmanı / İSG sorumlusu rolü var mı, sistem kullanıcısı olacak mı? Yoksa kapanışı Teknik Servis Müdürü mü onaylasın?
3. **Zorunlu belgeler listesi:** Hangi eğitim/belgeler geçerlilik süresiyle takip edilmeli (İSG temel eğitimi, yüksekte çalışma, elektrik, X-Ray radyasyon güvenliği, araç kullanımı vb.) ve yenileme periyotları nedir? Bu liste olmadan M08-03 boş kalır.
4. **Sınav ve gözlem eşikleri:** Katalogdaki "%85 uygunluk" ve "%90" ifadeleri resmi eşik mi? Sınavda geçme puanı hangi kurslarda olacak?
5. **Teknisyenin kendi kartını görmesi:** Teknisyen gözlem notlarını ve puanlarını görebilsin mi (önerim: evet + "Gördüm" onayı)? İtiraz akışı gerekli mi?
6. **Genel Koordinatör ve Üst Yönetim:** Kişi bazlı gözlem notlarını görmeli mi, yoksa yalnız özet mi?
7. **Gözlemci kim olabilir?** Yalnız şef mi, yoksa kıdemli teknisyen (yetkinlik seviyesi 4 "Uzman/Eğitici") de gözlem yapabilsin mi?
8. **Atamada yetkinlik uyarısı (M08-04):** Hangi iş türleri için hangi minimum yetkinlik seviyesi aranmalı? (Örn. X-Ray PB → XR ≥ 3; seviye 2 ise yanında seviye ≥ 3 biri olmalı.)
9. **Eğitimin operasyonel etkisi:** İleride teknisyen bazında "eğitim öncesi/sonrası 90 gün tekrar arıza oranı / ilk seferde çözüm" görmek ister misiniz? Bu, iş emri atamalarının kişi kimliğine bağlanmasından (M01-10) sonra yapılabilir; şimdilik listeye almadım.
10. **Mevcut test verisi:** Pilot veritabanında gerçek eğitim/gözlem kaydı girildi mi? (Göç scriptleri ve M08-08 taşıması buna göre test edilecek.)

---

## 5. Varsayımlar

- Roller ve izin dağılımı organizasyon şeması gelmeden **varsayım** olarak önerildi; `Catalog.RoleDefaults` (P.cs:3921-3935) yalnız şablondur, kişi bazında izin değiştirilebilir.
- Personel ↔ kullanıcı bağlantısı `Personnel.ErpUserId` üzerinden kurulacak; bağlantısı olmayan personel self-servis ve öz-değerlendirme kontrolünden yararlanamaz.
- Eğitim modülü bordro, ücret, performans primi veya disiplin süreci değildir; bu verilerle ilişkilendirilmez.
- Eğitim saati başarı ölçütü olarak kullanılmaz; yalnız bilgi.
- Gözlem/sınav verisi olmayan aşamalar raporda "veri yok/eksik" gösterilir, 0 gösterilmez.
- Tüm SQL değişiklikleri mevcut V113 yaklaşımıyla **idempotent ek** (kolon/tablo ekleme) olarak yapılır; mevcut tablolar silinmez, yeniden yazım yapılmaz.
- Otomatik e-posta/SMS kapsam dışı; uyarılar ERP içi (Ops uyarıları) üzerinden.
- Yasal İSG mevzuat uyumu (eğitim süreleri, belge zorunlulukları) bu belgede hukuki olarak değerlendirilmedi; liste kullanıcıdan/İSG uzmanından gelecek.
