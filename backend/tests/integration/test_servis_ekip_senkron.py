"""Atama kancaları: `ekip_degisiyor` reddi tüm isteği geri alır, `ekip_degisti`
yeni ekiple çağrılır (TS-025; E02-08, E09-09).

Gerçek kural (D1-G): açık sayacı olan kişi ekipten çıkarılamaz ("Ali Veli'nin
SRV-… sayacını bitirin"). Toplu atamada ikinci işte gelen ret, ilk işteki
değişikliği de geri almalı — yarım toplu atama, kimin hangi işte olduğunu
bilinmez kılar. Planlama (D1-D) `ekip_degisti` ile aktif plan üyelerini
atamalarla eşitler.
"""

import pytest
from servis_yardimci import giris, olay_sayisi, teknisyen
from sqlalchemy import select

from app.models import ServiceOrderAssignment
from app.services.teknik_servis import kancalar
from app.services.teknik_servis.kancalar import ServisHatasi

pytestmark = pytest.mark.integration


async def _aktif_kimlikler(db, so_id):
    return sorted(
        (
            await db.scalars(
                select(ServiceOrderAssignment.user_id).where(
                    ServiceOrderAssignment.service_order_id == so_id,
                    ServiceOrderAssignment.removed_at.is_(None),
                )
            )
        ).all()
    )


async def test_ekip_degisiyor_reddi_toplu_istegi_geri_alir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_e1", "SERVIS_SEF", ["GUVENLIK"])
    eski = await teknisyen(birimli_kullanici_ac, "eski_e1")
    yeni = await teknisyen(birimli_kullanici_ac, "yeni_e1")
    a = await servis_isi_ac(atananlar=[eski])
    b = await servis_isi_ac(atananlar=[eski])
    reddedilen = b.id

    async def _acik_sayac(db_, so, cikanlar):
        if so.id == reddedilen and cikanlar:
            raise ServisHatasi("Eski_E1'in sayacını bitirin")

    kancalar.kaydet("ekip_degisiyor", _acik_sayac)
    try:
        await giris(client, "sef_e1")
        r = await client.put(
            "/api/teknik-servis/isler/toplu-atama",
            json={
                "is_idler": [a.id, b.id],
                "atamalar": [{"user_id": yeni.id, "is_lead": True}],
                "mod": "DEGISTIR",
            },
        )
        assert r.status_code == 409
        assert "sayacını bitirin" in r.json()["detail"]
    finally:
        kancalar._KAYIT["ekip_degisiyor"].remove(_acik_sayac)
    # İlk iş de dahil HİÇBİR iş değişmedi.
    assert await _aktif_kimlikler(db, a.id) == [eski.id]
    assert await _aktif_kimlikler(db, b.id) == [eski.id]
    assert await olay_sayisi(db, a.id, "ATAMA") == 0


async def test_ekip_degisti_yeni_ekiple_cagrilir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_e2", "SERVIS_SEF", ["GUVENLIK"])
    t1 = await teknisyen(birimli_kullanici_ac, "tek_e2")
    t2 = await teknisyen(birimli_kullanici_ac, "tek_e3")
    so = await servis_isi_ac(atananlar=[t1])
    cagrilar = []

    async def _plan_senkron(db_, so_, yeni_ekip, clock):
        assert clock is not None  # Dalga 2: imza Clock taşır
        cagrilar.append((so_.id, sorted(a.user_id for a in yeni_ekip)))

    async def _cikanlar(db_, so_, cikan):
        cagrilar.append(("cikan", list(cikan)))

    kancalar.kaydet("ekip_degisti", _plan_senkron)
    kancalar.kaydet("ekip_degisiyor", _cikanlar)
    try:
        await giris(client, "sef_e2")
        r = await client.put(
            f"/api/teknik-servis/isler/{so.id}/atama",
            json={"atamalar": [{"user_id": t2.id, "is_lead": True}]},
        )
        assert r.status_code == 200, r.text
    finally:
        kancalar._KAYIT["ekip_degisti"].remove(_plan_senkron)
        kancalar._KAYIT["ekip_degisiyor"].remove(_cikanlar)
    assert cagrilar == [("cikan", [t1.id]), (so.id, [t2.id])]
