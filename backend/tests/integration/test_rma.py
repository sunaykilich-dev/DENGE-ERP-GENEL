"""RMA: garanti kararı, durum akışı, değişim devri, arıza oranı."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Account, DeviceVehicleAssignment, RmaCase, SimDeviceHistory, Vehicle

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username="teknik", rol="TEKNIK_SERVIS"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


@pytest.fixture
async def arac_ac(db):
    async def _make(plaka: str, musteri_id: int | None = None) -> Vehicle:
        a = Vehicle(plate=plaka, plate_key=plaka.lower(), customer_id=musteri_id)
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a

    return _make


class TestGarantiKarari:
    async def test_aktivasyondan_itibaren_garanti_ici(
        self, client, kullanici_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI", warranty_months=24)
        await cihaz_ac(
            imei="860000000000001",
            urun=u,
            status="AKTIF",
            first_activation_date=date(2025, 6, 1),
        )
        r = await client.post(
            "/api/rma",
            json={
                "kimlik": "860000000000001",
                "fault_description": "Sinyal yok",
                "received_at": "2026-01-15",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["warranty_status"] == "GARANTI_ICI"
        assert r.json()["warranty_end_date"] == "2027-06-01"

    async def test_suresi_gecmis_garanti_disi(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI", warranty_months=12)
        await cihaz_ac(
            imei="860000000000002",
            urun=u,
            status="AKTIF",
            first_activation_date=date(2023, 1, 1),
        )
        r = await client.post(
            "/api/rma",
            json={
                "kimlik": "860000000000002",
                "fault_description": "Su aldı",
                "received_at": "2026-01-15",
            },
        )
        assert r.json()["warranty_status"] == "GARANTI_DISI"

    async def test_aktivasyon_tarihi_yoksa_belirsiz(self, client, kullanici_ac, urun_ac, cihaz_ac):
        """Göçten gelen cihazların bir kısmında aktivasyon tarihi yok."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000003", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma",
            json={"kimlik": "860000000000003", "fault_description": "Arıza"},
        )
        assert r.json()["warranty_status"] == "BELIRSIZ"
        assert r.json()["warranty_end_date"] is None

    async def test_karar_dondurulur(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        """Garanti tarihi sonradan düzeltilse de açılmış kaydın kararı değişmez."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI", warranty_months=12)
        c = await cihaz_ac(
            imei="860000000000004",
            urun=u,
            status="AKTIF",
            first_activation_date=date(2023, 1, 1),
        )
        r = await client.post(
            "/api/rma",
            json={
                "kimlik": "860000000000004",
                "fault_description": "Arıza",
                "received_at": "2026-01-15",
            },
        )
        rma_id = r.json()["id"]
        assert r.json()["warranty_status"] == "GARANTI_DISI"

        # API başka oturumdan cihazı güncelledi; iyimser kilitleme için tazele.
        await db.refresh(c)
        c.warranty_end_date = date(2030, 1, 1)
        await db.commit()

        tekrar = await client.get(f"/api/rma/{rma_id}")
        assert tekrar.json()["warranty_status"] == "GARANTI_DISI"


class TestAkis:
    async def test_acilis_cihazi_arizaliya_ceker(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000010", urun=u, status="AKTIF")
        await client.post(
            "/api/rma", json={"kimlik": "860000000000010", "fault_description": "Arıza"}
        )
        await db.refresh(c)
        assert c.status == "ARIZALI"

    async def test_ayni_cihaza_ikinci_acik_kayit_acilmaz(
        self, client, kullanici_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000011", urun=u, status="AKTIF")
        veri = {"kimlik": "860000000000011", "fault_description": "Arıza"}
        assert (await client.post("/api/rma", json=veri)).status_code == 201
        ikinci = await client.post("/api/rma", json=veri)
        assert ikinci.status_code == 409
        assert "açık servis kaydı" in ikinci.json()["detail"]

    async def test_durum_zinciri_cihazi_izler(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000012", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000012", "fault_description": "Arıza"}
        )
        rma_id = r.json()["id"]

        await client.post(f"/api/rma/{rma_id}/durum", json={"durum": "INCELEMEDE"})
        await db.refresh(c)
        assert c.status == "RMA"

        await client.post(f"/api/rma/{rma_id}/durum", json={"durum": "TAMIRDE"})
        await db.refresh(c)
        assert c.status == "TAMIRDE"

    async def test_gecersiz_gecis_reddedilir(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000013", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000013", "fault_description": "Arıza"}
        )
        rma_id = r.json()["id"]
        # ACIK'tan doğrudan KAPANDI'ya geçilemez.
        assert (
            await client.post(f"/api/rma/{rma_id}/durum", json={"durum": "KAPANDI"})
        ).status_code == 409

    async def test_cozumsuz_kayit_kapanmaz(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000014", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000014", "fault_description": "Arıza"}
        )
        rma_id = r.json()["id"]
        await client.post(f"/api/rma/{rma_id}/durum", json={"durum": "INCELEMEDE"})
        assert (
            await client.post(f"/api/rma/{rma_id}/durum", json={"durum": "COZULDU"})
        ).status_code == 409


class TestCozum:
    async def test_tamir_cihazi_yeniden_stoga_alir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000020", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000020", "fault_description": "Arıza"}
        )
        rma_id = r.json()["id"]
        c_ = await client.post(
            f"/api/rma/{rma_id}/coz",
            json={"resolution": "TAMIR", "resolution_note": "Kart değişti"},
        )
        assert c_.status_code == 200, c_.text
        assert c_.json()["status"] == "COZULDU"
        await db.refresh(c)
        assert c.status == "YENIDEN_STOKTA"

    async def test_garanti_ici_kayda_ucret_yazilamaz(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI", warranty_months=24)
        await cihaz_ac(
            imei="860000000000021",
            urun=u,
            status="AKTIF",
            first_activation_date=date(2025, 6, 1),
        )
        r = await client.post(
            "/api/rma",
            json={
                "kimlik": "860000000000021",
                "fault_description": "Arıza",
                "received_at": "2026-01-15",
            },
        )
        rma_id = r.json()["id"]
        cevap = await client.post(
            f"/api/rma/{rma_id}/coz", json={"resolution": "TAMIR", "cost": 500}
        )
        assert cevap.status_code == 409
        assert "Garanti içi" in cevap.json()["detail"]

    async def test_garanti_disi_ucret_yazilir(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI", warranty_months=12)
        await cihaz_ac(
            imei="860000000000022",
            urun=u,
            status="AKTIF",
            first_activation_date=date(2023, 1, 1),
        )
        r = await client.post(
            "/api/rma",
            json={
                "kimlik": "860000000000022",
                "fault_description": "Arıza",
                "received_at": "2026-01-15",
            },
        )
        cevap = await client.post(
            f"/api/rma/{r.json()['id']}/coz", json={"resolution": "TAMIR", "cost": 750}
        )
        assert cevap.status_code == 200, cevap.text
        assert Decimal(cevap.json()["cost"]) == Decimal("750.00")

    async def test_degisim_cihazsiz_reddedilir(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000023", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000023", "fault_description": "Arıza"}
        )
        cevap = await client.post(f"/api/rma/{r.json()['id']}/coz", json={"resolution": "DEGISIM"})
        assert cevap.status_code == 409

    async def test_degisim_devri(
        self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, arac_ac, db
    ):
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        musteri = Account(title="ACME LTD", title_key="acme ltd", is_musteri=True)
        db.add(musteri)
        await db.commit()
        await db.refresh(musteri)

        u = await urun_ac("L300", "IMEI")
        eski = await cihaz_ac(imei="860000000000040", urun=u)
        yeni = await cihaz_ac(imei="860000000000041", urun=u)
        hat = await hat_ac("8990011234567890002")
        arac = await arac_ac("34ABC124", musteri.id)

        # Kurulum servisten: eski cihaz araçta ve hattı takılı.
        from app.services import assignments as atama_svc
        from app.services.devices import hat_tak

        await hat_tak(db, device_id=eski.id, sim_id=hat.id, clock=client.clock)
        await atama_svc.tak(
            db,
            device_id=eski.id,
            vehicle_id=arac.id,
            clock=client.clock,
            customer_id=musteri.id,
        )
        await db.commit()

        # Kurulumdan sonra zaman ilerler; aynı ANDA hem takıp hem sökmek
        # sıfır uzunlukta dönem demekti.
        client.clock.advance(hours=2)
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000040", "fault_description": "Bozuldu"}
        )
        assert r.status_code == 201, r.text
        rma_id = r.json()["id"]
        cevap = await client.post(
            f"/api/rma/{rma_id}/coz",
            json={"resolution": "DEGISIM", "replacement_kimlik": "860000000000041"},
        )
        assert cevap.status_code == 200, cevap.text
        assert cevap.json()["replacement_kimlik"] == "860000000000041"

        # Araç yeni cihaza geçti, eskinin dönemi kapandı.
        donemler = (
            await db.scalars(
                select(DeviceVehicleAssignment)
                .where(DeviceVehicleAssignment.vehicle_id == arac.id)
                .order_by(DeviceVehicleAssignment.id)
            )
        ).all()
        assert [d.device_id for d in donemler] == [eski.id, yeni.id]
        assert donemler[0].valid_to is not None
        assert donemler[1].valid_to is None
        assert donemler[1].customer_id == musteri.id

        # Hat da yeni cihaza taşındı.
        hat_donemleri = (
            await db.scalars(
                select(SimDeviceHistory)
                .where(SimDeviceHistory.sim_id == hat.id)
                .order_by(SimDeviceHistory.id)
            )
        ).all()
        assert hat_donemleri[-1].device_id == yeni.id
        assert hat_donemleri[-1].valid_to is None

        # Eski cihaz hurdaya ayrıldı.
        await db.refresh(eski)
        assert eski.status == "HURDA"


class TestArizaOrani:
    async def test_payda_toplam_cihaz(self, client, kullanici_ac, urun_ac, cihaz_ac):
        """Yalnız arıza sayısı listelemek çok satan modeli kötü gösterirdi."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        for i in range(4):
            await cihaz_ac(imei=f"86000000000050{i}", urun=u, status="AKTIF")
        await client.post(
            "/api/rma", json={"kimlik": "860000000000500", "fault_description": "Arıza"}
        )

        r = await client.get("/api/rma/ariza-orani")
        assert r.status_code == 200, r.text
        satir = next(x for x in r.json() if x["urun_kodu"] == "L300")
        assert satir["cihaz_sayisi"] == 4
        assert satir["rma_sayisi"] == 1
        assert satir["ariza_orani"] == 25.0


class TestTedarikciTakibi:
    async def test_tedarikci_bilgisi_yazilir(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        await _giris(client, kullanici_ac)
        tedarikci = Account(title="ARMOLI", title_key="armoli", is_tedarikci=True)
        db.add(tedarikci)
        await db.commit()
        await db.refresh(tedarikci)

        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000060", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000060", "fault_description": "Arıza"}
        )
        kayit = r.json()

        p = await client.patch(
            f"/api/rma/{kayit['id']}/tedarikci",
            json={
                "supplier_id": tedarikci.id,
                "supplier_rma_no": "ARM-2026-77",
                "sent_to_supplier_at": "2026-02-01",
                "version": kayit["version"],
            },
        )
        assert p.status_code == 200, p.text
        assert p.json()["supplier_rma_no"] == "ARM-2026-77"


