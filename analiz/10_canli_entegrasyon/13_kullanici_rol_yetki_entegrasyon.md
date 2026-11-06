# E13 — Teknik Servis Rolleri, İzinleri, Birim Kapsamı ve Personel: Canlı ERP Entegrasyon Tasarımı

> **Tarih:** 2026-10-21 · **Hedef:** Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`). Kod yalnız OKUNDU; hiçbir kaynak dosya değiştirilmedi.
> **Girdi:** `analiz\02_moduller\_ozet\13_kullanici_rol_yetki.json` (17 onaylı, 8 reddedilen madde), `13_kullanici_rol_yetki_tasarim.md`, `10_canli_entegrasyon\00_MIMARI_KURALLAR.md` (bağlayıcı). Ayrıca E01 (§2.1 `user_units`, §3 izin/kapsam/rol), E02 (E02-04 kaynak listesi), E08 (K1/K2 personel = kullanıcı), E09 (yönetici kapat, `servis.planla`) belgeleri. Tablo ve izin adları bu belgelerle tutarlıdır.
> **Dosya:satır** referansları `backend/app/...`, `frontend/src/...` ve `deploy/...` köklerine göredir. 2026-10-21'de kod okunarak doğrulandı.
> `dotnet_specific=true` olan tek madde **M13-D01**'dir. Özü (gerçek personel adı depoya girmez, yükleme tek seferlik ve idempotent) yeni sistemde geçerli olduğu için E13-04'e kabul kriteri olarak taşındı.

---

## 1. Özet

### 1.1 Canlıda ne var?

| Öğe | Canlı karşılık | E13 için anlamı |
|---|---|---|
| İzin kataloğu | `permissions.py:14-77` `PERMISSIONS` (Türkçe `x.gor/x.yaz`), roller `:89-248`, kapsam `:80-82` (`TUMU`, `KENDI_MUSTERILERI`) | **Tek kaynak.** Yeni izinler, roller, `BIRIMLER` ve kapsamlar buraya eklenir. |
| Rol/izin tabloları | `models/rbac.py` `permissions`, `role_permissions`, `user_permissions` (gerekçeli istisna), `roles.ozellestirildi` | Aynen kullanılır. Özelleştirilmiş rollere yeni izin inmez; seed uyarı yazar (`seeds/dev.py:44-107`). |
| Kullanıcı | `models/user.py:11-81` (`full_name`, `username`, `is_active`, MFA, `role_id`, istisnalar `selectin`) | **Personel = kullanıcı** (E01 K15, E02 K-01, E08 K1). Ayrı `personnel` tablosu açılmaz; personel alanları `users`'a nullable kolon olarak eklenir. |
| Yetki kontrolü | `api/deps.py:79-97` `require_permission`, `models/user.py:54-65` `has()` (istisna → rol, varsayılan ret) | Kullanıcı her istekte DB'den yüklenir (`services/auth.py:121-133`) → izin değişikliği **anında** etkili. |
| Kullanıcı yönetimi | `api/users.py` (`sistem.kullanici`): rol CRUD, istisna, kullanıcı CRUD, kilit açma | Kendi rolünü/izinlerini değiştirme ve kendini kapatma engelli (`:321-322`, `:424-428`). **Alt küme ve üstünlük kuralı YOK** (bkz. E13-01). |
| Oturum | `services/auth.py:15` 4 sa kayan pencere, `sessions` tablosu, `revoke_all_sessions` (rol/parola/pasiflik/MFA sıfırlamada çağrılıyor, `api/users.py:239-240, 344, 452-458`) | Anında düşürme VAR; **mutlak süre YOK**. |
| Giriş güvenliği | `api/auth.py:38-81`: 5 hatada kalıcı kilit (yönetici açar), MFA (TOTP, zorunlu kılınabilir), denetim kaydı | Kilit VAR. **Kendi parolasını değiştirme ucu yok**, zorunlu değişim yok, zamanlama eşitliği yok. |
| Denetim izi | `models/audit.py` (yalnız INSERT niyeti), `services/audit.py:19-23` parola/TOTP maskeleme, `api/audit_api.py` (`sistem.denetim`, filtreli liste) | Görüntüleme VAR. **DB seviyesinde değişmezlik yok** (`deploy/db-least-privilege.sql:23` UPDATE/DELETE veriyor). **Gerçek istemci IP'si büyük olasılıkla yanlış** (`api/deps.py:121-122` + compose port eşlemesi). |
| Kayıt kapsamı | `services/accounts.py:29-61` `kapsam_musteri`/`kapsam_disinda_mi`, `api/deps.py:108-118` `scope_filter` | Yalnız `KENDI_MUSTERILERI`'ne bakar. Yeni kapsamlar diğer modüllerde `TUMU` gibi davranır → mobilite akışı bozulmaz. |
| Birim / personel / vekâlet / işten çıkış / erişim gözden geçirme | **YOK** | E13 kurar. `user_units` tablosu E01-01 ile açılır; E13 yönetim ekranını, kurallarını ve testlerini ekler. |
| CI | `.github/workflows` yok; `make test` gerçek PG17 `_test` DB'de | Yetki matrisi testi `make test`'e eklenir; CI dosyası depo GitHub'a taşınınca devreye girer. |

**Sonuç:** 17 maddenin 7'si **KISMEN**, 10'u **YOK**. Hiçbiri tam VAR değil; ama canlıdaki RBAC omurgası (istisna, kendi-yetkisini-değiştirememe, oturum düşürme, maskeleme, MFA) eski V1.20.1'den güçlüdür ve **korunur**; E13 yalnız ekleme yapar.

### 1.2 Bağımlılık ve sıra

```
E13 çekirdek (bu belge §2-§3, E13-01..07)  ──►  E01 servis iş emri  ──►  E02 planlama / E09 zaman
        │                                                                     │
        └── E13-08 (ad eşleme) ─────► E01/E09 göçü          E13-09 (işten çıkış) ◄┘ (E01 atama + E09 sayaç gerekir)
E13-12/13 (denetim + parola) bağımsız, ilk sürümle birlikte
E13-15..17 (vekâlet, erişim gözden geçirme, yönetici ilişkisi) en son
```

`user_units` tablosu E01-01'de tanımlı (E01 K21: "Kullanıcı ekranındaki birim yönetimi E13'te genişletilir"). İki belge çakışmasın diye **tek migration** kuralı: `servis_birim_uyeligi` migration'ı E13 sürümünde açılır ve E01 onu kullanır.

### 1.3 Kullanıcının bizzat doğruladığı işlevler (kaybedilmez)

| İşlev | E13'teki yeri |
|---|---|
| **KPI kutuları tıklanabilir** | E13-16 erişim gözden geçirme sayfası: her kutu (hassas izin, sapma, 60+ gün girişsiz, ayrılmış ama hesabı açık) tıklanınca aynı filtreli listeyi açar; sayı = liste `X-Toplam-Kayit`. Personel sayfası üst kutuları (birim başına aktif teknisyen, birimsiz personel, girişsiz personel) aynı `KpiKutusu` bileşeniyle (E12) tıklanır. |
| **Toplu planlama / atama** | E13-07 `atanabilir_personel()` tek kaynaktır; E02 toplu atama ve plan penceresi kişi seçicileri yalnız bu servisten beslenir. Gömülü isim kalmaz. Ek birimli kişi her iki birimin toplu atama listesinde görünür. |
| **Excel export** | Personel listesi, erişim gözden geçirme ve ad eşleme raporu `services/export.py` `satirlari_xlsx_async` ile (`rapor.disaaktar` + ilgili görme izni). Dışa aktarım `audit.log(..., is_personal_data=True)`. |
| **Cihaz başına PB iş emri** | E13 doğrudan dokunmaz. Worker'ın ürettiği PB işleri birime göre (`service_orders.birim`) `kapsam_birim` ile süzülür; E13-11 "boş birim = hiçbiri" kuralı sayesinde birimsiz bir şef yanlışlıkla tüm PB işlerini görmez. |

---

## 2. Yerleşim

### 2.1 Dosyalar (yeni / değişen)

```
backend/app/permissions.py                       # + BIRIMLER, SCOPE_OWN_UNITS, SCOPE_OWN_JOBS (E01 ile ortak), yeni izinler/roller,
                                                 #   YUKSEK_YETKILI_IZINLER, SAHA_ROLLERI, AYRILIS_NEDENLERI
backend/app/models/user.py                       # + personel kolonları, birimler ilişkisi, has() vekâlet katmanı
backend/app/models/rbac.py                       # + UserUnit (user_units), UserDelegation (P3)
backend/app/models/personel.py                   # + PersonnelNameMap (göç eşleme tablosu)
backend/app/models/__init__.py                   # import + __all__
backend/app/services/yetki.py                    # YENİ: yetki_verilebilir_mi(), son_admin_mi(), ust_yetkili_mi(), hedef_kontrol()
backend/app/services/auth.py                     # + SESSION_MAX (mutlak süre), sabit-süreli authenticate, parola_degistir, gecici_parola_uret
backend/app/services/teknik_servis/kapsam.py     # kapsam_birim, birim_disinda_mi (E01), + kapsam_personel, personel_disinda_mi (E08 ile ortak)
backend/app/services/teknik_servis/personel.py   # YENİ: atanabilir_personel, cikis_onizleme, cikis_uygula, personel_aktiflestir, birimleri_yaz
backend/app/services/teknik_servis/ad_esleme.py  # YENİ: eski ad kaynaklarından öneri üretimi + onaylı uygulama (idempotent)
backend/app/services/audit.py                    # + guvenlik_olayi() ince sarmalayıcı (entity="guvenlik")
backend/app/services/kvkk.py                     # :325 öncesi SET LOCAL denge.kvkk_imha='1' (tetikleyiciyle uyum)
backend/app/api/users.py                         # alt küme/üstünlük kuralları, SCOPES kontrolü, birim ve giriş alanları
backend/app/api/auth.py                          # + POST /parola, /me çıktısına birimler, parola_degismeli
backend/app/api/deps.py                          # current_user: parola_degismeli → 403 (MFA kalıbı), vekâlet yükleme
backend/app/api/personel.py                      # YENİ: APIRouter(prefix="/api/personel", tags=["personel"])
backend/app/api/erisim_gozden.py                 # YENİ (P3): /api/kullanicilar/erisim-gozden-gecirme
backend/app/schemas/auth.py                      # UserOut + birimler, parola_degismeli, giris_acik; UserCreate/UserPatch genişler
backend/app/main.py                              # include_router (main.py:182-209 bloğu)
backend/app/yonetim.py                           # + personel-yukle <xlsx>, ad-esleme-oner, ad-esleme-uygula alt komutları
backend/app/worker.py                            # + vekalet_suresi_dolan (yalnız denetim kaydı), oturum_temizligi mevcut
backend/app/seeds/dev.py                         # ensure_admin → parola_degismeli=True; demo kullanıcılara birim
backend/alembic/versions/<rev>_servis_birim_uyeligi.py          # user_units (E01-01 ile ortak, tek migration)
backend/alembic/versions/<rev>_personel_alanlari.py             # users kolonları + kısıtlar
backend/alembic/versions/<rev>_denetim_degistirilemez.py        # audit_logs tetikleyicisi
backend/alembic/versions/<rev>_personel_ad_esleme.py            # personnel_name_maps
backend/alembic/versions/<rev>_sureli_vekalet.py                # user_delegations (P3)
deploy/db-least-privilege.sql                    # + REVOKE UPDATE, DELETE ON audit_logs (yalnız belge + sql)
docker-compose.yml / deploy/KURULUM.md           # uvicorn --forwarded-allow-ips (gerçek IP)
backend/tests/unit/test_permissions.py           # yeni değişmezler
backend/tests/integration/test_yetki_yukseltme.py, test_oturum_suresi.py, test_parola_yasam_dongusu.py,
    test_personel.py, test_personel_cikis.py, test_birim_kapsami.py, test_denetim_degismezlik.py,
    test_yetki_matrisi.py (parametrik), test_vekalet.py, test_erisim_gozden.py
