"""Yönetim özeti (KPI), 30/60/90 takip, geçerlilik ve uyarılar (TS-153, TS-159).

Kilitlenen riskler:
- Sayı = liste: her KPI kutusunun değeri, tıklanınca açılan listenin
  `X-Toplam-Kayit` başlığına eşit (her KPI kodu için).
- Takip (K19): tamamlanmadan önceki gözlem takibi kapatmaz, sonraki kapatır,
  iptal edilen gözlem yeniden açar; 01.09 tamamlanan eğitimin 30. gün takibi
  01.10'da vadesi gelenler listesinde ve uyarıda; uç toplamı = uyarı adedi.
- Geçerlilik: 12 ay periyotlu eğitim 01.11.2026 tamamlanırsa 01.11.2027'de
  biter; bitişe ≤30 gün kala "dolacak" (FakeClock).
- Uyarı birim süzmesi: kendi biriminde 1 geciken planı olan şef 1 görür
  (başka birimde çok kayıt olsa da); birimsiz personelin planı KENDI_BIRIMI
  şefinde 0, TUMU yöneticide 1; ayrılan personel ve pasif kurs uyarı
  üretmez, girişsiz personel üretir; birimsiz şefte 0; `egitim.gor` yoksa yok.
"""

from datetime import date

import pytest
from egitim_veri import an, giris, kurs, personel, plan, puanlar
from sqlalchemy import select

from app.models import PersonnelCertificate, User
from app.services.teknik_servis import egitim_rapor
from app.services.teknik_servis import uyarilar as ts_uyarilar

pytestmark = pytest.mark.integration

LISTE_UCLARI = {
    "planlar": "/api/egitim/planlar",
    "gozlemler": "/api/egitim/gozlemler",
    "faaliyetler": "/api/egitim/duzeltici-faaliyetler",
    "takipler": "/api/egitim/takipler",
    "belgeler": "/api/egitim/belgeler",
    "matris": "/api/egitim/yetkinlik-matrisi",
}


async def _uyarilar(db, username: str, clock) -> dict[str, int]:
    user = await db.scalar(select(User).where(User.username == username))
    return {
        u.kod: u.adet
        for u in await ts_uyarilar.topla(db, user, clock)
        if u.kod.startswith("egitim.")
    }


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac):
    await birimli_kullanici_ac("guv_sef", "SERVIS_SEF", ["GUVENLIK"])
    await kullanici_ac("ik", "IK")
    g1 = await personel(db, "Guv Bir", "GUVENLIK")
    g2 = await personel(db, "Guv Iki", "GUVENLIK")
    h1 = await personel(db, "Hab Bir", "HABERLESME")
    k, maddeler = await kurs(db, "ISG-01", yenileme_ay=12)
    return {"g1": g1, "g2": g2, "h1": h1, "kurs": k, "m": maddeler}


