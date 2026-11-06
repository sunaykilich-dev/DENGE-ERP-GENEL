# E07 Teklif ve İş Bazlı Maliyet: Bağımsız Denetim

> Tarih: 2026-10-21 · Denetlenen: `07_teklif_maliyet_entegrasyon.md` · Kaynak koda dokunulmadı, yalnızca okundu.
> Doğrulanan canlı dosyalar: `models/quote.py`, `api/quotes.py`, `services/quotes.py`, `api/public_quotes.py`, `services/statemachine.py`, `tests/unit/test_statemachine.py`, `permissions.py`, `tests/unit/test_permissions.py`, `services/mail.py`, `api/attachments.py`, `api/orders.py`, `models/order.py`, `models/stock.py`, `services/settings.py`, `services/reports.py`, `api/reports.py`, `services/uyarilar.py`.
> Çapraz kontrol için okunanlar: `00_MIMARI_KURALLAR.md`, `01_is_emirleri_entegrasyon.md` (§2.2, §2.5, §2.6, E01-06), `09_saha_zaman_entegrasyon.md` (§2.1), `11_yedek_parca_entegrasyon.md` (§2), `12_raporlama_entegrasyon.md`, `13_kullanici_rol_yetki_entegrasyon.md`.

## 1. Genel hüküm

Tasarımın canlı koda dair iddiaları büyük ölçüde doğru. Şunlar kodda doğrulandı:
- Sürümlü teklif, kalemde dondurulan fiyat ve KDV, iskonto eşiği (`services/quotes.py:32-68`).
- 50 satır sınırı (`api/quotes.py:174`).
- Kapsamsız tek kayıt uçları (`api/quotes.py:252-448`). Ek olarak `iskonto_onayla`, `teklif_pdf`, `gonder` ve `karar` uçları `is_deleted` kontrolü de yapmıyor (`:297, :322, :347, :424`).
- `MailKapali` mesajında sunucu adı ve port sızıyor (`services/mail.py:56-59`).
- `MAKINELER` içinde teklif makinesi yok (`statemachine.py:189-196`).
- `uyarilar.py` içinde teklif bloğu yok.
- `_kapsam` yalnız `accounts` için çalışıyor (`api/attachments.py:102`).
- `maliyet.gor` kümesi testle kilitli (`test_permissions.py:21-26`).

"YOK" denen şeyler (servis işi, tarife, iş geliri, gönderim günlüğü) canlıda gerçekten yok. Ayrı servis teklifi tablosu açmamak (K1) doğru karar. `ck_quote_durum` sapması (K2) da gerekçeli ve kabul edilebilir: `quotes` mobilite hak ediş zincirinde yer almıyor, değişiklik yalnız ekleme yapıyor. `work_orders`, `settlements`, `devices`, IMEI kuralı ve EXCLUDE kısıtlarına hiç yazılmıyor; mobilite akışı bozulmuyor.

Tasarımın zayıf yanı canlı satış kodu değil. Sorun üç yerde toplanıyor: **(a)** birimli teklifin mevcut satış uçlarından açık kalan yan kapıları, **(b)** önkoşul modüllerle (E01, E09, E11, E13) ad ve kolon çakışmaları, **(c)** birimli tekliflerin mevcut satış rapor ve panel sayılarına sızması. Tasarım bu üçüncüsünü "dokunulmayan" sayıyor, ama kod öyle olmadığını gösteriyor.

