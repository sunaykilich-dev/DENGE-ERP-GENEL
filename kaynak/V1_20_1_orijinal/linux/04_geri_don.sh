#!/usr/bin/env bash
set -Eeuo pipefail
if [[ $EUID -ne 0 ]]; then echo 'sudo bash linux/04_geri_don.sh'; exit 1; fi
FILE=/etc/dengeerp/previous_release
[[ -s "$FILE" ]] || { echo 'Geri donulecek onceki Linux surumu yok.'; exit 1; }
OLD=$(cat "$FILE")
[[ -s "$OLD/DengeERP.Api.dll" ]] || { echo "DLL yok: $OLD"; exit 1; }
NOW=$(readlink -f /opt/dengeerp/current)
ln -s "$OLD" /opt/dengeerp/.rollback
mv -Tf /opt/dengeerp/.rollback /opt/dengeerp/current
if ! systemctl restart dengeerp; then
  ln -s "$NOW" /opt/dengeerp/.failedback
  mv -Tf /opt/dengeerp/.failedback /opt/dengeerp/current
  systemctl restart dengeerp || true
  echo 'Geri donus basarisiz; eski servis geri alindi'; exit 1
fi
echo "Onceki Linux koduna donuldu: $OLD"
echo 'UYARI: Bu komut VERITABANI GERİ YUKLEMESİ YAPMAZ. DB geri donusu IT kontrolunde yedekten yapilir.'
