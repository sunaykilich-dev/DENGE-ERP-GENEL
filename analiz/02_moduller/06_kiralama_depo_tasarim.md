# M06 — Kiralama, Depo ve Kiralık Cihaz Envanteri: Gereksinim Tasarımı

Kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api/` (V1.20.1). Kaynak kod salt okunur, bu belge yalnızca analizdir.
Tarih: 2026-10-21. Kapsam: yalnızca teknik servis. Logo CRM / Flowick entegrasyonu kapsam dışı.
Öncelik sırası (kullanıcı kararı): **(c) yeni özellik → (b) mevcut eksikler → (a) güvenlik/üretime hazırlık**.

---

## 1. Mevcut durum (kodda ne var)

### 1.1 Veri modeli (SQL)

| Tablo | Script | Not |
|---|---|---|
| `RentalProducts` | `Database/DengeERP_Update.sql:261-307` | Birim + kategori + kod + ad + `RequiresSerial`. 23 ürün seed ile gelir (X-Ray, kapı dedektörü, bariyerler: seri takipsiz; Hytera telsizler). **Ekleme/düzenleme ekranı yok.** |
| `RentalOrders` | `DengeERP_Update.sql:310-345` | Kiralama başlığı. V1.4'ten kalan tekil alanlar hâlâ duruyor: `RentalProductId/ProductName/Quantity/SerialNumbers/ContactName/ContactPhone` (ilk kalemin kopyası). Müşteri/lokasyon serbest metin. Fiyat alanı yok. |
| `RentalOrderItems` | `ZZ_V112_RentalInventoryOperations.sql:3-17` | Çoklu ürün kalemi; `SerialNumbers` serbest metin (virgülle ayrılmış). |
| `RentalOrderContacts` | `ZZ_V112...sql:19-34` | Çoklu irtibat; tür (Satın Alma / Saha Operasyon / Teknik Sorumlu / Diğer). |
| `RentalWarehouses` | `ZZ_V112...sql:36-49` | DEPO-1/2/3 seed. **Yedek parça stoğu da aynı tabloyu kullanıyor** (`ZZ_V120_Operations.sql:21`). |
| `RentalInventory` | `ZZ_V112...sql:51-71` | Cihaz/stok satırı: ürün, depo, seri, adet, `ConditionStatus` (Hazır/Hazır Değil/Kirada/Kontrolde), eksik notu, `RentalOrderItemId` (tahsis). Seri tekilliği: `UX_RentalInventory_ProductSerial` (ürün+seri). |
| `RentalStageHistory` | `ZZ_V112...sql:73-93` | Aşama logu: aşama adı, zaman, ekip (serbest metin), depo, not, seri anlık görüntüsü, kaydeden. |

Hareket/denetim tablosu yok; envanterdeki bir cihazın geçmişi (hangi kiralamalara gitti, hangi depoya döndü, kim kontrol etti) tutulmuyor.

### 1.2 API uçları (`Program.cs`)

| Uç | Satır | İzin | Ne yapar |
|---|---|---|---|
| `GET /api/rentals/catalog` | 961-991 | rentals.view veya rentals.create | Aktif ürünler (birim filtresi) |
| `GET /api/rentals` | 993-1049 | rentals.view | Tüm kiralamalar (sayfalama yok) |
| `POST /api/rentals` | 1051-1138 | rentals.create | Kiralama + kalemler + irtibatlar, no `KIR-YYYYMM-####` (1098-1105). Durum `Talep` |
| `PUT /api/rentals/{id}` | 1140-1198 | rentals.edit | Başlık + **durum** (12 durum, 1146). Seri zorunluluğu yalnızca başlıktaki ilk ürün için (1171) |
| `GET /api/rentals/{id}/details` | 1201-1243 | rentals.view | Kalemler, irtibatlar, aşamalar |
| `PUT /api/rentals/{id}/composition` | 1245-1290 | rentals.edit | Kalem/irtibat kaydet; tahsisli kalemin modeli/adedi azaltılamaz (1267-1274) |
| `GET /api/rentals/inventory` | 1292-1320 | rentals.view veya warehouse.view | Depolar + tüm envanter |
| `PUT /api/rentals/warehouses/{id}` | 1322-1332 | rentals.edit | Depo adı değiştir (birim kontrolü yok, yedek parça depolarını da etkiler) |
| `POST /api/rentals/inventory` | 1334-1374 | rentals.edit | Envanter ekle/düzenle; durum serbestçe seçilebilir (1341) |
| `POST /api/rentals/{id}/allocate` | 1376-1434 | rentals.edit | Kaleme cihaz tahsisi, `Serializable` işlem, çift tahsis engeli (1408) |
| `POST /api/rentals/{id}/stage` | 1436-1482 | rentals.edit | Aşama kaydı; `Sevk Edildi` → tahsisli Hazır cihazlar `Kirada` (1465-1471); `Depoya Alındı` → kiralamadaki **tüm** cihazlar seçilen depoya `Kontrolde` + tahsis çözülür (1472-1480) |

Yardımcılar: `JoinRentalSerials` 3177, `ValidateRentalComposition` 3183-3201 (en fazla 100 kalem / 50 kişi), `SaveRentalCompositionAsync` 3203-3255 (irtibatlar her kayıtta **silinip yeniden yazılır**, 3238-3240). İstek kayıtları 3842-3850. Rol şablonları: `Depo` 3932, `Kiralama Operasyon` 3933. Birim kontrolü `UnitAllowed` 2807 (boş liste = tüm birimler).

### 1.3 Ön yüz (`wwwroot/app.js`)

