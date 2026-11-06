# E03 — Güvenlik Cihaz Kütüğü (X-Ray, kapı dedektörü vb.): Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21 · Hedef: Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdi: `analiz/02_moduller/_ozet/03_cihaz_kutugu.json` (denetçi onaylı 16 madde), `03_cihaz_kutugu_tasarim.md`, `03_cihaz_kutugu_denetim.md`, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`.
> Kaynak koda DOKUNULMADI; aşağıdaki "canlı karşılık" satırları kod okunarak doğrulandı (dosya:satır `backend/app/` ve `frontend/src/` köküne göredir).
> Madde kimlikleri `E03-NN`; her maddede eski analiz kimliği (`M03-xx`) verilir.

---

## 0. Özet

| | |
|---|---|
| Canlıda karşılık | **Yok denecek kadar az.** Canlıdaki `devices` (`models/device.py:72-158`) mobilite stok cihazıdır: global `uq_devices_seri` (`:93-98`), stok yaşam döngüsü (`CIHAZ_DURUMLARI` `:47-62`), `identity_kind` FK'sı (`:79-90`) taşır. Müşteri malı, seri no'su mükerrer/boş olabilen 1.324 güvenlik cihazı buraya giremez (mimari karar, `00_MIMARI_KURALLAR.md` §5). |
| Yeniden kullanılan | `accounts` (müşteri), `addresses` (lokasyon/tesis), `contacts` (saha irtibatı), `products` (marka/model + `warranty_months` `models/catalog.py:97`), `audit_logs` + `audit.log_change` (`services/audit.py:55-92`), `attachments`, görev panosu `KAYIT_TIPLERI` (`services/gorevler.py:47-57`), `sayfala()`, `services/export.py` (formül enjeksiyonu korumalı xlsx), `services/normalize.py`, `services/statemachine.py`, `migration/` göç kalıbı (hazırla → karantina → yükle). |
| Yeni tablo | **Yalnız `service_equipment`** (genel teknik servis ekipman kütüğü; bu modül GÜVENLİK birimi kayıtlarıyla başlar). Sözleşme bağı `maintenance_contract_items.equipment_id` üzerinden (Bakım Sözleşmesi modülü), değişiklik geçmişi `audit_logs` üzerinden; ayrı geçmiş / öneri / alias tablosu AÇILMAZ. |
| Yeni izin | `ekipman.gor`, `ekipman.yaz` (Excel için mevcut `rapor.disaaktar` yeniden kullanılır). |
| Yeni durum makinesi | `SERVIS_EKIPMANI` → `MAKINELER["servis_ekipmani"]`. |
| Dokunulmayan | `devices`, cihaz durum makinesi, `work_orders/work_order_items/settlements`, stok EXCLUDE kısıtları, mevcut `TEKNIK_SERVIS` rolü. |

Kullanıcının eski sistemde bizzat doğruladığı işlevler korunur: **KPI kutuları tıklanabilir** (E03-11, E03-15), **toplu işlem** (çoklu seçimle toplu durum / toplu sözleşmeye bağlama / toplu servis işi açma — E03-08, E03-09, E03-11), **Excel dışa aktarım** (E03-11), **cihaz başına PB iş emri** (E03-07; üretim Planlı Bakım modülünde, ekipman kimliğine bağlı).

---

## 1. Veri modeli

### 1.1 `service_equipment` (yeni, `models/teknik_servis.py`)

Mixin'ler: `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin` (`models/mixins.py:23-113`); `models/__init__.py` import + `__all__` kaydı.

| Kolon | Tip | Not |
|---|---|---|
| `birim` | `String(12)` NOT NULL | `ck_svceq_birim` → `permissions.BIRIMLER` kodları (GUVENLIK, HABERLESME, POC, MOBILITE, ARAC_TAKIP). Kütük göçü `GUVENLIK` yazar. |
| `equipment_type` | `String(30)` NOT NULL | `EKIPMAN_TIPLERI = ("XRAY","KAPI_DEDEKTORU","EL_DEDEKTORU","DIGER_GUVENLIK","DIGER")` + `ck_svceq_tip`. Ekranda `KAPI_DEDEKTORU` = "Kapı Tipi Metal Dedektörü". Tip listesi genişlerse CHECK migration'ı ELLE yazılır (drop+create). |
| `product_id` | `BigInteger` FK `products.id` `ON DELETE SET NULL`, NULL | Katalogda karşılığı olan model için; zorunlu değil (eski kütükte 193 farklı model metni var). |
| `brand` / `model` | `String(60)` / `String(80)` | Ekranda gösterilen metin (ürün seçilince üründen kopyalanır). |
| `model_key` | `String(80)` | `normalize.model_anahtari(model)` = Türkçe katlama + büyük harf + boşluk/`-` kaldırma. Filtre buradan (M03-10c). |
| `product_raw` | `Text` | Kaynaktaki ham ürün metni, değiştirilmez. |
| `serial_no` | `String(200)` NULL | **Metin**: baştaki sıfır, iç boşluk, `-` `.` `/` korunur; uydurulmaz. |
| `serial_key` | `String(200)` NULL | `normalize.seri_anahtari(serial_no)` = yalnız `strip()` + Türkçe güvenli büyük harf. ORM `before_insert/before_update` olayıyla doldurulur (`models/account.py:193-196` emsali). **UNIQUE DEĞİL** (kaynakta 38 seri/96 satır mükerrer). |
| `account_id` | FK `accounts.id` `ON DELETE RESTRICT`, NULL | Müşteri = hesap (`is_musteri`). Göçte eşleşmeyen satır NULL kalır + `customer_name_raw`. |
| `customer_name_raw` | `String(200)` | Kaynak müşteri adı (eşleştirme izi). |
| `address_id` | FK `addresses.id` `ON DELETE SET NULL`, NULL | Servis lokasyonu/tesis (addresses genişletmesi servis lokasyonu modülünde). Şehir `addresses.city`'den okunur; ekipmana ayrı `city` kolonu AÇILMAZ. |
| `location_raw` | `Text` | Kaynak lokasyon metni. |
| `zone` | `String(120)` | Cihaz bölgesi ("B Kapısı Giriş", "Kargo Kabul"). |
| `contact_id` | FK `contacts.id` `ON DELETE SET NULL`, NULL | Saha irtibatı. |
| `contact_name_raw` | `String(120)` | **Kişisel veri** → denetimde `is_personal_data=True`, KVKK anonimleştirmesine dahil. |
| `delivery_date` / `delivery_date_raw` | `Date` / `String(100)` | Excel gün sayısı dönüşümü (M03-10a); ham metin korunur. |
| `install_date` | `Date` NULL | Gelecek tarih servis katmanında (`Clock`) reddedilir. |
| `warranty_start` / `warranty_end` | `Date` NULL | `ck_svceq_garanti_aralik`: `warranty_end IS NULL OR warranty_start IS NULL OR warranty_end >= warranty_start`. |
| `warranty_source` | `String(12)` NULL | `GARANTI_KAYNAKLARI = ("BELGE","HESAPLANDI","BILINMIYOR")` + `ck_svceq_garanti_kaynagi`. |
| `lifecycle_status` | `String(20)` NOT NULL default `'BILINMIYOR'` | `EKIPMAN_DURUMLARI = ("KURULU","KURULUM_BEKLIYOR","DEVRE_DISI","HURDA","BILINMIYOR")` + `ck_svceq_durum`. "Serviste" SAKLANMAZ, açık ARIZA servis işinden hesaplanır. |
| `is_active` | `Boolean` default true | Kayıt geçerli mi (mükerrer/hatalı kayıt pasifi). Fiziksel durumdan AYRI (denetim M03-04 notu 4). `accounts.is_active` emsali. |
| `merged_into_id` | FK `service_equipment.id` `ON DELETE SET NULL` | `ck_svceq_kendine_birlesemez` (`id <> merged_into_id`), `ck_svceq_birlesen_pasif` (`merged_into_id IS NULL OR NOT is_active`). |
| `duplicate_ack_reason` | `Text` NULL | Aynı tip+marka+seri ile ikinci aktif kayıt için "farklı cihaz" gerekçesi. |
| `device_id` | FK `devices.id` `ON DELETE SET NULL`, NULL | `ck_svceq_cihaz_birim`: `device_id IS NULL OR birim IN ('MOBILITE','ARAC_TAKIP')`. Güvenlik ekipmanı `devices`'a yazılmaz. |
| `notes` | `Text` | |

