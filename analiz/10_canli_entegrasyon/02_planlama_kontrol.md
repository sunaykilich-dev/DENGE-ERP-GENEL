# E02 — Planlama Takvimi ve Toplu Atama: Bağımsız Denetim

> Tarih: 2026-10-21 · Denetlenen: `02_planlama_entegrasyon.md` · Bağlayıcı: `00_MIMARI_KURALLAR.md`, `01_is_emirleri_entegrasyon.md` (E01)
> Canlı kod `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp` yalnız OKUNDU; kaynak koda dokunulmadı.

## 1. Genel hüküm

Tasarım mimari kurallara büyük ölçüde uyuyor: yalnız yeni tablolar açılıyor, `work_orders` / `vehicles` / hak ediş zincirine yazılmıyor, SEQUENCE ile numara üretiliyor, tek aktif plan kısmi tekil indeksle sağlanıyor ve gruplama anahtarı sunucuda `tr_normkey` ile üretiliyor. "Canlıda YOK" iddiaları doğrulandı: canlıda plan tablosu, takvim, birim kavramı ve advisory lock yok. Ön yüzde `Calendar` kullanımı da yok.

Ancak **E01 ile çelişen ve veri bütünlüğünü bozabilecek** birkaç sorun var. Kodlamadan önce düzeltilmeleri gerekir:

| # | Sorun | Kanıt | Etkilenen |
|---|---|---|---|
| 1 | **Ekip iki ayrı yerde tutuluyor.** E01-12 `service_order_assignments` tablosunu (SEF/TEKNISYEN, `is_lead`, toplu atama ucu `PUT /isler/toplu-atama`) zaten tanımlıyor. E02 ise `service_plan_members` ve ikinci bir toplu atama ucu (`POST /toplu-ata`) ekliyor, ayrıca E01'de bulunmayan `service_orders.sorumlu_sef_id` alanına yazıyor. | `01_is_emirleri_entegrasyon.md` §2.8, E01-12 | E02-08, E02-01, K-08 |
| 2 | **İzin çelişkisi.** E01 K23, atama ile planı bilinçli olarak tek izinde (`servis.planla`) birleştirdi. E02 `servis.ata` ve `servis.musaitlik` izinlerini ekliyor ve ikisini de `servis.planla` ile **aynı rollere** (SERVIS_YONETICI, SERVIS_SEF) veriyor. Ayrım hiçbir şeyi kısıtlamıyor, yalnız boş izin üretiyor. | E01 §3 K23; E02 §4 | E02-01, E02-03, E02-08, E02-20 |
| 3 | **Durum adları ve geçişler E01 makinesine uymuyor.** E02 `YOLDA` ve `MUSTERI_TALEBI→PLANLANDI` dışında yol tanımıyor. E01'de ise `PLANLAMADA`, `YOLA_CIKILDI`, `ISLEMDE`, `KARGODA`, `TEST_KONTROL` ve `TEKRAR_ACILDI` var; PLANLANDI'ya MUSTERI_TALEBI, PLANLAMADA, BEKLEMEDE ve TEKRAR_ACILDI'dan gidilebiliyor. E02'nin makineye eklemek istediği `PLANLANDI→MUSTERI_TALEBI` geçişi gereksiz, çünkü E01'de `PLANLANDI→PLANLAMADA` zaten var. | E01 §4 | E02-02, E02-12 |
| 4 | **Geri alma ilerlemiş işi geri çekebilir (M02-10 hatasının aynısı).** "Durum `previous_status` değerine döner" kuralında bir açık var. SAHADA olan işin planı geri alınırsa durum, plan öncesi değer olan MUSTERI_TALEBI'ye düşer. Ertelenmiş zincirde ise son satırın `previous_status` değeri PLANLANDI olur. | E02-12 | E02-12 |
| 5 | **`ck_svcplan_neden_zorunlu` tasarımın kendisiyle çelişiyor.** Kısıt `change_type='ILK_PLAN' OR change_reason IS NOT NULL` biçiminde. E02-08 ise EKIP_DEGISIMI için "neden zorunlu değil" diyor, E02-22 de göç satırları için "neden kaydı yok" diyor. Kısıt bu haliyle ikisini de 409'a düşürür. Ayrıca `GERI_ALMA` change_type değeri tanımlı ama K-09 bu satırın açılmayacağını söylüyor, yani değer ölü. | E02 §3.2 | E02-01, E02-08, E02-12, E02-22 |
| 6 | **Yer bilgisi kopyalanıyor.** `service_plans.address_id/contact_id` alanları, E01'deki `service_orders.address_id/contact_id/iletisim_*` alanlarının ikinci kopyası. Ziyaretlerim, föy ve Excel'in hangi adresi göstereceği belirsiz kalıyor. Kopya yerine E01 alanları kullanılmalı; plana yalnız ziyarete özgü `site_area/site_note` kalmalı. | E01 §2.2 | E02-01, E02-11, E02-24 |
| 7 | **HTTP kodları canlı kalıba uymuyor.** Pydantic `Field` ihlali canlıda **422** döner (`RequestValidationError` 400'e eşlenmiyor; `test_hesaplar.py:57`, `test_ekler.py:115`). E02 bu durumlar için 400 bekliyor. Kapalı işe plan bir kural ihlalidir ve rehbere göre **409** olmalı (E01 de 409 diyor); E02 400 diyor. | `main.py:150-161`, rehber §1.4 | E02-02, -03, -07, -08, -13 |
| 8 | **409 gövdesi istemcide kayboluyor.** `ApiError` yanıt gövdesini saklamıyor ve `detail` yalnız string ise okunuyor (`api/client.ts:12-46`). Ayrıca `cakisma` getter'ı her 409'u "başkası değiştirdi" olarak yorumluyor. Planlama çakışması, iyimser kilit 409'u ve `uq_svcplan_aktif` 409'u birbirinden ayırt edilemiyor. | `frontend/src/api/client.ts` | E02-15 |
| 9 | **E02 E01'in `KENDI_ISLERI` kapsamını (SERVIS_TEKNISYEN) yok sayıyor.** Takvim, havuz, KPI, Excel, kaynak görünümü ve uyarılar yalnız birim kapsamına göre tasarlanmış. | E01 §3, K22 | E02-05, -06, -19, -21, -25 |
| 10 | **İyimser kilit boşa çıkabiliyor.** `version` alanı service_orders'ınki. İşin durumu değişmeyen planlamada (SAHADA iş, ya da PLANLANDI→PLANLANDI) service_orders satırı güncellenmiyor ve version artmıyor. Bu yüzden iki şefin ardışık PUT'u sessizce birbirini ezer. | E02-03 | E02-03 |

## 2. Madde bazında karar

| Madde | Karar | Öncelik | Özet gerekçe |
|---|---|---|---|
| E02-01 | DEĞİŞTİR | P1 | Plan tablosu ve tek aktif plan doğru. Düzeltilecekler: neden CHECK'i, GERI_ALMA ve `previous_status` alanları, adres/irtibat kopyası, iki gereksiz izin, mixin'lerin açıkça yazılmaması. |
| E02-02 | DEĞİŞTİR | P1 | Fikir doğru. Durum kümesi ve HTTP kodu E01'e hizalanmalı; statemachine değişikliği gereksiz. |
| E02-03 | DEĞİŞTİR | P1 | Doğrulama kodları 422 olmalı. `servis.ata` kalkmalı. Kilit, aktif plan kimliğiyle kurulmalı. Araç doğrulaması eklenmeli. |
| E02-04 | KABUL | P1 | Doğru ve gerekli. Not: `password_hash` NOT NULL olduğu için K-01 düzeltilmeli. |
| E02-05 | KABUL | P1 | Doğru. Kapsam kuralına KENDI_ISLERI eklenmeli. |
| E02-06 | KABUL | P1 | Kullanıcının doğruladığı işlev; tek kaynak tasarımı iyi. |
| E02-07 | DEĞİŞTİR | P1 | E01 `toplu_dogrula` ve `atama.ata` kullanılmalı; uç yolu ve HTTP kodu tek olmalı. |
| E02-08 | DEĞİŞTİR | P1 | E01-12'nin kopyası. E02 yalnız "aktif planlı işte EKIP_DEGISIMI satırı aç" kancasını sağlamalı. |
| E02-09 | DEĞİŞTİR | P2 | E01'de `lokasyon_metni` yok. Anahtar adres kaydı üzerinden kurulmalı. |
| E02-10 | KABUL | P2 | Doğru; ekip tek kaynak kuralına (E02-D01) bağlı. |
| E02-11 | DEĞİŞTİR | P2 | Öneri E01 iş alanlarına ve planın `site_*` alanlarına yazılmalı. |
| E02-12 | DEĞİŞTİR | P2 | Geri alma hedefi E01 makinesine göre belirlenmeli. |
| E02-13 | DEĞİŞTİR | P2 | HTTP kodu ve neden kuralı düzeltilmeli. |
| E02-14 | KABUL | P2 | Gerekli. KENDI_ISLERI ile uyumlu. |
| E02-15 | DEĞİŞTİR | P2 | 409 gövde sözleşmesi, istemcide ayrım ve gece yarısını aşan kilit. |
| E02-16 | DEĞİŞTİR | P3 | Şehir gruplaması P2 S kalabilir; bölge önerisi P3. |
| E02-17 | KABUL | P2 | Doğru. Mixin'ler açıkça yazılmalı. |
| E02-18 | DEĞİŞTİR | P3 | "Ad-soyad kalıbı" araması kırılgan; yalnız seed adları aranmalı. |
| E02-19 | DEĞİŞTİR | P2 | Boş tarih dizesi FastAPI'de 422 verir; açık çözüm gerekli. |
| E02-20 | DEĞİŞTİR | P3 | `kvkk.py` hesap merkezli; çalışan notu oraya uymaz. İzin `servis.planla` ile birleşmeli. |
| E02-21 | KABUL | P3 | — |
| E02-22 | KABUL | P3 | E09'a bağlı; göç satırları için neden CHECK'i düzeltilmeli (E02-01). |
| E02-23 | KABUL | P3 | — |
| E02-24 | DEĞİŞTİR | P3 | E01 `iletisim_*` alanları da gizlenmeli. YONETIM hesap ekranından `contacts` telefonunu zaten görüyor; bu sınır not edilmeli. |
| E02-25 | DEĞİŞTİR | P2 | DEFAULTS'ta E01 ile mükerrer anahtar var. Süre sınırı ve gün sınırı DEFAULTS'a konmamalı. Uyarı sayımı KENDI_ISLERI'ye uymalı. |

Ayrıntılı revize metinler iş akışı çıktısındadır (StructuredOutput `verdicts[].revised`). Aşağıda yalnız kritik düzeltmelerin şeması var.

### 2.1 E02-01 düzeltilmiş şema notları

- **`service_plans`**
  - `address_id` ve `contact_id` kaldırılır. Adres ve irtibat `service_orders` alanlarından okunur.
  - `site_area`, `site_note` ve `plan_note` kalır.
  - `previous_status` kaldırılır. Olayda (`service_order_events`) önceki ve sonraki durum zaten tutulur.
  - `change_type` değerleri: ILK_PLAN, ERTELEME, EKIP_DEGISIMI, YENIDEN_PLAN. GERI_ALMA çıkarılır; geri alma `cancelled_at` + `cancel_reason` ile izlenir.
  - Yeni kolonlar: `cancel_reason` (`ck_svcplan_iptal_neden`) ve `cancel_note`.
  - Neden kısıtı: `ck_svcplan_neden_zorunlu`: `change_type IN ('ILK_PLAN','EKIP_DEGISIMI') OR change_reason IS NOT NULL OR source_system IS NOT NULL`.
- **Mixin'ler**
  - `service_vehicles` ve `service_unavailability` için mixin'ler açıkça yazılır: Pk, Timestamp, Actor, SoftDelete, Versioned (+ göçte Source).
  - `service_plan_members` yalnız Pk ve Timestamp alır; tasarımdaki gibi kalır.
- **İzinler**
  - Kalanlar: `servis.planla` (plan, atama, müsaitlik, çakışmayı gerekçeyle geçme), `servis.arac_yaz` ve `servis.irtibat_gor`.
  - `servis.ata` ve `servis.musaitlik` açılmaz (E01 K23).
- **Test temizliği:** `_TRUNCATE`'e ekleme zararsız ama gereksiz. `users` tablosu listede ve `CASCADE` ile truncate ediliyor; ActorMixin FK'sı taşıyan her tablo otomatik temizlenir (`tests/conftest.py:41-50`). Tasarımdaki "cascade yolu garanti değil" gerekçesi hatalı.

### 2.2 E02-02 / E02-12 düzeltilmiş durum kuralı (E01 makinesine göre)

- **Plan yazımı:**
  - Durum ∈ {MUSTERI_TALEBI, PLANLAMADA, TEKRAR_ACILDI} ise `is_emirleri.durum_degistir(..., "PLANLANDI", kaynak="planla")` çağrılır (E01 tek giriş noktası).
  - Durum ∈ {PLANLANDI, BEKLEMEDE, YOLA_CIKILDI, SAHADA, ISLEMDE, ATOLYEDE, KARGODA, TEST_KONTROL} ise durum değişmez.
  - BEKLEMEDE'den çıkış yalnız bekleme ucundan olur (E01 `UC_HEDEFLERI`).
  - Durum ∈ KAPALI_DURUMLAR ise **409** döner ve hiçbir satır yazılmaz.
- **Geri alma:**
  - Durum PLANLANDI ise `PLANLAMADA`'ya döner. Bu geçiş E01 makinesinde zaten var.
  - Diğer bütün açık durumlarda durum DEĞİŞMEZ.
  - Kapalı işte 409 döner.
  - `statemachine.py`'ye ek geçiş GEREKMEZ.

### 2.3 E02-15 409 sözleşmesi

- **Sunucu yanıtı:** `JSONResponse(409, {"detail": "<Türkçe özet>", "kod": "PLAN_CAKISMA", "cakismalar": [...]})`. `HTTPException(detail=dict)` kullanılmaz, çünkü canlı istemci dict `detail`'i okuyamaz.
- **`client.ts`:**
  - `ApiError`'a isteğe bağlı `govde?: unknown` alanı eklenir; mevcut `status`, `message` ve `cakisma` aynen kalır.
  - `PlanPenceresi`, `govde.kod === "PLAN_CAKISMA"` ise gerekçe Modal'ını açar; değilse "yenileyin" mesajını gösterir.
- **Advisory lock:** Anahtar kümesi, adayın `[starts_at, ends_at)` aralığının değdiği **bütün İstanbul günleridir** (süre 1440 dk'ya kadar çıktığı için gece yarısı aşılabilir). Kilitler sıralı alınır. Müsaitlik yazımı da aynı kilidi alır.

## 3. Eklenen maddeler (kaçırılanlar)

| Id | Başlık | Öncelik |
|---|---|---|
| E02-D01 | Ekip tek kaynak: `service_order_assignments` (E01) ↔ `service_plan_members` (E02) senkron kuralı | P1 |
| E02-D02 | `KENDI_ISLERI` kapsamının bütün planlama uçlarına, KPI'lara, Excel'e ve uyarılara uygulanması | P1 |
| E02-D03 | Mobilite dokunulmazlık regresyon testi (planlama uçları `work_orders`/`vehicles`/hak edişe yazmaz) | P1 |
| E02-D04 | Tek göç adımı: eski `WorkOrderPlans`/`TPL-` → visits/plans/members, idempotent + uzlaşma raporu | P2 |
| E02-D05 | KVKK: hesap anonimleştirmesinin planlama serbest metinlerini kapsaması | P2 |

## 4. Kararlar üzerine görüş

| Karar | Hüküm |
|---|---|
| K-01 Personel = User | **Makul, ama eksik.** `users.password_hash` NOT NULL (`models/user.py:17`), yani "parolası atanmamış kullanıcı" açılamaz. Giriş yapmayan personel için kullanılamaz bir hash (ör. `"!"`, doğrulayıcı hiçbir zaman eşleştirmez) yazılmalı ve bu seed/yönetim ekranında açıkça işaretlenmeli. Aksi halde rastgele parolalı, MFA'sız aktif hesaplar saldırı yüzeyi olur. |
| K-02, K-03, K-05, K-06, K-07, K-10–K-17, K-20, K-21 | Makul. |
| K-04 (ayrı override izni yok) | Makul. |
| K-08 (plansız işe ekip `sorumlu_sef_id`) | **Reddedilmeli.** Alan E01'de yok; plansız işte ekip E01 `service_order_assignments` tablosuna yazılır (E02-D01). |
| K-09 (append-only) | Makul, ama "GERI_ALMA" change_type değeri ve `previous_status` ile çelişiyor (bkz. 2.1). |
| K-18 | Makul. |
| K-19 | Makul. Ancak YONETIM `hesap.gor` ile `contacts.phone` değerini Hesaplar ekranından zaten görüyor; gizleme yalnız E01 `iletisim_*` ve planlama yanıtları için anlamlı. Bu sınır belgeye yazılmalı. |
| K-22 | Makul. |
| K-23 (ayrı uç dosyası) | Makul. |

## 5. Diğer gözlemler (E13 / altyapı bağımlılıkları)

- `api/users.py:181, 225` rol kapsamını yalnız `TUMU/KENDI_MUSTERILERI` olarak kabul ediyor. E13 bu beyaz listeyi `SCOPES` üzerinden genişletmezse SERVIS_SEF rolü ekrandan düzenlenemez. E02'nin ön koşulu olarak not edilmeli.
- `pyproject.toml` içinde yalnız `integration` işareti tanımlı. E02-05'teki `@pytest.mark.slow` işareti `markers` listesine eklenmeli.
- `uq_svcplan_aktif` bir kısmi tekil **indeks**. psycopg ihlalde indeks adını `constraint_name` olarak bildirir, `main.py:71-77` de `uq_` önekiyle doğru mesajı verir. Bu nokta doğrulandı.
- DEFAULTS'ta E01 `servis_toplu_atama_ust_sinir=150`, E02 ise `servis_toplu_islem_azami=150` tanımlıyor. Tek anahtar kullanılmalı.
- Canlıdaki `api/workorders.py:355-366` doğrudan durum ataması, `models/workorder.py:116` `scheduled_at` ve `:110-113` atama alanları ile `PanelPage` Statistic'lerinin tıklanmadığı doğrulandı.
