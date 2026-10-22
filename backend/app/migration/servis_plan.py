"""Plan göçü: V1 `WorkOrderPlans` / `TPL-` rota grupları → ziyaret, plan, ekip (TS-175, E02-D04).

Kurallar:

- Plan yalnız göç edilmiş işe bağlanır (`WorkOrders:<Id>` → `service_orders`);
  işi aktarılmamış plan KARANTİNADA kalır (servis işi göçünden sonra koşulur).
- **Düzeltilmez, raporlanır:** kapalı işe kapanıştan sonra yapılmış plan
  (`KAPALI_IKEN_PLANLI`) ve aynı işin birden çok aktif planı
  (`CIFT_AKTIF_PLAN`) olduğu gibi taşınır. Tek aktif plan şemada zorunlu
  (`uq_svcplan_aktif`) olduğundan çift aktifin EN SON planlananı aktif kalır,
  öncekiler `YENIDEN_PLAN` ile pasif aktarılır — veri atılmaz, karar raporda.
- Süre bilinmiyorsa ya da 15–1440 dk dışındaysa 60 dk yazılır ve uyarıya
  düşer (`duration_min` zorunlu; raporlu varsayılan).
- `RouteGroupNo` (`TPL-…`) → `service_visits` (`source_ref='TPL:<no>'`).
- Ekip = işin göçle gelen aktif atamaları (eski planda kişi yoktu); yalnız
  aktif plana yazılır. Adres/telefon plana KOPYALANMAZ (E02 kontrol 2.1).
- İdempotent: `uq_svcplan_kaynak` / `uq_svcvisit_kaynak` ile tekrar koşu 0 yeni.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration.servis_kaynak import (
    GOC_SISTEMI,
    YEREL,
    AdimSonucu,
    KaynakDizini,
    bit,
    gun,
    kaynak_ref,
    metin,
    mevcut_refler,
    saat,
    tamsayi,
    yerel_an,
)
from app.models import (
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServicePlanMember,
    ServiceVehicle,
    ServiceVisit,
)
from app.models.servis_planlama import PLAN_SURE_ALT_DK, PLAN_SURE_UST_DK
from app.models.vehicle import plaka_anahtari
from app.services import audit
from app.services.teknik_servis import numara
from app.services.teknik_servis.planlama import saat_araligi

KAYNAK_TABLO = "WorkOrderPlans"
HEDEF_TABLO = "service_plans"
VARSAYILAN_SURE_DK = 60


@dataclass
class PlanTaslagi:
    ref: str
    is_ref: str
    plan_date: date
    start_time: time | None
    duration_min: int
    planlandi_at: datetime | None
    aktif: bool
    change_type: str
    cancelled_at: datetime | None
    rota: str | None
    plaka: str | None
    site_area: str | None
    site_note: str | None
    plan_note: str | None
    sira_anahtari: tuple = field(default_factory=tuple)


def hazirla(dizin: KaynakDizini, isler: dict[str, dict[str, Any]]) -> AdimSonucu:
    """`isler`: göç edilmiş işler `{source_ref: {id, status, closed_at}}`."""
    planlar = dizin.tablo(KAYNAK_TABLO)
    sonuc = AdimSonucu(KAYNAK_TABLO, HEDEF_TABLO, kaynak=len(planlar))
    gruplar: dict[str, list[PlanTaslagi]] = defaultdict(list)
    gorulen: set[str] = set()

    for sira, p in enumerate(planlar, start=1):
        kimlik = tamsayi(p.get("WorkOrderPlanId"))
        if kimlik is None:
            sonuc.reddet(f"satır {sira}", "WorkOrderPlanId yok")
            continue
        ref = kaynak_ref(KAYNAK_TABLO, kimlik)
        if ref in gorulen:
            sonuc.reddet(ref, "dökümde aynı kimlik iki kez")
            continue
        gorulen.add(ref)
        is_ref = kaynak_ref("WorkOrders", p.get("WorkOrderId"))
        if is_ref not in isler:
            sonuc.karantinaya(ref, f"Plan işi aktarılmamış ({is_ref})")
            continue
        try:
            plan_gunu = gun(p.get("PlanDate"))
            baslangic = saat(p.get("StartTime"))
            planlandi = yerel_an(p.get("PlannedAt"))
            sure = tamsayi(p.get("EstimatedMinutes"))
        except ValueError as exc:
            sonuc.karantinaya(ref, f"Okunamayan alan: {exc}")
            continue
        if plan_gunu is None:
            sonuc.karantinaya(ref, "Plan tarihi yok")
            continue
        if sure is None or not PLAN_SURE_ALT_DK <= sure <= PLAN_SURE_UST_DK:
            sonuc.uyar(ref, "SURE_VARSAYILAN", f"kaynak: {sure}")
            sure = VARSAYILAN_SURE_DK
        t = PlanTaslagi(
            ref=ref,
            is_ref=is_ref,
            plan_date=plan_gunu,
            start_time=baslangic,
            duration_min=sure,
            planlandi_at=planlandi,
            aktif=bit(p.get("IsActive"), varsayilan=True),
            change_type="ILK_PLAN",
            cancelled_at=None,
            rota=metin(p.get("RouteGroupNo")),
            plaka=metin(p.get("VehiclePlate")),
            site_area=(metin(p.get("SiteArea")) or "")[:200] or None,
            site_note=(metin(p.get("SiteDirections")) or "")[:500] or None,
            plan_note=(metin(p.get("PlanNote")) or "")[:1000] or None,
            sira_anahtari=(kimlik,),
        )
        gruplar[is_ref].append(t)

    for is_ref, liste in gruplar.items():
        liste.sort(key=lambda x: (x.planlandi_at is None, x.planlandi_at or 0, x.sira_anahtari[0]))
        aktifler = [x for x in liste if x.aktif]
        if len(aktifler) > 1:
            for x in aktifler:
                sonuc.uyar(x.ref, "CIFT_AKTIF_PLAN", is_ref)
            for x in aktifler[:-1]:
                x.aktif = False
        for i, x in enumerate(liste):
            x.change_type = "ILK_PLAN" if i == 0 else "YENIDEN_PLAN"
            if not x.aktif:
                sonraki = liste[i + 1].planlandi_at if i + 1 < len(liste) else None
                x.cancelled_at = sonraki or x.planlandi_at
                if x.cancelled_at is None:
                    sonuc.karantinaya(x.ref, "Pasif plan için zaman bilgisi yok")
                    continue
            bilgi = isler[is_ref]
            # Kapanış = KAPATILDI anı, yoksa ilk TAMAMLANDI (çözülmüş iş de kapalıdır).
            kapanis = bilgi.get("closed_at")
            if x.aktif and kapanis is not None and x.plan_date > kapanis.astimezone(YEREL).date():
                sonuc.uyar(x.ref, "KAPALI_IKEN_PLANLI", is_ref)
            sonuc.aktarilacak.append(x)
    return sonuc


async def goc_isleri(db: AsyncSession) -> dict[str, dict[str, Any]]:
    return {
        ref: {
            "id": i,
            "status": durum,
            "closed_at": kapanis,
            "birim": birim,
            "customer_id": musteri,
            "address_id": adres,
        }
        for ref, i, durum, kapanis, birim, musteri, adres in (
            await db.execute(
                select(
                    ServiceOrder.source_ref,
                    ServiceOrder.id,
                    ServiceOrder.status,
                    func.coalesce(ServiceOrder.closed_at, ServiceOrder.completed_at),
                    ServiceOrder.birim,
                    ServiceOrder.customer_id,
                    ServiceOrder.address_id,
                ).where(ServiceOrder.source_system == GOC_SISTEMI)
            )
        ).all()
    }


async def hazirla_db(db: AsyncSession, dizin: KaynakDizini) -> AdimSonucu:
    sonuc = hazirla(dizin, await goc_isleri(db))
    var = await mevcut_refler(db, HEDEF_TABLO, KAYNAK_TABLO)
    sonuc.mevcut = sum(1 for t in sonuc.aktarilacak if t.ref in var)
    sonuc.yeni = len(sonuc.aktarilacak) - sonuc.mevcut
    return sonuc


async def _ziyaret(
    db: AsyncSession, rota: str, t: PlanTaslagi, bilgi: dict[str, Any], user_id: int | None
) -> int:
    ref = f"TPL:{rota}"[:64]
    mevcut = await db.scalar(
        select(ServiceVisit.id).where(
            ServiceVisit.source_system == GOC_SISTEMI, ServiceVisit.source_ref == ref
        )
    )
    if mevcut is not None:
        return mevcut
    no = await numara.belge_no(db, "service_visit_no_seq", "ZYR", t.plan_date)
    stmt = (
        insert(ServiceVisit.__table__)
        .values(
            visit_no=no,
            birim=bilgi["birim"],
            customer_id=bilgi["customer_id"],
            address_id=bilgi["address_id"],
            source_system=GOC_SISTEMI,
            source_ref=ref,
            created_by=user_id,
            updated_by=user_id,
        )
        .on_conflict_do_nothing(constraint="uq_svcvisit_kaynak")
        .returning(ServiceVisit.__table__.c.id)
    )
    return (await db.execute(stmt)).scalar()


async def yukle(db: AsyncSession, sonuc: AdimSonucu, *, user_id: int | None = None) -> AdimSonucu:
    isler = await goc_isleri(db)
    araclar = {
        k: i
        for i, k in (
            await db.execute(
                select(ServiceVehicle.id, ServiceVehicle.plate_key).where(
                    ServiceVehicle.is_deleted.is_(False)
                )
            )
        ).all()
    }
    eklenen = uye = pasife = 0
    for t in sonuc.aktarilacak:
        bilgi = isler[t.is_ref]
        so_id = bilgi["id"]
        aktif = t.aktif
        if aktif:
            baska_aktif = await db.scalar(
                select(ServicePlan.id).where(
                    ServicePlan.service_order_id == so_id,
                    ServicePlan.is_active.is_(True),
                    ServicePlan.is_deleted.is_(False),
                    (ServicePlan.source_ref.is_(None)) | (ServicePlan.source_ref != t.ref),
                )
            )
            if baska_aktif is not None:
                aktif = False
                pasife += 1
                sonuc.uyar(t.ref, "EKRANDA_AKTIF_PLAN_VAR", t.is_ref)
        bas, bit_ = saat_araligi(t.plan_date, t.start_time, t.duration_min)
        ziyaret_id = await _ziyaret(db, t.rota, t, bilgi, user_id) if t.rota else None
        degerler = {
            "service_order_id": so_id,
            "visit_id": ziyaret_id,
            "is_active": aktif,
            "plan_date": t.plan_date,
            "start_time": t.start_time,
            "duration_min": t.duration_min,
            "starts_at": bas,
            "ends_at": bit_,
            "vehicle_id": araclar.get(plaka_anahtari(t.plaka)) if t.plaka else None,
            "legacy_vehicle_text": (t.plaka or "")[:30] or None,
            "site_area": t.site_area,
            "site_note": t.site_note,
            "plan_note": t.plan_note,
            "change_type": t.change_type,
            "cancelled_at": None
            if aktif
            else (
                t.cancelled_at
                or t.planlandi_at
                or datetime.combine(t.plan_date, time(0), tzinfo=YEREL)
            ),
            "source_system": GOC_SISTEMI,
            "source_ref": t.ref,
            "created_by": user_id,
            "updated_by": user_id,
        }
        if t.planlandi_at is not None:
            degerler["created_at"] = t.planlandi_at
        stmt = (
            insert(ServicePlan.__table__)
            .values(**degerler)
            .on_conflict_do_nothing(constraint="uq_svcplan_kaynak")
            .returning(ServicePlan.__table__.c.id)
        )
        plan_id = (await db.execute(stmt)).scalar()
        if plan_id is None:
            continue
        eklenen += 1
        if aktif:
            for uid, rol in (
                await db.execute(
                    select(ServiceOrderAssignment.user_id, ServiceOrderAssignment.rol).where(
                        ServiceOrderAssignment.service_order_id == so_id,
                        ServiceOrderAssignment.removed_at.is_(None),
                    )
                )
            ).all():
                db.add(
                    ServicePlanMember(plan_id=plan_id, user_id=uid, rol=rol, sahaya_gidiyor=True)
                )
                uye += 1
    await db.flush()
    sonuc.yeni = eklenen
    sonuc.mevcut = len(sonuc.aktarilacak) - eklenen
    sonuc.ek["sayac"] = {"ekip_uyesi": uye, "ekranda_aktif_var": pasife}
    await audit.log(
        db,
        "service_plans",
        "goc.servis_plan",
        new_value={**sonuc.ozet(), **sonuc.ek["sayac"]},
        user_id=user_id,
    )
    return sonuc