class TestYetki:
    async def test_satis_rma_acamaz(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000001", "fault_description": "x"}
        )
        assert r.status_code == 403

    async def test_satis_rma_gorebilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        assert (await client.get("/api/rma")).status_code == 200


class TestSaat:
    async def test_kapanis_zamani_saatten_gelir(self, client, kullanici_ac, urun_ac, cihaz_ac):
        client.clock.set(datetime(2026, 5, 10, 9, 30, tzinfo=UTC))
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000070", urun=u, status="AKTIF")
        r = await client.post(
            "/api/rma", json={"kimlik": "860000000000070", "fault_description": "Arıza"}
        )
        rma_id = r.json()["id"]
        await client.post(f"/api/rma/{rma_id}/coz", json={"resolution": "TAMIR"})
        k = await client.post(f"/api/rma/{rma_id}/durum", json={"durum": "KAPANDI"})
        assert k.json()["closed_at"].startswith("2026-05-10")

        kayit = await client.get(f"/api/rma/{rma_id}")
        assert kayit.json()["status"] == "KAPANDI"
        assert kayit.json()["sonraki_durumlar"] == []


class TestNumara:
    async def test_rma_numarasi_tekil(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        for i in range(3):
            await cihaz_ac(imei=f"86000000000080{i}", urun=u, status="AKTIF")
            await client.post(
                "/api/rma",
                json={"kimlik": f"86000000000080{i}", "fault_description": "Arıza"},
            )
        nolar = [k.rma_no for k in (await db.scalars(select(RmaCase))).all()]
        assert len(nolar) == len(set(nolar)) == 3
