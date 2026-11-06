# DengeERP V1.20.1 — Rol / Yetki / Modül Envanteri (orkestratör ön taraması)

Kaynak: `kaynak/V1_20_1_orijinal/DengeERP.Api/` — `Program.cs` (3.937 satır, tek dosya minimal API), `OpsSuite.cs` (V1.20 operasyon uçları), `wwwroot/app.js` (~238 KB tek dosya SPA), `wwwroot/ops120.js`, `Database/*.sql` (11 script, başlangıçta alfabetik sırayla uygulanıyor).

## Kullanıcı modeli
- Tablo `dbo.ErpUsers`: Username, PasswordHash/Salt (PBKDF2-SHA256 120k), FullName, RoleName, `AllowedUnits` (pipe ile ayrılmış metin), `Permissions` (pipe metin, `*` = tümü), IsActive, MustChangePassword.
- `dbo.Personnel`: FullName, DepartmentName, AdditionalDepartments, Title, UnitCode, ManagerName, StartDate, IsActive, ErpUserId. Personel ↔ kullanıcı bağlantısı isteğe bağlı.
- Teknisyen/şef atamaları (`WorkOrderAssignments`, `AssignmentRequest(Chief, Technicians)`) **isim metni** ile tutuluyor; kullanıcı/personel kimliğine bağlı değil.
- Müşteri ana tablosu yok: `CustomerName`, `Location`, `ProjectName` iş emri/kiralama/teklif tablolarında serbest metin.

## Birimler (Catalog.AllUnits)
Güvenlik Sistemleri, Haberleşme, POC, Mobilite, Araç Takip. `AllowedUnits` boşsa kullanıcı **tüm birimleri** görür.

## Roller (Catalog.RoleDefaults) — rol yalnızca varsayılan izin şablonu; kişi bazında izin değiştirilebilir
| Rol | Öne çıkan izinler |
|---|---|
| Admin | `*` |
| Üst Yönetim | neredeyse tümü + users.manage + finance.prices.view |
| Teknik Servis Müdürü | Üst Yönetim ile aynı |
| Teknik Servis Müdür Yardımcısı | Üst Yönetim ile aynı (users.manage dahil) |
| Genel Koordinatör | görüntüleme + offers.approve + rapor export |
| Operasyon Uzmanı | iş kaydı açma, teklif oluşturma, kiralama açma, görüntüleme |
| Şef | iş düzenleme/atama/planlama/kapama, bakım yönetimi, atölye, saha gözlemi |
| Teknisyen | iş görüntüleme/düzenleme/kapama, cihaz görüntüleme, atölye yönetimi |
| Muhasebe | görüntüleme, offers.approve, rapor export, accounting.view |
| Depo | görüntüleme, warehouse.view, rentals.view |
| Kiralama Operasyon | kiralama CRUD, teklif oluşturma |
| İnsan Kaynakları | personel yönetimi, eğitim yönetimi, **users.manage** |

## İzin kataloğu (34 anahtar)
dashboard.view · workorders.view/create/edit/assign/plan/close · offers.view/create/approve/send · reports.view/export · training.view/manage/observe/export · users.manage · warehouse.view/manage · operations.manage · finance.costs.manage · finance.prices.view · accounting.view · rentals.view/create/edit · personnel.view/manage · devices.view · maintenance.view/manage · workshop.view/manage

## Departmanlar (Catalog.Departments, 19 adet)
Üst Yönetim, Genel Koordinatörlük, Teknik Servis, Güvenlik Sistemleri Teknik Servis, Depo & Lojistik, Müşteri İlişkileri & Kurumsal İletişim, Satış Yönetimi, Güvenlik Satış, Haberleşme Sistemleri Satış, Denge Mobil, Haberleşme Sistemleri Teknik Servis Yönetimi, Haberleşme Sistemleri Teknik Servis, İnsan Kaynakları, Muhasebe & Finans GMY, GMY, İdari İşler, Kiralama & Satış Yönetimi, Kiralama & Operasyon Yönetimi, Muhasebe Yönetimi.

## API uç noktaları (≈80) — modül eşlemesi
- Auth: /api/auth/login, me, logout, change-password; /api/meta/permissions; /api/health
- Kullanıcı: /api/users (GET/POST/PUT/status/reset-password)
- İş emirleri: /api/workorders (+serials, status, assignments, bulk-assign, bulk-plan, plan, site-suggestion, history)
- Teklif: /api/offers (+status, pdf, send)
- Kiralama/depo: /api/rentals (+catalog, details, composition, inventory, warehouses, allocate, stage)
- Eğitim: /api/training/* (overview, courses, plans/bulk, sessions, attendance, competencies, observations, export.csv)
- Personel: /api/personnel (+status)
- Zaman: /api/timetracking/*, /api/workorders/{id}/live-timer/*, time-logs
- Rapor: /api/reports/worklogs, /api/reports/workorders.xlsx
- Cihaz/bakım: /api/security/devices, /api/maintenance/* (contracts, generate-due, plans/devices, workorders/{id}/form)
- Atölye: /api/workshop/tickets
- Operasyon (OpsSuite.cs): /api/ops/overview, alerts/ack, sla/{priority}, workorders/{id}/hold|release, stock, stock/part, stock/movement, finance, finance/rate, finance/{id}, export.csv

## Orkestratörün ilk gözlemleri (doğrulanmalı)
1. Oturumlar bellek içi `ConcurrentDictionary`; **süre sonu yok**, servis yeniden başlayınca hepsi düşer, çoklu sunucuda çalışmaz.
2. `users.manage` sahibi kendine/başkasına `*` (Admin) verebilir; İK ve Müdür Yardımcısı da bu izne sahip → yetki yükseltme riski.
3. Login'de deneme sınırı / kilitleme yok; denetim (audit) kaydı yok (kullanıcı/yetki değişikliği loglanmıyor).
4. `/api/health` anonim ve SQL hata mesajını (`ex.Message`) döndürüyor.
5. `AllowedUnits` boş = tüm birimler (güvensiz varsayılan).
6. Şef/teknisyen atamaları isim metni; “teknisyen yalnızca kendi işini görür” gibi kurallar kimlik üzerinden uygulanamıyor olabilir.
7. Müşteri/lokasyon/sözleşme ana verisi yok; serbest metin → tekilleştirme ve raporlama sorunu.
8. Tüm backend tek `Program.cs` dosyasında; test projesi yok.
