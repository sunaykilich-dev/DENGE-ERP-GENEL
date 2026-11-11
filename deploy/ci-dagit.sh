#!/usr/bin/env bash
#
# GitLab CI dağıtımı — SUNUCUNUN ÜZERİNDEKİ runner'da koşar (deploy/GITLAB.md).
#
#   deploy/ci-dagit.sh <paket-dizini>
#
# Ortam değişkenleri (GitLab ortam/proje değişkenleri ya da runner ayarı):
#   DAGITIM_HEDEF   kurulum dizini (varsayılan /opt/denge-erp)
#   DAGITIM_ORTAMI  prova | canli (CI_ENVIRONMENT_NAME'den gelir)
#   PAKET_ARSIVI    önceki paketlerin saklandığı dizin (varsayılan ~/denge-paketler)
#   PAKET_SAKLA     kaç paket saklansın (varsayılan 5)
#
# Sıra KURULUM.md G.0 ile aynıdır: önce yedek → kur.sh (--veri yok) → doğrula.
# Yedek alınamazsa dağıtım BAŞLAMAZ. Geri dönüş otomatik değildir: canlıda
# `alembic downgrade` kullanılmaz; G.6 (önce geri-yukle.sh, sonra önceki
# paketle kur.sh). Önceki paket PAKET_ARSIVI'nde hazır durur.
#
# İlk kurulumu bu betik YAPMAZ: ilk kurulum dökümlü pakettir ve elle yapılır
# (KURULUM.md Adım 1–8). Bu betik yalnız var olan kurulumu yükseltir.
set -Eeuo pipefail

PAKET=${1:?kullanım: ci-dagit.sh <paket-dizini>}
PAKET=$(cd "$PAKET" && pwd)
HEDEF=${DAGITIM_HEDEF:-/opt/denge-erp}
ORTAM=${DAGITIM_ORTAMI:-${CI_ENVIRONMENT_NAME:-bilinmiyor}}
PAKET_ARSIVI=${PAKET_ARSIVI:-$HOME/denge-paketler}
PAKET_SAKLA=${PAKET_SAKLA:-5}

basla() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
tamam() { printf '   \033[32m✓\033[0m %s\n' "$1"; }
dur()   { printf '\n   \033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

basla "Dağıtım: $ORTAM → $HEDEF"
[ -f "$PAKET/SURUM.txt" ] || dur "pakette SURUM.txt yok — paket işi tamamlanmamış"
[ -f "$PAKET/kur.sh" ] || dur "pakette kur.sh yok"
[ ! -f "$PAKET/denge-veritabani.sql.gz" ] \
  || dur "pakette veritabanı dökümü var — CI paketi döküm TAŞIMAMALI (KVKK)"
sed 's/^/   | /' "$PAKET/SURUM.txt"
HEDEF_HEAD=$(grep '^hedef head' "$PAKET/SURUM.txt" | cut -d: -f2- | tr -d ' \r')
[ -n "$HEDEF_HEAD" ] || dur "SURUM.txt'te hedef head yok"

[ -f "$HEDEF/.env" ] \
  || dur "$HEDEF/.env yok — ilk kurulum CI ile yapılmaz, KURULUM.md Adım 1–8'i elle uygulayın"
command -v flock >/dev/null || dur "flock yok: sudo apt install -y util-linux"

# Aynı sunucuya iki dağıtım aynı anda koşmasın (GitLab resource_group'una ek
# olarak; elle çalıştırılan kur.sh ile çakışmayı da önler).
exec 9>"${TMPDIR:-/tmp}/denge-erp-dagitim.kilit"
flock -n 9 || dur "başka bir dağıtım sürüyor"

basla "Önceki sürüm"
if [ -f "$HEDEF/SURUM.txt" ]; then
  sed 's/^/   | /' "$HEDEF/SURUM.txt"
else
  echo "   (SURUM.txt yok)"
fi

basla "Yedek (yükseltmeden önce, şart)"
# yedekle.sh root ister (GPG parolası /root altında). gitlab-runner kullanıcısına
# YALNIZ bu betik için parolasız sudo verilir (deploy/GITLAB.md, sudoers satırı).
sudo -n "$HEDEF/deploy/yedekle.sh" \
  || dur "yedek alınamadı — dağıtım başlamadı. sudoers satırını ve yedekle.sh log'unu kontrol edin."
tamam "yedek alındı (geri dönüş: KURULUM.md G.6)"

basla "Paket saklanıyor (geri dönüş için)"
DAMGA=$(date +%Y%m%d-%H%M%S)
mkdir -p "$PAKET_ARSIVI"
cp -a "$PAKET" "$PAKET_ARSIVI/$DAMGA"
# Yalnız son PAKET_SAKLA paket kalır.
ls -1d "$PAKET_ARSIVI"/*/ 2>/dev/null | sort | head -n -"$PAKET_SAKLA" | xargs -r rm -rf
tamam "$PAKET_ARSIVI/$DAMGA"

basla "kur.sh --veri yok"
(cd "$PAKET" && chmod +x ./*.sh && ./kur.sh --veri yok --hedef "$HEDEF")

basla "Sonuç denetimi"
cd "$HEDEF"
curl -fsS http://127.0.0.1:8000/api/health >/dev/null || dur "/api/health yanıt vermiyor"
tamam "/api/health yanıt veriyor"
DB_SURUM=$(docker compose exec -T db psql -U dengeerp -d dengeerp -tAc \
  'select version_num from alembic_version' | tr -d ' \r')
[ "$DB_SURUM" = "$HEDEF_HEAD" ] \
  || dur "göç sürümü $DB_SURUM, beklenen $HEDEF_HEAD — docker compose logs api"
tamam "göç sürümü $DB_SURUM = paketin hedef head'i"

# dogrula.sh bilgi amaçlı: konteynerler yeni açıldığı için "worker görevi son
# 25 saatte bitti" maddesi ilk gün ✗ verebilir; dağıtımı bu yüzden düşürmeyiz.
basla "dogrula.sh (bilgi)"
"$HEDEF/deploy/dogrula.sh" || echo "   ! dogrula.sh uyarı verdi — yukarıdaki ✗ satırlarını inceleyin"

printf '\n\033[32mDAĞITIM TAMAM\033[0m — %s\n' "$ORTAM"
