# E01 — Servis İş Emirleri ve İş Havuzu (İş Takibi): Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21 · Hedef: Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdi: `analiz/02_moduller/_ozet/01_is_emirleri.json` (denetçi onaylı 23 madde), `01_is_emirleri_tasarim.md`, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`
> Bu belge YALNIZ tasarımdır. Kaynak koda dokunulmadı. Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köklerine göredir ve 2026-10-21'de kod okunarak doğrulandı.
> Madde kimlikleri `E01-NN`; kaynak madde kimlikleri `M01-xx` olarak yazıldı.

---

## 0. Özet

- Canlı ERP'de teknik servis iş emri kavramı **hiç yok**. Mevcut `work_orders` mobilite montaj ziyaretidir, kayıt doğrudan `TAMAMLANDI` olarak doğar (`services/workorders.py:274`) ve onay alanı doğrudan atanır (`api/workorders.py:366`). Bu zincire **dokunulmaz**.
- Servis işleri için `service_orders` merkezli yeni bir alan kurulur: `models/teknik_servis.py`, `services/teknik_servis/`, `api/teknik_servis.py` (`/api/teknik-servis`), `pages/Servis*.tsx`.
- Doğrudan yeniden kullanılanlar: müşteri = `Account(is_musteri)`, lokasyon = `addresses`, irtibat = `contacts`, ek dosya = `attachments`, PDF = `services/pdf.py`, Excel = `services/export.py`, denetim izi = `services/audit.py`, görev panosu = `services/gorevler.py`, uyarılar = `services/uyarilar.py`, ayarlar = `services/settings.py`, durum makinesi = `services/statemachine.py`, sayfalama = `api/deps.py:sayfala`, kapsam = `services/accounts.py:kapsam_musteri / kapsam_disinda_mi`, maskeleme = `services/kvkk.py:maskele`.
- 23 kaynak maddenin 5'i .NET'e özgü (`M01-12, M01-13, M01-D01, M01-D02, M01-15`). Bunlar ayrı madde olarak taşınmadı, ama özleri ilgili maddelerin kabul kriterlerine eklendi (bkz. §6 izlenebilirlik).
- Kullanıcının eski sistemde bizzat doğruladığı dört işlev korunuyor:
  - Tıklanabilir KPI kutuları: E01-14.
  - Toplu atama: E01-12. Toplu planlama: E01-12 ve E02'ye köprü.
  - Excel dışa aktarım: E01-15.
  - Cihaz başına PB iş emri: E01-17.

---

## 1. Canlı karşılık taraması (kod okunarak)

| Konu | Canlıda ne var | Kanıt |
|---|---|---|
| Servis iş emri tablosu | YOK. `work_orders` yalnız montaj/söküm ziyareti; `settlement_period` zorunlu, kalemler hak edişe gider | `models/workorder.py:77-200`, `api/workorders.py:221-266` |
| Durum makinesi | Altyapı VAR (`StateMachine`, `MAKINELER`); servis iş emri makinesi YOK | `services/statemachine.py:27-83, 189-196` |
| Olay geçmişi | Yalnız genel denetim izi (`audit_logs`, serbest JSON) | `services/audit.py:26-92` |
| Bekleme (hold) | YOK | — |
| Ek dosya | VAR, polimorfik. Ancak `service_orders` sahibi yok, `_kapsam` yalnız `accounts` için çalışıyor, magic-byte denetimi yok, silme kalıcı | `models/attachment.py:31-62`, `api/attachments.py:41-52, 91-114, 283-320`, `services/storage.py:28-38, 70-83, 88` |
| PDF | VAR (WeasyPrint + Jinja2, Türkçe karakter sorunsuz) | `services/pdf.py:53-68`, `services/belgeler.py:119, 147-200` |
| Excel | VAR (tek sayfa, formül enjeksiyonu korumalı) | `services/export.py:45-61`, `api/reports.py:33-38` |
| KPI paneli | VAR, ama mobilite yönetim paneli; kutular tıklanabilir DEĞİL (`onClick`/`navigate` yok) | `pages/PanelPage.tsx:76-200`, `services/reports.py:43` |
| Liste + sayfalama | VAR (`sayfala`, `X-Toplam-Kayit`) | `api/deps.py:142-190` |
| Kapsam | Yalnız `KENDI_MUSTERILERI`; birim kavramı YOK | `permissions.py:80-82`, `services/accounts.py:29-61`, `api/deps.py:108-118` |
| Rol kapsamı doğrulama | `api/users.py` kapsamı `(SCOPE_ALL, SCOPE_OWN_CUSTOMERS)` diye SABİT kontrol ediyor; yeni kapsam eklenince burası da değişmeli | `api/users.py:73, 181, 225` |
| Kişi = personel | Ayrı personel tablosu YOK; kişi = `users` | `models/user.py:11-81` |
| Belge numarası | `count()+1` / `max(id)+1`, eşzamanlılıkta çakışır | `services/workorders.py:102-103`, `services/rma.py:70-72` |
| Seri no normalleştirme | YOK (IMEI/MSISDN/ICCID/plaka var) | `services/normalize.py:22-242` |
| Görev panosu bağlantısı | VAR, tip kataloğu tek yerde | `services/gorevler.py:47-57` |
| Uyarı merkezi | VAR, izne tabi, hesaplanır | `services/uyarilar.py:47-192` |
| Ayarlar | VAR (`DEFAULTS` beyaz listesi) | `services/settings.py:33-93` |
| Worker | VAR, `GOREVLER` | `worker.py:120-125` |
| KVKK anonimleştirme | `accounts, contacts, vehicles` | `services/kvkk.py:30, 217-262, 398` |
| Router kaydı | Elle | `main.py:182-209` |
| Menü / rota | Elle | `components/AppLayout.tsx:52-100`, `main.tsx:67-94` |
| Test altyapısı | PG17, `_TRUNCATE`, `kullanici_ac` | `tests/conftest.py:41, 122, 150-219` |

Sonuç: Bu modülün **iş kuralı katmanı tamamen YOK**. Buna karşılık altyapının neredeyse tamamı VAR ve yeniden kullanılır. Maddelerin çoğu "YOK", altyapıya yaslananlar "KISMEN" işaretlendi.

---

## 2. Veri modeli (yeni tablolar ve genişletmeler)

Tüm ana tablolar `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin` alır (`models/mixins.py`). V1.20.1'den göç edilecek tablolar ayrıca `SourceMixin` ve `uq_<tablo>_kaynak` alır. Durum ve enum alanları `String` olur; yanında Türkçe tuple ve adlı `CheckConstraint` bulunur. Dosya: `backend/app/models/teknik_servis.py`. Model `models/__init__.py`'ye import ve `__all__` ile eklenir.

### 2.1 `user_units` (E01-01; birim üyeliği, RBAC altyapısı)
| Kolon | Tip | Not |
|---|---|---|
| user_id | BigInteger FK users CASCADE | PK parçası |
| birim | String(20) | PK parçası; `ck_user_units_birim` → `BIRIMLER` |
| is_primary | Boolean default false | `uq_user_units_birincil` kısmi tekil (user_id) WHERE is_primary |
| created_at / created_by | | `TimestampMixin` + `ActorMixin` |

### 2.2 `service_orders` (E01-02)
| Kolon | Tip | Kısıt / Not |
|---|---|---|
| so_no | String(24) NOT NULL | `uq_so_no`; `service_order_no_seq` SEQUENCE'ten, `SRV-YYYYAA-NNNNNN` (PB: `PB-YYYYAA-NNNNNN`) |
| birim | String(20) | `ck_so_birim` IN (GUVENLIK, HABERLESME, POC, MOBILITE, ARAC_TAKIP) |
| tur | String(30) | `ck_so_tur` → `SERVIS_TURLERI` (ARIZA, PLANSIZ_BAKIM, PB, KURULUM, DEVREYE_ALMA, KESIF, ATOLYE_ONARIM, DESTEK, DIGER) |
| kategori | String(20) | `ck_so_kategori` IN (GUNLUK_SERVIS, PLANLI_BAKIM, ATOLYE, KURULUM, DIGER); `tur_kategorisi(tur)` ile doldurulur |
| oncelik | String(10) default NORMAL | `ck_so_oncelik` IN (NORMAL, YUKSEK, KRITIK) |
| status | String(20) default MUSTERI_TALEBI | `ck_so_durum` → `SERVIS_DURUMLARI` |
| customer_id | FK accounts RESTRICT NOT NULL | müşteri = hesap |
| address_id | FK addresses SET NULL | servis lokasyonu |
| contact_id | FK contacts SET NULL | irtibat kaydı varsa |
| iletisim_ad / iletisim_telefon | String(120)/String(20) | kişisel veri; KVKK kapsamı |
| talep_kanali | String(20) | `ck_so_kanal` IN (TELEFON, WHATSAPP, EPOSTA, SAHADA_BILDIRILDI, BAKIM_OTOMATIK, DIGER) |
| reported_at | timestamptz NULL | müşterinin bildirdiği an; göçte NULL kalır (uydurma tarih yok) |
| proje / sistem | String(120) | serbest |
| konu | String(200) NOT NULL | |
| aciklama | Text | |
| completed_at / completed_by | | TAMAMLANDI anında |
| closed_at / closed_by | | KAPATILDI anında |
| cancelled_at / cancelled_by / cancel_reason | | `ck_so_iptal_gerekce`: status='IPTAL' ise cancel_reason NOT NULL |
| reopen_count | Integer default 0 | |
| iliskili_is_id / iliski_turu | FK service_orders SET NULL / String(20) | `ck_so_iliski` (ikisi birlikte dolu ya da boş), `ck_so_kendine_bagli` (id <> iliskili_is_id), tür IN (MUKERRER, TEKRAR_ARIZA, DEVAM) |
| work_order_id | FK work_orders SET NULL | mobilite köprüsü; yalnız okunur. Servis kodu `work_orders`'a YAZMAZ |
| rma_case_id | FK rma_cases SET NULL | atölye köprüsü (E05) |
| İndeksler | | `ix_so_durum_olusma(status, created_at)`, `ix_so_kapanis(closed_at)`, `ix_so_birim_durum(birim, status)`, `ix_so_musteri(customer_id)` |

