"""Planlama P3: müsaitlik blokları, kaynak görünümü, plan uyumu, bölge önerisi,
eğitim oturumu blokları, kapalı işin planı (TS-190; E02-16/20/21/22/23, E08-D03).

Kilitlenen riskler:
- İzin girilen kişiye o güne plan 409 + gerekçe ister; blok silinince uyarı kalkar.
- Müsaitlik notu ≤200 ve sağlık bilgisi içeremez (KVKK m.6); blok yazımı plan
  yazımının gün kilidini alır (aynı kilit).
- Kapsam dışı personel → 404 ve veri DEĞİŞMEZ.
- Kaynak görünümünde hücre "plan" dakikasıdır; teknisyen yalnız kendi satırını görür.
- Plan uyumu = aynı İstanbul günü; eksik paydaya girmez; Excel = ekran.
- Bölge önerisi aynı ilçe (normalize) — seçilen iş AYRI tekli plan olur.
"""

import io
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from planlama_yardim import ortam_fixture, plan_govdesi  # noqa: F401
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    ServicePlan,
    ServiceTimeEntry,
    ServiceUnavailability,
    TrainingAttendance,
    TrainingCourse,
    TrainingSession,
)

pytestmark = pytest.mark.integration

ON = "/api/teknik-servis/planlama"


def _blok(kisi_id, bas="2026-01-15T09:00:00+03:00", bit="2026-01-15T18:00:00+03:00", **kw):
    return {"kisi_id": kisi_id, "baslangic": bas, "bitis": bit, "tur": "IZIN", **kw}


async def _planla(ist, so_id, **kw):
    r = await ist.put(f"{ON}/isler/{so_id}/plan", json=plan_govdesi(**kw))
    assert r.status_code == 200, r.text
    return r.json()["plan"]


async def _blok_sayisi(db) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ServiceUnavailability)
            .where(ServiceUnavailability.is_deleted.is_(False))
        )
        or 0
    )


# --- Müsaitlik (E02-20) ------------------------------------------------------------


async def test_izinli_kisiye_plan_409_gerekce_ve_silince_uyari_kalkar(
    ortam, servis_isi_ac, db
) -> None:
    sef = await ortam.ist("sef_g")
    tek1 = ortam.kisi("tek1").id
    r = await sef.post(f"{ON}/musaitlik", json=_blok(tek1, **{"not": "Yıllık izin"}))
    assert r.status_code == 201, r.text
    blok = r.json()
    denetim = await db.scalar(select(AuditLog).where(AuditLog.entity == "service_unavailability"))
    assert denetim.is_personal_data is True
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    r = await sef.put(
        f"{ON}/isler/{so.id}/plan", json=plan_govdesi(ekip={"teknisyen_idler": [tek1]})
    )
    assert r.status_code == 409, r.text
    assert r.json()["kod"] == "PLAN_CAKISMA"
    assert [c["tur"] for c in r.json()["cakismalar"]] == ["MUSAITLIK"]
    await _planla(
        sef,
        so.id,
        ekip={"teknisyen_idler": [tek1]},
        cakisma_gerekcesi="Kişi izinden erken dönüyor (test)",
    )
    kpi = {
        k["kod"]: k["deger"]
        for k in (await sef.get(f"{ON}/kpi", params={"gun": "2026-01-15"})).json()
    }
    assert kpi["cakismali"] == 1
    # Aynı kişiye örtüşen ikinci blok 409.
    r = await sef.post(
        f"{ON}/musaitlik",
        json=_blok(tek1, "2026-01-15T17:00:00+03:00", "2026-01-15T19:00:00+03:00"),
    )
    assert r.status_code == 409, r.text
    # Silince çakışma uyarısı kalkar.
    r = await sef.delete(f"{ON}/musaitlik/personel/{tek1}/bloklar/{blok['id']}")
    assert r.status_code == 200, r.text
    kpi = {
        k["kod"]: k["deger"]
        for k in (await sef.get(f"{ON}/kpi", params={"gun": "2026-01-15"})).json()
    }
    assert kpi["cakismali"] == 0
    r = await sef.delete(f"{ON}/musaitlik/personel/{tek1}/bloklar/{blok['id']}")
    assert r.status_code == 409  # zaten silinmiş


