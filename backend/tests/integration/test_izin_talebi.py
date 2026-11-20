"""Personel izin talebi (KARARLAR 2026-11-20 §7).

- Vekil, il ve iletişim numarası zorunlu; vekil kendisi olamaz.
- Yöneticisi tanımlı olmayan personelin talebi alınmaz (409).
- Zincir org şemasından: şef → müdür → GMY; sıra atlanamaz (başkası karar veremez).
- E-postadaki tek kullanımlık bağlantı karar verir; ikinci kullanım 404.
- 24 saatte karar verilmeyen basamak sonraki yöneticiye geçer.
- Son onayda talep ONAYLANDI ve planlamada İZİN bloğu oluşur.
- Red gerekçesiz olmaz; çakışan talep 409.
"""

from __future__ import annotations

import pytest
from servis_teklif_yardimci import kapat, oturum
from sqlalchemy import select

from app.models import IzinOnayi, IzinTalebi
from app.models.servis_planlama import ServiceUnavailability
from app.services import izin as izin_svc

pytestmark = pytest.mark.integration

GOVDE = {
    "tur": "YILLIK",
    "baslangic": "2026-02-02",
    "bitis": "2026-02-06",
    "izin_ili": "Antalya",
    "iletisim_tel": "0532 111 22 33",
}


@pytest.fixture
async def ortam(client, db, kullanici_ac):
    gmy = await kullanici_ac("i_gmy", "YONETIM")
    mudur = await kullanici_ac("i_mudur", "SERVIS_YONETICI")
    sef = await kullanici_ac("i_sef", "SERVIS_SEF")
    per = await kullanici_ac("i_per", "SERVIS_TEKNISYEN")
    vekil = await kullanici_ac("i_vekil", "SERVIS_TEKNISYEN")
    await kullanici_ac("i_ik", "IK")
    per.yonetici_id, sef.yonetici_id, mudur.yonetici_id = sef.id, mudur.id, gmy.id
    await db.commit()
    ist = {ad: await oturum(ad) for ad in ("i_gmy", "i_mudur", "i_sef", "i_per", "i_vekil", "i_ik")}
    ist["id"] = {"gmy": gmy.id, "mudur": mudur.id, "sef": sef.id, "per": per.id, "vekil": vekil.id}
    yield ist
    await kapat(*(v for k, v in ist.items() if k != "id"))


async def _token(db, talep_id: int) -> str:
    db.expire_all()
    o = await db.scalar(
        select(IzinOnayi).where(IzinOnayi.talep_id == talep_id, IzinOnayi.durum == "BEKLIYOR")
    )
    return o.token


