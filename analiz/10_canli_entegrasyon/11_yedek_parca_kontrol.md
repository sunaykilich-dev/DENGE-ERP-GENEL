# E11 Yedek Parça ve Servis Stoğu: Bağımsız Kontrol

> Tarih: 2026-10-21 · Denetlenen: `11_yedek_parca_entegrasyon.md` · Yöntem: canlı kod okundu (kaynak koda dokunulmadı).
> Okunan canlı dosyalar: `backend/app/models/stock.py`, `services/stock.py`, `api/stock.py`, `models/catalog.py`, `api/catalog.py`, `permissions.py`, `services/imports/__init__.py`, `services/imports/cekirdek.py`, `api/imports.py`, `models/purchase.py`, `services/purchasing.py`, `services/uyarilar.py`, `pyproject.toml`, `frontend/src/pages/StokPage.tsx`; kardeş belgeler `00_MIMARI_KURALLAR.md`, `01_is_emirleri_entegrasyon.md`, `01_is_emirleri_kontrol.md`, `06_kiralama_depo_entegrasyon.md`, `07_teklif_maliyet_entegrasyon.md`.

---

## 1. Genel hüküm

Tasarımın ana kararı doğru: ayrı defter açılmıyor, canlı `stock_movements` yalnız nullable kolonlarla genişletiliyor, canlı `ck_stok_hareket_neden` ve `ck_stok_hareket_adet` olduğu gibi kalıyor. Ayrıntılı tür ayrı kolonda tutuluyor ve tür ile `reason`/işaret eşlemesi CHECK ile kilitleniyor. Mobilite hak ediş zinciri, IMEI kimlik kuralı ve EXCLUDE kısıtları bu tasarımdan etkilenmiyor. Canlı durum tespitleri doğrulandı:

- `stock_movements` işaretli adetli bir defter (`models/stock.py:200-236`).
- Tek yazıcı `services/stock.py:300-340`; kilit ve bakiye kontrolü yok.
- `StockMovement(` yalnız `services/stock.py:329`'da kuruluyor.
- Liste ucu sayfasız ve tek filtreli (`api/stock.py:316-343`).
- `products` tablosunda birim, minimum stok ve yedek parça bayrağı yok.

Yine de tasarımda düzeltilmesi gereken **beş kritik nokta** var:

