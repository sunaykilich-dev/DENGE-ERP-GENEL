# E06 Kiralama ve Kiralık Cihaz Envanteri: Bağımsız Kontrol Raporu

> Tarih: 21.10.2026 · Denetlenen: `10_canli_entegrasyon/06_kiralama_depo_entegrasyon.md`
> Yöntem: Canlı kod okundu (`denge-erp/backend/app`, `backend/tests`, `docker-compose.yml`, `Makefile`). Kaynak gereksinim `02_moduller/_ozet/06_kiralama_depo.json` ve kardeş belgeler (00, E01, E02, E05, E09, E11, E13, E14) ile karşılaştırıldı. Kaynak koda dokunulmadı.

---

## 1. Genel hüküm

Tasarımın ana kararları doğru ve canlı mimariyle uyumlu:
- Kiralık envanter `devices`'a yazılmıyor (K1). Global `uq_devices_seri` kısmi tekil indeksi (`models/device.py:93-98`) ve `stock_movements` CHECK'i (`models/stock.py:218-221`) bu kararı zorunlu kılıyor.
- Toplu stok bakiyesi hareket toplamından hesaplanıyor. Bu, canlının kendi ilkesi (`models/stock.py:200-204`).
- Müşteri `accounts`, ürün `products`, depo `warehouses`, ek, görev, denetim, PDF ve Excel yeniden kullanılıyor; kopya varlık üretilmiyor.
- `work_orders`, `settlements`, `devices` ve `device_custody_history` tablolarına yazım yok. Altın kayıt testi etkilenmez.

"Canlıda YOK" tespitleri doğrulandı. Canlıdaki tek `KIRALIK` izi mobilite sahiplik değeri `MUSTERI_KIRALIK` (`models/stock.py:56`) ve bu modülle ilgisiz.

**Sorunlar dört grupta toplanıyor:**
1. Canlı kodla çelişen iddialar (§2: EXCLUDE sayısı, `extra="forbid"` 400 değil 422 döner, `_SAHIP_TABLOSU`, `api/imports.py` dalına gerek yok, seed üretimde çalışmaz).
2. Paylaşılan `warehouses` tablosunda mobilite ↔ kiralama çapraz kullanımına karşı koruma yok. "Stok ekranı değişmez" iddiası yanlış (§2.1).
3. Kardeş belgelerle ad ve sözleşme uyuşmazlıkları (§3).
4. Rol tasarımında bir boşluk ve bir fazlalık. `KIRALAMA_OPERASYON` servis işi açamıyor; E13'ün `SERVIS_OPERASYON` rolü aynı işi zaten görüyor.

---

## 2. Canlı koda karşı doğrulanan teknik bulgular

### 2.1 Paylaşılan depo tablosu: çapraz kullanım koruması yok (yüksek risk)

`GET /api/stok/depolar` (`api/stock.py:361-371`) tüm aktif depoları filtresiz döner. Mobilite seri hareketi (`POST /api/stok/hareket`, `api/stock.py:296`), transfer, sipariş sevki (`api/orders.py:616`), satın alma girişi (`api/purchasing.py:91`) ve cihaz göçü (`services/imports/eslesme.py:483`) bir `warehouse_id` alıyor ve depo türünü sınamıyor.

`KIR-DEPO-1..3` eklendiği anda iki sonuç doğar:
- Mobilite kullanıcısı kiralama deposunu açılır listede görür.
- Mobilite cihazını ya da serisiz stoğu kiralama deposuna yazabilir. Kiralama servisi de tersine mobilite deposuna hareket yazabilir.

Tasarımın "stok ekranı değişmez" ifadesi bu nedenle doğru değil. Gerekli önlemler E06-D01'de toplandı.

### 2.2 Diğer bulgular