Kısıt/indeksler: `uq_svceq_kaynak (source_system, source_ref)`, `ix_svceq_seri (serial_key)`, `ix_svceq_seri_trgm` (`serial_key gin_trgm_ops`, arama), `ix_svceq_tip_marka_model (equipment_type, brand, model_key)`, `ix_svceq_hesap (account_id)`, `ix_svceq_adres (address_id)`, `ix_svceq_birim_durum (birim, lifecycle_status)`. Tümü `uq_/ck_/ix_` önekli (`main.py:71-77`).

### 1.2 Başka modüllerin tablolarına beklenen bağlar (bu modül YAZMAZ, kolon adını sabitler)

| Tablo (sahip modül) | Kolon | Amaç |
|---|---|---|
| `maintenance_contract_items` (Bakım Sözleşmesi) | `equipment_id` FK → `service_equipment.id` RESTRICT, NOT NULL; tarihli `ex_sozlesme_kalem_cakisma` | "Bağlı cihaz" = aktif kalem. Eski `MaintenanceContractId` kolonu ekipmana EKLENMEZ (bir cihaz zamanla sözleşme değiştirir; tarihli kalem doğruluk kaynağıdır). |
| `service_orders` (Servis İş Emri) | `equipment_id` FK, `contract_item_id`, `tur` | Birleşik geçmiş, "Serviste" rozeti, tekrar arıza KPI'ı, PB = 1 ekipman. |
| `service_results` (Servis İş Emri) | `saha_seri_no String(200)`, `saha_bolge String(120)`, `kutuk_fark_durumu String(12)` (`ACIK/UYGULANDI/YOK_SAYILDI`, `ck_svcres_kutuk_fark`) | Sahadan gelen farklar (E03-14); ayrı öneri tablosu yok. |
| `stock_movements` (canlı, genişletme) | nullable `service_order_id` | Parça geçmişi (E03-06). |

### 1.3 Durum makinesi (`services/statemachine.py`)

```python
SERVIS_EKIPMANI = StateMachine(
    ad="Servis Ekipmanı",
    baslangiclar=frozenset({"BILINMIYOR", "KURULUM_BEKLIYOR", "KURULU"}),
    gecisler=_m(
        BILINMIYOR=("KURULUM_BEKLIYOR", "KURULU", "DEVRE_DISI", "HURDA"),
        KURULUM_BEKLIYOR=("KURULU", "DEVRE_DISI", "HURDA"),
        KURULU=("DEVRE_DISI", "KURULUM_BEKLIYOR"),
        DEVRE_DISI=("KURULU", "HURDA"),
        HURDA=("DEVRE_DISI",),   # gerekçeyle geri alınabilir (denetim M03-04)
    ),
)
MAKINELER["servis_ekipmani"] = SERVIS_EKIPMANI
```
Durum alanına doğrudan atama yok; servis içinde `SERVIS_EKIPMANI.dogrula()` çağrılır, API yanıtı `sonraki_durumlar` döner (`api/rma.py:103, 211` emsali).

### 1.4 İzinler ve roller (`permissions.py`)

```python
"ekipman.gor": ("Servis Ekipmanı", "Ekipman kütüğünü, kartı ve geçmişini görür"),
"ekipman.yaz": ("Servis Ekipmanı", "Ekipman ekler, düzenler, durum değiştirir, pasife alır, birleştirir, saha farkını kütüğe uygular"),
```
- Excel: `ekipman.gor` + mevcut `rapor.disaaktar` (yeni `ekipman.disaaktar` açılmaz; eski karar).
- Roller (RBAC+birim adımında açılan yeni roller): `SERVIS_YONETICI` (gor+yaz, TUMU), `SERVIS_SEF` (gor+yaz, KENDI_BIRIMI), `SERVIS_TEKNISYEN` (gor, KENDI_BIRIMI), `ATOLYE` (gor, KENDI_BIRIMI). `ADMIN` hepsini, `YONETIM` `.gor` kuralıyla `ekipman.gor`'u otomatik alır (`permissions.py:84, 247`). Mevcut roller (SATIS, DEPO, MUHASEBE_DESTEK, TEKNIK_SERVIS ...) DEĞİŞMEZ → kütük yalnız yeni servis rollerine açılır. `maliyet.gor` kümesi değişmez.

### 1.5 Ayarlar (`services/settings.py` `DEFAULTS`)

