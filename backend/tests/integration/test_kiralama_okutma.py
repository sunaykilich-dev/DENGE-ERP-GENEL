"""Kiralamada barkodla iade kontrolü ve karekodla teslim (KARARLAR 2026-11-20 §2–3).

- İade kontrolü sevk edilmiş, dönmemiş seri cihazlarla karşılaştırır; seri
  numarasız ek ekipmanda gelen adet sayılır.
- Eksik/fazla varken açıklamasız kayıt 400; açıklamalı kayıt KONTROL olayı yazar.
- `kaydet=false` hiçbir şey yazmaz.
- Etiket kodu değişmez; karekod sayfası cihazı ve kiralamayı gösterir.
- Gidiş ve dönüş teslimi bir kez okutulur (ikincisi 409).
"""

from __future__ import annotations

import pytest
from kiralama_ortak import URL, hazir_kiralama, istemci
from sqlalchemy import func, select

from app.models import RentalEvent

pytestmark = pytest.mark.integration


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("kir_okut", "SERVIS_YONETICI")
    i = await istemci("kir_okut")
    yield i
    await i.aclose()


async def _kontrol_sayisi(db, kiralama_id: int) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(RentalEvent)
        .where(RentalEvent.rental_id == kiralama_id, RentalEvent.tur == "KONTROL")
    )


async def test_iade_kontrolu_eksik_ve_fazla_aciklama_ister(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=3, toplu_adet=4, on_ek="OK", sevk=True)
    k = h["k"]
    toplu_tahsis = next(t["id"] for t in k["tahsisler"] if t.get("kiralik_id") is None)

    govde = {
        "okutulan_seriler": ["ok-s0", "OK-S1", "YABANCI-9"],
        "adetler": [{"tahsis_id": toplu_tahsis, "gelen": 3}],
    }
    r = await ist.post(f"{URL}/{k['id']}/iade-kontrol", json=govde)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["eksik_seri"] == 1 and v["eksik_adet"] == 1 and v["fazla"] == ["YABANCI-9"]
    oneriler = {s["seri"]: s["oneri_sonuc"] for s in v["satirlar"] if s["seri"]}
    assert oneriler == {"OK-S0": "IADE_ALINDI", "OK-S1": "IADE_ALINDI", "OK-S2": "MUSTERIDE"}
    assert await _kontrol_sayisi(db, k["id"]) == 0  # karşılaştırma yazmaz

    r = await ist.post(f"{URL}/{k['id']}/iade-kontrol", json={**govde, "kaydet": True})
    assert r.status_code == 400, r.text
    r = await ist.post(
        f"{URL}/{k['id']}/iade-kontrol",
        json={**govde, "kaydet": True, "aciklama": "Bir telsiz müşteride arızalı kaldı"},
    )
    assert r.status_code == 200 and r.json()["kaydedildi"] is True, r.text
    assert await _kontrol_sayisi(db, k["id"]) == 1


async def test_tam_iade_aciklama_istemez(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=2, on_ek="TI", sevk=True)
    k = h["k"]
    r = await ist.post(
        f"{URL}/{k['id']}/iade-kontrol",
        json={"okutulan_seriler": ["TI-S0", "TI-S1"], "kaydet": True},
    )
    assert r.status_code == 200 and r.json()["tam"] is True, r.text


async def test_karekod_etiket_ve_teslim_okutma(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=1, on_ek="QR", sevk=True)
    cihaz_id = h["cihazlar"][0]

    r = await ist.post(f"{URL}/envanter/{cihaz_id}/etiket")
    assert r.status_code == 200, r.text
    kod = r.json()["etiket_kodu"]
    assert kod and len(kod) >= 10
    r = await ist.post(f"{URL}/envanter/{cihaz_id}/etiket")
    assert r.json()["etiket_kodu"] == kod  # değişmez

    r = await ist.get(f"{URL}/etiket/{kod}")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["seri"] == "QR-S0" and v["kiralama"]["id"] == h["k"]["id"]
    assert v["gidis_teslim_at"] is None

    r = await ist.post(f"{URL}/etiket/{kod}/teslim", json={"yon": "GIDIS"})
    assert r.status_code == 200 and r.json()["gidis_teslim_at"], r.text
    r = await ist.post(f"{URL}/etiket/{kod}/teslim", json={"yon": "GIDIS"})
    assert r.status_code == 409
    r = await ist.post(f"{URL}/etiket/{kod}/teslim", json={"yon": "DONUS", "not": "Depoda"})
    assert r.status_code == 200 and r.json()["donus_teslim_at"], r.text

    assert (await ist.get(f"{URL}/etiket/yok-boyle-kod")).status_code == 404
