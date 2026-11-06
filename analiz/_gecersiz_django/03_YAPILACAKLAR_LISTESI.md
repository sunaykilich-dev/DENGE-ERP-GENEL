# DengeERP — Yeni Sistem (Django + PostgreSQL) Yapılacaklar Listesi

**Sürüm:** 2026-10-21 · **Kapsam:** Yalnız teknik servis · **Hedef:** Ubuntu 24.04 (10.10.50.16), iç ağ
**Karar:** DengeERP V1.20.1 (.NET 10 + SQL Server + vanilla JS) **Python Django + PostgreSQL ile yeniden yazılıyor.** Eski kod (`kaynak\V1_20_1_orijinal\DengeERP.Api`) yalnız **salt okunur referans**tır; bu liste "eski koda yama" değil, **yeni sistemin gereksinim ve teslim planı**dır.

**Girdiler:** 14 modülün denetçi onaylı maddeleri (`analiz\02_moduller\_ozet\*.json`), A1–A4 denetim bulguları (`analiz\01_denetim\`), eski sistem işlev envanteri (`analiz\05_ESKI_SISTEM_ISLEV_ENVANTERI.md`), proje geçmişi ve rol/yetki envanteri.

**Korunan iş kararları (tüm maddeler için geçerli):** 1 cihaz = 1 PB iş emri · seri no metin (baştaki sıfır ve `/ - .` korunur) · fiyat/maliyet **API seviyesinde** gizli · zaman takibi bordro değil · mola kişi-saate dahil değil · süre kaydı yoksa **"eksik"** (asla 0) · Logo CRM/Flowick kapsam dışı · tüm çıktılar Türkçe.

---

## 0. Sıralama gerekçesi (ONAYINIZA SUNULUR)

Sizin önceliğiniz (c) yeni özellik → (b) eksikler → (a) güvenlik/üretime hazırlık idi. Yeniden yazım kararıyla birlikte yeni özelliklerin üzerine kurulacağı bir zemin henüz yok: kullanıcı, yetki, birim kapsamı, iş emri ve durum servisi olmadan hiçbir yeni modül yazılamaz. Bu yüzden **Dalga 0 (temel altyapı)** ve **Dalga 1 (eski sistemle eşdeğerlik)** zorunlu olarak öne alındı; pilot kullanıcılar ancak Dalga 1 bitince eski sistemi bırakabilir. Dalga 0'daki birkaç güvenlik maddesi (yetki yükseltme önlemi, oturum düşürme, fiyat gizleme) "a" grubundan görünse de yeni sistemde **baştan doğru kurmak neredeyse bedavadır**, sonradan eklemek pahalıdır; bu yüzden temele alındı. Dalga 1'den sonra sıra sizin istediğiniz gibi **c → b → a** ilerler; yalnız Dalga 4'te **[Pilot öncesi]** işaretli 4 madde (sunucu kurulumu, HTTPS, yedek, loglama) Dalga 1 canlıya alınmadan önce öne çekilir.

| Dalga | İçerik | Madde | Sizin önceliğinizle ilişkisi |
|---|---|---:|---|
| 0 | Temel altyapı (bloke edenler) | 23 | Zorunlu ön koşul |
| 1 | Eski sistemle eşdeğerlik + veri aktarımı | 38 | Zorunlu (pilot geçişi) |
| 2 | Yeni modül/özellikler | 79 | (c) |
| 3 | Kalan eksikler | 29 | (b) |
| 4 | Üretime hazırlık / güvenlik sıkılaştırma | 12 | (a) — 4'ü pilot öncesi |
| **Toplam** | | **181** | |

**Kritik zaman uyarısı:** Eski sistemde planlı bakım sayacı yıl devrinde sıfırlanmıyor (A3-02/A2-03/H-09). Eski sistem **1 Ocak 2027'de hâlâ canlıysa** 2027 bakımları "tamamlanmış" doğar. Dalga 1 bu tarihe yetişmezse eski sistem için geçici önlem kararı gerekir (Soru 4).

---

## 1. Önerilen Django app yapısı

Python 3.12 · Django 5.2 LTS · Django REST Framework · PostgreSQL 16 · pytest-django (VARSAYIM, bkz. §8).

| App | Sorumluluk | Ana modeller / servisler |
|---|---|---|
| `core` | Ayarlar, ortak yardımcılar, tek `simdi()`, normalizasyon, numara servisi, katalog/meta, hata işleyici, iyimser kilit, fiyat alanı mixin'i | `NumberSequence`, `normalize_serial()`, `normalize_tr()`, `PriceFieldMixin`, `/api/meta` |
| `accounts` | Özel `User` modeli (ilk migration'da!), izin kataloğu, rol şablonları, kişi bazlı izin, birim kapsamı, oturum, şifre | `User`, `Unit`, `Permission` kataloğu, `RoleTemplate`, `scoped_queryset()` |
| `personnel` | Personel kartı, kullanıcı bağı, ek birimler, saha rolü, atanabilir personel, müsaitlik | `Personnel`, `PersonnelUnit`, `AvailabilityBlock` |
| `customers` | Müşteri (cari), lokasyon (tesis), irtibat, takma ad, birleştirme | `Customer`, `Site`, `Contact`, `CustomerAlias` |
| `audit` | Merkezi denetim kaydı (yalnız INSERT) | `AuditLog` |
| `attachments` | Ek dosya/fotoğraf (magic byte, rastgele ad, erişim kontrolü) | `Attachment` |
| `workorders` | İş emri, seri satırları, **merkezi durum geçiş servisi**, geçmiş, not, bekleme, atama, kategori, bağlı iş, kapanış/onay, servis formu, Ana Panel | `WorkOrder`, `WorkOrderDevice`, `WorkOrderEvent`, `Hold`, `Assignment`, `transition()` |
| `planning` | Plan, toplu plan/atama, takvim, çakışma, erteleme, saha önerisi, kaynak görünümü | `WorkOrderPlan`, `PlanHistory` |
| `devices` | Güvenlik cihaz kütüğü, garanti, yaşam döngüsü, veri kalitesi | `SecurityDevice`, `DeviceChange` |
| `maintenance` | Bakım sözleşmesi, kapsam, dönem/PB üretimi, dijital form, kontrol şablonları, uygunsuzluk | `MaintenanceContract`, `MaintenancePlan`, `MaintenanceItem`, `Visit`, `generate_pb()` |
| `workshop` | Haberleşme atölye kabul–teşhis–onarım–teslim, aksesuar, RMA | `WorkshopTicket`, `WorkshopStatusLog`, `Accessory` |
| `rentals` | Kiralık envanter, hareket defteri, tahsis, aşama, sevk/iade, kontrol, müsaitlik | `InventoryItem`, `InventoryMovement`, `Allocation`, `Rental`, `RentalStage` |
| `stock` | Yedek parça kartı, depo, stok hareket defteri (tür+yön), transfer, sayım, talep | `Part`, `Warehouse`, `StockMovement`, `StockCount` |
| `offers` | Teklif, kalem, revizyon, onay akışı, PDF, gönderim | `Offer`, `OfferLine`, `OfferStatusHistory` |
| `costing` | İç maliyet tarifesi, iş geliri, maliyet analizi | `LaborTariff`, `WorkOrderRevenue` |
| `training` | Kurs, oturum, katılım, plan, gözlem, yetkinlik, belge geçerliliği, İSG faaliyeti | `Course`, `Session`, `Observation`, `CompetencyAssessment` |
| `timetracking` | Canlı sayaç, faaliyet bölümleri, manuel kayıt, mobil "Benim İşlerim" | `TimerSession`, `TimeEntry` |
| `operations` | Operasyon Merkezi, SLA politikası, mesai takvimi, bekleme kataloğu, tekrar arıza, iş yükü | `SlaPolicy`, `WorkCalendar`, `HoldReason` |
| `notifications` | Kalıcı bildirim, rozet, e-posta giden kutusu (outbox) | `Notification`, `OutboxMessage` |
| `reports` | Tek KPI/rapor motoru, Excel (tipli şema, pivot), web rapor ekranı | `kpi_service`, `excel_export` |
| `legacy_import` | SQL Server → PostgreSQL salt okunur aktarım, profil, eşleme tabloları, uzlaştırma raporları | `PersonnelNameMap`, importer komutları |
| `ui` | Türkçe arayüz kabuğu (temel şablon, menü, statik dosyalar) | `base.html`, menü kaydı |

**Uygulama ilkeleri:** Uygulamalar arası çağrı yalnız `services.py` fonksiyonlarıyla (ör. `workorders.services.transition()`); başka app'in modeline doğrudan yazılmaz. Her app kendi izinlerini `permissions.py` ile kataloğa kaydeder (`accounts` dosyalarına dokunmadan). Durum değişikliği yapan tek yol `transition()`'dır.

---

## 2. Dalga 0 — Temel altyapı (23 madde)

| ID | Başlık | App | Tür | Kaynak | Ö | E | Bağımlılık | Kabul kriteri |
|---|---|---|---|---|---|---|---|---|
| YL-001 | Proje iskeleti, ortam değişkenli ayarlar, `USE_TZ=True`, `TIME_ZONE=Europe/Istanbul`, `LANGUAGE_CODE=tr`, tek `simdi()`/`bugun()` yardımcısı, özel `User` modeli ilk migration'da | core | ALTYAPI | A2-05, A4-06, A3-15, M09-12, M10-12, A4-11, A4-32 | P1 | M | – | `check --deploy` (üretim profili) uyarısız; kodda doğrudan `datetime.now()` yok (lint kuralı); 23:30'da açılan iş "bugün", 00:30'da açılan "ertesi gün" (TR) testleri geçer; `.env.example` tüm sırları listeler. |
| YL-002 | PostgreSQL dev/test/üretim ayrımı ve en az yetkili DB rolleri | core | ALTYAPI | A3-01, A2-01, A1-21, A1-17 | P1 | S | YL-001 | DB adı yalnız ortam değişkeninden; şema yalnız `migrate` ile ve ayrı DDL rolüyle; uygulama rolünde DDL yok; `audit_auditlog` üzerinde UPDATE/DELETE yetkisi yok; test DB her koşuda sıfırdan kurulur. |
| YL-003 | GitHub private depo, `.gitignore`, gitleaks, pre-commit (ruff/black), GitHub Actions CI (PostgreSQL servisli pytest) | core | ALTYAPI | A4-02, A1-17, A4-12, M01-D05, M13-14 | P1 | S | YL-001 | İlk commit öncesi gitleaks temiz; gerçek müşteri/personel/sözleşme dosyası depoda yok; CI kırmızıyken birleştirme engelli. |
| YL-004 | Test altyapısı: pytest-django, factory_boy, sahte adlı sentetik fixture, ortak yetki test yardımcıları | core | TEST | M01-D05, M09-D03, M11-D02, M08-D04, M12-D01, M06-D04, M13-D01 | P1 | M | YL-003 | `pytest` tek komutla ayrı test DB'sinde çalışır; ≥20 temel senaryo (giriş, 401, 403, 404, 409, fiyat gizleme); gerçek veriye dokunmaz; kullanıcı test verisi geldiğinde ayrı klasörden yüklenir. |
| YL-005 | Ortak API sözleşmesi: DRF, Türkçe JSON hata işleyici (400/401/403/404/409), `IntegrityError`→409, sayfalama, throttling, `version` alanlı iyimser kilit mixin'i | core | ALTYAPI | A2-10, A4-09, M07-D01*, A2-11, A3-17, A4-23, A1-20, A2-08, A1-12 | P1 | M | YL-001 | Yetkisiz istek JSON 403 döner ve logda istisna oluşmaz; eski `version` ile güncelleme 409; liste uçları sayfalı; `DEBUG=False`'da yığın izi/SQL hatası istemciye gitmez. |
| YL-006 | Kimlik doğrulama ve oturum: DB tabanlı Django oturumu, HttpOnly/Secure/SameSite çerez, CSRF, `SESSION_COOKIE_AGE` + boşta kalma süresi; pasifleştirme/şifre sıfırlamada tüm oturumlar silinir; izin değişikliği ≤60 sn yansır | accounts | GÜVENLİK | M13-13, A1-04, A4-01, A2-16, A4-13, A1-18 | P1-KRİTİK | M | YL-005 | Pasif yapılan/şifresi sıfırlanan hesabın tüm oturumları sonraki istekte 401; kaldırılan izin ≤60 sn içinde 403; süre aşımı 401; sunucu yeniden başlatması oturumu düşürmez; belirteç localStorage'da tutulmaz. |
| YL-007 | Şifre yaşam döngüsü (çekirdek): `AUTH_PASSWORD_VALIDATORS` (min 12), zorunlu değişim ara katmanı, mevcut şifre sorgusu, değişimde diğer oturumların düşmesi, django-axes (5 hata/15 dk) | accounts | GÜVENLİK | M13-11(a,b), A1-11, A1-05 | P1 | S | YL-006 | Zorunlu değişim bekleyen hesap tüm uçlarda 403; mevcut şifre yanlışsa 400; 6. hatalı denemede kilit; var olmayan/pasif/yanlış kullanıcıda yanıt metni aynı. |
| YL-008 | İzin kataloğu (34 mevcut + yeni anahtarlar), 12 rol şablonu, kişi bazlı izin; şablon değişikliği mevcut hesabı değiştirmez | accounts | GÜVENLİK | M13-07, M01-18, M01-D02*, M10-14, M11-12, M06-16, M14-01, M08-05, M08-17, M12-16 | P1 | M | YL-006 | Yeni anahtarlar: `workorders.complete/close/reopen/edit_basic`, `operations.view`, `stock.use`, `rentals.inventory/stage`, `customers.view/edit/merge`, `training.self/view_detail`, `reports.personnel`, `finance.costs.manage`; katalog dışı izin/rol 400; Teknisyen şablonunda `close` yok, `complete` var; Şef şablonunda `operations.manage` yok; tüm izinler Türkçe açıklamalı. |
| YL-009 | Yetki yükseltme önlemi (alt küme, kendine dokunmama, Admin üstünlüğü, son `*` korunur) | accounts | GÜVENLİK | M13-12, A1-01, A1-07, M13-D02 | P1-KRİTİK | S-M | YL-008 | `users.manage` sahibi kendine/başkasına `*`, `users.manage`, `audit.view` veya Admin rolü veremez (403); İK teknisyeni pasifleştirir ama Admin'i pasifleştiremez; kimse kendi izin/birimini değiştiremez veya kendini pasifleştiremez; son aktif `*` düşürülemez; işlemler denetime yazılır. |
| YL-010 | Birim kapsamı (Unit tablosu, M2M, **boş = hiçbiri**) ve ortak kapsam queryset'i (birim + `own_only` + teknisyen ataması FK); kapsam dışı nesne 404 | accounts | GÜVENLİK | M13-08, A1-13, A1-08, A1-19, M01-18, M07-14 | P1 | M | YL-008, YL-011 | Tüm liste/detay/ilişkili kimlik çözümü bu queryset'ten geçer (testle zorlanır); birimsiz hesap açma 400; `own_only` kullanıcı başkasının işini hiçbir uçta göremez/güncelleyemez. |
| YL-011 | Personel modeli ve kullanıcı bağı: ana birim + ek birimler, saha rolü (FieldRole), aktiflik; User↔Personnel tekil bağ; personeli aktifleştirmek hesabı açmaz | personnel | VERİ | M13-01(A), M13-D02, M13-D03, M13-02, A1-07, A2-06 | P1 | M | YL-008 | İkinci bağlama 409 (kısmi UNIQUE); ayırma hesabı pasif yapmaz; aktifleştirilen personelin hesabı pasif kalır ve yanıt "hesap ayrıca açılmalı" der; personel ve hesap ayrı izinlerle yönetilir. |
| YL-012 | Atanabilir personel servisi (`personnel.view` gerektirmez, birim kapsamlı, yalnız aktif); ön yüze personel adı gömülmez | personnel | VERİ | M13-02, M02-03a, M02-14*, A2-15, H-19 | P1 | S | YL-011, YL-010 | `personnel.view`'siz Şef kendi biriminin (ana/ek) aktif teknisyenlerini görür; oturumsuz erişilen hiçbir statik dosyada personel adı yok; iletişim/fiyat alanı dönmez; kapsam dışı birim 403. |
| YL-013 | Gerçek personel listesi için tek seferlik, idempotent yükleme komutu (depo dışı dosyadan) | personnel | VERİ | M13-D01*, A4-02 | P1 | S | YL-011 | Komut ikinci kez çalışınca personel çoğalmaz, kaldırılan bağ/izin geri gelmez; dosya yolu parametreyle verilir, depoya girmez. |
| YL-014 | Müşteri / lokasyon / irtibat / takma ad ana verisi + API + hızlı ekleme ucu + `customers.*` izinleri + değişiklik denetimi | customers | YENİ | M14-01, M14-13, A3-10 | P1 | L | YL-010, YL-015 | Aynı VKN 409; normalize ad tekrarı onay ister; teknisyen 403 (irtibatı yalnız atandığı iş üzerinden görür); hızlı ekleme yalnız "doğrulanmamış" kayıt açar; silme ucu yok; her değişiklik eski/yeni değerle denetimde. |
| YL-015 | Merkezi denetim kaydı (yapan, hedef, eski/yeni JSON, gerçek istemci IP'si yalnız yerel nginx'e güvenilerek) + giriş/yetki/hesap/şifre olayları | audit | GÜVENLİK | M13-06, A1-16, A4-28, M14-13 | P1 | M | YL-002 | Şifre kayda girmez; API'den değiştirilemez/silinemez; başarısız girişler kaydedilir; `audit.view` ile sorgulanır. |
| YL-016 | Ek dosya/fotoğraf altyapısı | attachments | YENİ | M01-03 | P1 | M | YL-010 | Uzantı + magic byte kontrolü; tek dosya/istek; rastgele adla sunucu klasörüne yazım; path traversal engeli; indirme bağlı nesnenin kapsam kontrolünden geçer; yedek + geri yükleme testi; üst sınır ayardan (varsayım 10 MB). |
| YL-017 | Numara servisi (`NumberSequence` + `select_for_update`): SRV/PB/TKL/KIR/AT önekleri, aylık sıfırlama, taşma kontrolü, PB'de hedef ay, eski numaralardan devam | core | VERİ | A2-18, A3-21, R-07 | P1 | S | YL-002 | 50 eşzamanlı istekte mükerrer numara yok; 9999 sonrası anlamlı hata; aktarılan son numaradan devam eder; ay öneki TR saatine göre. |
| YL-018 | Ortak normalizasyon fonksiyonları: seri no, Türkçe metin/lokasyon (İ/ı), müşteri adı, plaka | core | VERİ | M01-16, M02-13, M03-D02, M14-09, M12-14 | P1 | S | YL-001 | Seri: trim + büyük harf (TR) + iç boşluk teke; baştaki 0 ve `/ - .` korunur; `' abc-001 '`→`ABC-001`; "Akyaka  AVM" = "AKYAKA AVM"; birim testleri ≥15 vaka. |
| YL-019 | Katalog/meta servisi: durum, öncelik, iş türü kuralları, talep kanalları, bekleme nedenleri — `TextChoices` + `CheckConstraint`, `/api/meta` | core | VERİ | A1-14, A3-12, A2-15, H-16, H-17, M10-13 | P1 | S | YL-001 | Katalog dışı değer DB'de reddedilir; ön yüz listeleri yalnız `/api/meta`'dan gelir; "Çözüldü" ve "Düşük" kararı (Soru 5) kataloğa yansır. |
| YL-020 | Fiyat/maliyet alan gizleme: serializer mixin'i (`finance.prices.view` yoksa alan yok/null, yazmada yok sayılır) + her fiyat içeren uç için otomatik test | core | GÜVENLİK | A1-02, A2-02, M05-17, M07-15, H-13, R-08 | P1-KRİTİK | S | YL-008 | Yeni bir fiyat alanı mixin'siz eklenirse test kırılır; izinsiz kullanıcının gönderdiği tutar yok sayılır (403 değil), mevcut değer korunur; PDF/Excel/CSV aynı kuralı uygular. |
| YL-021 | Türkçe arayüz iskeleti: giriş, zorunlu şifre ekranı, izne göre menü, 375 px mobil yerleşim, hash'li statik dosyalar, modül hata izolasyonu, yetkiye göre açılış ekranı | ui | ALTYAPI | A4-08, A4-24, A2-15 | P1 | M | YL-006 | İK rolü dahil her rol uygulamaya girer; bir modülün hatası diğerlerini durdurmaz; sürüm sonrası eski JS önbellekten gelmez; 375 px'te yatay kaydırma yok. |
| YL-022 | Veri aktarım çerçevesi: SQL Server'a salt okunur bağlantı, hedef DB adı doğrulama, rapor modu / uygula modu, idempotent içe aktarım, eşleme tabloları, eski yerel saatin Europe/Istanbul yorumlanması | legacy_import | VERİ | A3-01, A3-05, A4-03, A3-15, A2-05, M03-01*, M04-D03* | P1 | M | YL-002 | Kaynağa yazma yetkisi olmayan hesapla çalışır; rapor modu hiçbir satır yazmaz; ikinci çalıştırma 0 satır değiştirir; yalnız INSERT (mevcut düzeltmeleri ezmez, `IsActive` zorlamaz). |
| YL-023 | Eski veri salt okunur profil ve sağlık raporu | legacy_import | VERİ | M03-D01, M14-D03, M05-D03, M06-D03, A3-11, A1-03, M02-10, M04-D01 | P1 | M | YL-022 | Tek rapor: kütük eksik/mükerrer seri, lokasyonsuz cihaz, tarih desenleri; atölye 7 kontrolü; kiralama 4 uyumsuzluğu; müşteri varyantları; yetim kayıtlar; boş `AllowedUnits`; demo hesaplar; durum dağılımı; kapalıyken Planlandı'ya dönmüş ve çift aktif planlı işler; İptal PB'ler. Satır sayıları değişmez. |

\* = .NET'e özgü kaynak madde; gereksinimi buraya kabul kriteri olarak taşındı (§7.2).

---

## 3. Dalga 1 — Eski sistemle eşdeğerlik (38 madde)

Amaç: pilot kullanıcıların eski sistemi bırakabilmesi. Önce **kullanıcının çalıştığını doğruladığı işlevler** (K-1 KPI kutuları, K-2 toplu atama, K-3 Excel) ve **PB iş emirleri**, sonra diğer 21 ekranın eşdeğeri ve onaylı hata/eksik giderimleri. Eski kodun 19 hatası (H-01…H-19) birebir taşınmaz.

### 3.1 Dalga 1A — Doğrulanmış işlevler ve çekirdek

| ID | Başlık | App | Tür | Kaynak | Ö | E | Bağımlılık | Kabul kriteri |
|---|---|---|---|---|---|---|---|---|
| YL-024 | İş emri çekirdek modeli ve CRUD (açılış, liste, detay, seri satırları, iş türü kuralları, nullable müşteri/lokasyon FK'leri) | workorders | PARITY | Envanter §2.3, M14-05-A, M14-D01*, M05-D02, M01-D03 | P1 | L | Dalga 0 | Boş/boşluk müşteri adı 400, ad kırpılır, 251 karakter 400; "Atölye Teknik Servis" türü genel ekrandan 400 "Atölye ekranından açın"; kapalı/iptal işte seri değişikliği 400 (reopen izni + gerekçe hariç), eski→yeni geçmişe yazılır; müşteri kimliği boş eski kayıtlar hatasız açılır. |
| YL-025 | **Merkezi durum geçiş servisi** (`transition()`) + birleşik iş geçmişi + iş notu | workorders | EKSİK/YENİ | M01-09, M01-06, M01-D01*, M01-15*, M12-12, A2-07, A4-14, A4-15, A3-07, A3-13 | P1-KRİTİK | L | YL-024 | Katalog dışı 400; doğrudan Kapatıldı 400; teknisyen Kapatıldı 403 / Tamamlandı 200; gerekçesiz İptal/reopen 400; reopen alanları sıfırlar; aynı durum log üretmez; `ClosedAt` yalnız açık→kapalı geçişte; Çözüm/Kapanış/İptal zaman damgaları servisten; atama değişikliği "Atama değişti" olarak yazılır; not durumu değiştirmez; geçmiş silinemez/düzenlenemez; başka app'ler (atölye dahil) durumu yalnız bu servisle değiştirir, kapalı iş sessizce açılmaz. |
| YL-026 | Bekleme akışı tek serviste: tek aktif bekleme, katalogdan neden, geçmiş kaydı, Beklemede dışına her geçişte otomatik kapanış | workorders | HATA | M01-14, M10-11, A4-18, A3-13, H-18 | P1 | S | YL-025 | Hold/release geçmişe nedenle yazılır; ikinci hold 409; status ucuyla Beklemede 400; Kapatılan işte bekleme otomatik notla kapanır; "Beklemede olmayıp aktif beklemesi olan iş" sayısı 0; bekleme süresi dakika olarak raporlanır. |
| YL-027 | Kimlik bazlı çoklu teknisyen ataması ve tek sorumlu teknisyen (PersonnelId FK, ErpUserId türetilir) | workorders | EKSİK | M01-10, M02-03b, A4-19, A3-03, M09-13 | P1 | M | YL-011, YL-025 | Ad değişse de erişim sürer; aynı adlı iki kişi karışmaz; kapalı işe atama 400; açık sayaçlı teknisyeni çıkaran atama 409; her değişiklik geçmişe yazılır. |
| YL-028 | **Ana Panel KPI kutuları** (tıklanabilir, sayı = açılan liste) + iş kategorisinin tek sunucu fonksiyonu [✔K-1] | workorders | PARITY+HATA | K-1, M01-12*, M01-07, M05-D01, H-01, H-02 | P1 | M | YL-025 | Her kutunun sayısı ve listesi aynı sunucu filtresinden gelir ve eşittir (Sahada/İşlemde, Açık Bakım dahil); atölyedeki iş "Sahada" değil "Atölyede" kartında; kategori panel/liste/Ops/Excel'de aynı; kategorisi eşlenemeyen kurallar raporlanır. |
| YL-029 | Planlama takvimi + tekli plan ve ekip ataması tek uç/tek transaction | planning | PARITY+HATA | M02-10, M02-11, M01-13*, A4-16, H-06 | P1-KRİTİK | M | YL-025, YL-027 | Tamamlandı/Kapatıldı/İptal işe plan ve atama 400; yalnız Müşteri Talebi/Planlandı durumu Planlandı olur, diğer açık durumlar korunur; geçmişe gerçek eski durum yazılır; tarih zorunlu, süre 15–1440 dk; plan hata verirse atama da değişmez; yalnız plan izinli kullanıcı ekibi değiştirmeden plan kaydeder. |
| YL-030 | İş emri başına tek aktif plan garantisi | planning | VERİ | M02-D02, A3-14 | P1 | S | YL-029 | PostgreSQL kısmi benzersiz kısıt + `select_for_update`: eşzamanlı iki plan isteğinden sonra en fazla bir aktif satır. |
| YL-031 | **Toplu ekip ataması ve toplu planlama** (aynı müşteri + lokasyon + birim, TPL ziyaret grubu) [✔K-2] | planning | PARITY | K-2, R-17, R-18, M09-11 | P1 | M | YL-029 | Planlı/kapalı iş seçilemez; tüm seçim tek transaction'da; açık sayaçlı teknisyeni çıkaran toplu atama 409 ve hiçbir iş değişmez; lokasyon eşleşmesi YL-018 normalizasyonuyla (istemcide aynı grupta görünen iş sunucuda reddedilmez). |
| YL-032 | Sunucu tarafı plan çakışma kontrolü (uyarı + gerekçeyle geçme), şef ataması varsayılan "sorumlu" | planning | HATA/EKSİK | M02-09, M02-D01, A4-17, H-07, A3-14 | P1 | M | YL-029 | Çakışma API'de 409 + çakışan iş listesi; gerekçeli kayıt geçmişte görünür; aynı TPL ziyaretinin işleri birbirine çakışma vermez; şef yalnız "sahaya gidiyor" işaretliyse çakışmaya girer; eşzamanlı iki çakışan istekten ikincisi 409 (advisory lock). |
| YL-033 | **Excel dışa aktarma** (8 sayfa, tarih seçili/boş) — tipli hücre şeması, tek durum kataloğu, hesap doğruluğu [✔K-3] | reports | PARITY+HATA | K-3, M12-10, M12-11, M12-09, A2-14, M09-14, A2-13, A3-16, A4-20 | P1 | M | YL-025 | `0012345`, 18–19 haneli ve rakam dışı seri no'lar ile telefonlar birebir metin; tarih sütunları tarih filtresiyle süzülür; kişi-saat sayı olarak toplanır; süre kaydı olmayan işte hücre boş + "eksik"; Toplam = Açık + Çözülen + İptal + Tanımsız; Aylık Özet açılan/çözüleni ayrı sayar. |
| YL-034 | **PB iş emri üretimi (1 cihaz = 1 PB)**: yapısal sözleşme alanları, gerekçeli `skipped` listesi, cihaz kimliğiyle eşleşme, dönem bazlı tamamlanma, üretimin iş emri kapanışından ayrılması | maintenance | PARITY+HATA | M04-D02, M04-02, M04-01, M04-04a*, M03-09, M14-06, A2-03, A2-04, A3-02, A4-07, H-09, H-10, H-11, R-32…R-36 | P1-KRİTİK | L | YL-025, YL-059 | 17 cihazlı sözleşmede 17 PB doğru cihaz/seriyle; üretim `{generated, skipped}` döner (SEGATECH, KENTPARK, Ziraat/Sanko, "600 X-RAY" gerekçeli); 02.01.2027 üretiminde yeni dönem planlarından hiçbiri tamamlanmış doğmaz; ikinci üretim 0 iş emri açar; arıza iş emri kapanışında PB oluşmaz; üretim yönetim komutu + zamanlanmış görevle çalışır, üreten kullanıcı kaydedilir; süresi dolmuş/pasif sözleşmede PB yok; mevcut PB numaraları değişmez. |
| YL-035 | Dijital bakım formu (X-Ray 11 / Kapı 10 madde): kapanış kuralları, değişmez ziyaret kaydı, iş emri lokasyon/açıklaması ezilmez | maintenance | PARITY+HATA | R-42…R-45, M14-07*, M12-13, A3-08, M04-08 | P1 | M | YL-034 | Tüm maddeler Uygun değilse Tamamlandı yasak, diğer sonuçta iş Beklemede; bölge yalnız `Zone`'a, yapılan iş `PerformedWork`'e yazılır, iş emri Location/Description değişmez; dönem tüm cihazlar bitince bir kez kapanır, sayaç bir kez artar; aynı dönemde aynı seri ikinci cihazda olamaz; her tamamla çağrısı değiştirilemez ziyaret kaydı üretir (UserId ile). |
| YL-036 | PB iş emrinin genel uçtan döngüden çıkarılmasının engeli, cihaz dönem dışı bırakma (talep + şef onayı), gerekçeli yeniden açma | maintenance | HATA/EKSİK | M04-D01, M04-10, M04-14 | P1 | S | YL-035 | PB işe status=İptal 400 ve dönem dışı yoluna yönlendirir; 2 tamamlandı + 1 onaylı kapsam dışı dönem kapanır, sayaç bir kez artar; talep sahibi kendi talebini onaylayamaz; yetkisiz/gerekçesiz reopen reddedilir ve sayaç tutarlı geri alınır. |

### 3.2 Dalga 1B — Diğer mevcut ekranların eşdeğeri

| ID | Başlık | App | Tür | Kaynak | Ö | E | Bağımlılık | Kabul kriteri |
|---|---|---|---|---|---|---|---|---|
| YL-037 | Güvenlik cihaz kütüğü ekranı ve bakım sözleşmeleri listesi (görüntüleme, sunucu filtresi, Excel) + izinler | devices | PARITY | M03-12, M03-13, M03-D03*, A4-29 | P1 | M | YL-059 | Girişte kütük yüklenmez, ekran açılınca gelir; 1.324+ satır gezilebilir; Excel filtreyle aynı satır sayısında, seri metin; yalnız `workorders.view` sahibi kütük ve sözleşmede 403; `devices.view` teknisyen GET 200, POST/PUT 403; fiyat izni yoksa sözleşme ücreti dönmez. |
| YL-038 | Saha önerisi: aynı müşteri+lokasyonun son plan satırı ve tek normalize seri ile kütük lokasyonu | planning | PARITY+EKSİK | M02-12, M03-D02 | P2 | S | YL-029, YL-018 | 8 saha alanı önerilir, kullanıcının doldurduğu alan ezilmez; çoklu seri eşleşmesinde öneri yok; kayıt yoksa alan boş. |
| YL-039 | POC / Mobilite ekranı eşdeğeri | workorders | PARITY | Envanter menü 13 | P2 | S | YL-025 | Eski ekrandaki liste/filtre işlevleri yeni durum kataloğuyla çalışır (POC durumlarının çözüm kanalına taşınması Soru 5 ile Dalga 2'de). |
| YL-040 | Haberleşme atölye: durum makinesi + durum geçmişi, iş emri durumunun yalnız atölye ucundan değişmesi, tek atama kaynağı, OpsHolds senkronu | workshop | PARITY+HATA | M05-01, M05-10, M05-11*, M05-12*, M05-13*, M05-14*, M05-15, M05-18, M12-D02, H-08 | P1 | L | YL-025, YL-027 | Yeni kayıt yalnız "Kabul Edildi" ile; her geçiş atölye ve iş emri geçmişine aynı transaction'da; durum değişmeyen kayıt iş emrine dokunmaz; **atölye İptal → iş emri İptal** (gerekçe geçmişe); tamamlanma/teslim zamanı sunucudan, `EntryDate` gönderilmezse korunur; atölye seri değişince iş emri cihaz satırı güncellenir; genel PATCH ve ops hold atölye işinde 409; teknisyen yalnız atandığı kaydı görür; açık sayaçta Teslim Edildi 409. |
| YL-041 | Atölye tamir bedeli fiyat izni, sunucu doğrulaması, eşzamanlı düzenleme koruması | workshop | GÜVENLİK | M05-17, M05-19 | P1 | S | YL-040, YL-020 | `finance.prices.view` yoksa `repairAmount` null ve gönderilen tutar yok sayılır; tutarı yalnız `finance.prices.view + workshop.manage` değiştirir; uzunluk sınırları (Model ≤120, Marka+Model ≤150) 400; e-posta/liste değerleri sunucuda doğrulanır; eşzamanlı ikinci kayıt 409. |
| YL-042 | Kiralama: envanter hareket defteri (ekleme-yalnız), adet bazlı ayrı tahsis tablosu, durum makinesi | rentals | PARITY+HATA | M06-07, M06-13, M06-11, A2-17, A3-09, R-75…R-77 | P1 | L | Dalga 0 | 50 adetten 20+30 tahsis, 51. adet 409; seri takipli kalemde adet=1 CHECK; eşzamanlı tahsis stoğu aşamaz; normalize seri ürün bağımsız UNIQUE; sevksiz depoya alma 400, tekrar aşama 409; cihazı müşteride olan kiralama kapanamaz; eski "Teklif" → "Talep". |
| YL-043 | Kiralama: sevk şartı, cihaz bazlı kısmi sevk/iade, iptalde tahsis çözme, tek işlem kayıt, ürün kataloğu, izinler ve birim kontrolü | rentals | PARITY+HATA | M06-12, M06-04, M06-14, M06-15, M06-10, M06-16, M06-17 | P1 | M | YL-042 | Tahsis toplamı ≠ kalem adedi ise sevk 400, elle seri listesi yok sayılır; 5 cihazdan 3 Depo1/1 Depo2/1 Kayıp işlenir; sevksiz iptalde tahsisler çözülür, sevkliyse 409, gerekçe boşsa 400; eski sürümle kayıt 409; kullanılan ürün silinemez; `rentals.inventory` olmayan envanter ekleyemez; başka birim cihazı 403. |
| YL-044 | Kiralama uçtan uca otomatik testleri | rentals | TEST | M06-D04 | P1 | M | YL-043 | Ana akış, iptal, eşzamanlı tahsis ve birim yetkisi senaryoları envanter durumu + hareket sayısıyla doğrulanır. |
| YL-045 | Teklif eşdeğeri: oluşturma, sunucu doğrulama + satır bazında yuvarlama, birim kontrolü, PDF (tüm kalemler), "Elle gönderildi", mevcut e-posta gönderimi | offers | PARITY+HATA | M07-07, M07-14, M07-05a, M07-06a, A1-09, A1-10, A2-19 | P1 | M | YL-020, YL-025 | Geçersiz adet/iskonto/KDV, geçmiş `validUntil`, erişilemeyen iş emri 400/403 (500 yok); başka birim teklifinde durum değişikliği 404; 40 kalemin tamamı çok sayfalı PDF'te, Türkçe metin aynen kopyalanır, satır toplamı = Ara Toplam − İskonto; SMTP yoksa "Elle gönderildi" (kanal zorunlu); SMTP hata ayrıntısı yalnız loga. |
| YL-046 | Maliyet analizi eşdeğeri + eksik veri ayrımı | costing | PARITY+VERİ | M07-09, M07-D02, M07-D03, M09-14, A3-16 | P1 | S | YL-048 | Süre yoksa `labor:null` "Süre kaydı eksik"; tarife 0/tanımsız ise "Tarife tanımsız"; gelir yoksa `margin:null` "Gelir kaydı yok"; Ücretsiz-Garanti işte gelir 0 (not zorunlu); fark toplamı yalnız tam işleri içerir. |
| YL-047 | Eğitim / personel gelişimi eşdeğeri + onaylı hata giderimleri | training | PARITY+HATA | M08-08, M08-11(a,b), M08-13, M08-09, M08-14, M08-D03, M08-17, M08-D01, M08-16*, R-84 | P1 | L | YL-010, YL-011 | Yetkinlik değerlendirmesi her seferinde yeni satır; ileri tarihli oturum 400; katılım en eski açık planı kapatır; gözlem skoru sunucuda (100×Σpuan/(n×2)), kritik maddede gerekçesiz "Gözlenmedi" 400; gerekçeli soft iptal/erteleme (PreviousDueDate); başka birim kursuna oturum 403, pasif kursa 400; `notes/actionPlan/evidence` yalnız `training.view_detail`; uyarı birim süzmesi limitten önce; overview yanıtında detay alanları ayıklanır. |
| YL-048 | Saha / zaman takibi eşdeğeri | timetracking | PARITY+HATA | R-51…R-58, M09-08, M09-12, M09-13, M09-D01, M09-15*, M09-11 | P1 | L | YL-027 | Kişi başına tek aktif sayaç (DB tekil indeks); bölüm 1 dk–18 sa; mola kişi-saate dahil değil; çakışma kişi kimliğiyle; zaman DB saatinden; kaynak (Canlı/Manuel) ve gerekçe alanları, 30 dk'dan eski manuelde gerekçe, yetkisiz kullanıcı en fazla 2 gün geriye; açık sayaçlı iş/bakım kapatılamaz; 18 saati aşan sayacı teknisyen gerçek bitişle kendisi kapatır; DB düzeyinde filtre, hafif `/timetracking/me`, WorkOrderId indeksi. |
| YL-049 | Zaman kuralları otomatik test seti | timetracking | TEST | M09-D03 | P1 | M | YL-048 | Tüm zaman senaryoları her koşuda sıfırdan kurulan test DB'sinde yeşil. |
| YL-050 | Mobil teknisyen paneli eşdeğeri (kendi işleri, sayaç başlat/değiştir/bitir) | timetracking | PARITY | Envanter menü 3 | P1 | S | YL-048 | 375 px'te kullanılabilir; yalnız kendine atanmış açık işler; fiyat/maliyet yok. (Geliştirilmiş "Benim İşlerim" YL-113.) |
| YL-051 | Operasyon Merkezi eşdeğeri + onaylı hata giderimleri | operations | PARITY+HATA | M10-10, M10-11, M10-12, M10-13, M10-14, H-03, A4-21 | P1 | M | YL-026 | PB işleri öncelik SLA'sı dışında, vade plan dönem sonundan; "Vadesi geçen bakım" ayrı sayaç; Geciken yalnız bakım dışı işler; kapalı iş Bekleme sayacında yok; "Acil" gibi katalog dışı öncelik 400; yalnız `dashboard.view` olan kullanıcı overview'da 403 (`operations.view` gerekir); sayaç düğmeleri filtreler. |
| YL-052 | Yedek parça stoğu eşdeğeri: tür+yön hareket defteri, tek stok servisi, negatif stok ve kapalı işe çıkış engeli, az stok tek fonksiyon, açılış stoğu CSV | stock | PARITY+HATA | M11-D01, M11-14, M11-15*, M11-10, M11-17, A3-18, R-78 | P1 | M | YL-025 | Tüm yazımlar tek servis (`atomic` + `select_for_update`); bakiye 1'de iki paralel çıkıştan biri 400; kapalı/iptal işe çıkış 400; iş emrine bağlı iade yalnız İade türüyle ve net çıkışla sınırlı, malzeme tutarı negatif olamaz; Depo1=5/Depo2=0/min=3 → "Yeterli"; CSV ya tamamen ya hiç yüklenir. |
| YL-053 | Raporlar web ekranı eşdeğeri + lokasyon kavramları ayrımı + atölye kategorisi | reports | PARITY | E-16, M12-12, M12-13, M12-D02 | P1 | M | YL-025, YL-033 | Kişi-saat faaliyet başlangıç tarihine göre süzülür; tesis/bölge/not ayrı alanlardan tek öncelik kuralıyla gruplanır; iptal edilen atölye işi açık/geciken görünmez; ekran toplamları Excel ile eşit. |
| YL-054 | Kullanıcı/Yetki ve Personel/Organizasyon ekranları eşdeğeri | accounts, personnel | PARITY | Envanter §2.2, §2.7, M13-01(A), M13-07 | P1 | M | YL-009, YL-011 | Rol şablonu uygulama, kişi izni, birim seçimi, hesap bağlama/ayırma ekrandan yapılır; birimsiz personel ve Notes yalnız `personnel.manage`'e; personel listesi birim kapsamına göre süzülür. |
| YL-055 | Depo ve Muhasebe ekranları eşdeğeri | rentals, costing | PARITY | Envanter menü 18–19 | P2 | S | YL-042, YL-046 | Eski ekranlardaki listeler yeni modellerden aynı kolonlarla gelir; `accounting.view` yoksa 403. |

### 3.3 Dalga 1V — Veri aktarımı (pilot SQL Server → PostgreSQL)

| ID | Başlık | App | Tür | Kaynak | Ö | E | Bağımlılık | Kabul kriteri |
|---|---|---|---|---|---|---|---|---|
| YL-056 | Kullanıcı / izin / birim aktarımı ve izin göçü | legacy_import | VERİ | M01-D02*, M13-08, A1-03, A1-13, M10-14, M06-16 | P1 | S | YL-022, YL-008 | Pipe alanlar M2M'e açılır; boş `AllowedUnits` 5 birimin açık listesine çevrilip raporlanır; demo hesaplar taşınmaz veya pasif + zorunlu şifre değişimiyle gelir; teknisyen `close`→`complete`; önizleme raporlu ve idempotent. |
| YL-057 | İsim metni → personel/kullanıcı kimliği eşlemesi (atama, süre kaydı, gözlemci, şef, yönetici) | legacy_import | VERİ | M13-10, A2-06, A3-03, A4-19, M02-03b, M09-13, H-12 | P1 | M | YL-056 | Betik kayıt sayılı/normalize önerili `PersonnelNameMap` üretip Excel'e verir; yalnız onaylı satırlar uygulanır, eski metin anlık kopya olarak korunur; eşleşmeyen "eşleşmedi" kalır, tahmin yapılmaz; SicilNo tekrarı 409; satır silinmez. |
| YL-058 | İş emri, durum logu, plan, bekleme, atama aktarımı | legacy_import | VERİ | M02-10, M02-D02, A1-14, A3-12, M10-13, A2-18 | P1 | M | YL-057 | Durumlar eşleme tablosuyla normalize (POC, Çözüldü, eski Beklemede); kapalıyken Planlandı'ya dönmüş ve çift aktif planlı kayıtlar listelenir, **onayınızla** düzeltilir; WorkOrderNo vb. korunur; numara sayaçları son değerden devam. |
| YL-059 | Cihaz kütüğü ve bakım sözleşmesi aktarımı | legacy_import | VERİ | M03-01*, M04-D03*, A3-05, A4-03, M03-10(tarih), A3-22, M04-D02 | P1 | M | YL-022 | Kaynak, Excel seed değil **canlı pilot DB'deki düzeltilmiş veri**; yalnız INSERT, ikinci çalıştırmada satır sayısı ve düzeltmeler/pasif durumlar korunur; `DeliveryDateText` ('44083'→2020-09-09) DATE'e dönüştürülür, orijinal metin saklanır, dönüştürülemeyenler "kontrol gerekli"; 87 sözleşme "ayrıştırıldı / teyit bekliyor" durumuyla Excel teyit listesine çıkar. |
| YL-060 | Atölye, kiralama, teklif, eğitim, stok ve süre kayıtları aktarımı + uzlaştırma raporları | legacy_import | VERİ | M05-D03, M06-D03, M05-05, M11-17, M11-18, M08-08, A3-15, A3-18 | P1 | L | YL-057, YL-058 | Tarayıcı UTC'siyle yazılmış atölye tarihleri düzeltilir; Accessory1..5 adet 1 satıra; stok defter–bakiye mutabakat raporu; eski serbest metin parça kayıtları değişmeden "Not" olarak korunur, stok hareketi üretmez; iptal edilmiş süre/sayaç/pasif satırlar denetim izi olarak taşınır; her uygulama adımı kullanıcı onaylı. |
| YL-061 | Karşılaştırmalı kabul testi ve geçiş provası | legacy_import, reports | TEST | M12-D01, Envanter §7, §9 | P1 | M | YL-024…YL-060 | Aynı veride eski ve yeni sistemin KPI kutuları, Excel toplamları ve PB sayıları eşit (farklar bilinen H-xx hatalarıyla açıklanır); envanterin "en riskli 15 kural"ı testle doğrulanır; tam aktarım provası süre ölçümüyle en az bir kez yapılır; kullanıcı test verisiyle onay alınır. |

---

## 4. Dalga 2 — Yeni modül ve özellikler (c) (79 madde)

| ID | Başlık | App | Tür | Kaynak | Ö | E | Bağımlılık | Kabul kriteri |
|---|---|---|---|---|---|---|---|---|
| YL-062 | Kapanış formu: ziyaret sonucu ile tamamlanmanın ayrılması | workorders | YENİ | M01-01 | P1 | M | YL-025 | Sonuç yokken Tamamlandı 400; yalnız Çözüldü/Çözülemedi ile tamamlanır; "Tekrar Gidilecek" Planlamada'ya döner; "Teklif Sunulacak" beklemeye girer; Excel kolonları çıkar. |
| YL-063 | Zorunlu çözüm kanalı; açılışta "çözüldü" kısa yolu (karara bağlı); POC eşlemesi | workorders | YENİ | M01-02 | P2 | M | YL-062 | Sonuç kaydında kanal zorunlu; onaylanırsa `resolve_remote` tek istekte tamamlar; eski POC eşlemesi eşlenemeyenleri raporlar. |
| YL-064 | Talep bilgileri, mükerrer kayıt kontrolü ve bağlı iş ilişkisi | workorders | YENİ | M01-05, M01-D04, M10-04(bağ) | P2 | M | YL-018, YL-024 | Kanal ve kişi/telefon zorunlu; aynı normalize seri açık işte 409, `force=true` geçmişe yazılır ve iş bağlanır; müşteri+lokasyon yalnız uyarı; iş kendine bağlanamaz. |
| YL-065 | Müşteri onayı (ziyaret bazlı tek onay) ve yazdırılabilir HTML servis/bakım formu | workorders, maintenance | YENİ | M01-04, M04-06, M04-07 | P2 | M | YL-016, YL-062, YL-035 | Onay değiştirilemez; ad, unvan, yöntem, sunucu zamanı; imtinada gerekçe; zorunluluk ayarı başlangıçta kapalı; Türkçe doğru basılır; süre yoksa "Süre kaydı eksik"; fiyat yok; parça bölümü yoksa "kayıt yok"; form erişim kontrolü. |
| YL-066 | İş kaydında müşteri–lokasyon–irtibat seçimi, hızlı ekleme, plan saha bilgisinin lokasyondan dolması | workorders | YENİ | M14-04 | P1 | M | YL-014, YL-024 | Yeni işte CustomerId/SiteId dolu; yabancı lokasyon veya pasif müşteri 400; plan formu lokasyondan ön dolar. |
| YL-067 | Müşteriler ekranı ve müşteri/lokasyon kartı | customers | YENİ | M14-02 | P2 | M | YL-066 | Açık iş sayısı iş listesiyle aynı; fiyat alanları gizli; birim yetkisi; 375 px'te kullanılabilir. |
| YL-068 | Onaylı müşteri eşleştirme içe aktarma (Faz 1 sözleşme + kütük, Faz 2 diğer tablolar), sözleşme tesis/cari ayrımı ve dönem çakışma uyarısı | customers, legacy_import | VERİ | M14-03, M14-08 | P1 | L | YL-014, YL-059 | Aday üretimi veri değiştirmez; yalnız onaylı satırlar yazılır; eski metinler korunur; tekrar çalıştırılabilir; tablo bazında sayı raporu; çakışan aktif sözleşme onay ister, hiçbir sözleşme otomatik pasifleşmez. |
| YL-069 | Mükerrer önleme ve müşteri/lokasyon birleştirme | customers | YENİ | M14-09 | P2 | M | YL-068 | Tek transaction; önizleme sayıları gerçekleşenle eşit; geçersiz hedef 400; `customers.merge` yoksa 403. |
| YL-070 | İş açılışında sözleşme kapsam bilgisi ve CoverageStatus anlık görüntüsü | workorders | YENİ | M14-11 | P3 | S | YL-066, YL-079, YL-082 | Dönem ayrıştırılamazsa "Sözleşmeli" denmez; tutar yok; CoverageStatus sonradan değişmez. |
| YL-071 | Ana panel KPI seti ve dönem seçimi | workorders | EKSİK | M01-11 | P2 | M | YL-028, YL-062, YL-064, YL-134 | Sayı = liste; alt kutular toplamı = Açık Servis; Geciken Ops ile aynı; süre yoksa "eksik". |
| YL-072 | Erteleme nedeni zorunluluğu, planı geri alma ve plan geçmişi | planning | YENİ | M02-02 | P2 | M | YL-030 | Aktif planlı işte nedensiz tarih değişikliği 400; geri alınan plan işi havuza ve önceki duruma (aktif bekleme varsa Beklemede) döndürür; kapalı işte geri alma reddedilir. |
| YL-073 | Ziyaret kartındaki seçili işleri tek işlemde yeniden planlama (iş emri ID listesiyle) | planning | YENİ | M02-01 | P2 | M | YL-072 | 17 işlik kart tek transaction'da taşınır; seçilmeyen iş aynı grup no'yu taşısa da taşınmaz; kapalı/farklı birim iş 400 ile listelenir; her işe eski/yeni tarih + neden yazılır. |
| YL-074 | Şehir/ilçe bazlı havuz ve aynı bölge önerisi | planning | YENİ | M02-06 | P2 | M | YL-066 | Havuz lokasyon ↔ şehir-ilçe gruplaması arasında geçer; şehri boş işler ayrı grupta; aynı ilçedeki plansız işler ve ±3 gün planlı ziyaretler önerilir; seçilen iş ayrı tekli plan olarak kaydedilir. |
| YL-075 | Personel müsaitlik blokları (Şef/Müdür girer, uyarı üretir, bordro değil) | personnel, planning | YENİ | M02-05 | P3 | M | YL-032 | İzinli personele plan uyarı + gerekçe ister; blok silinince uyarı kalkar; bloklar kişi-saate girmez. |
| YL-076 | Kaynak (ekip) görünümü: personel × gün, plan dakikası | planning | YENİ | M02-04 | P3 | M | YL-075 | Hafta modunda birimdeki her aktif personel için satır; boş personel görünür; hücrede "plan" etiketli dakika; teknisyen yalnız kendi satırı. |
| YL-077 | Plan uyumu raporu (ilk sürüm) | reports | YENİ | M02-07 | P3 | M | YL-072, YL-134 | Plan bekleyen yaşı, plana uyum (süre yoksa ayrı "eksik" satırı), erteleme, ziyaret başına iş, tekrar ziyaret; servis/bakım ayrı; Excel = web; tahmini süre gerçek süre olarak geçmez. |
| YL-078 | Cihaz detay kartı, birleşik cihaz geçmişi ve bakım geçmişi ucu | devices | YENİ | M03-02, M04-09 | P1 | M | YL-037, YL-035 | Tarih sıralı olaylar; süre yoksa "eksik"; maliyet fiyat izni olmayana dönmez; seri ve bölge sonraki döneme devredilir, baştaki sıfırlar korunur; birim yetkisi. |
| YL-079 | Garanti tarihleri/kaynağı ve sözleşme bağlantısı | devices | YENİ | M03-03 | P2 | M | YL-145 | Geçmiş bitiş "Garanti Bitti", boş "Bilinmiyor"; bitiş<başlangıç 400; sözleşmede ayrı "bağlı cihaz" sayısı, plan cihaz sayısı değişmez. |
| YL-080 | Cihaz yaşam döngüsü durumu (Kurulu/Sevk Edildi/Devre Dışı/Hurdaya/Bilinmiyor; "Serviste" hesaplanır) | devices | YENİ | M03-04 | P2 | M | YL-145 | Gerekçesiz durum değişikliği 400; Devre Dışı/Hurdaya cihaz hiçbir yolda PB üretimine girmez; açık işler silinmez, uyarı verilir. |
| YL-081 | Kütük KPI ilk sürüm (12 aydan eski bakımlı sözleşmeli cihaz; 90 günde ≥2 PB dışı arıza) | devices | YENİ | M03-05 | P3 | M | YL-078…YL-080 | KPI sayısı = açılan liste satırı; seri no'suz cihaz tekrar arıza listesine girmez. |
| YL-082 | Bakım sözleşmesi yönetimi ve tür + adet cihaz kapsam tablosu | maintenance | YENİ | M04-03 | P1 | L | YL-034 | 2 X-Ray + 3 kapı kapsamlı sözleşmede 5 PB; yetkisiz kullanıcıda ücret null ve kaydedilmez; süresi dolmuşta dönem üretilmez. |
| YL-083 | Sözleşme başlangıcına/sabit aylara dayalı hedef tarih, gerekçeli elle tarih, önizleme, üretim kaydı, ön açılış | maintenance | YENİ | M04-04b | P2 | M | YL-082 | 01.06.2026 başlangıçlı 3 bakımlı sözleşme Haz/Eki 2026, Şub 2027 hedefi alır; elle hedef korunur; önizleme satır yazmaz. |
| YL-084 | Uygunsuzluk notu zorunluluğu, bekleme kaydı, basit aksiyon tablosu, butonla bağlı arıza iş emri | maintenance | YENİ | M04-05 | P2 | S+M | YL-035, YL-026 | Notsuz uygunsuz madde 400; 2 uygunsuzlukta 2 aksiyon + bekleme nedeni; açık aksiyonla PB tamamlanamaz. |
| YL-085 | Kontrol şablonlarının veriye taşınması | maintenance | EKSİK | M04-13 | P3 | M | Soru S6/S7 | Taşıma sonrası 11/10 madde aynen çıkar; yeni tür şablonuyla 2 adet için 2 PB. |
| YL-086 | Yapılandırılmış teşhis ve onarım kaydı | workshop | YENİ | M05-02 | P2 | M | YL-040 | Teşhisten çıkışta arıza kategorisi zorunlu; test "Geçti" değilse Teslime Hazır reddedilir; onarılamazsa yalnız "Onarılmadan İade". |
| YL-087 | Ücretli onarımda müşteri onayı ve teklif bağlantısı | workshop | YENİ | M05-03 | P2 | M | YL-089, YL-099 | Garanti "Garantili" değilse (Bilinmiyor dahil) Onarımda'ya geçiş onay veya gerekçeli "onay gerekmez" olmadan reddedilir. |
| YL-088 | Kabul fişi / teslim tutanağı ve satır bazlı aksesuar kaydı | workshop | YENİ | M05-04, M05-05 | P2 | M | YL-040 | Türkçe ve seri no aynen basılır; izinsiz kullanıcının çıktısında/JSON'unda tutar yok; sınırsız aksesuar satırı; teslimde işaretlenmemiş aksesuar varsa açıklamasız Teslim Edildi 400. |
| YL-089 | Seri no geçmişi ve açık kayıt engeli; garanti durumunun sunucu hesabı | workshop | YENİ | M05-06, M05-07 | P2 | M | YL-040 | Aynı seri açık kayıt varken 409 + mevcut atölye no; kabulde seri geçmişi; tekrar geliş penceresi yapılandırılabilir (varsayım 90 gün); bitiş<kabul "Garanti Dışı", tarih yoksa "Bilinmiyor". |
| YL-090 | Atölye listesi sunucu filtre/arama/sayfalama + yaşlandırma, KPI/Excel, teslim/kargo kuralları | workshop | YENİ | M05-08a, M05-08b, M05-09 | P2 | M | YL-040 | 0-3/4-7/8-14/15+ gün kutuları; çevrim süresi yalnız "Teslime Hazır" logu olanlardan, diğerleri "süre kaydı eksik"; Kargo + boş takip no ile Kargoya Verildi 400; teslim alan boşken Teslim Edildi 400. |
| YL-091 | Dış servis (üretici/distribütör RMA) takibi | workshop | YENİ | M05-D04 | P3 | M | YL-040 | "Dış Serviste" durumu ve ExternalVendor/RmaNo/SentAt/ReturnedAt; süre atölye performansından ayrı raporlanır. |
| YL-092 | Dönüş kontrol kaydı (Kontrolde / Hazır Değil) | rentals | YENİ | M06-03 | P2 | M | YL-043 | Yalnız Kontrolde/Hazır Değil cihaz kabul edilir; sonuca göre Hazır/Hazır Değil; kontrol eden ve zaman kaydedilir. |
| YL-093 | Tarih bazlı müsaitlik ve ürün/adet rezervasyonu (uzatma dahil) | rentals | YENİ | M06-01 | P2 | M | YL-043 | Sorgu toplam/rezerve/müsait/kontrolde döner; çakışma Planlandı geçişini ve bitiş uzatmasını 409 ile reddeder; Kayıp/Hazır Değil düşülür. |
| YL-094 | Teslim ve iade tutanağı (fiyatsız) | rentals | YENİ | M06-06 | P2 | S | YL-043 | Yalnız tahsisli seriler; sevk öncesi TASLAK; fiyat/maliyet yok. |
| YL-095 | Kiralama uyarıları (kademeli) | rentals | YENİ | M06-09 | P2 | S | YL-093, YL-124 | Her uyarı türü test verisiyle üretilir; birim yetkisine uyar; eşikler ayardan. |
| YL-096 | Kurulum/toplama işlerinin iş emrine bağlanması | rentals | YENİ | M06-02 | P2 | L | YL-043, YL-048 | Aşamada bağlı iş emri seçilir; ekip atanmış personelden, süre zaman kayıtlarından (yoksa "eksik"). |
| YL-097 | Sahada cihaz değişimi birleşik ekranı | rentals | YENİ | M06-05 | P3 | S | YL-043 | Yeni seri kalemde; eski cihaz geçmişinde "değiştirildi"; rezervli cihazla işlem reddedilir. |
| YL-098 | Kiralama ilk üç rapor (depo anlık, geciken iade, kontrolde bekleme) | reports | YENİ | M06-08 | P3 | M | YL-134 | Birim yetkisi; süre yoksa "eksik". |
| YL-099 | Teklif onay akışı ve durum makinesi + teklif detay ekranı | offers | EKSİK | M07-02, A1-09 | P1 | M | YL-045 | Taslak→Kabul 409; ayar açıkken öz-onay 403; nedensiz ret 400; her geçiş geçmişte; süresi geçen gönderilmiş teklif "Süresi Doldu" hesaplanır. |
| YL-100 | Taslak teklif düzenleme ve revizyon (ParentOfferId + RevisionNo) | offers | YENİ | M07-01 | P2 | M | YL-099 | Taslak dışı PUT 409; Kabul teklife revize 409; R1 açılınca R0 "Revize Edildi". |
| YL-101 | Teklif–iş emri bağlantısı, bakım formundan kısayol, OfferId'li bekleme, "Teklif Sunulacak" uyarısı | offers | YENİ | M07-03, M07-D04 | P2 | S | YL-099, YL-026 | Bağlı teklifler iş emrinde; Beklet ile iş Beklemede; 2 gün geçmiş teklifsiz bulgu uyarıda, teklif açılınca kalkar; fiyat izni yoksa tutar yok. |
| YL-102 | Kabul edilen teklifin KDV hariç tutarının iş gelirine aktarımı + gelir/maliyet değişiklik geçmişi | costing | YENİ | M07-04, M07-13 | P2 | S | YL-099, YL-046 | 10.000 TL + KDV kabulünde gelir 10.000,00 kaynak "Teklif"; elle gelir korunur + uyarı; iptalde geri alınır; her değişiklik eski→yeni; `finance.prices.view` yoksa 403. |
| YL-103 | Kurumsal teklif PDF şablonu | offers | YENİ | M07-05b | P2 | S | YL-045 | Firma bilgisi, logo, revizyon no, hazırlayan/onaylayan, şartlar, KDV oranı dökümü. |
| YL-104 | Geçerlilik tarihli saatlik iç maliyet tarifesi | costing | VERİ | M07-10 | P2 | S | YL-046 | Ekim 500 / Kasım 600 TL/sa ile 2 saatlik kayıtlar 1.000 / 1.200 TL; Ekim raporu değişmez. |
| YL-105 | Teklif dönüşüm raporu | reports | YENİ | M07-12 | P3 | S | YL-099 (2–3 ay veri) | Örnek veride kabul oranı %60; revize teklif tek sayılır; yetkisiz birim girmez. |
| YL-106 | Kritik İSG uygunsuzluğu için gözlem başına tek düzeltici faaliyet | training | YENİ | M08-01 | P2 | M | YL-047 | Kritik 0 içeren gözlem 1 açık faaliyet açar; uygun yeni gözlemle otomatik veya `training.manage` + kanıtla kapanır (kanıt boşsa 400); vadesi geçmiş faaliyet uyarı üretir. |
| YL-107 | Gözlemi iş emrinden başlatma/gösterme | training | YENİ | M08-02 | P2 | M | YL-047 | İş emri detayından form kilitli açılır; bağlı gözlemler listelenir; başka birim iş emri 403; eski iş emirleri aramayla seçilir. |
| YL-108 | Teknisyen "Gelişim Kartım" ve "Gördüm" onayı | training | YENİ | M08-05 | P2 | M | YL-047 | `/api/training/me` yalnız kendi verisi, başkası 403; onay geri alınamaz; bağlantısız kullanıcıya bilgi mesajı. |
| YL-109 | Oturumda toplu katılım girişi | training | YENİ | M08-06 | P2 | S | YL-047 | 15 satır tek transaction; hatalı satırda hiçbiri yazılmaz ve satır belirtilir. |
| YL-110 | Zorunlu eğitim/belge geçerlilik takibi | training | YENİ | M08-03 | P2 | M | YL-047 | 12 ay periyotlu eğitimi 01.11.2026'da tamamlayanın geçerliliği 01.11.2027; ≤30 gün kalan uyarıda; belge listesi gelene kadar uyarı üretilmez. |
| YL-111 | Eğitim etkinliği raporu ve xlsx (aşamalı) | reports | YENİ | M08-07 | P2 | M | YL-047, YL-134 | Kurs × birim 0/30/60/90 başarı oranı ve 0→90 farkı; veri yoksa "veri yok"; xlsx birim kapsamlı. |
| YL-112 | İş emri atamasında yetkinlik/belge uyarısı (engellemez) | training | YENİ | M08-04 | P3 | M-L | YL-027, YL-110 | Yetersiz seviyeli atama `warnings` döner ama kaydedilir; eşleme boşsa uyarı yok. |
| YL-113 | Mobil "Benim İşlerim", tek sayfa iş kartı ve "Bugünkü ziyaretlerim" (öncelik rozeti, SLA kalan süre) | timetracking | YENİ | M09-01, M02-08, M10-D01 | P1 | M | YL-050, YL-114 | Teknisyen/Şef kendine atanmış açık işleri plan saatine göre gruplu görür; 17 PB işi tek ziyaret kartında; aktif sayaç üstte; telefona dokununca arama; SLA'sı en yakın iş ilk sırada, PB'de "Vade: Ekim 2026"; 375 px'te yatay kaydırma yok; fiyat yok. |
| YL-114 | Tek dokunuşla saha akış düğmeleri, sunucuda resume, bekleme nedeni; iş beklemesi ile sayaç "Bekleme" faaliyetinin ayrımı | timetracking | YENİ | M09-02, M10-D02 | P1 | M | YL-048, YL-049 | Saha–Mola–Devam sonunda boşluksuz bölüm; mola süre kaydına yazılmaz; nedensiz Bekleme 400; neden sözlüğü bekleme kataloğuyla aynı; sayaç Beklemesi SLA'yı etkilemez. |
| YL-115 | Sayacı sonraki iş emrine taşıma (`targetWorkOrderId`) | timetracking | YENİ | M09-03 | P2 | S | YL-114 | A'nın bitişi = B'nin başlangıcı; atanmamış/kapalı hedef 400; hata olursa iki taraf değişmez. |
| YL-116 | Teknisyen "Bugünüm" özeti ve gün sonu eksik listesi | timetracking | YENİ | M09-04 | P2 | M | YL-048 | 60+30 dk ve 15 dk molada 1 sa 30 dk ve mola (hariç) görünür; kaydı olmayan iş "Süre kaydı eksik". |
| YL-117 | Uzun açık sayaç uyarısı ve yönetici "iptal et ve düzelt" | timetracking | YENİ | M09-05 | P2 | M | YL-048, YL-124 | 10 saati (ayar) aşan oturum uyarıda; düzeltme tek transaction'da "Yönetici Düzeltmesi" kaydı; çakışmada 409. |
| YL-118 | İş emri zaman çizelgesi ve Tam/Kısmi/Eksik metrikleri | timetracking | YENİ | M09-06 | P2 | M | YL-027 | Biri kayıt girmişse "Kısmi"; kaydı olmayan işte sapma ve Excel hücresi boş + "Eksik"; ekran = Excel. |
| YL-119 | Personel tablosuna veri disiplini sütunları | reports | YENİ | M09-07 | P3 | S | YL-048 | 3 canlı (120 dk) + 1 manuel (60 dk) → canlı oranı %66,7; 2 gün sonra girilen manuel gecikmeli. |
| YL-120 | SLA politikası (öncelik + isteğe bağlı birim), işe damgalanan hedef, FirstResponseAt/ResolvedAt, tekrar açılma kuralı, gecikme nedeni Kapatıldı adımında | operations | YENİ | M10-01, A4-21 | P1 | M | YL-025, YL-048 | Kritik iş açılınca ResolveDueAt = SlaStartAt + 12 sa; SLA değişince eski hedef değişmez; ilk Saha/Uzaktan/Atölye sayacı FirstResponseAt'i doldurur (Yol/Bekleme/Mola doldurmaz); hedef geçmiş işte gecikme nedenisiz Kapatıldı 400; SLA değişikliği denetimde. |
| YL-121 | Ortak mesai takvimi (isteğe bağlı öğle arası) ve resmi tatil tablosu | operations | YENİ | M10-02 | P2 | M | YL-120 | Pzt–Cum 08:30–17:30 iken Cuma 16:30 açılan 8 saatlik işin hedefi Pazartesi 15:30; tatil sayılmaz; 7/24 politika etkilenmez; ≥6 birim testi. |
| YL-122 | Bekleme nedeni kataloğu yönetimi, SLA durdurma bayrağı, beklenen bitiş tarihi | operations | YENİ | M10-03 | P2 | M | YL-026, YL-120 | Katalog dışı/pasif neden 400; SLA durduran nedenle bekleyen işin hedefi bekleme süresi kadar kayar (Malzeme ile kaymaz); beklenen bitiş geçmiş olamaz; teknisyen yalnız kendi işini bekletir. |
| YL-123 | Tekrar arıza işareti (çoklu seri eşleşmesi, onay), kök neden Kapatıldı adımında | operations | YENİ | M10-04 | P2 | M | YL-064, YL-025 | Herhangi bir aktif seri son 30 günde kapanmış servis işiyle eşleşirse iş işaretlenir (45 gün işaretlenmez); PB tetiklemez; işaretli iş kök nedensiz Kapatıldı olamaz, Tamamlandı engellenmez. |
| YL-124 | Kalıcı bildirim tablosu, 5 dk arka plan üretimi, izin+birim bazlı alıcı, her sayfada rozet | notifications | YENİ | M10-05, M10-D04* | P2 | M | YL-120, YL-122 | Aynı koşul için tek kayıt, koşul kalkınca kapanır; başka birim bildirimi görünmez; teknisyene yalnız kendi işleri; rozet yalnız COUNT, 1000 açık işte <200 ms; okundu tek UPDATE. |
| YL-125 | Operasyon merkezi yeni sayaçlar, SLA kalan süre sıralaması, filtreler, dönem seçimi; SLA durumu tek sunucu fonksiyonundan | operations | EKSİK | M10-08, M10-D03 | P2 | S-M | YL-120, YL-134 | Atanmamış sayacı = liste; birim filtresi sayaçları yeniden hesaplar; Ana Panel, Ops, Excel ve bildirim gecikme sayıları eşit; ön yüzde SLA hesabı yok. |
| YL-126 | Personel iş yükü: canlı sayaç durumu ve bugün/yarın planlı yük | operations | EKSİK | M10-09 | P2 | S | YL-027, YL-048 | Sayaç başlayınca satırda iş no + faaliyet; aynı adlı personel ayrı satırda; Mola çalışma sayılmaz. |
| YL-127 | Eski veriden SLA alanlarının geri doldurulması | legacy_import | VERİ | M10-15 | P2 | S-M | YL-120, YL-058 | Rapor modu veri değiştirmez; ikinci çalıştırma 0 satır; logu/ClosedAt'i olmayan kapalı iş "Ölçülemedi"; PB hariç; SlaSource = "Geriye dönük (güncel hedef)". |
| YL-128 | E-posta bildirimi (anlık SLA aşımı + günlük özet), giden kutusu, 3 deneme | notifications | YENİ | M10-06 | P3 | M | YL-124, SMTP | SMTP yokken hatasız kuyrukta bekler; bildirim başına tek e-posta; 3 hatada Başarısız; parola yalnız ortam değişkeninde; fiyat yok. |
| YL-129 | İş emri detayında "Kullanılan Parçalar" ve `stock.use` ile teknisyen parça kullanımı | stock | YENİ | M11-01, M11-12 | P1 | L | YL-052 | `stock.use` sahibi yalnız erişebildiği açık işe çıkış yapar; kapalı işe 400; stok yetersiz 400; yetkisiz işe 404; maliyet anahtarı izne bağlı; rol şablonları güncellenir, mevcut kullanıcı izinleri değişmez. |
| YL-130 | İade ve ters kayıt (düzeltme) | stock | YENİ | M11-02 | P1 | M | YL-129 | İade net çıkışı aşamaz; ters kayıt gerekçeli ve tek seferlik; bakiye geri döner, finans tutarı doğru yönde değişir. |
| YL-131 | Stok hareket geçmişi, depolar arası transfer, stok sayımı | stock | YENİ | M11-03, M11-04, M11-05 | P2 | M | YL-052 | Hareketler birim kapsamlı ve CSV formül enjeksiyonuna korumalı; transfer aynı TransferGroupId'li iki hareket; sayım onayında bakiye düzelir, aynı depoda iki açık sayım yok. |
| YL-132 | Parça tüketim raporu ve iş emri/seri bazlı geçmiş (parça × marka/model kırılımı dahil) | reports | YENİ | M11-07, M12-07(not) | P2 | M | YL-130, YL-134 | Net çıkış = çıkış − iade − ters kayıt, defterle birebir; PB ve servis ayrı; tutarlar izne bağlı. |
| YL-133 | Parça talebi ve malzeme bekleme bağlantısı | stock | YENİ | M11-06 | P2 | M | YL-129, YL-026 | Talep depo listesinde; girişte "Parça geldi" uyarısı; çıkışta "Karşılandı"; iş kapanınca "İptal". (Soru 13 "hayır" ise düşer.) |
| YL-134 | Sunucu tarafı tek KPI/rapor motoru ve `summary` ucu | reports | YENİ | M12-01 | P2 | L | YL-033, YL-053 | Ekran, Excel ve Ops aynı servisi kullanır, toplamlar testte eşit; bilinmeyen parametre 400; yetkisiz birim 403; en çok 24 ay; yanıtta `generatedAt` + kapsam. |
| YL-135 | Native Excel PivotTable ve tipli ham veri tabloları | reports | YENİ | M12-02 | P2 | M | YL-134, Soru 14 | Excel onarım uyarısız açılır; 3 pivot `refreshOnLoad`; pivot kişi-saat toplamı = Yönetim Özeti; boş sonuçta "Kayıt yok". |
| YL-136 | Planlı bakım tamamlama raporu (sözleşme/dönem bazlı) | reports | YENİ | M12-05 | P2 | M | YL-134, YL-034 | AKYAKA 17 cihaz senaryosunda dönem satırı %88,2 (15/17) Açık; sayım cihaz PB iş emirlerinden; sözleşme tutarı yok. |
| YL-137 | SLA, bekleme ve tekrar arıza raporu (ekran + Excel + CSV) | reports | YENİ | M10-07, M12-03, M12-04 | P2 | M | YL-120…YL-123, YL-134 | 7 zamanında / 2 aşıldı / 1 eksikte uyum %77,8 ve Ölçülemedi:1; yalnız SLA'yı durduran bekleme düşülür; PB ve iptal paydaya girmez; tekrar arıza oranı onaylı işaretten, eski veri "onaysız" ayrı satırda. |
| YL-138 | Önceki dönem karşılaştırması ve 12 aylık trend | reports | YENİ | M12-06 | P3 | M | YL-134 | Fark ±n/±%; boşsa "—"; dönem sonu açık sayısı durum logundan veya "değişebilir" notu. |
| YL-139 | İşten çıkış akışı (önizleme + tek transaction) | personnel | YENİ | M13-03 | P2 | M | YL-006, YL-011 | Personel ve hesap pasif, oturumlar düşer; açık sayaç "İşten çıkış" ile kapanıp incelemeye düşer ama süre kaydı otomatik oluşmaz; açık işler "Yeniden atanacak" listesine. |
| YL-140 | Süreli vekâlet (yalnız operasyonel izinler, ≤30 gün) | accounts | YENİ | M13-04 | P3 | M | YL-009 | Verenin sahip olmadığı izin 403; süre bitiminde yeniden başlatma gerekmeden 403; denetime yazılır. |

---

## 5. Dalga 3 — Kalan eksikler (b) (29 madde)

| ID | Başlık | App | Tür | Kaynak | Ö | E | Bağımlılık | Kabul kriteri |
|---|---|---|---|---|---|---|---|---|
| YL-141 | İş emri temel bilgilerini düzeltme | workorders | EKSİK | M01-08 | P2 | S | YL-025 | Alan bazlı geçmiş; kapalı işte yetkili + gerekçe; birim değişmez; atölye alanları 400; eşzamanlılıkta 409; `edit_basic` izni. |
| YL-142 | Kapsam filtresinin sorguda olması, isteğe bağlı filtre/sayfalama | workorders | EKSİK | M01-17 | P3 | M | YL-071 | Parametresiz çağrı KPI'ları bozmaz. |
| YL-143 | Takvim verisinin tarih aralığıyla yüklenmesi | planning | EKSİK | M02-D03 | P3 | M | YL-032 | Hafta görünümü yalnız o haftayı + açık havuzu yükler; 10.000 iş emrili test verisinde açılış İT eşiği içinde. |
| YL-144 | Kapanan planlı işler takvimde soluk ve salt okunur | planning | EKSİK | M02-D04 | P3 | S | YL-029 | "Planla" düğmesi yok; çakışmaya dahil değil. |
| YL-145 | Cihaz ekle/düzenle/pasife al + kütük değişiklik geçmişi | devices | EKSİK | M03-06, M03-07 | P1 | M | YL-037, YL-015 | Fiziksel silme yok; `00123/A-7` aynen saklanır; aynı tip+marka+seri aktif kayıt gerekçesiz 409 (UNIQUE olmayan normalize indeks); eşzamanlı düzenleme 409; seri değişikliğinde eski/yeni + kullanıcı + zaman; geçmiş düzenlenemez. |
| YL-146 | Sahada düzeltilen seri/bölgenin kütüğe dönmesi ("Sahadan gelen farklar") | devices | HATA | M03-08 | P2 | M | YL-145, YL-148 | Form kapanışında kütük değişmez, fark listede; "Kütüğe uygula" sonrası geçmişte teknisyen + onaylayan; çakışma otomatik uygulanamaz. |
| YL-147 | Tip tekleştirme ve ModelNormalized | devices | VERİ | M03-10 | P2 | M | YL-059 | Model filtresi her iki yazımı getirir; dönüşüm idempotent. |
| YL-148 | Kütük veri kalitesi ekranı ve çakışmasız birleştirme | devices | VERİ | M03-11 | P2 | M | YL-145 | Mükerrer grup sayısı DB sorgusuyla aynı; aynı planda çakışmada birleştirme 409; PB numaraları değişmez. |
| YL-149 | Bakım KPI adım 1 ve 2 | reports | EKSİK | M04-12a, M04-12b | P2 | M | YL-136, YL-084, YL-065 | 10 dönemden 7'si zamanında → uyum %70, 3 geciken listelenir; süre kaydı eksik PB ayrı; uygunsuzluk oranı, en sık 5 madde, aksiyon yaşı, onaysız kapanış (ekran + Excel). |
| YL-150 | Katalogdan bilgi amaçlı parça bildirimi ve depoda bekleyen çıkış listesi | maintenance | EKSİK | M04-11 | P3 | S | YL-129 | Bildirim stoku değiştirmez; çıkış PB'ye bağlı yapılır; teknisyene maliyet yok. |
| YL-151 | Atölye detayında parça ve süre görünümü (salt okunur) | workshop | EKSİK | M05-16 | P2 | M | YL-129, YL-048 | Süre yoksa "Süre kaydı eksik"; mola dahil değil; parça çıkışı düğmesi yalnız `warehouse.manage`'e; maliyet izinsize null. |
| YL-152 | Kiralama aşama düzeltme / gerekçeli geri alma | rentals | EKSİK | M06-D01 | P2 | S | YL-043 | Yalnız son aşama gerekçeyle geri alınır; cihazlar önceki duruma döner; geçmişte görünür. |
| YL-153 | Toplu envanter girişi ve fiziksel sayım | rentals | EKSİK | M06-D02 | P2 | M | YL-042 | Mükerrer seriler reddedilir, diğerleri hareketle yüklenir; sayım eksiği onaysız durum değiştirmez. |
| YL-154 | Teklif e-posta yeniden gönderim, en fazla 3 alıcı, CC, gönderim geçmişi | offers | EKSİK | M07-06b | P2 | S | YL-045 | İkinci gönderim ikinci log; "abc@" 400; SMTP hatasında istisna metni dönmez. |
| YL-155 | Teklif listesi filtreleri, bekleyen teklifler kutusu, süre dolum uyarısı, sunucu filtresi + indeks | offers | EKSİK | M07-08, M07-08b | P2 | S | YL-099 | 2 gün sonra dolacak teklif uyarı verir; filtre DB'de uygulanır; yetkisiz birim API'de yok. |
| YL-156 | Maliyet analizi dönem/birim/iş türü filtresi, özet, CSV ve müşteri kırılımı | costing | EKSİK | M07-11, M07-11b | P2 | M | YL-046, YL-134 | Özet = detay toplamı; CSV `finance.prices.view + reports.export` ister ve eksik veri sütunlarını içerir. |
| YL-157 | "Faturaya iletildi" devir işareti | costing | YENİ | M07-D05 | P3 | S | YL-099 | Kabul teklifli kapanan iş listede, işaretlenince düşer; `accounting.view` yoksa 403. |
| YL-158 | Yetkinlik kataloğu yönetimi; kurs–yetkinlik bağı ve "yeniden değerlendir" listesi | training | EKSİK | M08-10 | P2/P3 | M | YL-047 | Yetkinlik eklenir/pasifleşir; başarılı 90. gün gözlemi şef listesine düşer, seviye kendiliğinden değişmez. |
| YL-159 | 30/60/90 takibinin sunucuda hesaplanması ve uyarı (+ isteğe bağlı sınav eşiği) | training | EKSİK | M08-12, M08-11(c) | P2 | S | YL-047 | Uç ve ekran aynı sayıyı verir; yalnız tamamlanma sonrası iptal edilmemiş gözlem takibi kapatır; sınav eşiği yalnız tanımlı ve onaylıysa uygulanır. |
| YL-160 | Gözlem tarih/aşama doğrulaması, ObserverUserId ve öz-değerlendirme engeli | training | HATA/VERİ | M08-D02, M08-15 | P2 | S | YL-047 | Yarın tarihli gözlem 400; erken/mükerrer aşama `warning` ile kaydedilir; gözlemci = gözlenen ise 400. |
| YL-161 | Sayaç–durum bağı, ilk 5 dk geri alma, kapanışta süre eksik uyarısı | timetracking | EKSİK | M09-09, M09-10, M09-D02 | P2 | S | YL-048, YL-118 | Çözüldü işte başlatma 400; açık sayaçlı işi İptal'e alma 409; 3. dk geri alma kayıt üretmez, 6. dk 400; eksik kayıtlı işi kapatan onay penceresi görür, onay geçmişe not düşer. (Otomatik Planlandı→Sahada, Soru'ya bağlı.) |
| YL-162 | Stok: parça kartı düzenleme/pasifleştirme, tam sayı birimde ondalık reddi, giriş belge no/not, düşük stok uyarı kitlesi, form tabanlı aranabilir ekran | stock | EKSİK | M11-08, M11-16, M11-11, M11-D03, M11-09 | P2 | M | YL-052 | Kod tekrarı 409; pasif parçaya giriş/çıkış/transfer 400; AllowFraction=False birimde 1.5 400; DocumentNo ≤50 / Note ≤500; uyarı yalnız `warehouse.manage`'e; kullanıcı hiçbir işlemde sayısal ID yazmaz. |
| YL-163 | Bakım formu ve atölyede yapılandırılmış parça listesi | stock | EKSİK | M11-13, M11-18 | P2 | M | YL-129 | PB formunda eklenen parça bakiyeden düşer; iş kapanınca eklenemez; eski serbest metin "Not" olarak korunur. |
| YL-164 | Rapor eksik kırılımlar: şef, müşteri, şehir, öncelik, çözüm şekli; personel filtresi tam eşleşme | reports | EKSİK | M12-08 | P2 | M | YL-134, YL-168 | Şef toplamları + "Şef atanmamış" = filtrelenen iş; "Ali Veli" seçimi "Aliye"yi getirmez; boş şehir ayrı satır. |
| YL-165 | Veri Kalitesi sayfası (yalnız listeler) | reports | EKSİK | M12-14 | P2 | M | YL-069, YL-119 | Müşteri varyantları ortak normalizasyonla, süre disiplini YL-119 tanımıyla bulunur. |
| YL-166 | Yeniden açılan iş göstergesi | reports | EKSİK | M12-D03 | P2 | S | YL-134 | Sayı/oran/liste; PB ayrı; tekrar arıza olarak ikinci kez sayılmaz. |
| YL-167 | İş emrinde gerekçeli müşteri/lokasyon düzeltme; atölye firma/seri değişikliğinin iş emri tarihçesine yazılması | workorders, workshop | EKSİK | M14-10, M14-D02 | P2 | S | YL-066 | Gerekçesiz 400; teknisyen 403; PB işinde 400; kapalıda `customers.merge`; değişiklik yoksa satır yok. |
| YL-168 | Teklif/kiralama/atölye müşteri bağları, siteId+birim gruplaması, raporda CustomerId/SiteId, saha önerisinin lokasyon kaydından gelmesi | customers, planning, reports | EKSİK/HATA | M14-05-B, M14-D04, M14-12, M14-14 | P2/P3 | M | YL-068 | İş emrinden açılan teklifte kimlikler aynı; aynı SiteId'li farklı yazımlı işler tek grupta; kimlik doluluk oranı gösterilir; öneri asla cari unvanı adres, kütük ContactName'i irtibat olarak döndürmez. |
| YL-169 | Personel ad senkronu ve yönetici ilişkisinin kimliğe bağlanması | personnel | YENİ/VERİ | M13-01(B), M13-09 | P2/P3 | S | YL-027, org şeması | Ad senkronu kimlikle atama sonrası açılır; ManagerPersonnelId eşleşmeyenleri tahminsiz raporlar; döngü 400. |

---

## 6. Dalga 4 — Üretime hazırlık ve güvenlik sıkılaştırma (a) (12 madde)

**[Pilot öncesi]** işaretli 4 madde Dalga 1 canlıya alınmadan önce yapılır.

| ID | Başlık | App | Tür | Kaynak | Ö | E | Bağımlılık | Kabul kriteri |
|---|---|---|---|---|---|---|---|---|
| YL-170 | **[Pilot öncesi]** Ubuntu 24.04 kurulumu: venv + gunicorn + systemd + nginx, yetkisiz servis kullanıcısı, kilitli bağımlılıklar, yayın ve sağlık döngülü geri dönüş betiği, son N sürüm temizliği | core | OPERASYON | A4-25, A4-11, A4-04 | P1 | M | Dalga 0 | Yayın betiği yedek → migrate → yeniden başlat → sağlık kontrolü sırasıyla çalışır; başarısızsa önceki sürüme `ln -sfn` ile döner; derleme root ile yapılmaz. |
| YL-171 | **[Pilot öncesi]** HTTPS (iç CA veya şirket sertifikası), HTTP→HTTPS yönlendirme, HSTS, `SECURE_*` ayarları, `ALLOWED_HOSTS` ortamdan, nginx varsayılan sitesi kapalı, güvenlik başlıkları + django-csp | core | GÜVENLİK | A1-06, A4-26, A1-18 | P1 | S | YL-170 | Parola hiçbir zaman düz HTTP'den geçmez; `check --deploy` temiz; bilinmeyen Host 400. |
| YL-172 | **[Pilot öncesi]** Yedekleme ve geri yükleme: günlük `pg_dump` (+ isteğe bağlı WAL), 14–30 gün saklama, sunucu dışı kopya, migrate öncesi zorunlu yedek, ek dosya klasörü yedeği, RPO/RTO tanımı, geri yükleme tatbikatı; geçiş günü eski SQL Server'a geri dönüş kartı | core | OPERASYON | A3-06, A4-05, K-7 | P1 | M | YL-170 | Ayrı makinede gerçek geri yükleme en az bir kez kanıtlanır ve aylık tekrarlanır; geri dönüş kartı provası yapılır. |
| YL-173 | **[Pilot öncesi]** Yapılandırılmış loglama + logrotate, anonim `/health` (yalnız ok/fail), yetkili detay ucu (migration durumu, saat farkı, sürüm), nginx üzerinden gerçek Host ile doğrulama, NTP/`timedatectl` | core | OPERASYON | A4-27, A4-10, A1-12, A4-06 | P1 | S | YL-170 | Hata ayrıntısı yalnız logda, istemciye izleme kimliği; eksik migration ve >60 sn saat farkı detay ucunda görünür. |
| YL-174 | Giriş sıkılaştırma: nginx `limit_req`, sistemce üretilen ve 72 saatte dolan geçici şifre, kullanıcı adı zamanlama farkının giderilmesi | accounts | GÜVENLİK | M13-11, A1-05 | P2 | S | YL-007 | Var olmayan/pasif/yanlış kullanıcıda yanıt süresi farkı ölçülemez; geçici şifre 72 sa sonra geçersiz. |
| YL-175 | KVKK: saha irtibat alanlarının rol bazlı gizlenmesi, `reports.personnel` izni, her dışa aktarımın denetim kaydı, saklama politikası, yedek şifreleme | reports, workorders, audit | GÜVENLİK | M02-15, M12-16, A1-15, M14-13 | P2 | M | YL-015, YL-020 | Yetkisiz rolde saha telefonu/yetkilisi null; izinsiz kullanıcıya kişi bazlı süre ve notlar dönmez; her Excel/CSV kullanıcı, zaman, filtreyle denetimde. |
| YL-176 | Rapor ve operasyon sorgularının veritabanında süzülmesi/toplanması + performans testi | reports, operations | PERFORMANS | M12-15, A3-19, A1-20, A4-31 | P2 | M | YL-134 | Rapor sayfası dışında hiçbir ekran tüm süre kayıtlarını indirmez; 5.000 iş / 50.000 süre kaydında overview <1 sn; Meta.indexes tanımlı. |
| YL-177 | Yetki matrisi ve otomatik yetki testlerinin tamamlanması | accounts (testler tüm app'lerde) | GÜVENLİK | M13-14, M07-15, M01-18, A4-09 | P2 | M | YL-009, YL-020 | Her uç × her rol şablonu için beklenen 200/403/404 tablosu testle doğrulanır; fiyat sızıntı senaryoları (Finance 403, stok cost:null, sözleşme ücret null, başka birim 404) geçer. |
| YL-178 | Erişim gözden geçirme listesi | accounts | GÜVENLİK | M13-05 | P3 | S-M | YL-015 | Hassas izin sahipleri, şablon sapmaları, 60+ gün girişsizler, pasif personele bağlı aktif hesaplar; işaret denetimde; yalnız `users.manage`. |
| YL-179 | Stok defteri değiştirilemezliği, depo adı ve maliyet yazma yetkisi; sayaç iptali/başkası adına kayıt yalnız `workorders.assign` | stock, timetracking | GÜVENLİK | M11-19, M09-16 | P3 | S | YL-052, YL-048 | Hareketi güncelleyen/silen kod yok; maliyet yazmak `finance.costs.manage + finance.prices.view`; yalnız `users.manage` ile sayaç iptali 403. |
| YL-180 | SMTP sırları ortam dosyasında, gönderim hız sınırı, gönderilen PDF SHA-256 kaydı | offers, notifications | GÜVENLİK | M07-16, M07-05c, A1-17 | P3 | S | YL-154 | Dağıtılan yapılandırmada parola yok; 1 dakikadaki 11. gönderim 429; her gönderimde PDF hash loga. |
| YL-181 | Dokümantasyon ve İT devri: tek `KURULUM.md`, sürümlü `CHANGELOG`, `.env` şablonu, işletim el kitabı | core | OPERASYON | A4-32 | P2 | S | YL-170…YL-173 | İT, belgeyi izleyerek boş sunucuya kurulumu ve geri yüklemeyi yardım almadan yapar. |

---

## 7. Framework ile karşılananlar ve listeden çıkarılanlar

### 7.1 Django ile karşılanan denetim bulguları (DJANGO_COZER)

Bu bulgular ayrı iş maddesi değildir; doğru yapılandırma ilgili maddenin kabul kriterine yazıldı.

| Bulgu | Konu | Django karşılığı / gerekli yapılandırma | Kabul kriteri yeri |
|---|---|---|---|
| A1-04, A4-01, A2-16, A4-13 | Süresiz, bellek içi oturum | DB tabanlı session; `SESSION_COOKIE_AGE`, boşta kalma ara katmanı; pasifleştirmede oturum silme | YL-006 |
| A1-11 | Zorunlu şifre değişimi sunucuda yok | `AUTH_PASSWORD_VALIDATORS` (min 12), `PasswordChangeForm`, `must_change_password` ara katmanı | YL-007 |
| A1-12, A4-10 | Hata/ortam bilgisi sızıntısı | `DEBUG=False`, özel exception handler, ayrıntısız health | YL-005, YL-173 |
| A1-18 | Güvenlik başlıkları, localStorage belirteci | `SecurityMiddleware`, django-csp, HttpOnly çerez, CSRF | YL-006, YL-171 |
| A1-21, A3-04, A4-04, A2-12 | Başlangıçta SQL betiği, sürümsüz şema | Django migrations (transaction'lı DDL), ayrı DDL rolü, seed ayrı komut | YL-002, YL-022, YL-170 |
| A2-09 | Tek dosya backend | App bazlı modüler yapı, DRF permission sınıfları, pytest | §1, YL-004 |
| A2-10 | Global hata yönetimi yok | Serializer doğrulaması, `IntegrityError`→409 handler, `logging` | YL-005 |
| A3-19, A3-20 | Index eksikleri, isimsiz constraint | FK otomatik index; `Meta.indexes`/`Meta.constraints` açık adlı | YL-176 |
| A4-09 | `Results.Forbid()` → 500 | DRF izin sınıfları JSON 403 | YL-005 |
| A4-24 | Statik dosya sürümü | `ManifestStaticFilesStorage` + index no-cache | YL-021 |

### 7.2 .NET'e özgü olduğu için çıkarılan modül maddeleri (gereksinim taşındı)

| Çıkarılan | Neden .NET'e özgü | Taşınan gereksinim → madde |
|---|---|---|
| M01-12 | Eski istemci KPI filtre farkı | Sayı = liste aynı sunucu filtresinden → YL-028 |
| M01-13 | Eski tekli plan ucu | Kapalı işe plan 400, tarih/süre doğrulaması → YL-029 |
| M01-D01 | Eski atölye güncelleme kodu | Atölye durum değişimi yalnız `transition()` → YL-025, YL-040 |
| M01-D02 | Eski izin dizgileri | Teknisyen close→complete göçü → YL-008, YL-056 |
| M01-15 | Eski detay kayıt akışı | Atomik kayıt, gereksiz durum logu yok → YL-025 |
| M02-14 | Eski `app.js` personel listesi | Personel adı statik dosyada yok → YL-012 |
| M03-01 | Eski seed MERGE | Aktarım yalnız INSERT, düzeltmeleri ezmez → YL-022, YL-059 |
| M03-D03 | Eski sözleşme ucu izni | Sözleşme listesi `maintenance.view` → YL-037 |
| M04-D03 | Eski seed MERGE | Aynı → YL-059 |
| M04-04a | Eski kapanışa gömülü PB üretimi | Üretim ayrı komut, üreten kullanıcı kaydı → YL-034 |
| M05-11, M05-12, M05-13, M05-14 | Eski atölye ucu | Geçmiş yazımı, İptal→İptal, sunucu saati, tek seri → YL-040 |
| M07-D01 | `Results.Forbid()` 500 | Tutarlı JSON 403 → YL-005 |
| M08-16 | Eski overview yükü | Detay alanları ayıklanır → YL-047 |
| M09-15 | Eski bellek içi filtre | DB düzeyi filtre, `/timetracking/me`, indeks → YL-048 |
| M10-D04 | Eski Ops yükü | Rozet COUNT, ack tek UPDATE → YL-124, YL-176 |
| M11-15 | Eski örtük iade | İade yalnız İade türüyle, net çıkışla sınırlı → YL-052 |
| M13-D01 | Eski migration'a gömülü personel seed'i | Tek seferlik depo dışı yükleme → YL-013 |
| M14-07 | Eski bakım formu SQL'i | Location/Description ezilmez → YL-035 |
| M14-D01 | Eski açılış ucu | Müşteri adı doğrulaması → YL-024 |

### 7.3 Reddedilen önemli maddeler

| Kaynak | Reddedilen | Gerekçe |
|---|---|---|
| M12-07 | İş emri bazlı parça kullanımı sayfası | M11-07 ile mükerrer ve yalnız Çıkış saydığı için yanlış; kırılım YL-132'ye not olarak eklendi. |
| M13-13-SecurityStamp | SecurityStamp alanı | Django session auth hash aynı işi görür. |
| M13-03-Kabul3 | İşten çıkışta otomatik süre kaydı | Gerçek bitiş bilinmeden süre üretir; "kayıt yoksa eksik" kararına aykırı. |
| M13-07 | Şef şablonuna `operations.manage` | Şirket geneli SLA'yı değiştirme yetkisi verir. |
| M13-08 | AllUnits bayrağı | Sabit 5 birim; boş listeyi açık listeye çevirmek yeterli. |
| M13-10-Ekran | Ayrı kimlik eşleştirme ekranı | 47 kişi için onaylı Excel tablosu + betik yeterli. |
| M09 (orijinal) | `timetracking.manage/team.view` yeni izinleri, ayrı Veri Disiplini sayfası, ayrı move ucu | Org şeması yokken rol modelini büyütür; `workorders.assign` ve mevcut tablo yeterli. |
| M08 (kısmi) | Genel TrainingChangeLog, sınav eşiğinin zorunlu uygulanması, uç bölme | Sistem geneli denetim tek merkezden (YL-015); "katılım = tamamlandı" bilinçli karar; performans sorunu kanıtlanmadı. |
| M07 (kısmi) | RootOfferId revizyon ağacı, gelir bağlantı tablosu, maliyet sayfalama | Küçük ekip için ağır; ParentOfferId ve Offers.WorkOrderId yeterli. |
| M03 (kısmi) | Ayrı değişiklik talep tablosu, model eşanlam tablosu, elle "Serviste" durumu, `devices.export` izni | Fark listesi, ModelNormalized, hesaplanan durum ve `reports.export` yeterli. |
| M14 (kısmi) | Teknisyene `customers.view`, yedi tabloyu kapsayan eşleştirme ekranı, M14'te KPI'lar | KVKK açısından geniş; Faz 1 Excel tabanlı onay; KPI'lar M10'a devredildi. |

---

## 8. Varsayımlar

1. **Teknoloji:** Python 3.12, Django 5.2 LTS, DRF, PostgreSQL 16 (Ubuntu 24.04 deposu), openpyxl, pytest-django, django-axes, django-csp. PDF için WeasyPrint veya tarayıcıdan yazdırma (lisans Soru 14).
2. **Arayüz:** Django şablonları + hafif JS (HTMX/Alpine; derleme adımı yok), mobil öncelikli; JSON API (DRF) Excel/mobil/ileride entegrasyon için. Ayrı SPA istenirse Dalga 0 iş bölümü değişir (Soru 2).
3. **Arka plan işleri:** Celery yok; yönetim komutu + systemd timer (PB üretimi, bildirim üretimi 5 dk, e-posta outbox).
4. **Tek sunucu, iç ağ**; HTTPS iç CA veya şirket sertifikasıyla.
5. **Eski sistem Dalga 1 kabulüne kadar çalışmaya devam eder**; geçiş "büyük patlama" değil, prova + kesme günüyle yapılır.
6. **Test verisi** kullanıcıdan gelene kadar sentetik fixture kullanılır; gerçek veri depoya girmez.
7. **Organizasyon şeması gelene kadar** Şef/Müdür kapsamı birim bazlıdır; "Ekibim" tanımı sonra.
8. **Varsayılan değerler** (ayarla değiştirilebilir): tekrar arıza penceresi 30 gün (atölye 90), dosya üst sınırı 10 MB, saha oturumu 8 sa boşta / 12 sa mutlak, denetim kaydı saklama 2 yıl, SLA çözüm hedefleri Kritik 12 / Yüksek 24 / Normal 72 / Düşük 120 sa, unutulan sayaç uyarısı 10 sa, manuel geriye kayıt 2 gün, PB gecikme toleransı 30 gün.
9. Müdür'e `operations.manage` ve `finance.costs.manage` verilmesi, Teknisyen/Şef'e `warehouse.view + stock.use` verilmesi **varsayımdır**.
10. Eski 21 ekranın tamamı yeni sistemde karşılanır; eşdeğerlik ölçütü envanter belgesidir (82 uç, 88 kural, 13 çıktı).

---

## 9. Size sorulacak en önemli 15 soru (tekilleştirilmiş)

1. **Dalga sırası:** Dalga 0 (altyapı) ve Dalga 1 (eşdeğerlik) önce, sonra c → b → a sırasını onaylıyor musunuz?
2. **Arayüz:** Django şablonları + hafif JS (önerilen, derleme yok) mi, yoksa ayrı bir SPA (React/Vue) mi?
3. **Eski veri:** Pilot veritabanındaki tüm kayıtlar (iş emri, eğitim, kiralama, stok, süre) taşınacak mı, yoksa bazı modüller sıfırdan mı başlayacak? SQL Server'a salt okunur erişim veya güncel yedek ne zaman sağlanabilir?
4. **Yıl devri:** Dalga 1 1 Ocak 2027'ye yetişmezse eski sistemdeki PB sayacı hatası için geçici önlem alınsın mı (eski koda tek seferlik yama veya elle düzeltme)?
5. **Durumlar:** Teknisyen yalnız "Tamamlandı" mı yapsın, "Kapatıldı"yı şef mi versin? Atölye "Teslim Edildi" iş emrini doğrudan kapatsın mı? "Çözüldü" ve "Düşük" öncelik katalogda kalsın mı? POC durumları çözüm kanalına taşınsın mı?
6. **Hesaplar:** Her teknisyen/stajyerin kendi hesabı ve internetli telefonu olacak mı; atölye tableti/depo gibi ortak hesap olacak mı?
7. **Fiyat görünürlüğü:** Teklif tutarlarını kim görecek (`offers.view` sahipleri mi, yalnız `finance.prices.view` mi)? `users.manage` yalnız Admin ve TS Müdürü'nde mi kalsın? Şefler tamir bedelini görsün mü?
8. **SLA:** Hedef saatler (12/24/72/120) doğru mu; 7/24 mü mesai saatine göre mi; başlangıç anı kayıt açılışı mı müşterinin bildirdiği saat mi; müdahale anı "sahaya vardım" mı?
9. **Planlı bakım:** Hedef tarihler eşit aralıkla mı belirli aylarda mı; kaç gün gecikme "vadesi geçti"; uygunsuzluk bulunan ama bakımı yapılmış cihaz "yapıldı" sayılsın mı; 87 sözleşmeyi kim teyit edecek?
10. **Müşteri onayı ve dosyalar:** Onay hangi iş türlerinde zorunlu, imza mı fotoğraf mı; dosyalar sunucuda mı tutulsun, üst sınır ve KVKK saklama süreleri (dosya, denetim kaydı) nedir?
11. **Planlama:** Şefler sahaya bizzat çıkıyor mu? Çakışmada sistem engellesin mi, gerekçeyle geçişe izin mi versin?
12. **Müşteri ana verisi:** Ekranda cari mi tesis mi önde görünsün; ilk eşleştirmeyi kim yapacak; Muhasebe cari listesi (Excel) ilk kaynak olabilir mi; VKN zorunlu mu?
13. **Stok:** Servis deposu kiralama depolarından ayrı mı; araçlarda sürekli parça stoğu var mı; iç maliyet yöntemi (son alış / ağırlıklı ortalama / sabit); parça talebi akışı isteniyor mu?
14. **Çıktılar:** Excel'de native PivotTable şart mı (kütüphane seçimi buna bağlı); PDF kütüphanesi lisansı İT ile onaylansın mı; kurumsal SMTP bilgisi ne zaman gelir?
15. **İT / sunucu:** HTTPS sertifikası (iç CA mı, şirket alan adı mı), yedeklerin sunucu dışı kopya yeri ve kabul edilebilir veri kaybı (RPO) / kesinti (RTO) süresi nedir?

---

## 10. Kodlama iş bölümü (paralel ajan paketleri)

**Genel kurallar:**
- Her paket **yalnız kendi app klasörüne** yazar. Paylaşılan dosyalar (`settings`, kök `urls.py`, `ui/templates/base.html`, menü kaydı, CI dosyası) yalnız **P0-1**'e aittir; P0-1 tüm app'lerin boş iskeletini, URL include'larını ve menü kayıt mekanizmasını baştan kurar, sonraki paketler bu dosyalara dokunmaz.
- App'ler arası bağımlılık yalnız `services.py` arayüzüyle; arayüz imzaları paket başında dondurulur (`docs/arayuzler.md`). Diğer app'in modeline yazmak yasak.
- İzinler her app'in `permissions.py` dosyasında kaydedilir; aktarım betikleri yalnız `legacy_import/importers/<app>.py` altında, yalnız aktarım paketince yazılır.
- Her paketin ortak "bitti" ölçütü: kabul kriterleri otomatik testle yeşil, CI yeşil, `ruff` temiz, migration'lar çakışmasız, Türkçe arayüz metinleri tamam, ilgili YL maddeleri kapatıldı.

### Dalga 0

| Paket | App(ler) | Maddeler | Sıra | Bitti ölçütü |
|---|---|---|---|---|
| P0-1 İskelet | core, ui, tüm app boş iskeletleri | YL-001…005, 017…019, 021 | **Önce, tek başına** | Özel `User` modeli ilk migration'da; CI yeşil; boş app'ler URL'e bağlı; `/api/meta` ve hata işleyici çalışır; giriş ekranı açılır. |
| P0-2 Yetki | accounts (+ core fiyat mixin) | YL-006…010, 020 | P0-1 sonrası paralel | Yetki yükseltme ve oturum düşürme testleri yeşil; kapsam queryset'i ve fiyat mixin'i diğer paketlere dokümante. |
| P0-3 Personel | personnel | YL-011…013 | P0-2'nin User/Unit modelinden sonra | Bağlama/ayırma ve atanabilir personel uçları testli; yükleme komutu idempotent. |
| P0-4 Müşteri | customers | YL-014 | P0-2 kapsam arayüzünden sonra | CRUD + hızlı ekleme + denetim testli. |
| P0-5 Denetim & dosya | audit, attachments | YL-015, 016 | P0-1 sonrası paralel | Denetim yalnız INSERT (DB yetkisiyle); dosya güvenlik testleri yeşil. |
| P0-6 Aktarım çerçevesi | legacy_import | YL-022, 023 | P0-1 sonrası paralel | Salt okunur bağlantı; profil raporu üretildi ve size sunuldu. |

### Dalga 1

| Paket | App(ler) | Maddeler | Sıra | Bitti ölçütü |
|---|---|---|---|---|
| P1-1 İş emri çekirdeği | workorders | YL-024…028, 039 | **Önce** (`transition()` arayüzü diğerlerini bloke eder) | `transition()`, hold, atama servisleri dondurulmuş arayüzle yayında; KPI kutuları sayı = liste testi yeşil. |
| P1-2 Planlama | planning | YL-029…032, 038 | P1-1 sonrası | Toplu atama/plan ve çakışma testleri yeşil; K-2 senaryosu elle doğrulandı. |
| P1-3 Bakım & kütük | maintenance, devices | YL-034…037 | P1-1 + YL-059 sonrası | Yıl devri (02.01.2027) ve 17 cihaz senaryoları yeşil. |
| P1-4 Atölye | workshop | YL-040, 041 | P1-1 sonrası | Atölye ↔ iş emri senkron testleri yeşil. |
| P1-5 Kiralama | rentals | YL-042…044 | P0 sonrası (bağımsız) | Uçtan uca kiralama testleri yeşil. |
| P1-6 Teklif & maliyet | offers, costing | YL-045, 046 | P1-1 sonrası | 40 kalemli PDF ve fiyat sızıntı testleri yeşil. |
| P1-7 Eğitim | training | YL-047 | P0 sonrası (bağımsız) | Eğitim kabul kriterleri testli. |
| P1-8 Zaman & mobil | timetracking | YL-048…050 | P1-1 atama arayüzünden sonra | Zaman test seti yeşil; 375 px mobil kontrol. |
| P1-9 Operasyon & stok | operations, stock | YL-051, 052 | P1-1 sonrası | Ops sayaçları ve stok eşzamanlılık testleri yeşil. |
| P1-10 Raporlar | reports | YL-033, 053 | P1-1, P1-8 sonrası | K-3 Excel tipli hücre testi; ekran = Excel toplamları. |
| P1-11 Yönetim ekranları | accounts, personnel (yalnız şablon/view dosyaları), rentals/costing'in Depo/Muhasebe görünümleri P1-5/P1-6'ya bırakılır | YL-054 (YL-055 → P1-5/P1-6) | P0 sonrası | Rol şablonu uygulama ve hesap bağlama ekrandan çalışır. |
| P1-12 Veri aktarımı | legacy_import | YL-056…061 | Modeller dondukça kademeli; YL-059 erken (P1-3 bekler) | Prova aktarım raporu, eşleme Excel'leri onayınıza sunuldu; YL-061 karşılaştırma eşit. |

### Dalga 2

| Paket | App(ler) | Maddeler | Bitti ölçütü |
|---|---|---|---|
| P2-1 İş emri yenilikleri | workorders | YL-062…066, 070, 071 | Kapanış formu, onay, servis formu çıktısı testli. |
| P2-2 Müşteri | customers (+ importers/customers.py) | YL-067…069 | Eşleştirme Faz 1 onaylı aktarımı tamam. |
| P2-3 Planlama | planning, personnel (yalnız müsaitlik modeli) | YL-072…076 | Erteleme/geri alma ve bulk-replan testli. |
| P2-4 Kütük & bakım | devices, maintenance | YL-078…085 | Sözleşme yönetimi ve hedef tarih önizlemesi testli. |
| P2-5 Atölye | workshop | YL-086…091 | Teşhis/onay/teslim kuralları testli. |
| P2-6 Kiralama | rentals | YL-092…097 | Müsaitlik çakışma testleri yeşil. |
| P2-7 Teklif & maliyet | offers, costing | YL-099…104 | Onay akışı, revizyon, gelir aktarımı testli. |
| P2-8 Eğitim | training | YL-106…110, 112 | İSG faaliyet ve belge geçerliliği testli. |
| P2-9 Zaman & mobil | timetracking | YL-113…118 | Mobil akış 375 px'te elle + otomatik testli. |
| P2-10 Operasyon & bildirim | operations, notifications, legacy_import/importers/sla.py | YL-120…128 | SLA takvim testleri (≥6 senaryo) ve rozet performansı geçer. |
| P2-11 Stok | stock | YL-129…131, 133 | Parça kullanımı/iade eşzamanlılık testleri yeşil. |
| P2-12 Raporlar | reports | YL-077, 098, 105, 111, 119, 132, 134…138 | Rapor motoru: ekran = Excel = Ops toplamları. |
| P2-13 Hesap yaşam döngüsü | accounts, personnel | YL-139, 140 | İşten çıkış ve vekâlet testli. |

### Dalga 3

| Paket | App(ler) | Maddeler |
|---|---|---|
| P3-1 İş emri & müşteri | workorders, customers | YL-141, 142, 167, 168 (customers/planning kısmı) |
| P3-2 Planlama | planning | YL-143, 144 |
| P3-3 Kütük | devices | YL-145…148 |
| P3-4 Bakım & atölye | maintenance, workshop | YL-150, 151 |
| P3-5 Kiralama | rentals | YL-152, 153 |
| P3-6 Teklif & maliyet | offers, costing | YL-154…157 |
| P3-7 Eğitim | training | YL-158…160 |
| P3-8 Zaman | timetracking | YL-161 |
| P3-9 Stok | stock | YL-162, 163 |
| P3-10 Raporlar | reports | YL-149, 164…166 |
| P3-11 Personel | personnel | YL-169 |

Bitti ölçütü (her paket): kabul kriterleri testli, CI yeşil, kullanıcı test verisiyle kısa kabul turu.

### Dalga 4

| Paket | Kapsam | Maddeler | Bitti ölçütü |
|---|---|---|---|
| P4-1 Sunucu & yayın **[Pilot öncesi]** | deploy/ klasörü, nginx, systemd, betikler | YL-170…173, 181 | Boş Ubuntu 24.04'e belgeyle kurulum, HTTPS, yedek + geri yükleme tatbikatı kanıtlandı. |
| P4-2 Güvenlik sıkılaştırma | accounts, audit, reports, workorders (yalnız serializer/izin dosyaları) | YL-174, 175, 177, 178 | Yetki matrisi testleri tüm uçlarda yeşil. |
| P4-3 Performans & küçük sıkılaştırmalar | reports, operations, stock, timetracking, offers, notifications | YL-176, 179, 180 | 5.000 iş / 50.000 süre kaydında hedef süreler tutar. |

---

*Bu liste, 14 modül tasarım/denetim belgesi, A1–A4 denetim raporları ve eski sistem işlev envanterinden sentezlenmiştir. Ayrıntılı gerekçeler için ilgili kaynak ID'lerin belgelerine bakınız: `analiz\02_moduller\`, `analiz\01_denetim\`, `analiz\05_ESKI_SISTEM_ISLEV_ENVANTERI.md`.*