Sonraki modüllerin **nullable** kolonla ekleyeceği alanlar (burada YER AYRILIR, kolon açılmaz):
- E03: `equipment_id`.
- E04: `contract_item_id`, `bakim_donemi` ve `uq_so_pb_cihaz_donem`.
- E10: `sla_due_at`.
- Teklif tarafında `quotes.service_order_id` (E07).
- Parça tarafında `stock_movements.service_order_id` (E11).

### 2.3 `service_order_serials` (E01-02, E01-10, E01-13)
| Kolon | Not |
|---|---|
| service_order_id | FK service_orders RESTRICT |
| seri_no | String(80); girildiği gibi (yalnız baş/son boşluk kırpılır) |
| seri_norm | String(80); `normalize_seri()` çıktısı; `ix_sos_seri_norm` + GIN `pg_trgm` |
| device_id | FK devices SET NULL. Yalnız MOBILITE/ARAC_TAKIP biriminde ve kütükte bulunursa doludur |
| is_active / removed_at / removed_by | Seri değişince eski satır pasiflenir, silinmez |
| Kısıtlar | `uq_sos_aktif` kısmi tekil (service_order_id, seri_norm) WHERE is_active; `ck_sos_pasif` (is_active OR removed_at IS NOT NULL) |

### 2.4 `service_order_events` (E01-04), silinemez olay geçmişi
| Kolon | Not |
|---|---|
| id | `PkMixin` |
| service_order_id | FK RESTRICT; `ix_soe_is_zaman(service_order_id, olusma_zamani)` |
| olay_turu | `ck_soe_tur` IN (OLUSTUR, DURUM, ATAMA, PLAN, BEKLEME, BEKLEME_BITTI, NOT, EK, EK_SIL, ONAY, SONUC, DUZELTME, SERI, BAGLANTI, MUKERRER_GECILDI) |
| eski_durum / yeni_durum | yalnız DURUM ve BEKLEME olaylarında dolu |
| ozet | String(500), Türkçe insan okunur metin |
| veri | JSONB; kişisel veri içermez, yalnız alan adı ve kodlar |
| user_id / olusma_zamani | `Clock` ile yazılır |

Silinmezlik iki katmanda sağlanır:
1. API'de silme ve düzenleme ucu yoktur.
2. Migration'da `trg_soe_salt_ekleme` tetikleyicisi (BEFORE UPDATE OR DELETE → RAISE) kurulur. `TRUNCATE` tetikleyiciyi çalıştırmadığı için testler etkilenmez.

### 2.5 `service_holds` (E01-05)
| Kolon | Not |
|---|---|
| service_order_id | FK RESTRICT |
| neden | `ck_hold_neden` IN (MALZEME, MUSTERI_ONAYI, TEKLIF, MUSTERI_ERISIMI, PERSONEL, DIGER) |
| aciklama | `ck_hold_diger_aciklama`: neden='DIGER' ise NOT NULL |
| onceki_durum | release sonrası dönülecek durum |
| started_at / started_by / released_at / released_by | `ck_hold_aralik` released_at >= started_at |
| Tek aktif bekleme | `uq_hold_aktif` kısmi tekil (service_order_id) WHERE released_at IS NULL |

### 2.6 `service_results` (E01-06), ziyaret veya işlem sonucu
| Kolon | Not |
|---|---|
| service_order_id | FK RESTRICT |
| sonuc | `ck_sr_sonuc` IN (COZULDU, COZULEMEDI, TEKRAR_GIDILECEK, TEKLIF_SUNULACAK, SERVISE_ALINDI) |
| cozum_kanali | `ck_sr_kanal` IN (TELEFON, UZAKTAN, YERINDE, ATOLYE); NOT NULL |
| yapilan_islem | Text NOT NULL; `ck_sr_islem_bos` length(trim) > 0 |
| ariza_nedeni_id | FK service_fault_reasons RESTRICT, NULL olabilir |
| gecersiz_at / gecersiz_by | Yeniden açılışta önceki kapanış sonucu geçersiz kılınır, silinmez |

### 2.7 `service_fault_reasons` (E01-06), birim bazlı arıza nedeni kataloğu
`birim` (`ck_sfr_birim`), `ad`, `sira`, `is_active`; `uq_sfr_birim_ad`. Tohum listesi §5 karar K6'dadır.

### 2.8 `service_order_assignments` (E01-12)
| Kolon | Not |
|---|---|
| service_order_id | FK RESTRICT |
| user_id | FK users RESTRICT |
| rol | `ck_soa_rol` IN (SEF, TEKNISYEN) |
| is_lead | sorumlu teknisyen |
| assigned_at / assigned_by / removed_at / removed_by | atama geçmişi; satır silinmez |
| Kısıtlar | `uq_soa_aktif` kısmi tekil (service_order_id, user_id) WHERE removed_at IS NULL; `uq_soa_tek_sorumlu` kısmi tekil (service_order_id) WHERE is_lead AND removed_at IS NULL; `ck_soa_sorumlu_teknisyen` (NOT is_lead OR rol='TEKNISYEN') |

### 2.9 `service_approvals` (E01-08), müşteri onayı
| Kolon | Not |
|---|---|
| service_order_id | FK RESTRICT |
| tur | `ck_sa_tur` IN (IMZA, SOZLU, BASILI_FORM, ALINAMADI) |
| imzalayan_ad / imzalayan_unvan | kişisel veri |
| ek_id | FK attachments RESTRICT; imza PNG'si ya da basılı form fotoğrafı (IMZA ve BASILI_FORM'da zorunlu, `ck_sa_ek`) |
| eksik_nedeni | `ck_sa_neden`: tur='ALINAMADI' ise NOT NULL |
| gecersiz_kilan_id | FK service_approvals; yeni kayıt eskisini geçersiz kılar, eski satır değişmez |

### 2.10 Genişletilen mevcut yapılar (yalnız ekleme)
- `permissions.py`: `BIRIMLER`, `SCOPE_OWN_UNITS="KENDI_BIRIMI"`, `SCOPE_OWN_JOBS="KENDI_ISLERI"`, yeni izinler ve roller (§3).
- `models/attachment.py:31-62`: `EK_SAHIPLERI += ("service_orders",)`, `EK_TURLERI += ("SERVIS_ONCESI", "SERVIS_SONRASI", "SERVIS_FORMU", "MUSTERI_IMZASI")`. `kind` kolonunda DB CHECK yok, bu yüzden migration gerekmez.
- `services/normalize.py`: yeni `normalize_seri()`.
- `services/settings.py:33-93` `DEFAULTS`:
  - `servis_onay_zorunlu_turler: []`
  - `servis_liste_kapali_gun: 90`
  - `servis_bildirim_geriye_uyari_gun: 7`
  - `servis_toplu_atama_ust_sinir: 150`
  - `servis_bekleme_uyari_gun: 5`
  - `servis_kapanis_bekleme_uyari_gun: 2`
- `services/gorevler.py:47-57` `KAYIT_TIPLERI` → `KayitTipi("servis", "Servis İşi", ServiceOrder, ("so_no",), "/servis-isleri/{id}")`.
- `services/uyarilar.py:47` `topla()` → `if user.has("servis.gor"):` bloğu.
- `services/kvkk.py:30, 217-262`: hesabın anonimleştirilmesi o hesaba bağlı `service_orders.iletisim_ad/telefon` ve `service_approvals.imzalayan_ad/unvan` alanlarını da temizler.

### 2.11 Migration'lar
Zincir `b30e012dd879`'a bağlanır; kodlamaya başlarken `alembic heads` ile yeniden doğrulanır.
1. `make makemigration m="servis_birim_uyeligi"`: `user_units`. Bu migration RBAC katmanına aittir.
2. `make makemigration m="servis_is_emri_cekirdek"`:
   - Bölüm 2.2–2.9'daki tablolar.
   - `CREATE SEQUENCE service_order_no_seq` (op.execute).
   - `trg_soe_salt_ekleme` fonksiyonu ve tetikleyicisi (op.execute).
   - pg_trgm GIN indeksi (op.execute).
   - Arıza nedeni tohum verisi `op.bulk_insert` ile yazılır. Downgrade'de tohum satırları silinir.
3. Downgrade sırası: tetikleyici, fonksiyon, tablolar (FK sırasıyla), sequence. Sonra head→base→head testi koşar.
4. Canlı tablolarda (`work_orders`, `settlements`, `devices`, `stock_*`) hiçbir CHECK veya EXCLUDE değişmez.

---

## 3. İzinler, kapsam ve roller

### 3.1 Yeni izin kodları (`permissions.py:14-77` PERMISSIONS'a, modül "Teknik Servis")
| Kod | Açıklama |
|---|---|
| `servis.gor` | Servis işlerini, geçmişini ve eklerini görür |
| `servis.yaz` | Servis işi açar, temel bilgiyi düzeltir, not/ek ekler, bekletir, saha durumunu ilerletir |
| `servis.planla` | Atama, toplu atama, plan (E02 bu izni kullanır) |
| `servis.tamamla` | Sonuç girer ve işi TAMAMLANDI yapar |
| `servis.kapat` | KAPATILDI / İPTAL / TEKRAR_ACILDI; kapalı işte gerekçeli düzeltme ve seri değişikliği |
| `servis.uzaktan_coz` | Açılışta "telefonla/uzaktan çözüldü" kısa yolu |
| `servis.tanim` | Arıza nedeni kataloğunu düzenler |

- Excel dışa aktarımı yeni izin açmaz. Mevcut `rapor.disaaktar` ile `servis.gor` birlikte istenir.
- Fiyat ve maliyet bu modülde YOKTUR. `maliyet.gor` kümesi değişmez (`tests/unit/test_permissions.py`).

### 3.2 Kapsam
- `SCOPE_OWN_UNITS = "KENDI_BIRIMI"`: yalnız `user_units`'teki birimlerin servis işleri.
- `SCOPE_OWN_JOBS = "KENDI_ISLERI"`: birim filtresine ek olarak yalnız kişinin atama satırı bulunan işler. Atamanın aktif ya da geçmiş olması fark etmez. Yazma için aktif atama gerekir.
- `SCOPES` demeti bu iki değerle genişler.
- `api/users.py:181` ve `:225`'teki sabit `(SCOPE_ALL, SCOPE_OWN_CUSTOMERS)` kontrolü `SCOPES` olarak değişir. `_KAPSAM_ACIKLAMA` (`api/users.py:73`) genişletilir.
- `kapsam_musteri` / `kapsam_disinda_mi` (`services/accounts.py:42, 56`) ve `scope_filter` (`api/deps.py:116`) yalnız `KENDI_MUSTERILERI`'ye baktığı için yeni kapsamlar diğer modüllerde `TUMU` gibi davranır. Mobilite akışı değişmez.
- `services/teknik_servis/kapsam.py`:
  - `kapsam_birim(stmt, user, birim_sutunu)`
  - `kapsam_kendi_isleri(stmt, user)` (EXISTS assignments)
  - `birim_disinda_mi(user, birim) -> bool`
  - `is_erisimi_yok_mu(db, user, so, yazma: bool) -> bool`: tek kayıt uçlarında 404. Müşteri, birim ve kendi işleri kontrollerini birleştirir.
