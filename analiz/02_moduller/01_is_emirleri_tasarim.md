# M01 — Ana Panel, İş Havuzu ve İş Emirleri (İş Takibi) — Gereksinim Tasarımı

> **Tarih:** 21 Ekim 2026 · **Kaynak sürüm:** V1.20.1 (salt okunur inceleme, kaynak koda dokunulmadı)
> **Kapsam:** Sadece teknik servis. Logo CRM / Flowick entegrasyonu kapsam dışı.
> **Öncelik sırası (kullanıcı kararı):** (c) yeni özellik → (b) mevcut eksikler → (a) güvenlik/üretime hazırlık. Kritik veri kaybı/sızıntısı varsa ayrıca "KRİTİK" yazılır.
> **Kısaltmalar:** `P.cs` = `DengeERP.Api/Program.cs`, `Ops.cs` = `OpsSuite.cs`, `app.js` = `wwwroot/app.js`, `upd.sql` = `Database/DengeERP_Update.sql`.

---

## 1. Mevcut durum (kodda ne var?)

### 1.1 API uçları

| Uç | Yer | Ne yapıyor | İzin |
|---|---|---|---|
| `GET /api/workorders` | P.cs:359-368 | **Tüm** iş emirlerini tek seferde yükler, bellekte birim/teknisyen filtresi uygular (P.cs:3441-3502). Sayfalama/tarih filtresi yok. | `workorders.view` |
| `POST /api/workorders` | P.cs:370-430 | `SRV-yyyyMM-####` numarası, durum sabit `Müşteri Talebi`, seri no listesi `WorkOrderDevices`'a, durum logu. | `workorders.create` + birim |
| `PUT /api/workorders/{id}/serials` | P.cs:432-471 | Seri noları değiştirir (eskileri pasif). PB işlerinde engelli. **Geçmişe yazmaz.** | create/edit/close |
| `PATCH /api/workorders/{id}/status` | P.cs:473-543 | **Serbest metin** durum kabul eder; geçiş kuralı yok. Kapanışta: açık sayaç, PB formu, seri no kuralı kontrolü. `ClosedAt` yalnız `Kapatıldı`'da set edilir, tekrar açılınca temizlenmez. | `workorders.edit` **veya** `workorders.close` |
| `PUT /api/workorders/{id}/assignments` | P.cs:545-570 | Şef + çoklu teknisyen, **isim metniyle**. Geçmişe yazmaz. Kapalı işe de atama yapılabilir. | `workorders.assign` |
| `PUT /api/workorders/bulk-assign` | P.cs:573-614 | Aynı birimde ≤150 açık işe toplu atama, geçmişe yazar. | `workorders.assign` |
| `PUT /api/workorders/bulk-plan` | P.cs:649-720 | Aynı müşteri+lokasyon+birim toplu plan, `TPL-…` ziyaret no. | plan + assign |
| `PUT /api/workorders/{id}/plan` | P.cs:722-761 | Tekil plan. **Durum kontrolü yok** → kapalı işi `Planlandı` yapar; log'da `OldStatus=NULL` (P.cs:757). | `workorders.plan` |
| `GET /api/workorders/{id}/history` | P.cs:763-788 | Yalnızca `WorkOrderStatusLogs`. | `workorders.view` |
| `GET /api/workorders/{id}/site-suggestion` | P.cs:619-647 | Cihaz kütüğünden saha önerisi. | `workorders.plan` |
| `POST /api/ops/workorders/{id}/hold` / `release` | Ops.cs:130-159 | `OpsHolds` + durumu `Beklemede`/önceki duruma çevirir. **`WorkOrderStatusLogs`'a yazmaz**, çift aktif bekleme engellenmez. | `operations.manage` veya `workorders.edit` |
| `GET /api/ops/overview` | Ops.cs:76-110 | Operasyon merkezi sayaçları; SLA `CreatedAt + öncelik saati` (Ops.cs:31, 87), bekleme süresi düşülmez. | `dashboard.view` |
| `GET /api/rules/worktypes` | P.cs:153-172 | Birim + iş türü bazında seri no zorunluluğu. | oturum |

Canlı sayaç / süre kaydı uçları (P.cs:1929-2179) bu modülle bağlantılı ama **Saha/Zaman** modülüne aittir; burada yalnız kapanış engeli olarak (P.cs:504-509) dikkate alındı.

### 1.2 Tablolar (upd.sql)

- `WorkOrders` (upd.sql:6-30, 169-186): No, Birim, İş Türü, Müşteri (metin), Proje, Lokasyon, Konu, Açıklama, Öncelik, Durum, SystemName, SerialNo, CustomerEmail, CreatedAt, UpdatedAt, ClosedAt, `RowVersion` (**kullanılmıyor**). Durum için CHECK/katalog yok. **İletişim kişisi/telefonu, talep kanalı, kategori, çözüm kanalı, yapılan işlem, arıza nedeni, iptal gerekçesi alanı yok.**
- `WorkOrderAssignments` (upd.sql:33-46): `AssignedName` metin + rol (Şef/Teknisyen). Personel/kullanıcı kimliği yok, "sorumlu teknisyen" yok, kim atadı yok.
- `WorkOrderDevices` (upd.sql:67-82): seri no metin; `SecurityDevices` ile FK yok.
- `WorkOrderStatusLogs` (upd.sql:84-99): eski/yeni durum, not, kullanıcı. Olay türü yok.
- `WorkTypeRules` (upd.sql:101-139; V15_Schema.sql:136-144): seri no kuralı; **kategori kolonu yok.**
- **Ek dosya, fotoğraf, müşteri onayı/imza için hiçbir tablo veya uç yok** (Grep: `attachment|photo|imza|upload|IFormFile` → yalnız teklif e-postası eki, P.cs:924).

### 1.3 Ön yüz (app.js)

