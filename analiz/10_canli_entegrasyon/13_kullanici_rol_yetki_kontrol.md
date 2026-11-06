# E13 Teknik Servis Rolleri, İzinleri, Birim Kapsamı ve Personel: Bağımsız Kontrol

> Tarih: 2026-10-21 · Denetlenen: `13_kullanici_rol_yetki_entegrasyon.md` · Yöntem: canlı kod okundu, kaynak koda dokunulmadı.
> Okunan canlı dosyalar: `backend/app/permissions.py`, `models/user.py`, `models/rbac.py`, `models/audit.py`, `models/mixins.py`, `api/users.py`, `api/auth.py`, `api/deps.py`, `api/imports.py`, `api/audit_api.py`, `schemas/auth.py`, `services/auth.py`, `services/audit.py`, `services/accounts.py`, `services/kvkk.py`, `services/imports/cekirdek.py`, `services/imports/eslesme.py`, `seeds/dev.py`, `worker.py`, `yonetim.py`, `main.py`, `tests/conftest.py`, `tests/unit/test_permissions.py`, `tests/integration/test_auth_rbac.py`, `tests/integration/test_rol_ve_izin_duzenleme.py`, `docker-compose.yml`, `deploy/db-least-privilege.sql`, `deploy/Caddyfile`, `deploy/fail2ban/*`, `Makefile`. Kardeş belgeler: `00_MIMARI_KURALLAR.md`, `01_is_emirleri_entegrasyon.md`, `01_is_emirleri_kontrol.md`, `02_planlama_kontrol.md`, `04_planli_bakim_kontrol.md`, `05_haberlesme_atolye_kontrol.md`, `11_yedek_parca_kontrol.md`.

---

## 1. Genel hüküm

Tasarımın omurgası doğru ve canlı mimariyle uyumlu:

- **Personel = kullanıcı (K-01).** Ayrı `personnel` tablosu açılmıyor; `users` tablosuna yalnız nullable veya varsayılanlı kolon ekleniyor. `is_active` ile `giris_acik` ayrımı (K-03), E01 kontrolündeki B4 çelişkisini ("pasif kullanıcıya atama 400" ile "girişsiz personel" kuralının çakışması) temiz biçimde çözüyor.
- **Mevcut RBAC omurgası korunuyor:** gerekçeli istisna, kendi yetkisini değiştirememe, rol değişince oturum düşürme, parola ve TOTP maskeleme, MFA.
- **Mobilite akışlarına dokunulmuyor.** `work_orders`, `settlements`, IMEI/`identity_kind` ve EXCLUDE kısıtları değişmiyor. Mevcut 9 rol ve `TEKNIK_SERVIS` aynen kalıyor.

"Canlıda var/yok" tespitleri kodla doğrulandı:

| İddia | Doğrulama |
|---|---|
| `sistem.kullanici` yalnız ADMIN'de | Doğru (`permissions.py:90`; başka rolde yok). |
| ADMIN rolü başkasına verilebiliyor, istisnayla yüksek izin verilebiliyor, ADMIN rolü boşaltılabiliyor, son admin koruması yok | Doğru (`api/users.py:436-440`, `:302-356`, `:209-258`). |
| Kapsam yalnız TUMU / KENDI_MUSTERILERI | Doğru (`permissions.py:80-82`). Rol ekranı da beyaz listeye bağlı (`api/users.py:181,225`). |
| Mutlak oturum süresi yok | Doğru (`services/auth.py:121-133` her istekte yalnız kayan pencere). |
| Kendi parolasını değiştirme ucu ve zorunlu değişim yok | Doğru (`api/auth.py` içinde yok). |
| Zamanlama farkı ve 423 kullanıcı adı varlığını sızdırıyor | Doğru. `authenticate` var olmayan ya da pasif kullanıcıda argon2 çalıştırmadan dönüyor (`services/auth.py:39-43`). `record_failed_login` var olmayan kullanıcıya satır açmıyor (`:85-89`), yani 423 yalnız gerçek hesapta çıkar. |
| `db-least-privilege.sql` audit_logs'ta UPDATE/DELETE veriyor | Doğru (`:23`). |
| Gerçek istemci IP'si kayıp | Doğru. Caddy host üzerinde çalışıyor (`deploy/Caddyfile`), uvicorn `--proxy-headers`/`--forwarded-allow-ips` olmadan başlıyor (`docker-compose.yml:32-35`), `client_ip` doğrudan `request.client.host` döndürüyor (`api/deps.py:121-122`). |
| Birim, personel, vekâlet ve işten çıkış kavramları yok | Doğru. |