- Durum listesi: `rentalStatuses` 32. Veri yükleme 147-149. Menü “Kiralama” yalnızca `rentals.view` ile 192.
- Kalem/irtibat düzenleyici: 748-818. Liste tablosu 823-830. Sayfa + KPI kartları (kayıt, kirada, iade/kontrol, kalem) 857-866.
- Depo/Envanter sekmesi 831-856: Hazır/Eksik-Kontrolde/Kirada sayaçları, depo kartları, arama/filtre.
- Yeni kiralama 867-910; detay/operasyon penceresi 911-982 — kaydetme **iki ayrı istek** (önce composition 956, sonra başlık 958), atomik değil.
- Tahsis penceresi 984-1000; envanter ekle/düzenle 1001-1028; depo adı 1029-1033.
- Sorumlu listesi departman adı metin eşleşmesiyle (“Kiralama & Operasyon Yönetimi”) 757-760.

### 1.4 Uygulanan iş kuralları (çalışanlar)

- Çoklu ürün kalemi ve çoklu irtibat — var.
- Depo 1-3 ve yeniden adlandırma — var.
- Seri takipli ürün envantere tek tek ve seri ile girilir (1350-1351); ürün+seri tekil (SQL indeks).
- Aynı envanter satırı iki kaleme tahsis edilemez (1408) — `Serializable` + `UPDLOCK,HOLDLOCK` ile yarış durumuna karşı korumalı.
- Depoya dönen cihaz `Kontrolde` olur, otomatik `Hazır` sayılmaz (1474).
- Tahsisli kalem silinemez / modeli değiştirilemez (3215-3218, 1267-1274).

### 1.5 Tespit edilen hatalar ve boşluklar (özet; ayrıntı bölüm 3’te)

1. **Durum (12 adet) ile aşama logu (5 adet) birbirinden kopuk.** Aşama kaydı durumu değiştirmiyor; durum elle `Kapandı` yapılabilir, cihazlar hâlâ `Kirada` kalır.
2. **Aşama sırası doğrulanmıyor.** `Sevk Edildi` olmadan `Depoya Alındı` girilebilir; aynı aşama tekrar tekrar girilebilir (1441-1442).
3. **Depoya Alındı tüm cihazları depoya alıyor** (1472-1480): müşteride kalan, kaybolan, hasarlı cihaz da “depoda, kontrolde” görünür → envanter gerçeği yansıtmaz. Kısmi iade yok.
4. **Seri takipsiz toplu stok kısmen tahsis edilemiyor**: 50 adetlik bariyer satırı 20 adetlik kaleme atanamaz (1412), sevkte satırın tamamı `Kirada` olur.
5. **Seri takipli üründe sevk için tahsis şartı yok**: kalemde elle yazılmış seri yeterli sayılıyor; elle yazılan seri başka kiralamada mı kontrol edilmiyor → çift tahsis engeli delinebilir.
6. **İptal/Kapanışta tahsis çözülmüyor**: `İptal` edilen kiralamanın cihazları sonsuza kadar bağlı kalır, başka işe atanamaz.
7. **Tarih bazlı müsaitlik yok**: tahsis yalnızca “şu an boşta mı” üzerinden; gelecek etkinlik için cihaz ayırmak, bugünkü kiralamayı bloke eder.
8. Envanter düzenlemede durum serbest (`Kirada` elle verilebilir), `Kontrolde → Hazır` geçişi kontrol kaydı olmadan yapılır; kim kontrol etti bilinmez.
9. Kurulum/toplama ekibi serbest metin; teknik servis iş emri, planlama ve zaman takibiyle bağ yok.
10. Rapor, uyarı (geciken iade, eksik tahsis) yok.
11. `Depo` rol şablonunda yalnızca görüntüleme var; depo personeli depoya alma/kontrol yapamaz, buna karşılık `rentals.edit` sahibi her şeyi (envanter, depo adı, aşama) yapar.
12. Eşzamanlı düzenlemede son yazan kazanır; irtibatlar her kayıtta silinip yeniden yazıldığı için kayıp riski var.

---

## 2. Olması gereken (Denge Elektronik çalışma modeli)

### 2.1 Roller (VARSAYIM — organizasyon şeması gelince doğrulanacak)

| Rol | Bu modülde yaptığı | İzin önerisi |
|---|---|---|
| Kiralama Operasyon (Kiralama & Operasyon Yönetimi) | Talep/kiralama açar, kalem/irtibat/tarih girer, rezervasyonu onaylar, kapanışı yapar | rentals.view/create/edit |
| Depo & Lojistik | Envanter girişi, depo transferi, sevk hazırlığı (tahsis), sevk çıkışı, depoya alma, dönüş kontrolü | rentals.view + **rentals.inventory** + **rentals.stage** + **rentals.check** |
| Teknik Servis şefi | Kurulum / devreye alma / toplama işini ekip ve tarih ile planlar | workorders.plan/assign (iş emri modülü) |
| Teknisyen (Güvenlik / Haberleşme TS) | Kurulum, devreye alma, toplama aşamasını kendi iş emri üzerinden kaydeder; süre zaman takibinden gelir | workorders.edit/close |
| Atölye | Dönüş kontrolünde arızalı çıkan cihazın onarımı | workshop.manage |
| Yönetim | Kullanım oranı, geciken iade, kontrolde bekleyen raporları | reports.view/export |

### 2.2 Veri

