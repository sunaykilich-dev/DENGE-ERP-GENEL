# DengeERP V1.20.1 — Ubuntu 24.04 LTS kurulum ve test paketi

**Hedef sunucu IP:** `10.10.50.16/24` (alt ağ `10.10.50.0/24`). Sunucunun bu IP'ye atanmış olması beklenir. **Ağ geçidi / DNS / arayüz adı bilinmiyor:** İT belirler. Bu paket IP'yi otomatik değiştirmez.

**Pilot LAN URL:** `http://10.10.50.16:5050` (yalnızca şirket içi test). HTTPS sertifikası gelince `https://10.10.50.16` veya IT'nin sağladığı DNS adını kullanın. IP ile HTTPS kullanılacaksa sertifikanın SAN alanında IP de bulunmalı.

**Kapsam:** Gerçek V1.20.1 kaynak kodu, rapor tarih filtresi düzeltmesi, Ubuntu derleme/yayınlama betikleri, `systemd`, Nginx, SQL bağlantı şablonu, yedek ve geri dönüş talimatları. Bu dosya içinde Linux üzerinde önceden derlenmiş DLL YOKTUR: kurulum esnasında `.NET 10 SDK` ile `dotnet publish` çalışır.

## Ön koşullar

- Ubuntu Server **24.04 LTS x64**, şirketin iç ağında 10.10.50.16/24 atanmış olmalı.
- Sunucu apt/NuGet depolarına erişebilmeli veya şirket içi paket aynası hazır olmalı.
- Şirket SQL Server'da **DengeERP_TEST** adlı restore edilmiş **test kopyası** mevcut olmalı. MSSQL TCP portu (varsayılan 1433) firewall'dan yalnızca gerekli kaynaklardan erişilebilir olmalı. Named instance varsa IT portu belirlemeli.
- SQL login (SQL Authentication) ve güçlü parola IT tarafından hazırlanmalı; SQL TLS sertifika zinciri doğrulanmalı. **Windows `Trusted_Connection=True` Linux paketi için kullanılmaz.**
- V1.20.1'de kullanıcı ve iş emirleri SQL içinde tutuluyor; Windows'taki `DengeERP` `.bak` dosyası test ortamına geri yüklendiğinde veriler ve parolalar korunur. Dosya yüklemeleri ve entegrasyonlar varsa ayrıca envanter yapılmalı.
- **Bu pilot pakette kurumsal güvenlik denetimi tamamlanmış değildir; kamu internetine açmayın.** HTTP yalnızca geçici iç ağ testidir.

## 1. Paketi Linux'a kopyala ve aç

Windows PC'de ZIP'i sunucuya SCP/SFTP veya IT'nin dosya yöntemiyle kopyalayın. Sunucuda terminal:

```bash
sudo apt-get update && sudo apt-get install -y unzip
mkdir -p ~/dengeerp-setup
unzip -q ~/DengeERP_LINUX_V1_20_1_10_10_50_16.zip -d ~/dengeerp-setup
cd ~/dengeerp-setup
```

> ZIP sunucuda başka klasördeyse dosya yolunu değiştirin.

## 2. Ubuntu ve servis bileşenlerini hazırla

```bash
sudo bash linux/01_sunucuyu_hazirla.sh
```

Bu işlem Ubuntu 24.04 ve IP doğrular; .NET 10 SDK, Nginx kurar; `dengeerp` sistem kullanıcısı, `/etc/dengeerp/dengeerp.env`, `systemd` ve Nginx dosyalarını hazırlar. Servisi **başlatmaz**, mevcut SQL kayıtlarını **değiştirmez**.

## 3. Test SQL bağlantısını ayarla

```bash
sudo nano /etc/dengeerp/dengeerp.env
```

`ConnectionStrings__DengeERP` satırındaki **SQL-SERVER-ADRESI, DengeERP_TEST, SQL kullanıcı ve parola** değerlerini IT doldurmalı. `DengeERP__RunDatabaseSetupOnStartup=false` KALSIN. Dosyada parola olduğu için izinler `root:root` ve `0600` olmalı.

```bash
sudo chown root:root /etc/dengeerp/dengeerp.env
sudo chmod 600 /etc/dengeerp/dengeerp.env
```

> SQL TLS kurulu değilse `TrustServerCertificate=False` ile bağlantı başarısız olur; güvenliği düşürmek yerine IT'den SQL sertifika zincirini düzeltmesini isteyin.

## 4. Uygulamayı derle / servise al

```bash
sudo bash linux/02_yayinla.sh
```

