"""Deploy betiklerinin birbiriyle ve kodla tutarlılığı (TS-219, TS-220).

NEDEN: betikler sunucuda koşar ve testte çalıştırılamaz; tutarsızlık ancak
canlıda görünür. Bir kez oldu: `yedekle.sh` `/var/backups/denge-erp`'e
yazarken `dogrula.sh` `/var/yedek/denge-erp`'te `*.sql.gz` arıyordu ve
yedek alınmış olsa da "yedek bulunamadı" diyordu. Bu dosya o tür kaymaları
(yedek dizini/adı, migration alt sınırı, head, tablo ve görev adları,
paket içeriği, KURULUM.md migration listesi) kodla karşılaştırarak kilitler.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[3]
DEPLOY = KOK / "deploy"
BACKEND = KOK / "backend"


def _oku(ad: str) -> str:
    return (DEPLOY / ad).read_text(encoding="utf-8")


def _varsayilan_yedek_dizini(metin: str) -> str:
    m = re.search(r"^YEDEK_DIZIN=\$\{YEDEK_DIZIN:-([^}]+)\}", metin, re.M)
    assert m, "YEDEK_DIZIN varsayılanı bulunamadı"
    return m.group(1)


def _migration_head_ve_sayi() -> tuple[list[str], int]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    betik = ScriptDirectory.from_config(cfg)
    sayi = sum(1 for _ in betik.walk_revisions())
    return list(betik.get_heads()), sayi


# --- TS-219: yedek dizini tek değişken ------------------------------------


def test_yedek_dizini_yazan_ve_okuyan_betikte_ayni():
    yazan = _varsayilan_yedek_dizini(_oku("yedekle.sh"))
    assert yazan == "/var/backups/denge-erp"
    for ad in ("dogrula.sh", "cikis-provasi.sh"):
        assert _varsayilan_yedek_dizini(_oku(ad)) == yazan, ad
    # Ortak ayar dosyası ikisinde de okunur: biri değiştirilince diğeri kaymasın.
    for ad in ("yedekle.sh", "dogrula.sh", "cikis-provasi.sh"):
        assert "/etc/default/denge-erp" in _oku(ad), ad


def test_eski_yedek_dizini_hicbir_yerde_kalmadi():
    for f in DEPLOY.rglob("*"):
        if f.is_file() and f.suffix in {".sh", ".md", ".py"}:
            assert "/var/yedek/" not in f.read_text(encoding="utf-8"), f.name


def test_dogrula_yedekle_shin_yazdigi_adi_ariyor():
    yedekle = _oku("yedekle.sh")
    dogrula = _oku("dogrula.sh")
    assert "dengeerp-$DAMGA.sql.gz.gpg" in yedekle
    assert "dosyalar-$DAMGA.tar.gz.gpg" in yedekle
    assert "dengeerp-*.sql.gz.gpg" in dogrula
    assert "dosyalar-" in dogrula and ".tar.gz.gpg" in dogrula


# --- TS-219: migration alt sınırı ve head ---------------------------------


def test_on_kontrol_migration_alt_siniri_guncel():
    m = re.search(r"^MIGRATION_ALT_SINIR=(\d+)", _oku("on-kontrol.sh"), re.M)
    assert m
    alt = int(m.group(1))
    dosya = [
        f for f in (BACKEND / "alembic" / "versions").glob("*.py") if not f.name.startswith("._")
    ]
    heads, revizyon = _migration_head_ve_sayi()
    # Alt sınır gerçek sayıyı aşmamalı (yoksa her kurulum düşer) ve Dalga 4
    # sonrası sayının altında kalmamalı (yoksa eksik arşiv yakalanmaz).
    assert alt <= len(dosya) == revizyon
    assert alt >= 39, "Dalga 0-4 sonrası 39 migration var (d3a000000003 atlandı)"
    assert len(heads) == 1


def test_on_kontrol_ve_paket_head_hesabi_alembicle_ayni():
    """on-kontrol.sh ve paket-uret.sh head'i alembic'siz, regex ile bulur;
    aynı regex alembic'in bulduğu tek head'i vermeli."""
    heads, _ = _migration_head_ve_sayi()
    rev, onceki = set(), set()
    for f in (BACKEND / "alembic" / "versions").glob("*.py"):
        m = f.read_text(encoding="utf-8")
        r = re.search(r'^revision(?:: str)?\s*=\s*["\']([^"\']+)', m, re.M)
        d = re.search(r"^down_revision[^=]*=\s*(.+)$", m, re.M)
        if r:
            rev.add(r.group(1))
        if d:
            onceki.update(re.findall(r'["\']([^"\']+)["\']', d.group(1)))
    assert sorted(rev - onceki) == heads
    for ad in ("on-kontrol.sh", "paket-uret.sh"):
        metin = _oku(ad)
        assert "^revision(?:: str)?" in metin and "^down_revision[^=]*=" in metin, ad
    assert 'echo "hedef head   : $HEDEF_HEAD"' in _oku("paket-uret.sh")


# --- TS-219: dogrula.sh'in denetlediği adlar kodda var ---------------------


def test_dogrula_servis_tablolari_semada_var():
    import app.models  # noqa: F401 — tüm modelleri metadata'ya kaydeder
    from app.db import Base

    m = re.search(r'SERVIS_TABLOLARI="([^"]+)"', _oku("dogrula.sh"))
    assert m
    tablolar = m.group(1).split()
    assert len(tablolar) >= 20
    eksik = [t for t in tablolar if t not in Base.metadata.tables]
    assert not eksik


def test_dogrula_zorunlu_worker_gorevleri_kodda_var():
    from app import worker

    adlar = {g.ad for g in worker.GOREVLER}
    m = re.search(r"for g in ([a-z\- ]+); do", _oku("dogrula.sh"))
    assert m
    zorunlu = set(m.group(1).split())
    assert {"servis-sla-uyarilari", "servis-eposta"} <= zorunlu
    assert zorunlu <= adlar
    # dogrula.sh log'da bu kalıbı arar; log biçimi değişirse betik kör kalır.
    kaynak = (BACKEND / "app" / "worker.py").read_text(encoding="utf-8")
    assert '"görev bitti ad=%s süre=' in kaynak
    assert "görev bitti ad=$g " in _oku("dogrula.sh")


def test_dogrula_beklenenleri_koddan_okur():
    dogrula = _oku("dogrula.sh")
    assert "alembic heads" in dogrula
    assert "from app.permissions import ROLES" in dogrula
    assert "from app.worker import GOREVLER" in dogrula


# --- TS-220: paket içeriği ------------------------------------------------


def test_paket_yedek_ve_geri_donus_betiklerini_tasir():
    paket = _oku("paket-uret.sh")
    m = re.search(r"PAKET_BETIKLERI=\(([^)]+)\)", paket)
    assert m
    betikler = set(m.group(1).split())
    assert {"kur.sh", "on-kontrol.sh", "dogrula.sh", "yedekle.sh", "geri-yukle.sh"} <= betikler
    assert "cikis-provasi.sh" in betikler
    assert all((DEPLOY / b).is_file() for b in betikler)
    assert "servis_duman.py" in paket and "CIKIS-PROVASI-TUTANAGI.md" in paket
    # kur.sh paketteki betikleri hedefe kopyalar; liste aynı olmalı.
    kur = re.search(r"for b in ([a-z\-. ]+); do\n\s+\[ -f \"\$PAKET/\$b\" \]", _oku("kur.sh"))
    assert kur
    assert set(kur.group(1).split()) == betikler
    assert "teknik servis:" in paket


def test_paket_gnu_tarda_da_calisir():
    """`--no-mac-metadata` yalnız bsdtar'da var; koşulsuz verilirse Linux'ta
    paket hiç üretilemez."""
    paket = _oku("paket-uret.sh")
    for satir in paket.splitlines():
        if "--no-mac-metadata" in satir and not satir.lstrip().startswith("#"):
            assert "TAR_EK=" in satir or "grep -q" in satir, satir


def test_geri_yukle_canli_veritabanini_yeniden_yaratir():
    metin = _oku("geri-yukle.sh")
    assert "WITH (FORCE)" in metin
    assert "docker compose stop api worker" in metin
    # api durdurulduktan sonra `exec api` çalışmaz.
    zorla_blogu = metin.split('elif [ "$HEDEF_DB" = "dengeerp" ]; then', 1)[1].split("else", 1)[0]
    assert "exec -T api" not in zorla_blogu


# --- TS-220: KURULUM.md ---------------------------------------------------


def test_kurulum_tum_servis_migrationlarini_ve_geri_donus_kuralini_anlatir():
    kurulum = _oku("KURULUM.md")
    for f in sorted((BACKEND / "alembic" / "versions").glob("d[0-9]a*.py")):
        rev = f.name.split("_", 1)[0]
        assert rev in kurulum, rev
    assert "d3a000000003" in kurulum  # atlandığı yazılı olmalı
    assert "EK G" in kurulum and "Teknik Servis devreye alma" in kurulum
    assert "alembic downgrade" in kurulum
    for terim in ("geri-yukle.sh", "cikis-provasi.sh", "Göç-2", "G.8"):
        assert terim in kurulum, terim


# --- Biçim: LF satır sonu ve bash sözdizimi -------------------------------


def _bash() -> str | None:
    for aday in (shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"):
        if aday and Path(aday).exists() and "System32" not in aday:
            return aday
    return None


@pytest.mark.parametrize("ad", sorted(p.name for p in DEPLOY.glob("*.sh")))
def test_betik_lf_ve_bash_sozdizimi(ad):
    ham = (DEPLOY / ad).read_bytes()
    assert b"\r\n" not in ham, f"{ad} CRLF içeriyor; sunucuda '$'\\r': command not found' verir"
    assert ham.startswith(b"#!/usr/bin/env bash")
    bash = _bash()
    if bash is None:
        pytest.skip("bash yok")
    sonuc = subprocess.run([bash, "-n", str(DEPLOY / ad)], capture_output=True, text=True)
    assert sonuc.returncode == 0, sonuc.stderr


# --- Servis duman testi modülü --------------------------------------------


def _duman_modulu():
    spec = importlib.util.spec_from_file_location("servis_duman", DEPLOY / "servis_duman.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_duman_testi_prova_bayragi_olmadan_calismaz(monkeypatch, capsys):
    mod = _duman_modulu()
    monkeypatch.delenv("DENGE_PROVA", raising=False)
    assert mod.main() == 2
    assert "DENGE_PROVA=1" in capsys.readouterr().out


def test_duman_testi_rotalari_uygulamada_kayitli():
    mod = _duman_modulu()
    sonuc = mod.rota_denetimi()
    assert len(sonuc) == len(mod.BEKLENEN_ONEKLER)
    assert all(tamam for tamam, _ in sonuc), [m for t, m in sonuc if not t]


def test_cikis_provasi_onaysiz_calismaz():
    bash = _bash()
    if bash is None:
        pytest.skip("bash yok")
    ortam = {k: v for k, v in os.environ.items() if k != "PROVA_ONAY"}
    sonuc = subprocess.run(
        [bash, str(DEPLOY / "cikis-provasi.sh")], capture_output=True, text=True, env=ortam
    )
    assert sonuc.returncode == 2
    assert "PROVA_ONAY=evet" in sonuc.stderr