- Kiralama başlığı: no, birim, müşteri, proje/etkinlik, lokasyon, başlangıç/bitiş, sorumlu, durum, notlar, `RowVersion`.
- Kalem: ürün, adet, not. **Seri bilgisi kalemde serbest metin değil, tahsis tablosundan gelir** (seri takipli ürünlerde).
- Tahsis (yeni, satır bazlı): kalem ↔ envanter + adet + tahsis/sevk/iade zamanları + iade sonucu (iade edildi / kayıp / hasarlı). Toplu stoğun kısmi tahsisini çözer.
- Envanter hareketi (yeni): giriş, transfer, tahsis, sevk, iade, kontrol, durum değişikliği; kim, ne zaman, önceki/sonraki depo-durum.
- Dönüş kontrol kaydı (yeni): cihaz, sonuç (Uygun / Eksik / Arızalı), eksik açıklaması, kontrol eden, zaman, gerekirse atölye/iş emri bağlantısı.
- Aşama kaydı: mevcut tablo + personel kimlikleri (serbest metin ekip yerine) + bağlı iş emri.
- İrtibat: kalıcı kimlik (silip-yaz yerine güncelle), “birincil irtibat” işareti.
- Seri numarası her yerde **metin** (karar).

### 2.3 Akış (durum makinesi önerisi)

```
Talep → Planlandı(rezerve) → Hazırlanıyor(tahsis) → Sevk Edildi → Kurulum Yapıldı → Devreye Alındı(=Kirada)
      → Toplandı → Depoya Alındı → Kontrol Tamamlandı → Kapandı
Her adımdan → İptal (sevk öncesi; tahsisler çözülür)
```

- Durum, aşama kaydının **sonucu** olur; elle seçilen ayrı bir durum alanı kalmaz (geçiş yalnızca aşama uçlarıyla).
- Kurulum/devreye alma aşamaları birim/ürüne göre opsiyonel olabilir (telsiz kiralamada çoğu zaman yok — kullanıcıya soruldu).
- Kapanış şartı: kiralamaya bağlı tüm cihazlar iade edildi + kontrol edildi **veya** kayıp/hasar olarak işaretlendi.

### 2.4 Doğrulamalar

- Seri takipli kalemde sevk için tahsis adedi = kalem adedi.
- Aynı cihaz aynı tarih aralığında iki kiralamaya rezerve/tahsis edilemez (tarih çakışması dahil).
- Toplu stokta tahsis edilen toplam adet, depo satırındaki boştaki adedi aşamaz.
- Aşama sırası geriye gidemez; aynı aşama ikinci kez girilemez (düzeltme ayrı bir “düzelt/geri al” işlemiyle, gerekçeli).
- `Kirada` durumu yalnızca sevk ile, `Hazır` durumu yalnızca kontrol ile oluşur; envanter düzenleme ekranından verilemez.
- Aşama zamanı kiralama başlangıcından çok önce / bugünden ileri olamaz (mevcut ±1 gün/10 yıl kuralı korunur).

### 2.5 Raporlar / KPI

- Depo bazında anlık durum (Hazır / Rezerve / Kirada / Kontrolde / Hazır Değil / Kayıp).
- Ürün bazında kullanım oranı: kirada geçen cihaz-gün / toplam cihaz-gün (dönem).
- Geciken iade listesi (bitiş tarihi geçmiş, cihaz hâlâ müşteride).
- Kontrolde bekleme süresi (depoya alındı → kontrol tamamlandı, gün).
- Dönüşte eksik/arızalı oranı, kayıp cihaz listesi.
- Seri bazlı cihaz geçmişi (hangi kiralamalar, hangi arızalar).
- Aşama süreleri yalnızca kayıtlı zamanlardan hesaplanır; kayıt yoksa **“eksik”** yazılır, 0 değil (karar).

---

## 3. Fark listesi (maddeler)

Sıralama: önce (c) YENİ, sonra (b) EKSİK/HATA/VERİ, en son (a) GÜVENLİK. Bu modülde veri sızıntısı yaratan **KRİTİK** güvenlik açığı tespit edilmedi; envanter gerçeğini bozan HATA maddeleri (M06-04, M06-12, M06-13) önceliklidir.

### (c) Yeni özellikler

#### M06-01 [YENİ] Tarih bazlı müsaitlik ve rezervasyon — Efor: M
- **Açıklama:** Ürün + tarih aralığı için “kaç adet müsait” sorgusu; kiralama `Planlandı` olduğunda kalem adetleri o tarih aralığı için rezerve sayılır. Çift tahsis kuralı tarih çakışmasıyla genişletilir.
- **Neden:** Etkinlik kiralamasında (X-Ray, kapı dedektörü, bariyer) asıl soru “o hafta sonu kaç cihazım boşta?”. Bugün yalnızca anlık durum var; gelecek iş için tahsis bugünü bloke ediyor.
- **Mevcut:** `allocate` yalnızca anlık `Hazır` + boş tahsis kontrolü (`Program.cs:1408`); tarih alanları (`StartDate/EndDate`) kontrolde kullanılmıyor.
- **Kabul:** (1) `GET /api/rentals/availability?productId&from&to` toplam, rezerve, müsait adedini döner. (2) 10 adet PG-5030 varken 1-5 Kasım için 8 adet rezerve edilmişse aynı tarihlerde 3 adet istenen kiralama `Planlandı`’ya geçemez (409, eksik adet mesajı); 10-12 Kasım için geçer. (3) İptal edilen kiralamanın rezervi anında düşer.
- **Roller:** Kiralama Operasyon (rentals.edit), Depo (rentals.view).
- **Veri:** Rezerve hesabı mevcut kalemler + durum + tarihten türetilir (yeni tablo gerekmez); `Hazır Değil/Kontrolde/Kayıp` cihazlar müsaitten düşülür.
- **Bağımlılık:** M06-11.

