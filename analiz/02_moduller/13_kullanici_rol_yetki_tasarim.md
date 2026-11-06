# M13 — Kullanıcı, Rol, Yetki ve Personel/Organizasyon — Gereksinim Tasarımı

> **Kapsam:** Yalnızca teknik servis. Konular: rol şablonları, kişi bazlı izin, birim kapsamı, personel ile kullanıcı bağlantısı, teknisyen kimliğiyle atama, yetki devri ve yükseltme önlemi, denetim kaydı, işten çıkışta erişimin kapatılması.
> **Kaynak:** `kaynak/V1_20_1_orijinal/DengeERP.Api` (salt okunur). Kısaltmalar: **P.cs** = `Program.cs`, **upd.sql** = `Database/DengeERP_Update.sql`, **v15.sql** = `Database/DengeERP_V15_Schema.sql`.
> **İlgili belgeler:** `01_denetim/A1_guvenlik.md` (A1-01, A1-04, A1-05, A1-07, A1-11, A1-13, A1-16), `02_moduller/01_is_emirleri_tasarim.md` (M01-10, M01-18), `02_planlama_tasarim.md` (M02-03, M02-14), `09_saha_zaman_tasarim.md` (M09-13, M09-16).
> **Organizasyon şeması henüz gelmedi.** Bu nedenle rol ve sorumluluk önerileri **varsayımdır** (§5).

Bu modül diğer modüllerin dayandığı **kimlik altyapısıdır**. M01-10, M02-03 ve M09-13, atama ve süre kayıtlarını `PersonnelId` üzerine taşımayı istiyor. Bu belge o kimliğin nasıl tanımlanacağını, nasıl bağlanacağını ve nasıl kapatılacağını tarif eder.

---

## 1. Mevcut durum (koddan çıkarıldı)

### 1.1 Veri modeli

| Tablo | Önemli alanlar | Not |
|---|---|---|
| `dbo.ErpUsers` (upd.sql:141-158) | `UserId`, `Username` UNIQUE, `PasswordHash/Salt` (PBKDF2-SHA256, 120.000 tur, P.cs:2827-2844), `FullName`, `RoleName` (serbest metin), `AllowedUnits` (`|` ile ayrılmış metin), `Permissions` (`|` ile ayrılmış metin, `*` tüm izinler), `IsActive`, `MustChangePassword`, `CreatedAt`, `UpdatedAt` | Son giriş zamanı, başarısız deneme sayısı ve kilit alanı yok. |
| `dbo.Personnel` (upd.sql:348-369) | `PersonnelId`, `FullName`, `DepartmentName`, `AdditionalDepartments` (metin), `Title` (serbest), `UnitCode` (tek birim), `ManagerName` (**ad metni**), `StartDate`, `EndDate`, `IsActive`, `ErpUserId` (FK, **tekil değil**), `Notes` | Sicil no yok. Aynı ad iki kez girilebilir. |
| `dbo.WorkOrderAssignments` | `AssignedName` (**ad metni**), `AssignmentRole` ('Şef'/'Teknisyen'), `IsActive` (P.cs:3338-3347) | Personel veya kullanıcı kimliği tutulmuyor. |
| `dbo.WorkOrderLiveSessions` | `TechnicianUserId` (FK) **ve** `TechnicianName` | Tek kimlik bağlı tablo budur. |
| `dbo.WorkOrderTimeLogs` | `TechnicianName` (metin) | Çakışma kontrolü ada göre yapılıyor (P.cs:1960-1963, 2040-2041). |

- **Başlangıç verisi:** 47 gerçek personel SQL içine gömülü (upd.sql:372-426). Kullanıcı ile personel, **ad soyad birebir eşleşirse** bağlanıyor (upd.sql:428-432).
- **Gömülü isim listesi:** `app.js:23-29` içinde birim bazlı şef/teknisyen adları var (`personnelFallback`). `app.js` anonim erişilen statik bir dosyadır (M02-14).
- **İzin dağıtımı:** Yeni modül izinleri eski kullanıcılara **rol adına göre** SQL ile ekleniyor (v15.sql:146-171). Kişiye özel profil, rol adı aynıysa yine değişiyor.

### 1.2 API uçları

| Uç | İzin | Satır | Gözlem |
|---|---|---|---|
| `POST /api/auth/login` | anonim | P.cs:67-99 | Deneme sınırı yok. Belirteç 32 bayt rastgele. Oturum bellekte (`ConcurrentDictionary`, P.cs:21), **süre sonu yok**. |
| `GET /api/auth/me`, `POST /api/auth/logout` | oturum | P.cs:101-112 | — |
| `POST /api/auth/change-password` | oturum | P.cs:114-137 | **Mevcut şifre sorulmuyor.** Uzunluk dışında kural yok. |
| `GET /api/meta/permissions` | oturum | P.cs:139-151 | İzin kataloğu, rol şablonları, birimler, departmanlar. |
| `GET /api/users` | `users.manage` | P.cs:174-201 | Tüm kullanıcılar, birim filtresi yok. |
| `POST /api/users` | `users.manage` | P.cs:203-243 | İzin listesi **doğrulanmıyor** (`*` dahil her metin kabul). Birim boşsa tüm birimler atanıyor. |
| `PUT /api/users/{id}` | `users.manage` | P.cs:245-319 | Kendine veya başkasına `*` ve `RoleName="Admin"` verilebilir. Admin hesabı düzenlenebilir. Açık oturum güncelleniyor (P.cs:297-298). |
| `PATCH /api/users/{id}/status` | `users.manage` | P.cs:321-336 | Yalnız kendini pasif yapma engelli. **Pasifleştirilen kullanıcının açık oturumu düşmüyor.** |
| `POST /api/users/{id}/reset-password` | `users.manage` | P.cs:338-357 | Geçici şifreyi yönetici yazıyor. **Oturum düşmüyor.** Admin'in şifresi de sıfırlanabilir. |
| `GET /api/personnel` | `personnel.view` | P.cs:1733-1768 | Tüm personel, birim kapsamı yok. |
| `POST /api/personnel` | `personnel.manage` (+ hesap için `users.manage`) | P.cs:1770-1832 | Aynı işlemde hesap açılabiliyor. Rol boşsa "Operasyon Uzmanı" atanıyor. **Birim boşsa `[]`, yani tüm birimler** (P.cs:1797). |
| `PUT /api/personnel/{id}` | `personnel.manage` | P.cs:1834-1860 | Ad değişikliği **kullanıcı kaydına yansımıyor**. `ErpUserId` bağlama ya da ayırma yok. |
| `PATCH /api/personnel/{id}/status` | `personnel.manage` | P.cs:1862-1903 | Pasif yapılınca bağlı hesap da pasif oluyor ve **oturumları düşüyor**. Hedef hesabın yetkisine bakılmıyor (Admin de kapatılabiliyor, A1-07). |
| `POST /api/timetracking/sessions/{id}/cancel` | `workorders.assign` **veya `users.manage`** | P.cs:2080-2084 | Kullanıcı yönetimi izni operasyonel yetki olarak kullanılıyor (M09-16). |

### 1.3 Yetki yardımcıları (P.cs:2804-2825)

