# M14 — Müşteri, Lokasyon ve Sözleşme Ana Verisi · Gereksinim Tasarımı

> **Sürüm tabanı:** DengeERP V1.20.1 (kaynak salt okunur incelendi: `kaynak/V1_20_1_orijinal/DengeERP.Api`)
> **Tarih:** 21.10.2026 · **Kapsam:** Yalnızca teknik servis. Logo CRM / Flowick entegrasyonu kapsam dışı.
> **Öncelik ilkesi:** (c) yeni özellik → (b) mevcut eksik → (a) güvenlik/üretim. Veri kaybı yaratan hata ayrıca **KRİTİK** işaretlidir.
> **Rol önerileri varsayımdır**; organizasyon şeması geldiğinde gözden geçirilecek.

İlgili diğer tasarımlar: `01_is_emirleri`, `03_cihaz_kutugu` (M03-03, M03-09), `04_planli_bakim` (M04-02, M04-03, M04-04), `05_haberlesme_atolye`, `06_kiralama_depo`, `07_teklif_maliyet`, `10_operasyon_sla`. Bu modül **sözleşmenin içeriğini (dönem, frekans, cihaz kapsamı) yeniden tasarlamaz** — o iş M04-03'tedir. Bu modül sözleşmenin **kime (cari) ve nereye (lokasyon) ait olduğunu** tanımlar.

---

## 1. Mevcut durum (kodda ne var?)

### 1.1 Özet

Sistemde **müşteri, lokasyon veya irtibat ana tablosu yok.** Müşteri adı her modülde ayrı bir serbest metin kolonu olarak tutuluyor ve modüller arasındaki tek bağ **metnin birebir aynı yazılmış olması**. Lokasyon da serbest metin; il/ilçe/adres/saha yetkilisi yalnızca plan kaydında (her planda yeniden) tutuluyor. İrtibat kişisi yalnızca kiralamada çoklu ve yapısal.

### 1.2 Tablolar (müşteri/lokasyon/irtibat taşıyan kolonlar)

| Tablo | Kaynak | Müşteri / lokasyon / irtibat kolonları | Not |
|---|---|---|---|
| `WorkOrders` | `Database/DengeERP_Update.sql:4-31` | `CustomerName NVARCHAR(250) NOT NULL`, `ProjectName`, `Location`, `CustomerEmail` | Müşteri kimliği yok; telefon/irtibat yok. |
| `WorkOrderPlans` | `Database/ZZ_V111_PlanSites.sql:1-25` | `SiteName, SiteCity, SiteDistrict, SiteAddress, SiteArea, SiteContact, SitePhone, SiteDirections` | Her plan kaydında yeniden yazılıyor; bir sonraki ziyarette tekrar girilmesi gerekiyor. |
| `Offers` | `Database/DengeERP_Update.sql:189-213` | `CustomerName NOT NULL`, `CustomerEmail` | |
| `RentalOrders` | `Database/DengeERP_Update.sql:310-342` | `CustomerName NOT NULL`, `CustomerEmail`, `ProjectName`, `Location`, `ContactName`, `ContactPhone` | |
| `RentalOrderContacts` | `Database/ZZ_V112_RentalInventoryOperations.sql:19-31`, aktarım `:103-107` | `ContactType, FullName, JobTitle, Phone, Email` | Sistemdeki **tek yapısal irtibat** tablosu; ama kiralamaya bağlı, müşteriye değil. |
| `SecurityDevices` | `Database/DengeERP_V15_Schema.sql:3-24` | `CustomerName`, `Location`, `ContactName` | Excel'den aktarıldı (1.324 satır). |
| `MaintenanceContracts` | `Database/DengeERP_V15_Schema.sql:31-52` | `CustomerName NOT NULL`, `CurrentAddress` | Aşağıda 1.4: `CurrentAddress` fiilen **cari/ticari unvan** tutuyor. |
| `MaintenanceDeviceItems` | `Database/DengeERP_V17_Schema.sql:4-19` | `SecurityDeviceId` (FK) | Cihaz kimliği bağı var ama müşteri eşleşmesiyle dolduruluyor (1.3). |
| `WorkshopTickets` | `Database/DengeERP_V15_Schema.sql:78-127` | `CompanyName NOT NULL`, `CompanyAddress`, `ContactName`, `CustomerEmail`, `CustomerPhone` | Atölye kendi müşteri alanlarını tutuyor. |

### 1.3 API uçları ve iş kuralları

| Uç / fonksiyon | Kaynak | Müşteri/lokasyon davranışı |
|---|---|---|
| `POST /api/workorders` | `Program.cs:370-430`, istek kaydı `:3814` | `CustomerName` doğrudan yazılıyor; boşluk/uzunluk/tekrar kontrolü yok (yalnız ön yüzde `required`). |
| `GET /api/workorders/{id}/site-suggestion` | `Program.cs:619-647` | Saha önerisi: cihaz kütüğünü `sd2.CustomerName = w.CustomerName AND sd2.SerialNo = w.SerialNo` ile **metin eşleşmesiyle** buluyor (`:633`); il/ilçe/telefon her zaman `null` (`:643-645`); irtibat olarak `SecurityDevices.ContactName` dönüyor. |
| `POST /api/offers` | `Program.cs:800-880`, `:831`, kayıt `:3837` | Müşteri serbest metin. |
| `POST/PUT /api/rentals` | `Program.cs:1051-1200` (`:1059` yalnız boş kontrolü, `:1176` güncelleme), kayıt `:3849-3850` | Müşteri ve irtibat serbest metin + `RentalOrderContacts`. |
| `GET /api/security/devices` | `Program.cs:2232-2285` | `CustomerName/Location` üzerinde `LIKE` araması. |
| `GET /api/maintenance/contracts` | `Program.cs:2288-2345` | Fiyat alanları `finance.prices.view` yoksa API'de `null` (`:2329-2333`) — doğru. Sözleşmeyi düzenleyen uç yok. |
| Bakım iş emri üretimi | `Program.cs:2895-2982`, `:2986-3102` | Sözleşmeye ait cihazlar `SecurityDevices WHERE CustomerName=@Customer` ile bulunuyor (`:3010-3016`). Bulunamazsa cihaz kalemi seri no/bölge/`SecurityDeviceId` **boş** açılıyor (`:3032`, `:3040-3042`). PB iş emrinin `Location`'ı = cihaz lokasyonu ya da `CurrentAddress` (`:3088`). |
| `POST /api/maintenance/workorders/{id}/form` | `Program.cs:2445-2557` | Kapanışta `WorkOrders.Location = COALESCE(@Zone, Location)` (`:2519`) — **iş emrinin lokasyonu, cihazın bina içi bölgesiyle eziliyor.** Teknisyenin girdiği seri no cihaz kütüğüne geri yazılmıyor. |
| `POST/PUT /api/workshop/tickets` | `Program.cs:2628-2706`, `:2757-2769` | Atölye kaydı kendi `CompanyName`'i ile `WorkOrders` açıyor/güncelliyor (iş emrinde müşteri adı yalnız buradan değiştirilebiliyor). |
| Excel raporu | `Program.cs:2191-2230` (müşteri filtresi `Contains`, `:2212`), "Müşteri Lokasyon" sayfası `:3706-3709` | Gruplama `CustomerName` metni + `SiteName/Location` metni ile; yazım farkı = ayrı müşteri. |
| Operasyon merkezi | `OpsSuite.cs:32-33, 85, 93, 233, 263` | Uyarı, liste, tekrar arıza (seri no bazlı, `:93`), maliyet ve CSV'de `CustomerName` metni. Müşteri/lokasyon bazında tekrar arıza yok. |
| İş emrinde müşteri düzeltme | — | Genel `PUT /api/workorders/{id}` yok; yanlış yazılan müşteri adı (atölye dışında) düzeltilemiyor. |

