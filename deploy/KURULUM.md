# Denge Mobilite ERP — Sunucu Kurulumu

**Kurulumun tamamını `kur.sh` yapar.** Elle komut dizisi izlemeniz gerekmiyor;
betik kodu yerleştirir, sırları üretir, veritabanını kurar, dökümü yükler,
uygulamayı başlatır ve sonucu doğrular. Yarıda kalırsa **aynı komutla kaldığı
yerden sürer**; var olan `.env`'in üzerine yazmaz, veri varsa dökümü yüklemez.

Hedef: Ubuntu 22.04/24.04 LTS, 4 çekirdek / 8 GB RAM / 100 GB disk. Tek
sunucu. Ekip 6–15 kişi, ~20.000 cihaz. Bu ölçekte ayrı veritabanı sunucusu,
kuyruk altyapısı ya da yük dengeleyici gerekmez.

Toplam süre: yaklaşık 25 dakika (DNS yayılması hariç).

## Kurulumun haritası

| # | Adım | Elle mi | Sonunda ne doğrularsınız |
|---|---|---|---|
| 1 | Sunucuyu hazırla | elle | `docker --version` sürüm yazıyor |
| 2 | Paketi sunucuya koy | elle | `kur.sh` ve üç arşiv aynı klasörde |
| 3 | **`./kur.sh`** | **betik** | `KURULUM BAŞARILI` + yedi sayı birebir |
| 4 | Geliştirme kimliklerini temizle | elle | yönetici parolası elinizde |
| 5 | Alan adı ve HTTPS | elle | `/api/health` → `{"status":"ok","env":"prod"}` |
| 6 | İlk giriş | elle | MFA kuruldu, Parametreler girildi |
| 7 | Otomatik başlatma + fail2ban | elle | sunucu yeniden başladı, yığın kalktı |
| 8 | Yedekleme | elle | yedek dosyaları oluştu |

Adım 3 eskiden beş ayrı elle adımdı (kod, `.env`, veritabanı, uygulama,
belgeler). Üç ayrı arıza o adımlarda çıktığı için hepsi betiğe alındı ve
betik her birini kendi doğruluyor.

**Tek kural:** bir adım hata verirse durun, sonrakine geçmeyin. Hatanın
metnini EK A'da arayın.

---

## Başlamadan önce

**Gerekenler:**

