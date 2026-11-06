# M09 — Saha / Zaman Takibi ve Mobil Teknisyen Görünümü: Bağımsız Denetim Raporu

> **Tarih:** 21 Ekim 2026 · **Denetlenen belge:** `09_saha_zaman_tasarim.md` · **Baz kod:** V1.20.1 (`kaynak/V1_20_1_orijinal/DengeERP.Api`, salt okunur; kaynak koda dokunulmadı)
> **Yöntem:** Her maddenin "mevcut durum" iddiası `Program.cs` (1908-2189, 495-614, 2804-2808, 3385-3502, 3641-3680, 3871-3935), `OpsSuite.cs` (1-110, 214-236), `wwwroot/app.js` (1436-1567, 1608-1664), `wwwroot/ops120.js` ve `linux/*` üzerinden satır satır kontrol edildi. Ayrıca `01_denetim/A1`, `A2`, `A4` raporlarıyla mükerrerlik arandı.
> **Kısaltmalar:** `P.cs` = `Program.cs`, `Ops.cs` = `OpsSuite.cs`.
> **Öncelik ölçeği:** P1 = iş akışını bloke eden veya veri doğruluğunu bozan · P2 = operasyonel kalite · P3 = sonra.

---

## 1. Özet

| Karar | Adet | Maddeler |
|---|---|---|
| KABUL | 6 | M09-01 (P1), M09-02 (P1), M09-06 (P2), M09-09 (P2), M09-11 (P1), M09-13 (P2) |
| DEĞİŞTİR | 10 | M09-03, M09-04, M09-05, M09-07, M09-08, M09-10, M09-12, M09-14, M09-15, M09-16 |
| RET | 0 | — |
| Eklenen | 3 | M09-D01 … M09-D03 |

**Genel değerlendirme:** Tasarım kodu doğru okumuş. Satır referanslarının neredeyse tamamı doğru. Hata iddiaları (M09-09 durum listesi tutarsızlığı, M09-11 atama kilidi, M09-12 saat kaynağı, M09-15 tam tablo okuması) kodda doğrulandı. Kapsam dışı (satış, muhasebe, İK iş takibi, Logo/Flowick) madde yok. Bordro, mola ve "eksik ≠ 0" kararlarına uyulmuş. Zayıf noktalar şunlar:

1. **Gözden kaçan bir kilitlenme var: 18 saat sınırı.** Cuma akşamı kapatılmayan sayaç pazartesi sabahı 18 saati aşar. `finish` 400 döner (P.cs:2024-2025). Açık oturum kişi başına tek aktif sayaç kuralına takıldığı için teknisyen yeni işte de sayaç başlatamaz (P.cs:1955-1958). Bu, yönetici gelip iptal edene kadar teknisyenin bütün gününü bloke eder. M09-05 bunu yalnızca yönetici tarafından çözüyor; teknisyenin kendi kendini kurtarabileceği bir yol yok (**M09-D01**).
2. **Kısmen yanlış gerekçeler var.** M09-14'teki "ops listesinde 0 dk görünür" iddiası yanlış: `recordedMinutes` API'de 0 dönüyor (Ops.cs:88) ama `ops120.js` bu alanı hiçbir yerde göstermiyor. Gerçek etki maliyet ekranında (işçilik 0,00 TL, fark şişik) ve Excel'de (`Gerçek Kişi-Saat` hücresi "0.00", P.cs:3678). M09-01'deki "ziyaret bilgileri WhatsApp ile iletiliyor" kısmen yanlış: adres, saha yetkilisi, telefon ve ulaşım notu iş emri penceresinde zaten var (app.js:1625). Eksik olan, bunların mobil listede ve tıklanabilir (`tel:`, harita) biçimde olmaması. M09-02 kabul (4)'teki çift basış koruması da büyük ölçüde mevcut: düğme kilitleniyor (app.js:1530), ikinci `finish` 409, ikinci `change` 400 dönüyor (P.cs:2013, 2019-2023).
3. **Mükerrerlik.** M09-12 (saat dilimi), `A4-06` ve `A2-05` ile aynı sorunu tekrarlıyor. Altyapı tarafı (TZ, NTP) orada çözülmeli. Bu modülde yalnızca zaman kaydına özgü kısım kalmalı. M09-16'nın gerekçesi (`users.manage` ile İK'nın sayaç iptal etmesi) gerçek, ama `users.manage` sahibi kendine istediği izni zaten verebiliyor (envanter §52, A1). Bu iki uçtan `users.manage`'ı çıkarmak güvenlik kazancı sağlamaz; asıl çözüm A1/M13'teki "verilebilir izin" kuralıdır.
4. **Aşırı mühendislik eğilimi.** İki yeni izin anahtarı (`timetracking.manage`, `timetracking.team.view`), ayrı "disiplin raporu" sayfası ve "aynı ziyaret" doğrulaması, ziyaret kavramı henüz bir tablo olmadan (M02 denetimi: kart `RouteGroupNo` ile değil birim+müşteri+saha+şehir ile gruplanıyor) gereksiz karmaşıklık getiriyor. Mevcut `workorders.assign` izni "zaman yönetimi" için yeterli; Şef ve Müdür şablonlarında zaten var, Teknisyen'de yok (P.cs:3925-3930).
5. **Test eksikliği.** Proje geçmişi V1.14 canlı sayacın "gerçek zaman kayıtlarının uçtan uca testi eksik" olduğunu açıkça yazıyor (geçmiş belgesi §V1.14, §6 test listesi). Tasarım serializable transaction'lara, çakışma kurallarına ve yeni uçlara dokunan 10'dan fazla değişiklik öneriyor, ama otomatik test seti önermiyor (**M09-D03**).

