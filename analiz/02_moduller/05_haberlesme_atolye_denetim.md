# M05 — Haberleşme Atölyesi: Bağımsız Denetim Raporu

> **Tarih:** 21 Ekim 2026 · **Denetlenen:** `05_haberlesme_atolye_tasarim.md` (M05-01 … M05-19)
> **Kaynak (salt okunur):** `kaynak/V1_20_1_orijinal/DengeERP.Api` — `Program.cs`, `OpsSuite.cs`, `wwwroot/app.js`, `Database/*.sql`
> **Yöntem:** Her maddenin "mevcut durum" iddiası kod okunarak doğrulandı. Kullanıcı kararlarına (kapsam yalnız teknik servis, öncelik c→b→a, Logo/Flowick kapsam dışı, fiyat API'de gizli, süre yoksa "eksik") uygunluk ve gereklilik sınandı. Rol önerileri **varsayımdır**, organizasyon şeması gelince doğrulanmalıdır.

---

## 1. Özet

| Karar | Adet | Maddeler |
|---|---|---|
| KABUL | 6 | M05-02, M05-05, M05-09, M05-11, M05-12, M05-13 |
| DEĞİŞTİR | 13 | M05-01, M05-03, M05-04, M05-06, M05-07, M05-08, M05-10, M05-14, M05-15, M05-16, M05-17, M05-18, M05-19 |
| RET | 0 | — |
| Eklenen | 4 | M05-D01 … M05-D04 |

Genel değerlendirme: Tasarım büyük ölçüde doğru ve kodla örtüşüyor. Satır referanslarının çoğu tuttu. Ancak dört iddia **abartılı veya kısmen yanlış**:
1. **M05-10:** Teknisyenin bağlı iş emrini "hiç göremediği" iddiası yanlış. İş emri ekranındaki atama ucu (`Program.cs:545-570`) ile atanırsa görür ve sayaç başlatır. Gerçek hata, **iki ayrı atama kaynağı** olması ve atölye ekranındaki "Atanan" alanının etkisiz kalmasıdır. Parça çıkışı iddiası da yanıltıcı: parça çıkışı `warehouse.manage` ister (`OpsSuite.cs:190`) ve varsayılan Teknisyen rolünde bu izin yok.
2. **M05-17:** "Tutar alanı modalda gizlensin" ile "PUT'ta 403" birlikte uygulanırsa sorun çıkar. PUT tüm alanları ezdiği için (`Program.cs:2735`) gizli alan `null` gider. Sonuç ya kayıt hatası (403) ya da **tutarın silinmesi** olur. Doğrusu: izinsiz kullanıcının gönderdiği tutar yok sayılır ve mevcut değer korunur.
3. **M05-18(c):** Varsayılan rollerde `workorders.edit` olup `workshop.manage` olmayan rol yok (`Program.cs:3921-3935`). Bu yüzden PUT tarafındaki açık teoriktir. POST tarafında ise yedek izni kaldırmak, tasarımcının "Kabul" rolü saydığı **Operasyon Uzmanı**'nı (yalnız `workorders.create` var) dışarıda bırakır. Buna karşılık tasarımcı daha geniş bir açığı kaçırmış: `workorders.view` yedeği nedeniyle **Muhasebe, Depo ve Kiralama Operasyon** rolleri de tüm atölye kayıtlarını, müşteri iletişim bilgileriyle birlikte okuyabiliyor.
4. **M05-04:** Teklif PDF altyapısı (`BuildSimpleOfferPdf`, `Program.cs:3573-3599`) metni `ToAscii` ile basıyor, yani Türkçe karakterler bozuluyor. Müşteriye verilecek kabul fişi için yeniden kullanılmamalı.

Ayrıca **M05-06**'daki tekrar gelen cihaz analizi Operasyon Merkezi'nde kısmen zaten var (`OpsSuite.cs:93-96`). Bu analiz yeniden yazılmamalı, mevcut olan kullanılmalı.

---

## 2. Madde bazında kararlar

### M05-01 · Atölye durum makinesi ve durum geçmişi — **DEĞİŞTİR · P1**
- **Doğrulama:** Doğru. Liste serbest (`app.js:673`). Eşleme tek yönlü (`Program.cs:2746-2755`). PUT log yazmıyor. Ek tespit: yeni kayıtta formdan herhangi bir durum seçilebiliyor (ör. "Teslim Edildi"), ama POST iş emrini her zaman `Atölyede` açıyor (`Program.cs:2657`). Bu, oluşturma anında tutarsızlık demek.
- **Gereklilik:** Modülün omurgası. M05-02/03/08/09/15 buna bağlı.
- **Düzeltilmiş tanım:** Geçiş tablosu kodda sabit tutulur, yönetim ekranı yapılmaz (aşırı mühendislikten kaçınmak için). Yeni kayıt **yalnız** "Kabul Edildi" ile başlar; POST durum alanını yok sayar. `POST /api/workshop/tickets/{id}/status` aynı transaction'da şunları yapar: `WorkshopTicketStatusLog` satırı yazar, iş emri durumunu eşler ve `InsertStatusLogAsync` ile iş emri tarihçesine yazar (M05-11'i kapsar). "Kargoya Verildi" yalnız teslim tipi Kargo ise izinlidir. Göçte eski "Beklemede" değerleri otomatik eşlenmez: önce rapor alınır, varsayılan olarak "Parça Bekliyor"a çevrilir ve liste kullanıcıya sunulur. `workshop.close` yeni izni **varsayımdır**. Proje kararı gereği unvana bağlı değil, kişi bazında atanabilir olmalıdır.
- **Kabul kriteri ekleri:** POST'ta `status="Teslim Edildi"` gönderilse bile kayıt "Kabul Edildi" ile açılır. Kapalı bir kaydı yeniden açmak (Teslim Edildi'den başka duruma geçmek) yalnız `workshop.close` ile ve gerekçeyle yapılabilir.

