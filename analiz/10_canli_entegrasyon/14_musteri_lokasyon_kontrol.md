# E14 Müşteri, Lokasyon, Saha ve Sözleşme Ana Verisi: Bağımsız Denetim

> Tarih: 2026-10-21 · Denetlenen belge: `14_musteri_lokasyon_entegrasyon.md`. Kaynak koda dokunulmadı; kod yalnız okundu.
> Doğrulanan canlı dosyalar: `models/account.py` (tamamı), `models/mixins.py:70-113`, `models/attachment.py:25-84`, `models/settlement.py:100-170`, `models/subscription.py:125-190`, `models/workorder.py:95-120`, tüm `models/*` içinde `ForeignKey("accounts…")` ve `ExcludeConstraint` taraması, `api/accounts.py:1-150, 248-465`, `schemas/accounts.py`, `services/accounts.py`, `services/normalize.py:105-135`, `services/belgeler.py:140-170`, `services/kvkk.py:24-30, 217-330`, `services/imports/hesap.py`, `services/imports/__init__.py`, `api/attachments.py:41-110, 180-210`, `services/uyarilar.py` (blok başlıkları), `permissions.py` (hesap/rapor/sistem kodları), `migration/hesap_birlestir.py` (tamamı), `tests/conftest.py:30-50`.
> Çapraz okunanlar: `00_MIMARI_KURALLAR.md`, E01 §3.3 rol tablosu, E03 §2, E04 §2.1, E13 §3.3-3.4, `12_raporlama_kontrol.md` (B8, B9, B11).

## 1. Genel hüküm

Tasarımın ana kararı doğru ve canlı mimariye uygun: ayrı `customers/sites` tablosu açılmıyor; `accounts / addresses / contacts` yeniden kullanılıyor, yalnız `account_aliases` ve `account_merges` yeni. Canlı karşılık taramasındaki iddiaların hepsi kodla doğrulandı:

- `addresses` için hiçbir API ucu yok; tek okuyucu `services/belgeler.py:150-152` (`.limit(1)`, sıralama YOK).
- `ix_accounts_tax_no` tekil değil (`account.py:67`); `tr_normkey` yalnız Türkçe katlama + boşluk yapıyor (`normalize.py:119-133`).
- `hesabi_anonimlestir` yalnız `accounts`, `contacts`, `vehicles`'ı maskeliyor; `KISISEL_VARLIKLAR = ("accounts","contacts","vehicles")` (`kvkk.py:30, 217-302`).
- `hesap_birlestir.py` FK'leri şemadan okuyor (`:116-128`), `datetime.now(UTC)` kullanıyor (`:219`, Clock kuralı ihlali — taşınırken düzelmeli).
- `_kapsam` ek uçlarında yalnız `accounts` için çalışıyor (`attachments.py:99-103`).

Mobilite akışı korunuyor: `work_orders / settlements` zincirine yazılmıyor, EXCLUDE ve IMEI kurallarına dokunulmuyor. Canlı tablolara (`accounts`, `addresses`, `contacts`, `quotes`) yalnız nullable/server_default kolon ekleniyor; `addresses.line` NOT NULL gevşetmesi CHECK değil kolon nullability değişikliği olduğundan rehber §2 yasağına girmiyor.

**Asıl sorunlar ayrıntıda:** (a) canlı `POST/PATCH /api/hesaplar`'a eklenecek VKN kontrolünün tetik koşulu yanlış tanımlı (mobilite formunu kilitleyebilir), (b) birleştirme servisinin "hak ediş zinciri" listesi canlı tablo adlarıyla uyuşmuyor ve mobilite geçmişini de taşıyor, (c) KVKK genişlemesi türetilmiş anahtarları (`alias_key`, `site_key`) ve denetim izi maskesini unutuyor, (d) servis rollerine verilen `hesap.gor/hesap.yaz` mobilite verisini ve montaj noktası IBAN'ını açıyor.

## 2. Bulgular

