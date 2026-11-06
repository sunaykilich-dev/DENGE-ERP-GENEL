"""Cihaz kartı ve durum geçişleri — kabul kriteri 1 ve brief §4.2."""

import pytest

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username="teknik", rol="TEKNIK_SERVIS"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


async def test_imei_ile_cihaz_karti_gelir(client, kullanici_ac, urun_ac, cihaz_ac):
    """Kabul kriteri 1: bir IMEI yazıldığında tek ekranda her şey."""
    await _giris(client, kullanici_ac)
    urun = await urun_ac("L300", "IMEI", family="L300")
    await cihaz_ac(imei="861100063834630", urun=urun, status="AKTIF")

    r = await client.get("/api/cihazlar/861100063834630")
    assert r.status_code == 200, r.text
    kart = r.json()
    assert kart["kimlik"] == "861100063834630"
    assert kart["product_code"] == "L300"
    assert kart["status"] == "AKTIF"
    assert set(kart["sonraki_durumlar"]) == {"SOKULDU", "ARIZALI", "KAYIP_CALINTI"}


async def test_seri_no_ile_de_bulunur(client, kullanici_ac, urun_ac, cihaz_ac):
    await _giris(client, kullanici_ac)
    urun = await urun_ac("DAHUA-HDW3200GP", "SERI_NO", requires_parent=True)
    await cihaz_ac(serial_no="BB06882PAG00032", urun=urun)
    r = await client.get("/api/cihazlar/BB06882PAG00032")
    assert r.status_code == 200
    assert r.json()["identity_kind"] == "SERI_NO"


async def test_kartta_takili_hat_gorunur(client, kullanici_ac, urun_ac, cihaz_ac, hat_ac):
    await _giris(client, kullanici_ac, "hatci", "HAT_SORUMLUSU")
    urun = await urun_ac("L300", "IMEI")
    cihaz = await cihaz_ac(imei="861100063834630", urun=urun)
    hat = await hat_ac("8990011234567890123", msisdn="+905018116520", plan_name="50 GB")

    tak = await client.post(f"/api/hatlar/{hat.id}/tak", json={"device_id": cihaz.id})
    assert tak.status_code == 200, tak.text

    kart = (await client.get("/api/cihazlar/861100063834630")).json()
    assert kart["hat"]["iccid"] == "8990011234567890123"
    assert kart["hat"]["plan_name"] == "50 GB"
    assert kart["hat_gecmisi_adedi"] == 1


async def test_kartta_ek_kameralar_kanallariyla_gorunur(client, kullanici_ac, urun_ac, cihaz_ac):
    """'Aracın arka kamerası arızalı' kaydının tutulabilmesinin ön koşulu."""
    await _giris(client, kullanici_ac)
    dashcam_urun = await urun_ac("DAHUA-CDR8213", "IMEI", channel_count=2)
    kamera_urun = await urun_ac("DAHUA-HDW3200GP", "SERI_NO", requires_parent=True)
    dashcam = await cihaz_ac(imei="861100063834630", urun=dashcam_urun)
    await cihaz_ac(
        serial_no="BB06882PAG00032", urun=kamera_urun, parent_device_id=dashcam.id, channel_no=1
    )
    await cihaz_ac(
        serial_no="BB06882PAG00033", urun=kamera_urun, parent_device_id=dashcam.id, channel_no=2
    )

    kart = (await client.get("/api/cihazlar/861100063834630")).json()
    assert [a["channel_no"] for a in kart["alt_cihazlar"]] == [1, 2]


async def test_imei_zorunlu_urunde_anlasilir_hata(client, kullanici_ac, urun_ac):
    """Veritabanı da engelliyor ama kullanıcı anlaşılır mesaj görmeli."""
    await _giris(client, kullanici_ac)
    urun = await urun_ac("L300", "IMEI")
    r = await client.post("/api/cihazlar", json={"product_id": urun.id})
    assert r.status_code == 400
    assert "IMEI boş bırakılamaz" in r.json()["detail"]


async def test_seri_no_zorunlu_urunde_anlasilir_hata(client, kullanici_ac, urun_ac):
    await _giris(client, kullanici_ac)
    urun = await urun_ac("DAHUA-HDW3200GP", "SERI_NO", requires_parent=True)
    r = await client.post("/api/cihazlar", json={"product_id": urun.id})
    assert r.status_code == 400
    assert "seri numarasıyla takip edilir" in r.json()["detail"]


