# Rol testi 3. aşama: Teknisyen, Saha Sorumlusu ve Atölye (2026-11-04)

Ortam yereldi: API 127.0.0.1:8000, web 127.0.0.1:5173. Kod değiştirilmedi, canlı sisteme dokunulmadı. Raporda kişi adı,
parola ve plaka yok; kişiler test kullanıcı adlarıyla anılıyor.

Betikler, kayıtlar (`log_*.json`) ve ekran görüntüleri (`m01…m17.png`, 375 px) şu klasörde:
`C:\Users\skilic\AppData\Local\Temp\claude\ff375d97b5e42a31\c9ec6dae-0467-416d-a7b6-190f1738d382\scratchpad\rol_testi\saha\`

4. aşamanın girdisi `analiz/rol_testi/saha_sonuclari.json`. Bu dosyada tamamlanan, teklif bekleyen, uygunsuzluk,
malzeme bekleyen, işlemdeki ve atölyedeki işler var. Her iş için şunlar yazılı: durum, bekleme nedeni, sonuç, bağlı
iş, kullanılan parça, parça talebi, kişi-saat ve süre kaydının var/eksik/kısmi olduğu.

## 1. Ne yaptım

### 1.0 Ön koşul verisi
Hiç servis deposu ve yedek parça yoktu. Parça senaryosu için şunları açtım:
- **Depolar** (admin ile, `sistem.ayar` gerekiyor): RT3-GUV (id 1), t_tek_guv1'in araç deposu RT3-ARC-G1 (id 2) ve
  t_tek_guv2'nin araç deposu RT3-ARC-G2 (id 3).
- **Parça kartları** (t_depo_guv ile): RT3-YP-01…05. RT3-YP-05 "jeneratör" bilerek stoksuz bırakıldı.
- **Stok**: maliyetli giriş yapıldı (RT3-IRS-1), sonra araç depolarına transfer edildi.

PB işleri ekipsizdi. Bu yüzden t_sef_guv PB-202601-000001, 000003, 000004 ve 000013'ü teknisyenlere tayin etti.

### 1.1 Hedefi TAMAMLANDI olan işler
Her iş ekipteki kişinin kendi kullanıcısıyla işlendi. Adımlar:

1. **Süre kaydı:** her ekip üyesi için YOL (ziyaretin ilk işinde 30 dk) ve SAHA girildi. Çok cihazlı ziyaretlerde
   süre cihazlara bölündü.
2. **Geriye dönük kayıt sınırı:** teknisyen 2 günden eski kaydı giremiyor (`zaman_manuel_geri_gun=2` → 400 "şefinize
   başvurun"). 26–31 Ekim işlerini t_sef_guv "başkası adına" girdi. 2 Kasım ve sonrasındaki işleri teknisyen
   kendisi girdi.
3. **Durum ve sonuç:** iş İŞLEMDE'ye alındı, sonra sonuç girildi. Sonucu ekibin sorumlusu (teknisyen ya da şef)
   girdi. Arıza işlerinde arıza nedeni seçildi; bazı işlerde sahada görülen seri girildi.
4. **Müşteri onayı ve ekler:** imza (PNG ek + onay), sözlü onay ya da "alınamadı + neden" dönüşümlü girildi. Bazı
   işlere "servis sonrası" fotoğrafı eklendi.
5. **Toplu imza:** KİPA ziyaret 3'ün 6 cihazına (000027–000032) t_saha_guv tek imzayla ziyaret onayı verdi (201).
6. **Parça kullanımı:** 7 kurulum işinde teknisyen kendi araç deposundan 1 adet RT3-YP-03 (UPS akü) çıkışı yaptı:
   000061, 063, 069, 072, 098, 101, 107.

Sonuçlar:

| Sonuç | Adet | İşler |
|---|---|---|
| TAMAMLANDI (COZULDU) | 45 | 44 liste işi + PB-202601-000001 (imzalı bakım formu). Ayrıntı `saha_sonuclari.json`'da |
| TEKLIF_SUNULACAK → BEKLEMEDE (TEKLIF) | 5 | SRV-202611-000064, 065, 066 (MALTEPE PARK), 000080 (AVUSTURYA BAŞKONSOLOSLUĞU), 000090 (İSTANBUL HAVALİMANI GÖÇ İDARESİ) |
| Parça bekleniyor → BEKLEMEDE (MALZEME) | 2 | SRV-202611-000093 (MALTEPE PARK, arıza) ve 000105 (TCDD 2. Bölge, kurulum). Ayrıntı aşağıda |
| PB UYGUNSUZLUK_VAR → bağlı ARIZA işi | 3 | Ayrıntı aşağıda |
| Süre kaydı girmeden kapatma | 3 | Ayrıntı aşağıda |

**Parça bekleyen işler:** 000093 ve 000105'te RT3-YP-05 için `isi_beklet` ile parça talebi açıldı. İkisi de
BEKLEMEDE (MALZEME) durumuna geçti.

**PB uygunsuzlukları:**

| PB işi | Uygunsuz madde | Bağlı arıza işi |
|---|---|---|
| PB-202601-000003 | Acil stop kırık | SRV-202611-000135 |
| PB-202601-000004 | Görüntüde leke / atlama | SRV-202611-000136 |
| PB-202601-000013 | Konveyör bandı yırtık | SRV-202611-000137 |

- Üç PB işi de BEKLEMEDE (BAKIM_UYGUNSUZLUK) durumunda.
- Bağlı arıza işleri MÜŞTERİ TALEBİ durumunda.
- Arıza işlerini şef açtı. Teknisyen denediğinde 403 aldı (`bakim.onayla`).

**Süre kaydı girmeden kapatma:**
- **000036 ve 000110:** önce 409 "Süre kaydı eksik… onaylayarak kapatın" döndü. Onayla kapandılar. Kişi-saat **null**,
  durum "EKSIK" (0 değil). Teknisyen kartında "Süre kaydı eksik" etiketi görünüyor.
- **000087 (3 kişilik ekip, yalnız 2 kişi süre girdi):** 409 eksik kişiyi adıyla gösterdi. Onaylı kapanınca durum
  KISMI oldu (bkz. B4).

### 1.2 Hedefi İŞLEMDE olan işler: canlı sayaç
**SRV-202611-000114 (t_tek_hab):**
1. Yola Çıktım → iş YOLA ÇIKILDI.
2. İkinci sayaç denemesi → 409 "Önce açık sayacı bitirin".
3. Sahaya Vardım → iş SAHADA.
4. Mola → Devam → Bitir → iş İŞLEMDE.

Sonuç: kişi-saat 3 dk, mola 1 dk ayrı gösterildi ve toplama **dahil edilmedi**.

**SRV-202611-000081…086 (İSKİ, 6 cihaz, t_sef_guv):**
1. Yola Çıktım, ardından Sahaya Vardım.
2. Sayaç `hedef_is_id` ile sıradaki cihaza taşındı: 082 → 083 → 084 → 085 → 086.
3. Bitir, sonra 6 iş de İŞLEMDE'ye alındı.

### 1.3 Atölye (t_atolye_guv)

| Kayıt | Senaryo | Akış | Son durum |
|---|---|---|---|
| **AT-202611-000001 / SRV-202611-000139** (ZONGULDAK EREN ENERJİ) | §7.6 X-Ray PC kasası, kargoyla geldi | Kabul (KARGO, aksesuar) → teşhis (arıza nedeni, onarılabilir) → "onay gerekmez" + gerekçe → ONARIMDA → test GEÇTİ → TESLİME HAZIR → KARGOYA VERİLDİ (takip no olmadan 400, ile 200). Saha işi SRV-202611-000024'e DEVAM ilişkisi kuruldu | Kargoya verildi |
| **AT-202611-000002 / SRV-202611-000140** (ESAN BALYA ECZACIBAŞI) | §7.6 müşterinin klavyesi | Kabul (ELDEN) → teşhis. Arıza nedeni girilmeden ONAY_BEKLİYOR'a geçiş 400 verdi, nedenle 200 | ONAY BEKLİYOR; servis işi "müşteri onayı bekleniyor" beklemesinde (4. aşama teklif hazırlayacak) |

### 1.4 Yetki sınırları
`log_yetki.json`: 50 denemenin hepsi beklendiği gibi sonuçlandı.

- **Ekip dışı iş (t_tek_guv2 → 000092):** detay, iş kartı, sayaç, elle süre, sonuç, onay, ek, parça ve durum
  denemelerinin hepsi 404. Liste de işi göstermiyor.
- **Başka teknisyenin araç deposu:** 404. Başkası adına süre kaydı: 403.
- **t_tek_hab (Haberleşme):** Güvenlik işine 404. ELEKTRONİK şirketine geçiş 403 (SIRKET_DISI). Liste yalnız
  HABERLESME. Depo görmüyor. Atölyeye 403.
- **t_saha_guv (saha sorumlusu):** tayin, toplu tayin ve plan 403 (`servis.planla`). Kalite onayı, kapatma ve maliyet
  403. Sonuç 403 (`servis.tamamla`). Başkası adına süre 403. Tayin edilmediği işe sayaç 400.
- **Teknisyen fiyat/maliyet:** maliyet ucu, teklifler, bakım sözleşmeleri, kalite onayı ve kapatma 403. Şu
  yanıtların hiçbirinde maliyet, fiyat, tutar ya da ücret anahtarı yok: iş detayı, iş kartı, iş parçaları, stok,
  hareketler, Benim İşlerim.
- **Kapalı iş ve kilit:** kapalı işe ek 409, sayaç 409, ikinci sonuç 409. Eski `version` ile sayaç bitirme 409.
  Çakışan elle kayıt 409. İleri tarihli kayıt 400.

### 1.5 Arayüz, 375 px (Playwright)
**Benim İşlerim:**
- 3,4 sn'de açılıyor, yatay taşma yok.
- Gruplar: Geciken 6, Bugün 1, Yarın 6, Plansız 2. "Kayıt Sayısı 15", grup toplamlarıyla tutarlı (`m02`).

**İş kartı (`m03`):**
- Düğmeler: Yola Çıktım, Sahaya Vardım, Diğer faaliyet, Haritada aç, telefon, Elle süre gir, Sonuç Gir, Yükle.
- Fiyat yok.

**Yanlış başlatma denemesi:** "Yola Çıktım" ardından "Yanlış başlattım" basıldı (`m04`–`m06`). Bölüm geri alındı ama
iş durumu geri dönmedi (bkz. B1).

**Çevrimdışı (`m07`):**
- Sayaç düğmeleri kalkıyor ve "Bağlantı yok — süreyi sonra elle girin" uyarısı çıkıyor.
- Sayfa geçişi tarayıcı hata sayfasına düşüyor; PWA Faz B'de bekleniyor.

**Sonuç girme (`m09`, `m10`):** "Sonuç Gir" masaüstü Servis İşleri listesini ve ayrıntı penceresini açıyor.
- **Tıklama sayısı:** liste → kart (1) → Sonuç Gir (2) → "Sonuç gir" (3) → 3 zorunlu alan → Kaydet (4).
- **Zorunlu alanlar:** sonuç, çözüm kanalı, yapılan işlem (gereksiz zorunlu alan yok).
- **İmza:** ayrı "Müşteri onayı" düğmesinde. **Parça:** "Parçalar" sekmesinde.

**Diğer roller:**
- Saha sorumlusunun Benim İşlerim ekranı açılıyor (`m14`).
- Atölye listesi ve ayrıntısı 375 px'te taşmıyor (`m16`, `m17`).

## 2. Bulgular

| No | Önem | Tür | Ekran / uç | Yeniden üretme | Beklenen | Gerçekleşen | Önerilen düzeltme |
|---|---|---|---|---|---|---|---|
| B1 | YÜKSEK | akış/veri | Mobil iş kartı "Yanlış başlattım"; `POST /isler/{id}/zaman/bolumler/{b}/geri-al` | t_tek_guv1, SRV-202611-000096 (PLANLANDI): Yola Çıktım → Yanlış başlattım | Bölüm geri alınır, iş PLANLANDI'ya döner, süre "beklenmiyor" kalır | Bölüm GERI_ALINDI ama iş **YOLA_CIKILDI'da kaldı**. Süre özeti "EKSIK", "Kaydı eksik: T1" gösteriyor. İş saha grubunda ve süre eksik KPI'sına aday | `services/teknik_servis/zaman.py` `geri_al`: geri alınan bölüm işi sayaçla ilerletmişse ve başka geçerli bölüm yoksa `durum_degistir(YOLA_CIKILDI→PLANLANDI, kaynak='sayac')` çalışsın (durum makinesi bu kenarı zaten "yanlış basış" için tutuyor, `statemachine.py:220`). 000096 şu an YOLA_CIKILDI'da; düzeltilmeli |
| B2 | YÜKSEK | akış/veri | Bakım formu `api/bakim.py:153` (`_pb`) | Talep listesinden gelen PLANSIZ_BAKIM işinde (ör. 000027) bakım formunu aç | Liste bakımlarında da (40+ iş) X-Ray/KMD kontrol listesi, uygunsuzluk ve bağlı arıza akışı | Form yalnız `tur=='PB'` (sözleşme dönemi) işlerde açılıyor; PLANSIZ_BAKIM 404 "planlı bakım işi değil". Teknisyen bakımı serbest metinle kapatıyor; UYGUNSUZLUK_VAR ve madde bazlı kayıt yok | Bakım formunu ekipmanı olan PLANSIZ_BAKIM işlerine de aç (şablon `equipment_type`'tan), ya da liste bakımlarını PB'ye dönüştür. Mobil kartta "Bakım Formu" düğmesi `bakim_formu` bayrağına bağlı |
| B3 | YÜKSEK | veri | Bakım formu (§4.2) | PB-202601-000003 formunu doldur | Jeneratör kV/mA, penetrasyon (mm), çözünürlük (AWG), doz (yan panel/tünel), AC voltaj sayısal alanları; acil stop kırık için KRİTİK işareti | Ölçüm alanı yok, `technician_note`'a serbest metin yazıldı. Uygunsuzlukta önem/KRİTİK alanı yok. Açılan bağlı arıza işi SRV-202611-000135 NORMAL öncelikli. Konusu madde etiketi oluyor ("Bakım bulgusu: Acil durdurma sistemi … kontrol edildi"); bulgunun kendisi konuda yok | `MaintenanceForm`'a ölçüm satırları (şablona bağlı, doz zorunlu). `MaintenanceNonconformity`'ye `onem` (KRİTİK→arıza işi ACIL). `bakim_formu.py:812` konuyu `description`'dan üret |
| B4 | ORTA | veri (sayı = liste) | Zaman Takibi KPI "süre kaydı eksik" `GET /zaman/isler?kpi=sure_eksik` | 3 kişilik ekipte 1 teknisyen süre girmeden kapat (SRV-202611-000087) | İş detayı KISMI dediğine ve kapanış 409 "Süre kaydı eksik" verdiğine göre KPI listesinde de olmalı (tanım: EKSIK ∪ KISMI) | Liste yalnız 000036 ve 000110'u veriyor (`X-Toplam-Kayit: 2`). 000087 yok | `zaman.py:1018` `sure_eksik_ifadesi` / `_eksik_teknisyen_var` ile Python `sure_durumu_hesapla` arasındaki eşitlik testine bu durum eklenmeli (SEF + 2 TEKNISYEN, birinin bölümü yok, bölümleri şef adına girilmiş) |
| B5 | ORTA | yetki/akış | Atölye `POST /atolye/{id}/ata`, `POST /isler/{id}/zaman` | t_atolye_guv kendi kaydına kendini tayin etsin, ATÖLYE süresi girsin | Atölye ustası kendi işine tayinli olur, ATÖLYE/TEST süresi yazar | 400 "saha personeli değil; tayin edilemez". Süre 400 "işe tayin edilmiş değil". Atölye işleri hep "süre eksik" kapanacak | Personel kartında ATOLYE rolüne saha rolü (TEKNISYEN) verilmeli, ya da atölye işinde tayin kuralı ATOLYE rolünü kabul etmeli (`services/teknik_servis/atama.py`). Ekran uyarısı da olsun |
| B6 | ORTA | UX | Mobil iş kartı `ServisIsKartiMobil.tsx:226-231` | 375 px'te iş kartında "Sonuç Gir" | Telefonda tek sayfa: sonuç, imza (canvas), parça çıkışı | Masaüstü Servis İşleri listesi (39 satır tablo) ve üstünde ayrıntı penceresi açılıyor. İmza "Müşteri onayı" düğmesinde, parça "Parçalar" sekmesinde. Mobil kartta parça ve imza yok. En az 4 dokunuş + sekme gezintisi | Mobil kartta "Sonuç gir" çekmecesi; "Parça kullan" (araç deposu varsayılan) ve "Müşteri imzası" düğmeleri karta taşınsın |
| B7 | ORTA | akış | Tayin (2. aşama) ve sonuç | SRV-202611-000104 yalnız t_saha_guv'a tayinli | Ekipte sonuç girebilecek en az bir kişi | Saha sorumlusu sonuç giremiyor (403, doğru). Ekipte başka kimse yok, iş tamamlanamaz. Tayin ekranı uyarmıyor | Tayinde "ekipte `servis.tamamla` sahibi yok" uyarısı (`atama.ata` uyarı toplayıcısı) |
| B8 | DÜŞÜK | UX/akış | `POST /isler/{id}/bagli-yeni-is` | t_tek_guv1, TAMAMLANDI 000041'den bağlı iş açtı → SRV-202611-000138 | Açan kişi işi görür; ilişki türü seçilebilir (BAKIM_BULGUSU) | 201, ama hemen ardından `GET /isler/138` 404 (tayinsiz, KENDI_ISLERI kapsamı). İlişki türü boş, `BagliIsIn`'de `iliski_turu` yok | Açan teknisyene geçici görme hakkı ya da "Şefe iletildi" mesajı. `BagliIsIn.iliski_turu` (TEKRAR_ARIZA/BAKIM_BULGUSU) |
| B9 | DÜŞÜK | UX | Servis İşleri listesi, Benim İşlerim | 375 px'te PB-202601-000003 satırı | Türkçe durum adı | Liste "ASKIDA-BAKIM_UYGUNSUZLUK" diye ham kod gösteriyor. Aynı BEKLEMEDE durumu Benim İşlerim'de "İŞLEM-ARA VERİLDİ", listede "ASKIDA" (iki ad) | Bekleme nedeni adı katalogdan gelsin; tek terim |
| B10 | DÜŞÜK | UX | Mobil iş kartı | 375 px dokunma hedefleri | ≥ 44 px | Elle süre gir 24 px, Yükle 24 px, "devamı" 15 px, geri düğmesi 32 px. 12 px altı 10 metin öğesi | `size="small"` yerine `minHeight: 44` (`ServisIsKartiMobil.tsx:211`, `EkYukleyici`) |
| B11 | DÜŞÜK | yetki/UX | `PATCH /atolye/{id}` | t_atolye_guv (maliyet.gor yok) `repair_amount: 1500` gönderdi | 403 (bakım ücretinde olduğu gibi) ya da açık uyarı | 200 döndü, tutar sessizce yazılmadı (null) | `api/atolye.py` patch: maliyet alanı izinsiz gönderilirse 403, `bakim._ucret_yetkisi` gibi |
| B12 | DÜŞÜK | UX | Atölye kabul formu | Güvenlik cihazı (PC kasası, klavye) kabul et | Güvenlik markaları / serbest marka | Marka listesi yalnız telsiz markaları; "DIGER + marka adı" zorunlu. `KabulOrtakIn.birim` varsayılanı HABERLESME | Marka listesi birime göre; varsayılan birim kullanıcının birimi |
| B13 | DÜŞÜK | UX | Mobil iş kartı (kapalı iş) | TAMAMLANDI 000036 kartı | Kapalı işte yalnız görüntüleme | "Elle süre gir" ve "Sonuç Gir" düğmeleri görünüyor (sayaç doğru biçimde kapalı) | Kapalı işte düğmeleri gizle ya da "eksik süreyi tamamla" diye adlandır |

Not: geçmiş tarihli işlerde teknisyenin süre girememesi (2 gün sınırı) ayarın beklenen davranışı. Mesaj açık ("şefinize
başvurun"). 26–31 Ekim kayıtlarının hepsini şef girmek zorunda kaldı, bu da şefe ciddi iş yükü getiriyor.

## 3. İyi çalışanlar

**Kapsam ve yetki:**
- Teknisyen ekibinde olmadığı işi hiçbir uçtan göremiyor ve yazamıyor (404, varlık sızmıyor).
- Şirket ayrımı ve Haberleşme–Güvenlik ayrımı sağlam.
- Teknisyen yanıtlarında maliyet anahtarı hiç yok.
- Saha sorumlusu tayin, kalite, kapatma ve sonuç işlemlerinden doğru biçimde kesik.
- Ziyaret toplu imzasını saha sorumlusu verebiliyor.

**Süre kuralları:**
- Süre kaydı yoksa "EKSIK" ve kişi-saat null (0 değil).
- Kapanışta 409 ve onaylı kapanış çalışıyor.
- Mola kişi-saate dahil değil, ayrı gösteriliyor.

**Sayaç:**
- Tek açık sayaç kuralı çalışıyor; ikinci sayaç 409.
- Sayaç sıradaki cihaza taşınabiliyor (`hedef_is_id`).
- İyimser kilit ve çakışma mesajları okunur.

**Sonuç ve bekleme akışları:**
- TEKLIF_SUNULACAK işi otomatik TEKLIF beklemesine alıyor.
- Parça talebi `isi_beklet` ile MALZEME beklemesi açıyor.

**PB bakım formu:**
- Müşteri onayı zorunlu.
- Uygunsuz maddeye not zorunlu.
- Uygunsuzlukta iş beklemeye düşüyor ve arıza işi tek düğmeyle (şef) BAKIM_BULGUSU bağıyla açılıyor.

**Atölye:**
- Durum makinesi tutarlı; teşhis eksikse onaya geçmiyor.
- Kargoda firma ve takip no zorunlu.
- Atölye kaydı servis işini doğru beklemeye alıyor.

**Mobil:**
- 375 px'te yatay taşma yok.
- Çevrimdışıyken sayaç düğmeleri kilitleniyor ve açık uyarı veriliyor.

**Kayıt özeti:**
- **İşlenen:** SRV-202611-000027…036, 038–047, 061–073, 079–093, 097–108, 110, 114, 121, 126 (ayrıntı JSON'da) ve
  PB-202601-000001, 000003, 000004, 000013.
- **Açılan:** SRV-202611-000135, 136, 137 (PB bulgusu arıza işleri), 000138 (bağlı iş), 000139 ve 000140 (atölye;
  AT-202611-000001, 000002).
- **Yan etki:** SRV-202611-000096 B1 yüzünden YOLA_CIKILDI'da kaldı.