async def test_kpi_kutusu_sayisi_liste_toplamina_esit(client, db, ortam) -> None:
    from app.models import Competency, CompetencyAssessment

    k, g1, g2, h1 = ortam["kurs"], ortam["g1"], ortam["g2"], ortam["h1"]
    await plan(db, g1, k, 2026, hedef=date(2026, 3, 1))  # geciken
    await plan(db, g2, k, 2026, tamamlandi=date(2025, 11, 1))  # belge dolacak/ doldu
    await plan(db, h1, k, 2026, hedef=date(2026, 3, 1))  # kapsam dışı (şefe)
    yetkinlik = Competency(kod="XR", ad="X-Ray", is_critical=True, onerilen_hedef=3)
    db.add(yetkinlik)
    await db.flush()
    db.add(
        CompetencyAssessment(
            user_id=g1.id,
            competency_id=yetkinlik.id,
            mevcut_seviye=2,
            hedef_seviye=3,
            degerlendirme_tarihi=date(2026, 1, 5),
            kaynak="GOC",
        )
    )
    await db.commit()
    client.clock.set(an(2026, 10, 15))
    await giris(client, "guv_sef")
    r = await client.post(
        "/api/egitim/gozlemler",
        json={
            "user_id": g1.id,
            "course_id": k.id,
            "asama": 0,
            "gozlem_tarihi": "2026-10-10",
            "puanlar": puanlar(ortam["m"], 0, 2, 2, 2),
        },
    )
    assert r.status_code == 201, r.text
    for username in ("guv_sef", "ik"):
        await giris(client, username)
        ozet = (await client.get("/api/egitim/ozet?yil=2026")).json()
        kodlar = {k["kod"] for k in ozet["kutular"]}
        assert kodlar == set(egitim_rapor.KPI_TANIMLARI), kodlar
        for kutu in ozet["kutular"]:
            tanim = egitim_rapor.KPI_TANIMLARI[kutu["kod"]]
            r = await client.get(f"{LISTE_UCLARI[tanim.liste]}?kpi={kutu['kod']}&yil=2026")
            assert r.status_code == 200, (kutu, r.text)
            assert int(r.headers["X-Toplam-Kayit"]) == kutu["deger"], (username, kutu)
            assert kutu["yol"].startswith(f"/egitim?sekme={tanim.sekme}&kpi={kutu['kod']}")
    await giris(client, "guv_sef")
    ozet = {
        k["kod"]: k["deger"]
        for k in (await client.get("/api/egitim/ozet?yil=2026")).json()["kutular"]
    }
    assert ozet["plan_geciken"] == 1  # Hab Bir sayılmaz
    assert ozet["gozlem_kritik"] == 1 and ozet["faaliyet_acik"] == 1
    assert ozet["yetkinlik_kritik_alti"] == 1


async def test_veri_yoksa_belge_ve_yetkinlik_kutusu_cizilmez(client, db, ortam) -> None:
    from app.models import TrainingCourse

    kurs_kaydi = await db.get(TrainingCourse, ortam["kurs"].id)
    kurs_kaydi.yenileme_ay = None
    await db.commit()
    await giris(client, "ik")
    kodlar = {k["kod"] for k in (await client.get("/api/egitim/ozet?yil=2026")).json()["kutular"]}
    assert not {"belge_doldu", "belge_dolacak", "yetkinlik_hedef_alti"} & kodlar
    assert "plan_acik" in kodlar


async def test_takip_kurallari_ve_uyari_ile_uc_esit(client, db, ortam) -> None:
    g1, k = ortam["g1"], ortam["kurs"]
    p = await plan(db, g1, k, 2026, tamamlandi=date(2026, 9, 1))
    client.clock.set(an(2026, 10, 1))
    await giris(client, "guv_sef")
    r = await client.get("/api/egitim/takipler?vadesi_gelen=1")
    assert [(t["plan_id"], t["asama"], t["durum"]) for t in r.json()] == [
        (p.id, 30, "ZAMANI_GELDI")
    ]
    assert (await _uyarilar(db, "guv_sef", client.clock))["egitim.takip"] == int(
        r.headers["X-Toplam-Kayit"]
    )
    # Tamamlanmadan ÖNCE tarihli 30. gün gözlemi takibi kapatmaz (uyarılı kaydedilir).
    govde = {
        "user_id": g1.id,
        "course_id": k.id,
        "asama": 30,
        "plan_id": p.id,
        "puanlar": puanlar(ortam["m"], 2, 2, 2, 2),
    }
    r = await client.post("/api/egitim/gozlemler", json={**govde, "gozlem_tarihi": "2026-08-20"})
    assert r.status_code == 201 and r.json()["uyarilar"]
    assert len((await client.get("/api/egitim/takipler?vadesi_gelen=1")).json()) == 1
    r = await client.post("/api/egitim/gozlemler", json={**govde, "gozlem_tarihi": "2026-09-30"})
    sonraki = r.json()["gozlem"]["id"]
    assert (await client.get("/api/egitim/takipler?vadesi_gelen=1")).json() == []
    await client.post(
        f"/api/egitim/kisiler/{g1.id}/gozlemler/{sonraki}/iptal", json={"gerekce": "hatalı"}
    )
    assert len((await client.get("/api/egitim/takipler?vadesi_gelen=1")).json()) == 1
    # Başka birimin personeli görünmez.
    await plan(db, ortam["h1"], k, 2026, tamamlandi=date(2026, 9, 1))
    assert len((await client.get("/api/egitim/takipler?vadesi_gelen=1")).json()) == 1


