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
| `on-kontrol.sh` | Kaynak ağacını, migration zincirini (tek head, en az 39 dosya) ve `.env`'i mekanik denetler; `kur.sh` içinden de koşar |
| `dogrula.sh` | Kurulumdan sonra her an durum raporu verir (göç sürümü, roller, servis tabloları, worker görevleri, son yedek) |
| `yedekle.sh`, `geri-yukle.sh` | Yedek (Adım 8) ve geri yükleme / geri dönüş (EK G.6) |
| `cikis-provasi.sh`, `servis_duman.py`, `CIKIS-PROVASI-TUTANAGI.md` | Canlıya çıkış provası — yalnız prova sunucusunda (EK G.7) |
| `denge-erp-kaynak.tar.gz` | Uygulamanın kendisi (arayüz derlenmiş halde içinde) |
| `denge-veritabani.sql.gz` | Veritabanı dökümü — 480 hesap, 17.350 cihaz, 12.553 hat, **552.825,00 ₺ hak ediş** |
| `denge-dosyalar.tar.gz` | Yüklenen belgeler (21 dosya: vergi levhaları vb.) |
| `SURUM.txt` | Paketin tarihi, commit'i, dökümün göç sürümü, **hedef head** ve teknik servis sürümü — sunucuda hangi sürüm kurulu, buradan okunur |
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
cd ~/denge-canli && chmod +x *.sh && ls -lh
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

**Yedek dizini tek yerden ayarlanır.** `yedekle.sh` yazar, `dogrula.sh` aynı
dizinde son yedeği arar; ikisi de varsayılan `/var/backups/denge-erp`'i
kullanır. Başka bir dizin istiyorsanız betikleri düzenlemeyin, ikisinin de
okuduğu dosyaya yazın:

```bash
echo 'YEDEK_DIZIN=/srv/yedek/denge-erp' | sudo tee /etc/default/denge-erp
```

`dogrula.sh` son yedeğin 26 saatten eski olmamasını ve yanında dosya
yedeğinin (`dosyalar-*.tar.gz.gpg`) bulunmasını da denetler.

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
      bağlantısı, sayılar, hak ediş toplamı, çakışan dönem, göç sürümü =
      beklenen head, roller, teknik servis tabloları, worker görevleri, son yedek)
