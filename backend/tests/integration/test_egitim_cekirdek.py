"""Eğitim çekirdeği: katalog, toplu plan, oturum/katılım, plan kuralları (TS-150…152).

Kilitlenen riskler:
- Toplu plan mükerrer üretmez (kişi+kurs+yıl), iptal edilen yıl yeniden
  planlanabilir, üst sınır ayardan (301 → 400), pasif kurs 400.
- Plan tamamlama kuralı (E08-04): en eski açık plan; sonraki yılın planı
  önceki yıl oturumuyla kapanmaz; "katılmadı" düzeltmesi planı geri açar;
  ileri tarihli oturum 400; oturum tarihi düzeltmesi tamamlanma tarihini
  taşır; katılımlı oturum silinemez.
- Kapsam: başka birimin kişisinin planı 404 ve veri değişmez; plan.xlsx
  kapsam dışı satır içermez, `servis_rapor.disaaktar` yoksa 403, denetime yazılır.
"""

from datetime import date

import pytest
from egitim_veri import an, giris, kurs, personel, plan
from sqlalchemy import func, select

from app.models import AuditLog, TrainingAttendance, TrainingPlan, TrainingSession

pytestmark = pytest.mark.integration


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac):
    ik = await kullanici_ac("ik", "IK")
    sef = await birimli_kullanici_ac("guv_sef", "SERVIS_SEF", ["GUVENLIK"])
    yonetim = await kullanici_ac("yonetim", "YONETIM")
    tek = await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    g1 = await personel(db, "Guv Bir", "GUVENLIK")
    g2 = await personel(db, "Guv Iki", "GUVENLIK")
    g3 = await personel(db, "Guv Uc", "GUVENLIK")
    h1 = await personel(db, "Hab Bir", "HABERLESME")
    k, maddeler = await kurs(db, "ISG-01")
    client.clock.set(an(2026, 6, 15))
    return {
        "ik": ik,
        "sef": sef,
        "yonetim": yonetim,
        "tek": tek,
        "g": [g1, g2, g3],
        "h1": h1,
        "kurs": k,
        "maddeler": maddeler,
    }


# --- RBAC ---------------------------------------------------------------------------


async def test_katalog_yazma_yalniz_egitim_yaz(client, ortam) -> None:
    govde = {"kod": "TEK-01", "baslik": "Teknik", "kategori": "TEKNIK", "sure_saat": 2}
    await giris(client, "guv_sef")
    assert (await client.post("/api/egitim/kurslar", json=govde)).status_code == 403
    assert (await client.get("/api/egitim/kurslar")).status_code == 200
    await giris(client, "tek")
    assert (await client.get("/api/egitim/kurslar")).status_code == 403
    await giris(client, "ik")
    r = await client.post("/api/egitim/kurslar", json=govde)
    assert r.status_code == 201, r.text
    assert (await client.post("/api/egitim/kurslar", json=govde)).status_code == 409
    kurs_id, surum = r.json()["id"], r.json()["version"]
    r = await client.patch(
        "/api/egitim/kurslar", json={"id": kurs_id, "version": surum, "is_active": False}
    )
    assert r.status_code == 200 and r.json()["is_active"] is False
    # Eski sürümle düzenleme 409 (iyimser kilit).
    r = await client.patch(
        "/api/egitim/kurslar", json={"id": kurs_id, "version": surum, "baslik": "X"}
    )
    assert r.status_code == 409
    aktifler = (await client.get("/api/egitim/kurslar?aktif=true")).json()
    assert kurs_id not in {k["id"] for k in aktifler}


async def test_kriter_silinmez_pasiflenir(client, ortam) -> None:
    await giris(client, "ik")
    r = await client.post(
        "/api/egitim/kriterler",
        json={"kurs_id": ortam["kurs"].id, "metin": "Yeni madde", "is_critical": False},
    )
    assert r.status_code == 201 and r.json()["sira"] == 5
    r = await client.patch(
        "/api/egitim/kriterler", json={"id": r.json()["id"], "version": 1, "is_active": False}
    )
    assert r.status_code == 200 and r.json()["is_active"] is False


# --- Toplu plan -------------------------------------------------------------------------


