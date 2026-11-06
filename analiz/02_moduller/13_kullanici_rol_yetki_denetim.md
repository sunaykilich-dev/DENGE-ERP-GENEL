# M13 — Kullanıcı, Rol, Yetki ve Personel/Organizasyon — Bağımsız Denetim

> **Tarih:** 21 Ekim 2026 · **Denetlenen:** `13_kullanici_rol_yetki_tasarim.md` (M13-01 … M13-14)
> **Kaynak (salt okunur):** `kaynak/V1_20_1_orijinal/DengeERP.Api`. Kısaltmalar: **P.cs** = `Program.cs`, **Ops.cs** = `OpsSuite.cs`, **upd.sql** = `Database/DengeERP_Update.sql`, **v15.sql** = `Database/DengeERP_V15_Schema.sql`.
> **Yöntem:** Her maddenin "mevcut durum" iddiası kod okunarak doğrulandı. Kullanıcı kararlarıyla (kapsam yalnız teknik servis; öncelik c→b→a; kritik güvenlik ayrıca işaretlenir; org şeması sonra gelecek) karşılaştırıldı.

---

## 1. Genel değerlendirme

Tasarım genel olarak **doğru ve kodla tutarlı**. Kritik iki iddia (yetki yükseltme ve kapatılan hesabın açık oturumla çalışmaya devam etmesi) kodda birebir doğrulandı:

- `POST/PUT /api/users` izin listesini hiç doğrulamıyor. `users.manage` sahibi kendine veya başkasına `*` ve `RoleName="Admin"` verebiliyor (P.cs:213-216, 253-258). `reset-password` ve `status` uçlarında hedefin yetkisine bakılmıyor (P.cs:321-357).
- `PATCH /api/users/{id}/status` ve `reset-password` oturumları düşürmüyor. Oturum düşürme yalnız personel ucunda var (P.cs:1897-1898). `GetCurrentUser` yalnız bellekteki sözlüğe bakıyor (P.cs:2821-2825).
- `IsAdmin()` rol adına bakıyor; `UnitAllowed()` boş birim listesini "tümü" sayıyor (P.cs:2805-2807).

Bununla birlikte denetimde **dört önemli düzeltme** ve **üç kaçırılmış madde** çıktı:

1. **M13-12 kural 4 kendi içinde çelişkili.** "Hedef daha genişse pasifleştirme 403" kuralı alt küme mantığıyla uygulanırsa, İK (yalnız `personnel.*` ve `training.*`) **hiçbir teknisyeni** işten çıkaramaz; çünkü teknisyende İK'da olmayan `workorders.*` izinleri var. Bu, tasarımın kendi "erişimi kapatmak kolay olmalı" ilkesine ters. Kapatma için üstünlük kuralı yalnız hassas izinlere (`*`, `users.manage`) uygulanmalı.
2. **M13-07'deki "Şef'e `operations.manage`" önerisi yanlış.** `operations.manage` yalnız **şirket geneli SLA hedeflerini** değiştiren uçta kullanılıyor (Ops.cs:124). Bekletme/serbest bırakma zaten `workorders.edit` ile açık (Ops.cs:133, 149) ve Şef şablonunda bu izin var. Şefe `operations.manage` vermek, şefin tüm şirketin SLA saatini değiştirmesine yol açar.
3. **M13-03 kabul (3) "kurallar"la çelişiyor.** İşten çıkış anında açık sayacı "şimdi" ile kapatıp süre kaydı oluşturmak, kişinin gerçekte bıraktığı saati bilmeden süre yazmak demektir. Karar: "tahmini süre gerçek süre yerine kullanılmaz; kayıt yoksa eksik denir". Sayaç kapatılmalı, ama kişi-saat kaydı **otomatik oluşturulmamalı**; yönetici incelemesine düşmeli.
4. **M13-08 yeni sütun gerektirmiyor.** Birim kataloğu sabit 5 birim (P.cs:3873). Boş listeyi açık listeye çevirmek yeterli. `AllUnits` bayrağı gereksiz karmaşıklık.

Kaçırılan maddeler (§4): personel seed'i ve ad eşleşmesiyle bağlama betiğinin her şema çalışmasında yeniden çalışması (M13-01 ve M13-09'u bozar), personel ucundan hesabın yeniden açılabilmesi (yetki atlatma), ve **çoklu birim** desteğinin olmaması (M13-02 Araç Takip ve POC için boş liste döndürür).

---

## 2. Karar tablosu

