# E10 — Operasyon Merkezi, SLA, Bekleme Nedenleri ve Uyarılar: Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21 · Hedef: Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdi: `analiz/02_moduller/_ozet/10_operasyon_sla.json` (denetçi onaylı 19 madde), `10_operasyon_sla_tasarim.md`, `10_operasyon_sla_denetim.md`, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`, kardeş tasarımlar `01_is_emirleri_entegrasyon.md` (E01), `02_planlama_entegrasyon.md` (E02), `04_planli_bakim_entegrasyon.md` (E04), `05_haberlesme_atolye_entegrasyon.md` (E05).
> Bu belge YALNIZ tasarımdır. Kaynak koda dokunulmadı. Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köklerine göredir ve 2026-10-21'de kod okunarak doğrulandı.
> Madde kimlikleri `E10-NN`; kaynak madde kimlikleri `M10-xx` olarak yazıldı.

---

## 0. Özet

- Canlı ERP'de **SLA, bekleme nedeni kataloğu, mesai takvimi, operasyon merkezi ve personel iş yükü kavramlarının hiçbiri yok.** Servis işi kavramı da yok; o E01'de (`service_orders`) kuruluyor. Bu modül E01 çekirdeğinin ÜZERİNE oturur ve yalnız onun tablolarına nullable kolon ekler.
- Buna karşılık altyapının önemli kısmı VAR ve yeniden kullanılır:
  - **Uyarı zili** her sayfada 60 saniyede bir yoklanıyor (`components/UyariZili.tsx:40-47`, `components/AppLayout.tsx:161`), sayılar sunucuda izne göre hesaplanıyor (`services/uyarilar.py:47-192`, `api/reports.py:206-230`). M10-05'in "her sayfada 60 sn rozet" kısmı canlıda zaten VAR.
  - **E-posta** gönderimi VAR (`services/mail.py:20-58`); SMTP parolası DB'de **şifreli** duruyor (`services/settings.py:26-31, 85-90`), kullanıcıda `email` kolonu VAR (`models/user.py:16`).
  - **Saat** `Clock` üzerinden okunuyor (`clock.py:14-34`, `api/deps.py:22-27`), ama **yerel saat dilimi kavramı YOK**: "bugün" her yerde `clock.now().date()` ile UTC olarak alınıyor (`api/sims.py:138`, `api/subscriptions.py:141`, `api/workorders.py:210`). Kodda `Europe/Istanbul`/`ZoneInfo` geçmiyor.
  - Worker periyodik görev koşucusu VAR (`worker.py:48-55, 108-113`), Excel VAR (`services/export.py:45-61`), denetim izi VAR (`services/audit.py:26-92`), durum makinesi VAR (`services/statemachine.py:27-83, 189-196`), ayar beyaz listesi VAR (`services/settings.py:33-91`).