async def test_gecerlilik_on_iki_ay_ve_uyari_penceresi(client, db, ortam) -> None:
    await plan(db, ortam["g1"], ortam["kurs"], 2026, tamamlandi=date(2026, 11, 1))
    client.clock.set(an(2027, 10, 1))
    await giris(client, "guv_sef")
    satirlar = (await client.get("/api/egitim/belgeler")).json()
    assert [(s["kaynak"], s["bitis"], s["durum"]) for s in satirlar] == [
        ("PLAN", "2027-11-01", "GECERLI")
    ]
    client.clock.set(an(2027, 10, 5))
    await giris(client, "guv_sef")
    r = await client.get("/api/egitim/belgeler?durum=DOLACAK")
    assert int(r.headers["X-Toplam-Kayit"]) == 1
    assert (await _uyarilar(db, "guv_sef", client.clock))["egitim.belge_bitiyor"] == 1
    # Elle girilen belge kişi kartında; belge no yalnız egitim.detay ile.
    db.add(
        PersonnelCertificate(
            user_id=ortam["g1"].id,
            belge_adi="Forklift",
            verilis_tarihi=date(2026, 1, 1),
            gecerlilik_bitis=date(2027, 9, 1),
            belge_no="F-123",
        )
    )
    await db.commit()
    kart = (await client.get(f"/api/egitim/kisiler/{ortam['g1'].id}/kart")).json()
    assert {b["belge_adi"] for b in kart["belgeler"]} == {"Forklift"}
    assert kart["belgeler"][0]["belge_no"] == "F-123"
    assert (await _uyarilar(db, "guv_sef", client.clock))["egitim.belge_doldu"] == 1


async def test_uyari_birim_suzmesi(client, db, ortam, kullanici_ac, birimli_kullanici_ac) -> None:
    k = ortam["kurs"]
    await plan(db, ortam["g1"], k, 2026, hedef=date(2026, 3, 1))
    for i in range(5):
        h = await personel(db, f"Hab Ek {i}", "HABERLESME")
        await plan(db, h, k, 2026, hedef=date(2026, 3, 1))
    birimsiz = await personel(db, "Birimsiz Kisi")
    await plan(db, birimsiz, k, 2026, hedef=date(2026, 3, 1))
    ayrilan = await personel(db, "Ayrilan Kisi", "GUVENLIK", ayrildi=True)
    await plan(db, ayrilan, k, 2026, hedef=date(2026, 3, 1))
    pasif, _ = await kurs(db, "PASIF-01", aktif=False)
    await plan(db, ortam["g2"], pasif, 2026, hedef=date(2026, 3, 1))
    await plan(db, ortam["g2"], k, 2026, hedef=date(2026, 3, 1), durum="IPTAL")
    await birimli_kullanici_ac("birimsiz_sef", "SERVIS_SEF", [])
    await kullanici_ac("teknisyen", "SERVIS_TEKNISYEN")
    clock = client.clock
    clock.set(an(2026, 6, 1))
    sef = await _uyarilar(db, "guv_sef", clock)
    assert sef["egitim.plan_vadesi"] == 1
    assert (await _uyarilar(db, "ik", clock))["egitim.plan_vadesi"] == 7  # 1 + 5 + birimsiz
    assert sum((await _uyarilar(db, "birimsiz_sef", clock)).values()) == 0
    assert await _uyarilar(db, "teknisyen", clock) == {}
    # Listede de aynı sayı.
    await giris(client, "guv_sef")
    r = await client.get("/api/egitim/planlar?vade=1")
    assert int(r.headers["X-Toplam-Kayit"]) == 1