Yine de düzeltilmesi gereken **altı kritik nokta** var.

### 1.1 Rol tablosu E01, E04, E11 kontrolleriyle hizalı değil; E13 tek kaynak olmalı (E13-D01)

- E11 kontrolü (E11-05) bir `SERVIS_DEPO` rolü istiyor; E13 rol tablosunda bu rol yok.
- E04, E07 ve E11 kontrolleri aynı sonuca vardı: `maliyet.gor` yalnız ADMIN, SATIS_MUDURU, MUHASEBE_DESTEK ve YONETIM rollerinde (`permissions.py:138,243,247`). Servis tarafında maliyet ya da ücret **fiilen yalnız ADMIN'e girilebiliyor**. E13 "maliyet.gor kümesi değişmez" diyerek bu sorunu sabitliyor.
- E01 kontrolü (B7) `SERVIS_TEKNISYEN`'den `hesap.gor`'un çıkarılmasını istiyor. Gerekçe: yeni kapsamlar mobilite modüllerinde `TUMU` gibi davranıyor, çünkü canlıdaki tüm kontroller yalnız `== KENDI_MUSTERILERI` eşitliğine bakıyor (`services/accounts.py:18,42,56`, `api/deps.py:116`, `api/orders.py:201,228`, `api/quotes.py:178,192`).

Rol ve izin kataloğunun sahibi E13 olduğuna göre, bütün servis rollerinin konsolide matrisi burada tek tabloda yer almalı.

### 1.2 ADMIN rolünün kendisi korumasız

- `seeds/dev.py:58-72` özelleştirilmiş role yeni izin indirmiyor. Canlıda ADMIN rolü bir kez arayüzden düzenlendiyse (`ozellestirildi=true`), `personel.*` ve `vekalet.ver` ADMIN'e **hiç inmez**. Yalnız log'a bir uyarı düşer.
- E13-01'in "ADMIN rolü düzenlenemez (409)" kuralı bu riski yalnız ileriye dönük kapatıyor. Seed, ADMIN'i her açılışta `tuple(PERMISSIONS)`'a **zorla** eşitlemeli ve `ozellestirildi` bayrağını false'a çekmeli.
- Ek değişmez gerekli: `YUKSEK_YETKILI_IZINLER` ADMIN dışında **hiçbir rolde** (özel roller dahil) bulunamaz. Bunun için `rol_olustur`/`rol_guncelle` 403 dönmeli ve bir birim testi eklenmeli.

### 1.3 "Alt küme ve üstünlük" kuralı K-02 ile büyük ölçüde ölü kod

- K-02'ye göre `sistem.kullanici` yalnız ADMIN'de kalıyor, ADMIN de bütün izinlere sahip. Bu durumda `verilebilir_mi` alt küme kontrolü hiçbir canlı senaryoda reddetmez.
- Kabuldeki "sistem.kullanici istisnasıyla donatılmış ADMIN olmayan hesap" senaryosu, yine E13-01 kuralı yüzünden API üzerinden kurulamıyor.
- Gerçek riskler başka yerde ve bunlar korunmalı: personel uçlarının (`personel.yaz`, `personel.cikis`) üst yetkili hedefe dokunması, ADMIN rolünün atanması ve son ADMIN.
- Kural seti sadeleştirilmeli (bkz. E13-01). `ust_yetkili_mi` ölçütü de genişlemeli: hedef `YUKSEK_YETKILI_IZINLER`'den **herhangi birine** sahipse üst yetkilidir; yalnız `sistem.kullanici` yetmez.

### 1.4 Giriş yolu tek noktadan geçmiyor

- `api/auth.py:93-95` `login_mfa` kullanıcıyı `db.get` ile yüklüyor ve yalnız `is_active`'e bakıyor.
- Tasarım `giris_acik` ve `parola_degismeli` denetimini yalnız `authenticate` ile `resolve_session`'a ekliyor. MFA'lı hesapta parolası doğru ama `giris_acik=false` olan kişi, eline geçmiş bir `pending_token` ile oturum açabilir.
- Çözüm: `User.giris_yapabilir_mi()` tek kural olsun (`mfa_kurulumu_gerekli` kalıbı, `models/user.py:41-52`) ve üç yol (`authenticate`, `login_mfa`, `resolve_session`) da onu çağırsın.