frontend/src/api/personel.ts
frontend/src/pages/PersonelPage.tsx              # liste + Drawer kart + çıkış sihirbazı
frontend/src/pages/UsersPage.tsx                 # birimler, giriş açık, sapma rozeti, erişim gözden geçirme sekmesi
frontend/src/pages/ParolaDegistirPage.tsx        # zorunlu değişim ekranı (MFA kurulum ekranı kalıbı)
frontend/src/main.tsx (rota /personel, /parola), components/AppLayout.tsx (MENU)
```

**Dokunulmayanlar:** `work_orders` / `work_order_items` / `settlements` zinciri; mevcut `TEKNIK_SERVIS` rolü (mobilite montaj ve onay rolü olarak kalır, izin listesi değişmez); `services/accounts.py` kapsam yardımcıları (yalnız import edilir); `maliyet.gor` rol kümesi; altın kayıt testi.

### 2.2 Veri modeli

#### 2.2.1 `users` genişletmesi (nullable / varsayılanlı; mevcut satırlar etkilenmez)
`users` tablosu `SoftDeleteMixin`/`ActorMixin` almıyor; E13 bunu değiştirmez (göç riski). Personel kolonları:

| Kolon | Tip | Kısıt / Not |
|---|---|---|
| giris_acik | Boolean NOT NULL default true | Giriş yetkisi. `false` = girişsiz saha personeli (E08 K2'deki "rastgele parola" hilesinin açık hâli). `authenticate` ve `resolve_session` bunu da ister. |
| sicil_no | String(30) NULL | `uq_users_sicil_no` kısmi tekil WHERE sicil_no IS NOT NULL → tekrar 409 |
| unvan | String(80) NULL | Serbest ünvan; yetki ya da atama listesi buna BAKMAZ |
| saha_rolu | String(12) NULL | `ck_users_saha_rolu` IN (SEF, TEKNISYEN, STAJYER, OFIS, YOK) → `SAHA_ROLLERI` |
| ise_giris_tarihi | Date NULL | |
| ayrilis_tarihi | Date NULL | Personel durumu: NULL = çalışıyor |
| ayrilis_nedeni | String(20) NULL | `ck_users_ayrilis_nedeni` IN (ISTIFA, FESIH, EMEKLILIK, SOZLESME_SONU, DIGER); `ck_users_ayrilis` (ayrilis_tarihi IS NULL) = (ayrilis_nedeni IS NULL) |
| ayrilisi_yapan_id | BigInteger FK users SET NULL | `fk_users_ayrilisi_yapan` |
| yonetici_id | BigInteger FK users SET NULL | P3 (E13-17); `ck_users_yonetici_kendisi` (yonetici_id IS NULL OR yonetici_id <> id); döngü servis katmanında |
| personel_notu | Text NULL | Yalnız `personel.yaz` sahibine döner |
| parola_degismeli | Boolean NOT NULL default false | Sunucuda zorunlu değişim (E13-13) |
| gecici_parola_bitis | DateTime(tz) NULL | Geçici parola 72 sa |
| parola_degisti_at | DateTime(tz) NULL | |
| son_giris_at | DateTime(tz) NULL | Erişim gözden geçirme (60+ gün) |

Anlam ayrımı (E13-03'ün çekirdeği):
- `is_active` = **personel/hesap kaydı canlı** (E08 K2 ile aynı: `false` yalnız "ayrıldı/kapatıldı").
- `giris_acik` = **oturum açabilir mi**.
- Giriş koşulu: `is_active AND giris_acik`. Personeli yeniden aktifleştirmek `giris_acik`'a dokunmaz.

#### 2.2.2 `user_units` (E01 §2.1 ile aynı; tek migration)
PK (`user_id`, `birim`), `user_id` FK users CASCADE, `birim` `ck_user_units_birim` → `BIRIMLER`, `is_primary` + `uq_user_units_birincil` kısmi tekil (user_id) WHERE is_primary, `created_at`/`created_by`. `User.birimler` ilişkisi `lazy="selectin"` (izin istisnaları kalıbı, N+1 yok).

#### 2.2.3 `personnel_name_maps` (E13-08)
`PkMixin, TimestampMixin, ActorMixin, VersionedMixin`.

| Kolon | Not |
|---|---|
| kaynak_sistem | String(30) (ör. `V1_20_1`) |
| kaynak_alan | String(60) (ör. `WorkOrders.AssignedName`, `TimeEntries.PersonnelName`) |
| kaynak_ad | String(150) — ham metin, değişmez |
| normal_ad | String(150) — `services/normalize.py` ile (Türkçe büyük harf, boşluk) |
| kayit_sayisi | Integer |
| onerilen_user_id / onaylanan_user_id | FK users SET NULL |
| durum | `ck_pnm_durum` IN (ONERI, ONAYLANDI, ESLESMEDI, REDDEDILDI) |
| onaylayan_id / onay_at | |
| Kısıt | `uq_pnm_kaynak` (kaynak_sistem, kaynak_alan, normal_ad) |

#### 2.2.4 `user_delegations` (E13-15, P3)
`PkMixin, TimestampMixin, ActorMixin, VersionedMixin`. `veren_id`, `alan_id` (FK users RESTRICT), `izinler` ARRAY(String(50)), `birimler` ARRAY(String(20)), `baslangic`, `bitis` (tz), `gerekce` String(300) NOT NULL, `iptal_at`, `iptal_eden_id`.
Kısıtlar: `ck_ud_kendine` (veren_id <> alan_id), `ck_ud_sure` (bitis > baslangic AND bitis - baslangic <= interval '30 days'), `ix_ud_alan_aktif` (alan_id) WHERE iptal_at IS NULL.

#### 2.2.5 `audit_logs` tetikleyicisi (E13-12)
`trg_audit_degistirilemez` (BEFORE UPDATE OR DELETE):
- DELETE → her zaman `RAISE EXCEPTION`.
- UPDATE → yalnız `current_setting('denge.kvkk_imha', true) = '1'` iken, yalnız `old_value`/`new_value` değişiyorsa ve satır `is_personal_data` ise izinli. Bu, `services/kvkk.py:325`'teki KVKK imha akışını korur.

### 2.3 Migration sırası
Zincir güncel head `b30e012dd879`'a bağlanır (kodlamaya başlarken `alembic heads` ile yeniden doğrulanır; tek head kuralı):
1. `make makemigration m="servis_birim_uyeligi"`: `user_units` (E01-01 de bunu kullanır; ikinci kez açılmaz).
2. `make makemigration m="personel_alanlari"`: §2.2.1 kolonları + `uq_users_sicil_no`, `ck_users_*`. **Geçiş verisi:** mevcut kullanıcılara `giris_acik=true`; birim ve saha rolü **yazılmaz** (uydurma veri yok). Downgrade kolonları düşürür.
3. `make makemigration m="denetim_degistirilemez"`: tetikleyici fonksiyonu ve tetikleyici `op.execute` ile elle; downgrade ikisini düşürür.
4. `make makemigration m="personel_ad_esleme"`: `personnel_name_maps`.
5. (P3) `make makemigration m="sureli_vekalet"`: `user_delegations`.
Her migration başına NEDEN açıklaması yazılır; head→base→head testi (`test_migration_zinciri`) koşar. Canlı tablolarda (`work_orders`, `settlements`, `devices`, `stock_*`) hiçbir CHECK/EXCLUDE değişmez.

---

## 3. İzinler, kapsam ve roller

### 3.1 Sabitler (`permissions.py`)
```python
BIRIMLER = {"GUVENLIK": "Güvenlik Sistemleri", "HABERLESME": "Haberleşme", "POC": "POC",
            "MOBILITE": "Mobilite", "ARAC_TAKIP": "Araç Takip"}
