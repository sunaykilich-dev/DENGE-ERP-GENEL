"""Denge stoğu özeti — model bazında adet.

Serili ve serisiz ürün AYNI listede birleşir ama sayım yolları farklıdır:
cihazda her adedin kendi kaydı var, aksesuarda yok. İkisini tek sayaçta
birleştirmek (ör. cihazlar için de bir adet kolonu tutmak) iki rakamın
zamanla ayrışması demekti; bu testler ayrımı çiviliyor.
"""

import pytest

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, ad="depocu", rol="DEPO"):
    await kullanici_ac(ad, rol)
    r = await client.post("/api/auth/login", json={"username": ad, "password": "parola1234"})
    assert r.status_code == 200, r.text


class TestStokOzeti:
    async def test_serili_urun_cihaz_durumlarindan_sayilir(
        self, client, kullanici_ac, urun_ac, cihaz_ac
    ):
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000010", urun=u, status="STOKTA")
        await cihaz_ac(imei="860000000000028", urun=u, status="TEST_EDILDI")
        await cihaz_ac(imei="860000000000036", urun=u, status="AKTIF")
        await cihaz_ac(imei="860000000000044", urun=u, status="REZERVE")

        await _giris(client, kullanici_ac)
        r = await client.get("/api/stok/ozet")
        assert r.status_code == 200, r.text
        satir = next(s for s in r.json() if s["kod"] == "L300")

        assert satir["serili"] is True
        # STOKTA + TEST_EDILDI elde sayılır; REZERVE söz verilmiştir, AKTIF sahadadır.
        assert satir["elde"] == 2
        assert satir["ayrilmis"] == 1
        assert satir["sahada"] == 1

    async def test_serisiz_urun_hareket_toplamidir(self, client, db, kullanici_ac, urun_ac):
        u = await urun_ac("KABLO-5M", "YOK", type="AKSESUAR")
        await _giris(client, kullanici_ac, "depo2", "ADMIN")

        for adet, neden in ((100, "GIRIS"), (-30, "CIKIS"), (5, "SAYIM")):
            r = await client.post(
                "/api/stok/hareket",
                json={"product_id": u.id, "qty": adet, "reason": neden},
            )
            assert r.status_code == 201, r.text

        ozet = (await client.get("/api/stok/ozet")).json()
        satir = next(s for s in ozet if s["kod"] == "KABLO-5M")
        assert satir["serili"] is False
        assert satir["elde"] == 75

    async def test_serili_urune_adet_hareketi_yazilamaz(self, client, kullanici_ac, urun_ac):
        """Cihazda adet, kayıtların kendisidir; ikinci bir sayaç tutulmaz."""
        u = await urun_ac("L300", "IMEI")
        await _giris(client, kullanici_ac, "depo3", "ADMIN")

        r = await client.post("/api/stok/hareket", json={"product_id": u.id, "qty": 5})
        assert r.status_code == 409
        assert "seri numarasıyla takip" in r.json()["detail"]

    async def test_sifir_adet_reddedilir(self, client, kullanici_ac, urun_ac):
        u = await urun_ac("KABLO-5M", "YOK", type="AKSESUAR")
        await _giris(client, kullanici_ac, "depo4", "ADMIN")
        r = await client.post("/api/stok/hareket", json={"product_id": u.id, "qty": 0})
        assert r.status_code == 409