| ID | Karar | Öncelik | Kısa gerekçe |
|---|---|---|---|
| M13-01 | DEĞİŞTİR | P1 | Bağlama/ayırma P1 (kimlik zincirinin ilk halkası). Ad senkronu, kimlikle atama (M13-02 + M01-10) devreye girmeden yapılırsa teknisyenin eski işleri görünmez olur; sıralama düzeltilmeli. |
| M13-02 | DEĞİŞTİR | P1 | Doğru ve gerekli. Ancak "ek birim" alanı yok (`AdditionalDepartments` departmandır, birim değil). Araç Takip biriminde seed'de hiç personel yok; uç boş döner. M13-D03'e bağlanmalı. |
| M13-03 | DEĞİŞTİR | P2 | Gerekli. Sayaç otomatik süre kaydına dönüşmemeli; personel ucunun hesabı yeniden açması kapatılmalı; yeni uç yerine mevcut `status` ucu genişletilebilir. |
| M13-04 | DEĞİŞTİR | P3 | Fikir doğru, ama 47 kişilik yapıda ve S6 cevaplanmadan erken. Verilebilir izinler operasyonel izinlerle sınırlanmalı. |
| M13-05 | DEĞİŞTİR | P3 | Erişim gözden geçirme P3. "Kimlik tutarlılığı" listesi M13-10'a taşınmalı. `AccessReviews` tablosu yerine denetim kaydı kullanılmalı. |
| M13-06 | DEĞİŞTİR | P2 | Gerekli (A1-16). Nginx arkasında IP her zaman 127.0.0.1 görünür; `ForwardedHeaders` eklenmeli. |
| M13-07 | DEĞİŞTİR | P2 | Şef'e `operations.manage` önerisi çıkarılmalı. Diğer kısımlar doğru. Mevcut hesaplar değişmeyeceği için Depo için bugün de elle izin verilebiliyor (bloke edici değil). |
| M13-08 | DEĞİŞTİR | P2 | Sorun gerçek (P.cs:1797, 2807). Yeni `AllUnits` sütunu yerine boş listeyi açık listeye çeviren geçiş yeterli. Admin rol adı kuralı M13-12'de kalmalı (tekrar). |
| M13-09 | DEĞİŞTİR | P3 | Org şeması ve S11 cevabı gelmeden "Ekibim" kuralı belirsiz. Yalnız sütun ve geçiş hazırlanabilir. |
| M13-10 | DEĞİŞTİR | P1 | M01-10/M09-13 kimlik geçişi bunsuz yanlış kişiye süre yazar. Ayrı ekran yerine onaylı eşleme tablosu + betik yeterli. `SicilNo` S12'ye bağlı, isteğe bağlı. |
| M13-11 | DEĞİŞTİR | P2 | (a) sunucuda zorunlu değişim ve (b) mevcut şifre kontrolü gerçek açıklar. Kabul (5) bugün zaten sağlanıyor (P.cs:79 ve 92 aynı 401). Zamanlama farkı ele alınmalı. |
| M13-12 | DEĞİŞTİR | P1 — **KRİTİK** | Açık doğrulandı. Kural 4 İK'nın teknisyen kapatmasını engelliyor; kapatma için ayrı kural gerekli. Personel ucundan yeniden açma ve kullanıcı adı değiştirme de kapsama alınmalı. |
| M13-13 | KABUL | P1 — **KRİTİK** | Doğrulandı. Önce S eforlu kısım (pasif/sıfırlama → oturum düşür), ardından 60 sn yeniden okuma ve süre sınırı. |
| M13-14 | DEĞİŞTİR | P2 | Gerekli. "users.manage ile sayaç iptali" bir test değil, kod düzeltmesidir; M13-07'ye taşınmalı (P.cs:2084 ve 2170). |

---

## 3. Madde bazında ayrıntı

### M13-01 · DEĞİŞTİR · P1
**Doğrulama:** `PUT /api/personnel` `ErpUserId` almıyor ve adı kullanıcıya yansıtmıyor (P.cs:1834-1860). Bağlama yalnız oluşturma anında (P.cs:1784-1811) veya ad eşleşmesiyle SQL betiğinde (upd.sql:428-432) yapılıyor. `Personnel.ErpUserId` tekil değil (upd.sql:362). İddialar doğru.