- **Kalıcı bildirim kararı:** Canlı uyarı merkezi bilinçli olarak "saklanmaz, hesaplanır" (`services/uyarilar.py:9-12`). Bu ilke mevcut modüller için korunur. Yalnız SLA bildirimlerinde "görüldü", "tek kayıt / otomatik kapanma" ve "aynı bildirim için tek e-posta" kuralları kalıcı durum gerektirdiği için dar kapsamlı bir `service_alerts` tablosu açılır. Rozet yine mevcut `UyariZili` + `uyarilar.topla()` üzerinden gelir; ayrı bir zil eklenmez (karar K3).
- **Tek SLA kaynağı:** Bütün ekranlar (Operasyon Merkezi, Servis Paneli "geciken", liste, Excel, CSV, uyarı üretimi, "Benim İşlerim") `services/teknik_servis/sla.py` içindeki tek modülü kullanır. Bu modül hem Python tarafı `sla_durumu(is, simdi)` hem de SQL tarafı `sla_ifadeleri(simdi)` üretir; ikisinin aynı sonucu verdiği testle kilitlenir (M10-D03).
- 19 kaynak maddenin 1'i .NET'e özgü (`M10-D04`). Ayrı madde olarak taşınmadı, özü E10-05 ve E10-08 kabul kriterlerine eklendi.
- Kullanıcının eski sistemde bizzat doğruladığı işlevler korunuyor:
  - Tıklanabilir KPI kutuları → E10-08 (Operasyon Merkezi sayaçları tıklanır, liste aynı sorgudan gelir; E01-14 Servis Paneli'nin "geciken" kutusu E10-18 ile dolar).
  - Toplu planlama/atama → E10-08 listesinde satır seçimi E01-12 `toplu-atama` ve E02 `toplu-plan` uçlarına bağlanır; yeni toplu uç açılmaz.
  - Excel dışa aktarım → E10-07 (SLA raporu) ve E10-08 (operasyon listesi).
  - Cihaz başına PB iş emri → E10-10 (PB işleri SLA dışı, vade `maintenance_periods` üzerinden; E01-17/E04'ün `uq_so_pb_cihaz_donem` kuralına dokunulmaz).

---

## 1. Canlı karşılık taraması (kod okunarak)

| Konu | Canlıda ne var | Kanıt | Sonuç |
|---|---|---|---|
| SLA politikası / hedef | YOK | `grep sla` → yalnız analiz belgeleri | YOK |
| Mesai takvimi / resmi tatil | YOK | `grep tatil|holiday` → sonuç yok | YOK |
| Yerel saat dilimi | YOK; "bugün" UTC tarihidir | `clock.py:18-20` (`datetime.now(UTC)`), `api/sims.py:138`, `api/workorders.py:210` | YOK |
| Saat soyutlaması | VAR (`Clock`, `FakeClock`) | `clock.py:14-34`, `tests/conftest.py:157-167` | Yeniden kullan |
| Uyarı merkezi | VAR; hesaplanır, izne tabi, kalıcı tablo YOK | `services/uyarilar.py:1-17, 47-192` | Genişlet (yeni blok) |
| Her sayfada rozet | VAR; 60 sn `refetchInterval` | `components/UyariZili.tsx:40-47`, `AppLayout.tsx:161` | Yeniden kullan |
| Uyarı ucu | VAR; ayrı izin istemez | `api/reports.py:206-230` | Yeniden kullan |
| Kalıcı bildirim / görüldü | YOK (bilinçli) | `services/uyarilar.py:9-12` | Dar kapsamla yeni tablo |
| E-posta | VAR; ayar yoksa `MailKapali` | `services/mail.py:15-58` | Yeniden kullan + küçük yardımcı |
| SMTP parolası | DB'de şifreli (`SENSITIVE_KEYS`) | `services/settings.py:26-31`, `config.py:29-33` | Yeniden kullan (karar K9) |
| Kullanıcı e-postası | VAR (`users.email`, unique) | `models/user.py:16` | Yeniden kullan |
| Giden kutusu / outbox | YOK; kuyruk D10 ile ertelendi | `worker.py:6-9` | Dar kapsamla yeni tablo |
| Worker | VAR, `GOREVLER` | `worker.py:48-55, 108-113` | Genişlet |
| Excel | VAR, tek sayfa, formül enjeksiyonu korumalı | `services/export.py:26-61` | Genişlet (çok sayfa E01-15'te) |
| CSV dışa aktarım | YOK | — | Yeni küçük yardımcı |
| Ayarlar | VAR (`DEFAULTS` beyaz liste) | `services/settings.py:33-91` | Genişlet |
| İzin / rol | VAR; `operasyon.*` YOK | `permissions.py:14-77, 89-248` | Genişlet |
| Rol senkronu | VAR, idempotent; özelleştirilmiş role yeni izin inmez, log'a yazar | `seeds/dev.py:1-9, 41-90` | Yeniden kullan |
| Durum makinesi | VAR; servis makinesi E01'de | `services/statemachine.py:189-196` | E01 üzerinden |
| Bekleme (hold) | YOK; E01-05'te `service_holds` + `ck_hold_neden` olarak tasarlandı | `01_is_emirleri_entegrasyon.md` §2.5 | E10 kataloğa çevirir |
| Tekrar arıza bağı | YOK; E01-11'de `iliskili_is_id` + `iliski_turu=TEKRAR_ARIZA` tasarlandı | E01 §2.2 | E10 kural + işaret ekler |
| Zaman kaydı (sayaç) | YOK; E09'da `service_time_entries` (faaliyet YOL/ISCILIK/MOLA/BEKLEME, E05 için ATOLYE/TEST) | E02 §E02-12, E05 §19 | E10 yalnız okur |
| Plan | YOK; E02'de `service_plans` + `service_plan_members` | E02 | E10 yalnız okur |
| PB dönem vadesi | YOK; E04'te `maintenance_periods.target_date` + ayar `bakim_tolerans_gun=30` | E04 §2.3, satır 186 | E10 yalnız okur |
| Mobil saha uygulaması | YOK, kapsam dışı; ekranlar 375 px'te kullanılabilir | `permissions.py:86-88`, `AppLayout.tsx:133-137` | "Benim İşlerim" duyarlı görünüm |
| Göç betikleri | VAR (`app/migration/*.py`) | `migration/yukle_isemri.py` vb. | Emsal |
| Alembic head | `b30e012dd879` (hiçbir dosyanın `down_revision`'ı değil) | `alembic/versions/` taraması | Zincir buna bağlanır |

Sonuç: Bu modülün **iş kuralı katmanı tamamen YOK**; görüntüleme ve dağıtım altyapısı (zil, e-posta, Excel, worker, ayar, izin) VAR. Maddelerin çoğu YOK, altyapıya yaslananlar KISMEN işaretlendi. Hiçbir madde VAR değil.

---

## 2. Veri modeli

Dosya: `backend/app/models/teknik_servis.py` (E01 dosyası; büyürse `models/servis_sla.py` olarak ayrılır ve `models/__init__.py`'ye import + `__all__` eklenir). Ana tablolar `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin` alır. Değişmez kayıtlar (okundu işareti, giden kutusu satırı) yalnız `PkMixin, TimestampMixin` alır. Durum/enum alanları `String` + Türkçe tuple + adlı `CheckConstraint`.

### 2.1 `service_sla_policies` — SLA politikası (E10-01)
| Kolon | Tip | Kısıt / Not |
|---|---|---|
| oncelik | String(10) NOT NULL | `ck_slap_oncelik` IN (`ONCELIKLER` = NORMAL, YUKSEK, KRITIK) — E01 `ck_so_oncelik` ile aynı tuple |
| birim | String(20) NULL | `ck_slap_birim` IN `BIRIMLER`; NULL = tüm birimler |
| kategori | String(20) NULL | **Yer tutucu**; ilk sürümde `ck_slap_kategori_bos` (kategori IS NULL). Kategori kırılımı kullanıcı onayıyla açılır |
| cozum_saat | Numeric(6,2) NOT NULL | `ck_slap_cozum_pozitif` > 0 |
| mudahale_saat | Numeric(6,2) NULL | NULL = müdahale SLA'sı "tanımsız" |
| takvim_turu | String(10) NOT NULL default `7_24` | `ck_slap_takvim` IN (`7_24`, `MESAI`) |
| is_active | Boolean default true | |
| Tekillik | | `uq_slap_aktif` kısmi tekil (oncelik, COALESCE(birim,'*')) WHERE is_active AND NOT is_deleted |

Tohum (migration `op.bulk_insert`, sabit `VARSAYILAN_SLA_POLITIKALARI` modelde tutulur): KRITIK 12 sa, YUKSEK 24 sa, NORMAL 72 sa; `mudahale_saat` NULL; `takvim_turu=7_24`; `birim` NULL.

### 2.2 `service_work_calendar` ve `service_holidays` — mesai takvimi ve tatil (E10-02)
| Tablo | Kolonlar | Kısıt |
|---|---|---|
| `service_work_calendar` | `gun` SmallInteger (0=Pzt…6=Paz), `baslangic` Time, `bitis` Time, `ogle_baslangic` Time NULL, `ogle_bitis` Time NULL, `is_active` | `uq_swc_gun` (gun); `ck_swc_aralik` bitis > baslangic; `ck_swc_ogle` (ikisi birlikte NULL ya da baslangic ≤ ogle_baslangic < ogle_bitis ≤ bitis) |
| `service_holidays` | `tarih` Date, `ad` String(80), `yarim_gun` Boolean default false (ikinci aşama; ilk sürümde `ck_sh_yarim_gun_yok` NOT yarim_gun) | `uq_sh_tarih` kısmi tekil (tarih) WHERE NOT is_deleted |

Tohum: Pzt–Cum 08:30–17:30, öğle arası yok. Tatil tohumu YAZILMAZ (uydurma veri yok); yönetici girer.

### 2.3 `service_hold_reasons` — bekleme nedeni kataloğu (E10-03; E01-05 bunu kullanır)
| Kolon | Not |
|---|---|
| kod | String(30) NOT NULL, `uq_shr_kod`; değişmez kimlik |
| ad | String(80) |
| sla_durdurur | Boolean NOT NULL |
| aciklama_zorunlu | Boolean default false |
| sadece_sistem | Boolean default false (ör. `BAKIM_UYGUNSUZLUK`; ekrandan seçilemez, yalnız servis fonksiyonu açar) |
| sira, is_active | |

Tohum (`VARSAYILAN_BEKLEME_NEDENLERI`): MALZEME (durdurmaz), MUSTERI_ONAYI (durdurur), TEKLIF (durdurur), MUSTERI_ERISIMI (durdurur), PERSONEL (durdurmaz), BAKIM_UYGUNSUZLUK (durdurmaz, sadece_sistem), DIGER (durdurmaz, aciklama_zorunlu).

**E01 ile uyum:** E01 §2.5'teki `ck_hold_neden` CHECK'i yerine `service_holds.neden` → `service_hold_reasons.kod` FK (RESTRICT) kullanılır. E01 henüz kodlanmadığı için değişiklik E01 migration'ına doğrudan yazılır; kodlanmışsa E10 migration'ı yalnız bu yeni tabloyu açar, CHECK'i düşürür ve FK'yı ekler (tablo yeni, canlı mobilite verisi yok). E04'ün kullandığı `UYGUNSUZLUK` kodu `BAKIM_UYGUNSUZLUK` olarak hizalanır (karar K6).

### 2.4 `service_holds` üzerine eklenen kolonlar (E01 tablosu)
| Kolon | Not |
|---|---|
| beklenen_bitis_at | timestamptz NULL; açılışta `clock.now()`'dan eski olamaz (servis 400) |
| sla_durdurur | Boolean NOT NULL; açılışta katalogdan **dondurulur** (katalog sonradan değişse de geçmiş değişmez) |
| sure_dk | Integer NULL; kapanışta duvar saati dakikası. `ck_hold_sure` (released_at IS NULL) = (sure_dk IS NULL) |
| sla_kayma_dk | Integer NULL; kapanışta takvime göre hesaplanan SLA kayması (durdurmayan nedende 0) |
| kapanis_notu | String(200) NULL; otomatik kapanışta "otomatik: durum değişti" |
| otomatik_kapandi | Boolean default false |

### 2.5 `service_orders` üzerine eklenen nullable kolonlar (E01 tablosu; E01 §2.2'de "E10: sla_due_at" diye ayrılan yer)
| Kolon | Not |
|---|---|
| sla_policy_id | FK service_sla_policies RESTRICT NULL. PB işinde NULL (`ck_so_pb_sla`: tur='PB' ise NULL) |
| sla_baslangic_at | timestamptz NULL; = açılış anı (`created_at`, karar K1) |
| cozum_hedef_dk / mudahale_hedef_dk | Integer NULL; politikadan dondurulan dakika |
| sla_takvim_turu | String(10) NULL; politikadan dondurulur, `ck_so_sla_takvim` |
| cozum_hedef_ilk_at | timestamptz NULL; açılışta damgalanan ilk hedef, bir daha değişmez |
| cozum_hedef_at | timestamptz NULL; güncel hedef (yalnız SLA durduran bekleme bitince ve öncelik düzeltmesinde ileri alınır, her değişim olay geçmişine yazılır) |
| mudahale_hedef_at | timestamptz NULL; politika tanımsızsa NULL |
| ilk_mudahale_at | timestamptz NULL; FirstResponseAt (§E10-01) |
| ilk_yola_cikis_at | timestamptz NULL; bilgi amaçlı, SLA'yı karşılamaz |
| sla_sonuc | String(12) NULL; `ck_so_sla_sonuc` IN (ZAMANINDA, ASILDI, OLCULEMEDI); TAMAMLANDI anında dondurulur, TEKRAR_ACILDI'da NULL |
| sla_durdurulan_dk | Integer NULL; TAMAMLANDI anındaki toplam `sla_kayma_dk` |
| sla_kaynak | String(14) NULL; `ck_so_sla_kaynak` IN (CANLI, GERIYE_DONUK) |
| gecikme_nedeni | String(30) NULL; `ck_so_gecikme_neden` IN `GECIKME_NEDENLERI` (MALZEME_TEDARIK, MUSTERI_KAYNAKLI, ULASIM, PERSONEL_YETERSIZ, YOGUNLUK, TEKNIK_ZORLUK, DIGER) |
| gecikme_aciklama | String(300) NULL; `ck_so_gecikme_diger`: gecikme_nedeni='DIGER' ise NOT NULL |
| tekrar_ariza_aday | Boolean NOT NULL server_default false |
| tekrar_ariza_teyit | String(20) NULL; `ck_so_tekrar_teyit` IN (AYNI_ARIZA, FARKLI_ARIZA, KULLANICI_HATASI) |
| İndeksler | `ix_so_sla_hedef` (cozum_hedef_at) WHERE status NOT IN ('TAMAMLANDI','KAPATILDI','IPTAL') AND NOT is_deleted; `ix_so_tekrar_aday` (tekrar_ariza_aday) WHERE tekrar_ariza_aday |

### 2.6 `service_alerts`, `service_alert_reads` — kalıcı SLA bildirimi (E10-05)
| Tablo | Kolonlar | Kısıt |
|---|---|---|
| `service_alerts` (`PkMixin, TimestampMixin`; yumuşak silme YOK, temizlik worker'da) | `kod` String(30), `service_order_id` FK CASCADE, `birim` String(20) (denormalize, rozet sorgusu iş tablosunu okumasın), `customer_id` (denormalize), `onem` (`ck_salert_onem` IN bilgi/uyari/kritik), `baslik` String(200), `acilis_at`, `kapanis_at` NULL, `kapanis_nedeni` String(30) NULL | `ck_salert_kod` IN `UYARI_KODLARI` (SLA_RISK, SLA_ASILDI, MUDAHALE_ASILDI, BEKLEME_BITIS_GECTI, PB_VADE_GECTI, KRITIK_ATANMAMIS); **`uq_salert_acik`** kısmi tekil (kod, service_order_id) WHERE kapanis_at IS NULL; `ix_salert_acik_birim` (birim) WHERE kapanis_at IS NULL |
| `service_alert_reads` | `alert_id` FK CASCADE, `user_id` FK users CASCADE, `goruldu_at` | PK (alert_id, user_id) — "görüldü" tek INSERT … ON CONFLICT DO NOTHING |

Alıcı listesi SAKLANMAZ; okuma anında `servis.gor` izni + E01 kapsam yardımcıları (`kapsam_musteri`, `kapsam_birim`, `kapsam_kendi_isleri`) ile hesaplanır. Böylece rol/birim değişikliği geçmiş bildirimlerde de doğru uygulanır (karar K4).

### 2.7 `service_notification_prefs` ve `service_mail_outbox` — e-posta (E10-06, ikinci aşama)
| Tablo | Kolonlar | Kısıt |
|---|---|---|
| `service_notification_prefs` | `user_id` PK FK users CASCADE, `anlik_eposta` Boolean default false, `gunluk_ozet` Boolean default false, `updated_at` | — |
| `service_mail_outbox` (`PkMixin, TimestampMixin`) | `tur` (`ck_smo_tur` IN ANLIK, GUNLUK_OZET), `alert_id` FK SET NULL NULL, `user_id` FK CASCADE, `ozet_gunu` Date NULL, `alici` String(160), `konu`, `govde` Text, `durum` (`ck_smo_durum` IN BEKLIYOR, GONDERILDI, BASARISIZ), `deneme` SmallInteger default 0, `son_hata` String(300), `gonderildi_at` | `uq_smo_anlik` kısmi tekil (alert_id, user_id) WHERE tur='ANLIK'; `uq_smo_ozet` kısmi tekil (user_id, ozet_gunu) WHERE tur='GUNLUK_OZET'; `ck_smo_deneme` deneme BETWEEN 0 AND 10 |

`son_hata` alanına SMTP parolası ya da kullanıcı adı yazılmaz; `mail.py`'nin hata metninden yalnız istisna sınıf adı ve sunucu:port alınır (E10-06 kabul 4).

### 2.8 Genişletilen mevcut yapılar (yalnız ekleme)
- `app/clock.py`: mevcut sınıflara DOKUNULMAZ; dosya sonuna saf yardımcılar eklenir: `YEREL_TZ = ZoneInfo("Europe/Istanbul")`, `yerel(an)`, `yerel_bugun(clock)`, `yerel_gun_araligi(gun) -> (utc_bas, utc_bit)`. Bağımlılık: `pyproject.toml`'a `tzdata` (Windows ve slim imajda IANA veritabanı garanti olsun). Mevcut modüllerin UTC "bugün" kullanımı değiştirilmez (gözlem olarak §9'a yazıldı).
- `permissions.py`: `operasyon.gor`, `operasyon.yonet` (§3).
- `services/settings.py` `DEFAULTS` (yeni "Teknik servis — SLA/operasyon" bloğu):
  - `servis_sla_risk_yuzde: 80` — hedef süresinin %80'i dolunca RISKTE.
  - `servis_tekrar_ariza_gun: 30`.
  - `servis_uyari_uretimi_acik: True`.
  - `servis_uyari_saklama_gun: 90`.
  - `servis_eposta_acik: False` (SMTP hazır olunca açılır).
  - `servis_eposta_deneme: 3`.
  - `servis_gunluk_ozet_saati: "07:30"` (İstanbul).
  - `bakim_tolerans_gun` E04'e aittir; E10 yalnız okur.
- `services/uyarilar.py:47` `topla()` → `if user.has("servis.gor"):` bloğuna (E01-18) SLA satırları eklenir: açık `service_alerts` kod bazında `COUNT`, kapsamla süzülmüş. Mevcut blokların sırası ve sayıları değişmez.
- `services/mail.py`: yeni saf yardımcı `yapilandirildi_mi(ayarlar) -> bool` (mevcut `gonder` imzası değişmez).
- `services/export.py`: yeni `satirlari_csv(basliklar, satirlar) -> bytes` (UTF-8 BOM, `;` ayraç, `=+-@` ile başlayan hücre başına `'` — CSV'de formül enjeksiyonunu kesmenin tek yolu budur; xlsx'teki `_formulu_metne_cevir` CSV'de uygulanamaz).
- `worker.py` `GOREVLER`: üç yeni görev (§E10-05, E10-06).
- `services/teknik_servis/` alt paketi (E01 emsali): `sla.py`, `sla_takvim.py`, `operasyon.py`, `uyari_uretimi.py`, `eposta.py`, `tekrar_ariza.py`; `raporlar.py`'ye `sla_raporu`.

### 2.9 Migration'lar
Zincir E01/E02/E04 migration'larının ardından gelir (kodlama başında `alembic heads` ile doğrulanır; bugünkü canlı head `b30e012dd879`).
1. `make makemigration m="servis_sla_temel"`:
   - `service_sla_policies`, `service_work_calendar`, `service_holidays`, `service_hold_reasons` + `op.bulk_insert` tohumları.
   - `service_orders` nullable kolonları, CHECK'leri ve kısmi indeksleri.
   - `service_holds` kolonları; `ck_hold_neden` varsa `op.drop_constraint` + `fk_service_holds_neden` (`op.create_foreign_key`); tohumdan sonra eklenir ki mevcut satırlar (varsa) geçerli olsun.
   - Docstring: NEDEN (hedef damgası, katalog, takvim) + bedel (geriye dönük hedef "güncel hedef"tir).
   - Downgrade: FK → CHECK geri, kolonlar, tablolar (FK sırası), tohum satırları.
2. `make makemigration m="servis_uyari_bildirim"`: `service_alerts`, `service_alert_reads`, `service_notification_prefs`, `service_mail_outbox`.
3. Canlı tablolarda (`work_orders`, `work_order_items`, `settlements`, `devices`, `stock_*`, `users`, `settings`) hiçbir kolon, CHECK ya da EXCLUDE değişmez.
4. head→base→head testi (`tests/migration/test_migration_zinciri.py`) ve tek head kuralı.

---

## 3. İzinler, roller, kapsam

### 3.1 Yeni izin kodları (`permissions.py` `PERMISSIONS`, modül "Teknik Servis")
| Kod | Açıklama |
|---|---|
| `operasyon.gor` | Operasyon Merkezi'ni (sayaçlar, SLA sıralı liste, personel iş yükü) görür. Uçlar `operasyon.gor` + `servis.gor` birlikte ister |
| `operasyon.yonet` | SLA politikası, mesai takvimi, resmi tatil ve bekleme nedeni kataloğunu düzenler |

- SLA raporu yeni izin açmaz: ekran `servis.gor` + `rapor.gor`, Excel/CSV ayrıca `rapor.disaaktar`.
- Bildirim listesi ve "görüldü" `servis.gor` ister; kapsam E01 yardımcılarıyla.
- Bu modülde fiyat/maliyet alanı YOKTUR; `maliyet.gor` kümesi değişmez.

### 3.2 Rol dağılımı (yalnız E01'de tanımlanan YENİ servis rolleri genişler; mevcut roller değişmez)
| Rol | operasyon.gor | operasyon.yonet |
|---|---|---|
| SERVIS_YONETICI | ✔ | ✔ |
| SERVIS_SEF | ✔ | — |
| SERVIS_OPERASYON | ✔ | — |
| SERVIS_TEKNISYEN | — | — |
| ATOLYE | — | — |
| YONETIM | ✔ (otomatik `.gor`, `permissions.py:84, 247`) | — |
| ADMIN | ✔ | ✔ |

`TEKNIK_SERVIS` (mobilite montaj/onay rolü) DEĞİŞMEZ. `ozellestirildi=True` DB rollerine yeni izin inmez; `seeds/dev.py` bunu log'a "eksik izin" olarak yazar (`seeds/dev.py:58-72`). Bu satır M10-14'ün "önizleme" şartının canlı karşılığıdır (karar K12).

### 3.3 Kapsam
Bütün E10 uçları E01'in `kapsam_musteri` + `kapsam_birim` + `kapsam_kendi_isleri` zincirini uygular. Operasyon sayaçları, liste, personel iş yükü, uyarı sayısı, rapor, Excel ve CSV aynı süzgeçten geçer; "sayı = sızıntı" kuralı (`services/uyarilar.py:14-17`) servis bildirimlerinde de geçerlidir.

---

## 4. SLA çekirdeği: `services/teknik_servis/sla.py`

### 4.1 Durum değerleri (`SLA_DURUMLARI`)
`ZAMANINDA`, `RISKTE`, `ASILDI`, `DURDURULDU`, `KARSILANDI` (kapalı, zamanında), `KARSILANMADI` (kapalı, geç), `OLCULEMEDI`, `SLA_DISI_PB`.

### 4.2 Fonksiyonlar
| Fonksiyon | Görev |
|---|---|
| `politika_bul(db, oncelik, birim)` | Önce birim+öncelik, yoksa öncelik (birim NULL) aktif politika; yoksa `ServisIsiHatasi` (açılış 409 "SLA politikası tanımsız") |
| `damgala(db, so, clock)` | Açılışta (E01 `olustur`) çağrılır: politika, `sla_baslangic_at`, dakikalar, takvim türü, `cozum_hedef_ilk_at = cozum_hedef_at`, `mudahale_hedef_at`; PB'de hiçbir şey yazmaz |
| `yeniden_damgala(db, so, clock, user_id)` | E01-13 öncelik düzeltmesinde: yeni politika, hedef `sla_baslangic_at`'ten yeniden hesaplanır + biriken `sla_kayma_dk` eklenir; DUZELTME olayı eski/yeni hedefle; `audit.log_change` |
| `bekleme_kapandi(db, so, hold, clock)` | `sla_durdurur` ise `sla_kayma_dk = takvim_dakika(hold.started_at, hold.released_at)`; `cozum_hedef_at = is_saati_ekle(cozum_hedef_at, kayma)`; `ilk_mudahale_at` NULL ise müdahale hedefi de kayar; olay "SLA hedefi X → Y (bekleme: neden)" |
| `ilk_mudahale_isle(db, so, an, kaynak)` | İlk çağrıda `ilk_mudahale_at` yazar; sonraki çağrılar etkisiz. Kaynaklar: E09 zaman kaydı başlangıcı (faaliyet ∉ {YOL, MOLA, BEKLEME}), durum geçişi SAHADA/ISLEMDE/ATOLYEDE, açılışta çözüldü (TELEFON/UZAKTAN) sonucu |
| `yola_cikis_isle(db, so, an)` | YOL faaliyeti ya da YOLA_CIKILDI durumu; yalnız bilgi |
| `cozum_sonucu_dondur(so, an)` | `durum_degistir` TAMAMLANDI'da: `sla_sonuc` = ZAMANINDA / ASILDI (completed_at > cozum_hedef_at) / OLCULEMEDI (hedef NULL); `sla_durdurulan_dk` |
| `sla_durumu(so, aktif_bekleme, simdi, risk_yuzde) -> SlaDurumu` | Python tarafı tek hesap: {durum, hedef_at, kalan_dk, mudahale_durumu, vade (PB)} |
| `sla_ifadeleri(simdi, risk_yuzde)` | SQL tarafı: `durum_ifadesi` (CASE), `kalan_dk_ifadesi`, `siralama_ifadesi`; liste, sayaç, Excel ve uyarı üretimi bunu kullanır |

**Kalan süre (açık iş):** `kalan = cozum_hedef_at − simdi`; SLA durduran aktif bekleme varsa durum DURDURULDU ve `kalan = cozum_hedef_at − hold.started_at` (donmuş). RISKTE: geçen süre ≥ `risk_yuzde` × (`cozum_hedef_at − sla_baslangic_at`). MESAI türünde RISKTE eşiği duvar saatiyle ölçülür, hedefin kendisi takvimle hesaplanır (karar K7).
**Tutarlılık testi:** 40 rastgele işlik veri setinde her iş için `sla_durumu()` ile SQL `durum_ifadesi` aynı değeri vermeli (`tests/unit` değil, PG gerektiği için `tests/integration/test_servis_sla_tutarlilik.py`).

### 4.3 Takvim: `services/teknik_servis/sla_takvim.py` (saf fonksiyonlar, DB'siz test edilir)
- `is_saati_ekle(baslangic_utc, dakika, takvim, tatiller, tur) -> datetime`: `7_24` için `baslangic + dakika`; `MESAI` için İstanbul yerel saatinde gün gün ilerler, mesai dışını, öğle arasını ve tatili atlar.
- `takvim_dakika(bas_utc, bit_utc, takvim, tatiller, tur) -> int`: aralıktaki çalışılan dakika.
- Takvim ve tatiller servis fonksiyonu girişinde bir kez okunup değer nesnesi (`Takvim`) olarak geçirilir.

---

## 5. Kararlar (kullanıcıya soru sorulmadı)

- **K1 SLA başlangıcı = kaydın açıldığı an.** `reported_at` (E01) bilgi alanı olarak kalır. *Gerekçe:* `reported_at` elle girilir ve geriye 7 güne kadar uzanabilir (E01-09); SLA'yı elle girilen alana bağlamak hem manipülasyona hem de "açılır açılmaz aşılmış" işlere yol açar.
- **K2 SLA değerleri.** Tohum: KRITIK 12 / YUKSEK 24 / NORMAL 72 saat çözüm, müdahale hedefi tanımsız (NULL), takvim 7/24. *Gerekçe:* eski sistemde fiilen uygulanan değerler bunlar; kullanıcı değer vermedi. Müdahale hedefi uydurulmaz; ekran "tanımsız" gösterir. `DUSUK` önceliği EKLENMEZ (E01 `ck_so_oncelik` üç değer; eski formda da yoktu).
- **K3 Kalıcı bildirim yalnız SLA için.** Canlının "uyarılar hesaplanır" ilkesi (`services/uyarilar.py:9-12`) bozulmaz. `service_alerts` yalnız servis işine bağlı, koşul bazlı ve worker'ın ürettiği SLA bildirimlerini tutar. Rozet mevcut `UyariZili`'dir; ikinci zil eklenmez.
- **K4 Alıcı saklanmaz.** Bildirim kime gideceğini okuma anında izin + kapsamla bulur. Kademeli eskalasyon (şef → müdür) organizasyon şeması gelene kadar AÇILMAZ; yer olarak `UYARI_KODLARI` ile `onem` yeterlidir.
- **K5 Uzun açık sayaç uyarısı E09'a aittir** (M09-05); burada yeniden tanımlanmaz.
- **K6 Bekleme kataloğu tablo, CHECK değil.** SLA durdurma bayrağı ve pasifleştirme gerektiği için E01'deki `ck_hold_neden` tablo + FK'ya çevrilir. E04'teki `UYGUNSUZLUK` kodu `BAKIM_UYGUNSUZLUK` olarak hizalanır. SLA durduran nedenler: MUSTERI_ONAYI, TEKLIF, MUSTERI_ERISIMI. MALZEME ve PERSONEL Denge'nin kendi sorumluluğundadır, durdurmaz.
- **K7 Risk eşiği duvar saatiyle.** RISKTE eşiği (%80) SQL'de ucuz hesaplanabilsin diye duvar saatiyle ölçülür; hedefin kendisi takvimle hesaplanır. Fark yalnız MESAI politikasında ve yalnız "risk" uyarısının birkaç saat erken çıkmasıdır; ASILDI kararı her zaman kesindir.
- **K8 Hedef ileri alınır, yeniden hesaplanmaz.** Durduran bekleme bitince kayma o andaki takvimle hesaplanıp `cozum_hedef_at`'e eklenir ve olay geçmişine yazılır. Takvim ya da tatil sonradan değişse de damgalı hedefler değişmez (M10-02 kabul 4).
- **K9 SMTP parolası.** Kabul kriteri "yalnız ortam değişkeninde" diyor; canlıda SMTP parolası `settings` tablosunda **şifreli** saklanıyor ve arayüze maskeli dönüyor (`services/settings.py:26-31`, `config.py:29-33`). Özü (düz metin DB'de ve log'da yok) sağlandığı için canlı mekanizma kullanılır; ikinci bir yapılandırma yolu açılmaz.
- **K10 Gecikme nedeni ve tekrar arıza teyidi KAPATILDI adımında** (şef, `servis.kapat`). TAMAMLANDI'da isteğe bağlı alınır, teknisyen bloke edilmez.
- **K11 Tekrar arıza.** Pencere 30 gün (ayar). Eşleşme E01 `seri_norm` ile (TRIM + büyük harf + iç boşluk teke; tire ve baştaki sıfır korunur). PB işleri ne tetikler ne tetiklenir. Eşleşme varsa ve iş henüz bağlı değilse `iliskili_is_id` en son kapanan eşleşen işe `TEKRAR_ARIZA` olarak bağlanır; iş zaten bağlıysa yalnız `tekrar_ariza_aday=true` yazılır ve eşleşen işler olay verisine eklenir.
- **K12 İzin dağıtımı.** Ayrı bir "izin dağıtım betiği" yazılmaz; canlı `seeds/dev.py` zaten idempotent ve özelleştirilmiş rollere dokunmadan eksik izinleri log'a yazıyor. Kurulum notunda bu log satırının okunup elle ekleme yapılması adımı yer alır.
- **K13 Öncelik hatası 422.** Kabul "400" diyor; canlıda girdi biçimi hataları Pydantic ile 422 döner (E01 kararıyla aynı). Doğrulayıcı büyük/küçük harfi normalleştirir: "kritik" → KRITIK; katalog dışı ("Acil") → 422.
- **K14 PB vadesi = `target_date + bakim_tolerans_gun`.** E04'ün uyum/gecikme tanımıyla aynı kaynak kullanılır; ayrı bir "ay sonu" kuralı açılmaz. Ekranda "Vade: Ekim 2026" `target_date`'in ayıdır.
- **K15 Operasyon Merkezi ayrı sayfa, aynı KPI kaydı.** Sayaçlar E01-14'ün `KPI_TANIMLARI` kaydına eklenir; Servis Paneli'nin "geciken" kutusu E10'un `sla_asildi` tanımını kullanır. İki ekran aynı sayıyı verir.
- **K16 Mobil = duyarlı "Benim İşlerim".** Canlıda mobil uygulama kapsam dışı (`permissions.py:86-88`). M10-D01, 375 px'te çalışan liste görünümüyle karşılanır.
- **K17 CSV.** Genişletilmiş CSV, Excel'in "İşler" sayfasıyla aynı satır üretecinden çıkar; ayrı sorgu yazılmaz.
- **K18 Ölçülemedi.** Hedefi olmayan (göç, politika yok) ya da TAMAMLANDI zamanı bilinmeyen kapalı iş OLCULEMEDI'dir; uyum oranının paydasına girmez, raporda ayrı satırdır. "Süre kaydı eksik" (E09) bundan ayrı bir bayraktır.
- **K19 sla_durumu önceliği P1'e yükseltildi.** Kaynakta P2; ancak E10-01, E10-08, E10-10 ve E01-14 "geciken" kutusu buna dayandığı için çekirdekle birlikte yapılır.
- **K20 Hata kodları canlı kalıbında.** Kural ihlali (ör. gecikme nedenisiz kapatma, kök neden yokken kapatma) 409; girdi hatası (ör. geçmiş tarihli beklenen bitiş) 400; şema dışı değer 422.
- **K21 Yerel saat yardımcısı `clock.py`'de.** M09-12 ile ortak; mevcut UTC "bugün" kullanımları bu modülde düzeltilmez (mobilite davranışı değişmesin).

---

## 6. Maddeler

### E10-01 · SLA politikası, işe damgalanan hedef, ilk müdahale, tekrar açılma ve gecikme nedeni (M10-01)
- **Canlı:** YOK. SLA kavramı yok; servis işi E01'de kuruluyor.
- **Yaklaşım:**
  - Tablo `service_sla_policies` (§2.1), `service_orders` SLA kolonları (§2.5).
  - `sla.damgala()` E01 `olustur()` içinde, `yeniden_damgala()` E01-13 öncelik düzeltmesinde, `cozum_sonucu_dondur()` E01 `durum_degistir(TAMAMLANDI)` içinde çağrılır. TEKRAR_ACILDI'da `sla_sonuc`, `sla_durdurulan_dk` NULL; `completed_at` E01 gereği zaten NULL; hedef aynı kalır.
  - `ilk_mudahale_isle()` E09 zaman kaydı başlatma ucu, E01 durum geçişi (SAHADA/ISLEMDE/ATOLYEDE) ve açılışta çözüldü kısa yolundan çağrılır.
  - E01 `POST /isler/{id}/kapat` gövdesine `gecikme_nedeni`, `gecikme_aciklama` eklenir: `sla_sonuc='ASILDI'` ve neden yoksa 409.
  - Tanım uçları (`/api/teknik-servis/tanimlar/sla-politikalari`): GET (`servis.gor`), POST/PATCH (`operasyon.yonet`, `version`, 409). Değişiklik `audit.log_change(..., "sla.politika.degistir")` ile eski/yeni değer.
  - Detay çıktısı (`_cikti`) `sla` bloğu döner: durum, hedef, kalan dk, müdahale durumu, ilk/güncel hedef, durdurulan dk.
  - Ön yüz: Servis işi Drawer'ında "SLA" kartı (durum `Tag`, kalan süre, hedef `DD.MM.YYYY HH:mm`); kapatma penceresinde gecikme nedeni `Select` (yalnız aşılmış işte zorunlu).
- **Kabul:**
  - (1) KRITIK iş açılınca `cozum_hedef_at = sla_baslangic_at + 12 sa` (FakeClock).
  - (2) Politika 12→8 yapılınca eski işin `cozum_hedef_at`'i değişmez; yeni iş 8 sa alır.
  - (3) İlk ISCILIK/ATOLYE sayacı `ilk_mudahale_at`'i doldurur; YOL, BEKLEME, MOLA doldurmaz; ikinci sayaç değiştirmez.
  - (4) Hedef geçmiş işte gecikme nedenisiz KAPATILDI 409; TAMAMLANDI 200.
  - (5) Öncelik NORMAL→KRITIK düzeltmesi hedefi yeniden hesaplar, geçmişte eski/yeni hedef var.
  - (6) Politika değişikliği denetim kaydında kullanıcı, eski ve yeni değerle.
  - (7) TEKRAR_ACILDI sonrası `sla_sonuc` NULL, `cozum_hedef_ilk_at` değişmemiş.
  - (8) PB işinde `sla_policy_id` NULL (`ck_so_pb_sla`).
  - (9) Aktif politika yokken açılış 409 "SLA politikası tanımsız".
- **P1 · M · Bağımlılık:** E01-02, E01-03, E01-13, E09 (ilk müdahale için; yoksa yalnız durum geçişi kaynak olur), E10-12, E10-18 · **Canlı risk:** yok; yalnız yeni tablo ve E01'in yeni tablolarına kolon.

### E10-02 · Ortak mesai takvimi, öğle arası, resmi tatil; politika bazında takvim türü (M10-02)
- **Canlı:** YOK.
- **Yaklaşım:**
  - Tablolar `service_work_calendar`, `service_holidays` (§2.2); `sla_takvim.py` saf fonksiyonları (§4.3).
  - Uçlar: `GET/PUT /tanimlar/mesai-takvimi` (7 satırı tek istekte, `operasyon.yonet`), `GET/POST/DELETE /tanimlar/tatiller` (silme yumuşak). Her değişiklik `audit.log`.
  - Politika `takvim_turu=MESAI` ise `damgala` ve `bekleme_kapandi` takvimi kullanır.
  - Ön yüz: `ServisTanimlarPage` "Mesai Takvimi" sekmesi (gün satırları `TimePicker`) ve "Resmî Tatiller" sekmesi (`DatePicker`, `DD.MM.YYYY`).
  - Yarım gün (`yarim_gun`) ikinci aşamadır; kolon var, CHECK ile kapalı.
- **Kabul:**
  - (1) Pzt–Cum 08:30–17:30 (öğle yok), Cuma 16:30 açılan 8 saatlik işin hedefi Pazartesi 15:30; 12:30–13:30 öğle arasıyla Pazartesi 16:30.
  - (2) 29 Ekim tatil tanımlıysa o gün sayılmaz.
  - (3) 7/24 politika takvimden etkilenmez.
  - (4) Takvim/tatil değişikliği denetimde; damgalı hedefler değişmez.
  - (5) `tests/unit/test_sla_takvim.py` ≥ 6 senaryo: hafta sonu, mesai dışı açılış, tatil, yılbaşı devri, öğle arası, durduran bekleme kayması; tümü İstanbul saatiyle (UTC+3) ve DB'siz.
- **P2 · M · Bağımlılık:** E10-01, E10-12 · **Canlı risk:** yok.

### E10-03 · Bekleme nedeni kataloğu, SLA durdurma bayrağı, beklenen bitiş, form tabanlı giriş (M10-03)
- **Canlı:** YOK. E01-05 bekleme akışını sabit CHECK listesiyle tasarladı.
- **Yaklaşım:**
  - `service_hold_reasons` tablosu ve tohum (§2.3); `service_holds` ek kolonları (§2.4); `ck_hold_neden` → FK.
  - E01 `bekletme.beklet()` girişinde: neden aktif ve `sadece_sistem=false` olmalı (değilse 400), `aciklama_zorunlu` ise açıklama, `beklenen_bitis_at` ≥ şimdi (400), `sla_durdurur` katalogdan dondurulur.
  - `beklemeyi_bitir()`: `sure_dk` ve `sla_kayma_dk` yazılır, `sla.bekleme_kapandi()` çağrılır.
  - Teknisyen yalnız kendi işini bekletebilir: E01 `KENDI_ISLERI` kapsamı yazma için aktif atama ister; ayrı kod yazılmaz, test edilir.
  - Tanım uçları `GET/POST/PATCH /tanimlar/bekleme-nedenleri` (GET `servis.gor`, yazma `operasyon.yonet`); `kod` değiştirilemez; pasifleştirme yeni beklemede seçimi engeller, eski kayıtlar korunur.
  - Ön yüz: Bekletme penceresi (`Select` yalnız aktif ve sistem dışı nedenler; neden `sla_durdurur` ise "SLA durur" etiketi; `DatePicker` beklenen bitiş); `prompt()` yok. `ServisTanimlarPage` "Bekleme Nedenleri" sekmesi.
- **Kabul:**
  - (1) Katalog dışı neden 400 (servis) / FK ihlali 409 (`fk_` mesajı).
  - (2) MUSTERI_ONAYI ile 3 saat bekleyen 7/24 işin hedefi 3 saat ileri kayar; MALZEME ile kaymaz.
  - (3) Geçmiş tarihli beklenen bitiş 400.
  - (4) Kapanışta `sure_dk` dakika olarak dolu.
  - (5) Pasif neden yeni beklemede 400; eski beklemenin nedeni görünmeye devam eder.
  - (6) `KENDI_ISLERI` teknisyeni başkasının işini bekletmeye çalışınca 404 ve iş değişmemiş.
  - (7) BAKIM_UYGUNSUZLUK ekrandan seçilemez (400).
- **P2 · M · Bağımlılık:** E01-05, E10-01 · **Canlı risk:** yok.

### E10-04 · Tekrar arıza: otomatik işaret, çoklu seri eşleşmesi, kök neden teyidi KAPATILDI'da (M10-04)
- **Canlı:** YOK. E01-11 bağ alanlarını (`iliskili_is_id`, `iliski_turu=TEKRAR_ARIZA`) ve E01-10 `seri_norm`'u tasarladı.
- **Yaklaşım:**
  - `tekrar_ariza.py:adaylari_bul(db, so, clock, gun)`: yeni işin aktif `service_order_serials.seri_norm` değerlerinden HERHANGİ BİRİ, son N gün içinde `closed_at` almış (KAPATILDI), `tur<>'PB'` başka bir işle eşleşirse aday listesi döner.
  - E01 `olustur()` sonunda çağrılır (PB'de çağrılmaz); K11'e göre bağ kurulur, `tekrar_ariza_aday=true`, BAGLANTI olayı. E01-13 seri değişikliğinde yeniden değerlendirilir (yalnız işaret ekler, kaldırmaz).
  - E01 kapatma ucu: `tekrar_ariza_aday` ise `tekrar_ariza_teyit` zorunlu (409) ve E01 `service_results.ariza_nedeni_id` dolu olmalı (409 "kök neden seçin").
  - Liste filtresi `?tekrar_ariza=1`; E01-14 "30 gün içinde tekrar arıza" KPI'sı bu bayrağı sayar.
- **Kabul:**
  - (1) 'ab-001 ' seriyle açılan iş, 20 gün önce kapanan 'AB-001' işine bağlanır; 45 gün önceki işe bağlanmaz.
  - (2) '0AB001' ile 'AB-001' eşleşmez.
  - (3) İki serili yeni işte yalnız ikinci seri eşleşse de iş işaretlenir.
  - (4) PB işi ne işaretlenir ne de başka işi işaretler.
  - (5) İşaretli iş teyit ve kök neden olmadan KAPATILDI 409; TAMAMLANDI 200.
  - (6) Kapsam dışı birimdeki eski iş eşleşirse bağ kurulur ama yanıtta yalnız "başka birimde kayıt var" yazar (numara sızmaz; E01-09 kalıbı).
- **P2 · M · Bağımlılık:** E01-10, E01-11, E01-03 · **Canlı risk:** yok.

### E10-05 · Kalıcı SLA bildirimi, 5 dakikalık üretim, izin+birim bazlı görünürlük, her sayfada rozet (M10-05; öz: M10-D04)
- **Canlı:** KISMEN. Rozet her sayfada 60 sn'de yoklanıyor (`UyariZili.tsx:40-47`), sayılar izne göre sunucuda hesaplanıyor (`uyarilar.py:47`). Kalıcı kayıt, görüldü, otomatik kapanma ve 5 dakikalık üretim YOK.
- **Yaklaşım:**
  - Tablolar `service_alerts`, `service_alert_reads` (§2.6).
  - `uyari_uretimi.py:sla_uyarilarini_uret(db, clock) -> str`: `servis_uyari_uretimi_acik` kapalıysa çıkar. `sla_ifadeleri` ile koşulları SQL'de bulur; olmayan koşul için `INSERT … ON CONFLICT DO NOTHING` (`uq_salert_acik`), artık geçerli olmayan açık kayıtlar `kapanis_at=now, kapanis_nedeni='KOSUL_KALKTI'`; iş kapanınca `IS_KAPANDI`. SLA_ASILDI açılınca aynı işin SLA_RISK kaydı kapanır. Özet metni "açılan/kapanan/açık" sayıları.
  - Koşullar: SLA_RISK, SLA_ASILDI, MUDAHALE_ASILDI (hedef tanımlıysa), BEKLEME_BITIS_GECTI, PB_VADE_GECTI (E10-10), KRITIK_ATANMAMIS. Uzun açık sayaç E09'dadır (K5).
  - Worker: `Gorev("servis-sla-uyarilari", timedelta(minutes=5), ...)`, `Gorev("servis-uyari-temizligi", timedelta(hours=24), ...)` — `servis_uyari_saklama_gun`'den eski KAPALI kayıtları siler. İkisi de idempotent.
  - Rozet: `uyarilar.topla()` E01-18 bloğuna `service_alerts` kod bazında `COUNT` (yalnız açık, kapsamla); `yol="/operasyon-merkezi?sayac=..."` (operasyon.gor yoksa `/servis-isleri?kpi=...`).
  - Uçlar: `GET /api/teknik-servis/bildirimler?acik=1&kod=&goruldu=` (`servis.gor`, `sayfala`), `POST /bildirimler/{id}/goruldu` (tek INSERT, kapsam dışı 404).
  - Ön yüz: Operasyon Merkezi'nde "Bildirimler" sekmesi (görüldü düğmesi); `UyariZili` değişmez, yeni satırlar otomatik görünür.
- **Kabul:**
  - (1) Worker aynı turu iki kez koşunca açık kayıt sayısı değişmez; koşul kalkınca kayıt kapanır; yeniden oluşunca yeni kayıt açılır.
  - (2) Yalnız HABERLESME birimli şef GUVENLIK bildirimini ne listede ne rozette görür.
  - (3) `KENDI_ISLERI` teknisyeni yalnız kendi işlerinin bildirimlerini görür.
  - (4) `servis.gor` olmayan kullanıcıda servis uyarı satırı yok.
  - (5) "Görüldü" tek satır ekler; ikinci istek değişiklik yapmaz.
  - (6) 90 günden eski kapalı bildirim temizlik görevinde silinir, açık olan silinmez.
  - (7) Öz M10-D04: rozet sorgusu yalnız `service_alerts` (+ teknisyen için atama EXISTS) okur; 1000 açık işlik veride `/api/raporlar/uyarilar` < 200 ms (EXPLAIN ile `ix_salert_acik_birim` kullanımı).
  - (8) Mevcut uyarı satırlarının sayı ve sırası değişmez (`test_uyarilar` regresyon).
- **P2 · M · Bağımlılık:** E10-01, E10-03, E10-18, E01-18 · **Canlı risk:** `uyarilar.topla` ve `worker.GOREVLER` yalnız genişler. 5 dakikalık görev tek kopya worker'da koşar (`replicas: 1`).

### E10-06 · E-posta bildirimi: anlık SLA aşımı + günlük özet, giden kutusu, 3 deneme, kullanıcı tercihi (M10-06; ikinci aşama)
- **Canlı:** KISMEN. `mail.gonder` VAR (`services/mail.py:20-58`), SMTP ayarları şifreli VAR, `users.email` VAR. Giden kutusu, tercih ve özet YOK.
- **Yaklaşım:**
  - Tablolar `service_notification_prefs`, `service_mail_outbox` (§2.7).
  - `eposta.py`:
    - `kuyruga_al(db, clock)`: `servis_eposta_acik` ise açık SLA_ASILDI/MUDAHALE_ASILDI bildirimleri için, bildirimi görebilecek ve `anlik_eposta=true` + `email` dolu kullanıcılara ANLIK satır (`uq_smo_anlik` ile tek); İstanbul saatiyle `servis_gunluk_ozet_saati` geçmişse ve bugünün özeti yoksa GUNLUK_OZET satırı.
    - `gonder_bekleyenler(db, clock)`: `mail.yapilandirildi_mi()` false ise HİÇBİR satıra dokunmaz (deneme artmaz); gönderimde `MailKapali` olursa `deneme+1`, `son_hata` (yalnız sınıf adı + sunucu:port), `servis_eposta_deneme`'ye ulaşınca BASARISIZ.
    - Gövde: iş no, birim, müşteri unvanı, öncelik, hedef, durum ve ERP bağlantısı (`public_base_url`); fiyat/maliyet ve iletişim telefonu YOK.
  - Worker: `Gorev("servis-eposta", timedelta(minutes=5), ...)`; SMTP G/Ç'si `asyncio.to_thread` içinde (worker.py:17-24 kuralı).
  - Uçlar: `GET/PUT /api/teknik-servis/bildirim-tercihlerim` (`servis.gor`; yalnız kendi satırı). Yönetici görünümü: `GET /bildirimler/eposta-kutusu` (`operasyon.yonet`, durum filtresi).
  - Ön yüz: kullanıcı menüsünde "Bildirim tercihleri" penceresi; `SettingsPage` mevcut "Bildirim" grubuna `servis_eposta_acik`, `servis_gunluk_ozet_saati` anahtarları.
- **Kabul:**
  - (1) SMTP tanımsızken kuyruk BEKLIYOR kalır, `deneme=0`, worker hata log'lamaz (bilgi satırı yazar).
  - (2) Aynı bildirim için worker 3 tur koşsa da tek e-posta satırı/gönderimi.
  - (3) 3 hatalı denemede BASARISIZ ve `son_hata` dolu.
  - (4) `son_hata`, log ve `service_mail_outbox` içinde SMTP parolası geçmez (test: bilinen parola metniyle arama).
  - (5) E-posta gövdesinde `fiyat|tutar|maliyet|₺` geçmez.
  - (6) `anlik_eposta=false` kullanıcıya satır oluşmaz; `email` boş kullanıcı özet metninde "e-postası olmayan alıcı" sayısı olarak geçer.
- **P3 · M · Bağımlılık:** E10-05, İT'nin SMTP bilgisi · **Canlı risk:** `mail.py`'ye yalnız yeni yardımcı; teklif/hak ediş gönderimi değişmez.

### E10-07 · SLA, bekleme ve tekrar arıza raporu: ekran + Excel + genişletilmiş CSV (M10-07)
- **Canlı:** KISMEN. Rapor/Excel altyapısı VAR (`api/reports.py:33-38`, `services/export.py:45-61`); servis SLA raporu ve CSV YOK.
- **Yaklaşım:**
  - `services/teknik_servis/raporlar.py:sla_raporu(db, clock, bas, bit, birim_kumesi, kapsam)` dönem içinde TAMAMLANDI olmuş (ilk kez) PB dışı işleri okur:
    - Özet: zamanında, aşıldı, ölçülemedi, uyum % = zamanında / (zamanında + aşıldı); öncelik ve birim kırılımı; ortalama çözüm süresi; ortalama ilk müdahale.
    - Gecikme nedeni dağılımı.
    - **İş Beklemesi** (service_holds): neden bazında adet, toplam `sure_dk`, SLA'yı durduran toplam `sla_kayma_dk`.
    - **Personel Bekleme Süresi** (E09 BEKLEME faaliyeti) ayrı kolon (E10-17).
    - Tekrar arıza: işaretli, teyit dağılımı.
    - PB vade uyumu ayrı satır: E04 `bakim_uyumu` fonksiyonundan alınır (tekrar hesaplanmaz).
  - Uçlar: `GET /api/teknik-servis/raporlar/sla?bas=&bit=&birim=` (`servis.gor` + `rapor.gor`), `.xlsx` ve `.csv` (+ `rapor.disaaktar`). Excel çok sayfalı (E01-15 `sayfalari_xlsx_async`): Özet, İşler, İş Beklemeleri, Tekrar Arıza, PB Vade Uyumu. CSV = "İşler" satırları (K17).
  - Ön yüz: `pages/ServisRaporlariPage.tsx` (`/servis-raporlari`, menü `rapor.gor`), dönem `RangePicker`, birim `Select`, Excel/CSV düğmeleri (`window.open`).
- **Kabul:**
  - (1) 10 kapanan işten 7 zamanında / 2 aşıldı / 1 ölçülemedi → uyum %77,8 ve "Ölçülemedi: 1".
  - (2) Bekleme toplamı `service_holds.sure_dk` toplamına eşit.
  - (3) Ekran, Excel ve CSV aynı sayıları verir (aynı fonksiyon).
  - (4) PB işleri SLA uyumunda yok, PB vade satırında var.
  - (5) Yanıt ve dosyada fiyat/maliyet alanı yok.
  - (6) Birim A şefinin raporunda birim B işleri yok; `rapor.disaaktar` yoksa xlsx/csv 403.
  - (7) CSV'de `=cmd` ile başlayan konu `'=cmd` olarak yazılır.
- **P2 · M · Bağımlılık:** E10-01, E10-03, E10-04, E10-10, E10-17, E01-15, E04 · **Canlı risk:** `export.py`'ye yalnız yeni fonksiyon.

### E10-08 · Operasyon Merkezi: sayaçlar, SLA kalan süre sıralı liste, filtreler, dönem seçimi; hesap sunucuda (M10-08; öz: M10-D04)
- **Canlı:** YOK. Mobilite `PanelPage` servis verisi taşımıyor ve kutular tıklanmıyor (E01 §1).
- **Yaklaşım:**
  - `services/teknik_servis/operasyon.py`; sayaçlar E01-14 `KPI_TANIMLARI` kaydına eklenir (K15): `atanmamis` (E01), `plansiz` (= E01 `plan_bekleyen` durumları), `sla_riskte`, `sla_asildi`, `durduruldu`, `sahada` (E01), `beklemede`, `vadesi_gecen_bakim` (E10-10), `bugun_acilan` (İstanbul günü), `bugun_planli` (E02).
  - Sayı ve liste AYNI filtre fonksiyonundan; servis sayaçları `tur<>'PB'` süzer, yalnız `vadesi_gecen_bakim` PB sayar.
  - Uçlar (`operasyon.gor` + `servis.gor`):
    - `GET /api/teknik-servis/operasyon/ozet?birim=&oncelik=&donem=bugun|hafta|ay|30gun&bas=&bit=` → tüm sayaçlar tek SQL turunda (`FILTER (WHERE ...)` toplamaları).
    - `GET /operasyon/isler?sayac=&birim=&oncelik=&siralama=sla&limit&offset` → E01 `liste_sorgusu` + `sla_ifadeleri`; varsayılan sıralama `siralama_ifadesi` artan (DURDURULDU sonda), `sayfala`.
    - `GET /operasyon/isler.xlsx` (+ `rapor.disaaktar`), aynı filtre.
  - Ön yüz: `pages/OperasyonMerkeziPage.tsx` (`/operasyon-merkezi`), menü `{key:"/operasyon-merkezi", label:"Operasyon Merkezi", izin:"operasyon.gor"}`. Üstte tıklanabilir `Card hoverable` sayaçlar → URL `?sayac=` ile liste; birim/öncelik/dönem filtreleri (dönem `localStorage`'da, try/catch); liste satır seçimi → "Toplu Ata" (E01-12) ve "Toplu Planla" (E02) pencereleri; sekmeler: İşler, Personel (E10-09), Bildirimler (E10-05). SLA rengi ve kalan süre sunucudan; istemcide saat hesabı YOK. `useQuery(["operasyon", filtre, sayfa])`, `refetchInterval: 60_000`.
- **Kabul:**
  - (1) 3 atanmamış iş varken sayaç 3 ve liste 3 satır (`X-Toplam-Kayit`).
  - (2) Liste SLA kalan süreye göre artan.
  - (3) Birim filtresi tüm sayaçları yeniden hesaplar.
  - (4) PB işleri servis sayaçlarında yok.
  - (5) 300 açık işte her sayaç = ilgili liste toplamı (sayfalama ile, parametrik test).
  - (6) Öz M10-D04: 5.000 iş / 50.000 zaman kaydında `/operasyon/ozet` < 1 sn (tek tur toplama, EXPLAIN).
  - (7) Servis Paneli "geciken" = Operasyon `sla_asildi` = uyarı SLA_ASILDI sayısı (E10-18).
  - (8) `servis.gor` var ama `operasyon.gor` yok → 403; teknisyen 403.
- **P2 · M · Bağımlılık:** E10-01, E10-10, E10-18, E01-12, E01-14, E01-15, E02 · **Canlı risk:** yok; mobilite paneli değişmez.

### E10-09 · Personel iş yükü: kimlik bazlı canlı sayaç durumu, bugün/yarın planlı yük (M10-09)
- **Canlı:** YOK. Kişi = `users` (ayrı personel tablosu yok, E01 K15).
- **Yaklaşım:**
  - `operasyon.personel_yuku(db, clock, birim_kumesi)`: kullanıcı başına (kapsamdaki birimlerin `user_units` üyeleri, aktif):
    - açık sayaç: E09 `service_time_entries` `bitis IS NULL` → iş no, faaliyet, başlangıç;
    - bugün ve yarın planlı iş sayısı: E02 `service_plan_members` ⨝ `service_plans` (İstanbul günü);
    - açık atanmış iş sayısı (E01 `service_order_assignments`, `removed_at IS NULL`);
    - bugün çalışılan dk (MOLA hariç); kayıt yoksa `"EKSIK"` (0 yazılmaz).
  - Uç: `GET /api/teknik-servis/operasyon/personel?birim=&gun=` (`operasyon.gor` + `servis.gor`).
  - Ön yüz: Operasyon Merkezi "Personel" sekmesi; satır tıklayınca `/operasyon-merkezi?sayac=acik&teknisyen_id=` listesi.
- **Kabul:**
  - (1) Sayaç başlayınca satırda iş no ve faaliyet görünür.
  - (2) "Bugün: 4" plan sayısıyla eşit.
  - (3) Aynı tam ada sahip iki kullanıcı ayrı satır.
  - (4) MOLA dakikası çalışma süresine girmez.
  - (5) Kaydı olmayan kişide "eksik" yazar.
  - (6) Başka birimin personeli şefin listesinde yok.
- **P2 · S · Bağımlılık:** E09, E02, E01-01, E10-12 · **Canlı risk:** yok.

### E10-10 · PB işleri öncelik SLA'sı dışında; vade bakım döneminden; ayrı "Vadesi geçen bakım" sayacı (M10-10)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `ck_so_pb_sla` ile PB'de `sla_policy_id` NULL; `sla_durumu` PB için `SLA_DISI_PB` + `vade` döner.
  - Vade = `maintenance_periods.target_date + bakim_tolerans_gun` (K14); join yolu `service_orders.maintenance_period_id → maintenance_periods` (E04 §2.5), `GeneratedWorkOrderId` benzeri tek-iş bağı kullanılmaz.
  - `vadesi_gecen_bakim` KPI'sı: açık PB işi ve vade < İstanbul bugünü. PB_VADE_GECTI bildirimi bu koşuldan.
  - `sla_asildi`/"Geciken" sayaçları `tur<>'PB'` şartını ortak `servis_isi_filtresi()` yardımcısından alır.
- **Kabul:**
  - (1) Hedef tarihi bu ayın 1'i olan PB işi üretimden 4 gün sonra "Geciken"e girmez ve bildirim üretmez.
  - (2) `target_date + 30` gün geçmiş açık PB "Vadesi geçen bakım"da görünür.
  - (3) Aynı döneme bağlı 17 cihaz PB'si aynı vadeyi alır.
  - (4) "Geciken" yalnız PB dışı işlerden oluşur (otomatik test).
  - (5) `uq_so_pb_cihaz_donem` ve E04 worker davranışı değişmez.
- **P1 · S · Bağımlılık:** E04 (`maintenance_periods`), E10-18 · **Canlı risk:** yok.

### E10-11 · Bekleme–durum tutarlılığı: BEKLEMEDE dışına her geçişte aktif beklemenin aynı transaction'da kapanması (M10-11)
- **Canlı:** YOK.
- **Yaklaşım:**
  - E01 `durum_degistir()` (tek giriş noktası): önceki durum BEKLEMEDE ve hedef farklıysa, `beklemeyi_bitir()` dışından gelindiyse aktif `service_holds` satırı aynı flush içinde kapatılır: `released_at=clock.now()`, `released_by=user_id` (worker'da NULL), `otomatik_kapandi=true`, `kapanis_notu='otomatik: durum değişti'`, `sla.bekleme_kapandi()` çağrılır, BEKLEME_BITTI olayı.
  - Bakım formu (E04) "uygunsuzluk / tekrar gidilecek" sonucu `beklet(neden='BAKIM_UYGUNSUZLUK')` çağırır (doğrudan durum ataması yok).
  - `beklemede` sayacı = `status='BEKLEMEDE'` (kapalı işler tanım gereği yok).
  - Gece uzlaştırma: `servis-sla-uyarilari` görevi özetine "tutarsız bekleme" sayısı yazar (status<>'BEKLEMEDE' AND aktif hold); 0 değilse log UYARI.
  - 409 ve "genel uçla BEKLEMEDE yasak" kuralları E01-05'tedir; burada tekrarlanmaz.
- **Kabul:**
  - (1) Bekletilmiş iş IPTAL edilince bekleme `released_at`, `released_by`, "otomatik: durum değişti" ile kapanır.
  - (2) Bakım formu "tekrar gidilecek" sonucu BAKIM_UYGUNSUZLUK kodlu bekleme açar.
  - (3) Tüm durum testlerinden sonra `status<>'BEKLEMEDE'` ve aktif beklemesi olan iş sayısı 0 (oturum sonu fixture'ında doğrulanır).
  - (4) Kapalı iş bekleme sayacında yok.
- **P1 · S · Bağımlılık:** E01-03, E01-05, E04, E10-03 · **Canlı risk:** yok.

### E10-12 · Ops/SLA hesapları tek "şimdi" ve Europe/Istanbul gün sınırı (M10-12)
- **Canlı:** KISMEN. `Clock` VAR ve `datetime.now()` yasak (`clock.py:8`, `worker.py:26`); yerel saat dilimi YOK, "bugün" UTC tarihidir (`api/sims.py:138`).
- **Yaklaşım:**
  - `app/clock.py`'ye saf yardımcılar (§2.8); `tzdata` bağımlılığı.
  - E10 (ve E01/E02/E09 servis kodu) "bugün/yarın/dönem" hesaplarında yalnız `yerel_bugun(clock)` ve `yerel_gun_araligi()` kullanır; SQL'de `created_at >= :utc_bas AND created_at < :utc_bit` (indeks kullanılsın diye `AT TIME ZONE` kolon üzerinde uygulanmaz).
  - Worker görevleri `clock` parametresini kullanır; `servis_gunluk_ozet_saati` İstanbul saatine göre değerlendirilir.
  - Lint kapısı: `ruff` kuralı `DTZ` (datetime.now/date.today yasak) `app/services/teknik_servis/` için etkin.
- **Kabul:**
  - (1) FakeClock 2026-10-20 20:30 UTC (İstanbul 23:30) açılan iş "bugün açılan"da; 21:30 UTC (İstanbul 00:30) açılan ertesi günde.
  - (2) `app/services/teknik_servis/` altında `datetime.now`/`date.today` yok (ruff DTZ).
  - (3) Mevcut mobilite uçlarının "bugün" davranışı değişmez (regresyon).
- **P1 · S · Bağımlılık:** E09/M09-12 ile ortak (yardımcı tek yerde) · **Canlı risk:** `clock.py`'ye yalnız ekleme; mevcut sınıflar değişmez.

### E10-13 · Öncelik katalogdan doğrulanır ve normalleştirilir; form listesi = SLA öncelikleri (M10-13)
- **Canlı:** YOK (servis işi yok).
- **Yaklaşım:**
  - `ONCELIKLER` tek tuple (models): `ck_so_oncelik`, `ck_slap_oncelik`, Pydantic doğrulayıcı (`field_validator`: `str.strip().upper()`, Türkçe 'ı/İ' için `tr` dönüşümü uygulanmaz; değer ASCII) ve form verisi aynı sabitten.
  - `GET /isler/form-verileri` `oncelikler` alanını aktif SLA politikalarından üretir (ONCELIKLER ∩ politikası olan).
  - Unit test: her `ONCELIKLER` değerinin aktif tohum politikası var.
  - Göç: E10-15 raporu katalog dışı/harf farklı eski öncelikleri sayar, eşler (`'kritik'→KRITIK`, `'Acil'→KRITIK` eşlemesi raporda gösterilir, uygulanmadan önce onaya sunulur).
- **Kabul:**
  - (1) `oncelik="Acil"` 422 (K13).
  - (2) `oncelik="kritik"` KRITIK olarak kaydedilir.
  - (3) Form listesi SLA politikalarıyla aynı.
  - (4) Göç raporu katalog dışı kayıt sayısını gösterir.
- **P2 · S · Bağımlılık:** E10-01, E01-02, E10-15 · **Canlı risk:** yok.

### E10-14 · `operasyon.gor` / `operasyon.yonet` izinleri ve rol dağılımı (M10-14)
- **Canlı:** KISMEN. RBAC, varsayılan RED, idempotent rol senkronu VAR (`api/deps.py:79-97`, `seeds/dev.py`); operasyon izinleri YOK.
- **Yaklaşım:**
  - §3.1–3.2. Operasyon uçları `require_permission("operasyon.gor", "servis.gor")`; tanım yazma uçları `operasyon.yonet`.
  - Menü kalemi `izin:"operasyon.gor"`; görünürlük yalnız görsel, sunucu iki izni de ister.
  - `tests/unit/test_permissions.py` mevcut kuralları (her izin ≥1 rol, `maliyet.gor` kümesi sabit, YONETIM yazma izni yok) yeni izinlerle yeşil kalır; `operasyon.yonet` YONETIM'e inmez (`.gor` değil).
  - Kurulum notu: `seeds/dev.py` çıktısındaki "özelleştirilmiş rol: eksik izin" satırları için elle ekleme listesi (K12).
- **Kabul:**
  - (1) Yalnız `rapor.gor` olan kullanıcı ve SERVIS_TEKNISYEN `/operasyon/ozet`'te 403.
  - (2) `servis.gor` olmayan rollerde (SATIS, DEPO, MUHASEBE_DESTEK, TEKNIK_SERVIS) menüde Operasyon Merkezi görünmez ve uç 403.
  - (3) Birim filtresi tüm operasyon uçlarında uygulanır.
  - (4) `seeds/dev.py` iki kez çalışınca izin/rol sayısı değişmez; özelleştirilmiş rol için eksik izin log'da.
  - (5) Her yeni uç için 403/200 testi.
- **P2 · S · Bağımlılık:** E01-01 · **Canlı risk:** mevcut rollerin izin listesine dokunulmaz; YONETIM'in otomatik `.gor` genişlemesi beklenen davranıştır.

### E10-15 · Eski veriden SLA alanlarının geri doldurulması (rapor modu, idempotent) (M10-15)
- **Canlı:** KISMEN. Göç betiği kalıbı VAR (`app/migration/*.py`, `SourceMixin`); SLA geri doldurma YOK.
- **Yaklaşım:**
  - `app/migration/servis_sla_geri_doldur.py --rapor | --uygula`; yalnız `source_system='DENGEERP_V1'` ve `sla_kaynak IS NULL` satırlar (ikinci çalıştırma 0 satır).
  - Kurallar: PB hariç; politika = bugünkü aktif politika; `cozum_hedef_ilk_at = cozum_hedef_at = created_at + saat` (takvim türüyle); `sla_kaynak='GERIYE_DONUK'` ("güncel hedef" etiketi raporda ve detayda görünür); `ilk_mudahale_at` eski durum logunda saha/uzaktan geçişi varsa; `sla_sonuc` = `completed_at` (yoksa `closed_at`) ile; ikisi de yoksa ya da durum logu yoksa OLCULEMEDI. Atölye (E05 kaynaklı) satırları ayrı sayılır.
  - Eski `OpsHolds` satırları serbest metin nedenle gelir: anahtar kelime eşlemesi (`malzeme`→MALZEME, `onay`→MUSTERI_ONAYI …), eşleşmeyen DIGER + açıklama = eski metin; `sla_durdurur` göçte false (geçmiş hedef kaydırılmaz).
  - Rapor çıktısı: güncellenecek / ölçülemedi / atölye ölçülemedi / katalog dışı öncelik (E10-13) / eşlenemeyen bekleme nedeni sayıları; Excel (`export.satirlari_xlsx`).
  - Uygula modu tek transaction, `audit.log("service_orders","sla.geri_doldur", new_value={adet})`.
- **Kabul:**
  - (1) Rapor modu veri değiştirmez (satır sayısı ve `updated_at` aynı).
  - (2) İkinci `--uygula` 0 satır değiştirir.
  - (3) Logu ve `closed_at`'i olmayan kapalı iş OLCULEMEDI.
  - (4) PB işleri dahil edilmez.
  - (5) Atölye ölçülemedi ayrı satırda.
- **P2 · M · Bağımlılık:** E10-01, E10-03, E10-11, E10-13, E01 göç betiği (`migration/servis_goc.py`) · **Canlı risk:** yalnız yeni servis tablolarına yazar.

### E10-16 · "Benim İşlerim": öncelik rozeti, SLA kalan süre, bugün planlı + SLA sıralaması (M10-D01)
- **Canlı:** YOK. Mobil uygulama kapsam dışı (K16).
- **Yaklaşım:**
  - E01 `GET /isler?benim=1&siralama=gunluk` → `kapsam_kendi_isleri` + sıralama: önce bugün planlı (E02, İstanbul günü), sonra `siralama_ifadesi`. Satırda `sla` bloğu (durum, kalan dk) ve PB'de `vade_ay` ("Ekim 2026").
  - Ön yüz: `pages/BenimIslerimPage.tsx` (`/benim-islerim`, menü `servis.gor`), 375 px'te kart listesi: öncelik `Tag`, "Kalan 3 sa 20 dk" / "Gecikti" / "Durduruldu" / "Vade: Ekim 2026". Değerler sunucudan.
- **Kabul:**
  - (1) Teknisyenin 3 açık işinden SLA'sı en yakın ilk sırada (bugün planlı yoksa).
  - (2) PB işinde "Vade: Ekim 2026".
  - (3) Yanıtta fiyat/maliyet alanı yok.
  - (4) Başkasının işi listede yok.
- **P2 · S · Bağımlılık:** E10-01, E10-10, E10-18, E01-15, E02 · **Canlı risk:** yok.

### E10-17 · "İş Beklemesi" ile "Personel Bekleme Süresi"nin ayrıştırılması (M10-D02)
- **Canlı:** YOK.
- **Yaklaşım:**
  - Terim sabitleri (ön yüz ve rapor başlıkları): "İş Beklemesi" (`service_holds`, neden + SLA etkisi) ve "Personel Bekleme Süresi" (E09 BEKLEME faaliyeti).
  - SLA hesabı yalnız `service_holds.sla_kayma_dk` kullanır; E09 BEKLEME faaliyeti SLA'yı durdurmaz ve `ilk_mudahale` sayılmaz.
  - E09 zaman başlatma ucu: işte `sla_durdurur=true` aktif bekleme varken saha/işçilik faaliyeti başlatılırsa kayıt AÇILIR ve yanıtta `uyarilar: ["İş beklemede görünüyor; beklemeyi kaldırmak ister misiniz?"]` döner; ön yüz "Beklemeyi bitir" kısa yolu sunar.
- **Kabul:**
  - (1) SLA raporunda yalnız İş Beklemesi "durdurulan süre" olarak.
  - (2) Personel Bekleme Süresi ayrı kolonda, SLA hedefini değiştirmez.
  - (3) Beklemedeki işte sayaç başlatılınca uyarı döner ve sayaç kaydı oluşur (201).
- **P2 · S · Bağımlılık:** E10-03, E09 · **Canlı risk:** yok.

### E10-18 · SLA durumunun tek sunucu modülünden üretilmesi; istemcide SLA hesabı yok (M10-D03)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `sla.py` (§4): Python `sla_durumu()` + SQL `sla_ifadeleri()`; tek risk eşiği ayarı; tek PB istisnası (`servis_isi_filtresi`).
  - Tüketiciler: E01 detay/liste/Excel, E01-14 "geciken", E10-05 üretim, E10-07 rapor, E10-08 sayaç/liste, E10-16.
  - Ön yüz kod incelemesi kapısı: `frontend/src` içinde öncelik → saat eşlemesi yok (oxlint özel kuralı yerine PR kontrol listesi + `grep` testi `tests/unit/test_on_yuz_sla_hesabi_yok.py`: `KRITIK.*12|72 \* 60` desenleri aranır).
- **Kabul:**
  - (1) Aynı test verisinde Servis Paneli "geciken", Operasyon `sla_asildi`, Excel aşıldı satırı ve açık SLA_ASILDI bildirim sayısı eşit (otomatik test).
  - (2) Python ve SQL hesapları 40 işlik karışık veri setinde aynı durumu verir.
  - (3) Ön yüzde önceliğe dayalı saat hesabı yok.
- **P1 · S · Bağımlılık:** E10-01 · **Canlı risk:** yok.

### E10-19 · Test paketi, tohum fixture'ları ve regresyon kapıları (M10-D03, M10-D04 özleri; E01-19 genişlemesi)
- **Canlı:** KISMEN. Test altyapısı VAR (PG17, `_TRUNCATE`, FakeClock, `kullanici_ac`; `tests/conftest.py`). Servis SLA testleri YOK.
- **Yaklaşım:**
  - `tests/unit/test_sla_takvim.py` (DB'siz), `tests/unit/test_permissions.py` (yeni izinler).
  - `tests/integration/`: `test_servis_sla.py`, `test_servis_sla_tutarlilik.py`, `test_servis_bekleme_katalog.py`, `test_servis_tekrar_ariza.py`, `test_operasyon_merkezi.py`, `test_servis_bildirim.py`, `test_servis_eposta.py`, `test_servis_sla_rapor.py`, `test_servis_saat_dilimi.py`.
  - Fixture `sla_tohum`: migration tohumları `TRUNCATE ... CASCADE` (users → ActorMixin FK) ile silinebileceği için katalog/politika/takvim her testte `VARSAYILAN_*` sabitlerinden yazılır (migration ile aynı sabit).
  - `_TRUNCATE`'e: `service_alert_reads`, `service_mail_outbox`, `service_notification_prefs`, `service_holidays`, `service_work_calendar`, `service_hold_reasons`, `service_sla_policies` (FK zinciri dışında kalabilecekler açıkça yazılır).
  - Worker testleri `worker.GOREVLER` içindeki fonksiyonu doğrudan `db, client.clock` ile çağırır.
- **Kabul:**
  - (1) `make test` ≥ 35 E10 senaryosunu koşar.
  - (2) Altın kayıt (932 iş / 552.825,00 TL) yeşil.
  - (3) `test_migration_zinciri` head→base→head yeşil, tek head.
  - (4) Mevcut tüm testler yeşil (`test_uyarilar`, `test_ekler`, `test_permissions`).
  - (5) Her yeni uç için 403 ve kapsam (404 + `db.refresh` ile veri değişmedi) testi.
- **P1 · M · Bağımlılık:** E10-01..E10-18 · **Canlı risk:** `conftest.py` yalnız ekleme.

---

## 7. Ön yüz özeti

| Sayfa / bileşen | Rota | Menü izni | Not |
|---|---|---|---|
| `pages/OperasyonMerkeziPage.tsx` | `/operasyon-merkezi` | `operasyon.gor` | Sayaç kartları (tıklanabilir), İşler / Personel / Bildirimler sekmeleri, toplu ata/planla |
| `pages/BenimIslerimPage.tsx` | `/benim-islerim` | `servis.gor` | 375 px kart listesi |
| `pages/ServisRaporlariPage.tsx` | `/servis-raporlari` | `rapor.gor` | SLA raporu, Excel/CSV |
| `pages/ServisTanimlarPage.tsx` | `/servis-tanimlar` | `operasyon.yonet` (yalnız okuma sekmeleri `servis.gor`) | Arıza nedenleri (E01), Bekleme nedenleri, SLA politikaları, Mesai takvimi, Tatiller |
| `components/SlaEtiketi.tsx` | — | — | Sunucudan gelen `sla` bloğunu gösterir; hesap yapmaz |
| `components/UyariZili.tsx` | — | — | DEĞİŞMEZ; servis satırları sunucudan gelir |
| `api/teknikServis.ts` | — | — | E01 dosyasına `operasyon*`, `bildirim*`, `tanim*` fonksiyonları |

Kalıplar: `useQuery` (queryKey'de filtre + sayfa), `api.getSayfa`, `Table` sunucu sayfalaması, `KartPenceresi` (politika/neden düzenleme, `version` ile 409), `dayjs("tr")` + `DD.MM.YYYY HH:mm`, tüm metinler Türkçe, enum gösterimi `replaceAll("_"," ")`.

---

## 8. İzlenebilirlik (kaynak → hedef)

| Kaynak | dotnet_specific | Hedef |
|---|---|---|
| M10-01 | hayır | E10-01 |
| M10-02 | hayır | E10-02 |
| M10-03 | hayır | E10-03 |
| M10-04 | hayır | E10-04 |
| M10-05 | hayır | E10-05 |
| M10-06 | hayır | E10-06 |
| M10-07 | hayır | E10-07 |
| M10-08 | hayır | E10-08 |
| M10-09 | hayır | E10-09 |
| M10-10 | hayır | E10-10 |
| M10-11 | hayır | E10-11 |
| M10-12 | hayır | E10-12 |
| M10-13 | hayır | E10-13 |
| M10-14 | hayır | E10-14 |
| M10-15 | hayır | E10-15 |
| M10-D01 | hayır | E10-16 |
| M10-D02 | hayır | E10-17 |
| M10-D03 | hayır | E10-18 (+E10-19) |
| M10-D04 | **evet** | öz → E10-05 kabul (7), E10-08 kabul (6), E10-19 |
| Kullanıcı doğrulaması: KPI tıklanabilir | — | E10-08 (+E01-14) |
| Kullanıcı doğrulaması: toplu atama/plan | — | E10-08 (E01-12, E02 uçlarına bağlanır) |
| Kullanıcı doğrulaması: Excel | — | E10-07, E10-08 |
| Kullanıcı doğrulaması: cihaz başına PB | — | E10-10 (E01-17/E04 kuralı korunur) |

## 9. Uygulama sırası ve kapılar

1. **Temel:** E10-12 (saat yardımcısı), E10-14 (izinler), E10-03 (katalog; E01-05 ile aynı migration'da olması tercih edilir).
2. **Çekirdek:** E10-01 + E10-18 + E10-10 + E10-11 (E01-03/E01-05 ile birlikte).
3. **Ekran:** E10-08, E10-09, E10-16, E10-17.
4. **Bildirim:** E10-05; ardından E10-04, E10-13.
5. **Rapor ve göç:** E10-07, E10-15.
6. **İkinci aşama:** E10-02 (kullanıcı MESAI politikası isterse), E10-06 (SMTP hazır olunca).
7. **Sürekli:** E10-19.

Her adımda: `make test` (altın kayıt dahil), `test_migration_zinciri`, `ruff` (DTZ dahil), `npm run build`, `oxlint`.

## 10. Dokunulmazlık kontrol listesi ve gözlemler

- `work_orders` / `work_order_items` / `settlements` ve `services/settlements.py`, `services/reports.py` sorguları, `services/uyarilar.py` mevcut blokları DEĞİŞMEZ. Servis kodu `work_orders`'a yazmaz.
- Cihaz durum makinesi, `device_vehicle_assignments` ve stok EXCLUDE kısıtları değişmez.
- `TEKNIK_SERVIS` rolü ve mevcut rollerin izin listeleri değişmez; `maliyet.gor` kümesi sabit.
- `clock.py`'deki `Clock/RealClock/FakeClock` ve `mail.gonder` imzası değişmez; yalnız yardımcı eklenir.
- **Gözlem (değiştirilmedi):** Canlıda "bugün" UTC tarihidir (`api/sims.py:138`, `api/subscriptions.py:141`, `api/workorders.py:210`); İstanbul'da 00:00–03:00 arası yapılan işlemler bir önceki güne düşer. Mobilite modüllerinde düzeltilmesi ayrı iş olarak önerilir; bu modül yalnız servis kodunda yerel gün kullanır.
- **Gözlem (değiştirilmedi):** `services/reports.py:81` `"DEGISTI"` değeri (`KALEM_EYLEMLERI`'nde `DEGISTIRILDI`); E10'u etkilemez.
