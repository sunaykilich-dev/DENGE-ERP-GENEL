# UI/UX toplu raporu: rol testi bulguları (2026-11-06)

**Kaynak:** 2026-11-04 rol testinin 6 raporu (`1_ice_aktarim_operasyon.md`, `2_menu_link_yonetim.md`,
`3_yonetici_sef_planlama.md`, `4_sirket_sizinti_denetimi.md`, `5_teknisyen_saha_atolye.md`,
`6_satis_onay_finans_depo.md`). Ajanlar yerel ERP'yi (FastAPI + React/AntD, Fiori görünüm) farklı rollerle
arayüzden ve API'den kullandı. Tasarım hedefi için `analiz/FIORI_TASARIM_REHBERI.md` esas alındı.

**Kapsam:** Yalnız kullanıcıya görünen bulgular alındı: gezinme, menü, boş ya da kırık sayfalar, anlaşılmayan
ifadeler, tıklama sayısı, formlar, mobil (375 px), arayüzde alan olmadığı için API'ye başvurma, panel ile liste
arasındaki sayı farkları, geri bildirim ve erişilebilirlik. Ekranda görünmeyen arka uç ve güvenlik bulguları
(ör. S1, S2, S5, Y7, O10) bu rapora alınmadı.

**Durum yöntemi:** `denge-erp` main dalında `git log --since=2026-11-04` incelendi. Commit'ler: 5a51bf2, 6ba2586,
9298b7f, d9c4dc2, 1c2df55, 3b4aa60 ve abbacf0. Bazı bulgular ayrıca `frontend/src` içinde grep ile yoklandı. Kod
çalıştırılmadı, bu yüzden durumlar kesin değil.
- **Düzeltildi:** commit açıklamasında adıyla geçiyor ya da kodda karşılığı bulundu.
- **Kısmen:** bulgunun bir kısmı giderildi.
- **Açık:** iz yok.
- **Bilinmiyor:** hızlı yoklamayla karar verilemedi.

Kaynak sütunundaki kodlar raporlardaki numaralardır. Raporlarda aynı numara birden çok kez kullanıldığı için
(ör. B1) kod dosya numarasıyla verildi: `R3-B1` = 3. rapor, B1.

---

## 1. Gezinme, menü ve açılış

