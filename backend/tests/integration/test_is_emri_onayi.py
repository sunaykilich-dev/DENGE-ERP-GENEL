"""İş Emri Onayı modülü (2026-11-10): onaya gelen işler birim birim.

Ekran (`/is-emri-onayi`) yeni uç açmaz; Ana Panel "Bekleyen Onaylar"
süzgecini (`kpi=onay_bekleyen`) birimle daraltır. Burada sınanan: birim
sekmesi yalnız o birimin onay bekleyen (TAMAMLANDI ya da kalite onayı
bekleyen) işlerini getirir; açık iş gelmez (PB hariçliği Ana Panel
testlerinde). Ön yüz kaydı (menü,
rota, izinler katalogda) ayrıca denetlenir.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from servis_yardimci import giris

from app.permissions import PERMISSIONS, ROLES

pytestmark = pytest.mark.integration

LISTE = "/api/teknik-servis/isler"
ON_YUZ = Path(__file__).resolve().parents[3] / "frontend" / "src"


async def test_birim_sekmesi_yalniz_o_birimin_onay_bekleyenlerini_getirir(
    client, kullanici_ac, servis_isi_ac
) -> None:
    await kullanici_ac("onayci_m", "SERVIS_YONETICI")
    guv = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI")
    await servis_isi_ac(birim="GUVENLIK", durum="SAHADA")  # açık: onaya gitmedi
    await servis_isi_ac(birim="HABERLESME", durum="PLANLANDI")  # açık
    hab = await servis_isi_ac(birim="HABERLESME", durum="TAMAMLANDI")

    await giris(client, "onayci_m")
    for birim, beklenen in (("GUVENLIK", guv.id), ("HABERLESME", hab.id)):
        r = await client.get(LISTE, params={"kpi": "onay_bekleyen", "birim": birim})
        assert r.status_code == 200, r.text
        assert [k["id"] for k in r.json()] == [beklenen], birim
        assert r.headers["X-Toplam-Kayit"] == "1"


def test_on_yuz_kaydi_ve_izinler() -> None:
    if not ON_YUZ.is_dir():
        pytest.skip("frontend/src yok (yalnız backend)")
    uygulamalar = (ON_YUZ / "fiori" / "uygulamalar.ts").read_text(encoding="utf-8")
    blok = uygulamalar[uygulamalar.index('id: "/is-emri-onayi"') :]
    blok = blok[: blok.index("}")]
    izinler = re.findall(r'"([a-z_]+\.[a-z_]+)"', blok[blok.index("izin:") :])
    assert izinler == ["servis.kalite_onay", "servis.son_onay"]
    assert set(izinler) <= set(PERMISSIONS)
    # Onay yetkisi olan bir rol ekranı görür; teknisyen görmez.
    assert "servis.son_onay" in ROLES["SERVIS_YONETICI"][1]
    assert not set(izinler) & set(ROLES["SERVIS_TEKNISYEN"][1])
    assert 'sayfa("/is-emri-onayi")' in (ON_YUZ / "fiori" / "menu.ts").read_text(encoding="utf-8")
    rotalar = (ON_YUZ / "main.tsx").read_text(encoding="utf-8")
    assert 'path="/is-emri-onayi"' in rotalar and 'path="/is-emri-onayi/:id"' in rotalar
