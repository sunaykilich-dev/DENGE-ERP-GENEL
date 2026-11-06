# DengeERP V1.20.1 — Eski Sistem İşlev Envanteri (Parity Checklist)

> **Belge tarihi:** 21 Ekim 2026
> **Amaç:** .NET 10 + SQL Server + vanilla JS SPA olan V1.20.1'in Python **Django + PostgreSQL** ile yeniden yazımında **kaybolmaması gereken her işlevin** kaynak konumlu kontrol listesi.
> **Kaynak (salt okunur):** `kaynak/V1_20_1_orijinal/DengeERP.Api/`
> **Kapsam:** Teknik servis. Logo CRM / Flowick entegrasyonu kapsam dışı (yalnızca alanların korunması listelenir).
> **Yöntem:** `Program.cs` (3.937 satır), `OpsSuite.cs` (280), `wwwroot/app.js` (2.047), `wwwroot/ops120.js` (102), `Database/*.sql` (11 dosya), `CHANGELOG_PILOT_*.txt`, `HOTFIX_V1201.txt`, `TEST_SONUCLARI_V120.txt` satır satır okundu.

## 0. Okuma kılavuzu

**Kaynak kısaltmaları** (satır numaraları dosyanın ham satırlarıdır):

| Kısaltma | Dosya |
|---|---|
| `P:n` | `DengeERP.Api/Program.cs` |
| `O:n` | `DengeERP.Api/OpsSuite.cs` |
| `A:n` | `DengeERP.Api/wwwroot/app.js` |
| `J:n` | `DengeERP.Api/wwwroot/ops120.js` |
| `S-UPD:n` | `Database/DengeERP_Update.sql` |
| `S-V15:n` | `Database/DengeERP_V15_Schema.sql` |
| `S-SEED:n` | `Database/DengeERP_V15_Seed.sql` |
| `S-V17:n` | `Database/DengeERP_V17_Schema.sql` |
| `S-V18:n` | `Database/DengeERP_V18_DeviceWorkOrders.sql` |
| `S-110:n` … `S-120:n` | `Database/ZZ_V110_…sql` … `ZZ_V120_…sql` |
| `CL-x:n` | `CHANGELOG_PILOT_Vx.txt` |
| `BELGE §n` | `analiz/DengeERP_Proje_Gecmisi_Kararlar_ve_Teknik_Durum_2026-10-21.md` |

**İşaretler**

- `[✔K]` — Proje geçmişi belgesine göre **kullanıcı tarafından çalıştığı doğrulanmış** işlev (BELGE §4, §10.1).
- `[KURAL R-xx]` — Bölüm 6'daki numaralı iş kuralına bağlantı.
- `[⚠ HATA]` — Eski kodda tespit edilen tutarsızlık/hata. Parity'de **birebir kopyalanmamalı**; davranış bilinçli karar ile düzeltilmeli.
- `[⚠ BOŞLUK]` — İş kararı (BELGE) ile kod arasında uyumsuzluk; yeni sistemde kapatılmalı.
- `[İSTEMCİ]` — Kural yalnızca tarayıcıda uygulanıyor; sunucu doğrulamıyor. Yeni sistemde sunucuya taşınmalı.

## 1. Özet sayılar

| Kalem | Adet | Not |
|---|---:|---|
| API ucu | **82** | Program.cs 70 + OpsSuite.cs 12 (statik dosyalar hariç) |
| Ekran (menü) | **21** | + 2 kimlik ekranı (giriş, zorunlu şifre değişimi) = 23 |
| Modal / alt ekran | **18** | İş emri detayı, plan, toplu plan, bakım formu vb. |
| Veritabanı tablosu | **43** | Tüm scriptlerin birleşik son hali |
| Numaralı iş kuralı | **88** | Bölüm 6 (R-01 … R-96; modül blokları için numaralarda boşluk bırakıldı) |
| Rapor / çıktı | **13** | Excel 8 sayfa + 3 CSV + 1 PDF + 1 web rapor ekranı |
| Seed / sabit liste | **38** | Bölüm 4 |
| Kullanıcı doğrulamalı işlev | **7** | Bölüm 7 |
| Tespit edilen hata/boşluk | **19** | Bölüm 8 |

---

## 2. API uçları (82)

Ortak davranışlar (her uçta geçerli):

- Kimlik: `Authorization: Bearer <token>`; token bellek içi sözlükte (`P:21`, `P:2814-2825`). Token yok/geçersiz → **401**. Yetki yok → **403** (`Results.Forbid`).
- `Can(user,p)`: `*` veya izin listesinde `p` (`P:2806`). `IsAdmin`: `*` **veya** rol adı `Admin` (`P:2805`).
- `UnitAllowed`: Admin **veya `AllowedUnits` boş** **veya** birim listede (büyük/küçük harf duyarsız) (`P:2807`). [KURAL R-02]
- `CanAccessWorkOrderAsync`: birim erişimi + rol adı tam olarak `Teknisyen` ise yalnızca **aktif teknisyen ataması isimle eşleşen** iş (`P:3385-3401`). [KURAL R-03]
- `FilterWorkOrdersForUser`: liste uçlarında aynı birim + teknisyen filtresi (`P:3495-3502`).
- `Db(x)`: boş/boşluk metin → `NULL`, değilse `Trim()` (`P:2809`).
- Hata mesajları Türkçe `{"message": "..."}`; SQL unique ihlali (2601/2627) → **409**.

### 2.1 Sistem / Kimlik / Meta (7)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 1 | `GET /api/health` | **Anonim** | SQL bağlantısı açılırsa `{application,status:"Çalışıyor",database:"Bağlı",time}`; hata → 503 + `ex.Message` (bilgi sızıntısı) | `P:47-65` |
| 2 | `POST /api/auth/login` | Anonim | Kullanıcı adı `Trim`; pasif kullanıcı veya yanlış şifre → 401 (ayrım yok). PBKDF2-SHA256, 120.000 tur, 16 bayt tuz, 32 bayt hash, sabit zamanlı karşılaştırma. 32 bayt rastgele hex token; oturum `{userId,username,fullName,roleName,allowedUnits,permissions,mustChangePassword}` döner. Deneme sınırı / kilit yok. [R-01] | `P:67-99`, `P:2827-2844` |
| 3 | `GET /api/auth/me` | Oturum | Oturum nesnesini döndürür | `P:101-105` |
| 4 | `POST /api/auth/logout` | — | Token'ı sözlükten siler | `P:107-112` |
| 5 | `POST /api/auth/change-password` | Oturum | Yeni şifre ≥ 8 karakter; `MustChangePassword=0`; oturum güncellenir. Eski şifre sorulmaz. [R-04] | `P:114-137` |
| 6 | `GET /api/meta/permissions` | Oturum | İzin kataloğu (34), rol varsayılanları (12 rol), birimler (5), departmanlar (19) | `P:139-151`, `P:3871-3936` |
| 7 | `GET /api/rules/worktypes` | Oturum | Aktif `WorkTypeRules` (birim, iş türü, açılışta/kapanışta seri zorunlu) | `P:153-172` |

### 2.2 Kullanıcı / Yetki (5)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 8 | `GET /api/users` | `users.manage` | Tüm kullanıcılar (hash hariç), `FullName` sıralı | `P:174-201` |
| 9 | `POST /api/users` | `users.manage` | Ad soyad + kullanıcı adı zorunlu; geçici şifre ≥ 8. İzin listesi boşsa **rol varsayılanı**; birim listesi boşsa **tüm 5 birim**. Kullanıcı adı tekrarı → 409. [R-05] | `P:203-243` |
| 10 | `PUT /api/users/{id}` | `users.manage` | Ad, kullanıcı adı, rol, birim, izin, `MustChangePassword` güncellenir; aynı boş-liste varsayılanları; kullanıcının **açık oturumları anında yeni yetkiyle güncellenir**. Yetki yükseltme koruması yok (`*` verilebilir). [R-05][R-06] | `P:245-319` |
| 11 | `PATCH /api/users/{id}/status` | `users.manage` | Aktif/pasif. **Kendi hesabını pasif yapamaz.** Pasifleştirilen kullanıcının oturumu düşürülmez. | `P:321-336` |
| 12 | `POST /api/users/{id}/reset-password` | `users.manage` | Geçici şifre ≥ 8; `MustChangePassword=1` | `P:338-357` |

### 2.3 İş Emirleri / Planlama (10)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 13 | `GET /api/workorders` | `workorders.view` | Tüm iş emirleri + son aktif plan + aktif şef (en son atanan) + teknisyenler (virgüllü) + aktif seri nolar (`WorkOrderDevices` yoksa `WorkOrders.SerialNo`); birim/teknisyen filtresi | `P:359-368`, `P:3441-3502` |
| 14 | `POST /api/workorders` | `workorders.create` + birim | Seri no temizleme [R-10]; iş türü kuralı `SerialRequiredOnCreate` ise seri zorunlu [R-11]. Numara **`SRV-YYYYMM-####`** [R-07]. Durum **`Müşteri Talebi`**; ilk seri `WorkOrders.SerialNo`'ya, tüm seriler `WorkOrderDevices`'a; `CreatedByErpUserId` = kullanıcı; durum geçmişine "Kayıt oluşturuldu." Tek transaction. 201 döner. | `P:370-430` |
| 15 | `PUT /api/workorders/{id}/serials` | `workorders.create` **veya** `edit` **veya** `close` + iş erişimi | Bakım cihaz iş emri ise reddedilir ("Bakım formundan güncelleyin") [R-30]. Eski cihaz satırları **pasifleştirilir** (silinmez), yenileri eklenir; `WorkOrders.SerialNo` = ilk seri. | `P:432-471` |
| 16 | `PATCH /api/workorders/{id}/status` | `workorders.edit` **veya** `close` + iş erişimi | Durum metni **sunucuda doğrulanmaz** [⚠ HATA H-05]. Kapatılmış cihaz bakım emri yeniden açılamaz [R-31]. Kapanış durumu (`Tamamlandı`/`Kapatıldı`/`Çözüldü`) için: aktif canlı sayaç varsa **409** [R-52]; cihaz bakım emri ise bu uçtan kapatılamaz (form zorunlu) [R-30]; eski tip ana PB kontrolleri; `SerialRequiredOnClose` ise seri zorunlu [R-12]. `ClosedAt` yalnızca `Kapatıldı`'da set edilir [R-14]. Durum geçmişi yazılır. Kapanış sonrası `CompleteMaintenanceFromWorkOrderAsync` + bakım üretimi tetiklenir [R-36]. | `P:473-543`, `P:2808` |
| 17 | `PUT /api/workorders/{id}/assignments` | `workorders.assign` + iş erişimi | Aktif atamalar pasifleştirilir; şef (rol `Şef`) + teknisyenler (rol `Teknisyen`, tekilleştirilmiş) **isim metni** olarak eklenir. Tarihçeye yazmaz. [R-15] | `P:545-570` |
| 18 | `PUT /api/workorders/bulk-assign` | `workorders.assign` | 1–150 iş; en az bir şef **veya** teknisyen; ≤ 30 teknisyen, isim ≤ 150; tüm işler bulunmalı; **tek birim**; kapalı (`Tamamlandı/Kapatıldı/İptal`) olamaz; plan/tarih/araç değişmez; her işe tarihçe notu "Toplu personel ataması…". Tek transaction (kısmi kayıt yok). [R-16] [✔K] | `P:573-614` |
| 19 | `GET /api/workorders/{id}/site-suggestion` | `workorders.plan` + iş erişimi | Cihaz kütüğü / bakım sözleşmesinden saha önerisi: `siteName`=iş lokasyonu, `siteAddress`=sözleşme adresi, `siteArea`=cihaz bölgesi veya kütük lokasyonu, `siteContact`=kütük ilgili kişi; **şehir/ilçe/telefon tahmin edilmez (null)**. [R-21] | `P:619-647` |
| 20 | `PUT /api/workorders/bulk-plan` | `workorders.plan` **ve** `workorders.assign` | 1–150 iş; tarih + başlangıç saati zorunlu, süre **15–1440 dk**; plaka ≤ 30, not ≤ 1000, saha alanı uzunlukları [R-20]; en az şef/teknisyen; ≤ 30 teknisyen; **aynı müşteri + aynı lokasyon + aynı birim** (trim, harf duyarsız), lokasyon/müşteri boş olamaz; kapalı veya **zaten planlı** iş olamaz. Rota grup no **`TPL-` + 16 hex**. Her işe ayrı plan satırı + atama + durum `Planlandı` + tarihçe. Tek transaction. **Çakışma kontrolü yok** [İSTEMCİ R-18]. [R-17] | `P:649-720` |
| 21 | `PUT /api/workorders/{id}/plan` | `workorders.plan` + iş erişimi | Saha alanı uzunluk kontrolü; eski aktif plan pasifleştirilir, yenisi eklenir; durum **koşulsuz** `Planlandı` (kapalı işte bile) [⚠ HATA H-06]; tarih/süre doğrulaması yok; çakışma kontrolü yok. | `P:722-761` |
| 22 | `GET /api/workorders/{id}/history` | `workorders.view` + iş erişimi | `WorkOrderStatusLogs` yeni→eski | `P:763-788` |

### 2.4 Teklif (5)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 23 | `GET /api/offers` | `offers.view` | Admin değilse birim filtresi. **Fiyatlar `finance.prices.view` olmadan da döner** [⚠ BOŞLUK H-13] | `P:790-798` |
| 24 | `POST /api/offers` | `offers.create` + birim | ≥ 1 kalem; toplam hesabı [R-60]; numara **`TKL-YYYYMM-####`** [R-07]; durum `Taslak`; isteğe bağlı iş emri bağı | `P:800-859`, `P:3504-3518` |
| 25 | `PATCH /api/offers/{id}/status` | `offers.approve` | İzinli durumlar: `Taslak, Onay Bekliyor, Onaylandı, Kabul Edildi, Reddedildi`; `Onaylandı`'da onaylayan + zaman. Birim kontrolü yok. | `P:861-881` |
| 26 | `GET /api/offers/{id}/pdf` | `offers.view` + birim | Tek sayfa ASCII PDF (Bölüm 5.4) | `P:883-893`, `P:3573-3636` |
| 27 | `POST /api/offers/{id}/send` | `offers.send` + birim | Yalnız `Onaylandı` teklif; alıcı = istek veya müşteri e-postası; SMTP ayarı yoksa 400; PDF ekli e-posta; `EmailLogs`'a her denemede kayıt; başarıda durum **`Müşteriye Gönderildi`** + `SentAt`; hata → 502. [R-61] | `P:895-958` |

