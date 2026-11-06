# M06 — Kiralama, Depo ve Kiralık Cihaz Envanteri: Bağımsız Denetim

> **Denetlenen:** `analiz/02_moduller/06_kiralama_depo_tasarim.md` (M06-01 … M06-17)
> **Kaynak:** V1.20.1, salt okunur (`kaynak/V1_20_1_orijinal/DengeERP.Api`). Koda dokunulmadı.
> **Tarih:** 21.10.2026
> **Yöntem:** Her "mevcut durum" iddiası kodda tek tek doğrulandı: `Program.cs` 961-1482, 3177-3255, 3896-3933; `OpsSuite.cs`; `app.js` 32, 770, 941, 955-964; `DengeERP_Update.sql` 278-307; `ZZ_V112_RentalInventoryOperations.sql`. Maddeler ayrıca kullanıcı kararlarına göre sınandı: kapsam yalnız teknik servis, öncelik c → b → a, Logo/Flowick kapsam dışı, roller VARSAYIM, teknoloji yığını korunur.

---

## 1. Özet

| Madde | Karar | Öncelik | Kısa gerekçe |
|---|---|---|---|
| M06-01 Tarih bazlı müsaitlik | **DEĞİŞTİR** | P2 | Gerekli. Rezerv ürün/adet düzeyinde hesaplanmalı. Bitiş tarihi uzatması da kontrol edilmeli. `Kontrolde` cihaz gelecekteki müsaitlikten düşülmemeli, ayrı gösterilmeli. |
| M06-02 Kurulum/toplama iş emri bağı | **DEĞİŞTİR** | P2 | Teknik servis kapsamında, ama M01, M02 ve saha zamanına bağımlı, efor L. Kullanıcı sorusu 1 yanıtlanmadan başlanmamalı. Otomatik aşama yazımı sadeleştirilmeli. |
| M06-03 Dönüş kontrol kaydı | **DEĞİŞTİR** | P2 | Gerekli. `Hazır Değil` → `Hazır` yolu (onarım sonrası yeniden kontrol) eksik. Yeni envanter girişi `Hazır` olabilmeli. |
| M06-04 Kısmi sevk/iade, kayıp | **DEĞİŞTİR** | P1 | Hata doğrulandı ve kapsamı daha geniş: sevk edilmemiş tahsisli cihazlar da `Kontrolde` yapılıyor. "Hasarlı" sonucu M06-03 ile çakışıyor. |
| M06-05 Sahada cihaz değişimi | **DEĞİŞTİR** | P3 | M06-04 ve M06-13 gelince bu madde yalnızca bir birleşik ekran olur. Ayrı veri modeli gerekmez. |
| M06-06 Teslim/iade tutanağı | **KABUL** | P2 | Gerekli ve ucuz. Şablon, kullanıcının basılı formu (soru 9) gelince kesinleşmeli. |
| M06-07 Envanter hareket geçmişi | **KABUL** | P1 | Temel madde. `ServicePartMovements` deseni (OpsSuite.cs:206) aynen kullanılabilir. |
| M06-08 Kiralama raporları | **DEĞİŞTİR** | P3 | İlk sürümde üç rapor yeterli. Aşama süreleri M06-02'ye bağlı. M12 raporlama modülüyle tek yerde yapılmalı. |
| M06-09 Kiralama uyarıları | **KABUL** | P2 | `AuxiliaryAlerts` deseni hazır (OpsSuite.cs:38-49). (d) türü M06-01 gelene kadar ertelenir. |
| M06-10 Ürün kataloğu yönetimi | **DEĞİŞTİR** | P2 | Doğru, ama eksik: seed `MERGE` `IsActive=1` de yazıyor. Bu yüzden pasifleştirme her güncellemede geri alınır. |
| M06-11 Durum ve aşama birleşimi | **DEĞİŞTİR** | P1 | Doğrulandı. Eklenmesi gereken: tahsis ve aşama uçları kiralama durumuna bakmıyor (`İptal`/`Kapandı` kiralama sevk edilebiliyor). Kurulum aşamaları birime göre opsiyonel olmalı. |
| M06-12 Seri ve sevk şartı | **DEĞİŞTİR** | P1 | Gerçek risk, iddiada belirtilenden farklı: tahsissiz sevkte cihaz envanterde `Hazır` kalır ve başka işe tahsis edilebilir. Kural seri takipsiz ürünleri de kapsamalı. |
| M06-13 Adet bazlı kısmi tahsis | **KABUL** | P1 | Doğrulandı (1412, 1467). Bariyer tahsisi pratikte yapılamıyor. Sevk sonrası tahsis ekleme de desteklenmeli (M06-05 için). |
| M06-14 İptalde tahsis çözümü | **DEĞİŞTİR** | P2 | "Sonsuza kadar bağlı" ifadesi abartılı. Boş listeyle `allocate` çağrısı (1413) tahsisi elle çözebiliyor. Otomatik çözüm yine de gerekli. |
| M06-15 Atomik kayıt, RowVersion | **DEĞİŞTİR** | P2 | Atomik olmama ve son yazanın kazanması doğrulandı. İrtibat kimliğini korumak şu an iş değeri taşımıyor; `IsPrimary` gereksiz. |
| M06-16 Yetki ayrıştırma | **DEĞİŞTİR** | P2 | Doğrulandı. Dört anahtar fazla; organizasyon şeması gelmeden iki anahtar yeterli. KRİTİK değil. |
| M06-17 Envanter düzenleme kontrolleri | **DEĞİŞTİR** | P2 | Birimler arası düzenleme açığı doğrulandı. "Tahsisli cihazın serisi değiştirilemez" ise **zaten var** (1357-1359). |

