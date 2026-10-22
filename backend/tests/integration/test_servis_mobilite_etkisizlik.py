"""Mobilite etkisizlik regresyonu (TS-028; E01-D04, E02-D03, KD-01).

Gerçek risk: servis işi mobilite `work_orders`'a yazılsaydı hak ediş, panel
ve altın kayıt (932 iş / 552.825,00 TL) kirlenirdi. Servis akışının TAMAMI
(açılış, atama, saha, bekleme, sonuç, kapat, yeniden aç, iptal, düzeltme,
seri, toplu atama, Excel) koşulduktan sonra mobilite tablolarının satır
sayıları ve özeti, mobilite uyarıları ve `reports.dashboard` AYNI kalmalı.
"""

import pytest
from servis_yardimci import acilis, giris, musteri, teknisyen
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import (
    Device,
    DeviceStatusHistory,
    PartnerSettlement,
    Payment,
    SettlementLine,
    User,
    Vehicle,
    WorkOrder,
    WorkOrderItem,
)
from app.services import reports, uyarilar
from app.services.teknik_servis import uyarilar as ts_uyarilar

pytestmark = pytest.mark.integration

_MOBILITE = (WorkOrder, WorkOrderItem, PartnerSettlement, SettlementLine, Payment, Device,
             DeviceStatusHistory, Vehicle)  # fmt: skip


async def _ozet(db, admin, clock) -> dict:
    sayilar = {
        m.__tablename__: await db.scalar(select(func.count()).select_from(m)) for m in _MOBILITE
    }
    cihaz_durumlari = sorted(
        (await db.execute(select(Device.id, Device.status).order_by(Device.id))).all()
    )
    pano = await reports.dashboard(db, clock)
    ts_kodlari = {u.kod for u in await ts_uyarilar.topla(db, admin, clock)}
    mobilite_uyarilari = sorted(
        (u.kod, u.adet) for u in (await uyarilar.topla(db, clock, admin)).uyarilar
        if u.kod not in ts_kodlari
    )  # fmt: skip
    return {
        "sayilar": sayilar,
        "cihazlar": cihaz_durumlari,
        "pano": pano,
        "uyarilar": mobilite_uyarilari,
    }


async def test_servis_akisi_mobiliteye_dokunmaz(
    client, db, kullanici_ac, birimli_kullanici_ac, cihaz_ac
) -> None:
    await kullanici_ac("admin_m", "ADMIN")
    await kullanici_ac("mud_mb", "SERVIS_YONETICI")
    t1 = await teknisyen(birimli_kullanici_ac, "tek_mb1")
    t2 = await teknisyen(birimli_kullanici_ac, "tek_mb2")
    cihaz = await cihaz_ac(imei="356938035643809")
    hesap = await musteri(db)
    admin = await db.scalar(select(User).where(User.username == "admin_m"))
    clock = FakeClock()
    once = await _ozet(db, admin, clock)

    await giris(client, "mud_mb")
    yol = "/api/teknik-servis/isler"
    # Mobilite birimi + cihazın IMEI'siyle açılan servis işi de devices'a yazmaz.
    r = await client.post(yol, json=acilis(hesap.id, birim="MOBILITE", seriler=[cihaz.imei]))
    assert r.status_code == 201, r.text
    mob = r.json()["id"]
    r = await client.post(yol, json=acilis(hesap.id, seriler=["SN-MB-1"]))
    so = r.json()["id"]
    r = await client.post(yol, json=acilis(hesap.id, konu="İkinci"))
    ikinci = r.json()["id"]
    ekip = {"atamalar": [{"user_id": t1.id, "is_lead": True}, {"user_id": t2.id}]}
    assert (await client.put(f"{yol}/{so}/atama", json=ekip)).status_code == 200
    assert (await client.post(f"{yol}/{so}/durum", json={"hedef": "ISLEMDE"})).status_code == 200
    assert (await client.post(f"{yol}/{so}/bekleme", json={"neden": "MALZEME"})).status_code == 200
    assert (await client.post(f"{yol}/{so}/bekleme/bitir", json={})).status_code == 200
    sonuc = {
        "sonuc": "COZULDU",
        "cozum_kanali": "YERINDE",
        "yapilan_islem": "Onarıldı",
        "sure_eksik_onay": True,
    }
    assert (await client.post(f"{yol}/{so}/sonuc", json=sonuc)).status_code == 200
    assert (await client.post(f"{yol}/{so}/kapat", json={})).status_code == 200
    r = await client.post(f"{yol}/{so}/yeniden-ac", json={"gerekce": "Tekrarladı"})
    assert r.status_code == 200
    r = await client.patch(f"{yol}/{so}", json={"version": r.json()["version"], "konu": "Düz."})
    assert r.status_code == 200
    assert (
        await client.put(f"{yol}/{so}/seriler", json={"seriler": ["SN-MB-2"]})
    ).status_code == 200
    r = await client.put(
        f"{yol}/toplu-atama", json={"is_idler": [ikinci, mob], "atamalar": [], "mod": "EKLE"}
    )
    assert r.status_code in (200, 409)  # MOBILITE ve GUVENLIK karışık → 409
    assert (
        await client.post(f"{yol}/{ikinci}/iptal", json={"gerekce": "Mükerrer"})
    ).status_code == 200
    assert (await client.post(f"{yol}/{mob}/notlar", json={"metin": "not"})).status_code == 201
    assert (await client.get(f"{yol}.xlsx")).status_code == 200

    sonra = await _ozet(db, admin, clock)
    assert sonra == once
