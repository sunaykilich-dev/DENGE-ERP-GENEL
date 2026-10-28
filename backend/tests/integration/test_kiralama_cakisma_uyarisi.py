"""Kiralamada aynı cihaz / çakışan tarih: engel değil UYARI + gerekçe (M10.1).

KARARLAR 2026-10-28 §7 Faz A/4. Seri kiralık cihaz başka bir kiralamada aynı
tarihlere AKTİF tahsisliyse:

- onaysız istek 409 + `kod=KIRALAMA_CAKISMA` + çakışan kiralama listesi alır,
  HİÇBİR şey yazılmaz;
- `cakisma_onay=true` gerekçesiz gelirse 400;
- onay + gerekçe ile kayıt yapılır, gerekçe ve çakışma listesi denetim izine
  (`kiralama.cakisma_onay`) düşer.

Aynı kural tahsiste, tarih değişikliğinde (PUT) ve sahada değişimde geçerli.
"""

import pytest
from kiralama_ortak import (
    URL,
    depo_ac,
    hareket_sayisi,
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
from sqlalchemy import select

from app.models import AuditLog, RentalAllocation

pytestmark = pytest.mark.integration

GEREKCE = "Müşteri A erken iade edecek, cihaz aynı gün B'ye gider"


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("cak_yon", "SERVIS_YONETICI")
    i = await istemci("cak_yon")
    yield i
    await i.aclose()


async def _iki_cihaz(db, ist):
    depo = await depo_ac(db, "CK-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "CK-XRAY", seri=True)
    await stok_gir(ist, seri, depo, seriler=["CK-1", "CK-2"])
    cihaz1, _ = await seri_idleri(db, seri)
    return depo, seri, cihaz1


async def _aktif_tahsis_sayisi(db, cihaz_id: int) -> int:
    return len(
        (
            await db.scalars(
                select(RentalAllocation).where(
                    RentalAllocation.asset_id == cihaz_id, RentalAllocation.durum == "AKTIF"
                )
            )
        ).all()
    )


async def _onay_denetimleri(db) -> list[AuditLog]:
    return list(
        (await db.scalars(select(AuditLog).where(AuditLog.action == "kiralama.cakisma_onay"))).all()
    )


async def test_tahsis_cakismasi_uyari_sonra_gerekceyle_kayit(ist, db) -> None:
    _, seri, cihaz = await _iki_cihaz(db, ist)
    musteri = await musteri_ac(db)
    k1 = await planla(ist, await kiralama_ac(ist, musteri, [(seri, 1)]))
    k1 = await tahsis(ist, k1, [{"kalem_id": kalem_id(k1, seri), "kiralik_idler": [cihaz]}])
    # Ürün düzeyinde 2 cihaz var: ikinci kiralama planlanır; AYNI cihaz istenir.
    k2 = await planla(
        ist, await kiralama_ac(ist, musteri, [(seri, 1)], bas="2026-11-03", bit="2026-11-08")
    )
    satirlar = [{"kalem_id": kalem_id(k2, seri), "kiralik_idler": [cihaz]}]
    tahsis_once = await hareket_sayisi(db, "TAHSIS")

    r = await ist.post(f"{URL}/{k2['id']}/tahsis", json={"satirlar": satirlar})
    assert r.status_code == 409, r.text
    detay = r.json()["detail"]
    assert detay["kod"] == "KIRALAMA_CAKISMA"
    assert "gerekçe" in detay["mesaj"]
    [cakisma] = detay["cakismalar"]
    assert cakisma["kiralama_no"] == k1["rental_no"]
    assert cakisma["kiralama_id"] == k1["id"]
    assert cakisma["seri_no"] == "CK-1"
    assert (cakisma["baslangic"], cakisma["bitis"]) == ("2026-11-01", "2026-11-05")
    # Müşteri adı uyarıda taşınmaz (çakışan kiralama kapsam dışı olabilir).
    assert "musteri" not in cakisma
    assert await hareket_sayisi(db, "TAHSIS") == tahsis_once
    assert await _aktif_tahsis_sayisi(db, cihaz) == 1

    # Onay var ama gerekçe boş → 400, yine yazılmaz.
    for gerekce in (None, "   "):
        r = await ist.post(
            f"{URL}/{k2['id']}/tahsis",
            json={"satirlar": satirlar, "cakisma_onay": True, "cakisma_gerekcesi": gerekce},
        )
        assert r.status_code == 400, r.text
    assert await _aktif_tahsis_sayisi(db, cihaz) == 1

    r = await ist.post(
        f"{URL}/{k2['id']}/tahsis",
        json={"satirlar": satirlar, "cakisma_onay": True, "cakisma_gerekcesi": GEREKCE},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "HAZIRLANIYOR"
    assert await _aktif_tahsis_sayisi(db, cihaz) == 2

    [kayit] = await _onay_denetimleri(db)
    assert (kayit.entity, kayit.entity_id) == ("rentals", str(k2["id"]))
    assert kayit.new_value["gerekce"] == GEREKCE
    assert kayit.new_value["islem"] == "tahsis"
    assert [c["kiralama_no"] for c in kayit.new_value["cakismalar"]] == [k1["rental_no"]]


async def test_cakisma_yoksa_onay_denetim_yazmaz(ist, db) -> None:
    """Gereksiz onay zararsız: çakışma yoksa gerekçe denetime düşmez."""
    _, seri, cihaz = await _iki_cihaz(db, ist)
    k = await planla(ist, await kiralama_ac(ist, await musteri_ac(db), [(seri, 1)]))
    r = await ist.post(
        f"{URL}/{k['id']}/tahsis",
        json={
            "satirlar": [{"kalem_id": kalem_id(k, seri), "kiralik_idler": [cihaz]}],
            "cakisma_onay": True,
            "cakisma_gerekcesi": GEREKCE,
        },
    )
    assert r.status_code == 200, r.text
    assert await _onay_denetimleri(db) == []


async def test_yari_acik_aralik_cakisma_sayilmaz(ist, db) -> None:
    """İade günü = sonraki çıkış günü: uyarı yok (aralık `[)`)."""
    _, seri, cihaz = await _iki_cihaz(db, ist)
    musteri = await musteri_ac(db)
    k1 = await planla(ist, await kiralama_ac(ist, musteri, [(seri, 1)]))
    await tahsis(ist, k1, [{"kalem_id": kalem_id(k1, seri), "kiralik_idler": [cihaz]}])
    k2 = await planla(
        ist, await kiralama_ac(ist, musteri, [(seri, 1)], bas="2026-11-05", bit="2026-11-07")
    )
    await tahsis(ist, k2, [{"kalem_id": kalem_id(k2, seri), "kiralik_idler": [cihaz]}])
    assert await _onay_denetimleri(db) == []


async def test_tarih_uzatma_cakismasi_uyari_ve_onay(ist, db) -> None:
    _, seri, cihaz = await _iki_cihaz(db, ist)
    musteri = await musteri_ac(db)
    k1 = await planla(ist, await kiralama_ac(ist, musteri, [(seri, 1)]))
    k1 = await tahsis(ist, k1, [{"kalem_id": kalem_id(k1, seri), "kiralik_idler": [cihaz]}])
    k2 = await planla(
        ist, await kiralama_ac(ist, musteri, [(seri, 1)], bas="2026-11-05", bit="2026-11-07")
    )
    await tahsis(ist, k2, [{"kalem_id": kalem_id(k2, seri), "kiralik_idler": [cihaz]}])

    kart = (await ist.get(f"{URL}/{k1['id']}")).json()
    govde = {"version": kart["version"], "bitis": "2026-11-06"}
    r = await ist.put(f"{URL}/{k1['id']}", json=govde)
    assert r.status_code == 409, r.text
    detay = r.json()["detail"]
    assert detay["kod"] == "KIRALAMA_CAKISMA"
    assert [c["kiralama_no"] for c in detay["cakismalar"]] == [k2["rental_no"]]
    assert (await ist.get(f"{URL}/{k1['id']}")).json()["bitis"] == "2026-11-05"

    r = await ist.put(
        f"{URL}/{k1['id']}",
        json={**govde, "cakisma_onay": True, "cakisma_gerekcesi": GEREKCE},
    )
    assert r.status_code == 200, r.text
    assert r.json()["bitis"] == "2026-11-06"
    db.expire_all()
    bitisler = {
        str(t.bitis)
        for t in (
            await db.scalars(select(RentalAllocation).where(RentalAllocation.rental_id == k1["id"]))
        ).all()
    }
    assert bitisler == {"2026-11-06"}
    [kayit] = await _onay_denetimleri(db)
    assert kayit.new_value["islem"] == "tarih"
