"""D2-B atölye testlerinin ortak yardımcıları (kabul gövdesi, akış adımları).

`conftest.py` donmuş olduğu için (plan §4.2) paket yardımcıları burada durur;
fixture değil düz fonksiyonlardır.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.models import ServiceFaultReason, ServiceOrderEvent

ATOLYE_NO_DESENI = r"^AT-\d{6}-\d{6,}$"
ONEK = "/api/teknik-servis/atolye"


async def sef(birimli_kullanici_ac, ad: str = "atl_sef", birimler=("HABERLESME",)):
    """Haberleşme şefi: atolye.gor/yaz + servis.kapat + servis.planla; maliyet.gor YOK."""
    return await birimli_kullanici_ac(ad, "SERVIS_SEF", list(birimler), saha_rolu="SEF")


def kabul_govdesi(musteri_id: int, seri: str = "SN-0001", **kw: Any) -> dict[str, Any]:
    ekipman = {"tip": "TELSIZ", "marka": "HYTERA", "model": "PD785", "seri": seri}
    ekipman.update(kw.pop("ekipman", {}))
    govde: dict[str, Any] = {
        "customer_id": musteri_id,
        "service_type": "ARIZA_ONARIMI",
        "receive_type": "ELDEN",
        "customer_complaint": "Cihaz açılmıyor",
        "ekipman": ekipman,
        "aksesuarlar": [{"kind": "BATARYA", "qty": 1}, {"kind": "ANTEN", "qty": 1}],
    }
    govde.update(kw)
    return govde


async def kabul_et(client, musteri_id: int, seri: str = "SN-0001", **kw: Any) -> dict[str, Any]:
    r = await client.post(ONEK, json=kabul_govdesi(musteri_id, seri, **kw))
    assert r.status_code == 201, r.text
    return r.json()


async def detay(client, so_id: int) -> dict[str, Any]:
    r = await client.get(f"{ONEK}/{so_id}")
    assert r.status_code == 200, r.text
    return r.json()


async def duzelt(client, so_id: int, beklenen: int = 200, **alanlar: Any):
    d = await detay(client, so_id)
    r = await client.patch(f"{ONEK}/{so_id}", json={"version": d["version"], **alanlar})
    assert r.status_code == beklenen, r.text
    return r


async def gec(client, so_id: int, hedef: str, beklenen: int = 200, **kw: Any):
    r = await client.post(f"{ONEK}/{so_id}/durum", json={"hedef": hedef, **kw})
    assert r.status_code == beklenen, r.text
    return r


async def ariza_nedeni_id(db, birim: str = "HABERLESME") -> int:
    return await db.scalar(
        select(ServiceFaultReason.id)
        .where(ServiceFaultReason.birim == birim, ServiceFaultReason.is_active.is_(True))
        .order_by(ServiceFaultReason.id)
        .limit(1)
    )


async def teshis_et(client, db, so_id: int, *, onarilabilir: bool = True, onay: bool = True):
    """KABUL_EDILDI → TESHISTE, teşhis alanları (+ müşteri onayı)."""
    await gec(client, so_id, "TESHISTE")
    alanlar: dict[str, Any] = {
        "fault_reason_id": await ariza_nedeni_id(db),
        "is_repairable": onarilabilir,
        "diagnosis_note": "Kart arızası",
    }
    if onay:
        alanlar.update(
            approval_decision="ONAYLANDI",
            approval_channel="TELEFON",
            approved_by_name="Onaylayan Kişi",
        )
    await duzelt(client, so_id, **alanlar)


async def teslime_hazirla(client, db, so_id: int) -> None:
    """Kabul → teşhis → onarım → test GEÇTİ → TESLIME_HAZIR."""
    await teshis_et(client, db, so_id)
    await gec(client, so_id, "ONARIMDA")
    await duzelt(client, so_id, repair_category="PARCA_DEGISIMI", repair_note="Kart değişti")
    await gec(client, so_id, "TEST_KONTROL")
    await duzelt(client, so_id, test_result="GECTI")
    await gec(client, so_id, "TESLIME_HAZIR")


def teslim_govdesi(d: dict[str, Any], *, eksik: bool = False, **kw: Any) -> dict[str, Any]:
    iade = [
        {"id": a["id"], "returned": not (eksik and i == 0)} for i, a in enumerate(d["aksesuarlar"])
    ]
    teslim = {"teslim_alan": "Teslim Alan Kişi", "teslim_tipi": "ELDEN", "aksesuar_iade": iade}
    teslim.update(kw)
    return teslim


async def atolye_olaylari(db, so_id: int, alt_tur: str | None = None) -> list[ServiceOrderEvent]:
    stmt = select(ServiceOrderEvent).where(
        ServiceOrderEvent.service_order_id == so_id, ServiceOrderEvent.olay_turu == "ATOLYE"
    )
    if alt_tur is not None:
        stmt = stmt.where(ServiceOrderEvent.veri["alt_tur"].astext == alt_tur)
    return list((await db.scalars(stmt.order_by(ServiceOrderEvent.id))).all())


async def olay_say(db, so_id: int, tur: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ServiceOrderEvent)
            .where(ServiceOrderEvent.service_order_id == so_id, ServiceOrderEvent.olay_turu == tur)
        )
        or 0
    )
