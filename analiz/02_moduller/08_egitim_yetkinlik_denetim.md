# M08 — Eğitim, Yetkinlik ve Personel Gelişimi — Bağımsız Denetim

> **Tarih:** 21 Ekim 2026 · **Denetlenen:** `02_moduller/08_egitim_yetkinlik_tasarim.md` (M08-01 … M08-17)
> **Yöntem:** Her maddenin "mevcut durum" iddiası kaynak kodda satır satır okundu (salt okunur; koda dokunulmadı).
> **Kısaltmalar:** `P.cs` = Program.cs, `Ops.cs` = OpsSuite.cs, `app.js` = wwwroot/app.js, `V113.sql` = Database/ZZ_V113_TrainingDevelopment.sql, `CL113` = CHANGELOG_PILOT_V1_13.txt
> **Öncelik tanımı:** P1 = iş akışını bloke eden / veri doğruluğunu bozan · P2 = operasyonel kalite · P3 = sonra.

---

## 1. Genel değerlendirme

Tasarım raporu **büyük ölçüde doğru** ve kodla tutarlı. Kontrol edilen 25+ satır referansının tamamı doğru yeri gösteriyor. Uydurma veya "zaten var olan şeyi yeni diye sunma" durumu bulunmadı. Ancak aşağıdaki düzeltmeler gerekli:

1. **M08-11'in "sınav eşiği" kısmı hata değil, tasarım kararı.** CL113:42-43 açıkça şunu söylüyor: "Eğitim planı 'Tamamlandı' durumu katılımla işlenir; saha gelişimi ayrı puanlanır." Arayüzde de seçenek "Katıldı (tamamlandı)" olarak etiketli (app.js:1360). Bu yüzden sınav eşiği **isteğe bağlı yeni özellik** olmalı (P3). İleri tarih ve yıl uyumsuzluğu ise gerçek hata (P1).
2. **Bağımlılıklarda döngü var.** M08-01 M08-13'e, M08-13 de M08-01'e bağlı. Doğru sıra: M08-13 → M08-01.
3. **Aynı alan iki maddede tanımlanmış.** `ObserverUserId` hem M08-02'de hem M08-15'te. Tek sahip M08-15 olmalı.
4. **Aşırı mühendislik var.** M08-09'daki alan bazlı genel `TrainingChangeLog`, M08-16'daki uç bölme/sayfalama ve M08-04'teki ad eşleşmesine dayalı atama kontrolü, bugünkü ölçekte (5 birim, onlarca teknisyen) ve kimlik bazlı atama gelmeden fazla yük getiriyor.
5. **Bir bulgu eksik kalmış.** Gözlem formunda tüm maddelerin varsayılanı "Gözlenmedi"dir (-1), kritik maddeler de dahil (`trainingChecks`, app.js:1363). Kullanıcı kritik maddeye hiç dokunmadan gözlemi kaydedebilir. Bu, M08-13'ü güçlendiriyor ve P1 yapıyor.
6. **CL113:17 ile gerçek davranış uyuşmuyor.** Changelog "Kritik maddedeki 'uygun değil' ayrıca uyarı üretir" diyor. Gerçekte yalnızca istemcide `confirm()` var (app.js:1433), sunucu uyarısı yok. Bu durum M08-01 ve M08-13'ün gerekçesini doğruluyor.
7. **KRİTİK etiketi:** Tasarımcıya katılıyorum. Bu modülde sistem dışına sızıntı ya da geri dönüşsüz büyük veri kaybı yaratan **KRİTİK** bir açık yok. M08-08'deki üzerine yazma, kalıcı tarihsel veri kaybıdır ve P1'dir.

---

## 2. Madde bazlı kararlar

