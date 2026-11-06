# E04 — Planlı Bakım Sözleşmeleri ve Dijital Servis Formu: Canlı ERP Entegrasyon Tasarımı

> Tarih: 21.10.2026 · Hedef: **Denge Mobilite ERP** (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdi: `analiz/02_moduller/_ozet/04_planli_bakim.json` (19 onaylı madde), `04_planli_bakim_tasarim.md`, `04_planli_bakim_denetim.md`, `05_ESKI_SISTEM_ISLEV_ENVANTERI.md` (E-11, §2.10, §5.1), `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`
> Bağlayıcı rehber: `00_MIMARI_KURALLAR.md`. Bu belgedeki her tablo, izin, uç ve test o rehberin kalıbına göre yazıldı.
> Kaynak koda dokunulmadı; yalnız okundu. Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köklerine göredir.

---

## 0. Özet

1. **Canlıda karşılık yok.** `backend/app` ve `frontend/src` içinde `bakim|maintenance|sözleşme formu|kontrol listesi|müşteri onayı` araması planlı bakıma ait hiçbir model, servis, uç ya da sayfa döndürmedi (21.10.2026, Grep). Bulunan "sözleşme" eşleşmelerinin tamamı **abonelik** sözleşmesi (`models/subscription.py`, ek sahibi `contracts` → `abonelik.gor`, `api/attachments.py:49`). Bu nedenle 19 gereksinimin tamamı **YOK** ya da **KISMEN**. KISMEN olanlarda yalnız altyapı hazır: PDF (WeasyPrint, `services/pdf.py:53`), içe aktarma çerçevesi (`services/imports/cekirdek.py:90`), `SourceMixin` (`models/mixins.py:97-113`), stok hareketi (`models/stock.py:213-236`), ekler (`models/attachment.py:31-62`), uyarılar (`services/uyarilar.py:47`), ayarlar (`services/settings.py:33`), worker (`worker.py:120-125`).
2. **Abonelik sözleşmesi yeniden kullanılmaz.** Bakım sözleşmesi ayrı bir varlıktır (`maintenance_contracts`). Rehber §5 bunu "aboneliğe dönüştürülmez" diye bağlıyor. Abonelikte dönem başına bakım planı, cihaz kapsamı ve PB üretimi yok. Tahsilat/MRR zincirine bakım ücreti sokmak da kapsam dışı (faturalama kapsam dışı, tasarım §4).
3. **Mimari yerleşim.** Bu modül E01'in açtığı servis iş emri çekirdeğinin (`service_orders`, `SERVIS_IS_EMRI` makinesi, `service_order_events`, `service_holds`, `service_results`) üstüne oturur. PB iş emri `service_orders.tur='PB'` satırıdır. **Mobilite `work_orders` tablosuna hiçbir şey yazılmaz.**
   - Model: `models/servis_bakim.py`. Rehber §6.2 "gerekirse servis_*.py olarak bölünür" diyor; bu modül 11 tablo getirdiği için bölündü.
   - Servis: `services/teknik_servis/bakim.py`, `bakim_uretim.py`, `bakim_formu.py`, `bakim_raporlari.py`, `bakim_sablonlari.py`.
   - Uç: `api/bakim.py`, prefix `/api/teknik-servis/bakim`.
   - Ön yüz: `pages/BakimPage.tsx`, `pages/BakimFormu.tsx`, `api/bakim.ts`.
4. **Korunan iş kuralları:**
   - 1 kapsam cihazı × 1 bakım dönemi = 1 PB iş emri. `uq_so_pb_cihaz_donem` kısmi tekil indeksiyle şemada zorlanır.
   - Seri no metindir, baştaki sıfırlar korunur.
   - Ücret yalnız `sees_cost(user)` ile görülür. Ücret alanı yanıtta, listede ve Excel'de hiç yer almaz.
   - Süre kaydı yoksa "süre kaydı eksik" yazılır, 0 yazılmaz.
   - Mola kişi-saate girmez.
5. **Kullanıcının bizzat doğruladığı işlevler korunur:**
   - Tıklanabilir KPI kutuları → E04-18.
   - Toplu planlama/atama → E04-12.
   - Excel dışa aktarım → E04-18 ve E04-19.
   - Cihaz başına PB iş emri → E04-09.

---

## 1. Bağımlılıklar (diğer entegrasyon modülleri)

| Kod | Bu modülün ondan beklediği | Yoksa ne olur |
|---|---|---|
| **E13** RBAC + birim | `BIRIMLER`, `SCOPE_OWN_UNITS`, `user_units`, `services/teknik_servis/kapsam.py` (`kapsam_birim`, `birim_disinda_mi`), roller `SERVIS_YONETICI/SERVIS_SEF/SERVIS_TEKNISYEN` | Bakım ilk adımda (E04-01) yalnız izinle korunur, birim filtresi E13 gelince eklenir. Yine de E13 sırada önce yer alıyor. |
| **E01** Servis iş emri çekirdeği | `service_orders` (`tur` CHECK'inde `PB`), `SERVIS_IS_EMRI` makinesi, `service_order_events`, `service_holds` (neden listesinde `UYGUNSUZLUK`), `service_results`, servis işi numarası için sequence, "kendi işi" erişim kontrolü (`is_emirleri.erisebilir_mi`) | PB iş emri açılamaz; E04-09 ve sonrası bloke. |
| **E02** Planlama | `service_plans` + `service_plan_members`, toplu planla/ata servisi | E04-12 bloke; PB'ler "planlanmayı bekleyen" olarak kalır. |
| **E03** Kurulu ekipman | `service_equipment` (seri metin, `account_id`, `address_id`, `birim`) | E04-17 bloke; seri/bölge PB formunda tutulur, devralma önceki formdan yapılır. |
| **E09** Saha zaman | `service_time_entries` (faaliyet `MOLA` dahil) | Form çıktısı ve KPI'da "süre kaydı eksik" her kapalı PB için doğru kalır. |
| **E11** Yedek parça | `stock_movements.service_order_id` (nullable FK) | E04-21 bekleyen listesi `document_no = PB no` eşleşmesiyle geçici çalışır. |
| **E07** Teklif | `quotes.service_order_id` (nullable) | Uygunsuzluk aksiyonu teklif bağını `linked_quote_id` ile tek yönlü tutar. |
| **E14** Müşteri/lokasyon | `addresses` nullable genişletmesi (`site_kodu`, `bolge`, `is_active`) | Sözleşme saha adresi mevcut `addresses` satırını kullanır. |

---

## 2. Veri modeli (`models/servis_bakim.py`, `models/__init__.py`'ye kayıt zorunlu)

Bütün ana tablolar `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin` alır. Göç edilen tablo ayrıca `SourceMixin` + `uq_<tablo>_kaynak` alır. İstisna değişmez kayıtlardır (ziyaret, üretim kaydı, onay): bunlar yalnız `PkMixin, TimestampMixin, ActorMixin` alır ve API'de güncelleme/silme ucu açılmaz. Enum alanları `String` + Türkçe tuple + adlı `CheckConstraint` ile tanımlanır.

### 2.1 `maintenance_contracts` — bakım sözleşmesi (+ `SourceMixin`)

| Kolon | Tip | Not |
|---|---|---|
| `contract_no` | String(30) | `uq_mc_no`. Yeni kayıtta `BKM-{YYYY}-{seq:05d}` biçimindedir; numara `seq_bakim_sozlesme_no` SEQUENCE'ından gelir, count+1 kullanılmaz. Göç edilende eski anahtar korunur (`BAKIM-0029`). |
| `birim` | String(20) | `ck_mc_birim IN BIRIMLER`, varsayılan `GUVENLIK` |
| `account_id` | FK accounts RESTRICT | Müşteri = `Account(is_musteri)`. Servis katmanında `is_musteri` doğrulanır. |
| `address_id` | FK addresses SET NULL | Saha / lokasyon |
| `contact_id` | FK contacts SET NULL | Saha irtibatı (kişisel veri) |
| `responsible_user_id` | FK users SET NULL | Sorumlu şef |
| `valid_from`, `valid_to` | timestamptz | Sözleşme dönemi, yarı açık `[)`. `ck_mc_aralik`: `valid_to > valid_from`. `ck_mc_aktif_tarih`: `status <> 'AKTIF' OR (valid_from IS NOT NULL AND valid_to IS NOT NULL)`. Tarihi bilinmeyen göç kaydına uydurma tarih yazılmaz; böyle kayıt NULL + `TEYIT_BEKLIYOR` olarak kalır. |
| `annual_frequency` | SmallInteger NULL | `ck_mc_frekans`: `annual_frequency BETWEEN 1 AND 12`, `AKTIF` için zorunlu |
| `fixed_months` | ARRAY(SmallInteger) NULL | Sabit bakım ayları ("5. ve 11. ay"). `ck_mc_sabit_ay`: `fixed_months IS NULL OR cardinality(fixed_months) = annual_frequency` |
| `status` | String(20) | `BAKIM_SOZLESME_DURUMLARI = ('TASLAK','TEYIT_BEKLIYOR','AKTIF','PASIF')`, `ck_mc_durum`. "Süresi doldu" saklanmaz; `valid_to <= now` ile hesaplanır ve yanıtta `suresi_doldu: bool` olarak döner. |
| `teyit_gerekcesi` | Text NULL | Göç/ayrıştırma gerekçesi. `ck_mc_teyit_gerekce`: `TEYIT_BEKLIYOR` ise dolu olmalı. |
| `fee_per_visit`, `contract_total` | Numeric(14,2) NULL | **Ücret**: yalnız `sees_cost` |
| `currency` | String(3) | varsayılan `TRY` |
| `legacy_products_text`, `legacy_period_text`, `legacy_frequency_text` | Text NULL | Eski serbest metinler (salt okunur, iz) |
| `legacy_fee_text` | Text NULL | Ücret metni. **Ücret kuralına tabidir.** |
| `legacy_completed_count` | SmallInteger NULL | Yalnız göç başlangıç değeri (E04-05) |
| `notes` | Text NULL | |

İndeksler: `ix_mc_musteri(account_id)`, `ix_mc_durum_bitis(status, valid_to)`.

### 2.2 `maintenance_contract_items` — kapsam cihazı (tür+adet girilir, satır başına 1 cihaz saklanır)

Kullanıcı ekranda "2 X-Ray + 3 Kapı Dedektörü" girer. Servis bunu **5 satıra** açar: aynı türde sıra no 1..n, her satır 1 fiziksel cihazdır. Bu yapı rehberdeki `contract_item_id` = "1 cihaz" anlamını korur. Böylece "1 cihaz = 1 PB" kuralı tek bir tekil indeksle zorlanabilir.

| Kolon | Not |
|---|---|
| `contract_id` | FK maintenance_contracts CASCADE |
| `equipment_type` | `BAKIM_CIHAZ_TURLERI = ('XRAY','KAPI_DEDEKTORU')`, `ck_mci_tur`. Yeni tür eklemek için CHECK migration'ı elle yazılır; bu ancak M04-13/E04-22 ile gelir. |
| `sira` | SmallInteger. `uq_mci_sira (contract_id, equipment_type, sira) WHERE NOT is_deleted` |
| `equipment_id` | FK service_equipment SET NULL, NULL olabilir. Ekipman bağı E04-17 ile kurulur. |
| `last_serial_no`, `last_zone` | String NULL. Son kapanan formdan devralınan seri/bölge, sonraki döneme önceden dolu gelir. |
| `valid_from`, `valid_to` | timestamptz. Kapsama giriş/çıkış tarihi. Adet azaltma ya da "sökülmüş" onayı satırı silmez, `valid_to` yazar. `ck_mci_aralik`. |
| EXCLUDE | `ex_mci_ekipman_cakisma`: `equipment_id WITH =`, `tstzrange(valid_from, valid_to,'[)') WITH &&`, `WHERE equipment_id IS NOT NULL AND NOT is_deleted`. Aynı ekipman aynı anda iki sözleşmede kapsamda olamaz. |

### 2.3 `maintenance_periods` — bakım dönemi (eski `MaintenancePlans`)

| Kolon | Not |
|---|---|
| `contract_id` | FK CASCADE |
| `cycle_start` | timestamptz. Sözleşme döngüsünün başlangıcı: `valid_from + k yıl`. **Dönem anahtarı takvim yılı değil, sözleşme döngüsüdür** (M04-01). |
| `sequence_no` | SmallInteger. `uq_mp_donem (contract_id, cycle_start, sequence_no)` |
| `target_date` | date |
| `target_manual` | bool. Elle değiştirilmişse yeniden hesaplanmaz. `target_change_reason` Text; `ck_mp_elle_gerekce`: `NOT target_manual OR target_change_reason IS NOT NULL` |
| `closed_at` | timestamptz NULL |
| `closing_kind` | `DONEM_KAPANIS_TURLERI = ('TAMAMLANDI','KISMI','YAPILAMADI','GOC_BASLANGIC')`, `ck_mp_kapanis`. Bütünlük için `ck_mp_kapanis_cift`: `(closed_at IS NULL) = (closing_kind IS NULL)`. |
| `generation_run_id` | FK maintenance_generation_runs SET NULL. PB'leri ilk üreten tur. |

"Yapılan dönem (n/frekans)" sayacı **saklanmaz**. Değeri, döngüdeki `closing_kind IN ('TAMAMLANDI','KISMI','GOC_BASLANGIC')` dönemlerinin sayısıdır. Bu sayede yıl devrinde sayaç sıfırlama ya da yanlış devretme hatası oluşamaz.

### 2.4 `maintenance_generation_runs` — üretim kaydı (değişmez)

`PkMixin, TimestampMixin, ActorMixin` alır. Kolonlar:
- `tetik`: `('ELLE','WORKER','EKSIK_TAMAMLA')`, `ck_mgr_tetik`.
- `created_by`: tetikleyen kullanıcı; worker için NULL (= sistem).
- `generated_count`.
- `skipped`: JSONB `[{contract_id, contract_no, source_ref, musteri, neden_kodu, neden}]`.
- `parametreler`: JSONB (ön açılış günü, tarih).

FK yalnız `users`'a gittiği için tablo `tests/conftest.py` `_TRUNCATE` listesine eklenir.

### 2.5 `service_orders` üzerinde bu modülün kolonları (E01 tablosu, nullable)

- `contract_item_id` → maintenance_contract_items RESTRICT
- `maintenance_period_id` → maintenance_periods RESTRICT
- `ck_so_pb_bag`: `tur <> 'PB' OR (contract_item_id IS NOT NULL AND maintenance_period_id IS NOT NULL)`
- **`uq_so_pb_cihaz_donem`**: (`contract_item_id`, `maintenance_period_id`) `WHERE tur='PB' AND NOT is_deleted`. "1 cihaz = 1 PB" kuralını şemada zorlar ve worker yeniden denemesini idempotent yapar.

E01 bu kolonları kendi migration'ında açmamışsa bu modülün migration'ı ekler. Tablo yenidir, canlı veri içermez.

### 2.6 Form, ziyaret, onay, aksiyon, kapsam dışı, parça

| Tablo | Kolonlar / kısıtlar |
|---|---|
| `maintenance_forms` (Versioned) | `service_order_id` FK CASCADE, `uq_mf_is_emri`. Diğer kolonlar: `template_code`, `template_version`, `serial_no` String(200) metin, `zone`, `performed_work`, `technician_note`, `parts_text` (katalog dışı parça), `bakim_sonucu`. `bakim_sonucu` değerleri `BAKIM_SONUCLARI = ('TAMAMLANDI','UYGUNSUZLUK_VAR','KONTROL_EDILEMEDI','TEKRAR_GIDILECEK')`, `ck_mf_sonuc`. `status`: `('TASLAK','TAMAMLANDI')`, `ck_mf_durum`. Ayrıca `completed_by` FK users (**ad metni değil**) ve `completed_at`. |
| `maintenance_form_checks` | `form_id` CASCADE, `check_code`, `label` (üretimde kopyalanır), `sira`. `result`: `KONTROL_SONUCLARI = ('BEKLIYOR','UYGUN','UYGUNSUZ','KONTROL_EDILEMEDI')`, `ck_mfc_sonuc`. `note` Text. **`ck_mfc_not_zorunlu`**: `result NOT IN ('UYGUNSUZ','KONTROL_EDILEMEDI') OR length(trim(note)) > 0`. `checked_by` FK users, `checked_at`. `uq_mfc_madde (form_id, check_code)`. |
| `maintenance_visits` (değişmez) | `form_id`, `service_order_id`, `visit_no` (`uq_mv_no (form_id, visit_no)`), `visited_at` (Clock). `technician_user_id` FK users; kimlik tutulur, ad tutulmaz. `tur`: `('TAMAMLAMA','YENIDEN_ACMA')`. `bakim_sonucu`, `serial_no`, `zone`, `performed_work`. `checks` JSONB `[{code,label,result,note}]`. `approval_id`. `gerekce` (yeniden açmada zorunlu: `ck_mv_acma_gerekce`). |
| `service_customer_approvals` (değişmez; genel servis formuna da açık) | `account_id`, `address_id`, `visit_date` (date), `approver_name` String(120), `approver_title`. `method`: `('EKRAN_IMZA','KAGIT_FORM','IMTINA')`, `ck_sca_yontem`. `paper_form_no`, `refusal_reason`. `ck_sca_alan`: `KAGIT_FORM → paper_form_no`, `IMTINA → refusal_reason` dolu olmalı. `approved_at` (sunucu Clock, istemciden alınmaz). |
| `service_approval_links` | `approval_id` FK, `service_order_id` FK. `uq_sal_is_emri (service_order_id)`: bir işin tek onayı olur, tek onay çok işe bağlanabilir. |
| `maintenance_nonconformities` (Versioned) | `form_id`, `service_order_id`, `check_code`, `check_label`, `description` (madde notundan kopya). `action_type`: `('YERINDE_GIDERILDI','TEKLIF','ARIZA_IS_EMRI','MUSTERI_KAYNAKLI')` NULL, `ck_mnc_tur`. `responsible_user_id`, `due_date`. `linked_service_order_id` FK service_orders SET NULL, `linked_quote_id` FK quotes SET NULL. `status`: `('ACIK','KAPALI')`, `ck_mnc_durum`. `closed_at`, `closed_by`, `closing_note`; `ck_mnc_kapanis`: KAPALI ise not ve kapatan dolu olmalı. |
| `maintenance_exclusion_requests` (Versioned) | `service_order_id`, `contract_item_id`, `maintenance_period_id`. `reason_code`: `('SOKULMUS','ERISIM_YOK','TASINMIS','MUSTERI_IPTAL')`, `ck_mer_neden`. `description` zorunlu. `requested_by` FK users. `status`: `('TALEP','ONAYLANDI','REDDEDILDI')`. `decided_by`, `decided_at`, `decision_note`. **`ck_mer_kendi_onayi`**: `decided_by IS NULL OR decided_by <> requested_by`. `uq_mer_acik (service_order_id) WHERE status='TALEP'`. |
| `maintenance_part_reports` | `form_id`, `service_order_id`, `product_id` FK products RESTRICT, `qty` (`ck_mpr_adet > 0`), `note`. Bilgi kaydıdır, stok değiştirmez. **Maliyet kolonu yoktur.** |

Kontrol şablonları ilk sürümde **kod sabitidir**: `services/teknik_servis/bakim_sablonlari.py`, `KONTROL_SABLONLARI = {"XRAY": (sürüm, 11 madde), "KAPI_DEDEKTORU": (sürüm, 10 madde)}`. Madde metinleri eski koddan (`Program.cs:3105-3134`) aynen taşınır. PB üretiminde maddeler forma kopyalanır; bu yüzden şablon sonradan değişse de eski formun metni değişmez. Tabloya taşıma işi P3'tür (E04-22).

---

## 3. Durum makineleri (`services/statemachine.py` → `MAKINELER`)

- **`BAKIM_SOZLESMESI`** (yeni):
  - Başlangıç durumları: {`TASLAK`, `TEYIT_BEKLIYOR`}.
  - Geçişler: `TASLAK→{AKTIF,PASIF}`, `TEYIT_BEKLIYOR→{AKTIF,PASIF}`, `AKTIF→{PASIF}`, `PASIF→{AKTIF}`.
  - API önce `BAKIM_SOZLESMESI.dogrula()` çağırır ve yanıtta `sonraki_durumlar` döner (emsal `api/rma.py:103,211`).
  - Makine `MAKINELER`'e eklendiği için meta-test (`tests/unit/test_statemachine.py:8`) onu otomatik sınar.
- **`SERVIS_IS_EMRI`** (E01'e ait): bu modül makineyi değiştirmez, PB'ye özgü **koruma** ekler. Koruma `bakim_formu.pb_gecis_dogrula(is_emri, hedef, baglam)` fonksiyonudur ve E01'in genel durum ucu `tur=='PB'` olduğunda bu fonksiyonu çağırır.
  - `TAMAMLANDI`'ya yalnız `bakim_formu.tamamla()` geçirebilir.
  - `IPTAL`'e yalnız `kapsam_disi_karar(onay=True)` geçirebilir.
  - Diğer yollar 409 döner ve gerekçe "Planlı bakım iş emri bakım formundan kapatılır / cihazı dönemden çıkarmak için Kapsam Dışı talebi açın" olur (E04-10).
  - Yeniden açma için E01 makinesinde `TAMAMLANDI→BEKLEMEDE` geçişi olmalı. Bu geçiş PB'de yalnız `bakim.yeniden_ac` ile kullanılır (E04-20).

---

## 4. İzinler ve roller (`permissions.py`)

| Kod | Modül | Açıklama | Roller |
|---|---|---|---|
| `bakim.gor` | Planlı Bakım | Sözleşme, dönem, uygunsuzluk, KPI görür | SERVIS_YONETICI, SERVIS_SEF (+ YONETIM otomatik, ADMIN) |
| `bakim.yaz` | Planlı Bakım | Sözleşme ekler, düzenler, kapsamı değiştirir, pasifler | SERVIS_YONETICI, SERVIS_SEF |
| `bakim.uret` | Planlı Bakım | Vadesi gelen PB'leri önizler/üretir, eksik PB tamamlar, hedef tarihi gerekçeyle değiştirir | SERVIS_YONETICI, SERVIS_SEF |
| `bakim.form` | Planlı Bakım | PB formunu doldurur/tamamlar, müşteri onayı alır, parça bildirir, kapsam dışı talebi açar | SERVIS_TEKNISYEN, SERVIS_SEF, SERVIS_YONETICI |
| `bakim.onayla` | Planlı Bakım | Kapsam dışı talebini karara bağlar, uygunsuzluk aksiyonuna tür/sorumlu/hedef atar ve kapatır | SERVIS_SEF, SERVIS_YONETICI |
| `bakim.yeniden_ac` | Planlı Bakım | Kapalı PB formunu gerekçeyle yeniden açar | SERVIS_YONETICI |

- **Kapsam.** Bütün bakım uçları ikili filtre uygular: `kapsam_musteri` (`services/accounts.py:29-44`) ve E13'ün `kapsam_birim` fonksiyonu. Tek kayıtta kapsam dışıysa 404 döner. `SERVIS_SEF` ve `SERVIS_TEKNISYEN` `KENDI_BIRIMI` kapsamındadır.
- **Teknisyen sözleşme listesini görmez** (M04-14). Form ucu adresi kendisi döndürür.
- **`maliyet.gor` kümesi değişmez** (`tests/unit/test_permissions.py:21-26`). Sonuç olarak SERVIS_YONETICI bakım ücretini görmez. Gerekirse kişiye `UserPermission(allow, gerekce)` ile istisna verilir (`models/rbac.py:29-52`).
- **Mevcut `TEKNIK_SERVIS` (mobilite) rolüne bakım izni verilmez.**
- **Excel** için `bakim.gor` ile `rapor.disaaktar` birlikte istenir.
- **Özelleştirilmiş DB rolleri.** Seed bunlara yeni izin indirmez (`seeds/dev.py:44-79`). Sürüm notunda bu rollere bakım izinlerinin elle verilmesi gerektiği yazılır.

Uç dosyasındaki takma adlar: `Okuyucu=bakim.gor`, `Yazici=bakim.yaz`, `Uretici=bakim.uret`, `FormYazici=bakim.form`, `Onaylayici=bakim.onayla`, `YenidenAcan=bakim.yeniden_ac`.

---

## 5. Ayarlar, worker, uyarılar, ekler, görev panosu, KVKK

- **`services/settings.py` `DEFAULTS`:**

  | Anahtar | Varsayılan | Anlamı |
  |---|---|---|
  | `bakim_on_acilis_gun` | 30 | PB, hedef tarihten bu kadar gün önce açılır |
  | `bakim_tolerans_gun` | 30 | Uyum ve gecikme penceresi |
  | `bakim_musteri_onayi_zorunlu` | True | İmtina seçeneği olduğu için saha bloke olmaz |
  | `bakim_otomatik_uretim` | False | Worker yalnız açıkken üretir (M04-04a) |
  | `bakim_sozlesme_bitis_uyari_gun` | 60 | Bitişi yaklaşan sözleşme uyarısının eşiği |

- **`worker.py` `GOREVLER`:** `Gorev("bakim-pb-uretimi", timedelta(hours=24), bakim_pb_uretimi)`.
  - Görev ayarı her turda okur. Ayar kapalıysa "otomatik üretim kapalı" özetini döner.
  - Açıksa `bakim_uretim.uret(db, clock, user=None, tetik="WORKER")` çağırır.
  - İdempotenttir: `uq_mp_donem` ve `uq_so_pb_cihaz_donem` ile korunur, ekleme `INSERT ... ON CONFLICT DO NOTHING` ile yapılır.
- **`services/uyarilar.py`:** `if user.has("bakim.gor"):` bloğu eklenir. Sayılar birim ve müşteri kapsamına tabidir, çünkü sayının kendisi de sızıntıdır.

  | Uyarı | Yol |
  |---|---|
  | Geciken bakım dönemi | `/bakim?sekme=donemler&gecikmis=1` |
  | Teyit bekleyen sözleşme | `/bakim?durum=TEYIT_BEKLIYOR` |
  | Bitişi yaklaşan sözleşme | |
  | Açık kapsam dışı talebi | Yalnız `bakim.onayla` sahibine görünür |
  | Stok çıkışı bekleyen PB parçası | Yalnız `cihaz.yaz` sahibine görünür |

- **Ekler.** `models/attachment.py` içinde `EK_SAHIPLERI`'ne `maintenance_contracts` ve `service_customer_approvals` eklenir. `EK_TURLERI`'ne `BAKIM_FORMU` (imzalı kağıt form taraması) eklenir; mevcut `IMZA` türü yeniden kullanılır. `api/attachments.py` iki yerde değişir:
  - `SAHIP_IZNI`: `maintenance_contracts → (bakim.gor, bakim.yaz)`, `service_customer_approvals → (servis.gor, bakim.form)`.
  - `_kapsam`: bu iki varlık için müşteri ve birim kontrolü eklenir. Bugün `_kapsam` yalnız `accounts` için çalışıyor (`api/attachments.py:91-114`).
  - `entity` kolonunda DB CHECK'i yok, bu yüzden migration gerekmez.
- **Görev panosu.** `services/gorevler.py:47-57` `KAYIT_TIPLERI`'ne `KayitTipi("BAKIM_SOZLESMESI", "Bakım Sözleşmesi", MaintenanceContract, ..., yol="/bakim?sozlesme={id}")` eklenir.
- **KVKK.** `services/kvkk.py` anonimleştirme kapsamına `service_customer_approvals.approver_name/approver_title` ve sözleşme `contact_id` bağı girer. Onay kaydının denetim izi `is_personal_data=True` ile yazılır.
- **Denetim izi.** Her yazma ucu commit'ten önce `audit.log` / `audit.log_change` çağırır. Eylemler:
  - `bakim.sozlesme.olustur`, `bakim.sozlesme.durum`, `bakim.kapsam.degistir`
  - `bakim.donem.hedef_degistir`, `bakim.uret`
  - `bakim.form.tamamla`, `bakim.form.yeniden_ac`
  - `bakim.kapsam_disi.talep`, `bakim.kapsam_disi.karar`
  - `bakim.uygunsuzluk.kapat`, `bakim.onay.olustur`

---

## 6. API uçları (`api/bakim.py`, prefix `/api/teknik-servis/bakim`, `main.py:182-209`'a elle kayıt)

| Yöntem ve yol | İzin | Not |
|---|---|---|
| `GET /sozlesmeler` | bakim.gor | `sayfala`. Filtreler: durum, birim, müşteri, `q`, `gecikmis`, `suresi_doluyor`. Ücret alanları yalnız `sees_cost` ile döner. |
| `GET /sozlesmeler/{id}` | bakim.gor | kapsam → 404 |
| `POST /sozlesmeler` | bakim.yaz | `kapsam: [{tur, adet}]` ile kalemleri açar. Ücret alanı gönderilir ve `sees_cost` false ise 403 döner. |
| `PATCH /sozlesmeler/{id}` | bakim.yaz | `version` zorunlu, uyuşmazlıkta 409. Tarih veya frekans değişirse elle olmayan ve henüz PB'si olmayan dönemler yeniden hesaplanır. Birim değişiyorsa hedef birim kullanıcının birimlerinde olmalı. |
| `POST /sozlesmeler/{id}/durum` | bakim.yaz | `BAKIM_SOZLESMESI.dogrula` |
| `PUT /sozlesmeler/{id}/kapsam` | bakim.yaz | Tür+adet farkını uygular: artışta satır açar, azalışta `valid_to` yazar. PB'si açık satır kapatılamaz (409). |
| `GET /donemler` | bakim.gor | Filtreler: sözleşme, `gecikmis`, `acik`, `ay`, sorumlu şef. Yanıtta yapılan/frekans, açık/tamamlanan PB sayısı. |
| `GET /donemler/{id}/cihazlar` | bakim.gor | PB no, cihaz #sıra, seri, bölge, durum, form durumu |
| `PATCH /donemler/{id}/hedef-tarih` | bakim.uret | `{hedef_tarih, gerekce}` → `target_manual=true` |
| `POST /donemler/{id}/eksik-pb` | bakim.uret | Eksik cihaz PB'lerini idempotent tamamlar |
| `POST /uretim/onizleme` | bakim.uret | **DB'ye yazmaz.** `{uretilecek:[{sozlesme, donem, hedef, cihaz_sayisi, pb_sayisi}], atlanacak:[...]}` |
| `POST /uretim` | bakim.uret | `{run_id, generated, skipped:[{contract_id, contract_no, source_ref, musteri, neden_kodu, neden}]}` |
| `GET /uretim-kayitlari` | bakim.gor | |
| `GET /formlar/{service_order_id}` | servis.gor + E01 kayıt erişimi + birim | Form, maddeler, adres, ekipman, önceki ziyaretler. Maliyet alanı yoktur. |
| `PUT /formlar/{service_order_id}` | bakim.form + erişim | Taslak kaydeder. `version`. Ziyaret kaydı **oluşturmaz**. |
| `POST /formlar/{service_order_id}/tamamla` | bakim.form + erişim | Doğrulama + ziyaret + aksiyon + bekleme + dönem kapanışı (E04-09, 13, 14, 15) |
| `POST /formlar/{service_order_id}/yeniden-ac` | bakim.yeniden_ac | `{gerekce}` zorunlu |
| `GET /formlar/{service_order_id}/ziyaretler` | servis.gor + erişim | Salt okunur; PUT/DELETE ucu yoktur |
| `GET /formlar/{service_order_id}/form.pdf` | Form ucuyla aynı | Fiyat içermez |
| `POST /onaylar` | bakim.form | `{service_order_ids[], approver_name, approver_title, method, paper_form_no?, refusal_reason?}`. Bütün işler aynı müşteri + adres + gün olmalı, aksi 409. |
| `GET /onaylar/{id}/form.pdf` | servis.gor + erişim (tüm bağlı işler) | Ziyaret toplu çıktısı |
| `POST /formlar/{service_order_id}/kapsam-disi` | bakim.form + erişim | Talep açar |
| `GET /kapsam-disi` | bakim.gor | |
| `POST /kapsam-disi/{id}/karar` | bakim.onayla | `{onay, not}`. Kendi talebini onaylama denemesi 409 döner; şemada `ck_mer_kendi_onayi` ayrıca korur. |
| `GET /uygunsuzluklar` | bakim.gor | Filtreler: durum, sorumlu, yaş (gün), müşteri |
| `PATCH /uygunsuzluklar/{id}` | bakim.onayla | Tür, sorumlu, hedef tarih, `linked_quote_id` |
| `POST /uygunsuzluklar/{id}/ariza-isi` | bakim.onayla + servis.yaz | Önceden doldurulmuş form gövdesiyle E01 `is_emirleri.olustur(tur='ARIZA')` çağrılır ve bağ tek transaction'da kurulur |
| `POST /uygunsuzluklar/{id}/kapat` | bakim.onayla | `closing_note` zorunlu |
| `GET /parca-bildirimleri` | bakim.gor veya cihaz.yaz | `?stok_cikisi_bekleyen=1` |
| `GET /raporlar/ozet` | bakim.gor | KPI kutuları |
| `GET /raporlar/geciken-donemler` | bakim.gor | |
| `GET /raporlar/uygunsuzluk` | bakim.gor | |
| `GET /raporlar/bakim.xlsx` | bakim.gor + rapor.disaaktar | `services/export.py` `satirlari_xlsx_async` |
| `GET /ekipman/{equipment_id}/bakim-gecmisi` | servis.gor + birim | E03 ekipman kartı da bu ucu çağırır |

Hata kodları canlı kalıbını izler: kural ihlali 409, girdi hatası 400, yetki 403, kapsam dışı/yok 404.

---

## 7. Ön yüz

- **Menü** (`components/AppLayout.tsx` MENU): `{ key: "/bakim", label: "Planlı Bakım", icon: <SafetyCertificateOutlined/>, izin: "bakim.gor" }`. "Servis İşleri" (E01) kaleminin hemen altına konur. Rota `main.tsx` içinde `AppLayout` altına eklenir.
- **`pages/BakimPage.tsx`:**
  - Sekmeler: Sözleşmeler | Bakım Dönemleri | Uygunsuzluklar | Kapsam Dışı Talepleri | Üretim Kayıtları.
  - Üstte **tıklanabilir KPI kartları** (`Card hoverable onClick`, `components/Statistic.tsx`): Bakım Sözleşmesi, Vadesi Gelen, Geciken Dönem, Açık PB, Tamamlanan PB Cihazı, Uyum Oranı, Süre Kaydı Eksik PB, Teyit Bekleyen. Tıklayınca ilgili sekmeye filtreli geçer (URL query); liste her zaman sayının sorgusuyla aynı sorgudan gelir. Bu, eski H-02 hatasını (sayı ve liste farklı koşul) önler.
- **Sözleşme penceresi** `KartPenceresi` kalıbındadır: tek form hem yeni kayıt hem düzenleme içindir.
  - Alanlar: müşteri (hesap arama), saha adresi, irtibat, sorumlu şef, başlangıç/bitiş (`DD.MM.YYYY`), yıllık adet, sabit aylar (çoklu seçim), birim.
  - Kapsam `Form.List` ile tür+adet olarak girilir.
  - Ücret alanları yalnız `yetkili("maliyet.gor")` ile görünür.
  - Ek dosyalar `EkYukleyici entity="maintenance_contracts"` ile, görev bağlantısı `KayitGorevleri` ile eklenir.
- **Dönem Drawer'ı:**
  - Cihaz PB tablosunda satır seçimi vardır. Kapalı satırlar devre dışıdır; farklı lokasyon seçimi engellenir.
  - **"Seçilenleri Planla + Ata"** E02'nin toplu planlama bileşenini açar (E04-12).
  - "Eksik PB'leri Oluştur" ve "Hedef Tarihi Değiştir" (gerekçe zorunlu) düğmeleri vardır.
- **Üretim:** "Vadesi Gelenleri Önizle" düğmesi önizleme tablosunu gösterir, "Üret" ile üretim yapılır. Atlanan sözleşmeler **kırmızı `Alert` + tablo** olarak gösterilir (neden, kaynak anahtarı).
- **`pages/BakimFormu.tsx`** (Drawer, `size={680}`). Servis İşi detayındaki "Bakım Formunu Aç" düğmesinden ve dönem listesinden açılır.
  - Başlık "DİJİTAL TEKNİK SERVİS / PLANLI BAKIM FORMU". Alanlar: Seri No* (mono, metin), Bölge*, adres (salt okunur).
  - Her kontrol maddesinde 4 seçenekli `Radio.Group` bulunur. Uygunsuz veya Kontrol Edilemedi seçilince not alanı açılır ve zorunlu olur.
  - "Kontrol Edilenlerin Tümünü Uygun İşaretle" düğmesi `Popconfirm` ister ve yalnız BEKLIYOR olanları işaretler.
  - Diğer alanlar: Yapılan İşlem, Parça (katalog `Select` + adet, ayrıca katalog dışı metin), Teknisyen Notu*, Bakım Sonucu*.
  - **Müşteri onayı bloğu:** ad-soyad, unvan, yöntem; KAGIT_FORM için form no, IMTINA için gerekçe. "Bu ziyaretteki diğer formlara da uygula" seçeneği aynı müşteri+adres+gün PB'lerini listeler.
  - Düğmeler: Taslak Kaydet / Formu Tamamla / Kapsam Dışı Talebi / Form Çıktısı (PDF).
  - `Timeline` ile ziyaret geçmişi ve olaylar gösterilir.
  - Salt okunur durumlar: form TAMAMLANDI ise ya da kullanıcıda `bakim.form` yoksa. Yeniden aç düğmesi yalnız `bakim.yeniden_ac` sahibine görünür.
- **`src/api/bakim.ts`:** tipler ve fonksiyonlar. Listeler `api.getSayfa`, mutasyonlar `invalidateQueries(["bakim", ...])` kullanır. 409 gelince "Kayıt başkası tarafından değiştirildi, yenileyin" gösterilir.

---

## 8. Migration planı (head: `b30e012dd879` → E13 → E01 → E02/E03 → bu modül; kodlama başında `alembic heads` ile yeniden doğrulanır)

1. **`bakim_sozlesme_donem_uretim`**
   - Sequence `seq_bakim_sozlesme_no` oluşturulur.
   - Tablolar: `maintenance_contracts`, `maintenance_contract_items` (EXCLUDE autogenerate kalıbı, `versions/28bd1a023e28_...py:175` biçimi), `maintenance_periods`, `maintenance_generation_runs`.
   - `service_orders` tablosuna `contract_item_id`, `maintenance_period_id`, `ck_so_pb_bag` ve kısmi `uq_so_pb_cihaz_donem` eklenir. Bu tablo E01'in yeni tablosudur, canlı mobilite tablosu değildir.
2. **`bakim_formu_ziyaret_onay`**
   - Tablolar: `maintenance_forms`, `maintenance_form_checks`, `maintenance_visits`, `service_customer_approvals`, `service_approval_links`, `maintenance_nonconformities`, `maintenance_exclusion_requests`, `maintenance_part_reports`.

Her dosyanın başına NEDEN docstring'i yazılır. `downgrade` zorunludur; tabloları ters FK sırasıyla düşürür. Head→base→head testinden geçmeli ve EXCLUDE sayısını korumalıdır. `work_orders`, `work_order_items`, `settlements`, `devices`, `device_vehicle_assignments` ve stok EXCLUDE kısıtlarına **hiçbir migration dokunmaz**. `attachments` için migration gerekmez.

---

## 9. Testler

| Dosya | Kapsam |
|---|---|
| `tests/unit/test_bakim_takvim.py` | Hedef tarih hesabı:<br>• 01.06.2026 başlangıç, frekans 3 → 01.06.2026, 01.10.2026, 01.02.2027.<br>• Sabit aylar.<br>• Ay sonu kırpma (31 → 28/29).<br>• Bitiş sonrası dönem üretilmez. |
| `tests/unit/test_bakim_ayristirma.py` | Göç ayrıştırıcısı:<br>• "4 X-RAY 9 KAPI DEDEKTÖRÜ" → (4,9).<br>• "7 ADET KAPI DEDEKTÖRÜ" → teyit.<br>• "11 X-RAY 8 KAPI DEDEKTÖÜ" → kısmi + teyit.<br>• "600 X-RAY" → aralık dışı.<br>• Dönem metinleri: "17.02.2026-17.02-2027", "5. VE 11. AYDA", NULL. |
| `tests/unit/test_statemachine.py` | `BAKIM_SOZLESMESI` `MAKINELER`'e girdiği için otomatik sınanır |
| `tests/unit/test_permissions.py` | Mevcut: her yeni izin bir role atanmış; `maliyet.gor` kümesi değişmemiş; YONETIM yazma izni almamış |
| `tests/integration/test_bakim_sozlesme.py` | • CRUD.<br>• 2 X-Ray + 3 kapı → üretimde 5 PB.<br>• Ücret: yetkisiz kullanıcının yanıtında anahtar yok; gönderirse 403 ve DB değişmemiş.<br>• Pasif sözleşme üretime girmez.<br>• `version` uyuşmazlığı 409.<br>• Her uçta 403/200. |
| `tests/integration/test_bakim_uretim.py` | • Önizleme satır sayısını değiştirmez.<br>• İkinci üretim 0 PB.<br>• Worker ayar kapalıyken üretmez.<br>• `created_by` = tetikleyen kullanıcı.<br>• FakeClock 02.01.2027: 2026 döngüsü tamamlanmış sözleşmenin yeni dönemleri tamamlandı sayılmaz, açık 2026 dönemi gecikmiş görünür.<br>• Bozuk sözleşme `skipped`'e düşer, diğerleri üretilir.<br>• E01 arıza işinin kapanışı PB üretmez. |
| `tests/integration/test_bakim_formu.py` | • Not zorunluluğu (400 ve `ck_mfc_not_zorunlu`).<br>• BEKLIYOR madde varken tamamlama 409.<br>• Uygunsuz → BEKLEMEDE, aksiyon açılır, `service_holds` kaydı oluşur.<br>• Ziyaret: taslak kaydetme ziyaret oluşturmaz; iki tamamlama iki ziyaret üretir ve ilki korunur.<br>• Onay zorunlu iken onaysız tamamlama 409; imtina gerekçesiz 400.<br>• Onay zamanı FakeClock'tan gelir.<br>• Yeniden açma: izinsiz 403, gerekçesiz 400; dönem kapanışı geri alınır. |
| `tests/integration/test_bakim_kapsam_disi.py` | • 2 tamamlandı + 1 onaylı kapsam dışı → dönem KISMI kapanır ve bir kez sayılır.<br>• Onaysız talep dönemi kapatmaz.<br>• Kendi talebini onaylama 409.<br>• PB'ye genel uçtan IPTAL/TAMAMLANDI → 409. |
| `tests/integration/test_bakim_kapsam_guvenligi.py` | • İki birim, iki şef: liste boş, GET 404, PATCH 404 **ve** `db.refresh` ile değişmemiş.<br>• Ek listesi 404.<br>• Uyarı sayısı yalnız kendi birimi.<br>• Teknisyen sözleşme listesinde 403 alır. |
| `tests/integration/test_bakim_rapor.py` | • 10 vadeli dönemin 7'si tolerans içinde → %70, geciken listesi 3.<br>• Süre kaydı olmayan kapalı PB ayrı sayılır.<br>• Excel'de ücret kolonu `sees_cost` yoksa yok. |
| `tests/integration/test_bakim_goc.py` | • İki kez yükleme aynı sonucu verir.<br>• Ekrandan pasiflenen sözleşme ikinci yüklemede pasif kalır. |
| `tests/migration/test_altin_kayit.py` | Değişmeden yeşil kalmalı: 932 iş / 552.825,00 TL |

Yeni tablolardan `maintenance_generation_runs` `_TRUNCATE` listesine eklenir. Diğerleri accounts ve service_orders zincirine FK ile bağlı olduğu için CASCADE ile temizlenir.

---

## 10. Madde listesi

Her maddenin canlı durumu, karşılığı, yaklaşımı, kabulü, önceliği, eforu ve bağımlılığı StructuredOutput çıktısında ayrıntılı verilmiştir. Kısa liste:

| ID | Kaynak | Başlık | Canlı | Öncelik | Efor |
|---|---|---|---|---|---|
| E04-01 | M04-14 (izin kısmı), tasarım §1.5/§2.1, S8 | Bakım izinleri, roller, birim/müşteri kapsamı, menü | YOK | P1 | S |
| E04-02 | M04-03 | Bakım sözleşmesi yönetimi + tür+adet kapsam | YOK | P1 | L |
| E04-03 | M04-D02 | 87 sözleşmenin yapısal göçü + Excel teyit listesi | KISMEN | P1 | M |
| E04-04 | M04-D03 | Göç/yükleme ekrandan girilen veriyi ezmez | KISMEN | P1 | S |
| E04-05 | M04-01 | Dönem modeli; tamamlanan adet dönemden hesaplanır | YOK | P1 | M |
| E04-06 | M04-02 | Üretim motoru: gerekçeli `skipped`, tek hata durdurmaz | YOK | P1 | S |
| E04-07 | M04-04a | Üretim kapanıştan ayrı; tetikleyen kaydı; worker ayara bağlı | KISMEN | P1 | S |
| E04-08 | M04-04b | Sözleşme başlangıcına göre hedef, elle tarih, önizleme, üretim kaydı, ön açılış | YOK | P2 | M |
| E04-09 | Eski işlev E-11 + M04-08/M04-14 önkoşulu | Cihaz başına PB iş emri ve dijital form çekirdeği | YOK | P1 | M |
| E04-10 | M04-D01 | PB'nin genel uçtan İptal/Tamamlandı yapılmasının engeli | YOK | P1 | S |
| E04-11 | M04-10 | Kapsam dışı talebi + şef onayı + kısmi dönem | YOK | P1 | S |
| E04-12 | Eski işlev [✔K] toplu planla/ata | PB'lerin toplu planlanması ve atanması | YOK | P1 | M |
| E04-13 | M04-08 | Değişmez ziyaret kaydı | YOK | P2 | M |
| E04-14 | M04-05 | Uygunsuzluk: not zorunlu, bekleme, aksiyon, bağlı arıza işi | YOK | P2 | M |
| E04-15 | M04-06 | Müşteri onayı (ziyaret bazlı tek onay), zorunluluk ayarı | KISMEN | P2 | M |
| E04-16 | M04-07 | Teknik Servis Formu çıktısı (PDF) | KISMEN | P2 | M |
| E04-17 | M04-09 | Ekipmana kimlikle bağ, devralma, bakım geçmişi ucu | YOK | P2 | M |
| E04-18 | M04-12a + [✔K] KPI/Excel | KPI adım 1: tıklanabilir kutular, geciken, uyum, süre eksik, Excel | KISMEN | P2 | M |
| E04-19 | M04-12b | KPI adım 2: uygunsuzluk oranı, en sık 5 madde, aksiyon yaşı, onaysız kapanış | YOK | P2 | M |
| E04-20 | M04-14 | Kullanıcı kimliği, gerekçeli yeniden açma, sözleşme listesi izni | KISMEN | P2 | M |
| E04-21 | M04-11 | Katalogdan parça bildirimi + stok çıkışı bekleyen listesi | KISMEN | P3 | S |
| E04-22 | M04-13 | Kontrol şablonlarının veriye taşınması (ertelendi) | YOK | P3 | M |
| E04-23 | Rehber §1.13-1.14, M04-12a | Uyarılar, görev panosu, KVKK entegrasyonu | KISMEN | P2 | S |

**Uygulama sırası:**
1. Veri güvencesi ve çekirdek: E04-01 → E04-02 → E04-05 → E04-06 → E04-07 → E04-03 → E04-04 → E04-09 → E04-10 → E04-11 → E04-12.
2. Yeni özellik: E04-08 → E04-16 → E04-15.
3. Eksik: E04-18 → E04-13 → E04-14 → E04-17 → E04-19 → E04-23.
4. Güvenlik: E04-20.
5. P3: E04-21, E04-22.

---

## 11. Kararlar (kullanıcıya soru sorulmadı; gerekçeli)

1. **S1 (uygunsuzlukta dönem):** Açık aksiyon varken PB `TAMAMLANDI` olamaz, BEKLEMEDE kalır. Dönem de bu yüzden açık kalır. Gerekçe: eski davranış ve onaylı kabul kriteri ("açık aksiyonla PB Tamamlandı kapatılamaz") bunu gerektiriyor. KPI'da "bakımı yapıldı, uygunsuzluk açık" ayrı sayılır; yönetim taahhüdün fiilen yerine getirildiğini görebilir.
2. **S2/S3 (onay):** `bakim_musteri_onayi_zorunlu=True` varsayılandır. Yöntemler EKRAN_IMZA / KAGIT_FORM / IMTINA olduğu için saha hiçbir zaman bloke olmaz. Ziyaret (müşteri + adres + gün) başına tek onay birden çok PB'ye bağlanır.
3. **S4:** Hedefler eşit aralıkla sözleşme döngüsü başlangıcından hesaplanır; sabit aylar girilirse onlar kullanılır. Ön açılış 30 gün, tolerans 30 gün; ikisi de ayardır.
4. **S5:** Basılı formun örneği yok. Çıktı, eşleme tablosundaki alanları içeren tek düzen olarak üretilir. Birebir düzen sonra yalnız şablon dosyası değiştirilerek sağlanır.
5. **S6/S7:** Ölçüm alanı ve yeni cihaz türü yok. Şablonlar kod sabiti olarak kalır; E04-22 P3'e ertelendi.
6. **S8:** Sözleşme yazma yetkisi `bakim.yaz` ile SERVIS_YONETICI ve SERVIS_SEF'tedir; şef birim kapsamıyla sınırlıdır.
7. **S9:** Teyit sorumlusu SERVIS_YONETICI'dir. Göç teyit listesi Excel'i onun ekranından indirilir/yüklenir. SEGATECH, KENTPARK, Ziraat, Sanko, `CompletedCount>0` olanlar ve süresi dolmuşlar bu listeye düşer.
8. **S10:** Parça bildirimi yalnız bilgi kaydıdır. Stok çıkışı depoda mevcut `POST /api/stok/hareket` (`cihaz.yaz`, `api/stock.py:296`) ile ve PB'ye bağlı yapılır. Ayrı onay akışı kurulmaz.
9. **İmza/fotoğraf depolama:** Eski sistemdeki "DB mi dosya mı" sorusu canlıda zaten çözülü. `services/storage.py` (disk, sha256, 25 MB, MIME doğrulama) ve `attachments` tablosu kullanılır. KVKK saklama süresi mevcut `kvkk_saklama_yili` ayarına bağlanır.
10. **PDF yöntemi:** Denetim "print CSS" önermişti; gerekçesi eski sistemin ASCII PDF fonksiyonuydu. Canlıda Türkçe karakter ve görseli destekleyen WeasyPrint var (`services/pdf.py:53`). Bu yüzden sunucu PDF'i seçildi: `templates/servis_formu.html` + `belgeler.servis_formu_baglami`. Tarayıcıda satır içi açılır, ayrı bir yazdırma düzeni gerekmez.
11. **Hata kodu:** Onaylı kabullerde "400" geçen kural ihlalleri canlı kalıbında 409'dur. Örnekler: PB'ye İptal, onaysız tamamlama, BEKLIYOR madde. Girdi biçimi hataları 400 kalır: tanımsız durum metni, gerekçesiz imtina, notsuz uygunsuz madde.
12. **Kapsam modeli:** İlk sürümde yalnız tür+adet vardır (denetim kararı). Tür+adet satırları servis tarafında cihaz başına satıra açılır. Böylece "1 cihaz = 1 PB" kuralı tek tekil indeksle zorlanır, ekipman bağı sonradan aynı satıra eklenir.
13. **Sayaç saklanmaz.** "Yapılan dönem" ve "CompletedCount" sayıları dönem kapanışlarından hesaplanır. Eski sayaç yalnız `legacy_completed_count` + `GOC_BASLANGIC` kapanışı olarak göç döngüsüne uygulanır.
14. **Dönemler birbirini bloke etmez.** Eski sistemde sıradaki dönem `CompletedCount+1` ile seçiliyordu ve tek açık cihaz bütün yılı kilitliyordu. Yeni sistemde vadesi gelen her dönemin PB'leri bağımsız üretilir.
15. **Süresi dolan sözleşme:** Yeni dönem ve PB üretilmez (`SURESI_DOLMUS` atlama gerekçesi). Açık kalan dönemler gecikmiş listesinde görünmeye devam eder. Yenileme `valid_to` uzatılarak aynı sözleşmede yapılır.
16. **Ücret yetkisi:** Canlıdaki `maliyet.gor` (eski `finance.prices.view` karşılığı) kullanılır. Yeni rol bu izni almaz, çünkü küme unit testle kilitli.
17. **Numaralar:**
    - Sözleşme no `seq_bakim_sozlesme_no` sequence'ından gelir.
    - PB servis işi no `PB-{hedefYYYYMM}-{seq:05d}` biçimindedir. Önek eski raporlarla ve kullanıcı alışkanlığıyla uyumludur; numara E01'in sequence'ından gelir.
    - count+1 / max+1 kullanılmaz.
18. **Birim:** Sözleşme her birime açılabilir. Eski kural tablosunda Araç Takip'te "Bakım" iş türü var. Ancak şablonu olmayan tür için PB üretilmez ve `SABLON_YOK` gerekçesiyle atlanır. Varsayılan birim GUVENLIK'tir.
19. **Teknisyen sözleşme listesini görmez.** Formda adres ve müşteri bilgisi zaten döner (M04-14 denetim kararı).
20. **Arıza servis işi otomatik açılmaz.** Uygunsuzluk ekranındaki düğme önceden dolu formla E01 servis fonksiyonunu tek transaction'da çağırır ve bağı kurar.
21. **Göç kanalı:** Yeni bir başlangıç seed'i yazılmaz. Canlıda iş verisi seed'i yok; `seeds/dev.py` yalnız izin ve rol yazıyor. Göç iki adımda yapılır: `app/migration/bakim_sozlesme.py` (eski döküm → ayrıştırılmış ara Excel) ve `services/imports/bakim_sozlesme.py` profili (`PROFILLER`'e eklenir). `source_system='DENGEERP_V1'`, `source_ref='BAKIM-00NN'`. Var olan kayıt yalnız `TEYIT_BEKLIYOR` durumundaysa güncellenir; aksi halde "ekrandan yönetiliyor, korundu" diye raporlanır.

---

## 12. Canlı akış riskleri ve önlemler

| Risk | Önlem |
|---|---|
| Hak ediş/uyarı/panel sayılarının kirlenmesi | Bakım hiçbir zaman `work_orders`/`work_order_items`'a yazmaz. `services/reports.py` ve `uyarilar.py`'deki mevcut bloklar değiştirilmez, yalnız yeni blok eklenir. Altın kayıt testi her adımda koşar. |
| Mobilite `TEKNIK_SERVIS` rolünün anlamı | Bu role izin eklenmez, yeni roller ayrı kodla açılır |
| `maliyet.gor` küme testi | Yeni rol maliyet izni almaz |
| Ek kimliklerinin taranması | `_kapsam` yeni varlıklar için genişletilir. Genişletilmezse ek uçları yalnız izinle korunur, bu yüzden ek bağlantısı E04-23 ile birlikte açılır. |
| EXCLUDE/CHECK migration hataları | Canlı tablolara kısıt eklenmez. Yeni tablolar autogenerate kalıbını izler, downgrade testten geçer. |
| Worker yeniden denemesinde çift PB | `uq_so_pb_cihaz_donem` + `ON CONFLICT DO NOTHING`; sözleşme başına SAVEPOINT |
| Uyarı sayısıyla sızıntı | Uyarı sayıları da birim ve müşteri kapsamıyla süzülür |