### M05-02 · Yapılandırılmış teşhis ve onarım kaydı — **KABUL · P2**
- **Doğrulama:** Doğru. Yalnız serbest metin `DeviceCondition` ve `RepairInfo` alanları var (`V15_Schema.sql:119-120`).
- **Not:** Arıza kategorisi listesi şimdilik kodda sabit kalabilir. `IsRepairable=0` seçilirse yalnız "Onarılmadan İade" yolu açık olmalı. Bu kural M05-01'in geçiş tablosuna eklenir.

### M05-03 · Ücretli onarımda müşteri onayı ve teklif bağlantısı — **DEĞİŞTİR · P2**
- **Doğrulama:** Doğru. Yalnız serbest `RepairAmount` alanı var ve teklif bağlantısı yok.
- **Sorun:** Tasarımcının kendi 1. sorusu (onay nasıl alınıyor, eşik tutar var mı) cevaplanmadan ayrı bir `WorkshopApprovals` tablosu ve sert engel kurmak erken olur. Ayrıca garanti durumu "Bilinmiyor" olduğunda ne olacağı tanımlanmamış.
- **Düzeltilmiş tanım:** İlk adım minimal tutulur. "Onay Bekliyor" durumu ve kayıt üzerinde onay alanları: `ApprovalDecision`, `ApprovalChannel`, `ApprovedByName`, `ApprovalAt`, isteğe bağlı `OfferId`. Teklif oluşturma kısayolu mevcut teklif ucunu `WorkOrderId` ile çağırır. Garanti "Garantili" değilse (Bilinmiyor dahil) "Onarımda"ya geçmek için onay kaydı **veya** gerekçeli "onay gerekmez" işareti zorunludur. OpsHolds "Müşteri onayı" bekletmesi M05-15'teki senkron kuralıyla açılır ve kapanır. Ayrı tablo, kullanıcı birden fazla onay turu olduğunu söylerse eklenir.