- Sunucuya `sudo` yetkili SSH erişimi
- Bir alan adı (`erp.dengemobil.com.tr`) ve sunucunun IP'sine bakan **A kaydı**
- 80 ve 443 portları dışarı açık (80, Let's Encrypt doğrulaması için şart)
- Doğrulama uygulaması olan bir telefon (Google Authenticator, 1Password, Authy…)

**Elinizdeki paket** — `denge-canli` klasörü:

| Dosya | Ne işe yarar |
|---|---|
| `kur.sh` | **Kurulumu yapan betik.** Adım 3'te bunu çalıştırırsınız |
| `on-kontrol.sh` | Kaynak ağacını ve `.env`'i mekanik denetler; `kur.sh` içinden de koşar |
| `dogrula.sh` | Kurulumdan sonra her an durum raporu verir |
| `denge-erp-kaynak.tar.gz` | Uygulamanın kendisi (arayüz derlenmiş halde içinde) |
| `denge-veritabani.sql.gz` | Veritabanı dökümü — 480 hesap, 17.350 cihaz, 12.553 hat, **552.825,00 ₺ hak ediş** |
| `denge-dosyalar.tar.gz` | Yüklenen belgeler (21 dosya: vergi levhaları vb.) |
| `SURUM.txt` | Paketin tarihi, commit'i ve göç sürümü — sunucuda hangi sürüm kurulu, buradan okunur |
| `Caddyfile`, `denge-erp.service`, `fail2ban/`, `db-least-privilege.sql` | Adım 5, 7 ve EK E'de kullanılır |
| `KURULUM.md` | Bu belge |

**Kaynak arşivinde `.env` YOKTUR** — sırlar sunucuda, `kur.sh` tarafından
üretilir ve `/opt/denge-erp/.env` dosyasında `-rw-------` izniyle durur.

DNS'i şimdi doğrulayın; sertifika adımına kadar yayılmış olsun:

```bash
dig +short erp.dengemobil.com.tr
```

(`dig` yoksa: `sudo apt install -y dnsutils`.) Sunucunuzun IP'sini vermeli.
Vermiyorsa A kaydını düzeltip devam edin — Adım 5'e kadar sorun çıkarmaz.

---
## Adım 1 — Sunucuyu hazırla

**Sunucuda:**

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg ufw fail2ban rsync
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

**Şimdi SSH oturumunu kapatıp yeniden bağlanın** — `docker` komutunu `sudo`
olmadan kullanabilmek için grup üyeliğinin geçerli olması gerekiyor.

Yeniden bağlandıktan sonra güvenlik duvarı:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw --force enable
```

Doğrulama — ikisi de sürüm yazmalı:

```bash
docker --version && docker compose version
```

> Veritabanı portu dışarı **açılmaz**. Compose eşlemesi `127.0.0.1`
> üzerindedir; veritabanına yalnız sunucunun içinden erişilir.

---


## Adım 2 — Paketi sunucuya koy

`denge-canli` klasörünün **tamamını** sunucuya yükleyin — betikler ve arşivler
aynı klasörde olmalı. Yöntem serbest: SFTP istemcisi (FileZilla, Cyberduck),
hosting panelinin dosya yöneticisi ya da `scp`.

Diyelim `/home/erpadmin/denge-canli` altına koydunuz:

```bash
cd ~/denge-canli && chmod +x kur.sh on-kontrol.sh dogrula.sh && ls -lh
```

Doğrulama — bu dört dosya görünmeli:

```bash
ls kur.sh denge-erp-kaynak.tar.gz denge-veritabani.sql.gz denge-dosyalar.tar.gz
```

Arşivlerin aktarımda bozulmadığını teyit edin — **hiç çıktı vermemeli**:

```bash
gzip -t denge-erp-kaynak.tar.gz denge-veritabani.sql.gz denge-dosyalar.tar.gz && echo "arsivler saglam"
```

> Çıktı veriyorsa dosya aktarımda bozulmuştur; yeniden yükleyin. `kur.sh` bu
> kontrolü kendi de yapar ve bozuk arşivle başlamaz.

---

## Adım 3 — `./kur.sh`

Tek komut. Kurulumun tamamı budur.

```bash
cd ~/denge-canli && ./kur.sh --alan erp.dengemobil.com.tr
```

Alan adınız farklıysa `--alan` değerini değiştirin. Varsayılan hedef dizin
`/opt/denge-erp`; başka yere kurmak isterseniz `--hedef /srv/erp` ekleyin.
Veriyi yüklemeden boş bir sistem kurmak isterseniz `--veri yok` ekleyin.

Betik dokuz aşamayı sırayla koşar ve her birini doğrular:

| Aşama | Ne yapar |
|---|---|
| 1 | docker, docker compose, rsync, python3 var mı; arşivler sağlam mı (`gzip -t`) |
| 2 | Kodu `rsync --delete` ile yerleştirir, macOS yan dosyalarını (`._*`) siler |
| 3 | `.env` yoksa üretir (`openssl`), **varsa dokunmaz** |
| 4 | `on-kontrol.sh` — AppleDouble / NUL / sözdizimi / `.env` tutarlılığı |
| 5 | PostgreSQL'i kaldırır, `pg_isready` ile bekler |
| 6 | **Rol parolasını `.env` ile eşitler** ve TCP+scram ile doğrular |
| 7 | Veritabanı boşsa dökümü ve belgeleri yükler; **veri varsa dokunmaz** |
| 8 | `api` + `worker`'ı yeniden oluşturur, `/api/health` yanıt verene kadar bekler |
| 9 | Sayıları, hak ediş toplamını ve arayüzü (`200`) doğrular |

Sonunda yeşil **`KURULUM BAŞARILI`** ve şu tablo görünmeli:

```
 hesap              | 480
 cihaz              | 17350
 arac               | 7366
 hat                | 12553
 is_emri            | 1226
 hakedis_dokumu     | 83
 hakedis_toplam     | 552,825.00
 cakisan_acik_donem | 0
```

**Bu yedi sayı ve `cakisan_acik_donem = 0` tutmalı.** `hakedis_toplam`
canlı hak ediş uygulamasının rakamıyla kuruşu kuruşuna aynıdır; tutmuyorsa
döküm eksik yüklenmiştir — EK A'ya bakın, devam etmeyin.

Hata alırsanız betik **durur** ve sebebi yazar; `api` ayağa kalkmazsa son 40
satır log'u da basar. Düzeltip **aynı komutu tekrar çalıştırın** — betik
tekrar çalıştırılabilir, yaptığı işi iki kez yapmaz.

Kurulumdan sonra durumu her an görebilirsiniz:

```bash
/opt/denge-erp/deploy/dogrula.sh
```

---

## Adım 4 — Geliştirme kimliklerini temizle

**Bu adım atlanamaz.** Geliştirme veritabanı her rolden bir kullanıcıyı
**sabit `deneme1234` parolasıyla** açmıştı. Canlıya giderse parolası herkesçe
bilinen sekiz hesap doğar.

Önce ne olacağını görün:

```bash
cd /opt/denge-erp
docker compose exec -T api python -m app.yonetim canliya-hazirla
```

Uygulayın:

```bash
docker compose exec -T api python -m app.yonetim canliya-hazirla --uygula
```

**Ekrana basılan yönetici parolasını şimdi kaydedin — bir kez görünür.**

Komut demo kullanıcılarını kapatır (silmez; denetim izi onlara işaret
ediyor), açık oturumları düşürür, yönetici parolasını yeniler ve MFA'sını
sıfırlar.

Test kaydı kalmadığını doğrulayın — "silinecek" satırlarının hepsi **0**
olmalı. Komut gerçek ticari kayda (teklif, sipariş, abonelik, RMA, tahsilat)
**dokunmaz**; varsa "DOKUNULMAYACAK gerçek kayıt" satırında sayar:

```bash
docker compose exec -T api python -m app.yonetim test-verisi-temizle
```

Hat durumlarını da doğrulayın — cihazda takılı bir hat "STOKTA" görünmemeli
(görünürse "kaç boş hattımız var" raporu o kadar şişer):

```bash
docker compose exec -T api python -m app.yonetim hat-durumu-duzelt
```

---

## Adım 5 — Alan adı ve HTTPS

> **Bu adım bitmeden giriş yapmayı denemeyin.** Üretimde oturum çerezi
> `Secure` işaretlidir; tarayıcı onu yalnız HTTPS üzerinden saklar.
> `http://<sunucu-ip>` ile denerseniz giriş 200 döner ama **oturum açılmaz**,
> sonraki her istek 401 verir ve ekran sessizce giriş sayfasına döner.
> "Kullanıcılar göçte mi kayboldu?" paniğinin en sık sebebi budur.

Caddy Ubuntu'nun kendi depolarında **yoktur**; önce resmî deposu eklenir:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
sudo apt update
sudo apt install -y caddy
```

Sonra yapılandırmayı yerleştirin:

```bash
sudo cp /opt/denge-erp/deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/SUNUCU_ALAN_ADI/erp.dengemobil.com.tr/' /etc/caddy/Caddyfile
sudo mkdir -p /var/log/caddy && sudo chown -R caddy:caddy /var/log/caddy && sudo chmod 755 /var/log/caddy
sudo systemctl restart caddy && sudo systemctl enable caddy
```

### Gelen bağlantı yoksa: Cloudflare DNS doğrulaması (önerilen)

Let's Encrypt'in iki doğrulama yolu vardır. Öntanımlı olan **HTTP-01**, port
80'e dışarıdan ulaşılmasını ister. **DNS-01** ise hiç gelen bağlantı istemez:
Caddy, Cloudflare'de geçici bir TXT kaydı açar, Let's Encrypt onu okur ve
sertifikayı verir. Sunucunun internete **çıkabilmesi** yeterlidir.

Bu yol, sunucu iç ağdayken ya da güvenlik duvarı yönlendirmesi beklenirken
doğru seçimdir — ve aldığınız sertifika **gerçek, uyarısız** bir
sertifikadır. Yönlendirme sonradan açılırsa hiçbir şey değişmez.

**1) Cloudflare'de API jetonu üretin.** dash.cloudflare.com → sağ üst profil →
*API Tokens* → *Create Token* → *Edit zone DNS* şablonu. *Zone Resources*
kısmında **yalnız `dengemobil.com.tr`** seçin. Jeton bir kez görünür.

> Jetonu kimseyle paylaşmayın, bu belgeye ya da bir sohbete yapıştırmayın.
> Doğrudan sunucuya yazın. Yetkisi yalnız DNS kaydı düzenlemekle sınırlıdır.

**2) Caddy'ye Cloudflare eklentisini ekleyin.** Apt'tan gelen Caddy'de bu
modül yoktur; `add-package` ikiliyi modüllü sürümle değiştirir:

```bash
sudo caddy add-package github.com/caddy-dns/cloudflare
sudo systemctl restart caddy
caddy list-modules | grep dns.providers.cloudflare
```

Son komut `dns.providers.cloudflare` yazmalı. `add-package` yoksa (Caddy 2.7
öncesi) <https://caddyserver.com/download> adresinden `caddy-dns/cloudflare`
modülünü seçip ikiliyi indirin ve `/usr/bin/caddy` ile değiştirin.

**3) Jetonu sunucuya koyun** — dosya yalnız Caddy tarafından okunabilir:

```bash
sudo install -o caddy -g caddy -m 600 /dev/null /etc/caddy/cloudflare.env
sudo nano /etc/caddy/cloudflare.env
```

Tek satır yazın (jetonu kendi jetonunuzla değiştirin, tırnak koymayın):

```
CLOUDFLARE_API_TOKEN=buraya_jetonunuz
```

Caddy'nin bu dosyayı okuması için servise tanıtın:

```bash
sudo systemctl edit caddy
```

Açılan düzenleyiciye şunu ekleyip kaydedin:

```
[Service]
EnvironmentFile=/etc/caddy/cloudflare.env
```

**4) Caddyfile'a DNS doğrulamasını yazın** — alan adı satırının altına:

```bash
sudo sed -i '/^erp\.dengemobil\.com\.tr {/a\\ttls {\n\t\tdns cloudflare {env.CLOUDFLARE_API_TOKEN}\n\t}' /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl daemon-reload && sudo systemctl restart caddy
```

`validate` "Valid configuration" demeli. Sertifika bir dakika içinde gelir:

```bash
sudo journalctl -u caddy -n 30 --no-pager | grep -i "certificate obtained\|error"
```

**5) İç kullanıcılar sunucuya nasıl ulaşacak.** Alan adı halka açık DNS'te
dış IP'ye bakar; ofisteki bilgisayarlar güvenlik duvarı hairpin yapmıyorsa
oraya ulaşamaz. İki yol var:

- **Kalıcı:** şirket iç DNS sunucusunda `erp.dengemobil.com.tr` için
  sunucunun iç IP'sini (`10.10.200.3`) gösteren bir kayıt açın. İsim her iki
  tarafta aynı kalır, sertifika da o isme çıktığı için uyarı olmaz.
- **Geçici (birkaç bilgisayar için):** `hosts` dosyasına satır ekleyin —
  Windows'ta `C:\Windows\System32\drivers\etc\hosts`, macOS/Linux'ta
  `/etc/hosts`:

  ```
  10.10.200.3  erp.dengemobil.com.tr
  ```

Sonra tarayıcıda `https://erp.dengemobil.com.tr` açılır, kilit simgesi gelir
ve giriş çalışır.

### Sunucu iç ağdaysa (10.x, 192.168.x, 172.16-31.x)

Let's Encrypt sertifikayı **port 80'den doğrular**: alan adı internetten bu
sunucuya ulaşabilmelidir. Sunucu iç ağdaysa önce güvenlik duvarında
yönlendirme açılır:

```
erp.dengemobil.com.tr -> <dis IP> :80  ve :443  ->  <sunucunun ic IP'si> :80 ve :443
```

Yönlendirmenin gerçekten çalıştığını **dışarıdan** teyit edin (ofis ağından
değil — telefonunuzun mobil verisi ya da dış bir sunucudan):

```bash
curl -sS -m 10 -o /dev/null -w '%{http_code}\n' http://erp.dengemobil.com.tr/
```

Bir kod dönüyorsa (404 bile olsa) yol açıktır; `000` ya da bağlantı hatası
dönüyorsa yönlendirme yoktur ve Caddy sertifika alamaz.

**Yönlendirme henüz açılamıyorsa** geçici olarak Caddy'nin kendi sertifikası
kullanılabilir — `/etc/caddy/Caddyfile` içinde alan adı satırının hemen
altına `tls internal` ekleyin:

```bash
sudo sed -i '/^erp\.dengemobil\.com\.tr {/a\\ttls internal' /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Bu sertifikayı **yalnız kök sertifikası kurulu bilgisayarlar** tanır; geri
kalanı tarayıcı uyarısı görür. Kök sertifikayı dağıtmak için:

```bash
sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
```

Çıktıyı `denge-root.crt` olarak kaydedip bilgisayarlara "Güvenilen Kök
Sertifika Yetkilileri" deposuna kurun (GPO ile de dağıtılabilir).

**İnternete açık kullanım için bu yol uygun değildir** — dışarıdan gelen
hiç kimse kökü tanımaz. Yönlendirme açılır açılmaz `tls internal` satırını
silip Caddy'yi yeniden başlatın, gerçek sertifika kendiliğinden gelir.

### İnternete açılıyorsa — atlanamaz sertleştirme

ERP dışarıdan erişilebilir olacaksa şu üçü **isteğe bağlı değildir**:

- **Adım 7'deki fail2ban** kurulmalı (`denge-erp-login` jail'i). Dışarı açık
  bir giriş ekranı saatler içinde otomatik deneme trafiği görür.
- **MFA zorunlu** kalmalı (`.env` içinde `MFA_ZORUNLU=true` — öntanımlı böyle).
- **`/api/docs` kapalı** olmalı (üretimde kapalı; kontrol listesinde teyit var).

Ayrıca DNS'iniz Cloudflare'de olduğu için, alan adını Cloudflare üzerinden
**proxy'li** (turuncu bulut) yayınlamak sunucunun gerçek IP'sini gizler ve
önüne bir katman daha koyar. Bunu yaparsanız Caddy'nin sertifika doğrulaması
için Cloudflare'de SSL modunun **Full (strict)** olması gerekir.

Sertifika birkaç saniyede gelir. Doğrulama — `{"status":"ok","env":"prod"}`:

```bash
curl -s https://erp.dengemobil.com.tr/api/health
```

---

## Adım 6 — İlk giriş

Tarayıcıdan `https://erp.dengemobil.com.tr` açın.

1. Kullanıcı adı `admin`, parola: **Adım 4'te ekrana basılan parola**
2. **QR kodu çıkar** — doğrulama uygulamanıza okutun
3. Uygulamadaki 6 haneli kodu girin

MFA zorunludur: parola doğru olsa da kurulum bitmeden hiçbir ekran açılmaz.
Her kullanıcı ilk girişinde bu adımdan geçer.

Girdikten sonra **Parametreler** ekranından girilecekler:

- KDV, stopaj, damga vergisi oranları
- Şirket künyesi (unvan, VKN, vergi dairesi, MERSİS, KEP)
- SMTP bilgileri (teklif ve hak ediş e-postaları için)

Ekibin hesaplarını **Kullanıcılar** ekranından açın; her biri ilk girişinde
kendi MFA'sını kuracak.

---

## Adım 7 — Otomatik başlatma ve fail2ban

Sunucu yeniden başladığında yığın kendiliğinden kalksın:

```bash
sudo cp /opt/denge-erp/deploy/denge-erp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now denge-erp
```

fail2ban:

```bash
sudo cp /opt/denge-erp/deploy/fail2ban/jail.local         /etc/fail2ban/jail.local
sudo cp /opt/denge-erp/deploy/fail2ban/filter.conf        /etc/fail2ban/filter.d/denge-erp.conf
sudo cp /opt/denge-erp/deploy/fail2ban/filter-teklif.conf /etc/fail2ban/filter.d/denge-erp-teklif.conf
```

**`jail.local` içindeki `ignoreip` satırına ofis çıkış IP'nizi ekleyin** —
yoksa kendinizi yasaklayabilirsiniz. Sonra:

```bash
sudo nano /etc/fail2ban/jail.local      # ignoreip satırı
sudo systemctl restart fail2ban
sudo fail2ban-client status denge-erp-login
```

Sunucuyu yeniden başlatıp doğrulayın — test edilmemiş bir otomatik başlatma
yokmuş gibidir:

```bash
sudo reboot
# ~1 dakika sonra, kendi makinenizden:
curl -s https://erp.dengemobil.com.tr/api/health
```

---

## Adım 8 — Yedekleme

Yedek parolası:

```bash
openssl rand -hex 32 | sudo tee /root/.denge_erp_yedek_parolasi >/dev/null
sudo chmod 600 /root/.denge_erp_yedek_parolasi
```

> Bu parolayı **sunucunun dışında** da saklayın. Kaybolursa yedekler açılamaz.

**Önce ilk yedeği UZAK HEDEF OLMADAN alın** — yedeğin kendisinin çalıştığını
görmek, uzak kopyayı ayarlamaktan önce gelir:

```bash
sudo /opt/denge-erp/deploy/yedekle.sh
ls -lh /var/backups/denge-erp/
```

İki dosya oluşmalı (`dengeerp-*.sql.gz.gpg` ve `dosyalar-*.tar.gz.gpg`) ve
komut "UYARI: UZAK_HEDEF tanimli degil" yazmalı — bu beklenen.

**Sonra uzak hedefi bağlayın.** `UZAK_HEDEF` mutlaka **başka bir makine ya da
disk** olmalı: ERP ile yedeğin aynı diskte durması yedek sayılmaz. Hedef
dizin VAR OLMALI, yoksa `rsync` hata verir:

```bash
# Örnek: ağ diski /mnt/yedek'e bağlıysa
ls -ld /mnt/yedek
sudo UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh
```

Uzak hedefiniz SSH üzerinden bir sunucuysa `UZAK_HEDEF` yerine
`kullanici@sunucu:/yedek/denge` yazabilirsiniz (anahtarla parolasız giriş
kurulu olmalı).

Günlük yedek (saat 03:00) — kendi `UZAK_HEDEF` değerinizle:

```bash
sudo crontab -e
# Şu satırı ekleyin:
# 0 3 * * * UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh >> /var/log/denge-yedek.log 2>&1
```

**Ayda bir geri yükleme provası** (canlıya dokunmaz, geçici veritabanına yükler):

```bash
sudo /opt/denge-erp/deploy/geri-yukle.sh /var/backups/denge-erp/dengeerp-<tarih>.sql.gz.gpg
```

Çıktıdaki hak ediş genel toplamı canlıyla aynı olmalı; `cakisan_acik_donem = 0`
ve `exclude_kisiti = 7` de görünmeli — tarihli kısıtlar geri yüklemede
düşerse veri modeli sessizce bozulurdu.

---

## Kurulum sonrası kontrol listesi

İşaretlenmeyen madde "sonra bakarız" değil, **bitmemiş kurulum** demektir.

İlk dört maddeyi tek komut kontrol eder:

```bash
/opt/denge-erp/deploy/dogrula.sh
```

`SISTEM SAGLIKLI` yazarsa ilk dördü işaretleyebilirsiniz; `SORUN VAR` yazarsa
`✗` satırlarını EK A'da arayın.

- [ ] `dogrula.sh` → **`SISTEM SAGLIKLI`** (servisler, `/api/health`, TCP
      bağlantısı, sayılar, hak ediş toplamı, çakışan dönem, son yedek)
- [ ] `https://erp.dengemobil.com.tr` açılıyor, kilit simgesi var
- [ ] `docker compose logs worker` dört görevin bittiğini yazıyor
- [ ] `/api/docs` **404** veriyor (üretimde kapalı olmalı)
- [ ] Yönetici girişi çalışıyor, ilk girişte MFA kurulumu çıktı
- [ ] `deneme1234` ile **hiçbir hesaba girilemiyor**
- [ ] Hak Ediş → dönem paneli 2026-01'de **152.700,00 ₺** gösteriyor
- [ ] Cihazlar ekranı **17.350** yazıyor ve son sayfa açılıyor
- [ ] İş emirleri listesi **1.226** ile tutuyor
- [ ] Bir IMEI aratıldığında müşterisi, aracı ve hattı görünüyor
- [ ] Bir hesabın **Belgeler** sekmesinden vergi levhası PDF'i açılıyor
- [ ] `test-verisi-temizle` "silinecek" satırlarında **sıfır** gösteriyor
- [ ] `hat-durumu-duzelt` **sıfır** hat buluyor
- [ ] Yeni montaj girişinde fiyat kendiliğinden geliyor (ATS 350, OBD 150)
- [ ] Saat dilimi teyidi yapıldı (EK D)
- [ ] Sunucu yeniden başlatıldı, yığın kendiliğinden kalktı ve
      `docker compose logs worker` dört görevin **bittiğini** yazıyor
      (ilk turda "yeniden denenecek" görmek normal: veritabanı worker'dan
      birkaç saniye sonra hazır olur, worker saniyeler içinde toparlar)
- [ ] Bir gecelik yedek oluştu ve uzak hedefe kopyalandı
- [ ] Geri yükleme provası yapıldı, sayılar tuttu
- [ ] fail2ban `denge-erp-login` jail'i aktif
- [ ] Parametreler ekranından oranlar, şirket künyesi ve SMTP girildi
- [ ] **Görevler** menüsü açılıyor, bir pano açılabiliyor (kolonlar hazır geliyor)
- [ ] Bir teklif bağlantısı gizli sekmede (oturumsuz) açılıyor

---
---

# EK A — Sorun giderme

### `service "api" is not running`

Yığın henüz başlamamış. `docker compose exec` yalnız **çalışan** bir
konteynere girer. `./kur.sh` komutunu tekrar çalıştırın (Adım 3).

### `failed to resolve host 'db'`

`api`, veritabanı konteynerini bulamıyor — parola ya da şema sorunu değil,
ağ sorunu. `restart: unless-stopped` yüzünden aynı hata sonsuz tekrarlanır;
logdaki yüzlerce satır tek bir sorunun kopyasıdır.

```bash
docker compose ps -a
docker compose logs db --tail 30
```

En sık sebebi `docker compose up -d api` yazılmasıdır — bu yalnız `api`'yi
kaldırır. Servis adı vermeden yazın:

```bash
docker compose up -d
```

`db` hiç başlamıyorsa `.env`'de `POSTGRES_PASSWORD` yoktur.

### `relation "accounts" already exists`

Dökümü, şeması zaten kurulmuş bir veritabanına yüklüyorsunuz (uygulama
başlatıldıktan sonra). **Veri yoksa** `./kur.sh` dökümü kendi yükler (Adım 3); elle yüklemek isterseniz:

```bash
cd /opt/denge-erp
docker compose down
docker volume rm denge-erp_pgdata      # DİKKAT: veritabanını siler
docker compose up -d db
# ...dökümü yükleyin, sonra docker compose up -d
```

Veritabanında değerli bir şey varsa bu komutu **çalıştırmayın**; önce yedek
alın.

### Worker sürekli "görev yeniden denenecek" yazıyor

Bir-iki tur normaldir (veritabanı henüz hazır değildir). Dakikalarca
sürüyorsa veritabanına gerçekten ulaşılamıyordur:

```bash
docker compose ps db
docker compose logs db --tail 20
docker compose exec -T db psql -U dengeerp -d dengeerp -c "select 1"
```

`deneme=3` ve üstünde aralık iki dakikaya sabitlenir; worker kendini
düşürmez, düzelince kendiliğinden devam eder.

### `SyntaxError: source code string cannot contain null bytes`

> **`./kur.sh` bu hatayı kendi kapatır** — `._*` dosyalarını kaynakta ve
> hedefte siler; `.dockerignore` ve `Dockerfile` ayrıca imaja girmelerini
> engeller. Bu bölüm eski bir kurulumu onaranlar için duruyor.

`api` konteyneri `alembic upgrade head`'de, bir migration dosyasını
**yüklerken** düşer. Sebep veritabanı değil: `backend/alembic/versions/`
içindeki `.py` dosyalarından biri bozuk. Alembic o dizindeki **her** `.py`'yi
içe aktardığı için tek bozuk dosya tüm açılışı engeller.

Sebep neredeyse her zaman **macOS AppleDouble yan dosyalarıdır**: `._` önekli,
163 baytlık, ilk baytı NUL olan ikili dosyalar. macOS'tan genişletilmiş
özellik desteklemeyen bir hedefe (SMB paylaşımı, exFAT disk, bazı SFTP
istemcileri) kopyalarken kendiliğinden oluşurlar.

İki tuzak bu hatayı teşhis etmeyi zorlaştırır:

- **`ls *.py` onları göstermez.** Kabuk kalıpları baştaki noktayı eşlemez,
  bu yüzden `ls versions/*.py | wc -l` dosyalar orada dururken doğru sayıyı
  verir. `ls -a` ya da `find` kullanın.
- **`grep -P '\x00'` NUL baytını bildirmez.** GNU grep PCRE kipinde NUL
  içeren girdiyi düzgün işlemez; "bozuk dosya yok" çıktısı yanlış negatiftir.
  `on-kontrol.sh` bu ölçümü Python ile yapar.

`cp` ve `tar -x` hedefte fazladan duran dosyaları silmediği için arşivi
yeniden çıkarmak da sorunu çözmez.

Önce suçluyu görün — bu komut kesin ölçer:

```bash
/opt/denge-erp/deploy/on-kontrol.sh
```

"macOS AppleDouble / .DS_Store dosyasi: N dosya" satırı varsa sorun odur.
Elle de bakmak isterseniz:

```bash
cd /opt/denge-erp && find . -name '._*' -o -name '.DS_Store' | head -20
```

Çözüm — paket dizininden kurulum betiğini tekrar çalıştırın; `._*`
dosyalarını siler, kodu `rsync --delete` ile tazeler, imajı yeniden kurar
(`.env` ve yüklenen dosyalar korunur, veri yüklenmez):

```bash
cd ~/denge-canli && ./kur.sh
```

Paket elinizde değilse elle:

```bash
cd /opt/denge-erp
find . -name '._*' -delete
find . -name '.DS_Store' -delete
docker compose build api worker
docker compose up -d --force-recreate api worker
```

### `tar: Ignoring unknown extended header keyword 'LIBARCHIVE.xattr...'`

**Zararsız — kurulumu bozmaz, bir şey yapmanız gerekmez.** Arşiv macOS'ta
üretildiyse dosyaların macOS'a özel genişletilmiş özellikleri (`com.apple.*`)
arşive de yazılır; sunucudaki GNU tar bunları tanımaz, atlar ve her dosya için
bir uyarı basar. **Dosyaların kendisi eksiksiz çıkarılır.**

Şüpheniz varsa çıkarmanın tam olduğunu doğrulayın:

```bash
cd /opt/denge-erp
ls backend/app/static/index.html docker-compose.yml backend/alembic/versions >/dev/null \
  && echo "cikarma tam"
```

Uyarıyı hiç görmemek için arşivi `tar --warning=no-unknown-keyword -xzf ...`
ile açabilirsiniz. 7 Ekim 2026'dan sonra üretilen paketlerde bu uyarı çıkmaz.

### `password authentication failed for user "dengeerp"`

> **`./kur.sh` bu hatayı kendi kapatır** — 6. aşamada rol parolasını her
> kurulumda `.env` ile eşitler ve TCP+scram ile doğrular. Bu bölüm betiği
> kullanmadan elle müdahale edenler için duruyor.

**Sebep:** veritabanı birimi DAHA ÖNCEKİ bir parolayla kurulmuş.
`POSTGRES_PASSWORD` yalnız veri dizini **ilk kez** oluşturulurken geçerlidir;
`.env`'i sonradan yeniden üretirseniz
Postgres eski parolayı korur, uygulama ise yeni parolayı dener.

**Veri silinmez.** Rolün parolasını `.env`'dekine eşitlemek yeter — yerel
soket bağlantısı `trust` olduğu için parola bilmeden girilebilir:

```bash
cd /opt/denge-erp
PAROLA=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
docker compose exec -T db psql -U dengeerp -d postgres \
  -c "ALTER USER dengeerp WITH PASSWORD '$PAROLA';"
docker compose up -d
```

Doğrulama — uygulamanın yaptığı gibi TCP üzerinden bağlanır:

```bash
cd /opt/denge-erp
PAROLA=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
docker compose exec -T -e PGPASSWORD="$PAROLA" db \
  psql -h 127.0.0.1 -U dengeerp -d dengeerp -tA -c "select count(*) from accounts;"
```

Sayı dönüyorsa düzelmiştir. **Nerede kaldığınızı şununla anlayın:**

```bash
docker compose exec -T db psql -U dengeerp -d dengeerp -tA \
  -c "select count(*) from accounts;" 2>&1 | tail -1
```

- **480** → döküm zaten yüklü; `./kur.sh` komutunu tekrar çalıştırın, kaldığı yerden sürer.
- `relation "accounts" does not exist` → döküm henüz yüklenmemiş,
  `./kur.sh` komutunu tekrar çalıştırın; dökümü kendi yükler.

> Veritabanını sıfırdan kurmak isterseniz (yalnız **döküm henüz
> yüklenmediyse**): `docker compose down && docker volume rm denge-erp_pgdata`
> — bu komut veriyi **kalıcı olarak siler**, yüklü döküm varsa kullanmayın.

### Caddy açılmıyor: `open /var/log/caddy/access.log: permission denied`

Caddy yapılandırmayı **yükleyemeyince servis düşer** ve hiçbir port
dinlenmez. Dizini açmak yetmez: daha önce root olarak çalışmış bir Caddy
varsa `access.log` dosyası root'a aittir ve `caddy` kullanıcısı açamaz.
`chown` bu yüzden **özyinelemeli** olmalıdır:

```bash
sudo mkdir -p /var/log/caddy
sudo chown -R caddy:caddy /var/log/caddy
sudo chmod 755 /var/log/caddy
sudo systemctl restart caddy
systemctl is-active caddy
```

Bu sırada şaşırtıcı bir yan etki olur: **eski Caddy süreci hâlâ ayakta**
olabilir ve port 80'de öntanımlı "Caddy works!" sayfasını verir. Dışarıdan
bakan kişi "sunucu cevap veriyor" sanır, oysa sizin yapılandırmanız hiç
yüklenmemiştir. İki işaret ayırt eder:

- `http://alan-adiniz/` **308 yönlendirme** yerine **200** dönüyorsa,
- `ss -tlnp` 443'ü dinleyen bir Caddy **göstermiyorsa**,

yüklü olan sizin yapılandırmanız değildir. `systemctl is-active caddy`
ve `journalctl -u caddy -n 20` gerçeği söyler.

Hâlâ izin reddi alıyorsanız systemd sertleştirmesine bakın:

```bash
systemctl cat caddy | grep -iE 'User|Group|Protect|ReadWrite|LogsDirectory'
```

`ProtectSystem=strict` varsa birim dosyasına `ReadWritePaths=/var/log/caddy`
eklemek (ya da `LogsDirectory=caddy` kullanmak) gerekir:

```bash
sudo systemctl edit caddy     # [Service] altina: ReadWritePaths=/var/log/caddy
sudo systemctl daemon-reload && sudo systemctl restart caddy
```

### `Unable to locate package caddy`

Caddy'nin resmî deposu eklenmemiş. Adım 5'in ilk komut bloğunu (depo ekleme)
atlamış olabilirsiniz; baştan koşun. `sudo apt update` satırını atlamak da
aynı hatayı verir.

### `rsync: ... No such file or directory` (yedek alırken)

`UZAK_HEDEF` olarak verdiğiniz dizin yok ya da bağlı değil. Önce
`ls -ld <dizin>` ile kontrol edin; hedef hazır olana kadar yedeği
`UZAK_HEDEF` vermeden alın — yedek yine oluşur, yalnız uzak kopya atlanır.

### `No module named app.worker`

`worker` konteynerinin imajı eski. `docker compose build api` yalnız `api`
imajını yeniler; `worker` ayrı bir imajdır. Servis adı vermeden derleyin:

```bash
docker compose build && docker compose up -d
```

Bu sessiz bir arızadır: gece cihaz uzlaştırması, oturum temizliği ve yetim
dosya toplayıcı çalışmaz, kimse fark etmez.

### `api` açılışta duruyor (`Exited (1)`)

```bash
docker compose logs api --tail 40
```

Uygulama, üretim yapılandırması eksikse **bilerek** açılmaz ve eksik
anahtarları tek tek listeler (`Üretim yapılandırması eksik (.env)`). Listeyi
`.env`'e girip `docker compose up -d` deyin. Sessizce çalışan ama oturum
jetonu tahmin edilebilir bir ERP, hiç açılmayandan kötüdür.

### Giriş 200 dönüyor ama içeri girilmiyor

HTTPS'siz deniyorsunuz. Adım 5'i tamamlayın, `https://` ile girin.

### Yönetici hesabı kilitlendi

Giriş kilidi süreli değildir: 5 hatalı denemede kapanır ve bir yönetici
açana kadar kapalı kalır. Yönetici de kilitlenirse tek çıkış budur:

```bash
cd /opt/denge-erp
docker compose exec -T api python -m app.yonetim kilitliler
docker compose exec -T api python -m app.yonetim kilit-ac admin
```

### Yönetici MFA'sını kaybetti

```bash
cd /opt/denge-erp
docker compose exec -T api python -m app.yonetim canliya-hazirla --uygula
```

Parolayı ve MFA'yı birlikte yeniler; yeni parola ekrana basılır. Diğer
kullanıcıların MFA'sı **Kullanıcılar** ekranından sıfırlanır.

### Belgeler 404 veriyor

Belgeler yüklenmemiş (`kur.sh` bunu Adım 3'te yapar). Dosya sayısını kontrol edin:

```bash
docker compose exec -T api sh -c 'find /app/var/files -type f | wc -l'
```

**Göç betiklerini ileride çalıştırırsanız konteynerin İÇİNDE çalıştırın**
(`docker compose exec api python -m app.migration...`). Ana makinede koşarsa
dosyalar host dizinine yazılır, uygulama Docker birimini okur; kayıt
veritabanında görünür ama indirilemez.

---

# EK B — Sürüm yükseltme

Yeni bir `denge-canli` paketi aldığınızda **kurulumun aynı komutu** koşar:

```bash
sudo UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh   # önce yedek
cd ~/denge-canli-yeni && chmod +x kur.sh on-kontrol.sh dogrula.sh
./kur.sh
```

`kur.sh` yükseltmede şunları yapar ve **yapmaz**:

- Kodu `rsync --delete` ile tazeler: eski sürümde olup yenisinde olmayan
  dosyalar (silinmiş bir migration, kaldırılmış bir modül) hedefte **kalmaz**.
  Bu silme olmadan uygulama açılışta o artıklara takılır.
- `.env`'e **dokunmaz** — sırlarınız, alan adınız yerinde kalır.
- Veritabanında veri olduğu için dökümü **yüklemez**; mevcut veriniz korunur.
- İmajları yeniden kurar, `api`/`worker`'ı yeni imajla oluşturur, açılışta
  `alembic upgrade head` yeni migration'ları uygular.
- Sonunda sayıları basar; yükseltme öncesi/sonrası karşılaştırabilirsiniz.

`--alan` vermeniz gerekmez; `.env` zaten dolu.

Yükseltmeden sonra:

```bash
/opt/denge-erp/deploy/dogrula.sh
cat /opt/denge-erp/SURUM.txt
```

---

# EK C — Karar bekleyen kayıtlar

Bunlar hata değil, **karar bekleyen gerçek veri**. Canlıya çıkmayı
engellemez; ekip ekranlardan çözer.

| Ne | Adet | Nerede |
|---|---:|---|
| `KARAR_BEKLIYOR` iş emri kalemi (2026-07, 11.600 ₺) | 19 | Hak Ediş → dönem paneli |
| Montaj noktası atanmamış karar bekleyen kalem | 3 | G202607-01199 / -01200 / -01206 |
| Belge tipi `BELIRSIZ` montaj noktası | 39 | Hesaplar → montaj noktası kartı |
| `ARMOLI-BELIRSIZ` üzerindeki cihaz | 2.446 | Cihazlar → ürün filtresi |
| Bayi ekli mükerrer hesap adayı | 78 | Hesaplar → "Mükerrer adayları" |
| Eşleşmeyen vergi levhası | 6 | Kullanıcıda |
| ICCID'si yer tutucu olan hat | 9.192 | Hatlar → "ICCID eksik" filtresi |
| Başlangıcı bilinmeyen cihaz–hat eşleşmesi | 6.469 | Cihaz kartı → "başlangıç tarihi bilinmiyor" rozeti |
| Başlangıcı bilinmeyen cihaz–araç eşleşmesi | 2.783 | Cihaz kartı → "başlangıç tarihi bilinmiyor" rozeti |
| Cihaz–SIM eşleşmesi (gerçek tarih bekliyor) | 2.097 | Kullanıcıda |

**Belge tipi `BELIRSIZ` özel:** hak ediş dökümü onayı bu yüzden engellenir —
stopaj ve damga oranı belge tipine bağlı. İlk ödeme koşusundan önce her
montaj noktası için seçilmeli (fatura / serbest meslek makbuzu / gider
pusulası). Sistem sessizce yanlış hesaplamaz, net mesajla durdurur.

**Montaj noktası atanmamış 3 kalem:** kaynak dosyada işi kimin yaptığı
yazmıyor. Karar verilse bile hak ediş satırı oluşmaz; önce montaj noktası
atanmalı.

---

# EK D — Saat dilimi teyidi

Göç sırasında kaynak zaman damgaları **UTC** kabul edildi. Takip platformu
yerel saat (UTC+3) veriyorsa, 21:00'den sonra kaydedilen 299 satır ekranda
bir gün sonra görünür (142 cihaz–araç, 157 cihaz–SIM dönemi; 30 Eyl 2026'da
canlı veriden sayıldı).

**Hak edişi etkilemez** — dönem `settlement_period` alanından gelir, zaman
damgasından değil.

**Teyit:** montaj tarihini kesin bildiğiniz bir cihazın kartını açın. Tarih
bir gün ileri görünüyorsa kayma vardır ve şu SQL ile düzeltilir:

```bash
cd /opt/denge-erp
docker compose exec -T db psql -U dengeerp -d dengeerp -c "
update device_vehicle_assignments set valid_from = valid_from - interval '3 hours'
 where valid_from is not null and valid_from::time >= '21:00';
update sim_device_history set valid_from = valid_from - interval '3 hours'
 where valid_from is not null and valid_from::time >= '21:00';"
```

Kayma yoksa **bu SQL'i çalıştırmayın** — doğru tarihleri bozar.

Başlangıcı bilinmeyen (tarihsiz) eşleşmelere dokunmaz: `valid_from` NULL olan
satır zaten bir zaman iddia etmiyor.

---

# EK E — En az yetkili veritabanı kullanıcısı (önerilir)

Varsayılan kurulumda uygulama şema sahibiyle bağlanır ve teoride `DROP TABLE`
yapabilir. Ayırmak için:

```bash
cd /opt/denge-erp
docker compose exec -T db psql -U dengeerp -d dengeerp < deploy/db-least-privilege.sql
```

Betikteki parolayı değiştirin, `.env`'deki `DATABASE_URL`'i `dengeerp_app`
kullanıcısına çevirin ve migration ile seed'i **sahibiyle** çalıştırmaya devam
edin (betiğin sonundaki komutlar). Bu durumda `api` konteynerinin açılış
komutundan `alembic upgrade head` ve `python -m app.seeds.dev` adımlarını
çıkarıp sürüm yükseltmelerinde elle çalıştırın.

SQL enjeksiyonunda kalan asıl kaldıraç budur ve kod değil kurulum işidir.

---

# EK F — Göçleri sıfırdan koşmak

**Bu yolu kullanmayın.** Adım 3'te yüklenen veritabanı dökümü tercih edilir.

Veri geliştirmede oluşturuldu ve doğrulandı; arkasında sekiz ayrı göç ve
**insan kararları** var (hesap birleştirmeleri, 0,95 benzerlik kuralı, tarife
eşleştirmeleri, elle doğrulanmış vergi levhası eşleşmeleri). Sunucuda göçleri
yeniden koşmak, tüm kaynak Excel'lerini ve karar dosyalarını oraya taşımayı
ve aynı kararların aynı sırayla tekrarlanmasını gerektirir — kırılgan ve
gereksiz.

Yine de gerekirse göç betikleri `backend/app/migration/` altında; hepsi
`--uygula` olmadan hiçbir şey yazmaz ve idempotenttir.
