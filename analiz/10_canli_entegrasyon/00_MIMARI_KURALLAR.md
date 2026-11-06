# Denge Mobilite ERP — Mimari Kurallar Rehberi (Teknik Servis Entegrasyonu)

> Tarih: 2026-10-21 · Kaynak: `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp` (yalnız OKUNDU, hiçbir dosya değiştirilmedi)
> Hedef okuyucu: teknik servis modüllerini tasarlayacak ve kodlayacak ajanlar.
> Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köklerine göredir.
> Bu belge bağlayıcıdır: burada "KURAL" diye yazılan her madde, mevcut kodun gerçekte yaptığı şeydir. Yeni kod bundan sapmaz; sapma gerekiyorsa gerekçesi tasarım belgesine yazılır.

---

## 0. En kritik 12 kural (özet)

1. **Katman sırası değişmez:** `models/` (ORM + kısıtlar) → `services/` (iş kuralı, `flush`, commit YOK) → `api/` (Pydantic In/Out, izin, kapsam, denetim izi, `commit`). Router `main.py`'ye elle eklenir.
2. **Her ana tablo** `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin` (+ göç edilecekse `SourceMixin`) alır (`models/mixins.py:23-113`). Örnek: `models/workorder.py:77-79`, `models/service.py:57`.
3. **Durum/enum alanı = `String` + adlandırılmış `CheckConstraint`**, Python tarafında aynı değerlerin tuple'ı (`models/workorder.py:49-59, 84-91`). Postgres ENUM tipi kullanılmaz.
4. **Kısıt adı önekleri zorunlu:** `uq_`, `fk_`, `ck_`, `ex_`, `ix_`. `main.py:71-77` kullanıcı mesajını ADIN İLK 3 HARFİNDEN seçer; öneksiz kısıt kullanıcıya anlamsız mesaj döndürür.
5. **Durum geçişi yalnız `services/statemachine.py` makinesiyle:** API önce `MAKINE.dogrula(onceki, hedef)` çağırır, çıktıda `sonraki_durumlar` döner (`api/rma.py:103, 211`). Yeni makine `MAKINELER`'e eklenir (`statemachine.py:189-196`) ki meta-test (`tests/unit/test_statemachine.py:8`) onu da sınasın.
6. **İzin kodu Türkçe `modul.gor / modul.yaz / modul.<eylem>`**, tek kaynak `permissions.py:14-77`; her uç `require_permission(...)` ile korunur (`api/deps.py:79-97`); uç dosyasında `Okuyucu/Yazici/Onaylayici` takma adları tanımlanır (`api/workorders.py:33-35`).
7. **Kapsam iki yerde uygulanır:** liste uçlarında `kapsam_musteri(stmt, user, sutun)` (`services/accounts.py:29-44`), tek kayıt yazma/okuma uçlarında `kapsam_disinda_mi(...)` → 404 (`services/accounts.py:47-61`). 404 dönüp yazmaya izin vermek açıktır (`tests/integration/test_kapsam_guvenligi.py:49-56`).
8. **Denetim izi aynı transaction içinde, `commit`'ten ÖNCE** (`services/audit.py:26-52`; örnek `api/workorders.py:247-261`). Alan değişikliği için `audit.log_change` (`api/workorders.py:484`). Kişisel veri içeren kayıtta `is_personal_data=True` (`api/accounts.py:423`).
9. **Fiyat/maliyet varsayılan GİZLİ:** `sees_cost(user)` (`api/deps.py:103-105`) false ise alan YANITTA HİÇ YOK (`api/reports.py:41-55`). Bu kural bir unit testle kilitli (`tests/unit/test_permissions.py:21-26`).
10. **Saat `Clock` üzerinden** (`api/deps.py:22-27`, `clock.py`); uygulama kodunda `datetime.now()` yok (`worker.py:26`). Testler `FakeClock` ile zamanı ilerletir (`tests/conftest.py:157-167`).
11. **Liste uçları `sayfala()` kullanır** — toplam `X-Toplam-Kayit` başlığında, sıralamaya PK kırılması otomatik (`api/deps.py:142-190`); ön yüz `api.getSayfa` (`frontend/src/api/client.ts:63-81`).
12. **Hak ediş zincirine DOKUNULMAZ:** `work_orders` / `work_order_items` / `settlements` (bkz. §5). Teknik servis işleri bu tablolara yazılmaz.

---

## 1. Katmanlar

### 1.1 `models/` — ORM ve kısıtlar

