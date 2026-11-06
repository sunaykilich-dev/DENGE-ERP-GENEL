# E09: Saha / Zaman Takibi ve Mobil Teknisyen Görünümü (Canlı ERP Entegrasyon Tasarımı)

> Tarih: 2026-10-21 · Hedef: Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdi: `analiz/02_moduller/_ozet/09_saha_zaman.json` (denetçi onaylı 19 madde), `09_saha_zaman_tasarim.md`, `09_saha_zaman_denetim.md`, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`, `01_is_emirleri_entegrasyon.md` (E01), `04_planli_bakim_entegrasyon.md` (E04), `05_haberlesme_atolye_entegrasyon.md` (E05).
> Bu belge yalnız tasarımdır; kaynak koda dokunulmadı. Dosya:satır referansları `backend/app/...` ve `frontend/src/...` köklerine göredir ve 2026-10-21'de kod okunarak doğrulandı.
> Madde kimlikleri `E09-NN` biçimindedir. Kaynak maddeler `M09-xx` olarak yazıldı.

---

## 0. Özet

- **Canlı ERP'de zaman takibi, saha sayacı ve mobil teknisyen ekranı hiç yok.** Kullanım kılavuzu bunu açıkça söylüyor: "Mobil saha uygulaması yok — işler ofisten girilir" (`docs/KULLANIM-KILAVUZU.md:420`). `permissions.py:87-88` da "Saha Teknisyeni (mobil) rolü yok" diyor. Mobilite iş emrindeki tek zaman alanı `work_orders.started_at` (`models/workorder.py:117`); bu alan süre kaydı değildir ve **dokunulmaz**.
- Altyapının neredeyse tamamı yeniden kullanılır: `Clock` (`clock.py:14-34`), `sayfala` (`api/deps.py:170-190`), `sees_cost` (`api/deps.py:103-105`), uyarı merkezi (`services/uyarilar.py:47`), ayarlar (`services/settings.py:33-93`), worker (`worker.py:120-125`), Excel (`services/export.py:45`), denetim izi, EXCLUDE kalıbı (`models/sim.py:166-176` `where=` emsali, `models/stock.py:88-97` açık dönem kısmi tekil indeksi) ve `main.py:131-148` (`ex_`/`uq_` önekli kısıt → 409).
- **Tek yeni tablo:** `service_time_entries`. Canlı sayaç bölümü, elle girilen kayıt, mola ve düzeltme aynı tabloda tutulur. Açık bölümün `ended_at` değeri NULL'dır. Kişi başına çakışmazlık bir **EXCLUDE** kısıtıyla, kişi başına tek açık sayaç ise **kısmi tekil indeksle** veritabanında güvenceye alınır. Mola bu tabloda yer alır ama kişi-saate hiçbir zaman katılmaz. Süre kaydı yoksa sonuç "EKSİK" olarak hesaplanır; 0 yazılmaz ve bu değer saklanmaz.
- Zaman, E01 servis iş emrine (`service_orders`) bağlanır. Mobilite `work_orders` zincirine hiçbir şekilde yazılmaz.
- Yeni izin yalnız `zaman.yaz`. Yönetici eylemleri (iptal, düzeltme, başkası adına kayıt, 2 günden eski kayıt) **mevcut** `servis.planla` iznini kullanır; bu izin eski `workorders.assign`'ın karşılığıdır (E01 K23). Ekip görünümü `rapor.gor` ile açılır. Eski analizde reddedilen `timetracking.manage` ve `timetracking.team.view` açılmaz. `maliyet.gor` kümesi değişmez.
- Kaynak maddeler: 19. .NET'e özgü olan tek madde M09-15'tir. Ayrı madde olarak taşınmadı, özü (SQL'de süzme, indeksler, hafif "benim sayacım" ucu, varsayılan 31 günlük aralık) E09-01, E09-02 ve E09-14'ün kabul kriterlerine eklendi.
- Kullanıcının eski sistemde bizzat doğruladığı işlevler korunur:
  - Tıklanabilir KPI kutuları: E09-14 (Zaman Takibi sayfası) ve E01-14'teki "süre kaydı eksik" kutusu (E09-11 bunu besler).
  - Toplu planlama ve atama: E09-09. Toplu atamada açık sayaç kuralı uygulanır, akış bozulmaz. Mobil liste E02 planını okur.
  - Excel dışa aktarım: E09-14 ve E09-11 (iş Excel'ine süre kolonları).
  - Cihaz başına PB iş emri: E09-04 (17 PB tek ziyaret kartında, her iş ayrı seçilir) ve E09-03 (sayaç bir sonraki cihaza boşluksuz taşınır, cihaz bazlı süre korunur).

---

## 1. Canlı karşılık taraması (kod okunarak)

| Konu | Canlıda ne var | Kanıt |
|---|---|---|
| Süre kaydı / canlı sayaç tablosu | YOK | `models/` altında yok; `models/workorder.py:117` yalnız `started_at` |
| Mobil teknisyen ekranı | YOK. Yalnız genel düzen 375 px'te kullanılabilir tutuluyor; yan menü `lg` altında 56 px'e daralıyor | `components/AppLayout.tsx:133-137, 203`; `docs/KULLANIM-KILAVUZU.md:420` |
| Saat kaynağı | VAR: `Clock` protokolü, `RealClock` = uygulama sunucusunun UTC saati; uygulama kodunda `datetime.now()` yasak | `clock.py:8-20`, `api/deps.py:19-27`, `worker.py:26` |
| Yerel gün (Europe/Istanbul) | YOK. Kod "bugün"ü `clock.now().date()` ile UTC olarak alıyor; 00:00-03:00 arasında gün bir önceki gün sayılıyor. İmajda `tzdata` da yok (`python:3.13-slim`) | `api/sims.py:138`, `api/workorders.py:210`, `backend/Dockerfile:1` |
| Sunucu saatini istemciye bildirme | YOK | `main.py:211-213` (`/api/health` yalnız `status/env`) |
| Uyarı merkezi | VAR. Saklanmaz, hesaplanır, izne tabidir. "Okundu/ack" altyapısı YOK | `services/uyarilar.py:9-17, 47-192`; `components/UyariZili.tsx:38-47` |
| Worker | VAR, periyodik görevler | `worker.py:120-125` |
| Ayarlar | VAR, `DEFAULTS` beyaz listesi; zamanla ilgili anahtar yok | `services/settings.py:33-93` |
| Kişi kimliği | `users.id` + `full_name`; ayrı personel tablosu yok | `models/user.py:11-19` |
| Rapor/Excel | VAR (`_xlsx`, `rapor.gor` / `rapor.disaaktar`); kişi-saat raporu YOK | `api/reports.py:29-55`, `services/export.py:45-61` |
| Maliyet gizliliği | VAR | `api/deps.py:103-105`, `api/reports.py:41-55` |
| EXCLUDE + kısmi koşul | VAR (emsal) | `models/sim.py:166-176`, `models/workorder.py:213-235`, `models/stock.py:88-97` |
| Kısıt adı → 409 mesajı | VAR | `main.py:131-148` |
| Kapsam | Yalnız `KENDI_MUSTERILERI`. Birim kapsamı E01-01 ile gelir | `permissions.py:80-82`, `services/accounts.py:29-61` |
| Servis iş emri, atama, durum makinesi, olay geçmişi | Canlıda YOK; E01'de tasarlandı (`service_orders`, `service_order_assignments`, `SERVIS_IS_EMRI`, `service_order_events`, `service_holds`) | `01_is_emirleri_entegrasyon.md` §2, §4 |
| Plan tarihi / ziyaret | Canlıda YOK; E02 (`service_plans`) tasarlayacak (E01 K20) | `01_is_emirleri_entegrasyon.md` K20 |
| Test altyapısı | VAR: PG17, `_TRUNCATE ... CASCADE` (`users` dahil), FakeClock | `tests/conftest.py:41-49, 157-167` |

**Sonuç:** Modülün iş kuralı katmanı tamamen YOK. Altyapı VAR ve yeniden kullanılır. Bu yüzden maddelerin çoğu "YOK", altyapıya yaslananlar "KISMEN" işaretlendi.

---

## 2. Veri modeli

Dosya: `backend/app/models/teknik_servis.py`. E01 ile aynı dosyadır; büyürse `models/servis_zaman.py` olarak bölünür. Model `models/__init__.py`'ye import ve `__all__` ile eklenir.

### 2.1 `service_time_entries` (yeni)

Mixin'ler: `PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin`.
- **Yumuşak silme = iptal.** Kayıt fiziksel olarak silinmez. İptal, `is_deleted/deleted_at/deleted_by` ile `iptal_turu` ve `iptal_gerekcesi` alanlarından oluşur.
- **SourceMixin** V1.20.1 göçü içindir (`uq_ste_kaynak`).

| Kolon | Tip | Not |
|---|---|---|
| service_order_id | BigInteger FK `service_orders` RESTRICT NOT NULL | Zaman yalnız servis işine yazılır; `work_orders`'a hiç yazılmaz |
| user_id | BigInteger FK `users` RESTRICT NULL | **Kimlik** (M09-13). NULL yalnız göçte eşleşmeyen satırda olabilir (`ck_ste_kisi`) |
| kaynak_personel_adi | String(100) NULL | Yalnız göç: eski isim metni. Gösterim ve eşleştirme raporu için kullanılır |
| faaliyet | String(20) NOT NULL | `ck_ste_faaliyet` IN (YOL, SAHA, BEKLEME, MOLA, UZAKTAN, ATOLYE, TEST, DIGER) → `ZAMAN_FAALIYETLERI` |
| bekleme_nedeni | String(30) NULL | `ck_ste_bekleme_neden`: faaliyet='BEKLEME' ise NOT NULL ve E01 `SERVIS_BEKLEME_NEDENLERI` içinde (OpsHolds sözlüğünün karşılığı) |
| started_at | timestamptz NOT NULL | Canlıda `clock.now()`, elle girişte istemciden gelir |
| ended_at | timestamptz NULL | NULL = açık canlı bölüm |
| kaynak | String(24) NOT NULL | `ck_ste_kaynak` IN (CANLI, MANUEL, KULLANICI_DUZELTMESI, YONETICI_DUZELTMESI). **Server default YOK**; her INSERT kaynağı açıkça yazar (denetimin `DEFAULT 'Manuel'` uyarısı) |
| kapanis_turu | String(16) NULL | IN (BITIR, GECIS, UNUTULDU, YONETICI). GECIS: değiştir, mola, devam ve taşı. Açık bölümde ve MANUEL kayıtta NULL |
| gerekce | String(300) NULL | Manuel kayıt gerekçesi veya düzeltme gerekçesi. `ck_ste_duzeltme_gerekce`: kaynak *_DUZELTMESI ise NOT NULL |
| duzelten_id | FK users SET NULL | Bölümü kapatan veya düzelten kişi (sahibi ya da yönetici) |
| onceki_bolum_id | FK `service_time_entries` SET NULL | Zincir: GECIS ile açılan bölüm öncekini gösterir. DEVAM'da son mola dışı faaliyet bu zincirden bulunur |
| girildi_at | timestamptz NOT NULL | Kaydın sisteme girildiği an (`clock.now()`); gecikmeli manuel kayıt ölçüsü. `created_at` DB saatidir, FakeClock'la sınanamaz; bu yüzden ayrı tutulur |
| konum_notu | String(200) NULL | Serbest metin. GPS YOK (K3) |
| aciklama | Text NULL | Yapılan iş notu |
| iptal_turu | String(20) NULL | IN (GERI_ALINDI, YONETICI_IPTAL, KAYIT_IPTAL, GOC_IPTAL, GOC_CAKISMA) |
| iptal_gerekcesi | String(300) NULL | `ck_ste_iptal_gerekce`: iptal_turu IN (YONETICI_IPTAL, KAYIT_IPTAL) ise NOT NULL |

Kısıtlar ve indeksler:
- `ck_ste_aralik`: `ended_at IS NULL OR ended_at > started_at`
- `ck_ste_azami_sure`: `ended_at IS NULL OR ended_at <= started_at + interval '18 hours'` (eski CHECK ≤ 1080 dk karşılığı)
- `ck_ste_acik_yalniz_canli`: `ended_at IS NOT NULL OR kaynak = 'CANLI'`
- `ck_ste_iptal`: `is_deleted = (iptal_turu IS NOT NULL)`
- `ck_ste_kisi`: `user_id IS NOT NULL OR (source_system IS NOT NULL AND kaynak_personel_adi IS NOT NULL)`
- `uq_ste_acik_kisi`: kısmi tekil indeks `(user_id) WHERE ended_at IS NULL AND is_deleted = false`. Kişi başına **tek aktif sayaç** sağlar (eski `UX_LiveSessions_OneActivePerUser`). Emsal: `models/stock.py:91 uq_custody_acik`.
- `ex_ste_kisi_cakisma`: `ExcludeConstraint(("user_id","="), (literal_column("tstzrange(started_at, ended_at, '[)')"),"&&"), using="gist", where=text("is_deleted = false AND user_id IS NOT NULL"))`. Emsal: `models/sim.py:166-176`.
  - Canlı, manuel, mola ve düzeltme kayıtlarının **hiçbiri** aynı kişide çakışamaz.
  - Açık bölümün üst sınırı NULL olduğu için sonsuz sayılır. Bu yüzden çalışan sayacın başlangıcından sonraya manuel kayıt girilemez.
  - Yarı açık `'[)'` aralık, ardışık bölümlerin aynı saniyede bitip başlamasına izin verir (Mola → Devam ve Taşı boşluksuz olur).
  - Kısıt adı `ex_` ile başladığı için `main.py:131-148` bunu 409 + Türkçe mesaja çevirir.
- `ix_ste_is_baslangic (service_order_id, started_at)`, `ix_ste_kisi_baslangic (user_id, started_at)`, `ix_ste_girildi (girildi_at)`. Bu indeksler M09-15'in özüdür: iş ve kişi bazlı okuma SQL'de yapılır.
- `UniqueConstraint("source_system","source_ref", name="uq_ste_kaynak")`.

Python sabitleri (`models/teknik_servis.py`):
- `ZAMAN_FAALIYETLERI`
- `KISI_SAATE_DAHIL = ZAMAN_FAALIYETLERI - {"MOLA"}`
- `ZAMAN_KAYNAKLARI`
- `SAHA_AKIS = {"YOLA_CIKTIM": "YOL", "SAHAYA_VARDIM": "SAHA"}`

### 2.2 Genişletilen yapılar (yalnız ekleme)

- `services/settings.py:33-93` `DEFAULTS`:
  - `zaman_manuel_geri_gun: 2`: `servis.planla` olmayan kişinin geriye kayıt sınırı
  - `zaman_manuel_gerekce_esik_dk: 30`: bitişi bundan eski manuel kayıtta gerekçe zorunlu
  - `zaman_geri_alma_dk: 5`
  - `zaman_asgari_bolum_dk: 1`
  - `zaman_uzun_sayac_uyari_saat: 10`
  - `zaman_gecikmeli_manuel_saat: 24`
  - `zaman_rapor_varsayilan_gun: 31`
  - `servis_iscilik_saat_maliyeti_tl: 0.0`: 0 "tanımlı değil" demektir; maliyet hesaplanmaz, null döner
- `permissions.py`: `zaman.yaz` (§3).
- E01 `services/teknik_servis/atama.py`: `ata()` ve `toplu_ata()` içine açık sayaç kontrolü (E09-09).
- E01 `durum_degistir()`: IPTAL ve TAMAMLANDI'da açık sayaç kontrolü; `kaynak="SAYAC"` için YOLA_CIKILDI ve SAHADA hedefleri `UC_HEDEFLERI`'ne eklenir (E09-10).
- E04 `POST /formlar/{id}/tamamla`: süre eksik uyarısı (E09-12).
- `services/uyarilar.py:47 topla()`: yeni `zaman.*` blokları (E09-06).
- `worker.py:120-125 GOREVLER`: `saat-farki` görevi (E09-16).
- `backend/pyproject.toml`: `tzdata` bağımlılığı. `ZoneInfo("Europe/Istanbul")` slim imajda ve Windows'ta bu paket olmadan çalışmaz.
- `components/AppLayout.tsx`: `<AktifSayacBandi/>` (yalnız `yetkili("zaman.yaz")` ise çizilir) ve iki MENU kalemi.

### 2.3 Migration

- `make makemigration m="servis_zaman_kaydi"`. `down_revision` = E01/E03 zincirinin o anki tek head'i (bugün `b30e012dd879`; kodlama başında `alembic heads` ile doğrulanır).
- Dosya başına NEDEN docstring'i yazılır: kişi-saatin tek tablo + EXCLUDE ile korunduğu, molanın neden aynı tabloda tutulduğu, neden server default olmadığı.
- Yeni tabloda autogenerate EXCLUDE'u `postgresql.ExcludeConstraint(..., where=...)` biçiminde üretir ve bu biçim korunur (00 §2).
- Downgrade: tabloyu düşürür. head→base→head testi EXCLUDE sayısını doğrular.
- Canlı tablolarda hiçbir CHECK veya EXCLUDE değişmez. `service_order_events` CHECK'i de değişmez: zaman olayları mevcut `DUZELTME` ve `NOT` türleriyle yazılır (K10).

### 2.4 Hesaplanan (saklanmayan) değerler: `services/teknik_servis/zaman.py`

- `sure_ozeti_toplu(db, is_idler) -> dict[int, SureOzeti]`: Tek bir SQL toplama sorgusu kullanır. **Ekran, liste, Excel, panel ve uyarı aynı fonksiyonu çağırır** (eski H-02: sayı ile liste farklı koşul).
- `SureOzeti` alanları:
  - `kisi_saat_dk | None`: MOLA hariç, iptal edilmemiş, kapalı bölümler.
  - `faaliyet_kirilimi`.
  - `mola_dk` (bilgi, hariç).
  - `ilk_yol_at`, `ilk_varis_at` (ilk SAHA başlangıcı), `son_bitis_at`.
  - `kisi_bazli: {user_id: dk}`.
  - `sure_durumu ∈ {TAM, KISMI, EKSIK, BEKLENMIYOR}`.
  - `sapma_dk | None`.
- `sure_durumu` kuralı:
  - **BEKLENMIYOR**: iş hiç çalışılmamış bir durumda (MUSTERI_TALEBI, PLANLAMADA, PLANLANDI, IPTAL) ya da sonucu TELEFON/UZAKTAN kanalıyla açılışta çözülmüş (E01-06). Telefonla çözülen işler "eksik" sayılırsa sayaç şişer (denetimin "şişik sayaç" bulgusu).
  - **EKSIK**: çalışılmış bir durumda (YOLA_CIKILDI, SAHADA, ISLEMDE, ATOLYEDE, KARGODA, TEST_KONTROL, TAMAMLANDI, KAPATILDI) hiç geçerli bölüm yok.
  - **KISMI**: aktif TEKNISYEN atamalarından en az birinin geçerli bölümü yok.
  - **TAM**: diğer durumlar.
- `kisi_saat_dk` kayıt yoksa **None** döner; ekranda "Süre kaydı eksik" yazılır, Excel hücresi boş kalır.
- `sapma_dk = kisi_saat_dk - tahmini_sure_dk`. Yalnız gerçek kayıt varsa ve E02 `service_plans.tahmini_sure_dk` doluysa hesaplanır; yoksa None.
- `yerel_gun(an) -> date` ve `yerel_gun_araligi(gun) -> (UTC bas, UTC bit)`. `ZoneInfo("Europe/Istanbul")` kullanılır. "Bugün", "dün" ve "gün değişmiş" kontrollerinin tamamı buradan geçer.

---

## 3. İzinler, kapsam ve roller

### 3.1 Yeni izin (`permissions.py:14-77` `PERMISSIONS`, modül "Teknik Servis")

| Kod | Açıklama | Roller |
|---|---|---|
| `zaman.yaz` | Kendi canlı sayacını yönetir, kendi adına sınırlı geçmişe elle süre kaydı girer, unuttuğu sayacı kapatır, ilk 5 dakikada geri alır | SERVIS_TEKNISYEN, SERVIS_SEF, ATOLYE, SERVIS_YONETICI |

Mevcut ya da E01'de tanımlanan izinlerin bu modüldeki kullanımı:

| Eylem | İzin |
|---|---|
| İş detayında zaman kayıtlarını ve özeti görme | `servis.gor` + E01 iş erişimi (`is_erisimi_yok_mu`) |
| Yönetici iptali/düzeltmesi, kayıt iptali, başkası adına kayıt, `zaman_manuel_geri_gun`'den eski kayıt | `servis.planla` (eski `workorders.assign` karşılığı; Şef ve Müdürde var, Teknisyende yok) |
| Ekip zaman sayfası, aktif sayaçlar, kişi dağılımı | `servis.gor` + `rapor.gor` (eski `reports.view` kararıyla aynı) |
| Zaman Excel'i | `servis.gor` + `rapor.disaaktar` |
| İşçilik maliyeti | `maliyet.gor` (`sees_cost`); yoksa alan yanıtta hiç yer almaz |

- `sistem.kullanici` (eski `users.manage`) bu uçların hiçbirine yetki vermez (M09-16).
- `maliyet.gor` sahipleri kümesi değişmez (`tests/unit/test_permissions.py:21-26`).
- `ozellestirildi=True` olan DB rollerine `zaman.yaz` kendiliğinden inmez; seed bunu log'a yazar (`models/rbac.py:64-69`). Kurulum notunda elle ekleme listesi verilir.

### 3.2 Kapsam

- Tüm iş bazlı uçlar E01'in `is_erisimi_yok_mu(db, user, so, yazma)` fonksiyonunu kullanır (müşteri + birim + KENDI_ISLERI). Erişim yoksa 404 döner ve veri değişmez.
- **İstisna (M09-11, M09-10, M09-D01):** Oturum sahibi kendi açık bölümünü **iş erişimine ve atamaya bakılmadan** bitirebilir, geri alabilir ve unuttum akışıyla kapatabilir. Kontrol yalnız `bolum.user_id == user.id` üzerinden yapılır. Başka kişinin bölümü 403 döner.
- Ekip uçları (`/zaman/ozet`, `/zaman/kayitlar`, `/zaman/aktif`, Excel) `service_orders` ile JOIN üzerinden `kapsam_musteri(..., ServiceOrder.customer_id)` ve `kapsam_birim(..., ServiceOrder.birim)` uygular. A biriminin şefi B biriminin sayaçlarını göremez ve sayısını da göremez.
- "Bugünüm" ve "benim sayacım" uçları yalnız `user_id = user.id` satırlarını döndürür. Başkasının kaydı görünmez (M09-04 kabul 3).

### 3.3 Roller

Mevcut roller değişmez. E01 §3.3'teki yeni rollere yalnız `zaman.yaz` eklenir. `TEKNIK_SERVIS` (mobilite montaj ve onay rolü) bu izni ALMAZ.

---

## 4. Saha akışı (sunucu kuralları)

```
Sayaç yok:       [Yola Çıktım] → YOL      [Sahaya Vardım] → SAHA      (masaüstü: Uzaktan/Atölye/Test/Diğer)
YOL açık:        [Sahaya Vardım] → SAHA   [Mola] [Bekleme(neden)] [Bitir]
SAHA açık:       [Mola] → MOLA            [Bekleme(neden)] → BEKLEME  [Sonraki Cihaza Geç] [Bitir]
MOLA açık:       [Devam] → son mola dışı faaliyet (sunucu bulur)   [Bitir]
BEKLEME açık:    [Devam] → son bekleme/mola dışı faaliyet          [Bitir]
İlk 5 dk:        [Yanlış başlattım] (geri al)
>18 sa / dünden: [Unuttum, gerçek bitişi gir]
```

`services/teknik_servis/zaman.py` içindeki her geçiş tek transaction'da şu adımları uygular:
1. Kullanıcının açık bölümü `SELECT ... FOR UPDATE` ile kilitlenir.
2. İstekteki `bolum_id` ve `version` doğrulanır. Uyuşmazsa 409 döner: çift basışta ikinci istek artık açık olmayan bölümü gösterdiği için reddedilir.
3. `an = clock.now()` alınır.
4. Kontroller yapılır: asgari 1 dk (400), azami 18 sa (400 + "Unuttum akışını kullanın").
5. Açık bölüm `ended_at = an` ve `kapanis_turu` ile kapatılır.
6. Gerekiyorsa yeni bölüm `started_at = an`, `onceki_bolum_id` ve `kaynak='CANLI'` ile açılır.
7. `flush` yapılır. EXCLUDE ihlali olursa IntegrityError oluşur ve 409 döner; transaction geri alınır, iki taraf da değişmez.

Servis katmanı commit yapmaz; commit API'dedir (00 kural 1).

---

## 5. Kararlar (kullanıcıya soru sorulmadı)

- **K1 Tek tablo.** Eski sistemdeki iki tablo (`WorkOrderLiveSessions` + `WorkOrderTimeLogs`) birleştirildi. Molanın manuel kayıtla çakışabilmesi, düzeltmenin oturumdan kopması ve iki kaynak arasında isim/kimlik uyumsuzluğu eski hataların köküydü. Tek tablo ve tek EXCLUDE bu üç sorunu yapısal olarak kapatıyor. 00, E04 ve E05 de yalnız `service_time_entries` adını kullanıyor. Kolon adları canlı kurala göre İngilizcedir; E05'teki "`bitis IS NULL`" ifadesi `ended_at IS NULL` olarak okunmalı.
- **K2 Hesabı olmayan personel (S1).** Herkes kendi hesabından süre tutar (eski karar). Hesabı veya telefonu olmayan saha personeli için E01 K15'e göre girişsiz/pasif kullanıcı açılır. Bu kişinin süresini şef `servis.planla` ile "başkası adına manuel kayıt" olarak girer. Kayıt `kaynak=MANUEL` ve `created_by=şef` olur ve disiplin sütunlarında görünür.
- **K3 GPS yok (S3).** Konum kaydedilmez. KVKK aydınlatma ve açık rıza süreci, araç takip entegrasyonu gündeme gelene kadar ertelenir. Yalnız serbest `konum_notu` tutulur. Harita bağlantısı adres metniyle kurulur ve yalnız kullanıcı dokunduğunda açılır.
- **K4 Otomatik durum (S4, M09-09a): EVET, sınırlı.** "Yola Çıktım" ile iş PLANLANDI ise YOLA_CIKILDI olur. "Sahaya Vardım" ile iş PLANLANDI veya YOLA_CIKILDI ise SAHADA olur. Geçiş E01 `durum_degistir(kaynak="SAYAC")` üzerinden yapılır ve geçmişe tek DURUM satırı yazar. Diğer durumlar (BEKLEMEDE, ISLEMDE, ATOLYEDE …) değişmez. *Gerekçe:* E01-14 panelindeki "sahada" kutusu bugün elle güncellemeye bağlı; sayaç bu bilgiyi zaten üretiyor ve E01 makinesi bu geçişlere izin veriyor.
- **K5 Geriye dönük sınır (S5).** 2 gün (`zaman_manuel_geri_gun`) ve yerel gün sınırı uygulanır (dünden önceki gün dahil). Daha eskisi `servis.planla` ister. Manuel kayıt için şef onay akışı **açılmaz**: kayıt anında geçerli olur, disiplin sütunlarında ve "Giren" kolonunda görünür. *Gerekçe:* Onay kuyruğu saha yükü getirir ve organizasyon şeması gelmeden onaylayıcıyı belirlemek mümkün değil.
- **K6 Uzun sayaç eşiği (S6).** 10 saat veya başlangıcın yerel günü bugünden önce. Uyarı `servis.planla` sahibi şef ve müdüre birim kapsamında gider; sayaç sahibine de "kendi sayacın" uyarısı olarak gider.
- **K7 "Ack" altyapısı açılmaz.** Canlı uyarı merkezi bilinçli olarak "saklanmaz, hesaplanır" (`services/uyarilar.py:9-12`). Uyarı yalnız koşul sürdükçe görünür ve sayaç kapatıldığında kendiliğinden kaybolur. Eski "ack sonrası aynı gün çıkmaz" kabulü "sayaç kapanınca kaybolur, açık kaldıkça görünür" olarak uyarlandı. Gerekçe: unutulan sayaç düzeltilmesi gereken bir veri hatasıdır; susturulması değil düzeltilmesi istenir.
- **K8 Şefin günlük "kontrol edildi" kapatması (S7).** Açılmaz (bordro değil; ek yük).
- **K9 Mesai dışı ayrımı (S8).** Bu aşamada rapora eklenmez. Mesai tanımı (saat ve tatil takvimi) yok; uydurma mesai tanımı yanlış veri üretir. Ayrıntı Excel'inde yerel başlangıç saati ve haftanın günü kolonu bulunur, böylece kullanıcı kendisi süzebilir.
- **K10 Olay geçmişi.** Her başlat ve bitir işlemi `service_order_events`'e yazılmaz; günde yüzlerce satır zaman çizelgesini boğar ve zaman tablosu zaten kronolojiktir. Geçmişe yazılanlar:
  - Otomatik durum geçişi (DURUM; `durum_degistir` yazar).
  - Yönetici iptali ve düzeltmesi, unuttum düzeltmesi, kayıt iptali (`DUZELTME`, `veri={"alan":"zaman", "bolum_id":…}`).
  - "Süre kaydı eksik olarak kapatıldı" (`NOT`).
  
  E01'in `ck_soe_tur` CHECK'i değişmez. Aynı işlemler ayrıca `audit.log("service_time_entries", ...)` ile aynı transaction'da denetime yazılır. Rutin başlat ve bitir denetime yazılmaz; tablonun kendisi (`created_by`, `duzelten_id`, `girildi_at`) izdir.
- **K11 Ekip arkadaşlarının süresi (S10).** İş detayında aynı işin tüm bölümleri kişi adıyla görünür; "Tam/Kısmi" bunu gerektirir ve eski davranış da buydu. "Bugünüm", "benim sayacım" ve kişi bazlı listeler yalnız kişinin kendisini gösterir.
- **K12 Sahada çalışan şef (S11).** Sayaç, işte aktif atama satırı olan herkesi (rol TEKNISYEN veya SEF) kabul eder. "Tam/Kısmi" hesabında zorunlu kişi yalnız aktif TEKNISYEN atamalarıdır; şefin kaydı varsa toplam kişi-saate eklenir.
- **K13 Hafta sonu unutulan sayaç (S12).** Teknisyen kendisi düzeltir (E09-07), şef onayı gerekmez. Kayıt `KULLANICI_DUZELTMESI` olarak işaretlenir, disiplin sütununda ve uyarı geçmişinde görünür. Şef isterse `servis.planla` ile iptal edip yeniden girer.
- **K14 Toplu ziyarette yol ve bekleme (S2).** Kullanıcı kararı gelene kadar yol ilk iş emrinde kalır (denetim kabulü). Dağıtım yapılmaz. Zaman raporunda "ziyaret toplamı" (aynı kişi + gün + müşteri + adres) ayrıca gösterilir ve PB'lerin cihaz başı süresinde "yol dağıtılmadı" notu yer alır. Böylece cihaz başı süre yanıltıcı olmaz.
- **K15 Asgari bölüm.** 1 dakika kuralı değiştir, bitir ve taşı için korunur (`zaman_asgari_bolum_dk`). Yanlış dokunuş 5 dakikalık geri alma ile çözülür. Azami bölüm 18 saattir; bu hem kod sabiti hem CHECK'tir, ayar değildir. Şemaya bağlı bir sınırı ayardan değiştirmek CHECK ile çelişirdi.
- **K16 Sayaç kendiliğinden kapanmaz.** Worker açık sayacı hiçbir zaman otomatik kapatmaz; uydurma bitiş saati yazmak "uydurma tarih yazılmaz" kuralına aykırıdır (00 §2).
- **K17 Saat kaynağı.** Tek kaynak `Clock`'tur (00 kural 10). Kayıt zamanları DB `now()` ile yazılmaz. Uygulama ve DB aynı Compose ağında, ikisi de UTC ve `timestamptz`; eski sistemdeki saat dilimi hatası (yerel saat ile UTC karışması) burada yapısal olarak yok. Kalan risk saat kaymasıdır; worker `saat-farki` görevi DB `now()` ile `clock.now()` arasındaki farkı ölçer ve 60 sn'yi aşarsa uyarı loglar. TZ/NTP altyapısı A4-06'dadır. İstemci farkı her yanıttaki `sunucu_zamani` ile düzeltilir.
- **K18 Yerel gün.** Canlı kodun UTC tarih kullanımına (`api/sims.py:138` vb.) dokunulmaz. Zaman modülü kendi `yerel_gun()` yardımcısını kullanır. Mevcut UTC-gün kullanımı ayrı gözlem olarak kayda geçer.
- **K19 Çevrimdışı (S9).** Kapsam dışıdır. Bağlantı yoksa düğmeler kilitlenir ve "Bağlantı yok — süreyi sonra elle girin" uyarısı çıkar. Sunucu saati kullanıldığı için çevrimdışı basış biriktirilip sonradan gönderilmez; çünkü bu sahte "canlı" kayıt üretir.
- **K20 Yeni izin sayısı.** Yalnız `zaman.yaz` açılır. Teknisyenin sayaç kullanabilmesi `servis.yaz`'dan ayrı tutulmalı: SERVIS_OPERASYON `servis.yaz` taşır ama sahaya çıkmaz ve sayacı yoktur. Eski analizde reddedilen yönetim ve ekip görünümü izinleri açılmaz.
- **K21 Göç (M09-13).** V1.20.1 `WorkOrderTimeLogs` ve tamamlanmış MOLA oturumları `app/migration/servis_zaman_goc.py` ile aktarılır.
  - İsim eşleştirme `users.full_name` üzerinden `tr_normkey` ile yapılır.
  - Eşleşmeyen veya birden çok kişiyle eşleşen satırlar `user_id=NULL` + `kaynak_personel_adi` ile aktarılır.
  - EXCLUDE'a takılan çakışan eski satırlar `is_deleted=true, iptal_turu='GOC_CAKISMA'` olarak saklanır.
  - Eski iptal satırları `GOC_IPTAL` ve "Eski sistemde gerekçesiz iptal" gerekçesiyle aktarılır.
  - **Hiçbir satır atılmaz.** Rapor eşleşen, eşleşmeyen, çoklu ve çakışan sayılarını verir.
  - Kaynak eşlemesi: `ResultTimeLogId` ile bağlı satır CANLI, diğerleri MANUEL.
  - İş emri eşlemesi E01 göçünün `source_ref`'i ile yapılır.
- **K22 İşçilik maliyeti.** Canlıda iç saat maliyeti tanımı yok. `servis_iscilik_saat_maliyeti_tl` ayarı eklenir; 0 "tanımlı değil" demektir. Maliyet = kişi-saat × ayar. Kayıt eksikse veya ayar 0 ise null döner, 0 yazılmaz. Alan yalnız `sees_cost` ise yanıtta yer alır.
- **K23 Mobil ekran ayrı uygulama değildir.** Aynı React SPA içinde, AppLayout altında `/benim-islerim` rotasıdır. PWA ve offline kapsam dışıdır. Menüde "İş Emirleri" (mobilite) ve "Servis İşleri"nden ayrı, "Benim İşlerim" adıyla durur.
- **K24 Saha beklemesi ile iş beklemesi ayrıdır.** Sayaçtaki BEKLEME faaliyeti kişinin sahada beklediği süredir ve kişi-saate dahildir. İşin durumunu BEKLEMEDE yapmaz. İş beklemesi E01-05 ucuyla verilir. İkisi aynı neden sözlüğünü paylaşır (`SERVIS_BEKLEME_NEDENLERI`). Mobil kartta "İşi de beklemeye al" kısayolu iki çağrıyı arka arkaya yapar.

---

## 6. Maddeler

### E09-01 · Zaman kaydı veri modeli: kimlik, kaynak, gerekçe, iptal, çakışmazlık (M09-08, M09-13; öz: M09-15)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `service_time_entries` tablosu ve kısıtları (§2.1), migration `servis_zaman_kaydi`, `DEFAULTS` anahtarları.
  - `services/teknik_servis/zaman.py`:
    - `@dataclass ManuelKayitGirdisi`, `class ZamanHatasi(ValueError)`.
    - `manuel_kaydet(db, so, girdi, user, clock)`. Kurallar:
      - Bitiş `clock.now()`'dan ileri olamaz (400).
      - Başlangıç < bitiş ve süre ≤ 18 sa (400).
      - Bitiş `zaman_manuel_gerekce_esik_dk`'dan eskiyse gerekçe zorunlu (400).
      - `servis.planla` yoksa kayıt yalnız kendi adına girilir (başkası adına 403) ve başlangıç `zaman_manuel_geri_gun` yerel gün sınırı içinde olmalı (400).
      - Kişi işte aktif atamalı olmalı (400); yönetici geçmiş ataması olan kişi adına da girebilir.
      - İş IPTAL ise 409.
      - Çakışma kontrolü EXCLUDE'dadır: canlı, mola ve diğer manuel kayıtların hepsi 409 döner.
    - `kaydi_iptal_et(db, kayit, gerekce, user, clock)`: `servis.planla` ister; gerekçe zorunlu; açık bölüm bu uçla iptal edilemez (E09-06'yı kullan).
  - Uçlar (`api/teknik_servis.py`):
    - `GET /isler/{id}/zaman`: SQL'de `WHERE service_order_id = :id` ile süzülür. Bölümler ve `sure_ozeti` döner; kolonlar: kişi, faaliyet, başlangıç, bitiş, dk, kaynak, giren, girildi, gerekçe, iptal bilgisi.
    - `POST /isler/{id}/zaman` (`zaman.yaz` + `servis.gor`; başkası adına ise `servis.planla`).
    - `POST /zaman/kayitlar/{kid}/iptal {gerekce}` (`servis.planla`).
  - Denetim: manuel kayıt `olustur`, iptal `iptal` (`audit.log`, commit'ten önce). İptalde ayrıca `DUZELTME` olayı yazılır.
  - Ön yüz: Servis işi Drawer'ında "Zaman" kartı. Tablo kolonları Kaynak, Giren ve İptal gerekçesidir. "Elle Süre Gir" penceresi KartPenceresi kalıbındadır; kişi seçimi yalnız `servis.planla` sahibine görünür.
- **Kabul:**
  - (1) Gerekçesiz, bitişi 30 dk'dan eski manuel kayıt 400. 10 dk önce biten kayıt gerekçesiz 201.
  - (2) `zaman.yaz` sahibi teknisyen 3 gün önceye kayıt girince 400; şef gerekçeyle 201.
  - (3) Teknisyenin başkası adına kaydı 403.
  - (4) 10:00-10:30 MOLA bölümü olan kişiye 10:15-11:00 manuel kayıt 409 (`ex_ste_kisi_cakisma`), mesaj Türkçe.
  - (5) Gerekçesiz iptal 400; iptal gerekçesi ve iptal eden ekranda görünüyor; satır silinmiyor.
  - (6) Canlı akışla oluşan her bölüm `kaynak=CANLI`. Server default olmadığı için kaynaksız INSERT DB hatası verir (test).
  - (7) Ad değiştirilen kullanıcının kayıtları `user_id` ile görünmeye devam ediyor. Aynı adlı iki kullanıcının aynı saatteki kayıtları birbirini engellemiyor.
  - (8) `GET /isler/{id}/zaman` sorgu planında `ix_ste_is_baslangic` kullanılıyor (EXPLAIN testi) ve yalnız o işin satırları okunuyor.
  - (9) `sees_cost` olmayan yanıtta `iscilik_maliyeti` anahtarı yok.
  - (10) `work_orders`, `work_order_items` ve `settlements` satır sayıları değişmiyor; altın kayıt yeşil.
- **P1 · M · Bağımlılık:** E01-01, E01-02, E01-12 · **Canlı risk:** Yalnız yeni tablo. EXCLUDE için gereken `btree_gist` zaten kuruludur (`alembic/env.py:32-39`). Mobilite tablolarına dokunulmaz.

### E09-02 · Tek dokunuşla saha akışı: Yola Çıktım, Sahaya Vardım, Bekleme, Mola, Devam, Bitir (M09-02; öz: M09-15 "hafif benim ucu")
- **Canlı:** YOK.
- **Yaklaşım:**
  - `zaman.py` fonksiyonları: `baslat()`, `gecis(hedef_faaliyet, bekleme_nedeni=None, hedef_is=None)`, `mola()`, `devam()`, `bitir()` (§4 kuralları).
  - `devam()` faaliyeti sunucuda bulur: `onceki_bolum_id` zincirinde geriye yürür ve ilk MOLA/BEKLEME dışı faaliyeti alır. Zincir boşsa SAHA kullanılır.
  - Başlatma koşulları:
    - Kişinin başka açık bölümü yok (`uq_ste_acik_kisi` → 409 "Önce açık sayacı bitirin: SRV-…").
    - Kişi işte aktif atamalı (400).
    - İş açık bir durumda (E09-10).
    - İş erişimi var (404).
  - Uçlar:
    - `GET /zaman/benim`: hafif uç. Yanıt `{sunucu_zamani, acik_bolum|null, is_ozet, izinli_dugmeler}`. Bant ve iş kartı bunu kullanır; zaman özeti çağrılmaz (M09-15 özü).
    - `POST /zaman/baslat {is_id, eylem: YOLA_CIKTIM|SAHAYA_VARDIM|DIGER, faaliyet?, konum_notu?}`.
    - `POST /zaman/bolumler/{bid}/gecis {version, faaliyet, bekleme_nedeni?}`.
    - `POST /zaman/bolumler/{bid}/mola {version}`, `POST .../devam {version}`, `POST .../bitir {version, aciklama?}`.
    - Tümü `zaman.yaz` ister. Yanıt yeni durumu ve `sunucu_zamani`'yı içerir.
  - Pydantic `Literal` faaliyet ve neden listeleriyle yazılır; listede olmayan değer 422.
  - Ön yüz: `components/SayacDugmeleri.tsx`. Düğmeler duruma göre değişir, en az 44 px yüksekliktedir ve istek sürerken kilitlenir. Bekleme seçilince neden `Select`'i açılır. Masaüstünde "Diğer faaliyet" açılır listesi (Uzaktan/Atölye/Test/Diğer) bulunur.
- **Kabul:**
  - (1) Sayaç yokken yalnız "Yola Çıktım" ve "Sahaya Vardım" düğmeleri dönüyor.
  - (2) SAHA → MOLA → DEVAM sonunda yeni bölüm SAHA; MOLA bölümünün bitişi yeni bölümün başlangıcına eşit (boşluk ve çakışma yok); MOLA kişi-saate girmiyor.
  - (3) Nedensiz BEKLEME 400 (Pydantic/servis); neden sözlüğü E01 `SERVIS_BEKLEME_NEDENLERI` ile aynı (unit test).
  - (4) Çift basış: aynı `bid` + `version` ile iki `bitir` isteğinde ikincisi 409 döner ve tek bölüm oluşur. Eşzamanlı iki `baslat`ta biri 409 (`uq_ste_acik_kisi`).
  - (5) 1 dakikadan kısa bölümde geçiş 400.
  - (6) 18 saati aşmış açık bölümde `bitir` 400 ve yanıtta "unuttum" yönlendirmesi.
  - (7) `GET /zaman/benim` tek sorgu + PK okuması yapar, zaman özetini hesaplamaz (sorgu sayacı testi).
- **P1 · M · Bağımlılık:** E09-01, E09-16 · **Canlı risk:** yok.

### E09-03 · Sayacı sonraki iş emrine taşıma (M09-03)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `POST /zaman/bolumler/{bid}/gecis` gövdesine isteğe bağlı `hedef_is_id` eklenir. Ayrı `move` ucu açılmaz (denetim kararı).
  - Verilirse açık bölüm `kapanis_turu=GECIS` ile kapanır ve hedef işte aynı (veya seçilen) faaliyetle `started_at = an`, `onceki_bolum_id` dolu yeni bölüm açılır. İşlem tek transaction'dadır.
  - Hedef koşulları:
    - Kişinin aktif ataması var (400).
    - İş açık; IPTAL/TAMAMLANDI/KAPATILDI değil (400).
    - Erişim var (404).
    - Aynı iş değil (400).
  - "Aynı ziyaret" sunucuda doğrulanmaz; mobil ziyaret kartı yalnız aynı karttaki işleri önerir.
  - Hedef iş PLANLANDI ise K4 kuralıyla SAHADA olur.
  - Yol süresi ilk işte kalır (K14).
  - Ön yüz: ziyaret kartında "Sonraki Cihaza Geç" (sıradaki açık iş önerilir, liste değiştirilebilir).
- **Kabul:**
  - (1) A'daki bölümün `ended_at` değeri B'deki bölümün `started_at` değerine mikro saniyesine kadar eşit.
  - (2) Atanmamış hedef 400; KAPATILDI/IPTAL/TAMAMLANDI hedef 400.
  - (3) Hedef açılırken hata olursa (ör. EXCLUDE veya kapsam) A'daki bölüm açık kalır ve B'de satır oluşmaz (rollback testi).
  - (4) 17 PB'lik ziyarette art arda 16 geçişten sonra her PB işinin kendi SAHA süresi var; YOL yalnız ilk işte.
- **P2 · S · Bağımlılık:** E09-02, E09-01 · **Canlı risk:** yok.

### E09-04 · Mobil "Benim İşlerim" ekranı, tek sayfa iş kartı ve aktif sayaç bandı (M09-01)
- **Canlı:** YOK. Sayfa yok, menü kalemi yok. Genel düzen dar ekranda çalışıyor (`components/AppLayout.tsx:133-137, 203`).
- **Yaklaşım:**
  - `services/teknik_servis/mobil.py:benim_islerim(db, user, clock, gorunum)`:
    - Varsayılan `gorunum=benim`: kişinin aktif ataması olan açık işler (rol adına bakılmaz).
    - `tumu` yalnız `servis.planla` sahibine açıktır ve yine `kapsam_birim` uygulanır.
    - Gruplar: GECIKEN (plan yerel günü < bugün ve iş açık), BUGUN, YARIN, SONRA, PLANSIZ. Plan verisi E02 `service_plans`'tan gelir; E02 yoksa her iş PLANSIZ grubundadır.
    - Grup içinde **ziyaret anahtarı** = plan yerel günü + birim + `customer_id` + `address_id` + `addresses.city`. Bu, M02-08 takvim kartıyla aynı anahtardır. Sıralama plan başlangıç saatine göre.
  - Uçlar:
    - `GET /benim-islerim?gorunum=` (`servis.gor` + `zaman.yaz`; `tumu` için `servis.planla`).
    - `GET /benim-islerim/{is_id}`: tek sayfa kart. İçerik: adres (`addresses.line/district/city`), saha yetkilisi (`contacts` veya `iletisim_*`; E01 K11 maskeleme), seri/ekipman, plan notu, ulaşım notu, E04 bakım formu bağlantısı, `SureOzeti` ve `izinli_dugmeler`. **Fiyat ve maliyet alanı yoktur.**
  - Ön yüz:
    - `pages/BenimIslerimPage.tsx`: rota `/benim-islerim`, menü `{key:"/benim-islerim", label:"Benim İşlerim", icon:<MobileOutlined/>, izin:"zaman.yaz"}`. Sekmeler "İşlerim" ve "Bugünüm" (E09-05). Gruplu `Collapse`/`List`; ziyaret kartı açılınca içindeki her iş ayrı seçilir.
    - `pages/ServisIsKartiMobil.tsx` (`/benim-islerim/:id`): `tel:` bağlantısı; harita bağlantısı `https://www.google.com/maps/search/?api=1&query=<adres metni>` (yalnız dokunulunca, K3); `SayacDugmeleri`; "Sonuç Gir" (E01-06); "Bakım Formu" (E04); `EkYukleyici` (`capture`).
    - `components/AktifSayacBandi.tsx`: AppLayout'ta `<Outlet/>` üstünde, yalnız `yetkili("zaman.yaz")` ise çizilir. `useQuery(["zaman-benim"], refetchInterval 30 sn)`. Faaliyet, iş no, geçen süre (E09-16 ofsetiyle) ve Bitir düğmesi gösterir; 18 saati aşmışsa "Unuttum" düğmesi çıkar.
    - Tüm metinler Türkçedir. Tarih `DD.MM.YYYY HH:mm` biçimindedir.