### M05-04 · Kabul fişi ve teslim tutanağı — **DEĞİŞTİR · P2**
- **Doğrulama:** "Yok" iddiası doğru. Ancak önerilen yeniden kullanım yanlış: `BuildSimpleOfferPdf` elle yazılmış bir PDF üreticisi ve metni `ToAscii` ile basıyor (`Program.cs:3575`). Bu yüzden "Şikâyet", "Aksesuar", firma adlarındaki ş/ğ/ı/ö/ü/ç bozulur.
- **Düzeltilmiş tanım:** Yazdırmaya uygun HTML sayfa kullanılır. Sunucu, izne göre süzülmüş veriyi döndüren bir uç sağlar; tarayıcı bu sayfayı "Yazdır / PDF olarak kaydet" ile çıktı alır. Yeni kütüphane eklenmez ve teknoloji yığını korunur. Tutar satırı sunucu yanıtında `finance.prices.view` yoksa hiç yer almaz.
- **Kabul:** Türkçe karakterler doğru basılır. Seri no baştaki sıfırlarıyla aynen basılır. İzinsiz kullanıcının çıktısında ve JSON'unda tutar yer almaz.

### M05-05 · Satır bazlı aksesuar kaydı — **KABUL · P2**
- **Doğrulama:** Doğru (`V15_Schema.sql:111-115`, `app.js:674, 722`).
- **Not:** Teslimdeki karşılaştırma kuralı M05-01'deki "Teslim Edildi" geçişine bağlıdır. Bağımlılığa M05-01 eklenmelidir. Eski kolonlar silinmez.

### M05-06 · Seri no geçmişi, tekrar gelen cihaz, açık kayıt engeli — **DEĞİŞTİR · P2**
- **Doğrulama:** POST'ta mükerrer kontrol olmadığı doğru (`Program.cs:2628-2637`). "Geçmiş görünümü yok" iddiası kısmen yanlış: Operasyon Merkezi tekrar gelen seri listesini zaten üretiyor (`OpsSuite.cs:93-96`). Bu liste zaman penceresi olmadan, tüm iş emirleri üzerinden ve `WorkOrderDevices` kaynaklı.
- **Düzeltilmiş tanım:** (1) Açık atölye kaydı varken aynı seri no ile POST 409 döner ve mesajda mevcut atölye no yer alır. (2) Kabul ekranında seri no geçmişi listelenir; mevcut OpsSuite analizinin mantığı yeniden kullanılır. (3) `IsRepeatVisit` bayrağı **eklenmez**, çünkü tarih ve seri nodan türetilebilir. (4) 90 günlük pencere tasarımcının 2. sorusuna (Denge onarım garantisi süresi) bağlıdır; cevap gelene kadar yapılandırılabilir sabit olarak tutulur.

### M05-07 · Garanti durumunun hesaplanması — **DEĞİŞTİR · P2**
- **Doğrulama:** Doğru. Alan serbest metin ve varsayılan değer "Garanti Değil" (`app.js:721`).
- **Düzeltilmiş tanım:** Liste ve hesaplama kabul edilir. "Onarım Garantisi" değeri M05-06'daki tekrar geliş tespitine bağlıdır. Eski kayıtların dönüşümü kullanıcı 10. soruya cevap verene kadar **yapılmaz**. Bağımlılık: M05-06 (yalnız Onarım Garantisi için).

### M05-08 · Filtre/arama, yaşlandırma ve KPI — **DEĞİŞTİR · P2 (liste) / P3 (KPI)**
- **Doğrulama:** Doğru. Filtresiz tablo var (`app.js:676-682`). GET tüm kayıtları sayfalamasız döndürüyor (`Program.cs:2569-2576`).
- **Düzeltilmiş tanım:** İki parçaya ayrılır. **(a) P2, bağımlılık yok:** sunucu tarafında filtre ve sayfalama (durum, teknisyen, marka, metin arama), bekleme günü `EntryDate`'ten hesaplanır, tahmini bitişi geçen kayıtlar işaretlenir, 0-3/4-7/8-14/15+ yaşlandırma kutuları gösterilir. **(b) P3, M05-01'e bağlı:** çevrim süresi, tekrar geliş oranı, arıza dağılımı ve teknisyen raporu ile Excel. Çevrim süresi yalnız "Teslime Hazır" log kaydı olan kayıtlarla hesaplanır; diğerleri "süre kaydı eksik" sayılır.

