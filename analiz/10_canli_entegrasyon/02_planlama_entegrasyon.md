# E02 — Planlama Takvimi ve Toplu Atama: Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21 · Hedef: Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`), bu aşamada yalnız OKUNDU ve kaynak koda dokunulmadı.
> Girdiler: `02_moduller/_ozet/02_planlama.json` (denetçi onaylı 21 madde), `02_planlama_tasarim.md`, `02_planlama_denetim.md`, `05_ESKI_SISTEM_ISLEV_ENVANTERI.md`, proje geçmişi, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md` (bağlayıcı).
> Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köküne göredir.
> Ön koşullar: **E13/RBAC + birim** adımı (`BIRIMLER`, `SCOPE_OWN_UNITS`, `user_units`, `services/teknik_servis/kapsam.py`) ve **E01 servis iş emri çekirdeği** (`service_orders`, `service_order_events`, `service_holds`, `SERVIS_IS_EMRI` makinesi). Bu belge bu ikisinin 00 rehberindeki tasarımla geleceğini varsayar.

---

## 1. Özet

### 1.1 Canlıdaki durum

Canlı ERP'de teknik servis planlaması **hiç yok**. Kod taraması bunu doğruluyor (`plan|takvim|birim|personel` araması):

- Mobilite iş emrinde yalnız `work_orders.scheduled_at` alanı var (`models/workorder.py:116`). Bu alan için plan geçmişi, ekip, araç ve takvim yok. Bu tabloya **dokunulmaz**.
- Personel/birim kavramı yok:
  - `User` modelinde birim alanı yok (`models/user.py:11-39`).
  - `SCOPES` yalnız `TUMU` ve `KENDI_MUSTERILERI` değerlerini içeriyor (`permissions.py:80-82`).
- `vehicles` tablosu müşteri araçlarını tutuyor (mobilite filosu; `models/vehicle.py:48-97`). Servis ekibinin araç havuzu değil.
- Yeniden kullanılabilir parçalar:
  - `tr_normkey` Türkçe normalizasyonu (`services/normalize.py:119-133`)
  - `plaka_anahtari` (`models/vehicle.py:102-110`)
  - `addresses.city/district` (`models/account.py:177-187`)
  - `contacts` (`models/account.py:163-174`)
  - `sayfala` (`api/deps.py:170`)
  - `_xlsx` / `satirlari_xlsx_async` (`api/reports.py:33-38`)
  - `Statistic` (`components/Statistic.tsx`)
  - uyarı merkezi (`services/uyarilar.py:47`)
  - `DEFAULTS` (`services/settings.py:33-91`)
  - `with_for_update` emsali (`api/imports.py:202`)

### 1.2 Sonuç tablosu

| Durum | Adet | Maddeler |
|---|---|---|
| VAR | 1 | E02-18 (gömülü personel adı yok; kalıcı test eklenir) |
| KISMEN | 4 | E02-09 (normalizasyon fonksiyonu var, planlamaya uygulanmamış), E02-16 (`addresses.city/district` var, havuz yok), E02-17 (`plaka_anahtari` var, servis araç havuzu yok), E02-19 (xlsx altyapısı var, planlama dışa aktarımı yok) |
| YOK | 20 | geri kalanlar |

### 1.3 Kullanıcının bizzat doğruladığı işlevler

Eski DengeERP'de kullanıcının doğruladığı işlevler ayrı maddeler olarak güvenceye alındı:

| İşlev | Madde |
|---|---|
| Tıklanabilir KPI kutuları (V1.8) | E02-06 |
| Toplu planlama ve ekip ataması (V1.9) | E02-07 |
| İş Emirleri'nden toplu atama (V1.9) | E02-08 |
| Excel indirme (V1.20.1) | E02-19 |
| Cihaz başına PB iş emri | Planlama her iş emrini ayrı plan satırıyla taşır, iş emirlerini birleştirmez (E02-07, E02-13) |

---

## 2. Mimari yerleşim

```
backend/app/models/teknik_servis.py            (+ ServiceVisit, ServicePlan, ServicePlanMember,
                                                  ServiceVehicle, ServiceUnavailability)
