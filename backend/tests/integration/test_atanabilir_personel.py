"""Atanabilir personel servisi — planlama kaynak listesi (TS-009; E13-07, E02-04).

Eski sistemde kaynak listesi koda gömülü isimlerden ve rol adından
türetiliyordu: ünvanı "Sistem Mühendisi" olan saha teknisyeni listede
yoktu, ofisteki "müdür" ise şef listesinde çıkıyordu. Ölçüt artık tek ve
açık: aktif, ayrılmamış, saha rolü SEF/TEKNISYEN/STAJYER, birim üyesi.
Girişsiz personel listededir (sahaya gider, ekrana girmez).
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import Role, User, UserPermission, UserUnit

pytestmark = pytest.mark.integration

ALANLAR = {"id", "ad", "saha_rolu", "birimler", "birincil_birim", "giris_acik"}


async def _giris(client, username: str, password: str = "parola1234"):
    cevap = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert cevap.status_code == 200, cevap.text


async def _birim(db, kisi: User, *birimler: str, birincil: str | None = None) -> None:
    birincil = birincil or birimler[0]
    for b in birimler:
        db.add(UserUnit(user_id=kisi.id, birim=b, is_primary=b == birincil))
    await db.commit()


async def _personel(db, ad: str, *birimler: str, saha_rolu: str | None = "TEKNISYEN", **kw):
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
    kisi = User(
        full_name=ad,
        username=ad.lower().replace(" ", "."),
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA",
        role_id=rol.id,
        giris_acik=kw.pop("giris_acik", False),
        saha_rolu=saha_rolu,
        **kw,
    )
    db.add(kisi)
    await db.commit()
    await db.refresh(kisi)
    if birimler:
        await _birim(db, kisi, *birimler)
    return kisi


@pytest.fixture
async def ortam(client, db, kullanici_ac):
    sef = await kullanici_ac("guv_sef", "SERVIS_SEF")
    await _birim(db, sef, "GUVENLIK")
    # Şef kartları görmesin: liste `personel.gor` İSTEMEMELİ.
    db.add(
        UserPermission(user_id=sef.id, permission_code="personel.gor", allow=False, gerekce="test")
    )
    await db.commit()

    kisiler = {
        "muhendis": await _personel(db, "Sistem Muhendisi", "GUVENLIK", unvan="Sistem Mühendisi"),
        "stajyer": await _personel(db, "Girissiz Stajyer", "GUVENLIK", saha_rolu="STAJYER"),
        "sef_kisi": await _personel(db, "Saha Sefi", "GUVENLIK", saha_rolu="SEF"),
        "mudur": await _personel(db, "Ofis Muduru", "GUVENLIK", saha_rolu="OFIS", unvan="Müdür"),
        "rolsuz": await _personel(db, "Rolsuz Kisi", "GUVENLIK", saha_rolu=None),
        "ayrilmis": await _personel(
            db,
            "Ayrilmis Kisi",
            "GUVENLIK",
            is_active=False,
            ayrilis_tarihi=date(2026, 9, 1),
            ayrilis_nedeni="ISTIFA",
        ),
        "poc": await _personel(db, "Poc Teknisyen", "POC"),
        "cift": await _personel(db, "Cift Birimli", "MOBILITE", "ARAC_TAKIP"),
    }
    return {"sef": sef, **kisiler}


class TestYetki:
    async def test_servis_gor_olmayan_403(self, client, kullanici_ac, ortam):
        await kullanici_ac("satisci", "SATIS")
        await _giris(client, "satisci")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "GUVENLIK"})
        assert cevap.status_code == 403

    async def test_personel_gor_olmadan_sef_kendi_birimini_gorur(self, client, ortam):
        await _giris(client, "guv_sef")
        assert (await client.get("/api/personel")).status_code == 403  # kartlar kapalı
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "GUVENLIK"})
        assert cevap.status_code == 200


class TestOlcut:
    async def test_olcut(self, client, ortam):
        await _giris(client, "guv_sef")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "GUVENLIK"})
        adlar = {s["ad"] for s in cevap.json()}
        assert adlar == {"Sistem Muhendisi", "Girissiz Stajyer", "Saha Sefi"}

    async def test_girissiz_personel_bayrakla_listede(self, client, ortam):
        await _giris(client, "guv_sef")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "GUVENLIK"})
        stajyer = next(s for s in cevap.json() if s["ad"] == "Girissiz Stajyer")
        assert stajyer["giris_acik"] is False

    async def test_yalniz_izinli_alanlar(self, client, ortam):
        await _giris(client, "guv_sef")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "GUVENLIK"})
        for satir in cevap.json():
            assert set(satir) == ALANLAR, set(satir) ^ ALANLAR

    async def test_saha_rolu_suzgeci(self, client, ortam):
        await _giris(client, "guv_sef")
        cevap = await client.get(
            "/api/personel/atanabilir", params={"birim": "GUVENLIK", "saha_rolu": "SEF"}
        )
        assert [s["ad"] for s in cevap.json()] == ["Saha Sefi"]
        cevap = await client.get(
            "/api/personel/atanabilir", params={"birim": "GUVENLIK", "saha_rolu": "OFIS"}
        )
        assert cevap.status_code == 400

    async def test_cok_birimli_kisi_iki_listede(self, client, kullanici_ac, ortam):
        await kullanici_ac("servis_mudur", "SERVIS_YONETICI")
        await _giris(client, "servis_mudur")
        for birim in ("MOBILITE", "ARAC_TAKIP"):
            cevap = await client.get("/api/personel/atanabilir", params={"birim": birim})
            assert [s["ad"] for s in cevap.json()] == ["Cift Birimli"], birim
            assert cevap.json()[0]["birimler"] == ["ARAC_TAKIP", "MOBILITE"]


class TestDogrulamaVeKapsam:
    async def test_katalog_disi_birim_400(self, client, ortam):
        await _giris(client, "guv_sef")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "UZAY"})
        assert cevap.status_code == 400

    async def test_birim_zorunlu(self, client, ortam):
        await _giris(client, "guv_sef")
        assert (await client.get("/api/personel/atanabilir")).status_code == 422

    async def test_kapsam_disi_birim_404(self, client, ortam):
        await _giris(client, "guv_sef")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "POC"})
        assert cevap.status_code == 404

    async def test_birimsiz_sef_404(self, client, kullanici_ac, ortam):
        await kullanici_ac("birimsiz_sef", "SERVIS_SEF")
        await _giris(client, "birimsiz_sef")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "GUVENLIK"})
        assert cevap.status_code == 404

    async def test_teknisyen_yalniz_kendisini_gorur(self, client, db, kullanici_ac, ortam):
        tek = await kullanici_ac("girisli_tek", "SERVIS_TEKNISYEN")
        tek.saha_rolu = "TEKNISYEN"
        await db.commit()
        await _birim(db, tek, "GUVENLIK")
        await _giris(client, "girisli_tek")
        cevap = await client.get("/api/personel/atanabilir", params={"birim": "GUVENLIK"})
        assert cevap.status_code == 200
        assert [s["id"] for s in cevap.json()] == [tek.id]


class TestServisFonksiyonu:
    async def test_atanabilir_mi_ayni_olcut(self, db, ortam):
        from app.services.teknik_servis import personel as svc

        assert await svc.atanabilir_mi(db, ortam["stajyer"].id, "GUVENLIK") is True
        assert await svc.atanabilir_mi(db, ortam["mudur"].id, "GUVENLIK") is False
        assert await svc.atanabilir_mi(db, ortam["ayrilmis"].id, "GUVENLIK") is False
        assert await svc.atanabilir_mi(db, ortam["poc"].id, "GUVENLIK") is False
        assert await svc.atanabilir_mi(db, ortam["sef_kisi"].id, "GUVENLIK", ("SEF",)) is True
        assert await svc.atanabilir_mi(db, ortam["muhendis"].id, "GUVENLIK", ("SEF",)) is False