#### M06-02 [YENİ] Kurulum / devreye alma / toplama işlerinin teknik servis iş emrine bağlanması — Efor: L
- **Açıklama:** Kiralama detayından “Kurulum işi oluştur” ve “Toplama işi oluştur” ile ilgili birimin iş havuzuna iş emri açılır (müşteri, lokasyon, tarih, kiralama no, seri listesi taşınır). Şef bu işi normal planlama ekranında ekip/araç ile planlar; teknisyen kendi iş emrinde zaman sayacını kullanır. İş emri kapanışı ilgili aşamayı (Kurulum Yapıldı / Devreye Alındı / Toplandı) personel kimlikleriyle otomatik yazar.
- **Neden:** Kurulum ve toplama teknik servisin sahadaki gerçek işi; şu an ekip serbest metin, süre/kişi-saat ölçülemiyor, planlama takviminde görünmüyor.
- **Mevcut:** `RentalStageHistory.TeamName` serbest metin (`ZZ_V112...sql:80`, `app.js:941`); iş emri ile ilişki yok.
- **Kabul:** (1) Kiralamadan açılan iş emrinde kiralama no ve seri listesi görünür, iş emri listesinde “Kiralama” iş türüyle filtrelenir. (2) İş emri kapatılınca aşama kaydı oluşur; `TeamName` yerine atanmış personel adları ve iş emri no yazılır. (3) Aşama süresi iş emrinin zaman kayıtlarından gelir; zaman kaydı yoksa raporda “eksik” görünür. (4) Aynı kiralama için aynı türde açık ikinci iş emri açılamaz.
- **Roller:** Kiralama Operasyon (rentals.edit + workorders.create), Şef (workorders.plan/assign), Teknisyen (workorders.edit/close).
- **Veri:** `WorkOrders.RentalOrderId` (NULL’lanabilir FK) + `WorkOrders` iş türü “Kiralama Kurulum / Kiralama Toplama”; `RentalStageHistory.WorkOrderId`.
- **Bağımlılık:** M01 (iş emri), M02 (planlama), saha zaman modülü; M06-11.

#### M06-03 [YENİ] Depo dönüş kontrolü (cihaz bazlı kontrol kaydı) — Efor: M
- **Açıklama:** `Kontrolde` cihazlar için “Kontrol Et” ekranı: sonuç Uygun → `Hazır`; Eksik → `Hazır Değil` + eksik açıklaması zorunlu; Arızalı → `Hazır Değil` + isteğe bağlı atölye kaydı/iş emri açma. Kontrol eden ve zaman kaydedilir. Toplu “seçilenleri uygun işaretle” desteklenir.
- **Neden:** Belge kararı: “depoya dönen cihaz önce kontrol”. Bugün kontrol, envanter düzenleme ekranında durumu `Hazır` seçmekten ibaret; kim, ne zaman, ne buldu bilinmiyor.
- **Mevcut:** `POST /api/rentals/inventory` durum alanı serbest (`Program.cs:1341`), kontrol kaydı yok.
- **Kabul:** (1) `Kontrolde` olmayan cihaz kontrol edilemez (400). (2) `Hazır` durumu yalnızca bu uçla oluşur; envanter düzenleme ekranında `Hazır/Kirada` seçeneği yeni kayıt dışında sunulmaz. (3) Arızalı sonucunda “Atölye kaydı aç” işaretlenirse atölye kaydı oluşur ve cihaz kartında bağlantı görünür. (4) Kontrol listesi ekranı “kontrolde bekleme gün sayısı”nı gösterir.
- **Roller:** Depo & Lojistik (rentals.check — VARSAYIM), Atölye (workshop.manage).
- **Veri:** Yeni `RentalInventoryChecks` (InventoryId, RentalOrderId, Result, MissingNotes, CheckedByUserId, CheckedAt, WorkshopTicketId NULL).
- **Bağımlılık:** M06-07, M06-16.

#### M06-04 [YENİ/HATA] Cihaz bazlı (kısmi) sevk ve iade; kayıp/hasar kaydı — Efor: M
- **Açıklama:** Sevk ve depoya alma kiralamanın tamamı yerine **seçilen cihazlar/adetler** için yapılır. İade ekranında her tahsis satırı için: İade alındı (depo seç) / Müşteride kaldı / Kayıp / Hasarlı. Kayıp cihaz envanterde `Kayıp` durumuna geçer, müsaitten düşer.
- **Neden:** Etkinlik dönüşlerinde cihazlar farklı günlerde ve farklı depolara dönebilir; kayıp/hasar gerçek bir risk. Bugün `Depoya Alındı` kiralamadaki tüm cihazları depoda gösteriyor → fiziksel olarak olmayan cihaz “depoda” görünür (envanter kaybı fark edilmez).
- **Mevcut:** `Program.cs:1472-1480` tüm tahsisli cihazları tek depoya `Kontrolde` yapar; `Program.cs:1465-1471` sevk tüm `Hazır` tahsisleri `Kirada` yapar.
- **Kabul:** (1) 5 cihazlık kiralamada 3 cihaz Depo 1’e, 1 cihaz Depo 2’ye iade edilir, 1 cihaz “Kayıp” işaretlenir; envanterde 3+1 `Kontrolde`, 1 `Kayıp`. (2) Tüm cihazlar iade/kayıp/hasar sonucu almadan kiralama `Kapandı` olamaz. (3) Kısmi iadede kiralama durumu “Kısmi İade” gösterir. (4) Kayıp cihazı tekrar envantere almak gerekçe ister ve harekete yazılır.
- **Roller:** Depo & Lojistik (rentals.stage), Kiralama Operasyon (kapanış).
- **Veri:** M06-13’teki tahsis tablosuna iade sonucu/zamanı/depo; envanter durum listesine `Kayıp`.
- **Bağımlılık:** M06-13, M06-07.

