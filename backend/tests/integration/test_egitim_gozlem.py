"""Saha gözlemi, kritik İSG düzeltici faaliyeti ve servis işi bağı (TS-151/152/155/156).

Kilitlenen riskler:
- Sonuç ve puan SUNUCUDA hesaplanır; istemcinin gönderdiği `sonuc` yok sayılır.
- Gözlemci oturumdaki kullanıcıdır; öz-gözlem 409; ileri tarih 400.
- Kapsam dışı servis işine bağlı gözlem 404 ve KAYIT OLUŞMAZ; birim işten.
- Kritik maddede 0 → gözlem başına TEK faaliyet (sorumlu = gözlemci, termin
  +14 gün); sonraki tarihli ve kritik maddeleri 2 olan gözlem otomatik kapatır;
  manuel kapanış kanıtsız 400, `egitim.gozlem` ile 403.
- İptal: gerekçe zorunlu; başkasının gözlemini şef iptal edemez; bağlı faaliyet
  açık kalır.
- Detay alanları (`notlar`, `aksiyon_plani`, `maddeler`) yalnız `egitim.detay`
  sahibinin JSON'unda ANAHTAR olarak var (YONETIM'de yok).
"""

from datetime import date

import pytest
from egitim_veri import an, giris, kurs, personel, puanlar
from sqlalchemy import func, select

from app.models import TrainingCorrectiveAction, TrainingObservation

pytestmark = pytest.mark.integration

DETAY = {"notlar", "aksiyon_plani", "maddeler", "personel_yorumu", "sonraki_izleme"}


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac):
    sef = await birimli_kullanici_ac("guv_sef", "SERVIS_SEF", ["GUVENLIK"])
    sef2 = await birimli_kullanici_ac("guv_sef2", "SERVIS_SEF", ["GUVENLIK"])
    await kullanici_ac("ik", "IK")
    await kullanici_ac("yonetim", "YONETIM")
    g1 = await personel(db, "Guv Bir", "GUVENLIK")
    h1 = await personel(db, "Hab Bir", "HABERLESME")
    k, maddeler = await kurs(db, "ISG-01")
    so_guv = await servis_isi_ac(birim="GUVENLIK", atananlar=[g1])
    so_hab = await servis_isi_ac(birim="HABERLESME")
    client.clock.set(an(2026, 6, 15))
    await giris(client, "guv_sef")
    return {
        "sef": sef,
        "sef2": sef2,
        "g1": g1,
        "h1": h1,
        "kurs": k,
        "m": maddeler,
        "so_guv": so_guv,
        "so_hab": so_hab,
    }


def _govde(o, *degerler, **kw) -> dict:
    return {
        "user_id": o["g1"].id,
        "course_id": o["kurs"].id,
        "asama": 0,
        "gozlem_tarihi": "2026-06-10",
        "puanlar": puanlar(o["m"], *degerler),
        **kw,
    }


async def test_sonuc_sunucuda_istemci_sonucu_yok_sayilir(client, ortam) -> None:
    r = await client.post(
        "/api/egitim/gozlemler",
        json={**_govde(ortam, 2, 2, 1, -1), "sonuc": "BASARILI", "puan": 100},
    )
    assert r.status_code == 201, r.text
    g = r.json()["gozlem"]
    assert float(g["puan"]) == 83.33 and g["sonuc"] == "GELISIM_GEREKLI"
    assert g["observer_user_id"] == ortam["sef"].id and g["gozlemci_ad"] == "Guv_Sef"
    assert g["birim"] == "GUVENLIK"


async def test_oz_gozlem_409_ileri_tarih_400(client, db, ortam) -> None:
    r = await client.post(
        "/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, user_id=ortam["sef"].id)
    )
    assert r.status_code == 409
    r = await client.post(
        "/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, gozlem_tarihi="2026-06-16")
    )
    assert r.status_code == 400
    # Kritik madde -1 gerekçesiz → 400.
    govde = _govde(ortam, 2, 2, 2, 2)
    govde["puanlar"][0] = {"criterion_id": ortam["m"][0].id, "puan": -1}
    assert (await client.post("/api/egitim/gozlemler", json=govde)).status_code == 400
    assert await db.scalar(select(func.count()).select_from(TrainingObservation)) == 0


async def test_kapsam_disi_kisi_ve_servis_isi_404_kayit_olusmaz(client, db, ortam) -> None:
    r = await client.post(
        "/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, user_id=ortam["h1"].id)
    )
    assert r.status_code == 404
    r = await client.post(
        "/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, service_order_id=ortam["so_hab"].id)
    )
    assert r.status_code == 404
    assert await db.scalar(select(func.count()).select_from(TrainingObservation)) == 0


async def test_servis_isinden_gozlem_birim_isten_atama_uyarisi(
    client, db, ortam, servis_isi_ac
) -> None:
    r = await client.post(
        "/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, service_order_id=ortam["so_guv"].id)
    )
    assert r.status_code == 201, r.text
    assert r.json()["uyarilar"] == []
    # Servis detayında listelenir.
    liste = (
        await client.get(f"/api/egitim/gozlemler?service_order_id={ortam['so_guv'].id}")
    ).json()
    assert [g["id"] for g in liste] == [r.json()["gozlem"]["id"]]
    # Atamasız kişi: kayıt yapılır, yanıt uyarılı.
    so_atamasiz = await servis_isi_ac(birim="GUVENLIK")
    r = await client.post(
        "/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, service_order_id=so_atamasiz.id)
    )
    assert r.status_code == 201
    assert any("tayini yok" in u for u in r.json()["uyarilar"])


