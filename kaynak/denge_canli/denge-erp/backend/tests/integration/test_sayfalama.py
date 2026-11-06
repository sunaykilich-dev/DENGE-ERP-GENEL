"""Liste uçlarının sayfalaması ve TOPLAM kayıt sayısı.

Bu testler bir üretim hatasından doğdu: liste uçları yalnız `limit`
uyguluyordu, arayüz de gelen diziyi kendi içinde sayfalıyordu. Veri 1.700'den
17.350'ye çıkınca kullanıcı 17.350 cihazın **100'ünü** gördü ve gerisi yokmuş
gibi davrandı. Hiçbir hata mesajı yoktu — sessiz kesme.

Aranan davranış: sunucu istenen sayfayı döndürür ve TOPLAMI
`X-Toplam-Kayit` başlığında bildirir.
"""

import pytest

from app.api.deps import TOPLAM_BASLIGI
from app.models import Device

pytestmark = pytest.mark.integration


@pytest.fixture
async def otuz_cihaz(db, urun_ac):
    urun = await urun_ac(code="SAYFA-TEST", identity_kind="IMEI")
    for i in range(30):
        db.add(Device(product_id=urun.id, identity_kind="IMEI", imei=f"9{i:014d}"))
    await db.commit()
    return urun


async def test_toplam_baslikta_bildirilir(client, kullanici_ac, otuz_cihaz):
    await kullanici_ac("depocu", "DEPO")
    await client.post("/api/auth/login", json={"username": "depocu", "password": "parola1234"})

    r = await client.get("/api/cihazlar?limit=10")
    assert r.status_code == 200
    assert len(r.json()) == 10, "istenen sayfa boyutu aşılmamalı"
    assert r.headers[TOPLAM_BASLIGI] == "30", "toplam, sayfa boyutu değil TÜM kayıt sayısıdır"


async def test_offset_sonraki_sayfayi_getirir(client, kullanici_ac, otuz_cihaz):
    await kullanici_ac("depocu", "DEPO")
    await client.post("/api/auth/login", json={"username": "depocu", "password": "parola1234"})

    ilk = (await client.get("/api/cihazlar?limit=10&offset=0")).json()
    ikinci = (await client.get("/api/cihazlar?limit=10&offset=10")).json()
    ucuncu = (await client.get("/api/cihazlar?limit=10&offset=20")).json()

    kimlikler = [c["id"] for c in ilk + ikinci + ucuncu]
    assert len(set(kimlikler)) == 30, "sayfalar ÇAKIŞMAMALI ve hiçbir kayıt atlanmamalı"


async def test_son_sayfa_eksik_dolu_gelir(client, kullanici_ac, otuz_cihaz):
    await kullanici_ac("depocu", "DEPO")
    await client.post("/api/auth/login", json={"username": "depocu", "password": "parola1234"})

    r = await client.get("/api/cihazlar?limit=10&offset=25")
    assert len(r.json()) == 5
    assert r.headers[TOPLAM_BASLIGI] == "30"


async def test_filtre_toplami_da_daraltir(client, kullanici_ac, otuz_cihaz, db):
    """Toplam, uygulanan filtreden SONRAKİ sayıdır; yoksa sayfa sayısı şişerdi."""
    await kullanici_ac("depocu", "DEPO")
    await client.post("/api/auth/login", json={"username": "depocu", "password": "parola1234"})

    r = await client.get("/api/cihazlar?q=900000000000005&limit=10")
    assert r.headers[TOPLAM_BASLIGI] == str(len(r.json()))