### 1.5 Denetim değişmezliğinin gerçek kontrolü tetikleyicidir; REVOKE varsayılan kurulumda etkisiz

- `docker-compose.yml:36-37,52-53`: api ve worker şema sahibi `dengeerp` ile bağlanıyor. Tablo sahibi REVOKE'tan etkilenmez, bu yüzden `db-least-privilege.sql` değişikliği ancak `dengeerp_app` geçişi yapılmışsa işe yarar. Tasarımın tetikleyiciyi ana önlem seçmesi doğru; belge bunu açıkça söylemeli.
- Tetikleyicinin iki yan etkisi tasarımda yok:
  - (a) `audit_logs.user_id` FK'si `ON DELETE SET NULL` (`models/audit.py`). Herhangi bir kullanıcı satırı fiziksel olarak silinirse, RI güncellemesi tetikleyiciye takılır ve silme başarısız olur. Bugün kodda kullanıcı silme yok, ama E13-04 canlı İçe Aktarma çerçevesine taşınırsa parti iptali gerçek satır siler (`api/imports.py:249`). Personel profilinde iptal yalnız **pasifleştirme** yapmalı.
  - (b) `conftest.py:41-42` audit_logs'u TRUNCATE ile temizliyor. Satır düzeyi tetikleyici TRUNCATE'te çalışmaz, yani testler kırılmaz. Bunun bilinçli kabul edildiği belgeye yazılmalı.
- `FORWARDED_ALLOW_IPS` 127.0.0.1 değil, **compose ağının ağ geçidi IP'si** olmalı. Caddy host'ta çalışıyor ve Docker port eşlemesi kaynağı ağ geçidi olarak gösteriyor.
- Caddy v2 güvenilmeyen istemcinin `X-Forwarded-For` başlığını kendi değeriyle eziyor, yani sahtecilik Caddy'de kesiliyor. KURULUM.md'ye doğrulama adımı eklenmeli: `docker network inspect` ile ağ geçidi bulunur, audit_logs'taki IP gerçek IP ile karşılaştırılır.

### 1.6 Mevcut çerçeveler yeniden kullanılmamış

- **Personel yükleme ve ad eşleme onayı:** E13-04 ve E13-08 yeni `yonetim.py` alt komutları ve yeni bir PATCH ucu öneriyor. Oysa canlıda bu işi yapan bir çerçeve var: profil tabanlı **İçe Aktarma** (`services/imports/cekirdek.py:90` `Profil.dogrula/yaz`, `api/imports.py` önizleme → uygula → karantina.xlsx, `PROFIL_IZINLERI` ile profile özel izin). Bu çerçeve kuru çalışma, satır hatası, karantina Excel'i ve parti geçmişini zaten sağlıyor.
- **Süreli vekâlet:** E13-15 yeni bir `user_delegations` tablosu, `has()` içine yeni bir katman ve worker işi öneriyor. Canlıdaki gerekçeli `user_permissions` istisnasına nullable bir `bitis_at` eklemek aynı işi tek kolonla görür (bkz. E13-15).
- **Denetim:** `guvenlik_olayi` sarmalayıcısı gereksiz. `api/audit_api.py:30-37` zaten `entity` ve `action` önekiyle süzüyor. Ayrıca §2.1 sarmalayıcıyı `entity="guvenlik"` diye tanımlarken E13-12 maddesi `entity users` diyor; bu bir iç tutarsızlık. Canlı kalıp korunmalı: `entity="users"` ve eylem önekleri. Ön yüzde yalnız hazır bir süzgeç olur.

### Aşırı mühendislik bulunanlar

- `.github/workflows/test.yml` (K-10). Çalışma kopyası git deposu bile değil; çalışmayan bir CI dosyası bakım yükünden başka bir şey üretmez.
- Saha rolünü rol kodundan türetme ve rozetleme (E13-07). Canlıda hiç servis kullanıcısı yok; geçiş durumu oluşmaz.
- `user_delegations` tablosu ve `has()` vekâlet katmanı (E13-15).
- `personnel_name_maps` için ayrı API ucu (E13-08). Onay Excel ile İçe Aktarma'dan yapılabilir. Tablo, göç izi olarak kalabilir.

---

## 2. Madde kararları

