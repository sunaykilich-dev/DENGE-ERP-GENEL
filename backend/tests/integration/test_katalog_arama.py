"""Ürün kataloğu ve genel arama."""

import pytest

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username="yonetici", rol="ADMIN"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


async def test_urun_kimlik_tipi_kaydedilir(client, kullanici_ac):
    """IMEI zorunluluğu ürüne bağlı: takip cihazında IMEI, ek kamerada seri no."""
    await _giris(client, kullanici_ac)
    takip = await client.post(
        "/api/urunler",
        json={"code": "L300", "name": "Armoli L300", "identity_kind": "IMEI", "family": "L300"},
    )
    assert takip.status_code == 201
    assert takip.json()["identity_kind"] == "IMEI"

    kamera = await client.post(
        "/api/urunler",
        json={
            "code": "DAHUA-HMW3200LP",
            "name": "Dahua HMW3200LP İç Kamera",
            "identity_kind": "SERI_NO",
            "requires_parent": True,
        },
    )
    assert kamera.status_code == 201
    assert kamera.json()["requires_parent"] is True


async def test_ana_cihaz_gerektiren_urun_imei_ile_tanimlanamaz(client, kullanici_ac):
    """Veritabanı kısıtı: ana cihaza bağlanan ürün seri no ile tanımlanır.

    Kısıt ihlali kullanıcı hatasıdır: eskiden `IntegrityError` uca kadar
    çıkıyor ve 500 veriyordu. Artık okunabilir bir 409 dönüyor — transaction
    yine temiz geri alınıyor, yarım kayıt kalmıyor.
    """
    await _giris(client, kullanici_ac)
    cevap = await client.post(
        "/api/urunler",
        json={
            "code": "HATALI",
            "name": "Tutarsız Ürün",
            "identity_kind": "IMEI",
            "requires_parent": True,
        },
    )
    assert cevap.status_code == 409
    assert "kural" in cevap.json()["detail"] or "izin verilen" in cevap.json()["detail"]
    # Yarım kayıt kalmadı.
    assert (await client.get("/api/urunler?q=HATALI")).json() == []


async def test_ayni_kod_iki_kez_acilamaz(client, kullanici_ac):
    await _giris(client, kullanici_ac)
    veri = {"code": "GS900", "name": "GS900 Araç Takip"}
    assert (await client.post("/api/urunler", json=veri)).status_code == 201
    r = await client.post("/api/urunler", json=veri)
    assert r.status_code == 409


async def test_bilinmeyen_sebeke_teknolojisi_reddedilir(client, kullanici_ac):
    await _giris(client, kullanici_ac)
    r = await client.post(
        "/api/urunler",
        json={"code": "X1", "name": "Test", "supported_network_tech": ["5G"]},
    )
    assert r.status_code == 422


async def test_genel_arama_hesap_ve_urunu_birlikte_bulur(client, kullanici_ac):
    """Kabul kriteri 1'in temeli: tek kutudan arama."""
    await _giris(client, kullanici_ac)
    await client.post("/api/hesaplar", json={"title": "L300 LOJİSTİK", "is_musteri": True})
    await client.post("/api/urunler", json={"code": "L300", "name": "Armoli L300"})

    sonuc = (await client.get("/api/arama?q=L300")).json()
    turler = {s["tur"] for s in sonuc}
    assert turler == {"HESAP", "URUN"}


async def test_arama_kapsami_ve_izni_birlikte_uygular(client, kullanici_ac):
    """Arama bir yetki atlatma yolu olmamalı.

    İki ayrı mekanizma: satış temsilcisi BAŞKASININ müşterisini kapsam
    filtresi yüzünden göremez, ama ürün kataloğunu görür (teklif hazırlamak
    için `urun.gor` izni var). Arama ikisine de uymalı.
    """
    yonetici = await kullanici_ac("yonetici", "ADMIN")
    await kullanici_ac("satisci", "SATIS")
    await client.post("/api/auth/login", json={"username": "yonetici", "password": "parola1234"})
    await client.post(
        "/api/hesaplar",
        json={"title": "Gizli Müşteri", "is_musteri": True, "sales_rep_id": yonetici.id},
    )
    await client.post("/api/urunler", json={"code": "GIZLI", "name": "Gizli Ürün"})
    await client.post("/api/auth/logout")

    await client.post("/api/auth/login", json={"username": "satisci", "password": "parola1234"})
    sonuc = (await client.get("/api/arama?q=Gizli")).json()
    turler = {s["tur"] for s in sonuc}
    assert "HESAP" not in turler, "başkasının müşterisi arama üzerinden sızdı"
    assert turler == {"URUN"}, "ürün kataloğu satış temsilcisine açık olmalı"


async def test_urun_izni_olmayan_katalogu_goremez(client, kullanici_ac):
    await _giris(client, kullanici_ac, "hatci", "HAT_SORUMLUSU")
    assert (await client.get("/api/urunler")).status_code == 200  # urun.gor var
    r = await client.post("/api/urunler", json={"code": "X", "name": "Test"})
    assert r.status_code == 403  # urun.yaz yok