### 1.4 Ön yüz (app.js)

| Ekran | Kaynak | Davranış |
|---|---|---|
| Yeni iş kaydı formu | `wwwroot/app.js:296-301`, gönderim `:1951` | "Müşteri *", "Müşteri E-posta", "Proje", "Lokasyon" düz `input`; öneri/otomatik tamamlama (`datalist`) yok, telefon/irtibat alanı yok. |
| İş listesi arama | `app.js:275` | Metin içinde arama. |
| Cihaz kütüğü arama | `app.js:549` | Metin içinde arama. |
| Atölye formu | `app.js:692-695` | "Firma *", "Kişi", e-posta, telefon serbest metin. |
| Kiralama formu | `app.js:874-877`, `:900`, `:926` | "Müşteri *", "Lokasyon / Etkinlik Adresi" serbest metin, çoklu irtibat. |
| Teklif formu | `app.js:1888` civarı | İş emri seçilirse müşteri adı oradan; değilse serbest metin. |
| Müşteri ekranı | — | **Yok.** Müşteri/lokasyon listesi, kartı veya geçmişi gösteren bir menü yok. |

### 1.5 İzinler

Müşteri ana verisine özgü izin yok. Müşteri bilgisi, ilgili modülün görüntüleme izniyle (`workorders.view`, `rentals.view`, `devices.view`, `maintenance.view`, `workshop.view`, `offers.view`) birlikte geliyor. Birim filtresi (`AllowedUnits`) uygulanıyor; müşteri bazında filtre yok.

### 1.6 Veri kalitesi — seed verisi üzerinden ölçüm

`Database/DengeERP_V15_Seed.sql` üzerinde salt okunur sayım yapıldı (**canlı SQL değil**; canlıda kullanıcılar düzeltmiş olabilir, aynı sorgu SSMS'te tekrarlanmalı):

| Bulgu | Değer | Etki |
|---|---:|---|
| Cihaz kütüğü satırı | 1.324 | |
| Cihazdaki farklı müşteri adı | 507 (112 satırda müşteri **boş**) | Aynı firma farklı yazımlarla: `G4S ELEKTRONIK SISTEMLERI A.S.` / `G4S ELEKTRONİK SİSTEMLERİ ANONİM ŞİRKETİ`; `ÇEKMEKÖY BELEDİYE BAŞKANLIĞI` / `ÇEKMEKÖY BELEDİYESİ`; `DORUK TİCARİ ... A.Ş.` / `... ANONİM ŞİRKETİ`; `BARKODES ...` 3 farklı yazım. |
| Cihaz `Location ≠ CustomerName` | 1.037 satır | Müşteri kolonu çoğunlukla **satın alan firma/bayi**, `Location` ise **kurulu tesis**. Çok sayıda kayıt bayi/entegratör ("… ÜZERİNDEN", "SECURİTAS AVMLERİ"). |
| Bakım sözleşmesi | 87 | |
| Sözleşme `CustomerName` cihaz kütüğünde **birebir** bulunan | **1 / 87** (yalnız "İSTANBUL TİCARET ODASI") | Örn. sözleşme `AKYAKA AVM` ↔ kütük `AKYAKA PARK AVM`; `KENTPARK AVM` ↔ `KENT PARK AVM`; `GAZİANTEP PRİMEMALL AVM` ↔ `GAZİANTEP PRİMALL AVM`; `İZMİR OPTİMUM AVM` ↔ `İZMİR OPTİMUM`. Sonuç: bakım üretiminde (`Program.cs:3010-3016`) 86 sözleşmenin PB iş emirleri **seri no, bölge ve cihaz kimliği olmadan** açılır. |
| Sözleşmede `CustomerName` ↔ `CurrentAddress` anlamı | `CustomerName` = **tesis** (PİAZZA İSTANBUL AVM), `CurrentAddress` = **cari unvan** (SALACAK GAYRİMENKUL) | Kolon adı "adres" ama içerik fatura carisi; PB iş emrine lokasyon olarak cari unvanı yazılabiliyor (`:3088`). |
| Mükerrer/çakışan sözleşme | `PAM MÜLK YÖNETİMİ` ×2 (BAKIM-0041 ve -0087 içerik aynı), `KAZANCI HOLDİNG A.Ş.` ×3 (-0012 ve -0052 aynı, -0051 farklı tesis), `KARTAL BELEDİYESİ BAŞKANLIĞI` ×2 (-0009 / -0046 farklı dönem) | Aynı tesis için iki kez bakım iş emri üretilme riski. |
| Cihaz `ContactName` dağılımı | 13 farklı isim; en sık `NAZIM KÖSE` (366), `EMRE UTKU` (348), `AYDIN EROL` (92) | Bunlar büyük olasılıkla **Denge satış/proje sorumlusu**, müşteri irtibatı değil. Saha önerisi (`Program.cs:627`) bunu "saha yetkilisi" olarak gösteriyor. (Kullanıcıya soru, bkz. §5.) |

---

## 2. Olması gerekenler (hedef kurgu)

### 2.1 Kavram modeli

```text
Müşteri (Cari)  ──1..n──  Lokasyon (Tesis / Saha)  ──1..n──  Cihaz (kütük, M03)
   │  └─ üst müşteri (grup/holding, isteğe bağlı)          │
   │                                                       ├── İş emri (her iş 1 müşteri + 1 lokasyon)
   ├──1..n── İrtibat kişisi (müşteriye ya da lokasyona)    ├── Plan/ziyaret (saha bilgisi lokasyondan gelir)
   └──1..n── Bakım sözleşmesi (M04) ──n..1── Lokasyon      └── Kiralama / teklif / atölye kaydı
```

- **Müşteri (cari):** Sözleşmenin/teklifin tarafı, faturalanan tüzel kişi veya kamu kurumu. Örn. `SALACAK GAYRİMENKUL`.
- **Lokasyon (tesis/saha):** Teknisyenin gittiği yer. Örn. `PİAZZA İSTANBUL AVM`. Bir müşterinin birden çok lokasyonu olabilir (`KAZANCI HOLDİNG` → `ERKOL`, `KONİ İNŞAAT`; `HD YÖNETİM` → `AXIS EYÜP`, `AXIS KAĞITHANE`).
- **Bayi / entegratör:** Cihazı Denge'den alıp son kullanıcıya kuran firma da bir müşteridir (tür = Bayi/Entegratör). Cihaz kütüğünde "satın alan müşteri" ile "kurulu olduğu lokasyon" ayrı tutulur (cihaz modeli M03'te; bu modül alanların hedefini sağlar).
- **İrtibat kişisi:** Satın alma, saha/güvenlik amiri, teknik sorumlu, muhasebe. Müşteriye ya da belirli bir lokasyona bağlı.
- **Metin anlık görüntüsü (snapshot):** İş emri, teklif, kiralama, atölye kayıtlarındaki mevcut `CustomerName/Location` metinleri **silinmez**; kayıt anındaki adı gösterir. Yeni kimlik kolonları (`CustomerId`, `SiteId`, `ContactId`) yanına **nullable** eklenir. Böylece eski sürüm ekranları ve raporlar bozulmaz, geçiş artımlı olur.

### 2.2 Tutulacak veriler (asgari)

**Müşteri:** Müşteri kodu (otomatik, `MUS-#####`), ticari unvan, kısa/görünen ad, tür (Son Kullanıcı / Bayi-Entegratör / Kamu / Diğer), vergi no (VKN, isteğe bağlı), vergi dairesi, üst müşteri (grup), durum (Aktif / Pasif / Birleştirildi), doğrulandı mı (hızlı açılan kayıtlar "Doğrulanmamış"), dış referans kodu (ör. muhasebedeki cari kodu — **yalnız metin, entegrasyon değildir**), not, oluşturan/güncelleyen/zaman.

