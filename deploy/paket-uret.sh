#!/usr/bin/env bash
# Canlıya çıkış paketini üretir.
#
#   deploy/paket-uret.sh [çıktı-dizini]
#
# Neden betik: paket elle üretilirken bir adım atlanınca SESSİZCE eski sürüm
# çıkıyor. Bir kez gerçekten oldu — `npm run build` çıktıyı `frontend/dist`e
# yazıyor, `backend/app/static`e kopyalamak AYRI bir adım ve atlandığında
# paket beş günlük bir arayüz taşıdı. Betik o kopyayı yapar ve derlenmiş
# arayüzde yeni bir ekranın gerçekten bulunduğunu DOĞRULAR.
#
# Kaynak arşivine .env ASLA girmez — sırlar sunucuda üretilir (KURULUM.md
# Adım 4). Arayüz derlenmiş halde gider; sunucuda node kurulu olması
# gerekmesin diye.
set -euo pipefail

PROJE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CIKTI=${1:-$HOME/Downloads/denge-canli}
HAZIRLIK=$(mktemp -d)
trap 'rm -rf "$HAZIRLIK"' EXIT

cd "$PROJE"

echo "1/5 Arayüz derleniyor…"
# `npm run build` ciktiyi frontend/dist'e yazar; backend/app/static'e KOPYALAMAK
# ayri bir adim (Makefile'daki `build` hedefi de boyle yapiyor). Bu kopya
# atlandiginda paket SESSIZCE eski arayuzu tasiyordu.
(cd frontend && npm run build >/dev/null)
test -f frontend/dist/index.html || { echo "HATA: frontend/dist/index.html yok"; exit 1; }
rm -rf backend/app/static && cp -r frontend/dist backend/app/static
test -f backend/app/static/index.html || { echo "HATA: static/index.html yok"; exit 1; }
# Paketin tasidigi arayuz gercekten YENI mi: kaynakta olup pakette olmayan bir
# ekran, sessizce eski surum demek.
grep -rq "Görevler" backend/app/static/assets/*.js || {
  echo "HATA: derlenmis arayuzde 'Görevler' yok — eski build paketlenmis"; exit 1; }

echo "2/5 Kaynak arşivi…"
mkdir -p "$HAZIRLIK/denge-erp"
# Surum damgasi: iki paket disaridan ayni goruniyordu ve "sunucuda hangi
# surum kurulu" sorusu cevapsizdi.
{
  echo "Denge Mobilite ERP"
  echo "paket tarihi : $(date '+%Y-%m-%d %H:%M')"
  echo "commit       : $(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"
  echo "commit tarihi: $(git log -1 --date=short --pretty=%ad)"
  echo "goc surumu   : $(docker compose exec -T db psql -U dengeerp -d dengeerp -tA -c 'select version_num from alembic_version')"
} > "$HAZIRLIK/SURUM.txt"
git ls-files -z | tar --null -T - --no-mac-metadata --no-xattrs -cf - | tar -xf - -C "$HAZIRLIK/denge-erp"
mkdir -p "$HAZIRLIK/denge-erp/backend/app/static"
cp -a backend/app/static/. "$HAZIRLIK/denge-erp/backend/app/static/"
find "$HAZIRLIK/denge-erp" -name ".env" -delete
mkdir -p "$CIKTI"
cp "$HAZIRLIK/SURUM.txt" "$HAZIRLIK/denge-erp/SURUM.txt"
tar --no-mac-metadata --no-xattrs -czf "$CIKTI/denge-erp-kaynak.tar.gz" -C "$HAZIRLIK" denge-erp
cp "$HAZIRLIK/SURUM.txt" "$CIKTI/SURUM.txt"

echo "3/5 Veritabanı dökümü…"
docker compose exec -T db pg_dump -U dengeerp -d dengeerp --clean --if-exists \
  | gzip -9 > "$CIKTI/denge-veritabani.sql.gz"

echo "4/5 Yüklenen belgeler…"
docker compose exec -T api tar -C /app/var/files -c . | gzip -9 > "$CIKTI/denge-dosyalar.tar.gz"

echo "5/5 Belgeler…"
cp deploy/KURULUM.md deploy/Caddyfile deploy/db-least-privilege.sql \
   deploy/denge-erp.service "$CIKTI/"
# Kurulum artik elle komut dizisi degil: kur.sh her seyi yapar, on-kontrol.sh
# her adimda mekanik dogrular, dogrula.sh kurulumdan sonra durum verir.
cp deploy/kur.sh deploy/on-kontrol.sh deploy/dogrula.sh "$CIKTI/"
chmod +x "$CIKTI/kur.sh" "$CIKTI/on-kontrol.sh" "$CIKTI/dogrula.sh"
cp -a deploy/fail2ban "$CIKTI/"
[ -f .env.example ] && cp .env.example "$CIKTI/"

echo
echo "--- paket ---"
ls -lh "$CIKTI"
echo
echo "--- kaynak arşivinde .env var mı (boş olmalı) ---"
tar -tzf "$CIKTI/denge-erp-kaynak.tar.gz" | grep -E "(^|/)\.env$" || echo "yok — iyi"
echo
tar -tzf "$CIKTI/denge-erp-kaynak.tar.gz" | grep -c "backend/app/static/" | xargs echo "static dosya adedi:"
tar -tzf "$CIKTI/denge-erp-kaynak.tar.gz" | grep -c "alembic/versions/" | xargs echo "migration adedi:"

# Arsivin KENDISINE on kontrolu kosar. Elle yazilan dogrulama komutlari bu
# projede iki kez yanlis negatif verdi: `*.py` kabuk kalibi bastaki noktayi
# eslemez (._dosya.py gorunmez) ve `grep -P '\x00'` NUL bayti bildirmez.
# on-kontrol.sh ikisini de Python ile kesin olcer.
DENETIM=$(mktemp -d)
trap 'rm -rf "$HAZIRLIK" "$DENETIM"' EXIT
tar -xzf "$CIKTI/denge-erp-kaynak.tar.gz" -C "$DENETIM"
cp deploy/on-kontrol.sh "$DENETIM/denge-erp/deploy/on-kontrol.sh"
chmod +x "$DENETIM/denge-erp/deploy/on-kontrol.sh"
# .env arsivde yoktur (olmamali); on kontrolun .env bolumu bu yuzden atlanir.
touch "$DENETIM/denge-erp/.env"
printf 'POSTGRES_PASSWORD=x\nDATABASE_URL=postgresql+psycopg://dengeerp:x@db:5432/dengeerp\nSECRET_KEY=x\nSETTINGS_ENC_KEY=x\n' > "$DENETIM/denge-erp/.env"
echo
echo "--- arsive on kontrol ---"
"$DENETIM/denge-erp/deploy/on-kontrol.sh" || {
  echo "HATA: arsiv on kontrolden gecmedi, paket GONDERILEMEZ." >&2; exit 1; }

echo
echo "--- SURUM.txt ---"
cat "$CIKTI/SURUM.txt"
