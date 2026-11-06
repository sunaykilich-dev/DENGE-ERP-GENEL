#!/usr/bin/env bash
#
# Denge Mobilite ERP — uygulama kurulumu. Paket dizininden çalıştırılır:
#
#   ./kur.sh                                 # /opt/denge-erp, döküm yüklenir
#   ./kur.sh --hedef /srv/erp                # başka dizin
#   ./kur.sh --alan erp.ornek.com            # PUBLIC_BASE_URL
#   ./kur.sh --veri yok                      # boş veritabanıyla kur
#
# TEKRAR ÇALIŞTIRILABİLİR. Var olan `.env`'in ÜZERİNE YAZMAZ, veri varsa
# dökümü YÜKLEMEZ. Yarıda kalırsa aynı komutla kaldığı yerden sürer.
#
# Neden betik: bu kurulum elle yapılırken üç ayrı yerde durdu — (1) veritabanı
# birimi eski parolayla kurulmuştu, (2) hedefte kalan macOS yan dosyaları
# alembic'i düşürdü, (3) "göz karası" doğrulama komutları yanlış negatif verdi
# (`*.py` kalıbı baştaki noktayı eşlemez, `grep -P '\x00'` NUL bildirmez).
# Üçü de burada mekanik olarak kapatıldı.
set -Eeuo pipefail

PAKET=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HEDEF=/opt/denge-erp
ALAN=""
VERI=var
GECICI=""

trap 'KOD=$?; echo; echo "KURULUM DURDU — kur.sh satır $LINENO (çıkış kodu $KOD)."; echo "Yukarıdaki son hata mesajı sebebi söyler; KURULUM.md EK A.";
      echo "Düzelttikten sonra AYNI komutu tekrar çalıştırın; betik kaldığı yerden sürer.";
      [ -n "$GECICI" ] && rm -rf "$GECICI"; exit "$KOD"' ERR
trap '[ -n "$GECICI" ] && rm -rf "$GECICI"' EXIT

while [ $# -gt 0 ]; do
  case "$1" in
    --hedef) HEDEF=$2; shift 2 ;;
    --alan)  ALAN=$2;  shift 2 ;;
    --veri)  VERI=$2;  shift 2 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Bilinmeyen seçenek: $1" >&2; exit 2 ;;
  esac
done

