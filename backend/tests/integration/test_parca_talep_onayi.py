"""Parça talebi amir onayı (kullanıcı isteği 2026-11-09).

"Teknisyenler yedek parça taleplerini sistem üzerinden amir onayı ile depodan
talep edebilsin." Akış: teknisyen işin biriminin deposundan ister
(ONAY_BEKLIYOR) → şef tek adımda onaylar (ACIK) ya da gerekçeyle reddeder
(REDDEDILDI) → depo teslim eder (çıkış, KARSILANDI). Sınananlar: birim
ayrımı (başka birimin şefi/deposu 404), izinler (teknisyen onaylayamaz,
şef teslim edemez), teknisyenin onayı dolanamaması (birim deposundan doğrudan
çıkış 403), red gerekçesinin teknisyene görünmesi, uyarılar.
"""

import httpx
import pytest
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import Product, ServicePartRequest, StockMovement, Warehouse
from app.services.teknik_servis import parca as svc

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/parca"


@pytest.fixture
async def giris(client):
    from app.main import app

    acik: list[httpx.AsyncClient] = []

    async def _ac(username: str) -> httpx.AsyncClient:
        ist = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Requested-With": "fetch"},
        )
        r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
        assert r.status_code == 200, r.text
        acik.append(ist)
        return ist

    yield _ac
    for ist in acik:
        await ist.aclose()