| Öğe | Kural | Kanıt |
|---|---|---|
| Taban | `from app.db import Base` (`AsyncAttrs, DeclarativeBase`) | `db.py:14` |
| PK | `PkMixin`: `BigInteger Identity()`; dışa açık kaynak ayrıca jeton taşır | `models/mixins.py:89-94` |
| Zaman damgası | `TimestampMixin`: `created_at/updated_at` DB tarafında `now()` | `mixins.py:23-34` |
| Aktör | `ActorMixin`: `created_by/updated_by` → `users.id ON DELETE SET NULL`; NULL = sistem/worker | `mixins.py:37-49` |
| Yumuşak silme | `SoftDeleteMixin`: `is_deleted, deleted_at, deleted_by`. Sorgular `X.is_deleted.is_(False)` filtresini ELLE yazar | `mixins.py:52-67`, `api/workorders.py:283` |
| İyimser kilit | `VersionedMixin`: `version_id_col`; çakışma `StaleDataError` → 409 | `mixins.py:70-86`, `main.py:115-129` |
| Göç kimliği | `SourceMixin` + tabloda `UniqueConstraint("source_system","source_ref", name="uq_<tablo>_kaynak")` | `mixins.py:97-113`, `models/workorder.py:83` |
| Kayıt | Yeni model dosyası `models/__init__.py`'ye import + `__all__` eklenir; yoksa Alembic tabloyu görmez | `models/__init__.py:1-2, 59-118` |
| Enum | `XXX_DURUMLARI = (...)` tuple + `CheckConstraint("status IN (...)", name="ck_<kısa>_durum")` | `models/service.py:40-48, 61-64` |
| Koşullu zorunluluk | CHECK ile şemada: ör. "ödenmeyecekse neden zorunlu" | `models/workorder.py:159-162` |
| Kimlik kuralı şemada | Bileşik FK + CHECK (IMEI/SERI_NO/YOK) | `models/device.py:79-98` |
| Tarihli kayıt | `_ARALIK = literal_column("tstzrange(valid_from, valid_to, '[)')")` + `ExcludeConstraint(..., using="gist")`, açık dönem için kısmi tekil indeks, `ck_..._aralik` | `models/workorder.py:74, 213-235`; `models/stock.py:61, 88-97` |
| Aralık | DAİMA yarı açık `'[)'` (aynı gün sök-tak kabul edilsin) | `README.md:49` |
| Tarihsiz satır | Uydurma tarih yazılmaz; gerekiyorsa `valid_from` NULL + EXCLUDE `WHERE valid_from IS NOT NULL` + `ck_..._tarihsiz_acik` | `models/workorder.py:213-235, 262-266` |
| Polimorfik bağ | `entity` (tablo adı) + `entity_id`; yarım bağ CHECK ile engellenir | `models/gorev.py:147-151, 168-170`; `models/attachment.py:72-73` |
| Türetilmiş alan | `current_*` gibi denormalize alanlar yalnız sorgu kolaylığı; doğruluk kaynağı tarihli tablo, gece worker uzlaştırır | `models/device.py:125-130`, `worker.py:61-76` |
| Adlandırma | Tablo/kolon İngilizce (`work_orders`, `rma_cases`, `settlement_period`); sabitler, servis fonksiyonları, docstring ve mesajlar Türkçe. Yeni tablolarda da bu karışım korunur | tüm `models/` |
| Docstring | Her modelin başında "NEDEN böyle" açıklaması (gerçek veri/karar gerekçesi) zorunlu üslup | `models/workorder.py:1-16` |

### 1.2 `schemas/` ve Pydantic

- `app/schemas/` yalnız 4 modülde var (`accounts, auth, catalog, devices`). **Fiili kalıp:** In/Out sınıfları ilgili `api/*.py` içinde tanımlanır (`api/workorders.py:38-151`, `api/rma.py:24-84`).
- Adlandırma: `XxxIn`, `XxxPatch`, `XxxOut`; Out'ta `model_config = {"from_attributes": True}` (`api/workorders.py:50, 73`).
- Doğrulama Pydantic `Field` ile: `max_length`, `ge=0`, `pattern` (`api/workorders.py:124-151, 390-391`).
- Zenginleştirilmiş çıktı `_cikti(db, kayit)` yardımcı fonksiyonuyla üretilir (`api/workorders.py:93-121`, `api/rma.py:93-105`).
- PATCH'te iyimser kilit: yanıt `version` döner, istemci geri yollar, uyuşmazsa 409 (`api/accounts.py:434-440`; ön yüz `pages/HesaplarPage.tsx:164`).

### 1.3 `services/` — iş kuralı

- Girdi: `@dataclass XxxGirdisi` (`services/workorders.py:61-89`).
- Hata: modüle özgü `class XxxHatasi(ValueError)` (`services/workorders.py:57`, `services/rma.py:39`); API bunu 409/400'e çevirir (`api/workorders.py:242-245`).
- Servis `db.flush()` yapar, **`commit` yapmaz**; transaction sınırı API'dedir (`services/workorders.py:288-295`, `api/workorders.py:261`).
- Servis `clock: Clock` parametresi alır (`services/workorders.py:245-251`).
- Cihaz durumu yalnız `cihaz_svc.durum_degistir` / `CIHAZ.yol` ile yürütülür; ara durumlar geçmişe yazılır (`services/workorders.py:220-242`, `services/devices.py:46-66`).
- Alt paket emsali: `services/imports/` (çok dosyalı alan). Teknik servis için `services/teknik_servis/` bu emsale uyar.
- Belge numarası: bugün `count()+1` (`services/workorders.py:101-103`) ve `max(id)+1` (`services/rma.py:70-72`) — eşzamanlılıkta çakışır, `uq_` kısıtı 409'a çevirir. **Yeni modülde** PostgreSQL `SEQUENCE` ya da yıl bazlı sayaç tablosu + `uq_` kullan; mevcutları değiştirme.

### 1.4 `api/` — uçlar

| Öğe | Kural | Kanıt |
|---|---|---|
| Router | `APIRouter(prefix="/api/<türkçe-kebab>", tags=[...])` | `api/workorders.py:31`, `api/rma.py:18` |
| Bağımlılıklar | `DbDep`, `ClockDep`, `CurrentUser` | `api/deps.py:26-27, 76` |
| İzin | `Annotated[User, Depends(require_permission("x.y"))]`; varsayılan RED; birden çok kod = hepsi gerekli | `api/deps.py:79-97` |
| İzin sahip kayda göre değişiyorsa | gövdede `_izin(user, kod)` | `api/attachments.py:117-121` |
| CSRF | Mutasyonlarda `X-Requested-With: fetch` başlığı şart | `api/deps.py:56-57` |
| MFA kapısı | `current_user` içinde; yeni uçlar otomatik korunur | `api/deps.py:64-72` |
| Liste | `stmt` kur → `kapsam_musteri` → filtreler → `sayfala(db, response, stmt, limit, offset)`; `limit le=200` | `api/workorders.py:269-297` |
| Tek kayıt | `db.get` → `is_deleted` kontrol → 404; kapsam kontrolü `db.get`'ten SONRA ama yazmadan ÖNCE | `api/workorders.py:352-354`, `services/accounts.py:47-61` |
| Kilitli kaynağı koru | Ödenmiş/kilitli bağımlı satır varsa 409 + Türkçe gerekçe | `api/workorders.py:416-427, 466-476` |
| Hata kodları | Kural ihlali 409, girdi hatası 400, yetki 403, yok/kapsam dışı 404, DB veri hatası 422 | `main.py:131-161` |
| Maliyet | `sees_cost(user)`; görmeyen için alan çıkarılır, 0 yazılmaz | `api/reports.py:41-55`, `api/sims.py:160` |
| Dönem parametresi | `donem_dogrula()` (YYYY-AA) | `api/deps.py:125-139` |

