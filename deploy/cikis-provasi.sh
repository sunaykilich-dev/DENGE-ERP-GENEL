#!/usr/bin/env bash
#
# CANLIYA ÇIKIŞ PROVASI (TS-220, plan §5) — zaman damgalı tutanak üretir.
#
# NEREDE: canlıdaki paketin kurulu olduğu ve CANLI DÖKÜMÜN KOPYASININ yüklü
# olduğu AYRI bir prova sunucusunda. Canlı sunucuda ÇALIŞTIRILMAZ: servis
# duman testi bir servis işi numarası tüketir, geri dönüş provası
# veritabanını siler ve yeniden yükler.
#
#   1. Prova sunucusuna şu an canlıda olan paketi kur.sh ile kurun; kur.sh
#      boş veritabanına o paketin dökümünü (canlı döküm kopyası) yükler.
#      Yedek parolası: KURULUM.md Adım 8.
#   2. YENİ paketi ayrı bir klasöre açın ve oradan:
#        PROVA_ONAY=evet ./cikis-provasi.sh [--hedef /opt/denge-erp] \
#                                           [--geri-donus ~/denge-canli-onceki]
#
# Adımlar: parmak izi (önce) → yedek → kur.sh → dogrula.sh → altın kayıt
# (mobilite parmak izi önce = sonra) → servis duman testi → geri-yukle.sh
# provası → [--geri-donus: önce geri-yukle.sh ZORLA, sonra önceki paketle
# kur.sh, parmak izi yine aynı]. Her adımın başlangıç/bitiş saati ve sonucu
# tutanağa (CIKIS-PROVASI-<damga>.md), çıktının tamamı yanındaki .log
# dosyasına yazılır. Tutanak biçimi: CIKIS-PROVASI-TUTANAGI.md.
set -uo pipefail

PAKET=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HEDEF=/opt/denge-erp
ONCEKI_PAKET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --hedef) HEDEF=$2; shift 2 ;;
    --geri-donus) ONCEKI_PAKET=$(cd "$2" && pwd); shift 2 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Bilinmeyen seçenek: $1" >&2; exit 2 ;;
  esac
done

if [ "${PROVA_ONAY:-}" != "evet" ]; then
  echo "Bu betik yalnız PROVA sunucusunda çalışır. Emin iseniz: PROVA_ONAY=evet $0" >&2
  exit 2
fi
for b in kur.sh dogrula.sh yedekle.sh geri-yukle.sh servis_duman.py; do
  [ -f "$PAKET/$b" ] || [ -f "$PAKET/../deploy/$b" ] || { echo "pakette $b yok" >&2; exit 2; }
done
[ -z "$ONCEKI_PAKET" ] || [ -x "$ONCEKI_PAKET/kur.sh" ] || {
  echo "--geri-donus dizininde kur.sh yok: $ONCEKI_PAKET" >&2; exit 2; }

SUDO=""; [ "$(id -u)" = 0 ] || SUDO=sudo
# shellcheck disable=SC1091
[ -r /etc/default/denge-erp ] && . /etc/default/denge-erp
YEDEK_DIZIN=${YEDEK_DIZIN:-/var/backups/denge-erp}

DAMGA=$(date +%Y%m%d-%H%M%S)
TUTANAK=${TUTANAK:-$PWD/CIKIS-PROVASI-$DAMGA.md}
LOG=${TUTANAK%.md}.log
IZ_ONCE=$(mktemp); IZ_SONRA=$(mktemp)
trap 'rm -f "$IZ_ONCE" "$IZ_SONRA"' EXIT
GENEL=0

zaman() { date '+%Y-%m-%d %H:%M:%S'; }
dc() { (cd "$HEDEF" && docker compose "$@"); }
sql() { dc exec -T db psql -U dengeerp -d dengeerp -tA -c "$1" 2>>"$LOG" | tr -d '\r'; }
betik() { if [ -f "$PAKET/$1" ]; then echo "$PAKET/$1"; else echo "$PAKET/../deploy/$1"; fi; }

