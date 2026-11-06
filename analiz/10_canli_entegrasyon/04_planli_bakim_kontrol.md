# E04 Planlı Bakım: Bağımsız Kontrol Raporu

> Tarih: 21.10.2026 · Denetlenen: `10_canli_entegrasyon/04_planli_bakim_entegrasyon.md`
> Yöntem: Canlı kod (`denge-erp/backend/app`, `tests/conftest.py`) ve kardeş entegrasyon belgeleri (E01, E02, E03, E07, E09, E11, E12) okundu. Kaynak koda dokunulmadı.

---

## 1. Genel hüküm

Tasarımın ana yönü doğru:
- Ayrı `maintenance_*` tabloları açılıyor ve PB, `service_orders.tur='PB'` olarak tutuluyor.
- `work_orders`, `work_order_items` ve `settlements` tablolarına yazılmıyor.
- "1 cihaz = 1 PB" kuralı kısmi tekil indeksle zorlanıyor.
- Sayaç saklanmıyor, dönemler birbirini bloke etmiyor.
- Ücret `sees_cost` ile gizleniyor ve `Clock` kullanılıyor.

"Canlıda YOK" tespitleri doğru. `backend/app` içinde bakım sözleşmesi, form, onay ya da kontrol listesi yok. Tek "bakım" izi mobilite iş emrindeki `type='BAKIM'` (`models/workorder.py:56,85`, `services/workorders.py:50`); bu bir montaj ziyareti türü ve tasarımla çakışmıyor.

**Asıl sorun canlı kodla değil, kardeş tasarımlarla.** E04, E01/E02/E03/E09/E11'in zaten tanımladığı varlıkların bir kısmını yeniden üretiyor ya da onlarla uyuşmayan adlar ve sözleşmeler kullanıyor. Kodlama bu haliyle başlarsa ikinci migration'da CHECK, kolon veya tablo düzeltmesi gerekir.

| # | Çakışma | E04 | Kardeş belge | Karar |
|---|---|---|---|---|
| 1 | Dönem kolonu | `service_orders.maintenance_period_id` (FK) | E01 §2.2 ve E01-17: `bakim_donemi` (YYYY-AA metin) | E04'ün FK'sı doğru. E01 metni güncellenmeli. |
| 2 | Müşteri onayı | `service_customer_approvals` + `service_approval_links`; yöntemler EKRAN_IMZA/KAGIT_FORM/IMTINA | E01-08 `service_approvals` (IMZA/SOZLU/BASILI_FORM/ALINAMADI, `ek_id`, `gecersiz_kilan_id`) ve `servis_onay_zorunlu_turler` ayarı | **Mükerrer tablo.** E01 tablosu yeniden kullanılır (E04-15). |
| 3 | PB yeniden açma | `TAMAMLANDI→BEKLEMEDE`, yeni izin `bakim.yeniden_ac` | E01 makinesinde `TAMAMLANDI→{KAPATILDI, TEKRAR_ACILDI}` var, `BEKLEMEDE` yok; yeniden açma `POST /isler/{id}/yeniden-ac` (`servis.kapat`) | E01 yolu kullanılır (E04-20). |
| 4 | Bekleme nedeni | `service_holds.neden='UYGUNSUZLUK'` | E01 `ck_hold_neden`: MALZEME, MUSTERI_ONAYI, TEKLIF, MUSTERI_ERISIMI, PERSONEL, DIGER | E01 tuple'ına eklenmeli; E01 migration'ı yayımlanmadan yapılırsa elle CHECK migration'ı gerekmez. |
| 5 | Teknisyen kapsamı | §4 "SERVIS_TEKNISYEN KENDI_BIRIMI" | E01 §3.3: `KENDI_ISLERI` | E01 doğru. |
| 6 | Birim altyapısı | "E13" bağımlılığı | E01-01 (K21) `user_units`, `BIRIMLER`, `kapsam.py`; ayrı E13 belgesi yok | Bağımlılık E01-01'e çevrilir. |
| 7 | Sözleşme kalemi ↔ ekipman | `equipment_id` nullable, SET NULL, `ex_mci_ekipman_cakisma` | E03: NOT NULL, RESTRICT, `ex_sozlesme_kalem_cakisma` | E04'ün nullable yaklaşımı tür+adet kararıyla tutarlı. FK RESTRICT olmalı; tek EXCLUDE adı seçilmeli; E03 güncellenmeli. |
| 8 | Seri no | `maintenance_forms.serial_no` + `contract_items.last_serial_no` | E01 `service_order_serials` (seri_norm, pg_trgm); E01-17 "PB'de seri değişikliği 409" | **Çift kaynak.** PB serisi E01 tablosunda tutulur. Form onu düzenler; ilk girişe ve açık PB'de düzeltmeye bakım formu bağlamında izin verilir. |
| 9 | Parça | `maintenance_part_reports` + depoda `POST /api/stok/hareket` (cihaz.yaz) | E11 K21 ve E11-14: E04-21 yerine `ServisParcalari` + `service_part_requests` + `parca.kullan` | **E11 öncelikli.** Ayrı tablo kaldırılır (E04-21). |
| 10 | Toplu planlama | `TopluPlanPenceresi.tsx`, `ex_plan_kisi_cakisma` → 409 | E02: `POST /toplu-plan`, `PlanPenceresi.tsx`, çakışma motoru (gerekçe yoksa 409), kapalı iş 400 | Adlar ve kabul E02'ye göre düzeltilir (E04-12). |
| 11 | Form PDF | `GET /formlar/{id}/form.pdf` | E01-08 `GET /isler/{id}/servis-formu.pdf` ve aynı şablon | Tek uç kalır; PB bölümü koşullu eklenir (E04-16). |
| 12 | Süre eksik | Kendi sorgusu ("MOLA dışı kayıt yok") | E09 süre durumu fonksiyonu (EKSIK/BEKLENMIYOR, `kisi_saat_dk=None`) | E09 fonksiyonu çağrılır (E04-18). |
| 13 | KPI kutusu | Kendi `Card hoverable` kodu | E12 `KpiKutusu.tsx` ve KPI motoru ("kendi sayaç SQL'i yazmaz") | E12 bileşeni kullanılır. |
| 14 | Worker görevi | `bakim-pb-uretimi` | E01-17: `pb-uretimi` | Tek ad seçilir. |
| 15 | İmza ek türü | Canlıdaki `IMZA` (`models/attachment.py:49`) | E01: yeni `MUSTERI_IMZASI` | Canlı `IMZA` kullanılır; E01'in yeni türü gereksiz. |