async def test_zorunlu_alanlar_ve_zincir(ortam, db, client) -> None:
    p = ortam["i_per"]
    vekil = ortam["id"]["vekil"]
    assert (await p.post("/api/izin", json=GOVDE)).status_code == 400  # vekil yok
    assert (await p.post("/api/izin", json={**GOVDE, "vekil_id": ortam["id"]["per"]})).status_code == 400
    assert (
        await p.post("/api/izin", json={**GOVDE, "vekil_id": vekil, "izin_ili": " "})
    ).status_code == 400
    assert (
        await p.post("/api/izin", json={**GOVDE, "vekil_id": vekil, "iletisim_tel": "123"})
    ).status_code == 400
    # Yöneticisi olmayan (vekil) talep açamaz.
    r = await ortam["i_vekil"].post("/api/izin", json={**GOVDE, "vekil_id": ortam["id"]["per"]})
    assert r.status_code == 409 and "yönetici" in r.json()["detail"]

    r = await p.post("/api/izin", json={**GOVDE, "vekil_id": vekil})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["gun_sayisi"] == 5
    assert [(o["onaylayici_id"], o["durum"]) for o in t["onaylar"]] == [
        (ortam["id"]["sef"], "BEKLIYOR"),
        (ortam["id"]["mudur"], "SIRADA"),
        (ortam["id"]["gmy"], "SIRADA"),
    ]
    # Çakışan ikinci talep 409.
    assert (await p.post("/api/izin", json={**GOVDE, "vekil_id": vekil})).status_code == 409

    # Sıra şefte: müdür karar veremez.
    birinci, ikinci = t["onaylar"][0]["id"], t["onaylar"][1]["id"]
    r = await ortam["i_mudur"].post(f"/api/izin/onay/{birinci}/karar", json={"karar": "ONAY"})
    assert r.status_code == 404
    r = await ortam["i_mudur"].post(f"/api/izin/onay/{ikinci}/karar", json={"karar": "ONAY"})
    assert r.status_code == 409
    assert (await ortam["i_sef"].get("/api/izin/ozet")).json()["onayimda"] == 1
    r = await ortam["i_sef"].post(f"/api/izin/onay/{birinci}/karar", json={"karar": "ONAY"})
    assert r.status_code == 200, r.text

    # Müdür e-postadaki bağlantıyla karar verir (oturumsuz).
    token = await _token(db, t["id"])
    r = await client.get(f"/api/public/izin/{token}")
    assert r.status_code == 200 and r.json()["personel"] and "iletisim_tel" not in r.json()
    r = await client.post(f"/api/public/izin/{token}/karar", json={"karar": "ONAY"})
    assert r.status_code == 200, r.text
    assert (await client.post(f"/api/public/izin/{token}/karar", json={"karar": "ONAY"})).status_code == 404

    # GMY red gerekçesiz olmaz; onaylayınca talep biter ve planlamaya izin düşer.
    ucuncu = t["onaylar"][2]["id"]
    g = ortam["i_gmy"]
    assert (await g.post(f"/api/izin/onay/{ucuncu}/karar", json={"karar": "RED"})).status_code == 400
    r = await g.post(f"/api/izin/onay/{ucuncu}/karar", json={"karar": "ONAY"})
    assert r.status_code == 200 and r.json()["durum"] == "ONAYLANDI", r.text
    blok = await db.scalar(
        select(ServiceUnavailability).where(ServiceUnavailability.user_id == ortam["id"]["per"])
    )
    assert blok is not None and blok.tur == "IZIN"

    # İK hepsini görür; personel yalnız kendininkini.
    assert len((await ortam["i_ik"].get("/api/izin/tum")).json()) == 1
    assert (await p.get("/api/izin/tum")).status_code == 403


async def test_24_saatte_karar_yoksa_sonraki_yoneticiye_gecer(ortam, db, client) -> None:
    r = await ortam["i_per"].post(
        "/api/izin", json={**GOVDE, "tur": "MAZERET", "vekil_id": ortam["id"]["vekil"]}
    )
    assert r.status_code == 201, r.text
    talep_id = r.json()["id"]

    client.clock.advance(hours=23)
    await izin_svc.yukselt(db, client.clock)
    db.expire_all()
    t = await db.get(IzinTalebi, talep_id)
    assert [o.durum for o in t.onaylar] == ["BEKLIYOR", "SIRADA", "SIRADA"]

    client.clock.advance(hours=2)
    sonuc = await izin_svc.yukselt(db, client.clock)
    assert "1 talep" in sonuc
    db.expire_all()
    t = await db.get(IzinTalebi, talep_id)
    assert [o.durum for o in t.onaylar] == ["SURE_ASIMI", "BEKLIYOR", "SIRADA"]
    # Eski bağlantı geçersiz.
    assert t.onaylar[0].token is None

    # Personel kendi bekleyen talebini iptal edebilir (saat ilerlediği için yeni oturum).
    yeni = await oturum("i_per")
    r = await yeni.post(f"/api/izin/{talep_id}/iptal")
    await kapat(yeni)
    assert r.status_code == 200 and r.json()["durum"] == "IPTAL", r.text
