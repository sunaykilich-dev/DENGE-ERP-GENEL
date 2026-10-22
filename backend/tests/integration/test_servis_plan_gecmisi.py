"""Erteleme nedeni, plan geri alma, plan geçmişi (TS-044, E02-12).

Kabul: `DELETE /isler/{id}/plan {neden, not}`; PLANLANDI → PLANLAMADA (diğer
açık durumlar korunur); nedensiz geri alma/erteleme 409; `/plan-gecmisi` tüm
satırları planlayan ve nedenle döner; geri alınan iş havuzda görünür.
"""

import pytest
from planlama_yardim import (  # noqa: F401
    aktif_plan_sayisi,
    ortam_fixture,
    plan_govdesi,
    plan_sayisi,
)
from sqlalchemy import select

from app.models import ServiceOrderEvent, ServicePlan

pytestmark = pytest.mark.integration

YOL = "/api/teknik-servis/planlama/isler/{}/plan"


async def _planli(servis_isi_ac, ortam, durum="MUSTERI_TALEBI"):
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, durum=durum)
    sef = await ortam.ist("sef_g")
    r = await sef.put(YOL.format(so.id), json=plan_govdesi())
    assert r.status_code == 200, r.text
    return so, r.json()["plan"]["id"], sef


async def test_geri_alma_nedensiz_409_nedenli_planlamaya_doner(ortam, servis_isi_ac, db) -> None:
    so, plan_id, sef = await _planli(servis_isi_ac, ortam)
    r = await sef.request("DELETE", YOL.format(so.id), json={})
    assert r.status_code == 409
    assert await aktif_plan_sayisi(db, so.id) == 1
    r = await sef.request("DELETE", YOL.format(so.id), json={"neden": "YOK_BOYLE_NEDEN"})
    assert r.status_code == 400
    r = await sef.request("DELETE", YOL.format(so.id), json={"neden": "DIGER"})
    assert r.status_code == 400  # DIGER açıklama ister
    r = await sef.request(
        "DELETE", YOL.format(so.id), json={"neden": "MUSTERI_TALEBI", "not": "Müşteri erteledi"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "PLANLAMADA"
    plan = await db.get(ServicePlan, plan_id)
    await db.refresh(plan)
    assert plan.is_active is False
    assert plan.cancel_reason == "MUSTERI_TALEBI" and plan.cancel_note == "Müşteri erteledi"
    # Geri alınan iş havuzda görünür.
    r = await sef.get("/api/teknik-servis/planlama/havuz")
    assert so.id in {s["is_id"] for s in r.json()}
    olay = await db.scalar(
        select(ServiceOrderEvent)
        .where(ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "PLAN")
        .order_by(ServiceOrderEvent.id.desc())
    )
    assert olay.veri["islem"] == "GERI_AL"


async def test_sahadaki_isin_plani_geri_alininca_durum_korunur(ortam, servis_isi_ac, db) -> None:
    so, _, sef = await _planli(servis_isi_ac, ortam, durum="SAHADA")
    r = await sef.request("DELETE", YOL.format(so.id), json={"neden": "ONCEKI_IS_UZADI"})
    assert r.status_code == 200, r.text
    await db.refresh(so)
    assert so.status == "SAHADA"
    assert await aktif_plan_sayisi(db, so.id) == 0


async def test_aktif_plan_yoksa_ve_rbac(ortam, servis_isi_ac, db) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef = await ortam.ist("sef_g")
    r = await sef.request("DELETE", YOL.format(so.id), json={"neden": "MUSTERI_TALEBI"})
    assert r.status_code == 409
    op = await ortam.ist("operasyon")
    r = await op.request("DELETE", YOL.format(so.id), json={"neden": "MUSTERI_TALEBI"})
    assert r.status_code == 403
    # Geçmiş okuma servis.gor ile açık.
    r = await op.get(YOL.format(so.id) + "-gecmisi")
    assert r.status_code == 200 and r.json() == []


async def test_plan_gecmisi_tum_satirlar_planlayan_ve_neden(ortam, servis_isi_ac, db) -> None:
    so, plan_id, sef = await _planli(servis_isi_ac, ortam)
    r = await sef.put(
        YOL.format(so.id),
        json=plan_govdesi(
            tarih="2026-01-22",
            beklenen_aktif_plan_id=plan_id,
            degisim_nedeni="DIGER",
            degisim_notu="Bina kapalı",
        ),
    )
    assert r.status_code == 200, r.text
    r = await sef.get(YOL.format(so.id) + "-gecmisi")
    assert r.status_code == 200
    gecmis = r.json()
    assert [g["degisim"] for g in gecmis] == ["ILK_PLAN", "ERTELEME"]
    assert [g["aktif"] for g in gecmis] == [False, True]
    assert gecmis[1]["degisim_nedeni"] == "DIGER" and gecmis[1]["degisim_notu"] == "Bina kapalı"
    assert all(g["planlayan"] == ortam.kisi("sef_g").full_name for g in gecmis)
    assert await plan_sayisi(db, so.id) == 2