| ID | Karar | Öncelik | Kısa gerekçe |
|---|---|---|---|
| M08-01 | DEĞİŞTİR | P2 | Gerekli (§5.8, CL113:17), ancak akış sadeleştirilmeli. Döngüsel bağımlılık giderilmeli. |
| M08-02 | DEĞİŞTİR | P2 | İş emri birim kontrolü eksikliği gerçek. Ad eşleşmesiyle atama uyarısı ise M01-10'a ertelenmeli. |
| M08-03 | DEĞİŞTİR | P2 | Bilinen boşluk (CL113:40-41). Plan önerisi kısmı P3'e taşınmalı. Belge listesi kullanıcıdan bekleniyor. |
| M08-04 | DEĞİŞTİR | P3 | Değerli, ancak kimlik bazlı atama, belge ve geçmiş maddelerine bağımlı. Eşleme verisi de yok. |
| M08-05 | KABUL | P2 | Teknisyenin hiç eğitim izni yok (P.cs:3930). `ErpUserId` mevcut. Efor S değil, M olmalı. |
| M08-06 | KABUL | P2 | Katılım ucu tek kişilik (P.cs:1612). Operasyonel yük gerçek. |
| M08-07 | DEĞİŞTİR | P2 | Ana iş sorusunu cevaplıyor, ancak tek seferde 6 sayfalık Excel fazla. Aşamalı yapılmalı. |
| M08-08 | KABUL | P1 | MERGE ile üzerine yazma doğrulandı (P.cs:1655-1659, V113.sql:104). Kalıcı veri kaybı. |
| M08-09 | DEĞİŞTİR | P1 | Düzeltme ve iptal ucu yok (doğrulandı). Genel değişiklik günlüğü yerine hafif çözüm. Katılım düzeltmesi zaten var. |
| M08-10 | DEĞİŞTİR | P2 / P3 | Katalog yönetimi P2. Kurs-yetkinlik bağı ve "yeniden değerlendir" görevi P3. |
| M08-11 | DEĞİŞTİR | P1 | İleri tarih ve yıl uyumsuzluğu gerçek hata. Sınav eşiği tasarım kararı değişikliği (P3, isteğe bağlı). |
| M08-12 | KABUL | P2 | Takip yalnızca istemcide hesaplanıyor (app.js:1293-1305). Ops uyarısında yok. |
| M08-13 | DEĞİŞTİR | P1 | §5.8'in doğrudan ihlali. Ayrıca kritik madde varsayılanı "Gözlenmedi". Bağımlılık döngüsü kırılmalı. Rozet kısmen zaten var. |
| M08-14 | KABUL | P2 | Oturum ucunda birim ve aktiflik kontrolü yok (doğrulandı). |
| M08-15 | DEĞİŞTİR | P2 | Öz-değerlendirme engeli geçerli. Ad "spoof" riski yok (sunucu `user.FullName` yazıyor). M08-02 bağımlılığı kaldırılmalı. |
| M08-16 | DEĞİŞTİR | P3 | Bugünkü ölçekte performans sorunu kanıtlanmadı. Yalnızca alan ayıklama ve yıl sınırı yapılmalı. |
| M08-17 | DEĞİŞTİR | P2 | Gerekli (en az yetki ilkesi, KVKK). M08-16 bağımlılığı gereksiz. Rol dağılımı varsayım. |

Ayrıntılı gerekçeler ve düzeltilmiş tanımlar aşağıda.

### M08-01 · DEĞİŞTİR · P2 — Kritik İSG düzeltici faaliyet
- **Doğrulama:** P.cs:1690 yalnızca `critical` bayrağını hesaplıyor. Ops.cs:50-63 eğitim için yalnızca plan vadesine bakıyor. app.js:1433'te sadece `confirm()` var. İddialar doğru.
- **Sorunlar:**
  - (a) Bağımlılık döngüsü var (M08-13 ↔ M08-01).
  - (b) Tasarımda hem "yeni başarılı gözlemle otomatik kapanış" hem "Müdür kapanış onayı" var. Bu ikisi çelişiyor.
  - (c) Faaliyetin kriter bazında mı, gözlem bazında mı açılacağı belirsiz.
