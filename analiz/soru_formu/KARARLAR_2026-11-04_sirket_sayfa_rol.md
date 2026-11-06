# Kararlar — 2026-11-04: şirket ayrımı, sayfa yapısı, kullanıcı rolleri, ana panel, UX

Kaynak: kullanıcının 2026-11-04 mesajı + 4 görsel (Logo CRM ekranı, el yazısı "Sayfa Yapısı",
el yazısı "Kullanıcı Rolleri", örnek "master dashboard"). Kullanıcı soru sorulmamasını istediği için
(2026-10-21) belirsiz noktalar aşağıda **varsayım** olarak işaretlendi; hepsi yönetici ekranından
değiştirilebilir veya tek satırlık kod sabitidir.

## 1. Şirket ayrımı (DENGE TELEKOM / DENGE ELEKTRONİK / DENGE MOBİLİTE)

- Üç şirket tek sistemi kullanır; üst çubukta **şirket seçici** vardır (Logo CRM'deki "2-DENGE TELEKOM" gibi).
- Kullanıcı yalnız üyesi olduğu şirketleri seçebilir; tek şirketi varsa seçici sabit etiket olur.
  ADMIN bütün şirketleri görür. Etkin şirket **oturumda (sunucuda)** tutulur; her istek onu kullanır.
- **Ayrım anahtarı birimdir:** teknik servis zaten her kaydı birime bağlar ve kapsamı birimle süzer
  (`services/teknik_servis/kapsam.py`). Her birim bir şirkete aittir (`birim_sirketleri` tablosu);
  kullanıcının görebileceği birimler = (kapsamına göre birimleri) ∩ (etkin şirketin birimleri).
  TUMU kapsamlı kullanıcı (yönetici, finans) da yalnız etkin şirketin birimlerini görür.
  Böylece sayı = liste kuralı ve fail-closed davranışı korunur, her tabloya sütun eklenmez.
- **Varsayılan birim → şirket eşlemesi (varsayım, Logo CRM ekranından: Telekom servis kayıtları Hytera telsiz):**
  - DENGE TELEKOM: HABERLESME, POC
  - DENGE ELEKTRONİK: GUVENLIK, BARIYER (yeni birim: Set Bariyer)
  - DENGE MOBİLİTE: MOBILITE, ARAC_TAKIP
- **Mobilite modülü** (hesaplar/cihazlar/hatlar/hak ediş… canlı ekranlar) yalnız etkin şirket DENGE MOBİLİTE iken
  görünür ve erişilir. Modülün iş kuralları değişmez (G2.5, D8.6); yalnız yönlendirici düzeyinde şirket kapısı eklenir.
- **Müşteri/cari kartları grup ortaktır** (aynı müşteri birden çok şirketten hizmet alır, ör. REC); işlem kayıtları
  (servis işi, bakım, ekipman, kiralama, stok) birim üzerinden şirkete bağlıdır. Ortak cari, Logo entegrasyonunda
  (Faz D) şirket bazlı cari koduna eşlenir.
- Birimsiz ortak kayıtlar (ör. ortak depo) her şirkette görünür (mevcut kapsam kuralı).

## 2. Sayfa yapısı (sol menü, Logo CRM kurgusu)

Sol tarafta ana bölüm başlıkları; başlığa tıklanınca alt bölümler aşağı açılır (akordeon). Menü etkin şirkete ve
izinlere göre süzülür. Fiori liste ekranları (kategori şeridi, durum çubuğu, tablo) korunur; Launchpad ana sayfa
olmaktan çıkar, yerini **Ana Panel** alır. Üst çubuk: menü daralt, logo, şirket seçici, genel arama, "Hızlı oluştur",
bildirim, kullanıcı.

El yazısı sayfa ağacı (birim → alt bölüm → iş türü):

- **Güvenlik** → Teknik Servis (Kurulum, Arıza, Bakım) · Satış (Bakım/Arıza Tespit, Ürün) · Atölye (Bakım)
- **Haberleşme** → Teknik Servis: Laboratuvar (Arıza Onarım; yedek parça stok kurgusu), Saha (Keşif, Arıza, Bakım) ·
  Satış (Ürün, Bakım, Arıza Tespit — satış destek: Ebrar Hanım) · Frekans (Setra) · POC
- **POC**
- **Mobilite** (mevcut mobilite modülü)
- **Set Bariyer** → Kurulum, Toplama, Taşıma (yeni iş türü TASIMA)
- **Kiralama** (bütün birimler)
- Ortak: Ana Panel, Benim İşlerim, Planlama, Planlı Bakım, Onaylar/Takip, Depo/Yedek Parça, Raporlar, İK, Sistem

Menü öğeleri mevcut ekranları süzgeçle açar (ör. `/servis-isleri?birim=GUVENLIK&tur=KURULUM`). Henüz ekranı olmayan
dallar (Satış → Ürün/Bakım/Arıza Tespit satış akışı, Frekans/Setra) Faz B/C'de yapılır; o zamana kadar menüde
gösterilmez (boş ekran göstermemek için).

## 3. Kullanıcı rolleri (el yazısı)

| El yazısı | Sistem rolü | Not |
|---|---|---|
| Admin | ADMIN | değişmez |
| Haberleşme/Güvenlik — Yönetici | SERVIS_YONETICI | birim üyeliğiyle bölüm ayrılır |
| — Takım Lideri / Şef | SERVIS_SEF | |
| — Teknisyen | SERVIS_TEKNISYEN | |
| — Operasyon Uzmanı | SERVIS_OPERASYON | |
| — Saha Sorumlusu | **SAHA_SORUMLUSU (yeni)** | sahadaki işleri açar, takip eder, kalite onayı yok; tayin yok |
| — Satış | SATIS | |
| — Satış Destek | **SATIS_DESTEK (yeni)** | teklif/sipariş hazırlar, servis kayıtlarını görür, arıza tespit sonucu okur |
| Finans — Yönetici | **FINANS_YONETICI (yeni)** | maliyet/fiyat görür, fatura devri onayı |
| Finans — Uzman | MUHASEBE_DESTEK (ad: "Finans Uzmanı") | yalnız ofis kısıtı korunur |
| Depo — Uzman | SERVIS_DEPO | |
| G-Kart | — | anlamı belirsiz; açıklama bekleniyor (KARARLAR §6'ya eklendi) |

"Haberleşme / Güvenlik" ayrımı ayrı rol kodlarıyla değil, aynı rol + **birim üyeliğiyle** yapılır (mevcut kalıp);
rol sayısı azalır, yetki tek yerde kalır (G1.9).

## 4. Ana Panel (örnek master dashboard)

Üstte süzgeçler (bölüm, durum, şef, personel, lokasyon, tarih aralığı); KPI kartları (açık iş emri, bu ay planlı bakım,
acil arıza, POC açık talep, SLA riski, sahadaki ekip, askıdaki kayıt, bekleyen onay) önceki döneme göre değişimle;
birim bazında canlı operasyon özeti (açık / sahada / atölyede / tamamlanan + ilerleme); "Aktif işler / kim ne yapıyor"
tablosu; canlı ekip durumu; birimler arası bekleyen aksiyonlar; duruma göre iş dağılımı, bölüme göre iş yükü,
planlı bakım tamamlanma oranı, haftalık plan, aylık bakım takvimi. Hepsi kullanıcının kapsamı ve etkin şirketle süzülür
(sayı = liste). Araç konumu Faz D (GPS) gelene kadar "sahadaki ekip" sayısı zaman kaydından hesaplanır.

## 5. UX ilkeleri

- Menü durumu (açık bölümler, daraltılmış menü) ve liste süzgeçleri kullanıcı başına hatırlanır.
- "Hızlı oluştur" (yeni servis işi, yeni bakım, yeni kiralama) her ekrandan erişilir; Ctrl+K genel arama.
- Sayfa başında ekmek kırıntısı (Şirket › Bölüm › Alt bölüm); boş listelerde ne yapılacağını söyleyen mesaj.
- Favoriler ve son açılanlar menünün tepesinde.
- Mobilde menü çekmece olur; dokunma hedefleri ≥ 40 px.

## 6. Rol testi düzeltmeleri (arka uç, 2026-11-04)

Kaynak: `analiz/rol_testi/1_ice_aktarim_operasyon.md` (B…), `2_menu_link_yonetim.md` (B-07),
`3_yonetici_sef_planlama.md` (B…), `4_sirket_sizinti_denetimi.md` (S…). Kullanıcı soru sorulmasını
istemediği için belirsiz noktalarda karar verildi; gerekçeler aşağıda. Ön yüz ayrı pakette düzeltiliyor;
burada yalnız arka uç sözleşmesi yazılı. Migration: `f2a000000001_rol_testi_duzeltmeleri`.

### 6.1 Görev panosu şirkete bağlandı (S1, KRİTİK)
- **Pano etkin şirkete aittir** (`boards.sirket_kod`). Pano, kolon, etiket, kart, yorum uçları yalnız panonun
  şirketi seçiliyken çalışır; başka şirketin panosu/kartı kimlikle istense de **404**. Var olan panolar
  migration'da DENGE MOBİLİTE'ye yazıldı (şirket ayrımından önceki canlı sistem mobilite şirketidir —
  §1 varsayılan üyelik kuralıyla aynı gerekçe). İşten çıkış inceleme panosu çıkışı yapanın etkin şirketinde açılır.
- **Bağlı kayıt kapsamlıdır:** karta yalnız kullanıcının kendi ekranında görebildiği kayıt bağlanır (okuma
  izni + teknik serviste birim/şirket kapsamı, mobilite tiplerinde mobilite kapısı + müşteri kapsamı,
  teklifte teklif kapsamı). Değilse **404** ("kayıt yok" ile aynı yanıt; id sayarak varlık öğrenilemez).
  `GET /gorevler/kayit/{tip}/{id}` de aynı kuraldan geçer.
- **Etiket yalnız görebilene:** bağlantı etiketi (iş no, sözleşme no, plaka, MSISDN, IMEI) kaydı göremeyen
  kişiye "erişim yok" olarak, adressiz ve `var=false` döner. Eski "görev uçlarında kapsam uygulanmaz"
  kararı (30 Eyl 2026) şirket içinde kart başlığı için geçerli kalır; bağlı kaydın içeriği için kaldırıldı.

### 6.2 Mobilite dışa aktarmaları görüntüleme iznine bağlandı (S2)
Hak ediş ödeme Excel'i `rapor.disaaktar` + `hakedis.gor`; abonelik tahakkuk xlsx `rapor.disaaktar` +
`abonelik.gor`; mobilite MRR raporu `rapor.gor` + `abonelik.gor`. Şirket kapısı zaten yönlendiricideydi
(`MOBILITE_KAPISI`). Mobilite iş kuralı değişmedi; yalnız güvenlik kapısı eklendi (G2.5 buna izin verir).

### 6.3 Birimsiz personel şirket üyeliğiyle süzülür (S3, B19)
Birimsiz kişi yalnız `kullanici_sirketleri` üyeliği olan şirkette görünür (yalnız MOBİLİTE üyesi depo
kullanıcısı TELEKOM listesinde görünmez). Birimli kişi eskisi gibi biriminin şirketinde. ADMIN hangi
şirketlerde üyelik satırı varsa orada görünür.

### 6.4 Planlama kontrolü ve tayin mesajları başka şirketi sızdırmaz (B3)
`POST /planlama/kontrol`: kişi ya da araç planlayıcının kapsamında değilse **404** (doluluk takvimi
dönmez). Tayin/plan doğrulamasında işin şirketiyle (birim ya da şirket üyeliği) bağı olmayan kişi
"Kullanıcı bulunamadı (#id)" alır — ad, birim ya da pasiflik mesajı verilmez.

### 6.5 Rol yetkileri: Satış Destek ve Operasyon
- **Satış Destek** (§5.8/3 kurulum takibi): `ekipman.yaz`, `lokasyon.yaz` ve **yeni dar izin
  `servis.kurulum_ac`** ("yalnız KURULUM türünde servis işi açar"; ekran ve ekipmandan açılış). `servis.yaz`
  verilmedi: arıza/bakım açma, not/ek yazma satış desteğin işi değil; en az yetki. Kurulum dışı tür → 403.
- **`hesap.kart_yaz` gerçekten işe yarar:** hızlı müşteri ucu artık yalnız `hesap.kart_yaz` | `hesap.yaz`
  ister (eskiden ayrıca `servis.yaz` istiyordu; satış destekte 53 deneme 403).
- **Operasyon müşteri/tesis açar** (`hesap.kart_yaz`): G10.2'deki "müşteri kartı talebi" mekanizması yok ve
  rol testinde operasyon tamamen tıkandı (41 müşterinin 30'u yeni). Karar: G10.2'nin amacı (doğrulanmış kartı
  yalnız yetkili açar) hızlı kartın **doğrulanmamış** doğmasıyla korunur; doğrulama `hesap.birlestir`
  (yönetici) ekranında. Benzer kayıt uyarısı (409 + aday listesi, `onay_benzer`) aynen sürer; ek onay
  adımı yok (G1.9). KARARLAR 2026-10-28 G10.2 / Faz A-5 bu ölçüde güncellendi.
- **Operasyon atölye kabulü** yapar: yeni dar izin **`atolye.kabul`** (tekli/toplu kabul uçları
  `atolye.yaz` | `atolye.kabul`) + `atolye.gor`. Teşhis, onarım, test, teslim `atolye.yaz`'da kalır.
- **Tesis doğrulaması:** `POST /lokasyonlar` ile açılan tesis, açanın `hesap.birlestir` izni yoksa
  doğrulanmamış doğar ("Doğrulanmamış tesis" kalite listesine düşer).
- İzinler seed senkronuyla (özelleştirilmemiş roller) uygulanır; özelleştirilmiş rolde yönetici rol
  ekranından ekler.

### 6.6 Şef sorumlu olabilir; "tayin edilmemiş" tek tanım (B1)
- Sorumlu (is_lead) teknisyen **ya da şef** olabilir (DB kısıtı `ck_soa_sorumlu_rol`). Planda sorumlu
  verilmezse ilk teknisyen; teknisyen yoksa sahaya giden ilk şef sorumlu olur (Set Bariyer).
- **Tayin edilmemiş iş** = aktif teknisyen tayini YOK ve aktif sorumlu YOK ve sahaya giden kişisi olan
  aktif plan YOK. Liste süzgeci (`/isler?atanmamis=true`), Servis Paneli KPI'ı ve kritik-atanmamış uyarısı
  aynı fonksiyonu (`is_emirleri.tayinsiz_is_kosulu`) kullanır (sayı = liste). Sahaya gitmeyen, sorumlu
  olmayan şef tek başına tayin sayılmaz. Ana Panel "Tayin edilen personel" sorumlu şefi de gösterir.

### 6.7 Kaynak görünümünde ziyaret süresi bir kez (B2)
Kişi × gün hücresinde aynı ziyaretin planları tek kez (ziyaret başına en uzun plan süresi) sayılır;
ziyaretsiz plan kendi süresiyle. 5 cihazlık 300 dk ziyaret artık 300 dk (1500 değil).

### 6.8 Şefin tayin yetkisi (B4; KARARLAR 2026-10-28 §6/2, D3.1–D4.2) — DARALTILMADI
Karar "tayin: TS yöneticisi + **laboratuvar** takım lideri; **saha** takım lideri tayin edemez" diyor.
`SERVIS_SEF` rolü bugün hem laboratuvar şefini (Haberleşme lab) hem saha şefini hem de **yöneticisi
olmayan Set Bariyer'in tek sorumlusunu** temsil ediyor (§3 el yazısı rol tablosunda tek "Takım Lideri /
Şef" satırı). `servis.planla` rolden çıkarılsaydı lab şefi ve Set Bariyer planlama yapamazdı. Karar: rol
daraltılmaz; **saha takım lideri** olarak tanımlanan kişiye kullanıcıya özel izin istisnası
(`user_permissions`, `allow=false`, gerekçeli) ile `servis.planla` kapatılır — yeni rol açılmaz (G1.9,
rol enflasyonu yok). Saha şefi adları bildirildiğinde yönetici ekranından uygulanır.

### 6.9 Planlama doğrulamaları (B6, B7, B5)
- **Geçmiş tarihe plan** (tekli, toplu, yeniden plan; yalnız tarih değişiyorsa): gerekçesiz → 409
  `kod=GECMIS_TARIH`; `gecmis_tarih_gerekcesi` (≥10 karakter) ile kabul, gerekçe denetim izine yazılır.
  Engel değil uyarı (göç/geriye dönük kayıt meşru).
- **Sahada kimsesiz plan** (ekipsiz ya da yalnız sahaya gitmeyen şef): tekli planda da 400 (toplu planla
  aynı kural). Ekipsiz bırakılacak iş PLANLAMADA'da kalır.
- **Tur (aynı müşterinin farklı tesisleri, §7.6 KİPA 9 şube) — ERTELENDİ, Faz B:** küçük bir çözüm yok;
  "tur" kaydı (sıralı birden çok ziyaret, tek ekip/araç, şubeler arası saat çakışmasının sayılmaması,
  ziyaret başı faturalama) ziyaret modeline yeni bir katman ister. O zamana kadar her tesis ayrı ziyaret,
  ardışık saatlerle planlanır (çakışma motoru doğru davranıyor).

### 6.10 Veri kalitesi (B6, B9)
- `seri_eksik` kalite kontrolü ekipmansız ARIZA/PLANSIZ_BAKIM (tek cihazlı, "seri bekleniyor") işleri de sayar.
- "Aynı lokasyonda açık iş" uyarısı iş açılışında **tek** uyarı olarak döner (`adet` + `isler` listesi;
  `so_no`/`id` ilk iş — geri uyum).

### 6.11 Geçiş kaydı ve yurt dışı il (B5, B14)
- **Geçiş/içe aktarma kaydı:** `IsAcIn.gecis_kaydi=true` + `gecis_gerekcesi` (≥10 karakter) ile bildirim
  tarihi 7 günden eski olabilir; iş `sla_kaynak=GECIS` doğar, SLA damgalanmaz (sonuç ÖLÇÜLEMEDİ), işe
  gerekçeli not düşer. Yeni izin **`servis.gecis_kaydi`** yalnız TS müdüründe: SLA dışı bırakma SLA'dan
  kaçış yolu olmasın. Normal girişte 7 gün kuralı aynen. (Talep listesi betiği bu alanla yönetici hesabıyla çalışır.)
- **Yurt dışı il:** il alanı "Yurt dışı", "Yurt dışı - Nijerya", "KKTC"/"Kıbrıs" kabul eder → "Yurt dışı"
  ya da "Yurt dışı (Ülke)". Ülke kataloğu Faz C (Logo cari eşlemesi). İl seçicisine seçenek ön yüz paketinde.

### 6.12 Servis Maliyet sözlükleri (2_menu B-07)
`GET /teknik-servis/isler/form-verileri` `servis.gor` | `maliyet.gor` ister: Servis Maliyet sayfasını
gören Finans Uzmanı süzgeç sözlüklerini okur (yalnız katalog; kayıt dönmez).

### 6.13 Ek notlar (uygulama sırasında verilen kararlar)
- Operasyon `hesap.kart_yaz` ile hızlı kart açtığı gibi kart künyesini (unvan, il, telefon, e-posta, cari kodu)
  de düzeltebilir — izin tek; künye düzeltmesi denetim izine yazılır, mobilite rolü taşıyan hesapta 409 kuralı aynen.
- "Sahada kimse yok" kuralı tekli planda **ekip gönderildiğinde** uygulanır (ekran her zaman ekip gönderir).
  Ekip alanı gönderilmeyen API çağrısı "mevcut ekibi koru" anlamındadır (göç/erteleme betikleri) ve eski
  davranışta kalır.
- Başka şirketin kişisi tayin/plan ekibine verilirse 400 "Kullanıcı bulunamadı (#id)"; aynı şirketin başka
  biriminin kişisi eskisi gibi 409 "… bu işin biriminde değil" (şirket içi ad zaten görünür).

## 7. Rol testi düzeltmeleri — tur 2 (arka uç, 2026-11-05)

Kaynak: `analiz/rol_testi/5_teknisyen_saha_atolye.md` (B…), `6_satis_onay_finans_depo.md` (Y…/O…/D…),
`2_menu_link_yonetim.md` (B-08, B-12). §6 kararları aynen geçerlidir; burada yalnız ekler var. Kullanıcı soru
sorulmasını istemediği için belirsiz noktalarda karar verildi; gerekçeler aşağıda. Ön yüz ayrı pakette düzeltilecek.
Migration: `f3a000000001_rol_testi_tur2` (yalnız sütun ekler; veri değiştirmez). İzin değişiklikleri seed
senkronuyla (özelleştirilmemiş roller) uygulanır.

### 7.1 Teklif kararı ve parça gelişi işi planlama kuyruğuna döndürür (Y1, Y2, O5)
- Saha durumundan (Yola Çıkıldı / Sahada / İşlemde) açılmış **TEKLIF** ya da **MALZEME** beklemesi bitince iş
  İŞLEMDE'ye değil **PLANLAMADA**'ya döner ("Plan bekleyen" KPI'sı, planlama havuzu). Kural tek yerde:
  `bekletme._donus_durumu`. Teklif **reddi** de aynı yere döner: şef işi yeniden planlar ya da sonucu
  "Çözülemedi" girip kapatır (red için ayrı kapanış adımı eklenmedi — G1.9).
- **İstisna:** beklemeyi işin aktif ekibinden biri bitiriyorsa (teknisyen kendi araç deposundan parçayı çıkarıp işe
  devam ediyor) iş önceki durumuna döner; kişi zaten sahadadır, yeniden plan gereksiz adım olurdu.
- **Bildirim:** zilde yeni uyarı `servis.planlamaya_donen` ("Yeniden planlanacak iş") — KPI `planlamaya_donen`
  (PLANLAMADA ∧ saha durumundan açılmış TEKLIF/MALZEME beklemesi kapanmış; PB hariç). Sayı = liste; kapsamla
  süzülür: şef/yönetici biriminde, sorumlu teknisyen kendi işinde görür. İş planlanınca uyarı kendiliğinden düşer.

### 7.2 Fatura devri kalite onayı ister (Y3)
Yalnız **kalite onaylı** iş faturaya devredilir (`fatura_devri.kalite_kapisi`). Kalite kuyruğu iş türü ayırmadığı
için bütün türler (PB dahil) onay ister; kalite kuyruğuna hiç girmeyen göç kayıtları (`source_system` dolu)
istisnadır. Ana Panel "Mali İşler" satırı aynı kapıyı kullanır. Kapıdan önce iletilmiş işler "İletilenler"de
kalır (geri alma bozulmasın).

### 7.3 Kalite reddi ve toplu kalite onayı (Y5, O3)
- `POST /isler/{id}/kalite-reddi` (`servis.kalite_onay`): gerekçe ≥10 karakter; iş **İŞLEMDE** (kayıt/sonuç
  düzeltmesi) ya da **PLANLAMADA** (yeniden ziyaret; varsayılan) durumuna döner. Makineye TAMAMLANDI → İŞLEMDE /
  PLANLAMADA kenarı eklendi ama **yalnız** bu uçtan (`kaynak='kalite_red'`) kullanılır; genel durum ucu tamamlanmış
  işi geri alamaz. KAPATILDI terminal kalır (M1.7: kapanmış iş yeniden açılmaz → bağlı yeni iş).
- Retle geçerli sonuç geçersiz kılınır (düzeltilen iş yeni sonuçla tamamlanır), bakım formu varsa taslağa döner
  (YENIDEN_ACMA ziyaret satırı, gerekçeli). SLA ilk tamamlanmada dondurulduğu için değişmez.
- Engeller: görevler ayrılığı onayla aynı (işte çalışan reddedemez, 403); kalite onayı verilmiş, faturaya iletilmiş
  ya da atölye işi 409 (atölye düzeltmesi atölye kaydının geri alma geçişleriyle).
- Son ret izi `service_orders.kalite_red_at/by/gerekcesi`; ayrıntı iş geçmişinde (KALITE olayı) ve denetimde.
  Zil uyarısı `servis.kalite_reddedilen` (açık ∧ reddedilmiş iş).
- `POST /isler/toplu-kalite-onayi` (en çok 200 iş, her biri kendi `version`'ıyla): her iş tekli kuralla sınanır,
  uygunlar onaylanır, uymayanlar nedeniyle `atlanan`da döner. **Kısmi sonuç bilinçli:** kalite onayı mali işaret
  değildir (fatura devrinin "hepsi ya da hiçbiri" kuralı burada gerekmez); bir işin engeli diğerlerini bekletmesin.
  Kapsam dışı iş "bulunamadı" olarak, iş numarası verilmeden atlanır.
- **Kalite onayı kapanışı da yapsın mı (O3 önerisi) — YAPILMADI:** kapanış (`servis.kapat`) ve kalite
  (`servis.kalite_onay`) Faz A'da ayrı izinler olarak kararlaştırıldı (D3.4/G4.6); birleştirmek şefin kapattığı ama
  kalitesini yöneticinin onayladığı akışı bozar. Toplu onay tık sayısını zaten düşürür.

### 7.4 Yola çıkışın geri alınması (B1, Y6)
- Teknisyenin "Yanlış başlattım"ı (`zaman.geri_al`) YOL bölümünü geri alınca işte başka geçerli bölüm yoksa iş
  YOLA_CIKILDI → **PLANLANDI** döner (makinedeki "yanlış basış" kenarı).
- Pencere geçtiyse yönetici/şef: `POST /isler/{id}/yola-cikis-geri-al` (`servis.planla`, gerekçe ≥10, `version`):
  işteki açık YOL sayaçları gerekçeyle iptal edilir (kişi-saate girmez), iş PLANLANDI olur; denetim izi + DURUM
  olayı. Açık SAHA sayacı varsa 409 (kişi sahada). İş detayındaki geçiş seçeneği artık bu ucu gösterir (eskiden
  "planla" vaat edip durumu değiştirmiyordu).

### 7.5 Bakım formu: sözleşmesiz bakım, ölçümler, önem (B2, B3)
- Form **PLANSIZ_BAKIM** işlerinde de açılır (cihazı bağlı olan işte, şablon cihaz türünden; ilk görüntülemede
  `servis.yaz` sahibi için kendiliğinden açılır — ek düğme yok, G1.9). Cihazsız ya da şablonsuz türde 404 açıklamalı.
  Dönem kapanışı ve kapsam dışı talebi yalnız PB'de kalır. Talep listesi bakımlarını PB'ye dönüştürmek
  ve sözleşmeye bağlamak **Faz B** (ziyaret/tur modeliyle birlikte, §6.9).
- **Ölçümler** (opsiyonel, sayısal, birimli; boş = ölçülmedi, 0 değil): jeneratör kV, mA, penetrasyon (mm),
  doz (µSv/h), besleme voltajı (V). Negatif 422/400. Tamamlamada değişmez ziyaret kaydına kopyalanır. Çözünürlük
  (AWG) ve doz zorunluluğu şablona bağlı ölçüm tablosu ister → E04-22 ile birlikte **Faz B** (şablon tabloya).
- **Uygunsuzluk önemi** DUSUK/NORMAL/YUKSEK/KRITIK (madde → aksiyon); KRİTİK/YÜKSEK bulgudan açılan arıza işi
  aynı önceliği alır. Bağlı arıza işinin **konusu bulgunun kendisi** ("Bakım bulgusu: <teknisyen notu>"); madde
  etiketi açıklamaya.

### 7.6 Bakım işlerinin faturalamaya ulaşması (Y4)
- **Ücret girişi:** `PUT /bakim/sozlesmeler/{id}/ucret` = `maliyet.gor` ∧ (`bakim.yaz` ∨ `tahsilat.yaz`):
  TS yöneticisi (7.7 ile `maliyet.gor`) ve **finans yöneticisi** girer (G4.4 maliyet görenler + fatura devri
  sorumlusu). Satış müdürü/yönetim (salt okur) giremez.
- **PB geliri:** PB TAMAMLANDI olunca sözleşmenin ziyaret başı ücreti (TRY) işin geliri olarak `SOZLESME`
  kaynağıyla yazılır (otomatik, denetimli); elle girilmiş gelir ya da faturaya iletilmiş iş ezilmez, dövizli
  ücret yazılmaz. Böylece kalite onayından sonra fatura devrine düşer.
- **Dönem kapanışı / "faturalanacak" işareti ve bakım dönemleri raporunda "Faturalanacak" sütunu — Faz notu
  (Faz C, Logo geçişi):** dönem başı toplu faturalama, sözleşme toplamı ile ziyaret başı ücretin uzlaştırılması
  ve PLANSIZ_BAKIM'ın sözleşme bağı küçük bir çözüm değildir; o zamana kadar PB'ler tek tek fatura devrinden geçer.

### 7.7 Maliyet görünürlüğü G4.4'e hizalandı (Y7, O6)
- **TS Yöneticisi (`SERVIS_YONETICI`) `maliyet.gor` ALIR** (G4.4 listesinde). Servis rollerinde maliyet yasağına
  tek istisna budur (`maliyet.yaz` yine yalnız ADMIN).
- **Finans Uzmanı (`MUHASEBE_DESTEK`) `maliyet.gor` KAYBEDER** (G4.4: "Muhasebe Uzmanı görmez"). Fatura devri
  tutarını `teklif.gor` ile görmeye devam eder (gelir/teklif tutarı maliyet değildir). Yan etki (bilinçli, G4.4
  şirket geneli karar): mobilite hat kârlılık raporu (`maliyet.gor`) ve satın alma birim maliyeti finans uzmanına
  kapanır; hak ediş/rapor erişimi (`hakedis.gor`) değişmez. Mobilite iş mantığı değişmedi, yalnız rol izni.

### 7.8 Satış kendi müşterilerinin servis işlerini ve tekliflerini görür (Y8, O12)
- `SATIS` rolüne `servis.gor`. KENDI_MUSTERILERI iş kapsamı: müşteri portföyde (`accounts.sales_rep_id`) ∧ birim
  (üyeliği varsa o birimler, yoksa etkin şirketin birimleri). Müşterisiz iş görünmez; şirket ayrımı sürer
  (başka şirketin işi kimlikle de 404). Yazma, irtibat tam görünümü ve maliyet yok.
- Teklif okuma kapsamı: kendi teklifi **veya** kendi müşterisinin teklifi (satış destek'in hazırladığı servis
  teklifi görünür). Yazma yalnız kendi teklifinde. BAŞKA temsilcinin müşterisine teklif açamaz ("Müşteri bulunamadı");
  sahipsiz (temsilcisi atanmamış) müşteriye ilk teklif canlı satış akışındaki gibi açık kalır (mobilite akışı bozulmasın).
- Ana Panel satışta artık açılır (kapsamlı sayılarla).

### 7.9 – 7.10 Liste süzgeci ve "süre kaydı eksik" (O11, B4)
- `GET /isler?sonuc=TEKLIF_SUNULACAK` (Excel'de de): geçerli sonucu verilen olan işler — satış destek "teklif
  hazırlanacak" listesi.
- Servis Paneli `sure_eksik` KPI'sı artık **EKSİK ∪ KISMİ** sayar (`zaman.sure_eksik_ifadesi`, Zaman Takibi KPI'sı
  ve kapanış uyarısıyla tek tanım). 3 kişilik ekipte 1 kişinin süresi eksik kapanan iş listede.

### 7.11 – 7.13 Tayin ve bağlı iş (B5, B7, B8)
- **Atölye ustası** (`atolye.yaz`) saha rolü olmasa da **atölye işine** tayin edilebilir (kendine de) ve süre girer;
  saha işlerinde kural değişmez.
- Ekipte `servis.tamamla` sahibi yoksa (ör. yalnız saha sorumlusu) tayin **engellenmez**, uyarı döner
  ("Ekipte sonuç girebilecek kimse yok; işi şef ya da yönetici tamamlar"). Saha sorumlusuna sonuç izni
  verilmedi (§3 rol tanımı); iş, ekip dışından `servis.tamamla` sahibi şef/yönetici tarafından tamamlanır.
- Teknisyen **kendi açtığı bağlı işi** (kapanmış işten "bağlı yeni iş") tayin edilmeden de görür (KENDI_ISLERI
  kapsamına yalnız bu eklendi; genel açılış kapsamı değişmedi). `BagliIsIn.iliski_turu`
  (TEKRAR_ARIZA / BAKIM_BULGUSU / DEVAM) bağın türünü yazar.

### 7.14 – 7.15 Atölye (B11, B12)
- `PATCH /atolye/{id}` izinsiz kullanıcı `repair_amount` gönderirse **403** (sessiz yok sayma kaldırıldı).
- Kabulde `birim` verilmezse kullanıcının birimi (birincil / tek görünür birim; geri uyum için HABERLESME); belirsizse
  400. `form-verileri?birim=` aynı kuralla; marka ve ekipman tipi listesi birime göre (telsiz birimleri: marka
  sözlüğü; diğerleri: birimin kütüğündeki markalar + DIGER, serbest marka).

### 7.16 Tek "açık iş" tanımı (B-08, D3)
Ana Panel'de durum dağılımı, bölüm iş yükü ve aktif işler tablosu "Açık İş Emirleri" KPI'sıyla aynı tabanı
kullanır: **PB hariç** (`kpi=servis_isleri` liste süzgeci). Planlı bakım kendi kartı ve grafiğinde. Sayı = liste.

### 7.17 POC kartı ve görünür birimler (B-12)
POC KPI kartı yalnız POC birimi etkin şirkette/kapsamda iken döner (ELEKTRONİK/MOBİLİTE'de hiç yok). `/auth/me`
yanıtına `gorunur_birimler` eklendi (etkin şirkette görülebilen birimler; oturum dışı boş).

### 7.18 Finans yöneticisi yalnız ofisten (O10)
`FINANS_YONETICI` `YALNIZ_OFIS_ROLLERI`'ne eklendi (G3.8 + Faz A/8 "muhasebe rolleri", iş analizi §5.9/5).
Liste boşken kısıt uygulanmaz (kurulum günü kilitlenme yok). **Canlıya geçiş listesi:** `ofis_ag_listesi` ayarı
girilmeli; uvicorn `--forwarded-allow-ips` yalnız ters vekile verilmeli (aksi halde X-Forwarded-For ile kısıt
aşılır — rol testi 1.3 notu).

### 7.19 Ertelenenler (Faz notları)
- Bakım dönem kapanışı / toplu faturalama (7.6), PLANSIZ_BAKIM'ın sözleşmeye bağlanması (7.5), şablona bağlı
  zorunlu ölçümler (7.5) — Faz B/C.
- Teklif kabulünde atölye MÜŞTERİ_ONAYI beklemesinin teklife bağlanması (O1), parça transferinin talebe bağlanması
  (O5 ikinci yarı), teknisyen çıkışının depo onayı (O8), depo ekipman yetkisi (O7), fatura devri satırında iş
  özeti (O9), kalite onay penceresinde süre-eksik uyarısı (O2), Ana Panel ek KPI'ları (D2/D4) — bu turda
  yapılmadı; ayrı pakete.

## 8. Atölye listesi: KPI kutucukları sekme şeridine taşındı (2026-11-06)

Kullanıcı isteği: atölye işlerinde KPI kutucukları sayfada durmasın; bilgileri ikonlu sekme şeridinde olsun, sayfa sade olsun, sekmeler arasında gezilip süzülsün, kullanıcı görmek istediği sekmeleri kendisi seçsin.

- **8.1** Kutucuk ızgarası kaldırıldı. Her KPI (Atölyede, durumlar, bekleme yaşı, tahmini bitişi geçen, teslim alınmayan, süre kaydı eksik) şeritte bir "durum sekmesi" oldu. Sayısı rozette görünür (0 da gösterilir). Uyarı niteliğindeki sekmeler sayı > 0 iken kırmızıdır.
- **8.2** Şerit iki gruptur: servis türü | durum, aralarında ince ayraç vardır. İkisi birlikte seçilebilir (ör. ARIZA ONARIMI + TEŞHİSTE). Durum sekmesine ikinci tık süzgeci kaldırır. Sayı = liste kuralı korunur: sekme sunucunun KPI süzgecini (`sorgu`) uygular.
- **8.3** Şeridin sağ ucundaki "Sekmeler" dişlisiyle kullanıcı hangi sekmelerin görüneceğini seçer. "Tümü" gizlenemez; "Varsayılana dön" ve "Hepsini göster" vardır.
  - Varsayılan: bütün servis türleri ve 7 durum sekmesi (Atölyede, Teşhiste, Onay bekliyor, Onarımda, Parça bekliyor, Teslime hazır, Tahmini bitişi geçen).
  - Seçili sekme gizlense de görünür kalır; süzgeç sessizce kaybolmaz.
- **8.4** Tercih tarayıcıda kullanıcı başına saklanır (`yerelDepo`, §5: yalnız kolaylık verisi, kişisel veri yok). Başka bilgisayarda varsayılanla açılır; sunucu tarafı tercih tablosu gerekirse sonra eklenir.
- **8.5** Yetenek ortak bileşende (`KategoriSeridi` / `ListeRaporu.kategoriAyari`); diğer liste sayfaları aynı şekilde açılabilir.
