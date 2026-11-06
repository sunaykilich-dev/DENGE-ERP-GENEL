# E12 Teknik Servis Raporları ve KPI: Bağımsız Denetim

> Tarih: 2026-10-21 · Denetlenen belge: `12_raporlama_entegrasyon.md`. Kaynak koda dokunulmadı, kod yalnızca okundu.
> Doğrulanan canlı dosyalar: `api/reports.py`, `services/reports.py` (dashboard, musteri_geliri, teklif_donusumu), `services/export.py`, `api/deps.py`, `permissions.py`, `services/audit.py`, `services/kvkk.py:40-65`, `api/kvkk.py:54-112`, `services/accounts.py:11-106`, `services/uyarilar.py:1-110`, `services/settings.py:25-130`, `models/account.py:163-196`, `main.py` (hata eşleyiciler ve router kaydı), `config.py`, `frontend/src/components/AppLayout.tsx`, `tests/conftest.py:38-122`, `tests/unit/test_permissions.py`, `pyproject.toml`.
> Çapraz okunanlar: `00_MIMARI_KURALLAR.md`, E01, E04, E05 (+ kontrol), E09, E10, E14 entegrasyon belgeleri, `02_moduller/_ozet/12_raporlama.json`.

## 1. Genel hüküm

Canlı kodla ilgili iddialar doğru. Doğrulananlar şunlar:

- JSON ve xlsx aynı servis fonksiyonundan üretiliyor (`api/reports.py:1-6, 33-38`).
- Formül enjeksiyonu koruması var (`export.py:26-42`), Excel üretimi ayrı iş parçacığında çalışıyor (`export.py:45-54`).
- `require_permission(*codes)` verilen kodların hepsini istiyor (`deps.py:79-97`).
- `sayfala` toplamı `X-Toplam-Kayit` başlığına yazıyor (`deps.py:170-190`).
- `audit.log(..., is_personal_data)` var (`audit.py:26-52`) ve KVKK erişim logu bu bayrağa göre okunuyor (`kvkk.py:79, 326`).
- Hiçbir mobilite `.xlsx` ucu denetim izine yazmıyor.
- `_maliyet_gizle` alanı silmiyor, `None` yapıyor (`reports.py:41-45`).
- `rapor.personel` `.gor` ile bitmediği için YONETIM'e otomatik inmiyor (`permissions.py:84, 247`).

Mobilite akışı da korunuyor. `work_orders`, `settlements`, `devices`, EXCLUDE kısıtları ve IMEI kuralı okunmuyor da yazılmıyor da. Canlı tabloya yapılan tek değişiklik, henüz var olmayan E01 tablosuna eklenen nullable `first_completed_at` kolonu.

**Asıl sorun kardeş tasarımlarla çakışma.** E12 kendini "tek KPI/rapor motoru" olarak tanımlıyor. Oysa aynı şeyleri E01, E09, E10 ve E14 zaten tasarlamış ve E12 bunları görmeden kendi kopyasını yazıyor. Bu hâliyle kodlanırsa M12'nin çözmeye çalıştığı "ekran A, Excel B diyor" sorunu bu kez modüller arasında yeniden doğar. Ayrıca E12, E10'un gerçek alan adlarını kullanmıyor; E01'deki yer tutucu adlarla yazılmış.

### 1.1 Bulgular