---

## 2. Canlı koda karşı doğrulanan teknik bulgular

1. **`ON CONFLICT ON uq_so_pb_cihaz_donem` çalışmaz.** Bu bir kısmi tekil İNDEKS, constraint değil. `ON CONFLICT ON CONSTRAINT` kısmi indeksi hedefleyemez. Doğru biçim indeks çıkarımıdır: `ON CONFLICT (contract_item_id, maintenance_period_id) WHERE tur='PB' AND NOT is_deleted DO NOTHING`. Alternatif: ORM ile SAVEPOINT içinde ekleme yapılır ve `IntegrityError` yakalanır. Form ve madde satırları yalnız PB gerçekten eklendiyse (RETURNING) açılmalı.
2. **`PROFIL_IZINLERI` eksik.** `api/imports.py:67` profil kodu için `PROFIL_IZINLERI[kod]` okuyor. Profil buraya eklenmezse KeyError → 500 oluşur. Ayrıca içe aktarma birim kapsamı uygulamıyor: `bakim.yaz` sahibi SERVIS_SEF Excel'le başka birime sözleşme açabilir.
3. **`require_permission` "hepsi" anlamındadır** (`api/deps.py:79-80`). "bakim.gor **veya** cihaz.yaz" bir bağımlılıkla yazılamaz; gövdede kontrol gerekir. Daha önemlisi, `cihaz.yaz` mobilite `TEKNIK_SERVIS` rolünde de var (`permissions.py:170`). Bu yüzden E04-21'deki uç ve uyarı, PB verisini mobilite rolüne açar ve "TEKNIK_SERVIS'e bakım izni verilmez" kuralını dolaylı olarak deler. E11 yolu bunu da çözer.
4. **Ücret girişini kimse yapamaz.** `maliyet.gor` yalnız ADMIN, SATIS_MUDURU, MUHASEBE_DESTEK ve YONETIM rollerinde (`permissions.py:138,243,247`). `bakim.yaz` yalnız SERVIS_YONETICI ve SERVIS_SEF'te olacak. Kesişim yalnız ADMIN; "ücret gönderene 403" kuralıyla birlikte sözleşme ücreti fiilen girilemez. Ayrıca göç Excel'indeki `legacy_fee_text`, ücret görmeyen SERVIS_YONETICI'nin yükleyip indirdiği dosyada açıkta kalır.
5. **`seq_bakim_sozlesme_no` testlerde sıfırlanmaz.** `TRUNCATE ... RESTART IDENTITY` yalnız tabloya ait (owned) sequence'ları sıfırlar (`tests/conftest.py:41-49`). Sequence `OWNED BY maintenance_contracts.id` yapılmalı ya da testler numara değerine bağlanmamalı. Downgrade sequence'ı düşürmeli.
6. **`_TRUNCATE` eklemesi gereksiz.** `maintenance_generation_runs` `users`'a FK ile bağlı ve `users` listede; `CASCADE` tabloyu zaten temizler. Zararsız ama gerekçe yanlış.
7. **Tarihsiz kalem EXCLUDE'u kirletir.** TEYIT_BEKLIYOR sözleşmenin kalemlerinde `valid_from` NULL ise `tstzrange(NULL,NULL)` sonsuz aralıktır ve ekipman bağlandığında her şeyle çakışır. Rehber §1.1'e göre EXCLUDE `WHERE valid_from IS NOT NULL AND equipment_id IS NOT NULL AND NOT is_deleted` olmalı; buna `ck_mci_tarihsiz_acik` eşlik etmeli.
8. **`uq_mci_sira (contract_id, equipment_type, sira) WHERE NOT is_deleted` yeniden artışta çakışır.** Kapsam azaltma satırı silmiyor, `valid_to` yazıyor; adet tekrar artınca aynı `sira` kapalı satırla çakışır. `sira` her zaman max+1 verilmeli (kapalılar dahil) ya da tekillik `WHERE valid_to IS NULL` ile sınırlanmalı.
9. **`ck_mc_sabit_ay` ay değerlerini sınamıyor.** `fixed_months <@ ARRAY[1..12]::smallint[]` eklenmeli.
10. **`KayitTipi.kod` canlıda küçük harf kısa koddur** (`"isemri"`, `"rma"`; `services/gorevler.py:48-56`). Önerilen `"BAKIM_SOZLESMESI"` kalıba uymuyor; `"bakim_sozlesme"`, alanlar `("contract_no",)`, yol `/bakim?sozlesme={id}` olmalı.
11. **Başarısız tamamlamada ziyaret yazılamaz.** E04-13 "başarılı veya başarısız her sonuç için" diyor. 400/409 transaction'ı geri alır, ziyaret satırı da gider. Doğru ifade: "her başarılı tamamla çağrısı (UYGUNSUZLUK_VAR dahil)".
12. **E04-05 kabul 1 sınadığını iddia ettiği şeyi sınamıyor.** Döngü `valid_from`'a bağlı. 01.06.2026 başlangıçlı sözleşmede 02.01.2027 hâlâ ilk döngüdür. Test sözleşmesinin `valid_from`'u 01.01.2026 olarak açıkça verilmeli ya da FakeClock döngü sınırını geçmeli.
13. **`_maliyet_gizle` canlıda anahtarı silmiyor, `None` yapıyor** (`api/reports.py:41-45`). E04'ün "anahtar hiç yok" kabulü canlıdan sıkı; yeni uçlarda doğru olan da bu. Ama rapor/Excel yardımcısı kopyalanırken `None` kalıbı taşınmamalı.

