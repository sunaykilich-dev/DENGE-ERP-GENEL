#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ $EUID -ne 0 ]]; then echo 'sudo bash linux/02_yayinla.sh'; exit 1; fi
CFG=/etc/dengeerp/dengeerp.env
[[ -f "$CFG" ]] || { echo "Eksik: $CFG - once 01_sunucuyu_hazirla.sh"; exit 1; }
[[ $(stat -c '%a' "$CFG") == 600 ]] || { echo "Guvenlik: $CFG izinleri 600 olmali"; exit 1; }
if grep -Eq 'SQL-SERVER-ADRESI|DEGISTIR_GUCLU_SIFRE|DENGEERP_SQL_USER' "$CFG"; then
  echo 'SQL baglantisi halen sablon; IT ayarlamadan yayin yapilmaz.'; exit 1
fi
if grep -Eq '^DengeERP__RunDatabaseSetupOnStartup=true' "$CFG"; then
 echo 'Otomatik veritabani guncellemesi acik. Bu komut yalnizca kapaliyken kullanilir.'; exit 1
fi
if ! ip -4 addr show | grep -Eq 'inet 10\.10\.50\.16/24([[:space:]]|$)'; then
 echo '10.10.50.16/24 IP atanmamis - yayin yapilmadi'; exit 1
fi
[[ -f "$ROOT/DengeERP.Api/DengeERP.Api.csproj" ]] || { echo 'Kaynak proje bulunamadi'; exit 1; }
BUILD_DIR="$(mktemp -d /tmp/dengeerp-build.XXXXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT
# SQL sunucuya dokunmadan dotnet publish yapar.
dotnet publish "$ROOT/DengeERP.Api/DengeERP.Api.csproj" -c Release -o "$BUILD_DIR/publish" --nologo
[[ -s "$BUILD_DIR/publish/DengeERP.Api.dll" ]] || { echo 'DLL uretilmedi'; exit 1; }
[[ -s "$BUILD_DIR/publish/wwwroot/index.html" ]] || { echo 'Web arayuzu uretilmedi'; exit 1; }
VERSION="v1.20.1-$(date -u +%Y%m%dT%H%M%SZ)"
DEST="/opt/dengeerp/releases/$VERSION"
install -d -m 0755 "$DEST"
cp -a "$BUILD_DIR/publish/." "$DEST/"
chown -R root:root "$DEST"
chmod -R go-w "$DEST"
# Mevcut surum yedegi ve geri donus hedefi.
PREVIOUS=''
if [[ -L /opt/dengeerp/current ]]; then PREVIOUS="$(readlink -f /opt/dengeerp/current)"; fi
if [[ -n "$PREVIOUS" ]]; then printf '%s\n' "$PREVIOUS" > /etc/dengeerp/previous_release; fi
ln -s "$DEST" /opt/dengeerp/.current_new
mv -Tf /opt/dengeerp/.current_new /opt/dengeerp/current
ln -sfn /etc/nginx/sites-available/dengeerp /etc/nginx/sites-enabled/dengeerp
nginx -t
systemctl daemon-reload
systemctl enable --now nginx
if ! systemctl restart dengeerp; then
  echo 'DengeERP servisi baslatilamadi; journalctl -u dengeerp -n 80'
  if [[ -n "$PREVIOUS" ]]; then ln -sfn "$PREVIOUS" /opt/dengeerp/.rollback; mv -Tf /opt/dengeerp/.rollback /opt/dengeerp/current; systemctl restart dengeerp || true; fi
  exit 1
fi
systemctl enable dengeerp
systemctl reload nginx
OK=0
for i in $(seq 1 20); do
  if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:5051/api/health > /tmp/dengeerp-health.json 2>/dev/null; then
    OK=1; break
  fi
  sleep 2
done
if [[ $OK -ne 1 ]]; then
  echo 'Saglik kontrolu BASARISIZ. Onceki surume donuluyor (varsa).'
  journalctl -u dengeerp -n 45 --no-pager || true
  if [[ -n "$PREVIOUS" ]]; then ln -sfn "$PREVIOUS" /opt/dengeerp/.rollback; mv -Tf /opt/dengeerp/.rollback /opt/dengeerp/current; systemctl restart dengeerp || true; else systemctl stop dengeerp || true; fi
  exit 1
fi
printf '\nPILOT TEST SERVISI HAZIR: http://10.10.50.16:5050\n'
printf 'SQL baglantisi kontrol: '; cat /tmp/dengeerp-health.json; printf '\n'
printf 'INTERNETE ACMAYIN. HTTPS ve yetki testleri tamamlanmadan uretime gecmeyin.\n'