**Sorun — sıralama:** Bugün görünürlük, sayaç ve manuel süre `user.FullName == AssignedName` metin eşleşmesine dayanıyor (P.cs:3398-3400, 3499-3500, 1945-1946, 2135). Ad senkronu M13-02/M01-10'dan önce yayımlanırsa, adı değişen teknisyen **eski atamalarının tümünü kaybeder** ve sayaç başlatamaz. Tasarımın kabul (3) maddesi "M13-02 sonrası" diyerek bunu kabul ediyor, ama bağımlılık zinciri ters yazılmış (M13-01 → M13-10 → M13-02 → M13-01).

**Sorun — seed:** Bağlantı kaldırılsa bile upd.sql:428-432 bir sonraki şema çalışmasında hesabı ad eşleşmesiyle **yeniden bağlar** (M13-D01).

**Düzeltilmiş hali:** İki aşama. (A, P1) Bağlama/ayırma uçları + filtreli UNIQUE index. Index öncesi mükerrer bağlantıları raporlayan tek sorgu yeterli; tam M13-10 ekranı beklenmez. (B, P2) Ad senkronu yalnız kimlikle atama (M13-02 `IsAssignedTo` + M01-10 `PersonnelId`) yayımlandıktan sonra açılır. O zamana kadar bağlı hesabı olan ve açık ataması olan personelin adı değiştirilmek istenirse sunucu uyarı verir ve onay ister. Bağımlılık: M13-D01, M13-12.

### M13-02 · DEĞİŞTİR · P1
**Doğrulama:** `personnelFallback` gerçek adları içeriyor (app.js:23-29). `state.users` yalnız `users.manage`, `state.personnel` yalnız `personnel.view` sahibine yükleniyor (app.js:145, 151). Şef şablonunda ikisi de yok (P.cs:3929). Şef/teknisyen ayrımı ünvan regex'i ile (app.js:1598, 1602). Doğru.

**Kaçırılan nokta:** Tasarım "ek birimi o birim olan personel" diyor, ama `Personnel` tablosunda ek **birim** alanı yok; `AdditionalDepartments` departman adlarıdır (upd.sql:355). Seed'de Araç Takip birimli hiç personel yok, POC şefi Ertuğrul Çakır'ın birimi Haberleşme (upd.sql:396-405). Uç `UnitCode`'a göre süzerse Araç Takip için **boş liste**, POC için şefsiz liste döner. Gömülü liste de kaldırılınca bu birimlerde atama yapılamaz (gerileme).

**Düzeltilmiş hali:** Tanım aynı. Ek kabul kriteri: "(7) Mobilite ve Araç Takip'te çalışan kişi her iki birimin atama listesinde görünür; POC şefi POC listesinde görünür." Uç `UnitCode` **veya** M13-D03'teki ek birimlere göre süzer. Uç ilk aşamada `PersonnelId` ve ad döndürür; yazma işlemi M01-10 tamamlanana kadar ad ile devam edebilir.

### M13-03 · DEĞİŞTİR · P2
**Doğrulama:** Personel pasif yapılınca hesap kapanıyor ve oturumlar düşüyor (P.cs:1890-1899). Açık atamalar ve sayaç dokunulmadan kalıyor. Doğru.

**Kaçırılan nokta (güvenlik):** Aynı uç `IsActive=true` gelince bağlı ERP hesabını da **yeniden aktif ediyor** (P.cs:1892-1895). Bunun için yalnız `personnel.manage` yeterli. Tasarım yalnız kullanıcı ekranından yeniden açmayı ele almış (M13-D02).

**Kaçırılan nokta (veri doğruluğu):** Kabul (3) "süre kaydı işten çıkış notuyla oluşur, sıfır sayılmaz" diyor. Sayacı onay anında kapatıp süre yazmak, kişinin gerçekte işi bıraktığı saati bilmeden süre üretir. Bu, "tahmini süre gerçek süre yerine kullanılmaz" kararına aykırı.

**Düzeltilmiş hali:** Önizleme ve tek transaction aynı. Açık sayaç `EndedAt=şimdi`, `StopReason='İşten çıkış'` ile kapatılır; **`WorkOrderTimeLogs` kaydı otomatik oluşturulmaz**. Oturum "İnceleme bekliyor" olarak işaretlenir. Yönetici gerçek bitiş saatini girerse süre kaydı oluşur; girmezse raporda "süre kaydı eksik" görünür. Personelin yeniden aktif edilmesi bağlı hesabı **açmaz**; hesap yalnız Admin tarafından ayrıca açılır. Mevcut `PATCH /api/personnel/{id}/status` ucu genişletilebilir; ayrı `offboard` ucu zorunlu değil. Bağımlılık: M13-13, M13-D02 (M13-02 yoksa açık işler ad eşleşmesiyle bulunur).