backend/app/models/__init__.py                 (import + __all__)
backend/app/services/teknik_servis/planlama.py (plan, toplu plan, yeniden plan, geri al, atama)
backend/app/services/teknik_servis/cakisma.py  (çakışma motoru; tek kaynak)
backend/app/services/teknik_servis/takvim.py   (takvim, havuz, KPI sayaçları, kaynak görünümü)
backend/app/services/teknik_servis/raporlar.py (plan uyum raporu)
backend/app/api/teknik_servis_planlama.py      (prefix /api/teknik-servis/planlama)
backend/app/main.py                            (include_router; main.py:182-209 bloğu)
backend/app/permissions.py                     (yeni izinler + rol atamaları)
backend/app/services/settings.py               (DEFAULTS planlama blokları)
backend/app/services/uyarilar.py               (servis.gor bloğu)
backend/app/templates/ziyaret_foyu.html        (P3, fiyatsız föy)
frontend/src/api/teknikServis.ts               (planlama tipleri ve çağrıları)
frontend/src/pages/ServisPlanlamaPage.tsx      (/servis-planlama)
frontend/src/pages/ZiyaretlerimPage.tsx        (/ziyaretlerim, 375 px öncelikli)
frontend/src/components/PlanPenceresi.tsx      (KartPenceresi kalıbı: tekli + toplu + yeniden plan)
frontend/src/components/AppLayout.tsx          (MENU kalemleri)
frontend/src/main.tsx                          (rotalar)
tests/unit/test_servis_cakisma.py, tests/integration/test_servis_planlama*.py
```

Uç dosyası ayrı tutulur: `api/teknik_servis.py` (E01) büyümesin diye. 00 rehberindeki "büyürse ayrı dosya" kuralına uygundur.

---

## 3. Veri modeli (yeni tablolar ve migration)

Tüm ana tablolar şu mixin'leri alır: `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin`. Eski DengeERP'den göç edilecek tablolar ayrıca `SourceMixin` ve `uq_<tablo>_kaynak` alır. Kısıt adları `uq_/fk_/ck_/ex_/ix_` önekiyle başlar.

### 3.1 `service_visits`: ziyaret (eski `RouteGroupNo`/`TPL-`)

| Kolon | Tip | Not |
|---|---|---|
| visit_no | String(20) | `ZYR-2026-000123`. PostgreSQL `SEQUENCE service_visit_no_seq` ile üretilir; count/max+1 kullanılmaz. `uq_svcvisit_no` |
| birim | String(12) | `ck_svcvisit_birim` (BIRIMLER) |
| customer_id | FK accounts SET NULL | |
| address_id | FK addresses SET NULL | |
| notes | String(1000) | |
| + SourceMixin | | `uq_svcvisit_kaynak`. Eski `TPL-…` değeri `source_ref` olur |

Ziyaret ayrı tablo olarak tutulur. Eski tasarım §5 "ayrı tablo şart değil" diyordu. Ancak denetim, serbest metin `RouteGroupNo` yüzünden ayrılmış işlerin habersiz taşındığını gösterdi. Ayrı tablo bu riski kapatır (karar K-03).

### 3.2 `service_plans`: plan satırı (silinmez geçmiş)

| Kolon | Tip | Not |
|---|---|---|
| service_order_id | FK service_orders RESTRICT | |
| visit_id | FK service_visits SET NULL | Tekli planda NULL ya da tek işlik ziyaret |
| is_active | Boolean | |
| plan_date | Date NOT NULL | Tarihsiz plan yok (`ck_svcplan_tarih` yerine NOT NULL) |
| start_time | Time NULL | NULL ise "saat belirsiz" |
| duration_min | Integer NOT NULL | `ck_svcplan_sure` (15–1440) |
| starts_at / ends_at | DateTime(tz) NULL | Europe/Istanbul'dan hesaplanır, sorgu için tutulur. `ck_svcplan_saat`: `(start_time IS NULL) = (starts_at IS NULL)` ve `ends_at > starts_at` |
| vehicle_id | FK service_vehicles SET NULL | |
| legacy_vehicle_text | String(30) | Yalnız göç. Eşleşmeyen plaka uydurulmaz |
| address_id | FK addresses SET NULL | Saha |
| contact_id | FK contacts SET NULL | Saha yetkilisi. Telefon `contacts.phone`'dan okunur, plana kopyalanmaz (KVKK) |
| site_area | String(200) | Bina/kat/cihaz bölgesi |
| site_note | String(500) | Ulaşım/otopark |
| plan_note | String(1000) | |
| change_type | String(16) | `ck_svcplan_degisim`: ILK_PLAN, ERTELEME, EKIP_DEGISIMI, YENIDEN_PLAN, GERI_ALMA |
| change_reason | String(24) NULL | `ck_svcplan_neden`: MUSTERI_TALEBI, PERSONEL_YOK, ARAC_YOK, MALZEME_BEKLENIYOR, HAVA_ERISIM, ONCEKI_IS_UZADI, DIGER |
| change_note | String(500) | |
| `ck_svcplan_neden_zorunlu` | | `change_type IN ('ILK_PLAN') OR change_reason IS NOT NULL` |
| `ck_svcplan_diger_not` | | `change_reason <> 'DIGER' OR change_note IS NOT NULL` |
| previous_status | String(16) | Plan öncesindeki gerçek durum |
| conflict_override_note | String(500) NULL | Gerekçeyle geçilen çakışma |
| cancelled_at | DateTime(tz) NULL | Geri alma / yenisiyle değişme zamanı |
| + SourceMixin | | `uq_svcplan_kaynak` |

İndeksler:

- **`uq_svcplan_aktif`**: `(service_order_id) WHERE is_active AND NOT is_deleted`. Kısmi tekil indekstir; M02-D02'yi karşılar.
- `ix_svcplan_tarih (plan_date) WHERE is_active`
- `ix_svcplan_ziyaret (visit_id)`

Planlayan kişi `created_by` kolonudur (ActorMixin), ayrı kolon açılmaz.

### 3.3 `service_plan_members`: ekip

| Kolon | Tip | Not |
|---|---|---|
| plan_id | FK service_plans CASCADE | |
| user_id | FK users RESTRICT | Personel = `User` (karar K-01) |
| rol | String(10) | `ck_svcplanuye_rol`: SEF, TEKNISYEN |
| sahaya_gidiyor | Boolean | Teknisyende her zaman true (`ck_svcplanuye_teknisyen_sahada`). Şefte varsayılan false (M02-D01) |
| | | `uq_svcplanuye (plan_id, user_id)`, `ix_svcplanuye_kullanici (user_id)` |

Mixin istisnası: yalnız `PkMixin, TimestampMixin` kullanılır (emsal `Contact`, `models/account.py:163`). Satır değişmez. Ekip değişince yeni plan satırı açılır ve geçmiş plan satırıyla birlikte korunur.

### 3.4 `service_vehicles`: servis araç havuzu

| Kolon | Not |
|---|---|
| plate, plate_key | `plate_key` = `plaka_anahtari(plate)` (ORM `before_insert/update` olayı, `models/vehicle.py:113-116` emsali). `uq_svcarac_plaka (plate_key) WHERE NOT is_deleted` |
| birim | NULL = ortak havuz. `ck_svcarac_birim` |
| assigned_user_id | FK users SET NULL; zimmet (isteğe bağlı) |
| vehicle_id | FK vehicles SET NULL; araç mobilite takip filosunda da varsa salt referans |
| is_active, notes | |

### 3.5 `service_unavailability`: müsaitlik bloğu (P3)

| Kolon | Not |
|---|---|
| user_id | FK users CASCADE |
| starts_at, ends_at | `ck_svcmusait_aralik` |
| tur | `ck_svcmusait_tur`: IZIN, EGITIM, OFIS, DIGER. Sağlık raporu ayrı tür değildir (karar K-11) |
| note | String(300) |
| | `ex_svcmusait_cakisma`: `user_id =`, `tstzrange(starts_at, ends_at, '[)') &&` (gist) |

### 3.6 Var olan tablolara etki

- **Hiçbiri yok.** `work_orders`, `vehicles`, `addresses` ve `contacts` yalnız okunur.
- Şehir/ilçe için `addresses.city/district` zaten var (`models/account.py:185-186`). Lokasyon/şehir alanlarının sahipliği E14 (müşteri-lokasyon) ve E01'dedir. Planlama bu alanları okur.

### 3.7 Migration

- Komut: `make makemigration m="servis_planlama_takvim"`. Head, E01 migration'ından sonra gelir; kodlamaya başlarken `alembic heads` ile doğrulanır.
- Sequence elle yazılır: `op.execute("CREATE SEQUENCE service_visit_no_seq")` ve downgrade'de `DROP SEQUENCE`.
- `ex_svcmusait_cakisma` yeni tabloda olduğu için autogenerate biçimiyle korunur.
- Downgrade zorunludur. head→base→head testi EXCLUDE sayısını korur.
- `tests/conftest.py` `_TRUNCATE` listesine şunlar eklenir: `service_vehicles`, `service_unavailability`, `service_visits` (FK ile `users`'a bağlılar ama listedeki tablolara cascade yolları garanti değil).

---

## 4. İzinler ve roller (`permissions.py`)

| Kod | Modül | Açıklama | Roller |
|---|---|---|---|
| `servis.planla` | Servis | Plan oluşturur, erteler, geri alır, ziyaret taşır, çakışmayı gerekçeyle geçer | SERVIS_YONETICI, SERVIS_SEF |
| `servis.ata` | Servis | Plan değiştirmeden ekip (şef/teknisyen) atar; toplu atama | SERVIS_YONETICI, SERVIS_SEF |
| `servis.musaitlik` | Servis | Personel müsaitlik bloğu girer/siler | SERVIS_YONETICI, SERVIS_SEF |
| `servis.arac_yaz` | Servis | Servis araç havuzunu yönetir | SERVIS_YONETICI |
| `servis.irtibat_gor` | Servis | Saha yetkilisi adı/telefonu ve açık adresi görür. Plan ekibindeki kullanıcı kendi işinde izinsiz de görür | SERVIS_YONETICI, SERVIS_SEF, SERVIS_TEKNISYEN |

Okuma izni `servis.gor` E01'de tanımlanır ve burada yeniden kullanılır.

Kurallar:

- Her yeni izin en az bir role atanır (`tests/unit/test_permissions.py:43-46`).
- `maliyet.gor` kümesine dokunulmaz.
- `servis.irtibat_gor` `.gor` ile bitmediği için `YONETIM`'e otomatik inmez (`permissions.py:84`). Bu bilinçlidir (M02-15).
- `TEKNIK_SERVIS` (mobilite) rolüne hiçbir yeni izin eklenmez.
- `ozellestirildi=True` DB rollerine izinler otomatik inmez; seed log uyarısı yeterlidir (`seeds/dev.py:44-79`).

---

## 5. API uçları (`/api/teknik-servis/planlama`)

| Yöntem ve yol | İzin | Amaç | Madde |
|---|---|---|---|
| `GET /kaynaklar?birim=` | `servis.planla` **veya** `servis.ata` (gövdede `_izin`) | Birimdeki aktif şef/teknisyen (id, ad, birimler) + aktif araçlar. E-posta/telefon dönmez | E02-04 |
| `GET /takvim?baslangic=&bitis=&birim=&tur=` | `servis.gor` | Aralıktaki plan satırları (≤ 62 gün), çakışma bayrakları, kapalı işler soluk | E02-05, E02-23 |
| `GET /havuz?gruplama=lokasyon\|sehir&q=&birim=` | `servis.gor` | Plansız açık işler; `sayfala`; grup anahtarı sunucuda | E02-05, E02-16 |
| `GET /kpi?gun=&birim=` | `servis.gor` | KPI sayaçları; her sayaç bir `filtre` kodu döner | E02-06 |
| `POST /kontrol` | `servis.planla` | Çakışma önizlemesi (kayıt yok) | E02-15 |
| `PUT /isler/{id}/plan` | `servis.planla` (+ ekip değişiyorsa `servis.ata`) | Tekli plan + ekip, tek transaction | E02-02 |
| `DELETE /isler/{id}/plan` | `servis.planla` | Planı geri al (neden zorunlu) | E02-12 |
| `GET /isler/{id}/plan-gecmisi` | `servis.gor` | Plan satırları + yapan + neden | E02-12 |
| `GET /isler/{id}/saha-onerisi` | `servis.planla` | Aynı müşteri+adres/lokasyonun son planından öneri | E02-11 |
| `POST /toplu-plan` | `servis.planla` + `servis.ata` | Aynı müşteri + lokasyon + birim, plansız işler → tek ziyaret | E02-07 |
| `POST /yeniden-plan` | `servis.planla` | Seçili iş id listesini taşır | E02-13 |
| `POST /toplu-ata` | `servis.ata` | Plan değiştirmeden ekip ataması (≤ 150) | E02-08 |
| `GET /ziyaretlerim?gun=bugun\|yarin` | `servis.gor` | Oturumdaki kullanıcının ekip üyesi olduğu planlar | E02-14 |
| `GET /kaynak-gorunumu?hafta=&birim=` | `servis.gor` | Personel × gün plan dakikası | E02-21 |
| `GET/POST/DELETE /musaitlik` | gör: `servis.gor`, yaz: `servis.musaitlik` | Müsaitlik blokları | E02-20 |
| `GET/POST/PATCH /araclar` | gör: `servis.gor`, yaz: `servis.arac_yaz` | Servis araç havuzu | E02-17 |
| `GET /takvim.xlsx`, `GET /plan-uyumu.xlsx` | `servis.gor` + `rapor.disaaktar` | Excel | E02-19, E02-22 |
| `GET /plan-uyumu` | `servis.gor` + `rapor.gor` | Plan uyum raporu | E02-22 |
| `GET /ziyaretler/{id}/foy.pdf` | `servis.planla` | Fiyatsız ziyaret föyü (P3) | E02-14 |

Bütün uçlarda ortak kurallar:

- Listeler `kapsam_musteri` ve `kapsam_birim` uygular.
- Tek kayıtta `kapsam_disinda_mi` / `birim_disinda_mi` → 404. Kontrol yazmadan önce yapılır.
- Durum geçişi `SERVIS_IS_EMRI.dogrula` ile yapılır. Yanıt `sonraki_durumlar` döner.
- Olay geçmişi `service_order_events` (E01) tablosuna, denetim izi `audit.log` ile aynı transaction'da yazılır.
- Saat yalnız `Clock` ile okunur.
- Hatalar: kural ihlali 409, girdi 400.

---

## 6. Madde bazında entegrasyon

> Biçim: **Kaynak** · **Canlı durum** · **Yaklaşım** · **Dosyalar** · **Kabul** · **Öncelik/Efor** · **Bağımlılık** · **Canlı risk**

### E02-01 · Plan tabloları, tek aktif plan garantisi ve planlama izinleri
- **Kaynak:** M02-D02 (+ modülün veri temeli)
- **Canlı durum:** YOK. Plan tablosu yok; mobilite `work_orders.scheduled_at` tek alan (`models/workorder.py:116`).
- **Yaklaşım:**
  - §3'teki tablolar eklenir: `service_visits`, `service_plans`, `service_plan_members`, `service_vehicles`; `uq_svcplan_aktif` kısmi tekil indeksi ve `service_visit_no_seq`.
  - Plan yazan her servis fonksiyonu önce iş emri satırını `select(ServiceOrder).where(...).with_for_update()` ile kilitler (emsal `api/imports.py:202`). Ardından eski aktif planı `is_active=False, cancelled_at=clock.now()` yapar ve yeni satırı ekler.
  - §4 izinleri `permissions.py`'ye eklenir.
  - Göç betiği `app/migration/servis_plan.py` (emsal `migration/yukle_isemri.py`) eski `WorkOrderPlans`'ta `IsActive=1` olup birden fazla satırı olan iş emirlerini **raporlar**. Yalnız en yüksek `WorkOrderPlanId` aktif aktarılır, diğerleri pasif geçmiş olur, rapora satır yazılır. Otomatik "düzeltme" yapılmaz.
- **Dosyalar:** `models/teknik_servis.py`, `models/__init__.py`, `alembic/versions/<rev>_servis_planlama_takvim.py`, `permissions.py`, `app/migration/servis_plan.py`, `tests/conftest.py`, `tests/integration/test_servis_planlama_eszamanli.py`, `tests/unit/test_permissions.py` (otomatik).
- **Kabul:**
  - Aynı işe eşzamanlı iki plan isteği (`asyncio.gather`, iki ayrı oturum) sonrasında aktif plan satırı sayısı 1'dir; ikinci istek ya sıralanır ya da 409 alır.
  - İki aktif satırı doğrudan INSERT ile yazma denemesi `uq_svcplan_aktif` → 409 Türkçe mesaj döner.
  - Göç raporu çift aktif kayıtları listeler.
  - head→base→head yeşildir.
- **Öncelik/Efor:** P1 · M
- **Bağımlılık:** E01 (service_orders, events), E13 (BIRIMLER, user_units)
- **Canlı risk:** Yok. Yalnız yeni tablolar eklenir. Önlem: altın kayıt testi ve migration zinciri testi koşulur.

### E02-02 · Planlama kapalı/ilerlemiş işin durumunu geri çekmez (KRİTİK)
- **Kaynak:** M02-10
- **Canlı durum:** YOK (servis iş emri ve plan ucu yok). Hatanın kökü olan "durumu doğrudan atama" canlı mobilitede de var (`api/workorders.py:355-366`). Yeni kod bunu kopyalamaz.
- **Yaklaşım:**
  - `services/teknik_servis/planlama.py` içinde tek bir `durum_planla(so, clock)` fonksiyonu bulunur. Bu fonksiyon yalnız `MUSTERI_TALEBI → PLANLANDI` geçişini `SERVIS_IS_EMRI.dogrula` üzerinden yapar.
  - `PLANLANDI` işte durum aynı kalır. `YOLDA/SAHADA/ATOLYEDE/BEKLEMEDE` işte yalnız plan güncellenir, durum korunur.
  - `KAPALI_DURUMLAR = ("TAMAMLANDI","KAPATILDI","IPTAL")` sabiti E01'den alınır. Bu durumlardaki işe plan, toplu plan, yeniden plan, geri alma ve atama `PlanlamaHatasi` → **400** verir ve hiçbir satır yazılmaz.
  - Olay geçmişine `onceki_durum` gerçek değerle yazılır (NULL yazılmaz).
  - Ön yüzde "Planla" ve "Planı Düzenle" düğmeleri `sonraki_durumlar` ve `kapali` bayrağına göre gizlenir.
  - Göç: `app/migration/servis_plan.py` eski veride iki tür kaydı **tespit edip listeler**, düzeltmez:
    - `ClosedAt` dolu ama durumu `Kapatıldı` olmayanlar,
    - `Kapatıldı` sonrası `OldStatus NULL` ile `Planlandı` satırı olanlar.
  - Bu kayıtlar `service_orders`'a eski durumlarıyla aktarılır ve uyarı merkezine "göç: durum tutarsız iş" olarak düşer (E02-25).
- **Dosyalar:** `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `services/statemachine.py` (yalnız E01'in SERVIS_IS_EMRI geçişlerine `PLANLANDI→MUSTERI_TALEBI` ve `PLANLANDI→BEKLEMEDE` geri alma geçişlerinin eklendiği teyidi), `pages/ServisPlanlamaPage.tsx`, `app/migration/servis_plan.py`, `tests/integration/test_servis_planlama_durum.py`.
- **Kabul:**
  - TAMAMLANDI/KAPATILDI/IPTAL işe `PUT /plan`, `POST /toplu-plan`, `POST /yeniden-plan`, `POST /toplu-ata` 400 döner ve `db.refresh` sonrası plan, üye ve durum değişmemiş olur.
  - MUSTERI_TALEBI → PLANLANDI geçer.
  - SAHADA işin planı güncellenir, durum SAHADA kalır.
  - Olayda `onceki_durum` doludur.
  - Göç raporu etkilenen kayıtları listeler ve otomatik düzeltme yapmaz.
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E02-01, E01 (SERVIS_IS_EMRI)
- **Canlı risk:** Yok. `statemachine.py`'ye yalnız yeni makine eklenir; meta-test (`tests/unit/test_statemachine.py:8`) otomatik sınar. CIHAZ/RMA makinelerine dokunulmaz.

### E02-03 · Tekli plan ve ekip ataması tek uç, tek transaction; tarih/süre doğrulaması
- **Kaynak:** M02-11
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `PUT /isler/{id}/plan` uç gövdesi `PlanIn` (Pydantic) şu alanları taşır:
    - `plan_tarihi: date` (zorunlu), `baslangic_saati: time | None`
    - `sure_dk: int = Field(ge=15, le=1440)` (alt/üst sınır `DEFAULTS["servis_plan_sure_min_dk"/"_max_dk"]` ile ikinci kez serviste doğrulanır)
    - `arac_id`, `adres_id`, `irtibat_id`, `saha_bolgesi`, `saha_notu`, `not_`
    - `ekip: EkipIn | None` (`sef_id`, `sef_sahada`, `teknisyen_idleri: list[int] = Field(max_length=30)`)
    - `degisim_nedeni`, `degisim_notu`, `cakisma_gerekcesi`, `version`
  - `ekip` alanı **None** ise mevcut ekip yeni plan satırına kopyalanır. Bu durumda yalnız `servis.planla` yeterlidir.
  - Ekip gönderilmiş **ve** değişmişse gövdede `_izin(user, "servis.ata")` aranır; yoksa 403.
  - Tek `await db.commit()` yapılır; servis yalnız `flush` eder. Hata olursa ne plan ne ekip değişir.
  - Ekipteki kullanıcıların aktif olması ve işin birimine (`user_units`) üye olması gerekir. Aksi 400 (karar K-07).
  - İyimser kilit: `version` service_orders'ınkidir; uyuşmazlık 409 döner.
- **Dosyalar:** `api/teknik_servis_planlama.py`, `services/teknik_servis/planlama.py`, `components/PlanPenceresi.tsx`, `tests/integration/test_servis_planlama_tekli.py`.
- **Kabul:**
  - Planlama sırasında çakışma veya kısıt hatası oluşursa üye satırları da değişmemiştir.
  - Tarihsiz istek 400 döner; 10 dk ve 2000 dk 400 döner.
  - Yalnız `servis.planla` olan kullanıcı ekip göndermeden 200 alır, farklı ekip gönderince 403 alır.
  - 31 teknisyen 400 döner.
  - Başka birimin kullanıcısı ekipte ise 400 döner.
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E02-01, E02-02
- **Canlı risk:** Yok

### E02-04 · Planlama kaynak listesi API'den (kullanıcı yönetimi izni gerekmeden, birim yetkili)
- **Kaynak:** M02-03a
- **Canlı durum:** YOK. Kullanıcı listesi yalnız `sistem.kullanici` ile açık (`api/users.py`). Birim üyeliği yok.
- **Yaklaşım:**
  - `GET /kaynaklar?birim=` şunları döndürür:
    - `user_units` + `users.is_active` + rol kodu ∈ {SERVIS_SEF, SERVIS_TEKNISYEN, SERVIS_YONETICI} olan kullanıcıların `{id, ad, birimler, rol_kodu}` bilgisi,
    - aktif `service_vehicles` (`birim = :birim OR birim IS NULL`).
  - `birim` parametresi kullanıcının birimleri dışındaysa (KENDI_BIRIMI kapsamı) 404 döner.
  - E-posta, kullanıcı adı ve telefon **dönmez** (veri minimizasyonu).
  - Ön yüzde `PlanPenceresi` seçicileri yalnız bu uca bağlanır; kodda gömülü isim yoktur.
- **Dosyalar:** `api/teknik_servis_planlama.py`, `services/teknik_servis/takvim.py`, `api/teknikServis.ts`, `components/PlanPenceresi.tsx`, `tests/integration/test_servis_planlama_kaynak.py`.
- **Kabul:**
  - SERVIS_SEF (sistem.kullanici yok) kendi biriminin aktif personelini görür; pasif kullanıcı listede yoktur.
  - Başka birim parametresi 404 döner.
  - Yanıtta `email` ve `username` anahtarları yoktur.
  - `grep` testi: `frontend/src` içinde gerçek kişi adı yoktur (E02-18).
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E13 (user_units, roller)
- **Canlı risk:** Yok

### E02-05 · Planlama takvimi çekirdeği (Gün/Hafta/Ay, plansız havuz) ve tarih aralıklı yükleme
- **Kaynak:** M02-D03 (+ V1.6 takvim/havuz; proje geçmişi §5.2)
- **Canlı durum:** YOK
- **Yaklaşım:**
  - **Sunucu:**
    - `GET /takvim` aralığı en fazla 62 gün olabilir; aşarsa 400.
    - Sorgu `service_plans` aktif satırları + `service_orders` + üyeler + araç için tek JOIN; üyeler `selectinload` ile yüklenir.
    - Çakışma bayrakları E02-15 motorundan aynı istekte hesaplanır. Ekrandaki birim filtresinden bağımsızdır, çünkü hesap tüm birimler üzerinde yapılır.
    - Kart anahtarı `visit_id` (ziyaret) olur; tekli planda `so.id` kullanılır.
    - `GET /havuz` aktif planı olmayan ve kapalı olmayan işleri `sayfala` ile döner (X-Toplam-Kayit). Arama `q` şu alanlarda yapılır: iş no, müşteri `title_key`, seri no (E03 `service_equipment.serial_no`) ve lokasyon anahtarı.
  - **Ön yüz:**
    - `ServisPlanlamaPage` menüden açılınca doğrudan takvime gelir.
    - Görünümler `Segmented` (Gün/Hafta/Ay/Kaynak) ile seçilir. Servis/Bakım/Tümü sekmeleri ve birim seçici bulunur.
    - Havuz sağda `Card` içinde, aranabilir ve gruplu durur. Dar ekranda (<768 px) `Drawer`'a geçer.
    - Hafta görünümünde gün başına 4, ay görünümünde 3 kart gösterilir; fazlası "+N" ile gün görünümüne geçer.
    - Ziyaret kartı saat, adet, Bakım/Servis/Karma etiketi ve ekibi gösterir. Kart tıklanınca `Drawer` açılır ve alt işler **ayrı ayrı** listelenir.
    - `useQuery({queryKey: ["servis-takvim", baslangic, bitis, birim, tur]})` kullanılır. Yeni kütüphane eklenmez; AntD ve dayjs yeterlidir (karar K-12).
  - **Menü:** `{key:"/servis-planlama", label:"Servis Planlama", icon:<CalendarOutlined/>, izin:"servis.gor"}`. "İş Emirleri" (mobilite) ile ad ayrımı korunur.
- **Dosyalar:** `services/teknik_servis/takvim.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx`, `api/teknikServis.ts`, `components/AppLayout.tsx`, `main.tsx`, `tests/integration/test_servis_takvim.py`.
- **Kabul:**
  - Hafta görünümü yalnız o haftanın planlarını ve havuzun ilk sayfasını yükler.
  - 10.000 servis iş emri + 3.000 plan içeren test verisinde `GET /takvim` (7 gün) p95 < 500 ms ölçülür. Eşik İT ile teyit edilir; ölçüm testi `@pytest.mark.slow` işaretlidir.
  - 63 günlük aralık 400 döner.
  - KENDI_BIRIMI kullanıcısı başka birimin kartlarını görmez.
- **Öncelik/Efor:** P1 · M
- **Bağımlılık:** E02-01, E02-15 (bayraklar; ilk sürümde bayraksız çıkabilir)
- **Canlı risk:** Yok. Yeni rota ve menü kalemi; mevcut "İş Emirleri" kalemi değişmez.

### E02-06 · Tıklanabilir KPI kutuları (sayı = açılan liste)
- **Kaynak:** Proje geçmişi V1.8 (kullanıcı doğruladı); M01-12 dersi; M02-D04 KPI ayrımı
- **Canlı durum:** YOK. Canlı paneldeki `Statistic` kartları tıklanmıyor (`pages/PanelPage.tsx:119-151`).
- **Yaklaşım:**
  - `services/teknik_servis/takvim.py` içinde `KPI_FILTRELERI: dict[str, Callable[[Select, date], Select]]` tanımlanır. Anahtarlar: `bugun_planli`, `hafta_planli`, `havuz`, `cakismali`, `saat_belirsiz`, `bugun_tamamlanan`.
  - `GET /kpi` her filtrenin `count()` değerini, `GET /takvim?kpi=<kod>` aynı filtreyle listeyi döndürür. **Tek kaynak** budur: sayı ile liste aynı fonksiyondan gelir.
  - Ön yüzde `Card hoverable onClick={() => setKpi(kod)}` içinde `Statistic` gösterilir. Seçili kutu vurgulanır. Liste `Drawer`'da `sayfala` ile açılır.
- **Dosyalar:** `services/teknik_servis/takvim.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx`, `tests/integration/test_servis_kpi.py`.
- **Kabul:**
  - Her KPI kodu için `GET /kpi` sayısı ile `GET /takvim?kpi=` X-Toplam-Kayit değeri parametrik testte eşittir.
  - Kapalı işler "planlı" yerine "tamamlanan" kutusunda sayılır.
  - Kutuya tıklayınca liste açılır.
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E02-05
- **Canlı risk:** Yok. `PanelPage` değiştirilmez.

### E02-07 · Toplu planlama (aynı müşteri + lokasyon + birim → tek ziyaret, iş başına ayrı plan)
- **Kaynak:** Envanter #20 `bulk-plan`, proje geçmişi V1.9 (kullanıcı doğruladı); 1 cihaz = 1 PB iş emri kuralı
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `POST /toplu-plan` gövdesi `{is_idleri (1–150), PlanIn alanları, ekip zorunlu (en az şef veya teknisyen)}` biçimindedir.
  - Servis `toplu_planla()` sırasıyla şunları yapar:
    1. `select(ServiceOrder).where(id.in_(…)).order_by(id).with_for_update()` ile satırları kilitler (id sıralı kilit, deadlock önlemi).
    2. Tümünün bulunduğunu, kapsam içinde olduğunu (aksi 404), **aynı birim**, **aynı müşteri** ve **aynı lokasyon anahtarı** (E02-09) taşıdığını, kapalı olmadığını ve aktif planı olmadığını doğrular. Aksi durumda 400 döner ve iş numaraları listelenir.
    3. Bir `service_visits` satırı açar (sequence numarası).
    4. **Her iş için ayrı** `service_plans` + üyeler yazar. İşler birleştirilmez; PB işleri cihaz başına kalır.
    5. Durumu E02-02 kuralıyla yürütür.
    6. Her işe `PLAN` olayı ve tek `audit.log("service_visits","toplu_planla")` yazar.
  - Toplu plan **yalnız plansız işler** içindir. Planlı işleri taşımak E02-13'ün işidir.
- **Dosyalar:** `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `components/PlanPenceresi.tsx`, `pages/ServisPlanlamaPage.tsx` (havuzda grup onay kutusu), `tests/integration/test_servis_toplu_plan.py`.
- **Kabul:**
  - 17 iş tek istekte tek ziyaret altında 17 ayrı aktif plan satırına dönüşür.
  - Farklı lokasyon/müşteri/birim veya planlı iş varsa 400 döner, liste verilir ve hiçbir satır yazılmaz.
  - 151 iş 400 döner.
  - PB işleri ayrı iş emri olarak kalır (`service_orders` sayısı değişmez).
- **Öncelik/Efor:** P1 · M
- **Bağımlılık:** E02-01, E02-02, E02-09
- **Canlı risk:** Yok

### E02-08 · İş listesinden toplu ekip ataması (plan değişmeden)
- **Kaynak:** Envanter #18 `bulk-assign`, proje geçmişi V1.9 (kullanıcı doğruladı: "toplu olarak atamasını yapabiliyorum")
- **Canlı durum:** YOK. Canlı mobilite iş emrinde atama montaj noktası/iç teknisyen alanıdır (`models/workorder.py:111-114`); servis ekibiyle ilgisi yoktur.
- **Yaklaşım:**
  - `POST /toplu-ata {is_idleri ≤150, sef_id?, sef_sahada, teknisyen_idleri ≤30}`. En az şef veya teknisyen zorunludur.
  - Kurallar: tek birim, kapalı iş yok, tek transaction, id sıralı kilit.
  - Aktif planı olan işte ekip değişikliği yeni plan satırı (`change_type=EKIP_DEGISIMI`, tarih/saat/araç aynen kopyalanır, neden zorunlu değil) olarak yazılır.
  - Aktif planı olmayan işte ekip **plansız sorumlu atama** olarak `service_orders.sorumlu_sef_id` / E01'in atama alanına yazılır (E01 ile ortak karar K-08).
  - Her işe `ATAMA` olayı yazılır: "Toplu personel ataması…".
  - Ön yüzde `ServisIsleriPage` (E01) tablosunda `rowSelection` + "Toplu Ata" düğmesi (`yetkili("servis.ata")`) bulunur.
- **Dosyalar:** `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `pages/ServisIsleriPage.tsx` (E01), `tests/integration/test_servis_toplu_ata.py`.
- **Kabul:**
  - Plan tarihi/saati/aracı değişmez.
  - Farklı birim veya kapalı iş 400 döner ve hiçbir satır değişmez.
  - Olay geçmişinde not görünür.
  - `servis.ata` olmayan kullanıcı 403 alır.
- **Öncelik/Efor:** P1 · S
- **Bağımlılık:** E02-01, E01
- **Canlı risk:** Yok

### E02-09 · Lokasyon eşleşmesinde tek ortak Türkçe normalizasyon
- **Kaynak:** M02-13
- **Canlı durum:** KISMEN. `tr_normkey` İ/ı/I/i'yi katlar, çoklu boşluğu teke indirir ve kırpar (`services/normalize.py:119-133`). Hesap unvanında kullanılıyor (`models/account.py:193-196`), planlamada kullanılmıyor.
- **Yaklaşım:**
  - Lokasyon anahtarı **yalnız sunucuda** hesaplanır: `lokasyon_anahtari(so) = f"{so.customer_id}|{so.address_id or ''}|{tr_normkey(so.lokasyon_metni)}"`.
  - Önce `address_id` eşleşmesine, yoksa normalize serbest metne bakılır.
  - Havuz, takvim ve toplu plan doğrulaması aynı fonksiyonu kullanır.
  - Ön yüz kendi normalizasyonunu **yazmaz**; sunucunun döndürdüğü `grup_anahtari` ile gruplar. İstemci ile sunucu bu yüzden ayrışamaz (karar K-05).
  - Toplu lokasyon düzeltmesi E01/E14'e devredilir.
- **Dosyalar:** `services/teknik_servis/takvim.py`, `services/teknik_servis/planlama.py`, `tests/unit/test_servis_lokasyon_anahtari.py`.
- **Kabul:**
  - "Akyaka  AVM" ile "AKYAKA AVM" aynı anahtara düşer.
  - "İSTANBUL ŞUBE" ile "istanbul şube" aynı gruptadır ve toplu planda reddedilmez.
  - Havuzdaki `grup_anahtari` toplu plan doğrulamasıyla aynıdır.
- **Öncelik/Efor:** P2 · S
- **Bağımlılık:** E01 (lokasyon alanı), E14 (adres)
- **Canlı risk:** Yok. `tr_normkey` değiştirilmez, yalnız çağrılır.

### E02-10 · Şef ataması varsayılan "sorumlu"; yalnız "sahaya gidiyor" ise çakışmaya girer
- **Kaynak:** M02-D01
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `service_plan_members.sahaya_gidiyor` kolonu bulunur. Şef için varsayılan **false**, teknisyen için CHECK ile true'dur.
  - Çakışma motoru (E02-15) kişi kümesini `WHERE sahaya_gidiyor` ile alır.
  - Plan formunda "Şef sahaya gidiyor" `Switch` bulunur.
  - Şef↔teknisyen çapraz kontrolü yalnız sahadaki kişiler arasında doğal olarak oluşur: aynı `user_id` hangi rolde olursa olsun sahadaysa çakışır.
- **Dosyalar:** `models/teknik_servis.py`, `services/teknik_servis/cakisma.py`, `components/PlanPenceresi.tsx`, `tests/unit/test_servis_cakisma.py`.
- **Kabul:**
  - Aynı şefin örtüşen, farklı teknisyenli iki işi çakışma vermez.
  - Şef sahaya işaretliyse çakışma verir.
  - A işinde sahadaki şef, B işinde teknisyense çakışma verir.
  - `cakismali` KPI'ı yalnız gerçek çakışmaları sayar.
- **Öncelik/Efor:** P2 · S
- **Bağımlılık:** E02-01
- **Canlı risk:** Yok

### E02-11 · Saha önerisi aynı müşteri + lokasyonun son plan satırından
- **Kaynak:** M02-12
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `GET /isler/{id}/saha-onerisi`, aynı `lokasyon_anahtari` (E02-09) ile en son `service_plans` satırını bulur. Bu satır aktif ya da pasif olabilir ve `created_at desc` ile seçilir.
  - Öneri alan bazında `{alan, deger, kaynak: "ONCEKI_PLAN"|"EKIPMAN"|"SOZLESME"}` biçiminde döner. Alanlar: `adres_id` (+ adres metni, il, ilçe), `irtibat_id` (+ ad, telefon yalnız `servis.irtibat_gor` ile), `saha_bolgesi`, `saha_notu`.
  - İkinci kaynaklar: E03 `service_equipment.address_id` ve E04 sözleşme lokasyonu.
  - Kayıt yoksa alan dönmez; tahmin yapılmaz.
  - Ön yüz yalnız **boş** form alanlarını doldurur (`form.isFieldTouched` / değer boş kontrolü).
  - Eski 8 serbest alan şöyle eşlenir: il/ilçe/açık adres → `addresses`, yetkili/telefon → `contacts`, bina/kat → `site_area`, ulaşım → `site_note`, tesis adı → `addresses.label`.
- **Dosyalar:** `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `components/PlanPenceresi.tsx`, `tests/integration/test_servis_saha_onerisi.py`.
- **Kabul:**
  - Önceden saha bilgisiyle planlanmış lokasyonda yeni işin formu bütün saha alanlarını önerir.
  - Kullanıcının doldurduğu alan ezilmez.
  - Kayıt yoksa öneri boştur.
  - `servis.irtibat_gor` olmayan kullanıcıya telefon dönmez.
- **Öncelik/Efor:** P2 · S
- **Bağımlılık:** E02-09, E14 (addresses genişletmesi isteğe bağlı)
- **Canlı risk:** Yok. `addresses` ve `contacts` yalnız okunur.

### E02-12 · Erteleme nedeni zorunluluğu, planı geri alma ve plan geçmişi
- **Kaynak:** M02-02
- **Canlı durum:** YOK
- **Yaklaşım:**
  - **Erteleme:** Aktif planlı işte `plan_tarihi` veya `baslangic_saati` değişirse `change_type=ERTELEME` olur. `degisim_nedeni` yoksa servis `PlanlamaHatasi` → **400** döner. Bu kural DB'de `ck_svcplan_neden_zorunlu` ile de güvenceye alınır. Neden listesi `PLAN_DEGISIM_NEDENLERI` tuple'ıdır.
  - **Geri alma:** `DELETE /isler/{id}/plan` gövdesi `{neden, not}` taşır. Aktif plan `is_active=False, cancelled_at` olur ve `change_type=GERI_ALMA` ile işaretli boş bir iz satırı açılmaz (karar K-09: geri alma, kapatılan satırın kendisine `cancelled_at` ve olaya neden yazılarak izlenir). Plan satırına `change_reason` güncellemesi yapılmaz, çünkü satır değişmez kalmalı.
  - Geri almada durum `previous_status` değerine döner. `service_holds`'ta aktif bekleme varsa durum `BEKLEMEDE` olur. Bu geçiş `SERVIS_IS_EMRI.dogrula` ile yapılır.
  - **Geçmiş:** `GET /plan-gecmisi` pasif ve aktif bütün satırları tarih, saat, ekip, araç, planlayan (`created_by` → ad), değişim türü, neden ve not ile sırayla döner. Detay `Drawer`'da `Timeline` olarak gösterilir.
- **Dosyalar:** `models/teknik_servis.py`, `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx`, `pages/ServisIsleriPage.tsx` (E01 detayına "Plan Geçmişi" sekmesi), `tests/integration/test_servis_plan_gecmisi.py`.
- **Kabul:**
  - Nedensiz tarih değişikliği 400 döner.
  - Geri alınan iş havuzda görünür ve durumu önceki değerine döner; aktif bekleme varsa BEKLEMEDE olur.
  - Geçmiş yapan kişi ve nedenle listelenir.
  - Kapalı işte geri alma 400 döner.
  - Olay geçmişinde `PLAN_GERI_AL` vardır.
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E02-01, E02-02, E01 (holds)
- **Canlı risk:** Yok

### E02-13 · Ziyaret kartındaki seçili işleri tek işlemde yeniden planlama
- **Kaynak:** M02-01
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `POST /yeniden-plan` gövdesi `{is_idleri (1–150), yeni tarih/saat/süre, ekip?, arac_id?, neden (zorunlu), not, cakisma_gerekcesi}` biçimindedir.
  - Doğrulama: tüm işlerin aktif planı var, hepsi tek birimde, hiçbiri kapalı değil, hepsi kapsam içinde. Aksi 400 döner ve iş numaraları listelenir.
  - **Yalnız gönderilen id'ler** taşınır. Aynı ziyarette olup seçilmeyen işe dokunulmaz.
  - Ziyaret ataması:
    - Seçilen işlerin hepsi aynı `visit_id`'yi taşıyor **ve** ziyaretin bütün aktif işleri seçildiyse ziyaret korunur.
    - Aksi halde seçilenler için yeni `service_visits` açılır, yani ziyaretten ayrılırlar.
  - Tekli planda (`PUT /plan`) ziyaret alanı istemciden **alınmaz**, salt okunurdur. Tek iş yeni tarihe alınırsa ve ziyarette başka iş kalıyorsa `visit_id=NULL` olur.
  - Her işe `PLAN_ERTELE` olayı yazılır (eski → yeni tarih/saat, neden). Durum korunur (E02-02).
  - Tek transaction, id sıralı `with_for_update`. Çakışma kontrolü E02-15 ile yapılır.
- **Dosyalar:** `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx` (ziyaret `Drawer`ında onay kutulu alt iş listesi + "Seçilenleri Taşı"), `tests/integration/test_servis_yeniden_plan.py`.
- **Kabul:**
  - 17 işlik kart tek transaction'da taşınır.
  - Seçilmeyen iş eski tarihte kalır.
  - Kapalı veya farklı birim iş varsa 400 döner, liste verilir ve hiçbir satır değişmez.
  - Her işin olayında eski/yeni tarih ve neden bulunur.
  - Tekli plan gövdesindeki `ziyaret_id` yok sayılır.
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E02-12, E02-02, E02-15
- **Canlı risk:** Yok

### E02-14 · Teknisyen "Bugünkü ziyaretlerim" mobil listesi (+ P3 föy)
- **Kaynak:** M02-08
- **Canlı durum:** YOK. Canlı uygulamada mobil saha rolü bilinçli olarak yok (`permissions.py:87-88`). Yeni `SERVIS_TEKNISYEN` rolü bu boşluğu teknik servis için doldurur.
- **Yaklaşım:**
  - `GET /ziyaretlerim?gun=bugun|yarin` yalnız `service_plan_members.user_id = user.id` olan aktif planları döner. Planlar `starts_at` sırasına göre (saat belirsizler sona), ziyaret bazında gruplu gelir.
  - Ekip üyesi kendi işinde irtibat bilgisini izinden bağımsız görür (E02-24).
  - Planı olmayan ama kendisine sorumlu atanmış açık işler ayrı blokta listelenir.
  - Ön yüz `ZiyaretlerimPage` 375 px öncelikli çalışır:
    - `List` + `Card`,
    - `<a href={"tel:"+telefon}>`,
    - harita bağlantısı `https://www.google.com/maps/search/?api=1&query=<encodeURIComponent(adres)>`. Anahtar kullanılmaz ve yalnız tıklanınca açılır (karar K-13).
    - Cihaz/seri listesi bulunur. Her iş "Aç" ile ayrı detaya (E01) gider.
  - Menü: `{key:"/ziyaretlerim", label:"Ziyaretlerim", izin:"servis.gor"}`.
  - P3 föy: `GET /ziyaretler/{id}/foy.pdf`, `templates/ziyaret_foyu.html` + `belgeler.ziyaret_foyu_baglami`. Fiyat ve maliyet alanı bağlama **hiç konmaz**.
- **Dosyalar:** `services/teknik_servis/takvim.py`, `api/teknik_servis_planlama.py`, `pages/ZiyaretlerimPage.tsx`, `components/AppLayout.tsx`, `main.tsx`, `services/belgeler.py`, `templates/ziyaret_foyu.html`, `tests/integration/test_servis_ziyaretlerim.py`.
- **Kabul:**
  - Teknisyen yalnız kendine atanmış bugün/yarın işlerini saat sırasıyla görür.
  - Başka teknisyenin işi listede yoktur.
  - Telefon `tel:` bağlantısıdır.
  - Her iş ayrı açılır.
  - Föy PDF metninde "₺" ve fiyat/maliyet anahtarı yoktur.
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E02-01, E02-04, E01 (detay ekranı)
- **Canlı risk:** Yok

### E02-15 · Sunucu tarafı çakışma kontrolü (uyarı + gerekçeyle geçme)
- **Kaynak:** M02-09
- **Canlı durum:** YOK. Kod tabanında `pg_advisory_xact_lock` kullanımı da yok; bu modül ilk kullanım olacak.
- **Yaklaşım:**
  - `services/teknik_servis/cakisma.py` → `cakismalari_bul(db, adaylar) -> list[Cakisma]`. Çakışma türleri `KISI`, `ARAC`, `MUSAITLIK`, `SAAT_BELIRSIZ` (uyarı).
  - Sorgu **tüm birimler** üzerinde, `kapsam_birim` uygulanmadan çalışır. Kapsam yalnız **yanıtta** uygulanır: kullanıcının kapsamı dışındaki çakışan iş `{tur, birim, saat_araligi, maskeli: true}` olarak döner; iş no ve müşteri adı dönmez (karar K-06).
  - Örtüşme `tstzrange(starts_at, ends_at, '[)') && :aralik` ile hesaplanır. Saati belirsiz plan çakışmaya girmez, `SAAT_BELIRSIZ` uyarısı üretir.
  - Aynı `visit_id` içindeki işler birbiriyle çakışmaz.
  - Araç eşleşmesi `vehicle_id` ile yapılır; göç kayıtlarında `plaka_anahtari(legacy_vehicle_text)` kullanılır.
  - Kişi kümesi yalnız `sahaya_gidiyor` üyelerden oluşur (E02-10). MUSAITLIK E02-20 ile gelir.
  - **Akış:** `POST /kontrol` önizleme yapar. Yazma uçları da kayıttan önce aynı fonksiyonu çağırır.
    - Çakışma varsa ve `cakisma_gerekcesi` boşsa **409** döner: `{detail, cakismalar:[...]}`.
    - Gerekçe (≥ 10 karakter) varsa kayıt yapılır, `conflict_override_note` yazılır, `CAKISMA_GECILDI` olayı ve `audit.log` eklenir.
    - Gerekçeyle geçme yetkisi `servis.planla` sahibindedir (karar K-04).
  - **Eşzamanlılık:** Yazmadan önce etkilenen her `plan_date` için tarih sıralı `SELECT pg_advisory_xact_lock(hashtextextended('servis_plan:' || :tarih, 0))` alınır. İki eşzamanlı çakışan istekte ikincisi kilidi bekler, birincinin satırını görür ve 409 alır.
  - Ön yüzde 409'da `Modal` çakışma listesini ve gerekçe alanını gösterir; "Gerekçeyle Kaydet" ile istek tekrarlanır.
- **Dosyalar:** `services/teknik_servis/cakisma.py`, `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `components/PlanPenceresi.tsx`, `api/client.ts` (yalnız `ApiError` gövdesinden `cakismalar` okunur; mevcut `cakisma` 409 alanı korunur), `tests/unit/test_servis_cakisma.py`, `tests/integration/test_servis_cakisma_eszamanli.py`.
- **Kabul:**
  - Haberleşme işinde 10:00–12:00 atanan kişi POC işinde 11:00'e atanınca API 409 döner.
  - Takvimde birim filtresi POC iken bayrak işaretli kalır.
  - Aynı ziyaretin işleri birbirine çakışma vermez.
  - Gerekçeli kayıt olay geçmişinde görünür.
  - Eşzamanlı iki çakışan istekten ikincisi 409 alır.
  - Kapsam dışı çakışmada yanıtta müşteri adı yoktur.
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E02-10, E02-03, E02-01
- **Canlı risk:** Düşük. Advisory lock yalnız `servis_plan:` ad alanında alınır; diğer modüller kilit kullanmaz. Önlem: kilit anahtarı sabit önekli ve transaction ölçekli (`_xact_`); bağlantı havuzunda sızıntı olmaz.

### E02-16 · Şehir/ilçe bazlı havuz ve aynı bölge önerisi (ayrı tekli plan olarak)
- **Kaynak:** M02-06
- **Canlı durum:** KISMEN. `addresses.city/district` var (`models/account.py:185-186`). İş emrinde şehir yok; havuz ve öneri yok.
- **Yaklaşım:**
  - Şehir/ilçe, işin `address_id` üzerinden okunur. Alan sahipliği E01/E14'tedir; planlama yeni kolon açmaz.
  - `GET /havuz?gruplama=sehir` `(tr_normkey(city), tr_normkey(district))` ile gruplar. Boş şehirler `"Şehir girilmemiş"` grubuna düşer.
  - `GET /bolge-onerisi?is_id=&tarih=` iki liste döner:
    - aynı ilçedeki plansız işler,
    - `DEFAULTS["servis_bolge_oneri_gun"]=3` gün içindeki aynı ilçe ziyaretleri.
  - Panelden seçilen iş **ayrı tekli plan** (`PUT /plan`) olarak kaydedilir: aynı gün ve ekip, başlangıç saati önceki ziyaretin `ends_at` değerinden sonra. Ziyarete eklenmez; toplu planın aynı lokasyon kuralı korunur.
  - Eski kayıtlar göçte yalnız dolu `SiteCity/SiteDistrict` ile adres oluşturur; tahmin yapılmaz.
- **Dosyalar:** `services/teknik_servis/takvim.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx`, `app/migration/servis_plan.py`, `tests/integration/test_servis_bolge.py`.
- **Kabul:**
  - Havuz Lokasyon/Şehir-İlçe arasında geçer.
  - Şehri boş işler "Şehir girilmemiş" grubunda toplanır.
  - İstanbul/Üsküdar ziyareti planlanırken aynı ilçedeki plansız işler ve ±3 gün ziyaretleri önerilir.
  - Seçilen iş ayrı plan satırı ve ayrı ziyaretle kaydedilir.
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E01/E14 (iş → adres), E02-03
- **Canlı risk:** Yok

### E02-17 · Kimlik bazlı atama ve servis araç ana tablosu
- **Kaynak:** M02-03b
- **Canlı durum:** KISMEN. `plaka_anahtari` normalize plaka kuralı hazır (`models/vehicle.py:102-110`). Ekip üyeleri E02-01'de zaten `user_id` FK ile tutulur, yani isimden bağımsız görünürlük doğuştan vardır. Servis araç havuzu tablosu ve eski isim atamalarının eşleştirilmesi yok.
- **Yaklaşım:**
  - `service_vehicles` (§3.4) tablosu açılır. Ekran: `ServisPlanlamaPage` içinde "Araçlar" sekmesi (KartPenceresi kalıbı, `servis.arac_yaz`).
  - Göç `app/migration/servis_plan.py` şunları yapar:
    - Eski `AssignedName` → `tr_normkey(users.full_name)` tam eşleşmesi aranır. Eşleşmeyen veya birden çok eşleşen isimler **eşleşmedi raporuna** yazılır, tahmin yapılmaz. Eşleşmeyen atama, plan satırının `source_ref` notunda ham metin olarak korunur.
    - Eski `VehiclePlate` → `plaka_anahtari` ile `service_vehicles` eşleşir. Eşleşmezse `legacy_vehicle_text` doldurulur.
  - Teknisyen görünürlüğü `service_plan_members.user_id = user.id` ile sağlanır.
- **Dosyalar:** `models/teknik_servis.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx`, `app/migration/servis_plan.py`, `tests/integration/test_servis_araclar.py`.
- **Kabul:**
  - "34 ABC 123" ve "34abc123" ikinci kez tanımlanamaz (`uq_svcarac_plaka` → 409).
  - Teknisyen, adı farklı yazılsa da `user_id` ile işlerini görür.
  - Göç raporu eşleşmeyen isim ve plakaları listeler.
- **Öncelik/Efor:** P2 · M
- **Bağımlılık:** E02-01, E13 (kullanıcı/birim), araç sayısı kararı (K-10)
- **Canlı risk:** Yok. Mobilite `vehicles` tablosuna yazılmaz; yalnız isteğe bağlı FK ile okunur.

### E02-18 · Personel adlarının oturumsuz statik dosyada yayınlanmaması
- **Kaynak:** M02-14 (dotnet_specific; özü geçerli)
- **Canlı durum:** VAR. Canlı ön yüzde kişi listesi koda gömülü değil. Kullanıcılar API'den geliyor; ön yüz paketi yalnız kod içeriyor (`frontend/src`).
- **Yaklaşım:**
  - Kalıcı güvence: `tests/unit/test_on_yuz_kisisel_veri.py` testi `frontend/src/**/*.ts(x)` içinde seed kullanıcılarının `full_name` değerlerini ve Türkçe ad-soyad listesi kalıbını arar ve bulunursa kırmızı olur.
  - Kaynak listesi yalnız E02-04 ucundan gelir.
- **Dosyalar:** `tests/unit/test_on_yuz_kisisel_veri.py`.
- **Kabul:** Oturumsuz erişilebilen ön yüz paketinde personel adı geçmez; test CI'da koşar.
- **Öncelik/Efor:** P3 · S
- **Bağımlılık:** E02-04
- **Canlı risk:** Yok

### E02-19 · Planlama Excel dışa aktarımı
- **Kaynak:** Envanter #60 (8 sayfalı Excel, V1.20.1'de kullanıcı doğruladı); proje geçmişi §7
- **Canlı durum:** KISMEN. Altyapı hazır: `export.satirlari_xlsx_async` (`services/export.py:45`), formül enjeksiyonu koruması (`:26`), `_xlsx` yardımcısı (`api/reports.py:33-38`), `rapor.disaaktar` izni. Planlama dışa aktarımı yok.
- **Yaklaşım:**
  - `GET /takvim.xlsx?baslangic=&bitis=&birim=&tur=&kpi=`: ekranla **aynı** servis fonksiyonu ve filtreyle üretilir.
  - Kolonlar: iş no, birim, tür (Servis/Bakım), müşteri, lokasyon, il/ilçe, plan tarihi, saat, süre (**"Planlanan süre (dk)"** başlığıyla; gerçek süre değildir), ziyaret no, şef, teknisyenler, araç, durum, çakışma, erteleme sayısı.
  - Boş tarih parametresi URL'ye eklenmez; sunucuda `None` kabul edilir. Bu, V1.20 hatasının dersidir: boş dize 400/422 üretmez, Pydantic `date | None` olarak çözülür.
  - İrtibat telefonu yalnız `servis.irtibat_gor` ile kolon olarak eklenir. Maliyet kolonu yoktur.
  - Birim kapsamı Excel'e de uygulanır.
  - Kalan 8 sayfalık yönetim raporunun bütünü E12'nin işidir.
- **Dosyalar:** `api/teknik_servis_planlama.py`, `services/teknik_servis/takvim.py`, `pages/ServisPlanlamaPage.tsx` (`ExcelBtn` kalıbı, `pages/RaporlarPage.tsx:182`), `tests/integration/test_servis_takvim_xlsx.py`.
- **Kabul:**
  - Excel satır sayısı aynı filtreyle `GET /takvim` toplamına eşittir.
  - Tarih seçili/seçili değil iki durumda da dosya iner.
  - `rapor.disaaktar` olmayan kullanıcı 403 alır.
  - KENDI_BIRIMI kullanıcısının dosyasında başka birim satırı yoktur.
- **Öncelik/Efor:** P2 · S
- **Bağımlılık:** E02-05
- **Canlı risk:** Yok. `api/reports.py` değiştirilmez; yalnız `export_svc` çağrılır.

### E02-20 · Personel müsaitlik blokları (bordro değil)
- **Kaynak:** M02-05
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `service_unavailability` (§3.5) tablosu eklenir. Uçlar `GET/POST/DELETE /musaitlik` şeklindedir.
  - Şef yalnız kendi birimindeki kullanıcıya blok girer; aksi 404. Yönetici herkese girebilir.
  - Silme `SoftDeleteMixin` ile yapılır ve EXCLUDE `WHERE NOT is_deleted` olarak tanımlanır.
  - Çakışma motoru `MUSAITLIK` türünü üretir; bu tür **uyarı + gerekçe** ister (E02-15 akışı).
  - Kişi-saat ve zaman raporları (E09) bu tabloyu **okumaz**.
  - `audit.log(..., is_personal_data=True)`.
  - KVKK: `services/kvkk.py` anonimleştirme kapsamına `service_unavailability.note` eklenir.
  - Eğitim entegrasyonu ayrı adımdır (E08): katılımcısı önceden girilmiş oturumlar gün bazlı salt-okunur blok olarak okunur.
- **Dosyalar:** `models/teknik_servis.py`, `services/teknik_servis/cakisma.py`, `api/teknik_servis_planlama.py`, `services/kvkk.py`, `pages/ServisPlanlamaPage.tsx` (Kaynak görünümünde blok girişi), `tests/integration/test_servis_musaitlik.py`.
- **Kabul:**
  - İzin girilen personele o güne plan yapılınca 409 ve gerekçe istenir.
  - Blok silinince uyarı kalkar.
  - Aynı kişiye örtüşen iki blok `ex_svcmusait_cakisma` → 409 döner.
  - E09 kişi-saat raporunda blok süresi yoktur.
- **Öncelik/Efor:** P3 · M
- **Bağımlılık:** E02-15, E02-17
- **Canlı risk:** Yok

### E02-21 · Kaynak (ekip) görünümü: personel × gün, plan dakikası
- **Kaynak:** M02-04
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `GET /kaynak-gorunumu?hafta=YYYY-MM-DD&birim=` birimdeki her aktif kaynak kullanıcı için 7 hücre döner: `plan_dk` (yalnız `sahaya_gidiyor` üyelikleri), ziyaret sayısı, çakışma ve müsaitlik bayrağı.
  - Planı olmayan kişi boş satır olarak gelir.
  - `servis.planla` olmayan kullanıcı (teknisyen) yalnız kendi satırını alır.
  - Ön yüzde `Table` (satır = kişi, kolon = gün) bulunur. Hücrede "**plan** 240 dk" etiketi gösterilir; gerçek süre olarak sunulmaz.
- **Dosyalar:** `services/teknik_servis/takvim.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx`, `tests/integration/test_servis_kaynak_gorunumu.py`.
- **Kabul:**
  - Hafta modunda birimdeki her aktif personel için satır oluşur.
  - Planı olmayan boş görünür.
  - Hücrede "plan" etiketli toplam dakika vardır.
  - Teknisyen yalnız kendi satırını görür.
- **Öncelik/Efor:** P3 · M
- **Bağımlılık:** E02-17, E02-10, E02-20 (kısmen)
- **Canlı risk:** Yok

### E02-22 · Plan uyumu raporu (plan doluluğu hariç ilk sürüm)
- **Kaynak:** M02-07
- **Canlı durum:** YOK. Rapor altyapısı var (`services/reports.py`, `api/reports.py:27-30`).
- **Yaklaşım:**
  - `services/teknik_servis/raporlar.py` → `plan_uyumu(db, clock, baslangic, bitis, birim_kumesi)`. Ayrı ayrı şunları döner:
    - **plan bekleyen yaşı:** havuzdaki işlerin `clock.today() - created_at::date` dağılımı;
    - **plana uyum:** ziyaret başına ilk `service_time_entries` (E09; faaliyet YOL/ISCILIK) kaydının İstanbul günü = `plan_date` ise "uyumlu", farklıysa "kaydı". Süre kaydı yoksa **"süre kaydı eksik"** ayrı satıra yazılır ve paydaya girmez;
    - **erteleme:** `change_type=ERTELEME` sayısı ve neden dağılımı. Göçten gelen nedensiz satırlar "neden kaydı yok" olarak görünür;
    - **ziyaret başına iş:** `count(service_order_id)/count(distinct visit_id)`;
    - **30 günde tekrar ziyaret:** aynı müşteri + `address_id` için 30 gün içindeki ayrı ziyaretler.
  - Kırılımlar: birim, şef, teknisyen, il, **Servis / Bakım (tur='PB') ayrı**.
  - `GET /plan-uyumu` (`rapor.gor`) ve `GET /plan-uyumu.xlsx` (`rapor.disaaktar`) aynı fonksiyondan üretilir.
  - Hiçbir kolonda `duration_min` "gerçek süre" adıyla yer almaz. Plan doluluğu eklenmez; çalışma saati ayarı ve müsaitlik oturunca ayrı madde olur.
  - Maliyet alanı yoktur.
  - Ön yüzde `RaporlarPage`'e yeni bir `Card` eklenmez; rapor `ServisPlanlamaPage` "Rapor" sekmesindedir (karar K-14). Böylece mevcut rapor ekranı değişmez.
- **Dosyalar:** `services/teknik_servis/raporlar.py`, `api/teknik_servis_planlama.py`, `pages/ServisPlanlamaPage.tsx`, `tests/integration/test_servis_plan_uyumu.py`.
- **Kabul:**
  - 22.10 planlı ve 22.10'da ilk kaydı olan iş "uyumlu", 23.10 kaydı olan "kaydı", kaydı olmayan "eksik" sayılır.
  - Eksik paydaya girmez.
  - Excel ve web toplamları eşittir.
  - Servis ve bakım ayrı satırlarda raporlanır.
  - Tahmini süre "gerçek" başlıklı kolonda geçmez.
- **Öncelik/Efor:** P3 · M
- **Bağımlılık:** E02-12, E09 (service_time_entries)
- **Canlı risk:** Yok. `services/reports.py` değiştirilmez.

### E02-23 · Kapanan planlı işler takvimde soluk ve salt okunur
- **Kaynak:** M02-D04
- **Canlı durum:** YOK
- **Yaklaşım:**
  - `GET /takvim` kapalı işlerin aktif planını **filtrelemez**, `kapali: true` bayrağıyla döner.
  - Kapalı işler çakışma motoruna aday olarak girmez (`WHERE status NOT IN KAPALI_DURUMLAR`).
  - Kartta `opacity: 0.5` uygulanır, "Planla" düğmesi gösterilmez.
  - KPI "planlı" ve "tamamlanan" olarak ayrılır (E02-06).
- **Dosyalar:** `services/teknik_servis/takvim.py`, `services/teknik_servis/cakisma.py`, `pages/ServisPlanlamaPage.tsx`, `tests/integration/test_servis_takvim.py`.
- **Kabul:**
  - Kapatılan iş plan gününde soluk kartla, "Planla" düğmesi olmadan görünür.
  - Çakışma sayısına dahil edilmez.
  - KPI'lar planlı ve tamamlanan olarak ayrı sayılır.
- **Öncelik/Efor:** P3 · S
- **Bağımlılık:** E02-02, E02-05
- **Canlı risk:** Yok

### E02-24 · Saha irtibat alanlarının rol bazlı API seviyesinde gizlenmesi (KVKK)
- **Kaynak:** M02-15
- **Canlı durum:** YOK. Emsal kalıp `sees_cost` → alanın yanıtta hiç yer almaması (`api/reports.py:41-55`, `api/deps.py:103-105`).
- **Yaklaşım:**
  - `irtibat_gorur(user, plan) = user.has("servis.irtibat_gor") or user.id in plan.uye_idleri` yardımcısı eklenir.
  - False ise şu alanlar takvim, ziyaret, saha önerisi ve Excel yanıtlarında **null** döner: `irtibat_adi`, `irtibat_telefon`, `acik_adres`. İl/ilçe görünür kalır; havuz gruplaması için gereklidir.
  - Kişisel veri okuma `audit.log(..., is_personal_data=True)` ile yalnız tek kayıt detayında loglanır; listelerde loglanmaz (canlı KVKK kalıbı `api/accounts.py:423`).
- **Dosyalar:** `api/teknik_servis_planlama.py`, `services/teknik_servis/takvim.py`, `tests/integration/test_servis_irtibat_gizliligi.py`.
- **Kabul:**
  - `servis.gor` olup `servis.irtibat_gor` olmayan YONETIM kullanıcısının takvim yanıtında telefon ve yetkili null döner.
  - Atanmış teknisyen ve SERVIS_SEF bu alanları görür.
  - Excel'de irtibat kolonu yalnız izinliye eklenir.
- **Öncelik/Efor:** P3 · S
- **Bağımlılık:** E02-05, E02-14
- **Canlı risk:** Yok

### E02-25 · Planlama uyarıları (yarın planı, bekleyen yaşlı iş, çakışmalı plan, göç tutarsızlığı)
- **Kaynak:** Proje geçmişi §"ERP içi geciken iş, yarın planı uyarıları"; envanter (OpsSuite yarın planlı uyarısı); M02-10 göç tespiti
- **Canlı durum:** YOK. Uyarı merkezi hesaplanan ve izne tabi kalıpla çalışıyor (`services/uyarilar.py:47-160`).
- **Yaklaşım:**
  - `topla()` içine `if user.has("servis.gor"):` bloğu eklenir. Bütün sayılar `kapsam_birim` ile süzülür, çünkü sayı da bir sızıntıdır.
  - Uyarılar:
    - `servis.yarin_plan` (bilgi; `/servis-planlama?gun=yarin`),
    - `servis.plan_bekleyen` (uyarı; `DEFAULTS["servis_plan_bekleyen_uyari_gun"]=3` günden eski havuz işi),
    - `servis.cakisma` (uyarı; önümüzdeki 7 gündeki gerekçesiz çakışmalı plan; normalde 0, göç verisinde dolu olabilir),
    - `servis.saat_belirsiz` (bilgi).
  - Yeni worker görevi açılmaz. İstenirse `worker.is_uyarilari` özet satırına (`worker.py:86-102`) servis sayıları eklenir (karar K-15).
  - `DEFAULTS` yeni blok:
    - `servis_plan_sure_min_dk: 15`
    - `servis_plan_sure_max_dk: 1440`
    - `servis_plan_varsayilan_sure_dk: 60`
    - `servis_toplu_islem_azami: 150`
    - `servis_bolge_oneri_gun: 3`
    - `servis_plan_bekleyen_uyari_gun: 3`
    - `servis_takvim_azami_gun: 62`
- **Dosyalar:** `services/uyarilar.py`, `services/settings.py`, `worker.py` (isteğe bağlı), `tests/integration/test_servis_uyarilar.py`.
- **Kabul:**
  - Yarın planlı 3 işi olan birim şefinin uyarı zilinde 3 görünür.
  - Başka birim şefinde 0 görünür.
  - `servis.gor` olmayan kullanıcıda blok yoktur.
  - Ayarlar ekranında yeni anahtarlar düzenlenebilir.
- **Öncelik/Efor:** P2 · S
- **Bağımlılık:** E02-05, E13
- **Canlı risk:** Düşük. `uyarilar.topla` ortak fonksiyondur. Önlem: blok yalnız `servis.gor` sahibinde koşar, mevcut blokların sırası ve kodu değişmez. Mevcut uyarı testleri koşulur.

---

## 7. Test planı (özet)

| Dosya | İçerik |
|---|---|
| `tests/unit/test_servis_cakisma.py` | Örtüşme, ziyaret istisnası, şef sahada/değil, saat belirsiz, araç, müsaitlik (DB'siz, saf fonksiyon katmanı) |
| `tests/unit/test_servis_lokasyon_anahtari.py` | İ/ı, çoklu boşluk, adres önceliği |
| `tests/unit/test_permissions.py` | Otomatik: yeni izinler role atanmış, `maliyet.gor` kümesi sabit |
| `tests/unit/test_statemachine.py` | Otomatik: SERVIS_IS_EMRI geri alma geçişleri |
| `tests/unit/test_on_yuz_kisisel_veri.py` | Gömülü kişi adı yok |
| `tests/integration/test_servis_planlama_*.py` | Her uç için 403/200; kapsam testi (başka birim → 404 **ve** `db.refresh` ile değişmemiş); kapalı iş 400 + değişmemiş; tek transaction (hata enjekte → üye satırı yok); eşzamanlılık (iki oturum) |
| `tests/integration/test_servis_irtibat_gizliligi.py` | Alan yanıtta null |
| `tests/integration/test_servis_takvim_xlsx.py` | Excel satır = web toplamı; kapsam |
| `tests/migration/test_migration_zinciri.py` | head→base→head; EXCLUDE sayısı; sequence düşürme |
| `tests/migration/test_altin_kayit.py` | 932 iş / 552.825,00 TL yeşil (mobilite dokunulmadı kanıtı) |

Her adım sonunda `make test`, `ruff`, `npm run build` ve `oxlint` çalıştırılır.

## 8. Uygulama sırası (öncelik kararıyla uyumlu)

1. **P1 çekirdek:** E02-01 → E02-02 → E02-03 → E02-04 → E02-05 → E02-06 → E02-07 → E02-08 (kullanıcının doğruladığı işlevler ilk dilimde).
2. **P2 yeni özellik:** E02-12 → E02-13 → E02-14 → E02-15 → E02-16; ardından eksikler E02-09, E02-10, E02-11, E02-17, E02-19, E02-25.
3. **P3:** E02-20 → E02-21 → E02-22 → E02-23; güvenlik sıkılaştırma E02-24, E02-18.

## 9. Kararlar (kullanıcıya soru sorulmadı; gerekçeli)

- **K-01 Personel = `User` (+ `user_units`).** Canlı sistemde ayrı personel tablosu yok. Ayrı bir `personnel` tablosu kullanıcıyla ikinci kimlik kaynağı yaratır; eski sistemdeki isim eşleşmesi hatası (M02-03) tam olarak bundan doğmuştu. Sahaya çıkan teknisyen "Ziyaretlerim" için zaten oturum açacak. Giriş yapmayan personel için `is_active=True`, MFA kurulmamış ve parolası atanmamış kullanıcı açılabilir.
- **K-02 Mobilite `work_orders.scheduled_at` ve `vehicles` kullanılmaz.** Hak ediş zinciri ve müşteri aracı anlamı bozulmasın diye servis planı ve servis aracı ayrı tablolarda tutulur. Köprü yalnız salt-okunur FK'dir.
- **K-03 Ziyaret ayrı tablo (`service_visits`), numarası SEQUENCE.** Serbest metin `RouteGroupNo` ayrılmış işlerin habersiz taşınmasına yol açıyordu (denetim M02-01). count/max+1 numara eşzamanlılıkta çakışır (00 rehberi gözlemi).
- **K-04 Çakışma = uyarı + gerekçeyle geçme; yetki `servis.planla` sahibinde.** Ayrı `override` izni açılmadı. Denetçi önerisi böyleydi ve sert red şefin günlük planını yöneticiye bağlardı. Sert engel gerekirse yeni bir izinle kolayca daraltılabilir.
- **K-05 Lokasyon/şehir gruplama anahtarı yalnız sunucuda üretilir.** İstemci ve sunucu normalizasyonunun ayrışması (İ/ı hatası) mimari olarak imkânsız hale gelir. Mevcut `tr_normkey` yeniden kullanılır.
- **K-06 Çakışma hesabı birim kapsamını aşar, yanıt aşmaz.** Birimler arası çakışma yakalanmalı (M02-09). Ancak başka birimin müşteri adı ve iş numarası kapsam dışı kullanıcıya maskelenir, aksi bir kapsam sızıntısı olurdu.
- **K-07 Şef yalnız kendi biriminin personelini atar (birimler arası paylaşım = çoklu `user_units` üyeliği).** Personel paylaşımı sorusu cevapsız. Çoklu üyelik bunu yetki genişletmeden çözer: paylaşılan teknisyen iki birime üye yapılır.
- **K-08 Plansız işe ekip atanabilir (sorumlu).** Eski toplu atama "planı değiştirmeden" çalışıyordu ve kullanıcı bunu doğruladı. Plansız işte ekip, E01'deki sorumlu atama alanına yazılır; plan açılınca ekibe öneri olur.
- **K-09 Plan satırları değişmez (append-only).** Geri alma ve erteleme yeni satır veya `cancelled_at` ile izlenir. Plan geçmişi ve erteleme raporu ancak böyle güvenilir olur. Nedenler olay geçmişinde ve yeni plan satırında tutulur.
- **K-10 Araç havuzu `service_vehicles`, birim NULL = ortak havuz, isteğe bağlı zimmet.** Araç sayısı ve zimmet sorusu cevapsız. Bu model üç olasılığı da (birime bağlı, ortak, kişiye zimmetli) kolon değişikliği olmadan karşılar. Plaka planda zorunlu değil.
- **K-11 Müsaitlik türlerinde "sağlık raporu" ayrı tür değil (IZIN altında).** KVKK m.6 özel nitelikli veri (sağlık) toplanmasını önler. Planlama için "müsait değil" bilgisi yeterlidir. Girişi şef ve yönetici yapar; İK kapsam dışıdır.
- **K-12 Takvim için yeni ön yüz kütüphanesi eklenmez.** AntD ve dayjs yeterli. Bağımlılık yüzeyi ve CSP (`main.py:163-180`) değişmez.
- **K-13 Harita bağlantısı API anahtarsız Google Maps arama URL'si, yalnız tıklanınca.** Sunucudan üçüncü tarafa veri gitmez. Adres yalnız kullanıcının tıklamasıyla tarayıcıdan açılır.
- **K-14 Plan uyum raporu planlama ekranında, canlı Raporlar sayfası değiştirilmez.** Mevcut rapor ekranına ve testlerine dokunmamak için. E12 (raporlama) birleşik rapor sayfasını sonra toplar.
- **K-15 Yeni worker görevi yok.** Planlama uyarıları hesaplanır ve saklanmaz (uyarı merkezi ilkesi). PB üretimi E04'ün worker işidir.
- **K-16 Standart saha mesaisi ve hafta sonu bilinmiyor.** İlk sürümde hafta sonu planı serbesttir; "plan doluluğu" metriği rapora konmaz. Saat varsayılanı yalnız formda 09:00 olarak önerilir, sunucuda varsayılan uygulanmaz. Saati boş plan "saat belirsiz" sayılır.
- **K-17 Plana uyum = aynı takvim günü (Europe/Istanbul).** Saat toleransı tanımı yok. Gün bazlı ölçüm tahmin içermez; tolerans sonra ayar anahtarı olarak eklenebilir.
- **K-18 Eski bozuk kayıtlar (kapalıyken yeniden planlanmış, çift aktif plan) göçte otomatik düzeltilmez.** Raporlanır ve uyarı merkezinde görünür; düzeltme insan kararıdır (00 rehberi: uydurma veri yazılmaz).
- **K-19 Depo/Muhasebe/Yönetim rolleri saha irtibatını görmez.** Bu rollerin `servis.irtibat_gor` izni yok; gerekirse rol düzenleme ekranından kişi bazlı istisna verilebilir (`UserPermission`).
- **K-20 Erteleme neden listesi tasarımdaki 7 kod.** Liste CHECK + tuple ile sabittir. Değişiklik migration gerektirir; bu, rapor kırılımlarının tutarlılığı için bilinçli bir tercihtir.
- **K-21 E02-01 (tek aktif plan) P2'den P1'e çekildi.** Yeni tabloda kısmi tekil indeks sıfır ek maliyetle doğar ve geri alma/erteleme maddelerinin doğruluk ön koşuludur.
