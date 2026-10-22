"""Ekipman kütüğü kapsamı: iki birim, iki şef (TS-050 kabulü, TS-053 sayı = sızıntı,
TS-057 ek/arama kapsamı). Kapsam dışı tek kayıt 404 ve `db.refresh` ile veri
değişmedi doğrulanır."""

import httpx
import pytest
from sqlalchemy import func, select

from app.models import AuditLog, ServiceEquipment

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/ekipman"


@pytest.fixture
async def ortam(client, birimli_kullanici_ac, ekipman_ac):
    from app.main import app

    await birimli_kullanici_ac("sef_guv", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_hab", "SERVIS_SEF", ["HABERLESME"])
    await birimli_kullanici_ac("sef_birimsiz", "SERVIS_SEF", [])
    istemciler = {}
    for ad in ("sef_guv", "sef_hab", "sef_birimsiz"):
        ist = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Requested-With": "fetch"},
        )
        r = await ist.post("/api/auth/login", json={"username": ad, "password": "parola1234"})
        assert r.status_code == 200, r.text
        istemciler[ad] = ist
    guv = [await ekipman_ac(birim="GUVENLIK", seri=f"GV-{i}") for i in range(3)]
    hab = await ekipman_ac(birim="HABERLESME", seri="HB-1", zone="Eski Bölge")
    yield istemciler, guv, hab
    for ist in istemciler.values():
        await ist.aclose()


async def _anlik(db, e: ServiceEquipment) -> dict:
    db.expire(e)
    await db.refresh(e)
    kolonlar = {
        a: getattr(e, a)
        for a in ("birim", "zone", "serial_no", "lifecycle_status", "is_active", "version")
    }
    kolonlar["#audit"] = await db.scalar(select(func.count()).select_from(AuditLog))
    return kolonlar


async def test_liste_ozet_excel_yalniz_kendi_birimi(ortam) -> None:
    ist, guv, hab = ortam
    r = await ist["sef_guv"].get(URL)
    assert r.headers["X-Toplam-Kayit"] == "3"
    assert {s["id"] for s in r.json()} == {e.id for e in guv}
    ozet = {k["kod"]: k["deger"] for k in (await ist["sef_guv"].get(f"{URL}/ozet")).json()}
    assert ozet["toplam"] == 3
    r = await ist["sef_hab"].get(URL)
    assert [s["id"] for s in r.json()] == [hab.id]
    # Kimlik listesiyle Excel de kapsamı aşamaz.
    r = await ist["sef_hab"].get(
        f"{URL}/liste.xlsx", params={"ids": ",".join(str(e.id) for e in guv)}
    )
    assert r.status_code == 200
    from io import BytesIO

    from openpyxl import load_workbook

    assert load_workbook(BytesIO(r.content)).active.max_row == 1  # yalnız başlık


async def test_birimsiz_sef_hicbir_sey_gormez(ortam) -> None:
    ist, guv, _ = ortam
    r = await ist["sef_birimsiz"].get(URL)
    assert r.status_code == 200 and r.json() == []
    assert r.headers["X-Toplam-Kayit"] == "0"
    assert (await ist["sef_birimsiz"].get(f"{URL}/{guv[0].id}")).status_code == 404


@pytest.mark.parametrize(
    ("yontem", "yol", "govde"),
    [
        ("GET", "", None),
        ("GET", "/gecmis", None),
        ("GET", "/degisiklikler", None),
        ("PATCH", "", {"version": 1, "zone": "Değişti"}),
        ("POST", "/pasif", {"gerekce": "Kapsam dışı deneme"}),
        ("POST", "/aktif", {"gerekce": "Kapsam dışı deneme"}),
        ("POST", "/durum", {"hedef": "KURULU", "gerekce": "Kapsam dışı deneme"}),
    ],
)
async def test_kapsam_disi_tek_kayit_404_veri_degismez(ortam, db, yontem, yol, govde) -> None:
    ist, _, hab = ortam
    once = await _anlik(db, hab)
    r = await ist["sef_guv"].request(yontem, f"{URL}/{hab.id}{yol}", json=govde)
    assert r.status_code == 404, r.text
    assert await _anlik(db, hab) == once


async def test_birimi_kapsam_disina_tasima_404(ortam, db) -> None:
    ist, guv, _ = ortam
    e = guv[0]
    once = await _anlik(db, e)
    r = await ist["sef_guv"].patch(
        f"{URL}/{e.id}", json={"version": e.version, "birim": "HABERLESME"}
    )
    assert r.status_code == 404
    assert await _anlik(db, e) == once


async def test_kapsam_disi_birime_kayit_acilamaz(ortam, db) -> None:
    ist, _, hab = ortam
    once = await db.scalar(select(func.count()).select_from(ServiceEquipment))
    r = await ist["sef_guv"].post(
        URL, json={"birim": "HABERLESME", "equipment_type": "XRAY", "account_id": hab.account_id}
    )
    assert r.status_code == 404
    assert await db.scalar(select(func.count()).select_from(ServiceEquipment)) == once


async def test_ekler_baska_birimde_404(ortam) -> None:
    ist, guv, hab = ortam
    assert (
        await ist["sef_guv"].get(f"/api/ekler/service_equipment/{guv[0].id}")
    ).status_code == 200
    assert (await ist["sef_guv"].get(f"/api/ekler/service_equipment/{hab.id}")).status_code == 404
    r = await ist["sef_guv"].post(
        f"/api/ekler/service_equipment/{hab.id}",
        data={"kind": "DIGER"},
        files={"file": ("a.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert r.status_code == 404


async def test_genel_arama_kapsamli(ortam) -> None:
    ist, guv, hab = ortam
    r = await ist["sef_guv"].get("/api/arama", params={"q": "hb-1"})
    assert r.status_code == 200
    assert not [s for s in r.json() if s["tur"] == "EKIPMAN"]
    r = await ist["sef_hab"].get("/api/arama", params={"q": "hb-1"})
    sonuc = [s for s in r.json() if s["tur"] == "EKIPMAN"]
    assert [s["id"] for s in sonuc] == [hab.id]
    assert sonuc[0]["yol"] == f"/servis-ekipman/{hab.id}"