### 1.5 `main.py`

- Router kaydı ELLE: `app.include_router(x_api.router)` (`main.py:182-209`); import bloğu `main.py:11-36`.
- Global hata eşleyiciler: `StaleDataError→409` (115-129), `IntegrityError→409` kısıt önekiyle (131-148), `DataError→422` (150-161).
- Güvenlik başlıkları + CSP (`main.py:163-180`); prod'da `/api/docs` kapalı (96-101).

### 1.6 `worker.py` — arka plan

- **Gerçek durum:** periyodik görev koşucusu; `FOR UPDATE SKIP LOCKED` iş kuyruğu YOK, D10 ile ertelendi (`worker.py:6-9`). Kodda tek satır kilidi `api/imports.py:202` (`with_for_update=True`).
- Görev = `Gorev(ad, periyot, calistir)`; imza `async def f(db, clock) -> str` (özet metni döner) (`worker.py:48-55, 120-125`).
- Her tur kendi oturumu + `commit`, hatada yutup loglar, artan aralıkla yeniden dener (`worker.py:131-181`).
- Tek kopya (`replicas: 1`), CPU-bağlı iş `asyncio.to_thread` (`worker.py:13-24`).
- **Teknik servis için:** "Bakım periyodu gelen sözleşmelerden PB iş emri üret" görevi `GOREVLER`'e eklenir; **idempotent** olmalı (sözleşme kalemi + dönem başına `uq_` kısıtı) çünkü yeniden deneme aynı turu tekrar koşar. Birden çok süreç ihtimali doğarsa `select(...).with_for_update(skip_locked=True)` kullanılır.

### 1.7 `services/statemachine.py`

- `StateMachine(ad, gecisler, baslangiclar)`; `dogrula`, `sonraki`, `yol` (`statemachine.py:27-83`).
- Makineler: CIHAZ, HAT, SIPARIS, ABONELIK, RMA, SATINALMA (+ hak ediş `DOKUM` `api/settlements.py:50-51`).
- **İş emri (mobilite) için makine YOK**; onay doğrudan atama (`api/workorders.py:355-366`) ve kayıt doğrudan `TAMAMLANDI` doğar (`services/workorders.py:274`). Bu canlı davranıştır — **dokunma**, ama yeni servis iş emri bu sapmayı KOPYALAMAZ: `SERVIS_IS_EMRI` makinesi tanımlanır.
- Disiplin: "durum alanına doğrudan atama yok" (`statemachine.py:6-9`). RMA servisi atamayı yapıyor (`services/rma.py:134`) ama API önce `RMA.dogrula` çağırıyor (`api/rma.py:211`) — yeni kodda doğrulama servis içinde de yapılmalı.

### 1.8 `services/audit.py`

- `log(db, entity, action, *, entity_id, old_value, new_value, user_id, ip, is_personal_data)` (26-52); `log_change(db, obj, action, ...)` yalnız gerçekten değişen kolonları yazar (55-92); hassas alanlar maskelenir (19-23).
- `entity` = tablo adı, `action` = Türkçe fiil (`olustur`, `onayla`, `hakedis.donem.degistir`) (`api/workorders.py:247-260, 369-377, 432-441`).

### 1.9 Ekler (`models/attachment.py`, `api/attachments.py`, `services/storage.py`)

- Tek tablo, polimorfik; izin sahip kayda göre `SAHIP_IZNI` (`api/attachments.py:41-52`).
- Yeni varlık eklemek için 4 yer: `EK_SAHIPLERI` (`models/attachment.py:31-42`), `EK_TURLERI` (`:46-62`, ör. `SERVIS_FORMU`, `BAKIM_FORMU`, `MUSTERI_IMZASI`), `SAHIP_IZNI` (`api/attachments.py:41-52`), `_kapsam` (`api/attachments.py:91-114`) — **_kapsam bugün yalnız `accounts` için çalışıyor**; servis kayıtları için müşteri + birim kapsamı buraya eklenmeli, yoksa ek kimliği sıralı olduğu için arşiv taranabilir (gerekçe `api/attachments.py:94-97`).
- Depolama `storage.py` arkasında; 25 MB sınırı (`storage.py:88`), MIME doğrulama `mime_coz` (`:70`), içerik özeti `sha256`; yetim dosya temizliği worker'da (`worker.py:105-117`).

### 1.10 PDF / belgeler

- Jinja2 şablonları `app/templates/` (`services/pdf.py:21-25`); `pdf_uret_async` (`:53`) WeasyPrint'i thread'de koşar; açılışta ısıtılır (`main.py:43-67`).
- Bağlam fonksiyonları `services/belgeler.py` (`dokum_baglami:31`, `teklif_baglami:147`, `firma_bilgisi:119` ayarlardan künye).
- Servis formu/bakım raporu PDF'i: `belgeler.servis_formu_baglami` + `templates/servis_formu.html` aynı kalıpla.

### 1.11 Dışa aktarım / raporlar

- `services/export.py`: `satirlari_xlsx_async` (`:45`), formül enjeksiyonuna karşı metne çevirme (`:26`); `api/reports.py:_xlsx` (`:33`).
- İzinler: `rapor.gor` (ekran), `rapor.disaaktar` (Excel) (`api/reports.py:29-30`).
- Rapor sorguları `services/reports.py` içinde; maliyet kolonu `_maliyet_gizle` ile.
- Gözlem (dokunma, kaydet): `services/reports.py:81` `"DEGISTI"` değeri `KALEM_EYLEMLERI`'nde yok (`models/workorder.py:61` → `DEGISTIRILDI`); panelde değişim sayılmıyor olabilir.

### 1.12 Ayarlar (`services/settings.py`)