SCOPE_OWN_UNITS = "KENDI_BIRIMI"      # E01 §3.2
SCOPE_OWN_JOBS  = "KENDI_ISLERI"      # E01 §3.2 / K22
SCOPES = (SCOPE_ALL, SCOPE_OWN_CUSTOMERS, SCOPE_OWN_UNITS, SCOPE_OWN_JOBS)
BIRIM_KAPSAMLARI = (SCOPE_OWN_UNITS, SCOPE_OWN_JOBS)   # birim zorunlu olan kapsamlar
SAHA_ROLLERI = ("SEF", "TEKNISYEN", "STAJYER", "OFIS", "YOK")
ATANABILIR_SAHA_ROLLERI = ("SEF", "TEKNISYEN", "STAJYER")
AYRILIS_NEDENLERI = ("ISTIFA", "FESIH", "EMEKLILIK", "SOZLESME_SONU", "DIGER")
# Yalnız ADMIN rolündeki kişinin verebileceği/alabileceği izinler (eski "*", users.manage, audit.view karşılığı)
YUKSEK_YETKILI_IZINLER = frozenset({"sistem.kullanici", "sistem.denetim", "sistem.ayar", "sistem.goc", "kvkk.yonet"})
# Vekâletle verilemeyecek izinler (M13-04)
VEKALETE_KAPALI = YUKSEK_YETKILI_IZINLER | {"maliyet.gor", "hakedis.onayla", "hakedis.ode", "tahsilat.yaz", "vekalet.ver"}
```

### 3.2 Yeni izin kodları (modül "Personel")
| Kod | Açıklama |
|---|---|
| `personel.gor` | Personel listesini ve kartını görür (birim kapsamlı) |
| `personel.yaz` | Personel kartı açar/düzenler: ünvan, sicil, saha rolü, birimler, işe giriş; girişsiz personel açar; ayrılmış personeli yeniden aktifleştirir (hesabı açmaz) |
| `personel.cikis` | İşten çıkış önizlemesi ve onayı |
| `vekalet.ver` | Süreli vekâlet verir/iptal eder (P3) |

Servis izinleri (`servis.*`, `zaman.yaz`, `bakim.*`, `kiralama.*`, `egitim.*` …) E01/E04/E06/E08/E09 belgelerinde tanımlıdır; E13 onları yeniden tanımlamaz, yalnız rol tablosunu birleştirir. Excel için yeni izin açılmaz (`rapor.disaaktar` + görme izni). Erişim gözden geçirme `sistem.kullanici` ile açılır.

### 3.3 Roller (`ROLES`; mevcut 9 rol DEĞİŞMEZ)
| Kod | Ad | Kapsam | E13'ün eklediği izinler (servis izinleri E01 §3.3'teki gibi) |
|---|---|---|---|
| SERVIS_YONETICI | Teknik Servis Müdürü | TUMU | `personel.gor`, `personel.yaz`, `personel.cikis`, `vekalet.ver` |
| SERVIS_SEF | Servis Şefi / Takım Lideri | KENDI_BIRIMI | `personel.gor` |
| SERVIS_OPERASYON | Servis Operasyon Uzmanı | KENDI_BIRIMI | `personel.gor` |
| SERVIS_TEKNISYEN | Servis Teknisyeni | KENDI_ISLERI | — |
| ATOLYE | Atölye Teknisyeni | KENDI_BIRIMI | — |
| IK | İnsan Kaynakları | TUMU | `personel.gor`, `personel.yaz`, `personel.cikis`, `gorev.gor`, `gorev.yaz` (servis/maliyet izni yok) |

- `ADMIN` hepsini alır (`tuple(PERMISSIONS)`).
- `YONETIM` `personel.gor`'ü `_READ_ONLY_ALL` üzerinden kendiliğinden alır (`permissions.py:84`). Bu bilinçli: salt okunur yönetim personel listesini görür; `personel_notu` görmez (yalnız `personel.yaz`).
- `sistem.kullanici` yalnız `ADMIN`'de kalır (S1 kararı, §5 K-02).
- `maliyet.gor` kümesi `{ADMIN, SATIS_MUDURU, MUHASEBE_DESTEK, YONETIM}` değişmez (`tests/unit/test_permissions.py:26`).
- Özelleştirilmiş DB rollerine yeni izin inmez; kurulum notunda elle ekleme listesi verilir (`seeds/dev.py:101-106` uyarısı zaten bunu log'a yazar).

### 3.4 Kapsam uygulayıcıları (`services/teknik_servis/kapsam.py`)
- `kullanici_birimleri(user) -> frozenset[str]` (vekâletle gelen birimler dahil).
- `kapsam_birim(stmt, user, sutun)`: kapsam ∈ `BIRIM_KAPSAMLARI` ise `sutun.in_(birimler)`; **boş küme → `false()`** (E13-11). `TUMU` ve `KENDI_MUSTERILERI` → dokunmaz.
- `birim_disinda_mi(user, birim) -> bool` → tek kayıt uçlarında 404.
- `kapsam_personel(stmt, user, kisi_sutunu)` ve `personel_disinda_mi(db, user, hedef_id)` (E08 §… ile aynı imza): `EXISTS(user_units uu WHERE uu.user_id = kisi AND uu.birim IN :birimler)`; birimsiz personel yalnız `TUMU` kapsamına görünür.
- Yazma uçlarında birim **değiştirme** kontrolü: yeni birimlerin tamamı yazanın birimlerinde olmalı (`api/accounts.py:441-447` emsali), değilse 404.

---

## 4. Maddeler

### E13-01 · Yetki yükseltme önlemi: katalog, alt küme, üstünlük ve "son yönetici" kuralları (M13-12)
- **Canlı:** KISMEN.
  - VAR: katalog dışı izin 400 (`api/users.py:153-155, 323-325`); bilinmeyen rol 400 (`:381-382, 437-439`); kendi izinlerini (`:321-322`), rolünü ve aktifliğini (`:424-428`) değiştirememe; kullanıcı adı PATCH ile değiştirilemez (`schemas/auth.py:83-91` `UserPatch`'te `username` yok).
  - YOK: `sistem.kullanici` sahibi başkasına `ADMIN` rolü verebilir (`:436-440`), istisnayla `sistem.kullanici`/`sistem.denetim` verebilir (`:302-356`), sahip olmadığı izinlerle yeni rol açabilir (`:178-206`). `ADMIN` rolünün izinleri boşaltılabilir (`:209-258`) → herkes kilitlenir. Son aktif ADMIN başka bir ADMIN tarafından kapatılabilir.
- **Yaklaşım:**
  - `services/yetki.py` (saf iş kuralı, flush yok):
    - `verilebilir_mi(aktor, kodlar) -> list[str]`: dönen liste = aktörün `etkin_izinler()`'inde olmayan **veya** `YUKSEK_YETKILI_IZINLER` içinde olup aktörün rolü `ADMIN` olmayan kodlar.
    - `rol_atanabilir_mi(aktor, rol)`: rol izinleri ⊆ aktör izinleri; `rol.code == "ADMIN"` ise aktör ADMIN olmalı.
    - `ust_yetkili_mi(hedef)`: hedef `ADMIN` rolünde ya da `sistem.kullanici` sahibi.
    - `son_admin_mi(db, hedef)`: `is_active AND giris_acik AND role.code='ADMIN'` sayısı 1 ve hedef o kişi.
  - `api/users.py` değişiklikleri:
    - `rol_olustur` / `rol_guncelle`: izin listesi `verilebilir_mi` ile denetlenir → 403 "Sahip olmadığınız izni veremezsiniz: …".
    - `rol_guncelle(kod="ADMIN")` → 409 "Sistem yöneticisi rolü katalogdan yönetilir". ADMIN rolü `ozellestirildi` olamaz.
    - `create_user` / `patch_user(role_code)`: `rol_atanabilir_mi` → 403.
    - `istisnalari_yaz`: `allow=True` satırları `verilebilir_mi` ile → 403. `allow=False` (kısma) her zaman serbest; ancak hedef `ust_yetkili_mi` ise aktör ADMIN olmalı.
    - `patch_user(is_active=False | giris_acik=False | role değişimi)`: hedef `son_admin_mi` → 409; hedef `ust_yetkili_mi` ve aktör ADMIN değil → 403.
    - Kapsam doğrulaması `(SCOPE_ALL, SCOPE_OWN_CUSTOMERS)` sabiti yerine `SCOPES` (`:181`, `:225`); `_KAPSAM_ACIKLAMA` (`:73-76`) iki yeni kapsamla genişler.
  - Kendi birimini değiştirme: `PUT /api/kullanicilar/{id}/birimler` ve personel kartı birim alanı, `hedef.id == aktor.id` ise 400 "Kendi biriminizi değiştiremezsiniz".
  - Her ret ve kabul `audit.log("users" | "roles", "yetki.ret" | …)` ile denetime yazılır (ret de bir güvenlik olayıdır; E13-12).
- **Dosyalar:** `services/yetki.py`, `api/users.py`, `permissions.py` (`YUKSEK_YETKILI_IZINLER`), `tests/integration/test_yetki_yukseltme.py`.
- **Kabul:**
  - `sistem.kullanici` istisnasıyla donatılmış ADMIN olmayan hesap: başkasına `ADMIN` rolü (403), `sistem.kullanici`/`sistem.denetim` istisnası (403), sahip olmadığı izni içeren yeni rol (403) veremez.
  - Katalog dışı izin 400; bilinmeyen rol 400 (mevcut testler yeşil kalır).
  - `personel.cikis` sahibi IK teknisyeni pasifleştirebilir (200), ADMIN'i pasifleştiremez (403).
  - Son aktif ADMIN kapatılamaz / rolü değiştirilemez (409); ADMIN rolünün izinleri değiştirilemez (409).
  - Kimse kendi izinlerini, rolünü, birimini değiştiremez veya kendini pasifleştiremez (400).
  - Ret denemesi denetim kaydında görünür.
- **Öncelik/Efor:** P1 · M
- **Bağımlılık:** Yok (ilk yapılacak). E13-03 ile aynı sürüm.
- **Canlı risk:** Düşük. Bugün `sistem.kullanici` yalnız ADMIN'de (`permissions.py:90`) olduğundan mevcut yöneticinin hiçbir işlemi reddedilmez. Önlem: ADMIN aktörü için kuralların tümü geçer; `test_auth_rbac.py` mevcut 15 testi değişmeden yeşil kalmalı.

### E13-02 · Oturum: pasifleştirme/parola/yetki daraltma anında yansır; mutlak süre (M13-13)
- **Canlı:** KISMEN.
  - VAR: kullanıcı her istekte DB'den okunur (`services/auth.py:121-133`), `is_active=false` olunca sonraki istek 401; rol/parola/aktiflik/MFA sıfırlama ve istisna değişiminde `revoke_all_sessions` (`api/users.py:239-240, 344, 452-458`); rol izni değişince etki anında (izinler istekte yükleniyor) → "60 sn içinde 403" fazlasıyla karşılanıyor. Hareketsizlik süresi 4 sa (kullanıcı kararı, `services/auth.py:12-15`).
  - YOK: **mutlak süre**. Kayan pencere her istekte uzadığı için sürekli kullanılan oturum hiç bitmez. `giris_acik` kavramı yok.
- **Yaklaşım:**
  - `services/auth.py`: `SESSION_MAX = timedelta(hours=12)`; `resolve_session` → `now - sess.created_at >= SESSION_MAX` ise None (401). Kayan uzatma `min(now + SESSION_TTL, created_at + SESSION_MAX)`.
  - `resolve_session` ve `authenticate` ek koşul `user.giris_acik`.
  - Birim değişikliği (`user_units`) ve vekâlet verme/iptali de `revoke_all_sessions` çağırır (kapsam değişti).
  - Çerez `max_age` değişmez (sunucu tarafı belirleyici).
  - Süreler `services/settings.py DEFAULTS`'a taşınmaz: güvenlik sabiti, arayüzden gevşetilemesin (K-05).
- **Dosyalar:** `services/auth.py`, `api/users.py`, `api/personel.py`, `tests/integration/test_oturum_suresi.py` (FakeClock).
- **Kabul:**
  - Pasifleştirilen, `giris_acik=false` yapılan veya parolası sıfırlanan hesabın tüm oturumları sonraki istekte 401.
  - Rolden kaldırılan izin aynı oturumdaki sonraki istekte 403.
  - FakeClock ile 4 sa hareketsizlik → 401; her 20 dk'da istek atan oturum 12. saatte 401.
  - Birimi değişen kullanıcının oturumu düşer.
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E13-01 ile aynı sürüm.
- **Canlı risk:** Düşük. Mobilite kullanıcıları 12 saatte bir yeniden giriş yapar (MFA dahil). Önlem: sürüm notunda duyurulur; worker `oturum_temizligi` (`worker.py:79`) değişmez.

### E13-03 · Personel yeniden aktifleştirme giriş hesabını açmaz (M13-D02)
- **Canlı:** YOK. Personel kavramı yok; tek bayrak `is_active` hem "çalışıyor" hem "girebilir" anlamında.
- **Yaklaşım:**
  - `is_active` (kayıt canlı) ve `giris_acik` (oturum açabilir) ayrılır (§2.2.1).
  - `services/teknik_servis/personel.py:personel_aktiflestir(db, hedef, aktor)`: `personel.yaz` ister; `is_active=True`, `ayrilis_*` temizlenir, **`giris_acik` değişmez** (çıkışta `false` yapılmıştı). Yanıt `{"giris_acik": false, "mesaj": "Giriş hesabı ayrıca açılmalı"}`.
  - Girişi açmak yalnız `PATCH /api/kullanicilar/{id} {giris_acik: true, password}` ile (`sistem.kullanici` + E13-01 kuralları) ve geçici parolayla (E13-13) yapılır.
  - Kişi kendi personel kaydını pasifleştiremez (400).
  - `audit.log("users", "personel.aktiflestir", old/new)`.
- **Dosyalar:** `models/user.py`, `services/teknik_servis/personel.py`, `api/personel.py`, `tests/integration/test_personel.py`.
- **Kabul:**
  - Ayrılmış personel aktifleştirilince `is_active=true`, `giris_acik=false` kalır; giriş denemesi 401.
  - Yanıt "hesap ayrıca açılmalı" der.
  - Kendi kaydını pasifleştirme 400.
  - İşlem denetim kaydında.
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E13-01, E13-05.
- **Canlı risk:** Düşük. Mevcut kullanıcıların `giris_acik` değeri migration'da `true`.

### E13-04 · Gerçek personel listesi depoya girmez; yükleme tek seferlik ve idempotent (M13-D01, dotnet_specific → öz)
- **Canlı:** KISMEN. Demo kullanıcılar sahte adlı ve yalnız `ENV=dev` (`seeds/dev.py:131-159`); ilk admin rastgele parolalı (`:110-125`). Test fixture'ları sahte ad (`tests/conftest.py:192`). Personel yükleme komutu yok.
- **Yaklaşım:**
  - `python -m app.yonetim personel-yukle <dosya.xlsx> [--yaz]` alt komutu (`yonetim.py:412` argparse kalıbı). Dosya depo dışında; varsayılan kuru çalışma (`--yaz` yoksa yalnız rapor).
  - Eşleşme anahtarı sırayla `sicil_no`, yoksa `username`. Var olan kayıt güncellenir, yoksa `giris_acik=false` personel açılır → iki kez çalıştırma hiçbir şeyi çoğaltmaz.
  - Birim ve saha rolü Excel'den yalnız açık sütun olarak okunur; tahmin yazılmaz.
  - Komut hiçbir izni/istisnayı geri getirmez, rol atamaz (girişsiz personel varsayılan rolü `SERVIS_TEKNISYEN`; giriş kapalıyken etkisizdir).
  - Migration'lar personel verisi içermez (§2.3 madde 2).
  - `tests/fixtures/personel_ornek.xlsx` sahte adlı.
- **Dosyalar:** `yonetim.py`, `services/teknik_servis/personel.py:toplu_yukle`, `tests/integration/test_personel_yukle.py`.
- **Kabul:**
  - Komut iki kez `--yaz` ile çalıştırılınca kullanıcı sayısı değişmez.
  - `alembic downgrade base && upgrade head` personel üretmez.
  - `grep` testi: `backend/` ve `frontend/src` altında gerçek personel adı listesi (eski `app.js` gömülü listesi) yok (E02-18 ile ortak test).
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E13-05.
- **Canlı risk:** Yok.

### E13-05 · Personel kartı = kullanıcı kaydı; giriş aç/kapat; ad tek kaynak (M13-01 A/B)
- **Canlı:** KISMEN. Kullanıcı kaydı ve ekranı VAR (`api/users.py:370-462`, `pages/UsersPage.tsx`); personel alanları, girişsiz personel ve personel izni YOK. Eski "hesabı personele bağla/ayır" kavramı, personel = kullanıcı kararıyla (E01 K15, E08 K1) **yapısal olarak gereksizleşir**: bağ yok, tek satır var.
- **Yaklaşım:**
  - (A) "Bağlama/ayırma" karşılığı: `giris_acik` aç/kapat. Kapatmak hesabı pasif yapmaz (`is_active` dokunulmaz), oturumları düşürür. "İkinci personele bağlama 409" kuralının karşılığı: aynı kişi için ikinci kayıt `uq_users_sicil_no` ve `username` tekilliği ile 409.
  - (B) Ad senkronu: tek `full_name` alanı var; atamalar `users.id` ile (E01 K15) → ad değişikliği atamaları bozmaz, uyarı gerekmez.
  - Uçlar (`api/personel.py`, `Okuyucu = personel.gor`, `Yazici = personel.yaz`):
    - `GET /api/personel` (sayfala; filtre `birim`, `saha_rolu`, `durum`=CALISIYOR|AYRILDI, `giris`=ACIK|KAPALI, `q`) + `kapsam_personel`.
    - `GET /api/personel/{id}` → kapsam dışı 404; KVKK `erisim_kaydet`.
    - `POST /api/personel` (girişsiz personel: `full_name`, `sicil_no`, `unvan`, `saha_rolu`, `birimler`, `ise_giris_tarihi`). `username` sunucuda `p.<id>` üretilir; parola özeti rastgele; `giris_acik=false`.
    - `PATCH /api/personel/{id}` (`version` zorunlu, 409; yalnız personel alanları — rol/izin/parola/giriş bu uçta YOK).
    - `GET /api/personel.xlsx` (`rapor.disaaktar`).
  - `PersonelOut`: `email`, `username`, `personel_notu` yalnız `personel.yaz` sahibine; hiçbir yerde fiyat/maliyet yok.
  - Ön yüz `PersonelPage.tsx`: `useQuery(["personel", filtreler, sayfa])` + sunucu sayfalaması + Drawer kart; `KartPenceresi` kalıbı tek form; üstte tıklanabilir KPI kutuları (birim başına aktif saha personeli, birimsiz personel, girişsiz personel); MENU `{key:"/personel", label:"Personel", icon:<IdcardOutlined/>, izin:"personel.gor"}`. `_SAYFA_IZINLERI`'ne ("Personel", "personel.gor") eklenir (`api/users.py:48-71`).
  - `UsersPage.tsx` kullanıcı formuna "Giriş açık" anahtarı ve "Birimler" çoklu seçimi.
- **Dosyalar:** `models/user.py`, `api/personel.py`, `schemas/auth.py`, `services/teknik_servis/personel.py`, `pages/PersonelPage.tsx`, `UsersPage.tsx`, `api/personel.ts`, `main.tsx`, `AppLayout.tsx`, `tests/integration/test_personel.py`.
- **Kabul:**
  - IK rolü girişsiz personel açar (201), aynı sicille ikinci kayıt 409.
  - `giris_acik=false` yapılan hesap 401 alır ama atama listelerinde görünmeye devam eder.
  - Ad değişince açık atamalar aynı kişide kalır.
  - `personel.gor` olmayan 403; `KENDI_BIRIMI` şef başka birimin personel kartında 404.
  - Liste/Excel yanıtında `personel.yaz` yoksa `personel_notu`, `email`, `username` anahtarı yok.
- **Öncelik/Efor:** P1 (A) · M
- **Bağımlılık:** E13-01, migration 1-2.
- **Canlı risk:** Düşük. `UserOut` (`schemas/auth.py:17-52`) yalnız ek alan alır; mevcut istemci bozulmaz.

### E13-06 · Birim üyeliği yönetimi ve çoklu birim (M13-D03 + birim altyapısı)
- **Canlı:** YOK. `user_units` tablosu ve birim kavramı yok.
- **Yaklaşım:**
  - `user_units` (E01-01 tanımı, migration 1).
  - `services/teknik_servis/personel.py:birimleri_yaz(db, hedef, birimler, birincil, aktor)`:
    - `personel.yaz` **veya** `sistem.kullanici` ister.
    - Kendi birimi 400.
    - Aktör `KENDI_BIRIMI` kapsamındaysa (ör. ileride şefe verilirse) yalnız kendi birimlerini ekleyip çıkarabilir.
    - Hedef `ust_yetkili_mi` ise aktör ADMIN olmalı (403).
    - Birincil birim tam bir tane (`uq_user_units_birincil`); birimler boş değilse birincil zorunlu (400).
    - Kapsam değiştiği için `revoke_all_sessions`; `audit.log("users","birim.degistir", old/new)`.
  - Uç: `PUT /api/personel/{id}/birimler {birimler:[…], birincil}`; aynı fonksiyonu kullanıcı ekranı da çağırır.
  - `/api/auth/me` (`UserOut`) `birimler: list[str]`, `birincil_birim` döner; ön yüz birim seçicilerini buradan doldurur.
  - Eski gömülü birim–kişi ilişkisi yalnız **öneri raporu** olarak (`yonetim.py personel-yukle` kuru çalışma çıktısında "öneri" sütunu) üretilir; İK onayıyla `--yaz` uygulanır.
- **Dosyalar:** `models/rbac.py` (UserUnit), `models/user.py` (ilişki), `services/teknik_servis/personel.py`, `api/personel.py`, `schemas/auth.py`, `tests/integration/test_birim_kapsami.py`.
- **Kabul:**
  - Personel kartında katalog dışı birim 400 (`ck_user_units_birim` + Pydantic).
  - Mobilite + Araç Takip üyesi kişi iki birimin atama listesinde görünür (E13-07 testiyle).
  - Kendi birimini değiştirme 400; birim değişince oturum düşer.
  - `/api/auth/me` birimleri döner.
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E13-01, E13-05.
- **Canlı risk:** Yok. Mevcut roller `KENDI_BIRIMI` kullanmadığı için hiçbir canlı kullanıcı birimsizlikten etkilenmez.

### E13-07 · Saha rolü ve atanabilir personel servisi (M13-02)
- **Canlı:** YOK. Mobilite iş emrinde atama `assigned_type/assigned_id` (`models/workorder.py:72, 111-112`) ve dokunulmaz; servis tarafında kaynak listesi E02-04'te tanımlı ama "rol kodu ∈ …" filtresine dayanıyor.
- **Yaklaşım:**
  - `services/teknik_servis/personel.py:atanabilir_personel(db, user, birim, saha_rolleri=ATANABILIR_SAHA_ROLLERI) -> list[AtanabilirKisi]`:
    - Koşul: `is_active` AND `ayrilis_tarihi IS NULL` AND `saha_rolu IN :roller` AND `EXISTS user_units(birim=:birim)`. `giris_acik` filtrelenmez (girişsiz stajyer de atanır).
    - `birim_disinda_mi(user, birim)` → 404 (canlı kapsam kalıbı: tek kayıt/parametre kapsam dışı = 404; eski kabuldeki "403" bu nedenle 404 olur, K-08).
    - Dönen alanlar yalnız `{id, ad, saha_rolu, birimler, birincil_birim, giris_acik}`; e-posta, kullanıcı adı, telefon, not, fiyat/maliyet YOK.
    - `personel.gor` gerektirmez; çağıran uç kendi iznini ister (E02-04 `GET /kaynaklar` → `servis.planla` veya `servis.gor`).
  - **E02-04 uyarlaması:** E02-04'teki "rol kodu ∈ {SERVIS_SEF, SERVIS_TEKNISYEN, SERVIS_YONETICI}" filtresi bu servisle değiştirilir. Geçiş sürecinde `saha_rolu IS NULL` ise rol kodundan türetilir (`SERVIS_SEF→SEF`, `SERVIS_TEKNISYEN|ATOLYE→TEKNISYEN`) ve listede "saha rolü girilmemiş" rozeti gösterilir.
  - Saha rolü ünvandan **öneri** olarak `personel-yukle` raporunda üretilir; otomatik yazılmaz.
  - E01 atama kuralı: `service_order_assignments.rol='SEF'` yalnız `saha_rolu='SEF'`, `TEKNISYEN` satırı `TEKNISYEN|STAJYER` kişiye yazılır (servis katmanında 400).
- **Dosyalar:** `services/teknik_servis/personel.py`, E02 `api/teknik_servis_planlama.py` (çağrı), `tests/integration/test_atanabilir_personel.py`.
- **Kabul:**
  - `personel.gor`'süz SERVIS_SEF kendi biriminin (birincil veya ek) aktif saha personelini görür.
  - Mobilite + Araç Takip kişisi iki listede; POC şefi POC listesinde.
  - Ayrılmış personel listede yok; ünvanı "Sistem Mühendisi" + `saha_rolu=TEKNISYEN` olan listede, `saha_rolu=OFIS` olan "müdür" ünvanlı kişi şef listesinde yok.
  - Yanıtta `email`, `username`, fiyat/maliyet anahtarı yok.
  - Kapsam dışı birim parametresi 404.
- **Öncelik/Efor:** P1 · M
- **Bağımlılık:** E13-05, E13-06; tüketici E02-04, E01-12.
- **Canlı risk:** Yok (yalnız yeni servis tablolarını besler).

### E13-08 · Eski ad bazlı kayıtların onaylı eşlemesi ve sicil tekilliği (M13-10)
- **Canlı:** YOK. (E09 göçü eşleşmeyen satırı `user_id=NULL` + `kaynak_personel_adi` ile aktarmayı öngörüyor; eşleme tablosu yok.)
- **Yaklaşım:**
  - `personnel_name_maps` (§2.2.3).
  - `python -m app.yonetim ad-esleme-oner <kaynak_db_dsn|csv>`: tüm eski ad kaynaklarını (iş emri atanan, zaman kaydı personel adı, şef adı, yönetici adı) tarar, `normal_ad` ile gruplar, `kayit_sayisi` ve `normalize` + `pg_trgm` benzerlik önerisi (`onerilen_user_id`) yazar, Excel'e döker (`satirlari_xlsx_async`).
  - Onay `PATCH /api/personel/ad-esleme/{id} {onaylanan_user_id | durum}` (`personel.yaz`, `version`) veya Excel geri yükleme. Yalnız `ONAYLANDI` satırlar uygulanır.
  - `python -m app.yonetim ad-esleme-uygula [--yaz]`: E01/E09 göç tablolarında `user_id IS NULL AND kaynak_personel_adi = :ad` satırlarını doldurur; metin korunur; idempotent (ikinci çalıştırma 0 değişiklik). Eşleşmeyenler `ESLESMEDI` kalır.
  - Kimlik tutarlılığı raporu aynı komutun çıktısıdır (eşleşen/eşleşmeyen/çoklu aday sayıları).
  - Uygulama öncesi SQL yedeği talimatı `deploy/KURULUM.md` göç bölümüne eklenir.
  - `sicil_no` tekrarı 409 (`uq_users_sicil_no`, `main.py:71-77` önek eşlemesi `uq_` → kullanıcı mesajı).
- **Dosyalar:** `models/personel.py`, `services/teknik_servis/ad_esleme.py`, `yonetim.py`, `api/personel.py`, `tests/integration/test_ad_esleme.py`.
- **Kabul:**
  - Öneri çıktısında her ayrı ad için kayıt sayısı ve öneri var.
  - Onay sonrası ilgili satırlarda `user_id` dolar, kaynak metin değişmez.
  - Onaysız ad "eşleşmedi" sayılır; komut iki kez çalışınca ikincisi hiçbir satırı değiştirmez.
  - Aynı `sicil_no` 409.
- **Öncelik/Efor:** P1 · M
- **Bağımlılık:** E13-04, E01/E09 göç kolonları.
- **Canlı risk:** Yok (yalnız yeni servis tablolarına yazar; `work_orders` taranmaz).

### E13-09 · İşten çıkış akışı: önizleme + tek transaction; otomatik süre kaydı yok (M13-03)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `GET /api/personel/{id}/cikis-onizleme` (`personel.cikis`) → `{aktif_atamalar:[so_no, durum], acik_sayac:{bolum_id, baslangic, faaliyet}|null, acik_oturum_sayisi, ust_yetkili:bool}`.
  - `POST /api/personel/{id}/cikis {ayrilis_tarihi, ayrilis_nedeni, version}` → `services/teknik_servis/personel.py:cikis_uygula` tek transaction:
    1. E13-01 kuralları (kendisi 400, son admin 409, üst yetkili + aktör ADMIN değil 403).
    2. `is_active=False`, `giris_acik=False`, `ayrilis_*` yazılır; `revoke_all_sessions`.
    3. Aktif `service_order_assignments` satırları `removed_at=now, removed_by=aktor` ile kapanır (satır silinmez); her iş için `service_order_events` `ATAMA` olayı ("İşten çıkış"). İş durumu DEĞİŞMEZ; atanmamış kalan işler `kpi=yeniden_atanacak` listesine düşer (E01 liste filtresi: açık + aktif sorumlu yok).
    4. **Açık sayaç kapatılmaz** ve süre üretilmez. Açık bölüm olduğu gibi kalır; kişi pasif olduğu için yeni bölüm açılamaz. E09-06 "uzun açık sayaç" uyarısı ve `GET /zaman/...` "şu an çalışanlar" tablosu onu "İnceleme bekliyor (işten çıkış)" etiketiyle gösterir. Yönetici gerçek bitişi `POST /zaman/bolumler/{bid}/yonetici-kapat` ile girer ya da iptal eder; girmezse raporlarda "süre kaydı eksik" (E09 kuralı, `null`).
    5. Görev panosunda (`services/gorevler.py`, `KAYIT_TIPLERI`) "İşten çıkış incelemesi" kartı açılır (aktif atama veya açık sayaç varsa).
    6. `audit.log("users","personel.cikis", old/new)`.
  - Personel aktifleştirme hesabı açmaz (E13-03).
  - Ön yüz: `PersonelPage` Drawer'ında "İşten çıkış" düğmesi → önizleme modalı → onay.
- **Dosyalar:** `services/teknik_servis/personel.py`, `api/personel.py`, `pages/PersonelPage.tsx`, `tests/integration/test_personel_cikis.py`.
- **Kabul:**
  - Önizleme açık işleri ve sayacı gösterir.
  - Onayla personel ve giriş kapanır, oturumlar 401 alır, aktif atamalar `removed_at` dolu, iş durumları değişmemiş.
  - Açık sayaç için `ended_at` NULL kalır ve hiçbir süre satırı oluşmaz; uyarı merkezi "inceleme bekliyor" sayar.
  - Atanmamış işler `kpi=yeniden_atanacak` listesinde.
  - Ardından aktifleştirme girişi açmaz.
  - Hata (ör. sürüm 409) olursa hiçbir adım uygulanmamış (rollback testi).
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E13-02, E13-03, E01 (atamalar, olaylar), E09 (sayaç, yönetici kapat).
- **Canlı risk:** Yok. Mobilite `work_orders.assigned_id` (`models/workorder.py:111-112`) değiştirilmez; önizleme mobilite iş emirlerini yalnız bilgi olarak sayar.

### E13-10 · Rol şablonları ve sapma görünürlüğü (M13-07)
- **Canlı:** KISMEN.
  - VAR: katalog dışı rol 400 (`api/users.py:381-382`); kişiye özel istisna + gerekçe + "rolünden farklı" görünümü (`api/users.py:115-130`, `UsersPage.tsx:345-352`); rol kartı açtığı ekranları gösterir (`:79-112`).
  - YOK: servis rolleri; liste düzeyinde sapma rozeti; Şef/Teknisyen ayrımının izinle ifadesi.
- **Yaklaşım:**
  - §3.3 rol tablosu `permissions.py`'ye. Eski kabul maddelerinin canlı karşılığı:
    - "Şef'e `operations.manage` verilmez" → SLA hedefi değiştirme izni (E10 `sla.yaz`) SERVIS_SEF'e verilmez; bekletme `servis.yaz` ile açıktır.
    - "Sayaç/süre kaydı iptali yalnız `workorders.assign` ister" → E09'daki gibi `servis.planla`; `sistem.kullanici` ile açılmaz.
    - "Depo şablonlu hesap stok hareketi yapabilir" → mevcut `DEPO` rolü `cihaz.transfer` (`permissions.py:142-161`) VAR.
    - "own_only izinli hesap yalnız kendi işleri" → `KENDI_ISLERI` kapsamı (E01 K22).
  - `GET /api/kullanicilar` yanıtına `sapma_sayisi` (istisna satır sayısı) ve `rol_ozellestirildi`; `UsersPage` tablosunda "Rolünden farklı (n)" rozeti.
  - Rol = canlı şablon semantiği korunur (değişiklik roldeki herkese yansır, oturumlar düşer, `api/users.py:213-221`). Eski "şablon değişikliği mevcut hesapları değiştirmez" kuralı alınmaz (K-06).
- **Dosyalar:** `permissions.py`, `api/users.py`, `UsersPage.tsx`, `tests/unit/test_permissions.py`, `tests/integration/test_yetki_matrisi.py`.
- **Kabul:**
  - SERVIS_SEF şablonlu hesap SLA hedefi değiştirmede 403, bekletmede 200.
  - SERVIS_TEKNISYEN sayaç iptalinde 403, SERVIS_SEF 200.
  - DEPO hesabı stok transferinde 200.
  - `KENDI_ISLERI` hesabı yalnız kendi işlerini görür.
  - Katalog dışı rol 400; istisnalı kullanıcı listede rozetli.
- **Öncelik/Efor:** P2 · S
- **Bağımlılık:** E01, E09, E10 izinleri; E13-01.
- **Canlı risk:** Yok (mevcut roller değişmez).

### E13-11 · Birim kapsamının açık tanımı (boş = hiçbiri) ve personel listesinde birim filtresi (M13-08)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `kapsam_birim` ve `kapsam_personel`: birim kapsamlı kullanıcının birim kümesi boşsa `false()` → boş liste; tek kayıtta 404. "Tüm birimler" ancak `TUMU` kapsamlı rolle olur (reddedilen `AllUnits` bayrağı açılmaz).
  - Hesap açma/düzenleme: hedef rolün kapsamı `BIRIM_KAPSAMLARI` içindeyse ve birim listesi boşsa 400 "Bu rol için en az bir birim seçilmeli" (`create_user`, `patch_user(role_code)`, `birimleri_yaz` son birimi silme).
  - Geçiş: canlıda birim kapsamlı rolde kullanıcı yok; dolayısıyla "boş listeleri 5 birime çevirme" adımı gerekmez. Migration bunu **yapmaz**; yerine `yonetim.py personel-yukle` kuru çalışma raporu "birimsiz birim kapsamlı kullanıcı" sayısını gösterir (beklenen 0).
  - Personel listesi `kapsam_personel` ile süzülür; birimsiz personel yalnız `TUMU` kapsamına görünür; `personel_notu` yalnız `personel.yaz` sahibine.
  - E08'in personel filtresi (`kapsam_personel`) aynı fonksiyondur; ek birimleri dikkate alır.
- **Dosyalar:** `services/teknik_servis/kapsam.py`, `api/users.py`, `services/teknik_servis/personel.py`, `tests/integration/test_birim_kapsami.py`.
- **Kabul:**
  - Birimi olmayan SERVIS_SEF servis/personel listesinde 0 kayıt görür, tek kayıtta 404.
  - SERVIS_SEF rolüyle birimsiz hesap açma 400.
  - POC şefi personel listesinde yalnız POC üyelerini görür; birimsiz personel görünmez; `personel_notu` anahtarı yok.
- **Öncelik/Efor:** P2 · S
- **Bağımlılık:** E13-06.
- **Canlı risk:** Yok (yalnız yeni kapsamlara uygulanır; `kapsam_musteri` dokunulmaz).

### E13-12 · Güvenlik denetim kaydı: DB seviyesinde değişmezlik, gerçek IP, güvenlik olayları görünümü (M13-06)
- **Canlı:** KISMEN.
  - VAR: giriş/başarısız giriş/MFA/çıkış/kullanıcı/rol/istisna/kilit olayları kaydediliyor (`api/auth.py:53-59, 78, 99-107`, `api/users.py`); parola ve TOTP sırrı maskeleniyor (`services/audit.py:19-23`); görüntüleme ekranı (`api/audit_api.py`, `sistem.denetim`, `action` önek filtresi).
  - YOK: **DB seviyesinde** UPDATE/DELETE engeli. `deploy/db-least-privilege.sql:23` uygulama rolüne tüm tablolarda UPDATE/DELETE veriyor; model yorumu (`models/audit.py:28-30`) ile çelişkili.
  - YANLIŞ (büyük olasılıkla): IP. `client_ip` `request.client.host` döner (`api/deps.py:121-122`). uvicorn yalnız 127.0.0.1'den gelen `X-Forwarded-For`'a güvenir; Caddy host'ta, API ise Docker port eşlemesiyle konteynerde (`docker-compose.yml:32, 36-37`). Konteynerin gördüğü kaynak Docker ağ geçidi (172.x) olacağından başlık yok sayılır.
- **Yaklaşım:**
  - Migration `denetim_degistirilemez`: §2.2.5 tetikleyici. `services/kvkk.py:325` UPDATE'inden önce `await db.execute(text("SET LOCAL denge.kvkk_imha = '1'"))`.
  - `deploy/db-least-privilege.sql`'e `REVOKE UPDATE, DELETE ON audit_logs FROM dengeerp_app; GRANT UPDATE (old_value, new_value) ON audit_logs TO dengeerp_app;` (KVKK imha için sütun düzeyi).
  - Gerçek IP: `docker-compose.yml` uvicorn komutuna `--proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"` (.env'de Docker ağ geçidi, varsayılan `127.0.0.1`). `client_ip` değişmez. `deploy/KURULUM.md`'ye doğrulama adımı: giriş sonrası denetim kaydındaki IP 127.0.0.1/172.x olmamalı.
  - `services/audit.py:guvenlik_olayi(db, action, *, hedef_id, aktor_id, ip, fark)` ince sarmalayıcı: `entity="users"` korunur (eski kayıtlarla aynı sorgu), action önekleri `giris.*`, `parola.*`, `yetki.*`, `birim.*`, `personel.*`, `vekalet.*`.
  - Ön yüz Denetim İzi sayfasına "Güvenlik olayları" hazır filtresi (entity=users|roles).
  - Saklama: denetim kaydı silinmez; otomatik temizleme işi yazılmaz (K-07).