**Lokasyon:** Lokasyon kodu, müşteri, lokasyon adı, il, ilçe, açık adres, bina/kat notu, giriş/otopark/erişim notu, varsayılan birim(ler), durum (Aktif/Pasif), not. *(Koordinat/GPS bu fazda yok — araç takip ile birlikte ele alınır.)*

**İrtibat:** Ad soyad, görev/rol (Satın Alma / Saha-Güvenlik Amiri / Teknik Sorumlu / Muhasebe / Diğer), telefon, e-posta, bağlı lokasyon (boşsa müşteri geneli), birincil irtibat işareti, durum, not.

**Takma adlar (alias):** Eski serbest metin yazımları (`AKYAKA AVM`, `AKYAKA PARK AVM`), normalize edilmiş biçimi ve hangi müşteri/lokasyona çözüldüğü. Arama ve geçmiş kayıt eşleştirmesi bunun üzerinden çalışır.

### 2.3 Roller ve yetkiler (VARSAYIM — org şeması gelince teyit)

Önerilen yeni izin anahtarları: `customers.view`, `customers.edit`, `customers.merge`.

| Rol | Öneri |
|---|---|
| Operasyon Uzmanı | `customers.view` + `customers.edit` (müşteri/lokasyon/irtibat ekle-düzenle). İş kaydı açarken hızlı müşteri ekleyebilir (kayıt "Doğrulanmamış" düşer). |
| Şef | `customers.view` + `customers.edit` (özellikle lokasyon adres/erişim notu, saha irtibatı). |
| Teknisyen | `customers.view` (atandığı işin müşteri/lokasyon/irtibat bilgisi); düzenleme yok. Sahada yanlış bilgi görürse iş notuna yazar. |
| Teknik Servis Müdürü / Müdür Yrd. | `customers.view/edit/merge` — birleştirme, pasifleştirme, doğrulama. |
| Kiralama Operasyon | `customers.view` + `customers.edit` (kiralama müşterisi ve irtibatı). |
| Muhasebe / Genel Koordinatör / Üst Yönetim | `customers.view` (rapor). |
| Admin | `*` |

`workorders.create` sahibi, `customers.edit` olmasa da iş açarken **hızlı müşteri/lokasyon** oluşturabilir (yalnız ad + il; "Doğrulanmamış"). Böylece telefonla gelen acil iş ana veri yüzünden bekletilmez.

### 2.4 Durumlar ve akışlar

1. **Yeni iş kaydı:** Operatör müşteri adını yazmaya başlar → ad, takma ad, VKN, lokasyon adı üzerinden öneri listesi → müşteri seçilir → o müşterinin lokasyonları listelenir → lokasyon seçilir → irtibat seçilir/eklenir. Lokasyonun aktif sözleşmesi/garanti durumu bilgi olarak görünür (M14-11).
2. **Hızlı ekleme:** Öneri yoksa "Yeni müşteri ekle" → benzer adlar uyarı olarak gösterilir ("Bunu mu demek istediniz?") → yine de eklenirse kayıt "Doğrulanmamış" olur.
3. **Doğrulama:** Müdür/yetkili, doğrulanmamış kayıt listesini haftalık gözden geçirir: doğrula, mevcut kayıtla birleştir veya düzelt.
4. **Planlama:** Plan ekranındaki saha alanları (il, ilçe, adres, erişim notu, saha irtibatı/telefonu) seçili lokasyondan **ön doldurulur**, plan için elle değiştirilebilir (mevcut karar korunur). Planda değiştirilen bilgi "lokasyon kaydına da işle" seçeneğiyle ana veriye yazılabilir.
5. **Birleştirme:** İki müşteri (veya aynı müşterinin iki lokasyonu) birleştirilir → tüm bağlı kayıtlar hedefe taşınır → kaynak "Birleştirildi" durumuna geçer, adı takma ad olarak kalır → işlem geri alınamaz uyarısı ve denetim kaydı.
6. **Pasifleştirme:** Pasif müşteri/lokasyon yeni iş/teklif/kiralama için seçilemez; geçmiş kayıtlarda görünmeye devam eder. Açık işi olan lokasyon pasifleştirilirken uyarı verilir.

### 2.5 Doğrulama kuralları

- Ticari unvan zorunlu, 2–250 karakter, baş/son boşluk kırpılır.
- VKN girilmişse 10 hane rakam; aktif müşteriler arasında tekil.
- Normalize ad (büyük harf tr-TR, noktalama ve çoklu boşluk temizliği, `A.Ş./ANONİM ŞİRKETİ`, `LTD. ŞTİ./LİMİTED ŞİRKETİ`, `SAN. VE TİC.` gibi ekler kaldırılmış) aynı olan ikinci aktif müşteri **engellenmez ama uyarı ile onay ister**.
- Lokasyon adı aynı müşteri + il içinde tekil (uyarı).
- E-posta biçim kontrolü; telefon yalnız rakam/+ olarak saklanır, ekranda biçimlenir.
- İş emrinde seçilen lokasyon, seçilen müşteriye ait olmalı; irtibat o müşteriye (veya lokasyonuna) ait olmalı — **API'de** kontrol edilir.
- Pasif / birleştirilmiş müşteri yeni kayıtta seçilemez (API reddeder).
- Kimlik kolonu boş eski kayıtlar çalışmaya devam eder; raporlarda "Eşleştirilmemiş" grubu altında görünür (0 veya rastgele müşteriye atanmaz).

### 2.6 Raporlar / KPI'lar

| KPI / rapor | Tanım |
|---|---|
| Müşteri & lokasyon iş özeti | Dönemde açılan / kapanan / açık / geciken iş adedi; günlük servis ve planlı bakım **ayrı**. |
| Lokasyon tekrar arıza | Aynı lokasyonda X gün içinde (varsayılan 30) ikinci arıza kaydı sayısı ve listesi (seri no bazlı tekrara ek). |
| Ortalama çözüm süresi (müşteri/lokasyon) | Açılış → kapanış takvim saati; süre kaydı olmayan işler "süre kaydı eksik" sayısı olarak ayrıca gösterilir (0 kabul edilmez). |
| Saha kişi-saati (lokasyon) | Mevcut zaman kayıtlarından; mola hariç. Tahmini süre kullanılmaz. |
| Sözleşmeli lokasyon bakım tamamlama | Lokasyon başına planlanan / tamamlanan cihaz bakımı (M04 ile ortak). |
| Sözleşmesiz servis | Aktif sözleşmesi olmayan lokasyonlara açılan arıza işleri (ücretlendirme kontrolü için). |
| Veri kalitesi | Müşteri kimliği dolu iş emri oranı, doğrulanmamış müşteri sayısı, irtibatı olmayan aktif lokasyon sayısı, eşleştirilmemiş eski metin sayısı. |

---

## 3. Fark analizi — maddeler

### 3.1 Özet tablo

