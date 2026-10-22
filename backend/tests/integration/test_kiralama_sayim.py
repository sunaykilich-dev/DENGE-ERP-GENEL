"""Kiralama deposu fiziksel sayımı (TS-195, E06-22 b).

Kabul: sayımda eksik çıkan seri ONAYSIZ durum değiştirmez; onaylı satır
KAYIP olur ve `SAYIM` hareketi görünür; toplu fark düzeltilir; aynı depoda
ikinci açık sayım 409; sayım sonrası hareket 409 (+ değişimi kabul); kapsam
dışı sayım 404 ve veri değişmez.
"""

import pytest
from kiralama_ortak import (
    URL,
    bakiye,
    depo_ac,
    istemci,
    kiralik_urun_ac,
    seri_idleri,
    stok_gir,
)
from sqlalchemy import func, select

from app.models import RentalAsset, RentalCount, RentalCountLine, RentalInventoryMovement

pytestmark = pytest.mark.integration


@pytest.fixture
async def ist(client, birimli_kullanici_ac):
    await birimli_kullanici_ac("say_depo", "KIRALAMA_DEPO", ["GUVENLIK"])
    i = await istemci("say_depo")
    yield i
    await i.aclose()


async def _ortam(db, ist):
    depo = await depo_ac(db, "SY-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "SY-SERI", seri=True)
    toplu = await kiralik_urun_ac(db, "SY-TOPLU", seri=False)
    await stok_gir(ist, seri, depo, seriler=["SY-1", "SY-2", "SY-3"])
    await stok_gir(ist, toplu, depo, adet=10)
    return depo, seri, toplu


async def _ac(ist, depo) -> dict:
    r = await ist.post(f"{URL}/sayimlar", json={"depo_id": depo.id})
    assert r.status_code == 201, r.text
    return r.json()


async def _hareket_sayisi(db) -> int:
    return int(await db.scalar(select(func.count()).select_from(RentalInventoryMovement)) or 0)


async def test_onaysiz_fark_degistirmez_onayli_kayip_ve_toplu_duzeltme(ist, db) -> None:
    depo, seri, toplu = await _ortam(db, ist)
    sayim = await _ac(ist, depo)
    # Aynı depoda ikinci açık sayım 409.
    assert (await ist.post(f"{URL}/sayimlar", json={"depo_id": depo.id})).status_code == 409
    r = await ist.put(
        f"{URL}/sayim/satirlar",
        json={
            "sayim_id": sayim["id"],
            "satirlar": [
                {"product_id": seri.id, "seri": "sy-1"},
                {"product_id": seri.id, "seri": "SY-2"},
                {"product_id": seri.id, "seri": "YABANCI-9"},
                {"product_id": toplu.id, "adet": 8},
            ],
        },
    )
    assert r.status_code == 200, r.text
    once = await _hareket_sayisi(db)
    fark = (await ist.get(f"{URL}/sayim/fark", params={"sayim_id": sayim["id"]})).json()
    turler = {r_["anahtar"]: r_["tur"] for r_ in fark["satirlar"]}
    sy3 = max(await seri_idleri(db, seri))
    assert turler[f"S:{sy3}"] == "SAYILMADI"
    assert turler[f"T:{toplu.id}"] == "EKSIK"
    assert "SISTEMDE_YOK" in turler.values()
    # Fark okumak hiçbir şey yazmaz; SY-3 hâlâ HAZIR.
    assert await _hareket_sayisi(db) == once
    assert (await db.get(RentalAsset, sy3, populate_existing=True)).durum == "HAZIR"
    # Bilgi satırı onaylanamaz (400) ve hiçbir şey değişmez.
    bilgi = next(a for a, t in turler.items() if t == "SISTEMDE_YOK")
    r = await ist.post(f"{URL}/sayim/onayla", json={"sayim_id": sayim["id"], "kararlar": [bilgi]})
    assert r.status_code == 400
    assert await _hareket_sayisi(db) == once
    # Yalnız seri satırı onaylanır: SY-3 KAYIP; toplu fark onaysız kalır.
    r = await ist.post(
        f"{URL}/sayim/onayla",
        json={"sayim_id": sayim["id"], "kararlar": [f"S:{sy3}"], "gerekce": "Yıl sonu"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "ONAYLANDI" and len(r.json()["hareketler"]) == 1
    assert (await db.get(RentalAsset, sy3, populate_existing=True)).durum == "KAYIP"
    assert await bakiye(db, toplu, depo, "HAZIR") == 10
    hareket = await db.scalar(
        select(RentalInventoryMovement).where(RentalInventoryMovement.kind == "SAYIM")
    )
    assert hareket.asset_id == sy3 and hareket.to_durum == "KAYIP"
    assert hareket.note.startswith(f"Sayım #{sayim['id']}")
    # Onaylanmış sayım değişmez.
    r = await ist.put(f"{URL}/sayim/satirlar", json={"sayim_id": sayim["id"], "satirlar": []})
    assert r.status_code == 409
    # Yeni sayımda toplu eksik onaylanır: 10 → 8 (2 adet KAYIP).
    s2 = await _ac(ist, depo)
    await ist.put(
        f"{URL}/sayim/satirlar",
        json={"sayim_id": s2["id"], "satirlar": [{"product_id": toplu.id, "adet": 8}]},
    )
    r = await ist.post(
        f"{URL}/sayim/onayla", json={"sayim_id": s2["id"], "kararlar": [f"T:{toplu.id}"]}
    )
    assert r.status_code == 200, r.text
    assert await bakiye(db, toplu, depo, "HAZIR") == 8
    assert await bakiye(db, toplu, None, "KAYIP") == 2


async def test_toplu_fazla_kontrolde_ve_sayim_sonrasi_hareket_409(client, ist, db) -> None:
    depo, _, toplu = await _ortam(db, ist)
    sayim = await _ac(ist, depo)
    await ist.put(
        f"{URL}/sayim/satirlar",
        json={"sayim_id": sayim["id"], "satirlar": [{"product_id": toplu.id, "adet": 12}]},
    )
    client.clock.advance(minutes=5)
    await stok_gir(ist, toplu, depo, adet=1)  # sayım sürerken giriş
    govde = {"sayim_id": sayim["id"], "kararlar": [f"T:{toplu.id}"]}
    r = await ist.post(f"{URL}/sayim/onayla", json=govde)
    assert r.status_code == 409, r.text
    assert f"T:{toplu.id}" in r.json()["detail"]["etkilenen"]
    r = await ist.post(f"{URL}/sayim/onayla", json={**govde, "degisimi_kabul": True})
    assert r.status_code == 200, r.text
    # Fark güncel bakiyeyle: 12 − 11 = 1 adet KONTROLDE'ye girer.
    assert await bakiye(db, toplu, depo, "HAZIR") == 11
    assert await bakiye(db, toplu, depo, "KONTROLDE") == 1


async def test_iptal_ve_kapsam_disi_404(ist, db, birimli_kullanici_ac) -> None:
    depo, seri, _ = await _ortam(db, ist)
    sayim = await _ac(ist, depo)
    await birimli_kullanici_ac("say_hab", "KIRALAMA_DEPO", ["HABERLESME"])
    hb = await istemci("say_hab")
    try:
        kayit = await db.get(RentalCount, sayim["id"])
        surum = kayit.version
        assert (await hb.get(f"{URL}/sayim", params={"sayim_id": sayim["id"]})).status_code == 404
        r = await hb.put(
            f"{URL}/sayim/satirlar",
            json={"sayim_id": sayim["id"], "satirlar": [{"product_id": seri.id, "seri": "X"}]},
        )
        assert r.status_code == 404
        r = await hb.post(
            f"{URL}/sayim/iptal", json={"sayim_id": sayim["id"], "gerekce": "Başkası"}
        )
        assert r.status_code == 404
        assert (await hb.post(f"{URL}/sayimlar", json={"depo_id": depo.id})).status_code == 404
        r = await hb.get(f"{URL}/sayimlar")
        assert r.status_code == 200 and r.json() == []
        await db.refresh(kayit)
        assert kayit.version == surum and kayit.durum == "ACIK"
        satir_sayisi = await db.scalar(
            select(func.count())
            .select_from(RentalCountLine)
            .where(RentalCountLine.rental_count_id == kayit.id)
        )
        assert satir_sayisi == 0
    finally:
        await hb.aclose()
    # Gerekçesiz iptal 400; gerekçeli iptal; sonra yeni sayım açılabilir.
    r = await ist.post(f"{URL}/sayim/iptal", json={"sayim_id": sayim["id"], "gerekce": " "})
    assert r.status_code == 400
    r = await ist.post(f"{URL}/sayim/iptal", json={"sayim_id": sayim["id"], "gerekce": "Hata"})
    assert r.status_code == 200 and r.json()["durum"] == "IPTAL"
    await _ac(ist, depo)


async def test_sayim_rbac(client, db, birimli_kullanici_ac) -> None:
    # SERVIS_OPERASYON: kiralama.gor var, kiralama.envanter yok.
    await birimli_kullanici_ac("say_ops", "SERVIS_OPERASYON", ["GUVENLIK"])
    o = await istemci("say_ops")
    try:
        assert (await o.get(f"{URL}/sayimlar")).status_code == 200
        assert (await o.post(f"{URL}/sayimlar", json={"depo_id": 1})).status_code == 403
        r = await o.post(f"{URL}/sayim/onayla", json={"sayim_id": 1, "kararlar": []})
        assert r.status_code == 403
    finally:
        await o.aclose()