**Eklenen maddeler:**
- M06-D01: Aşama düzeltme/geri alma (P2)
- M06-D02: Toplu envanter girişi ve fiziksel sayım (P2)
- M06-D03: Geçiş öncesi pilot veri uzlaştırma raporu (P1)
- M06-D04: Uçtan uca kiralama akış testleri (P1)

**KRİTİK güvenlik:** Bu modülde veri kaybı ya da sızıntısı yaratan KRİTİK bir açık bulunamadı; tasarımcının tespiti doğru. Liste, detay, envanter ve aşama uçlarının hepsinde `UnitAllowed` var. En ciddi yetki açığı M06-17'deki birimler arası envanter düzenlemesi. Bu açık yalnızca iç kullanıcıların kullanabileceği bir **bütünlük** açığı, sızıntı değil.

---

## 2. Madde madde değerlendirme

### M06-01 · DEĞİŞTİR · P2
**Doğrulama:** `allocate` (Program.cs:1376-1434) yalnızca anlık durumu kontrol ediyor (`Hazır`/`Kirada` ve boşta). `StartDate`/`EndDate` hiçbir kontrolde kullanılmıyor. **Doğru.** Gelecek bir iş için yapılan tahsis, cihazı bugünden itibaren bağlıyor (1408).

**Sorunlar:**
- Kabul kriteri yalnızca `Planlandı` geçişini sınıyor. Kiralamanın bitiş tarihi uzatıldığında da çakışma oluşur (kullanıcı sorusu 11). Bugün `PUT /api/rentals/{id}` tarihi serbestçe değiştiriyor (1190-1191).
- "`Kontrolde` müsaitten düşer" kuralı gelecek tarih için fazla kötümser. Bugün `Kontrolde` olan cihaz, iki hafta sonraki etkinlikte büyük olasılıkla hazırdır. Ayrı bir sütunda gösterilmeli. Kesin düşülmesi gerekenler: `Kayıp` ve `Hazır Değil`.
- Bariyer gibi toplu stokta adet hesabı M06-13'e bağlıdır. Bağımlılık listesine eklenmeli.

**Düzeltilmiş kabul:** Bkz. JSON `revised`.

