"""Planlama kapalı/ilerlemiş işin durumunu geri çekmez (TS-040, E02-02 — KRİTİK).

MUSTERI_TALEBI/PLANLAMADA/TEKRAR_ACILDI → PLANLANDI; saha/atölye/bekleme
durumunda yalnız plan güncellenir; kapalı işte 409 ve `db.refresh` sonrası
plan, üye ve durum değişmemiş olur. Toplu plan ve yeniden plan da aynı kuralı
uygular.
"""

import pytest
from planlama_yardim import (  # noqa: F401
    aktif_plan_sayisi,
    ortam_fixture,
    plan_govdesi,
    plan_sayisi,
)
from sqlalchemy import select

from app.models import ServiceOrderEvent

pytestmark = pytest.mark.integration

YOL = "/api/teknik-servis/planlama/isler/{}/plan"


@pytest.mark.parametrize("durum", ["MUSTERI_TALEBI", "PLANLAMADA", "TEKRAR_ACILDI"])
async def test_planlanabilir_durum_planlandiya_gecer(ortam, servis_isi_ac, db, durum) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, durum=durum)
    sef = await ortam.ist("sef_g")
    r = await sef.put(YOL.format(so.id), json=plan_govdesi())
    assert r.status_code == 200, r.text
    await db.refresh(so)
    assert so.status == "PLANLANDI"
    olay = await db.scalar(
        select(ServiceOrderEvent).where(
            ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "DURUM"
        )
    )
    assert olay.eski_durum == durum and olay.yeni_durum == "PLANLANDI"


@pytest.mark.parametrize("durum", ["SAHADA", "ISLEMDE", "YOLA_CIKILDI", "BEKLEMEDE", "ATOLYEDE"])
async def test_ilerlemis_iste_yalniz_plan_guncellenir(ortam, servis_isi_ac, db, durum) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, durum=durum)
    sef = await ortam.ist("sef_g")
    r = await sef.put(YOL.format(so.id), json=plan_govdesi())
    assert r.status_code == 200, r.text
    await db.refresh(so)
    assert so.status == durum
    assert await aktif_plan_sayisi(db, so.id) == 1


@pytest.mark.parametrize("durum", ["TAMAMLANDI", "KAPATILDI", "IPTAL"])
async def test_kapali_iste_her_planlama_ucu_409_ve_degismez(
    ortam, servis_isi_ac, db, durum
) -> None:
    ek = {"cancel_reason": "Müşteri vazgeçti"} if durum == "IPTAL" else {}
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, durum=durum, **ek)
    surum = so.version
    sef = await ortam.ist("sef_g")
    tek = ortam.kisi("tek1").id
    istekler = [
        sef.put(YOL.format(so.id), json=plan_govdesi()),
        sef.request("DELETE", YOL.format(so.id), json={"neden": "MUSTERI_TALEBI"}),
        sef.post(
            "/api/teknik-servis/planlama/toplu-plan",
            json={**plan_govdesi(), "is_idler": [so.id], "ekip": {"teknisyen_idler": [tek]}},
        ),
        sef.post(
            "/api/teknik-servis/planlama/yeniden-plan",
            json={**plan_govdesi(), "is_idler": [so.id], "degisim_nedeni": "MUSTERI_TALEBI"},
        ),
    ]
    for istek in istekler:
        r = await istek
        assert r.status_code == 409, r.text
    await db.refresh(so)
    assert so.status == durum
    assert so.version == surum
    assert await plan_sayisi(db, so.id) == 0
    toplu = await sef.post(
        "/api/teknik-servis/planlama/toplu-plan",
        json={**plan_govdesi(), "is_idler": [so.id], "ekip": {"teknisyen_idler": [tek]}},
    )
    assert so.so_no in toplu.json()["is_nolari"]
