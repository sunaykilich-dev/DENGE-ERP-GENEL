"""Kiralama kapsam ve yetki (TS-110…122; plan §1.2, §4.5).

- RBAC: her izin kümesi için yetkisiz 403, yetkili 2xx.
- Kapsam: iki birimden iki kullanıcı; kapsam dışı `{kiralama_id}`,
  `{kiralik_id}`, `{katalog_id}` uçlarının HEPSİ 404 döner ve hiçbir veri
  değişmez (uç listesi router'dan üretilir — yeni uç unutulmaz). Liste, KPI,
  Excel ve uyarı sayıları yalnız kendi birimi; birimsiz kullanıcı hiçbir şey
  görmez.
"""

from io import BytesIO

import pytest
from kiralama_ortak import (
    URL,
    depo_ac,
    hazir_kiralama,
    istemci,
    kiralik_urun_ac,
    musteri_ac,
    seri_idleri,
    stok_gir,
)
from sqlalchemy import func, inspect, select
from yetki_tarama import cagir, uclar, yol_doldur, yol_parametreleri

from app.models import (
    AuditLog,
    Rental,
    RentalAllocation,
    RentalAsset,
    RentalCatalogItem,
    RentalCheck,
    RentalContact,
    RentalEvent,
    RentalInventoryMovement,
    RentalItem,
    ServiceOrder,
    User,
)
from app.permissions import PERMISSIONS

pytestmark = pytest.mark.integration

_SAYILAN = (
    AuditLog,
    RentalEvent,
    RentalInventoryMovement,
    RentalAllocation,
    RentalCheck,
    RentalItem,
    RentalContact,
    ServiceOrder,
)
_PARAM_HEDEFI = {
    "kiralama_id": "kiralama",
    "kiralik_id": "kiralik",
    "katalog_id": "katalog",
    "kod": "kiralik",  # karekod etiketi: değer cihazın etiket kodu
}
# Kimlik yerine başka alanla adreslenen parametreler.
_PARAM_ALANI = {"kod": "etiket_kodu"}


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac, rol_ac):
    tum = list(PERMISSIONS)
    await rol_ac("T_KIR_BIRIM", tum, "KENDI_BIRIMI")
    await kullanici_ac("kap_yon", "SERVIS_YONETICI")
    await birimli_kullanici_ac("kap_guv", "T_KIR_BIRIM", ["GUVENLIK"])
    await birimli_kullanici_ac("kap_hab", "T_KIR_BIRIM", ["HABERLESME"])
    await birimli_kullanici_ac("kap_bos", "T_KIR_BIRIM", [])
    ist = {ad: await istemci(ad) for ad in ("kap_yon", "kap_guv", "kap_hab", "kap_bos")}
    yon = ist["kap_yon"]
    guv = await hazir_kiralama(db, yon, seri_adet=1, toplu_adet=2, on_ek="KG", sevk=True)
    hab = await hazir_kiralama(
        db, yon, seri_adet=2, toplu_adet=2, on_ek="KH", birim="HABERLESME", sevk=True
    )
    yield {"ist": ist, "guv": guv, "hab": hab}
    for i in ist.values():
        await i.aclose()


async def _anlik(db, kayitlar) -> list[dict]:
    sonuc = []
    for k in kayitlar:
        db.expire(k)
        await db.refresh(k)
        sonuc.append({a.key: getattr(k, a.key) for a in inspect(k).mapper.column_attrs})
    sayilar = {
        m.__tablename__: await db.scalar(select(func.count()).select_from(m)) for m in _SAYILAN
    }
    return [*sonuc, sayilar]


def _kiralama_uclari():
    from app.main import app

    return [
        u
        for u in uclar(app)
        if u.yol.startswith(URL) and set(yol_parametreleri(u.yol)) & set(_PARAM_HEDEFI)
    ]


async def test_uc_listesi_bos_degil_ve_parametreler_taninir() -> None:
    from app.main import app

    bilinmeyen = [
        u.ad
        for u in uclar(app)
        if u.yol.startswith(URL)
        and yol_parametreleri(u.yol)
        and not set(yol_parametreleri(u.yol)) & set(_PARAM_HEDEFI)
    ]
    assert not bilinmeyen, bilinmeyen
    assert len(_kiralama_uclari()) >= 15


