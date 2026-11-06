# Rol testi 1. aşama: Operasyon Uzmanı + Satış Destek, iş açılışı (2026-11-04)

Ortam: yerel deneme (API 127.0.0.1:8000, web 127.0.0.1:5173). Kod değiştirilmedi. Kişi adı, telefon, plaka ve parola
bu rapora ve üretilen dosyalara yazılmadı. PERSONEL sütunu test kullanıcılarına eşlendi; eşleme yalnız bellekte tutuldu.
NOT sütunundaki adlar maskelendi.

Üretilen dosyalar:
- `analiz/rol_testi/acilan_isler.json`: 110 servis işi ve 145 ekipman. Her işte no, birim, tür, hedef durum, plan bilgisi
  ve eşlenen test teknisyeni var. 2. aşama bunu kullanacak.
- `analiz/rol_testi/acilan_isler_olaylar.json`: 403 alıp yedek kullanıcıyla tamamlanan eylemler ve sistem uyarıları.
- `araclar/talep_listesi_yukle.py`: yeniden kullanılabilir içe aktarma betiği. `--bolum A|B|TELEKOM|BARIYER|hepsi`,
  `--kuru` seçenekleri var; yeniden çalıştırıldığında aynı kaydı ikinci kez açmaz. Parolayı dosyadan okur. Ek ad maskesi
  isteğe bağlı olarak `.yerel_gizli/ad_maskesi.txt` dosyasından okunur (git dışı).

## 1. Ne yaptım

### 1.1 Güvenlik talep listesi, A bölümü (müşteri talepleri)
- Hesap: t_ops_guv, etkin şirket ELEKTRONIK, birim GUVENLIK. Listede 44 satır var (2–41 ve 69–72).
  **74 iş** açıldı: **SRV-202611-000023 … SRV-202611-000096**.
