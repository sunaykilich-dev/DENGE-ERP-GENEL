"""Kiralama raporları ve sahada cihaz değişimi (TS-195, E06-21 / E06-20).

- Raporlar kiralama router'ında, `servis_rapor.gor + kiralama.gor`; Excel ek
  olarak `servis_rapor.disaaktar`; fiyat kolonu yok; birim kapsamı.
- Geciken iade sayısı = `?kpi=geciken` listesinin `X-Toplam-Kayit`'ı.
- Süre kaydı olmayan aşama "EKSIK".
- Değişim: yeni seri tahsiste, eski seri KONTROLDE, `DEGISIM` hareketleri;
  başka kiralamaya rezervli yeni cihaz 409; kapsam dışı kiralama 404 ve veri
  değişmez.
"""

from io import BytesIO

import pytest
from kiralama_ortak import (
    URL,
    depo_ac,
    hazir_kiralama,
    istemci,
    kalem_id,
    kiralama_ac,
    kiralik_urun_ac,
    planla,
    seri_idleri,
    stok_gir,
    tahsis,
)
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    Rental,
    RentalAllocation,
    RentalAsset,
    RentalInventoryMovement,
)

pytestmark = pytest.mark.integration

RAPOR = f"{URL}/raporlar"


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("krp_yon", "SERVIS_YONETICI")
    i = await istemci("krp_yon")
    yield i
    await i.aclose()


def _satir(rapor: dict, depo_id, kod: str) -> dict:
    return next(s for s in rapor["satirlar"] if s["depo_id"] == depo_id and s["urun_kodu"] == kod)


async def test_depo_durumu_rezerve_serbest_ve_kirada(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=2, toplu_adet=5, on_ek="RD")
    await stok_gir(ist, h["toplu"], h["depo"], adet=3)
    r = await ist.get(f"{RAPOR}/depo-durumu")
    assert r.status_code == 200, r.text
    toplu = _satir(r.json(), h["depo"].id, "RD-TOPLU")
    seri = _satir(r.json(), h["depo"].id, "RD-SERI")
    assert (toplu["hazir"], toplu["rezerve"], toplu["serbest"], toplu["kirada"]) == (8, 5, 3, 0)
    assert (seri["hazir"], seri["rezerve"], seri["serbest"]) == (2, 2, 0)
    assert "fiyat" not in toplu and "tutar" not in toplu
    assert (await ist.post(f"{URL}/{h['k']['id']}/sevk", json={})).status_code == 200
    r = await ist.get(f"{RAPOR}/depo-durumu")
    toplu = _satir(r.json(), h["depo"].id, "RD-TOPLU")
    seri = _satir(r.json(), h["depo"].id, "RD-SERI")
    assert (toplu["hazir"], toplu["rezerve"], toplu["kirada"]) == (3, 0, 5)
    assert (seri["hazir"], seri["kirada"]) == (0, 2)
    depo = next(d for d in r.json()["depolar"] if d["depo_id"] == h["depo"].id)
    assert depo["kirada"] == 7


async def test_geciken_iade_sayisi_liste_ile_ayni_ve_asama_suresi_eksik(
    client, ist, db, kullanici_ac
) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=1, on_ek="GI", sevk=True)
    k = h["k"]
    r = await ist.post(f"{URL}/{k['id']}/servis-isi", json={"tur": "KURULUM"})
    assert r.status_code == 201, r.text
    client.clock.advance(days=320)  # 2026-11-17: iade günü 5 Kasım
    ist2 = await istemci("krp_yon")
    try:
        r = await ist2.get(f"{RAPOR}/geciken-iade")
        assert r.status_code == 200, r.text
        (satir,) = r.json()
        assert satir["rental_no"] == k["rental_no"]
        assert satir["gecikme_gun"] == 12
        assert satir["musteride_adet"] == 1 and satir["seriler"] == ["GI-S0"]
        assert satir["asama_sureleri"]["KURULUM"]["durum"] == "EKSIK"
        assert satir["asama_sureleri"]["KURULUM"]["dk"] is None
        assert satir["asama_sureleri"]["TOPLAMA"]["durum"] == "IS_YOK"
        liste = await ist2.get(URL, params={"kpi": "geciken"})
        assert liste.headers["X-Toplam-Kayit"] == r.headers["X-Toplam-Kayit"] == "1"
        x = await ist2.get(f"{RAPOR}/geciken-iade.xlsx")
        assert x.status_code == 200
        satirlar = list(load_workbook(BytesIO(x.content)).active.iter_rows(values_only=True))
        assert satirlar[1][8] == "Eksik" and len(satirlar) == 2
        assert not any("Fiyat" in str(b) or "Tutar" in str(b) for b in satirlar[0])
        assert await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "rapor.disaaktar", AuditLog.entity == "rentals")
        )
    finally:
        await ist2.aclose()