basla() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
tamam() { printf '   \033[32m✓\033[0m %s\n' "$1"; }
bilgi() { printf '   · %s\n' "$1"; }
dur()   { printf '\n   \033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

dc() { (cd "$HEDEF" && docker compose "$@"); }

# ---------------------------------------------------------------- 1
basla "1/9  Ortam kontrolü"
command -v docker >/dev/null || dur "docker yok. KURULUM.md Adım 1'i uygulayın."
docker compose version >/dev/null 2>&1 || dur "docker compose v2 yok. KURULUM.md Adım 1."
docker info >/dev/null 2>&1 || dur "docker çalışmıyor ya da kullanıcınız docker grubunda değil (çıkış-giriş gerekir)."
command -v rsync >/dev/null || dur "rsync yok: sudo apt install -y rsync"
command -v python3 >/dev/null || dur "python3 yok: sudo apt install -y python3"
tamam "docker, docker compose, rsync, python3 hazır"

# sudo yalnizca hedef dizin yoksa VE ust dizine yazamiyorsak gerekir.
# Parolayi BASTA sorar; kurulumun ortasinda sormasi akisi bozuyordu.
SUDO=
if [ ! -d "$HEDEF" ] && [ ! -w "$(dirname "$HEDEF")" ]; then
  bilgi "$HEDEF oluşturulacak; $(dirname "$HEDEF") için yönetici yetkisi gerekiyor."
  sudo -v || dur "sudo parolası alınamadı. Dizini önceden açıp sahibini verin: sudo mkdir -p $HEDEF && sudo chown $(id -un) $HEDEF"
  SUDO=sudo
  tamam "yönetici yetkisi alındı"
fi

for d in denge-erp-kaynak.tar.gz denge-veritabani.sql.gz on-kontrol.sh; do
  [ -f "$PAKET/$d" ] || dur "pakette $d yok — arşivi eksik açmış olabilirsiniz."
done
gzip -t "$PAKET/denge-erp-kaynak.tar.gz" || dur "denge-erp-kaynak.tar.gz bozuk gelmiş, yeniden yükleyin."
gzip -t "$PAKET/denge-veritabani.sql.gz" || dur "denge-veritabani.sql.gz bozuk gelmiş, yeniden yükleyin."
tamam "paket dosyaları sağlam (gzip doğrulandı)"
[ -f "$PAKET/SURUM.txt" ] && sed 's/^/   | /' "$PAKET/SURUM.txt"

# ---------------------------------------------------------------- 2
basla "2/9  Kod yerleştiriliyor → $HEDEF"
if [ ! -d "$HEDEF" ]; then
  if mkdir -p "$HEDEF" 2>/dev/null; then
    bilgi "$HEDEF oluşturuldu"
  else
    ${SUDO:-sudo} mkdir -p "$HEDEF"
    ${SUDO:-sudo} chown "$(id -un)":"$(id -gn)" "$HEDEF"
    bilgi "$HEDEF oluşturuldu (yönetici yetkisiyle)"
  fi
fi
[ -w "$HEDEF" ] || dur "$HEDEF yazılabilir değil: sudo chown $(id -un) $HEDEF"

GECICI=$(mktemp -d)
tar -xzf "$PAKET/denge-erp-kaynak.tar.gz" -C "$GECICI" 2>/dev/null
# macOS yan dosyaları: adları *.py ile bittiği için alembic onları migration
# sanıp içe aktarır ve ilk baytta (NUL) düşer. Kaynakta da hedefte de yok et.
find "$GECICI" -name '._*' -delete 2>/dev/null || true
find "$GECICI" -name '.DS_Store' -delete 2>/dev/null || true
# --delete ŞART: cp ve tar -x hedefte FAZLADAN duran dosyaları silmez, bir kez
# düşen bozuk dosya her kurulumda orada kalır.
# .claude/ haric: sunucuda Claude Code oturumu acilirsa ayarlari burada durur
# ve surum yukseltmesinde --delete tarafindan silinmemeli.
rsync -a --delete --exclude '.env' --exclude 'var/' --exclude '.claude/' \
      "$GECICI/denge-erp/" "$HEDEF/"
rm -rf "$GECICI"; GECICI=""
find "$HEDEF" -name '._*' -delete 2>/dev/null || true
find "$HEDEF" -name '.DS_Store' -delete 2>/dev/null || true
# Betikler kaynak arsivinde de var; paketteki surum daha yeni olabilir diye
# uzerine yazariz (eski bir arsivle yeni bir paket karistirilirsa diye).
for b in kur.sh on-kontrol.sh dogrula.sh; do
  [ -f "$PAKET/$b" ] && cp "$PAKET/$b" "$HEDEF/deploy/$b"
done
chmod +x "$HEDEF/deploy/"*.sh 2>/dev/null || true
tamam "kod yerleşti (fazlalıklar silindi)"

# ---------------------------------------------------------------- 3
basla "3/9  .env"
if [ -f "$HEDEF/.env" ]; then
  tamam ".env zaten var — DOKUNULMADI (sırlarınız korunuyor)"
else
  PAROLA=$(openssl rand -hex 24)
  URL=${ALAN:+https://$ALAN}
  cat > "$HEDEF/.env" <<EOF
ENV=prod
POSTGRES_PASSWORD=$PAROLA
DATABASE_URL=postgresql+psycopg://dengeerp:$PAROLA@db:5432/dengeerp
SECRET_KEY=$(openssl rand -hex 32)
SETTINGS_ENC_KEY=$(openssl rand -hex 32)
WEBHOOK_PATH_TOKEN=$(openssl rand -hex 16)
PUBLIC_BASE_URL=${URL:-https://erp.dengemobil.com.tr}
FILES_DIR=./var/files
MFA_ZORUNLU=true
EOF
  chmod 600 "$HEDEF/.env"
  tamam ".env üretildi (parolalar openssl ile, aynı parola iki satıra da yazıldı)"
  [ -z "$ALAN" ] && bilgi "PUBLIC_BASE_URL varsayılan kaldı; alan adınız farklıysa .env'i düzeltin"
fi

# ---------------------------------------------------------------- 4
basla "4/9  Ön kontrol"
"$HEDEF/deploy/on-kontrol.sh" || dur "ön kontrol başarısız — yukarıdaki HATA satırlarını giderip tekrar çalıştırın."

# ---------------------------------------------------------------- 5
basla "5/9  Veritabanı ayağa kaldırılıyor"
dc up -d db
# DIKKAT: `pg_isready` tek basina YETMEZ. Postgres imaji ilk kurulumda initdb
# icin GECICI bir sunucu baslatir, isini bitirince kapatir ve gercek sunucuyu
# acar. pg_isready o geciciye "hazir" der, hemen ardindan soket kaybolur ve
# sonraki komut "No such file or directory" ile duser. Bu yuzden gercek bir
# sorgunun UST USTE UC KEZ calismasini bekliyoruz.
BASARI=0
for i in $(seq 1 120); do
  if dc exec -T db psql -U dengeerp -d dengeerp -tAc 'select 1' >/dev/null 2>&1; then
    BASARI=$((BASARI + 1))
    [ "$BASARI" -ge 3 ] && break
  else
    BASARI=0
  fi
  if [ "$i" = 120 ]; then
    dc logs db --tail 30
    dur "veritabanı 120 saniyede kalıcı olarak hazır olmadı."
  fi
  sleep 1
done
tamam "postgres hazır (sorgu üst üste 3 kez çalıştı)"

# ---------------------------------------------------------------- 6
basla "6/9  Veritabanı parolası .env ile eşitleniyor"
# POSTGRES_PASSWORD YALNIZ veri dizini ilk oluşurken geçerlidir. Birim daha
# önce başka bir parolayla kurulmuşsa api "password authentication failed" ile
# döngüye girer. Yerel soket `trust` olduğu için parolayı bilmeden düzeltiriz.
# Her kurulumda koşar; zaten doğruysa etkisizdir.
PAROLA=$(grep '^POSTGRES_PASSWORD=' "$HEDEF/.env" | cut -d= -f2- | tr -d '\r\n')
[ -n "$PAROLA" ] || dur ".env içinde POSTGRES_PASSWORD boş."
dc exec -T db psql -U dengeerp -d postgres -v ON_ERROR_STOP=1 \
   -c "ALTER USER dengeerp WITH PASSWORD '$PAROLA';" >/dev/null
# Uygulamanın yaptığı gibi TCP + scram ile dene; `trust` olan soketi kullanmaz.
dc exec -T -e PGPASSWORD="$PAROLA" db \
   psql -h 127.0.0.1 -U dengeerp -d dengeerp -tAc 'select 1' >/dev/null \
   || dur "parola eşitlendi ama TCP bağlantısı hâlâ başarısız — EK A'ya bakın."
tamam "rol parolası .env ile aynı, TCP bağlantısı doğrulandı"

# ---------------------------------------------------------------- 7
basla "7/9  Veri"
VAR_MI=$(dc exec -T db psql -U dengeerp -d dengeerp -tAc \
  "select to_regclass('public.accounts') is not null" 2>/dev/null | tr -d ' \r')
if [ "$VERI" = "yok" ]; then
  bilgi "--veri yok verildi: döküm yüklenmeyecek, şema migration'lardan kurulacak"
elif [ "$VAR_MI" = "t" ]; then
  ADET=$(dc exec -T db psql -U dengeerp -d dengeerp -tAc 'select count(*) from accounts' | tr -d ' \r')
  tamam "veritabanında zaten veri var ($ADET hesap) — döküm YÜKLENMEDİ, üzerine yazılmadı"
else
  bilgi "veritabanı boş, döküm yükleniyor…"
  gunzip -c "$PAKET/denge-veritabani.sql.gz" \
    | dc exec -T db psql -U dengeerp -d dengeerp -v ON_ERROR_STOP=1 --quiet >/dev/null
  tamam "döküm yüklendi"
  if [ -f "$PAKET/denge-dosyalar.tar.gz" ]; then
    gunzip -c "$PAKET/denge-dosyalar.tar.gz" \
      | dc run --rm -T --no-deps --entrypoint sh api -c 'mkdir -p /app/var/files && cd /app/var/files && tar -x' >/dev/null
    tamam "yüklenen belgeler yerine kondu"
  fi
fi

# ---------------------------------------------------------------- 8
basla "8/9  Uygulama başlatılıyor"
dc up -d --force-recreate api worker
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then break; fi
  if [ "$i" = 90 ]; then
    echo; echo "--- api log (son 40 satır) ---"; dc logs api --tail 40
    dur "api 90 saniyede yanıt vermedi. Yukarıdaki log sebebi söyler; KURULUM.md EK A."
  fi
  sleep 1
done
tamam "api yanıt veriyor (/api/health)"
dc ps --format '   | {{.Service}}  {{.Status}}'

# ---------------------------------------------------------------- 9
basla "9/9  Doğrulama"
dc exec -T db psql -U dengeerp -d dengeerp -P pager=off -c \
  "SELECT 'hesap' ne, count(*)::text sayi FROM accounts
   UNION ALL SELECT 'cihaz', count(*)::text FROM devices
   UNION ALL SELECT 'arac', count(*)::text FROM vehicles
   UNION ALL SELECT 'hat', count(*)::text FROM sim_cards
   UNION ALL SELECT 'is_emri', count(*)::text FROM work_orders
   UNION ALL SELECT 'hakedis_dokumu', count(*)::text FROM partner_settlements
   UNION ALL SELECT 'hakedis_toplam', to_char(coalesce(sum(gross_amount),0),'FM999G999G990D00') FROM partner_settlements
   UNION ALL SELECT 'cakisan_acik_donem', count(*)::text FROM (
     SELECT device_id FROM device_vehicle_assignments WHERE valid_to IS NULL
     GROUP BY device_id HAVING count(*)>1) x;" 2>/dev/null | sed 's/^/   /' || true

KOD=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/)
[ "$KOD" = 200 ] || dur "arayüz / isteğine $KOD döndü (200 beklenir)."
tamam "arayüz 200 döndü"

printf '\n\033[32mKURULUM BAŞARILI\033[0m\n'
cat <<SON

Sıradaki adımlar (KURULUM.md):
  · Adım 4  Geliştirme kimliklerini temizle  <-- ATLANAMAZ
  · Adım 5  Alan adı ve HTTPS (Caddy)
  · Adım 6  İlk giriş ve MFA
  · Adım 7  Otomatik başlatma + fail2ban
  · Adım 8  Yedekleme

Uygulama şu an yalnız sunucu içinden erişilebilir:  http://127.0.0.1:8000
Durumu her zaman şununla görebilirsiniz:            $HEDEF/deploy/dogrula.sh
SON