async def test_musaitlik_notu_200_ve_saglik_uyarisi(ortam, db) -> None:
    sef = await ortam.ist("sef_g")
    tek1 = ortam.kisi("tek1").id
    r = await sef.post(f"{ON}/musaitlik", json=_blok(tek1, **{"not": "x" * 201}))
    assert r.status_code == 422
    for not_ in ("Hastanede yatıyor", "Sağlık raporu var", "AMELİYAT sonrası"):
        r = await sef.post(f"{ON}/musaitlik", json=_blok(tek1, **{"not": not_}))
        assert r.status_code == 400, (not_, r.text)
        assert "sağlık" in r.json()["detail"].lower()
    r = await sef.post(f"{ON}/musaitlik", json=_blok(tek1, tur="HASTALIK"))
    assert r.status_code == 422  # sağlık ayrı tür değil (K-11)
    assert await _blok_sayisi(db) == 0
    r = await sef.post(f"{ON}/musaitlik", json=_blok(tek1, **{"not": "x" * 200}))
    assert r.status_code == 201


async def test_musaitlik_ayni_gun_kilidiyle_yazilir(ortam, monkeypatch) -> None:
    """Blok yazımı/silimi plan yazımının `gun_kilitleri`ni (aynı anahtar) alır."""
    from app.services.teknik_servis import cakisma

    alinan: list[list[date]] = []
    gercek = cakisma.gun_kilitleri

    async def _kayit(db, gunler):
        gunler = sorted(set(gunler))
        alinan.append(gunler)
        await gercek(db, gunler)

    monkeypatch.setattr(cakisma, "gun_kilitleri", _kayit)
    sef = await ortam.ist("sef_g")
    tek1 = ortam.kisi("tek1").id
    r = await sef.post(
        f"{ON}/musaitlik",
        json=_blok(tek1, "2026-01-15T22:00:00+03:00", "2026-01-16T08:00:00+03:00"),
    )
    assert r.status_code == 201, r.text
    assert alinan[-1] == [date(2026, 1, 15), date(2026, 1, 16)]
    r = await sef.delete(f"{ON}/musaitlik/personel/{tek1}/bloklar/{r.json()['id']}")
    assert r.status_code == 200
    assert alinan[-1] == [date(2026, 1, 15), date(2026, 1, 16)]


async def test_musaitlik_kapsam_ve_yetki(ortam, db) -> None:
    sef_g = await ortam.ist("sef_g")
    tek1 = ortam.kisi("tek1").id
    r = await sef_g.post(f"{ON}/musaitlik", json=_blok(tek1, **{"not": "İzin"}))
    blok_id = r.json()["id"]
    sef_h = await ortam.ist("sef_h")
    r = await sef_h.post(
        f"{ON}/musaitlik",
        json=_blok(tek1, "2026-01-20T09:00:00+03:00", "2026-01-20T10:00:00+03:00"),
    )
    assert r.status_code == 404
    r = await sef_h.delete(f"{ON}/musaitlik/personel/{tek1}/bloklar/{blok_id}")
    assert r.status_code == 404
    blok = await db.get(ServiceUnavailability, blok_id)
    await db.refresh(blok)
    assert blok.is_deleted is False and await _blok_sayisi(db) == 1
    # Blok başka kişinin yolundan silinemez.
    r = await sef_g.delete(f"{ON}/musaitlik/personel/{ortam.kisi('tek2').id}/bloklar/{blok_id}")
    assert r.status_code == 404
    # Teknisyen blok yazamaz; listede yalnız kendisini ve kendi notunu görür.
    tek = await ortam.ist("tek1")
    r = await tek.post(f"{ON}/musaitlik", json=_blok(tek1))
    assert r.status_code == 403
    r = await tek.get(f"{ON}/musaitlik", params={"baslangic": "2026-01-12", "bitis": "2026-01-18"})
    assert [b["not"] for b in r.json()] == ["İzin"]
    tek2 = await ortam.ist("tek2")
    r = await tek2.get(f"{ON}/musaitlik", params={"baslangic": "2026-01-12", "bitis": "2026-01-18"})
    assert r.json() == []
    r = await sef_h.get(
        f"{ON}/musaitlik", params={"baslangic": "2026-01-12", "bitis": "2026-01-18"}
    )
    assert r.json() == []


