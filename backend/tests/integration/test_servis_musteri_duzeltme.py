"""Temel bilgi, seri ve müşteri/lokasyon gerekçeli düzeltme (TS-031; E01-13, E14-13).

Gerçek hikâye: açılışta yanlış müşteriye açılan iş sonradan "elle" taşınınca
hangi alanın kimin tarafından değiştiği bilinmiyordu. Burada her düzeltme
iyimser kilitli, DUZELTME olayına alan alan yazılır; kapalı işte yalnız
`servis.kapat` + gerekçe, PB'de müşteri/seri/tür değişmez.
"""

from datetime import UTC, date, datetime

import pytest
from servis_yardimci import giris, musteri, olay_sayisi, tazele, teknisyen
from sqlalchemy import select

from app.models import (
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceOrderEvent,
)

pytestmark = pytest.mark.integration


async def test_acik_iste_duzeltme_ve_kilit(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("op_m1", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac(iletisim_telefon="+905551112233")
    surum = so.version
    await giris(client, "op_m1")
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}",
        json={
            "version": surum,
            "konu": "Yeni konu",
            "oncelik": "KRITIK",
            "iletisim_telefon": "+905559998877",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["konu"] == "Yeni konu" and r.json()["oncelik"] == "KRITIK"
    olay = await db.scalar(
        select(ServiceOrderEvent).where(
            ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "DUZELTME"
        )
    )
    alanlar = {a["alan"]: a for a in olay.veri["alanlar"]}
    assert alanlar["konu"]["eski"] == "Test arızası" and alanlar["konu"]["yeni"] == "Yeni konu"
    assert alanlar["iletisim_telefon"] == {"alan": "iletisim_telefon"}  # değer yazılmaz
    assert "+90555" not in str(olay.veri)
    # Eski sürüm 409; birim 400; PB'ye geçiş 409.
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={"version": surum, "konu": "x"}
    )
    assert r.status_code == 409
    yeni = r = await client.get(f"/api/teknik-servis/isler/{so.id}")
    surum2 = yeni.json()["version"]
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={"version": surum2, "birim": "HABERLESME"}
    )
    assert r.status_code == 400
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={"version": surum2, "tur": "PB"}
    )
    assert r.status_code == 409
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={"version": surum2, "tur": "PLANSIZ_BAKIM"}
    )
    assert r.status_code == 200 and r.json()["kategori"] == "GUNLUK_SERVIS"


async def test_teknisyen_ve_musteri_duzeltme_yetkisi(
    client, db, birimli_kullanici_ac, servis_isi_ac, lokasyon_ac
) -> None:
    await birimli_kullanici_ac("op_m2", "SERVIS_OPERASYON", ["GUVENLIK"])  # planla yok
    await birimli_kullanici_ac("sef_m2", "SERVIS_SEF", ["GUVENLIK"])
    tek = await teknisyen(birimli_kullanici_ac, "tek_m2")
    so = await servis_isi_ac(atananlar=[tek])
    yeni_hesap = await musteri(db, "Doğru Müşteri A.Ş.")
    tesis = await lokasyon_ac(yeni_hesap, ad="Doğru Tesis")
    baska_tesis = await lokasyon_ac()
    govde = {"version": so.version, "customer_id": yeni_hesap.id, "address_id": tesis.id}

    await giris(client, "tek_m2")
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={"version": so.version, "konu": "x"}
    )
    assert r.status_code == 403
    await giris(client, "op_m2")
    r = await client.patch(f"/api/teknik-servis/isler/{so.id}", json=govde)
    assert r.status_code == 403
    await giris(client, "sef_m2")
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={**govde, "address_id": baska_tesis.id}
    )
    assert r.status_code == 400
    r = await client.patch(f"/api/teknik-servis/isler/{so.id}", json=govde)
    assert r.status_code == 200, r.text
    assert r.json()["musteri"]["id"] == yeni_hesap.id
    assert r.json()["lokasyon"]["ad"] == "Doğru Tesis"