`servis.kpi_bakim_gecikme_ay = 12`, `servis.tekrar_ariza_gun = 90`, `servis.tekrar_ariza_esik = 2`, `servis.garanti_uyari_gun = 60` (garanti KPI'ı veri dolunca açılır).

### 1.6 Dosyalar

```
backend/app/models/teknik_servis.py                 (+ models/__init__.py)
backend/app/services/teknik_servis/ekipman.py       (CRUD, durum, birleştir, eşleştir, veri kalitesi, KPI)
backend/app/services/teknik_servis/kapsam.py        (RBAC+birim adımından: kapsam_birim, birim_disinda_mi)
backend/app/services/normalize.py                   (EKLEME: seri_anahtari, model_anahtari, excel_gun_tarihi)
backend/app/services/statemachine.py                (EKLEME: SERVIS_EKIPMANI)
backend/app/permissions.py                          (EKLEME: ekipman.gor/yaz + yeni rollere)
backend/app/api/teknik_servis.py                    (/api/teknik-servis/ekipman...)
backend/app/models/attachment.py, api/attachments.py, services/gorevler.py, api/search.py, services/kvkk.py, services/uyarilar.py, services/settings.py (EKLEME blokları)
backend/app/migration/kaynak_kutuk.py, hazirla_kutuk.py, yukle_kutuk.py, kutuk_profil.py
backend/alembic/versions/<rev>_servis_ekipman_kutugu.py
backend/tests/integration/test_servis_ekipman.py, test_servis_ekipman_kapsam.py, test_servis_ekipman_gecmis.py, test_servis_ekipman_kalite.py
backend/tests/unit/test_normalize_seri.py, tests/migration/test_kutuk_gocu.py
frontend/src/api/teknikServis.ts, pages/ServisEkipmanPage.tsx, components/EkipmanFormu.tsx, components/EkipmanKarti.tsx
```

---

## 2. Maddeler

### E03-01 · Kütük izinleri ve kayıt/birim kapsamı — P1 · S · (M03-13, M03-D03 özü)
- **Canlı durum: YOK.** `cihaz.gor/cihaz.yaz` (`permissions.py:22-24`) mobilite cihazı içindir; kütük izni yok. Kapsam yalnız `KENDI_MUSTERILERI` (`services/accounts.py:29-61`).
- **Yaklaşım:** §1.4 izinleri. `api/teknik_servis.py` içinde `EkipmanOkuyucu = Annotated[User, Depends(require_permission("ekipman.gor"))]`, `EkipmanYazici = ... ("ekipman.yaz")`, `EkipmanAktarici = ... ("ekipman.gor","rapor.disaaktar")` (çoklu kod = hepsi, `api/deps.py:79-97`). Liste uçları `kapsam_musteri(stmt, user, ServiceEquipment.account_id)` + `kapsam_birim(stmt, user, ServiceEquipment.birim)`; tek kayıt uçları `kapsam_disinda_mi` / `birim_disinda_mi` → 404 (yazmadan ÖNCE). PATCH'te `birim` değiştirilirse hedef birim kullanıcının birimlerinde olmalı, değilse 403 (`api/accounts.py:441-447` emsali). Bakım sözleşmesi uçları yalnız `bakim.gor` ile açılır; `isemri.gor` ya da `ekipman.gor` fallback'i KONMAZ (M03-D03 özü — Bakım Sözleşmesi modülünün kabulüne taşınır).
- **Kabul:** (1) Yalnız `isemri.gor` sahibi (ör. MONTAJ_KOORD) `/api/teknik-servis/ekipman` → 403. (2) `SERVIS_TEKNISYEN` GET 200, POST/PATCH 403. (3) HABERLESME birimindeki şef GÜVENLİK ekipmanında GET 404, PATCH 404 **ve** `db.refresh` sonrası kayıt değişmemiş. (4) Liste ve `X-Toplam-Kayit` yalnız kendi biriminin sayısını verir. (5) `tests/unit/test_permissions.py` yeşil (her izin bir rolde, `maliyet.gor` kümesi aynı).
- **Bağımlılık:** RBAC+birim adımı (`BIRIMLER`, `SCOPE_OWN_UNITS`, `user_units`, `kapsam.py`, SERVIS_* rolleri).
- **Canlı risk:** Düşük. Yalnız yeni izin/rol eklenir; mevcut rol listeleri değişmez. Özelleştirilmiş DB rollerine izin inmez (`models/rbac.py:64-69`) → yayın notunda belirtilir.

### E03-02 · Ekipman ekle / düzenle / pasife al (iyimser kilit, metin seri no, tekil olmayan normalize indeks) — P1 · M · (M03-06)
- **Canlı durum: YOK** (kütük için). `api/devices.py:198-221` yalnız mobilite cihazı açar ve `uq_devices_seri` global tekildir — kullanılamaz.
- **Yaklaşım:** Model §1.1. Migration `make makemigration m="servis_ekipman_kutugu"`; docstring'de NEDEN (`devices`'a neden yazılmadığı, seri tekilliğinin neden uygulamada olduğu); downgrade tabloyu düşürür. Servis `services/teknik_servis/ekipman.py`: `@dataclass EkipmanGirdisi`, `class EkipmanHatasi(ValueError)`, `olustur(db, girdi, *, clock, user_id)`, `guncelle(...)`, `pasife_al(db, ekipman, gerekce)`, `aktife_al(...)`. Mükerrer kontrol: `pg_advisory_xact_lock(hashtext(tip||'|'||coalesce(marka,'')||'|'||serial_key))` alınır, aynı tip+marka+`serial_key` ile `is_active AND NOT is_deleted` başka kayıt varsa ve `duplicate_ack_reason` boşsa `EkipmanHatasi` → 409 ("Aynı seri no ile aktif kayıt var: #id"). Seri no boşsa kontrol yapılmaz, kayıt "Seri no eksik" etiketi alır. API: `POST /api/teknik-servis/ekipman` (201), `PATCH /ekipman/{id}` (gövdede `version`; uyuşmazlık 409, `api/accounts.py:434-440`), `POST /ekipman/{id}/pasif` ve `/aktif` (`gerekce` min 5 karakter). Fiziksel silme ucu YOK. Ön yüz: `EkipmanFormu` (KartPenceresi kalıbı, tek form yeni+düzenle; müşteri `Select` hesap araması, lokasyon müşterinin adreslerinden, ürün katalog araması opsiyonel; 409 mükerrer yanıtında "Farklı cihaz olduğunu onaylıyorum" + gerekçe alanı açılır).
- **Kabul:** (1) `ekipman.yaz` olmayana 403. (2) `'00123/A-7'` aynen saklanır ve döner; `serial_key='00123/A-7'`. (3) Aynı tip+marka+seri ile ikinci aktif kayıt gerekçesiz 409, gerekçeyle 201. (4) Aynı kaydı eski `version` ile düzenleyen ikinci istek 409. (5) Her yazma `audit_logs`'a düşer (E03-03).
- **Bağımlılık:** E03-01.
- **Canlı risk:** Yok (yeni tablo). `devices` ve kısıtlarına dokunulmaz.

### E03-03 · Kütük değişiklik geçmişi (yalnız INSERT, aynı transaction) — P1 · S · (M03-07)
- **Canlı durum: KISMEN.** `audit.log_change` yalnız değişen kolonları eski/yeni yazar ve çağıranın transaction'ında flush eder (`services/audit.py:26-92`); `audit_logs` için güncelleme/silme ucu yok (`api/audit_api.py` yalnız GET, `sistem.denetim`). Eksik: kayıt bazlı, `ekipman.gor` ile okunabilen geçmiş ucu.
- **Yaklaşım:** Ayrı geçmiş tablosu AÇILMAZ. Tüm ekipman yazmaları commit'ten önce `audit.log_change(db, ekipman, "<eylem>", user_id, ip, is_personal_data=<irtibat değiştiyse True>)`; eylem adları: `olustur`, `guncelle`, `durum.degistir`, `pasif`, `aktif`, `birlestir`, `saha.uygula`, `saha.yoksay`, `garanti.toplu`. Gerekçe `new_value["gerekce"]` içinde. Uç: `GET /api/teknik-servis/ekipman/{id}/degisiklikler` (EkipmanOkuyucu + kapsam) → `audit_logs WHERE entity='service_equipment' AND entity_id=:id` + `users.full_name` join. Kullanıcı adı kopyası tutulmaz: kullanıcılar silinmez, kapatılır (`yonetim.py:75`).
- **Kabul:** (1) Seri no değişikliğinde eski/yeni değer, kullanıcı adı ve zaman görünür. (2) Geçmiş için PATCH/DELETE ucu yok (OpenAPI testinde doğrulanır). (3) Servis içinde `EkipmanHatasi` atılan yazmada `audit_logs` satırı oluşmaz (rollback testi). (4) Teknisyen (`ekipman.gor`) geçmişi görür, `sistem.denetim` gerekmez; başka birim 404.
- **Bağımlılık:** E03-02.
- **Canlı risk:** Yok. `audit_logs` şeması değişmez.

