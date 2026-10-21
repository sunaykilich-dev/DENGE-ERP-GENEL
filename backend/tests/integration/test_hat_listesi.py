"""Hat listesi ucu — göçten gelen yer tutucu ICCID'lerle birlikte.

Bu dosyanın var olma sebebi bir gerileme: ICCID'si bilinmeyen hatlarda göç
`MSISDN:+90…` yer tutucusu yazıyor ve bu dizge TAM 20 KARAKTER. Sağlama
fonksiyonu 20 haneliyi Luhn'dan geçirmeye çalışıp `int('+')` ile patlıyor,
tek bir böyle satır BÜTÜN hat listesini 500 yapıyordu. Canlı veride bu
durumda olan 1.657 hat vardı; yani ekran hiç açılmıyordu.
"""

import pytest

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, ad="hatci", rol="HAT_SORUMLUSU"):
    await kullanici_ac(ad, rol)
    r = await client.post("/api/auth/login", json={"username": ad, "password": "parola1234"})
    assert r.status_code == 200, r.text


class TestHatListesi:
    async def test_yer_tutucu_iccid_listeyi_dusurmez(self, client, kullanici_ac, hat_ac):
        await hat_ac(
            "MSISDN:+905014693254",
            msisdn="+905014693254",
            operator="TURK_TELEKOM",
            status="AKTIF",
            field_sources={"iccid": "EKSIK"},
        )
        await hat_ac("8990011234567890123", msisdn="+905018116520", status="AKTIF")

        await _giris(client, kullanici_ac)
        r = await client.get("/api/hatlar")
        assert r.status_code == 200, r.text
        assert len(r.json()) == 2

    async def test_eksik_iccid_supheli_sayilmaz(self, client, kullanici_ac, hat_ac):
        """ "ICCID yok" ile "sağlaması tutmuyor" ayrı şeyler: biri operatörden
        istenecek eksik bilgi, diğeri şüpheli veri. İkisini aynı saymak 1.657
        hattın tamamını "kontrol edin" diye işaretlerdi."""
        await hat_ac(
            "MSISDN:+905014693254",
            msisdn="+905014693254",
            status="AKTIF",
            field_sources={"iccid": "EKSIK"},
        )
        await _giris(client, kullanici_ac)

        satir = (await client.get("/api/hatlar")).json()[0]
        assert satir["iccid_eksik"] is True
        assert satir["iccid_saglamasi"] is True, "eksik ICCID şüphe üretmemeli"

    async def test_sagalamasi_bozuk_iccid_isaretlenir(self, client, kullanici_ac, hat_ac):
        await hat_ac("89900112345678901232", msisdn="+905018116521", status="AKTIF")
        await _giris(client, kullanici_ac)

        satir = (await client.get("/api/hatlar")).json()[0]
        assert satir["iccid_eksik"] is False
        assert satir["iccid_saglamasi"] is False