| # | Bulgu | Kanıt | Etki / düzeltme |
|---|---|---|---|
| B1 | **Public link revize edilmiş ve iptal edilmiş teklifte karar kabul ediyor.** `_karar_verilebilir` yalnız sürümdeki karar ve süre alanlarına ve 4 duruma bakıyor. Sürümün güncel sürüm olup olmadığına bakmıyor; `IPTAL`, `TASLAK`, `ONAY_BEKLIYOR` ve `ONAYLANDI` durumlarını da engellemiyor. R0 gönderildikten sonra R1 açılırsa, R0'ın jetonu (`sent_at` dolu, kilitli) hâlâ "kabul" alıyor ve `karar_ver` teklifi KABUL yapıyor. Oysa güncel sürüm R1. | `api/public_quotes.py:76-83, 148-165`; `services/quotes.py:233-236`; `api/quotes.py:252-278` | Birimli teklifte müşteri onaysız bir R1 varken eski R0'ı kabul edebilir. Ardından E07-16 geliri R1'in kalemlerinden aktarır, IPTAL edilmiş teklif de linkten yeniden KABUL olur. Aynı açık satışta da var: `orders.tekliften` güncel sürümü kullanıyor, müşteri ise R0 fiyatını kabul etmiş oluyor. Eklenen madde **E07-D01**. |
| B2 | **Birimli teklif mevcut satış uçlarından makineyi atlayabiliyor.** `iskonto_onayla` `ONAY_BEKLIYOR → TASLAK` geçişini doğrudan atıyor. `SATIS_MUDURU` (`teklif.iskonto_onayla`, TUMU) bu yolla servis teklifinin iç onayını yok sayabilir. `gonder` eşik aşıldığında `status='ONAY_BEKLIYOR'` atayıp commit ediyor. `revize_et` her zaman `REVIZE_EDILDI` yazıyor. | `api/quotes.py:293-317, 352-354, 278` | E07-04 yalnız `gonder` ve `karar` uçlarına birimli dal ekliyor. `iskonto-onayla` ucu birimli teklifte 409 ("iç onayı kullanın") vermeli. `gonder` önce onay kuralını denetlemeli, iskonto dalına hiç girmemeli. `revize_et` de birimli dala (TASLAK) yönlenmeli. |
| B3 | **Birimli teklifler satış KPI'larına karışıyor.** Panelin "bekleyen teklif" sayısı ve `teklif_donusumu` `birim` süzgeci olmadan tüm teklifleri sayıyor. `SATIS_MUDURU` ile `MUHASEBE_DESTEK` (TUMU) teklif listesinde servis tekliflerini de görecek. | `services/reports.py:85-96, 135-181`; `api/reports.py:57-61`; `api/quotes.py:168-184` | Tasarımın "satış akışı aynen" iddiası rapor tarafında tutmuyor. Mevcut panel ve dönüşüm sorgularına varsayılan `birim IS NULL` eklenmeli, servis kırılımı ayrı verilmeli. Ön yüzde liste için Birim kolonu ve "Satış / Servis" süzgeci gerekiyor. Eklenen madde **E07-D02**. |
| B4 | **Alanlar arası yazma yetkisi tanımsız.** K23 yalnız "SERVIS_YONETICI satış tekliflerini salt görür" diyor. Oysa rolün `teklif.yaz` izni ve TUMU kapsamı var; bu haliyle satış tekliflerini revize edebilir, gönderebilir ve karara bağlayabilir. Tersine `SATIS_MUDURU` da servis tekliflerini yazabilir, kabul ettirip iş gelirine (E07-16) dokunabilir. | `permissions.py:114-140`; tasarım §1.5, K23 | `teklif_yazilabilir_mi(user, t)` yardımcısı eklenmeli. Birimli teklife yazmak için kullanıcının bir servis rolünde olması ya da o birime üye olması gerekir. Birimsiz teklife yazmak için servis rolü yetmez. Her iki tarafta kapsam dışı yazma 404 döner. Bu kural E07-02'ye eklenir. |
| B5 | **Yedek parça maliyet kolonu E11 ile çakışıyor.** E07 `stock_movements.unit_cost_try Numeric(14,2)` kolonunu açıyor ve değerini "son mal kabul × kur, yoksa `landed_cost_try`" ile buluyor. E11 ise aynı tabloya `unit_cost Numeric(14,4)` açıyor ve değeri servis depolarındaki girişlerin hareketli ağırlıklı ortalamasından dondurıyor. E11'de `CIKIS_SERVIS`, `IADE_SERVIS` ve ters kayıt da var. | `11_yedek_parca_entegrasyon.md:47, 68, 152, 269` | İki kolon ve iki farklı maliyet kuralı oluşur. "Hangi migration önce gelirse açar" kuralı ad farkı yüzünden işlemez. E07, E11'in `unit_cost` kolonunu ve kuralını yeniden kullanmalı. Malzeme maliyeti net çıkışla (iade ve ters kayıt düşülerek) hesaplanmalı. |
| B6 | **Bekleme modeli E01 ile çelişiyor.** E01'de bekleme nedeni zaten `TEKLIF`. `TEKLIF_SUNULACAK` sonucu bu beklemeyi kendiliğinden açıyor. `uq_hold_aktif` kısıtı işte tek aktif bekleme olmasını zorluyor. E07 ise yeni `TEKLIF_ONAYI` nedeni ve ikinci bir bekleme açmayı öneriyor. Kabul 3'teki "MALZEME beklemesi açıkken teklif beklemesi de var" senaryosu şemada mümkün değil. | `01_is_emirleri_entegrasyon.md:126-134, 451, 463` | `TEKLIF_ONAYI` açılmaz, E01'in `TEKLIF` nedeni kullanılır. `beklet=True` ise E01 akışıyla açılmış aktif `TEKLIF` beklemesine `quote_id` yazılır; aktif bekleme yoksa E01 `beklet()` fonksiyonuyla yeni bekleme açılır. Kabul 3 şöyle düzeltilir: "başka nedenli aktif bekleme varken teklif beklemesi açılmaz ve yanıtta uyarı döner". |
| B7 | **Zaman kaydı sözlüğü E09 ile uyuşmuyor.** K22 "YOL, ISCILIK, BEKLEME" diyor. E09'un faaliyet listesi ise `YOL, SAHA, BEKLEME, MOLA, UZAKTAN, ATOLYE, TEST, DIGER`. E09 ayrıca `KISI_SAATE_DAHIL` kümesini ve `kisi_saat_dk` yardımcısını tanımlıyor (iptal edilmemiş, kapalı bölümler). E07 ise `is_deleted` ile kendi toplamını yazıyor. | `09_saha_zaman_entegrasyon.md:67, 99, 135` | `iscilik_hesapla`, E09'un `KISI_SAATE_DAHIL` kümesini ve iptal/açık bölüm kuralını yeniden kullanmalı. Açık bölümü (`ended_at IS NULL`) olan iş `SURE_EKSIK` sayılır. |
| B8 | **Tarife kapatma kuralı kendi CHECK'iyle çelişiyor.** §1.2 "hatalı ileri tarihli satır `valid_to = valid_from` yapılarak kapatılır" diyor. Ancak `ck_iscilik_tarife_aralik` kısıtı `valid_to > valid_from` istiyor. `tarife_ekle` de yeni `valid_from` değeri açık satırın başlangıcına eşit ya da ondan önceyse aynı kısıta takılır. | tasarım §1.2, E07-20 | Kısıt `valid_to >= valid_from` yapılmalı. `daterange('[)')` ile eşit sınırlı aralık boştur ve EXCLUDE ile çakışmaz; emsali `models/workorder.py:213-235` kalıbıdır. Başlangıcı açık satırdan önce olan yeni tarife 409 döner. |
| B9 | **500 karakterlik açıklama satış siparişini kırar.** `KalemIn` teklif ve siparişte ortak (`kalem_alanlari`). `order_lines.description` ise `String(300)`. Satış teklifine 400 karakterlik açıklama girilip siparişe dönüştürülürse `DataError` oluşur (422/500). | `models/order.py:121`; `api/orders.py:26, 209, 342` | Genişletme ya yalnız birimli teklif kalemine uygulanmalı (satışta 300 korunur) ya da `order_lines.description` de aynı migration'da 500'e çıkarılmalı. Önerilen: yalnız birimli teklif. Birimli teklif siparişe zaten dönüşmüyor (K17). |
| B10 | **Faturaya iletilmiş işin geliri değişebiliyor.** KABUL → IPTAL, ikinci kabul, `gelir_aktar` ve `PUT /gelir` uçları `fatura_iletildi_at` alanını denetlemiyor. Muhasebeye devredilmiş tutar sessizce değişebilir. | tasarım E07-16, E07-26 | Eklenen madde **E07-D04**. |
| B11 | **`maliyet.yaz` E13'te korunmuyor.** E13 `VEKALETE_KAPALI` kümesinde `maliyet.gor` var, `maliyet.yaz` yok. Erişim gözden geçirmedeki "hassas izin" KPI'ı da yeni izni kapsamıyor. Oysa K5 ve K21 maliyet yetkisini kişi bazlı istisnaya bağlıyor. | `13_kullanici_rol_yetki_entegrasyon.md:182, 559, 604` | Eklenen madde **E07-D03**. |
| B12 | **Ad ve kapsam uyumsuzlukları.** `quotes.birim String(12)`, ama E01 ve `user_units` `String(20)` kullanıyor. Tasarım `SERVIS_TEKNISYEN` kapsamını KENDI_BIRIMI sayıyor; E13'e göre `KENDI_ISLERI`. `teklif_kapsami` yalnız TUMU, KENDI_MUSTERILERI ve KENDI_BIRIMI değerlerini işliyor; bilinmeyen kapsamın ne olacağı tanımsız. | `01_...:63, 71`; `13_...:201` | `String(20)` kullanılmalı. `teklif_kapsami` bilinmeyen kapsamda **reddetmeli** (`false()`). `UserPermission` ile `teklif.gor` alan bir `KENDI_ISLERI` kullanıcısı tüm teklifleri görmemeli. Eklenen madde **E07-D05**. |

