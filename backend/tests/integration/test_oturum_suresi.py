"""Oturum: 12 saat mutlak süre ve `giris_acik` (TS-007, E13-02).

Kayan pencere her istekte uzadığı için sürekli kullanılan — ya da çalınıp
açık tutulan — bir oturum hiç bitmiyordu. Ayrıca giriş kuralı üç yolda üç
farklı yazılmıştı: `login_mfa` yalnız `is_active`'e bakıyordu, yani girişi
kapatılan MFA'lı hesap eldeki pending_token ile yine oturum açabilirdi.
"""

import pyotp
import pytest
from sqlalchemy import select

from app import crypto
from app.models import Session as OturumModel
from app.models import User
from app.services.auth import SESSION_MAX, SESSION_TTL

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


def test_sureler_kod_sabiti():
    from datetime import timedelta

    assert SESSION_MAX == timedelta(hours=12)
    assert SESSION_TTL == timedelta(hours=4)


async def test_dort_saat_hareketsiz_oturum_duser(client, kullanici_ac):
    await kullanici_ac("depocu", "DEPO")
    assert (await _giris(client, "depocu")).status_code == 200
    client.clock.advance(hours=3, minutes=59)
    assert (await client.get("/api/auth/me")).status_code == 200
    client.clock.advance(hours=4)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_surekli_kullanilan_oturum_12_saatte_duser(client, kullanici_ac, db):
    """Her 20 dakikada istek atan oturum kaymaya devam eder ama 12. saatte biter."""
    await kullanici_ac("depocu", "DEPO")
    assert (await _giris(client, "depocu")).status_code == 200
    for _ in range(35):  # 35 × 20 dk = 11 sa 40 dk
        client.clock.advance(minutes=20)
        assert (await client.get("/api/auth/me")).status_code == 200

    # Kaydırılmış bitiş mutlak sınırı aşmamalı.
    kisi = await db.scalar(select(User).where(User.username == "depocu"))
    oturum = await db.scalar(select(OturumModel).where(OturumModel.user_id == kisi.id))
    assert oturum.expires_at <= oturum.created_at + SESSION_MAX

    client.clock.advance(minutes=20)  # tam 12 saat
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_girisi_kapali_hesap_dogru_parolayla_giremez(client, kullanici_ac, db):
    kisi = await kullanici_ac("saha", "DEPO")
    kisi.giris_acik = False
    await db.commit()
    r = await _giris(client, "saha")
    assert r.status_code == 401
    assert r.json()["detail"] == "Kullanıcı adı veya parola hatalı", "ayrıntı sızdırılmaz"


async def test_girisi_kapatilan_kisinin_acik_oturumu_sonraki_istekte_duser(
    client, kullanici_ac, db
):
    """Oturumlar silinmemiş olsa bile `resolve_session` giriş kuralını uygular."""
    kisi = await kullanici_ac("depocu", "DEPO")
    assert (await _giris(client, "depocu")).status_code == 200
    kisi.giris_acik = False
    await db.commit()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_yonetici_girisi_kapatinca_tum_oturumlar_silinir(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "depocu")
    depocu_cerezi = dict(client.cookies)
    await _giris(client, "yonetici")

    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"giris_acik": False})
    assert r.status_code == 200, r.text
    assert r.json()["giris_acik"] is False
    assert r.json()["is_active"] is True, "kayıt canlı kalır; yalnız giriş kapanır"

    kalan = (await db.scalars(select(OturumModel).where(OturumModel.user_id == hedef.id))).all()
    assert kalan == []
    client.cookies.update(depocu_cerezi)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_girisi_kapatmak_yetki_ister(client, kullanici_ac, db):
    hedef = await kullanici_ac("depocu", "DEPO")
    await kullanici_ac("depocu2", "DEPO")
    await _giris(client, "depocu2")
    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"giris_acik": False})
    assert r.status_code == 403
    await db.refresh(hedef)
    assert hedef.giris_acik is True


async def test_mfa_li_girisi_kapali_hesap_pending_token_ile_giremez(client, kullanici_ac, db):
    """Parola adımı geçildikten SONRA girişi kapatılan hesap, elindeki geçerli
    pending_token ve doğru kodla oturum açamamalı (E13-02 c)."""
    sir = pyotp.random_base32()
    kisi = await kullanici_ac("depocu", "DEPO")
    kisi.mfa_enabled = True
    kisi.totp_secret = crypto.encrypt(sir)
    await db.commit()

    govde = (await _giris(client, "depocu")).json()
    assert govde["mfa_required"] is True
    jeton = govde["pending_token"]

    kisi.giris_acik = False
    await db.commit()

    r = await client.post(
        "/api/auth/login/mfa", json={"pending_token": jeton, "code": pyotp.TOTP(sir).now()}
    )
    assert r.status_code == 401
    assert "dngerp_session" not in r.cookies


async def test_mfa_li_acik_hesap_kodla_girer(client, kullanici_ac, db):
    """Kontrol: aynı akış giriş açıkken çalışıyor (yukarıdaki 401 gerçek ret)."""
    sir = pyotp.random_base32()
    kisi = await kullanici_ac("depocu", "DEPO")
    kisi.mfa_enabled = True
    kisi.totp_secret = crypto.encrypt(sir)
    await db.commit()
    jeton = (await _giris(client, "depocu")).json()["pending_token"]
    r = await client.post(
        "/api/auth/login/mfa", json={"pending_token": jeton, "code": pyotp.TOTP(sir).now()}
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["giris_acik"] is True


async def test_me_birim_ve_giris_alanlarini_dondurur(client, kullanici_ac, db):
    from app.models import UserUnit

    kisi = await kullanici_ac("sef", "SERVIS_SEF")
    db.add_all(
        [
            UserUnit(user_id=kisi.id, birim="POC", is_primary=True),
            UserUnit(user_id=kisi.id, birim="GUVENLIK"),
        ]
    )
    await db.commit()
    await _giris(client, "sef")
    me = (await client.get("/api/auth/me")).json()
    assert me["birimler"] == ["GUVENLIK", "POC"]
    assert me["birincil_birim"] == "POC"
    assert me["giris_acik"] is True
    assert me["parola_degismeli"] is False
    # Personel alanları giriş yanıtında yok (PersonelOut'ta).
    assert not {"sicil_no", "personel_notu", "saha_rolu"} & set(me)
