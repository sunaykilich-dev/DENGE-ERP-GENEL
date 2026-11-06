# M10 — Operasyon Merkezi, SLA, Bekleme Nedenleri ve Uyarılar — Bağımsız Denetim

> **Tarih:** 21 Ekim 2026 · **Denetlenen:** `10_operasyon_sla_tasarim.md` (M10-01 … M10-15)
> **Kaynak:** V1.20.1 salt okunur. Kaynak koda dokunulmadı.
> **Kısaltmalar:** `P.cs` = Program.cs, `Ops.cs` = OpsSuite.cs, `ops.js` = wwwroot/ops120.js, `app.js` = wwwroot/app.js, `v120.sql` = Database/ZZ_V120_Operations.sql, `v114.sql` = Database/ZZ_V114_LiveTimeTracking.sql.
> **Uyulan kararlar:** Kapsam yalnız teknik servis. Öncelik sırası (c) yeni → (b) eksik → (a) güvenlik; veri kaybı/sızıntısı yaratan açıklar KRİTİK diye işaretlenir. Logo/Flowick kapsam dışı. Rol önerileri VARSAYIM'dır. Süre kaydı yoksa "eksik" yazılır. Tahmini süre gerçek süre yerine kullanılmaz. Mola kişi-saate girmez. Büyük yeniden yazım yok.

---

## 1. Özet

| Karar | Adet | Maddeler |
|---|---|---|
| KABUL | 6 | M10-03, M10-06, M10-07, M10-08, M10-09, M10-15 |
| DEĞİŞTİR | 9 | M10-01, M10-02, M10-04, M10-05, M10-10, M10-11, M10-12, M10-13, M10-14 |
| RET | 0 | — |
| Eklenen | 4 | M10-D01 … M10-D04 |

**Genel görüş:** Tasarımın mevcut durum tespitleri büyük ölçüde doğru ve kanıtlı. Kodla karşılaştırdığımda bir maddeyi bile "zaten var olan bir şeyi yeni diye önermiş" olarak bulmadım. Ana sorunlar şunlar:

1. **Başka modüllerle çakışma.** M10-11 ↔ M01-14/M01-D01, M10-12 ↔ M09-12, M10-04 ↔ M01-D04, M10-05 (açık sayaç uyarısı) ↔ M09-05, M10-14 ↔ M13 (operations.manage şablonu). Aynı iş iki kez yazılmamalı.
2. **Kabul kriterinde iki hesap/olgu hatası var.** M10-02(1) mesai hesabı yanlış. M10-13'ün gerekçesindeki "kritik → 72 saat" iddiası yanlış (sözlük büyük/küçük harf duyarsız).
3. **Var olmayan bir akışa dayanılıyor.** Kodda öncelik değiştirme ucu ve ekranı yok (yalnız INSERT'te `Priority`: P.cs:400, 409, 2655, 3086). M10-01(5) ve M10-13 "öncelik değişince" kriterleri ancak M01-08 gelince test edilebilir.
4. **Aşırı mühendislik riski.** M10-01'deki "birim + kategori + öncelik" politika matrisi, M10-05'teki kademeli alıcı/eskalasyon ve M10-02'deki yarım gün tatil, kullanıcı SLA sayılarını ve organizasyon şemasını vermeden kurulmamalı. İlk sürüm sade tutulmalı, tablo yapısı genişlemeye açık bırakılmalı.

**KRİTİK:** Bu modülde KRİTİK seviyede açık yok. Tasarımcının değerlendirmesine katılıyorum. Ancak M10-14'ün etkisi, İK rolündeki `users.manage` izni (P.cs:3934) yüzünden pratikte sınırlı kalır. İK kendine her izni verebilir. Bu konu M13'te ele alınmalı.

---

## 2. Madde madde değerlendirme

### M10-01 · SLA politikası v2 ve işe damgalanan hedef — **DEĞİŞTİR · P1**

**Doğrulama:**
- `OpsSlaTargets` yalnız `Priority, ResolutionHours` içeriyor (v120.sql:2-6).
- Gecikme her istekte `CreatedAt + SLA` olarak hesaplanıyor (Ops.cs:31, 87). Hedef işe damgalanmadığı için SLA değişince geçmiş geriye dönük değişiyor. Bu doğru.
- `PUT /api/ops/sla` denetim kaydı yazmıyor (Ops.cs:122-129). Bu doğru.
- `ClosedAt` yalnız `Kapatıldı` geçişinde doluyor (P.cs:527, 2761). Bakım formunda `@Done=0` iken NULL'a çekiliyor (P.cs:2520). Bu doğru.

**Sorunlar:**
- **(a) Öncelik değiştirme akışı yok.** Kodda öncelik değiştirme ucu yok. Kriter (5) M01-08 olmadan test edilemez. Bu yüzden bağımlılık M01-08 olmalı.
- **(b) Politika matrisi erken.** Birim+kategori+öncelik matrisi, kullanıcı gerçek SLA sayılarını vermeden (tasarım §4 S1-S3) ve M01-07 kategorisi olmadan erken kalıyor.
- **(c) Teknisyeni bloke eden kural.** "Hedef geçmişken gecikme nedenisiz `Tamamlandı` → 400" kuralı sahadaki teknisyeni bloke eder. M01-09 `Tamamlandı`'yı teknisyene, `Kapatıldı`'yı şefe veriyor.
- **(d) Tekrar açılma kuralı tanımsız.** "Tekrar Açıldı" durumunda ResolvedAt/SlaResult ne olacak, belli değil.
- **(e) Müdahale tanımı M09 ile çelişebilir.** "Yola çıktım"ı müdahale saymak tartışmalı. M09-06'da "ilk varış = ilk Saha Çalışması" diye tanımlandı. Tanımlar çelişmemeli. Sayaçta `Bekleme` ve `Mola / Ara` faaliyetleri de var (v114.sql:19-21). Bunlar müdahale sayılmamalı.

**Düzeltilmiş tanım:**
- **Politika tablosu:**
  - İlk sürümde politika = öncelik (+ isteğe bağlı birim). Tabloda `UnitCode NULL`, `Category NULL` kolonları yer tutucu olarak durur.
  - Kategori kırılımı M01-07 ve kullanıcı onayı sonrası açılır.
  - Müdahale hedefi kolonu eklenir ama kullanıcı onaylayana kadar NULL olabilir. NULL ise müdahale SLA'sı "tanımsız" gösterilir.
- **Açılışta damgalama:** `SlaPolicyId`, `ResponseDueAt` ve `ResolveDueAt` işe yazılır.
- **FirstResponseAt:**
  - İlk `Saha Çalışması`, `Uzaktan Destek` ya da `Atölye` sayaç başlangıcıdır, ya da POC'ta `Telefonla Destek`/`Uzaktan Müdahale` durumuna ilk geçiştir.
  - `Yol / Ulaşım` ayrı bir "ilk yola çıkış" bilgisi olarak tutulur. Müdahale sayılıp sayılmayacağını kullanıcı onaylar.
  - `Bekleme` ve `Mola / Ara` asla müdahale değildir.
- **ResolvedAt:** İlk `Tamamlandı`/`Kapatıldı` geçişidir.
- **Tekrar Açıldı:** `ResolvedAt` ve `SlaResult` temizlenir, hedef aynı kalır. İş, müşteri açısından çözülmemiş sayılır.
- **Gecikme nedeni:** Zorunluluk `Kapatıldı` adımındadır (şef). `Tamamlandı`'da isteğe bağlıdır.
- **Tek SLA fonksiyonu:** SLA hesabı tek bir sunucu fonksiyonunda yapılır (M10-D03).
- **Kabul kriterleri:**
  1. Kritik iş açılınca `ResolveDueAt = SlaStartAt + 12 sa`.
  2. SLA 12→8 yapılınca eski işin hedefi değişmez.
  3. İlk `Saha Çalışması` sayacı `FirstResponseAt`'i doldurur. `Yol`, `Bekleme` ve `Mola` doldurmaz. İkinci sayaç değiştirmez.
  4. Hedef geçmiş işte gecikme nedenisiz `Kapatıldı` → 400. `Tamamlandı` → 200.
  5. Öncelik değişimi (M01-08 ucu ile) hedefi yeniden hesaplar ve eski/yeni hedefi geçmişe yazar.
  6. `PUT /api/ops/sla` sonrası denetim kaydında kullanıcı, eski değer ve yeni değer var.
  7. `Tekrar Açıldı` sonrası `SlaResult` NULL olur.
- **Bağımlılık:** M01-08, M01-09, M09-06 (tanım uyumu), M13 (`operations.manage` şablonu).

### M10-02 · Mesai takvimi ve resmi tatiller — **DEĞİŞTİR · P2**

**Doğrulama:**
- Takvim yok. ops.js:47'de yalnız "mesai takvimi uygulanmaz" uyarı metni var. Bu doğru.
- Belgede (§5.10 ve §14 / satır 223, 535) açık iş olarak not edilmiş.

**Hata — Kriter (1) yanlış hesaplanmış:**
- Mesai 08:30–17:30 iken Cuma 16:30'da açılan işin cuma günü 1 saati kalır.
- Kalan 7 saat Pazartesi 08:30'dan sayılırsa hedef **15:30** olur, 16:30 değil.
- Hedefin 16:30 çıkması için öğle arası (ör. 12:30–13:30) tanımı gerekir. Tasarımda öğle arası yok.

**Diğer notlar:**
- `IsHalfDay` (arife) ilk sürüm için gerekli değil, sonra eklenebilir.
- Kullanıcı 7/24 mü mesai mi olduğunu henüz söylemedi. Havalimanı ve AVM X-Ray işleri büyük olasılıkla 7/24 olacak. Bu yüzden P2.

**Düzeltilmiş tanım:**
- Tek ortak mesai takvimi (gün, başlangıç, bitiş, isteğe bağlı öğle arası) ve tatil tablosu (tarih, ad).
- `CalendarType` politika bazında tanımlanır.
- **Kabul kriterleri:**
  1. Mesai Pzt–Cum 08:30–17:30 (öğle arası yok) iken Cuma 16:30 açılan 8 saatlik işin hedefi Pazartesi 15:30. Aynı ayarda 12:30–13:30 öğle arası tanımlıysa hedef Pazartesi 16:30.
  2. 29 Ekim tatil tanımlıysa o gün sayılmaz.
  3. 7/24 politika takvimden etkilenmez.
  4. Takvim ve tatil değişikliği denetim kaydına yazılır. Daha önce damgalanmış hedefler değişmez.
  5. En az 6 senaryolu birim testi: hafta sonu, mesai dışı açılış, tatil, yılbaşı, öğle arası, SLA durdurmalı bekleme.
- Yarım gün desteği ikinci aşamadır.

### M10-03 · Bekleme nedeni kataloğu, SLA durdurma, beklenen bitiş — **KABUL · P2**

**Doğrulama:**
- Neden serbest metin ve en fazla 100 karakter (Ops.cs:134).
- Neden `prompt()` ile alınıyor (ops.js:72-76).
- `OpsHolds` tablosunda katalog, beklenen tarih ve kapatan kullanıcı alanları yok (v120.sql:9).
- Üç iddia da doğru.

**Notlar:**
- M01-14 de "neden sabit listeden" diyor. Katalog tablosu tek yerde (bu maddede) tanımlanmalı, M01-14 bu tabloyu kullanmalı.
- "Teknisyen yalnız kendi işi" kuralı bugün zaten fiilen geçerli: `FilterWorkOrdersForUser` Teknisyen rolünü atamaya göre süzüyor (P.cs:3499-3500, Ops.cs:135). Yeni kod gerekmez, test yeterli.
- Rol tablosunda "Operasyon Uzmanı müşteri beklemesi girer" yazıyor. Ama bu şablonda ne `workorders.edit` ne de `operations.manage` var (P.cs:3928). Bunu M13 çözmeli. Rol önerisi VARSAYIM'dır.

### M10-04 · Tekrar arıza kuralı, işaret ve kök neden — **DEĞİŞTİR · P2**

**Doğrulama:** Mevcut liste (Ops.cs:93-96) zaman penceresi kullanmıyor ve yalnız dönem içi/açık işlerde aynı seriyi sayıyor. İddia doğru.

**Sorunlar:**
- M01-D04 zaten `RelatedWorkOrderId + RelationType` (Mükerrer / Tekrar Arıza / Devam İşi) öneriyor. İkinci bir `RepeatOfWorkOrderId` kolonu açmak gereksiz.
- Servis işinde birden çok seri olabiliyor (`WorkOrderDevices`, P.cs:416-425). Kural tek seriye göre yazılmış.
- Kök neden seçimi "kapanışta"ya bağlanmış. Teknisyeni bloke etmemesi için şef adımında (`Kapatıldı`) olmalı.

**Düzeltilmiş tanım:**
- Tekrar arıza bağı M01-D04'teki `RelatedWorkOrderId` ile ve `RelationType='Tekrar Arıza'` değeriyle tutulur. Yalnız `RepeatConfirmed` (Aynı arıza / Farklı arıza / Kullanıcı hatası) bu maddede eklenir.
- Eşleşme kuralı:
  - Yeni işin **herhangi bir aktif seri numarası** (`WorkOrderDevices.IsActive=1`), son N gün (varsayılan 30) içinde kapanmış servis işlerinden birinin serisiyle eşleşirse iş işaretlenir.
  - Normalizasyon yalnız `TRIM` + büyük harftir. Tire ve baştaki sıfır korunur (seri no metin kuralı).
  - M01-16 tamamlanınca cihaz kimliği öncelikli kullanılır.
- **Kabul kriterleri (değişen kısım):**
  - (5) Tekrar işaretli iş kök neden seçilmeden `Kapatıldı` olamaz (400). `Tamamlandı` engellenmez.
  - (7) İki seri içeren yeni işte yalnız ikinci seri eşleşirse de iş işaretlenir.
  - Diğer kriterler aynı kalır.
- **Bağımlılık:** M01-D04, M01-09, M01-16 (isteğe bağlı).

### M10-05 · Kalıcı bildirim, kademeli SLA uyarısı, rozet — **DEĞİŞTİR · P2**

**Doğrulama:**
- Uyarı anahtarı günlük (`…:yyyyMMdd`, Ops.cs:32-34, 48, 60). Bu yüzden "Görüldü" ertesi gün sıfırlanıyor.
- Uyarılar yalnız Operasyon sayfası açıkken 3 dakikada bir yenileniyor (ops.js:102).
- `OpsAlertAcks` tablosu hiç temizlenmiyor (v120.sql:14-15).
- Ack ucu tüm uyarıları yeniden hesaplıyor (Ops.cs:114-116).
- Hepsi doğru.

**Sorunlar:**
- **Kademeli alıcı erken.** Organizasyon şeması yok ve şef bir kullanıcı kimliği değil, atamadaki isim metni (P.cs:3450). "Birim şefi → müdür" kademesi bugün güvenilir kurulamaz.
- **Uyarı tekrarı.** "Açık sayaç > 10 sa" uyarısı M09-05 ile aynı.
- **Kriter (3) belirsiz.** `AllowedUnits` boş olan kullanıcı tüm birimleri görüyor (P.cs:2807).

**Düzeltilmiş tanım:**
- İlk sürüm:
  - `BackgroundService` ile 5 dakikada bir `OpsNotifications` tablosuna yazılır.
  - Koşul kalkınca kayıt otomatik kapanır. Aynı koşul için yeni kayıt açılmaz.
  - Alıcı belirleme izin + birim filtresine göredir: `operations.view` + `UnitAllowed`. Teknisyene yalnız kendi işleri gider.
  - Kademeli eskalasyon (müdüre ikinci kademe) organizasyon şeması gelince açılacak bir ayar olarak bırakılır.
  - "Uzun açık sayaç" türü M09-05'ten alınır, burada yeniden tanımlanmaz.
- Rozet her sayfada 60 saniyede bir yoklanır. Rozet ucu yalnız `COUNT` döner (M10-D04).
- **Kabul kriterleri (değişen kısım):**
  - (3) `AllowedUnits=[Haberleşme]` olan kullanıcı Güvenlik Sistemleri bildirimini görmez.
  - (7) Rozet ucu 1000 açık işte 200 ms altında yanıt verir.
- **Bağımlılık:** M10-01, M10-03, M09-05.

### M10-06 · E-posta bildirimi (ikinci aşama) — **KABUL · P3**

**Doğrulama:**
- SMTP yalnız teklif gönderiminde kullanılıyor.
- `ErpUsers` tablosunda e-posta alanı yok.
- Belgede "otomatik e-posta hazır değil" diye geçiyor (satır 227, 533).

**Notlar:**
- İkinci aşama olarak işaretlenmesi doğru. SMTP bilgisi İT'ye bağlı.
- SMTP parolası `dengeerp.env` ortam değişkeninde kalmalı. Veritabanına ve loga yazılmamalı.

### M10-07 · SLA, bekleme ve tekrar arıza raporu — **KABUL · P2**

**Doğrulama:**
- CSV 8 kolon (Ops.cs:262-263).
- Excel'de SLA kolonu yok. Öncelik yalnız `=="Kritik"` sayımı olarak geçiyor (P.cs:3688, 3693).

**Notlar:**
- Kriter (1) doğru kurgulanmış: eksik iş paydadan çıkarılıyor, "Ölçülemedi" ayrı sayılıyor.
- **Bekleme ayrımı şart.** "Bekleme" iki farklı veri demek: iş beklemesi (`OpsHolds`) ve personel sayacındaki `Bekleme` faaliyeti (v114.sql:20). Rapor ikisini ayrı başlıkla göstermeli (M10-D02). Aksi halde aynı kelime iki farklı sayı üretir.
- Rapor ekranı M12 (Raporlama) ile aynı yerde ve aynı filtre altyapısıyla yapılmalı.

### M10-08 · Operasyon merkezi sayaçları, sıralama, dönem seçimi — **KABUL · P2**

**Doğrulama:**
- `days=30` sabit (ops.js:2).
- Atanmamış ve plansız sayaçları yok (ops.js:27).
- Sıralama yalnız gecikmiş/gecikmemiş ikilisi (Ops.cs:106).
- Hepsi doğru.

**Ek gözlem:**
- Sayaçlar sunucuda, listeler istemcide ayrı mantıkla süzülüyor (ops.js:31-41).
- "Bugün" istemcide tarayıcı tarihiyle, sunucuda `DateTime.Today` ile hesaplanıyor.
- Liste sunucuda 1500, istemcide 250 kayıtla kesiliyor (Ops.cs:106, ops.js:43).
- Bu yüzden "sayaç = liste" kriteri bugün büyük veride sağlanamaz.
- Kabul kriterine şu eklenmeli: **"300 açık işte sayaç ve liste toplamı eşit (sayfalama ile)".**

### M10-09 · Personel iş yükü: canlı durum ve planlı yük — **KABUL · P2**

**Doğrulama:** Bugünkü sekme yalnız isim metniyle atama sayısı veriyor (Ops.cs:89-92). İddia doğru.

**Not:** `WorkOrderLiveSessions.TechnicianUserId` zaten kimlik tutuyor (v114.sql:8). Canlı durum M01-10 beklenmeden kimlik bazlı gösterilebilir. Yalnız planlı yük için M01-10 gerekli.

### M10-10 · PB işleri sahte "Geciken" — **DEĞİŞTİR · P1**

**Doğrulama:**
- Bulgu gerçek. PB işleri `N'Normal'` önceliğiyle açılıyor (P.cs:3086). Ops.cs:31 ve 87 bunlara da 72 saat uyguluyor. Uyarı anahtarı günlük olduğu için her gün yeniden "Kritik" uyarı çıkıyor.

**Düzeltme gereken iki ayrıntı:**
- **(a) "Gelecek ay hedefli" senaryosu sınırlı.** Otomatik üretim yalnız hedef ayın 1'i geldiğinde çalışıyor (`if(nextTarget > today) continue;`, P.cs:2960). Gelecek hedefli PB işi yalnız elle "iş emri üret" ucuyla oluşabiliyor (P.cs:2386-2398). Asıl yaygın sorun şu: dönem içinde (ör. 3-4 aylık periyot) yapılması normal olan bakım, üretimden 3 gün sonra "Geciken" sayılıyor.
- **(b) Join yolu yanlış.** Bir plan birden çok PB iş emri üretiyor. `MaintenancePlans.GeneratedWorkOrderId` yalnız ilk işi tutuyor (P.cs:3095). Doğru yol `MaintenanceDeviceItems.WorkOrderId → MaintenancePlanId → TargetDate`.

**Düzeltilmiş kabul kriterleri:**
1. TargetDate'i bu ayın 1'i olan ve dönem sonu henüz gelmemiş PB işi, üretimden 4 gün sonra "Geciken" sayısına girmez ve uyarı üretmez.
2. Dönem sonu (kullanıcı kararı: ay sonu ya da TargetDate + 12/frekans ay) geçmiş ve kapanmamış PB işi "Vadesi geçen bakım" sayacında görünür.
3. Aynı plana bağlı 17 cihaz işinin hepsi aynı vadeyi alır (join `MaintenanceDeviceItems` üzerinden).
4. "Geciken" yalnız `Maint()=false` işlerden oluşur (otomatik test).

### M10-11 · Bekleme kaydı ile iş durumu tutarsız — **DEĞİŞTİR · P1**

**Doğrulama:**
- `PATCH status` aktif `OpsHolds` kaydını kapatmıyor (P.cs:525-533).
- Bakım formu `Beklemede` durumunu hold kaydı açmadan veriyor (P.cs:2512).
- Atölye ucu da aynı şekilde, hold kaydı olmadan (P.cs:2750).
- İkinci hold isteği filtreli benzersiz indekse çarpıp SqlException ile 500 dönüyor (Ops.cs:136-143, v120.sql:11-12).
- `counters.hold` kapalı işleri de sayıyor (Ops.cs:105).
- Hepsi doğru.

**Sorun:** Bu maddenin (c) "409" ve "PATCH ile Beklemede engeli" kısmı M01-14'te, atölye ucunun durum geçişi ise M01-D01'de zaten var. Aynı uçlar üç maddede ayrı ayrı düzeltilmemeli.

**Düzeltilmiş tanım:** Bu madde yalnız şunları kapsar:
- **(a) Otomatik kapatma:** İş herhangi bir uçtan (PATCH, bakım formu, atölye, plan) `Beklemede` dışına çıkınca aktif `OpsHolds` kaydı aynı transaction'da kapatılır. Kapatma kaydına `ReleasedBy` ve "otomatik: durum değişti" notu yazılır. Bu mantık M01-09'daki `TryTransition` içinde tek yerde durur.
- **(b) Bakım formu:** Sonuç "tekrar gidilecek/teklif" olunca katalog kodlu bir bekleme kaydı açılır (`BAKIM_UYGUNSUZLUK`).
- **(c) Sayaç:** "Bekleme" sayacı yalnız açık işleri sayar.
- 409 ve PATCH engeli M01-14'e, atölye geçişi M01-D01'e bırakılır.
- **Kabul kriterleri:** (1), (2), (4) ve (5) aynı kalır. (3) M01-14'e taşınır.

### M10-12 · Saat dilimi — **DEĞİŞTİR · P1**

**Doğrulama:**
- `linux/` altında `TZ`, `timedatectl` ya da `Istanbul` geçmiyor (grep ile doğrulandı).
- Ops "şimdi" değerini `DateTime.Now`/`DateTime.Today` ile alıyor, `CreatedAt` ise SQL `SYSDATETIME()`'dan geliyor (Ops.cs:28, 83, 87, 101-104).
- İddia doğru.

**Sorun:** M09-12 aynı işi kapsıyor: `03_dogrula.sh` saat dilimi kontrolü ve SQL saatinin tek kaynak olması.

**Düzeltilmiş tanım:**
- Kurulum kontrolü ve saat kaynağı kararı M09-12'de tek madde olarak kalır.
- Bu madde yalnız Ops ve SLA hesaplarının (`overdue`, `today`, `tomorrow`, uyarı üretimi, BackgroundService) M09-12'deki tek "şimdi" yardımcısını kullanmasını şart koşar.
- Kriter (3) aynen korunur: 23:30 / 00:30 senaryosu.
- **Bağımlılık:** M09-12.

### M10-13 · Öncelik doğrulanmıyor — **DEĞİŞTİR · P2**

**Doğrulama:**
- `POST /api/workorders` önceliği doğrulamadan kaydediyor (P.cs:409).
- Formda yalnız Normal/Yüksek/Kritik var, `Düşük` yok (app.js:297).
- Excel `=="Kritik"` karşılaştırması yapıyor (P.cs:3688, 3693).
- Bunlar doğru.

**Olgu hatası:** Gerekçedeki "'kritik' SLA'da 72 saat alıyor" iddiası yanlış.
- `Targets` sözlüğü `StringComparer.OrdinalIgnoreCase` ile kuruluyor (Ops.cs:15). Bu yüzden `kritik` SLA'da 12 saat alıyor.
- Excel ve ön yüzdeki `==='Kritik'` karşılaştırmaları ise onu Kritik saymıyor (P.cs:3688, app.js:247, 1162).
- 72 saat yalnız katalogda hiç olmayan değerlere (ör. `Acil`) uygulanıyor.
- Yani sorun, aynı işin **SLA'da kritik, raporda kritik değil** görünmesi.

**Düzeltilmiş gerekçe ve kabul kriterleri:**
1. `priority="Acil"` → 400. `priority="kritik"` → `Kritik` olarak kaydedilir ya da 400 döner. Hangisi olacağına geliştirici karar verir ama davranış tutarlı olmalıdır.
2. Form listesi = SLA tablosu öncelikleri.
3. Katalog dışı ya da harf farklı mevcut kayıtlar M10-15 ile raporlanıp düzeltilir.

Öncelik değişikliğinde doğrulama M01-08 ucunda yapılır.

### M10-14 · Operasyon merkezi yalnız `dashboard.view` ile — **DEĞİŞTİR · P2**

**Doğrulama:**
- Uç yalnız `dashboard.view` istiyor (Ops.cs:79).
- Menü de yalnız `dashboard.view` ile açılıyor (app.js:182).
- İK şablonunda `dashboard.view` var ama `workorders.view` yok (P.cs:3934).
- Bu doğru. KRİTİK değil; fiyat/maliyet dönmüyor.

**Düzeltmeler:**
- **Depo iddiası geçersiz.** Gerekçede Depo da sayılmış, ama Depo şablonunda zaten `workorders.view` var (P.cs:3932). Asıl sorun yalnız İK'da.
- **Etki sınırlı.** İK'da `users.manage` var. Bu kişi kendine her izni verebilir (P.cs:3934, envanter §52). M13 düzeltilmeden bu maddenin etkisi sınırlıdır.
- **`operations.manage` hiçbir şablonda yok.** İzin katalogda var (P.cs:3897) ama Admin dışında hiçbir şablonda yok (P.cs:3921-3935). Bugün Müdür bile SLA'yı düzenleyemiyor. Bu M13'te ele alınıyor, burada bağımlılık olarak yazılmalı.

**Düzeltilmiş kabul kriterleri:** Mevcut (1)–(5) korunur, şunlar eklenir:
- (6) Müdür/Yrd. şablonunda `operations.manage` var. Bu VARSAYIM'dır; M13 ile birlikte yapılır.
- (7) Geçiş scripti önce önizleme raporu üretir, iki kez çalıştırılınca sonuç aynıdır.

**Bağımlılık:** M13 (`users.manage` ayrıştırma ve şablon güncellemesi), M01-D02 (izin göçü kalıbı).

### M10-15 · Geçmiş SLA alanlarının geri doldurulması — **KABUL · P2**

**Doğrulama:** `WorkOrderStatusLogs` var ve `InsertStatusLogAsync` P.cs:3349-3361'de. SLA alanları yok.

**Notlar:**
- **(a) Atölye işleri çoğunlukla "Ölçülemedi" kalacak.** Atölye ucu durum logu yazmıyor (P.cs:2746-2772), `Tamamlandı`'da `ClosedAt` da dolmuyor. Script raporunda bu durum ayrı satırda gösterilmeli. Bu beklenen bir sonuçtur, hata değildir.
- **(b) "O günkü hedef" bilinemez.** SLA değişiklik geçmişi yok. Bu yüzden `SlaSource='Geriye dönük (güncel hedef)'` yazılmalı.
- **(c) PB işleri hariç tutulur.** PB işleri geri doldurmaya girmez (M10-10).

---

## 3. Eklenen maddeler

### M10-D01 · EKSİK · Mobil iş listesinde öncelik ve SLA kalan süre — **P2**
- **Mevcut:**
  - Mobil İşler kartında yalnız iş no, müşteri, şehir ve durum var. Öncelik ve hedef yok (ops.js:7-8).
  - Liste sıralaması sunucunun `WorkOrderId DESC` sırası (P.cs:3462).
  - Tasarım §2.1 "teknisyen kendi işlerinin SLA kalan süresini mobilde görür" diyor ama bunu yapan bir madde yok. M09-01'de de SLA geçmiyor.
- **Neden:** Teknisyen hangi işe önce gideceğini bilemiyor. SLA ancak sahada uygulanırsa tutturulur.
- **Yapılacak:**
  - Mobil kartta öncelik rozeti ve "SLA kalan süre" gösterilir. Negatifse "Gecikti" yazar. Duran beklemede "Durduruldu" yazar.
  - Varsayılan sıralama: önce bugün planlı olanlar, sonra SLA kalan süresi artan.
  - Değerler sunucudan gelir (M10-D03).
- **Kabul kriterleri:**
  1. Teknisyenin 3 açık işinden SLA'sı en yakın olan listede ilk sırada.
  2. PB işinde SLA yerine "Vade: Ekim 2026" yazar.
  3. Fiyat/maliyet bilgisi görünmez.
- **Roller:** Teknisyen (kendi işleri); `workorders.view`.
- **Veri:** Yok.
- **Efor:** S
- **Bağımlılık:** M10-01, M10-10, M10-D03, M09-01.

### M10-D02 · EKSİK · İş beklemesi ile sayaçtaki "Bekleme" faaliyetinin ayrıştırılması — **P2**
- **Mevcut:**
  - İki ayrı "bekleme" var: iş beklemesi `OpsHolds` (v120.sql:9) ve personel sayacı faaliyeti `Bekleme` (v114.sql:20).
  - İkisi arasında bağ ya da tanım yok.
  - Teknisyen sahada "Bekleme" sayacı çalıştırırken iş `Beklemede` (SLA durmuş) olabiliyor. Ya da tersi oluyor: iş SLA'sı işlerken personel saatlerce "Bekleme" yazıyor.
- **Neden:**
  - M10-07 "bekleme nedeni dağılımı" ve M09 "yol/saha/bekleme süresi" raporları aynı kelimeyle farklı sayılar üretecek. Yönetici güvenmez.
  - SLA durdurma, personel bekleme sayacıyla karıştırılmamalı.
- **Yapılacak:**
  - Raporlarda ve ekranda iki ayrı terim kullanılır: "İş Beklemesi (neden + SLA etkisi)" ve "Personel Bekleme Süresi (sayaç)".
  - SLA durduran iş beklemesi açıkken `Saha Çalışması` sayacı başlatılırsa uyarı gösterilir ("İş beklemede görünüyor, beklemeyi kaldırmak ister misiniz?"). Kayıt engellenmez.
  - Personel `Bekleme` faaliyeti SLA'yı durdurmaz.
- **Kabul kriterleri:**
  1. SLA raporunda yalnız `OpsHolds` süresi "durdurulan süre" olarak görünür.
  2. Saha/Zaman raporunda sayaç `Bekleme` süresi ayrı kolonda görünür ve SLA'yı etkilemez.
  3. Beklemedeki işte saha sayacı başlatılınca uyarı çıkar, sayaç yine başlar.
- **Roller:** —
- **Veri:** Yok.
- **Efor:** S
- **Bağımlılık:** M10-03, M09-02.

### M10-D03 · EKSİK · SLA durumunun tek sunucu fonksiyonundan üretilmesi (tek doğru kaynak) — **P2**
- **Mevcut:** SLA ve gecikme mantığı dağınık:
  - Ops.cs:31 (uyarı) ve 87 (liste) aynı hesabı iki ayrı yerde yapıyor.
  - Ana panelde kritik/geciken mantığı istemcide (app.js:216-257).
  - Excel kendi sayımını yapıyor (P.cs:3688-3693).
  - Mobil ekranda hiç yok.
  - M01-11 "Geciken, Operasyon Merkezi ile aynı sayı" şartını koyuyor ama ortak bir kaynak tanımlanmamış.
- **Neden:** Mesai takvimi, durdurma ve PB istisnası eklenince istemcide tekrar eden her hesap farklı sonuç verir. Bu da "kutu ≠ liste ≠ Excel" sorununu kalıcı hâle getirir.
- **Yapılacak:**
  - Tek bir C# fonksiyonu yazılır: `SlaState(iş, şimdi)` → {hedef, kalan dakika, durum: Zamanında/Risk/Aşıldı/Durduruldu/Karşılandı/Ölçülemedi/SLA dışı (PB)}.
  - İş listesi, overview, Excel, CSV, bildirim servisi ve mobil bu fonksiyonun API çıktısını kullanır.
  - İstemcide SLA hesabı yapılmaz.
- **Kabul kriterleri:**
  1. Aynı test verisinde Ana Panel "Geciken", Operasyon "SLA aşıldı", Excel ve bildirim sayısı eşittir (otomatik test).
  2. app.js ve ops.js içinde `priority`'ye dayalı saat hesabı kalmaz.
- **Roller:** —
- **Veri:** Yok.
- **Efor:** S
- **Bağımlılık:** M10-01, M01-D05 (test altyapısı).

### M10-D04 · EKSİK · Operasyon uçlarının hafifletilmesi (rozet ve ack) — **P3**
- **Mevcut:**
  - Her `overview` çağrısı tüm `WorkOrders` (P.cs:3441-3493) ve tüm `WorkOrderTimeLogs` (P.cs:3424-3439) kayıtlarını belleğe alıyor.
  - Ack ucu "Görüldü" için bütün uyarıları yeniden hesaplıyor (Ops.cs:114-116).
  - Ops sayfası açık her tarayıcı 3 dakikada bir bu işi tekrarlıyor (ops.js:102).
  - M10-05 her sayfaya 60 saniyelik rozet yoklaması eklerse yük kullanıcı sayısıyla çarpılır.
- **Neden:** Pilot ölçekte sorun değil. Ama rozet tüm kullanıcılara açılınca Linux VM'de gereksiz SQL yükü oluşur. Ucuz ve önleyici bir iş.
- **Yapılacak:**
  - Rozet ucu yalnız `SELECT COUNT(*) FROM OpsNotifications WHERE …` çalıştırır.
  - Ack bildirim kimliğiyle tek UPDATE yapar.
  - Overview süre kayıtlarını yalnız seçili dönemin işleri için ve SQL'de toplayarak okur.
  - Genel sayfalama M01-17'ye, zaman tablosunun okunması M09-15'e bırakılır.
- **Kabul kriterleri:**
  1. Rozet ucu iş emri ya da süre tablosunu okumaz (SQL profiler ile doğrulanır).
  2. Ack ucu tek satır günceller.
  3. Test verisinde (5.000 iş, 50.000 süre kaydı) overview 1 saniyenin altında yanıt verir.
- **Roller:** —
- **Veri:** İndeks `OpsNotifications(RecipientUserId, ClosedAt, SeenAt)`.
- **Efor:** S
- **Bağımlılık:** M10-05.

---

## 4. Önerilen uygulama sırası (denetim sonrası)

1. **Hemen yapılacak düzeltmeler** (yanlış sayı üretenler): M10-10, M10-11 (M01-14 ile birlikte), M10-12 (M09-12 ile birlikte).
2. **Yeni özellik çekirdeği:** M10-01 (sade politika) → M10-D03 → M10-03 → M10-15 → M10-04.
3. **Ekran ve rapor:** M10-08, M10-09, M10-D01, M10-D02, M10-07.
4. **Bildirim:** M10-05 → M10-D04. Daha sonra M10-02 (kullanıcı mesai kararı verince) ve M10-06 (SMTP hazır olunca).
5. **Güvenlik:** M10-13 ve M10-14 (M13 ile birlikte).

## 5. Kullanıcı kararı bekleyen ek sorular (tasarımın §4 listesine ek)

- **Müdahale anı:** "Yola çıktım" mı, "Sahaya vardım / uzaktan bağlandım" mı? (Öneri: varış. M09-06 ile uyumlu.)
- **Tekrar açılan iş:** SLA'yı ilk hedefle sürdürsün mü? (Öneri: evet, ilk çözüm geçersiz sayılır.)
- **Gecikme nedeni:** Teknisyenin `Tamamlandı` adımında değil, şefin `Kapatıldı` adımında zorunlu olsun mu? (Öneri: evet.)
