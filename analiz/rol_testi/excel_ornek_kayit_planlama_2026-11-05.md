# Excel'lerden örnek kayıt açma ve toplu planlama denemesi (2026-11-05)

Ortam: yerel deneme (`denge-erp-deneme`, 0189424), http://127.0.0.1:5173. Canlıya dokunulmadı.
Kayıtlar API üzerinden, gerçek uçlardan geçerek açıldı. Betikler oturumun geçici çalışma klasöründe duruyor (`kayit_aktarim/aktar.py`, `kiralama.py`, `planla.py`).
Kişi verisi aktarılmadı:
- irtibatlar kurgusal ("Tesis Yetkilisi (örnek)");
- iş planındaki personel ve araç bilgisi alınmadı.

## 1. Açılan kayıtlar

| Kaynak | Bölüm | Ne açıldı |
|---|---|---|
| BAKIMLAR_2026-2027.xlsx + X-RAY KÜTÜK | Güvenlik | 5 bakım sözleşmesi. Her X-Ray ve kapı dedektörü ayrı ekipman olarak açıldı (54 cihaz); her cihaz sözleşme kalemine bağlandı. Güncel dönem için her cihaza 1 PB açıldı: PB-…141 – PB-…194. |
| Guvenlik_Talep_Takip | Güvenlik | Zonguldak Eren Enerji (arıza), Esan Balya Eczacıbaşı (kapı arızası + X-Ray eğitimi, 2 ayrı iş), Kıbrıs Girne Limanı (konveyör kurulumu), KİPA Derince (bakım). İş no 195–199. |
| Denge_Is_Plani (Ekim 2026) | Haberleşme | İGDAŞ araç telsizi arızası, TP-OTC Filyos telsiz sistemi arızası, BUSKİ telsiz kurulumu (araç + sabit telsiz, 2 ayrı iş), Halkbank Gaziantep telsiz bakımı. İş no 200–204. |
| Denge_Is_Plani (Ekim 2026) | Kiralama | KÜÇÜKPRENS OKULLARI: 1 X-Ray + 1 kapı dedektörü (Güvenlik, KIR-…001). ESAS GRUP GÜVENLİK: 50 telsiz (Haberleşme, KIR-…002). Her biri için toplama işi açıldı (205, 206). |

Bakım sözleşmeleri:

| Tesis | Müşteri | Cihaz | Yıllık bakım | PB dönemi |
|---|---|---|---|---|
| PİAZZA SAMSUN AVM | MEL 2 GAYRİMENKUL | 3 X-Ray + 6 kapı | 3 | Eylül 2026 (gecikmiş) |
| ANKARA OPTİMUM AVM | KURTKÖY GAYRİMENKUL | 4 + 4 | 3 | Eylül 2026 |
| KADIKÖY BELEDİYESİ | KADIKÖY BELEDİYE BAŞKANLIĞI | 5 + 5 | 2 | Temmuz 2026 |
| HİLLTOWN AVM | TARABYA GAYRİMENKUL | 8 + 13 | 3 | Aralık 2026 |
| HİLLTOWN AVM OFİS | TARABYA GAYRİMENKUL | 3 + 3 | 3 | Aralık 2026 |

Kütükte bu tesisler için yalnız 2 seri no bulundu: Ankara'da bir X-Ray, Kadıköy'de bir kapı dedektörü. Diğer cihazlar seri nosuz açıldı, notlarına "sahada tamamlanacak" yazıldı. Seri no metin olarak tutuluyor ve sonradan girilebilir.

## 2. Planlama denemesi

Sonuç: 12/12 senaryo beklendiği gibi.