### M06-02 · DEĞİŞTİR · P2
**Doğrulama:** `TeamName` serbest metin (ZZ_V112:80, app.js:941). İş emri ile ilişki yok. **Doğru.**

**Değerlendirme:** Kurulum ve toplama teknik servisin saha işi, yani kapsam içinde. Ancak:
- Madde üç başka modüle bağımlı (M01 iş emri, M02 planlama, saha zaman). Efor L.
- Tasarımcının kendi sorusu (soru 1) hâlâ açık.
- Telsiz kiralamalarında kurulum aşaması olmayabilir (soru 2).

"İş emri kapanınca aşamayı otomatik yaz" fazla bağlayıcı. Bir iş emri birden çok aşamayı kapsayabilir (kurulum + devreye alma) ya da kısmi kapanabilir. Daha sade öneri: aşama kaydı ekranında bağlı iş emri seçilir. İş emri kapanışı yalnızca bir aşama **önerir**, onayı depo/operasyon verir. Ekip bilgisi iş emrinin atanmış personelinden gelir.

Kural: süre iş emri zaman kayıtlarından gelir, kayıt yoksa "eksik" yazılır. Tahmini süre kullanılmaz. Bu kural kullanıcı kararıyla uyumlu.

### M06-03 · DEĞİŞTİR · P2
**Doğrulama:** `POST /api/rentals/inventory` durumu serbest bırakıyor (1341). Kontrol tablosu yok. **Doğru.**

**Sorunlar:**
- "Hazır yalnızca bu uçla oluşur" kuralı yeni envanter girişini engeller. Depoya ilk kez giren cihaz `Hazır` girilebilmeli. Tasarım raporunda bu istisna var, JSON'da yok.
- `Hazır Değil` (eksik veya arızalı) cihaz, eksik tamamlandığında ya da atölyeden döndüğünde `Hazır`'a nasıl geçecek? Kabul (1) bu cihazı kontrol dışı bırakıyor ve cihaz kilitlenir. Kontrol ucu `Kontrolde` **ve** `Hazır Değil` cihazları kabul etmeli.
- Atölye bağlantısı M05'e bağlıdır. M05 haberleşme atölyesi müşteri cihazı odaklıdır, kiralık cihaz için kayıt açılıp açılamayacağı orada kesinleşmeli. Bu yüzden atölye kaydı açma **isteğe bağlı ikinci adım** olmalı.
- Soru 6 açık (kontrolü kim yapar, ürün bazlı kontrol listesi). Kontrol listesi şimdilik serbest not olarak kalmalı; şablon P3.

### M06-04 · DEĞİŞTİR · P1
**Doğrulama:** 1472-1480: `Depoya Alındı`, kiralamaya tahsisli **tüm** satırları seçilen depoya taşıyor, `Kontrolde` yapıyor ve tahsisi siliyor. 1465-1471: sevk, tahsisli `Hazır` satırların hepsini `Kirada` yapıyor. **Doğru.**

**Tasarımcının kaçırdığı:** `Depoya Alındı` hiç sevk edilmemiş tahsisli `Hazır` cihazları da `Kontrolde` yapıp başka depoya "taşıyor". Bu da envanteri bozar.

**Sorun:** İade sonucu "Hasarlı" ile M06-03'ün "Arızalı" kontrol sonucu aynı bilgiyi iki yerde tutar. İade anında yalnızca fiziksel durum bilinir: İade alındı (depo) / Müşteride / Kayıp. Hasar ve eksik tespiti M06-03 kontrolünde yapılmalı; iade notu serbest metin olarak kalır. "Kısmi İade" ayrı bir durum değil, M06-11 durum makinesinde türetilen bir gösterimdir.

### M06-05 · DEĞİŞTİR · P3
**Doğrulama:** 1397-1398 sevk edilmiş kalemin tahsis değişikliğini reddediyor. **Doğru.**