#### M06-05 [YENİ] Sahada cihaz değişimi (arızalı cihazın yenisiyle değiştirilmesi) — Efor: S
- **Açıklama:** Kirada bir cihaz arızalanınca “Değiştir” işlemi: eski cihaz tahsisten çıkar (iade sonucu Arızalı, `Kontrolde`/atölye), yeni `Hazır` cihaz aynı kaleme tahsis + sevk edilir; tek işlem, tek hareket kaydı.
- **Neden:** Bugün sevk edilmiş kalemin tahsisi değiştirilemiyor (`Program.cs:1397-1398`); sahadaki değişim sisteme girilemiyor, seri listesi yanlış kalıyor.
- **Mevcut:** Değişim akışı yok.
- **Kabul:** (1) Değişim sonrası kalem seri listesinde yeni seri var, eski seri yok; eski seri cihaz geçmişinde “değiştirildi” görünür. (2) Yeni cihaz başka kiralamaya rezerveli ise işlem reddedilir. (3) İsteğe bağlı olarak arıza iş emri açılabilir.
- **Roller:** Depo & Lojistik, Teknisyen (rentals.stage).
- **Veri:** M06-13 tahsis tablosu + M06-07 hareket.
- **Bağımlılık:** M06-04, M06-13.

#### M06-06 [YENİ] Sevk / teslim ve iade tutanağı (yazdırılabilir) — Efor: S
- **Açıklama:** Kiralama detayından seri listeli “Teslim Tutanağı” ve “İade Tutanağı” çıktısı (HTML yazdır / PDF): müşteri, lokasyon, irtibat, kalemler, seri nolar, aksesuar/eksik notu, teslim eden/alan imza alanları. Fiyat içermez.
- **Neden:** Sahada kâğıt form ve WhatsApp ile dönen süreçler var; seri bazlı imzalı tutanak hem kayıp/hasar anlaşmazlığında kanıt hem dijital disiplin aracı.
- **Mevcut:** Yok (teklif PDF’i var, kiralama için yok).
- **Kabul:** (1) Tutanak yalnızca tahsis edilmiş cihazların serilerini listeler. (2) Sevk aşaması kaydedilmeden teslim tutanağı “TASLAK” filigranlı çıkar. (3) Çıktıda hiçbir fiyat/maliyet alanı yoktur.
- **Roller:** Kiralama Operasyon, Depo (rentals.view).
- **Veri:** Yok (mevcut veriden üretilir); isteğe bağlı imzalı tarama dosyası eki ileride.
- **Bağımlılık:** M06-13.

#### M06-07 [YENİ/VERİ] Envanter hareket geçmişi ve kiralama değişiklik izi — Efor: M
- **Açıklama:** Her envanter değişikliği (giriş, depo transferi, durum, tahsis, sevk, iade, kontrol, kayıp) `RentalInventoryMovements` tablosuna yazılır. Cihaz kartında seri bazlı zaman çizelgesi. Kiralama başlığındaki durum/tarih değişiklikleri de kim-ne zaman ile loglanır.
- **Neden:** “Bu cihaz şu an nerede, son kim aldı?” sorusu cevapsız; `UpdatedAt` tek alan. Kayıp/hasar sorumluluğu ve tekrar arıza analizi için zorunlu.
- **Mevcut:** Yalnızca `RentalStageHistory` (kiralama bazlı, cihaz bazlı değil), `RentalInventory.UpdatedAt`.
- **Kabul:** (1) Bir cihazın girişinden iki kiralama + bir depo transferine kadar tüm adımlar sıralı listelenir. (2) Hareket kayıtları API üzerinden düzenlenemez/silinemez. (3) Depolar arası transfer ayrı bir işlem olarak yapılır (envanter düzenlemede depo değiştirmek yerine) ve hareket yazar.
- **Roller:** Depo (rentals.view), Yönetim (reports.view).
- **Veri:** Yeni `RentalInventoryMovements` (InventoryId, Kind, FromWarehouseId, ToWarehouseId, FromStatus, ToStatus, Quantity, RentalOrderId, UserId, At, Note). Mevcut kayıtlar için “açılış” hareketi bir kez üretilir.
- **Bağımlılık:** Yok (diğer maddelerin temeli; önce yapılmalı).

#### M06-08 [YENİ] Kiralama ve depo raporları — Efor: M
- **Açıklama:** Rapor sayfası/Excel: depo bazlı durum, ürün bazlı kullanım oranı (cihaz-gün), geciken iadeler, kontrolde bekleme süresi, dönüş eksik/arıza oranı, kayıp listesi, aşama süreleri (iş emri zamanından). Mevcut 8 sayfalı Excel’e “Kiralama” sayfası eklenir.
- **Neden:** Yönetim hangi cihazın atıl, hangisinin yetersiz olduğunu göremiyor (yatırım/satın alma kararı).
- **Mevcut:** Kiralama sayfasında 4 sayaç (`app.js:864`), envanterde 3 sayaç (`app.js:845-848`); rapor ucu yok.
- **Kabul:** (1) Dönem seçilerek ürün bazında kullanım oranı hesaplanır; elle doğrulanan 2 örnekle aynı sonuç. (2) Zaman kaydı olmayan aşama süresi “eksik” yazılır. (3) Birim yetkisi dışındaki kiralamalar raporda yer almaz.
- **Roller:** Yönetim, Kiralama Operasyon (reports.view/export).
- **Veri:** Yok (M06-07 ve M06-13 verisinden).
- **Bağımlılık:** M06-07, M06-13.