- **Kabul:**
  - (1) Teknisyen hesabıyla yalnız kendine atanmış açık işler geliyor. Şef hesabıyla varsayılan da "bana atananlar"; "Tümü" yalnız `servis.planla` ile ve yalnız kendi biriminde.
  - (2) Bugünkü işler plan saatine göre sıralı; dün planlı açık iş GECIKEN grubunda (yerel gün, 23:30 UTC sınır testi).
  - (3) Aynı gün, müşteri ve adresteki 17 PB işi tek ziyaret kartında, her biri ayrı seçilebilir.
  - (4) Aktif sayaç varsa bant her sayfada üstte ve Bitir oradan çalışıyor; `zaman.yaz` olmayan mobilite kullanıcısında bant ve istek yok.
  - (5) 375 px'te yatay kaydırma yok, ana düğmeler ≥ 44 px (elle doğrulama + `npm run build` + `oxlint`).
  - (6) Kart yanıtında `fiyat|tutar|maliyet` anahtarı yok (test).
  - (7) Kapsam dışı işin kartı 404.
- **P1 · M · Bağımlılık:** E09-02, E01-12, E02 (plan; yoksa PLANSIZ grubu) · **Canlı risk:** `AppLayout.tsx` ortak bileşendir. Ekleme yalnız `zaman.yaz` koşullu bant ve iki MENU kalemiyle sınırlıdır; mobilite kullanıcısının ekranı değişmez.