# --- Kaynak görünümü (E02-21, E08-D03) --------------------------------------------


async def test_kaynak_gorunumu_plan_dakikasi_ve_bloklar(ortam, servis_isi_ac, db) -> None:
    sef = await ortam.ist("sef_g")
    tek1 = ortam.kisi("tek1")
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    await _planla(sef, so.id, sure=90, ekip={"teknisyen_idler": [tek1.id]})
    r = await sef.post(
        f"{ON}/musaitlik",
        json=_blok(tek1.id, "2026-01-16T09:00:00+03:00", "2026-01-16T12:00:00+03:00", tur="OFIS"),
    )
    assert r.status_code == 201
    kurs = TrainingCourse(kod="ISG-01", baslik="İSG Temel", kategori="ISG", sure_saat=Decimal("4"))
    db.add(kurs)
    await db.flush()
    oturum = TrainingSession(
        course_id=kurs.id, oturum_tarihi=date(2026, 1, 17), sure_saat=Decimal("4")
    )
    db.add(oturum)
    await db.flush()
    db.add(TrainingAttendance(session_id=oturum.id, user_id=tek1.id))
    await db.commit()

    r = await sef.get(f"{ON}/kaynak-gorunumu", params={"hafta": "2026-01-15", "birim": "GUVENLIK"})
    assert r.status_code == 200, r.text
    veri = r.json()
    assert veri["hafta_baslangic"] == "2026-01-12" and len(veri["gunler"]) == 7
    satirlar = {s["user_id"]: s for s in veri["satirlar"]}
    # Birimdeki her aktif saha personeli satır alır; planı olmayan boş satır.
    assert {ortam.kisi(k).id for k in ("sef_g", "tek1", "tek2", "tek_ortak")} <= set(satirlar)
    assert ortam.kisi("operasyon").id not in satirlar  # saha rolü yok
    assert ortam.kisi("tek_h").id not in satirlar
    hucre = {h["gun"]: h for h in satirlar[tek1.id]["hucreler"]}
    assert hucre["2026-01-15"]["plan_dk"] == 90 and hucre["2026-01-15"]["ziyaret_sayisi"] == 1
    assert hucre["2026-01-16"]["musaitlik"][0]["tur"] == "OFIS"
    assert hucre["2026-01-17"]["egitim"] == [{"kurs": "İSG Temel", "sure_saat": 4.0}]
    assert satirlar[ortam.kisi("tek2").id]["toplam_plan_dk"] == 0
    # Teknisyen yalnız kendi satırını görür.
    tek = await ortam.ist("tek1")
    r = await tek.get(f"{ON}/kaynak-gorunumu", params={"hafta": "2026-01-15"})
    assert [s["user_id"] for s in r.json()["satirlar"]] == [tek1.id]
    # Kapsam dışı birim 404.
    sef_h = await ortam.ist("sef_h")
    r = await sef_h.get(
        f"{ON}/kaynak-gorunumu", params={"hafta": "2026-01-15", "birim": "GUVENLIK"}
    )
    assert r.status_code == 404