Betiğin adımları: `dotnet publish -c Release`, sürümlü `/opt/dengeerp/releases/...` klasörüne kopyalama, `current` symlink değiştirme, `systemd` başlatma, `nginx -t`, health check. Test DB yoksa `/api/health` başarısız olur ve servis kapatılır / varsa önceki koda döner. Veritabanı otomatik güncellenmez.

## 5. Sağlık testleri

```bash
sudo bash linux/03_dogrula.sh
```

İT / şirket içi tarayıcı: `http://10.10.50.16:5050` ve `http://10.10.50.16:5050/api/health`. API `status` ve `database` yanıtı sağlıklı olmalı. İlk kabul testinde giriş, kiralama, bakım, planlama, eğitim, zaman takibi, rapor Excel aktarımı ve finans yetkilerini doğrulayın. Gerçek veri üzerinde test değişikliği yapmayın.

## 6. Ağ güvenliği

- IP **10.10.50.16/24**, ağ **10.10.50.0/24**. Varsayılan gateway IP'sini bu bilgi tek başına belirlemez.
- Pilot Nginx **10.10.50.16:5050** dinler; sadece `10.10.50.0/24` ve localhost istemcilerini kabul eder. **Kestrel yalnızca 127.0.0.1:5051** dinler.
- UFW merkezi yönlendirilen şirket güvenlik duvarıyla çakışabileceği için betikler UFW kuralı eklemez. İT inbound TCP/5050'yi yalnızca onaylı LAN/VPN erişimine açar. WAN'dan erişime izin verilmemeli.
- SQL Server TCP/1433 veya şirketin gerçek SQL portuna yalnızca Linux uygulama sunucusundan erişim olmalı.
- HTTPS sertifikası hazır olduğunda `linux/nginx/dengeerp-https.conf.example` yapılandırmasını **IT** düzenleyip etkinleştirir, port 443'e geçer ve 5050 erişimini kaldırır. Bir sertifikayı IP'ye bağlarken SAN-IP şarttır; DNS adı varsa kurumsal CA / ACME kullanılabilir.

## 7. Veritabanı ilklendirme ve eski kullanıcılar

Varsayılan durumda **SQL güncellemesi ve seed KAPALIDIR**; test DB bir Windows V1.20.1 yedeğinden geri yüklenmiş olmalıdır. `SQL_HAZIRLIK_YEDEK.sql` Windows SSMS için yedek örneğidir. Yeni ve boş veritabanını kurmak isterseniz İT önce SQL backup almalı ve test ortamında migration sırasını ayrı onaylamalı. Uygulamanın `DengeERP__RunDatabaseSetupOnStartup=true` seçeneği `Database/*.sql` dosyalarını ve demo olmayan admin seed'ini çalıştırır; **yalnızca bir kez, yedekli test DB ve İT gözetiminde** kullanılmalıdır. Varsayılan veriler eklenebilir; betik SQL tarafında her adımı geri alamaz. Bu ayar sonra mutlaka `false` olmalıdır.

**Boş test DB** için yeni admin parolası `DengeERP__InitialAdminPassword` ile en az 14 karakter olmalı. Var olan DengeERP SQL kopyasındaki kullanıcı kayıtları ve parolaları değiştirilmez. Paket eski sabit `Denge2026!` demo hesap oluşturmayı kaldırır.

## 8. Sürüm geri dönüşü

```bash
sudo bash linux/04_geri_don.sh
```

Yalnızca önceki **Linux uygulama dosyalarına** döner. **SQL geri yüklemez.** SQL rollback'i İT, yedekten ve bakımdan sonra ayrı yürütmelidir. İlk Linux sürümü olduğundan henüz önceki Linux sürümü bulunmayabilir; o durumda Windows V1.20.1 pilotu yedeği korunur.

## 9. Önemli sınırlar

- Bu ortamda .NET 10 derlemesi ve gerçek SQL Server erişimi yapılamadı. Ubuntu sunucusunda `dotnet publish` ve uçtan uca test henüz doğrulanmalı.
- Kaynak V1.20.1 güvenlik incelemesi tamamlanmadı: oturumlar bellekte, TLS zorunluluğu ve API yetki testleri geçiş öncesi denetlenmeli. HTTPS tek başına üretim güvenliği sağlamaz.
- E-posta/SMS otomasyonu ve çevrimdışı senkronizasyon başka geliştirmeler gerektirir.
- Sunucuya şirket bilgileri içeren SQL yedeğini ancak şirketin IT ve KVKK prosedürlerine göre aktarın.
