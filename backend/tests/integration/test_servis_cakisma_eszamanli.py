"""Sunucu tarafı çakışma kontrolü ve şefin "sahaya gidiyor" bayrağı (TS-045, E02-10/15).

Kabul: 409 `{detail, kod:'PLAN_CAKISMA', cakismalar}`; gerekçeyle geçme
(`servis.planla`, ≥10 karakter); kapsam dışı çakışan iş maskeli (iş no yok);
birimler arası çakışma yakalanır; şef yalnız sahaya gidiyorsa çakışır;
eşzamanlı iki çakışan istekten ikincisi 409 (gün sıralı advisory lock).
"""

import asyncio
from datetime import date, time

import pytest
from planlama_yardim import ortam_fixture, plan_govdesi  # noqa: F401
from sqlalchemy import select

from app.clock import FakeClock
from app.models import ServiceOrderEvent, ServicePlan, User
from app.services.teknik_servis import cakisma, planlama
from app.services.teknik_servis.atama import AtamaSatiri

pytestmark = pytest.mark.integration

YOL = "/api/teknik-servis/planlama/isler/{}/plan"


async def test_birimler_arasi_cakisma_maskeli_ve_gerekceyle_gecilir(
    ortam, servis_isi_ac, db
) -> None:
    ortak = ortam.kisi("tek_ortak").id
    hab = await servis_isi_ac(birim="HABERLESME")
    guv = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef_h = await ortam.ist("sef_h")
    r = await sef_h.put(
        YOL.format(hab.id),
        json=plan_govdesi(saat="10:00", sure=120, ekip={"teknisyen_idler": [ortak]}),
    )
    assert r.status_code == 200, r.text

    sef_g = await ortam.ist("sef_g")
    govde = plan_govdesi(saat="11:00", sure=60, ekip={"teknisyen_idler": [ortak]})
    r = await sef_g.put(YOL.format(guv.id), json=govde)
    assert r.status_code == 409
    g = r.json()
    assert g["kod"] == "PLAN_CAKISMA"
    assert g["cakismalar"][0]["tur"] == "KISI"
    assert g["cakismalar"][0]["maskeli"] is True
    assert g["cakismalar"][0]["so_no"] is None and g["cakismalar"][0]["plan_id"] is None
    assert hab.so_no not in r.text
    # Ön izleme aynı motoru kullanır.
    r = await sef_g.post(
        "/api/teknik-servis/planlama/kontrol",
        json={
            "plan_tarihi": "2026-01-15",
            "baslangic_saati": "11:00",
            "sure_dk": 60,
            "kisi_idler": [ortak],
        },
    )
    assert r.status_code == 200 and len(r.json()["cakismalar"]) == 1

    r = await sef_g.put(YOL.format(guv.id), json={**govde, "cakisma_gerekcesi": "kısa"})
    assert r.status_code == 400
    r = await sef_g.put(
        YOL.format(guv.id), json={**govde, "cakisma_gerekcesi": "Acil arıza, müşteri bekliyor"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["cakisma_gerekcesi"] == "Acil arıza, müşteri bekliyor"
    olay = await db.scalar(
        select(ServiceOrderEvent).where(
            ServiceOrderEvent.service_order_id == guv.id, ServiceOrderEvent.olay_turu == "PLAN"
        )
    )
    assert olay.veri["cakisma_gecildi"] is True

    # Takvimde birim filtresi HABERLESME iken (TUMU kullanıcı) bayrak yanar.
    yon = await ortam.ist("yonetici")
    r = await yon.get(
        "/api/teknik-servis/planlama/takvim",
        params={"baslangic": "2026-01-15", "bitis": "2026-01-15", "birim": "HABERLESME"},
    )
    assert [s["cakisma"] for s in r.json()] == [True]


async def test_sef_yalniz_sahaya_gidiyorsa_cakisir(ortam, servis_isi_ac) -> None:
    sef = ortam.kisi("sef_g").id
    a = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    b = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    ist = await ortam.ist("sef_g")
    r = await ist.put(
        YOL.format(a.id),
        json=plan_govdesi(ekip={"sef_idler": [sef], "teknisyen_idler": [ortam.kisi("tek1").id]}),
    )
    assert r.status_code == 200
    # Şef B'de de sorumlu ama sahaya gitmiyor: çakışma yok.
    r = await ist.put(
        YOL.format(b.id),
        json=plan_govdesi(ekip={"sef_idler": [sef], "teknisyen_idler": [ortam.kisi("tek2").id]}),
    )
    assert r.status_code == 200, r.text
    plan_b = r.json()["plan"]["id"]
    # Şef B'de sahaya gidiyor; A'da sahada değil → hâlâ çakışma yok.
    govde = plan_govdesi(
        beklenen_aktif_plan_id=plan_b,
        ekip={
            "sef_idler": [sef],
            "sahaya_giden_sefler": [sef],
            "teknisyen_idler": [ortam.kisi("tek2").id],
        },
    )
    r = await ist.put(YOL.format(b.id), json=govde)
    assert r.status_code == 200, r.text
    plan_b = r.json()["plan"]["id"]
    # A'da da sahaya çıkarsa çakışır.
    plan_a = (await ist.get(YOL.format(a.id))).json()["plan"]["id"]
    r = await ist.put(
        YOL.format(a.id),
        json=plan_govdesi(
            beklenen_aktif_plan_id=plan_a,
            ekip={
                "sef_idler": [sef],
                "sahaya_giden_sefler": [sef],
                "teknisyen_idler": [ortam.kisi("tek1").id],
            },
        ),
    )
    assert r.status_code == 409
    assert r.json()["cakismalar"][0]["user_id"] == sef
    assert r.json()["cakismalar"][0]["maskeli"] is False


async def test_eszamanli_iki_cakisan_istekten_ikincisi_409(
    ortam, servis_isi_ac, session_factory, db
) -> None:
    tek = ortam.kisi("tek1").id
    sef_id = ortam.kisi("sef_g").id
    isler = [await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon) for _ in range(2)]
    saat = FakeClock()

    async def _planla(so):
        async with session_factory() as s:
            user = await s.get(User, sef_id)
            girdi = planlama.PlanGirdisi(
                plan_date=date(2026, 1, 15),
                duration_min=60,
                start_time=time(9, 0),
                ekip=[AtamaSatiri(user_id=tek, rol="TEKNISYEN", is_lead=True)],
            )
            try:
                await planlama.planla(s, so, girdi, user=user, clock=saat)
                await asyncio.sleep(0.2)
                await s.commit()
                return "ok"
            except cakisma.PlanCakismasi:
                await s.rollback()
                return "409"

    sonuc = await asyncio.gather(*(_planla(so) for so in isler))
    assert sorted(sonuc) == ["409", "ok"]
    aktif = (await db.scalars(select(ServicePlan).where(ServicePlan.is_active.is_(True)))).all()
    assert len(aktif) == 1