async def test_toplu_plan_mukerrer_uretmez_ve_iptal_sonrasi_yeniden_planlanir(
    client, db, ortam
) -> None:
    await giris(client, "ik")
    kisiler = [k.id for k in ortam["g"]]
    govde = {"course_id": ortam["kurs"].id, "plan_yili": 2026, "user_ids": kisiler}
    r = await client.post("/api/egitim/planlar/toplu", json=govde)
    assert r.status_code == 200, r.text
    assert (r.json()["olusan"], r.json()["atlanan"]) == (3, 0)
    r = await client.post("/api/egitim/planlar/toplu", json=govde)
    assert (r.json()["olusan"], r.json()["atlanan"]) == (0, 3)
    assert await db.scalar(select(func.count()).select_from(TrainingPlan)) == 3

    p = await db.scalar(select(TrainingPlan).where(TrainingPlan.user_id == kisiler[0]))
    yol = f"/api/egitim/kisiler/{kisiler[0]}/planlar/{p.id}/iptal"
    assert (await client.post(yol, json={"gerekce": "  "})).status_code == 400
    assert (await client.post(yol, json={"gerekce": "Görev değişti"})).status_code == 200
    r = await client.post("/api/egitim/planlar/toplu", json=govde)
    assert (r.json()["olusan"], r.json()["atlanan"]) == (1, 2)


async def test_toplu_plan_ust_siniri_ve_pasif_kurs(client, db, ortam) -> None:
    await giris(client, "ik")
    r = await client.post(
        "/api/egitim/planlar/toplu",
        json={"course_id": ortam["kurs"].id, "plan_yili": 2026, "user_ids": list(range(1, 302))},
    )
    assert r.status_code == 400
    pasif, _ = await kurs(db, "PASIF-01", aktif=False)
    r = await client.post(
        "/api/egitim/planlar/toplu",
        json={"course_id": pasif.id, "plan_yili": 2026, "user_ids": [ortam["g"][0].id]},
    )
    assert r.status_code == 400