| # | Bulgu | Kanıt | Etki / düzeltme |
|---|---|---|---|
| B1 | **VKN 409'u PATCH'te her kayıtta tetiklenebilir.** Ön yüz düzenlemede formun tamamını gönderiyor; `guncelle` `exclude_unset` ile gelen her alanı yazıyor. Canlıda aynı VKN'li şube/bayi çiftleri varsa (K6 bunu kabul ediyor), bu hesaplarda telefon değiştirmek bile 409 + onay ister. | `api/accounts.py:440-449`; `pages/HesaplarPage.tsx:164` | Kontrol yalnız `tax_no` gövdede VAR ve eski değerden FARKLI ise çalışır (POST'ta dolu ise). Kabule "VKN'si değişmeyen PATCH 200" testi eklenir. |
| B2 | **Yeni gövde alanları ORM'e sızar.** `olustur` `Account(**payload.model_dump(exclude={"partner"}))` yapıyor; `vkn_cakisma_onayi/gerekce` eklenirse `TypeError` → 500. PATCH döngüsü bilinmeyen alanı sessizce nesneye `setattr` eder. `is_verified` HesapPatch'e girerse `hesap.yaz` sahibi doğrulamayı atlatır. | `api/accounts.py:400-401, 448-449`; `schemas/accounts.py:20-69` | `exclude={"partner","vkn_cakisma_onayi","vkn_cakisma_gerekce"}`; `is_verified/verified_*/merged_into_id` HesapIn/Patch'e EKLENMEZ (yalnız `/dogrula`, `hesap.birlestir`). `dis_referans` Patch'e eklenebilir. |
| B3 | **"Hak ediş zinciri" listesi canlı adlarla uyuşmuyor; birleştirme mobilite geçmişini de taşıyor.** Canlıda `settlements` tablosu yok: `partner_tariffs` (EXCLUDE `ex_tarife_cakisma` partner_id üzerinde), `partner_settlements` (`uq_dokum_nokta_donem`), `settlement_lines`, `settlement_disputes`, `payments`, `installation_partners`. Ayrıca FK-genel UPDATE `orders`, `subscriptions`, `subscription_events`, `devices`, `vehicles`, `device_vehicle_assignments`, `transfers`, `rma_cases` müşteri kolonlarını da taşır; bunlar ekrandan yapılacak servis birleştirmesinin işi değil. | `models/settlement.py:105-170, 199, 246, 269`; `migration/hesap_birlestir.py:184-202`; `models/workorder.py:102-114, 245-253` | Ekran birleştirmesi **izin listesiyle** çalışır: kaynağın referansları yalnız `contacts, addresses, account_aliases, quotes, attachments(accounts)` ve servis tabloları (E01-E07) ise uygulanır; başka herhangi bir FK'de satır varsa 409 + tablo listesi ("sistem.goc betiğiyle"). FK listesi yine şemadan okunur (yeni tablo eklenince önce reddedilir, sessiz kalmaz). |
| B4 | **Lokasyon birleştirmesinde hesap eşitliği şartı yok; ekler taşınmıyor.** `addresses` başka hesaba aitse servis işleri yabancı hesabın tesisine bağlanır (`lokasyon_dogrula` değişmezi bozulur). `EK_BAGLAR` yalnız `entity='accounts'`. | `hesap_birlestir.py:95-98` | LOKASYON türünde `kaynak.account_id = hedef.account_id` değilse 400. `EK_BAGLAR`'a `("attachments","entity_id","entity = 'addresses'")` eklenir. HESAP birleştirmesi sonrası hedefte aynı `site_key`'li iki aktif tesis ve iki birincil irtibat oluşabilir; önizleme bunları "çakışma" olarak gösterir. |
| B5 | **KVKK: türetilmiş anahtarlar ve denetim izi maskelenmiyor.** `alias_text` maskelenip `alias_key` kalırsa ad geri okunur (ayrıca global tekil olduğu için yeni kayıt 409 alır). `_denetim_izini_maskele` yalnız `accounts` ve `contacts` entity'lerini temizliyor; `addresses`, `account_aliases` denetim satırları açık kalır. `veri_bul` (ilgili kişi başvurusu) adres/takma adı aramıyor. `account_merges.doldurulan_alanlar` betikteki gibi DEĞERLERİ (VKN, IBAN, telefon) taşırsa silinemez kişisel veri doğar. | `kvkk.py:108-145, 305-329`; `hesap_birlestir.py:170-174` | Anonimleştirmede `alias_key` ve `site_key` maskeli metinden yeniden üretilir; `_denetim_izini_maskele` bu iki entity'yi kapsar; `veri_bul` `addresses.line/access_note` ve `alias_text`'i arar; `account_merges` yalnız ALAN ADLARINI saklar. |
| B6 | **Servis rollerine verilen `hesap.gor/hesap.yaz` mobilite verisini açıyor.** `KENDI_BIRIMI` kapsamı hesaplara uygulanmıyor (yalnız `KENDI_MUSTERILERI` süzer). SERVIS_SEF `hesap.gor` ile tüm müşterilerin IBAN/VKN'sini (`HesapOut`) ve `/kart`'ta cihaz IMEI, plaka, şase, sipariş `grand_total`'ını görür. SERVIS_OPERASYON `hesap.yaz` ile **montaj noktasının IBAN'ını** değiştirebilir; ödeme listesi IBAN'dan üretiliyor. | `services/accounts.py:11-21, 42-44`; `schemas/accounts.py:80-104`; `api/accounts.py:248-368`; `services/imports/hesap.py:8-11`; E01 §3.3 `:230-232` | Eklenen madde E14-D01. |
| B7 | **Ek dosya için 5. yer unutulmuş.** Tasarım `EK_SAHIPLERI`, `SAHIP_IZNI`, `_kapsam` diyor; canlıda ayrıca `_SAHIP_TABLOSU` var (ek yüklemeden önce kaydın varlığı). Eksikse `addresses` ekinde varlık kontrolü atlanır (`return True`). | `api/attachments.py:190-210` | `_SAHIP_TABLOSU["addresses"]="addresses"` eklenir. |
| B8 | **"Teklif PDF çıktısı değişmez" iddiası tam değil.** Bugünkü sorgu sırasız `limit(1)`; `is_primary DESC` eklemek birden çok adresi olan hesapta basılan adresi değiştirebilir. | `belgeler.py:150-152` | `ORDER BY is_primary DESC, id` kullanılır ve E14-08 canlı ölçümüne "birden çok adresi olan hesap sayısı" eklenir; sayı 0 değilse yayın notuna yazılır. |
| B9 | **Tesis tekilliği yalnız serviste.** "Aynı hesapta aynı `site_key` aktif tesis 409" yarışta iki kayıt üretir; rehber §1.3 "uq_ kısıtı 409'a çevirir" kalıbını öneriyor. Canlıda TESIS satırı olmadığı için kısmi indeks sorunsuz kurulur. | rehber §1.3, `main.py:131-148` | `uq_addresses_tesis_aktif (account_id, site_key) WHERE kind='TESIS' AND is_active`. Hesap birleştirmesi bu indekse takılırsa önizleme önce tesis birleştirmesini ister. |
| B10 | **`ck_mc_musteri_teyit` E04 geçişini kırar.** E04 makinesi `TEYIT_BEKLIYOR→PASIF` geçişine izin veriyor; müşterisi eşleşmemiş eski sözleşme pasifleştirilemez (CHECK 409). Eski/pasif sözleşme göçü de ancak TEYIT_BEKLIYOR olarak girebilir. | `04_…:65, 145-146` | `account_id IS NOT NULL OR status IN ('TEYIT_BEKLIYOR','PASIF')`. Ham metin kolon boyu E03 ile aynı tutulur (`String(200)`, tasarımda 250). |
| B11 | **İki farklı "eşleşmemiş" anahtarı.** E14-06 `tr_normkey(location_raw)`, E14-18 `unvan_anahtari(ham)` kullanıyor; E09 ziyaret anahtarı `customer_id+address_id+city`. Havuz, takvim ve rapor aynı işi farklı gruplar. E12 B8 bu fonksiyonların E14'te tek olmasını bekliyor. | `09_…:346`; tasarım §7 E14-06/E14-18 | Tek fonksiyon `ana_veri.lokasyon_anahtari(kayit)`; grup ve rapor boyutu ondan türer, E09/E12 de onu çağırır. |
| B12 | **`il` serbest metin; normalleştirme tanımsız.** Hızlı ekleme `region=il`, lokasyon `city` serbest metin; E12 kontrolü (B8) şehir normalleştirmesini E14'e bırakmış ama E14'te yok. | `account.py:95, 186` | Eklenen madde E14-D02. |
| B13 | **Küçük:** `account_merges` için gerekçe "FK yalnız users'a gittiği için `_TRUNCATE`'e eklenir" yanlış: `users` listede ve `CASCADE` olduğundan tablo zaten temizlenir; eklemek zararsız. `K16`'daki "VEYA" izni `require_permission` (hepsi gerekli) ile yazılamaz; gövdede `_izin` kalıbı gerekir (`attachments.py:117-121`). Birleştirmeden sonra canlı `/api/hesaplar?q=` takma adı aramaz; kaynak unvanla yalnız `musteri-ara` bulur — kabul metni buna göre kalmalı. Canlı `/kart` sipariş `grand_total`'ı `sees_cost` uygulamadan dönüyor (gözlem; dokunulmaz). | `conftest.py:41-50`; `deps.py:79-97`; `accounts.py:109-119, 338` | Metin düzeltmesi. |