- Servis listeleri sırayla `kapsam_musteri(stmt, user, ServiceOrder.customer_id)`, `kapsam_birim` ve `kapsam_kendi_isleri` uygular.

### 3.3 Roller (`ROLES`; mevcut roller DEĞİŞMEZ, `TEKNIK_SERVIS` mobilite rolü olarak kalır)
| Kod | Ad | Kapsam | İzinler |
|---|---|---|---|
| SERVIS_YONETICI | Teknik Servis Müdürü | TUMU | servis.* (7), hesap.gor, hesap.yaz, urun.gor, cihaz.gor, rma.gor, teklif.gor, gorev.gor, gorev.yaz, rapor.gor, rapor.disaaktar |
| SERVIS_SEF | Servis Şefi / Takım Lideri | KENDI_BIRIMI | servis.gor/yaz/planla/tamamla/kapat/uzaktan_coz, hesap.gor, urun.gor, cihaz.gor, rma.gor, gorev.gor, gorev.yaz, rapor.gor, rapor.disaaktar |
| SERVIS_OPERASYON | Servis Operasyon Uzmanı | KENDI_BIRIMI | servis.gor, servis.yaz, servis.uzaktan_coz, hesap.gor, hesap.yaz, urun.gor, cihaz.gor, gorev.gor, gorev.yaz |
| SERVIS_TEKNISYEN | Servis Teknisyeni | KENDI_ISLERI | servis.gor, servis.yaz, servis.tamamla, hesap.gor, urun.gor, cihaz.gor, gorev.gor |
| ATOLYE | Atölye Teknisyeni | KENDI_BIRIMI | servis.gor, servis.yaz, servis.tamamla, hesap.gor, urun.gor, cihaz.gor, rma.gor, gorev.gor |

`YONETIM` `servis.gor`'ü kendiliğinden alır (`permissions.py:84, 247`). `ADMIN` hepsini alır. `ozellestirildi=True` olan DB rollerine yeni izin İNMEZ; seed bunu log'a yazar (`models/rbac.py:64-69`). Kurulum notunda bu roller için elle ekleme listesi verilir. M01-D02'nin özü budur.

---

## 4. Servis iş emri durum makinesi `SERVIS_IS_EMRI` (`services/statemachine.py`)

```
baslangiclar = {MUSTERI_TALEBI}
MUSTERI_TALEBI → PLANLAMADA, PLANLANDI, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, IPTAL
PLANLAMADA     → PLANLANDI, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, IPTAL
PLANLANDI      → YOLA_CIKILDI, SAHADA, ISLEMDE, PLANLAMADA, BEKLEMEDE, IPTAL
YOLA_CIKILDI   → SAHADA, ISLEMDE, PLANLAMADA, BEKLEMEDE
SAHADA         → ISLEMDE, TAMAMLANDI, ATOLYEDE, PLANLAMADA, BEKLEMEDE
ISLEMDE        → TAMAMLANDI, ATOLYEDE, KARGODA, TEST_KONTROL, PLANLAMADA, BEKLEMEDE
ATOLYEDE       → TEST_KONTROL, KARGODA, TAMAMLANDI, PLANLAMADA, BEKLEMEDE
KARGODA        → ATOLYEDE, TAMAMLANDI, BEKLEMEDE
TEST_KONTROL   → TAMAMLANDI, ATOLYEDE, BEKLEMEDE
BEKLEMEDE      → MUSTERI_TALEBI, PLANLAMADA, PLANLANDI, YOLA_CIKILDI, SAHADA, ISLEMDE, ATOLYEDE, KARGODA, TEST_KONTROL, IPTAL
TAMAMLANDI     → KAPATILDI, TEKRAR_ACILDI
KAPATILDI      → TEKRAR_ACILDI
TEKRAR_ACILDI  → PLANLAMADA, PLANLANDI, SAHADA, ISLEMDE, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, IPTAL
IPTAL          → ()   (terminal; yeni arıza = yeni iş + bağlı iş)
```

**Uç kısıtları:** Hangi hedefe hangi uçtan gidilebildiği `UC_HEDEFLERI` sabitinde durur ve servis içinde doğrulanır.

| Hedef durum | Giriş yolu |
|---|---|
| PLANLANDI | yalnız `planla()` (E02 plan ucu ve E01-12 toplu ucu) |
| BEKLEMEDE | yalnız bekleme ucu (E01-05) |
| TAMAMLANDI | yalnız sonuç ucu (E01-06) |
| KAPATILDI / IPTAL / TEKRAR_ACILDI | kendi uçları + `servis.kapat` |
| YOLA_CIKILDI, SAHADA, ISLEMDE, ATOLYEDE, KARGODA, TEST_KONTROL, PLANLAMADA | genel `POST /durum` ucu (saha ilerleme) |

**Tek giriş noktası:** Tüm uçlar ve diğer modüller (atölye E05, PB worker E04) `services/teknik_servis/is_emirleri.py:durum_degistir(db, so, hedef, *, kaynak, user_id, clock, not_=None)` fonksiyonunu çağırır. Fonksiyon şu adımları uygular:
1. `SERVIS_IS_EMRI.dogrula` ile geçişi doğrular.
2. Uç kısıtını doğrular.
3. Tarihleri düzenler: TAMAMLANDI'da `completed_at`, KAPATILDI'da `closed_at`; TEKRAR_ACILDI'da bu ikisi NULL olur ve `reopen_count + 1` yapılır.
4. Olay geçmişine DURUM satırı yazar.

Aynı durum tekrar gelirse `IzinsizGecis` oluşur ve API 409 döner. Bu yüzden boş yere olay satırı yazılmaz (M01-15'in özü). `MAKINELER["servis_is_emri"]` olarak kaydedilen makineyi meta-test (`tests/unit/test_statemachine.py`) otomatik sınar.

---

## 5. Kararlar (kullanıcıya soru sorulmadı)

- **K1 Kapatma yetkisi.** Teknisyen işi yalnız TAMAMLANDI yapabilir. KAPATILDI'yı `servis.kapat` sahibi (şef veya müdür) verir. Telefonla çözülen iş dahil hiçbir iş otomatik kapanmaz. *Gerekçe:* tek kontrol noktası olur ve "kapanış bekleyen" KPI'sı anlamlı kalır.
- **K2 POC durumları.** POC'nin "Telefonla Destek / Uzaktan Müdahale / Yerinde Müdahale" durumları çözüm kanalına (TELEFON/UZAKTAN/YERINDE) taşınır ve POC standart akışa girer. Göç eşlemesi E01-06'dadır.
- **K3 Açılışta çözüldü.** Operasyon uzmanı (`servis.uzaktan_coz`) telefonla ya da uzaktan çözdüğü işi tek istekte MUSTERI_TALEBI→TAMAMLANDI olarak kaydedebilir. Şef ayrıca kapatır.
- **K4 Müşteri onayı.** Başlangıçta hiçbir türde zorunlu değildir (`servis_onay_zorunlu_turler=[]`). Kabul edilen biçimler: ekranda imza (canvas PNG), basılı formun fotoğrafı, sözlü onay, "alınamadı + neden". "Alınamadı" için şef onayı gerekmez; raporda görünür.
- **K5 Dosya saklama.** Canlı `storage.py` kullanılır: `FILES_DIR`, 25 MB sınırı, içerik adresli depolama. Eski analizdeki 10 MB önerisi alınmadı, çünkü canlı sınır tüm modüllerde 25 MB ve telefon fotoğrafları için gerekli. Saklama süresi `kvkk_saklama_yili` ayarına bağlıdır. Ekleri yalnız `servis.gor` ve kapsamı uygun kullanıcılar görür.
- **K6 Arıza nedeni.** Birim bazlı `service_fault_reasons` tablosu açılır. Her birime şu kısa tohum liste yazılır: Güç/Besleme, Kablo/Bağlantı, Donanım Arızası, Yazılım/Yapılandırma, Kullanıcı Hatası, Çevresel/Fiziksel Hasar, Arıza Bulunamadı, Diğer. `servis.tanim` sahibi listeyi düzenler.
- **K7 Tekrar arıza.** Kapanmış işte arıza tekrar ederse YENİ iş açılır ve `iliski_turu=TEKRAR_ARIZA` ile eskisine bağlanır. TEKRAR_ACILDI yalnız yanlış kapanış ya da şef reddi için kullanılır. IPTAL terminaldir.
- **K8 Talep kanalları.** TELEFON, WHATSAPP, EPOSTA, SAHADA_BILDIRILDI, BAKIM_OTOMATIK, DIGER. DIGER, eksik kalan kanalları kaybetmemek için eklendi.
- **K9 Plansız bakım.** GUNLUK_SERVIS kategorisine ve servis KPI'larına girer. PLANLI_BAKIM kategorisi yalnız `tur=PB` işlerindir.
- **K10 Kapalı işte düzeltme.** Yalnız `servis.kapat` sahibi, gerekçeyle yapabilir.
- **K11 İletişim bilgisi görünürlüğü.** `iletisim_telefon` alanı `servis.yaz` izni olmayanlara `kvkk.maskele` (`services/kvkk.py:398`) ile maskeli döner. Liste ve Excel dahildir.
- **K12 Durum kataloğu.** Kodda sabittir (tuple, CHECK ve makine). Yönetici ekranından eklenmez.
- **K13 Atölye teslimi.** Atölye kaydı TESLIM_EDILDI olunca servis işi TAMAMLANDI olur, KAPATILDI'yı şef verir. Geçiş `durum_degistir(kaynak="ATOLYE")` üzerinden yapılır (M01-D01'in özü).
- **K14 Şefin iş açması.** Şef iş açabilir (`servis.yaz`).
- **K15 Personel.** Canlıda ayrı personel tablosu yok. Atama `users.id` ile yapılır ve "aynı ad" sorunu yapısal olarak ortadan kalkar. ERP hesabı olmayan saha personeline pasif-girişsiz kullanıcı açılır. Personel/yetkinlik modülü (E08) gelirse bağlanır.
- **K16 Numara.** `service_order_no_seq` global sequence kullanılır, yıl/ay sıfırlaması yoktur. Biçim `SRV-YYYYAA-NNNNNN` / `PB-YYYYAA-NNNNNN`. Göçle gelen eski numaralar (`SRV-yyyyMM-####`) olduğu gibi korunur. Hane sayısı farklı olduğu için çakışmaz; `uq_so_no` ayrıca güvence verir. Mevcut `count()+1` üreticilerine dokunulmaz.
- **K17 Ayrı panel.** Servis KPI'ları ayrı `ServisPaneli` sayfasında durur. Mobilite `PanelPage` ve `services/reports.dashboard` değişmez, böylece altın kayıt ve hak ediş paneli etkilenmez.
- **K18 Magic-byte denetimi.** Yalnız `service_orders` eklerinde uygulanır (jpg/png/webp/heic/pdf imza baytları). Tüm modüllere genişletme, güvenlik sıkılaştırma aşamasına bırakılır, çünkü mevcut yüklemeleri kırabilir.
- **K19 Ek silme.** Paylaşılan `attachments` tablosuna "void" kolonu eklenmez. Servis işi ekini yalnız yükleyen kişi 24 saat içinde ya da `servis.kapat` sahibi silebilir. Kapalı işte silme ve ekleme yalnız `servis.kapat` ile yapılır. Silinen dosyanın adı ve sha256 değeri `EK_SIL` olayıyla geçmişte kalır.
- **K20 Plan verisinin sahibi.** Plan verisi (tarih, ekip, ziyaret) E02 `service_plans` tablosundadır. E01 yalnız `planla()` sözleşmesini ve PLANLANDI geçiş kuralını tanımlar. "Bugün planlı" KPI'sı E02 gelene kadar gizlidir.
- **K21 Birim altyapısının yeri.** `BIRIMLER`, `KENDI_BIRIMI` ve `user_units` bu modülde (E01-01) kurulur, çünkü servis iş emrinin ön koşuludur. Kullanıcı ekranındaki birim yönetimi E13'te genişletilir.
- **K22 Teknisyen kapsamı.** Teknisyenin "yalnız kendi işi" kuralı rol adına değil `KENDI_ISLERI` kapsamına bağlanır (M01-18). İzin bayrağı açılmaz, çünkü kayıt kapsamı canlıda `Role.scope` ile ifade ediliyor.
- **K23 İzin birleştirme.** Atama ve plan tek izinde (`servis.planla`) birleştirildi. Eski sistemde aynı roller (şef/müdür) ikisine birden sahipti; ayrı tutmak boş izin üretirdi.
- **K24 Bağlı iş.** Bir işin tek üst bağlantısı vardır (`iliskili_is_id`). Çoklu ilişki gerekirse ileride ara tablo açılır.
- **K25 Olay tablosu ve denetim izi.** Olay geçmişi denetim izinin yerini almaz. Kritik işlemler (oluştur, kapat, iptal, yeniden aç, düzeltme, atama) AYRICA `audit.log` / `log_change` ile aynı transaction'da yazılır.
- **K26 Mükerrer kontrolü.** Yalnız AÇIK işlerde aynı `seri_norm` aranır ve sonuç 409 + liste döner. Müşteri + lokasyon eşleşmesi engel olmaz, yanıtta `uyarilar` olarak döner.
- **K27 PB kalıcılığı.** PB işi iptal edilse bile `uq_so_pb_cihaz_donem` onu saymaya devam eder, çünkü worker'ın idempotentliği bunu gerektirir. İptal edilen PB'yi yeniden üretmek E04'te ayrı yönetici eylemiyle yapılır.

