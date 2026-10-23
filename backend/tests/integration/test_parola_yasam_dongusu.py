"""Parola ve giriş yaşam döngüsü (TS-212, E13-13).

Gerçek hikâye: yöneticinin belirlediği parola kalıcıydı (yönetici kullanıcının
parolasını biliyordu), kullanıcının kendi parolasını değiştireceği uç yoktu,
ilk kurulum parolası değiştirilmeden kullanılıyordu. Kilitli hesap 423 ile
ayrı bildirildiği ve var olmayan kullanıcıda argon2 hiç koşmadığı için hem
yanıt kodu hem yanıt süresi "bu kullanıcı adı var" diyordu.
"""

import os
import time

import httpx
import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Session, User

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def _ikinci_istemci():
    from app.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )


async def _zorunlu(db, kullanici: User, parola_degismeli: bool = True) -> None:
    kullanici.parola_degismeli = parola_degismeli
    await db.commit()


async def test_parola_degismeli_hesap_yalniz_muaf_yollara_erisir(client, kullanici_ac, db):
    kisi = await kullanici_ac("depocu", "DEPO")
    await _zorunlu(db, kisi)
    assert (await _giris(client, "depocu")).status_code == 200

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["parola_degismeli"] is True

    r = await client.get("/api/hesaplar")
    assert r.status_code == 403
    assert r.json()["detail"]["kod"] == "PAROLA_DEGISMELI"


async def test_parola_degistir_yanlis_mevcut_400_ve_sayaca_yazilir(client, kullanici_ac, db):
    await kullanici_ac("depocu", "DEPO")
    await _giris(client, "depocu")
    r = await client.post(
        "/api/auth/parola", json={"mevcut": "yanlis", "yeni": "cokguclu-parola-42"}
    )
    assert r.status_code == 400
    assert "Mevcut parola" in r.json()["detail"]
    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "parola.degistir_basarisiz"))
    assert kayit is not None and kayit.new_value == {"kilitlendi": False}


async def test_parola_degistirmede_bes_yanlis_mevcut_hesabi_kilitler_ve_oturumu_dusurur(
    client, kullanici_ac
):
    """Çalınmış oturumla parola denemesi de brute-force'tur."""
    await kullanici_ac("depocu", "DEPO")
    await _giris(client, "depocu")
    for _ in range(4):
        r = await client.post(
            "/api/auth/parola", json={"mevcut": "x", "yeni": "cokguclu-parola-42"}
        )
        assert r.status_code == 400
    r = await client.post("/api/auth/parola", json={"mevcut": "x", "yeni": "cokguclu-parola-42"})
    assert r.status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await _giris(client, "depocu")).status_code == 401  # kilitli


@pytest.mark.parametrize(
    ("yeni", "parca"),
    [
        ("kisa1234", "en az 10"),
        ("depocu-parolasi-1", "kullanıcı adınızı"),
        ("parola1234", "farklı"),
    ],
)
async def test_yeni_parola_kurallari(client, kullanici_ac, yeni, parca):
    await kullanici_ac("depocu", "DEPO")
    await _giris(client, "depocu")
    r = await client.post("/api/auth/parola", json={"mevcut": "parola1234", "yeni": yeni})
    assert r.status_code == 400
    assert parca in r.json()["detail"]


async def test_degisim_sonrasi_diger_oturumlar_duser_bu_oturum_kalir(client, kullanici_ac, db):
    kisi = await kullanici_ac("depocu", "DEPO")
    await _zorunlu(db, kisi)
    ikinci = await _ikinci_istemci()
    try:
        assert (await _giris(ikinci, "depocu")).status_code == 200
        assert (await _giris(client, "depocu")).status_code == 200

        r = await client.post(
            "/api/auth/parola", json={"mevcut": "parola1234", "yeni": "yepyeni-parola-77"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["parola_degismeli"] is False

        assert (await client.get("/api/hesaplar")).status_code == 200  # bu oturum sürer
        assert (await ikinci.get("/api/auth/me")).status_code == 401  # diğeri düştü
    finally:
        await ikinci.aclose()

    await db.refresh(kisi)
    assert kisi.parola_degismeli is False
    assert kisi.parola_degisti_at is not None
    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "parola.degistir"))
    assert kayit is not None and kayit.new_value is None  # parola değeri yok
    await client.post("/api/auth/logout")
    assert (await _giris(client, "depocu", "yepyeni-parola-77")).status_code == 200


async def test_gecici_parola_bir_kez_doner_denetimde_yok_72_saat_sonra_401(
    client, kullanici_ac, db
):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"parola_sifirla": True})
    assert r.status_code == 200, r.text
    gecici = r.json()["gecici_parola"]
    assert gecici and len(gecici) >= 10
    assert r.json()["parola_degismeli"] is True

    # Liste ve tekrar okuma geçici parolayı taşımaz; denetim kaydında yok.
    liste = (await client.get("/api/kullanicilar")).text
    assert gecici not in liste
    kayitlar = (await db.scalars(select(AuditLog))).all()
    assert gecici not in str([(k.old_value, k.new_value) for k in kayitlar])

    await client.post("/api/auth/logout")
    assert (await _giris(client, "depocu")).status_code == 401  # eski parola geçmez
    client.clock.advance(hours=72, seconds=1)
    assert (await _giris(client, "depocu", gecici)).status_code == 401  # süresi doldu


