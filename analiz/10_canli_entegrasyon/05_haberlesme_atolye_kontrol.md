# E05 Haberleşme Atölyesi: Bağımsız Denetim

> Tarih: 2026-10-21 · Denetlenen: `05_haberlesme_atolye_entegrasyon.md` · Kaynak koda dokunulmadı, yalnızca okundu.
> Doğrulanan canlı dosyalar: `services/statemachine.py`, `services/rma.py`, `models/attachment.py`, `models/quote.py`, `models/account.py`, `models/service.py`, `permissions.py`, `api/deps.py`, `services/gorevler.py`, `services/uyarilar.py`, `services/belgeler.py`, `services/pdf.py`, `services/kvkk.py`, `tests/conftest.py`.
> Çapraz kontrol için okunanlar: `00_MIMARI_KURALLAR.md`, `01_is_emirleri_entegrasyon.md`, `01_is_emirleri_kontrol.md`, `03_cihaz_kutugu_entegrasyon.md`.

## 1. Genel hüküm

Canlı kodla karşılaştırıldığında tasarımın iddiaları doğru çıkıyor. Canlıda atölye kavramı yok. Kullanılan altyapı gerçekten mevcut: `StateMachine`/`MAKINELER` (`statemachine.py:27-83, 189-196`), RMA garanti dondurma ve açık kayıt engeli (`rma.py:43-67, 91-99`), `sees_cost` (`deps.py:103-105`), `KayitTipi` (`gorevler.py:34-57`), `topla()` içindeki `user.has()` blokları (`uyarilar.py:47-166`), `pdf_uret_async` ve `firma_bilgisi` (`pdf.py:53`, `belgeler.py:119`). Teklif durumlarında `KABUL` değeri var (`quote.py:45-66`), `Account.is_tedarikci` de var (`account.py:80`).

Mobilite tarafı korunuyor: `work_orders`, `settlements`, `devices`, EXCLUDE kısıtları ve IMEI kuralı hiç yazılmıyor. Tek istisna aşağıdaki B6'da anlatılan RMA köprüsü.

Asıl sorun canlı kodla değil, **önkoşul modüllerle (E01 ve E03) uyumsuzluk**. Tasarım, E01 ve E03'ün gerçekte tanımladığından farklı bir sözlük ve tablo yapısı varsayıyor. Bu hâliyle yazılırsa tasarımın kendi önerdiği meta-test (`test_atolye_esleme.py`) daha ilk koşuda kırılır. Atölyenin çözmek istediği "iki kaynaklı durum/seri" sorunu da yeniden doğar.