### M13-04 · DEĞİŞTİR · P3
**Doğrulama:** Kodda vekâlet yok. İddia doğru.

**Değerlendirme:** Teknik servis için gerçek ihtiyaç (şef izni) var. Ancak 2 şef 2'şer birimi yönetiyor ve toplam 47 personel var. Kalıcı izin + M13-06 denetim kaydı + M13-05 gözden geçirme kısa vadede aynı riski yönetir. S6 henüz cevaplanmadı. Oturum izinlerinin canlı hesaplanması (M13-13) önkoşul.

**Düzeltilmiş hali:** P3'e alınır. Uygulandığında vekâlette verilebilecek izinler **operasyonel izinlerle** sınırlıdır (`workorders.assign/plan/close/edit`, `maintenance.manage`, `workshop.manage`, birim ekleme). `users.*`, `finance.*`, `audit.view`, `*` vekâletle verilemez. En fazla 30 gün. Kabul kriterleri aynı.

### M13-05 · DEĞİŞTİR · P3
**Doğrulama:** `LastLoginAt` yok; kullanıcı listesinde yalnız rol, birim, durum var. Doğru.

**Değerlendirme:** KVKK kanıtı için değerli ama kullanıcı önceliğinde son sırada. "Kimlik tutarlılığı" listesi ise M13-10 geçişi için **gereken** bir çıktı; oraya taşınmalı. `AccessReviews` tablosu gereksiz: "Gözden geçirildi" işareti `SecurityAuditLog` içine `AccessReviewed` olayı olarak yazılabilir.

**Düzeltilmiş hali:** Yalnız erişim listesi (hassas izin sahipleri, şablondan sapma, 60+ gün giriş yok, pasif personele bağlı aktif hesap). İşaret denetim kaydına yazılır, ayrı tablo yok. Excel çıktısı mevcut rapor altyapısıyla. Kimlik listesi M13-10'da. Bağımlılık: M13-06, M13-07, M13-11 (`LastLoginAt`).

### M13-06 · DEĞİŞTİR · P2
**Doğrulama:** Denetim tablosu yok; yalnız `UpdatedAt` güncelleniyor (P.cs:273, 331, 350). Doğru.

**Kaçırılan nokta:** Uygulamada `UseForwardedHeaders` yok (kaynakta `ForwardedHeaders` / `RemoteIpAddress` geçmiyor). Linux kurulumunda nginx önde olduğu için kayıttaki IP her zaman 127.0.0.1 olur ve alan işe yaramaz.

**Düzeltilmiş hali:** Tanım aynı. Ek: yalnız yerel nginx'e güvenen `ForwardedHeaders` ayarı (KnownProxies = 127.0.0.1). Ek kabul: "(6) Ağdan yapılan girişte kayıttaki IP istemcinin IP'sidir, 127.0.0.1 değildir." Saklama süresi S8'e bağlı.

### M13-07 · DEĞİŞTİR · P2
**Doğrulama:** `operations.manage`, `warehouse.manage`, `finance.costs.manage` Admin dışında hiçbir şablonda yok (P.cs:3921-3935). Depo stok hareketi `warehouse.manage` istiyor (Ops.cs:179, 190). Teknisyen kapsamı rol adı metnine bağlı (P.cs:3398, 3499, 2120). Bilinmeyen rol için `workorders.view` (P.cs:2804). v15.sql:147-170 rol adına göre toplu izin ekliyor. Hepsi doğru.

**Hata:** "Şef şablonuna `operations.manage` (bekleme nedeni)" önerisi koda uymuyor. Bekletme/serbest bırakma `operations.manage` **veya** `workorders.edit` ile açık (Ops.cs:133, 149); Şef'te `workorders.edit` var. `operations.manage` tek başına yalnız şirket geneli SLA hedefini değiştiren uçta kullanılıyor (Ops.cs:124). Şefe vermek yetki genişletmesidir.

**Öncelik notu:** Kararla uyumlu olarak yeni şablon mevcut hesaplara dağıtılmıyor. Mevcut Depo hesaplarına izni yine yönetici elle verecek; bu bugün de ekrandan yapılabiliyor. Bu yüzden bloke edici değil, P2.

