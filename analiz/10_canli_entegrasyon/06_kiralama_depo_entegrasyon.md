# M06 Kiralama ve Kiralık Cihaz Envanteri: Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21. Yalnız rapor yazıldı; canlı ERP kaynak koduna dokunulmadı.
> Girdiler:
> - `analiz/02_moduller/_ozet/06_kiralama_depo.json`: 21 onaylı madde, hiçbiri `dotnet_specific` değil.
> - `06_kiralama_depo_tasarim.md`, `06_kiralama_depo_denetim.md`.
> - `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`.
> - Canlı kod: `denge-erp/backend/app`, `frontend/src`.
>
> Dosya:satır referansları `backend/app/...` köküne göredir.
> Madde kimlikleri `E06-NN` biçimindedir; eski kimlik her maddenin başında yazılıdır.

---

## 0. Özet

**Canlıda durum.** Kiralama modülünün canlıda **hiçbir karşılığı yok**.
- `grep kirala|rental` taramasında yalnız iki iz çıkıyor:
  - Mobilite cihaz sahipliğindeki `MUSTERI_KIRALIK` değeri (`models/stock.py:56`). Bu, abonelikle kiralanan araç takip cihazına aittir ve bu modülle ilgisi yoktur.
  - Hesap birleştirme betiğindeki bir firma adı.
- Bu nedenle 21 maddenin tamamı **YOK** ya da **KISMEN** durumunda. KISMEN olanlarda canlıdaki altyapı yeniden kullanılıyor: depo, ürün kataloğu, ek dosya, denetim izi, PDF, içe aktarma, uyarı, rapor, worker.

**Tek mimari karar.** Kiralık envanter `devices` tablosuna **yazılmaz**. Bunun yerine `services/teknik_servis/` altında ayrı bir **kiralık envanter defteri** kurulur:
- seri takipli cihazlar için `rental_assets` satırları,
- seri takipsiz toplu stok (bariyer) için ekleme-yalnız `rental_inventory_movements` hareket toplamı.

Toplu stok için seçilen yöntem canlının kendi serisiz stok ilkesidir: "bakiye ayrı kolonda tutulmaz, hareket toplamından hesaplanır" (`models/stock.py:200-204`). Aynı ilke burada tekrar uygulanıyor.

**Kiralık envanterin `devices` tablosuna girmemesinin dört gerekçesi:**
1. Global `uq_devices_seri` var; X-Ray ve telsiz serileri üreticiler arasında çakışabilir.
2. `devices` mobilite stok yaşam döngüsünü (STOKTA→AKTIF) ve gece uzlaştırmasını taşıyor.
3. `_stok_adedi` (`api/catalog.py:113-135`) ve `denge_stogu` raporları kiralık bariyerleri satış stoğu gibi sayardı.
4. `stock_movements` CHECK listesi (`ck_stok_hareket_neden`) canlı tabloda değiştirilemez (mimari kural 11).

**Mobilite akışı.** `work_orders`, `settlements`, cihaz durum makinesi ve `device_custody_history` EXCLUDE kısıtlarına hiçbir yazım yapılmaz. Altın kayıt testi (932 iş / 552.825,00 TL) etkilenmez.

---

## 1. Canlıda yeniden kullanılan varlıklar (kopya üretilmez)

| İhtiyaç | Canlı varlık | Nasıl |
|---|---|---|
| Müşteri | `accounts` (`is_musteri`) | `rentals.customer_id` → `accounts.id` (RESTRICT). Serbest metin müşteri adı yok; eski "boş müşteri adı 500" hatası FK + Pydantic ile 400'e dönüşür |
| Lokasyon | `addresses` (`models/account.py:177`) | `rentals.address_id` (nullable) + `lokasyon_metni` (etkinlik alanı gibi adres kartı olmayan yer için) |
| İrtibat | `contacts` (`models/account.py:163`) | `rental_contacts(rental_id, contact_id, rol)`. Kişi müşterinin kişisi olmalı (servis kuralı) |
| Ürün/model | `products` (`models/catalog.py:53`) | Kiralama kataloğu ayrı ürün tablosu DEĞİL; `rental_catalog_items` yalnız profil (birim, kategori, sıra, aktif). Seri takibi `products.identity_kind` alanından okunur (`SERI_NO/IMEI` = seri takipli, `YOK` = toplu) |
| Depolar | `warehouses` (`models/stock.py:64`) | Kiralama depoları 1–3 yeni satır olarak eklenir. `warehouses` tablosuna nullable `birim` ve `kiralama_deposu` kolonları gelir |
| Teklif | `quotes` | `rentals.quote_id` nullable FK (kaynak teklif); `quotes` tablosuna yazım yok |
| Ek dosya | `attachments` | `EK_SAHIPLERI += "rentals","rental_assets"`, `EK_TURLERI += "TESLIM_TUTANAGI","IADE_TUTANAGI"`, `SAHIP_IZNI`, `_kapsam` (müşteri + birim) |
| Görev panosu | `services/gorevler.py:47-57` | `KayitTipi("kiralama","Kiralama",Rental,("rental_no",),"/kiralamalar?id={id}")` |
| Denetim izi | `services/audit.py` | Her yazma ucunda commit'ten önce `audit.log/log_change`; irtibat değişikliklerinde `is_personal_data=True` |
| PDF | `services/pdf.py`, `services/belgeler.py` | `belgeler.kiralama_tutanak_baglami` + `templates/kiralama_tutanak.html` |
| Excel | `services/export.py` | `satirlari_xlsx_async` |
| İçe aktarma | `services/imports/` (`PROFILLER`, `PROFIL_IZINLERI`) | Pilot verinin göçü için `KiralamaGocProfili`. Toplu envanter girişi kiralama ucunda yapılır, yalnız ayrıştırıcı `cekirdek.oku/sablon_xlsx` yeniden kullanılır (gerekçe Karar K9) |
| Uyarı | `services/uyarilar.py` | `if user.has("kiralama.gor"):` bloğu |
| Ayar | `services/settings.py` `DEFAULTS` | eşik günleri |
| Worker | `worker.py` `GOREVLER` | `kiralama-uzlastirma` |
| Servis iş emri | `service_orders` (teknik servis çekirdeği, ayrı entegrasyon belgesi) | `service_orders.rental_id` nullable FK; kurulum/toplama işi |
| Atölye | `workshop_records` (M05 entegrasyonu) | `workshop_records.rental_asset_id` nullable FK |
| Birim kapsamı | `services/teknik_servis/kapsam.py` (`kapsam_birim`, `birim_disinda_mi`) | Tüm liste, tek kayıt, ek, uyarı, rapor uçlarında |

---

## 2. Veri modeli

Model dosyası: `backend/app/models/servis_kiralama.py`. Dosya `models/__init__.py` içine import edilir ve `__all__` listesine eklenir.

Adlandırma kuralı:
- Tablo ve kolon adları İngilizce.
- Sabitler, mesajlar ve docstring Türkçe.

Kısıt adları `uq_/fk_/ck_/ex_/ix_` önekiyle başlar.

### 2.1 Sabitler

```python
KIRALAMA_DURUMLARI = ("TALEP","PLANLANDI","HAZIRLANIYOR","SEVK_EDILDI","KURULUM_YAPILDI",
                      "DEVREYE_ALINDI","TOPLANDI","DEPOYA_ALINDI","KAPANDI","IPTAL")
KIRALIK_DURUMLARI = ("HAZIR","HAZIR_DEGIL","KONTROLDE","KIRADA","KAYIP","ATOLYEDE")
HAREKET_TURLERI = ("GIRIS","TRANSFER","TAHSIS","TAHSIS_COZ","SEVK","IADE","KAYIP",
                   "BULUNDU","KONTROL","ATOLYE","DUZENLEME","SAYIM","DUZELTME","DEGISIM")
TAHSIS_DURUMLARI = ("AKTIF","KAPANDI","COZULDU")
KONTROL_SONUCLARI = ("UYGUN","EKSIK","ARIZALI")
IRTIBAT_ROLLERI = ("SATIN_ALMA","SAHA_OPERASYON","TEKNIK_SORUMLU","DIGER")
KIRALAMA_OLAY_TURLERI = ("OLUSTUR","DURUM","ASAMA","TAHSIS","SEVK","IADE","KONTROL","IPTAL",
                         "DUZELTME","TARIH","SORUMLU","KALEM","IRTIBAT","NOT")
```

### 2.2 Tablolar

