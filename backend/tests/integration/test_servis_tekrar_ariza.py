"""Tekrar arıza işareti ve kök neden teyidi (TS-084, E10-04).

Kural: yeni işin serilerinden biri son 30 günde KAPATILMIŞ başka bir işte
geçiyorsa iş "tekrar arıza adayı" olur ve (bağı yoksa) o işe TEKRAR_ARIZA
olarak bağlanır. Eşleşme `seri_norm` ile (tire ve baştaki sıfır korunur); PB ne
tetikler ne tetiklenir; elle kurulan bağın üzerine yazılmaz; kapsam dışı bağ
maskelenir. Aday iş teyit + kök neden olmadan KAPATILAMAZ.
"""

from datetime import UTC, datetime, timedelta

import pytest
from servis_yardimci import acilis, giris, musteri
from sqlalchemy import select

from app.clock import FakeClock
from app.models import (
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceFaultReason,
    ServiceOrder,
    ServiceOrderEvent,
    ServiceOrderSerial,
)
from app.services.teknik_servis import tekrar_ariza

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)
TS = "/api/teknik-servis"


async def _ac(client, hesap_id: int, seriler: list[str], **kw) -> dict:
    r = await client.post(
        f"{TS}/isler", json=acilis(hesap_id, seriler=seriler, mukerrer_gec=True, **kw)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _tamamla(client, so_id: int, ariza_nedeni_id: int | None = None) -> None:
    govde = {"sonuc": "COZULDU", "cozum_kanali": "TELEFON", "yapilan_islem": "Çözüldü"}
    if ariza_nedeni_id is not None:
        govde["ariza_nedeni_id"] = ariza_nedeni_id
    r = await client.post(f"{TS}/isler/{so_id}/sonuc", json=govde)
    assert r.status_code == 200, r.text


async def _kapat(client, so_id: int):
    return await client.post(f"{TS}/isler/{so_id}/kapat", json={})


async def _kayit(db, so_id: int) -> ServiceOrder:
    db.expire_all()
    return await db.get(ServiceOrder, so_id)


@pytest.fixture
async def ortam(client, db, kullanici_ac):
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    await giris(client, "mudur")
    hesap = await musteri(db)
    neden = await db.scalar(
        select(ServiceFaultReason.id).where(ServiceFaultReason.birim == "GUVENLIK").limit(1)
    )
    return hesap.id, neden


async def test_eslesme_kurallari(client, db, ortam) -> None:
    """Kabul: 20 gün önce kapanan aynı seri → bağ; 45 gün → yok; '0AB001' ≠ 'AB-001';
    iki serili işte yalnız ikinci seri eşleşse de işaret; elle kurulan bağ korunur."""
    hesap, _ = ortam
    a = await _ac(client, hesap, ["AB-001"])
    g = await _ac(client, hesap, ["XY-9"])
    for so in (a, g):
        await _tamamla(client, so["id"])
        assert (await _kapat(client, so["id"])).status_code == 200

    client.clock.advance(days=20)
    await giris(client, "mudur")
    b = await _ac(client, hesap, ["ab-001 "])
    kb = await _kayit(db, b["id"])
    assert kb.tekrar_ariza_aday is True
    assert (kb.iliskili_is_id, kb.iliski_turu) == (a["id"], "TEKRAR_ARIZA")
    c = await _ac(client, hesap, ["0AB001"])
    assert (await _kayit(db, c["id"])).tekrar_ariza_aday is False
    h = await _ac(client, hesap, ["ZZ-1", "AB-001"])
    assert (await _kayit(db, h["id"])).tekrar_ariza_aday is True
    d = await _ac(
        client, hesap, ["AB-001"], iliskili_is_id=c["id"], iliski_turu="MUKERRER"
    )
    kd = await _kayit(db, d["id"])
    assert kd.tekrar_ariza_aday is True
    assert (kd.iliskili_is_id, kd.iliski_turu) == (c["id"], "MUKERRER")  # üzerine yazılmadı

    client.clock.advance(days=25)  # A ve G 45 gün önce kapandı
    await giris(client, "mudur")
    x = await _ac(client, hesap, ["XY-9"])
    assert (await _kayit(db, x["id"])).tekrar_ariza_aday is False


async def test_pb_ne_tetikler_ne_tetiklenir(client, db, ortam, servis_isi_ac, sozlesme_ac) -> None:
    hesap, _ = ortam
    sozlesme = await sozlesme_ac()
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=AN, sequence_no=1, target_date=AN.date()
    )
    db.add_all([kalem, donem])
    await db.commit()
    sozlesme_id, kalem_id = sozlesme.id, kalem.id
    pb = await servis_isi_ac(
        tur="PB",
        durum="KAPATILDI",
        closed_at=AN - timedelta(days=2),
        contract_item_id=kalem.id,
        maintenance_period_id=donem.id,
    )
    db.add(ServiceOrderSerial(service_order_id=pb.id, seri_no="PB-77", seri_norm="PB-77"))
    await db.commit()
    yeni = await _ac(client, hesap, ["PB-77"])
    assert (await _kayit(db, yeni["id"])).tekrar_ariza_aday is False

    # PB işinin kendisi de işaretlenmez (kanca PB'yi atlar).
    ariza = await _ac(client, hesap, ["PB-88"])
    await _tamamla(client, ariza["id"])
    assert (await _kapat(client, ariza["id"])).status_code == 200
    pb2_donem = MaintenancePeriod(
        contract_id=sozlesme_id, cycle_start=AN, sequence_no=2, target_date=AN.date()
    )
    db.add(pb2_donem)
    await db.commit()
    pb2 = await servis_isi_ac(
        tur="PB", contract_item_id=kalem_id, maintenance_period_id=pb2_donem.id
    )
    db.add(ServiceOrderSerial(service_order_id=pb2.id, seri_no="PB-88", seri_norm="PB-88"))
    await db.commit()
    await tekrar_ariza.isaretle(db, pb2, FakeClock(AN + timedelta(days=1)))
    await db.commit()
    assert (await _kayit(db, pb2.id)).tekrar_ariza_aday is False


