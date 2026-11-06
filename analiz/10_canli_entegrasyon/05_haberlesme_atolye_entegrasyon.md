# E05 — Haberleşme Atölyesi: Canlı ERP Entegrasyon Tasarımı

> **Tarih:** 2026-10-21 · **Hedef:** Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`, yalnız OKUNDU, hiçbir dosya değiştirilmedi)
> **Girdi:** `analiz\02_moduller\_ozet\05_haberlesme_atolye.json` (24 onaylı madde), `05_haberlesme_atolye_tasarim.md`, `05_haberlesme_atolye_denetim.md`, `05_ESKI_SISTEM_ISLEV_ENVANTERI.md` (E-12, L-25..L-27, R-63/R-64, H-08/H-13), `10_canli_entegrasyon\00_MIMARI_KURALLAR.md` (bağlayıcı)
> **Bağımlılık zinciri:** RBAC + birim adımı (00 §6.3) → Servis iş emri çekirdeği (E01: `service_orders`, `service_order_events`, `service_holds`, `SERVIS_IS_EMRI` makinesi, tek atama kaynağı) → Zaman kaydı (E09: `service_time_entries`) → Kurulu ekipman (E03: `service_equipment`) → **E05 Atölye**. Yedek parça (E11: `stock_movements.service_order_id`) ve teklif köprüsü (E07: `quotes.service_order_id`) E05'in salt okunur görünümleri için gereklidir.
> Dosya:satır referansları `backend/app/...` köküne göredir.

---

## 1. Özet ve yerleşim kararı

**Canlıda atölye kavramı hiç yok.** `atolye|workshop|telsiz` araması yalnız `models/account.py:48` (`HYTERA_BAYI` segmenti) sonucunu veriyor. 24 maddenin 18'i **YOK**, 6'sı **KISMEN** (altyapı var, atölyeye uygulanmamış). Yeniden kullanılacak hazır altyapı: durum makinesi sınıfı (`services/statemachine.py:27-83`), RMA garanti hesabı ve "açık kayıt varken ikincisi açılmaz" kalıbı (`services/rma.py:43-117`), PDF (Jinja2 + WeasyPrint, `services/pdf.py`, `services/belgeler.py`), Excel (`services/export.py`), ekler (`models/attachment.py`), sayfalama (`api/deps.py:170`), iyimser kilit (`models/mixins.py:70-86`), maliyet gizleme (`api/deps.py:103-105`), uyarılar (`services/uyarilar.py:47`), ayarlar (`services/settings.py:33-93`).

### 1.1 TEK karar: "1 atölye kaydı = 1 cihaz = 1 servis işi", durum tek yerden yürür

Eski sistemdeki hataların (M05-10/11/12/14/15, D01, D02) ortak kökü, atölye kaydı ile iş emrinin **iki ayrı durum, iki ayrı atama, iki ayrı seri no** tutmasıydı. Yeni yerleşim bunu yapısal olarak kapatır:

| Kavram | Nerede tutulur | Neden |
|---|---|---|
| Atölye kaydı (kabul, teşhis, onarım, onay, aksesuar, teslim, dış servis, tamir bedeli) | **Yeni** `workshop_records` (+ `workshop_accessories`) | Atölyeye özgü alanlar servis iş emrini kirletmesin |
| İş kimliği, müşteri, birim, **atama**, zaman kaydı, parça, bekleme, olay geçmişi, ekler, görev kartı | **E01** `service_orders` (tür `ATOLYE`) ve onun yardımcı tabloları | Teknisyenin "işlerim" listesi, sayaç, SLA, parça tüketimi tek kaynaktan çalışsın (M05-10, M05-16) |
| Seri no, marka, model | **E03** `service_equipment` (seri METİN) | Seri no tek kaynak (M05-14); düzeltme her yerde görünür |
| Atölye durumu | `workshop_records.status` + yeni **`ATOLYE`** makinesi | Atölye akışı servis akışından ayrıntılı |
| Servis işi durumu (tür `ATOLYE`) | `service_orders.status`, **YALNIZ** `services/teknik_servis/atolye.py::durum_degistir` yazar (eşleme tablosuyla, `SERVIS_IS_EMRI.dogrula` çağrılarak) | Genel servis durum/bekleme uçları bu tür için 409 döner (M05-15) |

- `workshop_records.service_order_id` **NOT NULL + `uq_atolye_servis_isi`** → 1:1.
- Mobilite tabloları (`work_orders`, `work_order_items`, `settlements`) **hiç okunmaz, hiç yazılmaz**. Atölye mobilite iş emrine köprü kurmaz; telsizler `devices`'a yazılmaz (00 §5, global `uq_devices_seri`).
- RMA köprüsü yalnız ekipman Denge'nin `devices` kaydına bağlıysa (`service_equipment.device_id` dolu) açılır (`rma_cases.device_id NOT NULL RESTRICT`, `models/service.py:79-81`).

### 1.2 Dosya yerleşimi (yeni/değişen)

```
backend/app/models/teknik_servis.py         # + WorkshopRecord, WorkshopAccessory, sabit tuple'lar (E01 dosyası; büyürse models/atolye.py) + models/__init__.py kaydı
backend/app/services/teknik_servis/atolye.py    # kabul, durum_degistir, teslim, garanti, seri geçmişi, numara
backend/app/services/teknik_servis/atolye_rapor.py  # liste filtresi (tek kaynak), özet, KPI, Excel satırları
backend/app/services/teknik_servis/kapsam.py    # (00 §6.3) kapsam_birim / birim_disinda_mi — E05 yalnız kullanır
backend/app/services/statemachine.py        # + ATOLYE makinesi, MAKINELER["atolye"]
backend/app/services/belgeler.py            # + atolye_kabul_baglami, atolye_teslim_baglami
backend/app/templates/atolye_kabul_fisi.html, atolye_teslim_tutanagi.html
backend/app/api/atolye.py                   # APIRouter(prefix="/api/teknik-servis/atolye", tags=["atolye"])
backend/app/main.py                         # import + app.include_router(atolye_api.router)
backend/app/permissions.py                  # + atolye.gor / atolye.yaz / atolye.kapat, rollere dağıtım
backend/app/models/attachment.py, api/attachments.py  # ek türleri + kapsam (E01'in service_orders sahibine)
backend/app/services/uyarilar.py, services/settings.py, services/gorevler.py, services/kvkk.py
backend/app/migration/atolye_saglik.py, yukle_atolye.py   # yalnız eski pilot verisi taşınacaksa
backend/alembic/versions/<rev>_atolye_cekirdek.py
backend/tests/unit/test_atolye_esleme.py, tests/integration/test_atolye*.py
frontend/src/api/atolye.ts, pages/AtolyePage.tsx, components/AtolyeKabulPenceresi.tsx, components/AtolyeDurumPenceresi.tsx
frontend/src/main.tsx (rota), components/AppLayout.tsx (MENU), pages/RaporlarPage.tsx (Atölye sekmesi)
```

---

## 2. Veri modeli

Tüm sabitler Türkçe, kolonlar İngilizce (00 §1.1). Durum/liste alanları `String` + adlı `CheckConstraint`; Python tarafında aynı değerlerin tuple'ı.

### 2.1 Sabitler (`models/teknik_servis.py`)

```python
ATOLYE_DURUMLARI = ("KABUL_EDILDI","TESHISTE","ONAY_BEKLIYOR","ONARIMDA","PARCA_BEKLIYOR",
                    "DIS_SERVISTE","TEST_KONTROL","TESLIME_HAZIR","ONARILMADAN_IADE",
                    "KARGOYA_VERILDI","TESLIM_EDILDI","IPTAL")
ATOLYE_ACIK_OLMAYAN = ("TESLIM_EDILDI","IPTAL")
ATOLYE_SERVIS_TURLERI = ("ARIZA_ONARIMI","GARANTI_ONARIMI","DIS_SERVIS","YAZILIM_FREKANS","KIRALAMA_TAKIP")   # L-26
ATOLYE_MARKALARI = ("HYTERA","HYT","HQT","MOTOROLA","KIRISUN","ASELSAN","DIGER")                      # L-25 (+DIGER)
ATOLYE_TESLIM_TIPLERI = ("ELDEN","KARGO","KURYE","SAHA")
ATOLYE_GARANTI_DURUMLARI = ("GARANTI_ICI","GARANTI_DISI","ONARIM_GARANTISI","BELIRSIZ")  # RMA'nın 3 değeri + 1
ATOLYE_ARIZA_KATEGORILERI = ("BATARYA_SARJ","EKRAN_TUS","HOPARLOR_MIKROFON","ANTEN_RF","YAZILIM_PROGRAMLAMA",
                             "SIVI_TEMASI","FIZIKSEL_HASAR","ARIZA_BULUNAMADI","DIGER")
ATOLYE_ONARIM_KATEGORILERI = ("PARCA_DEGISIMI","LEHIM_KART_ONARIMI","YAZILIM_YUKLEME","FREKANS_PROGRAMLAMA",
                              "TEMIZLIK_BAKIM","AYAR_KALIBRASYON","ISLEM_YAPILMADI","DIGER")
ATOLYE_TEST_SONUCLARI = ("GECTI","KALDI")
ATOLYE_ONAY_KARARLARI = ("ONAYLANDI","REDDEDILDI","ONAY_GEREKMEZ")
ATOLYE_ONAY_KANALLARI = ("TELEFON","EPOSTA","YAZILI","TEKLIF")
AKSESUAR_TURLERI = ("BATARYA","SARJ_UNITESI","SARJ_ADAPTORU","ANTEN","KEMER_KLIPSI","KILIF",
                    "KULAKLIK","HARICI_MIKROFON","KABLO","DIGER")