async def test_kapsam_disi_kimlik_404_ve_veri_degismez(ortam, db) -> None:
    hab = ortam["hab"]
    kiralama = await db.get(Rental, hab["k"]["id"])
    kiralik = await db.get(RentalAsset, hab["cihazlar"][0])
    kiralik.etiket_kodu = "KH-ETIKET-1"
    await db.commit()
    katalog = await db.scalar(
        select(RentalCatalogItem).where(RentalCatalogItem.product_id == hab["seri"].id)
    )
    hedefler = {"kiralama": kiralama, "kiralik": kiralik, "katalog": katalog}
    hatalar = []
    for uc in _kiralama_uclari():
        degerler = {
            p: getattr(hedefler[_PARAM_HEDEFI[p]], _PARAM_ALANI.get(p, "id"))
            for p in yol_parametreleri(uc.yol)
            if p in _PARAM_HEDEFI
        }
        once = await _anlik(db, hedefler.values())
        r = await cagir(ortam["ist"]["kap_guv"], uc, yol_doldur(uc.yol, degerler))
        sonra = await _anlik(db, hedefler.values())
        if r.status_code == 422:
            hatalar.append(f"{uc.ad}: 422 — gövde örneği ekleyin")
        elif r.status_code != 404:
            hatalar.append(f"{uc.ad}: {r.status_code} (404 bekleniyordu) {r.text[:120]}")
        if once != sonra:
            hatalar.append(f"{uc.ad}: kapsam dışı kayıt DEĞİŞTİ")
    assert not hatalar, "\n".join(hatalar)
    # Ek uçları da kapsamı uygular.
    r = await ortam["ist"]["kap_guv"].get(f"/api/ekler/rentals/{kiralama.id}")
    assert r.status_code == 404
    r = await ortam["ist"]["kap_guv"].get(f"/api/ekler/rental_assets/{kiralik.id}")
    assert r.status_code == 404
    r = await ortam["ist"]["kap_hab"].get(f"/api/ekler/rentals/{kiralama.id}")
    assert r.status_code == 200


async def test_liste_ozet_excel_envanter_yalniz_kendi_birimi(ortam, db) -> None:
    ist, guv, hab = ortam["ist"], ortam["guv"], ortam["hab"]
    r = await ist["kap_guv"].get(URL)
    assert [x["id"] for x in r.json()] == [guv["k"]["id"]]
    assert r.headers["X-Toplam-Kayit"] == "1"
    ozet = {k["kod"]: k["deger"] for k in (await ist["kap_guv"].get(f"{URL}/ozet")).json()}
    assert ozet["kirada"] == 1
    r = await ist["kap_guv"].get(f"{URL}/liste.xlsx", params={"ids": str(hab["k"]["id"])})
    from openpyxl import load_workbook

    assert load_workbook(BytesIO(r.content)).active.max_row == 1  # yalnız başlık
    cihazlar = (await ist["kap_guv"].get(f"{URL}/envanter")).json()
    assert {c["birim"] for c in cihazlar} == {"GUVENLIK"}
    bakiyeler = (await ist["kap_guv"].get(f"{URL}/envanter/bakiyeler")).json()
    assert {b["urun_kodu"] for b in bakiyeler} <= {"KG-SERI", "KG-TOPLU"}
    katalog = (await ist["kap_guv"].get(f"{URL}/katalog")).json()
    assert {k["birim"] for k in katalog} == {"GUVENLIK"}
    assert {d["code"] for d in (await ist["kap_guv"].get(f"{URL}/depolar")).json()} == {"KG-D1"}
    # Birimsiz kullanıcı hiçbir şey görmez (fail-closed).
    bos = ist["kap_bos"]
    r = await bos.get(URL)
    assert r.json() == [] and r.headers["X-Toplam-Kayit"] == "0"
    assert (await bos.get(f"{URL}/envanter")).json() == []
    assert (await bos.get(f"{URL}/{guv['k']['id']}")).status_code == 404


async def test_kpi_ve_uyari_sayisi_liste_toplamina_esit(ortam, db, client) -> None:
    from datetime import date

    from app.services.teknik_servis import kiralama_raporlar

    ist = ortam["ist"]
    # İki kiralamanın iade günü geçmiş olsun (saat ilerletilmez: oturum düşer).
    for h in (ortam["guv"], ortam["hab"]):
        kayit = await db.get(Rental, h["k"]["id"])
        kayit.baslangic, kayit.bitis = date(2025, 12, 1), date(2025, 12, 10)
    await db.commit()
    for ad, beklenen in (("kap_guv", 1), ("kap_hab", 1), ("kap_yon", 2)):
        ozet = {k["kod"]: k["deger"] for k in (await ist[ad].get(f"{URL}/ozet")).json()}
        liste = await ist[ad].get(URL, params={"kpi": "geciken"})
        assert ozet["geciken"] == int(liste.headers["X-Toplam-Kayit"]) == beklenen
        user = await db.scalar(select(User).where(User.username == ad))
        uyarilar = {u.kod: u.adet for u in await kiralama_raporlar.uyarilar(db, user, client.clock)}
        assert uyarilar["kiralama.geciken_iade"] == beklenen
    assert (await ist["kap_guv"].get(URL, params={"kpi": "yok"})).status_code == 400


