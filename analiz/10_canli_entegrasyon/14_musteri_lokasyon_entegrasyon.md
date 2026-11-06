# E14 — Müşteri, Lokasyon, Saha ve Sözleşme Ana Verisi: Canlı ERP Entegrasyon Tasarımı

> Tarih: 21.10.2026 · Hedef: **Denge Mobilite ERP** (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdi: `analiz/02_moduller/_ozet/14_musteri_lokasyon.json` (17 onaylı madde, 5 ret), `14_musteri_lokasyon_tasarim.md`, `14_musteri_lokasyon_denetim.md`, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`, komşu entegrasyon belgeleri E01, E02, E03, E04, E06, E09, E12.
> Bağlayıcı rehber: `00_MIMARI_KURALLAR.md`. Kaynak koda dokunulmadı; yalnız okundu. Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köklerine göredir ve 21.10.2026'da kod okunarak doğrulandı.
> Madde kimlikleri `E14-NN`; kaynak madde kimlikleri `M14-xx` olarak yazıldı.

---

## 0. Özet

1. **Ayrı müşteri/lokasyon tablosu AÇILMAZ.** Eski tasarımın `Customers / CustomerSites / CustomerContacts / CustomerAliases` dörtlüsünün üçü canlıda zaten var:
   - Müşteri = `accounts` (`Account(is_musteri=True)`, `models/account.py:53-130`). Bayrak seti, `title_key` + `pg_trgm` indeksi (`:66`), `SourceMixin` + `uq_accounts_kaynak` (`:68`), iyimser kilit, yumuşak silme, denetim izi, kapsam (`services/accounts.py:11-61`), mükerrer aday ucu (`api/accounts.py:371-387`) ve Excel içe aktarma profili (`services/imports/hesap.py`) hazır.
   - İrtibat = `contacts` (`models/account.py:163-174`). Ekleme, güncelleme ve silme uçları denetim izine `is_personal_data=True` ile yazıyor (`api/accounts.py:147-245`).
   - Lokasyon/tesis = `addresses` (`models/account.py:177-187`). Tablo var ama **hiç API ucu yok**; yalnız teklif PDF'i ilk satırı okuyor (`services/belgeler.py:150-152`). Bu modül `addresses`'i nullable kolonlarla "servis lokasyonu"na genişletir.
   - Takma ad tablosu YOK → tek yeni ana tablo `account_aliases`.
2. **Birleştirme mantığı canlıda VAR ama yalnız komut satırı betiği.** `migration/hesap_birlestir.py` önizleme/uygulama yapıyor, `accounts`'a bakan FK'leri şemadan okuyor (`:116-128`), kaynak kaydı yumuşak siliyor, tek transaction. Bu mantık `services/hesap_birlestir.py`'ye taşınır, API ve ekran ondan beslenir; betik aynı servisi çağırır. Hak ediş zincirine dokunan hesaplar ekrandan birleştirilemez.
3. **Servis kayıtlarının müşteri/lokasyon bağları** (servis işi, plan, ekipman, sözleşme, kiralama, atölye, teklif) E01/E02/E03/E04/E05/E06/E07 tablolarında tanımlı. Bu modül o bağların **ortak kurallarını** koyar: müşteri `is_musteri`, lokasyon aynı müşteriye ait ve aktif, FK `accounts RESTRICT / addresses SET NULL`, göç kayıtlarında ham metin korunur, eşleştirme yalnız onaylı satırla yapılır.
4. **Mobilite akışı korunur.** `work_orders / work_order_items / settlements` zincirine yazılmaz. Canlı uçlarda yalnız iki küçük ve geriye uyumlu değişiklik var:
   - `POST/PATCH /api/hesaplar`'a VKN çakışma uyarısı (409 + onayla geç).
   - Çıktıya `is_verified` alanı.
   Teklif PDF'inin adres seçimi tesis satırını atlar.
5. **Yetki:** Yeni izinler `hesap.birlestir` ve `lokasyon.yaz`. Teknisyen ve atölye rollerine `hesap.gor` VERİLMEZ (KVKK, M14-01-ROL reddi). Bu roller müşteriyi yalnız atandıkları servis işi üzerinden ve hafif arama ucundan (ad + il, irtibat ve VKN olmadan) görür.
6. **Kullanıcının bizzat doğruladığı işlevler korunur:**
   - Tıklanabilir KPI kutuları: E14-18 (veri kalitesi paneli).
   - Toplu planlama/atama: E14-06 (havuz gruplaması lokasyon kimliğine geçer, toplu planda farklı lokasyon uyarısı).
   - Excel dışa aktarım: E14-09 (eşleştirme aday listesi) ve E14-18.
   - Cihaz başına PB iş emri: E14-10 (PB üretiminde tesis ve ekipman eşleşmesi; 1 cihaz = 1 PB kuralı E04'teki `uq_so_pb_cihaz_donem` ile).

---

## 1. Canlı karşılık taraması

| Konu | Canlıda ne var | Kanıt | Sonuç |
|---|---|---|---|
| Müşteri ana kaydı | `accounts`, bayrak seti, `title_key`, trgm indeksi, `tax_no` indeksi (tekil DEĞİL), `is_active`, `parent_dealer_id` | `models/account.py:53-130` | VAR, genişletilecek |
| Müşteri CRUD + kapsam | Liste/getir/oluştur/güncelle; `_kapsamli_hesap` ile kapsam; PATCH'te `version` | `api/accounts.py:30-49, 60-108, 390-464` | VAR |
| Müşteri silme ucu | YOK (yalnız KVKK anonimleştirme) | `api/accounts.py` (DELETE yok), `services/kvkk.py:217-302` | VAR (kural zaten sağlanıyor) |
| VKN tekilliği | YOK; yalnız `ix_accounts_tax_no` | `models/account.py:67` | YOK |
| Mükerrer ad adayı | `mukerrer_adaylari()` (trgm benzerliği, eşik 0,45) | `services/accounts.py:84-106`, `api/accounts.py:371-387` | VAR (aday üretir, engellemez) |
| Unvan normalleştirme | `tr_normkey` yalnız Türkçe katlama + boşluk; `A.Ş./LTD. ŞTİ.` eklerini atmaz | `services/normalize.py:119-133` | KISMEN |
| "Doğrulanmamış" kayıt kavramı | YOK | — | YOK |
| İrtibat | `contacts` + uçlar + denetim (`is_personal_data=True`), tek birincil kuralı | `api/accounts.py:111-245` | VAR; lokasyon bağı YOK |
| Lokasyon/tesis | `addresses` (label 40 kr., line NOT NULL, district, city, is_primary); **API ucu yok** | `models/account.py:177-187`; Grep: yalnız `services/belgeler.py:151` | KISMEN |
| Takma ad | YOK | — | YOK |
| Birleştirme | Komut satırı betiği; FK'leri şemadan okur; önizleme; tek transaction | `migration/hesap_birlestir.py:116-223` | KISMEN (API/ekran/takma ad/kayıt yok) |
| Excel içe aktarma çerçevesi | Profil + parti + karantina + karar; profil izni modülün yazma iznine bağlı | `services/imports/__init__.py`, `cekirdek.py:90`, `api/imports.py:82-282` | VAR, yeni profil eklenecek |
| Excel dışa aktarma | `satirlari_xlsx_async`, formül enjeksiyonu korumalı | `services/export.py:26, 45` | VAR |
| Denetim izi | `audit.log / log_change`; denetim API'si yalnız GET (değiştirilemez) | `services/audit.py:26-92`, `api/audit_api.py:17` | VAR |
| Kişisel veri okuma logu | `kvkk.erisim_kaydet` | `services/kvkk.py:40-66` | VAR |
| KVKK anonimleştirme | `accounts, contacts, vehicles`; **addresses ve takma adlar kapsam dışı** | `services/kvkk.py:30, 217-302` | KISMEN |
| Dışa aktarım denetimi | Rapor Excel'leri denetime yazılmıyor | `api/reports.py:30` | YOK |
| Hesap kartı | Kişiler, siparişler, cihazlar, araçlar, abonelikler, belgeler, görevler | `api/accounts.py:248-368`, `pages/HesaplarPage.tsx:396-700` | KISMEN (servis sekmeleri yok) |
| Uyarı merkezi | `hesap.gor` bloğu yalnız montaj noktası eksikleri | `services/uyarilar.py:166-190` | Genişletilecek |
| Rol kapsamı doğrulama | `api/users.py:181, 225` sabit `(SCOPE_ALL, SCOPE_OWN_CUSTOMERS)` | `api/users.py:73-75, 181, 225` | E13/E01'de değişiyor |
| Teklif müşterisi | `quotes.customer_id` FK (zorunlu) | `models/quote.py:74` | VAR; kaynak servis işi bağı E07'de |
| Servis tabloları (`service_orders`, `service_equipment`, `maintenance_contracts`, `rentals`, `workshop_records`, `service_plans`) | Canlıda YOK; E01–E07'de tasarlandı (`customer_id/account_id`, `address_id`, `contact_id`) | E01 §2.2, E03 §2, E04 §2.1, E06 | Bu modül ortak kuralları bağlar |

Sonuç: Müşteri ve irtibat tarafının **altyapısı büyük ölçüde VAR**. Eksik olanlar şunlar:
- lokasyonun servis için kullanılabilir hâle gelmesi;
- takma ad ve onaylı eşleştirme;
- ekrandan birleştirme;
- doğrulanmamış kayıt kavramı;
- servis kayıtlarının bu ana veriye kurallı bağlanması.

---

## 2. Bağımlılıklar

| Kod | Bu modülün ondan beklediği | Yoksa ne olur |
|---|---|---|
| **E13** RBAC + birim | `BIRIMLER`, `SCOPE_OWN_UNITS`, `user_units`, `services/teknik_servis/kapsam.py` (`kapsam_birim`, `birim_disinda_mi`), roller `SERVIS_YONETICI / SERVIS_SEF / SERVIS_OPERASYON / SERVIS_TEKNISYEN / ATOLYE` | E14-01..03 yalnız izinle çalışır; servis kartı sekmelerindeki birim filtresi E13 ile gelir. |
| **E01** Servis iş emri | `service_orders.customer_id / address_id / contact_id`, `service_order_events` (`DUZELTME`), `PATCH /isler/{id}` (E01-13) | E14-05, E14-13, E14-17 bloke. |
| **E02** Planlama | Havuz ve toplu planlama servisi, plan saha alanları | E14-06 ve plan ön dolumu (E14-05) bloke. |
| **E03** Kurulu ekipman | `service_equipment.account_id / address_id / customer_name_raw / location_raw / contact_name_raw` | E14-09 Faz 1 (ekipman) ve E14-10 bloke. |
| **E04** Bakım sözleşmesi | `maintenance_contracts.account_id / address_id` + bu modülün istediği `customer_name_raw`, `site_name_raw` | E14-09, E14-10, E14-11 bloke. |
| **E05 / E06 / E07** | Atölye, kiralama, teklif kayıtlarında `account_id / address_id` | E14-14, E14-15 bloke. |
| **E10 / E12** | Rapor gruplama ve KPI'lar | E14-18'de yalnız boyut ve veri kalitesi göstergesi bu modülde kalır. |

Uygulama sırası (rehber §6.4 ile uyumlu):
1. E13 (RBAC + birim).
2. **E14-01, E14-02, E14-03, E14-04**. Ana veri, E01'den ÖNCE gelir; çünkü servis işi açılışı lokasyon seçimine dayanır.
3. E01 + E14-05, E14-13.
4. E02 + E14-06.
5. E03/E04 + E14-08 → E14-09 → E14-10, E14-11.
6. E14-12 (birleştirme), E14-14, E14-15, E14-16.
7. E14-17, E14-18.

---

## 3. Veri modeli

Model dosyası: `backend/app/models/account.py`'deki mevcut sınıflara kolon eklenir. Yeni sınıflar aynı dosyaya eklenir; ayrı müşteri modeli açılmaz. Hepsi `models/__init__.py` `__all__` listesine eklenir. Migration: `make makemigration m="servis_musteri_lokasyon_ana_veri"`; bağlandığı head, kodlama günü `alembic heads` ile doğrulanır (rehberde `b30e012dd879`). Migration başına NEDEN ve bedel açıklaması yazılır. Var olan tablolara yalnız nullable ya da `server_default`'lu kolon eklenir. Var olan CHECK/EXCLUDE kısıtlarına dokunulmaz.

### 3.1 `accounts` — genişletme (canlı tablo, geriye uyumlu)

| Kolon | Tip | Not |
|---|---|---|
| `is_verified` | Boolean NOT NULL `server_default true` | Var olan tüm hesaplar doğrulanmış sayılır; mobilite davranışı değişmez. Hızlı eklenen müşteri `false` doğar. |
| `verified_at` / `verified_by` | timestamptz NULL / FK users SET NULL | Doğrulama anı (Clock) ve kişi. |
| `dis_referans` | String(40) NULL | Muhasebe cari kodu. **Yalnız metindir, entegrasyon değildir.** İndeks: `ix_accounts_dis_referans`. |
| `merged_into_id` | FK accounts SET NULL | Ekrandan birleştirilen kaynak kaydın hedefi. `ck_accounts_birlesen_silinmis`: `merged_into_id IS NULL OR is_deleted`. `ck_accounts_kendine_birlesemez`: `merged_into_id <> id`. 23.09.2026 betikle birleştirilen 5 kayıt NULL kalır; notlarında hedef numarası zaten var (`hesap_birlestir.py:221-222`). |

**VKN için tekil indeks AÇILMAZ** (bkz. Karar K6). Kontrol servis katmanındadır: `vkn_cakismasi()` 409 döndürür; onay ve gerekçe verilirse kayıt açılır.

### 3.2 `addresses` — servis lokasyonuna genişletme

Ayrı `sites` tablosu açılmaz. `addresses` satırı `kind='TESIS'` olduğunda servis lokasyonudur.

| Kolon | Tip | Not |
|---|---|---|
| `kind` | String(10) NOT NULL `server_default 'MERKEZ'` | `ADRES_TURLERI = ('MERKEZ','FATURA','SEVK','TESIS')`, `ck_addresses_tur`. Var olan satırlar MERKEZ olur. |
| `site_name` | String(200) NULL | Tesis adı (örn. "PİAZZA İSTANBUL AVM"). `label` 40 karakterlik "Merkez" etiketi olarak kalır. `ck_addresses_tesis_adi`: `kind <> 'TESIS' OR site_name IS NOT NULL`. |
| `site_key` | String(200) NULL | `normalize.unvan_anahtari(site_name)`; ORM `before_insert/before_update` olayıyla doldurulur (`models/account.py:193-196` emsali). `ix_addresses_tesis_trgm` (GIN `gin_trgm_ops`). |
| `line` | Text **NULL'a çevrilir** | Hızlı eklemede yalnız ad ve il bilinir; uydurma adres yazılmaz. Eski kural tesis dışı satırlar için korunur: `ck_addresses_satir`: `kind = 'TESIS' OR line IS NOT NULL`. Var olan satırların hepsi dolu olduğu için kısıt sorunsuz kurulur. |
| `access_note` | Text NULL | Bina/kat, ulaşım, giriş kuralı (E02 plan formu bunu okur). |
| `primary_contact_id` | FK contacts SET NULL | Lokasyonun birincil irtibatı. Servis katmanı irtibatın aynı hesaba ait olduğunu doğrular. |
| `is_active` | Boolean NOT NULL `server_default true` | Pasif lokasyon yeni kayıtta seçilemez (400); eski kayıtlar bağlı kalır. **SoftDeleteMixin eklenmez**: `services/belgeler.py:151` silinmiş filtresi yazmıyor ve silme ucu zaten açılmayacak. |
| `is_verified` | Boolean NOT NULL `server_default true` | Hızlı eklenen tesis `false`. |
| `created_by / updated_by` | `ActorMixin` | |
| `version` | `VersionedMixin` | PATCH'te iyimser kilit. `server_default 1` ile var olan satırlar kilitlenmez. |
| `source_system / source_ref` | `SourceMixin` + `uq_addresses_kaynak` | Tesis göçü tekrar koşulabilir. |
| indeksler | `ix_addresses_hesap_tur (account_id, kind, is_active)` | |

### 3.3 `contacts` — lokasyon bağı

| Kolon | Tip | Not |
|---|---|---|
| `address_id` | FK addresses SET NULL, NULL | İrtibatın bağlı olduğu tesis. NULL = hesap geneli. `ix_contacts_adres`. |

Tek birincil kuralı hesap düzeyinde aynen kalır (`api/accounts.py:131-144`). Tesis düzeyindeki birincil kişi `addresses.primary_contact_id` ile tutulur.

### 3.4 `account_aliases` — takma ad (YENİ)

`PkMixin, TimestampMixin, ActorMixin`. Kayıt değiştirilmez; yalnız eklenir ve silinir (silme denetime yazılır). Tablonun dışarıya FK'si yalnız `accounts`, `addresses` ve `users` olduğundan, ayrıca `_TRUNCATE` listesine eklenmesi GEREKMEZ (`accounts` listede; CASCADE yeter). Kodlama günü `tests/conftest.py:35-44` ile teyit edilir.

| Kolon | Not |
|---|---|
| `account_id` | FK accounts CASCADE NOT NULL. Birleştirmede FK otomatik taşınır. |
| `address_id` | FK addresses SET NULL. Doluysa ad tesise işaret eder. Servis katmanı `address.account_id = account_id` koşulunu doğrular. |
| `alias_text` | String(250); ham yazım ("AKYAKA PARK AVM") |
| `alias_key` | String(250); `unvan_anahtari(alias_text)`. **`uq_account_aliases_anahtar (alias_key)` global tekil.** Bir yazım yalnız bir hedefe gider; eşleştirme bu sayede deterministik kalır. Çakışma 409 verir ve mevcut hedefi döndürür. `ix_account_aliases_trgm` GIN. |
| `kaynak` | `TAKMA_AD_KAYNAKLARI = ('ELLE','ESLESTIRME','BIRLESTIRME','GOC')`, `ck_account_aliases_kaynak` |
| `kaynak_tablo` | String(40) NULL (örn. `maintenance_contracts.customer_name_raw`) |

### 3.5 `account_merges` — birleştirme kaydı (YENİ, değişmez)

`PkMixin, TimestampMixin, ActorMixin`. API'de güncelleme ve silme ucu yoktur.

| Kolon | Not |
|---|---|
| `tur` | `('HESAP','LOKASYON')`, `ck_account_merges_tur` |
| `kaynak_id`, `hedef_id` | BigInteger. FK yoktur, çünkü tür polimorfiktir. `ck_account_merges_farkli`: `kaynak_id <> hedef_id` |
| `gerekce` | Text NOT NULL, `ck_account_merges_gerekce`: `length(trim(gerekce)) >= 5` |
| `onizleme` | JSONB `{tablo.kolon: adet}`; uygulamadan önce kullanıcıya gösterilen sayılar |
| `tasinan` | JSONB `{tablo.kolon: adet}`; gerçekte güncellenen satırlar |
| `doldurulan_alanlar`, `eklenen_roller` | JSONB |

FK yalnız `users`'a gittiği için tablo `tests/conftest.py` `_TRUNCATE` listesine eklenir.

### 3.6 Diğer modüllerin tablolarına bu modülün koyduğu ortak kural (koordinasyon)

| Tablo (sahibi) | Müşteri kolonu | Lokasyon kolonu | Ham metin (göç izi) | Kural |
|---|---|---|---|---|
| `service_orders` (E01) | `customer_id` RESTRICT NOT NULL | `address_id` SET NULL | **E14 ister:** `customer_name_raw` String(250), `location_raw` Text (yalnız göç) | Yeni kayıtta `customer_id` hesabı `is_musteri` ve `is_active` olmalıdır, `address_id` aynı hesaba ait ve aktif olmalıdır; aksi 400. |
| `service_order_events` (E01) | — | — | — | Müşteri/lokasyon düzeltmesi `DUZELTME` olayı olarak yazılır (E14-13). |
| `service_plans` (E02) | (işten) | `address_id` + saha alanları | — | Plan formu lokasyondan ön dolar. Plan alanı değişince lokasyon kaydı DEĞİŞMEZ; ancak "lokasyon kaydını da güncelle" kutusu işaretliyse `lokasyon.yaz` ile güncellenir. |
| `service_equipment` (E03) | `account_id` RESTRICT NULL (satın alan/sahip) | `address_id` SET NULL (kurulu yer) | `customer_name_raw`, `location_raw`, `contact_name_raw` (E03'te var) | Eşleşmeyen satır NULL kalır; uydurma bağ kurulmaz. |
| `maintenance_contracts` (E04) | `account_id` RESTRICT (sözleşme tarafı = cari) | `address_id` SET NULL (tesis) | **E14 ister:** `customer_name_raw`, `site_name_raw` | `account_id` yalnız `TEYIT_BEKLIYOR` durumunda NULL olabilir: `ck_mc_musteri_teyit`: `account_id IS NOT NULL OR status = 'TEYIT_BEKLIYOR'`. |
| `rentals` + irtibatlar (E06) | `account_id` | `address_id` + `lokasyon_metni` (E06'da var) | — | E14-15 |
| `workshop_records` (E05) | `account_id` | — | `firma_metni` | E14-14, E14-15 |
| `quotes` (canlı + E07) | `customer_id` (canlı) | **E14 ister:** `address_id` SET NULL nullable | — | Servis işinden açılan teklifte `customer_id` ve `address_id` **sunucuda** işten kopyalanır (E14-15). |

Bütün bu FK'ler canlı birleştirme servisinin `referans_kolonlari()` sorgusunca otomatik görülür (`hesap_birlestir.py:116-128`). Bu yüzden yeni tablo eklendiğinde birleştirme eksik kalmaz.

### 3.7 `services/normalize.py` — yeni fonksiyon

`unvan_anahtari(ham) -> str` şunları yapar:
- `tr_normkey` uygular;
- noktalama işaretlerini atar;
- `A.Ş./ANONİM ŞİRKETİ`, `LTD. ŞTİ./LİMİTED ŞİRKETİ`, `SAN. VE TİC.`, `TİC.`, `SAN.` eklerini atar;
- çoklu boşluğu teke indirir.

Doctest örneği: `G4S ELEKTRONİK SİSTEMLERİ A.Ş.` ile `G4S Elektronik Sistemleri Anonim Şirketi` aynı anahtarı üretir. **`tr_normkey` ve `accounts.title_key` DEĞİŞMEZ**: mobilite araması ve içe aktarma onlara bağlı.

---

## 4. İzinler, kapsam, roller

### 4.1 Yeni izin kodları (`permissions.py` PERMISSIONS, modül "Hesaplar")

| Kod | Açıklama | Roller |
|---|---|---|
| `hesap.birlestir` | Mükerrer hesap/lokasyonu birleştirir, takma ad yönetir, eşleştirme dosyasını uygular, hızlı açılan müşteri ve tesisi doğrular | ADMIN (otomatik), **SERVIS_YONETICI** |
| `lokasyon.yaz` | Servis lokasyonu (tesis) ve lokasyon irtibatı açar, düzenler, pasifler; servis işi açılışında hızlı müşteri/tesis ekler | ADMIN (otomatik), **SERVIS_YONETICI, SERVIS_SEF, SERVIS_OPERASYON** |

Okuma için yeni izin açılmaz:
- Lokasyon, irtibat ve kart `hesap.gor` ile okunur.
- Hafif arama uçları (yalnız ad, il, tesis adı ve doğrulama durumu) `servis.gor` ile çalışır.

### 4.2 Rol tablosuna düzeltme (E01 §3.3 ve E13 ile koordine)

- **`SERVIS_TEKNISYEN` ve `ATOLYE` rollerinden `hesap.gor` ÇIKARILIR.** E01 tablosu bu izni veriyordu. M14-01-ROL reddi bunu yasaklıyor: `hesap.gor` tüm müşterileri, irtibatları, VKN ve IBAN'ı açar (`api/accounts.py:60-108, 248-368`). Teknisyen irtibatı yalnız atandığı işin detayında görür (E01 `is_erisimi_yok_mu` + K11 maskeleme). Müşteri seçimi gerektiğinde `servis.gor` ile hafif arama ucunu kullanır.
- `SERVIS_SEF` ve `SERVIS_OPERASYON`: `hesap.gor` korunur, `lokasyon.yaz` eklenir. Hesabın mali alanları (IBAN, VKN, temsilci) için `hesap.yaz` YALNIZ `SERVIS_OPERASYON` ve `SERVIS_YONETICI`'de kalır (E01 tablosu).
- **Mevcut rollerin izin listesi DEĞİŞMEZ.** ADMIN yeni izinleri otomatik alır (`permissions.py:90`). YONETIM yalnız `.gor` alır, yeni `.gor` izni olmadığı için bir şey değişmez (`:84, 247`). `maliyet.gor` kümesi değişmez.
- `ozellestirildi=True` DB rollerine yeni izin otomatik inmez (`models/rbac.py:64-69`). Yayın notunda yazılır.
- Unit test (`tests/unit/test_permissions.py:43-46`): iki yeni iznin en az bir role atanmış olması.

### 4.3 Kapsam

- **Müşteri kaydının kendisi birime bağlı DEĞİLDİR** (tek ortak müşteri listesi; Karar K9). Hesap listesi ve kartı canlıdaki `kapsam_uygula` / `_kapsamli_hesap` (`services/accounts.py:11-21`, `api/accounts.py:30-49`) ile süzülür.
- **Servis kartı sekmeleri** (servis işleri, sözleşmeler, ekipman, kiralama, atölye) ve sayıları ayrıca `kapsam_birim` uygular. Sayı da sızıntı olduğu için sayılar da birime göre süzülür.
- **Lokasyon uçları:**
  - Liste: `kapsam_musteri(stmt, user, Address.account_id)`.
  - Tek kayıt: `kapsam_disinda_mi(db, user, address.account_id)` → 404. Kontrol yazmadan ÖNCE yapılır; emsal `test_kapsam_guvenligi.py:49-56`.
- **Ekler:** Tesis krokisi/fotoğrafı için `EK_SAHIPLERI`'ne `addresses` eklenir (`models/attachment.py:31-42`). `SAHIP_IZNI`: `addresses → (hesap.gor, lokasyon.yaz)`. `_kapsam` (`api/attachments.py:91-114`) `addresses` için hesabın kapsamını uygular.

---

## 5. Servis ve API katmanı

### 5.1 Dosyalar

```
backend/app/models/account.py                     (kolonlar + AccountAlias, AccountMerge)
backend/app/services/normalize.py                 (+ unvan_anahtari)
backend/app/services/accounts.py                  (+ vkn_cakismasi, benzer_unvanlar)
backend/app/services/hesap_birlestir.py           (YENİ; migration/hesap_birlestir.py mantığı buraya taşınır)
backend/app/services/teknik_servis/ana_veri.py    (YENİ: hizli_musteri, lokasyon_dogrula, kapsam_bilgisi, saha_onerisi, tesis_eslestir)
backend/app/services/teknik_servis/veri_kalitesi.py (YENİ: göstergeler, aday listeleri)
backend/app/services/imports/musteri_eslestirme.py  (YENİ profil) + __init__.py PROFILLER/PROFIL_IZINLERI
backend/app/api/lokasyonlar.py                    (YENİ, prefix /api/lokasyonlar)
backend/app/api/teknik_servis_ana_veri.py         (YENİ, prefix /api/teknik-servis/ana-veri)
backend/app/api/accounts.py                       (VKN uyarısı, is_verified çıktısı, dogrulanmamis filtresi — geriye uyumlu)
backend/app/main.py                               (iki router elle eklenir, :182-209)
backend/app/migration/hesap_birlestir.py          (servis fonksiyonlarını çağıracak şekilde inceltilir)
frontend/src/api/anaVeri.ts
frontend/src/components/MusteriLokasyonSecici.tsx, BirlestirmePenceresi.tsx, LokasyonPenceresi.tsx
frontend/src/pages/HesaplarPage.tsx                (Lokasyonlar + Servis sekmeleri, Doğrulanmamış etiketi/filtresi)
frontend/src/pages/ServisAnaVeriPage.tsx           (YENİ, /servis/ana-veri)
```

### 5.2 Servis fonksiyonları (yalnız `flush`, commit API'de; saat `Clock`)

- `accounts.vkn_cakismasi(db, tax_no, haric_id) -> list[Account]`: aynı VKN'li, silinmemiş ve aktif hesaplar.
- `accounts.benzer_unvanlar(db, unvan, *, esik)`: önce `unvan_anahtari` tam eşleşmesi, sonra `title_key` trgm benzerliği (mevcut `mukerrer_adaylari` sorgusu yeniden kullanılır) ve `account_aliases.alias_key` eşleşmesi.
- `ana_veri.hizli_musteri(db, girdi, user, clock) -> (Account, Address|None)`:
  - Girdi: `unvan`, `il`, opsiyonel `tesis_adi` ve `onay_benzer`.
  - `Account(is_musteri=True, is_verified=False, region=il)` açar.
  - `tesis_adi` varsa `Address(kind='TESIS', site_name, city=il, is_verified=False)` açar.
  - Benzer kayıt varsa ve `onay_benzer` false ise `AnaVeriHatasi(409, adaylar)` verir.
- `ana_veri.lokasyon_dogrula(db, customer_id, address_id, contact_id)`: servis kayıtlarının ortak doğrulayıcısı. 400 verdiği durumlar:
  - hesap `is_musteri` değil, pasif ya da silinmiş;
  - adres başka hesaba ait ya da pasif;
  - kişi başka hesaba ait.

  E01, E03, E04, E05, E06 ve E07 bu fonksiyonu çağırır; kural tek yerde kalır.
- `hesap_birlestir.onizle(db, tur, kaynak_id, hedef_id)` / `uygula(db, ..., gerekce, user, clock)`:
  - Hesap için `confrelid='accounts'`, lokasyon için `confrelid='addresses'` FK'leri şemadan okunur.
  - `EK_BAGLAR` (attachments, `devices.current_customer_id`) aynen korunur.
  - Kaynak `is_deleted=True`, `merged_into_id=hedef`, `deleted_at=clock.now()` olur. Lokasyonda `is_active=False` olur ve takma ad eklenir.
  - Kaynak unvan/tesis adı `account_aliases`'e `kaynak='BIRLESTIRME'` ile yazılır.
  - `account_merges` satırı açılır.
  - İki kayıt `with_for_update()` ile kilitlenir.
- `ana_veri.kapsam_bilgisi(db, customer_id, address_id, equipment_id, clock)` → E14-17.
- `ana_veri.saha_onerisi(db, address_id | service_order_id)` → E14-16.
- `ana_veri.tesis_eslestir(db, sozlesme)` → E14-10 (E04 PB üretimi çağırır).
- `veri_kalitesi.gostergeler(db, user)`, `veri_kalitesi.adaylar(db, kaynak)` → E14-09, E14-18.

Hata sınıfı: `AnaVeriHatasi(ValueError)` (emsal `services/rma.py:39`). API bunu 409/400'e çevirir.

### 5.3 API uçları

**`api/lokasyonlar.py` — prefix `/api/lokasyonlar`**

| Yöntem ve yol | İzin | Not |
|---|---|---|
| `GET ?hesap_id=&q=&tur=&aktif=&dogrulanmamis=` | hesap.gor | `sayfala`; `kapsam_musteri(Address.account_id)`; `q` → `site_key` trgm + `line/city` |
| `GET /{id}` | hesap.gor | kapsam → 404; irtibatlar dahil. Kart açılışı `kvkk.erisim_kaydet` ile loglanır. |
| `POST` | lokasyon.yaz | `{hesap_id, kind, site_name, line?, district?, city, access_note?, primary_contact_id?}`. Aynı hesapta aynı `site_key`'li aktif tesis varsa 409 + mevcut kayıt döner. |
| `PATCH /{id}` | lokasyon.yaz | `version` zorunlu, uyuşmazlıkta 409. `account_id` değiştirilemez (400); hesap taşıma yalnız birleştirmeyle yapılır. |
| `POST /{id}/pasif`, `POST /{id}/aktif` | lokasyon.yaz | Silme ucu YOK. |
| `POST /{id}/kisiler`, `PATCH /kisiler/{kisi_id}` | lokasyon.yaz | `contacts.address_id` doldurulur. Telefon `normalize_msisdn` ile normalleştirilir; denetime `is_personal_data=True` yazılır (canlı `api/accounts.py:147-221` kalıbı). |

**`api/teknik_servis_ana_veri.py` — prefix `/api/teknik-servis/ana-veri`**

| Yöntem ve yol | İzin | Not |
|---|---|---|
| `GET /musteri-ara?q=` | servis.gor | En çok 20 sonuç. Yanıt: `{id, unvan, il, dogrulandi, eslesen: 'unvan'|'takma_ad'|'tesis'|'vkn'}`. **İrtibat, VKN, IBAN ve telefon dönmez.** `kapsam_uygula` uygulanır. |
| `GET /lokasyon-ara?hesap_id=&q=` | servis.gor | `{id, tesis_adi, ilce, il, aktif}` |
| `POST /hizli-musteri` | servis.yaz + lokasyon.yaz | 201 `{hesap, lokasyon}` ya da 409 `{adaylar}` |
| `POST /musteriler/{id}/dogrula`, `POST /lokasyonlar/{id}/dogrula` | hesap.birlestir | `is_verified=True`, `verified_at` Clock |
| `GET /musteriler/{id}/servis-karti` | hesap.gor + servis.gor | E14-07 |
| `GET /kapsam-bilgisi?hesap_id=&lokasyon_id=&ekipman_id=` | servis.gor | E14-17; tutar yok |
| `GET /saha-onerisi?lokasyon_id=` veya `?is_id=` | servis.gor (+ işe erişim) | E14-16 |
| `GET /takma-adlar?hesap_id=`, `POST /takma-adlar`, `DELETE /takma-adlar/{id}` | hesap.birlestir | Silme denetime yazılır. |
| `POST /birlestirme/onizle` | hesap.birlestir | DB'ye yazmaz |
| `POST /birlestirme/uygula` | hesap.birlestir | `{tur, kaynak_id, hedef_id, gerekce, beklenen: {tablo.kolon: adet}}`. Beklenen sayılar güncel önizlemeyle uyuşmazsa 409 "veri değişti, yeniden önizleyin". |
| `GET /birlestirmeler` | hesap.birlestir | Salt okunur kayıt |
| `GET /eslestirme/adaylar.xlsx?kaynak=` | hesap.birlestir + rapor.disaaktar | E14-09 |
| `GET /veri-kalitesi` | servis.gor + rapor.gor | E14-18 KPI kutuları |
| `GET /veri-kalitesi/{gosterge}.xlsx` | rapor.disaaktar + servis.gor | E14-18 |

**Canlı `api/accounts.py`'ye geriye uyumlu eklemeler:**
- `HesapIn`/`HesapPatch`'e `vkn_cakisma_onayi: bool = False` ve `vkn_cakisma_gerekce: str | None` eklenir. VKN dolu ve başka aktif hesapta varsa 409 `{mesaj, mevcut:[{id, title}]}` döner. Onay ve gerekçe verilirse kayıt geçer ve `audit.log(... "vkn.cakisma.onay")` yazılır.
- `HesapOut`'a `is_verified`, `dis_referans` eklenir. `GET /api/hesaplar`'a `dogrulanmamis: bool = False` filtresi eklenir.
- `HesapProfili` (`services/imports/hesap.py:31-56`) isteğe bağlı `Cari Kodu` sütununu alır ve `dis_referans`'a yazar.

### 5.4 Denetim izi eylemleri

`hesap.hizli_olustur`, `hesap.dogrula`, `vkn.cakisma.onay`, `lokasyon.olustur`, `lokasyon.guncelle` (`log_change`), `lokasyon.pasif`, `lokasyon.dogrula`, `contacts.olustur/guncelle` (`is_personal_data=True`), `takma_ad.ekle`, `takma_ad.sil`, `hesap.birlestir`, `lokasyon.birlestir`, `eslestirme.uygula`, `ana_veri.disaaktar`. Hepsi commit'ten önce, aynı transaction içinde yazılır.

---

## 6. Ön yüz

- **Menü (`components/AppLayout.tsx:45-120`):** "Hesaplar" aynı kalır. Teknik Servis grubuna `{key:"/servis/ana-veri", label:"Servis Ana Verisi", izin:["hesap.birlestir","rapor.gor"]}` eklenir. Rota `main.tsx` AppLayout altına eklenir.
- **`HesaplarPage.tsx`:**
  - Satırda "Doğrulanmamış" etiketi ve `Select` ile "Doğrulanmamışlar" filtresi.
  - Kartta yeni sekmeler:
    - "Lokasyonlar" (`yetkili("hesap.gor")`): tesis listesi, aktif/pasif, birincil irtibat; `LokasyonPenceresi` (KartPenceresi kalıbı, `version` geri gönderilir).
    - "Servis" (`yetkili("servis.gor")`): E14-07.
  - "Birleştir" düğmesi (`yetkili("hesap.birlestir")`) `BirlestirmePenceresi`'ni açar: hedef seçimi, önizleme tablosu, gerekçe, onay.
  - VKN 409'unda `Modal.confirm` ile "aynı VKN'li kayıtlar" listesi ve gerekçe alanı açılır.
- **`MusteriLokasyonSecici.tsx`:** `AutoComplete` → `/musteri-ara`, ardından `/lokasyon-ara`, ardından irtibat. "Hızlı ekle" bağlantısı yalnız `yetkili("lokasyon.yaz")` ise görünür. 409'da "Bunu mu demek istediniz?" listesi açılır. Servis işi formu (E01), sözleşme (E04), kiralama (E06), atölye (E05) ve teklif (E07) bu bileşeni kullanır.
- **`ServisAnaVeriPage.tsx`:**
  - Tıklanabilir KPI kutuları: her kutu ilgili filtreli listeye gider.
  - Doğrulanmamış müşteri/tesis tablosu.
  - Eşleştirme: aday Excel indirme ve İçe Aktarma sayfasına bağlantı.
  - Birleştirme kayıtları.
  - Liste kalıbı: `useQuery` + sunucu sayfalaması + `Drawer`.
- Tarih `DD.MM.YYYY`, tüm metinler Türkçe, 375 px'te kullanılabilir. Ön yüz kapısı: `npm run build` + `oxlint`.

---

## 7. Gereksinim maddeleri

### E14-01 · Müşteri ana verisinin servis için genişletilmesi: doğrulama durumu, hızlı ekleme, VKN ve ad tekrarı (M14-01)
- **Canlı:** KISMEN. Müşteri = `accounts` (`models/account.py:53-130`), CRUD + kapsam + denetim VAR (`api/accounts.py:60-464`). VKN tekilliği, "Doğrulanmamış" kavramı, hızlı ekleme ucu ve unvan eki normalleştirmesi YOK. `customers.*` karşılığı `hesap.gor/hesap.yaz` VAR; birleştirme izni YOK.
- **Yaklaşım:**
  - §3.1 kolonları (`is_verified`, `verified_at/by`, `dis_referans`, `merged_into_id`) ve §3.7 `unvan_anahtari`.
  - `hesap.birlestir` ve `lokasyon.yaz` izinleri; §4.2 rol düzeltmesi.
  - `POST /api/teknik-servis/ana-veri/hizli-musteri`: yalnız ad + il (+ ops. tesis adı), daima `is_verified=False`, denetim `hesap.hizli_olustur`.
  - VKN uyarısı canlı `POST/PATCH /api/hesaplar`'a eklenir (409, onay + gerekçe ile geçer).
  - Ad tekrarı: hızlı eklemede `unvan_anahtari` eşleşmesi veya benzerlik ≥ `musteri_benzerlik_esigi` olursa 409 + aday listesi döner; `onay_benzer=true` ile kaydedilir.
  - Ayar (`services/settings.py` DEFAULTS): `musteri_benzerlik_esigi=0.6`.
  - Testler: `tests/integration/test_ana_veri_musteri.py`, `tests/unit/test_normalize.py` (doctest dahil).
- **Kabul:**
  1. Hızlı ekleme ile açılan hesap `is_musteri=True`, `is_verified=False` doğar. Gövdede `is_verified=true` gönderilse de yok sayılır.
  2. Aynı VKN'li ikinci aktif hesap `POST /api/hesaplar` ile 409 alır. `vkn_cakisma_onayi=true` + gerekçe ile 201 döner ve denetimde `vkn.cakisma.onay` görünür.
  3. `G4S ELEKTRONİK SİSTEMLERİ A.Ş.` varken `G4S Elektronik Sistemleri Anonim Şirketi` hızlı eklemesi 409 + aday döner; onayla 201 döner.
  4. `SERVIS_TEKNISYEN` ile `/api/hesaplar` 403 alır; `/ana-veri/musteri-ara` 200 döner ve yanıtta `tax_no/phone/email/kisiler` anahtarı yoktur.
  5. `SERVIS_TEKNISYEN` (lokasyon.yaz yok) ile hızlı ekleme 403 alır.
  6. Var olan mobilite hesapları migration sonrası `is_verified=true`'dur. `test_altin_kayit` yeşil kalır.
  7. Boş/boşluk unvan 422, 201+ karakter 422 alır; unvan kırpılarak kaydedilir (M14-D01 özü; Pydantic `min_length/max_length` + strip).
- **P1 · M · Bağımlılık:** E13 · **Canlı risk:** `POST/PATCH /api/hesaplar` VKN dolu ve çakışıyorsa artık 409 dönüyor. Mobilite kullanıcısı için ek onay adımı doğuyor ama kayıt engellenmiyor. Önlem: önce E14-08'in canlı PG ölçümü ile mevcut çakışma sayısı raporlanır; HesaplarPage onay penceresi aynı sürümde gelir; içe aktarma profili bu kontrole tabi DEĞİLDİR, karantina akışı değişmez.

### E14-02 · Servis lokasyonu (tesis) = `addresses` genişletmesi + uçlar + takma ad (M14-01)
- **Canlı:** KISMEN. `addresses` tablosu VAR (`models/account.py:177-187`), ama hiçbir API ucu, aktif/pasif, tesis adı, irtibat bağı ve takma ad YOK. Tek okuyucu `services/belgeler.py:150-152`.
- **Yaklaşım:**
  - §3.2 kolonları, `contacts.address_id` (§3.3) ve `account_aliases` (§3.4).
  - Migration: `line DROP NOT NULL` + `ck_addresses_satir`, `ck_addresses_tur`, `ck_addresses_tesis_adi`, `uq_addresses_kaynak`, trgm indeksi.
  - `api/lokasyonlar.py` (§5.3); `LokasyonPenceresi`; HesaplarPage "Lokasyonlar" sekmesi.
  - `belgeler.teklif_baglami` adres seçimi `kind <> 'TESIS'` ve `is_primary DESC` sıralamasıyla yapılır. Var olan satırların hepsi MERKEZ olduğundan bugünkü PDF çıktısı değişmez.
  - Testler: `test_ana_veri_lokasyon.py`.
- **Kabul:**
  1. Lokasyon + irtibat API ile oluşturulur; irtibat `address_id` taşır ve denetimde `is_personal_data=True` olur.
  2. Aynı hesapta aynı `site_key`'li ikinci aktif tesis 409 alır.
  3. `PATCH` eski `version` ile 409 alır; `account_id` değiştirme denemesi 400 alır.
  4. Pasif lokasyon `lokasyon_dogrula` tarafından reddedilir (400); pasiflenen lokasyona bağlı eski kayıtlar açılmaya devam eder.
  5. Silme ucu yoktur (405).
  6. `SATIS` (KENDI_MUSTERILERI) kapsam dışı hesabın lokasyonunu GET'te 404, PATCH'te 404 alır **ve** kayıt değişmemiştir (`db.refresh`).
  7. Takma ad çakışması (`alias_key` başka hedefe ait) 409 + mevcut hedef döner.
  8. Teklif PDF testi (`test_belgeler` / teklif PDF) aynı adresi basar.
- **P1 · M · Bağımlılık:** E14-01 · **Canlı risk:** Düşük. Canlı tabloya yalnız nullable/server_default kolon eklenir. `line` NOT NULL gevşetilir ama tesis dışı satırlar için CHECK ile korunur. `belgeler.py` değişikliği tek sorguda yapılır ve teklif PDF testiyle kilitlenir. downgrade: kolonlar düşer, `line` NULL olan TESIS satırı varsa downgrade önce bunları listeler ve durur (veri kaybı görünür kılınır).

### E14-03 · Ana veri denetimi ve kişisel veri (KVKK) kuralları (M14-13)
- **Canlı:** KISMEN. Denetim izi ve değiştirilemezliği VAR (`services/audit.py:26-92`; `api/audit_api.py` yalnız GET). Hesap/irtibat yazımları zaten denetimde (`api/accounts.py:168-177, 209-219`). Okuma logu `kvkk.erisim_kaydet` VAR. Anonimleştirme `addresses`, `account_aliases`, `contacts.address_id` bağını ve servis kayıtlarındaki ham irtibat metnini KAPSAMIYOR (`services/kvkk.py:30, 217-302`). Rapor Excel'leri denetime yazılmıyor.
- **Yaklaşım:**
  - E14-01/02/12 uçlarının hepsi §5.4 eylemleriyle denetime yazar. Hızlı ekleme ve eşleştirme içe aktarması dahildir; içe aktarmada parti başına bir özet kaydı ve satır başına `log_change` yazılır.
  - Lokasyon/irtibat kartı açılışı `kvkk.erisim_kaydet(amac="lokasyon.kart")` ile loglanır.
  - `hesabi_anonimlestir` genişler:
    - hesabın `addresses.line/access_note` alanları `ANONIM_ISARETI` ile, `account_aliases.alias_text` alanları maskeyle doldurulur;
    - E03 `service_equipment.contact_name_raw` ve E01 `iletisim_ad/telefon` temizlenir (E01 §kvkk ile aynı satır).

    `KISISEL_VARLIKLAR`'a `addresses` eklenir.
  - Servis tarafı her Excel dışa aktarımı `audit.log(..., "ana_veri.disaaktar", new_value={"rapor":..., "satir":n})` yazar ve `rapor.disaaktar` ister.
  - Testler: `test_ana_veri_kvkk.py`.
- **Kabul:**
  1. İrtibat telefonu değişikliği denetim tablosunda eski/yeni değer (maskeli), kullanıcı ve zamanla görünür.
  2. Denetim kaydını değiştirecek API ucu yoktur (PUT/DELETE `/api/denetim` 405).
  3. `rapor.disaaktar` olmayan kullanıcı aday/veri kalitesi Excel'inde 403 alır; olan kullanıcının dışa aktarımı denetimde görünür.
  4. Anonimleştirilen hesabın tesis satırı ve takma adları maskelenir, servis işi kaydı korunur.
  5. Hızlı ekleme ve eşleştirme içe aktarması denetim satırı üretir.
- **P2 · S · Bağımlılık:** E14-01 ile aynı sürüm (denetim sonradan eklenmez) · **Canlı risk:** `hesabi_anonimlestir` genişliyor. Mobilite hesaplarında `addresses` satırı varsa artık o da maskeleniyor; bu KVKK açısından bir düzeltmedir. Önlem: mevcut `test_kvkk` testleri yeşil kalır, yeni test addresses maskesini doğrular.

### E14-04 · Servis kayıtlarında müşteri/lokasyon FK bağlarının ortak kuralı — Faz A (M14-05-A)
- **Canlı:** KISMEN. Servis tabloları canlıda yok; E01 (`service_orders.customer_id RESTRICT NOT NULL, address_id SET NULL`), E02 (`service_plans.address_id`), E03 (`service_equipment.account_id RESTRICT NULL, address_id`), E04 (`maintenance_contracts.account_id RESTRICT, address_id`) tasarımlarında var. Hesap silme ucu canlıda zaten yok.
- **Yaklaşım:**
  - §3.6 tablosu bağlayıcıdır. Bu madde kod olarak `ana_veri.lokasyon_dogrula()` ortak doğrulayıcısını ve E01/E04 için iki koordinasyon kolonunu getirir:
    - `service_orders.customer_name_raw / location_raw`;
    - `maintenance_contracts.customer_name_raw / site_name_raw` + `ck_mc_musteri_teyit`.
  - Kolonlar ilgili modülün migration'ında açılır. Sahibi modül önce kodlanırsa E14 migration'ı ekler.
  - Göç edilen kayıt eşleşmezse müşteri FK'si yalnız izin verilen tablolarda NULL kalır; uydurma bağ kurulmaz.
  - Testler: `test_ana_veri_baglar.py` (parametrik: her servis kaydı türü için doğrulayıcı).
- **Kabul:**
  1. Müşteri/lokasyonu boş göç kaydı (ekipman, `TEYIT_BEKLIYOR` sözleşme) hatasız listelenir ve açılır; ekranda "Eşleştirilmemiş: <ham metin>" görünür.
  2. Servis kaydı bağlı hesabı DB'de silme denemesi `fk_`/RESTRICT ile 409 alır; API'de hesap silme ucu yoktur.
  3. Başka hesabın lokasyonuyla veya pasif/`is_musteri=false` hesapla servis işi, sözleşme ya da ekipman kaydı 400 alır (Türkçe mesaj).
  4. `AKTIF` sözleşmede `account_id` NULL olamaz (`ck_mc_musteri_teyit`, 409).
- **P1 · M · Bağımlılık:** E14-01, E14-02; E01, E03, E04 ile koordine · **Canlı risk:** Yok. Kolonlar yeni tablolara açılıyor; canlı tablolara yazılmıyor.

### E14-05 · Servis işi açılışında müşteri-lokasyon-irtibat seçimi, hızlı ekleme ve plan ön dolumu (M14-04, M14-D01 özü)
- **Canlı:** YOK. Mobilite iş emri formu (`pages/IsEmriFormu.tsx`) servis işi için kullanılmaz; seçici bileşen yok.
- **Yaklaşım:**
  - `MusteriLokasyonSecici.tsx` + `/musteri-ara`, `/lokasyon-ara`, `/hizli-musteri`.
  - E01 `POST /isler` servisi `lokasyon_dogrula()` çağırır.
  - E02 plan formu `GET /api/lokasyonlar/{id}` ile ön dolar: il, ilçe, açık adres, `access_note`, birincil irtibat.
  - Plan kaydında "lokasyon kaydını da güncelle" kutusu: işaretli ve kullanıcıda `lokasyon.yaz` varsa aynı transaction'da lokasyon `log_change` ile güncellenir. İşaretsizse yalnız plan satırı yazılır.
  - M14-D01 özü:
    - müşteri serbest metin değil, FK'dir;
    - `customer_id` boş/geçersizse 422/400 döner, 500 dönmez;
    - servis işinden açılan teklifte müşteri sunucuda işten alınır (E14-15).
- **Kabul:**
  1. Seçiciyle açılan serviste `customer_id` ve `address_id` dolu olur.
  2. Başka müşterinin lokasyonu veya pasif müşteri 400 alır.
  3. `customer_id` gönderilmezse 422 alır (500 değil).
  4. Plan formu lokasyondan ön dolar. Kutu işaretli değilse lokasyon kaydı değişmez (`version` aynı kalır); işaretliyse `lokasyon.yaz` olmayan kullanıcı 403 alır.
  5. Hızlı eklenen müşteri ve tesis "Doğrulanmamış" listesinde görünür.
  6. Teknisyen formunda "Hızlı ekle" bağlantısı görünmez.
- **P1 · M · Bağımlılık:** E14-01, E14-02, E14-04; E01, E02 · **Canlı risk:** Yok.

### E14-06 · Havuz/toplu planlama ve takvim gruplamasının lokasyon kimliğine geçmesi (M14-D04)
- **Canlı:** YOK. Servis havuzu E02'de tasarlandı. E09 ziyaret anahtarı `customer_id + address_id + city` (`09_saha_zaman_entegrasyon.md:346`).
- **Yaklaşım:**
  - E02 havuz servisindeki grup anahtarı `ana_veri.grup_anahtari(is) -> tuple` olarak tek yerde tanımlanır:
    - `address_id` doluysa `(birim, 'L', address_id)`;
    - boşsa `(birim, 'M', customer_id, tr_normkey(location_raw or ''))`.
  - E02 toplu planla/ata ucu farklı `address_id`'li işler içeriyorsa 409 `{farkli_lokasyonlar:[...]}` döner. `farkli_lokasyon_onayi=true` ile geçilir ve `PLAN` olayına not düşülür.
  - Ön yüz takvim kartı aynı anahtarı API'den (`grup_anahtari` alanı) alır; istemcide metin birleştirme yapılmaz.
- **Kabul:**
  1. "AKYAKA AVM" ve "AKYAKA PARK AVM" ham metinli, aynı `address_id`'li iki iş havuzda tek grupta görünür.
  2. `address_id` boş eski işler ham metinle gruplanır.
  3. Farklı `address_id`'li toplu plan 409 alır; onayla 200 döner ve olay geçmişinde not görünür.
  4. Toplu planlama/atama işlevi (kullanıcının doğruladığı) aynı çağrıyla çalışmaya devam eder.
- **P2 · S · Bağımlılık:** E14-04; E02, E09 · **Canlı risk:** Yok.

### E14-07 · Müşteri kartında servis sekmeleri (M14-02)
- **Canlı:** KISMEN. Hesap kartı VAR (`api/accounts.py:248-368`, `pages/HesaplarPage.tsx:396-700`: kişiler, belgeler, siparişler, cihazlar, araçlar, abonelikler, görevler). Lokasyon, servis işi, sözleşme, ekipman, kiralama ve teklif özeti YOK.
- **Yaklaşım:**
  - Canlı `/kart` ucu DEĞİŞMEZ. Yeni `GET /api/teknik-servis/ana-veri/musteriler/{id}/servis-karti` (hesap.gor + servis.gor) şunları döndürür:
    - `lokasyonlar` (açık iş sayısıyla);
    - `servis_isleri` (açık/son 20) ve `acik_is_sayisi`;
    - `sozlesmeler` (no, tesis, dönem, durum);
    - `ekipman_sayisi` ve tür kırılımı;
    - `kiralamalar` (açık);
    - `teklifler` (no, durum, tarih).
  - **Açık iş sayısı** E01 liste servisinin `liste_sorgusu(filtre={musteri: id, acik: True})` fonksiyonuyla sayılır. Kartta ayrı sayım yazılmaz.
  - Sözleşme, kiralama ve servis sayıları `kapsam_birim` uygular.
  - **Tutar alanları** (teklif toplamı, sözleşme ücreti, kiralama bedeli) yalnız `sees_cost(user)` true ise anahtar olarak yer alır.
  - Eşleştirilmemiş kayıt nedeniyle boş kalan sekmede açıklama gösterilir: "Bu müşteriye bağlanmamış eski kayıtlar olabilir — Servis Ana Verisi > Eşleştirme".
  - HesaplarPage "Servis" sekmesi `yetkili("servis.gor")` ile görünür. Satırlar ilgili listeye filtreli bağlantı verir.
- **Kabul:**
  1. Karttaki açık iş sayısı, `/api/teknik-servis/isler?musteri=..&acik=1` yanıtının `X-Toplam-Kayit` değerine eşittir.
  2. `maliyet.gor` olmayan kullanıcının yanıtında `toplam`, `ucret`, `bedel` anahtarları yoktur.
  3. GUVENLIK birimli şef HABERLESME işlerini kartta göremez ve sayıya da katmaz.
  4. Eşleştirilmemiş boş sekmede açıklama görünür.
  5. 375 px'te sekmeler kullanılabilir.
  6. Canlı `/api/hesaplar/{id}/kart` yanıtı birebir aynıdır (regresyon testi).
- **P2 · M · Bağımlılık:** E14-02, E14-04; E01, E04, E06, E07 · **Canlı risk:** Yok; yalnız yeni uç ve yeni sekme eklenir.

### E14-08 · Veri kalitesi ölçümü — kaynak (salt okunur) ve canlı (M14-D03)
- **Canlı:** YOK.
- **Yaklaşım:**
  - **Kaynak ölçümü (göç öncesi):** `backend/app/migration/teknik_servis/sql/m14_olcum.sql`. Yalnız `SELECT` içeren T-SQL; V1.20.1 SQL Server test kopyasında SSMS ile koşulur. Ayrı sonuç kümeleri:
    - tablo bazında farklı müşteri metni sayısı;
    - sözleşme–kütük eşleşmesi (`CustomerName` ve `Location` ayrı ayrı);
    - boş müşteri;
    - `WorkOrders.Location = MaintenanceDeviceItems.Zone` olan PB işleri (M14-07 etkisi);
    - şüpheli mükerrer sözleşmeler.

    Çıktı Excel'e kopyalanır ve E14-09 faz planını kesinleştirir.
  - **Canlı ölçüm (PG):** `uv run python -m app.migration.ana_veri_olcum` salt okunur betiği. Transaction `SET TRANSACTION READ ONLY` ile açılır. Ölçtükleri:
    - aynı VKN'li aktif hesap grupları;
    - `unvan_anahtari` çakışan hesap grupları;
    - `addresses` dağılımı.

    Sonuç xlsx olarak yazılır.
- **Kabul:**
  1. Her iki betik yalnız okuma yapar. Canlı betik READ ONLY transaction'dadır; yazma denemesi DB hatası verir (test). Koşu öncesi/sonrası satır sayıları aynıdır.
  2. Çıktı tablo bazında ayrı sonuç kümeleri/sayfalardır.
  3. Test kopyasında çalışır.
  4. Sonuçlar E14-01 VKN uyarısının yayın notuna ve E14-09 faz kapsamına yazılır.
- **P1 · S · Bağımlılık:** Yok · **Canlı risk:** Yok (salt okunur).

### E14-09 · Serbest metinden onaylı eşleştirme — Excel ile (M14-03)
- **Canlı:** KISMEN. İçe aktarma çerçevesi VAR: profil, şablon, parti, karantina, karar, denetim (`services/imports/__init__.py`, `api/imports.py:82-282`). xlsx dışa aktarma VAR (`services/export.py:45`). Eşleştirme profili, aday üretimi ve takma ad YOK.
- **Yaklaşım:**
  - **Faz 1:** `maintenance_contracts` (E04) + GUVENLIK `service_equipment` (E03).
  - **Faz 2:** `service_orders`, `service_plans`, `quotes`(servis), `rentals`, `workshop_records`.
  - Aday listesi: `GET /ana-veri/eslestirme/adaylar.xlsx?kaynak=sozlesme|ekipman|...`. Yalnız okur. Satır başına şu sütunlar yazılır:
    - kaynak tablo ve id, ham müşteri metni, ham tesis/lokasyon metni;
    - önerilen hesap (id, unvan, yöntem: takma_ad / unvan_anahtari / trgm skoru);
    - önerilen tesis;
    - boş `Onay (E/H)`, `Hedef Hesap Id`, `Hedef Lokasyon Id`, `Yeni Tesis Adı`.

    Müşterisi boş ekipmanlar ayrı sayfada listelenir.
  - İçe aktarma: yeni profil `musteri_eslestirme` (`PROFIL_IZINLERI["musteri_eslestirme"]="hesap.birlestir"`).
    - `dogrula()`: onaysız veya boş satır atlanır; hedef hesap `is_musteri` değilse ya da tesis başka hesaba aitse satır karantinaya düşer.
    - `yaz()`: yalnız `Onay=E` satırlarda kaynak kaydın `account_id/address_id` kolonu yazılır. "Yeni Tesis Adı" doluysa `kind='TESIS'` adres açılır. Ham metin `account_aliases`'e `kaynak='ESLESTIRME'`, `kaynak_tablo` ile eklenir; zaten varsa atlanır, idempotent. **Ham metin kolonları değiştirilmez.**
    - Sayaç `{tablo: {yazilan, atlanan, karantina}}` döner.
  - Ekran: ServisAnaVeriPage'den aday indirme; yükleme mevcut İçe Aktarma sayfasında. Profil listesi profillerden beslendiği için (`services/imports/__init__.py` docstring) ön yüzde ek iş yoktur.
- **Kabul:**
  1. Aday üretimi veriyi değiştirmez (öncesi/sonrası satır ve `version` aynı).
  2. Yalnız onaylı satırlar `account_id/address_id` ve takma ada yazılır; onaysız ve boş satır hiçbir tabloya yazılmaz.
  3. `customer_name_raw/site_name_raw/location_raw` korunur.
  4. Müşterisi boş ekipmanlar ayrı sayfadadır.
  5. Aynı dosya iki kez uygulanırsa ikinci koşu 0 satır yazar (idempotent).
  6. Sonuç tablo bazında yazılan satır sayısını raporlar.
  7. `hesap.birlestir` olmayan kullanıcı 403 alır.
- **P1 · L · Bağımlılık:** E14-01, E14-02, E14-04, E14-08; E03, E04 · **Canlı risk:** Yok. Yeni profil, mevcut profillerin sırasını ve izinlerini değiştirmez.

### E14-10 · PB üretiminde tesis/ekipman eşleşmesi; bakım formu lokasyonu ezmez (M14-06, M14-07 özü)
- **Canlı:** YOK (PB üretimi E04'te tasarlandı).
- **Yaklaşım:**
  - `ana_veri.tesis_eslestir(db, sozlesme) -> TesisEslesme(ekipmanlar, yontem, eksik_adet, uyarilar)`. E04 `bakim_uretim` kapsam kalemine ekipman bağlarken bu fonksiyonu çağırır. Sıra:
    1. Kalemde doğrudan `equipment_id` (E04-17);
    2. `service_equipment.address_id = sozlesme.address_id` ve aynı tür;
    3. `unvan_anahtari(service_equipment.location_raw)` veya `customer_name_raw` = `unvan_anahtari(sozlesme.site_name_raw)`, ya da takma ad eşleşmesi.
  - Eşleşme yoksa PB yine açılır ama `seri_no` boş kalır, uydurulmaz. `address_id` sözleşmeninkidir; NULL ise `location_raw = site_name_raw` olur. Üretim kaydının `skipped/uyarilar` alanına "eşleşen ekipman yok / eksik N" yazılır.
  - **PB işinin lokasyonuna cari unvan (sözleşme tarafı) yazılmaz.**
  - M14-07 özü (E04 ile koordine):
    - Bakım formu kaydı servis işinin `address_id`, `location_raw` ve `aciklama` alanlarını değiştirmez.
    - Bölge yalnız `maintenance_forms.zone` / `maintenance_contract_items.last_zone` alanına, yapılan iş yalnız `performed_work` alanına yazılır.
  - İdempotentlik E04 `uq_so_pb_cihaz_donem` ile sağlanır.
- **Kabul:**
  1. Eşlenen tesiste PB cihaz kalemlerinde `equipment_id` ve seri no dolu gelir.
  2. Eşleşmeyen sözleşme için üretim kaydında uyarı çıkar ve seri no boştur.
  3. Hiçbir PB işinin `location_raw`/`address_id`'si sözleşme tarafı carinin unvanı ya da merkez adresi olmaz (test: cari ≠ tesis verisiyle).
  4. Taslak ve tamamlanan formda bölge girildikten sonra PB işinin `address_id/location_raw/aciklama` alanları değişmez ve iş havuzda aynı grupta kalır.
  5. Üretim iki kez koşulursa ikinci koşu 0 PB açar.
  6. 1 cihaz = 1 PB korunur.
- **P1 · M · Bağımlılık:** E14-04, E14-09 (adım 3 için takma ad); E03, E04 · **Canlı risk:** Yok.

### E14-11 · Sözleşmede tesis/cari ayrımı ve dönem çakışması uyarısı (M14-08)
- **Canlı:** YOK.
- **Yaklaşım:**
  - Sözleşmede `account_id` = sözleşme tarafı cari, `address_id` = tesis (o carinin `kind='TESIS'` adresi). Ekranda iki ayrı alan gösterilir: "Tesis" ve "Sözleşme Tarafı (Cari)".
  - `ana_veri.donem_cakismalari(db, address_id, valid_from, valid_to, haric_id)`: aynı `address_id`'de `AKTIF` ve aralığı kesişen (`tstzrange '[)' &&`) sözleşmeleri bulur.
    - Ayrıştırılmış tarih yoksa (`TEYIT_BEKLIYOR`) aynı `site_key`'de birden çok aktif sözleşme listelenir.
    - E04 `POST/PATCH /sozlesmeler` ve durum→AKTIF geçişi bu fonksiyonu çağırır: çakışma varsa 409 `{cakisanlar}` döner, `cakisma_onayi + gerekce` ile geçilir ve denetime yazılır.
    - EXCLUDE kısıtı KONMAZ, çünkü onaylı istisna gerekir.
  - Mükerrer sözleşme düzeltme listesi: `GET /ana-veri/veri-kalitesi/mukerrer-sozlesme.xlsx`. Otomatik pasifleştirme ve silme yoktur.
  - Pasifleştirilen sözleşmenin açık PB işleri yanıtta `acik_pb_isleri` olarak listelenir.
- **Kabul:**
  1. Aynı tesiste dönemi çakışan ikinci AKTIF sözleşme 409 alır; onay + gerekçe ile kaydedilir ve denetimde görünür.
  2. Hiçbir sözleşme otomatik pasifleştirilmez veya silinmez.
  3. Pasifleştirme yanıtı açık PB işlerini listeler.
  4. Dönemi bilinmeyen sözleşmelerde "aynı tesis adında birden çok aktif sözleşme" listesi döner.
- **P2 · S · Bağımlılık:** E14-09; E04 (E04-03) · **Canlı risk:** Yok.

### E14-12 · Müşteri ve lokasyon birleştirme — önizleme, tek transaction, takma ad, kayıt (M14-09)
- **Canlı:** KISMEN. `migration/hesap_birlestir.py` önizleme + uygula + FK'leri şemadan okuma + yumuşak silme + tek transaction VAR (`:116-223`). API, ekran, lokasyon birleştirme, takma ad, kalıcı kayıt ve `Clock` kullanımı YOK; betik `datetime.now` kullanıyor (`:219`). Mükerrer aday ucu VAR (`api/accounts.py:371-387`) ama ekranda kullanılmıyor.
- **Yaklaşım:**
  - Mantık `services/hesap_birlestir.py`'ye taşınır (`tur='HESAP'|'LOKASYON'`, `clock`, `user`).
  - Betik bu servisi çağırır; `BIRLESMELER` listesi tarihî kayıt olarak kalır.
  - Ek kurallar:
    - **Hak ediş zinciri koruması:** kaynak hesabın `work_orders`, `work_order_items`, `settlements`/`partner_settlements` ya da `installation_partners` tablolarında referansı varsa API 409 döner: "Mobilite hak ediş kaydı olan hesap bu ekrandan birleştirilemez." Bu birleştirme yalnız `sistem.goc` betiğiyle yapılır.
    - Hedef silinmiş, pasif veya kaynakla aynıysa 400 döner. Lokasyonda hedef başka hesaba aitse 400 döner.
    - Önizleme sayıları istemciden `beklenen` olarak geri gelir; uyuşmazsa 409.
    - Kaynak unvan/tesis adı takma ad olur. `account_merges` satırı açılır. Denetime `hesap.birlestir` / `lokasyon.birlestir` yazılır.
    - Kaynak hesabın tesisleri hedefe taşınır (FK). Aynı `site_key`'li tesis hedefte de varsa önizlemede "tesis birleştirmesi önerilir" uyarısı çıkar; otomatik birleştirilmez.
  - Ekran: `BirlestirmePenceresi` (HesaplarPage ve ServisAnaVeriPage). Mükerrer adaylar mevcut `/mukerrer-adaylari` ucundan gelir.
  - Testler: `test_ana_veri_birlestirme.py`.
- **Kabul:**
  1. Birleştirme sonrası tüm bağlı servis kayıtları, irtibatlar, tesisler ve ekler hedefte görünür.
  2. Önizleme sayıları `account_merges.tasinan` ile eşittir.
  3. Yapay hata (ikinci UPDATE'te hata) halinde hiçbir satır taşınmaz.
  4. Geçersiz/pasif hedef 400, `hesap.birlestir` olmayan kullanıcı 403 alır.
  5. Hak ediş referansı olan hesap 409 alır ve `test_altin_kayit` yeşil kalır.
  6. Kaynak kayıt yumuşak silinir, `merged_into_id` dolar ve kaynak unvanıyla `musteri-ara` hedefi bulur.
  7. Betik `--uygula` modu servis üzerinden aynı sonucu verir.
- **P2 · M · Bağımlılık:** E14-01, E14-02, E14-04 · **Canlı risk:** Orta, çünkü birleştirme canlı tablolarda UPDATE yapar. Önlem: hak ediş zinciri referanslı hesaplar API'den reddedilir; işlem tek transaction ve satır kilidiyle yapılır; önizleme ile beklenen sayı karşılaştırılır; yalnız `hesap.birlestir` (SERVIS_YONETICI/ADMIN) yapabilir; birleştirme öncesi ve sonrası altın kayıt testi koşulur.

### E14-13 · Servis işinde gerekçeli müşteri/lokasyon düzeltme (M14-10)
- **Canlı:** YOK. E01-13 `PATCH /isler/{id}` tasarımda var, ama müşteri alanı için yetki ayrımı yok.
- **Yaklaşım:** E01-13'e kural eklenir.
  - `customer_id`, `address_id` veya `contact_id` alanlarından biri değişiyorsa:
    - `gerekce` zorunludur (yoksa 400);
    - açık işte `servis.planla` VEYA `hesap.yaz` gerekir. `SERVIS_TEKNISYEN`'de ikisi de yok, sonuç 403;
    - kapalı işte (`TAMAMLANDI/KAPATILDI/IPTAL`) `hesap.birlestir` gerekir;
    - `tur='PB'` işte 409 döner: "Planlı bakım işinin müşteri/lokasyonu sözleşmeden gelir".
  - Değişiklik `lokasyon_dogrula` + `DUZELTME` olayı (alan, eski→yeni id ve ad; irtibatta yalnız alan adı) + `audit.log_change` ile yazılır.
  - Plan kaydı otomatik değişmez. Yanıtta `plan_guncellenmeli: true` uyarısı döner.
- **Kabul:**
  1. Değişiklik eski/yeni değer ve gerekçeyle olay geçmişinde görünür.
  2. Gerekçesiz 400 alır.
  3. Yalnız `servis.yaz/servis.tamamla` taşıyan teknisyen 403 alır.
  4. PB işinde 409 alır.
  5. Kapalı işte `hesap.birlestir` olmadan 403 alır.
  6. Lokasyon değişince bağlı plan satırının adresi değişmez.
- **P2 · S · Bağımlılık:** E14-01, E14-04; E01 (E01-13), E02 · **Canlı risk:** Yok.

### E14-14 · Atölye kaydındaki firma/seri değişikliğinin servis işi geçmişine yazılması (M14-D02)
- **Canlı:** YOK (atölye E05'te tasarlandı).
- **Yaklaşım:**
  - E05 atölye güncelleme servisi `account_id`, `firma_metni` veya seri değiştiğinde bağlı `service_order_id` için `service_order_events` satırı yazar: `olay_turu='DUZELTME'`, `ozet="Atölye kaydından firma değişti: X → Y"`, kullanıcı, Clock.
  - Değişiklik yoksa satır yazılmaz (`log_change` kalıbı: yalnız değişen kolon).
  - Atölye güncellemesi servis işinin müşterisini değiştirecekse E14-13 kuralları uygulanır; teknisyen atölyeden müşteri değiştiremez.
- **Kabul:**
  1. Firma adı değiştirilen atölye kaydının bağlı servis işi `/gecmis` çıktısında eski ve yeni ad, kullanıcı ve zaman görünür.
  2. Değişiklik yoksa geçmiş satırı oluşmaz.
  3. Atölye rolü servis işi müşterisini değiştirmeye çalışırsa 403 alır.
- **P2 · S · Bağımlılık:** E01, E05, E14-13 · **Canlı risk:** Yok.

### E14-15 · Faz B: teklif, kiralama ve atölye kayıtlarının ana veriye bağlanması (M14-05-B, M14-D01 özü)
- **Canlı:** KISMEN. `quotes.customer_id` VAR (`models/quote.py:74`); `address_id` ve kaynak servis işi bağı YOK. Kiralama ve atölye canlıda yok (E05/E06).
- **Yaklaşım:**
  - `quotes.address_id` (nullable, SET NULL) canlı tabloya eklenir. Kaynak iş kolonu E07'de açılır.
  - Servis işinden teklif açan uç (E07) `customer_id/address_id`'yi **sunucuda** servis işinden kopyalar. İstemcinin gönderdiği farklı müşteri yok sayılır, denetime "istemci müşterisi yok sayıldı" notu düşülür.
  - Kiralama (E06) ve atölye (E05) formları `MusteriLokasyonSecici` kullanır ve kayıtta `lokasyon_dogrula` çağırır. Kiralama irtibatları `contacts`'tan seçilir; serbest irtibat kişisel veri olarak denetime girer.
  - Servis kartı (E14-07) bu kayıtları listeler.
- **Kabul:**
  1. Bir müşteriye bağlı teklif, kiralama ve atölye kayıtları servis kartında listelenir.
  2. Servis işinden açılan teklifte `customer_id/address_id` iş ile aynıdır; istemci farklı müşteri gönderse bile sonuç aynıdır.
  3. Canlı teklif uçları (`/api/teklifler`) `address_id` gönderilmeden eskisi gibi çalışır; mevcut teklif testleri yeşil kalır.
- **P2 · M · Bağımlılık:** E14-01, E14-02, E14-04; E05, E06, E07 · **Canlı risk:** Düşük. `quotes`'a nullable kolon ekleniyor. Önlem: mevcut teklif uçlarında `address_id` opsiyoneldir; teklif PDF'i adres seçiminde önce `quotes.address_id`'yi, yoksa bugünkü sorguyu kullanır.

### E14-16 · Saha önerisinin doğru kaynaktan gelmesi (M14-14)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `GET /ana-veri/saha-onerisi` yalnız `addresses` satırından döner: `line, district, city, access_note` ve `primary_contact_id` → `contacts(full_name, phone)`.
  - Kaynak gösterilmez ve kullanılmaz:
    - sözleşme tarafı carinin unvanı adres olarak;
    - `service_equipment.contact_name_raw` irtibat olarak (kullanıcı teyidine kadar; Karar K3).
  - Lokasyon yoksa ya da birincil irtibatı yoksa alan `null` döner.
  - Telefon, `servis.yaz` olmayan kullanıcıya `kvkk.maskele` ile döner (E01 K11 ile aynı).
- **Kabul:**
  1. Saha önerisi hiçbir zaman `accounts.title` değerini `adres` alanında döndürmez.
  2. Kütük `contact_name_raw` değeri irtibat olarak dönmez.
  3. Lokasyon irtibatı yoksa `irtibat: null` döner.
  4. `servis.yaz` olmayan kullanıcıda telefon maskelidir.
- **P2 · S · Bağımlılık:** E14-02; E03 · **Canlı risk:** Yok.

### E14-17 · Servis işi açılışında sözleşme/garanti kapsam bilgisi ve anlık görüntü (M14-11)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `GET /ana-veri/kapsam-bilgisi` şunları döndürür:
    - `aktif_sozlesmeler`: `[{no, tesis, donem: "01.01.2026–31.12.2026" | "Dönem bilgisi yok", durum}]`;
    - `garanti`: E03 `warranty_end` ≥ bugün (Clock) ise `{bitis, kaynak}`;
    - `son_isler`: son `kapsam_son_is_gun` (ayar, varsayılan 30) gündeki aynı tesis/ekipman servis işleri;
    - `kapsam_durumu`.
  - `kapsam_durumu` değerleri ve kuralı:
    - değerler `('SOZLESMELI','GARANTILI','KAPSAM_DISI','BILINMIYOR')`;
    - yalnız tarihi bilinen AKTIF sözleşme ya da garanti varsa SOZLESMELI/GARANTILI olur;
    - `TEYIT_BEKLIYOR`/tarihsiz sözleşme BILINMIYOR olur ("Sözleşmeli" denmez).
  - **Tutar alanı yoktur** (sözleşme ücreti dahil).
  - E01 `service_orders`'a `coverage_status` String(12) NULL + `ck_so_kapsam` ve `coverage_snapshot` JSONB NULL kolonları açılır; açılışta bir kez yazılır. Güncelleme uçları bu iki alanı kabul etmez. Sonradan değişen sözleşme bunları değiştirmez.
- **Kabul:**
  1. Aktif sözleşmede no ve dönem görünür.
  2. Tarihsiz/teyit bekleyen sözleşmede "Dönem bilgisi yok" yazar ve durum BILINMIYOR olur.
  3. Yanıtta `ucret`, `tutar` anahtarı yoktur (maliyet.gor olan kullanıcıda bile).
  4. `coverage_status` iş açılışından sonra sözleşme pasiflense de değişmez; PATCH ile gönderilirse yok sayılır.
  5. Garanti satırı E03 tarihi yoksa gösterilmez.
- **P3 · S · Bağımlılık:** E14-05, E14-04; E03 (garanti), E04 (dönem) · **Canlı risk:** Yok.

### E14-18 · Rapor gruplama boyutu, müşteri/lokasyon filtresi ve veri kalitesi göstergeleri (M14-12)
- **Canlı:** KISMEN. Rapor + xlsx + izin altyapısı VAR (`services/reports.py`, `api/reports.py:29-55`, `services/export.py:45`). Uyarı merkezi VAR (`services/uyarilar.py:47-192`). Servis raporu, müşteri/lokasyon boyutu ve veri kalitesi göstergesi YOK. Tekrar arıza, çözüm süresi ve kişi-saat KPI'ları E10/E12'ye devredildi (M14-12-KPI reddi).
- **Yaklaşım:**
  - `ana_veri.rapor_boyutu(kayit) -> (anahtar, etiket)`:
    - `address_id` doluysa `('L', id)` + "Tesis adı (İl)";
    - değilse `customer_id` doluysa `('M', id)` + unvan;
    - hiçbiri yoksa `('E', unvan_anahtari(ham))` + "Eşleştirilmemiş: <ham metin>".

    E12 servis raporları gruplamayı bu fonksiyonla yapar. Bütün servis raporu uçları `musteri_id`, `lokasyon_id` filtresini kabul eder; tarih filtresi boşken de çalışır.
  - `veri_kalitesi.gostergeler()` → `GET /ana-veri/veri-kalitesi`. KPI kutuları tıklanabilir, her biri filtreli listeye gider:
    - müşterisi/lokasyonu dolu servis işi oranı;
    - eşleştirilmemiş sözleşme ve ekipman sayısı;
    - doğrulanmamış müşteri ve tesis sayısı;
    - mükerrer aday grubu sayısı (`unvan_anahtari` ve VKN);
    - aynı tesiste çakışan sözleşme sayısı.

    Her kutunun Excel'i (`rapor.disaaktar`) alınır.
  - Uyarı merkezine `if user.has("hesap.birlestir"):` bloğu eklenir: "Doğrulanmamış müşteri/tesis" (ayar `dogrulanmamis_uyari_gun=7`'den eski olanlar) ve "Eşleştirilmemiş servis kaydı". Sayılar `kapsam_birim` uygular. Mevcut bloklara dokunulmaz.
  - Ayarlar: `kapsam_son_is_gun=30`, `dogrulanmamis_uyari_gun=7`, `musteri_benzerlik_esigi=0.6`.
- **Kabul:**
  1. Farklı yazılmış ama aynı `address_id`'li 3 servis işi raporda tek satırda görünür.
  2. `address_id`/`customer_id` boş iş "Eşleştirilmemiş: <metin>" etiketiyle ayrı satırda görünür.
  3. Kimliği dolu iş oranı ve doğrulanmamış müşteri sayısı gösterilir; kutuya tıklanınca aynı sayıda satırlı liste açılır.
  4. Tarih filtresi boşken rapor 200 döner.
  5. Excel `rapor.disaaktar` olmadan 403 alır ve dışa aktarım denetime yazılır.
  6. GUVENLIK şefi HABERLESME sayılarını göremez.
- **P3 · M · Bağımlılık:** E14-09, E14-04; E10, E12 · **Canlı risk:** Yok. `services/reports.py` ve mevcut uyarı blokları değişmez.

---

## 8. Test planı (özet)

| Dosya | İçerik |
|---|---|
| `tests/unit/test_permissions.py` | `hesap.birlestir`, `lokasyon.yaz` en az bir rolde; `SERVIS_TEKNISYEN` ve `ATOLYE`'de `hesap.gor` YOK; `maliyet.gor` kümesi aynı |
| `tests/unit/test_normalize.py` | `unvan_anahtari` ek/noktalama/Türkçe katlama; `tr_normkey` çıktısı değişmemiş |
| `tests/integration/test_ana_veri_musteri.py` | E14-01 kabul 1-7 (403/200, VKN 409/onay, hızlı ekleme 409/201) |
| `tests/integration/test_ana_veri_lokasyon.py` | E14-02 + kapsam (404 **ve** veri değişmemiş), `version` 409, silme ucu yok |
| `tests/integration/test_ana_veri_kvkk.py` | E14-03; denetim satırları, anonimleştirme kapsamı, dışa aktarım 403 |
| `tests/integration/test_ana_veri_birlestirme.py` | E14-12; atomiklik, hak ediş koruması, takma ad, `account_merges` |
| `tests/integration/test_ana_veri_eslestirme.py` | E14-09; aday Excel salt okunur, onaylı satır, idempotent |
| `tests/integration/test_ana_veri_kart.py` | E14-07; açık iş sayısı = liste toplamı, maliyet anahtarı yok, birim kapsamı, canlı `/kart` regresyonu |
| `tests/integration/test_belgeler*.py` | Teklif PDF adresi değişmedi |
| `tests/migration/test_migration_zinciri.py` | head→base→head; tek head |
| `tests/migration/test_altin_kayit.py` | 932 iş / 552.825,00 TL yeşil |

Fixture: `kullanici_ac(..., "SERVIS_YONETICI" | "SERVIS_SEF" | "SERVIS_TEKNISYEN")`. Hesap ve tesis için `hesap_ac`/`tesis_ac` yardımcıları `conftest.py`'ye eklenir; emsal `urun_ac`.

---

## 9. İzlenebilirlik (M14 → E14)

| Kaynak | E14 | Not |
|---|---|---|
| M14-01 | E14-01, E14-02 | Ayrı müşteri tablosu yerine `accounts` + `addresses` + `account_aliases` |
| M14-05-A | E14-04 | |
| M14-04 | E14-05 | |
| M14-D04 | E14-06 | |
| M14-D01 (dotnet_specific) | E14-01 kabul 7, E14-05 kabul 3, E14-15 kabul 2 | Özü: boş/geçersiz müşteri 4xx, teklifte müşteri sunucuda |
| M14-02 | E14-07 | |
| M14-03 | E14-09 | |
| M14-D03 | E14-08 | |
| M14-06 | E14-10 | |
| M14-07 (dotnet_specific) | E14-10 kabul 4, E14-06 kabul 1 | Özü: form lokasyon/açıklamayı ezmez, gruplama bozulmaz |
| M14-08 | E14-11 | |
| M14-09 | E14-12 | |
| M14-10 | E14-13 | |
| M14-D02 | E14-14 | |
| M14-05-B | E14-15 | |
| M14-14 | E14-16 | |
| M14-13 | E14-03 | |
| M14-11 | E14-17 | |
| M14-12 | E14-18 | KPI'lar E10/E12'de |

---

## 10. Kararlar (kullanıcıya soru sorulmadan verildi)

- **K1 — "Müşteri" kimdir:** Servis kaydında `customer_id` = fatura/sözleşme tarafı cari (`accounts`); gidilen yer = tesis (`addresses.kind='TESIS'`, o carinin altında). Operasyon ekranlarında (iş listesi, plan, takvim) **tesis adı önde**, cari ikinci kolonda gösterilir. Raporlarda varsayılan gruplama tesistir, cari seçilebilir boyuttur. Gerekçe: teknisyen tesise gider, fatura cariye kesilir; iki bilginin de kaybolmaması gerekir.
- **K2 — Bayi/entegratör üzerinden gelen iş (G4S, SECURİTAS, "… ÜZERİNDEN"):** İş son kullanıcı tesisinin carisine açılır. Aracı bayi, canlıdaki `accounts.parent_dealer_id` ile gösterilir (yeni kolon açılmaz). Son kullanıcı bilinmiyorsa bayi hesabı müşteri olur ve tesis bayinin altına açılır. Faturalama kapsam dışıdır.
- **K3 — Kütükteki ContactName:** Denge personeli olma ihtimali yüksek, teyit yok. Kullanıcı teyidine kadar müşteri irtibatına aktarılmaz; `service_equipment.contact_name_raw` (E03) olarak kalır, kişisel veri sayılır, saha önerisinde kullanılmaz.
- **K4 — Muhasebe cari kodu:** `accounts.dis_referans` metin olarak tutulur, entegrasyon yoktur (Logo kapsam dışı). İlk aktarımda cari listesi mevcut "Hesaplar" içe aktarma profiliyle yüklenebilir (yeni "Cari Kodu" sütunu).
- **K5 — Şüpheli mükerrer sözleşmeler (BAKIM-0041/-0087 vb.):** Otomatik karar verilmez. E14-11 düzeltme listesi + kullanıcı onayı uygulanır.
- **K6 — VKN:** Zorunlu değil. Tekil DB indeksi konmaz, çünkü mobilite verisinde şube/bayi ayrımlı aynı VKN olabilir ve tekil indeks canlı migration'ı mevcut veriyle kırabilir. Kural servis katmanında 409 + onay/gerekçe olarak uygulanır. TCKN servis tarafında istenmez; canlı `HesapIn` TCKN kabul etmeye devam eder (mobilite bireysel müşteri).
- **K7 — Birleştirme/doğrulama yetkisi:** `hesap.birlestir` → `SERVIS_YONETICI` (Teknik Servis Müdürü; Müdür Yrd. aynı rolle) + ADMIN. Doğrulanmamış kayıtlar uyarı merkezinde 7 günden eski olunca görünür (ayar).
- **K8 — İlk eşleştirme:** Güvenlik birimi sözleşmeleri + GUVENLIK ekipmanından başlanır (Faz 1). Servis Yöneticisi yapar. Diğer birimler Faz 2'de.
- **K9 — Birimler tek müşteri listesi kullanır.** `accounts` zaten tek tablodur. Birim kapsamı müşteri kaydına değil, servis kayıtlarına ve sayılarına uygulanır.
- **K10 — Tekrar arıza penceresi:** 30 gün (ayar). Hesaplama E10/E12'dedir; bu modül yalnız `kapsam_son_is_gun=30` ayarını kullanır.
- **K11 — Kaynak veri ölçümü:** Kaynak tarafta (SQL Server test kopyası) T-SQL SELECT betiği, canlı tarafta READ ONLY Python betiği çalışır. Tarih ve sayılar ölçümden gelir; uydurulmaz.
- **K12 — Ayrı `customers/sites/contacts` tabloları AÇILMAZ.** `accounts`, `addresses` ve `contacts` yeniden kullanılır. Rehberdeki "yeni müşteri tablosu YASAK" ve "ayrı lokasyon tablosu açılmaz" kuralı uygulanır.
- **K13 — `addresses`'e SoftDeleteMixin eklenmez.** `is_active` ile pasifleme yapılır, silme ucu yoktur. Gerekçe: `services/belgeler.py:151` silinmiş filtresi yazmıyor; mevcut okuyucuyu değiştirmeden güvenli kalır.
- **K14 — Teknisyen ve atölye rollerinden `hesap.gor` çıkarılır** (E01 §3.3 düzeltmesi, M14-01-ROL). Müşteri seçimi için hafif `musteri-ara` ucu (`servis.gor`; ad + il) yeterlidir. İrtibat yalnız atanan işte görünür.
- **K15 — Hızlı ekleme yetkisi:** `servis.yaz` + `lokasyon.yaz`. Bu, Operasyon, Şef ve Yönetici demektir. Teknisyen ve Atölye hızlı ekleme yapamaz; atölye yeni firmayı `firma_metni` olarak girer, eşleştirmeyle bağlanır.
- **K16 — Açık işte müşteri düzeltme izni:** `servis.planla` VEYA `hesap.yaz`; kapalı işte `hesap.birlestir`. Eski sistemdeki `workorders.create/plan` ve `customers.merge` karşılıklarıdır. Yeni izin açılmaz.
- **K17 — Ekrandan birleştirme hak ediş zincirine dokunamaz.** `work_orders`, `work_order_items` veya hak ediş referansı olan hesap 409 alır. Böyle birleştirmeler yalnız `sistem.goc` betiğiyle yapılır, çünkü kapanmış dönem dökümleri ve altın kayıt testi korunmalıdır.
- **K18 — Takma ad global tekildir** (`alias_key`). Bir yazım yalnız bir hedefe gider; eşleştirme deterministik kalır, belirsiz yazım 409 ile insana döner.
- **K19 — Birleştirme mantığı `services/hesap_birlestir.py`'ye taşınır.** Komut satırı betiği o servisi çağırır. Gerekçe: aynı kural iki yerde yaşamasın; FK listesi şemadan okunmaya devam etsin.
- **K20 — `unvan_anahtari` yeni fonksiyondur;** `tr_normkey` ve `title_key` değişmez, çünkü mobilite araması ve içe aktarma onlara bağlı.
- **K21 — Kartta ve servis tarafında tutar alanları** (teklif toplamı, sözleşme ücreti, kiralama bedeli) yalnız `sees_cost` ile döner. Kapsam bilgisinde hiç tutar yoktur. Gerekçe: "fiyat/maliyet API seviyesinde gizli" kuralı.
- **K22 — Canlı `/api/hesaplar/{id}/kart` ucu değiştirilmez.** Servis bilgisi ayrı uçtan gelir; mobilite kartı regresyonsuz kalır.
- **K23 — Sözleşme dönem çakışmasına EXCLUDE kısıtı konmaz.** Onaylı istisna gerektiği için kural servis katmanında 409 + onay olarak uygulanır. Ekipmanın iki sözleşmede eş zamanlı kapsamı ise E04 `ex_mci_ekipman_cakisma` ile şemada kalır.
- **K24 — Teklif PDF adres seçimi** tesis satırını atlayacak şekilde tek sorguda düzeltilir. Var olan satırlar MERKEZ olduğu için çıktı bugün değişmez; servis tesisleri eklendikten sonra yanlış adres basılması önlenir.
