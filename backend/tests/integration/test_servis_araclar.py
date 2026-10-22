"""Servis araç havuzu (TS-048, E02-17).

Kabul: yazma `servis.arac_yaz`; plaka anahtarı tekil ("34 ABC 123" ile
"34abc123" aynı araç → 409); birim NULL = ortak havuz; birim kapsamı (başka
birimin aracı görünmez, güncellenemez → 404 ve veri değişmez); mobilite
`vehicles` tablosu yalnız okunur.
"""

import pytest
from planlama_yardim import ortam_fixture, oturum  # noqa: F401
from sqlalchemy import func, select

from app.models import ServiceVehicle, Vehicle

pytestmark = pytest.mark.integration

YOL = "/api/teknik-servis/planlama/araclar"


async def test_plaka_anahtari_tekil_ve_rbac(ortam, db) -> None:
    mobilite_once = await db.scalar(select(func.count()).select_from(Vehicle))
    yon = await ortam.ist("yonetici")
    r = await yon.post(YOL, json={"plaka": "34 ABC 123", "birim": "GUVENLIK"})
    assert r.status_code == 201, r.text
    r = await yon.post(YOL, json={"plaka": "34abc123"})
    assert r.status_code == 409
    sef = await ortam.ist("sef_g")  # servis.arac_yaz yok
    r = await sef.post(YOL, json={"plaka": "34 XYZ 999"})
    assert r.status_code == 403
    r = await yon.post(YOL, json={"plaka": "34 ABC 123", "birim": "YOK_BIRIM"})
    assert r.status_code == 400
    assert await db.scalar(select(func.count()).select_from(Vehicle)) == mobilite_once


async def test_birim_kapsami_ortak_havuz_ve_guncelleme(
    ortam, db, rol_ac, birimli_kullanici_ac
) -> None:
    guv = ServiceVehicle(plate="34 GUV 001", birim="GUVENLIK")
    hab = ServiceVehicle(plate="34 HAB 001", birim="HABERLESME")
    ortak = ServiceVehicle(plate="34 ORT 001", birim=None)
    db.add_all([guv, hab, ortak])
    await db.commit()

    sef = await ortam.ist("sef_g")
    r = await sef.get(YOL)
    assert r.status_code == 200
    assert {a["plaka"] for a in r.json()} == {"34 GUV 001", "34 ORT 001"}

    await rol_ac("T_ARACCI", ["servis.gor", "servis.arac_yaz"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("aracci", "T_ARACCI", ["GUVENLIK"])
    ist = await oturum("aracci")
    try:
        r = await ist.patch(f"{YOL}/{hab.id}", json={"version": hab.version, "notlar": "x"})
        assert r.status_code == 404
        await db.refresh(hab)
        assert hab.notes is None and hab.version == 1
        # Kendi biriminin aracını başka birime taşıyamaz.
        r = await ist.patch(f"{YOL}/{guv.id}", json={"version": guv.version, "birim": "HABERLESME"})
        assert r.status_code == 404
        # Ortak havuz açamaz (yalnız TUMU).
        r = await ist.post(YOL, json={"plaka": "34 YEN 001"})
        assert r.status_code == 404
        r = await ist.patch(
            f"{YOL}/{guv.id}",
            json={"version": guv.version, "is_active": False, "notlar": "Bakımda"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        r = await ist.patch(f"{YOL}/{guv.id}", json={"version": 1, "notlar": "eski sürüm"})
        assert r.status_code == 409
    finally:
        await ist.aclose()
