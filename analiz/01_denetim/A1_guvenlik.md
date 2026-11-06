# A1 — DengeERP V1.20.1 Güvenlik Denetimi

> **Tarih:** 21 Ekim 2026
> **Kapsam:** `kaynak/V1_20_1_orijinal/DengeERP.Api` (Program.cs, OpsSuite.cs, wwwroot/app.js, wwwroot/ops120.js, wwwroot/index.html, Database/*.sql, appsettings*, launchSettings, Start-Pilot.bat) ve `linux/` kurulum dosyaları.
> **Yöntem:** Statik kod incelemesi. Uygulama çalıştırılmadı, canlı veritabanına bağlanılmadı. Kaynak koda dokunulmadı.
> **Doğrulama düzeyleri:** "Kodla doğrulandı" = ilgili satırlar okunarak teyit edildi. "Doğrulanmadı" = davranış çalışma zamanına ya da canlı veriye bağlı, tahmindir.
> **Kullanıcı kararları:** Öncelik sırası (c) yeni özellik, (b) modül eksikleri, (a) güvenlik/üretime hazırlık. Buna rağmen veri sızıntısı veya hesap ele geçirme yaratan açıklar **KRİTİK** olarak işaretlendi. Rol önerileri, organizasyon şeması gelmediği için **varsayımdır**.

---

## 1. Özet

DengeERP'nin temel güvenlik yapı taşları sağlam: tüm SQL sorguları parametreli, parolalar PBKDF2-SHA256 (120.000 tur) ile saklanıyor ve sabit zamanlı karşılaştırılıyor, oturum belirteci 256 bit rastgele üretiliyor, istemci tarafında HTML kaçışı (`esc`) tutarlı kullanılmış, CSV dışa aktarımlarında formül enjeksiyonu engellenmiş. Kimlik doğrulama `Authorization: Bearer` başlığıyla yapıldığı ve çerez kullanılmadığı için klasik CSRF riski yok.

Asıl sorunlar **yetkilendirme modelinde** ve **oturum yaşam döngüsünde**:

1. **Yetki yükseltme (KRİTİK):** `users.manage` izni olan herkes (İnsan Kaynakları ve Teknik Servis Müdür Yardımcısı rolleri dahil) kendine veya başkasına `*` (tam yetki) verebiliyor, Admin hesabının parolasını sıfırlayıp o hesapla girebiliyor.
2. **Fiyat/maliyet sızıntısı (KRİTİK):** "Fiyat API seviyesinde gizlenmeli" kararına rağmen teklif tutarları (`/api/offers`, teklif PDF'i) ve atölye tamir bedeli (`repairAmount`) `finance.prices.view` kontrolü olmadan dönüyor. Teknisyen rolü atölye kayıtlarının tamir bedelini görüyor.
3. **Bilinen demo hesaplar (KRİTİK, canlı DB'de doğrulanmadı):** Eski pilot veritabanında parolası belgelerde yazılı demo hesaplar (admin dahil) bulunabilir. Giriş denemesi sınırı da olmadığından bu hesaplar kolayca ele geçirilebilir.
4. **Oturum yönetimi (YÜKSEK):** Oturumların süre sonu yok. Kullanıcı Kullanıcı/Yetki ekranından pasif yapıldığında veya parolası sıfırlandığında açık oturumu **düşmüyor**. Pasif yapılan kişi servis yeniden başlatılana kadar sisteme erişmeye devam ediyor.
5. **Şifresiz HTTP (YÜKSEK):** Windows pilot Wi-Fi üzerinden düz HTTP ile yayında. Parola ve oturum belirteci ağda açık metin taşınıyor.

SQL injection ve XSS için **somut bir açık bulunmadı** (ayrıntı bölüm 4).

Toplam **21 bulgu**: 3 KRİTİK, 5 YÜKSEK, 9 ORTA, 4 DÜŞÜK.

### Önerilen ele alış (kullanıcı öncelik sırasıyla uyumlu)

Kullanıcı önceliği (c) → (b) → (a). Güvenlik işleri bu nedenle büyük bir "güvenlik sürümü" olarak değil, **küçük ve artımlı adımlarla** önerildi. Ancak A1-01, A1-02 ve A1-03 için birkaç saatlik "hızlı kazanım" düzeltmelerinin, yeni özelliklerden **önce** veya ilk yeni özellik sürümüyle **birlikte** yapılması önerilir. Gerekçe: bu üç açık yeni özellik geliştirmesinden bağımsızdır ve mevcut pilot verisini bugün etkiler.

| Dalga | İçerik | Tahmini efor |
|---|---|---|
| **0 — Hızlı kazanım (yeni özellikten önce)** | A1-01 (yalnız Admin `*` verebilsin, Admin hesabına dokunulamasın), A1-02 (teklif/atölye fiyat alanlarını API'de maskele), A1-03 (demo hesapları kapat), A1-04'ün "pasif/parola sıfırlamada oturumu düşür" kısmı | 1 gün |
| **1 — Yeni özellik sürümlerine eşlik eden** | A1-05 (giriş sınırlama), A1-04 (oturum süre sonu), A1-07, A1-09, A1-11, A1-14 | 2–3 gün, sürümlere yayılarak |
| **2 — Linux/üretim öncesi** | A1-06 (HTTPS), A1-12 (Production ortamı, hata yönetimi), A1-16 (denetim izi), A1-17 (sırlar), A1-18 (güvenlik başlıkları), A1-15 (KVKK) | İT ile birlikte |
| **3 — Modül geliştirmeleriyle birlikte** | A1-08 (isim yerine kimlik bazlı atama), A1-13, A1-19, A1-20, A1-21 | Modül refaktörleriyle |

---

## 2. Bulgular tablosu (önem sırasıyla)

| ID | Önem | Başlık | Ana konum |
|---|---|---|---|
| A1-01 | KRİTİK | `users.manage` ile tam yetki (`*`) verme / Admin hesabını ele geçirme | Program.cs:203-243, 245-319, 321-357, 1777-1811, 2805 |
| A1-02 | KRİTİK | Teklif tutarları ve atölye tamir bedeli `finance.prices.view` olmadan API'den dönüyor | Program.cs:790-798, 883-893, 3520-3539, 2599 |
| A1-03 | KRİTİK | Eski pilot DB'deki bilinen demo hesaplar (doğrulanmadı) | PILOT_KURULUM.txt:42-49, IT_ICIN_ILK_OKU.md:48 |
| A1-04 | YÜKSEK | Oturum: süre sonu yok, pasifleştirme/parola sıfırlama oturumu düşürmüyor | Program.cs:21, 92-98, 321-357, 2821-2825 |
| A1-05 | YÜKSEK | Giriş denemesi sınırı/kilitleme yok; kullanıcı adı zamanlama ile tespit edilebilir | Program.cs:67-99 |
| A1-06 | YÜKSEK | Parola ve belirteç Wi-Fi/LAN üzerinden şifresiz HTTP ile taşınıyor | Program.cs:12, Start-Pilot.bat:11, launchSettings.json:8,17, linux/nginx/dengeerp-http.conf:4 |
| A1-07 | YÜKSEK | `personnel.manage` ile Admin dahil herhangi bir ERP hesabı kapatılabiliyor; personelde birim kapsamı yok | Program.cs:1834-1903 |
| A1-08 | YÜKSEK | Teknisyen kapsamı rol **adına** ve **ad soyad metnine** bağlı; atölyede teknisyen kapsamı hiç yok | Program.cs:3398-3400, 3499-3500, 2120, 2560-2626 |
| A1-09 | ORTA | Teklif durumunu değiştirmede birim kontrolü ve görev ayrılığı yok | Program.cs:861-881, 829 |
| A1-10 | ORTA | Teklif e-postası keyfi alıcıya gönderilebiliyor; SMTP hata metni istemciye dönüyor | Program.cs:895-958 |
| A1-11 | ORTA | "Şifre değiştirme zorunlu" sunucuda uygulanmıyor; şifre değiştirmede mevcut şifre sorulmuyor | Program.cs:114-137, 2821-2825 |
| A1-12 | ORTA | Hata ve ortam bilgisi sızıntısı (`/api/health`, Development ortamı, işlenmeyen hatalar) | Program.cs:47-65, 76; launchSettings.json:10,19 |
| A1-13 | ORTA | Boş `AllowedUnits` = tüm birimler (güvensiz varsayılan) | Program.cs:216, 256-258, 1797, 2807, 3497 |
| A1-14 | ORTA | İş emri durumu serbest metin; "İptal" ve atölye ekranı üzerinden kapanış kuralları atlanabiliyor | Program.cs:473-543, 2707-2776 |
| A1-15 | ORTA | KVKK: kişisel veriler kapsam, maskeleme, saklama süresi ve erişim kaydı olmadan sunuluyor | Program.cs:1733-1768, 2191-2229, 993-1049 |
| A1-16 | ORTA | Denetim izi eksik (kullanıcı/yetki/parola/teklif/maliyet değişiklikleri) | Program.cs:245-357, 861-881; OpsSuite.cs:237-258 |
| A1-17 | ORTA | Sır yönetimi: SMTP parolası için düz metin `appsettings.json` öneriliyor | appsettings.json:4-11, PILOT_KURULUM.txt:92 |
| A1-18 | DÜŞÜK | Güvenlik başlıkları yok; belirteç `localStorage`'da (XSS olursa etki büyür) | Program.cs:15-16, app.js:35, 2032 |
| A1-19 | DÜŞÜK | Küçük IDOR / kapsam boşlukları (kiralama envanteri, depo adı, eğitim oturumu, cihaz kütüğü) | Program.cs:1322-1374, 1598-1610, 1649-1666, 2232-2285, 2360-2376 |
| A1-20 | DÜŞÜK | Hizmet engelleme (DoS) riski: her istekte tüm iş emirleri belleğe alınıyor, istek hızı sınırı yok | Program.cs:3441-3493, 536-540 |
| A1-21 | DÜŞÜK | Başlangıçta `Database/*.sql` dosyalarının otomatik yürütülmesi | Program.cs:26-41, 3257-3269 |

---

## 3. Bulgu ayrıntıları ve öneriler

### A1-01 — KRİTİK — `users.manage` ile tam yetki verme / Admin hesabını ele geçirme

**Konum:**
- `POST /api/users` Program.cs:203-243. `request.Permissions` hiç süzülmeden `JoinPipe(permissions)` ile yazılıyor (213-215, 234).
- `PUT /api/users/{id}` Program.cs:245-319. Aynı şekilde `Permissions`, `RoleName`, `AllowedUnits` süzülmüyor. Hedef kullanıcının kim olduğu (Admin mi, kendisi mi) kontrol edilmiyor.
- `PATCH /api/users/{id}/status` Program.cs:321-336. Yalnızca "kendini pasif yapma" engelli. Admin hesabı pasif yapılabiliyor.
- `POST /api/users/{id}/reset-password` Program.cs:338-357. Admin dahil herkesin parolası sıfırlanabiliyor.
- `POST /api/personnel` (`CreateUser=true`) Program.cs:1777-1811. Aynı süzülmemiş izin listesi.
- `IsAdmin` Program.cs:2805: `user.Permissions.Contains("*") || user.RoleName == "Admin"`. Rol adı serbest metin olduğu için `RoleName="Admin"` yazmak tek başına birim kısıtlarını kaldırıyor.
- `users.manage` sahibi roller: Catalog.RoleDefaults Program.cs:3924-3926 (Üst Yönetim, Teknik Servis Müdürü, **Teknik Servis Müdür Yardımcısı**) ve 3934 (**İnsan Kaynakları**).
- `users.manage`, kullanıcı yönetimi dışında da genel yönetici izni gibi kullanılıyor: canlı sayaç iptali (2084) ve süre kaydı iptali (2170).

**Kodla doğrulandı.**

**Senaryo:** İK kullanıcısı tarayıcı geliştirici araçlarından `PUT /api/users/{kendi id}` gönderir: `{"permissions":["*"],"roleName":"Admin",...}`. Sunucu oturumu anında günceller (297-298), kullanıcı tüm birimlerin iş emirlerine, fiyatlara ve maliyetlere erişir. Alternatif olarak `reset-password` ile `admin` hesabının parolasını belirleyip o hesapla girebilir. İz bırakmaz, çünkü bkz. A1-16.

**Öneri (artımlı):**
1. Sunucuda bir "verilebilir izin" kuralı: `*` ve `users.manage` yalnızca `*` sahibi tarafından verilebilsin. Genel kural: bir kullanıcı **kendi sahip olmadığı** bir izni başkasına veremesin.
2. `RoleName` yalnızca `Catalog.RoleDefaults` anahtarlarından biri olabilsin. `IsAdmin` yalnızca `*` iznine baksın, rol adına bakmasın.
3. Hedef kullanıcı `*` sahibiyse (Admin), yalnızca başka bir `*` sahibi düzenleyebilsin, pasif yapabilsin ya da parolasını sıfırlayabilsin. Son aktif Admin pasif yapılamasın.
4. Kullanıcı kendi izinlerini değiştiremesin (`current.UserId == id` iken `Permissions`/`RoleName`/`AllowedUnits` değişikliği reddedilsin).
5. İzin listesi `Catalog.PermissionCatalog` anahtarlarıyla sınırlansın; bilinmeyen anahtarlar reddedilsin.
6. Sayaç ve süre kaydı iptalinde `users.manage` yerine `workorders.assign` ya da yeni `timetracking.manage` izni kullanılsın.
7. **Rol önerisi (varsayım, organizasyon şeması bekleniyor):** İK rolünden `users.manage` kaldırılsın. Yerine "personel kaydı oluştur + hesap açma talebi" akışı düşünülebilir. Müdür Yardımcısı için `users.manage` gerekip gerekmediği kullanıcıyla teyit edilmeli.

---

### A1-02 — KRİTİK — Fiyat/maliyet alanları yetkisiz kullanıcıya API'den dönüyor

**Konum:**
- `GET /api/offers` Program.cs:790-798 yalnızca `offers.view` istiyor. `LoadOffersAsync` (3520-3539) `SubTotal`, `DiscountTotal`, `VatTotal`, `GrandTotal` alanlarını her zaman döndürüyor.
- `GET /api/offers/{id}/pdf` Program.cs:883-893: PDF'te kalem birim fiyatları ve toplamlar var (`BuildSimpleOfferPdf` 3588-3594). `finance.prices.view` kontrolü yok.
- `offers.view` sahibi ama `finance.prices.view` sahibi **olmayan** roller (Program.cs:3927-3933): Genel Koordinatör, Operasyon Uzmanı, Şef, Muhasebe, Kiralama Operasyon.
- `GET /api/workshop/tickets` Program.cs:2560-2626: `repairAmount` (2599) koşulsuz dönüyor. Teknisyen rolü `workshop.view` iznine sahip (3930) ve ayrıca `workorders.view` izni de bu ucu açıyor (2564).
- Arayüz de aynı veriyi gösteriyor: app.js:1214 (teklif tablosu "Toplam"), app.js:1277 (Muhasebe görünümü), app.js:706 (Tamir Bedeli alanı).

**Kodla doğrulandı.** Karşılaştırma için doğru yapılmış örnekler: bakım sözleşmesi ücreti (Program.cs:2329-2333), yedek parça iç maliyeti (OpsSuite.cs:173), maliyet analizi (OpsSuite.cs:217).

**Etki:** Proje kararı "fiyat sütununu gizlemek yetmez, API de vermemeli" ve İT kabul listesindeki "Maliyet ve fiyat alanları yetkisiz hesapta API üzerinden erişilemez" maddesi bugün karşılanmıyor. Şef ve teknisyen rolleri müşteri teklif tutarlarını ve tamir bedellerini görebiliyor.

**Öneri:**
1. `/api/offers` ve `/api/offers/{id}/pdf` uçlarında `finance.prices.view` yoksa tutar alanları `null` dönsün. PDF ya üretilmesin (403) ya da tutarsız "iş kapsamı" PDF'i üretilsin. Bu bir iş kararıdır, kullanıcıya sorulmalı.
2. `/api/workshop/tickets` GET'te `repairAmount` için aynı maskeleme uygulansın. POST/PUT'ta `finance.prices.view` yoksa gelen `repairAmount` yok sayılıp mevcut değer korunsun. Aksi halde yetkisiz kullanıcı formu kaydettiğinde değer `null`'a döner, bu da veri kaybıdır.
3. Arayüzde `can('finance.prices.view')` koşulu ile sütun gizlensin (sunucu düzeltmesinin tamamlayıcısı).
4. **Varsayım:** Teklif **oluşturan** Operasyon Uzmanı fiyat girmek zorunda. "Fiyat girebilir ama listede göremez" mi, yoksa bu role `finance.prices.view` mi verilecek, kullanıcıyla netleştirilmeli.
5. Kabul testi: `finance.prices.view` olmayan bir hesapla `/api/offers`, `/api/offers/{id}/pdf`, `/api/workshop/tickets`, `/api/maintenance/contracts`, `/api/ops/stock` yanıtlarında tutar alanı olmadığı otomatik testle doğrulansın.

---

### A1-03 — KRİTİK — Eski pilot veritabanında bilinen demo hesaplar (doğrulanmadı)

**Konum:** PILOT_KURULUM.txt:42-47 demo hesapları listeliyor (`admin`, `operasyon`, `sef`, `teknisyen`; parolalar belgede maskelenmiş). Satır 49'a göre **admin dışındaki** hesaplar ilk girişte şifre değiştirir, yani admin hesabının zorunlu şifre değişikliği yoktu. IT_ICIN_ILK_OKU.md:48 bu hesapların şifrelerinin "sıfırlanmadığını" ve İT'nin değiştirmesi gerektiğini açıkça söylüyor. Yeni kurulumdaki `SeedUsersAsync` (Program.cs:3271-3295) doğru: demo hesap yok, admin parolası en az 14 karakter ve `MustChangePassword=1`.

**Doğrulanmadı:** Canlı Windows pilot SQL'inde bu hesapların hâlâ aktif ve eski parolalı olup olmadığı görülmedi. Linux `DengeERP_TEST` kopyası bu yedekten geri yükleneceği için aynı hesaplar oraya da taşınacak.

**Etki:** Parolası eski sürüm belgelerinde ve önceki ZIP'lerde yazılı bir Admin hesabı, giriş sınırı da olmadığından (A1-05) LAN'daki herkesin tam yetkiyle girmesine imkân verir.

**Öneri:**
1. SSMS ile hemen kontrol: `SELECT UserId,Username,RoleName,IsActive,MustChangePassword,UpdatedAt FROM dbo.ErpUsers WHERE Username IN (N'admin',N'operasyon',N'sef',N'teknisyen');`
2. Kullanılmayan demo hesaplar `IsActive=0` yapılsın. `admin` gerçek bir kişiye devredilecekse parolası sıfırlansın ve `MustChangePassword=1` yapılsın.
3. Linux test DB geri yüklendikten sonra aynı adım tekrarlansın (İT kontrol listesine eklenmeli).

---

### A1-04 — YÜKSEK — Oturum yönetimi: süre sonu yok, iptal eksik

**Konum:**
- Oturum deposu bellek içi `ConcurrentDictionary` (Program.cs:21). Oluşturma zamanı ve son kullanım zamanı tutulmuyor (`SessionUser` kaydı 3799). `GetCurrentUser` (2821-2825) yalnızca anahtar varlığına bakıyor. **Belirteç servis yeniden başlatılana kadar süresiz geçerli.**
- `PATCH /api/users/{id}/status` (321-336) kullanıcıyı pasif yapıyor ama `sessions` içinden **silmiyor**. Karşılaştırma: personel pasifleştirme (1897-1898) siliyor. Pasif yapılan kullanıcının mevcut oturumu çalışmaya devam ediyor. **Kodla doğrulandı.**
- `POST /api/users/{id}/reset-password` (338-357) mevcut oturumları düşürmüyor. Parolası ele geçirilip sıfırlanan bir hesabın saldırgan oturumu açık kalıyor.
- `POST /api/auth/change-password` (114-137) yalnızca o anki belirteci güncelliyor, diğer cihazlardaki oturumları kapatmıyor.
- Belirteç `localStorage`'da saklanıyor (app.js:35, 2032) ve sekme kapansa da kalıcı.
- Çoklu sunucu veya yeniden başlatmada tüm oturumlar düşüyor (işlevsel kısıt, güvenlik açığı değil).

**Öneri (artımlı, teknoloji yığınını değiştirmeden):**
1. **Hemen:** `users/status` (pasif) ve `reset-password` uçlarında `sessions` içinden ilgili `UserId` kayıtları silinsin (personel ucundaki 1897-1898 kalıbı kopyalanabilir). `change-password` sonrası diğer belirteçler silinsin.
2. `SessionUser` yanına `CreatedAt` ve `LastSeenAt` eklensin: örneğin 8–12 saat mutlak süre ve 60 dakika boşta kalma süresi (değerler kullanıcıyla netleşmeli). `GetCurrentUser` süresi dolanı silsin. Bir arka plan temizliği eklensin.
3. Orta vade: oturumlar SQL'de `ErpSessions` tablosunda belirtecin SHA-256 özetiyle tutulsun. Böylece yeniden başlatmada oturum kaybı olmaz, "tüm cihazlardan çıkış" ve denetim mümkün olur.
4. İstemci 401 aldığında zaten `logoutLocal()` yapıyor (app.js:91), ek değişiklik gerekmez.

---

### A1-05 — YÜKSEK — Giriş denemesi sınırı yok, kullanıcı adı tespit edilebilir

**Konum:** `POST /api/auth/login` Program.cs:67-99. Başarısız deneme sayılmıyor, gecikme ya da kilitleme yok. Nginx yapılandırmasında (`linux/nginx/dengeerp-http.conf`) `limit_req` yok. Kullanıcı bulunamadığında yanıt PBKDF2 hesaplanmadan hemen dönüyor (79). Kullanıcı varsa 120.000 turluk PBKDF2 çalışıyor (92). Yanıt süresi farkı, kullanıcı adının var olup olmadığını ele veriyor. Pasif kullanıcıda da (`!isActive ||` kısa devre) doğrulama atlanıyor.

**Kodla doğrulandı.** Zamanlama farkının ölçülebilirliği çalışma zamanında **doğrulanmadı**, ancak PBKDF2 120k turun onlarca milisaniye sürmesi beklenir.

**Öneri:**
1. .NET'in yerleşik `Microsoft.AspNetCore.RateLimiting` ara katmanıyla `/api/auth/login` için IP başına örneğin dakikada 10 deneme sınırı (ek paket gerekmez).
2. Kullanıcı başına sayaç (`ErpUsers.FailedLoginCount`, `LockedUntil`): örneğin 5 hatalı denemede 15 dakika kilit. Admin kilidi açabilsin.
3. Kullanıcı bulunmasa bile sahte bir PBKDF2 hesaplaması yapılsın (sabit süre).
4. Linux'ta Nginx `limit_req_zone` ile ikinci katman.
5. Başarısız ve başarılı girişler loglansın (bkz. A1-16).

---

### A1-06 — YÜKSEK — Parola ve belirteç şifresiz HTTP ile taşınıyor

**Konum:** Program.cs:12 varsayılan `http://0.0.0.0:5050`. Start-Pilot.bat:11, launchSettings.json:8 ve 17 (`https` profili de HTTP'ye bağlanıyor). linux/nginx/dengeerp-http.conf:4 (TLS yok). Proje belgesine göre Windows pilot **Wi-Fi** üzerinden `10.10.50.137` adresinden yayında.

**Kodla doğrulandı** (yapılandırma). Ağ dinlemesi test edilmedi.

**Etki:** Aynı ağdaki biri giriş isteğindeki parolayı ve her istekteki `Bearer` belirtecini görebilir. Belirteç süresiz olduğu için (A1-04) tek bir yakalama kalıcı erişim demektir.

**Öneri:**
1. Linux pilotta İT sertifikası hazır olur olmaz `dengeerp-https.conf.example` devreye alınsın. 80/5050 portları 443'e yönlendirilsin. HSTS başlığı eklensin.
2. Windows pilot geçici olduğu sürece en azından kablolu/VPN segmentiyle sınırlansın. Wi-Fi misafir ağından erişilemediği İT ile teyit edilsin.
3. Kestrel'in `UseUrls` ile sabit HTTP bağlanması yalnızca Nginx arkasında (`127.0.0.1:5051`) kalsın. Windows pilotta da `0.0.0.0` yerine Kestrel HTTPS geliştirme sertifikası düşünülebilir.

---

### A1-07 — YÜKSEK — `personnel.manage` ile ERP hesabı kapatma; personelde birim kapsamı yok

**Konum:**
- `PATCH /api/personnel/{id}/status` Program.cs:1862-1903: personel pasif yapılınca bağlı `ErpUsers` kaydı da pasif yapılıyor ve oturumları siliniyor (1890-1899). Yalnızca `personnel.manage` gerekiyor, `users.manage` gerekmiyor. Admin'in personel kaydı varsa İK Admin'i sistemden atabilir. "Kendini pasif yapamazsın" kontrolü de burada yok.
- `PUT /api/personnel/{id}` Program.cs:1834-1860: birim kontrolü yok. `UnitCode` değiştirilebiliyor. Eğitim modülünün birim kapsamı `Personnel.UnitCode`'a bağlı olduğu için (1495, 2796-2802) personeli kendi birimine çekip eğitim verilerini görmek mümkün.
- Personel–kullanıcı bağı SQL betiğinde **ad soyad eşleşmesiyle** otomatik kuruluyor (Database/DengeERP_Update.sql:431).

**Kodla doğrulandı.**

**Öneri:**
1. Personel pasifleştirme bağlı ERP hesabını etkileyecekse `users.manage` de istensin. Değilse yalnızca personel kaydı pasif yapılsın ve "bağlı hesap aktif kaldı, Kullanıcı/Yetki'den kapatın" uyarısı dönsün. Admin (`*`) hesabına bağlı personel için A1-01'deki koruma uygulansın.
2. Personel GET/PUT/PATCH için `UnitAllowed(current, personel.UnitCode)` kontrolü eklensin. `UnitCode` değişikliği için hem eski hem yeni birime yetki istensin.
3. Ad soyadla otomatik hesap bağlama betiği yeniden çalıştırılmamalı. Bağlantı yalnızca ekrandan, açıkça kurulmalı.

---

### A1-08 — YÜKSEK — Teknisyen kapsamı rol adı ve ad soyad metnine bağlı

**Konum:**
- `CanAccessWorkOrderAsync` Program.cs:3398: `if (user.RoleName != "Teknisyen") return true;`. `FilterWorkOrdersForUser` 3499: `if (user.RoleName == "Teknisyen")`. Kısıtlama yalnızca rol adı **tam olarak** "Teknisyen" ise uygulanıyor. Teknisyen izinleriyle açılmış ama rol adı farklı (ör. "Şef" rol adıyla kısıtlı izinler, ya da A1-01 nedeniyle serbest metin rol adı) bir kullanıcı biriminin **tüm** iş emirlerini görür ve düzenler.
- Atama ve sahiplik `AssignedName` metniyle `user.FullName` karşılaştırılarak yapılıyor (3400, 3500, 1945-1947, 2135). Aynı ad soyada sahip iki personel birbirinin işlerini görür. `users.manage` sahibi bir kullanıcının `FullName` alanını değiştirerek başkasının işlerine erişim verebilir (PUT /api/users 268).
- Süre kaydı (2120): rol adı "Teknisyen" değilse istekteki `TechnicianName` kullanılıyor. Kısıtlı izinli ama farklı rol adlı bir kullanıcı başkası adına süre yazabilir.
- **Atölye kayıtları teknisyen kapsamında değil:** `GET /api/workshop/tickets` (2560-2626) Haberleşme biriminin **tüm** atölye kayıtlarını (müşteri e-posta, telefon, adres, tamir bedeli) döndürüyor. `PUT /api/workshop/tickets/{id}` (2707-2776) `CanAccessWorkOrderAsync` çağırmıyor.

**Kodla doğrulandı.**

**Öneri:**
1. Kısa vade: "kendi işini görür" kuralını rol adından ayırıp yeni bir izne bağlamak (ör. `workorders.view.all` yoksa yalnızca atanan işler). Rol varsayılanlarında Teknisyen dışındaki tüm rollere bu izin eklenir. **Varsayım:** hangi rollerin tüm birim işlerini göreceği organizasyon şemasıyla teyit edilmeli.
2. Orta vade (modül geliştirmesiyle): `WorkOrderAssignments` tablosuna `PersonnelId`/`ErpUserId` sütunu eklenip eşleştirme kimlikle yapılsın. İsim metni yalnızca görüntü için kalsın. Bu değişiklik planlama/toplu atama modülü geliştirmesine eklenebilir.
3. Atölye GET/PUT uçlarına aynı teknisyen kapsamı uygulansın.

---

### A1-09 — ORTA — Teklif durum değişikliğinde birim kontrolü ve görev ayrılığı yok

**Konum:** `PATCH /api/offers/{id}/status` Program.cs:861-881: yalnızca `offers.approve` kontrol ediliyor. Teklifin `UnitCode`'u yüklenip `UnitAllowed` ile karşılaştırılmıyor. Bu yüzden başka birimin teklifi kimlikle (IDOR) onaylanabiliyor veya reddedilebiliyor. Teklifi oluşturan kişinin kendi teklifini onaylaması engellenmiyor. "Onaylandı" durumundan "Taslak" durumuna geri dönüş de serbest. `POST /api/offers` (829) içindeki `WorkOrderId`'nin kullanıcının erişebildiği bir iş emri olduğu doğrulanmıyor. Başka birimin iş emrine teklif bağlanabiliyor ve teklif listesinde o iş emrinin numarası görünüyor.

**Kodla doğrulandı.**

**Öneri:** Teklif yüklenip `UnitAllowed` kontrolü eklensin. İzinli durum geçişleri tanımlansın. Oluşturan ile onaylayan aynı kişi olamasın (iş kuralı, kullanıcıya teyit ettirilmeli). `WorkOrderId` için `CanAccessWorkOrderAsync` çağrılsın.

---

### A1-10 — ORTA — Teklif e-postası keyfi alıcıya; SMTP hata metni sızıntısı

**Konum:** `POST /api/offers/{id}/send` Program.cs:895-958. `request.Recipient` (906) müşteri e-postasından bağımsız olarak herhangi bir adres olabilir. Teklif PDF'i şirket SMTP'si üzerinden şirket dışındaki bir adrese gönderilebilir. Gönderim sayısı sınırlı değil, aynı teklif tekrar tekrar gönderilebilir (yalnızca durumu "Onaylandı" olan teklif için, 904; başarılı gönderimde durum değişiyor ama hata durumunda değişmiyor). Hata halinde `ex.Message` (936) hem `EmailLogs`'a yazılıyor hem istemciye `detail` olarak dönüyor (957). SMTP sunucu adı ve kimlik doğrulama hataları sızabilir. Başlık enjeksiyonu riski yok: `MailAddress` ayrıştırması CRLF içeren adresleri reddediyor.

**Kodla doğrulandı.** SMTP şu an yapılandırılmamış (appsettings.json:5-10), bu yüzden risk SMTP açıldığında gerçekleşir.

**Öneri:** Alıcı varsayılan olarak teklifteki `CustomerEmail` olsun. Farklı alıcı yalnızca ayrı bir izinle ve şirket alan adı/izinli listeyle sınırlansın. İstemciye genel bir hata mesajı dönsün, ayrıntı yalnızca loga yazılsın. Kullanıcı ve teklif başına gönderim sınırı konsun.

---

### A1-11 — ORTA — Zorunlu şifre değişikliği sunucuda uygulanmıyor; şifre değişikliğinde mevcut şifre sorulmuyor

**Konum:**
- `MustChangePassword` yalnızca istemcide kontrol ediliyor (app.js:2040). Sunucuda `GetCurrentUser` (2821-2825) bu bayrağa bakmıyor. Geçici şifreyle giren kullanıcı API'yi doğrudan çağırarak şifresini değiştirmeden tüm işlemleri yapabilir.
- `POST /api/auth/change-password` (114-137) mevcut şifreyi istemiyor. Belirteci çalınan birinin (A1-06, A1-18) şifreyi değiştirip hesabı kalıcı olarak ele geçirmesi mümkün.
- Parola politikası yalnızca "en az 8 karakter" (118, 210, 343). Yeni Admin için 14 karakter kuralı var (3280), diğer hesaplar için yok.

**Kodla doğrulandı.**

**Öneri:** `MustChangePassword=true` iken yalnızca `/api/auth/me`, `/api/auth/change-password` ve `/api/auth/logout` uçlarına izin verilsin (tek yardımcı fonksiyonla). `change-password` isteğine `CurrentPassword` eklensin (geçici şifreyle ilk değişiklik dahil). Minimum uzunluk 10–12 karaktere çıkarılsın, kullanıcı adıyla aynı parola reddedilsin.

---

### A1-12 — ORTA — Hata ve ortam bilgisi sızıntısı

**Konum:**
- `GET /api/health` (47-65) anonim. Hata durumunda `ex.Message` dönüyor (63). SQL sunucu adı, örnek adı, oturum açma hatası gibi bilgiler LAN'daki herkese açık.
- Windows pilot `ASPNETCORE_ENVIRONMENT=Development` ile çalışıyor (launchSettings.json:10, 19; proje belgesi bölüm 3.2). Minimal API'de Development ortamında geliştirici hata sayfası otomatik etkin. İşlenmeyen bir hata tam yığın izi, dosya yolları ve SQL ayrıntısıyla döner. **Doğrulanmadı** (çalıştırılmadı), ancak ASP.NET Core'un varsayılan davranışı budur.
- İşlenmeyen hata örnekleri: `request.Username.Trim()` (76), gövdede `username` yoksa `NullReferenceException`. Benzer şekilde `request.FullName.Trim()` gibi zorunlu varsayılan alanlar.
- `Results.Forbid()` ~100 yerde kullanılıyor ama `AddAuthentication` çağrılmıyor. ASP.NET Core'da `Forbid` sonucu bir kimlik doğrulama şeması ister. Şema yoksa 403 yerine **500 (InvalidOperationException)** üretmesi beklenir. **Doğrulanmadı**, çalıştırılarak teyit edilmeli. Erişim yine reddedilir, ama Development ortamında hata sayfası sızıntıya dönüşür ve istemci "İşlem başarısız (500)" görür.
- İstemci, JSON olmayan hata gövdesini doğrudan mesaj olarak kullanıyor (app.js:103, 1901): yığın izi kullanıcıya `alert` ile gösterilebilir.

**Öneri:**
1. Windows pilot da `ASPNETCORE_ENVIRONMENT=Production` ile çalıştırılsın (Linux env dosyası zaten Production).
2. `app.UseExceptionHandler` ile genel bir JSON hata yanıtı (`{ message: "Beklenmeyen hata", traceId }`) ve sunucu tarafı loglama.
3. `/api/health` yalnızca `{status:"ok"|"degraded"}` dönsün. Ayrıntılı kontrol yalnızca `127.0.0.1`'den ya da yetkili kullanıcıya açık olsun.
4. `Results.Forbid()` yerine `Results.StatusCode(403)` (veya `Results.Json(new{message="Yetkiniz yok."}, statusCode:403)`) kullanılsın. Bu, tek bir yardımcı fonksiyonla tüm dosyaya uygulanabilir.
5. İstek kayıtlarında zorunlu alanlar için null kontrolü yapılsın ya da DTO doğrulaması eklensin.

---

### A1-13 — ORTA — Boş `AllowedUnits` = tüm birimler

**Konum:** `UnitAllowed` (2807) ve `FilterWorkOrdersForUser` (3497): `AllowedUnits.Count == 0` ise kısıt yok. `POST /api/users` (216) ve `PUT /api/users` (256-258) boş liste gelirse **tüm birimleri** atıyor. `POST /api/personnel` (`CreateUser`) (1797) boş listeyi olduğu gibi yazıyor, bu da sınırsız erişim demek. Eğitim modülünde de aynı mantık (1491, 1723, 2801).

**Kodla doğrulandı.**

**Öneri:** Boş liste "hiçbir birim" anlamına gelsin. "Tüm birimler" ya açıkça tüm birimlerin listelenmesiyle ya da `*` izniyle ifade edilsin. Geçiş için SQL'de `AllowedUnits=''` olan aktif kullanıcılar raporlanıp yönetici onayıyla doldurulsun. Arayüzde birim seçimi zorunlu olsun.

---

### A1-14 — ORTA — İş emri durumu serbest metin; kapanış kuralları atlanabiliyor

**Konum:**
- `PATCH /api/workorders/{id}/status` (473-543): `request.Status` izinli değerler listesiyle doğrulanmıyor (kiralama ve teklifte doğrulama var: 1146-1147, 866-867). `IsClosingStatus` (2808) yalnızca "Tamamlandı", "Kapatıldı", "Çözüldü" değerlerini kapsıyor. **"İptal"** durumuna geçişte açık canlı sayaç kontrolü (506-509), bakım formu zorunluluğu (510-513) ve seri no kuralı (520-522) çalışmıyor. Cihaz bakım iş emri ana ekrandan "İptal" yapılabiliyor (yalnızca kapatılmış emrin yeniden açılması engelli, 502-503). `workorders.edit` izni (Teknisyen dahil) yeterli.
- `PUT /api/workshop/tickets/{id}` (2707-2776): atölye durumu "Teslim Edildi" gönderilince bağlı iş emri doğrudan "Kapatıldı" yapılıyor (2753, 2758-2772). Canlı sayaç, seri no kuralı ve durum geçmişi (`InsertStatusLogAsync` çağrılmıyor) atlanıyor. `request.Status` doğrulanmıyor (2868).

**Kodla doğrulandı.** Bu bulgu bir veri bütünlüğü sorunudur. Güvenlik açısından önemi, yetkili bir kullanıcının denetim kuralını (açık sayaç varken kapatmama) kayıt bırakmadan atlayabilmesidir.

**Öneri:** İzinli durum listesi ve geçiş tablosu tanımlansın. "İptal" için ayrı izin (`workorders.cancel`) ve gerekçe zorunluluğu getirilsin. Atölye PUT'u iş emri durumunu aynı merkezi durum değiştirme fonksiyonundan geçirsin (kurallar ve durum logu tek yerde).

---

### A1-15 — ORTA — KVKK: kişisel verilerin kapsam, maskeleme ve saklama kontrolü eksik

**Konum ve gözlemler:**
- `GET /api/personnel` (1733-1768): birim kapsamı yok. Tüm personelin ad, departman, unvan, yönetici, başlangıç/çıkış tarihi, **notlar**, kullanıcı adı ve rolü `personnel.view` sahibine (Genel Koordinatör, İK, Müdürler) dönüyor.
- Müşteri irtibat verileri: iş emri `CustomerEmail`, plan `SiteContact`/`SitePhone` (3448-3454), kiralama `ContactName`/`ContactPhone`/`CustomerEmail` (1003-1005, 1224), atölye `CustomerPhone`/`CustomerEmail`/`CompanyAddress` (2570-2574). Bunlar ilgili modülün görüntüleme izniyle tam olarak dönüyor. `GET /api/workorders` (359-368) tek yanıtta kullanıcının birimindeki **tüm** iş emirlerini kişisel verilerle birlikte döndürüyor.
- Çalışan performans verileri: eğitim sınav puanları, yetkinlik düzeyleri, saha gözlem notları (1503-1535), personel bazlı kişi-saat ve konum notları (2191-2229 Excel, 1908-1927). Proje kararı "zaman takibi bordro değildir" doğru, ama bu veriler yine de çalışan kişisel verisidir.
- Excel dışa aktarımı (2191-2229) saha telefonu, saha yetkilisi, teknisyen adı ve konum notlarını içeriyor. Dışa aktarma kaydı tutulmuyor.
- Saklama süresi, silme veya anonimleştirme mekanizması yok. Erişim kaydı yok (A1-16).
- Yedeklerin şifrelenip şifrelenmediği **doğrulanmadı** (`BACKUP ... WITH COPY_ONLY, CHECKSUM`, şifreleme parametresi yok: linux/SQL_HAZIRLIK_YEDEK.sql:8).

**Öneri (artımlı):**
1. Personel uçlarına birim kapsamı (A1-07 ile birlikte). Personel `Notes` alanı yalnızca `personnel.manage` sahibine dönsün.
2. Dışa aktarma işlemleri (Excel/CSV) kimin, ne zaman, hangi filtreyle indirdiği bilgisiyle loglansın.
3. Yedekler için SQL Server yedek şifrelemesi (`WITH ENCRYPTION`) veya şifreli depolama İT ile kararlaştırılsın.
4. KVKK aydınlatma metni ve çalışanlara yönelik "saha zaman/konum kaydı" bilgilendirmesi hukuk/İK ile hazırlansın (kod dışı iş).
5. Saklama süresi politikası belirlensin (ör. süre kayıtları X yıl). Bu kararı kullanıcı/hukuk vermeli.

---

### A1-16 — ORTA — Denetim izi eksik

**Konum:** İş emri durum geçmişi var (`WorkOrderStatusLogs`, 3349-3361), süre kaydı iptalinde kim iptal etti tutuluyor (2174-2176). Ancak şunlar için hiçbir kayıt yok:
- Kullanıcı oluşturma, yetki ve birim değişikliği, pasifleştirme, parola sıfırlama (203-357).
- Başarılı ve başarısız girişler (67-99).
- Teklif durum değişiklikleri (yalnızca son onaylayan tutuluyor, 873-874).
- Maliyet, gelir ve tarife değişiklikleri (OpsSuite.cs:237-258; yalnızca son güncelleyen).
- SLA hedefi değişikliği (OpsSuite.cs:122-129).
- Atama değişiklikleri (tek iş emri ataması 545-570 durum logu yazmıyor, toplu atama yazıyor 609-610).
- Excel/CSV dışa aktarımları.

Nginx `X-Forwarded-For` başlığını gönderiyor ama uygulama `UseForwardedHeaders` kullanmıyor. Uygulama loglarında istemci IP'si görünmez (kodla doğrulandı: Program.cs'de `ForwardedHeaders` yok).

**Öneri:** Tek bir `dbo.AuditLog(At, UserId, UserName, Ip, Action, EntityType, EntityId, Before, After)` tablosu ve yardımcı fonksiyon. İlk etapta yalnızca kullanıcı/yetki, giriş, teklif durumu, maliyet/tarife ve dışa aktarma olaylarına bağlansın. `UseForwardedHeaders` yalnızca `127.0.0.1` vekil sunucusuna güvenecek şekilde yapılandırılsın.

---

### A1-17 — ORTA — Sır yönetimi

**Konum:** appsettings.json:4-11 `Email:Password` alanı var. PILOT_KURULUM.txt:92 SMTP bilgilerinin `appsettings.json`'a yazılmasını öneriyor. Bu dosya kaynak klasöründe ve ZIP'lerde dolaşıyor, GitHub'a geçiş planlandığı için depoya sızma riski var. Windows pilotta bağlantı dizesinin nerede tutulduğu **doğrulanmadı**: teslim kopyasında `ConnectionStrings` boş. Eski sürümlerde `appsettings.json` içinde (Integrated Security) olduğu belgeden anlaşılıyor (PILOT_KURULUM.txt "appsettings.json -> ConnectionStrings").

Olumlu: Linux'ta `/etc/dengeerp/dengeerp.env` 0600 izinli, `02_yayinla.sh` izinleri ve şablon değerleri denetliyor, systemd sertleştirmesi (NoNewPrivileges, ProtectSystem=strict) var.

**Öneri:**
1. GitHub'a geçmeden önce `.gitignore` ile `appsettings.*.local.json`, `*.env` ve `*.bak` dışlansın. Depo geçmişinde sır olmadığı `git log -p` / gitleaks ile kontrol edilsin.
2. Windows'ta sırlar ortam değişkeni veya `dotnet user-secrets` ile verilsin. Linux'ta env dosyası yaklaşımı sürsün.
3. SQL hesabı en az yetkiyle çalışsın: uygulama hesabı `db_datareader`/`db_datawriter` + gerekli `EXECUTE`. Şema güncellemesi ayrı bir hesapla ve elle yapılsın (bkz. A1-21).

---

### A1-18 — DÜŞÜK — Güvenlik başlıkları yok, belirteç `localStorage`'da

**Konum:** Program.cs:15-16 yalnızca statik dosya ara katmanı var. `Content-Security-Policy`, `X-Frame-Options`/`frame-ancestors`, `X-Content-Type-Options`, `Referrer-Policy`, `Strict-Transport-Security` başlıkları yok (Nginx yapılandırmasında da yok). Belirteç `localStorage`'da (app.js:35, 2032).

**XSS değerlendirmesi (kodla doğrulandı):** app.js ve ops120.js içindeki tüm `${...}` ara değerleri tarandı. Sunucudan gelen metinler tutarlı biçimde `esc()` (app.js:3), `statusBadge` (125, kaçışlı), `workshopFieldValue` (683, kaçışlı) veya `option`/`select` yardımcıları (261, 1189, kaçışlı) üzerinden yazılıyor. Kaçışsız ara değerler yalnızca sabit metinler, sayısal kimlikler, sunucu tarihleri veya kaçışlı alt şablonlar. Hata mesajları `alert`/`textContent` ile gösteriliyor. **Somut bir XSS bulunmadı.** Tek dosyalık büyük SPA'da gelecekte bir `esc` unutulması olasıdır. CSP bu durumda ikinci savunma hattı olur.

**Öneri:** Küçük bir ara katmanla `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'` (inline `onclick` kullanılmadığı görüldü, olay bağlama `addEventListener` ile yapılıyor; yine de canlıda test edilmeli), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` eklensin. HTTPS sonrası HSTS. Belirtecin `sessionStorage`'a taşınması değerlendirilsin: sekme kapanınca oturum biter. Bu kullanılabilirlik etkisi olan bir karar, kullanıcıya sorulmalı.

---

### A1-19 — DÜŞÜK — Küçük IDOR / kapsam boşlukları

| Uç | Konum | Sorun |
|---|---|---|
| `POST /api/rentals/inventory` (güncelleme) | Program.cs:1355-1372 | `RentalInventoryId` verildiğinde **mevcut** kaydın ürün birimi kontrol edilmiyor, yalnızca yeni ürünün birimi kontrol ediliyor (1349). Başka birimin envanter kaydı kendi birimine taşınabilir. |
| `PUT /api/rentals/warehouses/{id}` | Program.cs:1322-1332 | Herhangi bir `rentals.edit` sahibi ortak depo adlarını değiştirebilir. |
| `POST /api/training/sessions` | Program.cs:1598-1610 | Kursun birimi kontrol edilmiyor. Başka birimin kursuna oturum açılabilir. |
| `POST /api/training/competencies` | Program.cs:1649-1666 | `CompetencyId`'nin birimi kontrol edilmiyor (personel birimi kontrol ediliyor). |
| `POST /api/training/observations` | Program.cs:1668-1710 | `WorkOrderId`'nin kullanıcının erişebildiği bir iş olduğu kontrol edilmiyor. |
| `GET /api/security/devices`, `GET /api/maintenance/plans/{id}/devices` | Program.cs:2232-2285, 2360-2376 | Teknisyen (`workorders.view`) tüm müşterilerin cihaz kütüğünü ve bakım cihaz listelerini görüyor. Tasarım gereği olabilir, kullanıcıya teyit ettirilmeli. |
| `POST /api/offers` | Program.cs:829 | Bkz. A1-09. |

**Öneri:** Her birine tek satırlık `UnitAllowed`/`CanAccessWorkOrderAsync` kontrolü. İlgili modül geliştirilirken eklenebilir.

---

### A1-20 — DÜŞÜK — DoS / performans kaynaklı erişilebilirlik riski

**Konum:** `LoadWorkOrdersAsync` (3441-3493) her çağrıda **tüm** iş emirlerini ve planlarını belleğe alıyor. Bu fonksiyon `GET /api/workorders`, zaman özeti, raporlar ve OpsSuite'teki hold/release/stock movement/finance yetki kontrolleri dahil pek çok uçta çağrılıyor (OpsSuite.cs:135, 150, 193, 250). İş emri kapatma her seferinde tüm bakım sözleşmelerini tarayan `EnsureMaintenancePlansAndWorkOrdersAsync` fonksiyonunu çalıştırıyor (539). Hız sınırı yok. Kötü niyetli ya da hatalı bir istemci servisi yavaşlatabilir. Cihaz aramasında `LIKE N'%'+@Q+N'%'` (2255-2258) parametreli, injection yok, yalnızca tam tablo taraması.

**Öneri:** Yetki kontrolleri için tek kayıt sorgusu (`CanAccessWorkOrderAsync` kalıbı) kullanılsın. Genel hız sınırı (A1-05'teki ara katman) eklensin. Bakım üretimi kapanış isteğinden ayrılıp zamanlanmış göreve taşınsın. Bu iş raporlama/operasyon modülü geliştirmesiyle birlikte yapılabilir.

---

### A1-21 — DÜŞÜK — Başlangıçta SQL betiklerinin otomatik yürütülmesi

**Konum:** Program.cs:26-41 ve `ApplySchemaAsync` 3257-3269: `RunDatabaseSetupOnStartup=true` olduğunda `Database/*.sql` dosyaları alfabetik sırayla uygulama hesabının yetkisiyle çalıştırılıyor. Linux'ta varsayılan kapalı ve `02_yayinla.sh` açıkken yayını reddediyor (iyi). Windows pilotta eski sürümler bu davranışı **varsayılan açık** kullanıyordu (PILOT_KURULUM.txt "Uygulama acilirken ... otomatik uygular"). Uygulama klasörüne yazabilen biri `.sql` dosyası bırakarak SQL çalıştırabilir. Uygulama hesabının DDL yetkisi olması gerekir. Windows pilot ayarının bugünkü değeri **doğrulanmadı**.

**Öneri:** Şema güncellemeleri yalnızca SSMS'ten ve ayrı yetkili hesapla yapılsın (proje çalışma yöntemiyle zaten uyumlu). Uygulama hesabından DDL yetkisi kaldırılsın. Windows pilot klasörü yalnızca yöneticinin yazabileceği izinlerde tutulsun.

---

## 4. Konu bazında değerlendirme

| Konu | Sonuç | Not |
|---|---|---|
| **Kimlik doğrulama** | Kısmen yeterli | PBKDF2-SHA256 120k + 16 bayt salt + `FixedTimeEquals` (2827-2844) iyi. Giriş sınırı (A1-05), MFA ve zorunlu şifre değişikliği uygulaması (A1-11) eksik. |
| **Oturum yönetimi** | Yetersiz | Bellek içi, süre sonu yok, iptal eksik (A1-04). Belirteç üretimi güçlü (94). |
| **Uç bazında yetki** | Genel olarak var | Ek'teki tabloda listelenen 82 ucun (Program.cs'de 70, OpsSuite.cs'de 12) tamamında oturum kontrolü var. İstisnalar: health ve login anonim, logout yalnızca belirteci siliyor. Sorunlar izin **modelinde** (A1-01, A1-08, A1-13) ve birkaç kapsam boşluğunda (A1-09, A1-19). |
| **IDOR / birim kapsamı** | Çoğunlukla doğru | İş emri uçları `CanAccessWorkOrderAsync`, toplu işlemler kayıt başına `UnitAllowed` kullanıyor. Boşluklar: A1-07, A1-09, A1-19. |
| **Yetki yükseltme** | **KRİTİK açık** | A1-01. |
| **Fiyat/maliyet sızıntısı** | **KRİTİK açık** | A1-02. Bakım sözleşmesi, stok ve maliyet analizi doğru korunuyor. |
| **SQL injection** | Bulunmadı | Tüm kullanıcı girdileri `Parameters.AddWithValue` ile. Dinamik SQL parçaları yalnızca sabit metin veya üretilen parametre adları: ReadBulkTargetsAsync (3321-3329), eğitim `access` sabiti (1495), LoadLiveTimers koşulu (3411-3413). Veritabanı betiklerinde `EXEC(`/`sp_executesql` kullanımı görülmedi. |
| **XSS** | Bulunmadı | Bkz. A1-18. CSP eklenmesi önerilir. |
| **CSRF** | Uygulanabilir değil | Kimlik doğrulama çerez değil `Authorization` başlığıyla (app.js:88, ReadToken 2814-2819). CORS yapılandırılmadığı için başka kökenden okuma da yok. İleride çerez tabanlı oturuma geçilirse CSRF koruması (SameSite=Strict + anti-forgery) şart olur. |
| **Brute-force** | Koruma yok | A1-05. |
| **Hata mesajı sızıntısı** | Var | A1-12, A1-10 (SMTP). |
| **Sır yönetimi** | Linux iyi, Windows/Git riski | A1-17. |
| **E-posta** | Koşullu risk | A1-10. SMTP şu an kapalı. TLS varsayılan açık (`EnableSsl ?? true`, 927). |
| **Dosya/PDF/Excel üretimi** | Güvenli | PDF metni ASCII'ye çevrilip `\ ( )` kaçışlanıyor (3575). Dosya adları sunucu üretimi (`OfferNo`). XLSX hücreleri `inlineStr` + XML kaçışı (3764-3766, 3783), formül oluşturulmuyor. CSV'lerde formül enjeksiyonu önlenmiş (1725, OpsSuite.cs:66-70). Dosya yükleme ucu yok. |
| **KVKK** | Süreç eksik | A1-15, A1-16. |
| **Dağıtım** | Linux iyi tasarlanmış | systemd sertleştirmesi, env 0600, Nginx IP izin listesi, şablon değer kontrolü. Eksikler: TLS (A1-06), hız sınırı, güvenlik başlıkları. |

---

## 5. Ek — Uç noktası yetki tablosu (tek tek)

Kısaltmalar: **Oturum** = `GetCurrentUser` kontrolü. **Birim** = `UnitAllowed`. **İE** = `CanAccessWorkOrderAsync` (birim + teknisyen kapsamı). **Filtre** = `FilterWorkOrdersForUser`.

### Program.cs

| Satır | Yöntem / Yol | İzin | Kapsam | Değerlendirme |
|---|---|---|---|---|
| 47 | GET /api/health | Anonim | — | A1-12 hata sızıntısı |
| 67 | POST /api/auth/login | Anonim | — | A1-05 |
| 101 | GET /api/auth/me | Oturum | — | Uygun |
| 107 | POST /api/auth/logout | — | — | Uygun |
| 114 | POST /api/auth/change-password | Oturum | Kendisi | A1-11 |
| 139 | GET /api/meta/permissions | Oturum | — | Uygun |
| 153 | GET /api/rules/worktypes | Oturum | — | Uygun |
| 174 | GET /api/users | users.manage | — | Uygun |
| 203 | POST /api/users | users.manage | — | **A1-01**, A1-13 |
| 245 | PUT /api/users/{id} | users.manage | Hedef korunmuyor | **A1-01**, A1-13 |
| 321 | PATCH /api/users/{id}/status | users.manage | Yalnız kendini koruyor | **A1-01**, A1-04 |
| 338 | POST /api/users/{id}/reset-password | users.manage | Hedef korunmuyor | **A1-01**, A1-04 |
| 359 | GET /api/workorders | workorders.view | Filtre | A1-08, A1-13, A1-15 |
| 370 | POST /api/workorders | workorders.create | Birim | Uygun |
| 432 | PUT /api/workorders/{id}/serials | create/edit/close | İE | Uygun |
| 473 | PATCH /api/workorders/{id}/status | edit/close | İE + Birim | A1-14 |
| 545 | PUT /api/workorders/{id}/assignments | assign | İE | Uygun (durum logu yok, A1-16) |
| 573 | PUT /api/workorders/bulk-assign | assign | Birim (kayıt başına) | Uygun |
| 619 | GET /api/workorders/{id}/site-suggestion | plan | İE | Uygun |
| 649 | PUT /api/workorders/bulk-plan | plan + assign | Birim (kayıt başına) | Uygun |
| 722 | PUT /api/workorders/{id}/plan | plan | İE | Uygun |
| 763 | GET /api/workorders/{id}/history | view | İE | Uygun |
| 790 | GET /api/offers | offers.view | Birim | **A1-02** |
| 800 | POST /api/offers | offers.create | Birim | A1-09 (WorkOrderId) |
| 861 | PATCH /api/offers/{id}/status | offers.approve | **Yok** | A1-09 |
| 883 | GET /api/offers/{id}/pdf | offers.view | Birim | **A1-02** |
| 895 | POST /api/offers/{id}/send | offers.send | Birim | A1-10 |
| 961 | GET /api/rentals/catalog | rentals.view/create | Birim | Uygun |
| 993 | GET /api/rentals | rentals.view | Birim | Uygun (A1-15) |
| 1051 | POST /api/rentals | rentals.create | Birim | Uygun |
| 1140 | PUT /api/rentals/{id} | rentals.edit | Birim | Uygun |
| 1201 | GET /api/rentals/{id}/details | rentals.view | Birim | Uygun |
| 1245 | PUT /api/rentals/{id}/composition | rentals.edit | Birim | Uygun |
| 1292 | GET /api/rentals/inventory | rentals.view / warehouse.view | Birim | Uygun |
| 1322 | PUT /api/rentals/warehouses/{id} | rentals.edit | — | A1-19 |
| 1334 | POST /api/rentals/inventory | rentals.edit | Yalnız yeni ürün birimi | A1-19 |
| 1376 | POST /api/rentals/{id}/allocate | rentals.edit | Birim | Uygun |
| 1436 | POST /api/rentals/{id}/stage | rentals.edit | Birim | Uygun |
| 1485 | GET /api/training/overview | training.view | Birim (SQL) | Uygun (A1-15) |
| 1538 | POST /api/training/courses | training.manage | Birim | Uygun |
| 1571 | POST /api/training/plans/bulk | training.manage | Kurs + personel birimi | Uygun |
| 1598 | POST /api/training/sessions | training.manage | **Yok** | A1-19 |
| 1612 | POST /api/training/attendance | training.manage | Personel + kurs birimi | Uygun |
| 1649 | POST /api/training/competencies | manage / observe | Personel birimi | A1-19 |
| 1668 | POST /api/training/observations | observe / manage | Personel + kurs birimi | A1-19 (WorkOrderId) |
| 1712 | GET /api/training/export.csv | view + export | Birim (SQL) | Uygun |
| 1733 | GET /api/personnel | personnel.view | **Yok** | A1-15 |
| 1770 | POST /api/personnel | personnel.manage (+users.manage) | — | A1-01, A1-13 |
| 1834 | PUT /api/personnel/{id} | personnel.manage | **Yok** | A1-07 |
| 1862 | PATCH /api/personnel/{id}/status | personnel.manage | **Yok** | **A1-07** |
| 1908 | GET /api/timetracking/summary | workorders.view | Filtre + kendisi/yönetici | Uygun |
| 1929 | POST /api/workorders/{id}/live-timer/start | view + close/edit | İE + atama (isim) | A1-08 |
| 1985 | POST …/live-timer/change | view + close/edit | İE + kendi oturumu | Uygun |
| 1987 | POST …/live-timer/finish | view + close/edit | İE + kendi oturumu | Uygun |
| 2080 | POST /api/timetracking/sessions/{id}/cancel | assign / users.manage | İE | A1-01 (users.manage kullanımı) |
| 2105 | GET /api/workorders/{id}/time-logs | view | İE | Uygun |
| 2114 | POST /api/workorders/{id}/time-logs | close / edit | İE + atama (isim) | A1-08 |
| 2166 | DELETE /api/workorders/{id}/time-logs/{logId} | assign / users.manage | İE | Uygun (yumuşak silme) |
| 2181 | GET /api/reports/worklogs | reports.view | Filtre | Uygun |
| 2191 | GET /api/reports/workorders.xlsx | reports.export | Filtre | A1-15, A1-16 |
| 2232 | GET /api/security/devices | devices.view / workorders.view | Güvenlik birimi | A1-19 |
| 2288 | GET /api/maintenance/contracts | maintenance.view / workorders.view | Güvenlik birimi | Uygun, fiyat doğru gizli |
| 2347 | POST /api/maintenance/generate-due | maintenance.manage / plan | Güvenlik birimi | A1-20 |
| 2360 | GET /api/maintenance/plans/{id}/devices | maintenance.view / workorders.view | Güvenlik birimi | A1-19 |
| 2379 | POST /api/maintenance/plans/{id}/devices/initialize | maintenance.manage | Güvenlik birimi | Uygun |
| 2403 | GET /api/maintenance/workorders/{id}/form | view | İE | Uygun |
| 2445 | POST /api/maintenance/workorders/{id}/form | close / maintenance.manage | İE | Uygun |
| 2560 | GET /api/workshop/tickets | workshop.view / workorders.view | Haberleşme birimi | **A1-02**, A1-08 |
| 2628 | POST /api/workshop/tickets | workshop.manage / create | Haberleşme birimi | A1-02 (repairAmount yazımı) |
| 2707 | PUT /api/workshop/tickets/{id} | workshop.manage / edit | Haberleşme birimi, İE yok | A1-08, A1-14 |

### OpsSuite.cs

| Satır | Yöntem / Yol | İzin | Kapsam | Değerlendirme |
|---|---|---|---|---|
| 76 | GET /api/ops/overview | dashboard.view | Filtre | Uygun |
| 111 | POST /api/ops/alerts/ack | dashboard.view | Yalnız görünen uyarı | Uygun |
| 122 | PUT /api/ops/sla/{priority} | operations.manage | Genel | Uygun (A1-16) |
| 130 | POST /api/ops/workorders/{id}/hold | operations.manage / edit | Filtre | Uygun (A1-20) |
| 146 | POST /api/ops/workorders/{id}/release | operations.manage / edit | Filtre | Uygun |
| 160 | GET /api/ops/stock | warehouse.view | — | Uygun, maliyet gizli |
| 177 | POST /api/ops/stock/part | warehouse.manage (+costs) | — | Uygun |
| 188 | POST /api/ops/stock/movement | warehouse.manage | İE filtre | Uygun |
| 214 | GET /api/ops/finance | prices.view + reports.view | Filtre | Uygun |
| 237 | PUT /api/ops/finance/rate | prices.view + costs.manage | Birim | Uygun (A1-16) |
| 246 | PUT /api/ops/finance/{id} | prices.view + costs.manage | Filtre | Uygun (A1-16) |
| 259 | GET /api/ops/export.csv | reports.export | Filtre | Uygun |

---

## 6. Doğrulanmayan iddialar ve önerilen testler

| İddia | Neden doğrulanmadı | Önerilen test |
|---|---|---|
| Eski demo hesaplar canlı DB'de aktif (A1-03) | Canlı SQL'e erişim yok | Bölüm A1-03'teki SSMS sorgusu |
| `Results.Forbid()` 403 yerine 500 üretiyor (A1-12) | Uygulama çalıştırılmadı | Teknisyen hesabıyla `GET /api/users` çağır, durum kodunu gözle |
| Development hata sayfası yığın izi gösteriyor (A1-12) | Çalıştırılmadı | Windows pilotta `POST /api/auth/login` gövdesi `{}` ile 500 yanıtını incele |
| Login zamanlama farkı ölçülebilir (A1-05) | Çalıştırılmadı | Var olan / olmayan kullanıcı adıyla 20'şer istek, süre ortalamaları |
| Windows pilotta bağlantı dizesi ve `RunDatabaseSetupOnStartup` değeri (A1-17, A1-21) | Canlı klasör görülmedi | Çalışan klasördeki appsettings*.json ve ortam değişkenleri |
| Yedeklerin şifrelenmediği (A1-15) | Yedek politikası görülmedi | İT ile yedek konumu ve şifrelemesi teyidi |

Önerilen otomatik test seti (bir sonraki geliştirme dalgasında bir test projesi ile): her rol için "izin yok → 403", "başka birim → 403", "teknisyen başka işi → 403", "fiyat izni yok → tutar alanı null" ve "pasif kullanıcı → 401" senaryoları. Proje belgesindeki "Rol değişiminde hassas finans API'larının gerçekten veri sızdırmaması" açık doğrulaması bu setle kapatılabilir.