async def test_kapsam_disi_bag_maskelenir(
    client, db, ortam, birimli_kullanici_ac, servis_isi_ac
) -> None:
    """Kabul (6): başka birimdeki eşleşen işe bağ kurulur ama numara ne detayda ne olay
    geçmişinde görünür."""
    hesap, _ = ortam
    eski = await servis_isi_ac(
        birim="HABERLESME", durum="KAPATILDI", closed_at=AN - timedelta(days=3)
    )
    eski_id, eski_no = eski.id, eski.so_no
    db.add(ServiceOrderSerial(service_order_id=eski_id, seri_no="HB-1", seri_norm="HB-1"))
    await db.commit()
    await birimli_kullanici_ac("sef_a", "SERVIS_SEF", ["GUVENLIK"])
    await giris(client, "sef_a")
    yeni = await _ac(client, hesap, ["HB-1"])
    k = await _kayit(db, yeni["id"])
    assert k.tekrar_ariza_aday and k.iliskili_is_id == eski_id
    detay = (await client.get(f"{TS}/isler/{yeni['id']}")).json()
    ust = detay["iliskili_isler"]["ust"]
    assert ust["kapsam_disi"] is True and ust["id"] is None and ust["so_no"] == "Kapsam dışı iş"
    kart = (await client.get(f"{TS}/operasyon/isler/{yeni['id']}/sla")).json()
    assert kart["tekrar_ariza"]["bagli_is"]["so_no"] == "Kapsam dışı iş"
    ozetler = (
        await db.scalars(
            select(ServiceOrderEvent.ozet).where(ServiceOrderEvent.service_order_id == yeni["id"])
        )
    ).all()
    assert all(eski_no not in o for o in ozetler)


async def test_kapanista_teyit_ve_kok_neden_zorunlu(client, db, ortam) -> None:
    """Kabul (5): aday iş TAMAMLANDI 200; teyitsiz KAPATILDI 409, kök nedensiz 409."""
    hesap, neden = ortam
    a = await _ac(client, hesap, ["KK-1"])
    await _tamamla(client, a["id"])
    assert (await _kapat(client, a["id"])).status_code == 200
    client.clock.advance(days=5)
    await giris(client, "mudur")
    b = await _ac(client, hesap, ["KK-1"])
    e = await _ac(client, hesap, ["KK-1"])
    await _tamamla(client, b["id"])
    await _tamamla(client, e["id"], ariza_nedeni_id=neden)

    r = await _kapat(client, b["id"])
    assert r.status_code == 409 and "teyidi" in r.json()["detail"]
    yol = f"{TS}/operasyon/isler/{b['id']}/kapanis-bilgisi"
    assert (await client.put(yol, json={"tekrar_ariza_teyit": "AYNI_ARIZA"})).status_code == 200
    r = await _kapat(client, b["id"])
    assert r.status_code == 409 and "kök neden" in r.json()["detail"]
    assert (await _kayit(db, b["id"])).status == "TAMAMLANDI"

    assert (await _kapat(client, e["id"])).status_code == 409
    yol = f"{TS}/operasyon/isler/{e['id']}/kapanis-bilgisi"
    assert (await client.put(yol, json={"tekrar_ariza_teyit": "FARKLI_ARIZA"})).status_code == 200
    assert (await _kapat(client, e["id"])).status_code == 200
    assert (await _kayit(db, e["id"])).tekrar_ariza_teyit == "FARKLI_ARIZA"