async def test_kapsam_disi_birime_kiralama_ve_giris_yapilamaz(ortam, db) -> None:
    ist = ortam["ist"]["kap_guv"]
    hab = ortam["hab"]
    once = await db.scalar(select(func.count()).select_from(Rental))
    r = await ist.post(
        URL,
        json={
            "birim": "HABERLESME",
            "customer_id": hab["musteri"].id,
            "baslangic": "2026-11-01",
            "bitis": "2026-11-03",
            "kalemler": [{"product_id": hab["toplu"].id, "qty": 1}],
        },
    )
    assert r.status_code == 404
    assert await db.scalar(select(func.count()).select_from(Rental)) == once
    # Gövdedeki başka birim ürünü (katalog öğesi) → 403.
    r = await ist.post(
        f"{URL}/envanter",
        json={"product_id": hab["toplu"].id, "depo_id": hab["depo"].id, "adet": 1},
    )
    assert r.status_code == 403
    # Gövdedeki kapsam dışı cihaz → 404.
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={"satirlar": [{"kiralik_id": hab["cihazlar"][0], "sonuc": "UYGUN"}]},
    )
    assert r.status_code == 404


async def test_rbac_izin_kumeleri(client, db, kullanici_ac, birimli_kullanici_ac) -> None:
    await kullanici_ac("rb_yon", "SERVIS_YONETICI")
    await birimli_kullanici_ac("rb_op", "SERVIS_OPERASYON", ["GUVENLIK"])
    await birimli_kullanici_ac("rb_depo", "KIRALAMA_DEPO", ["GUVENLIK"])
    await birimli_kullanici_ac("rb_tek", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    yon, op, depo_ist, tek = [await istemci(a) for a in ("rb_yon", "rb_op", "rb_depo", "rb_tek")]
    try:
        depo = await depo_ac(db, "RB-D1", birim="GUVENLIK")
        urun = await kiralik_urun_ac(db, "RB-SERI", seri=True)
        musteri = await musteri_ac(db)
        # Teknisyende kiralama.gor yok (en az yetki): liste 403.
        assert (await tek.get(URL)).status_code == 403
        # kiralama.yaz var, kiralama.envanter yok → envanter girişi 403.
        govde = {"product_id": urun.id, "depo_id": depo.id, "seriler": ["RB-1", "RB-2"]}
        assert (await op.post(f"{URL}/envanter", json=govde)).status_code == 403
        assert (await depo_ist.post(f"{URL}/envanter", json=govde)).status_code == 201
        # Talep: operasyon açar; depo açamaz.
        talep = {
            "birim": "GUVENLIK",
            "customer_id": musteri.id,
            "baslangic": "2026-11-01",
            "bitis": "2026-11-03",
            "kalemler": [{"product_id": urun.id, "qty": 1}],
        }
        assert (await depo_ist.post(URL, json=talep)).status_code == 403
        r = await op.post(URL, json=talep)
        assert r.status_code == 201, r.text
        k = r.json()
        # Başlık PUT: depoya 403; planla operasyonda.
        r = await depo_ist.put(f"{URL}/{k['id']}", json={"version": k["version"], "notes": "x"})
        assert r.status_code == 403
        assert (await op.post(f"{URL}/{k['id']}/planla")).status_code == 200
        cihaz = (await seri_idleri(db, urun))[0]
        tahsis = {"satirlar": [{"kalem_id": k["kalemler"][0]["id"], "kiralik_idler": [cihaz]}]}
        assert (await op.post(f"{URL}/{k['id']}/tahsis", json=tahsis)).status_code == 403
        assert (await depo_ist.post(f"{URL}/{k['id']}/tahsis", json=tahsis)).status_code == 200
        assert (await op.post(f"{URL}/{k['id']}/sevk", json={})).status_code == 403
        assert (await depo_ist.post(f"{URL}/{k['id']}/sevk", json={})).status_code == 200
        # Excel servis_rapor.disaaktar ister: depoda yok.
        assert (await depo_ist.get(f"{URL}/liste.xlsx")).status_code == 403
        assert (await yon.get(f"{URL}/liste.xlsx")).status_code == 200
        # Katalog: envanter izni.
        await stok_gir(depo_ist, urun, depo, seriler=["RB-3"])
        assert (await op.get(f"{URL}/katalog")).status_code == 200
        r = await op.post(f"{URL}/katalog", json={"product_id": urun.id, "birim": "GUVENLIK"})
        assert r.status_code == 403
    finally:
        for i in (yon, op, depo_ist, tek):
            await i.aclose()
