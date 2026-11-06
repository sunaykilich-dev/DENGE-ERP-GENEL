#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
if [[ $EUID -ne 0 ]]; then echo 'sudo bash linux/01_sunucuyu_hazirla.sh'; exit 1; fi
if [[ ! -r /etc/os-release ]]; then echo '/etc/os-release bulunamadi'; exit 1; fi
source /etc/os-release
if [[ "$ID" != "ubuntu" || "$VERSION_ID" != "24.04" ]]; then
  echo "Bu paket Ubuntu Server 24.04 LTS icin hazirlandi: bulunan $ID $VERSION_ID"; exit 1
fi
if ! ip -4 addr show | grep -Eq 'inet 10\.10\.50\.16/24([[:space:]]|$)'; then
  echo '10.10.50.16/24 sunucu arayuzunde bulunamadi. IT sabit IP/DNS/ag gecidi ayarini yapmali.'
  echo 'Bu betik network IP adresini otomatik degistirmez.'; exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y dotnet-sdk-10.0 nginx curl unzip ca-certificates
command -v dotnet >/dev/null || { echo 'dotnet kurulamadi'; exit 1; }
dotnet --list-sdks | grep -q '^10\.' || { echo '.NET 10 SDK bulunamadi'; exit 1; }
if ! id dengeerp >/dev/null 2>&1; then
  useradd --system --home /var/lib/dengeerp --shell /usr/sbin/nologin --user-group dengeerp
fi
install -d -m 0755 -o root -g root /opt/dengeerp/releases /etc/dengeerp
install -d -m 0750 -o dengeerp -g dengeerp /var/lib/dengeerp
if [[ ! -e /etc/dengeerp/dengeerp.env ]]; then
   install -o root -g root -m 0600 linux/dengeerp.env.example /etc/dengeerp/dengeerp.env
   echo 'Sablon olusturuldu: /etc/dengeerp/dengeerp.env - IT duzenlemeli.'
fi
install -o root -g root -m 0644 linux/dengeerp.service /etc/systemd/system/dengeerp.service
install -o root -g root -m 0644 linux/nginx/dengeerp-http.conf /etc/nginx/sites-available/dengeerp
systemctl daemon-reload
nginx -t
printf '\nSunucu hazir. HENUZ ERP BASLATILMADI.\n'
printf 'Simdi IT /etc/dengeerp/dengeerp.env icine TEST SQL baglantisini girmeli.\n'
printf 'Ardindan: sudo bash linux/02_yayinla.sh\n'
