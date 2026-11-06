# E08 — Eğitim, Yetkinlik ve Saha Gözlemi: Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21 · Hedef: Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdi: `analiz/02_moduller/_ozet/08_egitim_yetkinlik.json` (denetçi onaylı 21 madde), `08_egitim_yetkinlik_tasarim.md`, `08_egitim_yetkinlik_denetim.md`, `05_ESKI_SISTEM_ISLEV_ENVANTERI.md` §2.6, E-18, R-80…R-87, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`, `01_is_emirleri_entegrasyon.md` (E01).
> Bu belge YALNIZ tasarımdır. Kaynak koda dokunulmadı. Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köklerine göredir ve 2026-10-21'de kod okunarak doğrulandı.
> Madde kimlikleri `E08-NN`; kaynak madde kimlikleri `M08-xx` olarak yazıldı.

---

## 0. Özet

- Canlı ERP'de eğitim, yetkinlik, saha gözlemi, personel belgesi kavramlarından **hiçbiri yok**. `backend/app` altında `training|egitim|yetkinlik|competenc|gozlem|personnel` için yalnız ilgisiz 13 eşleşme var (`models/attachment.py`, `models/catalog.py`, `migration/cihaz_sim.py`). Ayrı personel tablosu da yok: kişi = `users` (`models/user.py:11-81`; E01 karar K15).
- Altyapının neredeyse tamamı VAR ve yeniden kullanılır: RBAC (`permissions.py`), birim kapsamı (E01-01 ile gelen `BIRIMLER`, `KENDI_BIRIMI`, `user_units`, `services/teknik_servis/kapsam.py`), durum makinesi (`services/statemachine.py:189-196`), denetim izi (`services/audit.py`), KVKK erişim logu (`services/kvkk.py:30, 40-65`), ekler (`models/attachment.py:31-62`, `api/attachments.py:41-52, 91-114`), uyarı merkezi (`services/uyarilar.py:47`), ayarlar (`services/settings.py:33-93`), Excel (`services/export.py:45-61`), sayfalama (`api/deps.py:170`), servis iş emri (E01 `service_orders`).
- Bu yüzden maddelerin çoğu **YOK**; altyapıya yaslananlar **KISMEN** işaretlendi. Kaynak listede yalnız "fark" maddeleri olduğu için eski sistemin temel işlevlerini (7 sekme, envanter #39-46) taşıyan bir **çekirdek madde (E08-02)** ve bir **izin/kapsam maddesi (E08-01)** eklendi.
- Yeni alan, mobilite zincirinden tamamen ayrıdır: `work_orders`, `work_order_items`, `settlements`, `devices` tablolarına yazılmaz, bunların CHECK/EXCLUDE kısıtlarına dokunulmaz. Saha gözlemi yalnız E01 `service_orders`'a nullable FK ile bağlanır.
- Kullanıcının eski sistemde bizzat doğruladığı işlevler korunuyor:
  - Tıklanabilir KPI kutuları: E08-23.
  - Toplu planlama/atama: E08-02 (toplu yıllık plan), E08-10 (toplu katılım).
  - Excel dışa aktarım: E08-02 (plan.xlsx), E08-12 (etkinlik.xlsx).
  - Cihaz başına PB iş emri: bu modülde PB üretimi yok; E04'teki `uq_so_pb_cihaz_donem` kuralına dokunulmaz. E08-22'deki yetkinlik uyarısı PB işine atamada da yalnız uyarı üretir, PB işini bölmez/birleştirmez.
- `dotnet_specific=true` olan tek madde (M08-16, overview yükü) ayrı madde olarak taşınmadı; özü (detay alanlarının sunucuda ayıklanması, yıl sınırı) E08-02 ve E08-20 kabul kriterlerine eklendi.

---

## 1. Canlı karşılık taraması (kod okunarak)

| Konu | Canlıda ne var | Kanıt |
|---|---|---|
| Eğitim/yetkinlik/gözlem tabloları | YOK | `models/__init__.py:59-118` |
| Personel tablosu | YOK; kişi = `users`; `user_units` E01-01 ile gelir | `models/user.py:11-81`, E01 §2.1 |
| Kullanıcı aktifliği | `users.is_active`; girişte kontrol | `services/auth.py:41, 127` |
| Birim kapsamı | Canlıda YOK; E01-01 ile `KENDI_BIRIMI`, `kapsam_birim`, `birim_disinda_mi` gelir | `permissions.py:80-82`, E01 §3.2 |
| İzin/rol | Altyapı VAR; eğitim izni YOK | `permissions.py:14-77, 89-248` |
| YONETIM rolü | Tüm `.gor` izinlerini otomatik alır | `permissions.py:84, 247` |
| Durum makinesi | Altyapı VAR; eğitim planı makinesi YOK | `services/statemachine.py:27-83, 189-196` |
| Denetim izi | VAR; `log`, `log_change`, `is_personal_data` | `services/audit.py:26-92` |
| KVKK okuma erişim logu | VAR (`erisim_kaydet`), varlık listesi `accounts, contacts, vehicles` | `services/kvkk.py:30, 40-65` |
| Ekler | VAR, polimorfik; eğitim sahibi YOK; `_kapsam` yalnız `accounts` | `models/attachment.py:31-62`, `api/attachments.py:41-52, 91-114` |
| Uyarı merkezi | VAR, hesaplanır, izne tabi; eğitim bloğu YOK | `services/uyarilar.py:9-17, 47-192` |
| Ayarlar | VAR (`DEFAULTS` beyaz listesi); eğitim anahtarı YOK | `services/settings.py:33-93` |
| Excel | VAR, TEK sayfa; çok sayfalı yardımcı YOK (E01-15 `sayfalari_xlsx_async` ekler) | `services/export.py:45-61` |
| Sayfalama | VAR | `api/deps.py:170-190` |
| Maliyet gizliliği kalıbı | VAR (`sees_cost` → alan yanıtta hiç yok) | `api/deps.py:103-105`, `api/reports.py:41-55` |
| Görev panosu bağlantısı | VAR, tek katalog | `services/gorevler.py:47-57` |
| Worker | VAR (`GOREVLER`); eğitim işi gerekmez (bkz. K8) | `worker.py:120-125` |
| Servis iş emri | Canlıda YOK; E01 `service_orders` ile gelir | E01 §2.2 |
| Mobilite iş emri atanan | `work_orders.assigned_id → accounts.id` (kişi değil, hesap) | `models/workorder.py:72, 111-114` |
| Yerel tarih yardımcısı | YOK; `Clock` yalnız `now()` (UTC) döner | `clock.py:14-34` |
| Demo/test verisi koruması | `--demo` yalnız `ENV=dev` | `seeds/dev.py:141` |
| Test altyapısı | PG17, `_TRUNCATE`, `kullanici_ac`, FakeClock | `tests/conftest.py:41, 122, 179` |

Sonuç: Bu modülün **iş kuralı ve veri katmanı tamamen YOK**; altyapı VAR ve yeniden kullanılır.

---

## 2. Veri modeli

Dosya: `backend/app/models/egitim.py` (+ `models/__init__.py` import ve `__all__`). Tablolar İngilizce, sabitler/servis/mesajlar Türkçe. Ana tablolar `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin` alır. V1.20.1'den göç edilebilecek tablolar (`training_courses`, `training_criteria`, `training_plans`, `training_sessions`, `training_attendance`, `training_observations`, `competencies`, `competency_assessments`) ayrıca `SourceMixin` ve `uq_<tablo>_kaynak` alır. Durum alanları `String` + Türkçe tuple + adlı `CheckConstraint`.

### 2.1 Kişi = `users` (yeni personel tablosu AÇILMAZ)
- Eğitim öznesi `users.id`'dir. Personelin birimi E01-01'in `user_units` tablosundan okunur (çoklu üyelik desteklenir).
- "Aktif personel" = `users.is_active=true`. Ayrılan personel `is_active=false` olur, geçmişi korunur, uyarı üretmez.
- ERP girişi olmayan saha personeli (E01 K15): `is_active=true` + kimseye verilmeyen rastgele parola özeti. `auth` koduna dokunulmaz (bkz. K2).
- "Birimsiz personel" = `user_units` satırı olmayan kullanıcı. Yalnız `TUMU` kapsamlı kullanıcı görür (R-80).

### 2.2 Tablolar

| Tablo | Ana kolonlar | Kısıtlar / indeksler |
|---|---|---|
| `training_courses` | `kod` String(30), `baslik` String(200), `kategori` String(20), `birim` String(20) NULL, `sure_saat` Numeric(4,1), `zorunlu` bool, `neden`, `hedef_davranis`, `basari_olcutu` Text, `gozlem_esik_yuzde` Numeric(5,2) NULL, `sinav_gecme_puani` Integer NULL (P3), `yenileme_ay` Integer NULL, `is_active` bool | `uq_tc_kod`; `ck_tc_kategori` IN (TEKNIK, ISG, KISISEL_GELISIM, IS_SURECI); `ck_tc_birim` (NULL veya BIRIMLER); `ck_tc_sure` 0.5–24; `ck_tc_esik` 0–100; `ck_tc_sinav` 0–100; `ck_tc_yenileme` 1–120 |
| `training_criteria` | `course_id` FK RESTRICT, `sira` Integer, `metin` String(300), `is_critical` bool, `is_active` bool | `uq_tcr_kurs_sira`; silme ucu yok, yalnız pasifleme |
| `training_plans` | `user_id` FK users RESTRICT, `course_id` FK RESTRICT, `plan_yili` Integer, `hedef_tarih` Date, `gelisim_hedefi` Text, `status` String(20) default PLANLANDI, `durum_gerekcesi` String(500), `onceki_hedef_tarih` Date NULL, `completed_on` Date NULL, `completed_session_id` FK training_sessions SET NULL | `uq_tp_kisi_kurs_yil` kısmi tekil (user_id, course_id, plan_yili) WHERE NOT is_deleted; `ck_tp_durum` → `PLAN_DURUMLARI`; `ck_tp_gerekce` (status IN ('ERTELENDI','IPTAL') → durum_gerekcesi NOT NULL); `ck_tp_tamam` (status='TAMAMLANDI' ↔ completed_on NOT NULL); `ck_tp_yil` 2020–2100; `ix_tp_yil_durum(plan_yili, status)` |
| `training_sessions` | `course_id` FK RESTRICT, `oturum_tarihi` Date, `egitmen_ad` String(120), `egitmen_user_id` FK users SET NULL, `sure_saat` Numeric(4,1), `yer` String(200), `notlar` Text | `ck_ts_sure`; ileri tarih kontrolü serviste (`Clock`) |
| `training_attendance` | `session_id` FK RESTRICT, `user_id` FK RESTRICT, `katildi` bool, `on_puan` / `son_puan` Integer NULL, `notlar` | `uq_ta_oturum_kisi`; `ck_ta_puan` 0–100. Yalnız Pk/Timestamp/Actor/Versioned/Source (düzeltme = PATCH, silme yok) |
| `training_observations` | `user_id` (gözlenen) FK RESTRICT, `course_id` FK RESTRICT, `plan_id` FK training_plans SET NULL, `asama` Integer, `gozlem_tarihi` Date, `observer_user_id` FK users SET NULL, `gozlemci_ad` String(100) (göç/gösterim), `service_order_id` FK service_orders SET NULL, `birim` String(20) NULL (anlık görüntü), `puan` Numeric(5,2), `sonuc` String(20), `kritik` bool, `notlar` Text, `aksiyon_plani` Text, `sonraki_izleme` Date NULL, `gordu_at` timestamptz NULL, `personel_yorumu` String(900), `cancelled_at`, `cancelled_by`, `cancel_reason` | `ck_tob_asama` IN (0,30,60,90); `ck_tob_sonuc` IN (KRITIK, EKSIK_GOZLEM, BASARILI, GELISIM_GEREKLI); `ck_tob_iptal` (cancelled_at NULL ↔ cancel_reason NULL); `ck_tob_puan` 0–100; `ix_tob_kisi_kurs_asama(user_id, course_id, asama)`; `ix_tob_servis(service_order_id)` |
| `training_observation_ratings` | `observation_id` FK CASCADE, `criterion_id` FK RESTRICT, `puan` SmallInteger, `gozlenmedi_gerekcesi` String(300) | `uq_tor_gozlem_madde`; `ck_tor_puan` IN (-1,0,1,2). Kritik madde kuralı serviste (tablo arası) |
| `training_corrective_actions` | `observation_id` FK RESTRICT, `user_id`, `course_id`, `sorumlu_user_id` FK users SET NULL, `termin` Date, `status` String(12), `kapanis_turu` String(20), `closing_observation_id` FK SET NULL, `kapanis_kaniti` Text, `closed_at`, `closed_by` | `uq_tca_gozlem` (gözlem başına tek); `ck_tca_durum` IN (ACIK, KAPATILDI); `ck_tca_kapanis` (status='KAPATILDI' → kapanis_turu NOT NULL; kapanis_turu='MANUEL' → length(trim(kapanis_kaniti))>0; 'OTOMATIK_GOZLEM' → closing_observation_id NOT NULL); `ix_tca_acik(user_id, course_id) WHERE status='ACIK'`. Kritik kriterler AYRI TABLODA TUTULMAZ, gözlemin `puan=0` olan kritik maddelerinden türetilir |
| `competencies` | `kod` String(20), `ad` String(150), `birim` String(20) NULL, `onerilen_hedef` SmallInteger, `is_critical` bool, `is_active` bool | `uq_cmp_kod`; `ck_cmp_hedef` 1–4; `ck_cmp_birim` |
| `competency_assessments` | `user_id` FK RESTRICT, `competency_id` FK RESTRICT, `mevcut_seviye` / `hedef_seviye` SmallInteger, `degerlendirme_tarihi` Date, `assessed_by_user_id` FK users SET NULL, `assessed_by_ad` String(100), `kanit` Text, `kaynak` String(12), `observation_id` FK SET NULL, `sonraki_degerlendirme` Date NULL | `ck_cas_seviye` 1–4 (iki kolon); `ck_cas_kaynak` IN (GOZLEM, SINAV, YONETICI, GOC); `ck_cas_kanit_kaynak` (kaynak<>'GOC' → assessed_by_user_id NOT NULL); `ix_cas_son(user_id, competency_id, degerlendirme_tarihi DESC, id DESC)`. SADECE EKLEME; güncel durum `DISTINCT ON` sorgusuyla |
| `course_competencies` (P3) | `course_id`, `competency_id` | PK ikisi; FK CASCADE |
| `personnel_certificates` | `user_id` FK RESTRICT, `course_id` FK SET NULL, `belge_adi` String(200), `verilis_tarihi` Date, `gecerlilik_bitis` Date NULL, `belge_no` String(60), `aciklama` Text, `cancelled_at/by/cancel_reason` | `ck_pc_aralik` (gecerlilik_bitis IS NULL OR >= verilis_tarihi); `ck_pc_iptal`; `ix_pc_bitis(gecerlilik_bitis) WHERE cancelled_at IS NULL` |
| `service_competency_requirements` (P3) | `birim`, `tur` (E01 `SERVIS_TURLERI`), `competency_id`, `min_seviye`, `course_id` NULL | `uq_scr_birim_tur_yetkinlik`; `ck_scr_seviye` 1–4; `ck_scr_birim`, `ck_scr_tur` |

Notlar:
- Belge numarası üretilmez; numara sayaç sorunu (count/max+1) bu modülde doğmaz.
- Fiyat/maliyet alanı YOK (eğitim maliyeti tutulmaz). `maliyet.gor` etkilenmez.
- EXCLUDE kısıtı gerekmez (tarih aralığı çakışması kuralı yok).

### 2.3 Durum makineleri (`services/statemachine.py`, `MAKINELER`'e eklenir)
```
EGITIM_PLANI (ad="Eğitim Planı", baslangiclar={PLANLANDI})
PLANLANDI         → TAMAMLANDI, BASARISIZ_TEKRAR, ERTELENDI, IPTAL
ERTELENDI         → TAMAMLANDI, BASARISIZ_TEKRAR, ERTELENDI*, IPTAL
BASARISIZ_TEKRAR  → TAMAMLANDI, ERTELENDI, IPTAL
TAMAMLANDI        → PLANLANDI   (yalnız katılım düzeltmesi "katılmadı" yapılırsa)
IPTAL             → ()          (terminal)

DUZELTICI_FAALIYET (ad="Düzeltici Faaliyet", baslangiclar={ACIK})
ACIK → KAPATILDI ;  KAPATILDI → ()
```
\* Aynı durum tekrar `IzinsizGecis` verir; ikinci erteleme durum değil yalnız tarih değiştirir (servis `ERTELENDI→ERTELENDI` için makineyi çağırmaz, `onceki_hedef_tarih`'i günceller). Meta-test (`tests/unit/test_statemachine.py:8-33`) iki makineyi otomatik sınar.

### 2.4 Genişletilen mevcut yapılar (yalnız ekleme)
- `models/attachment.py:31-62`: `EK_SAHIPLERI += ("training_observations", "training_corrective_actions", "personnel_certificates")`, `EK_TURLERI += ("GOZLEM_FOTOGRAFI", "DUZELTICI_KANIT", "SERTIFIKA")`. `kind` için DB CHECK yok → migration gerekmez.
- `api/attachments.py:41-52` `SAHIP_IZNI`: gözlem `("egitim.detay", "egitim.gozlem")`, faaliyet `("egitim.detay", "egitim.yaz")`, belge `("egitim.detay", "egitim.yaz")`. `_kapsam` (`:91-114`) bu üç varlık için `personel_disinda_mi` ile 404.
- `services/kvkk.py:30` `KISISEL_VARLIKLAR += ("training_observations", "competency_assessments", "personnel_certificates")` → kişi kartı açılışı `erisim_kaydet` ile loglanır.
- `services/settings.py:33-93` `DEFAULTS`: `egitim_gozlem_basari_esigi_yuzde: 85`, `egitim_rozet_sari_esigi_yuzde: 65`, `egitim_duzeltici_termin_gun: 14`, `egitim_belge_uyari_gun: 30`, `egitim_plan_uyari_gun: 7`, `egitim_toplu_plan_ust_sinir: 300`, `egitim_takip_pencere_gun: 7` (takip "yaklaşan" penceresi).
- `services/uyarilar.py:47` `topla()` → `if user.has("egitim.gor"):` bloğu (E08-13/14/07/11).
- `services/gorevler.py:47-57` `KAYIT_TIPLERI` → `KayitTipi("egitim_faaliyet", "Düzeltici Faaliyet", TrainingCorrectiveAction, ("id",), "/egitim?sekme=faaliyet&id={id}")`.
- `services/export.py`: E01-15'in eklediği `sayfalari_xlsx_async` yeniden kullanılır (E08 önce kodlanırsa aynı imzayla burada eklenir).
- E01 `ServisIsleriPage` detay çekmecesine "Saha Gözlemleri" kartı (E08-08).

### 2.5 Migration'lar (zincir E01 migration'larının ardına; kodlarken `alembic heads` ile doğrulanır)
1. `make makemigration m="egitim_cekirdek"`: `training_courses, training_criteria, training_sessions, training_plans, training_attendance, training_observations, training_observation_ratings, competencies, competency_assessments`. `service_order_id` FK'si E01 `service_orders`'a bağlıdır.
2. `make makemigration m="egitim_duzeltici_belge"`: `training_corrective_actions, personnel_certificates`.
3. `make makemigration m="egitim_yetkinlik_esleme"` (P3): `course_competencies, service_competency_requirements`.
- Tohum veri migration'a YAZILMAZ (katalog şirket içeriğidir, düzenlenebilir). Eski katalog (7 kurs, 29 madde, 8 yetkinlik) ve varsa pilot kayıtlar `backend/app/migration/egitim.py` göç betiğiyle idempotent yüklenir (`source_system='DENGEERP_V120'`, `source_ref=<eski kimlik>`, `uq_<tablo>_kaynak`).
- Downgrade: FK sırasıyla tablolar düşer; head→base→head testi (`tests/migration/test_migration_zinciri.py`) koşar. Canlı tablolarda hiçbir CHECK/EXCLUDE değişmez; `users`'a kolon EKLENMEZ.

---

## 3. İzinler, kapsam ve roller

### 3.1 Yeni izinler (`permissions.py` `PERMISSIONS`, modül "Eğitim")
| Kod | Açıklama |
|---|---|
| `egitim.gor` | Katalog, yıllık plan, oturum/katılım, gözlem özeti (tarih, aşama, puan, sonuç), yetkinlik matrisi (seviye), belge geçerliliği ve KPI'ları görür (kapsamındaki personel) |
| `egitim.detay` | Gözlem notu, aksiyon planı, madde puanları ve gerekçeleri, yetkinlik kanıtı, belge no/açıklama, düzeltici faaliyet kanıtı (KVKK "gerekli kadar" ayrımı) |
| `egitim.yaz` | Katalog, kriter, yetkinlik kataloğu, yıllık plan (toplu), erteleme/iptal, oturum, katılım (tek/toplu), belge kaydı, düzeltici faaliyet manuel kapanışı |
| `egitim.gozlem` | Saha gözlemi ve yetkinlik değerlendirmesi girer; kendi girdiği gözlemi iptal eder |
| `egitim.kendim` | Yalnız kendi gelişim kartını görür, kendi gözlemini "Gördüm" diye onaylar |

- Dışa aktarım için yeni izin açılmaz: `egitim.gor` + mevcut `rapor.disaaktar` (E01 §3.1 emsali). Eski `training.export` buna eşlenir.
- `egitim.detay` bilerek `.gor` ile BİTMEZ: `YONETIM` rolü `permissions.py:84`'teki `.gor` kuralıyla otomatik yalnız `egitim.gor` alır; kişi bazlı notları görmez (tasarım §2.1 "Üst Yönetim yalnız özet").

### 3.2 Roller (E01 rolleri genişler; mevcut roller DEĞİŞMEZ)
| Rol | Kapsam | Eklenen eğitim izinleri |
|---|---|---|
| `SERVIS_YONETICI` (E01) | TUMU | egitim.gor, egitim.detay, egitim.yaz, egitim.gozlem, egitim.kendim |
| `SERVIS_SEF` (E01) | KENDI_BIRIMI | egitim.gor, egitim.detay, egitim.gozlem, egitim.kendim |
| `SERVIS_OPERASYON`, `SERVIS_TEKNISYEN`, `ATOLYE` (E01) | KENDI_BIRIMI / KENDI_ISLERI | egitim.kendim |
| **`EGITIM_SORUMLUSU`** (yeni; İK / eğitim sorumlusu) | TUMU | egitim.gor, egitim.detay, egitim.yaz, rapor.gor, rapor.disaaktar, gorev.gor, gorev.yaz |
| `YONETIM` | TUMU | egitim.gor (otomatik) |
| `ADMIN` | TUMU | tümü (otomatik) |

- Her yeni izin en az bir role atanmıştır (`tests/unit/test_permissions.py:43-46`). `maliyet.gor` kümesi değişmez (`:21-26`). `YONETIM` yazma izni almaz (`:35-40`).
- `ozellestirildi=True` DB rollerine yeni izin inmez (`models/rbac.py:64-69`); kurulum notunda elle ekleme listesi verilir.
- Mevcut `TEKNIK_SERVIS` (mobilite montaj/onay) rolüne eğitim izni EKLENMEZ.

### 3.3 Personel kapsamı (`services/teknik_servis/kapsam.py`'ye ek)
- `kapsam_personel(stmt, user, kisi_sutunu)`: `TUMU` ve `KENDI_MUSTERILERI` → dokunmaz (müşteri kapsamı personele uygulanmaz); `KENDI_BIRIMI` ve `KENDI_ISLERI` → `EXISTS (user_units uu WHERE uu.user_id = kisi_sutunu AND uu.birim IN :kullanici_birimleri)`. Birimsiz personel böylece yalnız TUMU'ya görünür.
- `personel_disinda_mi(db, user, hedef_user_id) -> bool` → URL'deki kayıtta 404, veri değişmez.
- `katalog_birim_yasak_mi(user, birim) -> bool`: kurs/yetkinlik `birim` NULL ise serbest; değilse `birim_disinda_mi`. Gövdede başvurulan kurs/yetkinlik için 403 (katalog gizli değildir).
- Yerel tarih: `services/teknik_servis/ortak.py:yerel_bugun(clock) -> date` (`ZoneInfo("Europe/Istanbul")`); "ileri tarih" kontrolleri bununla yapılır, `datetime.now()` kullanılmaz.

---

## 4. Servis, API ve ön yüz yerleşimi

```
backend/app/models/egitim.py
backend/app/services/teknik_servis/egitim.py          # katalog, plan, oturum, katılım, tamamlama kuralı
backend/app/services/teknik_servis/egitim_gozlem.py   # gözlem, sonuç hesabı, düzeltici faaliyet, takip
backend/app/services/teknik_servis/egitim_yetkinlik.py
backend/app/services/teknik_servis/egitim_rapor.py    # KPI tanımları, etkinlik raporu, xlsx satırları, uyarı sayıları
backend/app/api/egitim.py                              # APIRouter(prefix="/api/egitim", tags=["egitim"]) → main.py:182-209
backend/app/migration/egitim.py                        # V1.20.1 göç betiği (idempotent)
backend/tests/integration/test_egitim_*.py, tests/unit/test_egitim_sonuc.py, tests/veri/egitim.py
frontend/src/api/egitim.ts
frontend/src/pages/EgitimPage.tsx (sekmeler), EgitimKisiKarti.tsx, GelisimKartimPage.tsx
frontend/src/components/GozlemFormu.tsx, KatilimTablosu.tsx
```
- Hata sınıfı `EgitimHatasi(ValueError)` → API'de 400 (girdi) / 409 (kural); servisler yalnız `flush`, commit API'de; denetim izi commit'ten önce, gözlem/yetkinlik/belge için `is_personal_data=True`.
- Menü (`components/AppLayout.tsx` MENU): `{key:"/egitim", label:"Eğitim ve Gelişim", icon:<ReadOutlined/>, izin:"egitim.gor"}`, `{key:"/gelisim-kartim", label:"Gelişim Kartım", icon:<IdcardOutlined/>, izin:"egitim.kendim"}`. Rotalar `main.tsx` AppLayout altına: `/egitim`, `/egitim/kisiler/:id`, `/gelisim-kartim`.
- `EgitimPage` sekmeleri eskiyle aynı sırada (E-18): Yönetim Özeti · Yıllık Plan · Eğitim Kataloğu · Katılım ve Sınav · Saha Gözlemi · Düzeltici Faaliyetler · Yetkinlik Matrisi · Belgeler · Bireysel Gelişim. Sekme `?sekme=` URL parametresinde (KPI tıklaması doğrudan açar).

---

## 5. Kararlar (kullanıcıya soru sorulmadı)

- **K1 Personel = kullanıcı.** Ayrı `personnel` tablosu açılmaz; eğitim öznesi `users.id`. *Gerekçe:* E01 K15 ile tutarlı, "aynı ad" sorunu yapısal olarak kalkar, `Personnel.ErpUserId` bağ kalitesi sorunu (denetim M08-05) ortadan kalkar.
- **K2 Girişsiz saha personeli.** `is_active=true` + rastgele, kimseye verilmeyen parola özeti. `is_active=false` yalnız "ayrıldı" anlamına gelir. *Gerekçe:* `services/auth.py:41,127`'ye dokunmadan girişi engeller; "pasif personel uyarı üretmez" kuralı (M08-D01) çalışan girişsiz personeli yanlışlıkla düşürmez. Kullanıcı ekranında ayrım bayrağı gerekirse E13'te eklenir.
- **K3 Birim.** Personelin birimi `user_units`; çok birimli kişi her iki birimin şefine görünür. Gözlem kaydında `birim` anlık görüntü olarak (kursun birimi, yoksa gözlemcinin birincil birimi) saklanır; raporlar personel birimine göre süzülür.
- **K4 Kapsam yanıt kodları.** URL'deki kişi/gözlem/faaliyet/belge kapsam dışıysa canlı kural gereği **404** (eski kabul kriterindeki 403 yerine). Gövdede başvurulan **kurs/yetkinlik** başka birime aitse **403** (katalog herkese açık, varlık gizlenmiyor). Gövdede başvurulan **servis işi** kapsam dışıysa **404** (servis işi kimliği sıralı; 403 varlığı sızdırır — `api/attachments.py:94-97` gerekçesi). Bu, M08-02/M08-D03'ün "403" ifadesinden bilinçli sapmadır; testler 404 bekler.
- **K5 Gözlem iş emri bağı.** Gözlem yalnız E01 `service_orders`'a bağlanır. Mobilite `work_orders` bağlanmaz: atanan alanı kişi değil hesap (`models/workorder.py:111-114`) ve zincir dokunulmazdır.
- **K6 Gözlemci kimdir.** `egitim.gozlem` sahibi herkes (varsayılan şef ve müdür). Kıdemli teknisyen (seviye 4) gerekirse rol değiştirmeden `UserPermission(allow=True, gerekce)` istisnasıyla yetkilendirilir (`models/rbac.py:29-52`).
- **K7 Sonuç hesabı ve eşik.** Sıra: (1) kritik maddede 0 → KRITIK; (2) kritik madde -1 (gerekçeli) → EKSIK_GOZLEM; (3) puan ≥ eşik → BASARILI; (4) diğer → GELISIM_GEREKLI. Eşik = `training_courses.gozlem_esik_yuzde`, yoksa `egitim_gozlem_basari_esigi_yuzde` (85; eski yeşil rozet eşiği). Puan = 100 × Σpuan / (cevaplanan × 2), -1 paydaya girmez (R-84). Kritik madde için kurs bazlı "her gözlemde zorunlu" ayrımı yapılmaz; gerekçe zorunluluğu yeterli kabul edildi.
- **K8 Hesaplanan, saklanmayan veriler.** 30/60/90 takip listesi, belge/eğitim geçerlilik bitişi (kurs `yenileme_ay` + plan `completed_on`), yetkinlik "son durum", düzeltici faaliyet gecikmesi ve tüm uyarılar sorgu ile hesaplanır. Worker işi eklenmez. *Gerekçe:* `services/uyarilar.py:9-12` ilkesi; idempotentlik sorunu doğmaz.
- **K9 Sınav eşiği (M08-11-c).** Kolon (`sinav_gecme_puani`) çekirdek migration'da açılır ama NULL kalır; NULL iken "katılım = tamamlandı" (CL113:42-43) aynen korunur. Doluysa ve son puan altında ise plan BASARISIZ_TEKRAR olur (P3, ekranda kurs kartında ayrıca onay kutusuyla açılır).
- **K10 Düzeltici faaliyet.** Gözlem başına tek; sorumlu = gözlemci; termin = gözlem tarihi + `egitim_duzeltici_termin_gun` (14). Otomatik kapanış: aynı kişi+kurs için, o faaliyetin kritik maddelerinin TÜMÜ 2 (Uygun) olan, iptal edilmemiş ve daha sonraki tarihli gözlem. Manuel kapanış: `egitim.yaz` + kanıt metni (boşsa 400). Müdür onayı + otomatik kapanış birlikte YOK (denetim reddi).
- **K11 Kritik açıkken atama.** Engellenmez; yalnız E08-22 uyarısı (`warnings`) ve olay geçmişinde not. *Gerekçe:* denetim "engelleme yok" kararı; operasyonu durdurmamak.
- **K12 Teknisyen kendi notlarını görür.** `egitim.kendim` sahibi kendi gözleminin notunu, madde puanlarını ve aksiyon planını görür (ilgili kişinin kendi verisine erişimi KVKK md. 11 ile uyumlu). Ayrı itiraz akışı yok; "Gördüm" + yorum (900 karakter) yeterli, onay geri alınamaz.
- **K13 Genel yönetim.** `YONETIM` yalnız özet (`egitim.gor`); `egitim.detay` verilmez.
- **K14 Belge türleri.** Liste kullanıcıdan/İSG uzmanından gelene kadar `personnel_certificates` boş, `yenileme_ay` NULL kalır; bu durumda belge uyarısı üretilmez. Taranmış belge mevcut ek altyapısıyla (`SERTIFIKA`) eklenebilir (eski tasarımdaki "dosya yok" kısıtı canlıda gereksiz, altyapı hazır).
- **K15 Yetkinlik geçmişi.** `competency_assessments` yalnız ekleme; "son durum" tablosu açılmaz (`DISTINCT ON`). Düzeltme = yeni satır. Hedef < mevcut ise yanıtta uyarı; kritik yetkinlikte kanıt zorunlu (400).
- **K16 Değişiklik günlüğü.** Ayrı `TrainingChangeLog` açılmaz (denetim reddi); canlı `audit.log_change` zaten alan bazlı değişikliği yazar (`services/audit.py:55-92`). Ertelemede eski tarih ayrıca `onceki_hedef_tarih`'te durur.
- **K17 Göç.** `backend/app/migration/egitim.py` (emsal `migration/` klasörü) V1.20.1 tablolarını okur; personel `Personnel.ErpUserId` ile `users`'a eşlenir, eşleşmeyen personel karantina raporuna yazılır (otomatik kullanıcı açılmaz; `--girissiz-ac` bayrağıyla K2'ye göre açılır). Eski `PersonnelCompetencies` satırları `kaynak='GOC'` ile ilk geçmiş satırı olur; ikinci koşu çift üretmez (`uq_cas_kaynak`). Pilot veri yoksa yalnız katalog yüklenir.
- **K18 Kurs↔yetkinlik ve "yeniden değerlendir".** P3; görev kartı açılmaz, şefin ekranında hesaplanan liste olarak durur (K8). Seviye kendiliğinden değişmez.
- **K19 Takip başlangıcı.** 30/60/90 takibi yalnız `TAMAMLANDI` planlarda `completed_on` + N gün; takibi yalnız `gozlem_tarihi >= completed_on` olan, iptal edilmemiş, aynı kişi+kurs+aşama gözlemi kapatır (sonraki yılın tekrarında önceki yıl gözlemi saymaz — denetim M08-12 ek notu). Aşama 0 "ilk/eğitim öncesi" gözlemdir, takip üretmez.
- **K20 Eğitim maliyeti tutulmaz.** Eski sistemde yok; kapsam dışı. `maliyet.gor` etkisi sıfır.
- **K21 Excel biçimi.** Eski CSV (`;`, BOM) yerine canlı kalıp `.xlsx` (formül enjeksiyonu korumalı `services/export.py:26-42`). Kolonlar eski CSV ile aynı ad ve sırada.
- **K22 Operasyonel etki raporu** (eğitim öncesi/sonrası tekrar arıza oranı) kapsam dışı; E08-22 ve E01 kimlik bazlı atama oturduktan sonra ayrı madde.

---

## 6. Maddeler

### E08-01 · Eğitim izinleri, rolleri ve personel kapsamı (altyapı; M08-17, M08-05 roller kısmı)
- **Canlı:** KISMEN. RBAC altyapısı VAR (`permissions.py:14-248`, `api/deps.py:79-97`); eğitim izni, personel kapsamı YOK. Birim kapsamı E01-01 ile gelir.
- **Yaklaşım:** §3'teki 5 izin, `EGITIM_SORUMLUSU` rolü ve E01 rollerine eklemeler `permissions.py`'ye; `kapsam_personel`, `personel_disinda_mi`, `katalog_birim_yasak_mi`, `yerel_bugun` `services/teknik_servis/kapsam.py` / `ortak.py`'ye. `api/egitim.py` takma adları: `Okuyucu = egitim.gor`, `Detayci = egitim.detay`, `Yazici = egitim.yaz`, `Gozlemci = egitim.gozlem`, `Kendim = egitim.kendim`.
- **Kabul:** (1) `test_permissions` yeşil (her izin ≥1 rol, maliyet kümesi aynı, YONETIM yazma yok). (2) YONETIM `egitim.gor` alır, `egitim.detay` almaz. (3) İki birim (GUVENLIK, HABERLESME) şefi: kapsam dışı kişinin kartı 404. (4) Birimsiz personel yalnız TUMU kullanıcının listesinde. (5) `KENDI_BIRIMI` rolü hesap/cihaz/mobilite iş emri listelerinde bugünkü sonucu görür (regresyon).
- **Dosyalar:** `backend/app/permissions.py`, `backend/app/services/teknik_servis/kapsam.py`, `backend/app/services/teknik_servis/ortak.py`, `backend/tests/unit/test_permissions.py`, `backend/tests/integration/test_egitim_kapsam.py`.
- **Öncelik/Efor:** P1 / S · **Bağımlılık:** E01-01. · **Canlı risk:** Düşük. Yalnız ekleme; mevcut rol izin listeleri değişmez. Önlem: unit testler + kapsam regresyon testi.

### E08-02 · Eğitim çekirdeği: katalog, toplu yıllık plan, oturum/katılım, gözlem, yetkinlik, kişi kartı, plan Excel'i (envanter #39-46, E-18; M08-16 özü)
- **Canlı:** YOK.
- **Yaklaşım:**
  - Migration `egitim_cekirdek` (§2.5-1); modeller `models/egitim.py`.
  - Uçlar (`/api/egitim`): `GET/POST /kurslar`, `GET/PATCH /kurslar/{id}` (version), `POST /kurslar/{id}/kriterler`, `PATCH /kriterler/{id}`; `GET /planlar` (filtre: yil, birim, kurs_id, durum, kisi_id, kpi; `sayfala`), `POST /planlar/toplu` (≤ `egitim_toplu_plan_ust_sinir`; mevcut kişi+kurs+yıl atlanır, yanıtta `olusan/atlanan` sayıları); `GET/POST /oturumlar`, `POST /oturumlar/{id}/katilim` (tek kişi); `GET/POST /gozlemler`, `GET /gozlemler/{id}`; `GET /yetkinlikler`, `GET /yetkinlik-matrisi`, `POST /yetkinlik-degerlendirmeleri`; `GET /kisiler` (kapsamlı personel listesi), `GET /kisiler/{user_id}/kart` (`kvkk.erisim_kaydet`); `GET /plan.xlsx` (`egitim.gor` + `rapor.disaaktar`; kolonlar: Personel, Eğitim, Yıl, Hedef Tarih, Durum, Tamamlanma, Son Sınav).
  - Eski tek "overview" ucu TAŞINMAZ; sekme başına sayfalı uçlar canlı kalıptır. Gözlemler varsayılan olarak seçili yıl ± 1 ile sınırlıdır (M08-16 özü).
  - Ön yüz: `EgitimPage` sekmeleri (§4); listeler `useQuery(["egitim-planlar", filtre, sayfa])` + `api.getSayfa`; formlar `KartPenceresi` kalıbı; toplu plan formu (kurs*, yıl, hedef tarih varsayılan yıl-12-15, gelişim hedefi, personel çoklu seçim + tümünü seç/temizle); gecikmiş hedef kırmızı; rozet eşikleri ≥85 yeşil / ≥65 sarı (ayar).
  - Göç betiği `migration/egitim.py` (K17).
- **Kabul:** (1) 3 kişiye toplu plan → 3 satır; tekrarı 0 yeni satır ve `atlanan=3`. (2) 301 kişilik istek 400. (3) Pasif kurs plan seçiminde gelmez. (4) Gözlem puanı R-84 formülüyle sunucuda hesaplanır (2,2,1,-1 → %83,33). (5) `plan.xlsx` kapsam dışı personel satırı içermez ve `rapor.disaaktar` yoksa 403. (6) Her uç için 403/200 testi. (7) Göç betiği iki kez koşunca satır sayısı değişmez.
- **Dosyalar:** `backend/app/models/egitim.py`, `backend/app/models/__init__.py`, `backend/alembic/versions/<rev>_egitim_cekirdek.py`, `backend/app/services/teknik_servis/egitim.py`, `egitim_gozlem.py`, `egitim_yetkinlik.py`, `backend/app/api/egitim.py`, `backend/app/main.py`, `backend/app/migration/egitim.py`, `frontend/src/api/egitim.ts`, `frontend/src/pages/EgitimPage.tsx`, `frontend/src/pages/EgitimKisiKarti.tsx`, `frontend/src/main.tsx`, `frontend/src/components/AppLayout.tsx`, `backend/tests/integration/test_egitim_cekirdek.py`.
- **Öncelik/Efor:** P1 / L · **Bağımlılık:** E08-01, E01-02 (`service_orders` FK). · **Canlı risk:** Düşük. Yeni tablolar; `main.py` yalnız router ekleme. Önlem: altın kayıt testi ve migration zinciri testi her adımda.

### E08-03 · Yetkinlik değerlendirme geçmişi (M08-08)
- **Canlı:** YOK.
- **Yaklaşım:** `competency_assessments` yalnız ekleme (K15). `POST /yetkinlik-degerlendirmeleri` (`egitim.gozlem`): yeni satır; `assessed_by_user_id = user.id`, `assessed_by_ad = user.full_name`. Matris `DISTINCT ON (user_id, competency_id) ORDER BY degerlendirme_tarihi DESC, id DESC`. `GET /kisiler/{id}/yetkinlik-gecmisi` zaman çizelgesi (`Timeline`). Yetkinliğin `birim`i için `katalog_birim_yasak_mi` (403), kişi için `personel_disinda_mi` (404). Göçte eski satırlar `kaynak='GOC'` ile idempotent taşınır.
- **Kabul:** (1) Aynı kişi+yetkinlik için 2→3 sonrası geçmişte 2 satır, matriste 3. (2) `assessed_by_user_id` dolu. (3) Başka birim yetkinliği 403. (4) Göç iki kez koşunca satır sayısı = eski satır sayısı. (5) Kritik yetkinlikte kanıtsız istek 400.
- **Dosyalar:** `backend/app/models/egitim.py`, `backend/app/services/teknik_servis/egitim_yetkinlik.py`, `backend/app/api/egitim.py`, `backend/app/migration/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `frontend/src/pages/EgitimKisiKarti.tsx`, `backend/tests/integration/test_egitim_yetkinlik.py`.
- **Öncelik/Efor:** P1 / S · **Bağımlılık:** E08-02. · **Canlı risk:** Yok.

### E08-04 · Plan tamamlama kuralları (M08-11)
- **Canlı:** YOK.
- **Yaklaşım:** `egitim.py:katilim_isle(db, oturum, kisi, katildi, on, son, *, user_id, clock)` tek fonksiyon (tek kişilik ve toplu uç aynı kuralı kullanır):
  - (a) `POST/PATCH /oturumlar`: `oturum_tarihi > yerel_bugun(clock)` → 400.
  - (b) `katildi=True` → aynı kişi+kurs için `plan_yili <= oturum_tarihi.year`, durum IN (PLANLANDI, ERTELENDI, BASARISIZ_TEKRAR), silinmemiş planlardan **en eski** (`plan_yili, hedef_tarih, id`) `EGITIM_PLANI.dogrula` ile TAMAMLANDI; `completed_on = oturum_tarihi`, `completed_session_id`. "Geç" = `completed_on > hedef_tarih` (hesaplanır). Açık plan yoksa katılım yazılır, plan oluşturulmaz.
  - (c, P3) `sinav_gecme_puani` doluysa ve `son_puan < esik` → BASARISIZ_TEKRAR (K9).
  - Katılım "katılmadı"ya düzeltilirse bu oturumla kapanan plan PLANLANDI'ya döner (makinede tek geri geçiş).
- **Kabul:** (1) Yarın tarihli oturum 400. (2) 2026 planı Ocak 2027 oturumuyla TAMAMLANDI ve raporda "geç". (3) 2027 planı varken Aralık 2026 oturumu 2027 planını kapatmaz. (4) Eşik NULL kursta son puan 20 olsa da tamamlandı. (5) Eşik 70, puan 60 → BASARISIZ_TEKRAR (P3 testi).
- **Dosyalar:** `backend/app/services/teknik_servis/egitim.py`, `backend/app/services/statemachine.py`, `backend/app/api/egitim.py`, `backend/tests/integration/test_egitim_plan_tamamlama.py`.
- **Öncelik/Efor:** P1 (a,b) / P3 (c) · S · **Bağımlılık:** E08-02. · **Canlı risk:** Düşük; `MAKINELER`'e ekleme meta-testi otomatik koşar.

### E08-05 · Gözlem sonucunun sunucuda hesaplanması, kritik madde kuralı, başarı oranı KPI'sı (M08-13)
- **Canlı:** YOK.
- **Yaklaşım:** `egitim_gozlem.py:sonuc_hesapla(kriterler, puanlar, esik) -> (puan, sonuc, kritik)` saf fonksiyon (unit test). Doğrulama: tüm maddeler -1 → 400; kritik madde -1 ve `gozlenmedi_gerekcesi` boş → 400; pasif kriter → 400; kursa ait olmayan kriter → 400. KPI: başarı oranı = BASARILI / iptal edilmemiş gözlem; ortalama puan ikincil; "kritik" ayrı kutu. Ön yüzde kritik maddelerin varsayılanı "Gözlenmedi" DEĞİL, boş (seçim zorunlu) — denetim ek bulgusu; rozet kritikte puan yerine "KRİTİK".
- **Kabul:** (1) 3 gözlem (%95, %90-kritik, %70) → başarı oranı 1/3, kritik kutusu 1, ortalama %85. (2) Kritik madde -1 gerekçesiz → 400; gerekçeli → EKSIK_GOZLEM ve başarılı sayılmaz. (3) `sonuc` istemciden gönderilse bile yok sayılır.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim_gozlem.py`, `backend/app/services/teknik_servis/egitim_rapor.py`, `backend/app/api/egitim.py`, `frontend/src/components/GozlemFormu.tsx`, `backend/tests/unit/test_egitim_sonuc.py`, `backend/tests/integration/test_egitim_gozlem.py`.
- **Öncelik/Efor:** P1 / S · **Bağımlılık:** E08-02. · **Canlı risk:** Yok.

### E08-06 · Düzeltme ve iptal (M08-09)
- **Canlı:** YOK.
- **Yaklaşım:**
  - P1: `POST /gozlemler/{id}/iptal` (gerekçe zorunlu; gözlemci kendisi `egitim.gozlem` ile, diğerleri `egitim.yaz`); `POST /planlar/{id}/ertele` (yeni hedef tarih + gerekçe; eski tarih `onceki_hedef_tarih`); `POST /planlar/{id}/iptal` (gerekçe); `PATCH /kurslar/{id}` `is_active`; `PATCH /kriterler/{id}` `is_active` (puanlanmış kriter silinmez, silme ucu yok).
  - P2: kurs metin alanları ve `PATCH /oturumlar/{id}` (tarih kuralı E08-04-a geçerli).
  - Tüm değişiklikler `audit.log_change` ile; iptal edilen gözlem/plan KPI, 30/60/90, uyarı ve raporlardan düşer, kişi kartında "iptal — gerekçe" görünür. Gözlem iptali bağlı açık düzeltici faaliyeti KAPATMAZ: faaliyet açık kalır, ekranda "gözlemi iptal edildi" etiketi çıkar ve yalnız manuel kapanır (sessiz kayıp önlenir).
- **Kabul:** (1) Gerekçesiz iptal/erteleme 400. (2) İptal edilen gözlem başarı oranından ve takipten düşer, kartta görünür. (3) Ertelenen planın eski tarihi `onceki_hedef_tarih`'te ve denetim izinde. (4) Pasif kriterli eski gözlemin puanı değişmez. (5) PATCH'te eski `version` → 409.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim.py`, `egitim_gozlem.py`, `backend/app/api/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_duzeltme.py`.
- **Öncelik/Efor:** P1 / P2 · M · **Bağımlılık:** E08-02, E08-04. · **Canlı risk:** Yok.

### E08-07 · Kritik İSG uygunsuzluğu için düzeltici faaliyet (M08-01)
- **Canlı:** YOK.
- **Yaklaşım:** Migration `egitim_duzeltici_belge`. Gözlem kaydı aynı transaction'da `sonuc=KRITIK` ise `training_corrective_actions` açar (K10). Aynı transaction'da, yeni gözlem aynı kişi+kurs için açık faaliyetlerin kritik maddelerini 2 ile karşılıyorsa `DUZELTICI_FAALIYET.dogrula` → KAPATILDI (`OTOMATIK_GOZLEM`, `closing_observation_id`). `POST /duzeltici-faaliyetler/{id}/kapat` (`egitim.yaz`, kanıt zorunlu). `GET /duzeltici-faaliyetler` (durum, gecikmiş, birim; `sayfala`). Uyarılar: açık → `onem="uyari"`, termin geçmiş → `onem="kritik"`; sayılar `kapsam_personel` ile SQL'de. Görev panosuna bağlanabilir (`KAYIT_TIPLERI`). Kanıt fotoğrafı `DUZELTICI_KANIT` eki.
- **Kabul:** (1) Kritik maddede 0 içeren gözlem 1 açık faaliyet açar (sorumlu=gözlemci, termin=+14 gün, ayar değişince yeni kayıtlarda değişir). (2) Aynı gözlem için ikinci faaliyet açılamaz (`uq_tca_gozlem`). (3) Kritik maddeleri 2 olan sonraki gözlem faaliyeti otomatik kapatır ve bağlantıyı tutar. (4) Kanıtsız manuel kapanış 400; `egitim.gozlem` ile kapanış 403. (5) Termin geçince uyarı "kritik"e çıkar (FakeClock). (6) Başka birim şefinin uyarı sayısı 0.
- **Dosyalar:** `backend/app/models/egitim.py`, `backend/alembic/versions/<rev>_egitim_duzeltici_belge.py`, `backend/app/services/teknik_servis/egitim_gozlem.py`, `backend/app/services/statemachine.py`, `backend/app/services/uyarilar.py`, `backend/app/services/gorevler.py`, `backend/app/services/settings.py`, `backend/app/models/attachment.py`, `backend/app/api/attachments.py`, `backend/app/api/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_duzeltici.py`.
- **Öncelik/Efor:** P2 / M · **Bağımlılık:** E08-05. · **Canlı risk:** Düşük. `uyarilar.topla()` yeni blok izne bağlı; mevcut blokların sayıları değişmez (test: mevcut uyarı kodları aynı). `attachments._kapsam` yalnız yeni varlıklar için dal ekler, `accounts` dalı aynı kalır.

### E08-08 · Saha gözlemini servis işinden başlatma ve serviste gösterme (M08-02)
- **Canlı:** YOK (E01 servis işi ekranı da henüz yok).
- **Yaklaşım:** `POST /gozlemler` gövdesinde `service_order_id`: servis işi `is_erisimi_yok_mu` (E01 §3.2) ile kontrol, kapsam dışı → 404 (K4). `GET /gozlemler?service_order_id=` servis detayında listelenir (`egitim.gor`; detay alanları `egitim.detay`'a bağlı). Ön yüz: E01 `ServisIsleriPage` çekmecesinde "Saha Gözlemleri" kartı + "Saha Gözlemi Yap" düğmesi (`yetkili("egitim.gozlem")`), `GozlemFormu` iş no ve birim kilitli açılır; aktif atamalı teknisyenler (E01 `service_order_assignments`) personel seçiminde önce gelir. Bağımsız gözlem formunda servis işi seçimi sunucu aramasıyla (`GET /api/teknik-servis/isler?q=` E01-15) yapılır, 400 sınırı yok. "Atama dışı" uyarısı kimlik bazlı atama olduğu için artık doğrudan yapılabilir: gözlenen kişinin o işte atama satırı (aktif veya geçmiş) yoksa yanıtta `uyarilar` döner; bayrak saklanmaz.
- **Kabul:** (1) Servis detayından açılan formda iş no ve birim kilitli. (2) Kaydedilen gözlem servis detayında listelenir. (3) Başka birimin servis işiyle gözlem 404 ve kayıt oluşmaz. (4) Eski bir servis işi aramayla seçilir. (5) Atamasız kişi için kayıt yapılır, yanıtta uyarı döner.
- **Dosyalar:** `backend/app/api/egitim.py`, `backend/app/services/teknik_servis/egitim_gozlem.py`, `frontend/src/components/GozlemFormu.tsx`, `frontend/src/pages/ServisIsleriPage.tsx`, `backend/tests/integration/test_egitim_servis_bagi.py`.
- **Öncelik/Efor:** P2 / M · **Bağımlılık:** E08-02, E08-17, E01-02, E01-12, E01-15. · **Canlı risk:** Yok; servis kodu yalnız okunur, `work_orders`'a bağ yok (K5).

### E08-09 · Teknisyen "Gelişim Kartım" ve gözlem "Gördüm" onayı (M08-05)
- **Canlı:** YOK.
- **Yaklaşım:** `GET /api/egitim/kendim` (`egitim.kendim`): yalnız `user.id`'nin planları, belgeleri ve geçerlilikleri, gözlemleri (madde puanı + not + aksiyon planı, K12), yetkinlik geçmişi, açık düzeltici faaliyetleri. Kişi kimliği parametre ALMAZ; başka kişinin kartı için `/kisiler/{id}/kart` `egitim.gor` ister → teknisyende 403. `POST /kendim/gozlemler/{id}/gordum` (yorum ops.): `observation.user_id == user.id` değilse 404; `gordu_at` doluysa 409 (geri alınamaz). Personel bağı kavramı canlıda yok (K1); "personel kaydınız bağlı değil" durumu yerine: kullanıcının hiç eğitim kaydı yoksa boş kart + "Henüz eğitim kaydınız yok" mesajı. Ön yüz `GelisimKartimPage` (375 px uyumlu).
- **Kabul:** (1) `egitim.kendim` sahibi yalnız kendi verisini alır. (2) `/kisiler/{baska}/kart` 403. (3) Başkasının gözlemini onaylama 404, kendi onayı ikinci kez 409. (4) Onay tarihi şefin gözlem listesinde görünür. (5) Kaydı olmayan kullanıcıya boş kart.
- **Dosyalar:** `backend/app/api/egitim.py`, `backend/app/services/teknik_servis/egitim_gozlem.py`, `frontend/src/pages/GelisimKartimPage.tsx`, `frontend/src/main.tsx`, `frontend/src/components/AppLayout.tsx`, `backend/tests/integration/test_egitim_kendim.py`.
- **Öncelik/Efor:** P2 / M · **Bağımlılık:** E08-02, E08-01. · **Canlı risk:** Yok.

### E08-10 · Oturumda toplu katılım girişi (M08-06)
- **Canlı:** YOK.
- **Yaklaşım:** `GET /oturumlar/{id}/aday-katilimcilar` (kursun o yıl açık planı olan kapsamdaki kişiler + mevcut katılım satırları); `PUT /oturumlar/{id}/katilim/toplu` (liste, ≤300): her satır `katilim_isle` (E08-04) ile; tek transaction, ilk hatada `EgitimHatasi(satir=n)` → 400 `{"satir": n, "mesaj": ...}` ve hiçbir satır yazılmaz (API commit etmez). Plan dışı kişi eklenebilir. Tek kişilik uç korunur. Ön yüz `KatilimTablosu` (düzenlenebilir `Table`, katıldı anahtarı, ön/son puan).
- **Kabul:** (1) 15 satır tek istekte yazılır. (2) 7. satırda puan 120 → 400, satır=7, DB'de 0 yeni satır. (3) Plan sahipleri önceden listelenir. (4) Tamamlama kuralı E08-04 ile aynı (testler ortak). (5) Tek kişilik uç çalışır.
- **Dosyalar:** `backend/app/api/egitim.py`, `backend/app/services/teknik_servis/egitim.py`, `frontend/src/components/KatilimTablosu.tsx`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_toplu_katilim.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-04. · **Canlı risk:** Yok.

### E08-11 · Zorunlu eğitim / belge geçerlilik takibi (M08-03)
- **Canlı:** YOK.
- **Yaklaşım:** Kurs `yenileme_ay` (çekirdekte NULL). Geçerlilik = TAMAMLANDI planın `completed_on` + `yenileme_ay` (hesaplanır; aynı kişi+kurs için en son tamamlanan esas). `personnel_certificates` CRUD: `GET /belgeler?durum=dolan|dolacak|gecerli` (pencere `egitim_belge_uyari_gun`), `POST /belgeler`, `POST /belgeler/{id}/iptal` (`egitim.yaz`); belge no/açıklama `egitim.detay`. Uyarı `egitim.belge_bitiyor` (≤30 gün, `uyari`) ve `egitim.belge_doldu` (`kritik`); `yenileme_ay` NULL ve belge yoksa sıfır. P3: `GET /belgeler/yenileme-onerisi?yil=` → seçilenler `POST /planlar/toplu`'ya (mükerrer üretmez). Tarama `SERTIFIKA` eki.
- **Kabul:** (1) 12 ay periyotlu eğitimi 01.11.2026'da tamamlayanın geçerliliği 01.11.2027. (2) Bitişe ≤30 gün kalan kayıt uyarıda (FakeClock). (3) Elle girilen belge kişi kartında. (4) "Süresi dolan" sayısı = tıklanınca açılan liste uzunluğu. (5) Liste boşken uyarı 0. (6) Öneri listesinden toplu plan mükerrer üretmez (P3).
- **Dosyalar:** `backend/app/models/egitim.py`, `backend/app/services/teknik_servis/egitim.py`, `backend/app/services/teknik_servis/egitim_rapor.py`, `backend/app/services/uyarilar.py`, `backend/app/services/settings.py`, `backend/app/api/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_belge.py`.
- **Öncelik/Efor:** P2 (çekirdek) / P3 (öneri) · M · **Bağımlılık:** E08-02, E08-04. · **Canlı risk:** Yok.

### E08-12 · Eğitim etkinliği raporu ve xlsx (M08-07)
- **Canlı:** KISMEN. Excel altyapısı VAR (`services/export.py:45-61`), tek sayfa; çok sayfa E01-15 ile gelir. Rapor yok.
- **Yaklaşım:** `egitim_rapor.py:etkinlik(db, user, yil, birim, kurs_id)`: kurs × birim satırı; 0/30/60/90 başarı oranı ve ortalama (veri yoksa `None` → ekranda "veri yok"), 0→90 farkı (yalnız ikisi de varsa), ön/son sınav ortalaması ve farkı, kritik sayısı (açık/kapalı), takip uyumu (zamanı gelen / yapılan), eğitim saati yalnız bilgi kolonu. `GET /rapor/etkinlik` (`egitim.gor`), `GET /rapor/etkinlik.xlsx` (`egitim.gor` + `rapor.disaaktar`): Aşama 1 sayfaları "Plan" ve "Gözlemler" (not/aksiyon kolonları yalnız `egitim.detay` ile — kolon hiç yok, boş değil). Aşama 2: "Yetkinlik", "Düzeltici Faaliyetler", "Belgeler". Kapsam `kapsam_personel` ile SQL'de.
- **Kabul:** (1) 0. gün ort. 60, 90. gün ort. 85 → "+25". (2) Kritikli gözlem başarı oranında başarısız. (3) Gözlemsiz aşama "veri yok". (4) xlsx'te kapsam dışı personel yok. (5) `egitim.detay` olmayanın xlsx'inde "Notlar" kolonu yok. (6) Formül enjeksiyonu metne çevrilir.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim_rapor.py`, `backend/app/services/export.py` (E01-15 yardımcısı), `backend/app/api/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_rapor.py`.
- **Öncelik/Efor:** P2 / M · **Bağımlılık:** E08-04, E08-05 (aşama 2: E08-03, E08-07, E08-11). · **Canlı risk:** Yok; mobilite `services/reports.py` ve `api/reports.py` değişmez.

### E08-13 · 30/60/90 takibinin sunucuda hesaplanması ve uyarı (M08-12)
- **Canlı:** YOK.
- **Yaklaşım:** `egitim_gozlem.py:takip_sorgusu(user, bugun)` tek fonksiyon (K19): TAMAMLANDI ve silinmemiş plan × (30,60,90); `vade = completed_on + N`; kapatan gözlem = aynı kişi+kurs+aşama, `gozlem_tarihi >= completed_on`, iptal edilmemiş, en sonuncusu. Durum: GECIKTI (vade < bugün), ZAMANI_GELDI (vade = bugün), YAKLASAN (≤ `egitim_takip_pencere_gun`). Pasif personel/kurs dahil edilmez. `GET /takipler` (sayfalı) ve uyarı `egitim.takip` aynı fonksiyondan sayılır.
- **Kabul:** (1) 01.09'da tamamlanan eğitimin 30. gün takibi 01.10'da uyarıda. (2) Tamamlanmadan önceki tarihli gözlem takibi kapatmaz; sonraki tarihli kapatır; iptal edilen gözlem takibi yeniden açar. (3) Uç toplamı = uyarı adedi. (4) Başka birimin personeli görünmez.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim_gozlem.py`, `backend/app/services/uyarilar.py`, `backend/app/api/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_takip.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-04, E08-06, E08-14. · **Canlı risk:** Yok.

### E08-14 · Eğitim uyarısında birim süzmesi, pasif kayıt ve birimsiz personel (M08-D01)
- **Canlı:** YOK (uyarı bloğu yok); hata canlıya hiç taşınmaz.
- **Yaklaşım:** `uyarilar.topla()` eğitim bloğu: `egitim.plan_vadesi` (hedef ≤ bugün + `egitim_plan_uyari_gun`, durum IN PLANLANDI/BASARISIZ_TEKRAR — ERTELENDI yeni tarihle dahil, IPTAL hariç), `egitim.takip`, `egitim.duzeltici`, `egitim.belge_*`. Tüm sayılar tek SQL'de `count()` ile; `kapsam_personel` sorgu içinde, LIMIT yok (sayı döner); `users.is_active`, `training_courses.is_active`, `is_deleted` süzmesi. Birimsiz personel yalnız TUMU'ya.
- **Kabul:** (1) Kendi biriminde 1 geciken planı olan şef 1 uyarı görür; başka birimde 50 eski kayıt olsa da. (2) Pasif personel/kurs ve iptal planlar uyarı üretmez. (3) Birimsiz personelin planı KENDI_BIRIMI şefinde 0, TUMU yöneticide 1. (4) `egitim.gor` olmayan kullanıcıda eğitim uyarısı yok.
- **Dosyalar:** `backend/app/services/uyarilar.py`, `backend/app/services/teknik_servis/egitim_rapor.py`, `backend/tests/integration/test_egitim_uyarilar.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-01, E08-02. · **Canlı risk:** Düşük; yeni blok `if user.has("egitim.gor")` altında. Önlem: mevcut uyarı testleri değişmeden yeşil.

### E08-15 · Gözlem tarihi ve aşama doğrulaması (M08-D02)
- **Canlı:** YOK.
- **Yaklaşım:** `gozlem_tarihi > yerel_bugun(clock)` → 400. Aşama 30/60/90 için ilgili plan (`plan_id`; yoksa en son TAMAMLANDI plan) `completed_on`'dan önceki tarih → kayıt + yanıtta `uyarilar`; aynı kişi+kurs+aşama+plan için iptal edilmemiş ikinci gözlem → kayıt + uyarı. Takip en son geçerli gözlemi esas alır (E08-13).
- **Kabul:** (1) Yarın tarihli gözlem 400. (2) Tamamlanmadan önceki 30. gün gözlemi kaydedilir, yanıt uyarılı. (3) Aynı aşama ikinci gözlem kaydedilir, uyarılı; takip sonuncuyu esas alır.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim_gozlem.py`, `backend/app/api/egitim.py`, `backend/tests/integration/test_egitim_gozlem.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-06. · **Canlı risk:** Yok.

### E08-16 · Yetkinlik kataloğu yönetimi; kurs↔yetkinlik bağı ve "yeniden değerlendir" listesi (M08-10)
- **Canlı:** YOK.
- **Yaklaşım:** P2: `POST /yetkinlikler`, `PATCH /yetkinlikler/{id}` (ad, birim, önerilen hedef, kritik, `is_active`; version) `egitim.yaz`. Pasif yetkinlik matris formunda seçilmez, geçmişte görünür. P3: migration `egitim_yetkinlik_esleme` → `course_competencies`; kurs kartında bağlı yetkinlikler; `GET /yeniden-degerlendirilecekler`: aşama 90 BASARILI gözlemi olup, gözlem tarihinden sonra o kursa bağlı yetkinlik için değerlendirmesi olmayan kişi×yetkinlik (hesaplanır, K18). Seviye otomatik değişmez.
- **Kabul:** (1) Yeni yetkinlik eklenip matriste seçilebilir; pasife alınınca seçilmez. (2) (P3) Bağlı yetkinlik kurs kartında. (3) (P3) Başarılı 90. gün gözlemi listeye 1 kayıt düşürür, değerlendirme girilince düşer; seviye değişmez.
- **Dosyalar:** `backend/app/models/egitim.py`, `backend/alembic/versions/<rev>_egitim_yetkinlik_esleme.py`, `backend/app/services/teknik_servis/egitim_yetkinlik.py`, `backend/app/api/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_yetkinlik.py`.
- **Öncelik/Efor:** P2 / P3 · M · **Bağımlılık:** E08-03. · **Canlı risk:** Yok.

### E08-17 · Gözlemci kimliği ve öz-değerlendirme engeli (M08-15)
- **Canlı:** YOK.
- **Yaklaşım:** `observer_user_id = user.id`, `gozlemci_ad = user.full_name` sunucuda (istemciden alınmaz). Personel = kullanıcı olduğu için kural doğrudandır: `gozlenen.user_id == user.id` → 400 "Kendi gözleminizi giremezsiniz"; yetkinlikte `assessed_by_user_id == user_id` → 400. Göçle gelen eski kayıtlar `observer_user_id` NULL, `gozlemci_ad` ile görüntülenir.
- **Kabul:** (1) Yeni gözlemde `observer_user_id` dolu. (2) Kendi kendine gözlem ve değerlendirme 400. (3) Göç kayıtları bozulmadan listelenir.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim_gozlem.py`, `egitim_yetkinlik.py`, `backend/tests/integration/test_egitim_gozlem.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-03. · **Canlı risk:** Yok.

### E08-18 · Oturum oluşturmada kurs birimi ve aktif kurs kontrolü (M08-14)
- **Canlı:** YOK.
- **Yaklaşım:** `POST/PATCH /oturumlar`: kurs pasif → 400; `katalog_birim_yasak_mi(user, kurs.birim)` → 403; birimsiz kurs serbest. Aynı kontrol kurs ve kriter yazma uçlarında.
- **Kabul:** (1) Yalnız HABERLESME birimli yazma yetkilisinin GUVENLIK kursuna oturum isteği 403. (2) Pasif kursa oturum 400. (3) Birimsiz kurs kabul.
- **Dosyalar:** `backend/app/api/egitim.py`, `backend/app/services/teknik_servis/egitim.py`, `backend/tests/integration/test_egitim_kapsam.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-01. · **Canlı risk:** Yok. Not: `egitim.yaz` varsayılanda TUMU rollerinde; test istisna (`UserPermission`) ile KENDI_BIRIMI kullanıcı kurar.

### E08-19 · Yetkinlik, gözlem ve servis işi bağında kapsam ve aktiflik (M08-D03)
- **Canlı:** YOK.
- **Yaklaşım:** Yetkinlik değerlendirmesi: başka birim yetkinliği 403, pasif 400. Gözlem: pasif kurs 400, başka birim kursu 403, kapsam dışı personel 404, kapsam dışı servis işi 404 (K4). Birimsiz kurs/yetkinlik kabul.
- **Kabul:** (1) Başka birim yetkinliği 403. (2) Pasif kursa gözlem 400. (3) Başka birimin servis işine bağlı gözlem 404 ve kayıt yok. (4) Birimsiz yetkinlik/kurs kabul.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim_gozlem.py`, `egitim_yetkinlik.py`, `backend/app/api/egitim.py`, `backend/tests/integration/test_egitim_kapsam.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-01, E08-08. · **Canlı risk:** Yok.

### E08-20 · Kişisel performans detaylarının `egitim.detay`'a bağlanması (M08-17; M08-16 özü)
- **Canlı:** KISMEN. Alanı yanıttan tamamen çıkarma kalıbı VAR (`sees_cost`, `api/reports.py:41-55`); eğitim için uygulanacak.
- **Yaklaşım:** Out şemaları iki katmanlı: `GozlemOzetOut` (tarih, aşama, puan, sonuç, kritik, gözlemci, gördü) ve `GozlemDetayOut(GozlemOzetOut)` (+ notlar, aksiyon_plani, madde puanları, gerekçeler). `_cikti(db, kayit, user)` `user.has("egitim.detay")` değilse ÖZET sınıfıyla serileştirir — alan `null` değil, YOK. Aynı kural yetkinlik `kanit`, belge `belge_no/aciklama`, faaliyet `kapanis_kaniti`, kişi kartı, liste, Excel ve ek uçları (`SAHIP_IZNI` gor = `egitim.detay`) için. Kişi kartı açılışı `kvkk.erisim_kaydet(amac="egitim.kart")`. Gözlem listeleri varsayılan yıl ± 1 ile sınırlı (M08-16 özü); ölçülmüş yavaşlık olmadıkça ek bölme yapılmaz.
- **Kabul:** (1) Yalnız `egitim.gor` sahibinin JSON'unda `notlar`, `aksiyon_plani`, `kanit` anahtarları yok. (2) `egitim.detay` ile var. (3) YONETIM rolünde detay yok. (4) Ekler `egitim.detay` olmadan 403. (5) Kart açılışı KVKK erişim logunda.
- **Dosyalar:** `backend/app/api/egitim.py`, `backend/app/api/attachments.py`, `backend/app/services/kvkk.py`, `frontend/src/pages/EgitimPage.tsx`, `frontend/src/pages/EgitimKisiKarti.tsx`, `backend/tests/integration/test_egitim_kvkk.py`.
- **Öncelik/Efor:** P2 / S · **Bağımlılık:** E08-01, E08-02. · **Canlı risk:** Düşük; `KISISEL_VARLIKLAR` genişler — KVKK erişim logu ekranı yeni varlık adlarını gösterir (test: mevcut `accounts/contacts/vehicles` sorguları aynı).

### E08-21 · Test verisi ve otomatik entegrasyon testleri (M08-D04)
- **Canlı:** KISMEN. Test altyapısı VAR (`tests/conftest.py`, PG17, FakeClock, `kullanici_ac`); eğitim testi YOK.
- **Yaklaşım:** `backend/tests/veri/egitim.py` fixture fabrikası (yalnız test paketinde; üretime uygulanamaz): 2 birim (GUVENLIK, HABERLESME), 6 personel (biri birimsiz, biri `is_active=false`), 2 kurs (birinde kritik madde), planlar (biri önceki yıl), oturum, gözlemler. Dev ortamı için aynı veri `seeds/dev.py --demo` altında (`ENV=dev` koruması `seeds/dev.py:141`). Yeni tablolar `users`/`service_orders` FK zinciriyle TRUNCATE CASCADE'e girer; yine de E01 emsaliyle `_TRUNCATE`'e açıkça eklenir. Testler: §6'daki dosyalar; her uçta 403/200, kapsam 404 + veri değişmedi (`db.refresh`), detay alanı yokluğu, FakeClock ile tarih kuralları.
- **Kabul:** (1) Fabrika idempotent (iki çağrı aynı sayıları verir). (2) E08-03, -04, -05, -14, -18, -19 kabul kriterleri otomatik testte yeşil. (3) Altın kayıt (932 iş / 552.825,00 TL) ve migration zinciri yeşil. (4) `ENV!=dev` iken `--demo` hata verir.
- **Dosyalar:** `backend/tests/veri/egitim.py`, `backend/tests/conftest.py`, `backend/app/seeds/dev.py`, `backend/tests/integration/test_egitim_*.py`, `backend/tests/unit/test_egitim_sonuc.py`.
- **Öncelik/Efor:** P2 / M · **Bağımlılık:** E08-03, -04, -05, -14, -18, -19. · **Canlı risk:** Düşük; `_TRUNCATE` listesine yalnız ekleme.

### E08-22 · Servis işine teknisyen atamasında yetkinlik/belge uyarısı (M08-04)
- **Canlı:** YOK.
- **Yaklaşım:** `service_competency_requirements(birim, tur, competency_id, min_seviye, course_id)` (eski `WorkTypeRules(UnitCode, WorkType)` anahtarının karşılığı E01 `birim` + `tur`). E01 atama servisi (`planla()` / toplu atama, E01-12) atama yazdıktan sonra `egitim_yetkinlik.atama_uyarilari(db, so, user_ids)` çağırır: kişinin güncel seviyesi < min, zorunlu kurs geçerliliği yok/dolmuş veya kişide açık kritik düzeltici faaliyet → yanıtta `uyarilar` ve `service_order_events` ATAMA olayı özetine "yetkinlik uyarısıyla atandı" notu. Atama ENGELLENMEZ (K11). Eşleme boşsa sıfır uyarı. Eşleme yönetimi `egitim.yaz` (`GET/PUT /yetkinlik-gereksinimleri`). PB (cihaz başına) işlere toplu atamada her iş için ayrı değerlendirilir; PB üretim kuralına dokunulmaz.
- **Kabul:** (1) XR seviyesi 2 olan teknisyen X-Ray PB işine (eşleme XR≥3) atanınca yanıt uyarılı, atama kayıtlı, olayda not. (2) Seviye ≥ eşik ve belge geçerliyse uyarı yok. (3) Eşleme boşsa uyarı yok. (4) Toplu atamada uyarı iş bazında listelenir.
- **Dosyalar:** `backend/app/models/egitim.py`, `backend/alembic/versions/<rev>_egitim_yetkinlik_esleme.py`, `backend/app/services/teknik_servis/egitim_yetkinlik.py`, `backend/app/services/teknik_servis/planlama.py` (E01/E02 atama), `backend/app/api/egitim.py`, `frontend/src/pages/ServisIsleriPage.tsx`, `backend/tests/integration/test_egitim_atama_uyarisi.py`.
- **Öncelik/Efor:** P3 / L · **Bağımlılık:** E01-12 (kimlik bazlı atama; M01-10 karşılığı), E08-03, E08-11. · **Canlı risk:** Düşük; E01 atama akışına yalnız okuma + yanıt alanı eklenir. Önlem: E01 atama testleri değişmeden yeşil; uyarı hesabı yalnız okuma sorgusudur, atama satırını ve durum geçişini değiştirmez.

### E08-23 · Yönetim Özeti: tıklanabilir KPI kutuları (kullanıcı doğrulamalı işlev; M08-13, M08-07 KPI'ları)
- **Canlı:** KISMEN. `Statistic` bileşeni ve mobilite paneli VAR ama kutular tıklanamıyor (`pages/PanelPage.tsx:76-200`); eğitim KPI'sı YOK.
- **Yaklaşım:** E01-14 kalıbı: `egitim_rapor.py:KPI_TANIMLARI` sözlüğü; sayı ve liste AYNI filtre fonksiyonundan. `GET /ozet?yil=&birim=` kutular: yıllık gerçekleşme % (zamanında/geç/açık), gözlem başarı oranı (ortalama ikincil), açık kritik uygunsuzluk (+ en eski açık yaşı), geciken 30/60/90, süresi dolan/dolacak belge, hedefin altındaki yetkinlik (kritik ayrı). Her kutu `{kod, baslik, deger, yol}`; ön yüz tıklamada `navigate("/egitim?sekme=...&kpi=<kod>")`, liste uçları `kpi` parametresiyle aynı filtreyi uygular. Birim bazlı ilerleme çubukları korunur. Eğitim saati yalnız bilgi.
- **Kabul:** (1) Her kutunun sayısı = tıklanınca açılan listenin `X-Toplam-Kayit` değeri (test her KPI kodu için). (2) Kapsam dışı personel sayılmaz. (3) İptal kayıtlar sayılmaz. (4) Kritik kutusu ortalamadan bağımsız.
- **Dosyalar:** `backend/app/services/teknik_servis/egitim_rapor.py`, `backend/app/api/egitim.py`, `frontend/src/pages/EgitimPage.tsx`, `backend/tests/integration/test_egitim_ozet.py`.
- **Öncelik/Efor:** P1 / M · **Bağımlılık:** E08-02, E08-05 (kutular ilgili maddeler geldikçe açılır). · **Canlı risk:** Yok; mobilite `PanelPage` ve `services/reports.dashboard` değişmez.

---

## 7. Uygulama sırası

1. E08-01 (E01-01 sonrası) → E08-02 → E08-03 → E08-04 (a,b) → E08-05 → E08-06 (P1) → E08-23 → E08-21 test verisi bu adımla birlikte.
2. Yeni özellikler: E08-07 → E08-08 → E08-09 → E08-10 → E08-11 (çekirdek) → E08-12 (aşama 1).
3. Eksikler: E08-13 + E08-14 → E08-15 → E08-16 (P2) → E08-17.
4. Güvenlik: E08-18 + E08-19 → E08-20.
5. P3: E08-22, E08-16 (bağ), E08-04-c, E08-11 (öneri), E08-12 (aşama 2).

Her adım sonunda: `make test` (altın kayıt dahil), `test_migration_zinciri`, `ruff`, `npm run build`, `oxlint`.

## 8. İzlenebilirlik

| Kaynak | Hedef |
|---|---|
| Envanter #39-46, E-18, R-80/84/85/87 | E08-01, E08-02, E08-23 |
| M08-08 | E08-03 |
| M08-11 | E08-04 |
| M08-13 | E08-05, E08-23 |
| M08-09 | E08-06 |
| M08-01 | E08-07 |
| M08-02 | E08-08 |
| M08-05 | E08-09, E08-01 (rol) |
| M08-06 | E08-10 |
| M08-03 | E08-11 |
| M08-07 | E08-12 |
| M08-12 | E08-13 |
| M08-D01 | E08-14 |
| M08-D02 | E08-15 |
| M08-10 | E08-16 |
| M08-15 | E08-17 |
| M08-14 | E08-18 |
| M08-D03 | E08-19 |
| M08-17 | E08-20, E08-01 |
| M08-16 (dotnet_specific) | öz: E08-02 kabul (yıl ± 1 sınırı), E08-20 (alan ayıklama) |
| M08-D04 | E08-21 |
| M08-04 | E08-22 |