async def test_kapali_isin_plani_cakismaya_girmez(ortam, servis_isi_ac, db) -> None:
    """E02-23: kapatılan işin planı soluk bayrakla döner, çakışma sayılmaz."""
    sef = await ortam.ist("sef_g")
    t1 = ortam.kisi("tek1").id
    a = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    b = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    await _planla(sef, a.id, ekip={"teknisyen_idler": [t1]})
    await db.refresh(a)
    a.status = "KAPATILDI"
    await db.commit()
    await _planla(sef, b.id, ekip={"teknisyen_idler": [t1]})  # 409 yok
    r = await sef.get(f"{ON}/takvim", params={"baslangic": "2026-01-15", "bitis": "2026-01-15"})
    satir = {s["is_id"]: s for s in r.json()}
    assert satir[a.id]["kapali"] is True and satir[a.id]["cakisma"] is False


# --- Plan uyumu (E02-22) ------------------------------------------------------------


async def _zaman(db, so, kisi, bas: datetime, faaliyet: str = "SAHA") -> None:
    db.add(
        ServiceTimeEntry(
            service_order_id=so.id,
            user_id=kisi.id,
            faaliyet=faaliyet,
            started_at=bas,
            ended_at=bas.replace(minute=bas.minute + 20),
            kaynak="MANUEL",
            girildi_at=bas,
            created_by=kisi.id,
        )
    )
    await db.commit()


async def _uyum_verisi(ortam, servis_isi_ac, sozlesme_ac, db, client):
    # Saat oturum açılmadan ayarlanır (oturum süresi FakeClock'a bağlı).
    client.clock.set(datetime(2026, 1, 20, 9, 0, tzinfo=UTC))
    sef = await ortam.ist("sef_g")
    tek1 = ortam.kisi("tek1")
    isler = []
    for _ in range(3):
        so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, atananlar=[tek1])
        await _planla(sef, so.id, ekip={"teknisyen_idler": [tek1.id]}, saat=None)
        isler.append(so)
    from app.models import MaintenanceContractItem, MaintenancePeriod

    sozlesme = await sozlesme_ac(musteri=ortam.musteri)
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    an = datetime(2026, 1, 1, tzinfo=UTC)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=an, sequence_no=1, target_date=an.date()
    )
    db.add_all([kalem, donem])
    await db.commit()
    pb = await servis_isi_ac(
        musteri=ortam.musteri,
        lokasyon=ortam.lokasyon,
        tur="PB",
        contract_item_id=kalem.id,
        maintenance_period_id=donem.id,
    )
    await _planla(sef, pb.id, tarih="2026-01-16", saat=None, ekip={"teknisyen_idler": [tek1.id]})
    gelecek = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    await _planla(sef, gelecek.id, tarih="2026-01-25", saat=None)
    ertelenen = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    ilk = await _planla(sef, ertelenen.id, tarih="2026-01-14", saat=None)
    await _planla(
        sef,
        ertelenen.id,
        tarih="2026-01-17",
        saat=None,
        degisim_nedeni="MUSTERI_TALEBI",
        beklenen_aktif_plan_id=ilk["id"],
    )
    a, b, c = isler
    # 15.01 Türkiye günü 00:30 → UYUMLU; 15.01 22:30 UTC = 16.01 TR → KAYDI; c kayıtsız.
    await _zaman(db, a, tek1, datetime(2026, 1, 14, 21, 30, tzinfo=UTC), "YOL")
    await _zaman(db, b, tek1, datetime(2026, 1, 15, 22, 30, tzinfo=UTC))
    await _zaman(db, pb, tek1, datetime(2026, 1, 16, 7, 0, tzinfo=UTC))
    return sef