1. **EXCLUDE sayısı testte sabit değil.** `tests/migration/test_migration_zinciri.py:71-102` EXCLUDE sayısını gidiş-dönüşten önce ve sonra ölçüp karşılaştırıyor; sabit bir beklenen sayı yok. E06-04 ve E06-10'daki "zincir testindeki EXCLUDE sayısı güncellenmeli" ifadesi yanlış, "Canlı risk" satırı da geçersiz. Gerçek koşul şu: downgrade `ex_rtahsis_cihaz_cakisma` dahil her şeyi düşürmeli ve `rental_no_seq` sequence'ini de silmeli.
2. **`extra="forbid"` 400 değil 422 üretir.** Canlıda `RequestValidationError` eşleyicisi yok (`main.py` yalnız `StaleDataError`, `IntegrityError`, `DataError` eşliyor). E06-18'in "durum gönderilirse 400" kabulü bu yöntemle sağlanamaz. Ya şemada `durum/warehouse_id/product_id/birim` alanları `None` varsayılanla tanımlanır ve doluysa uç 400 fırlatır, ya da kabul 422 olarak düzeltilir. Kaynak kabul 400 istediği için birinci yol önerilir.
3. **Ek sahibi beş yerde tanımlanır, dört yerde değil.** `api/attachments.py:206-214` `_SAHIP_TABLOSU` sözlüğünü kullanıyor. `rentals` ve `rental_assets` buraya eklenmezse `_sahip_var_mi` `True` döner ve olmayan kayda ek yüklenir.
4. **`SAHIP_IZNI` tek yazma izni taşır** (`api/attachments.py:41-52`). İmzalı teslim tutanağını sevkte depo (`kiralama.asama`) yükler. `("kiralama.gor","kiralama.yaz")` seçilirse KIRALAMA_DEPO yükleyemez. Öneri: `rentals → ("kiralama.gor","kiralama.asama")`, `rental_assets → ("kiralama.gor","kiralama.envanter")`.
5. **`api/imports.py`'ye yeni dal gerekmez.** Canlı mekanizma zaten onay istiyor: `cakisma` taşıyan satır, `kararlar` içinde açıkça `guncelle` verilmedikçe `atla` sayılır (`services/imports/cekirdek.py:132-133`). Dört uyumsuzluk `cakisma` olarak işaretlenirse "onaysız aktarım yok" kuralı canlı dosyaya dokunmadan sağlanır. Ek olarak `PROFIL_IZINLERI`'ne dört kod eklenmeli; eklenmezse `api/imports.py:67` KeyError ile 500 döner.
6. **`seeds/kiralama.py` üretimde çalışmaz.** `docker-compose.yml:31` yalnız `python -m app.seeds.dev` çalıştırıyor. Ayrıca seed `products` tablosuna, yani canlı mobilite kataloğuna, 23 ürün yazıyor. `identity_kind` sunucu varsayılanı `'IMEI'` (`models/catalog.py:90`); açıkça verilmezse bariyer IMEI'li ürün olarak doğar. Öneri: katalog verisi seed yerine göç profiliyle (`sistem.goc`) ya da ürün ekranından girilir. Depolar `sistem.ayar` uçlarıyla açılır. Seed kalırsa `seeds.dev.main` içinden çağrılır ve her ürün için `identity_kind/type` açıkça yazılır.
7. **`rental_no_seq` testlerde sıfırlanmaz.** `TRUNCATE ... RESTART IDENTITY` (`tests/conftest.py:41-50`) yalnız tabloya ait sequence'ları sıfırlar. Ya `OWNED BY rentals.id` verilir ya da testler numaranın değerine bağlanmaz. Tek sequence yıl değişince sıfırlanmaz; `KIR-2027-00513` gibi numaralar beklenen davranış olarak yazılmalı.
8. **Eşzamanlılık testi gerçek.** `client` her istek için ayrı oturum açıyor (`tests/conftest.py:159-161`). `asyncio.gather` ile gönderilen iki tahsis isteği gerçekten iki transaction'dır. E06-04 kabulü uygulanabilir.
9. **Kilit sırası.** `planla` ve uzatma birden çok kalem için `rental_catalog_items FOR UPDATE` alıyor. Kilitler `product_id` sırasıyla alınmazsa iki kiralama arasında deadlock oluşur. Kural yazılmalı.
10. **Toplu bakiye yazım anında korunmalı.** E06-03 "bakiye ≥ 0" koşulunu yalnız gece worker'ında denetliyor. Toplu transfer, kontrol, iade düzeltmesi ve sayım hareketleri `from_*` tarafında bakiye düşürür. `hareket_yaz` bu hareketlerde katalog satırını kilitleyip kaynak bakiyenin yeterli olduğunu doğrulamalı (409). Worker yalnız ikinci savunma hattıdır.
11. **IMEI ürünü kiralık envantere girerse çift envanter oluşur.** `ck_rasset_seri_takipli` yalnız `identity_kind <> 'YOK'` diyor. Araç takip birimi IMEI'li cihaz kiralarsa aynı fiziksel cihaz hem `devices`'ta hem `rental_assets`'te bulunur. `rental_assets` için `identity_kind = 'SERI_NO'` CHECK'i eklenmeli. `rental_catalog_items.birim` MOBILITE/ARAC_TAKIP olmamalı; bu birimlerin kiralık cihazı canlıda `MUSTERI_KIRALIK` ile izleniyor (E06-D05).
12. **Ürün kimlik tipi değişikliğinde mesaj yanıltıcı.** `fk_rasset_urun_kimlik ON UPDATE RESTRICT` ihlali `main.py:71-77` eşlemesiyle "Bağlanmak istenen kayıt bulunamadı" mesajına düşer. `api/catalog.guncelle` koruması kiralık cihaz sayısını da açıkça sınamalı ve Türkçe gerekçeli 409 döndürmeli.
13. **`DEPOYA_ALINDI` otomatik geçişi her durumdan yapılamaz.** Makinede yalnız `SEVK_EDILDI→DEPOYA_ALINDI` ve `TOPLANDI→DEPOYA_ALINDI` kenarları var. `KURULUM_YAPILDI` ya da `DEVREYE_ALINDI` durumundaki kiralamada son iade otomatik geçişi 409 ile patlar. Kural açık yazılmalı: kurulum yapılmış kiralamada son iade önce `TOPLANDI` ister. Kısmi iade her sevk sonrası durumda serbesttir.
14. **`MUSTERIDE` sonucu sayaç değiştirmez.** "Tüm tahsisler sonuç alınca DEPOYA_ALINDI" ifadesi belirsiz. Doğru koşul: her AKTIF tahsiste `iade_adet + kayip_adet = sevk_adet`.
15. **Kısmen sevk edilmiş tahsisin kalanı.** Kapanış "sevk edilmemiş AKTIF tahsis kalmamalı" diyor; qty=10, sevk=6 olan tahsisin 4 adedi ne olacak, belli değil. Kapanışta kalan otomatik `TAHSIS_COZ` hareketiyle çözülmeli ya da kullanıcıdan açık çözme istenmeli. Biri seçilmeli; öneri otomatik çözme ve olay kaydı.
16. **Geri almada doğrudan durum ataması.** E06-08 durumu makine dışı bir geriye atamayla `onceki_durum`'a döndürüyor; bu, rehber §1.7'deki "doğrudan atama yok" disiplininden bilinçli bir sapma. Tek fonksiyonda yapılmalı, docstring'de sapma gerekçelendirilmeli. `KAPANDI` ve `IPTAL` terminal olduğu için geri alınamaz.

