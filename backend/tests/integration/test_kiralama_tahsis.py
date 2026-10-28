"""Adet bazlı kısmi tahsis, eşzamanlılık, seri cihaz çift tahsis (TS-112, E06-04).

Seri cihazın başka kiralamayla tarih çakışması M10.1 ile uyarıdır; ayrıntı
`test_kiralama_cakisma_uyarisi.py`.
"""

import asyncio
from datetime import date

import pytest
from kiralama_ortak import (
    URL,
    depo_ac,
    hareket_sayisi,
    hazir_kiralama,
    istemci,
    kalem_id,
    kiralama_ac,
    kiralik_urun_ac,
    musteri_ac,
    planla,
    seri_idleri,
    stok_gir,
    tahsis,
)
from sqlalchemy.exc import IntegrityError

from app.models import RentalAllocation

pytestmark = pytest.mark.integration


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("tah_yon", "SERVIS_YONETICI")
    i = await istemci("tah_yon")
    yield i
    await i.aclose()


async def _bariyer(db, ist, adet: int = 50):
    depo = await depo_ac(db, "TB-D1", birim="GUVENLIK")
    urun = await kiralik_urun_ac(db, "PG-5030", seri=False)
    await stok_gir(ist, urun, depo, adet=adet)
    return depo, urun


async def _planli(ist, musteri, urun, qty, **kw):
    k = await kiralama_ac(ist, musteri, [(urun, qty)], **kw)
    await planla(ist, k)
    return k


async def test_yirmi_otuz_ve_elli_birinci_adet(ist, db) -> None:
    depo, urun = await _bariyer(db, ist)
    musteri = await musteri_ac(db)
    k1 = await _planli(ist, musteri, urun, 20)
    k2 = await _planli(ist, musteri, urun, 30)
    k1 = await tahsis(ist, k1, [{"kalem_id": kalem_id(k1, urun), "depo_id": depo.id, "adet": 20}])
    assert k1["status"] == "HAZIRLANIYOR"
    await tahsis(ist, k2, [{"kalem_id": kalem_id(k2, urun), "depo_id": depo.id, "adet": 30}])
    # Üçüncü kiralama 1 adet: talepte planlanamaz (müsaitlik 0), tahsis de 409.
    k3 = await kiralama_ac(ist, musteri, [(urun, 1)])
    assert (await ist.post(f"{URL}/{k3['id']}/planla")).status_code == 409
    assert await hareket_sayisi(db, "TAHSIS") == 2


async def test_ayni_kaleme_eszamanli_iki_tahsisten_biri_409(ist, db) -> None:
    """Kalem toplamı da kilit altında sınanır: 30'luk kaleme aynı anda iki 30."""
    depo, urun = await _bariyer(db, ist)
    k1 = await _planli(ist, await musteri_ac(db), urun, 30)
    govde = {"satirlar": [{"kalem_id": kalem_id(k1, urun), "depo_id": depo.id, "adet": 30}]}
    r1, r2 = await asyncio.gather(
        ist.post(f"{URL}/{k1['id']}/tahsis", json=govde),
        ist.post(f"{URL}/{k1['id']}/tahsis", json=govde),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)


async def test_eszamanli_iki_kiralama_ayni_stoktan_otuzar(ist, db) -> None:
    """İki kiralama aynı tarihlerde 50'lik stoktan 30+30 ister: biri 200, diğeri 409."""
    from app.models import Rental

    depo, urun = await _bariyer(db, ist)
    musteri = await musteri_ac(db)
    k1 = await kiralama_ac(ist, musteri, [(urun, 30)])
    k2 = await kiralama_ac(ist, musteri, [(urun, 30)])
    # Rezerv kuralını atlayıp (iki planlı kiralama 60 > 50 olamazdı) tahsis
    # kilidini sınamak için ikisi doğrudan PLANLANDI'ya alınır.
    for k in (k1, k2):
        kayit = await db.get(Rental, k["id"])
        kayit.status = "PLANLANDI"
    await db.commit()
    r1, r2 = await asyncio.gather(
        ist.post(
            f"{URL}/{k1['id']}/tahsis",
            json={"satirlar": [{"kalem_id": kalem_id(k1, urun), "depo_id": depo.id, "adet": 30}]},
        ),
        ist.post(
            f"{URL}/{k2['id']}/tahsis",
            json={"satirlar": [{"kalem_id": kalem_id(k2, urun), "depo_id": depo.id, "adet": 30}]},
        ),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)
    assert await hareket_sayisi(db, "TAHSIS") == 1


