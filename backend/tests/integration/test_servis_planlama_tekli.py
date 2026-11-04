"""Tekli plan + ekip ataması: tek uç, tek transaction (TS-041, E02-03).

Kabul: `PUT /isler/{id}/plan` + `beklenen_aktif_plan_id`; uyuşmazlık 409;
şema ihlali 422; ekip `atama.ata` ile (plan üyeleri = atamalar); araç aktif
ve birimi uygun, aksi 409; hata enjeksiyonunda ne plan ne üye ne atama yazılır;
kapsam dışı iş 404 ve veri değişmez.
"""

import pytest
from planlama_yardim import (  # noqa: F401
    aktif_plan_sayisi,
    ortam_fixture,
    plan_govdesi,
    plan_sayisi,
)
from sqlalchemy import func, select

from app.models import (
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServicePlan,
    ServicePlanMember,
    ServiceVehicle,
)
from app.services.teknik_servis import planlama
from app.services.teknik_servis.kancalar import ServisHatasi

pytestmark = pytest.mark.integration

YOL = "/api/teknik-servis/planlama/isler/{}/plan"


async def _is(servis_isi_ac, ortam, **kw):
    return await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, **kw)


async def test_rbac_plan_izni_yoksa_403_varsa_200(ortam, servis_isi_ac, db) -> None:
    so = await _is(servis_isi_ac, ortam)
    op = await ortam.ist("operasyon")
    r = await op.put(YOL.format(so.id), json=plan_govdesi())
    assert r.status_code == 403
    assert await plan_sayisi(db, so.id) == 0

    sef = await ortam.ist("sef_g")
    r = await sef.put(YOL.format(so.id), json=plan_govdesi())
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "PLANLANDI"
    assert r.json()["plan"]["degisim"] == "ILK_PLAN"
    assert await aktif_plan_sayisi(db, so.id) == 1


async def test_kapsam_disi_is_404_ve_veri_degismez(ortam, servis_isi_ac, db) -> None:
    so = await _is(servis_isi_ac, ortam)
    yabanci = await ortam.ist("sef_h")
    for istek in (
        yabanci.put(YOL.format(so.id), json=plan_govdesi()),
        yabanci.request("DELETE", YOL.format(so.id), json={"neden": "MUSTERI_TALEBI"}),
        yabanci.get(YOL.format(so.id)),
        yabanci.get(YOL.format(so.id) + "-gecmisi"),
        yabanci.get(f"/api/teknik-servis/planlama/isler/{so.id}/saha-onerisi"),
    ):
        r = await istek
        assert r.status_code == 404, r.text
    await db.refresh(so)
    assert so.status == "MUSTERI_TALEBI"
    assert await plan_sayisi(db, so.id) == 0


@pytest.mark.parametrize(
    "govde",
    [
        {"baslangic_saati": "10:00", "sure_dk": 60},  # tarihsiz
        plan_govdesi(sure=10),
        plan_govdesi(sure=2000),
        plan_govdesi(ekip={"teknisyen_idler": list(range(1, 32))}),  # 31 teknisyen
    ],
)
async def test_sema_ihlali_422(ortam, servis_isi_ac, db, govde) -> None:
    so = await _is(servis_isi_ac, ortam)
    sef = await ortam.ist("sef_g")
    r = await sef.put(YOL.format(so.id), json=govde)
    assert r.status_code == 422
    assert await plan_sayisi(db, so.id) == 0


