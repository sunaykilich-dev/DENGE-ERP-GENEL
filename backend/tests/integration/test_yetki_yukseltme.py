"""Yetki yükseltme önlemi (TS-006, E13-01 revised (1)–(8)).

Gerçek hikâye: `sistem.kullanici` sahibi başkasına ADMIN rolü, istisnayla
`sistem.denetim` ya da kendisinde olmayan izinlerle yeni rol verebiliyordu;
ADMIN rolünün izinleri boşaltılabiliyordu (herkes kilitlenir) ve son yönetici
kapatılabiliyordu. Bugün `sistem.kullanici` yalnız ADMIN'de olduğu için
"ADMIN olmayan aktör" senaryoları, eski kurulumda elle açılmış bir özel rolle
(API'yi atlayarak, doğrudan DB'de) kurulur — savunma tam bu durum için var.
"""

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models import AuditLog, Role, RolePermission, User, UserPermission

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


async def _ret_kaydi(db, entity: str) -> AuditLog | None:
    return await db.scalar(
        select(AuditLog).where(AuditLog.entity == entity, AuditLog.action == "yetki.ret")
    )


@pytest_asyncio.fixture
async def eski_kullanici_yoneticisi(seeded, db, kullanici_ac):
    """Eski kurulumda elle açılmış, `sistem.kullanici` taşıyan ADMIN olmayan rol."""
    rol = Role(code="KULLANICI_YON", name="Kullanıcı Yöneticisi", scope="TUMU", is_system=False)
    db.add(rol)
    await db.flush()
    for kod in ("sistem.kullanici", "cihaz.gor", "gorev.gor"):
        db.add(RolePermission(role_id=rol.id, permission_code=kod))
    await db.commit()
    return await kullanici_ac("kyon", "KULLANICI_YON")


# --- (1) Yüksek yetkili izinler yalnız ADMIN rolünde --------------------------


async def test_ozel_rol_yuksek_yetkili_izinle_acilamaz_ve_ret_denetime_yazilir(
    client, kullanici_ac, db
):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.post(
        "/api/roller",
        json={"code": "DENETCI", "name": "Denetçi", "izinler": ["sistem.denetim", "cihaz.gor"]},
    )
    assert r.status_code == 403
    assert "sistem.denetim" in r.json()["detail"]
    assert await db.scalar(select(Role).where(Role.code == "DENETCI")) is None
    kayit = await _ret_kaydi(db, "roles")
    assert kayit is not None and kayit.new_value["izinler"] == ["sistem.denetim"]


async def test_mevcut_role_yuksek_yetkili_izin_eklenemez(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    mevcut = [i["kod"] for i in (await client.get("/api/roller/DEPO/yetkiler")).json()["izinler"]]
    r = await client.patch("/api/roller/DEPO", json={"izinler": [*mevcut, "kvkk.yonet"]})
    assert r.status_code == 403
    rol = await db.scalar(select(Role).where(Role.code == "DEPO"))
    await db.refresh(rol)
    assert rol.ozellestirildi is False, "ret yazma yapmamalı"


async def test_yuksek_yetkili_istisna_verilemez(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "sistem.denetim", "allow": True, "gerekce": "denetim için"}],
    )
    assert r.status_code == 403
    kalan = (
        await db.scalars(select(UserPermission).where(UserPermission.user_id == hedef.id))
    ).all()
    assert kalan == []
    assert await _ret_kaydi(db, "users") is not None


# --- (2) ADMIN rolünü yalnız ADMIN atar ----------------------------------------


async def test_admin_olmayan_aktor_admin_rolu_veremez(
    client, eski_kullanici_yoneticisi, kullanici_ac, db
):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "kyon")

    r = await client.post(
        "/api/kullanicilar",
        json={
            "full_name": "Yeni",
            "username": "yeni",
            "password": "parola1234",
            "role_code": "ADMIN",
        },
    )
    assert r.status_code == 403
    assert await db.scalar(select(User).where(User.username == "yeni")) is None

    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"role_code": "ADMIN"})
    assert r.status_code == 403
    await db.refresh(hedef)
    rol = await db.get(Role, hedef.role_id)
    assert rol.code == "DEPO"


async def test_admin_olmayan_aktor_sahip_olmadigi_izni_veremez(
    client, eski_kullanici_yoneticisi, kullanici_ac
):
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "kyon")
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "hakedis.gor", "allow": True, "gerekce": "ay sonu"}],
    )
    assert r.status_code == 403
    # Kısma her zaman serbest.
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "cihaz.transfer", "allow": False, "gerekce": "geçici kısıt"}],
    )
    assert r.status_code == 200, r.text


async def test_admin_aktor_admin_rolu_atayabilir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"role_code": "ADMIN"})
    assert r.status_code == 200
    assert r.json()["role"]["code"] == "ADMIN"


