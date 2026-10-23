#!/usr/bin/env bash
# Kurulu sistemin durumu. Hiçbir şeyi değiştirmez; her zaman çalıştırılabilir.
#   /opt/denge-erp/deploy/dogrula.sh
#
# TS-219 ile genişletildi: göç sürümü = koddaki beklenen head, kodda tanımlı
# her rol veritabanında var, teknik servis tabloları okunabiliyor, worker'ın
# kodda tanımlı her görevi son 25 saatte en az bir kez bitti, yedek
# yedekle.sh'in yazdığı dizinde (YEDEK_DIZIN) bulunuyor.
#
# Beklenen değerler (head, roller, görevler) BETİĞE YAZILMAZ, çalışan
# imajdaki koddan okunur: yeni bir migration, rol ya da görev eklendiğinde
# bu betiği güncellemeyi unutmak sessiz bir "SAĞLIKLI" üretmesin.
set -uo pipefail
HEDEF=$(cd "$(dirname "$0")/.." && pwd)
cd "$HEDEF"

# Yedek dizini yedekle.sh ile AYNI kaynaktan (tek değişken).
# shellcheck disable=SC1091
[ -r /etc/default/denge-erp ] && . /etc/default/denge-erp
YEDEK_DIZIN=${YEDEK_DIZIN:-/var/backups/denge-erp}
# Gece yedeği 03:00'te; 26 saatten eski son yedek "cron çalışmıyor" demektir.
YEDEK_AZAMI_SAAT=${YEDEK_AZAMI_SAAT:-26}

HATA=0
gec() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
kal() { printf '  \033[31m✗\033[0m %s\n' "$1"; HATA=1; }
bil() { printf '  · %s\n' "$1"; }

sql() { docker compose exec -T db psql -U dengeerp -d dengeerp -tAc "$1" 2>/dev/null | tr -d '\r'; }
# Koddan okuma: imajdaki uygulama ne bekliyorsa onu söyler.
kod() { docker compose exec -T api python -c "$1" 2>/dev/null | tr -d '\r'; }

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

CAKISMA=$(sql "SELECT count(*) FROM (SELECT device_id FROM device_vehicle_assignments
   WHERE valid_to IS NULL GROUP BY device_id HAVING count(*)>1) x" | tr -d ' ')
[ "${CAKISMA:-1}" = 0 ] && gec "çakışan açık dönem yok" || kal "çakışan açık dönem: $CAKISMA"

# --- Göç sürümü: veritabanı = koddaki tek head ---------------------------
# `alembic heads` imajdaki migration dosyalarından okur. Birden fazla head
# varsa zincir çatallanmıştır ve `upgrade head` açılışta düşer.
HEADS=$(docker compose exec -T api alembic heads 2>/dev/null | tr -d '\r' | awk '{print $1}' | grep -v '^$')
HEAD_ADET=$(printf '%s\n' "$HEADS" | grep -c . || true)
DB_SURUM=$(sql "select version_num from alembic_version")
if [ "$HEAD_ADET" != 1 ]; then
  kal "koddaki migration head sayısı $HEAD_ADET (tek olmalı): $(echo "$HEADS" | tr '\n' ' ')"
elif [ "$DB_SURUM" = "$HEADS" ]; then
  gec "göç sürümü $DB_SURUM = koddaki beklenen head"
else
  kal "göç sürümü ${DB_SURUM:-okunamadı}, beklenen $HEADS — api açılışında 'alembic upgrade head' koşmadı (docker compose logs api); EK E uygulandıysa migration'ı sahibiyle elle koşun"
fi
if [ -f SURUM.txt ] && grep -q '^hedef head' SURUM.txt; then
  PAKET_HEAD=$(grep '^hedef head' SURUM.txt | cut -d: -f2- | tr -d ' \r')
  [ "$PAKET_HEAD" = "$HEADS" ] && gec "SURUM.txt hedef head ile aynı ($PAKET_HEAD)" \
    || kal "SURUM.txt hedef head $PAKET_HEAD, kurulu kod $HEADS — paket ile kod karışmış"
fi

# --- Roller: kodda tanımlı her rol veritabanında var ---------------------
# Seed (python -m app.seeds.dev) açılışta rolleri senkronlar. Atlanırsa yeni
# servis rolleri kimsede görünmez ve kullanıcı atanamaz.
KOD_ROLLER=$(kod "from app.permissions import ROLES; print('\n'.join(sorted(ROLES)))")
DB_ROLLER=$(sql "select code from roles order by code")
if [ -z "$KOD_ROLLER" ]; then
  kal "koddaki rol listesi okunamadı (api konteyneri çalışıyor mu?)"
else
  EKSIK_ROL=$(comm -23 <(printf '%s\n' "$KOD_ROLLER" | sort) <(printf '%s\n' "$DB_ROLLER" | sort) | tr '\n' ' ')
  if [ -z "${EKSIK_ROL// /}" ]; then
    gec "kodda tanımlı $(printf '%s\n' "$KOD_ROLLER" | grep -c .) rolün hepsi veritabanında (servis rolleri dahil)"
  else
    kal "veritabanında olmayan rol(ler): $EKSIK_ROL — seed koşmamış: docker compose exec api python -m app.seeds.dev"
  fi
fi

# --- Teknik servis tabloları okunabiliyor --------------------------------
# Uygulamanın bağlandığı kullanıcıyla değil şema sahibiyle okunur; EK E
# uygulandıysa uygulama kullanıcısının yetkisini db-least-privilege.sql verir.
SERVIS_TABLOLARI="user_units service_orders service_order_events service_holds service_results
 service_equipment service_visits service_plans service_time_entries
 maintenance_contracts maintenance_periods maintenance_forms
 service_sla_policies service_alerts workshop_records rentals rental_assets
 service_part_requests quote_sends service_order_financials training_courses
 competencies service_notification_prefs service_mail_outbox
 course_competencies service_competency_requirements"