```

### 2.2 `workshop_records` (`PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin`)

| Kolon | Tip | Not |
|---|---|---|
| `atolye_no` | String(20) | `uq_atolye_no`; `AT-YYYY-NNNNNN`, PostgreSQL `SEQUENCE atolye_no_seq` (count/max+1 YASAK, 00 §1.3) |
| `service_order_id` | BigInteger FK `service_orders.id` RESTRICT, NOT NULL | `uq_atolye_servis_isi` (1:1) |
| `equipment_id` | BigInteger FK `service_equipment.id` RESTRICT, NOT NULL | seri/marka/model buradan okunur (tek kaynak) |
| `intake_group_no` | String(20) NULL | toplu kabul grubu (`KG-YYYY-NNNNN`, `SEQUENCE atolye_kabul_grubu_seq`); `ix_atolye_grup` |
| `service_type` | String(20) | `ck_atolye_servis_turu` |
| `status` | String(20) default `'KABUL_EDILDI'` | `ck_atolye_durum` |
| `received_at` | timestamptz NOT NULL | **sunucu saati (Clock)**; istemciden alınmaz (M05-13). Yalnız göçte kaynak değer yazılır |
| `received_by` | FK users SET NULL | kabul eden |
| `receive_type` | String(10) | `ck_atolye_kabul_tipi` (ATOLYE_TESLIM_TIPLERI) |
| `contact_id` | FK `contacts.id` SET NULL | irtibat = mevcut `contacts` |
| `customer_complaint` | Text NOT NULL | |
| `physical_condition` | Text NULL | |
| `estimated_finish_date` | Date NULL | |
| `warranty_start_date`, `warranty_end_date` | Date NULL | `ck_atolye_garanti_aralik`: `warranty_end_date IS NULL OR warranty_start_date IS NULL OR warranty_end_date >= warranty_start_date` |
| `warranty_status` | String(16) default `'BELIRSIZ'` | `ck_atolye_garanti`; kabulde HESAPLANIR ve DONDURULUR (RMA kalıbı `models/service.py:3-6`) |
| `fault_category`, `diagnosis_note`, `diagnosed_by` (FK users), `diagnosed_at` (tstz), `is_repairable` (Boolean NULL) | | `ck_atolye_ariza` |
| `repair_category`, `repair_note`, `test_result`, `tested_by`, `tested_at` | | `ck_atolye_onarim`, `ck_atolye_test` |
| `approval_decision`, `approval_channel`, `approved_by_name` (String 120), `approval_at` (tstz), `approval_note` (Text) | | `ck_atolye_onay_karari`, `ck_atolye_onay_kanali`, `ck_atolye_onay_gerekce`: `approval_decision IS DISTINCT FROM 'ONAY_GEREKMEZ' OR approval_note IS NOT NULL` |
| `repair_amount` | Numeric(12,2) NULL | `ck_atolye_bedel` (`>= 0`); **yalnız `sees_cost` (maliyet.gor)** okur/yazar |
| `delivery_type` | String(10) NULL | `ck_atolye_teslim_tipi` |
| `cargo_company`, `cargo_tracking_no` | String(60) NULL | |
| `cargo_sent_at`, `delivered_at`, `completed_at` | tstz NULL | hepsi Clock'tan; `completed_at` ilk TESLIME_HAZIR/ONARILMADAN_IADE'de bir kez yazılır, sonra değişmez |
| `delivered_to_name` | String(120) NULL | kişisel veri (KVKK anonimleştirme kapsamı) |
| `delivery_note` | Text NULL | eksik aksesuar açıklaması |
| `external_vendor_id` | FK `accounts.id` SET NULL | dış servis (üretici/distribütör; `is_tedarikci`) |
| `external_rma_no` | String(60) NULL | |
| `external_sent_at`, `external_returned_at` | Date NULL | `ck_atolye_dis_servis_tarih`: dönüş ≥ gönderim |
| `rma_case_id` | FK `rma_cases.id` SET NULL | yalnız `devices` bağlı ekipmanda |
| `logo_form_no`, `logo_main_service_no` | String(80) NULL | **yalnız serbest metin** (Logo CRM kapsam dışı) |
| `integration_company`, `project_name` | String(150) NULL | eski alanlar korunur |
| `notes` | Text NULL | |

Şema düzeyindeki koşullu zorunluluklar (yeni tablo olduğu için CHECK serbest):
- `ck_atolye_kargo`: `status <> 'KARGOYA_VERILDI' OR (delivery_type = 'KARGO' AND cargo_tracking_no IS NOT NULL AND cargo_company IS NOT NULL)`
- `ck_atolye_teslim`: `status <> 'TESLIM_EDILDI' OR (delivered_to_name IS NOT NULL AND delivered_at IS NOT NULL AND delivery_type IS NOT NULL)`
- `ck_atolye_tamamlanma`: `status NOT IN ('TESLIME_HAZIR','ONARILMADAN_IADE','KARGOYA_VERILDI','TESLIM_EDILDI') OR completed_at IS NOT NULL`

İndeksler:
- `uq_atolye_acik_ekipman` UNIQUE (`equipment_id`) `WHERE status NOT IN ('TESLIM_EDILDI','IPTAL') AND NOT is_deleted` → aynı cihaza ikinci açık kayıt DB'de de engelli (M05-06); servis önce kontrol edip 409 + mevcut `atolye_no` döner, yarış durumunda `IntegrityError` → `main.py:131-148` önekten 409.
- `ix_atolye_durum` (`status`, `received_at DESC`), `ix_atolye_tahmini_bitis` (`estimated_finish_date`) kısmi `WHERE status NOT IN ('TESLIM_EDILDI','IPTAL')`.
- `uq_workshop_records_kaynak` (`source_system`,`source_ref`) — göç idempotentliği.

### 2.3 `workshop_accessories` (`PkMixin, TimestampMixin, ActorMixin`)

| Kolon | Not |
|---|---|
| `workshop_record_id` FK CASCADE | `ix_atolye_aksesuar_kayit` |
| `kind` String(20) | `ck_atolye_aksesuar_tur` |
| `description` String(120) NULL | `ck_atolye_aksesuar_aciklama`: `kind <> 'DIGER' OR description IS NOT NULL` |
| `qty` Integer | `ck_atolye_aksesuar_adet` (`qty > 0`) |
| `returned` Boolean NULL | NULL = teslimde henüz işaretlenmedi |
| `return_note` String(300) NULL | |

Satır sayısı sınırsız (eski `Accessory1..5` kaldırıldı). Teslimden sonra satırlar kilitlenir (servis 409).

### 2.4 Yeniden kullanılan / genişletilen tablolar (E05 kendi migration'ında DOKUNMAZ, önkoşul olarak bekler)

| Tablo | Sahibi | E05'in ihtiyacı |
|---|---|---|
| `service_orders` | E01 | `tur` CHECK'inde `ATOLYE` değeri; `birim` (atölye varsayılanı `HABERLESME`) |
| `service_order_events` | E01 | olay türlerine `ATOLYE_DURUM`, `ATOLYE_TESHIS`, `ATOLYE_ONAY`, `ATOLYE_TESLIM`, `ATOLYE_DUZELTME` eklenir. E01 bu kolonu CHECK'li tanımladıysa E05 migration'ı CHECK'i **elle** drop+create eder (00 §2: autogenerate yakalamaz) |
| `service_holds` | E01 | bekleme nedenlerinde `MUSTERI_ONAYI`, `PARCA`, `DIS_SERVIS` |
| `service_time_entries` | E09 | faaliyet `ATOLYE` ve `TEST` (eski L-29'da vardı); E09 eklemezse `ISCILIK` kullanılır |
| `service_equipment` | E03 | bul-veya-aç: (`brand`, normalize seri) — seri METİN, baştaki sıfırlar korunur, karşılaştırma `upper(trim())` |
| `stock_movements.service_order_id` | E11 | parça hareketleri salt okunur listelenir |
| `quotes.service_order_id` | E07 | ücretli onarım teklifi |
| `accounts`, `contacts`, `rma_cases`, `attachments`, `audit_logs` | canlı | doğrudan |

### 2.5 Migration `<rev>_atolye_cekirdek.py`

- `make makemigration m="atolye_cekirdek"`; `down_revision` = E01/E03/E09 zincirinin o anki tek head'i (bugün `b30e012dd879`; kodlama başında `alembic heads` ile doğrulanır).
- İçerik: `op.execute("CREATE SEQUENCE atolye_no_seq")`, `op.execute("CREATE SEQUENCE atolye_kabul_grubu_seq")`, iki tablo, kısmi indeksler (`postgresql_where`), gerekiyorsa `service_order_events`/`service_holds` CHECK genişletmesi (drop + create, downgrade'de eski haline).
- Docstring: NEDEN (1:1 servis işi, durumun tek yerden yürümesi, açık kayıt tekilliği) + bedeli.
- `downgrade`: tablolar, indeksler, sequence'ler düşer; head→base→head testinden geçer (`tests/migration/test_migration_zinciri.py`).
- Canlı mobilite tablolarına ve mevcut CHECK/EXCLUDE'lara **dokunmaz**.

---

## 3. Durum makinesi `ATOLYE` ve servis işi eşlemesi

### 3.1 Makine (`services/statemachine.py`, `MAKINELER["atolye"] = ATOLYE`)

```python
ATOLYE = StateMachine(
    ad="Atölye",
    baslangiclar=frozenset({"KABUL_EDILDI"}),
    gecisler=_m(
        KABUL_EDILDI=("TESHISTE", "IPTAL"),
        TESHISTE=("ONAY_BEKLIYOR", "ONARIMDA", "PARCA_BEKLIYOR", "DIS_SERVISTE", "ONARILMADAN_IADE", "IPTAL"),
        ONAY_BEKLIYOR=("ONARIMDA", "ONARILMADAN_IADE", "IPTAL"),
        ONARIMDA=("PARCA_BEKLIYOR", "DIS_SERVISTE", "TEST_KONTROL", "ONARILMADAN_IADE", "IPTAL"),
        PARCA_BEKLIYOR=("ONARIMDA", "ONARILMADAN_IADE", "IPTAL"),
        DIS_SERVISTE=("ONARIMDA", "TEST_KONTROL", "ONARILMADAN_IADE", "IPTAL"),
        TEST_KONTROL=("ONARIMDA", "TESLIME_HAZIR"),
        TESLIME_HAZIR=("KARGOYA_VERILDI", "TESLIM_EDILDI", "ONARIMDA"),      # ONARIMDA = geri alma
        ONARILMADAN_IADE=("KARGOYA_VERILDI", "TESLIM_EDILDI", "TESHISTE"),   # TESHISTE = geri alma
        KARGOYA_VERILDI=("TESLIM_EDILDI", "TESLIME_HAZIR"),                  # TESLIME_HAZIR = geri alma
        TESLIM_EDILDI=(),
        IPTAL=(),
    ),
)
```

Makinenin ÜSTÜNDEKİ iş kuralları `atolye.durum_degistir` içinde (servis katmanı, `AtolyeHatasi(ValueError)` → API 409; girdi eksiği → 400):

| Hedef | Kural |
|---|---|
| TESHISTE'den çıkış (IPTAL hariç) | `fault_category` ve `is_repairable` dolu |
| `is_repairable = False` | yalnız `ONARILMADAN_IADE` / `IPTAL` |
| `ONARIMDA` (TESHISTE/ONAY_BEKLIYOR'dan) | `warranty_status <> 'GARANTI_ICI'` ise (BELIRSIZ dahil) `approval_decision IN ('ONAYLANDI','ONAY_GEREKMEZ')` **veya** bağlı teklif (`quotes.service_order_id`) `KABUL` |
| `approval_decision = 'REDDEDILDI'` | yalnız `ONARILMADAN_IADE` / `IPTAL` |
| `TESLIME_HAZIR` | `test_result = 'GECTI'` ve `repair_category` dolu |
| `KARGOYA_VERILDI` | `delivery_type = 'KARGO'`, `cargo_company`, `cargo_tracking_no` dolu (aksi 400); `cargo_sent_at = clock.now()` |
| `TESLIM_EDILDI` | `delivered_to_name` dolu (400); tüm aksesuarlarda `returned` işaretli, `returned = false` olan varsa `delivery_note` zorunlu (400); servis işinde **açık zaman kaydı yoksa** (`service_time_entries.bitis IS NULL` → 409); seri no var (ekipman NOT NULL olduğundan şema garantisi); `delivered_at = clock.now()` |
| `IPTAL` | gerekçe zorunlu (400) + `atolye.kapat` |
| Geri alma geçişleri (TESLIME_HAZIR→ONARIMDA, ONARILMADAN_IADE→TESHISTE, KARGOYA_VERILDI→TESLIME_HAZIR) | gerekçe zorunlu + `atolye.kapat` |
| `completed_at` | ilk kez TESLIME_HAZIR veya ONARILMADAN_IADE'ye girerken `COALESCE(completed_at, now)` |
| Her geçiş | `service_order_events` (`ATOLYE_DURUM`, `{onceki, yeni, gerekce}`) + `audit.log(... "atolye.durum.degistir")` + servis işi eşlemesi — **tek transaction**, servis `flush`, API `commit` |

### 3.2 Servis işi eşlemesi (`atolye.py::SERVIS_DURUMU`, `BEKLEME_NEDENI`)

| Atölye | Servis işi (`SERVIS_IS_EMRI`) | `service_holds` |
|---|---|---|
| KABUL_EDILDI | başlangıç durumu (E01: `PLANLANACAK`) | — |
| TESHISTE, ONARIMDA, TEST_KONTROL | `ISLEMDE` | açık bekleme varsa kapanır |
| ONAY_BEKLIYOR | `ISLEMDE` | `MUSTERI_ONAYI` açılır |
| PARCA_BEKLIYOR | `ISLEMDE` | `PARCA` açılır |
| DIS_SERVISTE | `ISLEMDE` | `DIS_SERVIS` açılır |
| TESLIME_HAZIR, ONARILMADAN_IADE, KARGOYA_VERILDI | `TAMAMLANDI` (+ `service_results`: ONARILDI→`COZULDU`, onarılmadan iade→`COZULEMEDI`) | kapanır |
| TESLIM_EDILDI | `KAPANDI` | — |
| IPTAL | `IPTAL` | kapanır |

- Servis işi tarafı da **makineyle** yürür: aynı servis durumuna eşlenen atölye geçişinde servis durumu değişmez (eski M05-15 "durum değişmeyen kayıt iş emrine dokunmaz"); değişiyorsa `SERVIS_IS_EMRI.dogrula(onceki, hedef)` çağrılır, alan doğrudan atanmaz (00 §1.7).
- **Meta-test (`tests/unit/test_atolye_esleme.py`):** (a) her `ATOLYE_DURUMLARI` değerinin eşlemesi var; (b) eşlenen hedefler `SERVIS_IS_EMRI.durumlar` içinde; (c) ATOLYE makinesindeki HER geçiş için eşlenen servis çifti ya eşit ya `SERVIS_IS_EMRI.izinli_mi(...)` true. E01 durum adları farklı çıkarsa bu test kırılır ve eşleme tek yerde düzeltilir — sessiz sapma imkânsız.

---

## 4. İzinler ve roller (`permissions.py`)

| Yeni kod | Modül / açıklama |
|---|---|
| `atolye.gor` | "Atölye" — atölye kayıtlarını, seri geçmişini, kabul fişini görür |
| `atolye.yaz` | kabul açar, teşhis/onarım/test/onay/aksesuar/teslim girer, ara geçişleri yapar |
| `atolye.kapat` | iptal eder, geri alma geçişlerini yapar (gerekçeli) |

Mevcut kodlar yeniden kullanılır: `maliyet.gor` (tamir bedeli ve parça maliyeti), `rapor.gor`/`rapor.disaaktar` (KPI ve Excel), `rma.yaz` (RMA köprüsü), `zaman.yaz` (00 §6.3), `cihaz.yaz` (parça çıkışı düğmesi; canlı `POST /api/stok/hareket` bu izni ister, `api/stock.py:31,296`).
"Yalnız atandığı işler" kuralı E01'inkidir; E01 bunu bir izinle (`servis.tumunu_gor`) kurmazsa E05 bu kodu ekler: **yoksa** kullanıcı yalnız atandığı servis işlerinin atölye kayıtlarını görür/değiştirir.

| Rol (00 §6.3) | Kapsam | Atölye izinleri |
|---|---|---|
| `SERVIS_YONETICI` | TUMU | `atolye.gor`, `atolye.yaz`, `atolye.kapat`, `servis.tumunu_gor` |
| `SERVIS_SEF` | KENDI_BIRIMI | `atolye.gor`, `atolye.yaz`, `atolye.kapat`, `servis.tumunu_gor` |
| `ATOLYE` (kabul/operasyon + atölye ustası) | KENDI_BIRIMI | `atolye.gor`, `atolye.yaz`, `servis.tumunu_gor`, `zaman.yaz` |
| `SERVIS_TEKNISYEN` | KENDI_BIRIMI | `atolye.gor`, `atolye.yaz`, `zaman.yaz` (yalnız atandığı işler) |
| `YONETIM` | TUMU | `atolye.gor` otomatik (`_READ_ONLY_ALL`, `permissions.py:84`) |
| `ADMIN` | TUMU | otomatik |
| Mevcut `TEKNIK_SERVIS`, `DEPO`, `SATIS`... | — | **değişmez** (TEKNIK_SERVIS mobilite rolüdür) |

- `maliyet.gor` HİÇBİR yeni role verilmez (`tests/unit/test_permissions.py:21-26` kümesi sabit). Şefin bedeli görmesi gerekiyorsa kişi bazında `UserPermission(allow, gerekce)` (`models/rbac.py:29-52`).
- Özelleştirilmiş DB rollerine yeni izin inmez (`seeds/dev.py:44-79`) — devreye almada kullanıcı yönetimi ekranından elle verilir; sürüm notuna yazılır.

---

## 5. API uçları (`api/atolye.py`, prefix `/api/teknik-servis/atolye`)

`Okuyucu = require_permission("atolye.gor")`, `Yazici = require_permission("atolye.yaz")`, `Kapatici = require_permission("atolye.yaz","atolye.kapat")`. Her tek kayıt ucunda sıra: `db.get` → `is_deleted` → **kapsam** (`kapsam_disinda_mi(customer)` + `birim_disinda_mi(service_order.birim)` + atama kuralı) → 404; yazma ondan sonra.

| Uç | İzin | Davranış |
|---|---|---|
| `GET ""` | Okuyucu | filtreler: `durum` (çoklu), `teknisyen_id`, `marka`, `servis_turu`, `q` (atölye no / servis no / seri / müşteri `title_key` trgm), `yas` (`0-3`,`4-7`,`8-14`,`15+`), `geciken` (tahmini bitiş < bugün ve açık), `kabul_grubu`; `kapsam_musteri` + `kapsam_birim` + atama; `sayfala` (`X-Toplam-Kayit`) |
| `GET "/ozet"` | Okuyucu | aynı filtre yardımcısı (`atolye_rapor.filtreli_sorgu`) ile durum başına ve yaş kovası başına sayılar + geciken sayısı → **tıklanabilir KPI kutuları** |
| `GET "/disaaktar"` | Okuyucu + `rapor.disaaktar` | AYNI `filtreli_sorgu` → `satirlari_xlsx_async`; `repair_amount` sütunu yalnız `sees_cost` |
| `GET "/seri-gecmisi"` | Okuyucu | `?marka=&seri=` → aynı ekipmanın önceki atölye kayıtları (tarih, arıza, onarım, sonuç), `tekrar_gelis` (son N gün), kapsam dışı kayıtlar sayılmaz/gösterilmez |
| `GET "/{id}"` | Okuyucu | detay + `sonraki_durumlar` (makine ∩ kullanıcının izinleri ∩ iş kuralı ön kontrolü) + aksesuarlar + olay zaman çizelgesi + parça hareketleri + süre özeti (`toplam_kisi_saat` MOLA hariç; kayıt yoksa `sure_durumu: "EKSIK"`, 0 yazılmaz) |
| `POST ""` | Yazici | **kabul**: müşteri (`customer_id` ya da `yeni_musteri` → `services/accounts` mükerrer aday kontrolüyle minimal `Account(is_musteri)`; aday varsa 409 + aday listesi), ekipman bul-veya-aç, garanti hesabı, `service_orders` (tür ATOLYE, birim varsayılan HABERLESME, kullanıcının birimi dışında 404/403) + `workshop_records` + aksesuarlar; `status` alanı gelse bile **yok sayılır** → KABUL_EDILDI; açık kayıt varsa 409 + mevcut `atolye_no` |
| `POST "/toplu-kabul"` | Yazici | aynı müşteriden N cihaz → N kayıt + N servis işi, ortak `intake_group_no`; hepsi ya da hiçbiri |
| `PATCH "/{id}"` | Yazici | tanımlayıcı/veri alanları (şikâyet, fiziksel durum, tahmini bitiş, teşhis/onarım/test/onay/teslim/dış servis alanları, Logo no'ları); `version` zorunlu, uyuşmazlık 409; `status` kabul edilmez; `repair_amount` `sees_cost` değilse **sessizce yok sayılır, mevcut değer korunur**; `received_at`/`completed_at`/`delivered_at` istemciden alınmaz; `audit.log_change` |
| `PUT "/{id}/ekipman"` | Yazici | seri/marka/model düzeltme → `service_equipment` güncellenir (tek kaynak) + `ATOLYE_DUZELTME` olayı + denetim; açık kayıt tekilliği yeniden sınanır |
| `PUT "/{id}/aksesuarlar"` | Yazici | listenin tamamını değiştirir; teslimden sonra 409 |
| `POST "/{id}/durum"` | Yazici (+ hedefe göre `atolye.kapat` gövdede `_izin`) | `{hedef, gerekce?, teslim?: {teslim_alan, teslim_tipi, kargo_firmasi, takip_no, aksesuar_iade: [{id, returned, not}], aciklama}}`; önce `ATOLYE.dogrula`, sonra iş kuralları; yanıtta `sonraki_durumlar` |
| `POST "/{id}/ata"` | Yazici + E01 atama izni | E01 `is_emirleri.ata(service_order, teknisyen)` çağırır; atölye kendi atama alanı TUTMAZ |
| `POST "/toplu-ata"` | aynı | `{ids, teknisyen_id}`; her kayıt kapsam kontrolünden geçer, biri düşerse hiçbiri yazılmaz |
| `POST "/{id}/teklif"` | Yazici + `teklif.yaz` | E07 kısayolu: `quotes.service_order_id` dolu taslak teklif açar |
| `POST "/{id}/rma"` | Yazici + `rma.yaz` | ekipman `device_id` doluysa `services/rma.ac(...)`, `rma_case_id` yazılır; değilse 409 "Denge kaydı olmayan cihaz için RMA açılamaz" |
| `GET "/{id}/kabul-fisi.pdf"`, `GET "/{id}/teslim-tutanagi.pdf"`, `GET "/kabul-grubu/{no}/fis.pdf"` | Okuyucu | `belgeler.atolye_*_baglami(kayit, goster_bedel=sees_cost(user))` + WeasyPrint; tutar anahtarı bağlama hiç girmez |
| `GET "/raporlar/kpi"`, `GET "/raporlar/kpi.xlsx"` | Okuyucu + `rapor.gor` (xlsx: + `rapor.disaaktar`) | §7 |

Genel servis uçlarına (E01) eklenecek korumalar (E05 kapsamında yazılır, E01 dosyasında):
- `POST /api/teknik-servis/isler` ile `tur='ATOLYE'` → 400 "Atölye işini Atölye ekranından açın".
- Genel durum ucu ve bekleme aç/kapat uçları `tur='ATOLYE'` servis işinde → 409 "Bu işin durumu Atölye ekranından değişir" (+ `atolye_id` yönlendirmesi).

---

## 6. Ön yüz

- `src/api/atolye.ts`: tipler (`AtolyeKaydi`, `AtolyeOzet`, `Aksesuar`, `SeriGecmisi`) + fonksiyonlar; liste `api.getSayfa`.
- `main.tsx`: `/atolye` ve `/atolye/:id` rotaları `AppLayout` altında. `AppLayout MENU`: Teknik Servis grubunda `{key: "/atolye", label: "Haberleşme Atölyesi", icon: <ToolOutlined/>, izin: "atolye.gor"}` (mobilite "İş Emirleri" ile karışmasın diye ad açık).
- `pages/AtolyePage.tsx`:
  - Üstte **tıklanabilir KPI kutuları** (`/ozet`): durum başına (Kabul, Teşhis, Onay Bekliyor, Onarımda, Parça Bekliyor, Dış Serviste, Test, Teslime Hazır, Kargoda), yaş kovaları (0-3 / 4-7 / 8-14 / 15+), "Tahmini bitişi geçen". Tıklama filtreyi ayarlar, sayfa 1'e döner.
  - `Table` sunucu sayfalaması; sütunlar: Atölye No (`mono`), Servis No, Müşteri, Servis Türü, Marka/Model, Seri (`mono`, olduğu gibi), Durum (`replaceAll("_"," ")`), Atanan, Kabul (DD.MM.YYYY HH:mm), Bekleme günü, gecikme rozeti; satır seçimi → **Toplu Ata** ve **Excel** (aynı filtre).
  - Satır → `Drawer size={680}`: Kabul / Teşhis-Onarım / Onay (+ "Teklif oluştur") / Aksesuar / Parça & Süre (salt okunur; "Süre kaydı eksik" etiketi; "Parça çıkışı" düğmesi yalnız `yetkili("cihaz.yaz")`) / Teslim / Dış Servis / Geçmiş (`Timeline`) / Ekler (`EkYukleyici entity="service_orders"`) / Görevler (`KayitGorevleri`). Tamir bedeli alanı yalnız `yetkili("maliyet.gor")`.
- `components/AtolyeKabulPenceresi.tsx` (KartPenceresi kalıbı, tek form yeni+düzenle): müşteri seçimi/hızlı müşteri, marka (sabit liste), model, seri → seri girilince `/seri-gecmisi` paneli ("Tekrar geliş — onarım garantisi olabilir" uyarısı), aksesuar satırları (dinamik `Form.List`), "Toplu kabul" modu (seri listesi yapıştırma).
- `components/AtolyeDurumPenceresi.tsx`: yalnız `sonraki_durumlar` gösterilir; hedefe göre zorunlu alanlar (gerekçe, teslim alan, kargo, aksesuar iade işaretleme).
- Kabul fişi / teslim tutanağı: yeni sekmede PDF.
- `RaporlarPage.tsx`: "Atölye" sekmesi (KPI + Excel).
- 409'da "Kayıt başka kullanıcı tarafından değiştirildi, yenileyin" (`HesaplarPage.tsx:164` kalıbı). Tüm metinler Türkçe; tarih `dayjs("tr")`.

---

## 7. Raporlar, uyarılar, ayarlar, worker

- **KPI (`atolye_rapor.kpi(db, clock, user, baslangic, bitis)`):** çevrim süresi (takvim günü) = kabul → ilk `ATOLYE_DURUM yeni=TESLIME_HAZIR` olayı; olayı olmayan kapanmış kayıt **"süre kaydı eksik"** ayrı sayılır (0 gün sayılmaz); dış servis bekleme süresi (`external_sent_at`→`external_returned_at`) **ayrı** raporlanır ve çevrim ortalamasından ayrıca "dış servis hariç" varyantı verilir; tekrar geliş oranı (aynı ekipman, N gün); arıza kategorisi × marka/model dağılımı; teknisyen başına tamamlanan kayıt + kayıtlı kişi-saat (MOLA hariç, kayıt yoksa "eksik"); onay bekleyen sayısı ve ret oranı; teslim alınmayı bekleyen cihazlar. Tümü birim + müşteri kapsamına tabi.
- **Uyarılar (`uyarilar.topla`, `if user.has("atolye.gor"):` bloğu, birim kapsamlı sayım):** `ATOLYE_GECIKEN` (tahmini bitiş geçti), `ATOLYE_15_GUN` (15+ gündür açık), `ATOLYE_TESLIM_ALINMADI` (TESLIME_HAZIR/ONARILMADAN_IADE'de `atolye_teslim_bekleme_uyari_gun` gündür), `ATOLYE_SURE_EKSIK` (tamamlanmış ama zaman kaydı yok), `ATOLYE_DIS_SERVIS_GECIKEN` (dış serviste `atolye_dis_servis_uyari_gun`+).
- **Ayarlar (`services/settings.py` DEFAULTS):** `atolye_tekrar_gelis_gun: 90`, `atolye_onarim_garanti_gun: 90`, `atolye_teslim_bekleme_uyari_gun: 30`, `atolye_dis_servis_uyari_gun: 30`.
- **Worker:** yeni periyodik görev GEREKMEZ (uyarılar hesaplanır, saklanmaz).
- **Görev panosu (`services/gorevler.py` KAYIT_TIPLERI):** `KayitTipi("atolye", "Atölye Kaydı", WorkshopRecord, ("atolye_no",), "/atolye/{id}")`.
- **KVKK (`services/kvkk.py`):** `delivered_to_name`, `approved_by_name` anonimleştirme kapsamına; bireysel müşteri kabulünde denetim `is_personal_data=True`.

---

## 8. Madde bazında entegrasyon (E05-NN)

Durum: **VAR** = canlıda karşılanıyor, **KISMEN** = altyapı var, atölyeye uygulanmamış, **YOK** = canlıda karşılığı yok.

### E05-01 · Atölye durum makinesi ve olay geçmişi — kaynak M05-01, M05-11 · **YOK** · P1 · L
- **Canlı karşılık:** Makine sınıfı `services/statemachine.py:27-83`, `MAKINELER` `:189-196`, meta-test `tests/unit/test_statemachine.py:8-33`; RMA durum ucu emsali `api/rma.py:197-232`. Atölye makinesi ve geçmişi yok.
- **Yaklaşım:** §3.1 `ATOLYE` makinesi `MAKINELER`'e; `POST /{id}/durum` tek durum ucu; geçmiş ayrı tablo değil, E01 `service_order_events` (`ATOLYE_DURUM`, silinemez) — aynı transaction'da servis işi eşlemesi ve denetim izi. Yeni kayıt yalnız KABUL_EDILDI. Geri alma geçişleri `atolye.kapat` + gerekçe; TESLIM_EDILDI ve IPTAL terminal (canlı RMA ilkesi `statemachine.py:159-161`).
- **Dosyalar:** `services/statemachine.py`, `services/teknik_servis/atolye.py`, `api/atolye.py`, `tests/unit/test_atolye_esleme.py`, `tests/integration/test_atolye_durum.py`.
- **Kabul:** KABUL_EDILDI→TESLIM_EDILDI isteği 409 ve izinli listeyi döner; POST'ta `status="TESLIM_EDILDI"` gönderilse de kayıt KABUL_EDILDI açılır; her geçerli geçiş 1 `ATOLYE_DURUM` olayı + 1 denetim satırı üretir; servis durumu değişmeyen geçişte servis işine satır/olay yazılmaz; gerekçesiz IPTAL 400; `atolye.kapat` olmadan IPTAL/geri alma 403; meta-testler yeşil.
- **Canlı risk:** Yok — yeni makine; meta-test tüm makineleri zaten parametrik sınıyor.

### E05-02 · Yapılandırılmış teşhis ve onarım — M05-02 · **YOK** · P2 · M
- **Canlı karşılık:** Yok (RMA'da yalnız `fault_description`, `resolution` var — `models/service.py:91-97`).
- **Yaklaşım:** §2.2 teşhis/onarım/test kolonları + CHECK'ler; `diagnosed_at`/`tested_at` Clock; kurallar §3.1. PATCH ile girilir, `ATOLYE_TESHIS` olayı.
- **Kabul:** `fault_category` boşken TESHISTE'den çıkış 400; `test_result <> GECTI` iken TESLIME_HAZIR 409; `is_repairable=false` iken ONARIMDA 409, ONARILMADAN_IADE 200; arıza kategorisi KPI ve Excel'de sütun.
- **Canlı risk:** Yok.

### E05-03 · Ücretli onarımda müşteri onayı + teklif bağlantısı — M05-03 · **YOK** · P2 · M
- **Canlı karşılık:** Teklif modülü var (`models/quote.py:60-89`, `services/quotes.py`) ama iş bağlantısı yok; `quotes.service_order_id` E07'de eklenecek.
- **Yaklaşım:** Kayıt üstünde onay alanları (ayrı tablo YOK); ONAY_BEKLIYOR girişinde `MUSTERI_ONAYI` bekleme açılır, çıkışta kapanır. Onay = `approval_decision` ONAYLANDI/ONAY_GEREKMEZ(gerekçeli) **veya** bağlı teklif KABUL. `POST /{id}/teklif` kısayolu. Onay zamanı Clock.
- **Kabul:** Garanti `GARANTI_ICI` değilken (BELIRSIZ dahil) onaysız ONARIMDA 409; `ONAY_GEREKMEZ` + boş gerekçe 400 (`ck_atolye_onay_gerekce`); REDDEDILDI sonrası yalnız ONARILMADAN_IADE/IPTAL; bağlı teklif KABUL ise ONARIMDA 200; onay bekleyen kayıt E01 bekleme listesinde "Müşteri onayı" nedeniyle görünür.
- **Canlı risk:** Teklif tablosuna yalnız nullable kolon (E07) — teklif akışı değişmez.

### E05-04 · Kabul fişi ve teslim tutanağı (PDF) — M05-04 · **KISMEN** · P2 · M
- **Canlı karşılık:** PDF altyapısı `services/pdf.py:21-53` (Jinja2 + WeasyPrint, UTF-8, Türkçe sorunsuz), bağlam kalıbı `services/belgeler.py:31,119,147`, şablonlar `templates/teklif.html`. Atölye şablonu yok.
- **Yaklaşım:** Denetimin "HTML + tarayıcıdan yazdır" önerisi, eski sistemin ASCII PDF sorunu yüzündendi; canlıda bu sorun yok → **canlı PDF altyapısı kullanılır**, yeni kütüphane eklenmez. `belgeler.atolye_kabul_baglami / atolye_teslim_baglami(goster_bedel)`; `templates/atolye_kabul_fisi.html`, `atolye_teslim_tutanagi.html` (firma künyesi `firma_bilgisi`), kabul grubu fişi. İmza alanı kâğıtta; imzalı tarama EK olarak (`MUSTERI_IMZASI`).
- **Kabul:** PDF 200 ve `%PDF` ile başlar; "Şikâyet/Aksesuar/ĞğİıŞş" doğru basılır (metin çıkarımı testi); seri `000123` aynen; `maliyet.gor` olmayan kullanıcının bağlam sözlüğünde `tamir_bedeli` anahtarı yok, PDF metninde "₺" yok.
- **Canlı risk:** Yok; WeasyPrint ısınması `main.py:43-67` paylaşılır.

### E05-05 · Satır bazlı aksesuar ve teslimde karşılaştırma — M05-05 · **YOK** · P2 · M
- **Canlı karşılık:** Yok.
- **Yaklaşım:** `workshop_accessories` (§2.3); `PUT /{id}/aksesuarlar`; teslimde `aksesuar_iade` listesi zorunlu işaretleme; eski `Accessory1..5` → göçte (E05-23) her dolu alan `qty=1`, listede olmayan değer `DIGER`+açıklama.
- **Kabul:** 6+ satır eklenir, `qty<=0` 400 (`ck_atolye_aksesuar_adet`); işaretlenmemiş veya `returned=false` satır varken açıklamasız TESLIM_EDILDI 400; teslim sonrası aksesuar değişikliği 409; göç testi: 5 dolu eski alan → 5 satır, kayıp yok.
- **Canlı risk:** Yok.

### E05-06 · Seri no geçmişi ve açık kayıt engeli — M05-06 · **KISMEN** · P2 · M
- **Canlı karşılık:** Aynı kalıp RMA'da: "aynı cihaz için açık kayıt varsa ikincisi açılmaz" (`services/rma.py:91-99`). Atölye/ekipman için yok.
- **Yaklaşım:** Servis kontrolü + `uq_atolye_acik_ekipman` kısmi tekil indeksi (yarışta da güvenli); ekipman eşlemesi (`brand`, `upper(trim(seri))`), baştaki sıfırlar korunur. `GET /seri-gecmisi`; tekrar geliş **bayrak olarak saklanmaz**, tarih + ekipmandan türetilir; pencere `atolye_tekrar_gelis_gun` ayarı.
- **Kabul:** Açık kayıt varken POST 409 ve mesajda mevcut `AT-...` no; `" ab12 "` ile `"AB12"` aynı ekipmanı bulur, `"0AB12"` farklıdır; geçmiş tarih sırasıyla döner; kapsam dışı birimin kayıtları geçmişte görünmez.
- **Canlı risk:** Yok.

### E05-07 · Garanti durumu sabit liste + sunucu hesabı — M05-07 · **KISMEN** · P2 · S
- **Canlı karşılık:** `GARANTI_DURUMLARI` ve hesap/dondurma `models/service.py:50-52`, `services/rma.py:43-67`.
- **Yaklaşım:** `ATOLYE_GARANTI_DURUMLARI` = RMA'nın üç değeri + `ONARIM_GARANTISI`. Kabulde hesaplanır ve donar: ekipman `device_id` bağlıysa `rma.garanti_karari(cihaz)` yeniden kullanılır; değilse girilen tarihler: bitiş < kabul → GARANTI_DISI, bitiş ≥ kabul → GARANTI_ICI, tarih yok → BELIRSIZ; aynı ekipman son `atolye_onarim_garanti_gun` içinde ONARILDI sonucuyla teslim edildiyse ONARIM_GARANTISI. "Garanti Değil" varsayılanı yazılmaz.
- **Kabul:** bitiş<kabul → GARANTI_DISI; bitiş<başlangıç 400 (+ `ck_atolye_garanti_aralik`); tarih yok → BELIRSIZ; garanti tarihi sonradan düzeltilince `warranty_status` değişmez; eski kayıt dönüşümü göçte yalnız kullanıcı onaylı listeyle.
- **Canlı risk:** `rma.garanti_karari` yalnız okunur/çağrılır, değiştirilmez.

### E05-08 · Liste: sunucu filtresi, sayfalama, yaşlandırma, tıklanabilir KPI kutuları — M05-08a · **KISMEN** · P2 · M
- **Canlı karşılık:** `sayfala()` `api/deps.py:170-190`, liste kalıbı `api/workorders.py:269-297`, ön yüz `pages/IsEmirleriPage.tsx:66-166`.
- **Yaklaşım:** `GET ""` + `GET "/ozet"` tek filtre yardımcısını paylaşır; bekleme günü `received_at`'ten (Clock), yaş kovaları, geciken işareti; KPI kutuları tıklanabilir (eski sistemde kullanıcı doğrulamış işlev).
- **Kabul:** durum/teknisyen/marka/metin filtreleri ve sayfalama sunucuda; `X-Toplam-Kayit` doğru; 15+ kovası filtrelenebilir; kutu sayısı = aynı filtreyle liste toplamı; geciken kayıt işaretli.
- **Canlı risk:** Yok.

### E05-09 · KPI raporları ve Excel — M05-08b · **KISMEN** · P3 · M
- **Canlı karşılık:** `services/export.py:26,45`, `api/reports.py:29-55` (izin + maliyet gizleme), `pages/RaporlarPage.tsx`.
- **Yaklaşım:** §7 KPI; `GET /raporlar/kpi(.xlsx)`; liste Excel'i `GET /disaaktar` aynı filtre fonksiyonundan.
- **Kabul:** çevrim süresi yalnız TESLIME_HAZIR olayı olan kayıtlardan, diğerleri "süre kaydı eksik" sayısında; Excel satırları = ekrandaki filtreli liste (test: aynı filtreyle id kümeleri eşit); `rapor.disaaktar` yoksa 403; `maliyet.gor` yoksa bedel sütunu yok.
- **Canlı risk:** Mevcut rapor sorguları değiştirilmez.

### E05-10 · Teslim/kargo sabit liste ve zorunluluklar — M05-09 · **YOK** · P2 · S
- **Canlı karşılık:** Yok (transfer belgesinde `delivered_by/received_by` serbest metin var, `models/stock.py:171-175`, atölyeye uygulanamaz).
- **Yaklaşım:** `receive_type`/`delivery_type` CHECK'li liste; kargo firması + takip no; `cargo_sent_at`, `delivered_at` Clock; şema CHECK'leri `ck_atolye_kargo`, `ck_atolye_teslim`.
- **Kabul:** KARGO + boş takip no ile KARGOYA_VERILDI 400; teslim alan boşken TESLIM_EDILDI 400; `delivered_at` istemciden gönderilse yok sayılır, Clock değeri yazılır.
- **Canlı risk:** Yok.

### E05-11 · Tek atama kaynağı — M05-10 · **YOK** · P1 · M
- **Canlı karşılık:** Mobilite iş emrinde atama `assigned_type/assigned_*` (dokunulmaz); teknik servis atama kaynağı E01'de doğacak.
- **Yaklaşım:** Atölye kaydında atama kolonu YOK; `POST /{id}/ata` ve toplu ata E01 `ata()`'yı çağırır; liste "Atanan" sütunu E01 kaynağından okunur; atama değişince E01 eski atamayı pasifler ve `ATAMA` olayı yazar. Teknisyenin "işlerim" ve zaman sayacı (E09) aynı servis işi üzerinden çalışır.
- **Kabul:** Atölye ekranından atanan teknisyen, kendi kullanıcısıyla E01 iş listesinde işi görür ve `ATOLYE` faaliyetiyle süre başlatır; E01 ekranından yapılan atama atölye listesinde görünür; atama değişince eski atama pasif ve olay geçmişinde iki satır.
- **Canlı risk:** Yok (mobilite atamasına dokunulmaz).

### E05-12 · Durum değişikliği iş tarihçesine — M05-11 (dotnet_specific) · **YOK** · P1 · S
- **Canlı karşılık:** —
- **Yaklaşım:** Özü korunur: atölye geçişi ve servis işi geçişi aynı transaction'da `service_order_events`'e yazılır (E05-01 ile birlikte uygulanır, ayrı kod yok).
- **Kabul:** ONARIMDA yapılınca servis işi zaman çizelgesinde eski→yeni + kullanıcı satırı; durumu değişmeyen PATCH'te olay yazılmaz.
- **Canlı risk:** Yok.

### E05-13 · İptalin servis işine yansıması — M05-12 (dotnet_specific) · **YOK** · P1 · S
- **Yaklaşım:** Eşleme IPTAL→IPTAL, açık bekleme kapanır, gerekçe olaya ve denetime; "Atölyede" sayımı açık kayıtlardan yapıldığı için iptal sayıdan düşer.
- **Kabul:** Atölye IPTAL → servis işi IPTAL, açık `service_holds` kapalı, panel/özet "Atölyede" sayısı 1 azalır, gerekçe olayda.
- **Canlı risk:** Yok.

### E05-14 · Tarih/saat doğruluğu — M05-13 (dotnet_specific) · **KISMEN** · P1 · S
- **Canlı karşılık:** `Clock` (`api/deps.py:22-27`, `clock.py`), `timestamptz` alışkanlığı, `FakeClock` testleri (`tests/conftest.py:157-167`).
- **Yaklaşım:** Tüm zaman damgaları sunucu Clock'undan, `timestamptz`; `completed_at` bir kez yazılır; istemci zaman alanları Pydantic modelinde yok; ön yüz `dayjs` yerel gösterim.
- **Kabul:** FakeClock 11:00Z (TR 14:00) → yanıtta `...T11:00:00Z`, ekranda 14:00; tamamlanmış kayıtta not PATCH'i `completed_at`'i değiştirmez; PATCH `received_at` gönderilse yok sayılır.
- **Canlı risk:** Yok.

### E05-15 · Seri no tek kaynak — M05-14 (dotnet_specific) · **YOK** · P1 · S
- **Yaklaşım:** Seri yalnız `service_equipment`'ta; atölye ve servis işi `equipment_id` ile okur → iki kopya yok. Düzeltme `PUT /{id}/ekipman`, `ATOLYE_DUZELTME` olayı + `audit.log_change`. Servis işine birden çok ekipman eklenmesi `tur='ATOLYE'` için E01 ekipman ucunda 409.
- **Kabul:** `00A-12`→`00A-123` düzeltmesi sonrası atölye detayı, servis işi, seri geçmişi ve KPI yalnız `00A-123` gösterir, olay + denetim satırı var; ATOLYE işine ikinci ekipman 409.
- **Canlı risk:** Yok.

### E05-16 · Servis işi durumu yalnız atölye ucundan; bekleme senkronu — M05-15 · **YOK** · P1 · M
- **Yaklaşım:** §3.2 eşleme + `service_holds` aç/kapat; E01 genel durum ve bekleme uçlarında `tur='ATOLYE'` → 409 + yönlendirme.
- **Kabul:** Genel durum ucu ve bekleme aç/kapat ATOLYE işinde 409, mesaj atölye ekranını gösterir; ONAY_BEKLIYOR/PARCA_BEKLIYOR/DIS_SERVISTE girişinde tek aktif bekleme (`uq_hold_aktif`), çıkışta `released_at` dolu; not PATCH'i servis işi durumuna dokunmaz.
- **Canlı risk:** Yok.

### E05-17 · Atölye detayında parça ve süre görünümü — M05-16 · **KISMEN** · P2 · M
- **Canlı karşılık:** Serisiz stok hareketi `services/stock.py:300-340`, `POST /api/stok/hareket` (`cihaz.yaz`, `api/stock.py:296`); bağlantı kolonu E11'de.
- **Yaklaşım:** Detay yanıtına `parcalar` (`stock_movements WHERE service_order_id`) ve `sure` (`service_time_entries`, MOLA hariç kişi-saat; kayıt yoksa `sure_durumu="EKSIK"`). Parça maliyeti alanı `sees_cost` değilse **yanıtta hiç yok**. Parça çıkışı düğmesi `cihaz.yaz` sahibine; teknisyen parça talebi kapsam dışı (E11).
- **Kabul:** 2 parça çıkışı (E11 ucuyla) sonrası detayda 2 satır ve stok bakiyesi düşmüş; zaman kaydı yokken "Süre kaydı eksik"; MOLA 30 dk kişi-saate eklenmez; `maliyet.gor` olmayan yanıtta `maliyet` anahtarı yok.
- **Canlı risk:** `stock_movements`'e yalnız nullable kolon (E11).

### E05-18 · KRİTİK: tamir bedeli gizliliği — M05-17 · **YOK** · P1 · S
- **Canlı karşılık:** Kural ve kalıp hazır: `sees_cost` `api/deps.py:103-105`, alan çıkarma `api/reports.py:41-55`, `api/sims.py:160`.
- **Yaklaşım:** `repair_amount` Out modelinde `exclude`/`None` değil, `sees_cost` false ise dict'ten çıkarılır (liste, detay, Excel, PDF, olay yükü, denetim değeri dahil — denetim `audit.py:19-23` maskeleme listesine `repair_amount` eklenir mi: HAYIR, denetim ekranı `sistem.denetim` iznine tabi; ama olay geçmişi tutar İÇERMEZ). PATCH'te izinsiz kullanıcının tutarı **sessizce yok sayılır**; yazmak `maliyet.gor` + `atolye.yaz` ister. Modalda alan gizli.
- **Kabul:** `maliyet.gor` olmayan GET/liste/Excel/PDF/olay yanıtında `repair_amount` anahtarı yok; aynı kullanıcı PATCH'le 999 gönderir → 200 ve DB değeri değişmemiş; `maliyet.gor`+`atolye.yaz` kullanıcısı değiştirebilir; `test_permissions` maliyet kümesi değişmemiş.
- **Canlı risk:** Yok.

### E05-19 · Yetki, kapsam ve kapanış kontrolleri — M05-18 · **YOK** · P1 · M
- **Canlı karşılık:** `require_permission` `api/deps.py:79-97`; müşteri kapsamı `services/accounts.py:29-61`; kapsam testi emsali `tests/integration/test_kapsam_guvenligi.py:49-56`. Birim kapsamı 00 §6.3'te tanımlanacak.
- **Yaklaşım:** Okuma yalnız `atolye.gor`, yazma yalnız `atolye.yaz` (yedek izin YOK); liste + tek kayıt + ek + uyarı + rapor + Excel + PDF uçlarında müşteri + birim + atama kapsamı; birim taşıma engeli (kaydın birimi kullanıcının birimleri dışına alınamaz); TESLIM_EDILDI'de açık zaman kaydı 409.
- **Kabul:** `isemri.gor`/`rma.gor` sahibi (atolye.gor yok) 403; SERVIS_TEKNISYEN yalnız atandığı kayıtları listeler, başkasının kaydına PATCH 404 **ve** kayıt değişmemiş; GUVENLIK birimi şefi HABERLESME kaydına GET/PATCH/ek listesi 404; uyarı sayısı yalnız kendi birimi; açık sayaçla teslim 409.
- **Canlı risk:** Yok (mevcut rollerin izinleri değişmez).

### E05-20 · Sunucu doğrulaması ve eşzamanlı düzenleme — M05-19 · **KISMEN** · P2 · S
- **Canlı karşılık:** `VersionedMixin` + `StaleDataError→409` (`models/mixins.py:70-86`, `main.py:115-129`); PATCH version kalıbı (`api/rma.py:298-308`); Pydantic `Field` doğrulaması.
- **Yaklaşım:** Pydantic: marka `Literal[ATOLYE_MARKALARI]`, model ≤120, seri ≤60, şikâyet ≥3, e-posta `EmailStr` (hızlı müşteri), liste değerleri `Literal`; uzunluklar tablo kolonlarıyla aynı; `version` zorunlu, uyuşmazlık 409 (istemci değeri kayda ATANMAZ — `api/rma.py:298-302` notu).
- **Kabul:** 300 karakter model 422/400 anlaşılır Türkçe mesaj (500 değil); listede olmayan marka/durum 400; iki sekmede ikinci kayıt 409 "başka kullanıcı değiştirdi".
- **Canlı risk:** Yok.

### E05-21 · "Atölyede" sayımı doğru karttan — M05-D01 · **YOK** · P1 · S
- **Canlı karşılık:** Canlı panel (`services/reports.py:43-131`) mobiliteye özgü; atölye/sahada kartı yok — **dokunulmaz**.
- **Yaklaşım:** Atölye özeti (`/ozet`) ve E01/E12 teknik servis panelinde "Atölyede" = açık `workshop_records` sayısı (durumdan bağımsız); "Sahada" kartı `tur <> 'ATOLYE'` süzer. Canlı mobilite paneli değişmez.
- **Kabul:** ONARIMDA atölye kaydı servis panelinde "Sahada"da değil "Atölyede"; "Atölyede" = atölye listesi açık kayıt toplamı (aynı kapsamla); canlı `/api/raporlar/panel` çıktısı değişmemiş (altın kayıt yeşil).
- **Canlı risk:** Yok.

### E05-22 · Atölye kaydı olmadan ATOLYE servis işi açılamaz — M05-D02 · **YOK** · P1 · S
- **Yaklaşım:** E01 genel açılış ucunda `tur='ATOLYE'` → 400 "Atölye ekranından açın"; atölye kabulü servis işini kendisi açar (aynı transaction). Veri bütünlüğü kontrolüne (`tests/integration/test_veri_butunlugu.py` kalıbı) "atölye kaydı olmayan ATOLYE işi = 0" eklenir.
- **Kabul:** Genel uçtan ATOLYE işi 400; kabul ucu her zaman 1 servis işi + 1 atölye kaydı üretir; bütünlük testi yetim iş sayısını 0 bulur.
- **Canlı risk:** Yok.

### E05-23 · Eski pilot verisi için sağlık raporu ve göç — M05-D03 · **YOK** · P1 · S (göç yapılırsa +M)
- **Canlı karşılık:** Göç kalıbı `app/migration/*` (hazırla/yükle), `SourceMixin` + `uq_*_kaynak` (`models/mixins.py:97-113`).
- **Yaklaşım:** `app/migration/atolye_saglik.py` salt okunur rapor (7 kontrol: durum uyuşmazlığı, iptal-açık iş, seri farkı, eşleşmeyen AssignedTo, yetim iş emri, mükerrer açık seri, eski durum dağılımı). `yukle_atolye.py` idempotent (`source_system='DENGEERP_V1'`, `source_ref=WorkshopTicketId`): durum eşlemesi Yeni Kayıt→KABUL_EDILDI, Onarımda→ONARIMDA, Beklemede→PARCA_BEKLIYOR (liste raporlanır), Test / Kontrol→TEST_KONTROL, Tamamlandı→TESLIME_HAZIR, Teslim Edildi→TESLIM_EDILDI, İptal→IPTAL; geçmiş olaylar uydurulmaz (tek "GOC" olayı); `received_at` kaynak `EntryDate` (kayma düzeltilmez, rapora not); "Garanti Değil" dönüştürülmez → BELIRSIZ değil, onaylı listeye göre; aksesuarlar E05-05.
- **Kabul:** Rapor 7 bölüm üretir ve hiçbir tabloya yazmaz; yükleme ikinci kez koşunca 0 yeni satır; her göç kullanıcı onaylı rapor çıktısıyla başlar.
- **Canlı risk:** Yok (yalnız yeni tablolara yazar).

### E05-24 · Dış servis (üretici/distribütör RMA) takibi — M05-D04 · **KISMEN** · P3 · M
- **Canlı karşılık:** RMA'da tedarikçi takibi var (`models/service.py:104-110`, `PATCH /api/rma/{id}/tedarikci`) ama `device_id` zorunlu → müşteri malı telsize uygulanamaz.
- **Yaklaşım:** DIS_SERVISTE durumu + `external_vendor_id` (Account `is_tedarikci`), `external_rma_no`, `external_sent_at`, `external_returned_at`; bekleme `DIS_SERVIS`; KPI'da ayrı süre; cihaz Denge `devices` kaydıysa ayrıca RMA köprüsü (`POST /{id}/rma`).
- **Kabul:** DIS_SERVISTE'ye geçiş `external_vendor_id` ve `external_sent_at` ister (400); dönüş < gönderim 400; dış servis süresi atölye çevrim ortalamasından ayrı raporlanır.
- **Canlı risk:** RMA servisi değiştirilmez, yalnız çağrılır.

### E05-25 · Toplu kabul (kabul grubu) ve toplu atama — kaynak: M05 soru 5, eski E-12 + kullanıcının doğruladığı "toplu atama" · **YOK** · P2 · M
- **Yaklaşım:** `POST /toplu-kabul` (her cihaz ayrı kayıt + ayrı servis işi, ortak `intake_group_no`, tek fiş PDF); `POST /toplu-ata`. Hepsi-ya-hiçbiri transaction.
- **Kabul:** 12 telsizlik grup → 12 kayıt, 12 servis işi, 1 grup no, 1 fiş; gruptaki bir seri açık kayıtlıysa 409 ve hiçbir kayıt açılmaz; toplu atamada bir kayıt kapsam dışıysa 404 ve hiçbiri değişmez.
- **Canlı risk:** Yok.

### E05-26 · İzinler, roller, ek/görev/KVKK entegrasyonu — kaynak: M05-18, M05-01 (`workshop.close`) · **KISMEN** · P1 · S
- **Canlı karşılık:** `permissions.py:14-248`, ekler `models/attachment.py:31-62` + `api/attachments.py:41-52,91-114`, görev `services/gorevler.py:47-57`, KVKK `services/kvkk.py`.
- **Yaklaşım:** §4 izinler/roller; ek türleri `MUSTERI_IMZASI` (00'da önerilen) ve `CIHAZ_FOTOGRAFI` (E01 ile ortak) — atölye ekleri E01'in `service_orders` sahibine bağlanır, `_kapsam` E01'de müşteri+birim+atama ile genişletilir; `KayitTipi("atolye", ...)`; KVKK alanları.
- **Kabul:** `test_permissions`: her yeni izin ≥1 rolde, maliyet kümesi sabit, YONETIM yazma izni taşımıyor; kapsam dışı servis işinin ek listesi/indirme 404; görev kartı atölye kaydına bağlanır ve aramada `AT-` no ile bulunur.
- **Canlı risk:** `attachments._kapsam` genişlemesi yalnız yeni entity için dal ekler; `accounts` dalı aynen.

### E05-27 · Kiralama iadesi testinden atölyeye köprü — kaynak: M05 soru 4 (L-26 `KIRALAMA_TAKIP`) · **YOK** · P3 · S
- **Yaklaşım:** "Kiradan Dönen El Telsizi Testi" kiralama modülünün (E06) iade kontrol adımıdır; test başarısızsa E06 ucu bu modülün kabul servis fonksiyonunu `service_type='KIRALAMA_TAKIP'` ile çağırır, müşteri = Denge iç hesabı değil kiracı hesap, kaynak `rental_item_id` olay yüküne yazılır (FK eklenmez; E06 tablosu kesinleşince nullable kolonla).
- **Kabul:** Kiralama iadesinde "arızalı" işaretlenen telsiz için tek tıkla atölye kaydı açılır, olayda kiralama no görünür; atölye kaydı kiralama müsaitlik EXCLUDE'una dokunmaz.
- **Canlı risk:** Yok.

### E05-28 · Atölye uyarıları ve teslim alınmayan cihaz politikası — kaynak: M05-08a, M05 soru 7 · **KISMEN** · P3 · S
- **Canlı karşılık:** Hesaplanan uyarı altyapısı `services/uyarilar.py:28-35,47-190`.
- **Yaklaşım:** §7 uyarı kodları, birim kapsamlı sayım, eşikler ayarlardan.
- **Kabul:** FakeClock ile 31 gün ilerletilince TESLIME_HAZIR kaydı `ATOLYE_TESLIM_ALINMADI` sayısında; başka birim şefi bu sayıyı görmez; `atolye.gor` olmayan kullanıcıda blok yok.
- **Canlı risk:** Yok (yeni blok).

---

## 9. Test planı

| Dosya | İçerik |
|---|---|
| `tests/unit/test_statemachine.py` | Değişiklik yok; `ATOLYE` `MAKINELER`'e girince otomatik sınanır |
| `tests/unit/test_atolye_esleme.py` | §3.2 meta-test (eşleme tam, hedefler geçerli, her geçiş SERVIS_IS_EMRI'nde izinli) |
| `tests/unit/test_permissions.py` | Değişiklik yok; yeni izinler otomatik denetlenir |
| `tests/integration/test_atolye_kabul.py` | kabul, açık kayıt 409, toplu kabul, hızlı müşteri mükerrer aday 409, garanti hesabı, status yok sayma |
| `tests/integration/test_atolye_durum.py` | tüm iş kuralları (§3.1), bekleme senkronu, servis işi eşlemesi, genel uçların 409/400'ü, açık sayaçla teslim 409 |
| `tests/integration/test_atolye_kapsam.py` | iki birim + teknisyen atama kuralı: liste boş, GET/PATCH 404 + `db.refresh` ile değişmemiş, ek 404, uyarı sayısı |
| `tests/integration/test_atolye_maliyet.py` | bedel anahtarı yok (liste/detay/Excel/PDF bağlamı), izinsiz PATCH değeri korunur |
| `tests/integration/test_atolye_rapor.py` | ozet = liste toplamı, Excel id kümesi = liste, çevrim süresi eksik sayımı, MOLA hariç |
| `tests/migration/test_migration_zinciri.py`, `test_altin_kayit.py` | head→base→head, tek head, **932 iş / 552.825,00 TL yeşil** |

- Yeni tablolar FK ile `service_orders`/`accounts`'a bağlı → `TRUNCATE ... CASCADE` kapsar. Ancak bağımsız `SEQUENCE`'ler `RESTART IDENTITY` ile sıfırlanmaz: conftest'e `ALTER SEQUENCE atolye_no_seq RESTART; ALTER SEQUENCE atolye_kabul_grubu_seq RESTART` eklenir ya da testler numara değerine bağlanmaz (karar: conftest'e eklenir).
- Her uç için 403/200 çifti; fixture'lar `client` (FakeClock), `kullanici_ac`, birim üyeliği yardımcısı (00 §6.3'te eklenecek).

---

## 10. Uygulama sırası (E05 içi)

1. Önkoşullar hazır mı: RBAC+birim, E01 çekirdek (ATOLYE türü, olay/bekleme türleri), E03 ekipman, E09 zaman.
2. E05-26 (izin/rol) → E05-01 + E05-12 + E05-13 + E05-16 + E05-22 (makine, eşleme, genel uç korumaları) → E05-11, E05-15, E05-14.
3. E05-18 (KRİTİK bedel) ve E05-19 (kapsam) çekirdekle aynı PR'da — kapsamsız/bedeli açık uç hiç yayına çıkmaz.
4. E05-02, E05-05, E05-06, E05-07, E05-10, E05-08, E05-25, E05-03, E05-04.
5. E05-17, E05-09, E05-20, E05-21, E05-24, E05-28, E05-27; göç gerekiyorsa E05-23.
Her adım sonunda: `make test` (altın kayıt dahil), migration zinciri, `ruff`, `npm run build` + `oxlint`.

---

## 11. Kararlar (kullanıcıya soru sorulmadı; gerekçeleriyle)

1. **Atölye kaydı 1:1 servis işi (E01 `service_orders`, tür ATOLYE) ile açılır; durum tek servis fonksiyonundan yürür.** Eski hataların kökü iki kaynaklı durum/atama/seri idi; servis işini yeniden kullanmak atama, zaman, parça, bekleme, ek ve görev altyapısını tekrar yazmadan verir. Mobilite `work_orders` kullanılmaz (00 §6.2).
2. **Ayrı `WorkshopTicketStatusLog` tablosu açılmaz;** durum geçmişi E01 `service_order_events` (silinemez) içinde `ATOLYE_DURUM` türüyle tutulur. Tek zaman çizelgesi hem atölye hem iş tarihçesi gereksinimini karşılar.
3. **TESLIM_EDILDI ve IPTAL terminaldir;** "kapalı kaydı yeniden açma" gereksinimi, teslim öncesi geri alma geçişlerine (`atolye.kapat` + gerekçe) indirgendi. Gerekçe: canlı RMA ilkesi "kapanan kayıt yeniden açılmaz, yeni arıza yeni kayıttır" (`statemachine.py:159-161`) ve servis işi KAPANDI'nın geri açılması hak ediş benzeri kapanış mantığıyla çelişir. Teslimden sonra dönen cihaz yeni kayıttır; tekrar geliş ve onarım garantisi otomatik tespit edilir.
4. **Fiyat izni = canlı `maliyet.gor`;** yeni "fiyat görme" izni açılmaz, `maliyet.gor` yeni rollere verilmez (kilitli test). Şef ihtiyacı kişi bazlı `UserPermission` ile.
5. **İzinsiz kullanıcının bedel alanı yanıtta HİÇ yer almaz** (eski kabuldeki "null" yerine): canlı kural 00 §0/9 bağlayıcıdır. Gönderdiği tutar yok sayılır (403 değil).
6. **İzinler `atolye.gor / atolye.yaz / atolye.kapat`.** Teslim ve kargo `atolye.yaz` ile (kabul/teslimi aynı kişi yapıyor); `atolye.kapat` iptal ve geri alma içindir. Eski "Teslim = şef" önerisi, kabul personelinin teslimi yapamaması sonucunu doğuracağı için alınmadı.
7. **Kabul rolü = yeni `ATOLYE` rolü** (eski "Operasyon Uzmanı" varsayımı yerine); `hesap.yaz` verilmez, yeni müşteri kabul ucunun içinde mükerrer aday kontrolüyle minimal hesap olarak açılır (hesap düzenleme yetkisi genişlemesin).
8. **Ücretli onay minimal:** kayıt üstünde alanlar; ayrı onay tablosu yok. Onay kanalı TELEFON/EPOSTA/YAZILI/TEKLIF; bağlı teklif KABUL ise onay sayılır. Eşik tutar altında onaysız onarım kuralı yok — ihtiyaç olursa `ONAY_GEREKMEZ` + gerekçe kullanılır.
9. **Garanti "Bilinmiyor" = canlı `BELIRSIZ`** değeri; RMA ile aynı kelime dağarcığı (+ `ONARIM_GARANTISI`). Denge onarım garantisi ve tekrar geliş penceresi 90 gün, ayarlardan değiştirilebilir. Eski "Garanti Değil" kayıtları otomatik dönüştürülmez.
10. **Dış servis izlenir** (soru 3 → evet), atölye kaydı içinde; RMA yalnız Denge `devices` kaydı olan cihazda köprülenir.
11. **Toplu gelen telsiz:** her cihaz ayrı kayıt + ortak kabul grubu numarası + tek fiş (1 cihaz = 1 kayıt kuralı korunur).
12. **İmza kâğıtta kalır;** imzalı fiş/tutanak taraması ve cihaz fotoğrafı ek olarak yüklenir (mobil uygulama kapsam dışı — `models/attachment.py:3-7`).
13. **Teslim alınmayan cihaz:** 30. günde uyarı; otomatik işlem (hurda/iade) yapılmaz.
14. **Kiradan dönen telsiz testi kiralama modülündedir;** yalnız arıza çıkarsa atölye kaydı açılır (`KIRALAMA_TAKIP`).
15. **PDF canlı WeasyPrint altyapısıyla** üretilir; denetimin "yalnız HTML yazdır" önerisi eski sistemin ASCII PDF sorunundan doğmuştu, canlıda bu sorun yok.
16. **Markalar kodda sabit liste** (L-25 + DIGER): sunucu doğrulaması ve açık kayıt tekilliği için tutarlı değer şart; yeni marka nadir ve kod değişikliğiyle eklenir.
17. **Açık kayıt tekilliği ekipman (marka + normalize seri) üzerinden;** yalnız seri kullanmak farklı üreticilerin çakışan serilerinde yanlış 409 üretirdi; marka sabit listeden geldiği için yazım farkı oluşmaz.
18. **Kabul zamanı istemciden alınmaz;** geçmiş tarihli giriş yalnız göç betiğinde.
19. **Zaman faaliyeti:** E09 `ATOLYE`/`TEST` faaliyetlerini eklemezse `ISCILIK` kullanılır; E05 kendi faaliyet listesini tanımlamaz (CHECK sahipliği E09'da).
20. **Numara üretimi PostgreSQL SEQUENCE** (`AT-YYYY-NNNNNN`); yıl değişiminde sıfırlanmaz (sıfırlama eşzamanlılık riski doğurur), yıl yalnız önektir.
21. **Eski pilot verisinin göçü koşulludur;** pilot gerçek veri üretmediyse E05-23 yalnız sağlık raporu olarak kalır. Logo Form No alanları yalnız serbest metin.
22. **Canlı mobilite paneli değiştirilmez;** "Atölyede/Sahada" düzeltmesi yeni teknik servis panelinde ve atölye özetinde uygulanır.

---

## 12. Gözlemler (canlı kodda, DEĞİŞTİRİLMEDİ)

1. `api/attachments.py:192-203` `_SAHIP_TABLOSU` `rma_cases`, `purchase_orders`, `partner_settlements` içeriyor, ama `models/attachment.py:31-42` `EK_SAHIPLERI` ve `api/attachments.py:41-52` `SAHIP_IZNI` bunları içermiyor (`contracts`/`settlements` adlarıyla farklı). Sonuç: RMA kaydına ek yüklenemiyor (`_sahip_dogrula` 400). Yeni varlık eklerken üç liste birlikte güncellenmeli; E05 bu yüzden ekleri E01'in `service_orders` sahibine bağlar.
2. `api/rma.py:121-142` RMA listesi `sayfala()` ve `kapsam_musteri` kullanmıyor: `rma.gor` sahibi SATIS (KENDI_MUSTERILERI) tüm müşterilerin servis kayıtlarını görüyor; ayrıca `GET /api/rma/{id}` kapsam kontrolü yapmıyor. Güvenlik sıkılaştırma aşamasına not.
3. `services/rma.py:70-72` numara `max(id)+1` — eşzamanlı açılışta `uq_rma_no` çakışması (00 §1.3 ile aynı gözlem). E05 SEQUENCE kullanır.
4. `services/reports.py:81` `"DEGISTI"` (geçerli değer `DEGISTIRILDI`) — 00'da kayıtlı gözlem, burada da tekrar doğrulandı.