**Düzeltilmiş hali:** (a) Depo'ya `warehouse.manage`; Teknik Servis Müdürü'ne `operations.manage` ve `finance.costs.manage` (VARSAYIM). **Şef'e `operations.manage` eklenmez.** (b)-(f) aynı. Ek: (g) `users.manage` iznin operasyonel uçlarda kullanılması kaldırılır: sayaç iptali P.cs:2084 ve süre kaydı iptali P.cs:2170 yalnız `workorders.assign` ister (M09-16 ile ortak; M13-14'ten taşındı). Ek kabul: "(6) Şef şablonlu hesap `PUT /api/ops/sla/{priority}` çağrısında 403 alır, bekletme işleminde 200 alır." Kabul (5) ancak M13-D01/A2-12 ile sağlanabilir; aksi halde v15.sql bir sonraki şema çalışmasında kaldırılan izinleri geri ekler.

### M13-08 · DEĞİŞTİR · P2
**Doğrulama:** Kullanıcı uçları boş birimi tüm birimlere çeviriyor (P.cs:216, 256-258). Personel ile hesap açma boş liste yazıyor (P.cs:1797). `UnitAllowed` boş listeyi "tümü" sayıyor (P.cs:2807). Eğitim tarafında da aynı varsayım var (P.cs:2801). Personel listesi tüm şirketi gösteriyor (P.cs:1742-1747). Doğru.

**Değerlendirme:** Birim kataloğu kodda sabit 5 öğe. Yeni bir `AllUnits` sütunu ve iki anlamlı durum yerine, boş listeyi açık listeye çevirmek daha basit ve daha az hata riskli.

**Düzeltilmiş hali:** (a) Geçiş betiği `AllowedUnits=''` olan hesapları 5 birimin açık listesine çevirir ve listeyi raporlar (erişim korunur). (b) `UnitAllowed` ve P.cs:2801 artık boş listeyi "hiçbiri" sayar. (c) Hesap açan tüm uçlarda birim boşsa 400. (d) `GET /api/personnel` birim kapsamına göre süzülür; birimi boş personel (yönetim, İK, idari) yalnız `personnel.manage` sahibine görünür; `Notes` alanı yalnız `personnel.manage` sahibine döner (KVKK veri azaltma). (e) Bağlı personelin birimi hesap birimlerinde yoksa uyarı. Admin rol adı kuralı M13-12'de kalır. Veri değişikliği: yok (yalnız geçiş betiği).

### M13-09 · DEĞİŞTİR · P3
**Doğrulama:** `ManagerName` metin (upd.sql:358). Doğru.

**Değerlendirme:** Organizasyon şeması gelmedi ve "şef kendi ekibini mi, tüm birimi mi görür" sorusu (S11) açık. Şef bugün tüm birimin işlerini görüyor ve bu çalışan bir düzen. "Ekibim" süzgecini bugün tasarlamak varsayım üstüne kurulur. Ad senkronu (M13-01) varken ad metni pratikte nadiren kopar.

**Düzeltilmiş hali:** Org şeması ve S11 cevabı gelene kadar ertelenir. Geldiğinde: `ManagerPersonnelId` sütunu, ada göre geçiş (eşleşmeyen raporlanır, tahmin yok), döngü kontrolü. "Ekibim" görünümü S11 cevabına göre ayrıca tanımlanır.

### M13-10 · DEĞİŞTİR · P1
**Doğrulama:** Atama ve süre kayıtları ad metniyle (P.cs:3341-3342, 2153); personel tekilliği yok, seed tekilliği yalnız ada göre (upd.sql:425). Doğru.

**Değerlendirme:** M01-10 (P1) ve M09-13'ün kimliğe geçişi bu eşleme olmadan ya yanlış kişiye süre yazar ya da geçmişi koparır. Bu yüzden P1. Ancak 47 personel ve yaklaşık 25 farklı teknisyen adı için ayrı bir ekran fazla. Onaylı eşleme tablosu + betik yeterli.

**Düzeltilmiş hali:** (1) Betik, tüm ad kaynaklarındaki (`AssignedName`, `TimeLogs.TechnicianName`, `LiveSessions.TechnicianName`, `ManagerName`) her ayrı ad için kayıt sayısı ve normalize öneri içeren bir `PersonnelNameMap(SourceName, PersonnelId NULL, Status, ApprovedBy, ApprovedAt)` tablosu üretir ve Excel'e verir. (2) İK/Admin onaylı satırlar doldurulur; yalnız onaylı satırlar uygulanır; metin korunur. (3) Eşleşmeyenler "eşleşmedi" kalır ve sayılır. (4) Kimlik tutarlılığı listesi (hesabı olmayan saha personeli, personeli olmayan hesap, ad uyuşmazlığı) bu betiğin raporudur (M13-05'ten taşındı). (5) İdempotent; öncesinde yedek talimatı. (6) `SicilNo` isteğe bağlı ve S12 cevabına bağlı; girilirse tekil (409). (7) Aynı birimde aynı adla ikinci aktif personel onay ister. Bağımlılık: M13-D01, M01-10 sütunları.