**Önerilen ilk dilim (şema değişikliği yok veya çok az):** M09-11 → M09-D01 → M09-09(b,c) → M09-D03 (test iskeleti) → M09-02 → M09-01 → M09-14. Ardından M09-08 (tek şema scripti: `SourceType`, `ManualReason`, `VoidReason`, `SourceSessionId`) ve buna bağlı M09-05, M09-03, M09-04 gelir. Linux geçişinden önce M09-12 (A4-06 ile birlikte) zorunludur.

---

## 2. Madde bazında değerlendirme

### M09-01 · YENİ · Mobil "Benim İşlerim" ekranı ve tek sayfa iş kartı — **KABUL · P1**

**Doğrulama:**
- `ops120.js:7-8` doğru: liste rol adı `Teknisyen` ise isimle süzülüyor, diğer rollerde tüm açık işler. Sıralama, gruplama ve sayaç bandı yok. "İşi Aç" (`data-open`) masaüstü penceresini açıyor.
- Sayaç kartı, uzun iş emri penceresinin ortasında; atama, durum, teklif kartlarından sonra geliyor (app.js:1628). Telefonda kullanımı gerçekten zor.
- **Düzeltme:** Adres, saha yetkilisi, telefon ve ulaşım notu iş emri penceresinde zaten var (app.js:1625). Eksik olan mobil listede gösterilmeleri ve `tel:` / harita bağlantısı olarak çalışmaları.

**Neden gerekli:** Bu modülün bütün değeri sahadan gerçek süre verisi gelmesine bağlı. Sayaç telefondan kolay kullanılamazsa M09-04, 06 ve 07'nin hiçbiri anlamlı veri üretmez. Kullanıcının (c) önceliğine de uygun.

**Notlar:**
- Gruplama anahtarı M02-08 ile aynı olmalı. M02 denetimi takvim kartının `RouteGroupNo` ile değil birim+müşteri+saha+şehir ile gruplandığını tespit etti. Aynı anahtar kullanılmazsa takvimdeki ziyaret ile mobildeki ziyaret farklı görünür.
- Şef için "bana atanan" tanımı netleştirilmeli: Şef ataması `AssignmentRole='Şef'` satırıdır. Canlı sayaç ise yalnızca `AssignmentRole='Teknisyen'` satırı varsa başlıyor (P.cs:1943-1948). Sahada çalışan şef ayrıca teknisyen olarak atanmazsa sayaç başlatamaz. Bu bir kullanıcı sorusu olarak eklenmeli.
- `state.workOrders` istemciye **tüm** iş emirlerini yüklüyor (`LoadWorkOrdersAsync` filtre yok, P.cs:3441-3493). Mobil hatta bu ekranın açılış süresi M09-15 ile birlikte ele alınmalı.

### M09-02 · YENİ · Tek dokunuşla saha akış düğmeleri — **KABUL · P1**

**Doğrulama:** Akış yalnızca açılır liste + "Faaliyeti Değiştir" ile yürüyor (app.js:1461-1464, 1504). `change` ucu var (P.cs:1985), `resume` ve bekleme nedeni yok. Doğru.

**Notlar (tanımı değiştirmeyen):**
- Kabul (4) büyük ölçüde zaten sağlanıyor: istemci düğmeyi kilitliyor (app.js:1530), ikinci `finish` 409 (P.cs:2013), ikinci `change` aynı faaliyet için 400 veya 1 dk kuralıyla 400 (P.cs:2019-2023). Bu kabul maddesi yeni geliştirme değil, **regresyon testi** olarak M09-D03'e taşınmalı.
- Bekleme nedeni listesi, `OpsHolds` için kullanılan listeyle aynı olmalı (Malzeme / Müşteri Onayı / Teklif / Personel / Diğer, ops120.js:73). Aksi halde aynı iş için iş emri düzeyinde ve zaman bölümü düzeyinde iki farklı neden sözlüğü oluşur.
- `resume` sunucuda "bu kişinin bu iş emrindeki son mola dışı bölümünün faaliyeti" ile hesaplanmalı; istemci hafızasına güvenilmemeli (sayfa yenilenince kaybolur).

### M09-03 · YENİ · Ziyaret içinde sonraki iş emrine sayacı taşıma — **DEĞİŞTİR · P2**

**Doğrulama:** Böyle bir uç yok. 1 dk alt sınırı var (P.cs:2022). 17 cihazlık PB ziyaretinde Bitir + aç + Başlat döngüsünün süreyi tek işe yığmaya ittiği gerekçesi makul.

**Sorunlar:**
- **"Aynı ziyaret" doğrulanamaz.** Ziyaret ayrı bir tablo değil. `RouteGroupNo` serbest metin ve tek başına taşınan işte eski değer kalabiliyor (M02 denetimi). Kabul (2) "farklı ziyaretteki hedef 400" bu yüzden güvenilir biçimde uygulanamaz ve sahada yanlış reddetme üretir.
- Hedef herhangi bir atanmış açık iş olduğunda bu işlem "Bitir + hemen Başlat" ile aynıdır, sadece boşluk bırakmaz. Ek risk yaratmaz; ziyaret kısıtı gereksiz.
- Yeni uç yerine mevcut `change` ucuna isteğe bağlı `targetWorkOrderId` eklenmesi yeterli. Aynı transaction ve kilitler zaten orada (P.cs:2004-2075).