async def test_bozuk_imei_reddedilir(client, kullanici_ac, urun_ac):
    await _giris(client, kullanici_ac)
    urun = await urun_ac("L300", "IMEI")
    r = await client.post("/api/cihazlar", json={"product_id": urun.id, "imei": "8.63071E+14"})
    assert r.status_code == 422


async def test_durum_gecisi_gecmise_yazilir(client, kullanici_ac, urun_ac, cihaz_ac, db):
    await _giris(client, kullanici_ac)
    urun = await urun_ac("L300", "IMEI")
    cihaz = await cihaz_ac(imei="861100063834630", urun=urun, status="STOKTA")

    r = await client.post(
        f"/api/cihazlar/{cihaz.id}/durum",
        json={"to_status": "TEST_EDILDI", "reason": "Giriş testi"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "TEST_EDILDI"

    kart = (await client.get("/api/cihazlar/861100063834630")).json()
    assert kart["durum_gecmisi"][0]["from_status"] == "STOKTA"
    assert kart["durum_gecmisi"][0]["to_status"] == "TEST_EDILDI"
    assert kart["durum_gecmisi"][0]["reason"] == "Giriş testi"


async def test_kurala_aykiri_gecis_reddedilir(client, kullanici_ac, urun_ac, cihaz_ac):
    """Brief §4.2'nin açık örneği: HURDA'dan AKTIF'e geçilemez."""
    await _giris(client, kullanici_ac)
    urun = await urun_ac("L300", "IMEI")
    cihaz = await cihaz_ac(imei="861100063834630", urun=urun, status="HURDA")
    r = await client.post(f"/api/cihazlar/{cihaz.id}/durum", json={"to_status": "AKTIF"})
    assert r.status_code == 409
    assert "terminal" in r.json()["detail"]


async def test_ilk_aktivasyon_tarihi_bir_kez_yazilir(client, kullanici_ac, urun_ac, cihaz_ac, db):
    """Garanti cihaza bağlıdır; araç değişse de başlangıç değişmez."""
    from app.models import Device

    await _giris(client, kullanici_ac)
    urun = await urun_ac("L300", "IMEI")
    cihaz = await cihaz_ac(imei="861100063834630", urun=urun, status="MONTAJ_BEKLIYOR")
    await client.post(f"/api/cihazlar/{cihaz.id}/durum", json={"to_status": "AKTIF"})

    guncel = await db.get(Device, cihaz.id)
    await db.refresh(guncel)
    ilk = guncel.first_activation_date
    assert ilk is not None

    await client.post(f"/api/cihazlar/{cihaz.id}/durum", json={"to_status": "SOKULDU"})
    await client.post(f"/api/cihazlar/{cihaz.id}/durum", json={"to_status": "AKTIF"})
    await db.refresh(guncel)
    assert guncel.first_activation_date == ilk


async def test_cihaz_izni_olmayan_goremez(client, kullanici_ac, urun_ac, cihaz_ac):
    urun = await urun_ac("L300", "IMEI")
    await cihaz_ac(imei="861100063834630", urun=urun)
    await _giris(client, kullanici_ac, "montajci", "MONTAJ_KOORD")
    assert (await client.get("/api/cihazlar")).status_code == 200  # cihaz.gor var
    r = await client.post("/api/cihazlar", json={"product_id": urun.id, "imei": "111111111111111"})
    assert r.status_code == 403  # cihaz.yaz yok


async def test_arac_listesi_plaka_dogrulama_bayragini_tasir(client, kullanici_ac, db):
    """Bayrak çıktı şemasından düşerse arayüz TÜM araçları 'doğrulanmadı'
    gösterir — sessiz ve yanıltıcı bir hata."""
    from app.models import Vehicle

    await kullanici_ac("teknik", "TEKNIK_SERVIS")
    await client.post("/api/auth/login", json={"username": "teknik", "password": "parola1234"})

    db.add(Vehicle(plate="34ABC123", is_plate_verified=True))
    db.add(Vehicle(plate="KAZICI YÜKLEYİCİ-1", is_plate_verified=False))
    await db.commit()

    liste = (await client.get("/api/araclar")).json()
    bayraklar = {a["plate"]: a["is_plate_verified"] for a in liste}
    assert bayraklar["34ABC123"] is True
    assert bayraklar["KAZICI YÜKLEYİCİ-1"] is False
