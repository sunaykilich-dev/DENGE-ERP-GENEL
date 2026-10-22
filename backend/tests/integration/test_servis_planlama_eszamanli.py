"""Tek aktif plan: eşzamanlı iki istekten sonra tek aktif satır (TS-040, E02-01).

İki ayrı oturum aynı işe aynı anda plan yazar: iş satırı `FOR UPDATE` ile
kilitlendiği için ikinci istek sıraya girer, birincinin planını görür ve
`beklenen_aktif_plan_id` uyuşmazlığıyla 409 alır. Şema da ikinci aktif satırı
reddeder (`uq_svcplan_aktif`).
"""

import asyncio
from datetime import date, time

import pytest
from planlama_yardim import aktif_plan_sayisi, ortam_fixture  # noqa: F401
from sqlalchemy.exc import IntegrityError

from app.clock import FakeClock
from app.models import ServicePlan, User
from app.services.teknik_servis import planlama

pytestmark = pytest.mark.integration


async def test_eszamanli_iki_plan_istegi_tek_aktif_satir(
    ortam, servis_isi_ac, session_factory, db
) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef_id = ortam.kisi("sef_g").id
    saat = FakeClock()

    async def _planla(dakika: int):
        async with session_factory() as s:
            user = await s.get(User, sef_id)
            girdi = planlama.PlanGirdisi(
                plan_date=date(2026, 1, 15), duration_min=dakika, start_time=time(10, 0)
            )
            try:
                await planlama.planla(s, so, girdi, user=user, clock=saat)
                await asyncio.sleep(0.2)  # kilidi tutarken diğer istek beklesin
                await s.commit()
                return "ok"
            except planlama.PlanlamaHatasi:
                await s.rollback()
                return "409"

    sonuclar = await asyncio.gather(_planla(60), _planla(90))
    assert sorted(sonuclar) == ["409", "ok"]
    assert await aktif_plan_sayisi(db, so.id) == 1


async def test_ikinci_aktif_satir_semada_reddedilir(ortam, servis_isi_ac, db) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    for _ in range(2):
        db.add(
            ServicePlan(
                service_order_id=so.id,
                plan_date=date(2026, 1, 15),
                duration_min=60,
                change_type="ILK_PLAN",
            )
        )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