### E09-05 · Teknisyen "Bugünüm" özeti ve gün sonu "süre kaydı eksik" listesi (M09-04)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `zaman.py:gunum(db, user, gun, clock)`:
    - Yerel gün aralığındaki kişinin kendi bölümleri (canlı ve manuel).
    - Toplamlar: kişi-saat, YOL, SAHA, BEKLEME, diğer, MOLA (hariç).
    - "Süre kaydı eksik" listesi şu üç koşulu birlikte sağlayan işlerdir:
      - Kişinin aktif TEKNISYEN/SEF ataması var.
      - Planı bugün **veya** kişi bugün durumunu değiştirmiş (`service_order_events` DURUM, `user_id=kişi`, yerel gün).
      - Kişinin o işte bugün geçerli bölümü yok.
    - Boşluklar yalnız bilgi olarak hesaplanır (bordro değil).
  - Uç: `GET /zaman/bugunum?gun=YYYY-AA-GG` (`zaman.yaz`; yalnız kendi; varsayılan bugün; en fazla 31 gün geriye).
  - Ön yüz: "Bugünüm" sekmesi. `Timeline` bölümler, `Statistic` toplamlar, eksik listesi ve her satırda "Elle gir" (E09-01 penceresi, iş önceden seçili).
- **Kabul:**
  - (1) 60 + 30 dk bölüm ve 15 dk molası olan teknisyende "1 sa 30 dk" ve "Mola 15 dk (hariç)".
  - (2) Bugün TAMAMLANDI yaptığı ama bölümü olmayan iş "Süre kaydı eksik" listesinde; "0 dk" yazılmıyor.
  - (3) Başka teknisyenin bölümleri yanıtta yok; `user_id` parametresi kabul edilmiyor (422).
  - (4) Sonucu TELEFON/UZAKTAN olan iş listede yok (BEKLENMIYOR).