- [ ] `https://erp.dengemobil.com.tr` açılıyor, kilit simgesi var
- [ ] `docker compose logs worker` her görevin bittiğini yazıyor (görev
      listesini ve eksik olanı `dogrula.sh` "Worker görevleri" bölümü verir)
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
      `docker compose logs worker` her görevin **bittiğini** yazıyor
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
ls -lh /var/backups/denge-erp | tail -2                       # adı ve boyutu tutanağa
cd ~/denge-canli-yeni && chmod +x *.sh
cat SURUM.txt          # "hedef head" ve "teknik servis" satırları
./kur.sh
```

Teknik servis modüllerini getiren yükseltmede (Dalga 0–4) ek adımlar,
bayraklar ve geri dönüş kuralı **EK G**'dedir; o yükseltmeden önce canlı döküm
kopyasında çıkış provası (EK G.7) yapılmış olmalıdır.

`kur.sh` yükseltmede şunları yapar ve **yapmaz**:

- Kodu `rsync --delete` ile tazeler: eski sürümde olup yenisinde olmayan
  dosyalar (silinmiş bir migration, kaldırılmış bir modül) hedefte **kalmaz**.
  Bu silme olmadan uygulama açılışta o artıklara takılır.
- `.env`'e **dokunmaz** — sırlarınız, alan adınız yerinde kalır.
- Veritabanında veri olduğu için dökümü **yüklemez**; mevcut veriniz korunur.
- İmajları yeniden kurar, `api`/`worker`'ı yeni imajla oluşturur, açılışta
  `alembic upgrade head` yeni migration'ları uygular.
- Sonunda sayıları basar; yükseltme öncesi/sonrası karşılaştırabilirsiniz.
- Göç sürümünün koddaki head'e ulaştığını denetler; ulaşmadıysa durur
  (genellikle EK E uygulanmış ve migration sahibiyle koşulmamıştır).
- **Geri almaz.** `alembic downgrade` canlıda kullanılmaz; geri dönüş yedekten
  geri yüklemedir (EK G.6).

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

**Denetim izi ve bu ayrım (Dalga 4):** `audit_logs` satırları veritabanı
tetikleyicisiyle korunur (`trg_audit_degistirilemez`, migration
`d4a000000001`): silme her zaman, değiştirme KVKK maskesi dışında reddedilir.
Tetikleyici `TRUNCATE`'i durdurmaz; bu yüzden uygulamanın bağlandığı
kullanıcıda `TRUNCATE` yetkisi olmamalıdır. `db-least-privilege.sql` yalnız
`SELECT, INSERT, UPDATE, DELETE` verir; şema sahibiyle bağlanan varsayılan
kurulumda bu koruma eksik kalır — EK E'nin önerilme sebeplerinden biri budur.

**EK E uygulandıysa her yükseltmede** (`kur.sh`'ten önce ya da `kur.sh`
"göç sürümü ... beklenen ..." diye durduğunda):

```bash
cd /opt/denge-erp
docker compose run --rm -e DATABASE_URL=postgresql+psycopg://dengeerp:SAHIP_PAROLA@db:5432/dengeerp api alembic upgrade head
docker compose run --rm -e DATABASE_URL=postgresql+psycopg://dengeerp:SAHIP_PAROLA@db:5432/dengeerp api python -m app.seeds.dev
docker compose up -d api worker && deploy/dogrula.sh
```

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

---

# EK G — Teknik Servis devreye alma

Teknik servis modülleri (servis işleri, planlama, cihaz kütüğü, planlı bakım,
atölye, kiralama, yedek parça, servis teklifi/maliyet, eğitim, raporlar) beş
dalgada geldi. Bu ek sırasıyla: hangi migration'ların uygulanacağı ve
yükseltme sonrası bayraklar (G.0), eski sistem verisinin göçü (G.1–G.5),
geri dönüş (G.6), çıkış provası (G.7) ve paketin Windows'ta hazırlanması
(G.8).

## G.0 Yükseltme: migration'lar, roller, bayraklar

**Sıra:** önce yedek (Adım 8 / EK B) → `./kur.sh` → `dogrula.sh` → bayraklar →
kullanıcı atama. `kur.sh` başka bir şey istemez; aşağıdaki migration'ları
`api` açılışındaki `alembic upgrade head` **yalnız ileri** uygular ve
`python -m app.seeds.dev` yeni izinleri ve rolleri senkronlar (EK E
uygulandıysa ikisi sahibiyle elle, EK E'nin sonundaki komutlarla).

Canlıda bugünkü göç sürümü `b30e012dd879`'dur (SURUM.txt "goc surumu").
Yükseltme sonunda `dogrula.sh` "göç sürümü `d4a000000002` = koddaki beklenen
head" yazmalıdır.

| Dalga | Revizyon | İçerik |
|---|---|---|
| 0 | `d0a000000001` | birim üyeliği (`user_units`), personel kolonları, personel ad eşleme |
| 0 | `d0a000000002` | hesap/lokasyon ana veri kolonları, takma ad, hesap birleştirme |
| 0 | `d0a000000003` | servis işi çekirdeği: iş, seri, olay, bekleme, sonuç, atama, onay, arıza/bekleme nedeni katalogları |
| 0 | `d0a000000004` | servis ekipman kütüğü |
| 0 | `d0a000000005` | planlama, ziyaret, ekip, araç, müsait olmama |
| 0 | `d0a000000006` | bakım sözleşmesi, dönem, form |
| 0 | `d0a000000007` | saha zaman kaydı |
| 2 | `d2a000000001` | SLA politikası, servis uyarıları |
| 2 | `d2a000000002` | atölye |
| 2 | `d2a000000003` | depo ayrımı ve kiralama |
| 2 | `d2a000000004` | yedek parça stok defteri, sayım, parça talebi |
| 2 | `d2a000000005` | servis teklifi, işçilik tarifesi, iş finansalları |
| 2 | `d2a000000006` | eğitim, yetkinlik, belge |
| 2 | `d2a000000007` | servis işi ↔ kiralama/atölye bağı |
| 3 | `d3a000000001` | kiralama sayımı |
| 3 | `d3a000000002` | servis e-posta bildirimi ve e-posta kutusu |
| 3 | `d3a000000004` | eğitim–yetkinlik eşlemesi |
| 4 | `d4a000000001` | denetim kaydının değiştirilemezliği (`trg_audit_degistirilemez`) |
| 4 | `d4a000000002` | süreli vekâlet (`user_permissions` başlangıç/bitiş) |

`d3a000000003` (mesai takvimi) **bilerek yoktur**: mesai takvimli SLA kararı
verilmedi, revizyon atlandı ve zincir `d3a000000002 → d3a000000004` devam
eder. Dalga 1'in kendi migration'ı yoktur (şeması Dalga 0'da kuruldu). Toplam
39 migration dosyası; `on-kontrol.sh` daha azını kabul etmez.

Hiçbiri mobilite tablolarındaki veriyi değiştirmez; yalnız yeni tablo, yeni
nullable kolon ve kısıt ekler. Hak ediş toplamı yükseltme öncesi ve sonrası
kuruşu kuruşuna aynı kalır (çıkış provasında denetlenir, G.7).

**Yeni roller** (seed açar; `dogrula.sh` kodda tanımlı her rolün varlığını
denetler): Teknik Servis Müdürü (`SERVIS_YONETICI`), Teknik Servis Şefi
(`SERVIS_SEF`), Operasyon Uzmanı (`SERVIS_OPERASYON`), Servis Teknisyeni
(`SERVIS_TEKNISYEN`), Atölye (`ATOLYE`), Servis Deposu (`SERVIS_DEPO`),
Kiralama Deposu (`KIRALAMA_DEPO`), İnsan Kaynakları (`IK`). Mevcut dokuz rol
aynen kalır; **özelleştirilmiş** bir role yeni izin inmez, `api` log'u "elle
eklenecek" listesini yazar.

**Yeni worker görevleri** (`dogrula.sh` son 25 saatte her birinin bittiğini
denetler): `pb-uretimi`, `bakim-donem-uzlastirma`, `servis-sla-uyarilari`,
`servis-uyari-temizligi`, `servis-eposta` (mevcut dördüne ek).

**Devreye alma bayrakları** (Parametreler ekranı; `dogrula.sh` değerlerini
listeler). Yükseltme bunları kapalı/boş getirir; sırası:

| Bayrak | İlk değer | Ne zaman değişir |
|---|---|---|
| `bakim_otomatik_uretim` | `false` | bakım sözleşmesi eşleştirmesi %100 olunca (Planlı Bakım ekranı) |
| `servis_sla_yururluk_at` | boş | ilk birimin (GUVENLIK) göçü bitince **bir kez** şimdiki zaman (G.3) |
| `servis_eposta_acik` | `false` | SMTP tanımlı ve pilot birim ilk haftayı bitirince (Operasyon Merkezi → E-posta kutusu) |

**Kullanıcı atama:** servis rolleri ve birim üyeliği önce pilot birime
(GUVENLIK) verilir. Menü yalnız izinli kullanıcıya görünür; diğer
kullanıcılar için ERP değişmemiş görünür. İlk gün "yalnız pilot birim +
saatlik yedek" uygulanır (G.6):

```bash
sudo crontab -e   # ilk gün: 0 * * * * UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh ...
```

**Caddy / fail2ban:** değişiklik gerekmez; yeni uçlar `/api/*` altında,
aynı kimlik doğrulama ve CSRF ile çalışır.

### G.0.1 Dalga 4 güvenlik değişiklikleri (yükseltmede bir kez)

1. **Gerçek istemci IP'si (TS-211).** `.env`'e Docker ağ geçidini yazın;
   yazılmazsa denetim kaydına her giriş için ağ geçidi IP'si düşer:

   ```bash
   docker network inspect denge-erp_default -f '{{(index .IPAM.Config 0).Gateway}}'
   echo 'FORWARDED_ALLOW_IPS=172.18.0.1' >> /opt/denge-erp/.env   # yukarıdaki değer
   docker compose up -d api
   ```

   Doğrulama: kendi makinenizden bir kez giriş yapın; Denetim Kaydı'ndaki son
   `auth.login` satırının IP'si sizin genel/iç IP'niz olmalı, `172.x` değil.
2. **Denetim izi yetkileri (EK E uygulandıysa).** `db-least-privilege.sql`'in
   "Denetim izi değiştirilemez (Dalga 4)" bloğundaki üç satırı şema sahibiyle
   çalıştırın; bloktaki iki doğrulama sorgusu `dengeerp_app` ile HATA vermeli.
3. **Ek içerik denetimi (TS-218).** Canlı ek türlerinde (hesap, cihaz, ürün,
   RMA...) magic-byte denetimi **kuru koşuda** gelir: uyuşmayan dosya kabul
   edilir ve denetime yazılır. Bir hafta sonra yönetici
   `GET /api/ekler/icerik-denetimi` raporunu okur; rapor temizse (ya da
   uyuşmazlıklar incelenip kabul edildiyse) Parametreler → 
   `ek_icerik_denetimi_canli_turler = true`. Açıldıktan sonra uyuşmayan yükleme
   422 alır.
4. **Sürüm notu — kullanıcıya duyurun:**
   - Kilitli hesap artık 423 değil, yanlış parolayla **aynı 401** ve aynı metni
     alır (hesabın varlığı sızmasın). Giriş ekranı "kilitlendiyse yöneticinize
     başvurun" der; kilidi yönetici açar (`python -m app.yonetim kilit-ac`).
   - Yöneticinin belirlediği/sıfırladığı parola **geçicidir**: 72 saat ve tek
     giriş geçerli, ilk girişte değiştirilmesi zorunlu. `canliya-hazirla`'nın
     ürettiği yönetici parolası ve yeni kurulumun ilk yöneticisi de böyledir.
   - Süreli vekâlet (en çok 30 gün) Personel kartından verilir; süresi dolunca
     gece görevi `vekalet-sona-erme` kapatır.
   - Satış temsilcisi genel aramada ve cihaz/RMA eklerinde yalnız kendi
     portföyünü görür (liste ekranlarıyla aynı kural).
   - Teklif e-postası kullanıcı başına dakikada en çok 10 (ayar
     `teklif_gonderim_dakika_limiti`); aşımda 429.
   - RMA listesi artık sunucu tarafında sayfalı; RMA kaydına ek yüklenebilir.

## G.1–G.4 Eski .NET DengeERP servis verisinin göçü (Göç-1)

Teknik servis verisi (cihaz kütüğü, bakım sözleşmeleri, servis işleri, planlar,
zaman kayıtları) eski .NET DengeERP V1.20.1'den (SQL Server) **bir kez ve
tekrarlanabilir** biçimde aktarılır. Göç idempotenttir: aynı döküm ikinci kez
uygulanınca 0 yeni satır yazılır ve ekrandan yapılmış düzeltme ezilmez.
Hiçbir adım uygulama açılışında koşmaz; hepsi elle, sırayla çalıştırılır.

> **ÖNCE YEDEK.** Her yazan adımdan (`ad-uygula`, İçe Aktarma "Uygula",
> `goc-servis-uygula`) önce `sudo UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh`
> çalıştırın; yedek dosyasının adını ve boyutunu göç tutanağına yazın. Geri
> dönüş yalnız yedekten geri yüklemedir (`alembic downgrade` kullanılmaz).

### G.1 Kaynağı dışa aktar (canlı SQL Server'a BAĞLANMAYIN)

1. V1.20.1 `.bak` yedeğini **ayrı bir SQL Server test örneğine** geri yükleyin.
2. O örneğe erişen bir Windows makinesinde (SqlServer PowerShell modülü kurulu):

   ```powershell
   powershell -File backend\app\migration\teknik_servis\sql\disa_aktar.ps1 `
       -Sunucu "localhost\SQLTEST" -Veritabani DengeERP -Hedef C:\goc\v1
   ```

   Her `goc_NN_<Tablo>.sql` yalnız `SELECT` içerir ve `<Tablo>.csv` üretir
   (UTF-8; seri no metin; tarih ISO 8601, eski sistemin **yerel saati** —
   göç UTC'ye kendisi çevirir). Kişi notları ve telefonlar bilerek alınmaz.
3. Dizini sunucuya kopyalayın (ör. `/opt/denge-erp/goc/v1`) ve konteynere verin:
   `docker compose cp /opt/denge-erp/goc/v1 api:/tmp/goc_v1`.

Aşağıda `GOC="docker compose exec -T api python -m app.migration"` kısaltması
kullanılır (geliştirmede aynı komutların `make` hedefleri vardır, `make help`).

### G.2 İnsan kararı gereken adımlar (sıra zorunlu)

| Sıra | Ne | Komut / ekran | İzin |
|---|---|---|---|
| 1 | Personel listesi | İçe Aktarma → **Personel** | `personel.yaz` |
| 2 | Ad eşleme önerisi | `$GOC.servis_ad_esleme oner --kaynak /tmp/goc_v1 --cikti /tmp/ad.xlsx` (`make goc-servis-ad-oner`) | — |
| 3 | İK ad kararları | İçe Aktarma → **Personel Ad Eşleme (göç)**; `Karar`: E / H / ESLESMEDI | `personel.yaz` |
| 4 | Cihaz kütüğü | G.3 komutları `--adim kutuk` ile | sunucu erişimi |
| 5 | Bakım sözleşmesi teyidi | `$GOC.bakim_sozlesme --kaynak /tmp/goc_v1 --cikti /tmp/bakim.xlsx` → servis yöneticisi doldurur → İçe Aktarma → **Bakım Sözleşmesi (göç/teyit)** | `bakim.yaz` |
| 6 | Müşteri/tesis eşleştirme | Teknik Servis → **Ana Veri Kalitesi** → aday listesi (sözleşme, ekipman); İçe Aktarma → **Müşteri/Lokasyon Eşleştirme** (`Onay=E`). Onaylanan yazımlar takma ad olur; sonraki adım bunları kullanır | `hesap.birlestir` |
| 7 | Servis işleri + plan + zaman | G.3 komutları `--adim servis,plan,zaman` ile | sunucu erişimi |
| 8 | Servis işi karantinası | G.3 raporunun `_servis_isleri_karantina.xlsx` dosyası → `Tür/Durum` doldurulur → İçe Aktarma → **Servis İşleri (göç karantinası)** | `sistem.goc` |

Notlar:

- Ad eşleme **önerisi uydurma değildir**: sistem yalnız birebir ad ve benzerlik
  önerir, karar İK'nındır. Onaylanmayan ad "eşleşmedi" kalır; zaman kaydı
  `user_id` boş + ham adla gelir. Sonradan onay verilirse
  `$GOC.servis_ad_esleme uygula` (`make goc-servis-ad-uygula`) bu satırları
  bağlar, `goc-servis-uygula` yeniden koşulursa eksik atamalar eklenir.
- Bakım teyit Excel'inde **ücret kolonları yoktur**. Ücretli liste yalnız
  `maliyet.gor` sahibine `--ucret` ile üretilir; ücretsiz kullanıcının yüklediği
  dosyadaki ücretler yok sayılır. Ekrandan yönetilen (TEYIT_BEKLIYOR dışı)
  sözleşme yüklemede **korunur**.
- Birden çok müşteri adayı olan satır karantinaya düşer; `Hesap Id`
  yazılarak karar verilir.

### G.3 Önizleme → uygulama → uzlaşma

```bash
$GOC.servis_uzlasma onizleme --kaynak /tmp/goc_v1 --cikti /tmp/goc_onizleme.xlsx   # yazmaz
$GOC.servis_uzlasma uygula   --kaynak /tmp/goc_v1 --cikti /tmp/goc_uygulama.xlsx  # tek transaction
$GOC.servis_uzlasma rapor    --kaynak /tmp/goc_v1 --cikti /tmp/goc_uzlasma.xlsx   # salt okunur
docker compose cp api:/tmp/goc_uzlasma.xlsx .
```

Rapor her kaynak tablo için **kaynak = aktarılan + karantina + reddedilen
(+ ertelenen)** eşitliğini sınar; tutmayan tabloda çıkış kodu 2'dir. Ayrıca
karantina/red nedenleri, uyarılar (`SERISIZ`, `MUKERRER_SERI`,
`MUSTERI_ESLESMEDI`, `SONUCSUZ_KAPALI`, `CIFT_AKTIF_PLAN`,
`KAPALI_IKEN_PLANLI` ...) ve eski sistem ekranıyla elle karşılaştırılacak
**5 örnek iş** listelenir. `uygula` ikinci kez koşulunca bütün tablolarda
"yeni" 0 olmalıdır.

**Birim bazlı geçiş:** `--birim GUVENLIK` (sonra `HABERLESME,POC`, sonra
`MOBILITE,ARAC_TAKIP`) yalnız o birimlerin servis işlerini aktarır; diğerleri
raporda "ertelenen" görünür. Plan ve zaman kayıtları yalnız aktarılmış işe
bağlanır, kalanlar karantinada bekler ve sonraki koşuda kendiliğinden gelir.
SLA yürürlük anı (`servis_sla_yururluk_at`) yalnız ilk birim geçişinden sonra
bir kez ayarlanır.

**Bilinçli karantina (bu göçte aktarılmaz):** planlı bakım işleri (bakım
dönemi göçü yok), atölye ve kiralık telsiz işleri (Dalga 3), tanınmayan
durum/tür, okunamayan tarih. Eski parça hareketleri ve kullanıcı parolaları
göç kapsamı dışındadır.

### G.4 Prova sırası

Canlı döküm kopyası (`paket-uret.sh`) → `alembic upgrade head` → G.2/G.3 →
altın kayıt ve mobilite testleri (`make test-goc`) → uzlaşma raporu tutanağa →
canlı.

## G.5 Göç-2: atölye, kiralama, eğitim, SLA geri doldurma, ana veri Faz 2

Göç-1 tamamlandıktan **sonra** ve her yazan adımdan önce yedekle. Atölye ve
kiralama adımları yalnız rapor üretir (pilot gerçek veri üretmediyse göç
yoktur); eğitim ve SLA önizleme → onay → uygulama sırasıyla koşar.

| Sıra | Ne | Sunucuda (`$GOC` = G.1'deki kısaltma) | Geliştirmede | Yazar mı |
|---|---|---|---|---|
| 1 | Atölye pilot sağlık raporu (7 bölüm) | `$GOC.atolye_saglik --kaynak /tmp/goc_v1 --cikti /tmp/atolye_saglik.xlsx` | `make goc-atolye-saglik` | hayır |
| 2 | Kiralama pilot uzlaştırma (4 tür) | `$GOC.kiralama_uzlastirma --kaynak /tmp/goc_v1 --cikti /tmp/kiralama_uzlastirma.xlsx` | `make goc-kiralama-uzlastirma` | hayır |
| 3 | Eğitim göçü | `$GOC.egitim onizleme\|uygula\|rapor --kaynak /tmp/goc_v1 --cikti /tmp/goc_egitim.xlsx` | `make goc-egitim-onizleme` … | `uygula` yazar |
| 4 | SLA geri doldurma | `$GOC.servis_sla_geri_doldur rapor` → onay → `uygula` (`--kaynak` isteğe bağlı) | `make goc-servis-sla-rapor` … | `uygula` yazar |
| 5 | Ana veri eşleştirme Faz 2 adayları | `$GOC.ana_veri_faz2 --kaynak servis_isi\|ekipman_diger --cikti /tmp/faz2.xlsx` | `make goc-ana-veri-faz2 FAZ2=…` | hayır (onay İçe Aktarma'dan) |

Kurallar:

- Eğitim göçünde eşleşmeyen kişi **karantinada** kalır; otomatik kullanıcı
  açılmaz. İkinci `uygula` 0 yeni satır yazmalıdır.
- SLA geri doldurma `servis_sla_yururluk_at` ayarlandıktan sonra koşar:
  kapalı göç işleri `OLCULEMEDI`, açık işler yürürlük anından damgalanır;
  geriye dönük ölçüm yalnız rapordur.
- Eski serbest metin parça kayıtları not olarak taşınmıştır (Göç-1);
  parça hareketi göçü yoktur, açılış stoğu fiziksel sayımladır.

## G.6 Geri dönüş

**Canlıda `alembic downgrade` KULLANILMAZ.** Downgrade'ler testte zorunludur
ama canlıda veri kaybı ve yarım şema riski taşır. Önceki sürüme dönmenin tek
yolu:

1. **Önce yedeği geri yükle** — yükseltmeden hemen önce alınan yedek:

   ```bash
   cd /opt/denge-erp
   sudo HEDEF_DB=dengeerp ZORLA=1 deploy/geri-yukle.sh /var/backups/denge-erp/dengeerp-<damga>.sql.gz.gpg
   ```

   Betik `api` ve `worker`'ı durdurur, veritabanını **silip yeniden yaratır**
   (dump'ı var olanın üstüne yüklemek yeni tabloları bırakırdı ve sonraki
   yükseltme "relation already exists" ile düşerdi), dosyaları da geri açar.
   Bitince `api`/`worker` durmuş kalır.

2. **Sonra önceki paketle `kur.sh`:**

   ```bash
   cd ~/denge-canli-onceki && ./kur.sh
   /opt/denge-erp/deploy/dogrula.sh     # göç sürümü önceki head'i göstermeli
   ```

Sıra önemlidir: önce `kur.sh` koşarsa `rsync --delete` yeni migration
dosyalarını siler ama `alembic_version` yeni head'i gösterdiği için eski kod
açılışta `Can't locate revision` ile düşer. Yeni paketle `api`'yi açmak da
yanlıştır: açılıştaki `alembic upgrade head` yedeği yeniden yükseltir.

Yükseltmeden sonra servis verisi girildiyse geri dönüş **o verinin kaybı**
demektir. Bu yüzden her sürümün ilk günü yalnız pilot birim çalışır ve yedek
saatlik alınır (G.0).

## G.7 Çıkış provası (her R sürümünden önce)

Prova, canlıyla aynı paketin kurulu ve **canlı dökümün kopyasının** yüklü
olduğu ayrı bir sunucuda koşar; canlı sunucuya dokunmaz. Hazırlık:

1. Prova sunucusuna şu an canlıda olan paketi `./kur.sh` ile kurun (boş
   veritabanına o paketin dökümünü yükler), Adım 8'deki yedek parolasını
   oluşturun.
2. Yeni paketi ayrı klasöre açın ve oradan:

   ```bash
   PROVA_ONAY=evet ./cikis-provasi.sh --geri-donus ~/denge-canli-onceki
   ```

Betik sırasıyla: mobilite parmak izi (önce) → `yedekle.sh` → `kur.sh` →
`dogrula.sh` → **altın kayıt** (hesap/cihaz/araç/hat/iş emri sayıları, hak
ediş dökümü ve dönem bazında tutarlar önce = sonra) → **servis duman testi**
(`servis_duman.py`: her servis modülünün uçları kayıtlı; bir arıza işi açılır,
okunur, olay geçmişi yazılır ve transaction geri alınır) → `geri-yukle.sh`
provası (geçici veritabanı) → `--geri-donus` verildiyse G.6'nın tamamı ve
parmak izi yine önce = sonra.

Her adımın başlangıç/bitiş saati ve sonucu `CIKIS-PROVASI-<damga>.md`
tutanağına, çıktının tamamı yanındaki `.log`'a yazılır. Tutanağın biçimi ve
imza bölümü pakette `CIKIS-PROVASI-TUTANAGI.md`'dedir. **PROVA BAŞARISIZ**
yazan tutanakla canlıya çıkılmaz. Geliştirmede ayrıca `make test`
(altın kayıt `test_altin_kayit.py` dahil) ve `make test-goc` yeşil olmalıdır.

## G.8 Paketi hazırlamak (Windows dışı komutlar)

`deploy/paket-uret.sh` (`make paket`) bash, git, docker compose, node/npm ve
python3 ister; **macOS ya da Linux'ta** çalışır. Geliştirme makinesi
Windows ise:

- **WSL (önerilen)** ya da **Git Bash + Docker Desktop** içinde, depo kökünde:

  ```bash
  deploy/paket-uret.sh ~/denge-canli          # make paket ile aynı
  ```

- PowerShell'den doğrudan çalışmaz (`.sh`, `tar`, `$(…)`). Windows'ta
  yalnız testler ve derleme koşar (`araclar\test.ps1`).
- Betikler sunucuda **LF** satır sonuyla çalışır; Windows'ta düzenlenen bir
  `.sh` CRLF'ye dönerse sunucuda `$'\r': command not found` verir.
  `tests/unit/test_deploy_betikleri.py` bunu ve `bash -n` sözdizimini denetler.

Betik şunları yapar: arayüzü derler ve `backend/app/static`'e kopyalar
(derlenmiş arayüzde "Görevler" ve "Operasyon Merkezi" ekranlarını arar),
`git ls-files` ile kaynak arşivi çıkarır (**commit edilmemiş dosya pakete
girmez**), geliştirme veritabanının dökümünü ve yüklenen belgeleri alır,
betikleri ve bu belgeyi pakete kopyalar, `SURUM.txt`'e commit, dökümün göç
sürümü, **hedef head** ve teknik servis sürümünü yazar ve arşive ön kontrolü
koşturur (tek head, en az 39 migration, SURUM.txt ile aynı head).

Sunucu tarafındaki her komut (Adım 1–8, EK B, EK G) Linux'ta, `bash` ile
çalışır; Windows'tan SSH (PowerShell `ssh`, PuTTY) ile bağlanıp sunucuda
koşulur.