| # | Bulgu | Kanıt | Etki / düzeltme |
|---|---|---|---|
| B1 | **Servis işi durum eşlemesi E01 makinesinde yok.** Eşleme `PLANLANACAK`, `KAPANDI` ve `ISLEMDE` kullanıyor. E01'de başlangıç durumu `MUSTERI_TALEBI`, kapanış durumu `KAPATILDI`. `MUSTERI_TALEBI→ISLEMDE` geçişi yok. `ISLEMDE` ve `ATOLYEDE` durumlarından `IPTAL`'e geçiş yok. `TAMAMLANDI`'dan yalnız `KAPATILDI` ve `TEKRAR_ACILDI`'ya gidilebiliyor. | `01_...entegrasyon.md:243-257`; tasarım §3.2 | Meta-test (c) kırılır. TESLIME_HAZIR→ONARIMDA geri alması servis işini `TEKRAR_ACILDI`'ya düşürür (`reopen_count` artar, sonuç geçersiz olur). Doğru eşleme: atölyedeki tüm açık durumlar → `ATOLYEDE`; bekleme durumları → E01 bekleme ucuyla `BEKLEMEDE`; `TESLIM_EDILDI` → `TAMAMLANDI` (E01 K13); `KAPATILDI` kararı şefte (E01 K1: hiçbir iş otomatik kapanmaz). E01 makinesine `ATOLYEDE→IPTAL` eklenmeli. |
| B2 | **Tür ve kategori adı yanlış.** Tasarım her yerde `tur='ATOLYE'` diyor. E01'de tür `ATOLYE_ONARIM`, kategori ise `ATOLYE`. | `01_...:72-73` | E05-22 koruması, E05-21 sayımı ve E05-16 uç kontrolleri `kategori='ATOLYE'` üzerinden yazılmalı. |
| B3 | **Bekleme mekanizması E01'inkini kopyalıyor.** E05, servis işi `ISLEMDE` kalırken `service_holds` satırını kendisi açıp kapatıyor. E01'de bekleme durumu `BEKLEMEDE`'dir ve yalnız bekleme ucundan girilir (`onceki_durum` tutulur). Bekleme nedenleri `MALZEME, MUSTERI_ONAYI, TEKLIF, ...` olup içinde `PARCA` ve `DIS_SERVIS` yok. | `01_...:126-134, 262-268` | E05 bekleme satırını kendisi yazmamalı, E01'in beklet/beklemeyi_bitir servis fonksiyonunu çağırmalı. `PARCA` yerine `MALZEME` kullanılmalı. `DIS_SERVIS` E01 listesine eklenmeli. |
| B4 | **Seri ve ekipman iki kaynaklı.** E01 seriyi `service_order_serials` tablosunda, ekipmanı `service_orders.equipment_id` (E03) kolonunda tutuyor. E05 bunlara ek olarak `workshop_records.equipment_id` açıyor. Aynı iş için üç seri/ekipman yeri oluşuyor. Normalleştirme için de üç ayrı fonksiyon öneriliyor: E01 `normalize_seri`, E03 `seri_anahtari` (Türkçe güvenli büyük harf) ve E05 `upper(trim())`. Python'un `upper()` fonksiyonu `i`'yi `I`'ya çevirir, `İ`'ye çevirmez. | `01_...:95,101-109`; `03_...:39-40` | E05-15'in "tek kaynak" iddiası tutmuyor. Düzeltme: bileşik FK `fk_atolye_servis_ekipman (service_order_id, equipment_id) → service_orders(id, equipment_id) ON UPDATE CASCADE` (canlı emsal: `models/device.py:79-98`). ATOLYE işinde `service_order_serials` satırı açılmaz ya da E01 yazıcısıyla tek seferde senkron yazılır. Tek normalleştirici E03 `seri_anahtari` olur. |
| B5 | **E03 kütüğü telsizi kabul etmiyor.** `EKIPMAN_TIPLERI` yalnız güvenlik cihazlarını içeriyor (XRAY, KAPI_DEDEKTORU, ...). Aynı tip+marka+seri için ikinci aktif kayıt gerekçeyle açılabiliyor, yani bul-veya-aç birden çok eşleşme bulabilir. `brand` String(60), `serial_no` String(200), ama E05 seri için ≤60 diyor. | `03_...:34-40, 55` | Bu önkoşul tasarımda hiç geçmiyor (eklenen madde E05-D01). |
| B6 | **RMA köprüsü ve cihaz garantisi Haberleşme biriminde çalışmaz.** E03'teki `ck_svceq_cihaz_birim` kısıtı `device_id`'yi yalnız MOBILITE ve ARAC_TAKIP birimlerinde serbest bırakıyor. `rma.ac()` "yalnızca çağrılan" masum bir fonksiyon da değil: cihazı `ARIZALI` durumuna çekiyor ve `device_status_history`'ye yazıyor. Bu, mobilite cihaz yaşam döngüsünü değiştirmek ve ikinci bir durum kaynağı açmak demek. | `03_...:56`; `rma.py:75-117` | E05-24'teki `POST /{id}/rma` ve E05-07'deki `devices` dalı ölü kod olur. Bunlar kaldırılmalı; Denge'nin sattığı mobilite cihazı canlı RMA ekranından yürür. |
| B7 | **Garanti tarihi iki yerde.** E03'te `warranty_start/end` ekipman üzerinde tutuluyor. E05 aynı tarihleri kayıt üstünde tekrar tutuyor. | `03_...:50-51` | Tarihler E03'te kalmalı. Atölye kaydı RMA kalıbındaki gibi yalnız dondurulmuş `warranty_status` ve `warranty_end_snapshot` tutmalı (`rma.py:101-110`). |
| B8 | **Roller E01 ile çelişiyor.** E01 `ATOLYE` rolünü zaten tanımlıyor, `SERVIS_TEKNISYEN` için de `KENDI_ISLERI` kapsamını kullanıyor. E05 aynı rolleri farklı izinlerle yeniden tanımlıyor ve gereksiz bir `servis.tumunu_gor` izni uyduruyor. `atolye.kapat` ise, eşlemede servis işini zaten `IPTAL` veya `TEKRAR_ACILDI`'ya götürdüğü için E01'deki `servis.kapat` ile fiilen aynı yetki. | `01_...:198-236` | E05 yalnız `atolye.gor` ve `atolye.yaz` iznini ekler, bunları E01 rollerine dağıtır. İptal ve geri alma için `servis.kapat` kullanılır. Kapsam E01'in `is_erisimi_yok_mu` fonksiyonundan gelir. |
| B9 | **Ek türü ve arıza kataloğu kopyalanıyor.** Canlıda `IMZA` ek türü zaten var (`attachment.py:49`); E05 `MUSTERI_IMZASI` ekliyor (E01 denetimindeki B1 bulgusunun aynısı). E01'de birim bazlı `service_fault_reasons` arıza kataloğu ve `service_results.ariza_nedeni_id` var; E05 ayrıca `ATOLYE_ARIZA_KATEGORILERI` sabit listesini açıyor. | `01_...:141-147` | `IMZA` kullanılmalı. Arıza kategorisi HABERLESME biriminin tohum kayıtlarıyla `service_fault_reasons` tablosuna FK olarak bağlanmalı. Onarım kategorisi atölyeye özgü olduğu için tuple olarak kalabilir. |
| B10 | **Olay geçmişinde KVKK riski.** E01 denetimi (B5) olay satırlarında kişisel veriyi yasaklıyor; tablo salt-ekleme olduğu için anonimleştirme sonradan temizleyemez. E05'teki `gerekce` alanı serbest metin. `ATOLYE_TESLIM` olayına `delivered_to_name` sızabilir. | `01_kontrol.md` B5; `kvkk.py:217-302` | Olay `veri` alanına yalnız kod ve alan adı yazılmalı. Teslim alan ve onaylayan adı olaya yazılmamalı. `hesabi_anonimlestir` ve `_denetim_izini_maskele` fonksiyonları `workshop_records` tablosunu da kapsamalı (eklenen madde E05-D03). |

