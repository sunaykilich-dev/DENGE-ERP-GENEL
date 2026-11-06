"""Hesaplar: bayrak seti, kayıt bazlı kapsam, eksik alan uyarısı."""

import pytest

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username: str, rol: str):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


async def test_hesap_en_az_bir_rol_ister(client, kullanici_ac):
    await _giris(client, kullanici_ac, "yonetici", "ADMIN")
    r = await client.post("/api/hesaplar", json={"title": "Rolsüz A.Ş."})
    assert r.status_code == 400
    assert "en az bir rolü" in r.json()["detail"]


async def test_ayni_hesap_hem_musteri_hem_montaj_noktasi_olabilir(client, kullanici_ac):
    """AUTOLAND gerçek örneği: kendi aracına kendi montajını yapan rent-a-car.
    Tekil enum tasarımı bunu modelleyemezdi."""
    await _giris(client, kullanici_ac, "yonetici", "ADMIN")
    r = await client.post(
        "/api/hesaplar",
        json={"title": "AUTOLAND Rent A Car", "is_musteri": True, "is_montaj_noktasi": True},
    )
    assert r.status_code == 201, r.text
    assert set(r.json()["roller"]) == {"MUSTERI", "MONTAJ_NOKTASI"}
    # Montaj noktası rolü işaretliyse hak ediş kaydı da açılmalı
    assert r.json()["partner"] is not None


async def test_montaj_noktasinin_eksikleri_gorunur(client, kullanici_ac):
    """E-posta ve IBAN olmadan hak ediş dökümü gönderilemez, ödeme listesi
    çıkarılamaz. Kayıt açılırken zorunlu tutmak göçü kilitlerdi."""
    await _giris(client, kullanici_ac, "yonetici", "ADMIN")
    r = await client.post(
        "/api/hesaplar", json={"title": "Yeni Montajcı", "is_montaj_noktasi": True}
    )
    assert set(r.json()["eksik_alanlar"]) == {"e-posta", "IBAN", "VKN/TCKN"}

    liste = await client.get("/api/hesaplar?eksigi_olanlar=true")
    assert any(h["title"] == "Yeni Montajcı" for h in liste.json())


async def test_gecersiz_iban_reddedilir(client, kullanici_ac):
    await _giris(client, kullanici_ac, "yonetici", "ADMIN")
    r = await client.post(
        "/api/hesaplar",
        json={
            "title": "Hatalı IBAN A.Ş.",
            "is_montaj_noktasi": True,
            "iban": "TR330006100519786457841327",
        },
    )
    assert r.status_code == 422


async def test_satis_temsilcisi_yalniz_kendi_musterilerini_gorur(client, kullanici_ac, db):
    """Kayıt bazlı filtre (brief §3)."""
    yonetici = await kullanici_ac("yonetici", "ADMIN")
    satisci = await kullanici_ac("satisci", "SATIS")

    await client.post("/api/auth/login", json={"username": "yonetici", "password": "parola1234"})
    await client.post(
        "/api/hesaplar",
        json={"title": "Benim Müşterim", "is_musteri": True, "sales_rep_id": satisci.id},
    )
    await client.post(
        "/api/hesaplar",
        json={"title": "Başkasının Müşterisi", "is_musteri": True, "sales_rep_id": yonetici.id},
    )
    await client.post("/api/auth/logout")

    await client.post("/api/auth/login", json={"username": "satisci", "password": "parola1234"})
    basliklar = [h["title"] for h in (await client.get("/api/hesaplar")).json()]
    assert basliklar == ["Benim Müşterim"]


async def test_kapsam_disi_hesap_dogrudan_da_acilamaz(client, kullanici_ac):
    """Liste filtrelenirken detay ucu açık kalırsa kapsam anlamsızlaşır."""
    yonetici = await kullanici_ac("yonetici", "ADMIN")
    await kullanici_ac("satisci", "SATIS")
    await client.post("/api/auth/login", json={"username": "yonetici", "password": "parola1234"})
    r = await client.post(
        "/api/hesaplar",
        json={"title": "Başkasının Müşterisi", "is_musteri": True, "sales_rep_id": yonetici.id},
    )
    hesap_id = r.json()["id"]
    await client.post("/api/auth/logout")

    await client.post("/api/auth/login", json={"username": "satisci", "password": "parola1234"})
    assert (await client.get(f"/api/hesaplar/{hesap_id}")).status_code == 404


async def test_mukerrer_adaylari_benzer_unvani_bulur(client, kullanici_ac):
    await _giris(client, kullanici_ac, "yonetici", "ADMIN")
    ilk = await client.post(
        "/api/hesaplar", json={"title": "ANTALYA RAMAZAN CULLU", "is_montaj_noktasi": True}
    )
    await client.post(
        "/api/hesaplar", json={"title": "ANTALYA RAMAZAN ÇULLU", "is_montaj_noktasi": True}
    )
    adaylar = await client.get(f"/api/hesaplar/{ilk.json()['id']}/mukerrer-adaylari")
    assert adaylar.status_code == 200
    assert any("ÇULLU" in a["title"] for a in adaylar.json())


async def test_unvan_turkce_duyarli_aranir(client, kullanici_ac):
    await _giris(client, kullanici_ac, "yonetici", "ADMIN")
    await client.post(
        "/api/hesaplar", json={"title": "İZMİR OTOFOM OTOMOTİV", "is_montaj_noktasi": True}
    )
    for terim in ("izmir", "İZMİR", "IZMIR", "otofom"):
        sonuc = (await client.get(f"/api/hesaplar?q={terim}")).json()
        assert len(sonuc) == 1, f"{terim} için bulunamadı"


async def test_hesap_degisikligi_kvkk_isaretiyle_loglanir(client, kullanici_ac, db):
    from sqlalchemy import select

    from app.models import AuditLog

    await _giris(client, kullanici_ac, "yonetici", "ADMIN")
    await client.post("/api/hesaplar", json={"title": "KVKK Testi", "is_musteri": True})
    kayit = await db.scalar(select(AuditLog).where(AuditLog.entity == "accounts"))
    assert kayit is not None
    assert kayit.is_personal_data is True
