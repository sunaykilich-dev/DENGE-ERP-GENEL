"""Ziyaret kartındaki seçili işleri tek işlemde yeniden planlama (TS-046, E02-13).

Kabul: yalnız seçilenler taşınır; tarih/saat değişirse YENIDEN_PLAN + neden
zorunlu (aksi 409); yalnız ekip/araç → EKIP_DEGISIMI; kural ihlalinde 409 +
iş no listesi ve hiçbir satır değişmez; ziyaretin tümü seçildiyse ziyaret
korunur, kısmi seçimde seçilenler yeni ziyarete ayrılır.
"""

import pytest
from planlama_yardim import ortam_fixture, plan_govdesi  # noqa: F401
from sqlalchemy import func, select

from app.models import ServiceOrderEvent, ServicePlan, ServiceVisit

pytestmark = pytest.mark.integration

TOPLU = "/api/teknik-servis/planlama/toplu-plan"
YENIDEN = "/api/teknik-servis/planlama/yeniden-plan"


async def _ziyaret(servis_isi_ac, ortam, adet=3):
    isler = [
        await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon) for _ in range(adet)
    ]
    sef = await ortam.ist("sef_g")
    r = await sef.post(
        TOPLU,
        json={
            **plan_govdesi(),
            "is_idler": [so.id for so in isler],
            "ekip": {"teknisyen_idler": [ortam.kisi("tek1").id]},
        },
    )
    assert r.status_code == 201, r.text
    return isler, r.json()["ziyaret_id"], sef


async def _aktif(db, so_id):
    return await db.scalar(
        select(ServicePlan).where(
            ServicePlan.service_order_id == so_id, ServicePlan.is_active.is_(True)
        )
    )


async def test_secilenler_tasinir_secilmeyen_kalir(ortam, servis_isi_ac, db) -> None:
    (a, b, c), ziyaret_id, sef = await _ziyaret(servis_isi_ac, ortam)
    govde = {**plan_govdesi(tarih="2026-01-20", saat="14:00"), "is_idler": [a.id, b.id]}
    r = await sef.post(YENIDEN, json=govde)
    assert r.status_code == 409  # neden yok
    assert r.json()["is_nolari"] == sorted([a.so_no, b.so_no])
    r = await sef.post(YENIDEN, json={**govde, "degisim_nedeni": "ARAC_YOK"})
    assert r.status_code == 200, r.text
    yeni_ziyaret = r.json()["ziyaret_id"]
    assert yeni_ziyaret not in (None, ziyaret_id)
    for so in (a, b):
        p = await _aktif(db, so.id)
        assert p.change_type == "YENIDEN_PLAN" and p.change_reason == "ARAC_YOK"
        assert p.plan_date.isoformat() == "2026-01-20" and p.visit_id == yeni_ziyaret
    kalan = await _aktif(db, c.id)
    assert kalan.plan_date.isoformat() == "2026-01-15" and kalan.visit_id == ziyaret_id
    olay = await db.scalar(
        select(ServiceOrderEvent)
        .where(ServiceOrderEvent.service_order_id == a.id, ServiceOrderEvent.olay_turu == "PLAN")
        .order_by(ServiceOrderEvent.id.desc())
    )
    assert olay.veri["onceki"]["plan_tarihi"] == "2026-01-15"
    assert olay.veri["plan_tarihi"] == "2026-01-20" and olay.veri["neden"] == "ARAC_YOK"
    # Durum korunur (PLANLANDI kalır).
    await db.refresh(a)
    assert a.status == "PLANLANDI"


async def test_tum_ziyaret_secilince_ziyaret_korunur_yalniz_ekip_degisimi(
    ortam, servis_isi_ac, db
) -> None:
    isler, ziyaret_id, sef = await _ziyaret(servis_isi_ac, ortam, adet=2)
    r = await sef.post(
        YENIDEN,
        json={
            **plan_govdesi(),
            "is_idler": [so.id for so in isler],
            "ekip": {"teknisyen_idler": [ortam.kisi("tek2").id]},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ziyaret_id"] == ziyaret_id
    for so in isler:
        p = await _aktif(db, so.id)
        assert p.change_type == "EKIP_DEGISIMI" and p.change_reason is None
    assert await db.scalar(select(func.count()).select_from(ServiceVisit)) == 1


async def test_kural_ihlali_409_liste_ve_degismez(ortam, servis_isi_ac, db) -> None:
    (a, _, _), _, sef = await _ziyaret(servis_isi_ac, ortam)
    plansiz = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    once = await db.scalar(select(func.count()).select_from(ServicePlan))
    r = await sef.post(
        YENIDEN,
        json={
            **plan_govdesi(tarih="2026-01-21"),
            "is_idler": [a.id, plansiz.id],
            "degisim_nedeni": "MUSTERI_TALEBI",
        },
    )
    assert r.status_code == 409
    assert r.json()["is_nolari"] == [plansiz.so_no]
    assert await db.scalar(select(func.count()).select_from(ServicePlan)) == once
    p = await _aktif(db, a.id)
    assert p.plan_date.isoformat() == "2026-01-15"
    # Kapsam dışı iş 404; plan izni olmayan 403.
    yabanci = await ortam.ist("sef_h")
    r = await yabanci.post(
        YENIDEN, json={**plan_govdesi(), "is_idler": [a.id], "degisim_nedeni": "DIGER"}
    )
    assert r.status_code == 404
    op = await ortam.ist("operasyon")
    r = await op.post(YENIDEN, json={**plan_govdesi(), "is_idler": [a.id]})
    assert r.status_code == 403