| # | Bulgu | Kanıt | Etki / düzeltme |
|---|---|---|---|
| B1 | **KPI kayıt defteri ikinci kez tanımlanıyor.** E01-14 `services/teknik_servis/panel.py` içinde `KPI_TANIMLARI` (sayı ve liste aynı filtreden) ve `DURUM_GRUPLARI` (E01-03) tanımlıyor. E10-08 "Operasyon Merkezi sayaçları E01-14 `KPI_TANIMLARI` kaydına eklenir" diyor (E10 K15). E12 ise `rapor_tanimlari.KPI_TANIMLARI` ve `models.SERVIS_DURUM_GRUPLARI` açıyor. | `01_...:376, 632-678`; `10_...:258, 409` | İki kayıt defteri, iki durum grubu sözlüğü oluşur. Düzeltme: E12, E01-14 kaydını **genişletir** (`tanim`, `birim`, `kisisel`, `kategori_ayri` alanları eklenir); E01-03'ün `DURUM_GRUPLARI` sözlüğüne rapor grubu eşlemesi (ACIK/COZULDU/IPTAL) eklenir; yeni sözlük açılmaz. |
| B2 | **Çok sayfalı Excel yazıcısı ikinci kez tanımlanıyor.** E01-15, `export.py`'ye `sayfalari_xlsx_async` ekliyor; E09-14 ve E10-07 bunu kullanıyor. E12 ise `rapor_excel.tipli_sayfa` açıyor ve özel `_formulu_metne_cevir` fonksiyonunu modül dışından içe aktarıyor. | `01_...:689-692`; `09_...:553`; `10_...:394`; `export.py:26` | Düzeltme: sütun şeması (METIN/TARIH/...) E01-15'in `sayfalari_xlsx_async` fonksiyonuna isteğe bağlı parametre olarak eklenir. Böylece E01/E09/E10 Excel'leri de tipli olur (seri no ve tarih sorunu tek yerde çözülür). `satirlari_xlsx` değişmez. |
| B3 | **SLA raporu ve rapor sayfası E10'da zaten var.** E10-07 `raporlar.sla_raporu`, `GET /api/teknik-servis/raporlar/sla(.xlsx/.csv)` ve `pages/ServisRaporlariPage.tsx` (`/servis-raporlari`) sayfasını tasarlamış. Excel'i "Özet, İşler, İş Beklemeleri, Tekrar Arıza, PB Vade Uyumu" sayfalarından oluşuyor. E12 aynı rota, aynı sayfa ve aynı uçları yeniden tanımlıyor ve "E10 tasarlanmadı" diyor. | `10_...:384-404, 594` | Aynı dosyayı iki tasarım yazıyor. Düzeltme: sayfa ve router'ın sahibi E12 olur; SLA sekmesi E10'un `sla_raporu` fonksiyonunu çağırır. E12-13, E10-07'nin sunumuna indirgenir. |
| B4 | **E10 alan adları yanlış.** E12 `sla_due_at`, `sla_result (ICINDE/...)`, `sla_paused_minutes`, `delay_reason` adlarını kullanıyor. E10'daki gerçek adlar: `cozum_hedef_at`, `sla_sonuc` IN (ZAMANINDA, ASILDI, OLCULEMEDI), `sla_durdurulan_dk`, `gecikme_nedeni`. Bekleme düşümü ayardan değil, `service_hold_reasons.sla_durdurur` katalog bayrağından okunuyor. | `10_...:96-134, 225-228` | E12'nin `servis_sla_durduran_bekleme_nedenleri` ayarı yanlış mekanizma ve çıkarılmalı. M12-03 kabulü de "alanlar M10-01 adlarıyla okunur" diyor. |
| B5 | **SLA sonucu hangi çözüme göre? İki tasarım farklı söylüyor.** M12-12 ve E12, SLA sonucunun ilk çözümde damgalanıp değişmeyeceğini söylüyor. E10-01 ise `sla_sonuc`'u her TAMAMLANDI'da donduruyor ve TEKRAR_ACILDI'da NULL yapıyor (E10-01 kabul 7). Bu durumda sonuç son çözüme göre hesaplanır. | `10_...:127, 274, 287`; `12_raporlama.json` M12-12 | Bu bir karar çelişkisi. `first_completed_at` (E12-02) kolonu E10'un da ihtiyacını karşılar ("ilk kez TAMAMLANDI", `10_...:387`). E10-01 bu kolona bağlanmalı ve yeniden açılışta `sla_sonuc` silinmemeli. |
| B6 | **"Onaylı tekrar arıza" tanımı yanlış.** E12 K11, sistemin kurduğu `iliski_turu='TEKRAR_ARIZA'` bağını "şef onayı" sayıyor. Oysa E10 K11 / E10-04'e göre bağı **sistem otomatik kuruyor** (aynı `seri_norm` ile son 30 gün). Şef onayı ayrı bir alanda tutuluyor: `tekrar_ariza_teyit` IN (AYNI_ARIZA, FARKLI_ARIZA, KULLANICI_HATASI), ve KAPATILDI'da zorunlu. | `10_...:132-133, 254, 327-333` | Bağa dayanan oran onaysız (aday) sayıyı verir. Onaylı oran `tekrar_ariza_teyit='AYNI_ARIZA'` alanından hesaplanmalı. Pencere ayarı da E10'da zaten var: `servis_tekrar_ariza_gun`. E12'nin açtığı `servis_rapor_tekrar_ariza_gun` bunun kopyası. |
| B7 | **"Süre eksik" tanımı E09 ile çelişiyor.** E12-05 "çözülmüş ve hiç kaydı yok" diyor. E09 ise `sure_durumu` ile çalışıyor (TAM/KISMI/EKSIK/BEKLENMIYOR); TELEFON/UZAKTAN kanalıyla açılışta çözülen iş **BEKLENMIYOR** sayılıyor ("şişik sayaç" bulgusu). E12-16 bu tanımın E09 ile aynı olacağını söylüyor, ama E12-05 farklı bir tanım yazıyor. Kolon adları da E09'dan farklı: E12 `baslangic/bitis` diyor, E09'da `started_at/ended_at`. E12 `ISCILIK` faaliyetini kullanıyor, E09'da böyle bir faaliyet yok; doğru küme `KISI_SAATE_DAHIL`. | `09_...:67, 94, 99, 131-149` | E12 kendi NOT EXISTS tanımını yazmaz. E09'un `sure_ozeti_toplu` / `sure_durumu` SQL ifadesini kullanır. "Eksik" = COZULDU grubu ∧ `sure_durumu='EKSIK'`. |
| B8 | **Lokasyon ve veri kalitesi E14 ile kopya.** E14-18, "E12 servis raporları gruplamayı bu fonksiyonla yapar" diyerek `ana_veri.rapor_boyutu()` tanımlıyor; mükerrer müşteri grubu ve "müşterisi/lokasyonu dolu iş oranı" göstergeleri de E14-18'de. E12 bunların karşılığını `lokasyon_anahtari()`, `musteri_varyanti` ve `lokasyonsuz` adlarıyla yeniden yazıyor. | `14_...:667-693` | E12-03, E12-11 ve E12-16 E14 fonksiyonlarını çağırmalı. `addresses.city` serbest metin (`account.py:186`); şehir normalleştirmesi E14'te yapılır. |
| B9 | **`mukerrer_adaylari` toplu kontrol için uygun değil.** Fonksiyon tek bir hesabı alıp en fazla 5 aday döndürüyor ve kapsam filtresi uygulamıyor (`accounts.py:84-106`). Bu fonksiyonla "küme eşitliği" testi tanımsız kalır; KENDI_BIRIMI şefi de kapsamı dışındaki hesap unvanlarını görür. | `accounts.py:84-106` | Müşteri varyantı kontrolü E12'den çıkarılır ve E14'ün (kapsamlı) göstergesine bağlantı verilir. |
| B10 | **`rapor.personel` başka uçlardan atlatılabiliyor.** E09-14 `/zaman/ozet` (personel dağılımı), `/zaman/kayitlar(.xlsx)` (ham süre ve kişi bazlı satır) ve E10-09 "personel iş yükü" yalnız `servis.gor` + `rapor.gor` istiyor. E01-15 `/isler.xlsx` iletişim telefonunu yalnız maskeliyor. | `09_...:550-554, 663-664`; `10_...:427-444`; `01_...:692` | E12'nin KVKK kuralı yalnız kendi uçlarında kalırsa işe yaramaz. `rapor.personel` bu uçlara da uygulanmalı (E12-09 revize). |
| B11 | **`rapor.gor` / `rapor.disaaktar` mobilite finans raporlarını da açıyor.** E01, SERVIS_SEF ve SERVIS_YONETICI'ye bu iki izni veriyor. Canlıda `/api/raporlar/musteri-geliri(.xlsx)` (müşteri başına abonelik ve sipariş geliri), `/dashboard`, `/teklif-donusumu`, `/bayi-stogu` uçları yalnız bu iznin kendisini istiyor ve kapsam uygulamıyor. `musteri-geliri.xlsx` için yalnız `rapor.disaaktar` yetiyor. Menüde "Panel" ve "Raporlar" kalemleri de `rapor.gor` ile açılıyor. | `permissions.py:61-62`; `api/reports.py:29-30, 48-54, 109-132`; `services/reports.py:236-248`; `AppLayout.tsx:52, 79`; `01_...:230-231` | KENDI_BIRIMI kapsamlı bir şef bütün şirketin müşteri gelirini görür ve indirir. Bu "en az erişim" ilkesine aykırı ve E12'nin dayandığı izin modelinin bir yan etkisi (eklenen madde E12-D01). |
| B12 | **Atölye iptali E01 makinesinde yok, atölye kapanışı da tek giriş noktasını atlıyor.** E01 makinesinde `ATOLYEDE→IPTAL` geçişi yok (E05 kontrol B1). E05 tasarımı `service_orders.status` alanını `atolye.durum_degistir` ile yazıyor. | `01_...:250`; `05_...:24`; `05_..._kontrol.md` B1 | E12-04 (atölye iptali) ve E12-02 (`first_completed_at` yalnız E01 `durum_degistir` içinde yazılır) bu düzeltme olmadan çalışmaz. E05, E01 `durum_degistir`'i çağırmalı. |
| B13 | **"Tanımsız durum" canlı veritabanında oluşamaz.** `service_orders.status`, `ck_so_durum` CHECK kısıtına bağlı. Eşlenemeyen eski değer göç karantinasına düşer, tabloya hiç girmez. | `01_...:75` | "Toplam = Açık + Çözüldü + İptal + Tanımsız" eşitliği canlı tabloda her zaman Tanımsız=0 ile sağlanır; test bu yüzden hiçbir şey kanıtlamaz. Tanımsız sayısı göç karantinasından okunmalı (Veri Kalitesi). Eşitlik testi göç önizlemesinde anlamlıdır. |
| B14 | **400 ile 422 karışıyor.** `main.py`'de `RequestValidationError` eşleyicisi yok. Pydantic `Literal` / `Query(ge, le)` ihlali **422** döner (E01-03 kabulü de "katalog dışı hedef 422" diyor). E12 ise "Literal ile 400" diyor. | `main.py:115-161` | Kabul şöyle düzeltilmeli: katalog dışı değer ve `tekrar_gun=200` → 422; tarih sırası ve 24 ay sınırı (servis doğrulaması) → 400. |
| B15 | **Test seed koruması her zaman hata verir.** `config.env` varsayılanı `"dev"` ve conftest bu değeri değiştirmiyor (`config.py:24`, `conftest.py:99-115`). Bu yüzden `env != "test"` koşulu testte de `RuntimeError` fırlatır. | `config.py:24`; `conftest.py:53-67` | Koruma conftest'teki kalıpla yapılmalı: veritabanı adı `_test` ile bitmiyorsa ya da adres `get_config().database_url` ile aynıysa hata verilir. |
| B16 | **Denetim kaydı ve dosya adı ayrıntıları.** `audit.log` `new_value` alanına JSONB yazıyor; filtrelerdeki `date` nesnesi serileştirilemez, ISO metne çevrilmeli. `Content-Disposition` başlığı latin-1 kodlanır; Türkçe karakterli dosya adı 500 hatası verir (`deps.py:128-136` docstring'i). openpyxl saat dilimi taşıyan (`timestamptz`) datetime değerini yazmayı reddeder; yerel saate çevrilmesi zorunludur. | `audit.py:40-52`; `deps.py:131-136` | Bunlar E12-06 ve E12-09 kabullerine eklenmeli. |
| B17 | **"Her izin en az bir rolde" testi bu iddiayı kanıtlamaz.** ADMIN bütün izinleri aldığı için test her durumda geçer. | `test_permissions.py:17-18, 43-46` | `rapor.personel` için ayrı bir test yazılmalı: izin yalnız SERVIS_YONETICI ve SERVIS_SEF rollerinde (ve ADMIN'de) bulunur. |

### 1.2 Diğer gözlemler

- **Pivot şablonu (E12-17):** İnternetten indirilen dosya Excel'de Korumalı Görünüm'de açılır ve bu modda `refreshOnLoad` çalışmaz. Pivot, şablonun önbelleğindeki örnek satırı gösterir; kullanıcı yanlış sayı görür. Şablonun pivot önbelleği boş kaydedilmeli (cacheRecords yok). Pivotun boş görünüp "Düzenlemeyi etkinleştir" dendiğinde dolması, yanlış veri göstermesinden iyidir. openpyxl pivotu yalnız "korur", oluşturamaz; onarım uyarısı riski için bir özellik bayrağıyla yalnız Excel Tablosu yedeği tutulmalı. Bu yüzden öncelik P3 olmalı.
- **Ayar doğrulaması:** `settings.set_many` tip ve aralık doğrulamıyor (`settings.py:116-124`). `servis_rapor_azami_ay` ya da `servis_rapor_excel_azami_satir` alanına metin veya 0 girilirse rapor çöker. Okuma tarafında `int()` dönüşümü ve sınır uygulanmalı.
- **Uç yolu tutarsız:** E12 §4 `GET /api/teknik-servis/is-emirleri?kpi=` diyor, E01'deki uç `GET /isler?kpi=`.
- **Uyarı bloğu:** `uyarilar.topla` hiçbir kapsam uygulamıyor (`uyarilar.py:47-110`). Servis bloğundaki sayı birim ve müşteri kapsamlı sorgudan gelmeli (E12 bunu belirtmiş, doğru).
- **Menü izni:** E12 K5 menü için `servis.gor`, E10 ise `rapor.gor` diyor. Kalem tek tanımlanmalı. E12 K5 makul.
- **Operasyon Merkezi:** E12 K15 ayrı sayfa olmadığını, E10 K15 ise ayrı sayfa olduğunu söylüyor. Bu çelişki E12-D02 kapsamında çözülmeli. Öneri: E10-08 ayrı sayfa olarak kalsın, ama sayaçları E01-14 kaydından alsın.

## 2. Madde hükümleri

| Madde | Hüküm | Öncelik | Gerekçe / düzeltme |
|---|---|---|---|
| E12-01 | DEĞİŞTİR | P1 | B1, B13. E01-03 `DURUM_GRUPLARI` sözlüğüne `RAPOR_GRUBU` eşlemesi eklenir (COZULDU = TAMAMLANDI + KAPATILDI); `durum_grubu_ifadesi()` aynı sözlükten üretilir. Tanımsız sayısı göç karantinasından gelir. |
| E12-02 | KABUL | P1 | Gerçek ihtiyaç; E10'un "ilk kez çözülen" tanımı da bunu gerektiriyor. Ön koşullar: (a) E05 `durum_degistir`'i çağırır (B12); (b) E10-01, `sla_sonuc`'u `first_completed_at`'e bağlar ve yeniden açılışta silmez (B5); (c) E01 K3 kısa yolu (MUSTERI_TALEBI→TAMAMLANDI) da aynı fonksiyondan geçer. |
| E12-03 | DEĞİŞTİR | P1 | B8. `lokasyon_anahtari()` yazılmaz, E14 `ana_veri.rapor_boyutu()` kullanılır. PB formunun alanları ezmemesi E04 testinde kalır, E12 yalnız çapraz test ekler. |
| E12-04 | DEĞİŞTİR | P1 | Kategori E01-16'nın işi. E12 yalnız çapraz testi yazar. E01 makinesine `ATOLYEDE→IPTAL` eklenmesi önkoşuldur (B12). |
| E12-05 | DEĞİŞTİR | P1 | B7. E09 `sure_durumu` ve `KISI_SAATE_DAHIL` kullanılır. TELEFON/UZAKTAN kanalıyla çözülen iş BEKLENMIYOR sayılır. Göçten gelen ve `user_id` boş olan süreler ayrı satırda gösterilir (E12-D03). Aylık akış (açılan ve çözülen ayrı) ve eşitlik testi kalır. |
| E12-06 | DEĞİŞTİR | P1 | B2, B16. Tipli yazım E01-15 `sayfalari_xlsx_async` fonksiyonuna sütun şeması olarak eklenir. `timestamptz` değerleri Europe/Istanbul saatine çevrilip saat dilimi bilgisi atılır. Dosya adı ASCII olur. |
| E12-07 | DEĞİŞTİR | P1 | B15. Koruma veritabanı adına (`_test`) göre yapılır. Seed iki aşamalıdır: çekirdek (E01+E09) P1, diğer modüller geldikçe eklenir. Her senaryo E01..E11'i beklerse P1 test hiç yazılamaz. |
| E12-08 | DEĞİŞTİR | P2 | B1, B3, B14. Motor E01-14 kaydını genişletir; `KpiKutusu` E01-14'te doğar, E12 onu ortaklaştırır. E05 (`/raporlar/kpi`), E09-14 ve E10-08 sayaçları aynı kayıttan okur. Katalog dışı parametre 422 döner. |
| E12-09 | DEĞİŞTİR | P2 (üretim öncesi zorunlu) | B10, B16, B17. `rapor.personel` E09 `/zaman/ozet`, `/zaman/kayitlar(.xlsx)`, E10-09 personel yükü ve E01-15 iletişim kolonlarına da uygulanır. Denetim kaydında filtreler ISO metin olarak yazılır. Rol testi açık yazılır. |
| E12-10 | KABUL | P2 | `ix_ste_is_baslangic` E09'da zaten tanımlı. Sınırlar makul. Ham süre yalnız `rapor.personel` ile Excel'de yer alır. |
| E12-11 | DEĞİŞTİR | P2 | B8. Müşteri ve şehir boyutu E14'ten gelir. `teknisyen` boyutu ve filtresi `rapor.personel` ister. Göç kaynaklı adlar (E12-D03) "Eşleşmemiş: ad" satırında gösterilir. |
| E12-12 | DEĞİŞTİR | P2 | E04'te `donem_tamamlama()` henüz tanımlı değil. Fonksiyon E04 `bakim_raporlari.py`'de tanımlanır ve E04-18, E10-07 "PB Vade Uyumu" ve E12 bu tek fonksiyonu kullanır. Dönem durumu `closing_kind` alanından okunur. |
| E12-13 | DEĞİŞTİR | P2 | B3, B4. SLA hesabı ve Excel E10-07'nindir. E12 yalnız sekmeyi ve KPI kaydını ekler; E10 alan adları kullanılır, ayar kopyası açılmaz. Efor S olur. |
| E12-14 | DEĞİŞTİR | P2 | B6. Onaylı oran = `tekrar_ariza_teyit='AYNI_ARIZA'`. Aday (bağ ya da `tekrar_ariza_aday`) ayrı satırda, onaysız geçmiş ayrı satırda gösterilir. Ayar `servis_tekrar_ariza_gun` (E10). Tekrar ziyaret E12'nin özgün katkısı: SAHA faaliyetli günler sayılır (yalnız YOL dışı değil). |
| E12-15 | KABUL | P2 | E01 olay tablosu ve `first_completed_at` ile kopya oluşmuyor. ATOLYE kategorisinde yeniden açma ucu 409 döndüğü için (E05 kontrol) atölye bu listeye girmez. |
| E12-16 | DEĞİŞTİR | P2 | B8, B9, B13. Kalan kontroller yalnız servise özgü olanlar: tanımsız (karantina), çözüm zamanı eksik, süre eksik (E09), seri eksik (`TUR_KURALLARI.seri_zorunlu`; ayar açılmaz), şef atanmamış, SLA ölçülemedi. Müşteri ve lokasyon için E14-18 göstergesine bağlantı verilir. |
| E12-17 | DEĞİŞTİR | P3 | §1.2. Şablon pivot önbelleği boş tutulur ve bir özellik bayrağıyla yalnız tablo yedeği korunur. Önce E12-06 tipli tablolar gelir. |
| E12-18 | KABUL | P3 | Daraltılmış kapsam makul. Göçten gelen ve olayı olmayan işler için "geçmiş değişebilir" notu doğru. |

## 3. Kararların değerlendirmesi

| Karar | Hüküm |
|---|---|
| K1 | Makul (E01 ile uyumlu). |
| K2 | Makul; Korumalı Görünüm riskiyle birlikte P3. |
| K3 | Makul; E10'da PB SLA dışı, `ck_so_pb_sla` ile uyumlu. |
| K4 | Makul. |
| K5 | Makul, ancak E10'daki `rapor.gor` menü tanımıyla tek kaleme indirilmeli. |
| K6 | Makul. |
| K7 | Makul. |
| K8 | Makul, ancak B10 nedeniyle eksik: izin diğer modül uçlarına da uygulanmalı. |
| K9 | Makul (öncelik sırası). B11 ise ayrı bir konu ve güvenlik aşamasına bırakılmamalı, çünkü yeni roller bu açığı **yeni** açıyor. |
| K10 | DEĞİŞTİR: E10 `servis_tekrar_ariza_gun` yeniden kullanılır. |
| K11 | RET: onay işareti `tekrar_ariza_teyit` alanıdır (B6). |
| K12 | Makul. |
| K13 | Makul (E09 `yerel_gun`, E10-12 ile aynı). |
| K14 | Makul; E10 de bu kolona bağlanmalı (B5). |
| K15 | Çelişkili (E10 K15); E12-D02'de çözülür. |
| K16 | Makul; seed koruması düzeltilmeli (B15). |
| M12-07 reddi | Makul. |
| Mobilite raporlarına dokunmama | Makul. |

## 4. Eklenen maddeler

- **E12-D01 (P1):** Servis rollerinin `rapor.gor` / `rapor.disaaktar` üzerinden mobilite finans raporlarına erişmesi (B11).
- **E12-D02 (P1):** Modüller arası rapor ve KPI sahipliği tablosu (B1, B2, B3, B8; K15 çelişkisi).
- **E12-D03 (P2):** Göç kaynaklı, kullanıcıyla eşleşmemiş süre kayıtlarının raporlanması.
- **E12-D04 (P2):** Rapor parametre doğrulaması, ayar okuma sınırları ve çıktı güvenliği (B14, B16, ayar doğrulaması).
