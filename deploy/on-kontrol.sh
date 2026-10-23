#!/usr/bin/env bash
# Kurulumun her adiminda "elle bakmak" yerine kosulacak tek kontrol.
# Goz karari dogrulama hata kacirir: *.py kabuk kalibi bastaki noktayi
# eslemez (._dosya.py gorunmez) ve grep -P '\x00' NUL bayti bildirmez.
# Bu betik ikisini de Python ile, kesin olarak olcer.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

HATA=0
gec() { printf '  \033[32mTAMAM\033[0m  %s\n' "$1"; }
kal() { printf '  \033[31mHATA \033[0m  %s\n' "$1"; HATA=1; }

echo "== Denge ERP kurulum on kontrolu =="
echo

echo "1) Dosyalar yerinde mi"
for d in docker-compose.yml backend/Dockerfile backend/alembic.ini \
         backend/app/static/index.html backend/app/main.py; do
  [ -f "$d" ] && gec "$d" || kal "$d YOK"
done

echo
echo "2) Kaynak agaci temiz mi (AppleDouble / NUL / sozdizimi)"
python3 - <<'PY'
import pathlib, sys
kok = pathlib.Path(".")
atla = {".git", ".venv", "node_modules", "__pycache__", "var", "dist"}
apple, nul, sozdizimi, sayi = [], [], [], 0
for f in kok.rglob("*"):
    if not f.is_file() or set(f.parts) & atla:
        continue
    if f.name.startswith("._") or f.name == ".DS_Store":
        apple.append(str(f)); continue
    if f.suffix != ".py":
        continue
    sayi += 1
    b = f.read_bytes()
    if b"\x00" in b:
        nul.append(f"{f} (NUL @ {b.index(b'\x00')})"); continue
    try:
        compile(b, str(f), "exec")
    except SyntaxError as e:
        sozdizimi.append(f"{f}: {e}")

def rapor(ad, liste):
    if liste:
        print(f"  HATA   {ad}: {len(liste)} dosya")
        for x in liste[:10]:
            print(f"         - {x}")
        if len(liste) > 10:
            print(f"         ... +{len(liste)-10} daha")
        return 1
    print(f"  TAMAM  {ad} yok")
    return 0

k  = rapor("macOS AppleDouble / .DS_Store dosyasi", apple)
k += rapor("NUL bayti iceren .py", nul)
k += rapor("sozdizimi hatali .py", sozdizimi)
print(f"  TAMAM  {sayi} .py dosyasi derlendi")
sys.exit(1 if k else 0)
PY
[ $? -eq 0 ] || HATA=1

echo
echo "3) Migration zinciri"
# Alt sinir (TS-219): teknik servis Dalga 0-4 ile 39 dosya (d3a000000003
# bilerek atlandi). Daha azi eksik acilmis arsiv ya da eski paket demektir.
# Sayi tek basina yetmez: zincir tek head'de bitmeli ve SURUM.txt'teki
# "hedef head" ile ayni olmali; alembic'e gerek kalmadan dosyalardan okunur.
MIGRATION_ALT_SINIR=39
python3 - "$MIGRATION_ALT_SINIR" <<'PY'
import pathlib, re, sys
alt = int(sys.argv[1])
dosyalar = [f for f in pathlib.Path("backend/alembic/versions").glob("*.py")
            if not f.name.startswith("._")]
rev, onceki = {}, set()
for f in dosyalar:
    m = f.read_text(encoding="utf-8", errors="replace")
    r = re.search(r'^revision(?:: str)?\s*=\s*["\']([^"\']+)', m, re.M)
    d = re.search(r'^down_revision[^=]*=\s*(.+)$', m, re.M)
    if r:
        rev[r.group(1)] = f.name
    if d:
        onceki.update(re.findall(r'["\']([^"\']+)["\']', d.group(1)))
head = sorted(set(rev) - onceki)
kod = 0
if len(dosyalar) >= alt:
    print(f"  TAMAM  {len(dosyalar)} migration dosyasi (alt sinir {alt})")
else:
    print(f"  HATA   yalnizca {len(dosyalar)} migration (en az {alt} beklenir)"); kod = 1
if len(head) == 1:
    print(f"  TAMAM  tek head: {head[0]}")
else:
    print(f"  HATA   head sayisi {len(head)}: {head}"); kod = 1
surum = pathlib.Path("SURUM.txt")
if surum.exists() and len(head) == 1:
    for satir in surum.read_text(encoding="utf-8", errors="replace").splitlines():
        if satir.startswith("hedef head"):
            beklenen = satir.split(":", 1)[1].strip()
            if beklenen == head[0]:
                print(f"  TAMAM  SURUM.txt hedef head ile ayni")
            else:
                print(f"  HATA   SURUM.txt hedef head {beklenen}, kaynak agaci {head[0]}"); kod = 1
sys.exit(kod)
PY
[ $? -eq 0 ] || HATA=1

echo
echo "4) .env"
if [ -f .env ]; then
  for a in POSTGRES_PASSWORD DATABASE_URL SECRET_KEY SETTINGS_ENC_KEY; do
    grep -q "^$a=." .env && gec "$a dolu" || kal "$a eksik ya da bos"
  done
  P=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
  if [ -n "$P" ] && grep -q "^DATABASE_URL=.*:${P}@" .env; then
    gec "DATABASE_URL parolasi POSTGRES_PASSWORD ile ayni"
  else
    kal "DATABASE_URL icindeki parola POSTGRES_PASSWORD'den FARKLI"
  fi
  grep -qi 'degistir' .env && kal ".env'de ornek deger kalmis ('degistir')" \
                           || gec "ornek deger kalmamis"
else
  kal ".env yok (Adim 4)"
fi

echo
if [ "$HATA" -eq 0 ]; then
  printf '\033[32mON KONTROL BASARILI\033[0m — sonraki adima gecebilirsiniz.\n'
else
  printf '\033[31mON KONTROL BASARISIZ\033[0m — yukaridaki HATA satirlarini giderin, DEVAM ETMEYIN.\n'
fi
exit "$HATA"