Diğer gözlemler:

- **TEKLIF makinesi sadeleşmeli.** Makine yalnız birimli teklifte zorlanıyor, ama satış durumlarını da taşıyor. `KABUL→SIPARISE_DONUSTU` geçişi K17'yle çelişiyor. `REVIZE_EDILDI` ve `SURESI_DOLDU` durumları birimli teklifte hiç yazılmıyor (K7). Önerilen makine:
  ```
  TASLAK → ONAY_BEKLIYOR | IPTAL
  ONAY_BEKLIYOR → TASLAK | ONAYLANDI | IPTAL
  ONAYLANDI → GONDERILDI | TASLAK | IPTAL
  GONDERILDI → GORUNTULENDI | KABUL | RED | TASLAK | IPTAL
  GORUNTULENDI → KABUL | RED | TASLAK | IPTAL
  RED → TASLAK
  KABUL → IPTAL
  IPTAL → (terminal)
  ```
  Bu makine meta-testten (`test_statemachine.py:10-33`) geçer: her durum ulaşılabilir, `IPTAL` terminaldir.
- **Satış uçlarına "doğrulamasız `durum_degistir`" eklenmemeli.** Tasarım 8 canlı çağrı noktasına (satış uçları, `orders`, `public_quotes`) dokunmayı öneriyor. Bunlar zaten audit yazıyor. `GET /gecmis` mevcut audit eylemlerini (`olustur, revize, gonder, karar, iskonto.onayla, goruntulendi`) ve yeni `durum` eylemini birlikte okuyarak aynı zaman çizelgesini üretebilir. Böylece satış kodu değişmeden kalır ve canlı risk düşer.
- **İyimser kilit eksik (E07-13).** `PUT` ile kalemler değişince `Quote` satırı güncellenmiyor; `version_id` artmadığı için kilit işlemez. `PUT` aynı zamanda teklif başlığını (en az `updated_at`/`updated_by`) yazmalı ki sürüm artsın. `QuoteVersion` tablosunda `VersionedMixin` yok.
- **PB işine teklif geliri (E07-16 ile K9).** Bakım bulgusundan doğan teklif kalem bazında PB işine bağlanıyor. Kabulde gelir de PB işine yazılıyor. Bu durumda işin gelir durumu `SOZLESME_KAPSAMI` olmaktan çıkıp `TEKLIF` oluyor ve bakım ziyaretinin işçiliği, henüz yapılmamış düzeltici işin geliriyle karşılaştırılıyor. Önerilen: kabul edilen bulgu teklifi için düzeltici servis işi açılır (`iliskili_is_id=PB`, `iliski_turu='DEVAM'`, E01) ve gelir o işe aktarılır. PB işi yalnız teklifin kaynağı olarak kalır. Bu yapılmayacaksa analizde PB işinin TEKLIF geliri ayrı sayaçta gösterilmeli.
- **Yuvarlama siparişi de etkiler (E07-03).** `kalem_alanlari` sipariş kalemleriyle ortak. 2 hane yuvarlama sipariş toplamlarını da (aynı kuruş farkıyla) hizalar. Canlı risk notuna sipariş de yazılmalı ve `test_siparis*` testleri koşturulmalı.
- **E07-19 öncelik ve sıra.** E07-19 aslında canlı bir hata (51. teklife ulaşılamıyor). E07-02'nin "X-Toplam-Kayit" kabulü ve E07-18 de buna bağlı. P3 değil P2 olmalı ve E07-02 ile aynı PR'da gelmeli.
- **Aşırı mühendislik değerlendirmesi.** `quote_sends` (K16) gerekçeli; başarısız deneme ve hız sınırı sorgusu `audit_logs` üzerinden zor yapılır. `service_order_financials` tablosunun 1:1 ayrı tutulması da doğru: maliyet hassas alanları `service_orders` çıktısından yapısal olarak ayrılmış olur. Dakikada 10 hız sınırı (E07-25), iç ağda ve kimlik doğrulamalı bir sistemde düşük değerli; P3 ve "sıkılaştırma" adımında kalması yeterli. E07-23'teki "tüm GET rotalarını gez" testi değerli, ama yasak anahtar listesi fazla genel (aşağıya bakın).