- **P2 · M · Bağımlılık:** E09-01, E09-11 (`sure_ozeti`), E01-04, E02 (plan; yoksa yalnız durum değişikliği ölçütü) · **Canlı risk:** yok.

### E09-06 · Uzun açık sayaç uyarısı ve yönetici "iptal et / gerçek bitişle düzelt" akışı (M09-05)
- **Canlı:** KISMEN. Uyarı merkezi VAR (`services/uyarilar.py:47-192`), ama zaman uyarısı ve ack yok. İptal akışı YOK.
- **Yaklaşım:**
  - `uyarilar.topla()` sonuna iki blok eklenir; mevcut blokların sırası ve sayıları değişmez:
    - `if user.has("servis.planla")`: `zaman.uzun_sayac` (açık bölüm `started_at < now - zaman_uzun_sayac_uyari_saat` **veya** yerel günü < bugün). Sayım `service_orders` JOIN + `kapsam_birim` + `kapsam_musteri` ile yapılır. `onem="kritik"`, `yol="/zaman-takibi?kpi=uzun_sayac"`.
    - `if user.has("zaman.yaz")`: `zaman.kendi_uzun_sayac` (yalnız kendi; `yol="/benim-islerim"`, aciklama "Unuttuysanız gerçek bitiş saatini girin").
  - Ack yok (K7).
  - `zaman.py:yonetici_kapat(db, bolum, gercek_bitis | None, gerekce, user, clock)`. `servis.planla` + kayıt erişimi ister; gerekçe zorunlu.
    - `gercek_bitis` yoksa bölüm iptal edilir: `is_deleted`, `iptal_turu=YONETICI_IPTAL`.
    - Varsa koşullar `started_at < gercek_bitis <= clock.now()` ve ≤ 18 sa (400). Bölüm `ended_at=gercek_bitis`, `kaynak=YONETICI_DUZELTMESI`, `kapanis_turu=YONETICI`, `duzelten_id`, `gerekce` ile kapanır. Tek satır, tek transaction.
    - EXCLUDE ihlalinde 409 döner ve rollback sonrası bölüm açık kalır.
    - MOLA bölümü düzeltilirse yine MOLA kalır; kişi-saate girmez.
  - Uç: `POST /zaman/bolumler/{bid}/yonetici-kapat {gercek_bitis?, gerekce}`.
  - Denetim `audit.log("service_time_entries","yonetici_duzeltme"|"yonetici_iptal")` ve `DUZELTME` olayı.
  - Ön yüz: Zaman Takibi sayfasında "Şu an çalışanlar" tablosu (E09-14). Uzun sayaç satırları kırmızı; "Kapat / Düzelt" penceresinde gerçek bitiş `DatePicker` (isteğe bağlı) ve zorunlu gerekçe.