---

## 3. Kardeş belgelerle uyuşmazlıklar

| # | Konu | E06 | Kardeş belge | Karar |
|---|---|---|---|---|
| 1 | Servis işi durum adları | `uq_so_kiralama_tur_acik ... status NOT IN ('TAMAMLANDI','IPTAL','KAPANDI')` | E01: `KAPATILDI`, `TEKRAR_ACILDI` | E01 adları kullanılır. Açık iş tanımı `status NOT IN ('KAPATILDI','IPTAL')` olmalı; aksi halde TAMAMLANDI işin yanında ikinci iş açılır ve ilk iş TEKRAR_ACILDI olunca tekil indeks patlar. |
| 2 | `TOPLAMA` türü | "çekirdekte eklenmeli" | E01 `SERVIS_TURLERI`'nde yok | E01 tuple'ına E01 migration'ı yayımlanmadan eklenir. |
| 3 | Kurulum işinin açılış izni | `kiralama.yaz` + `servis.yaz` | KIRALAMA_OPERASYON rolünde `servis.yaz` yok | Kurulum işini fiilen yalnız SERVIS_YONETICI ve ADMIN açabilir. E06-01'de çözülür. |
| 4 | Operasyon rolü | Yeni `KIRALAMA_OPERASYON` | E13 §3.3 ve E01: `SERVIS_OPERASYON` (KENDI_BIRIMI; `servis.yaz`, `hesap.yaz`, görev) | Rol enflasyonu. `kiralama.gor/yaz` SERVIS_OPERASYON'a verilir; ayrı personel teyit edilirse KIRALAMA_OPERASYON açılır. |
| 5 | Teknisyen kapsamı | SERVIS_TEKNISYEN'e `kiralama.gor` | E13: SERVIS_TEKNISYEN `KENDI_ISLERI` | Teknisyen kiralama no ve seri listesini servis işinde görür. `kiralama.gor` verilmez (en az yetki). |
| 6 | Atölye köprüsü | `workshop_records.rental_asset_id` FK, doğrudan kayıt açma | E05-27: kabul servis fonksiyonu, `service_type='KIRALAMA_TAKIP'`, müşteri = kiracı | E05 kabul fonksiyonu çağrılır; FK E06'daki gibi `rental_asset_id` olur. Müşteri için öneri Denge iç hesabıdır (cihaz Denge demirbaşı); kullanıcıya teyit için sorulmalı. |
| 7 | Süre "eksik" | Kendi hesabı | E09 `sure_durumu/sure_ozeti` (EKSIK/KISMI/TAM/BEKLENMIYOR) | E09 fonksiyonu çağrılır (E06-19, E06-21). |
| 8 | Ekip | `service_plan_members` | E02: ekip ziyarete/plana bağlı (`service_visits`, `service_plans`) | Ekip `service_order_id` → aktif plan → üyeler zinciriyle okunur. |
| 9 | Depo kolonları | `warehouses.birim`, `kiralama_deposu` | E11: `birim NULL = ortak`, `servis_deposu`, `ck_warehouse_tur_tekil` | Uyumlu. Kolonları açan migration E06'dır; E11 kendi kolonunu sonra ekler. |
| 10 | Müşteri/lokasyon | `customer_id`, `address_id` | E14: `lokasyon_dogrula`, adres aynı müşterinin ve aktif; tabloda `account_id` yazıyor | E06 `customer_id` adını korur (canlı `quotes.customer_id` emsali); E14 tablosu düzeltilir; `lokasyon_dogrula` çağrılır. |
| 11 | Rehber §6.2 | `rental_allocations` + `daterange` | 00: `rentals + rental_items` "satır başına seri", `ex_kiralama_ekipman_cakisma` `equipment_id`/`tstzrange` | E06 modeli doğru (kalem ≠ tahsis); rehber güncellenir. `Date` kolonunda `daterange` kullanmak canlı yarı açık ilkesine uygun. |
| 12 | KPI kutusu | Sayfada kendi kutuları | E12 KPI motoru / `KpiKutusu` | E12 bileşeni kullanılır. |