### M13-11 · DEĞİŞTİR · P2
**Doğrulama:** Zorunlu değişim yalnız istemcide (app.js:2040); sunucuda hiçbir uç `MustChangePassword` bakmıyor. `change-password` mevcut şifreyi sormuyor (P.cs:114-137, istek kaydı P.cs:3808). Geçici şifre `prompt()` ile yöneticiden (app.js:2028). Deneme sınırı yok. Doğru.

**Hatalı iddia:** Kabul (5) "var olan ve olmayan kullanıcı için aynı hata" bugün **zaten sağlanıyor**: iki durumda da `Results.Unauthorized()` dönüyor (P.cs:79, 92). Gerçek fark **zamanlamada**: kullanıcı yoksa veya pasifse PBKDF2 (120.000 tur) çalışmadan hemen dönüyor.

**Düzeltilmiş hali:** (a)-(d) aynı. (e) Şifre değişince kullanıcının **diğer** oturumları düşer. (f) Kilit: 5 hata / 15 dk; nginx arkasında IP güvenilir değilse (M13-06) kilit kullanıcı adı bazlıdır. Kabul (5) şöyle değişir: "Var olmayan, pasif ve yanlış şifreli kullanıcı için yanıt metni ve süre farkı ölçülebilir değildir (sahte hash ile doğrulama yapılır)." Alt öncelik: (a) ve (b) aynı sürümde M13-12/13 ile; kalan kısım P2.

### M13-12 · DEĞİŞTİR · P1 — KRİTİK
**Doğrulama:** Doğrulandı. `POST/PUT /api/users` izinleri katalogla karşılaştırmıyor (P.cs:213-215, 253-255); `RoleName` serbest. Hedef kontrolü yok (P.cs:321-357). Personel ucunda hesap açma aynı açığı taşıyor (P.cs:1795-1797). `IsAdmin` rol adına bakıyor (P.cs:2805). İK şablonunda `users.manage` var (P.cs:3934). Bir İK hesabı kendine `*` verebilir ve fiyat/maliyet dahil tüm veriye erişir.

**İç çelişki:** Kural 4, "hedefte işlemi yapanda olmayan bir izin varsa pasifleştirme 403" diyor. İK'da `workorders.*` yok; her teknisyende var. Bu kuralla İK hiçbir teknisyeni kapatamaz; tasarımın §2.2'deki "erişimi kapatmak kolay olmalı" ilkesi ve M13-03 bozulur.

**Kaçırılan yollar:** (i) Personel ucu `IsActive=true` ile bağlı hesabı yeniden açıyor (P.cs:1892-1895) — yalnız `personnel.manage` ile. (ii) `PUT /api/users` hedefin `Username` alanını değiştirebiliyor; istemcide yalnız `admin` adı salt okunur (app.js:1236), sunucuda kontrol yok. (iii) Personel durum ucunda "kendini pasif yapamazsın" kontrolü yok.

**Düzeltilmiş hali:** Tek sunucu kontrolü:
1. İzinler ve rol adı katalogda olmalı (400). `*`, `users.manage`, `audit.view` ve `RoleName="Admin"` yalnız `*` sahibince verilebilir.
2. **Verme/düzenleme/şifre sıfırlama/kullanıcı adı değiştirme/hesabı yeniden açma:** verilen izin ve birimler işlemi yapanın alt kümesi olmalı; hedef işlemi yapandan genişse 403.
3. **Kapatma (pasifleştirme, işten çıkış):** `personnel.manage` veya `users.manage` sahibi herhangi bir hesabı kapatabilir; **yalnız** hedefte `*` veya `users.manage` varsa işlemi yapanın `*` olması gerekir.
4. Kişi kendi izinlerini, birimlerini değiştiremez ve kendini pasifleştiremez (her iki uçta).
5. Son aktif `*` hesabı pasifleştirilemez ve düşürülemez.
6. `IsAdmin()` rol adına bakmaz.
7. Personel aktifleştirme bağlı hesabı açmaz (M13-D02).