async def test_plan_uyumu_ayni_istanbul_gunu_ve_eksik_paydada_yok(
    ortam, servis_isi_ac, sozlesme_ac, db, client
) -> None:
    sef = await _uyum_verisi(ortam, servis_isi_ac, sozlesme_ac, db, client)
    prm = {"baslangic": "2026-01-01", "bitis": "2026-01-31"}
    r = await sef.get(f"{ON}/plan-uyumu", params=prm)
    assert r.status_code == 200, r.text
    rapor = r.json()
    o = rapor["ozet"]
    # a, pb UYUMLU; b KAYDI; c + ertelenen (17.01, kayıtsız) EKSIK; 25.01 gelecek → yok.
    assert (o["uyumlu"], o["kaydi"], o["eksik"]) == (2, 1, 2)
    assert o["oran"] == 66.7  # eksik paydaya girmez
    assert o["ziyaret_sayisi"] == 5 and o["ziyaret_basina_is"] == 1.0
    tur = {k["anahtar"]: k for k in rapor["kirilimlar"]["tur"]}
    assert tur["BAKIM"]["uyumlu"] == 1 and tur["SERVIS"]["kaydi"] == 1
    assert "teknisyen" in rapor["kirilimlar"]  # şef: servis_rapor.personel var
    assert rapor["erteleme"]["toplam"] == 1
    assert rapor["erteleme"]["nedenler"][0]["neden"] == "MUSTERI_TALEBI"
    assert o["tekrar_ziyaret_30"] == 4  # aynı müşteri+lokasyon, 30 gün içinde
    # Sayı = liste.
    for sinif, adet in (("UYUMLU", 2), ("KAYDI", 1), ("EKSIK", 2)):
        r = await sef.get(f"{ON}/plan-uyumu/ayrinti", params={**prm, "sinif": sinif})
        assert int(r.headers["X-Toplam-Kayit"]) == adet == len(r.json()), sinif
    # Excel = ekran; "gerçek süre" başlıklı kolon yok.
    r = await sef.get(f"{ON}/plan-uyumu.xlsx", params=prm)
    assert r.status_code == 200, r.text
    assert r.headers["X-Toplam-Kayit"] == "5"
    kitap = load_workbook(io.BytesIO(r.content))
    assert kitap["Ayrıntı"].max_row - 1 == 5
    for ws in kitap.worksheets:
        for h in ws[1]:
            assert "gerçek" not in str(h.value or "").lower()
    ozet = {s[0].value: s[1].value for s in kitap["Özet"].iter_rows(min_row=2)}
    assert ozet["Plana uyumlu ziyaret"] == 2 and ozet["Uyum oranı (%)"] == 66.7


async def test_plan_uyumu_yetki_ve_kisi_kirilimi(
    ortam, servis_isi_ac, sozlesme_ac, db, client, birimli_kullanici_ac
) -> None:
    await _uyum_verisi(ortam, servis_isi_ac, sozlesme_ac, db, client)
    prm = {"baslangic": "2026-01-01", "bitis": "2026-01-31"}
    tek = await ortam.ist("tek1")
    assert (await tek.get(f"{ON}/plan-uyumu", params=prm)).status_code == 403
    assert (await tek.get(f"{ON}/plan-uyumu.xlsx", params=prm)).status_code == 403
    sef = await ortam.ist("sef_g")
    r = await sef.get(f"{ON}/plan-uyumu", params={**prm, "birim": "HABERLESME"})
    assert r.status_code == 403
    r = await sef.get(f"{ON}/plan-uyumu", params={"baslangic": "2025-01-01", "bitis": "2026-01-31"})
    assert r.status_code == 400  # 366 günden uzun
    await birimli_kullanici_ac("depo_p", "SERVIS_DEPO", ["GUVENLIK"])
    from planlama_yardim import oturum

    depo = await oturum("depo_p")
    r = await depo.get(f"{ON}/plan-uyumu", params=prm)
    assert r.status_code == 200
    assert "teknisyen" not in r.json()["kirilimlar"] and "sef" not in r.json()["kirilimlar"]
    r = await depo.get(f"{ON}/plan-uyumu/ayrinti", params=prm)
    assert all("teknisyenler" not in s for s in r.json())
    await depo.aclose()
    sef_h = await ortam.ist("sef_h")
    r = await sef_h.get(f"{ON}/plan-uyumu", params=prm)
    assert r.json()["ozet"]["ziyaret_sayisi"] == 0  # başka birim görünmez


