"""Parça tüketim raporu (TS-196, E11-18).

- net çıkış = −Σqty (servis işine yazılmış satırlar; ters kayıt dahil) ve
  aynı süzgeçli hareket defteri toplamına BİREBİR eşit;
- PB ve diğer servis ayrı satırlar;
- `maliyet.gor` yoksa `tutar` anahtarı yanıtta ve Excel'de YOK;
- E07 iş malzeme maliyeti ile raporun iş tutarı aynı;
- maliyeti bilinmeyen satır "maliyet eksik" (0 değil);
- RBAC: `parca.gor + servis_rapor.gor`; Excel ek olarak `servis_rapor.disaaktar`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    MaintenanceContractItem,
    MaintenancePeriod,
    Product,
    StockMovement,
    Warehouse,
)
from app.services.teknik_servis import maliyet as maliyet_svc
from app.services.teknik_servis import parca as parca_svc

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/parca"
RAPOR = f"{URL}/raporlar/tuketim"


async def _istemci(username: str) -> httpx.AsyncClient:
    from app.main import app

    ist = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
    r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text
    return ist


async def _parca(db, kod: str) -> Product:
    u = Product(
        code=kod, name=f"{kod} Parça", type="AKSESUAR", identity_kind="YOK", yedek_parca=True
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _hareket(ist, yol: str, so, depo, urun, adet: int) -> list[dict]:
    r = await ist.post(
        f"{URL}/{yol}",
        json={
            "service_order_id": so.id,
            "depo_id": depo.id,
            "satirlar": [{"product_id": urun.id, "adet": adet}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def ortam(client, db, birimli_kullanici_ac, kullanici_ac, servis_isi_ac, sozlesme_ac):
    """GUVENLIK servis deposu; maliyetli (12,50) ve maliyetsiz iki parça; bir
    arıza ve bir PB işi; depocu (maliyet görmez), admin (görür)."""
    await birimli_kullanici_ac("tk_depocu", "SERVIS_DEPO", ["GUVENLIK"])
    await kullanici_ac("tk_admin", "ADMIN")
    depo = Warehouse(code="TK-SRV", name="TK Servis Deposu", birim="GUVENLIK", servis_deposu=True)
    db.add(depo)
    await db.commit()
    maliyetli = await _parca(db, "TK-1")
    maliyetsiz = await _parca(db, "TK-2")
    ariza = await servis_isi_ac(birim="GUVENLIK")
    sozlesme = await sozlesme_ac()
    an = datetime(2026, 1, 1, tzinfo=UTC)
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=an, sequence_no=1, target_date=an.date()
    )
    db.add_all([kalem, donem])
    await db.commit()
    pb = await servis_isi_ac(
        birim="GUVENLIK", tur="PB", contract_item_id=kalem.id, maintenance_period_id=donem.id
    )
    depocu = await _istemci("tk_depocu")
    admin = await _istemci("tk_admin")
    r = await depocu.post(
        f"{URL}/giris",
        json={
            "depo_id": depo.id,
            "satirlar": [
                {"product_id": maliyetli.id, "adet": 20, "unit_cost": "12.50"},
                {"product_id": maliyetsiz.id, "adet": 5},
            ],
        },
    )
    assert r.status_code == 201, r.text
    await _hareket(depocu, "cikis", ariza, depo, maliyetli, 5)
    await _hareket(depocu, "iade", ariza, depo, maliyetli, 2)
    await _hareket(depocu, "cikis", pb, depo, maliyetli, 4)
    await _hareket(depocu, "cikis", pb, depo, maliyetsiz, 1)

    class Ortam:
        pass

    o = Ortam()
    o.depo, o.maliyetli, o.maliyetsiz, o.ariza, o.pb = depo, maliyetli, maliyetsiz, ariza, pb
    o.depocu, o.admin = depocu, admin
    yield o
    await depocu.aclose()
    await admin.aclose()


async def test_net_cikis_defter_toplamina_esit_ve_pb_ayri(ortam, db) -> None:
    r = await ortam.depocu.get(RAPOR, params={"bas": "2026-01-01", "bit": "2026-01-01"})
    assert r.status_code == 200, r.text
    rapor = r.json()
    satirlar = {(s["urun_kodu"], s["is_grubu"]): s for s in rapor["satirlar"]}
    assert satirlar[("TK-1", "SERVIS")]["net_cikis"] == 3
    assert satirlar[("TK-1", "PLANLI_BAKIM")]["net_cikis"] == 4
    assert satirlar[("TK-2", "PLANLI_BAKIM")]["net_cikis"] == 1
    assert rapor["toplam"]["net_cikis"] == 8
    # Aynı süzgeçli hareket defteri: servis işine bağlı satırların −Σqty'si.
    defter = await db.scalar(
        select(-func.sum(StockMovement.qty)).where(StockMovement.service_order_id.is_not(None))
    )
    assert int(defter) == rapor["toplam"]["net_cikis"]
    # Maliyet görmeyen: tutar anahtarı YOK.
    assert all("tutar" not in s and "maliyet_eksik" not in s for s in rapor["satirlar"])
    assert "tutar" not in rapor["toplam"]
    # İş grubu ve iş türü kırılımları.
    r = await ortam.depocu.get(
        RAPOR, params={"bas": "2026-01-01", "bit": "2026-01-01", "is_grubu": "PLANLI_BAKIM"}
    )
    assert r.json()["toplam"]["net_cikis"] == 5
    r = await ortam.depocu.get(
        RAPOR, params={"bas": "2026-01-01", "bit": "2026-01-01", "kirilim": "is_turu"}
    )
    assert {s["is_turu"]: s["net_cikis"] for s in r.json()["satirlar"]} == {"ARIZA": 3, "PB": 5}
    r = await ortam.depocu.get(RAPOR, params={"kirilim": "birim"})
    assert sum(s["net_cikis"] for s in r.json()["satirlar"]) == 8


async def test_tutar_maliyet_gorurde_ve_e07_ile_ayni(ortam, db) -> None:
    r = await ortam.admin.get(
        RAPOR, params={"bas": "2026-01-01", "bit": "2026-01-01", "kirilim": "is"}
    )
    assert r.status_code == 200, r.text
    rapor = r.json()
    ariza = [s for s in rapor["satirlar"] if s["so_id"] == ortam.ariza.id]
    pb = [s for s in rapor["satirlar"] if s["so_id"] == ortam.pb.id]
    assert [Decimal(s["tutar"]) for s in ariza] == [Decimal("37.50")]
    eksik = next(s for s in pb if s["urun_kodu"] == "TK-2")
    assert eksik["tutar"] is None and eksik["maliyet_eksik"] is True
    finans = await maliyet_svc.is_finansi_toplu(db, [ortam.ariza.id, ortam.pb.id])
    assert finans[ortam.ariza.id].malzeme == Decimal("37.50")
    assert finans[ortam.pb.id].malzeme is None
    tek = await parca_svc.malzeme_maliyeti_toplu(db, [ortam.ariza.id, ortam.pb.id])
    assert tek[ortam.ariza.id] == (finans[ortam.ariza.id].malzeme, "TAM")
    assert tek[ortam.pb.id] == (None, "MALIYET_EKSIK")


async def test_excel_tutar_yalniz_maliyet_gorurde_ve_rbac(ortam, db, birimli_kullanici_ac) -> None:
    r = await ortam.depocu.get(f"{RAPOR}.xlsx", params={"bas": "2026-01-01", "bit": "2026-01-01"})
    assert r.status_code == 200, r.text
    baslik = [h.value for h in load_workbook(BytesIO(r.content)).active[1]]
    assert "Tutar (TL)" not in baslik and "Net Çıkış" in baslik
    r = await ortam.admin.get(f"{RAPOR}.xlsx", params={"bas": "2026-01-01", "bit": "2026-01-01"})
    assert "Tutar (TL)" in [h.value for h in load_workbook(BytesIO(r.content)).active[1]]
    denetim = await db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "parca.tuketim_disa_aktar")
        .order_by(AuditLog.id.desc())
    )
    assert denetim.new_value["bas"] == "2026-01-01"
    # Girdi doğrulama: dönem sırası / 24 ay / bilinmeyen kırılım → 400.
    assert (
        await ortam.admin.get(RAPOR, params={"bas": "2026-02-01", "bit": "2026-01-01"})
    ).status_code == 400
    assert (
        await ortam.admin.get(RAPOR, params={"bas": "2023-01-01", "bit": "2026-01-01"})
    ).status_code == 400
    assert (await ortam.admin.get(RAPOR, params={"kirilim": "yok"})).status_code == 400
    # SERVIS_TEKNISYEN: parca.gor var, servis_rapor.gor yok → 403.
    await birimli_kullanici_ac("tk_tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    tek = await _istemci("tk_tek")
    try:
        assert (await tek.get(RAPOR)).status_code == 403
        assert (await tek.get(f"{RAPOR}.xlsx")).status_code == 403
    finally:
        await tek.aclose()


async def test_baska_birim_tuketimi_gormez(ortam, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("tk_hab", "SERVIS_DEPO", ["HABERLESME"])
    hb = await _istemci("tk_hab")
    try:
        r = await hb.get(RAPOR, params={"bas": "2026-01-01", "bit": "2026-01-01"})
        assert r.status_code == 200
        assert r.json()["satirlar"] == [] and r.json()["toplam"]["net_cikis"] == 0
    finally:
        await hb.aclose()