### E03-04 · İlk aktarım tek seferlik ve idempotent; mevcut kayıtları ezmez — P1 · S · (M03-01, .NET'e özgü; özü kabule taşındı)
- **Canlı durum: KISMEN.** Göç altyapısı var: `migration/` (hazırla → karantina → yükle, ör. `migration/hazirla_envanter.py`, `yukle.py`), `SourceMixin` + `uq_<tablo>_kaynak` idempotentliği; içe aktarma çekirdeği varsayılan olarak çakışmayı **atlar** (`services/imports/cekirdek.py:119-136`). Kütük kaynağı ve profili yok.
- **Yaklaşım:** `migration/kaynak_kutuk.py` (X-RAY KÜTÜK Excel'i / eski SQL Server dökümü okur), `migration/hazirla_kutuk.py` (saf fonksiyonlar: tip eşleme, `excel_gun_tarihi`, `seri_anahtari`, hesap eşleştirme `title_key` + `pg_trgm` aday, belirsizler karantinaya), `migration/yukle_kutuk.py` (`INSERT ... ON CONFLICT ON CONSTRAINT uq_svceq_kaynak DO NOTHING`; `source_system='DENGEERP_V120'`, `source_ref=SourceKey`). `is_active` zorlanmaz, `lifecycle_status` kaynakta yoksa `BILINMIYOR`. Bakım sözleşmesi göçü Bakım Sözleşmesi modülünde AYNI kuralla yazılır (pasif sözleşme yeniden aktifleşmez, PB üretmez). Komut `make` hedefi olarak eklenir (`sistem.goc` ile ekrandan değil, CLI'dan).
- **Kabul:** (1) Yükleme ikinci kez koşunca satır sayısı değişmez, ekrandan yapılmış düzeltme (seri no, pasif, durum) korunur. (2) Pasife alınmış sözleşme yeniden yüklemeden sonra pasif kalır ve worker PB üretmez (sözleşme modülü testi). (3) Karantina raporu: eşleşmeyen müşteri, seri no'suz, geçersiz tarih adetleri.
- **Bağımlılık:** E03-02, E03-05.
- **Canlı risk:** Yok (yalnız yeni tabloya yazar). Göç ayrı CLI; uygulama açılışında koşmaz.

