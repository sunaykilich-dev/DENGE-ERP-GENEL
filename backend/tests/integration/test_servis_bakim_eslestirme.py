"""Sözleşme–ekipman ilk eşleştirmesi (TS-063, E03-D03).

Sistem önerir, şef onaylar: türde TEK aday kalan kaleme öneri konur, birden
çok aday listede kalır (sistem tahmin etmez). Otomatik PB üretimi
eşleştirme %100 olmadan açılamaz (409): eksik eşleşmeyle açılırsa worker
ekipmansız kalemleri sessizce atlar ve dönem eksik PB'yle başlar.
"""

import pytest
from bakim_yardimci import ONEK, giris, hepsini_eslestir, ortam_kur, sozlesme_ac
from sqlalchemy import select

from app.models import MaintenanceContractItem
from app.services import settings as ayar_svc

pytestmark = pytest.mark.integration


@pytest.fixture
async def kisiler(birimli_kullanici_ac, kullanici_ac):
    return {
        "yonetici": await birimli_kullanici_ac("yon_e", "SERVIS_YONETICI", ["GUVENLIK"]),
        "sef": await birimli_kullanici_ac("sef_e", "SERVIS_SEF", ["GUVENLIK"]),
        "sef_h": await birimli_kullanici_ac("sefh_e", "SERVIS_SEF", ["HABERLESME"]),
        "yonetim": await kullanici_ac("yonetim_e", "YONETIM"),
    }


async def test_tek_aday_oneri_coklu_aday_liste(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=2)
    await giris(client, "sef_e")
    s = await sozlesme_ac(client, o)
    r = await client.get(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme")
    assert r.status_code == 200, r.text
    veri = r.json()
    assert veri["oran"] == {"toplam": 3, "eslesen": 0, "yuzde": 0.0}
    xray = [k for k in veri["kalemler"] if k["equipment_type"] == "XRAY"]
    kapi = [k for k in veri["kalemler"] if k["equipment_type"] == "KAPI_DEDEKTORU"]
    assert xray[0]["oneri_id"] == o.ekipmanlar["XRAY"][0].id  # tek aday → öneri
    assert all(k["oneri_id"] is None for k in kapi)  # iki aday → karar şefin
    assert {a["id"] for a in kapi[0]["adaylar"]} == {e.id for e in o.ekipmanlar["KAPI_DEDEKTORU"]}

    veri = await hepsini_eslestir(client, s["id"], o)
    assert veri["oran"]["yuzde"] == 100.0
    bagli = (
        await db.scalars(
            select(MaintenanceContractItem.equipment_id).where(
                MaintenanceContractItem.contract_id == s["id"]
            )
        )
    ).all()
    assert None not in bagli


async def test_baska_sozlesmeye_bagli_ekipman_409_tur_uyusmazligi_400(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=1)
    await giris(client, "sef_e")
    ilk = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, ilk["id"], o)
    ikinci = await sozlesme_ac(client, o, aktif=False, kapsam={"XRAY": 1})
    kalem = (await client.get(f"{ONEK}/sozlesmeler/{ikinci['id']}/eslestirme")).json()["kalemler"][
        0
    ]
    assert kalem["adaylar"] == []  # bağlı ekipman aday olmaz
    r = await client.put(
        f"{ONEK}/sozlesmeler/{ikinci['id']}/eslestirme",
        json={
            "eslesmeler": [
                {"kalem_id": kalem["kalem_id"], "equipment_id": o.ekipmanlar["XRAY"][0].id}
            ]
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["sozlesme"] == ilk["contract_no"]
    r = await client.put(
        f"{ONEK}/sozlesmeler/{ikinci['id']}/eslestirme",
        json={
            "eslesmeler": [
                {
                    "kalem_id": kalem["kalem_id"],
                    "equipment_id": o.ekipmanlar["KAPI_DEDEKTORU"][0].id,
                }
            ]
        },
    )
    assert r.status_code in (400, 409)  # tür uyuşmaz (ya da bağlı)


async def test_otomatik_uretim_eslesme_yuzde_yuz_olmadan_acilamaz(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=1)
    await giris(client, "sef_e")
    s = await sozlesme_ac(client, o)
    # Birim şefi genel bayrağı değiştiremez (diğer birimlerin eksiğini görmez).
    assert (await client.put(f"{ONEK}/otomatik-uretim", json={"acik": True})).status_code == 403

    await giris(client, "yon_e")
    r = await client.put(f"{ONEK}/otomatik-uretim", json={"acik": True})
    assert r.status_code == 409
    assert r.json()["detail"]["kod"] == "ESLESTIRME_EKSIK"
    assert await ayar_svc.get(db, "bakim_otomatik_uretim") is False

    await hepsini_eslestir(client, s["id"], o)
    r = await client.put(f"{ONEK}/otomatik-uretim", json={"acik": True})
    assert r.status_code == 200, r.text
    durum = (await client.get(f"{ONEK}/otomatik-uretim")).json()
    assert durum["acik"] is True and durum["oran"]["yuzde"] == 100.0


async def test_eslestirme_rbac_ve_kapsam_404(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_e")
    s = await sozlesme_ac(client, o)
    kalem = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme")).json()["kalemler"][0]
    govde = {
        "eslesmeler": [{"kalem_id": kalem["kalem_id"], "equipment_id": o.ekipmanlar["XRAY"][0].id}]
    }

    await giris(client, "yonetim_e")
    assert (await client.get(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme")).status_code == 200
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme", json=govde)
    assert r.status_code == 403

    await giris(client, "sefh_e")
    assert (await client.get(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme")).status_code == 404
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme", json=govde)
    assert r.status_code == 404
    kayit = await db.get(MaintenanceContractItem, kalem["kalem_id"])
    await db.refresh(kayit)
    assert kayit.equipment_id is None  # kapsam dışı yazma geçmedi
