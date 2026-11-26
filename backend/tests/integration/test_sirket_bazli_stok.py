"""Şirket bazlı ürün / cihaz / stok / hat (migration fcl000000001) — gerçek kodla.

Sahip kararı (2026-11-23): her şirket yalnız kendi kalemlerini görür.
- ürün: `sirket` NULL = ortak (herkese), dolu = yalnız o şirkete;
- cihaz: ürününün şirketi; ortak ürünün cihazı herkese;
- depo: biriminin şirketi; birimsiz depo ortak;
- hat: `sirket` = etkin şirket; yeni hat etkin şirketi alır.
Stok/hat/cihaz ekranları üç şirkete açıktır (MOBİLİTE kapısı kalktı); operatör
senkronu MOBİLİTE'ye kapalı kalır.
"""

import pytest
from servis_yardimci import giris

from app.models import KullaniciSirketi, SimCard, Warehouse

pytestmark = [pytest.mark.integration, pytest.mark.sirket_ayrimi]


async def _sec(client, kod: str) -> None:
    r = await client.put("/api/oturum/aktif-sirket", json={"kod": kod})
    assert r.status_code == 200, r.text


@pytest.fixture
async def veri(db, urun_ac, cihaz_ac):
    """Her şirketten ürün + cihaz + hat, bir ortak ürün ve şirket depoları."""
    mob = await urun_ac("MOB-L300", sirket="MOBILITE")
    elk = await urun_ac("ELK-KAM", identity_kind="SERI_NO", sirket="ELEKTRONIK")
    tel = await urun_ac("TEL-TELSIZ", identity_kind="SERI_NO", sirket="TELEKOM")
    ortak = await urun_ac("ORTAK-KABLO", identity_kind="YOK", type="AKSESUAR")
    cihazlar = {
        "MOB": await cihaz_ac(imei="862000000000101", urun=mob),
        "ELK": await cihaz_ac(serial_no="ELK-SN-1", urun=elk),
        "TEL": await cihaz_ac(serial_no="TEL-SN-1", urun=tel),
    }
    hatlar = {
        "MOB": SimCard(iccid="8990011111111111111", sirket="MOBILITE"),
        "TEL": SimCard(iccid="8990022222222222222", sirket="TELEKOM"),
    }
    depolar = {
        "ORTAK": Warehouse(code="SB-ORTAK", name="Ortak Depo"),
        "ELK": Warehouse(code="SB-ELK", name="Güvenlik Deposu", birim="GUVENLIK"),
        "TEL": Warehouse(code="SB-TEL", name="Haberleşme Deposu", birim="HABERLESME"),
    }
    db.add_all([*hatlar.values(), *depolar.values()])
    await db.commit()
    return {
        "urun": {"MOB": mob, "ELK": elk, "TEL": tel, "ORTAK": ortak},
        "cihaz": cihazlar,
        "hat": hatlar,
        "depo": depolar,
    }


@pytest.fixture
async def depocu(db, client, kullanici_ac):
    """Üç şirkete üye depo kullanıcısı (DEPO rolü, birimsiz)."""
    kisi = await kullanici_ac("depocu", "DEPO")
    for kod in ("TELEKOM", "ELEKTRONIK", "MOBILITE"):
        db.add(KullaniciSirketi(user_id=kisi.id, sirket_kod=kod))
    await db.commit()
    await giris(client, "depocu")
    return kisi


async def _urun_kodlari(client) -> set[str]:
    r = await client.get("/api/urunler", params={"pasifler": True})
    assert r.status_code == 200, r.text
    return {u["code"] for u in r.json()}


async def test_elektronik_kendi_ve_ortak_urunleri_gorur(client, veri, depocu) -> None:
    await _sec(client, "ELEKTRONIK")
    assert await _urun_kodlari(client) == {"ELK-KAM", "ORTAK-KABLO"}
    u = veri["urun"]
    assert (await client.get(f"/api/urunler/{u['MOB'].id}")).status_code == 404
    r = await client.get(f"/api/urunler/{u['ELK'].id}")
    assert r.status_code == 200 and r.json()["sirket"] == "ELEKTRONIK"
    r = await client.get(f"/api/urunler/{u['ORTAK'].id}")
    assert r.status_code == 200 and r.json()["sirket"] is None
    # Arama da aynı kuraldan
    r = await client.get("/api/arama", params={"q": "MOB-L300"})
    assert all(s["tur"] != "URUN" for s in r.json())


