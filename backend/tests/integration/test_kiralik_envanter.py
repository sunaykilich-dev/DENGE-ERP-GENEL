"""Kiralık envanter: giriş, ekleme-yalnız defter, transfer, düzenleme, dönüş
kontrolü, kayıp/hurda, toplu giriş (TS-111, TS-115, TS-121, TS-102 kiralama tarafı)."""

import asyncio
import io

import pytest
from kiralama_ortak import (
    URL,
    bakiye,
    cihaz_durumlari,
    depo_ac,
    hazir_kiralama,
    istemci,
    kiralik_urun_ac,
    seri_idleri,
    stok_gir,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, RentalAsset, RentalCheck, RentalInventoryMovement

pytestmark = pytest.mark.integration


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("env_yon", "SERVIS_YONETICI")
    i = await istemci("env_yon")
    yield i
    await i.aclose()


async def test_giris_kurallari(ist, db, urun_ac) -> None:
    depo = await depo_ac(db, "EG-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "EG-SERI", seri=True)
    toplu = await kiralik_urun_ac(db, "EG-TOPLU", seri=False)
    katalogsuz = await kiralik_urun_ac(db, "EG-YOK", seri=False, katalog=False)
    imei = await urun_ac("EG-IMEI", "IMEI")

    def govde(urun, **kw):
        return {"product_id": urun.id, "depo_id": depo.id, **kw}

    # IMEI ürün kataloğa da envantere de giremez (E06-D05).
    r = await ist.post(f"{URL}/katalog", json={"product_id": imei.id, "birim": "GUVENLIK"})
    assert r.status_code == 400
    assert (await ist.post(f"{URL}/envanter", json=govde(imei, adet=1))).status_code == 400
    assert (await ist.post(f"{URL}/envanter", json=govde(katalogsuz, adet=1))).status_code == 400
    # KIRADA/KAYIP girişte kullanılamaz.
    r = await ist.post(f"{URL}/envanter", json=govde(toplu, adet=5, durum="KIRADA"))
    assert r.status_code == 400
    # Seri üründe seri zorunlu, toplu üründe seri girilmez.
    assert (await ist.post(f"{URL}/envanter", json=govde(seri, adet=2))).status_code == 400
    r = await ist.post(f"{URL}/envanter", json=govde(toplu, seriler=["X"], adet=1))
    assert r.status_code == 400
    sonuc = await stok_gir(ist, seri, depo, seriler=["sn-001", "SN-002"])
    assert len(sonuc["kiralik_idler"]) == 2
    # Mükerrer seri (normalize: büyük harf, kırpma) → 409.
    r = await ist.post(f"{URL}/envanter", json=govde(seri, seriler=["  SN-001 "]))
    assert r.status_code == 409, r.text
    await stok_gir(ist, toplu, depo, adet=40, durum="KONTROLDE")
    assert await bakiye(db, toplu, depo, "KONTROLDE") == 40
    assert await cihaz_durumlari(db, seri) == {"HAZIR": 2}


async def test_hareket_defteri_ekleme_yalniz_ve_sirali(ist, db) -> None:
    depo1 = await depo_ac(db, "HD-D1", birim="GUVENLIK")
    depo2 = await depo_ac(db, "HD-D2")  # birimsiz (ortak) kiralama deposu
    seri = await kiralik_urun_ac(db, "HD-SERI", seri=True)
    await stok_gir(ist, seri, depo1, seriler=["HD-1"])
    cihaz = (await seri_idleri(db, seri))[0]
    r = await ist.post(
        f"{URL}/envanter/transfer", json={"hedef_depo_id": depo2.id, "kiralik_idler": [cihaz]}
    )
    assert r.status_code == 200, r.text
    kart = (await ist.get(f"{URL}/envanter/{cihaz}")).json()
    assert kart["depo_id"] == depo2.id and kart["durum"] == "HAZIR"
    turler = [h["kind"] for h in kart["hareketler"]]
    assert turler == ["GIRIS", "TRANSFER"]
    zamanlar = [(h["at"], h["id"]) for h in kart["hareketler"]]
    assert zamanlar == sorted(zamanlar)
    # Değiştirme ucu yok; DB tetikleyicisi de UPDATE/DELETE'i reddeder.
    hid = kart["hareketler"][0]["id"]
    assert (await ist.patch(f"{URL}/envanter/hareketler/{hid}", json={})).status_code in (
        404,
        405,
    )
    with pytest.raises(DBAPIError):
        await db.execute(
            text("UPDATE rental_inventory_movements SET qty = 5 WHERE id = :i"), {"i": hid}
        )
    await db.rollback()
    with pytest.raises(DBAPIError):
        await db.execute(text("DELETE FROM rental_inventory_movements WHERE id = :i"), {"i": hid})
    await db.rollback()


async def test_esz_amanli_iki_toplu_transfer_bakiyeyi_eksiye_dusurmez(ist, db) -> None:
    depo1 = await depo_ac(db, "ET-D1", birim="GUVENLIK")
    depo2 = await depo_ac(db, "ET-D2", birim="GUVENLIK")
    toplu = await kiralik_urun_ac(db, "ET-BARIYER", seri=False)
    await stok_gir(ist, toplu, depo1, adet=50)
    govde = {
        "hedef_depo_id": depo2.id,
        "product_id": toplu.id,
        "kaynak_depo_id": depo1.id,
        "adet": 30,
    }
    r1, r2 = await asyncio.gather(
        ist.post(f"{URL}/envanter/transfer", json=govde),
        ist.post(f"{URL}/envanter/transfer", json=govde),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)
    assert await bakiye(db, toplu, depo1, "HAZIR") == 20
    assert await bakiye(db, toplu, depo2, "HAZIR") == 30


async def test_duzenleme_alan_kisitlari(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=1, on_ek="DZ")
    serbest_urun = await kiralik_urun_ac(db, "DZ-SERBEST", seri=True)
    await stok_gir(ist, serbest_urun, h["depo"], seriler=["FREE-1"])
    serbest = (await seri_idleri(db, serbest_urun))[0]
    tahsisli = h["cihazlar"][0]
    kart = (await ist.get(f"{URL}/envanter/{serbest}")).json()
    yol = f"{URL}/envanter/{serbest}"
    for alan, deger in (
        ("durum", "KIRADA"),
        ("warehouse_id", h["depo"].id),
        ("product_id", 1),
        ("birim", "HABERLESME"),
    ):
        r = await ist.patch(yol, json={"version": kart["version"], alan: deger})
        assert r.status_code == 400, (alan, r.text)
    r = await ist.patch(yol, json={"version": kart["version"], "serial_no": "FREE-1B"})
    assert r.status_code == 200, r.text
    assert r.json()["serial_no"] == "FREE-1B"
    assert r.json()["hareketler"][-1]["kind"] == "DUZENLEME"
    t_kart = (await ist.get(f"{URL}/envanter/{tahsisli}")).json()
    r = await ist.patch(
        f"{URL}/envanter/{tahsisli}", json={"version": t_kart["version"], "serial_no": "YENI"}
    )
    assert r.status_code == 409
    # Eksik notu tahsisliyken de düzenlenebilir.
    r = await ist.patch(
        f"{URL}/envanter/{tahsisli}", json={"version": t_kart["version"], "eksik_notu": "Kılıf"}
    )
    assert r.status_code == 200


async def test_donus_kontrolu(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=2, on_ek="DK", sevk=True)
    k = h["k"]
    c1, c2 = h["cihazlar"]
    # KIRADA cihaz kontrol edilemez (400).
    r = await ist.post(
        f"{URL}/envanter/kontrol", json={"satirlar": [{"kiralik_id": c1, "sonuc": "UYGUN"}]}
    )
    assert r.status_code == 400
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={
            "satirlar": [
                {"tahsis_id": t["id"], "sonuc": "IADE_ALINDI", "depo_id": h["depo"].id}
                for t in k["tahsisler"]
            ]
        },
    )
    assert r.status_code == 200
    # EKSIK açıklamasız → 400; hiçbir kontrol yazılmaz.
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={
            "satirlar": [{"kiralik_id": c1, "sonuc": "UYGUN"}, {"kiralik_id": c2, "sonuc": "EKSIK"}]
        },
    )
    assert r.status_code == 400
    assert await db.scalar(select(func.count()).select_from(RentalCheck)) == 0
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={
            "satirlar": [
                {"kiralik_id": c1, "sonuc": "UYGUN", "rental_id": k["id"]},
                {"kiralik_id": c2, "sonuc": "EKSIK", "aciklama": "Şarj aleti eksik"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    kontroller = r.json()["kontroller"]
    assert all(x["kontrol_eden"] and x["at"] for x in kontroller)
    assert await cihaz_durumlari(db, h["seri"]) == {"HAZIR": 1, "HAZIR_DEGIL": 1}
    kart = (await ist.get(f"{URL}/envanter/{c2}")).json()
    assert kart["eksik_notu"] == "Şarj aleti eksik"
    # HAZIR_DEGIL → yeniden kontrolde UYGUN → HAZIR.
    r = await ist.post(
        f"{URL}/envanter/kontrol", json={"satirlar": [{"kiralik_id": c2, "sonuc": "UYGUN"}]}
    )
    assert r.status_code == 200
    assert await cihaz_durumlari(db, h["seri"]) == {"HAZIR": 2}
    # HAZIR cihaz yeniden kontrol edilemez.
    r = await ist.post(
        f"{URL}/envanter/kontrol", json={"satirlar": [{"kiralik_id": c2, "sonuc": "UYGUN"}]}
    )
    assert r.status_code == 400


async def test_toplu_kontrol_on_cihaz_tek_istek(ist, db) -> None:
    depo = await depo_ac(db, "TK-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "TK-SERI", seri=True)
    await stok_gir(ist, seri, depo, seriler=[f"TK-{i}" for i in range(10)], durum="KONTROLDE")
    cihazlar = await seri_idleri(db, seri)
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={"satirlar": [{"kiralik_id": c, "sonuc": "UYGUN"} for c in cihazlar]},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["kontroller"]) == 10
    assert await cihaz_durumlari(db, seri) == {"HAZIR": 10}


async def test_toplu_urun_kontrolu_ve_bakiye(ist, db) -> None:
    depo = await depo_ac(db, "TU-D1", birim="GUVENLIK")
    toplu = await kiralik_urun_ac(db, "TU-TOPLU", seri=False)
    await stok_gir(ist, toplu, depo, adet=10, durum="KONTROLDE")
    satir = {"product_id": toplu.id, "depo_id": depo.id}
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={
            "satirlar": [
                {**satir, "adet": 8, "sonuc": "UYGUN"},
                {**satir, "adet": 2, "sonuc": "ARIZALI", "aciklama": "Kırık ayak"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert await bakiye(db, toplu, depo, "HAZIR") == 8
    assert await bakiye(db, toplu, depo, "HAZIR_DEGIL") == 2
    assert await bakiye(db, toplu, depo, "KONTROLDE") == 0
    # Bakiye yetmezse 409.
    r = await ist.post(
        f"{URL}/envanter/kontrol", json={"satirlar": [{**satir, "adet": 1, "sonuc": "UYGUN"}]}
    )
    assert r.status_code == 409
    # Hurda: gerekçe zorunlu; gerekçeli çıkış hareketi.
    hurda = {"product_id": toplu.id, "depo_id": depo.id, "adet": 2}
    assert (await ist.post(f"{URL}/envanter/hurda", json=hurda)).status_code == 400
    r = await ist.post(f"{URL}/envanter/hurda", json={**hurda, "gerekce": "Onarılamaz"})
    assert r.status_code == 200, r.text
    assert await bakiye(db, toplu, depo, "HAZIR_DEGIL") == 0
    assert await bakiye(db, toplu, None, "HURDA") == 2


async def test_kayip_bulundu_ve_atolye_kopru(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=2, on_ek="KB", sevk=True)
    k = h["k"]
    c1, c2 = h["cihazlar"]
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={
            "satirlar": [
                {"tahsis_id": k["tahsisler"][0]["id"], "sonuc": "KAYIP"},
                {
                    "tahsis_id": k["tahsisler"][1]["id"],
                    "sonuc": "IADE_ALINDI",
                    "depo_id": h["depo"].id,
                },
            ]
        },
    )
    assert r.status_code == 200, r.text
    govde = {"depo_id": h["depo"].id, "kiralik_id": c1}
    assert (await ist.post(f"{URL}/envanter/bulundu", json=govde)).status_code == 400
    r = await ist.post(f"{URL}/envanter/bulundu", json={**govde, "gerekce": "Sahada bulundu"})
    assert r.status_code == 200, r.text
    assert await cihaz_durumlari(db, h["seri"]) == {"KONTROLDE": 2}
    # Arızalı + atölye: KIRALAMA_TAKIP atölye kaydı açılır, cihaz ATOLYEDE (TS-102;
    # atölye teslimiyle dönüş `test_servis_uctan_uca_d2.py`'de).
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={
            "satirlar": [
                {
                    "kiralik_id": c2,
                    "sonuc": "ARIZALI",
                    "aciklama": "Açılmıyor",
                    "atolye_kaydi_ac": True,
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert (await ist.get(f"{URL}/envanter/{c2}")).json()["durum"] == "ATOLYEDE"
    # Hurda seri: KONTROLDE cihaz gerekçeyle hurdaya ayrılır, kayıt silinmez.
    r = await ist.post(f"{URL}/envanter/hurda", json={"kiralik_id": c1, "gerekce": "Ekran kırık"})
    assert r.status_code == 200, r.text
    assert (await ist.get(f"{URL}/envanter/{c1}")).json()["durum"] == "HURDA"


async def test_atolyeden_donus_kontrole_gider(ist, db) -> None:
    """TS-102: atölye teslim kancasının çağıracağı fonksiyon (D2-B bağlar)."""
    from app.clock import FakeClock
    from app.services.teknik_servis import kiralik_envanter as env

    depo = await depo_ac(db, "AD-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "AD-SERI", seri=True)
    await stok_gir(ist, seri, depo, seriler=["AD-1"], durum="HAZIR_DEGIL")
    cihaz = await db.get(RentalAsset, (await seri_idleri(db, seri))[0])
    await env.hareket_yaz(
        db,
        tur="ATOLYE",
        product_id=seri.id,
        qty=1,
        clock=FakeClock(),
        user=None,
        asset=cihaz,
        from_warehouse_id=depo.id,
        from_durum="HAZIR_DEGIL",
        to_durum="ATOLYEDE",
    )
    await env.atolyeden_dondu(db, cihaz.id, depo.id, user=None, clock=FakeClock())
    await db.commit()
    await db.refresh(cihaz)
    assert cihaz.durum == "KONTROLDE" and cihaz.warehouse_id == depo.id


def _csv(satirlar: list[str]) -> bytes:
    return ("Ürün Kodu,Seri No,Adet,Depo Kodu,Durum\n" + "\n".join(satirlar)).encode("utf-8")


async def test_toplu_giris_onizleme_onay(ist, db) -> None:
    depo = await depo_ac(db, "TG-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "TG-SERI", seri=True)
    toplu = await kiralik_urun_ac(db, "TG-TOPLU", seri=False)
    await stok_gir(ist, seri, depo, seriler=["VAR-1"])
    icerik = _csv(
        [
            "TG-SERI,YENI-1,,TG-D1,HAZIR",
            "TG-SERI,YENI-2,1,TG-D1,",
            "TG-SERI,YENI-1,,TG-D1,HAZIR",  # dosyada mükerrer
            "TG-SERI,VAR-1,,TG-D1,HAZIR",  # DB'de var
            "TG-TOPLU,,25,TG-D1,KONTROLDE",
            "TG-TOPLU,,abc,TG-D1,HAZIR",
            "YOK-KOD,,1,TG-D1,HAZIR",
        ]
    )
    once = await db.scalar(select(func.count()).select_from(RentalInventoryMovement))
    r = await ist.post(
        f"{URL}/envanter/toplu/onizleme", files={"file": ("giris.csv", icerik, "text/csv")}
    )
    assert r.status_code == 200, r.text
    on = r.json()
    assert on["toplam"] == 7 and on["gecerli"] == 3 and on["hatali"] == 4
    assert await db.scalar(select(func.count()).select_from(RentalInventoryMovement)) == once
    # Özet tutmazsa 409, hiçbir şey yazılmaz.
    r = await ist.post(
        f"{URL}/envanter/toplu/onayla",
        files={"file": ("giris.csv", icerik + b"\n", "text/csv")},
        data={"sha256": on["sha256"]},
    )
    assert r.status_code == 409
    r = await ist.post(
        f"{URL}/envanter/toplu/onayla",
        files={"file": ("giris.csv", icerik, "text/csv")},
        data={"sha256": on["sha256"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["yazilan_satir"] == 3 and r.json()["toplam_adet"] == 27
    assert await cihaz_durumlari(db, seri) == {"HAZIR": 3}
    assert await bakiye(db, toplu, depo, "KONTROLDE") == 25
    sablon = await ist.get(f"{URL}/envanter/sablon.xlsx")
    assert sablon.status_code == 200
    from openpyxl import load_workbook

    basliklar = [c.value for c in load_workbook(io.BytesIO(sablon.content)).active[1]]
    assert "Ürün Kodu" in basliklar and "Seri No" in basliklar


async def test_katalog_birim_degisikligi_ve_pasiflestirme(ist, db) -> None:
    depo = await depo_ac(db, "KT-D1", birim="GUVENLIK")
    urun = await kiralik_urun_ac(db, "KT-1", seri=False)
    katalog = (await ist.get(f"{URL}/katalog")).json()
    satir = next(x for x in katalog if x["product_id"] == urun.id)
    r = await ist.patch(f"{URL}/katalog/{satir['id']}", json={"birim": "HABERLESME"})
    assert r.status_code == 200, r.text  # envanteri yok: birim değişebilir
    r = await ist.patch(f"{URL}/katalog/{satir['id']}", json={"birim": "GUVENLIK"})
    assert r.status_code == 200
    await stok_gir(ist, urun, depo, adet=3)
    r = await ist.patch(f"{URL}/katalog/{satir['id']}", json={"birim": "HABERLESME"})
    assert r.status_code == 409
    r = await ist.patch(f"{URL}/katalog/{satir['id']}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    # Pasif üründe yeni giriş yok.
    r = await ist.post(
        f"{URL}/envanter", json={"product_id": urun.id, "depo_id": depo.id, "adet": 1}
    )
    assert r.status_code == 400
    r = await ist.post(f"{URL}/katalog", json={"product_id": urun.id, "birim": "GUVENLIK"})
    assert r.status_code == 409  # profil zaten var (silinmez, pasifleşir)
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.entity == "rental_catalog_items")
        )
        >= 2
    )


async def test_envanterli_urunde_kimlik_tipi_degismez(ist, db, kullanici_ac) -> None:
    """TS-118: kiralık envanteri olan ürünün seri takibi ürün kartında değişmez (409)."""
    depo = await depo_ac(db, "KT-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "KT-SERI", seri=True)
    bos = await kiralik_urun_ac(db, "KT-BOS", seri=True)
    await stok_gir(ist, seri, depo, seriler=["KT-1"])
    await kullanici_ac("kt_admin", "ADMIN")
    adm = await istemci("kt_admin")
    try:
        r = await adm.patch(f"/api/urunler/{seri.id}", json={"identity_kind": "YOK"})
        assert r.status_code == 409, r.text
        await db.refresh(seri)
        assert seri.identity_kind == "SERI_NO"  # veri değişmedi
        # Envanteri olmayan katalog ürününde değişiklik serbest.
        r = await adm.patch(f"/api/urunler/{bos.id}", json={"identity_kind": "YOK"})
        assert r.status_code == 200, r.text
    finally:
        await adm.aclose()