---

## 6. Maddeler

Her madde için: canlı durum, karşılık, yaklaşım, dosyalar, kabul, öncelik, efor, bağımlılık ve canlı risk. Kaynak maddeler parantez içindedir.

### E01-01 · Birim kapsamı ve servis izin/rol altyapısı (M01-18, M01-D02)
- **Canlı:** YOK. Kapsam yalnız `TUMU/KENDI_MUSTERILERI` (`permissions.py:80-82`, `services/accounts.py:42-61`). Birim kavramı yok. `api/users.py:181,225` kapsamı sabit kontrol ediyor.
- **Yaklaşım:**
  - `permissions.py`'ye `BIRIMLER`, `SCOPE_OWN_UNITS`, `SCOPE_OWN_JOBS`, 7 yeni izin ve 5 yeni rol eklenir (§3).
  - `models/teknik_servis.py` → `UserUnit` modeli; `User.birimler` ilişkisi `lazy="selectin"`.
  - Migration `servis_birim_uyeligi`.
  - `services/teknik_servis/kapsam.py` yazılır.
  - `api/users.py` kapsam doğrulaması `SCOPES` olur; kullanıcı düzenlemede `birimler: list[str]` alanı gelir (denetime yazılır, kişi kendi birimini değiştiremez).
  - `/api/auth/me` (`api/auth.py:138`) `UserOut`'una `birimler` eklenir.
  - Ön yüz `UsersPage` birim çoklu seçimi ve `AuthContext`'e `birimler` eklenir.
- **Kabul:**
  - (1) Her yeni izin en az bir role atanmış (unit test yeşil).
  - (2) `maliyet.gor` sahipleri kümesi değişmemiş.
  - (3) `KENDI_BIRIMI` rolündeki kullanıcı hesap, cihaz ve iş emri listelerinde bugünkü `TUMU` sonucunu görüyor (regresyon testi).
  - (4) `/auth/me` `birimler` döndürüyor.
  - (5) Rol düzenleme `KENDI_BIRIMI`'yi kabul ediyor, geçersiz kapsam 400.
  - (6) Kişi kendi birimini değiştiremiyor (400).
  - (7) Özelleştirilmiş rol için seed uyarısı log'da.
- **P1 · M · Bağımlılık:** — · **Canlı risk:** `api/users.py` kapsam listesi değişir; mevcut iki değer aynen kabul edilmeye devam eder. Mevcut rollerin izin listesine dokunulmaz.

### E01-02 · Servis iş emri çekirdeği: model, numara, açılış, detay (M01-07 kısmen, M01-16 kısmen)
- **Canlı:** YOK. `work_orders` servis işi taşıyamaz (`models/workorder.py:84-91` tip/durum CHECK, `settlement_period` zorunlu).
- **Yaklaşım:**
  - `service_orders` ve `service_order_serials` tabloları (§2.2-2.3), `service_order_no_seq`.
  - `services/teknik_servis/is_emirleri.py`:
    - `@dataclass ServisIsiGirdisi`, `class ServisIsiHatasi(ValueError)`.
    - `numara_uret(db, clock, tur)`.
    - `olustur(db, girdi, clock, user_id)` yalnız flush eder.
    - `tur_kategorisi()`.
    - `TUR_KURALLARI`: tur → (kategori, seri_zorunlu).
  - `api/teknik_servis.py`:
    - `router = APIRouter(prefix="/api/teknik-servis")`; `Okuyucu/Yazici` takma adları.
    - `GET /isler/form-verileri`, `POST /isler`, `GET /isler/{id}`.
    - Detay çıktısı `_cikti()` ile `sonraki_durumlar` ve `sure_durumu` (E09 gelene kadar "bilinmiyor") içerir.
    - `main.py:182-209`'a `include_router` eklenir.
  - Birim kuralları:
    - Açılışta `birim` kullanıcının birimlerinde olmalı; değilse 403.
    - `customer_id` hesabı `is_musteri` olmalı.
    - `address_id` ve `contact_id` aynı hesaba ait olmalı; değilse 400.
  - Denetim: `audit.log("service_orders","olustur")`. İletişim alanı varsa `is_personal_data=True`.
  - Ön yüz:
    - `api/teknikServis.ts`.
    - `pages/ServisIsFormu.tsx` (KartPenceresi kalıbı; müşteri seçince adres ve kişi listesi dolar).
    - `pages/ServisIsleriPage.tsx` (Drawer detay).
    - Rota `/servis-isleri`, `/servis-isleri/:id`; menü `{key:"/servis-isleri", label:"Servis İşleri", izin:"servis.gor"}`. Mobilite menüsü "İş Emirleri" adıyla kalır.
- **Kabul:**
  - (1) `servis.yaz` olmadan POST 403, olunca 201 ve `so_no` `SRV-` ile başlıyor.
  - (2) İki eşzamanlı açılış farklı numara alıyor (sequence).
  - (3) Kapsam dışı birime açılış 403.
  - (4) Başka hesabın adresiyle açılış 400.
  - (5) `seri_zorunlu` türde seri yoksa 400.
  - (6) Seri no baştaki sıfır ve `/ - .` ile aynen saklanıyor.
  - (7) `work_orders`, `work_order_items` ve `settlements` satır sayıları değişmiyor (test).
  - (8) Altın kayıt testi yeşil.
- **P1 · L · Bağımlılık:** E01-01 · **Canlı risk:** Yalnız yeni tablolar. Mobilite iş emri listesi ve hak edişi bu tabloları okumuyor. "İş Emirleri" ile "Servis İşleri" adları karışmasın diye menü ve sayfa başlıklarında ad ayrımı zorunlu.

### E01-03 · Sunucu tarafı durum yaşam döngüsü (M01-09; öz: M01-13, M01-D01, M01-15)
- **Canlı:** KISMEN. `StateMachine` ve meta-test var (`services/statemachine.py:27-83, 189-196`). Servis makinesi yok. Mobilite iş emrinde makine yok ve bu sapma kopyalanmayacak.
- **Yaklaşım:**
  - `SERVIS_IS_EMRI` makinesi (§4) ve `MAKINELER["servis_is_emri"]` kaydı.
  - `durum_degistir()` tek giriş noktası; `UC_HEDEFLERI`; `DURUM_GRUPLARI` (ACIK alt grupları ve KAPALI).
  - Uçlar:
    - `POST /isler/{id}/durum {hedef, beklenen_durum, not}`.
    - `POST /isler/{id}/kapat`.
    - `POST /isler/{id}/iptal {gerekce}`.
    - `POST /isler/{id}/yeniden-ac {gerekce}`.
  - Durum değişen her uç yanıtında `sonraki_durumlar` döner.
  - İptal kontrolü: açık zaman kaydı (E09) varsa 409.
  - `planla()` sözleşmesi: kapalı veya iptal işe plan 409. SAHADA/ISLEMDE işin planı değişirse durum PLANLANDI'ya geri düşmez.
  - Tamamlama koşulları:
    - Geçerli sonuç kaydı var.
    - `TUR_KURALLARI` seri kuralı sağlanıyor.
    - Açık süre sayacı yok (E09).
    - Onay kuralı (E01-08) sağlanıyor.