| Id | Karar | Öncelik | Gerekçe / düzeltme |
|---|---|---|---|
| E13-01 | DEĞİŞTİR | P1 | Kural seti sadeleşir ve gerçek risklere odaklanır:<br>(1) **Değişmez:** `YUKSEK_YETKILI_IZINLER` yalnız ADMIN rolünde bulunur. Özel rol açarken veya düzenlerken (`api/users.py:178-258`) ya da `allow=True` istisna yazarken (`:302-356`) bu izinler istenirse 403. Unit testte `ROLES` üzerinden de doğrulanır.<br>(2) ADMIN rolü yalnız ADMIN aktör tarafından atanır (`create_user`, `patch_user`; `:380-382`, `:436-440`).<br>(3) `rol_guncelle("ADMIN")` 409. `sync_roles` (`seeds/dev.py:58`) ADMIN'i `ozellestirildi` bayrağına bakmadan `tuple(PERMISSIONS)`'a eşitler ve bayrağı false yapar.<br>(4) Son aktif ADMIN (`is_active AND giris_acik`) kapatılamaz, rolü değiştirilemez, girişi kapatılamaz: 409.<br>(5) `ust_yetkili_mi` = hedef ADMIN rolünde **veya** `etkin_izinler ∩ YUKSEK_YETKILI_IZINLER` boş değil. Personel uçları (`personel.yaz`, `personel.cikis`, `birimleri_yaz`) üst yetkili hedefe 403 döner.<br>(6) Genel alt küme kuralı (`verilebilir_mi`) yalnız ADMIN olmayan bir aktörün rol/istisna yazdığı yolda anlamlıdır. K-02 sürdükçe ölü koddur; ya hiç yazılmaz ya da (1)'in içinde tek satırlık savunma olarak kalır.<br>(7) Kapsam beyaz listesi `SCOPES`'a çevrilir (`:181,:225`), `_KAPSAM_ACIKLAMA` (`:73-76`) genişler.<br>(8) Ret denemeleri `audit.log("users"/"roles","yetki.ret")` ile yazılır.<br>Kabule eklenecek: "ADMIN rolü `ozellestirildi=true` iken seed sonrası ADMIN yeni izinlere sahip"; "özel rol `sistem.denetim` ile açılamaz (403)". `test_auth_rbac.py` (15 test) ve `test_rol_ve_izin_duzenleme.py` (DEPO rolünü düzenleyen testler `:158-255`) yeşil kalır. |
| E13-02 | DEĞİŞTİR | P1 | Yaklaşım doğru (`SESSION_MAX=12h`, uzatma `created_at+SESSION_MAX` ile sınırlı, süreler kod sabiti). Eklenecekler:<br>(a) Giriş kuralı `User.giris_yapabilir_mi()` (`is_active AND giris_acik`) olarak tek yerde tanımlanır; `authenticate`, `login_mfa` (`api/auth.py:93-95`, bugün yalnız `is_active` bakıyor) ve `resolve_session` bunu çağırır.<br>(b) `giris_acik=false` yapan her yol `revoke_all_sessions` çağırır (`api/users.py:452-458` koşul listesine eklenir).<br>(c) Kabule eklenecek: "MFA'lı, `giris_acik=false` hesap geçerli pending_token ile 401". |
| E13-03 | KABUL | P1 | K-03 ile doğru. Aktifleştirme `giris_acik`'a dokunmaz. Giriş açma yalnız `sistem.kullanici` ile yapılır. |
| E13-04 | DEĞİŞTİR | P1 | İlke doğru: depoda gerçek ad yok, idempotent, tahmin yok. Uygulama aracı değişir: `yonetim.py` alt komutu yerine **canlı İçe Aktarma çerçevesinde `personel` profili** (`services/imports/__init__.py` `PROFILLER` + `PROFIL_IZINLERI["personel"]="personel.yaz"`, `Profil.dogrula/yaz`). Böylece önizleme (kuru çalışma), satır hataları, karantina.xlsx ve parti geçmişi hazır gelir; şablon `sablon_xlsx` ile üretilir. Kurallar:<br>- Eşleşme sırası `sicil_no`, sonra `username`.<br>- Yeni kayıt `giris_acik=false`, rol SERVIS_TEKNISYEN; `password_hash` rastgele bir sırrın argon2 özeti. "!" gibi geçersiz bir özet KULLANILMAZ: `verify_password` geçersiz özette `VerifyMismatchError` değil `InvalidHash` fırlatır ve 500 doğurur.<br>- Personel partisi için **iptal fiziksel silme yapmaz** (audit FK ve E13-12 tetikleyicisi, bkz. §1.5); en fazla pasifleştirir ya da 409 döner.<br>- `username` üretimi: `p.` + `sicil_no` normalize; sicil yoksa `p.` + kısa rastgele ek. Insert öncesi id bilinmez, `p.<id>` ise iki adımlı güncelleme gerektirir.<br>Kabul aynen; ek olarak "aynı dosya ikinci kez uygulanınca 0 yeni satır". |
| E13-05 | DEĞİŞTİR | P1 | Yön doğru. Düzeltmeler:<br>(a) Personel kolonlarındaki değişiklik `audit.log_change(..., is_personal_data=True)` ile yazılmalı (sicil, not, ayrılış nedeni kişisel veri). Ayrıca tetikleyici yalnız `is_personal_data` satırlarında maskelemeye izin veriyor; bayrak konmazsa bu kayıtlar ileride maskelenemez (bkz. E13-D03).<br>(b) `personel.yaz` sahibi üst yetkili hedefin kartını yalnız ünvan/sicil düzeyinde değiştirebilir; `full_name` değişikliği üst yetkili hedefte 403. Aksi hâlde İK ADMIN'in adını değiştirip denetim izinde karışıklık yaratır.<br>(c) `KpiKutusu` canlıda yok (yalnız `components/KartPenceresi.tsx` var); E12'ye bağımlılık açıkça yazılmalı ya da ilk sürümde düz `Statistic` kullanılmalı.<br>(d) `GET /api/personel` sayfalama `sayfala` (`api/deps.py:170`) ile; Excel `rapor.disaaktar` + `personel.gor`, `audit.log(..., is_personal_data=True)`.<br>(e) `UserOut`'a yalnız `giris_acik`, `birimler`, `birincil_birim`, `parola_degismeli` eklenir; personel alanları `UserOut`'a değil `PersonelOut`'a girer. |
| E13-06 | KABUL | P1 | `user_units` tek migration (K-19) doğru. Tamamlanacaklar:<br>- Birim değişiminde `revoke_all_sessions`.<br>- `User.birimler` `lazy="selectin"` (istisna kalıbı, `models/user.py:34-36`).<br>- Ön yüzde sabit kapsam listeleri güncellenmeli: `components/RolDuzenle.tsx:144`, `UsersPage.tsx`, `AppLayout.tsx` (E01 kontrolü B8, E13-D02). |
| E13-07 | DEĞİŞTİR | P1 | Servis doğru, `giris_acik` filtrelenmemesi doğru. Değişecekler:<br>(a) **Rol kodundan saha rolü türetme ve rozet kaldırılır.** Canlıda servis kullanıcısı yok; servis personeli E13-04 profiliyle açık `saha_rolu` ile gelir. `saha_rolu IS NULL` kişi atanamaz ve personel KPI'sında "saha rolü eksik" olarak sayılır.<br>(b) E01 kontrolü E01-12'nin "users'a dokunmadan user_units'e kolon" önerisi bu madde ve K-01 ile geçersizleşir; E01 belgesinde bu maddeye atıf yapılır.<br>(c) `birim` parametresi `BIRIMLER`'e karşı doğrulanır (400), kapsam dışı birim 404 (K-08). |
| E13-08 | DEĞİŞTİR | P2 | Eşleme gerekli: eski ad bazlı geçmiş başka türlü kişiye bağlanamaz. Ama:<br>(a) Onay ayrı bir PATCH ucu ve ekranı yerine İçe Aktarma çerçevesinde `ad_esleme` profiliyle yapılır: öneri Excel'i indirilir, İK "onaylanan sicil/kullanıcı" sütununu doldurur, profil yükler.<br>(b) `personnel_name_maps` göç izi olarak kalır; `VersionedMixin` gereksizdir (tek yazıcı profil).<br>(c) `normal_ad` için canlı `services/normalize.py:tr_normkey` kullanılır.<br>(d) `pg_trgm` önerisi yalnız öneri olarak yazılır, asla otomatik onaylanmaz.<br>Öncelik P2'ye iner: E01/E09 göçü çalışmadan uygulanacak satır yoktur, ama göç sürümünde zorunludur. |
| E13-09 | KABUL | P2 | K-11 (açık sayaç kapatılmaz) iş kuralıyla uyumlu: süre kaydı yoksa "eksik". Notlar:<br>- Üst yetkili ölçütü E13-01(5)'e göre.<br>- `service_order_events` için `ATAMA` türü E01 `ck_soe_tur` listesinde var (`01_is_emirleri_entegrasyon.md:116`).<br>- Kişinin `user_units` satırları silinmez (geçmiş raporu birimi kaybetmesin); atanabilirlik zaten `is_active` ile kesilir.<br>- Mobilite `work_orders.assigned_id` yalnız bilgi olarak sayılır. |
| E13-10 | KABUL | P2 | Rol = canlı şablon (K-06) canlı semantikle aynı (`api/users.py:213-221`). Rol listesi E13-D01'deki konsolide matristen gelir. `sapma_sayisi` UserOut'a değil liste yanıtına eklenir. |
| E13-11 | KABUL | P2 | Fail-closed kuralı E01 kontrolüyle aynı. `kapsam.py` tek uygulama olur (E01 ve E08 import eder). Kabule eklenecek: "KENDI_BIRIMI rolünde birimsiz kullanıcı açma 400". |
| E13-12 | DEĞİŞTİR | P2 | Tetikleyici ana önlemdir. REVOKE yalnız `dengeerp_app` ile bağlanan kurulumda etkilidir; varsayılan compose sahibiyle bağlanıyor (`docker-compose.yml:36,52`). Belge ve KURULUM.md bunu açıkça söylemeli. Eklenecekler:<br>(a) Tetikleyicinin `ON DELETE SET NULL` RI güncellemesini de engellediği, kullanıcıların fiziksel olarak silinmeyeceği (E13-04 parti iptali dahil) kuralı.<br>(b) `FORWARDED_ALLOW_IPS` = compose ağ geçidi IP'si (Caddy host'ta).<br>(c) `guvenlik_olayi` sarmalayıcısı ve `entity="guvenlik"` çıkarılır; `api/audit_api.py:30-37` süzgeci yeter, ön yüze yalnız hazır süzgeç eklenir.<br>(d) KVKK imhasında `SET LOCAL denge.kvkk_imha='1'` aynı sürümde gelir; tetikleyici yalnız `old_value/new_value` değişikliğine izin verir, `services/kvkk.py:325` bu koşula uyuyor.<br>(e) `fail2ban/jail.local` içindeki "5 hata → 15 dk" yorumu canlıyla çelişiyor (kalıcı kilit); düzeltilir. |
| E13-13 | DEĞİŞTİR | P2 | Doğru. Ekler:<br>(a) `parola_degismeli` muafiyet listesi `MFA_MUAF_YOLLAR` (`api/deps.py:37-44`) kalıbında ayrı bir `PAROLA_MUAF_YOLLAR` = {/me, /logout, /parola} olur.<br>(b) `POST /api/auth/parola`'da yanlış mevcut parola `record_failed_login` sayacına girer (çalıntı oturumla parola deneme).<br>(c) 423 → 401 değişimi `test_auth_rbac.py:43,45,58,66` beklentilerini değiştirir; E13-01'deki "15 test değişmeden yeşil" ifadesiyle çelişir, sürüm notu ve test güncellemesi açıkça listelenmeli. fail2ban filtresi `401|423`'ü zaten yakalıyor.<br>(d) Kilitli hesabın kullanıcıya "kilitli" denmeden 401 alması destek yükü doğurur. Yönetici kilitli listesi (`api/users.py:465`) ve UsersPage'de "Kilitli" rozeti bunu karşılar. |
| E13-14 | DEĞİŞTİR | P2 | Matris testi doğru; iki düzeltme:<br>(a) `require_permission`'ın ürettiği `_guard` kapanışı izin kodlarını dışarı vermiyor (`api/deps.py:88-97`). Rotalardan türetme için `_guard.izinler = codes` niteliği eklenir; kapanış iç gözlemi kırılgandır.<br>(b) `.github/workflows/test.yml` çıkarılır (K-10 RET): depo git'te bile değil; zorunlu kapı `make test`.<br>Değişmez testleri: `YUKSEK_YETKILI_IZINLER` yalnız ADMIN'de; `VEKALETE_KAPALI ⊆ PERMISSIONS`; servis rollerinin mobilite yazma izinlerine (`isemri.onayla`, `hakedis.*`) sahip olmadığı. |
| E13-15 | DEĞİŞTİR | P3 | Yeni tablo, `has()` katmanı ve worker işi yerine canlı `user_permissions` istisnasına nullable `bitis_at` (tz) eklenir. `has()` ve `etkin_izinler()` süresi geçmiş istisnayı yok sayar (Clock ile). Yalnız `allow=True` istisnalar süreli olabilir, en fazla 30 gün (CHECK); `VEKALETE_KAPALI` 403. `vekalet.ver` sahibi (SERVIS_YONETICI) yalnız kendi `etkin_izinler` alt kümesini ve yalnız `sistem.kullanici` gerektirmeyen ayrı bir uçtan verebilir. Birim vekâleti P3 kapsamı dışında bırakılır (gerekirse `user_units.bitis_at`). Kazanç: `has()` tek kural olarak kalır, mevcut "rolünden farklı" rozeti süreli istisnayı da gösterir. |
| E13-16 | KABUL | P3 | Küçük, salt okunur. `KpiKutusu` E12 bağımlılığı (E13-05c gibi). `uzun_girissiz` eşiği ayarlanabilir; güvenlik sabiti değildir. |
| E13-17 | KABUL | P3 | Nullable kolon ucuz; döngü kontrolü servis katmanında. "Ekibim" yalnız süzgeç (K-20). Eski ManagerName eşlemesi E13-08 profiline bir kaynak alan olarak eklenir. |