async def test_toplu_plan_kapsam_disi_kisi_404_hicbir_sey_yazilmaz(
    client, db, ortam, rol_ac, birimli_kullanici_ac
) -> None:
    await rol_ac("T_EGITIM_BIRIM", ["egitim.gor", "egitim.yaz"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("birim_yazar", "T_EGITIM_BIRIM", ["GUVENLIK"])
    await giris(client, "birim_yazar")
    r = await client.post(
        "/api/egitim/planlar/toplu",
        json={
            "course_id": ortam["kurs"].id,
            "plan_yili": 2026,
            "user_ids": [ortam["g"][0].id, ortam["h1"].id],
        },
    )
    assert r.status_code == 404
    assert await db.scalar(select(func.count()).select_from(TrainingPlan)) == 0


async def test_erteleme_eski_tarihi_saklar_ve_denetime_yazar(client, db, ortam) -> None:
    kisi = ortam["g"][0]
    p = await plan(db, kisi, ortam["kurs"], 2026, hedef=date(2026, 9, 1))
    await giris(client, "ik")
    yol = f"/api/egitim/kisiler/{kisi.id}/planlar/{p.id}/ertele"
    assert (
        await client.post(yol, json={"yeni_tarih": "2026-11-01", "gerekce": ""})
    ).status_code == 400
    r = await client.post(yol, json={"yeni_tarih": "2026-11-01", "gerekce": "Saha yoğunluğu"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ERTELENDI"
    assert r.json()["onceki_hedef_tarih"] == "2026-09-01"
    # İkinci erteleme yalnız tarihi değiştirir (makine öz-geçişi reddederdi).
    r = await client.post(yol, json={"yeni_tarih": "2026-12-01", "gerekce": "Yine ertelendi"})
    assert r.status_code == 200 and r.json()["onceki_hedef_tarih"] == "2026-11-01"
    denetim = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity == "training_plans", AuditLog.action == "ertele")
    )
    assert denetim == 2


async def test_kapsam_disi_kisinin_plani_404_ve_degismez(
    client, db, ortam, rol_ac, birimli_kullanici_ac
) -> None:
    await rol_ac("T_EGITIM_BIRIM", ["egitim.gor", "egitim.yaz"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("birim_yazar", "T_EGITIM_BIRIM", ["GUVENLIK"])
    p = await plan(db, ortam["h1"], ortam["kurs"], 2026)
    await giris(client, "birim_yazar")
    r = await client.post(
        f"/api/egitim/kisiler/{ortam['h1'].id}/planlar/{p.id}/iptal", json={"gerekce": "x"}
    )
    assert r.status_code == 404
    await db.refresh(p)
    assert p.status == "PLANLANDI"
    # Başka kişinin URL'si altında plan kimliği → 404.
    r = await client.post(
        f"/api/egitim/kisiler/{ortam['g'][0].id}/planlar/{p.id}/iptal", json={"gerekce": "x"}
    )
    assert r.status_code == 404
    # Liste kapsamlı.
    assert (await client.get("/api/egitim/planlar")).json() == []


# --- Oturum ve tamamlama kuralı (TS-151) ---------------------------------------------------


async def _oturum(client, kurs_id: int, tarih: str) -> dict:
    r = await client.post(
        "/api/egitim/oturumlar", json={"course_id": kurs_id, "oturum_tarihi": tarih}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _katil(client, oturum_id: int, kisi_id: int, katildi: bool = True, **kw):
    return await client.post(
        "/api/egitim/oturumlar/katilim",
        json={"oturum_id": oturum_id, "user_id": kisi_id, "katildi": katildi, **kw},
    )


async def test_ileri_tarihli_oturum_400_yerel_gun(client, ortam) -> None:
    # 15.06.2026 21:30 UTC = 16.06.2026 00:30 Türkiye: 16.06 "bugün"dür.
    client.clock.set(an(2026, 6, 15, 21))
    client.clock.advance(minutes=30)
    await giris(client, "ik")
    await _oturum(client, ortam["kurs"].id, "2026-06-16")
    r = await client.post(
        "/api/egitim/oturumlar", json={"course_id": ortam["kurs"].id, "oturum_tarihi": "2026-06-17"}
    )
    assert r.status_code == 400


async def test_pasif_kursa_oturum_400(client, db, ortam) -> None:
    pasif, _ = await kurs(db, "PASIF-02", aktif=False)
    await giris(client, "ik")
    r = await client.post(
        "/api/egitim/oturumlar", json={"course_id": pasif.id, "oturum_tarihi": "2026-06-01"}
    )
    assert r.status_code == 400


async def test_en_eski_acik_plan_tamamlanir_ve_gec_sayilir(client, db, ortam) -> None:
    kisi = ortam["g"][0]
    p26 = await plan(db, kisi, ortam["kurs"], 2026)
    p27 = await plan(db, kisi, ortam["kurs"], 2027)
    client.clock.set(an(2027, 1, 20))
    await giris(client, "ik")
    o = await _oturum(client, ortam["kurs"].id, "2027-01-10")
    assert (await _katil(client, o["id"], kisi.id)).status_code == 200
    await db.refresh(p26)
    await db.refresh(p27)
    assert p26.status == "TAMAMLANDI" and p26.completed_on == date(2027, 1, 10)
    assert p27.status == "PLANLANDI"
    satir = next(
        x
        for x in (await client.get(f"/api/egitim/planlar?kisi_id={kisi.id}")).json()
        if x["id"] == p26.id
    )
    assert satir["gec"] is True


async def test_onceki_yil_oturumu_sonraki_yil_planini_kapatmaz(client, db, ortam) -> None:
    kisi = ortam["g"][0]
    p27 = await plan(db, kisi, ortam["kurs"], 2027)
    client.clock.set(an(2026, 12, 20))
    await giris(client, "ik")
    o = await _oturum(client, ortam["kurs"].id, "2026-12-10")
    assert (await _katil(client, o["id"], kisi.id)).status_code == 200
    await db.refresh(p27)
    assert p27.status == "PLANLANDI"
    # Açık plan yoksa katılım yazılır, plan OLUŞTURULMAZ.
    assert await db.scalar(select(func.count()).select_from(TrainingPlan)) == 1
    assert await db.scalar(select(func.count()).select_from(TrainingAttendance)) == 1


async def test_katilmadi_duzeltmesi_plani_geri_acar(client, db, ortam) -> None:
    kisi = ortam["g"][0]
    p = await plan(db, kisi, ortam["kurs"], 2026)
    await giris(client, "ik")
    o = await _oturum(client, ortam["kurs"].id, "2026-06-10")
    await _katil(client, o["id"], kisi.id, son_puan=20)  # eşik NULL: puan önemsiz
    await db.refresh(p)
    assert p.status == "TAMAMLANDI"
    assert (await _katil(client, o["id"], kisi.id, katildi=False)).status_code == 200
    await db.refresh(p)
    assert (p.status, p.completed_on, p.completed_session_id) == ("PLANLANDI", None, None)


async def test_sinav_esigi_altinda_basarisiz_tekrar(client, db, ortam) -> None:
    """P3 (K9): eşik doluysa ve son puan altındaysa BASARISIZ_TEKRAR."""
    k, _ = await kurs(db, "SINAV-01", sinav=70)
    kisi = ortam["g"][1]
    p = await plan(db, kisi, k, 2026)
    await giris(client, "ik")
    o = await _oturum(client, k.id, "2026-06-10")
    await _katil(client, o["id"], kisi.id, son_puan=60)
    await db.refresh(p)
    assert p.status == "BASARISIZ_TEKRAR"


async def test_oturum_tarihi_duzeltmesi_tamamlanma_tarihini_tasir(client, db, ortam) -> None:
    kisi = ortam["g"][0]
    p = await plan(db, kisi, ortam["kurs"], 2026)
    await giris(client, "ik")
    o = await _oturum(client, ortam["kurs"].id, "2026-06-10")
    await _katil(client, o["id"], kisi.id)
    r = await client.patch(
        "/api/egitim/oturumlar",
        json={"id": o["id"], "version": o["version"], "oturum_tarihi": "2026-06-05"},
    )
    assert r.status_code == 200, r.text
    await db.refresh(p)
    assert p.completed_on == date(2026, 6, 5)
    # Katılımlı oturumda yıl değişikliği 409; silme 409.
    r = await client.patch(
        "/api/egitim/oturumlar",
        json={"id": o["id"], "version": r.json()["version"], "oturum_tarihi": "2025-12-30"},
    )
    assert r.status_code == 409
    oturum = await db.get(TrainingSession, o["id"])
    await db.refresh(oturum)
    r = await client.post(
        "/api/egitim/oturumlar/sil", json={"id": o["id"], "version": oturum.version}
    )
    assert r.status_code == 409
    bos = await _oturum(client, ortam["kurs"].id, "2026-06-11")
    r = await client.post("/api/egitim/oturumlar/sil", json={"id": bos["id"], "version": 1})
    assert r.status_code == 204


# --- Excel ve özet görünüm ---------------------------------------------------------------


async def test_plan_xlsx_kapsamli_ve_denetimde(client, db, ortam) -> None:
    from io import BytesIO

    from openpyxl import load_workbook

    await plan(db, ortam["g"][0], ortam["kurs"], 2026)
    await plan(db, ortam["h1"], ortam["kurs"], 2026)
    await giris(client, "yonetim")  # egitim.gor var, servis_rapor.disaaktar yok
    assert (await client.get("/api/egitim/plan.xlsx")).status_code == 403
    await giris(client, "guv_sef")
    r = await client.get("/api/egitim/plan.xlsx?yil=2026")
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.content)).active
    adlar = [ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)]
    assert adlar == ["Guv Bir"]
    assert [c.value for c in ws[1]] == [
        "Personel",
        "Eğitim",
        "Yıl",
        "Hedef Tarih",
        "Durum",
        "Tamamlanma",
        "Son Sınav",
    ]
    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "training_plans", AuditLog.action == "disaaktar")
    )
    assert kayit is not None and kayit.is_personal_data is True


async def test_kisi_listesi_ve_kart_kapsamli_kvkk_loglu(client, db, ortam) -> None:
    birimsiz = await personel(db, "Birimsiz Kisi")
    await giris(client, "guv_sef")
    adlar = {k["ad"] for k in (await client.get("/api/egitim/kisiler?limit=200")).json()}
    assert "Guv Bir" in adlar and "Hab Bir" not in adlar and "Birimsiz Kisi" not in adlar
    assert (await client.get(f"/api/egitim/kisiler/{ortam['h1'].id}/kart")).status_code == 404
    r = await client.get(f"/api/egitim/kisiler/{ortam['g'][0].id}/kart")
    assert r.status_code == 200
    log = await db.scalar(
        select(AuditLog).where(
            AuditLog.entity == "users",
            AuditLog.action == "kisisel.eris",
            AuditLog.entity_id == str(ortam["g"][0].id),
        )
    )
    assert log is not None and log.new_value == {"amac": "egitim.kart"}
    await giris(client, "ik")
    adlar = {k["ad"] for k in (await client.get("/api/egitim/kisiler?limit=200")).json()}
    assert "Birimsiz Kisi" in adlar
    assert birimsiz.id
