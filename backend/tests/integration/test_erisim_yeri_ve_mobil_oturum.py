"""Erişim yeri ve istemci türüne göre oturum süresi (KARARLAR 2026-10-28 §7 Faz A/8).

G3.8 — "saha her yerden, muhasebe yalnız ofisten": `roles.yalniz_ofis`
işaretli rol (varsayılan MUHASEBE_DESTEK) `ofis_ag_listesi` dışındaki IP'den
giriş yapamaz ve kimlikli istek atamaz (403 + `OFIS_DISI_ERISIM`). Liste boşsa
kısıt yok. IP `request.client.host`'tur (vekil başlığını uvicorn güvenilen
vekilden çözer); uygulama X-Forwarded-For'a bakmaz — testte sahte başlık
kısıtı AŞAMAMALI.

G3.7 — "masaüstünde kısa, mobilde uzun oturum": giriş isteğindeki
`istemci: "mobil"` ipucuyla oturum 12 sa hareketsizlik / 24 sa mutlak süre
alır; masaüstü 4 sa / 12 sa kalır. Süreyi sunucu seçer.
"""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, Setting, User
from app.models import Session as OturumModel
from app.services import auth as auth_service

pytestmark = pytest.mark.integration

OFIS_IP = "10.10.5.20"
DIS_IP = "203.0.113.7"


def _istemci(ip: str) -> httpx.AsyncClient:
    """Belirli bir kaynak IP'den gelen istemci (`client` fikstürünün DB/saat
    geçersiz kılmaları açıkken kullanılır)."""
    from app.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(ip, 51000)),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )


async def _giris(ist: httpx.AsyncClient, username: str, **ek) -> httpx.Response:
    return await ist.post(
        "/api/auth/login", json={"username": username, "password": "parola1234", **ek}
    )


async def _ofis_agi(db, *aglar: str) -> None:
    db.add(Setting(key="ofis_ag_listesi", value=list(aglar)))
    await db.commit()


# --- G3.8 ---------------------------------------------------------------------------


async def test_seed_muhasebe_rolunu_ofise_baglar(seeded) -> None:
    roller = {r.code: r.yalniz_ofis for r in (await seeded.scalars(select(Role))).all()}
    assert {k for k, v in roller.items() if v} == {"MUHASEBE_DESTEK", "FINANS_YONETICI"}  # §7.18


async def test_liste_bossa_muhasebe_her_yerden_girer(client, kullanici_ac) -> None:
    await kullanici_ac("muhasebe", "MUHASEBE_DESTEK")
    async with _istemci(DIS_IP) as ist:
        assert (await _giris(ist, "muhasebe")).status_code == 200
        assert (await ist.get("/api/auth/me")).status_code == 200


async def test_muhasebe_ofis_disindan_giremez_ofisten_girer(client, kullanici_ac, db) -> None:
    await kullanici_ac("muhasebe", "MUHASEBE_DESTEK")
    await _ofis_agi(db, "10.10.0.0/16")

    async with _istemci(DIS_IP) as ist:
        # Sahte vekil başlığı kısıtı aşamaz.
        r = await ist.post(
            "/api/auth/login",
            json={"username": "muhasebe", "password": "parola1234"},
            headers={"X-Forwarded-For": OFIS_IP, "X-Real-IP": OFIS_IP},
        )
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["kod"] == "OFIS_DISI_ERISIM"
        assert "ofis" in r.json()["detail"]["mesaj"]
        assert "dngerp_session" not in ist.cookies
    kisi = await db.scalar(select(User).where(User.username == "muhasebe"))
    assert await db.scalar(select(OturumModel).where(OturumModel.user_id == kisi.id)) is None
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "giris.ofis_disi"))
    # Doğru parola başarısız giriş sayılmaz (kilit sayacına yazılmaz).
    assert await auth_service.kilit_zamani(db, "muhasebe") is None

    async with _istemci(OFIS_IP) as ist:
        assert (await _giris(ist, "muhasebe")).status_code == 200
        assert (await ist.get("/api/auth/me")).status_code == 200


async def test_ofiste_acilan_oturum_disarida_calismaz(client, kullanici_ac, db) -> None:
    """Her kimlikli istek denetlenir: oturum çerezi dışarı taşınınca 403."""
    await kullanici_ac("muhasebe", "MUHASEBE_DESTEK")
    await _ofis_agi(db, "10.10.0.0/16")
    async with _istemci(OFIS_IP) as ofis:
        assert (await _giris(ofis, "muhasebe")).status_code == 200
        cerez = ofis.cookies.get("dngerp_session")
    async with _istemci(DIS_IP) as dis:
        dis.cookies.set("dngerp_session", cerez)
        r = await dis.get("/api/auth/me")
        assert r.status_code == 403
        assert r.json()["detail"]["kod"] == "OFIS_DISI_ERISIM"
        assert (await dis.get("/api/tahsilat")).status_code == 403
        # Çıkış her yerden yapılabilir.
        assert (await dis.post("/api/auth/logout")).status_code == 200