- Tür eşlemesi (§7.5'e göre):

  | Liste | ERP türü | Adet |
  |---|---|---:|
  | Bakım ve kalibrasyon | Bakım (PLANSIZ_BAKIM) | 43 |
  | Arıza, tespit, tamir, parça değişimi | ARIZA | 16 |
  | Kurulum ve teslim | KURULUM | 8 |
  | Eğitim ve depo işleri | DESTEK | 4 |
  | Arızalı/onarılmış parçayı teslim alma | TASIMA | 1 |
  | İkame cihazı geri alma | TOPLAMA | 1 |
  | Kıbrıs konveyör teslimi | KURULUM | 1 |

  Toplam 74. Birden çok işi olan satırlar ayrı işlere bölündü: "bakım + anakart değişimi" (bakım + arıza), "kurulum +
  eğitim" (kurulum + destek), "eğitim + KMD arızası" (destek + arıza).
- **1 cihaz = 1 iş** uygulandı. Örnekler: "6 adet SC-5030A bakımı" 6 ayrı iş oldu; KİPA AVM'nin 9 şubesindeki 18 cihaz
  18 iş oldu; "3 arızalı X-Ray" 3 ARIZA işi oldu. Seri numarası bilinmediği için seri alanı boş bırakıldı ve
  açıklamaya "Seri no bilinmiyor (seri bekleniyor)" yazıldı.
  - Sistem seri olmadan açılışı kabul ediyor.
  - Tek işte iki seri girilirse 400 dönüyor: "'Arıza' işinde en çok 1 cihaz … her cihaz için ayrı iş açın". Kural doğru.
- İletişim kişisi için kurgusal "Tesis Teknik Sorumlusu" ve "0 555 000 00 00" kullanıldı. Talep kanalı DIGER seçildi.
- Planlanan tarih ve durum işlenmedi. Her iş için `hedef` yazıldı: 49 TAMAMLANDI, 25 PLANLANDI, 8 BEKLEMEDE, 6 İŞLEMDE,
  1 PLANLAMADA (ERTELEME). TAMAMLANDI hedeflerinde sonuç (ÇÖZÜLDÜ veya TEKLİF_SUNULACAK) ve "süre kaydı eksik" notu var.
  "Leke atıyor" ve "anakart donma" gibi bulgu içeren notlar `hedef.bulgu` alanına işaretlendi (BAKIM_BULGUSU önerisi).
- Müşteri ve tesis: 30 müşteri listede yoktu. t_ops_guv'un hızlı müşteri açma isteği 403 aldı, t_sdestek_guv'unki de
  403 aldı. Müşteriler bu yüzden **t_yon_guv (TS yöneticisi)** ile açıldı. KİPA AVM'nin 8 ek şubesi tesis olarak t_ops_guv
  ile açıldı (`lokasyon.yaz` izni var).

### 1.2 B bölümü (satılan cihaz kalemleri, 27 satır)
- Hesap: t_sdestek_guv. Bu rol **hiçbir adımı yapamadı**: müşteri, tesis, ekipman ve iş açma isteklerinin hepsi 403 aldı.
  Adımlar şöyle tamamlandı:
  - **145 ekipman** (ekipman id 14–158; 53 X-Ray, 88 kapı dedektörü, 4 el dedektörü) t_yon_guv ile açıldı. Hepsi
    `KURULUM_BEKLIYOR` durumunda ve seri numarasız. Roller, sehpa ve kılıf ekipman türüne uymadığı için X-Ray kaydının
    notuna "aksesuar" olarak yazıldı.
  - DURUMU "tamamlandı" veya "planlandı" olan 15 satır için iş açıldı: **SRV-202611-000097 … 000111** (14 KURULUM,
    1 TASIMA). İşler t_ops_guv ile açıldı. Kargo satırı TASIMA türüne çevrildi. Yurt dışı satırda (Nijerya) iş açılmadı,
    yalnız ekipman açıldı.
  - İşlerin hedef durumları: 9 TAMAMLANDI (ekipman hedefi KURULU), 6 PLANLANDI. Durumu boş satırlar için yalnız ekipman açıldı.

### 1.3 Haberleşme (TELEKOM) ve Set Bariyer
- t_ops_hab, etkin şirket TELEKOM, birim HABERLESME ile iş planı Excel'inin 2026 satırlarından 14 temsilî iş seçildi.
  **15 iş** açıldı (İGDAŞ satırındaki 2 araç telsizi 2 ayrı iş oldu): **SRV-202611-000112 … 000126**.
  - Türler: 6 ARIZA (laboratuvar röle onarımı dahil), 2 KEŞİF, 3 BAKIM, 3 KURULUM, 1 DEMONTAJ.
  - 13 müşteri hızlı açma isteği 403 aldı ve t_yon_hab ile açıldı.
- t_sef_bar, etkin şirket ELEKTRONIK, birim BARIYER ile **3 iş** açıldı: **SRV-202611-000127** (KURULUM),
  **000128** (TOPLAMA), **000129** (TASIMA). İki müşteri t_yon_guv ile açıldı.

### 1.4 Arayüzden açılan işler (Playwright, t_ops_guv)
| İş | Yol | Not |
|---|---|---|
| SRV-202611-000130 | "+ Hızlı oluştur" → Yeni servis işi (Arıza) | İki "Aynı lokasyonda açık iş" bildirimi çıktı |
| SRV-202611-000131 | "+ Hızlı oluştur" → Yeni bakım işi (seri UI-5030A-0001) | Birim ve tür kendiliğinden geldi, ancak ilk ~1,5 sn'de alanlar boştu (B11) |
| SRV-202611-000132 | Menü Güvenlik → Teknik Servis → Kurulum → Yeni Kayıt | Form Birim=Güvenlik, Tür=Kurulum ile doğru doldu |

000132'yi test betiğim yanlışlıkla "Bakım" türünde açtı. Tür düzeltme ucuyla KURULUM'a çevrildi: PATCH 200 döndü ve
kategori PROJE olarak yeniden hesaplandı. Bir işin elle doldurulması yaklaşık 15–20 sn sürüyor (8 zorunlu alan).
Ekran görüntüleri: `C:\Users\skilic\AppData\Local\Temp\claude\ff375d97b5e42a31\c9ec6dae-0467-416d-a7b6-190f1738d382\scratchpad\rol_testi\ops_ice_aktarim\`.

### 1.5 Şirket ve kapsam kontrolleri
- t_ops_hab'ın ELEKTRONIK seçme isteği 403 SIRKET_DISI aldı. `/oturum/sirketler` yalnız TELEKOM döndürüyor. Doğru.
- t_ops_guv'un TELEKOM seçme isteği de 403 aldı. Doğru.
- İşe id ile doğrudan erişim:
  - t_ops_hab → GUVENLIK işi 23: 404
  - t_ops_guv → HABERLESME işi 112: 404
  - t_ops_guv → BARIYER işi 127: 404

  Hepsi doğru.

## 2. Bulgular

| No | Önem | Tür | Ekran / uç | Yeniden üretme | Beklenen | Gerçekleşen | Önerilen düzeltme |
|---|---|---|---|---|---|---|---|
| B1 | YÜKSEK | yetki/akış | `POST /teknik-servis/ana-veri/hizli-musteri`; Yeni servis işi formu | t_ops_guv, t_ops_hab veya t_sef_bar, listede olmayan müşteri için iş açmayı dener | Operasyon talebi kayda alabilmeli: ya müşteri kartı talebi bırakır ya da talep `customer_name_raw` ile açılır | 403. Formda yalnız "Müşteri İlişkileri'nden kart açmasını isteyin" yazıyor. Uygulamada kart talebi mekanizması yok (yalnız `teknik_servis_ana_veri.py:13` yorumunda geçiyor). Listedeki 41 müşterinin 30'u yeni olduğu için operasyon tamamen tıkandı. Bu aşamada 68 müşteri kartı yöneticiyle açıldı (Güvenlik A 30 + B 23, TELEKOM 13, Bariyer 2) | Müşteri kartı talebi kaydı (Görev ya da ayrı tablo, `customer_name_raw` ile iş açma) ya da operasyona "doğrulanmamış hızlı kart" izni (G10.2 yeniden değerlendirilmeli) |
| B2 | YÜKSEK | yetki | `hizli-musteri` (`teknik_servis_ana_veri.py:144-152`), `POST /hesaplar` | t_sdestek_guv hızlı müşteri açmayı dener | `hesap.kart_yaz` sahibi satış destek müşteri kartı açabilmeli (G10.2) | `hizli-musteri` ayrıca `servis.yaz` istiyor, `/hesaplar` ise `hesap.yaz` istiyor. Satış destekte `hesap.kart_yaz` izni hiçbir uçta işe yaramıyor (53 deneme 403) | Kart açma için `servis.yaz` gerektirmeyen bir uç (`hesap.kart_yaz` yeterli olsun) ya da `HizliEkleyici` → `require_any_permission("servis.yaz","hesap.kart_yaz")` |
| B3 | YÜKSEK | yetki | `POST /teknik-servis/ekipman`, `POST /lokasyonlar`, `POST /isler` | t_sdestek_guv B bölümünü (satılan cihazlar) işler | §5.8/3: satış destek satılan cihazların kurulum takibini yapar (ekipman KURULUM_BEKLIYOR + KURULUM işi) | `ekipman.yaz`, `lokasyon.yaz` ve `servis.yaz` izinleri yok. 145 ekipman yöneticiyle, 15 iş operasyonla açıldı | `permissions.py:733` SATIS_DESTEK'e en azından satış kaynaklı ekipman açma ve KURULUM işi talebi (ya da teklif → kurulum işi D2.2) verilmeli |
| B4 | YÜKSEK | yetki/akış | Atölye kabulü | §5.6/5: operasyon kargoyla gelen arızalı KMD kafasını atölye kabulüyle kaydeder (liste satır 3, 16 ve 22; Haberleşme laboratuvar onarımı) | Operasyon atölye kabul kaydı açabilmeli | SERVIS_OPERASYON'da `atolye.yaz` yok (`permissions.py:596`). ATOLYE türü ekrandan açılamıyor. Bu işler ARIZA olarak açıldı ve atölye takibi kayboldu | Operasyona `atolye.yaz` (yalnız kabul) ya da ayrı `atolye.kabul` izni |
| B5 | ORTA | veri | `POST /isler` `reported_at` (`is_emirleri.py:233,346`) | Talep tarihi 15.10.2026 olan satır `reported_at` ile açılır | Geçiş ve içe aktarmada asıl talep tarihi korunmalı (§7.5 `sla_kaynak=GECIS`) | 400 "Bildirim zamanı en çok 7 gün geriye girilebilir". Talep tarihi yalnız açıklamaya yazılabildi. Bildirim tarihi, SLA ve talep yaşı (11–35 gün) bugünden başlıyor | ImportBatch / göç ucu (`servis.ice_aktar`) ya da yöneticiye gerekçeli geriye tarih izni |
| B6 | ORTA | veri | Veri kalitesi "seri_eksik" | 59 Bakım/Arıza işi seri numarasız açılır, sonra `/ana-veri/veri-kalitesi` (yönetici) açılır | "Seri bekleniyor" işleri listelenmeli (§7.5) | servis `seri_eksik` = 0 (yalnız ekipman tarafında 145 sayılıyor). Seri bekleyen tek-cihaz işleri görünmüyor | Kontrol GUNLUK_SERVIS (azami_seri=1) türlerinde seri yok + ekipman yok işleri de saymalı |
| B7 | ORTA | veri | `POST /lokasyonlar` (`models/account.py:307`, `api/lokasyonlar.py:322`) | t_ops_guv mevcut müşteriye tesis ekler (KİPA AVM 8 şube) | Operasyonun açtığı tesis "doğrulanmamış" doğmalı (hızlı müşteri tesisi gibi) | `is_verified` varsayılan true. Operasyonun açtığı tesis doğrulanmış görünüyor; hızlı müşteriyle açılan ilk tesis doğrulanmamış | Oluşturmada `is_verified=False`; doğrulamayı `hesap.birlestir` yapsın |
| B8 | ORTA | veri/UX | Hızlı müşteri benzerlik kontrolü | "HALKBANK GENEL" açılır, sonra "HALKBANKASI İFM" açılır | Benzer kayıt uyarısı | İlk çiftte uyarı çıkmadı. "HALKBANKASI" açılırken 409 çıktı, ama betik onayladı. Sonuçta 3 ayrı Halkbank kartı var; veri kalitesi `mukerrer_unvan` = 0 | Benzerlikte ek sözcükleri ("GENEL", "İFM", "A.Ş.", "BANKASI/BANK") normalize et; mükerrer ünvan kontrolü bunu yakalasın |
| B9 | ORTA | UX/akış | İş açılışı "Aynı lokasyonda açık iş" uyarısı | Aynı tesiste 6 cihaz için 6 bakım işi açılır | 1 cihaz = 1 iş kuralıyla çok cihazlı bakım kolayca açılabilmeli | Her yeni iş öncekilerin hepsi için ayrı uyarı veriyor (6. işte 5 uyarı; toplam 73). Ekrandan aynı tesisteki 6 cihaz için 6 kez form doldurmak gerekiyor | Yeni iş formunda "adet / cihaz listesi" ile tek seferde N iş (ziyaretle gruplu). Toplu açılış ucu `isler/ekipmandan` yalnız ekipman kütüğünden çalışıyor, ekipmanı olmayan müşteride işe yaramıyor |
| B10 | ORTA | veri | KURULUM işi ↔ ekipman | Satılan 6 X-Ray için KURULUM işi açılır | Kurulum işi kurulacak ekipmanlara bağlanmalı; ürün kalemi bazında "kuruldu / bekliyor" izlenmeli (Y7) | `IsAcIn` ekipman alanı içermiyor. İş yalnız açıklamada ekipman id listesi taşıyabiliyor. Roller ve sehpa için ekipman türü yok (EKIPMAN_TIPLERI). "6 sattık, 2 kuruldu, 4 bekliyor" ERP'de izlenemiyor | KURULUM işine `ekipman_idler` (çok cihaz) + kalem bazlı kuruldu işareti; aksesuar türü |
| B11 | DÜŞÜK | UX | Yeni servis işi çekmecesi | "+ Hızlı oluştur" → "Yeni bakım işi" (sayfa yüklenirken) | Form hazır gelmeli | İlk ~1,5 sn Birim ve İş türü boş, talep kanalı ham kod "TELEFON" görünüyor; sözlük yüklenince düzeliyor. Hızlı kullanıcı boş birimle ilerleyebilir | `form-verileri` yüklenene kadar formu "yükleniyor" göster (`ServisIsFormu.tsx`) |
| B12 | DÜŞÜK | UX/link | Sol menü, `/servis-isleri?birim=BARIYER` | t_ops_guv (yalnız GUVENLIK) sol menüye bakar | Kullanıcının birimi olmayan birim grubu menüde olmamalı | "Set Bariyer" grubu görünüyor. Liste "Kayıt Sayısı: 0" ve "eşleşen iş yok" diyor ama BARIYER'de 3 iş var. "Yeni servis işi aç" düğmesi de etkin. Ayrıca sayfa yüklenirken menü kısa süre Haberleşme/POC/Mobilite gruplarını da gösteriyor | `fiori/menu.ts`: birim grubunu `kapsam.gorunur_birimler` ile süz; `/oturum/sirketler` yüklenene kadar menüyü gösterme |
| B13 | DÜŞÜK | UX | Servis işleri listesi (1440 px) | Arayüzden müşteri adı yazmadan iş açılır (000130) | Listede müşteri görünmeli | Sütunlar Durum, İş No, Bildirim tarihi/saati, Açıklama. Müşteri sütunu yok; 000130 listede yalnız "KMD SÜREKLİ ALARM VERİYOR" olarak görünüyor | Müşteri/tesis sütunu varsayılan görünür |
| B14 | DÜŞÜK | veri | İl doğrulama (`ana_veri.il_dogrula`) | Kıbrıs (Girne Limanı) ya da Nijerya müşterisi açılır | Yurt dışı müşteri ve tesis tutulabilmeli | "Bilinmeyen il" 400 döner. İstanbul yer tutucusu kullanıldı ve açıklamaya not yazıldı | İl alanına "Yurt dışı" + ülke |
| B15 | DÜŞÜK | veri | Liste sütunlarının ERP karşılığı | ARAÇ = "HAVA YOLU" | Ulaşım türü (havayolu/toplu taşıma) plan notu | Ulaşım türü alanı yok; araç alanı yalnız plaka için. JSON'da `ulasim` olarak tutuldu (2 satır) | Plan formunda "ulaşım türü" seçimi |
| B16 | DÜŞÜK | akış | Test kullanıcıları / Set Bariyer | Set Bariyer'de müşteri açmak gerekir | Birimin bir operasyon veya yönetici rolü olmalı | Set Bariyer'de yalnız şef var (`t_sef_bar`); müşteri açma Güvenlik yöneticisine düştü | Bilgi: Set Bariyer için operasyon ve yönetici rolü tanımı (KARARLAR §2) |
| B17 | DÜŞÜK | UX | `/teknik-servis/isler/form-verileri` | Sözlük çağrılır | Ekrandan seçilemeyen kanal sözlükte olmamalı | BAKIM_OTOMATIK dönüyor (arayüz kendisi süzüyor; API 400 veriyor). Ayrıca `/isler?limit=500` 422 dönüyor, sınır 200 | Sözlükte `ekrandan` bayrağı ya da süzülmüş liste |

## 3. İyi çalışanlar
- Şirket seçici doğru: t_ops_hab ELEKTRONIK'i, t_ops_guv TELEKOM'u seçemiyor (403 SIRKET_DISI). İşe id ile çapraz erişim
  her üç birimde 404 dönüyor.
- 1 cihaz = 1 iş kuralı sunucuda zorunlu: tek işte ikinci seri reddediliyor ve mesaj yol gösteriyor.
- Zorunlu alan mesajları tek seferde ve Türkçe geliyor ("Zorunlu alan eksik: lokasyon, talep eden kişinin adı, …").
- Menüden açılan yeni iş, listenin birim ve tür süzgecini doğru taşıyor (Kurulum listesi → Tür=Kurulum).
- Tür düzeltmesi (Bakım → Kurulum) kategoriyi türden yeniden türetiyor (GUNLUK_SERVIS → PROJE).
- Müşteri araması Türkçe büyük/küçük harf ve İ/I farkını doğru eşliyor ("iski", "ISKI", "İSKİ" aynı sonucu veriyor).
  Tesis adıyla da buluyor (Dalgakıran → SECURİTAS).
- Müşteri kartları şirketler arasında ortak: Güvenlik yöneticisinin açtığı müşteri Haberleşme aramasında da görünüyor.
- Ekipman veri kalitesi seri numarasız 145 kaydı doğru sayıyor.