---

## 4. Madde bazında karar

| ID | Karar | Öncelik | Özet gerekçe |
|---|---|---|---|
| E06-01 | DEĞİŞTİR | P1 | SERVIS_OPERASYON'a izin verilir; teknisyenden `kiralama.gor` çıkarılır; ek sahibi izinleri |
| E06-02 | DEĞİŞTİR | P1 | `_SAHIP_TABLOSU`, depo türü doğrulaması, seed yerine `sistem.ayar`/göç, `lokasyon_dogrula`, sequence |
| E06-03 | DEĞİŞTİR | P1 | Toplu bakiye yazım anında kilit + kontrol; cihaz satırı kilidi |
| E06-04 | DEĞİŞTİR | P1 | EXCLUDE sayısı iddiası kaldırılır; katalog profili zorunlu; birim tutarlılığı |
| E06-05 | DEĞİŞTİR | P1 | DEPOYA_ALINDI kenar kuralı, kısmi tahsis kalanı, iade durumları |
| E06-06 | KABUL | P1 | İlk sevkin tüm tahsisi göndermek zorunda olmadığı netleştirilir |
| E06-07 | DEĞİŞTİR | P1 | Tamamlanma koşulu sayaçla; MUSTERIDE yalnız not; toplu KAYIP için bulundu |
| E06-08 | KABUL | P2 | Doğrudan atama sapması belgelenir; terminaller geri alınmaz |
| E06-09 | DEĞİŞTİR | P1 | `api/imports.py`'ye dokunulmaz; `cakisma` + `kararlar`; `PROFIL_IZINLERI` |
| E06-10 | DEĞİŞTİR | P1 | EXCLUDE sayısı yanlış; sequence sıfırlama; depo çapraz testi |
| E06-11 | DEĞİŞTİR | P2 | Atölye E05 kabul fonksiyonuyla; ATOLYEDE dönüşü; toplu kontrolde kilit |
| E06-12 | DEĞİŞTİR | P2 | Formül çelişkisi (KONTROLDE); kilit sırası |
| E06-13 | KABUL | P2 | `SAHIP_IZNI` yükleme izni `kiralama.asama` |
| E06-14 | KABUL | P2 | — |
| E06-15 | KABUL | P2 | E14 `lokasyon_dogrula` ve irtibat-müşteri kuralı eklenir |
| E06-16 | DEĞİŞTİR | P2 | Seed canlı kataloğa yazmaz; `identity_kind` açık; yalnız SERI_NO/YOK; anlamlı 409 |
| E06-17 | KABUL | P2 | Eksik tahsis uyarısına yol verilir |
| E06-18 | DEĞİŞTİR | P2 | `extra="forbid"` 422 üretir; açık alan + 400 |
| E06-19 | DEĞİŞTİR | P2 | E01 durum adları, TOPLAMA, izin boşluğu, E09/E02 fonksiyonları |
| E06-20 | KABUL | P3 | — |
| E06-21 | DEĞİŞTİR | P3 | E09 süre fonksiyonu, E12 KPI motoru |
| E06-22 | DEĞİŞTİR | P2 | Onayda dosya yeniden doğrulanır (sha256); sayım P3'e ayrılır |
| E06-23 | KABUL | P2 | E12/E14 bileşenleri; mobilite depo listesi D01 ile korunur |