## 3. Madde kararları

| Madde | Karar | Öncelik | Gerekçe / düzeltme |
|---|---|---|---|
| E14-01 | DEĞİŞTİR | P1 | B1, B2: VKN kontrolü yalnız değişen/yeni `tax_no` için; yeni gövde alanları `Account(**…)`'dan hariç; `is_verified` yalnız `/dogrula` ile. Hızlı eklemede benzer ad kontrolü silinmiş-birleşmiş hesapların takma adlarını da tarar. |
| E14-02 | DEĞİŞTİR | P1 | B7, B8, B9: `_SAHIP_TABLOSU`, `ORDER BY is_primary DESC, id`, kısmi tekil indeks. Geri kalan (nullable kolonlar, `line` gevşetme + CHECK, silme ucu yok, kapsam) doğru. |
| E14-03 | DEĞİŞTİR | P1 | B5. Yeni kişisel veri alanı açan sürümle aynı anda gelmeli; P2 değil P1. |
| E14-04 | DEĞİŞTİR | P1 | B10: CHECK PASIF'e de izin verir; ham metin boyları E03 ile aynı. |
| E14-05 | KABUL | P1 | Seçici + `lokasyon_dogrula` + plan ön dolumu doğru ve gerekli; canlıya dokunmuyor. |
| E14-06 | DEĞİŞTİR | P2 | B11: tek `lokasyon_anahtari` fonksiyonu (E09/E12 ile ortak). |
| E14-07 | KABUL | P2 | Canlı `/kart` değişmiyor; ayrı uç, birim kapsamı, `sees_cost`. |
| E14-08 | DEĞİŞTİR | P1 | Ölçüme eklenir: birden çok adresli hesap sayısı (B8), aynı VKN'li aktif hesap grupları (B1 yayın kapısı), `region/city` farklı yazımları (E14-D02). |
| E14-09 | KABUL | P1 | İçe aktarma çerçevesini yeniden kullanıyor; onaysız satır yazmıyor; idempotent. Yazılan her satır `lokasyon_dogrula`'dan geçmeli. |
| E14-10 | DEĞİŞTİR | P1 | 3. adım (ad anahtarı eşleşmesi) yalnız TEK aday varsa bağlar; birden çok aday "eksik" sayılır. `unvan_anahtari` ek atarken farklı firmaları tek anahtara indirebilir. |
| E14-11 | KABUL | P2 | E04'te karşılığı yok; EXCLUDE yerine onaylı 409 doğru. |
| E14-12 | DEĞİŞTİR | P2 | B3, B4, B5: izin listeli birleştirme, LOKASYON'da aynı hesap şartı, `addresses` ekleri, değer saklamayan `account_merges`, Clock. |
| E14-13 | KABUL | P2 | "VEYA" izni gövdede kontrol edilir (B13). |
| E14-14 | KABUL | P2 | Küçük, E05 servisinde tek nokta. |
| E14-15 | KABUL | P2 | `quotes.address_id` nullable; sunucu tarafı kopyalama doğru. |
| E14-16 | KABUL | P2 | K3 ile tutarlı. |
| E14-17 | KABUL | P3 | Kolonlar E01'e ait; tutar yok. |
| E14-18 | KABUL | P3 | Mükerrer aday grubu sayısı kapsamlı hesaplanmalı (E12 B9). |

