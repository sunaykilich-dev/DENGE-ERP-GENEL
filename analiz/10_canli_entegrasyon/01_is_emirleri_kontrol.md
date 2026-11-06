# E01 Servis İş Emirleri ve İş Havuzu — Bağımsız Denetim

> Tarih: 2026-10-21 · Denetlenen: `01_is_emirleri_entegrasyon.md` · Kaynak kod yalnız OKUNDU, değiştirilmedi.
> Doğrulanan canlı dosyalar: `permissions.py`, `models/rbac.py`, `models/user.py`, `api/users.py`, `api/deps.py`, `services/accounts.py`, `services/statemachine.py`, `tests/unit/test_statemachine.py`, `models/attachment.py`, `api/attachments.py`, `services/storage.py`, `services/kvkk.py`, `services/settings.py`, `services/gorevler.py`, `services/normalize.py`, `models/device.py`, `worker.py`, `tests/conftest.py`, `frontend/src/components/RolDuzenle.tsx`, `UsersPage.tsx`, `AppLayout.tsx`; çapraz kontrol: `02_planlama_entegrasyon.md`, `05_haberlesme_atolye_entegrasyon.md`.

## 1. Genel hüküm

Tasarım canlı mimariye büyük ölçüde uyuyor: ayrı alan (B seçeneği), `work_orders/settlements`'a yazmama, adlı CHECK'ler, `MAKINELER` kaydı, `sayfala`, `audit.log` aynı transaction'da, `rapor.disaaktar` yeniden kullanımı, `services/teknik_servis/` alt paketi. "Canlıda YOK" iddiaları doğrulandı: seri no normalleştirme yok (`normalize.py` yalnız MSISDN/IMEI/ICCID/plaka/vergi/IBAN), birim kavramı yok, kapsam yalnız `TUMU/KENDI_MUSTERILERI` (`permissions.py:80-82`), `users.py:181,225` sabit iki değer kontrol ediyor. Mobilite hak ediş zinciri, IMEI kimlik kuralı ve EXCLUDE kısıtlarına dokunan bir değişiklik yok.

Ama şu sorunlar düzeltilmeden kodlamaya geçilmemeli:

| # | Bulgu | Kanıt | Etki |
|---|---|---|---|
| B1 | **Mevcut varlık kopyası:** `EK_TURLERI` zaten `IMZA` içeriyor; tasarım `MUSTERI_IMZASI` ekliyor. | `models/attachment.py:49` | Aynı anlamlı iki ek türü; rapor/filtre bölünür. `IMZA` yeniden kullanılmalı. |
| B2 | **Durum kataloğu modüller arası tutarsız:** E01 `YOLA_CIKILDI`, E02 `YOLDA` diyor; E02 `PLANLANDI→MUSTERI_TALEBI` geri alma geçişini "E01'de teyit" ediyor ama E01'de yok (E01'de `PLANLANDI→PLANLAMADA`). E01'in `KARGODA/TEST_KONTROL` durumları E05'in `ATOLYE` makinesindeki `KARGOYA_VERILDI/TEST_KONTROL` ile çift durum takibi üretiyor. | `02_planlama...md:267-279`, `05_...md:62-63, 167-181` | Durum + CHECK + makine üç yerde ayrışır; K12 "tek katalog" kararı fiilen bozulur. |
| B3 | **E01 tek başına çalışmaz:** `PLANLANDI` yalnız `planla()` ile (E02); `PLANLAMADA→YOLA_CIKILDI/SAHADA` geçişi yok. E02 gelene kadar saha işi sahaya geçemez. | Tasarım §4 tablo | E01 yayını işlevsiz kalır; ya E01+E02 birlikte yayınlanmalı ya da E01'de geçici asgari `planla(tarih)` olmalı. |
| B4 | **Atama kuralı K15 ile çelişiyor:** K15 "girişsiz saha personeline pasif-girişsiz kullanıcı açılır" diyor; E01-12 kabul (1) "pasif kullanıcıya atama 400". Canlıda "girişsiz" bayrağı yok; tek araç `users.is_active` ve o hem girişi hem atamayı keser. | `models/user.py:19`, `permissions.py:87-88` ("Saha Teknisyeni (mobil) rolü yok — işler ofisten giriliyor") | Saha personeli ya atanamaz ya da giriş yetkisi alır. Uygunluk ölçütü açıkça tanımlanmalı. |
| B5 | **Olay tablosu ile mixin/KVKK çakışması:** Görev metni "hepsi SoftDelete+Versioned" diyor; salt-ekleme tetikleyicisi (`trg_soe_salt_ekleme`) UPDATE'i reddeder → yumuşak silme, `updated_at` ve sürüm artışı imkânsız. Ayrıca `ozet` serbest Türkçe metin: irtibat adı yazılırsa KVKK anonimleştirmesi tetikleyici yüzünden onu temizleyemez. `user_id` FK'si `ON DELETE SET NULL` olursa (ActorMixin kalıbı) kullanıcı silme UPDATE'e dönüşür ve tetikleyiciye çarpar. | `models/mixins.py` (ActorMixin SET NULL), `services/kvkk.py:217-302` | `service_order_events` yalnız `PkMixin` (+ Clock ile `olusma_zamani`) almalı; `ozet` ve `veri` kişisel veri içermemeli; `user_id` FK'si `ON DELETE RESTRICT` olmalı (canlıda kullanıcı hard-delete yok, risk yok). |
| B6 | **KVKK boşlukları:** (a) `_denetim_izini_maskele` yalnız `accounts/contacts` denetim satırlarını maskeler; `service_orders` için `is_personal_data=True` yazılan denetim satırlarındaki iletişim adı/telefonu anonimleştirmeden sonra düz metin kalır. (b) `saklama_suresi_dolanlar` yalnız abonelik/cihaz/mobilite iş emrine bakar; son yıllarda servis işi olan müşteri "hareketsiz" listesine düşer. (c) İmza PNG'si (`IMZA` eki) kişisel veridir; anonimleştirme ekleri ele almıyor. | `services/kvkk.py:305-329, 335-395` | E01-18'e eklenmeli. |
| B7 | **Kapsam yan etkisi bilinçli kabul edilmeli:** `KENDI_BIRIMI/KENDI_ISLERI` diğer tüm modüllerde `TUMU` davranır (yalnız `== KENDI_MUSTERILERI` kontrolleri var: `accounts.py:18,42,56`, `deps.py:116`, `orders.py:201,228`, `quotes.py:178,192`). Yani `SERVIS_TEKNISYEN` (`hesap.gor`) 7 binden fazla hesabın tamamını, irtibat kişileriyle görür. Ayrıca yönetici mevcut bir `KENDI_MUSTERILERI` rolünü yanlışlıkla `KENDI_BIRIMI` yaparsa satış temsilcisi sessizce TÜM hesapları görmeye başlar. | — | En az yetki: `SERVIS_TEKNISYEN`'den `hesap.gor` çıkarılmalı (müşteri/adres/irtibat servis işi detayında gömülü döner). `_KAPSAM_ACIKLAMA` metni "Servis işlerinde yalnız kendi birimi; diğer modüllerde tüm kayıtlar" diye açık yazılmalı. |
| B8 | **Ön yüzde sabit kapsam listeleri kaçırılmış:** `RolDuzenle.tsx:144` kapsam seçeneklerini sabit veriyor; `UsersPage.tsx:141,187,285,339` ve `AppLayout.tsx:171` yalnız `KENDI_MUSTERILERI` etiketini biliyor; `api/users.py` `_SAYFA_IZINLERI` (rol önizleme) servis sayfalarını bilmiyor. Tasarım yalnız `UsersPage` birim seçimini sayıyor. | Ön yüz grep | Yeni kapsam rol ekranından seçilemez; rol önizlemesi "Servis İşleri"ni göstermez. |
| B9 | **Ek silme 24 saat kuralı saat kaynağı:** `attachments.uploaded_at` DB `now()` ile yazılıyor, servis kuralı `clock.now()` ile karşılaştırırsa FakeClock testlerinde ve saat kaymasında yanlış sonuç verir. `service_approvals.ek_id → attachments RESTRICT` olduğu için onaya bağlı ek silinmek istenirse genel `IntegrityError` → 409 "fk_" mesajı döner. | `models/attachment.py:86-88`, `api/attachments.py:283-320` | Süre, `EK` olayının `olusma_zamani`'ndan (Clock) hesaplanmalı; onaya bağlı ek açık Türkçe 409 ile reddedilmeli. |
| B10 | **Öncelik/bağımlılık tutarsızlıkları:** `seri_norm` kolonu E01-02'de (P1) ama `normalize_seri` E01-10'da (P3); E01-09 (P2) E01-10'a (P3) bağlı; kategori kolonu E01-02'de ama kuralı E01-16'da (P2) ve P1 panel (E01-14) ona dayanıyor; KENDI_ISLERI kapsamının uygulanması E01-20'de P2 iken kapsam E01-01'de P1 açılıyor. Kapsam uygulaması "güvenlik sıkılaştırma" değil, yeni ucun doğruluğudur. | Madde listesi | normalize_seri, TUR_KURALLARI ve tek-kayıt kapsam kontrolü P1 çekirdeğe alınmalı. |