### M05-09 · Teslim/kargo sabit liste ve zorunluluk — **KABUL · P2**
- **Doğrulama:** Doğru. Alanlar serbest metin (`app.js:707-711`). `DeliveredAt` alanının sunucu saatinden atanması M05-13 ile tutarlıdır.

### M05-10 · Atölye ataması iş emri atamasına yansımıyor — **DEĞİŞTİR · P1**
- **Doğrulama:** Kısmen doğru. `AssignedTo` yalnız isim metni olarak `WorkshopTickets` tablosunda tutuluyor (`Program.cs:2875`) ve `WorkOrderAssignments`'a yazılmıyor. Ancak iş emri ekranından atama yapılırsa (`Program.cs:545-570`) teknisyen işi görür ve sayaç başlatır (`Program.cs:1935, 1943-1945`). Parça çıkışı ise atamaya değil `warehouse.manage` iznine bağlı (`OpsSuite.cs:190`); Teknisyen rolünde bu izin zaten yok (`Program.cs:3930`).
- **Gerçek hata:** İki ayrı atama kaynağı var. Atölye ekranındaki "Atanan" alanı yetki ve süre tarafında **etkisiz**. Atölye listesi ile iş emri listesi farklı kişiyi gösterebiliyor.
- **Düzeltilmiş tanım:** Tek kaynak `WorkOrderAssignments` olur. Atölye ekranındaki "Atanan" seçimi bu tabloya (Teknisyen rolü) yazar, okurken de buradan okur. `AssignedTo` yalnız eski veri için salt okunur kalır. Atama değişince eski satır pasif olur. Göç: `AssignedTo` değerleri personel adlarıyla eşleştirilir; eşleşmeyenler raporlanır (M05-D03).
- **Kabul:** Atölye ekranında atanan teknisyen iş emri listesinde kaydı görür ve "Atölye" faaliyetiyle sayaç başlatabilir. İş emri ekranından yapılan atama atölye listesinde de görünür.

### M05-11 · Durum değişikliği iş emri tarihçesine yazılmıyor — **KABUL · P1**
- **Doğrulama:** Doğru. PUT'ta `InsertStatusLogAsync` çağrısı yok; yalnız oluşturmada var (`Program.cs:2701`). Küçük ve bağımsız bir düzeltme. M05-01 beklenmeden hemen yapılabilir.

### M05-12 · İptal edilen kaydın iş emri açık kalıyor — **KABUL · P1**
- **Doğrulama:** Doğru. `_ => "Atölyede"` (`Program.cs:2754`) ve "İptal" listede var (`app.js:673`). Sonuç: panoda açık iş ve "Atölyede" sayısı şişiyor.

### M05-13 · Tarih/saat kayması ve tamamlanma tarihinin ezilmesi — **KABUL · P1**
- **Doğrulama:** Doğru. `new Date().toISOString().slice(0,16)` UTC değeri bölge bilgisi olmadan gönderiyor (`app.js:697`), sunucu bunu yerel saat sanıyor ve 3 saat kayma oluşuyor. `completionDate` her kaydetmede "şimdi" ile ezilip UTC gönderiliyor (`app.js:739`). `EntryDate ?? DateTime.Now` (`Program.cs:2863`) ön yüz alanı boş gönderirse kabul tarihini değiştirir. Çevrim süresi KPI'ı için ön koşul.

### M05-14 · Seri no güncellemesi WorkOrderDevices'a yansımıyor — **DEĞİŞTİR · P1**
- **Doğrulama:** Doğru (`Program.cs:2669-2675` ve `2757-2772`). Durum ucu cihaz satırını okuyor (`Program.cs:486`). Tekrar analizi de aynı kaynağı kullanıyor (`OpsSuite.cs:93`).
- **Ek (tasarımcı kaçırmış):** Ters yönde de kayma var. `PUT /api/workorders/{id}/serials` (`Program.cs:432-470`) `WorkOrderDevices` ve `WorkOrders.SerialNo` alanlarını güncelliyor, `WorkshopTickets.SerialNo` alanını güncellemiyor. Üstelik atölye iş emrine **birden fazla seri** eklenmesine izin veriyor, bu da "1 atölye kaydı = 1 cihaz" kuralını bozuyor.
- **Düzeltilmiş tanım:** Atölye PUT'u seri no değişince `WorkOrderDevices` aktif satırını da günceller ve değişikliği tarihçeye yazar. Genel seri ucu, atölye kaydına bağlı iş emri için 409 döner ve kullanıcıyı atölye ekranına yönlendirir.

