# M10 — Operasyon Merkezi, SLA, Bekleme Nedenleri ve Uyarılar — Gereksinim Tasarımı

> **Tarih:** 21 Ekim 2026 · **Kaynak sürüm:** V1.20.1 (salt okunur inceleme, kaynak koda dokunulmadı)
> **Kapsam:** Sadece teknik servis. Logo CRM / Flowick entegrasyonu kapsam dışı.
> **Öncelik sırası (kullanıcı kararı):** (c) yeni özellik → (b) mevcut eksikler → (a) güvenlik/üretime hazırlık. Veri kaybı/sızıntısı yaratan açıklar ayrıca "KRİTİK" diye işaretlenir (bu modülde KRİTİK seviyede açık bulunmadı).
> **Kısaltmalar:** `P.cs` = `DengeERP.Api/Program.cs`, `Ops.cs` = `OpsSuite.cs`, `ops.js` = `wwwroot/ops120.js`, `app.js` = `wwwroot/app.js`, `v120.sql` = `Database/ZZ_V120_Operations.sql`.
> **İlgili modüller:** M01 İş Emirleri (durum yaşam döngüsü, bekleme geçmişi M01-14), M04 Planlı Bakım, Saha/Zaman Takibi, Raporlama. Çakışan maddeler burada tekrar edilmedi; bağımlılık olarak gösterildi.

---

## 1. Mevcut durum (kodda ne var?)

### 1.1 API uçları (tamamı `Ops.cs`, kayıt: P.cs:2778-2779)

| Uç | Yer | Ne yapıyor | İzin |
|---|---|---|---|
| `GET /api/ops/overview?days=` | Ops.cs:76-110 | **Tüm** iş emirlerini ve **tüm** süre kayıtlarını yükler (P.cs:3424-3502), son `days` (1–366, vars. 30) gün açılan + açık işleri seçer (Ops.cs:83). Sayaçlar, iş listesi (≤1500), personel iş yükü, tekrar arıza, uyarılar, SLA tablosu döner. | yalnız `dashboard.view` |
| `POST /api/ops/alerts/ack` | Ops.cs:111-121 | Uyarıyı kullanıcı bazında "görüldü" yapar. Doğrulama için tüm uyarıları yeniden hesaplar. | `dashboard.view` |
| `PUT /api/ops/sla/{priority}` | Ops.cs:122-129 | Öncelik için çözüm saati (1–8760). Kim/ne zaman değiştirdi **kaydı yok**. | `operations.manage` |
| `POST /api/ops/workorders/{id}/hold` | Ops.cs:130-145 | `OpsHolds` kaydı + iş durumunu `Beklemede` yapar. Neden serbest metin ≤100. `WorkOrderStatusLogs`'a yazmaz. | `operations.manage` **veya** `workorders.edit` |
| `POST /api/ops/workorders/{id}/release` | Ops.cs:146-159 | Aktif beklemeyi kapatır, durum `Beklemede` ise önceki duruma döndürür. | aynı |
| `GET /api/ops/export.csv` | Ops.cs:259-265 | İş emri listesi CSV (8 kolon; SLA/bekleme/gecikme kolonu yok). CSV enjeksiyonu önlemi var (Ops.cs:66-70). | `reports.export` |
| (stok / finans uçları) | Ops.cs:160-258 | Yedek parça ve maliyet modülüne aittir; burada yalnız "düşük stok uyarısı" kaynağı olarak dikkate alındı. | — |

### 1.2 Tablolar (v120.sql)

- `OpsSlaTargets(Priority PK, ResolutionHours)` (v120.sql:2-6): tohum Kritik 12 / Yüksek 24 / Normal 72 / Düşük 120 saat. **Yalnız çözüm hedefi**; müdahale (ilk yanıt) hedefi, birim/iş türü/müşteri kırılımı, mesai takvimi yok.
- `OpsHolds(HoldId, WorkOrderId, Reason, Notes, PreviousStatus, CreatedBy, CreatedAt, ReleasedAt)` (v120.sql:8-12) + **iş başına tek aktif bekleme** filtreli benzersiz indeksi `UX_OpsHolds_Open`. Neden kataloğu, beklenen bitiş tarihi, kapatan kullanıcı yok.
- `OpsAlertAcks(AlertKey, UserId, AckAt)` (v120.sql:14-15): yalnız "görüldü" kaydı. Uyarının kendisi **tabloda tutulmaz**, her istekte yeniden hesaplanır. Temizleme yok (sürekli büyür).
- `WorkOrders` üzerinde SLA'ya dair kolon **yok** (hedef tarih, ilk müdahale, çözüm zamanı, durdurulan süre). `ClosedAt` yalnız `Kapatıldı`'da dolar (P.cs:527); `Tamamlandı` olan işin çözüm zamanı tutulmaz.

### 1.3 Ön yüz