| No | Bulgu | Rol / ekran | Etki | Durum | Kaynak |
|---|---|---|---|---|---|
| G1 | `servis.gor` izni olmayan rollerde açılış sayfası Ana Panel. Ekranda yalnız "Ana panel yüklenemedi — yetkiniz yok" yazıyor. | Satış, Finans Uzmanı, Mobilite depo / açılış | Yüksek | Düzeltildi (5a51bf2: açılış ilk yetkili sayfa) | R2 B-01, R6 Y8 |
| G2 | Satış, Satış Destek ve Finans menülerinde Hesaplar, Teklifler ve Ürünler yok. Bu sayfalar yalnız Mobilite altında; ELEKTRONİK ve TELEKOM'da URL yazılarak açılıyor. | Satış, Satış Destek, Finans / sol menü | Yüksek | Düzeltildi (5a51bf2: "Satış ve Müşteri" bölümü) | R2 B-02, R6 D1 |
| G3 | Sayfa yüklenirken menü kısa süre bütün şirketlerin bölümlerini gösteriyor ve kırıntıda şirket adı yok. Kullanıcı başka şirketin menüsüne tıklayıp 403 alabiliyor. | Tüm roller / sol menü | Orta | Düzeltildi (5a51bf2: yükleniyor iskeleti, fail-closed) | R2 B-05, R1 B12 |
| G4 | Menüde olmayan sayfa URL ile açılınca başlıklar, boş tablo ve hatta yazma düğmeleri çiziliyor; arkada 403 dönüyor. "Yetkiniz yok" iletisi yok. | Tüm roller / URL ile erişim | Orta | Düzeltildi (5a51bf2: ortak rota kapısı) | R2 B-06 |
| G5 | Mobilite ekranı başka şirket etkinken açılınca "Veri Yok" gösteriyor. Sunucunun `SIRKET_DISI` iletisi ekrana gelmiyor, kullanıcı kaydın olmadığını sanıyor. | TELEKOM/ELEKTRONİK kullanıcıları / `/cihazlar`, `/hatlar` | Orta | Düzeltildi (5a51bf2: SIRKET_DISI ortak tanıma) | R4 S4 |
| G6 | Birimi olmayan kullanıcıya "Set Bariyer" grubu görünüyor. Liste "0 kayıt" diyor ama "Yeni iş aç" düğmesi etkin. | Operasyon (GUVENLIK) / sol menü | Düşük | Düzeltildi (5a51bf2: birim kapsamıyla süzme) | R1 B12 |
| G7 | "POC › Tüm işler" ile "Haberleşme › POC" aynı URL'yi kullanıyor; kırıntı ve vurgu yanlış yaprağı gösteriyor. Son açılanlarda iki tane bağlamsız "Tüm işler" var. | TELEKOM / menü, son açılanlar | Düşük | Düzeltildi (5a51bf2 küçükler) | R2 B-10 |
| G8 | Ana Panel'de KPI kartına tıklayınca kırıntı genel "Tüm Servis İşleri" oluyor, KPI adı görünmüyor. | Yönetici / Ana Panel → liste | Düşük | Düzeltildi (5a51bf2, 3b4aa60 KPI_ADLARI) | R2 B-11 |
| G9 | Servis tanımları ve içe aktarma ekranları menüde yok ama URL ile salt okunur açılıyor. Menü ile rota tutarsız. | Teknisyen, şef, YONETIM / URL | Düşük | Kısmen (rota kapısı var; menü kararı belirsiz) | R2 B-16 |
| G10 | Satış destek teklif hazırlanacak işleri bulamıyor. Menüdeki "Sonuçlanan Arıza İşleri" bunları göstermiyor ve bildirim de gelmiyor. | Satış Destek / menü | Orta | Kısmen (3b4aa60: "Teklif sunulacak" süzgeci var; ayrı yaprak ve bildirim yok) | R6 O11 |
| G11 | Girişte MOBİLİTE şirketi açılıyor, teknik servis ekranları boş geliyor. Son seçilen şirket hatırlanmıyor. | YONETIM, Finans Yöneticisi / giriş | Düşük | Açık | R6 D5 |
| G12 | 375 px'te üst çubuk şirketi kodla gösteriyor ("MOBILITE", İ'siz). | YONETIM / mobil üst çubuk | Düşük | Düzeltildi (5a51bf2 küçükler) | R2 B-15 |
| G13 | İK Personel ve Kiralamalar şeridinde etkin şirkete ait olmayan birimler var; bunlara tıklayınca liste boş geliyor. | YONETIM, Admin / şerit | Düşük | Düzeltildi (5a51bf2: şerit) | R2 B-13 |

## 2. Ana Panel ve sayı tutarlılığı (panel ↔ liste)

