#!/usr/bin/env bash
# Kurulu sistemin durumu. Hiçbir şeyi değiştirmez; her zaman çalıştırılabilir.
#   /opt/denge-erp/deploy/dogrula.sh
set -uo pipefail
HEDEF=$(cd "$(dirname "$0")/.." && pwd)
cd "$HEDEF"
HATA=0
gec() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
kal() { printf '  \033[31m✗\033[0m %s\n' "$1"; HATA=1; }

printf '\033[1m== Denge ERP durum (%s) ==\033[0m\n' "$(date '+%Y-%m-%d %H:%M')"
[ -f SURUM.txt ] && sed 's/^/  | /' SURUM.txt && echo

echo "Konteynerler"
docker compose ps --format '  {{.Service}}  {{.Status}}'
for s in db api worker; do
  D=$(docker compose ps --status running --services 2>/dev/null | grep -cx "$s")
  [ "$D" = 1 ] && gec "$s çalışıyor" || kal "$s ÇALIŞMIYOR"
done

echo
echo "Uygulama"
KOD=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health 2>/dev/null)
[ "$KOD" = 200 ] && gec "/api/health 200" || kal "/api/health → ${KOD:-yanıt yok}"
KOD=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ 2>/dev/null)
[ "$KOD" = 200 ] && gec "arayüz 200" || kal "arayüz → ${KOD:-yanıt yok}"

echo
echo "Veritabanı"
if P=$(grep '^POSTGRES_PASSWORD=' .env 2>/dev/null | cut -d= -f2- | tr -d '\r\n') && [ -n "$P" ]; then
  if docker compose exec -T -e PGPASSWORD="$P" db \
       psql -h 127.0.0.1 -U dengeerp -d dengeerp -tAc 'select 1' >/dev/null 2>&1; then
    gec "TCP + parola bağlantısı (api'nin kullandığı yol)"
  else
    kal "TCP + parola bağlantısı BAŞARISIZ — EK A: password authentication failed"
  fi
else
  kal ".env okunamadı ya da POSTGRES_PASSWORD boş"
fi
docker compose exec -T db psql -U dengeerp -d dengeerp -P pager=off -c \
  "SELECT 'hesap' ne, count(*)::text sayi FROM accounts
   UNION ALL SELECT 'cihaz', count(*)::text FROM devices
   UNION ALL SELECT 'arac', count(*)::text FROM vehicles
   UNION ALL SELECT 'hat', count(*)::text FROM sim_cards
   UNION ALL SELECT 'is_emri', count(*)::text FROM work_orders
   UNION ALL SELECT 'hakedis_dokumu', count(*)::text FROM partner_settlements
   UNION ALL SELECT 'hakedis_toplam', to_char(coalesce(sum(gross_amount),0),'FM999G999G990D00') FROM partner_settlements
   UNION ALL SELECT 'goc_surumu', (select version_num from alembic_version)
   UNION ALL SELECT 'cakisan_acik_donem', count(*)::text FROM (
     SELECT device_id FROM device_vehicle_assignments WHERE valid_to IS NULL
     GROUP BY device_id HAVING count(*)>1) x;" 2>/dev/null | sed 's/^/  /' \
  || kal "veritabanı sorgusu başarısız"

CAKISMA=$(docker compose exec -T db psql -U dengeerp -d dengeerp -tAc \
  "SELECT count(*) FROM (SELECT device_id FROM device_vehicle_assignments
   WHERE valid_to IS NULL GROUP BY device_id HAVING count(*)>1) x" 2>/dev/null | tr -d ' \r')
[ "${CAKISMA:-1}" = 0 ] && gec "çakışan açık dönem yok" || kal "çakışan açık dönem: $CAKISMA"

echo
echo "Kaynak ağacı"
if [ -x deploy/on-kontrol.sh ]; then
  deploy/on-kontrol.sh >/dev/null 2>&1 && gec "ön kontrol temiz" \
    || { kal "ön kontrol başarısız — ayrıntı: deploy/on-kontrol.sh"; }
fi

echo
echo "Yedek"
SON=$(ls -1t /var/yedek/denge-erp/*.sql.gz 2>/dev/null | head -1)
if [ -n "$SON" ]; then
  gec "en son yedek: $(basename "$SON")  ($(du -h "$SON" | cut -f1), $(date -r "$SON" '+%Y-%m-%d %H:%M'))"
else
  kal "yedek bulunamadı (/var/yedek/denge-erp) — KURULUM.md Adım 8"
fi

echo
[ "$HATA" -eq 0 ] && printf '\033[32mSISTEM SAGLIKLI\033[0m\n' \
                  || printf '\033[31mSORUN VAR\033[0m — yukarıdaki ✗ satırlarına bakın.\n'
exit "$HATA"
