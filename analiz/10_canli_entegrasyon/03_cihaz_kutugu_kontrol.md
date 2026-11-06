# E03 — Güvenlik Cihaz Kütüğü: Bağımsız Denetim (Kontrol) Raporu

> Tarih: 2026-10-21 · Denetlenen: `10_canli_entegrasyon/03_cihaz_kutugu_entegrasyon.md`
> Yöntem: Canlı kod (`denge-erp/backend/app`, `tests/`) OKUNARAK doğrulandı; kaynak koda dokunulmadı. Komşu tasarımlar (E01, E02, E04, E05, E06) çapraz kontrol edildi.
> Dosya:satır referansları `backend/app/` köküne göredir.

---

## 0. Genel hüküm

Tasarım **genel olarak sağlam ve canlı mimariye uyumlu**: `devices`'a dokunmaması, tek yeni tablo (`service_equipment`), değişiklik geçmişini `audit_logs` üzerinden kurması, `accounts/addresses/contacts/products/attachments/görev panosu`'nu yeniden kullanması, `statemachine` + `MAKINELER` meta-testi, `sayfala()`, `rapor.disaaktar` ve `SourceMixin + uq_*_kaynak` idempotent göç kalıbı doğru seçilmiş. Mobilite akışlarına (iş emri onayı → hak ediş, IMEI/`identity_kind`, EXCLUDE kısıtları) **hiçbir yazma yolu yok**; altın kayıt testi etkilenmez.

Ancak şüpheci okumada **dört gerçek sorun** çıktı; ikisi modüller arası çelişki, ikisi canlı koddan doğan boşluk:

1. **Seri no normalizasyonu üç tasarımda üç farklı tanımda** (E01-10 `normalize_seri`: iç boşluk teke iner, ASCII büyük harf, `tr_normkey` YOK; E03 `seri_anahtari`: yalnız strip + "Türkçe güvenli büyük harf"; E05: `upper(trim())`). E03-12'nin "tek fonksiyon" iddiası bu haliyle tutmaz. Ayrıca "Türkçe güvenli büyük harf" seri no için HATALI: Türkçe klavyede küçük yazılan `i` → `İ` olur, ASCII `I` ile eşleşmez.
2. **Saha seri/bölge bilgisi üç yerde** tasarlanmış: E03-14 `service_results.saha_seri_no/saha_bolge`, E04 `maintenance_forms.serial_no/zone` + `maintenance_contract_items.last_serial_no/last_zone`, E01 `service_order_serials.seri_norm`. Seri "tek kaynak" ilkesine aykırı.
3. **`maintenance_contract_items.equipment_id` sözleşmesi çelişkili:** E03 "RESTRICT, NOT NULL, `ex_sozlesme_kalem_cakisma`", E04 "SET NULL, NULL olabilir, `ex_mci_ekipman_cakisma`, bağ E04-17 (P2) ile kurulur". E03-07 (P1) "PB yalnız bağlı ekipmana" derken E04 eşleştirmeyi P2'ye bırakıyor → canlıya geçişte 87 sözleşmenin PB üretimi durur. Eski analizdeki açık soru ("87 sözleşmenin ilk eşleştirmesini kim yapacak; sistem önerip şef onaylasın mı?") hiçbir maddede karşılanmamış.
4. **Canlı koddan doğan boşluklar:**
   - `addresses` için **hiçbir API ucu yok** (`Address` yalnız `models/account.py:177-187` ve `services/belgeler.py`'de geçiyor). E03-02 formundaki "lokasyon müşterinin adreslerinden" seçimi E14 (adres genişletmesi + uçları) olmadan yapılamaz; bağımlılık yazılmamış.
   - `address_id` / `contact_id` ile `account_id` arasında tutarlılık kuralı yok (başka müşterinin adresi bağlanabilir).
   - Genel arama router'ı `require_permission("hesap.gor")` ile korunuyor (`api/search.py:25`); yeni SERVIS_* rollerine `hesap.gor` verilmezse ekipman araması ve müşteri seçimi çalışmaz.
   - KVKK: `hesabi_anonimlestir` (`services/kvkk.py:217-302`) yalnız `accounts/contacts/vehicles` alanlarını ve `entity IN (accounts, contacts)` denetim satırlarını maskeler; maskeleme satırın **tüm** `old_value/new_value`'sunu siler (`:305-332`). `log_change` irtibatla birlikte seri no değişikliğini aynı satıra yazarsa anonimleştirme seri geçmişini de yok eder; hesabı olmayan (account_id NULL) ekipmanın `contact_name_raw`'ı hiçbir anonimleştirme yolundan erişilemez.
   - `ck_svceq_cihaz_birim` (device_id yalnız MOBILITE/ARAC_TAKIP) E05'in RMA köprüsüyle çelişiyor: E05 "RMA köprüsü yalnız `service_equipment.device_id` doluysa" diyor ve bu Haberleşme atölyesi içindir.
   - E05 atölye "bul-veya-aç" ile `service_equipment`'a (marka + `upper(trim(seri))` anahtarıyla) kayıt açıyor ve `PUT /{id}/ekipman` ile düzeltiyor; E03 ise yazmayı yalnız `ekipman.yaz` (SERVIS_YONETICI/SEF) ile ve (tip+marka+serial_key) mükerrer kilidiyle tanımlıyor. Tek yazma kapısı tanımlanmamış.

"Canlıda YOK" iddiaları doğrulandı: ekipman izni, kütük tablosu, seri/model normalizasyonu, Excel gün sayısı dönüşümü, ekipman durum makinesi, ekipman ek sahipliği canlıda yok. "KISMEN" dedikleri (audit, göç altyapısı, ek altyapısı, sayfalama/Excel) doğru.

Aşırı mühendislik açısından: E03-13'teki birleştirmede **başka modüllerin tablolarındaki açık sözleşme kalemlerini/servis işlerini taşıma** hem modül sahipliğini deliyor hem tarihli EXCLUDE ile çakışma üretir; sadeleştirilmeli. Diğer maddeler (toplu durum, toplu garanti önizlemesi, KPI kutuları) kullanıcının eski sistemde doğruladığı işlevler olduğu için kabul edildi.

---

## 1. Canlı kod doğrulama tablosu

| İddia (tasarım) | Canlı kod | Sonuç |
|---|---|---|
| `cihaz.gor/yaz` yalnız mobilite | `permissions.py:22-24` | Doğru |
| Kapsam yalnız `KENDI_MUSTERILERI` | `permissions.py:80-82`, `services/accounts.py:29-61` | Doğru; `kapsam_disinda_mi(musteri_id=None)` → False (hesapsız ekipman müşteri kapsamında "kapsam içi" sayılır — yalnız SCOPE_OWN_CUSTOMERS rolü ekipman.gor almadığı sürece sorun değil) |
| YONETIM `.gor`'ları otomatik alır | `permissions.py:84, 247` (`_READ_ONLY_ALL`) | Doğru; `rapor.disaaktar` da YONETIM'de → YONETIM kütük Excel'i alabilir (kabul edilebilir, rapor notu) |
| `maliyet.gor` kümesi testle kilitli | `tests/unit/test_permissions.py:21-26` | Doğru |
| Meta-test yeni makineyi sınar | `tests/unit/test_statemachine.py:8-33` | Doğru; önerilen makinede terminal durum yok, tüm durumlar ulaşılabilir/başlangıç → test geçer |
| `uq_devices_seri` global | `models/device.py:93-98` | Doğru |
| `products.warranty_months` | `models/catalog.py:97` NOT NULL server_default 24 | Doğru; ayar fallback'i pratikte yalnız `product_id IS NULL` için çalışır |
| `audit.log_change` aynı transaction | `services/audit.py:26-92` | Doğru |
| "audit_logs yalnız INSERT" | `services/kvkk.py:324-328` `UPDATE audit_logs` (KVKK maskeleme) | **Kısmen yanlış**: KVKK satır değerlerini günceller |
| Kullanıcılar silinmez | `yonetim.py:74-76` docstring ("Silinmezler, KAPATILIRLAR") | Doğru |
| `_kapsam` yalnız accounts | `api/attachments.py:91-114` | Doğru; ilk satır `if entity != "accounts" or scope_filter(user) is None: return` → yeni dal bu satırın YENİDEN YAZILMASINI gerektirir (salt "ekleme" değil) |
| `EK_TURLERI` DB'de CHECK yok | `models/attachment.py:46-63, 67-70` | Doğru → ek türü eklemek migration gerektirmez |
| `KAYIT_TIPLERI` | `services/gorevler.py:44-54` | Doğru; görev uçlarında kapsam yok → bağlı ekipmanın seri/model etiketi başka birimdeki kart izleyicisine görünür (düşük risk, not) |
| Genel arama | `api/search.py:25` router guard `hesap.gor` | **Tasarımda eksik**: SERVIS_* rollerine `hesap.gor` şart |
| `addresses` lokasyon olarak kullanılabilir | `models/account.py:177-187`; API ucu YOK | **Tasarımda eksik bağımlılık** (E14) |
| `contacts` | `models/account.py:162-174`; `DELETE /hesaplar/kisiler/{id}` fiziksel siler (`api/accounts.py:224`) | `contact_id SET NULL` doğru seçim; silinince ekipman irtibatı sessizce boşalır (kabul) |
| Hesap birleştirme | `migration/hesap_birlestir.py` FK kolonlarını DB'den okur | `service_equipment.account_id` otomatik kapsanır — olumlu |
| `MAKS_SATIR = 20_000` | `services/imports/cekirdek.py:36` | Doğru |
| Excel uçlarında audit | `api/reports.py:85-175` disaaktar audit YAZMIYOR | Tasarımın audit eklemesi canlıdan sıkı; zararsız |
| Gözlem: cihaz kartı kapsamsız | `api/devices.py:123-138` | Doğrulandı |
| Gözlem: `_maliyet_gizle` None yapar | `api/reports.py:41-45` | Doğrulandı |
| advisory lock emsali | canlıda yok (`with_for_update` yalnız `api/imports.py:202`) | Yeni desen; gerekçesi (göçteki mükerrerler kısmi UNIQUE'i engelliyor) geçerli |

---

## 2. Madde bazında karar

| Id | Karar | Öncelik | Gerekçe / değişiklik |
|---|---|---|---|
| E03-01 | DEĞİŞTİR | P1 | Doğru iskelet. Eksik: SERVIS_* rollerine `hesap.gor` (müşteri seçimi + arama router'ı) RBAC adımında verilmeli; birim kapsamı liste/kart dışında `ozet`, `veri-kalitesi`, `saha-farklari`, `oneri`, `.xlsx`, `degisiklikler`, `gecmis` uçlarının HEPSİNE uygulanmalı ve testte sayılmalı. |
| E03-02 | DEĞİŞTİR | P1 | Mükerrer anahtarı `brand` serbest metin olduğu için kaçırır ("SMITHS" / "Smiths Detection") → anahtar `tr_normkey(brand)`; `address_id/contact_id` aynı `account_id`'ye ait olmalı (servis 400); `uq_svceq_cihaz` (device_id kısmi tekil) eklenmeli; `ck_svceq_cihaz_birim` E05 RMA köprüsüyle çelişiyor → kaldır ya da HABERLESME'yi ekle; adres seçimi E14'e bağımlı. |
| E03-03 | DEĞİŞTİR | P1 | Audit yaklaşımı doğru; ancak irtibat alanları (`contact_id`, `contact_name_raw`) AYRI denetim satırına `is_personal_data=True` ile yazılmalı, diğer alanlar `False`. Aksi halde KVKK maskelemesi seri no geçmişini de siler. "Yalnız INSERT" ifadesi "yalnız INSERT + KVKK maskelemesi" olarak düzeltilmeli. |
| E03-04 | KABUL | P1 | Canlı göç kalıbıyla birebir (`SourceMixin`, `ON CONFLICT DO NOTHING`, CLI). İrtibat adı eşleşen hesapta mevcut `contacts`'a bağlanması önerilir (bkz. E03-16). |
| E03-05 | KABUL | P1 | Salt okunur profil, `stok_raporu.py` emsali; risk yok. |
| E03-06 | DEĞİŞTİR | P1 | Kart P1 doğru; geçmiş E04'ün `GET /ekipman/{id}/bakim-gecmisi` (servis.gor) ucuyla ÇİFT tanımlı. Birleşik geçmiş tek servis fonksiyonunda toplanmalı, E04 ucu ya kaldırılmalı ya E03 ucunu çağırmalı; izin `ekipman.gor` + birim kapsamı. |
| E03-07 | DEĞİŞTİR | P1 | Kural doğru ama E04 ile çelişkili (FK davranışı, kısıt adı, E04-17 P2). Worker yalnız `equipment_id IS NOT NULL` + uygun ekipman kalemine PB üretmeli; FK `RESTRICT` (SET NULL PB zincirini sessiz koparır); kısıt adı tek. Sahiplik E04, ilk eşleştirme E03-D03. |
| E03-08 | KABUL | P2 | Kurallar net, `BELGE`'ye dokunmuyor, önizlemeli. "Sözleşmeye bağla" yalnız E04 ucunu çağıran UI. |
| E03-09 | KABUL | P2 | Makine meta-teste uygun; "Serviste" hesaplanıyor; toplu durum atomik. |
| E03-10 | DEĞİŞTİR | P2 | Fonksiyonlar `normalize.py`'ye ekleme olarak doğru; ancak seri fonksiyonu E01-10'un `normalize_seri`'si ile TEK olmalı (E03-D01). `excel_gun_tarihi('44083')=2020-09-09` hesabı doğrulandı. |
| E03-11 | DEĞİŞTİR | P1 | Liste ekranı modülün ana kullanım yüzeyi; E03-02 formu bu sayfadan açılır → liste + filtre + sayfalama + Drawer + Excel P1; KPI kutuları ve toplu işlemler aynı maddenin ikinci teslimi (P2). Statik yollar (`/ekipman/ozet` vb.) `/{id}`'den önce tanımlanmalı ya da `{id:int}`. |
| E03-12 | DEĞİŞTİR | P2 | Tek fonksiyon E01'inkiyle birleşmeli; Türkçe büyük harf DEĞİL ASCII katlama (`i/ı/İ → I`); `oneri` ucu birim kapsamlı (başka birimin lokasyonunu sızdırmaz); otomatik bağlamada müşteri + birim şartı (E03-14 ile tutarlı). |
| E03-13 | DEĞİŞTİR | P2 | Birleştirme başka modül tablolarını TAŞIMAMALI: ikincilde aktif sözleşme kalemi / açık servis işi / açık atölye kaydı varsa 409 + liste; kullanıcı önce kendi modülünde taşır. Böylece EXCLUDE çakışması ve modül sahipliği sorunu ortadan kalkar. |
| E03-14 | DEĞİŞTİR | P2 | Saha seri/bölge E04 `maintenance_forms` ve E01 `service_order_serials` ile çift tanımlı. Fark listesi bu kaynaklardan türetilmeli; `kutuk_fark_durumu` tek tabloda (PB için `maintenance_forms`, arıza için E01 kapanış tablosu) tutulmalı. Otomatik bağlama yalnız aynı müşteri + birim + TEK eşleşmede. |
| E03-15 | KABUL | P3 | Ayardan eşik, aynı sorgu = aynı sayı; veri dolunca. |
| E03-16 | DEĞİŞTİR | P2 | `_kapsam` ilk satırı yeniden yazılmalı (yalnız ekleme değil); arama router'ı `hesap.gor` korumalı; KVKK: `veri_bul` `contact_name_raw` içinde de aramalı, `hesabi_anonimlestir` bağlı ekipmanın `contact_name_raw`'ını ve `service_equipment` kişisel denetim satırlarını temizlemeli; hesapsız ekipman için ayrı yol. |

---

## 3. Kaçırılan maddeler (eklenen)

### E03-D01 · Modüller arası seri no ve ekipman bağ sözleşmesi (tek normalizasyon, tek saha-seri kaynağı, tek FK tanımı) — P1 · S
- **Neden:** E01-10, E03-10/12/14, E04 (§tablolar), E05 aynı kavramı farklı tanımlıyor; kodlamada ilk gelen modül tanımı dondurur, ikincisi sessizce ayrışır ve "tekrar arıza", "PB eşleşmesi", "atölye bul-veya-aç" farklı sonuç verir.
- **Yaklaşım:** `normalize.py`'de TEK `seri_anahtari` (E01'in `normalize_seri` adıyla da çağrılabilir takma ad YOK, tek ad): strip, iç boşluk teke, ASCII büyük harf (`i/ı/İ → I`), baştaki sıfır ve `/ - .` korunur. E01 `service_order_serials.seri_norm`, E03 `serial_key`, E05 bul-veya-aç aynı fonksiyonu kullanır. Saha seri/bölge: PB için yalnız E04 `maintenance_forms`, arıza için yalnız E01 kapanış; `maintenance_contract_items.last_serial_no/last_zone` kopyası kaldırılır (kütükten okunur). `maintenance_contract_items.equipment_id`: FK `service_equipment` **RESTRICT**, NULL olabilir ama PB üretimi `equipment_id IS NOT NULL` şartlı; kısıt adı tek (`ex_mci_ekipman_cakisma`). Bu sözleşme `00_MIMARI_KURALLAR.md`'ye ek olarak yazılır.
- **Kabul:** Üç modülün tasarımı aynı fonksiyon/kolon adlarını kullanır; `test_normalize_seri.py`: `' abc-i01 '` → `ABC-I01`, `00123≠123`, `AB-1≠AB1`, `'SC  5030'=='SC 5030'`.

### E03-D02 · Ekipman yazımında tek kapı ve izin matrisi (atölye/servis işi ekranından ekipman açma) — P1 · S
- **Neden:** E05 atölye `service_equipment`'a kendi anahtarıyla kayıt açıyor/düzeltiyor; E03 yazmayı `ekipman.yaz` (YONETICI/SEF) + mükerrer kilidiyle sınırlıyor. İki yol = iki mükerrer kuralı ve denetimsiz kütük değişikliği.
- **Yaklaşım:** Tüm modüller yalnız `services/teknik_servis/ekipman.olustur/guncelle` çağırır (advisory lock, audit, birim kontrolü tek yerde). Yeni kayıt açma (bul-veya-aç) çağıran modülün izniyle (`servis.yaz`/atölye izni) yapılabilir, mevcut kaydın kimlik alanlarını (seri, tip, marka, müşteri) değiştirmek yalnız `ekipman.yaz`. Kararlar §5 maddesi buna göre güncellenir.
- **Kabul:** Atölyeden açılan ekipman aynı mükerrer kuralına takılır (409 + gerekçe); ATOLYE rolü mevcut ekipmanın serisini değiştirmeye çalışınca 403; tüm yollar `audit_logs`'a düşer.

### E03-D03 · Sözleşme–ekipman ilk eşleştirme (öneri + şef onayı), PB worker'ı açılmadan önce — P1 · M
- **Neden:** E03-07 PB'yi yalnız bağlı ekipmana üretiyor; E04 bağı P2 (E04-17). Göçte `SecurityDeviceId` boş kalemler + adet farkları varken canlıya geçişte PB üretimi büyük oranda durur. Eski analizin açık sorusu (87 sözleşmenin eşleştirmesi) cevapsız.
- **Yaklaşım:** E04 sahipliğinde, E03 verisiyle: `GET /bakim-sozlesmeleri/eslestirme-onerileri` — sırayla (1) göçteki `SecurityDeviceId → source_ref`, (2) önceki dönem PB kalemi, (3) aynı müşteri + tip + `serial_key`; her öneri güven düzeyiyle. Şef toplu onaylar (`bakim.yaz`), onay sözleşme kalemi açar + audit. Worker'ın `pb-uretimi` görevi eşleştirme oranı ayarı (ör. sözleşme başına %100 bağlı değilse uyarı) ile devreye alınır.
- **Kabul:** Önerisiz kalem PB almaz ve "Sözleşme adet farkı" uyarısında görünür; onaylanan öneri sonraki worker turunda PB üretir; ikinci turda tekrar üretmez.

### E03-D04 · Ekipman–hesap–adres–irtibat tutarlılığı ve adres uçları bağımlılığı — P1 · S
- **Neden:** Canlıda `addresses` için uç yok; `address_id`/`contact_id` ile `account_id` arasında tutarlılık kuralı tasarlanmamış.
- **Yaklaşım:** Servis kuralı: `address.account_id == ekipman.account_id` ve `contact.account_id == ekipman.account_id`, aksi 400; `account_id` değişirse adres/irtibat boşaltılır ya da yeni hesaptan seçilmesi istenir. Adres listeleme/ekleme uçları E14'te (yoksa E03 kapsamında `GET/POST /api/hesaplar/{id}/adresler` minimal, `hesap.gor/hesap.yaz`). Hesap birleştirme betiği FK'ları DB'den okuduğu için `service_equipment` otomatik taşınır (doğrulama testi).
- **Kabul:** Başka hesabın adresiyle kayıt 400; hesap değişiminde eski adres kalmaz; `hesap_birlestir --uygula` sonrası ekipman hedef hesaba bağlı.

---

## 4. Kararların değerlendirmesi

| # | Karar | Değerlendirme |
|---|---|---|
| 1 | `service_equipment`, `devices` değil | **Makul**, canlı kodla kanıtlı. |
| 2 | Birim-genel tablo | **Makul**, ancak MOBILITE/ARAC_TAKIP için `devices` zaten kütük; bu birimlerde `service_equipment` kaydı yalnız `devices`'ta olmayan müşteri malı için açılmalı (kopya üretme). |
| 3 | Tek seferlik göç | Makul. |
| 4 | `ekipman.gor/yaz` + `rapor.disaaktar` | Makul; E03-D02 ile atölye/servis yolu netleşmeli. |
| 5 | `ekipman.yaz` yalnız YONETICI/SEF | Makul; atölyenin yeni kayıt açma ihtiyacı E03-D02'de. |
| 6 | Geçmiş = `audit_logs` | Makul; kişisel veri satırı ayrımı şart (E03-03). |
| 7 | Tarihli sözleşme kalemi | Makul; FK davranışı E04 ile uzlaştırılmalı (E03-D01). |
| 8 | Adet farkında PB uydurulmaz | Makul; ilk eşleştirme yolu olmadan canlıya çıkış riski (E03-D03). |
| 9 | Müşteri eşleşmesi title_key/trigram/karantina | Makul (`migration/esleme.py` "insan karar verir" ilkesiyle uyumlu). |
| 10 | Garanti kuralı | Makul. |
| 11 | DIGER_GUVENLIK | Makul. |
| 12 | Otomatik birleştirme yok | Makul (`hesap_birlestir.py` emsali). |
| 13 | Kiralama ayrı | Makul; E06 K1 ile tutarlı. |
| 14 | is_active ≠ lifecycle_status | Makul. |
| 15 | Advisory lock | Makul; canlıda emsal yok ama gerekçeli. Anahtar normalize marka ile. |
| 16 | Excel 20.000 | Makul. |
| 17 | Serviste hesaplanır | Makul. |
| 18 | "Ekipman Kütüğü" | Makul. |
| 19 | Profil döküm üzerinde | Makul. |
| 20 | .NET maddelerinin özü kabullere taşındı | Makul. |
| 21 | Gözlemler | İkisi de doğrulandı. |

## 5. Mobilite akışlarına etki

Hiçbir madde `work_orders`, `work_order_items`, `settlements`, `devices`, `device_*_history`, cihaz durum makinesi veya mevcut EXCLUDE kısıtlarına yazmıyor. Ortak koda dokunan üç nokta: `api/attachments.py:_kapsam` (ilk satır yeniden yazılır → `test_kapsam_guvenligi.py` regresyonu şart), `services/uyarilar.py` (yeni blok), `api/search.py` (yeni arayıcı). `permissions.py`'de mevcut rol listeleri değişmiyor; `test_permissions.py` maliyet kümesi aynı kalıyor.