- **Kabul:**
  - (1) 10 saati aşan veya dünden kalan açık bölüm uyarıda sayılıyor; kapatılınca uyarıdan düşüyor; A birimi şefinin sayısında B birimi yok.
  - (2) Gerçek bitişle kapatma tek satırı `YONETICI_DUZELTMESI` yapıyor; geçmişte `DUZELTME` olayı ve denetim satırı var.
  - (3) Başlangıçtan önce veya `clock.now()`'dan sonra bitiş 400.
  - (4) Çakışan bitiş 409 ve bölüm hâlâ açık (rollback).
  - (5) Gerçek bitiş verilmezse yalnız iptal; kişi-saat oluşmuyor.
  - (6) MOLA bölümü düzeltilince kişi-saat değişmiyor.
  - (7) Yalnız `sistem.kullanici` olan hesap 403.
- **P2 · M · Bağımlılık:** E09-01, E09-07, E01-01 · **Canlı risk:** `uyarilar.topla` yalnız genişler; mevcut uyarıların hesap ve sırası değişmez.

### E09-07 · Unutulan sayacı teknisyenin kendisinin gerçek bitişle kapatması (M09-D01)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `zaman.py:unuttum(db, bolum, gercek_bitis, gerekce, user, clock)`. Koşullar:
    - Yalnız bölüm sahibi (değilse 403). İş erişimi ve atama aranmaz.
    - Bölüm açık ve (`now - started_at > 18 sa` **veya** başlangıcın yerel günü < bugün **veya** `now - started_at > zaman_uzun_sayac_uyari_saat`).
    - `started_at < gercek_bitis <= clock.now()` ve `gercek_bitis <= started_at + 18 sa` (400).
    - Gerekçe zorunlu (400).
  - Sonuç: `kaynak=KULLANICI_DUZELTMESI`, `kapanis_turu=UNUTULDU`, `duzelten_id=user`. MOLA ise MOLA kalır.
  - EXCLUDE ihlalinde 409 döner ve bölüm açık kalır.
  - Uç: `POST /zaman/bolumler/{bid}/unuttum {gercek_bitis, gerekce}` (`zaman.yaz`).
  - Denetim ve `DUZELTME` olayı yazılır.
  - Ön yüz: banttaki ve Bugünüm'deki "Unuttum, gerçek bitişi gir" penceresi.