- `DEFAULTS` sözlüğü = düzenlenebilir anahtarların beyaz listesi (`:33-93`); okuma `await ayar_svc.get(db, "anahtar")` (`:109`); hassas anahtar şifreli (`:26-31`).
- Teknik servis parametreleri (SLA saatleri, PB öncesi üretim günü, eksik süre eşiği vb.) buraya eklenir; koda sabit gömülmez.

### 1.13 Uyarılar (`services/uyarilar.py`)

- Saklanmaz, HESAPLANIR; izne tabidir (`uyarilar.py:9-17`); `Uyari(kod, baslik, adet, yol, onem, aciklama)` (`:28-35`); `topla()` içine `if user.has("servis.gor"):` bloğu eklenir (kalıp `:55-100`).
- Teknik servis uyarıları: "süre kaydı eksik iş", "SLA aşımı", "bakımı gecikmiş sözleşme", "dönüşü geciken kiralama". Birim kapsamı uyarı sayısına da uygulanmalı (sayı = sızıntı).

### 1.14 Görev panosu ve arama

- Karta bağlanabilir tipler tek yerde: `services/gorevler.py:47-57` (`KayitTipi(kod, ad, model, alanlar, yol)`); servis iş emri, sözleşme, kiralama eklenir. Görev uçlarında kapsam bilerek uygulanmaz (`api/gorevler.py:6-9`).

### 1.15 RBAC (`permissions.py`, `models/rbac.py`, `seeds/dev.py`)

- İzin kataloğu `PERMISSIONS` (`permissions.py:14-77`), kapsam sabitleri (`:80-82`), roller (`:89-248`), `YONETIM` tüm `.gor` izinlerini otomatik alır (`:84, 247`).
- DB rolleri düzenlenebilir; `ozellestirildi=True` rollere seed yeni izin İNDİRMEZ, log'a uyarı yazar (`models/rbac.py:64-69`, `seeds/dev.py:44-79`). Kullanıcı bazlı istisna `UserPermission(allow, gerekce)` (`models/rbac.py:29-52`).
- Unit testler: her izin en az bir role atanmış olmalı (`tests/unit/test_permissions.py:43-46`), maliyet görenler kümesi sabit (`:21-26`), YONETIM yazma izni taşımaz (`:35-40`).
- Mevcut `TEKNIK_SERVIS` rolü MOBİLİTE montaj/onay rolüdür (`permissions.py:162-183`; `isemri.onayla` içerir → hak edişe giriş). Yeni teknik servis rolleri AYRI kodla açılmalı (ör. `SERVIS_YONETICI`, `SERVIS_SEF`, `SERVIS_TEKNISYEN`, `ATOLYE`); mevcut rol yeniden anlamlandırılmaz.

---

## 2. Alembic kuralları