async def test_kapali_iste_yalniz_kapat_ve_gerekce(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("atl_m3", "ATOLYE", ["GUVENLIK"])  # yaz var, kapat yok
    await birimli_kullanici_ac("sef_m3", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac(durum="KAPATILDI")
    await giris(client, "atl_m3")
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={"version": so.version, "konu": "x"}
    )
    assert r.status_code == 403
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/seriler", json={"seriler": ["A1"]})
    assert r.status_code == 403
    await giris(client, "sef_m3")
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}", json={"version": so.version, "konu": "x"}
    )
    assert r.status_code == 400
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/seriler", json={"seriler": ["A1"]})
    assert r.status_code == 400
    r = await client.patch(
        f"/api/teknik-servis/isler/{so.id}",
        json={"version": so.version, "konu": "Düzeltildi", "gerekce": "Yanlış konu"},
    )
    assert r.status_code == 200
    r = await client.put(
        f"/api/teknik-servis/isler/{so.id}/seriler",
        json={"seriler": ["A1"], "gerekce": "Sahada farklı cihaz"},
    )
    assert r.status_code == 200
    assert [s["seri_no"] for s in r.json()["seriler"]] == ["A1"]
    assert await olay_sayisi(db, so.id, "SERI") == 1
    assert await olay_sayisi(db, so.id, "DUZELTME") == 1


async def test_seri_degisikligi_eski_satiri_pasifler(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    from app.models import ServiceOrderSerial

    tek = await teknisyen(birimli_kullanici_ac, "tek_m4")
    so = await servis_isi_ac(atananlar=[tek])
    await giris(client, "tek_m4")  # teknisyen saha serisi girebilir
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/seriler", json={"seriler": ["S-1"]})
    assert r.status_code == 200
    r = await client.put(f"/api/teknik-servis/isler/{so.id}/seriler", json={"seriler": ["S-2"]})
    assert [s["seri_no"] for s in r.json()["seriler"]] == ["S-2"]
    tum = (
        await db.scalars(
            select(ServiceOrderSerial).where(ServiceOrderSerial.service_order_id == so.id)
        )
    ).all()
    assert {(s.seri_no, s.is_active) for s in tum} == {("S-1", False), ("S-2", True)}


async def test_pb_isinde_musteri_seri_tur_degismez(
    client, db, kullanici_ac, servis_isi_ac, sozlesme_ac
) -> None:
    from app.models import ServiceOrderSerial

    await kullanici_ac("mud_m5", "SERVIS_YONETICI")
    sozlesme = await sozlesme_ac()
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id,
        cycle_start=datetime(2026, 1, 1, tzinfo=UTC),
        sequence_no=1,
        target_date=date(2026, 1, 15),
    )
    db.add_all([kalem, donem])
    await db.commit()
    pb = await servis_isi_ac(
        tur="PB", durum="PLANLAMADA", contract_item_id=kalem.id, maintenance_period_id=donem.id
    )
    db.add(ServiceOrderSerial(service_order_id=pb.id, seri_no="PB-SN", seri_norm="PB-SN"))
    await db.commit()
    assert pb.so_no.startswith("PB-")
    yeni = await musteri(db, "Başka Müşteri")
    await giris(client, "mud_m5")
    for govde in ({"customer_id": yeni.id}, {"tur": "ARIZA"}):
        r = await client.patch(
            f"/api/teknik-servis/isler/{pb.id}", json={"version": pb.version, **govde}
        )
        assert r.status_code == 409, govde
    r = await client.put(f"/api/teknik-servis/isler/{pb.id}/seriler", json={"seriler": ["BASKA"]})
    assert r.status_code == 409
    pb = await tazele(db, pb)
    assert pb.tur == "PB" and pb.customer_id != yeni.id


async def test_kapsam_disi_duzeltme_404_veri_degismez(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_m6", "SERVIS_SEF", ["GUVENLIK"])
    yabanci = await servis_isi_ac(birim="HABERLESME")
    await giris(client, "sef_m6")
    r = await client.patch(
        f"/api/teknik-servis/isler/{yabanci.id}", json={"version": yabanci.version, "konu": "x"}
    )
    assert r.status_code == 404
    yabanci = await tazele(db, yabanci)
    assert yabanci.konu == "Test arızası"