# Mobilite parmak izi: yükseltme bunlardan HİÇBİRİNİ değiştirmemeli (altın
# kayıt ilkesi: hak ediş toplamı kuruşu kuruşuna aynı kalır). Sayılar ve
# toplamlar; dönem bazında hak ediş dökümü.
parmak_izi() {
  sql "SELECT 'hesap '||count(*) FROM accounts
       UNION ALL SELECT 'cihaz '||count(*) FROM devices
       UNION ALL SELECT 'arac '||count(*) FROM vehicles
       UNION ALL SELECT 'hat '||count(*) FROM sim_cards
       UNION ALL SELECT 'is_emri '||count(*) FROM work_orders
       UNION ALL SELECT 'is_emri_kalemi '||count(*) FROM work_order_items
       UNION ALL SELECT 'cihaz_arac_donemi '||count(*) FROM device_vehicle_assignments
       UNION ALL SELECT 'hakedis_dokumu '||count(*) FROM partner_settlements
       UNION ALL SELECT 'hakedis_brut '||coalesce(sum(gross_amount),0) FROM partner_settlements
       UNION ALL SELECT 'hakedis_satiri '||count(*)||' '||coalesce(sum(amount),0) FROM settlement_lines
       UNION ALL (SELECT 'donem '||period||' '||count(*)||' '||sum(gross_amount)
                  FROM partner_settlements GROUP BY period ORDER BY period)"
}

{
  echo "# Canlıya çıkış provası tutanağı"
  echo
  echo "| Alan | Değer |"
  echo "|---|---|"
  echo "| Başlangıç | $(zaman) |"
  echo "| Sunucu | $(hostname) |"
  echo "| Hedef dizin | \`$HEDEF\` |"
  echo "| Yeni paket | \`$PAKET\` |"
  echo "| Önceki paket (geri dönüş) | \`${ONCEKI_PAKET:-provada geri dönüş yok}\` |"
  echo "| Yürüten | $(id -un) |"
  echo
  echo "Yeni paket SURUM.txt:"
  echo
  echo '```'
  cat "$PAKET/SURUM.txt" 2>/dev/null || echo "(SURUM.txt yok)"
  echo '```'
  echo
  echo "| # | Adım | Başlangıç | Bitiş | Sonuç | Not |"
  echo "|---|---|---|---|---|---|"
} > "$TUTANAK"
: > "$LOG"

# adim <no> <ad> <komut...>: komutu koşar, çıktıyı log'a, satırı tutanağa yazar.
NOT=""
adim() {
  local no=$1 ad=$2; shift 2
  local bas; bas=$(zaman)
  printf '\n\033[1m== %s. %s (%s)\033[0m\n' "$no" "$ad" "$bas"
  { echo; echo "===== $no. $ad — $bas"; } >> "$LOG"
  NOT=""
  # Boru (`| tee`) DEĞİL süreç ikamesi: adım fonksiyonu alt kabukta koşarsa
  # YEDEK ve NOT değişkenleri sonraki adımlara ulaşmaz.
  if "$@" > >(tee -a "$LOG") 2>&1; then
    SONUC="TAMAM"
  else
    SONUC="**HATA**"; GENEL=1
  fi
  sleep 0.2  # tee'nin son satırları ekrana düşsün
  echo "| $no | $ad | $bas | $(zaman) | $SONUC | ${NOT//|/\\|} |" >> "$TUTANAK"
  [ "$SONUC" = "TAMAM" ]
}

a_iz_once() {
  parmak_izi > "$IZ_ONCE"
  [ -s "$IZ_ONCE" ] || { echo "parmak izi alınamadı (veritabanı boş mu?)"; return 1; }
  cat "$IZ_ONCE"
  NOT="göç sürümü $(sql 'select version_num from alembic_version'), $(grep -c . "$IZ_ONCE") satır"
}

a_yedek() {
  $SUDO env YEDEK_DIZIN="$YEDEK_DIZIN" REPO_DIR="$HEDEF" "$(betik yedekle.sh)" || return 1
  YEDEK=$(ls -1t "$YEDEK_DIZIN"/dengeerp-*.sql.gz.gpg 2>/dev/null | head -1)
  [ -n "$YEDEK" ] || { echo "yedek dosyası bulunamadı ($YEDEK_DIZIN)"; return 1; }
  NOT="\`$(basename "$YEDEK")\` $(du -h "$YEDEK" | cut -f1)"
}

a_kur() {
  (cd "$PAKET" && ./kur.sh --hedef "$HEDEF") || return 1
  NOT="göç sürümü $(sql 'select version_num from alembic_version')"
}