1. **Canlı mobilite uçları servis defterini sızdırıyor ve toplamlara karıştırıyor (K1 ile §12'deki "dokunulmaz" listesi çelişiyor).**
   - `GET /api/stok/hareketler` uç noktası `cihaz.gor` ile korunuyor ve kapsam filtresi yok (`api/stock.py:316-343`). `SATIS` rolü `KENDI_MUSTERILERI` kapsamında olduğu hâlde bu izne sahip (`permissions.py:91-112`). Sonuç olarak servis işine bağlı parça hareketleri, notlar ve belge numaraları birim ya da müşteri kapsamı olmadan listelenir. Mobilite `StokPage.tsx:141` de bu listeyi gösterir; ters kayıtlar orada "CIKIS +3" gibi anlamsız satırlar olarak görünür.
   - `/api/stok/ozet` (`services/stock.py:255-263`) ve ürün `stok_adedi` (`api/catalog.py:130-136`) servis deposundaki adedi mobilite "elde" rakamına katar.
   - Tasarımdaki "migration sonrası özet aynı" kabulü yalnız migration anı için doğrudur.
   - Bu konu E11-D01 olarak eklendi.
2. **Maliyet hiç girilemez hâle geliyor.** `maliyet.gor` yalnız ADMIN, SATIS_MUDURU, MUHASEBE_DESTEK ve YONETIM rollerinde var (`permissions.py:138, 243, 247`). Tasarım, `unit_cost` yazmak için `parca.yonet + maliyet.gor` istiyor ve `maliyet.gor` kümesini değiştirmiyor.
   - Bu yüzden `SERVIS_DEPO` ve `SERVIS_YONETICI` maliyet giremez; pratikte maliyeti yalnız ADMIN girebilir.
   - K8'deki hareketli ortalama ve E11-18'deki tutar bu durumda boşa çalışır.
   - Ayrıca canlı satın alma modülü serisiz ürünü mal kabulde reddediyor (`services/purchasing.py:130-133`), yani maliyetin doğal kaynağı da kapalı. Bu konu E11-D02 olarak eklendi.
3. **E07 ile kolon çakışması.** E07 aynı kolonu `stock_movements.unit_cost_try Numeric(14,2)` adıyla tanımlıyor ve değeri "son mal kabul × kur" yöntemiyle hesaplıyor. E11 ise `unit_cost Numeric(14,4)` adını ve "hareketli ağırlıklı ortalama" yöntemini kullanıyor (`07_teklif_maliyet_entegrasyon.md:17, 95`). Hangi migration önce gelirse ötekini kırar. Bu konu E11-D03 olarak eklendi.
4. **E01 sözleşmesiyle uyumsuz adlar.** E01'deki `ck_soe_tur` listesinde `PARCA` yok (`01_is_emirleri_entegrasyon.md:116`). Bekleme nedeni de `PARCA` değil, `MALZEME` (`:130`). E11-04 ile E11-19 bu adlarla yazılırsa CHECK ihlali olur.
5. **Kilitlenme ve yarış koşulları.**
   - Çok satırlı çıkış, transfer ve sayım onayı ürün satırlarını rastgele sırada `FOR UPDATE` ile kilitlerse, ters sıralı iki istek kilitlenme (deadlock) üretir. Kilitler ürün kimliğine göre sıralı alınmalı.
   - Çıkış ile iş kapanışı aynı anda olursa kapalı işe parça yazılabilir. Servis işi satırı da kilitlenmeli.

Aşırı mühendislik olarak görülenler:

- `ix_stok_hareket_depo_urun (warehouse_id, product_id)`: canlı `ix_stok_hareket_urun (product_id, warehouse_id)` ile gereksiz tekrar.
- Mutabakat ucu ve uyarısı: CHECK, tetikleyici ve kilit zaten bu ihlalleri yapısal olarak engelliyor.
- `parca_toplu_satir_ust_sinir` ve `parca_sayim_degisim_toleransi` ayarları: Pydantic `max_length` ve `degisimi_kabul` yeterli.
- İsteğe bağlı mutabakat worker'ı.
- Belge no trigram indeksi: tablo küçük; P3 ya da isteğe bağlı.
- `api/imports.py`'ye `hepsi_ya_hic` bayrağı eklemek: gereksiz. Profilin `yaz()` metodu ValueError fırlatırsa mevcut uç zaten 409 döner ve transaction'ı geri alır (`api/imports.py:218-227`).

---

## 2. Madde kararları

| Id | Karar | Öncelik | Gerekçe / düzeltme |
|---|---|---|---|
| E11-01 | DEĞİŞTİR | P1 | Model doğru, şu düzeltmeler gerekli: (a) `hareket_yaz` isteğe giren tüm ürünleri **kimliğe göre sıralı** ve tek seferde `FOR UPDATE` ile kilitlemeli; çok satırlı çıkış, transfer ve sayım onayı aynı yardımcıyı kullanmalı. (b) `trg_stok_hareket_degismez` E11-22'den bu migration'a alınmalı (ayrı ikinci migration'a gerek yok); `created_by/updated_by/updated_at` dışındaki tüm kolonları korumalı. (c) `ix_stok_hareket_depo_urun` çıkarılmalı (canlı `ix_stok_hareket_urun` aynı işi görüyor). (d) Açılış tekilliği için kısmi `uq_stok_hareket_acilis (product_id, warehouse_id) WHERE hareket_turu='ACILIS'` eklenmeli. (e) Maliyet kolonunun adı ve tipi E11-D03'e göre sabitlenmeli. (f) Kabul (4) "migration anında aynı" diye daraltılmalı; sonrası E11-D01'e bağlanmalı. |
| E11-02 | DEĞİŞTİR | P1 | Kural doğru, ama yarış koşulu var: `CIKIS_SERVIS` yazılırken `service_orders` satırı `with_for_update(read=True)` ile kilitlenmeli. Böylece E01 kapanış güncellemesi çıkış commit edilene kadar bekler. Kabule eklenecek: "Eşzamanlı kapanış ve çıkışta kapalı işe hareket kalmaz." |
| E11-03 | DEĞİŞTİR | P1 | `hypothesis` bağımlılıklarda yok (`pyproject.toml`), bu yüzden "property testi" sabit tohumlu parametrik rastgele dizi testine çevrilmeli. `net_cikis` tanımı `-Σqty WHERE service_order_id=:so AND product_id=:p` olmalı; ters kayıt `service_order_id`'yi kopyaladığı için ayrıca birleştirme gerekmez. |
| E11-04 | DEĞİŞTİR | P1 | E01'deki `ck_soe_tur` listesine `PARCA` eklenmeli (E01 belgesi güncellenir); yoksa olay satırı CHECK'e takılır. Yanıtta maliyet anahtarı yalnız `sees_cost` true ise yer almalı. Teknisyenin depo kümesi §3 ile E11-23 arasında tutarlı hâle getirilmeli. |
| E11-05 | DEĞİŞTİR | P1 | `SERVIS_DEPO` rolü `13_kullanici_rol_yetki_entegrasyon.md`'de yok; orada da tanımlanmalı. Bu rol maliyet giremez (bkz. E11-22). Parça kartı açamaz, çünkü `urun.yaz` yalnız ADMIN ve SATIS_MUDURU'da var (bkz. E11-12). Birimi olmayan `KENDI_BIRIMI` kullanıcısı için depo kümesi boş olmalı. |
| E11-06 | DEĞİŞTİR | P1 | (a) **Kapalı işte `IADE_SERVIS` satırının ters kaydı fiilen yeni bir çıkıştır ve K3'ü deler;** 409 dönmeli. (b) `SAYIM_FAZLASI/EKSIGI` satırlarının ters kaydı yasak olmalı (düzeltme yeni sayımla yapılır). (c) Transfer bacağının ters kayıtları aynı `transfer_grup` değerini taşımalı. |
| E11-07 | DEĞİŞTİR | P1 | Açılış yüklemesi P1 kalır, ama: (a) Hepsi-ya-hiç kuralı profilin `yaz()` metodunda uygulanmalı: hatalı satır varsa `ValueError` fırlatılır, mevcut uç 409 döner ve geri alır. `api/imports.py` değişmez. (b) `yaz()` ve `dogrula()` kullanıcı nesnesi almıyor (`cekirdek.py:100-112`). Depo kapsamı için `yaz()` içinde `user_id` ile kullanıcı yüklenmeli ve `erisilebilir_depolar` kontrol edilmeli; yoksa KENDI_BIRIMI kullanıcısı başka birimin deposuna açılış yazar. (c) (Parça, depo) için önceden hareket varsa açılış reddedilmeli ve tekillik `uq_stok_hareket_acilis` ile sağlanmalı. (d) Mutabakat ucu ve uyarısı P3'e inmeli. |
| E11-08 | KABUL | P2 | Canlı uyarı kalıbına uygun (`uyarilar.py:47` `topla`, izne bağlı bloklar). |
| E11-09 | KABUL | P2 | Mobilite `StokPage` değişmiyor; form kalıbı canlıyla uyumlu. |
| E11-10 | KABUL | P2 | `stok_durumu` saf fonksiyon olmalı (`async` gereksiz). Ekran, filtre ve uyarı aynı depo kümesiyle aynı fonksiyonu kullanmalı. |
| E11-11 | KABUL | P2 | `qty Integer` kalıyor; Numeric'e genişletme ayrı madde. |
| E11-12 | DEĞİŞTİR | P2 | `urun.yaz` yalnız ADMIN ve SATIS_MUDURU'da; servis depo sorumlusu yeni parça kartı açamaz. `POST /api/teknik-servis/parca/kartlar` (`parca.yonet`) eklenmeli: kart `type='AKSESUAR'`, `identity_kind='YOK'`, `yedek_parca=true` ile açılır; yalnız kod, ad, marka, model, tedarikçi kodu, birim ve min. stok girilir; fiyat alanı yok. `birim` ve `min_stok` `UrunOut`'a eklenmeli ama `UrunIn/UrunPatch`'e eklenmemeli, yoksa `urun.yaz` ile bu alanlar `parca.yonet` atlanarak değiştirilebilir. Katalog PATCH mesajı iyileştirmesi isteğe bağlı. |
| E11-13 | DEĞİŞTİR | P2 | Kolonların yeniden kullanımı doğru. §4 tablosunda `notes≤500` yazıyor, K9 ise 300 diyor; 300 olmalı. `ix_stok_hareket_belge` (gin_trgm) P3 ya da isteğe bağlı; küçük tabloda ILIKE yeterli. |
| E11-14 | KABUL | P2 | Bileşen tekrar kullanımı doğru; K21 ile E04-21/E05-17 güncellemesi yerinde. |
| E11-15 | KABUL | P2 | Yeni uç kapsamlı. Canlı uçtaki sızıntı E11-D01'de ele alınıyor. |
| E11-16 | KABUL | P2 | İki bacaklı transfer ve aynı grup kimliği yeterli. Kilit sırası E11-01'deki ortak yardımcıdan gelir. |
| E11-17 | KABUL | P2 | Görüntü, onay ve açık sayım kilidi gerekli ve makul. `parca_sayim_degisim_toleransi` ayarı gereksiz; `degisimi_kabul` yeterli. Onayda sayım ürünleri sıralı kilitlenmeli. |
| E11-18 | DEĞİŞTİR | P2 | Net çıkış `-Σqty WHERE service_order_id IS NOT NULL` ile hesaplanmalı; ters kayıtlar kendiliğinden girer. Maliyeti NULL olan satır, E07'deki `MALIYET_EKSIK` anlamıyla "maliyet eksik" sayılmalı. E07 malzeme maliyeti ile bu rapor aynı fonksiyonu kullanmalı. |
| E11-19 | DEĞİŞTİR | P2 | Bekleme nedeni E01'deki `ck_hold_neden` değeri olan `MALZEME` olmalı. İş TAMAMLANDI olunca da (çıkış artık yasak olduğundan) talep IPTAL edilmeli ya da "parça geldi" uyarısından çıkarılmalı. KARSILANDI hesabında yalnız talep tarihinden sonraki çıkışlar sayılmalı. |
| E11-20 | DEĞİŞTİR | P2 | `hypothesis` yerine sabit tohumlu test yazılmalı. Eklenecek testler: E11-D01 (mobilite hareket listesi servis satırı içermez); ters sıralı iki çok satırlı çıkışın kilitlenmeden bitmesi; tetikleyicinin UPDATE ve DELETE'i reddetmesi; kapalı işte iade ters kaydının 409 dönmesi. |
| E11-21 | KABUL | P3 | Göç hareket üretmiyor, metin korunuyor. |
| E11-22 | DEĞİŞTİR | P2 | Tetikleyici E11-01'e taşınmalı. Depo adı ve tanımı E06 ucunun işi. Maliyet yazma yetkisi yeniden kurgulanmalı: `unit_cost` yalnız `parca.yonet` ile yazılabilsin; maliyet.gor yoksa değer yanıtta hiç dönmesin (yazma, görme sayılmaz) ya da maliyet satın alma mal kabulünden gelsin (E11-D02). K8'deki "hareketli ağırlıklı ortalama" net tanımlanmalı. Bakiye kolonu olmadığı için ya kümülatif ağırlıklı ortalama (Σ giriş adedi×maliyet / Σ giriş adedi, maliyetli girişler) seçilmeli ya da E07'deki "son mal kabul" yöntemi; iki modül tek yöntemde birleşmeli. |
| E11-23 | DEĞİŞTİR | P1 | (a) `SRV-MERKEZ` migration ya da üretim seed'i olarak yazılmamalı (uydurma veri). Yalnız dev seed'e girmeli; gerçek depolar `POST /depolar` ile açılmalı. (b) Teknisyen depo kümesi §3'te "kendi birim depoları + kendi araç deposu", kabulde "yalnız kendi araç deposu" deniyor; tek tanım seçilmeli (önerilen: §3). (c) Canlı `GET /api/stok/depolar` çıktısı servis depolarını da listeler. E11-D01'deki filtre burada da uygulanmalı. |

---

## 3. Eklenen maddeler

### E11-D01 · Canlı mobilite stok uçlarında servis defterinin sızması ve karışması · P1 · S
- **Canlı:**
  - `GET /api/stok/hareketler` (`api/stock.py:316-343`): izin `cihaz.gor`; kapsam, depo ve tür filtresi yok.
  - `StokPage.tsx:141` bu listeyi gösteriyor.
  - `denge_stogu` (`services/stock.py:255-263`) ve `_stok_adedi` (`api/catalog.py:130-136`) depodan bağımsız toplam alıyor.
  - `GET /api/stok/depolar` (`api/stock.py:361-371`) tüm aktif depoları listeliyor.
- **Yaklaşım:**
  - Hareketler ucuna `StockMovement.hareket_turu.is_(None)` filtresi eklenir; servis hareketleri yalnız E11-15 ucundan görülür.
  - `denge_stogu` ve `stok_adedi` için `elde` değeri değişmez (K1'deki "tek toplam" ilkesi korunur). Ek, opsiyonel bir `servis_deposunda` alanı servis depolarındaki adedi gösterir; mobilite ekranı "elde"nin bir kısmının servis deposunda olduğunu görür.
  - `/api/stok/depolar` uçu `servis_deposu=false` filtresini alır.
- **Kabul:** Servis çıkışından sonra `GET /api/stok/hareketler` yanıtında servis satırı yok. `GET /api/stok/ozet` için `elde` tek toplamdır ve `servis_deposunda` doğru. `test_stok_ozet` değişmeden yeşil. Servis depoları `/api/stok/depolar` listesinde yok.
- **Canlı risk:** Düşük. Yalnız filtre ve ek alan; servis satırı yokken çıktı birebir aynı.

### E11-D02 · Satın alma mal kabulünden serisiz parça girişi · P2 · M
- **Canlı:** `mal_kabul` (`services/purchasing.py:72-156`) `identity_kind='YOK'` ürünü reddediyor (`:130-133`). Satın alma siparişi `unit_price` ve kuru (`models/purchase.py:76-106`) tutuyor, ama serisiz kalem stoğa giremiyor.
- **Yaklaşım:** `mal_kabul`'e serisiz dal eklenir: `adet` parametresi alınır. Hedef depo servis deposuysa `parca.hareket_yaz(tur="GIRIS", document_no=receipt_no, unit_cost=unit_price×fx)` çağrılır, mobilite deposuysa `stock.stok_hareketi(reason="GIRIS")`. `qty_received` ilerletilir. Satın alma API'sinde gövdeye `adet` eklenir. Cihaz (IMEI/SERI_NO) dalı aynen kalır.
- **Kabul:** Serisiz kalemde 10 adet mal kabulden sonra servis deposu bakiyesi +10 olur, maliyet TL'ye çevrilmiş olarak dondurulur, `qty_received` 10'dur. IMEI dalının testleri değişmeden yeşil kalır. Kalan adetten fazlası 409 döner.
- **Canlı risk:** Düşük-orta. `purchasing.py` canlı bir akış; yalnız yeni `else` dalı açılır ve mevcut testlerle korunur.

### E11-D03 · E07 ile maliyet kolonu ve yönteminin tekleştirilmesi · P1 · S
- **Canlı:** Kolon yok. E07 `unit_cost_try Numeric(14,2)` ve "son mal kabul" yöntemini, E11 `unit_cost Numeric(14,4)` ve "hareketli ağırlıklı ortalama" yöntemini öneriyor.
- **Yaklaşım:** Tek ad (önerilen `unit_cost_try`, canlıdaki `landed_cost_try` ile tutarlı), tek tip (`Numeric(14,4)`) ve tek hesap fonksiyonu kullanılır (`services/teknik_servis/parca.py::birim_maliyet`; E07 bunu okur). Kolon, hangi modül önce gelirse onun migration'ında açılır ve öteki belgede "yalnız okur" yazılır. Maliyeti NULL olan satır her iki modülde de "maliyet eksik" sayılır.
- **Kabul:** İki belgede de aynı kolon adı ve tipi geçer. E07 malzeme toplamı ile E11-18 tutarı aynı iş için eşittir. `YASAK_ANAHTARLAR` testi bu kolonu kapsar.
- **Canlı risk:** Yok.

---

## 4. Kararların değerlendirmesi

- **K1, K2, K10, K11, K12, K13, K14, K16, K17, K18, K20, K21, K22: makul.** Canlı mimariye ve 00 §5'e uyuyor.
- **K3: makul**, ancak iade ters kaydı kapalı işte yasaklanmalı (E11-06).
- **K4, K5, K6: makul.** K5'teki bekleme nedeni `MALZEME` olmalı.
- **K7, K9: makul.** §4 tablosundaki `notes≤500` düzeltilmeli.
- **K8: belirsiz ve uygulanamaz durumda.** Maliyet girecek rol yok; yöntem E07 ile çelişiyor (E11-22, E11-D02, E11-D03).
- **K15: makul**, E06'nın işi.
- **K19: eksik.** Kilit sırası belirtilmemiş (E11-01) ve servis işi satırı kilitlenmiyor (E11-02).
- **Belgenin §12 "Dokunulmayanlar" listesi ile E11-D01 çelişiyor.** Canlı `GET /api/stok/*` uçlarına küçük filtreler eklenmesi zorunlu; aksi hâlde kapsam güvenliği deliniyor.
