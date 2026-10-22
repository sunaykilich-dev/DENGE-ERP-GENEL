"""Satın alma mal kabulünden serisiz parça girişi (TS-196, E11-D02).

Kabul: serisiz kalemde 10 adet kabulden sonra servis deposu bakiyesi +10,
maliyet TL'ye çevrilmiş olarak DONDURULUR (`unit_cost`), `qty_received` 10;
kalan adetten fazlası 409; mobilite deposuna canlı `GIRIS` hareketi; kiralama
deposu 409; IMEI dalı değişmez (`test_satinalma.py`).
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Account, PurchaseOrderLine, StockMovement, Warehouse
from app.services.teknik_servis import parca as parca_svc

pytestmark = pytest.mark.integration

URL = "/api/satinalma/siparisler"


async def _ortam(client, db, kullanici_ac, urun_ac, *, doviz="USD", kur="32.5"):
    await kullanici_ac("sa_admin", "ADMIN")
    r = await client.post(
        "/api/auth/login", json={"username": "sa_admin", "password": "parola1234"}
    )
    assert r.status_code == 200
    tedarikci = Account(title="PARCA TEDARIK", title_key="parca tedarik", is_tedarikci=True)
    servis = Warehouse(code="SA-SRV", name="Servis Deposu", servis_deposu=True, birim="GUVENLIK")
    mobil = Warehouse(code="SA-MOB", name="Mobilite Deposu")
    kiralik = Warehouse(code="SA-KIR", name="Kiralık Deposu", kiralama_deposu=True)
    db.add_all([tedarikci, servis, mobil, kiralik])
    await db.commit()
    parca = await urun_ac("SA-PARCA", "YOK", yedek_parca=True, type="AKSESUAR")
    govde = {
        "supplier_id": tedarikci.id,
        "currency": doviz,
        "kalemler": [{"product_id": parca.id, "qty": 15, "unit_price": "2.40"}],
    }
    if kur is not None:
        govde["fx_rate"] = kur
    r = await client.post(URL, json=govde)
    assert r.status_code == 201, r.text
    s = r.json()
    r = await client.post(f"{URL}/{s['id']}/durum", json={"durum": "SIPARIS_VERILDI"})
    assert r.status_code == 200, r.text
    return r.json(), parca, servis, mobil, kiralik


async def test_serisiz_kabul_servis_deposuna_maliyetle(client, db, kullanici_ac, urun_ac) -> None:
    s, parca, servis, _, _ = await _ortam(client, db, kullanici_ac, urun_ac)
    kalem_id = s["kalemler"][0]["id"]
    r = await client.post(
        f"{URL}/{s['id']}/mal-kabul",
        json={"kalem_id": kalem_id, "adet": 10, "warehouse_id": servis.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["adet"] == 10 and r.json()["siparis"]["status"] == "KISMI_TESLIM"
    assert await parca_svc.bakiye(db, parca.id, servis.id) == 10
    hareket = await db.scalar(
        select(StockMovement).where(
            StockMovement.product_id == parca.id, StockMovement.warehouse_id == servis.id
        )
    )
    assert hareket.hareket_turu == "GIRIS" and hareket.document_no == r.json()["fis_no"]
    # 2,40 USD × 32,5 = 78,00 TL (hareket anında dondurulur).
    assert hareket.unit_cost == Decimal("78.0000")
    kalem = await db.get(PurchaseOrderLine, kalem_id, populate_existing=True)
    assert kalem.qty_received == Decimal("10")
    # Kalandan (5) fazlası 409; hiçbir şey yazılmaz.
    r = await client.post(
        f"{URL}/{s['id']}/mal-kabul",
        json={"kalem_id": kalem_id, "adet": 6, "warehouse_id": servis.id},
    )
    assert r.status_code == 409
    assert await parca_svc.bakiye(db, parca.id, servis.id) == 10
    # Serisiz kaleme kimlik listesi 409, adetsiz/kimliksiz 400.
    r = await client.post(
        f"{URL}/{s['id']}/mal-kabul", json={"kalem_id": kalem_id, "kimlikler": ["X-1"]}
    )
    assert r.status_code == 409
    r = await client.post(f"{URL}/{s['id']}/mal-kabul", json={"kalem_id": kalem_id})
    assert r.status_code == 400


async def test_serisiz_kabul_mobilite_ve_kiralama_deposu(client, db, kullanici_ac, urun_ac) -> None:
    s, parca, _, mobil, kiralik = await _ortam(client, db, kullanici_ac, urun_ac, doviz="TRY")
    kalem_id = s["kalemler"][0]["id"]
    r = await client.post(
        f"{URL}/{s['id']}/mal-kabul",
        json={"kalem_id": kalem_id, "adet": 3, "warehouse_id": kiralik.id},
    )
    assert r.status_code == 409
    r = await client.post(
        f"{URL}/{s['id']}/mal-kabul",
        json={"kalem_id": kalem_id, "adet": 3, "warehouse_id": mobil.id},
    )
    assert r.status_code == 200, r.text
    hareket = await db.scalar(select(StockMovement).where(StockMovement.warehouse_id == mobil.id))
    # Mobilite deposu: canlı hareket (servis türü ve maliyet YOK).
    assert hareket.qty == 3 and hareket.reason == "GIRIS"
    assert hareket.hareket_turu is None and hareket.unit_cost is None


async def test_kursuz_doviz_maliyeti_bilinmiyor(client, db, kullanici_ac, urun_ac) -> None:
    s, parca, servis, _, _ = await _ortam(client, db, kullanici_ac, urun_ac, kur=None)
    r = await client.post(
        f"{URL}/{s['id']}/mal-kabul",
        json={"kalem_id": s["kalemler"][0]["id"], "adet": 2, "warehouse_id": servis.id},
    )
    assert r.status_code == 200, r.text
    hareket = await db.scalar(select(StockMovement).where(StockMovement.warehouse_id == servis.id))
    # Kur yoksa maliyet bilinmiyor: NULL ("maliyet eksik"), 0 yazılmaz.
    assert hareket.unit_cost is None


async def test_satinalma_yetkisi(client, db, kullanici_ac) -> None:
    await kullanici_ac("sa_teknik", "TEKNIK_SERVIS")
    await client.post("/api/auth/login", json={"username": "sa_teknik", "password": "parola1234"})
    r = await client.post(f"{URL}/1/mal-kabul", json={"kalem_id": 1, "adet": 1})
    assert r.status_code == 403
