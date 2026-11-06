# A4 — Kurulum, Operasyon ve İş Akışı Tutarlılığı Denetimi (DengeERP V1.20.1)

> **Tarih:** 21.10.2026  
> **Denetlenen kaynak (salt okunur):** `kaynak/V1_20_1_orijinal/` — `DengeERP.Api/Program.cs`, `OpsSuite.cs`, `wwwroot/app.js`, `wwwroot/ops120.js`, `wwwroot/index.html`, `Database/*.sql`, `appsettings*.json`, `Properties/launchSettings.json`, `linux/*`, kurulum/changelog metinleri.  
> **Yöntem:** Kod ve betikler satır satır okunarak doğrulandı. Uygulama bu makinede **çalıştırılmadı** (bu bilgisayarda .NET SDK ve SQL Server servisi yok — `dotnet --list-sdks` boş, `MSSQL*` servisi yok). Çalıştırma gerektiren iddialar “**doğrulanmadı**” diye işaretlendi.  
> **Kapsam kararları:** yalnızca teknik servis; öncelik (c) yeni modül/özellik → (b) mevcut modül eksikleri → (a) güvenlik/üretime hazırlık. Veri kaybı/sızıntısı yaratan açıklar yine **KRİTİK** işaretlendi. Logo CRM / Flowick kapsam dışı. Rol önerileri, organizasyon şeması gelene kadar **varsayımdır**.

---

## 1. Özet

DengeERP V1.20.1'in Linux kurulum paketi (systemd + Nginx + sürümlü yayın + geri dönüş) genel hatlarıyla **düzgün ve temkinli** kurgulanmış: sırlar `0600` env dosyasında, Kestrel yalnızca `127.0.0.1:5051`'de, şema güncellemesi varsayılan kapalı, yayın betiği sağlık kontrolü başarısızsa önceki sürüme dönüyor. Buna karşılık denetim üç ana risk kümesi ortaya çıkardı:

1. **Veri güvenliği / sızıntı (KRİTİK):** “Kullanıcı / Yetki” ekranından pasif yapılan kullanıcının oturumu düşmüyor ve oturumların süre sonu yok; ayrıca birkaç gün içinde planlanan GitHub geçişinde kaynakta gömülü **gerçek müşteri, sözleşme bedeli ve personel adları** bulunuyor.
2. **Operasyonel süreklilik (YÜKSEK):** sürümlü veritabanı migration mekanizması yok; şema kurulumu açıldığında seed betiği elle düzeltilmiş verileri eziyor; otomatik yedek/geri yükleme yok; Linux sunucusunda saat dilimi ayarlanmıyor (uygulama `DateTime.Now`, SQL `SYSDATETIME()` kullanıyor); bakım sayacı yıl dönümünde sıfırlanmıyor (01.01.2027'de planlı bakımlar açılmayabilir); İnsan Kaynakları rolü uygulamaya giremiyor; yetkisiz isteklerin 403 yerine büyük olasılıkla 500 döndürmesi; Windows pilotun `Development` modunda hata ayrıntısı sızdırması; bu makinede derleme/test ortamının hazır olmaması.
3. **İş akışı tutarlılığı (ORTA):** iş emri durumları için sunucuda durum makinesi yok; “Kaydet” her seferinde durumu yeniden gönderdiği için kapanış tarihi kayıyor ve kapanış yan etkileri tekrar çalışıyor; tekli planlama kapalı işi yeniden açabiliyor; “Beklemede” iki farklı mekanizmayla yönetiliyor; çakışma kontrolü sadece tarayıcıda; süre kaydı olmayan işler bazı ekranlarda “0” görünüyor (karar ihlali); SLA planlı bakımlara da uygulanıyor; bakım formundaki yedek parça metni stok çıkışıyla bağlantısız.

Toplam **32 bulgu**: 2 KRİTİK, 9 YÜKSEK, 18 ORTA, 3 DÜŞÜK.

**Uçtan uca akış değerlendirmesi (talep → planlama → saha → kapanış → rapor):**

| Adım | Kodda var mı? | Tutarlılık durumu |
|---|---|---|
| Talep açma | `POST /api/workorders` (Program.cs:370) | Var; durum `Müşteri Talebi`. Müşteri/lokasyon serbest metin. |
| Havuz / atama | Tekli `PUT …/assignments` (545), toplu `bulk-assign` (573) | Tekli atamada durum kontrolü ve iz kaydı yok (A4-19). Atama **isim metni** (A4-19). |
| Planlama | Tekli `PUT …/plan` (722), toplu `bulk-plan` (649) | Tekli planlamada durum ön koşulu yok, kapalı işi `Planlandı`ya çeviriyor (A4-16). Sunucuda çakışma kontrolü yok (A4-17). |
| Saha / süre | Canlı sayaç (1929–2078), manuel süre (2114) | Sağlam kurallar (tek aktif sayaç, çakışma, mola hariç). Ancak sayaç ile iş durumu bağımsız (A4-30); saat dilimi riski (A4-06). |
| Kontrol listesi / kapanış | Bakım formu (2445), durum PATCH (473) | Bakım tarafı kuralları iyi. Genel işlerde durum makinesi yok, `Tamamlandı`/`Kapatıldı` ayrımı tanımsız (A4-14, A4-15). |
| Rapor / KPI | Excel (2191), Operasyon Merkezi (OpsSuite.cs:76) | Excel “süre kaydı eksik” gösteriyor (Program.cs:3666) ✔; Operasyon/Maliyet ekranları “0” kullanıyor (A4-20). SLA PB'ye de uygulanıyor (A4-21). |

---

## 2. Bulgular tablosu (önem sırasıyla)

| ID | Önem | Başlık | Ana konum |
|---|---|---|---|
| A4-01 | KRİTİK | Pasif yapılan kullanıcının / şifresi sıfırlanan kullanıcının oturumu düşmüyor; oturumların süre sonu yok | Program.cs:321-336, 338-357, 21, 94-96, 2821-2825 |
| A4-02 | KRİTİK | GitHub geçişi öncesi: kaynakta gerçek müşteri, sözleşme bedeli ve personel adları (KVKK) | Database/DengeERP_V15_Seed.sql (2444 satır); wwwroot/app.js:23-29 |
| A4-03 | YÜKSEK | Şema kurulumu açıldığında seed MERGE elle düzeltilmiş cihaz/sözleşme verisini eziyor | DengeERP_V15_Seed.sql:1361-1364, 2437-2441; Program.cs:26-34 |
| A4-04 | YÜKSEK | Sürümlü migration / şema sürüm takibi yok; kısmi uygulanma riski | Program.cs:26-41, 3257-3269; PILOT_V120_KURULUM_VE_TEST.txt:44 |
| A4-05 | YÜKSEK | Otomatik SQL yedeği, saklama ve geri yükleme tatbikatı yok | linux/SQL_HAZIRLIK_YEDEK.sql:8-9; linux/04_geri_don.sh:18 |
| A4-06 | YÜKSEK | Saat dilimi tutarsızlığı: Linux'ta TZ ayarlanmıyor; `DateTime.Now` ile `SYSDATETIME()` karışık | Program.cs:2126, 1959, 386, 2897; OpsSuite.cs:28-33, 87; linux/01_sunucuyu_hazirla.sh |
| A4-07 | YÜKSEK | Bakım sayacı yıl dönümünde sıfırlanmıyor; sözleşme dönemi dikkate alınmıyor | Program.cs:2897-2960, 3165-3170, 2546, 2309 |
| A4-08 | YÜKSEK | “İnsan Kaynakları” rolü uygulamaya giriş yapamıyor | app.js:137-141, 2032, 2045; Program.cs:363, 3934 |
| A4-09 | YÜKSEK | `Results.Forbid()` kimlik doğrulama servisi olmadan 403 yerine 500 üretiyor (doğrulanmadı) | Program.cs:11-13, 178, 363 vb.; app.js:96-106 |
| A4-10 | YÜKSEK | Windows pilot `Development` modunda: yığın izi/SQL hatası LAN kullanıcılarına; health `ex.Message` | Properties/launchSettings.json:8-10; Program.cs:11-16, 61-64 |
| A4-11 | YÜKSEK | Yerel derleme/test ortamı hazır değil; `appsettings.json` Linux'a göre ayarlı | appsettings.json:2-3, 18; Program.cs:12, 18-19 |
| A4-12 | ORTA | Seed ve personel listesi uygulama paketine/yayına da kopyalanıyor | DengeERP.Api.csproj:15-19; linux/02_yayinla.sh:26-29 |
| A4-13 | ORTA | Oturumlar bellekte: her yayın/yeniden başlatma tüm kullanıcıları düşürür | Program.cs:21; linux/02_yayinla.sh:40 |
| A4-14 | ORTA | İş emri durum makinesi yok; `Tamamlandı`/`Kapatıldı`/`Çözüldü`/`Tekrar Açıldı` tutarsız | Program.cs:473-543, 527, 2808, 3316-3317; app.js:30-31 |
| A4-15 | ORTA | “Kaydet” her seferinde durumu yeniden gönderiyor: kapanış tarihi kayması, kısmi güncelleme, kapanış yan etkileri | app.js:1668-1672; Program.cs:525-540 |
| A4-16 | ORTA | Tekli planlama durum ön koşulu olmadan `Planlandı` yapıyor; toplu yeniden planlama mümkün değil | Program.cs:722-761, 682-683 |
| A4-17 | ORTA | Şef/teknisyen/araç çakışma kontrolü yalnızca tarayıcıda | app.js:385, 522, 531; Program.cs:649-761 |
| A4-18 | ORTA | “Beklemede” iki ayrı mekanizma; bekletme/kaldırma iş emri geçmişine yazılmıyor | OpsSuite.cs:130-159; Program.cs:2512; ops120.js:43 |
| A4-19 | ORTA | Atamalar isim metni; atama değişikliği aktif sayacı kilitliyor; tekli atamada iz kaydı yok | Program.cs:545-570, 1945-1947, 1996, 3398-3400; app.js:23-29, 1604 |
| A4-20 | ORTA | Süre kaydı olmayan iş “0” olarak gösteriliyor (Operasyon/Maliyet/İş detayı) — karar ihlali | OpsSuite.cs:82, 88, 230-234; ops120.js:19-21; app.js:1640 |
| A4-21 | ORTA | SLA planlı bakım işlerine de uygulanıyor; bekleme süresi düşülmüyor; kapanan işte SLA uyumu ölçülmüyor | OpsSuite.cs:26-36, 87, 102 |
| A4-22 | ORTA | Yedek parça: bakım formundaki parça metni stok çıkışına bağlı değil; kiralama depo tablosu kullanılıyor; ID ile prompt arayüzü | Program.cs:2515; OpsSuite.cs:188-213; ZZ_V120_Operations.sql:21, 24; ops120.js:84-92 |
| A4-23 | ORTA | Eşzamanlı düzenlemede “son yazan kazanır” (kayıp güncelleme) | Program.cs:545-570, 722-761; app.js:1668-1672 |
| A4-24 | ORTA | Statik dosya sürüm parametresi hotfix sonrası değişmemiş (`?v=120`) | wwwroot/index.html:8-14; HOTFIX_V1201.txt:1 |
| A4-25 | ORTA | Linux betik eksikleri: .NET 10 apt kaynağı (doğrulanmadı), root ile derleme, geri dönüşte sağlık kontrolü yok, eski sürüm temizliği yok | linux/01:16; linux/02:18-29, 34-35; linux/04:9-16 |
| A4-26 | ORTA | Nginx/HTTPS/AllowedHosts: IP sabit kodlu, HTTPS örneğinde yönlendirme/HSTS yok, güvenlik başlıkları yok, varsayılan site açık | linux/nginx/*.conf; appsettings.json:18; linux/01:29 |
| A4-27 | ORTA | Sağlık kontrolü dar: yalnızca SQL bağlantısı; Nginx üzerinden ve şema sürümü test edilmiyor | Program.cs:47-65; linux/02:49; linux/03:8 |
| A4-28 | ORTA | Loglama ve denetim izi eksik (kullanıcı/yetki değişikliği, bekletme, atama, stok) | Program.cs:245-357; OpsSuite.cs:130-159; appsettings.json:12-17 |
| A4-29 | ORTA | Cihaz kütüğü ve bakım sözleşmeleri arayüzden yönetilemiyor (yarım modül) | Program.cs:2232 (yalnız GET), 2288 (yalnız GET) |
| A4-30 | DÜŞÜK | Canlı sayaç ile iş durumu bağımsız (`Yola Çıkıldı`/`Sahada` elle) | Program.cs:1929-1983; app.js:30 |
| A4-31 | DÜŞÜK | Her istekte tüm iş emirlerini belleğe yükleme; Operasyon listesinde sessiz kesme | Program.cs:3441-3462; OpsSuite.cs:106, 135, 150, 193, 250; ops120.js:43 |
| A4-32 | DÜŞÜK | Doküman ve yapılandırma tutarsızlıkları (otomatik migration iddiası, ZIP adları, e-posta ayarı) | PILOT_V120_KURULUM_VE_TEST.txt:44; linux/README_KURULUM_TR.md:25; IT_ICIN_ILK_OKU.md:24; appsettings.json:4-11; linux/dengeerp.env.example |

---

## 3. Bulgu ayrıntıları ve öneriler

### A4-01 — KRİTİK — Pasif yapılan / şifresi sıfırlanan kullanıcının oturumu düşmüyor; oturumların süre sonu yok

**Konum:** `Program.cs:321-336` (`PATCH /api/users/{id}/status`), `Program.cs:338-357` (`reset-password`), `Program.cs:21` (`ConcurrentDictionary` oturumlar), `Program.cs:94-96` (token üretimi, süre bilgisi yok), `Program.cs:2821-2825` (`GetCurrentUser` yalnızca sözlüğe bakar).

**Ayrıntı:** “Kullanıcı / Yetki” ekranından bir hesap pasif yapıldığında yalnızca `ErpUsers.IsActive=0` güncelleniyor; bellekteki oturum silinmiyor. `GetCurrentUser` her istekte veritabanına bakmadığı ve oturumun süre sonu olmadığı için, işten ayrılan veya yetkisi alınan kişi **servis yeniden başlatılana kadar** tüm yetkileriyle (fiyat/maliyet dahil) çalışmaya devam eder. Aynı durum şifre sıfırlamada da var (eski oturumlar geçerli kalıyor). Tutarsızlık: `PATCH /api/personnel/{id}/status` (`Program.cs:1897-1898`) oturumları **siliyor**; iki yol farklı davranıyor. Token tarayıcıda `localStorage`'da (`app.js:35`) tutulduğu için paylaşılan bilgisayarda da geçerli kalır.

**Öneri (artımlı):** (1) `users/{id}/status` ve `reset-password` uçlarında `sessions` içinden ilgili `UserId` kayıtlarını silin (personel ucundaki 3 satırın aynısı). (2) `SessionUser`'a `ExpiresAt` + kayan süre (ör. 8–12 saat) ekleyin; `GetCurrentUser` süresi dolanı silsin. (3) Orta vadede oturumları SQL tablosuna taşıyın (A4-13 ile birlikte).

---

### A4-02 — KRİTİK — GitHub geçişi öncesi: kaynakta gerçek müşteri, sözleşme bedeli ve personel adları

**Konum:** `Database/DengeERP_V15_Seed.sql` (2444 satır; ör. satır 6-20 müşteri adları, cihaz seri numaraları, irtibat kişileri; satır 2346-2435 sözleşme bedelleri `N'15400 TL + KDV'`), `wwwroot/app.js:23-29` (`personnelFallback` — gerçek şef/teknisyen ad-soyadları), kök klasörde `TUM_KAYNAK_KODLARI_TEK_DOSYA.txt` ve `KAYNAK_KODLARI_V1_20_1.zip` (aynı verinin kopyaları).

**Ayrıntı:** Kullanıcı birkaç gün içinde GitHub'a geçileceğini belirtti. Bu dosyalar olduğu gibi depoya eklenirse (özellikle herkese açık depoda veya ileride depo erişimi genişlediğinde) müşteri listesi, kurum adları, cihaz seri numaraları, sözleşme bedelleri ve çalışan adları kalıcı olarak git geçmişine girer; sonradan silmek geçmişten temizlemeyi gerektirir. Bu bir **KVKK / ticari sır** sızıntısı riskidir.

**Öneri:** Depo **özel (private)** açılmalı. İlk commit'ten önce: (1) `DengeERP_V15_Seed.sql` depodan çıkarılıp yalnızca İT kontrollü alanda tutulsun; yerine sentetik test verisi üreten bir `Seed_Test.sql` konulsun (kullanıcı “test verisine sen karar ver” dedi → **sentetik veri önerilir**). (2) `personnelFallback` kaldırılsın; listeler yalnızca `/api/personnel` ve kullanıcı tablosundan gelsin (A4-19). (3) `.gitignore`: `*.bak`, `appsettings.*.local.json`, `*.env`, `TUM_KAYNAK_KODLARI_TEK_DOSYA.txt`, `KAYNAK_KODLARI_*.zip`, `bin/`, `obj/`. (4) Commit öncesi gizli bilgi taraması (ör. gitleaks) çalıştırılsın.

---

### A4-03 — YÜKSEK — Şema kurulumu açıldığında seed MERGE elle düzeltilmiş verileri eziyor

**Konum:** `Database/DengeERP_V15_Seed.sql:1361-1364, 1787-1790, 2200-2203, 2337-2340` (`WHEN MATCHED THEN UPDATE SET … SerialNo=s.SerialNo, CustomerName=…, Location=…, IsActive=1`), `:2437-2441` (sözleşmede `AnnualFrequency`, `PeriodText`, `MaintenanceFeeText` üzerine yazılıyor); `Program.cs:26-34` (bayrak açıkken **tüm** `*.sql` dosyaları alfabetik sırayla çalıştırılıyor).

**Ayrıntı:** `DengeERP__RunDatabaseSetupOnStartup=true` her yapıldığında (README bunu “boş DB ilklendirme” için tarif ediyor, ama yeni sürümde yeni tablo gerekirse de tek yol bu) seed betiği de çalışır ve: SSMS'ten düzeltilmiş cihaz seri numaralarını/lokasyonlarını Excel'deki eski değerlere döndürür, pasif yapılmış cihazları yeniden **aktif** eder (`IsActive=1`), yenilenmiş sözleşmelerin yıllık frekansını/dönemini eski değere çeker. Arayüzde cihaz düzenleme olmadığı için (A4-29) düzeltmelerin tek yolu SSMS'tir; bunlar sessizce kaybolur. Bu bir **veri kaybı** riskidir. Ayrıca seed sonrası `EnsureMaintenancePlansAndWorkOrdersAsync` (Program.cs:34) çalışıp toplu PB iş emri açabilir.

**Öneri:** (1) Seed'i şema betiklerinden ayırın; “yalnızca boş tablo ise ekle” (`WHEN NOT MATCHED` only) yapın veya tek seferlik içe aktarma aracına dönüştürün. (2) Başlangıç bayrağı yalnızca şema (DDL) betiklerini çalıştırsın. (3) A4-04'teki migration günlüğüyle her betik yalnızca bir kez çalışsın.

---

### A4-04 — YÜKSEK — Sürümlü migration / şema sürüm takibi yok

**Konum:** `Program.cs:26-41` (bayrak tabanlı toplu çalıştırma), `Program.cs:3257-3269` (`ApplySchemaAsync`: `GO` ile bölüp transaction olmadan sırayla çalıştırır), `linux/dengeerp.env.example:4, 9-10`, `linux/README_KURULUM_TR.md:80`; buna karşılık `PILOT_V120_KURULUM_VE_TEST.txt:44` “İLK AÇILIŞTA SQL MIGRATION OTOMATİK UYGULANIR” diyor.

**Ayrıntı:** Veritabanında hangi betiğin uygulandığını tutan bir tablo yok; sağlık kontrolü şema sürümüne bakmıyor. Sonuçlar: (1) Artımlı geliştirmede (V1.21, V1.22 …) yeni tablolar ya bayrak açılarak tüm betiklerle (A4-03 riskiyle) ya da elle SSMS'ten uygulanmak zorunda. (2) Uygulama kodu yeni, şema eskiyse uygulama açılır, `/api/health` “Bağlı” der ama ilgili ekranlar 500 verir. (3) Bir batch hata verirse önceki batch'ler uygulanmış kalır (transaction yok) → yarım şema. (4) `04_geri_don.sh` kodu geri alır, şemayı almaz; uyumluluk kontrolü yok. (5) Windows talimatı (otomatik migration) ile V1.20.1 kodu (varsayılan kapalı) çelişiyor.

**Öneri (teknoloji yığını korunarak):** `dbo.SchemaMigrations(ScriptName, Checksum, AppliedAt, AppliedBy)` tablosu; `Database/Migrations/0001_*.sql` numaralı, yalnızca ileri yönlü betikler; uygulama açılışında **yalnızca kontrol** (eksik migration varsa logla ve `/api/health`'te `schema: eksik` döndür), uygulamayı ayrı bir komutla (`dotnet DengeERP.Api.dll --migrate` veya ayrı PowerShell/SSMS betiği) ve yedek sonrası yapın. Her betik kendi transaction'ında çalışsın.

---

### A4-05 — YÜKSEK — Otomatik SQL yedeği, saklama ve geri yükleme tatbikatı yok

**Konum:** `linux/SQL_HAZIRLIK_YEDEK.sql:8-9` (tek seferlik `COPY_ONLY` yedek, sunucunun varsayılan yedek klasörüne), `linux/04_geri_don.sh:18` (“VERİTABANI GERİ YÜKLEMESİ YAPMAZ”), `linux/README_KURULUM_TR.md:90`.

**Ayrıntı:** Pakette zamanlanmış tam/fark/log yedeği, saklama süresi, sunucu dışına kopyalama veya geri yükleme tatbikatı betiği yok. Yedek, SQL sunucusunun kendi diskinde (`InstanceDefaultBackupPath`) duruyor; disk/sunucu kaybında yedek de kaybolur. `RESTORE VERIFYONLY` gerçek geri yüklemenin yerini tutmaz (proje belgesi §9 da bunu söylüyor). SQL Server Express kullanılırsa SQL Agent yoktur; zamanlama Windows Görev Zamanlayıcı/cron ile yapılmalıdır.

**Öneri:** (1) Günlük tam + (Full recovery ise) saatlik log yedeği; en az 14–30 gün saklama; sunucu dışı kopya. (2) Aylık “ayrı test veritabanına geri yükle + `/api/health` + örnek sorgular” tatbikat betiği (`RESTORE … WITH MOVE` → `DengeERP_RESTORE_TEST`). (3) Her yayından önce `02_yayinla.sh`'ın, son yedeğin 24 saatten yeni olduğunu teyit eden bir ön kontrol yapması (İT ile).

---

### A4-06 — YÜKSEK — Saat dilimi tutarsızlığı (Linux'ta TZ ayarlanmıyor)

**Konum:** Uygulama saati: `Program.cs:386` (`SRV-{DateTime.Now:yyyyMM}`), `Program.cs:2126` (“gelecek tarihli kayıt” kontrolü `DateTime.Now`), `Program.cs:2897` (`DateTime.Today` bakım vadesi), `OpsSuite.cs:28-33, 87, 103-104` (SLA gecikme, bugün/yarın); SQL saati: `Program.cs:1959, 2021` (`SELECT SYSDATETIME()` canlı sayaç), tablo varsayılanları `CreatedAt DEFAULT SYSDATETIME()`. Tarayıcı `datetime-local` değerini saat dilimi olmadan gönderiyor (`app.js:1634-1635`). `linux/01_sunucuyu_hazirla.sh` içinde `timedatectl`/TZ/NTP ayarı **yok** (grep ile doğrulandı).

**Ayrıntı:** Ubuntu bulut/VM imajları genellikle UTC ile gelir; SQL Server (Windows) muhtemelen Türkiye saatindedir (UTC+3). Bu durumda (doğrulanmadı — sunucu TZ'si bilinmiyor): manuel süre girişi son 3 saat için “Gelecek tarihli gerçekleşen çalışma kaydı oluşturulamaz” hatası verir (Program.cs:2126); SLA gecikmesi `CreatedAt` (SQL saati) ile `DateTime.Now` (Linux saati) karşılaştırıldığı için 3 saat kayar; “Bugün/Yarın planlı” ve iş emri ay öneki gece yarısı civarında yanlış güne düşer; canlı sayaç (SQL saati) ile manuel kayıtlar (tarayıcı saati) arasındaki çakışma kontrolü kayar.

**Öneri:** (1) `01_sunucuyu_hazirla.sh`'a `timedatectl set-timezone Europe/Istanbul` ve NTP (`systemd-timesyncd`/chrony) kontrolü; SQL sunucusu ile saat farkını `/api/health`'te raporlayın. (2) Kodda tek kaynak: ya her yerde SQL `SYSDATETIME()` ya da `TimeProvider` + açık `Europe/Istanbul` dönüşümü. (3) `systemd` birimine `Environment=TZ=Europe/Istanbul` (sunucu TZ'sinden bağımsız güvence).

---

### A4-07 — YÜKSEK — Bakım sayacı yıl dönümünde sıfırlanmıyor; sözleşme dönemi dikkate alınmıyor

**Konum:** `Program.cs:2897-2898` (`year = today.Year`), `Program.cs:2924-2950` (`@Completed = seq <= CompletedCount`), `Program.cs:3165-3170` ve `2546` (`CompletedCount+1`, üst sınır `AnnualFrequency`), `Program.cs:2309` (`PlanYear=YEAR(GETDATE())`), `DengeERP_V15_Seed.sql:2440` (seed sayaç büyük olanı korur). Kodda `CompletedCount` sıfırlayan **hiçbir** yer yok (grep ile doğrulandı).

**Ayrıntı:** `MaintenanceContracts.CompletedCount` yıllık sayaç gibi kullanılıyor ama yıl değişince sıfırlanmıyor. 2026'da 4/4 tamamlanan sözleşme için 01.01.2027'den sonra çağrılan ilk `EnsureMaintenancePlansAndWorkOrdersAsync`, 2027 planlarının 1–4. sıralarını **tamamlanmış** olarak oluşturur ve hiç PB iş emri üretmez; 2/4 tamamlanmış sözleşmede 2027'nin ilk iki bakımı “yapılmış” sayılır. Ayrıca `PeriodText` (ör. `15.01.2025-15.01.2026`) ayrıştırılmıyor; dönemi bitmiş sözleşmeler `IsActive=1` kaldıkça bakım üretmeye devam eder, dönemi yıl ortasında başlayan sözleşmelerin hedef ayları her zaman Ocak'tan hesaplanır. Bu, yaklaşık 2,5 ay sonra **sözleşmeli bakımların sistemde hiç görünmemesine** yol açabilir.

**Öneri:** Tamamlanan sayıyı `MaintenancePlans` üzerinden yıl bazında hesaplayın (`COUNT(*) WHERE PlanYear=@Year AND IsCompleted=1`) ve `CompletedCount`'u yalnızca gösterim için türetin; sözleşmeye `StartDate/EndDate` (tarih tipinde) alanları ekleyip plan aylarını dönem başlangıcından hesaplayın; dönemi bitmiş sözleşme için üretimi durdurup “yenileme bekliyor” uyarısı verin. Yıl dönümü senaryosu için tarihli test yazın.

---

### A4-08 — YÜKSEK — “İnsan Kaynakları” rolü uygulamaya giriş yapamıyor

**Konum:** `Program.cs:3934` (İK rolünde `workorders.view` yok), `app.js:137-141` (`loadCore` koşulsuz `api('/api/workorders')` çağırıyor), `Program.cs:363` (`workorders.view` yoksa `Forbid`), `app.js:2032` (giriş sonrası `loadCore` hatası giriş ekranında kalıyor), `app.js:2045` (sayfa yenilemede `loadCore` hatası → `logoutLocal`).

**Ayrıntı:** İK rolüyle giriş yapan kullanıcıda `Promise.all` ilk istekte reddedilir; kullanıcı giriş ekranında “İşlem başarısız (…)” mesajıyla kalır, sayfayı yenilerse oturumu yerelde silinir. İK menüsünde Eğitim/Personel/Kullanıcı ekranları olmasına rağmen erişilemez. Aynı kalıp, rol şablonundan `workorders.view` çıkarılmış her özel profil için de geçerli.

**Öneri:** `loadCore` içinde `/api/workorders` ve `/api/timetracking/summary` çağrılarını `can('workorders.view')` koşuluna bağlayın; açılış ekranını izinlere göre seçin; her modül yüklemesini ayrı `try/catch` ile yapın ki bir modül hatası tüm uygulamayı kilitlemesin. (Rol önerisi — **varsayım**: İK'nın iş emri görmesi gerekmiyorsa izin eklemek yerine istemci düzeltilmeli.)

---

### A4-09 — YÜKSEK — `Results.Forbid()` 403 yerine büyük olasılıkla 500 üretiyor (doğrulanmadı)

**Konum:** `Program.cs:11-13` (`AddAuthentication`/`AddAuthorization` yok), ~80 uçta `return Results.Forbid();` (ör. `Program.cs:178, 363, 374`; `OpsSuite.cs:79, 162, 217`), istemci `app.js:96-106`.

**Ayrıntı:** ASP.NET Core'da `Results.Forbid()` → `HttpContext.ForbidAsync()` çağırır; bu, `IAuthenticationService` kayıtlı değilse `InvalidOperationException` fırlatır. Kodda kimlik doğrulama servisi kaydı yok (özel Bearer + sözlük kullanılıyor). Dolayısıyla yetkisiz her istek **500** olur: Production'da boş gövdeli “İşlem başarısız (500)”, Development'ta HTML yığın izi (istemci JSON ayrıştıramayınca ham HTML'i `alert` ile gösterir, `app.js:103`). Journald her yetki reddinde istisna kaydıyla dolar. PILOT_V120 test listesindeki “finans ekranına yetkisiz kişi ERİŞEMEMELİ (403)” maddesi de bu nedenle 403 yerine 500 görebilir. **Uygulama çalıştırılmadığı için doğrulanmadı**; kod okumasına göre yüksek olasılık.

**Öneri:** `Results.Forbid()` yerine `Results.StatusCode(403)` veya `Results.Json(new{message="Bu işlem için yetkiniz yok."}, statusCode:403)` kullanan tek bir yardımcı (`Deny()`); ilk derlemede yetkisiz kullanıcıyla bir uç test edilerek teyit edilsin.

---

### A4-10 — YÜKSEK — Windows pilot `Development` modunda; hata ayrıntıları ağdaki kullanıcılara açık

**Konum:** `Properties/launchSettings.json:8-10, 17-19` (`ASPNETCORE_ENVIRONMENT=Development`, `0.0.0.0:5050`), `Program.cs:11-16` (özel hata işleyici yok; Development'ta Developer Exception Page otomatik), `Program.cs:61-64` (`/api/health` anonim, `detail: ex.Message`), proje belgesi §3.2 (“Hosting environment: Development” görüldü).

**Ayrıntı:** Windows pilot `dotnet run` ile Development'ta, HTTP üzerinden, Wi-Fi IP'sinden yayında. Her işlenmemiş hata (ve A4-09 nedeniyle her yetki reddi) LAN'daki kullanıcıya yığın izi, SQL sorgu metni ve SQL hata ayrıntısını gösterir. `/api/health` kimlik doğrulamasız olarak SQL bağlantı hatası metnini (sunucu adı, oturum açma hatası) döndürür.

**Öneri:** Windows pilotta `--environment Production` (veya `ASPNETCORE_ENVIRONMENT=Production`) ile çalıştırın; `app.UseExceptionHandler` ile JSON hata (izleme kimliği ile) döndürün, ayrıntıyı yalnızca log'a yazın; `/api/health` dış yanıtında yalnızca `ok/fail` verin, ayrıntıyı log'a yazın.

---

### A4-11 — YÜKSEK — Yerel derleme/test ortamı hazır değil; `appsettings.json` Linux'a göre ayarlı

**Konum:** `appsettings.json:2` (`Urls: http://127.0.0.1:5051`), `:3` (`ConnectionStrings: {}`), `:18` (`AllowedHosts: 10.10.50.16;localhost;127.0.0.1`), `Program.cs:12` (`UseUrls(config["Urls"])`), `Program.cs:18-19` (bağlantı yoksa açılışta istisna), `appsettings.Development.json` (yalnızca log ayarı). Bu makinede .NET SDK ve SQL Server servisi bulunamadı.

**Ayrıntı:** Kullanıcı “derleme ve test şimdilik burada” dedi. Mevcut kaynakla: (1) Bağlantı dizesi olmadığından uygulama açılmaz (yalnızca env/user-secrets ile verilebilir; eski `PILOT_KURULUM.txt:26` hâlâ `appsettings.json`'u tarif ediyor). (2) `AllowedHosts` yalnızca `10.10.50.16`/localhost içerdiği için bu PC'ye LAN IP'si (ör. `10.10.50.137`) ile gelen istekler HostFiltering tarafından **400** ile reddedilir (doğrulanmadı — çalıştırılmadı). (3) `--urls` verilmeden `dotnet run` yapılırsa `appsettings.json`'daki `Urls` büyük olasılıkla `launchSettings` adresinin önüne geçer ve uygulama `127.0.0.1:5051`'de açılır (doğrulanmadı). (4) Boş test DB için `RunDatabaseSetupOnStartup=true` ve en az 14 karakterlik `InitialAdminPassword` gerekir; bu da A4-03'teki gerçek veri seed'ini yükler.

**Öneri:** Kalıcı geliştirme klasöründe (`Documents\DengeERP_Gelistirme`) : .NET 10 SDK + SQL Server Express/LocalDB kurulumu; `appsettings.Development.json`'a (depoya girmeyecek `appsettings.Development.local.json` veya `dotnet user-secrets`) LocalDB bağlantısı, `AllowedHosts: "*"`, `Urls: http://localhost:5050`; sentetik test seed'i (A4-02). Bu adımlar “c-b-a” sırasındaki yeni geliştirmelerin önkoşuludur.

---

### A4-12 — ORTA — Seed ve kaynak arşivleri yayın paketine/sunucuya da kopyalanıyor

**Konum:** `DengeERP.Api.csproj:15-19` (`Database\**\*.sql` → çıktıya kopyalanır), `linux/02_yayinla.sh:26-29` (`/opt/dengeerp/releases/<sürüm>/Database/` — dizinler `0755`, dosyalar `cp -a` ile kaynak izinleriyle).

**Ayrıntı:** Gerçek müşteri listesini içeren 309 KB seed her sürümde uygulama sunucusuna kopyalanır ve sunucudaki her yerel kullanıcı tarafından okunabilir (doğrulanmadı — dosya izinleri kaynağa bağlı). Bayrak kapalıyken bu betiklere çalışma zamanında ihtiyaç yok.

**Öneri:** Seed'i yayın çıktısından çıkarın (A4-02/A4-03); migration betikleri gerekiyorsa `0640 root:dengeerp` ile kopyalayın.

---

### A4-13 — ORTA — Oturumların bellekte tutulması: her yayın/yeniden başlatma tüm kullanıcıları düşürür

**Konum:** `Program.cs:21`, `linux/02_yayinla.sh:40` (`systemctl restart`), `dengeerp.service:13` (`Restart=on-failure`), istemci `app.js:91` (401'de yerel çıkış).

**Ayrıntı:** Her yayın, geri dönüş veya çökme sonrası yeniden başlatmada tüm kullanıcılar oturumdan düşer; sahada form doldururken (bakım formu, süre girişi) kaydedilmemiş veri kaybolur. Çoklu örnek/yük dengeleme mümkün değildir. Yayın betiğinde “kullanıcılara bildir / mesai dışı yap” uyarısı yok.

**Öneri:** Kısa vadede yayınları mesai dışına alın ve `02_yayinla.sh`'a uyarı ekleyin. Orta vadede oturumları `dbo.ErpSessions(TokenHash, UserId, ExpiresAt, LastSeenAt)` tablosuna taşıyın (A4-01 ile birlikte, token'ın SHA-256 özeti saklanarak).

---

### A4-14 — ORTA — İş emri durum makinesi yok; kapanış durumları tutarsız

**Konum:** `Program.cs:473-543` (`request.Status` hiçbir listeyle doğrulanmıyor), `Program.cs:527` (`ClosedAt` yalnızca `Kapatıldı`'da set ediliyor, `Tekrar Açıldı`'da temizlenmiyor), `Program.cs:2808` (`IsClosingStatus` = Tamamlandı/Kapatıldı/**Çözüldü**), `Program.cs:3316-3317` (`IsBulkClosedStatus` = Tamamlandı/Kapatıldı/**İptal**), `OpsSuite.cs:8` (`Open` = Kapatıldı/Tamamlandı/İptal dışı), `app.js:30-31` (istemci listelerinde `Çözüldü` yok), `app.js:131` (`isOpen` yalnızca Kapatıldı/İptal'i kapalı sayıyor), `Program.cs:477` (`workorders.edit` tek başına kapatmaya yetiyor).

**Ayrıntı:** (1) API herhangi bir metni durum olarak kabul eder; `Müşteri Talebi → Kapatıldı` gibi atlamalar ve geri dönüşler serbesttir. (2) `Çözüldü` yalnızca sunucuda var (ölü kod). (3) `Tamamlandı` olan işlerde `ClosedAt` boş kalır → Excel'de “kapanış tarihine göre” filtre bu işleri dışarıda bırakır (Program.cs:2207). (4) `Tekrar Açıldı` sonrası `ClosedAt` eski değeriyle kalır. (5) “Açık iş” tanımı ekranlar arasında farklı (`app.js:131` Tamamlandı'yı açık, `OpsSuite.cs:8` kapalı sayıyor). (6) `İptal` kapanış kontrollerinden (aktif sayaç, seri no) geçmiyor. (7) `workorders.close` izni fiilen işlevsiz (edit yeterli).

**Öneri:** Sunucu tarafında tek bir durum kataloğu ve izinli geçiş tablosu (örn. `Tamamlandı` = teknisyen bitirdi, `Kapatıldı` = şef onayladı; yalnız `workorders.close` sahibi `Kapatıldı` yapabilir); `ClosedAt`/`CompletedAt`'i ayrı tutun ve yeniden açılışta temizleyin; “açık iş” tanımını tek yardımcı fonksiyonda toplayıp hem API hem istemci kullansın. (Rol/onay akışı **varsayım** — organizasyon şemasıyla teyit edilmeli.)

---

### A4-15 — ORTA — “Kaydet” her seferinde durumu yeniden gönderiyor

**Konum:** `app.js:1668-1672` (önce `PUT …/assignments`, ardından **her durumda** `PATCH …/status`), `Program.cs:525-540` (her `Kapatıldı` gönderiminde `ClosedAt=SYSDATETIME()`; kapanış durumlarında commit sonrası `CompleteMaintenanceFromWorkOrderAsync` + `EnsureMaintenancePlansAndWorkOrdersAsync`).

**Ayrıntı:** Kapalı bir işte yalnızca atama düzeltmek için “Kaydet”e basılırsa: kapanış tarihi o ana kayar (raporlar bozulur), aynı durumla mükerrer geçmiş kaydı oluşur, kapanış yan etkileri tekrar çalışır. İki çağrı ayrı transaction olduğundan, durum adımı hata verirse (ör. cihaz bakım işi bu ekrandan kapatılamaz, Program.cs:512-513) atama değişmiş, durum değişmemiş olur (kısmi güncelleme). Ayrıca kapanışın yan etkisi olarak **tüm sözleşmeler için** bakım planı üretimi (`EnsureMaintenancePlansAndWorkOrdersAsync`) çalışır; burada oluşan bir istisna (ör. Program.cs:2996 “Bakım cihaz adedi hatalı”) kapanış commit edildikten sonra istemciye 500 döndürür — kullanıcı işi kapatamadığını sanar.

**Öneri:** İstemci yalnızca değişen alanı göndersin; sunucu `oldStatus == newStatus` ise no-op dönsün; `ClosedAt` yalnızca açık→kapalı geçişte set edilsin; bakım planı üretimini kapanıştan ayırıp günlük zamanlanmış işe/“Vadesi gelenleri üret” düğmesine bırakın.

---

### A4-16 — ORTA — Tekli planlama kapalı işi yeniden açabiliyor; toplu yeniden planlama yok

**Konum:** `Program.cs:722-761` (durum ön koşulu yok; `Status=N'Planlandı'` koşulsuz; `InsertStatusLogAsync(..., null, "Planlandı", ...)` eski durumu `NULL` yazıyor), karşılaştırma: toplu planlama `Program.cs:682-683` kapalı ve **zaten planlı** işleri reddediyor.

**Ayrıntı:** `Kapatıldı`/`İptal` bir iş (cihaz bakım işi dahil) tekli planlama ile `Planlandı`ya döner; bu, “kapatılmış cihaz bakım emri tekrar açılamaz” kuralını (Program.cs:502-503) ve bakım formu kilidini (2473) dolanır. Geçmişte eski durum görünmez. Öte yandan bakım formunda “Tekrar Gidilecek” sonucu alan (WO `Beklemede`, aktif plan duruyor) aynı lokasyondaki cihaz işleri **toplu** yeniden planlanamaz (aktif plan var diye reddedilir) → tek tek planlamak gerekir.

**Öneri:** Tekli planlamaya toplu planlamadaki durum kontrolünü ekleyin, eski durumu loglayın; toplu planlamaya “yeniden planla” modu (mevcut aktif planı pasifleştirerek) ekleyin.

---

### A4-17 — ORTA — Çakışma kontrolü yalnızca tarayıcıda

**Konum:** `app.js:385, 522, 531` (takvimde “Çakışmalı iş” göstergesi), `Program.cs:649-761` (plan/bulk-plan uçlarında personel/araç çakışma sorgusu yok); proje belgesi §5.2 “Şef/teknisyen/araç çakışması denetlensin”.

**Ayrıntı:** Sunucu aynı teknisyeni veya aracı aynı saatte iki farklı sahaya planlamayı kabul eder; istemci yalnızca sonradan uyarı rozeti gösterir. Farklı kullanıcılar eşzamanlı planlama yaptığında çakışma fark edilmeyebilir.

**Öneri:** Plan kaydında sunucu tarafı kontrol: aynı `PlanDate` + `[StartTime, StartTime+EstimatedMinutes)` aralığında aynı `AssignedName` veya `VehiclePlate` olan aktif plan varsa (aynı `RouteGroupNo` hariç) 409 + çakışan iş listesi; yönetici bilinçli olarak “yine de kaydet” diyebilsin.

---

### A4-18 — ORTA — “Beklemede” iki ayrı mekanizma; bekletme geçmişe yazılmıyor

**Konum:** `OpsSuite.cs:130-145` (hold: `OpsHolds` + `Status='Beklemede'`, **`WorkOrderStatusLogs` kaydı yok**), `OpsSuite.cs:146-159` (release: yine log yok), `Program.cs:2512` (bakım formu “takip gerekli” sonucunda `Beklemede` yapıyor, `OpsHolds` kaydı açmıyor), `Program.cs:473-543` (durum ekranından elle `Beklemede` yapılabiliyor), `ops120.js:43` (“Beklemeyi Kaldır” yalnızca `holdReason` varsa görünür).

**Ayrıntı:** Aynı durum üç yoldan oluşuyor; yalnız biri neden/önceki durum tutuyor. Operasyon Merkezi “Bekleme” sayacı (`OpsSuite.cs:105`) yalnızca `OpsHolds` kayıtlılarını sayar; formdan veya elle bekletilen işler sayılmaz. Bekletilmiş iş durum ekranından kapatılırsa `OpsHolds` açık kalır ve kapalı iş “Bekleme” sayacına girer. İş emri geçmişinde bekletme/kaldırma görünmez. Aynı işe ikinci kez bekletme denenirse benzersiz indeks (ZZ_V120:11-12) nedeniyle işlenmemiş SQL istisnası → 500.

**Öneri:** Tek bir “bekletme” servisi: her `Beklemede` geçişi neden zorunlu `OpsHolds` kaydı açsın, her çıkış kapatsın; hepsi `WorkOrderStatusLogs`'a yazsın; bekleme süreleri SLA'dan düşülebilsin (A4-21).

---

### A4-19 — ORTA — Atamalar isim metni; atama değişikliği aktif sayacı kilitliyor

**Konum:** `Program.cs:3338-3347` (`AssignedName` metin), `Program.cs:1945-1947` (canlı sayaç yalnızca `AssignedName = user.FullName` ise), `Program.cs:3398-3400` (teknisyenin işe erişimi isim eşleşmesiyle), `Program.cs:1996` (sayaç bitirmek için de erişim gerekli), `Program.cs:545-570` (tekli atama: durum kontrolü ve iz kaydı yok; toplu atama 609-610 log yazıyor), `app.js:23-29, 1604` (`personnelFallback` sabit isimleri seçeneklere ekliyor).

**Ayrıntı:** (1) Personel kaydındaki ad ile ERP kullanıcısının `FullName`'i birebir aynı değilse (ör. “Ali Kaya” / “Ali KAYA” SQL harmanlamasına göre, “Burak Mehmet Şahinbaş” / “Burak Şahinbaş”) teknisyen işini göremez, sayaç başlatamaz. (2) Sabit `personnelFallback` listesindeki isimle atanan ama hesabı farklı adla açılmış kişi aynı sorunu yaşar. (3) Sayacı çalışan teknisyen atamadan çıkarılırsa kendi sayacını **bitiremez** (erişim reddi); yalnızca yönetici iptal edebilir ve o süre kişi-saate girmez. (4) Tekli atama değişikliği geçmişe yazılmaz; kapalı işlerde de atama değiştirilebilir.

**Öneri:** `WorkOrderAssignments`'a `PersonnelId`/`ErpUserId` kolonu ekleyip (isim gösterim için kalsın) eşleştirmeyi kimlik üzerinden yapın; `personnelFallback`'i kaldırın; atamadan çıkarılan kişinin açık sayacı varsa atamayı engelleyin veya sayacı otomatik kapatın; tekli atamada da status log yazın.

---

### A4-20 — ORTA — Süre kaydı olmayan iş “0” gösteriliyor (karar ihlali)

**Konum:** `OpsSuite.cs:82, 88` (`recordedMinutes = minutes.GetValueOrDefault(id, 0)`), `OpsSuite.cs:230-234` (süre kaydı yoksa `hours=0` → `labor=0` → `margin` olduğundan yüksek), `ops120.js:19-21` (Maliyet Analizi toplamları ve tablo bu değerleri “eksik” ayrımı olmadan gösteriyor), `app.js:1640` (“Toplam 0 kişi-saat kayıtlıdır”, ayrıca yuvarlanmamış ondalık). Doğru örnek: Excel `Program.cs:3666` (“Süre Kaydı Eksik İş”).

**Ayrıntı:** Kullanıcı kararı: “süre kaydı yoksa ‘eksik’ denir, 0 değil”. Operasyon Merkezi API'si ve Maliyet Analizi bunu uygulamıyor; özellikle maliyet ekranında süresi girilmemiş iş “işçilik 0 TL, yüksek kâr” görünür.

**Öneri:** API `recordedMinutes: null` + `timeLogStatus: "eksik"` döndürsün; maliyet satırında `laborStatus: "eksik"` ve toplamlarda “X işte süre kaydı eksik — işçilik hesaplanamadı” uyarısı; iş detayında 0 yerine “Süre kaydı eksik”.

---

### A4-21 — ORTA — SLA planlı bakımlara da uygulanıyor; bekleme düşülmüyor; kapanmış işte ölçüm yok

**Konum:** `OpsSuite.cs:29-32` (tüm açık işler için `CreatedAt + SLA saati` < şimdi → “Kritik” uyarı), `OpsSuite.cs:87` (`overdue`), `OpsSuite.cs:102` (gecikme sayacı), `Program.cs:3086` (PB işleri `Normal` öncelik ve ayın 1'inde oluşturuluyor).

**Ayrıntı:** Ayın başında toplu açılan onlarca PB iş emri 72 saat sonra “Geciken” olur ve uyarı listesini doldurur; günlük arızaların gerçek gecikmesi bu gürültüde kaybolur. `Beklemede` (müşteri onayı, malzeme) süresi SLA'dan düşülmez. Kapanan işler için “SLA içinde mi kapandı” hesaplanmıyor; yönetsel KPI yalnızca anlık açık işlere bakıyor. (Ekranda “takvim saati” uyarısı var — ops120.js:47 — bu bilinçli sınır.)

**Öneri (c/b):** PB işleri için SLA'yı hedef tarih (`MaintenancePlans.TargetDate`, ay sonu) üzerinden ayrı ölçün; günlük servis SLA'sında `OpsHolds` sürelerini düşün; kapanışta `SlaMet` / `SlaMinutes` hesaplayıp raporlara ekleyin. Sözleşme/mesai takvimi bazlı SLA ileriki sürüm.

---

### A4-22 — ORTA — Yedek parça akışı bakım formu ve iş emriyle bağlantısız

**Konum:** `Program.cs:2515` (bakım formunda `SpareParts` serbest metin), `OpsSuite.cs:188-213` (stok çıkışı ayrı ekrandan, iş emri **ID** ile), `ZZ_V120_Operations.sql:21, 24` (servis stoku `RentalWarehouses` tablosuna bağlı), `ops120.js:84-92` (parça ID, depo ID, tür, miktar, iş emri ID `prompt` ile), `OpsSuite.cs:193` (kapalı işe de çıkış yapılabiliyor).

**Ayrıntı:** Teknisyen formda “kullanılan parça”yı metin olarak yazar; depo ayrıca stok çıkışı girer — iki kayıt uzlaştırılmaz, maliyet analizindeki malzeme yalnızca ikinciden gelir. Servis yedek parça stoku ile kiralama cihaz deposu aynı depo tablosunu paylaşıyor (proje belgesi §5.11 bunların “farklı iş mantıkları” olmasını istiyor). Arayüz, kullanıcının parça/depo ID'lerini ezbere bilmesini gerektiriyor (stok tablosunda depo ID'si gösterilmiyor).

**Öneri (c):** İş emri ve bakım formuna “Parça kullan” bileşeni (katalogdan seçim → stok çıkışı aynı transaction'da); `SpareParts` metnini salt “not” olarak bırakın; ayrı `ServiceWarehouses` tablosu veya `RentalWarehouses`'a `Purpose` kolonu; seçim listeli form (prompt yerine).

---

### A4-23 — ORTA — Eşzamanlı düzenlemede kayıp güncelleme

**Konum:** `Program.cs:545-570` (atamalar tamamen silinip yeniden yazılıyor), `Program.cs:722-761`, `Program.cs:473-543` (hiçbir uçta `UpdatedAt`/`rowversion` kontrolü yok), `app.js:1668-1672`.

**Ayrıntı:** Şef ve operasyon uzmanı aynı iş emrini aynı anda açıp kaydederse sonra kaydeden diğerinin atama/durum değişikliğini sessizce ezer. İstemci verisi yalnızca Operasyon Merkezi'nde 3 dakikada bir yenileniyor (ops120.js:102); diğer ekranlar eski veriyle çalışır.

**Öneri:** `WorkOrders`'a `rowversion` ekleyin; istemci okuduğu sürümü göndersin, uyuşmazlıkta 409 “Kayıt başka kullanıcı tarafından değiştirildi, yenileyin”.

---

### A4-24 — ORTA — Statik dosya sürüm parametresi hotfix sonrası değişmemiş

**Konum:** `wwwroot/index.html:8-14` (`styles.css?v=120`, `ops120.js?v=120`, `app.js?v=120`), `HOTFIX_V1201.txt:1` (V1.20.1'de `app.js` değişti), `Program.cs:15-16` (`UseStaticFiles` varsayılan; `Cache-Control` başlığı yok).

**Ayrıntı:** V1.20.1 `app.js`'i değiştirdiği hâlde sürüm parametresi aynı kaldı. Tarayıcılar `Last-Modified`'a dayalı sezgisel önbellekleme ile eski `app.js`'i kullanmaya devam edebilir (doğrulanmadı; tarayıcıya bağlı). Pilotta “Ctrl+F5” ile aşıldı ama sahadaki mobil tarayıcılarda kullanıcı bunu bilmez; tarih filtresi hatası geri dönmüş gibi görünür.

**Öneri:** Her sürümde `?v=` değerini derleme sürümünden üretin (ör. `?v=1.20.1`); `index.html` için `Cache-Control: no-cache`, sürümlü JS/CSS için uzun önbellek (`UseStaticFiles` `OnPrepareResponse` ile).

---

### A4-25 — ORTA — Linux betik eksikleri

**Konum ve ayrıntı:**
- `linux/01_sunucuyu_hazirla.sh:16` — `apt-get install dotnet-sdk-10.0` öncesinde Microsoft veya Ubuntu backports deposu eklenmiyor. Ubuntu 24.04 ana deposunda .NET 10 paketinin bulunup bulunmadığı **doğrulanmadı**; yoksa kurulum ilk adımda durur.
- `linux/02_yayinla.sh:18-21` — `dotnet publish` **root** ile ve üretim sunucusunda (NuGet'ten internetle) çalışıyor; SDK üretim sunucusunda kalıyor. Tedarik zinciri ve tekrarlanabilirlik riski.
- `linux/02_yayinla.sh:24-29` — her yayın yeni klasör; eski sürümler hiç temizlenmiyor (disk büyür).
- `linux/02_yayinla.sh:34-35`, `04_geri_don.sh:9, 12` — önceki yarım kalmış çalışmadan kalan `.current_new`/`.rollback`/`.failedback` bağlantıları varsa `ln -s` hata verir ve `set -e` ile betik durur (02'nin 42/57. satırlarında `ln -sfn` doğru kullanılmış, 34. satırda kullanılmamış).
- `linux/04_geri_don.sh:11-16` — geri dönüşte yalnızca `systemctl restart` sonucu kontrol ediliyor; `Type=simple` servis neredeyse her zaman “başarılı” döner. 02'deki gibi `/api/health` döngüsü yok; `previous_release` geri dönüşten sonra güncellenmiyor (ileri dönüş hedefi kaybolur).
- `linux/02_yayinla.sh:49, 61` — sağlık çıktısı tahmin edilebilir `/tmp/dengeerp-health.json` yoluna root olarak yazılıyor (düşük risk).

**Öneri:** Derlemeyi geliştirme makinesinde/GitHub Actions'ta yapıp yalnızca `publish` çıktısını (SHA-256 ile) sunucuya taşıyın; sunucuya yalnızca ASP.NET Core runtime kurun; son N=5 sürümü tutan temizlik; `ln -sfn` her yerde; 04'e sağlık döngüsü ve `previous_release` güncellemesi; `mktemp` ile sağlık dosyası.

---

### A4-26 — ORTA — Nginx / HTTPS / AllowedHosts yapılandırma tutarlılığı

**Konum:** `linux/nginx/dengeerp-http.conf:3-21`, `linux/nginx/dengeerp-https.conf.example:4-24`, `appsettings.json:18`, `linux/01_sunucuyu_hazirla.sh:10, 29`, `linux/02_yayinla.sh:14, 36`; `Program.cs` içinde `UseForwardedHeaders` yok.

**Ayrıntı:**
- IP `10.10.50.16` dört ayrı yerde sabit (betik kontrolleri, nginx `listen/server_name`, `AllowedHosts` — yayınlanan `appsettings.json` içinde). DNS adına geçildiğinde `AllowedHosts` güncellenmezse tüm istekler 400 alır; 03_dogrula bunu yakalamaz (Kestrel'e doğrudan `127.0.0.1` ile gider, A4-27).
- HTTPS örneğinde 80/5050 → 443 yönlendirmesi ve HSTS yok; README “5050 erişimini kaldırın” diyor ama betik yok.
- Güvenlik başlıkları yok (`X-Content-Type-Options`, `X-Frame-Options`/`frame-ancestors`, `Referrer-Policy`, CSP). Token `localStorage`'da olduğu için CSP, olası bir XSS'in etkisini azaltmada önemli.
- Ubuntu nginx paketinin varsayılan sitesi (`sites-enabled/default`, port 80) kapatılmıyor.
- `X-Forwarded-*` başlıkları gönderiliyor ama uygulama işlemiyor; ileride IP bazlı log/kilitleme yanlış IP (127.0.0.1) görür.

**Öneri:** `AllowedHosts` ve sunucu adını env'den (`AllowedHosts=…`) verin; `dengeerp.env.example`'a ekleyin; HTTPS şablonuna yönlendirme + HSTS + güvenlik başlıkları; 01'de `rm -f /etc/nginx/sites-enabled/default`; `UseForwardedHeaders` (yalnızca 127.0.0.1 güvenilir proxy).

---

### A4-27 — ORTA — Sağlık kontrolü kapsamı dar

**Konum:** `Program.cs:47-65`, `linux/02_yayinla.sh:48-53`, `linux/03_dogrula.sh:8`.

**Ayrıntı:** `/api/health` yalnızca SQL bağlantısını açıyor: şema sürümü (A4-04), saat farkı (A4-06), statik dosyaların varlığı kontrol edilmiyor. Yayın ve doğrulama betikleri Kestrel'e doğrudan (`127.0.0.1:5051`) gidiyor; Nginx `allow/deny`, `AllowedHosts`, proxy başlıkları test edilmiyor. Anonim yanıt hata ayrıntısı veriyor (A4-10).

**Öneri:** `/api/health` (anonim, yalnızca `ok/fail`) ve `/api/health/details` (yalnız localhost veya admin: şema sürümü, eksik migration, SQL/uygulama saat farkı, sürüm numarası). `03_dogrula.sh`'a `curl -H 'Host: <gerçek ad>' http://10.10.50.16:5050/api/health` adımı.

---

### A4-28 — ORTA — Loglama ve denetim izi eksik

**Konum:** `Program.cs:203-357` (kullanıcı oluşturma, yetki değiştirme, pasifleştirme, şifre sıfırlama — hiçbiri loglanmıyor), `OpsSuite.cs:130-159` (bekletme), `Program.cs:545-570` (tekli atama), `OpsSuite.cs:237-258` (tarife/maliyet değişikliği yalnızca `UpdatedBy` — önceki değer yok), `appsettings.json:12-17` (yalnızca konsol; `Microsoft.AspNetCore: Warning` — istek logu yok), `Program.cs:67-99` (başarısız giriş loglanmıyor).

**Ayrıntı:** Operasyonel sorun çözümünde ve yetki denetiminde “kim, ne zaman, neyi değiştirdi” sorusu yanıtlanamaz. Journald varsayılan boyut sınırıyla eski kayıtları siler; ayrı saklama politikası yok. Proje belgesi §8.2 “işlem denetimi” ve “loglama”yı açık iş olarak sayıyor.

**Öneri:** `dbo.AuditLog(At, UserId, Action, Entity, EntityId, OldJson, NewJson, Ip)` ve tek yardımcı fonksiyon; ilk aşamada kullanıcı/yetki, bekletme, atama, finans, stok uçları. Başarısız giriş denemeleri loglansın. Journald için `SystemMaxUse`/saklama İT ile belirlensin.

---

### A4-29 — ORTA — Cihaz kütüğü ve bakım sözleşmeleri arayüzden yönetilemiyor (yarım modül)

**Konum:** `Program.cs:2232` (`/api/security/devices` yalnız GET), `Program.cs:2288` (`/api/maintenance/contracts` yalnız GET), kodda `INSERT/UPDATE dbo.SecurityDevices` yok, `UPDATE dbo.MaintenanceContracts` yalnızca sayaç için (Program.cs:3167) — grep ile doğrulandı.

**Ayrıntı:** Yeni kurulan cihaz, değişen seri numarası/lokasyon, yeni veya yenilenen bakım sözleşmesi ancak SSMS ile girilebiliyor; bu da A4-03'teki seed ezme riskiyle birleşiyor. Bakım formunda girilen seri no/bölge (Program.cs:2514) cihaz kütüğüne geri yazılmıyor; kütük ile saha gerçeği ayrışıyor. Proje belgesi §5.3 “cihaz geçmişi, bakımlar, iş emirleri cihazla ilişkilendirilmeli” hedefini koyuyor.

**Öneri (c — yeni özellik önceliği):** Cihaz kütüğü CRUD (yetki `devices.manage` — **varsayım**), sözleşme CRUD (`maintenance.manage`), bakım formunda “kütükteki seri no ile farklı — kütüğü güncelle” onaylı akışı ve cihaz geçmişi sekmesi.

---

### A4-30 — DÜŞÜK — Canlı sayaç ile iş durumu bağımsız

**Konum:** `Program.cs:1929-1983` (sayaç başlatma durumu değiştirmiyor), `Program.cs:2077` (“İş emri durumu ayrıca kapatılabilir”), `app.js:30` (`Yola Çıkıldı`, `Sahada`, `İşlemde` elle seçiliyor).

**Ayrıntı:** Teknisyen “Yol / Ulaşım” sayacını başlatsa da iş `Planlandı` kalır; Ana Panel'deki “Sahada” sayısı teknisyenin ayrıca durum değiştirmesine bağlı. Çift giriş ve tutarsız KPI.

**Öneri (c):** Sayaç başlangıcında isteğe bağlı otomatik durum önerisi (`Yol / Ulaşım` → `Yola Çıkıldı`, `Saha Çalışması` → `Sahada`), durum makinesi (A4-14) kuralları içinde.

---

### A4-31 — DÜŞÜK — Tüm iş emirlerini her istekte belleğe yükleme; sessiz liste kesme

**Konum:** `Program.cs:3441-3462` (`LoadWorkOrdersAsync` filtresiz tüm tablo + alt sorgular), kullanım: `OpsSuite.cs:80, 114, 135, 150, 193, 218, 250, 263`; `Program.cs:365, 1913, 2186, 2197`; liste kesme `OpsSuite.cs:106` (`Take(1500)`), `ops120.js:43` (`slice(0,250)`), `ops120.js:21` (`slice(0,350)`).

**Ayrıntı:** Tek bir iş emrini bekletmek veya bir stok hareketi kaydetmek için bile tüm iş emirleri ve tüm süre kayıtları okunuyor. 1.324 cihaz × yıllık 2–4 bakım ile yıllık binlerce PB kaydı birikecek; yanıt süreleri büyür. Listeler kullanıcıya “ilk 250” olduğu söylenmeden kesiliyor.

**Öneri:** Tekil kontroller için `CanAccessWorkOrderAsync` kullanın; listelerde tarih/durum filtresi ve sayfalama; kesme olduğunda “X kayıttan ilk 250'si” notu.

---

### A4-32 — DÜŞÜK — Doküman ve yapılandırma tutarsızlıkları

**Konum ve ayrıntı:**
- `PILOT_V120_KURULUM_VE_TEST.txt:44` “ilk açılışta SQL migration otomatik uygulanır” — V1.20.1 kodunda varsayılan kapalı (`appsettings.json:20`).
- `PILOT_KURULUM.txt:26` bağlantı dizesini `appsettings.json`'da tarif ediyor — dosyada artık `ConnectionStrings: {}` var (başında “ARŞİV” notu bulunuyor ✔).
- `linux/README_KURULUM_TR.md:25` ZIP adı `DengeERP_LINUX_V1_20_1_10_10_50_16.zip`, `IT_ICIN_ILK_OKU.md:24` ise `DengeERP_V1_20_1_LINUX_IT_TAM_TESLIM_10_10_50_16.zip` diyor.
- `appsettings.json:4-11` e-posta ayarı (parola dahil) düz metin `appsettings.json` içinde tasarlanmış; `linux/dengeerp.env.example` içinde `Email__*` anahtarları yok → Linux'ta teklif e-postası nasıl açılacağı belirsiz.
- `dengeerp.service:2` açıklamada sürüm sabit (`V1.20.1`) — her sürümde unutulabilir.

**Öneri:** Tek “KURULUM.md” (Windows geliştirme + Linux) ve sürümle güncellenen CHANGELOG; env şablonuna `Email__SmtpHost`, `Email__Username`, `Email__Password` (boş) ve `AllowedHosts` ekleyin.

---

## 4. Önerilen uygulama sırası (kullanıcı önceliği c → b → a ile uyumlu)

| Sıra | Ne | Neden bu sırada |
|---|---|---|
| 0 (hemen, ön koşul) | A4-02 (GitHub öncesi veri temizliği), A4-11 (yerel ortam), A4-01 (oturum düşürme — 3 satır) | GitHub geçişi birkaç gün içinde; geliştirme bu makinede yapılacak; A4-01 KRİTİK ve çok küçük düzeltme |
| 1 (c — yeni/geliştirilen özellikler) | A4-29 cihaz/sözleşme yönetimi, A4-22 parça kullanımı iş emrinde, A4-30 sayaç–durum bağlantısı, A4-21 PB için hedef tarih bazlı SLA | Kullanıcının birinci önceliği; mevcut modülleri tamamlayan özellikler |
| 2 (b — mevcut modül eksikleri) | A4-07 yıl dönümü (31.12.2026'dan önce!), A4-08 İK girişi, A4-14/15/16 durum ve planlama tutarlılığı, A4-17 çakışma, A4-18 bekletme, A4-19 kimlik bazlı atama, A4-20 “eksik” gösterimi, A4-23 eşzamanlılık | A4-07'nin son tarihi var; diğerleri günlük operasyonun doğruluğunu belirliyor |
| 3 (a — üretime hazırlık) | A4-04 migration, A4-03 seed, A4-05 yedek, A4-06 saat dilimi, A4-09/10 hata yönetimi, A4-13 kalıcı oturum, A4-24…A4-28 kurulum/izleme | Linux geçişinden önce tamamlanmalı; A4-06 ve A4-05 Linux pilotu başlamadan zorunlu |

> Not: A4-07 (yıl dönümü) öncelik sırasında (b) grubunda olsa da **takvim kısıtı** nedeniyle 2026 sonundan önce çözülmelidir.