async def test_kalem_toplami_asilamaz_ve_sevk_sonrasi_ek_tahsis(ist, db) -> None:
    h = await hazir_kiralama(db, ist, toplu_adet=5, on_ek="KT", sevk=True)
    k = h["k"]
    r = await ist.post(
        f"{URL}/{k['id']}/tahsis",
        json={
            "satirlar": [{"kalem_id": kalem_id(k, h["toplu"]), "depo_id": h["depo"].id, "adet": 1}]
        },
    )
    assert r.status_code == 409  # kalem 5, 5 tahsisli
    # Kalemi artırıp sevk sonrası ek tahsis.
    await stok_gir(ist, h["toplu"], h["depo"], adet=2)
    kart = (await ist.get(f"{URL}/{k['id']}")).json()
    r = await ist.put(
        f"{URL}/{k['id']}",
        json={
            "version": kart["version"],
            "kalemler": [{"id": kart["kalemler"][0]["id"], "product_id": h["toplu"].id, "qty": 7}],
        },
    )
    assert r.status_code == 200, r.text
    r = await ist.post(
        f"{URL}/{k['id']}/tahsis",
        json={
            "satirlar": [{"kalem_id": kalem_id(k, h["toplu"]), "depo_id": h["depo"].id, "adet": 2}]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SEVK_EDILDI"
    # Tahsisli kalemin adedi tahsisin altına indirilemez.
    r = await ist.put(
        f"{URL}/{k['id']}",
        json={
            "version": r.json()["version"],
            "kalemler": [{"id": kart["kalemler"][0]["id"], "product_id": h["toplu"].id, "qty": 6}],
        },
    )
    assert r.status_code == 409


async def test_seri_cihaz_cift_tahsis_engeli(ist, db) -> None:
    depo = await depo_ac(db, "SC-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "SC-XRAY", seri=True)
    await stok_gir(ist, seri, depo, seriler=["X-1"])
    cihaz = (await seri_idleri(db, seri))[0]
    musteri = await musteri_ac(db)
    k1 = await kiralama_ac(ist, musteri, [(seri, 1)])
    await planla(ist, k1)
    await tahsis(ist, k1, [{"kalem_id": kalem_id(k1, seri), "kiralik_idler": [cihaz]}])
    # Aynı cihaz çakışan tarihte ikinci kiralamaya → 409 (planlama da 409).
    k2 = await kiralama_ac(ist, musteri, [(seri, 1)], bas="2026-11-04", bit="2026-11-09")
    assert (await ist.post(f"{URL}/{k2['id']}/planla")).status_code == 409
    # Çakışmayan tarih (yarı açık: 5 Kasım iade, 5 Kasım çıkış) serbest.
    k3 = await kiralama_ac(ist, musteri, [(seri, 1)], bas="2026-11-05", bit="2026-11-07")
    await planla(ist, k3)
    await tahsis(ist, k3, [{"kalem_id": kalem_id(k3, seri), "kiralik_idler": [cihaz]}])
    # Seri üründe adet ≠ seçilen cihaz sayısı 400; seri cihaz tahsisinde qty=1 CHECK.
    k4 = await kiralama_ac(ist, musteri, [(seri, 1)], bas="2026-12-01", bit="2026-12-03")
    await planla(ist, k4)
    r = await ist.post(
        f"{URL}/{k4['id']}/tahsis",
        json={"satirlar": [{"kalem_id": kalem_id(k4, seri), "kiralik_idler": [cihaz], "adet": 2}]},
    )
    assert r.status_code == 400
    # Rollback nesneleri bayatlatır: kimlikler önceden alınır.
    urun_id, depo_id, k4_kalem = seri.id, depo.id, kalem_id(k4, seri)
    db.add(
        RentalAllocation(
            rental_id=k4["id"],
            rental_item_id=k4_kalem,
            product_id=urun_id,
            asset_id=cihaz,
            from_warehouse_id=depo_id,
            qty=2,
            baslangic=date(2026, 12, 1),
            bitis=date(2026, 12, 3),
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    # M10.1 (KARARLAR 2026-10-28): çakışan ikinci AKTİF tahsis artık DB'de
    # engellenmez (EXCLUDE kaldırıldı); kural servis katmanında uyarı +
    # gerekçe (`test_kiralama_cakisma_uyarisi.py`).


async def test_tahsis_coz(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=1, toplu_adet=3, on_ek="TC")
    k = h["k"]
    toplu_t = next(t for t in k["tahsisler"] if t["kiralik_id"] is None)
    r = await ist.post(f"{URL}/{k['id']}/tahsis/{toplu_t['id']}/coz")
    assert r.status_code == 200, r.text
    assert next(t for t in r.json()["tahsisler"] if t["id"] == toplu_t["id"])["durum"] == "COZULDU"
    assert await hareket_sayisi(db, "TAHSIS_COZ") == 1
    # Başka kiralamanın tahsisi bu yoldan çözülemez (404).
    h2 = await hazir_kiralama(db, ist, toplu_adet=1, on_ek="TC2")
    r = await ist.post(f"{URL}/{k['id']}/tahsis/{h2['k']['tahsisler'][0]['id']}/coz")
    assert r.status_code == 404
    # Sevk edilmiş tahsis çözülemez.
    seri_t = next(t for t in k["tahsisler"] if t["kiralik_id"] is not None)
    r = await ist.post(
        f"{URL}/{k['id']}/tahsis",
        json={
            "satirlar": [{"kalem_id": kalem_id(k, h["toplu"]), "depo_id": h["depo"].id, "adet": 3}]
        },
    )
    assert r.status_code == 200
    r = await ist.post(f"{URL}/{k['id']}/sevk", json={})
    assert r.status_code == 200, r.text
    r = await ist.post(f"{URL}/{k['id']}/tahsis/{seri_t['id']}/coz")
    assert r.status_code == 409
