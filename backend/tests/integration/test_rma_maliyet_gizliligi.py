"""RMA maliyet alanı sızıntı testi (M6.5, KARARLAR 2026-10-28 §7 Faz A/3).

`rma_cases.cost` `maliyet.gor` olmayan kullanıcıya hiçbir RMA yanıtında dolu
dönmez; bu kullanıcı bedel yazamaz (403) ve çözümü başkasının girdiği bedeli
silemez. Yetkili kullanıcı (ADMIN) için davranış değişmez.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models import RmaCase

pytestmark = pytest.mark.integration

GIZLI = Decimal("1234.56")


async def _giris(client, username: str) -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _kayit(client, db, kullanici_ac, urun_ac, cihaz_ac) -> int:
    """Garanti dışı RMA + yetkili kullanıcının girdiği bedel."""
    await kullanici_ac("yonetici", "ADMIN")
    await kullanici_ac("teknik", "TEKNIK_SERVIS")
    u = await urun_ac("L300", "IMEI", warranty_months=12)
    await cihaz_ac(
        imei="860000000000901", urun=u, status="AKTIF", first_activation_date=date(2023, 1, 1)
    )
    await _giris(client, "yonetici")
    r = await client.post(
        "/api/rma",
        json={"kimlik": "860000000000901", "fault_description": "Su aldı"},
    )
    assert r.status_code == 201, r.text
    rma_id = r.json()["id"]
    r = await client.post(
        f"/api/rma/{rma_id}/coz", json={"resolution": "TAMIR", "cost": str(GIZLI)}
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["cost"]) == GIZLI
    return rma_id


async def test_maliyet_gormeyen_hicbir_ucta_maliyet_almaz(
    client, db, kullanici_ac, urun_ac, cihaz_ac
) -> None:
    rma_id = await _kayit(client, db, kullanici_ac, urun_ac, cihaz_ac)
    await _giris(client, "teknik")

    yanitlar = [
        await client.get("/api/rma"),
        await client.get(f"/api/rma?cihaz_id={(await db.get(RmaCase, rma_id)).device_id}"),
        await client.get(f"/api/rma/{rma_id}"),
        await client.post(f"/api/rma/{rma_id}/durum", json={"durum": "INCELEMEDE"}),
    ]
    surum = (await client.get(f"/api/rma/{rma_id}")).json()["version"]
    yanitlar.append(
        await client.patch(
            f"/api/rma/{rma_id}/tedarikci", json={"supplier_rma_no": "X-1", "version": surum}
        )
    )
    for r in yanitlar:
        assert r.status_code == 200, r.text
        govde = r.json()
        satirlar = govde if isinstance(govde, list) else [govde]
        assert satirlar
        for satir in satirlar:
            assert satir.get("cost") is None, f"maliyet sızdı: {r.request.url}"
        # Ham metinde de değer yok (başka bir alan adıyla taşınmasın).
        assert "1234.56" not in r.text and "1234,56" not in r.text


async def test_maliyet_gormeyen_bedel_yazamaz_ve_silemez(
    client, db, kullanici_ac, urun_ac, cihaz_ac
) -> None:
    rma_id = await _kayit(client, db, kullanici_ac, urun_ac, cihaz_ac)
    await _giris(client, "teknik")

    r = await client.post(f"/api/rma/{rma_id}/coz", json={"resolution": "TAMIR", "cost": "10"})
    assert r.status_code == 403
    assert "maliyet.gor" in r.json()["detail"]

    # Bedelsiz çözüm güncellemesi serbest; mevcut bedel KORUNUR.
    r = await client.post(
        f"/api/rma/{rma_id}/coz", json={"resolution": "TAMIR", "resolution_note": "Kart değişti"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["cost"] is None
    db.expire_all()
    assert (await db.get(RmaCase, rma_id)).cost == GIZLI

    # Yetkili kullanıcı aynı kaydı bedeliyle görür.
    await _giris(client, "yonetici")
    r = await client.get(f"/api/rma/{rma_id}")
    assert Decimal(r.json()["cost"]) == GIZLI