#### M06-09 [YENİ] Kiralama uyarıları (operasyon merkezi) — Efor: S
- **Açıklama:** Mevcut ERP içi uyarı listesine: (a) bitiş tarihi geçmiş, cihazı müşteride olan kiralama; (b) 3 gün içinde başlayacak ama tahsisi eksik kiralama; (c) 5 günden uzun `Kontrolde` bekleyen cihaz; (d) müsaitlik açığı olan planlı kiralama.
- **Neden:** Geciken iade = kayıp gelir + bir sonraki etkinlikte eksik cihaz.
- **Mevcut:** `OpsSuite.cs:38-49` yalnızca yedek parça düşük stok uyarısı; kiralama uyarısı yok.
- **Kabul:** Her uyarı türü için test verisiyle uyarı üretilir, ilgili kiralamaya bağlantı verir, birim yetkisine uyar; eşik günleri ayar dosyasından okunur.
- **Roller:** Kiralama Operasyon, Depo (rentals.view).
- **Veri:** Yok.
- **Bağımlılık:** M06-01, M06-04.

### (b) Mevcut modül eksikleri / hataları

#### M06-10 [EKSİK] Kiralama ürün kataloğu yönetimi — Efor: S
- **Açıklama:** Ürün (birim, kategori, kod, marka/model adı, seri takipli mi, aktif, sıra) ekleme/düzenleme/pasifleştirme ekranı ve API.
- **Neden:** Yeni model alındığında kod/SQL değişikliği gerekiyor; seed `MERGE` her güncellemede adları geri yazıyor (`DengeERP_Update.sql:305`).
- **Mevcut:** Yalnızca `GET /api/rentals/catalog` (`Program.cs:961`).
- **Kabul:** (1) Yeni ürün eklenir, kiralama ve envanter ekranlarında listelenir. (2) Envanteri veya kalemi olan ürün silinemez, yalnızca pasifleşir. (3) Envanterinde seri girilmemiş satır varken “seri takipli”ye çevrilemez. (4) Güncelleme scripti kullanıcı tarafından eklenen/düzenlenen ürünleri ezmez.
- **Roller:** Kiralama Operasyon yöneticisi (rentals.catalog.manage — VARSAYIM).
- **Veri:** Seed `MERGE`’in `WHEN MATCHED UPDATE` kısmı kaldırılmalı/koşullanmalı.
- **Bağımlılık:** Yok.

#### M06-11 [HATA] Durum ile aşamaların birleştirilmesi ve sıra doğrulaması — Efor: M
- **Açıklama:** Kiralama durumu yalnızca aşama/işlem uçlarıyla ilerler (bölüm 2.3). Elle durum seçimi kaldırılır; geri alma ayrı, gerekçeli bir işlemdir.
- **Neden:** 12 durumlu açılır liste ile 5 aşamalı log birbirinden bağımsız; rapor ve KPI’lar yanlış (`Kirada` sayacı elle seçilen duruma bakıyor, `app.js:864`).
- **Mevcut:** `Program.cs:1146` durum serbest; `Program.cs:1436-1482` aşama durumu değiştirmiyor, sıra kontrolü yok.
- **Kabul:** (1) `Sevk Edildi` olmadan `Depoya Alındı` → 400. (2) Aynı aşama ikinci kez → 409. (3) `Sevk Edildi` kaydı durumu `Sevk Edildi` yapar. (4) Cihazı müşteride olan kiralama `Kapandı` yapılamaz. (5) Mevcut kayıtlar için durum, aşama geçmişinden bir kez yeniden hesaplanır; uyumsuz kayıtlar listelenir (otomatik düzeltilmez).
- **Roller:** Kiralama Operasyon, Depo.
- **Veri:** Durum listesi sadeleşir; geçiş scripti + uyumsuzluk raporu.
- **Bağımlılık:** Yok.

#### M06-12 [HATA] Seri takipli kalemde serinin envanterden gelmesi ve sevk şartı — Efor: S
- **Açıklama:** Seri takipli ürünlerde kalem seri alanı salt okunur olur, yalnızca tahsisten dolar. Sevk için tahsis adedi = kalem adedi şartı. Elle seri girişi kaldırılır.
- **Neden:** Elle yazılan seri başka kiralamada olsa bile kabul ediliyor → çift tahsis engeli delinebilir; seri zorunluluğu yalnızca ilk kaleme bakıyor.
- **Mevcut:** `app.js:770` serbest seri textarea; `Program.cs:1171` yalnızca başlık ürünü (ilk kalem) için seri kontrolü; sevkte tahsis şartı yok (`Program.cs:1465`).
- **Kabul:** (1) 3 adetlik seri takipli kalemde 2 cihaz tahsisliyken sevk → 400 “1 cihaz eksik”. (2) API’ye seri listesi gönderilse bile seri takipli kalemde yok sayılır. (3) İkinci kalemi seri takipli olan kiralamada da kural çalışır.
- **Roller:** Depo, Kiralama Operasyon.
- **Veri:** Mevcut elle girilmiş serilerin envanterle eşleşmeyenleri raporlanır (silinmez).
- **Bağımlılık:** M06-11.

