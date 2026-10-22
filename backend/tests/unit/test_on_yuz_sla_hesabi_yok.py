"""İstemcide SLA hesabı YOK (TS-081, E10-18 (3)).

SLA durumu, kalan süre ve hedef yalnız sunucudaki tek SLA modülünden gelir
(`services/teknik_servis/sla.py`). Ön yüzde öncelik → saat eşlemesi (ör.
"KRITIK: 12") ya da hedef süre çarpımı (`72 * 60`) yazılırsa iki kaynak oluşur
ve politika değişince ekran sunucudan ayrışır. Bu grep testi o kopyayı yakalar.
`frontend/` yoksa (yalnız backend imajı) atlanır.
"""

import re
from pathlib import Path

import pytest

FRONTEND_SRC = Path(__file__).resolve().parents[3] / "frontend" / "src"

# Öncelik adı ile aynı satırda saat/dakika sayısı (12, 24, 72 veya *60 çarpımı).
DESENLER = (
    re.compile(r"\b(KRITIK|YUKSEK|NORMAL)\b\s*[:=]\s*\(?\s*(12|24|72|720|1440|4320)\b"),
    re.compile(r"\b(12|24|72)\s*\*\s*60\b"),
    re.compile(r"cozum_saat\s*\*"),
)


def test_on_yuzde_oncelik_saat_eslemesi_yok() -> None:
    if not FRONTEND_SRC.is_dir():
        pytest.skip("frontend/src yok (yalnız backend)")
    bulgular = []
    for dosya in FRONTEND_SRC.rglob("*.ts*"):
        metin = dosya.read_text(encoding="utf-8")
        for no, satir in enumerate(metin.splitlines(), start=1):
            if any(d.search(satir) for d in DESENLER):
                bulgular.append(f"{dosya.relative_to(FRONTEND_SRC)}:{no}: {satir.strip()}")
    assert not bulgular, "Ön yüzde SLA hesabı (öncelik → saat) bulundu:\n" + "\n".join(bulgular)
