"""MFA zorunluluğu — parola doğru olsa da kurulum yapılmadan iş yapılamaz.

Diğer testler `MFA_ZORUNLU=false` ile koşuyor (conftest); iş mantığını
sınayan her test kurulum kapısına takılsaydı hiçbir şey test edilemezdi.
Kapının kendisi burada, açıkken sınanıyor.
"""

import os

import pytest

from app.config import get_config

pytestmark = pytest.mark.integration


@pytest.fixture
def mfa_zorunlu():
    """Bu dosya süresince zorunluluğu açar; çıkışta eski hâline döndürür."""
    onceki = os.environ.get("MFA_ZORUNLU")
    os.environ["MFA_ZORUNLU"] = "true"
    get_config.cache_clear()
    yield
    if onceki is None:
        del os.environ["MFA_ZORUNLU"]
    else:
        os.environ["MFA_ZORUNLU"] = onceki
    get_config.cache_clear()


async def _giris(client, username: str = "depocu", password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def test_kurulum_yapmadan_uclara_erisilemez(client, kullanici_ac, mfa_zorunlu):
    await kullanici_ac("depocu", "DEPO")
    assert (await _giris(client)).status_code == 200, "parola girişi yine de çalışmalı"

    r = await client.get("/api/cihazlar")
    assert r.status_code == 403
    assert r.json()["detail"]["kod"] == "MFA_KURULUMU_GEREKLI"


async def test_me_ve_kurulum_uclari_acik_kalir(client, kullanici_ac, mfa_zorunlu):
    """Kurulumu yapabilmek için bu üç yol gerekiyor; kapatılsa kilitlenirdik."""
    await kullanici_ac("depocu", "DEPO")
    await _giris(client)

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["mfa_kurulumu_gerekli"] is True

    assert (await client.post("/api/auth/mfa/enroll")).status_code == 200


async def test_kurulum_bitince_kapi_acilir(client, kullanici_ac, mfa_zorunlu):
    import pyotp

    await kullanici_ac("depocu", "DEPO")
    await _giris(client)

    kayit = await client.post("/api/auth/mfa/enroll")
    sir = kayit.json()["secret"]
    kod = pyotp.TOTP(sir).now()
    assert (await client.post("/api/auth/mfa/confirm", json={"code": kod})).status_code == 200

    assert (await client.get("/api/cihazlar")).status_code == 200
    me = await client.get("/api/auth/me")
    assert me.json()["mfa_kurulumu_gerekli"] is False


async def test_zorunluyken_mfa_kapatilamaz(client, kullanici_ac, mfa_zorunlu):
    import pyotp

    await kullanici_ac("depocu", "DEPO")
    await _giris(client)
    sir = (await client.post("/api/auth/mfa/enroll")).json()["secret"]
    await client.post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(sir).now()})

    r = await client.post("/api/auth/mfa/disable", json={"password": "parola1234"})
    assert r.status_code == 409, "zorunluyken kapatılabilseydi zorunlu olmazdı"


async def test_giris_yaniti_kurulum_bayragini_tasir(client, kullanici_ac, mfa_zorunlu):
    """GİRİŞ yanıtı da `mfa_kurulumu_gerekli` taşımalı — /me ile aynı cevabı.

    Canlıda şu oldu: `/auth/me` bayrağı doğru döndürüyordu ama `UserOut.of()`
    onu hiç hesaplamıyordu, dolayısıyla GİRİŞ yanıtında `false` kalıyordu.
    Arayüz kullanıcıyı girişten sonra bu yanıttan kurduğu için uygulamanın
    içine düşüyor, ardından `/me` dışındaki her istek 403 alıyordu: eksiksiz
    bir menü, hiçbir şeyin açılmadığı bir ekran. Yalnız F5 sonrası (yani
    `/me` çağrılınca) kurulum ekranı geliyordu.
    """
    await kullanici_ac("depocu", "DEPO")

    giris = await _giris(client)
    assert giris.status_code == 200
    assert giris.json()["user"]["mfa_kurulumu_gerekli"] is True, (
        "giriş yanıtı kurulum gerektiğini söylemeli, yoksa arayüz kullanıcıyı içeri alır"
    )

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["mfa_kurulumu_gerekli"] is True
    assert me.json()["mfa_kurulumu_gerekli"] == giris.json()["user"]["mfa_kurulumu_gerekli"], (
        "iki uç aynı kuralı uygulamalı"
    )


async def test_mfa_kuruluysa_giris_kod_ister_ve_oturum_acilmaz(
    client, kullanici_ac, db, mfa_zorunlu
):
    """MFA kurulu kullanıcıda giriş yanıtı oturum AÇMAZ, kod ister.

    Bayrağın yanlışlıkla True kalıp kullanıcıyı kurulum ekranına kilitlemediği
    de burada görülür: bu yolda kullanıcı nesnesi hiç dönmez.
    """
    from sqlalchemy import select

    from app.models import User

    await kullanici_ac("depocu", "DEPO")
    kullanici = await db.scalar(select(User).where(User.username == "depocu"))
    kullanici.mfa_enabled = True
    kullanici.totp_secret = "JBSWY3DPEHPK3PXP"
    await db.commit()

    govde = (await _giris(client)).json()
    assert govde["mfa_required"] is True
    assert govde["user"] is None, "kod doğrulanmadan kullanıcı dönmemeli"
    assert govde["pending_token"]