#### M06-13 [HATA] Toplu (seri takipsiz) stokta adet bazlı kısmi tahsis — Efor: M
- **Açıklama:** Tahsis, “envanter satırı → kalem” yerine “envanter satırı + adet → kalem” olarak ayrı tabloda tutulur. 50 adetlik bariyer satırından 20’si bir kiralamaya, 30’u başka bir kiralamaya tahsis edilebilir.
- **Neden:** Bariyerler (seri takipsiz, en çok adetli ürünler) bugün pratikte tahsis edilemiyor; satırın tamamı kiraya çıkıyor ya da kullanıcı satırı elle bölmek zorunda.
- **Mevcut:** `RentalInventory.RentalOrderItemId` tek tahsis (`ZZ_V112...sql:62`); `Program.cs:1412` toplam adet > kalem adedi ise reddediyor; sevk satırın tamamını `Kirada` yapıyor (1467).
- **Kabul:** (1) 50 adetlik satırdan 20 + 30 iki farklı kiralamaya tahsis edilir; 51. adet istenirse 409. (2) 20’lik kiralamanın sevki yalnızca 20 adedi “kirada” sayar; depo kartında 30 hazır/rezerve görünür. (3) Seri takipli ürünlerde adet her zaman 1’dir. (4) Eşzamanlı iki tahsis isteğinde toplam stok aşılamaz (test).
- **Roller:** Depo (rentals.inventory).
- **Veri:** Yeni `RentalAllocations` (AllocationId, RentalOrderItemId, RentalInventoryId, Quantity, AllocatedAt, ShippedAt, ReturnedAt, ReturnResult, ReturnWarehouseId). Mevcut `RentalOrderItemId` bağlantıları bir kez taşınır; eski kolon geçiş sonrası salt okunur.
- **Bağımlılık:** M06-07.

#### M06-14 [HATA] İptalde tahsis/rezerv çözümü — Efor: S
- **Açıklama:** Sevk öncesi `İptal` edilen kiralamanın tüm tahsisleri çözülür ve hareket yazılır; sevk sonrası iptal engellenir (önce iade).
- **Neden:** İptal edilen kiralamanın cihazları başka işe atanamıyor; depo “boşta” göremiyor.
- **Mevcut:** `Program.cs:1174-1196` durum güncellemesi tahsise dokunmuyor.
- **Kabul:** (1) Tahsisli, sevk edilmemiş kiralama iptal edilince cihazlar `Hazır` ve boşta görünür. (2) Sevk edilmiş kiralamada iptal → 409. (3) İptal gerekçesi zorunlu.
- **Roller:** Kiralama Operasyon.
- **Veri:** Yok.
- **Bağımlılık:** M06-11.

#### M06-15 [VERİ] Tek istekte atomik kaydetme, eşzamanlılık ve irtibat kimliklerinin korunması — Efor: S
- **Açıklama:** Başlık + kalem + irtibat tek uçta, tek işlemde kaydedilir; `RowVersion` ile eşzamanlı düzenleme çakışması 409 döner. İrtibatlar silinip yazılmaz, kimlikle güncellenir; “birincil irtibat” işareti eklenir. `RentalOrders` içindeki eski tekil kopya alanlar (ürün, adet, seri, irtibat) artık yazılmaz.
- **Neden:** Bugün iki istekten ikincisi hata verirse kayıt yarım kalır; iki kişi aynı anda düzenlerse son yazan diğerinin irtibat değişikliğini siler.
- **Mevcut:** `app.js:956-964` iki ayrı istek; `Program.cs:3238-3240` irtibatlar silinip yeniden yazılıyor; `Program.cs:1280-1287` ve 1107/1127 eski alanlar ilk kalemden kopyalanıyor.
- **Kabul:** (1) Eski sürümle açılmış formu kaydetmek 409 “kayıt başka kullanıcı tarafından değişti” döner. (2) İrtibat düzenlendiğinde kimliği değişmez. (3) Başlık kaydı hata verirse kalem değişiklikleri de geri alınır. (4) Liste ekranı kalem özetini `RentalOrderItems`’tan okur.
- **Roller:** Kiralama Operasyon.
- **Veri:** `RentalOrders.RowVersion`, `RentalOrderContacts.IsPrimary`; eski kolonlar silinmez, yalnızca kullanılmaz (geri dönüş için).
- **Bağımlılık:** Yok.

### (a) Güvenlik / yetki / üretime hazırlık

#### M06-16 [GÜVENLİK] Kiralama yetkilerinin ayrıştırılması ve Depo rolünün işlevsel hale gelmesi — Efor: S
- **Açıklama:** `rentals.edit` tek anahtarının yaptığı işler ayrılır: `rentals.inventory` (envanter giriş/transfer/tahsis), `rentals.stage` (sevk/iade), `rentals.check` (dönüş kontrolü), `rentals.catalog.manage` (ürün + depo adı). Depo rol şablonuna inventory/stage/check eklenir (VARSAYIM). Depo adı değişikliği yedek parça depolarını da etkilediği için `warehouse.manage` ile de korunur.
- **Neden:** Depo rolü bugün hiçbir depo işlemi yapamıyor; buna karşılık kiralama açan kişi envanter durumunu, depo adını ve aşamaları serbestçe değiştirebiliyor (görev ayrılığı yok).
- **Mevcut:** `Program.cs:1326, 1338, 1380, 1440` hepsi `rentals.edit`; rol şablonları `Program.cs:3932-3933`.
- **Kabul:** (1) Yalnızca `rentals.view + rentals.check` sahibi kullanıcı kontrol yapabilir ama kiralama başlığını düzenleyemez (403). (2) `rentals.edit` sahibi ama `rentals.inventory` olmayan kullanıcı envanter ekleyemez (403). (3) Mevcut kullanıcıların yetkileri geçiş scriptiyle eşdeğer yeni anahtarlara açılır (kimse iş göremez hale gelmez).
- **Roller:** Tümü; izin kataloğuna 4 yeni anahtar.
- **Veri:** `ErpUsers.Permissions` geçişi.
- **Bağımlılık:** Kullanıcı/yetki modülü.

