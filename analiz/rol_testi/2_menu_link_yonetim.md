# Rol testi 2 — Menü/link denetimi, Üst Yönetim (YONETIM) ve Admin (2026-11-04)

Ajan: "Üst Yönetim + Admin + menü/link denetçisi". Ortam: yerel (web 127.0.0.1:5173, API 127.0.0.1:8000).
Kod değiştirilmedi. Betikler ve ekran görüntüleri:
`C:\Users\skilic\AppData\Local\Temp\claude\C--Users-skilic-Documents-DengeERP-Gelistirme\c9ec6dae-0467-416d-a7b6-190f1738d382\scratchpad\rol_testi\menu_yonetim\`
(`tara.py` menü taraması, `tarama_hepsi.json` ham sonuç, `ust.py`/`ust2.py` üst çubuk + Ana Panel,
`anapanel.py`/`ap_suzgec.py` sayı = liste, `saha_ver.py` saha rolü, `uyelik*.py` şirket üyeliği).

## 1. Ne yaptım

1. **Menü taraması (Playwright, 20 kullanıcı, 24 kullanıcı×şirket bileşimi).** Her kullanıcıyla arayüzden giriş;
   seçebildiği her şirket için (t_yonetim ve t_finans_yon: TELEKOM/ELEKTRONIK/MOBILITE; diğerleri tek şirket)
   sol menüdeki bütün bölümler açıldı, her yaprak tek tek ziyaret edildi (toplam ≈ 690 yaprak ziyareti), sonra
   `main.tsx`'teki 44 rotadan menüde OLMAYANLAR URL ile açıldı (≈ 560 ziyaret). Her ziyarette: URL, 4xx/5xx ağ
   istekleri, JS hataları (`pageerror` + konsol), içerik uzunluğu (boş sayfa), "yetkiniz yok" metni, `document.title`,
   ekmek kırıntısı, vurgulu menü öğesi, görünür yazma düğmeleri. Sonuç Ek-A matrisinde.
2. **Üst çubuk** (t_yonetim masaüstü + 375 px; 20 kullanıcıda Hızlı oluştur/şirket etiketi): şirket seçici,
   Ctrl+K, Hızlı oluştur, uyarı zili, favori/son açılanlar, menü daraltma ve hatırlama, mobil çekmece.
3. **Ana Panel**: t_yonetim (TELEKOM/ELEKTRONIK/MOBILITE arasında arayüzden geçiş), t_yon_guv, t_yon_hab.
   Her KPI kartı ve birim özeti sayısı hem API düzeyinde (`liste_yolu` → `/api/teknik-servis/isler` `X-Toplam-Kayit`)
   hem arayüzde (karta tıkla → listedeki "Kayıt Sayısı") karşılaştırıldı; süzgeçler (bölüm, durum grubu, şef,
   personel, lokasyon, dönem) tek tek uygulandı (≈ 45 süzgeç bileşimi × ~40 sayı).
4. **Üst yönetimin günlük ihtiyacı** (§5.12/§5.1) tıklama sayısıyla değerlendirildi (bölüm 4).
5. **Admin**: Kullanıcılar ekranı (yeni kullanıcı/düzenle pencereleri, rol listesi), şirket üyeliği değiştirip geri
   alma (API ile — arayüzde alan yok, bkz. B-03), personel kartından saha rolü verme (ARAYÜZDEN, aşağıda).

### Saha rolü verildi (sonraki ajanlar için ÖNEMLİ)
Başlangıçta 20 test kullanıcısının hiçbirinde personel kartı `saha_rolu` dolu değildi; `GET /api/personel/atanabilir`
yalnız "Deneme …" kullanıcılarını döndürüyordu → t_tek_*/t_sef_* plana/tayine **atanamıyordu**.
Admin olarak **İnsan Kaynakları › Personel** ekranında (etkin şirket ilgili şirket) satır seçildi → alt çubuk
"Kartı Aç / Düzenle" → "Saha rolü" alanı → **Kaydet** ("Personel kartı kaydedildi" iletisi). Yapılanlar:

| Kullanıcı | Şirket / birim | Verilen saha rolü | Doğrulama (`GET /api/personel/{id}`) |
|---|---|---|---|
| t_tek_guv1 (id 24) | ELEKTRONİK / GUVENLIK | Teknisyen | TEKNISYEN |
| t_tek_guv2 (id 25) | ELEKTRONİK / GUVENLIK | Teknisyen | TEKNISYEN |
| t_sef_guv (id 21) | ELEKTRONİK / GUVENLIK | Şef | SEF |
| t_sef_bar (id 23) | ELEKTRONİK / BARIYER | Şef | SEF |
| t_saha_guv (id 34) | ELEKTRONİK / GUVENLIK | Teknisyen (gerekçe: §5.5 saha sorumlusu sahada çalışır ama tayin yetkisi yoktur; "Şef" verilseydi şef listelerine düşerdi) | TEKNISYEN |
| t_tek_hab (id 26) | TELEKOM / HABERLESME | Teknisyen | TEKNISYEN |
| t_sef_hab (id 22) | TELEKOM / HABERLESME | Şef | SEF |

Sonrasında `atanabilir?birim=GUVENLIK` → 4 test kullanıcısı (+3 deneme), `BARIYER` → t_sef_bar, `HABERLESME` →
t_tek_hab + t_sef_hab dönüyor. Birim üyelikleri değiştirilmedi.

### Şirket üyeliği değiştirme ve GERİ ALMA
t_sdestek_hab (id 36): `PATCH /api/kullanicilar/36 {"sirketler":["TELEKOM","ELEKTRONIK"],version}` → 200; kullanıcı
oturumunda `GET /api/oturum/sirketler` iki şirketi gösterdi, ELEKTRONİK seçilebildi (servis işi sayısı 0 — birimi
HABERLESME olduğu için fail-closed, doğru). Ardından `{"sirketler":["TELEKOM"]}` ile **geri alındı** (son durum
`['TELEKOM']`). İkinci denemede kullanıcı ELEKTRONİK'te açıkken üyelik kaldırıldı: açık oturumun etkin şirketi
kendiliğinden TELEKOM'a döndü (doğru). Üye olunmayan şirkete geçiş (`PUT aktif-sirket MOBILITE`) → 403 (doğru).

Açılan/işlenen kayıt: yeni servis/bakım kaydı AÇILMADI. Değişen kayıtlar yalnız yukarıdaki 7 personel kartı
(saha_rolu) ve t_sdestek_hab şirket üyeliği (değiştirildi + geri alındı, iki kez). Favori yıldızı t_yonetim'de
konuldu ve geri alındı; menü daraltma t_yonetim tarayıcı bağlamında kaldı (yerel depo, sunucuya etkisi yok).

## 2. Bulgular

| No | Önem | Tür | Ekran / uç | Yeniden üretme | Beklenen | Gerçekleşen | Önerilen düzeltme |
|---|---|---|---|---|---|---|---|
| B-01 | YÜKSEK | link/yetki | Sol menü "Ana Panel" + açılış sayfası | t_satis_guv, t_finans_uzm veya t_mob_depo ile giriş | `servis.gor` olmayan rolün açılış sayfası çalışan bir ekran olmalı; Ana Panel menüde görünmemeli ya da rol için anlamlı içerik göstermeli | Herkesin açılışı Ana Panel; `GET /api/teknik-servis/ana-panel` 403 → "Ana panel yüklenemedi — Bu işlem için yetkiniz yok (servis.gor)". Menüde Ana Panel yaprağı `uygulama: null` (herkese açık) | `fiori/menu.ts:116-123` Ana Panel yaprağına izin bağla (ör. `servis.gor`), açılışta `acilisYolu()` (`uygulamalar.ts:200`) ile yetkili ilk sayfaya git; ya da Ana Panel'in servis dışı (satış/finans/depo) özet sürümü |
| B-02 | YÜKSEK | link/akış | Satış, Satış Destek, Finans Uzmanı menüsü | t_satis_guv (ELEKTRONİK) menüsünü aç | Satış: Hesaplar/Teklifler/Siparişler; Satış Destek: teklif + servis kayıtları; Finans: fatura devri/tahsilat menüden erişilebilir | t_satis_guv menüsünde 4 yaprak (Ana Panel=403, Görevler, Uygulamalar). Hesaplar, Teklifler, Ürünler yalnız **Mobilite › Mobilite Modülü** altında; ELEKTRONİK/TELEKOM'da bölüm gizli, ama URL ile açılıyor ve veri geliyor (`/hesaplar`, `/teklifler`, `/urunler` — matris "A"). t_finans_uzm 5 yaprak; Satış Destek'te Teklifler yok | Ortak (şirketten bağımsız) bir "Satış / Müşteri" bölümü: Hesaplar (müşteri kartları KARAR §1 gereği ortak), Teklifler, Ürün Kataloğu; `menu.ts` `mobiliteSayfalari` içinden ortak olanları ayır |
| B-03 | YÜKSEK | UX/akış | Sistem › Kullanıcılar (UsersPage) | Admin → Kullanıcılar → "Yeni kullanıcı" ve satırda "Düzenle" | KARAR §1 ve §5.1: admin kullanıcıyı şirkete üye yapar | İki pencerede de **şirket üyeliği alanı yok** (yeni: Ad, kullanıcı adı, e-posta, geçici parola, rol [+birim]; düzenle: Ad, e-posta, rol, oturum açabilir, parola, 2FA). API `PATCH /api/kullanicilar/{id}` `sirketler` alanını kabul ediyor ve çalışıyor (`schemas/auth.py:154`, `api/users.py:909`). Düzenle penceresinde birim de yok (yalnız personel kartında) | `frontend/src/pages/UsersPage.tsx` yeni/düzenle formlarına "Şirketler" çoklu seçimi (`GET /api/oturum/sirketler` kataloğundan) ve birim/birincil birim |
| B-04 | ORTA | UX/akış | Personel kartı ↔ Planlama tayini | Yeni rol kullanıcısı açıp plana atamayı dene | Admin rol verince kişi atanabilir olmalı ya da eksik açıkça söylenmeli | Rol + birim olan kullanıcı `saha_rolu` boşsa `atanabilir` listesine girmiyor; 20 test kullanıcısının hepsi böyleydi. İpucu yalnız Personel ekranındaki "Saha rolü girilmemiş: 29" kutucuğunda; Kullanıcılar ekranında hiç anılmıyor; saha rolü ve birim iki ayrı ekranda (Kullanıcılar ≠ İK › Personel) | Kullanıcı oluştururken servis rollerinde saha rolü varsayılanı (TEKNISYEN→Teknisyen, SEF→Şef) ya da Kullanıcılar ekranında "Personel kartını aç" bağlantısı; planlama tayin listesinde "saha rolü girilmemiş N kişi" uyarısı |
| B-05 | ORTA | UX (görsel fail-open) | Sol menü + kırıntı, bütün kullanıcılar | `oturum/sirketler` yanıtı gecikince (yaris.py: 3 sn gecikme) sayfayı aç | Şirket bilgisi gelene kadar birim bölümleri gizli kalmalı | İlk anda **bütün şirketlerin bölümleri** görünüyor (t_yon_guv: Güvenlik, Haberleşme, POC, Mobilite, Set Bariyer…), kırıntıda şirket yok; 3–4 sn sonra düzeliyor. Tarama sırasında t_yonetim@ELEKTRONİK menüsü bu yüzden 64 yaprak (Mobilite modülü dahil) okundu ve o yapraklar 403 verdi. Sunucu reddediyor (veri sızmıyor) ama kullanıcı başka şirketin menüsüne tıklayabiliyor; aynı nedenle t_tek_guv2'de bir ölçümde şirket etiketi hiç çizilmemişti | `fiori/menu.ts:290` `s.aktifBirimler` null iken birimli bölümleri GİZLE (fail-closed); `auth/SirketContext.tsx:134` yükleniyor durumunu ayrı ver |
| B-06 | ORTA | link/UX | Menüde olmayan sayfalar (URL ile) | t_tek_hab ile `/kullanicilar`, `/hakedis`, `/raporlar` … aç | "Bu sayfaya yetkiniz yok" sayfası ya da yetkili sayfaya yönlendirme | Rota düzeyinde koruma yok (yalnız `/panel` için `PanelKapisi`): sayfanın iskeleti (başlıklar, sekmeler, "Veri Yok" tablosu, bazen "Yeni kullanıcı" gibi düğmeler) çiziliyor, arkada 1–6 adet 403; kırıntı "Şirket › Denge ERP". Yalnız `/servis-raporlari` ve `/servis-ana-veri` kendi "yetkiniz yok" iletisini veriyor | `main.tsx:117-178` rotaları katalogdaki `izin` ile saran ortak bir `IzinKapisi` (yoksa "yetkiniz yok" sonucu) |
| B-07 | ORTA | yetki | Raporlar › Servis Maliyet (t_finans_uzm) | t_finans_uzm → Raporlar › Servis Maliyet | Sayfa hatasız açılmalı | `GET /api/teknik-servis/isler/form-verileri` 403 (Finans Uzmanı'nda `servis.gor` yok); sayfa açılıyor ama süzgeç sözlükleri boş | ServisMaliyetPage sözlük için `servis.gor` gerektirmeyen uç kullansın ya da `maliyet.gor` sahibine form-verileri açılsın |
| B-08 | ORTA | veri/UX | Ana Panel | t_yonetim, ELEKTRONİK, süzgeçsiz; ya da `lokasyon_id=1` | Aynı ekranda "açık" tek anlamda | KPI "Açık İş Emirleri" = 98 (PB hariç, tanımda yazıyor) ama "Duruma göre dağılım" açık toplamı = 116 ve "Aktif İşler" tablosu PB işlerini de listeliyor. lokasyon_id=1 süzgecinde KPI 1, tabloda 10 satır (9'u PB PLANLAMADA) → yönetici çelişki görüyor. Her sayı kendi listesiyle tutarlı (sayı = liste bozulmuyor) | Kart adını "Açık İş Emirleri (PB hariç)" yap ya da dağılım/aktif işler aynı tanımı kullansın (`services/teknik_servis/ana_panel.py`) |
| B-09 | ORTA | eksik gösterge | Ana Panel (YONETIM) | t_yonetim ile Ana Panel | GMY "yönetim özeti": grup geneli tek bakış | Grup toplamı yok: üç şirketi görmek için şirket seçiciden 3 kez geçiş gerekiyor (her geçiş = 2 tık + yeniden yükleme). SLA **uyum oranı** (yalnız "SLA riski olan iş" sayısı var), şehir dışı oranı, araç-km, kârlılık özeti panelde yok (bkz. bölüm 4) | Yalnız birden çok şirkete üye (YONETIM/FINANS_YONETICI) için "Tüm şirketler" seçeneği ya da Ana Panel'de şirket kırılımı kartı |
| B-10 | DÜŞÜK | link | Menü: POC › Tüm işler | t_tek_hab/t_yonetim (TELEKOM) → POC › Tüm işler | Kırıntı "POC › Tüm işler", vurgu tıklanan yaprakta | Aynı URL (`/servis-isleri?birim=POC`) Haberleşme › POC › POC işleri ile ortak: kırıntı ve sekme başlığı "Haberleşme › POC › POC işleri", vurgu Haberleşme bölümünde (7 kullanıcı×şirket). Son açılanlarda iki ayrı "Tüm işler" bağlamsız görünüyor | İki yapraktan birini kaldır ya da ayrıştırıcı parametre ekle (`menu.ts:174-189`); son açılanlarda üst bölüm adını göster |
| B-11 | DÜŞÜK | UX | Ana Panel KPI → liste kırıntısı | Herhangi bir KPI kartına tıkla (ör. Açık İş Emirleri) | Kırıntı/sekme başlığı "Açık İş Emirleri" | Kırıntı "Takip ve Onaylar › Tüm Servis İşleri" (kpi=acik, kritik_acik, sla_riskli, bakim_bu_ay_planli, onay_bekleyen menüde yaprak değil). Liste üstünde "Panel: … (sayı = liste)" çipi var, o doğru | `aktifYaprak` eşleşmeyen `kpi` için kırıntıya KPI adını ekle |
| B-12 | DÜŞÜK | UX | Ana Panel KPI "POC Açık Talep" | t_yonetim ELEKTRONİK veya MOBİLİTE | POC birimi yalnız TELEKOM'da; diğer şirkette kart gösterilmemeli | Kart her şirkette 0 ile görünüyor, tıklayınca boş liste | Kartı etkin şirkette POC birimi varsa göster |
| B-13 | DÜŞÜK | sızıntı (hafif) | İK › Personel, Kiralamalar kategori şeridi | t_yonetim veya admin, ELEKTRONİK etkin | Şerit ve liste yalnız etkin şirketin birimlerini/kişilerini göstermeli | Şerit bütün birimleri (HABERLEŞME, POC, MOBİLİTE, ARAÇ TAKİP) gösteriyor (tıklayınca boş). Personel listesinde birimsiz kişiler şirket üyeliğine bakılmadan her şirkette (ör. yalnız MOBİLİTE üyesi t_mob_depo ve yalnız ELEKTRONİK üyesi t_finans_uzm TELEKOM personel listesinde) | Şeridi `aktifBirimler` ile süz; birimsiz personeli `kullanici_sirketleri` ile süz |
| B-14 | DÜŞÜK | UX | Ana Panel dönem süzgeci | Dönem = son 7 gün | Açık KPI değişmeli ya da süzgecin neyi etkilediği belli olmalı | Açık iş, askıda, SLA sayıları değişmiyor (tasarım: dönem yalnız "tamamlanan/dönemde iş emri" ve karşılaştırmayı etkiler); ekranda bunu söyleyen ipucu yok | Dönem seçicinin yanına "Açık sayılar anlık; dönem tamamlanan ve karşılaştırmayı etkiler" ipucu |
| B-15 | DÜŞÜK | UX | Mobil (375 px) şirket etiketi | t_yonetim 375 px | Türkçe ad | Üst çubukta kod "MOBILITE" (İ'siz) gösteriliyor (`Kabuk.tsx:136` mobilde `aktif.kod`) | Kısa ad alanı ya da `ad` kısaltması |
| B-16 | DÜŞÜK | yetki (okuma) | `/servis-tanimlar`, `/ice-aktarma` | Teknisyen/şef/ops ile `/servis-tanimlar`; YONETIM/finans ile `/ice-aktarma` | Menüde olmayan tanım/içe aktarma ekranı açılmamalı | Servis tanımları (arıza/bekleme nedenleri, SLA politikaları) `servis.gor` ile okunuyor; içe aktarma parti listesi YONETIM ve finansa açık. Yazma düğmesi gizli, sunucu yazmayı reddediyor; yalnız menü/rota tutarsızlığı | Bilinçli ise menüye salt okunur yaprak; değilse B-06 kapısı |
| B-17 | DÜŞÜK | performans | Servis işleri listeleri | 5 paralel tarayıcıyla tarama | < 3 sn | "Tüm Servis İşleri", "Kalite Onayı Bekleyen", "Personel", "Eğitim" yer yer 8–12 sn (networkidle'a kadar). Eşzamanlı ajan yükü altında ölçüldü; kesin değil | Yük altında yeniden ölçün |

Hata olmayan ama not: JS `pageerror` hiç yakalanmadı; konsoldaki tek hata türü 403 kaynak yükleme iletileri
(46 kez, hepsi B-01/B-05/B-07 kaynaklı) ve antd kullanım uyarıları (`Drawer width`, `List` deprecated).

## 3. İyi çalışanlar

- **Sayı = liste**: 5 kullanıcı×şirket × ~40 sayı × 45 süzgeç bileşiminde API düzeyinde hiç fark yok; arayüzde
  KPI'ya ve birim kartı sayılarına tıklayınca listedeki "Kayıt Sayısı" aynı (ör. ELEKTRONİK Açık 99=99, Kritik 1=1,
  Güvenlik açık 95=95, Bariyer 3=3; TELEKOM açık 15=15). Hatırlanan liste süzgeci (öncelik=KRİTİK) panel bağlantısını
  bozmuyor (kpi parametresi hatırlamayı kapatıyor).
- **Şirket geçişi**: t_yonetim için seçici çalışıyor, sayılar şirkete göre değişiyor (TELEKOM 15 / ELEKTRONİK 98 /
  MOBİLİTE 0), menü bölümleri doğru süzülüyor (yüklendikten sonra), kırıntı şirket adıyla başlıyor, uyarı zili de
  şirkete göre değişiyor. Tek şirketli 17 kullanıcıda sabit etiket. Başka şirket birimi süzgeci → 403.
- **Menüdeki yapraklar**: servis rolleri (yönetici/şef/teknisyen/ops/atölye/saha/depo/satış destek/finans yön.) için
  menüdeki her yaprak 403'süz açılıyor, kırıntı = menü yolu, sekme başlığı = yaprak adı, vurgu doğru.
- **YONETIM salt okunur**: Ana Panel, servis işleri, bakım, kiralama, personel, ekipman, yedek parça ekranlarında
  yazma düğmesi yok ("Kartı Aç / Düzenle" pasif); Hızlı oluştur gizli. Hızlı oluştur seçenekleri 20 kullanıcıda
  izinlerle birebir (servis.yaz / bakim.yaz / kiralama.yaz).
- Ctrl+K arama kutusuna odaklıyor; menü yaprağı ("Kiral") ve kayıt numarası ("SRV") araması sonuç veriyor.
  Favori yıldızı ve "Son açılanlar" yeniden yüklemede korunuyor; menü daraltma ve açık bölümler hatırlanıyor;
  daraltılmış ikona tıklamak menüyü açıyor. 375 px'de yan menü yerine çekmece, yaprağa tıklayınca kapanıyor,
  yatay taşma yok (liste ve Ana Panel).
- Şirket üyeliği API'si sürüm kilidiyle çalışıyor; üyelik kaldırılınca açık oturum fail-closed şirket değiştiriyor.
- Rol listesinde yeni roller var: Saha Sorumlusu, Satış Destek, Finans Yöneticisi, "Finans Uzmanı" (MUHASEBE_DESTEK).

## 4. Üst yönetimin günlük ihtiyacı (IS_ANALIZI_OZETI §5.12) — kaç tık, ne eksik

| İhtiyaç | Nerede | Tık (girişten) | Durum |
|---|---|---|---|
| Birim bazında açık / sahada / atölyede / tamamlanan | Ana Panel birim kartları | 0 (açılış) | VAR |
| Bekleyen onaylar, askıdakiler, acil arıza, SLA riski | Ana Panel KPI | 0 | VAR (sayı) |
| SLA **uyum oranı** (%) | Raporlar › Servis Raporları › "SLA ve Bekleme" | 3 | Panelde YOK, raporda var |
| Bu ay planlı bakım tamamlanma oranı | Ana Panel "Planlı Bakım Tamamlanma" halkası | 0 | VAR |
| Önceki döneme göre değişim | KPI altı ("dönem başına göre") | 0 | VAR |
| Yıllık/aylık eğilim (iş tipine göre) | Raporlar › Servis Raporları › 12 Ay Trend | 3 | VAR (panelde yok) |
| Şehir dışı oranı | Servis Raporları › Kırılımlar › boyut "Şehir" | 4–5 | Oran YOK (yalnız şehir kırılımı) |
| Araç-km | — | — | YOK (Faz D GPS) |
| Kârlılık özeti, büyük müşteri bazında iş/fatura | Raporlar › Servis Maliyet; Raporlar › Fatura Devri; Kırılımlar › Müşteri | 2–4 | Ayrı ekranlarda; tek "yönetim özeti" yok |
| Üç şirketin toplamı | Şirket seçici ×3 | 6+ | YOK (B-09) |
| Dışa aktarma | Servis raporları Excel | 3 | VAR (`rapor.disaaktar` YONETIM'de; §5.12-4 "ayrı yetki" ile uyumlu) |

Öneri: Ana Panel'e YONETIM için "Yönetim özeti" şeridi (SLA uyum %, şirket kırılımı, ay sonu kârlılık
özeti `maliyet.gor` ile) — mevcut rapor uçlarından (`/api/servis-raporlari/sla`, `/trend`, `/api/servis-maliyet/analiz`).

## Ek-A. Rol × sayfa matrisi

Kolon: kullanıcı/şirket (t_ öneki atıldı). Hücre: **✓** menüde ve hatasız açıldı · **403** menüde ama API 403 ·
**Y** menüde ama "yetkiniz yok" · boş = menüde yok ve URL'de denenmedi (süzgeçli yaprak) · **·** menüde yok, URL ile
açınca 403/yetki iletisi (doğru) · **A** menüde YOK ama URL ile veriyle açılıyor · **→** başka sayfaya yönlendi.
t_yonetim kolonları kırıntıda şirket görünene kadar beklenerek yeniden tarandı (B-05 yarışını dışlamak için).

| Sayfa (menü yolu) / URL | sef_hab/TEL | yon_guv/ELE | yon_hab/TEL | sef_guv/ELE | tek_guv1/ELE | tek_guv2/ELE | tek_hab/TEL | sef_bar/ELE | ops_guv/ELE | saha_guv/ELE | ops_hab/TEL | atolye_guv/ELE | yonetim/TEL | yonetim/ELE | yonetim/MOB | satis_guv/ELE | finans_uzm/ELE | sdestek_guv/ELE | sdestek_hab/TEL | mob_depo/MOB | depo_guv/ELE | finans_yon/TEL | finans_yon/ELE | finans_yon/MOB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ana Panel `/ana-panel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Y | Y | ✓ | ✓ | Y | ✓ | ✓ | ✓ | ✓ |
| Benim İşlerim `/benim-islerim` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | ✓ | · | ✓ | · | · | · | · | · | · | · | · | · | · | · | · |
| Haberleşme › Teknik Servis › Tüm işler `/servis-isleri?birim=HABERLESME` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| Haberleşme › Laboratuvar › Arıza Onarım `/atolye?birim=HABERLESME` | ✓ |  | ✓ |  |  |  |  |  |  |  |  |  | ✓ |  |  |  |  |  | ✓ |  |  |  |  |  |
| Haberleşme › Laboratuvar › Yedek Parça Stok `/yedek-parca?sekme=stok` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  |  |  | ✓ |  |  |  |  |  |  |  |  |  |  |  |
| Haberleşme › Saha › Keşif `/servis-isleri?birim=HABERLESME&tur=KESIF` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| Haberleşme › Saha › Arıza `/servis-isleri?birim=HABERLESME&tur=ARIZA` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| Haberleşme › Saha › Bakım `/servis-isleri?birim=HABERLESME&tur=PLANSIZ_BAKIM` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| Haberleşme › Poc › POC işleri `/servis-isleri?birim=POC` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| Poc › Arıza `/servis-isleri?birim=POC&tur=ARIZA` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| Poc › Kurulum `/servis-isleri?birim=POC&tur=KURULUM` | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| Kiralama › Kiralamalar `/kiralamalar` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | ✓ | · | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | · | · | · | ✓ | ✓ | ✓ |
| Kiralama › Kiralık Envanter `/kiralik-envanter` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | ✓ | · | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | · | · | · | ✓ | ✓ | ✓ |
| Planlama › Planlama `/servis-planlama` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | · | ✓ | ✓ | ✓ | ✓ |
| Planlama › Operasyon Merkezi `/operasyon` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | ✓ | ✓ | ✓ | · | ✓ | ✓ | ✓ | · | · | · | · | · | · | · | · | · |
| Planlama › Zaman Takibi `/zaman-takibi` | ✓ | ✓ | ✓ | ✓ | → | → | → | ✓ | → | → | → | → | ✓ | ✓ | ✓ | → | → | → | → | → | ✓ | ✓ | ✓ | ✓ |
| Planlı Bakım › Bakım Bildirimleri `/bakim` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | · | · | · | · | ✓ | ✓ | ✓ | · | · | · | · | · | · | ✓ | ✓ | ✓ |
| Planlı Bakım › Sözleşmeler `/bakim?sekme=sozlesmeler` | ✓ | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ | ✓ | ✓ |  |  |  |  |  |  | ✓ | ✓ | ✓ |
| Planlı Bakım › Bakım Dönemleri `/bakim?sekme=donemler` | ✓ | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ | ✓ | ✓ |  |  |  |  |  |  | ✓ | ✓ | ✓ |
| Planlı Bakım › Açık Bakım İşleri `/servis-isleri?kpi=bakim_acik` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ | ✓ | ✓ |
| Planlı Bakım › Geciken Bakım `/servis-isleri?kpi=bakim_geciken` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ | ✓ | ✓ |
| Takip ve Onaylar › Tüm Servis İşleri `/servis-isleri` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | · | ✓ | ✓ | ✓ | ✓ |
| Takip ve Onaylar › Servis Paneli `/servis-paneli` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | · | ✓ | ✓ | ✓ | ✓ |
| Takip ve Onaylar › Tayin Edilmemiş İşler `/servis-isleri?kpi=atanmamis` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ | ✓ | ✓ |
| Takip ve Onaylar › Kapanış Onayı `/servis-isleri?kpi=kapanis_bekleyen` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ | ✓ | ✓ |
| Takip ve Onaylar › Kalite Onayı Bekleyen `/servis-isleri?kalite=BEKLEYEN` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ | ✓ | ✓ |
| Takip ve Onaylar › Askıdaki İşler `/servis-isleri?kpi=beklemede` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ | ✓ | ✓ |
| Takip ve Onaylar › Görevler `/gorevler` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Depo ve Yedek Parça › Yedek Parça `/yedek-parca` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | ✓ | ✓ | ✓ | · | · | · | · | · | ✓ | · | · | · |
| Depo ve Yedek Parça › Ekipman Kütüğü `/servis-ekipman` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | ✓ | · | ✓ | ✓ | ✓ | ✓ | · | · | ✓ | ✓ | · | · | · | · | · |
| Raporlar › Servis Raporları `/servis-raporlari` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | · | · | · | · | ✓ | ✓ | ✓ | · | · | · | · | · | ✓ | ✓ | ✓ | ✓ |
| Raporlar › Ana Veri Kalitesi `/servis-ana-veri` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | · | · | · | · | ✓ | ✓ | ✓ | · | · | · | · | · | ✓ | ✓ | ✓ | ✓ |
| İnsan Kaynakları › Personel `/personel` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | ✓ | · | ✓ | · | ✓ | ✓ | ✓ | · | · | · | · | · | · | · | · | · |
| İnsan Kaynakları › Eğitim ve Gelişim `/egitim` | ✓ | ✓ | ✓ | ✓ | · | · | · | ✓ | · | · | · | · | ✓ | ✓ | ✓ | · | · | · | · | · | · | · | · | · |
| İnsan Kaynakları › Gelişim Kartım `/gelisim-kartim` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · | · | · | · | · | · | · | · | · | · | · | · |
| Sistem Yönetimi › Uygulamalar (kutucuklar) `/uygulamalar` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Güvenlik › Teknik Servis › Tüm işler `/servis-isleri?birim=GUVENLIK` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Güvenlik › Teknik Servis › Kurulum `/servis-isleri?birim=GUVENLIK&tur=KURULUM` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Güvenlik › Teknik Servis › Arıza `/servis-isleri?birim=GUVENLIK&tur=ARIZA` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Güvenlik › Teknik Servis › Bakım `/servis-isleri?birim=GUVENLIK&tur=PLANSIZ_BAKIM` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Güvenlik › Atölye › Bakım `/atolye?birim=GUVENLIK` |  | ✓ |  | ✓ |  |  |  | ✓ |  |  |  | ✓ |  | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| Set Bariyer › Tüm işler `/servis-isleri?birim=BARIYER` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Set Bariyer › Kurulum `/servis-isleri?birim=BARIYER&tur=KURULUM` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Set Bariyer › Toplama `/servis-isleri?birim=BARIYER&tur=TOPLAMA` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Set Bariyer › Taşıma `/servis-isleri?birim=BARIYER&tur=TASIMA` |  | ✓ |  | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  | ✓ |  |  | ✓ |  | ✓ |  |
| Mobilite › Teknik Servis › Mobilite işleri `/servis-isleri?birim=MOBILITE` |  |  |  |  |  |  |  |  |  |  |  |  |  |  | ✓ |  |  |  |  |  |  |  |  | ✓ |
| Mobilite › Teknik Servis › Araç Takip işleri `/servis-isleri?birim=ARAC_TAKIP` |  |  |  |  |  |  |  |  |  |  |  |  |  |  | ✓ |  |  |  |  |  |  |  |  | ✓ |
| (menüde yok) `/panel` | → | → | → | → | → | → | → | → | → | → | → | → | · | · | ✓ | · | · | → | → | ✓ | → | · | · | ✓ |
| (menüde yok) `/raporlar` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | ✓ | · | · | · | ✓ |
| (menüde yok) `/kvkk` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| (menüde yok) `/stok` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | ✓ | · | · | · | ✓ |
| (menüde yok) `/teklifler` | **A** | **A** | **A** | **A** | · | · | · | **A** | · | · | · | · | **A** | **A** | ✓ | **A** | **A** | **A** | **A** | · | · | **A** | **A** | ✓ |
| (menüde yok) `/siparisler` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | · | · | · | · | ✓ |
| (menüde yok) `/abonelikler` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | · | · | · | · | ✓ |
| (menüde yok) `/tahsilat` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | · | · | · | · | ✓ |
| (menüde yok) `/ice-aktarma` | · | · | · | · | · | · | · | **A** | · | · | · | · | **A** | **A** | **A** | ✓ | **A** | · | · | ✓ | · | **A** | **A** | **A** |
| (menüde yok) `/rma` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | · | · | · | · | · |
| (menüde yok) `/satinalma` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | ✓ | · | · | · | ✓ |
| (menüde yok) `/is-emirleri` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | ✓ | · | · | · | ✓ |
| (menüde yok) `/hakedis` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | · | · | · | · | ✓ |
| (menüde yok) `/cihazlar` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | ✓ | · | · | · | ✓ |
| (menüde yok) `/hatlar` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | ✓ | · | · | · | · |
| (menüde yok) `/araclar` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | · | · | · | · | ✓ | · | · | · | · |
| (menüde yok) `/hesaplar` | **A** | **A** | **A** | **A** | · | · | · | **A** | **A** | **A** | **A** | · | **A** | **A** | ✓ | **A** | **A** | **A** | **A** | ✓ | **A** | **A** | **A** | ✓ |
| (menüde yok) `/urunler` | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | ✓ | **A** | **A** | **A** | **A** | ✓ | **A** | **A** | **A** | ✓ |
| (menüde yok) `/kullanicilar` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| (menüde yok) `/ayarlar` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| (menüde yok) `/denetim` | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| (menüde yok) `/servis-tanimlar` | **A** | ✓ | ✓ | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | **A** | · | · | **A** | **A** | · | **A** | **A** | **A** | **A** |
| (menüde yok) `/servis-maliyet` | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | ✓ | ✓ | · | 403 | · | · | · | · | ✓ | ✓ | ✓ |
| (menüde yok) `/fatura-devri` | · | · | · | · | · | · | · | · | · | · | · | · | ✓ | ✓ | ✓ | · | ✓ | · | · | · | · | ✓ | ✓ | ✓ |
| (menüde yok) `/atolye` |  |  |  |  | · | · | · |  | · | · | · |  |  |  | **A** | · | · |  |  | · | · | · | · | · |