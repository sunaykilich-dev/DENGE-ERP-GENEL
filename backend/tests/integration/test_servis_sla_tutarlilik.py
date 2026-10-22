"""Tek SLA modülü: Python `sla_durumu` = SQL `sla_ifadeleri` (TS-081, E10-18 (2)).

Liste/sayaç/uyarı SQL ifadesini, detay/kart Python hesabını kullanır; ikisi
40 işlik karışık veri setinde (zamanında, riskte, aşılmış, durdurulmuş,
kapalı, PB, damgasız, proje) AYNI durumu ve kalan dakikayı vermeli.
"""

import random
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceHold,
    ServiceOrder,
)
from app.services.teknik_servis import sla

pytestmark = pytest.mark.integration

SIMDI = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


async def test_python_ve_sql_ayni_durumu_verir(db, servis_isi_ac, sozlesme_ac) -> None:
    rnd = random.Random(20261022)
    sozlesme = await sozlesme_ac()
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=SIMDI, sequence_no=1, target_date=date(2026, 3, 1)
    )
    db.add_all([kalem, donem])
    await db.commit()

    isler: list[ServiceOrder] = []
    for i in range(40):
        tip = i % 8
        saat = rnd.choice((12, 24, 72))
        bas = SIMDI - timedelta(minutes=rnd.randint(0, 100 * 60))
        hedef = bas + timedelta(hours=saat)
        kw: dict = {
            "oncelik": rnd.choice(("KRITIK", "YUKSEK", "NORMAL")),
            "durum": rnd.choice(("MUSTERI_TALEBI", "PLANLANDI", "ISLEMDE", "SAHADA")),
            "sla_baslangic_at": bas,
            "cozum_hedef_at": hedef,
            "cozum_hedef_ilk_at": hedef,
            "sla_kaynak": "CANLI",
        }
        if tip == 1:  # kapalı, sonuç donmuş
            kw.update(durum="KAPATILDI", sla_sonuc=rnd.choice(("ZAMANINDA", "ASILDI")))
        elif tip == 2:  # damgasız açık
            kw.update(sla_baslangic_at=None, cozum_hedef_at=None, cozum_hedef_ilk_at=None)
            kw.pop("sla_kaynak")
        elif tip == 3:  # iptal
            kw.update(durum="IPTAL", cancel_reason="test")
        elif tip == 4:  # beklemede (durduran ya da durdurmayan)
            kw.update(durum="BEKLEMEDE")
        elif tip == 5 and i < 8:  # tek PB (uq_so_pb_cihaz_donem)
            kw = {"tur": "PB", "durum": "PLANLAMADA"}
            kw.update(contract_item_id=kalem.id, maintenance_period_id=donem.id)
        elif tip == 6:  # proje
            kw = {"tur": "KURULUM", "durum": "PLANLANDI"}
        so = await servis_isi_ac(**kw)
        if kw.get("durum") == "BEKLEMEDE":
            db.add(
                ServiceHold(
                    service_order_id=so.id,
                    neden=rnd.choice(("MUSTERI_ONAYI", "MALZEME")),
                    onceki_durum="ISLEMDE",
                    started_at=SIMDI - timedelta(minutes=rnd.randint(1, 600)),
                    sla_durdurur=rnd.choice((True, False)),
                )
            )
            await db.commit()
        isler.append(so)
    assert len(isler) >= 35

    ifade = sla.sla_ifadeleri(SIMDI, 80)
    sql = {
        i: (d, k)
        for i, d, k in (
            await db.execute(select(ServiceOrder.id, ifade["durum"], ifade["kalan_dk"]))
        ).all()
    }
    beklemeler = {
        b.service_order_id: b
        for b in (
            await db.scalars(select(ServiceHold).where(ServiceHold.released_at.is_(None)))
        ).all()
    }
    gorulen = set()
    for so in isler:
        await db.refresh(so)
        py = sla.sla_durumu(so, beklemeler.get(so.id), SIMDI, 80)
        assert sql[so.id] == (py.durum, py.kalan_dk), (so.id, so.tur, so.status)
        gorulen.add(py.durum)
    # Veri seti gerçekten karışık olmalı.
    assert {"ZAMANINDA", "ASILDI", "OLCULEMEDI", "SLA_DISI_PB"} <= gorulen
    assert gorulen & {"KARSILANDI", "KARSILANMADI"}

    # Sıralama: işleyen SLA en yakın hedef önce, durdurulanlar sonra, ölçülmeyen en sonda.
    sirali = (
        await db.scalars(select(ServiceOrder.id).order_by(*ifade["siralama"]))
    ).all()
    gruplar = []
    for so_id in sirali:
        d = sql[so_id][0]
        gruplar.append(0 if d in ("ZAMANINDA", "RISKTE", "ASILDI") else 1 if d == "DURDURULDU" else 2)
    assert gruplar == sorted(gruplar)