- **Düzeltilmiş tanım:**
  - Kritik maddede 0 alan her gözlem için **gözlem başına tek** düzeltici faaliyet açılır. Kritik kriterler alt liste olarak tutulur.
  - Varsayılan sorumlu: gözlemi yapan kullanıcı. Termin varsayılanı yapılandırılabilir (öneri 14 gün; kullanıcı onayı bekleniyor).
  - **Otomatik kapanış:** Aynı personel ve aynı kurs için, ilgili tüm kritik maddeleri "Uygun (2)" olan yeni bir gözlem girilir.
  - **Manuel kapanış:** Yalnızca `training.manage` yetkisiyle ve zorunlu kanıt metniyle yapılır.
  - Açık faaliyetler Ops uyarısına "Uyarı" olarak düşer. Termini geçenler "Kritik" seviyesine çıkar. Uyarılar birim kapsamına göre süzülür.
- **Kabul kriterleri:** Tasarımdaki 1-5 geçerli. Ek olarak (6): manuel kapanışta kanıt metni boşsa 400 döner.
- **Bağımlılık:** M08-13.

### M08-02 · DEĞİŞTİR · P2 — İş emrinden gözlem
- **Doğrulama:** app.js:1372'de `state.workOrders.slice(0,400)` var. P.cs:1695 yalnızca FK kontrolü yapıyor; iş emrinin birimi kontrol edilmiyor. Doğru.
- **Sorunlar:**
  - "Personel o işe atanmış mı" kontrolü, atamalar isim metni olduğu için güvenilmez (envanter #6). `OutsideAssignment` bayrağı yanlış pozitif üretir.
  - `ObserverUserId` M08-15 ile çakışıyor.
- **Düzeltilmiş tanım:**
  - (1) Sunucu, gözleme bağlanan `WorkOrderId` için iş emrinin `UnitCode`'una `UnitAllowed` kontrolü uygular. Yetkisizse 403 döner. Bu küçük ama gerçek bir doğrulama açığıdır.
  - (2) İş emri detayında "Saha Gözlemi Yap" düğmesi bulunur (`training.observe`). Form, iş emri ve birim kilitli olarak açılır.
  - (3) İş emri detayında bağlı gözlemler listelenir.
  - (4) Gözlem formunda iş emri, sunucu aramasıyla seçilir.
  - Atama dışı uyarısı ve `OutsideAssignment` bayrağı **M01-10 tamamlandıktan sonra** eklenir. `ObserverUserId` M08-15'e taşınır.

### M08-03 · DEĞİŞTİR · P2 — Belge geçerliliği
- **Doğrulama:** `TrainingCourses` tablosunda periyot alanı yok, belge tablosu yok. CL113:40-41 "resmi İSG sertifika mevzuat takibi henüz yok, yasal eğitim periyotları ayrı yönetilmelidir" diyor. Bu bilinen bir boşluk.
- **Düzeltilmiş tanım:**
  - Kapsam: `RenewalMonths` alanı, `PersonnelCertificates` tablosu (dosya yükleme yok, yalnızca üst veri), geçerlilik bitişi hesabı, süresi dolan ve 30 gün içinde dolacak belgelerin listesi, Ops uyarısı.
  - "Sonraki yıl planı önerisi ve toplu plan" P3'e taşınır. Mevcut toplu plan ekranı zaten mükerrer kayıt üretmiyor.
  - Belge türleri ve periyotlar kullanıcı veya İSG uzmanı tarafından verilecek. Liste gelene kadar tablo boş kalır ve sistem uyarı üretmez.

### M08-04 · DEĞİŞTİR · P3 — Atamada yetkinlik uyarısı
- **Doğrulama:** Atama uçları yetkinliğe bakmıyor ve isimle çalışıyor. Doğru.
- **Sorunlar:**
  - Üç maddeye (M01-10, M08-03, M08-08) ve kullanıcının dolduracağı eşleme verisine bağlı. İsim metniyle personel eşlemesi hatalı uyarılar üretir.
  - Açıklamadaki "toplu plana atama" ifadesi konu dışı.
- **Düzeltilmiş tanım:**
  - Yalnızca iş emrine teknisyen atamasında uyarı verilir, engelleme yapılmaz.
  - Eşleme anahtarı olarak mevcut `WorkTypeRules(UnitCode, WorkType)` (DengeERP_Update.sql:103-111) yeniden kullanılır.
  - M01-10 (kimlik bazlı atama) bitmeden başlanmaz. Eşleme tablosu boşsa hiçbir uyarı üretilmez.
  - Efor: M-L.

### M08-05 · KABUL · P2 — Gelişim Kartım
- **Doğrulama:** Teknisyen rolünde `training.*` izni yok (P.cs:3930). `Personnel.ErpUserId` var (DengeERP_Update.sql:362, 366). Otomatik bağlama yalnızca ad eşleşmesiyle yapılıyor (DengeERP_Update.sql:429-432). Bağlantı kalitesi pilotta kontrol edilmeli.
- **Not:** Efor S değil **M** (yeni uç, onay ucu, yeni izin, yeni ekran). Onay ucu sahiplik kontrolü yapmalı: yalnızca `Personnel.ErpUserId = user.UserId` olan kayıt onaylanabilir. Rol varsayılanı bir varsayımdır.

### M08-06 · KABUL · P2 — Toplu katılım
- **Doğrulama:** Uç tek kişilik (P.cs:1612), form da tek kişilik (app.js:1360).
- **Not:** Tamamlama kuralı M08-11 ile aynı olmalı. Mevcut tek kişilik uç korunmalı.

### M08-07 · DEĞİŞTİR · P2 — Etkinlik raporu ve Excel
- **Doğrulama:** Yalnızca plan CSV'si var (P.cs:1712-1731). Kodda bir xlsx üreticisi zaten mevcut (P.cs:2191, `ZipArchive` P.cs:3712). Ek kütüphane gerekmez.
- **Notlar:** Oturum bazında ön/son ortalama ekranda zaten gösteriliyor (app.js:1361). Kabul kriteri (1)'in sınav kısmı kısmen mevcut.
- **Düzeltilmiş tanım (aşama 1):**
  - Ekranda kurs × birim bazında: 0/30/60/90 gözlem başarı oranı ve ortalama, 0. gün ile 90. gün arasındaki fark, kritik sayısı, takip uyumu. Veri yoksa "veri yok" yazılır.
  - xlsx dosyasında iki sayfa olur: "Plan" ve "Gözlemler".
- **Aşama 2:** Yetkinlik, Düzeltici Faaliyet ve Belgeler sayfaları, ilgili maddeler (M08-08, M08-01, M08-03) bittikçe eklenir.
- **Kabul kriterleri:** Tasarımdaki 1-5 geçerli.

### M08-08 · KABUL · P1 — Yetkinlik geçmişi
- **Doğrulama:** MERGE ile üzerine yazma (P.cs:1655-1659) ve tekil kısıt (V113.sql:104) doğrulandı. `AssessedBy` ad metni (P.cs:1662).
- **Ek notlar:**
  - Göç scripti mevcut başlangıç düzenine uymalı (Database/*.sql alfabetik ve idempotent).
  - Aynı uçta `CompetencyCatalog.UnitCode` kapsam kontrolü de eklenmeli (bkz. M08-D03).

### M08-09 · DEĞİŞTİR · P1 — Düzeltme ve iptal
- **Doğrulama:** Yalnızca POST uçları var. `IsActive` kurs alanı mevcut ama değiştiren bir uç yok. Doğru.
- **Düzeltme:** Katılım ve puan düzeltmesi **zaten mümkün**: aynı oturum ve kişi için tekrar gönderim MERGE ile güncelleniyor (P.cs:1626-1631).
- **Aşırı mühendislik:** Alan bazlı genel `TrainingChangeLog` gereksiz. Sistem genelinde denetim (audit) altyapısı yok (envanter #3). Bu ihtiyaç (a) grubunda tek merkezden çözülmeli.
- **Düzeltilmiş tanım:**
  - **P1:** Gözlemin gerekçeli soft iptali (`IsCancelled`, `CancelReason`, `CancelledByUserId`, `CancelledAt`). Planın erteleme ve iptali (`Status`, `StatusReason`, `UpdatedByUserId`, `UpdatedAt`; eski hedef tarih `PreviousDueDate` alanında saklanır). Kursun ve kriterin pasife alınması.
  - **P2:** Kurs metin alanlarının ve oturumun düzenlenmesi.
  - Plan ve gözlem iptalleri Ops uyarısı ile 30/60/90 hesabından düşer (bkz. M08-D01).
  - Genel değişiklik günlüğü, sistem geneli denetim maddesine bırakılır.

### M08-10 · DEĞİŞTİR · P2 (katalog) / P3 (bağlantı ve görev)
- **Doğrulama:** `CompetencyCatalog` için uç yok, yalnızca tohum verisi var. Doğru.
- **Düzeltilmiş tanım:**
  - **P2:** Yetkinlik ekleme, düzenleme ve pasife alma (`training.manage`).
  - **P3:** `TrainingCourseCompetencies` bağlantısı ve 90. gün sonrası "yeniden değerlendir" listesi.

### M08-11 · DEĞİŞTİR · P1 — Plan tamamlama kuralları
- **Doğrulama:** P.cs:1601 oturum tarihini kontrol etmiyor. P.cs:1642'deki `pl.PlanYear=YEAR(s.SessionDate)` koşulu yüzünden geç tamamlanan plan kapanmıyor. Gerçek hata.
- **Düzeltme:** İleri tarihli oturumda plan "bugünden" değil, `CompletedAt` = gelecek tarih olarak kapanıyor. KPI'da yine "tamamlandı" sayıldığı için sonuç aynı ölçüde yanlış.
- **Sınav eşiği:** Hata değil. CL113:42-43 ve app.js:1360'a göre bilinçli bir tasarım kararı.
- **Düzeltilmiş tanım:**
  - **P1-a:** Gerçekleşen oturum tarihi bugünden ileri olamaz. İstek 400 döner.
  - **P1-b:** Katılım, aynı kişi ve kurs için `PlanYear <= YEAR(SessionDate)` olan **en eski açık** planı tamamlar. Gelecek yılın planını kapatmaz. Hedef tarih geçmişse "geç" sayılır.
  - **P3-c (isteğe bağlı):** Kursa `ExamPassScore` alanı eklenir. Tanımlıysa ve son puan eşiğin altındaysa plan "Başarısız-Tekrar" olur. Tanımsızsa mevcut davranış sürer. Kullanıcı onayı gerekir (tasarım §4-4).
  - Gözlem sonucunun sunucuda hesaplanması M08-13'e taşınır.

### M08-12 · KABUL · P2 — 30/60/90 sunucu ve uyarı
- **Doğrulama:** Hesap istemcide yapılıyor (app.js:1293-1305). Ops.cs:50-63 bu takibi içermiyor. Doğru.
- **Ek not:** Aynı kişi ve kurs için kurs bir sonraki yıl tekrar alınırsa, önceki yılın gözlemi yeni takibi "yapıldı" sayıyor (app.js:1300'de plan veya tarih eşlemesi yok). Sunucu hesabında gözlem tarihi, plan tamamlanma tarihinden sonra olmalı. M08-D01 ile birlikte yapılmalı.

### M08-13 · DEĞİŞTİR · P1 — Kritik uygunsuzluk ortalamada kayboluyor
- **Doğrulama:**
  - app.js:1310 ve 1318 düz ortalama hesaplıyor.
  - P.cs:1673 yalnızca "hepsi -1" durumunu reddediyor.
  - **Ek bulgu:** Kritik dahil tüm maddelerin varsayılanı "Gözlenmedi" (app.js:1363). Kritik maddeye dokunmadan kayıt yapılabiliyor.
  - Rozet kısmen mevcut: `trainingScoreLabel` kritikte kırmızı rozet ve "· Kritik" eki gösteriyor (app.js:1291). Kabul kriteri (3) yalnızca küçük bir iyileştirmedir.
- **Düzeltilmiş tanım:**
  - Sunucu her gözlem için `Result` alanını hesaplar ve saklar:
    - **Kritik:** Kritik maddelerden biri 0.
    - **Eksik Gözlem:** Kritik madde -1 ve gerekçe girilmiş.
    - **Başarılı:** Puan ≥ kurs eşiği (tanımsızsa 85; bugünkü yeşil rozet eşiği). Kritik yok.
    - **Gelişim Gerekli:** Diğer durumlar.
  - Kritik madde -1 ise gerekçe zorunludur; gerekçe yoksa 400 döner.
  - Özet KPI başarı oranı olur. Ortalama ikincil bilgi olarak kalır. Kritik sayısı ayrı bir kutuda gösterilir.
  - **Bağımlılık:** Yok. M08-01 bu maddeye bağlıdır.

### M08-14 · KABUL · P2 — Oturumda birim kontrolü
- **Doğrulama:** P.cs:1598-1610'da kontrol yok. P.cs:1577-1580'de aynı kontrol var. Doğru.
- **Ek:** Aynı uçta `IsActive=1` kurs kontrolü de eklenmeli; pasif kursa oturum açılabiliyor.
- **Not:** KRİTİK değil. Etki, `training.manage` sahibi birim kısıtlı kullanıcılarla sınırlı.

### M08-15 · DEĞİŞTİR · P2 — Gözlemci kimliği ve öz-değerlendirme
- **Doğrulama:** `ObserverName` ve `AssessedBy` ad metni (V113.sql:100, 116). Ancak değer istemciden değil, sunucudan (`user.FullName`, P.cs:1662, 1696) geliyor. "Sahte gözlemci adı" riski yok. Gerekçe "ad değişikliği ve eşadlılık" olarak daraltılmalı.
- **Düzeltilmiş tanım:**
  - `TrainingObservations.ObserverUserId` alanının tek sahibi bu maddedir.
  - Gözlemcinin `Personnel.ErpUserId` bağlantısı gözlenen kişiyse gözlem 400 döner. Aynı kural yetkinlik değerlendirmesinde de uygulanır.
  - **Bağımlılık:** Yalnızca M08-08 (`AssessedByUserId`).

### M08-16 · DEĞİŞTİR · P3 — Overview yükü
- **Doğrulama:** Overview tek uç ve sayfalama yok. Ancak gerekçedeki "tüm yılların verisi" ifadesi abartılı:
  - Gözlemler Yıl-1..Yıl+1 aralığında (P.cs:1533).
  - Oturum ve katılım yalnızca seçili yılda.
  - Yalnızca `levels` kayıtları tüm zamanları kapsıyor.
- **Değerlendirme:** Bu ölçekte (yaklaşık onlarca teknisyen) performans sorunu kanıtlanmadı. Sekme bazlı uçlara bölmek SPA'da gereksiz bir yeniden yazım olur.
- **Düzeltilmiş tanım:**
  - Detay alanlarının ayıklanması M08-17 kapsamında yapılır.
  - Uç bölme ve sayfalama, ölçülen bir yavaşlık (örneğin overview > 2 sn veya > 1 MB) görülürse yapılır.

### M08-17 · DEĞİŞTİR · P2 — Kişisel performans verisinin ayrıştırılması (KVKK)
- **Doğrulama:** P.cs:1530-1534 `notes`, `actionPlan`, `evidence` alanlarını döndürüyor. P.cs:3927 Genel Koordinatör'e `training.view` veriyor. Doğru.
- **Düzeltilmiş tanım:**
  - Mevcut overview ucunda, `training.view_detail` izni yoksa bu alanlar **sunucuda null/yok** olarak döner.
  - Kişi kartı ve gözlem listesi bu durumda yalnızca puan, sonuç ve tarihi gösterir.
  - **Bağımlılık:** M08-16 gerekmez.
  - Rol dağılımı varsayımdır; organizasyon şeması gelince doğrulanacak.
  - KRİTİK değil (sızıntı yetkili iç kullanıcılarla sınırlı).
- **Not:** İK rolünde `users.manage` var. İK kendine `view_detail` verebilir. Bu genel yetki yükseltme konusudur (envanter #2) ve bu modülün kapsamında değildir.

---

## 3. Tasarımcının kaçırdığı maddeler

### M08-D01 · HATA · P2 — Ops eğitim uyarısı yanlış süzülüyor ve bayat kayıtlarla doluyor
- **Mevcut durum:** Ops.cs:52-62.
  - `TOP(40)`, birim süzmesinden **önce** SQL'de uygulanıyor; birim süzmesi sonradan C#'ta yapılıyor (satır 59). En eski 40 kayıt başka birimlere aitse, birim kısıtlı bir Şef kendi birimine ait **hiçbir** uyarıyı göremez.
  - `ORDER BY DueDate` artan sırada ve alt sınır yok. Geçmiş yılların kapanmamış planları ilk 40 sırayı kalıcı olarak işgal ediyor. M08-11-b'deki yıl uyumsuzluğu hatası bu durumu artırıyor.
  - `Personnel.IsActive` ve `TrainingCourses.IsActive` süzülmüyor. Ayrılan personelin planları da uyarı üretiyor.
  - Birimsiz personel (`UnitCode` boş) birim kısıtlı herkese gösteriliyor. Bu, `TrainingCanAccessPersonnelAsync` kuralıyla (P.cs:2801) çelişiyor: o kurala göre birimsiz personeli yalnızca Admin veya tüm birim yetkilisi görür.
- **Kabul kriterleri:**
  1. Birim süzmesi SQL içinde yapılır; `TOP`, süzmeden sonra uygulanır.
  2. Pasif personel ve pasif kurs uyarı üretmez.
  3. Birimsiz personel yalnızca tüm birim yetkilisine görünür.
  4. Süzme sonrası kendi biriminde 1 geciken plan bulunan Şef, 1 uyarı görür.
  5. Bu ilk adımda iptal ve ertelenen planlar dahil edilmez.
- **Efor:** S · **Bağımlılık:** Yok (M08-09 durumları gelince süzmeye eklenir).

### M08-D02 · HATA · P2 — Gözlem tarihi ve aşama doğrulaması
- **Mevcut durum:**
  - P.cs:1668-1710 `ObservedOn` için ileri tarih kontrolü yapmıyor.
  - 30/60/90 aşaması, planın tamamlanma tarihinden önce girilebiliyor.
  - Aynı kişi + kurs + aşama için mükerrer gözlem engellenmiyor ve uyarı da verilmiyor.
  - Bu kurallar tasarım §2.5'te yazıyor ama hiçbir madde bunları üstlenmiyor.
- **Kabul kriterleri:**
  1. Yarın tarihli gözlem 400 döner.
  2. Tamamlanma tarihinden önce girilen 30/60/90 gözlemi kaydedilir, ancak yanıtta `warning` döner.
  3. Aynı aşama için ikinci gözlem kaydedilir ve uyarı döner. Takip hesabı en son geçerli (iptal edilmemiş) gözlemi esas alır.
- **Efor:** S.

### M08-D03 · GÜVENLİK · P2 — Eğitim uçlarında eksik kapsam ve aktiflik kontrolleri
- **Mevcut durum:**
  - P.cs:1649-1666: Yetkinlik değerlendirmesi, `CompetencyCatalog.UnitCode` için `UnitAllowed` kontrolü yapmıyor.
  - P.cs:1677-1683: Gözlemde kursun `IsActive` durumu kontrol edilmiyor.
  - P.cs:1695: Gözlemde iş emrinin birimi kontrol edilmiyor.
  - M08-14 yalnızca oturum ucunu kapsıyor.
- **Kabul kriterleri:**
  1. Haberleşme yetkili kullanıcı, Güvenlik Sistemleri yetkinliğini değerlendirmeye çalışırsa 403 döner.
  2. Pasif kursa gözlem girilirse 400 döner.
  3. Başka birimin iş emrine bağlı gözlem girilirse 403 döner.
  4. Birimsiz yetkinlik ve kurs kabul edilir.
- **Efor:** S.

### M08-D04 · EKSİK · P2 — Eğitim modülü için test senaryoları ve test verisi
- **Mevcut durum:**
  - CL113:34-37: ".NET derlemesi ve gerçek SQL Server üzerinde uygulama testi bu ortamda YAPILMADI."
  - Proje geçmişi belgesinin 562. satırındaki "[ ] Eğitim ve saha gözlemi test edildi" maddesi işaretlenmemiş.
  - TEST_SONUCLARI_V120.txt dosyasında eğitimle ilgili hiçbir kayıt yok.
  - Test projesi yok (envanter #8).
  - Kullanıcı kararı: Derleme ve test bu makinede yapılacak, test verisi olacak.
- **Kabul kriterleri:**
  1. İdempotent bir test verisi scripti oluşturulur: 2 birim, 6 personel (biri birimsiz, biri pasif), 2 kurs (birinde kritik madde), planlar, oturum ve gözlemler.
  2. M08-08, M08-11, M08-13, M08-14, M08-D01 ve M08-D03'ün kabul kriterleri otomatik entegrasyon testi olarak yazılır ve geçer.
  3. Test verisi, üretim veritabanına uygulanamayacak biçimde ayrı bir klasörde tutulur.
- **Efor:** M.

---

## 4. Önerilen uygulama sırası (kullanıcının c → b → a kararına uygun, bağımlılıklar çözülmüş)

1. **(b) önce gelmesi zorunlu veri doğruluğu:** M08-08 → M08-11 (a, b) → M08-13 → M08-09 (P1 kısmı). M08-D04'ün test verisi bunlarla birlikte hazırlanır.
2. **(c) yeni özellikler:** M08-01 → M08-02 (düzeltilmiş) → M08-05 → M08-06 → M08-03 (çekirdek) → M08-07 (aşama 1).
3. **(b) kalanlar:** M08-12 + M08-D01 → M08-D02 → M08-10 (katalog) → M08-15.
4. **(a) güvenlik:** M08-14 + M08-D03 → M08-17.
5. **P3:** M08-04 (M01-10 sonrası), M08-10 (bağlantı), M08-11-c (sınav eşiği), M08-03 (öneri), M08-16.

> Not: (c)'nin başa alınması kullanıcı kararıdır. Ancak M08-01 ve M08-07'nin doğru sonuç vermesi için M08-13 ve M08-11'in önce bitmesi gerekiyor. Aksi halde yeni rapor ve uyarılar yanlış veriyle beslenir. Bu nedenle 1. adımdaki küçük (S) düzeltmeler, (c) grubunun ön koşulu olarak öne alındı.

## 5. Kullanıcıya iletilecek açık sorular (tasarımın §4'üne ek)
- Kritik maddede "Gözlenmedi" seçilebilmesi işin kapsamına bağlı olabilir (örneğin yüksekte çalışma maddesi her işte geçerli değil). Gerekçe zorunluluğu yeterli mi, yoksa kurs bazında "her gözlemde zorunlu kritik madde" ayrımı mı istenir?
- Sınav eşiği istenmiyorsa M08-11-c tamamen çıkarılabilir. Mevcut "katılım = tamamlandı" kararı korunur.