**Düzeltilmiş tanım (revised):** Mevcut `POST /live-timer/change` isteğine isteğe bağlı `targetWorkOrderId` eklenir. Verilirse açık bölüm kapatılır ve hedef işte aynı (veya seçilen) faaliyetle, aynı `end` zamanında yeni bölüm açılır. Hedef iş kişinin teknisyen olarak atandığı, kapalı/iptal/çözülmüş olmayan bir iş olmalıdır. Mobil ziyaret kartında "Sonraki Cihaza Geç" düğmesi olarak görünür ve yalnızca aynı kartta gruplanan işleri önerir (kısıt arayüzde, sunucuda değil). **Kabul:** (1) A'daki bölümün bitişi B'deki bölümün başlangıcına eşittir. (2) Atanmamış hedef 400. (3) Kapalı/İptal/Çözüldü hedef 400. (4) Hata olursa iki taraf da değişmez (tek transaction). (5) Yol süresinin hangi işe yazılacağı kullanıcı kararı gelene kadar ilk iş emrinde kalır.

### M09-04 · YENİ · Teknisyen "Bugünüm" özeti ve gün sonu eksik kontrolü — **DEĞİŞTİR · P2**

**Doğrulama:** Sayfada yalnızca dönem toplamları var (app.js:1508). Kişiye ve güne özel eksik listesi yok. Doğru.

**Sorun:** "Bugün işlem görmüş" tanımı bakım formu güncellemesini de içeriyor. Bu, bakım formu tablolarına ek sorgu ve tanım belirsizliği getirir. Durum geçmişi (`InsertStatusLogAsync`, kullanıcıyla birlikte yazılıyor) ve plan tarihi yeterli ve daha net bir kaynak.

**Düzeltilmiş tanım (revised):** "Bugünüm" sekmesi kişinin bugünkü bölümlerini (canlı + manuel), toplamları ve molayı (hariç) gösterir. "Süre kaydı eksik" listesi şu işleri içerir: kişinin teknisyen olarak atandığı **ve** (planı bugün olan **veya** kişinin bugün durumunu değiştirdiği) **ve** kişinin bugün hiç gerçek süre kaydı olmayan işler. Her satırda elle giriş bağlantısı bulunur. Saat çizelgesindeki boşluklar yalnızca bilgi olarak gösterilir. **Kabul:** tasarımdaki (1)-(3) aynen geçerlidir. M09-13 gelmeden isimle eşleştirme kabul edilir.

### M09-05 · YENİ · Unutulan sayaç uyarısı ve yönetici "iptal et ve düzelt" akışı — **DEĞİŞTİR · P2**

**Doğrulama:** Ops uyarılarında sayaç türü yok (Ops.cs:26-37, 38-65). İptal yalnızca oturumu kapatıyor; transaction yok, süre kaydı oluşmuyor (P.cs:2080-2102). Doğru. Uyarı anahtarları tarih içerdiği için "aynı gün tekrar çıkmaz" davranışı mevcut `ack` altyapısıyla zaten sağlanır (Ops.cs:32-34, 99).

**Sorunlar:**
- Yeni `timetracking.manage` izni gereksiz (bkz. M09-16). `workorders.assign` yeterli.
- Teknisyenin kendi unuttuğu sayacı düzeltememesi asıl kilitlenme kaynağı. Bu, ayrı bir madde olarak P1 seviyesinde ele alınmalı (**M09-D01**). M09-05 yönetici tarafını tamamlar.

**Düzeltilmiş tanım (revised):** (a) Ops uyarılarına "Uzun açık sayaç" türü eklenir (varsayım: 10 saat veya başlangıç günü bugünden önce). Şef ve Müdür görür. Teknisyene girişte banner gösterilir ve M09-D01 akışına yönlendirilir. (b) Yönetici iptal penceresine isteğe bağlı "Gerçek bitiş saati" eklenir. Doldurulursa iptal ve `SourceType='Yönetici Düzeltmesi'`, `SourceSessionId=<oturum>` kaydı tek transaction'da oluşur. Yetki: `workorders.assign`. **Kabul:** tasarımdaki (1)-(4) aynen; ek olarak (5) mola türündeki oturum düzeltilirse süre kaydı oluşmaz.

### M09-06 · YENİ · İş emri zaman çizelgesi ve türetilmiş saha metrikleri — **KABUL · P2**

**Doğrulama:** İş emrinde düz tablo ve toplam var (app.js:1639-1640). Excel'de "SÜRE KAYDI YOK / Kayıtlı" ayrımı var (P.cs:3678), "Kısmi" yok. Doğru.

**Notlar:**
- Kayıt olmayan satırda Excel "Gerçek Kişi-Saat" hücresine bugün `0.00` yazıyor (P.cs:3647, 3678). Bu madde kapsamında bu hücre **boş** bırakılmalı ve durum sütunu "Eksik" demeli. "Eksik ≠ 0" kararının Excel'deki karşılığıdır.
- "Tam/Kısmi" atama listesine göre hesaplanır. M01-10 gelene kadar isimle eşleştirme kabul edilebilir; bağımlılık zorunlu değil, önerilir.