## 4. Eklenen maddeler

### E14-D01 · Servis rollerinin canlı hesap verisine erişiminin daraltılması (P1, S)
- **Sorun:** B6. `KENDI_BIRIMI` hesaplara uygulanmadığı için SERVIS_SEF bütün müşterilerin IBAN/VKN'sini ve mobilite kartını; SERVIS_OPERASYON `hesap.yaz` ile montaj noktası/bayi/tedarikçi IBAN, VKN, rol ve `partner` alanlarını değiştirebilir (hak ediş ödeme listesi).
- **Yaklaşım:** Yeni izin açmadan:
  1. `SERVIS_SEF` ve `SERVIS_OPERASYON`'dan `hesap.gor` ve `hesap.yaz` kaldırılır; yalnız `SERVIS_YONETICI`'de kalır (E01 §3.3 ve E13 tablosu buna göre düzeltilir).
  2. `GET /api/lokasyonlar*` ve `servis-karti` `hesap.gor` VEYA `servis.gor` ile açılır; `servis.gor` yanıtında IBAN/VKN/vergi dairesi alanı hiç yok (K25 değişmeden).
  3. Servis tarafı müşteri düzenlemesi yeni `PATCH /api/teknik-servis/ana-veri/musteriler/{id}` ucu: `lokasyon.yaz`; yalnız `title, region, phone, email, dis_referans`; hesap `is_montaj_noktasi/is_bayi/is_tedarikci` ise 409 ("mobilite hesabı, Hesaplar ekranından"); `version` + `log_change`.
  4. K16'daki "`servis.planla` VEYA `hesap.yaz`" kuralı "`servis.planla`" olur.