---

## 3. Kararlar (K-01 … K-20)

| Karar | Hüküm |
|---|---|
| K-01 Personel = kullanıcı | **Makul.** E01, E02 ve E08 ile tutarlı. `password_hash NOT NULL` için rastgele argon2 özeti kullanılır (E13-04). |
| K-02 sistem.kullanici yalnız ADMIN | **Makul.** Sonucu: genel alt küme kuralı gereksizleşir (E13-01). |
| K-03 is_active ile giris_acik ayrımı | **Makul.** Tek kural `giris_yapabilir_mi()` olmalı (§1.4). |
| K-04 Kalıcı kilit, 401 aynı metin | **Makul.** Destek yükü kilitli rozetiyle karşılanır. |
| K-05 4 sa + 12 sa, kod sabiti | **Makul.** |
| K-06 Rol = canlı şablon | **Makul.** Canlı semantikle aynı. |
| K-07 Denetim hiç silinmez | **Makul.** Kullanıcı fiziksel silme yasağını da doğurur (§1.5). |
| K-08 Kapsam dışı 404 | **Makul.** Canlı kalıp. |
| K-09 BIRIMLER kod sabiti | **Makul.** |
| K-10 CI dosyası hazırlanır | **RET.** Git dışı çalışma kopyasında ölü dosya üretir; `make test` yeter. |
| K-11 Açık sayaç kapatılmaz | **Makul.** "Süre kaydı yoksa eksik" kuralıyla uyumlu. |
| K-12 Girişsiz personelin rolü SERVIS_TEKNISYEN | **Makul.** Giriş açılırken rol bilinçli seçilir. |
| K-13 IK rolü | **Makul.** `gorev.*` dışında servis veya maliyet izni yok. `personel.cikis` üst yetkili hedefte 403. |
| K-14 Vekâlete kapalı liste | **Makul.** Uygulama aracı süreli istisna olmalı (E13-15). |
| K-15 Saha rolü İK olgusu | **Makul.** Ancak "rol kodundan türet" kısmı RET (E13-07). |
| K-16 Stajyer girişsiz, ortak hesap yok | **Makul.** |
| K-17 Teknik servis dışına yeni rol yok | **Makul.** |
| K-18 FORWARDED_ALLOW_IPS | **Makul.** Değer ağ geçidi IP'si olmalı. |
| K-19 user_units tek migration | **Makul.** |
| K-20 Ekibim yalnız süzgeç | **Makul.** |
| (eksik karar) maliyet.gor | **Açık karar gerekli** (E13-D01): servis tarafında ücret ve maliyeti kim girecek? |