Diğer gözlemler:

- **İş numarası:** 1:1 ilişkide iki numara (`so_no` ve `atolye_no`) arama ve fişte karışıklık yaratır. E01 zaten tür önekli numara üretiyor (`PB-`). Ayrı `atolye_no_seq` yerine `ATL-YYYYAA-NNNNNN` aynı `service_order_no_seq` dizisinden üretilebilir. Ayrı numara korunacaksa gerekçesi yazılmalı. Kabul grubu dizisi (`intake_group_no`) makul.
- **Silme:** `workshop_records` için `SoftDeleteMixin` önerilmiş ama silme ucu yok. Silme tanımlanmazsa yetim servis işi riski olmaz; tanımlanacaksa servis işiyle birlikte yapılmalı. Önerim: silme yok, IPTAL kullanılır.
- **Çevrim süresi:** Süre `completed_at - received_at` farkından hesaplanmalı (alan zaten bir kez yazılıyor). Olaydan ikinci bir hesap yapmak iki kaynak demektir.
- **Atama yetkisi:** E01 `ATOLYE` rolünde `servis.planla` yok. Atölye kabul personeli atama yapamaz; ihtiyaç varsa role eklenmeli.
- **Test temizliği:** `conftest._TRUNCATE` (`conftest.py:41-50`) bağımsız sequence'leri sıfırlamaz. `ALTER SEQUENCE ... RESTART` eklenmesi doğru bir karar.

## 2. Madde hükümleri

