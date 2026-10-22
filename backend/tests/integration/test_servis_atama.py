"""Kimlik bazlı çoklu atama, tek sorumlu ve toplu atama (TS-025; E01-12).

Gerçek hikâye: eski sistem atamayı AD METNİ ile tutuyordu; aynı adlı iki
teknisyen birbirinin işini görüyor, kişi bazlı her sayı yanlış çıkıyordu.
Atama `users.id` iledir; girişsiz saha personeli atanabilir, işten ayrılan
atanamaz; toplu atama tek transaction'dır.
"""

from datetime import date

import pytest
from servis_yardimci import giris, olay_sayisi, tazele, teknisyen
from sqlalchemy import select

from app.models import ServiceOrderAssignment

pytestmark = pytest.mark.integration


async def _aktif(db, so_id):
    return (
        await db.scalars(
            select(ServiceOrderAssignment).where(
                ServiceOrderAssignment.service_order_id == so_id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    ).all()


async def test_atama_izin_ve_olay(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_a1", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("op_a1", "SERVIS_OPERASYON", ["GUVENLIK"])
    t1 = await teknisyen(birimli_kullanici_ac, "tek_a1")
    t2 = await teknisyen(birimli_kullanici_ac, "tek_a2")
    so = await servis_isi_ac()
    govde = {
        "atamalar": [
            {"user_id": t1.id, "rol": "TEKNISYEN", "is_lead": True},
            {"user_id": t2.id, "rol": "TEKNISYEN"},
        ]
    }
    await giris(client, "op_a1")
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/atama", json=govde)
    assert r.status_code == 403
    await giris(client, "sef_a1")
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/atama", json=govde)
    assert r.status_code == 200, r.text
    assert [(k["ad"], k["is_lead"]) for k in r.json()] == [("Tek_A1", True), ("Tek_A2", False)]
    assert await olay_sayisi(db, so.id, "ATAMA") == 1
    assert await olay_sayisi(db, so.id, "DURUM") == 0  # atama durumu değiştirmez
    so = await tazele(db, so)
    assert so.status == "MUSTERI_TALEBI"

    # Sorumlu değişimi: eski satır kapanır, geçmiş kalır; aynı istek tekrarı olay üretmez.
    govde2 = {"atamalar": [{"user_id": t2.id, "rol": "TEKNISYEN", "is_lead": True}]}
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/atama", json=govde2)
    assert r.status_code == 200
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/atama", json=govde2)
    assert await olay_sayisi(db, so.id, "ATAMA") == 2
    tum = (
        await db.scalars(
            select(ServiceOrderAssignment)
            .where(ServiceOrderAssignment.service_order_id == so.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    assert len(tum) == 3 and len([a for a in tum if a.removed_at is None]) == 1
    r = await client.get(f"/api/teknik-servis/isler/{so.id}/gecmis", params={"tur": "ATAMA"})
    assert r.json()[0]["kisiler"]["sorumlu"] == "Tek_A1"


async def test_atanabilirlik_kurallari(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_a2", "SERVIS_SEF", ["GUVENLIK"])
    ayrilan = await teknisyen(birimli_kullanici_ac, "ayrilan_a2")
    ayrilan.ayrilis_tarihi = date(2025, 12, 1)
    ayrilan.ayrilis_nedeni = "ISTIFA"
    girissiz = await teknisyen(birimli_kullanici_ac, "girissiz_a2")
    girissiz.giris_acik = False
    baska_birim = await teknisyen(birimli_kullanici_ac, "haber_a2", ["HABERLESME"])
    ofis = await birimli_kullanici_ac("ofis_a2", "SERVIS_OPERASYON", ["GUVENLIK"])
    t1 = await teknisyen(birimli_kullanici_ac, "tek_a3")
    await db.commit()
    so = await servis_isi_ac()
    kapali = await servis_isi_ac(durum="TAMAMLANDI")
    await giris(client, "sef_a2")

    def tek(kisi, lead=False):
        return {"atamalar": [{"user_id": kisi.id, "rol": "TEKNISYEN", "is_lead": lead}]}

    yol = f"/api/teknik-servis/isler/{so.id}/atama"
    assert (await client.put(yol, json=tek(ayrilan))).status_code == 400
    assert (await client.put(yol, json=tek(ofis))).status_code == 400  # saha rolü yok
    assert (await client.put(yol, json=tek(baska_birim))).status_code == 409
    assert (
        await client.put(yol, json={"atamalar": [{"user_id": 987654, "rol": "SEF"}]})
    ).status_code == 400
    iki_sorumlu = {
        "atamalar": [
            {"user_id": t1.id, "rol": "TEKNISYEN", "is_lead": True},
            {"user_id": girissiz.id, "rol": "TEKNISYEN", "is_lead": True},
        ]
    }
    assert (await client.put(yol, json=iki_sorumlu)).status_code == 409
    sef_sorumlu = {"atamalar": [{"user_id": t1.id, "rol": "SEF", "is_lead": True}]}
    assert (await client.put(yol, json=sef_sorumlu)).status_code == 400
    assert await _aktif(db, so.id) == []
    # Girişsiz saha personeli atanabilir.
    r = await client.put(yol, json=tek(girissiz, True))
    assert r.status_code == 200, r.text
    assert r.json()[0]["giris_acik"] is False
    # Kapalı işe atama 409.
    r = await client.put(f"/api/teknik-servis/isler/{kapali.id}/atama", json=tek(t1))
    assert r.status_code == 409


async def test_kendi_isleri_kapsami_atamaya_bagli(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_a4", "SERVIS_SEF", ["GUVENLIK"])
    t1 = await teknisyen(birimli_kullanici_ac, "tek_a4")
    so = await servis_isi_ac()
    await giris(client, "tek_a4")
    assert (await client.get(f"/api/teknik-servis/isler/{so.id}")).status_code == 404
    await giris(client, "sef_a4")
    await client.put(
        f"/api/teknik-servis/isler/{so.id}/atama",
        json={"atamalar": [{"user_id": t1.id, "is_lead": True}]},
    )
    await giris(client, "tek_a4")
    assert (await client.get(f"/api/teknik-servis/isler/{so.id}")).status_code == 200
    # Adı değişse de (kimlik bazlı) işi görmeye devam eder.
    t1.full_name = "Başka Ad"
    await db.commit()
    r = await client.get("/api/teknik-servis/isler")
    assert [x["id"] for x in r.json()] == [so.id]


async def test_toplu_atama_sinir_ve_atomiklik(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_a5", "SERVIS_SEF", ["GUVENLIK"])
    t1 = await teknisyen(birimli_kullanici_ac, "tek_a5")
    a = await servis_isi_ac()
    b = await servis_isi_ac()
    h = await servis_isi_ac(birim="HABERLESME")
    kapali = await servis_isi_ac(durum="KAPATILDI")
    ekip = [{"user_id": t1.id, "rol": "TEKNISYEN", "is_lead": True}]
    await giris(client, "sef_a5")
    yol = "/api/teknik-servis/isler/toplu-atama"

    r = await client.put(yol, json={"is_idler": list(range(1, 152)), "atamalar": ekip})
    assert r.status_code == 422
    r = await client.put(yol, json={"is_idler": [a.id, b.id, h.id], "atamalar": ekip})
    assert r.status_code == 404  # kapsam dışı iş; hangisi olduğu söylenmez
    r = await client.put(yol, json={"is_idler": [a.id, kapali.id], "atamalar": ekip})
    assert r.status_code == 409 and kapali.so_no in r.json()["detail"]
    for so in (a, b, kapali):
        assert await _aktif(db, so.id) == []

    r = await client.put(yol, json={"is_idler": [a.id, b.id], "atamalar": ekip, "mod": "EKLE"})
    assert r.status_code == 200, r.text
    assert r.json()["guncellenen"] == 2
    for so in (a, b):
        assert [x.user_id for x in await _aktif(db, so.id)] == [t1.id]


async def test_toplu_atama_karisik_birim_409(
    client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await kullanici_ac("mud_a6", "SERVIS_YONETICI")
    t1 = await teknisyen(birimli_kullanici_ac, "tek_a6", ["GUVENLIK", "HABERLESME"])
    a = await servis_isi_ac()
    h = await servis_isi_ac(birim="HABERLESME")
    await giris(client, "mud_a6")
    r = await client.put(
        "/api/teknik-servis/isler/toplu-atama",
        json={"is_idler": [a.id, h.id], "atamalar": [{"user_id": t1.id, "is_lead": True}]},
    )
    assert r.status_code == 409
    assert await _aktif(db, a.id) == [] and await _aktif(db, h.id) == []