- `Can()`: `*` veya izin listesinde varsa geçer.
- `IsAdmin()`: `*` **veya `RoleName=="Admin"`**. Rol adı tek başına birim kapsamını aşıyor.
- `UnitAllowed()`: Admin **veya `AllowedUnits` boşsa** tüm birimler (güvensiz varsayılan, A1-13).
- `GetRoleDefaults()`: Bilinmeyen rol adı için `["workorders.view"]`.
- **Teknisyen kapsamı:** `RoleName=="Teknisyen"` ise yalnız `AssignedName` içinde **kendi `FullName` metni** geçen işler görünür (P.cs:3398-3400, 3499-3500). Canlı sayaç ve manuel süre de aynı ad eşleşmesine bağlı (P.cs:1943-1948, 2120, 2133-2138).
- **Oturum nesnesi** (`SessionUser`, P.cs:3799) girişte kopyalanıyor. İzin değişikliği yalnız `PUT /api/users` ile oturuma yansıyor.
- **İlk Admin:** Boş veritabanında en az 14 karakterlik parola ile `admin` hesabı oluşuyor (P.cs:3271-3295). Bu iyi bir uygulama.

### 1.4 Rol şablonları (Catalog, P.cs:3871-3936)

- 12 rol ve 34 izin anahtarı var. Rol yalnızca **varsayılan şablondur**. Kişi bazında izin ve birim değiştirilebilir (karar ile uyumlu).
- `users.manage` izni Admin dışında **Üst Yönetim, Teknik Servis Müdürü, Müdür Yardımcısı ve İK** rollerinde de var.
- `operations.manage`, `warehouse.manage` ve `finance.costs.manage` izinleri **Admin dışındaki hiçbir şablonda yok**. Depo rolü stok hareketi yapamıyor. Müdür SLA'yı ve bekleme nedenini yönetemiyor.
- Şef şablonunda `personnel.view` yok. Bu yüzden atama listesinde personel tablosu boş geliyor (aşağıya bakın).

### 1.5 Ön yüz (app.js)

- **Menü:** "Personel / Organizasyon" (`personnel.view`) ve "Kullanıcı / Yetki" (`users.manage`) (app.js:200-201).
- **Kullanıcı ekranı** (app.js:1221-1262): yeni kullanıcı, liste, düzenleme penceresi, rol değişince şablon izinlerini doldurma (1247), pasif/aktif ve geçici şifre (`prompt()` ile, 2027-2028). Admin hesabının yalnız kullanıcı adı salt okunur (1236).
- **Personel ekranı** (app.js:1037-1084, 2010-2020): departman filtresi, isteğe bağlı hesap açma, pasif/aktif. Mevcut personele mevcut hesabı bağlama yok.
- **Atama aday listesi** (app.js:1593-1606): Aktif kullanıcılar (yalnız `users.manage` sahibine yüklenir, 145), personel (yalnız `personnel.view` sahibine yüklenir, 151) ve gömülü `personnelFallback` birleştiriliyor. Şef/teknisyen ayrımı **ünvan metni regex'i** ile yapılıyor (`/takım lideri|yönetici|müdür/`, `/teknisyen|mühendis|.../`). **Şef rolündeki kullanıcı pratikte yalnız koddaki sabit listeyi görüyor.**
- **Zorunlu şifre değişikliği** yalnız istemcide uygulanıyor (app.js:2040). Belirteç `localStorage` içinde (app.js:35, 2032).

### 1.6 Kodda olan iş kuralları (özet)

1. Kullanıcı adı tekil, şifre en az 8 karakter, PBKDF2 ile saklanıyor.
2. Kendi hesabını pasif yapamazsın (yalnız kullanıcı ekranında).
3. Personel pasif → bağlı hesap pasif ve oturumları düşer (P.cs:1890-1899). **Bu, kodda işten çıkış için var olan tek mekanizmadır.**
4. Rol değişince izinler istemcide şablona göre doldurulur. Sunucuda izin listesi boş gelirse şablon atanır.
5. Denetim kaydı yok. Yalnızca iş emri durum günlüğü (`WorkOrderStatusLogs`) kimin ne yaptığını tutuyor.

---

## 2. Olması gereken (hedef tasarım)

### 2.1 Temel ilke: tek kişi = tek kimlik

```text
Personnel (kişi, ana kimlik)  1 ──── 0..1  ErpUsers (giriş hesabı)
   │  PersonnelId                              UserId
   │  FieldRole: Şef / Teknisyen / Stajyer / Ofis / Yok
   │  UnitCode, ManagerPersonnelId
   ▼
WorkOrderAssignments.PersonnelId, WorkOrderTimeLogs.PersonnelId, LiveSessions.TechnicianUserId
```

- Adı, birimi, yöneticisi ve saha rolü **personel kartında** tutulur. Hesap yalnız giriş ve izin taşır. `ErpUsers.FullName`, bağlı personelden kopyalanır (tek kaynak).
- Atama, görünürlük ve süre kuralları **ada değil kimliğe** bakar. Ad yalnızca ekranda gösterilir.
- Hesabı olmayan personel (ör. stajyer) atanabilir, ama süre kaydedemez. Ekranda bu uyarılır (M01-10 ile uyumlu).

### 2.2 Roller ve sorumluluklar (VARSAYIM: organizasyon şeması gelince doğrulanacak)

| Rol (şablon) | Bu modülde yapabildikleri | Yapamadıkları |
|---|---|---|
| **Admin (İT / Sistem Yöneticisi)** | Hesap açma ve kapatma, tüm izinler, `users.manage` ve hassas izinleri verme, denetim kaydını görme | — (en az bir aktif Admin kalmalı) |
| **Teknik Servis Müdürü** | Kendi birimlerinde hesap açma, kendi sahip olduğu izinler kadar izin verme, vekâlet verme, erişim gözden geçirme | `*`, `users.manage` ve `finance.prices.view` verme (önerilen; §4 S1-S2) |
| **Müdür Yardımcısı** | Personel ve görüntüleme, vekâlet önerme | Hesap ve yetki değiştirme (önerilen; bugün `users.manage` var) |
| **Şef** | Kendi biriminin aktif personelini atama listesinde görme, ekibinin müsaitlik ve özet bilgisi | Personel kartı düzenleme, yetki |
| **Teknisyen** | Kendi profilini ve kendi işlerini görme, şifre değiştirme | Başkasının işleri ve süreleri |
| **İnsan Kaynakları** | Personel kartı açma ve düzenleme, **işten çıkış başlatma** (erişimi kapatır) | İzin verme ve hesabı yeniden açma (önerilen; bugün `users.manage` var) |

Görev ayrılığı kuralı: **Erişimi kapatmak** kolay ve hızlı olmalı (İK ve Müdür yapabilir). **Erişim açmak ve genişletmek** dar bir gruba ait olmalı.

### 2.3 Tutulması gereken veriler (yalnız değer katanlar)

- **Personnel:** `SicilNo` (isteğe bağlı, tekil), `FieldRole`, `ManagerPersonnelId`, `EndDate`, `OffboardedByUserId`, `OffboardReason` (serbest değil, kısa liste).
- **ErpUsers:** `LastLoginAt`, `FailedLoginCount`, `LockedUntil`, `PasswordChangedAt`, `AllUnits BIT` (boş liste artık "tümü" anlamına gelmez).
- **UserTemporaryGrants:** vekâlet ve geçici yetki (kime, hangi izinler ve birimler, başlangıç, bitiş, gerekçe, veren).
- **SecurityAuditLog:** yalnız eklenen kayıt (kim, ne zaman, hangi işlem, hedef, önce/sonra özeti, IP).

