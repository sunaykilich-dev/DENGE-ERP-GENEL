# İK "Bordro ve Belgeler": Kolaysoft ve benzerleri araştırması (2026-11-06)

Kullanıcı isteği: personele bordro ve imzalanacak form/talimat/taahhütname gönderilsin, personel onaylasın ya da itiraz etsin, İK takip etsin, "Kolaysoft'taki gibi" olsun. Örnek olarak portal.kolaysoft.com.tr gösterildi.

## 1. Kolaysoft'un ürünü: KolayPeyk (PEYK)

Kolaysoft'un bordro ve belge dağıtım ürününün adı "e-Bordro" değil **KolayPeyk (PEYK)**. Kolaysoft'un kendi sayfaları otomatik çekimde boş döndü. Aşağıdaki bilgiler bayi sayfası ve basın haberlerinden geliyor; çoğu tanıtım metni.

| Konu | Bulgu | Kaynak |
|---|---|---|
| Kayıt ve giriş | İK çalışanı portala kaydeder. Çalışana SMS ile şifre oluşturma bağlantısı gider. Kullanıcı adı TCKN; hesap SMS koduyla aktifleşir. | https://www.adenyum.com/urun/62/425/kolay-peyk-nasil-calisir |
| Çalışan ekranı | Gönderilmiş ama onaylanmamış bordro ve formlar **"Onay bekleyenler"** sekmesinde listelenir. Onay iki yolla verilir: "Onayla" düğmesi ya da (firma izin verdiyse) cevap yazıp "Cevapla". | aynı kaynak |
| Mobil | "Peyk" uygulaması var (com.kolaysoft.peyk): bordro görme/indirme, talep formu. | https://play.google.com/store/apps/details?id=com.kolaysoft.peyk |
| Belge türleri | Bordro dışında izin bildirimi, KVKK ve İSG belgeleri; ek modüllerde izin/avans talebi, savunma isteme, ihtar. | https://www.milliyet.com.tr/ekonomi/yerli-yazilimla-bordrolar-cepte-6199530 ; https://turkhabergazetesi.com/haber/kolaysoft-peyk-ile-calisan-deneyimini-dijitallestiriyor-58714 |
| Bildirim | Her gönderimde SMS ve e-posta. | turkhabergazetesi (yukarıda) |
| İmza | "TÜBİTAK zaman damgası uyumlu"; tebligatlar e-imza ve zaman damgasıyla, KEP entegrasyonu var. Çalışanın nitelikli e-imzayla imzaladığı **doğrulanamadı**; çalışan onayı portaldaki düğmeyle. | adenyum ve turkhabergazetesi |
| Takip | İşlemler kaydedilir, yanıtlar anlık izlenir, form yanıtları Excel'e aktarılır. Ekranın ayrıntısı doğrulanamadı. | https://www.yenicagri.com/peykin-tarihcesi-nedir-kolaypeyk-nedir |

Doğrulanamayanlar: İK'nın bordroyu nasıl yüklediği (toplu PDF/zip, TCKN eşleştirme), ayrı itiraz akışı, "görüldü"/"süresi geçti" durumları, otomatik hatırlatma.

## 2. Benzer ürünlerden desenler

- Ayrı onay imzası ve itiraz imzası, ayarlanabilir itiraz süresi, tek kullanımlık bağlantı: https://www.e-inovasyon.com/ik-bordro-karsilastirma.html
- "KEP ile tebliğ edildi", "okundu ama onaylanmadı", "onaylandı/reddedildi" durumları: https://www.datamarket.com.tr/bordro-imzalamanin-sessiz-kahramani-tubitak-zaman-damgasi/
- Mikro: bordro KEP adresine toplu gider, personel onay bağlantısıyla onaylar (arama özetinden).
- Sektörde yaygın model: kimlik SMS OTP ile doğrulanır, onay kaydının özeti zaman damgasıyla mühürlenir (RFC 3161).

## 3. Yasal dayanak

- **4857 sayılı İş Kanunu md. 37:** işveren ödeme sırasında işçiye imzalı ya da işyerinin özel işaretini taşıyan ücret hesap pusulası vermek zorunda. Çalışma Genel Müdürlüğü'nün 13.11.2017 görüşüne göre KEP'le elektronik gönderim bu yükümlülüğü karşılıyor (ikincil kaynak): https://kplegal.com.tr/ucret-bordrolarinin-calisanlara-kep-adresi-uzerinden-gonderilmesi-ve-bu-sekilde-gonderilen-ucret-bordrolarinin-kesin-delil-niteligi/
- **5070 sayılı Elektronik İmza Kanunu md. 5:** yalnız güvenli (nitelikli) e-imza elle atılan imzayla aynı sonucu doğurur. **HMK 205/2:** güvenli e-imzalı belge senet hükmünde. Parola/OTP onayı "basit elektronik delil", takdiri delildir.
- **Yargıtay:** ihtirazi kayıtsız imzalı bordro kesin delildir (9. HD E.2022/5402); ihtirazi kayıt varsa fazla çalışma her delille ispatlanır (9. HD E.2021/7105); imzasız bordroda banka ödemesi mahsup edilir (22. HD E.2017/23154). Bazı istinaf kararları KEP'le gönderilip çalışanca imzalanmayan bordroyu "imzasız" saydı (ikincil kaynak).
- **Hukukçu önerisi:** çalışandan önceden "elektronik gönderilen bordroya belirli sürede itiraz etmezsem kabul etmiş sayılırım" taahhüdü alınması (yerleşik içtihat değil).
- **6698 KVKK:** bordro özel nitelikli veri değil ama kişisel ve gizli veridir; yalnız ilgili kişi ve yetkili İK görmeli, erişim izlenmeli.

## 4. Denge ERP için çıkarım (uygulanan tasarım, ayrıntı KARARLAR §11)

1. Durum dizisi: **Gönderildi → Görüldü → Onaylandı / İtiraz edildi**. Süre aşımı ayrı durum değil, takip ekranında "gecikmiş" işareti.
2. Personel ayrı portala değil, **kendi ERP hesabına** girer (Personel = kullanıcı kuralı). "Belgelerim" ekranı mobilde de çalışır.
3. Onay: tek ekranda "Okudum, onaylıyorum" + **parola tekrarı** (SMS sağlayıcısı Faz D'de; SMS OTP gelince eklenebilir). İtiraz gerekçesi zorunlu.
4. Her onay/itirazda belgenin SHA-256 özeti, zaman, IP ve tarayıcı bilgisi değişmez kayıt olarak tutulur; özet zinciri sonradan değişikliği belli eder.
5. Nitelikli e-imza ve KEP bu sürümde yok: hukuki etkisi "basit elektronik delil". İlk gönderimde imzalatılacak **e-belge kabul taahhütnamesi** şablonu önerilir.
6. Bildirim: ERP içi + e-posta (varsa); hatırlatma elle, İK'nın tek düğmesiyle.
