# DengeERP V1.20.1 — İT Teslim ve Kurulum Dosyası

**Hedef:** Ubuntu Server 24.04 LTS (x64), önceden atanmış `10.10.50.16/24` IP'si, şirket içi pilot erişim `http://10.10.50.16:5050`.

## Pakette neler var?

| Dosya / klasör | İçeriği |
|---|---|
| `DengeERP.Api/` | Gerçek ve düzenlenebilir .NET 10 API projesi, HTML/CSS/JavaScript, SQL şema dosyaları, proje ayarları. |
| `KAYNAK_KODLARI_V1_20_1.zip` | **Tek dosyada tam kaynak proje**; bu ZIP'in içinde yine `DengeERP.Api/` vardır. İT kaynakları ayrı arşiv olarak da alabilir. |
| `TUM_KAYNAK_KODLARI_TEK_DOSYA.txt` | İnceleme için kaynak kodlarının tek bir okunabilir metin dosyasında birleştirilmiş hali (her bölümün dosya adı belli). **Derleme için bu TXT kullanılmaz.** |
| `linux/` | Ubuntu hazırlama, .NET publish, systemd, Nginx, kontrol ve geri dönüş betikleri. |
| `linux/README_KURULUM_TR.md` | Adım adım kurulum ve dikkat edilmesi gereken noktalar. |
| `KAYNAK_DOSYA_LISTESI_SHA256.txt` | Her kaynak ve yapılandırma dosyasının SHA-256 özeti. |
| `PAKET_BILGISI.json` | Sürüm ve sunucu bilgileri. |

## Hızlı kurulum sırası

IT öncelikle **yeni test SQL veritabanı** hazırlamalı. Kaynağı doğrudan mevcut canlı veritabanına bağlamayın.

```bash
sudo apt-get update && sudo apt-get install -y unzip
mkdir -p ~/dengeerp-setup
unzip ~/DengeERP_V1_20_1_LINUX_IT_TAM_TESLIM_10_10_50_16.zip -d ~/dengeerp-setup
cd ~/dengeerp-setup
sudo bash linux/01_sunucuyu_hazirla.sh
sudo nano /etc/dengeerp/dengeerp.env
sudo bash linux/02_yayinla.sh
sudo bash linux/03_dogrula.sh
```

`/etc/dengeerp/dengeerp.env` dosyasında örnek SQL adresi, kullanıcı adı ve parola **IT tarafından gerçek TEST SQL bilgileriyle değiştirilmelidir**. Veritabanı şema güncellemeleri varsayılan olarak **kapalıdır**. SQL test kopyası mevcut kurulumun yedeğinden geri yüklenmelidir.

## Bu pakette OLMAYAN, İT tarafından sağlanması gerekenler

1. **SQL Server veritabanının gerçek `.bak` yedeği**, kurtarma/güncelleme ve SQL sunucusu bilgileri. Gerçek şirket veri tabanı kullanıcı verisi bu kod ZIP'ine eklenmedi.
2. Sunucuda Ubuntu işletim sistemi, yönetici yetkisi, şirketin DNS/gateway ve güvenlik duvarı ayarları.
3. SQL Server hesabı/parolası; üretim ortamında güçlü ve en az yetkili hesabın yapılandırılması; SQL TLS sertifika zinciri.
4. İnternet erişimi veya onaylı yerel paket aynası (ilk kurulumda .NET 10 SDK ve NuGet paketlerini indirebilmek için).
5. Şirket içi pilot aşamasından sonra kurumsal **HTTPS sertifikası ve DNS adı**; güvenlik incelemesi ve kullanıcı kabul testi.

## Uyarılar

- **Bu dosya kaynak kodlu kurulum paketidir, Linux'ta önceden derlenmiş çalışır binary değildir.** `02_yayinla.sh` `dotnet publish` ile derleme yapar.
- Uygulamanın `V1.20.1` Windows pilot sürümünden türetildiği kontrol edilmiştir; gerçek Ubuntu/.NET ve SQL entegrasyonu henüz test edilmedi.
- **Güvenlik denetimi tamamlanmadı:** Pilotun internete açılması veya şirket genelinde üretim olarak kullanılması için önce kod/kimlik doğrulama/yetki/HTTPS denetimi gereklidir. Mevcut oturumlar bellekte tutulmaktadır.
- Eski pilot dokümanlarında Windows adresleri görülebilir. Linux için **yalnızca** `linux/README_KURULUM_TR.md` izlenmeli.
- UI üzerindeki sabit demo parola ve yeni kullanıcı formundaki önceden doldurulmuş demo parola bu Linux teslim kopyasından kaldırıldı. **Daha önceki SQL veritabanında bulunan demo kullanıcıların şifreleri bu değişiklikle sıfırlanmaz**; IT bunları değiştirmeli veya devre dışı bırakmalı.
- Eski Windows pilotunu ve SQL yedeğini silmeyin. Kurulum başlangıcında **gerçek canlı DB üzerinde otomatik migration çalıştırılmamalı**.

## İlk kabul testleri

İT `http://127.0.0.1:5051/api/health` (sunucunun kendi içi), `http://10.10.50.16:5050` ve giriş ekranını doğrulasın; ayrıca kiralama, depo, cihaz bakım iş emri, toplu atama, eğitim, saha zamanı, rapor indirme ve yetki testlerini test veritabanında yapsın.