**Değerlendirme:** M06-04 (tek cihaz iadesi) ve M06-13 (tahsis tablosu, sevk sonrası yeni tahsis ve tek cihaz sevki) yapıldığında değişim şu üç adımdan oluşur:
1. Eski cihazın kısmi iadesi
2. Yeni cihazın tahsisi
3. Yeni cihazın kısmi sevki

Bu yüzden ayrı bir iş kuralı değil, tek ekranda birleşik bir işlemdir. Kendi başına P3. Kayıp riskini M06-04 zaten kapatıyor.

### M06-06 · KABUL · P2
**Doğrulama:** Kiralama için çıktı yok. Teklif PDF'i dışında belge üretimi yok. **Doğru.** Fiyat içermemesi kullanıcı kararıyla uyumlu. Şablon, kullanıcıdan basılı form örneği (soru 9) gelince kesinleşmeli.

### M06-07 · KABUL · P1
**Doğrulama:** Cihaz bazlı hareket tablosu yok. Yalnızca `RentalStageHistory` (kiralama bazlı) ve `UpdatedAt` var. Kodda genel bir denetim (audit) tablosu da yok (grep: `AuditLog` sonuç vermedi). **Doğru.**

**Uygulama notu:** Yedek parçadaki `ServicePartMovements` ekleme-yalnız deseni (OpsSuite.cs:188-210) aynen uygulanabilir. Kiralama başlığı değişiklik izi yalnızca durum, tarih ve sorumlu alanlarıyla sınırlı tutulmalı. Tüm alanları loglamak M13 genel denetim tasarımının işi.

### M06-08 · DEĞİŞTİR · P3
**Doğrulama:** Rapor ucu yok. Yalnızca ekran sayaçları var. Excel raporu (Program.cs:2191, 3643) kiralama içermiyor. **Doğru.**

**Değerlendirme:** Yedi rapor bir anda fazla. Aşama süreleri M06-02 olmadan anlamsız. "Dönüş eksik/arıza oranı" M06-03 verisi biriktikten sonra anlam kazanır. İlk sürümde üç rapor yeterli: depo bazlı anlık durum, geciken iade ve kontrolde bekleme. Kullanım oranı M06-13 sonrasında eklenir. Raporlar M12 rapor altyapısıyla tek yerde yapılmalı.

### M06-09 · KABUL · P2
**Doğrulama:** `AuxiliaryAlerts` (OpsSuite.cs:38-49) yalnızca düşük stok ve eğitim uyarısı üretiyor. **Doğru.**

**Not:**
- Kullanıcı başına `can` ve `unitAllowed` filtresi bu fonksiyonda hazır.
- (a) ve (c) türleri bugünkü veriyle bile üretilebilir. (b) M06-13'e, (d) M06-01'e bağlı. Teslim kademeli olabilir.
- Uyarı anahtarı mevcut desende `tür:id:gün`; aynısı kullanılmalı.

### M06-10 · DEĞİŞTİR · P2
**Doğrulama:** Yalnızca `GET /api/rentals/catalog` var (961). Seed `MERGE` (DengeERP_Update.sql:305) `WHEN MATCHED` durumunda `ProductName`, `RequiresSerial` **ve `IsActive=1`** yazıyor. **Doğru, ama eksik:** ekrandan pasifleştirilen ürün, bir sonraki şema uygulamasında yeniden aktifleşir. `RequiresSerial` da geri yazılır. Bu yüzden `MERGE` düzeltmesi bu maddeyle **aynı sürümde** gelmek zorunda; düzeltme yapılmazsa madde zararlı olur.

**Ek kural:** Envanteri veya kalemi olan ürünün `UnitCode` değeri değiştirilemez. Değişirse birim yetki filtresi kayar.

### M06-11 · DEĞİŞTİR · P1
**Doğrulama:**
- 1146: 12 durum serbest seçiliyor.
- 1436-1482: aşama durumu değiştirmiyor, sıra ve tekrar kontrolü yok.
- `Kapandı` seçilince (1180) yalnızca `ClosedAt` yazılıyor, cihazlar `Kirada` kalıyor.
- `app.js:864` sayaçları elle seçilen duruma bakıyor.