# --- Bölge önerisi (E02-16) ----------------------------------------------------------


async def test_bolge_onerisi_ayni_ilce_ve_ayri_tekli_plan(
    ortam, servis_isi_ac, lokasyon_ac, db
) -> None:
    sef = await ortam.ist("sef_g")
    tek1 = ortam.kisi("tek1").id
    hedef = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    uskudar2 = await lokasyon_ac(
        ortam.musteri, ad="Üsküdar Depo", il="ISTANBUL", district="ÜSKÜDAR"
    )
    kadikoy = await lokasyon_ac(ortam.musteri, ad="Kadıköy Şube", district="Kadıköy")
    ayni = await servis_isi_ac(musteri=ortam.musteri, lokasyon=uskudar2)
    farkli = await servis_isi_ac(musteri=ortam.musteri, lokasyon=kadikoy)
    ziyaret_isi = await servis_isi_ac(musteri=ortam.musteri, lokasyon=uskudar2)
    await _planla(
        sef,
        ziyaret_isi.id,
        tarih="2026-01-16",
        saat="10:00",
        sure=90,
        ekip={"teknisyen_idler": [tek1]},
    )
    uzak = await servis_isi_ac(musteri=ortam.musteri, lokasyon=uskudar2)
    await _planla(sef, uzak.id, tarih="2026-01-25", saat="10:00")

    r = await sef.get(f"{ON}/bolge-onerisi", params={"is_id": hedef.id, "tarih": "2026-01-15"})
    assert r.status_code == 200, r.text
    oneri = r.json()
    assert oneri["duzey"] == "ilce"
    plansiz = {s["is_id"] for s in oneri["plansiz_isler"]}
    assert ayni.id in plansiz and farkli.id not in plansiz and hedef.id not in plansiz
    (ziyaret,) = oneri["ziyaretler"]  # ±3 gün; 25.01 dışarıda
    assert ziyaret["plan_tarihi"] == "2026-01-16" and ziyaret["onerilen_baslangic"] == "11:30"
    assert [u["user_id"] for u in ziyaret["ekip"]] == [tek1]
    # Seçilen iş AYRI tekli plan: ziyarete eklenmez.
    plan = await _planla(
        sef,
        hedef.id,
        tarih=ziyaret["plan_tarihi"],
        saat=ziyaret["onerilen_baslangic"],
        ekip={"teknisyen_idler": [tek1]},
    )
    diger = await db.scalar(
        select(ServicePlan).where(
            ServicePlan.service_order_id == ziyaret_isi.id, ServicePlan.is_active.is_(True)
        )
    )
    assert plan["is_id"] == hedef.id and plan["id"] != diger.id
    assert plan["ziyaret_id"] is None or plan["ziyaret_id"] != diger.visit_id
    # Kapsam dışı iş 404; plan izni olmayan 403.
    sef_h = await ortam.ist("sef_h")
    r = await sef_h.get(f"{ON}/bolge-onerisi", params={"is_id": hedef.id})
    assert r.status_code == 404
    tek = await ortam.ist("tek1")
    assert (await tek.get(f"{ON}/bolge-onerisi", params={"is_id": hedef.id})).status_code == 403


async def test_bolge_onerisi_ilsiz_lokasyonda_tahmin_yok(ortam, servis_isi_ac) -> None:
    sef = await ortam.ist("sef_g")
    so = await servis_isi_ac(musteri=ortam.musteri)
    r = await sef.get(f"{ON}/bolge-onerisi", params={"is_id": so.id})
    assert r.status_code == 200
    assert r.json()["plansiz_isler"] == [] and r.json()["mesaj"]
