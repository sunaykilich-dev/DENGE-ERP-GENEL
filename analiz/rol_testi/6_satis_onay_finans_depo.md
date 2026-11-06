# Rol testi 4. aşama: Satış, Satış Destek, TS Yöneticisi (kalite), Finans, Depo, Üst Yönetim (2026-11-04)

Ortam yereldi (API 127.0.0.1:8000, web 127.0.0.1:5173). Kod değiştirilmedi, canlıya dokunulmadı. Kişi adı ve parola
yok; kullanıcılar test koduyla anılıyor. Betikler, kayıtlar (`log_*.json`) ve ekran görüntüleri (`k01…k16.png`, 1440 px):
`C:\Users\skilic\AppData\Local\Temp\claude\ff375d97b5e42a31\c9ec6dae-0467-416d-a7b6-190f1738d382\scratchpad\rol_testi\kapanis\`

Bir istisna dışında yalnız iş verisi değiştirildi. İstisna: ofis kısıtını denemek için `ofis_ag_listesi` ayarı admin
ile yaklaşık 1 dakikalığına değiştirildi ve hemen eski hâline (`[]`) döndürüldü (bkz. 1.3).

## 1. Ne yaptım

### 1.1 Satış destek ve satış (t_sdestek_guv, t_satis_guv)

**Teklif bekleyen 5 iş.** Her iş için parça ve işçilik kalemli birimli teklif hazırlandı. Teklif işten açıldı;
müşteri, birim ve adres işten geldi.

| İş | Teklif | Akış | Teklif sonucu | İşin sonraki durumu |
|---|---|---|---|---|
| SRV-202611-000064 (MALTEPE PARK) | TKF2026-00001 (112.800 ₺ KDV dahil) | Onaya gönder (`beklet`) → t_yon_guv onayladı → elle gönderildi (e-posta) → KABUL | KABUL | BEKLEMEDE(TEKLIF) → **İŞLEMDE** |
| SRV-202611-000080 (AVUSTURYA BAŞKONSOLOSLUĞU) | TKF2026-00002 (18.000 ₺) | Aynı akış | KABUL | → **İŞLEMDE** |
| SRV-202611-000065 (MALTEPE PARK) | TKF2026-00003 | Gönderildi → nedensiz red 400 → nedenli RED | RED | → **İŞLEMDE** |
| SRV-202611-000066 (MALTEPE PARK) | TKF2026-00004 | Onaylandı ve gönderildi; karar bekliyor | GONDERILDI | BEKLEMEDE(TEKLIF) |
| SRV-202611-000090 (İST. HAVALİMANI GÖÇ İD.) | TKF2026-00005 | Onaya gönderildi | ONAY_BEKLIYOR | BEKLEMEDE(TEKLIF) |

- Satış destek teklifini kendisi onaylamayı denedi: 403 (`teklif.onayla`). Bu doğru.
- Kabul ve red işi aynı yere götürüyor: bekleme kapanıyor ve iş önceki durumu olan İŞLEMDE'ye dönüyor. Bkz. Y1 ve Y2.

**Atölye AT-202611-000002 / SRV-202611-000140 (ESAN BALYA, klavye).**
1. Teklif TKF2026-00007 (3.840 ₺) hazırlandı.
2. Onaya gönderirken uyarı geldi: "İşte başka nedenli aktif bekleme var; teklif beklemesi açılmadı".
3. Teklif onaylandı, gönderildi ve KABUL edildi. Atölye kaydı ONAY_BEKLİYOR'da, iş MÜŞTERİ_ONAYI beklemesinde kaldı.
4. t_atolye_guv onay kaydını girmeden ONARIMDA'ya geçebildi. Kural, işe bağlı kabul edilmiş teklifi onay sayıyor. Bu
   doğru, ama ustaya bildirim gitmiyor.
5. Ardından onay kaydı girildi (ONAYLANDI/EPOSTA), test GEÇTİ, teslime hazır ve TESLİM EDİLDİ yapıldı. İş TAMAMLANDI
   oldu; süre "EKSIK" (atölye ustası süre giremiyor, 5. rapor B5).

**Satış (t_satis_guv, KENDI_MUSTERILERI).**
- `servis.gor` izni yok. Servis işi 403. Ana Panel açılmıyor ("Ana panel yüklenemedi — servis.gor").
- Menüdeki "Sonuçlanan Arıza İşleri" 403 veriyor.
- Kendi müşterisi yok (`/hesaplar` 0 kayıt). Teklif listesi boş: satış destek'in hazırladığı servis teklifleri,
  `owner_id` satış destek olduğu için görünmüyor.
- Buna karşın görmediği müşteri (id 19, `/hesaplar/19` 404) için teklif açabildi: TKF2026-00006 (sonra kendisi iptal
  etti). Servis işine bağlı teklif ise 404.

### 1.2 TS yöneticisi ve şef: kalite onayı (t_yon_guv, t_sef_guv, t_yon_hab, t_sef_hab)

**Başlangıç sayıları (t_yon_guv):**

| Gösterge | Sayı |
|---|---|
| "Kalite Onayı Bekleyen" listesi | 43 (PB-202601-000001 dahil) |
| Ana Panel "Bekleyen Onaylar" | 42 (liste 42, PB hariç) |
| Bekleyen aksiyonlar "Şef (kapanış onayı)" | 43 |
| KPI `kapanis_bekleyen` | 42 |

Bkz. O4.

**Görevler ayrılığı.**
- t_sef_guv 44 işin 13'üne onay veremiyor ("tayin edildiğiniz için", 403). Doğru davranış.
- Şef her ekipte SEF olarak yer aldığından yükün tamamı yöneticiye kalıyor.

**Yönetici onayları.** t_yon_guv 12 işe tek tek kalite onayı verdi:
- 000080, 000036 (süre EKSİK), 000087 (KISMİ), 000110 (EKSİK), 000097–000102, 000107, 000108.
- Süre eksik ve kısmi işlerde hiçbir uyarı çıkmadı (O2).
- Eski `version` ile istek 409 döndü.
- Toplu onay ucu yok (405). Listede seçim kutusu yok (`k06`).
- SRV-202611-000140'a da onay verildi.

**Kapanış.**
- t_yon_guv kapattı: 000080, 000036, 000108.
- t_sef_guv kalite onayı olmayan 000068'i KAPATILDI yaptı. Kapanış ile kalite birbirinden bağımsız iki ayrı onay.

**Ret ve geri gönderme yok.** Makinede TAMAMLANDI'dan yalnız KAPATILDI'ya gidiliyor. Kaliteyi beğenmeyen yöneticinin
tek seçeneği bağlı yeni iş açmak. İş kalite kuyruğunda süresiz kalıyor (Y5).

**Diğer işler.**
- Uygunsuzluktan açılan 000135–137: MÜŞTERİ TALEBİ durumunda. "Plan bekleyen" ve Ana Panel aksiyonlarında
  görünüyorlar; PB işleri BAKIM_UYGUNSUZLUK beklemesinde.
- t_yon_hab ve t_sef_hab: yalnız HABERLESME (000121, 000126). Sızıntı yok.

**Yan etki düzeltmesi: SRV-202611-000096 (görev 7).**
1. Doğrudan PLANLANDI denendi: 400 ("planla ucunu kullanın").
2. Aynı plan yeniden yazıldı (200), ama durum değişmedi. `planlama.PLANLANDIYA_GECER` YOLA_CIKILDI'yı içermiyor.
3. Plan geri alma bu duruma uygun değil.
4. Geçici yol: bekleme (DİĞER) → bekleme bitir (iş PLANLAMADA'ya düştü) → yeniden planla.

Sonuç: 000096 **PLANLANDI**, süre "BEKLENMIYOR", aktif bekleme yok. Bu üç adımlık yol bulgu sayıldı (Y6).

### 1.3 Finans (t_finans_yon, t_finans_uzm)

**Şirket geçişi (t_finans_yon).**

| Şirket | Fatura devri | Diğer |
|---|---|---|
| MOBİLİTE | 0 | Ana Panel 0 |
| ELEKTRONİK | 000080 (teklif, 15.000 ₺ KDV hariç) | Teklifler TKF-00001…00007 |
| TELEKOM | 0 | Açık iş 13 |

Sızıntı yok. Giriş sonrası açılan şirket MOBİLİTE; teknik servis verisi orada boş.

**Kalite onaysız devir.** 000064 şef sonucu ile TAMAMLANDI oldu; kalite ve kapanış onayı yoktu. İş hemen fatura devri
"bekleyen" listesine düştü (94.000 ₺). SRV-202611-000140 da onaysız düştü (Y3).

**İşaretleme (t_finans_uzm):**
- Toplu [80, 70] isteği bütünüyle 409 döndü ve `sorunlu_isler=[70]` yazıldı.
- 80 tek başına iletildi olarak işaretlendi.
- Boş gerekçeyle geri alma 422, gerekçeyle 200.
- t_finans_yon 80'i yeniden işaretledi.
- Gelir kilidi çalışıyor: faturaya iletilmiş işin teklifini iptal etme isteği 409 ("önce devri geri alın").

**Maliyet görünürlüğü.**

| Kullanıcı | Maliyet | Diğer |
|---|---|---|
| t_finans_yon | Görüyor (doğru) | — |
| t_finans_uzm | Görüyor: `/maliyet/isler/80` işçilik/malzeme/fark durumu, fatura devri tutarı | Servis işi detayı 403, maliyet analizi 403, Excel 403, Ana Panel hata veriyor |
| t_yon_guv (TS yöneticisi) | **Görmüyor** (`maliyet.gor` yok) | — |

Finans uzmanının maliyet görmesi G4.4'e aykırı (Y7). TS yöneticisinin görmemesi de G4.4'e aykırı (O6).

**Bakım dönem kapanışı (§7.6 "Ekim bakım turu").** Yapılamadı:
- BAKIM-0001 ve 0002'de `fee_per_visit` boş. Ücret ucu `bakim.yaz + maliyet.gor` istiyor; bu ikisi bir arada yalnız
  ADMIN'de var.
- Tamamlanan PB-202601-000001 `gelir_durumu=SOZLESME_KAPSAMI`, gelir boş. Fatura devrine düşmüyor.
- Ekim turunun KİPA işleri (000027–032 vb.) PLANSIZ_BAKIM, gelirsiz. Devre hiç düşmüyor.
- Dönem kapanışı / "faturalanacak" işareti yok (Y4).

**Logo.** Yalnız fatura devri Excel'i var (t_finans_yon). Logo formatı ve aktarımı yok (Faz D, beklenen).

**Ofis kısıtı.** Varsayılan `ofis_ag_listesi=[]` olduğu için kısıt kapalı. Ayar admin ile 10.250.0.0/16 yapıldı:
- t_finans_uzm'un açık oturumu 403 `OFIS_DISI_ERISIM` aldı.
- Yeni giriş 403 (X-Forwarded-For'suz ve 8.8.8.8 ile).
- 127.0.0.0/8 yapılınca 200.
- t_finans_yon etkilenmedi.

Ayar geri alındı (`[]`). Not: yerelde uvicorn 127.0.0.1'den gelen X-Forwarded-For'a güvendiği için XFF'de "ofis içi"
bir IP yazılınca giriş açılıyor. Canlıda `--forwarded-allow-ips` yalnız vekile verilmeli.

### 1.4 Depo (t_depo_guv)

**Hazırlık.** RT3-YP-05 (jeneratör) RT3-GUV deposuna girildi: RT4-IRS-1, iki kez 2 adet (biri `unit_cost`'lu; tasarım
gereği yazılıyor, yanıtta gizli). Fazladan 2 adet stokta kaldı.

**SRV-202611-000093.** Depo doğrudan işe çıkış yaptı. Talep KARŞILANDI oldu. İş BEKLEMEDE(MALZEME)'den **İŞLEMDE**'ye
döndü.

**SRV-202611-000105.**
1. Depo, t_tek_guv1'in araç deposuna (RT3-ARC-G1) transfer yaptı.
2. Talep ACIK kaldı, iş beklemede kaldı. Teknisyene bildirim gitmedi.
3. Teknisyen araç deposundan çıkış yaptı. Talep KARŞILANDI oldu, iş İŞLEMDE'ye döndü.

**Teknisyen çıkışının depo onayı (D6.7).** Böyle bir alan ya da ekran yok.

**Satılan cihazlar (B bölümü, 145 ekipman KURULUM_BEKLIYOR).** Depo kütüğü göremiyor:
- `ekipman.gor` ve `ekipman.yaz` 403. Satılan cihazın depo girişi, seri kaydı ve sevkiyat hazırlığı akışı yok.
- `/siparisler` yalnız MOBİLİTE'de açılıyor (satış destek de 403 SIRKET_DISI).

### 1.5 Üst yönetim (t_yonetim)

Üç şirkette Ana Panel, servis paneli, teklif dönüşümü ve fatura devri tarandı. Sayı = liste denetimi:
- Ana Panel KPI'larının hepsi tutarlı (`kpi=` listesi ile).
- Birim özetinin açık/sahada/atölyede/tamamlanan/dönem iş emri sayıları da tutarlı.

ELEKTRONİK:

| Gösterge | Değer |
|---|---|
| Açık | 61 |
| Bekleyen onay | 41 |
| Askıda | 10 |
| SLA riski | 0 |
| GÜVENLİK tamamlanan | 44 |
| Teklif dönüşümü (GÜVENLİK) | 7 teklif, 3 kabul / 1 red, %75, kabul net 112.200 ₺ |
| Fatura devri bekleyen | 1 (taramadan sonra 000064 ve 000140 eklendi) |

Yazma denemesi 403. TELEKOM ve MOBİLİTE verileri ayrı.

**Eksikler:**
- Ana Panelde teklif dönüşümü ve fatura devri KPI'ı yok. Fatura devri yalnız "Mali İşler" aksiyon satırında.
- "SLA riski 0" yanıltıcı: açık 61 işin hiçbirinde SLA hedefi yok.
- Bölüm iş yükü GÜVENLİK 75 (PB dahil), Açık İş KPI 58 (PB hariç): aynı ekranda iki ayrı "açık".
- Teklifi reddedilen 000065 ve parçası gelen 000093/105 İŞLEMDE kaldıkları için panelde **"sahada"** sayılıyor.

## 2. Bulgular

| No | Önem | Tür | Ekran / uç | Yeniden üretme | Beklenen | Gerçekleşen | Önerilen düzeltme |
|---|---|---|---|---|---|---|---|
| Y1 | YÜKSEK | akış (kopuk el değiştirme) | `POST /teklifler/{id}/karar` → `services/quotes.py` `bekleme_kapat` → `bekletme.beklemeyi_bitir` | 000064/080: teklif KABUL | İş "ikinci ziyaret planlanacak" kuyruğuna düşer (PLANLAMADA, Plan bekleyen KPI, planlama havuzu); şef/yöneticiye bildirim gider | İş önceki durumu İŞLEMDE'ye döner. Plan bekleyende ve havuzda yok, bildirim yok. İŞLEMDE→PLANLAMADA makinede yok. Plan yazılsa da durum İŞLEMDE kalıyor (000080 denendi). Panelde "sahada" sayılıyor | Teklif KABUL'de beklemeden dönüş hedefi PLANLAMADA olsun (`_donus_durumu`'na neden bazlı hedef: TEKLIF/MALZEME → PLANLAMADA). Ya da `SERVIS_IS_EMRI` ISLEMDE→PLANLAMADA kenarı + "Teklif kabul — planlanacak" aksiyon satırı |
| Y2 | YÜKSEK | akış | Aynı yer, RED | 000065: teklif RED | İş kapanış kararına gider (şefe "teklif reddedildi: kapat / çözülemedi" görevi) | İş İŞLEMDE'ye dönüyor, sonuç TEKLIF_SUNULACAK kalıyor. Kimse görmüyor; Ana Panelde "sahada" sayılıyor | RED'de işi şefin kapanış aksiyonuna (Ana Panel "Şef" satırı) düşür, ya da sonucu otomatik "Çözülemedi — teklif reddedildi" önerisiyle beklet |
| Y3 | YÜKSEK | akış/veri | `services/teknik_servis/fatura_devri.py:93` `uygun_kosulu` | 000064 TAMAMLANDI (kalite ve kapanış yok) → `GET /maliyet/fatura-devri` | §3.1/§5.9: yalnız kalite onaylı (ve kapatılmış) iş faturaya devredilir | Kalite onayı olmayan TAMAMLANDI iş hemen "bekleyen"de (000064 94.000 ₺, 000140). Finans, kalitesi onaylanmamış işi faturalayabilir | `uygun_kosulu`'na `ServiceOrder.kalite_onay_at.is_not(None)` ekle (ya da ayarla açılıp kapanan kural). Ana Panel "Mali İşler" sorgusu (`ana_panel.py:861`) aynı tanımı kullansın |
| Y4 | YÜKSEK | akış | Bakım sözleşmesi ücreti, `maliyet.gelir_kaydet`, fatura devri | §7.6 Ekim bakım turu: tamamlanan PB-202601-000001 ve KİPA bakım işleri | Dönem kapanışında ziyaret başı ücretle "faturalanacak" satırlar | Sözleşmelerde `fee_per_visit` boş. Ücret ucu `bakim.yaz+maliyet.gor` istiyor (yalnız ADMIN). PB tamamlanınca SOZLESME geliri yazılmıyor (`gelir_durumu=SOZLESME_KAPSAMI`, gelir boş). Bakım işleri devre hiç düşmüyor. Dönem kapanış/faturala işlemi yok | PB TAMAMLANDI kancasında `fee_per_visit` varsa `gelir_kaynagi=SOZLESME` yaz. Ücret girişini FINANS_YONETICI'ye aç. Bakım dönemleri raporuna "Faturalanacak" sütunu ve dönem kapanışı ekle. Liste bakımları (PLANSIZ_BAKIM) için sözleşme bağı (5. rapor B2) |
| Y5 | YÜKSEK | akış | Kalite onayı, `statemachine.py:241` (TAMAMLANDI→yalnız KAPATILDI) | Kalitesi uygun olmayan tamamlanmış işi reddet / geri gönder | Ret + gerekçe, işin teknisyene dönmesi ya da düzeltici iş, kuyruktan düşmesi | Ret ucu yok. İş "Kalite Onayı Bekleyen"de süresiz kalıyor; tek yol elle bağlı yeni iş | `POST /isler/{id}/kalite-reddi` (gerekçe zorunlu): `kalite_red_at` yazar ve bağlı düzeltici işi (`bagli_yeni_is`, ilişki KALITE_RED) aynı transaction'da açar. `kalite_kosulu("BEKLEYEN")` reddedilenleri dışlasın |
| Y6 | YÜKSEK | akış/yetki | `planlama.py:79` `PLANLANDIYA_GECER`; iş detayı `gecisler` | SRV-202611-000096 YOLA_CIKILDI → yönetici PLANLANDI'ya almak istedi | Yönetici tek işlemle planı geri yükler | `durum` ucu 400. `planla` 200 döner ama durum değişmez; detay ise "PLANLANDI (planla) yetkili" diyor (yanlış vaat). Yalnız bekleme→bitir→planla geçici yoluyla düzeltilebildi (sahte bekleme kaydı da oluşuyor) | `PLANLANDIYA_GECER`'e YOLA_CIKILDI ekle (makine izin veriyor) ya da yönetici için "Yola çıkışı geri al" ucu. 5. rapor B1 düzeltmesiyle birlikte |
| Y7 | YÜKSEK | yetki | `permissions.py` MUHASEBE_DESTEK (`maliyet.gor`); `GET /maliyet/isler/{id}` | t_finans_uzm ile `/teknik-servis/maliyet/isler/80` | G4.4 ve §5.10/2: Finans uzmanı maliyet ve kârlılık görmez | 200: işçilik/malzeme/diğer maliyet ve fark durumu. Fatura devri tutarı da geliyor (tutar görmesi kabul edilebilir) | MUHASEBE_DESTEK'ten `maliyet.gor`'u kaldır. Fatura devri tutarı için `tahsilat.gor`'a bağlı ayrı kural (`fatura_devri.tutar_gorur_mu`) |
| Y8 | YÜKSEK | link/UX | Ana Panel (açılış sayfası) `GET /teknik-servis/ana-panel` | t_satis_guv ve t_finans_uzm ile giriş | Rolüne uygun açılış ekranı | İlk ekran "Ana panel yüklenemedi — Bu işlem için yetkiniz yok (servis.gor)" (`k08`, `k14`). Satışın "Sonuçlanan Arıza İşleri" menüsü de 403 | `servis.gor`'u olmayan rolde açılış sayfası Teklifler / Fatura Devri olsun, ya da Ana Panel izinsiz bölümleri gizleyerek açılsın. Satışa `servis.gor` (kendi müşterileri) ya da menüden bu yaprağı kaldır |
| O1 | ORTA | akış | Teklif `onaya-gonder`, atölye MÜŞTERİ_ONAYI | SRV-202611-000140: teklif hazırla → kabul | Kabul atölye beklemesini kapatır ya da ustaya bildirim gider | Uyarı "başka nedenli bekleme var; teklif beklemesi açılmadı". Kabulden sonra kayıt ONAY_BEKLİYOR'da kaldı, ustaya bildirim yok (ONARIMDA'ya geçişte kabul sayılıyor) | `bekleme_bagla`: MUSTERI_ONAYI beklemesini de teklife bağla (`quote_id`), kabulde `approval_decision=ONAYLANDI, channel=TEKLIF` yaz |
| O2 | ORTA | akış/veri | `POST /isler/{id}/kalite-onayi` | Süresi EKSİK (000036, 000110) ve KISMİ (000087) işlere kalite onayı | Onay penceresinde "süre kaydı eksik" uyarısı (ya da onaydan önce tamamlatma) | Uyarısız 200 | `kalite_durumu`'na `sure_durumu` uyarısı. Arayüzde onay penceresinde göster |
| O3 | ORTA | UX (G1.9) | Servis İşleri "Kalite Onayı Bekleyen" (`k06`) | 45 tamamlanan iş | Toplu onay; tek onay adımı | Toplu uç yok (405), seçim kutusu yok. Her iş için ayrı kapanış (`servis.kapat`) ve kalite onayı: iki onay × 45 iş, iş başına yaklaşık 6 tık | Toplu kalite onayı (seçili, görevler ayrılığı süzülerek). Kalite onayı kapanışı da yapsın (tek adım, G1.9) |
| O4 | ORTA | veri (sayı = liste) | Ana Panel `bekleyen_aksiyonlar` (`ana_panel.py:823`) | t_yon_guv Ana Panel | "Şef (kapanış onayı)" = KPI `kapanis_bekleyen` | Aksiyon 43 (PB dahil), KPI 42 (PB hariç). "Kalite Onayı Bekleyen" listesi PB'yi sayıyor (43), "Bekleyen Onaylar" saymıyor (42) | Aksiyon kaynağına `tur != 'PB'` ekle, ya da KPI'lar PB'yi de saysın. Tek tanım |
| O5 | ORTA | akış | Parça talebi karşılanınca bekleme bitişi (`parca.py:564`) | Depo 000093'e çıkış yaptı | İş yeniden planlamaya düşer, teknisyene/şefe bildirim gider | İş İŞLEMDE'ye döndü; planlama havuzunda ve bildirimde yok. Araç deposuna transfer talebi ilerletmiyor (ACIK kaldı) | Y1 ile aynı düzeltme (MALZEME → PLANLAMADA). Transferi talebe bağla (`part_request_id`, "teknisyene gönderildi" durumu) |
| O6 | ORTA | yetki | `permissions.py` SERVIS_YONETICI | t_yon_guv maliyet ucu | G4.4: TS yöneticisi maliyet görür | `maliyet.gor` yok (403). Bakım ücreti de giremiyor | SERVIS_YONETICI'ye `maliyet.gor` (karar G4.4) |
| O7 | ORTA | yetki/akış | t_depo_guv: ekipman 403 | §5.11/1, §7.6: 6 X-Ray depo girişi, seri kaydı, "kurulum bekliyor" | Depo kütüğe seri ile giriş yapar, sevkiyat hazırlığı işaretler | `ekipman.gor/yaz` yok. Satış siparişi yalnız MOBİLİTE'de. Satılan cihaz akışı yok | SERVIS_DEPO'ya `ekipman.gor` + seri/durum güncelleme. Ekipmanda "SEVKE_HAZIR" ara durumu (Faz C satışla bağlanır) |
| O8 | ORTA | yetki | Teknisyen parça çıkışı (D6.7) | t_tek_guv1 araç deposundan çıkış (000105) | Depo sonradan onaylar | Onay alanı ya da kuyruk yok | `stock_movements.onay_at/by` + depo "onay bekleyen çıkışlar" listesi |
| O9 | ORTA | UX/link | Fatura Devri ekranı (`k09`) | t_finans_yon / t_finans_uzm | İş numarası tıklanır, sonucu ve imzayı görür | İş no bağlantı değil. Finans uzmanı servis işini zaten açamıyor (403 `servis.gor`) | Satırda salt-okunur iş özeti (sonuç, kalite onayı, teklifler) çekmecesi; `tahsilat.gor` ile görülebilsin |
| O10 | ORTA | yetki | Rol özelliği `yalniz_ofis` | §5.9/5 | Finans yöneticisi de ofis dışından giremez | FINANS_YONETICI `yalniz_ofis=false`. Ayrıca `ofis_ag_listesi` boş olduğu için kısıt kapalı | YALNIZ_OFIS_ROLLERI'ne FINANS_YONETICI (karar teyidiyle). Canlıya geçiş listesine "ofis ağı ayarı girilecek" |
| O11 | ORTA | akış/UX | Satış destek iş bulma | Teknisyen TEKLIF_SUNULACAK girdi | Satış destek "teklif hazırlanacak" listesini menüden ya da bildirimle görür | Bildirim yok. Menüdeki "Sonuçlanan Arıza İşleri" (`durum_grubu=COZULDU`) teklif bekleyenleri GÖSTERMİYOR (BEKLEMEDE). Tek yol Ana Panel "bekleyen aksiyonlar → Satış" satırı | KPI `teklif_hazirlanacak` (TEKLIF beklemesi ∧ bağlı teklif yok) + menü yaprağı. Satış destek için bildirim |
| O12 | ORTA | yetki/veri | SATIS kapsamı (`quotes.py:504`) | t_satis_guv | Kendi müşterilerinin servis tekliflerini ve sonucunu görür, kendi birim fiyatını görür | Müşteri sahipliği yok (0 kayıt). Satış destek'in açtığı teklif görünmüyor (`owner_id`). Görmediği müşteriye (`/hesaplar/19` 404) teklif açabiliyor | KENDI_MUSTERILERI teklif kapsamı `owner_id = user` YA DA `account.owner_id = user` olsun. Teklif açılışında müşteri kapsamı denetlensin |
| D1 | DÜŞÜK | UX | Menü "Satış ve Müşteri" (`menu.ts`, 20:14'te değişmiş) | t_sdestek_guv, t_satis_guv, 20:32'de giriş | Bölüm görünür | Menüde "Satış ve Müşteri" grubu çıkmadı; Teklifler'e yalnız adresle ulaşıldı | Diğer ajanın değişikliği yüklendikten sonra yeniden doğrulayın |
| D2 | DÜŞÜK | UX | Ana Panel SLA | ELEKTRONİK | SLA hedefi yoksa "tanımsız" | "SLA riski 0" gösteriliyor; 61 açık işin hiçbirinde hedef yok | Hedefi olmayan iş sayısını göster ("SLA tanımsız: 61") |
| D3 | DÜŞÜK | UX | Ana Panel | Bölüm iş yükü ile Açık İş KPI | Tek "açık" tanımı | 75 (PB dahil) ve 58 (PB hariç) | Grafikte PB'yi ayrı renkle göster ya da tanımı yaz |
| D4 | DÜŞÜK | UX | Ana Panel KPI seti | Üst yönetim | Teklif dönüşümü, fatura devri bekleyen, tamamlanan KPI kartı | Yalnız raporlarda / aksiyon satırında. Teklif dönüşümü birim zorunlu, şirket toplamı yok | KPI kartları ekle; `teklif-donusumu` birimsiz = etkin şirket toplamı |
| D5 | DÜŞÜK | UX | Giriş sonrası şirket | t_finans_yon, t_yonetim | Son kullanılan / ilk birimli şirket | MOBİLİTE açılıyor; teknik servis ekranları boş | Son seçilen şirketi hatırla |
| D6 | DÜŞÜK | veri (sayı = liste) | Ana Panel aksiyon "Depo" | t_depo_guv | Açık parça talebi sayısı | "Depo 3" (MALZEME beklemesi), açık talep 2 (000053 talepsiz MALZEME) | Aksiyon açıklamasını "malzeme bekleyen iş" yap ya da talep sayısıyla eşitle |
| D7 | DÜŞÜK | yetki | Fatura devri işaretleme | §1 KARAR "fatura devri onayı finans yöneticisinde" | Uzman işaretler, yönetici onaylar (ya da kararla tek adım) | Uzman tek başına işaretliyor ve geri alıyor (gerekçeli, denetimli). G1.9 ile uyumlu sayılabilir | Kararı netleştir; gerekirse geri almayı yalnız yöneticiye ver |

## 3. İyi çalışanlar
- **Teklif makinesi:** öz-onay yasağı (403), nedensiz red 400, gönderimden önce onay zorunlu.
- **Teklif ve gelir:** KDV hariç kabul tutarı işin gelirine aktarılıyor; dönüşüm raporu doğru (%75, 112.200 ₺).
- **Fatura devri:** toplu işaret bütün olarak 409 dönüyor (sorunlu kimlik yazılı); geri alma gerekçe istiyor; gelir
  kilidi teklif iptalini engelliyor.
- **Şirket ayrımı:** fatura devri, Ana Panel ve teklifler üç şirkette doğru ayrılıyor; HABERLESME/GÜVENLİK kalite
  listeleri ayrı.
- **Görevler ayrılığı:** kalite onayında doğru (şef kendi işine 403); eski `version` 409.
- **Sayı = liste:** Ana Panel KPI'ları ve birim özeti listelerle birebir.
- **Ofis kısıtı:** liste doluyken açık oturumu da kesiyor.
- **Depo:** parça çıkışı talebi kapatıp beklemeyi bitiriyor.
- **Atölye:** kabul edilmiş teklif onay yerine sayılıyor; süre eksikse teslimde onay isteniyor.

## 4. Uçtan uca zincir

"Tık" sayısı masaüstü arayüzdeki en kısa yoldur; giriş dahil değil.

| İş | Talep → plan | Saha → sonuç | Teklif / onay | Kalite onayı | Fatura devri | Kopukluk |
|---|---|---|---|---|---|---|
| **SRV-202611-000080** (konsolosluk KMD) | Talep listesinden içe aktarım → şef planı (2. aşama) | Şef: TEKLIF_SUNULACAK → BEKLEMEDE(TEKLIF) | **Satış destek:** bildirim yok; Ana Panel → "Satış" aksiyon satırı (1) → iş çekmecesi "Teklif hazırla" (2) → kalem + kaydet (3–4) → onaya gönder (5). **Yönetici:** Ana Panelde teklif onayı yok; Teklifler → "Onay bekliyor" (2–3) → onayla. **Satış destek:** gönderildi (2) → kabul (2). **Kabulden sonra iş İŞLEMDE'ye düştü; plan bekleyende yok (Y1).** Yönetici işi bulup elle yeni plan yazdı; durum İŞLEMDE kaldı | Teknisyen Benim İşlerim'de gördü, süre ve sonuç girdi. t_yon_guv: Ana Panel "Bekleyen onaylar" (1) → liste → iş (2) → Kalite onayı → Onayla (4) + Kapat (2) | t_finans_yon: Raporlar → Fatura Devri (2) → seç → işaretle (2). Excel var, Logo yok | Teklif kabul → planlama **KOPUK (YÜKSEK)**. Satış destek ve yönetici bildirimsiz |
| **SRV-202611-000064** (MALTEPE X-Ray) | Aynı | Şef: TEKLIF_SUNULACAK | TKF2026-00001 KABUL → İŞLEMDE (Y1) | Şef sonucu ile TAMAMLANDI; **kalite ve kapanış yok** | **Kalite onayı olmadan bekleyen listesinde (94.000 ₺)** | Kalite → fatura kapısı yok **(Y3, YÜKSEK)** |
| **SRV-202611-000140 / AT-202611-000002** (klavye) | Atölye kabulü | Teşhis → ONAY_BEKLİYOR (MÜŞTERİ_ONAYI) | Teklif TKF2026-00007: beklemeye bağlanamadı (uyarı). Kabulden sonra usta bildirim almadı; atölye listesinden kendisi baktı | Onarım → test → teslim → TAMAMLANDI (süre EKSİK, uyarısız kalite onayı O2) | Bekleyen listesinde (3.200 ₺) | Teklif → atölye **zayıf (O1)** |
| **SRV-202611-000065** (MALTEPE, red) | Aynı | TEKLIF_SUNULACAK | TKF2026-00003 RED → İŞLEMDE | Kimsenin kuyruğunda değil; panelde "sahada" | — | Red → kapanış **KOPUK (Y2)** |
| **PB-202601-000001** (sözleşmeli bakım) | Dönem üretimi → tayin | Bakım formu → TAMAMLANDI | — | Kalite kuyruğunda (KPI'da sayılmıyor, O4) | **Hiç düşmüyor** (ücret yok, SOZLESME geliri yazılmıyor) | Bakım → fatura **KOPUK (Y4)** |
| **SRV-202611-000093 / 000105** (parça) | Plan → saha | Parça talebi → BEKLEMEDE(MALZEME) | Depo: Yedek Parça "Parça Talepleri" (2) → çıkış ya da transfer. Teknisyen: araç deposundan çıkış | — | — | Parça geldi → yeniden plan **KOPUK (O5)** |

## 5. Açılan / işlenen kayıtlar
- **Teklifler:** TKF2026-00001 (000064, KABUL), 00002 (000080, KABUL), 00003 (000065, RED), 00004 (000066,
  GONDERILDI), 00005 (000090, ONAY_BEKLIYOR), 00006 (satış denemesi, İPTAL), 00007 (000140 atölye, KABUL).
- **Planlar:** 000080 ikinci ziyaret planı; 000096 yeniden planlandı (PLANLANDI).
- **Kalite onayı (t_yon_guv):** 000036, 080, 087, 097, 098, 099, 100, 101, 102, 107, 108, 110, 140.
- **Kapanış:** 000036, 080, 108 (t_yon_guv); 000068 (t_sef_guv, kalitesiz).
- **Sonuç girişi:**
  - 000080 COZULDU (t_tek_guv1, süre sonradan eklendi → TAM).
  - 000064 COZULDU (t_sef_guv).
  - 000140 atölye TESLİM EDİLDİ.
- **Fatura devri:** 000080 iletildi (uzman işaretledi → geri aldı → yönetici yeniden işaretledi). 000064 ve 000140
  bekliyor.
- **Stok:**
  - RT3-YP-05 girişleri (belge RT4-IRS-1, 2 × 2 adet).
  - 000093'e depodan çıkış.
  - RT3-GUV → RT3-ARC-G1 transferi.
  - 000105'e araç deposundan çıkış.
- **Ayar:** `ofis_ag_listesi` geçici olarak değiştirildi, `[]`'a geri alındı.