Hepsi **doğru.**

**Tasarımcının kaçırdığı:** `allocate` (1385-1392) ve `stage` (1447-1449) kiralamanın durumunu hiç okumuyor. `İptal` veya `Kapandı` bir kiralamaya cihaz tahsis edilip sevk kaydı girilebiliyor.

**Sorunlar:**
- Önerilen makinede "Kurulum Yapıldı → Devreye Alındı" zorunlu adım gibi duruyor. Soru 2'ye göre birim bazlı **opsiyonel** olmalı; telsizde Sevk → Toplandı/İade akışı geçerli olmalı.
- Geri alma işlemi açıklamada geçiyor ama kabul kriteri yok. M06-D01 olarak ayrı yazıldı.
- Mevcut veride "Teklif" durumu var. Yeni makinede yok. Geçişte "Talep" ile eşlenmeli.

### M06-12 · DEĞİŞTİR · P1
**Doğrulama:**
- `app.js:770` serbest seri alanı var.
- 1155-1171: seri zorunluluğu `r.RentalProductId` üzerinden, yani yalnızca başlıktaki ilk ürün için kontrol ediliyor.
- 1465: sevk için tahsis şartı yok.

Hepsi **doğru.**

**Düzeltme:** "Elle yazılan seri envanterdeki çift tahsis engelini deliyor" ifadesi tam doğru değil. Envanter satırı kilidi (1408) korunuyor. Gerçek risk şu: seri takipli kalem **tahsissiz** sevk edilirse cihaz envanterde `Hazır` kalır ve başka bir kiralamaya tahsis edilebilir. Yani fiziksel çift tahsis olur. Aynı risk seri takipsiz (bariyer) kalemler için de geçerli, bu yüzden sevk şartı **tüm ürünlere** uygulanmalı: tahsis toplam adedi = kalem adedi. Bu kural M06-13'e bağımlıdır.

### M06-13 · KABUL · P1
**Doğrulama:**
- `RentalInventory.RentalOrderItemId` tekil (ZZ_V112:62).
- 1412: `SUM(Qty) > kalem adedi` ise ret. 50'lik satır 20'lik kaleme atanamıyor.
- 1467: sevk satırın tamamını `Kirada` yapıyor.

Hepsi **doğru.**

**Not:**
- Elle satır bölme (envanteri 20 + 30 iki satır olarak girme) bugünkü geçici çözüm, ama iade sonrası satırlar dağılır. Ayrı tahsis tablosu doğru çözüm.
- Tahsis tablosu **sevk edilmiş kaleme yeni tahsis ve tek tahsis satırı sevki** de desteklemeli. Bu destek M06-05'i ucuzlatır.
- Seri takipli cihazda `Quantity=1` bir CHECK kısıtıyla zorlanmalı.

### M06-14 · DEĞİŞTİR · P2
**Doğrulama:** 1174-1196 durum güncellemesi tahsise dokunmuyor. **Doğru.**

**Abartı:** `POST /allocate` boş listeyle çağrılınca 1413'te kalemin `Hazır` tahsisleri çözülüyor. Yani elle serbest bırakma mümkün; cihazlar "sonsuza kadar bağlı" kalmıyor. Otomatik çözüm ve gerekçe zorunluluğu yine de gerekli. İş akışını bloke etmediği için P2.

### M06-15 · DEĞİŞTİR · P2
**Doğrulama:**
- app.js:956-964 iki ayrı istek gönderiyor. composition commit edildikten sonra başlık isteği hata verirse kayıt yarım kalır.
- 3238-3240 irtibatlar silinip yeniden yazılıyor.
- 1107, 1127, 1280-1287 ilk kalem başlığa kopyalanıyor.
- Ayrıca 1182'de `request.CustomerName.Trim()` null kontrolü yok; boş müşteri gelince 500 hatası döner.

Hepsi **doğru.**