---

## 3. Madde bazında karar

| ID | Karar | Öncelik | Özet gerekçe |
|---|---|---|---|
| E04-01 | DEĞİŞTİR | P1 | Teknisyen kapsamı `KENDI_ISLERI`; bağımlılık E01-01; izin sayısı 6'dan 3'e iner |
| E04-02 | DEĞİŞTİR | P1 | Sıra tekilliği, tarihsiz EXCLUDE, RESTRICT FK, ücret giriş yolu |
| E04-03 | DEĞİŞTİR | P1 | `PROFIL_IZINLERI`, birim kapsamı, ücret kolonu, `title_key` çoklu eşleşme |
| E04-04 | DEĞİŞTİR | P1 | Teyit kaydında kapsam azaltmaya izin verilir; "korundu" çekirdeğin `cakisma` kanalıyla |
| E04-05 | DEĞİŞTİR | P1 | Kabul 1 düzeltilir; kapanış E01 durum kancasından da tetiklenir |
| E04-06 | DEĞİŞTİR | P1 | Kısmi indekste ON CONFLICT biçimi; PB'nin E01 zorunlu alanları |
| E04-07 | KABUL | P1 | Görev adı E01-17 ile tekleştirilir |
| E04-08 | KABUL | P2 | Saf fonksiyon + gerekçeli elle tarih yeterli; önizlemede SAVEPOINT seçeneği |
| E04-09 | DEĞİŞTİR | P1 | Seri E01 tablosunda; sonuç `service_results`'a eşlenir; TAMAMLANDI E01 `durum_degistir(kaynak=...)` ile |
| E04-10 | DEĞİŞTİR | P1 | Koruma E01'in tek giriş noktasında; `/sonuc`, `/iptal`, `/yeniden-ac` uçları da kapsanır |
| E04-11 | DEĞİŞTİR | P1 | İptal E01 `cancel_reason` ile; tek şefli birimde karar yöneticiye düşer |
| E04-12 | DEĞİŞTİR | P1 | E02 uç/bileşen adları, çakışma kuralı ve 400 kodu |
| E04-13 | DEĞİŞTİR | P2 | Yalnız başarılı tamamlamada; YENIDEN_ACMA E01 olayıyla birlikte |
| E04-14 | DEĞİŞTİR | P2 | Bekleme nedeni E01'e eklenir; teklif bağı E07 kısayolu ile |
| E04-15 | DEĞİŞTİR | P2 | E01 `service_approvals` yeniden kullanılır; mükerrer tablo yok |
| E04-16 | DEĞİŞTİR | P2 | E01-08 PDF ucu ve bağlamı genişletilir; parça E11'den |
| E04-17 | DEĞİŞTİR | P2 | Otomatik ekipman bağı tamamlamayı bloke etmez; E03 ile tek şema |
| E04-18 | DEĞİŞTİR | P2 | E12 KPI motoru/`KpiKutusu` ve E09 süre fonksiyonu kullanılır |
| E04-19 | DEĞİŞTİR | P3 | Ziyaret verisi birikmeden anlamsız; adım 1'den sonra |
| E04-20 | DEĞİŞTİR | P2 | `TEKRAR_ACILDI` + `servis.kapat`; `bakim.yeniden_ac` açılmaz |
| E04-21 | DEĞİŞTİR | P3 | E11'e devredilir; `maintenance_part_reports` açılmaz |
| E04-22 | KABUL | P3 | Ertelenmiş; tetik koşullu |
| E04-23 | DEĞİŞTİR | P2 | `KayitTipi` kalıbı; KVKK E01-18'den gelir |

