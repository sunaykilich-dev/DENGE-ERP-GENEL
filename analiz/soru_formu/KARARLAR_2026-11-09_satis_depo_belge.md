# Kararlar 2026-11-09: satış, keşif, depo al-ver, belgeler, menü, Ana Panel

Bu kararlar kullanıcının 2026-11-09 tarihli isteklerine dayanıyor. Kullanıcı "soru sorma" dediği için kararlar gerekçeleriyle buraya yazıldı. Bağlayıcı üst belge `KARARLAR_2026-10-28.md`'dir. Bu belge onun G5.2/G5.5, G7.2/G7.3, G8.1, D2.2 ve D6.7 maddelerini somutlaştırır.

Bugünkü durumu çıkaran inceleme 2026-11-09'da `denge-erp-deneme` üzerinde yapıldı ve kısa özeti şu:
- İskonto onayında tek bir genel eşik var (`iskonto_onay_esigi_yuzde` = %10) ve onay tek adımlı.
- Teklif kaybedildiğinde girilen neden serbest metin; satışçıya özel bir rapor yok.
- Keşif yalnızca bir servis işi türü. Satış ekibi keşif isteyemiyor.
- Satış siparişiyle servis işi arasında bağ yok.
- İrsaliye diye bir belge yok. Logo entegrasyonu da yok, yalnız Excel dışa aktarımı var.
- PDF'ler var ama eksik.
- Ana Panel yalnız teknik servise göre kurulu ve kişiye göre ayarlanamıyor.

## S1. İskonto yetkisi ve onayı
- **S1.1 Rol limiti:** Her satış rolünün bir iskonto üst limiti var: Satış Temsilcisi %10, Satış Destek %5, Satış Müdürü %25. Limitler Ayarlar ekranından değiştirilebilir.
- **S1.2 Kişi limiti:** Kişiye özel limit tanımlanabilir ve tanımlıysa rol limitinin yerine geçer.
- **S1.3 Ölçü:** Limit, teklifteki en yüksek satır iskontosuna ve toplam iskonto oranına birlikte bakar. Hangisi daha yüksekse o esas alınır.
- **S1.4 Limit aşılırsa:** Teklif onaylanamaz ve müşteriye gönderilemez. Onay Satış Müdürü'ne düşer (`teklif.iskonto_onayla`). Müdür kendi limitinin üstünde onay veremez; o durumda onay Genel Müdür'e ya da ADMIN'e gider. Bu, G5.5'teki kademeli onaydır.
- **S1.5 Onaydan sonra fiyat değişirse:** Onaylı teklifte fiyat ya da iskonto değişirse onay düşer ve yeniden onay gerekir. Bu, sürümleme altyapısıyla zaten sağlanıyor.
- **S1.6 Tek adım:** Limitin altındaki teklif hiçbir onaya takılmaz (G1.9).

## S2. Teklif sonuç takibi
- **S2.1 Kaybedilme nedeni:** Neden artık bir listeden seçilir. Liste: Fiyat yüksek, Rakip tercih edildi, Bütçe yok veya ertelendi, Teknik uygunsuzluk, Teslim süresi, Müşteri yanıt vermedi, Diğer. "Diğer" seçilirse açıklama zorunludur. Eski serbest metin kayıtları "Diğer" altında açıklama olarak korunur.
- **S2.2 "Tekliflerim" görünümü:** Satışçı kendi tekliflerini görür: açık, kazanılan, kaybedilen, süresi dolan ve bunların oranları, kaybedilenlerde de nedene göre dağılım. Dönem filtresi var. Satış Müdürü aynı görünümü satışçı kırılımıyla görür.
- **S2.3 Hatırlatma:** Süresi dolmak üzere olan ve yanıt bekleyen teklifler satışçıya hatırlatılır.

## S3. Keşif
- **S3.1 Keşif talebi:** Teklif aşamasında satışçı tekliften "Keşif iste" der. Bu, teklife bağlı bir KESIF servis işi açar.
  - Birim tekliften gelir; teklifte birim yoksa satışçı Haberleşme ya da Güvenlik'i seçer.
  - İş PLANLAMADA durumunda başlar.
- **S3.2 Öncelik:** Önceliği satışçı önerir (Normal veya Yüksek). Keşifler arızanın önüne geçmez: KRITIK seçilemez ve SLA yoktur.
  - Hedef tarih teklifin geçerlilik süresinden türetilir; varsayılan 5 iş günü.
  - Planlamayı birim şefi yapar ve normal planlama ekranında yürür. Ayrı bir keşif ekranı yok.
- **S3.3 Sonuç:** Keşif tamamlanınca teknisyenin raporu ve fotoğrafları teklife bağlanır, satışçıya bildirim gider. Keşif raporu PDF olarak indirilebilir.
- **S3.4 Satışçının işi takibi:** Satışçı keşif işinin aşamasını teklif ekranından görür.

## S4. Satıştan sonra
- **S4.1 Kurulum ve teslimat işi:** Kabul edilen teklif ya da siparişten kurulum veya teslimat işi açılır (D2.2). Bir teklif ya da siparişe birden çok iş bağlanabilir.
- **S4.2 Aşama takibi:** Satışçı teklif ve sipariş ekranında bağlı tüm işleri ve aşamalarını görür. Aşamalar: Planlandı, Yolda, Sahada, Tamamlandı, Askıda (neden ile).
  - Ayrıca "Satışlarımın durumu" listesi var.
  - Bakım ve onarım işleri de müşteri kartı üzerinden aynı şekilde izlenir.
  - Maliyet bilgisi gizli kalır (`maliyet.gor`).