OKUNAMAYAN=""
for t in $SERVIS_TABLOLARI; do
  [ -n "$(sql "select 1 from $t limit 0; select 'ok'")" ] || OKUNAMAYAN="$OKUNAMAYAN $t"
done
if [ -z "$OKUNAMAYAN" ]; then
  gec "teknik servis tabloları okunabiliyor ($(echo $SERVIS_TABLOLARI | wc -w) tablo)"
  sql "SELECT 'servis_isi='||(select count(*) from service_orders)
       ||' ekipman='||(select count(*) from service_equipment)
       ||' bakim_sozlesmesi='||(select count(*) from maintenance_contracts)
       ||' servis_rolu_atanmis_kullanici='||(select count(distinct u.id) from users u
            join roles r on r.id = u.role_id where r.code in
            ('SERVIS_YONETICI','SERVIS_SEF','SERVIS_OPERASYON','SERVIS_TEKNISYEN',
             'ATOLYE','SERVIS_DEPO','KIRALAMA_DEPO','IK'))" | sed 's/^/  · /'
else
  kal "okunamayan servis tablosu:$OKUNAMAYAN — migration eksik ya da yetki yok"
fi

# Devreye alma bayrakları (KURULUM.md EK G.0): bilgi amaçlı, hata sayılmaz.
sql "select key||' = '||coalesce(value::text,'(boş)') from settings
     where key in ('bakim_otomatik_uretim','servis_sla_yururluk_at','servis_eposta_acik')
     order by key" | sed 's/^/  · bayrak: /'

echo
echo "Worker görevleri"
# Görev listesi koddan (app.worker.GOREVLER). Her görev worker açılışında bir
# kez, sonra periyoduyla (en seyreği 24 saat) koşar; bu yüzden son 25 saatin
# log'unda her görev için en az bir "görev bitti ad=<görev>" satırı olmalı.
GOREVLER=$(docker compose exec -T worker python -c \
  "from app.worker import GOREVLER; print('\n'.join(g.ad for g in GOREVLER))" 2>/dev/null | tr -d '\r')
if [ -z "$GOREVLER" ]; then
  kal "worker görev listesi okunamadı — EK A: No module named app.worker"
else
  for g in servis-sla-uyarilari servis-uyari-temizligi servis-eposta pb-uretimi bakim-donem-uzlastirma; do
    printf '%s\n' "$GOREVLER" | grep -qx "$g" || kal "worker görev listesinde '$g' YOK — worker imajı eski: docker compose build && docker compose up -d"
  done
  LOG=$(docker compose logs worker --since 25h --no-color 2>/dev/null)
  EKSIK_GOREV=""
  for g in $GOREVLER; do
    printf '%s\n' "$LOG" | grep -q "görev bitti ad=$g " || EKSIK_GOREV="$EKSIK_GOREV $g"
  done
  if [ -z "$EKSIK_GOREV" ]; then
    gec "$(printf '%s\n' "$GOREVLER" | grep -c .) görevin hepsi son 25 saatte en az bir kez bitti"
  else
    kal "son 25 saatte bitmemiş görev:$EKSIK_GOREV — docker compose logs worker | grep 'görev HATA'"
  fi
fi

echo
echo "Kaynak ağacı"
if [ -x deploy/on-kontrol.sh ]; then
  deploy/on-kontrol.sh >/dev/null 2>&1 && gec "ön kontrol temiz" \
    || { kal "ön kontrol başarısız — ayrıntı: deploy/on-kontrol.sh"; }
fi

echo
echo "Yedek ($YEDEK_DIZIN)"
# yedekle.sh iki dosya yazar: dengeerp-<damga>.sql.gz.gpg ve
# dosyalar-<damga>.tar.gz.gpg. Yalnız DB yedeği ekleri geri getirmez.
SON=$(ls -1t "$YEDEK_DIZIN"/dengeerp-*.sql.gz.gpg 2>/dev/null | head -1)
if [ -n "$SON" ]; then
  YAS_SAAT=$(( ( $(date +%s) - $(date -r "$SON" +%s) ) / 3600 ))
  if [ "$YAS_SAAT" -le "$YEDEK_AZAMI_SAAT" ]; then
    gec "en son yedek: $(basename "$SON")  ($(du -h "$SON" | cut -f1), $(date -r "$SON" '+%Y-%m-%d %H:%M'))"
  else
    kal "en son yedek $YAS_SAAT saat önce ($(basename "$SON")) — cron çalışmıyor: sudo crontab -l"
  fi
  ESI="$YEDEK_DIZIN/$(basename "$SON" | sed 's/^dengeerp-/dosyalar-/; s/\.sql\.gz\.gpg$/.tar.gz.gpg/')"
  [ -f "$ESI" ] && gec "dosya yedeği de var: $(basename "$ESI")" \
    || kal "dosya yedeği yok ($(basename "$ESI")) — ekler geri getirilemez"
else
  kal "yedek bulunamadı ($YEDEK_DIZIN) — KURULUM.md Adım 8"
fi

echo
[ "$HATA" -eq 0 ] && printf '\033[32mSISTEM SAGLIKLI\033[0m\n' \
                  || printf '\033[31mSORUN VAR\033[0m — yukarıdaki ✗ satırlarına bakın.\n'
exit "$HATA"