### 2.4 Akışlar

**İşe giriş:** İK personel kartını açar (`FieldRole`, birim, yönetici) → yetkili kişi hesabı açar ya da mevcut hesabı bağlar → rol şablonu seçilir, gerekirse kişi bazında izin eklenip çıkarılır → sistem tek kullanımlık geçici şifre üretir → ilk girişte şifre değişimi sunucuda zorunludur.

**Rol veya birim değişikliği:** Kart güncellenir → hesap izinleri şablondan farkıyla gösterilir → kaydedilince açık oturum yeni izinlerle yenilenir → denetim kaydı yazılır.

**Vekâlet:** Şef izne çıkar → Müdür, başka bir kullanıcıya 1-30 günlük ek birim ve izin verir → süre bitince ek yetki kendiliğinden düşer → kayıt kalır.

**İşten çıkış:** İK "İşten Çıkış" başlatır → sistem önizleme gösterir (açık atamalar, aktif sayaç, gelecek planlar, açık atölye kayıtları) → onay ile tek transaction içinde personel pasif olur, hesap pasif olur, oturumlar düşer, aktif sayaç "işten çıkış" gerekçesiyle kapatılır → açık işler "Yeniden atanacak" listesine düşer (otomatik silinmez) → hesabı yeniden açmayı yalnız Admin yapabilir.

### 2.5 Doğrulamalar

1. İzin anahtarı katalogda yoksa 400 döner. `*` ve `RoleName="Admin"` yalnız Admin tarafından verilebilir.
2. Kimse sahip olmadığı bir izni veya birimi veremez (alt küme kuralı).
3. Kimse kendi izinlerini veya birimlerini genişletemez.
4. Kendinden **daha geniş** yetkili bir hesabı düzenleyemez, pasifleştiremez, şifresini sıfırlayamaz.
5. Son aktif Admin pasifleştirilemez ve yetkisi düşürülemez.
6. Bir personel en fazla bir hesaba, bir hesap en fazla bir personele bağlıdır.
7. `FieldRole` Teknisyen veya Şef olan **aktif** personelin bir birimi olmalıdır. Bağlı hesabın birimleri bu birimi kapsamalıdır (uyarı).
8. Pasif personel atama listesinde görünmez. Pasif personele yeni atama yapılırsa 400 döner.

### 2.6 Raporlar ve KPI'lar

| Rapor / KPI | Amaç |
|---|---|
| **Erişim gözden geçirme listesi**: hassas izin sahipleri (`*`, `users.manage`, `finance.prices.view`, `finance.costs.manage`, `reports.export`), şablondan sapan hesaplar, 60 günden uzun süredir giriş yapmayanlar | Üç ayda bir yönetici onayı; KVKK erişim kontrolü kanıtı |
| **Kimlik tutarlılığı**: hesabı olmayan teknik servis personeli, personeli olmayan hesaplar, ad uyuşmazlıkları, eşleşmemiş eski atama adları | Kimliğe geçişin ilerlemesini ölçer |
| **İşten çıkış kapanış süresi**: `EndDate` ile hesabın kapanması arasındaki süre (hedef: 0 gün), çıkıştan sonra hâlâ açık iş sayısı | Erişim kapatma disiplini |
| **Süresi dolan vekâletler** (önümüzdeki 7 gün) | Unutulan geçici yetkiyi önler |
| **Başarısız giriş ve kilitlenen hesaplar** (son 30 gün) | Saldırı veya unutulan şifre belirtisi |

---

## 3. Fark listesi (öncelik sırası: YENİ → EKSİK/HATA/VERİ → GÜVENLİK)

> **KRİTİK işaretli iki madde var:** M13-12 (yetki yükseltme, A1-01) ve M13-13 (kapatılan hesabın açık oturumla çalışmaya devam etmesi). Kullanıcının öncelik sırasında güvenlik en sonda gelse de, **bu iki madde diğerlerinden önce ya da en geç ilk sürümle birlikte** yapılmalıdır. İkisi de küçük ya da orta efordur.

### M13-01 · YENİ · Personel kartı ana kimlik: hesap bağlama, ayırma ve ad senkronu
- **Açıklama:** Personel kartında "ERP Hesabı" bölümü olur: "Yeni hesap aç", "Mevcut hesabı bağla" (bağsız hesaplar listesinden), "Bağlantıyı kaldır". Uçlar: `POST /api/personnel/{id}/link-user {userId}` ve `DELETE /api/personnel/{id}/link-user`. Personel adı değişince bağlı `ErpUsers.FullName` aynı transaction içinde güncellenir. Kullanıcı ekranında ad alanı salt okunur olur ("Personel kartından değiştirilir"). Bağlı hesabın açık oturumundaki `FullName` de yenilenir.
- **Gerekçe:** Bugün personel ve kullanıcı adı iki ayrı kopya. Biri değişince teknisyen kendi işini göremez, sayaç başlatamaz (P.cs:3398-3400, 1943-1948). Mevcut personele mevcut hesap yalnız ad birebir eşleşirse SQL ile bağlanmış (upd.sql:428-432). Arayüzden bağlama yapılamıyor.
- **Mevcut:** P.cs:1834-1860 (PUT personelde `ErpUserId` yok, ad kullanıcıya yansımıyor); P.cs:245-319 (kullanıcı adı ayrı düzenleniyor); app.js:1037-1084.
- **Kabul:** (1) Bağsız bir hesap, personel kartından bağlanır ve listede "ERP" sütununda görünür. (2) Zaten bağlı bir hesap ikinci personele bağlanmak istenince 409 döner. (3) Personelin adı "Ali Kaya" iken "Ali Kaya Yılmaz" yapılınca `ErpUsers.FullName` de değişir; teknisyen **çıkış yapmadan** işlerini görmeye devam eder (M13-02 sonrası kimlikle). (4) Kullanıcı düzenleme ekranında bağlı hesabın adı değiştirilemez (sunucu 400 döner). (5) Bağlantı kaldırılınca hesap pasif olmaz; yalnız bağ kopar ve denetim kaydı yazılır.
- **Roller:** Bağlama ve ayırma için `users.manage`. Ad değişikliği için `personnel.manage`.
- **Veri:** `Personnel.ErpUserId` üzerine filtreli UNIQUE index (`WHERE ErpUserId IS NOT NULL`). Yeni sütun yok.
- **Efor:** M · **Bağımlılık:** M13-10 (önce mükerrer bağlantılar temizlenmeli).