- **Dosyalar:** migration, `services/kvkk.py` (1 satır), `services/audit.py`, `deploy/db-least-privilege.sql`, `docker-compose.yml`, `deploy/KURULUM.md`, `.env.example`, `tests/integration/test_denetim_degismezlik.py`.
- **Kabul:**
  - `UPDATE audit_logs SET action='x'` ve `DELETE FROM audit_logs` uygulama bağlantısında hata verir.
  - KVKK imha testi (mevcut) yeşil kalır.
  - Parola içeren PATCH sonrası kayıtta düz parola yok (mevcut `test_parola_denetim_kaydina_duz_metin_yazilmaz` yeşil).
  - `X-Forwarded-For: 203.0.113.5` ile güvenilen proxy'den gelen girişte kayıt IP'si 203.0.113.5; güvenilmeyen kaynaktan gelen başlık yok sayılır.
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** Yok.
- **Canlı risk:** Orta. Tetikleyici canlıdaki tek UPDATE yolunu (KVKK imha) kırabilir. Önlem: `SET LOCAL` aynı sürümde; `test_kvkk*.py` ve altın kayıt testi koşulur. Yönetim komutları (`yonetim.py:75`) audit satırı silmiyor (doğrulandı: "Silinmezler, KAPATILIRLAR").