| No | Senaryo | Sonuç |
|---|---|---|
| 1 | Aynı firmanın iki lokasyonu (Hilltown AVM + Ofis) birlikte toplu plan | 409 PLAN_KURAL "farklı lokasyonlarda" ✔ |
| 2 | Hilltown AVM'deki 21 cihazın PB'si tek ziyarette (şef + 2 teknisyen, 01.12.2026 08:00) | 201, ZYR-202612-000022 ✔ |
| 3 | Aynı ekip aynı saatte Ofis'e | 409 PLAN_CAKISMA ✔ |
| 4 | Ofis'teki 6 PB aynı gün 13:30 | 201, ZYR-202612-000023 ✔ |
| 5 | Geçmiş tarihe gerekçesiz plan | 409 GECMIS_TARIH ✔ |
| 6 | Gecikmiş Samsun PB'leri (9) 10.11.2026 tarihine | 201 ✔ |
| 7 | Esan Balya'da aynı lokasyon, farklı tür (arıza + eğitim) | 201 ✔ |
| 8 | Kiralama toplama işinin tek başına planı | 200 ✔ |
| 9 | Teknisyen toplu plan yapmaya çalışır | 403 (servis.planla) ✔ |
| 10 | Güvenlik şefi Telekom'daki BUSKİ işini planlar ya da açar | 404 ✔ |
| 11 | Haberleşme şefi BUSKİ'deki 2 telsiz işini toplu planlar | 201 ✔ |
| 12 | Haberleşme şefi Güvenlik ekibiyle plan yapmaya çalışır | 400 "kullanıcı bulunamadı" ✔ |

Teknisyenin iş listesinde yalnız kendi atandığı ya da ekibinde olduğu işler var (KENDI_ISLERI), sızıntı yok.

Ekran kontrolü (Servis Planlama, Güvenlik şefi):
- Plansız havuz "Müşteri / Tesis" kartlarına gruplanıyor.
- Kart başlığındaki kutu o lokasyonun bütün işlerini seçiyor.
- "Toplu Planla (n)" düğmesi "Toplu Plan ve Tayin" penceresini açıyor.

## 3. Bulgular

| No | Önem | Tür | Konu | Öneri |
|---|---|---|---|---|
| E1 | YÜKSEK | veri | Aynı adlı müşteri ikinci kez uyarısız açılabiliyor. ESAN BALYA ECZACIBAŞI ve KİPA AVM, önceki rol testinden kalan kayıtların yanında ikinci kez oluştu. Mükerrer kontrolü yalnız vergi numarasına bakıyor. Sonuç: havuzda aynı firma iki grup olarak görünüyor ve tek ziyarette planlanamıyor. | Hesap açılışında normalize edilmiş ad eşleşmesine 409 + mevcut liste + gerekçeli onay (vergi numarası kontrolündeki akışın aynısı). |
| E2 | ORTA | akış | Telsiz ve röle cihazları bakım sözleşmesine giremiyor; kapsam yalnız XRAY ve KAPI_DEDEKTORU kabul ediyor. Oysa iş planında Halkbank telsiz yıllık bakımı ve Esenler Belediyesi aylık bakımı gibi periyodik Haberleşme bakımları var. Şimdilik plansız bakım olarak açıldı. | Haberleşme birimi için TELSIZ, ROLE_TEKRARLAYICI ve TELSIZ_DIGER bakım kapsamına eklensin. |
| E3 | DÜŞÜK | UX | Toplu plan penceresi şef ve teknisyeni "opsiyonel" gösteriyor, oysa sunucu sahaya giden en az bir kişi istiyor. Süre, iş sayısından bağımsız olarak 60 dk geliyor. Sorumlu seçimi yok, ilk teknisyen sorumlu oluyor. | Etiketleri düzelt, sorumlu seçimi ekle (bilinen eksik). |
| E4 | DÜŞÜK | akış | Kiralama "TALEP" aşamasındayken, yani henüz hiçbir cihaz tahsis ya da sevk edilmemişken, toplama işi açılıp planlanabiliyor. Müsaitlik denetimi tahsis aşamasında yapılıyor; bu doğru. | Toplama işini sevkten sonra açtır, ya da uyarı göster. |
| E5 | bilgi | veri | Kütükte firma adları tesis adlarıyla birebir eşleşmiyor ve bakım listesindeki cihazların çoğunun seri nosu yok. | Seri nolar ilk bakım ziyaretinde sahada toplanmalı. Bakım formu buna uygun. |