async def test_mobilite_kendi_urunlerini_gorur(client, veri, depocu) -> None:
    await _sec(client, "MOBILITE")
    assert await _urun_kodlari(client) == {"MOB-L300", "ORTAK-KABLO"}
    markalar = (await client.get("/api/urunler/markalar")).status_code
    assert markalar == 200


async def test_urun_olusturma_etkin_sirketi_yazar(client, kullanici_ac, db, veri) -> None:
    kisi = await kullanici_ac("yonetici", "ADMIN")
    await giris(client, "yonetici")
    assert kisi is not None
    await _sec(client, "TELEKOM")
    r = await client.post("/api/urunler", json={"code": "TEL-YENI", "name": "Yeni Telsiz"})
    assert r.status_code == 201, r.text
    assert r.json()["sirket"] == "TELEKOM"
    # Açıkça null = ortak ürün
    r = await client.post(
        "/api/urunler", json={"code": "ORTAK-YENI", "name": "Ortak Ürün", "sirket": None}
    )
    assert r.status_code == 201 and r.json()["sirket"] is None
    # Başka şirkete damgalanamaz
    r = await client.post(
        "/api/urunler", json={"code": "X-1", "name": "Başkası", "sirket": "MOBILITE"}
    )
    assert r.status_code == 400
    # Geçersiz kod
    r = await client.post("/api/urunler", json={"code": "X-2", "name": "Yanlış", "sirket": "YOK"})
    assert r.status_code == 422
    # Patch: kendi ürününü ortak yapabilir; başka şirketin ürününe dokunamaz
    pid = (await client.get("/api/urunler", params={"q": "TEL-YENI"})).json()[0]["id"]
    r = await client.patch(f"/api/urunler/{pid}", json={"sirket": None})
    assert r.status_code == 200 and r.json()["sirket"] is None
    r = await client.patch(f"/api/urunler/{veri['urun']['MOB'].id}", json={"notes": "x"})
    assert r.status_code == 404


async def test_cihaz_listesi_ve_stok_ozeti_sirkete_suzulur(client, veri, depocu) -> None:
    await _sec(client, "TELEKOM")
    r = await client.get("/api/cihazlar")
    assert r.status_code == 200, r.text
    assert {c["kimlik"] for c in r.json()} == {"TEL-SN-1"}
    assert int(r.headers["X-Toplam-Kayit"]) == 1, "sayı = liste"

    ozet = (await client.get("/api/stok/ozet")).json()
    assert {s["kod"] for s in ozet} == {"TEL-TELSIZ", "ORTAK-KABLO"}

    depolar = {d["code"] for d in (await client.get("/api/stok/depolar")).json()}
    assert depolar == {"SB-ORTAK", "SB-TEL"}

    await _sec(client, "MOBILITE")
    r = await client.get("/api/cihazlar")
    assert {c["kimlik"] for c in r.json()} == {"862000000000101"}
    ozet = (await client.get("/api/stok/ozet")).json()
    assert {s["kod"] for s in ozet} == {"MOB-L300", "ORTAK-KABLO"}