### M05-15 · İş emri ekranından yapılan durum değişikliği atölyeyi güncellemiyor — **DEĞİŞTİR · P1**
- **Doğrulama:** Doğru (`Program.cs:473-543`, `OpsSuite.cs:130-159`).
- **Ek:** Ters yönde de hata var. Atölye PUT'u iş emri durumunu her kayıtta koşulsuz ezer (`Program.cs:2757-2772`). Bu yüzden (a) OpsHolds aktifken atölyede not düzeltmek, iş emrini `Beklemede`den çıkarır ama bekletme kaydı açık kalır; (b) "Teslim Edildi" bir kayıt farklı durumla kaydedilirse `Kapatıldı` iş emri yeniden açılır ve `ClosedAt` eski değerde kalır.
- **Düzeltilmiş tanım:** Atölyeye bağlı iş emirlerinde durumu yalnız atölye durum ucu (M05-01) değiştirir. Genel PATCH ve ops hold/release 409 döner ve yönlendirme mesajı verir. Atölye ucu "Onay Bekliyor" veya "Parça Bekliyor" durumuna girerken OpsHolds kaydı açar, çıkarken kapatır. M05-01'e kadar geçici önlem: atölye PUT'u durum alanı değişmediyse iş emri durumuna dokunmaz.

### M05-16 · Atölye kaydında parça ve süre görünümü — **DEĞİŞTİR · P2**
- **Doğrulama:** Altyapının var olduğu doğru (`OpsSuite.cs:188-213`, `Program.cs:1929`). Ancak "Teknisyen atölye kaydından parça çıkışı yapar" varsayımı yanlış, çünkü bu işlem `warehouse.manage` gerektiriyor.
- **Düzeltilmiş tanım:** Atölye detayında bağlı iş emrinin parça hareketleri ve süre kayıtları **salt okunur** gösterilir. Süre kaydı yoksa "Süre kaydı eksik" yazılır, 0 yazılmaz. Mola süresi dahil edilmez. "Parça çıkışı" düğmesi yalnız `warehouse.manage` sahibine görünür. Teknisyenin parça talebi gerekiyorsa ayrı madde olarak, organizasyon şeması gelince ele alınır. Maliyet yalnız `finance.prices.view` ile döner, aksi halde `null`.

### M05-17 · KRİTİK — Tamir bedeli fiyat izni olmadan dönüyor — **DEĞİŞTİR · P1 (KRİTİK)**
- **Doğrulama:** Doğru ve kapsamı daha geniş. GET `repairAmount` alanını herkese döndürüyor (`Program.cs:2599`). Varsayılan rollerde fiyat izni olmayan Teknisyen, Şef, Operasyon Uzmanı ve Genel Koordinatör tutarı görüyor (`Program.cs:3927-3930`). Ayrıca `workorders.view` yedeği nedeniyle Depo ve Kiralama Operasyon rolleri de görüyor (`Program.cs:2564`). Bu durum "fiyat API seviyesinde gizlenmeli" kararını doğrudan ihlal ediyor.
- **Düzeltilmiş kabul kriteri:** (1) `finance.prices.view` olmayan kullanıcının GET yanıtında `repairAmount` `null` döner. (2) Bu kullanıcının PUT'taki `repairAmount` değeri **yok sayılır, mevcut değer korunur**. 403 döndürülmez; aksi halde modalda gizli alan yüzünden her kayıt başarısız olur ya da tutar silinir. (3) Tutarı yalnız `finance.prices.view` sahibi değiştirebilir; bu durumda iki izin birlikte gerekir: `finance.prices.view` ve `workshop.manage`. (4) Modalda alan gösterilmez.

