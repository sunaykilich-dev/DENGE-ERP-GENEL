"""Depo ayrımı ve mobilite ile çift envanter önlemi (TS-111, E06-D01/D04/D05).

Kiralama tarafı: kiralık envanter yalnız `kiralama_deposu=true` depoya yazılır;
mobilite ya da servis deposu 400; depo birimi kaydın birimiyle uyumlu olmalı;
IMEI'li ürün ve MOBILITE/ARAC_TAKIP birimi kiralık envantere giremez.
(Mobilite uçlarının kiralama deposunu reddetmesi TS-131'dir, D2-D.)
"""

import pytest
from kiralama_ortak import (
    URL,
    depo_ac,
    istemci,
    kalem_id,
    kiralama_ac,
    kiralik_urun_ac,
    musteri_ac,
    planla,
    stok_gir,
)
from sqlalchemy import func, select

from app.models import RentalAllocation, RentalCatalogItem

pytestmark = pytest.mark.integration


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("dep_yon", "SERVIS_YONETICI")
    i = await istemci("dep_yon")
    yield i
    await i.aclose()


async def test_mobilite_ve_servis_deposu_kiralamada_kullanilamaz(ist, db) -> None:
    mobilite = await depo_ac(db, "MOB-MERKEZ", kiralama=False)
    servis = await depo_ac(db, "SRV-PARCA", birim="GUVENLIK", kiralama=False, servis=True)
    kiralama = await depo_ac(db, "KIR-DEPO-1", birim="GUVENLIK")
    toplu = await kiralik_urun_ac(db, "DA-BARIYER", seri=False)
    for depo in (mobilite, servis):
        r = await ist.post(
            f"{URL}/envanter", json={"product_id": toplu.id, "depo_id": depo.id, "adet": 5}
        )
        assert r.status_code == 400, r.text
    await stok_gir(ist, toplu, kiralama, adet=5)
    r = await ist.post(
        f"{URL}/envanter/transfer",
        json={
            "hedef_depo_id": mobilite.id,
            "product_id": toplu.id,
            "kaynak_depo_id": kiralama.id,
            "adet": 1,
        },
    )
    assert r.status_code == 400
    k = await kiralama_ac(ist, await musteri_ac(db), [(toplu, 2)])
    await planla(ist, k)
    r = await ist.post(
        f"{URL}/{k['id']}/tahsis",
        json={"satirlar": [{"kalem_id": kalem_id(k, toplu), "depo_id": mobilite.id, "adet": 2}]},
    )
    assert r.status_code == 400
    assert await db.scalar(select(func.count()).select_from(RentalAllocation)) == 0
    # Kiralama depo listesi yalnız kiralama depoları.
    kodlar = {d["code"] for d in (await ist.get(f"{URL}/depolar")).json()}
    assert kodlar == {"KIR-DEPO-1"}


async def test_depo_birimi_kayit_birimiyle_uyumlu_olmali(ist, db) -> None:
    hab_depo = await depo_ac(db, "KIR-HAB", birim="HABERLESME")
    ortak = await depo_ac(db, "KIR-ORTAK")
    guv = await kiralik_urun_ac(db, "DB-GUV", seri=False, birim="GUVENLIK")
    r = await ist.post(
        f"{URL}/envanter", json={"product_id": guv.id, "depo_id": hab_depo.id, "adet": 1}
    )
    assert r.status_code == 400
    await stok_gir(ist, guv, ortak, adet=1)  # birimsiz ortak depo kabul


async def test_imei_urun_ve_mobilite_birimi_kiralik_envantere_girmez(ist, db, urun_ac) -> None:
    imei = await urun_ac("DB-IMEI", "IMEI")
    toplu = await urun_ac("DB-T", "YOK")
    r = await ist.post(f"{URL}/katalog", json={"product_id": imei.id, "birim": "GUVENLIK"})
    assert r.status_code == 400
    for birim in ("MOBILITE", "ARAC_TAKIP"):
        r = await ist.post(f"{URL}/katalog", json={"product_id": toplu.id, "birim": birim})
        assert r.status_code == 400, (birim, r.text)
    assert await db.scalar(select(func.count()).select_from(RentalCatalogItem)) == 0
    r = await ist.post(f"{URL}/katalog", json={"product_id": toplu.id, "birim": "POC"})
    assert r.status_code == 201, r.text
    musteri = await musteri_ac(db)
    await kiralama_ac(ist, musteri, [(toplu, 1)], birim="ARAC_TAKIP", beklenen=400)
    k = await kiralama_ac(ist, musteri, [(toplu, 1)], birim="POC")
    assert k["birim"] == "POC"