# --- (3) ADMIN rolü katalogdan yönetilir --------------------------------------


async def test_admin_rolu_duzenlenemez(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.patch("/api/roller/ADMIN", json={"izinler": ["cihaz.gor"]})
    assert r.status_code == 409
    rol = await db.scalar(select(Role).where(Role.code == "ADMIN"))
    await db.refresh(rol)
    assert len(rol.permissions) > 1, "izinler boşaltılmamalı"
    assert (await _ret_kaydi(db, "roles")) is not None


async def test_seed_ozellestirilmis_admin_rolunu_katalogla_esitler(seeded):
    from app.permissions import PERMISSIONS
    from app.seeds.dev import sync_roles

    db = seeded
    rol = await db.scalar(select(Role).where(Role.code == "ADMIN"))
    rol.ozellestirildi = True
    await db.execute(
        delete(RolePermission).where(
            RolePermission.role_id == rol.id, RolePermission.permission_code == "personel.gor"
        )
    )
    await db.commit()

    await sync_roles(db)
    await db.commit()
    await db.refresh(rol)
    assert rol.ozellestirildi is False
    assert {rp.permission_code for rp in rol.permissions} == set(PERMISSIONS)


# --- (4) Son aktif ADMIN -------------------------------------------------------


async def test_son_aktif_admin_kapatilamaz(client, eski_kullanici_yoneticisi, kullanici_ac, db):
    tek = await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "kyon")
    for govde in ({"is_active": False}, {"giris_acik": False}, {"role_code": "DEPO"}):
        r = await client.patch(f"/api/kullanicilar/{tek.id}", json=govde)
        assert r.status_code == 409, govde
    await db.refresh(tek)
    assert tek.is_active and tek.giris_acik
    assert (await db.get(Role, tek.role_id)).code == "ADMIN"


async def test_birden_fazla_admin_varken_biri_kapatilabilir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    ikinci = await kullanici_ac("yonetici2", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{ikinci.id}", json={"is_active": False})
    assert r.status_code == 200


# --- (5) Üst yetkili hedef ------------------------------------------------------


async def test_admin_olmayan_aktor_ust_yetkili_hedefe_dokunamaz(
    client, eski_kullanici_yoneticisi, kullanici_ac, db
):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("yonetici2", "ADMIN")
    await _giris(client, "kyon")
    for govde in ({"is_active": False}, {"password": "yeni-parola-1"}, {"full_name": "Başka"}):
        r = await client.patch(f"/api/kullanicilar/{hedef.id}", json=govde)
        assert r.status_code == 403, govde
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "cihaz.gor", "allow": False, "gerekce": "kısıtlama"}],
    )
    assert r.status_code == 403
    await db.refresh(hedef)
    assert hedef.is_active and hedef.full_name == "Yonetici2"


# --- (7) Kapsam doğrulaması ve birim zorunluluğu -------------------------------


async def test_birim_kapsamli_rolde_birimsiz_hesap_acilamaz(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    govde = {
        "full_name": "Şef",
        "username": "sef",
        "password": "parola1234",
        "role_code": "SERVIS_SEF",
    }
    r = await client.post("/api/kullanicilar", json=govde)
    assert r.status_code == 400
    assert "en az bir birim" in r.json()["detail"]

    r = await client.post("/api/kullanicilar", json={**govde, "birimler": ["UYDURMA"]})
    assert r.status_code == 400

    r = await client.post("/api/kullanicilar", json={**govde, "birimler": ["POC", "GUVENLIK"]})
    assert r.status_code == 201, r.text
    assert r.json()["birimler"] == ["GUVENLIK", "POC"]
    assert r.json()["birincil_birim"] == "GUVENLIK"
    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "users", AuditLog.action == "olustur")
    )
    assert kayit.new_value["birimler"] == ["GUVENLIK", "POC"]


async def test_birimsiz_kullanici_birim_kapsamli_role_tasinamaz(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{hedef.id}", json={"role_code": "SERVIS_TEKNISYEN"})
    assert r.status_code == 400
    await db.refresh(hedef)
    assert (await db.get(Role, hedef.role_id)).code == "DEPO"


async def test_kimse_kendi_girisini_kapatamaz(client, kullanici_ac):
    admin = await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.patch(f"/api/kullanicilar/{admin.id}", json={"giris_acik": False})
    assert r.status_code == 400


# --- Liste: rolünden sapma (E13-10) ------------------------------------------


async def test_kullanici_listesi_sapma_sayisini_gosterir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "hakedis.gor", "allow": True, "gerekce": "ay sonu kontrolü"}],
    )
    satirlar = {k["username"]: k for k in (await client.get("/api/kullanicilar")).json()}
    assert satirlar["depocu"]["sapma_sayisi"] == 1
    assert satirlar["yonetici"]["sapma_sayisi"] == 0
    assert satirlar["depocu"]["rol_ozellestirildi"] is False