Diğer gözlemler:
- `MAKINELER` meta-testi `dogrula(d, d)`'nin hata vermesini şart koşuyor (`test_statemachine.py:25-28`); tasarımın "aynı durum → 409, olay yok" kararı bununla uyumlu. Doğrulama servis içinde de yapılmalı (canlı RMA'daki "yalnız API doğruluyor" sapması kopyalanmamalı, rehber §1.7).
- `TRUNCATE ... RESTART IDENTITY` bağımsız sequence'i sıfırlamaz; tasarım bunu `_TRUNCATE`'e ekliyor, doğru. Tetikleyici satır düzeyinde olduğu için TRUNCATE'i engellemez, doğru.
- `settings.DEFAULTS` tür doğrulaması yapmaz (`settings.py:116-129`); `servis_onay_zorunlu_turler` liste değeri için servis tarafında tür ve değer (SERVIS_TURLERI) doğrulaması yazılmalı.
- `devices.serial_no` normalleştirilmeden saklanıyor (`models/device.py:107`, `uq_devices_seri` ham değer). E01-10 eşleşmesi `upper(trim(serial_no))` ve IMEI için `validate_imei` ile yapılmalı; `devices` yalnız okunmalı.
- Canlıda `_SAHIP_TABLOSU` ile `EK_SAHIPLERI/SAHIP_IZNI` arasında zaten uyumsuzluk var (ör. `rma_cases` tabloda var, izinde yok). Servis için üç sözlüğe birlikte eklenmeli ve bir unit testle eşitlik kilitlenmeli.
- `KENDI_BIRIMI` kullanıcısının `user_units` satırı yoksa liste BOŞ dönmeli (fail-closed); `TUMU` kapsamlı `SERVIS_YONETICI` birimsiz olsa da her birime iş açabilmeli.

## 2. Madde hükümleri