- **Kabul:**
  - (1) 20 saatlik açık bölümü olan teknisyen gerçek bitişi girerek kapatıyor ve aynı dakika içinde yeni işte sayaç başlatabiliyor.
  - (2) Gerekçesiz istek 400.
  - (3) `clock.now()`'dan sonra veya başlangıçtan 18 saatten fazla sonra bitiş 400.
  - (4) Başka kayıtla çakışma 409 ve bölüm açık.
  - (5) Başkasının bölümü 403.
  - (6) Ataması kaldırılmış iş için de çalışıyor.
  - (7) Kayıt disiplin sütununda "düzeltilmiş" sayılıyor (E09-15).
- **P1 · S · Bağımlılık:** E09-01, E09-02 · **Canlı risk:** yok.

### E09-08 · Yanlış başlatılan sayacı ilk 5 dakikada geri alma (M09-10)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `zaman.py:geri_al(db, bolum, user, clock)`. Koşullar:
    - Yalnız sahibi (403).
    - Yalnız açık bölüm (409).
    - `clock.now() < started_at + zaman_geri_alma_dk` (400).
  - Sonuç: `is_deleted=true`, `iptal_turu=GERI_ALINDI`. Kişi-saat oluşmaz.
  - Bölüm bir GECIS ile açılmışsa önceki bölüm **yeniden açılmaz**; önceki bölüm geçiş anında biter. Kullanıcı devam etmek isterse yeni sayaç başlatır.
  - Atama ve iş erişimi aranmaz.
  - Değiştir ve bitir uçlarındaki 1 dk kuralı değişmez.
  - Uç: `POST /zaman/bolumler/{bid}/geri-al` (`zaman.yaz`).
  - Ön yüz: bantta ilk 5 dakika boyunca görünen "Yanlış başlattım" bağlantısı (sunucu ofsetiyle sayılır).
- **Kabul:**
  - (1) 3. dakikada geri alınan bölüm kişi-saate girmiyor ve iş detayında "geri alındı" olarak gri görünüyor.
  - (2) 6. dakikada 400.
  - (3) Başkasının bölümü 403.
  - (4) Ataması kalkmış olsa da sahibi geri alabiliyor.
  - (5) 1 dk dolmadan `bitir` hâlâ 400.
- **P2 · S · Bağımlılık:** E09-02 · **Canlı risk:** yok.

