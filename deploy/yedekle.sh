#!/usr/bin/env bash
# Denge ERP yedeği — veritabanı + yüklenen dosyalar, şifreli ve tarihli.
#
# Cron (root):  0 3 * * * /opt/denge-erp/deploy/yedekle.sh >> /var/log/denge-yedek.log 2>&1
#
# GERI YUKLEME PROVASI deploy/geri-yukle.sh ile yapılır ve AYDA BIR
# çalıştırılmalıdır. Denenmemiş yedek, yedek değildir.
set -euo pipefail

# YEDEK_DIZIN TEK DEĞİŞKENDİR (TS-219): bu betik yazar, dogrula.sh okur.
# Önceden dogrula.sh başka bir dizine bakıyordu ve
# yedek alınmış olsa da "yedek bulunamadı" diyordu. Varsayılanı değiştirmek
# isterseniz İKİ betikte de geçerli olsun diye /etc/default/denge-erp'e
# `YEDEK_DIZIN=/baska/dizin` yazın; ikisi de bu dosyayı okur.
# shellcheck disable=SC1091
[ -r /etc/default/denge-erp ] && . /etc/default/denge-erp

REPO_DIR=${REPO_DIR:-/opt/denge-erp}
YEDEK_DIZIN=${YEDEK_DIZIN:-/var/backups/denge-erp}
SAKLAMA_GUN=${SAKLAMA_GUN:-30}
GPG_PAROLA_DOSYASI=${GPG_PAROLA_DOSYASI:-/root/.denge_erp_yedek_parolasi}

cd "$REPO_DIR"
mkdir -p "$YEDEK_DIZIN"
DAMGA=$(date +%Y%m%d-%H%M%S)

# --- 1) Veritabanı ---
DB_DOSYA="$YEDEK_DIZIN/dengeerp-$DAMGA.sql.gz.gpg"
docker compose exec -T db pg_dump -U dengeerp --clean --if-exists dengeerp \
  | gzip \
  | gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase-file "$GPG_PAROLA_DOSYASI" \
        -o "$DB_DOSYA"
echo "Veritabani: $DB_DOSYA ($(du -h "$DB_DOSYA" | cut -f1))"

# --- 2) Dosyalar (ekler, üretilen PDF'ler, içe aktarma raporları) ---
# Bunlar veritabanında DEĞİL diskte; yalnız DB yedeği almak montaj
# fotoğraflarını ve gönderilmiş teklif PDF'lerini kaybetmek demekti.
DOSYA_YEDEK="$YEDEK_DIZIN/dosyalar-$DAMGA.tar.gz.gpg"
docker compose run --rm -T --entrypoint sh api -c 'tar -cz -C /app/var files' \
  | gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase-file "$GPG_PAROLA_DOSYASI" \
        -o "$DOSYA_YEDEK"
echo "Dosyalar  : $DOSYA_YEDEK ($(du -h "$DOSYA_YEDEK" | cut -f1))"

# --- 3) Eskileri temizle ---
find "$YEDEK_DIZIN" -name 'dengeerp-*.sql.gz.gpg' -mtime +"$SAKLAMA_GUN" -delete
find "$YEDEK_DIZIN" -name 'dosyalar-*.tar.gz.gpg' -mtime +"$SAKLAMA_GUN" -delete

# --- 4) Ofis dışına kopya ---
# ERP ile yedeğin aynı makinede olması yedek sayılmaz: disk arızası, fidye
# yazılımı ve yanlışlıkla `docker compose down -v` ikisini birden götürür.
if [ -n "${UZAK_HEDEF:-}" ]; then
  rsync -a --delete "$YEDEK_DIZIN/" "$UZAK_HEDEF/"
  echo "Uzak kopya: $UZAK_HEDEF"
else
  echo "UYARI: UZAK_HEDEF tanimli degil, yedek yalniz bu makinede."
fi
