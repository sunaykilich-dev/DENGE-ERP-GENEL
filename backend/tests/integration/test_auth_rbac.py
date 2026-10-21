"""Kimlik doğrulama, yetkilendirme ve denetim izi — gerçek uçlar üzerinden."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, User

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def test_giris_ve_me(client, kullanici_ac):
    await kullanici_ac("depocu", "DEPO")
    r = await _giris(client, "depocu")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"]["code"] == "DEPO"

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    data = me.json()
    assert "cihaz.transfer" in data["permissions"]
    assert data["sees_cost"] is False  # depo maliyet görmez


async def test_hatali_parola_401_ve_denetime_yazilir(client, kullanici_ac, db):
    await kullanici_ac("depocu", "DEPO")
    r = await _giris(client, "depocu", "yanlis-parola")
    assert r.status_code == 401

    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "giris.basarisiz"))
    assert kayit is not None
    assert kayit.new_value["username"] == "depocu"


async def test_bes_hatali_denemede_hesap_kilitlenir(client, kullanici_ac):
    await kullanici_ac("depocu", "DEPO")
    for _ in range(4):
        assert (await _giris(client, "depocu", "yanlis")).status_code == 401
    # 5. deneme kilitler
    assert (await _giris(client, "depocu", "yanlis")).status_code == 423
    # Doğru parola bile artık geçmez
    assert (await _giris(client, "depocu")).status_code == 423


async def test_kilit_zaman_gecince_acilmaz(client, kullanici_ac):
    """Kilit SÜRELİ DEĞİL: saat ilerlese de kendiliğinden açılmamalı.

    Süreli kilitte saldırgan bekleyip kaldığı yerden devam edebiliyordu.
    """
    await kullanici_ac("depocu", "DEPO")
    for _ in range(5):
        await _giris(client, "depocu", "yanlis")

    client.clock.advance(days=7)
    assert (await _giris(client, "depocu")).status_code == 423


async def test_yonetici_kilidi_acabilir(client, kullanici_ac, db):
    await kullanici_ac("depocu", "DEPO")
    await kullanici_ac("patron", "ADMIN")
    for _ in range(5):
        await _giris(client, "depocu", "yanlis")
    assert (await _giris(client, "depocu")).status_code == 423

    await _giris(client, "patron")
    kilitliler = await client.get("/api/kullanicilar/kilitli")
    assert kilitliler.json() == ["depocu"]
    assert (await client.post("/api/kullanicilar/depocu/kilidi-ac")).status_code == 200

    await client.post("/api/auth/logout")
    assert (await _giris(client, "depocu")).status_code == 200, "kilit açıldıktan sonra girebilmeli"

    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "kilit.acildi"))
    assert kayit is not None and kayit.new_value["username"] == "depocu"


async def test_kilit_acma_yetki_ister(client, kullanici_ac):
    await kullanici_ac("depocu", "DEPO")
    await kullanici_ac("depocu2", "DEPO")
    for _ in range(5):
        await _giris(client, "depocu2", "yanlis")

    await _giris(client, "depocu")
    assert (await client.post("/api/kullanicilar/depocu2/kilidi-ac")).status_code == 403


async def test_oturumsuz_erisim_401(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_csrf_basligi_olmadan_mutasyon_403(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.post(
        "/api/kullanicilar",
        json={
            "full_name": "Yeni",
            "username": "yeni",
            "password": "parola1234",
            "role_code": "DEPO",
        },
        headers={"X-Requested-With": ""},
    )
    assert r.status_code == 403


async def test_yetkisiz_rol_kullanici_yonetemez(client, kullanici_ac):
    """Depo sorumlusunun sistem.kullanici izni yok — 403 almalı."""
    await kullanici_ac("depocu", "DEPO")
    await _giris(client, "depocu")
    r = await client.get("/api/kullanicilar")
    assert r.status_code == 403
    assert "yetkiniz yok" in r.json()["detail"]


async def test_admin_kullanici_acabilir_ve_denetime_yazilir(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.post(
        "/api/kullanicilar",
        json={
            "full_name": "Satış Kişisi",
            "username": "satisci",
            "password": "parola1234",
            "role_code": "SATIS",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"]["scope"] == "KENDI_MUSTERILERI"

    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "users", AuditLog.action == "olustur")
    )
    assert kayit is not None
    assert kayit.new_value == {"username": "satisci", "rol": "SATIS"}


async def test_kendi_rolunu_degistiremez(client, kullanici_ac):
    admin = await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{admin.id}", json={"role_code": "DEPO"})
    assert r.status_code == 400
    assert "Kendi rolünüzü" in r.json()["detail"]


async def test_kendi_hesabini_kapatamaz(client, kullanici_ac):
    admin = await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{admin.id}", json={"is_active": False})
    assert r.status_code == 400


async def test_rol_degisince_acik_oturumlar_dusurulur(client, kullanici_ac, db):
    """Eski yetkiyle açılmış oturum yeni kısıtı görmezdi — düşürülmeli."""
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"role_code": "SATIS"})
    assert r.status_code == 200
    assert r.json()["role"]["code"] == "SATIS"

    from app.models import Session as OturumModel

    kalan = (await db.scalars(select(OturumModel).where(OturumModel.user_id == hedef.id))).all()
    assert kalan == []


async def test_iyimser_kilitleme_cakismasi_409(client, kullanici_ac, db):
    """İki kişi aynı kaydı açtı; ikincisinin yazması sessizce kaybolmamalı."""
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")

    gorulen_surum = hedef.version  # her iki kullanıcının da gördüğü sürüm

    ilk = await client.patch(
        f"/api/kullanicilar/{hedef.id}",
        json={"full_name": "Birinci Yazan", "version": gorulen_surum},
    )
    assert ilk.status_code == 200

    ikinci = await client.patch(
        f"/api/kullanicilar/{hedef.id}",
        json={"full_name": "İkinci Yazan", "version": gorulen_surum},
    )
    assert ikinci.status_code == 409
    assert "başka biri değiştirdi" in ikinci.json()["detail"]

    guncel = await db.get(User, hedef.id)
    await db.refresh(guncel)
    assert guncel.full_name == "Birinci Yazan"  # ikinci yazma kaybolmadı, reddedildi


async def test_parola_denetim_kaydina_duz_metin_yazilmaz(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    await client.patch(f"/api/kullanicilar/{hedef.id}", json={"password": "yeni-parola-123"})

    kayitlar = (await db.scalars(select(AuditLog).where(AuditLog.entity == "users"))).all()
    hepsi = str([(k.old_value, k.new_value) for k in kayitlar])
    assert "yeni-parola-123" not in hepsi
    assert "***" in hepsi
