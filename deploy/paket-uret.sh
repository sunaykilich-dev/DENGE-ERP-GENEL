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
#
# Nerede çalışır: macOS ya da Linux (bash, git, docker compose, node/npm,
# python3). Windows'ta PowerShell'den ÇALIŞMAZ; Git Bash + Docker Desktop
# ile ya da WSL içinde çalıştırın (KURULUM.md EK G.8).
set -euo pipefail

PROJE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CIKTI=${1:-$HOME/Downloads/denge-canli}
HAZIRLIK=$(mktemp -d)
trap 'rm -rf "$HAZIRLIK"' EXIT

# Teknik servis modüllerinin bu pakette hangi dalgaya kadar geldiği. SURUM.txt
# "sunucuda hangi servis sürümü kurulu" sorusunu da cevaplasın (TS-220).
SERVIS_SURUMU=${SERVIS_SURUMU:-"Dalga 0-4 (TS-001…TS-220; R4)"}

# `--no-mac-metadata` yalnız bsdtar'da (macOS) var; GNU tar (Linux, Git Bash)
# bilinmeyen seçenekte durur. macOS yan dosyaları zaten aşağıda siliniyor.
TAR_EK=()
if tar --help 2>&1 | grep -q -- '--no-mac-metadata'; then
  TAR_EK=(--no-mac-metadata --no-xattrs)
fi

for k in git docker npm python3; do
  command -v "$k" >/dev/null || { echo "HATA: '$k' yok (KURULUM.md EK G.8)"; exit 1; }
done

cd "$PROJE"

# Hedef head koddan, migration dosyalarından okunur (veritabanından değil):
# paket hangi şemaya yükseltecekse onu söyler. Tek head değilse paket çıkmaz.
HEDEF_HEAD=$(python3 - <<'PY'
import pathlib, re, sys
rev, onceki = set(), set()
for f in pathlib.Path("backend/alembic/versions").glob("*.py"):
    if f.name.startswith("._"):
        continue
    m = f.read_text(encoding="utf-8")
    r = re.search(r'^revision(?:: str)?\s*=\s*["\']([^"\']+)', m, re.M)
    d = re.search(r'^down_revision[^=]*=\s*(.+)$', m, re.M)
    if r:
        rev.add(r.group(1))
    if d:
        onceki.update(re.findall(r'["\']([^"\']+)["\']', d.group(1)))
head = sorted(rev - onceki)
if len(head) != 1:
    sys.exit(f"HATA: migration head sayisi {len(head)}: {head}")
print(head[0])
PY
)

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
# Teknik servis ekranları da derlenmiş arayüzde olmalı (Dalga 2-3 ekranı).
grep -rq "Operasyon Merkezi" backend/app/static/assets/*.js || {
  echo "HATA: derlenmis arayuzde 'Operasyon Merkezi' yok — teknik servis ekranlari eksik"; exit 1; }

echo "2/5 Kaynak arşivi…"
mkdir -p "$HAZIRLIK/denge-erp"
# Surum damgasi: iki paket disaridan ayni goruniyordu ve "sunucuda hangi
# surum kurulu" sorusu cevapsizdi.
{
  echo "Denge Mobilite ERP"
  echo "paket tarihi : $(date '+%Y-%m-%d %H:%M')"
  echo "commit       : $(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"
  echo "commit tarihi: $(git log -1 --date=short --pretty=%ad)"
  echo "goc surumu   : $(docker compose exec -T db psql -U dengeerp -d dengeerp -tA -c 'select version_num from alembic_version' | tr -d '\r')"
  echo "hedef head   : $HEDEF_HEAD"
  echo "teknik servis: $SERVIS_SURUMU"
} > "$HAZIRLIK/SURUM.txt"
# "goc surumu" dökümün şeması, "hedef head" kurulumdan sonra olması gereken.
# Farklıysa kur.sh/api açılışı aradaki migration'ları ileri uygular.
git ls-files -z | tar --null -T - ${TAR_EK[@]+"${TAR_EK[@]}"} -cf - | tar -xf - -C "$HAZIRLIK/denge-erp"
mkdir -p "$HAZIRLIK/denge-erp/backend/app/static"
cp -a backend/app/static/. "$HAZIRLIK/denge-erp/backend/app/static/"
find "$HAZIRLIK/denge-erp" -name ".env" -delete
mkdir -p "$CIKTI"
cp "$HAZIRLIK/SURUM.txt" "$HAZIRLIK/denge-erp/SURUM.txt"
find "$HAZIRLIK/denge-erp" \( -name '._*' -o -name '.DS_Store' \) -delete
tar ${TAR_EK[@]+"${TAR_EK[@]}"} -czf "$CIKTI/denge-erp-kaynak.tar.gz" -C "$HAZIRLIK" denge-erp
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
# yedekle.sh ve geri-yukle.sh da pakette: yükseltmeden ÖNCE yedek ve geri
# dönüş (önce geri-yukle.sh, sonra önceki paket) paketten yapılabilsin;
# cikis-provasi.sh canlı döküm kopyasında zaman damgalı tutanak üretir.
PAKET_BETIKLERI=(kur.sh on-kontrol.sh dogrula.sh yedekle.sh geri-yukle.sh cikis-provasi.sh)
for b in "${PAKET_BETIKLERI[@]}"; do
  cp "deploy/$b" "$CIKTI/"
  chmod +x "$CIKTI/$b"
done
cp deploy/servis_duman.py deploy/CIKIS-PROVASI-TUTANAGI.md "$CIKTI/"
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
tar -tzf "$CIKTI/denge-erp-kaynak.tar.gz" | grep -c "alembic/versions/.*\.py$" | xargs echo "migration adedi:"
echo "hedef head: $HEDEF_HEAD"

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