### M13-02 · YENİ · Saha rolü ve atanabilir personel servisi (kimlikle atama altyapısı)
- **Açıklama:** Personel kartına `FieldRole` alanı eklenir: Şef / Teknisyen / Stajyer / Ofis / Yok. Ünvan regex'i ile tahmin kaldırılır. Yeni uç `GET /api/personnel/assignable?unit=` eklenir. Uç `workorders.assign` veya `workorders.plan` sahibine açıktır ve aktif, o birimdeki ya da ek birimi o birim olan personeli döner (`PersonnelId`, ad, `FieldRole`, hesap var mı). Sunucu tarafında tek bir yardımcı fonksiyon yazılır: `IsAssignedTo(SessionUser, workOrderId)`. Bu fonksiyon `ErpUserId → PersonnelId → WorkOrderAssignments.PersonnelId` zincirine bakar. Görünürlük (`FilterWorkOrdersForUser`, `CanAccessWorkOrderAsync`), sayaç ve süre uçları bu fonksiyonu kullanır. Gömülü `personnelFallback` silinir.
- **Gerekçe:** Şef şablonunda `personnel.view` yok ve kullanıcı listesi yalnız `users.manage` sahibine yükleniyor (app.js:145, 151). Bu yüzden şefin atama listesi koddaki sabit isimlerden geliyor (app.js:23-29, 1604). Yeni gelen teknisyen koda müdahale edilmeden atanamıyor. Ayrılan kişi ise listede kalıyor. Bu madde M01-10, M02-03 ve M09-13'ün ortak altyapısıdır; bu üç madde tüketici, bu madde sağlayıcıdır.
- **Mevcut:** app.js:1593-1606 (regex ile şef/teknisyen ayrımı), P.cs:3385-3401, 3495-3502 (ad eşleşmesi).
- **Kabul:** (1) `personnel.view` izni olmayan Şef hesabı, atama formunda kendi biriminin aktif teknisyenlerini görür. (2) Pasif personel listeye gelmez. (3) Ünvanı "Sistem Mühendisi" olan ama `FieldRole=Teknisyen` olan kişi teknisyen listesinde çıkar. Ünvanında "müdür" geçen ama `FieldRole=Ofis` olan kişi şef listesinde çıkmaz. (4) `app.js` içinde gerçek kişi adı kalmaz (M02-14). (5) Uç fiyat, maliyet ve kişisel iletişim alanı döndürmez. (6) Birim kapsamı dışındaki birim için istek 403 döner.
- **Roller:** Şef, Müdür (okuma). `FieldRole` düzenleme için `personnel.manage`.
- **Veri:** `Personnel.FieldRole NVARCHAR(20) NULL` + CHECK. Mevcut kayıtlar için ünvandan **öneri** üretilir, İK onaylar (otomatik yazılmaz).
- **Efor:** M · **Bağımlılık:** M13-01. Atama tablosu değişikliği M01-10 ve M02-03 kapsamındadır.

### M13-03 · YENİ · Tek adımda işten çıkış (offboarding) akışı
- **Açıklama:** Personel kartında "İşten Çıkış" düğmesi olur. Önce `GET /api/personnel/{id}/offboarding-preview` çağrılır. Bu uç kişinin açık iş atamalarını, aktif sayacını, bugün ve sonrası planlarını, açık atölye kayıtlarını ve bağlı hesabı döner. Onay için `POST /api/personnel/{id}/offboard {endDate, reason}` kullanılır. Bu işlem tek transaction içinde şunları yapar: personel pasif ve `EndDate`; hesap pasif; tüm oturumlar düşer; aktif canlı sayaç "İşten çıkış" gerekçesiyle kapatılır ve yönetici incelemesine işaretlenir; geçici yetkiler (M13-04) iptal edilir; denetim kaydı yazılır. Açık atamalar **silinmez**. Atamalar "Yeniden atanacak işler" listesine düşer ve şefin ana panelinde sayı olarak görünür. Hesabı yeniden açmak yalnız Admin'e açıktır ve yeni geçici şifre ister.
- **Gerekçe:** Bugün personeli pasif yapmak hesabı kapatıyor (P.cs:1890-1899). Ancak açık işler ayrılan kişinin adında kalıyor, aktif sayacı açık kalıyor ve kullanıcı ekranından "Aktif" düğmesiyle hesap tekrar açılabiliyor. Ayrılan teknisyenin işleri sessizce sahipsiz kalıyor.
- **Mevcut:** P.cs:1862-1903; app.js:2020 (personel pasif düğmesi, tarih = bugün).
- **Kabul:** (1) 3 açık işi ve aktif sayacı olan teknisyen için önizleme 3 iş ve 1 sayaç gösterir. (2) Onaydan sonra kişinin eski belirteciyle yapılan her istek 401 döner. (3) Sayaç kapanır; süre kaydı "işten çıkış" notu ve inceleme bayrağıyla oluşur, sıfır sayılmaz. (4) 3 iş "Yeniden atanacak" listesinde görünür ve yeniden atanınca listeden düşer. (5) İK hesabıyla hesabı tekrar aktif etme denemesi 403 döner, Admin ile yapılabilir. (6) Kişi atama listelerinde görünmez; geçmiş raporlarda adıyla görünmeye devam eder.
- **Roller:** Başlatma: `personnel.manage` (İK, Müdür). Yeniden açma: Admin.
- **Veri:** `Personnel.OffboardReason NVARCHAR(40) NULL`, `OffboardedByUserId INT NULL`. Canlı sayaç tablosunda `NeedsReview BIT` (M09-05 ile ortak olabilir).
- **Efor:** M · **Bağımlılık:** M13-02 (açık işleri kimlikle bulmak için; yoksa ad eşleşmesiyle geçici çözüm), M13-13.

