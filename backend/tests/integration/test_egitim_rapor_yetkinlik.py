"""Eğitim etkinlik raporu, kurs↔yetkinlik bağı, atamada yetkinlik uyarısı (TS-198).

Kabul (E08-12): 0. gün ort. 60, 90. gün ort. 85 → "+25"; kritikli gözlem
başarısız sayılır; gözlemsiz aşama "veri yok" (null); xlsx'te kapsam dışı
personel yok; `egitim.detay` olmayanın xlsx'inde "Notlar" kolonu yok; formül
enjeksiyonu metne çevrilir. (E08-16 P3) başarılı 90. gün gözlemi listeye bir
kayıt düşürür, değerlendirme girilince düşer, seviye kendiliğinden değişmez.
(E08-22) eşik altı teknisyen uyarılı, eşik üstü uyarısız, eşleme boşsa uyarı
yok; atama ENGELLENMEZ (yalnız okuma).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO

import pytest
from bakim_yardimci import giris
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    Competency,
    CompetencyAssessment,
    CourseCompetency,
    ServiceOrderAssignment,
    TrainingAttendance,
    TrainingCourse,
    TrainingObservation,
    TrainingPlan,
    TrainingSession,
)
from app.services.teknik_servis import egitim_yetkinlik, kancalar

pytestmark = pytest.mark.integration

ONEK = "/api/egitim"


@pytest.fixture
async def ortam(db, birimli_kullanici_ac, rol_ac):
    await rol_ac("T_EGITIM_RAPOR", ["egitim.gor", "servis_rapor.disaaktar"], "TUMU")
    await rol_ac("T_EGITIM_YAZ", ["egitim.gor", "egitim.yaz"], "KENDI_BIRIMI")
    o = {
        "sef": await birimli_kullanici_ac("sef_e", "SERVIS_SEF", ["GUVENLIK"]),
        "sef_h": await birimli_kullanici_ac("sef_eh", "SERVIS_SEF", ["HABERLESME"]),
        "rapor": await birimli_kullanici_ac("rapor_e", "T_EGITIM_RAPOR", ["GUVENLIK"]),
        "yazici": await birimli_kullanici_ac("yazici_e", "T_EGITIM_YAZ", ["GUVENLIK"]),
        "p1": await birimli_kullanici_ac("per1", "SERVIS_TEKNISYEN", ["GUVENLIK"]),
        "p2": await birimli_kullanici_ac("per2", "SERVIS_TEKNISYEN", ["GUVENLIK"]),
        "p3": await birimli_kullanici_ac("per3", "SERVIS_TEKNISYEN", ["HABERLESME"]),
    }
    kurs = TrainingCourse(
        kod="XR-01",
        baslik='=HYPERLINK("http://x")',  # formül enjeksiyonu denemesi
        kategori="TEKNIK",
        birim="GUVENLIK",
        sure_saat=Decimal("4"),
    )
    db.add(kurs)
    await db.commit()
    await db.refresh(kurs)
    o["kurs"] = kurs
    return o


def _gozlem(kisi, kurs, asama, puan, sonuc="BASARILI", gun=date(2026, 3, 1), **kw):
    return TrainingObservation(
        user_id=kisi.id,
        course_id=kurs.id,
        asama=asama,
        gozlem_tarihi=gun,
        puan=Decimal(str(puan)),
        sonuc=sonuc,
        kritik=sonuc == "KRITIK",
        notlar="Gizli gözlem notu",
        **kw,
    )


def _degerlendirme(kisi_id, yetkinlik_id, seviye, gun, degerlendiren_id):
    return CompetencyAssessment(
        user_id=kisi_id,
        competency_id=yetkinlik_id,
        mevcut_seviye=seviye,
        hedef_seviye=3,
        degerlendirme_tarihi=gun,
        assessed_by_user_id=degerlendiren_id,
        kaynak="YONETICI",
    )


async def test_etkinlik_farki_kritik_basarisiz_veri_yok_ve_kapsam(client, db, ortam):
    k, p1, p2, p3 = ortam["kurs"], ortam["p1"], ortam["p2"], ortam["p3"]
    db.add_all(
        [
            _gozlem(p1, k, 0, 50),
            _gozlem(p2, k, 0, 70, "KRITIK"),  # kritik → başarısız
            _gozlem(p1, k, 90, 80),
            _gozlem(p2, k, 90, 90),
            _gozlem(p3, k, 0, 0),  # HABERLESME: GUVENLIK şefinin raporuna girmez
        ]
    )
    oturum = TrainingSession(course_id=k.id, oturum_tarihi=date(2026, 2, 1), sure_saat=Decimal("4"))
    db.add(oturum)
    await db.flush()
    db.add(
        TrainingAttendance(
            session_id=oturum.id, user_id=p1.id, katildi=True, on_puan=40, son_puan=80
        )
    )
    await db.commit()

    await giris(client, "sef_e")
    r = await client.get(f"{ONEK}/rapor/etkinlik", params={"yil": 2026})
    assert r.status_code == 200, r.text
    [satir] = r.json()["satirlar"]
    assert satir["birim"] == "GUVENLIK"
    a0, a30, a90 = (satir["asamalar"][a] for a in ("0", "30", "90"))
    assert a0["ortalama"] == 60.0 and a0["basari_orani"] == 50.0 and a0["adet"] == 2
    assert a90["ortalama"] == 85.0 and a90["basari_orani"] == 100.0
    assert satir["fark_metni"] == "+25" and satir["fark_0_90"] == 25.0
    assert a30["ortalama"] is None and a30["basari_orani"] is None  # veri yok
    assert (satir["sinav_on_ort"], satir["sinav_son_ort"], satir["sinav_fark"]) == (
        40.0,
        80.0,
        40.0,
    )

    # Başka birimin şefi yalnız kendi personelini görür.
    await giris(client, "sef_eh")
    r = await client.get(f"{ONEK}/rapor/etkinlik", params={"yil": 2026})
    [satir] = r.json()["satirlar"]
    assert satir["birim"] == "HABERLESME" and satir["asamalar"]["0"]["ortalama"] == 0.0


async def test_etkinlik_xlsx_detay_kolonu_kapsam_formul_ve_denetim(client, db, ortam, kullanici_ac):
    k = ortam["kurs"]
    db.add_all([_gozlem(ortam["p1"], k, 0, 60), _gozlem(ortam["p3"], k, 0, 10)])
    await db.commit()

    # egitim.gor yetmez: servis_rapor.disaaktar da gerekir (YONETIM'de yok).
    await kullanici_ac("yonetim_e", "YONETIM")
    await giris(client, "yonetim_e")
    assert (await client.get(f"{ONEK}/rapor/etkinlik")).status_code == 200
    assert (await client.get(f"{ONEK}/rapor/etkinlik.xlsx")).status_code == 403

    await giris(client, "sef_e")  # egitim.detay var
    r = await client.get(f"{ONEK}/rapor/etkinlik.xlsx", params={"yil": 2026})
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == [
        "Etkinlik",
        "Plan",
        "Gözlemler",
        "Yetkinlik",
        "Düzeltici Faaliyetler",
        "Belgeler",
    ]
    ws = wb["Gözlemler"]
    assert "Notlar" in [h.value for h in ws[1]]
    kisiler = {ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)}
    assert kisiler == {ortam["p1"].full_name}  # kapsam dışı personel yok
    hucre = wb["Etkinlik"].cell(row=2, column=2)
    assert hucre.data_type == "s" and str(hucre.value).startswith("=HYPERLINK")
    kayit = await db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "servis_rapor.disaaktar", AuditLog.entity == "servis_rapor")
        .order_by(AuditLog.id.desc())
    )
    assert kayit.new_value["rapor"] == "egitim_etkinlik" and kayit.is_personal_data

    await giris(client, "rapor_e")  # egitim.detay yok
    r = await client.get(f"{ONEK}/rapor/etkinlik.xlsx", params={"yil": 2026})
    assert r.status_code == 200
    basliklar = [h.value for h in load_workbook(BytesIO(r.content))["Gözlemler"][1]]
    assert "Notlar" not in basliklar and "Aksiyon Planı" not in basliklar


async def test_kurs_yetkinlik_bagi_ve_yeniden_degerlendir(client, db, ortam):
    k, p1 = ortam["kurs"], ortam["p1"]
    y = Competency(kod="XR", ad="X-Ray Bakımı", birim="GUVENLIK")
    yh = Competency(kod="TLS", ad="Telsiz", birim="HABERLESME")
    pasif = Competency(kod="ESKI", ad="Eski", birim="GUVENLIK", is_active=False)
    db.add_all([y, yh, pasif])
    await db.commit()

    await giris(client, "yazici_e")
    yol = f"{ONEK}/kurs-yetkinlikleri"
    r = await client.put(yol, json={"kurs_id": k.id, "yetkinlik_idler": [yh.id]})
    assert r.status_code == 403  # başka birimin yetkinliği
    r = await client.put(yol, json={"kurs_id": k.id, "yetkinlik_idler": [pasif.id]})
    assert r.status_code == 400  # pasif
    r = await client.put(yol, json={"kurs_id": k.id, "yetkinlik_idler": [y.id]})
    assert r.status_code == 200, r.text
    assert [x["kod"] for x in r.json()] == ["XR"]
    r = await client.get(yol, params={"kurs_id": k.id})
    assert [x["kod"] for x in r.json()] == ["XR"]
    assert await db.scalar(select(func.count()).select_from(CourseCompetency)) == 1

    db.add(_gozlem(p1, k, 90, 95, gun=date(2026, 3, 1)))
    db.add(_degerlendirme(p1.id, y.id, 2, date(2026, 1, 15), ortam["sef"].id))
    await db.commit()
    await giris(client, "sef_e")
    r = await client.get(f"{ONEK}/yeniden-degerlendirilecekler")
    assert r.status_code == 200, r.text
    assert int(r.headers["X-Toplam-Kayit"]) == 1
    assert r.json()[0]["user_id"] == p1.id and r.json()[0]["kod"] == "XR"
    # Seviye kendiliğinden değişmedi (yeni değerlendirme satırı yok).
    adet = await db.scalar(
        select(func.count())
        .select_from(CompetencyAssessment)
        .where(CompetencyAssessment.user_id == p1.id)
    )
    assert adet == 1
    # Başka birimin şefi bu kişiyi görmez.
    await giris(client, "sef_eh")
    r = await client.get(f"{ONEK}/yeniden-degerlendirilecekler")
    assert int(r.headers["X-Toplam-Kayit"]) == 0

    # Gözlemden sonra değerlendirme girilince listeden düşer.
    client.clock.set(datetime(2026, 3, 10, 9, tzinfo=UTC))
    await giris(client, "sef_e")
    r = await client.post(
        f"{ONEK}/yetkinlik-degerlendirmeleri",
        json={
            "user_id": p1.id,
            "competency_id": y.id,
            "mevcut_seviye": 3,
            "degerlendirme_tarihi": "2026-03-02",
        },
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"{ONEK}/yeniden-degerlendirilecekler")
    assert int(r.headers["X-Toplam-Kayit"]) == 0


async def test_gereksinim_ve_atama_uyarisi_engellemez(client, db, ortam, servis_isi_ac):
    p1, p2 = ortam["p1"], ortam["p2"]
    y = Competency(kod="XR", ad="X-Ray Bakımı", birim="GUVENLIK")
    yh = Competency(kod="TLS", ad="Telsiz", birim="HABERLESME")
    kurs = TrainingCourse(
        kod="ISG-YK",
        baslik="Yüksekte Çalışma",
        kategori="ISG",
        sure_saat=Decimal("2"),
        yenileme_ay=12,
    )
    db.add_all([y, yh, kurs])
    await db.flush()
    db.add_all(
        [
            _degerlendirme(p, y.id, s, date(2025, 6, 1), ortam["sef"].id)
            for p, s in ((p1.id, 2), (p2.id, 3))
        ]
    )
    # p2'nin zorunlu eğitimi güncel; p1'inki hiç yok.
    db.add(
        TrainingPlan(
            user_id=p2.id,
            course_id=kurs.id,
            plan_yili=2025,
            hedef_tarih=date(2025, 9, 1),
            status="TAMAMLANDI",
            completed_on=datetime.now(UTC).date(),
        )
    )
    await db.commit()

    await giris(client, "yazici_e")
    yol = f"{ONEK}/yetkinlik-gereksinimleri"
    govde = {
        "birim": "GUVENLIK",
        "tur": "ARIZA",
        "satirlar": [{"competency_id": y.id, "min_seviye": 3, "course_id": kurs.id}],
    }
    assert (await client.put(yol, json={**govde, "birim": "HABERLESME"})).status_code == 403
    baska = {**govde, "satirlar": [{"competency_id": yh.id, "min_seviye": 2}]}
    assert (await client.put(yol, json=baska)).status_code == 403
    assert (await client.put(yol, json={**govde, "tur": "YOK"})).status_code == 400
    r = await client.put(yol, json=govde)
    assert r.status_code == 200, r.text
    assert r.json()[0]["min_seviye"] == 3
    r = await client.get(yol, params={"tur": "ARIZA"})
    assert len(r.json()) == 1

    so = await servis_isi_ac(birim="GUVENLIK", tur="ARIZA", atananlar=[p1, p2])
    uyarilar = await kancalar.atama_uyarilari(db, so, [p1.id, p2.id])
    p1_uyarilari = [u for u in uyarilar if u.startswith(p1.full_name)]
    assert any("seviyesi 2" in u for u in p1_uyarilari)
    assert any("Yüksekte Çalışma" in u for u in p1_uyarilari)
    assert not [u for u in uyarilar if u.startswith(p2.full_name)]
    # Atama engellenmedi (yalnız okuma): iki atama da duruyor.
    atama = await db.scalar(
        select(func.count())
        .select_from(ServiceOrderAssignment)
        .where(ServiceOrderAssignment.service_order_id == so.id)
    )
    assert atama == 2
    # Eşleme boşsa uyarı yok.
    destek = await servis_isi_ac(birim="GUVENLIK", tur="DESTEK")
    assert await egitim_yetkinlik.atama_uyarilari(db, destek, [p1.id]) == []

    await giris(client, "sef_e")
    on = f"{ONEK}/atama-uyarilari"
    r = await client.get(on, params={"so_id": so.id, "user_ids": [p1.id, p2.id]})
    assert r.status_code == 200, r.text
    assert len(r.json()["uyarilar"]) == len(uyarilar)
    yabanci = await servis_isi_ac(birim="HABERLESME", tur="ARIZA")
    r = await client.get(on, params={"so_id": yabanci.id, "user_ids": [p1.id]})
    assert r.status_code == 404
    await giris(client, "rapor_e")  # servis.planla yok
    r = await client.get(on, params={"so_id": so.id, "user_ids": [p1.id]})
    assert r.status_code == 403


async def test_kanca_kayitli():
    assert any(
        getattr(f, "__name__", "") == "_atama_uyarisi_kancasi"
        for f in kancalar.kayitlilar("atama_uyarilari")
    )
