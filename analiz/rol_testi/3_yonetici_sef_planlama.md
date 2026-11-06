# Rol testi 2. aşama: TS Yöneticisi + Takım Lideri/Şef, planlama (2026-11-04)

Ortam: yerel deneme (API 127.0.0.1:8000, web 127.0.0.1:5173). Kod değiştirilmedi. Kişi adı, plaka ve parola bu rapora
yazılmadı; kişiler test kullanıcı adlarıyla anılıyor.
Betikler ve ekran görüntüleri: `C:\Users\skilic\AppData\Local\Temp\claude\ff375d97b5e42a31\c9ec6dae-0467-416d-a7b6-190f1738d382\scratchpad\rol_testi\yonetici_plan\`
(`adim1_guv.py` … `adim6_sayilar.py`, `log_adim*.json`, `u*.png`).
3. aşama girdisi: `analiz/rol_testi/planlanan_isler.json` (110 iş). Her iş için şu alanlar var: şimdiki durum, plan
tarihi/saati/süresi, ziyaret, ekip (test kullanıcıları, sorumlu işareti), hedef ve 3. aşamada ne yapılacağı.

## 1. Ne yaptım

### 1.1 Ön kontrol: kişiler plana atanabiliyor mu?
Yönetici ve şef hesaplarıyla `GET /personel/atanabilir?birim=` denendi.
- GUVENLIK: t_sef_guv (SEF), t_tek_guv1, t_tek_guv2 ve t_saha_guv (TEKNISYEN) atanabiliyor.
- HABERLESME: t_sef_hab ve t_tek_hab atanabiliyor.
- BARIYER: yalnız t_sef_bar atanabiliyor.

Personel kartında saha rolü ya da birim eksiği yok, bu yüzden yönetici hesabıyla düzeltme gerekmedi.

### 1.2 t_yon_guv (ELEKTRONIK): Güvenlik planı
- **Arayüzden tekli plan:** SRV-202611-000096 (ESPARK). Planlama → havuzda ara → Planla → süre → teknisyen → Kaydet:
  **7 eylem**, "Plan kaydedildi".
- **Servis aracı:** GUVENLIK havuzunda 1 test aracı açıldı (`POST /planlama/araclar`, id 1).
- **KİPA turu (§7.6: 9 şube, 18 cihaz, iki ekip, 3 gün; 26–28 Ekim):**
  - Ekip A: t_tek_guv1 (sorumlu) + t_saha_guv, araçlı. Ekip B: t_tek_guv2.
  - Açılan ziyaretler: ZYR-202610-000001…000007, ayrıca 2 Kasım için ZYR-202611-000008 (000044) ve 3 Kasım için tekli plan (000037).
  - **Araç çakışması:** Ekip B aynı araçla aynı saate planlandı → 409 `PLAN_CAKISMA` (tür ARAÇ). Araçsız kaydedildi.
  - **Kişi çakışması:** Ekip A 28 Ekim 10:00'a ikinci şubeye planlandı → 409. Kısa gerekçe → 400 "en az 10 karakter".
    Geçerli gerekçeyle kaydedildi (ZYR-202610-000006).
  - **Farklı tesisler tek ziyarette:** 000044 ile 000037 birlikte gönderildi → 409 "Seçilen işler farklı lokasyonlarda" (bulgu B5).
- **Aynı tesisteki çok cihazlı işler toplu planla tek ziyarete alındı:** PİMSER (3), RÖNESANS (5), PALLADIUM (5), İSKİ (6),
  MALTEPE (3), DALGAKIRAN (2), DENGE GRUP (2), ŞANLIURFA (2), SECURİTAS (2), AVUSTURYA (2).
- **Listedeki gerçek çakışma:** PALLADIUM 27 Ekim'de t_tek_guv1'e yazılmıştı, ama ekip o gün KİPA turundaydı. Sistem 409
  verdi; iş 5 Kasım'a araçla planlandı.
- **Erteleme:**
  - 000092: neden yazmadan → 409. Geçersiz neden → 400 (geçerli nedenler listeleniyor). Eski plan id ile → 409
    ("siz görüntülerken değişti", iyimser kilit). `ONCEKI_IS_UZADI` ile 3 Kasım'dan 5 Kasım'a ertelendi.
  - 000067 (hedef PLANLAMADA): `MUSTERI_TALEBI` ile 9 Kasım'a ertelendi, sonra plan geri alındı.
    - Nedensiz geri alma → 409. "Diğer" seçilip not yazılmayınca → 400.
    - Geri almadan sonra durum **PLANLAMADA**. Plan geçmişi 2 satır.
  - 000053 (beklemede) `MALZEME_BEKLENIYOR` ile 10 Kasım'a ertelendi; durum BEKLEMEDE kaldı.
- **Beklemeler:**

  | İş | Neden |
  |---|---|
  | 000023 | MUSTERI_ERISIMI |
  | 000024 | DIS_SERVIS (beklenen bitiş verildi) |
  | 000053 | MALZEME |
  | 000054 | MUSTERI_ERISIMI |
  | 000025 | MUSTERI_ONAYI |
  | 000026 | DIGER (açıklamalı) |
  | 000048 | DIGER |
  | 000049 | DIGER |

  Ret denemeleri: açıklamasız DIGER → 400; `BAKIM_UYGUNSUZLUK` → 400 "yalnız sistem açar"; aktif beklemesi olan işe
  ikinci bekleme → 409.
- **Müsaitlik:** t_sef_guv, t_tek_guv2 için 7 Kasım'a "İzin" bloğu açtı. Nota "Doktor raporu" yazılınca 400 döndü (KVKK
  uyarısı doğru). `/kontrol` isteği izinli günü MUSAITLIK çakışması olarak gösterdi.

### 1.3 t_yon_hab (TELEKOM): Haberleşme planı
14 iş planlandı: 000112–000118 ve 000120–000126 (İGDAŞ'ın 2 telsizi tek ziyarette, ZYR-202611-000021).
- 000117 bekletildi (DIS_SERVIS).
- 000119 (hedef MUSTERI_TALEBI) planlanmadı.
- Ekipler: t_tek_hab (sorumlu); keşif, kurulum ve demontaj işlerinde ayrıca t_sef_hab sahada.

### 1.4 t_sef_bar: Set Bariyer
- 000129 (TAŞIMA, 5 Kasım) ve 000127 (KURULUM, 6 Kasım) şef tek başına sahada olacak şekilde planlandı.
- 000128 (TOPLAMA, hedef MUSTERI_TALEBI) şef "sahaya gitmiyor" seçilerek planlandı. Sistem bu planı kabul etti (bulgu B7).
  Plan sonra geri alındı (DIGER + not); durum PLANLAMADA.

### 1.5 t_sef_guv
- **Görünürlük:** Kendi biriminin işlerini görüyor (115 iş). Benim İşlerim'de kendisine tayinli 32 iş var (30 geciken, 2 bugün).
- **Ekip içi yeniden tayin:** 000109'a t_tek_guv1 eklendi (200).
- **Ret denemeleri:**
  - Ekibe Set Bariyer şefi → 409 "… bu işin biriminde değil".
  - Ekibe Haberleşme teknisyeni → 409 (aynı mesaj).
  - Var olmayan kişi → 400.
  - İki sorumlu → 409.
- **Erteleme:** 000111 `PERSONEL_YOK` ile 5 Kasım'a ertelendi.
- **Başka birimin işleri:** Haberleşme ve Bariyer işlerine plan denemesi → 404.
- **Yetkiler:** Şefin `servis.planla`, `servis.kalite_onay`, `bakim.onayla`, `servis.kapat` izinleri var
  (bulgu B4).
- **Kaza ve düzeltme:** Bir deneme 000109 ekibini geçici olarak bozdu (şef teknisyen rolüyle eklendi, t_tek_guv1 çıktı).
  Ekip aynı dakika içinde düzeltildi; şimdi t_tek_guv2 (sorumlu) + t_tek_guv1.

### 1.6 Yetki sınırları: id ile doğrudan erişim
- **t_yon_guv → Haberleşme işleri (112, 114, 119):**
  - Tek iş uçları 404: GET iş, plan GET/PUT/DELETE, atama, bekleme, saha önerisi.
  - Toplu uçlar 404: `toplu-plan`, `yeniden-plan`, `toplu-atama`.
  - Takvim ve havuz `birim=HABERLESME` ile boş dönüyor; `q=İGDAŞ` araması da boş.
- **t_yon_hab → Güvenlik ve Bariyer işleri (27, 96, 127, 130):**
  - GET, plan, toplu plan, plan geçmişi, ekip, ziyaret formu ve servis formu 404.
  - Takvim Excel'i `birim=GUVENLIK` ile 0 satır.
  - Güvenlik teknisyeni, şefi ya da aracıyla plan → 409/409/409.
- **Sızıntı:** `/planlama/kontrol` ucu ve 409 mesajları başka şirketin bilgisini açıyor (bulgu B3).

### 1.7 Takip: sayı = liste
Sayılar planlamadan önce ve sonra okundu (t_yon_guv).

| Kart | Önce | Sonra |
|---|---:|---:|
| Plan bekleyen | 97 | 8 |
| Planlandı | 2 | 84 |
| Beklemede | 0 | 8 |
| Tayin edilmemiş | 97 | 45 |
| Ana Panel "Askıdaki" | 0 | 8 |

Ana Panel "Açık İş Emirleri" 100 (Güvenlik 97 + Bariyer 3) gösteriyor.

Karşılaştırma şöyle yapıldı:
- Servis Paneli: 24 kutu, her biri `/isler?kpi=` listesinin toplamıyla.
- Planlama: 6 KPI, her biri `/kpi-liste` toplamıyla.

Hesaplar: t_yon_guv, t_yon_hab, t_sef_guv. **Hepsi eşit.**

Mantık sorunları ayrıca var: tayin edilmemiş sayısı, SLA riski ve geciken plan (bulgular B1, B6, B8).

### 1.8 Arayüz (Playwright, 1440 px; teknisyen 390 px)
- **Kullanılan ekranlar:** Planlama (Takvim, Gün, Hafta, Kaynak), plan penceresi, takvim kartı → ziyaret paneli
  ("Planı Düzenle / Geri Al / Plan geçmişi"), iş ayrıntısı (`/servis-isleri/96`, çekmece), "Tayini Değiştir" penceresi,
  Ana Panel, Benim İşlerim (şef, ve teknisyenin telefon görünümü).
- **Yazdırma:** Planlama ekranında "Yazdır" ya da PDF yok, yalnız Excel var. Ziyaret formu PDF'i bu makinede 503 döndü:
  Pango/Cairo kitaplıkları yok, bu bir ortam sorunu.
- **Yan etki:** UI betiği bir ara sol menüde "Planlama"yı yanlışlıkla sık kullanılanlara ekledi. Sonraki oturumda görünmüyordu.

## 2. Bulgular

| No | Önem | Tür | Ekran / uç | Yeniden üretme | Beklenen | Gerçekleşen | Önerilen düzeltme |
|---|---|---|---|---|---|---|---|
| B1 | YÜKSEK | akış/veri | Servis Paneli "Tayin Edilmemiş", `/isler?kpi=atanmamis`, Ana Panel "Tayin Edilen Personel" | 1) Bir işi yalnız şef sahaya gidecek şekilde planla (ör. 000055–59, 000127/129). 2) "Tayin Edilmemiş İşler"i aç. | Ekibi planlanmış iş tayinli sayılmalı | Güvenlik'te 45 "tayin edilmemiş" iş var; 35'inin şef ekibi var. Liste etiketi aynı iş için "TAYİN EDİLDİ" diyor. Ana Panel'de "Tayin Edilen Personel" boş ("—"). Set Bariyer'de yalnız şef olduğundan ve sorumlu yalnız TEKNİSYEN olabildiğinden (`atama.py:103-104`), Bariyer işleri **hiçbir zaman** tayinli görünmüyor | `atanmamis` = aktif tayini (rolü fark etmeksizin) olmayan iş; ya da sahaya giden şef sorumlu olabilsin. Etiket ve KPI aynı ölçütü kullansın |
| B2 | YÜKSEK | veri | Planlama → Kaynak (`/planlama/kaynak-gorunumu`) | 5 cihazlık PALLADIUM ziyaretini 300 dk planla, sonra 5 Kasım'a bak | Ziyaretin süresi bir kez sayılmalı (300 dk) | t_tek_guv1 için 5 Kasım: **1560 dk** (2 ziyaret, 6 iş → 5×300+60). 2 Kasım: 660 dk. Ziyaretteki her iş ayrı sayılıyor, kapasite planı 5 kat şişiyor | `takvim.py` kaynak hesabında aynı ziyaret ve aynı saat aralığını kişi başına birleştir (aralık birleşimi) |
| B3 | ORTA | sızıntı | `POST /planlama/kontrol`; `PUT /isler/{id}/atama` ve `PUT /planlama/isler/{id}/plan` 409 mesajı | t_yon_hab (TELEKOM) `kontrol`'e `kisi_idler:[24,21]` ya da `arac_id:1` gönderir; ya da kendi işine id ile Güvenlik kullanıcısı eklemeye çalışır | Kapsam dışı kişi/araç 404 dönmeli; başka şirketin adı ve takvimi görünmemeli | `kontrol` başka şirketin personelinin ve aracının dolu saatlerini döndürüyor (birim GUVENLIK, saat aralığı; iş no maskeli). 409 mesajı kişinin tam adını veriyor ("… Güvenlik 1 bu işin biriminde değil"); id taramasıyla şirketler arası ad listesi çıkarılabilir | `teknik_servis_planlama.py:456` kişi/araç kapsam kontrolü (dışındaysa 404). `atama.py:110-126` kapsam dışı kişi için "Kullanıcı bulunamadı (#id)" |
| B4 | ORTA | yetki | `permissions.py` SERVIS_SEF | t_sef_guv ekip değiştirir, erteler, plan geri alır | KARARLAR 2026-10-28 §(D3.1/D4.2): "saha takım lideri tayin edemez; ekibini görür, kalite onayı verir" | Şefte `servis.planla` var: tayin, plan, erteleme, geri alma ve müsaitlik bloğu açabiliyor | Kararı netleştir: lab ve saha şefini ayır (ör. SERVIS_SEF_LAB) ya da saha şefinden `servis.planla`'yı çıkar. Gerekirse kararı güncelle |
| B5 | ORTA | akış | Planlama → Toplu Planla (`toplu_planla`, `planlama.py:723`) | §7.6: KİPA'nın 9 şubesi, 2 ekip, 3 gün | Bir "tur" (aynı gün, aynı ekip, şube sırası, tek araç) tek seferde planlanabilmeli; şubeler arası saat çakışma sayılmamalı | Farklı tesis → 409. 9 ayrı ziyaret ve 9 ayrı plan girildi. Aynı ekibin aynı gündeki ikinci şubesi ya ayrı saatle ya da çakışma gerekçesiyle girildi. Tur bazlı görünüm, rota ve fatura (ziyaret başı) birliği yok | "Tur" kaydı (birden çok ziyaret, sıra, ekip, araç) ya da toplu planda "farklı lokasyon → ardışık saatlerle ayrı ziyaretler" seçeneği |
| B6 | ORTA | akış | `PUT /planlama/isler/{id}/plan`, Ana Panel, takvim | 4 Kasım'da 26 Ekim'e plan yap | Geçmiş tarihe plan uyarıyla (ya da gerekçeyle) yapılmalı; planı geçmiş açık iş yöneticiye görünmeli | Geçmiş tarih uyarısız kabul edildi (68 iş). Bu işler yalnız teknisyenin "Geciken" grubunda görünüyor. Ana Panel ve Servis Paneli'nde "planı geçmiş" kartı yok; haftalık takvimde gecikme rengi yok | Plan yazımında `plan_tarihi < bugün` için onay/uyarı. Ana Panel'e "Geciken plan" KPI'ı (`/isler?kpi=plan_gecikti`) ve takvimde gecikme işareti |
| B7 | ORTA | akış | Tekli plan (`planlama.planla`, `planlama.py:504`) | 000023/24/53 ekipsiz ve saatsiz planlanır; 000128'de şef "sahaya gitmiyor" seçilir, teknisyen yok | Sahaya kimse gitmeyen plan "Planlandı" olmamalı (toplu planda olduğu gibi) | Tekli plan ekipsiz ve sahada kişisiz planı kabul ediyor, durum PLANLANDI oluyor. Toplu plan bunu "en az bir şef ya da teknisyen" diye reddediyor; iki uç tutarsız | Tekli planda da sahada en az bir kişi zorunlu olsun; ya da ekipsiz plan PLANLAMADA'da kalsın |
| B8 | ORTA | veri | Ana Panel "SLA Riski Olan İşler", iş kartı SLA etiketi | Güvenlik ve Haberleşme işlerine bak | SLA riski anlamlı olmalı | Açık işlerin hepsi "Ölçülemedi" (Güvenlik 97, Haberleşme 16; PB'ler "SLA dışı"). Kart her zaman 0 gösteriyor ve güven vermiyor | Varsayılan birim/tür SLA hedefi tanımlansın ya da kartta "ölçülemeyen: N" ayrıca gösterilsin |
| B9 | ORTA | akış | Plan penceresi / `PlanIn` | Kıbrıs konveyör teslimi 26–31 Ekim | Çok günlü saha işi tek planla girilebilmeli (şehir dışı kurulum ve proje) | Süre en çok 1440 dk, bitiş tarihi yok. Aralık yalnız nota yazılabildi; çakışma kontrolü sonraki günleri görmüyor | `plan_bitis_tarihi` (günlük saat aralığıyla) ya da çok günlü plan desteği |
| B10 | ORTA | UX | Planlama (takvim) | Ertesi günün planını ekibe göndermek | §3.8: günlük plan çıktısı (PDF/görsel, WhatsApp'a) | Yalnız Excel var (`takvim.xlsx`); yazdır/PDF/görsel yok. Ziyaret formu PDF'i var ama plan özeti değil | Gün görünümüne "Günlük plan PDF'i" (ekip, saat, müşteri, tesis, irtibat, araç) |
| B11 | DÜŞÜK | UX | Planlama ekranı | 1440×900'de sayfayı aç | Takvim ilk ekranda görünmeli | 6 KPI kartı ekranın yaklaşık %60'ını kaplıyor, takvim katlanma çizgisinin altında kalıyor. 27.10 seçiliyken kart hâlâ "Bugün planlı: 21" diyor | Kartları tek satır ve kompakt yap. Başlık seçili günü göstersin ("27.10 planlı") |
| B12 | DÜŞÜK | UX | Haftalık takvim kartı | Hafta görünümü, 27 Ekim | Kartta müşteri ve ekip okunmalı | Müşteri ve ekip adları kırpılıyor ("KİPA AVM · E…", "Test Saha Sor…"); "+4 daha" ile işler gizleniyor | Hafta görünümünde satır yüksekliği ya da hover/özet; gün başına liste görünümü |
| B13 | DÜŞÜK | UX | İş ayrıntısı çekmecesi | `/servis-isleri/96` | Yönetici için sade ekran (G1.9) | 13 eylem düğmesi var, 7'si durum düğmesi (Planlamada/Yola Çıkıldı/Sahada…). Plan tarihi Genel sekmesinde yok; ayrıntıdan "Planla" düğmesi yok | Durum düğmelerini "Durum ▾" menüsünde topla. Genel sekmesine "Plan: tarih/saat/ekip" satırı ve "Planla" düğmesi ekle |
| B14 | DÜŞÜK | UX | Plan penceresi, Ekip Tayini penceresi | Havuzda "Planla" ya da "Tayini Değiştir" | Hangi iş planlandığı ve kimin sorumlu olduğu açık olmalı | Plan penceresinde iş no ve konu yok (yalnız tesis ve il). Sorumlu seçimi yok (ilk teknisyen sorumlu oluyor). Tayin penceresinde ikinci (sorumlu) alanın etiketi yok | Pencere başlığına iş no ve konu; "Sorumlu" etiketi |
| B15 | DÜŞÜK | UX | Ana Panel kartı | Ana Panel | Değişim okunur olmalı | "↑ %2.400 (dönem başına göre: 4)": içe aktarma günü 4'ten 100'e çıkış Türkçe binlik ayırıcıyla anlamsız görünüyor | Taban küçükse yüzde yerine "+96" göster |
| B16 | DÜŞÜK | veri | Müsaitlik çakışma metni | 7 Kasım tam gün izin, sonra `/kontrol` | "07.11 00:00 – 08.11 00:00" ya da "07.11 tüm gün" | "07.11.2026 00:00–00:00" | `saat_araligi` gün aşımında bitiş tarihini yazsın |
| B17 | DÜŞÜK | veri | Plan çıktısı `iptal_at` | Plan geri al | Tek saat dilimi | Geri almada `iptal_at` "+00:00", ertelemede pasiflenen planda "+03:00" | Çıktıyı yerel saate çevir (`_plan_cikti`) |
| B18 | DÜŞÜK | veri | Neden katalogları | Erteleme ve bekleme | Aynı kavram aynı kod olmalı | Erteleme kodları `MALZEME_BEKLENIYOR` ve `PERSONEL_YOK`; bekleme kodları `MALZEME` ve `PERSONEL`. Raporlarda birleştirmek zor | Ortak kod sözlüğü ya da eşleme tablosu |
| B19 | DÜŞÜK | sızıntı | `GET /personel` | t_yon_hab (TELEKOM) personel listesini açar | Yalnız etkin şirketin kişileri | Birimsiz bütün kullanıcılar görünüyor: diğer şirketlerin depo/finans hesapları, admin, yönetim | Birimsiz kişi yalnız şirket üyeliğiyle süzülsün |
| B20 | DÜŞÜK | yetki | Ekip Tayini | t_sef_guv kendisini TEKNİSYEN rolüyle ekibe ekler | Saha rolü SEF olan kişi şef rolüyle eklenmeli | Kabul edildi (rol = TEKNİSYEN, saha_rolu = SEF) | Rol ile saha_rolu tutarlılığı (uyarı yeterli) |

Bilgi (bulgu değil): Güvenlik yöneticisinin kapsamı TUMU olduğundan aynı şirketteki Set Bariyer işlerini de görüyor ve
planlayabiliyor. 1. aşamadaki B16 (Bariyer'in yöneticisi yok) düşünülünce bu işe yarıyor, ama karar olarak yazılmalı.

## 3. İyi çalışanlar
- **Şirket ayrımı:** Bütün tekli ve toplu plan/tayin/bekleme uçlarında id ile çapraz erişim 404. Takvim, havuz, Excel
  ve arama boş dönüyor. Başka birimin kişisi ya da aracı plana eklenemiyor.
- **Sayı = liste:** Servis Paneli'nin 24 kutusu ve Planlama'nın 6 KPI'ı, liste toplamlarıyla üç hesapta da birebir aynı.
- **Çakışma motoru:** Kişi, araç ve müsaitlik çakışmasını yakalıyor. Gerekçe en az 10 karakter. Ziyaret içi işler
  birbiriyle çakışma saymıyor.
- **Plan kuralları:** Erteleme nedeni zorunlu, geçerli neden listesi mesajda veriliyor. İyimser kilit (`beklenen_aktif_plan_id`)
  çalışıyor. Plan geçmişi tutuluyor. Geri almada neden zorunlu ve durum PLANLAMADA'ya dönüyor.
- **Bekleme:** Neden kataloğu, DIGER açıklama zorunluluğu, sistem nedeni koruması ve tek aktif bekleme kuralı çalışıyor.
- **Müsaitlik:** Notta sağlık bilgisi engelleniyor (KVKK).
- **Benim İşlerim:** Ziyaret bazlı gruplama (Geciken / Bugün / Yarın / Sonraki / Plansız) anlaşılır, telefonda da okunuyor.
  Şef "Tümü" görünümüne geçebiliyor, teknisyen geçemiyor (403 mesajı açık).
- **Arayüz:** Arayüzden tekli plan 7 eylemde bitiyor. Takvim kartı ziyaret panelini açıyor; düzenleme ve geri alma oradan yapılabiliyor.

## 4. Kayıtlar
- **Planlanan işler:**
  - Güvenlik: 000027–000047, 000050–000052, 000054–000066, 000068–000111 (000067 ertelenip geri alındı).
  - Haberleşme: 000112–000118, 000120–000126.
  - Bariyer: 000127, 000129.
- **Plansız bırakılanlar:** 000119, 000128, 000130, 000131, 000132 (hedef MUSTERI_TALEBI).
- **Beklemedekiler:** 000023, 000024, 000025, 000026, 000048, 000049, 000053, 000054, 000117.
- **Ziyaretler:** ZYR-202610-000001…000007, 000009…000015, 000019; ZYR-202611-000008, 000016…000018, 000020, 000021.
- **Diğer kayıtlar:** servis aracı id 1 (GUVENLIK); müsaitlik bloğu id 1 (t_tek_guv2, 7 Kasım, izin).
- **Sözleşme uyumu:** Listede "Tamamlandı" ya da "İşlemde" hedefi olan işler yalnız planlandı (durum PLANLANDI); sonucu
  3. aşama girecek. Plan tarihlerinin bir kısmı geçmişte (listedeki tarihler), bu yüzden teknisyen ekranında "Geciken"
  grubunda görünüyorlar.