Kabul (1)-(8) aynı; ek: "(9) Yalnız `personnel.manage` sahibi İK, teknisyen personelini pasifleştirir (200) ve hesabı kapanır; Admin'i pasifleştiremez (403)." "(10) `users.manage` sahibi, Admin hesabının kullanıcı adını değiştiremez (403)."

### M13-13 · KABUL · P1 — KRİTİK
**Doğrulama:** Doğrulandı (P.cs:21, 94-96, 321-357, 2821-2825). Pasifleştirilen veya şifresi sıfırlanan hesabın belirteci süresiz çalışıyor. İşten çıkış senaryosunda müşteri, cihaz ve personel verisine erişim sürer; KRİTİK işareti yerinde.

**Uygulama notu:** İki adımda yayımlanabilir. Önce S eforlu kısım: `users/status` ve `reset-password` uçlarında hedefin oturumlarını düşürmek (personel ucundaki P.cs:1897-1898 kalıbıyla aynı). Ardından 60 saniyelik veritabanı yeniden okuması ve hareketsizlik/mutlak süre (S5 cevabına göre). `SecurityStamp` gereksiz; tek sunucu ve bellek içi oturum için 60 sn yeniden okuma yeterli.

### M13-14 · DEĞİŞTİR · P2
**Doğrulama:** Test projesi yok. Doğru.

**Değerlendirme:** Gerekli. Kullanıcı bir iki gün sonra GitHub'a geçecek; derleme hattına girecek ilk testler bunlar olmalı. `WebApplicationFactory` için top-level `Program` sınıfının erişilebilir olması (`public partial class Program {}`) ve test DB'si için şema bayrağının (P.cs:26) açılması gerekir. Bunlar talimatta yazılmalı. "users.manage ile sayaç iptali" ise test değil, kod düzeltmesidir; M13-07(g)'ye taşındı.

**Düzeltilmiş hali:** Test projesi + matris; kabul (1)-(3) aynı. Ek: "(4) Testler yerelde `DengeERP_TEST` üzerinde tek komutla (`dotnet test`) çalışır; bağlantı dizesi ortam değişkeninden okunur, kaynakta sır yoktur." Sayaç iptali maddesi çıkarıldı.

---

## 4. Tasarımcının kaçırdığı maddeler

### M13-D01 · HATA · P1 · Personel seed'i ve ad eşleşmesiyle bağlama her şema çalışmasında tekrar ediyor
- **Mevcut durum:** upd.sql:372-425, 47 gerçek kişiyi `WHERE NOT EXISTS (... p.FullName=o.FullName)` ile ekliyor. upd.sql:428-432, hesabı olmayan personeli `u.FullName=p.FullName` ile bağlıyor. `RunDatabaseSetupOnStartup=true` iken tüm `.sql` dosyaları her açılışta çalışıyor (P.cs:26-31) ve sürüm tablosu yok (A2-12, A3-04).
- **Sonuç:** (1) Adı düzeltilen personel (ör. "Ali Guler" → "Ali Güler"), sonraki çalışmada eski adla **ikinci aktif personel** olarak geri gelir ve atama listelerine düşer. (2) M13-01 ile kaldırılan bağlantı ad eşleşmesiyle **yeniden kurulur**. (3) v15.sql:147-170, kaldırılan izinleri geri ekler. A2-12 bağlama ve izin kısmını not etmiş, ama personelin yeniden eklenmesini ve M13 maddelerine etkisini ele almamış. Ayrıca A4-02 (GitHub öncesi gerçek veri) upd.sql:372-420'deki **ad, ünvan ve yönetici hiyerarşisini** listelememiş.
- **Kabul:** (1) Personel seed'i ve ad eşleşmesiyle bağlama bir kerelik veri betiğine taşınır ve normal şema çalışmasında çalışmaz. (2) Adı değiştirilen personel, şema yeniden uygulandığında çoğalmaz. (3) Kaldırılan bağlantı ve izin geri gelmez. (4) Gerçek ad listesi GitHub deposuna girmez (deponun dışında, İT'nin sakladığı veri betiği). (5) Test DB'si için sahte adlı seed kullanılır.
- **Roller:** Geliştirici, İT. **Efor:** S. **Bağımlılık:** A2-12/A3-04 (`SchemaVersions`); M13-01, M13-07(f), M13-10 bundan önce yayımlanmamalı.

