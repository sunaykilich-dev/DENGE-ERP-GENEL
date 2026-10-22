"""Toplu planlama: aynı birim + müşteri + lokasyon → tek ziyaret (TS-043, E02-07, E04-12).

Kabul: 17 iş tek istekte tek ziyaret altında 17 ayrı aktif plan; işler
birleştirilmez (PB cihaz başına kalır); karışık birim/müşteri/lokasyon/kapalı/
planlı iş 409 + iş no listesi ve hiçbir satır yazılmaz; 151 iş 422; kapsam
dışı iş 404.
"""

import re

import pytest
from planlama_yardim import (  # noqa: F401
    aktif_plan_sayisi,
    ortam_fixture,
    plan_govdesi,
    plan_sayisi,
)
from sqlalchemy import func, select

from app.models import Account, ServiceOrder, ServicePlan, ServicePlanMember, ServiceVisit

pytestmark = pytest.mark.integration

YOL = "/api/teknik-servis/planlama/toplu-plan"


def _govde(is_idler, tek_id, **kw):
    return {**plan_govdesi(**kw), "is_idler": is_idler, "ekip": {"teknisyen_idler": [tek_id]}}


async def _isler(servis_isi_ac, ortam, adet: int, **kw):
    return [
        await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, **kw)
        for _ in range(adet)
    ]


async def test_on_yedi_is_tek_ziyaret_ayri_planlar(ortam, servis_isi_ac, db) -> None:
    isler = await _isler(servis_isi_ac, ortam, 17)
    is_sayisi = await db.scalar(select(func.count()).select_from(ServiceOrder))
    sef = await ortam.ist("sef_g")
    r = await sef.post(YOL, json=_govde([so.id for so in isler], ortam.kisi("tek1").id))
    assert r.status_code == 201, r.text
    assert re.match(r"^ZYR-\d{6}-\d{6,}$", r.json()["ziyaret_no"])
    ziyaret_id = r.json()["ziyaret_id"]
    planlar = (
        await db.scalars(select(ServicePlan).where(ServicePlan.visit_id == ziyaret_id))
    ).all()
    assert len(planlar) == 17
    assert all(p.is_active and p.change_type == "ILK_PLAN" for p in planlar)
    assert {p.service_order_id for p in planlar} == {so.id for so in isler}
    assert await db.scalar(select(func.count()).select_from(ServiceOrder)) == is_sayisi
    assert await db.scalar(select(func.count()).select_from(ServiceVisit)) == 1
    uye_sayisi = await db.scalar(select(func.count()).select_from(ServicePlanMember))
    assert uye_sayisi == 17
    for so in isler:
        await db.refresh(so)
        assert so.status == "PLANLANDI"


async def test_karisik_birim_musteri_lokasyon_409_liste_ve_yazim_yok(
    ortam, servis_isi_ac, lokasyon_ac, db
) -> None:
    sef = await ortam.ist("yonetici")  # TUMU: iki birimi de görür, kural 409 sınanır
    tek = ortam.kisi("tek_ortak").id
    a, b = await _isler(servis_isi_ac, ortam, 2)
    baska_birim = await servis_isi_ac(
        musteri=ortam.musteri, lokasyon=ortam.lokasyon, birim="HABERLESME"
    )
    diger_musteri = Account(title="Başka Müşteri", is_musteri=True)
    db.add(diger_musteri)
    await db.commit()
    baska_musteri = await servis_isi_ac(musteri=diger_musteri)
    baska_lok = await servis_isi_ac(
        musteri=ortam.musteri, lokasyon=await lokasyon_ac(ortam.musteri, ad="Başka Tesis")
    )
    for sorunlu in (baska_birim, baska_musteri, baska_lok):
        r = await sef.post(YOL, json=_govde([a.id, b.id, sorunlu.id], tek))
        assert r.status_code == 409, r.text
        assert sorunlu.so_no in r.json()["is_nolari"]
    assert await plan_sayisi(db) == 0
    assert await db.scalar(select(func.count()).select_from(ServiceVisit)) == 0


async def test_planli_ve_kapali_is_secilemez(ortam, servis_isi_ac, db) -> None:
    sef = await ortam.ist("sef_g")
    tek = ortam.kisi("tek1").id
    a, b = await _isler(servis_isi_ac, ortam, 2)
    kapali = await servis_isi_ac(
        musteri=ortam.musteri, lokasyon=ortam.lokasyon, durum="IPTAL", cancel_reason="vazgeçildi"
    )
    r = await sef.post(YOL, json=_govde([a.id, kapali.id], tek))
    assert r.status_code == 409 and r.json()["is_nolari"] == [kapali.so_no]
    r = await sef.put(f"/api/teknik-servis/planlama/isler/{b.id}/plan", json=plan_govdesi())
    assert r.status_code == 200
    r = await sef.post(YOL, json=_govde([a.id, b.id], tek))
    assert r.status_code == 409 and r.json()["is_nolari"] == [b.so_no]
    assert await aktif_plan_sayisi(db, a.id) == 0


async def test_sinir_kapsam_rbac_ve_ekip_zorunlu(ortam, servis_isi_ac, db) -> None:
    so = (await _isler(servis_isi_ac, ortam, 1))[0]
    tek = ortam.kisi("tek1").id
    sef = await ortam.ist("sef_g")
    r = await sef.post(YOL, json=_govde(list(range(1, 152)), tek))
    assert r.status_code == 422
    yabanci = await ortam.ist("sef_h")
    r = await yabanci.post(YOL, json=_govde([so.id], ortam.kisi("tek_h").id))
    assert r.status_code == 404
    op = await ortam.ist("operasyon")
    r = await op.post(YOL, json=_govde([so.id], tek))
    assert r.status_code == 403
    r = await sef.post(YOL, json={**plan_govdesi(), "is_idler": [so.id]})
    assert r.status_code == 400
    await db.refresh(so)
    assert so.status == "MUSTERI_TALEBI"
    assert await plan_sayisi(db) == 0


async def test_pb_isleri_cihaz_basina_ayri_kalir(ortam, servis_isi_ac, db) -> None:
    """PB toplu planlama (E04-12): aynı pencere/uç; her PB işi ayrı plan satırı.

    PB işinin sözleşme kalemi/dönem bağı (`ck_so_pb_bag`) bakım modülünün
    kurulumudur; burada kategori PROJE olan iki kurulum işiyle aynı kural
    sınanır (iş başına plan, iş sayısı değişmez)."""
    isler = await _isler(servis_isi_ac, ortam, 2, tur="KURULUM")
    sef = await ortam.ist("sef_g")
    r = await sef.post(YOL, json=_govde([so.id for so in isler], ortam.kisi("tek1").id))
    assert r.status_code == 201, r.text
    assert await aktif_plan_sayisi(db) == 2
