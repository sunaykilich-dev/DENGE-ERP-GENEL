"""Satış/kiralama talebinin teknik servis müdürüne ve birime yönlendirilmesi
(KARARLAR 2026-11-20 §5–6).

- Onaylı tekliften açılan kurulum işi sözleşme ayrıntısıyla müdürde (MUDURDE) belirir.
- Müdür yalnız birimin üyesi ve planlama yetkili kişiye yönlendirebilir.
- Şef kendisine yönlendirileni görür; müdür olmayan yönlendiremez (403).
- Kiralama talebi bir kez onaylanıp yönlendirilir (ikincisi 409); planlanınca
  açık listeden düşer.
"""

from __future__ import annotations

import pytest
from kiralama_ortak import kiralama_ac, kiralik_urun_ac, musteri_ac
from servis_teklif_yardimci import kapat, musteri, oturum

pytestmark = pytest.mark.integration

YON = "/api/teknik-servis/yonlendirmeler"


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac):
    await kullanici_ac("y_satis", "SATIS")
    await kullanici_ac("y_mudur", "SERVIS_YONETICI")
    await birimli_kullanici_ac("y_sef", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("y_tek", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    ist = {ad: await oturum(ad) for ad in ("y_satis", "y_mudur", "y_sef", "y_tek")}
    ist["musteri"] = await musteri(db, "Yönlendirme Müşterisi A.Ş.")
    yield ist
    await kapat(*(v for k, v in ist.items() if k != "musteri"))


async def test_satistan_mudure_mudurden_sefe(ortam, db) -> None:
    s = ortam["y_satis"]
    r = await s.post(
        "/api/teklifler",
        json={
            "customer_id": ortam["musteri"].id,
            "kalemler": [
                {"item_type": "SERBEST", "description": "Kamera", "qty": 1,
                 "unit_price": "1000", "vat_rate": 0.20}  # fmt: skip
            ],
        },
    )
    assert r.status_code == 201, r.text
    t = r.json()
    await s.post(f"/api/teklifler/{t['id']}/elle-gonderildi", json={"kanal": "ELDEN", "not": "x"})
    await s.post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
    r = await s.post(
        f"/api/satis-takip/teklif/{t['id']}/is",
        json={
            "tur": "KURULUM",
            "birim": "GUVENLIK",
            "sozlesme_detay": "36 ay bakım taahhüdü, 2 yıl garanti",
        },
    )
    assert r.status_code == 201, r.text
    so_id = r.json()["service_order_id"]

    m = ortam["y_mudur"]
    r = await m.get(YON)
    assert r.status_code == 200, r.text
    kayit = next(x for x in r.json() if x["service_order_id"] == so_id)
    assert kayit["durum"] == "MUDURDE" and kayit["kaynak"] == "SATIS"
    assert "taahhüdü" in kayit["sozlesme_detay"]

    r = await m.get(f"{YON}/adaylar", params={"birim": "GUVENLIK"})
    adlar = {a["id"] for a in r.json()}
    sef_id = (await ortam["y_sef"].get("/api/auth/me")).json()["id"]
    tek_id = (await ortam["y_tek"].get("/api/auth/me")).json()["id"]
    assert sef_id in adlar and tek_id not in adlar

    # Teknisyene (planlama yetkisi yok) yönlendirilemez; şef yönlendiremez.
    yol = f"{YON}/{kayit['id']}/yonlendir"
    r = await m.post(yol, json={"hedef_user_id": tek_id, "version": kayit["version"]})
    assert r.status_code == 400, r.text
    r = await ortam["y_sef"].post(yol, json={"hedef_user_id": sef_id, "version": kayit["version"]})
    assert r.status_code == 403
    r = await m.post(
        yol, json={"hedef_user_id": sef_id, "version": kayit["version"], "not": "Bu hafta planla"}
    )
    assert r.status_code == 200 and r.json()["durum"] == "BIRIMDE", r.text

    r = await ortam["y_sef"].get(YON)
    assert [x["id"] for x in r.json()] == [kayit["id"]]
    assert r.json()[0]["mudur_notu"] == "Bu hafta planla"


async def test_kiralama_talebi_onaylanir_ve_planlaninca_duser(ortam, db) -> None:
    m = ortam["y_mudur"]
    urun = await kiralik_urun_ac(db, "YON-TLS", seri=False)
    hesap = await musteri_ac(db, "Yön Kiralama")
    k = await kiralama_ac(m, hesap, [(urun, 1)])

    r = await m.post(f"/api/kiralama/{k['id']}/talep-onay", json={"sozlesme_detay": "Fuar, 5 gün"})
    assert r.status_code == 200, r.text
    r = await m.post(f"/api/kiralama/{k['id']}/talep-onay", json={})
    assert r.status_code == 409

    liste = (await m.get(YON)).json()
    assert any(x["rental_id"] == k["id"] and x["kaynak"] == "KIRALAMA" for x in liste)

    # TALEP'ten çıkınca açık listeden düşer (müsaitlik yetmese de iptal eder).
    r = await m.post(f"/api/kiralama/{k['id']}/iptal", json={"gerekce": "Müşteri vazgeçti"})
    assert r.status_code == 200, r.text
    liste = (await m.get(YON)).json()
    assert not any(x["rental_id"] == k["id"] for x in liste)
    tum = (await m.get(YON, params={"acik": False})).json()
    assert next(x for x in tum if x["rental_id"] == k["id"])["planlandi"] is True
