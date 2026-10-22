"""Gelişim Kartım, toplu katılım, yetkinlik kataloğu ve kişisel ekler (TS-154/157/158/160).

Kilitlenen riskler:
- Gelişim Kartım yalnız oturumdaki kişinin verisi; başkasının kartı 403;
  "Gördüm" başkasının gözleminde 404, ikinci kez 409 (geri alınamaz) ve onay
  tarihi şefin listesinde görünür; kaydı olmayan kişiye boş kart.
- Toplu katılım: 15 satır tek istekte; 7. satırda puan 120 → 422 (`loc`
  satır indeksi); kapsam dışı kişi → 400 `{satir}`; ilk hatada 0 satır.
- Yetkinlik: yeni yetkinlik matriste seçilir, pasif seçilmez; başka birimin
  yetkinliği 403; değerlendirme yalnız ekleme (2→3: geçmişte 2 satır,
  matriste 3); kritik yetkinlikte kanıtsız 400; öz-değerlendirme 409.
- Kişisel ek: gözlem eki `egitim.detay` olmadan (YONETIM) 403; teknisyen kendi
  gözleminin ekini görür, başkasınınkini 404.
"""

from datetime import date

import pytest
from egitim_veri import an, giris, kurs, personel, plan, puanlar
from sqlalchemy import func, select