async def test_kritik_faaliyet_acilir_ve_sonraki_gozlemle_kapanir(client, db, ortam) -> None:
    r = await client.post("/api/egitim/gozlemler", json=_govde(ortam, 0, 2, 2, 2))
    assert r.json()["gozlem"]["sonuc"] == "KRITIK"
    f = await db.get(TrainingCorrectiveAction, r.json()["faaliyet_id"])
    assert f.sorumlu_user_id == ortam["sef"].id
    assert f.termin == date(2026, 6, 24) and f.status == "ACIK"
    # Aynı tarihli gözlem kapatmaz; sonraki tarihli ve kritik maddesi 2 olan kapatır.
    await client.post("/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, asama=30))
    await db.refresh(f)
    assert f.status == "ACIK"
    r = await client.post(
        "/api/egitim/gozlemler",
        json=_govde(ortam, 2, 1, 1, 1, asama=30, gozlem_tarihi="2026-06-12"),
    )
    assert any("kapandı" in u for u in r.json()["uyarilar"])
    await db.refresh(f)
    assert (f.status, f.kapanis_turu, f.closing_observation_id) == (
        "KAPATILDI",
        "OTOMATIK_GOZLEM",
        r.json()["gozlem"]["id"],
    )


async def test_manuel_kapanis_kanit_ve_yetki(client, db, ortam) -> None:
    r = await client.post("/api/egitim/gozlemler", json=_govde(ortam, 0, 2, 2, 2))
    fid = r.json()["faaliyet_id"]
    yol = f"/api/egitim/kisiler/{ortam['g1'].id}/duzeltici-faaliyetler/{fid}/kapat"
    assert (await client.post(yol, json={"kanit": "Eğitim tekrarlandı"})).status_code == 403
    await giris(client, "ik")
    assert (await client.post(yol, json={"kanit": "  "})).status_code == 400
    r = await client.post(yol, json={"kanit": "Eğitim tekrarlandı"})
    assert r.status_code == 200 and r.json()["status"] == "KAPATILDI"
    assert r.json()["kapanis_kaniti"] == "Eğitim tekrarlandı"
    assert (await client.post(yol, json={"kanit": "tekrar"})).status_code == 409


async def test_gozlem_iptali_kurallari_ve_faaliyet_acik_kalir(client, db, ortam) -> None:
    r = await client.post("/api/egitim/gozlemler", json=_govde(ortam, 0, 2, 2, 2))
    gid, fid = r.json()["gozlem"]["id"], r.json()["faaliyet_id"]
    yol = f"/api/egitim/kisiler/{ortam['g1'].id}/gozlemler/{gid}/iptal"
    await giris(client, "guv_sef2")  # gözlemci değil, egitim.yaz yok
    assert (await client.post(yol, json={"gerekce": "hata"})).status_code == 403
    await giris(client, "guv_sef")
    assert (await client.post(yol, json={"gerekce": ""})).status_code == 400
    r = await client.post(yol, json={"gerekce": "Yanlış kişi"})
    assert r.status_code == 200 and r.json()["cancel_reason"] == "Yanlış kişi"
    f = await db.get(TrainingCorrectiveAction, fid)
    assert f.status == "ACIK"
    # İptal edilen gözlem listeden ve KPI'dan düşer.
    assert (await client.get("/api/egitim/gozlemler?yil=2026")).json() == []
    ozet = (await client.get("/api/egitim/ozet?yil=2026")).json()
    assert ozet["gozlem"]["toplam"] == 0
    kutu = {k["kod"]: k["deger"] for k in ozet["kutular"]}
    assert kutu["gozlem_kritik"] == 0 and kutu["faaliyet_acik"] == 1


async def test_detay_alanlari_yalniz_egitim_detay(client, ortam) -> None:
    r = await client.post(
        "/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2, notlar="Not", aksiyon_plani="Plan")
    )
    gid = r.json()["gozlem"]["id"]
    tek = f"/api/egitim/kisiler/{ortam['g1'].id}/gozlemler/{gid}"
    g = (await client.get(tek)).json()
    assert DETAY <= set(g) and g["notlar"] == "Not" and len(g["maddeler"]) == 4
    await giris(client, "yonetim")
    for g in [
        (await client.get(tek)).json(),
        *(await client.get("/api/egitim/gozlemler?yil=2026")).json(),
    ]:
        assert not DETAY & set(g), g
        assert g["sonuc"] == "BASARILI"
    kart = (await client.get(f"/api/egitim/kisiler/{ortam['g1'].id}/kart")).json()
    assert not DETAY & set(kart["gozlemler"][0])


async def test_kapsam_disi_kisinin_gozlemi_404(client, db, ortam, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("hab_sef", "SERVIS_SEF", ["HABERLESME"])
    r = await client.post("/api/egitim/gozlemler", json=_govde(ortam, 2, 2, 2, 2))
    gid = r.json()["gozlem"]["id"]
    await giris(client, "hab_sef")
    assert (
        await client.get(f"/api/egitim/kisiler/{ortam['g1'].id}/gozlemler/{gid}")
    ).status_code == 404
    r = await client.post(
        f"/api/egitim/kisiler/{ortam['g1'].id}/gozlemler/{gid}/iptal", json={"gerekce": "x"}
    )
    assert r.status_code == 404
    g = await db.get(TrainingObservation, gid)
    assert g.cancelled_at is None
