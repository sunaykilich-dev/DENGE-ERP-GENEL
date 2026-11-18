"""UI/UX revize (2026-11-18) — Planlı Bakım sekme sadeleştirmesi (S2/S9).

Bakım 10 sekmeden 6'ya indi; eski sekme adları yeni sekmelere yönlendirilir.
Sunucunun (KPI `yol`, rapor bağlantıları) ve ön yüzün ürettiği her
`/bakim?sekme=` bağlantısı hâlâ geçerli bir sekmeye düşmelidir — yoksa e-posta
özetindeki ya da kutucuktaki bağlantı boş sayfa açar.
"""

import re
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[3]
ON_YUZ = KOK / "frontend" / "src"


@pytest.fixture(autouse=True)
def _on_yuz_var() -> None:
    if not ON_YUZ.is_dir():
        pytest.skip("frontend/src yok (yalnız backend)")


def _oku(*parca: str) -> str:
    return ON_YUZ.joinpath(*parca).read_text(encoding="utf-8")


def _bakim_sekmeleri() -> tuple[set[str], dict[str, str], dict[str, str]]:
    bakim = _oku("pages", "BakimPage.tsx")
    govde = bakim.split("export default function BakimPage", 1)[1]
    tabs = govde.split("<Tabs", 1)[1].split("<BakimFormu", 1)[0]
    ust = {
        a or b
        for a, b in re.findall(r'^\s{12}\{ key: "([a-z-]+)"|^\s{14}key: "([a-z-]+)"', tabs, re.M)
    }

    def harita(ad: str) -> dict[str, str]:
        blok = bakim.split(f"const {ad}: Record<string, string> = {{", 1)[1].split("};", 1)[0]
        return dict(re.findall(r'"?([a-z-]+)"?:\s*"([a-z-]+)"', blok))

    return ust, harita("ESKI_SEKMELER"), harita("ALT_SEKMELER")


def test_s9_eski_bakim_bagliantilari_gecerli_sekmeye_duser() -> None:
    """Sunucu (KPI `yol`, rapor bağlantıları) ve ön yüzdeki her `/bakim?sekme=`
    değeri yeni yapıda bir sekmeye ya da alt görünüme çözülmelidir."""
    ust, eski, alt = _bakim_sekmeleri()
    gecerli = ust | set(eski) | set(alt)
    kaynaklar = list((KOK / "backend" / "app").rglob("*.py")) + list(ON_YUZ.rglob("*.ts*"))
    bulunan: set[str] = set()
    for dosya in kaynaklar:
        for deger in re.findall(r"/bakim\?sekme=([a-z-]+)", dosya.read_text(encoding="utf-8")):
            bulunan.add(deger)
    assert bulunan, "hiç /bakim?sekme= bağlantısı bulunamadı"
    assert bulunan <= gecerli, bulunan - gecerli