- **Kabul:**
  - (1) Katalog dışı hedef 422 (Pydantic `Literal`), izinsiz geçiş 409 ve mesajda izinli hedefler.
  - (2) MUSTERI_TALEBI→KAPATILDI 409.
  - (3) `servis.kapat` olmayan hesapla kapat/iptal/yeniden-aç 403.
  - (4) Gerekçesiz iptal veya yeniden açma 422/400.
  - (5) Yeniden açılışta `completed_at` ve `closed_at` NULL, `reopen_count` +1, önceki sonuç `gecersiz_at` dolu.
  - (6) Aynı durumu tekrar göndermek olay satırı üretmiyor.
  - (7) `beklenen_durum` uyuşmazsa 409.
  - (8) Genel durum ucuyla BEKLEMEDE, PLANLANDI veya TAMAMLANDI 400 ("ilgili ucu kullanın").
  - (9) Kapalı işe plan 409 ve durum değişmemiş.
  - (10) Meta-test yeni makineyi sınıyor.
  - (11) Atölye kaynaklı geçiş de olay geçmişine yazılıyor.
- **P1 · L · Bağımlılık:** E01-02, E01-04 · **Canlı risk:** `MAKINELER`'e ekleme meta-testi genişletir, diğer makinelere dokunulmaz.

### E01-04 · Birleşik iş geçmişi ve iş notu (M01-06; öz: M01-15)
- **Canlı:** KISMEN. Genel `audit_logs` var (`services/audit.py:26-92`), ama servis işine özel, türlü ve silinemez zaman çizelgesi yok.
- **Yaklaşım:**
  - `service_order_events` tablosu ve `trg_soe_salt_ekleme` tetikleyicisi.
  - `services/teknik_servis/gecmis.py:olay_yaz(db, so, tur, ozet, veri, user_id, clock, eski=None, yeni=None)`. Tüm servis fonksiyonları bunu çağırır.
  - Uçlar:
    - `POST /isler/{id}/notlar {metin}`: durum değişmez.
    - `GET /isler/{id}/gecmis`: tür, kullanıcı adı, zaman, özet.
  - Silme ve düzenleme ucu YOK.
  - Ön yüz: Drawer'da `Timeline` ve olay türü filtresi.
- **Kabul:**
  - (1) Açılış, durum, atama, plan, bekleme ve bitişi, not, ek, ek silme, onay, sonuç, düzeltme, seri ve bağlantı işlemlerinin her birinden sonra `/gecmis` yeni satır döndürüyor (parametrik test).
  - (2) Not ekleme `status` ve `version` değerini değiştirmiyor.
  - (3) Veritabanında `UPDATE/DELETE service_order_events` hata veriyor.
  - (4) Durum değişmeden yapılan atama kaydında DURUM satırı yok, ATAMA satırı var.
  - (5) Olay `veri` alanında kişisel veri yok (telefon değeri geçmiyor).
- **P1 · S · Bağımlılık:** E01-02 · **Canlı risk:** yok.

### E01-05 · Bekleme (hold) akışı (M01-14)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `service_holds` tablosu, `uq_hold_aktif` ve `ck_hold_diger_aciklama`.
  - `bekletme.py`:
    - `beklet(neden, aciklama)`: `onceki_durum` kaydedilir ve `durum_degistir(BEKLEMEDE)` çağrılır.
    - `beklemeyi_bitir()`: `onceki_durum`'a döner; o geçiş artık geçersizse PLANLAMADA'ya döner ve özet bunu söyler.
  - Uçlar: `POST /isler/{id}/bekleme`, `POST /isler/{id}/bekleme/bitir`.
  - Rapor fonksiyonu `bekleme_sureleri()`: iş bazında toplam bekleme dakikası; Excel kolonu.
  - Ön yüz: neden `Select`, DIGER seçilince açıklama zorunlu. `prompt()` kullanılmaz.
- **Kabul:**
  - (1) Bekletme ve bitirme sonrası geçmişte nedenle birlikte satır var.
  - (2) Aktif beklemede ikinci bekletme 409 (`uq_` → `main.py` mesajı).
  - (3) Genel durum ucuyla BEKLEMEDE 400.
  - (4) DIGER + boş açıklama 400.
  - (5) Bekleme süresi dakikası Excel'de ve iş detayında görünüyor.
  - (6) Kapalı iş bekletilemiyor (409).
- **P1 · S · Bağımlılık:** E01-03, E01-04 · **Canlı risk:** yok.

### E01-06 · Kapanış sonucu, çözüm kanalı ve açılışta çözüldü kısa yolu (M01-01, M01-02)
- **Canlı:** YOK. RMA'da çözüm alanları var (`services/rma.py:143 coz`), ama servis işine uygulanamaz (RMA cihaz ister).
- **Yaklaşım:**
  - `service_results` ve `service_fault_reasons` (tohumlu) tabloları.
  - `sonuc.py:sonuc_gir()` sonuca göre şunları yapar:

    | Sonuç | Etki |
    |---|---|
    | COZULDU / COZULEMEDI | TAMAMLANDI |
    | TEKRAR_GIDILECEK | PLANLAMADA'ya döner, olay yazılır |
    | TEKLIF_SUNULACAK | TEKLIF nedenli beklemeye girer (E01-05); E07 köprüsü açık kalır |
    | SERVISE_ALINDI | ATOLYEDE; E05 atölye kaydı açılır |

  - `POST /isler/{id}/sonuc` (`servis.tamamla`).
  - `POST /isler` gövdesinde `acilista_cozuldu: {kanal: TELEFON|UZAKTAN, yapilan_islem}` (`servis.uzaktan_coz`). Kayıt, sonuç ve TAMAMLANDI tek transaction'da oluşur.
  - Tanım uçları: `GET/POST/PATCH /tanimlar/ariza-nedenleri` (`servis.tanim`).
  - Göç eşleme betiği `migration/servis_goc.py`: POC durum ve türleri çözüm kanalına eşlenir; eşlenemeyen sayısı raporlanır.
  - Ön yüz: "Sonuç Gir" penceresi (kanal ve sonuç zorunlu; arıza nedeni birim listesinden).
- **Kabul:**
  - (1) Sonuç yokken TAMAMLANDI'ya giden her yol 409.
  - (2) Kanal boşsa 422.
  - (3) TEKRAR_GIDILECEK işi PLANLAMADA yapıyor ve geçmişe yazıyor.
  - (4) TEKLIF_SUNULACAK aktif TEKLIF beklemesi açıyor.
  - (5) Açılışta çözüldü kaydı tek istekte oluşuyor; geçmişte "Müşteri Talebi → Tamamlandı (Telefonla)" var.
  - (6) Bu işler "plan bekleyen" ve "atanmamış" KPI'larına girmiyor.
  - (7) Excel'de işlem, arıza nedeni, sonuç, kanal ve tamamlanma kolonları var.
  - (8) Göç betiği eşlenemeyen sayısını yazıyor.
- **P1 · M · Bağımlılık:** E01-03 · **Canlı risk:** yok.

### E01-07 · Servis işi ekleri ve fotoğraf (M01-03)
- **Canlı:** KISMEN. Genel ek altyapısı VAR: polimorfik, rastgele ad yerine içerik özeti, path traversal koruması `storage.py:157-165`, beyaz liste `:28-38`, `no-store` önbellek. Eksikler:
  - `service_orders` sahip değil.
  - `_kapsam` yalnız `accounts` için çalışıyor (`api/attachments.py:102`).
  - Magic-byte denetimi yok (`storage.py:70-83` beyan ve uzantıya bakıyor).
  - Silme kalıcı (`api/attachments.py:303`).
- **Yaklaşım:**
  - `EK_SAHIPLERI` ve `EK_TURLERI` genişletilir (§2.10).
  - `SAHIP_IZNI["service_orders"]=("servis.gor","servis.yaz")`; `_SAHIP_TABLOSU`'na eklenir.
  - `_kapsam()` içine `service_orders` dalı: müşteri, birim ve kendi işleri kontrolü; başarısızsa 404.
  - `storage.imza_dogrula(icerik, mime)` yalnız `service_orders` yüklemesinde çağrılır (K18).
  - Kapalı işe ekleme ve silme yalnız `servis.kapat` ile (K19).
  - Yükleme ve silme `olay_yaz(EK / EK_SIL)` ile geçmişe yazılır.
  - Ön yüz: `EkYukleyici entity="service_orders"`; mobilde `accept="image/*" capture`.
  - Yedekleme: `FILES_DIR` zaten yedek kapsamında. Kurulum belgesinde geri yükleme testi adımı doğrulanır.
- **Kabul:**
  - (1) Uzantısı .jpg olan ama içeriği HTML olan dosya 422.
  - (2) Başka birimin veya başka teknisyenin işine ait eki listeleme ve indirme 404.
  - (3) `../` içeren dosya adı depo dışına yazılmıyor (mevcut test genişletilir).
  - (4) Kapalı işe ek ekleme `servis.kapat` olmadan 409.
  - (5) Ek ekleme ve silme geçmişte görünüyor.
  - (6) Diğer sahip türlerinin yükleme davranışı değişmemiş (`test_ekler.py` yeşil).
- **P1 · M · Bağımlılık:** E01-01, E01-04 · **Canlı risk:** `api/attachments.py` ortak uç; değişiklik yalnız `entity=="service_orders"` dallarında. Mevcut `test_ekler.py` regresyon kapısı.