### E03-05 · Göç öncesi salt okunur kütük veri profili — P1 · S · (M03-D01)
- **Canlı durum: YOK.** Benzeri: `migration/stok_raporu.py` (raporlayıcı, yazmaz).
- **Yaklaşım:** `migration/kutuk_profil.py`: kaynak Excel + eski DB dökümü üzerinde yalnız okuma yapar, xlsx/konsol rapor üretir: tip/marka dağılımı, seri no'suz, `seri_anahtari` ile mükerrer grup, lokasyonsuz, `DeliveryDateText` desen dağılımı (Excel gün sayısı / `GG.AA.YYYY` / geçersiz), `SecurityDeviceId`'si boş PB kalemleri, sözleşme–kütük müşteri adı eşleşme oranı, `accounts` ile otomatik eşleşme oranı. Sonuç `analiz/` altına tarihli dosya olarak yazılır, E03-10/E03-13 kabul rakamları güncellenir.
- **Kabul:** (1) Script hiçbir tabloya yazmaz (DB kullanıcı rolü salt okunur / test DB'de satır sayıları önce-sonra aynı). (2) Çıktıdaki sayılar tasarım tablosuyla (1.324 / 96 / 38-96 / 299 / 1.137) karşılaştırılır. (3) PB kalemlerinde cihaz kimliği boş olanların adedi raporlanır.
- **Bağımlılık:** —
- **Canlı risk:** Yok.

### E03-06 · Ekipman detay kartı ve birleşik geçmiş — P1 · M · (M03-02)
- **Canlı durum: YOK** (kütük için). Kalıp var: `api/devices.py:123-195` (kart + durum geçmişi + ek sayısı), `pages/IsEmirleriPage.tsx:185-280` (Drawer + Timeline).
- **Yaklaşım:** `GET /api/teknik-servis/ekipman/{id}` → `EkipmanKarti` (kimlik, müşteri/lokasyon/bölge/irtibat, tarihler, garanti rozeti, yaşam durumu + `sonraki_durumlar`, `serviste` (hesaplanan), aktif sözleşme kalemi, ek adedi, açık görev adedi). `GET /ekipman/{id}/gecmis` → tarih sıralı birleşik olay listesi `{tarih, tur, baslik, kaynak, kaynak_id, sure_dakika|null, sure_eksik, eslesme: "KIMLIK"|"METIN", maliyet?}`; kaynaklar: `service_orders` (equipment_id), PB işleri, `stock_movements` (`service_order_id` üzerinden parçalar), `audit_logs` (kütük değişiklikleri), RMA köprüsü (varsa). Süre `service_time_entries` toplamından (MOLA hariç); kayıt yoksa `sure_eksik=true`, ekranda "eksik". Metin eşleşmeli eski/göç işleri (`equipment_id` boş, `serial_key` eşit) `eslesme="METIN"` etiketiyle döner. Parça birim maliyeti yalnız `sees_cost(user)` true ise anahtar olarak eklenir (yoksa anahtar YOK; `api/deps.py:103-105`). Ön yüz: `EkipmanKarti` Drawer (`size={680}`), sekmeler: Özet · Geçmiş (Timeline) · Değişiklikler (E03-03) · Ekler (`EkYukleyici entity="service_equipment"`) · Görevler (`KayitGorevleri`). Kart, servis işi / sözleşme modülleri gelmeden de salt okunur çıkar (o bölümler boş, garanti "Bilinmiyor").
- **Kabul:** (1) İki uç tarih sıralı olayları döndürür. (2) Süre kaydı olmayan iş "eksik" görünür. (3) `maliyet.gor` olmayan kullanıcının yanıtında maliyet anahtarı hiç yoktur (liste, kart, geçmiş). (4) Metin eşleşmeli satır etiketlidir. (5) Başka birim/müşteri kapsamında 404.
- **Bağımlılık:** E03-02, E03-03; tam içerik için Servis İş Emri (`service_orders`, `service_time_entries`), yedek parça (`stock_movements.service_order_id`).
- **Canlı risk:** Yok. `stock_movements` yalnız okunur (kolon eklemesi parça modülünde, nullable).

### E03-07 · PB eşleşmesi ekipman kimliğine bağlı; sessiz seri no'suz kalem yok — P1 · M · (M03-09)
- **Canlı durum: YOK.** Canlıda PB/sözleşme yok; worker'da yalnız 4 görev var (`worker.py:120-125`).
- **Yaklaşım:** Sahiplik **Planlı Bakım / Bakım Sözleşmesi modülünde**. Bu modülün katkısı: (a) sözleşme kalemi doğrudan `equipment_id` taşır (müşteri adı metin eşitliği ve `ORDER BY id` sıralaması tamamen ortadan kalkar); (b) `services/teknik_servis/ekipman.py: pb_uygun_ekipmanlar(db, sozlesme_id, donem)` — aktif kalem + `is_active` + `lifecycle_status NOT IN ('DEVRE_DISI','HURDA')`; (c) `sozlesme_adet_farki(db, sozlesme_id)` — sözleşmedeki tip başına adet (ör. 9 X-RAY + 8 KAPI_DEDEKTORU) ile bağlı ekipman sayısı farkı. Worker (`GOREVLER`'e "pb-uretimi", idempotent `uq_so_pb_cihaz_donem`) yalnız (b)'den gelen ekipmanlar için PB üretir; adet eksikse PB uydurmaz, uyarı (`uyarilar` "Sözleşme adet farkı") üretir. Kullanıcı eksik ekipmanı kütüğe seri no'suz bile ekleyip bağlayabilir (açık karar, "Seri no eksik" etiketiyle). Önceki dönem eşlemesi göçte: eski `MaintenanceDeviceItems.SecurityDeviceId` → `source_ref` üzerinden `equipment_id` (E03-04 hazırlama adımı); eşleşmeyenler karantinaya.
- **Kabul:** (1) 17 ekipman bağlı sözleşmede yeni dönem için 17 PB, her biri doğru `equipment_id` ve seri ile oluşur; worker ikinci kez koşunca yeni PB oluşmaz. (2) Adet farkında seri no'suz/ekipmansız PB üretilmez, uyarı görünür. (3) Mevcut PB'ler ve numaraları değişmez. (4) DEVRE_DISI/HURDA ekipman hiçbir yoldan (worker, elle "dönemi başlat") PB almaz.
- **Bağımlılık:** E03-02, E03-09; Bakım Sözleşmesi + Planlı Bakım modülleri.
- **Canlı risk:** Yok (yeni tablolar). Worker görevi idempotent ve `uq_` korumalı.

### E03-08 · Garanti tarihleri/kaynağı ve sözleşme bağı ("bağlı cihaz" sayısı ayrı) — P2 · M · (M03-03)
- **Canlı durum: KISMEN.** Ürün kartında `warranty_months` (`models/catalog.py:97`, varsayılan 24) ve mobilite cihazında `warranty_end_date` (`models/device.py:143`) var; ekipman için yok.
- **Yaklaşım:** Kolonlar §1.1. Servis doğrulaması: bitiş < başlangıç → 400 (Pydantic/servis) + şemada `ck_svceq_garanti_aralik` (422 değil 400 dönmesi için servis önce kontrol eder). Hesaplanan rozet (saklanmaz): `garanti_durumu` = `GECERLI` (bitiş ≥ bugün, `Clock`), `BITTI`, `BILINMIYOR` (bitiş boş). Toplu garanti doldurma: `POST /ekipman/garanti/toplu-hesapla` (EkipmanYazici, önizleme + uygula iki adım, `?uygula=false` varsayılan): yalnız `warranty_end IS NULL` kayıtlara `başlangıç = install_date ?? delivery_date`, `bitiş = başlangıç + ürün.warranty_months` (ürün yoksa `servis.varsayilan_garanti_ay`), `warranty_source='HESAPLANDI'`; `BELGE` kaynaklı kayda dokunmaz; her kayıt için `audit` `garanti.toplu`. Sözleşme bağı: kartta aktif `maintenance_contract_items` kalemi; sözleşme listesinde **"Bağlı ekipman"** sayısı ayrı kolon (aktif kalem adedi), sözleşmenin plan/adet alanı değişmez. Kütük listesinde çoklu seçim → "Sözleşmeye bağla" (Bakım Sözleşmesi ucunu çağırır, `bakim.yaz`).
- **Kabul:** (1) Bitişi geçmiş ekipman "Garanti Bitti", boş "Bilinmiyor" görünür. (2) bitiş<başlangıç 400. (3) Sözleşme listesinde "Bağlı ekipman" ayrı görünür; plan adedi değişmez. (4) Toplu hesaplama önizlemesi uygulama ile aynı satır sayısını verir ve `BELGE` kayıtları değişmez.
- **Bağımlılık:** E03-02, E03-04; Bakım Sözleşmesi modülü; iş emri rozeti için Servis İş Emri.
- **Canlı risk:** Yok. `products.warranty_months` yalnız okunur.

### E03-09 · Yaşam döngüsü durumu; "Serviste" hesaplanır — P2 · M · (M03-04)
- **Canlı durum: YOK** (ekipman için). Kalıp: `CIHAZ` makinesi + `services/devices.py:46-66` `durum_degistir`.
- **Yaklaşım:** §1.3 makinesi. `ekipman.durum_degistir(db, ekipman, hedef, *, gerekce, tarih, clock, user_id)` → `SERVIS_EKIPMANI.dogrula`, gerekçe zorunlu (boşsa `EkipmanHatasi` 400), `KURULU`'ya geçişte `install_date` boşsa istekteki tarih yazılır; `audit` `durum.degistir`. `DEVRE_DISI/HURDA`'ya geçişte açık servis işleri SİLİNMEZ; yanıt `uyarilar: ["Açık 2 servis işi var: SI-2026-000123 ..."]` içerir. Uçlar: `POST /ekipman/{id}/durum`, `POST /ekipman/toplu-durum` (en çok 200 kimlik, tek gerekçe, her kayıt ayrı audit, kapsam dışı kimlik varsa tümü 404 ve hiçbiri değişmez). "Serviste" rozeti: `EXISTS(service_orders WHERE equipment_id=… AND tur='ARIZA' AND status NOT IN terminal)`. Taşıma ayrı özellik değil: müşteri/lokasyon PATCH + audit. District eklenmez (adres modülü). PB dışlaması E03-07 (b).
- **Kabul:** (1) Gerekçesiz durum değişikliği 400, kayıt değişmez; gerekçeli değişiklik geçmişte görünür. (2) İzinsiz geçiş (ör. KURULU→HURDA) 409. (3) DEVRE_DISI/HURDA ekipman yeni PB üretiminde hiçbir yoldan yer almaz; açık işleri silinmez ve uyarı döner. (4) Meta-test (`tests/unit/test_statemachine.py`) yeni makineyi otomatik sınar ve yeşil.
- **Bağımlılık:** E03-02, E03-03.
- **Canlı risk:** Düşük: `statemachine.py`'ye yalnız yeni makine eklenir; mevcut makinelere dokunulmaz.

### E03-10 · Teslim tarihi metninden DATE, tip tekleştirme, `model_key` (alias tablosu yok) — P2 · M · (M03-10)
- **Canlı durum: KISMEN.** `services/normalize.py` Türkçe katlama (`tr_normkey` `:119-133`), dolgu temizleme (`clean_cell` `:141-149`) var; Excel gün sayısı → tarih ve model anahtarı yok.
- **Yaklaşım:** `normalize.py`'ye EKLEME: `excel_gun_tarihi(ham) -> date | None` (1900 sistemi, 1899-12-30 tabanı; `44083 → 2020-09-09`; `GG.AA.YYYY` ve ISO da çözülür; `00.00.2015` gibi geçersizler `None` + karantina uyarısı; uydurma yok), `model_anahtari(ham)` (tr_normkey + büyük harf + boşluk ve `-` silme: `SC-5030 A` ve `SC 5030 A` → `SC5030A`). Dönüşüm göçün hazırlama adımında (E03-04) uygulanır, `delivery_date_raw` korunur; yükleme idempotent olduğundan tekrar koşu aynı sonucu verir. Tip: kaynak `Kapı Dedektörü`/`Kapı Tipi Metal Dedektörü` → `KAPI_DEDEKTORU`; ekranda tip sabit listeden seçilir. Form kaydında `model_key` ORM olayıyla dolar. Filtre `model_key` üzerinden.
- **Kabul:** (1) `'44083'` → `delivery_date=2020-09-09`, `delivery_date_raw='44083'`. (2) Göç iki kez koşunca tarih/tip değerleri değişmez. (3) `SC 5030 A` filtresi `SC-5030 A` kaydını da getirir. (4) Unit test: `excel_gun_tarihi`, `model_anahtari` sınır değerleri.
- **Bağımlılık:** E03-04, E03-05.
- **Canlı risk:** Düşük: `normalize.py` yalnız yeni fonksiyon alır; mevcut fonksiyonların imzası/davranışı değişmez.

### E03-11 · Kütük ekranı: açılınca yükleme, sunucu filtreleri, sayfalama, tıklanabilir KPI kutuları, Excel — P2 · M · (M03-12; kullanıcı doğruladığı KPI/Excel/toplu işlem)
- **Canlı durum: KISMEN.** Altyapı var: `sayfala()` + `X-Toplam-Kayit` (`api/deps.py:142-190`), `api.getSayfa` (`frontend/src/api/client.ts:63-81`), `export.satirlari_xlsx_async` (`services/export.py:45`), liste kalıbı `pages/IsEmirleriPage.tsx:66-166`. Ekran ve uç yok.
- **Yaklaşım:** `GET /api/teknik-servis/ekipman` (filtreler: `q` [seri/müşteri/lokasyon/model, `serial_key` ve `title_key` üzerinde], `birim`, `tip`, `marka`, `model`, `durum`, `hesap_id`, `sozlesme_id`, `garanti`, `seri_eksik`, `lokasyonsuz`, `sozlesmesiz`, `pasifler_dahil`, `kpi`; `limit le=200`, `offset`). Filtre kurulumu tek fonksiyonda (`ekipman.liste_sorgusu(user, filtre)`); liste, özet ve Excel AYNI sorguyu kullanır. `GET /ekipman/ozet` → KPI sayıları (Toplam, X-Ray, Kapı Dedektörü, Seri No Mevcut, Seri No Eksik, Garanti Bilinmiyor) — her biri bir `kpi` filtre koduna karşılık gelir. `GET /ekipman.xlsx` (EkipmanAktarici): ekran filtresiyle aynı satırlar, üst sınır 20.000 (aşılırsa 400 "filtreyi daraltın"); seri no hücreleri `str` yazılır (metin hücre; `_formulu_metne_cevir` enjeksiyonu keser); maliyet kolonu yok; `audit.log("service_equipment","disaaktar", new_value={filtre, satir})`. Ön yüz `pages/ServisEkipmanPage.tsx`, rota `/servis-ekipman` (`main.tsx` AppLayout altı), menü `{key:"/servis-ekipman", label:"Ekipman Kütüğü", icon:<SafetyOutlined/>, izin:"ekipman.gor"}`; veri yalnız sayfa açılınca `useQuery(["servis-ekipman", filtre, sayfa])` ile gelir; KPI kutuları `Statistic` kartları, tıklanınca `kpi` filtresini set edip sayfa 1'e döner; satır tıklama → E03-06 Drawer; `rowSelection` ile toplu işlemler: "Durum değiştir" (E03-09), "Sözleşmeye bağla" (E03-08), "Servis işi aç" (seçili her ekipman için Servis İş Emri modülünün toplu açma ucu; `servis.yaz`), "Excel" (seçim yoksa filtre, varsa seçili kimlikler). Mobil 375 px'te kolonlar daraltılır.
- **Kabul:** (1) Girişte (`/api/auth/me`, panel) kütük ucu çağrılmaz. (2) 1.000'den fazla satır sayfalanarak gezilebilir, `X-Toplam-Kayit` doğru. (3) Excel satır sayısı aynı filtreyle `X-Toplam-Kayit`'e eşittir; seri no `'00123'` Excel'de metin. (4) `rapor.disaaktar` olmayan teknisyene Excel 403. (5) Her KPI kutusundaki sayı, tıklanınca açılan listenin `X-Toplam-Kayit` değerine eşittir.
- **Bağımlılık:** E03-01, E03-02.
- **Canlı risk:** Yok. Menüye yeni kalem; mevcut "İş Emirleri" ve "Cihazlar" kalemleri değişmez (ad karışıklığını önlemek için "Ekipman Kütüğü" adı).

### E03-12 · Tüm kütük eşleşmelerinde tek normalize seri fonksiyonu — P2 · S · (M03-D02)
- **Canlı durum: YOK.** Canlıda seri arama `ilike` (`api/devices.py:66-68`) ve kart birebir eşitlik (`:126`) kullanıyor; ekipman eşleşmesi yok.
- **Yaklaşım:** `normalize.seri_anahtari` tek kaynak; `ekipman.seri_ile_bul(db, ham_seri, *, account_id=None) -> Eslesme(TEK|BELIRSIZ|YOK, ekipman_id)`: `serial_key` eşitliği, aktif kayıtlar; tek eşleşmede müşteri adı şartı aranmaz, birden fazlada öneri verilmez. Kullanıcılar: servis işi planlamasında lokasyon önerisi (`GET /api/teknik-servis/ekipman/oneri?seri=`), tekrar arıza hesabı (E03-15), saha farkı otomatik bağlama (E03-14), göç eşleştirmesi (E03-04).
- **Kabul:** (1) `' abc-001 '` seriyle `ABC-001` ekipmanının lokasyonu önerilir. (2) Aynı anahtar iki aktif kayıtta → `BELIRSIZ`, öneri yok. (3) `00123` ile `123`, `AB-1` ile `AB1` eşleşmez (sıfır ve ayraç korunur).
- **Bağımlılık:** E03-02.
- **Canlı risk:** Yok.

### E03-13 · Veri kalitesi ekranı ve çakışmasız birleştirme — P2 · M · (M03-11)
- **Canlı durum: KISMEN.** Benzer desen: mobilite cihazında "kimliği geçici" listesi (`api/devices.py:74-75`), hesaplarda mükerrer aday (`services/accounts.py:84-106`). Ekipman için yok.
- **Yaklaşım:** `GET /ekipman/veri-kalitesi` → sayılar: mükerrer grup (`GROUP BY equipment_type, brand, serial_key HAVING count(*)>1` aktif kayıtlarda), seri no'suz, lokasyonsuz (`address_id IS NULL`), hesaba bağlanmamış (`account_id IS NULL`), sözleşmesiz KURULU, durumu BILINMIYOR, sahadan gelen farklar (E03-14). Her sayı liste ucuna `kpi`/kalite filtresi olarak bağlanır (tıklanabilir). `GET /ekipman/mukerrer-gruplar` (sayfalı). `POST /ekipman/{id}/birlestir {ana_id, gerekce}` (EkipmanYazici): ikincil kayıt `is_active=false`, `merged_into_id=ana_id`; ikincile bağlı açık sözleşme kalemleri ve açık servis işleri ana kayda yalnız aynı sözleşme/dönemde ana kaydın kalemi YOKSA taşınır, varsa `EkipmanHatasi` → 409 ve hiçbir şey değişmez; PB numaraları değişmez/silinmez; ek dosyalar ve geçmiş ikincide kalır, kartta "Birleştirildi → #ana" bağı. "Farklı cihaz" işaretlemesi `duplicate_ack_reason` PATCH'i. Tümü audit. Ön yüz: Ekipman Kütüğü sayfasında "Veri Kalitesi" sekmesi (KPI kartları + listeler + birleştir penceresi). Uyarı paneline (`services/uyarilar.py`) `if user.has("ekipman.yaz")` bloğu: "Seri no'su eksik ekipman", "Mükerrer seri no grubu" (birim kapsamlı sayı).
- **Kabul:** (1) Mükerrer grup sayısı DB `GROUP BY` sonucuyla aynı. (2) Aynı sözleşme döneminde iki kaydın da kalemi varken birleştirme 409, hiçbir satır değişmez. (3) Birleştirmede PB numaraları değişmez. (4) Her işlem geçmişe yazılır. (5) Uyarı sayısı yalnız kullanıcının birimini sayar.
- **Bağımlılık:** E03-02, E03-03, E03-05; taşıma kısmı Bakım Sözleşmesi + Servis İş Emri.
- **Canlı risk:** Düşük: `uyarilar.topla()`'ya yeni blok eklenir; mevcut bloklar ve `is-uyarilari` worker görevi değişmez.

### E03-14 · Sahada düzeltilen seri no/bölge kütüğe döner (otomatik tek eşleşme + fark listesi) — P2 · M · (M03-08)
- **Canlı durum: YOK.**
- **Yaklaşım:** Ayrı öneri tablosu AÇILMAZ. Servis/PB kapanışında (`service_results`) teknisyen `saha_seri_no`, `saha_bolge` girer. Kapanış servisi: iş `equipment_id` boşsa `seri_ile_bul(..., account_id=iş.müşteri)` TEK dönerse işi ekipmana bağlar (audit `saha.otomatik_bagla`); kütükle fark varsa (`seri_anahtari(saha) != serial_key` veya bölge farkı) `kutuk_fark_durumu='ACIK'`. Uçlar: `GET /ekipman/saha-farklari` (sayfalı; işin birimi/müşterisi kapsamı), `POST /ekipman/saha-farklari/{sonuc_id}/uygula` (EkipmanYazici: kütükteki seri/bölge güncellenir, audit `saha.uygula` new_value = `{teknisyen_id, onaylayan_id, is_no}`; hedef seri başka aktif kayıtta varsa 409 — çakışma otomatik uygulanmaz) ve `/yoksay` (`gerekce`, `YOK_SAYILDI`). Liste E03-13 ekranında sekme.
- **Kabul:** (1) Seri no'su boş ekipmanın PB'si `ABC-001` ile kapanınca kütük değişmez, fark listesinde görünür. (2) "Kütüğe uygula" sonrası seri `ABC-001`, geçmişte teknisyen ve onaylayan görünür. (3) `ABC-001` başka aktif kayıtta varsa uygula 409. (4) Yok say sonrası listeden düşer, gerekçe geçmişte.
- **Bağımlılık:** E03-02, E03-03, E03-12, E03-13; Servis İş Emri (`service_results`).
- **Canlı risk:** Yok.

### E03-15 · Analitik KPI'lar (tıklanabilir, sunucuda): 12 aydan eski bakımlı sözleşmeli ekipman, 90 günde ≥2 PB dışı arıza — P3 · M · (M03-05)
- **Canlı durum: YOK.** Benzer: `services/reports.py` `ariza-orani` (`api/reports.py:186`), mobilite cihazına özgü.
- **Yaklaşım:** `services/teknik_servis/ekipman.py: kpi_bakim_gecikmis(db, clock, user)` (aktif sözleşme kalemi olan, son TAMAMLANDI PB'si `servis.kpi_bakim_gecikme_ay`'dan eski veya hiç olmayan KURULU ekipman), `kpi_tekrar_ariza(...)` (son `servis.tekrar_ariza_gun` günde `tur<>'PB'` servis işi sayısı ≥ `servis.tekrar_ariza_esik`; yalnız `equipment_id` ile; seri no'suz ekipman sayılmaz). İkisi `GET /ekipman/ozet` içinde sayı, `GET /ekipman?kpi=bakim_gecikmis|tekrar_ariza` ile liste (aynı sorgu → sayı = satır). Rapor sekmesinde (`RaporlarPage`) Excel de aynı ucu kullanır. Garanti-60-gün ve model bazlı oran ertelenir (veri dolunca, `servis.garanti_uyari_gun` hazır).
- **Kabul:** (1) Her KPI sayısı tıklanınca açılan listenin `X-Toplam-Kayit` değerine eşit. (2) Seri no'suz ekipman tekrar arıza listesine girmez. (3) Eşikler ayardan okunur; ayar değişince sayı değişir (test FakeClock ile).
- **Bağımlılık:** E03-06, E03-08, E03-09, E03-11; Servis İş Emri + Planlı Bakım.
- **Canlı risk:** Yok (mevcut rapor sorguları değişmez).

### E03-16 · Ekler, görev panosu, genel arama ve KVKK entegrasyonu — P2 · S · (M03-02/M03-06'dan türetilmiş mimari gereklilik)
- **Canlı durum: KISMEN.** Ek altyapısı var ama `service_equipment` sahibi tanımlı değil (`models/attachment.py:31-42`, `api/attachments.py:41-52`) ve `_kapsam` yalnız `accounts` için çalışıyor (`api/attachments.py:91-114`). Görev bağlantı tipleri `services/gorevler.py:47-57`.
- **Yaklaşım:** `EK_SAHIPLERI += ("service_equipment",)`; `EK_TURLERI += ("CIHAZ_ETIKETI","KURULUM_TUTANAGI","GARANTI_BELGESI")`; `SAHIP_IZNI["service_equipment"] = ("ekipman.gor","ekipman.yaz")`; `_kapsam`'a `service_equipment` dalı (müşteri kapsamı + `birim_disinda_mi` → 404; `accounts` dalı aynen kalır). `KAYIT_TIPLERI += KayitTipi("ekipman","Servis Ekipmanı", ServiceEquipment, ("serial_no","model"), "/servis-ekipman?id={id}")`. `api/search.py` genel aramaya ekipman sonucu (yalnız `ekipman.gor` + kapsam). `services/kvkk.py` anonimleştirmesine `service_equipment.contact_name_raw` ve ilgili `audit_logs` (`is_personal_data`) eklenir.
- **Kabul:** (1) Başka birimin ekipmanının eki listelenemez/indirilemez/silinemez (404). (2) Satış temsilcisinin `accounts` ek kapsamı testi (`test_kapsam_guvenligi.py`) yeşil kalır. (3) Görev kartı ekipmana bağlanır ve bağlantı doğru rotaya gider. (4) KVKK anonimleştirmesi irtibat adını temizler.
- **Bağımlılık:** E03-01, E03-02.
- **Canlı risk:** Orta-düşük: `api/attachments.py:_kapsam` ortak koddur; yalnız yeni `if entity == "service_equipment"` dalı eklenir, `accounts` dalı değiştirilmez; mevcut ek testleri regresyon olarak koşar.

---

## 3. Test planı (özet)

| Dosya | İçerik |
|---|---|
| `tests/unit/test_normalize_seri.py` | `seri_anahtari`, `model_anahtari`, `excel_gun_tarihi` (44083, 00.00.2015, ISO, boş). |
| `tests/unit/test_statemachine.py` | Değişmez; `MAKINELER`'deki `servis_ekipmani` otomatik sınanır. |
| `tests/unit/test_permissions.py` | Değişmez; yeni izinlerin role atanması ve `maliyet.gor` kümesi otomatik denetlenir. |
| `tests/integration/test_servis_ekipman.py` | 403/200/201 matrisi; metin seri; mükerrer 409 + gerekçe; version 409; pasif/aktif; durum geçişleri; toplu durum atomikliği; Excel satır sayısı ve metin hücre; KPI = liste sayısı. |
| `tests/integration/test_servis_ekipman_kapsam.py` | İki birim, iki şef: liste, GET 404, PATCH 404 + `db.refresh` değişmemiş, birim taşıma 403, ek 404, uyarı sayısı, Excel kapsamı. |
| `tests/integration/test_servis_ekipman_gecmis.py` | Değişiklik geçmişi alanları; rollback'te audit yok; maliyet anahtarı yok (`maliyet.gor` olmayan). |
| `tests/integration/test_servis_ekipman_kalite.py` | Mükerrer grup = GROUP BY; birleştirme 409/başarı; saha farkı uygula/yok say/çakışma. |
| `tests/migration/test_kutuk_gocu.py` | Göç iki kez → satır sayısı aynı, elle düzeltme korunur; karantina sayıları. |
| Mevcut | `test_migration_zinciri` (head→base→head, tek head), `test_altin_kayit` (932 iş / 552.825,00 TL) yeşil. |

Yeni tablo `service_equipment` `accounts`'a FK ile bağlı olsa da `RESTRICT` olduğu ve `TRUNCATE ... CASCADE` zincirine `accounts` üzerinden gireceği için ayrıca `_TRUNCATE` listesine eklenir (güvenli taraf).

## 4. Uygulama sırası

1. (RBAC + birim adımı tamamlandıktan sonra) E03-01 → E03-02 + E03-03 (aynı sürüm) → E03-16.
2. E03-05 (profil) → E03-10 + E03-04 (göç) → E03-06 (salt okunur kart, servis işi verisi geldikçe dolar) → E03-11.
3. Bakım Sözleşmesi / Planlı Bakım ile birlikte: E03-08, E03-09, E03-07.
4. Servis İş Emri kapanışı gelince: E03-12, E03-14, E03-13.
5. Veri dolunca: E03-15.

Her adım sonunda `make test`, `ruff`, `npm run build`, `oxlint`.

## 5. Kararlar (kullanıcıya soru sorulmadı)

1. **Kütük tablosu `service_equipment`, `devices` değil.** Gerekçe: `uq_devices_seri` global tekil, kütükte 38 mükerrer seri grubu ve 96 seri no'suz satır var; `devices` stok yaşam döngüsü ve stok değeri raporu taşıyor.
2. **Tablo birim-genel** (`birim` kolonu); kütük göçü GUVENLIK yazar. Haberleşme/POC kurulu ekipmanı aynı tabloyu kullanır; ikinci kütük tablosu açılmaz.
3. **Yeni sistem kütüğün tek doğru kaynağıdır;** Excel'den sürekli içe aktarma profili yazılmaz, yalnız tek seferlik idempotent göç (eski soru 1).
4. **İzin adı `ekipman.gor/ekipman.yaz`** (`cihaz.*` mobilite cihazına ait, karıştırılmaz); Excel için `rapor.disaaktar` yeniden kullanılır (eski karar: yeni export izni yok). Hurdaya ayırma ayrı izin değil, `ekipman.yaz` + zorunlu gerekçe (denetim kararı).
5. **`ekipman.yaz` yalnız SERVIS_YONETICI ve SERVIS_SEF'te** (eski soru 3; Müdür/Şef). Mevcut roller kütüğü görmez (eski sistemdeki Muhasebe/Depo sızıntısı tekrarlanmaz).
6. **Değişiklik geçmişi `audit_logs`**; ayrı geçmiş tablosu yok. Kullanıcı adı kopyası tutulmaz, çünkü kullanıcılar silinmiyor (`yonetim.py:75`).
7. **Sözleşme bağı ekipmanda FK değil, tarihli `maintenance_contract_items.equipment_id`.** Bir cihaz zamanla sözleşme değiştirir; tek FK geçmişi kaybeder.
8. **Sözleşme adedi bağlı ekipmandan fazlaysa PB uydurulmaz;** uyarı üretilir, kullanıcı eksik ekipmanı (seri no'suz da olabilir) açıkça ekler. Bu, "seri no'suz kalem sessizce üretilmez" kuralının canlıdaki karşılığı.
9. **Müşteri eşleşmesi:** göçte `title_key` birebir → bağla; trigram adayı → karantina/elle karar; bulunamayan → `account_id NULL` + `customer_name_raw`, veri kalitesi listesinde. Yeni müşteri tablosu açılmaz (eski soru 8).
10. **Garanti kuralı:** başlangıç = kurulum tarihi, yoksa teslim tarihi; süre = ürün kartındaki `warranty_months`, ürün yoksa ayar `servis.varsayilan_garanti_ay` (24). Toplu hesaplama önizlemeli ve `HESAPLANDI` kaynağıyla; belgeli kayda dokunmaz (eski soru 2).
11. **"Diğer Güvenlik Cihazı" (99 kayıt)** `DIGER_GUVENLIK` tipine girer; ayrı checklist bu modülde açılmaz (Planlı Bakım formu kapsamı).
12. **Mükerrer temizliği** veri kalitesi ekranından SERVIS_SEF yapar; otomatik birleştirme yok (eski soru 5).
13. **Kiralama envanteri bu kütükte değil;** kiralama modülü `rental_items` üzerinden kendi seri kaydını tutar (eski soru 7), ileride `equipment_id` köprüsü nullable eklenebilir.
14. **`is_active` (kayıt geçerliliği) ile `lifecycle_status` (fiziksel durum) ayrı;** `is_deleted` yalnız yönetimsel temizlik için, ekranda "pasif" `is_active=false` demektir (`accounts` emsali).
15. **Mükerrer kontrolü uygulamada + advisory lock;** kısmi UNIQUE indeks kullanılmaz çünkü göçteki mevcut mükerrerler aktif kalmak zorunda.
16. **Excel üst sınırı 20.000 satır** (`MAKS_SATIR` emsali `services/imports/cekirdek.py:36`).
17. **"Serviste" rozeti saklanmaz,** açık ARIZA servis işinden hesaplanır (bayatlamaz).
18. **Ekran adı "Ekipman Kütüğü"** (rota `/servis-ekipman`): mevcut "Cihazlar" (mobilite) menüsüyle karışmasın.
19. **Profil scripti (E03-05)** SQL Server'a canlı bağlanmak yerine en güncel yedek/döküm ve Excel üzerinde çalışır (eski soru 9); erişim sağlanırsa aynı script bağlantı dizesiyle koşar.

## 6. Gözlemler (değiştirilmedi)

- `api/devices.py:123-138` cihaz kartı ucu `kapsam_disinda_mi` kontrolü yapmıyor: `SATIS` (KENDI_MUSTERILERI) kullanıcı IMEI/seri bilirse başka müşterinin cihaz kartını görebilir (liste ucu `:63` kapsamlı). Güvenlik sıkılaştırma aşamasına not.
- `api/reports.py:41-45` `_maliyet_gizle` alanı `None` yapıyor, mimari kural "alan hiç yer almaz" diyor. Yeni ekipman uçları anahtarı tamamen çıkarır.
- Önceki gözlemler (`services/reports.py:81` "DEGISTI"; count/max+1 numaralandırma) aynen geçerli; ekipmanda belge numarası yok, servis işi numarası sequence ile (Servis İş Emri modülü).
