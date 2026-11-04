"""Kalıcı SLA bildirimi ve zil rozeti (TS-083, E10-05/11/18).

Rozet ANLIK hesaplanır (worker turunu beklemez); `service_alerts` yalnız
görüldü/tekillik içindir ve kapsam okuma anında `service_orders` JOIN'iyle
uygulanır. Worker turu idempotenttir; koşul kalkınca kayıt kapanır.
"""

from datetime import UTC, datetime, timedelta

import pytest
from servis_yardimci import giris
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import ServiceAlert, ServiceAlertRead, ServiceOrder
from app.services import settings as ayarlar
from app.services.teknik_servis import uyari_uretimi

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)
TS = "/api/teknik-servis"


def _sla(bas_saat_once: float, sure_saat: int = 12, kaynak: str = "CANLI") -> dict:
    bas = AN - timedelta(hours=bas_saat_once)
    hedef = bas + timedelta(hours=sure_saat)
    return {
        "sla_baslangic_at": bas,
        "cozum_hedef_at": hedef,
        "cozum_hedef_ilk_at": hedef,
        "sla_kaynak": kaynak,
    }


@pytest.fixture
async def veri(client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac):
    tek = await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    await birimli_kullanici_ac("sef_a", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_b", "SERVIS_SEF", ["HABERLESME"])
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    await kullanici_ac("satis", "DEPO")  # servis.gor yok (SATIS §7.8 ile görür)
    return {
        "g1": await servis_isi_ac(durum="ISLEMDE", atananlar=[tek], **_sla(13)),
        "g2": await servis_isi_ac(durum="PLANLAMADA", **_sla(14)),
        "g_risk": await servis_isi_ac(durum="PLANLAMADA", **_sla(11)),
        "h1": await servis_isi_ac(birim="HABERLESME", durum="SAHADA", **_sla(20)),
        # Göç geri doldurması: bildirim üretmez.
        "geriye": await servis_isi_ac(durum="ISLEMDE", **_sla(30, kaynak="GERIYE_DONUK")),
    }


async def _acik(db, kod: str | None = None) -> dict[int, int]:
    stmt = select(ServiceAlert.service_order_id, ServiceAlert.id).where(
        ServiceAlert.kapanis_at.is_(None)
    )
    if kod:
        stmt = stmt.where(ServiceAlert.kod == kod)
    return dict((await db.execute(stmt)).all())


async def _uret(db, an: datetime = AN) -> int:
    acilan = await uyari_uretimi.uret(db, FakeClock(an))
    await db.commit()
    return acilan


async def test_uretim_idempotent_ve_kapanis(db, veri) -> None:
    """Kabul (1): iki tur aynı kayıt sayısı; koşul kalkınca kapanır; yeniden oluşunca yeni kayıt."""
    assert await _uret(db) == 4  # g1, g2, h1 ASILDI + g_risk RISK (geriye yok)
    assert set(await _acik(db, "SLA_ASILDI")) == {veri["g1"].id, veri["g2"].id, veri["h1"].id}
    assert set(await _acik(db, "SLA_RISK")) == {veri["g_risk"].id}
    assert await _uret(db) == 0
    assert len(await _acik(db)) == 4

    # 2 saat sonra riskteki iş aşıldı: RISK kapanır (KOSUL_KALKTI), ASILDI açılır.
    assert await _uret(db, AN + timedelta(hours=2)) == 1
    risk = await db.scalar(select(ServiceAlert).where(ServiceAlert.kod == "SLA_RISK"))
    assert risk.kapanis_at == AN + timedelta(hours=2) and risk.kapanis_nedeni == "KOSUL_KALKTI"

    # İş kapanınca bildirim IS_KAPANDI ile kapanır.
    so = await db.get(ServiceOrder, veri["g2"].id)
    so.status, so.sla_sonuc = "TAMAMLANDI", "ASILDI"
    await db.commit()
    await _uret(db, AN + timedelta(hours=3))
    kayit = await db.scalar(
        select(ServiceAlert).where(ServiceAlert.service_order_id == veri["g2"].id)
    )
    assert kayit.kapanis_nedeni == "IS_KAPANDI"
    # Yeniden açılan (sonuç donmuş) işte yeni ASILDI bildirimi açılmaz.
    so.status = "TEKRAR_ACILDI"
    await db.commit()
    await _uret(db, AN + timedelta(hours=4))
    assert veri["g2"].id not in await _acik(db)
    assert uyari_uretimi.son_ozet["tutarsiz_bekleme"] == 0


async def test_uretim_kapaliyken_yazmaz(db, veri) -> None:
    await ayarlar.set_many(db, {"servis_uyari_uretimi_acik": False}, None)
    await db.commit()
    assert await _uret(db) == 0
    assert await db.scalar(select(func.count()).select_from(ServiceAlert)) == 0
    assert "kapalı" in await uyari_uretimi.uretim_gorevi(db, FakeClock(AN))


async def test_rozet_anlik_ve_kapsamli(client, db, veri) -> None:
    """Kabul (2)(3)(4) + E10-18: zil worker turu olmadan doğru sayar; birim/iş kapsamlı;
    `servis.gor` yoksa satır yok."""

    async def zil(kullanici: str) -> dict[str, int]:
        await giris(client, kullanici)
        r = await client.get("/api/raporlar/uyarilar")
        assert r.status_code == 200, r.text
        return {u["kod"]: u["adet"] for u in r.json()["uyarilar"] if u["kod"].startswith("sla.")}

    assert await zil("sef_a") == {"sla.sla_asildi": 2, "sla.sla_riskte": 1}
    assert await zil("sef_b") == {"sla.sla_asildi": 1}
    assert await zil("tek") == {"sla.sla_asildi": 1}
    assert await zil("satis") == {}
    # Panel "geciken" = Operasyon sla_asildi = zil = açık SLA_ASILDI bildirimi (tur sonrası).
    await _uret(db)
    await giris(client, "mudur")
    ozet = {
        s["kod"]: s["deger"] for s in (await client.get(f"{TS}/operasyon/ozet")).json()["sayaclar"]
    }  # noqa: E501
    assert ozet["sla_asildi"] == len(await _acik(db, "SLA_ASILDI")) == 3
    assert (await zil("mudur"))["sla.sla_asildi"] == 3


async def test_bildirim_listesi_ve_goruldu(client, db, veri) -> None:
    """Kabul (2)(3)(5): liste kapsamlı; görüldü tek satır, ikinci istek değiştirmez;
    kapsam dışı bildirim 404 ve hiçbir satır yazılmaz."""
    await _uret(db)
    await giris(client, "sef_b")
    r = await client.get(f"{TS}/operasyon/bildirimler")
    assert r.status_code == 200 and int(r.headers["X-Toplam-Kayit"]) == 1
    h_id = r.json()[0]["id"]
    g_alert = (await _acik(db, "SLA_ASILDI"))[veri["g1"].id]
    r = await client.post(
        f"{TS}/operasyon/bildirimler/goruldu", json={"bildirim_idler": [h_id, g_alert]}
    )  # noqa: E501
    assert r.status_code == 404
    assert await db.scalar(select(func.count()).select_from(ServiceAlertRead)) == 0
    r = await client.post(f"{TS}/operasyon/bildirimler/goruldu", json={"bildirim_idler": [h_id]})
    assert r.json() == {"isaretlenen": 1, "zaten_goruldu": 0}
    r = await client.post(f"{TS}/operasyon/bildirimler/goruldu", json={"bildirim_idler": [h_id]})
    assert r.json() == {"isaretlenen": 0, "zaten_goruldu": 1}
    assert await db.scalar(select(func.count()).select_from(ServiceAlertRead)) == 1
    r = await client.get(f"{TS}/operasyon/bildirimler", params={"goruldu": "false"})
    assert r.json() == []

    await giris(client, "tek")  # KENDI_ISLERI: yalnız kendi işinin bildirimi
    satirlar = (await client.get(f"{TS}/operasyon/bildirimler")).json()
    assert {s["service_order_id"] for s in satirlar} == {veri["g1"].id}
    await giris(client, "satis")
    assert (await client.get(f"{TS}/operasyon/bildirimler")).status_code == 403
    r = await client.post(f"{TS}/operasyon/bildirimler/goruldu", json={"bildirim_idler": [h_id]})
    assert r.status_code == 403


async def test_temizlik_yalniz_eski_kapali(db, veri) -> None:
    """Kabul (6): saklama süresinden eski KAPALI bildirim silinir; açık olan silinmez."""
    db.add_all(
        [
            ServiceAlert(
                kod="SLA_RISK",
                service_order_id=veri["g1"].id,
                onem="UYARI",
                baslik="eski",
                acilis_at=AN - timedelta(days=200),
                kapanis_at=AN - timedelta(days=100),
                kapanis_nedeni="KOSUL_KALKTI",
            ),
            ServiceAlert(
                kod="SLA_RISK",
                service_order_id=veri["g2"].id,
                onem="UYARI",
                baslik="yakın",
                acilis_at=AN - timedelta(days=20),
                kapanis_at=AN - timedelta(days=10),
                kapanis_nedeni="KOSUL_KALKTI",
            ),
            ServiceAlert(
                kod="SLA_ASILDI",
                service_order_id=veri["h1"].id,
                onem="KRITIK",
                baslik="açık eski",
                acilis_at=AN - timedelta(days=300),
            ),
        ]
    )
    await db.commit()
    assert await uyari_uretimi.temizle(db, FakeClock(AN)) == 1
    await db.commit()
    kalan = set((await db.scalars(select(ServiceAlert.baslik))).all())
    assert kalan == {"yakın", "açık eski"}
