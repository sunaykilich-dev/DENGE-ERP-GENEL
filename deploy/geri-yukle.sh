#!/usr/bin/env bash
# YEDEKTEN GERI YUKLEME PROVASI (plan §D13).
#
# Yedeği CANLI veritabanına değil, yanına açılan geçici bir veritabanına
# yükler ve doğrular. Böylece prova, provanın kendisi yüzünden veri
# kaybetme riski taşımaz. Ayda bir çalıştırın.
#
#   deploy/geri-yukle.sh /var/backups/denge-erp/dengeerp-20260922-030000.sql.gz.gpg
#
# Gerçek felaket kurtarmada aynı dump'ı canlıya yüklemek için:
#   HEDEF_DB=dengeerp ZORLA=1 deploy/geri-yukle.sh <dosya>
#
# DOSYALAR: yedek iki parçadır — veritabanı VE yüklenen dosyalar. Ekler
# (vergi levhası, montaj fotoğrafı, sözleşme) veritabanında DEĞİL diskte
# durur; `attachments` yalnız yolu tutar. Yalnız veritabanı geri yüklenirse
# uygulama açılır ama her ek 404 verir ve "dosyalar gitmiş" sanılır.
# Betik, dump'ın yanındaki `dosyalar-<damga>.tar.gz.gpg` arşivini kendisi
# bulur: provada yalnız DOĞRULAR, ZORLA=1 ile gerçek kurtarmada AÇAR.
set -euo pipefail

YEDEK=${1:?Kullanim: geri-yukle.sh <yedek.sql.gz.gpg>}
REPO_DIR=${REPO_DIR:-/opt/denge-erp}
HEDEF_DB=${HEDEF_DB:-dengeerp_prova}
GPG_PAROLA_DOSYASI=${GPG_PAROLA_DOSYASI:-/root/.denge_erp_yedek_parolasi}

cd "$REPO_DIR"

if [ "$HEDEF_DB" = "dengeerp" ] && [ "${ZORLA:-0}" != "1" ]; then
  echo "HATA: canli veritabanina yazmak icin ZORLA=1 gerekir." >&2
  exit 1
fi

psql() { docker compose exec -T db psql -U dengeerp -v ON_ERROR_STOP=1 "$@"; }

if [ "$HEDEF_DB" = "dengeerp" ]; then
  # Gercek kurtarma / geri donus (KURULUM.md EK G.6): veritabani SILINIP
  # yeniden yaratilir. Dump'i var olan veritabaninin USTUNE yuklemek yetmez:
  # `--clean` yalniz dump'ta bulunan nesneleri siler, yeni surumun
  # migration'larinin actigi tablolar (servis tablolari gibi) kalir ve bir
  # sonraki yukseltme "relation already exists" ile duser. Bagli api/worker
  # varken DROP DATABASE da reddedilir; once durdurulur.
  echo "0/5 api ve worker durduruluyor (canli veritabani yeniden yaratilacak)"
  docker compose stop api worker
fi

echo "1/5 Gecici veritabani hazirlaniyor: $HEDEF_DB"
psql -d postgres -c "DROP DATABASE IF EXISTS $HEDEF_DB WITH (FORCE);"
psql -d postgres -c "CREATE DATABASE $HEDEF_DB OWNER dengeerp;"

echo "2/5 Yedek cozuluyor ve yukleniyor"
gpg --batch --quiet --decrypt --passphrase-file "$GPG_PAROLA_DOSYASI" "$YEDEK" \
  | gunzip \
  | psql -d "$HEDEF_DB" >/dev/null

# Dump'in yanindaki dosya arsivini bul: dengeerp-<damga>.sql.gz.gpg ->
# dosyalar-<damga>.tar.gz.gpg
DOSYA_ARSIV=${DOSYA_ARSIV:-$(dirname "$YEDEK")/$(basename "$YEDEK" \
  | sed 's/^dengeerp-/dosyalar-/; s/\.sql\.gz\.gpg$/.tar.gz.gpg/')}

echo "3/5 Dogrulama"
# Yedeğin "yüklendi" demesi yetmez: tablolar dolu mu, para tutuyor mu?
psql -d "$HEDEF_DB" -P pager=off -c "
  SELECT 'hesap' AS ne, count(*) FROM accounts
  UNION ALL SELECT 'cihaz',    count(*) FROM devices
  UNION ALL SELECT 'is_emri',  count(*) FROM work_orders
  UNION ALL SELECT 'dokum',    count(*) FROM partner_settlements
  UNION ALL SELECT 'kullanici',count(*) FROM users;"
psql -d "$HEDEF_DB" -tAc "SELECT 'goc_surumu: '||version_num FROM alembic_version;"

echo "--- Hak edis genel toplami (canli uygulamayla karsilastirilacak sayi) ---"
psql -d "$HEDEF_DB" -P pager=off -c "
  SELECT period, count(*) AS dokum, sum(gross_amount) AS brut
  FROM partner_settlements GROUP BY period ORDER BY period;"

echo "--- Tarihli kisitlar saglam mi (cakisan acik donem olmamali) ---"
psql -d "$HEDEF_DB" -P pager=off -c "
  SELECT count(*) AS cakisan_acik_donem FROM (
    SELECT device_id FROM device_vehicle_assignments
    WHERE valid_to IS NULL GROUP BY device_id HAVING count(*) > 1) x;"

echo "4/5 Yuklenen dosyalar"
if [ ! -f "$DOSYA_ARSIV" ]; then
  echo "UYARI: dosya arsivi bulunamadi ($DOSYA_ARSIV)."
  echo "       Ekler geri gelmeyecek; yedekleme dosyalari da aliyor mu kontrol edin."
elif [ "$HEDEF_DB" = "dengeerp" ]; then
  echo "Arsiv aciliyor: $DOSYA_ARSIV"
  # api durduruldu (adim 0); dosya birimine tek seferlik konteynerle yazilir.
  gpg --batch --quiet --decrypt --passphrase-file "$GPG_PAROLA_DOSYASI" "$DOSYA_ARSIV" \
    | docker compose run --rm -T --no-deps --entrypoint sh api -c 'tar -xz -C /app/var'
  ADET=$(docker compose run --rm -T --no-deps --entrypoint sh api \
    -c 'find /app/var/files -type f | wc -l' | tr -d '\r ')
  echo "Dosya sayisi: $ADET"
else
  # Prova canli dosyalarin uzerine YAZMAZ; arsivin acilabildigini dogrular.
  ADET=$(gpg --batch --quiet --decrypt --passphrase-file "$GPG_PAROLA_DOSYASI" "$DOSYA_ARSIV" \
    | tar -tz | grep -c '^files/.*[^/]$' || true)
  echo "Arsiv okunabiliyor, icinde $ADET dosya var (provada ACILMADI)."
fi

echo "5/5 Temizlik"
if [ "$HEDEF_DB" != "dengeerp" ]; then
  psql -d postgres -c "DROP DATABASE $HEDEF_DB;"
  echo "Prova veritabani silindi. PROVA BASARILI."
else
  echo "Canli veritabanina yuklendi; api ve worker DURDURULMUS durumda."
  echo "  - Ayni surume kurtarma : docker compose up -d api worker"
  echo "  - Onceki surume donus  : onceki paketin klasorunden ./kur.sh (KURULUM.md EK G.6)"
  echo "    Yeni surumle api'yi ACMAYIN: acilista 'alembic upgrade head' yedegi yeniden yukseltir."
fi