### M05-18 · Atölye PUT'u kapanış kontrollerini ve erişim kısıtını atlıyor — **DEĞİŞTİR · P1**
- **Doğrulama:** (a) Doğru. "Teslim Edildi" iş emrini `Kapatıldı` yapıyor ama açık sayaç ve seri kontrolleri yapılmıyor (`Program.cs:2753, 2761`; karşılaştırma için `Program.cs:504-523`). (b) Doğru. GET ve PUT'ta teknisyen kısıtı yok. (c) Abartılı: varsayılan rollerde `workorders.edit` olup `workshop.manage` olmayan rol yok. Ancak POST yedeğini kaldırmak, "Kabul" varsayılan rolü Operasyon Uzmanı'nın kayıt açmasını keser. Ön yüz zaten `workshop.manage` istediği için (`app.js:678`) bu rol bugün de arayüzden kayıt açamıyor.
- **Kaçırılan:** `workorders.view` yedeği (`Program.cs:2564`) nedeniyle Muhasebe, Depo ve Kiralama Operasyon rolleri de müşteri ad, telefon, e-posta ve adres bilgisiyle tüm atölye kayıtlarını API'den okuyabiliyor. Ön yüz bunu `workshop.view` ile sınırladığı halde (`app.js:154`) API sınırlamıyor.
- **Düzeltilmiş tanım:** (1) Atölye uçlarında yedek izinler kaldırılır: okuma için yalnız `workshop.view`, yazma için yalnız `workshop.manage` geçerli olur. Kabul rolüne `workshop.manage` verilir (varsayım; organizasyon şeması gelince doğrulanacak). (2) Teknisyen rolü yalnız `WorkOrderAssignments`'ta atanmış olduğu kayıtları listeler, PUT ve durum değişikliği yapar (M05-10'a bağlı). (3) "Teslim Edildi" geçişi, iş emri kapanışındaki kontrollerin aynısını uygular: açık sayaç varsa 409, seri no yoksa 400.

### M05-19 · Sunucu tarafı doğrulama ve eşzamanlı düzenleme — **DEĞİŞTİR · P2**
- **Doğrulama:** Doğru ve somut bir örnek eklenebilir. `WorkshopTickets.Model` 180 karakter, ama `WorkOrders.SystemName` 150 karakter (`DengeERP_Update.sql:26`). `Subject` ise "Marka + Model + ' Atölye Teknik Servis'" olarak 250 karakteri aşabilir. Bu yüzden atölye tablosu açısından geçerli bir model adı, iş emri tarafında SQL hatası ve 500 üretir.
- **Düzeltilmiş tanım:** Uzunluk sınırları iki tablonun **en dar** kolonuna göre doğrulanır (Model ≤ 120 önerilir; Brand+Model ≤ 150). Liste değerleri ve e-posta formatı sunucuda doğrulanır. `rowversion` kolonu eklenir; M05-01 sonrasında genel PUT yalnız tanımlayıcı alanları güncelleyeceği için öncelik P2'dir.

---

## 3. Eklenen maddeler (tasarımcının kaçırdıkları)

### M05-D01 · HATA · Ana Panel atölye işlerini "Sahada" kartında sayıyor — S · P1
- **Mevcut:** "Onarımda" durumu iş emrinde `İşlemde`ye eşleniyor (`Program.cs:2749`). Ana Panel'de "Sahada" kartı `['Sahada','İşlemde']` durumlarını sayıyor, "Atölyede" kartı ise yalnız `status==='Atölyede'` olanları (`app.js:220, 244`). Sonuç: onarımdaki telsiz "Sahada" görünüyor ve "Atölyede" sayısından düşüyor. Beklemede veya Test durumundaki atölye işleri de "Atölyede" sayılmıyor.
- **Öneri:** "Atölyede" kartı, atölye kaydına bağlı (veya `WorkType='Atölye Teknik Servis'`) ve açık olan iş emirlerini durumdan bağımsız sayar. "Sahada" kartı atölye iş türlerini hariç tutar.
- **Kabul:** Onarımda durumundaki atölye kaydı "Sahada" kartında görünmez, "Atölyede" kartında görünür. Kart toplamı atölye listesindeki açık kayıt sayısıyla eşittir.