Ayrıntılı gerekçe ve düzeltilmiş metin StructuredOutput `verdicts` alanındadır.

### İzin sadeleştirmesi (E04-01, E04-09, E04-20)

E04 altı izin açıyor, ama `bakim.yaz`, `bakim.uret` ve `bakim.onayla` aynı iki role (SERVIS_YONETICI, SERVIS_SEF) veriliyor. E01 K23 aynı durumda "ayrı tutmak boş izin üretir" diyerek birleştirmişti.

Öneri:

| İzin | Kapsam |
|---|---|
| `bakim.gor` | Okuma |
| `bakim.yaz` | Sözleşme, kapsam, üretim, hedef tarih |
| `bakim.onayla` | Kapsam dışı kararı, uygunsuzluk aksiyonu. "Talep eden onaylayamaz" ayrımı ve ileride operasyon rolüne yalnız yazma vermek için ayrı tutulur. |

- PB formu: taslak için `servis.yaz`, tamamlama için `servis.tamamla`. İkisi E01'de teknisyende zaten var; erişim E01 `is_erisimi_yok_mu` ile sağlanır.
- Yeniden açma: E01 `servis.kapat`.

---

## 4. Eklenen maddeler

| ID | Başlık | Öncelik |
|---|---|---|
| E04-D01 | Kardeş tasarımlarla şema ve ad hizalaması (§1 tablosu tek kaynak) | P1 · S |
| E04-D02 | PB durum kancası ve dönem kapanışının gece uzlaştırması | P1 · S |
| E04-D03 | Bakım içe/dışa aktarma güvenliği (`PROFIL_IZINLERI`, birim, ücret kolonları) | P1 · S |
| E04-D04 | Sözleşme ücretinin giriş yolu (`maliyet.gor` ∩ `bakim.yaz` boş) | P2 · S |
| E04-D05 | Mobilite `work_orders.type='BAKIM'` ile ad ve rapor ayrımı | P3 · S |