### 2.5 Kiralama / Depo (11)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 28 | `GET /api/rentals/catalog` | `rentals.view` **veya** `rentals.create` | Aktif ürünler, birim filtresi | `P:961-991` |
| 29 | `GET /api/rentals` | `rentals.view` | Kiralamalar + kalem sayısı + toplam adet; birim filtresi | `P:993-1049` |
| 30 | `POST /api/rentals` | `rentals.create` + birim | Adet ≥ 1; bitiş ≥ başlangıç; müşteri zorunlu; kompozisyon doğrulama [R-70]; tüm kalemler aynı birimin aktif ürünü; numara **`KIR-YYYYMM-####`**; durum `Talep`; üst kayıtta ilk kalem ürün/seri + toplam adet; kalem+irtibatlar kaydedilir. | `P:1051-1138`, `P:3183-3255` |
| 31 | `PUT /api/rentals/{id}` | `rentals.edit` + birim | 12 izinli durum [R-71]; tarih/adet kontrolü; seri takipli üründe `Teslim Edildi/Kirada/İade Bekliyor/İade Alındı/Test / Kontrol/Kapandı` için seri zorunlu [R-72]; `Kapandı/İptal`'de `ClosedAt` (diğerlerinde NULL'a döner). | `P:1140-1198` |
| 32 | `GET /api/rentals/{id}/details` | `rentals.view` + birim | Kalemler (+ atanmış envanter sayısı), irtibatlar, aşama geçmişi (seri anlık görüntüsü, kaydeden) | `P:1201-1243` |
| 33 | `PUT /api/rentals/{id}/composition` | `rentals.edit` + birim | Kalem+irtibat kümesini atomik kaydeder; ürün birimi eşleşmeli; envanter atanmış kalemin modeli değiştirilemez / adedi atananın altına inemez; atamalı kalem silinemez; irtibatlar komple yenilenir [R-73] | `P:1245-1290` |
| 34 | `GET /api/rentals/inventory` | `rentals.view` **veya** `warehouse.view` | Aktif depolar + envanter satırları (bağlı kiralama no ile) | `P:1292-1320` |
| 35 | `PUT /api/rentals/warehouses/{id}` | `rentals.edit` | Depo adı 1–120 karakter | `P:1322-1332` |
| 36 | `POST /api/rentals/inventory` | `rentals.edit` + ürün birimi | Ekle/güncelle (aynı uç). Adet 1–10000; seri ≤ 200; notlar ≤ 1500; durum ∈ {Hazır, Hazır Değil, Kirada, Kontrolde}; `Hazır Değil` → eksik notu zorunlu; seri takipli ürün → **seri zorunlu ve adet = 1**; depo aktif olmalı; **kiralamaya atanmış satır düzenlenemez**; ürün+seri tekrarı → 409. [R-74] | `P:1334-1374` |
| 37 | `POST /api/rentals/{id}/allocate` | `rentals.edit` + birim | Serializable transaction. Kaleme envanter atar; ≤ 1000 cihaz; sevk edilmiş (`Kirada`) atama depo dönüşü olmadan değiştirilemez; seçilen cihaz aynı ürün, `Hazır` (veya bu kaleme bağlı `Kirada`), başka kaleme bağlı değil; toplam adet ≤ kalem adedi; önceki `Hazır` bağları çözülür; kalem seri listesi envanterden yeniden yazılır. **Çift tahsis engeli** [R-75] | `P:1376-1434` |
| 38 | `POST /api/rentals/{id}/stage` | `rentals.edit` + birim | Aşama ∈ {Sevk Edildi, Kurulum Yapıldı, Devreye Alındı, Toplandı, Depoya Alındı}; tarih (şimdi−10 yıl … şimdi+1 gün); `Depoya Alındı` için depo zorunlu; geçmişe seri anlık görüntüsü. `Sevk Edildi` → bağlı `Hazır` envanter `Kirada`; `Depoya Alındı` → bağlı envanter seçilen depoya, durum **`Kontrolde`**, bağ çözülür. Aşama sırası zorlanmaz. [R-76][R-77] | `P:1436-1482` |

### 2.6 Eğitim / Yetkinlik (8)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 39 | `GET /api/training/overview?year=` | `training.view` | Yıl 2020–2100 (aksi bugünün yılı). Birim kapsamı: Admin/boş birim → tümü; aksi halde personel birimi listede (birimsiz personel yalnız tüm-birim kullanıcıya). Döner: kişiler, kurslar, kriterler, yıl planları, **önceki yıl tamamlanan planlar (carryover)**, yılın oturumları, katılım, yetkinlik kataloğu, seviyeler, gözlemler (yıl−1…yıl+1). [R-80] | `P:1485-1536` |
| 40 | `POST /api/training/courses` | `training.manage` | Kod + başlık + süre (0 < s ≤ 24) zorunlu; kontrol listesi metninden **1–30 madde**, her madde ≤ 450; `!` ile başlayan madde **kritik**; baştaki `! * -` temizlenir; kategori boşsa `Gelişim`; kod tekrarı → 409. [R-81] | `P:1538-1569` |
| 41 | `POST /api/training/plans/bulk` | `training.manage` | 1–300 personel; yıl 2020–2100; **hedef tarih yılı = plan yılı**; kurs aktif; her personele birim yetkisi önce kontrol (kısmi kayıt yok); aynı kişi+kurs+yıl varsa atlanır; "N yıllık gelişim hedefi eklendi" [R-82] | `P:1571-1596` |
| 42 | `POST /api/training/sessions` | `training.manage` | Eğitmen zorunlu, süre 0–24; kurs FK | `P:1598-1610` |
| 43 | `POST /api/training/attendance` | `training.manage` | Puanlar 0–100; personel ve kurs birimi yetkisi; MERGE (oturum+kişi tekil); **Katıldı ise aynı yıl planı `Tamamlandı` + CompletedAt = oturum tarihi**; katılmadı ise geçmiş tamamlanma silinmez [R-83] | `P:1612-1647` |
| 44 | `POST /api/training/competencies` | `training.manage` **veya** `training.observe` | Seviye 1–4 (mevcut/hedef); MERGE (kişi+yetkinlik tekil); değerlendiren = oturum adı | `P:1649-1666` |
| 45 | `POST /api/training/observations` | `training.observe` **veya** `training.manage` | Aşama ∈ {0,30,60,90}; puanlar ∈ {-1,0,1,2}, en az biri ≠ -1, tekrar yok, kursun kriteri olmalı; **skor = 100 × Σpuan / (cevaplanan × 2)**; **kritik madde 0 → CriticalFailure**; gözlemci = oturum adı; isteğe bağlı iş emri. [R-84][R-85] | `P:1668-1710` |
| 46 | `GET /api/training/export.csv?year=` | `training.view` **ve** `training.export` | Bölüm 5.2 | `P:1712-1731` |

### 2.7 Personel (4)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 47 | `GET /api/personnel` | `personnel.view` | Tüm personel + bağlı kullanıcı adı/rol (birim filtresi **yok**) | `P:1733-1768` |
| 48 | `POST /api/personnel` | `personnel.manage` (+ hesap için `users.manage`) | Ad + departman zorunlu; ek departmanlar pipe; isteğe bağlı aynı transaction'da ERP hesabı (kullanıcı adı + ≥ 8 şifre; rol boşsa `Operasyon Uzmanı`; izin boşsa rol varsayılanı; **birim boşsa boş = tüm birimler**). [R-90] | `P:1770-1832` |
| 49 | `PUT /api/personnel/{id}` | `personnel.manage` | Bilgi güncelleme (durum hariç) | `P:1834-1860` |
| 50 | `PATCH /api/personnel/{id}/status` | `personnel.manage` | Pasif → `EndDate` (verilmezse bugün); aktif → `EndDate=NULL`. **Bağlı ERP hesabı da aynı duruma alınır ve açık oturumları düşürülür.** [R-91] | `P:1862-1903` |

### 2.8 Saha / Zaman Takibi (8)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 51 | `GET /api/timetracking/summary` | `workorders.view` | Görünür işlerdeki açık sayaçlar, süre kayıtları, tamamlanmış molalar, `serverTime`, `isManager`. `reports.view` yoksa yalnız kendi sayaçları/kayıtları (kayıtlar **isimle**). | `P:1908-1927` |
| 52 | `POST /api/workorders/{id}/live-timer/start` | `workorders.view` + (`close` **veya** `edit`) + iş erişimi | Faaliyet ∈ 7 tür (Mola dahil); bölge ≤ 250, not ≤ 1000; Serializable. **Yalnız işe `Teknisyen` olarak atanmış kişinin kendi hesabıyla**; iş kapalı/iptal değil; **kullanıcının başka açık sayacı yok** (+ DB unique indeks); başlangıç anında başka süre kaydıyla çakışma yok; başlangıç = **SQL sunucu saati**. [R-50][R-51] | `P:1929-1983` |
| 53 | `POST /api/workorders/{id}/live-timer/change` | aynı | Faaliyet değiştir: aynı faaliyete geçilemez; bölüm ≥ **1 dk**, ≤ **18 saat**; kapalı işte yeni faaliyet açılamaz; Mola değilse süre kaydına yazılır (çakışma kontrolü ile); bölge/not boşsa öncekinden taşınır; yeni oturum bitişten başlar. [R-53][R-54][R-55] | `P:1985-2078` |
| 54 | `POST /api/workorders/{id}/live-timer/finish` | aynı | Aynı fonksiyon, yeni oturum açmadan. **İş emrini kapatmaz.** [R-56] | `P:1987-2078` |
| 55 | `POST /api/timetracking/sessions/{sessionId}/cancel` | `workorders.assign` **veya** `users.manage` + iş erişimi | Gerekçe zorunlu ≤ 500; açık oturum `İptal` ile kapanır, iptal eden + gerekçe saklanır; **kişi-saat oluşmaz**. [R-57] | `P:2080-2102` |
| 56 | `GET /api/workorders/{id}/time-logs` | `workorders.view` + iş erişimi | İşin iptal edilmemiş süre kayıtları | `P:2105-2113` |
| 57 | `POST /api/workorders/{id}/time-logs` | `workorders.close` **veya** `edit` + iş erişimi | Manuel süre. **Rol `Teknisyen` ise teknisyen adı zorla kendi adı**; faaliyet ∈ 7 tür (Diğer dahil, Mola yok); bitiş > başlangıç; ≤ 18 saat (1080 dk); gelecek tarih yok (+5 dk tolerans); kişi işe teknisyen olarak atanmış olmalı; kişinin açık sayacıyla çakışma yok; **aynı kişinin başka kayıtla zaman çakışması yok**. [R-58] | `P:2114-2165` |
| 58 | `DELETE /api/workorders/{id}/time-logs/{timeLogId}` | `workorders.assign` **veya** `users.manage` + iş erişimi | **Silmez**: `IsVoided=1`, iptal eden ad + zaman (denetim izi). [R-59] | `P:2166-2180` |

### 2.9 Raporlar (2)

| # | Yöntem + Yol | İzin | Ne yapar | Kaynak |
|---|---|---|---|---|
| 59 | `GET /api/reports/worklogs` | `reports.view` | Görünür işlerin iptal edilmemiş tüm süre kayıtları | `P:2181-2189` |
| 60 | `GET /api/reports/workorders.xlsx` | `reports.export` | Filtreler: `start,end,dateField(created/plan/closed),kind(all/service/maintenance),unit,status,workType,person,chief,customer`. start > end → 400. 8 sayfalı Excel (Bölüm 5.1). Dosya adı `DengeERP_Yonetim_Raporu_yyyyMMdd_HHmm.xlsx`. [✔K] (V1.20.1 boş tarih düzeltmesi) | `P:2191-2229` |

### 2.10 Güvenlik Cihaz Kütüğü + Planlı Bakım (7)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 61 | `GET /api/security/devices?q=&brand=&type=&model=` | (`devices.view` **veya** `workorders.view`) + birim `Güvenlik Sistemleri` | Aktif kütük; tam eşleşme filtreleri + `q` (seri/müşteri/lokasyon/model LIKE) | `P:2232-2285` |
| 62 | `GET /api/maintenance/contracts` | (`maintenance.view` **veya** `workorders.view`) + Güvenlik | Aktif sözleşmeler + **bu yılın ilk tamamlanmamış planı** + bağlı iş emri + cihaz sayısı/tamamlanan. **Ücret metni, sözleşme toplamı, 2026 toplamı `finance.prices.view` yoksa null.** [R-62] | `P:2288-2345` |
| 63 | `POST /api/maintenance/generate-due` | (`maintenance.manage` **veya** `workorders.plan`) + Güvenlik | Vadesi gelen cihaz PB iş emirlerini üretir; "N adet … oluşturuldu" [R-33] | `P:2347-2356`, `P:2894-2982` |
| 64 | `GET /api/maintenance/plans/{planId}/devices` | (`maintenance.view` **veya** `workorders.view`) + Güvenlik | Plan dönemindeki cihaz kalemleri + PB no + bölge | `P:2360-2376` |
| 65 | `POST /api/maintenance/plans/{planId}/devices/initialize` | `maintenance.manage` + Güvenlik | Açık plan için eksik cihaz iş emirlerini oluşturur; mevcutlar tekrar oluşturulmaz [R-34] | `P:2379-2400` |
| 66 | `GET /api/maintenance/workorders/{id}/form` | (`workorders.view` **veya** `maintenance.view`) + iş erişimi | Bakım formu + kontrol maddeleri (kod, etiket, sonuç) + marka/model + müşteri adresi | `P:2403-2443` |
| 67 | `POST /api/maintenance/workorders/{id}/form` | (`workorders.close` **veya** `maintenance.manage`) + iş erişimi | Taslak veya tamamla. Bölüm 6.4 kuralları R-37…R-45 (kapatılmış form değiştirilemez; sonuç listesi; tamamlarken seri/bölge/not/sonuç zorunlu; hiç `Bekliyor` kalmamalı; `Tamamlandı` için **tüm maddeler Uygun**; aynı dönemde aynı seri başka cihazda olamaz; açık sayaç varsa 409; `Tamamlandı` → iş `Kapatıldı`, değilse `Beklemede`; **plan + sözleşme sayacı tüm cihazlar bitince bir kez artar**). | `P:2445-2557` |

### 2.11 Haberleşme Atölye (3)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 68 | `GET /api/workshop/tickets` | (`workshop.view` **veya** `workorders.view`) + birim `Haberleşme` | Tüm atölye kayıtları (41 alan; **tamir bedeli maskelenmez** [⚠ BOŞLUK H-13]) | `P:2560-2626` |
| 69 | `POST /api/workshop/tickets` | (`workshop.manage` **veya** `workorders.create`) + Haberleşme | Firma, servis türü, marka, seri zorunlu. **Önce bağlı iş emri** (`SRV-`, birim Haberleşme, tür `Atölye Teknik Servis`, lokasyon `Atölye`, öncelik Normal, durum **`Atölyede`**, konu "{Marka} {Model} Atölye Teknik Servis"), cihaz satırı, sonra **`AT-YYYYMM-####`** atölye no; durum boşsa `Yeni Kayıt`; giriş tarihi boşsa şimdi; tarihçe. [R-63] | `P:2628-2705` |
| 70 | `PUT /api/workshop/tickets/{id}` | (`workshop.manage` **veya** `workorders.edit`) + Haberleşme | Tüm alanlar güncellenir; **atölye durumu → iş emri durumu eşlemesi** [R-64]; iş emri müşteri/konu/sistem/seri/e-posta senkronlanır; `Teslim Edildi` → iş `Kapatıldı` + `ClosedAt`. | `P:2707-2776` |

### 2.12 Operasyon Merkezi / SLA / Stok / Maliyet — OpsSuite (12)

| # | Yöntem + Yol | İzin | Ne yapar / iş kuralları | Kaynak |
|---|---|---|---|---|
| 71 | `GET /api/ops/overview?days=` | `dashboard.view` | `days` 1–366 (vars. 30). Kapsam: son N günde açılan **veya** açık işler. Her iş için `overdue` (SLA), bekleme nedeni, kayıtlı dakika. Sayaçlar: açık, geciken, servis, bakım, bugün, yarın, bekleme, kapanan. Personel iş yükü (toplam/açık/kapalı). **Tekrar arıza** (bakım hariç, aynı seri ≥ 2 iş, ilk 25, iş no ilk 8). Uyarılar (kullanıcının görmediği, ≤ 100). İlk 1500 iş (geciken önce). [R-65][R-66][R-67] | `O:76-110` |
| 72 | `POST /api/ops/alerts/ack` | `dashboard.view` | Uyarı anahtarı şu anki uyarılar arasında olmalı (yoksa 404); kullanıcı başına tekil kayıt [R-68] | `O:111-121` |
| 73 | `PUT /api/ops/sla/{priority}` | `operations.manage` | Saat 1–8760; olmayan öncelik → 404 | `O:122-129` |
| 74 | `POST /api/ops/workorders/{id}/hold` | `operations.manage` **veya** `workorders.edit` | Neden 1–100, not ≤ 1000; iş görünür olmalı; kapalı iş bekletilemez; önceki durum saklanır, durum **`Beklemede`**; DB'de iş başına tek açık bekleme. **Tarihçeye yazılmaz.** [R-69] | `O:130-145` |
| 75 | `POST /api/ops/workorders/{id}/release` | aynı | Açık bekleme kapanır; iş hâlâ `Beklemede` ise **önceki duruma** döner | `O:146-159` |
| 76 | `GET /api/ops/stock` | `warehouse.view` | Depolar + parça/depo bakiyeleri; **birim maliyet `finance.prices.view` yoksa null** | `O:160-176` |
| 77 | `POST /api/ops/stock/part` | `warehouse.manage` | Kod 1–80, ad 1–200, minimum ≥ 0, maliyet ≥ 0; **maliyet > 0 için `finance.costs.manage`**; birim sabit `Adet`; kod tekil (DB) | `O:177-187` |
| 78 | `POST /api/ops/stock/movement` | `warehouse.manage` | Miktar 0 < q ≤ 100000; tür ∈ {Giriş, Çıkış}; **Çıkış için iş emri zorunlu** ve görünür olmalı; Serializable + UPDLOCK; **negatif stok engeli**; bakiye upsert; hareket satırına o anki **birim maliyet anlık görüntüsü**. [R-78][R-79] | `O:188-213` |
| 79 | `GET /api/ops/finance` | `finance.prices.view` **ve** `reports.view` | İş başına gelir, diğer maliyet, malzeme, işçilik = saat × birim tarifesi, toplam, fark, saat; birim tarifeleri (birim yetkili olanlar). [R-86] | `O:214-236` |
| 80 | `PUT /api/ops/finance/rate` | `finance.prices.view` **ve** `finance.costs.manage` + birim | Tarife 0–1.000.000 | `O:237-245` |
| 81 | `PUT /api/ops/finance/{id}` | `finance.prices.view` **ve** `finance.costs.manage` + iş görünür | Gelir ve diğer maliyet 0–1e9; upsert | `O:246-258` |
| 82 | `GET /api/ops/export.csv` | `reports.export` | Bölüm 5.2 | `O:259-265` |