**Aşırı kısım:** `RentalOrderContactId` başka bir tabloda referans edilmiyor. Silip yeniden yazmanın tek gerçek zararı eşzamanlı kayıtta son yazanın kazanması; bunu RowVersion zaten çözer. Kimlik koruma ve `IsPrimary` şimdilik gereksiz (P3). Sadeleştirilmiş madde: tek uç + tek işlem + RowVersion + eski kolonların yazılmaması + müşteri adı doğrulaması.

### M06-16 · DEĞİŞTİR · P2
**Doğrulama:**
- 1326, 1338, 1380 ve 1440'ın hepsi `rentals.edit` istiyor.
- `Depo` şablonu (3932) yalnızca `warehouse.view` ve `rentals.view` içeriyor.
- `Şef` şablonunda (3929) da `rentals.edit` var.
- Depo adı ucu (1322-1332) yedek parça depolarını da etkiliyor; `warehouse.manage` (3896) mevcut ama kullanılmıyor.

Hepsi **doğru.**

**Aşırı kısım:** Organizasyon şeması gelmeden dört yeni anahtar (inventory, stage, check, catalog.manage) erken. Depo personeli büyük olasılıkla envanter, sevk/iade ve kontrolün hepsini birlikte yapar. Öneri iki anahtar:
- `rentals.inventory`: envanter, tahsis, transfer, kontrol ve katalog
- `rentals.stage`: sevk ve iade aşamaları

Şema gelince gerekirse bölünür. Depo adı değişikliği `warehouse.manage` ister.

### M06-17 · DEĞİŞTİR · P2
**Doğrulama:**
- 1344-1349: yalnızca **yeni** ürünün birimi kontrol ediliyor. Başka birimin `RentalInventoryId` değeriyle istek atan kullanıcı o satırı kendi birimindeki bir ürüne çevirebilir. **Doğru.**
- 1341: `Kirada` elle verilebiliyor. **Doğru.**

**Yanlış iddia:** "Tahsisli/kiradaki cihazın serisi değiştirilemez" kuralı **zaten var**. 1357-1359'da tahsisli satırın düzenlemesi tamamen reddediliyor. Bu kabul kriteri madde dışına alınmalı. Yeni tahsis tablosuna geçişte (M06-13) aynı kuralın korunduğu test edilmeli.

Bu açık KRİTİK değil (iç kullanıcı, bütünlük açığı), ama yeni uçlar yazılırken birlikte kapatılmalı.

---

## 3. Eklenen maddeler

### M06-D01 [EKSİK] Aşama düzeltme / geri alma · P2 · Efor S
**Mevcut:** Aşama kayıtları için silme veya düzeltme ucu yok. Yanlış girilen `Depoya Alındı` (1472-1480) tahsisleri NULL'lıyor ve cihazları başka depoya taşıyor; geri dönüş yolu yok. M06-11 aynı aşamanın ikinci kez girilmesini 409 ile engelleyince yanlış bir kayıt iş akışını tamamen kilitler.

**İstenen:**
- Son aşama kaydı için gerekçeli "geri al" işlemi.
- Envanter etkisi M06-07 hareketlerinden ters çevrilir.
- Geri alma kaydı silinmez, ters hareket olarak yazılır.

**Kabul:**
- Yanlış `Depoya Alındı` geri alınınca cihazlar önceki depo/durum/tahsis durumuna döner.
- Gerekçe boşsa 400 döner.
- Yalnızca en son aşama geri alınabilir.
- Geri alma kaydı geçmişte görünür.

### M06-D02 [EKSİK] Toplu envanter girişi ve fiziksel sayım · P2 · Efor M
**Mevcut:** Envanter yalnızca tek tek formla giriliyor (app.js:1001-1028, Program.cs:1334). Seri takipli her telsiz ayrı kayıt gerektiriyor. İçe aktarma ucu yok. Proje geçmişinde (satır 523) "kiralama stok geçişleri ve depo hareketi uzlaştırması" açık iş olarak duruyor.