### M09-07 · YENİ · Zaman verisi disiplin raporu — **DEĞİŞTİR · P3**

**Doğrulama:** Yok; kaynak alanı olmadığı için hesaplanamıyor. Doğru.

**Sorun:** Ayrı bir rapor sayfası ve Excel sayfası bu aşamada gereğinden fazla. Organizasyon şeması gelmeden "şef bazında" kırılım da varsayıma dayanıyor. Asıl ihtiyaç kişi-saat tablosunun yanında güvenilirlik göstergesi.

**Düzeltilmiş tanım (revised):** Mevcut "Personel / Kişi-Saat Dağılımı" tablosuna (app.js:1512) üç sütun eklenir: Canlı oranı (%), Manuel kayıt sayısı (gecikmeli olanlar ayrıca), İptal/düzeltilen sayaç sayısı. Aynı sütunlar Excel'deki personel sayfasına eklenir. Ayrı sayfa açılmaz. **Kabul:** tasarımdaki (1)-(3). M09-08'e bağlıdır.

### M09-08 · VERİ · Manuel kayıt kuralları — **DEĞİŞTİR · P1**

**Doğrulama:**
- Gün sınırı yok, yalnızca gelecek kontrolü var (P.cs:2124-2127). Doğru.
- Manuel kayıtta yalnızca çalışan sayaç ve diğer TimeLogs kontrol ediliyor. Tamamlanmış mola oturumları (`WorkOrderLiveSessions`, `ActivityType='Mola / Ara'`) kontrol edilmiyor (P.cs:2139-2151). Doğru; molanın üstüne yazılan manuel kayıt molayı kişi-saate sokar. Bu, "mola dahil değil" kararını delen bir veri doğruluğu hatası.
- İptalde gerekçe yok, iptal eden kişi ismiyle tutuluyor (P.cs:2166-2180). Doğru.
- "Giren" bilgisi API'de var (`CreatedByName`, P.cs:3431), ama iş emri tablosunda gösterilmiyor (app.js:1639). Doğru.

**Sorunlar:**
- `timetracking.manage` yerine `workorders.assign` kullanılmalı (bkz. M09-16).
- `SourceType` için `DEFAULT N'Manuel'` tehlikeli: canlı akıştaki INSERT (P.cs:2046-2048) güncellenmezse yeni canlı kayıtlar da "Manuel" yazılır. Kabul kriterine eklenmeli.
- Gerekçe zorunluluğu teknisyen için sürtünme yaratır. Yalnızca **geçmişe dönük** (bitişi 30 dk'dan eski) kayıtlarda zorunlu olmalı; sayaç kullanılamadığı anda girilen kayıt için isteğe bağlı olabilir.
- M09-05'teki `SourceSessionId` de aynı scriptte eklenmeli (tek şema değişikliği, tek yedek).

**Düzeltilmiş tanım (revised):** Tek script (`ZZ_V12x_TimeLogSource.sql`, idempotent, öncesinde `.bak` yedeği): `WorkOrderTimeLogs` ADD `SourceType NVARCHAR(20) NOT NULL DEFAULT N'Manuel'` (CHECK: Canlı/Manuel/Yönetici Düzeltmesi), `ManualReason NVARCHAR(300) NULL`, `VoidReason NVARCHAR(300) NULL`, `SourceSessionId BIGINT NULL`. Geri doldurma: `WorkOrderLiveSessions.ResultTimeLogId` ile bağlı kayıtlar `Canlı`. Kurallar: (i) Canlı akış INSERT'i `SourceType='Canlı'` yazar. (ii) Bitişi 30 dk'dan eski manuel kayıtta gerekçe zorunlu. (iii) `workorders.assign` izni olmayan kullanıcı en fazla 2 gün geriye kayıt girer. (iv) Manuel kayıt aynı kişinin tamamlanmış ve iptal edilmemiş mola oturumlarıyla çakışamaz. (v) Kayıt iptalinde gerekçe zorunlu. İş emri tablosunda "Kaynak" ve "Giren" sütunları gösterilir. **Kabul:** tasarımdaki (1)-(5); ek olarak (6) migration sonrası canlı sayaçla bitirilen yeni bir bölüm `Canlı` görünür.

### M09-09 · EKSİK / HATA · Sayaç ile iş emri durumu arasındaki bağ — **KABUL · P2**

**Doğrulama:**
- (b) Başlatma `Tamamlandı/Kapatıldı/İptal`'i engelliyor (P.cs:1953, 2031), kapanış kontrolü ise `Tamamlandı/Kapatıldı/Çözüldü` listesini kullanıyor (P.cs:2808). Tutarsızlık gerçek. `Çözüldü` durumundaki işe sayaç başlatılabiliyor ama o iş, açık sayaç varken `Çözüldü`'ye alınamıyor.
- (c) `İptal`'e geçiş `IsClosingStatus` dışında kaldığı için açık sayaç kontrolü yapılmıyor (P.cs:504-509). Sayaç iptal edilmiş işte çalışmaya devam ediyor ve `finish` iptal edilmiş işe süre yazıyor (`finish` dalında durum kontrolü yok, P.cs:2026-2033 yalnızca `change`'de). Gerçek.
- (a) Otomatik `Sahada` geçişi kullanıcı onayına bağlı ve M01-09 durum yaşam döngüsüyle uyumlu olmalı. Tasarım bunu doğru işaretlemiş.