a_dogrula() {
  # Yükseltmeden hemen sonra 24 saatlik görevlerin hepsi ilk turunu bitirmiş
  # olmayabilir; worker'a kısa bir süre tanınır.
  sleep "${DOGRULA_BEKLE:-90}"
  "$HEDEF/deploy/dogrula.sh"
}

a_altin_kayit() {
  parmak_izi > "$IZ_SONRA"
  if diff -u "$IZ_ONCE" "$IZ_SONRA"; then
    NOT="mobilite parmak izi önce = sonra; $(grep '^hakedis_brut' "$IZ_SONRA")"
  else
    NOT="mobilite parmak izi DEĞİŞTİ (log'da diff)"; return 1
  fi
}

a_servis_duman() {
  dc exec -T -e DENGE_PROVA=1 api python - < "$(betik servis_duman.py)"
}

a_geri_yukle_prova() {
  # Adım 2'deki (yükseltme ÖNCESİ) yedek geçici veritabanına yüklenir.
  $SUDO env REPO_DIR="$HEDEF" "$(betik geri-yukle.sh)" "$YEDEK" || return 1
  NOT="\`$(basename "$YEDEK")\` → dengeerp_prova, silindi"
}

a_geri_donus() {
  # Plan §5.2: ÖNCE yedek geri yüklenir, SONRA önceki paketle kur.sh.
  # alembic downgrade KULLANILMAZ.
  $SUDO env REPO_DIR="$HEDEF" HEDEF_DB=dengeerp ZORLA=1 "$(betik geri-yukle.sh)" "$YEDEK" || return 1
  (cd "$ONCEKI_PAKET" && ./kur.sh --hedef "$HEDEF") || return 1
  parmak_izi > "$IZ_SONRA"
  diff -u "$IZ_ONCE" "$IZ_SONRA" || { NOT="geri dönüşten sonra parmak izi farklı"; return 1; }
  NOT="önceki sürüm açıldı, göç sürümü $(sql 'select version_num from alembic_version'), parmak izi önce = sonra"
}

YEDEK=""
adim 1 "Parmak izi (yükseltme öncesi)" a_iz_once \
  && adim 2 "Yedek (yedekle.sh)" a_yedek \
  && adim 3 "Yükseltme (kur.sh)" a_kur
# 4-7 birbirinden bağımsız denetimlerdir; biri düşse de diğerleri koşar ki
# tutanak tam olsun. Yükseltme ya da yedek düştüyse anlamsızdır, atlanır.
if [ "$GENEL" = 0 ]; then
  adim 4 "Doğrulama (dogrula.sh)" a_dogrula
  adim 5 "Altın kayıt (mobilite parmak izi)" a_altin_kayit
  adim 6 "Servis duman testi" a_servis_duman
  adim 7 "Geri yükleme provası (geri-yukle.sh → dengeerp_prova)" a_geri_yukle_prova
  if [ -n "$ONCEKI_PAKET" ]; then
    adim 8 "Geri dönüş provası (geri-yukle.sh ZORLA + önceki paket kur.sh)" a_geri_donus
  fi
fi

{
  echo
  echo "Yükseltme öncesi parmak izi:"
  echo
  echo '```'
  cat "$IZ_ONCE"
  echo '```'
  echo
  echo "| Alan | Değer |"
  echo "|---|---|"
  echo "| Bitiş | $(zaman) |"
  if [ "$GENEL" = 0 ]; then
    echo "| Sonuç | **PROVA BAŞARILI** — canlıya çıkışa engel yok |"
  else
    echo "| Sonuç | **PROVA BAŞARISIZ** — HATA satırları giderilmeden canlıya çıkılmaz |"
  fi
  echo
  echo "Tam çıktı: \`$(basename "$LOG")\`. Tutanak KURULUM.md EK G.7'ye göre imzalanıp saklanır."
  echo
  echo "| Rol | Ad Soyad | İmza |"
  echo "|---|---|---|"
  echo "| Yürüten | | |"
  echo "| Onaylayan (servis müdürü) | | |"
  echo "| Onaylayan (BT / sistem) | | |"
} >> "$TUTANAK"

echo
echo "Tutanak: $TUTANAK"
echo "Log    : $LOG"
[ "$GENEL" = 0 ] && printf '\033[32mPROVA BAŞARILI\033[0m\n' || printf '\033[31mPROVA BAŞARISIZ\033[0m\n'
exit "$GENEL"