## 2. Madde hükümleri

| Madde | Hüküm | Öncelik | Gerekçe / düzeltme |
|---|---|---|---|
| E07-01 | KABUL | P3 | Canlıda var (`deps.py:79-97`); kod değişikliği yok. Parametrik 403 testi E07-23'e taşınır. P1 olması gerekmez. |
| E07-02 | DEĞİŞTİR | P1 | B4 ve B12. `teklif_kapsami` bilinmeyen kapsamda reddeder. Yazma için `teklif_yazilabilir_mi` (birimli ↔ servis rolü/birim, birimsiz ↔ servis dışı rol). `_teklif_al` canlıda eksik olan `is_deleted` kontrolünü de yapar. Kabul 3 `sayfala` gerektirir, bu yüzden E07-19 aynı PR'a alınır. |
| E07-03 | DEĞİŞTİR | P1 | B9. 500 karakter yalnız birimli teklif kaleminde geçerli (servis katmanında denetlenir); satış şeması 300'de kalır. Yuvarlamanın sipariş kalemlerine de etkisi canlı risk notuna yazılır, sipariş testleri koşturulur. |
| E07-04 | DEĞİŞTİR | P1 | B1, B2 ve yukarıdaki makine önerisi. Birimli teklifte `iskonto-onayla` 409, `gonder` önce onay kuralına bakar, `revize_et` TASLAK'a döner. Satış uçlarına `durum_degistir` eklenmez; `gecmis` mevcut audit eylemlerini birlikte okur. `KABUL→SIPARISE_DONUSTU` makineden çıkar. KABUL'den IPTAL'e geçişte E07-D04 kilidi uygulanır. |
| E07-05 | DEĞİŞTİR | P1 | `elle-gonderildi` satış teklifinde de kullanılabileceği için, `gonder` ucundaki iskonto onay kuralını (`onay_gerekiyor_mu` ve `discount_approved_at`) aynen uygulamalı; aksi halde iskonto onayını atlamanın yeni bir yolu açılır. Public link kararı E07-D01 kuralıyla sınırlanır. |
| E07-06 | KABUL | P2 | Geriye uyumlu `mail.gonder` genişlemesi ve `quote_sends` makul. Öneri: G4 sızıntısı `mail.py` içinde, kaynağında düzeltilirse hak ediş de korunur. Ayrıntı log'a yazılır, mesaj genel olur. Bu tek satırlık bir değişiklik ve hak ediş akışını bozmaz. |
| E07-07 | DEĞİŞTİR | P1 | B9: 500 karakterlik açıklama yalnız birimli teklifte; şablondaki sayfa numarası ve `overflow-wrap` değişikliği ortak kalır. Bir uyarı: `@page { margin: 0 }` canlı yerleşimde kasıtlı. Alt kenar boşluğu değişince satış PDF'inin altın görüntüsü (varsa) güncellenmeli. |
| E07-08 | KABUL | P2 | Bağlam sözlüğüne yalnız ekleme yapılıyor; onaylayan alanı yalnız doluysa basılıyor. |
| E07-09 | KABUL | P3 | Ucuz ve yerinde. |
| E07-10 | DEĞİŞTİR | P1 | B5 ve B7. `unit_cost_try` açılmaz; E11'in `unit_cost` kolonu ve kuralı kullanılır. Malzeme maliyeti net çıkışla (`CIKIS_SERVIS − IADE_SERVIS`, ters kayıtlar dahil) hesaplanır. Süre E09'un `KISI_SAATE_DAHIL` ve iptal kurallarıyla alınır; açık bölüm varsa `SURE_EKSIK`. |
| E07-11 | DEĞİŞTİR | P1 | B7: faaliyet adları E09'dan alınır. Tarife, bölümün yerel başlangıç tarihinde geçerli olan tarifedir; mantık doğru. Uyarı bloğu birim kapsamlı olmalı. |
| E07-12 | KABUL | P1 | NULL ≠ 0 ayrımı, CHECK'ler ve 1:1 ayrı tablo doğru. Gelir yazmalarına E07-D04 kilidi eklenir. |
| E07-13 | DEĞİŞTİR | P2 | İyimser kilit için `PUT` teklif başlığını da yazmalı ki `version_id` artsın. Birimli revize TASLAK'a döner; satış revize akışı aynen kalır. |
| E07-14 | DEĞİŞTİR | P2 | B6: E01'in `TEKLIF` bekleme nedeni ve `beklet/beklemeyi_bitir` fonksiyonları kullanılır; aktif TEKLIF beklemesine `quote_id` yazılır. Kabul 3 düzeltilir (tek aktif bekleme). E04'teki `linked_quote_id` ile çift yönlü tutarlılık yazılmalı. |
| E07-15 | DEĞİŞTİR | P2 | E01, TEKLIF_SUNULACAK sonucunda TEKLIF beklemesi açıyor. Uyarı `service_results` tarihinden değil, "aktif TEKLIF beklemesi var, `quote_id` boş ve N iş günü geçmiş" ölçütünden üretilir. Sorgu sadeleşir, iki kaynak oluşmaz. |
| E07-16 | DEĞİŞTİR | P2 | PB işine gelir yazmak K9'la çelişiyor; öneri yukarıda (düzeltici iş). E07-D04 kilidi ve E07-D01 güncel sürüm kuralı eklenir. Public linkte kullanıcı yoktur; audit satırı `user_id=None` ve `kanal='LINK'` ile yazılır. |
| E07-17 | KABUL | P2 | `audit.log_change` kullanılıyor, ayrı tablo yok; doğru. |
| E07-18 | KABUL | P2 | E07-19 ile birlikte gelir. `ozet` sayıları ile Excel aynı filtre ifadesini kullanmalı; tasarım bunu zaten öngörüyor. |
| E07-19 | DEĞİŞTİR | P2 | Önceliği P3'ten P2'ye çıkar (canlı hata, E07-02 kabulünün önkoşulu). İndeks kolonu `birim String(20)`. |
| E07-20 | DEĞİŞTİR | P2 | B8: `ck_iscilik_tarife_aralik` kısıtı `valid_to >= valid_from` olur; başlangıcı açık satırdan önce olan yeni tarife 409 döner. Geçmiş tarihli giriş `sistem.ayar` + gerekçe ister. Kapatılmış dönemin analizinin geriye dönük değişebileceği tarife ekranında uyarı olarak yazılmalı. |
| E07-21 | KABUL | P2 | Tek kaynak (`is_finansi`) ve dönem sınırı makul. Menü kalemi `maliyet.gor` ile `rapor.gor` izinlerinin ikisini birden istemeli; aksi halde istisnayla `maliyet.gor` alan kişi menüyü görür ama 403 alır. |
| E07-22 | KABUL | P3 | Canlı xlsx kalıbı kullanılıyor. |
| E07-23 | DEĞİŞTİR | P2 | `YASAK_ANAHTARLAR` fazla genel: `malzeme`, `diger` ve `gelir` meşru alan adlarıyla çakışır (ör. E11 iş detayındaki parça listesi). Bu yanlış alarm üretir ya da beyaz listeyi şişirir. Daha belirli anahtarlar kullanılmalı: `iscilik_tutari`, `malzeme_maliyeti`, `diger_maliyet`, `gelir`, `fark`, `hourly_cost`, `unit_cost`, `landed_cost_try`, `grand_total`, `subtotal`, `unit_price`, `line_total`, `vat_total`. Bir uyarı: canlı `_maliyet_gizle` anahtarı `None` yapıyor (E12 K12); test anahtarın varlığını aramalı. |
| E07-24 | DEĞİŞTİR | P3 | B3. Satış dönüşüm oranının anlamı değişmez: `etkin_durum` yalnız birimli tekliflere uygulanır, varsayılan çağrı `birim IS NULL` (satış) olarak kalır. Servis dönüşümü `birim` parametresiyle ayrı istenir. Böylece K7 ile tutarlı olunur (satış verisi sessizce değişmez). |
| E07-25 | KABUL | P3 | Sır yönetimi zaten canlıda var. Hız sınırı düşük değerli ama ucuz; sıkılaştırma adımında yapılır. |
| E07-26 | KABUL | P3 | Mevcut `tahsilat.*` izinlerinin yeniden kullanılması makul (K6). İşaretleme E07-D04 kilidini başlatır. |