from app.models import CompetencyAssessment, TrainingAttendance, TrainingPlan

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac):
    sef = await birimli_kullanici_ac("guv_sef", "SERVIS_SEF", ["GUVENLIK"])
    tek = await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    tek2 = await birimli_kullanici_ac("tek2", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    await kullanici_ac("ik", "IK")
    await kullanici_ac("yonetim", "YONETIM")
    h1 = await personel(db, "Hab Bir", "HABERLESME")
    k, maddeler = await kurs(db, "ISG-01")
    client.clock.set(an(2026, 6, 15))
    return {"sef": sef, "tek": tek, "tek2": tek2, "h1": h1, "kurs": k, "m": maddeler}


async def _gozlem(client, o, kisi) -> int:
    await giris(client, "guv_sef")
    r = await client.post(
        "/api/egitim/gozlemler",
        json={
            "user_id": kisi.id,
            "course_id": o["kurs"].id,
            "asama": 0,
            "gozlem_tarihi": "2026-06-10",
            "puanlar": puanlar(o["m"], 2, 2, 1, 2),
            "notlar": "Kask takılı",
            "aksiyon_plani": "Tekrar",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["gozlem"]["id"]


# --- Gelişim Kartım (TS-157) ------------------------------------------------------------


async def test_gelisim_kartim_yalniz_kendi_verisi(client, db, ortam) -> None:
    await plan(db, ortam["tek"], ortam["kurs"], 2026)
    await plan(db, ortam["tek2"], ortam["kurs"], 2026)
    gid = await _gozlem(client, ortam, ortam["tek"])
    await giris(client, "tek")
    kart = (await client.get("/api/egitim/kendim")).json()
    assert kart["kisi"]["id"] == ortam["tek"].id and kart["bos"] is False
    assert {p["user_id"] for p in kart["planlar"]} == {ortam["tek"].id}
    # K12: kişi kendi gözleminin notunu ve madde puanlarını görür.
    assert kart["gozlemler"][0]["notlar"] == "Kask takılı" and kart["gozlemler"][0]["maddeler"]
    assert (await client.get(f"/api/egitim/kisiler/{ortam['tek2'].id}/kart")).status_code == 403
    assert (await client.get("/api/egitim/planlar")).status_code == 403
    # Gördüm: kendi 200, ikinci 409; başkasınınki 404.
    r = await client.post("/api/egitim/kendim/gordum", json={"gozlem_id": gid, "yorum": "Okudum"})
    assert r.status_code == 200 and r.json()["gordu_at"]
    assert (
        await client.post("/api/egitim/kendim/gordum", json={"gozlem_id": gid})
    ).status_code == 409
    await giris(client, "tek2")
    assert (
        await client.post("/api/egitim/kendim/gordum", json={"gozlem_id": gid})
    ).status_code == 404
    bos = (await client.get("/api/egitim/kendim")).json()
    assert bos["gozlemler"] == [] and bos["kisi"]["id"] == ortam["tek2"].id
    # Onay tarihi şefin listesinde.
    await giris(client, "guv_sef")
    liste = (await client.get("/api/egitim/gozlemler?yil=2026")).json()
    assert liste[0]["gordu_at"] is not None


async def test_kaydi_olmayan_kisiye_bos_kart(client, ortam) -> None:
    await giris(client, "tek")
    kart = (await client.get("/api/egitim/kendim")).json()
    assert kart["bos"] is True


async def test_kisisel_ek_kendi_gorur_baskasi_404_ozet_403(client, db, ortam) -> None:
    gid = await _gozlem(client, ortam, ortam["tek"])
    r = await client.post(
        f"/api/ekler/training_observations/{gid}?kind=GOZLEM_FOTOGRAFI",
        files={"file": ("foto.png", PNG, "image/png")},
    )
    assert r.status_code == 201, r.text
    await giris(client, "tek")
    assert (await client.get(f"/api/ekler/training_observations/{gid}")).status_code == 200
    await giris(client, "tek2")
    assert (await client.get(f"/api/ekler/training_observations/{gid}")).status_code == 404
    await giris(client, "yonetim")
    assert (await client.get(f"/api/ekler/training_observations/{gid}")).status_code == 403


# --- Toplu katılım (TS-158) ---------------------------------------------------------------


async def _personeller(db, n: int, birim: str = "GUVENLIK"):
    return [await personel(db, f"Kisi {birim} {i:02d}", birim) for i in range(n)]


async def test_toplu_katilim_on_bes_satir_ve_plan_sahipleri(client, db, ortam) -> None:
    kisiler = await _personeller(db, 15)
    for k in kisiler[:5]:
        await plan(db, k, ortam["kurs"], 2026)
    await giris(client, "ik")
    o = (
        await client.post(
            "/api/egitim/oturumlar",
            json={"course_id": ortam["kurs"].id, "oturum_tarihi": "2026-06-10"},
        )
    ).json()
    adaylar = (await client.get(f"/api/egitim/oturumlar/katilimcilar?oturum_id={o['id']}")).json()
    assert {a["user_id"] for a in adaylar} == {k.id for k in kisiler[:5]}
    r = await client.put(
        "/api/egitim/oturumlar/katilim/toplu",
        json={
            "oturum_id": o["id"],
            "satirlar": [{"user_id": k.id, "son_puan": 80} for k in kisiler],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["yazilan"] == 15
    tamam = await db.scalar(
        select(func.count()).select_from(TrainingPlan).where(TrainingPlan.status == "TAMAMLANDI")
    )
    assert tamam == 5


async def test_toplu_katilim_hata_satiri_ve_sifir_yazim(client, db, ortam) -> None:
    kisiler = await _personeller(db, 10)
    await giris(client, "ik")
    o = (
        await client.post(
            "/api/egitim/oturumlar",
            json={"course_id": ortam["kurs"].id, "oturum_tarihi": "2026-06-10"},
        )
    ).json()
    satirlar = [{"user_id": k.id, "son_puan": 80} for k in kisiler]
    satirlar[6]["son_puan"] = 120
    r = await client.put(
        "/api/egitim/oturumlar/katilim/toplu", json={"oturum_id": o["id"], "satirlar": satirlar}
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][:3] == ["body", "satirlar", 6]
    assert await db.scalar(select(func.count()).select_from(TrainingAttendance)) == 0


async def test_toplu_katilim_kapsam_disi_kisi_400_satir(
    client, db, ortam, rol_ac, birimli_kullanici_ac
) -> None:
    await rol_ac("T_EGITIM_BIRIM", ["egitim.gor", "egitim.yaz"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("birim_yazar", "T_EGITIM_BIRIM", ["GUVENLIK"])
    kisiler = await _personeller(db, 4)
    await giris(client, "birim_yazar")
    o = (
        await client.post(
            "/api/egitim/oturumlar",
            json={"course_id": ortam["kurs"].id, "oturum_tarihi": "2026-06-10"},
        )
    ).json()
    satirlar = [{"user_id": k.id} for k in kisiler]
    satirlar.insert(2, {"user_id": ortam["h1"].id})
    r = await client.put(
        "/api/egitim/oturumlar/katilim/toplu", json={"oturum_id": o["id"], "satirlar": satirlar}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["satir"] == 3
    assert await db.scalar(select(func.count()).select_from(TrainingAttendance)) == 0


async def test_baska_birim_kursuna_oturum_403(
    client, db, ortam, rol_ac, birimli_kullanici_ac
) -> None:
    await rol_ac("T_EGITIM_HAB", ["egitim.gor", "egitim.yaz"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("hab_yazar", "T_EGITIM_HAB", ["HABERLESME"])
    guv_kurs, _ = await kurs(db, "GUV-01", birim="GUVENLIK")
    await giris(client, "hab_yazar")
    r = await client.post(
        "/api/egitim/oturumlar", json={"course_id": guv_kurs.id, "oturum_tarihi": "2026-06-10"}
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/egitim/oturumlar", json={"course_id": ortam["kurs"].id, "oturum_tarihi": "2026-06-10"}
    )
    assert r.status_code == 201  # birimsiz kurs serbest


# --- Yetkinlik (TS-150 / TS-160) ------------------------------------------------------------


async def test_yetkinlik_katalogu_ve_degerlendirme_gecmisi(
    client, db, ortam, rol_ac, birimli_kullanici_ac
) -> None:
    kisi = await personel(db, "Guv Bir", "GUVENLIK")
    await giris(client, "ik")
    r = await client.post(
        "/api/egitim/yetkinlikler", json={"kod": "XR", "ad": "X-Ray", "is_critical": True}
    )
    assert r.status_code == 201
    xr = r.json()
    r = await client.post(
        "/api/egitim/yetkinlikler", json={"kod": "KAM", "ad": "Kamera", "birim": "GUVENLIK"}
    )
    kam = r.json()
    await giris(client, "guv_sef")
    yol = "/api/egitim/yetkinlik-degerlendirmeleri"
    govde = {"user_id": kisi.id, "competency_id": xr["id"], "mevcut_seviye": 2}
    assert (await client.post(yol, json=govde)).status_code == 400  # kritik: kanıt zorunlu
    assert (
        await client.post(yol, json={**govde, "user_id": ortam["sef"].id, "kanit": "x"})
    ).status_code == 409
    r = await client.post(yol, json={**govde, "kanit": "Saha gözlemi"})
    assert r.status_code == 201 and r.json()["assessed_by_user_id"] == ortam["sef"].id
    await client.post(yol, json={**govde, "mevcut_seviye": 3, "kanit": "Tekrar"})
    gecmis = (await client.get(f"/api/egitim/kisiler/{kisi.id}/yetkinlik-gecmisi")).json()
    assert [g["mevcut_seviye"] for g in gecmis] == [3, 2]
    matris = (await client.get(f"/api/egitim/yetkinlik-matrisi?kisi_id={kisi.id}")).json()
    assert [(m["kod"], m["mevcut_seviye"]) for m in matris] == [("XR", 3)]
    assert await db.scalar(select(func.count()).select_from(CompetencyAssessment)) == 2
    # Pasif yetkinlik seçilmez (400) ve aktif listede yok.
    await giris(client, "ik")
    await client.patch(
        "/api/egitim/yetkinlikler",
        json={"id": kam["id"], "version": kam["version"], "is_active": False},
    )
    aktifler = {y["kod"] for y in (await client.get("/api/egitim/yetkinlikler?aktif=true")).json()}
    assert aktifler == {"XR"}
    await giris(client, "guv_sef")
    r = await client.post(
        yol, json={"user_id": kisi.id, "competency_id": kam["id"], "mevcut_seviye": 2}
    )
    assert r.status_code == 400
    # Başka birimin yetkinliği 403 (istisnalı birim yazıcısı).
    await rol_ac("T_EGITIM_HAB", ["egitim.gor", "egitim.yaz"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("hab_yazar", "T_EGITIM_HAB", ["HABERLESME"])
    await giris(client, "hab_yazar")
    r = await client.patch(
        "/api/egitim/yetkinlikler", json={"id": kam["id"], "version": kam["version"] + 1, "ad": "X"}
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/egitim/yetkinlikler", json={"kod": "GV2", "ad": "Güv", "birim": "GUVENLIK"}
    )
    assert r.status_code == 403


async def test_yetkinlik_detay_kaniti_yalniz_detay_izniyle(client, db, ortam) -> None:
    from app.models import Competency

    kisi = await personel(db, "Guv Bir", "GUVENLIK")
    y = Competency(kod="XR", ad="X-Ray", onerilen_hedef=3)
    db.add(y)
    await db.commit()
    await giris(client, "guv_sef")
    await client.post(
        "/api/egitim/yetkinlik-degerlendirmeleri",
        json={"user_id": kisi.id, "competency_id": y.id, "mevcut_seviye": 2, "kanit": "Kanıt"},
    )
    assert (await client.get(f"/api/egitim/kisiler/{kisi.id}/yetkinlik-gecmisi")).json()[0][
        "kanit"
    ] == "Kanıt"
    await giris(client, "yonetim")
    assert (
        "kanit"
        not in (await client.get(f"/api/egitim/kisiler/{kisi.id}/yetkinlik-gecmisi")).json()[0]
    )
    assert date(2026, 6, 15)