| Madde | Hüküm | Öncelik | Gerekçe / Düzeltme |
|---|---|---|---|
| E01-01 | DEĞİŞTİR | P1 | B7, B8. `RolDuzenle.tsx`, `UsersPage.tsx` etiketleri, `AppLayout.tsx`, `_SAYFA_IZINLERI`, `_KAPSAM_ACIKLAMA` dokunulan dosyalara eklenmeli. `SERVIS_TEKNISYEN`'den `hesap.gor` çıkarılmalı. Birimsiz `KENDI_BIRIMI` kullanıcısı = boş sonuç; `birimler` listesi `BIRIMLER`'e karşı doğrulanır. Kabule eklenecek: "KENDI_ISLERI rolündeki teknisyen /api/hesaplar'da 403". |
| E01-02 | DEĞİŞTİR | P1 | `normalize_seri()` (E01-10'dan) ve `TUR_KURALLARI/kategori` (E01-16) çekirdeğe alınır. Tek kayıt kapsam fonksiyonu `is_erisimi_yok_mu` ilk uçla birlikte gelir (E01-20'den). `TUMU` kullanıcı için birim üyeliği şartı aranmaz. `service_order_events` ve `service_approvals` için mixin istisnası (B5) modele yazılır. |
| E01-03 | DEĞİŞTİR | P1 | B2, B3. `KARGODA/TEST_KONTROL` çıkarılır, atölye ayrıntısı E05 `workshop_records` makinesinde kalır (servis işi yalnız `ATOLYEDE`). Saha durum adları E02 ile tek listede hizalanır (`YOLA_CIKILDI` ya da `YOLDA`, biri). E02 olmadan `PLANLANDI`'ya ulaşma yolu ya E01'de asgari `planla()` ile sağlanır ya da E01+E02 birlikte yayınlanır. `dogrula` servis içinde çağrılır. |
| E01-04 | DEĞİŞTİR | P1 | B5. Olay tablosu yalnız `PkMixin`; `ozet` ve `veri` alanında kişisel veri yasak (unit test: olay yazıcısı ad/telefon alanlarını kabul etmez); `user_id` FK `RESTRICT`. Downgrade tetikleyici+fonksiyonu düşürür. |
| E01-05 | KABUL | P1 | Kısmi tekil `uq_hold_aktif` ve tek giriş noktası doğru; `beklemeyi_bitir` de `durum_degistir` üzerinden. |
| E01-06 | KABUL | P1 | `service_results` RMA `coz()`'u kopyalamıyor; zorunlu kanal ve geçersiz kılma doğru. Göç eşleme betiği `app/migration/` emsaline uyuyor. |
| E01-07 | DEĞİŞTİR | P1 | B1, B9. `MUSTERI_IMZASI` yerine mevcut `IMZA`. 24 saat kuralı Clock tabanlı olay zamanından. Onaya bağlı ek silmede açık 409. `_kapsam` imzasına `yazma` bayrağı (KENDI_ISLERI'de yazma = aktif atama). `SAHIP_IZNI/_SAHIP_TABLOSU/EK_SAHIPLERI` eşitliği unit testle. |
| E01-08 | DEĞİŞTİR | P2 | Tür `IMZA`; imza eki KVKK anonimleştirme kapsamına (B6c). Geri kalanı (değiştirilemez onay, `servis_formu.html`, fiyatsız PDF, "Süre kaydı eksik") doğru. |
| E01-09 | KABUL | P2 | Bağımlılık E01-10 yerine E01-02 (normalize_seri çekirdekte). Kapsam dışı mükerrerde numara vermemek doğru. |
| E01-10 | DEĞİŞTİR | P3 | `normalize_seri` E01-02'ye taşınır; bu maddede yalnız cihaz bağı + cihaz kartı sekmesi + kütükte olmayan raporu kalır. Eşleşme: IMEI `validate_imei`, seri `upper(trim(devices.serial_no))`. |
| E01-11 | KABUL | P2 | Tek üst bağlantı yeterli; döngü kontrolü servis içinde. |
| E01-12 | DEĞİŞTİR | P1 | B4. Atanabilirlik ölçütü `is_active` yerine birim üyeliği + açık bir "saha personeli/girişsiz" bilgisi (yeni `user_units` kolonu; canlı `users` tablosuna dokunmadan). İşten ayrılan (pasif) kullanıcı atanamaz, girişsiz saha personeli atanabilir; ikisi ayrılır. |
| E01-13 | KABUL | P2 | VersionedMixin + `version` zorunlu PATCH canlı kalıbın birebir karşılığı. |
| E01-14 | KABUL | P1 | Ayrı `ServisPaneli`, `reports.dashboard` ve `PanelPage` değişmiyor; sayı = liste ilkesi aynı fonksiyondan. Bağımlı kutular (E02/E09/E10) gizli kalır. |
| E01-15 | KABUL | P1 | `sayfala`, SQL'de kapsam, `export.py`'ye yalnız yeni fonksiyon. Telefon maskeleme Excel'de de. |
| E01-16 | DEĞİŞTİR | P1 | B10. Kategori kuralı E01-02 çekirdeğine birleşir (panel P1 ona dayanıyor). |
| E01-17 | DEĞİŞTİR | P2 | E01'de yalnız `tur=PB` değişmezleri (seri/tür değişikliği 409, tek seri). `uq_so_pb_cihaz_donem`, `contract_item_id` ve worker görevi E04'ün maddesidir; E01'de P1 olarak sayılmamalı. |
| E01-18 | DEĞİŞTİR | P2 | B6. Eklenecek: `_denetim_izini_maskele` `service_orders` (ve `service_approvals`) denetim satırları; `saklama_suresi_dolanlar` son N yılda servis işi olan müşteriyi hariç tutar (NULL ayıklamalı alt sorgu); imza ekleri. `api/search.py`'ye kapsamlı `_servis_ara`. |
| E01-19 | KABUL | P1 | Fixture ve `_TRUNCATE` genişlemesi canlı kalıba uyuyor. Ek senaryo: servis işi açma/kapama cihaz durumunu ve `device_status_history`'yi değiştirmiyor (E01-D04). |
| E01-20 | DEĞİŞTİR | P1 | B10. Yeni uçların kapsam uygulaması sıkılaştırma değil doğruluk; router taramalı 404 testi ve KENDI_ISLERI uygulaması E01-01/E01-02 kabulüne girer. Telefon maskeleme (K11) P1 kalır. |

## 3. Kararların değerlendirmesi

- Makul: K1, K3, K4, K5, K6, K7, K8, K9, K10, K11, K13, K14, K16, K17, K18, K19, K20, K22, K23, K24, K25, K26, K27, K28, K29.
- **K2** makul; ancak eşlenemeyen POC kayıtlarının hangi durumda yükleneceği (karantina mı, MUSTERI_TALEBI mi) yazılmalı.
- **K12** doğru ilke, fakat E01/E02/E05 arasında fiilen bozulmuş (B2) → E01-D01.
- **K15** canlı modelle çelişiyor (B4) → E01-12 düzeltmesi.
- **K21** makul; birim yönetimi E13'e kalsa da rol ekranı kapsam seçeneği E01'de şart (B8).
- K19 için ek: onaya bağlı ek silinemez (B9).

## 4. Eklenen maddeler

- **E01-D01 (P1, S)** Servis durum kataloğunun E01/E02/E05/E09 arasında tek kaynakta hizalanması.
- **E01-D02 (P1, S)** Rol/kapsam yönetim ekranları ve rol önizlemesinin yeni kapsam ve sayfaları tanıması.
- **E01-D03 (P1, S)** E01'in E02'siz yayınlanabilirliği: asgari planlama yolu ya da birlikte yayın kararı.
- **E01-D04 (P1, S)** Mobilite/cihaz akışına etkisizlik regresyon testleri (cihaz durumu, RMA, hak ediş).

Ayrıntılar yapılandırılmış çıktıdadır.