### E01-08 · Müşteri onayı ve yazdırılabilir servis formu (M01-04)
- **Canlı:** KISMEN. PDF altyapısı VAR (`services/pdf.py:53-68`, `services/belgeler.py:119 firma_bilgisi`). Onay tablosu ve servis formu şablonu YOK.
- **Yaklaşım:**
  - `service_approvals` tablosu; `onay.py:onay_kaydet()` (yeni kayıt eskisini `gecersiz_kilan_id` ile geçersiz kılar).
  - `POST /isler/{id}/onay`.
  - İmza: ön yüzde canvas PNG `MUSTERI_IMZASI` türüyle eklenir, sonra onay `ek_id` ile kaydedilir.
  - `belgeler.servis_formu_baglami(db, so)` ve `templates/servis_formu.html`.
  - Form içeriği:

    | Bölüm | Kaynak |
    |---|---|
    | Künye | firma künyesi |
    | Müşteri ve lokasyon | hesap ve adres |
    | Ürün / seri | seri listesi |
    | İş bilgisi | servis türü, yapılan işlem, sonuç, onay |
    | Süre | E09 kayıtları; yoksa "Süre kaydı eksik" |
    | Parçalar | E11 stok hareketleri; yoksa "Kayıt yok" |

    Fiyat alanı YOK.
  - `GET /isler/{id}/servis-formu.pdf` (`servis.gor` ve kapsam).
  - Onay zorunluluğu: `servis_onay_zorunlu_turler` ayarı. TAMAMLANDI kontrolü E01-03'te.
- **Kabul:**
  - (1) Ayarda zorunlu olan türde onaysız tamamlama 409.
  - (2) ALINAMADI + boş neden 422.
  - (3) Onay satırı güncellenemiyor; yeni kayıt eskisini geçersiz kılıyor, ikisi de geçmişte var.
  - (4) PDF "ŞĞÜİÖÇ ışğüöç" karakterlerini doğru basıyor (metin çıkarma testi).
  - (5) Süre kaydı yokken "Süre kaydı eksik" yazıyor, "0" yazmıyor.
  - (6) PDF'te `fiyat|tutar|₺` geçmiyor.
  - (7) KVKK anonimleştirmesi `imzalayan_ad` alanını temizliyor.
- **P2 · M · Bağımlılık:** E01-06, E01-07 · **Canlı risk:** yok. Yeni şablon ve bağlam fonksiyonu ekleniyor.

### E01-09 · Talep alma bilgileri ve mükerrer kayıt kontrolü (M01-05)
- **Canlı:** YOK. Hesap mükerrer adayı var (`services/accounts.py:84-106`), ama servis işi için yok.
- **Yaklaşım:**
  - Açılışta `talep_kanali` zorunlu.
  - `contact_id` ya da (`iletisim_ad` veya `iletisim_telefon`) zorunlu; BAKIM_OTOMATIK kanalı bundan muaf.
  - `reported_at` için:
    - `clock.now()`'dan ileri olamaz (400).
    - `servis_bildirim_geriye_uyari_gun`'den eskiyse `reported_at_onay=true` istenir; yoksa 409 + uyarı.
  - `mukerrer_adaylari(db, seri_normlar, customer_id, address_id)`.
  - `GET /isler/mukerrer-kontrol` (form canlı uyarısı).
  - POST'ta açık işte aynı `seri_norm` varsa 409 + `{mevcut_isler:[so_no...]}`. `force=true` ile açılırsa MUKERRER_GECILDI olayı yazılır ve iş isteğe bağlı olarak `iliski_turu=MUKERRER` ile bağlanır.
  - Müşteri + lokasyon eşleşmesi yalnız `uyarilar` dizisinde döner.
  - İletişim bilgisi planlama kartında da (E02) görünür.
- **Kabul:**
  - (1) Kanal veya kişi/telefon boşsa 400.
  - (2) Gelecek tarihli `reported_at` 400.
  - (3) 8 gün önceki `reported_at` onaysız 409, onaylı 201.
  - (4) Açık işte aynı seri ("  abc-01 " ile "ABC-01") 409 ve iş no listesi.
  - (5) `force=true` 201 ve geçmişte "mükerrer uyarısı geçildi".
  - (6) Kapalı işte aynı seri engellemiyor.
  - (7) Kapsam dışı birimdeki mükerrer iş listede numarasıyla görünmüyor; sayı sızmasın diye yalnız "başka birimde açık kayıt var" yazıyor.
- **P2 · S · Bağımlılık:** E01-10 · **Canlı risk:** yok.

### E01-10 · Seri no normalleştirme ve cihaz/ekipman bağı (M01-16)
- **Canlı:** KISMEN. `normalize.py` IMEI, MSISDN, ICCID ve plaka için var (`services/normalize.py:22-242`); seri no için yok. Cihaz kütüğü `devices` var ama yalnız Mobilite/Araç Takip için kullanılabilir.
- **Yaklaşım:**
  - `normalize_seri(raw)`: baş/son boşluğu kırpar, iç boşlukları teke indirir, `str.upper()` uygular (Türkçe 'i' için `tr_normkey` KULLANILMAZ; seri ASCII kabul edilir), baştaki sıfırları ve `/ - .` karakterlerini korur.
  - `service_order_serials.seri_norm` indeksli.
  - MOBILITE/ARAC_TAKIP biriminde `devices` (imei/serial_no) eşleşirse `device_id` doldurulur; eşleşmezse NULL ("kütükte yok").
  - Güvenlik, Haberleşme ve POC için `devices`'a kayıt AÇILMAZ. Bağ E03 `service_equipment` ile `equipment_id` üzerinden kurulur.
  - Rapor `kutukte_olmayan_seriler()`.
- **Kabul:**
  - (1) `normalize_seri(" 00ab  12/3 ")=="00AB 12/3"` (unit).
  - (2) Mükerrer kontrolü ve tekrar arıza analizi `seri_norm` kullanıyor.
  - (3) Mobilite işinde kütükteki IMEI ile açılan işin `device_id` alanı dolu ve cihaz kartında "servis işleri" sekmesinde görünüyor.
  - (4) Kütükte olmayan seri kaydı engellemiyor ve raporda listeleniyor.
  - (5) Güvenlik birimi işi `devices` tablosuna satır eklemiyor (test).
- **P3 · S · Bağımlılık:** E01-02 · **Canlı risk:** `devices` yalnız okunur. Cihaz durum makinesine ve `uq_devices_seri` kısıtına dokunulmaz.

### E01-11 · Bağlı iş ilişkisi: Mükerrer / Tekrar Arıza / Devam (M01-D04)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `iliskili_is_id`, `iliski_turu`, `ck_so_kendine_bagli` ve `ck_so_iliski`.
  - `POST /isler/{id}/baglanti {iliskili_is_id, tur}`.
  - Döngü kontrolü servis içinde: hedefin zinciri bu işe dönmemeli; yoksa 409.
  - Detayda "bağlı işler" (üst + bu işe bağlananlar). İki tarafa da BAGLANTI olayı yazılır.
  - Hedef iş de kullanıcının kapsamında olmalı; değilse 404.
- **Kabul:**
  - (1) Mükerrer uyarısı geçilerek açılan iş bağlantılı oluşuyor.
  - (2) İş kendisine bağlanınca 409/422.
  - (3) Detayda bağlı işler listeleniyor.
  - (4) Tekrar arıza KPI'sı (E01-14) TEKRAR_ARIZA bağlarını sayıyor.
- **P2 · S · Bağımlılık:** E01-09 · **Canlı risk:** yok.

### E01-12 · Kimlik bazlı çoklu teknisyen ataması, sorumlu teknisyen ve TOPLU ATAMA (M01-10; kullanıcı doğrulaması: toplu atama/planlama)
- **Canlı:** YOK. Görev kartı üyeleri var (`models/gorev.py:108 CardMember`), ama bu plan veya ekip ataması değildir.
- **Yaklaşım:**
  - `service_order_assignments` tablosu (§2.8).
  - `atama.py`:
    - `ata(db, so, atamalar:[(user_id, rol, is_lead)], ...)`: fark hesabıyla eklenen satır açılır, çıkan satıra `removed_at` yazılır.
    - `toplu_ata(db, is_idler, atamalar, mod=EKLE|DEGISTIR)`.
  - Uçlar:
    - `PUT /isler/{id}/atama` (`servis.planla`).
    - `PUT /isler/toplu-atama` (`servis.planla`; üst sınır `servis_toplu_atama_ust_sinir`=150).
  - Toplu atama kuralları:
    - Tüm işler aynı birimde, açık ve kapsamda olmalı; değilse 409 ve sorunlu iş listesi. Hiçbiri yazılmaz.
    - Atanan kullanıcılar aktif olmalı.
    - Atanan kullanıcının birimi işin birimini kapsamalı.
  - Toplu planlama: E02'nin `PUT /isler/toplu-plan` ucu aynı doğrulama yardımcısını (`toplu_dogrula`) kullanır. E01 bunu sağlar.
  - Ön yüz:
    - Listede satır seçimi (`rowSelection`) ve "Toplu Ata" penceresi.
    - Detayda kullanıcı `Select` (yalnız birim üyeleri) ve sorumlu yıldızı.
- **Kabul:**
  - (1) Atama `user_id` ile; olmayan veya pasif kullanıcı 400.
  - (2) Bir işte ikinci sorumlu 409 (`uq_soa_tek_sorumlu`).
  - (3) Kapalı işe atama 409.
  - (4) Kullanıcının adı değişse de `KENDI_ISLERI` teknisyeni işi görmeye devam ediyor.
  - (5) Atama değişikliği ATAMA olayıyla geçmişe yazılıyor ve DURUM satırı oluşmuyor.
  - (6) 151 işlik toplu istek 422.
  - (7) Karışık birimli toplu istek 409, hiçbir iş değişmemiş.
  - (8) Başka birimdeki kullanıcıya atama 409.
- **P1 · M · Bağımlılık:** E01-01, E01-04 · **Canlı risk:** yok.