## 3. Eklenen maddeler

### E07-D01 · Public link ve elle kararda yalnız güncel ve karar verilebilir sürüm — P1 · S
- **Canlı durum: KISMEN.** `api/public_quotes.py:76-83` sürümün güncel olup olmadığına bakmıyor; `IPTAL`, `TASLAK`, `ONAY_BEKLIYOR` ve `ONAYLANDI` durumlarını engellemiyor. Elle `karar` ucu (`api/quotes.py:415-448`) da durumu hiç denetlemiyor.
- **Yaklaşım:**
  - `_karar_verilebilir` iki koşul daha alır: `v.id == t.current_version_id` ve `t.status in ("GONDERILDI","GORUNTULENDI","REVIZE_EDILDI")`.
  - Eski sürümün jetonuyla `goruntule` okumaya açık kalır, ama yanıta "Bu teklifin güncel bir sürümü var" uyarısı eklenir ve `karar_verilebilir=false` döner.
  - Birimli teklifte elle `karar`, `TEKLIF.dogrula` ile birlikte etkin süre kontrolü de yapar.
  - Satış teklifine de uygulanması önerilir: eski sürüm kabulü canlıda bir veri tutarsızlığı. Sürüm notunda belirtilir.
- **Kabul:**
  1. R1 açıldıktan sonra R0 jetonuyla karar 409 döner, teklif durumu değişmez.
  2. IPTAL edilmiş teklifin jetonuyla karar 409 döner.
  3. Birimli teklif TASLAK'a geri çevrildikten sonra eski jetonla karar 409 döner.
  4. `test_teklif.py` yeşil kalır.
