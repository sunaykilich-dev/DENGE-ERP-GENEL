"""Plan göçü (TS-175, E02-D04): WorkOrderPlans / TPL- → ziyaret, plan, ekip.

Kabul: kapalıyken planlanmış ve çift aktif plan DÜZELTİLMEZ, raporlanır
(çift aktifin en son planlananı aktif, öncekiler pasif taşınır — veri
atılmaz); işi aktarılmamış plan karantinada; ekip = işin aktif atamaları;
ekranda zaten aktif planı olan işe göç planı pasif yazılır; tekrar koşu 0 yeni.
"""

import pytest
from sqlalchemy import func, select

from app.migration import servis_uzlasma
from app.migration.servis_kaynak import KaynakDizini
from app.models import ServiceOrder, ServicePlan, ServicePlanMember, ServiceVisit
from tests.migration.goc_ortami import FIXTURE, goc_ortami

pytestmark = pytest.mark.integration


async def _plan(db, ref: str) -> ServicePlan:
    return await db.scalar(select(ServicePlan).where(ServicePlan.source_ref == ref))


async def test_plan_gocu_kurallari(seeded):
    db = seeded
    ort = await goc_ortami(db)
    kosu = await servis_uzlasma.kos(
        db, KaynakDizini(FIXTURE), adimlar=("servis", "plan"), uygula=True
    )
    await db.commit()
    plan_sonucu = kosu.sonuclar[1]
    assert plan_sonucu.yeni == 4 and len(plan_sonucu.karantina) == 1
    uyarilar = plan_sonucu.uyari_sayilari()
    assert uyarilar["CIFT_AKTIF_PLAN"] == 2
    assert uyarilar["KAPALI_IKEN_PLANLI"] == 1
    assert uyarilar["SURE_VARSAYILAN"] == 1

    ilk = await _plan(db, "WorkOrderPlans:701")
    assert ilk.is_active and ilk.change_type == "ILK_PLAN" and ilk.duration_min == 120
    assert ilk.legacy_vehicle_text == "34 ABC 123" and ilk.starts_at is not None
    ziyaret = await db.get(ServiceVisit, ilk.visit_id)
    assert ziyaret.source_ref == "TPL:TPL-ABC123" and ziyaret.visit_no.startswith("ZYR-")
    uyeler = (
        await db.scalars(
            select(ServicePlanMember.user_id).where(ServicePlanMember.plan_id == ilk.id)
        )
    ).all()
    assert uyeler == [ort.ali.id]

    eski = await _plan(db, "WorkOrderPlans:702")
    yeni = await _plan(db, "WorkOrderPlans:703")
    assert not eski.is_active and eski.cancelled_at is not None
    assert yeni.is_active and yeni.change_type == "YENIDEN_PLAN"
    # Kapalıyken planlanmış plan düzeltilmez: olduğu gibi aktif.
    assert (await _plan(db, "WorkOrderPlans:705")).is_active

    ikinci = await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), adimlar=("plan",), uygula=True)
    await db.commit()
    assert ikinci.sonuclar[0].yeni == 0
    assert await db.scalar(select(func.count()).select_from(ServicePlan)) == 4


async def test_ekranda_aktif_plan_varsa_goc_plani_pasif(seeded):
    db = seeded
    await goc_ortami(db)
    await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), adimlar=("servis",), uygula=True)
    await db.commit()
    is_ = await db.scalar(select(ServiceOrder).where(ServiceOrder.source_ref == "WorkOrders:101"))
    from datetime import date

    db.add(
        ServicePlan(
            service_order_id=is_.id,
            plan_date=date(2026, 1, 7),
            duration_min=60,
            change_type="ILK_PLAN",
        )
    )
    await db.commit()
    kosu = await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), adimlar=("plan",), uygula=True)
    await db.commit()
    assert kosu.sonuclar[0].uyari_sayilari()["EKRANDA_AKTIF_PLAN_VAR"] == 1
    goc = await _plan(db, "WorkOrderPlans:701")
    assert not goc.is_active and goc.cancelled_at is not None