### E09-09 · Atama değişikliği ile açık sayaç bağı (M09-11)
- **Canlı:** YOK (atama E01-12'de tasarlandı).
- **Yaklaşım:**
  - `zaman.py:acik_sayaclar(db, is_idler, user_idler) -> list[(so_no, user_id, ad)]`: tek `EXISTS/IN` sorgusu.
  - E01 `atama.py:ata()` ve `toplu_ata()` çıkarılacak (`removed_at` yazılacak) kullanıcıları hesapladıktan sonra, **yazmadan önce** bu fonksiyonu çağırır. Kesişim varsa `AtamaHatasi` yükselir ve 409 döner; mesaj "Önce Ali Veli'nin SRV-… işindeki sayacını bitirin veya iptal edin". Toplu istekte sorunlu işlerin listesi döner, hiçbir iş değişmez.
  - Sayacı bitirme, geri alma ve unuttum uçları atama kontrolü yapmaz (§3.2 istisnası).
  - Ön yüz: Bitir düğmesi atamaya bakmadan `acik_bolum.user_id == ben` ise gösterilir. Eski app.js:1460 hatası tekrarlanmaz.
- **Kabul:**
  - (1) Açık sayaçlı teknisyeni çıkaran tekil atama 409 ve atama değişmemiş.
  - (2) 150 işlik toplu atamada tek bir işte bu durum varsa 409 ve 150 işin hiçbiri değişmemiş.
  - (3) (Veri tutarsızlığı benzetimi) ataması doğrudan DB'de kaldırılmış kişi kendi bölümünü `bitir` ile bitirebiliyor ve kişi-saat oluşuyor.
  - (4) Sayacı olmayan teknisyenin çıkarılması eskisi gibi çalışıyor.
- **P1 · S · Bağımlılık:** E09-01, E01-12 · **Canlı risk:** yok (E01 yeni koddur).

### E09-10 · Sayaç ile servis işi durumu arasındaki bağ (M09-09)
- **Canlı:** YOK.
- **Yaklaşım:**
  - (b) Başlatma ve taşıma yalnız `SAYAC_ACILABILIR_DURUMLAR` için geçerlidir: MUSTERI_TALEBI, PLANLAMADA, PLANLANDI, YOLA_CIKILDI, SAHADA, ISLEMDE, ATOLYEDE, TEST_KONTROL, BEKLEMEDE, TEKRAR_ACILDI. TAMAMLANDI, KAPATILDI, IPTAL ve KARGODA 400 döner. Bu liste E01 `DURUM_GRUPLARI['KAPALI']` ile **tek kaynaktan** türetilir (eski P.cs:1953/2808 tutarsızlığının karşılığı).
  - (c) E01 `durum_degistir()` içine eklenir: hedef IPTAL veya TAMAMLANDI ise ve işte açık bölüm varsa 409 döner, mesaj "Açık sayaç var: kişi listesi". `bitir` ise iş IPTAL'e alınmış olsa bile **mevcut açık bölümü kapatabilir**; (c) kuralı iptal anında açık bölüm kalmasını zaten engeller. `baslat`, `gecis` ve manuel kayıt iptal edilmiş işe 409 döner.
  - (a) K4: `baslat` ve `gecis` sırasında `durum_degistir(kaynak="SAYAC")` çağrılır. YOL ile PLANLANDI → YOLA_CIKILDI; SAHA ile PLANLANDI/YOLA_CIKILDI → SAHADA. E01 `UC_HEDEFLERI`'ne `kaynak="SAYAC"` için bu iki hedef eklenir. Diğer durumlarda iş değişmez.
- **Kabul:**
  - (1) TAMAMLANDI veya KAPATILDI işte sayaç başlatma 400.
  - (2) Açık sayaçlı işi IPTAL'e almak 409; TAMAMLANDI'ya (sonuç ucu) almak 409.
  - (3) PLANLANDI işte "Sahaya Vardım" sonrası durum SAHADA ve geçmişte tek DURUM satırı (`kaynak=SAYAC`).
  - (4) BEKLEMEDE işte "Sahaya Vardım" durumu değiştirmiyor.
  - (5) IPTAL işe manuel kayıt 409.
- **P2 · S · Bağımlılık:** E01-03, E09-02 · **Canlı risk:** yok.

### E09-11 · İş zaman çizelgesi ve türetilmiş saha metrikleri: ilk yol, ilk varış, son bitiş, Tam/Kısmi/Eksik, sapma (M09-06)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `sure_ozeti_toplu()` (§2.4) tek fonksiyondur. Çağıranlar:
    - E01 detay `_cikti()` (`sure_durumu` alanı "bilinmiyor"dan gerçek değere geçer).
    - E01-15 `GET /isler` ve `isler.xlsx` yeni kolonları: "İlk Yola Çıkış", "İlk Varış", "Son Bitiş", "Gerçek Kişi-Saat", "Süre Kaydı Durumu", "Sapma (dk)".
    - E01-14 KPI `sure_eksik`.
    - E04 bakım formu çıktısı ve E05 atölye detayı.
  - Excel: kayıt yoksa "Gerçek Kişi-Saat" ve "Sapma" hücreleri **boş** (`None`) kalır, "Süre Kaydı Durumu" = "Eksik".
  - `ilk_varis_at` SLA modülüne (E10) "sahaya varış" verisi olarak sunulur.
  - Ön yüz: Drawer "Zaman" kartında üstte metrikler, altta kişi bazlı kırılım ve bölüm `Timeline`'ı.
- **Kabul:**
  - (1) İki TEKNISYEN atanmış ve yalnız biri bölüm girmişse durum KISMI.
  - (2) Bölümü olmayan çalışılmış işte sapma boş, durum EKSIK; Excel hücresi boş (`openpyxl` ile okunarak test).
  - (3) İlk varış = ilk SAHA bölümünün başlangıcı; SAHA yoksa boş.
  - (4) Aynı iş için ekran (`/isler/{id}`), liste, Excel ve E01-14 KPI aynı değeri veriyor (parametrik test).
  - (5) MOLA kişi-saate eklenmiyor.
  - (6) E02 tahmini süresi yoksa sapma boş, 0 değil.
- **P2 · M · Bağımlılık:** E09-01, E01-12, E01-15, E02 (tahmini süre) · **Canlı risk:** yok.

### E09-12 · Kapanışta "süre kaydı eksik" uyarısı ve onaylı kapanış notu (M09-D02)
- **Canlı:** YOK.
- **Yaklaşım:**
  - E01-06 `POST /isler/{id}/sonuc` (TAMAMLANDI'ya giden tek yol) ve E04 `POST /formlar/{id}/tamamla` gövdelerine `sure_eksik_onay: bool = False` eklenir.
  - Sunucu `sure_ozeti` ile durumu EKSIK veya KISMI bulur ve onay yoksa **409** döner: `{"kod":"SURE_EKSIK", "eksik_kisiler":[ad...]}`. Bu yalnız istemcinin onay penceresi göstermesi içindir; **iş engellenmez**, onayla tekrar gönderilir.
  - Onaylı kapanışta `olay_yaz(NOT, "Süre kaydı eksik olarak kapatıldı: <kişiler>")`.
  - BEKLENMIYOR durumunda (telefonla çözüm) pencere çıkmaz.
  - Ön yüz: `ApiError.status === 409 && kod==="SURE_EKSIK"` geldiğinde `Modal.confirm` açılır ve onaylanırsa yeniden gönderilir.
- **Kabul:**
  - (1) Bölümü olmayan işi kapatan kullanıcı onay penceresi görüyor; onaylarsa iş TAMAMLANDI ve geçmişte not var.
  - (2) Bölümleri tam olan işte pencere çıkmıyor (ilk istek 200).
  - (3) Atanan iki kişiden birinin kaydı eksikse pencerede o kişinin adı var.
  - (4) Bakım formu tamamlamada aynı davranış.
  - (5) Açık sayaç varken tamamlama yine 409 (E09-10), onayla geçilemiyor.
- **P2 · S · Bağımlılık:** E09-11, E01-06, E04 · **Canlı risk:** yok.

### E09-13 · "0 saat" yerine "süre kaydı eksik": null anlamı ve işçilik maliyeti (M09-14)
- **Canlı:** YOK. Maliyet gizliliği altyapısı VAR (`api/deps.py:103-105`, `api/reports.py:41-55`).
- **Yaklaşım:**
  - Tüm zaman çıktılarında kayıt yoksa `kisi_saat_dk`, `kayitli_dk` ve `iscilik_maliyeti` alanları **null** döner; hiçbir fonksiyon `or 0` / `coalesce(...,0)` ile 0'a çevirmez (kod incelemesi maddesi + test).
  - `services/teknik_servis/raporlar.py:servis_maliyet_ozeti(db, filtre, user)`:
    - İşçilik = kişi-saat × `servis_iscilik_saat_maliyeti_tl`.
    - Parça = E11 `stock_movements.service_order_id` maliyeti (varsa).
    - Kayıt yoksa veya ayar 0 ise işçilik null.
    - Özet satırları: "İşçilik kaydı eksik iş: n" ve "İşçilik maliyeti tanımlı değil" bayrağı.
    - Eksik işler toplama 0 olarak girmez; ayrı satırda sayılır.
  - Uç: `GET /raporlar/maliyet` (`servis.gor` + `rapor.gor` + `maliyet.gor`).
  - E01-15 Excel'inde maliyet kolonları yalnız `sees_cost` ise eklenir.
  - Ön yüz: null değer "Kayıt eksik" `Tag`'i ile gösterilir; `tl()` null'a uygulanmaz.
- **Kabul:**
  - (1) Kaydı olmayan iş maliyet ekranında "Kayıt eksik" görünüyor, "0,00 ₺" görünmüyor.
  - (2) Özette "İşçilik kaydı eksik iş: n" satırı var.
  - (3) Kaydı olan işlerin hesabı değişmiyor (sabit girdi testi).
  - (4) Excel'de kaydı olmayan satırda kişi-saat hücresi boş.
  - (5) `maliyet.gor` olmayan kullanıcıda maliyet ucu 403 ve iş Excel'inde maliyet kolonu yok.
  - (6) Eksik sayacı yalnız çalışılmış durumları sayıyor; ileri tarihli PLANLANDI iş sayılmıyor.
- **P1 · S · Bağımlılık:** E09-11 · **Canlı risk:** `maliyet.gor` kümesi değişmiyor; yeni rapor ucu ayrı fonksiyondur, mevcut `services/reports.py` sorgularına dokunulmaz.

### E09-14 · Saha / Zaman Takibi yönetim ekranı, tıklanabilir KPI'lar, aktif sayaçlar ve Excel (eski "Saha / Zaman Takibi" sayfasının karşılığı; öz: M09-15 summary from/to, M09-16 (iii))
- **Canlı:** YOK. Eski sistemde vardı (tasarım §1.3: yönetim özeti, şu an çalışan ekipler, personel dağılımı, ayrıntı tablosu, CSV). Canlıda karşılığı yok; kaybolmaması için ayrı madde açıldı.
- **Yaklaşım:**
  - `raporlar.py`:
    - `zaman_ozeti(db, user, bas, bit, birim?, kullanici_id?, faaliyet?)`.
    - `aktif_sayaclar(db, user, clock)`.
    - `zaman_kayitlari_sorgusu(...)`.
    - Tarih aralığı varsayılanı son `zaman_rapor_varsayilan_gun` (31) gündür; süzme SQL'de yapılır ve tarih `started_at` ile yerel gün aralığına göre alınır.
    - Liste, sayı, KPI ve Excel aynı sorgu fonksiyonundan gelir.
  - Uçlar:
    - `GET /zaman/ozet`: KPI'lar kişi-saat, YOL, SAHA, BEKLEME, MOLA (hariç), farklı iş, aktif sayaç, uzun sayaç, süre kaydı eksik iş, canlı oranı.
    - `GET /zaman/aktif`.
    - `GET /zaman/kayitlar?kpi=&...`: `sayfala`, `X-Toplam-Kayit`.
    - `GET /zaman/kayitlar.xlsx`: iki sayfa, "Süre Kayıtları" ve "Personel"; `export.sayfalari_xlsx_async` (E01-15) kullanılır, formül enjeksiyonu koruması mevcut.
    - Tümü `servis.gor` + `rapor.gor` ister (Excel için `rapor.disaaktar`) ve birim + müşteri kapsamı uygular.
  - Ön yüz `pages/ZamanTakibiPage.tsx` (rota `/zaman-takibi`; menü `{label:"Saha / Zaman Takibi", izin:"servis.gor"}`; `rapor.gor` yoksa `/benim-islerim`'e yönlendirir):
    - Üstte **tıklanabilir** `Statistic` kartları (`Card hoverable onClick` → `?kpi=` ile alttaki tablo süzülür; sayı = tablo toplamı).
    - "Şu an çalışanlar" tablosu (yönetici kapat/düzelt, E09-06).
    - Personel dağılımı tablosu (E09-15 sütunları).
    - Ayrıntı tablosu (sunucu sayfalaması) ve filtreler (tarih aralığı `RangePicker`, birim, kişi, faaliyet).
    - Excel düğmesi.
  - Filtre değişince sayfa 1'e döner.
- **Kabul:**
  - (1) Her KPI için parametrik test: `/zaman/ozet` değeri = `/zaman/kayitlar?kpi=` `X-Toplam-Kayit` (ya da toplamı).
  - (2) Parametresiz çağrı son 31 günü döndürüyor; 31 günden eski bölüm yok.
  - (3) A birimi şefi B biriminin aktif sayaçlarını, kayıtlarını ve sayılarını görmüyor.
  - (4) `rapor.gor` olmayan teknisyen ekip uçlarında 403.
  - (5) Excel ve ekran aynı kişi-saat toplamını veriyor; MOLA ayrı ve hariç.
  - (6) KPI kartları tıklanabilir ve açılan liste aynı sayıyı gösteriyor (elle doğrulama + build).
  - (7) Test üreticisinin performans profilinde (20.000 iş / 100.000 bölüm) `/zaman/ozet` ve `GET /isler/{id}/zaman` indeks kullanıyor (EXPLAIN) ve iş detayı açılışında özet uç çağrılmıyor.
- **P2 · M · Bağımlılık:** E09-01, E09-11, E01-15 (çok sayfalı xlsx), E01-01 · **Canlı risk:** `export.py`'ye eklenen fonksiyon E01-15'te tanımlıdır; mevcut imzalar değişmez.

### E09-15 · Veri disiplini sütunları: canlı oranı, manuel ve gecikmeli manuel, iptal ve düzeltilen sayaç (M09-07)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `zaman_ozeti` personel satırına şu sütunlar eklenir:
    - `canli_orani`: CANLI dakika ÷ (MOLA hariç, iptal edilmemiş) toplam dakika; toplam 0 ise null.
    - `manuel_sayisi`.
    - `gecikmeli_manuel_sayisi`: `girildi_at - ended_at > zaman_gecikmeli_manuel_saat`.
    - `duzeltilen_sayisi`: KULLANICI_DUZELTMESI + YONETICI_DUZELTMESI.
    - `iptal_sayisi`: YONETICI_IPTAL + KAYIT_IPTAL.
    - `geri_alinan_sayisi`.
  - Aynı sütunlar Excel "Personel" sayfasında yer alır. Ayrı sayfa açılmaz (denetim kararı); şef bazında kırılım yapılmaz.
- **Kabul:**
  - (1) 3 CANLI (toplam 120 dk) ve 1 MANUEL (60 dk) bölümü olan kişide canlı oranı %66,7.
  - (2) Bitişinden 2 gün sonra girilen manuel kayıt gecikmeli sayılıyor (FakeClock ile).
  - (3) Filtreler (tarih, birim, kişi) E09-14 ile aynı çalışıyor; ayrı uç yok.
  - (4) Sıfır dakikalı kişide oran boş, "%0" değil.
- **P3 · S · Bağımlılık:** E09-14, E09-01 · **Canlı risk:** yok.

### E09-16 · Tek saat kaynağı, istemci saat farkı düzeltmesi ve yerel gün (M09-12)
- **Canlı:** KISMEN. `Clock` VAR ve kural olarak zorunlu (`clock.py:8`, `api/deps.py:22-27`). İstemciye sunucu saati bildirilmiyor. Yerel gün yardımcısı YOK; kod UTC tarih kullanıyor (`api/sims.py:138`). İmajda `tzdata` yok.
- **Yaklaşım:**
  - Tüm zaman kontrolleri `clock.now()` ile yapılır: gelecek bitiş, geri gün sınırı, 5 dk, 18 sa, uzun sayaç. Kayıt zamanı DB `now()` ile yazılmaz (K17).
  - Zaman uçlarının tamamının yanıtı `sunucu_zamani` içerir.
  - Ön yüz `src/api/teknikServis.ts` `saatFarki = sunucu_zamani - Date.now()` değerini saklar. Geçen süre göstergesi ve 5 dk geri alma sayacı bu farkla düzeltilir.
  - `zaman.py:yerel_gun()` (`ZoneInfo("Europe/Istanbul")`); `pyproject.toml`'a `tzdata` eklenir.
  - Worker'a `Gorev("saat-farki", timedelta(hours=6), saat_farki)` eklenir: `SELECT now()` ile `clock.now()` farkını ölçer, |fark| > 60 sn ise WARNING loglar ve özet döner. Mevcut görevler değişmez.
  - Sunucu TZ/NTP ayarı A4-06 kapsamındadır (bu modülde yapılmaz).
- **Kabul:**
  - (1) FakeClock 12:00 iken 13:00'te biten manuel kayıt 400; uygulamanın kendi saati değil enjekte edilen saat belirleyici (test).
  - (2) Telefon saati 10 dk ileri olsa da geçen süre göstergesi sunucu kaydıyla en fazla 1 dk fark gösteriyor (istemci ofset hesabı; elle doğrulama).
  - (3) `yerel_gun(2026-10-21T22:30Z) == 2026-10-22` (unit).
  - (4) `saat-farki` görevi `--bir-kez` ile koşuyor ve fark değerini logluyor.
  - (5) Uygulama kodunda yeni `datetime.now()` yok (`ruff`/grep kapısı).
- **P1 · S · Bağımlılık:** A4-06 (altyapı) · **Canlı risk:** `tzdata` bağımlılığı eklenir; mevcut kod `ZoneInfo` kullanmadığı için davranış değişmez. Worker'a yalnız yeni görev eklenir.

### E09-17 · Zaman yönetimi yetkisi: rol adı yok, `sistem.kullanici` yetmez (M09-16)
- **Canlı:** KISMEN. Varsayılan RED izin altyapısı VAR (`api/deps.py:79-97`). Rol adına göre karar veren kod yok. Zaman uçları yok.
- **Yaklaşım:**
  - Yönetici eylemleri (yönetici kapat/iptal, kayıt iptali, başkası adına kayıt, geri gün sınırını aşma) yalnız `servis.planla` ile yapılabilir. `sistem.kullanici`, `sistem.ayar` ve `YONETIM` bu uçları açmaz. Teknisyen ile şef ayrımı rol adına değil izne bağlıdır.
  - Uç taraması testi `/api/teknik-servis/zaman*` yazma uçlarını router'dan listeler ve her birinin izin bağımlılığını doğrular (E01-20 emsali).
  - Not: `sistem.kullanici` sahibinin kendine izin verebilmesi (A1 / M13 "verilebilir izin") bu modülün konusu değildir ve orada çözülür.
- **Kabul:**
  - (1) Yalnız `sistem.kullanici` olan hesapla yönetici kapat 403.
  - (2) `servis.planla` olmayan hesapla başkası adına kayıt 403.
  - (3) SERVIS_TEKNISYEN rolünün izin listesi `zaman.yaz` dışında değişmemiş; `servis.planla` yok.
  - (4) YONETIM tüm zaman ekranlarını okuyabiliyor ama hiçbir yazma ucunu kullanamıyor (`tests/unit/test_permissions.py:35-40` kuralı).
  - (5) `maliyet.gor` kümesi değişmemiş.
- **P3 · S · Bağımlılık:** E01-01, E09-01 · **Canlı risk:** yok.

### E09-18 · Zaman kuralları için otomatik test seti ve test verisi üreticisi (M09-D03)
- **Canlı:** KISMEN. Test altyapısı VAR: PG17, ayrı `_test` DB, alembic head, `_TRUNCATE ... CASCADE` (`users` dahil, `tests/conftest.py:41-49`), FakeClock (`conftest.py:157-167`). Zaman testi YOK.
- **Yaklaşım:**
  - `tests/integration/`:
    - `test_servis_zaman_akis.py`: Yol → Saha → Mola → Devam → Bitir, çift basış, 1 dk / 18 sa, tek aktif sayaç, taşıma, geri alma.
    - `test_servis_zaman_manuel.py`: gerekçe, geri gün, başkası adına, mola/canlı/manuel çakışması.
    - `test_servis_zaman_yonetim.py`: uzun sayaç uyarısı, yönetici kapat, unuttum, atama 409, iptal 409, eksik onay.
    - `test_servis_zaman_kapsam.py`: birim; 404 + `db.refresh` ile veri değişmemiş; sahibi istisnası.
    - `test_servis_zaman_rapor.py`: KPI = liste, Excel boş hücre, maliyet gizliliği, canlı oranı.
  - `tests/unit/test_zaman_hesap.py`: `sure_durumu` tablosu, `yerel_gun`, neden sözlüğü eşitliği.
  - Fixture'lar `conftest.py`'ye eklenir: `zaman_bolumu_ac(user, is, faaliyet, bas, bit=None, kaynak="CANLI")`; E01'in `birimli_kullanici_ac` ve `servis_isi_ac` fixture'ları kullanılır.
  - `service_time_entries` FK ile `users`/`service_orders`'a bağlı olduğu için `CASCADE` ile temizlenir. Açık yazım için yine de `_TRUNCATE`'e eklenir.
  - Veri üreticisi `tests/veri/zaman_uretici.py`:
    - Varsayılan profil: 3 birim, 1 şef, 3 teknisyen (ikisi aynı adlı), 17 PB'lik bir ziyaret.
    - `performans` profili: 20.000 iş, 100.000 bölüm. `@pytest.mark.performans` ile işaretlenir ve varsayılan koşuda atlanır.
  - Gerçek veriye dokunmaz.
- **Kabul:**
  - (1) `make test` tek komutla ≥ 40 zaman senaryosu koşuyor, hepsi yeşil.
  - (2) Altın kayıt (932 iş / 552.825,00 TL) ve `test_migration_zinciri` (head→base→head, tek head, EXCLUDE sayısı) yeşil.
  - (3) Mevcut testlerin tamamı yeşil.
  - (4) Her yeni uçta en az bir 403 ve bir kapsam testi var.
  - (5) Test DB her koşuda sıfırdan kuruluyor.
- **P1 · M · Bağımlılık:** E01-19 (fixture'lar); her E09 maddesi kendi testiyle tamamlanır · **Canlı risk:** `conftest.py` yalnız genişler.

---

## 7. API uç özeti (`api/teknik_servis.py`, prefix `/api/teknik-servis`)

| Uç | İzin | Madde |
|---|---|---|
| `GET /zaman/benim` | zaman.yaz | E09-02 |
| `POST /zaman/baslat` | zaman.yaz + servis.gor | E09-02, E09-10 |
| `POST /zaman/bolumler/{bid}/gecis` (`hedef_is_id?`) | zaman.yaz | E09-02, E09-03 |
| `POST /zaman/bolumler/{bid}/mola` · `/devam` · `/bitir` | zaman.yaz (yalnız sahibi) | E09-02 |
| `POST /zaman/bolumler/{bid}/geri-al` | zaman.yaz (yalnız sahibi) | E09-08 |
| `POST /zaman/bolumler/{bid}/unuttum` | zaman.yaz (yalnız sahibi) | E09-07 |
| `POST /zaman/bolumler/{bid}/yonetici-kapat` | servis.planla | E09-06 |
| `GET /isler/{id}/zaman` | servis.gor | E09-01, E09-11 |
| `POST /isler/{id}/zaman` | zaman.yaz (+ servis.planla başkası/eski tarih) | E09-01 |
| `POST /zaman/kayitlar/{kid}/iptal` | servis.planla | E09-01 |
| `GET /zaman/bugunum` | zaman.yaz | E09-05 |
| `GET /benim-islerim`, `GET /benim-islerim/{id}` | servis.gor + zaman.yaz (`tumu`: servis.planla) | E09-04 |
| `GET /zaman/ozet` · `/zaman/aktif` · `/zaman/kayitlar` | servis.gor + rapor.gor | E09-14, E09-15 |
| `GET /zaman/kayitlar.xlsx` | servis.gor + rapor.disaaktar | E09-14 |
| `GET /raporlar/maliyet` | servis.gor + rapor.gor + maliyet.gor | E09-13 |

Bu uçlar E01'in `api/teknik_servis.py` router'ı içindedir ve `main.py:182-209`'a E01'de bir kez eklenir. Dosya büyürse `api/servis_zaman.py` olarak ayrılır ve ayrı `include_router` satırı eklenir. Mutasyonlar CSRF başlığı (`api/deps.py:56-57`) ve MFA kapısından (`api/deps.py:64-72`) otomatik geçer.

---

## 8. İzlenebilirlik (kaynak → hedef)

| Kaynak | dotnet_specific | Hedef |
|---|---|---|
| M09-01 | hayır | E09-04 |
| M09-02 | hayır | E09-02 |
| M09-03 | hayır | E09-03 |
| M09-04 | hayır | E09-05 |
| M09-05 | hayır | E09-06 |
| M09-06 | hayır | E09-11 |
| M09-07 | hayır | E09-15 |
| M09-08 | hayır | E09-01 |
| M09-09 | hayır | E09-10 |
| M09-10 | hayır | E09-08 |
| M09-11 | hayır | E09-09 |
| M09-12 | hayır | E09-16 |
| M09-13 | hayır | E09-01 (+ K21 göç) |
| M09-14 | hayır | E09-13 |
| M09-15 | **evet** | öz → E09-01 kabul (8), E09-02 kabul (7), E09-14 kabul (2)(7); indeksler §2.1 |
| M09-16 | hayır | E09-17 (+ §3.1) |
| M09-D01 | hayır | E09-07 |
| M09-D02 | hayır | E09-12 |
| M09-D03 | hayır | E09-18 |
| Eski "Saha / Zaman Takibi" sayfası (tasarım §1.3) | — | E09-14 |
| Kullanıcı doğrulaması: KPI tıklanabilir | — | E09-14, E01-14 (E09-11 besler) |
| Kullanıcı doğrulaması: toplu planlama/atama | — | E09-09 (toplu atama ile uyum), E09-04 (planı okur) |
| Kullanıcı doğrulaması: Excel | — | E09-14, E09-11 |
| Kullanıcı doğrulaması: cihaz başına PB | — | E09-04 (ziyaret kartı), E09-03 (cihazdan cihaza taşıma) |

---

## 9. Uygulama sırası

Ön koşul E01-01 (RBAC + birim), E01-02/03/04 (çekirdek) ve E01-12'dir (atama).

1. **E09-18 iskeleti + E09-01 + E09-16:** model, EXCLUDE, manuel kurallar, saat kaynağı.
2. **Kilit kaldırıcılar:** E09-09 (atama 409), E09-10 (durum bağı), E09-07 (unuttum), E09-13 ("eksik ≠ 0").
3. **Saha deneyimi:** E09-02 (akış düğmeleri), E09-04 (Benim İşlerim + bant), E09-08 (geri al), E09-03 (taşı).
4. **Yönetim:** E09-06 (uyarı + yönetici düzeltme), E09-11 (metrikler), E09-12 (kapanış uyarısı), E09-05 (Bugünüm), E09-14 (yönetim ekranı + Excel), E09-15 (disiplin).
5. **Güvenlik:** E09-17.
6. **Göç:** K21 betiği, E01 göçünden sonra.

Her adım sonunda şu kapılar koşar: `make test` (altın kayıt dahil), `test_migration_zinciri`, `ruff`, `npm run build`, `oxlint`.

## 10. Dokunulmazlık kontrol listesi

- `work_orders`, `work_order_items` ve `settlements` tablolarına, `work_orders.started_at`'a, `services/settlements.py`'ye, `services/reports.py` sorgularına ve `uyarilar.py`'deki mevcut bloklara dokunulmaz. Zaman verisi yalnız `service_orders`'a bağlanır.
- `TEKNIK_SERVIS` (mobilite) rolü `zaman.yaz` almaz ve değişmez.
- Cihaz durum makinesine, `device_vehicle_assignments`'a ve stok EXCLUDE kısıtlarına dokunulmaz.
- Mevcut rollerin izin listeleri değişmez. `maliyet.gor` kümesi sabit kalır.
- `AppLayout.tsx`'teki değişiklik yalnız koşullu bant ve iki MENU kalemiyle sınırlıdır.
- Gözlemler (bu modülde düzeltilmez, kayda geçer):
  - Canlı kod "bugün"ü UTC gün olarak alıyor (`api/sims.py:138`, `api/workorders.py:210` vb.). İstanbul'da 00:00-03:00 arası önceki gün sayılıyor.
  - `UyariZili` rozeti uyarı türü sayısını gösteriyor; ack/okundu altyapısı yok (K7).
