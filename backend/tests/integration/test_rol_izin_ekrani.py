"""Rol–izin düzenleme ekranı (kullanıcı isteği 2026-11-09).

"Erişilebilen sayfalar ve izin verilen aksiyonlar düzenlenebilsin admin
tarafından." İzin kataloğu kodda kalır (`permissions.py`); yönetici yalnız rol →
izin eşlemesini değiştirir. Sınananlar: izin kaldırılınca uç 403 ve sayfa
(menü kaynağı `/api/auth/me` izinleri, rol sayfa listesi) kaybolur; iyimser
kilit; ADMIN koruması; denetimde eklenen/çıkarılan; varsayılana dönüş;
hassas izin işareti ve iznin açtığı sayfalar.
"""

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from app.permissions import ROLES

pytestmark = pytest.mark.integration


@pytest.fixture
async def giris(client):
    from app.main import app

    acik: list[httpx.AsyncClient] = []

    async def _ac(username: str) -> httpx.AsyncClient:
        ist = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Requested-With": "fetch"},
        )
        r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
        assert r.status_code == 200, r.text
        acik.append(ist)
        return ist

    yield _ac
    for ist in acik:
        await ist.aclose()


@pytest.fixture
async def o(kullanici_ac, birimli_kullanici_ac, giris):
    await kullanici_ac("yonetici", "ADMIN")
    await birimli_kullanici_ac("tekn", "SERVIS_TEKNISYEN", ["GUVENLIK"])

    class O:
        pass

    x = O()
    x.admin = await giris("yonetici")
    return x


async def _yetki(ist, kod="SERVIS_TEKNISYEN") -> dict:
    r = await ist.get(f"/api/roller/{kod}/yetkiler")
    assert r.status_code == 200, r.text
    return r.json()


async def test_izin_kaldirilinca_uc_403_ve_sayfa_kaybolur(o, giris, db) -> None:
    tekn = await giris("tekn")
    assert (await tekn.get("/api/teknik-servis/parca/depolar")).status_code == 200
    y = await _yetki(o.admin)
    assert "Yedek Parça" in y["sayfalar"] and y["varsayilana_donebilir"] is True
    izinler = [i["kod"] for i in y["izinler"] if i["kod"] not in ("parca.gor", "parca.kullan")]

    r = await o.admin.patch(
        "/api/roller/SERVIS_TEKNISYEN", json={"izinler": izinler, "version": y["version"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["ozellestirildi"] is True and r.json()["version"] > y["version"]

    # Oturum düştü (yeni yetki hemen geçerli); yeniden girişte uç 403, menü izni yok.
    assert (await tekn.get("/api/auth/me")).status_code == 401
    tekn = await giris("tekn")
    assert (await tekn.get("/api/teknik-servis/parca/depolar")).status_code == 403
    assert "parca.gor" not in (await tekn.get("/api/auth/me")).json()["permissions"]
    assert "Yedek Parça" not in (await _yetki(o.admin))["sayfalar"]

    # Denetim: kim, hangi rol, eklenen/çıkarılan.
    kayit = await db.scalar(
        select(AuditLog)
        .where(AuditLog.entity == "roles", AuditLog.action == "guncelle")
        .order_by(AuditLog.id.desc())
    )
    assert kayit.new_value["cikarilan"] == ["parca.gor", "parca.kullan"]
    assert kayit.new_value["eklenen"] == []
    assert kayit.new_value["etkilenen_kullanici"] == 1


async def test_iyimser_kilit_409(o) -> None:
    y = await _yetki(o.admin)
    kodlar = [i["kod"] for i in y["izinler"]]
    r = await o.admin.patch(
        "/api/roller/SERVIS_TEKNISYEN", json={"izinler": kodlar[:-1], "version": y["version"]}
    )
    assert r.status_code == 200, r.text
    # Eski sürümle ikinci kayıt: 409, değişiklik yazılmaz.
    r = await o.admin.patch(
        "/api/roller/SERVIS_TEKNISYEN", json={"izinler": kodlar, "version": y["version"]}
    )
    assert r.status_code == 409
    assert len((await _yetki(o.admin))["izinler"]) == len(kodlar) - 1


async def test_admin_rolu_korunur(o) -> None:
    r = await o.admin.patch("/api/roller/ADMIN", json={"izinler": ["servis.gor"]})
    assert r.status_code == 409
    r = await o.admin.post("/api/roller/ADMIN/varsayilan", json={})
    assert r.status_code == 409
    assert (await _yetki(o.admin, "ADMIN"))["varsayilana_donebilir"] is False
    # Yönetici hâlâ kullanıcı yönetebilir (kendini dışarıda bırakmadı).
    assert (await o.admin.get("/api/kullanicilar")).status_code == 200


async def test_varsayilana_donus(o, giris, db) -> None:
    y = await _yetki(o.admin)
    r = await o.admin.patch(
        "/api/roller/SERVIS_TEKNISYEN",
        json={"izinler": ["servis.gor", "takip.gor"], "version": y["version"]},
    )
    assert r.status_code == 200, r.text
    r = await o.admin.post(
        "/api/roller/SERVIS_TEKNISYEN/varsayilan", json={"version": r.json()["version"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["ozellestirildi"] is False
    y = await _yetki(o.admin)
    assert {i["kod"] for i in y["izinler"]} == set(ROLES["SERVIS_TEKNISYEN"][1])
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
    await db.refresh(rol)
    assert rol.ozellestirildi is False
    kayit = await db.scalar(
        select(AuditLog)
        .where(AuditLog.entity == "roles", AuditLog.action == "varsayilana_don")
        .order_by(AuditLog.id.desc())
    )
    assert "takip.gor" in kayit.new_value["cikarilan"]
    assert "parca.gor" in kayit.new_value["eklenen"]
    tekn = await giris("tekn")
    assert (await tekn.get("/api/teknik-servis/parca/depolar")).status_code == 200


async def test_izin_katalogu_hassas_ve_sayfalar(o) -> None:
    r = await o.admin.get("/api/izinler")
    assert r.status_code == 200
    izin = {i["kod"]: i for i in r.json()}
    assert izin["maliyet.gor"]["hassas"] is True and izin["bordro.yonet"]["hassas"] is True
    assert izin["parca.gor"]["hassas"] is False
    assert izin["parca.gor"]["sayfalar"] == ["Yedek Parça"]
    assert "Planlama" in izin["takip.gor"]["sayfalar"]


async def test_yonetici_olmayan_rol_duzenleyemez(o, giris) -> None:
    tekn = await giris("tekn")
    assert (await tekn.patch("/api/roller/SERVIS_TEKNISYEN", json={"izinler": []})).status_code == 403
    assert (await tekn.post("/api/roller/SERVIS_TEKNISYEN/varsayilan", json={})).status_code == 403