async def _depo(db, code, birim, *, user=None) -> Warehouse:
    w = Warehouse(
        code=code,
        name=f"{code} Deposu",
        birim=birim,
        servis_deposu=True,
        location_type="TEKNISYEN" if user is not None else "BOLGE_DEPO",
        user_id=user.id if user is not None else None,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


class Ortam:
    pass


@pytest.fixture
async def o(db, birimli_kullanici_ac, servis_isi_ac, giris):
    x = Ortam()
    x.tekn_u = await birimli_kullanici_ac("tekn_h", "SERVIS_TEKNISYEN", ["HABERLESME"])
    await birimli_kullanici_ac("sef_h", "SERVIS_SEF", ["HABERLESME"])
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    x.depocu_u = await birimli_kullanici_ac("depo_h", "SERVIS_DEPO", ["HABERLESME"])
    x.hab = await _depo(db, "SRV-HAB", "HABERLESME")
    x.guv = await _depo(db, "SRV-GUV", "GUVENLIK")
    x.arac = await _depo(db, "ARAC-H", "HABERLESME", user=x.tekn_u)
    x.urun = Product(
        code="YP-T", name="Talep Parçası", type="AKSESUAR", identity_kind="YOK", yedek_parca=True
    )
    db.add(x.urun)
    await db.commit()
    for depo in (x.hab, x.guv, x.arac):
        await svc.hareket_yaz(
            db,
            tur="GIRIS",
            satirlar=[svc.Satir(x.urun.id, 10)],
            user=x.depocu_u,
            clock=FakeClock(),
            warehouse_id=depo.id,
        )
    await db.commit()
    x.is_h = await servis_isi_ac(birim="HABERLESME", atananlar=[x.tekn_u])
    x.tekn = await giris("tekn_h")
    x.sef_h = await giris("sef_h")
    x.sef_g = await giris("sef_g")
    x.depocu = await giris("depo_h")
    return x


async def _talep(o, adet=2, **ek):
    return await o.tekn.post(
        f"{URL}/talepler",
        json={"service_order_id": o.is_h.id, "product_id": o.urun.id, "adet": adet, **ek},
    )


async def _hareket_sayisi(db) -> int:
    return await db.scalar(select(func.count()).select_from(StockMovement))


async def test_onay_ve_teslim_akisi(o, db) -> None:
    r = await _talep(o)
    assert r.status_code == 201, r.text
    t = r.json()
    # Depo seçilmedi: işin biriminin TEK deposu (araç deposu hariç).
    assert t["durum"] == "ONAY_BEKLIYOR" and t["depo_id"] == o.hab.id
    assert t["talep_eden"] == "Tekn_H"
    # Teknisyen kendi talebini görür; onaylayamaz (403).
    benim = (await o.tekn.get(f"{URL}/talepler", params={"benim": True})).json()
    assert [x["id"] for x in benim] == [t["id"]]
    assert (
        await o.tekn.post(f"{URL}/talepler/onayla", json={"talep_id": t["id"]})
    ).status_code == 403
    # Onaysız talep teslim edilemez.
    r = await o.depocu.post(f"{URL}/talepler/teslim", json={"talep_id": t["id"]})
    assert r.status_code == 409
    # Şefe uyarı düşer.
    uyari = {
        u["kod"]: u["adet"]
        for u in (await o.sef_h.get("/api/raporlar/uyarilar")).json()["uyarilar"]
    }
    assert uyari.get("parca.talep_onay") == 1
    # Şef onaylar (tek adım); ikinci onay 409.
    r = await o.sef_h.post(f"{URL}/talepler/onayla", json={"talep_id": t["id"]})
    assert r.status_code == 200 and r.json()["durum"] == "ACIK", r.text
    assert r.json()["onaylayan"] == "Sef_H"
    assert (
        await o.sef_h.post(f"{URL}/talepler/onayla", json={"talep_id": t["id"]})
    ).status_code == 409
    # Şef teslim edemez (parca.yonet yok).
    assert (
        await o.sef_h.post(f"{URL}/talepler/teslim", json={"talep_id": t["id"]})
    ).status_code == 403
    uyari = {
        u["kod"]: u["adet"]
        for u in (await o.depocu.get("/api/raporlar/uyarilar")).json()["uyarilar"]
    }
    assert uyari.get("parca.talep_teslim") == 1
    # Depo teslim eder: talep deposundan işe çıkış, talep karşılandı.
    r = await o.depocu.post(f"{URL}/talepler/teslim", json={"talep_id": t["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["talep"]["durum"] == "KARSILANDI"
    assert await svc.bakiye(db, o.urun.id, o.hab.id) == 8
    assert await svc.net_cikis(db, o.is_h.id, o.urun.id) == 2


async def test_red_gerekceli_ve_teknisyen_gorur(o, db) -> None:
    t = (await _talep(o)).json()
    r = await o.sef_h.post(f"{URL}/talepler/reddet", json={"talep_id": t["id"]})
    assert r.status_code == 422  # gerekçe zorunlu
    r = await o.sef_h.post(
        f"{URL}/talepler/reddet", json={"talep_id": t["id"], "neden": "Araçta muadili var"}
    )
    assert r.status_code == 200 and r.json()["durum"] == "REDDEDILDI", r.text
    satir = (await o.tekn.get(f"{URL}/talepler")).json()[0]
    assert satir["durum"] == "REDDEDILDI" and satir["red_nedeni"] == "Araçta muadili var"
    # Reddedilen talep onaylanamaz/teslim edilemez; aynı parça yeniden istenebilir.
    assert (
        await o.sef_h.post(f"{URL}/talepler/onayla", json={"talep_id": t["id"]})
    ).status_code == 409
    assert (await _talep(o)).status_code == 201


async def test_baska_birimin_sefi_ve_deposu_404(o, db) -> None:
    t = (await _talep(o)).json()
    once = await db.scalar(select(ServicePartRequest.durum).where(ServicePartRequest.id == t["id"]))
    for yol, govde in (
        ("onayla", {"talep_id": t["id"]}),
        ("reddet", {"talep_id": t["id"], "neden": "Başka birim"}),
    ):
        r = await o.sef_g.post(f"{URL}/talepler/{yol}", json=govde)
        assert r.status_code == 404, (yol, r.text)
    assert (await o.sef_g.get(f"{URL}/talepler")).json() == []
    durum = await db.scalar(
        select(ServicePartRequest.durum).where(ServicePartRequest.id == t["id"])
    )
    assert durum == once == "ONAY_BEKLIYOR"
    # Teknisyen başka birimin deposundan talep edemez (görünmez: 404); araç
    # deposundan talep anlamsız (400).
    await o.tekn.post(f"{URL}/talepler/iptal", json={"talep_id": t["id"], "neden": "Yeniden"})
    assert (await _talep(o, depo_id=o.guv.id)).status_code == 404
    assert (await _talep(o, depo_id=o.arac.id)).status_code == 400


async def test_teknisyen_onayi_dolanamaz(o, db) -> None:
    """Birim deposundan doğrudan çıkış 403 (veri değişmez); araç deposundan serbest."""
    once = await _hareket_sayisi(db)
    govde = {
        "service_order_id": o.is_h.id,
        "depo_id": o.hab.id,
        "satirlar": [{"product_id": o.urun.id, "adet": 1}],
    }
    r = await o.tekn.post(f"{URL}/cikis", json=govde)
    assert r.status_code == 403, r.text
    assert await _hareket_sayisi(db) == once
    r = await o.tekn.post(f"{URL}/cikis", json={**govde, "depo_id": o.arac.id})
    assert r.status_code == 201, r.text


async def test_sefin_kendi_talebi_dogrudan_onayli(o, servis_isi_ac) -> None:
    so = await servis_isi_ac(birim="HABERLESME")
    r = await o.sef_h.post(
        f"{URL}/talepler", json={"service_order_id": so.id, "product_id": o.urun.id, "adet": 1}
    )
    assert r.status_code == 201 and r.json()["durum"] == "ACIK", r.text
    assert r.json()["onaylayan"] == "Sef_H"


async def test_birden_cok_depoda_secim_istenir(o, db) -> None:
    await _depo(db, "SRV-HAB2", "HABERLESME")
    r = await _talep(o)
    assert r.status_code == 400 and "depo" in r.text.lower()
    r = await _talep(o, depo_id=o.hab.id)
    assert r.status_code == 201 and r.json()["depo_id"] == o.hab.id


async def test_teknisyen_urun_katalogunu_goremez(o) -> None:
    """Menüden kaldırılan Ürün Kataloğu API'de de kapalı (urun.gor yok)."""
    assert (await o.tekn.get("/api/urunler")).status_code == 403
