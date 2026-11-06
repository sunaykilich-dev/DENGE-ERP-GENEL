# İş Analizi Özeti — Denge Grup teknik birimleri (04.11.2026)

Kaynaklar (salt okunur, `kaynak/is_analizi_2026-11-04/`):
`Denge_Is_Plani_Analizi_2017-2026.xlsx`, `Dijital_Servis_Formlari.pdf`, `Guvenlik_Talep_Takip_26.10.2026.xlsx`;
bağlam: `analiz/DengeERP_Proje_Gecmisi_...2026-10-21.md`, `analiz/soru_formu/KARARLAR_2026-10-28.md`,
`analiz/soru_formu/KARARLAR_2026-11-04_sirket_sayfa_rol.md`; ERP karşılaştırması `denge-erp/backend/app/models/*`,
`services/teknik_servis/*`, `templates/*.html`.

**KVKK:** Bu belgede kişi adı, telefon, plaka, e-posta yoktur. Kaynak dosyalarda personel adları, müşteri yetkili adları
ve telefonları, WhatsApp mesaj metinleri ve plakalar vardır; bunlar ERP'ye içe aktarılırken kişisel veri kuralları
(aydınlatma, saklama süresi, yetkiye bağlı görünürlük) uygulanmalıdır. Müşteriler sektör düzeyinde anlatıldı; yalnız
birkaç büyük kurumsal müşteri örnek verildi.

**Okuma notu:** Excel'deki sayılar aylık iş planı dosyalarından ve iki telefonun WhatsApp dökümünden türetilmiştir.
Bazı aylar kaynakta yok (ör. 2018 Mart–Aralık, 2020 Mart–Nisan, 2023 Temmuz, 2026 Kasım–Aralık; 2017 yalnız Ekim–Kasım),
bu yüzden yıllık eğilim **2021–2025 tam yılları** üzerinden yorumlandı. "Özet" sayfasındaki yıllık tablo formüllüdür ve
dosyada hesaplanmış değer olarak kayıtlı değildir; değerler `Tüm İşler` sayfasından yeniden hesaplandı.

---

## 1. Belgelerin içeriği (envanter)

### 1.1 `Denge_Is_Plani_Analizi_2017-2026.xlsx` (16 sayfa)

| Sayfa | Satır | İçerik |
|---|---:|---|
| Özet | 28 | Başlık "Kiralama ve Teknik Birimler İş Planı Analizi", yıllık özet şablonu, sayfa açıklamaları |
| Tüm İşler | 39.684 | 01.10.2017–20.10.2026 arası her plan satırı: tarih, gün, zaman ifadesi, personel (çoklu), iş tanımı, firma, adres, araç, iş türü (Saha/Ofis-Depo/İzin-Rapor/Yolculuk), bölge, şehir dışı, WhatsApp sonucu ve bitiş saati, bildiren, servis formu no, iş tipi (Kurulum/Arıza-Onarım/Teslim-İade/Bakım/Keşif/Diğer), plan saati, plandan bitişe dk, önceki işten dk |
| Ekim 2026 | 306 | Son ayın aynı düzende dökümü (148 saha, 115 ofis/depo, 29 izin, 14 yolculuk) |
| Personel (Yıllık) / (Ekim 2026) | 280 / 27 | Kişi başına planda gün, saha günü, saha iş adedi, şehir dışı gün, ofis/depo gün, izin, gece işi, bildirim oranı |
| Araçlar (Yıllık) / Araç Günlük Km | 111 / 7.323 | Plaka bazında kullanım günü, atanan iş, tahmini km, günlük güzergâh |
| Birleştirilebilir Seferler | 254 | 2–7 gün arayla aynı şehre yapılan ikinci seferler (≈125 bin km "önlenebilir" yol; en çok Bursa, Ankara, Gebze) |
| Tekrarlayan Arızalar | 60 | En çok arıza ziyareti alan lokasyonlar (AVM'ler başta; bir AVM'de 9 yılda 60 arıza günü) |
| Servis Formları | 835 | Dijitale aktarılan form listesi: tür, sıra no, tarih, firma, sonuç kutusu, eşleşen plan satırı, WhatsApp kaydı, kalite notu |
| Plan Dışı Bildirimler | 2.372 | WhatsApp'ta bildirilen ama planda karşılığı bulunamayan mesajlar (2023'te 670) |
| Verimlilik - Kişi / İş Tipi / Bitiş Saat Dağılımı | 141 / 17 / 24 | Medyan iş/gün, ilk-son iş bitiş saati, işler arası süre, mesai dışı bitiş oranı |
| Ekim 2026 Günlük Akış | 148 | Ekim 2026'da her işin plan saati, bitişi, gecikmesi |
| WhatsApp Görsel Arşivi | 2.037 | Fotoğrafların tahmini türü: 1.073 form/belge, 808 saha fotoğrafı, 156 plan görseli |

### 1.2 `Dijital_Servis_Formlari.pdf` (849 sayfa)

WhatsApp "Güvenlik Sistemleri" grubuna fotoğrafı atılan kâğıt formların 2023–Ekim 2026 yazıya aktarımı. İlk 13 sayfa
dizin; sonra her sayfa bir form ve altında "dijital kopya bilgisi" (kaynak görsel, WhatsApp kaydı, eşleşen plan satırı,
kontrol notu).

| Form | Adet | Belge kodu |
|---|---:|---|
| Teknik Servis Formu | 463 | PR.07-FR.08/00 |
| Servis Bakım Formu | 365 | (aynı alt bilgi) |
| Müşteri tarafından düzenlenen tutanak | 5 | — |
| Kiralama Teslim Tutanağı | 2 | — |
| Ürün Teslim Formu (demo/değişim) | 1 | — |