### E13-13 · Parola ve giriş yaşam döngüsü (M13-11)
- **Canlı:** KISMEN.
  - VAR: 5 hatada kilit (`services/auth.py:23, 74-98`), yönetici açar; argon2; MFA; var olmayan kullanıcı için kilit satırı açılmaz.
  - YOK: kullanıcının kendi parolasını değiştirdiği uç; sunucuda zorunlu değişim; geçici parola ve süresi; ilk admin parolası zorunlu değişim istemiyor (`seeds/dev.py:110-125`).
  - ZAYIF: zamanlama eşitliği. `authenticate` var olmayan/pasif kullanıcıda argon2 çalıştırmadan döner (`services/auth.py:39-43`) → yanıt süresi kullanıcı adının varlığını sızdırır. Ayrıca yalnız var olan kullanıcı kilitlendiği için 6. denemedeki 423 de varlığı ele verir.
- **Yaklaşım:**
  - `authenticate`: kullanıcı yoksa ya da `is_active AND giris_acik` değilse sabit bir sahte özetle `verify_password` yine çalıştırılır, sonra None. 
  - Kilit politikası canlıdaki gibi **kalıcı, yönetici açar** (kullanıcı kararı, daha sıkı; K-04). Var olmayan kullanıcı için `login_attempts` satırı açılmaması korunur. Sızıntıyı kapatmak için yanıt eşitlenir: hatalı giriş de kilitli hesap da **401 ve aynı metin** döner. Kilit bilgisi yalnız denetim kaydında ve yönetici ekranında görünür; kullanıcı girişte "hesabınız kilitlendiyse yöneticiye başvurun" yönlendirmesini görür.
  - `POST /api/auth/parola {mevcut, yeni}`: mevcut yanlışsa 400 (ve başarısız sayaca yazılır); yeni ≥ 10 karakter, kullanıcı adı/ad içermez; başarılıysa **bu oturum dışındaki** oturumlar düşer, `parola_degismeli=false`, `parola_degisti_at`, `audit("parola.degistir")`.
  - Geçici parola: yönetici `PATCH /api/kullanicilar/{id} {parola_sifirla: true}` → sunucu `secrets.token_urlsafe(9)` üretir, yanıtta **bir kez** döner, `parola_degismeli=true`, `gecici_parola_bitis=now+72h`. Süresi dolmuş geçici parolayla giriş 401. Mevcut `UserPatch.password` (yönetici belirlediği parola) korunur ama `parola_degismeli=true` yapar.
  - `api/deps.py current_user`: `user.parola_degismeli` iken yalnız `/api/auth/me`, `/logout`, `/parola` serbest; diğerleri 403 `{"kod": "PAROLA_DEGISMELI"}` (MFA kalıbı `:31-73`). Ön yüz `ParolaDegistirPage`'e yönlendirir.
  - `ensure_admin` ilk admini `parola_degismeli=True` açar.
  - `son_giris_at` başarılı girişte yazılır (E13-16 için).
