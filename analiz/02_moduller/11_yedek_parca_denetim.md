# M11 — Yedek Parça ve Servis Stoğu: Bağımsız Denetim

Tarih: 2026-10-21. Denetlenen belge: `analiz/02_moduller/11_yedek_parca_tasarim.md` (M11-01 … M11-19).
Kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api/` (salt okunur, değiştirilmedi).
Denetim yöntemi: tasarımcının her "mevcut durum" iddiası kod ve SQL şemasıyla tek tek karşılaştırıldı; kullanıcı kararlarıyla (kapsam yalnızca teknik servis, c→b→a önceliği, Logo/Flowick kapsam dışı, maliyet API seviyesinde gizli, roller VARSAYIM) çelişki arandı.

## 1. Genel sonuç

- Tasarımcının mevcut durum tespitleri **büyük ölçüde doğru**. Doğrulananlar: çıkış yalnızca `warehouse.manage` ile (`OpsSuite.cs:190`); bu izin yalnızca Admin'de `*` ile var (`Program.cs:3921-3935`); kapalı iş emri kontrolü yok (`OpsSuite.cs:193`, yalnızca `filterOrders`); iş emirli `Giriş` finans formülünde örtük iade sayılıyor (`OpsSuite.cs:225`, `ELSE -m.Quantity*m.UnitCost`); parça kodu tekrarında işlenmemiş SQL istisnası (`OpsSuite.cs:182-186`, `UNIQUE` kolon); birim sabit `Adet` (`OpsSuite.cs:185`); ekran satır bazında (`ops120.js:13`), uyarı toplam bazında (`OpsSuite.cs:44-46`); `prompt()` ile iç ID isteniyor (`ops120.js:85-89`); depo adı `rentals.edit` ile değişiyor (`Program.cs:1326`); bakım formunda parça serbest metin (`app.js:623, 647`; `Program.cs:2411, 2515-2526`).
- **KRİTİK açık yok** kararına katılıyorum: maliyet `finance.prices.view` olmadan `null` (`OpsSuite.cs:173`), negatif stok DB `CHECK` ile de engelli, hareket silme/güncelleme ucu yok. M11-15'teki sahte stok artışı gerçek bir veri bozulmasıdır ama bugün yalnızca Admin yapabildiği için KRİTİK değil, P1.
- **Tasarımcının kaçırdığı önemli teknik engel:** `ServicePartMovements.Kind` kolonu `NVARCHAR(10)` ve `CHECK(Kind IN(N'Giriş',N'Çıkış'))` **isimsiz** bir kısıt; `Quantity` için `CHECK(Quantity>0)` var (`ZZ_V120_Operations.sql:24`). Önerilen `Transfer Çıkış` / `Transfer Giriş` (14 karakter) ve `Sayım Farkı` (11 karakter) değerleri bu kolona **sığmaz**; M11-05'teki "Sayım Farkı −2" hareketi ise `Quantity>0` kısıtına takılır. Ayrıca finans formülü "Çıkış dışındaki her tür = alacak" varsayıyor; yeni türler eklenince iş emri malzeme tutarı yanlış hesaplanır. Bu yüzden M11-02/04/05/17'den önce bir altyapı maddesi gerekli (M11-D01).
- Aşırı mühendislik gördüğüm yerler: M11-08'deki kategori/uyumlu model/üretici no alanları, M11-10'daki depo bazlı minimum tablosu, M11-11'deki giriş maliyeti (maliyet yöntemi henüz kararlaştırılmadı), M11-19'un ayrı madde olması (maliyet gizleme her maddenin kabul kriterinde zaten var).

## 2. Madde madde karar

| ID | Başlık (kısa) | Karar | Öncelik | Gerekçe (özet) |
|---|---|---|---|---|
| M11-01 | İş emrinde "Kullanılan Parçalar" + `stock.use` | DEĞİŞTİR | P1 | İddia doğru; modülün asıl değeri bu. Ancak tek ortak stok kayıt fonksiyonu kullanılmalı (D01), GET ucu `workorders.view` + `filterOrders` ile korunmalı, Teknisyen erişimi bugünkü ad eşleşmesine bağlı (`Program.cs:3499-3500`). |
| M11-02 | İade ve ters kayıt | DEĞİŞTİR | P1 | Gerekli. Ancak `Kind NVARCHAR(10)` ve isimsiz CHECK nedeniyle D01 önce gelmeli; finans formülü tür bazlı işaretle yeniden yazılmalı. |
| M11-03 | Hareket geçmişi ekranı/API | KABUL | P2 | GET ucu gerçekten yok; `Csv()` yardımcı fonksiyonu mevcut (`OpsSuite.cs:66-70`). İş akışını bloke etmiyor, denetim için gerekli. |
| M11-04 | Depolar arası transfer | DEĞİŞTİR | P2 | Gerekli ve doğru; ancak `Transfer Çıkış/Giriş` 10 karaktere sığmaz → D01'e bağımlı. Efor S kalır. |
| M11-05 | Stok sayımı | DEĞİŞTİR | P2 | Gerekli; ancak `Quantity>0` kısıtı nedeniyle negatif "Sayım Farkı" yazılamaz. Yön ayrı kolonda veya iki türle (`Sayım Fazlası`/`Sayım Eksiği`). Onay yetkisi Soru 7 cevabına kadar `warehouse.manage`. |
| M11-06 | Parça talebi + malzeme bekleme | DEĞİŞTİR | P2 | Faydalı ama tasarımcının kendisi de kullanıcıya soruyor (Soru 9). Kapsam daraltılmalı: talep + depo listesi + otomatik "Karşılandı"; "Parça geldi" uyarısı mevcut hesaplanan uyarı mekanizmasıyla, ortalama bekleme raporu M11-07'ye. |
| M11-07 | Tüketim raporu + seri bazlı geçmiş | DEĞİŞTİR | P2 | Proje Geçmişi §7.1 isteği. Ancak servis iş emirlerinde `SerialNumbers` virgüllü metin; çok serili işte parça tek seriye atfedilemez. Seri bazlı geçmiş yalnızca tek serili işler (PB: 1 cihaz = 1 iş emri) için kesin, diğerleri "iş emri bazında" gösterilmeli. |
| M11-08 | Parça kartı düzenleme/pasif/birim | DEĞİŞTİR | P2 | Düzenleme/pasif/409 gerekli. Kategori, uyumlu model, üretici no, teknik birim alanları P3'e (kullanıcı ihtiyacı doğrulanmadı). |
| M11-09 | Form tabanlı, aranabilir stok ekranı | KABUL | P2 | İddia doğru (`ops120.js:84-92`); iç ID yazdırmak yanlış işe/depoya kayıt riski yaratıyor. |
| M11-10 | Az stok ekran/uyarı tutarsızlığı | DEĞİŞTİR | P2 | Hata gerçek. Ancak düzeltme için yeni `ServiceStockMinimums` tablosu gerekmez: önce ekran ve uyarı tek (toplam bazlı) fonksiyona bağlanır; depo bazlı minimum kullanıcı isterse P3. |
| M11-11 | Girişte belge no/not/maliyet | DEĞİŞTİR | P2 | Belge no + not gerekli ve ucuz. `EntryUnitCost` maliyet yöntemi kararı (Soru 5) gelene kadar ertelenmeli (P3). |
| M11-12 | Rol şablonlarında stok izinleri | DEĞİŞTİR | P1 | İddia doğru: `Depo` şablonunda bile `warehouse.manage` yok (`Program.cs:3932`). Ancak Teknisyene `warehouse.view` verilmesi düşük stok uyarılarını tüm teknisyenlere taşır (D03). Roller VARSAYIM. |
| M11-13 | Bakım formu/atölyede yapılandırılmış parça | KABUL | P2 | Çift kayıt sorunu gerçek (`app.js:623`). M11-01 bileşeninin yeniden kullanımı; serbest metin korunur. |
| M11-14 | Kapalı/iptal işe çıkış | DEĞİŞTİR | P1 | Hata gerçek (`OpsSuite.cs:193`, `Open()` fonksiyonu aynı dosyada var ama stokta kullanılmıyor). İstisna yolu (gerekçeli `warehouse.manage`) kullanıcı kararı (Soru 8) gelene kadar kapalı tutulmalı. |
| M11-15 | İş emirli Giriş sınırsız | DEĞİŞTİR | P1 | Hata gerçek. "Reddet veya sınırla" belirsizliği kaldırılmalı: M11-02 gelene kadar tek iade yolu bu olduğu için **net çıkışla sınırla**. |
| M11-16 | Adet biriminde ondalık | KABUL | P2 | İddia doğru (`OpsSuite.cs:191` yalnızca aralık kontrolü). Ucuz; M11-08'deki `AllowFraction` ile. |
| M11-17 | Açılış stoğu + mutabakat | DEĞİŞTİR | P1 (açılış) / P2 (mutabakat) | Gerçek stok yüklenmeden M11-01'deki her çıkış "Stok yetersiz" döner; bu yüzden açılış yüklemesi canlı kullanım için bloke edicidir. Mutabakat raporu P2. `Açılış` türü D01'e bağlı. |
| M11-18 | Eski serbest metnin korunması | KABUL | P3 | Doğru bir kısıt; ayrı iş değil, M11-13/M11-07 kabul kriteri olarak uygulanır. |
| M11-19 | Defter değiştirilemezliği, depo adı, maliyet | DEĞİŞTİR | P3 | KRİTİK değil (katılıyorum). Maliyet gizleme her maddenin kabulünde zaten var, ayrı madde gereksiz; kalan kısımlar (DB izni, depo adı yetkisi, maliyet yazma için `finance.prices.view`) üretime hazırlık kapsamında P3. |

## 3. Değiştirilen maddelerin düzeltilmiş hali

**M11-01 (P1, L):** İş emri detayına "Kullanılan Parçalar" bölümü. `GET /api/workorders/{id}/parts` için `workorders.view` + `FilterWorkOrdersForUser` erişimi; `POST` için `stock.use` + aynı erişim + iş emri açık (M11-14). Yazma işlemi D01'deki tek stok kayıt fonksiyonundan geçer (Serializable + `UPDLOCK,HOLDLOCK`, bakiye ve hareket aynı işlemde). Teknisyen yalnızca atandığı işe yazar (bugünkü ad eşleşmesi; M01'de kimlik bağlantısı gelince ona geçer). Kabul: tasarımcının 5 kriteri + (6) başka birimdeki/atanmadığı işe POST 403/404 döner, (7) yanıt ve iş emri detayında `unitCost`/tutar anahtarı `finance.prices.view` yoksa hiç yer almaz.

**M11-02 (P1, M):** `İade` ve `Ters Kayıt` türleri; `ReversalOfMovementId` + filtreli UNIQUE indeks; `Note` zorunlu (ters kayıtta). Finans malzeme formülü (`OpsSuite.cs:224-226`) tür→işaret eşlemesiyle yeniden yazılır (Çıkış +, İade −, Ters Kayıt orijinalin tersi; iş emirsiz türler hariç). Kabul: tasarımcının 5 kriteri + (6) iş emirli bir Giriş'in ters kaydı malzeme tutarını yanlış yöne değiştirmez. Bağımlılık: D01, M11-01.

**M11-04 (P2, S):** Tasarımcının tanımı aynen; Kind değerleri D01'deki genişletilmiş kolonla. Kabul + (4) pasif depoya transfer 400.

**M11-05 (P2, M):** Sayım farkı iki türle (`Sayım Fazlası` / `Sayım Eksiği`) veya D01'deki yön kolonu ile, `Quantity>0` korunarak yazılır. Sayım satırında sistem miktarı anlık görüntüsü tutulur; onay anında bakiye sayım başlangıcından beri değişmişse fark yeniden hesaplanır ve kullanıcı uyarılır. Onay yetkisi Soru 7 cevaplanana kadar `warehouse.manage`. Kabul: tasarımcının 4 kriteri.

**M11-06 (P2, M):** Parça talebi (katalog parçası + miktar + not), depo ekranında açık talep listesi, aynı iş emrine o parçadan çıkış yapılınca otomatik "Karşılandı", iş emri kapanınca/iptal edilince "İptal". "Parça geldi" uyarısı mevcut hesaplanan uyarı listesine (`AuxiliaryAlerts`) talep sahibine özel satır olarak eklenir; ayrı bildirim altyapısı kurulmaz. İş emrini bekletme mevcut `/api/ops/workorders/{id}/hold` akışıyla isteğe bağlı. Ortalama bekleme günü raporu M11-07'ye taşınır. Kullanıcı Soru 9'a "istemiyoruz" derse madde düşer.

**M11-07 (P2, M):** Parça × ay tüketimi; birim, müşteri, iş türü kırılımı (servis / planlı bakım ayrı); iş emri başına parçalar; Excel'e "Malzeme Hareketleri" sayfası. Seri bazlı geçmiş yalnızca iş emrinde tek seri olduğunda seri numarasına atfedilir; çok serili işlerde "iş emri bazında" gösterilir, parça uydurularak seriye bağlanmaz. Tutarlar yalnızca `finance.prices.view` ile. Kabul: tasarımcının 4 kriteri + (5) çok serili bir işte parça hiçbir seriye otomatik bağlanmaz.

**M11-08 (P2, M):** `PUT /api/ops/stock/part/{id}`: ad, birim (Adet/Metre/Takım/Litre), `AllowFraction`, minimum, aktif/pasif; kod tekrarında 409 "Bu parça kodu zaten kayıtlı." (hem POST hem PUT); `UpdatedBy/UpdatedAt`. Pasif parçaya giriş/çıkış/transfer 400, iade ve ters kayıt çalışır. Kategori, teknik birim, uyumlu model, üretici no: P3, kullanıcı ihtiyacı doğrulanınca.

**M11-10 (P2, S):** Ekran rozeti ve uyarı aynı hesaplamayı (parça toplamı < minimum) kullanır; ekran parça başına toplam + depo kırılımı gösterir; bakiyesi olmayan parça "Stok yok" yazar (sahte "Kayıt bekliyor" deposu kalkar, `OpsSuite.cs:168`). `ServiceStockMinimums` tablosu yalnızca kullanıcı depo bazlı minimum isterse (P3). Kabul: (1) Depo1=5, Depo2=0, min=3 → ekran ve uyarı "Yeterli", (2) min=0 için uyarı yok, (3) Az stok filtresindeki sayı = Uyarılar'daki düşük stok sayısı.

**M11-11 (P2, S):** Girişe `DocumentNo NVARCHAR(50) NULL` ve `Note NVARCHAR(500) NULL`. `EntryUnitCost` maliyet yöntemi (Soru 5) kararlaştırılınca eklenir (P3). Kabul: (1) belge no ile hareket geçmişinde arama, (2) uzunluk aşımı 400.

**M11-12 (P1, S):** `stock.use` izni `Permissions` kataloğuna eklenir. Şablon önerisi (VARSAYIM): Depo → `warehouse.view` + `warehouse.manage`; Teknisyen, Şef → `warehouse.view` + `stock.use`. Mevcut kullanıcılara otomatik dağıtılmaz; yönetici kişi bazında verir. D03 ile birlikte uygulanmalı (teknisyenlere düşük stok uyarısı yağmasın). Kabul: tasarımcının 3 kriteri + (4) kullanıcı yönetimi ekranında yeni izin Türkçe açıklamasıyla görünür.

**M11-14 (P1, S):** Çıkış (ve iade hariç iş emrine bağlı tüm hareketler) yalnızca `Open(status)` olan işe yapılır; aynı dosyadaki `Open()` fonksiyonu kullanılır. Kapalı işe sonradan parça yazma istisnası kullanıcı Soru 8'e "izin verilsin" derse eklenir (`warehouse.manage` + zorunlu gerekçe); o zamana kadar tamamen yasak. Kabul: (1) Kapatıldı/Tamamlandı/İptal işe çıkış 400 "Kapalı iş emrine parça yazılamaz." (2) Beklemede işe çıkış başarılı.

**M11-15 (P1, S):** M11-02 gelene kadar iş emirli `Giriş`, o iş emrinde o parçanın net çıkışıyla sınırlandırılır (reddedilmez; çünkü şu an tek iade yolu bu). M11-02 sonrası iş emirli iade yalnızca `İade` türüyle. Kabul: tasarımcının 2 kriteri.

**M11-17 (P1 açılış / P2 mutabakat, M):** (a) Açılış stoğu CSV (parça kodu, depo, miktar) → `Açılış` hareketleri; tek satır hatalıysa hiçbiri yüklenmez, hatalı satır numaraları raporlanır; aynı (parça, depo) için ikinci açılış reddedilir. (b) Mutabakat: (parça, depo) başına Σ(işaretli hareket) ile bakiye karşılaştırması; fark varsa yönetim uyarısı. Kabul: tasarımcının 4 kriteri. Bağımlılık: D01.

**M11-19 (P3, S):** (1) Uygulama SQL kullanıcısında `ServicePartMovements` için UPDATE/DELETE izninin kaldırılması İT ile değerlendirilir. (2) Depo adı değişikliği `rentals.edit` **veya** `warehouse.manage` yerine kullanıcı Soru 10'u cevaplayınca netleşir. (3) Parça kartına maliyet yazmak `finance.costs.manage` + `finance.prices.view` ister. Maliyet gizleme her maddenin kendi kabul kriterinde test edilir; ayrı madde olarak izlenmez.

## 4. Tasarımcının kaçırdığı maddeler

### M11-D01 — VERİ — Hareket türü altyapısı ve tek stok kayıt fonksiyonu (P1, M)
- **Sorun:** `ServicePartMovements.Kind NVARCHAR(10)`, isimsiz `CHECK(Kind IN(N'Giriş',N'Çıkış'))` ve `CHECK(Quantity>0)` (`ZZ_V120_Operations.sql:24`). `Transfer Çıkış`, `Transfer Giriş` (14 karakter) ve `Sayım Farkı` (11) sığmaz; negatif sayım farkı yazılamaz; finans formülü (`OpsSuite.cs:225`) Çıkış dışındaki her türü alacak sayar. Şema scriptleri `IF OBJECT_ID ... IS NULL` kalıbında olduğu için mevcut kurulumda tablo yeniden oluşturulmaz; değişiklik yeni, tekrar çalıştırılabilir bir script ister.
- **Çözüm:** Yeni `ZZ_V121_StockLedger.sql`: `Kind` → `NVARCHAR(30)`; isimsiz CHECK `sys.check_constraints` üzerinden bulunup düşürülür ve isimli yeni CHECK eklenir; `Direction SMALLINT NOT NULL (+1/−1)` kolonu (mevcut satırlar Kind'dan doldurulur). Tüm stok yazma işlemleri (çıkış, iade, ters kayıt, transfer, sayım, açılış) tek bir C# fonksiyonundan geçer: Serializable + `UPDLOCK,HOLDLOCK`, bakiye + hareket aynı işlemde, negatif bakiye engeli. Finans, rapor ve mutabakat `Quantity*Direction` kullanır.
- **Kabul:** (1) Script iki kez çalıştırıldığında hata vermez. (2) Mevcut Giriş/Çıkış satırlarının `Direction` değerleri doğru (+1/−1). (3) Finans ekranındaki iş emri malzeme tutarları yükseltme öncesi ve sonrası aynıdır. (4) Kodda `ServiceStockBalances` üzerinde UPDATE/INSERT yapan tek yer bu fonksiyondur.
- **Bağımlılık:** M11-02, M11-04, M11-05, M11-17 bu maddeye bağlıdır.

### M11-D02 — EKSİK — Stok modülü örnek verisi ve kabul test senaryoları (P2, S)
- **Sorun:** Proje Geçmişi "V1.20 stok düşümü … örnek kayıtlarla sınanması" maddesini açık bırakıyor; `TEST_SONUCLARI_V120.txt` dışında stok için tekrar çalıştırılabilir senaryo yok. Kullanıcı test verisinin bizde olacağına karar verdi.
- **Çözüm:** Yalnızca test veritabanında çalışan seed scripti (3 depo, ~30 parça, birkaç açık/kapalı iş emri) ve eşzamanlı çıkış, kapalı işe çıkış, iade sınırı, transfer, sayım, maliyet gizleme senaryolarını içeren kabul test listesi.
- **Kabul:** (1) Seed yalnızca test DB adında çalışır, canlı DB'de reddeder. (2) Senaryoların tümü M11-01…M11-17 kabul kriterlerine bire bir eşlenir. (3) İki paralel 1 adetlik çıkışta bakiye 1 iken biri 400 döner.

### M11-D03 — EKSİK — Düşük stok uyarısının hedef kitlesi (P2, S)
- **Sorun:** Düşük stok uyarısı `warehouse.view` olan herkese çıkıyor (`OpsSuite.cs:42`) ve görüldü anahtarı günlük (`stock:{id}:{yyyyMMdd}`, `OpsSuite.cs:48`), yani her gün yeniden çıkıyor. M11-12 ile Teknisyen ve Şef'e `warehouse.view` verildiğinde tüm teknisyenlerin Uyarılar sekmesi her gün düşük stok satırlarıyla dolar ve iş uyarıları kaybolur.
- **Çözüm:** Düşük stok uyarısı yalnızca `warehouse.manage` sahiplerine (ve isteğe bağlı yöneticilere) üretilir; görüldü anahtarı gün yerine "eşik altına düştüğü an"a bağlanır (bakiye eşiğin üstüne çıkıp yeniden düşerse yeni uyarı).
- **Kabul:** (1) Yalnızca `warehouse.view` + `stock.use` olan teknisyen düşük stok uyarısı görmez. (2) Depo sorumlusu gördü olarak işaretlediği uyarıyı ertesi gün tekrar görmez; parça eşik üstüne çıkıp yeniden düşerse yeni uyarı görür.

## 5. Önerilen uygulama sırası

1. P1 hata ve altyapı: M11-14, M11-15, M11-D01.
2. P1 yeni özellik: M11-01 + M11-12 (+ M11-D03), M11-02, M11-17 (açılış).
3. P2: M11-09, M11-10, M11-16, M11-08, M11-11, M11-13, M11-03, M11-04, M11-05, M11-07, M11-06, M11-D02, M11-17 (mutabakat).
4. P3: M11-18, M11-19, M11-08/10/11'in ertelenen parçaları.

Not: Kullanıcının c→b→a sırası korunmuştur; ancak M11-14, M11-15 ve M11-D01 "yeni özelliklerin doğru çalışması için ön koşul" olduğundan en başa alınmıştır. Bunlar S/M eforlu, kısa işlerdir.

## 6. Kullanıcı cevabına bağlı kalan maddeler

- Soru 1 (araç stoğu): Cevap "evet" ise M11-01'deki depo seçimi teknisyen/araç deposunu varsayılan yapmalı; yeni madde gerekir.
- Soru 5 (maliyet yöntemi): M11-11 `EntryUnitCost`.
- Soru 7 (sayım onayı): M11-05 onay izni.
- Soru 8 (kapalı işe parça): M11-14 istisna yolu.
- Soru 9 (parça talebi isteniyor mu): M11-06'nın varlığı.
- Soru 10 (depo adı yetkisi): M11-19 (2).