Yıl dağılımı (Excel "Servis Formları"): 2023: 3, 2024: 25, 2025: 484, 2026 (Eki'ye kadar): 318. Dijitalleşme 2025'te
başladı; formların 835'inin tamamı bir plan satırı ve WhatsApp kaydıyla eşleşti.

### 1.3 `Guvenlik_Talep_Takip_26.10.2026.xlsx` (1 sayfa, 71 dolu satır)

"Müşteri Talepleri" sayfası; Güvenlik Sistemleri biriminin elle tutulan talep/iş takip listesi. Sütunlar ve ayrıntı §7'de.

---

## 2. Şirket / birim / departman yapısı ve iş hacimleri

### 2.1 Yapı (belgelerden çıkan)

- **Denge Grup**: Denge Telekom (Haberleşme, POC), Denge Elektronik (Güvenlik, Set Bariyer), Denge Mobilite (Mobilite,
  Araç Takip) — birim→şirket eşlemesi KARARLAR_2026-11-04 varsayımıdır; iş planı belgesi bu ayrımı yapmaz, tümünü
  "Kiralama ve Teknik Birimler" tek planında yürütür.
- Ortak merkez: Ataşehir'deki plaza (ofis/depo satırlarının büyük çoğunluğunun bölgesi burası) + ayrı bir depo lokasyonu
  (sevkiyat hazırlığı, sandıktan çıkarma/test).
- Plan tek bir günlük "iş planı" Excel'i olarak hazırlanıp akşam WhatsApp gruplarına görsel olarak atılıyor
  (156 plan görseli); bitişler grup mesajı + fotoğraf ile bildiriliyor.
- Planda yer alan kişi sayısı yılda 26–40 (2025: 32, Ekim 2026: 27 kişi). Ekim 2026'da 17 kişinin saha işi var;
  4–5 kişi ağırlıkla ofis/depo/atölyede (planlama, satış destek, depo, laboratuvar).
- Araç havuzu yılda 12–21 plaka; ek olarak "kiralık araç", toplu taşıma, havayolu kullanılıyor. 2025'te ≈200 bin km.

### 2.2 Birimlerin yürüttüğü işler (iş tanımı metinlerinden)

| Birim / ekip | İşler | Ürünler |
|---|---|---|
| **Güvenlik Sistemleri (saha)** | X-Ray ve kapı tipi metal dedektörü (KMD) satış sonrası kurulum, periyodik bakım, arıza tespiti/onarımı, jeneratör/PC kasası/konveyör/roller değişimi, kalibrasyon, kullanıcı eğitimi | X-Ray (çok markalı), KMD, el dedektörü, roller/konveyör, araç altı arama |
| **Kiralama (tüm birimler)** | Etkinlik/fuar/kongre/maç/miting için kiralık X-Ray+roller, KMD, sehpa, telsiz, bariyer **teslim → kurulum → refakat → iade alma**; uzun süreli kiralama | X-Ray, KMD, telsiz setleri, tekno/akordiyon/polis bariyeri, silah dolabı |
| **Haberleşme (saha + laboratuvar)** | Telsiz/röle/anten kurulumu, araç telsizi montajı (enerji dağıtım şirketleri), multi-site sistem devreye alma, keşif, laboratuvarda arıza onarım + fiyatlandırma, kiralık telsiz bakım-kontrolü | Hytera telsiz, röle/tekrarlayıcı, dispatcher, gateway |
| **POC** | Bayi ve müşteri desteği (ofisten), cihaz tanıtım/eğitim | POC terminalleri |
| **Set Bariyer** | Bariyer teslim, kurulum, toplama, taşıma (yüzlerce adetlik etkinlik işleri) | Tekno, akordiyon, polis bariyeri |
| **Atölye / teknik servis içi** | "Teknik servise gelen cihazların tamiri, arızalı cihazlara fiyatlandırma", "onay alınan cihazların tamiri", jeneratör tamiri, yedek parça sipariş listesi | — |
| **Operasyon / satış destek (ofis)** | "Cihazların ilk kontrol ve kayıtları; teklif, CRM, fatura, irsaliye, tahsilat, depo ve kargo süreçlerinin yönetimi", proje takibi, gün sonu raporlarının iletilmesi (1.320 satır) | — |
| **Depo** | Depo giriş-çıkış, satılan ürünlerin stok işlemleri, tamirde kullanılan yedek parça çıkışı, sevkiyat hazırlığı | — |

### 2.3 Hacim ve eğilim

**Plan satırı türleri (tüm dönem):** Ofis/Depo 19.177 · Saha 17.245 · İzin/Rapor 2.616 · Yolculuk 646.

**Saha işleri, iş tipine göre:**

| Yıl | Kurulum | Arıza-Onarım | Teslim/İade | Bakım | Keşif | Diğer | Toplam saha |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 407 | 399 | 304 | 238 | 5 | 190 | 1.543 |
| 2022 | 719 | 439 | 572 | 205 | 16 | 289 | 2.240 |
| 2023* | 797 | 412 | 457 | 133 | 13 | 288 | 2.100 |
| 2024 | 751 | 470 | 529 | 188 | 9 | 232 | 2.179 |
| 2025 | 808 | 704 | 517 | 347 | 10 | 259 | **2.645** |
| 2026 (Oca–20 Eki) | 658 | 431 | 400 | 243 | 13 | 182 | 1.927 |

\* 2023 Temmuz verisi yok.

- **Büyüme:** saha işi 2021→2025 +%71. 2025'te arıza-onarım (+%50) ve bakım (+%85) sıçradı; 2026 aynı tempoda
  (≈9,5 ay için 1.927 → yıl sonu tahmini ≈2.400).
- **Ürün kırılımı (saha, metin anahtar kelimesi):** X-Ray/dedektör 9.457 (%55), telsiz/röle/haberleşme 2.329 (%14),
  bariyer 1.447 (%8), jeneratör 64, diğer 3.948. X-Ray geçen satır 2024'te 474 → 2025'te 1.424 → 2026'da 1.457
  (Güvenlik birimi ana büyüme kaynağı).
- **Kiralama:** "KİRALIK" geçen saha işi 2022'den beri yılda 600–800; Teslim/İade satırlarının çoğu kiralama.
- **Satış sonrası teslim/kurulum** ("SATIŞI YAPILAN / SIFIR"): 2021'de 82 → 2024'te 220 → 2025'te 194.
- **Müşteri çeşitliliği:** yılda farklı firma sayısı 2021: 609 → 2025: 1.093.
- **Müşteri tipi (saha işi, ad tabanlı sınıflama, kaba):** AVM 1.972 (arıza-onarım ağırlıklı: 992), fuar/kongre/etkinlik/
  ajans 2.329 (kurulum + teslim/iade ağırlıklı), belediye ve iştirakleri 1.039, adliye/kamu 852, enerji dağıtım/altyapı
  626 (telsiz montajı), özel güvenlik şirketleri 689, banka/finans 487, okul 201, otel 115, kargo/lojistik 149; Denge
  iç işleri 3.037. Örnek büyük kurumsal müşteriler: TÜYAP, Halkbank, İBB ve iştirakleri (İGDAŞ, İSKİ, İtfaiye),
  AYEDAŞ, ENERYA.
- **Şehir dışı:** saha satırlarının ≈%28'i; 2025'te 849 satır. Bursa, Ankara, İzmir, Konya, Antalya, Kocaeli öne çıkıyor.
- **Günlük yük:** 2025'te iş günü başına medyan 8 saha işi (en çok 21). Kişi başı WhatsApp ile bitişi bilinen iş/gün
  medyanı 1,3 → 1,6 (2021→2025). İşlerin %30–40'ı mesai dışında bitiyor; 00:00–05:00 arası 367 iş bitişi var
  (AVM'lerde gece bakım/kurulum).
- **Ölçülebilir süre:** 2026'da medyan "plan saatinden bitişe" arıza 212 dk, kurulum 205 dk, bakım 186 dk.

### 2.4 Mevsimsellik

- Ekim en yoğun ay (saha 1.895; kurulum 548, teslim/iade 481 — fuar/kongre sezonu), sonra Haziran (1.661) ve Ağustos
  (1.597). Şubat ve Nisan en sakin.
- Arıza-onarım Ağustos'ta tepe yapar (460; sıcak/yoğun AVM dönemi); bakım Haziran ve Aralık'ta yoğunlaşır
  (yarıyıl/yıl sonu bakım dönemleri).
- Hafta sonu: saha işlerinin %12–22'si Cumartesi-Pazar (etkinlik kurulumları). Cumartesi plan satırı 5.492 — Cumartesi
  fiilen iş günü.
- İzin/rapor satırlarında belirgin kalıp: "gece / şehir dışı / hafta sonu çalışmasından dolayı izinli" (≈400 satır) →
  telafi izni ayrı bir neden olarak takip ediliyor.

### 2.5 Ölçülen kalite ve verimlilik sorunları (ERP'nin çözmesi gerekenler)

1. **Bitiş kanıtı zayıf:** saha işlerinin yalnız %28–40'ında WhatsApp bitiş bildirimi var (2026: %40).
2. **Plan dışı iş:** 2.372 WhatsApp bildiriminin planda karşılığı yok → işler kayda girmeden yapılıyor.
3. **Tekrarlayan arıza:** ilk 25 lokasyonun hepsi 18+ arıza günü; çoğu AVM.
4. **Rota israfı:** 254 birleştirilebilir sefer, ≈125 bin km.
5. **Form kalitesi:** sonuç kutusu formların %60'ında boş; başlangıç/bitiş saati Teknik Servis Formlarının %80'inde boş;
   "bildirilen arıza" 383/463 formda boş; aynı sıra no 4 farklı formda; seri no çapraz yazımı (e-irsaliye ile çelişki);
   arıza giderilmediği hâlde "tamamlandı" işareti; acil stop kırık gibi güvenlik bulguları serbest notta kalıyor.

---

## 3. Uçtan uca iş akışları ve el değiştirmeler

Aşağıdaki akışlar iş tanımı metinleri, form türleri ve talep listesinden çıkarıldı. "Onay" sütunu bugünkü fiilî
uygulamayı ve ERP kararlarını (KARARLAR_2026-10-28 §4: tek adımlı onay, onaycı = org yöneticisi) birlikte gösterir.

### 3.1 Arıza (saha)
`Müşteri (telefon/WhatsApp/e-posta) → Operasyon uzmanı/satış destek kaydı → TS yöneticisi/lab takım lideri tayin + plan
(araç, ekip) → teknisyen sahada (Teknik Servis Formu, imza, fotoğraf) → sonuç: Tamamlandı | Tekrar gidilecek | Teklif
çekilecek | Servise alındı → (teklif) satış destek teklif hazırlar, müşteri onayı → parça (depo) → ikinci ziyaret →
takım lideri kalite onayı → finans faturalanacaklar → fatura (bugün Logo)`.
- Onaylar: tayin (TS yöneticisi / lab takım lideri), teklif iskontosu (satış yöneticisi), kalite (saha takım lideri;
  teknisyen kendi işini onaylayamaz), fatura devri (finans yöneticisi).
- Bugünkü kopukluk: "teklif çekilecek" sonucu formda kalıyor; teklife dönüşümü ve onay sonrası tekrar planlama
  izlenmiyor (talep listesinde "BEKLEMEDE" satırlarının notları: "parça temin edilecek", "kargoya verildi").

### 3.2 Atölye / laboratuvar onarımı
`Cihaz teslim alma (müşteri tutanağı veya kargo) → kabul + ilk kontrol kaydı (ofis) → arıza tespiti + fiyatlandırma →
müşteri onayı → tamir (yedek parça çıkışı depodan) → test → teslim (sahada kurulum veya kargo) → fatura`.
- Plan satırları: "servise gelen cihazların tamiri, fiyatlandırma çalışması" (523), "onay alınan cihazların tamiri" (≈700).
- Formdaki uyarı metni: servis süresi en fazla 20 iş günü, 90 gün içinde alınmayan üründen sorumluluk yok → ERP'de
  atölye kaydı için 20 iş günü hedefi ve 90 gün "teslim alınmadı" uyarısı.

### 3.3 Periyodik bakım (sözleşmeli)
`Satış/sözleşme (yılda n bakım, sabit aylar) → dönem üretimi → operasyon planı (aynı bölge/AVM zinciri tek turda) →
cihaz başına bakım formu (X-Ray 13 madde + ölçümler; KMD 14 madde) → uygunsuzluk: yerinde giderildi | teklif | arıza
iş emri → müşteri imzası → takım lideri kalite onayı → dönem kapanışı → faturalama (ziyaret başı ücret)`.
- Örnek: bir perakende zincirinin 9 ildeki şubeleri 2 ekip + 1 araçla 26–28 Ekim'de tek turda bakıldı (talep listesi).

### 3.4 Kiralama (etkinlik/fuar/uzun süreli)
`Talep (ajans/organizatör, satış) → teklif → onay/sipariş → depoda hazırlık (kontrol, yükleme planı) → teslim/kurulum
(Kiralama Teslim Tutanağı, seri nolar, aksesuar sayımı) → (refakat) → iade alma (eksik malzeme listesi) → depoda kontrol
(uygun/eksik/arızalı) → eksik/hasar bedeli faturası → kira faturası`.
- Kararlar: kurulum TS, sevk/toplama kiralama rolü (G2.6); çakışma uyarı + gerekçe (M10.1).
- Hacim: 2022'den beri yılda 600–800 kiralık saha satırı; Ekim zirvesi.

### 3.5 Satış → teslim → kurulum
`Satış (teklif, sipariş) → satın alma/ithalat → depoya giriş, sandıktan çıkarma, test → sevkiyat hazırlığı → e-irsaliye →
teslim + kurulum + kullanıcı eğitimi (formda "satılan cihazların kurulumu") → kütüğe garanti başlangıcı → fatura`.
- Talep listesinin ikinci bölümü (30 satır) tam olarak bu: satılan ürün kalemleri ve kurulum/teslim durumu (yurt dışı
  sevkiyat dâhil). Kurulumu "elektrik yok", "müşteri açık alan istedi" gibi saha engelleriyle bekleyenler var.

### 3.6 Keşif / proje (Haberleşme ağırlıklı)
`Talep/ihale → keşif (yol, şehir dışı) → proje dokümanı + teklif → onay → malzeme talebi/satın alma → kurulum (çok günlü,
şehir dışı) → devreye alma + eğitim → proje kapanış raporu → bakım sözleşmesi`.
- Plan satırlarında "devam eden projelerin takibi", "proje dokümantasyonlarının tamamlanması", "ihale kapsamında saha
  keşfi" sık; proje bazlı maliyet (yol, konaklama, araç-gün) bugün izlenmiyor.

### 3.7 Demo / değişim / emanet
`Talep eden (yönetim/satış) → Ürün Teslim Formu (demo süresi, birim fiyat, 10 gün içinde iade yoksa fatura) → teslim →
iade veya fatura`. ERP'de karşılığı yok (§4.5).

### 3.8 Günlük planlama ve gün sonu
`Akşam: ertesi günün planı (Excel → görsel → WhatsApp) → sabah: ekipler yola çıkar → iş bitince WhatsApp mesajı +
fotoğraf + form fotoğrafı → ofis "gün sonu raporlarının iletilmesi" → plan dosyası güncellenir`.
- ERP'de bunun karşılığı: planlama takvimi + teknisyene sabah iş listesi (G6) + mobil iş kartında başlat/bitir + form +
  imza + fotoğraf. WhatsApp'a gidecek **günlük plan çıktısı** (PDF/görsel) ERP'de yok.

---

## 4. Dijital servis formları ve ERP karşılığı

ERP referansı: `ServiceOrder` (iş), `ServiceOrderSerial`, `ServiceResult`, `ServiceApproval`, `ServiceTimeEntry`,
`ServicePlan`/`ServicePlanMember`/`ServiceVehicle`, `MaintenanceForm`/`MaintenanceFormCheck`/`MaintenanceNonconformity`,
`ServiceEquipment`, `Rental*`, `WorkshopRecord`, `Quote`; PDF şablonları `templates/servis_formu.html`,
`kiralama_tutanak.html`, `atolye_kabul_fisi.html`, `atolye_teslim_tutanagi.html`, `teklif.html`; bakım maddeleri
`services/teknik_servis/bakim_sablonlari.py`.

### 4.1 Teknik Servis Formu (463 adet)

| Kâğıt alan | ERP karşılığı | Durum |
|---|---|---|
| Sıra no (ön basılı) | `so_no` (sistem numarası) | Var. **Eksik:** paralel dönem için "basılı form no" alanı (G1.6; aynı sıra no 4 formda bulundu) |
| Tarih, başlangıç/bitiş saati | `ServiceTimeEntry` (YOL/SAHA…), `completed_at` | Var (daha ayrıntılı). PDF'te "süre" var; **form başlığında başlangıç–bitiş saati** gösterilmeli |
| Firma/kurum, adres/şube | `customer_id`, `address_id`, `location_raw` | Var |
| Vergi dairesi / vergi no | Müşteri kartı (account) | Var (kartta); PDF'te basılmıyor — kâğıtta 463/463 boş, ihtiyaç zayıf |
| Firma yetkilisi, tel | `contact_id`, `iletisim_ad`, `iletisim_telefon` | Var |
| Bildirilen arıza | `konu` + `aciklama` | Var. **Düzeltme:** ARIZA türünde "bildirilen arıza" ayrı ve zorunlu (kâğıtta 383/463 boş) |
| Servis türü kutuları: Garanti / Garanti dışı / Sözleşmeli | `coverage_status` (SOZLESMELI, GARANTILI, KAPSAM_DISI, BILINMIYOR) | Var |
| Bakım / Keşif / Kurulum | `tur` (PB, PLANSIZ_BAKIM, KESIF, KURULUM) | Var |
| Kiralama | `tur` KURULUM/TOPLAMA + `rental_id` | Var |
| Merkez servis | `tur` ATOLYE / `cozum_kanali` ATOLYE | Var |
| **Nakliye** | — | **Eksik:** TASIMA türü (karar var, kodda yok) |
| **Yedek parça (yalnız parça teslimi)** | — | **Eksik:** parça teslim/satış iş türü veya "TESLIM" türü |
| Diğer | DESTEK | Var |
| Ürün: marka-model, seri numaraları (çoklu) | `ServiceOrderSerial` + `ServiceEquipment` (brand, model) | Var; **kural:** arızada 1 cihaz, kurulumda çoklu seri |
| Kullanılan yedek parçalar (adet/birim) | `ServicePartRequest` + stok çıkışı; PDF "Parçalar" | Var (169 formda dolu). Sökülen parça/cihaz ayrı yazılmalı (formlarda "sökülen" yedek parça bölümüne yazılmış) |
| Yapılan işlem, not | `ServiceResult.yapilan_islem`, olay NOT | Var |
| Sonuç: Tamamlandı / Tekrar gidilecek / Teklif çekilecek | `ServiceResult.sonuc` COZULDU / TEKRAR_GIDILECEK / TEKLIF_SUNULACAK | Var |
| Sonuç: Servise alındı | `cozum_kanali=ATOLYE` + `WorkshopRecord` | Var (adlandırma farklı; mobil ekranda "Servise alındı" düğmesi olmalı) |
| Sonuç: Servis iptal | `status=IPTAL`, `cancel_reason` | Var |
| Denge yetkilisi (çoklu) | `ServiceOrderAssignment` | Var |
| Firma yetkilisi ad/ünvan/imza | `ServiceApproval` (IMZA/SOZLU/BASILI_FORM/ALINAMADI, imzalayan ad/ünvan, ek) | Var |
| Alt bilgi: belge kodu PR.07-FR.08/00, "servis süresi en fazla 20 iş günü, 90 gün" metni | — | **Eksik:** `servis_formu.html` bu kalite belge kodunu ve şartı basmıyor |
| WhatsApp fotoğraf kanıtı | Ekler (`EK`), konumlu başlat/bitir | Var; fotoğraf zorunluluğu iş türüne göre ayar olmalı |

### 4.2 Servis Bakım Formu (365 adet)

Tek kâğıtta X-Ray + KMD birlikte; ERP'de **1 cihaz = 1 PB iş emri** (korunur), PDF toplu basılabiliyor (`toplu`).

| Kâğıt alan | ERP karşılığı | Durum |
|---|---|---|
| Sıra no, tarih, başlangıç/bitiş | `so_no`, zaman kaydı | Var (basılı form no eksik, §4.1) |
| Ünvan, adres/şube | müşteri, adres, `zone` (bölge) | Var |
| Marka/model, seri | ekipman + seri | Var |
| X-Ray 13 ana madde (genel kontrol, temizlik 6 alt madde, perde, klavye, uyarı ışıkları, acil stop, besleme sistemi, konveyör motoru, yazılım, radyasyon, kablolar, izolasyon, teslim) | `XRAY` şablonu 11 madde (XR_EXT…XR_SAFETY) | **Kısmi.** Ayrı maddeler yok: yazılım sürümü/arşiv hafızası, TAEK/lisans geçerliliği, besleme voltajları, topraklama-nötr, jeneratör yağ kaçağı/sesi, motor bant kenarı, avare merdane |
| **Ölçümler:** jeneratör kV/mA, azami penetrasyon (mm), azami çözünürlük (AWG), dozimetre doz oranı (yan panel / tünel içi), AC voltaj | — (yalnız UYGUN/UYGUNSUZ + not) | **Eksik:** sayısal ölçüm alanları. Kâğıtta kV/mA 308/365 formda dolu; doz ölçümü yalnız 20'sinde → doz zorunlu yapılmalı (radyasyon güvenliği) |
| KMD 14 madde (yan panel, darbeli ekipman, modüller, soketler, AC, sabit durma, enerji kabloları, basınçlı hava, açılış testi, yönlendirme ışıkları, panel ışıkları, sayaçlar, **FAA testleri**, çıkış ışıkları) | `KAPI_DEDEKTORU` şablonu 10 madde (MD_*) | **Kısmi.** FAA/standart test sonucu ve sayaç değeri sayısal alan değil |
| Not | `technician_note`, `performed_work` | Var |
| Sonuç (kâğıtta yok) | `bakim_sonucu` (TAMAMLANDI/UYGUNSUZLUK_VAR/…) + uygunsuzluk aksiyonu | ERP daha iyi |
| Denge/firma yetkilisi imza | `ServiceApproval` | Var |

### 4.3 Kiralama Teslim Tutanağı (2 adet)

| Kâğıt alan | ERP (`Rental`, `RentalAllocation`, `kiralama_tutanak.html`) | Durum |
|---|---|---|
| Teslim tarihi, iade tarihi, **gün sayısı**, işin adı | `baslangic`, `bitis`, `proje_adi` | Gün sayısı hesaplanabilir; PDF'e eklenmeli |
| Firma, yetkili kişi | `customer_id`, `RentalContact` (rol) | Var |
| Cihaz marka/model, adet, seri nolar | kalemler, tahsis, seri | Var |
| **Aksesuar seti** (anten/batarya/klips, şarj takımı, kulaklık, çanta) | Ayrı ürün kalemi olarak girilebilir | **Eksik:** cihaza bağlı aksesuar seti (kit) ve set bazında iade sayımı |
| Sorumluluk metni (çalınma/kırılma/kayıp bedeli tahsil edilir) | — | **Eksik:** tutanakta şart metni (ayarlardan) |
| Teslim eden / teslim alan imza | — | **Eksik:** sevk anında imza/onay kaydı (ServiceApproval benzeri) |
| İade tarihi, iade esnasındaki eksik malzeme listesi (marka, malzeme, adet, açıklama), iade eden/alan | `iade_adet`, `kayip_adet`, `RentalCheck` (UYGUN/EKSIK/ARIZALI) | Var (sayı düzeyinde); iade imzası ve eksik bedeli → fatura bağlantısı eksik |

### 4.4 Müşteri tarafından düzenlenen tutanak (5 adet)

Denge'nin müşteriden cihaz **teslim aldığı** durum (onarım/iade). ERP: `WorkshopRecord` kabulü + `atolye_kabul_fisi.html`;
müşteri belgesinin fotoğrafı ek olarak yüklenebilir. **Eksik:** "teslim alma" saha işi (TESLIM türü) — plan satırlarında
"cihazın teslim alınması" çok sık; şu an ARIZA/DESTEK'e zorlanıyor.

### 4.5 Ürün Teslim Formu (demo/değişim, 1 adet)

Alanlar: firma, ilgili kişi, telefon, adres, VD/VN, proje, **demo süresi**, talep eden, açıklama, tarih, belge no, ürün
kodu, seri no, ürün adı, birim fiyat, adet, ticari koşullar (10 gün iade; iade yoksa fatura), eksiksiz teslim eden/alan.
**ERP'de karşılığı yok** → "Emanet/Demo teslim" kaydı: iade vadesi, vade aşımı uyarısı, iade ya da faturaya dönüşüm.

### 4.6 Formlardan çıkan ERP doğrulama kuralları

- Sonuç seçilmeden iş tamamlanamaz (formların %60'ında boş).
- "Tamamlandı" + açık uygunsuzluk / "arıza giderilemedi" çelişkisi engellensin.
- Seri no: kütükle ve aynı gün e-irsaliyedeki seriyle uyuşmazlıkta uyarı (çapraz yazım örneği var) — mevcut
  `kutuk_fark_durumu` mekanizması genişletilmeli.
- Planda yazan ekip ≠ formdaki ekip → atama/zaman kaydı kaynağı tek olsun (formdaki isim elle yazılmasın).
- Güvenlik bulgusu (acil stop kırık vb.) KRİTİK uygunsuzluk olarak işaretlensin ve yönetici panosuna düşsün.

---

## 5. Rollere göre günlük işler ve test senaryoları

Rol kodları `permissions.py` ve KARARLAR_2026-11-04 §3 ile eşlendi. **Not:** `SAHA_SORUMLUSU`, `SATIS_DESTEK`,
`FINANS_YONETICI` kararlarda var ama `backend/app/permissions.py`'de henüz tanımlı değil. Haberleşme/Güvenlik ayrımı
rol değil birim üyeliğiyle yapılır. Teknik serviste "tayin" dili kullanılır.

Her senaryoda beklenen: kapsam dışı birimin/şirketin kaydı görünmez (sayı = liste), maliyet `maliyet.gor` yoksa
gizli, her değişiklik denetim izine düşer, eşzamanlı düzenlemede `version` çakışması uyarısı verilir.

### 5.1 Admin (ADMIN)
1. Yeni işe başlayan teknisyen için hesap açar, Güvenlik birimine ve Denge Elektronik şirketine üye yapar, rol paketini
   verir; kişi giriş yapınca yalnız Güvenlik işlerini görür.
2. İşten ayrılan personelin hesabını pasifler; açık tayinleri olduğu için sistem uyarır, işler başka teknisyene tayin
   edilmeden hesap kapanmaz ya da açık iş listesi raporlanır.
3. Bir kullanıcıya ikinci şapka (ör. Haberleşme satış destek) ekler; kullanıcı üst çubukta aktif rolü değiştirir.
4. Muhasebe rolünün yalnız ofis ağından girişini doğrular (ofis dışı IP reddedilir).
5. Talep takip Excel'ini içe aktarma ekranından yükler; eşleşmeyen müşteri/lokasyon satırları ayrı listede düzeltilir (§7.5).
6. Denetim izinde bir iş emrinin durum ve tayin değişikliklerini tarih sırasıyla görür.

### 5.2 TS Yöneticisi (SERVIS_YONETICI — Güvenlik veya Haberleşme)
1. Sabah Ana Panel: açık iş, SLA riskindeki işler, bugün sahadaki ekipler, bekleyen kalite onayı, "tekrar arıza aday" işler.
2. Telefonla gelen acil AVM X-Ray arızasını KRİTİK öncelikle açtırır ve ekip + aracı tayin eder; aynı gün aynı bölgedeki
   ikinci işle birleştirilmesi önerisini görür.
3. Kasım bakım dönemi için bir perakende zincirinin 9 şubesindeki 18 cihaza dönem işlerini üretir, iki ekibe 3 günlük
   tura böler (çakışma uyarısını gerekçeyle geçer).
4. "Teklif sunulacak" sonucuyla kapanan 3 arızanın teklif durumunu izler; 7 günü geçen teklif için satış destek'e hatırlatma.
5. Tekrarlayan arızalar raporunda son 12 ayda 10+ ziyaret alan AVM'yi görür, cihaz değişimi/bakım sözleşmesi önerisi için
   satışa iş bırakır.
6. Haftalık: teknisyen bazında iş/gün, mesai dışı bitiş oranı, süre kaydı "eksik" iş sayısı (0 değil, eksik).
7. Personelin izin/telafi izni (gece/şehir dışı dönüşü) kaydını planlamada müsait değil olarak görür.

### 5.3 Takım Lideri / Şef (SERVIS_SEF)
1. Ekibinin bugünkü iş listesini mobilde açar; ilk işte "yola çıktım/sahaya vardım" başlatır (konum alınamazsa
   "Konum bilgisi alınamadı").
2. Tamamlanan bakım formunu kontrol eder; doz ölçümü boş olduğu için kalite onayı veremez, teknisyene geri gönderir.
3. Kendi yaptığı işi onaylamaya çalışır → engellenir (SoD).
4. Sahada fark ettiği ikinci cihaz arızası için "sahada bildirildi" kanalıyla bağlı yeni iş açar.
5. Kiralık X-Ray iade alımında 1 roller eksik → tahsiste eksik adet girer, kontrol "EKSIK" olur.
6. (Lab takım lideri) atölyeye gelen 4 telsize tayin yapar; saha takım lideri tayin yapamaz (D3.1/D4.2 kararı).

### 5.4 Teknisyen (SERVIS_TEKNISYEN)
1. Sabah bildirimiyle günün 3 işini görür (bakım, arıza, kurulum); başka ekibin işini göremez.
2. Bakım formunda X-Ray için 13 maddeyi işaretler, kV/mA, penetrasyon, çözünürlük ve doz değerlerini girer; acil stop
   kırık → UYGUNSUZ + KRİTİK, aksiyon "teklif".
3. Arıza işinde sonuç "Servise alındı" seçer; PC kasası atölyeye gider, iş ATOLYEDE durumuna geçer.
4. Müşteri yetkilisine ekranda imza attırır; yetkili yoksa "alınamadı" + neden.
5. Bağlantı yokken (bodrum kat) saat başlat/bitir ve fotoğraf girer; bağlantı gelince kuyruk gönderilir (Faz B PWA).
6. Parça kullandığında araç stoğundan çıkış yapar; depo sonradan onaylar.
7. Mola girer; kişi-saat toplamına dahil edilmediğini görür.

### 5.5 Saha Sorumlusu (SAHA_SORUMLUSU — yeni)
1. Fuar alanında 4 X-Ray + 14 KMD'lik kiralama kurulumunu açar ve ilerlemeyi izler; tayin yapamaz.
2. Gün içinde müşteriden gelen "1 KMD alarm veriyor" talebini mevcut kiralamaya bağlı iş olarak açar.
3. Sahadaki ekiplerin hangi işte olduğunu (zaman kaydından) görür.
4. Kalite onayı düğmesini göremez/kullanamaz.
5. Etkinlik bitiminde toplama işini açar ve iade sayımını başlatır.

### 5.6 Operasyon Uzmanı (SERVIS_OPERASYON)
1. Telefon/WhatsApp/e-postayla gelen talebi kaydeder: müşteri seçer (listede yoksa "müşteri kartı talebi"), talep eden
   kişi + telefon zorunlu, bildirilen arıza, tür, öncelik.
2. Bekleyen işler listesinde "malzeme bekleniyor" işin beklenen bitiş tarihini günceller; SLA durur/devam eder.
3. Ertesi günün planını hazırlar, araç ve ekip atamasını yöneticiye öneri olarak bırakır; günlük planı PDF olarak
   gruba gönderir.
4. Müşteri talebi "ertelendi" (açık alan isteği) → plan değişim nedeni ERTELEME ile kaydedilir.
5. Kargoyla gelen arızalı KMD kafasını atölye kabulüyle kaydeder ve kabul fişi basar.
6. Gün sonu: açık/kapalı iş sayısı, süre kaydı eksik işler listesini yöneticiye özet olarak gönderir.

### 5.7 Satış (SATIS)
1. Sözleşmesi bitmek üzere olan bakım müşterilerini listeler; yenileme teklifi hazırlar (yalnız kendi biriminin fiyatları).
2. Fuar organizatörünün 20 KMD + 30 bariyer kiralama talebini teklife çevirir; aynı tarihte stok yetersizliği uyarısı görür.
3. Kabul edilen satış teklifinden kurulum işi oluşmasını tetikler (D2.2).
4. Başka birimin (Haberleşme) teklif tutarlarını göremez.
5. Tekrarlayan arıza raporundan müşteri için cihaz yenileme fırsatı açar.

### 5.8 Satış Destek (SATIS_DESTEK — yeni)
1. "Teklif sunulacak" sonucuyla gelen arıza tespitini açar, sonuç metnini okur, parça + işçilik teklifi hazırlar.
2. Teklifi müşteriye bağlantıyla gönderir; kabul gelince iş "teklif onayı bekleniyor" beklemesinden çıkar.
3. Satılan 6 X-Ray'in sevkiyat/kurulum takibini yapar (talep listesinin ikinci bölümü): irsaliye, kurulum tarihi, durum.
4. Demo ürün teslim kaydı açar (10 gün iade vadesi) — ERP'ye eklenince.
5. Servis kayıtlarını görür ama tayin yapamaz, maliyet göremez.

### 5.9 Finans Yöneticisi (FINANS_YONETICI — yeni)
1. Faturalanacaklar listesinde (fatura devri) kalite onaylı ve sonuçlanmış işleri dönem bazında görür, devri onaylar.
2. Bakım sözleşmesinde ziyaret başı ücretle tamamlanan dönemleri faturalanacak olarak işaretler.
3. Kiralama iadesinde eksik/hasar bedeli satırını faturaya ekler.
4. İş bazlı kârlılık (parça + kişi-saat + yol) raporunu görür (maliyet görünür).
5. Ofis dışı ağdan giriş denemesi reddedilir.

### 5.10 Finans Uzmanı (MUHASEBE_DESTEK, ad: Finans Uzmanı)
1. Faturalanacaklar listesini dışa aktarmadan görüntüler; Logo'ya girer, ERP'de "iletildi" işaretler.
2. Maliyet ve kârlılık alanları gizlidir (G4.4).
3. Tahsilat girişini yapar; servis raporu dışa aktarma yetkisi yoktur (M13.4).
4. Geri alma (iletildi → bekleyen) yalnız gerekçeyle yapılır ve denetim izine düşer.

### 5.11 Depo Uzmanı (SERVIS_DEPO / KIRALAMA_DEPO)
1. Gelen 6 X-Ray'i sandıktan çıkarma/test işiyle depoya alır; seri numaralarını kütüğe "kurulum bekliyor" olarak kaydeder.
2. Teknisyenin araç stoğundan yaptığı parça çıkışını onaylar.
3. Kiralama için 5 X-Ray + roller hazırlığını kontrol eder (HAZIR), sevk eder; iadede UYGUN/EKSIK/ARIZALI işaretler.
4. Yedek parça stok sayımı açar, farkları onaylar.
5. Kritik stok altındaki X-Ray yedek parçaları için sipariş listesi çıkarır.

### 5.12 Üst yönetim (YONETIM — salt okunur; GMY "yönetim özeti")
1. Ana Panel: birim bazında açık/sahada/atölyede/tamamlanan, SLA uyumu, bekleyen onaylar, bu ay planlı bakım
   tamamlanma oranı.
2. Yıllık/aylık eğilim: saha iş hacmi iş tipine göre, şehir dışı oranı, araç-km.
3. Kârlılık özeti (maliyet görünür) ve büyük müşteri bazında iş/fatura.
4. Hiçbir kaydı düzenleyemez; dışa aktarma ayrı yetkiyle.

---

## 6. ERP için çıkarımlar — öncelikli eksik/düzeltme listesi

Öncelik sırası CLAUDE.md'ye göre: yeni modül/özellik → mevcut eksik → güvenlik/üretime hazırlık; G1.9 (sade ekran)
her maddede geçerli.

**Y1 – Yeni rollerin tanımı (SAHA_SORUMLUSU, SATIS_DESTEK, FINANS_YONETICI).** Kararlarda var, `permissions.py`'de yok;
§5 senaryoları bunlara dayanıyor. Migration + rol paketi + test.

**Y2 – Bakım formunda sayısal ölçümler.** kV, mA, penetrasyon (mm), çözünürlük (AWG), doz oranı (yan panel/tünel, µSv/h),
şebeke voltajı, topraklama; KMD için standart test sonucu ve sayaç. Gerekçe: kâğıt formların %84'ünde kV/mA dolu,
doz yalnız %5'inde (radyasyon güvenliği riski). Şablon maddelerini kâğıt formla hizala (yazılım sürümü, TAEK/lisans
geçerliliği, jeneratör yağ kaçağı/ses, FAA testi). Şablon sürümlenmiş olduğu için eski formlar bozulmaz.

**Y3 – Yeni iş türleri: TESLIM (teslim etme/teslim alma), EGITIM (müşteri kullanıcı eğitimi), TASIMA (nakliye).**
Gerekçe: Teslim/İade 3.333 saha satırı, "eğitim" 835 satır; kâğıt formda "nakliye" kutusu; Set Bariyer kararı TASIMA'yı
istiyor. CHECK listesi migration'la genişletilir.

**Y4 – Günlük plan çıktısı.** Planlama ekranından tarih seçip ekip/araç/iş/saat listesini PDF (ve paylaşılabilir görsel)
üret. Gerekçe: bugünkü işleyişin merkezi (WhatsApp'a atılan plan görseli); geçişte iki sistem paralel çalışacak (G1.6).

**Y5 – Demo/emanet teslim kaydı.** İade vadesi, vade aşımı uyarısı, iade/faturaya dönüşüm, Ürün Teslim Formu PDF'i.

**Y6 – Kiralama tutanağının tamamlanması.** Aksesuar seti (kit), gün sayısı, sorumluluk şartı metni (ayarlardan),
teslim/iade imzası, eksik/hasar bedelinin fatura devrine bağlanması.

**Y7 – Satış siparişinden kurulum takibi (D2.2'nin ilk adımı).** Talep listesinin yarısı satılan ürün → kurulum takibi.
Faz C beklenirken: teklif kabulünden KURULUM işi + kütükte "kurulum bekliyor" ekipman.

**Y8 – Rota/birleştirme önerisi.** Planlamada aynı il/ilçeye 7 gün içindeki açık işleri öner. Gerekçe: 254 sefer,
≈125 bin km. Basit kural tabanlı; harita entegrasyonu gerekmez.

**E1 – Kapanış doğrulamaları.** Sonuç zorunlu; "tamamlandı" ile açık KRİTİK uygunsuzluk/"çözülemedi" çelişkisi engel;
ARIZA'da bildirilen arıza zorunlu; seri no kütük/irsaliye farkı uyarısı.

**E2 – Basılı form no alanı ve PDF alt bilgisi.** Paralel dönemde kâğıt form numarası iş emrine yazılsın (tekillik
uyarısı); `servis_formu.html` belge kodu (PR.07-FR.08/00) ve "20 iş günü / 90 gün" şartını bassın; başlangıç–bitiş
saatini zaman kayıtlarından göstersin.

**E3 – "Servise alındı" ve "Servis iptal" sonuçlarının mobil ekranda kâğıttaki adlarıyla sunulması** (eşleme var,
kullanıcı dili yok). Atölye için 20 iş günü hedefi ve 90 gün teslim alınmadı uyarısı.

**E4 – Plan dışı işin hızlı kaydı.** Mobilde "sahada bildirildi" ile 3 alanlı hızlı iş açma (müşteri, konu, seri);
gerekçe 2.372 planda olmayan bildirim. Bitiş kanıtı: tamamlamada fotoğraf veya imza zorunluluğu iş türüne göre ayar.

**E5 – Telafi izni nedeni.** `ServiceUnavailability.tur`'a TELAFI (gece/hafta sonu/şehir dışı dönüşü); planlama
müsaitliğinde görünür. Bordro değildir (CLAUDE.md).

**E6 – Talep takip listesinin içe aktarılması** (§7.5 eşlemesi) — mevcut `IceAktarmaPage` + göç altyapısı üzerine.

**E7 – Mevsimsel kapasite görünümü.** Ekim/Haziran/Ağustos yoğunluğu için haftalık iş yükü × kişi müsaitliği
(bakım dönemlerini sakin aylara kaydırma önerisi).

**G1 – KVKK.** İçe aktarılacak kaynaklarda müşteri yetkili adı/telefonu, personel adı, plaka, WhatsApp metinleri var:
içe aktarma yalnız gerekli alanları alsın; WhatsApp mesaj metni ve fotoğrafları ERP'ye toplu taşınmasın (yalnız form
görseli, iş emrine ek olarak, saklama süresiyle). Teknisyen performans verisinin prim için kullanımı aydınlatma metnine
eklenmeli (G8.4).

**G2 – Araç kullanımı.** `ServiceVehicle`'da km/yakıt yok; araç-gün ve km raporu idari işler fazına (Faz C) kadar
plan kayıtlarından tahmini hesaplanabilir.

---

## 7. Güvenlik Sistemleri talep takip listesi (26.10.2026)

### 7.1 Yapı

Tek sayfa "Müşteri Talepleri", 71 dolu satır, 11 sütun. İki farklı liste aynı sayfada:
- **A bölümü (≈41 satır):** müşteri talepleri — bakım, arıza tespiti/onarımı, kurulum/teslim, eğitim, depo işleri.
- **B bölümü (≈30 satır):** satılan cihaz kalemleri (ör. "2 adet X-Ray; 2 giriş roller; 2 çıkış roller; 1 KMD") ve
  teslim/kurulum durumu; çoğunda talep tarihi ve durum yok. Bir satır yurt dışı sevkiyat.

Dosya adı 26.10 tarihli olmakla birlikte durum sütununda 03.11.2026'ya kadar işlenmiş sonuçlar var; liste canlı
tutuluyor.

### 7.2 Sütunlar, doluluk ve ERP eşleşmesi

| Sütun | Dolu | ERP alanı | Not |
|---|---:|---|---|
| TALEP TARİHİ | 23/71 | `reported_at` | Boşsa içe aktarmada "bilinmiyor"; SLA başlangıcı GERIYE_DONUK/ölçülemedi |
| MÜŞTERİ / FİRMA | 71 | `customer_id` (eşleme) / `customer_name_raw` | Aynı müşteri farklı yazımlarla (ör. "… / şube") |
| LOKASYON | 64 | `address_id` / `location_raw` | Çoğu yalnız "İstanbul Anadolu/Avrupa yakası" veya il |
| ARAÇ | 18 | `ServicePlan.vehicle_id` / `legacy_vehicle_text` | "Hava yolu" gibi değerler araç değil, ulaşım türü |
| PERSONEL | 35 | `ServicePlanMember` / tayin | Çoklu ad, ayraç tutarsız |
| TALEP DETAYI | 71 | `konu` (≤200) + `aciklama` | Adet ve model içeriyor ("6 adet SC-5030A bakımı") |
| YETKİLİ KİŞİ | 0 | `contact_id`, `iletisim_ad` | Hiç dolu değil — ERP'de zorunlu (M1.2) |
| YETKİLİ İLETİŞİM | 0 | `iletisim_telefon` | Hiç dolu değil |
| PLANLANAN TARİH | 51 | `ServicePlan.plan_date` | Metin değerler: aralık ("26-31.10"), "henüz belirlenmedi" |
| DURUM | 59 | `status` | §7.3 |
| NOT / AÇIKLAMA | 27 | `ServiceResult.yapilan_islem` veya olay NOT / bekleme açıklaması | Sonuç, bekleme nedeni ve bulgu karışık |

**ERP'de var, listede olmayan:** iş türü, öncelik, talep kanalı, seri no, sonuç kodu, SLA, bekleme nedeni, kalite
onayı, müşteri imzası. **Listede var, ERP'de zayıf olan:** satılan ürün kalemi bazında kurulum takibi (Y7), ulaşım
türü (havayolu/toplu taşıma — plan notu olarak tutulabilir).

### 7.3 Talep türleri ve durum dağılımı

| Tür (detaydan sınıflandırma) | Boş | Beklemede | Devam ediyor | Ertelendi | Planlandı | Tamamlandı | Toplam |
|---|---:|---:|---:|---:|---:|---:|---:|
| Bakım | – | – | 1 | – | 5 | 12 | 18 |
| Arıza tespiti/onarım | – | 4 | 1 | – | 2 | 5 | 12 |
| Teslim/kurulum | – | 1 | 1 | 1 | – | 5 | 8 |
| Eğitim | – | – | – | – | 1 | – | 1 |
| Satılan cihaz kalemi (B bölümü) | 12 | – | – | – | 5 | 13 | 30 |
| Diğer (depo test/sevkiyat hazırlığı) | – | – | – | – | 1 | 1 | 2 |
| **Toplam** | **12** | **5** | **3** | **1** | **14** | **36** | **71** |

- Kapalı (tamamlandı) 36 (%51); açık 23 (planlandı 14, beklemede 5, devam ediyor 3, ertelendi 1); durumsuz 12.
- **Bekleme süreleri:** talepten planlanan tarihe medyan 11 gün (ortalama 10,4; en çok 25; n=19). 26.10.2026 itibarıyla
  açık ve tarihli 11 talebin yaşı medyan 11 gün, en eskisi 35 gün (yurt dışı limanda konveyör teslimi).
- **Bekleme nedenleri (not sütunu):** parça temini (ekran kartı, kapı dedektörü kafası), kargo yolunda parça, müşteri
  sahası hazır değil (elektrik yok / yer değişikliği), müşteriye ait parçanın onarılabilirlik kararı.

### 7.4 Sorumlu roller

- Listeyi Güvenlik operasyon uzmanı/satış destek tutuyor (talep girişi, planlanan tarih, durum).
- Tayin ve plan TS yöneticisi; personel sütunu ekip (1–4 kişi, sıklıkla şehir dışı turlarında 2–3 kişi).
- Sonuç notunu teknisyen/ekip yazıyor ("bakımı yapıldı", "arıza tespiti yapıldı forma işlendi").
- B bölümü satış + satış destek + depo (sevkiyat hazırlığı) ortak listesi.

### 7.5 İçe aktarma eşlemesi önerisi

1. **Bölüm ayırımı:** satırda adet+model listesi var ve talep tarihi yoksa B (satış kalemi), değilse A.
2. **A bölümü → `ServiceOrder`** (birim GUVENLIK, kategori GUNLUK_SERVIS; `talep_kanali=DIGER`; `sla_kaynak=GECIS`):
   - Tür: "bakım" → PLANSIZ_BAKIM (sözleşmeli müşteri ise ilgili dönemin PB işi ile eşleştir); "arıza/tespit/tamir/
     değiştir" → ARIZA; "kurulum/montaj/teslim" → KURULUM (Y3 sonrası TESLIM); "eğitim" → DESTEK (Y3 sonrası EGITIM);
     depo test/sevkiyat → DESTEK + not.
   - **1 cihaz = 1 PB iş emri / arızada tek cihaz:** "6 adet cihaz bakımı" satırı 6 iş emrine bölünür; seri no
     bilinmediği için seri boş + "seri bekleniyor" uyarısı; ziyaret (`ServiceVisit`) ile gruplanır.
   - Durum: TAMAMLANDI → TAMAMLANDI + `ServiceResult(sonuc=COZULDU, yapilan_islem=NOT, cozum_kanali=YERINDE)`
     (kalite onayı yok, süre kaydı "eksik"); PLANLANDI → PLANLANDI + `ServicePlan`; DEVAM EDİYOR → notta parça/eksik
     varsa BEKLEMEDE(MALZEME), yoksa ISLEMDE; BEKLEMEDE → BEKLEMEDE, neden nottan (MALZEME / MUSTERI_ERISIMI /
     MUSTERI_ONAYI / DIS_SERVIS), yoksa DIGER + açıklama; ERTELENDİ → PLANLAMADA + plan değişimi ERTELEME (neden
     müşteri kaynaklı); boş → MUSTERI_TALEBI.
   - Planlanan tarih: tarih → `plan_date`; aralık → başlangıç günü + plan notu; "belirlenmedi" → plan yok.
   - Personel → kullanıcı eşleme tablosu (ad eşleme servisi `ad_esleme.py`); eşleşmeyen ad uydurulmaz, plan notuna yazılır.
   - Araç → plaka anahtarıyla `ServiceVehicle`; "hava yolu/toplu taşıma" → `legacy_vehicle_text`.
   - Yetkili kişi/telefon boş → içe aktarmada M1.2 zorunluluğu **göç kaynağı için gevşetilir**, iş "iletişim eksik"
     veri kalitesi uyarısı alır (`veri_kalitesi.py`).
3. **B bölümü → satış kurulum takibi:** her satır için müşteri + `ServiceEquipment` kayıtları (tür/model, adet kadar,
   `lifecycle_status=KURULUM_BEKLIYOR`, seri boş) ve durum tamamlandı/planlandı ise KURULUM işi; durumsuz satırlar yalnız
   ekipman "kurulum bekliyor" olarak gelir. Yurt dışı satır: kurulum işi açılmaz, not.
4. **Eşleşmeyen müşteri:** müşteri kartı açılmaz (G10.2); `customer_name_raw` ile gelir ve "müşteri kartı talebi"
   listesine düşer.
5. **Denetim:** her içe aktarılan kayıt `ImportBatch` ile işaretlenir; geri alınabilir; deneme önce kopya veritabanında.

### 7.6 Rol test senaryoları için gerçekçi örnekler (kişisel veri yok)

- Operasyon: "Yurt dışı bir limandaki müşteriye hazırlanan konveyör bandı teslim edilecek; kılavuzun teslim alınması
  bekleniyor" → BEKLEMEDE (MUSTERI_ERISIMI), planlanan tarih aralığı.
- Operasyon/atölye: "Enerji şirketindeki X-Ray'in bilgisayar kasası atölyede onarıldı, kargoyla gönderildi; müşteriye
  ulaşınca uzaktan kurulum" → ATOLYE kaydı + DIS_SERVIS/kargo beklemesi + UZAKTAN çözüm.
- TS yöneticisi: "Perakende zincirinin 9 şubesinde 18 adet SC-5030A bakımı, iki ekip, 3 gün" → 18 PB iş emri, 2 ziyaret
  turu, araç tayini.
- Teknisyen: "Bakımda dedektör leke atıyor/atlama yapıyor" → bakım sonucu UYGUNSUZLUK_VAR, aksiyon ARIZA_IS_EMRI.
- Teknisyen: "Konsolosluktaki KMD arıza tespiti yapıldı" → sonuç TEKLIF_SUNULACAK; satış destek teklif hazırlar.
- Teknisyen: "AVM'de X-Ray jeneratörü değiştirildi; not: anakart donma yapıyor" → COZULDU + yeni bağlı iş (BAKIM_BULGUSU).
- Saha sorumlusu: "Okula sıfır X-Ray + KMD bırakıldı, elektrik olmadığı için kurulum yapılamadı" → KURULUM BEKLEMEDE
  (MUSTERI_ERISIMI), ekipman KURULUM_BEKLIYOR.
- Operasyon: "Ortaokula 2 KMD teslimi ertelendi, müşteri açık alana kurulum istedi" → plan ERTELEME, keşif işi önerisi.
- Depo: "6 X-Ray sandıktan çıkarılıp test edildi, sevkiyata hazırlandı" → depo girişi + kütük KURULUM_BEKLIYOR.
- Satış destek: "Banka genel müdürlüğüne satılan 6 X-Ray + roller; 2'si kuruldu, 4'ü müşterinin kendi alanı hazır olunca"
  → 6 ekipman, 2 kurulum işi tamamlandı, 4'ü bekliyor.
- Atölye/satış destek: "Müşteriye ait klavye serviste; tamir edilebiliyorsa fiyat verilecek" → ATOLYE + MUSTERI_ONAYI
  beklemesi + teklif.
- Finans: "Ekim bakım turunun 9 şubesi tamamlandı" → dönem kapanışı, ziyaret başı ücretle faturalanacaklar.