- Durum listeleri: `statuses` (14 durum) ve `pocStatuses` (12 durum; `Telefonla Destek`, `Uzaktan Müdahale`, `Yerinde Müdahale` **durum** olarak) — app.js:30-31.
- İş türleri / sistemler sabit listesi (app.js:9-22); personel yedek listesi kodda sabit isimler (app.js:23-29).
- Kategori ayrımı **sezgisel**: `isMaintenanceOrder` = no `PB-` ile başlıyorsa veya tür `Planlı Bakım` (app.js:127; aynı mantık Ops.cs:9 ve P.cs:3639). Atölye, POC, Mobilite ayrımı yalnızca **birim** veya **iş türü metni** üzerinden.
- Ana Panel (app.js:211-225): Servis (8 kutu) + Bakım (4 kutu) + birim kartları + son 10 servis. Kutular tıklanabilir (app.js:229-289) — V1.8'de doğrulanmış.
- Yeni İş Açılışı formu (app.js:292-309, gönderim app.js:1951): birim sekmesi, tür, öncelik (Normal/Yüksek/Kritik), müşteri, e-posta, proje, lokasyon, sistem, seri no, konu, açıklama. **İlgili kişi/telefon, talep kanalı yok; mükerrer kayıt kontrolü yok.**
- İş Emirleri listesi (app.js:316-341, arama app.js:1953): servis/bakım sekmesi, açık/tamamlanan, birim filtresi, metin arama, toplu atama.
- İş emri detay penceresi `openWorkOrder` (app.js:1608-1676): bilgi, plan, atama+durum (tek "Kaydet" butonu her seferinde `PATCH status` çağırır → durum değişmese de log satırı oluşur, app.js:1671), teklif oluştur, canlı sayaç, gerçek süre, durum geçmişi. **Temel bilgiler (müşteri, lokasyon, konu, öncelik, tür) düzenlenemez — API'de de karşılığı yok.**
- Bekleme nedeni girişi `prompt()` ile (ops120.js:73).

### 1.4 İş kuralları (mevcut)

- Seri no zorunluluğu: açılışta/kapanışta, `WorkTypeRules`'tan (P.cs:378-380, 520-522; yedek kural P.cs:3380-3382).
- Kapanış engelleri: açık canlı sayaç, PB cihaz formu tamamlanmamış (P.cs:504-523).
- PB işi kapatıldıktan sonra bu ekrandan açılamaz (P.cs:500-503); **servis işleri için böyle bir koruma yok**.
- Teknisyen yalnız kendisine atanmış işi görür — ancak kontrol `RoleName=="Teknisyen"` ve **ad-soyad metni eşleşmesi** ile (P.cs:3398-3400, 3499-3500).
- `IsClosingStatus` = Tamamlandı/Kapatıldı/Çözüldü (P.cs:2808) — `Çözüldü` hiçbir listede yok; `İptal` kapanış sayılmıyor ama açık sayaç kontrolü yapılmadan iptal edilebilir.

### 1.5 Tespit edilen tutarsızlıklar (kanıtlı)

1. **"Sahada" kutusu sayı ≠ liste:** sayı `Sahada`+`İşlemde` sayar (app.js:220), tıklanınca açılan liste yalnız `Sahada` (app.js:243).
2. **"Açık Bakım" kutusu sayı ≠ liste:** sayı `reportIsOpen` (Tamamlandı hariç, app.js:216/222), liste `isOpen` (Tamamlandı dahil, app.js:248).
3. `Yola Çıkıldı`, `Planlamada`, `Test / Kontrol`, `Kargoda`, `Tekrar Açıldı` ve POC durumları "Açık Servis" toplamında var ama hiçbir alt kutuda yok → alt kutular toplamı açık sayıyı vermiyor.
4. Excel durum matrisi yalnız 10 durumu sayar (P.cs:3684) → diğer durumlardaki işler raporda kaybolur.
5. `ClosedAt` yalnız `Kapatıldı`'da dolar; `Tamamlandı` olan işin çözüm zamanı tutulmuyor; tekrar açılan işte eski `ClosedAt` kalıyor (P.cs:525-528).

---

## 2. Olması gereken (Denge Elektronik teknik servis çalışma sistemi)