async def test_baska_sirketin_cihazi_404(client, veri, depocu) -> None:
    await _sec(client, "ELEKTRONIK")
    mob = veri["cihaz"]["MOB"]
    assert (await client.get(f"/api/cihazlar/{mob.imei}")).status_code == 404
    assert (await client.get(f"/api/stok/cihaz/{mob.id}/konum-gecmisi")).status_code == 404
    r = await client.post(f"/api/cihazlar/{mob.id}/durum", json={"to_status": "TEST_EDILDI"})
    assert r.status_code == 404
    assert (await client.get("/api/cihazlar/ELK-SN-1")).status_code == 200
    # Arama da süzülür
    sonuc = (await client.get("/api/arama", params={"q": "862000000000101"})).json()
    assert all(s["tur"] != "CIHAZ" for s in sonuc)
    # Başka şirketin cihazı transferde "bulunamadı"; başka şirketin deposu 404
    govde = {
        "type": "IC_TRANSFER",
        "from_location_type": "MERKEZ_DEPO",
        "to_location_type": "BOLGE_DEPO",
        "kimlikler": [mob.imei],
    }
    r = await client.post("/api/stok/transferler", json=govde)
    assert r.status_code == 400, r.text
    assert "bulunamadı" in r.json()["detail"]
    r = await client.post(
        "/api/stok/transferler",
        json={**govde, "kimlikler": ["ELK-SN-1"], "to_warehouse_id": veri["depo"]["TEL"].id},
    )
    assert r.status_code == 404, r.text
    # Kendi cihazı + kendi deposu: transfer açılır
    r = await client.post(
        "/api/stok/transferler",
        json={**govde, "kimlikler": ["ELK-SN-1"], "to_warehouse_id": veri["depo"]["ELK"].id},
    )
    assert r.status_code == 201, r.text
    transfer_id = r.json()["id"]
    await _sec(client, "MOBILITE")
    listede = {t["id"] for t in (await client.get("/api/stok/transferler")).json()}
    assert transfer_id not in listede, "başka şirketin transferi görünmez"
    r = await client.post(f"/api/stok/transferler/{transfer_id}/teslim", json={})
    assert r.status_code == 404


async def test_hat_listesi_suzulur_yeni_hat_etkin_sirketi_alir(client, db, veri, depocu) -> None:
    await _sec(client, "TELEKOM")
    r = await client.get("/api/hatlar")
    assert r.status_code == 200, r.text
    assert {h["iccid"] for h in r.json()} == {"8990022222222222222"}
    assert r.json()[0]["sirket"] == "TELEKOM"

    r = await client.post("/api/hatlar", json={"iccid": "8990033333333333333"})
    assert r.status_code == 201, r.text
    assert r.json()["sirket"] == "TELEKOM"
    hat = await db.get(SimCard, r.json()["id"])
    await db.refresh(hat)
    assert hat.sirket == "TELEKOM"

    # Başka şirketin hattı 404 (okuma ve yazma)
    mob = veri["hat"]["MOB"]
    assert (await client.get(f"/api/hatlar/{mob.id}/paket-gecmisi")).status_code == 404
    r = await client.post(f"/api/hatlar/{mob.id}/durum", json={"to_status": "AKTIF"})
    assert r.status_code == 404
    # Başka şirketin cihazına hat takılamaz
    tel_hat = veri["hat"]["TEL"]
    r = await client.post(
        f"/api/hatlar/{tel_hat.id}/tak", json={"device_id": veri["cihaz"]["MOB"].id}
    )
    assert r.status_code == 404

    await _sec(client, "MOBILITE")
    iccidler = {h["iccid"] for h in (await client.get("/api/hatlar")).json()}
    assert iccidler == {"8990011111111111111"}


async def test_senkron_yalniz_mobilite(client, kullanici_ac, veri) -> None:
    await kullanici_ac("senkroncu", "ADMIN")
    await giris(client, "senkroncu")
    await _sec(client, "TELEKOM")
    r = await client.post("/api/hatlar/senkron")
    assert r.status_code == 403
    assert r.json()["detail"]["kod"] == "SIRKET_DISI"
    # Hat ekranı ise TELEKOM'da açık
    assert (await client.get("/api/hatlar")).status_code == 200

    await _sec(client, "MOBILITE")
    r = await client.post("/api/hatlar/senkron")
    assert r.status_code != 403, r.text


async def test_sirketsiz_kullanici_yalniz_ortak_gorur(client, kullanici_ac, veri) -> None:
    """Fail-closed: üyeliği olmayan kullanıcı ortak ürünü görür; şirket ürünü,
    cihazı ve hiçbir hat görmez."""
    await kullanici_ac("bos", "DEPO")
    await giris(client, "bos")
    assert await _urun_kodlari(client) == {"ORTAK-KABLO"}
    r = await client.get("/api/cihazlar")
    assert r.status_code == 200 and r.json() == []
    r = await client.get("/api/hatlar")
    assert r.status_code == 200 and r.json() == []