- **Dosyalar:** `services/auth.py`, `api/auth.py`, `api/deps.py`, `api/users.py`, `schemas/auth.py`, `seeds/dev.py`, `pages/ParolaDegistirPage.tsx`, `tests/integration/test_parola_yasam_dongusu.py`.
- **Kabul:**
  - `parola_degismeli` hesap `/api/hesaplar`'da 403 `PAROLA_DEGISMELI`, `/api/auth/me`'de 200.
  - Yanlış mevcut parolayla değişim 400; değişim sonrası diğer oturumlar 401, mevcut oturum 200.
  - Geçici parola yanıtta bir kez görünür, denetim kaydında yok; 72 sa sonra 401 (FakeClock).
  - 5 hatadan sonra hesap kilitli (mevcut test), yanıt var olmayan kullanıcıyla aynı kod ve metin.
  - Var olmayan / pasif / yanlış parolalı kullanıcı için ortalama yanıt süresi farkı < %20 (100 deneme, gevşek eşikli test; CI'da bayraklı).
- **Öncelik/Efor:** P2 (zamanlama eşitliği ve sunucu zorunlu değişimi P1 ile aynı sürüm) · M
- **Bağımlılık:** E13-01, E13-02, E13-12.
- **Canlı risk:** Düşük-orta. 423 → 401 değişikliği giriş ekranı metnini etkiler; `test_bes_hatali_denemede_hesap_kilitlenir` beklenen kodu 401'e günceller (davranış korunur: kilitli hesap girmez). Önlem: ön yüz giriş hatası metni "Giriş başarısız; hesabınız kilitlendiyse yöneticiye başvurun" olur.

### E13-14 · Yetki matrisi ve otomatik yetki testleri (M13-14)
- **Canlı:** KISMEN. `tests/unit/test_permissions.py` (katalog değişmezleri), `tests/integration/test_auth_rbac.py` (15 test); testler gerçek PG17 `_test` DB'de, bağlantı ortam değişkeninden. CI hattı yok.
- **Yaklaşım:**
  - `tests/unit/test_permissions.py`'ye:
    - her rol kapsamı `SCOPES` içinde (mevcut test otomatik genişler);
    - `YUKSEK_YETKILI_IZINLER` yalnız `ADMIN` rolünde;
    - `TEKNIK_SERVIS` izin listesi sabit (mobilite rolü değişmesin diye anlık görüntü testi);
    - `VEKALETE_KAPALI ⊆ PERMISSIONS`;
    - her izin en az bir rolde (mevcut).
  - `tests/integration/test_yetki_matrisi.py`: `ROLES × (uç, yöntem, gereken izin)` tablosu parametrik; her rol için demo kullanıcı açılır (`kullanici_ac`), beklenen 200/403 hesaplanır (`set(permissions_of(rol)) ⊇ gereken`). Uç tablosu `app.routes` taranarak `require_permission` bağımlılıklarından türetilir → yeni uç eklenince test kendiliğinden kapsar.
  - E13-01 ve E13-02 kabul senaryoları ayrı testlerde.
  - `Makefile`: `make test-yetki` hedefi. `.github/workflows/test.yml` (postgres:17 servisi, `make test`) dosyası hazırlanır; depo GitHub'a taşındığında devreye girer (K-10). Kaynakta sır yok: parola ve DSN ortam değişkeninden.
- **Dosyalar:** `tests/unit/test_permissions.py`, `tests/integration/test_yetki_matrisi.py`, `Makefile`, `.github/workflows/test.yml`.
- **Kabul:**
  - `make test` tek komutla ayrı test DB'sinde koşar, yetki matrisi ve E13-01/02 senaryoları dahil.
  - Bilerek bir uçtan `require_permission` kaldırıldığında matris testi kırmızı.
  - Kaynakta parola/DSN yok (`grep` testi).
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E13-01, E13-02.
- **Canlı risk:** Yok.

### E13-15 · Süreli vekâlet (yalnız operasyonel izinler, en fazla 30 gün) (M13-04)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `user_delegations` (§2.2.4).
  - `api/deps.py current_user`: kullanıcı çözüldükten sonra `Clock` ile aktif vekâletler tek sorguda yüklenir (`baslangic <= now < bitis AND iptal_at IS NULL`) ve `user._vekalet_izinleri`, `user._vekalet_birimleri` atanır. `User.has()` sırası: istisna (`allow=False` her zaman kazanır) → rol → vekâlet. `etkin_izinler()` ve `kullanici_birimleri()` vekâleti içerir.
  - Süre bitince ek bir iş gerekmez: kontrol her istekte saatle yapılır → sunucu yeniden başlamadan 403.
  - `POST /api/vekaletler {alan_id, izinler, birimler, baslangic, bitis, gerekce}` (`vekalet.ver`):
    - izinler ∩ `VEKALETE_KAPALI` boş olmalı (403);
    - izinler ⊆ verenin izinleri, birimler ⊆ verenin birimleri (403);
    - süre ≤ 30 gün (`ck_ud_sure` + 400);
    - kendine 400.
  - `POST /api/vekaletler/{id}/iptal` (veren veya ADMIN). Verme ve iptal `audit.log("users","vekalet.ver"|"vekalet.iptal")`, alıcının oturumları düşer.
  - Worker'a iş eklenmez (süre kontrolü istek anında); yalnız `GOREVLER`'e günlük "süresi dolan vekâletleri denetim kaydına yaz" işi idempotent eklenir (`uq` gerekmez; `audit` satırı `entity_id=vekalet.id, action='vekalet.sona_erdi'` varsa yazılmaz).
  - Ön yüz: `UsersPage` "Vekâletler" sekmesi; personel kartında "Vekâlet ver".
- **Dosyalar:** `models/rbac.py`, `api/deps.py`, `models/user.py`, `api/vekalet.py` (veya `api/personel.py` içinde), `worker.py`, `tests/integration/test_vekalet.py`.
- **Kabul:**
  - `sistem.*`, `kvkk.yonet`, `maliyet.gor`, `hakedis.onayla/ode`, `tahsilat.yaz` vekâletle verilemez (403).
  - Verenin sahip olmadığı izin 403; 31 gün 400.
  - FakeClock bitiş anını geçince aynı oturumdaki istek 403.
  - Verme/iptal denetimde.
- **Öncelik/Efor:** P3 · M
- **Bağımlılık:** E13-01, E13-02.
- **Canlı risk:** Düşük. `has()` değişikliği tüm uçlara dokunur. Önlem: vekâlet yoksa yol eski davranışla birebir (boş küme); `test_auth_rbac.py` ve yetki matrisi koşar.

### E13-16 · Erişim gözden geçirme listesi (ayrı tablo yok, işaret denetimde) (M13-05)
- **Canlı:** YOK. (Kilitli kullanıcı listesi VAR: `api/users.py:465-468`.)
- **Yaklaşım:**
  - `GET /api/kullanicilar/erisim-gozden-gecirme?kpi=` (`sistem.kullanici`), sayfalı. KPI kodları: `hassas_izin` (`YUKSEK_YETKILI_IZINLER` veya `maliyet.gor` sahibi), `sapma` (istisnası olan), `uzun_girissiz` (`son_giris_at` < now − `erisim_girissiz_gun` (DEFAULTS, 60) ve `giris_acik`), `ayrilmis_hesap_acik` (`ayrilis_tarihi IS NOT NULL AND giris_acik`), `kilitli`.
  - `GET .../ozet` → KPI sayıları; ön yüzde tıklanabilir `KpiKutusu` (E12 bileşeni), tıklanınca aynı `kpi` ile liste; sayı = `X-Toplam-Kayit` (test).
  - `POST .../{user_id}/gozden-gecirildi {not}` → yalnız `audit.log("users","erisim.gozden_gecirildi")`; listede son işaret tarihi denetimden okunur (ayrı tablo yok).
  - `GET .../erisim-gozden-gecirme.xlsx` (`sistem.kullanici` + `rapor.disaaktar`).
- **Dosyalar:** `api/erisim_gozden.py`, `services/settings.py` (`erisim_girissiz_gun`), `UsersPage.tsx` sekme, `tests/integration/test_erisim_gozden.py`.
- **Kabul:**
  - Dört kategori listelenir; KPI sayısı liste toplamına eşit.
  - "Gözden geçirildi" denetim kaydında ve listede tarihle görünür.
  - Excel alınır; `sistem.kullanici` olmayan 403.
- **Öncelik/Efor:** P3 · S
- **Bağımlılık:** E13-12, E13-13 (`son_giris_at`), E13-10.
- **Canlı risk:** Yok.

### E13-17 · Yönetici ilişkisinin kimliğe bağlanması ve "Ekibim" (M13-09)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `users.yonetici_id` (§2.2.1; migration 2'de nullable olarak şimdiden açılır, arayüz P3'te).
  - `personel.py:yonetici_ata`: döngü kontrolü (özyinelemeli CTE; kişi kendisinin ya da astının astı olamaz → 400).
  - Eski `ManagerName` metni E13-08 `ad-esleme` ile (`kaynak_alan='Personnel.ManagerName'`) eşlenir; eşleşmeyenler tahminsiz raporlanır.
  - "Ekibim" görünümü: `GET /api/personel?ekibim=1` → doğrudan bağlı aktif personel, `giris_acik`, `saha_rolu`, açık sayaç var mı (E09). S11 cevapsız; ilk sürüm "şef tüm birimini görür" (kapsam) + "Ekibim" yalnız süzgeçtir, yetki genişletmez.
- **Dosyalar:** `services/teknik_servis/personel.py`, `api/personel.py`, `PersonelPage.tsx`, `tests/integration/test_personel.py`.
- **Kabul:**
  - Döngü 400; eşlenmeyen yönetici adları raporda.
  - "Ekibim" yalnız doğrudan bağlıları gösterir ve kapsam dışı kişiyi göstermez.
- **Öncelik/Efor:** P3 · S
- **Bağımlılık:** E13-05, E13-08, org şeması.
- **Canlı risk:** Yok.

---

## 5. Kararlar (kullanıcıya soru sorulmadı)

- **K-01 Personel = kullanıcı; ayrı `personnel` tablosu yok.** E01 K15, E02 K-01, E08 K1 ile tutarlı. İkinci kimlik kaynağı, eski sistemdeki ad eşleşmesi hatalarının kaynağıydı. Personel alanları `users`'a nullable kolon olarak eklenir; `users` mixin seti (SoftDelete/Actor yok) değiştirilmez.
- **K-02 `sistem.kullanici` yalnız ADMIN'de kalır (S1).** SERVIS_YONETICI ve IK personel kartını (`personel.*`) yönetir ama giriş hesabı açma, rol ve izin verme İT'dedir. Gerekçe: hesap ve yetki verme en yüksek riskli işlem; canlıda bugün de böyle.
- **K-03 `is_active` ve `giris_acik` ayrımı.** `is_active` = kayıt canlı (E08 K2), `giris_acik` = oturum açabilir. M13-D02'nin "personel aktifleştirme hesabı açmaz" kuralı böylece tek tabloda sağlanır; E08'in "rastgele parola" hilesine gerek kalmaz.
- **K-04 Kilit politikası canlıdaki gibi kalıcı (yönetici açar).** Eski kabuldeki "15 dk kilit" daha gevşek; canlı karar bilinçli. Kullanıcı adı sızıntısı yanıt kodunu eşitleyerek (kilitli de 401) giderilir.
- **K-05 Oturum: 4 sa hareketsizlik (canlı kullanıcı kararı) + 12 sa mutlak (S5).** Süreler kod sabiti; ayar ekranından gevşetilemez. Saha/ofis ayrımı yapılmaz (tek kural, daha az hata).
- **K-06 Rol = canlı şablon.** Rol değişikliği roldeki herkese yansır (canlı davranış, oturum düşürmeli). Kişi farkı gerekçeli istisnayla verilir ve rozetle görünür. Eski "şablon değişikliği mevcut hesabı değiştirmez" modeli alınmaz; iki kaynaklı yetki, sapma takibini zorlaştırır.
- **K-07 Denetim kaydı silinmez (S8).** Saklama süresi en az 2 yıl önerisi, hiç silmeme ile karşılanır; otomatik temizleme işi yazılmaz. KVKK imhası yalnız `old_value/new_value` maskeler (tetikleyici izinli yol).
- **K-08 Kapsam dışı birim/kayıt → 404.** Eski kabuldeki "403" canlı kalıba (`kapsam_disinda_mi` → 404, `test_kapsam_guvenligi.py:49-56`) uyarlanır; varlık bilgisi sızdırılmaz. İzin yoksa yine 403.
- **K-09 Kalıcı birim katalogu kod sabiti (`BIRIMLER`), tablo değil.** 5 birim sabit; CHECK kısıtlarında aynı kodlar kullanılır. Reddedilen `AllUnits` bayrağı açılmaz; "tüm birimler" = `TUMU` kapsamı.
- **K-10 CI dosyası hazırlanır, zorunlu kapı değildir.** Depo henüz GitHub'da değil; `make test` yerel kapı, `.github/workflows/test.yml` taşınınca devreye girer.
- **K-11 İşten çıkışta açık sayaç kapatılmaz.** Gerçek bitiş bilinmeden süre üretmek "tahmini süre gerçek süre yerine kullanılmaz, kayıt yoksa eksik" kuralına aykırı (reddedilen M13-03-Kabul3). Bölüm açık kalır, kişi pasif olduğu için yeni bölüm açamaz; uyarı ve görev kartıyla yöneticiye düşer.
- **K-12 Girişsiz personelin rolü `SERVIS_TEKNISYEN`.** `role_id` NOT NULL; giriş kapalıyken rol etkisizdir. Girişi açan yönetici rolü bilinçli seçer (E13-01 kurallarıyla).
- **K-13 Yeni `IK` rolü açılır.** İK'nın teknisyeni kapatabilmesi (M13-12) ve personel kartını yönetmesi için; servis, maliyet ve kullanıcı yönetimi izni yoktur.
- **K-14 Vekâlete kapalı izinler.** `sistem.*`, `kvkk.yonet`, `maliyet.gor`, `hakedis.onayla`, `hakedis.ode`, `tahsilat.yaz`, `vekalet.ver`. Eski "users.*, finance.*, audit.view, *" listesinin canlı karşılığı; `maliyet.gor` rol kümesinin değişmezliği vekâletle delinmesin diye eklendi. Vekâleti yalnız `vekalet.ver` sahibi (SERVIS_YONETICI, ADMIN) verir (S6).
- **K-15 Saha rolü yetki değil, İK olgusudur.** Atama listeleri `saha_rolu`'na, yetki `Role`'e bakar; ünvan hiçbir kurala girmez. Geçişte `saha_rolu` boşsa rol kodundan türetilir ve rozetle gösterilir.
- **K-16 Stajyer ve ortak hesap (S3, S4).** Stajyer `saha_rolu=STAJYER`, girişsiz personel olarak atanabilir; süresini şef girer (E09 "başkası adına kayıt", `servis.planla`). Ortak hesap (atölye tableti/depo) açılmaz: denetim izinde kişi ayırt edilemez.
- **K-17 Teknik servis dışı kullanıcılar (S10).** Canlıdaki mevcut roller (Muhasebe Destek, Depo, Satış…) aynen kullanılır; yeni rol açılmaz.
- **K-18 Gerçek IP için uvicorn güvenilen proxy listesi ortam değişkeninden.** Uygulama kodu (`client_ip`) değişmez; Docker ağ geçidi `.env`'de tanımlanır.
- **K-19 `user_units` migration'ı tektir.** E01-01 ve E13 aynı `servis_birim_uyeligi` migration'ını kullanır; hangisi önce kodlanırsa o açar.

---

## 6. Test planı (özet)

| Test dosyası | Kapsadığı maddeler | Ana senaryolar |
|---|---|---|
| `unit/test_permissions.py` | E13-10, E13-14 | Kapsam geçerliliği, `YUKSEK_YETKILI_IZINLER` yalnız ADMIN'de, `TEKNIK_SERVIS` anlık görüntüsü, `maliyet.gor` kümesi, her izin bir rolde |
| `integration/test_yetki_yukseltme.py` | E13-01 | ADMIN rolü verme, yüksek izin istisnası, alt küme dışı rol, son admin, ADMIN rolü düzenleme, kendi birimi |
| `integration/test_oturum_suresi.py` | E13-02 | 4 sa hareketsizlik, 12 sa mutlak, `giris_acik=false`, birim değişimi |
| `integration/test_personel.py` | E13-03, E13-05, E13-17 | Girişsiz personel, sicil 409, aktifleştirme girişi açmaz, alan gizleme, kapsam 404, döngü |
| `integration/test_birim_kapsami.py` | E13-06, E13-11 | Boş birim = hiçbiri, birimsiz rol 400, çoklu birim, kendi birimi 400 |
| `integration/test_atanabilir_personel.py` | E13-07 | Ek birim, ayrılmış personel, saha rolü/ünvan, alan minimizasyonu, kapsam 404 |
| `integration/test_ad_esleme.py` | E13-08 | Öneri sayıları, onaylı uygulama, idempotent, eşleşmedi |
| `integration/test_personel_cikis.py` | E13-09 | Önizleme, atama kapanışı, açık sayaç korunur, rollback |
| `integration/test_denetim_degismezlik.py` | E13-12 | UPDATE/DELETE reddi, KVKK imha izinli yol, IP |
| `integration/test_parola_yasam_dongusu.py` | E13-13 | Zorunlu değişim 403, mevcut parola, geçici parola 72 sa, yanıt eşitliği |
| `integration/test_yetki_matrisi.py` | E13-14 | Rol × uç parametrik 200/403 |
| `integration/test_vekalet.py` | E13-15 | Kapalı izinler, alt küme, 30 gün, süre dolumu |
| `integration/test_erisim_gozden.py` | E13-16 | KPI = liste toplamı, işaret denetimde, Excel |

Her adım sonunda `make test` (altın kayıt 932 iş / 552.825,00 TL dahil), `test_migration_zinciri`, `ruff`, `npm run build`. Yeni tablolardan `user_units` ve `personnel_name_maps` conftest `_TRUNCATE` listesine açıkça eklenir.

## 7. Uygulama sırası

1. Migration 1-2 + `permissions.py` sabitleri + `services/yetki.py` + E13-01 + E13-02 (aynı sürüm, P1).
2. E13-05, E13-06, E13-03, E13-04 (personel kartı ve birim yönetimi) → E01 servis iş emri çekirdeği başlayabilir.
3. E13-07 (E02-04 ile birlikte), E13-08 (göç öncesi).
4. E13-12, E13-13 (güvenlik sıkılaştırma; zamanlama eşitliği ve zorunlu değişim 1. sürüme çekilebilir), E13-14.
5. E13-09 (E01 atama + E09 sayaç hazır olunca), E13-10, E13-11.
6. P3: E13-15, E13-16, E13-17.

## 8. Gözlemler (değiştirilmedi)

- `deploy/db-least-privilege.sql:23` uygulama rolüne `audit_logs` üzerinde UPDATE/DELETE veriyor; `models/audit.py:28-30` yorumu "uygulama kullanıcısından bu haklar alınır" diyor. Belge ile kurulum betiği çelişkili (E13-12 giderir).
- `api/users.py:209-258` `ADMIN` rolünün izinlerinin boşaltılmasına izin veriyor; tüm yöneticilerin kilitlenmesine yol açabilir (E13-01 giderir). Kurtarma yolu `yonetim.py` komutlarıdır.
- `services/auth.py:39-43` zamanlama farkı ve 423 yanıtı kullanıcı adı varlığını sızdırıyor (E13-13 giderir).
- uvicorn güvenilen proxy ayarı Docker düzeninde gerçek IP'yi kaybettiriyor olabilir; üretimde denetim kaydı IP'leri doğrulanmalı (E13-12).