| Tablo | Mixin | Ana kolonlar | Kısıtlar |
|---|---|---|---|
| `rental_catalog_items` | Pk, Timestamp, Actor, SoftDelete, Versioned | `product_id` → products (RESTRICT), `birim`, `kategori` (String 40), `sira`, `is_active` | `uq_rcat_urun` (product_id), `ck_rcat_birim` (BIRIMLER) |
| `rental_assets` (yalnız seri takipli) | Pk, Timestamp, Actor, SoftDelete, Versioned, Source | `product_id`, `identity_kind`, `serial_no` (METİN), `serial_key` (normalize büyük harf), `birim` (katalogdan kopya, değişmez), `warehouse_id` (nullable; KIRADA/KAYIP'ta son depo), `durum`, `eksik_notu`, `notes` | `fk_rasset_urun_kimlik` (product_id, identity_kind) → products(id, identity_kind) **ON UPDATE RESTRICT**; `ck_rasset_seri_takipli` (identity_kind <> 'YOK' AND serial_no IS NOT NULL); `ck_rasset_durum`; `uq_rasset_urun_seri` (product_id, serial_key) WHERE NOT is_deleted; `uq_rasset_kaynak` |
| `rental_inventory_movements` (ekleme-yalnız) | Pk, Timestamp, Actor | `at` (Clock), `kind`, `product_id`, `asset_id` (nullable = toplu), `qty`, `from_warehouse_id`, `to_warehouse_id`, `from_durum`, `to_durum`, `rental_id`, `allocation_id`, `check_id`, `reverses_id` → self, `note` | `ck_rhareket_tur`; `ck_rhareket_adet` (qty > 0); `ck_rhareket_seri_adet` (asset_id IS NULL OR qty = 1); `ck_rhareket_durumlar` (from_durum/to_durum NULL veya listede); `uq_rhareket_ters` (reverses_id) → bir hareket yalnız bir kez ters çevrilir; `ix_rhareket_bakiye` (product_id, to_warehouse_id, to_durum) + (product_id, from_warehouse_id, from_durum); `ix_rhareket_cihaz` (asset_id, at) |
| `rentals` | Pk, Timestamp, Actor, SoftDelete, Versioned, Source | `rental_no` (KIR-YYYY-#####, sequence `rental_no_seq`), `birim`, `customer_id`, `address_id`, `lokasyon_metni`, `proje_adi`, `baslangic` (Date), `bitis` (Date = iade günü), `status`, `sorumlu_user_id`, `quote_id`, `iptal_gerekcesi`, `kapanis_at`, `notes` | `uq_rental_no`, `uq_rental_kaynak`, `ck_rental_birim`, `ck_rental_durum`, `ck_rental_tarih` (bitis > baslangic), `ck_rental_iptal_gerekce` (status <> 'IPTAL' OR iptal_gerekcesi IS NOT NULL), `ix_rental_durum_bitis` |
| `rental_items` | Pk, Timestamp, Actor | `rental_id` (CASCADE), `product_id` (RESTRICT), `qty`, `note` | `uq_ritem_urun` (rental_id, product_id), `ck_ritem_adet` (qty > 0) |
| `rental_contacts` | Pk, Timestamp, Actor | `rental_id` (CASCADE), `contact_id` → contacts (RESTRICT), `rol` | `uq_rcontact` (rental_id, contact_id, rol), `ck_rcontact_rol` |
| `rental_allocations` | Pk, Timestamp, Actor, Versioned | `rental_id`, `rental_item_id`, `product_id`, `asset_id` (nullable), `from_warehouse_id`, `qty`, `sevk_adet`, `iade_adet`, `kayip_adet`, `baslangic`, `bitis` (kiralamadan kopya, uzatmada güncellenir), `durum`, `shipped_at`, `closed_at`, `replaced_allocation_id` (değişim izi) | `ck_rtahsis_seri_adet` ((asset_id IS NOT NULL AND qty=1) OR (asset_id IS NULL AND qty>0)); `ck_rtahsis_sevk` (0 ≤ sevk_adet ≤ qty); `ck_rtahsis_iade` (iade_adet + kayip_adet ≤ sevk_adet); `ck_rtahsis_durum`; **`ex_rtahsis_cihaz_cakisma`**: EXCLUDE USING gist (asset_id WITH =, daterange(baslangic, bitis, '[)') WITH &&) WHERE (asset_id IS NOT NULL AND durum = 'AKTIF'); `ix_rtahsis_urun_depo` (product_id, from_warehouse_id, durum) |
| `rental_events` (ekleme-yalnız) | Pk, Timestamp, Actor | `rental_id`, `at`, `tur`, `onceki_durum`, `yeni_durum`, `alan`, `eski`, `yeni` (JSONB, yalnız durum/tarih/sorumlu), `service_order_id`, `ekip_user_ids` (ARRAY BigInteger), `gerekce`, `geri_alinan_event_id` → self | `ck_revent_tur`; `uq_revent_geri_alma` (geri_alinan_event_id) |
| `rental_checks` | Pk, Timestamp, Actor | `at`, `product_id`, `asset_id` (nullable), `warehouse_id`, `qty`, `sonuc`, `aciklama`, `rental_id`, `workshop_record_id` | `ck_rkontrol_sonuc`; `ck_rkontrol_aciklama` (sonuc = 'UYGUN' OR length(trim(aciklama)) > 0); `ck_rkontrol_seri_adet` |
| `rental_counts` / `rental_count_lines` | Pk, Timestamp, Actor, Versioned / Pk | Sayım: `warehouse_id`, `durum` (ACIK/ONAYLANDI/IPTAL), `onaylayan`, `onay_at`. Satır: `product_id`, `asset_id`, `serial_text`, `sayilan_adet` | `ck_rsayim_durum`; `uq_rsayim_acik` (warehouse_id) WHERE durum='ACIK' |

### 2.3 Canlı tablolara eklenen nullable kolonlar (yalnız ekleme)

| Tablo | Kolon | Kısıt | Risk |
|---|---|---|---|
| `warehouses` | `birim` String(20) NULL, `kiralama_deposu` Boolean server_default false | yeni `ck_warehouse_birim` (birim IS NULL OR birim IN BIRIMLER) | Mevcut satırlar NULL/false kalır; stok ekranı (`api/stock.py:361`) değişmez |
| `service_orders` (teknik servis çekirdeği) | `rental_id` NULL FK → rentals (SET NULL) | `uq_so_kiralama_tur_acik` (rental_id, tur) WHERE rental_id IS NOT NULL AND status NOT IN ('TAMAMLANDI','IPTAL','KAPANDI') AND NOT is_deleted | Henüz canlıda olmayan tablo; çekirdek migration'ından sonra gelir. `ck_so_tur` listesine `TOPLAMA` değeri çekirdek tasarımında eklenmeli (KURULUM zaten var) |
| `workshop_records` (M05) | `rental_asset_id` NULL FK → rental_assets (SET NULL) | — | Aynı |

### 2.4 Toplu stok bakiyesi (hesaplanır, saklanmaz)

```
bakiye(product, depo, durum) = Σ qty [to_warehouse=depo AND to_durum=durum]
                             − Σ qty [from_warehouse=depo AND from_durum=durum]
                               (asset_id IS NULL)
```

- `KIRADA` ve `KAYIP` için depo NULL. Kirada adet, tahsislerde `sevk_adet − iade_adet − kayip_adet` toplamına eşittir. Gece worker bu iki sayıyı karşılaştırır (E06-03).
- Seri takipli cihazda doğruluk kaynağı hareket zinciridir. `rental_assets.durum/warehouse_id` yalnız sorgu kolaylığı için tutulan denormalize alanlardır; canlıdaki `current_*` deseni (`models/device.py:125-130`) ile aynıdır.

### 2.5 Durum makinesi `KIRALAMA` (`services/statemachine.py` → `MAKINELER["kiralama"]`)

```python
KIRALAMA = StateMachine(
    ad="Kiralama",
    baslangiclar=frozenset({"TALEP"}),
    gecisler=_m(
        TALEP=("PLANLANDI", "IPTAL"),
        PLANLANDI=("HAZIRLANIYOR", "IPTAL"),
        HAZIRLANIYOR=("SEVK_EDILDI", "IPTAL"),
        SEVK_EDILDI=("KURULUM_YAPILDI", "DEVREYE_ALINDI", "TOPLANDI", "DEPOYA_ALINDI"),
        KURULUM_YAPILDI=("DEVREYE_ALINDI", "TOPLANDI"),
        DEVREYE_ALINDI=("TOPLANDI",),
        TOPLANDI=("DEPOYA_ALINDI",),
        DEPOYA_ALINDI=("KAPANDI",),
        KAPANDI=(),
        IPTAL=(),
    ),
)
```

- Kurulum adımları isteğe bağlıdır. `SEVK_EDILDI→DEPOYA_ALINDI` yolu telsiz kiralamasında kurulum olmadan ilerler.
- "Kısmi iade" ayrı bir durum değildir. Tahsislerden türetilen `iade_gosterimi` alanıdır: `YOK / KISMI / TAM`.
- Geri alma makineye ters kenar eklemez. `asama_geri_al` yalnız son olayı geri çevirir ve önce `KIRALAMA.dogrula(hedef, mevcut)` ile bu ileri geçişin makinede gerçekten var olduğunu doğrular (E06-08).
- Mevcut `TEKNIK_SERVIS` mobilite rolüne ve iş emri onay akışına dokunulmaz.

---

## 3. İzinler, roller, kapsam (`permissions.py`)

| Kod | Modül | Açıklama | Roller |
|---|---|---|---|
| `kiralama.gor` | Kiralama | Kiralama, kiralık envanter, hareket geçmişi ve tutanağı görür | KIRALAMA_OPERASYON, KIRALAMA_DEPO, SERVIS_YONETICI, SERVIS_SEF, SERVIS_TEKNISYEN, ATOLYE, YONETIM (otomatik `.gor`), ADMIN |
| `kiralama.yaz` | Kiralama | Talep açar; kalem, irtibat, tarih ve sorumlu düzenler; planlar, iptal eder, kapatır | KIRALAMA_OPERASYON, SERVIS_YONETICI, ADMIN |
| `kiralama.envanter` | Kiralama | Envanter girişi, transfer, tahsis, dönüş kontrolü, sayım, toplu giriş, kiralama kataloğu (eski `rentals.inventory`) | KIRALAMA_DEPO, SERVIS_YONETICI, ADMIN |
| `kiralama.asama` | Kiralama | Sevk, iade, kurulum, devreye alma, toplama aşamaları, saha değişimi, son aşamayı geri alma (eski `rentals.stage`) | KIRALAMA_DEPO, SERVIS_SEF, SERVIS_YONETICI, ADMIN |

**Yeni roller:**
- `KIRALAMA_OPERASYON` ("Kiralama & Operasyon"): `kiralama.gor`, `kiralama.yaz`, `hesap.gor`, `urun.gor`, `teklif.gor`, `gorev.gor`, `gorev.yaz`, `servis.gor`, `rapor.gor`, `rapor.disaaktar`. Kapsam `KENDI_BIRIMI`.
- `KIRALAMA_DEPO` ("Kiralama Depo & Lojistik"): `kiralama.gor`, `kiralama.envanter`, `kiralama.asama`, `hesap.gor`, `urun.gor`, `gorev.gor`, `gorev.yaz`, `rapor.gor`. Kapsam `KENDI_BIRIMI`.

**Kurallar:**
- Mevcut `DEPO` ve `TEKNIK_SERVIS` rollerinin izin listeleri **değişmez**.
- `maliyet.gor` kümesi değişmez. Bu modülde fiyat alanı yok.
- Depo adı ve birim değişikliği (eski `warehouse.manage` beklentisi) yeni bir izin istemez. Canlıda depo yazma ucu hiç yok; eklenecek `PATCH /api/stok/depolar/{id}` mevcut `sistem.ayar` iznine bağlanır (Karar K6).
- Kapsam uygulaması:
  - Listeler: `kapsam_musteri(stmt, user, Rental.customer_id)` ve ardından `kapsam_birim(stmt, user, Rental.birim)`.
  - Envanter listeleri: `kapsam_birim(..., RentalAsset.birim)`; toplu stok için `RentalCatalogItem.birim` üzerinden join.
  - Tek kayıt: `birim_disinda_mi` ya da `kapsam_disinda_mi` → 404, yazma gerçekleşmez.
  - Yazmada kiralamanın `birim` alanı değiştirilemez (400).
  - Envanter satırında birim, katalog profilinden gelir ve değişmez. M06-17'deki "eski satırın birimi" açığı yapısal olarak kapanır.

---

## 4. Servis, API ve ön yüz yerleşimi

```
backend/app/models/servis_kiralama.py
backend/app/services/teknik_servis/kiralama.py            # başlık, kalem, irtibat, durum, iptal, kapanış, geri alma
backend/app/services/teknik_servis/kiralik_envanter.py    # giriş, transfer, bakiye, kontrol, sayım, hareket yazıcı
backend/app/services/teknik_servis/kiralama_tahsis.py     # tahsis, sevk, iade, değişim, müsaitlik
backend/app/services/teknik_servis/kiralama_raporlar.py   # 3 rapor + uyarı sorguları + uzlaştırma
backend/app/services/imports/kiralama_goc.py              # pilot veri göç profili (E06-09)
backend/app/api/kiralamalar.py                            # prefix /api/kiralama, tags=["Kiralama"]
backend/app/templates/kiralama_tutanak.html
frontend/src/api/kiralama.ts
frontend/src/pages/KiralamalarPage.tsx, KiralikEnvanterPage.tsx
```

- Hata sınıfı: `class KiralamaHatasi(ValueError)`. API bunu kural ihlalinde 409'a, girdi hatasında 400'e çevirir; ayrım için `kod` alanı kullanılır.
- Servis katmanı yalnız `flush` yapar. `commit` API katmanında, denetim izi yazıldıktan sonra yapılır.
- Saat yalnız `Clock` ile okunur.
- Router `main.py`'de elle kaydedilir: önce import bloğuna, sonra `app.include_router(kiralamalar_api.router)`.
- Menü (`AppLayout` MENU):
  - `{key:"/kiralamalar", label:"Kiralamalar", izin:"kiralama.gor"}`
  - `{key:"/kiralik-envanter", label:"Kiralık Envanter", izin:"kiralama.gor"}`
  - İkisi de "RMA / Servis" kaleminin hemen altına yerleşir.

---

## 5. Maddeler

Her maddede şu alanlar yer alır: **Canlı** (VAR / KISMEN / YOK ve karşılığı), **Yaklaşım**, **Dosyalar**, **Kabul**, **Öncelik / Efor**, **Bağımlılık**, **Canlı risk**.

### E06-01 · M06-16 · Kiralama izinleri, rolleri ve birim kapsamı
- **Canlı:** YOK. `permissions.py:14-77` içinde kiralama izni yok. Birim kapsamı (`KENDI_BIRIMI`, `user_units`) teknik servis RBAC adımında geliyor.
- **Yaklaşım:**
  - §3'teki 4 izin ve 2 rol `PERMISSIONS/ROLES` içine eklenir.
  - Diğer servis rollerinin izin listelerine kiralama kodları eklenir.
  - Uç takma adları: `Okuyucu`, `Yazici`, `Envanterci`, `Asamaci` (`require_permission`).
  - `seeds/dev.py` senkronu izinleri indirir. `ozellestirildi=True` rollere izin inmez; log uyarısı yeterli.
- **Dosyalar:** `permissions.py`, `api/kiralamalar.py`, `tests/unit/test_permissions.py` (mevcut testler otomatik kapsar), `tests/integration/test_kiralama_rbac.py`.
- **Kabul:**
  - `kiralama.yaz` olan ama `kiralama.envanter` olmayan kullanıcı envanter girişinde 403 alır.
  - Yalnız `kiralama.gor` + `kiralama.envanter` olan kullanıcı kontrol yapabilir; başlık PUT isteğinde 403 alır.
  - Her yeni izin en az bir rolde bulunur.
  - `maliyet.gor` kümesi değişmez.
- **Öncelik / Efor:** P1 / S. Yeni uçlar ilk günden doğru anahtarla yazılmalı; "güvenlik en son" ilkesi yetkisiz uç yazmak anlamına gelmez.
- **Bağımlılık:** Teknik servis RBAC + birim adımı.
- **Canlı risk:** Düşük. Yalnız yeni kod eklenir; mevcut roller değişmez.

### E06-02 · (temel) · Kiralama çekirdeği: başlık, kalem, irtibat, müşteri = hesap
- **Canlı:** YOK. `accounts`, `contacts`, `addresses`, `products` ve `warehouses` VAR ve yeniden kullanılır.
- **Yaklaşım:**
  - `rentals`, `rental_items`, `rental_contacts`, `rental_events` ve `rental_catalog_items` tabloları açılır; `rental_no_seq` sequence'i oluşturulur.
  - Belge numarası canlıdaki `count+1` deseniyle değil, sequence ile üretilir: `KIR-{yıl}-{nextval:05d}`.
  - `warehouses` tablosuna 2 nullable kolon gelir. Kiralama depoları `seeds` ile `ON CONFLICT DO NOTHING` olarak eklenir: `KIR-DEPO-1..3`, `kiralama_deposu=true`.
  - Uçlar:
    - `POST /api/kiralama`: başlık, kalemler ve irtibatlar tek işlemde (bkz. E06-15).
    - `GET /api/kiralama`: `sayfala`; filtreler `durum`, `birim`, `musteri_id`, `q`, `kpi`.
    - `GET /api/kiralama/{id}`: `_cikti` ile kalem, tahsis özeti, `iade_gosterimi`, `sonraki_durumlar`.
    - `GET /api/kiralama/{id}/gecmis`: `rental_events`.
  - Görev panosu `KayitTipi` ve ek sahipleri eklenir.
- **Dosyalar:** `models/servis_kiralama.py`, `models/__init__.py`, `services/teknik_servis/kiralama.py`, `api/kiralamalar.py`, `main.py`, `services/gorevler.py`, `models/attachment.py`, `api/attachments.py`, Alembic `kiralama_cekirdek`.
- **Kabul:**
  - Müşteri `is_musteri` olmayan hesap ya da yok → 400.
  - Kapsam dışı müşteri ya da birim → 404.
  - Liste kalem özetini `rental_items` tablosundan okur; başlıkta kopya ürün/seri alanı yoktur.
  - Ek ucu `_kapsam` başka birimin kiralamasında 404 döner.
- **Öncelik / Efor:** P1 / M.
- **Bağımlılık:** E06-01.
- **Canlı risk:** `warehouses` tablosuna nullable kolon ekleniyor; `ck_warehouse_birim` yalnız yeni kolonu sınar, mevcut satırları NULL bırakır. `attachments._kapsam` yeni dala sahip olur ama `accounts` dalı aynen kalır.

### E06-03 · M06-07 · Kiralık envanter, ekleme-yalnız hareket geçmişi, kiralama değişiklik izi
- **Canlı:** KISMEN.
  - Desen olarak `stock_movements` (`models/stock.py:213-236`) ve `device_status_history` var, ancak kiralık cihaz kaydı yok.
  - `audit_logs` genel iz tutuyor, ama cihaz bazlı sorgulanabilir geçmiş vermiyor (mimari §5 Denetim izi satırı).
- **Yaklaşım:**
  - `rental_assets` ve `rental_inventory_movements` tabloları açılır.
  - Tüm envanter değişiklikleri tek bir yazıcıdan geçer: `kiralik_envanter.hareket_yaz(...)`. Bu fonksiyon seri takipli cihazda denormalize durumu ve depoyu da günceller.
  - Depo değişimi yalnız transfer ile yapılır: `POST /api/kiralama/envanter/transfer`. Girdi ya seri listesi ya da ürün + adet + kaynak/hedef depodur; `kind=TRANSFER` yazılır. Envanter PATCH ucu `warehouse_id` kabul etmez.
  - Hareketler için PUT/PATCH/DELETE ucu yoktur. ORM tarafında `before_update/before_delete` olay dinleyicisi `KiralamaHatasi` fırlatır (savunma derinliği).
  - Kiralama başlığındaki durum, tarih ve sorumlu değişiklikleri `rental_events` tablosuna yazılır (`tur=DURUM/TARIH/SORUMLU`); ayrıca `audit.log_change` çağrılır.
  - Uçlar:
    - `GET /api/kiralama/envanter/{asset_id}/hareketler`
    - `GET /api/kiralama/envanter/hareketler?product_id&depo_id` (toplu)
  - Worker görevi `kiralama-uzlastirma` (24 saat):
    - seri takipli cihazın denormalize durumu = son hareketin `to_durum` mu,
    - toplu bakiye ≥ 0 mı,
    - kirada adet = tahsis toplamı mı.
    - Fark otomatik düzeltilmez; worker özet metnine ve log'a yazılır.
- **Dosyalar:** `models/servis_kiralama.py`, `services/teknik_servis/kiralik_envanter.py`, `api/kiralamalar.py`, `worker.py`, `tests/integration/test_kiralik_envanter.py`.
- **Kabul:**
  - Bir cihazın girişinden iki kiralama ve bir transfere kadar tüm hareketler `at`, `id` sırasıyla listelenir.
  - Hareket üzerinde PUT, PATCH ya da DELETE ucu bulunmaz (405/404). Olay dinleyicisi testte güncellemeyi reddeder.
  - Transfer ayrı bir hareket yazar ve toplu bakiyeyi iki depoda doğru değiştirir.
  - Başlık tarihi değişikliği `rental_events` tablosunda eski ve yeni değerle görünür.
- **Öncelik / Efor:** P1 / M.
- **Bağımlılık:** E06-02.
- **Canlı risk:** Yok. Yeni tablolar; `stock_movements` tablosuna dokunulmaz.

### E06-04 · M06-13 · Ayrı tahsis tablosuyla adet bazlı kısmi tahsis
- **Canlı:** YOK.
- **Yaklaşım:**
  - `rental_allocations` tablosu açılır.
  - Servis fonksiyonu `tahsis_et(db, clock, rental, kalem, asset_idler | (depo_id, adet), user)`:
    - Kiralama durumu `PLANLANDI/HAZIRLANIYOR` ya da sevk sonrası (`SEVK_EDILDI..TOPLANDI`, yalnız ek veya değişim tahsisi) olmalı; aksi halde 409. `IPTAL/KAPANDI` her zaman reddedilir.
    - Kalem toplamı: AKTIF tahsis `qty` toplamı + istenen ≤ `kalem.qty`; aşarsa 409.
    - **Seri takipli:** `SELECT ... FOR UPDATE` ile cihaz satırı kilitlenir; cihaz `HAZIR` olmalı. `ex_rtahsis_cihaz_cakisma` tarih çakışan ikinci tahsisi DB'de reddeder (`ex_` → 409).
    - **Toplu:** `rental_catalog_items` satırı `with_for_update()` ile kilitlenir; bu, ürün başına eşzamanlı tahsisleri sıraya sokar. Ardından şu koşul aranır: `bakiye(ürün, depo, HAZIR) − Σ(qty − sevk_adet)[AKTIF, aynı depo, tarih çakışan] ≥ istenen`; sağlanmazsa 409 ve eksik adet mesajı.
    - `kind=TAHSIS` hareketi yazılır. Durum değişmez: tahsis cihazı bağlar, depodan çıkarmaz.
  - İlk geçişte (kiralama `PLANLANDI` iken) kiralama `HAZIRLANIYOR` durumuna geçer.
  - Uçlar: `POST /api/kiralama/{id}/tahsis`, `POST /api/kiralama/{id}/tahsis/{tid}/coz` (yalnız `sevk_adet=0`; `kind=TAHSIS_COZ` yazar).
- **Dosyalar:** `services/teknik_servis/kiralama_tahsis.py`, `api/kiralamalar.py`, migration, `tests/integration/test_kiralama_tahsis.py`.
- **Kabul:**
  - 50 adetlik bariyerden 20 ve 30 adet iki ayrı kiralamaya tahsis edilir; 51. adet 409 döner.
  - Seri takipli tahsiste `qty=2` istenirse `ck_rtahsis_seri_adet` ihlal edilir.
  - İki eşzamanlı istemci (`asyncio.gather`) aynı 50'lik stoktan 30+30 ister: biri 201, diğeri 409 alır; toplam stok aşılmaz.
  - Sevk edilmiş kaleme ek tahsis yapılabilir.
- **Öncelik / Efor:** P1 / M.
- **Bağımlılık:** E06-03.
- **Canlı risk:** Yok. EXCLUDE yeni tabloda; autogenerate `ExcludeConstraint` biçimiyle yazılır; downgrade'de düşürülür.

### E06-05 · M06-11 · Durum makinesi; durum yalnız aşama uçlarıyla ilerler
- **Canlı:** YOK. `statemachine.py:189-196` içinde kiralama makinesi yok. Altyapı (`StateMachine`, meta-test) VAR.
- **Yaklaşım:**
  - `KIRALAMA` makinesi (§2.5) `MAKINELER["kiralama"]` altına eklenir. Başlık PUT ucu `status` alanını kabul etmez.
  - Geçiş uçları; her biri `KIRALAMA.dogrula` çağırır, servis içinde de doğrulama yapılır ve yanıt `sonraki_durumlar` döner:
    - `POST /{id}/planla`: rezerv kontrolü (E06-12).
    - `POST /{id}/sevk` (E06-06/07).
    - `POST /{id}/asama` gövdesi `{asama: KURULUM_YAPILDI|DEVREYE_ALINDI|TOPLANDI, at, service_order_id?, not}`.
    - `POST /{id}/iade` (E06-07); tüm tahsisler sevk edilmiş adet kadar sonuç aldığında kiralama `DEPOYA_ALINDI` olur.
    - `POST /{id}/iptal` (E06-14).
    - `POST /{id}/kapat`.
  - Aynı aşamanın ikinci kez girilmesi makinede yasak bir geçiştir → 409.
  - Aşama zamanı: `at ≤ clock.now()+1 gün` ve `at ≥ baslangic − 10 yıl` kuralı korunur.
  - Kapanış şartı: hiçbir AKTIF tahsiste `sevk_adet − iade_adet − kayip_adet > 0` kalmamalı (cihaz müşteride olamaz) ve sevk edilmemiş AKTIF tahsis kalmamalı.
  - Eski `Teklif` durumu göç profilinde `TALEP` ile eşlenir (E06-09).
- **Dosyalar:** `services/statemachine.py`, `services/teknik_servis/kiralama.py`, `api/kiralamalar.py`, `tests/unit/test_statemachine.py` (otomatik), `tests/integration/test_kiralama_akis.py`.
- **Kabul:**
  - Sevksiz depoya alma 409 döner (yasak geçiş).
  - Tekrar aynı aşama 409 döner.
  - `IPTAL/KAPANDI` kiralamada tahsis ya da sevk 409 döner.
  - Cihazı müşteride olan kiralama kapatılamaz (409).
  - Telsiz kiralaması `SEVK_EDILDI→DEPOYA_ALINDI` yolunu kurulum olmadan geçer.
  - Eski `Teklif` durumu göçte `TALEP` olur.
- **Öncelik / Efor:** P1 / M.
- **Bağımlılık:** E06-02, E06-04, E06-10.
- **Canlı risk:** Yok. Yeni makine meta-testi geçmeli; mevcut makineler değişmez.

> Not: Kabul kriterinde "sevksiz depoya alma **400**" yazıyor. Canlı kuralı (`main.py:131-161`) yasak durum geçişini 409'a eşliyor; burada 409 kullanılır. Gerekçe Karar K4'te.

### E06-06 · M06-12 · Sevk şartı: tahsis toplamı = kalem adedi (tüm ürünler)
- **Canlı:** YOK.
- **Yaklaşım:**
  - `sevk_et(...)` iki modda çalışır:
    - **(a) Tam sevk:** HAZIRLANIYOR→SEVK_EDILDI geçişinde her kalem için `Σ AKTIF qty == kalem.qty` aranır; eksikse 400 ve "PG-5030: 1 adet eksik tahsis" listesi döner.
    - **(b) Kısmi/ek sevk** (E06-07): durum zaten SEVK_EDILDI veya sonrasıysa yalnız seçilen tahsisler sevk edilir.
  - `RentalItemIn` şemasında seri alanı yok. Seri listesi yalnız tahsislerden türetilen salt-okunur `seriler` çıktısıdır. Gövdede gelen fazla alan (`extra="ignore"`) yok sayılır.
  - Sevk, seri takipli cihazı `HAZIR→KIRADA` yapar (`HAZIR` değilse 409). Toplu stokta `(depo, HAZIR)→(NULL, KIRADA)` hareketi yazılır.
- **Dosyalar:** `services/teknik_servis/kiralama_tahsis.py`, `api/kiralamalar.py`, `tests/integration/test_kiralama_akis.py`.
- **Kabul:**
  - 3 adetlik seri takipli kalemde 2 tahsis varken tam sevk 400 döner.
  - İkinci kalemi toplu olan kiralamada da kural çalışır.
  - Gövdeye eklenen `seri_listesi` yok sayılır.
- **Öncelik / Efor:** P1 / S.
- **Bağımlılık:** E06-04, E06-05.
- **Canlı risk:** Yok.

### E06-07 · M06-04 · Cihaz bazlı kısmi sevk ve iade; iade sonucu Depo / Müşteride / Kayıp
- **Canlı:** YOK.
- **Yaklaşım:**
  - `POST /{id}/sevk {satirlar:[{tahsis_id, adet}], at}`: seçilen tahsislerin `sevk_adet` değeri artar.
  - `POST /{id}/iade {at, satirlar:[{tahsis_id, sonuc: IADE_ALINDI|MUSTERIDE|KAYIP, adet, depo_id?, not}]}`:
    - `IADE_ALINDI` → `iade_adet += adet`, hareket `(NULL,KIRADA)→(depo,KONTROLDE)`. Depo zorunlu; birden çok depoya bölünebilir.
    - `KAYIP` → `kayip_adet += adet`, hareket `(NULL,KIRADA)→(NULL,KAYIP)`.
    - `MUSTERIDE` → yalnız olay notu yazılır; sayaç değişmez.
  - Sevk edilmemiş tahsis bu uçta reddedilir (400). Denetimin "sevk edilmemiş cihazlar da Kontrolde yapılıyor" bulgusu böylece kapanır.
  - Hasar ve eksik tespiti iade anında yapılmaz, kontrolde yapılır (E06-11).
  - `iade_gosterimi`: hiç iade yok → `YOK`, bir kısmı iade → `KISMI`, tamamı → `TAM`.
  - KAYIP cihazın yeniden envantere alınması: `POST /api/kiralama/envanter/{asset_id}/bulundu {gerekce, depo_id}`. KAYIP→KONTROLDE geçişinde gerekçe zorunludur (400); `kind=BULUNDU` yazılır.
- **Dosyalar:** `services/teknik_servis/kiralama_tahsis.py`, `services/teknik_servis/kiralik_envanter.py`, `api/kiralamalar.py`, testler.
- **Kabul:**
  - 5 cihazdan 3'ü Depo 1'e, 1'i Depo 2'ye iade edilir, 1'i KAYIP işaretlenir. Sonuçta envanterde 4 KONTROLDE (3+1) ve 1 KAYIP, 5 IADE/KAYIP hareketi bulunur.
  - Sevk edilmemiş tahsis iadeden etkilenmez.
  - Tüm cihazlar sonuç almadan `kapat` 409 döner.
  - Ekranda kısmi iade "Kısmi iade" etiketi olarak görünür; ayrı bir durum değildir.
- **Öncelik / Efor:** P1 / M.
- **Bağımlılık:** E06-04, E06-03.
- **Canlı risk:** Yok.

### E06-08 · M06-D01 · Son aşamayı gerekçeyle geri alma (ters hareket)
- **Canlı:** YOK. Canlıda emsal yok; RMA'da geri dönüş makine kenarıyla yapılıyor.
- **Yaklaşım:**
  - `POST /{id}/geri-al {gerekce}` (`kiralama.asama`). Boş gerekçe → 400.
  - Servis yalnız **son** `rental_events` aşama olayını hedefler; hedef olay zaten geri alınmışsa 409.
  - O olayın yazdığı hareketlerin her biri için `reverses_id` ile ters hareket yazılır: `from` ve `to` yer değiştirir. `uq_rhareket_ters` aynı hareketin iki kez geri alınmasını engeller.
  - Tahsis sayaçları (`sevk_adet/iade_adet/kayip_adet`) geri sarılır. Durum `onceki_durum` değerine döner; dönüşten önce `KIRALAMA.dogrula(onceki, mevcut)` ile bu geçişin gerçekten var olduğu doğrulanır.
  - Olay `tur=DUZELTME` ve `geri_alinan_event_id` ile yazılır; ayrıca `audit.log(..., "kiralama.asama.geri_al")` çağrılır.
  - Geri alınacak hareketin cihazı o arada başka bir harekete konu olduysa (ör. kontrol edildiyse) 409 döner: "Önce sonraki işlemi geri alın".
- **Dosyalar:** `services/teknik_servis/kiralama.py`, `api/kiralamalar.py`, testler.
- **Kabul:**
  - Yanlış DEPOYA_ALINDI geri alınınca cihazlar önceki depo, durum ve tahsis durumuna döner.
  - Geçmişte DUZELTME olayı ve ters hareketler görünür; hiçbir kayıt silinmez.
  - Son aşama dışındaki bir olay hedeflenirse 409 döner.
- **Öncelik / Efor:** P2 / S.
- **Bağımlılık:** E06-03, E06-05.
- **Canlı risk:** Yok.

### E06-09 · M06-D03 · Geçiş öncesi pilot veri uzlaştırma raporu (salt okunur)
- **Canlı:** KISMEN.
  - İçe aktarma altyapısı VAR: önizleme, karantina, `partiler/{id}/uygula` (`api/imports.py:118-249`), `PROFIL_IZINLERI` (`api/imports.py:65-69`), `SourceMixin`.
  - Kiralama profili YOK.
- **Yaklaşım:**
  - `services/imports/kiralama_goc.py` içinde dört profil tanımlanır: `KiralikEnvanterGocProfili`, `KiralamaGocProfili`, `KiralamaKalemGocProfili`, `KiralamaTahsisGocProfili`. Yükleme sırası envanter → kiralama → kalem → tahsis. `PROFIL_IZINLERI` değeri `sistem.goc`.
  - Profilin `dogrula` adımı dört uyumsuzluğu satır hatası olarak değil **uyarı (çakışma)** olarak işaretler:
    1. tahsissiz `Kirada` cihaz,
    2. KAPANDI/İPTAL kiralamaya bağlı cihaz,
    3. envanterle eşleşmeyen elle yazılmış seri,
    4. durum ile aşama geçmişi arasında uyumsuzluk.
  - Parti `uygula` adımında uyumsuz satır sayısı sıfırdan büyükse gövdede `uyumsuzluk_onayi=true` istenir; yoksa 409. Bu yalnız kiralama profillerinde uygulanan bir koşul kontrolüdür.
  - Ayrıca `GET /api/kiralama/goc/uzlastirma` (`sistem.goc`) seçili partiler için dört türün sayısını ve satır listesini, xlsx sürümüyle birlikte verir.
  - Göçte eski `Teklif` durumu `TALEP` olur. Uydurma tarih yazılmaz: aşama zamanı yoksa olay yazılmaz, durum hesaplanır.
- **Dosyalar:** `services/imports/kiralama_goc.py`, `services/imports/__init__.py` (`PROFILLER`), `api/imports.py` (onay koşulu), `api/kiralamalar.py`, `tests/integration/test_kiralama_goc.py`.
- **Kabul:**
  - Dört türün her birinden bir satır içeren test dosyası raporda 4 sayı ve 4 satır listesi üretir.
  - Onay verilmeden uygula 409 döner; onayla aktarılır.
  - Rapor hiçbir şey yazmaz; parti durumu HAZIR kalır.
- **Öncelik / Efor:** P1 / S.
- **Bağımlılık:** E06-03, E06-04, E06-05.
- **Canlı risk:** `api/imports.py` dosyasında yalnız kiralama profillerine özgü bir dal eklenir; diğer profiller etkilenmez. Bu, regresyon testiyle doğrulanır.

### E06-10 · M06-D04 · Uçtan uca kiralama akış testleri
- **Canlı:** KISMEN. Test altyapısı VAR: PG17 `_test`, `client` + FakeClock, `kullanici_ac`, `urun_ac`. Kiralama senaryosu YOK.
- **Yaklaşım:**
  - `tests/integration/test_kiralama_akis.py` şu senaryoları kapsar:
    1. talep → planla → tahsis → sevk → kısmi iade → kontrol → kapanış
    2. iptal
    3. eşzamanlı tahsis
    4. birim kapsamı: iki birimden iki kullanıcı; liste boş, GET 404, PATCH 404 ve kayıt değişmemiş (`db.refresh`), ek listesi 404, uyarı sayısı yalnız kendi birimi
    5. geri alma
  - Her senaryo envanter durumunu ve hareket sayısını doğrular.
  - Yardımcı fixture'lar: `kiralik_urun_ac` (katalog profili ile), `kiralama_ac`.
  - Yeni tabloların hepsi FK ile `accounts/products/users` tablolarına bağlı; TRUNCATE CASCADE onları da temizler. Yine de `rental_inventory_movements` ve `rental_events` açıkça `_TRUNCATE` listesine eklenir.
  - `tests/migration/test_migration_zinciri.py` head→base→head testi ve EXCLUDE sayısı yeni `ex_rtahsis_cihaz_cakisma` ile güncellenir.
  - Altın kayıt testi yeşil kalır.
- **Dosyalar:** `tests/integration/test_kiralama_*.py`, `tests/conftest.py`, `tests/migration/test_migration_zinciri.py`.
- **Kabul:** `make test` yeşil. Senaryolar beklenen envanter durumu ve hareket sayısıyla doğrulanır.
- **Öncelik / Efor:** P1 / M.
- **Bağımlılık:** Diğer maddelerle birlikte artımlı yazılır (her madde kendi testini getirir).
- **Canlı risk:** EXCLUDE sayısı beklentisi testte güncellenmeli; güncellenmezse zincir testi kırılır.

### E06-11 · M06-03 · Dönüş kontrol kaydı (KONTROLDE ve HAZIR_DEGIL için)
- **Canlı:** YOK. Atölye bağlantısı M05 tasarımında.
- **Yaklaşım:**
  - `rental_checks` tablosu açılır.
  - `POST /api/kiralama/envanter/kontrol {satirlar:[{asset_id | (product_id, depo_id, adet), sonuc, aciklama, rental_id?, atolye_kaydi_ac?}]}` (`kiralama.envanter`). Toplu "seçilenleri uygun işaretle" de bu uçla yapılır.
  - Kabul edilen başlangıç durumu yalnız `KONTROLDE` ya da `HAZIR_DEGIL`; diğerleri 400.
  - Sonuçlar:
    - `UYGUN` → `HAZIR`.
    - `EKSIK` ya da `ARIZALI` → `HAZIR_DEGIL`; açıklama zorunlu (CHECK + 400).
  - `atolye_kaydi_ac=true` ve sonuç `ARIZALI` ise `workshop_records` kaydı (`rental_asset_id`) açılır, cihaz `ATOLYEDE` olur (`kind=ATOLYE`). Bu isteğe bağlı ikinci adımdır; M05 hazır değilse alan gizlenir.
  - Kontrol eden kişi `created_by`, zaman `at` (Clock) alanına yazılır. Kontrol listesi serbest nottur.
  - Yeni envanter girişi `HAZIR` olarak yapılabilir (`kind=GIRIS`). `HAZIR` başka hiçbir yazma ucundan verilemez.
  - Kontrol listesi ekranı `kontrolde_gun` değerini gösterir: son `to_durum=KONTROLDE` hareketinden bugüne gün sayısı.
- **Dosyalar:** `services/teknik_servis/kiralik_envanter.py`, `api/kiralamalar.py`, `pages/KiralikEnvanterPage.tsx`, testler.
- **Kabul:**
  - KIRADA cihaz kontrol edilemez (400).
  - EKSIK sonucu açıklamasız gelirse 400 döner.
  - HAZIR_DEGIL cihaz yeniden kontrolde UYGUN olunca HAZIR olur.
  - Kontrol eden kişi ve zaman kayıtta görünür.
- **Öncelik / Efor:** P2 / M.
- **Bağımlılık:** E06-03, E06-01. Atölye adımı M05'e bağlı.
- **Canlı risk:** Yok.

### E06-12 · M06-01 · Tarih bazlı müsaitlik ve ürün/adet düzeyinde rezervasyon
- **Canlı:** YOK.
- **Yaklaşım:**
  - `kiralama_tahsis.musaitlik(db, clock, product_id, baslangic, bitis, haric_rental_id=None)` şu alanları döner: `toplam`, `rezerve`, `musait`, `kontrolde`, `hazir_degil`, `kayip`.
  - `toplam` = HAZIR + KONTROLDE + KIRADA (seri takipli için cihaz sayısı, toplu için bakiye).
  - `rezerve` = tarih aralığı çakışan (`daterange '[)'`) ve durumu `PLANLANDI..TOPLANDI` olan kiralamaların kalem adetleri.
    - Bitişi geçmiş olup cihazı hâlâ müşteride olan kiralamalar, geciken adet kadar rezerve sayılır.
  - `musait` = HAZIR + KIRADA(dönecek) − rezerve.
  - KAYIP ve HAZIR_DEGIL düşülür. KONTROLDE müsaite dahil edilir ama ayrı alanda gösterilir.
  - Uç: `GET /api/kiralama/musaitlik?product_id&baslangic&bitis` (`kiralama.gor`).
  - `planla` ve bitiş tarihi uzatma (PUT'ta `bitis` artarsa) aynı fonksiyonu `rental_catalog_items FOR UPDATE` kilidi altında çağırır. Eksik varsa 409 ve "X adet eksik" mesajı döner.
  - Uzatmada AKTIF tahsislerin `bitis` alanı da güncellenir. Seri takipli çakışmayı `ex_rtahsis_cihaz_cakisma` ayrıca yakalar.
  - İptal edilen kiralama rezervi anında düşürür: durum filtresi dışına çıkar.
- **Dosyalar:** `services/teknik_servis/kiralama_tahsis.py`, `api/kiralamalar.py`, testler.
- **Kabul:**
  - 10 adet PG-5030 varken 1-5 Kasım için 8 adet rezerveyse 3 adetlik kiralama `planla` adımında 409 alır; 10-12 Kasım için geçer.
  - Uzatma çakışma yaratırsa 409 döner.
  - KONTROLDE ayrı sütunda görünür.
  - İptal sonrası müsaitlik hemen artar.
- **Öncelik / Efor:** P2 / M.
- **Bağımlılık:** E06-05, E06-04.
- **Canlı risk:** Yok.

### E06-13 · M06-06 · Teslim ve iade tutanağı (yazdırılabilir, fiyatsız PDF)
- **Canlı:** KISMEN. PDF altyapısı VAR: `services/pdf.py`, `belgeler.firma_bilgisi`, teklif ve hak ediş şablonları. Kiralama şablonu YOK.
- **Yaklaşım:**
  - `belgeler.kiralama_tutanak_baglami(db, rental, tur)` bağlam fonksiyonu yazılır. İçeriği:
    - firma künyesi,
    - müşteri, lokasyon ve irtibat,
    - kalemler,
    - **yalnız tahsisli** seriler ya da adetler,
    - iade tutanağında iade sonucu ve notlar,
    - teslim eden ve teslim alan imza alanları.
  - Sevk yapılmadan alınan teslim tutanağına "TASLAK" filigranı basılır.
  - Fiyat/maliyet bağlamda yer almaz; şablonda fiyat alanı yoktur.
  - Uç: `GET /api/kiralama/{id}/tutanak.pdf?tur=TESLIM|IADE` (`kiralama.gor` + kapsam).
  - İmzalı tarama `EkYukleyici kind="TESLIM_TUTANAGI"` ile eklenir.
  - Şablon, kullanıcının basılı formu gelince yalnız HTML düzeyinde güncellenir.
- **Dosyalar:** `services/belgeler.py`, `templates/kiralama_tutanak.html`, `api/kiralamalar.py`, `models/attachment.py`, testler (PDF baytı + bağlamda fiyat anahtarı yok).
- **Kabul:**
  - Tutanak yalnız tahsisli serileri listeler.
  - Sevk öncesi alınan tutanakta TASLAK filigranı bulunur.
  - Bağlam sözlüğünde `fiyat`, `tutar` ve `maliyet` anahtarları yoktur (test).
- **Öncelik / Efor:** P2 / S.
- **Bağımlılık:** E06-04.
- **Canlı risk:** Yok. `belgeler.py` yalnız yeni fonksiyon alır.

### E06-14 · M06-14 · İptalde tahsislerin otomatik çözülmesi; gerekçe zorunlu
- **Canlı:** YOK.
- **Yaklaşım:**
  - `POST /{id}/iptal {gerekce}` (`kiralama.yaz`). Gerekçe boşsa 400 (`ck_rental_iptal_gerekce` ayrıca korur).
  - Herhangi bir tahsiste `sevk_adet > 0` varsa 409: "Önce iade alın".
  - Aksi halde tüm AKTIF tahsisler `COZULDU` durumuna geçer, her biri için `kind=TAHSIS_COZ` hareketi yazılır, ardından `KIRALAMA.dogrula(…, "IPTAL")` çağrılır.
  - `rental_events` tablosuna `IPTAL` olayı, denetime `kiralama.iptal` yazılır.
- **Dosyalar:** `services/teknik_servis/kiralama.py`, `api/kiralamalar.py`, testler.
- **Kabul:**
  - Tahsisli, sevk edilmemiş kiralama iptal edilince cihazlar başka kiralamaya tahsis edilebilir.
  - Sevk edilmiş kiralamada iptal 409 döner.
  - Gerekçe boşsa 400 döner.
- **Öncelik / Efor:** P2 / S.
- **Bağımlılık:** E06-05.
- **Canlı risk:** Yok.

### E06-15 · M06-15 · Başlık, kalem ve irtibat tek uçta tek işlemle kaydedilir; iyimser kilit
- **Canlı:** KISMEN. Kalıplar VAR: `VersionedMixin` → `StaleDataError` → 409 (`main.py:115-129`), PATCH'te `version` (`api/accounts.py:434-440`), ön yüzde 409 mesajı (`pages/HesaplarPage.tsx:164`).
- **Yaklaşım:**
  - `PUT /api/kiralama/{id}` gövdesi `{version, baslik…, kalemler:[{id?, product_id, qty, note}], irtibatlar:[{id?, contact_id, rol}]}`; tek transaction'da işlenir.
  - Kalem işlemleri:
    - kalem kimliğiyle güncelleme yapılır,
    - kimliği gelmeyen yeni kalem eklenir,
    - listede olmayan kalem silinir.
  - Tahsisli kalemde iki kısıt vardır: kalemin ürünü değiştirilemez, adedi AKTIF tahsis toplamının altına indirilemez; silinemez (409).
  - İrtibatlar kimlikle güncellenir; silip yeniden yazma yapılmaz. `IsPrimary` eklenmez (denetim kararı).
  - Herhangi bir parça hata verirse tüm transaction geri alınır, çünkü commit tektir.
  - Durum alanı bu uçta kabul edilmez.
  - Başlık ile kalemler arasındaki "eski tekil kopya alanlar" modelde hiç yoktur.
  - Müşteri doğrulaması: `customer_id` zorunludur ve `is_musteri` hesap olmalıdır (400).
- **Dosyalar:** `api/kiralamalar.py`, `services/teknik_servis/kiralama.py`, `pages/KiralamalarPage.tsx` (KartPenceresi kalıbı, tek form), testler.
- **Kabul:**
  - Eski `version` ile kayıt 409 döner.
  - Üçüncü kalemde geçersiz ürün varsa başlık değişikliği de geri alınır.
  - Müşterisiz istek 400 (422 değil) döner. Bu, `RequestValidationError` yerine servis doğrulamasıyla sağlanır; Karar K12.
  - İrtibat düzenlemesi kimliği korur.
- **Öncelik / Efor:** P2 / S.
- **Bağımlılık:** E06-02.
- **Canlı risk:** Yok.

### E06-16 · M06-10 · Kiralama kataloğu yönetimi; seed kullanıcı değişikliklerini ezmez
- **Canlı:** KISMEN.
  - Ürün CRUD VAR: `POST/PATCH /api/urunler`, `urun.yaz` (`api/catalog.py:139-185`), iyimser kilit, `is_active`.
  - Kiralama profili (birim, kategori, sıra) YOK.
  - Gözlem: `UrunPatch` `identity_kind` alanını kabul ediyor (`schemas/catalog.py`) ve değişiklik için koruma yok. `devices` FK'si ise `onupdate="CASCADE"` (`models/device.py`).
- **Yaklaşım:**
  - `rental_catalog_items` tablosu açılır.
  - Uçlar (`kiralama.envanter`):
    - `GET /api/kiralama/katalog?birim&aktif`
    - `POST /api/kiralama/katalog {product_id, birim, kategori, sira}`
    - `PATCH /api/kiralama/katalog/{id}`
  - Kayıt silinmez; yalnız `is_active=false` olur. Ürün kartı canlı katalogda (`/urunler`) açılır; burada yeni ürün tablosu yoktur.
  - Birim değişikliği yalnız ürünün envanteri ya da kalemi yoksa yapılabilir (409).
  - Seri takibi değişikliğine karşı koruma DB seviyesindedir: `fk_rasset_urun_kimlik ... ON UPDATE RESTRICT`. Kiralık cihazı olan ürünün `identity_kind` değeri değiştirilemez. Toplu bakiye varken YOK → SERI_NO geçişi için `api/catalog.guncelle` içine ek koruma eklenir: hareket kaydı varsa 409. Bu canlı katalog ucuna eklenen tek satırlık bir korumadır.
  - Seed `seeds/kiralama.py` başlangıç kataloğunu (eski 23 ürün) `INSERT ... ON CONFLICT (code) DO NOTHING` ile yazar. Var olan ürünün adı, aktifliği ve seri takibi güncellenmez.
- **Dosyalar:** `models/servis_kiralama.py`, `api/kiralamalar.py`, `api/catalog.py` (koruma), `seeds/kiralama.py`, testler.
- **Kabul:**
  - Ürün kiralama kataloğuna eklenip pasifleştirilebilir.
  - Envanteri olan ürünün birimi değiştirilemez (409).
  - Toplu bakiyesi olan ürün seri takipliye çevrilemez (409).
  - Seed ikinci kez çalışınca pasif ürün pasif kalır.
- **Öncelik / Efor:** P2 / S.
- **Bağımlılık:** E06-02.
- **Canlı risk:** `api/catalog.py` korumasına dikkat: yalnız `rental_inventory_movements` kaydı olan ürünlerde devreye girer. Mobilite ürünleri etkilenmez; bunu mevcut katalog testleri doğrular.

### E06-17 · M06-09 · Kiralama uyarıları (kademeli)
- **Canlı:** KISMEN. `services/uyarilar.py:47-190` deseni VAR: hesaplanan, izne tabi `Uyari(kod, baslik, adet, yol, onem)`. Kiralama bloğu YOK.
- **Yaklaşım:**
  - `if user.has("kiralama.gor"):` bloğu eklenir. Sorgular `kiralama_raporlar.py` içinde yazılır ve hepsi `kapsam_musteri` + `kapsam_birim` ile süzülür (sayı da bir sızıntı kaynağıdır).
  - Uyarı tanımları:

    | Kod | Koşul | Önem | Yol |
    |---|---|---|---|
    | `kiralama.geciken_iade` | Bitişi geçmiş, cihazı müşteride | kritik | `/kiralamalar?kpi=geciken` |
    | `kiralama.eksik_tahsis` | `kiralama_eksik_tahsis_gun` (3) gün içinde başlayacak ve tahsisi eksik | — | — |
    | `kiralama.uzun_kontrol` | `kiralama_kontrol_bekleme_gun` (5) günden uzun KONTROLDE | — | `/kiralik-envanter?durum=KONTROLDE&uzun=1` |
    | `kiralama.musaitlik_acigi` | PLANLANDI kiralamada müsaitlik negatif; E06-12 gelince açılır | — | — |

  - Eşikler `settings.DEFAULTS` içinden okunur.
  - Uyarı tekil anahtarı (`tur:id:gun`): canlı uyarılar saklanmıyor. Anahtar, satır listesi uçlarında (`/kiralamalar?kpi=...`) ve worker özetinde (`is_uyarilari`'na kiralama sayıları) `f"{kod}:{rental_id}:{gun}"` biçiminde döner. Karar K10.
- **Dosyalar:** `services/uyarilar.py`, `services/settings.py`, `services/teknik_servis/kiralama_raporlar.py`, `worker.py`, `tests/integration/test_kiralama_uyarilar.py`.
- **Kabul:**
  - Her uyarı türü test verisiyle üretilir ve kiralamaya bağlantı verir.
  - Başka birimin kaydı sayıya girmez.
  - Eşik ayarı değişince sonuç değişir.
- **Öncelik / Efor:** P2 / S.
- **Bağımlılık:** E06-04 (b), E06-12 (d).
- **Canlı risk:** `topla()` tüm kullanıcılar için çalışır. Yeni blok `kiralama.gor` iznine bağlı olduğu için mevcut kullanıcılar etkilenmez; YONETIM rolü `.gor` iznini otomatik aldığından kiralama uyarılarını görür, bu beklenen davranıştır.

### E06-18 · M06-17 · Envanter düzenlemede birim ve durum kontrolleri; depo değişimi transferle
- **Canlı:** YOK.
- **Yaklaşım:**
  - `PATCH /api/kiralama/envanter/{asset_id}` (`kiralama.envanter`, `version`) şu alanları kabul eder: `serial_no`, `eksik_notu`, `notes`.
  - Kabul edilmeyen alanlar şemada yoktur: `durum`, `warehouse_id`, `product_id`, `birim`. Bu alanlar gönderilirse 400 döner (`extra="forbid"`).
  - Kayıt `birim_disinda_mi` ise 404 döner ve kayıt değişmez.
  - Seri değişikliği yalnız cihazın AKTIF tahsisi yokken ve durumu KIRADA değilken yapılabilir (409). Değişiklik `kind=DUZENLEME` hareketi ve `audit.log_change` ile yazılır.
  - Yeni giriş ucu `POST /api/kiralama/envanter` şu durumları kabul eder: `HAZIR`, `KONTROLDE`, `HAZIR_DEGIL`. `KIRADA` ya da `KAYIP` gelirse 400.
- **Dosyalar:** `api/kiralamalar.py`, `services/teknik_servis/kiralik_envanter.py`, testler.
- **Kabul:**
  - Haberleşme birimindeki kullanıcı Güvenlik cihazını düzenlemeye çalışırsa 404 alır ve kayıt değişmez. Kaynak 403 bekliyordu; canlı kapsam kuralı 404'tür (Karar K4).
  - Düzenlemede `durum=KIRADA` gönderilirse 400 döner.
  - Tahsisli cihazın seri düzenlemesi 409 döner (yeni tahsis tablosunda test).
- **Öncelik / Efor:** P2 / S.
- **Bağımlılık:** E06-03, E06-04, E06-11.
- **Canlı risk:** Yok.

### E06-19 · M06-02 · Kurulum ve toplama işlerinin servis iş emrine bağlanması
- **Canlı:** YOK. `service_orders`, planlama ve zaman kaydı teknik servis çekirdek adımlarında geliyor. Mobilite `work_orders` tablosu **kullanılmaz**.
- **Yaklaşım:**
  - Kiralama detayında iki düğme bulunur: "Kurulum işi oluştur" ve "Toplama işi oluştur". Her biri `POST /api/kiralama/{id}/servis-isi {tur: KURULUM|TOPLAMA}` (`kiralama.yaz` + `servis.yaz`) çağırır ve servis iş emri servisinin `olustur()` fonksiyonuyla iş emri açar. Taşınan alanlar:
    - `birim`, `customer_id`, `address_id`,
    - `rental_id`,
    - açıklamada kiralama no ve seri listesi.
  - Aynı türde ikinci açık iş `uq_so_kiralama_tur_acik` ile engellenir (`uq_` → 409).
  - Aşama kaydında (`POST /{id}/asama`) bağlı `service_order_id` seçilir. Ekip bilgisi o işin `service_plan_members` atamalarından `ekip_user_ids` alanına yazılır; serbest metin ekip yoktur.
  - Süre yalnız `service_time_entries` kayıtlarından hesaplanır; MOLA dahil edilmez. Kayıt yoksa "eksik" yazılır. Tahmin yoktur, 0 yazılmaz.
  - Servis işi TAMAMLANDI olunca kiralama detayında "Önerilen aşama: Kurulum yapıldı" bandı görünür. Aşama otomatik yazılmaz; onayı `kiralama.asama` sahibi verir.
  - Servis iş emri listesinde "Kiralama" filtresi (`rental_id IS NOT NULL`) bulunur.
- **Dosyalar:** `api/kiralamalar.py`, `services/teknik_servis/kiralama.py`, servis çekirdeğinin migration'ına `rental_id` (ayrı migration `servis_kiralama_bagi`), `pages/KiralamalarPage.tsx`, testler.
- **Kabul:**
  - Açılan servis işinde kiralama no ve seri listesi görünür.
  - İkinci açık KURULUM işi 409 döner.
  - Aşama olayında ekip, iş emrinin atanmış personelidir.
  - Zaman kaydı olmayan işin aşama süresi raporda "eksik" yazar.
- **Öncelik / Efor:** P2 / L.
- **Bağımlılık:** Servis iş emri çekirdeği, planlama, zaman kaydı (teknik servis adım 2-3), E06-05.
- **Canlı risk:** `work_orders` ve hak edişe hiçbir yazım yapılmaz. `service_orders.rental_id` nullable olduğu için servis çekirdeğini bozmaz.

### E06-20 · M06-05 · Sahada cihaz değişimi tek birleşik ekranda
- **Canlı:** YOK.
- **Yaklaşım:**
  - `POST /{id}/degisim {eski_tahsis_id, yeni_asset_id | (depo_id, adet), iade_depo_id, not, ariza_isi_ac?}` (`kiralama.asama`) tek transaction'da üç adımı çağırır:
    1. eski cihazın iadesi (E06-07, `IADE_ALINDI` → KONTROLDE),
    2. yeni tahsis (E06-04),
    3. yeni tahsisin kısmi sevki (E06-07).
  - Yeni tahsisin `replaced_allocation_id` alanı eski tahsisi gösterir. Her iki cihaza `kind=DEGISIM` notlu hareket yazılır.
  - Ayrı bir veri modeli yoktur.
  - Yeni cihazın tarih çakışan başka bir tahsisi varsa EXCLUDE ihlali 409'a dönüşür.
- **Dosyalar:** `services/teknik_servis/kiralama_tahsis.py`, `api/kiralamalar.py`, `pages/KiralamalarPage.tsx`, testler.
- **Kabul:**
  - Değişim sonrası kalem serilerinde yeni seri var, eski seri yok.
  - Eski cihazın geçmişinde "değiştirildi" görünür.
  - Başka kiralamaya rezervli yeni cihaz 409 döner.
- **Öncelik / Efor:** P3 / S.
- **Bağımlılık:** E06-07, E06-04.
- **Canlı risk:** Yok.

### E06-21 · M06-08 · İlk sürümde üç rapor
- **Canlı:** KISMEN. Rapor altyapısı VAR: `api/reports.py` (`rapor.gor`, `rapor.disaaktar`, `_xlsx`), `services/export.py`. Kiralama raporu YOK.
- **Yaklaşım:** `api/reports.py` dosyasına aynı kalıpta üç uç ve xlsx sürümleri eklenir. Hepsi `rapor.gor` + `kiralama.gor` ister ve birim + müşteri kapsamıyla süzülür.
  - `GET /api/raporlar/kiralama-depo-durumu(.xlsx)`: depo × durum adetleri (HAZIR, REZERVE = AKTIF sevksiz tahsis, KIRADA, KONTROLDE, HAZIR_DEGIL, KAYIP).
  - `GET /api/raporlar/kiralama-geciken-iade(.xlsx)`: kiralama, müşteri, bitiş, gecikme günü, müşterideki adet ve seri.
  - `GET /api/raporlar/kiralama-kontrolde-bekleme(.xlsx)`: cihaz/ürün, depo, KONTROLDE'ye giriş, bekleme günü.
  - Aşama süresi kolonu, E06-19 gelince zaman kaydından hesaplanır; kayıt yoksa "eksik" yazılır. Kullanım oranı (cihaz-gün) ikinci sürümde, E06-04 verisinden eklenir.
  - Rapor sayfasına "Kiralama" sekmesi eklenir; KPI kutuları tıklanınca ilgili listeye gider.
- **Dosyalar:** `api/reports.py`, `services/teknik_servis/kiralama_raporlar.py`, `pages/RaporlarPage.tsx`, `tests/integration/test_raporlar.py` (kiralama bölümü).
- **Kabul:**
  - Üç rapor birim kapsamına uyar; başka birimin kaydı görünmez.
  - Excel dosyası `rapor.disaaktar` ister.
  - Süre kaydı olmayan aşama "eksik" yazar.
  - Raporlarda fiyat kolonu yoktur.
- **Öncelik / Efor:** P3 / M.
- **Bağımlılık:** E06-03, E06-04, M12 (canlı rapor altyapısı).
- **Canlı risk:** Mevcut rapor sorgularına dokunulmaz. `services/reports.py:81` içindeki `"DEGISTI"` gözlemi bu madde kapsamında düzeltilmez.

### E06-22 · M06-D02 · Toplu envanter girişi (CSV/Excel, önizlemeli) ve depo bazlı fiziksel sayım
- **Canlı:** KISMEN. Ayrıştırıcı ve şablon VAR: `services/imports/cekirdek.py` (`oku`, `sablon_xlsx`, `Sutun`). Önizleme ve uygula deseni `api/imports.py` içinde VAR. Kiralık envanter ve sayım YOK.
- **Yaklaşım:**
  - **Toplu giriş** (`kiralama.envanter`):
    - Şablon: `GET /api/kiralama/envanter/sablon.xlsx`. Sütunlar: ürün kodu, seri no, adet, depo kodu, durum (HAZIR, KONTROLDE ya da HAZIR_DEGIL), not.
    - Önizleme: `POST /api/kiralama/envanter/toplu/onizleme` (dosya). `cekirdek.oku` `asyncio.to_thread` içinde çalışır ve satır hatalarını işaretler: dosya içi mükerrer seri, DB'de var olan seri, başka birim ürünü, seri takipli üründe adet ≠ 1. Önizleme hiçbir şey yazmaz.
    - Onay: `POST /api/kiralama/envanter/toplu/onayla`. Önizlemenin satır özeti tekrar doğrulanır ve yalnız hatasız satırlar her biri `kind=GIRIS` hareketiyle yazılır.
    - Dosya 10 MB sınırına tabidir.
  - **Sayım:**
    - `POST /api/kiralama/sayimlar {depo_id}` açık sayım başlatır (`uq_rsayim_acik`).
    - `PUT /api/kiralama/sayimlar/{id}/satirlar` sayılan seri ve adetleri alır.
    - `GET /api/kiralama/sayimlar/{id}/fark` sistemde olup sayılmayan, sayılıp sistemde olmayan ve adet farkı satırlarını listeler.
    - `POST /api/kiralama/sayimlar/{id}/onayla {kararlar}`: eksik çıkan seri için yalnız onaylı satırlarda `KAYIP` (`kind=SAYIM`) yazılır. Toplu adet farkı `kind=SAYIM` ile düzeltilir.
    - Onaysız fark hiçbir durumu değiştirmez.
- **Dosyalar:** `api/kiralamalar.py`, `services/teknik_servis/kiralik_envanter.py`, `models/servis_kiralama.py` (`rental_counts`), `pages/KiralikEnvanterPage.tsx`, testler.
- **Kabul:**
  - 200 satırlık dosyada mükerrer seriler reddedilir, diğerleri hareketle yüklenir.
  - Sayımda eksik çıkan seri onaysız durum değiştirmez.
  - Onaylı satır `KAYIP` olur ve hareketi görünür.
- **Öncelik / Efor:** P2 / M.
- **Bağımlılık:** E06-03.
- **Canlı risk:** Yok. Canlı `imports` uçları değişmez.

### E06-23 · (kullanıcı doğrulamalı işlevler) · Ön yüz: tıklanabilir KPI kutuları, toplu işlemler, Excel
- **Canlı:** KISMEN. Kalıplar VAR:
  - liste + Drawer + KartPenceresi (`pages/IsEmirleriPage.tsx`, `components/KartPenceresi.tsx`),
  - `EkYukleyici`, `KayitGorevleri`,
  - Excel (`api/reports.py:_xlsx`).
- **Yaklaşım:**
  - **`KiralamalarPage.tsx`:**
    - Üstte tıklanabilir KPI kutuları: Talep, Planlı, Hazırlanıyor, Kirada, Geciken iade, Eksik tahsis. Tıklama `kpi` filtresini uygular ve sayfayı 1'e alır. Sayılar `GET /api/kiralama/ozet` ucundan gelir (kapsamlı).
    - Liste `useQuery` + `api.getSayfa`. Satır seçimiyle toplu işlemler yapılır: toplu tahsis (çoklu seri seçimi), toplu sevk, toplu iade.
    - Drawer içeriği: kalemler, tahsisler, `Timeline` olay geçmişi, ekler, görevler, tutanak düğmeleri, `sonraki_durumlar` düğmeleri, "Önerilen aşama" bandı.
    - Form: KartPenceresi kalıbı; aynı form yeni kayıt ve düzenleme için kullanılır, `version` geri gönderilir, 409'da "yenileyin" mesajı gösterilir.
    - Excel: `GET /api/kiralama.xlsx` (`rapor.disaaktar`).
  - **`KiralikEnvanterPage.tsx`:**
    - Depo kartları, tıklanabilir sayaçlar (HAZIR, KONTROLDE, KIRADA, HAZIR_DEGIL, KAYIP).
    - Envanter tablosu; cihaz geçmişi Drawer'da açılır.
    - "Kontrol Et" toplu penceresi, transfer penceresi, sayım sekmesi, toplu giriş sekmesi.
    - Excel: `GET /api/kiralama/envanter.xlsx`.
  - Görünürlük `yetkili()` ile kısılır. Tarihler `DD.MM.YYYY`. Tüm metinler Türkçe. 375 px genişlikte kullanılabilir olmalı.
  - "Cihaz başına PB iş emri" kuralı bu modülü etkilemez: kiralık envanter `service_equipment`'a kopyalanmaz, PB worker'ı kiralık cihazlara iş üretmez (Karar K11).
- **Dosyalar:** `frontend/src/api/kiralama.ts`, `pages/KiralamalarPage.tsx`, `pages/KiralikEnvanterPage.tsx`, `main.tsx`, `components/AppLayout.tsx`, `api/kiralamalar.py` (`ozet`, xlsx).
- **Kabul:**
  - KPI kutusuna tıklayınca liste o filtreyle açılır ve sayı ile liste toplamı eşittir.
  - Toplu kontrolde 10 cihaz tek istekle işlenir.
  - Excel dosyası filtreyi uygular ve fiyat kolonu içermez.
  - `npm run build` ve `oxlint` temiz geçer.
- **Öncelik / Efor:** P2 / M.
- **Bağımlılık:** E06-02 … E06-07, E06-11.
- **Canlı risk:** Menüye yalnız iki kalem eklenir. Mobilite ekranlarına ("İş Emirleri", "Stok ve Transfer") dokunulmaz.

---

## 6. Migration planı

Zincir, teknik servis RBAC/birim migration'ından sonra başlar. Kodlama başlarken `alembic heads` ile doğrulanır; bugünkü head `b30e012dd879`.

1. `kiralama_cekirdek`:
   - `warehouses.birim/kiralama_deposu` + `ck_warehouse_birim` (yeni kolon, `op.add_column` + `op.create_check_constraint`),
   - `rental_no_seq`,
   - `rental_catalog_items`, `rental_assets`, `rental_inventory_movements`, `rentals`, `rental_items`, `rental_contacts`, `rental_allocations` (EXCLUDE autogenerate biçimi; `daterange` için `literal_column("daterange(baslangic, bitis, '[)')")`), `rental_events`, `rental_checks`.
   - Docstring içinde NEDEN yazılır: devices'a neden yazılmadığı ve bakiyenin neden hareketten hesaplandığı.
   - downgrade: ters sırayla drop, sequence drop, `warehouses` kolonları drop.
2. `kiralama_sayim`: `rental_counts`, `rental_count_lines`.
3. `servis_kiralama_bagi`: `service_orders.rental_id` + `uq_so_kiralama_tur_acik` (kısmi indeks). Servis çekirdeği migration'ından sonra gelir.
4. `atolye_kiralik_cihaz`: `workshop_records.rental_asset_id`. M05 migration'ından sonra gelir.

Her adım sonunda `test_migration_zinciri` (EXCLUDE sayısı +1), altın kayıt testi, `ruff` ve `npm run build` çalıştırılır.

---

## 7. Kararlar (kullanıcıya soru sorulmadı)

- **K1. Kiralık envanter `devices`'a ve `service_equipment`'a yazılmaz.** Ayrı `rental_assets` (seri takipli) ve hareket defteri (toplu) kurulur. Gerekçeler:
  - global `uq_devices_seri`,
  - mobilite stok yaşam döngüsü ve raporları,
  - `stock_movements` CHECK listesinin canlıda değiştirilemezliği.
  - Kiralık cihaz müşteriye kurulu ekipman değildir; Denge'nin demirbaşıdır.
- **K2. Toplu (seri takipsiz) stok satır tutmaz, hareket toplamından hesaplanır.** Canlının serisiz stok ilkesiyle (`models/stock.py:200-204`) aynıdır. Eski sistemdeki "satır bölme" sorunu (denetim M06-13 notu) bu yolla hiç oluşmaz.
- **K3. Bloke zamanı:**
  - `PLANLANDI` geçişi ürün/adet düzeyinde rezerv yaratır (tarih bazlı).
  - `HAZIRLANIYOR` adımındaki tahsis fiziksel cihaz ya da adet bağlar.
  - Teklif/Talep aşaması hiçbir şeyi bloke etmez.
- **K4. HTTP kodları canlı kurala uyar:**
  - Yasak durum geçişi ve kural ihlali 409 (kaynakta bazı yerlerde 400 yazıyordu).
  - Girdi eksikliği 400 (gerekçe, tahsis eksikliği).
  - Kapsam dışı kayıt 404 (kaynakta 403). Canlı test emsali `test_kapsam_guvenligi.py:49-56`.
- **K5. Kurulum ve devreye alma aşamaları her birim için isteğe bağlıdır.** Makine `SEVK_EDILDI→DEPOYA_ALINDI` kısa yolunu tanır. Telsiz kiralamaları bu yolu kullanır; birim bazlı ayrı makine açılmaz.
- **K6. İzin sayısı:**
  - Denetim önerisi izlenir: `kiralama.envanter` ve `kiralama.asama`, artı `kiralama.gor/yaz`.
  - Ayrı `rentals.check` ve `catalog.manage` açılmaz; kontrol ve katalog `kiralama.envanter` kapsamındadır.
  - Depo tanımı değişikliği yeni izin açmaz, mevcut `sistem.ayar` iznine bağlanır. Depolar mobilite stoğuyla paylaşılıyor; adlarını kiralama rolü değiştirmemeli.
- **K7. Roller:**
  - Kiralama için iki yeni rol açılır: `KIRALAMA_OPERASYON` ve `KIRALAMA_DEPO`, ikisi de `KENDI_BIRIMI`.
  - Mevcut `DEPO` rolü değiştirilmez. Kiralık depo işini yapacak mevcut depo personeline `KIRALAMA_DEPO` rolü atanır ya da `UserPermission` istisnası verilir.
  - Eski sistem kullanıcılarının "eşdeğer anahtara taşınması" canlıya geçişte bu rol atamasıyla yapılır.
- **K8. Dönüş kontrolünü depo yapar (`kiralama.envanter`).** Arızalı cihaz atölyeye isteğe bağlı ikinci adımla gider. Ürün bazlı kontrol listesi şablonu P3'e bırakıldı; şimdilik serbest not kullanılır.
- **K9. Toplu envanter girişi canlı `imports` partisiyle değil, kiralama ucunda yapılır.** Profil `dogrula` imzası kullanıcıyı almıyor, bu yüzden birim kapsamı orada uygulanamaz. Ayrıştırıcı `cekirdek.oku` yeniden kullanılır. Pilot verinin göçü ise `imports` profilleriyle yapılır (`sistem.goc`, kapsam TUMU).
- **K10. Uyarılar saklanmaz, hesaplanır (canlı desen).** Eski "tür:id:gün" anahtarı yalnız satır listesi ve worker özetinde kimlik olarak üretilir; bildirim tablosu açılmaz.
- **K11. Kiralık cihaz için planlı bakım (PB) iş emri üretilmez.** "1 cihaz = 1 PB iş emri" kuralı kurulu ekipman (`service_equipment`) için geçerlidir ve bu modülden etkilenmez. Kiralık cihazın bakımı dönüş kontrolü ve atölye ile yapılır.
- **K12. Müşteri zorunluluğu servis doğrulamasıyla 400 döndürür.** Bu, eski "boş müşteri adı 400" kabulünü karşılar. Pydantic tip hatası 422 olarak kalır.
- **K13. Kiralama bedeli ve günlük ücret ERP'de tutulmaz.** Bu alanda fiyat ya da maliyet kolonu yoktur. Ticari taraf `rentals.quote_id` ile teklif modülünde kalır ve orada mevcut `sees_cost`/teklif görünürlüğüne tabidir. Tutanak, Excel ve raporlar fiyatsızdır.
- **K14. Kayıp/hasar için muhasebe rücu bildirimi yapılmaz.** Kayıp yalnız kayıt ve harekettir. Logo entegrasyonu kapsam dışıdır; gerekirse rapor Excel'i kullanılır.
- **K15. Kiralama süresi uzatma ayrı kayıt değildir.** Bitiş tarihi değişikliği müsaitlik kontrolünden geçer, `rental_events` tablosuna `TARIH` olayı olarak yazılır ve AKTIF tahsislerin bitişini günceller.
- **K16. Kiralama depoları `warehouses` tablosunda `kiralama_deposu=true` satırlarıdır.** Mobilite depolarıyla aynı tabloyu paylaşır ama ayrı satırlardır. Gerçek adlar `sistem.ayar` ile güncellenir; seed adları `KIR-DEPO-1..3` yer tutucudur.
- **K17. Bitiş tarihi iade günüdür; aralık `daterange(baslangic, bitis, '[)')`.** Aynı gün teslim alınıp başka kiralamaya çıkan cihaz çakışma sayılmaz (canlıdaki yarı açık aralık ilkesi).
- **K18. Belge numarası PostgreSQL sequence'i ile üretilir: `KIR-YYYY-#####`.** Canlıdaki `count+1` ve `max+1` desenleri kopyalanmaz.
- **K19. Hareket ve olay tabloları ekleme-yalnızdır.** API'de değiştirme ucu yoktur; ORM `before_update/before_delete` dinleyicisi ikinci savunma hattıdır. DB trigger'ı kullanılmaz, çünkü canlıda trigger emsali yok.
- **K20. Aşama geri alma için makineye ters kenar eklenmez.** `asama_geri_al` yalnız son olayı ters hareketle çevirir ve makinede var olan ileri geçişi doğrular. Böylece normal uçlardan geri gidiş mümkün olmaz.

## 8. Gözlemler (bu çalışmada değiştirilmedi)

- `schemas/catalog.py` `UrunPatch.identity_kind` değişikliğine izin veriyor ve bunun için koruma yok. `devices` FK'si `onupdate="CASCADE"` olduğu için kimlik tipi değişikliği seri/IMEI CHECK'ini cihazlarda kırabilir. Kiralama tarafı bunu `ON UPDATE RESTRICT` ve E06-16 korumasıyla kendi tablolarında kapatıyor; mobilite tarafı ayrı değerlendirilmeli.
- `api/stock.py` içinde depo tanımı yazma ucu yok (yalnız `GET /depolar`, `:361`). Depolar seed ile geliyor. E06-02 ve K16 bu nedenle `sistem.ayar` korumalı bir PATCH ucu öneriyor.
- Genel belgedeki gözlemler geçerliliğini koruyor: `services/reports.py:81` içindeki `"DEGISTI"` değeri ve `count/max+1` numaralama deseni.
