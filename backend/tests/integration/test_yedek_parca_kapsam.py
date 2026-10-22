"""Yedek parça kapsamı: depo kümesi, teknisyen araç deposu, kapsam dışı kimlik 404 +
veri değişmedi, liste/KPI/uyarı sayısı (TS-131, TS-133, plan §4.5)."""

import httpx
import pytest
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import (
    AuditLog,
    Product,
    ServicePartRequest,
    StockCount,
    StockMovement,
    Warehouse,
)
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


async def _depo(db, code, *, birim=None, user=None) -> Warehouse:
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


async def _parca(db, code, **kw) -> Product:
    u = Product(
        code=code,
        name=f"{code} Parça",
        type="AKSESUAR",
        identity_kind="YOK",
        yedek_parca=True,
        **kw,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _yaz(db, user, tur, depo, urun, adet, **kw):
    hareketler = await svc.hareket_yaz(
        db,
        tur=tur,
        satirlar=[svc.Satir(urun.id, adet)],
        user=user,
        clock=FakeClock(),
        warehouse_id=depo.id,
        **kw,
    )
    await db.commit()
    return hareketler


class Ortam:
    pass


@pytest.fixture
async def o(db, birimli_kullanici_ac, servis_isi_ac, giris):
    """GUVENLIK depocusu ve teknisyeni; HABERLESME deposu ve işi (kapsam dışı)."""
    x = Ortam()
    x.depocu_u = await birimli_kullanici_ac("depo_g", "SERVIS_DEPO", ["GUVENLIK"])
    x.tekn_u = await birimli_kullanici_ac("tekn_g", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    x.tekn2_u = await birimli_kullanici_ac("tekn_g2", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    x.ortak = await _depo(db, "SRV-ORTAK")
    x.guv = await _depo(db, "SRV-GUV", birim="GUVENLIK")
    x.hab = await _depo(db, "SRV-HAB", birim="HABERLESME")
    x.arac1 = await _depo(db, "ARAC-1", birim="GUVENLIK", user=x.tekn_u)
    x.arac2 = await _depo(db, "ARAC-2", birim="GUVENLIK", user=x.tekn2_u)
    x.urun = await _parca(db, "YP-K", min_stok=5)
    for depo in (x.ortak, x.guv, x.hab, x.arac1, x.arac2):
        await _yaz(db, x.depocu_u, "GIRIS", depo, x.urun, 3)
    x.is_guv = await servis_isi_ac(birim="GUVENLIK", atananlar=[x.tekn_u])
    x.is_hab = await servis_isi_ac(birim="HABERLESME")
    x.depocu = await giris("depo_g")
    x.tekn = await giris("tekn_g")
    return x


async def _anlik(db) -> dict:
    # Sayım sorguları DB'den okunur (kimlik haritasına bakmaz).
    return {
        "hareket": await db.scalar(select(func.count()).select_from(StockMovement)),
        "toplam": await db.scalar(select(func.coalesce(func.sum(StockMovement.qty), 0))),
        "talep": await db.scalar(select(func.count()).select_from(ServicePartRequest)),
        "sayim": await db.scalar(select(func.count()).select_from(StockCount)),
        "denetim": await db.scalar(select(func.count()).select_from(AuditLog)),
    }


async def test_depo_kumeleri(o, db, birimli_kullanici_ac, giris) -> None:
    kodlar = lambda r: sorted(d["code"] for d in r.json())  # noqa: E731
    assert kodlar(await o.depocu.get(f"{URL}/depolar")) == [
        "ARAC-1",
        "ARAC-2",
        "SRV-GUV",
        "SRV-ORTAK",
    ]
    # Teknisyen: ortak + birim depoları + KENDİ araç deposu; başkasınınki yok.
    r = await o.tekn.get(f"{URL}/depolar")
    assert kodlar(r) == ["ARAC-1", "SRV-GUV", "SRV-ORTAK"]
    assert [d["kendi_araci"] for d in r.json() if d["code"] == "ARAC-1"] == [True]
    # Birimsiz birim kapsamlı kullanıcı hiçbir depo görmez (fail-closed).
    await birimli_kullanici_ac("depo_bos", "SERVIS_DEPO", [])
    bos = await giris("depo_bos")
    assert (await bos.get(f"{URL}/depolar")).json() == []
    assert (await bos.get(f"{URL}/stok")).json()[0]["toplam"] == 0


async def test_stok_toplami_ve_uyari_kapsamli(o) -> None:
    # Depocu: ortak+guv+arac1+arac2 = 12 (HAB'daki 3 sayılmaz); asgari 5 → YETERLI.
    satir = (await o.depocu.get(f"{URL}/stok")).json()[0]
    assert satir["toplam"] == 12 and "SRV-HAB" not in [d["depo_kodu"] for d in satir["depolar"]]
    # Teknisyen: ortak+guv+arac1 = 9.
    assert (await o.tekn.get(f"{URL}/stok")).json()[0]["toplam"] == 9


async def test_kapsam_disi_depodan_cikis_404_veri_degismez(o, db) -> None:
    for depo in (o.hab, o.arac2):
        once = await _anlik(db)
        r = await o.tekn.post(
            f"{URL}/cikis",
            json={
                "service_order_id": o.is_guv.id,
                "depo_id": depo.id,
                "satirlar": [{"product_id": o.urun.id, "adet": 1}],
            },
        )
        assert r.status_code == 404, r.text
        assert await _anlik(db) == once
    r = await o.tekn.post(
        f"{URL}/cikis",
        json={
            "service_order_id": o.is_guv.id,
            "depo_id": o.arac1.id,
            "satirlar": [{"product_id": o.urun.id, "adet": 1}],
        },
    )
    assert r.status_code == 201, r.text


async def test_atanmadigi_ise_cikis_404(o, db, servis_isi_ac) -> None:
    atanmamis = await servis_isi_ac(birim="GUVENLIK")
    for so in (atanmamis, o.is_hab):
        once = await _anlik(db)
        r = await o.tekn.post(
            f"{URL}/cikis",
            json={
                "service_order_id": so.id,
                "depo_id": o.arac1.id,
                "satirlar": [{"product_id": o.urun.id, "adet": 1}],
            },
        )
        assert r.status_code == 404
        r = await o.tekn.post(
            f"{URL}/talepler",
            json={"service_order_id": so.id, "product_id": o.urun.id, "adet": 1},
        )
        assert r.status_code == 404
        assert await _anlik(db) == once


async def test_kimlikli_uclarda_kapsam_disi_404(o, db, kullanici_ac) -> None:
    """URL'deki hareket/sayım/talep/depo/iş başka birimde → 404 ve hiçbir şey yazılmaz."""
    hab_hareket = (await _yaz(db, o.depocu_u, "ZAYI", o.hab, o.urun, 1, notes="Kırık"))[0]
    # Ortak depoda AMA başka birimin işine bağlı hareket de görünmez.
    hab_cikis = (
        await svc.cikis_yap(
            db,
            so=o.is_hab,
            depo=o.ortak,
            satirlar=[svc.Satir(o.urun.id, 1)],
            user=o.depocu_u,
            clock=FakeClock(),
        )
    )[0]
    await db.commit()
    sayim = await svc.sayim_ac(db, depo=o.hab, user=o.depocu_u, clock=FakeClock())
    talep = await svc.talep_ac(
        db, so=o.is_hab, product_id=o.urun.id, adet=1, user=o.depocu_u, clock=FakeClock()
    )
    await db.commit()
    gizli = {hab_hareket.id, hab_cikis.id}
    istekler = [
        ("POST", f"{URL}/ters-kayit", {"hareket_id": hab_hareket.id, "gerekce": "Deneme"}),
        ("POST", f"{URL}/ters-kayit", {"hareket_id": hab_cikis.id, "gerekce": "Deneme"}),
        ("GET", f"{URL}/sayim?sayim_id={sayim.id}", None),
        (
            "PUT",
            f"{URL}/sayim/satirlar",
            {"sayim_id": sayim.id, "satirlar": [{"product_id": o.urun.id, "sayilan_adet": 0}]},
        ),
        ("POST", f"{URL}/sayim/onayla", {"sayim_id": sayim.id, "gerekce": "Deneme"}),
        ("POST", f"{URL}/sayim/iptal", {"sayim_id": sayim.id, "gerekce": "Deneme"}),
        ("POST", f"{URL}/talepler/iptal", {"talep_id": talep.id, "neden": "Deneme"}),
        ("GET", f"{URL}/isler/{o.is_hab.id}/parcalar", None),
    ]
    for yontem, yol, govde in istekler:
        once = await _anlik(db)
        r = await o.depocu.request(yontem, yol, json=govde)
        assert r.status_code == 404, (yol, r.status_code, r.text)
        assert await _anlik(db) == once, yol
    # Listelerde de yok: hareket (ortak depodaki HAB işi dahil), sayım, talep.
    hareketler = (await o.depocu.get(f"{URL}/hareketler")).json()
    assert {h["id"] for h in hareketler}.isdisjoint(gizli)
    assert (await o.depocu.get(f"{URL}/sayimlar")).json() == []
    assert (await o.depocu.get(f"{URL}/talepler")).json() == []
    ozet = (await o.depocu.get(f"{URL}/stok/ozet")).json()
    assert ozet["acik_sayim"] == 0 and ozet["acik_talep"] == 0


async def test_depo_tanimi_kapsam(o, db, birimli_kullanici_ac, rol_ac, giris) -> None:
    await rol_ac("T_AYAR_GUV", ["sistem.ayar", "parca.gor"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("ayarci", "T_AYAR_GUV", ["GUVENLIK"])
    ayarci = await giris("ayarci")
    r = await ayarci.patch(f"{URL}/depolar", json={"depo_id": o.hab.id, "name": "Ele geçir"})
    assert r.status_code == 404
    await db.refresh(o.hab)
    assert o.hab.name == "SRV-HAB Deposu"
    # Kendi depoyu başka birime taşıyamaz.
    r = await ayarci.patch(f"{URL}/depolar", json={"depo_id": o.guv.id, "birim": "HABERLESME"})
    assert r.status_code == 404
    r = await ayarci.post(f"{URL}/depolar", json={"code": "SRV-YENI", "name": "Yeni Depo"})
    assert r.status_code == 201
    yeni = await db.scalar(select(Warehouse).where(Warehouse.code == "SRV-YENI"))
    assert yeni.servis_deposu and not yeni.kiralama_deposu