### 2.1 Roller ve sorumluluklar (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol (mevcut rol adı) | Bu modülde yaptığı | Gerekli izinler |
|---|---|---|
| Operasyon Uzmanı / Teknik Servis Operasyon Uzmanı | Telefon/WhatsApp/e-postayla gelen talebi kaydeder; ilgili kişi, kanal, bildirim saati girer; telefonla çözülen basit talebi "açılışta çözüldü" olarak kaydeder. | `workorders.view`, `workorders.create`, (yeni) `workorders.resolve_remote` |
| Şef (Saha Takım Lideri / Laboratuvar Takım Lideri) | Havuzu inceler, kategori/öncelik düzeltir, planlar, ekip atar, bekletme nedeni girer, **Tamamlandı işi kontrol edip Kapatır**, gerekirse yeniden açar. | view, edit, assign, plan, close, (yeni) `workorders.reopen`, `workorders.cancel` |
| Teknisyen | Yalnız kendi işini görür; durumu ilerletir (Yola Çıkıldı → Sahada → Tamamlandı); kapanış formu, fotoğraf, müşteri onayı girer. **Kapatamaz.** | view, edit, (yeni) `workorders.complete`, (yeni) `workorders.attach` |
| Teknik Servis Müdürü / Yardımcısı | Tüm birimler; KPI; iptal/yeniden açma; kapanmış işte düzeltme. | tümü |
| Depo, Muhasebe, Kiralama, Genel Koordinatör | Salt görüntüleme (fiyat/maliyet alanı API'de gizli). | `workorders.view` |

### 2.2 Tutulacak veriler (artımlı, mevcut tabloya kolon ekleyerek)

- **Talep:** talep kanalı (Telefon / WhatsApp / E-posta / Sahada bildirildi / Bakım otomatik), müşteri ilgili kişi + telefon, müşterinin bildirdiği zaman (`ReportedAt`), mükerrer kayıt bağlantısı.
- **Sınıflandırma:** iş kategorisi (`ServiceCategory`: Günlük Servis/Arıza · Planlı Bakım · Atölye Onarım · Kurulum/Devreye Alma · Diğer) — `WorkTypeRules`'tan türetilir; birim (mevcut); iş türü (mevcut).
- **Çözüm:** çözüm kanalı (`ResolutionChannel`: Telefonla · Uzaktan · Yerinde · Atölyede), arıza nedeni kategorisi, yapılan işlem (metin), servis sonucu (Çözüldü / Tekrar Gidilecek / Teklif Sunulacak / Servise Alındı / Çözülemedi), `CompletedAt` + kim, `ClosedAt` + kim, iptal gerekçesi, yeniden açılma sayısı.
- **Ekip:** atamalarda Personel/Kullanıcı kimliği, sorumlu teknisyen işareti, atayan kişi, atama/çıkarma zamanı.
- **Kanıt:** ek dosya/fotoğraf (önce/sonra/arıza/servis formu), müşteri onayı (imza görüntüsü veya "sözlü onay" veya "onay alınamadı + neden").
- **Geçmiş:** durum, atama, plan, bekleme, not, ek, alan düzeltmesi olaylarının tek zaman çizelgesi.

### 2.3 Durum yaşam döngüsü (mevcut durum adları korunur — veri göçü gerekmez)

```
Müşteri Talebi ─┬─> Planlamada ─> Planlandı ─> Yola Çıkıldı ─> Sahada / İşlemde ─┬─> Tamamlandı ─> Kapatıldı
                │                                                  │            │        │  ▲            │
                │                                     Atölyede / Kargoda / Test-Kontrol      │  └─(şef reddi)┘
                └─> (telefon/uzaktan çözüm) ─────────────────────────────────────> Tamamlandı
Her açık durumdan: Beklemede (yalnız neden ile, önceki duruma döner) · İptal (gerekçe zorunlu)
Tamamlandı/Kapatıldı ─> Tekrar Açıldı (gerekçe + reopen izni) ─> akışa geri döner
```

Kurallar:
- `Planlandı` yalnız plan uçlarıyla; `Beklemede` yalnız bekleme ucuyla (nedenli) girilir.
- `Tamamlandı`: kapanış formu (çözüm kanalı, yapılan işlem, sonuç) + seri no kuralı + açık sayaç yok + (kurala göre) müşteri onayı.
- `Kapatıldı`: yalnız `Tamamlandı`'dan, `workorders.close` izniyle (şef kontrolü).
- `İptal`: gerekçe zorunlu; açık sayaç varsa engellenir.
- Kapalı/iptal işe plan, atama, seri no değişikliği yapılamaz.
- POC'nin `Telefonla Destek / Uzaktan Müdahale / Yerinde Müdahale` durumları → **çözüm kanalı alanına** taşınması önerilir (kullanıcı onayı gerekir, bkz. §4).

### 2.4 Ana Panel KPI'ları

Günlük servis ve planlı bakım ayrı kalır (karar). Her kutu = tek tanım fonksiyonu; sayı ve açılan liste **aynı fonksiyondan** gelir.

- **Servis:** Açık · Atanmamış (teknisyen yok) · Plan bekleyen · Bugün planlı · Sahada/İşlemde (Yola Çıkıldı dahil) · Atölyede/Kargoda · Beklemede (nedene göre kırılım) · Geciken (SLA) · Kritik açık · Bugün açılan · Bugün tamamlanan · Tamamlandı-kapanmayı bekleyen.
- **Dönemsel (seçilebilir: bugün / bu hafta / bu ay / son 30 gün):** tamamlanan iş, telefonla+uzaktan çözüm oranı, ortalama çözüm süresi (`ReportedAt`→`CompletedAt`), 30 gün içinde aynı seride tekrar arıza oranı, süre kaydı **eksik** olan tamamlanmış iş sayısı (0 saat değil, "eksik").
- **Bakım:** mevcut 4 kutu (tutarlılık düzeltilerek).

### 2.5 Doğrulamalar

- Zorunlu alanlar: birim, iş türü, müşteri, konu, öncelik, talep kanalı; ilgili kişi veya telefondan en az biri (bakım otomatik üretimi hariç).
- Seri no metin olarak saklanır (baştaki sıfır, `/`, `-`, `.` korunur) — mevcut karar.
- Açılışta aynı seri no veya aynı müşteri+lokasyon için **açık** iş varsa uyarı (engel değil).
- Tahmini süre hiçbir KPI'da gerçek süre yerine kullanılmaz; süre kaydı yoksa "eksik" gösterilir.
- Fiyat/maliyet alanları bu modülün API cevaplarında yetkisiz kullanıcıya dönmez.

---

## 3. Fark listesi (maddeler)

Sıralama: önce YENİ (c), sonra EKSİK/HATA/VERİ (b), en son GÜVENLİK (a). **Bu modülde, kendi başına KRİTİK seviyede veri kaybı/sızıntısı tespit edilmedi**; genel oturum/yetki açıkları (envanter §"İlk gözlemler") bu modülü de etkiler ve ayrıca ele alınmalıdır.

### M01-01 · YENİ · Servis işi kapanış formu (yapılan işlem, arıza nedeni, sonuç)
- **Açıklama:** PB dışındaki tüm iş emirlerinde `Tamamlandı`'ya geçişte zorunlu kapanış bölümü: yapılan işlem (metin), arıza nedeni kategorisi (birim bazlı liste), servis sonucu (Çözüldü / Tekrar Gidilecek / Teklif Sunulacak / Servise Alındı / Çözülemedi), çözüm kanalı (M01-02).
- **Neden:** Bugün servis işinde "ne yapıldı, neden arızalandı" verisi yok; tekrar arıza analizi ve basılı servis formunun dijitalleşmesi bu veriye dayanıyor. PB'de var (P.cs:2445-2457), servis işinde yok.
- **Mevcut:** `WorkOrders`'da ilgili kolon yok (upd.sql:6-30); durum değişimi yalnız serbest not alır (P.cs:3816).
- **Kabul:** (1) Kapanış formu boşken `Tamamlandı` isteği 400 döner. (2) Doldurulunca alanlar SQL'de iş emrinde görünür, iş detayında okunur. (3) "Tekrar Gidilecek" sonucu işi kapatmaz; durum `Planlamada`'ya döner ve geçmişe yazılır. (4) Arıza nedeni ve sonuç Excel "Günlük Servis" sayfasında kolon olarak çıkar.
- **Roller:** Teknisyen/Şef — `workorders.complete` (yeni) veya `workorders.close`.
- **Veri:** `WorkOrders` ADD `ActionTaken NVARCHAR(MAX)`, `FaultCategory NVARCHAR(100)`, `ServiceResult NVARCHAR(50)`, `CompletedAt DATETIME2`, `CompletedByUserId INT`; yeni `FaultCategories(UnitCode, Name, IsActive)`.
- **Efor:** M · **Bağımlılık:** M01-09 (durum geçiş kuralları ile birlikte)

### M01-02 · YENİ · Telefonla / uzaktan / yerinde / atölyede çözüm ayrımı (tüm birimler)
- **Açıklama:** `ResolutionChannel` alanı tüm birimlerde zorunlu kapanış bilgisi. Operasyon uzmanı için "Açılışta çözüldü" kısa yolu: kayıt açılırken "Telefonla çözüldü / Uzaktan çözüldü" seçilirse iş doğrudan `Tamamlandı` olur (planlama/atama gerekmez), şef onayıyla kapanır.
- **Neden:** Belgedeki hedef (§5.1, §14 Öncelik 2): telefonla/uzaktan çözülebilecek arızaların görünmesi, gereksiz saha ziyaretinin azaltılması. Bugün yalnız POC'de iş türü/durum olarak var (V15/upd.sql:132-134, app.js:31).
- **Mevcut:** POC dışı birimlerde bu bilgi tutulmuyor.
- **Kabul:** (1) Her birimde `Tamamlandı` için kanal seçimi zorunlu. (2) Açılışta-çözüldü kaydı tek istekte oluşur, geçmişte "Müşteri Talebi → Tamamlandı (Telefonla)" görünür. (3) Ana panelde dönem bazlı "telefonla+uzaktan çözüm oranı" kutusu, tıklanınca ilgili işleri listeler; sayı = liste uzunluğu. (4) Bu işler "Plan bekleyen" ve "Atanmamış" kutularında sayılmaz.
- **Roller:** Operasyon Uzmanı — `workorders.create` + yeni `workorders.resolve_remote` (VARSAYIM); Teknisyen/Şef — kapanış izinleri.
- **Veri:** `WorkOrders` ADD `ResolutionChannel NVARCHAR(30) NULL`. Geçmiş POC işleri için tek seferlik eşleme: iş türü `Telefonla Destek`→Telefonla, `Uzaktan Müdahale`→Uzaktan, `Yerinde Müdahale`→Yerinde (yalnız kapalı işlerde; diğerleri NULL = "girilmemiş").
- **Efor:** M · **Bağımlılık:** M01-01

### M01-03 · YENİ · Ek dosya / fotoğraf
- **Açıklama:** İş emrine dosya/fotoğraf ekleme, listeleme, indirme; mobilde kamera ile doğrudan çekim (`<input type=file accept="image/*" capture>`). Kategori: Arıza (önce) / Sonra / Servis formu (ıslak imzalı tarama) / Diğer. Silme yalnız gerekçeli "iptal" (kayıt korunur).
- **Neden:** Bugün kanıt WhatsApp'ta kalıyor; müşteri itirazı ve tekrar arızada sahadaki durum gösterilemiyor.
- **Mevcut:** Hiçbir yükleme ucu/tablosu yok (Grep sonucu, §1.2).
- **Kabul:** (1) Yalnız jpg/png/heic/pdf, dosya başına ≤10 MB (değer kullanıcı onayına bağlı); başka tür 400. (2) Dosya veritabanına değil, yapılandırılabilir klasöre rastgele adla yazılır (Linux: `/var/lib/dengeerp/files`); orijinal ad yalnız metadata. (3) İndirme ucu `CanAccessWorkOrderAsync` uygular — atanmamış teknisyen başka işin dosyasını indiremez (403 testi). (4) Kapalı işe ek eklenemez (şef/müdür hariç, gerekçeli). (5) Eklenen/iptal edilen dosya iş geçmişinde görünür. (6) Dosya adı `../` içerse bile klasör dışına yazılmaz (test).
- **Roller:** Atanmış teknisyen, şef, müdür — yeni `workorders.attach`; görüntüleme `workorders.view` + iş erişimi.
- **Veri:** Yeni `WorkOrderAttachments(AttachmentId BIGINT PK, WorkOrderId FK, Category, OriginalName, StoredName, ContentType, SizeBytes, Sha256, Note, UploadedByUserId, UploadedAt, IsVoided, VoidedByUserId, VoidedAt, VoidReason)`. Yedekleme prosedürüne dosya klasörü eklenmeli.
- **Efor:** M · **Bağımlılık:** —

### M01-04 · YENİ · Müşteri onayı ve dijital servis formu çıktısı
- **Açıklama:** İş tamamlanırken müşteri onayı: (a) ekranda parmakla imza (canvas → PNG ek), imzalayan ad/unvan; (b) "telefonla/sözlü onay" + onaylayan ad; (c) "onay alınamadı" + zorunlu neden. Basılı Teknik Servis Formu düzeninde **yazdırılabilir HTML servis formu** (tarayıcıdan PDF): firma/adres, başlangıç-bitiş (gerçek süre kayıtlarından), servis türü, ürün/seri no, kullanılan parçalar (stok çıkışlarından), yapılan işlem, sonuç, imza.
- **Neden:** Belge §6.1 ve §14 Öncelik 2: müşteri onayı/kanıt akışı eksik. Mevcut PDF üretici Türkçe karakterleri ASCII'ye çeviriyor (P.cs:3573-3575) → servis formu için HTML yazdırma daha uygun ve bağımlılık gerektirmez.
- **Mevcut:** Onay/imza alanı yok.
- **Kabul:** (1) Onay kuralı "zorunlu" olan iş türünde onay kaydı olmadan `Tamamlandı` 400 döner. (2) "Onay alınamadı" nedeni boşsa 400. (3) Servis formu Türkçe karakterleri doğru gösterir; süre kaydı yoksa süre alanında "Süre kaydı eksik" yazar, "0" yazmaz. (4) Onay kaydı sonradan değiştirilemez; yalnız yeni kayıtla geçersiz kılınır, ikisi de geçmişte görünür. (5) Form fiyat/maliyet içermez.
- **Roller:** Teknisyen/Şef — `workorders.complete`; form görüntüleme `workorders.view`.
- **Veri:** Yeni `WorkOrderApprovals(ApprovalId, WorkOrderId, ApprovalType, SignerName, SignerTitle, SignatureAttachmentId NULL, MissingReason, CreatedByUserId, CreatedAt, IsSuperseded)`; `WorkTypeRules` ADD `ApprovalRequiredOnComplete BIT`.
- **Efor:** M · **Bağımlılık:** M01-03, M01-01

### M01-05 · YENİ · Talep alma bilgileri ve mükerrer kayıt uyarısı
- **Açıklama:** Açılış formuna talep kanalı, müşteri ilgili kişi, telefon, bildirim zamanı (varsayılan şimdi, geçmişe alınabilir). Kayıt öncesi aynı seri no veya aynı müşteri+lokasyon için açık iş varsa listeyi gösterip "yine de aç / mevcut işe not ekle" seçimi.
- **Neden:** Talepler telefon/WhatsApp ile birden çok kişiye geliyor (belge §1); aynı arıza için çift kayıt ve "kim aradı, kime dönülecek" bilgisi kayboluyor. SLA'nın müşteri bildirim saatinden hesaplanabilmesi için `ReportedAt` gerekli.
- **Mevcut:** Form yalnız e-posta alıyor (app.js:298-299); mükerrer kontrolü yok (P.cs:370-430).
- **Kabul:** (1) Kanal ve (kişi veya telefon) boşsa 400 (bakım otomatik üretimi hariç). (2) `ReportedAt` gelecekte olamaz, 7 günden eskiyse uyarı ister. (3) Açık seri no çakışmasında API `409` + mevcut iş no listesi döner; `force=true` ile açılır ve geçmişe "mükerrer uyarısı geçildi" yazılır. (4) İlgili kişi/telefon iş detayında ve planlama kartında görünür.
- **Roller:** Operasyon Uzmanı, Şef — `workorders.create`.
- **Veri:** `WorkOrders` ADD `RequestChannel NVARCHAR(30)`, `ContactName NVARCHAR(150)`, `ContactPhone NVARCHAR(50)`, `ReportedAt DATETIME2` (eski kayıtlar için NULL; raporda `CreatedAt` yedeği "tahmini" etiketiyle).
- **Efor:** S · **Bağımlılık:** —

### M01-06 · YENİ · İş notu ve birleşik iş geçmişi
- **Açıklama:** Durum değiştirmeden "iş notu" ekleme (ilerleme, müşteriyle görüşme). İş geçmişi tek zaman çizelgesi: durum, atama, plan, bekleme/çözme, not, ek, onay, alan düzeltmesi, seri no değişikliği.
- **Neden:** "Bu işe ne oldu?" sorusunun tek yerden cevabı; bugün atama (P.cs:545-570), seri no (P.cs:432-471), bekleme (Ops.cs:130-159) değişiklikleri geçmişte görünmüyor.
- **Mevcut:** Yalnız `WorkOrderStatusLogs` (P.cs:763-788).
- **Kabul:** (1) Yukarıdaki her işlem sonrası `/history` yeni satır döner (tür + kullanıcı + zaman + özet). (2) Not ekleme durumu değiştirmez. (3) Geçmiş satırı API üzerinden silinemez/düzenlenemez.
- **Roller:** Not ekleme `workorders.edit` + iş erişimi; okuma `workorders.view`.
- **Veri:** `WorkOrderStatusLogs` ADD `EventType NVARCHAR(30) NOT NULL DEFAULT N'Durum'` (mevcut satırlar "Durum" kalır).
- **Efor:** S · **Bağımlılık:** —

### M01-07 · YENİ · Açık iş kategorisi (Günlük Servis / Planlı Bakım / Atölye / Kurulum)
- **Açıklama:** `WorkTypeRules`'a `Category` kolonu; iş açılırken kategori kayda yazılır. Panel, liste, Ops ve Excel `PB-` ön ekine/metin karşılaştırmasına değil bu alana bakar. POC ve Mobilite **birim** olarak kalır (kategori değil).
- **Neden:** Bugün kategori üç ayrı yerde sezgisel hesaplanıyor (app.js:127, Ops.cs:9, P.cs:3639); "Plansız Bakım" (app.js:10-11) servis mi bakım mı belirsiz; atölye işi ayrı sayılamıyor.
- **Mevcut:** Kategori kolonu yok.
- **Kabul:** (1) Her aktif `WorkTypeRules` satırında kategori dolu. (2) Mevcut işler tek seferlik script ile kategorilenir; eşlenemeyen kayıt sayısı script çıktısında raporlanır (0 değilse liste). (3) Ana panel, İş Emirleri sekmesi, Ops overview ve Excel aynı iş için aynı kategoriyi gösterir (örnek 10 kayıtla karşılaştırma). (4) Planlı bakım servis KPI'larına girmez (mevcut karar korunur).
- **Roller:** Kategori düzeltme: Şef/Müdür — `workorders.edit`.
- **Veri:** `WorkTypeRules` ADD `Category NVARCHAR(50)`; `WorkOrders` ADD `ServiceCategory NVARCHAR(50)` + geri doldurma scripti.
- **Efor:** M · **Bağımlılık:** —

### M01-08 · EKSİK · İş emri temel bilgilerini düzeltme
- **Açıklama:** `PUT /api/workorders/{id}` ile müşteri, proje, lokasyon, konu, açıklama, öncelik, iş türü (aynı birim içinde), ilgili kişi/telefon düzeltme. Her değişiklik eski→yeni değerle geçmişe yazılır.
- **Neden:** Bugün yanlış yazılmış müşteri/lokasyon düzeltilemiyor (API'de uç yok; detay ekranı salt-okunur, app.js:1623); toplu planlama aynı müşteri+lokasyon metin eşitliğine dayandığı için (P.cs:677-681) yazım hatası planlamayı da bozuyor.
- **Mevcut:** Uç yok.
- **Kabul:** (1) Açık işte düzeltme 200 döner, geçmişte alan bazında eski/yeni görünür. (2) `Kapatıldı`/`İptal` işte yalnız müdür (yeni `workorders.edit_closed` veya `*`) düzeltebilir, gerekçe zorunlu. (3) Birim değişikliği bu uçla yapılamaz (400). (4) `RowVersion` ile eşzamanlı düzenlemede ikinci kaydeden 409 alır.
- **Roller:** Şef, Operasyon Uzmanı (yalnız kendi açtığı ve henüz `Müşteri Talebi` olan iş — VARSAYIM) — `workorders.edit`.
- **Veri:** Kolon değişikliği yok (`RowVersion` zaten var).
- **Efor:** S · **Bağımlılık:** M01-06

### M01-09 · EKSİK · Sunucu tarafında durum yaşam döngüsü
- **Açıklama:** §2.3'teki geçiş tablosu API'de uygulanır: izinli geçişler listesi, `Tamamlandı` (teknisyen) / `Kapatıldı` (şef) ayrımı, `İptal` ve `Tekrar Açıldı` için gerekçe + izin, `Beklemede`'ye yalnız bekleme ucuyla, `Planlandı`'ya yalnız plan uçlarıyla geçiş. Durum kataloğu tek yerde (sunucu) tanımlanır, ön yüz ve Excel buradan okur. İstek `expectedStatus` taşır; uyuşmazsa 409.
- **Neden:** Bugün `PATCH status` herhangi bir metni kabul ediyor (P.cs:525-531); teknisyen kapalı servis işini tekrar açabiliyor; `Kapatıldı`'ya doğrudan geçiliyor; `ClosedAt` tekrar açılışta temizlenmiyor; Excel bazı durumları saymıyor (P.cs:3684).
- **Mevcut:** Geçiş kontrolü yalnız PB kapanışı için (P.cs:500-503).
- **Kabul:** (1) Katalog dışı durum → 400. (2) `Müşteri Talebi`→`Kapatıldı` doğrudan → 400. (3) Teknisyen hesabıyla `Kapatıldı` → 403. (4) `İptal` ve `Tekrar Açıldı` gerekçesiz → 400; izinsiz → 403. (5) `Tekrar Açıldı` sonrası `ClosedAt`/`CompletedAt` NULL, `ReopenCount` +1. (6) Aynı durumu tekrar göndermek log üretmez. (7) Excel durum matrisindeki toplam = filtrelenen iş sayısı.
- **Roller:** Teknisyen `workorders.complete`; Şef `workorders.close`, `workorders.reopen`, `workorders.cancel` (yeni anahtarlar; rol şablonlarına eklenir, mevcut özel profillere otomatik dağıtılmaz — mevcut karar).
- **Veri:** `WorkOrders` ADD `ClosedByUserId INT`, `CancelReason NVARCHAR(500)`, `ReopenCount INT NOT NULL DEFAULT 0`; yeni `WorkOrderStatusCatalog(Status, Group, SortOrder, IsActive)` (veya kodda sabit — karar §4).
- **Efor:** L · **Bağımlılık:** M01-01, M01-06

### M01-10 · EKSİK · Çoklu teknisyen: kimlik bazlı atama ve sorumlu teknisyen
- **Açıklama:** Atamada isim yerine `PersonnelId` (ve varsa `ErpUserId`) saklanır; bir teknisyen "sorumlu" işaretlenir; kim/ne zaman atadı tutulur. Seçim listesi yalnız `Personnel` tablosundan (kodda sabit yedek liste kaldırılır, app.js:23-29). Kapalı işe atama engellenir.
- **Neden:** Bugün atama metin; ad değişince veya iki kişi aynı adı taşıyınca teknisyen işini göremez (P.cs:3398-3400), canlı sayaç başlatamaz (P.cs:1943-1948); ERP kullanıcısı olmayan personel atanabiliyor ama süre kaydedemiyor.
- **Mevcut:** `WorkOrderAssignments.AssignedName` (upd.sql:39); tekil atama kapalı iş kontrolü yapmaz (P.cs:545-570).
- **Kabul:** (1) Yeni atamalarda `PersonnelId` dolu; personel listesinde olmayan ad 400. (2) Personelin adı değişse de teknisyen kendi işlerini görmeye devam eder. (3) Bir işte en fazla bir sorumlu teknisyen. (4) ERP hesabı olmayan personel atanınca ekranda "bu kişi süre kaydedemez" uyarısı. (5) Kapalı işe atama → 400. (6) Atama değişikliği geçmişe yazılır.
- **Roller:** Şef/Müdür — `workorders.assign`.
- **Veri:** `WorkOrderAssignments` ADD `PersonnelId BIGINT NULL FK`, `ErpUserId INT NULL`, `IsLead BIT DEFAULT 0`, `AssignedByUserId INT`, `RemovedAt DATETIME2`. Eski satırlar ad eşleşmesiyle doldurulur; eşleşmeyenler raporlanır, metin korunur.
- **Efor:** M · **Bağımlılık:** Personel modülü (personel listesinin doğruluğu)

### M01-11 · EKSİK · Ana panel KPI setinin tamamlanması ve dönem seçimi
- **Açıklama:** §2.4'teki kutular. Tüm kutular tek bir `kpiDefinitions` tablosundan (ad → filtre fonksiyonu) üretilir; sayı ve tıklanınca açılan liste aynı fonksiyonu kullanır. Dönemsel kutular için bugün/hafta/ay/30 gün seçimi; kullanıcının seçimi tarayıcıda hatırlanır.
- **Neden:** Belgedeki ana sorular (§1): "bugün ne geldi, ne kapandı, ne gecikti". Bugünkü "Tamamlanan Servis" tüm zamanların toplamı (app.js:216-220); atanmamış ve geciken iş Ana Panel'de yok (yalnız Operasyon Merkezi'nde).
- **Mevcut:** app.js:211-257.
- **Kabul:** (1) Her kutu için otomatik kontrol: sayı = açılan liste kayıt sayısı. (2) Servis açık alt kutularının toplamı (Beklemede ve Atölye dahil) = "Açık Servis". (3) "Geciken" Operasyon Merkezi ile aynı SLA tanımını kullanır (aynı veride aynı sayı). (4) Tamamlanan iş arasında süre kaydı olmayanlar "Süre kaydı eksik" kutusunda çıkar, "0 saat" yazılmaz.
- **Roller:** `dashboard.view`; birim ve teknisyen kapsamı mevcut filtrelerle.
- **Veri:** Yok (M01-02, M01-05 alanlarını kullanır).
- **Efor:** M · **Bağımlılık:** M01-02, M01-07

### M01-12 · HATA · KPI kutusu sayısı ile açılan liste uyuşmuyor
- **Açıklama:** "Sahada" sayısı `Sahada+İşlemde`, listesi yalnız `Sahada`; "Açık Bakım" sayısı Tamamlandı hariç, listesi Tamamlandı dahil. Bazı açık durumlar hiçbir alt kutuda değil.
- **Neden:** Yönetici sayıya tıklayınca farklı sayıda kayıt görüyor; panelin güvenilirliği bozuluyor. (M01-11 yapılana kadar küçük, hızlı düzeltme.)
- **Mevcut:** app.js:220 ↔ 243; app.js:216/222 ↔ 248.
- **Kabul:** (1) Test verisinde 1 `Sahada` + 1 `İşlemde` servis işi varken kutu 2, liste 2. (2) 1 `Tamamlandı` + 1 `Planlandı` PB işi varken "Açık Bakım" kutu 1, liste 1. (3) `Yola Çıkıldı` iş "Sahada/İşlemde" kutusunda görünür.
- **Roller:** —
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** —

### M01-13 · HATA · Tekil planlama kapalı işi sessizce yeniden açıyor
- **Açıklama:** `PUT /api/workorders/{id}/plan` iş durumunu kontrol etmeden `Planlandı` yapıyor; geçmiş satırına eski durum `NULL` yazılıyor; `ClosedAt` dolu kalıyor.
- **Neden:** Kapatılmış/iptal iş rapor dışına düşmeden "açık" görünür hâle gelebilir, kapanış bilgisi bozulur (veri bütünlüğü — yüksek önem, KRİTİK değil).
- **Mevcut:** P.cs:722-761 (özellikle 754-757). Toplu planlama bu kontrolü yapıyor (P.cs:682-683).
- **Kabul:** (1) `Tamamlandı`/`Kapatıldı`/`İptal` işe tekil plan → 400. (2) Açık işte plan sonrası geçmişte gerçek eski durum yazılı. (3) Zaten `Sahada` olan işin planı değişince durum `Planlandı`'ya geri düşmez (yalnız plan bilgisi güncellenir; VARSAYIM).
- **Roller:** —
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** —

### M01-14 · HATA · Bekleme (hold) akışı geçmişe yazılmıyor ve atlanabiliyor
- **Açıklama:** Hold/release `WorkOrderStatusLogs`'a yazmıyor; aynı işe ikinci bekleme açılabiliyor (çözülünce önceki durum `Beklemede` olarak geri gelebilir); durum açılır listesinden `Beklemede` seçilince neden alınmıyor; neden `prompt()` ile serbest metin.
- **Neden:** Belge §5.10: bekleme nedeni ve geçmişi raporlanmalı; bugün "neden beklendi, ne kadar beklendi" güvenilir değil.
- **Mevcut:** Ops.cs:130-159; app.js:1626 (durum listesinde Beklemede); ops120.js:73.
- **Kabul:** (1) Hold ve release sonrası `/history`'de neden ile satır var. (2) Aktif bekleme varken ikinci hold → 409. (3) `PATCH status` ile `Beklemede` → 400 ("bekleme ucunu kullanın"). (4) Neden sabit listeden (Malzeme / Müşteri Onayı / Teklif / Müşteri Erişimi / Personel / Diğer+açıklama) seçilir. (5) Bekleme süresi (dakika) raporda iş bazında görünür.
- **Roller:** `workorders.edit` veya `operations.manage` (mevcut).
- **Veri:** `OpsHolds` için filtreli tekil indeks `(WorkOrderId) WHERE ReleasedAt IS NULL`.
- **Efor:** S · **Bağımlılık:** M01-06

### M01-15 · HATA · Detay ekranı her kaydette gereksiz durum logu üretiyor
- **Açıklama:** "Kaydet" yalnız atama değişse bile `PATCH status` gönderiyor → aynı durumdan aynı duruma log; tekil atama ise hiç loglanmıyor.
- **Neden:** Geçmiş gürültülü ve yanıltıcı ("X kişisi durumu değiştirdi" görünüyor ama değiştirmedi).
- **Mevcut:** app.js:1668-1674; P.cs:545-570.
- **Kabul:** (1) Durum değişmeden kaydetmede yeni durum logu yok, "Atama değişti" satırı var. (2) Not girildiyse "Not" olay türüyle yazılır.
- **Roller:** —
- **Veri:** M01-06 ile aynı.
- **Efor:** S · **Bağımlılık:** M01-06

### M01-16 · VERİ · İş emri cihazını cihaz kütüğüne bağlama
- **Açıklama:** Açılışta girilen seri no `SecurityDevices` (ve ileride atölye cihazları) içinde aranır; bulunursa `WorkOrderDevices.SecurityDeviceId` ile bağlanır, müşteri/lokasyon önerilir; bulunamazsa "kütükte yok" işaretiyle metin olarak kaydedilir (seri no uydurulmaz — mevcut karar).
- **Neden:** "Hangi seri numaralı cihaza ne yapıldı" sorusu ve tekrar arıza analizi bugün yalnız metin eşleşmesine dayanıyor (Ops.cs:93-96).
- **Mevcut:** `WorkOrderDevices` FK'sız (upd.sql:67-82).
- **Kabul:** (1) Kütükte olan seri ile açılan işte `SecurityDeviceId` dolu ve cihaz geçmişinde iş görünür. (2) Seri no karşılaştırması büyük/küçük harf ve baş/son boşluktan bağımsız, baştaki sıfırlar korunur. (3) Kütükte olmayan seri kaydı engellenmez, "kütükte yok" listesi raporlanabilir.
- **Roller:** `workorders.create`, `devices.view`.
- **Veri:** `WorkOrderDevices` ADD `SecurityDeviceId INT NULL FK`, `IsInRegistry BIT`.
- **Efor:** M · **Bağımlılık:** Cihaz kütüğü modülü

### M01-17 · EKSİK · İş listesi sunucu tarafı filtre ve sayfalama
- **Açıklama:** `GET /api/workorders` açık işleri + son N günde kapanan işleri döndürür; tarih aralığı, birim, kategori, durum grubu, metin arama parametreleri; arşiv için sayfalı sorgu.
- **Neden:** Her ekran açılışında tüm geçmiş iş emirleri (1.324 cihazın yıllık PB işleri dahil) tarayıcıya iniyor (P.cs:3441-3462, ORDER BY ile tam tarama); yıl içinde yavaşlama ve gereksiz veri açığa çıkması.
- **Mevcut:** Parametresiz tam liste.
- **Kabul:** (1) Parametresiz çağrı yalnız açık + son 90 gün kapanan işleri döner (değer ayarlanabilir). (2) `?q=` arama sunucuda çalışır, sonuç ön yüz aramasıyla aynı alanları kapsar. (3) 10.000 iş emri test verisinde liste cevabı < 1 sn (pilot sunucu). (4) Panel KPI'ları bu değişiklikten sonra aynı sayıları verir.
- **Roller:** `workorders.view`.
- **Veri:** İndeks: `WorkOrders(Status, CreatedAt)`, `WorkOrders(ClosedAt)`.
- **Efor:** M · **Bağımlılık:** M01-11 (KPI hesaplarının dönem parametresine geçmesi)

### M01-18 · GÜVENLİK · İş emri izinlerinin ayrıştırılması ve teknisyen kapsamının kimliğe bağlanması
- **Açıklama:** (a) `workorders.edit` tek başına kapatma/iptal/yeniden açma yetkisi vermemeli (M01-09 anahtarları). (b) "Yalnız kendi işini görür" kuralı `RoleName=="Teknisyen"` metnine değil, bir izne/bayrağa (`workorders.own_only`) ve `ErpUserId` eşleşmesine bağlanmalı. (c) Detay/geçmiş/ek uçları aynı erişim fonksiyonunu kullanmalı. (d) İş listesi cevabında müşteri e-posta/telefonu yalnız iş ekibi ve yönetim rollerine dönmeli (VARSAYIM — §4).
- **Neden:** Bugün kapatma iki izinden biriyle mümkün (P.cs:477); farklı rol adıyla tanımlanan teknisyen tüm birim işlerini görür (P.cs:3398, 3499); ad-soyad eşleşmesi kolayca kırılır.
- **Mevcut:** P.cs:477, 3385-3401, 3495-3502.
- **Kabul:** (1) Yalnız `workorders.edit` olan hesapla `Kapatıldı`/`İptal`/`Tekrar Açıldı` → 403. (2) Rol adı "Saha Teknisyeni" olan ama `own_only` bayraklı kullanıcı başka teknisyenin işini `/api/workorders`, `/history`, ek indirme uçlarında göremez (403/listede yok). (3) Aynı ada sahip iki personelden biri, diğerinin işini göremez. (4) Yetki testleri otomatik test olarak kayıtlı.
- **Roller:** Tüm roller; rol şablonları güncellenir.
- **Veri:** İzin kataloğu yeni anahtarlar (Catalog, P.cs:3875-3911).
- **Efor:** M · **Bağımlılık:** M01-09, M01-10

---

## 4. Kullanıcıya sorulacaklar (benim karar veremeyeceğim konular)

1. **Kapatma yetkisi:** Teknisyen işi yalnız `Tamamlandı` yapsın, `Kapatıldı`'yı şef mi versin? Yoksa bazı iş türlerinde (telefonla çözüm, POC) teknisyen/operasyon doğrudan kapatabilsin mi?
2. **POC durumları:** `Telefonla Destek / Uzaktan Müdahale / Yerinde Müdahale` bugün hem iş türü hem durum. Bunları "çözüm kanalı" alanına taşıyıp POC'yi de standart durum akışına almamız uygun mu?
3. **Operasyon uzmanının telefonla çözdüğü iş:** Kendisi "çözüldü" olarak kaydedebilsin mi, yoksa yine bir teknisyene/şefe mi düşsün?
4. **Müşteri onayı:** Hangi iş türlerinde zorunlu olsun? Ekranda dijital imza mı, basılı formun fotoğrafı mı, ikisi de mi kabul? "Onay alınamadı" seçeneği serbest mi, şef onayı mı gerektirsin?
5. **Dosya saklama:** Dosyalar uygulama sunucusunda mı (İT yedeğine dahil edilecek) yoksa ayrı bir dosya sunucusunda mı tutulsun? Dosya başına üst sınır (öneri 10 MB) ve saklama süresi? Fotoğraflarda kişi yüzü/araç plakası olabileceği için KVKK açısından erişimi kimler görsün?
6. **Arıza nedeni listesi:** Birim bazında (Güvenlik / Haberleşme / POC / Mobilite / Araç Takip) arıza nedeni kategorilerini kim verecek? Başlangıç için benim önereceğim kısa liste kullanılabilir mi?
7. **Tekrar arıza / yeniden açma:** Kapanan işte arıza tekrar ederse aynı iş emri mi yeniden açılsın, yoksa yeni iş emri açılıp eskisine "bağlı iş" olarak mı işaretlensin? (Tekrar arıza KPI'sı bu karara göre hesaplanır.)
8. **Talep kanalları:** Telefon / WhatsApp / E-posta / Sahada bildirildi / Bakım otomatik — eksik veya fazla kanal var mı?
9. **"Plansız Bakım" iş türü** (Güvenlik ve Haberleşme): servis/arıza sayaçlarına mı, planlı bakım sayaçlarına mı girsin?
10. **Kapalı işte düzeltme:** Kapanmış iş emrinde müşteri/lokasyon/konu düzeltmesini kim yapabilsin (yalnız müdür mü)?
11. **Müşteri iletişim bilgisi görünürlüğü:** Depo, muhasebe, kiralama gibi salt-görüntüleme rolleri iş listesinde müşteri telefon/e-postasını görsün mü?
12. **Durum kataloğu:** Durum listesi kodda sabit mi kalsın, yoksa yönetici ekranından eklenebilir mi olsun? (Öneri: kodda sabit — raporlar ve geçiş kuralları buna bağlı.)

---

## 5. Varsayımlar

- Rol/sorumluluk tablosu (§2.1) organizasyon şeması gelmeden, mevcut `Catalog.RoleDefaults` (P.cs:3921-3935) ve personel ünvanlarından (upd.sql:373-420) türetilmiştir.
- Mevcut durum adları değiştirilmeden korunur; böylece eski kayıtlar için veri göçü gerekmez.
- Müşteri ana verisi (müşteri/lokasyon tablosu) bu modülün kapsamı dışında ayrı bir modül/madde olarak ele alınacaktır; bu tasarım serbest metin müşteri alanıyla da çalışır.
- SLA motoru, canlı sayaç ve planlama takvimi kendi modüllerinde tasarlanır; burada yalnız iş emri yaşam döngüsüne değen noktalar alındı.
- Servis formu çıktısı için yeni NuGet bağımlılığı eklemeden tarayıcı yazdırma (HTML → PDF) kullanılacaktır.
- Tüm yeni SQL değişiklikleri mevcut stilde idempotent `ZZ_V1xx_*.sql` scriptleriyle, yalnız ekleme (ADD COLUMN / CREATE TABLE) olarak yapılır; mevcut kayıt silinmez.
