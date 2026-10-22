"""Tarih bazlı müsaitlik, rezervasyon, uzatma (TS-116, E06-12).

Örnek: 10 adet PG-5030 varken 1-5 Kasım için 8 adet rezervliyse 3 adetlik
kiralama planlamada 409 alır; 10-12 Kasım için geçer. Bitiş iade günüdür
(yarı açık aralık).
"""

import asyncio

import pytest
from kiralama_ortak import (
    URL,
    depo_ac,
    hazir_kiralama,
    istemci,
    kiralama_ac,
    kiralik_urun_ac,
    musteri_ac,
    planla,
    stok_gir,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("mus_yon", "SERVIS_YONETICI")
    i = await istemci("mus_yon")
    yield i
    await i.aclose()


async def _musaitlik(ist, urun, bas, bit) -> dict:
    r = await ist.get(
        f"{URL}/musaitlik", params={"product_id": urun.id, "baslangic": bas, "bitis": bit}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_kasim_ornegi_iptal_ve_uzatma(ist, db) -> None:
    depo = await depo_ac(db, "MU-D1", birim="GUVENLIK")
    urun = await kiralik_urun_ac(db, "PG-5030", seri=False)
    await stok_gir(ist, urun, depo, adet=10)
    musteri = await musteri_ac(db)
    k8 = await kiralama_ac(ist, musteri, [(urun, 8)], bas="2026-11-01", bit="2026-11-05")
    k8 = await planla(ist, k8)
    m = await _musaitlik(ist, urun, "2026-11-01", "2026-11-05")
    assert (m["toplam"], m["rezerve"], m["musait"]) == (10, 8, 2)
    k3 = await kiralama_ac(ist, musteri, [(urun, 3)], bas="2026-11-01", bit="2026-11-05")
    r = await ist.post(f"{URL}/{k3['id']}/planla")
    assert r.status_code == 409 and "PG-5030: 1 adet eksik" in r.json()["detail"]
    k3b = await kiralama_ac(ist, musteri, [(urun, 3)], bas="2026-11-10", bit="2026-11-12")
    k3b = await planla(ist, k3b)
    # Talep (TALEP) hiçbir şeyi bloke etmez.
    m = await _musaitlik(ist, urun, "2026-11-01", "2026-11-05")
    assert m["rezerve"] == 8
    # 5 Kasım iade günü: 5-7 Kasım aralığı 8'lik kiralamayla çakışmaz.
    assert (await _musaitlik(ist, urun, "2026-11-05", "2026-11-07"))["musait"] == 10
    # Uzatma çakışma yaratırsa 409 (8 + 3 > 10), yaratmazsa geçer.
    r = await ist.put(f"{URL}/{k8['id']}", json={"version": k8["version"], "bitis": "2026-11-11"})
    assert r.status_code == 409, r.text
    r = await ist.put(f"{URL}/{k8['id']}", json={"version": k8["version"], "bitis": "2026-11-09"})
    assert r.status_code == 200, r.text
    gecmis = (await ist.get(f"{URL}/{k8['id']}/gecmis")).json()
    tarih = next(o for o in gecmis if o["tur"] == "TARIH")
    assert tarih["eski"]["bitis"] == "2026-11-05" and tarih["yeni"]["bitis"] == "2026-11-09"
    # İptal sonrası müsaitlik hemen artar.
    r = await ist.post(f"{URL}/{k8['id']}/iptal", json={"gerekce": "Etkinlik ertelendi"})
    assert r.status_code == 200
    assert (await _musaitlik(ist, urun, "2026-11-01", "2026-11-05"))["musait"] == 10
    r = await ist.post(f"{URL}/{k3['id']}/planla")
    assert r.status_code == 200


async def test_kontrolde_ayri_sutun_ve_kayip_dusulur(ist, db) -> None:
    h = await hazir_kiralama(db, ist, toplu_adet=6, on_ek="KS", sevk=True)
    k = h["k"]
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={
            "satirlar": [
                {
                    "tahsis_id": k["tahsisler"][0]["id"],
                    "sonuc": "IADE_ALINDI",
                    "adet": 4,
                    "depo_id": h["depo"].id,
                },
                {"tahsis_id": k["tahsisler"][0]["id"], "sonuc": "KAYIP", "adet": 2},
            ]
        },
    )
    assert r.status_code == 200, r.text
    m = await _musaitlik(ist, h["toplu"], "2026-12-01", "2026-12-03")
    assert m["kontrolde"] == 4 and m["kayip"] == 2
    assert m["toplam"] == 4 and m["musait"] == 4


async def test_geciken_iade_rezerv_sayilir(ist, db, client) -> None:
    """Bitişi geçmiş ama cihazı müşteride olan kiralama, müşterideki adet kadar rezerv."""
    h = await hazir_kiralama(
        db, ist, toplu_adet=5, on_ek="GC", sevk=True, bas="2026-01-01", bit="2026-01-05"
    )
    m = await _musaitlik(ist, h["toplu"], "2026-02-01", "2026-02-03")
    assert m["geciken"] == 5 and m["musait"] == 0


async def test_iki_kalemli_iki_kiralama_eszamanli_planlanir_deadlock_yok(ist, db) -> None:
    depo = await depo_ac(db, "DL-D1", birim="GUVENLIK")
    u1 = await kiralik_urun_ac(db, "DL-A", seri=False)
    u2 = await kiralik_urun_ac(db, "DL-B", seri=False)
    await stok_gir(ist, u1, depo, adet=10)
    await stok_gir(ist, u2, depo, adet=10)
    musteri = await musteri_ac(db)
    k1 = await kiralama_ac(ist, musteri, [(u1, 5), (u2, 5)])
    k2 = await kiralama_ac(ist, musteri, [(u2, 5), (u1, 5)])
    r1, r2 = await asyncio.wait_for(
        asyncio.gather(ist.post(f"{URL}/{k1['id']}/planla"), ist.post(f"{URL}/{k2['id']}/planla")),
        timeout=60,
    )
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    # Üçüncüsü artık sığmaz.
    k3 = await kiralama_ac(ist, musteri, [(u1, 1)])
    assert (await ist.post(f"{URL}/{k3['id']}/planla")).status_code == 409