- Menü: `dashboard.view` olan herkese "Operasyon Merkezi" (app.js:182); "Mobil İşler" (app.js:183).
- Ekran `ops.js:23-49`: 8 tıklanabilir sayaç (Açık, Geciken, Bugün/Yarın Planlı, Günlük Servis, Planlı Bakım, Bekleme, Kapanan — ops.js:27), 5 sekme (İş Listesi, Uyarılar, Personel İş Yükü, Tekrar Arıza, SLA Hedefleri — ops.js:28). Arama yalnız no/müşteri/lokasyon/şehir/personel (ops.js:32).
- `ops120.days=30` sabit (ops.js:2); dönem seçimi için **arayüz yok**.
- Bekletme: `prompt()` ile serbest metin, öneri "Malzeme / Müşteri Onayı / Teklif / Personel / Diğer" (ops.js:72-76).
- SLA sekmesi uyarı metni: "takvim saatidir; mesai takvimi uygulanmaz" (ops.js:47); düzenleme `prompt()` (ops.js:71).
- Uyarılar yalnız bu sayfa açıkken görünür; 3 dakikada bir yenilenir (ops.js:102). **Üst menüde/başka sayfada rozet yok** (app.js'te `alerts` geçmiyor).
- Mobil İşler teknisyen filtresi istemci tarafında ad-soyad eşleşmesiyle (ops.js:7); sunucu da aynı mantığı uygular (P.cs:3499-3500).
- Genel durum listesi (app.js:30) `Beklemede`'yi içerir → iş detayından nedensiz `Beklemede` seçilebilir. Yeni iş formunda öncelik yalnız Normal/Yüksek/Kritik (app.js:297); `Düşük` yok ama SLA tablosunda var.

### 1.4 İş kuralları (mevcut)

- **Açık iş:** durum `Kapatıldı/Tamamlandı/İptal` dışı (Ops.cs:8). `P.cs:2808 IsClosingStatus` ise `Çözüldü`'yü de kapanış sayar → iki tanım farklı.
- **Bakım ayrımı:** no `PB-` ile başlar veya tür `Planlı Bakım` (Ops.cs:9).
- **Geciken:** açık ve `şimdi > CreatedAt + SLA(Priority)`; bilinmeyen öncelik için 72 saat (Ops.cs:31, 87). Bekleme süresi düşülmez; hedef işe damgalanmaz → SLA değişince geçmiş/açık tüm işlerin gecikme durumu geriye dönük değişir.
- **Uyarı üretimi** (Ops.cs:26-65): geciken (Kritik), yarın planlı (Bilgi), beklemede (Uyarı), düşük stok (`warehouse.view`), 7 gün içinde eğitim (`training.view`, birim filtreli). Uyarı anahtarı **günlük** (`…:yyyyMMdd`) → "Görüldü" ertesi gün sıfırlanır. En fazla 100 uyarı.
- **Tekrar arıza** (Ops.cs:93-96): bakım dışı işlerde, seçili dönem + açık işler içinde aynı seri numarası (büyük/küçük harf duyarsız) birden fazla işte geçiyorsa listelenir. Zaman penceresi kuralı (ör. "kapanıştan sonra 30 gün"), müşteri/lokasyon, kök neden, iş emrinde işaret **yok**.
- **Personel iş yükü** (Ops.cs:89-92): `AssignedStaff` isim metni ile atama sayısı (toplam/açık/kapalı). Süre/plan/canlı durum yok.
- **Zaman:** sunucu `DateTime.Now` ile SQL `SYSDATETIME()` (CreatedAt) karşılaştırılır; Linux kurulum dosyalarında saat dilimi ayarı yok (`linux/` altında `TZ`/`timedatectl` geçmiyor).
- **E-posta altyapısı:** yalnız teklif gönderiminde SMTP var (P.cs:906-931, `Email:*` ayarları). Kullanıcı/personel tablolarında e-posta alanı yok (`Database/DengeERP_Update.sql:143-157, 350-367`).

### 1.5 Tespit edilen hatalar / tutarsızlıklar (kanıtlı)

1. **Planlı bakım işleri sahte "Geciken":** PB işleri `Priority=N'Normal'` ile toplu üretiliyor (P.cs:3086) ve hedef tarihi gelecekteki bir ay olabiliyor (`MaintenancePlans.TargetDate`, V15_Schema.sql:62; açıklama P.cs:3090). Ops.cs:87 bunlara da `CreatedAt+72 sa` uyguluyor → üretimden 3 gün sonra her PB işi "Geciken" sayılır ve her gün "Kritik" uyarı üretir. AKYAKA örneğinde 17 iş birden.
2. **Bekleme ↔ durum kopukluğu:** (a) İş `PATCH status`, bakım formu veya atölye üzerinden kapatılınca `OpsHolds` açık kalır; `counters.hold` kapalı işleri de sayar (Ops.cs:105). (b) Bakım formu (P.cs:2512), atölye (P.cs:2750) ve genel durum listesi (app.js:30) `Beklemede`'yi **neden kaydı olmadan** set eder → bu işler "Bekleme" sayacında yoktur, nedeni bilinmez. (c) Aktif beklemesi olan işe ikinci bekleme → benzersiz indeks ihlali → 409 yerine **500**.
3. **SLA ölçümü yalnız açık işler için:** kapanan işin hedefi tutturup tutturmadığı hiçbir yerde hesaplanmıyor; `Tamamlandı`'da `ClosedAt` yok (P.cs:527). Dolayısıyla "SLA uyum oranı" bugün üretilemez.
4. **Öncelik doğrulanmıyor:** `POST /api/workorders` önceliği serbest metin olarak kaydeder (P.cs:409); listede olmayan değer sessizce 72 saat alır.
5. **Yetki:** `/api/ops/overview` yalnız `dashboard.view` ister; `İnsan Kaynakları` (P.cs:3934) ve `Depo` rollerinin bu izni var → `workorders.view` olmadan da tüm iş listesini (müşteri, lokasyon, konu, atanan personel) görebilir (`AllowedUnits` boşsa tüm birimler).

---

## 2. Olması gereken (Denge Elektronik teknik servis çalışma sistemi)

### 2.1 Roller (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol | Bu modülde yaptığı | İzinler |
|---|---|---|
| Operasyon Uzmanı | Gün içinde açık/atanmamış/geciken işleri izler, müşteriyi arar, müşteri kaynaklı beklemeyi (onay, erişim) girer ve kapatır. | `operations.view` (yeni), `workorders.edit` |
| Şef (birim) | Kendi biriminin SLA riskini ve beklemelerini yönetir, uyarıları alır, gecikme açıklaması girer, tekrar arızada kök nedeni onaylar. | `operations.view`, `workorders.edit/assign/plan/close` |
| Teknisyen | Kendi işinde bekleme nedeni girer (malzeme, müşteri yok vb.); kendi işlerinin SLA kalan süresini mobilde görür. Operasyon merkezini görmez. | `workorders.edit` (yalnız kendi işi) |
| Teknik Servis Müdürü / Yrd. | SLA hedeflerini, mesai takvimini, bekleme nedeni kataloğunu yönetir; SLA ve tekrar arıza KPI'larını izler; SLA aşım uyarısının ikinci kademesi. | `operations.manage`, `reports.view/export` |
| Üst Yönetim / Genel Koordinatör | Aylık SLA uyum, tekrar arıza ve bekleme raporlarını görür. | `operations.view`, `reports.view` |
| İK, Depo, Muhasebe | Operasyon iş listesini **görmez**; Depo yalnız düşük stok uyarısını alır. | — |

### 2.2 Tutulacak veriler

- **İş emri SLA alanları:** `SlaPolicyId`, `SlaStartAt` (kayıt veya müşteri bildirim saati — M01-05 `ReportedAt`), `ResponseDueAt`, `ResolveDueAt`, `FirstResponseAt` (ilk "Yola çıktım/Sahadayım/Uzaktan destek" sayacı veya telefonla çözüm), `ResolvedAt` (ilk `Tamamlandı`), `PausedMinutes`, `SlaResult` (Karşılandı / Aşıldı / Ölçülemedi), `DelayReason` (aşımda zorunlu kısa açıklama).
- **SLA politikası:** birim + iş kategorisi (Günlük Servis / Atölye / Kurulum) + öncelik → müdahale saati, çözüm saati, takvim türü (7/24 veya mesai). Planlı bakım SLA dışıdır; kendi hedefi `MaintenancePlans.TargetDate`'tir.
- **Mesai takvimi ve tatiller:** hafta günü başlangıç/bitiş saatleri, resmi tatil/arife günleri tablosu.
- **Bekleme nedeni kataloğu:** kod, ad, `SlaDurdurur` (evet/hayır), not zorunlu mu, beklenen bitiş tarihi zorunlu mu, aktif.
- **Bekleme kaydı:** neden kodu, not, beklenen bitiş tarihi, açan/kapatan, açılış/kapanış saati, süre.
- **Tekrar arıza:** `RepeatOfWorkOrderId`, `IsRepeat`, kapanışta `RepeatConfirmed` (Aynı arıza / Farklı arıza / Kullanıcı hatası).
- **Bildirim:** tür, önem, hedef (kullanıcı / birim şefi / müdür), ilgili iş, oluşma–görülme–kapanma zamanı, e-posta gönderim durumu.

### 2.3 SLA durum akışı (iş bazında)

```text
Kayıt açıldı ──► Zamanında ──(%80 süre doldu)──► Risk ──(süre doldu)──► Aşıldı
      │               │                              │
      │      SLA durduran bekleme ◄──────────────────┘ (süre işlemez, "Durduruldu")
      │               │
      └──► Tamamlandı: ResolvedAt ≤ ResolveDueAt ? "Karşılandı" : "Aşıldı (gecikme nedeni zorunlu)"
Veri eksik (ör. geçmiş iş, tarih yok) ──► "Ölçülemedi" (0 veya "Karşılandı" sayılmaz)
Planlı bakım ──► SLA dışı; "Vadesi geçti" = hedef dönem sonu geçti ve kapanmadı
```

### 2.4 Operasyon merkezi ekranı (hedef)

Sayaçlar (her biri tıklanınca aynı sayıda kayıt listeler): Açık servis · **Atanmamış** · Plansız · Bugün planlı · Sahada şu an · **SLA riskte** · **SLA aşıldı** · Beklemede (nedene göre) · **Bekleme süresi aşıldı** · Vadesi geçen planlı bakım · Bugün kapanan · Tekrar arıza (açık).
İş listesi: SLA kalan süre sütunu ve ona göre sıralama, birim/şef/öncelik/kategori filtresi, bekleme nedeni ve süresi.
Personel: kim şu an hangi işte (aktif sayaç), bugün/yarın planlı iş sayısı, açık geciken iş sayısı.

### 2.5 KPI / raporlar

- SLA uyum oranı (müdahale ve çözüm ayrı) — birim, öncelik, müşteri, şef, ay kırılımı; "Ölçülemedi" sayısı ayrıca.
- Ortalama / medyan net çözüm süresi (durdurulan süre düşülmüş).
- Bekleme: nedene göre adet ve toplam süre, ortalama bekleme süresi, en uzun bekleyen işler.
- Tekrar arıza oranı (30 gün) — teknisyen, müşteri, marka/model, sistem kırılımı.
- Planlı bakım vade uyumu (dönem içinde kapanan / üretilen).
- Kural: **süre kaydı olmayan iş "eksik" gösterilir, 0 sayılmaz; tahmini süre gerçek süre yerine kullanılmaz.**

### 2.6 Doğrulamalar

- Öncelik ve bekleme nedeni yalnız katalogdan.
- `Beklemede` durumuna yalnız bekleme ucuyla girilir; iş kapanınca/iptal edilince aktif bekleme otomatik kapanır.
- SLA hedefi işe açılışta damgalanır; politika değişikliği geçmiş işleri değiştirmez. Öncelik değişirse hedef yeniden hesaplanır ve geçmişe yazılır.
- SLA aşımıyla kapanan işte gecikme nedeni zorunlu.
- Tüm SLA/takvim/katalog değişiklikleri kim-ne zaman-eski-yeni ile kaydedilir.
- Tüm zamanlar tek saat diliminde (Europe/Istanbul) ya da UTC olarak tutulup tek yerde dönüştürülür.

---

## 3. Fark analizi ve maddeler

> Sıra kullanıcı önceliğine göredir: önce YENİ, sonra EKSİK/HATA, en son GÜVENLİK/VERİ. Efor: S ≤ 2 gün, M ≈ 3–6 gün, L > 1 hafta (tek geliştirici).

### M10-01 · YENİ · SLA politikası v2: müdahale + çözüm hedefi, işe damgalanan hedef tarih
- **Açıklama:** `OpsSlaTargets` yerine/yanına birim + kategori + öncelik bazlı politika (müdahale saati, çözüm saati, takvim türü). İş açılışında `ResponseDueAt`/`ResolveDueAt` hesaplanıp işe yazılır. `FirstResponseAt` canlı sayacın ilk yol/saha/uzaktan destek başlangıcından veya telefonla çözüm kaydından; `ResolvedAt` ilk `Tamamlandı`/`Kapatıldı` geçişinden otomatik dolar. Kapanışta `SlaResult` hesaplanır; aşımda gecikme nedeni zorunlu. Öncelik değişince hedef yeniden hesaplanır ve geçmişe yazılır. SLA hedef değişiklikleri denetim kaydına yazılır.
- **Neden:** Bugün yalnız "şu an gecikmiş mi" var (Ops.cs:87); "geçen ay Kritik işlerin yüzde kaçı zamanında çözüldü" sorusu cevaplanamıyor. Hedef damgalanmadığı için SLA saati değişince tüm geçmiş geriye dönük değişiyor.
- **Mevcut:** Ops.cs:13-19, 31, 87, 122-129; v120.sql:2-6; P.cs:527 (`ClosedAt` yalnız Kapatıldı).
- **Kabul:** (1) Yeni Kritik iş açıldığında `ResolveDueAt = SlaStartAt + 12 sa` (7/24 politikada) DB'de görünür. (2) SLA saati 12→8 yapılınca önceden açılmış işin `ResolveDueAt` değeri değişmez. (3) İşte ilk "Yola çıktım" sayacı başlayınca `FirstResponseAt` dolar, ikinci sayaç değiştirmez. (4) Hedef geçtikten sonra `Tamamlandı` yapılmak istenirse gecikme nedeni boşsa 400 döner. (5) Öncelik Normal→Kritik değişince hedef yeniden hesaplanır ve iş geçmişinde eski/yeni hedef görünür. (6) `PUT /api/ops/sla/...` sonrası denetim kaydında kullanıcı, eski ve yeni değer var.
- **Roller/izin:** Politika yönetimi `operations.manage` (Müdür/Yrd.); görüntüleme `operations.view`.
- **Veri değişikliği:** `OpsSlaPolicies(PolicyId, UnitCode NULL, Category NULL, Priority, ResponseHours, ResolveHours, CalendarType, IsActive)`; `WorkOrders` + `SlaPolicyId, SlaStartAt, ResponseDueAt, ResolveDueAt, FirstResponseAt, ResolvedAt, PausedMinutes, SlaResult, DelayReason`; `OpsConfigAudit`.
- **Efor:** M · **Bağımlılık:** M01-09 (durum yaşam döngüsü), M01-05 (`ReportedAt`, isteğe bağlı).

### M10-02 · YENİ · Mesai takvimi ve resmi tatiller (iş saati bazlı SLA)
- **Açıklama:** Politikada `CalendarType = 7/24 | Mesai`. Mesai takvimi (hafta günleri, başlangıç-bitiş saatleri) ve tatil tablosu; SLA hedef hesaplaması ve kalan süre bu takvime göre yapılır. Tek ortak takvim yeterli; birime özel takvim yalnız gerekirse.
- **Neden:** Cuma 17:00'de açılan Normal iş takvim saatiyle Pazartesi sabah "gecikmiş" görünür; yönetici gecikme listesine güvenmez. Belge §5.10 ve §14 bunu açık iş olarak not ediyor; ops.js:47 bunu ekranda uyarı olarak yazıyor.
- **Mevcut:** Yok (ops.js:47 yalnız uyarı metni).
- **Kabul:** (1) Mesai 08:30–17:30 Pzt–Cum iken Cuma 16:30'da açılan 8 saatlik işin hedefi Pazartesi 16:30 olur. (2) 29 Ekim tatil tanımlıysa o gün sayılmaz. (3) 7/24 politikadaki Kritik iş takvimden etkilenmez. (4) Tatil ekleme/silme denetim kaydına yazılır. (5) Birim testleri: yılbaşı, hafta sonu, mesai dışı açılış, tatil arası 5 senaryo.
- **Roller/izin:** `operations.manage`.
- **Veri değişikliği:** `OpsWorkCalendar(DayOfWeek, StartTime, EndTime)`, `OpsHolidays(Date, Name, IsHalfDay)`.
- **Efor:** M · **Bağımlılık:** M10-01.

### M10-03 · YENİ · Bekleme nedeni kataloğu, SLA durdurma ve beklenen bitiş tarihi
- **Açıklama:** Bekleme nedenleri katalogdan seçilir (öneri: Malzeme/Yedek Parça · Müşteri Onayı · Teklif Onayı · Müşteri Erişimi/Saha Hazır Değil · Üretici/Garanti Dönüşü · Personel/Araç · Diğer). Her nedenin `SlaDurdurur` bayrağı vardır (öneri: müşteri kaynaklılar durdurur, iç kaynaklılar durdurmaz). Bekletmede "beklenen bitiş tarihi" ve not girilir (Diğer'de not zorunlu). SLA durduran beklemedeki süre `PausedMinutes`'a eklenir ve hedef tarih o kadar ileri kayar. `prompt()` yerine seçim listeli form.
- **Neden:** Bugün neden serbest metin (Ops.cs:134, ops.js:73) → raporda gruplanamaz; müşteri onayı beklenen iş teknisyene "gecikme" olarak yazılıyor; ne zaman tekrar bakılacağı belli değil.
- **Mevcut:** Ops.cs:130-159; v120.sql:8-12; ops.js:72-77.
- **Kabul:** (1) Katalog dışı neden kodu → 400. (2) "Müşteri Onayı" ile 5 saat beklemede kalan Normal işin `ResolveDueAt` değeri 5 saat (mesai takvimine göre) ileri kayar; "Malzeme" ile kaymaz. (3) Beklenen bitiş tarihi geçmiş tarih olamaz; geçince M10-05'te "Bekleme süresi aşıldı" uyarısı oluşur. (4) Bekleme kapanınca süre dakika olarak kayıtta görünür. (5) Katalogda pasife alınan neden yeni beklemede seçilemez, eski kayıtlar bozulmaz.
- **Roller/izin:** Bekletme/çözme `workorders.edit` (teknisyen yalnız kendi işi) veya `operations.manage`; katalog yönetimi `operations.manage`.
- **Veri değişikliği:** `OpsHoldReasons(Code PK, Name, PausesSla, NoteRequired, IsActive, SortOrder)`; `OpsHolds` + `ReasonCode, ExpectedEndDate, ReleasedBy, PausedMinutes`. Eski `Reason` metni korunur, eşlenemeyen eski kayıtlar `DIGER` koduna bağlanır.
- **Efor:** M · **Bağımlılık:** M01-14 (bekleme geçmişi ve `PATCH status` ile Beklemede engeli), M10-01.

### M10-04 · YENİ · Tekrar arıza kuralı, iş emrinde işaret ve kök neden onayı
- **Açıklama:** Kural: bakım dışı yeni iş açılırken aynı (normalize edilmiş) seri numarası için son **N gün** (vars. 30, ayarlanabilir) içinde kapanmış bir servis işi varsa yeni iş `IsRepeat=1`, `RepeatOfWorkOrderId` ile işaretlenir; açılış formunda "Bu cihaza 12 gün önce SRV-… ile müdahale edildi (Teknisyen X)" uyarısı çıkar. Seri no yoksa aynı müşteri + lokasyon + sistem için yalnız **bilgi uyarısı** verilir, işaretlenmez. Kapanışta şef "Aynı arıza / Farklı arıza / Kullanıcı hatası" seçer; KPI yalnız "Aynı arıza" olanları sayar. Operasyon merkezinde tekrar arıza sekmesi bu işaretten beslenir, müşteri ve önceki işin teknisyeni görünür.
- **Neden:** Belge §1: "aynı arıza tekrarlandı mı?" ana sorulardan. Bugünkü liste (Ops.cs:93-96) zaman kuralı olmadan aynı seri numarasını sayıyor; aynı gün açılmış iki iş ile 11 ay arayla açılmış iki işi ayırt etmiyor, kimin işinin geri döndüğünü göstermiyor.
- **Mevcut:** Ops.cs:93-96; ops.js:46.
- **Kabul:** (1) Seri `AB-001` için 10 gün önce kapanan iş varken yeni iş açılınca `IsRepeat=1` ve `RepeatOfWorkOrderId` dolu. (2) 45 gün önce kapanmışsa işaretlenmez. (3) `ab-001 ` (küçük harf + boşluk) aynı cihaz sayılır; `0AB001` ile `AB-001` aynı sayılmaz (seri no metin kuralı, baştaki sıfır ve tire korunur). (4) PB işleri ne tetikler ne tetiklenir. (5) Kapanışta seçim yapılmadan tekrar işaretli iş kapatılamaz (400). (6) Tekrar arıza oranı = "Aynı arıza" sayısı / dönemde kapanan servis işi; raporda teknisyen kırılımı var.
- **Roller/izin:** Uyarıyı herkes görür; kök neden seçimi `workorders.close` (Şef).
- **Veri değişikliği:** `WorkOrders` + `IsRepeat, RepeatOfWorkOrderId, RepeatConfirmed`; ayar `OpsSettings(RepeatWindowDays)`.
- **Efor:** M · **Bağımlılık:** M01-16 (cihaz kütüğü bağlantısı varsa seri yerine cihaz kimliği kullanılır), M01-01 (kapanış formu).

### M10-05 · YENİ · Kalıcı bildirim kaydı, kademeli SLA uyarısı ve her sayfada rozet
- **Açıklama:** Uyarılar istek anında değil, arka planda (`BackgroundService`, 5 dk aralık) üretilip `OpsNotifications` tablosuna yazılır. Koşul ortadan kalkınca (iş kapandı, bekleme çözüldü, stok tamamlandı) bildirim otomatik "Kapandı" olur; aynı koşul için tekrar kayıt açılmaz. Alıcı: işin birimi + şefi; SLA aşımında ikinci kademe müdür. Türler: SLA riskte (%80), SLA aşıldı, atanmamış iş (açılıştan X saat sonra), plansız Kritik/Yüksek iş, bekleme beklenen tarihi geçti, açık kalmış canlı sayaç (> 10 saat), yarın planlı iş, düşük stok, eğitim tarihi. Üst menüde okunmamış sayısı rozeti (her sayfada, 60 sn yoklama). Kullanıcı "Görüldü" der; kayıt kapanana kadar listede kalır.
- **Neden:** Bugün uyarılar yalnız Operasyon Merkezi sayfası açıkken görünür (ops.js:102), "Görüldü" ertesi gün sıfırlanır (Ops.cs:32), kim ne zaman gördü dışında iz yok; şef sayfayı açmazsa geciken işten haberi olmaz. E-posta (M10-06) için de kalıcı kayıt şart.
- **Mevcut:** Ops.cs:26-65, 99, 111-121, 267-272; v120.sql:14-15; ops.js:44, 102.
- **Kabul:** (1) Kritik iş %80 süreye gelince birim şefinde 5 dk içinde "SLA riskte" bildirimi oluşur; aynı iş için ikinci kayıt oluşmaz. (2) İş kapanınca bildirim durumu "Kapandı" olur ve rozetten düşer. (3) Başka birimin şefi bu bildirimi görmez. (4) İş Emirleri sayfasındayken rozet sayısı güncellenir. (5) Teknisyene yalnız kendi açık sayacı ve kendi yarınki işi bildirilir. (6) 90 günden eski kapalı bildirimler gece temizlenir/arşivlenir.
- **Roller/izin:** Görüntüleme kendi bildirimleri (oturum); eşik/alıcı ayarı `operations.manage`.
- **Veri değişikliği:** `OpsNotifications(NotificationId, Type, Severity, WorkOrderId NULL, RefKey, UnitCode, RecipientUserId NULL, RecipientRole NULL, Message, CreatedAt, SeenAt, SeenBy, ClosedAt)`; `OpsAlertAcks` taşınıp kaldırılır.
- **Efor:** M · **Bağımlılık:** M10-01, M10-03; alıcı belirleme için M01-10 (kimlik bazlı atama).

### M10-06 · YENİ (ikinci aşama) · E-posta bildirimi (anlık SLA aşımı + günlük özet)
- **Açıklama:** M10-05 kayıtlarından e-posta: (a) SLA aşımı ve Kritik iş açılışı anlık; (b) şeflere her iş günü 07:30'da "bugün planlı / geciken / bekleme süresi aşan / atanmamış" özeti. Mevcut teklif SMTP ayarları (P.cs:906-931) yeniden kullanılır. Giden kutusu tablosu ve 3 deneme; ayar kapalıyken hiçbir e-posta gitmez. Kullanıcı bazında aç/kapat. Müşteriye e-posta bu maddede **yok**.
- **Neden:** Belge §5.10/§14: otomatik e-posta hazır değil; şef sahadayken ERP'yi açmıyor.
- **Mevcut:** Yok; SMTP yalnız teklifte (P.cs:906-931). Kullanıcı tablosunda e-posta alanı yok (Update.sql:143-157).
- **Kabul:** (1) `Email:SmtpHost` boşken bildirim üretilir, e-posta kuyruğu "Yapılandırılmadı" durumunda bekler, hata fırlatmaz. (2) SLA aşımında birim şefine tek e-posta gider; aynı bildirim için ikinci e-posta gitmez. (3) SMTP hatasında 3 deneme sonrası "Başarısız" ve hata metni loglanır (parola loglanmaz). (4) Günlük özet hafta sonu/tatilde gönderilmez (M10-02). (5) E-postada fiyat/maliyet bilgisi yoktur.
- **Roller/izin:** Kişisel tercih (oturum); genel aç/kapat `operations.manage`.
- **Veri değişikliği:** `ErpUsers.Email`, `ErpUsers.NotifyByEmail`; `OpsEmailOutbox(Id, NotificationId, To, Subject, Body, Status, Attempts, LastError, SentAt)`.
- **Efor:** M · **Bağımlılık:** M10-05; İT'den SMTP bilgisi.

### M10-07 · YENİ · SLA, bekleme ve tekrar arıza raporu (ekran + Excel sayfası)
- **Açıklama:** Raporlar ekranına ve mevcut Excel'e "SLA ve Bekleme" sayfası: dönem/birim/öncelik/müşteri/şef filtreli SLA uyum oranı (müdahale, çözüm ayrı), "Ölçülemedi" adedi, net ortalama ve medyan çözüm süresi, bekleme nedeni dağılımı (adet + toplam saat), en uzun 20 bekleme, tekrar arıza oranı ve listesi, planlı bakım vade uyumu. Operasyon CSV'sine SLA hedefi, SLA sonucu, bekleme nedeni, gecikme nedeni kolonları eklenir.
- **Neden:** Yönetici "işler neden gecikti" sorusunu bugün cevaplayamıyor; Excel'de SLA/bekleme yok, CSV 8 kolon (Ops.cs:262).
- **Mevcut:** Ops.cs:259-265; Excel üretimi P.cs:3678-3700 civarı (SLA kolonu yok).
- **Kabul:** (1) 10 kapanan işten 7'si zamanında, 2'si aşıldı, 1'i tarih eksikse rapor %77,8 (7/9) ve "Ölçülemedi: 1" gösterir; eksik iş 0 veya "Karşılandı" sayılmaz. (2) Bekleme toplamı = `OpsHolds` kayıtlarının süre toplamı (SQL ile karşılaştırma testi). (3) Ekran ve Excel aynı filtreyle aynı sayıları verir. (4) Fiyat/maliyet kolonu yoktur. (5) Planlı bakım işleri SLA uyumuna girmez, ayrı "vade uyumu" satırında yer alır.
- **Roller/izin:** `reports.view`, dışa aktarma `reports.export`.
- **Veri değişikliği:** Yok (M10-01/03/04 alanlarından okur).
- **Efor:** M · **Bağımlılık:** M10-01, M10-03, M10-04, M10-10.

### M10-08 · EKSİK · Operasyon merkezi iş listesi: atanmamış/plansız/SLA kalan süre ve dönem seçimi
- **Açıklama:** Sayaçlara "Atanmamış", "Plansız", "SLA riskte", "SLA aşıldı", "Sahada şu an", "Vadesi geçen bakım" eklenir; listede "SLA kalan süre" sütunu (negatifse kırmızı) ve buna göre varsayılan sıralama; birim, şef, öncelik, kategori filtreleri; bekleme nedeni + bekleme süresi sütunu; dönem seçimi (7/30/90 gün) arayüzü. Hesaplama sunucuda yapılır; sayaç = liste uzunluğu.
- **Neden:** Şefin sabah ilk sorusu "atanmamış ve SLA'sı yaklaşan iş var mı?"; bugün bunlar ayrı kutu değil, sıralama gecikmiş/değil ikilisiyle (Ops.cs:106), dönem 30 günde sabit (ops.js:2).
- **Mevcut:** Ops.cs:83-106; ops.js:27-43.
- **Kabul:** (1) Teknisyen ataması olmayan 3 açık servis işi varken "Atanmamış" = 3 ve tıklayınca 3 satır. (2) Liste varsayılan olarak SLA kalan süreye göre artan sıralı. (3) Birim filtresi seçilince tüm sayaçlar o birime göre yeniden hesaplanır. (4) Dönem 90 seçilince 31–90 gün önce açılmış kapalı işler de "Kapanan" sayısına girer. (5) PB işleri servis sayaçlarında yer almaz.
- **Roller/izin:** `operations.view`.
- **Veri değişikliği:** Yok.
- **Efor:** S–M · **Bağımlılık:** M10-01, M10-10.

### M10-09 · EKSİK · Personel iş yükü: canlı durum ve planlı yük
- **Açıklama:** Personel sekmesinde kişi başına: şu an aktif sayaç (iş no + faaliyet + başlangıç), bugün ve yarın planlı iş sayısı, açık iş, SLA aşmış açık iş. Kaynak: `WorkOrderLiveSessions` ve plan tablosu. Kişi-saat bu ekranda gösterilmez (Saha/Zaman raporu esas); süre kaydı yoksa "eksik" yazılır.
- **Neden:** Operasyon "kim nerede, kime yeni iş verebilirim" sorusunu bugün telefonla soruyor; mevcut sekme yalnız atama sayısı veriyor (Ops.cs:89-92, ops.js:45).
- **Mevcut:** Ops.cs:89-92; ops.js:45.
- **Kabul:** (1) Teknisyen "Sahadayım" sayacını başlatınca 1 dk içinde (yenileme ile) personel satırında iş no ve "Saha" görünür. (2) Bugün 4 planlı işi olan kişide "Bugün: 4". (3) Aynı ada sahip iki personel ayrı satırda görünür (kimlik bazlı). (4) Mola sayacı "Mola" olarak gösterilir, çalışma sayılmaz.
- **Roller/izin:** `operations.view`; teknisyen bu sekmeyi görmez.
- **Veri değişikliği:** Yok.
- **Efor:** S · **Bağımlılık:** M01-10 (kimlik bazlı atama); yoksa isim eşleşmesiyle geçici çalışır.

### M10-10 · HATA · Planlı bakım işleri 72 saat sonra "Geciken" sayılıyor ve her gün Kritik uyarı üretiyor
- **Açıklama:** PB işlerine öncelik SLA'sı uygulanmamalı. PB işi için gecikme = bağlı `MaintenancePlans.TargetDate`'in ait olduğu dönem sonu (veya TargetDate + tolerans gün) geçti ve iş kapanmadı. Servis "Geciken" sayacı ve uyarıları yalnız servis işlerini sayar; PB için ayrı "Vadesi geçen bakım" sayacı.
- **Neden:** PB işleri `Normal` öncelikle toplu üretiliyor (P.cs:3086), Ops.cs:31 ve 87 bunlara da `CreatedAt+72 sa` uyguluyor → hedefi gelecek ay olan bakım işleri bile "Geciken" görünür; gecikme sayısı ve uyarılar anlamsızlaşır (AKYAKA örneği: 17 iş birden).
- **Mevcut:** Ops.cs:31, 87, 102; P.cs:3076-3092; V15_Schema.sql:56-75.
- **Kabul:** (1) Hedef tarihi gelecek ay olan PB işi bugün üretilip 4 gün geçince "Geciken" sayısına girmez ve uyarı üretmez. (2) Hedef dönemi geçmiş, kapanmamış PB işi "Vadesi geçen bakım" sayacında görünür. (3) "Geciken" sayısı yalnız `Maint()=false` işlerden oluşur (otomatik test).
- **Roller/izin:** —
- **Veri değişikliği:** Yok (TargetDate join ile okunur).
- **Efor:** S · **Bağımlılık:** Yok (hemen yapılabilir).

### M10-11 · HATA · Bekleme kaydı ile iş durumu tutarsız (kapanan işte açık bekleme, nedensiz Beklemede, 500 hatası)
- **Açıklama:** (a) İş herhangi bir yoldan `Tamamlandı/Kapatıldı/İptal` olduğunda aktif `OpsHolds` kaydı aynı işlemde kapatılır. (b) Bakım formu sonucu "tekrar gidilecek/teklif" olduğunda (P.cs:2512) ve atölye `Beklemede` durumunda (P.cs:2750) neden kodu ile bekleme kaydı da oluşturulur (bakım: "Bakım – Uygunsuzluk Aksiyonu", atölye: seçilen neden). (c) Aktif beklemesi olan işe ikinci bekleme 409 + anlaşılır mesaj. (d) Durum `Beklemede` dışına başka uçla çıkarsa bekleme kapatılır. (e) "Bekleme" sayacı yalnız açık işleri sayar.
- **Neden:** Bugün kapanmış işler "Bekleme" sayacında görünüyor (Ops.cs:105), bakım/atölye beklemeleri hiç görünmüyor; bekleme raporu (M10-07) güvenilir olamaz.
- **Mevcut:** Ops.cs:20-25, 105, 130-159; P.cs:473-543, 2512, 2746-2755; v120.sql:11-12.
- **Kabul:** (1) Bekletilmiş iş `PATCH status=Kapatıldı` ile kapanınca `OpsHolds.ReleasedAt` dolu. (2) Bakım formunda sonuç "Tekrar gidilecek" → işte aktif bekleme kaydı ve neden var, "Bekleme" sayacında görünür. (3) İkinci hold isteği 409 döner, 500 dönmez. (4) Veritabanında `Status<>'Beklemede'` olup aktif beklemesi olan iş sayısı 0 (kontrol sorgusu). (5) Kapalı iş "Bekleme" sayacında yok.
- **Roller/izin:** —
- **Veri değişikliği:** Mevcut tutarsız kayıtlar için tek seferlik düzeltme scripti (M10-15).
- **Efor:** S–M · **Bağımlılık:** M01-14 (aynı uçlar; birlikte yapılmalı), M10-03.

### M10-12 · HATA · Saat dilimi: SLA hesapları sunucu saat dilimine bağlı
- **Açıklama:** Uygulama `DateTime.Now`, veritabanı `SYSDATETIME()` kullanıyor; Linux kurulum paketinde saat dilimi tanımı yok. Uygulama ve SQL farklı sunucuda/farklı dilimdeyse gecikme, "bugün/yarın", vardiya hesapları 3 saat kayar. Çözüm (en az değişiklik): `dengeerp.service` ve sunucuda `Europe/Istanbul` zorunlu; `03_dogrula.sh` uygulama ve SQL saatini karşılaştırır, fark > 2 dk ise hata verir; uygulama içinde "şimdi" tek yardımcı fonksiyondan alınır.
- **Neden:** Linux geçişi (10.10.50.16) yakın; UTC'de çalışan bir VM'de tüm SLA uyarıları yanlış saatte tetiklenir.
- **Mevcut:** Ops.cs:28, 83, 87, 103-104; `linux/` (TZ ayarı yok).
- **Kabul:** (1) `03_dogrula.sh` sunucu dilimi Europe/Istanbul değilse başarısız olur. (2) Uygulama ve SQL saat farkı > 2 dk ise doğrulama başarısız. (3) 23:30'da açılan iş "bugün açılan" sayısında, 00:30'da açılan ertesi gün sayısında (Türkiye saati) görünür.
- **Roller/izin:** İT kurulum adımı.
- **Veri değişikliği:** Yok.
- **Efor:** S · **Bağımlılık:** Yok.

### M10-13 · HATA · Öncelik değeri doğrulanmıyor; ön yüz ile SLA tablosu farklı
- **Açıklama:** İş açılışında ve öncelik değişikliğinde değer SLA politikası kataloğundan doğrulanır (bilinmeyen değer 400). `Düşük` ya SLA tablosundan kaldırılır ya da formlara eklenir (kullanıcı kararı). Bilinmeyen öncelikte sessiz 72 saat varsayımı kaldırılır.
- **Neden:** P.cs:409 serbest metin kaydediyor; Ops.cs:31 tanımsız önceliğe 72 saat veriyor → API'den "kritik" (küçük harf) gelen iş, raporlarda `=="Kritik"` karşılaştırmalarında (P.cs:3688, 3693) Kritik sayılmıyor.
- **Mevcut:** P.cs:409; Ops.cs:31; app.js:297; v120.sql:5.
- **Kabul:** (1) `priority="Acil"` ile POST → 400. (2) Formdaki öncelik listesi ile SLA tablosundaki öncelikler aynı. (3) Mevcut DB'de katalog dışı öncelikli iş sayısı raporlanır ve düzeltilir (M10-15).
- **Roller/izin:** —
- **Veri değişikliği:** Mevcut kayıtlarda öncelik normalizasyonu.
- **Efor:** S · **Bağımlılık:** M10-01.

### M10-14 · GÜVENLİK · Operasyon merkezi yalnız `dashboard.view` ile tüm iş listesini veriyor
- **Açıklama:** Yeni `operations.view` izni; `/api/ops/overview`, ack ve operasyon CSV için `operations.view` + `workorders.view` istenir. İK, Depo, Muhasebe varsayılan şablonlarına verilmez; Depo yalnız düşük stok bildirimini M10-05 üzerinden alır. Operasyon CSV'si `reports.export` + `workorders.view` ister. Teknisyen operasyon merkezini görmez (mobil ekranı kendi işleriyle kalır). Ack ucu tüm uyarıları yeniden hesaplamak yerine bildirim kimliğiyle çalışır (M10-05).
- **Neden:** `İnsan Kaynakları` rolü (P.cs:3934) `workorders.view` olmadan müşteri adı, lokasyon, konu ve atanan personeli görebiliyor; `AllowedUnits` boşsa tüm birimler. Fiyat/maliyet sızmadığı için **KRİTİK değil**, ama gereksiz müşteri/personel verisi erişimi (KVKK) var.
- **Mevcut:** Ops.cs:79, 113, 261; app.js:182; P.cs:3921-3934.
- **Kabul:** (1) Yalnız `dashboard.view` olan kullanıcı `GET /api/ops/overview` → 403. (2) İK şablonuyla yeni kullanıcıda menüde "Operasyon Merkezi" görünmez. (3) `operations.view` + `workorders.view` + birim=Haberleşme olan kullanıcı yalnız Haberleşme işlerini görür. (4) Teknisyen rolüyle overview → 403. (5) Mevcut kullanıcılara yeni izin otomatik dağıtılmaz; geçiş scripti yalnız Şef/Müdür/Operasyon Uzmanı/Üst Yönetim şablonundakilere ekler ve listesini çıktı verir.
- **Roller/izin:** Yeni `operations.view`.
- **Veri değişikliği:** `Catalog.Permissions` ve rol şablonları; mevcut kullanıcılara kontrollü ekleme scripti.
- **Efor:** S · **Bağımlılık:** Yok.

### M10-15 · VERİ · Geçmiş işlerin SLA alanlarının geri doldurulması ve tutarsız kayıtların temizliği
- **Açıklama:** M10-01 devreye alınırken tek seferlik, tekrar çalıştırılabilir script: (a) mevcut açık/kapalı servis işleri için `ResolveDueAt = CreatedAt + o günkü hedef`, `SlaSource='Geriye dönük'`; (b) `ResolvedAt` = `WorkOrderStatusLogs`'taki ilk `Tamamlandı/Kapatıldı/Çözüldü` zamanı, yoksa `ClosedAt`, o da yoksa **NULL → "Ölçülemedi"**; (c) `FirstResponseAt` = ilk canlı sayaç/süre kaydı başlangıcı, yoksa NULL; (d) kapalı işlerdeki açık `OpsHolds` kayıtları kapatılır; (e) eski serbest metin bekleme nedenleri katalog koduna eşlenir; (f) katalog dışı öncelikler raporlanır. Script önce yalnız rapor modunda çalışır.
- **Neden:** Yeni SLA raporu geçmiş aylar için boş veya yanlış (0/karşılandı) çıkmamalı; belge kuralı "kayıt yoksa eksik denir".
- **Mevcut:** `WorkOrderStatusLogs` (Update.sql:84-99), `OpsHolds`, `WorkOrderTimeLogs`.
- **Kabul:** (1) Rapor modunda kaç işin güncelleneceği, kaçının "Ölçülemedi" kalacağı listelenir, veri değişmez. (2) Uygulama modu iki kez çalıştırıldığında ikinci çalıştırma 0 satır değiştirir. (3) Durum logu ve `ClosedAt` olmayan kapalı iş "Ölçülemedi" olur, "Karşılandı" olmaz. (4) Script öncesi `.bak` alınması ve `DengeERP_TEST` üzerinde deneme kurulum talimatında yazılıdır.
- **Roller/izin:** DBA / İT.
- **Veri değişikliği:** Yukarıdaki alanların doldurulması; silme yok.
- **Efor:** S–M · **Bağımlılık:** M10-01, M10-03, M10-11, M10-13.

### Önerilen uygulama sırası
1. Hızlı düzeltmeler (kullanıcı önceliğinden bağımsız, hatalı sayı ürettikleri için): **M10-10, M10-12, M10-14**.
2. Yeni özellik çekirdeği: **M10-01 → M10-03 (+M01-14, M10-11) → M10-04 → M10-05 → M10-02**.
3. Ekran ve rapor: **M10-08, M10-09, M10-07**, geçiş: **M10-15**.
4. İkinci aşama: **M10-06** (SMTP ve personel e-postaları hazır olunca).

---

## 4. Kullanıcıya sorulacaklar (karar verilemeyen konular)

1. **SLA hedefleri:** Mevcut Kritik 12 / Yüksek 24 / Normal 72 / Düşük 120 saat çözüm hedefleri gerçek mi, örnek mi? Ayrıca **müdahale (sahaya varış / ilk dönüş)** hedefi istiyor musunuz (ör. Kritik: 4 saat içinde sahada)?
2. **Takvim:** SLA saati 7/24 mü işlesin, mesai saatleriyle mi? Mesai saatleri ve cumartesi çalışması nedir? Havalimanı/AVM gibi 7/24 müşteriler için farklı kural var mı?
3. **Müşteriye özel SLA:** Bakım/servis sözleşmelerinde yazılı yanıt-çözüm süresi taahhüdü olan müşteriler var mı? Varsa ilk aşamada kaç müşteri? (Yoksa müşteri bazlı SLA ertelenir.)
4. **Bekleme nedenleri:** Önerilen katalog (Malzeme, Müşteri Onayı, Teklif Onayı, Müşteri Erişimi, Üretici/Garanti, Personel/Araç, Diğer) uygun mu? Hangileri SLA saatini durdursun? (Öneri: müşteri kaynaklılar durdurur, malzeme/personel durdurmaz.)
5. **Tekrar arıza tanımı:** Kaç gün içinde aynı cihaza yeniden servis "tekrar arıza" sayılsın (öneri 30)? Seri numarası yoksa müşteri + lokasyon + sistem eşleşmesi yalnız uyarı olarak yeterli mi?
6. **Planlı bakım gecikmesi:** PB işi ne zaman "vadesi geçti" sayılsın: hedef tarihin ay sonu mu, hedef tarih + X gün mü?
7. **SLA başlangıç anı:** Müşterinin aradığı/bildirdiği saat mi (operasyon girer) yoksa kaydın açıldığı saat mi?
8. **Uyarı alıcıları ve kademe:** SLA riskte/aşıldı uyarısı kime gitsin (birim şefi, müdür yardımcısı, müdür)? Organizasyon şeması gelince netleşecek.
9. **E-posta:** Kurumsal SMTP bilgisi İT'den ne zaman alınabilir? Personel e-posta adresleri ERP'ye girilebilir mi? Hangi uyarılar e-posta ile gitsin, günlük özet saati uygun mu (07:30)?
10. **`Düşük` öncelik:** Formlara eklensin mi, SLA tablosundan kaldırılsın mı?

---

## 5. Varsayımlar

- Rol-izin eşleşmeleri mevcut rol şablonlarından (P.cs:3921-3934) türetilmiştir; organizasyon şeması gelince güncellenecektir.
- Firma ölçeği küçük-orta (aylık birkaç yüz iş emri); bu yüzden SLA hesapları için ayrı iş akışı motoru gerekmez, mevcut .NET minimal API + SQL Server içinde arka plan servisi yeterlidir. Tüm iş emirlerini belleğe yükleyen mevcut yapı (P.cs:3441-3502) bu ölçekte kabul edilebilir; sayfalama M01-17'de ele alınır.
- Planlı bakım işleri öncelik SLA'sına tabi değildir; vadeleri sözleşme dönemi hedef tarihinden gelir.
- Teknisyenin "ilk müdahale" anı canlı sayacın ilk Yol/Saha/Uzaktan Destek başlangıcıdır; mola sayılmaz. Sayaç yoksa müdahale "ölçülemedi" olur, tahmini plan saati kullanılmaz.
- E-posta bildirimi yalnız şirket içi personele gider; müşteriye otomatik bildirim bu kapsamda yoktur.
- SMS/push ve mobil çevrimdışı çalışma bu modülün kapsamı dışındadır.
