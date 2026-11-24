"""Takvimde plansız işler (2026-11-24 sahip kararı).

Aktif planı olmayan iş, başladığı günden (bildirim) bittiği güne (tamamlanma,
yoksa kapanış) kadar her günde soluk kart olur; açık iş yalnız başladığı
günde; iptal ve planlı iş bu listede yok; aralık dışı iş gelmez.
"""

from datetime import UTC, date, datetime

import pytest
from servis_yardimci import giris

from app.models import ServicePlan
from app.services.teknik_servis import takvim

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/planlama/takvim/plansiz"


def _an(gun: int, ay: int = 10) -> datetime:
    return datetime(2026, ay, gun, 9, 0, tzinfo=UTC)


async def test_plansiz_isler_gun_araligi(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_tk", "SERVIS_SEF", ["GUVENLIK"])
    kapali = await servis_isi_ac(
        durum="KAPATILDI",
        konu="Üç günlük iş",
        reported_at=_an(5),
        completed_at=_an(7),
        closed_at=_an(9),
    )
    acik = await servis_isi_ac(durum="ISLEMDE", konu="Açık iş", reported_at=_an(6))
    iptal = await servis_isi_ac(
        durum="IPTAL", konu="İptal", reported_at=_an(6), cancel_reason="Vazgeçildi"
    )
    planli = await servis_isi_ac(durum="PLANLANDI", konu="Planlı", reported_at=_an(6))
    db.add(
        ServicePlan(
            service_order_id=planli.id,
            plan_date=date(2026, 10, 6),
            duration_min=60,
            change_type="ILK_PLAN",
        )
    )
    eski = await servis_isi_ac(
        durum="KAPATILDI", konu="Eski", reported_at=_an(1, 9), completed_at=_an(2, 9)
    )
    await db.commit()

    await giris(client, "sef_tk")
    r = await client.get(URL, params={"baslangic": "2026-10-01", "bitis": "2026-10-31"})
    assert r.status_code == 200, r.text
    satirlar = {x["is_id"]: x for x in r.json()}
    assert (satirlar[kapali.id]["baslangic"], satirlar[kapali.id]["bitis"]) == (
        "2026-10-05",
        "2026-10-07",
    )
    assert satirlar[kapali.id]["kapali"] is True
    assert (satirlar[acik.id]["baslangic"], satirlar[acik.id]["bitis"]) == (
        "2026-10-06",
        "2026-10-06",
    )
    for yok in (iptal, planli, eski):
        assert yok.id not in satirlar

    # Aralık işin bitişinden sonra başlarsa gelmez; ortasına denk gelirse gelir.
    r = await client.get(URL, params={"baslangic": "2026-10-08", "bitis": "2026-10-10"})
    assert kapali.id not in {x["is_id"] for x in r.json()}
    r = await client.get(URL, params={"baslangic": "2026-10-07", "bitis": "2026-10-07"})
    assert kapali.id in {x["is_id"] for x in r.json()}

    # Aralık sınırı takvimle aynı.
    r = await client.get(URL, params={"baslangic": "2026-01-01", "bitis": "2026-12-31"})
    assert r.status_code == 400
    assert takvim.TAKVIM_AZAMI_GUN == 62