- **S4.3 İrsaliye:** Depodan sevk sırasında sistem numaralı bir irsaliye üretir ve PDF'i alınabilir. Bu e-İrsaliye değildir; e-İrsaliye Faz D'de, GİB entegrasyonuyla gelecek.
  - Seri numarası olmayan sipariş satırları da stoktan düşülür.
- **S4.4 Muhasebe:** Logo'nun muhasebe ürünü ve sürümü hâlâ bilinmiyor (bkz. 10-28 §6/6). Bu yüzden doğrudan Logo entegrasyonu yapılmıyor.
  - Bunun yerine irsaliye, sipariş ve fatura devri için Logo'ya aktarılabilir Excel/CSV şablonu ve "muhasebeye devredildi" durumu var. Fatura devrindeki bugünkü kalıp genişletilir.
  - Logo API'si Faz D'de, ürün öğrenilince eklenecek.

## S5. Sahada onarım ile depo arasındaki parça alışverişi
- **S5.1 Parça çıkışı:** Teknisyen sahada parçayı kendi araç deposundan kullanır. Çıkış iş emrine bağlı olarak anında yapılır, iş beklemez. Şef bu kullanımı sonradan onaylar (D6.7). Şef reddederse fark kaydı açılır ve zimmet sorusu oluşur.
- **S5.2 Sökülen parça:** Arızalı ya da sökülen parça iş emrine "sökülen parça" olarak yazılır. Parça depoya iade edilir (tamir edilebilir veya hurda) ya da müşteride bırakılır. Seçim zorunludur; boş geçilemez.
- **S5.3 Araç deposu ikmali:** Araç deposunda azalan parça için ikmal talebi otomatik olarak önerilir. Bu talep, amir onaylı parça talebi akışıyla birim deposundan karşılanır.
- **S5.4 Fiş:** Her çıkış ve iade için parça fişi PDF olarak indirilebilir.

## S6. Belgeler ve PDF
Sistemde oluşturulan her müşteri belgesi ve iç fiş PDF olarak indirilebilir:
- teklif
- sipariş onayı
- irsaliye
- servis formu
- bakım fişi ve onarım fişi (ayrı şablon)
- keşif raporu
- parça çıkış/iade fişi
- atölye kabul ve teslim belgeleri
- kiralama tutanağı
- hak ediş

Fiyat ve maliyet içeren belgeler yalnız yetkisi olana fiyatlı basılır.

## S7. Sol menü
- **S7.1 Gruplama:** Menü göreve göre gruplanır, kişi yalnız işine yarayan kısmı görür. Önerilen üst gruplar:
  1. Ana Panel
  2. Benim İşlerim
  3. Servis İşleri (birim ve tür alt filtreleriyle)
  4. Planlama
  5. Satış
  6. Depo
  7. Kiralama
  8. Raporlar
  9. İnsan Kaynakları
  10. Yönetim
- **S7.2 Birim ayrımı:** Birim (Haberleşme, Güvenlik, POC, Set Bariyer) bir menü kökü değildir; ekranın içinde süzgeç olarak seçilir. Tek birimli kullanıcıda bu süzgeç otomatik gelir.
- **S7.3 Satış altındaki iş listesi:** Satış altındaki "Sonuçlanan Arıza İşleri" kaldırılır. Yerine "Teklif Hazırlanacak İşler" gelir; bu liste yalnız `sonuc=TEKLIF_SUNULACAK` olan işleri gösterir.
  - Bugünkü liste çözülmüş bütün arıza işlerini gösteriyordu, bu yüzden amacından geniş ve kafa karıştırıcıydı.
- **S7.4 Boş grup:** Alt öğesi olmayan grup gizlenir. Menüde en fazla iki seviye olur.

## S8. Ana Panel
- **S8.1 Kişisel düzen:** Her kullanıcı kendi panelini düzenler:
  - bileşen ekler veya çıkarır, sırasını değiştirir, boyutunu (dar veya geniş) seçer;
  - "varsayılana dön" ile başlangıç düzenine döner.
  - Düzen sunucuda saklanır, böylece kullanıcı her cihazda aynı paneli görür.
- **S8.2 Bileşen yetkisi:** Bileşen kataloğu izinle süzülür; kişi göremeyeceği veriyi panele ekleyemez. Satış rolleri için Tekliflerim, Kazanma oranı ve Satışlarımın durumu bileşenleri eklenir.
- **S8.3 Rol varsayılanı:** Yönetici her rol için bir varsayılan düzen belirleyebilir (G7.3). Kullanıcının kendi düzeni bunun üstüne yazılır.

## İş dağılımı
- **Depo oturumu** ("Depoları birime göre ayır"): S5 ve S7. Menü ve izin işi zaten bu oturumda olduğundan çakışma olmasın diye aynı oturuma verildi.
- **Satış oturumu:** S1, S2, S3, S4.1 ve S4.2, ayrıca teklif ve keşif PDF'leri.
- **Belge ve sevk oturumu:** S4.3, S4.4 ve S6'nın kalan PDF'leri. Parça fişi depo oturumunda yapılır.
- **Ana Panel oturumu:** S8.