Ayrıntılı gerekçe ve düzeltilmiş metin StructuredOutput `verdicts` alanındadır.

---

## 5. Eklenen maddeler

| ID | Başlık | Öncelik |
|---|---|---|
| E06-D01 | Paylaşılan `warehouses` tablosunda mobilite ↔ kiralama çapraz kullanım koruması | P1 · S |
| E06-D02 | Kiralık cihaz yaşam döngüsünün kapanışı: atölye dönüşü ve envanterden çıkış (HURDA) | P2 · S |
| E06-D03 | Kardeş tasarımlarla ad ve sözleşme hizalaması (§3 tablosu tek kaynak) | P1 · S |
| E06-D04 | Kiralama birimi ile ürün ve depo birimi tutarlılığı | P1 · S |
| E06-D05 | Mobilite ile çift envanter önlemi: IMEI ürünü ve mobilite birimleri kiralık envantere girmez | P1 · S |

---

## 6. Kararların değerlendirmesi

| Karar | Hüküm |
|---|---|
| K1 (devices'a yazılmaz) | Doğru. `uq_devices_seri` global (`models/device.py:93-98`). Tamamlayıcı koşul E06-D05: IMEI ürünü hariç tutulmalı. |
| K2 (toplu bakiye hesaplanır) | Doğru, ancak yazım anı kontrolü şart (§2.2/10). |
| K3 (bloke zamanı) | Makul; kaynak sorusu 3 ile uyumlu. |
| K4 (409/400/404) | Doğru. Tek istisna: `extra="forbid"` ile 400 üretilemez (§2.2/2). |
| K5 (kurulum isteğe bağlı) | Makul; DEPOYA_ALINDI kenar kuralı yazılmalı (§2.2/13). |
| K6 (4 izin, depo = `sistem.ayar`) | Makul; E11 K15 ile aynı. Ek yükleme izni §2.2/4'teki gibi. |
| K7 (2 yeni rol) | Kısmen. KIRALAMA_DEPO makul; KIRALAMA_OPERASYON E13 SERVIS_OPERASYON ile çakışıyor. |
| K8 (kontrolü depo yapar) | Makul; atölye adımı E05 fonksiyonuyla. |
| K9 (toplu giriş kiralama ucunda) | Doğru; `Profil.dogrula(db, satirlar)` kullanıcı almıyor (`services/imports/cekirdek.py:100`). |
| K10 (uyarı hesaplanır) | Doğru. |
| K11 (kiralıkta PB yok) | Doğru; "1 cihaz = 1 PB" kuralı etkilenmez. |
| K12 (müşteri 400) | Doğru. Şemada `customer_id: int | None` olmalı ki 422'ye düşmesin. |
| K13 (fiyat yok) | Doğru; `maliyet.gor` kümesi değişmez. |
| K14 (rücu yok) | Makul; Logo kapsam dışı. |
| K15 (uzatma = tarih değişikliği) | Makul. |
| K16 (depolar `warehouses`'ta) | Yeniden kullanım doğru, ancak çapraz kullanım koruması eksik (E06-D01). |
| K17 (`daterange '[)'`) | Doğru. `ck_rental_tarih (bitis > baslangic)` boş aralığı engellediği için EXCLUDE delinmez. |
| K18 (sequence) | Doğru; test sıfırlaması ve yıl davranışı yazılmalı (§2.2/7). |
| K19 (ekleme-yalnız, ORM dinleyici) | Makul. Dinleyici toplu `update()` ifadesini yakalamaz; bu, kabulde yazılmalı. |
| K20 (ters kenar yok) | Makul; doğrudan atama sapması belgelenmeli (§2.2/16). |
| K21 (ayrı API dosyası) | Rehber §6.2 ile uyumlu. |
| K22 (birim katalogdan) | Doğru; E06-D04 ile kiralama birimine bağlanmalı. |

---

## 7. Mobilite akışlarına etki

- `work_orders`, `work_order_items`, `settlements`, `devices`, `device_custody_history` ve `device_vehicle_assignments` tablolarına yazım ya da kısıt değişikliği yok. İş emri onayı → hak ediş zinciri ve altın kayıt testi etkilenmez.
- IMEI ve kimlik kuralı korunuyor. `fk_devices_urun_kimlik` CASCADE davranışı değişmiyor. Yeni RESTRICT FK, kiralık cihazı olan ürünün kimlik tipini kilitler; mobilite ürünleri etkilenmez.
- Mevcut EXCLUDE kısıtlarına dokunulmuyor; yeni EXCLUDE yeni tabloda.
- **Risk taşıyan tek nokta paylaşılan `warehouses` tablosu (§2.1).** E06-D01 uygulanmadan kiralama depoları açılmamalı. Mobilite tarafındaki değişiklik iki noktayla sınırlı: depo listesinde kiralama depolarının filtrelenmesi ve mobilite yazma servislerinde tek satırlık bir depo türü koruması.
- `api/catalog.guncelle`'ye eklenen koruma yalnız kiralama kaydı olan ürünlerde devreye girer.
- `api/imports.py`'ye dokunmaya gerek yok (§2.2/5).