---

## 5. Kararların değerlendirmesi

| Karar | Hüküm |
|---|---|
| S1 (açık aksiyonda PB BEKLEMEDE) | Onaylı kabul kriterine uyuyor, kabul edilebilir. Ancak teklif veya arıza işi aylarca açık kalabilir; dönem açık kalır ve "uyum" KPI'ı düşer. KPI'da "bakımı yapıldı, aksiyon açık" ayrımı **zorunlu** tutulmalı, uyum oranı ziyaret tarihine göre de raporlanmalı. Kullanıcıya teyit için sorulması önerilir. |
| S2/S3 (onay zorunlu, tek onay çok PB) | Makul. Ama E01'in ayarı (`servis_onay_zorunlu_turler`) varsayılan `["PB"]` ile kullanılmalı; yeni `bakim_musteri_onayi_zorunlu` ayarı açılmaz. |
| S4, S5, S6/S7, S8, S9 | Makul. |
| S10 (parça yalnız bilgi + cihaz.yaz) | **Geçersiz.** E11 K21 bunu `parca.kullan` + `ServisParcalari` ile değiştirdi; `cihaz.yaz` mobilite rolüne sızar. |
| Depolama, WeasyPrint | Makul. E01-08 ile aynı altyapı. |
| 409/400 ayrımı | Doğru yön, ama E01 aynı "yanlış uç" durumuna 400 diyor. İki modülde tek kural seçilmeli: kural ihlali 409. |
| Tür+adet → satır başına cihaz | Doğru; E03'ün NOT NULL `equipment_id` varsayımı güncellenmeli. |
| Sayaç saklanmaz, dönemler bloke etmez, süresi dolan üretilmez | Doğru. |
| `maliyet.gor` kullanımı | Doğru, ama giriş yolu eksik (E04-D04). |
| Numara | `BKM-YYYY-NNNNN` ile göçteki `BAKIM-00NN` iki biçim üretir. Kullanıcı alışkanlığı için yeni kayıtlar da `BAKIM-NNNN` biçiminde, sequence göçteki en büyük numaradan sonra başlatılarak (`setval`) üretilebilir. Bu bir tercih; çakışma riski yok. |
| Tüm birimlere açık sözleşme | Makul. Şablonu olmayan tür `SABLON_YOK` ile atlanıyor. Ancak `ck_mci_tur` yalnız XRAY/KAPI_DEDEKTORU kabul ettiği için şablonsuz tür girilemez; `SABLON_YOK` yolu E04-22 gelene kadar ölü koddur. |
| Ayrı varlık (abonelik değil) | Doğru (`api/attachments.py:49`). |
| `models/servis_bakim.py` bölünmesi | Makul. |
| Teknisyen sözleşme listesini görmez | Doğru. |
| Arıza işi otomatik açılmaz | Doğru. E01 `iliskili_is_id` ile PB'ye bağlanmalı; `iliski_turu`'na `BAKIM_BULGUSU` eklenebilir. |
| Göç iki adımlı, ezmeme kuralı | Doğru. Teyit kaydında kapsam azaltma serbest bırakılmalı (E04-04). |
| Ayrıştırıcı yazım hataları için genişletilmez | Doğru. |
| Toplu planlamada yeni motor yok | Doğru. |

---

## 6. Mobilite akışlarına etki

- `work_orders`, `work_order_items`, `settlements`, `devices` ve `device_vehicle_assignments` tablolarına yazma ya da kısıt değişikliği yok. Altın kayıt testi etkilenmez.
- Risk taşıyan tek nokta E04-21'deki `cihaz.yaz` ile açılan uç ve uyarı. Mobilite TEKNIK_SERVIS ve DEPO rolleri PB verisi görürdü. E11 yoluna geçilince risk kalkar.
- `api/attachments.py` `_kapsam` değişikliği yalnız yeni entity dallarını ekliyor; `accounts` dalı korunuyor (`:102`).
- `PROFILLER` sözlüğünde yeni profil sona eklenirse mevcut yükleme sırası bozulmaz (`services/imports/__init__.py:28-45`).
