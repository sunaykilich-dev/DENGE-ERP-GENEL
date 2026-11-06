# DengeERP — Proje Geçmişi, Alınan Kararlar ve Teknik Durum

> **Belge tarihi:** 21 Ekim 2026  
> **Proje:** Denge Elektronik — Teknik Servis ERP  
> **Son pilot sürüm:** V1.20.1 (V1.20 + raporlama tarih filtresi düzeltmesi)  
> **Belge türü:** Proje hafızası / fonksiyonel kapsam / teknik devir / yapılacak işler  
> **Kapsam notu:** Bu belge sohbetlerimizde alınan kararların, geliştirilen paketlerin ve gösterilen test sonuçlarının **derlenmiş kaydıdır**; konuşmaların kelimesi kelimesine dökümü değildir. Kodda bulunması ile canlıda doğrulanması farklı durumlar olarak belirtilmiştir.

---

## İçindekiler

1. [Projenin çıkış noktası ve hedefi](#1-projenin-çıkış-noktası-ve-hedefi)
2. [Çalışma yöntemi ve değişmez kurallar](#2-çalışma-yöntemi-ve-değişmez-kurallar)
3. [Teknik mimari ve ortamlar](#3-teknik-mimari-ve-ortamlar)
4. [Sürüm geçmişi V1–V1.20.1](#4-sürüm-geçmişi-v1v1201)
5. [Modüller ve fonksiyonel kararlar](#5-modüller-ve-fonksiyonel-kararlar)
6. [Operasyon akışları ve iş kuralları](#6-operasyon-akışları-ve-iş-kuralları)
7. [Raporlar ve yönetsel KPI'lar](#7-raporlar-ve-yönetsel-kpilar)
8. [Kullanıcı yetkileri ve güvenlik yaklaşımı](#8-kullanıcı-yetkileri-ve-güvenlik-yaklaşımı)
9. [Veritabanı ve veri aktarımı](#9-veritabanı-ve-veri-aktarımı)
10. [Test edildiği gösterilen işler ve açık doğrulamalar](#10-test-edildiği-gösterilen-işler-ve-açık-doğrulamalar)
11. [Windows üzerinde mevcut çalıştırma](#11-windows-üzerinde-mevcut-çalıştırma)
12. [Linux şirket sunucusuna taşınma](#12-linux-şirket-sunucusuna-taşınma)
13. [Hata ve düzeltme geçmişi](#13-hata-ve-düzeltme-geçmişi)
14. [Açık işler ve sonraki geliştirmeler](#14-açık-işler-ve-sonraki-geliştirmeler)
15. [İT ekibine devir ve kabul kontrol listesi](#15-it-ekibine-devir-ve-kabul-kontrol-listesi)
16. [Dosya ve paket referansları](#16-dosya-ve-paket-referansları)

---

## 1. Projenin çıkış noktası ve hedefi

DengeERP; **Güvenlik Sistemleri, Haberleşme Sistemleri, POC ve Mobilite** teknik servis süreçlerinin parçalı telefon, WhatsApp, kağıt servis formu ve farklı sistemlerde tutulan kayıtlardan daha izlenebilir ve yönetilebilir bir yapıya taşınması için geliştirildi.

Operasyonun mevcut işleyişinde müşteri talepleri satış/operasyon personeline ve şeflere telefonla ulaşıyor, planlar oluşturuluyor, bazı tamamlamalar WhatsApp ve basılı servis formları üzerinden ilerliyordu. Haberleşme atölyesinde **Logo CRM**, süreç ve SLA tarafında **Flowick BPM** kullanımı/gündemi vardı. DengeERP'nin amacı bunlarla ilgili süreçleri düzenlemek, gereksiz çift kaydı azaltmak ve ileride entegrasyona uygun bir temel oluşturmaktır. **Logo CRM / Flowick'in tam otomatik entegrasyonu tamamlanmış kabul edilmez.**

Hedeflenen ana sorular:

- Bugün hangi işler geldi, planlandı, sahada, beklemede, tamamlandı?
- Hangi müşterinin hangi lokasyonundaki hangi seri numaralı cihaza ne yapıldı?
- Şef hangi personele, ne zaman, hangi aracı atadı?
- Personel gerçekte ne kadar yol/saha/bekleme süresi kaydetti?
- Planlı bakımlardan hangileri yapılmadı; bakım başına hangi cihazlar tamamlandı?
- İşler neden gecikti, aynı arıza tekrarlandı mı, hangi yedek parçalar kullanıldı?
- Eğitim sonrasında teknisyenin sahadaki yetkinliği gelişti mi?
- Yönetici günlük/haftalık/aylık özetleri ve raporları tek yerden alabiliyor mu?

Temel prensip: **Teknik servis kaydı tek seferde, izlenebilir biçimde açılsın; müşteri, cihaz, personel, zaman ve işlem geçmişi birbiriyle ilişkilensin.**

## 2. Çalışma yöntemi ve değişmez kurallar

Bu yöntem kullanıcı tarafından özellikle istendi ve defalarca teyit edildi:

1. **SSMS:** SQL Server şeması, sorgular, veri kontrolü ve yedek.
2. **Windows PowerShell:** `.NET` projesini bulma, `dotnet build`, `dotnet run` işlemleri.
3. **Tarayıcı:** Kullanıcı arayüzü / akış testleri.
4. **Tam ZIP teslim:** Yeni özellikler mevcut proje kaynaklarının üzerine geliştirilmiş, sürüm adı olan **tam proje ZIP'i** olarak verilsin; bir sürüm için onlarca el ile kod değişikliği istenmesin.
5. **Çalışan sürümü koru:** Yeni sürüm ayrı klasöre çıkarılsın; önce derlensin. Mevcut klasör silinmesin veya üzerine rastgele yazılmasın.
6. **SQL yedeği:** Veritabanı güncellemesi / sürüm geçişi öncesinde güncel `.bak` alınıp doğrulansın.
7. **Tek kopyalanabilir komut bloğu:** Gereksiz açıklama ve soru olmadan hızlı ilerleme; işlem sonucunu gördükten sonra sonraki aşama.
8. **Çalışan uygulamayı erken durdurma:** Eski PowerShell yalnızca yeni sürüm derlenip yedek doğrulandığında durdurulsun; aynı anda iki sürüm aynı `5050` portuna bağlanmasın.
9. **Test sonucu ile iddiayı ayır:** “Kodlandı”, “derlendi”, “servis açıldı”, “tarayıcıda çalıştı”, “SQL'de doğru kaydetti” farklı doğrulama seviyeleridir.
10. **Doğrulanmamış .bat çalıştırma yerine** daha önce kullanılan PowerShell/SSMS akışı tercih edilsin.

## 3. Teknik mimari ve ortamlar

### 3.1 Uygulama

- **Backend / Web API:** ASP.NET Core / **.NET 10**, proje `DengeERP.Api`.
- **Ön yüz:** Web arayüzü; proje içinde `wwwroot/index.html`, `app.js`, `styles.css` ve sonraki sürümde `ops120.js` / `ops120.css`.
- **Veri katmanı:** Microsoft SQL Server; geliştirici bilgisayarındaki örnek **SQL Server Express / `SQLEXPRESS`**.
- **Veri akışı:** Tarayıcı → API → merkezi SQL Server. Tarayıcının doğrudan SQL'e bağlanması hedeflenmedi.
- **Kayıt yaklaşımı:** Müşteri, iş emri, cihaz, seri no, plan, personel, işlem, süre ve geçmiş ilişkili kayıtlar olarak tutuluyor.

### 3.2 Windows pilot

- Proje çalışma alanı: `C:\DengeERP\App\`.
- Kullanıcıların daha önce kullandığı adres: `http://10.10.50.60:5050`.
- Bilgisayar kapatılıp yeniden açıldıktan sonra 21 Ekim'de Wi-Fi üzerinden **`10.10.50.137/24`** IP aldığı görüldü. Bu nedenle eski `.60` adresi açılmadı.
- Bu andaki muhtemel yeni LAN adresi: `http://10.10.50.137:5050` — **tarayıcıdan son doğrulama ayrıca yapılmalı**.
- PowerShell ekranında son V1.20 kaynak klasöründen `Now listening on: http://0.0.0.0:5050` ve `Application started` çıktıları görüldü.
- Geliştirme modunda (`Hosting environment: Development`) çalıştığı görüldü. Bu biçim **üretim sunucusu yapılandırması değildir**.

### 3.3 Şirket Linux sunucusu için hedef

- İT'nin yönetebildiği şirket altyapısında **Ubuntu Server 24.04 LTS x64** test/pilot sanal sunucusu.
- Hedef sunucu IP: **`10.10.50.16/24`**. Bu bir sunucu IP'sidir; bağlı ağ **`10.10.50.0/24`**, maske `255.255.255.0`.
- Başlangıçta iç ağ pilot URL: `http://10.10.50.16:5050`.
- Mimari: **Nginx (`10.10.50.16:5050`) → Kestrel (`127.0.0.1:5051`) → SQL Server**.
- Sürekli çalışma: `systemd` servisi, sürümlü `/opt/dengeerp/releases/...` dizinleri.
- SQL için ayrı **`DengeERP_TEST`** kopyası; eski Windows üretim/pilot DB'sine doğrudan migration yaptırılmaması.
- Kurumsal DNS adı + HTTPS sertifikası, VPN/şirket ağı ve firewall kuralları İT ile tanımlanacak.
- IP'nin ağ cihazında sabitlenmesi, geçit/DNS ve routing değerleri İT sorumluluğundadır; paket bunları zorla değiştirmez.

## 4. Sürüm geçmişi V1–V1.20.1

> **Tarih:** Aşağıdaki geliştirme/talep ve testlerin çoğu 13–21 Ekim 2026 tarihlerinde gerçekleşti. **Durum** sütunu kaynak paket geçmişi ile sohbet içindeki ekran/test teyitlerinden çıkarılmıştır.

| Sürüm | Geliştirilen başlıca işler | Durum / önemli not |
|---|---|---|
| **V1 / V1.1** | SQL tabanlı kullanıcı/rol/yetki, iş emirleri, planlama, teklif/PDF, filtreli Excel raporu, ağ pilotu; kullanıcı/Foreign Key hotfix | Pilot temel altyapı |
| **V1.2** | Seri numarası giriş düzeltmeleri | Kaynak changelog'larda korunuyor |
| **V1.3** | Mevcut kullanıcıyı, rol/birim/izinlerini düzenleme; `PUT /api/users/{id}` | Kaynak pakette |
| **V1.4** | Kiralama yönetimi, `KIR-YYYYMM-####`, personel/organizasyon yönetimi, hesap bağlama, yetki şablonları | Kaynak pakette |
| **V1.5** | Güvenlik cihaz kütüğü, bakım otomasyonu, Logo CRM alanlarını örnek alan Haberleşme Atölyesi | Windows'ta derlendiğine dair ekran var |
| **V1.6** | Gün/Hafta/Ay Planlama Takvimi; sağda plansız havuz; filtre/çakışma | **Windows'ta derleme ve 5050 açılışı doğrulandı** |
| **V1.7** | Önce ana bakım emri + alt cihaz kayıtları; kişi bazlı ücret görüntüleme izni | **V1.8'de iş emri tasarımı değiştirildi** |
| **V1.8** | **1 cihaz = 1 PB iş emri**; X-Ray/kapı için ayrı dijital checklist, seri/bölge/not, tıklanabilir KPI kutuları | **Derlendi, başlatıldı; KPI kutuları kullanıcıca çalışır doğrulandı** |
| **V1.9** | Aynı lokasyondaki işlerde toplu planlama ve ekip ataması, İş Emirleri'nde toplu atama; seri no `text` | **Derlendi/çalıştırıldı; toplu atama kullanıcıca çalışır doğrulandı** |
| **V1.10** | Günlük servis vs bakım ayrımı; personel gerçek zaman kayıtları; 8 sayfalı Excel raporu | V1.11'in içinde korundu |
| **V1.11** | Kompakt lokasyon/şehir takvimi, saha adres ve irtibat detayları, raporlar/personel KPI | **Derlendi, güvenlik bağımlılığı güncellendi, uyarılar temizlendi, başlatıldı**; ekranların tümü UAT'den geçmedi |
| **V1.12** | Çoklu kiralama ürünü/kişi, depo 1–3, seri bazlı envanter, sevk–kurulum–devreye alma–toplama–depo aşamaları | **Derlendi ve başlatıldı**; ayrıntılı akış testleri eksik |
| **V1.13** | Eğitim kataloğu, yıllık eğitim, katılım/sınav, yetkinlik, saha gözlemi ve 30/60/90 takip | **Derlendi ve başlatıldı**; kayıt testleri tamamen sonuçlandırılmadı |
| **V1.14** | Canlı teknisyen zaman sayacı, faaliyet bazlı süre ve yönetsel KPI | **Derlendi ve başlatıldı**; gerçek zaman kayıtlarının uçtan uca testi eksik |
| **V1.15–V1.20 birleşik** | Operasyon merkezi, SLA, tekrar arıza, bekleme nedenleri, mobil online görünüm, yedek parça, ERP içi uyarılar, iş maliyeti | **V1.20 tek ZIP olarak derlendi ve başlatıldı**; bütün modüllerin canlı kabul testleri bitmedi |
| **V1.20.1** | Raporlar/Excel aktarımında boş `start` / `end` tarih parametresi hotfix | `app.js` düzeltildi; **Excel indirmenin çalıştığı kullanıcıca teyit edildi**. Linux teslim paketi bu düzeltmeyi içeriyor. |

### 4.1 V1.5 başlangıç veri aktarımı

Kaynak sürüm notlarına göre **1.324 güvenlik cihaz/kütük satırı** ve **87 firma/bakım sözleşmesi** pilot verisine aktarılmak üzere işlendi. Bunlar kaynak paket beyanlarıdır; **mevcut canlı SQL satır sayısı olarak ayrıca doğrulanmış değildir**.

### 4.2 Kritik mimari değişiklik — bakım iş emri

- İlk öneri: tek ana bakım iş emri altında çoklu cihaz kapatma.
- Kullanıcı kararı: **ana bakım emri değil; kaç cihaz varsa o kadar ayrı bakım iş emri.**
- V1.8'de buna geçildi. Örnek **AKYAKA AVM: 9 X-Ray + 8 kapı dedektörü = 17 ayrı iş emri**. Daha önce verilen “9 + 10 = 19” yalnızca tasarım örneğiydi; o dönemdeki sözleşme listesinde 9 + 8 bulunuyordu.
- İleride müşteri, seri numarası, model, bölge ve bakım geçmişi **cihaz bazında** izlenecek.

## 5. Modüller ve fonksiyonel kararlar

### 5.1 Ana Panel, iş havuzu ve iş emirleri

- Açık iş, müşteri talebi, planlandı, sahada, atölyede, beklemede, tamamlandı, kritik iş kartları.
- **Sayı kutuları tıklanabilir:** ilgili işlerin kategoriye ayrılmış listesi açılmalı; firma, arıza, personel ve iş numarası ile inceleme yapılabilmeli.
- İş emri numarası otomatik; iş geçmişi ve durum değişimi SQL'de.
- İş kategorileri günlük servis/arıza, **planlı/yıllık bakım**, atölye, POC, Mobilite vb. ayrılmalı. Planlı bakım işleri normal arıza listesinde sayıyı şişirmemeli.
- Telefonla çözülen, uzaktan çözülen ve yerinde müdahale kayıtlarının ayrılması hedeflendi.
- Çoklu teknisyen ataması mümkün olmalı.
- İlgili iş emrinden cihaz, müşteri, planlama, malzeme, süre ve tarihçe görülebilmeli.

### 5.2 Planlama Takvimi ve toplu atama

- Menüye tıklanınca doğrudan **Gün / Hafta / Ay** takvimi açılsın.
- Önceki/bugün/sonraki gezinmesi; birim, şef/teknisyen ve personel filtreleri.
- İş kartında müşteri, saat, lokasyon, birim, teknisyen, şef, araç ve durum.
- Plansız işler sağda **Planlanmayı Bekleyenler** havuzunda.
- **Toplu seçim:** aynı müşteri ve lokasyon cihazları işaretlenip tek işlemde tarih/saat, ekip, şef ve araç ataması.
- **İş Emirleri → Toplu Atama:** planı değiştirmeden birden fazla açık işe ekip atanabilsin.
- Şef/teknisyen/araç çakışması denetlensin; aynı toplu ziyaretin kendi işleri birbirini yanlış çakışma göstermesin.
- Uzun cihaz listesi yerine **aynı gün + müşteri + lokasyon + şehir** için **tek kompakt ziyaret kartı**; kart açılınca altındaki bağımsız iş emirleri.
- Takvim sonsuza kadar aşağı uzamasın: haftalık/aylık görünümde kart sayısı sınırı ve fazlasına geçiş.
- Planlanan yer: tesis, il, ilçe, açık adres, bina/kat, cihaz bölgesi, saha yetkilisi, telefon ve giriş/otopark notu.
- Kayıtlı cihaz/bakım kütüğünden önerilsin; gerekirse **elle değiştirilebilsin**.
- Plansız havuzda **müşteri, lokasyon, seri no ve iş emri araması** V1.10 geliştirmesinde eklendi.

### 5.3 Güvenlik Cihaz Kütüğü

- X-Ray, kapı tipi metal dedektörü ve diğer güvenlik cihazları ayrımı.
- Marka/model/cihaz türü/seri no/müşteri/lokasyon/ilgili kişi/kurulum durumu.
- Seri numarası **metin**; harf, rakam, tire, nokta, `/` ve baştaki sıfırlar korunmalı.
- Cihaz geçmişi, bakımlar, iş emirleri ve garanti durumu cihazla ilişkilendirilmeli.

### 5.4 Planlı Bakım ve dijital servis formu

- Bakım sözleşmesi, yıllık frekans ve tamamlanan bakım adedi; vadesi gelen bakımların otomatik iş emri üretimi.
- Her cihaz için ayrı **`PB-YYYYMM-####`**.
- Teknisyen iş emrinde **seri no, bulunduğu bölge, yapılan işlem, yedek parça, not, servis sonucu** bilgilerini girsin.
- **X-Ray:** 11 kontrol başlığı; **kapı tipi metal dedektörü:** 10 farklı kontrol başlığı.
- Kontrol durumu: Bekliyor / Uygun / Uygunsuz / Kontrol Edilemedi; her kontrol işaretlenebilir.
- Uygunsuz cihazın bakım iş emri otomatik “tamamlandı” olmamalı; aksiyon takibi sürsün.
- İş emirleri kapatıldıkça cihaz geçmişine yazılsın ve bakım dönemi sayacı yalnızca gereken koşullarda bir kez güncellensin.
- Bakım formunun tasarımında Denge Elektronik'in gönderdiği **basılı Teknik Servis Formu** örnek alındı: firma/adres, başlangıç/bitiş saatleri, servis türü, ürün/seri no, kullanılan parçalar, yapılan işlem, sonuç ve onay.

### 5.5 Haberleşme Atölye

- Logo CRM'deki kabul/onarım alanlarını örnek alan kayıt: müşteri/kişi/telefon, marka/model, seri no, garanti, servis türü, şikâyet, cihaz durumu, onarım, teslim/kargo ve aksesuarlar.
- Desteklenen örnek marka seçenekleri: HYTERA, HYT, HQT, MOTOROLA, KIRISUN, ASELSAN.
- Aksesuar 1–5 seçimleri; atölye servis kaydı ve iş emri bağlantısı.
- Operasyon uzmanı kaydının laboratuvara kabul, arıza teşhisi, müdahale ve kapanışla ilişkilendirilmesi hedefi.
- **Logo CRM entegrasyonu henüz ayrı geliştirme/görüşme konusudur**; alanların benzerliği otomatik entegrasyon anlamına gelmez.

### 5.6 Kiralama, depo ve operasyon

- Bir kiralamaya **birden fazla ürün satırı**, her satırda marka/model, adet, seri numarası ve not.
- Aynı müşteri için **birden fazla irtibat kişisi**; satın alma ve saha sorumlusu farklı olabilir. Kişi adı, organizasyondaki görevi, telefon/e-posta.
- İlk adları **Depo 1 / Depo 2 / Depo 3**; ileride adlar değiştirilebilir.
- Envanter: ürün, depo, seri, adet; hazır / eksik / kirada / kontrolde durumları; eksik malzeme notları.
- Aynı seri numaralı cihaz eşzamanlı iki kiralamaya tahsis edilmesin.
- Kiralama iş akışı: **Sevk edildi → Kurulum yapıldı → Devreye alındı → Toplandı → Depoya alındı**. Farklı teknik ekiplerin yaptığı aşamalarda ayrı ekip, zaman ve not kaydı.
- Depoya dönen cihaz otomatik hazır sayılmasın; önce **kontrol** aşaması.

### 5.7 Teklif ve finansal görünürlük

- Kalemli teklif, miktar, KDV, iskonto, durum, PDF oluşturma; fiyat/maliyet verilerinin yetkiye göre gösterimi.
- **Fiyat sütununu sadece gizlemek yeterli değil:** API de yetkisiz kullanıcıya fiyat/maliyet alanını vermemeli.
- Yönetici hangi kullanıcıya `finance.prices.view` verileceğini kişi bazında belirleyebilmeli; sabit unvan listesi istenmiyor.
- V1.20'de işe bağlı gelir, süre × iç saatlik tarife, parça maliyeti, diğer maliyetler ve **tahmini fark**. Bu değerler resmi kâr/finans tablosu sayılmamalı.

### 5.8 Eğitim, Yetkinlik ve Personel Gelişimi

- **Kendi eğitimini tanımla:** eğitim nedeni, beklenen davranış, ölçülebilir başarı kriteri, süre, zorunluluk, kontrol maddeleri.
- Bir yıllık çalışan bazlı gelişim planı; eğitim atama, katılım, sınav/ön-son değerlendirme ve eğitmen kaydı.
- **Yetkinlik matrisi:** 1–4 mevcut ve hedef seviye; teknik, İSG, müşteri ilişkileri, rapor disiplini vb.
- Eğitimin gerçek sahada uygulanması için **iş emrine bağlı saha gözlemi**.
- 30/60/90 gün gözlem, kanıt ve aksiyon; kritik İSG uygunsuzluğu ortalama puan içinde kaybolmamalı.
- Kişisel gelişim kartı, birim/şef/kişi bazlı yönetim özetleri.
- Eğitim saatini tek başarı ölçütü sayma: **eğitim öncesi ve sonrası saha davranışı** esas olsun.

### 5.9 Saha / Zaman Takibi

- İş emrinde **Yola çıktım → Sahadayım → Mola → Devam → Bitir** şeklinde canlı sayaç kullanımı.
- Faaliyetler: yol, saha çalışması, bekleme, uzaktan destek, atölye, test ve mola.
- Her personelin aynı anda en fazla **bir aktif sayacı**; ekiptekiler kendi hesaplarından ayrı zaman kaydı oluşturur.
- Sunucu saatine göre başlangıç/bitiş; manuel süre kayıtlarıyla çakışma kontrolü.
- **Mola çalışılan kişi-saat hesabına dahil değil.** Kapatmayı unutulan sayaç yönetici tarafından gerekçeli olarak iptal edilebilir.
- Açık sayaç varken iş emri kapatma engellenir; sayaç bitirmek tek başına iş kapatmaz.
- Bu sistem **bordro / resmi mesai puantajı değildir**; servis faaliyet süresini ölçer.

### 5.10 Operasyon Merkezi, SLA ve bildirimler (V1.20)

- Açık/geciken işler, bugün/yarın plan, bakım–günlük servis ayrımı, iş yükü.
- Öncelik bazlı **takvim saati** çözüm SLA hedefi; sözleşme, tatil ve çalışma takvimi bazlı tam SLA motoru henüz yok.
- Aynı cihaz/seri numarasındaki tekrar arıza analizi.
- Bekleme nedeni ekleme/kaldırma ve geçmiş: malzeme, müşteri onayı, teklif vb.
- **ERP içi** geciken iş, yarın planı, eksik stok, eğitim tarihi uyarıları; açık operasyon ekranı yenilenerek izlenir.
- **Otomatik e-posta/SMS/push gönderimi hazır değildir**.
- Mobil teknisyen görünümü **çevrimiçi** kullanılabilir; çevrimdışı yazma/senkronizasyon henüz yok.

### 5.11 Yedek parça ve stok yönetimi (V1.20)

- Depo bazında parça kataloğu ve stok seviyeleri.
- Giriş ve iş emrine bağlı parça çıkışı, hareket geçmişi.
- Negatif stok engeli ve az stok uyarıları.
- Kiralama cihaz envanteri ile servis yedek parça stoğu, farklı iş mantıkları olarak izlenmeli.

## 6. Operasyon akışları ve iş kuralları

### 6.1 Uçtan uca servis süreci

```text
Müşteri arızası / servis talebi
    ↓
Operasyon / ilgili çalışan iş kaydını açar
    ↓
Teknik Servis iş havuzu (ilgili birim)
    ↓
Şef kontrol eder, tarih/lokasyon/rota planlar
    ↓
Bir veya birden fazla teknisyen + araç ataması
    ↓
Yola çıkış / sahaya varış / müdahale / parça kullanımı
    ↓
Servis veya cihaz türüne özel kontrol listesi
    ↓
Teknisyen notu, süre, sonuç, müşteri onayı/kanıt
    ↓
İş emri kapanışı → depo/irsaliye/fatura süreçleri
    ↓
Yönetim raporları / SLA / KPI / tekrar arıza analizi
```

Gerçek hayatta basılı servis formu ve WhatsApp üzerinden dönen süreçler bulunduğu için **dijital kayıt disiplini** ve personel eğitimi kritik.

### 6.2 Planlı bakım

Bir sözleşmenin bakım periyodu geldiğinde çok sayıda cihaz için **ayrı iş emirleri** üretilir. Yönetici aynı lokasyondaki işleri **tek seferde planlayıp ekip atar**; takvim **tek ziyaret kartı** gösterebilir; ancak teknisyen her cihaz için **ayrı seri no, bölge, checklist ve kapanış** yapar.

### 6.3 Çoklu kişi ve tek doğru kayıt

- Çoklu teknisyenin süreleri bir iş emrinde ayrı ayrı tutulur.
- Teknisyenin aynı saatlerini iki işe yazması engellenir.
- Aynı cihazın farklı kiralamalara çift tahsisi engellenir.
- Planlı bakım seri numarası yoksa gerçekte bulunmayan seri numarası uydurulmaz; cihaz eşleştirmesi ayrıca yapılır.
- İleride Logo CRM, Flowick BPM ve araç takiple entegrasyon düşünüldüğünde **asıl kayıt sistemi** ve tekilleştirme kuralları belirlenecek.

## 7. Raporlar ve yönetsel KPI'lar

### 7.1 Rapor kırılımları

- **Günlük servis/arıza** ve **planlı/yıllık bakım** ayrı.
- Birim, şef, teknisyen, müşteri, lokasyon, iş türü, durum, tarih aralığı, iş emri.
- Açık, beklemede, geciken, tamamlanan, kritik işler; gecikme ve bekleme nedenleri.
- Personel başına iş, faaliyet türü ve lokasyonda geçirilen süreler.
- Saha / yol / bekleme / mola; **kişi-saat hesabı** (örneğin iki kişinin iki saat çalışması = dört kişi-saat).
- Bakım tamamlama, kapasite, tekrar ziyaret/arıza ve eğitim-sonrası gelişim.
- Malzeme giriş/çıkışı ve kayıtlı maliyetler.

### 7.2 Rapor çıktıları

V1.10/V1.11 kaynak notlarındaki 8 sayfalı Excel:

1. Yönetim Özeti
2. Günlük Servis
3. Planlı Bakım
4. Birim Durum
5. Aylık Özet
6. Personel KPI
7. Süre Hareketleri
8. Müşteri Lokasyon

**Önemli:** Bu raporlardaki otomatik çapraz özetler **pivot benzeri hazırlanmış tablolardır**; Excel'in yerel düzenlenebilir `PivotTable` nesneleri oldukları iddia edilmemelidir. Kullanıcı sonradan gerçek otomatik PivotTable istemişti; bu özellik ayrıca doğrulanmalı/iyileştirilmeli.

**Veri doğruluğu:** Tahmini iş süresi gerçek çalışma süresi yerine kullanılmasın. Geçmişte süre kaydı olmayan iş emri **0 saat çalışıldı** diye gösterilmesin; **süre kaydı eksik** olarak belirtilsin.

## 8. Kullanıcı yetkileri ve güvenlik yaklaşımı

### 8.1 Roller ve kapsam

- Sistem yöneticisi, üst yönetim, teknik servis yönetimi, birim şefi, operasyon, teknisyen, atölye vb. roller.
- Birim ve işlem bazlı izinler: görüntüleme, ekleme, atama, planlama, kapatma, rapor, export, maliyet/fiyat, eğitim yönetimi/gözlem.
- Yetki **kişiye özel değiştirilebilir**; yalnızca unvana göre sabit karar verilmesin.
- Ücret ve maliyet API üzerinden yetkisiz kişiye gitmesin.
- Örnek izinler: `finance.prices.view`, `training.view`, `training.manage`, `training.observe`, `training.export`, `reports.view`, `reports.export`, `operations.manage`, `warehouse.manage`, `finance.costs.manage`.
- Yeni yetkiler eski özel kullanıcı profillerine otomatik dağıtılmaz; yönetici tanımlar.

### 8.2 Henüz tamamlanmamış kurumsal güvenlik işleri

- Windows geliştirme ortamında görülen `Development` yapılandırması üretimde kullanılmamalı.
- Oturum yönetimi, API uçları için yetki testleri, kimlik doğrulama, parola/yetki yaşam döngüsü ve işlem denetimi profesyonel olarak gözden geçirilmeli.
- Dış internete açmadan önce **HTTPS**, uygun sertifika, erişim sınırı/VPN, loglama, güncelleme ve yedek/restore testi.
- SQL yedekleri, kullanıcı bilgileri ve personel kayıtlarının **KVKK / şirket bilgi güvenliği** süreçlerine göre korunması.
- Kurulum ZIP'inin Linux üzerinde paketlenmiş olması **güvenlik denetimi yapıldığı anlamına gelmez**.

## 9. Veritabanı ve veri aktarımı

Kaynak paket içinde bulunan önemli SQL dosyaları:

```text
Database/DengeERP_Update.sql
Database/DengeERP_V15_Schema.sql
Database/DengeERP_V15_Seed.sql
Database/DengeERP_V17_Schema.sql
Database/DengeERP_V18_DeviceWorkOrders.sql
Database/ZZ_V110_WorkOrderTimeLogs.sql
Database/ZZ_V111_PlanSites.sql
Database/ZZ_V112_RentalInventoryOperations.sql
Database/ZZ_V113_TrainingDevelopment.sql
Database/ZZ_V114_LiveTimeTracking.sql
Database/ZZ_V120_Operations.sql
```

Sohbette SSMS ile doğrulanmış bazı tablolar:

| Tablo | O gün görülen kolon sayısı |
|---|---:|
| `MaintenanceContracts` | 15 |
| `MaintenancePlans` | 9 |
| `SecurityDevices` | 16 |
| `WorkOrders` | 20 |

Bu sayılar **14 Ekim'deki sorgunun sonucudur**; V1.20 sonrası aynı kalmış olmaları beklenmemeli.

Sürüm scriptlerinin önemli kısmı idempotent (önceden var mı kontrol ederek ekleme) tasarlanmıştır. Bununla birlikte **yedek olmadan canlıya migration yapılmaz**. Daha eski sürüme yalnızca kod klasörünü geri almak, SQL şemasını otomatik geri almaz.

### SQL yedekleme ve doğrulama örneği (SSMS)

```sql
USE master;
GO
DECLARE @Klasor NVARCHAR(400) =
    CONVERT(NVARCHAR(400), SERVERPROPERTY('InstanceDefaultBackupPath'));
DECLARE @Dosya NVARCHAR(500) = @Klasor +
    CASE WHEN RIGHT(@Klasor, 1) = '\' THEN '' ELSE '\' END +
    'DengeERP_GUVENLI_YEDEK_' +
    FORMAT(GETDATE(), 'yyyyMMdd_HHmmss') + '.bak';

BACKUP DATABASE DengeERP TO DISK = @Dosya
WITH COPY_ONLY, CHECKSUM, INIT, STATS = 10;

RESTORE VERIFYONLY FROM DISK = @Dosya WITH CHECKSUM;
SELECT @Dosya AS YedekDosyasi;
```

Bu **örnek** yalnızca ilgili sunucuya yedek yazma yetkisi varsa çalışır. `RESTORE VERIFYONLY` faydalıdır; **gerçek geri yükleme denemesinin yerini tutmaz**.

## 10. Test edildiği gösterilen işler ve açık doğrulamalar

### 10.1 Kullanıcının ekran/konsol sonucu verdiği doğrulamalar

- V1.6, V1.7, V1.8, V1.9, V1.11, V1.12, V1.13, V1.14 ve V1.20 için çeşitli `.NET 10` derleme/başlatma ekranları paylaşıldı.
- V1.8 Ana Panel / Planlama **KPI sayı kutuları**: “çalıştı” teyidi.
- V1.9 **toplu ekip ataması**: “toplu olarak atamasını yapabiliyorum” teyidi.
- V1.11 **derleme 0 uyarı**: eski bağımlılık güncellenip nullable değer uyarıları giderildikten sonra.
- V1.20.1 **Excel dışa aktarma**: “dosya iniyor” teyidi.
- V1.20 Windows'da `Now listening on: http://0.0.0.0:5050` ve `Application started` mesajları görüldü.
- SQL Server yedekleme sorgusunun başarıyla çalıştığı ve yedek envanterinin göründüğü ekranlar paylaşıldı.

### 10.2 Tam kabulü hâlâ kanıtlanması gerekenler

- Her modülde **oluştur → kaydet → tekrar aç → güncelle → kapat → raporda gör** testi.
- V1.8 ayrı cihaz PB iş emirlerinin örnek gerçek müşteri üzerinde seri numaralı tek tek kapanışları.
- Kiralamada farklı marka/model, çoklu kişi, depo–stok ve farklı ekiplerin aşamalarının uçtan uca tutarlılığı.
- Eğitimde katılım, saha gözlemi, 30/60/90, yetkinlik matrisi ve hedef gelişim raporu.
- Canlı zaman sayacının gerçek iş emri / birden çok teknisyen / mola / açık sayaç / çakışma kuralları.
- V1.20 stok düşümü, tekrar arıza, SLA ve maliyet hesaplarının örnek kayıtlarla sınanması.
- Rol değişiminde hassas finans API'larının gerçekten veri sızdırmaması.
- Linux üzerinde `.NET publish`, SQL bağlantısı, migration yönetimi, `systemd`, Nginx ve HTTPS testi.
- Yedeklerin **ayrı test veritabanına geri yüklenmesi** ve işlevlerin çalışması.

**İş kuralı:** Derleme başarılı veya menü açıldı diye modülün üretim kabulü tamamlanmış sayılmasın.

## 11. Windows üzerinde mevcut çalıştırma

**Windows pilotun son kaynak sürümü:** `DengeERP_V1_20_TEMIZ_*` adlı klasörlerde V1.20 üzerine uygulanan **V1.20.1 `app.js` düzeltmesi**. Son gözlenen klasör örneği:

```text
C:\DengeERP\App\DengeERP_V1_20_TEMIZ_20261016_082529\DengeERP.Api
```

PowerShell komutu:

```powershell
$klasor = Get-ChildItem "C:\DengeERP\App" -Directory |
    Where-Object { $_.Name -like "DengeERP_V1_20_TEMIZ_*" } |
    Sort-Object CreationTime -Descending |
    Select-Object -First 1

if (-not $klasor) { throw "V1.20 klasoru bulunamadi!" }

$proje = Get-ChildItem $klasor.FullName -Recurse -Filter "DengeERP.Api.csproj" |
    Select-Object -First 1

if (-not $proje) { throw "Proje dosyasi bulunamadi!" }
Set-Location $proje.DirectoryName
dotnet run --urls "http://0.0.0.0:5050"
```

- Mevcut Windows PowerShell kapanırsa elle başlatılan uygulama da durur.
- LAN IP adresi DHCP ile değişebilir. 21 Ekim'de `10.10.50.137/24` görüldü; kalıcı IP için İT'den DHCP rezervasyonu istenebilir.
- İşletim sistemi bilgisayarı şirket sunucusu yerine sürekli barındırma için kullanılmamalı.
- Aynı portu iki uygulama kullanmasın.
- Kod değişikliklerini uygulamak için dosyanın mevcut sürümü ile hangi process tarafından kullanıldığı doğrulansın; gerekiyorsa kontrollü yeniden başlatılsın.

## 12. Linux şirket sunucusuna taşınma

### 12.1 Teslim edilen paket

```text
DengeERP_V1_20_1_LINUX_IT_TAM_TESLIM_10_10_50_16.zip
```

Paketteki ana içerik:

```text
BASLA.txt
IT_ICIN_ILK_OKU.md
DengeERP.Api/                     # .NET API + web arayüzü + SQL scriptleri
KAYNAK_KODLARI_V1_20_1.zip         # bağımsız tam kaynak arşivi
TUM_KAYNAK_KODLARI_TEK_DOSYA.txt   # inceleme amaçlı birleşik metin
KAYNAK_DOSYA_LISTESI_SHA256.txt
PAKET_BILGISI.json
linux/01_sunucuyu_hazirla.sh
linux/02_yayinla.sh
linux/03_dogrula.sh
linux/04_geri_don.sh
linux/dengeerp.env.example
linux/dengeerp.service
linux/nginx/dengeerp-http.conf
linux/nginx/dengeerp-https.conf.example
linux/README_KURULUM_TR.md
linux/SQL_HAZIRLIK_YEDEK.sql
```

**İT ayrıca sağlayacak:** gerçek veritabanı kopyası ve SQL hesabı/şifresi, Ubuntu VM ve ağ/DNS, HTTPS sertifikası, güvenlik duvarı/VPN, yedekleme hedefi. Sır veya canlı SQL yedeği kaynak ZIP'in içinde değildir.

### 12.2 Ubuntu kurulum sırası (İT)

ZIP sunucuya aktarıldıktan sonra (dosya adını gerçek adla kontrol ederek):

```bash
sudo apt-get update && sudo apt-get install -y unzip
mkdir -p ~/dengeerp-setup
unzip -q ~/DengeERP_V1_20_1_LINUX_IT_TAM_TESLIM_10_10_50_16.zip -d ~/dengeerp-setup
cd ~/dengeerp-setup
sudo bash linux/01_sunucuyu_hazirla.sh
sudo nano /etc/dengeerp/dengeerp.env
sudo bash linux/02_yayinla.sh
sudo bash linux/03_dogrula.sh
```

- `DengeERP__RunDatabaseSetupOnStartup=false` **test DB restore edilmeden değiştirilmemeli**.
- Örnek SQL bağlantısında `Encrypt=True;TrustServerCertificate=False` hedefleniyor; SQL sunucusunun sertifika zinciri doğru kurulmalı.
- Linux altında .NET 10 `dotnet publish -c Release` uygulanır.
- Uygulama dış LAN'da Nginx `:5050`, içeride Kestrel `127.0.0.1:5051` olarak çalışır.
- Ağ izni başlangıçta `10.10.50.0/24` ve localhost ile sınırlı.
- `DengeERP_TEST` ayrı SQL veritabanına bağlanır; **canlı Windows SQL'e farkında olmadan migration yok**.
- HTTP, yalnızca **kapalı iç ağ pilotu** için geçici; kurumsal kullanım öncesi HTTPS, yetkiler, güvenlik ve geri yükleme testleri yapılmalı.
- `linux/04_geri_don.sh` uygulama dosyalarını önceki Linux sürümüne çevirmeye yarar, **SQL'i geri almaz**.
- Pakette **önceden Linux'ta derlenmiş DLL yok**; kurulumda build/publish yapılır.

### 12.3 Lisans/sertifika görüşmesi

- Ubuntu + .NET 10 + Nginx ücretsiz kullanılabilir; SQL Server Express ücretsiz sürüm olmakla beraber kapasite/lisans sınırlarına dikkat edilmeli.
- Windows Server kullanılırsa işletim sistemi ve gerekli erişim lisansları ayrıca değerlendirilmeli.
- **SSL/TLS sertifikası**, Windows/SQL Server yazılım lisansı ile aynı şey değildir.
- Şirket DNS alt alan adı üzerinden HTTPS düşünüldü; sertifika şirket içi CA ya da uygun ACME/Let's Encrypt yöntemi ile alınabilir.
- Sertifikayı almak tek başına uygulamanın güvenli olduğunu garanti etmez.

## 13. Hata ve düzeltme geçmişi

1. **Yedek dosya yolu:** `InstanceDefaultBackupPath` sonuna `\` eklenmediğinde `...\BackupDengeERP_...` hatası görüldü. Sorguya gerektiğinde `\` ekleme kontrolü eklendi.
2. **V1.8 ZIP açma:** Aynı hedef klasörde dosyalar varken `Expand-Archive` üstüne yazma hatası. Çözüm: her kurulumda tarih-saat ekli **yeni temiz klasör**.
3. **V1.11 bağımlılık uyarıları:** `System.Security.Cryptography.Pkcs 9.0.18` için NU1902/NU1903 görüldü; `9.0.21` paketine güncellendi; kalan `CS8629` null tarih uyarıları düzeltilip `0 uyarı` derleme gösterildi.
4. **V1.20 boş tarih:** Rapor Excel export isteğinde `Nullable<DateOnly> start` için `""` gönderildiğinde HTTP bind hatası oluştu. `app.js` dosyası yedeklenerek boş `start/end` parametrelerini URL'den çıkaran düzeltme uygulandı; Excel indirmenin çalıştığı teyit edildi. Konsolda önceki hata loglarının kalmış olabileceği konuşuldu; temiz yeniden istek log testleri yine yararlı.
5. **V1.14 ZIP indirme:** ChatGPT sohbet linkinden tekrarlı indirme hatası alındı. Paket **ChatGPT Kitaplık'a** aktarıldı ve kullanıcı oradan indirebildi.
6. **Windows IP değişikliği:** Eski `10.10.50.60:5050` erişimi PC yeniden başladıktan sonra açılmadı; `10.10.50.137/24` Wi-Fi IP'si bulundu. Sorun koda bağlanmadı; yeni IP üzerinden deneme önerildi.
7. **Kaynak sürekliliği:** V1.20 ve Linux paketleri, Windows'ta kullanıcıca doğrulanan geliştirmelerden türetildi; her yeni sürümde hem kod hem veritabanı geri dönüş planı gerekli.

## 14. Açık işler ve sonraki geliştirmeler

**Öncelik 1 — Üretim öncesi kritik:**

- V1.20.1'in Windows pilotta eksiksiz **uçtan uca kabul testi**, hataların listelenmesi.
- Güncel SQL tam yedeği ve **restore testi**; yükseltmede veri migrasyonunun geri dönüş senaryosu.
- İT ile Linux test sunucusu ve SQL test kopyası; `systemd`, Nginx, TLS bağlantısı, saat dilimi ve dosya izinleri.
- Kimlik doğrulama, API yetkileri, maliyet/fiyat alanları, oturum yönetimi, demo hesaplar, loglama ve erişim incelemesi.

**Öncelik 2 — Operasyonel kalite:**

- Teknik servis basılı formunun tüm kritik alanlarının dijital formda eksiksiz bulunması ve müşteri onayı/kanıt akışı.
- Gerçek müşteri kayıtlarıyla cihaz bazlı bakım örneklemesi ve 17 iş emri senaryosunun kapanış testi.
- Kiralama stok/kiralık cihaz geçişleri ve depo hareketi uzlaştırması.
- İş planı/rota verimliliği: yakın tarihlerde aynı bölgeye tekrar ziyaret, telefonla/uzaktan çözülebilecek arızalar, personel ve araç plan uyumu.
- Veri kalitesi: şehir/bölge/seri no, müşteri adı tekilleştirme, eksik iş emri alanları.
- Yönetim ekranlarında **sahadan doğrulanmış** gerçek süre, gecikme ve tekrar arıza verilerinin kullanılması.

**Öncelik 3 — Önceden tartışılan ama eksik/gelecek işlevler:**

- Mobil teknisyen **offline kayıt + güvenilir senkronizasyon**.
- Araç takip API, GPS/koordinat ve gelişmiş rota optimizasyonu.
- Logo CRM / Flowick BPM bağlantılarının sınırları, çift kayıt sorunu, sistemler arası iş akışı.
- Otomatik e-posta/SMS/push bildirimleri ve güvenli SMTP/mesaj servisi yapılandırması.
- Native Excel PivotTable ihtiyacı ile mevcut pivot-benzeri özet farkının kapatılması.
- SLA'nın müşteri sözleşmesine, çalışma saatlerine ve resmi tatillere bağlanması.
- İrsaliye/faturalama/muhasebe/depo entegrasyonlarının tamamlanması.
- Cihaz bazında tam garanti/servis/arıza/onarım yaşam döngüsü raporu ve müşteri onayı.
- İT ile **kalıcı HTTPS DNS adı** ve üretim işletim prosedürü.

## 15. İT ekibine devir ve kabul kontrol listesi

### Teslimat öncesi

- [ ] Kaynak ZIP ve SHA-256 dosyası teslim edildi.
- [ ] Windows çalışan sürüm klasörü silinmedi.
- [ ] Son V1.20.1 tarih hotfix'i Linux pakette yer alıyor.
- [ ] SQL `.bak` güvenli alana kopyalandı, `RESTORE VERIFYONLY` geçti.
- [ ] SQL verisinin `DengeERP_TEST` test kopyası hazırlandı.
- [ ] Kurulum için sunucu IP'si `10.10.50.16/24`, DNS/gateway ve erişim portu teyit edildi.
- [ ] Yetkili sistem kullanıcıları ve veritabanı bağlantı sırları İT tarafından belirlendi.

### Kurulum ve operasyon

- [ ] `dotnet publish` başarılı.
- [ ] `systemctl status dengeerp` aktif.
- [ ] `nginx -t` başarılı.
- [ ] `http://10.10.50.16:5050/api/health` başarılı; DB test bağlantısı var.
- [ ] Kullanıcı girişi/çıkışı, rol ve modül izinleri test edildi.
- [ ] Normal iş emri açma/planlama/atama/kapama test edildi.
- [ ] Planlı bakım ayrı cihaz checklist/seri no ile test edildi.
- [ ] Kiralama çoklu ürün, depo tahsis, sevk, kurulum, toplama test edildi.
- [ ] Eğitim ve saha gözlemi test edildi.
- [ ] Saha zaman sayacı, mola ve kişi-saat raporu test edildi.
- [ ] Excel export tarih seçili/seçili değil testi başarılı.
- [ ] Maliyet ve fiyat alanları yetkisiz hesapta API üzerinden erişilemez.
- [ ] Uygulama servis restart sonrası otomatik açılıyor.
- [ ] Firewall, TLS/HTTPS, log, yedekleme ve geri yükleme tatbikatı tamamlandı.
- [ ] Canlıya alma/onay/geri dönüş sorumluları tanımlandı.

## 16. Dosya ve paket referansları

Geliştirme ve geçişte oluşturulan isimler (isimler dosyanın içeriğini belirtir; **dosyanın bulunması tek başına canlı test kanıtı değildir**):

```text
DengeERP_Pilot_V1_6_PLANNING_CALENDAR_2026-10-13(1).zip
DengeERP_Pilot_V1_7_CIHAZ_BAZLI_BAKIM_YETKI_2026-10-14.zip
DengeERP_Pilot_V1_8_CIHAZ_BAZLI_IS_EMRI_BAKIM_KPI_2026-10-14.zip
DengeERP_Pilot_V1_9_TOPLU_PLANLAMA_ATAMA_2026-10-14.zip
DengeERP_Pilot_V1_11_RAPOR_KOMPAKT_TAKVIM_SAHA_LOKASYON_2026-10-14.zip
DengeERP_Pilot_V1_12_KIRALAMA_ENVANTER_OPERASYON_2026-10-14.zip
DengeERP_Pilot_V1_13_EGITIM_YETKINLIK_SAHA_GELISIM_2026-10-14.zip
DengeERP_Pilot_V1_14_SAHA_ZAMAN_TAKIBI_KPI_2026-10-15.zip
DengeERP_Pilot_V1_20_BIRLESIK_PAKET_2026-10-15.zip
DengeERP_V1_20_1_TARIH_FILTRESI_DUZELTME.zip
DengeERP_LINUX_V1_20_1_10_10_50_16.zip
DengeERP_V1_20_1_LINUX_IT_TAM_TESLIM_10_10_50_16.zip
```

Ayrıca İT teslim ZIP'inin içinde mevcut olanlar:

- `DengeERP.Api/` — programın düzenlenebilir kaynak projesi.
- `KAYNAK_KODLARI_V1_20_1.zip` — ayrıca kaynak arşivi.
- `TUM_KAYNAK_KODLARI_TEK_DOSYA.txt` — okunabilir birleşik kod metni.
- `IT_ICIN_ILK_OKU.md` — şirket İT ekibine kurulum özeti.
- `linux/README_KURULUM_TR.md` — ayrıntılı Ubuntu yönergesi.

---

## Son durumun tek paragrafta özeti

**DengeERP**, Denge Elektronik teknik servis operasyonları için .NET 10 + SQL Server temelli, Windows bilgisayarda `5050` portundan çalışan **V1.20.1 pilot** uygulamasıdır. İş emri, planlama, her cihaz için ayrı bakım, cihaz kütüğü, Haberleşme Atölyesi, kiralama/depo, eğitim, saha zaman takibi, rapor, SLA/operasyon merkezi, stok ve maliyet modülleri aşamalı olarak projeye eklenmiştir. Birçok sürümün Windows derlemesi ve açılışı; KPI, toplu atama ve Excel indirme gibi bazı işlevler ayrıca doğrulanmıştır. **Tüm modüllerin uçtan uca kabul testi ve üretim güvenlik incelemesi tamamlanmış değildir.** Şirket Linux pilotu için **`10.10.50.16/24`** hedefli kaynak+kurulum ZIP'i hazırlanmış, ancak gerçek Ubuntu/SQL testi İT ile yapılmalıdır. Mevcut Windows dosyaları ve SQL yedekleri korunarak ilerlenmelidir.

> **Belgeyi güncelleme kuralı:** Yeni sürüm çıktığında tarih, ZIP adı, değişiklikler, SQL değişiklikleri, hangi testlerin geçtiği, hangi testlerin açık kaldığı ve geri dönüş adımı bu belgeye eklenmelidir.