#### M06-17 [GÜVENLİK] Envanter düzenlemede birim ve durum kontrolleri — Efor: S
- **Açıklama:** Mevcut envanter satırı düzenlenirken eski satırın ürün birimi için de `UnitAllowed` kontrol edilir; `Kirada`, `Hazır` (kontrolden çıkış) ve `Kayıp` durumları düzenleme ucundan verilemez; depo değişimi transfer işlemine taşınır. Depo adı değişikliği hareket/denetim logu yazar.
- **Neden:** Bir birimin kullanıcısı başka birime ait cihazı kimliğiyle düzenleyip kendi ürününe çevirebiliyor; tahsissiz “Kirada” cihaz oluşturulabiliyor (hayalet kiralık cihaz).
- **Mevcut:** `Program.cs:1344-1349` yalnızca yeni ürünün birimi kontrol ediliyor; `Program.cs:1341` durum serbest; `Program.cs:1361-1363` depo/ürün/seri doğrudan güncelleniyor.
- **Kabul:** (1) Haberleşme yetkili kullanıcı Güvenlik Sistemleri cihazının kimliğiyle düzenleme yaparsa 403. (2) Düzenleme isteğinde `Kirada` → 400. (3) Tahsisli/kirada cihazın seri numarası değiştirilemez.
- **Roller:** Depo, Kiralama Operasyon.
- **Veri:** Yok.
- **Bağımlılık:** M06-03, M06-07.

---

## 4. Uygulama sırası önerisi (artımlı)

1. Temel: M06-07 (hareket), M06-13 (tahsis tablosu), M06-11 (durum makinesi), M06-15 (atomik kayıt).
2. Yeni özellikler: M06-04, M06-03, M06-01, M06-05, M06-06, M06-02 (iş emri modülü hazır olunca).
3. Eksikler: M06-12, M06-14, M06-10.
4. Görünürlük: M06-09, M06-08.
5. Yetki: M06-16, M06-17 (yeni uçlar yazılırken anahtarlar baştan doğru verilmeli; “güvenlik en son” sırası, yeni uçların yetkisiz yazılması anlamına gelmez).

Not: Kullanıcının (c)→(b)→(a) sırası korunmuştur; ancak M06-07 ve M06-13 veri yapısını değiştirdiği için yeni özelliklerden önce yapılmazsa M06-01/03/04/05 iki kez yazılmak zorunda kalır.

## 5. Varsayımlar

- Rol eşlemesi (Depo & Lojistik = depo işlemleri + kontrol; Kiralama & Operasyon Yönetimi = kiralama yönetimi; teknik servis = kurulum/toplama) organizasyon şeması gelene kadar varsayımdır.
- Kiralama ile yedek parça stoğu farklı iş mantığıdır (belge kararı); ancak aynı `RentalWarehouses` tablosunu paylaşmaya devam ettikleri varsayıldı.
- Müşteri ana verisi bu modülün işi değil; irtibatlar kiralamaya bağlı kalır, müşteri ana verisi gelince bağlanır.
- Fiyat/bedel alanı bu tasarıma eklenmedi; eklenirse `finance.prices.view` ile API seviyesinde gizlenmelidir.
- Aşama süreleri bordro değildir; yalnızca servis faaliyet süresidir.

## 6. Kullanıcıya sorular

1. Kurulum / devreye alma / toplama işleri teknik servis iş emri olarak mı açılsın (planlama + zaman takibi), yoksa kiralama ekranında yalnızca aşama kaydı yeterli mi?
2. Haberleşme (telsiz) kiralamalarında kurulum ve devreye alma aşamaları gerçekten var mı, yoksa telsizler yalnızca teslim/iade mi ediliyor? Birime göre farklı aşama seti istiyor musunuz?
3. Cihaz ne zaman bloke edilsin: teklif aşamasında mı, müşteri onayından (Planlandı) sonra mı?
4. Seri takipsiz ürünler (bariyerler) adet bazlı mı kalmalı, yoksa demirbaş/etiket numarasıyla tek tek mi izlenmeli?
5. Depo 1/2/3’ün gerçek adları ve konumları nedir? Yedek parça depoları ile aynı fiziksel depolar mı?
6. Dönüş kontrolünü kim yapar: depo personeli mi, teknik servis mi? Ürün tipine göre kontrol listesi (ör. X-Ray için test) gerekiyor mu?
7. Kayıp/hasarlı dönen cihazda süreç ne: yalnızca kayıt mı, yoksa müşteriye yansıtma (fatura/rücu) için muhasebeye bildirim mi?
8. Kiralama bedeli / günlük ücret ERP’de tutulacak mı? Tutulacaksa kimler görebilir?
9. Sahada kullandığınız basılı teslim/iade formu var mı? Örneğini paylaşabilir misiniz?
10. Kiralık cihazlar cihaz kütüğüne (müşteri cihazları) de kaydedilsin mi, yoksa yalnızca kiralama envanterinde mi kalsın?
11. Kiralama süresi uzatma sık oluyor mu? Uzatma ayrı kayıt mı olmalı, yoksa bitiş tarihini değiştirmek yeterli mi?