**İstenen:**
- CSV/Excel ile toplu giriş: önce önizleme ve hata listesi, sonra onay.
- Depo bazlı sayım: sayılan seri ve adetler girilir. Fark listesi (fazla, eksik) çıkar. Onayla `Kayıp` ya da düzeltme hareketi yazılır.

**Kabul:**
- 200 satırlık dosyada mükerrer seri satırları reddedilir, diğerleri yüklenir, her satır için hareket yazılır.
- Sayım sonucu eksik çıkan seri onaysız durum değiştirmez.

### M06-D03 [VERİ] Geçiş öncesi pilot veri uzlaştırma raporu · P1 · Efor S
**Mevcut:** Pilotta 1146'daki serbest durumlar ve 1341'deki serbest cihaz durumu yüzünden tutarsız kayıtlar oluşmuş olabilir:
- tahsissiz `Kirada` cihaz
- `Kapandı`/`İptal` kiralamaya bağlı cihaz
- envanterle eşleşmeyen elle girilmiş seri
- durum ile aşama uyumsuzluğu

M06-11, M06-12 ve M06-13'ün geçiş scriptleri bu veriyi varsayımla dönüştürür.

**İstenen:** Geçişten **önce** çalışan, salt okunur tek bir uzlaştırma sorgusu ve raporu. Kullanıcı kayıtları düzeltir, ardından geçiş çalışır.

**Kabul:**
- Rapor dört uyumsuzluk türünü sayı ve satır listesiyle verir.
- Uyumsuz kayıt sayısı sıfır değilse geçiş scripti uyarı verir ve onay ister.

### M06-D04 [EKSİK] Uçtan uca kiralama akış testleri · P1 · Efor M
**Mevcut:** `TEST_SONUCLARI_V120.txt` kiralama içermiyor. Proje geçmişi V1.12 için "ayrıntılı akış testleri eksik" diyor (satır 113, 561).

**İstenen:** M06-11 ve M06-13 durum makinesini ve tahsis modelini değiştirmeden önce test verisiyle tekrarlanabilir senaryo seti:
- talep → tahsis → sevk → kısmi iade → kontrol → kapanış
- iptal
- eşzamanlı tahsis
- birim yetkisi

**Kabul:**
- Senaryolar test veritabanında betikle çalışır.
- Her senaryo beklenen envanter durumu ve hareket sayısıyla doğrulanır.
- Mevcut sürümde bilinen hatalar "beklenen başarısız" olarak işaretlenir.

---

## 4. Uygulama sırası yorumu

Tasarımcının sırası (temel: M06-07 → M06-13 → M06-11 → M06-15) teknik olarak doğru. Kullanıcının c → b → a önceliğiyle çelişmiyor, çünkü bu maddeler yeni özelliklerin önkoşulu. Önerilen düzeltilmiş sıra:

1. M06-D04 (testler) ve M06-D03 (uzlaştırma raporu): mevcut davranışı sabitle.
2. M06-07 → M06-13 → M06-11 (+M06-D01) → M06-12 → M06-04.
3. M06-03, M06-01, M06-06, M06-14, M06-15, M06-10 (`MERGE` düzeltmesiyle birlikte).
4. M06-09, M06-16, M06-17. Yeni uçlar yazılırken anahtarlar baştan doğru verilmeli.
5. M06-02 (iş emri modülü ve kullanıcı yanıtı gelince), M06-05, M06-08, M06-D02.

## 5. Açık kalan ve karar bekleyen

- Soru 1 (kurulum iş emri mi?), soru 2 (telsizde kurulum var mı?) ve soru 3 (rezerv hangi aşamada?) yanıtlanmadan M06-01, M06-02 ve M06-11'in ayrıntısı kesinleşmez.
- Rol eşlemeleri (Depo & Lojistik = envanter + sevk + kontrol) VARSAYIM'dır; organizasyon şeması gelince doğrulanmalıdır.
