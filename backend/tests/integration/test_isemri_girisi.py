"""Montaj / söküm girişi — ziyaret, araç, cihaz ve dönem tek işlemde.

Canlı uygulamada bir kayıt = bir cihazdı; ERP'de iş emri = bir ziyaret ve
içinde n kalem var. Bu testler o dönüşümün kaybettirmediğini çiviliyor:
araç açılıyor, cihaz durumu yürüyor, dönem açılıyor, ödenebilirlik kararı
kalem başına kalıyor.
"""

from datetime import date

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, ad="koord", rol="MONTAJ_KOORD"):
    await kullanici_ac(ad, rol)
    r = await client.post("/api/auth/login", json={"username": ad, "password": "parola1234"})
    assert r.status_code == 200, r.text


@pytest.fixture
async def nokta(db):
    from app.models import Account

    h = Account(
        title="DENEME MONTAJ NOKTASI",
        title_key="deneme montaj noktasi",
        is_montaj_noktasi=True,
    )
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


class TestIsEmriGirisi:
    async def test_montaj_arac_cihaz_ve_donem_acar(self, client, db, kullanici_ac, urun_ac, nokta):
        from app.models import Device, DeviceVehicleAssignment, Vehicle

        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac)

        r = await client.post(
            "/api/is-emirleri",
            json={
                "type": "MONTAJ",
                "completed_at": "2026-07-15",
                "assigned_id": nokta.id,
                "plaka": "34ABC123",
                "odometer_km": 145000,
                "travel_km": 12,
                "travel_unit_price": 10,
                "kalemler": [
                    {
                        "kimlik": "860000000000200",
                        "product_id": u.id,
                        "device_role": "BIRINCIL_TAKIP",
                        "payability": "ODENECEK",
                        "unit_price": 450,
                    }
                ],
            },
        )
        assert r.status_code == 201, r.text
        wo = r.json()
        assert wo["settlement_period"] == "2026-07"
        # 450 kalem + 12 km × 10 TL yol
        assert wo["toplam_tutar"] == 570

        arac = await db.scalar(select(Vehicle).where(Vehicle.plate == "34ABC123"))
        assert arac is not None

        cihaz = await db.scalar(select(Device).where(Device.imei == "860000000000200"))
        assert cihaz.status == "AKTIF"
        # Aktivasyon İŞİN tarihinden: garanti başlangıcı kaydın girildiği güne
        # kayarsa garanti süresi yanlış hesaplanır.
        assert cihaz.first_activation_date == date(2026, 7, 15)

        donem = await db.scalar(
            select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.device_id == cihaz.id)
        )
        assert donem.vehicle_id == arac.id
        assert donem.valid_to is None

    async def test_ikinci_montaj_onceki_donemi_kapatir(
        self, client, db, kullanici_ac, urun_ac, nokta
    ):
        from app.models import DeviceVehicleAssignment

        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac)
        ortak = {
            "type": "MONTAJ",
            "assigned_id": nokta.id,
            "kalemler": [{"kimlik": "860000000000218", "product_id": u.id}],
        }
        for tarih, plaka in (("2026-03-01", "34AAA111"), ("2026-06-01", "34BBB222")):
            r = await client.post(
                "/api/is-emirleri", json={**ortak, "completed_at": tarih, "plaka": plaka}
            )
            assert r.status_code == 201, r.text

        donemler = (
            await db.scalars(
                select(DeviceVehicleAssignment).order_by(DeviceVehicleAssignment.valid_from)
            )
        ).all()
        assert len(donemler) == 2
        assert donemler[0].valid_to is not None, "önceki dönem kapanmalı"
        assert donemler[1].valid_to is None

    async def test_gecmise_montaj_girmek_calisir(self, client, kullanici_ac, urun_ac, nokta):
        """Aynı cihazı ÖNCEKİ bir tarihe yazmak anlamsız; açık mesaj verilmeli."""
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac)
        ortak = {
            "type": "MONTAJ",
            "assigned_id": nokta.id,
            "kalemler": [{"kimlik": "860000000000226", "product_id": u.id}],
        }
        await client.post(
            "/api/is-emirleri", json={**ortak, "completed_at": "2026-06-01", "plaka": "34AAA111"}
        )
        r = await client.post(
            "/api/is-emirleri", json={**ortak, "completed_at": "2026-03-01", "plaka": "34BBB222"}
        )
        assert r.status_code == 409
        assert "SONRA" in r.json()["detail"]

    async def test_odenmeyecek_kalemde_neden_zorunlu(self, client, kullanici_ac, urun_ac, nokta):
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac)
        r = await client.post(
            "/api/is-emirleri",
            json={
                "type": "MONTAJ",
                "completed_at": "2026-07-15",
                "assigned_id": nokta.id,
                "plaka": "34CCC333",
                "kalemler": [
                    {
                        "kimlik": "860000000000234",
                        "product_id": u.id,
                        "payability": "ODENMEYECEK",
                    }
                ],
            },
        )
        assert r.status_code == 409
        assert "neden" in r.json()["detail"].lower()

    async def test_donem_is_tarihinden_bagimsiz(self, client, kullanici_ac, urun_ac, nokta):
        """İş bir ay yapılıp sonraki ayın hak edişinde ödenebilir."""
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac)
        r = await client.post(
            "/api/is-emirleri",
            json={
                "type": "MONTAJ",
                "completed_at": "2026-03-28",
                "settlement_period": "2026-04",
                "assigned_id": nokta.id,
                "plaka": "34DDD444",
                "kalemler": [{"kimlik": "860000000000242", "product_id": u.id}],
            },
        )
        assert r.status_code == 201
        assert r.json()["settlement_period"] == "2026-04"

    async def test_imei_cakismasi_uyarir(self, client, kullanici_ac, urun_ac, nokta):
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac)
        await client.post(
            "/api/is-emirleri",
            json={
                "type": "MONTAJ",
                "completed_at": "2026-07-15",
                "assigned_id": nokta.id,
                "plaka": "34EEE555",
                "kalemler": [{"kimlik": "860000000000259", "product_id": u.id}],
            },
        )
        r = await client.get("/api/is-emirleri/imei-kontrol?kimlik=860000000000259")
        assert r.status_code == 200
        c = r.json()["cakisma"]
        assert c["plaka"] == "34EEE555"
        assert c["status"] == "AKTIF"

    async def test_bilinmeyen_kimlikte_urun_zorunlu(self, client, kullanici_ac, nokta):
        """Sahte cihaz kaydı üretilmez: ürün seçilmeden yeni cihaz açılamaz."""
        await _giris(client, kullanici_ac)
        r = await client.post(
            "/api/is-emirleri",
            json={
                "type": "MONTAJ",
                "completed_at": "2026-07-15",
                "assigned_id": nokta.id,
                "plaka": "34FFF666",
                "kalemler": [{"kimlik": "860000000000267"}],
            },
        )
        assert r.status_code == 409
        assert "ürün seçilmeli" in r.json()["detail"]