### E01-13 · Temel bilgi düzeltme ve seri no değişikliği kuralları (M01-08, M01-D03)
- **Canlı:** YOK. Emsal olarak iyimser kilitli PATCH var (`api/accounts.py`, `VersionedMixin`, `main.py` StaleDataError → 409).
- **Yaklaşım:**
  - `PATCH /isler/{id}` (`servis.yaz`).
    - Gövde `version` taşır. Düzenlenebilir alanlar: müşteri, adres, kişi, iletişim, konu, açıklama, öncelik, tür (aynı birim içinde; PB'ye geçiş veya PB'den çıkış yok), proje, sistem, kanal, `reported_at`.
    - `birim` alanı gelirse 400.
    - Kapalı işte `servis.kapat` ve `gerekce` zorunlu; yoksa 403/400.
    - PB veya atölye kaynaklı alanlar (E04/E05 dolu) 409.
    - Her değişen alan için DUZELTME olayı (alan, eski→yeni; kişisel alanlarda yalnız alan adı) ve `audit.log_change`.
  - `PUT /isler/{id}/seriler {seriler, gerekce?}`:
    - Kapalı işte `servis.kapat` ve gerekçe istenir.
    - PB işinde seri değişikliği 409 (1 cihaz = 1 PB).
    - Her değişiklik SERI olayına eski→yeni olarak yazılır; eski satır pasiflenir.
  - Ön yüz: detayda "Düzenle" (KartPenceresi; 409'da "kayıt değişti, yenileyin").
- **Kabul:**
  - (1) Açık işte düzeltme 200 ve alan bazında eski/yeni geçmişte.
  - (2) KAPATILDI işte `servis.yaz` ile 403, `servis.kapat` ve gerekçeyle 200.
  - (3) Birim değişikliği 400.
  - (4) Eski `version` ile ikinci kayıt 409.
  - (5) Kapalı işte gerekçesiz seri değişikliği 400/403.
  - (6) PB işinde seri değişikliği 409.
  - (7) Kapsam dışı işe PATCH 404 ve kayıt değişmemiş.
- **P2 · S · Bağımlılık:** E01-04, E01-03 · **Canlı risk:** yok.

### E01-14 · Servis paneli: tek KPI tanım tablosu, TIKLANABİLİR kutular, dönem seçimi (M01-11; öz: M01-12)
- **Canlı:** KISMEN. Mobilite yönetim paneli VAR (`services/reports.py:43`, `pages/PanelPage.tsx:76-200`), ama kutular tıklanamıyor ve servis verisi yok. `Statistic` bileşeni var (`components/Statistic.tsx`).
- **Yaklaşım:**
  - `services/teknik_servis/panel.py`:
    - `KPI_TANIMLARI: dict[str, KpiTanimi(baslik, grup, filtre: Callable[[Select, Clock, Donem], Select])]`.
    - Sayı ve liste AYNI filtre fonksiyonundan gelir.
  - Servis kutuları:

    | Kutu | Tanım |
    |---|---|
    | acik | açık işlerin tümü |
    | plan_bekleyen | MUSTERI_TALEBI, PLANLAMADA, TEKRAR_ACILDI |
    | planlandi | PLANLANDI |
    | sahada | YOLA_CIKILDI, SAHADA, ISLEMDE |
    | atolyede | ATOLYEDE, KARGODA, TEST_KONTROL |
    | beklemede | BEKLEMEDE (nedene göre kırılım) |
    | atanmamis | aktif teknisyen ataması yok |
    | kritik_acik | açık ve öncelik KRITIK |
    | bugun_acilan | bugün açılan |
    | kapanis_bekleyen | TAMAMLANDI |
    | bugun_planli | E02 gelince |
    | geciken | E10 gelince |

  - Dönemsel kutular (bugün / bu hafta / bu ay / son 30 gün):
    - tamamlanan.
    - telefon + uzaktan oranı.
    - ortalama çözüm süresi (`reported_at`→`completed_at`; `reported_at` yoksa `created_at`, "tahmini" sayacıyla).
    - 30 gün içinde tekrar arıza (TEKRAR_ARIZA bağı ve aynı `seri_norm`).
    - süre kaydı eksik (E09 gelince).
  - Bakım kutuları (yalnız PB): açık bakım, bu ay planlı, geciken, tamamlanan. Servis kutuları PB'yi saymaz.
  - Uçlar:
    - `GET /panel?donem=&birim=` (`servis.gor`; kapsam_birim uygulanır).
    - `GET /isler?kpi=<kod>&donem=` aynı filtreyle liste döner.
  - Ön yüz:
    - `pages/ServisPaneli.tsx`; kutuya tıklayınca `navigate("/servis-isleri?kpi=..&donem=..")`.
    - Dönem seçimi `localStorage`'da hatırlanır (try/catch).
    - Menü `{key:"/servis-paneli", label:"Servis Paneli", izin:"servis.gor"}`.
    - Mobilite `PanelPage` değişmez (K17).
- **Kabul:**
  - (1) Her KPI için parametrik test: `/panel` sayısı = `/isler?kpi=` `X-Toplam-Kayit`.
  - (2) Unit test: `DURUM_GRUPLARI` açık durumların her birini tam bir alt kutuda içeriyor; alt kutu toplamı = `acik`.
  - (3) 1 SAHADA + 1 ISLEMDE + 1 YOLA_CIKILDI → sahada kutusu 3, liste 3.
  - (4) PB işi servis kutularında sayılmıyor.
  - (5) Süre kaydı olmayan iş "eksik" kutusunda; "0 saat" yazılmıyor.
  - (6) Birim A şefinin panelinde birim B işleri sayılmıyor.
  - (7) Kutular tıklanabilir ve açılan liste aynı sayıyı gösteriyor (elle doğrulama + `npm run build`).
- **P1 · M · Bağımlılık:** E01-03, E01-05, E01-06, E01-12 · **Canlı risk:** Mobilite paneli ve `services/reports.py` sorguları değişmez; altın kayıt etkilenmez.

### E01-15 · Sunucu taraflı liste filtresi, SQL'de kapsam, sayfalama ve EXCEL dışa aktarım (M01-17; kullanıcı doğrulaması: Excel)
- **Canlı:** KISMEN. `sayfala()` VAR (`api/deps.py:170-190`), `export.satirlari_xlsx_async` VAR (`services/export.py:45`), Excel düğmesi kalıbı VAR (`pages/RaporlarPage.tsx:178-182`). Servis listesi YOK. Çok sayfalı xlsx yardımcısı YOK.
- **Yaklaşım:**
  - `GET /isler` filtreleri: `birim, kategori, durum, durum_grubu, kpi, oncelik, musteri_id, teknisyen_id, atanmamis, bas, bit, q, kapali_dahil`.
  - Varsayılan: açık işler + son `servis_liste_kapali_gun` gün içinde kapananlar.
  - `q` araması `so_no`, `konu`, `seri_norm` (trigram) ve `Account.title_key` üzerinde çalışır.
  - Kapsam SQL'de uygulanır (E01-01 yardımcıları). `limit le=200` ve `sayfala`.
  - `liste_sorgusu(user, filtre)` hem liste, hem Excel, hem KPI tarafından kullanılan tek fonksiyondur.
  - `GET /isler.xlsx` (`servis.gor` + `rapor.disaaktar`; aynı filtre).
  - `export.py`'ye eklenen `sayfalari_xlsx_async`:
    - Sayfa 1 "Servis İşleri": no, birim, tür, kategori, durum, öncelik, müşteri, lokasyon, konu, seri(ler), kanal, bildirim, açılış, tamamlanma, kapanış, sorumlu, ekip, işlem, arıza nedeni, sonuç, bekleme dk, yeniden açılma.
    - Sayfa 2 "Durum Özeti": birim × durum matrisi ve toplam satırı.
  - İletişim telefonu K11'e göre maskelenir.
  - Ön yüz: `useQuery(["servis-isleri", filtre, sayfa])`, `api.getSayfa`, `Table` sunucu sayfalaması, URL parametreleri (`kpi`, `durum`), Excel düğmesi (`window.open`).
- **Kabul:**
  - (1) Parametresiz çağrı yalnız açık ve son 90 günde kapanan işleri döndürüyor.
  - (2) `?q=` seri, no, konu ve müşteri unvanında buluyor.
  - (3) `KENDI_ISLERI` teknisyeni listede yalnız kendi işlerini görüyor, Excel'de de aynı.
  - (4) Durum özeti toplamı = filtrelenen iş sayısı.
  - (5) `rapor.disaaktar` yoksa xlsx 403.
  - (6) Sayfalar arasında kayıt kaybı yok (`_kirilma_ekle` emsali, test).
  - (7) Formül enjeksiyonu (`=cmd`) metne çevriliyor.
  - (8) 10.000 işlik test verisinde liste < 1 sn (EXPLAIN ile indeks kullanımı).
- **P1 · M · Bağımlılık:** E01-01, E01-02 · **Canlı risk:** `export.py`'ye yalnız yeni fonksiyon eklenir, mevcut imzalar değişmez.

### E01-16 · İş kategorisi tek sunucu fonksiyonundan (M01-07)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `TUR_KURALLARI` (tur → kategori, seri_zorunlu, onay_varsayilan) tek sabit; `ck_so_kategori`.
  - Kategori açılışta türden atanır. Yalnız `servis.kapat` sahibi gerekçeyle düzeltebilir (DUZELTME olayı).
  - Panel, liste, Excel ve uyarı `kategori` kolonuna bakar; numara ön ekine ya da metin karşılaştırmasına bakılmaz.
  - Göç betiği eski iş türlerini eşler ve eşlenemeyenleri raporlar.
- **Kabul:**
  - (1) Her `SERVIS_TURLERI` değerinin kategorisi tanımlı (unit test).
  - (2) Aynı iş panelde, listede ve Excel'de aynı kategoriyle görünüyor.
  - (3) PB işleri servis KPI'larına girmiyor.
  - (4) PLANSIZ_BAKIM GUNLUK_SERVIS sayılıyor (K9).
  - (5) Göç raporu eşlenemeyen sayısını veriyor.
- **P2 · S · Bağımlılık:** E01-02 · **Canlı risk:** yok.

### E01-17 · Cihaz başına planlı bakım iş emri (1 cihaz = 1 PB) yapısal kuralı (kullanıcı doğrulaması; E04 ile ortak)
- **Canlı:** YOK.
- **Yaklaşım:**
  - E01'de `tur='PB'`, `kategori=PLANLI_BAKIM`, `PB-` numara ön eki ve PB'ye özgü engeller tanımlanır:
    - Seri değişikliği 409.
    - Türü PB'ye veya PB'den değiştirmek 409.
  - E04 migration'ı `service_orders`'a nullable `contract_item_id`, `bakim_donemi` (YYYY-AA) ekler ve kısmi tekil indeks kurar:
    `uq_so_pb_cihaz_donem (contract_item_id, bakim_donemi) WHERE tur='PB' AND is_deleted = false`.
  - Worker görevi `pb-uretimi` (E04) `GOREVLER`'e idempotent eklenir. Çakışmada `ON CONFLICT DO NOTHING` kullanılır ve özet metni "üretilen / zaten var" sayısını döner.
  - Her PB işinde tek seri olur (kontrat kalemi = tek ekipman).
- **Kabul:**
  - (1) Aynı kontrat kalemi ve dönem için ikinci PB işi 409 / worker'da atlanıyor.
  - (2) Worker aynı turu iki kez koşunca iş sayısı değişmiyor.
  - (3) PB işinde seri değiştirme 409.
  - (4) N ekipmanlı sözleşme bir dönemde N ayrı PB işi üretiyor.
  - (5) İptal edilen PB yeniden üretilmiyor (K27).
- **P1 · S · Bağımlılık:** E01-02, E04 · **Canlı risk:** Worker'a yeni görev eklenir; mevcut görevlerin (`worker.py:120-125`) davranışı değişmez.

### E01-18 · Uyarı merkezi, görev panosu, global arama ve KVKK entegrasyonu (M01-11 kısmen, M01-18 kısmen)
- **Canlı:** KISMEN. Altyapılar VAR (`services/uyarilar.py:47`, `services/gorevler.py:47-57`, `api/search.py`, `services/kvkk.py:30`). Servis işi yok.
- **Yaklaşım:**
  - Uyarılar: `if user.has("servis.gor")` bloğu, birim kapsamıyla sayılır.
    - "Atanmamış kritik servis işi" (kritik).
    - "`servis_kapanis_bekleme_uyari_gun`'den uzun süre kapanış bekleyen iş" (uyarı).
    - "`servis_bekleme_uyari_gun`'den uzun süredir beklemede" (uyarı).
    - Her uyarının yolu `/servis-isleri?kpi=...`.
  - Görev panosu: `KAYIT_TIPLERI`'ne "servis" tipi; detayda `KayitGorevleri` bileşeni.
  - Global arama: `so_no` ve `seri_norm`, kapsamlı.
  - KVKK: hesap anonimleştirme servis iletişim ve onay alanlarını temizler; `veri_bul` servis iletişim alanlarını arar.
- **Kabul:**
  - (1) Birim A şefinin uyarı sayısında birim B işleri yok.
  - (2) `servis.gor` olmayan kullanıcı servis uyarısı görmüyor.
  - (3) Görev kartı servis işine bağlanıyor ve `/servis-isleri/{id}` adresine gidiyor.
  - (4) Arama kapsam dışı işi döndürmüyor.
  - (5) Anonimleştirme sonrası servis işinde iletişim adı ve telefonu NULL.
- **P2 · S · Bağımlılık:** E01-02, E01-14 · **Canlı risk:** `uyarilar.topla` ve `gorevler` yalnız genişletilir. Mevcut blokların sırası ve sayıları değişmez.

### E01-19 · Otomatik test paketi ve tohum verisi (M01-D05; öz: M01-12 sayı = liste)
- **Canlı:** KISMEN. Test altyapısı VAR (PG17, `_TRUNCATE`, `kullanici_ac`, FakeClock; `tests/conftest.py:41, 150-219`). CI yapılandırması depoda yok. Servis testleri YOK.
- **Yaklaşım:**
  - `tests/integration/`:
    - `test_servis_is_emirleri.py`
    - `test_servis_durum.py`
    - `test_servis_kapsam.py`
    - `test_servis_panel.py`
    - `test_servis_ekler.py`
    - `test_servis_atama.py`
    - `test_servis_excel.py`
  - `tests/unit/`:
    - `test_servis_durum_gruplari.py`
    - `test_normalize_seri.py`
    - `test_permissions.py`: yeni rollerin kapsamı `SCOPES` içinde.
  - Fixture'lar `servis_isi_ac(...)` ve `birimli_kullanici_ac(username, rol, birimler)` `conftest.py`'ye eklenir.
  - `_TRUNCATE`'e şunlar eklenir:
    - `service_fault_reasons` ve `user_units`, çünkü FK zinciri `users` üzerinden olsa da açık yazım güvenlidir.
    - `ALTER SEQUENCE service_order_no_seq RESTART`.
  - CI yapılandırması bu kapsamda değildir. Tek komut `make test` olarak kalır.
  - Senaryo sayısı ≥ 30: 403/200 matrisi her uç için, kapsam (404 + `db.refresh` ile veri değişmedi), geçiş tablosu, KPI eşitliği, mükerrer kontrolü, toplu atama atomikliği.
- **Kabul:**
  - (1) `make test` tek komutla ≥ 30 servis senaryosunu koşuyor.
  - (2) Altın kayıt (932 iş / 552.825,00 TL) yeşil.
  - (3) `test_migration_zinciri` head→base→head yeşil, tek head.
  - (4) Mevcut tüm testler yeşil.
  - (5) Her yeni uç için en az bir 403 testi var (uç listesi testten taranır).
- **P1 · M · Bağımlılık:** E01-01..E01-15 · **Canlı risk:** `conftest.py` değişikliği yalnız ekleme.

### E01-20 · İzin ayrıştırma ve teknisyen kapsamının kimliğe bağlanması: güvenlik sıkılaştırma (M01-18)
- **Canlı:** KISMEN. İzin altyapısı varsayılan RED (`api/deps.py:79-97`). Kullanıcı istisnası var (`models/rbac.py:29-52`). Servis izinleri ve iş bazlı kimlik kapsamı yok.
- **Yaklaşım:**
  - Kapatma, iptal ve yeniden açma `servis.kapat`; tamamlama `servis.tamamla`; `servis.yaz` bunları vermez (E01-03).
  - `KENDI_ISLERI` kapsamı `users.id` atama satırına bağlıdır, ada bakılmaz (K22).
  - Aynı erişim fonksiyonu (`is_erisimi_yok_mu`) detay, geçmiş, ek, onay, PDF, Excel, panel ve uyarı uçlarında kullanılır.
  - Tüm yanıtlarda iletişim telefonu K11'e göre maskelenir.
  - Uç taraması testi: `/api/teknik-servis` altındaki her `{id}` ucu kapsam dışı kullanıcıyla 404 dönmeli. Router'dan otomatik listelenir, böylece yeni uç unutulmaz.
- **Kabul:**
  - (1) Yalnız `servis.yaz` olan hesapla kapat/iptal/yeniden-aç 403.
  - (2) `KENDI_ISLERI` kullanıcısı başkasının işini liste, geçmiş, ek, PDF ve Excel uçlarında göremiyor (404 / listede yok) ve güncelleyemiyor (404 + veri değişmemiş).
  - (3) Aynı tam ada sahip iki teknisyen birbirinin işini göremiyor.
  - (4) Otomatik uç taraması testi yeşil.
  - (5) Salt okuma rolünde telefon maskeli.
- **P2 · M · Bağımlılık:** E01-01, E01-03, E01-12 · **Canlı risk:** yok. Mevcut uçlara yeni kapsam uygulanmaz.

---

## 7. İzlenebilirlik (kaynak → hedef)

| Kaynak | dotnet_specific | Hedef |
|---|---|---|
| M01-01 | hayır | E01-06 |
| M01-02 | hayır | E01-06 |
| M01-03 | hayır | E01-07 |
| M01-04 | hayır | E01-08 |
| M01-05 | hayır | E01-09 |
| M01-06 | hayır | E01-04 |
| M01-07 | hayır | E01-16 (+E01-02) |
| M01-08 | hayır | E01-13 |
| M01-09 | hayır | E01-03 |
| M01-10 | hayır | E01-12 |
| M01-11 | hayır | E01-14 (+E01-18) |
| M01-12 | **evet** | öz → E01-14 kabul (1)(3), E01-19 |
| M01-13 | **evet** | öz → E01-03 kabul (9), `planla()` sözleşmesi |
| M01-14 | hayır | E01-05 |
| M01-15 | **evet** | öz → E01-03 kabul (6), E01-04 kabul (4) |
| M01-16 | hayır | E01-10 |
| M01-17 | hayır | E01-15 |
| M01-18 | hayır | E01-20 (+E01-01) |
| M01-D01 | **evet** | öz → E01-03 (`durum_degistir(kaynak="ATOLYE")`), K13 |
| M01-D02 | **evet** | öz → E01-01 kabul (7), §3.3 özelleştirilmiş rol notu |
| M01-D03 | hayır | E01-13 |
| M01-D04 | hayır | E01-11 |
| M01-D05 | hayır | E01-19 |
| Kullanıcı doğrulaması: KPI tıklanabilir | — | E01-14 |
| Kullanıcı doğrulaması: toplu atama/plan | — | E01-12 (+E02) |
| Kullanıcı doğrulaması: Excel | — | E01-15 |
| Kullanıcı doğrulaması: cihaz başına PB | — | E01-17 (+E04) |

## 8. Uygulama sırası

1. **RBAC ve birim (E01-01).** Ardından `make test`.
2. **Çekirdek:** E01-02 (model + açılış), E01-04 (olay geçmişi), E01-03 (makine), E01-05 (bekleme), E01-06 (sonuç), E01-16 (kategori).
3. **Atama ve liste:** E01-12 (atama + toplu), E01-15 (liste + Excel), E01-14 (panel).
4. **Kayıt bütünlüğü:** E01-07 (ek), E01-09 + E01-10 (talep, mükerrer, seri), E01-11 (bağlı iş), E01-13 (düzeltme).
5. **Belge ve entegrasyon:** E01-08 (onay + PDF), E01-18 (uyarı, görev, arama, KVKK).
6. **Güvenlik:** E01-20.
7. **Sürekli:** E01-19 her adımla büyür. E01-17 ise E04 ile birlikte yapılır.

Her adım sonunda şu kapılar koşar:
- `make test` (altın kayıt dahil)
- `test_migration_zinciri`
- `ruff`
- `npm run build`
- `oxlint`

## 9. Dokunulmazlık kontrol listesi

- `work_orders`, `work_order_items`, `settlements` tablolarına ve `services/settlements.py`, `services/uyarilar.py` hak ediş bloğu, `services/reports.py` sorgularına DOKUNULMAZ. `services/reports.py:81` `"DEGISTI"` gözlemi ayrı iş olarak kayda geçer; bu modülde düzeltilmez.
- `TEKNIK_SERVIS` rolü olduğu gibi kalır; yeni roller ayrı kodla açılır.
- Cihaz durum makinesi, `device_vehicle_assignments` ve stok EXCLUDE kısıtları değişmez. `devices` yalnız okunur.
- Mevcut rollerin izin listeleri değişmez. Değişen tek şey `YONETIM`'in otomatik `.gor` genişlemesidir. `maliyet.gor` kümesi sabit kalır.