async def test_gecici_parola_tek_seferlik(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    gecici = (
        await client.patch(f"/api/kullanicilar/{hedef.id}", json={"parola_sifirla": True})
    ).json()["gecici_parola"]
    await client.post("/api/auth/logout")

    assert (await _giris(client, "depocu", gecici)).status_code == 200
    assert (await client.get("/api/hesaplar")).status_code == 403  # önce değiştir
    await client.post("/api/auth/logout")
    client.clock.advance(minutes=1)
    # Değiştirmeden çıkan kullanıcı aynı geçici parolayla bir daha giremez.
    assert (await _giris(client, "depocu", gecici)).status_code == 401


async def test_yonetici_belirledigi_parola_da_zorunlu_degisim_ister(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"password": "yonetici-verdi-1"})
    assert r.status_code == 200
    assert r.json()["gecici_parola"] is None  # yönetici zaten biliyor; geri dönülmez
    await db.refresh(hedef)
    assert hedef.parola_degismeli is True and hedef.gecici_parola_bitis is not None

    r = await client.post(
        "/api/kullanicilar",
        json={
            "full_name": "Yeni Kişi",
            "username": "yeni",
            "password": "acilis-parolasi",
            "role_code": "DEPO",
        },
    )
    assert r.status_code == 201
    assert r.json()["parola_degismeli"] is True


async def test_yonetici_kendi_parolasini_kullanici_yonetiminden_degistiremez(client, kullanici_ac):
    admin = await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{admin.id}", json={"parola_sifirla": True})
    assert r.status_code == 400


async def test_ilk_yonetici_zorunlu_degisimle_acilir(db, seeded):
    from app.seeds.dev import ensure_admin

    parola = await ensure_admin(db, "İlk Yönetici")
    await db.commit()
    assert parola
    admin = await db.scalar(select(User).where(User.username == "admin"))
    assert admin.parola_degismeli is True
    assert admin.gecici_parola_bitis is None  # kurulum parolası süreye bağlı değil


async def test_kilitli_ve_olmayan_kullanici_ayni_yanit(client, kullanici_ac, db):
    await kullanici_ac("depocu", "DEPO")
    for _ in range(5):
        await _giris(client, "depocu", "yanlis")
    kilitli = await _giris(client, "depocu")
    olmayan = await _giris(client, "hic-olmayan-kisi")
    yanlis = await _giris(client, "depocu", "baska-yanlis")
    assert kilitli.status_code == olmayan.status_code == yanlis.status_code == 401
    assert kilitli.json() == olmayan.json() == yanlis.json()
    # Var olmayan kullanıcı için kilit satırı açılmaz (tablo şişirilemez).
    from app.models import LoginAttempt

    assert await db.get(LoginAttempt, "hic-olmayan-kisi") is None
    # Kilit bilgisi denetimde görünür.
    kayit = await db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "giris.basarisiz")
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    assert kayit is not None


async def test_argon2_her_durumda_kosar(client, kullanici_ac, db, monkeypatch):
    """Sabit zamanlama: var olmayan, pasif, girişi kapalı ve kilitli hesapta da
    parola özeti doğrulanır (yanıt süresi kullanıcı adını ele vermesin)."""
    from app.services import auth as auth_service

    pasif = await kullanici_ac("pasif", "DEPO")
    pasif.is_active = False
    await db.commit()
    await kullanici_ac("kilitli", "DEPO")
    for _ in range(5):
        await _giris(client, "kilitli", "yanlis")

    cagri: list[str] = []
    gercek = auth_service.verify_password

    def _say(plain, ozet):
        cagri.append(plain)
        return gercek(plain, ozet)

    monkeypatch.setattr(auth_service, "verify_password", _say)
    for ad in ("yok-boyle-biri", "pasif", "kilitli"):
        cagri.clear()
        assert (await _giris(client, ad)).status_code == 401
        assert cagri, f"{ad}: argon2 koşmadı"


@pytest.mark.skipif(
    os.getenv("ZAMANLAMA_TESTI") != "1", reason="yavaş ölçüm; ZAMANLAMA_TESTI=1 ile koşar"
)
async def test_yanit_suresi_kullanici_varligini_ele_vermez(client, kullanici_ac, db):
    """Var olmayan / pasif / yanlış parolalı: ortalama süre farkı < %20 (100 deneme)."""
    pasif = await kullanici_ac("pasif", "DEPO")
    pasif.is_active = False
    await db.commit()
    await kullanici_ac("gercek", "DEPO")

    async def _ortalama(ad: str) -> float:
        sureler = []
        for i in range(100):
            bas = time.perf_counter()
            await _giris(client, ad, f"yanlis-{i}")
            sureler.append(time.perf_counter() - bas)
            # Sayaç 5'te kilitler; ölçüm kilidin kendisini değil doğrulamayı sınar.
            if i % 4 == 3:
                from app.services import auth as auth_service

                await auth_service.reset_login_attempts(db, ad)
                await db.commit()
        return sum(sureler) / len(sureler)

    ortalamalar = [await _ortalama(a) for a in ("olmayan-kisi", "pasif", "gercek")]
    assert max(ortalamalar) / min(ortalamalar) < 1.2, ortalamalar


async def test_giris_son_giris_anini_yazar(client, kullanici_ac, db):
    kisi = await kullanici_ac("depocu", "DEPO")
    assert (await _giris(client, "depocu")).status_code == 200
    await db.refresh(kisi)
    assert kisi.son_giris_at == client.clock.now()
    assert await db.scalar(select(func.count()).select_from(Session)) == 1