| Sıra | Id | Tür | Başlık | Efor | Öncelik grubu |
|---:|---|---|---|---|---|
| 1 | M14-07 | HATA · **KRİTİK (veri kaybı)** | Bakım formu kapanışı iş emri lokasyonunu eziyor | S | hemen (küçük, bağımsız) |
| 2 | M14-01 | YENİ | Müşteri / lokasyon / irtibat ana tabloları ve API | L | c |
| 3 | M14-02 | YENİ | Müşteri ana veri ekranı ve müşteri kartı | M | c |
| 4 | M14-04 | YENİ | İş kaydında müşteri-lokasyon-irtibat seçimi, plan saha bilgisinin dolması | M | c |
| 5 | M14-03 | VERİ | Serbest metinden ilk aktarım ve onaylı eşleştirme | L | c |
| 6 | M14-09 | YENİ | Mükerrer önleme ve müşteri/lokasyon birleştirme | M | c |
| 7 | M14-11 | YENİ | İş açılışında sözleşme/garanti kapsamı bilgisi | S | c |
| 8 | M14-05 | EKSİK | Teklif, kiralama, atölye, cihaz kütüğü ve sözleşmenin ana veriye bağlanması | M | b |
| 9 | M14-06 | HATA | Bakım üretiminde cihaz eşleşmesinin metne bağlı olması (87'de 1) | M | b |
| 10 | M14-08 | VERİ | Sözleşmelerde tesis/cari karışıklığı ve mükerrer sözleşmeler | S | b |
| 11 | M14-10 | EKSİK | İş emrinde müşteri/lokasyon düzeltme (gerekçeli, tarihçeli) | S | b |
| 12 | M14-12 | EKSİK | Müşteri/lokasyon bazlı raporlar ve KPI'lar | M | b |
| 13 | M14-14 | HATA/VERİ | Saha önerisinde irtibat olarak cihaz kütüğü `ContactName` kullanılması | S | b |
| 14 | M14-13 | GÜVENLİK | İrtibat kişisel verisi, yetki ve ana veri değişiklik kaydı | S | a |

> M14-07 küçük ve bağımsız olduğu ve her bakım kapanışında veri kaybettirdiği için öncelik sırasından bağımsız olarak ilk sürüme alınmalıdır.

### 3.2 Madde ayrıntıları

#### M14-01 · YENİ — Müşteri, lokasyon ve irtibat ana tabloları + API
- **Açıklama:** `Customers`, `CustomerSites`, `CustomerContacts`, `CustomerAliases` tabloları ve CRUD uçları: `GET/POST/PUT /api/customers`, `GET /api/customers/search?q=` (ad, takma ad, VKN, lokasyon adı; en çok 20 sonuç), `GET/POST/PUT /api/customers/{id}/sites`, `GET/POST/PUT /api/customers/{id}/contacts`, `PUT .../status` (Aktif/Pasif). Yeni izinler `customers.view/edit/merge` kataloğa eklenir.
- **Gerekçe:** "Hangi müşterinin hangi lokasyonundaki hangi cihaza ne yapıldı?" sorusu (proje hedefi §1) metin eşleşmesiyle güvenilir yanıtlanamıyor; 507 farklı yazım bunu gösteriyor.
- **Mevcut:** Ana tablo yok (§1.2); müşteri her tabloda serbest metin.
- **Kabul kriterleri:**
  1. Yeni müşteri + 2 lokasyon + 3 irtibat (biri lokasyona bağlı) API ile oluşturulur, `GET /api/customers/{id}` hepsini döner.
  2. Aynı VKN ile ikinci aktif müşteri → HTTP 409.
  3. Normalize adı aynı olan müşteri (`G4S ELEKTRONİK SİSTEMLERİ A.Ş.` ↔ `G4S Elektronik Sistemleri Anonim Şirketi`) `confirmDuplicate=false` ile → HTTP 409 + benzer kayıt listesi; `true` ile kaydedilir.
  4. `customers.view` olmayan kullanıcı → 403; `customers.edit` olmayan kullanıcı POST/PUT → 403.
  5. Başka müşterinin lokasyonuna irtibat bağlanmak istenirse → 400.
  6. `search?q=akyaka` takma ad üzerinden `AKYAKA PARK AVM` lokasyonunu ve müşterisini döner.
  7. Script idempotent: iki kez çalıştırıldığında hata vermez, veri silmez.
- **Roller/izin:** Bkz. §2.3 (varsayım).
- **Veri değişikliği:** Yeni script `ZZ_V121_CustomerMaster.sql`: 4 tablo, `MusteriKodu` için sıra/numaralama, `NormalizedName` kolonu + indeks, `IX_CustomerSites_Customer`, `IX_CustomerContacts_Customer`, `IX_CustomerAliases_Normalized`. Rol şablonlarına yeni izinler (mevcut kişi bazlı profillere **otomatik dağıtılmaz**, proje kuralı).
- **Efor:** L · **Bağımlılık:** Yok.

#### M14-02 · YENİ — Müşteri ana veri ekranı ve müşteri kartı
- **Açıklama:** Menüde "Müşteriler": filtreli liste (ad, tür, il, durum, doğrulanmamış), müşteri kartı sekmeleri: Genel bilgi · Lokasyonlar · İrtibatlar · Sözleşmeler (salt okunur, M04) · Cihazlar (lokasyona göre, M03) · İş emirleri (açık/son 12 ay) · Kiralama/teklif özeti. Lokasyon kartında aynı yapı lokasyon bazında.
- **Gerekçe:** Telefonla arayan müşterinin geçmişini, açık işlerini ve sahadaki cihazlarını tek ekranda görmek operasyonun en sık ihtiyacı.
- **Mevcut:** Ekran yok (§1.4).
- **Kabul kriterleri:**
  1. Kartta açık iş sayısı, `GET /api/workorders` filtresiyle aynı sayıyı verir (aynı birim yetkisiyle).
  2. Fiyat/tutar alanları `finance.prices.view` olmayan kullanıcıda **API yanıtında** yer almaz (sadece gizlenmez).
  3. Birim yetkisi olmayan kullanıcının o birime ait iş emirleri kartta listelenmez.
  4. Pasif müşteri kartı açılabilir; üstünde "Pasif" etiketi görünür.
  5. 375 px genişlikte (mobil) kart sekmeleri yatay kaydırmasız kullanılabilir.
- **Roller/izin:** `customers.view`; düzenleme düğmeleri `customers.edit` ile.
- **Veri değişikliği:** Yok (M14-01 + M14-05 kolonlarını okur).
- **Efor:** M · **Bağımlılık:** M14-01; sekmelerin dolu gelmesi M14-03/M14-05'e bağlı.

#### M14-03 · VERİ — Serbest metinden ilk aktarım ve onaylı eşleştirme
- **Açıklama:** (1) `WorkOrders`, `SecurityDevices`, `MaintenanceContracts`, `Offers`, `RentalOrders`, `WorkshopTickets`, `WorkOrderPlans` içindeki farklı müşteri/lokasyon metinlerini normalize ederek **aday** listesi çıkaran salt okunur bir SQL/API; (2) "Eşleştirme" ekranı: her aday metin için önerilen müşteri + lokasyon (normalize ad aynıysa "yüksek güven", benzerlik ile "orta", yoksa "yeni oluştur"), toplu onay/tek tek onay; (3) onaylanan eşleşmeler `CustomerAliases`'a yazılır ve ilgili tablolardaki `CustomerId/SiteId` kolonları **yalnız onaylı eşleşmeye göre** doldurulur. Cihaz kütüğünde `CustomerName` → satın alan müşteri, `Location` → lokasyon olarak ayrı eşlenir. Sözleşmede `CustomerName` → lokasyon, `CurrentAddress` → cari (M14-08).
- **Gerekçe:** Ana tablo eski kayıtlara bağlanmadıkça raporlar ve bakım eşleşmesi düzelmez. Otomatik birleştirme yanlış firmaları birleştirebileceği için insan onayı şart ("uydurma veri yok" ilkesi).
- **Mevcut:** Eşleştirme yok; seed'de 507 cihaz müşteri adı, 87 sözleşmenin 1'i kütükle birebir eşleşiyor (§1.6).
- **Kabul kriterleri:**
  1. Aday listesi üretimi hiçbir tabloyu değiştirmez (çalıştırma öncesi/sonrası satır sayısı ve checksum aynı).
  2. `AKYAKA AVM` (sözleşme) ve `AKYAKA PARK AVM` (kütük) aynı lokasyona onaylandığında, her iki kaynaktaki satırların `SiteId`'si aynı olur ve sözleşme lokasyon kartında 17 cihaz (9 X-Ray + 8 kapı) görünür — kütükte o kadar kayıt varsa; yoksa eksik sayı açıkça gösterilir.
  3. Onaylanmamış hiçbir satırın `CustomerId`'si dolmaz.
  4. Eski metin kolonları değişmez (anlık görüntü korunur).
  5. Müşteri adı boş cihaz satırları (seed'de 112) "Müşterisi bilinmiyor" listesinde ayrıca görünür, rastgele müşteriye atanmaz.
  6. İşlem yarıda kesilirse yeniden başlatılabilir; aynı onay iki kez uygulanırsa çift kayıt oluşmaz.
  7. Canlı geçiş öncesi `.bak` alınması ve `RESTORE VERIFYONLY` adımı geçiş talimatında yer alır.
- **Roller/izin:** `customers.merge` (Müdür/Müdür Yrd. — varsayım). Lokasyon/irtibat önerilerini Şef/Operasyon hazırlayabilir, onay yetkilisi verir.
- **Veri değişikliği:** M14-05'teki nullable kolonlar; `CustomerAliases` (Source tablo/kolon bilgisiyle); eşleştirme oturumu tablosu (aday metin, öneri, karar, karar veren, tarih).
- **Efor:** L · **Bağımlılık:** M14-01, M14-05 (kolonlar), M14-08 ile birlikte yapılmalı.

#### M14-04 · YENİ — İş kaydında müşteri / lokasyon / irtibat seçimi; plan saha bilgisinin lokasyondan dolması
- **Açıklama:** Yeni iş formunda "Müşteri" alanı arama destekli seçim olur (yazdıkça `/api/customers/search`), ardından lokasyon ve irtibat seçimi. Öneri yoksa "hızlı ekle" (ad + il zorunlu, kayıt "Doğrulanmamış"). İsteğe `customerId`, `siteId`, `contactId` eklenir; `CustomerName/Location` metni sunucuda seçilen kaydın adından **anlık görüntü** olarak yazılır. Plan/toplu plan ekranında saha alanları seçili lokasyondan ön dolar, elle değiştirilebilir; "lokasyon kaydını da güncelle" kutusu işaretliyse ana veri güncellenir (yetki varsa).
- **Gerekçe:** Yeni kayıtların temiz açılması, eski veriyi temizlemekten daha değerli; aksi halde eşleştirme hiç bitmez. Şefin her ziyarette adres/irtibatı yeniden girmesini önler.
- **Mevcut:** Düz metin form (`app.js:296-301`, `:1951`); API'de boş/boşluk müşteri adı kontrolü yok (`Program.cs:370-404`); saha alanları her planda elle (`ZZ_V111_PlanSites.sql`), öneri yalnız cihaz kütüğünden ve il/ilçe/telefon hep boş (`Program.cs:643-645`).
- **Kabul kriterleri:**
  1. Müşteri seçilip kaydedilen iş emrinde `CustomerId`, `SiteId` dolu; `CustomerName` müşterinin görünen adıyla aynı.
  2. `siteId` başka müşteriye aitse API 400 döner.
  3. Pasif müşteri seçilerek gönderilirse API 400 döner.
  4. Eski istemci (yalnız `customerName` metni gönderen) hâlâ kayıt açabilir; `CustomerId` boş kalır ve iş "Eşleştirilmemiş" sayılır. `customerName` boş/yalnız boşluk ise 400.
  5. Hızlı eklenen müşteri "Doğrulanmamış" listesinde görünür.
  6. Lokasyonu `İstanbul / Kadıköy`, erişim notu dolu bir işte plan formu açıldığında il, ilçe, adres, erişim notu, saha irtibatı ve telefonu dolu gelir; elle değiştirilen değer yalnız o plana yazılır (kutu işaretli değilse lokasyon kaydı değişmez).
  7. Toplu planlamada seçilen işlerin lokasyonları farklıysa saha alanları otomatik doldurulmaz, uyarı gösterilir.
- **Roller/izin:** `workorders.create` (hızlı ekleme dahil), `workorders.plan` (plan); lokasyon kaydını güncelleme `customers.edit`.
- **Veri değişikliği:** `WorkOrders.CustomerId/SiteId/ContactId` (M14-05), `WorkOrderPlans.SiteId` (nullable).
- **Efor:** M · **Bağımlılık:** M14-01, M14-05.

#### M14-05 · EKSİK — Diğer modüllerin ana veriye bağlanması
- **Açıklama:** Nullable FK kolonları: `WorkOrders(CustomerId, SiteId, ContactId)`, `WorkOrderPlans(SiteId)`, `Offers(CustomerId, SiteId, ContactId)`, `RentalOrders(CustomerId, SiteId)` + `RentalOrderContacts.CustomerContactId`, `WorkshopTickets(CustomerId, ContactId)`, `SecurityDevices(CustomerId [satın alan], SiteId [kurulu lokasyon])`, `MaintenanceContracts(CustomerId [cari], SiteId [bakım yapılan tesis])`. İlgili formlar M14-04 ile aynı seçim bileşenini kullanır; listeler ve aramalar kimlik varsa ana kaydın güncel adını, yoksa metni gösterir. Teklif iş emrinden açılıyorsa müşteri/lokasyon iş emrinden kopyalanır.
- **Gerekçe:** Müşteri kartı (M14-02) ve raporların (M14-12) tek kimlik üzerinden toplanabilmesi; atölye ve kiralamanın kendi müşteri adacıklarını oluşturmaması.
- **Mevcut:** Her modülde ayrı serbest metin (§1.2–1.4).
- **Kabul kriterleri:**
  1. Bir müşteriye bağlı iş emri, teklif, kiralama, atölye kaydı ve cihazlar müşteri kartında aynı müşteri kimliğiyle listelenir.
  2. İş emrinden açılan teklifte `CustomerId/SiteId` iş emriyle aynıdır.
  3. Atölye kaydı güncellemesi (`PUT /api/workshop/tickets/{id}`) iş emrinin `CustomerId`'sini atölye kaydıyla tutarlı tutar (bugünkü metin senkronu `Program.cs:2759` gibi).
  4. Kimlik kolonları boş eski kayıtlar tüm ekranlarda hatasız açılır.
  5. Tüm FK'ler `ON DELETE NO ACTION`; müşteri **silme** uç noktası yoktur (yalnız pasifleştirme/birleştirme).
- **Roller/izin:** Modüllerin mevcut izinleri.
- **Veri değişikliği:** Yukarıdaki nullable kolonlar + indeksler, idempotent script.
- **Efor:** M · **Bağımlılık:** M14-01; modül ekranları için M05/M06/M07 tasarımlarıyla koordinasyon.

#### M14-06 · HATA — Bakım üretiminde cihaz eşleşmesi müşteri adı metnine bağlı
- **Açıklama:** Vadesi gelen bakım iş emirleri üretilirken sözleşmenin cihazları `SecurityDevices.CustomerName = MaintenanceContracts.CustomerName` ile aranıyor. Hedef: önce M03-03/M03-09'daki doğrudan sözleşme–cihaz bağı; o yoksa **`MaintenanceContracts.SiteId = SecurityDevices.SiteId`** ve cihaz türü; o da yoksa bugünkü davranış + üretim öncesi uyarı ("Bu sözleşme için kütükte eşleşen cihaz yok, iş emirleri seri no olmadan açılacak").
- **Gerekçe:** Seed'de 87 sözleşmenin yalnız 1'i kütükle birebir eşleşiyor; 86 sözleşmenin PB iş emirleri seri no/bölge/cihaz kimliği olmadan açılıyor → "1 cihaz = 1 PB iş emri" kararının cihaz geçmişi tarafı fiilen çalışmıyor.
- **Mevcut:** `Program.cs:3010-3016` (metin eşleşmesi), `:3032`, `:3040-3042` (boş cihaz kalemi), `:3088` (lokasyon olarak `CurrentAddress`).
- **Kabul kriterleri:**
  1. `AKYAKA AVM` sözleşmesi ile kütükteki `AKYAKA PARK AVM` cihazları aynı lokasyona eşlendikten sonra üretim çalıştırıldığında, her PB cihaz kaleminde `SecurityDeviceId` ve seri no dolu gelir (kütükte o türden yeterli cihaz varsa).
  2. Lokasyonu eşlenmemiş sözleşme için üretim ekranında uyarı listesi görünür; iş emri yine açılır ama seri no boş kalır (uydurulmaz).
  3. Üretilen PB iş emrinin `SiteId`'si sözleşmenin `SiteId`'sidir; `Location` metni lokasyon adıdır (cari unvan değil).
  4. Aynı dönem için üretim iki kez çalıştırıldığında iş emri sayısı artmaz (mevcut idempotentlik korunur).
- **Roller/izin:** `maintenance.manage` / `workorders.plan` (mevcut).
- **Veri değişikliği:** Yok (M14-05 kolonlarını kullanır).
- **Efor:** M · **Bağımlılık:** M14-03, M14-05, M14-08; M03-09 ve M04-04 ile aynı sürümde koordine.

#### M14-07 · HATA · KRİTİK (veri kaybı) — Bakım formu kapanışı iş emri lokasyonunu cihaz bölgesiyle eziyor
- **Açıklama:** Bakım formu kaydedilirken `UPDATE dbo.WorkOrders SET ... Location=COALESCE(@Zone,Location)` çalışıyor; teknisyenin yazdığı bina içi bölge (ör. "B Kapısı giriş") iş emrinin müşteri lokasyonunun yerine geçiyor ve eski değer hiçbir yerde saklanmıyor. Düzeltme: `WorkOrders.Location` bu uçta **değiştirilmez**; bölge yalnız `MaintenanceDeviceItems.Zone`'da tutulur. Geçmiş kayıtlar için: `MaintenanceDeviceItems.Zone = WorkOrders.Location` olan PB iş emirlerinde lokasyon, sözleşme/lokasyon kaydından geri yazılabilecek kayıtların listesi çıkarılır (onaylı düzeltme).
- **Gerekçe:** "Müşteri Lokasyon" raporu (`Program.cs:3706-3709`) ve operasyon merkezi lokasyonu bu alandan okuyor; her kapanan bakım raporda ayrı bir "lokasyon" gibi görünür, aynı tesisteki 17 cihaz 17 farklı lokasyona dağılır.
- **Mevcut:** `Program.cs:2519`.
- **Kabul kriterleri:**
  1. Lokasyonu "AKYAKA PARK AVM" olan PB iş emri, bölge "X-Ray 3 / Giriş B" girilerek kapatıldığında `WorkOrders.Location` hâlâ "AKYAKA PARK AVM"dir; `MaintenanceDeviceItems.Zone` "X-Ray 3 / Giriş B"dir.
  2. Taslak kayıt (`complete=false`) ve kapanış (`complete=true`) için aynı davranış.
  3. Excel "Müşteri Lokasyon" sayfasında aynı tesisteki kapanmış PB işleri tek lokasyon satırında toplanır.
  4. Geçmiş veri düzeltme sorgusu önce yalnız **listeler**; güncelleme ayrı ve yedek sonrası çalıştırılır.
- **Roller/izin:** Değişmez.
- **Veri değişikliği:** Kod düzeltmesi; isteğe bağlı tek seferlik onaylı düzeltme scripti.
- **Efor:** S · **Bağımlılık:** Yok (geçmiş düzeltme M14-03 sonrası daha doğru yapılır, ama kod düzeltmesi beklemez).

#### M14-08 · VERİ — Sözleşmelerde tesis/cari karışıklığı ve mükerrer sözleşmeler
- **Açıklama:** `MaintenanceContracts.CustomerName` fiilen **tesis**, `CurrentAddress` fiilen **cari unvan** taşıyor. Eşleştirmede (M14-03) `CustomerName` → `SiteId`, `CurrentAddress` → `CustomerId` olarak ele alınır; ekranda kolon etiketi "Tesis" ve "Sözleşme Tarafı (Cari)" olur. Aynı tesis için birden fazla **aktif ve dönemi çakışan** sözleşme varsa üretim öncesi uyarı verilir. Seed'deki şüpheli kayıtlar kullanıcı onayıyla düzeltilir: `PAM MÜLK YÖNETİMİ` (BAKIM-0041 = BAKIM-0087), `KAZANCI HOLDİNG A.Ş. / KONİ İNŞAAT` (BAKIM-0012 = BAKIM-0052), `KARTAL BELEDİYESİ` (BAKIM-0009 / -0046), `ZİRAAT BANKASI` (BAKIM-0085 — alanlar kaymış).
- **Gerekçe:** Mükerrer sözleşme aynı tesise iki kez bakım iş emri ürettirir (gereksiz saha ziyareti, şişen bakım sayısı); cari/tesis karışıklığı faturalama ve raporda yanlış müşteriye yazma demektir.
- **Mevcut:** `DengeERP_V15_Schema.sql:31-52`, seed `DengeERP_V15_Seed.sql:2346-2443`; dönem kolonları yok (M04-03 ele alıyor).
- **Kabul kriterleri:**
  1. Aynı `SiteId` için iki aktif sözleşme dönem kesişiyle kaydedilmeye çalışıldığında uyarı çıkar ve onay ister (M04-03 dönem alanları geldikten sonra; o zamana kadar aynı tesis adında iki aktif sözleşme listesi raporlanır).
  2. Mükerrer olduğu kullanıcı tarafından onaylanan sözleşme pasifleştirildiğinde, o sözleşmeden üretilmiş açık PB iş emirleri listelenir; kapatma/iptal kararı kullanıcıya bırakılır (otomatik silinmez).
  3. Sözleşme listesinde "Tesis" ve "Cari" iki ayrı sütun olarak görünür.
- **Roller/izin:** `maintenance.manage` + `customers.merge` (onay).
- **Veri değişikliği:** M14-05 kolonları; veri düzeltmesi yedek sonrası.
- **Efor:** S · **Bağımlılık:** M14-03; M04-03 ile koordine.

#### M14-09 · YENİ — Mükerrer önleme ve müşteri / lokasyon birleştirme
- **Açıklama:** (1) Kayıt anında normalize ad + VKN + takma ad ile benzer kayıt uyarısı (M14-01 kural). (2) `POST /api/customers/{id}/merge` (hedef müşteri) ve `POST /api/customers/{id}/sites/{siteId}/merge`: tüm bağlı kayıtların `CustomerId/SiteId`'si hedefe taşınır, kaynak "Birleştirildi" olur, adı hedefe takma ad olarak eklenir, işlem tek transaction'da ve denetim kaydıyla. Önizleme ekranı taşınacak kayıt sayılarını tablo bazında gösterir.
- **Gerekçe:** İlk aktarım ve hızlı eklemeler kaçınılmaz olarak mükerrer kayıt üretir; birleştirme yoksa raporlar bölünür.
- **Mevcut:** Yok.
- **Kabul kriterleri:**
  1. A müşterisi (3 iş, 1 sözleşme, 5 cihaz) B'ye birleştirildiğinde B kartında 3 iş, 1 sözleşme, 5 cihaz görünür; A "Birleştirildi" durumundadır ve aramada B'ye yönlenir.
  2. Önizlemedeki sayılar birleştirme sonrası taşınan satır sayılarına eşittir.
  3. Kendine, pasif olmayan bir hedef dışında birine veya zaten birleştirilmiş kayda birleştirme → 400.
  4. İşlem ortasında hata olursa hiçbir satır taşınmamış olur (transaction).
  5. Birleştirme denetim kaydında yapan kullanıcı, tarih, kaynak, hedef ve tablo bazında satır sayıları bulunur.
  6. `customers.merge` olmayan kullanıcı → 403.
- **Roller/izin:** `customers.merge` (Müdür / Müdür Yrd. / Admin — varsayım).
- **Veri değişikliği:** `Customers.MergedIntoCustomerId`, `CustomerSites.MergedIntoSiteId`, `CustomerMasterAudit` (bkz. M14-13).
- **Efor:** M · **Bağımlılık:** M14-01, M14-05.

#### M14-10 · EKSİK — İş emrinde müşteri / lokasyon düzeltme
- **Açıklama:** `PUT /api/workorders/{id}/customer` (müşteri, lokasyon, irtibat) — gerekçe zorunlu, eski/yeni değer iş emri tarihçesine yazılır. Kapalı iş emrinde yalnız `customers.merge` yetkisiyle.
- **Gerekçe:** Bugün yanlış yazılan müşteri adı atölye dışındaki işlerde düzeltilemiyor; operatör yeni iş açıp eskisini iptal etmek zorunda kalıyor (iş/KPI sayısını bozar).
- **Mevcut:** Genel iş emri güncelleme ucu yok; müşteri adını yalnız atölye güncellemesi değiştiriyor (`Program.cs:2757-2769`).
- **Kabul kriterleri:**
  1. Açık iş emrinin müşterisi değiştirildiğinde `/api/workorders/{id}/history` içinde eski ve yeni müşteri adı + gerekçe görünür.
  2. Gerekçe boşsa 400.
  3. Kapalı iş emrinde `customers.merge` yoksa 403.
  4. Lokasyon değişince aktif plandaki saha alanları otomatik değiştirilmez; kullanıcıya "planı da güncelle?" sorulur.
- **Roller/izin:** `workorders.edit` (açık iş), `customers.merge` (kapalı iş).
- **Veri değişikliği:** Yok (mevcut durum/tarihçe tablosu kullanılır; gerekirse alan değişikliği satır tipi).
- **Efor:** S · **Bağımlılık:** M14-01, M14-05.

#### M14-11 · YENİ — İş açılışında sözleşme / garanti kapsamı bilgisi
- **Açıklama:** Lokasyon seçildiğinde formda bilgi kutusu: aktif bakım sözleşmesi (dönem, kalan bakım), lokasyondaki cihazların garanti durumu (M03-03), son 30 gün içindeki işler. Fiyat/ücret bilgisi **yok** (yalnız kapsam). İş emrine açılış anındaki kapsam durumu ("Sözleşmeli / Sözleşme dışı / Bilinmiyor") anlık görüntü olarak yazılır.
- **Gerekçe:** Operasyon uzmanı telefonda "bu iş ücretli mi, bakım kapsamında mı, geçen hafta gidilmiş mi?" sorusunu yanıtlayabilmeli; "sözleşmesiz servis" raporu (M14-12) için veri kaynağı.
- **Mevcut:** Yok.
- **Kabul kriterleri:**
  1. Aktif sözleşmeli lokasyon seçildiğinde kutuda sözleşme no ve dönem görünür; süresi geçmiş sözleşmede "Süresi dolmuş" yazar.
  2. Sözleşme dönemi bilinmiyorsa (M04-03 öncesi eski kayıt) "Dönem bilgisi yok" yazar; "Sözleşmeli" denmez.
  3. Yanıtta hiçbir tutar alanı yoktur (`finance.prices.view` olsa bile bu uçta).
  4. İş emrinde `CoverageStatus` açılış anındaki değeri korur; sözleşme sonradan değişse de değişmez.
- **Roller/izin:** `workorders.create`.
- **Veri değişikliği:** `WorkOrders.CoverageStatus NVARCHAR(30) NULL`.
- **Efor:** S · **Bağımlılık:** M14-04, M14-05; dönem bilgisi için M04-03, garanti için M03-03.

#### M14-12 · EKSİK — Müşteri / lokasyon bazlı raporlar ve KPI'lar
- **Açıklama:** §2.6'daki KPI'lar. Excel "Müşteri Lokasyon" sayfası ve operasyon merkezi gruplaması `CustomerId/SiteId` varsa onunla, yoksa "Eşleştirilmemiş: <metin>" etiketiyle yapılır. Rapor filtresinde müşteri/lokasyon seçimi (metin aramasına ek). Lokasyon bazlı tekrar arıza listesi.
- **Gerekçe:** Yönetim sorusu "en çok sorun çıkan müşteri/tesis hangisi, sözleşme dışı ne kadar iş yapıyoruz" bugün yazım farkları yüzünden yanıtlanamıyor.
- **Mevcut:** `Program.cs:2212` (metin `Contains` filtresi), `:3706-3709` (metin gruplaması), `OpsSuite.cs:93` (yalnız seri no bazlı tekrar).
- **Kabul kriterleri:**
  1. Farklı yazımla açılmış ama aynı `SiteId`'ye eşlenmiş 3 iş, raporda tek lokasyon satırında 3 iş olarak görünür.
  2. Günlük servis ve planlı bakım ayrı sütun/sayfa.
  3. Süre kaydı olmayan işler ortalama süreye 0 olarak katılmaz; "süre kaydı eksik: N" olarak gösterilir.
  4. Lokasyonda 30 gün içinde ikinci arıza açıldığında tekrar arıza listesinde iki iş numarası birlikte görünür (planlı bakım işleri hariç).
  5. Veri kalitesi göstergesi: kimliği dolu iş emri oranı (%), doğrulanmamış müşteri sayısı.
  6. Rapor tarih filtresi boşken de çalışır (V1.20.1 hotfix davranışı korunur).
- **Roller/izin:** `reports.view`, `reports.export`; tutar içeren sütunlar `finance.prices.view`.
- **Veri değişikliği:** Yok.
- **Efor:** M · **Bağımlılık:** M14-03, M14-05; M10 (operasyon/SLA) ile koordine.

#### M14-13 · GÜVENLİK — İrtibat kişisel verisi, yetki ve ana veri değişiklik kaydı
- **Açıklama:** İrtibat kişisi adı/telefonu/e-postası KVKK kapsamında kişisel veridir. (1) Müşteri ana verisi uçlarında `customers.*` izinleri ve birim yetkisi API'de uygulanır. (2) Ana veri değişiklikleri (oluşturma, alan değişikliği, pasifleştirme, birleştirme, eşleştirme onayı) `CustomerMasterAudit` tablosuna yazılır: kim, ne zaman, hangi alan, eski/yeni değer. (3) Pasif irtibat kişisinin bilgileri arama sonuçlarında çıkmaz. (4) Müşteri listesi dışa aktarımı (Excel/CSV) ayrı izinle (`reports.export`) ve dışa aktarım kaydıyla.
- **Gerekçe:** Ortak ana veri yanlış/kasıtsız değiştirildiğinde tüm modülleri etkiler; kimin değiştirdiği bilinmeli. Kişisel verinin gereksiz geniş erişimi KVKK riski.
- **Mevcut:** Denetim kaydı yok (envanter gözlemi 3); müşteri irtibat bilgisi modül görüntüleme izniyle herkese açık.
- **Kabul kriterleri:**
  1. Bir lokasyonun telefonunu değiştiren işlem sonrası denetim tablosunda eski ve yeni değer, kullanıcı ve zaman vardır.
  2. Denetim kaydı API üzerinden değiştirilemez/silinemez (uç yok).
  3. `customers.view` olmayan kullanıcı `/api/customers*` uçlarından 403 alır; iş emri detayında yalnız kendi birimindeki işin irtibatını görür.
  4. Müşteri listesi dışa aktarımı `reports.export` olmadan 403.
- **Roller/izin:** Bkz. §2.3.
- **Veri değişikliği:** `CustomerMasterAudit` tablosu.
- **Efor:** S · **Bağımlılık:** M14-01. (Genel kimlik/oturum güvenliği ayrı güvenlik çalışmasında.)

#### M14-14 · HATA/VERİ — Saha önerisinde irtibat olarak cihaz kütüğü `ContactName` kullanılması
- **Açıklama:** Saha önerisi ucu "saha yetkilisi" olarak `SecurityDevices.ContactName` döndürüyor. Seed'de bu kolonda 13 farklı isim var ve 1.000'den fazla cihazda aynı birkaç isim geçiyor (ör. `NAZIM KÖSE` 366, `EMRE UTKU` 348) — büyük olasılıkla Denge satış/proje sorumlusu. Kullanıcı teyidi sonrası: bu alan cihaz kütüğünde "Satış/Proje Sorumlusu" olarak yeniden etiketlenir, saha önerisi irtibatı **lokasyon irtibatından** (M14-01) alır; M14-03 aktarımında bu isimler müşteri irtibatı olarak taşınmaz.
- **Gerekçe:** Şef planda müşterinin saha yetkilisi yerine kendi şirket çalışanının adını görüp yanlış kişiyi arayabilir.
- **Mevcut:** `Program.cs:627`, `:645`; seed dağılımı §1.6.
- **Kabul kriterleri:**
  1. Saha önerisinin `siteContact` alanı, lokasyonun birincil saha irtibatıdır; lokasyon irtibatı yoksa boş döner (cihaz kütüğü `ContactName` dönmez).
  2. Cihaz kütüğü ekranında alan başlığı kullanıcı kararına göre değişir.
  3. İlk aktarımda `SecurityDevices.ContactName` değerleri `CustomerContacts`'a yazılmaz.
- **Roller/izin:** Değişmez.
- **Veri değişikliği:** Yok (etiket ve sorgu değişikliği).
- **Efor:** S · **Bağımlılık:** Kullanıcı teyidi (§5 soru 3); M14-01.

---

## 4. Geçiş ve uygulama notları

- **Artımlı yol:** (1) M14-07 kod düzeltmesi → (2) M14-01 + M14-05 şema (tümü nullable, mevcut ekranlar etkilenmez) → (3) M14-02 ekran + M14-04 yeni iş formu (yeni kayıtlar temiz açılır) → (4) M14-03/M14-08 eşleştirme (güvenlik birimi sözleşmeli tesislerden başlayarak; 87 sözleşme + ilgili cihazlar) → (5) M14-06, M14-09–M14-12.
- **Geri dönüş:** Şema değişiklikleri yalnız nullable kolon + yeni tablo olduğundan eski uygulama klasörü yeni şemayla çalışmaya devam eder. Eşleştirme verisi geri alınması gerekirse `CustomerId/SiteId` kolonları `NULL`'a çekilerek eski duruma dönülür (metin kolonlarına dokunulmadığı için veri kaybı olmaz). Her adım öncesi `.bak` + `RESTORE VERIFYONLY`.
- **Test verisi:** Seed içindeki gerçek örnekler (AKYAKA, PİAZZA/SALACAK, HD YÖNETİM/AXIS, KAZANCI/ERKOL-KONİ, G4S yazım varyantları) kabul testlerinde kullanılabilir.
- **Kapsam dışı:** Logo cari entegrasyonu, adres doğrulama servisi, GPS/rota, müşteri portalı, e-posta/SMS bildirimleri.

---

## 5. Kullanıcıya sorulacaklar

1. **Müşteri tanımı:** Raporlarda ve iş kaydında "müşteri" denince fatura kesilen cari mi (ör. `SALACAK GAYRİMENKUL`) yoksa gidilen tesis mi (ör. `PİAZZA İSTANBUL AVM`) esas alınmalı? Tasarım ikisini ayrı tutuyor; ekranda hangisinin önde görüneceği sizin kararınız.
2. **Bayi/entegratör üzerinden satılan cihazlar:** Cihaz kütüğünde müşteri olarak bayi (ör. G4S, SECURİTAS, "… ÜZERİNDEN") yazan cihazlara servis talebi geldiğinde iş emri bayiye mi, son kullanıcı tesisine mi açılıyor? Faturayı kim ödüyor?
3. **Cihaz kütüğündeki `ContactName`** (NAZIM KÖSE, EMRE UTKU, AYDIN EROL …) Denge'nin satış/proje sorumlusu mu, yoksa müşteri tarafı kişi mi?
4. **Tek doğru müşteri listesi kaynağı:** Muhasebede (Logo vb.) kullanılan cari listesi ilk aktarım için kaynak olarak alınabilir mi (Excel dökümü yeterli)? Cari kodunu yalnız referans olarak saklamamız yeterli mi? (Entegrasyon kapsam dışı.)
5. **Mükerrer görünen sözleşmeler:** BAKIM-0041/-0087 (PAM MÜLK), BAKIM-0012/-0052 (KAZANCI/KONİ), BAKIM-0009/-0046 (KARTAL BELEDİYESİ) gerçekten iki ayrı sözleşme mi, yoksa tekrar mı? BAKIM-0085 (ZİRAAT BANKASI) kaydının doğru bilgisi nedir?
6. **Birleştirme ve doğrulama yetkisi** kimde olmalı (öneri: Teknik Servis Müdürü ve Müdür Yardımcısı)? Hızlı eklenen "doğrulanmamış" kayıtları kim, hangi sıklıkla gözden geçirecek?
7. **Vergi numarası** zorunlu olsun mu? Bireysel (şahıs) müşteriler var mı — varsa TCKN tutulmayacak şekilde mi ilerleyelim (KVKK açısından önerimiz: TCKN tutulmasın)?
8. **İlk eşleştirme işini kim yapacak** ve hangi birimden başlanacak (öneri: Güvenlik Sistemleri sözleşmeli tesisleri, sonra Haberleşme atölye müşterileri)? Bu iş birkaç gün insan emeği gerektirir.
9. **Haberleşme / POC / Mobilite müşterileri** güvenlik müşterileriyle aynı ana listede mi tutulmalı (aynı firma iki birimde müşteri olabilir) — öneri: evet, tek liste, birim yalnız iş kaydında.
10. **Tekrar arıza penceresi:** Lokasyon bazlı tekrar arıza için kaç gün esas alınsın (öneri 30)?

---

## 6. Varsayımlar

- Rol/izin önerileri varsayımdır; organizasyon şeması gelince güncellenecek.
- Seed verisi üzerinden yapılan sayımlar (§1.6) canlı SQL'in bugünkü durumunu temsil etmeyebilir; aynı sayımlar SSMS'te canlı/test kopyada tekrarlanmalı.
- Sözleşmenin dönem, frekans, cihaz kapsamı ve üretim mantığı M04 (Planlı Bakım) tasarımında; cihaz–sözleşme doğrudan bağı M03'te ele alınıyor. Bu modül yalnız müşteri/lokasyon kimliği ve bağlantıyı tanımlar.
- Mevcut metin kolonları kaldırılmayacak; anlık görüntü olarak kalacak (geri uyumluluk ve tarihsel doğruluk).
- Teknoloji yığını korunuyor (.NET 10 minimal API + SQL Server + mevcut vanilla JS SPA); yeni ekranlar mevcut `app.js` desenine eklenir.