async def test_saha_ve_yonetici_rolleri_her_yerden(client, kullanici_ac, db) -> None:
    await kullanici_ac("teknisyen", "SERVIS_TEKNISYEN")
    await kullanici_ac("yonetici", "ADMIN")
    await _ofis_agi(db, "10.10.0.0/16")
    async with _istemci(DIS_IP) as ist:
        for ad in ("teknisyen", "yonetici"):
            assert (await _giris(ist, ad)).status_code == 200, ad
            assert (await ist.get("/api/auth/me")).status_code == 200, ad


async def test_rol_ekranindan_ofis_kisiti_acilir(client, kullanici_ac, db) -> None:
    await kullanici_ac("yonetici", "ADMIN")
    await kullanici_ac("depocu", "DEPO")
    await _ofis_agi(db, "10.10.0.0/16")
    async with _istemci(OFIS_IP) as ist:
        assert (await _giris(ist, "yonetici")).status_code == 200
        r = await ist.patch("/api/roller/DEPO", json={"yalniz_ofis": True})
        assert r.status_code == 200, r.text
        assert r.json()["yalniz_ofis"] is True
    async with _istemci(DIS_IP) as ist:
        assert (await _giris(ist, "depocu")).status_code == 403


async def test_ipv4_esli_ipv6_ve_bozuk_adres() -> None:
    from app.services.erisim_yeri import ag_icinde_mi

    assert ag_icinde_mi("::ffff:10.10.1.1", ["10.10.0.0/16"])
    assert not ag_icinde_mi("bozuk", ["10.10.0.0/16"])
    assert not ag_icinde_mi(None, ["10.10.0.0/16"])
    assert ag_icinde_mi("2001:db8::5", ["2001:db8::/32"])


# --- G3.7 ---------------------------------------------------------------------------


def test_mobil_sureleri_kod_sabiti() -> None:
    assert auth_service.SESSION_TTL_MOBIL == timedelta(hours=12)
    assert auth_service.SESSION_MAX_MOBIL == timedelta(hours=24)
    # Masaüstü değişmedi.
    assert auth_service.oturum_sureleri("MASAUSTU") == (timedelta(hours=4), timedelta(hours=12))
    assert auth_service.istemci_turu("mobil") == "MOBIL"
    for ipucu in (None, "", "masaustu", "tablet", "MOBIL-ama-degil"):
        assert auth_service.istemci_turu(ipucu) == "MASAUSTU"


async def test_mobil_oturum_uzun_masaustu_kisa(client, kullanici_ac, db) -> None:
    await kullanici_ac("teknisyen", "SERVIS_TEKNISYEN")
    async with _istemci(OFIS_IP) as mobil, _istemci(OFIS_IP) as masa:
        r = await _giris(mobil, "teknisyen", istemci="mobil")
        assert r.status_code == 200
        assert (await _giris(masa, "teknisyen", istemci="masaustu")).status_code == 200
        kisi = await db.scalar(select(User).where(User.username == "teknisyen"))
        turler = sorted(
            await db.scalars(select(OturumModel.istemci).where(OturumModel.user_id == kisi.id))
        )
        assert turler == ["MASAUSTU", "MOBIL"]

        # 5 saat hareketsizlik: masaüstü düşer, mobil kalır.
        client.clock.advance(hours=5)
        assert (await masa.get("/api/auth/me")).status_code == 401
        assert (await mobil.get("/api/auth/me")).status_code == 200

        # Mobilde de 12 saat hareketsizlik düşürür.
        client.clock.advance(hours=12, minutes=1)
        assert (await mobil.get("/api/auth/me")).status_code == 401


async def test_mobil_oturum_mutlak_24_saatte_duser(client, kullanici_ac) -> None:
    await kullanici_ac("teknisyen", "SERVIS_TEKNISYEN")
    async with _istemci(OFIS_IP) as mobil:
        assert (await _giris(mobil, "teknisyen", istemci="mobil")).status_code == 200
        for _ in range(23):
            client.clock.advance(hours=1)
            assert (await mobil.get("/api/auth/me")).status_code == 200
        client.clock.advance(hours=1)  # tam 24 saat
        assert (await mobil.get("/api/auth/me")).status_code == 401