- **Dokunulan:** `api/public_quotes.py`, `api/quotes.py`, `tests/integration/test_servis_teklif_akisi.py`.
- **Canlı risk:** Düşük. Satışta yalnız eski sürümün kabulü kapanır; güncel sürüm akışı değişmez.

### E07-D02 · Mevcut satış panel, rapor ve listesinin birimli tekliflerden ayrılması — P1 · S
- **Canlı durum: YOK.** `services/reports.py:85-96` (panel), `:135-181` (dönüşüm) ve `api/quotes.py:168-184` (liste) birim ayrımı yapmıyor.
- **Yaklaşım:**
  - Panel ve `teklif_donusumu` varsayılan olarak `Quote.birim.is_(None)` ile süzülür. Servis teklifleri için ayrı kırılım ya da `birim` parametresi kullanılır.
  - Teklif listesinde `tur=SATIS|SERVIS` süzgeci ve Birim kolonu eklenir.
  - Ön yüzde satış rolleri için varsayılan süzgeç SATIS'tir.
- **Kabul:**
  1. Birimli 5 teklif eklendikten sonra panelin "bekleyen teklif" sayısı ve satış dönüşüm oranı değişmez.
  2. `?tur=SERVIS` yalnız birimli teklifleri döndürür.
- **Dokunulan:** `services/reports.py`, `api/reports.py`, `api/quotes.py`, `pages/TekliflerPage.tsx`, `tests/integration/test_raporlar.py`.
- **Canlı risk:** Yok. Bu madde canlı sayıları korumak içindir.

