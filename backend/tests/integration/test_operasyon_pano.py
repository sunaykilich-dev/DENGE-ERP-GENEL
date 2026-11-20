"""Operasyon Merkezi panosu (2026-11-18, kullanıcı kararları).

- Tayin bekleyenler `atanmamis` süzgeciyle aynıdır; bekleme MESAİ dakikasıdır
  (gece açılan iş mesai başlayınca saymaya başlar); eşik ayardır (kritik /
  diğer); sıra: önce süresi geçenler, sonra öncelik, sonra en uzun bekleyen.
- Planlı saati geçmiş ama hâlâ PLANLANDI olan iş "plandan sapan"dır.
- Süresi geçen tayinsiz iş TAYIN_GECIKTI kalıcı bildirimini üretir (anlık
  e-posta kodu); iş kapanınca bildirim kapanır.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from servis_yardimci import giris
from sqlalchemy import select

from app.clock import FakeClock
from app.models import ServiceAlert, ServiceOrderAssignment, ServicePlan, ServiceUnavailability
from app.models.teknik_servis import EPOSTA_ANLIK_KODLAR
from app.services import settings as ayarlar
from app.services.teknik_servis import uyari_uretimi

pytestmark = pytest.mark.integration

# Çarşamba 12:00 Türkiye (09:00 UTC); mesai 08:30-18:00.
AN = datetime(2026, 1, 7, 9, 0, tzinfo=UTC)
PANO = "/api/teknik-servis/operasyon/pano"
SAYI = "/api/teknik-servis/operasyon/tayin-sayilari"


@pytest.fixture
async def veri(client, db, birimli_kullanici_ac, servis_isi_ac):
    client.clock.set(AN)
    tek = await birimli_kullanici_ac(
        "op_tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    await birimli_kullanici_ac("op_sef", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    isler = {
        # 15 mesai dk: kritik eşik 10 → gecikti.
        "kritik": await servis_isi_ac(oncelik="KRITIK", created_at=AN - timedelta(minutes=15)),
        # 20 mesai dk: diğer eşik 30 → henüz değil.
        "yeni": await servis_isi_ac(created_at=AN - timedelta(minutes=20)),
        # Salı 20:00 Türkiye: gece saymaz → 08:30'dan bu yana 210 dk → gecikti.
        "gece": await servis_isi_ac(created_at=datetime(2026, 1, 6, 17, 0, tzinfo=UTC)),
        # Tayinli iş listede yok.
        "tayinli": await servis_isi_ac(
            durum="PLANLANDI", atananlar=[tek], created_at=AN - timedelta(hours=3)
        ),
    }
    # Bugün 11:00 Türkiye planlı, hâlâ PLANLANDI → plandan sapan.
    db.add(
        ServicePlan(
            service_order_id=isler["tayinli"].id,
            plan_date=date(2026, 1, 7),
            start_time=time(11, 0),
            duration_min=60,
            change_type="ILK_PLAN",
            starts_at=AN - timedelta(hours=1),
            ends_at=AN,
        )
    )
    await db.commit()
    return isler


async def test_tayin_bekleyenler_mesai_dakikasi_esik_ve_sira(client, veri) -> None:
    await giris(client, "op_sef")
    r = await client.get(PANO)
    assert r.status_code == 200, r.text
    d = r.json()
    satir = {s["id"]: s for s in d["tayin_bekleyenler"]}
    assert veri["tayinli"].id not in satir
    assert satir[veri["kritik"].id]["bekleme_dk"] == 15
    assert satir[veri["kritik"].id]["esik_dk"] == 10 and satir[veri["kritik"].id]["gecikti"]
    assert satir[veri["yeni"].id]["bekleme_dk"] == 20 and not satir[veri["yeni"].id]["gecikti"]
    # Gece açılan iş mesai başlangıcından sayılır.
    assert satir[veri["gece"].id]["bekleme_dk"] == 210 and satir[veri["gece"].id]["gecikti"]
    # Sıra: süresi geçenler (kritik önce), sonra diğerleri.
    assert [s["id"] for s in d["tayin_bekleyenler"]] == [
        veri["kritik"].id,
        veri["gece"].id,
        veri["yeni"].id,
    ]
    assert d["ozet"]["tayin_bekleyen"] == 3 and d["ozet"]["tayin_geciken"] == 2
    assert d["esikler"] == {"kritik_dk": 10, "diger_dk": 30}

    r = await client.get(SAYI)
    assert r.json() == {"bekleyen": 3, "geciken": 2}


async def test_esik_ayari_uygulanir(client, db, veri) -> None:
    await ayarlar.set_many(db, {"servis_tayin_suresi_dk": 15}, None)
    await db.commit()
    await giris(client, "op_sef")
    satir = {s["id"]: s for s in (await client.get(PANO)).json()["tayin_bekleyenler"]}
    assert satir[veri["yeni"].id]["esik_dk"] == 15 and satir[veri["yeni"].id]["gecikti"]


async def test_plani_kayan_is_ve_ekip(client, veri) -> None:
    await giris(client, "op_sef")
    d = (await client.get(PANO)).json()
    kayan = [s for s in d["sapmalar"] if s["sapma"] == "PLAN_SAATI"]
    assert [s["id"] for s in kayan] == [veri["tayinli"].id]
    assert kayan[0]["plan_baslangic"] is not None
    assert d["sapma_toplamlari"]["PLAN_SAATI"] == 1
    # Açık sayacı olmayan teknisyen boşta.
    ekip = {k["ad"]: k for k in d["ekip"]}
    assert ekip["Op_Tek"]["durum"] == "BOSTA"


async def test_tayin_isi_verildi_sayar_ve_izinliyi_gosterir(client, db, veri) -> None:
    """Rol testi 2026-11-20: panodan tayin edilen iş TAYİN EDİLDİ olur; ekip
    boşalınca tayin bekleyene döner. İzinli kişi boşta görünmez, tayinde uyarı."""
    tek_id = await db.scalar(
        select(ServiceOrderAssignment.user_id).where(
            ServiceOrderAssignment.service_order_id == veri["tayinli"].id
        )
    )
    db.add(
        ServiceUnavailability(
            user_id=tek_id,
            tur="IZIN",
            starts_at=AN - timedelta(hours=2),
            ends_at=AN + timedelta(days=1),
        )
    )
    await db.commit()
    await giris(client, "op_sef")
    d = (await client.get(PANO)).json()
    kisi = {k["ad"]: k for k in d["ekip"]}["Op_Tek"]
    assert kisi["durum"] == "MUSAIT_DEGIL" and kisi["musait_degil"]["tur"] == "IZIN"
    assert d["ozet"]["musait_degil"] == 1  # şef boşta, teknisyen izinli

    so_id = veri["yeni"].id
    r = await client.put(
        "/api/teknik-servis/isler/toplu-atama",
        json={
            "is_idler": [so_id],
            "atamalar": [{"user_id": tek_id, "rol": "TEKNISYEN", "is_lead": True}],
            "mod": "EKLE",
        },
    )
    assert r.status_code == 200, r.text
    assert any("izinli" in u for u in r.json()["uyarilar"])
    assert (await client.get(f"/api/teknik-servis/isler/{so_id}")).json()["status"] == "PLANLANDI"
    assert so_id not in {s["id"] for s in (await client.get(PANO)).json()["tayin_bekleyenler"]}

    # Ekip boşalınca (aktif plan yok) iş yeniden tayin bekler.
    r = await client.put(f"/api/teknik-servis/isler/{so_id}/atama", json={"atamalar": []})
    assert r.status_code == 200, r.text
    assert (await client.get(f"/api/teknik-servis/isler/{so_id}")).json()["status"] == "PLANLAMADA"


async def test_tayin_gecikti_bildirimi_ve_kapanisi(db, veri) -> None:
    assert "TAYIN_GECIKTI" in EPOSTA_ANLIK_KODLAR
    await uyari_uretimi.uret(db, FakeClock(AN))
    await db.commit()
    acik = set(
        (
            await db.scalars(
                select(ServiceAlert.service_order_id).where(
                    ServiceAlert.kod == "TAYIN_GECIKTI", ServiceAlert.kapanis_at.is_(None)
                )
            )
        ).all()
    )
    assert acik == {veri["kritik"].id, veri["gece"].id}

    # Kritik iş tayin edilince koşul kalkar, bildirim kapanır.
    tek_id = await db.scalar(
        select(ServiceOrderAssignment.user_id).where(
            ServiceOrderAssignment.service_order_id == veri["tayinli"].id
        )
    )
    db.add(
        ServiceOrderAssignment(
            service_order_id=veri["kritik"].id,
            user_id=tek_id,
            rol="TEKNISYEN",
            is_lead=True,
            assigned_at=AN,
        )
    )
    await db.commit()
    await uyari_uretimi.uret(db, FakeClock(AN + timedelta(minutes=5)))
    await db.commit()
    kayit = await db.scalar(
        select(ServiceAlert).where(
            ServiceAlert.kod == "TAYIN_GECIKTI",
            ServiceAlert.service_order_id == veri["kritik"].id,
        )
    )
    assert kayit.kapanis_at is not None and kayit.kapanis_nedeni == "KOSUL_KALKTI"


async def test_yetkisiz_goremez(client, kullanici_ac, veri) -> None:
    await kullanici_ac("op_depo", "DEPO")
    await giris(client, "op_depo")
    assert (await client.get(PANO)).status_code == 403
    assert (await client.get(SAYI)).status_code == 403