**Not:** (b) ve (c) şema değişikliği gerektirmez, ilk dilime alınmalı. (a) kullanıcı cevabı gelene kadar beklemeli.

### M09-10 · EKSİK · Yanlış başlatılan sayacı ilk 5 dakikada geri alma — **DEĞİŞTİR · P2**

**Doğrulama:** 1 dk alt sınırı (P.cs:2022-2023) ve iptalin yalnızca `workorders.assign`/`users.manage` ile yapılabilmesi (P.cs:2084) doğru.

**Gerekçe:** Mobilde 17 benzer iş kartı arasında yanlış karta dokunma olasılığı yüksek. Yönetici iptali için şefi aramak gereksiz yük.

**Sorun:** "Faaliyet değiştirmedeki 1 dk alt sınırı uygulanmaz" ifadesi belirsiz. Kural yalnızca geri alma işlemi için gevşemeli; `change` ve `finish` için 1 dk kuralı korunmalı.

**Düzeltilmiş tanım (revised):** Yeni `POST /api/timetracking/sessions/{sid}/undo`. Yalnızca oturum sahibi (`TechnicianUserId = user.UserId`), yalnızca açık oturumda ve `SYSDATETIME() < StartedAt + 5 dk` iken çalışır. Oturum `StopReason='Kullanıcı Geri Aldı'` ile kapanır, `TimeLogs`'a kayıt yazılmaz. Oturum ataması kalkmış olsa da sahibi geri alabilir (iş erişim kontrolüne takılmaz). `change`/`finish` için 1 dk kuralı değişmez. **Kabul:** tasarımdaki (1)-(3).

### M09-11 · HATA · Atama değişince açık sayaç sahibine kilitleniyor — **KABUL · P1**

**Doğrulama:**
- Tekil atama tüm aktif atamaları kapatıp yeniden yazıyor; açık sayaç kontrolü yok (P.cs:556-566). Toplu atama da aynı (P.cs:600-608).
- `FinishLiveTimerAsync`, oturum kimliğiyle çalışmasına rağmen önce `CanAccessWorkOrderAsync` çağırıyor (P.cs:1996). Bu fonksiyon `Teknisyen` rolünde atanmış isim listesine bakıyor (P.cs:3398-3400). Atama kalkınca 403 dönüyor.
- **Ek tespit:** Saha / Zaman Takibi sayfasındaki "Benim Canlı Faaliyetim" bölümü, atama kontrolü yapmadan Bitir düğmesini gösteriyor (app.js:1504). Teknisyen düğmeye basıyor ve 403 alıyor. Kişi başına tek aktif sayaç kuralı yüzünden (P.cs:1955-1958) başka işte de sayaç başlatamıyor. Gerçek bir iş akışı kilidi.

**Not:** Toplu atama 150 işi tek transaction'da yeniden yazıyor. Açık sayaç kontrolü tek bir `EXISTS` sorgusuyla eklenmeli. "Hiçbir iş değişmez" kabul kriteri mevcut transaction yapısıyla doğal olarak sağlanır.

### M09-12 · HATA · Saat kaynağı tutarsızlığı — **DEĞİŞTİR · P1 (Linux geçişinden önce)**

**Doğrulama:** Manuel kayıtta `DateTime.Now` (P.cs:2126), `summary.serverTime = DateTime.Now` (P.cs:1926), istemcide `Date.now()` (app.js:1439), canlı sayaçta `SYSDATETIME()` (P.cs:1959, 2021). `linux/dengeerp.service` ve `01_sunucuyu_hazirla.sh` saat dilimi ayarlamıyor. Doğru. Ubuntu sunucu UTC'de kalırsa teknisyenin **son 3 saatte biten** gerçek çalışması "gelecek tarih" diye reddedilir.