| Madde | Hüküm | Öncelik | Gerekçe / düzeltme |
|---|---|---|---|
| E05-01 | DEĞİŞTİR | P1 | B1, B8. Eşleme şöyle olmalı: açık durumlar→`ATOLYEDE`, beklemeler→E01 `BEKLEMEDE` (beklet fonksiyonu), `TESLIM_EDILDI`→`TAMAMLANDI` (+ `service_results`, kanal `ATOLYE`), `IPTAL`→`IPTAL` (`cancel_reason`). E01 makinesine `ATOLYEDE→IPTAL` eklenir. Geri alma servis işini etkilemez. İptal ve geri alma `servis.kapat` ister. Olay türü E01'de tek bir `ATOLYE` değeri olur, ayrım `veri.alt_tur` alanıyla yapılır; böylece beş yeni CHECK değeri açılmaz. |
| E05-02 | DEĞİŞTİR | P2 | B9. `fault_category` → `fault_reason_id` FK `service_fault_reasons` (HABERLESME tohumu). Kurallar aynen kalır. |
| E05-03 | KABUL | P2 | Kayıt üstündeki onay alanları E01 `service_approvals` tablosunun (iş bitimi imzası) kopyası değil. Bekleme E01 fonksiyonuyla açılır (`MUSTERI_ONAYI`). `approved_by_name` olaya yazılmaz. |
| E05-04 | KABUL | P2 | Canlı WeasyPrint ve `firma_bilgisi` doğrulandı. İmzalı tarama `IMZA` türüyle yüklenir. |
| E05-05 | KABUL | P2 | Aksesuar satır tablosu gerçek bir ihtiyaç ve kopya değil. |
| E05-06 | DEĞİŞTİR | P2 | B4, B5. Normalleştirme yalnız E03 `seri_anahtari` ile yapılır. Eşleşme `equipment_type` + `brand` + `serial_key` üzerinden olur. Birden çok aktif eşleşme varsa 409 ve aday listesi döner. Açık kayıt engeli bileşik FK sayesinde `workshop_records.equipment_id` üzerinde güvenle kalabilir. |
| E05-07 | DEĞİŞTİR | P2 | B6, B7. `devices` dalı çıkarılır. Tarihler E03 ekipmanında tutulur. Kayıt yalnız dondurulmuş `warranty_status` ve bitiş tarihinin anlık kopyasını taşır. |
| E05-08 | KABUL | P2 | `sayfala` ve tek filtre fonksiyonu canlı kalıba uyuyor. Kapsam E01 fonksiyonlarından gelir. |
| E05-09 | KABUL | P3 | Çevrim süresi `completed_at` alanından, rapor ve Excel aynı filtreden üretilir. |
| E05-10 | KABUL | P2 | |
| E05-11 | KABUL | P1 | E01 atama fonksiyonu yeniden kullanılıyor. `ATOLYE` rolüne `servis.planla` verilip verilmeyeceği kararlaştırılmalı. |
| E05-12 | KABUL | P1 | Ayrı kod yok, E05-01 içinde. |
| E05-13 | DEĞİŞTİR | P1 | E01 makinesinde `ATOLYEDE→IPTAL` olmadan çalışmaz. `ck_so_iptal_gerekce` dolu olmalı. Bekleme E01 fonksiyonuyla kapanır. |
| E05-14 | KABUL | P1 | |
| E05-15 | DEĞİŞTİR | P1 | B4. Bileşik FK `fk_atolye_servis_ekipman ... ON UPDATE CASCADE` eklenir. ATOLYE işinde `service_order_serials` için tek yazıcı tanımlanır. Seri düzeltmesi E03/E01 ucuyla yapılır; E05'te ikinci düzeltme ucu açılmaz. |
| E05-16 | DEĞİŞTİR | P1 | B3. Bekleme E01 beklet/beklemeyi_bitir fonksiyonlarıyla yürür. `PARCA` yerine `MALZEME` kullanılır, `DIS_SERVIS` E01'e eklenir. Genel uçlar `kategori='ATOLYE'` ise 409 döner. E01'in `TEKRAR_ACILDI` ucu da ATOLYE kategorisi için 409 dönmelidir. |
| E05-17 | KABUL | P2 | |
| E05-18 | KABUL | P1 | Kalıp canlıyla birebir aynı. `audit.log_change` tutarı denetime yazar; denetim izi izinli ekranda görüldüğü için kabul edilebilir. Olayda tutar yok. |
| E05-19 | DEĞİŞTİR | P1 | B8. `servis.tumunu_gor` çıkarılır. Kapsam E01'in `KENDI_ISLERI` kapsamı ve `is_erisimi_yok_mu` fonksiyonuyla sağlanır. Uyarı ve rapor sayıları da aynı fonksiyondan geçer. |
| E05-20 | DEĞİŞTİR | P2 | Uzunluklar E03 kolonlarıyla aynı olmalı: brand 60, model 80, seri 200. Marka için `Literal` yalnız API'de; E03 `brand` serbest metin olduğundan karşılaştırmada büyük/küçük harf farkı gözetilmez. |
| E05-21 | DEĞİŞTİR | P2 | E01 panelinde zaten "atölyede" kutusu var. Tanım `kategori='ATOLYE' AND status NOT IN (TAMAMLANDI, KAPATILDI, IPTAL)` olmalı; aksi hâlde `BEKLEMEDE` durumundaki atölye işleri kutudan düşer. Canlı panele dokunulmaz. |
| E05-22 | DEĞİŞTİR | P1 | B2. Koruma `kategori='ATOLYE'` (tür `ATOLYE_ONARIM`) üzerinden kurulur. Bütünlük testi yetim işin 0 olduğunu doğrular. |
| E05-23 | KABUL | P3 | Göç koşullu ve salt okunur sağlık raporu doğru. Pilot veri yoksa iş yükü yok; P1 gereksiz. |
| E05-24 | DEĞİŞTİR | P3 | B6. Dış servis alanları ve `DIS_SERVIS` beklemesi kalır, RMA köprüsü (`POST /{id}/rma`, `rma_case_id`) çıkarılır. |
| E05-25 | KABUL | P2 | |
| E05-26 | DEĞİŞTİR | P1 | B8, B9, B10. Yalnız `atolye.gor` ve `atolye.yaz` eklenir ve E01 rollerine dağıtılır; rol yeniden tanımlanmaz. Ek türü `IMZA` olur (`CIHAZ_FOTOGRAFI` gerekiyorsa bir kez E01'de eklenir). `KayitTipi` eklenir. KVKK ayrıntısı E05-D03'te. |
| E05-27 | KABUL | P3 | E06'ya bağlı; FK yok, olay yükü notu yeterli. |
| E05-28 | KABUL | P3 | `topla()` blok kalıbına uyuyor. Sayım E01 kapsam fonksiyonundan geçer. |

## 3. Eklenen maddeler

- **E05-D01 (P1, S):** E03 ekipman kütüğünün telsiz için genişletilmesi. Kapsamı: tip listesine `TELSIZ`, `ROLE_TEKRARLAYICI`, `TELSIZ_DIGER` eklenir (`ck_svceq_tip` migration'da elle drop+create edilir). Tek normalleştirici `seri_anahtari` olur. Kabul ucu, `ekipman.yaz` izni olmadan da `birim=HABERLESME` ekipmanı açabilir.
- **E05-D02 (P1, M):** E01↔E05 sözlük ve makine hizalaması tek PR'da yapılır. İçeriği: `ATOLYEDE→IPTAL`, ATOLYE kategorisinde `TEKRAR_ACILDI` engeli, `DIS_SERVIS` bekleme nedeni, `ATOLYE` olay türü. Eşleme meta-testi E01 makinesiyle yeşil olmalı.
- **E05-D03 (P2, S):** Atölye kişisel verileri için KVKK kapsamı. `hesabi_anonimlestir` fonksiyonu `workshop_records.delivered_to_name` ve `approved_by_name` alanlarını temizler. `_denetim_izini_maskele` atölye denetim satırlarını da maskeler. Olay yazıcısı bu alanları reddeder (unit test).

## 4. Kararların değerlendirmesi

- **Makul:** 2, 3, 4, 5, 8, 9 (BELIRSIZ), 11, 12, 13, 14, 15, 16, 18, 19, 21, 22.
- **Değişmeli:**
  - 1: Doğru, ama eşleme E01'in gerçek makinesine göre yeniden yazılmalı (B1).
  - 6: `atolye.kapat` yerine `servis.kapat` kullanılmalı.
  - 7: `ATOLYE` rolü E01'de tanımlı; burada yeniden tanımlanmamalı.
  - 10: RMA köprüsü Haberleşme birimi için imkânsız (B6).
  - 17: Normalleştirme E03 fonksiyonuyla yapılmalı.
  - 20: Ayrı sequence yerine E01 numarası önekle kullanılmalı.
  - "Yalnız atandığı işler": E01'in `KENDI_ISLERI` kapsamı yeterli, `servis.tumunu_gor` açılmamalı.
- **Gözlemler:** Canlı koddaki dört gözlem doğrulandı (`_SAHIP_TABLOSU` uyumsuzluğu, RMA listesinin kapsamsız olması, `max(id)+1` numara üretimi, `DEGISTI` değeri). E05 bunlara dokunmuyor, bu doğru.