| No | Bulgu | Rol / ekran | Etki | Durum | Kaynak |
|---|---|---|---|---|---|
| P1 | "Açık" aynı ekranda üç farklı değer gösteriyor: KPI 98 (PB hariç), dağılım 116 ve aktif işler tablosu (PB dahil). | Yönetici / Ana Panel | Orta | Düzeltildi (1c2df55: tek açık tanımı) | R2 B-08, R6 D3 |
| P2 | "Tayin edilmemiş" KPI'ı şef ekibi olan işleri de sayıyor, oysa liste etiketi bu işler için "TAYİN EDİLDİ" diyor. Bariyer işleri hiç tayinli görünmüyor. | Yönetici, şef / Ana Panel, Servis Paneli | Yüksek | Düzeltildi (9298b7f: tek tanım, şef sorumlu olabilir) | R3 B1 |
| P3 | Kaynak görünümü bir ziyaretin süresini her cihaz için ayrı sayıyor: 300 dk'lık ziyaret 1560 dk görünüyor ve kapasite planı yanıltıyor. | Yönetici / Planlama › Kaynak | Yüksek | Düzeltildi (9298b7f) | R3 B2 |
| P4 | "Süre kaydı eksik" KPI'ı kısmi eksik işi göstermiyor, iş ayrıntısı ise aynı işi "KISMİ" gösteriyor. | Şef / Zaman Takibi | Orta | Düzeltildi (1c2df55) | R5 B4 |
| P5 | "Şef (kapanış onayı)" aksiyon sayısı (43) ile KPI (42) farklı; PB'yi biri sayıyor, diğeri saymıyor. | Yönetici / Ana Panel | Orta | Bilinmiyor (tek açık tanımı yapıldı; aksiyon satırı doğrulanmadı) | R6 O4 |
| P6 | Depo aksiyonu "3" diyor (MALZEME beklemesi), açık parça talebi ise 2. | Depo / Ana Panel | Düşük | Açık | R6 D6 |
| P7 | SLA riski hep 0 görünüyor, çünkü açık işlerin hepsi "Ölçülemedi" durumunda. Kart güven vermiyor; "SLA tanımsız: N" bilgisi yok. | Yönetici / Ana Panel | Orta | Açık (Ana Panel'de ölçülemeyen sayısı yok) | R3 B8, R6 D2 |
| P8 | POC kartı POC birimi olmayan şirkette 0 ile görünüyor. | YONETIM / Ana Panel | Düşük | Düzeltildi (1c2df55, 3b4aa60) | R2 B-12 |
| P9 | Dönem süzgecinin açık sayıları etkilemediği ekranda söylenmiyor. | Yönetici / Ana Panel | Düşük | Düzeltildi (ipucu `AnaPanelPage.tsx:763`) | R2 B-14 |
| P10 | Değişim göstergesi "↑ %2.400" gibi anlamsız yüzdeler çıkarıyor (küçük tabanda). | Yönetici / Ana Panel | Düşük | Açık (`Degisim` hep yüzde gösteriyor) | R3 B15 |
| P11 | Grup toplamı yok: üç şirketi görmek için 3 kez şirket değiştirmek gerekiyor. SLA uyum %, şehir dışı oranı ve kârlılık özeti panelde yok. | YONETIM / Ana Panel | Orta | Açık | R2 B-09, §4 |
| P12 | Teklif dönüşümü, fatura devri bekleyen ve tamamlanan sayıları için KPI kartı yok. | YONETIM / Ana Panel | Düşük | Açık | R6 D4 |
| P13 | Planı geçmiş açık işler yöneticiye görünmüyor: "Geciken plan" KPI'ı da takvimde gecikme rengi de yok. | Yönetici / Ana Panel, takvim | Orta | Kısmen (9298b7f: geçmiş tarih gerekçe istiyor; KPI ve renk yok) | R3 B6 |

## 3. Formlar, akış ve tıklama sayısı

| No | Bulgu | Rol / ekran | Etki | Durum | Kaynak |
|---|---|---|---|---|---|
| F1 | Operasyon listede olmayan müşteri için iş açamıyor. Formda yalnız "Müşteri İlişkileri'nden isteyin" yazıyor, iş tıkanıyor. | Operasyon / Yeni servis işi | Yüksek | Düzeltildi (9298b7f, d9c4dc2: "Hızlı ekle" `hesap.kart_yaz`) | R1 B1, B2 |
| F2 | Satış destek arayüzden hiçbir adımı yapamıyor: müşteri, tesis, ekipman ve kurulum işi açılamıyor. | Satış Destek / formlar | Yüksek | Düzeltildi (9298b7f, d9c4dc2: kurulum işi açma) | R1 B3 |
| F3 | Kullanıcılar ekranında şirket üyeliği alanı yok; admin bunu API ile yapmak zorunda kalıyor. Düzenle penceresinde birim de yok. | Admin / Sistem › Kullanıcılar | Yüksek | Düzeltildi (5a51bf2) | R2 B-03 |
| F4 | Saha rolü ile kullanıcı ayrı ekranlarda. Saha rolü boş olan kişi tayin listesine girmiyor ve Kullanıcılar ekranı bunu hiç söylemiyor. | Admin / Kullanıcılar ↔ İK Personel | Orta | Kısmen (Ana Panel'de "saha rolü tanımlanmalı" metni; Kullanıcılar ekranında yok) | R2 B-04 |
| F5 | Aynı tesisteki 6 cihaz için formu 6 kez doldurmak gerekiyor. Her yeni iş öncekiler için ayrı uyarı veriyor (toplam 73 uyarı). | Operasyon / Yeni servis işi | Orta | Kısmen (d9c4dc2: tek uyarı + bağlantılar; çok cihazlı tek form yok) | R1 B9 |
| F6 | Kurulum işi kurulacak cihazlara bağlanamıyor; "6 sattık, 2 kuruldu" ekrandan izlenemiyor. | Operasyon, Satış Destek / Kurulum işi | Orta | Bilinmiyor | R1 B10 |
| F7 | Yeni iş çekmecesi ilk ~1,5 sn'de Birim ve Tür alanlarını boş, kanalı ham kod ("TELEFON") olarak gösteriyor. | Operasyon / Hızlı oluştur | Düşük | Düzeltildi (5a51bf2) | R1 B11 |
| F8 | Servis işleri listesinde Müşteri sütunu yok; iş yalnız açıklamasıyla tanınıyor. | Tüm servis rolleri / liste | Düşük | Düzeltildi (5a51bf2) | R1 B13 |
| F9 | Asıl talep tarihi girilemiyor (7 gün sınırı); tarih açıklamaya yazılıyor. | Operasyon / iş açılışı (geçiş) | Orta | Düzeltildi (d9c4dc2: "Geçmiş kayıt (geçiş)" kutusu) | R1 B5 |
| F10 | Yurt dışı (KKTC, Nijerya) müşteri ve tesis girilemiyor. | Operasyon / il alanı | Düşük | Düzeltildi (d9c4dc2: İl seçici) | R1 B14 |
| F11 | Planda ulaşım türü (havayolu vb.) seçilemiyor. | Yönetici / Plan penceresi | Düşük | Açık | R1 B15 |
| F12 | Operasyon atölye kabulü açamıyor; kargoyla gelen cihazlar ARIZA işi olarak açılıyor. | Operasyon / Atölye | Yüksek | Düzeltildi (9298b7f, d9c4dc2: `atolye.kabul`) | R1 B4 |
| F13 | Atölye kabul formunda yalnız telsiz markaları var ve varsayılan birim HABERLESME. | Atölye (Güvenlik) / Kabul formu | Düşük | Düzeltildi (1c2df55, 3b4aa60) | R5 B12 |
| F14 | Geçmiş tarihe plan uyarısız kabul ediliyor. | Yönetici / Plan penceresi | Orta | Düzeltildi (d9c4dc2: gerekçe penceresi) | R3 B6 |
| F15 | Tekli plan ekipsiz ya da sahada kimsesiz olsa da "Planlandı" oluyor; toplu plan aynı durumu reddediyor. | Yönetici / Plan penceresi | Orta | Düzeltildi (9298b7f, d9c4dc2) | R3 B7 |
| F16 | Plan penceresinde iş no ve konu yok, sorumlu seçilemiyor. Tayin penceresinde ikinci alanın etiketi yok. | Yönetici / Plan, Ekip Tayini | Düşük | Kısmen (sorumlu seçimi geldi; başlıkta iş no/konu doğrulanmadı) | R3 B14 |
| F17 | Çok günlü saha işi (şehir dışı kurulum) tek planla girilemiyor. | Yönetici / Plan penceresi | Orta | Açık | R3 B9 |
| F18 | Şube turu (aynı gün, aynı ekip, birden çok tesis) tek seferde planlanamıyor; 9 ayrı plan gerekiyor. | Yönetici / Toplu planla | Orta | Açık (Faz B'ye ertelendi) | R3 B5 |
| F19 | Yanlış basılan "Yola Çıktım" geri alınınca iş YOLA ÇIKILDI'da kalıyor. Yöneticinin bunu düzeltecek düğmesi yok ve ayrıntı ekranı olmayan bir geçişi vaat ediyor. | Teknisyen, Yönetici / Mobil kart, iş ayrıntısı | Yüksek | Düzeltildi (1c2df55, 3b4aa60: "Yola çıkışı geri al") | R5 B1, R6 Y6 |
| F20 | Kalite onayında ret ya da geri gönderme düğmesi yok; reddedilecek iş kuyrukta süresiz bekliyor. | Şef, Yönetici / Kalite Onayı Bekleyen | Yüksek | Düzeltildi (3b4aa60: "Reddet / geri gönder") | R6 Y5 |
| F21 | Toplu kalite onayı yok: 45 iş × 2 onay, iş başına yaklaşık 6 tık. | Şef, Yönetici / Kalite Onayı Bekleyen | Orta | Düzeltildi (3b4aa60: "Seçilenleri onayla"; abbacf0 iki aşamalı kapanış) | R6 O3 |
| F22 | Kalite onayı penceresi işin süre kaydının eksik olduğunu söylemiyor. | Şef / Kalite onayı | Orta | Açık (iz bulunmadı) | R6 O2 |
| F23 | Teklif KABUL ya da RED sonrası iş İŞLEMDE'ye dönüyor, planlama havuzuna düşmüyor ve bildirim gitmiyor. Panel bu işi "sahada" sayıyor. | Yönetici, Satış Destek / teklif → iş | Yüksek | Düzeltildi (1c2df55: planlamaya dönüş + zil; abbacf0) | R6 Y1, Y2, O5 |
| F24 | Bakım formu talep listesinden gelen bakım işlerinde açılmıyor; ölçüm alanı ve uygunsuzluk önemi yok, bulgu konuya yazılmıyor. | Teknisyen / Bakım formu | Yüksek | Düzeltildi (1c2df55, 3b4aa60) | R5 B2, B3 |
| F25 | Bağlı yeni iş açan teknisyen işi hemen göremiyor (404) ve ilişki türünü seçemiyor. | Teknisyen / Bağlı yeni iş | Düşük | Düzeltildi (6ba2586, 3b4aa60: "Bağ türü") | R5 B8 |
| F26 | Tayinde ekipte sonuç girebilecek kimse yoksa uyarı çıkmıyor; iş tamamlanamaz hâle geliyor. | Yönetici / Ekip Tayini | Orta | Düzeltildi (1c2df55, 3b4aa60) | R5 B7 |
| F27 | Atölye ustası maliyet izni olmadan tamir bedeli girdiğinde değer sessizce kaydedilmiyor, hata iletisi çıkmıyor. | Atölye / Atölye ayrıntısı | Düşük | Düzeltildi (1c2df55: 403) | R5 B11 |
| F28 | Atölye ustası kendini işe tayin edemediği için süre giremiyor; atölye işleri hep "süre eksik" kapanıyor. | Atölye / Atölye, zaman | Orta | Düzeltildi (1c2df55) | R5 B5 |
| F29 | Fatura Devri ekranında iş no bağlantı değil; finans işin sonucunu ve imzasını göremiyor. | Finans / Fatura Devri | Orta | Açık | R6 O9 |
| F30 | Servis Maliyet raporunun süzgeç listeleri boş geliyor (sözlük 403). | Finans Uzmanı / Raporlar › Servis Maliyet | Orta | Düzeltildi (9298b7f) | R2 B-07 |

## 4. Mobil (375 px) ve saha ekranları

| No | Bulgu | Rol / ekran | Etki | Durum | Kaynak |
|---|---|---|---|---|---|
| M1 | Mobil kartta "Sonuç Gir" masaüstü listeyi ve ayrıntı penceresini açıyor. İmza ve parça ayrı yerlerde; en az 4 dokunuş ve sekme gezintisi gerekiyor. | Teknisyen / Mobil iş kartı | Orta | Düzeltildi (6ba2586: MobilSonucCekmecesi) | R5 B6 |
| M2 | Dokunma hedefleri küçük (24 px, 15 px, 32 px); 10 metin öğesi 12 px'in altında. | Teknisyen / Mobil iş kartı | Düşük | Düzeltildi (6ba2586: ≥ 44 px) | R5 B10 |
| M3 | Kapalı işte "Elle süre gir" ve "Sonuç Gir" düğmeleri görünüyor. | Teknisyen / Mobil kart | Düşük | Düzeltildi (6ba2586) | R5 B13 |
| M4 | Çevrimdışıyken sayfa geçişi tarayıcının hata sayfasına düşüyor. | Teknisyen / Mobil | Orta | Açık (PWA Faz B) | R5 §1.5 |

## 5. İfadeler, ham kodlar ve ekran sadeliği

| No | Bulgu | Rol / ekran | Etki | Durum | Kaynak |
|---|---|---|---|---|---|
| D1 | Listede ham kod "ASKIDA-BAKIM_UYGUNSUZLUK" görünüyor. Aynı durum Benim İşlerim'de "İŞLEM-ARA VERİLDİ", listede "ASKIDA" diye iki farklı adla geçiyor. | Teknisyen / liste, Benim İşlerim | Düşük | Düzeltildi (6ba2586) | R5 B9 |
| D2 | İş ayrıntısında 13 eylem düğmesi var, bunların 7'si durum düğmesi. Plan bilgisi ve "Planla" düğmesi yok (G1.9'a aykırı). | Yönetici / İş ayrıntısı | Orta | Açık (iz bulunmadı) | R3 B13 |
| D3 | Planlama ekranında 6 KPI kartı ekranın ~%60'ını kaplıyor ve takvim aşağıda kalıyor. Seçili gün değişse de kartta "Bugün planlı" yazıyor. | Yönetici / Planlama | Düşük | Açık | R3 B11 |
| D4 | Haftalık takvimde müşteri ve ekip adları kırpılıyor, "+4 daha" ile işler gizleniyor. | Yönetici / Planlama › Hafta | Düşük | Açık | R3 B12 |
| D5 | Günlük plan çıktısı yalnız Excel; ekibe gönderilecek PDF ya da görsel yok. | Yönetici, Şef / Planlama | Orta | Açık | R3 B10 |
| D6 | Tam gün izin metni "07.11.2026 00:00–00:00" biçiminde görünüyor. | Yönetici / Müsaitlik çakışma iletisi | Düşük | Bilinmiyor | R3 B16 |
| D7 | Talep kanalı sözlüğünde ekrandan seçilemeyen BAKIM_OTOMATIK kodu var. | Operasyon / form sözlüğü | Düşük | Bilinmiyor | R1 B17 |
| D8 | Bazı listeler yük altında 8–12 sn'de açılıyor. | Tüm roller / Tüm Servis İşleri, Personel | Düşük | Bilinmiyor (yeniden ölçülmedi) | R2 B-17 |

---

## Öncelikli 10 (açık ya da kısmen açık olanlar; etki ve kullanım sıklığına göre)

1. **P7.** Ana Panel'de "SLA tanımsız / ölçülemeyen: N" gösterilmeli. Şu an SLA riski hep 0 görünüyor ve yanıltıyor.
2. **D2.** İş ayrıntısındaki 7 durum düğmesi "Durum ▾" menüsünde toplanmalı. Genel sekmesine plan satırı ve "Planla" düğmesi eklenmeli (G1.9).
3. **P13.** "Geciken plan" KPI'ı eklenmeli ve takvimde gecikme rengi gösterilmeli.
4. **F22.** Kalite onayı penceresi süre kaydı eksik ya da kısmi olan işte uyarı vermeli ("süre eksik" kuralı).
5. **F5.** Yeni iş formunda cihaz listesi ya da adet girilerek aynı tesis için tek seferde N iş açılabilmeli.
6. **G10.** Satış destek için "Teklif hazırlanacak" menü yaprağı ve zil bildirimi eklenmeli.
7. **D5.** Planlamaya "Günlük plan PDF'i" eklenmeli: ekip, saat, müşteri, tesis, irtibat ve araç.
8. **F29.** Fatura Devri satırından salt okunur iş özeti açılabilmeli: sonuç, kalite onayı, imza.
9. **P11 / P12.** YONETIM için "Tüm şirketler" görünümü ya da şirket kırılımı, SLA uyum % ve teklif dönüşümü kartları.
10. **F4.** Kullanıcılar ekranında saha rolü (servis rollerinde varsayılan) ya da "Personel kartını aç" bağlantısı olmalı; tayin listesinde "saha rolü girilmemiş N kişi" uyarısı gösterilmeli.

Sonraki sırada: F17 (çok günlü plan), D3 ve D4 (planlama ekranı yoğunluğu), P10 (yüzde yerine fark), G11 (son
şirketi hatırlama), M4 (çevrimdışı gezinme).