**Sorun:** Altyapı kısmı (TZ, NTP, `03_dogrula.sh`, `/api/health`'te SQL saat farkı) `A4-06` ve `A2-05` ile birebir aynı. İki yerde ayrı ayrı uygulanırsa çakışır.

**Düzeltilmiş tanım (revised):** Bu maddede yalnızca zaman kaydına özgü kısım kalır: (i) Manuel kayıttaki gelecek kontrolü ve M09-08'deki geriye dönük gün sınırı, transaction içinde okunan SQL `SYSDATETIME()` ile yapılır. (ii) `summary.serverTime` SQL saatinden döner. (iii) İstemci `serverTime - Date.now()` farkını saklar ve geçen süre göstergesini bu farkla düzeltir. Altyapı tarafı (systemd `Environment=TZ=Europe/Istanbul`, `timedatectl`, NTP, doğrulama betiği) **A4-06** kapsamında yapılır ve bu maddenin ön koşuludur. **Kabul:** tasarımdaki (1) ve (2); (3) A4-06'ya taşınır.

### M09-13 · VERİ · Zaman kayıtlarının kişi kimliğine bağlanması — **KABUL · P2**

**Doğrulama:** `WorkOrderTimeLogs`'ta kullanıcı kimliği yok. Çakışma ve "kendi kayıtlarım" kontrolleri isimle yapılıyor (P.cs:1921, 1962, 2041, 2140, 2146). Atama tablosu da isimle (P.cs:1945, 2135). Doğru.

**Not:** Ad değişikliği ve aynı adlı iki personel bugün gerçek ama nadir risk. Bu yüzden P2. Atama tarafı (M01-10 / M02-03) kimliğe geçmeden bu maddenin yalnızca yarısı işe yarar; ikisi aynı sürümde yapılmalı. Geri doldurma "eşleşmeyeni metin olarak koru, silme" kuralı doğru.

### M09-14 · VERİ · Ops ve maliyet ekranlarında "0 saat" yerine "süre kaydı eksik" — **DEĞİŞTİR · P1**

**Doğrulama:**
- `recordedMinutes` kayıt yoksa 0 dönüyor (Ops.cs:88). **Ancak bu alan `ops120.js`'de ve CSV'de hiç kullanılmıyor.** Kabul (1)'deki "ops listesinde 0 dk görünür" iddiası yanlış; ekranda gösterilen bir şey yok.
- Maliyet ekranında süre kaydı olmayan işin işçiliği 0,00 TL görünüyor, toplam maliyet düşük ve "fark" yüksek çıkıyor (Ops.cs:230-234, ops120.js:21). Gerçek ve yönetimi yanıltan bir hata.
- Excel'de kayıt olmayan iş için "Gerçek Kişi-Saat" `0.00` yazılıyor (P.cs:3678). "Bu Seçimde Süre Kaydı Eksik İş" sayacı henüz başlamamış veya ileri tarihli planlı işleri de eksik sayıyor (P.cs:3666); bu sayı şişik çıkıyor.

**Düzeltilmiş tanım (revised):** (i) `/api/ops/finance`: süre kaydı olmayan işte `hours` ve `labor` `null` döner; ekranda "Kayıt eksik" yazılır; özet kutularında "İşçilik kaydı eksik iş: n" gösterilir ve bu işler "Fark" toplamına ayrı satır olarak yansıtılır. (ii) `/api/ops/overview`: `recordedMinutes` kayıt yoksa `null` döner (ileride ekranda gösterilirse doğru başlasın). (iii) Excel: kaydı olmayan satırda "Gerçek Kişi-Saat" hücresi boş kalır. "Süre Kaydı Eksik İş" sayacı yalnızca durumu `Sahada/İşlemde/Atölyede/Tamamlandı/Kapatıldı` olan işleri sayar. **Kabul:** (1) Kaydı olmayan iş maliyet ekranında "Kayıt eksik" görünür, "0,00" görünmez. (2) Maliyet özetinde "İşçilik kaydı eksik iş: n" satırı bulunur. (3) Kaydı olan işlerin hesabı değişmez. (4) Excel'de kaydı olmayan satırda kişi-saat hücresi boştur.

### M09-15 · EKSİK · Özet ve kayıt uçlarında tüm tablonun belleğe okunması — **DEĞİŞTİR · P2**

**Doğrulama:** `LoadTimeLogsAsync` ve `LoadLiveTimersAsync` filtresiz okuyor (P.cs:3403-3439). `GET time-logs` tüm tabloyu okuyup bellekte süzüyor (P.cs:2111-2112). `summary` hem açılışta (app.js:143) hem her iş emri açılışında (app.js:1612) çağrılıyor. Ayrıca `summary` her çağrıda `LoadWorkOrdersAsync` ile tüm iş emirlerini okuyor (P.cs:1913). Doğru.

**Sorun:** Kabul (2)'deki "100.000 kayıtta 1 sn" ölçütü test verisi ve ortam belirtilmeden ölçülemez. Ayrıca iş emri penceresinin `summary`'yi yalnızca "benim aktif sayacım" için çağırdığı gözden kaçmış; bu iş için hafif bir uç yeterli.

**Düzeltilmiş tanım (revised):** (i) `GET /api/workorders/{id}/time-logs` SQL'de `WHERE WorkOrderId=@Id` ile okur. (ii) Yeni hafif uç `GET /api/timetracking/me` yalnızca kullanıcının açık oturumunu döner; iş emri penceresi ve mobil sayaç bandı bunu kullanır. (iii) `summary` `from/to` parametresi alır, varsayılanı son 31 gün; filtre SQL'de uygulanır. (iv) `WorkOrderTimeLogs(WorkOrderId)` ve `(StartedAt)` indeksleri eklenir (kimlik indeksi M09-13 ile). **Kabul:** (1) Sorgu planında `WorkOrderId` seek. (2) M09-D03 test veritabanında (20.000 iş emri, 100.000 süre kaydı) iş emri penceresi açılışında `summary` çağrılmaz. (3) Aynı filtrede eski ve yeni uçların sonuçları birebir aynıdır.

### M09-16 · GÜVENLİK · Zaman yönetimi yetkisinin ayrıştırılması — **DEĞİŞTİR · P3**

**Doğrulama:** Sayaç ve kayıt iptali `workorders.assign` **veya** `users.manage` kabul ediyor (P.cs:2084, 2170). İK şablonunda `users.manage` var (P.cs:3934). Başkası adına kayıt kararı rol adına bakıyor (P.cs:2120, app.js:1632, 1649). Ekip görünümü `reports.view` ile (P.cs:1915). Doğru.

**Sorunlar:**
- `users.manage` sahibi kendine `*` dahil istediği izni verebiliyor (envanter §52, A1). Bu iki uçtan `users.manage`'ı çıkarmak tek başına güvenlik sağlamaz. Asıl çözüm A1 / M13'teki "verilebilir izin" kuralıdır.
- İki yeni izin anahtarı, organizasyon şeması gelmeden rol modelini büyütüyor. `workorders.assign` zaten Şef ve Müdürlerde var, Teknisyen'de yok; zaman yönetimi için doğal karşılık.
- `RoleName == "Teknisyen"` sorunu bu modüle özgü değil. Aynı kontrol iş emri görünürlüğünde de var (P.cs:3398, 3499). M01-18 ile tek seferde çözülmeli.
- KRİTİK değil: veri kaybı veya dış sızıntı yaratmıyor; kayıtlar silinmiyor, yalnızca iptal işaretleniyor ve iz kalıyor.

**Düzeltilmiş tanım (revised):** (i) Sayaç iptali ve süre kaydı iptali yalnızca `workorders.assign` ile yapılır; `users.manage` bu iki uçtan çıkarılır (app.js:1511'deki düğme koşulu da). (ii) Başkası adına manuel kayıt `workorders.assign` iznine bağlanır; rol adı kontrolü kaldırılır. Bu, M01-18'deki `workorders.own_only` dönüşümüyle aynı sürümde yapılır. (iii) Ekip görünümü bu aşamada `reports.view` ile kalır; ayrı anahtar organizasyon şeması geldikten sonra değerlendirilir. **Kabul:** (1) Yalnız `users.manage` olan hesapla sayaç iptali 403. (2) `workorders.assign` olmayan hesapla başkası adına kayıt 403. (3) Teknisyen şablonu değişmez.

---

## 3. Eklenen maddeler

### M09-D01 · HATA · 18 saati aşan unutulmuş sayaç teknisyeni kilitliyor — **P1**

- **Mevcut:** `finish` ve `change`, 18 saati aşan oturumda 400 döner (P.cs:2024-2025). Kişi başına tek aktif sayaç kuralı nedeniyle (P.cs:1955-1958, `UX_LiveSessions_OneActivePerUser`) teknisyen başka işte sayaç da başlatamaz. Çözüm yalnızca yönetici iptali (P.cs:2084). Arayüz bunu "yetkili yönetici iptal etmeli" diye yazıyor (app.js:1505).
- **Neden gerekli:** Cuma akşamı açık kalan sayaç pazartesi sabahı ekibin işe başlamasını yöneticiye bağlıyor. Yönetici ulaşılamazsa o gün hiç canlı veri oluşmaz ya da teknisyen sayacı tamamen bırakır. Bu, modülün temel amacını (gerçek süre verisi) doğrudan bozar.
- **Tanım:** Oturum sahibi, 18 saati aşmış (veya başlangıç günü bugünden önce olan) kendi açık oturumunu "Unuttum, gerçek bitiş saatini gir" akışıyla kapatabilir. Girilen bitiş, başlangıçtan sonra, başlangıçtan en fazla 18 saat sonra ve SQL saatinden önce olmalıdır. Mola dışı faaliyette `SourceType='Manuel'`, `ManualReason` zorunlu ve `SourceSessionId` dolu bir süre kaydı oluşur. Oturum `StopReason='Kullanıcı Düzeltti'` ile kapanır. Çakışma kuralları manuel kayıtla aynıdır. İş emri ataması kalkmış olsa da sahibi bu işlemi yapabilir.
- **Kabul:** (1) 20 saatlik açık oturumu olan teknisyen gerçek bitiş saatini girerek oturumu kapatır ve hemen yeni işte sayaç başlatabilir. (2) Gerekçesiz istek 400. (3) Bitiş SQL saatinden sonra veya başlangıçtan 18 saatten fazla sonra ise 400. (4) Bitiş başka bir kayıtla çakışırsa 409, oturum açık kalır. (5) Başkasının oturumu 403. (6) Kayıt disiplin sütunlarında (M09-07) "düzeltilmiş" olarak sayılır.
- **Roller:** Teknisyen (kendi oturumu).
- **Veri:** M09-08 sütunlarını kullanır; ek şema yok.
- **Efor:** S · **Bağımlılık:** M09-08 (kaynak alanları). M09-08 gelmeden de `WorkNote` içine "Kullanıcı düzeltmesi: gerekçe" yazılarak geçici olarak uygulanabilir.

### M09-D02 · EKSİK · İş kapatılırken süre kaydı eksik uyarısı — **P2**

- **Mevcut:** Kapanışta açık sayaç kontrolü var (P.cs:504-509), ama işte hiç süre kaydı olmaması kontrol edilmiyor. Eksiklik ancak Excel'de "SÜRE KAYDI YOK" (P.cs:3678) veya Raporlar ekranında (app.js:1175) görülüyor. Tasarımın §2.1'i "Şef süre kaydı eksik işleri kapatmadan önce görür" diyor, ama bunu karşılayan bir madde yok.
- **Neden gerekli:** Eksik kaydın en ucuz düzeltileceği an iş kapanırken. Ay sonu Excel'inde fark edildiğinde kimse gerçek saati hatırlamıyor. "Eksik ≠ 0" kararının işe yaraması için eksiklerin kaynağında azaltılması gerekir.
- **Tanım:** `PATCH status` kapanış durumlarında (`Tamamlandı/Kapatıldı/Çözüldü`) işte iptal edilmemiş hiç süre kaydı yoksa veya atanan teknisyenlerden birinin kaydı yoksa yanıt `warnings` alanında bunu döner. İstemci kapanıştan önce "Bu işte X kişisinin süre kaydı yok. Yine de kapatılsın mı?" onayı ister. **Engellemez.** Onayla kapatılırsa durum geçmişi notuna "Süre kaydı eksik olarak kapatıldı" eklenir.
- **Kabul:** (1) Kaydı olmayan işi kapatmaya çalışan kullanıcı onay penceresi görür; onaylarsa iş kapanır ve geçmişte not görünür. (2) Kaydı tam olan işte pencere çıkmaz. (3) Planlı bakım "Bakım Formu" kapanışında da (P.cs:2496 çevresi) aynı uyarı verilir.
- **Roller:** `workorders.close` / `workorders.edit`.
- **Veri:** Yok.
- **Efor:** S · **Bağımlılık:** — (M09-06 "Kısmi" hesabıyla aynı fonksiyonu kullanmalı).

### M09-D03 · EKSİK · Zaman kuralları için otomatik entegrasyon test seti ve test verisi — **P1**

- **Mevcut:** Proje geçmişi V1.14 canlı sayacın uçtan uca testinin eksik olduğunu ve "Saha zaman sayacı, mola ve kişi-saat raporu test edildi" maddesinin açık kaldığını yazıyor. Kod tabanında test projesi yok. Tasarım serializable transaction'lara, çakışma ve kilit mantığına dokunan 10'dan fazla değişiklik öneriyor.
- **Neden gerekli:** Bu modüldeki hatalar sessizdir: çift sayım, molanın kişi-saate girmesi, kilitlenen sayaç. Kullanıcı test verisi sağlayacak ve derleme/test burada yapılacak; değişikliklerden **önce** mevcut davranışın bir test setiyle sabitlenmesi gerekir.
- **Tanım:** `DengeERP.Api.Tests` (xUnit + `WebApplicationFactory`, ayrı `DengeERP_TEST` veritabanı). Test verisi üreteci: 3 birim, 1 şef, 3 teknisyen (ikisi aynı adlı), 17 cihazlı bir PB ziyareti, 20.000 iş emri ve 100.000 süre kaydı (performans senaryosu için ayrı profil). Asgari senaryolar: tek aktif sayaç, 1 dk ve 18 sa sınırları, Yol → Saha → Mola → Devam → Bitir zinciri (mola TimeLogs'ta yok, boşluk/çakışma yok), çift basış, manuel ↔ canlı ↔ mola çakışması, açık sayaçla kapanış/iptal, atama kaldırma (M09-11), unutulan sayaç (M09-D01), "eksik ≠ 0" (M09-14), yetki (M09-16).
- **Kabul:** (1) `dotnet test` mevcut V1.20.1 davranışı için yeşil çalışır (bilinen hatalar `Skip` gerekçesiyle işaretlenir). (2) Her M09 maddesi kendi testini açarak tamamlanır. (3) Test veritabanı her koşuda sıfırdan kurulur, gerçek veriye dokunmaz.
- **Roller:** — (geliştirme)
- **Veri:** Yalnızca test veritabanı.
- **Efor:** M · **Bağımlılık:** — (diğer bütün M09 maddelerinden önce iskeleti kurulmalı).

> **Değerlendirilip eklenmeyen aday:** "Bitişteki çakışma 409'u oturumu kilitler" senaryosu incelendi. Manuel kayıt, çalışan sayaçla çakışınca zaten reddediliyor (P.cs:2139-2143) ve başlangıçta "şu an" kontrolü var (P.cs:1960-1965). Bitişte 409 ancak isim uyuşmazlığında (aynı adlı iki kişi, ad değişikliği) oluşabiliyor. Bu yüzden ayrı madde açılmadı; M09-13'ün kabul testlerine eklenmelidir.

---

## 4. Kullanıcıya iletilecek ek sorular (tasarımın §4 listesine ek)

1. **Sahada çalışan şef:** Şefler de sahada fiilen çalışıyorsa süreleri tutulacak mı? Tutulacaksa her işe ayrıca "teknisyen" olarak mı atanacaklar, yoksa sayaç şef atamasını da kabul mü etmeli? (Bugün yalnızca teknisyen ataması kabul ediliyor, P.cs:1945.)
2. **Hafta sonu / tatilde unutulan sayaç:** Teknisyen unuttuğu sayacı kendisi mi düzeltsin (M09-D01), yoksa her durumda şef onayı mı gereksin?

## 5. Uygulama sırası önerisi (denetim sonrası)

| Dilim | Maddeler | Şema | Not |
|---|---|---|---|
| 0 | M09-D03 (test iskeleti + test verisi) | Yalnız test DB | Diğer her şeyden önce |
| 1 | M09-11, M09-09(b,c), M09-D01 (geçici `WorkNote` ile), M09-14, M09-16(i) | Yok | Kilitleri ve "0" gösterimini kaldırır |
| 2 | M09-02, M09-01 (M02-08 ile tek ekran), M09-10 | Yok / `WaitReason` | Kullanıcının (c) önceliği |
| 3 | M09-08 (tek script, `SourceSessionId` dahil), M09-05, M09-03, M09-D02 | 1 script | `.bak` yedeği sonrası |
| 4 | M09-04, M09-06, M09-15 | İndeksler | Yönetim görünürlüğü |
| 5 | M09-13 (M01-10 ile), M09-07, M09-16(ii) (M01-18 ile), M09-09(a) (kullanıcı onayıyla) | 1 script | Kimlik geçişi |
| Linux öncesi | M09-12 + A4-06 | Yok | Geçişten önce zorunlu |