### M13-04 · YENİ · Süreli vekâlet ve geçici yetki
- **Açıklama:** Kullanıcı kartında "Geçici Yetki Ver" bölümü olur. Ek izinler ve ek birimler, başlangıç ve bitiş tarihi (en fazla 30 gün) ve zorunlu gerekçe girilir. Oturum yüklenirken aktif geçici yetkiler kalıcı izinlerle **birleştirilir**. Bitiş tarihinden sonra yetki kendiliğinden düşer; ilk istekte yeniden hesaplanır. Kalıcı izin listesi değişmez. Alt küme kuralı (M13-12) burada da geçerlidir.
- **Gerekçe:** Şef izne veya rapora çıkınca bugün tek yol başka kullanıcıya kalıcı izin eklemek. Bu izin geri alınmayı unutuluyor ve zamanla yetki birikiyor. Küçük ekipte bu durum sık yaşanır (Haberleşme ve POC'un tek şefi var, upd.sql:400-405).
- **Mevcut:** Yok.
- **Kabul:** (1) 3 günlük "Güvenlik Sistemleri / `workorders.assign`" vekâleti verilen kullanıcı, bu süre içinde o birime atama yapabilir. (2) Bitişten sonraki ilk istekte aynı işlem 403 döner (sunucu yeniden başlatılmadan). (3) Veren kişinin sahip olmadığı bir izin vekâlete eklenince 403 döner. (4) Kullanıcı kartında aktif vekâlet bitiş tarihiyle görünür. (5) Vekâlet erken iptal edilebilir. Verme ve iptal denetim kaydına yazılır.
- **Roller:** `users.manage` veya önerilen yeni `users.delegate` (yalnız Müdür; §4 S6).
- **Veri:** `UserTemporaryGrants(GrantId, UserId, Permissions, Units, StartsAt, EndsAt, Reason, GrantedByUserId, RevokedAt, RevokedByUserId, CreatedAt)`.
- **Efor:** M · **Bağımlılık:** M13-12, M13-13 (oturumun izinleri canlı hesaplaması).

### M13-05 · YENİ · Erişim gözden geçirme ve kimlik tutarlılığı raporu
- **Açıklama:** "Kullanıcı / Yetki" menüsüne "Gözden Geçirme" sekmesi eklenir. Sekmede iki liste vardır. **(a) Erişim:** hassas izin sahipleri, rol şablonundan sapan izinler (fazla ve eksik ayrı), son giriş tarihi, 60 günden uzun süredir giriş yapmayanlar, pasif personele bağlı aktif hesaplar. **(b) Kimlik:** hesabı olmayan `FieldRole` Teknisyen/Şef personel, personeli olmayan hesaplar, ad uyuşmazlıkları, eşleşmemiş eski atama adları (M13-10). Yönetici her satırı "Gözden geçirildi" olarak işaretleyebilir (tarih ve kişi tutulur). Excel çıktısı alınabilir.
- **Gerekçe:** Kişi bazlı izin kararı esneklik sağlıyor ama izlenmezse yetki birikir. Ücret ve fiyat görme izninin (`finance.prices.view`) kimde olduğu tek bakışta görülmeli. KVKK için periyodik erişim kontrolü kanıtı gerekir.
- **Mevcut:** Kullanıcı listesinde yalnız rol, birim ve durum var (app.js:1225). `LastLoginAt` alanı yok.
- **Kabul:** (1) Şablonu Şef olan ama `finance.prices.view` izni eklenmiş hesap "Şablondan fazla: finance.prices.view" olarak listelenir. (2) Pasif personele bağlı aktif hesap kırmızı listelenir (M13-13 sonrası sıfır olmalı). (3) Son girişi 61 gün önce olan hesap listede görünür. (4) "Gözden geçirildi" işareti tarih ve kişiyle saklanır, sonraki raporda görünür. (5) Rapor yalnız `users.manage` sahibine açıktır.
- **Roller:** Admin, Teknik Servis Müdürü.
- **Veri:** `ErpUsers.LastLoginAt DATETIME2 NULL`; `AccessReviews(ReviewId, UserId, ReviewedByUserId, ReviewedAt, Note)`.
- **Efor:** M · **Bağımlılık:** M13-06 (son giriş ve değişiklik geçmişi), M13-07 (şablon karşılaştırması).

### M13-06 · YENİ · Güvenlik denetim kaydı (SecurityAuditLog) ve görüntüleme ekranı
- **Açıklama:** Yalnız ekleme yapılan bir tablo kurulur. Kaydedilen olaylar: giriş başarılı ve başarısız, çıkış, şifre değişikliği ve sıfırlama, hesap açma, rol/izin/birim değişikliği (önceki ve sonraki listenin farkı), hesap aktif/pasif, personel bağlama ve ayırma, işten çıkış, vekâlet verme ve iptal, kilitlenme. Admin için tarih, kişi, hedef ve olay türüne göre filtreli bir ekran yapılır. Uygulamada güncelleme veya silme ucu bulunmaz. SQL tarafında uygulama hesabına bu tabloda `UPDATE/DELETE` yetkisi verilmez (İT ile).
- **Gerekçe:** Bugün kimin kime hangi yetkiyi verdiği, kimin hesabı kapattığı ve şifreyi kimin sıfırladığı hiçbir yerde tutulmuyor (A1-16). Yetki sızıntısı olursa geriye doğru inceleme yapılamıyor.
- **Mevcut:** Yok. Yalnız `UpdatedAt` sütunu güncelleniyor (P.cs:273, 331, 350).
- **Kabul:** (1) `PUT /api/users/5` ile `finance.prices.view` eklenince kayıtta işlemi yapan, hedef, eklenen izin ve saat yer alır. (2) 3 başarısız giriş 3 ayrı kayıt oluşturur; şifre metni hiçbir kayıtta bulunmaz. (3) Ekranda "son 7 gün, hedef = Ali Kaya" filtresi çalışır. (4) Uygulama üzerinden kayıt silinemez; SQL'de uygulama hesabıyla `DELETE` denemesi yetki hatası verir (İT doğrulaması). (5) Kayıtlar saklama süresi (§4 S8) dolmadan silinmez.
- **Roller:** Görüntüleme: Admin (önerilen yeni izin `audit.view`).
- **Veri:** `SecurityAuditLog(AuditId BIGINT, At DATETIME2, ActorUserId INT NULL, ActorName, Action NVARCHAR(50), TargetType, TargetId, Summary NVARCHAR(1000), Ip NVARCHAR(45))` + `(At)`, `(TargetType, TargetId)` index'leri.
- **Efor:** M · **Bağımlılık:** —

### M13-07 · EKSİK · Rol şablonlarının teknik servis gerçeğine göre düzeltilmesi
- **Açıklama:** (a) Eksik izinler şablonlara eklenir. **Depo** şablonuna `warehouse.manage`, **Teknik Servis Müdürü** şablonuna `operations.manage` ve `finance.costs.manage` (VARSAYIM), **Şef** şablonuna `operations.manage` (bekleme nedeni, VARSAYIM) eklenir. (b) `users.manage` İK ve Müdür Yardımcısı şablonlarından çıkarılır (§4 S1). İK'ya personel ve işten çıkış kalır. (c) Teknisyen kapsamı rol adından ayrılır: `workorders.own_only` izni (M01-18) Teknisyen ve Stajyer şablonlarına eklenir. (d) Rol adı serbest metin olmaktan çıkar ve sunucuda katalogdaki rollerden biri olmak zorunda olur. (e) Kullanıcı kartında "Şablondan farklı" rozeti ve "Şablona göre sıfırla" düğmesi bulunur. (f) Yeni izinler eski hesaplara **rol adına göre toplu SQL ile eklenmez**; yönetici M13-05 raporundan bakarak tek tek verir (belgedeki karar ile uyumlu).
- **Gerekçe:** `operations.manage`, `warehouse.manage` ve `finance.costs.manage` hiçbir şablonda yok (P.cs:3921-3935). Bu yüzden V1.20'deki SLA, stok ve maliyet ekranları Admin dışında kimse tarafından kullanılamıyor ya da tek tek elle izin veriliyor. Teknisyen kuralı "Teknisyen" rol adına bağlı; "Kıdemli Teknisyen" adıyla açılan hesap tüm birimin işlerini görür (P.cs:3398, 3499). v15.sql:146-171'deki toplu ekleme, kişiye özel profilleri de değiştiriyor.
- **Mevcut:** P.cs:3921-3935, 2804; v15.sql:146-171; app.js:1247.
- **Kabul:** (1) Depo şablonuyla açılan hesap `POST /api/ops/stock/movement` çağrısını yapabilir. (2) Katalogda olmayan rol adıyla kullanıcı oluşturma 400 döner. (3) Rol adı "Teknisyen" olmayan ama `workorders.own_only` izni olan hesap yalnız kendi işlerini görür. (4) Şablondan izni eksik veya fazla olan hesapta rozet görünür. "Şablona göre sıfırla" sonrası rozet kalkar ve değişiklik denetim kaydına yazılır. (5) Yeni şablon değişikliği mevcut hesapların izinlerini **değiştirmez** (sürüm geçişinde SQL ile doğrulanır).
- **Roller:** Tüm roller etkilenir. Şablon değişikliği kod ile yapılır (veritabanında düzenlenebilir şablon önerilmez; küçük ekip için gereksiz karmaşıklık).
- **Veri:** Yok (Catalog kodda). Yeni izin anahtarları: `workorders.own_only`, `audit.view`, isteğe bağlı `users.delegate`.
- **Efor:** S · **Bağımlılık:** M01-18 (`own_only` uygulaması).

### M13-08 · EKSİK · Birim kapsamının açık tanımlanması ve personel listesinde birim filtresi
- **Açıklama:** (a) "Tüm birimler" ayrı bir bayrak olur (`ErpUsers.AllUnits`). Boş birim listesi artık **hiçbir birim** anlamına gelir. Mevcut boş kayıtlar geçişte `AllUnits=1` yapılır ve M13-05 raporunda gösterilir. (b) Hesap açma ve personel ile hesap açma uçları aynı varsayılanı kullanır: birim seçilmezse 400 döner. (c) `GET /api/personnel` birim kapsamına göre süzülür. Birimi boş olan personel (yönetim, İK, muhasebe) yalnız `AllUnits` sahibine görünür. (d) Bağlı personelin `UnitCode` değeri hesabın birimleri içinde değilse kayıtta uyarı gösterilir.
- **Gerekçe:** Bugün aynı istek iki uçta farklı sonuç veriyor: kullanıcı ucu boş birimi tüm birim listesine çeviriyor (P.cs:216, 256-258), personel ucu boş liste yazıyor (P.cs:1797) ve `UnitAllowed` boş listeyi "tümü" sayıyor (P.cs:2807). Birim seçmeyi unutmak sessizce tam erişim veriyor (A1-13). Personel listesi her `personnel.view` sahibine tüm şirketi gösteriyor (P.cs:1742-1747).
- **Mevcut:** P.cs:216, 256-258, 1797, 2801, 2805-2807, 3497.
- **Kabul:** (1) Birim seçilmeden personel ile hesap açma 400 döner. (2) `AllowedUnits=''` ve `AllUnits=0` olan hesap hiçbir iş emrini görmez. (3) Geçişten önce boş olan hesaplar geçişten sonra aynı erişime sahiptir (`AllUnits=1`) ve raporda listelenir. (4) Yalnız "Haberleşme" birimli bir `personnel.view` sahibi Güvenlik Sistemleri personelini listede görmez. (5) `RoleName="Admin"` tek başına birim kapsamını aşmaz; yalnız `*` veya `AllUnits` aşar.
- **Roller:** Tüm roller.
- **Veri:** `ErpUsers.AllUnits BIT NOT NULL DEFAULT 0` ve geçiş betiği.
- **Efor:** S-M · **Bağımlılık:** —

### M13-09 · VERİ · Yönetici ilişkisinin kimliğe bağlanması ve "Ekibim" görünümü
- **Açıklama:** `Personnel.ManagerName` metni yerine `ManagerPersonnelId` kullanılır; ad metni geçiş süresince korunur. Şef için personel ekranında "Ekibim" süzgeci olur: doğrudan bağlı personel, hesap durumu, `FieldRole`, aktif sayaç var mı. Döngü engellenir (kişi kendisinin ya da astının astı olamaz).
- **Gerekçe:** Yönetici adı metin olduğu için ad değişikliği hiyerarşiyi koparıyor ve "şef kendi ekibini görür" gibi kurallar uygulanamıyor. Organizasyon şeması gelince doğrudan buraya işlenecek.
- **Mevcut:** upd.sql:358, 372-420 (ad metni); app.js:1044 (yönetici listesi aktif personel adları).
- **Kabul:** (1) Geçiş betiği mevcut `ManagerName` değerlerini ada göre eşler; eşleşmeyenler raporda listelenir, tahmin yapılmaz. (2) Yönetici adı değişince astların kartında yeni ad görünür. (3) A → B → A döngüsü kurulmak istenince 400 döner. (4) Şef "Ekibim" süzgecinde yalnız kendine bağlı aktif personeli görür.
- **Roller:** Düzenleme: `personnel.manage`. Görme: Şef (kendi ekibi).
- **Veri:** `Personnel.ManagerPersonnelId BIGINT NULL FK → Personnel`.
- **Efor:** S · **Bağımlılık:** Organizasyon şeması (yapı hazır olur, veri sonra girilir).

### M13-10 · VERİ · Ad bazlı eski kayıtların kimliğe eşlenmesi ve personel tekilliği
- **Açıklama:** Tek seferlik "Kimlik Eşleştirme" ekranı ve betiği hazırlanır. Kaynaklar: `WorkOrderAssignments.AssignedName`, `WorkOrderTimeLogs.TechnicianName`, `WorkOrderLiveSessions.TechnicianName`, `Personnel.ManagerName`. Her ayrı ad için önerilen `PersonnelId` gösterilir (birebir eşleşme, büyük/küçük harf ve Türkçe karakter normalize edilmiş eşleşme). İK ya da Admin onaylar. Onaylanmayan ad **eşleşmedi** olarak kalır, metin korunur, tahmin yazılmaz. Ek kurallar: `Personnel.SicilNo` (isteğe bağlı, tekil); aynı birimde aynı adla ikinci aktif personel açılırken onay istenir; bir hesap en fazla bir personele bağlanır (M13-01 index'i).
- **Gerekçe:** M01-10, M02-03 ve M09-13 kimliğe geçmeyi istiyor. Ancak geçmiş kayıtlar ad metniyle tutuluyor ve aynı kişi farklı yazılmış olabilir ("Ali Guler" / "Ali Güler"). Otomatik tahmin yanlış kişiye süre yazar. Personel tablosunda tekillik yok (upd.sql:350-367); seed tekilliği yalnız ada göre kontrol ediyor (upd.sql:425).
- **Mevcut:** upd.sql:425, 428-432; P.cs:3341-3342, 2047, 1967.
- **Kabul:** (1) Ekranda her ayrı ad için kayıt sayısı ve öneri görünür. (2) Onay sonrası ilgili satırların `PersonnelId` alanı dolar, `AssignedName` değişmez. (3) Onaylanmayan adlar M13-05 raporunda "eşleşmedi" olarak sayılır. (4) Aynı `SicilNo` ikinci kez girilince 409 döner. (5) Betik iki kez çalıştırılırsa ikinci çalıştırma hiçbir şeyi değiştirmez (idempotent). (6) Betik öncesi SQL yedeği alındığı geçiş talimatında yazılıdır.
- **Roller:** Admin, İK.
- **Veri:** `Personnel.SicilNo NVARCHAR(30) NULL` + filtreli UNIQUE; `PersonnelId` sütunları M01-10 ve M09-13 maddelerinde tanımlı.
- **Efor:** M · **Bağımlılık:** M01-10 ve M09-13 sütunlarının eklenmesi; M13-02.

### M13-11 · EKSİK · Şifre ve giriş yaşam döngüsü
- **Açıklama:** (a) "Şifre değişikliği zorunlu" sunucuda uygulanır: bayrak açıkken yalnız `me`, `logout` ve `change-password` çalışır, diğer uçlar 403 döner. (b) Şifre değiştirmede mevcut şifre sorulur. (c) Geçici şifreyi yönetici yazmaz. Sistem 12 karakterlik rastgele şifre üretir, **bir kez** gösterir, 72 saat geçerli olur. (d) Yeni şifre kullanıcı adını içeremez ve eski şifreyle aynı olamaz. (e) `LastLoginAt` ve `PasswordChangedAt` tutulur. (f) 5 başarısız denemede hesap 15 dakika kilitlenir (A1-05); kilit Admin tarafından açılabilir. Hata mesajı hesabın var olup olmadığını belli etmez.
- **Gerekçe:** Zorunlu değişim yalnız istemcide (app.js:2040). Geçici şifreyle doğrudan API çağrılabiliyor. Açık kalmış bir oturumdan şifre, mevcut şifre bilinmeden değiştirilip hesap ele geçirilebiliyor (P.cs:114-137, A1-11). Geçici şifreyi yönetici `prompt()` içine yazıyor ve biliyor (app.js:2028).
- **Mevcut:** P.cs:67-99, 114-137, 338-357; app.js:2028, 2040.
- **Kabul:** (1) `MustChangePassword=1` olan hesap `GET /api/workorders` çağrısında 403 alır. (2) Yanlış mevcut şifreyle değiştirme 400 döner. (3) Üretilen geçici şifre yanıtta bir kez döner ve denetim kaydına **yazılmaz**. 72 saat sonra girişte reddedilir. (4) 5 hatalı denemeden sonra doğru şifre de 15 dakika reddedilir; kilit denetim kaydına yazılır. (5) Var olmayan ve var olan kullanıcı adı için hata mesajı aynıdır.
- **Roller:** Tüm kullanıcılar. Kilit açma: Admin.
- **Veri:** `ErpUsers.FailedLoginCount INT`, `LockedUntil DATETIME2 NULL`, `PasswordChangedAt DATETIME2 NULL`, `TempPasswordExpiresAt DATETIME2 NULL`.
- **Efor:** M · **Bağımlılık:** M13-06.

### M13-12 · GÜVENLİK · **KRİTİK** · Yetki yükseltme önlemi (alt küme ve üstünlük kuralları)
- **Açıklama:** Kullanıcıya dokunan tüm uçlara (`POST/PUT /api/users`, `status`, `reset-password`, `POST /api/personnel` hesap açma, personel `status` ve işten çıkış, vekâlet) tek bir sunucu kontrolü eklenir:
  1. İzin anahtarları katalogda olmalıdır. `*`, `users.manage`, `audit.view` ve `RoleName="Admin"` yalnız `*` sahibince verilebilir.
  2. Verilen izin ve birimler, işlemi yapanın izin ve birimlerinin **alt kümesi** olmalıdır.
  3. Kişi kendi izinlerini ve birimlerini değiştiremez.
  4. Hedef hesabın yetkisi işlemi yapanınkinden genişse (işlemi yapanda olmayan bir izin veya birim varsa) düzenleme, şifre sıfırlama ve **pasifleştirme** 403 döner. Bu kural personel ekranından yapılan hesap kapatmayı da kapsar (A1-07). İK, Admin'i kapatamaz; kapatma isteği Admin'e iletilir.
  5. Son aktif `*` hesabı pasifleştirilemez ve yetkisi düşürülemez.
  6. `IsAdmin()` artık rol adına bakmaz.
- **Gerekçe:** Bugün `users.manage` sahibi (İK ve Müdür Yardımcısı dahil) kendine `*` verebiliyor, Admin'in şifresini sıfırlayıp hesabı ele geçirebiliyor ve fiyat/maliyet dahil tüm veriye erişebiliyor (P.cs:203-357, 2805; A1-01). Bu, veri sızıntısı yaratan bir açıktır. Personel ekranından Admin hesabı kapatılabiliyor (P.cs:1890-1899).
- **Mevcut:** P.cs:207, 249, 325, 342, 1777, 1866, 2805.
- **Kabul:** (1) `users.manage` olan ama `*` olmayan hesap kendine `finance.prices.view` eklemek isteyince 403 alır. (2) Aynı hesap başka bir kullanıcıya `*` veya `users.manage` verince 403 alır. (3) Admin'in şifresini sıfırlama ve Admin'i pasifleştirme denemesi 403 döner (kullanıcı ve personel uçlarının her ikisinde). (4) `RoleName="Admin"`, izinleri boş bir hesap başka birimin iş emrini göremez. (5) Tek aktif Admin pasifleştirilmek istenince 400 döner. (6) Katalogda olmayan `"hepsi"` izni gönderilince 400 döner. (7) Tüm reddedilen denemeler denetim kaydına yazılır. (8) Bu kurallar otomatik testle güvence altına alınır (M13-14).
- **Roller:** `users.manage`, `personnel.manage` sahipleri.
- **Veri:** Yok.
- **Efor:** S-M · **Bağımlılık:** Yok (ilk yapılacak). M13-06 ile birlikte yapılırsa reddedilen denemeler de kaydedilir.

### M13-13 · GÜVENLİK · **KRİTİK** · Erişim kapatma ve yetki daraltma anında etkili olmalı; oturum süresi
- **Açıklama:** (a) `PATCH /api/users/{id}/status` ile pasifleştirme, şifre sıfırlama ve kilit, hedefin **tüm oturumlarını** düşürür. (b) İzin veya birim **daraltması** açık oturuma hemen yansır (bugün yalnız PUT yansıtıyor; personel adı ve vekâlet bitişi yansımıyor). Bunun için oturumda yalnız `UserId` ve son doğrulama zamanı tutulur. İzinler 60 saniyelik önbellekle veritabanından okunur; `IsActive=0` görülünce oturum düşer. (c) Oturumun hareketsizlik süresi (öneri: 8 saat) ve mutlak süresi (öneri: 12 saat) olur (§4 S5). (d) Kullanıcı "tüm cihazlardan çık" diyebilir.
- **Gerekçe:** Kullanıcı ekranından pasifleştirilen veya şifresi sıfırlanan kişi, sunucu yeniden başlayana kadar **açık belirteciyle çalışmaya devam ediyor** (P.cs:321-357; oturum düşürme yalnız personel ucunda var, P.cs:1897-1898). İşten ayrılan kişinin telefonundaki açık oturum, müşteri, cihaz ve personel verisine erişimi sürdürüyor. Belirteçlerin süresi yok (P.cs:21, 94-96; A1-04). Bu madde işten çıkış bağlamında veri sızıntısı yarattığı için KRİTİK olarak işaretlendi. A1 denetimi aynı bulguyu genel bağlamda YÜKSEK olarak sınıflamıştı.
- **Mevcut:** P.cs:21, 94-96, 297-298, 321-357, 2821-2825.
- **Kabul:** (1) Kullanıcı ekranından pasif yapılan hesabın eski belirteci bir sonraki istekte 401 alır. (2) Şifresi sıfırlanan hesabın tüm açık oturumları 401 alır. (3) `reports.export` izni kaldırılan kullanıcı, çıkış yapmadan Excel indirmeye çalışınca en geç 60 saniye içinde 403 alır. (4) 8 saat işlem yapılmayan oturum 401 alır; istemci giriş ekranına döner. (5) Sunucu yeniden başlarsa tüm oturumlar düşer ve bu kabul edilir (tek sunucu pilotu). Çoklu sunucuya geçişte oturum tablosu ayrıca ele alınır.
- **Roller:** Tüm kullanıcılar.
- **Veri:** Bellekte oturum kaydına `CreatedAt`, `LastSeenAt` ve `PermsLoadedAt` eklenir. İsteğe bağlı `ErpUsers.SecurityStamp UNIQUEIDENTIFIER`: şifre veya yetki değişince yenilenir, oturumlar ona göre geçersizleşir.
- **Efor:** S-M · **Bağımlılık:** Yok (M13-12 ile aynı sürümde).

### M13-14 · GÜVENLİK · Yetki matrisi ve otomatik yetki testleri (bu modülün uçları)
- **Açıklama:** Küçük bir test projesi kurulur (`DengeERP.Api.Tests`, xUnit + `WebApplicationFactory`, `DengeERP_TEST` veritabanı). Bu modülün uçları için rol × uç × beklenen sonuç matrisi tablo olarak yazılır ve otomatik çalıştırılır. Örnek satırlar: İK → `PUT /api/users` (`*` verme) → 403; Şef → `GET /api/personnel/assignable` → 200; pasif hesap → herhangi bir uç → 401. Matris belgesi `analiz/` altında tutulur ve organizasyon şeması gelince güncellenir. Ayrıca `users.manage` izninin sayaç iptalinde operasyonel yetki olarak kullanılması kaldırılır (P.cs:2084; M09-16 ile ortak).
- **Gerekçe:** Yetki kuralları tek dosyada, yüzlerce `Can()` çağrısına dağılmış durumda ve test projesi yok. M13-12 ve M13-13 düzeltmeleri, sonraki sürümlerde fark edilmeden bozulabilir. Belgedeki açık doğrulamalardan biri "rol değişiminde hassas API'lerin veri sızdırmaması" (proje geçmişi §10.2).
- **Mevcut:** Test projesi yok. P.cs:2084, 2170.
- **Kabul:** (1) `dotnet test` en az M13-12 maddesinin 8 kabul senaryosunu ve M13-13 maddesinin 1-3 numaralı senaryolarını çalıştırır ve hepsi geçer. (2) Testlerden biri bozulduğunda derleme hattı (GitHub'a geçildiğinde) kırmızıya döner. (3) Matris belgesi her rol için bu modülün uçlarını içerir.
- **Roller:** Geliştirici, İT.
- **Veri:** Test veritabanı seed'i (gerçek kişi adı içermez).
- **Efor:** M · **Bağımlılık:** M13-12, M13-13. M07-15 (fiyat sızıntısı testleri) ile aynı test projesini kullanır.

### Uygulama sırası önerisi

| Sürüm | Maddeler | Not |
|---|---|---|
| **Hemen (küçük, kritik)** | M13-12, M13-13 | Kullanıcının öncelik sırası c→b→a olsa da bu ikisi veri sızıntısını kapatır ve S-M eforludur. |
| **1. dalga (YENİ)** | M13-06, M13-01, M13-02, M13-03 | Kimlik altyapısı. M01-10, M02-03 ve M09-13 bunun üzerine kurulur. |
| **2. dalga** | M13-07, M13-08, M13-10, M13-04 | Şablon düzeltmesi, birim kapsamı, eski kayıt eşleştirme, vekâlet. |
| **3. dalga** | M13-05, M13-09, M13-11, M13-14 | Gözden geçirme raporu, hiyerarşi, şifre yaşam döngüsü, testler. |

---

## 4. Kullanıcıya sorulacaklar (benim karar veremeyeceğim konular)

1. **S1 — Hesap açma ve yetki verme kimde olacak?** Bugün `users.manage` izni Admin, Üst Yönetim, Teknik Servis Müdürü, Müdür Yardımcısı ve İK'da var. Önerim: yalnız Admin (İT) ve Teknik Servis Müdürü. İK yalnız personel kartı ve işten çıkış yapsın. Uygun mu?
2. **S2 — Ücret ve fiyat görme (`finance.prices.view`) iznini kim verebilir?** Yalnız Admin mi, yoksa Üst Yönetim de mi?
3. **S3 — Her teknisyenin kendi ERP hesabı olacak mı?** Canlı sayaç ve süre kaydı kişi hesabı gerektiriyor. Stajyerler (ör. 2 lise stajyeri) hesap alacak mı, yoksa yalnız atanıp süreleri şef tarafından mı girilecek?
4. **S4 — Ortak hesap kullanımı (ör. atölye tableti, "depo" hesabı) var mı?** Önerim: ortak hesap olmasın; aksi halde kimin ne yaptığı izlenemez.
5. **S5 — Oturum süreleri:** Sahadaki teknisyen telefonda gün boyu açık kalmak istiyor. Önerim: 8 saat hareketsizlik, 12 saat mutlak süre. Ofis kullanıcıları için daha kısa (ör. 2 saat hareketsizlik) olsun mu?
6. **S6 — Vekâleti kim verebilir ve en uzun süresi ne olsun?** Önerim: yalnız Teknik Servis Müdürü, en fazla 30 gün.
7. **S7 — İşten çıkışı kim başlatır?** İK mı, birim müdürü mü, ikisi de mi? İK'nın çıkış tarihini önceden (ileri tarihli) girip erişimin o gün otomatik kapanması istenir mi?
8. **S8 — Denetim kaydı ne kadar saklanacak?** KVKK ve şirket politikası açısından öneri 2 yıl. Şirketin bilgi güvenliği politikası farklı bir süre öngörüyor mu?
9. **S9 — Şirkette Active Directory / Microsoft 365 hesabı var mı?** Varsa ileride ERP girişinin şirket hesabıyla yapılması (tek oturum açma) düşünülsün mü? Bu belge şimdilik yerel hesapla devam ediyor.
10. **S10 — Teknik servis dışındaki kullanıcılar (Muhasebe, Kiralama Operasyon, Genel Koordinatör) ERP'de kalacak mı?** Kapsam teknik servis ile sınırlı olsa da teklif onayı ve kiralama için hesapları var. Bu rollerin şablonları da gözden geçirilsin mi?
11. **S11 — Şef–birim ilişkisi:** Haberleşme ve POC'un şefi aynı kişi (Ertuğrul Çakır), Mobilite ve Araç Takip'in şefi aynı kişi (Serkan Doğan). Bir birimde birden fazla şef olabilir mi? Şef yalnız kendi ekibini mi, tüm birimi mi görmeli?
12. **S12 — Sicil numarası:** İK'da personel sicil numarası var mı ve ERP'ye girilebilir mi? (Aynı ad soyad durumunu kesin çözer.)

---

## 5. Varsayımlar

- Organizasyon şeması gelmediği için §2.2'deki rol dağılımı ve M13-07'deki şablon değişiklikleri **öneridir**. Gerçek yapı geldiğinde M13-14 matrisi ile birlikte güncellenecektir.
- Tek sunuculu pilot devam ediyor. Bellek içi oturum yapısı korunuyor ve yalnız süre, iptal ve canlı izin okuması ekleniyor. Oturum tablosu veya JWT gibi büyük bir değişiklik önerilmiyor.
- Rol şablonları kodda (`Catalog`) kalıyor. Veritabanında düzenlenebilir rol yönetimi bu ölçekte gereksiz görüldü.
- Kişi bazlı izin kararı korunuyor. Bu belge onu yalnız sınırlandırıyor (alt küme, üstünlük) ve izlenebilir yapıyor (denetim, gözden geçirme).
- Zaman takibi bordro değildir. Personel kartına izin, mesai veya ücret bilgisi eklenmiyor. Müsaitlik blokları M02-05 kapsamındadır.
- Eski ad bazlı kayıtlar otomatik tahminle kimliğe bağlanmıyor; eşleşmeyen kayıt "eşleşmedi" olarak kalıyor (seri no uydurmama ve süre yoksa "eksik" deme ilkesiyle aynı yaklaşım).
- Logo CRM, Flowick ve AD entegrasyonu kapsam dışı (S9 yalnız bilgi amaçlı soruluyor).
- Satır numaraları V1.20.1 orijinal kaynağına göredir.