class TestDonemPaneli:
    async def test_panel_ozet_ve_kontrolleri_verir(self, client, kullanici_ac, urun_ac, nokta):
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "koord2", "ADMIN")
        await client.post(
            "/api/is-emirleri",
            json={
                "type": "MONTAJ",
                "completed_at": "2026-07-15",
                "assigned_id": nokta.id,
                "plaka": "34GGG777",
                "travel_km": 10,
                "travel_unit_price": 10,
                "kalemler": [
                    {
                        "kimlik": "860000000000275",
                        "product_id": u.id,
                        "device_role": "BIRINCIL_TAKIP",
                        "payability": "ODENECEK",
                        "unit_price": 400,
                    },
                    # Tutarsız kalem: panelde uyarı çıkmalı.
                    {
                        "kimlik": "860000000000283",
                        "product_id": u.id,
                        "device_role": "KAMERA",
                        "payability": "ODENECEK",
                    },
                ],
            },
        )

        r = await client.get("/api/hakedis/panel/2026-07")
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["ziyaret"] == 1
        assert p["kalem"] == 2
        assert float(p["genel_toplam"]) == 500.0  # 400 kalem + 100 yol
        assert p["aktif_nokta"] == 1

        uyarilar = {k["ad"]: k["adet"] for k in p["kontroller"]}
        assert uyarilar.get("Ödenecek ama tutarı girilmemiş") == 1

        tipler = {t["tip"]: t["adet"] for t in p["is_tipleri"]}
        assert tipler == {"ATS_MONTAJ": 1, "DASHCAM_MONTAJ": 1}

    async def test_bozuk_donem_reddedilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "koord3", "ADMIN")
        assert (await client.get("/api/hakedis/panel/2026")).status_code == 400