---

## 3. Ekranlar (app.js / ops120.js)

### 3.1 Uygulama kabuğu

| Öğe | Ayrıntı | Kaynak |
|---|---|---|
| Önyükleme | `localStorage.denge_token` varsa `/me` + çekirdek veri; aksi giriş ekranı | `A:2044-2047`, `A:34-35` |
| Çekirdek veri yükleme | İş emirleri, kurallar, meta; izne göre süre kayıtları, canlı özet, kullanıcılar, teklifler, kiralama katalog/kayıt/envanter, personel, kütük, sözleşmeler, atölye | `A:137-155` |
| Giriş ekranı | Kullanıcı adı (varsayılan `admin`), şifre; hata mesajı tek tip | `A:157-169`, `A:2031-2033` |
| Zorunlu şifre değişimi | `mustChangePassword` ise tüm uygulama yerine; iki alan eşleşmeli, ≥ 8 | `A:171-177`, `A:2034-2040` |
| Yerleşim | Sol menü + mobil üst menü şeridi, üst bar (sayfa adı, "SQL Bağlı" çipi, kullanıcı baş harfleri, rol, Çıkış) | `A:205-209` |
| Giriş sonrası açılış | `dashboard.view` → Ana Panel, yoksa İş Emirleri, yoksa Teklifler | `A:2032` |
| 401 davranışı | Token silinir, "Oturum süresi doldu" | `A:91`, `A:1900` |
| Ortak modal / indirme | Tek modal yuvası; blob indirme `Content-Disposition` adıyla | `A:1591-1592`, `A:1897-1903` |
| Durum rozet renkleri | yeşil: Tamamlandı/Kapatıldı; mavi: talep/plan/saha/POC durumları; amber: Beklemede/Atölyede/Kargoda; kırmızı: İptal; mor: Test / Kontrol | `A:118-126` |

### 3.2 Menü (21 ekran) — görünürlük kuralları `A:179-203`

| # | Menü adı | `view` | Görünürlük | Sayfa başlığı |
|---|---|---|---|---|
| 1 | Ana Panel | dashboard | `dashboard.view` | Ana Panel |
| 2 | Operasyon Merkezi | operations120 | `dashboard.view` | Operasyon Merkezi |
| 3 | Mobil İşler | mobile120 | `workorders.view` | Mobil Teknisyen Paneli |
| 4 | Yedek Parça | stock120 | `warehouse.view` | Yedek Parça Stokları |
| 5 | Maliyet Analizi | finance120 | `finance.prices.view` **ve** `reports.view` | Maliyet Analizi |
| 6 | Yeni İş Açılışı | create | `workorders.create` | Yeni İş Açılışı |
| 7 | İş Emirleri | workorders | `workorders.view` | İş Emirleri |
| 8 | Planlama | planning | `workorders.plan` | Planlama Takvimi |
| 9 | Güvenlik Cihaz Kütüğü | securitydevices | `devices.view` + birim Güvenlik | — |
| 10 | Planlı Bakımlar | maintenance | `maintenance.view` + birim Güvenlik | — |
| 11 | Haberleşme Atölye | workshop | `workshop.view` + birim Haberleşme | Haberleşme Atölye Teknik Servis |
| 12 | Kiralama | rentals | `rentals.view` | Kiralama Yönetimi |
| 13 | POC / Mobilite | pocmobility | `workorders.view` | — |
| 14 | Teklif Yönetimi | offers | `offers.view` | — |
| 15 | Saha / Zaman Takibi | timetracking | `workorders.view` | — |
| 16 | Raporlar | reports | `reports.view` | — |
| 17 | Eğitim / Personel Gelişimi | training | `training.view` | Eğitim ve Personel Gelişimi |
| 18 | Depo | warehouse | `warehouse.view` | — |
| 19 | Muhasebe | accounting | `accounting.view` | — |
| 20 | Personel / Organizasyon | personnel | `personnel.view` | — |
| 21 | Kullanıcı / Yetki | users | `users.manage` | Kullanıcı ve Yetki Yönetimi |

Menü tıklamasında ek yenileme: ops ekranları → ops verisi; Zaman → canlı özet; Eğitim → eğitim verisi; Raporlar → iş emirleri + süre kayıtları (`A:1909`).

### 3.3 Ekran ayrıntıları