### M05-D02 · VERİ · Atölye kaydı olmadan "Atölye Teknik Servis" iş emri açılabiliyor — S · P1
- **Mevcut:** Genel iş emri açılışında "Atölye Teknik Servis" iş türü seçilebiliyor (`app.js:11`). `POST /api/workorders` bunu engellemiyor (`Program.cs:370-380`). Açılan iş emrinin atölye kaydı olmuyor, bu yüzden atölye listesinde, KPI'larda ve aksesuar/teslim akışında görünmüyor. Ayrıca bu iş emrine birden fazla seri eklenebiliyor.
- **Öneri:** Genel açılışta bu iş türü için 400 ve "Atölye ekranından açın" mesajı döner. Bunun yerine otomatik atölye kaydı oluşturmak kullanıcı tercihine bırakılır. Mevcut yetim iş emirleri raporlanır.

### M05-D03 · VERİ · Göç öncesi atölye veri sağlığı kontrol seti — S · P1
- **Mevcut:** M05-01, 05, 07, 10, 12 ve 14 maddelerinin her biri ayrı bir "önce rapor" sorgusu öneriyor ama ortak bir set yok.
- **Öneri:** Tek bir salt okunur SQL script hazırlanır. Kontroller: (1) Atölye durumu ile iş emri durumu uyuşmayanlar, (2) İptal atölye kaydı olup iş emri açık kalanlar, (3) `WorkshopTickets.SerialNo` ile `WorkOrderDevices` farkları, (4) `AssignedTo` değeri personel listesiyle eşleşmeyenler, (5) atölye kaydı olmayan "Atölye Teknik Servis" iş emirleri, (6) aynı seri no ile birden fazla açık kayıt, (7) eski durum değerlerinin dağılımı. Her göç bu raporla başlar ve kullanıcı onayıyla uygulanır.

### M05-D04 · YENİ · Dış servis (üretici/distribütör RMA) takibi — M · P3
- **Mevcut:** "Dış Servis" bir servis türü olarak var (`app.js:672`), ama gönderim tarihi, RMA no, dönüş tarihi gibi alanlar ve buna karşılık gelen bir durum yok. Bu cihazlar durum makinesinde "Onarımda" ya da "Beklemede" içinde kaybolur ve çevrim süresi KPI'ını bozar.
- **Öneri (varsayım, tasarımcının 3. sorusuna bağlı):** "Dış Serviste" durumu (iş emrinde `Beklemede` ve OpsHolds "Dış servis") ve `ExternalVendor`, `RmaNo`, `SentAt`, `ReturnedAt` alanları eklenir. Bekleme süresi atölye performansından ayrı raporlanır.

---

## 4. Önerilen uygulama sırası

Kullanıcı önceliği c→b→a'dır. Ancak bazı küçük hatalar yeni özelliklerin ön koşulu ve veri doğruluğunu bozuyor. Bu yüzden önce kısa bir **"veri doğruluğu" paketi** önerilir:

1. **Hızlı düzeltmeler (S, P1):** M05-17 (KRİTİK), M05-11, M05-12, M05-13, M05-D01, M05-D02, M05-D03.
2. **Yeni çekirdek (c):** M05-01 (M05-15 ve M05-18(a) ile birlikte), M05-10, M05-14.
3. **Yeni özellikler (c):** M05-02, M05-05, M05-06, M05-07, M05-09, M05-08(a), M05-03, M05-04.
4. **Sonra:** M05-16, M05-08(b), M05-18(b), M05-19, M05-D04.

## 5. Kullanıcıya iletilecek ek notlar
- Varsayılan rol tablosunda **Şef** rolünde `finance.prices.view` yok. M05-17 sonrasında şefler tamir bedelini göremeyecek. Bu izin kişi bazında verilmeli mi?
- "Kabul" rolü olarak varsayılan Operasyon Uzmanı'nda `workshop.manage` izni yok. Kabul işini kimin yaptığı organizasyon şemasıyla netleşmeli.
