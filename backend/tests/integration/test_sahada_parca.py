"""S5 sahada onarımda parça al-ver (KARARLAR_2026-11-09_satis_depo_belge.md S5).

S5.1 araç deposundan anında çıkış + şefin sonradan onayı / reddi (fark kaydı,
zimmet sorusu); S5.2 sökülen parça (karar zorunlu); S5.3 araç ikmali önerisi
ve amir onaylı ikmal talebi (teslim = transfer); S5.4 parça fişi PDF.
Birim ayrımı ve izinler her uçta sunucuda sınanır.
"""

import httpx
import pytest
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import Product, ServicePartUsageReview, ServiceRemovedPart, Warehouse
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
    x.tekn_u = await birimli_kullanici_ac("tekn_g", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_h", "SERVIS_SEF", ["HABERLESME"])
    x.depocu_u = await birimli_kullanici_ac("depo_g", "SERVIS_DEPO", ["GUVENLIK"])
    x.guv = await _depo(db, "SRV-GUV", "GUVENLIK")
    x.hab = await _depo(db, "SRV-HAB", "HABERLESME")
    x.arac = await _depo(db, "ARAC-G", "GUVENLIK", user=x.tekn_u)
    x.urun = Product(
        code="YP-S", name="Saha Parçası", type="AKSESUAR", identity_kind="YOK", yedek_parca=True
    )
    db.add(x.urun)
    await db.commit()
    for depo, adet in ((x.guv, 20), (x.arac, 4), (x.hab, 5)):
        await svc.hareket_yaz(
            db,
            tur="GIRIS",
            satirlar=[svc.Satir(x.urun.id, adet)],
            user=x.depocu_u,
            clock=FakeClock(),
            warehouse_id=depo.id,
        )
    await db.commit()
    x.is_g = await servis_isi_ac(birim="GUVENLIK", atananlar=[x.tekn_u])
    x.tekn = await giris("tekn_g")
    x.sef_g = await giris("sef_g")
    x.sef_h = await giris("sef_h")
    x.depocu = await giris("depo_g")
    return x


async def _arac_cikis(o, adet=1):
    r = await o.tekn.post(
        f"{URL}/cikis",
        json={
            "service_order_id": o.is_g.id,
            "depo_id": o.arac.id,
            "satirlar": [{"product_id": o.urun.id, "adet": adet}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_kullanim_onayi_ve_zimmet(o, db) -> None:
    # Çıkış anında yazılır (iş beklemez); şef sonradan onaylar.
    _arac_ilk = await _arac_cikis(o, 1)
    assert await svc.bakiye(db, o.urun.id, o.arac.id) == 3
    liste = (await o.sef_g.get(f"{URL}/kullanimlar", params={"durum": "BEKLIYOR"})).json()
    assert len(liste) == 1 and liste[0]["kullanan"] == "Tekn_G"
    k1 = liste[0]["id"]
    # Teknisyen onaylayamaz; başka birimin şefi göremez.
    r = await o.tekn.post(f"{URL}/kullanimlar/onayla", json={"kullanim_id": k1})
    assert r.status_code == 403
    r = await o.sef_h.post(f"{URL}/kullanimlar/onayla", json={"kullanim_id": k1})
    assert r.status_code == 404
    assert (await o.sef_h.get(f"{URL}/kullanimlar")).json() == []
    r = await o.sef_g.post(f"{URL}/kullanimlar/onayla", json={"kullanim_id": k1})
    assert r.status_code == 200 and r.json()["durum"] == "ONAYLANDI", r.text

    # İkinci kullanım reddedilir: fark kaydı + zimmet sorusu teknisyene.
    await _arac_cikis(o, 2)
    k2 = (await o.sef_g.get(f"{URL}/kullanimlar", params={"durum": "BEKLIYOR"})).json()[0]["id"]
    r = await o.sef_g.post(f"{URL}/kullanimlar/reddet", json={"kullanim_id": k2})
    assert r.status_code == 422
    r = await o.sef_g.post(
        f"{URL}/kullanimlar/reddet", json={"kullanim_id": k2, "neden": "İş için 1 adet yeterdi"}
    )
    assert r.status_code == 200 and r.json()["zimmet_durumu"] == "ACIK", r.text
    uyari = {
        u["kod"]: u["adet"] for u in (await o.tekn.get("/api/raporlar/uyarilar")).json()["uyarilar"]
    }
    assert uyari.get("parca.zimmet") == 1
    # Zimmeti yalnız kullanan açıklar.
    r = await o.sef_g.post(
        f"{URL}/kullanimlar/zimmet", json={"kullanim_id": k2, "aciklama": "Ben açıklarım"}
    )
    assert r.status_code == 409  # kullanan değil (kural)
    r = await o.tekn.post(
        f"{URL}/kullanimlar/zimmet", json={"kullanim_id": k2, "aciklama": "1 adet araçta duruyor"}
    )
    assert r.status_code == 200 and r.json()["zimmet_durumu"] == "CEVAPLANDI", r.text


async def test_birim_deposundan_cikis_kullanim_kaydi_acmaz(o, db) -> None:
    """Depo/şef çıkışı (araç dışı) onay kaydı açmaz; yalnız teknisyenin araç kullanımı."""
    r = await o.depocu.post(
        f"{URL}/cikis",
        json={
            "service_order_id": o.is_g.id,
            "depo_id": o.guv.id,
            "satirlar": [{"product_id": o.urun.id, "adet": 1}],
        },
    )
    assert r.status_code == 201, r.text
    assert await db.scalar(select(func.count()).select_from(ServicePartUsageReview)) == 0


async def test_sokulen_parca_karar_zorunlu(o, db) -> None:
    govde = {"service_order_id": o.is_g.id, "tanim": "Arızalı anakart", "seri_no": "007"}
    assert (await o.tekn.post(f"{URL}/sokulen", json=govde)).status_code == 422  # karar yok
    r = await o.tekn.post(f"{URL}/sokulen", json={**govde, "karar": "BELIRSIZ"})
    assert r.status_code == 400
    r = await o.tekn.post(f"{URL}/sokulen", json={**govde, "karar": "IADE_TAMIR"})
    assert r.status_code == 400 and "depo" in r.text.lower()  # iadede depo zorunlu
    # Başka birimin deposu görünmez (404).
    r = await o.tekn.post(
        f"{URL}/sokulen", json={**govde, "karar": "IADE_HURDA", "depo_id": o.hab.id}
    )
    assert r.status_code == 404
    r = await o.tekn.post(
        f"{URL}/sokulen", json={**govde, "karar": "IADE_TAMIR", "depo_id": o.guv.id}
    )
    assert r.status_code == 201 and r.json()["seri_no"] == "007", r.text
    sok_id = r.json()["id"]
    r = await o.tekn.post(
        f"{URL}/sokulen", json={**govde, "karar": "MUSTERIDE", "depo_id": o.guv.id}
    )
    assert r.status_code == 201 and r.json()["depo_id"] is None
    liste = (await o.tekn.get(f"{URL}/isler/{o.is_g.id}/sokulen")).json()
    assert [s["karar"] for s in liste] == ["IADE_TAMIR", "MUSTERIDE"]
    # Arızalı parça stoğa girmez; depo teslim alır.
    assert await svc.bakiye(db, o.urun.id, o.guv.id) == 20
    assert (
        await o.tekn.post(f"{URL}/sokulen/teslim", json={"sokulen_id": sok_id})
    ).status_code == 403
    r = await o.depocu.post(f"{URL}/sokulen/teslim", json={"sokulen_id": sok_id})
    assert r.status_code == 200 and r.json()["teslim_alindi"] is True, r.text
    assert await db.scalar(select(func.count()).select_from(ServiceRemovedPart)) == 2


async def test_ikmal_onerisi_ve_amir_onayli_ikmal(o, db) -> None:
    await _arac_cikis(o, 3)  # araçta 1 kaldı, 30 günde 3 tüketildi → öneri 2
    oneri = (await o.tekn.get(f"{URL}/ikmal-onerisi")).json()
    assert len(oneri) == 1 and oneri[0]["onerilen_adet"] == 2 and oneri[0]["bakiye"] == 1
    r = await o.tekn.post(
        f"{URL}/talepler/ikmal",
        json={"hedef_depo_id": o.arac.id, "product_id": o.urun.id, "adet": 2},
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["ikmal"] is True and t["durum"] == "ONAY_BEKLIYOR" and t["depo_id"] == o.guv.id
    assert t["hedef_depo_adi"] == "ARAC-G Deposu"
    # Açık ikmal talebi varken öneri tekrar etmez; ikinci talep 409.
    assert (await o.tekn.get(f"{URL}/ikmal-onerisi")).json() == []
    r = await o.tekn.post(
        f"{URL}/talepler/ikmal",
        json={"hedef_depo_id": o.arac.id, "product_id": o.urun.id, "adet": 1},
    )
    assert r.status_code == 409
    # Başka birimin şefi göremez; kendi şefi onaylar; depo teslim eder (transfer).
    assert (
        await o.sef_h.post(f"{URL}/talepler/onayla", json={"talep_id": t["id"]})
    ).status_code == 404
    r = await o.sef_g.post(f"{URL}/talepler/onayla", json={"talep_id": t["id"]})
    assert r.status_code == 200 and r.json()["durum"] == "ACIK", r.text
    r = await o.depocu.post(f"{URL}/talepler/teslim", json={"talep_id": t["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["talep"]["durum"] == "KARSILANDI"
    assert await svc.bakiye(db, o.urun.id, o.arac.id) == 3
    assert await svc.bakiye(db, o.urun.id, o.guv.id) == 18


async def test_ikmal_yalniz_kendi_aracina(o, db, birimli_kullanici_ac, giris) -> None:
    diger_u = await birimli_kullanici_ac("tekn_g2", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    diger_arac = await _depo(db, "ARAC-G2", "GUVENLIK", user=diger_u)
    r = await o.tekn.post(
        f"{URL}/talepler/ikmal",
        json={"hedef_depo_id": diger_arac.id, "product_id": o.urun.id, "adet": 1},
    )
    assert r.status_code == 404  # başkasının aracı teknisyene görünmez


async def test_parca_fisi_pdf_ve_kapsam(o, db) -> None:
    hareket = (await _arac_cikis(o, 1))[0]
    r = await o.tekn.get(f"{URL}/fis.pdf", params={"hareket_id": hareket["id"]})
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        assert r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    # Bağlam: aynı işlem, iş no, fiyat yok.
    from app.models import User
    from app.services.teknik_servis import sahada_parca

    tekn = await db.get(User, o.tekn_u.id)
    baglam = await sahada_parca.fis_baglami(db, tekn, hareket["id"])
    assert baglam["baslik"] == "PARÇA ÇIKIŞ FİŞİ" and baglam["so_no"] == o.is_g.so_no
    assert baglam["kalemler"] == [{"kod": "YP-S", "ad": "Saha Parçası", "adet": 1, "birim": "ADET"}]
    # Başka birimin şefi fişi göremez.
    r = await o.sef_h.get(f"{URL}/fis.pdf", params={"hareket_id": hareket["id"]})
    assert r.status_code == 404