**E-01 Ana Panel** (`A:211-225`, `A:229-289`) [✔K KPI kutuları]
- Bölüm "Günlük Servis / Arıza" (planlı bakım hariç), 8 tıklanabilir KPI: Açık Servis, Müşteri Talebi, Planlandı, Sahada (*Sahada + İşlemde*), Atölyede, Beklemede, Tamamlanan Servis, Kritik Servis (açık + öncelik Kritik).
- Bölüm "Planlı Bakım / Yıllık Bakım", 4 KPI: Açık Bakım, Planlanan Bakım, Tamamlanan Bakım, Bekleyen Bakım (açık + plan tarihi yok).
- "Servis/Bakım işlerini göster" → İş Emirleri ilgili sekme + açık işler.
- Birim kartları (yetkili birimler): Servis Açık, Bakım Açık, Planlı, Biten; tıklayınca İş Emirleri o birim + servis + açık.
- Son 10 günlük servis iş emri tablosu; "Raporlara git".
- **KPI detay modalı** (her tıklanabilir sayı kutusu): birim / iş türü / durum açılır filtreleri, serbest arama (iş no, müşteri, lokasyon, konu, açıklama, teknisyen, şef, seri), birime göre gruplu katlanır listeler, iş türü sayaç çipleri, iş no tıklayınca iş emri detayı.
- [⚠ HATA H-01] "Sahada" kutusu Sahada+İşlemde sayar, liste yalnız Sahada gösterir (`A:220` ↔ `A:243`). [⚠ HATA H-02] "Açık Bakım" sayısı `reportIsOpen`, liste `isOpen` (Tamamlandı'yı da içerir) (`A:222` ↔ `A:248`).

**E-02 Operasyon Merkezi** (`J:23-49`, `J:52-102`)
- Butonlar: Yenile, Operasyon CSV. **3 dakikada bir otomatik yenileme** (sayfa görünürken) (`J:102`).
- 8 tıklanabilir sayaç: Açık İş, Geciken, Bugün Planlı, Yarın Planlı, Günlük Servis, Planlı Bakım, Bekleme, Kapanan.
- 5 sekme: İş Listesi (arama: no/müşteri/lokasyon/şehir/personel; sıfırla; ilk 250; "Gecikti" rozeti; **Beklet / Beklemeyi Kaldır**), Uyarılar (Görüldü, İş Emri), Personel İş Yükü, Tekrar Arıza, SLA Hedefleri (`operations.manage` ile Düzenle).
- Bekletme nedeni istemi önerisi: "Malzeme / Müşteri Onayı / Teklif / Personel / Diğer", varsayılan "Malzeme Bekleniyor" (`J:73`).
- [⚠ HATA H-03] Sayaç düğmelerinin `data-filter` olayı `bind()` içinde İş Emirleri birim filtresiyle eziliyor (`A:1906` sonra `A:1911`; `J:68`) → sayaç tıklayınca liste filtrelenmiyor.

**E-03 Mobil İşler** (`J:6-9`)
- Teknisyen rolünde yalnız kendine atanmış, diğer rollerde tümü; kapalılar hariç; ilk 120 kart (no, müşteri, şehir/lokasyon, durum, "İşi Aç"). Çevrimiçi/çevrimdışı rozeti; "offline senkronizasyon yok" uyarısı.

**E-04 Yedek Parça** (`J:10-14`, `J:78-92`)
- Tablo: ID, kod, ürün, depo, stok, minimum, durum (Azaldı/Yeterli), iç maliyet (`finance.prices.view`).
- `warehouse.manage`: Parça Tanımla (kod, ad, minimum, maliyet yalnız `finance.costs.manage` ile); Stok Giriş/Çıkış (parça ID, depo ID, tür, miktar, Çıkış'ta iş emri ID zorunlu) — istem (prompt) tabanlı.

**E-05 Maliyet Analizi** (`J:15-22`, `J:93-100`)
- Toplam gelir / maliyet / fark kutuları; birim saatlik iç maliyet düğmeleri (`finance.costs.manage` ile düzenlenir); iş bazlı tablo (gelir, malzeme, işçilik, diğer, toplam, fark; ilk 350; Düzenle → gelir/diğer/not). "Resmi kârlılık raporu değildir" notu.

**E-06 Yeni İş Açılışı** (`A:291-314`, `A:1950-1951`)
- Birim sekmeleri (yetkili birimler). Alanlar: İş Türü* (birime göre liste), Öncelik (Normal/Yüksek/Kritik), Müşteri*, Müşteri E-posta, Proje, Lokasyon, Sistem/Ürün (birime göre liste), Seri No(lar) (virgül/; /satır), Kısa Konu*, Açıklama.
- İş türü değişince seri kuralı bilgi kutusu güncellenir (3 metin). Başarıda iş no uyarısı → İş Emirleri o birim.
- Not: arayüzde "Düşük" öncelik yok, SLA tablosunda var.

**E-07 İş Emirleri** (`A:316-341`, `A:1678-1748`, `A:1953`) [✔K toplu atama]
- Sekmeler: Günlük Servis / Arıza (varsayılan) | Planlı / Yıllık Bakım | Tümü; Açık İşler (varsayılan) | Tamamlananlar | Tüm Durumlar; Tüm Birimler | birim sekmeleri.
- Arama: no, müşteri, proje, lokasyon, seri, konu, teknisyen, şef.
- Kolonlar: [seçim], İş Emri, Birim, İş Türü, Müşteri, Lokasyon, Seri No, Şef, Teknisyen, Durum, Plan (Planla düğmesi `workorders.plan` ile).
- **Toplu atama çubuğu** (`workorders.assign`): satır seçimi; kapalı satırlar devre dışı; "tümünü seç" farklı birim içeriyorsa engellenir; **farklı birimden seçim önceki seçimi sıfırlar**; modal: şef (isteğe bağlı) + çoklu teknisyen; "Her iş emri bağımsız kaldı" mesajı.

**E-08 İş Emri Detay Modalı** (`A:1608-1676`)
- Özet: durum, şef, teknisyen, araç. Planlı Bakım ise "Cihaz Bakım Formu Aç".
- İş/cihaz bilgisi: sistem, seri nolar (düzenlenebilir: Planlı Bakım değil ve create/edit/close izni), seri kuralı, konu, açıklama; "Seri No Kaydet".
- Planlama özeti + saha alanları (şehir/ilçe, tesis, bina/kat/bölge, adres, yetkili, telefon, ulaşım notu); "Planı Aç / Düzenle".
- Atama/Durum (`assign` veya `edit`): şef seçimi, teknisyen çoklu seçim, durum listesi (POC birimi için ayrı liste; **Planlı Bakım işinde Tamamlandı/Kapatıldı seçilemez**), işlem notu; kaydet = önce atama PUT, sonra durum PATCH.
- "Bu İş İçin Teklif Oluştur" (`offers.create`).
- Canlı sayaç paneli (E-17 ile aynı kurallar), atanmamışsa uyarı.
- Manuel gerçek süre formu (`edit`/`close`): teknisyen (Teknisyen rolünde kilitli kendi adı, diğerlerinde atanmış teknisyenler), faaliyet (7), başlangıç/bitiş, bölge, not; süre kayıtları tablosu; `workorders.assign` ile "İptal" (void).
- Durum geçmişi tablosu.
- Şef/teknisyen seçenek kaynağı: aktif kullanıcılardan rol Şef/Teknisyen + personelden unvan regex (takım lideri|yönetici|müdür → şef; teknisyen|mühendis|operasyon uzmanı|destek uzmanı → teknisyen) + **sabit yedek liste** (`A:1593-1606`, `A:23-29`).

**E-09 Planlama Takvimi** (`A:343-537`, `A:1750-1878`, `A:1936-1947`)
- 5 tıklanabilir mini KPI: Bugün planlı, Bu hafta, Toplam planlı, **Çakışmalı iş**, Plan bekleyen.
- Sekmeler: Günlük Servis Planı (varsayılan) | Planlı Bakım Planı | Tüm Planlar. Gezinme ← / Bugün / →; Gün/Hafta (varsayılan)/Ay; birim ve personel (şef+teknisyen) filtreleri.
- Kaynak: kapalı/iptal olmayan işler (`isOpen`).
- **Kompakt ziyaret kartı**: aynı gün + birim + müşteri + tesis(siteName/lokasyon) + şehir → tek kart (en erken saat, Bakım/Servis/Karma etiketi, iş sayısı, ekip). Hafta: gün başına **en fazla 4** ziyaret + "+N lokasyon daha"; Ay: **en fazla 3**; Gün: tümü. Kart → ziyaretteki ayrı iş emirleri modalı. [R-19]
- **Çakışma işareti** [İSTEMCİ R-18]: aynı tarih, saat aralığı kesişimi (varsayılan başlangıç 09:00, süre 60 dk), aynı araç **veya** ortak teknisyen **veya** aynı şef; aynı `TPL-` grubundaki aynı ziyaret hariç.
- **Planlanmayı Bekleyenler**: plan tarihi olmayan açık işler; müşteri+lokasyon+birim gruplu (lokasyon/müşteri boşsa tekil, toplu seçilemez), grup onay kutusu, alt liste varsayılan kapalı; arama (müşteri, lokasyon, iş no, konu, seri); arama değişince seçim temizlenir; **seçim yalnız tek grup içinde** (başka grup seçilince önceki silinir).
- "Toplu Ekip Ata" (`assign`), "Toplu Planla + Ata" (`plan`+`assign`): tarih*, saat* (09:00), süre seçenekleri 1/2/3/4/6 saat/tam gün (vars. 4 saat), araç, şef, teknisyenler, not, saha alanları (öneriyle) [✔K].
- Tekli plan modalı: şef, teknisyenler, tarih*, saat, süre (1/2/3/4 saat/tam gün; vars. 2 saat), araç, rota grubu, not, saha alanları; kaydet = atama PUT + plan PUT.
- **Saha önerisi**: boş alanlar `site-suggestion` ile doldurulur, **dolu alanlar asla ezilmez**; kaynak etiketi (`A:1804-1817`).

**E-10 Güvenlik Cihaz Kütüğü** (`A:540-565`)
- KPI: Toplam kütük, X-Ray, Kapı Dedektörü, Seri No mevcut.
- Filtreler: cihaz tipi, marka, model (markaya bağlı), arama (seri, müşteri, lokasyon, model, ilgili kişi) — istemci tarafı. İlk 1000 satır.
- Kolonlar: Tip, Marka, Model, Seri No, Müşteri, Lokasyon, İlgili Kişi, Kurulum.

**E-11 Planlı Bakımlar** (`A:567-669`)
- "Vadesi Gelen Cihaz İş Emirlerini Oluştur" (`maintenance.manage`).
- KPI: Bakım Sözleşmesi, Vadesi Gelen (sonraki hedef tarih ≤ bugün), Açık PB İş Emri (tıklanır), Tamamlanan PB Cihazı (tıklanır).
- Tablo: Firma (+adres), Ürünler, Sıklık, Yapılan Dönem (n/frekans), Sonraki Bakım, Cihaz İş Emirleri (n cihaz, m tamamlandı, düğme), Ücret (`finance.prices.view`).
- **Cihaz iş emirleri penceresi**: PB no, cihaz #sıra, seri, bölge, durum, "Bakım Formu Aç/Formu Gör"; "Eksik Cihaz İş Emirlerini Oluştur / Kontrol Et" (`maintenance.manage`).
- **Dijital bakım formu** (`A:598-658`): başlık "DENGE ELEKTRONİK | DİJİTAL TEKNİK SERVİS / PLANLI BAKIM FORMU"; özet (firma, cihaz, marka/model, durum); Seri No*, Bölge*, firma adresi (salt okunur); kontrol listesi (her maddede "Uygun ✓" kutusu + 4 seçenek, birbirine senkron); "Kontrol Edilenlerin Tümünü Uygun İşaretle" (onay sorusu, yalnız `Bekliyor` olanları); Yapılan İşlem, Yedek Parçalar, Teknisyen Notu*, Servis Sonucu* (5 seçenek), kapatma kaydı; Taslak Kaydet / Formu Tamamla. Salt okunur: iş `Kapatıldı` veya izin yok.

**E-12 Haberleşme Atölye** (`A:671-746`)
- Liste: Atölye No, İş Emri bağlantısı, Firma, Servis Türü, Marka/Model, Seri, Durum, Atanan, Giriş, Düzenle/Görüntüle.
- Form 4 bölüm: Firma/Temel (firma*, adres, kişi, e-posta, telefon, giriş tarih-saati, tahmini bitiş, Logo Form No, Ana Servis Kaydı); Kategori/Atama/Durum (entegrasyon firması vars. "Denge Telekom", servis türü*, durum, tamir bedeli, teslim alma tipi, teslim alan, teslim eden, teslim etme tipi, kargo takip no, atanan = Haberleşme personeli); Cihaz/Garanti/Aksesuar (marka*, model, seri*, proje, garanti başlangıç/bitiş, garanti durumu vars. "Garanti Değil", Aksesuar 1–5); Diğer (notlar, müşteri şikâyeti, cihaz durumu, onarım bilgisi).
- Durum `Tamamlandı`/`Teslim Edildi` seçilince tamamlanma tarihi = şimdi (istemci) (`A:739`).

**E-13 Kiralama** (`A:748-1033`)
- Sekmeler: Kiralama Kayıtları | Depo / Envanter. Birim filtresi (katalogdaki birimler).
- KPI: Kiralama Kaydı, Kirada, İade/Kontrol (İade Bekliyor+İade Alındı+Test / Kontrol), Toplam Ürün Kalemi.
- Liste: no, birim, kalem sayısı + ilk ürün, toplam adet, müşteri/lokasyon, tarih aralığı, durum, Düzenle/Operasyon.
- Yeni kayıt modalı: birim*, müşteri*, e-posta, proje, lokasyon, başlangıç* (bugün), bitiş* (yarın), ERP sorumlusu (Kiralama & Operasyon departmanı veya unvanında "Kiralama"), not; **çoklu ürün kalemi** (ürün*, adet*, seriler — satır/virgül, not, en az 1 kalem) ve **çoklu irtibat** (tür: Satın Alma/Saha Operasyon/Teknik Sorumlu/Diğer, ad*, unvan, telefon, e-posta, not). Birim değişince kalemler sıfırlanır.
- Düzenleme modalı: durum (12), tarihler, müşteri bilgileri, sorumlu, not, kalemler/irtibatlar (kaydet = composition PUT, sonra kayıt PUT); **Depodan Cihaz Atama** (kalem başına; aday = aynı ürün, Hazır+boşta veya bu kaleme bağlı); **Operasyon süreci** geçmişi + 5 kısayol + form (aşama, tarih-saat, ekip, depo, not).
- Envanter sekmesi: özet (Hazır/Boşta, Eksik/Kontrolde, Kirada), depo kartları (hazır/kayıtlı, Depo Adını Düzenle), filtreler (arama, depo, durum), tablo, "Cihaz / Stok Ekle", Düzenle.
- [⚠ HATA H-04] Kiralamadan teklif kısayolu olayı tanımlı (`A:1977`) ama düğme hiçbir yerde üretilmiyor (V1.4 vaadi `CL-1_4:79` çalışmıyor).

**E-14 POC / Mobilite** (`A:1088-1091`): POC, Mobilite, Araç Takip birimlerinin tüm iş emirleri, standart iş tablosu.

**E-15 Teklif Yönetimi** (`A:1208-1215`, `A:1880-1894`, `A:1979-1982`)
- Liste: no, iş emri, birim, müşteri, durum, toplam (TL), tarih; PDF; Onayla (`offers.approve`, durum Taslak/Onay Bekliyor); Mail Gönder (`offers.send`, durum Onaylandı; alıcı istemi).
- Yeni teklif: ilgili iş emri (opsiyonel), birim*, müşteri*, e-posta, geçerlilik (bugün+15 gün), not; kalem satırları (kod, açıklama, adet, birim fiyat, iskonto %, KDV % vars. 20); açıklaması boş satırlar gönderilmez. İş emrinden açılırsa müşteri/e-posta/konu dolu gelir.

**E-16 Raporlar** — Bölüm 5.3.

**E-17 Saha / Zaman Takibi** (`A:1436-1567`)
- "Benim Canlı Faaliyetim": aktif sayaç (faaliyet + **15 sn'de bir güncellenen** geçen süre); atandığım açık işler seçimi; faaliyet, bölge (vars. iş `siteArea`), not; Başlat / Faaliyeti Değiştir / Süreyi Bitir (onay sorusu).
- Yönetim özeti filtreleri: başlangıç (ay başı), bitiş (bugün), birim, teknisyen, arama. KPI: toplam kişi-saat, sahada, yol, bekleme, **mola (hariç)**, farklı iş, aktif sayaç.
- Yönetici (`reports.view`): CSV dışa aktar (yalnız `reports.export`), Tam Raporlara Git; **Şu Anda Çalışan Ekipler** (iptal: `assign`/`users.manage`, gerekçe istemi).
- Personel / kişi-saat dağılımı (iş, faaliyet, toplam, saha, yol, bekleme, mola hariç); "Kim, Nerede, Ne Kadar Çalıştı?" (ilk 300).

**E-18 Eğitim / Personel Gelişimi** (`A:1280-1434`)
- Üst: yıl (2020–2100), birim filtresi, "Excel için CSV" (`training.export`).
- 7 sekme:
  1. **Yönetim Özeti**: Yıllık gerçekleşme %, saha gözlem uygunluğu (yıl ortalaması), hedef yetkinlik % (mevcut ≥ hedef), 30/60/90 takip sayısı; birim bazlı ilerleme çubukları; **30/60/90 gün takip kuyruğu** (tamamlanan planın tamamlanma tarihine +30/+60/+90; aynı kişi+kurs+aşama gözlemi yoksa; Gecikti/Zamanı geldi/Yaklaşan; ilk 16; önceki yıl tamamlananlar dahil) [R-87]; kişi bazlı tablo + Gelişim Kartı.
  2. **Yıllık Plan**: toplu atama formu (eğitim*, yıl salt okunur, hedef tarih vars. yıl-12-15, gelişim hedefi, personel çoklu seçim, tümünü seç/temizle); plan tablosu (gecikmiş hedef kırmızı).
  3. **Eğitim Kataloğu**: kartlar (zorunlu/gelişim, kod, kategori, süre, birim, neden, beklenen davranış, başarı ölçütü, kontrol maddeleri ⚠ kritik); yeni eğitim formu (kod*, başlık*, kategori Teknik/İSG/Kişisel Gelişim/İş Süreci, birim, süre 0.5–24, zorunlu, neden, davranış, ölçüm, madde listesi `!` kritik).
  4. **Katılım ve Sınav**: oturum formu (eğitim, tarih, eğitmen vars. kullanıcı, süre, yer, not); katılım formu (oturum, personel, katıldı/katılmadı, ön/son puan, not); oturum tablosu (katılan sayısı, ön→son ortalama).
  5. **Saha Gözlemi**: personel*, eğitim* (kriterler dinamik), aşama İlk/30/60/90, tarih, ilgili iş emri (ilk 400), madde değerlendirme (Gözlenmedi/2/1/0), gözlemci notu, aksiyon planı, sonraki izleme; **kritik maddede 0 → onay uyarısı** [R-85]; kayıtlı gözlemler (puan rozeti ≥85 yeşil, ≥65 amber, aksi kırmızı; kritik kırmızı).
  6. **Yetkinlik Matrisi**: seviye açıklaması (1 Başlangıç, 2 Gözetimle, 3 Bağımsız, 4 Uzman/Eğitici); form (personel, yetkinlik, mevcut vars. 2, hedef vars. 3, tarih, sonraki, kanıt); matris (Hedefte/Gelişim gerekli).
  7. **Bireysel Gelişim Kartı**: kişi seçimi; özet (yıllık eğitim, hedef yetkinlik, gözlem sayısı); plan, yetkinlik, saha gelişim geçmişi.

**E-19 Depo** (`A:1270-1274`): `rentals.view` varsa kiralama envanter görünümü + "Atölyede/Kargoda/Beklemede" durumundaki iş emirleri.

**E-20 Muhasebe** (`A:1275-1278`): Onay Bekliyor/Onaylandı/Müşteriye Gönderildi/Kabul Edildi teklifleri (no, müşteri, durum, toplam).

**E-21 Personel / Organizasyon** (`A:1035-1086`, `A:2004-2022`)
- KPI: aktif, pasif/ayrılan, departman sayısı, ERP hesabı olan.
- Departman kartları (ana + ek departman sayılır; ilk 4 isim); tıklayınca liste filtresi.
- Yeni personel formu (`personnel.manage`): ad*, departman* (19 liste), unvan, operasyon birimi (Genel/Birimsiz + 5), yönetici (aktif personel), işe giriş (bugün), ek departmanlar (virgül), not; `users.manage` ile "ERP kullanıcı hesabı oluştur" (kullanıcı adı, rol, geçici şifre, ilk girişte değiştir, birimler, izinler — rol değişince varsayılan izinler).
- Liste: ad, departman (+ek), unvan, birim, yönetici, ERP kullanıcı/rol, Aktif/Ayrıldı; Düzenle, İşten Çıkış/Aktif Yap (onay), Yetkiler (bağlı hesap → kullanıcı düzenleme).

**E-22 Kullanıcı / Yetki** (`A:1217-1268`, `A:2024-2028`)
- Yeni kullanıcı: ad*, kullanıcı adı*, rol*, geçici şifre* (≥8), birimler (vars. hepsi işaretli), izin kutuları (rol değişince varsayılan), ilk girişte değiştir (vars. işaretli).
- Liste: ad, kullanıcı, rol, birimler, durum; Düzenle; Pasif/Aktif Yap (**`admin` kullanıcısında gizli**); Şifre Sıfırla (istem).
- Düzenleme modalı: ad, kullanıcı adı (`admin` için salt okunur), rol (değişince izinler varsayılana döner), birimler, izinler, sonraki girişte değiştir. Kendini düzenlerse oturum nesnesi güncellenir.

### 3.4 Modal / alt ekran listesi (18)

KPI detay (`A:258`), Takvim ziyaret (`A:474`), İş emri detay (`A:1608`), Tekli plan (`A:1864`), Toplu plan (`A:1819`), Toplu atama (`A:1720`), Bakım cihaz listesi (`A:567`), Bakım formu (`A:598`), Atölye kaydı (`A:684`), Kiralama oluştur (`A:867`), Kiralama düzenle/operasyon (`A:911`), Envanter tahsis (`A:984`), Envanter ekle/düzenle (`A:1001`), Depo adı (`A:1029`, istem), Personel düzenle (`A:1067`), Kullanıcı düzenle (`A:1228`), Teklif oluştur (`A:1886`), Canlı sayaç iptal gerekçesi (`A:1562`, istem).

---

## 4. Veritabanı (43 tablo, son birleşik şema)

Scriptler uygulama açılışında **alfabetik sırayla** ve yalnızca `DengeERP:RunDatabaseSetupOnStartup=true` iken çalışır (`P:24-45`, `P:3257-3269`); `GO` ile bölünür. Sıra: `DengeERP_Update` → `V15_Schema` → `V15_Seed` → `V17_Schema` → `V18_DeviceWorkOrders` → `ZZ_V110` … `ZZ_V120`. Ardından boş DB'de admin oluşturma (şifre ≥ 14) ve bakım üretimi (`P:33-34`, `P:3271-3295`).
[⚠ HATA H-15] `DengeERP_Update.sql` `USE DengeERP;` ile başlar (`S-UPD:1`) — farklı adlı (örn. `DengeERP_TEST`) veritabanına kurulumda yanlış DB'ye geçer.
Not: Canlı veritabanında bu scriptlerin dışında eski tablolar bulunabilir (V1.1'de bahsedilen `AppUsers`, `WorkOrders.CreatedByUserId` eski FK'si — `CL-1:43-45`, `S-UPD:161-166`). Veri aktarımından önce canlı şema ayrıca dökülmelidir.

Tip kısaltmaları: `NV(n)`=NVARCHAR(n), `NVM`=NVARCHAR(MAX), `DT2`=DATETIME2, `DEC(p,s)`, `BIT`, `PK`, `FK→`, `UQ`, `DF`=varsayılan, `CK`=check.

### 4.1 Çekirdek / Kullanıcı

**T-01 `ErpUsers`** (`S-UPD:141-159`) — UserId INT PK IDENTITY; Username NV(100) **UQ**; PasswordHash NV(200); PasswordSalt NV(200); FullName NV(150); RoleName NV(100); AllowedUnits NVM DF '' (pipe `|`); Permissions NVM DF '' (pipe, `*`=tümü); IsActive BIT DF 1; MustChangePassword BIT DF 1; CreatedAt DT2 DF; UpdatedAt DT2.

**T-02 `Personnel`** (`S-UPD:348-369`) — PersonnelId BIGINT PK; FullName NV(180); DepartmentName NV(180); AdditionalDepartments NVM (pipe); Title NV(180); UnitCode NV(100); ManagerName NV(180) (**isim metni**); StartDate DATE; EndDate DATE; IsActive BIT DF 1; ErpUserId INT **FK→ErpUsers**; Notes NV(1000); CreatedAt; UpdatedAt. Seed sonrası aynı `FullName`'li kullanıcıya otomatik bağlanır (`S-UPD:428-433`).

### 4.2 İş emri

**T-03 `WorkOrders`** (`S-UPD:4-31`, `:163-187`) — WorkOrderId BIGINT PK; WorkOrderNo NV(50) **UQ**; UnitCode NV(100); WorkType NV(150); CustomerName NV(250); ProjectName NV(250); Location NV(250); Subject NV(250); Description NVM; Priority NV(50) DF 'Normal'; Status NV(100) DF 'Müşteri Talebi'; CreatedByUserId INT NULL (eski); CreatedAt DT2 DF; RowVersion ROWVERSION; SystemName NV(150); SerialNo NV(200); CustomerEmail NV(250); UpdatedAt DT2; ClosedAt DT2; CreatedByErpUserId INT **FK→ErpUsers** (`FK_WorkOrders_ErpUsers`). İndeks `IX_WorkOrders_Unit_Status(UnitCode,Status,CreatedAt DESC)`.

**T-04 `WorkOrderAssignments`** (`S-UPD:33-46`) — AssignmentId BIGINT PK; WorkOrderId **FK→WorkOrders**; AssignedName NV(150) (**isim**); AssignmentRole NV(50) DF 'Teknisyen' (`Şef`/`Teknisyen`); IsActive BIT DF 1; AssignedAt DT2. İndeks (WorkOrderId,IsActive,AssignmentRole).

**T-05 `WorkOrderPlans`** (`S-UPD:48-65`, `S-111:2-25`) — WorkOrderPlanId BIGINT PK; WorkOrderId **FK**; PlanDate DATE; StartTime TIME; EstimatedMinutes INT; VehiclePlate NV(30); RouteGroupNo NV(50); PlanNote NV(1000); IsActive BIT DF 1; PlannedAt DT2; SiteName NV(250); SiteCity NV(100); SiteDistrict NV(120); SiteAddress NV(600); SiteArea NV(250); SiteContact NV(180); SitePhone NV(80); SiteDirections NV(1000). İndeks (WorkOrderId,IsActive).

**T-06 `WorkOrderDevices`** (`S-UPD:67-82`) — WorkOrderDeviceId BIGINT PK; WorkOrderId **FK**; SerialNo NV(200) NOT NULL (**metin**); ProductName NV(200); Brand NV(120); Model NV(120); IsActive BIT DF 1; AddedAt DT2.

**T-07 `WorkOrderStatusLogs`** (`S-UPD:84-99`) — StatusLogId BIGINT PK; WorkOrderId **FK**; OldStatus NV(100); NewStatus NV(100); Note NV(1000); ChangedByUserId INT; ChangedByName NV(150); ChangedAt DT2.

**T-08 `WorkTypeRules`** (`S-UPD:101-114`) — RuleId INT PK; UnitCode NV(100); WorkType NV(150); SerialRequiredOnCreate BIT; SerialRequiredOnClose BIT; IsActive BIT; **UQ(UnitCode,WorkType)**.

**T-09 `WorkOrderTimeLogs`** (`S-110:2-30`) — TimeLogId BIGINT PK; WorkOrderId **FK**; TechnicianName NV(200) (**isim**); ActivityType NV(40) **CK** ∈ {Saha Çalışması, Yol / Ulaşım, Bekleme, Uzaktan Destek, Atölye, Test / Kontrol, Diğer}; StartedAt DT2(0); EndedAt DT2(0); LocationNote NV(250); WorkNote NV(1000); CreatedByUserId INT; CreatedByName NV(200); CreatedAt DT2(0) DF; IsVoided BIT DF 0; VoidedAt; VoidedByName NV(200); **CK EndedAt > StartedAt ve ≤ 1080 dk**. İndeksler (TechnicianName,StartedAt) INCLUDE…, (WorkOrderId).

**T-10 `WorkOrderLiveSessions`** (`S-114:2-35`) — SessionId BIGINT PK; WorkOrderId **FK**; TechnicianUserId INT **FK→ErpUsers**; TechnicianName NV(200); ActivityType NV(40) **CK** (7 tür, `Mola / Ara` dahil); StartedAt DT2(0) DF; EndedAt DT2(0); StopReason NV(30) (`Faaliyet Değiştirildi`/`Bitirildi`/`İptal`); LocationNote NV(250); WorkNote NV(1000); ResultTimeLogId BIGINT; CancelledByUserId INT; CancelReason NV(500); **CK EndedAt ≥ StartedAt**; **filtreli UQ `UX_LiveSessions_OneActivePerUser(TechnicianUserId) WHERE EndedAt IS NULL`** (tek aktif sayaç).

### 4.3 Teklif

**T-11 `Offers`** (`S-UPD:189-214`) — OfferId BIGINT PK; OfferNo NV(50) **UQ**; WorkOrderId **FK→WorkOrders** NULL; UnitCode; CustomerName; CustomerEmail; Status NV(50) DF 'Taslak'; ValidUntil DATE; Notes NV(1000); SubTotal/DiscountTotal/VatTotal/GrandTotal DEC(18,2); CreatedByUserId; CreatedAt; ApprovedByUserId; ApprovedAt; SentAt.

**T-12 `OfferItems`** (`S-UPD:216-231`) — OfferItemId PK; OfferId **FK→Offers ON DELETE CASCADE**; ItemCode NV(100); Description NV(500); Quantity DEC(18,2) DF 1; UnitPrice DEC(18,2); DiscountPercent DEC(9,2); VatPercent DEC(9,2) DF 20.

**T-13 `EmailLogs`** (`S-UPD:233-248`) — EmailLogId PK; OfferId **FK→Offers**; Recipient NV(250); Subject NV(500); Status NV(50) (`Gönderildi`/`Hata`); ErrorMessage NV(1000); SentByUserId; SentAt.

### 4.4 Güvenlik cihaz / Bakım

**T-14 `SecurityDevices`** (`S-V15:3-29`) — SecurityDeviceId BIGINT PK; SourceKey NV(80) **UQ** (örn. `XRAY-00002-1`); SourceRowNo INT; DeviceType NV(100); Brand NV(120); Model NV(250); ProductRaw NV(500); SerialNo NV(200); CustomerName NV(250); Location NV(250); ContactName NV(180); DeliveryDateText NV(100) (Excel seri tarih metni, örn. `42724`); InstallStatus NV(100); Notes NV(1000); IsActive; ImportedAt. İndeks (DeviceType,Brand,Model,SerialNo).

**T-15 `MaintenanceContracts`** (`S-V15:31-52`) — MaintenanceContractId BIGINT PK; SourceKey NV(80) **UQ** (`BAKIM-0002`…); CustomerName; CurrentAddress NV(500); ProductsText NV(500) (**cihaz adedinin kaynağı**); FrequencyText NV(100); AnnualFrequency INT DF 0; MaintenanceFeeText NV(100) 🔒; PeriodText NV(150); CompletedCount INT DF 0; ContractTotal DEC 🔒; Total2026 DEC 🔒; IsActive; ImportedAt; UpdatedAt. (🔒 = `finance.prices.view`)

**T-16 `MaintenancePlans`** (`S-V15:54-76`) — MaintenancePlanId BIGINT PK; MaintenanceContractId **FK**; PlanYear INT; SequenceNo INT; TargetDate DATE; IsCompleted BIT; CompletedAt; GeneratedWorkOrderId **FK→WorkOrders** (V1.8 sonrası "ilk cihazın iş emri" anlamında, `CL-1_8:183-187`); CreatedAt; **UQ(ContractId,PlanYear,SequenceNo)**.

**T-17 `MaintenanceDeviceItems`** (`S-V17:2-21`, `S-V18:3-29`) — MaintenanceDeviceItemId BIGINT PK; MaintenancePlanId **FK**; SecurityDeviceId **FK→SecurityDevices** NULL; DeviceType NV(100) (`X-Ray` / `Kapı Tipi Metal Dedektörü`); DeviceOrdinal INT; SerialNo NV(200); Status NV(30) DF 'Bekliyor'; CompletedBy NV(180); CompletedAt; Notes NV(1000); CreatedAt; WorkOrderId **FK→WorkOrders**; Zone NV(250); PerformedWork NVM; SpareParts NV(1000); ServiceResult NV(80); **UQ(PlanId,DeviceType,DeviceOrdinal)**; **filtreli UQ(WorkOrderId) WHERE NOT NULL** (1 cihaz = 1 iş emri).

**T-18 `MaintenanceDeviceChecks`** (`S-V18:30-46`) — MaintenanceDeviceCheckId PK; MaintenanceDeviceItemId **FK**; CheckCode NV(60); CheckLabel NV(350); CheckResult NV(40) DF 'Bekliyor'; CheckedBy NV(180); CheckedAt; **UQ(ItemId,CheckCode)**.

### 4.5 Atölye

**T-19 `WorkshopTickets`** (`S-V15:78-132`) — WorkshopTicketId BIGINT PK; WorkshopNo NV(50) **UQ**; WorkOrderId **FK→WorkOrders**; LogoFormNo NV(80); LogoMainServiceNo NV(80); CompanyName NV(250); CompanyAddress NV(500); ContactName NV(180); CustomerEmail; CustomerPhone NV(100); EntryDate DT2 DF; EstimatedFinishDate DATE; CompletionDate DT2; IntegrationCompany NV(150); ServiceType NV(120); Status NV(100) DF 'Yeni Kayıt'; RepairAmount DEC(18,2); ReceiveType; ReceivedBy; DeliveredBy; DeliveryType; CargoTrackingNo NV(150); AssignedTo NV(180); Brand NV(120); Model NV(180); SerialNo NV(180) NOT NULL; WarrantyStartDate; WarrantyEndDate; WarrantyStatus NV(100); Accessory1..5 NV(120); ProjectName; Notes NVM; CustomerComplaint NVM; DeviceCondition NVM; RepairInfo NVM; CreatedByUserId **FK→ErpUsers**; CreatedAt; UpdatedAt. İndeks (Status,EntryDate DESC).

### 4.6 Kiralama / Depo

**T-20 `RentalProducts`** (`S-UPD:261-276`) — RentalProductId INT PK; UnitCode; Category NV(120); ProductCode NV(100); ProductName NV(250); RequiresSerial BIT; IsActive; DisplayOrder INT; **UQ(UnitCode,ProductCode)**.

**T-21 `RentalOrders`** (`S-UPD:310-346`) — RentalOrderId BIGINT PK; RentalNo NV(50) **UQ**; UnitCode; Category; RentalProductId **FK→RentalProducts**; ProductCode; ProductName; CustomerName; CustomerEmail; ProjectName; Location; ContactName NV(150); ContactPhone NV(80); Quantity INT DF 1; SerialNumbers NVM; StartDate DATE; EndDate DATE; Status NV(100) DF 'Talep'; ResponsibleName NV(150); Notes NV(1500); CreatedByUserId **FK→ErpUsers**; CreatedAt; UpdatedAt; ClosedAt. (Üst kayıttaki ürün/seri alanları **ilk kalemin yansıması**dır.)

**T-22 `RentalOrderItems`** (`S-112:3-18`) — RentalOrderItemId BIGINT PK; RentalOrderId **FK**; RentalProductId **FK**; Quantity INT **CK > 0**; SerialNumbers NVM; Notes NV(1000); CreatedAt.

**T-23 `RentalOrderContacts`** (`S-112:19-35`) — RentalOrderContactId PK; RentalOrderId **FK**; ContactType NV(60) DF 'Saha Operasyon'; FullName NV(180); JobTitle NV(180); Phone NV(80); Email NV(250); Notes NV(500).

**T-24 `RentalWarehouses`** (`S-112:36-50`) — RentalWarehouseId INT PK; Code NV(50) **UQ**; Name NV(120); IsActive. (Yedek parça stoğu da bu depoları kullanır.)

**T-25 `RentalInventory`** (`S-112:51-72`) — RentalInventoryId BIGINT PK; RentalProductId **FK**; RentalWarehouseId **FK**; SerialNo NV(200); Quantity INT DF 1 **CK > 0**; ConditionStatus NV(40) DF 'Hazır'; MissingNotes NV(1500); Notes NV(1500); RentalOrderItemId **FK→RentalOrderItems** NULL (tahsis); UpdatedAt. **Filtreli UQ(RentalProductId,SerialNo) WHERE SerialNo NOT NULL**.

**T-26 `RentalStageHistory`** (`S-112:73-94`) — RentalStageHistoryId PK; RentalOrderId **FK**; StageName NV(80); EventAt DT2; TeamName NV(200); RentalWarehouseId **FK**; Notes NV(1500); SerialSnapshot NVM; CreatedByUserId **FK→ErpUsers**; CreatedAt.

Veri taşıma kuralı: eski tek ürünlü kiralamalar ilk kalem olarak, eski irtibat `Saha Operasyon` kişisi olarak kopyalanır (`S-112:95-108`).

### 4.7 Eğitim

**T-27 `TrainingCourses`** (`S-113:3-20`) — CourseId INT PK; CourseCode NV(50) **UQ**; Title NV(220); Category NV(80); UnitCode NV(100) NULL (=tüm birimler); Reason NV(1200); TargetBehavior NV(1200); SuccessMetric NV(800); DurationHours DEC(5,2) DF 2; Mandatory BIT; IsActive BIT; CreatedAt.
**T-28 `TrainingCriteria`** (`S-113:21-32`) — CriterionId INT PK; CourseId **FK**; CriterionText NV(450); IsCritical BIT; SortOrder INT.
**T-29 `TrainingPlans`** (`S-113:33-49`) — TrainingPlanId BIGINT PK; PersonnelId **FK→Personnel**; CourseId **FK**; PlanYear INT **CK 2020–2100**; DueDate DATE; Status NV(30) DF 'Planlandı'; PersonalGoal NV(900); CompletedAt; CreatedAt; **UQ(PersonnelId,CourseId,PlanYear)**.
**T-30 `TrainingSessions`** (`S-113:50-63`) — TrainingSessionId BIGINT PK; CourseId **FK**; SessionDate DATE; TrainerName NV(180); DurationHours DEC(5,2) **CK 0<x≤24**; Location; Notes; CreatedAt.
**T-31 `TrainingAttendance`** (`S-113:64-78`) — TrainingAttendanceId PK; TrainingSessionId **FK**; PersonnelId **FK**; Attended BIT; ScoreBefore/ScoreAfter INT **CK 0–100**; Notes; CreatedAt; **UQ(SessionId,PersonnelId)**.
**T-32 `CompetencyCatalog`** (`S-113:79-90`) — CompetencyId INT PK; Code NV(60) **UQ**; Name NV(220); UnitCode; SuggestedTargetLevel INT DF 3 **CK 1–4**; IsCritical BIT.
**T-33 `PersonnelCompetencies`** (`S-113:91-107`) — PersonnelCompetencyId PK; PersonnelId **FK**; CompetencyId **FK**; CurrentLevel/TargetLevel **CK 1–4**; AssessedAt DATE; AssessedBy NV(180); Evidence NV(1200); NextReviewDate; UpdatedAt; **UQ(PersonnelId,CompetencyId)**.
**T-34 `TrainingObservations`** (`S-113:108-127`) — ObservationId BIGINT PK; PersonnelId **FK**; CourseId **FK**; WorkOrderId **FK→WorkOrders** NULL; ObservedOn DATE; ObserverName NV(180); PhaseDays **CK ∈ (0,30,60,90)**; Score DEC(5,2); CriticalFailure BIT; Notes NV(1600); ActionPlan NV(1600); NextReviewDate; CreatedAt.
**T-35 `TrainingObservationRatings`** (`S-113:128-137`) — ObservationId **FK**; CriterionId **FK**; Rating **CK ∈ (-1,0,1,2)**; **PK(ObservationId,CriterionId)**.

### 4.8 Operasyon / Stok / Maliyet (V1.20)

**T-36 `OpsSlaTargets`** (`S-120:2-7`) — Priority NV(50) **PK**; ResolutionHours INT **CK 1–8760**.
**T-37 `OpsHolds`** (`S-120:8-13`) — HoldId BIGINT PK; WorkOrderId **FK**; Reason NV(100); Notes NV(1000); PreviousStatus NV(100); CreatedBy **FK→ErpUsers**; CreatedAt; ReleasedAt; **filtreli UQ(WorkOrderId) WHERE ReleasedAt IS NULL**.
**T-38 `OpsAlertAcks`** (`S-120:14-16`) — AlertKey NV(120); UserId **FK→ErpUsers**; AckAt; **PK(AlertKey,UserId)**.
**T-39 `ServicePartCatalog`** (`S-120:17-19`) — PartId INT PK; Code NV(80) **UQ**; Name NV(200); Unit NV(20) DF 'Adet'; MinimumQty DEC(18,3) **CK ≥0**; UnitCost DEC(18,2) **CK ≥0** 🔒.
**T-40 `ServiceStockBalances`** (`S-120:20-22`) — PartId **FK**; WarehouseId **FK→RentalWarehouses**; Quantity DEC(18,3) **CK ≥ 0**; **PK(PartId,WarehouseId)**.
**T-41 `ServicePartMovements`** (`S-120:23-25`) — MovementId BIGINT PK; PartId **FK**; WarehouseId **FK**; WorkOrderId **FK** NULL; Kind NV(10) **CK ∈ (Giriş, Çıkış)**; Quantity DEC(18,3) **CK > 0**; UnitCost DEC(18,2) (anlık); CreatedBy **FK→ErpUsers**; CreatedAt.
**T-42 `OpsLaborRates`** (`S-120:26-31`) — UnitCode NV(100) **PK**; HourlyCost DEC(18,2) **CK ≥ 0** 🔒.
**T-43 `OpsWorkFinancials`** (`S-120:32-34`) — WorkOrderId BIGINT **PK + FK**; Revenue DEC **CK ≥0** 🔒; OtherCost DEC **CK ≥0** 🔒; Notes NV(1000); UpdatedBy **FK→ErpUsers**; UpdatedAt.

### 4.9 Seed ve sabit listeler (38)

| # | Liste | İçerik | Kaynak |
|---|---|---|---|
| L-01 | **Birimler (5)** | Güvenlik Sistemleri, Haberleşme, POC, Mobilite, Araç Takip | `P:3873`, `A:8` |
| L-02 | **İzin kataloğu (34)** | dashboard.view; workorders.view/create/edit/assign/plan/close; offers.view/create/approve/send; reports.view/export; training.view/manage/observe/export; users.manage; warehouse.view/manage; operations.manage; finance.costs.manage; accounting.view; rentals.view/create/edit; personnel.view/manage; devices.view; finance.prices.view; maintenance.view/manage; workshop.view/manage (Türkçe etiketleriyle) | `P:3875-3911` |
| L-03 | **Roller (12) ve varsayılan izinleri** | Admin(`*`); Üst Yönetim, Teknik Servis Müdürü, Teknik Servis Müdür Yardımcısı (31 izin, `users.manage` + `finance.prices.view` dahil; `warehouse.manage`, `operations.manage`, `finance.costs.manage` **hariç**); Genel Koordinatör (13); Operasyon Uzmanı (10); Şef (18); Teknisyen (7); Muhasebe (7); Depo (4); Kiralama Operasyon (7); İnsan Kaynakları (7, `users.manage` dahil). Bilinmeyen rol → `workorders.view` | `P:3921-3935`, `P:2804` |
| L-04 | **Departmanlar (19)** | Üst Yönetim … Muhasebe Yönetimi | `P:3913-3919` |
| L-05 | **İş türü kuralları (18)** | Güvenlik: Atölye Tamir(1,1), Saha Arızası(0,1), Saha Kurulumu / Devreye Alma(0,1), Kontrol / Test(0,1), **Planlı Bakım(0,1)**; Haberleşme: Atölye Teknik Servis(1,1), Saha Arızası(0,1), Saha Kurulumu(0,1), Kiralık El Telsizi Hazırlığı(1,1), Kiradan Dönen El Telsizi Testi(1,1); Mobilite: Kurulum(0,1), Arıza(0,1); Araç Takip: Kurulum, Arıza, Bakım (0,1); POC: Uzaktan Müdahale, Telefonla Destek, Yerinde Müdahale (0,0). (açılış, kapanış) | `S-UPD:116-139`, `S-V15:136-144` |
| L-06 | **Arayüz iş türleri (birime göre)** | Güvenlik 5 (+Plansız Bakım), Haberleşme 10 (+Test / Devreye Alma, Programlama / Konfigürasyon, Keşif / Kapsama Çalışması, AR-GE Çalışması, Plansız Bakım), POC 3, Mobilite 3 (+Talep), Araç Takip 4 (+Talep). Kural tablosunda olmayanlar yedek kurala düşer [R-13] | `A:9-15` |
| L-07 | **Sistem / ürün listesi** | Güvenlik 2, Haberleşme 10, POC 3, Mobilite 3, Araç Takip 3 | `A:16-22` |
| L-08 | **İş emri durumları (14)** | Müşteri Talebi, Planlamada, Planlandı, Yola Çıkıldı, Sahada, İşlemde, Atölyede, Kargoda, Beklemede, Test / Kontrol, Tamamlandı, Kapatıldı, Tekrar Açıldı, İptal | `A:30` |
| L-09 | **POC durumları (12)** | Müşteri Talebi, Planlamada, Planlandı, İnceleniyor, Telefonla Destek, Uzaktan Müdahale, Yerinde Müdahale, Beklemede, Tamamlandı, Kapatıldı, Tekrar Açıldı, İptal | `A:31` |
| L-10 | **Öncelikler** | Arayüz: Normal, Yüksek, Kritik; SLA: Kritik 12 sa, Yüksek 24, Normal 72, Düşük 120; tanımsız öncelik 72 sa | `A:297`, `S-120:5`, `O:31` |
| L-11 | **Sabit personel yedek listesi** | Birim başına şef/teknisyen isimleri (Hakan Erdal …) | `A:23-29` |
| L-12 | **Organizasyon personeli (47 kişi)** | Ad, departman, ek departman, unvan, birim, yönetici; isimle tekrar etmez | `S-UPD:371-426` |
| L-13 | **X-Ray kontrol maddeleri (11)** | XR_EXT gövde/kapak/muhafaza; XR_CURTAIN kurşun perde; XR_ESTOP acil durdurma; XR_INTERLOCK kapak kilitleri; XR_BELT konveyör; XR_IMG görüntü kalitesi; XR_TEST test parçası; XR_LIGHT ikaz/ses; XR_CLEAN temizlik; XR_FAULT hata kaydı/kablo; XR_SAFETY radyasyon güvenliği kayıtları | `P:3107-3120` |
| L-14 | **Kapı dedektörü kontrol maddeleri (10)** | MD_EXT panel/gövde; MD_POWER enerji/kablo; MD_BOOT açılış/self-test; MD_ALARM sesli/ışıklı alarm; MD_ZONES algılama bölgeleri; MD_TEST test nesnesi; MD_SENS hassasiyet; MD_COUNTER sayaç; MD_FALSE yanlış alarm; MD_CLEAN temizlik | `P:3121-3133` |
| L-15 | **Kontrol sonuçları (4)** | Bekliyor, Uygun, Uygunsuz, Kontrol Edilemedi | `P:2454` |
| L-16 | **Servis sonuçları (5)** | Tamamlandı, Tekrar Gidilecek, Teklif Sunulacak, Servise Alındı, Servis İptal | `P:2457` |
| L-17 | **Güvenlik cihaz kütüğü (1.324 satır)** | Tip × marka: X-Ray (Power Guard 457, SC 425, Diğer 77, Dahua 17, Rapiscan 8, Smiths Heimann 1), Kapı Dedektörü (Power Guard 207, SC 26, Dahua 6, Diğer 1), Diğer Güvenlik Cihazı (Power Guard 92, Diğer 5, Dahua 1, L3 1). 4 MERGE bloğu; SourceKey ile idempotent | `S-SEED:4-2343` |
| L-18 | **Bakım sözleşmeleri (87)** | `BAKIM-0002`…`BAKIM-0088`; MERGE'de `CompletedCount = max(mevcut, seed)` (geri gitmez) | `S-SEED:2346-2444` |
| L-19 | **Kiralama ürünleri (23)** | Güvenlik: X-Ray PG-5030/6040/6550/100100 (seri), Kapı PG-3000-KING/PG-2000-KING/PGDH-D118 (seri), 13 bariyer (seri yok); Haberleşme: HYT-DMR, HYT-TETRA, HYT-LTE-POC (seri) | `S-UPD:278-308` |
| L-20 | **Depolar (3)** | DEPO-1 "Depo 1", DEPO-2, DEPO-3 (ad sonradan değişebilir) | `S-112:46-50` |
| L-21 | **Kiralama durumları (12)** | Talep, Teklif, Planlama, Hazırlanıyor, Teslimata Hazır, Teslim Edildi, Kirada, İade Bekliyor, İade Alındı, Test / Kontrol, Kapandı, İptal | `P:1146`, `A:32` |
| L-22 | **Kiralama aşamaları (5)** | Sevk Edildi, Kurulum Yapıldı, Devreye Alındı, Toplandı, Depoya Alındı | `P:1441` |
| L-23 | **Envanter durumları (4)** | Hazır, Hazır Değil, Kirada, Kontrolde | `P:1341` |
| L-24 | **İrtibat türleri (4)** | Satın Alma, Saha Operasyon, Teknik Sorumlu, Diğer (API boşsa `Diğer`) | `A:776`, `P:3247` |
| L-25 | **Atölye markaları (6)** | HYTERA, HYT, HQT, MOTOROLA, KIRISUN, ASELSAN | `A:671` |
| L-26 | **Atölye servis türleri (5)** | Arıza Onarımı, Garanti Onarımı, Dış Servis, Yazılım / Frekans Güncelleme, Setra - Kiralama Takip | `A:672` |
| L-27 | **Atölye durumları (7)** | Yeni Kayıt, Onarımda, Beklemede, Test / Kontrol, Tamamlandı, Teslim Edildi, İptal | `A:673` |
| L-28 | **Aksesuarlar (9)** | ADAPTÖR, ANTEN, ASKI İPİ, BATARYA, KAPAK, KLİPS, KULAKLIK, TAŞIMA ÇANTASI, ŞARJ CİHAZI | `A:674` |
| L-29 | **Canlı faaliyet türleri (7)** | Saha Çalışması, Yol / Ulaşım, Bekleme, Uzaktan Destek, Atölye, Test / Kontrol, **Mola / Ara** | `P:1936`, `A:1437` |
| L-30 | **Manuel süre faaliyetleri (7)** | Aynı ilk 6 + **Diğer** (Mola yok) | `P:2122` |
| L-31 | **Teklif durumları (6)** | Taslak, Onay Bekliyor, Onaylandı, Kabul Edildi, Reddedildi (+ sistemce `Müşteriye Gönderildi`) | `P:866`, `P:945` |
| L-32 | **Eğitim kursları (7)** | ISG-SAH-01 (zorunlu, 3 sa), ILET-01, XR-BAK-01, KMD-BAK-01, TELSIZ-01, POC-01, MOB-01 | `S-113:139-151` |
| L-33 | **Eğitim kontrol maddeleri (29)** | Kurs başına 3–5 madde, kritik işaretli | `S-113:153-188` |
| L-34 | **Yetkinlik kataloğu (8)** | ISG(4,kritik), RAPOR(4), ILETISIM(3), XR(3,kritik), KAPI, RADYO, POC, MOB | `S-113:189-202` |
| L-35 | **Eğitim kategorileri** | Teknik, İSG, Kişisel Gelişim, İş Süreci (API vars. Gelişim) | `A:1346`, `P:1552` |
| L-36 | **Gözlem aşamaları / puanlar** | 0/30/60/90; -1 Gözlenmedi, 0 Uygun değil, 1 Geliştirilmeli, 2 Uygun | `A:1363`, `A:1370` |
| L-37 | **Birim saatlik iç maliyet** | 5 birim, başlangıç 0 | `S-120:29-31` |
| L-38 | **Rozet eşikleri** | Gözlem puanı ≥85 yeşil, ≥65 amber; yetkinlik 1–4 açıklaması | `A:1291`, `A:1382` |

---

## 5. Raporlar ve çıktılar

### 5.1 Excel — 8 sayfa (`P:2191-2229`, `P:3638-3790`) [✔K indirme]

**Ortak filtre/veri mantığı**
- Kaynak: kullanıcının görebildiği iş emirleri (birim + teknisyen kısıtı).
- `kind`: `maintenance` = iş no `PB-` ile başlar **veya** iş türü `Planlı Bakım`; `service` = diğerleri (`P:3638-3639`).
- unit / status / workType = tam eşleşme ("Tümü" = filtresiz); chief = şef adı içerir; person = teknisyen listesi içerir; customer = müşteri/lokasyon/iş no/konu/seri içerir.
- Tarih esası `dateField`: `created` (vars.) açılış, `plan` plan tarihi, `closed` kapanış (yalnız `ClosedAt` dolu olanlar). Tarih filtresi varsa tarihi olmayan iş dışlanır.
- **Süre kayıtları iş emri tarih filtresine değil, faaliyet başlangıç tarihine** göre süzülür; person filtresi teknisyen adına, customer filtresi bölge notu + iş alanlarına uygulanır; süre kayıtları **tarih/kişi/müşteri dışındaki iş filtrelerini** (`baseRows`) kullanır. [R-92]
- Kişi-saat = Σ(dakika)/60, 2 ondalık, nokta ayraçlı; **dakika = DATEDIFF(saniye)/60 tamsayı** (`P:3431`).
- Biçim: başlık satırı lacivert/beyaz kalın (Aptos), detay sayfalarında **sabit başlık + AutoFilter**; kolon genişliği ilk 60 satıra göre 14–48; sayısal görünen hücreler gerçek sayı (baştaki sıfırlı metinler metin kalır — seri no koruması) (`P:3739-3774`). Native PivotTable **değil** (sayfada açıklama).

| Sayfa | Kolonlar / içerik | Hesap mantığı |
|---|---|---|
| **1. Yönetim Özeti** | Başlık; Dönem; Toplam İş Emri; Günlük Servis İş Emri; Planlı Bakım İş Emri; Açık Günlük Servis; Açık Planlı Bakım; Tamamlanan/Kapatılan İş; Gerçek Kişi-Saat; Sahada Çalışma Saati; Yol Saati; Bekleme Saati; Süre Girilen Farklı İş; **Bu Seçimde Süre Kaydı Eksik İş**; 4 açıklama satırı (tahmini süre kullanılmaz; tarih esası; 2×2=4 kişi-saat; pivot değildir) | Açık = Tamamlandı/Kapatıldı/İptal dışı; Tamamlanan = Tamamlandı+Kapatıldı (`P:3652-3672`) |
| **2. Günlük Servis** | İş Emri No, Açılış, Birim, İş Türü, Müşteri, Proje, Lokasyon (siteName ?? lokasyon), Şehir, İlçe, Açık Adres, Bina / Bölge, Saha Yetkilisi, Saha Telefonu, Ulaşım Notu, Sistem, Seri No, Konu, Öncelik, Durum, Şef, Teknisyenler, Plan Tarihi, Plan Saati, Tahmini Süre (dk), Araç, Rota, Plan Notu, Kapanış, Gerçek Kişi-Saat, **Süre Kaydı Durumu** (`SÜRE KAYDI YOK` / `Kayıtlı`) — 30 kolon | Kişi-saat yalnız filtrelenmiş süre kayıtlarından (`P:3674-3681`) |
| **3. Planlı Bakım** | Aynı 30 kolon, bakım işleri | `P:3682` |
| **4. Birim Durum** | Birim, Kategori (Günlük Servis/Planlı Bakım), Toplam, Açık, Tamamlanan, Kritik | Birim × 2 kategori; Kritik = öncelik Kritik (açık/kapalı fark etmez) (`P:3683-3689`) |
| **5. Aylık Özet** | Ay (yyyy-MM / "Tarih yok"), Kategori, Açılan İş, Tamamlanan İş, Kritik İş | Ay = seçilen tarih esasına göre (`P:3690-3694`) |
| **6. Personel KPI** | Personel, Gerçek Kişi-Saat, Farklı İş, Faaliyet Kaydı, Saha, Yol, Bekleme, Uzaktan, Atölye, Test, Diğer Saat | Süre kayıtlarından teknisyen adına göre, toplam saate göre azalan (`P:3695-3701`) |
| **7. Süre Hareketleri** | İş Emri, Kategori, Birim, Teknisyen, Müşteri, Şehir, İlçe, Lokasyon, Açık Adres, Bulunduğu Bölge, Faaliyet, Başlangıç, Bitiş, Süre (dk), Gerçek Saat, Teknisyen Notu, Kaydeden, Kayıt Tarihi | Başlangıca göre artan (`P:3702-3704`) |
| **8. Müşteri Lokasyon** | Müşteri, Şehir, Lokasyon / Bölge, Birim, Farklı İş, Teknisyen, Kayıt Sayısı, Kişi-Saat, Sahada, Yol, Bekleme | Grup: müşteri + şehir + (bölge notu ?? tesis ?? lokasyon) + birim + teknisyen; kişi-saate göre azalan (`P:3705-3709`) |

### 5.2 CSV çıktıları (3)

| Çıktı | Kolonlar | Kurallar | Kaynak |
|---|---|---|---|
| Eğitim planı `DengeERP_Egitim_Plani_{yıl}.csv` | Personel; Eğitim; Yıl; Hedef Tarih; Durum; Tamamlanma; Son Sınav (en son oturumun son puanı) | UTF-8 BOM, `;` ayraç, tırnaklı; **CSV enjeksiyonu koruması** (`= + - @` ile başlayana `'`); birim kapsamı | `P:1712-1731` |
| Operasyon `DengeERP_Operasyon.csv` | İş Emri; Birim; Müşteri; Tür; Durum; Oluşturma; Plan; Teknisyen | Görünür tüm işler; BOM; `;`; enjeksiyon koruması (`= + - @ \t \r`) | `O:259-265`, `O:66-70` |
| Personel süreleri `DengeERP_V114_Personel_Sureleri.csv` (**istemcide üretilir**) | Teknisyen; İş Emri; Birim; Müşteri; Lokasyon; Faaliyet; Başlangıç; Bitiş; Dakika; Not | Zaman ekranı filtreleri; `reports.export` istemcide kontrol; BOM; enjeksiyon koruması | `A:1548-1561` |

### 5.3 Web rapor ekranı (E-16) (`A:1092-1206`, `A:1984-2002`)

- Önayarlar: Güncelle, Bugün, Bu Hafta (pazartesi), Bu Ay, Tüm Tarihler; **ilk açılış tüm tarihler**. Filtreler: tarih esası, başlangıç, bitiş, kategori, birim, durum (14), iş türü (mevcut verilerden), teknisyen, şef, müşteri/lokasyon/seri (anlık).
- Yönetim özeti 6 KPI: Toplam İş, Açık Günlük Servis, Açık Planlı Bakım, Tamamlanan, Plan Bekleyen, Kritik Açık; servis/bakım ikili özet.
- Gerçek mesai 6 KPI: Kayıtlı Kişi-Saat, Süresi Girilen İş, Aktif Teknisyen, Sahada Çalışma, Yol Süresi, **Süre Kaydı Olmayan**.
- Kişi-saat pivotları (7 faaliyet kolonu + toplam satırı): Teknisyen; Müşteri • bölge; Ay • birim.
- Süre hareketleri tablosu (ilk 200).
- Çapraz özetler: Birim/Kategori × durum kovası; Ay × durum kovası. Kovalar: `Talep / Planlama`, `Planlandı`, `İşlemde` (Sahada, İşlemde, Yola Çıkıldı, Atölyede, Test / Kontrol), `Beklemede` (Beklemede, Kargoda), `Tamamlandı`, `İptal` (`A:1109-1116`).
- Personel iş yükü (atanan, servis, bakım, tamamlanan; çoklu teknisyen notu); filtrelenmiş iş emirleri (ilk 150).
- Excel düğmesi (`reports.export`): start > end engeli; **boş start/end parametreleri URL'den çıkarılır** (V1.20.1 düzeltmesi, `A:1999`, `HOTFIX_V1201.txt`) [✔K].

### 5.4 Teklif PDF düzeni (`P:3573-3636`)

- A4 (595×842), tek sayfa, Helvetica 11 pt, satır aralığı 14, sol 50 / üst 790.
- Satırlar: `DENGE ELEKTRONIK - TEKNIK SERVIS TEKLIFI`; Teklif No; Tarih (dd.MM.yyyy); Gecerlilik; Musteri; Is Emri; Birim; boş; `URUN / HIZMET KALEMLERI`; **ilk 15 kalem** `Açıklama | adet x birim fiyat TL | Isk %x | KDV %y`; boş; Ara Toplam; Iskonto; KDV; GENEL TOPLAM; Not (varsa).
- Türkçe karakterler ASCII'ye çevrilir (Ç→C, Ğ→G, İ→I, ı→i …), diğer ASCII dışı → `?`. Logo/imza/çok sayfa yok. Dosya adı `{OfferNo}.pdf`.
- E-posta: konu "Denge Elektronik Teknik Servis Teklifi - {No}", sabit Türkçe gövde, PDF ek (`P:922-924`).

---

## 6. İş kuralları (88 kural; R-01 … R-96)

### 6.1 Kimlik, yetki, görünürlük
- **R-01** Şifre PBKDF2-SHA256 / 120.000 / 16B tuz / 32B; giriş başarısızlığında pasif ile yanlış şifre ayırt edilmez (`P:92`, `P:2827-2844`).
- **R-02** `AllowedUnits` boş = **tüm birimler**; Admin/`*` tüm birimler (`P:2807`).
- **R-03** Rol adı `Teknisyen` olan kullanıcı yalnız **isim eşleşmesiyle** atandığı işleri görür/işler (`P:3385-3401`, `P:3495-3502`).
- **R-04** Şifre ≥ 8; ilk giriş/sıfırlama sonrası zorunlu değişim; boş DB ilk admin şifresi ≥ 14 (`P:118`, `P:3280`).
- **R-05** Kullanıcı oluştur/güncellede boş izin listesi → rol varsayılanı, boş birim → tüm birimler (`P:213-216`, `P:253-258`). Yetkiler kişiye özel düzenlenebilir; rol yalnız şablon.
- **R-06** Kullanıcı güncellenince açık oturumlarına yeni yetki anında yansır; personel pasifleşince bağlı hesap pasif + oturumlar silinir (`P:297-298`, `P:1890-1899`).
- **R-07** Numara formatları: **`SRV-YYYYMM-####`** (iş emri + atölye bağlı iş emri), **`PB-YYYYMM-####`** (cihaz bakım; **YYYYMM = bakım hedef ayı**, oluşturma ayı değil), **`TKL-YYYYMM-####`**, **`KIR-YYYYMM-####`**, **`AT-YYYYMM-####`**, **`TPL-`+16 hex** (toplu ziyaret). Sıra = aynı önekteki `MAX(sağ 4 hane)+1`, `UPDLOCK,HOLDLOCK` ile; her ay sıfırlanır; PB'de > 9999 → hata, diğerlerinde taşma kontrolü yok (`P:386-393`, `P:814-821`, `P:1098-1105`, `P:2643-2650`, `P:2677-2684`, `P:3076-3082`, `P:685`).
- **R-08** Fiyat/maliyet alanları API'de `finance.prices.view` yoksa null: bakım ücreti/toplamları, yedek parça birim maliyeti, maliyet analizi ucu tamamen (`P:2329-2333`, `O:173`, `O:217`). [⚠ BOŞLUK H-13: teklif tutarları ve atölye tamir bedeli maskelenmiyor]
- **R-09** Maliyet yazma (`finance.costs.manage`) ayrı izin; parça maliyeti > 0 girişi de bu izne bağlı (`O:181`, `O:240`, `O:249`).

### 6.2 İş emri
- **R-10** Seri no **metin**: `, ; \n \r` ile bölünür, kırpılır, boşlar atılır, büyük/küçük harf duyarsız tekilleştirilir; harf/tire/nokta/`/`/baştaki sıfır korunur (`P:2810`, `A:608`, `CL-1_9:225-226`).
- **R-11** Açılışta seri zorunluluğu `WorkTypeRules.SerialRequiredOnCreate` (`P:378-380`).
- **R-12** Kapanışta seri zorunluluğu `SerialRequiredOnClose`; aktif cihaz serileri yoksa iş emri `SerialNo` alanına bakılır (`P:484-487`, `P:520-522`).
- **R-13** Kural satırı yoksa yedek: açılışta zorunlu ⇔ iş türü "Atölye" içerir; kapanışta zorunlu ⇔ "Atölye/Saha/Kurulum/Arıza" içerir (`P:3380-3382`; istemci yedeği yalnız "Atölye" `A:135` — **farklı**).
- **R-14** Kapanış durumları: `Tamamlandı`, `Kapatıldı`, `Çözüldü`; `ClosedAt` yalnız `Kapatıldı`'da yazılır; raporlarda "tamamlanan" = Tamamlandı + Kapatıldı; "açık" = bu ikisi ve İptal dışı (`P:2808`, `P:527`, `P:3650`).
- **R-15** Atama = isim metni; her kaydetme önceki aktif atamaları pasifler (geçmiş satırlar korunur); şef = en son aktif şef satırı (`P:556-566`, `P:3450`).
- **R-16** Toplu atama: 1–150 iş, tek birim, kapalı iş yok, ≥1 şef/teknisyen, ≤30 teknisyen, isim ≤150, tek transaction, plan değişmez, tarihçe notu (`P:573-614`).
- **R-17** Toplu planlama: aynı müşteri+lokasyon+birim, planlanmamış ve açık, 15–1440 dk, tarih+saat zorunlu, tek transaction; her iş ayrı plan/atama/durum; ortak `TPL-` rota grubu (`P:649-720`).
- **R-18** **Çakışma kuralı** [İSTEMCİ]: aynı gün, zaman aralığı kesişimi; aynı araç plakası veya ortak teknisyen veya aynı şef; aynı `TPL-` ziyaretinin kendi işleri hariç; varsayılan başlangıç 09:00, süre 60 dk. Sunucuda kontrol **yok** (`A:357-406`).
- **R-19** Takvim kompakt ziyaret grubu = gün + birim + müşteri + tesis + şehir; hafta 4, ay 3 ziyaret sınırı (`A:443-505`).
- **R-20** Saha alan uzunlukları: tesis 250, şehir 100, ilçe 120, adres 600, bölge 250, yetkili 180, telefon 80, ulaşım 1000 (`P:3298-3302`).
- **R-21** Saha önerisi şehri/ilçeyi/telefonu tahmin etmez; dolu form alanları ezilmez (`P:643-646`, `A:1806-1813`).
- **R-22** Planlı bakım işi: arayüzde Tamamlandı/Kapatıldı seçilemez, seri no detaydan güncellenemez (formdan) (`A:1618`, `A:1626`).
- **R-23** Her durum değişikliği, toplu atama, toplu/tekli plan, bakım formu tamamlama, atölye açılışı **durum geçmişine** yazılır (eski, yeni, not, kullanıcı id+ad, zaman) (`P:3349-3361`). Bekletme/serbest bırakma ve atölye güncellemesi yazmaz.
- **R-24** Yeni iş durumu `Müşteri Talebi`; atölyeden açılan iş `Atölyede` (`P:400`, `P:2657`).
- **R-25** Bakım (kategori) ayrımı: iş no `PB-` önekli **veya** iş türü `Planlı Bakım`; günlük servis KPI/listeleri bakımı içermez (`P:3638`, `O:9`, `A:127`).

### 6.3 Planlı bakım üretimi (1 cihaz = 1 PB iş emri)
- **R-30** Cihaz bakım iş emri (MaintenanceDeviceItems'a bağlı) durum ucundan kapatılamaz ve seri ucundan güncellenemez; yalnız bakım formu (`P:442-445`, `P:510-513`).
- **R-31** Kapatılmış cihaz bakım iş emri tekrar açılamaz; kapatılmış form değiştirilemez (`P:502-503`, `P:2473`).
- **R-32** Yıllık plan dönemleri: her aktif sözleşme (frekans > 0) için **içinde bulunulan yıl**, sıra 1..frekans; hedef ay = `1 + floor((sıra−1) × 12 / frekans)`, ayın 1'i; `sıra ≤ CompletedCount` olan dönemler tamamlandı sayılır; tamamlanmış dönem geri açılmaz (`P:2922-2952`).
- **R-33** Vadesi gelen = `CompletedCount+1`'inci dönem ve hedef tarih ≤ bugün → cihaz iş emirleri üretilir; manuel tetik + her kapanış sonrası + açılış (`P:2954-2978`, `P:539`, `P:34`).
- **R-34** Cihaz adedi sözleşme `ProductsText`'ten regex ile okunur: `(\d+)\s*(X[\s-]*RAY|KAPI( TİPİ)?( METAL)? DEDEKTÖR(Ü|U)?)`; adet 1–500 değilse hata; **eşleşme yoksa hiçbir şey üretilmez (cihaz sayısı uydurulmaz)** (`P:2990-2999`).
- **R-35** Cihaz–kütük eşlemesi: aynı **müşteri adı (tam eşleşme)** ve tip (X-Ray: `%RAY%`; kapı: `%KAPI%` veya `%DEDEKT%`), `SecurityDeviceId` sırasına göre ordinal eşlenir; seri/bölge kütükten; kütükte yoksa seri boş (`P:3010-3043`). Her kalem için şablon kontrol maddeleri (11 / 10) bir kez eklenir.
- **R-36** Idempotent: (plan, tip, sıra) tekil; mevcut iş emri yeniden üretilmez; V1.7 ana PB emri silinmez, **ilk cihaza dönüştürülür**; iş emri: birim Güvenlik, tür `Planlı Bakım`, öncelik Normal, durum `Müşteri Talebi`, konu "Planlı bakım • {tip} #{sıra}", açıklama "{sıra}/{frekans} bakım dönemi, hedef dd.MM.yyyy…"; plan `GeneratedWorkOrderId` ilk iş emrine bağlanır; Serializable + plan satır kilidi (`P:3000-3101`).

### 6.4 Dijital bakım formu
- **R-37** Alan uzunlukları: seri ≤ 200, bölge ≤ 250, not ≤ 1000, yedek parça ≤ 1000 (`P:2452`).
- **R-38** Kontrol sonuçları 4 değerden biri, kod tekrarı yok, kod cihazın şablonunda olmalı (`P:2454-2456`, `P:2479-2480`).
- **R-39** `Bekliyor` dışı sonuçta kontrol eden + zaman yazılır; `Bekliyor`'a dönünce temizlenir (`P:2483-2486`).
- **R-40** Tamamlamada seri, bölge, teknisyen notu, servis sonucu **zorunlu** (`P:2500-2501`).
- **R-41** Tamamlamada hiçbir madde `Bekliyor` kalamaz (`P:2502`).
- **R-42** Sonuç `Tamamlandı` için **tüm maddeler Uygun** olmalı; aksi halde Tekrar Gidilecek/Teklif/Servise Alındı seçilmeli (`P:2503-2504`).
- **R-43** Aynı bakım döneminde aynı seri (trim) başka cihaz kaleminde olamaz (`P:2505-2509`).
- **R-44** Tamamlama: sonuç `Tamamlandı` → kalem `Tamamlandı`, iş `Kapatıldı`, kapatan/zaman; diğer sonuç → kalem `Bekliyor`, iş **`Beklemede`** (açık kalır, takip). Taslak: durum değişmez. İş emrinin seri/lokasyon(=bölge)/açıklama(=yapılan işlem) alanları formdan güncellenir; boş gönderilen alan mevcut değeri silmez (COALESCE) (`P:2511-2534`).
- **R-45** **Bakım sayacı tek sefer**: dönemdeki **tüm** cihazlar `Tamamlandı` olduğunda plan `IsCompleted=1` (yalnız 0→1 geçişinde) ve sözleşme `CompletedCount+1` (frekansı aşmaz) (`P:2538-2553`). Ayrıca eski genel PB yolu `CompleteMaintenanceFromWorkOrderAsync` aynı artışı yapar (`P:3136-3175`).

### 6.5 Saha / zaman
- **R-50** Canlı sayaç yalnız işe `Teknisyen` rolüyle **isimle** atanmış kişinin **kendi hesabıyla**; kapalı/iptal işte başlatılamaz (`P:1943-1954`).
- **R-51** **Tek aktif sayaç**: kişi başına bir açık oturum (uygulama kontrolü + filtreli unique indeks) (`P:1955-1958`, `S-114:26-30`).
- **R-52** Açık sayaç varken iş emri kapatılamaz ve bakım formu tamamlanamaz (`P:504-509`, `P:2496-2499`).
- **R-53** Zamanlar **SQL sunucu saati**; bölüm ≥ 1 dk (kısa bölüm reddedilir, sahte 1 dk yazılmaz), ≤ 18 saat (aşarsa yönetici iptal + manuel giriş) (`P:2021-2025`).
- **R-54** **Mola / Ara** süre kaydına yazılmaz → **kişi-saate dahil değil**; molalar ayrı listelenir (`P:2037`, `P:3412`, `A:1487`).
- **R-55** Canlı bölüm kaydedilirken aynı kişinin başka süre kaydıyla çakışma varsa işlem durdurulur (`P:2039-2045`); başlangıçta da kontrol (`P:1960-1965`).
- **R-56** Sayacı bitirmek iş emrini kapatmaz (`P:2077`).
- **R-57** Açık sayaç iptali: gerekçeli, kayıt saklanır, kişi-saat oluşmaz (`P:2094-2101`).
- **R-58** Manuel süre: teknisyen rolünde ad zorla kendisi; ≤ 18 saat; gelecek yok (+5 dk); atanmış teknisyen olmalı; açık sayaç ve diğer kayıtlarla çakışma yok (Serializable) (`P:2120-2151`).
- **R-59** Süre kaydı silinmez, iptal (void) edilir; raporlar iptalleri dışlar (`P:2174-2176`, `P:3432`).

### 6.6 Teklif / atölye / operasyon
- **R-60** Teklif hesabı kalem bazında: satır = adet × fiyat; iskonto = satır × %; KDV = (satır − iskonto) × %; genel = ara − iskonto + KDV; toplamlar 2 ondalık yuvarlanır (`P:3504-3518`).
- **R-61** Gönderim yalnız `Onaylandı`; her deneme loglanır; başarı → `Müşteriye Gönderildi` (`P:904`, `P:939-953`).
- **R-62** Bakım sözleşmesi ekranında sonraki dönem = bu yılın en küçük sıralı tamamlanmamış planı (`P:2304-2312`).
- **R-63** Atölye kaydı her zaman bağlı bir `SRV-` iş emri + cihaz satırı ile açılır; atölye no `AT-` (`P:2643-2701`).
- **R-64** Atölye→iş durumu: Yeni Kayıt→Atölyede, Onarımda→İşlemde, Beklemede→Beklemede, Test / Kontrol→Test / Kontrol, Tamamlandı→Tamamlandı, **Teslim Edildi→Kapatıldı** (+ClosedAt), diğer (İptal dahil)→Atölyede (`P:2746-2755`) [⚠ HATA H-08].
- **R-65** SLA geciken = açık iş ve `CreatedAt + hedef saat(öncelik; yoksa 72) < şimdi`; **takvim saati** (mesai/tatil yok) (`O:31`, `O:87`).
- **R-66** Uyarı türleri: Kritik "Geciken", Bilgi "Yarın" (plan yarın), Uyarı "Beklemede: neden", Uyarı "Düşük stok" (`warehouse.view`; toplam < minimum), Bilgi "Eğitim tarihi" (tamamlanmamış, hedef ≤ bugün+7, ilk 40, birim yetkisi); yardımcı uyarılar ≤ 80 (`O:26-65`).
- **R-67** Tekrar arıza = bakım dışı işlerde aynı seri (harf duyarsız) ≥ 2 iş; dönem = son N gün açılan veya açık işler (`O:93-96`).
- **R-68** Uyarı anahtarı günlüktür (`tip:id:yyyyMMdd`), "görüldü" kullanıcı bazında; ertesi gün yeniden çıkar (`O:32-34`, `O:117-118`).
- **R-69** Bekletme: kapalı iş bekletilemez; tek açık bekleme; önceki durum saklanır ve serbest bırakınca geri yüklenir (iş hâlâ Beklemede ise) (`O:136-157`).

### 6.7 Kiralama / depo / stok
- **R-70** Kompozisyon: 1–100 kalem, kalem adet 1–10000, not ≤ 1000, seri ≤ 200 kar., ≤ 10000 seri; ≤ 50 irtibat, ad zorunlu ≤ 180, unvan ≤ 180, tel ≤ 80, e-posta ≤ 250, not ≤ 500 (`P:3183-3201`).
- **R-71** 12 kiralama durumu; `Kapandı/İptal` → ClosedAt (ilk kez), diğer durumlara dönünce NULL (`P:1146`, `P:1180`).
- **R-72** Seri takipli üründe teslim/kirada/iade/test/kapanış durumlarında seri zorunlu (üst kayıt seri metnine bakılır) (`P:1171-1172`).
- **R-73** Kalem kimlikleri korunur; atamalı kalem silinemez; atamalı kalemin ürünü değişemez / adedi atananın altına inemez; irtibatlar atomik yenilenir (`P:1265-1275`, `P:3203-3255`).
- **R-74** Envanter: seri takipli = tek tek (adet 1 + seri); `Hazır Değil` için eksik açıklaması; ürün+seri tekil; tahsisli satır düzenlenemez (`P:1339-1373`).
- **R-75** **Çift tahsis engeli**: bir envanter satırı yalnız bir kaleme bağlı olabilir; yalnız `Hazır` (veya aynı kaleme bağlı `Kirada`) seçilebilir; sevk edilmiş atama depo dönüşü olmadan değişemez; toplam ≤ kalem adedi (`P:1397-1412`).
- **R-76** `Sevk Edildi` → bağlı Hazır cihazlar `Kirada` (`P:1465-1471`).
- **R-77** `Depoya Alındı` → depo zorunlu; bağlı cihazlar seçilen depoya, **`Kontrolde`** (otomatik Hazır değil), tahsis çözülür (`P:1472-1480`).
- **R-78** Yedek parça **negatif stok engeli**; çıkış iş emrine bağlı zorunlu; hareket anındaki birim maliyet saklanır (`O:192-212`).
- **R-79** Kiralama envanteri (RentalInventory) ile servis yedek parça stoğu (ServiceStockBalances) **ayrı** iş mantıkları; yalnız depo tablosu ortak (`O:165-170`).

### 6.8 Eğitim
- **R-80** Eğitim verisi birim kapsamı personelin birimine göre; birimsiz personel yalnız tüm-birim yetkili kullanıcıya (`P:2796-2802`).
- **R-81** Kurs kontrol listesi 1–30 madde, `!` = kritik (`P:1544-1547`).
- **R-82** Yıllık plan toplu atama: aynı kişi+kurs+yıl tekrar oluşmaz; hedef tarih aynı yıl içinde; yetki önce tümüne kontrol (`P:1574-1595`).
- **R-83** Katılım "katıldı" → aynı yılın planı `Tamamlandı`, tamamlanma = oturum tarihi; "katılmadı" geçmiş tamamlanmayı silmez (`P:1637-1645`).
- **R-84** Gözlem skoru = 100 × Σpuan / (değerlendirilen madde × 2), 2 ondalık; "Gözlenmedi" (-1) paydaya girmez (`P:1688-1689`).
- **R-85** Kritik maddede 0 puan → gözlem **kritik başarısızlık** (ortalama içinde kaybolmaz); arayüzde onay uyarısı (`P:1690`, `A:1433`).
- **R-87** 30/60/90 takip: tamamlanmış plan + 30/60/90 gün; aynı kişi+kurs+aşamada gözlem yoksa listede; geçmişse "Gecikti" (`A:1293-1305`).

### 6.9 Maliyet ve raporlama
- **R-86** İş maliyeti: malzeme = Σ(Çıkış q×maliyet) − Σ(Giriş q×maliyet) (iş emrine bağlı hareketler); işçilik = (gerçek dakika/60) × birim saatlik tarifesi; toplam = diğer + malzeme + işçilik; fark = gelir − toplam. Resmi kâr değildir (`O:224-234`, `J:19`).
- **R-88** Tahmini (plan) süre gerçek süre yerine **asla** kullanılmaz (`P:3667`, `P:2104`).
- **R-89** Süre kaydı olmayan iş **"SÜRE KAYDI YOK" / "Süre Kaydı Eksik"** olarak gösterilir, 0 saat yazılmaz (`P:3666`, `P:3678`, `A:1175`).
- **R-90** Personelle birlikte hesap açılırsa birim listesi boş gönderilebilir → **tüm birimler** yetkisi (`P:1797`) [güvenlik riski].
- **R-91** Personel pasif → `EndDate` bugün (verilmezse), hesap pasif, oturumlar düşer (`P:1879-1899`).
- **R-92** Kişi-saat = birden çok teknisyenin ayrı süreleri toplamı (2 kişi × 2 saat = 4 kişi-saat); tarih filtresi faaliyet başlangıcına uygulanır (`P:3669`, `P:2216-2225`).
- **R-93** CSV hücreleri `= + - @` (ops: + tab/CR) ile başlıyorsa `'` öneki (formül enjeksiyonu koruması) (`P:1725`, `O:68`, `A:1558`).
- **R-94** Excel'de baştaki sıfırlı değerler (örn. seri no) metin olarak kalır (`P:3761-3762`).
- **R-95** Personel listesi ve cihaz kütüğü kaydı **silinmez**; pasifleştirme/IsActive ile (genel desen; DELETE yalnız kiralama kalem/irtibat yenilemede) (`P:3219`, `P:3238`).
- **R-96** Atölye kaydı oluştururken giriş tarihi boşsa şimdi; tahmini/garanti tarihleri DATE; entegrasyon firması varsayılanı "Denge Telekom" (istemci) (`P:2863`, `A:703`).

---

## 7. Kullanıcı tarafından doğrulandığı belirtilen işlevler [✔K]

| # | İşlev | Sürüm | Doğrulama ifadesi (BELGE) | Envanterdeki karşılığı |
|---|---|---|---|---|
| K-1 | Ana Panel ve Planlama **tıklanabilir KPI sayı kutuları** (kategori modalı) | V1.8 | "çalıştı" teyidi (§4, §10.1) | E-01, E-09 KPI'ları, `A:229-289` |
| K-2 | **Toplu ekip ataması** | V1.9 | "toplu olarak atamasını yapabiliyorum" (§10.1) | Uç #18 (ve planlama bekleyenlerden toplu atama), E-07, E-09 |
| K-3 | **Excel dışa aktarma** (tarih seçili/boş) | V1.20.1 | "dosya iniyor" (§4, §10.1) | Uç #60, Bölüm 5.1, `A:1997-2001` |
| K-4 | V1.6 Planlama takvimi derleme + 5050'de açılış | V1.6 | "Windows'ta derleme ve 5050 açılışı doğrulandı" (§4) | E-09 (yalnız açılış; çakışma/plan akışı ayrıca test edilmedi) |
| K-5 | V1.11 derleme 0 uyarı | V1.11 | §10.1 | Yapısal; işlev değil |
| K-6 | V1.20 Windows'ta başlatma (`Now listening … 5050`) | V1.20 | §10.1 | Yapısal |
| K-7 | SQL yedekleme sorgusu ve yedek envanteri | — | §10.1 | Operasyon; yeni sistemde `pg_dump` eşleniği |

**Doğrulanmamış (kodda var, kabul testi yok — BELGE §10.2):** 17 cihazlık PB kapanışları, kiralama uçtan uca, eğitim kayıtları, canlı sayaç uçtan uca, stok düşümü, tekrar arıza, SLA, maliyet, finans API sızıntı testi. Bu işlevlerin yeni sistemdeki davranışı **kod okunarak** (bu belge) belirlenmiştir; kullanıcı test verisiyle karşılaştırmalı kabul testi gerekir.

---

## 8. Eski kodda tespit edilen hatalar / boşluklar (birebir taşınmamalı)

| # | Tür | Açıklama | Kaynak |
|---|---|---|---|
| H-01 | Hata | "Sahada" KPI sayısı Sahada+İşlemde, detay listesi yalnız Sahada | `A:220`, `A:243` |
| H-02 | Hata | "Açık Bakım" sayısı Tamamlandı'yı hariç tutar, detay listesi dahil eder | `A:222`, `A:248` |
| H-03 | Hata | Operasyon Merkezi sayaç düğmeleri `data-filter` çakışması nedeniyle filtrelemiyor | `A:1906`, `A:1911`, `J:68` |
| H-04 | Hata | Kiralamadan teklif kısayolu düğmesi üretilmiyor (ölü kod) | `A:1977` |
| H-05 | Boşluk | Durum metni sunucuda doğrulanmıyor; geçiş kuralı (state machine) yok | `P:473-543` |
| H-06 | Hata | Tekli plan kapalı işi bile `Planlandı` yapar; tarih/süre doğrulanmaz | `P:722-761` |
| H-07 | Boşluk | Plan çakışması yalnız istemcide; sunucu kaydı engellemez | `A:392-406` |
| H-08 | Hata | Atölye `İptal` durumu iş emrini `Atölyede`'ye çeker | `P:2746-2755` |
| H-09 | Risk | `CompletedCount` yıl dönümünde sıfırlanmaz; yeni yılda dönemler yanlış tamamlanmış sayılır; plan yalnız içinde bulunulan yıl için üretilir | `P:2922-2952` |
| H-10 | Veri | Regex bazı sözleşme metinlerini kaçırır: `KAPI DEDEKTÖÜ` (BAKIM-0088), `7 ADET KAPI DEDEKTÖRÜ` (BAKIM-0029) → cihaz iş emri eksik/hiç üretilmez | `P:2990`, `S-SEED:2375`, `S-SEED:2434` |
| H-11 | Veri | Cihaz-kütük eşlemesi müşteri adı tam eşleşmesine ve satır sırasına dayanıyor (sözleşme adı ≠ kütük adı ise seri boş) | `P:3010-3016` |
| H-12 | Mimari | Atama, süre, gözlemci, yönetici **isim metniyle**; isim değişikliği/aynı isim bütünlüğü bozar | `P:3338-3347`, `P:1945` |
| H-13 | Boşluk | Teklif tutarları (`/api/offers`, PDF) ve atölye tamir bedeli `finance.prices.view` olmadan dönüyor — "fiyat API seviyesinde gizli" kararıyla çelişir | `P:790-798`, `P:2599` |
| H-14 | Güvenlik | Oturum bellek içi, süresiz; giriş deneme sınırı yok; `users.manage` sahibi `*` verebilir; İK ve Müdür Yrd. `users.manage` sahibi; `/api/health` anonim + hata detayı | `P:21`, `P:67-99`, `P:245-319`, `P:47-65` |
| H-15 | Kurulum | `DengeERP_Update.sql` sabit `USE DengeERP` | `S-UPD:1` |
| H-16 | Tutarsızlık | Yedek seri kuralı sunucu (Atölye/Saha/Kurulum/Arıza) ile istemci (yalnız Atölye) farklı; arayüz iş türlerinin bir kısmı kural tablosunda yok | `P:3380-3382`, `A:135`, `A:9-15` |
| H-17 | Tutarsızlık | `Çözüldü` kapanış sayılıyor ama hiçbir durum listesinde yok; `Düşük` öncelik SLA'da var arayüzde yok | `P:2808`, `S-120:5`, `A:297` |
| H-18 | Boşluk | Bekletme/serbest bırakma ve atölye güncellemesi durum geçmişine yazılmıyor; kullanıcı/yetki değişiklikleri denetlenmiyor | `O:130-159`, `P:2707-2776` |
| H-19 | Boşluk | Personel listesi birim filtresi olmadan tüm şirkete açık (`personnel.view`); sayı/plan uçlarında `Teknisyen` kısıtı isimle | `P:1733-1768` |

---

## 9. En riskli / karmaşık 15 iş kuralı (geçişte öncelikli test)

1. **R-36/R-34/R-35 — Cihaz bazlı PB üretimi**: `ProductsText` regex'i, kütük eşlemesi, idempotent üretim, V1.7 ana emrinin ilk cihaza dönüşümü, PB numarasının hedef ayı kullanması.
2. **R-45 — Bakım sayacının bir kez artması**: tüm cihazlar tamamlanınca plan 0→1 ve sözleşme +1; ikinci yol (`CompleteMaintenanceFromWorkOrderAsync`) ile çift sayım olmaması.
3. **R-32/H-09 — Yıllık dönem hesabı**: hedef ay formülü, `CompletedCount` ↔ dönem eşlemesi, yıl dönümü davranışı (eski kodda hatalı).
4. **R-42/R-44 — Bakım formu kapanış mantığı**: tüm maddeler Uygun değilse `Tamamlandı` yasak; diğer sonuçta iş `Beklemede` kalır.
5. **R-51/R-53/R-54 — Tek aktif sayaç + 1 dk/18 sa + mola hariç**, sunucu saati.
6. **R-55/R-58 — Kişi bazlı zaman çakışma engeli** (manuel ↔ canlı ↔ manuel), Serializable kilitleme; isimle eşleşme.
7. **R-52 — Açık sayaç varken iş/bakım kapatma engeli.**
8. **R-75 — Kiralama çift tahsis engeli** + sevk sonrası tahsisin kilitlenmesi.
9. **R-76/R-77 — Aşama → envanter durum geçişleri** (Sevk→Kirada, Depoya Alındı→Kontrolde).
10. **R-78 — Negatif stok engeli** + iş emri zorunluluğu + maliyet anlık görüntüsü.
11. **R-17/R-18 — Toplu planlama doğrulamaları ve çakışma kuralı** (TPL ziyaret istisnası; sunucuya taşınmalı).
12. **R-07 — Numara üretimi** (aylık sıfırlama, eşzamanlılık kilidi; PostgreSQL'de sequence/advisory lock karşılığı).
13. **R-08/H-13 — Fiyat/maliyet alanlarının API'de gizlenmesi** (teklif ve atölye dahil genişletilmeli).
14. **R-03/R-02 — Teknisyen ve birim görünürlüğü** (boş birim = tümü; isimle atama eşleşmesi) — yeni sistemde kimlik (FK) temelli olmalı.
15. **R-92/R-89/R-84 — Rapor hesapları**: kişi-saat tarihinin faaliyet başlangıcına göre süzülmesi, "süre kaydı eksik" etiketi, gözlem skoru + kritik başarısızlık.

---

## 10. Geçişte veri aktarımı için not

- Korunması gereken kimlik/no alanları: `WorkOrderNo`, `OfferNo`, `RentalNo`, `WorkshopNo`, `SourceKey` (kütük/sözleşme), `RouteGroupNo`, `CourseCode`, competency `Code`, check `CheckCode`.
- Pipe (`|`) ile tutulan alanlar (izinler, birimler, ek departmanlar) ilişkisel tablolara açılmalı; virgüllü seri metinleri (`SerialNumbers`) satırlara bölünmeli (R-10 kuralıyla).
- İsim metinli ilişkiler (atama, süre kaydı teknisyeni, şef, yönetici, atanan, sorumlu, gözlemci) personel/kullanıcı kimliklerine eşlenmeli; eşleşmeyenler raporlanmalı (H-12).
- `DeliveryDateText` Excel seri tarih metni (`42724` → 2016-12-20 gibi) olarak saklanmış; dönüştürme ayrı karar.
- İptal edilmiş süre kayıtları, iptal edilmiş sayaçlar, pasif atama/cihaz/plan satırları **denetim izi** olarak taşınmalı.