---

## 4. Eklenen maddeler

### E13-D01 · Konsolide servis rol-izin matrisi, SERVIS_DEPO rolü ve maliyet girişi kararı (P1 · M)
- **Canlı:** YOK. `permissions.py:89-248` dokuz mobilite rolünü içeriyor. Servis rolleri E01 §3.3, E04, E05, E06, E07, E08, E09, E10 ve E11 belgelerine dağılmış ve çelişiyor:
  - E05 aynı rolleri farklı izinlerle yeniden tanımlıyor.
  - E11 `SERVIS_DEPO` rolünü istiyor.
  - E01 `SERVIS_TEKNISYEN`'e `hesap.gor` veriyor.
- **Yaklaşım:**
  - E13 belgesinde tek tablo kurulur: rol × izin × kapsam, bütün servis izinleri dahil. `permissions.py` bu tablodan yazılır.
  - `SERVIS_DEPO` (KENDI_BIRIMI) eklenir.
  - `SERVIS_TEKNISYEN`'den `hesap.gor` çıkarılır. Yeni kapsamlar mobilite modüllerinde TUMU gibi davrandığı için (`services/accounts.py:42,56`) servis rollerindeki her mobilite `.gor` izni gerekçelendirilir.
  - **Maliyet kararı kullanıcıya sorulur:** `maliyet.gor` SERVIS_YONETICI'ye verilsin mi? Verilmezse servis ücreti ve maliyeti yalnız ADMIN girer (E04, E07 ve E11 kontrollerinin ortak bulgusu). Karar `tests/unit/test_permissions.py:26` beklentisine yansır.