async def test_ekip_atama_ile_yazilir_plan_uyeleri_ayni(ortam, servis_isi_ac, db) -> None:
    so = await _is(servis_isi_ac, ortam)
    sef = await ortam.ist("sef_g")
    tek1, tek2, sefg = ortam.kisi("tek1"), ortam.kisi("tek2"), ortam.kisi("sef_g")
    r = await sef.put(
        YOL.format(so.id),
        json=plan_govdesi(
            ekip={
                "sef_idler": [sefg.id],
                "teknisyen_idler": [tek1.id, tek2.id],
                "sorumlu_id": tek2.id,
            }
        ),
    )
    assert r.status_code == 200, r.text
    atamalar = (
        await db.scalars(
            select(ServiceOrderAssignment).where(
                ServiceOrderAssignment.service_order_id == so.id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    ).all()
    assert {(a.user_id, a.rol) for a in atamalar} == {
        (sefg.id, "SEF"),
        (tek1.id, "TEKNISYEN"),
        (tek2.id, "TEKNISYEN"),
    }
    assert next(a.user_id for a in atamalar if a.is_lead) == tek2.id
    plan_id = r.json()["plan"]["id"]
    uyeler = (
        await db.scalars(select(ServicePlanMember).where(ServicePlanMember.plan_id == plan_id))
    ).all()
    assert {(u.user_id, u.rol) for u in uyeler} == {(a.user_id, a.rol) for a in atamalar}
    # Şef varsayılan olarak sahaya gitmez; teknisyen hep sahada.
    assert {u.user_id: u.sahaya_gidiyor for u in uyeler} == {
        sefg.id: False,
        tek1.id: True,
        tek2.id: True,
    }

    # Ekip gönderilmeden ikinci kayıt: ekip korunur, değişim EKIP_DEGISIMI.
    r2 = await sef.put(
        YOL.format(so.id),
        json=plan_govdesi(sure=90, beklenen_aktif_plan_id=plan_id),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["plan"]["degisim"] == "EKIP_DEGISIMI"
    assert {u["user_id"] for u in r2.json()["plan"]["ekip"]} == {sefg.id, tek1.id, tek2.id}
    assert await aktif_plan_sayisi(db, so.id) == 1
    assert await plan_sayisi(db, so.id) == 2


async def test_beklenen_aktif_plan_uyusmazligi_409(ortam, servis_isi_ac, db) -> None:
    so = await _is(servis_isi_ac, ortam)
    sef = await ortam.ist("sef_g")
    r = await sef.put(YOL.format(so.id), json=plan_govdesi())
    assert r.status_code == 200
    # İstemci eski ekranla (aktif plan yok sanarak) tekrar kaydediyor.
    r2 = await sef.put(YOL.format(so.id), json=plan_govdesi(sure=120))
    assert r2.status_code == 409
    assert r2.json()["kod"] == "PLAN_KURAL"
    assert await plan_sayisi(db, so.id) == 1


async def test_arac_aktif_ve_birimi_uygun_olmali(ortam, servis_isi_ac, db) -> None:
    so = await _is(servis_isi_ac, ortam)
    pasif = ServiceVehicle(plate="34 PAS 001", birim="GUVENLIK", is_active=False)
    baska = ServiceVehicle(plate="34 HAB 001", birim="HABERLESME")
    ortak = ServiceVehicle(plate="34 ORT 001", birim=None)
    db.add_all([pasif, baska, ortak])
    await db.commit()
    sef = await ortam.ist("sef_g")
    for arac in (pasif, baska):
        r = await sef.put(YOL.format(so.id), json=plan_govdesi(arac_id=arac.id))
        assert r.status_code == 409, r.text
    assert await plan_sayisi(db, so.id) == 0
    r = await sef.put(YOL.format(so.id), json=plan_govdesi(arac_id=ortak.id))
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["arac_id"] == ortak.id


async def test_ekipte_baska_birim_ya_da_ayrilmis_kisi(ortam, servis_isi_ac, db) -> None:
    from datetime import date

    so = await _is(servis_isi_ac, ortam)
    sef = await ortam.ist("sef_g")
    r = await sef.put(
        YOL.format(so.id), json=plan_govdesi(ekip={"teknisyen_idler": [ortam.kisi("tek_h").id]})
    )
    # Başka ŞİRKETİN kişisi (HABERLESME = TELEKOM, iş GUVENLIK = ELEKTRONİK):
    # "bulunamadı", ad yok (KARARLAR 2026-11-04 §6.4). Aynı şirketin başka birimi 409.
    assert r.status_code == 400, r.text
    assert "Kullanıcı bulunamadı" in r.text
    tek2 = ortam.kisi("tek2")
    tek2.ayrilis_tarihi = date(2025, 12, 31)
    tek2.ayrilis_nedeni = "ISTIFA"
    await db.commit()
    r = await sef.put(YOL.format(so.id), json=plan_govdesi(ekip={"teknisyen_idler": [tek2.id]}))
    assert r.status_code == 400, r.text
    assert await plan_sayisi(db, so.id) == 0
    await db.refresh(so)
    assert so.status == "MUSTERI_TALEBI"


async def test_hata_enjeksiyonunda_ne_plan_ne_uye_ne_atama(
    ortam, servis_isi_ac, db, monkeypatch
) -> None:
    so = await _is(servis_isi_ac, ortam)

    async def _patla(*a, **kw):
        raise ServisHatasi("enjekte edilen hata")

    monkeypatch.setattr(planlama, "_plan_olayi", _patla)
    sef = await ortam.ist("sef_g")
    r = await sef.put(
        YOL.format(so.id),
        json=plan_govdesi(ekip={"teknisyen_idler": [ortam.kisi("tek1").id]}),
    )
    assert r.status_code == 409
    await db.refresh(so)
    assert so.status == "MUSTERI_TALEBI"
    assert await plan_sayisi(db, so.id) == 0
    assert await db.scalar(select(func.count()).select_from(ServicePlanMember)) == 0
    assert (
        await db.scalar(
            select(func.count())
            .select_from(ServiceOrderAssignment)
            .where(ServiceOrderAssignment.service_order_id == so.id)
        )
        == 0
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(ServiceOrderEvent)
            .where(ServiceOrderEvent.service_order_id == so.id)
        )
        == 0
    )


async def test_plan_olayi_onceki_ve_yeni_tarih(ortam, servis_isi_ac, db) -> None:
    so = await _is(servis_isi_ac, ortam)
    sef = await ortam.ist("sef_g")
    r = await sef.put(YOL.format(so.id), json=plan_govdesi())
    plan_id = r.json()["plan"]["id"]
    # Tarih değişiyor: neden zorunlu (erteleme).
    r = await sef.put(
        YOL.format(so.id),
        json=plan_govdesi(tarih="2026-01-20", beklenen_aktif_plan_id=plan_id),
    )
    assert r.status_code == 409
    r = await sef.put(
        YOL.format(so.id),
        json=plan_govdesi(
            tarih="2026-01-20", beklenen_aktif_plan_id=plan_id, degisim_nedeni="PERSONEL_YOK"
        ),
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["degisim"] == "ERTELEME"
    olay = await db.scalar(
        select(ServiceOrderEvent)
        .where(ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "PLAN")
        .order_by(ServiceOrderEvent.id.desc())
    )
    assert olay.veri["onceki"]["plan_tarihi"] == "2026-01-15"
    assert olay.veri["plan_tarihi"] == "2026-01-20"
    assert olay.veri["neden"] == "PERSONEL_YOK"
    eski = await db.get(ServicePlan, plan_id)
    await db.refresh(eski)
    assert eski.is_active is False and eski.cancelled_at is not None


async def test_planlama_disi_ekip_degisimi_aktif_planda_ekip_degisimi_satiri(
    ortam, servis_isi_ac, db, client
) -> None:
    """E02-D01: iş ekranından (atama.ata) ekip değişince aktif plan yeni
    EKIP_DEGISIMI satırıyla güncellenir; tarih/saat/araç aynen kalır."""
    from app.services.teknik_servis import atama
    from app.services.teknik_servis.atama import AtamaSatiri

    so = await _is(servis_isi_ac, ortam)
    sef = await ortam.ist("sef_g")
    r = await sef.put(
        YOL.format(so.id),
        json=plan_govdesi(ekip={"teknisyen_idler": [ortam.kisi("tek1").id]}),
    )
    eski_id = r.json()["plan"]["id"]
    await db.refresh(so)
    await atama.ata(
        db,
        so,
        [AtamaSatiri(user_id=ortam.kisi("tek2").id, rol="TEKNISYEN", is_lead=True)],
        user=ortam.kisi("sef_g"),
        clock=client.clock,
    )
    await db.commit()
    yeni = await db.scalar(
        select(ServicePlan).where(
            ServicePlan.service_order_id == so.id, ServicePlan.is_active.is_(True)
        )
    )
    assert yeni.id != eski_id and yeni.change_type == "EKIP_DEGISIMI"
    assert yeni.plan_date.isoformat() == "2026-01-15"
    uyeler = (
        await db.scalars(select(ServicePlanMember).where(ServicePlanMember.plan_id == yeni.id))
    ).all()
    assert [u.user_id for u in uyeler] == [ortam.kisi("tek2").id]
    eski = await db.get(ServicePlan, eski_id)
    await db.refresh(eski)
    assert eski.is_active is False and eski.cancelled_at is not None