| Konu | Kural | Kanıt |
|---|---|---|
| Üretim | `make makemigration m="aciklama"` → `alembic revision --autogenerate` | `Makefile:62-63` |
| Dosya adı | `<rev>_<slug>.py` (`file_template = %%(rev)s_%%(slug)s`); mesaj küçük harf ASCII Türkçe (`gorev_panosu`, `rma_satinalma_ithalat_btk`) | `alembic.ini:4`, `alembic/versions/` |
| Docstring | Migration başında NEDEN + bedeli açıkça yazılır | `versions/8c41d2b7e903_...py:1-31` |
| Uzantılar | `btree_gist`, `pg_trgm` env.py'de her koşuda kurulur; yeni uzantı gerekiyorsa oraya | `alembic/env.py:32-39` |
| Model kaydı | `env.py` `import app.models` ile görür → yeni model `models/__init__.py`'de olmalı | `env.py:7` |
| EXCLUDE (yeni tablo) | autogenerate şu biçimi üretir, korunur: `postgresql.ExcludeConstraint((sa.column('device_id'), '='), (sa.literal_column("tstzrange(valid_from, valid_to, '[)')"), '&&'), using='gist', name='ex_...')` | `versions/28bd1a023e28_...py:175` |
| EXCLUDE (var olan tabloda değişiklik / kısmi) | `op.execute("ALTER TABLE ... ADD CONSTRAINT ex_... EXCLUDE USING gist (...) WHERE (...)")`; düşürme de ham SQL (Alembic'te `type_="exclude"` yok) | `versions/8c41d2b7e903_...py:54-60, 75-79` |
| CHECK | Yeni tabloda `sa.CheckConstraint(..., name='ck_...')`; var olan tabloya `op.create_check_constraint(...)`. **Autogenerate CHECK değişikliğini yakalamaz** — enum tuple'ı genişlediğinde migration ELLE yazılır (drop + create) | `versions/8c41...py:61-65` |
| Kısmi indeks | `postgresql_where=text("valid_to IS NULL")` | `models/workorder.py:225-230` |
| Downgrade | ZORUNLU ve çalışır olmalı; head→base→head testi koşar, EXCLUDE sayısı korunmalı, FK sırası elle düzeltilir | `tests/migration/test_migration_zinciri.py:1-11, 61-102` |
| Tek head | İki head testi kırar | `test_migration_zinciri.py:105-110` |
| Güncel head | `b30e012dd879` (gorev_karti_coklu_ilgili_kisi_ve_etiket) — yeni zincir buna bağlanır; kodlama başlarken `alembic heads` ile yeniden doğrula | `versions/b30e012dd879_...py:29-30` |
| Veri göçü | Uydurulmuş tarih/kimlik yazılmaz; downgrade'de kaybı görünür kıl | `versions/8c41...py:68-72`, `README.md:52` |
| Canlı tabloya kolon | Yalnız `nullable=True` (veya server_default'lu) kolon; mevcut CHECK/EXCLUDE'a dokunan migration teknik servis kapsamında YASAK | — |

---

## 3. Ön yüz kalıpları (React 19 + AntD 6 + TanStack Query 5)

| Öğe | Kural | Kanıt |
|---|---|---|
| Yönlendirme | Rotalar `KorumaliUygulama` içindeki `<Route element={<AppLayout/>}>` altına eklenir; Türkçe kebab yol (`/is-emirleri`, `/hesaplar/:id`) | `main.tsx:57-98` |
| Menü | `MENU` dizisine `{key, label, icon, izin}`; izin tek kod ya da "herhangi biri" listesi; kullanıcıda yoksa kalem görünmez (yalnız görsel) | `components/AppLayout.tsx:45-120` |
| Yetki | `const { yetkili } = useAuth(); yetkili("servis.yaz")` — sekme/buton gizleme | `auth/AuthContext.tsx:46-49`, `pages/IsEmirleriPage.tsx:173-181` |
| API istemcisi | `api.get/post/patch/put/delete`, sayfalı liste `api.getSayfa<T>()`; `ApiError.status`, `cakisma` (409) | `api/client.ts:12-24, 63-93` |
| Modül API dosyası | Büyük modülde `src/api/<modul>.ts` (tipler + fonksiyonlar) | `api/gorevler.ts` |
| Liste sayfası | `useQuery({queryKey: ["anahtar", filtre..., sayfa]})` + `URLSearchParams` (`limit`, `offset`) + `Table` sunucu sayfalaması (`current/pageSize/total/onChange/showTotal`) | `pages/IsEmirleriPage.tsx:66-107` |
| Filtre | Kart `extra` alanında `Input.Search`/`Select`; filtre değişince sayfa 1 | `pages/IsEmirleriPage.tsx:155-166` |
| Detay | Satır tıklama → `Drawer` (`size={680}`), içinde `Card size="small"` blokları, `Timeline` geçmiş | `pages/IsEmirleriPage.tsx:108, 185-280` |
| Form/pencere | `KartPenceresi` kalıbı: TEK form hem yeni hem düzenleme; `useMutation` → `message.success/error` → `invalidateQueries` → kapat | `components/KartPenceresi.tsx:30-131` |
| Ek dosya | `<EkYukleyici entity="..." entityId={id} kind="..." baslik="..." yazabilir={yetkili(...)} />` | `components/EkYukleyici.tsx:20-60` |
| Görev bağlama | `KayitGorevleri` bileşeni | `components/KayitGorevleri.tsx:18` |
| İyimser kilit | Düzenlemede `version` geri gönderilir; 409'da "yenileyin" mesajı | `pages/HesaplarPage.tsx:164` |
| Tarih | `dayjs` + `dayjs.locale("tr")` (`main.tsx:40`); gösterim `DD.MM.YYYY`, gönderim ISO (`YYYY-MM-DD`) | `pages/IsEmirleriPage.tsx:116` |
| Para | `tl()` biçimleyici `toLocaleString("tr-TR")` + `₺`; `className="tutar"`, kimlikler `className="mono"` | `pages/IsEmirleriPage.tsx:51-52, 110-148` |
| Metin | Tüm etiket, mesaj, boş durum Türkçe; enum gösteriminde `replaceAll("_"," ")` | `pages/IsEmirleriPage.tsx:124` |
| Dar ekran | 375 px'te kullanılabilirlik bilinçli korunuyor | `components/AppLayout.tsx:133-137` |
| Test | Ön yüz otomatik testi yok; `npm run build` (tsc) + `oxlint` kapısı | `package.json` |

---

## 4. Test kalıpları

| Öğe | Kural | Kanıt |
|---|---|---|
| Altyapı | Gerçek PostgreSQL 17, ayrı `<db>_test`; şema `alembic upgrade head` ile (her koşu zinciri doğrular) | `tests/conftest.py:1-17, 47-90` |
| Temizlik | Her testte `TRUNCATE ... RESTART IDENTITY CASCADE`; **yeni tablo, listedeki bir tabloya FK ile bağlı değilse `_TRUNCATE`'e eklenmeli** | `tests/conftest.py:35-44, 112-118` |
| Ortam | `FILES_DIR` geçici dizin, `MFA_ZORUNLU=false` | `conftest.py:93-109` |
| Fixture'lar | `db`, `seeded` (izin+rol senkronu), `client` (httpx ASGI, CSRF başlığı, `client.clock` FakeClock), `kullanici_ac(username, role_code)`, `urun_ac`, `cihaz_ac`, `hat_ac` | `conftest.py:126-250` |
| İşaret | `pytestmark = pytest.mark.integration`; `asyncio_mode = "auto"` | `tests/integration/test_auth_rbac.py:8`, `pyproject.toml:34-38` |
| Klasör | `tests/unit` (DB'siz: izin kataloğu, durum makinesi), `tests/integration` (uçlar üzerinden), `tests/migration` (zincir, altın kayıt) | `tests/` |
| Adlandırma | `test_<türkçe_davranış>`; docstring hatanın gerçek hikâyesini anlatır | `test_kapsam_guvenligi.py:1-12` |
| Giriş | `await client.post("/api/auth/login", json={...})` yardımcı `_giris` | `test_auth_rbac.py:11-12` |
| RBAC testi | Her yeni uç için: yetkisiz rol 403, yetkili 200/201 | `test_auth_rbac.py` |
| Kapsam testi | Kapsam dışı yazma 404 **VE** veri değişmemiş (`db.refresh` ile kontrol) | `test_kapsam_guvenligi.py:49-56` |
| Maliyet testi | Yetkisiz kullanıcının yanıtında fiyat/maliyet anahtarı YOK | `test_permissions.py:21-26`, `test_raporlar.py` |
| Durum makinesi | Yeni makine `MAKINELER`'e girince parametrik meta-test otomatik sınar | `tests/unit/test_statemachine.py:8-33` |
| Hak ediş koruması | `tests/migration/test_altin_kayit.py` (932 iş / 552.825,00 TL) teknik servis değişikliklerinden sonra da yeşil kalmalı | `README.md:93-111` |

---

## 5. Mevcut modüllerin teknik servis açısından sınıflandırması

| Modül | Dosyalar | Teknik servis için | Gerekçe / not |
|---|---|---|---|
| **Hesap** (müşteri/bayi/montaj noktası/tedarikçi) | `models/account.py:53-130` | **Doğrudan kullan** — servis müşterisi = `Account(is_musteri=True)` | Bayrak seti; yeni "müşteri" tablosu YASAK. `title_key` ORM olayıyla dolar (`:193-196`); mükerrer aday `services/accounts.py:84-106` |
| Kişi (`contacts`) | `account.py:163-174` | **Doğrudan kullan** — irtibat | Kişisel veri: denetimde `is_personal_data=True` |
| Adres (`addresses`) | `account.py:177-187` | **Genişlet** → servis lokasyonu/tesis (site) | Yalnız `belgeler.py`'de okunuyor; nullable kolon eklemek (`site_kodu`, `bolge`, `is_active`, `birincil_kisi_id` ...) risksiz. Ayrı "lokasyon" tablosu açılmaz |
| Ürün kataloğu | `models/catalog.py` | **Doğrudan kullan** — marka/model, yedek parça, hizmet kalemi | `identity_kind` (IMEI/SERI_NO/YOK) kuralı korunur |
| **Cihaz** | `models/device.py:72-158`, `services/devices.py` | **Yalnız Mobilite/Araç Takip birimlerinde doğrudan referans**; güvenlik/haberleşme/POC ekipmanı için `devices`'a KAYIT AÇMA | `devices` stok yaşam döngüsü (STOKTA→...→AKTIF), global `uq_devices_seri` (`:93-98`), stok değeri raporu ve gece uzlaştırması taşır. Müşteri malı kurulu ekipmanı (seri no metin, üreticiler arası çakışabilir) buraya sokmak hem tekil indeksi hem stok raporlarını bozar. Kurulu ekipman ayrı tabloda, isteğe bağlı `device_id` FK ile |
| Cihaz durum makinesi | `statemachine.py:92-111` | **Dokunma** | Tüm mobilite akışı buna bağlı |
| Cihaz–araç geçmişi | `models/workorder.py:203-278`, `services/assignments.py` | **Dokunma** (yalnız oku) | EXCLUDE + kısmi tekil indeks |
| **İş emri (mobilite ziyareti)** | `models/workorder.py:77-200`, `services/workorders.py`, `api/workorders.py` | **DOKUNULMAZ** | `settlements.donem_kapat` iş emrini yalnız `status IN (TAMAMLANDI, ONAYLANDI)` + `assigned_type='MONTAJ_NOKTASI'` ile süzüyor (`services/settlements.py:168-179`); `uyarilar` TÜM `work_order_items` `KARAR_BEKLIYOR` kalemlerini sayıyor (`services/uyarilar.py:131-146`); panel montaj sayısı kalemlerden (`services/reports.py:73-83`). Tip CHECK'i (`workorder.py:84-87`) değiştirmek ve servis işlerini bu tablolara yazmak hak ediş, uyarı ve panel sayılarını kirletir |
| Hak ediş / tarife / ödeme | `models/settlement.py`, `services/settlements.py`, `api/settlements.py` | **DOKUNULMAZ** | Altın kayıt testiyle kilitli (`README.md:93-119`); kapanmış dönem değişmez |
| **RMA** | `models/service.py:57-113`, `services/rma.py`, `api/rma.py` | **Doğrudan kullan + bağla** | Atölye kaydı Denge'nin sattığı cihazın garanti/servis sürecine dönüşürse RMA açılır; servis iş emrinde nullable `rma_case_id`. Garanti kararı dondurulur (`service.py:1-11`). RMA tablosu atölye kaydının yerine geçmez (cihaz zorunlu, `device_id NOT NULL RESTRICT` `:79-81`) |
| Stok — seri takipli | `models/stock.py:64-200`, `services/stock.py` | **Doğrudan kullan** (Mobilite cihazları, `TEKNISYEN` konumu, `SERVIS_GONDERIM/SERVIS_DONUS` transfer tipleri `:43-58`) | Tarihli konum EXCLUDE'u korunur |
| Stok — serisiz (`stock_movements`) | `models/stock.py:205-236` | **Genişlet** — yedek parça tüketimi için nullable `service_order_id` FK ya da `document_no` = servis iş emri no | Eldeki adet = hareket toplamı; `qty<>0` CHECK |
| Depo (`warehouses`) | `models/stock.py:64-77` | **Doğrudan kullan** — kiralama depoları 1–3, teknisyen araç stoğu (`user_id`) | — |
| Teklif | `models/quote.py:60-160`, `services/quotes.py` | **Doğrudan kullan + genişlet** — "teklif sunulacak" sonucu teklif açar | Nullable `service_order_id` (kaynak iş) eklenir; versiyon kilidi ve iskonto onayı aynen |
| Sipariş / abonelik / tahsilat | `models/order.py`, `subscription.py` | **Dokunma** (kapsam dışı) | Bakım sözleşmesi aboneliğe dönüştürülmez; sözleşme ayrı varlık |
| Ek dosya | `models/attachment.py` | **Doğrudan kullan + genişlet** (§1.9 dört yer) | — |
| Görev panosu | `models/gorev.py`, `services/gorevler.py` | **Doğrudan kullan + genişlet** (`KAYIT_TIPLERI`) | Plan/ekip ataması görev kartı DEĞİLDİR; servis planı kendi tablosunda |
| Denetim izi | `services/audit.py` | **Doğrudan kullan** | Birleşik iş geçmişi (M01-06) için denetim izi YETMEZ (serbest JSON, silinebilir değil ama sorgulanması zor): servis iş emrine özel olay tablosu açılır, kritik işlemler AYRICA denetime yazılır |
| Raporlar | `services/reports.py`, `api/reports.py`, `services/export.py` | **Genişlet** — yeni rapor fonksiyonları, aynı xlsx/izin kalıbı | Mevcut rapor sorguları değiştirilmez |
| Uyarılar | `services/uyarilar.py` | **Genişlet** (yeni blok) | İzne + birime tabi |
| Ayarlar | `services/settings.py` | **Genişlet** (`DEFAULTS`) | — |
| Worker | `worker.py` | **Genişlet** (`GOREVLER`) | İdempotent |
| Kullanıcı / rol | `models/user.py`, `models/rbac.py`, `permissions.py` | **Genişlet** — yeni izinler, roller, birim üyeliği | Mevcut rollerin izin listesi değiştirilmez (yalnız ADMIN otomatik, YONETIM `.gor` otomatik) |
| KVKK | `services/kvkk.py` | **Genişlet** — saha irtibatı/imza gibi kişisel veriler anonimleştirme kapsamına | — |

---

## 6. Önerilen yaklaşım

### 6.1 Seçenekler

| | A) Mevcut `work_orders`'a `tur/birim` eklemek | B) Ayrı teknik servis alanı (aynı katmanlarda yeni dosyalar) |
|---|---|---|
| Artı | Tek iş emri listesi; cihaz–araç geçmişi bedava | Hak ediş, uyarı, panel ve altın kayıt testi etkilenmez; servis iş emrine özgü durum makinesi, olay geçmişi, plan/zaman/sonuç alanları serbestçe tasarlanır; "1 cihaz = 1 PB iş emri" kuralı mobilitenin "1 iş emri = 1 ziyaret" kuralıyla çakışmaz |
| Eksi | `ck_wo_tip`/`ck_wo_durum` değişir; `donem_kapat`, `uyarilar`, `reports` sorguları servis kalemlerini görür; `settlement_period NOT NULL` + `ck_wo_donem_bicimi` servis işine anlamsız alan dayatır; `olustur()` kaydı doğrudan TAMAMLANDI doğurur — plan/atama/bekleme akışı yok; kalem = cihaz + hak ediş fiyatı modeli servis işine uymaz | İki "iş emri" kavramı: ekranda ad ayrımı şart ("İş Emirleri" mobilite, "Servis İşleri" teknik servis); Mobilite birimi servis işleri ile montaj ziyaretleri arasında köprü (nullable FK) gerekir |

### 6.2 TEK NET ÖNERİ: **B — ayrı teknik servis alanı, mevcut katman yapısına gömülü**

Django tarzı "app paketi" AÇILMAZ; canlı mimari katman bazlıdır. Yeni dosyalar:

```
backend/app/models/teknik_servis.py        # (gerekirse servis_*.py olarak bölünür) + models/__init__.py kaydı
backend/app/services/teknik_servis/        # alt paket (emsal: services/imports/)
    __init__.py, is_emirleri.py, planlama.py, zaman.py, bakim.py, atolye.py, kiralama.py, kapsam.py, raporlar.py
backend/app/api/teknik_servis.py           # prefix /api/teknik-servis  (büyürse api/bakim_sozlesmeleri.py, api/kiralamalar.py)
backend/app/templates/servis_formu.html
backend/tests/integration/test_servis_*.py, tests/unit/test_servis_*.py
frontend/src/api/teknikServis.ts
frontend/src/pages/ServisIsleriPage.tsx, ServisPlanlamaPage.tsx, BakimSozlesmeleriPage.tsx, KiralamalarPage.tsx, AtolyePage.tsx
```

Çekirdek tablolar (İngilizce ad, Türkçe sabitler; tümü `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin`, göç edilecekse `SourceMixin`):

| Tablo | Amaç | Ana kısıtlar |
|---|---|---|
| `service_equipment` | Kurulu ekipman (seri no METİN, marka/model `product_id` opsiyonel, `account_id`, `address_id`=lokasyon, `birim`, ops. `device_id`→`devices`) | `ck_svceq_birim`; seri tekilliği yalnız (`product_id`,`serial_no`) kısmi indeksiyle, global değil |
| `service_orders` | Servis iş emri; `birim`, `tur` (ARIZA, PB, KURULUM, KESIF, ...), `status`, `customer_id`→accounts, `address_id`, `equipment_id`, ops. `contract_item_id`, `rma_case_id`, `quote_id`, `work_order_id` (mobilite köprüsü, yalnız oku) | `ck_so_birim`, `ck_so_tur`, `ck_so_durum`; **PB kuralı:** `uq_so_pb_cihaz_donem` (`contract_item_id`, `bakim_donemi`) `WHERE tur='PB' AND NOT is_deleted` → 1 cihaz = 1 PB iş emri |
| `service_order_events` | Silinemez/düzenlenemez olay zaman çizelgesi (durum, atama, plan, bekleme, not, ek, düzeltme) | yalnız INSERT; API'de silme/düzenleme ucu yok |
| `service_holds` | Bekleme (neden sabit liste) | `uq_hold_aktif` kısmi tekil (`service_order_id`) `WHERE released_at IS NULL` |
| `service_plans` + `service_plan_members` | Tarih/saat + ekip/şef/araç ataması; aynı lokasyondaki işler tek planda gruplanır (görsel "ziyaret kartı") | teknisyen çifte rezervasyonu gerekiyorsa `ex_plan_kisi_cakisma` (`user_id =`, `tstzrange(baslangic,bitis,'[)') &&`) |
| `service_time_entries` | Zaman kaydı: kişi, faaliyet (YOL, ISCILIK, MOLA, BEKLEME), başlangıç/bitiş | `ex_zaman_kisi_cakisma` (kişi başına çakışmaz); MOLA kişi-saate dahil edilmez; kayıt yoksa iş "süre eksik" bayrağı (hesaplanır, saklanmaz) |
| `service_results` | Kapanış: sonuç (COZULDU, COZULEMEDI, TEKRAR_GIDILECEK, TEKLIF_SUNULACAK), çözüm kanalı | sonuç yoksa TAMAMLANDI geçişi servis içinde reddedilir |
| `maintenance_contracts` + `maintenance_contract_items` | Bakım sözleşmesi (hesap, lokasyon, periyot, geçerlilik) + kapsanan ekipman | tarihli: `ex_sozlesme_kalem_cakisma` (`equipment_id =`, aralık `&&`) |
| `workshop_records` | Atölye kaydı (haberleşme/telsiz onarımı), gerekirse `rma_case_id` | `ck_atolye_durum` |
| `rentals` + `rental_items` | Kiralama; satır başına seri no | `ex_kiralama_ekipman_cakisma` (`equipment_id =`, `tstzrange(teslim, iade,'[)') &&`) → aynı seri iki kiralamaya çift tahsis edilemez |

Fiyat/maliyet kolonları (işçilik birim fiyatı, parça maliyeti, iş maliyeti) yalnız `sees_cost` true ise yanıtta yer alır; liste ve Excel dahil.

Durum makinesi: `SERVIS_IS_EMRI = StateMachine(ad="Servis İş Emri", baslangiclar={"MUSTERI_TALEBI","PLANLANACAK"}, gecisler=...)`, `KIRALAMA`, `ATOLYE` → `MAKINELER`'e eklenir. Kapalı/iptal işe plan verilemez (M01-13) → makinede terminal durum.

Mobilite birimiyle köprü: Mobilite/Araç Takip servis işi saha montajına dönüşürse kullanıcı mevcut `POST /api/is-emirleri` ile ayrı mobilite iş emri açar; servis iş emri yalnız `work_order_id` referansını tutar. Servis kodu `work_orders`'a YAZMAZ.

### 6.3 Birim kavramının yetki kapsamına eklenmesi (mevcut SCOPE ile uyumlu)

Mevcut yapı: rol başına TEK kapsam dizesi (`Role.scope`, `models/rbac.py:60-61`), değerler `SCOPES` (`permissions.py:80-82`), uygulayıcılar `kapsam_musteri` / `kapsam_disinda_mi` yalnız `== SCOPE_OWN_CUSTOMERS` durumunda filtreler (`services/accounts.py:42-61`). Öneri:

1. **Birim kataloğu** `permissions.py`'ye sabit olarak: `BIRIMLER = {"GUVENLIK": "Güvenlik Sistemleri", "HABERLESME": "Haberleşme", "POC": "POC", "MOBILITE": "Mobilite", "ARAC_TAKIP": "Araç Takip"}` — kodlar kalıcı, CHECK'lerde aynen kullanılır.
2. **Yeni kapsam sabiti** `SCOPE_OWN_UNITS = "KENDI_BIRIMI"` → `SCOPES` demetine eklenir. Mevcut yardımcılar yalnız `KENDI_MUSTERILERI`'ne baktığı için bu rol hesap/cihaz/teklif ekranlarında otomatik `TUMU` davranır — canlı akış değişmez.
3. **Kullanıcı–birim üyeliği** çoklu: `user_units(user_id → users.id CASCADE, birim, is_primary)` PK (`user_id`,`birim`), `ck_user_units_birim`. (Mobilite + Araç Takip'te çalışan kişi iki satır.) `User`'a `birimler` ilişkisi (`lazy="selectin"`) ve `/api/auth/me` çıktısına `birimler` eklenir; kullanıcı yönetimi ekranında düzenlenir, değişiklik denetime yazılır; kişi kendi birimini değiştiremez.
4. **Uygulayıcılar** `services/teknik_servis/kapsam.py` içinde, `kapsam_musteri` kalıbının birebir karşılığı:
   - `kapsam_birim(stmt, user, sutun)` — `user.role.scope == SCOPE_OWN_UNITS` ise `sutun.in_(user_birimleri)`; değilse dokunmaz.
   - `birim_disinda_mi(user, birim) -> bool` — tek kayıt okuma/yazma uçlarında → 404.
   - Servis listeleri İKİ filtreyi de uygular: `kapsam_musteri(...)` (satış temsilcisi kendi müşterisinin servis işini görür) ve `kapsam_birim(...)`.
   - Yazma uçlarında birim DEĞİŞTİRME kontrolü: hedef birim de kullanıcının birimlerinde olmalı (kaydı başka birime taşıyıp kapsamı genişletmek engellenir — `api/accounts.py:441-447` emsali).
5. Aynı kontrol `api/attachments.py:_kapsam`, `services/uyarilar.py` sayıları, rapor uçları ve Excel dışa aktarımına eklenir.
6. Yeni roller (`ROLES`): `SERVIS_YONETICI` (TUMU), `SERVIS_SEF` (KENDI_BIRIMI; planla/ata/kapat), `SERVIS_TEKNISYEN` (KENDI_BIRIMI; kendi işleri, zaman kaydı; maliyet yok), `ATOLYE` (KENDI_BIRIMI). Yeni izinler örnek: `servis.gor`, `servis.yaz`, `servis.planla`, `servis.kapat`, `bakim.gor`, `bakim.yaz`, `kiralama.gor`, `kiralama.yaz`, `zaman.yaz`, `zaman.gor_tumu`. Her izin en az bir role atanır (unit test), `maliyet.gor` kümesi DEĞİŞMEZ.
7. Testler: `tests/integration/test_servis_kapsam.py` — iki birimden iki şef; kapsam dışı birimde liste boş, GET 404, PATCH 404 **ve** kayıt değişmemiş, ek listesi 404, uyarı sayısı yalnız kendi birimi; `tests/unit/test_permissions.py`'ye "her rolün kapsamı geçerli" zaten `SCOPES` üzerinden çalışır.

### 6.4 Uygulama sırası (öncelik kararıyla uyumlu)

1. RBAC + birim (izinler, `user_units`, `kapsam.py`, testler) — diğer her şeyin önkoşulu.
2. Servis iş emri çekirdeği (model, makine, olay geçmişi, bekleme, kapanış sonucu, ek, görev bağlantısı, liste/detay ekranı).
3. Planlama + zaman kaydı (EXCLUDE kısıtlarıyla).
4. Kurulu ekipman + bakım sözleşmesi + worker PB üretimi (idempotent).
5. Atölye (+ RMA köprüsü), kiralama, yedek parça tüketimi (`stock_movements`), teklif köprüsü.
6. Raporlar / uyarılar / SLA parametreleri; ardından eksikler ve güvenlik sıkılaştırma.

Her adım sonunda: `make test` (altın kayıt dahil), `test_migration_zinciri`, `ruff`, `npm run build`.