- **Kabul:**
  - Bütün servis rolleri tek tabloda ve `ROLES`'ta.
  - `test_her_izin_bir_role_atanmis` yeşil.
  - Servis rollerinden hiçbiri `isemri.onayla`, `hakedis.*`, `tahsilat.yaz` taşımaz.
  - Maliyet kararı belgede ve testte sabit.

### E13-D02 · Kullanıcı ve rol ekranlarının yeni kapsamları ve sayfaları tanıması (P1 · S)
- **Canlı:** KISMEN.
  - Kapsam seçenekleri ön yüzde sabit (`components/RolDuzenle.tsx:144`).
  - Etiketler yalnız `KENDI_MUSTERILERI`'yi tanıyor (`UsersPage.tsx`, `AppLayout.tsx`; E01 kontrolü B8).
  - `_SAYFA_IZINLERI` servis sayfalarını bilmiyor (`api/users.py:48-71`).
- **Yaklaşım:**
  - Kapsam listesi sunucudan gelir (`GET /api/roller` yanıtına ya da `/api/izinler` yanına `kapsamlar` eklenir).
  - `_SAYFA_IZINLERI` personel ve servis sayfalarıyla genişler.
  - E01-D02 ile **tek uygulama**: hangisi önce kodlanırsa o yapar.