- **Kabul:** SERVIS_SEF `/api/hesaplar` ve `/kart` 403; lokasyon ve servis kartı 200, yanıtta `iban/tax_no` yok; SERVIS_OPERASYON montaj noktası hesabında servis PATCH'i 409 ve kayıt değişmemiş; `test_altin_kayit` yeşil.

### E14-D02 · İl adı normalleştirmesi (P2, S)
- **Sorun:** B12. `region` ve `addresses.city` serbest metin; havuz/rapor/ziyaret anahtarı ve "ad + il" araması farklı yazımlarda bölünür.
- **Yaklaşım:** `normalize.il_adi(ham) -> str | None` (81 il listesi, `tr_normkey` ile eşleşme); hızlı ekleme ve lokasyon POST/PATCH'te bilinmeyen il 400; canlı `HesapIn.region` değişmez (mobilite); E14-08 ölçümü farklı yazımları listeler, eşleştirme profili düzeltir.
- **Kabul:** "istanbul", "İSTANBUL", "Istanbul" aynı değeri üretir; bilinmeyen il 400; canlı hesap formu davranışı değişmez.

## 5. Kararlar hakkında

- **Makul:** K1, K2, K3, K4, K5, K6, K8, K9, K10, K11, K12, K13, K15, K18, K19, K20, K21, K22, K23.
- **Düzeltilmeli:** K7 (doğrulama `hesap.birlestir` doğru, ama E14-D01 ile `hesap.yaz` daralır), K14 (doğru; SEF/OPERASYON'a genişletilir — E14-D01), K16 (VEYA → yalnız `servis.planla` + kapalı işte `hesap.birlestir`), K17 (somut tablo listesi yerine izin listesi — B3), K24 (sıralama `is_primary DESC, id`; "çıktı değişmez" ölçümle teyit — B8), K25 (`servis.gor` ile hafif lokasyon/kart okuması eklenir — E14-D01).