### E07-D03 · `maliyet.yaz` iznini vekâlete kapatma ve erişim gözden geçirmesine dahil etme — P2 · S
- **Canlı durum: YOK.** E13 tasarımında `VEKALETE_KAPALI` kümesi `maliyet.gor` içeriyor, `maliyet.yaz` içermiyor (`13_...:182, 604`).
- **Yaklaşım:**
  - `maliyet.yaz` ve `teklif.onayla` `VEKALETE_KAPALI` kümesine eklenir. Öz-onay yasağı vekâletle delinmemeli.
  - `erisim-gozden-gecirme` uçundaki `hassas_izin` KPI'ı `maliyet.yaz` iznini de kapsar.
  - `UserPermission` istisnasında gerekçe zorunlu olmaya devam eder.
- **Kabul:**
  1. `maliyet.yaz` ya da `teklif.onayla` vekâleti 403 döner.
  2. Bu istisnaya sahip kullanıcı "hassas izin" listesinde görünür.
- **Dokunulan:** `permissions.py` (E13 sabitleri), E13 servis dosyası, `tests/unit/test_permissions.py`.
- **Canlı risk:** Yok.

### E07-D04 · "Faturaya iletildi" sonrası gelir kilidi — P2 · S
- **Canlı durum: YOK.**
- **Yaklaşım:** `service_order_financials.fatura_iletildi_at` doluysa şu işlemler 409 döner: `PUT /gelir`, `PUT /diger-maliyet`, `gelir_aktar` (ikinci kabul ya da iptal kaynaklı) ve bağlı teklifin `KABUL→IPTAL` geçişi. Mesaj: "İş faturaya iletildi; önce devri geri alın". Devri geri alma (`/geri-al`, `tahsilat.yaz`, gerekçe zorunlu) kilidi açar ve audit kaydı yazar.
- **Kabul:**
  1. İletilmiş işte gelir PUT isteği 409 döner, `db.refresh` sonrası değer aynıdır.
  2. Bağlı teklifin iptali 409 döner.
  3. Geri alma sonrası aynı istek 200 döner ve geçmişte üç olay görünür.