async def test_kontrolde_bekleme(client, ist, db) -> None:
    depo = await depo_ac(db, "KB-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "KB-SERI", seri=True)
    toplu = await kiralik_urun_ac(db, "KB-TOPLU", seri=False)
    await stok_gir(ist, seri, depo, seriler=["KB-1", "KB-2"], durum="KONTROLDE")
    await stok_gir(ist, toplu, depo, adet=4, durum="KONTROLDE")
    client.clock.advance(days=9)
    ist2 = await istemci("krp_yon")
    try:
        r = await ist2.get(f"{RAPOR}/kontrolde-bekleme")
        assert r.status_code == 200, r.text
        rapor = r.json()
        assert {s["serial_no"] for s in rapor["seri"]} == {"KB-1", "KB-2"}
        assert all(s["bekleme_gun"] == 9 and s["uzun"] for s in rapor["seri"])
        (t,) = rapor["toplu"]
        assert t["adet"] == 4 and t["bekleme_gun"] == 9
        liste = await ist2.get(f"{URL}/envanter", params={"durum": "KONTROLDE"})
        assert int(liste.headers["X-Toplam-Kayit"]) == len(rapor["seri"])
        assert (await ist2.get(f"{RAPOR}/kontrolde-bekleme.xlsx")).status_code == 200
    finally:
        await ist2.aclose()


async def test_rapor_rbac_ve_birim_kapsami(client, ist, db, birimli_kullanici_ac) -> None:
    await hazir_kiralama(db, ist, toplu_adet=2, on_ek="RB", sevk=True)
    # KIRALAMA_DEPO: kiralama.gor + servis_rapor.gor var, disaaktar yok.
    await birimli_kullanici_ac("kdepo_g", "KIRALAMA_DEPO", ["GUVENLIK"])
    await birimli_kullanici_ac("kdepo_h", "KIRALAMA_DEPO", ["HABERLESME"])
    # SERVIS_OPERASYON: kiralama.gor var, servis_rapor.gor yok.
    await birimli_kullanici_ac("kops", "SERVIS_OPERASYON", ["GUVENLIK"])
    g = await istemci("kdepo_g")
    hb = await istemci("kdepo_h")
    o = await istemci("kops")
    try:
        r = await g.get(f"{RAPOR}/depo-durumu")
        assert r.status_code == 200 and r.json()["satirlar"]
        assert (await g.get(f"{RAPOR}/depo-durumu.xlsx")).status_code == 403
        r = await hb.get(f"{RAPOR}/depo-durumu")
        assert r.status_code == 200 and r.json()["satirlar"] == []
        for yol in ("depo-durumu", "geciken-iade", "kontrolde-bekleme"):
            assert (await o.get(f"{RAPOR}/{yol}")).status_code == 403
        assert (await ist.get(f"{RAPOR}/depo-durumu.xlsx")).status_code == 200
    finally:
        for i in (g, hb, o):
            await i.aclose()


# --- Sahada cihaz değişimi (E06-20) ---------------------------------------------------------


async def _degisim_ortami(db, ist):
    h = await hazir_kiralama(db, ist, seri_adet=1, on_ek="DG", sevk=True)
    await stok_gir(ist, h["seri"], h["depo"], seriler=["DG-YENI", "DG-REZ"])
    cihazlar = await seri_idleri(db, h["seri"])
    eski_cihaz = h["cihazlar"][0]
    yeni, rezervli = [c for c in cihazlar if c != eski_cihaz]
    tahsis_id = next(t["id"] for t in h["k"]["tahsisler"] if t["kiralik_id"] == eski_cihaz)
    return h, eski_cihaz, yeni, rezervli, tahsis_id


async def test_degisim_yeni_seri_kalemde_eski_kontrolde(ist, db) -> None:
    h, eski, yeni, _, tahsis_id = await _degisim_ortami(db, ist)
    k = h["k"]
    r = await ist.post(
        f"{URL}/{k['id']}/degisim",
        json={
            "eski_tahsis_id": tahsis_id,
            "yeni_kiralik_id": yeni,
            "iade_depo_id": h["depo"].id,
            "not": "Ekran arızası",
        },
    )
    assert r.status_code == 200, r.text
    kart = r.json()
    assert kart["status"] == k["status"]
    aktif = [t for t in kart["tahsisler"] if t["durum"] == "AKTIF"]
    assert [t["seri"] for t in aktif] == ["DG-YENI"]
    assert aktif[0]["replaced_allocation_id"] == tahsis_id and aktif[0]["musteride"] == 1
    eski_t = next(t for t in kart["tahsisler"] if t["id"] == tahsis_id)
    assert eski_t["durum"] == "KAPANDI" and eski_t["musteride"] == 0
    assert (await db.get(RentalAsset, eski, populate_existing=True)).durum == "KONTROLDE"
    assert (await db.get(RentalAsset, yeni, populate_existing=True)).durum == "KIRADA"
    hareketler = (
        await db.scalars(
            select(RentalInventoryMovement).where(RentalInventoryMovement.kind == "DEGISIM")
        )
    ).all()
    assert {h_.asset_id for h_ in hareketler} == {eski, yeni}
    # Eski cihazın geçmişinde değişim görünür.
    gecmis = (await ist.get(f"{URL}/envanter/{eski}")).json()["hareketler"]
    assert gecmis[-1]["kind"] == "DEGISIM" and "değişim" in gecmis[-1]["note"]


async def test_degisim_rezervli_cihaz_409_ve_hazir_olmayan(ist, db) -> None:
    h, _, _, rezervli, tahsis_id = await _degisim_ortami(db, ist)
    # Rezervli cihaz: aynı tarihlerde başka bir kiralamaya tahsisli.
    k2 = await kiralama_ac(ist, h["musteri"], [(h["seri"], 1)], bas="2026-11-02", bit="2026-11-04")
    await planla(ist, k2)
    await tahsis(ist, k2, [{"kalem_id": kalem_id(k2, h["seri"]), "kiralik_idler": [rezervli]}])
    once = await db.scalar(select(func.count()).select_from(RentalInventoryMovement))
    r = await ist.post(
        f"{URL}/{h['k']['id']}/degisim",
        json={
            "eski_tahsis_id": tahsis_id,
            "yeni_kiralik_id": rezervli,
            "iade_depo_id": h["depo"].id,
        },
    )
    assert r.status_code == 409, r.text
    assert await db.scalar(select(func.count()).select_from(RentalInventoryMovement)) == once
    # Kirada olan (eski) cihaz yeni cihaz olarak seçilemez: 400.
    r = await ist.post(
        f"{URL}/{h['k']['id']}/degisim",
        json={
            "eski_tahsis_id": tahsis_id,
            "yeni_kiralik_id": h["cihazlar"][0],
            "iade_depo_id": h["depo"].id,
        },
    )
    assert r.status_code == 400


async def test_degisim_sevk_oncesi_409_ve_kapsam_404(ist, db, birimli_kullanici_ac) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=1, on_ek="DS")
    await stok_gir(ist, h["seri"], h["depo"], seriler=["DS-YENI"])
    yeni = (await seri_idleri(db, h["seri"]))[-1]
    tahsis_id = h["k"]["tahsisler"][0]["id"]
    govde = {"eski_tahsis_id": tahsis_id, "yeni_kiralik_id": yeni, "iade_depo_id": h["depo"].id}
    assert (await ist.post(f"{URL}/{h['k']['id']}/degisim", json=govde)).status_code == 409
    # Başka birim kullanıcısı (aşama yetkili): 404 ve hiçbir şey değişmez.
    await birimli_kullanici_ac("hab_sef_k", "SERVIS_SEF", ["HABERLESME"])
    hb = await istemci("hab_sef_k")
    try:
        k = await db.get(Rental, h["k"]["id"])
        surum = k.version
        r = await hb.post(f"{URL}/{h['k']['id']}/degisim", json=govde)
        assert r.status_code == 404
        await db.refresh(k)
        assert k.version == surum
        assert (
            await db.scalar(
                select(func.count())
                .select_from(RentalAllocation)
                .where(RentalAllocation.rental_id == k.id)
            )
            == 1
        )
    finally:
        await hb.aclose()