- **Kabul:** Rol düzenleme ekranında KENDI_BIRIMI ve KENDI_ISLERI seçilebilir; rol önizlemesi Personel ve servis sayfalarını listeler.

### E13-D03 · Personel kişisel verisinin KVKK uyumu (P2 · S)
- **Canlı:** KISMEN.
  - KVKK erişim kaydı (`services/kvkk.py:40` `erisim_kaydet`) ve hesap imhası var. İmha, denetim maskelemesini yalnız `accounts` ve `contacts` için yapıyor (`kvkk.py:319-327`).
  - Çalışan verisi (sicil, ayrılış nedeni, personel notu) için ne saklama ne de maskeleme var.
  - `audit.log_change` users değişikliklerini `is_personal_data=false` yazıyor. E13-12 tetikleyicisi devreye girince bu satırlar bir daha maskelenemez.
- **Yaklaşım:**
  - Personel kolonlarına dokunan her `log_change` ve `log` çağrısı `is_personal_data=True`.
  - Personel kartı ve Excel'i `erisim_kaydet` ile kaydedilir.
  - `kvkk.py`'ye "ayrılmış personel anonimleştirme" eklenir: `personel_notu` ve `ayrilis_nedeni` temizlenir, users kaydı ve `full_name` iş geçmişi için kalır, denetim satırları aynı SET LOCAL yolundan maskelenir. Bu işlem `kvkk.yonet` ile ve elle yapılır; otomatik silme yoktur.
- **Kabul:**
  - Personel değişikliği denetimde `is_personal_data=true`.
  - Anonimleştirme sonrası ilgili denetim satırlarında not ve neden görünmez; olayın kendisi korunur.
  - Tetikleyici bu yola izin verir, başka UPDATE yolunu reddeder.