- **Dokunulan:** `services/teknik_servis/maliyet.py`, `services/quotes.py`, `api/servis_maliyet.py`, `tests/integration/test_servis_maliyet.py`.
- **Canlı risk:** Yok.

### E07-D05 · Önkoşul modüllerle ad ve kolon hizalaması (migration öncesi kapı) — P1 · S
- **Canlı durum: YOK** (tasarım belgeleri arasında).
- **Yaklaşım:** Migration yazılmadan önce aşağıdaki eşlemeler sabitlenir:
  - `stock_movements.unit_cost` (E11; `unit_cost_try` açılmaz);
  - `service_holds.neden='TEKLIF'` (E01; `TEKLIF_ONAYI` açılmaz) ve yalnız nullable `service_holds.quote_id` eklenir;
  - `quotes.birim String(20)` ve `ck_quote_birim` E01 `BIRIMLER` ile aynı;
  - zaman faaliyetleri E09 `ZAMAN_FAALIYETLERI` ve `KISI_SAATE_DAHIL` kümesinden;
  - `SERVIS_TEKNISYEN` kapsamı E13'teki `KENDI_ISLERI`; `teklif_kapsami` bilinmeyen kapsamı reddeder;
  - E04 `linked_quote_id` ile `quote_lines.service_order_id` arasındaki tutarlılık.

  Bu eşlemeler için `tests/unit/test_servis_sozluk_tutarliligi.py` yazılır: Python demetlerini karşılaştırır.
- **Kabul:**
  1. Sözlük testi yeşildir.
  2. `alembic upgrade head` sonrasında `stock_movements` tablosunda tek maliyet kolonu vardır.
  3. head→base→head yeşildir.
- **Dokunulan:** `alembic/versions/<rev>_servis_teklif_maliyet.py`, `models/quote.py`, `services/teknik_servis/maliyet.py`, `tests/unit/test_servis_sozluk_tutarliligi.py`.
- **Canlı risk:** Yok. Önlenen risk, iki maliyet kolonu ve iki bekleme nedeni oluşması.

## 4. Kararlar hakkında

- **K1, K3, K6, K11, K14, K15, K16, K17, K18, K19, K20 ve K24 makul.** Canlı varlıklar yeniden kullanılıyor.
- **K2 kabul edilebilir.** Sapma `00_MIMARI_KURALLAR.md` §2'ye "onaylı istisna" olarak işlenmeli. Migration testine "mevcut tüm satırlar yeni kısıtı geçer" ve "downgrade eşlemesi" kontrolleri eklenmeli.
- **K4 doğru**, ama B2 uygulanmadan geçerli değil: `iskonto-onayla` yan kapısı açık kalırsa tek kademeli onay delinir.
- **K5 doğru.** E07-D03 ile tamamlanır.
- **K7 doğru**, ama E07-24'ün satış oranını değiştirmesi K7'nin ruhuna aykırı. Bkz. E07-24 hükmü.
- **K9 ile E07-16 çelişiyor.** Önerilen çözüm düzeltici iş (yukarıda).
- **K10 doğru**, B8 düzeltmesiyle.
- **K12 ve K13 makul.**
- **K21 doğru**, E07-D04 kilidiyle tamamlanır.
- **K22'deki faaliyet adları E09'la hizalanmalı** (B7).
- **K23 eksik.** "Salt görme", izinler (`teklif.yaz` + TUMU) tarafından desteklenmiyor. B4'teki yazma ayrımı karara eklenmeli.