### M13-D02 · GÜVENLİK · P1 · Personel ucundan ERP hesabının yeniden açılması (yetki atlatma)
- **Mevcut durum:** `PATCH /api/personnel/{id}/status` `IsActive=true` gelince bağlı hesabı `IsActive=1` yapıyor (P.cs:1890-1895). Yalnız `personnel.manage` isteniyor (P.cs:1866). Hesap eski izinleriyle (fiyat/maliyet dahil olabilir) geri açılır.
- **Sonuç:** M13-07 İK'dan `users.manage` iznini kaldırsa bile İK, Admin'in güvenlik nedeniyle kapattığı bir hesabı personel ekranından açabilir. M13-12 bu yolu listelememiş. Aynı uçta kişinin kendini pasifleştirme kontrolü de yok.
- **Kabul:** (1) Personel aktifleştirildiğinde bağlı hesap pasif kalır; yanıt "hesap ayrıca açılmalı" der. (2) Hesabı açma yalnız `users.manage` + M13-12 kuralı ile (işten çıkış sonrası yalnız Admin). (3) Kişi kendi personel kaydını pasifleştiremez (400). (4) İşlem denetim kaydına yazılır (M13-06 varsa).
- **Roller:** `personnel.manage`, `users.manage`. **Efor:** S. **Bağımlılık:** Yok; M13-12 ile aynı sürüm.

### M13-D03 · VERİ · P1 · Personelin birden fazla birimde çalışabilmesi
- **Mevcut durum:** `Personnel.UnitCode` tek birim (upd.sql:357). `AdditionalDepartments` departman adı tutuyor, birim değil (upd.sql:355). Seed'de Araç Takip birimli personel yok. Gömülü liste ise Araç Takip'i Mobilite ekibiyle, POC'u Haberleşme şefiyle dolduruyor (app.js:26-28). Tasarım belgesi S11'de bu ortaklığı soruyor ama veri modelinde karşılığı yok.
- **Sonuç:** M13-02 gömülü listeyi kaldırıp `UnitCode` ile süzerse Araç Takip'te atanabilir kişi kalmaz, POC'ta şef görünmez. İş akışı bloke olur.
- **Kabul:** (1) Personel kartında ek birimler (katalogdaki 5 birimden) seçilebilir. (2) Mobilite + Araç Takip ekli kişi iki birimin atama listesinde görünür. (3) Geçiş, gömülü listedeki birim–kişi ilişkisini **öneri** olarak raporlar; İK onaylar, otomatik yazılmaz. (4) M13-08 personel birim filtresi ek birimleri de dikkate alır.
- **Roller:** Düzenleme `personnel.manage`; okuma `workorders.assign/plan`. **Veri:** `Personnel.AdditionalUnits NVARCHAR(400) NULL` (mevcut pipe kalıbıyla) — ayrı tablo bu ölçekte gereksiz. **Efor:** S. **Bağımlılık:** M13-02 ile aynı sürüm.

---

## 5. Önerilen uygulama sırası (düzeltilmiş)

| Sıra | Maddeler | Not |
|---|---|---|
| 0 — Hemen (S, kritik) | M13-12, M13-13 (adım 1), M13-D02 | Veri sızıntısı ve yetki atlatma. Kullanıcının c→b→a sırasından bağımsız. |
| 0 — GitHub öncesi | M13-D01 | Gerçek adların depoya girmemesi ve seed'in kimlik verisini ezmemesi. A2-12/A4-02 ile birlikte. |
| 1 — Kimlik altyapısı (c) | M13-01 (A), M13-02, M13-D03, M13-10 | M01-10, M02-03, M09-13 bunun üzerine kurulur. |
| 2 — Eksikler (b) | M13-03, M13-07, M13-08, M13-01 (B), M13-13 (adım 2) | |
| 3 — Güvenlik/üretim (a) | M13-06, M13-11, M13-14 | M13-14 GitHub hattı kurulunca ilk testler. |
| 4 — Sonra | M13-04, M13-05, M13-09 | S6, S11 ve org şeması cevabına bağlı. |

## 6. Varsayımlar ve açık noktalar
- Rol önerileri (Müdür'e `operations.manage`/`finance.costs.manage`, İK ve Müdür Yardımcısından `users.manage` çıkarılması) **varsayımdır**; org şeması gelince doğrulanmalıdır.
- S3 (her teknisyene hesap) cevabı M13-02 ve M13-10'u etkiler: hesabı olmayan personel atanabilir ama sayaç kullanamaz.
- Satır numaraları V1.20.1 orijinal kaynağına göredir. Kaynak koda dokunulmadı.
