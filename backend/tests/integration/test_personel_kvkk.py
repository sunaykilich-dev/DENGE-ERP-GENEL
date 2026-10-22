"""Ayrılmış personelin KVKK anonimleştirmesi (TS-165; E13-D03).

- Yalnız `kvkk.yonet` (ADMIN); İK 403. Elle yapılır, otomatik silme yok.
- Yalnız ayrılmış personel; çalışan personel 409, ikinci kez 409, onaysız 400.
- Kayıt ve ad iş geçmişi için KALIR; not, e-posta, ayrılış nedeni temizlenir.
- Denetim satırlarında değerler maskelenir, olay korunur; erişim kayıtları
  (`kisisel.eris`) korunur.
- Personel değişikliği denetime kişisel veri olarak yazılır.
- Veri bulma (ilgili kişi başvurusu) personel kaydını da bulur.
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, User, UserUnit
from app.services import auth as auth_service
from app.services import kvkk

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    cevap = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert cevap.status_code == 200, cevap.text


async def _taze(db, kimlik: int) -> User:
    kisi = await db.get(User, kimlik)
    await db.refresh(kisi)
    return kisi


@pytest.fixture
async def ortam(client, db, kullanici_ac):
    await kullanici_ac("ik_uzmani", "IK")
    await kullanici_ac("kvkk_admin", "ADMIN")
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
    kisi = User(
        full_name="Gizli Personel",
        username="gizli.personel",
        email="gizli.personel@example.com",
        password_hash=auth_service.hash_password("parola1234"),
        role_id=rol.id,
        giris_acik=False,
        saha_rolu="TEKNISYEN",
        sicil_no="KV-1",
        ise_giris_tarihi=date(2024, 1, 1),
        personel_notu="Sağlık raporu nedeniyle hafif iş",
    )
    db.add(kisi)
    await db.commit()
    db.add(UserUnit(user_id=kisi.id, birim="GUVENLIK", is_primary=True))
    await db.commit()
    return {"id": kisi.id, "surum": kisi.version}


async def _cikar(client, o) -> None:
    r = await client.post(
        f"/api/personel/{o['id']}/cikis",
        json={"ayrilis_tarihi": "2026-01-10", "ayrilis_nedeni": "FESIH", "version": o["surum"]},
    )
    assert r.status_code == 200, r.text


GOVDE = {"gerekce": "KVKK başvurusu 2026/7", "onay": True}


class TestYetki:
    async def test_ik_403_admin_200(self, client, db, ortam):
        await _giris(client, "ik_uzmani")
        await _cikar(client, ortam)
        yol = f"/api/personel/{ortam['id']}/anonimlestir"
        assert (await client.post(yol, json=GOVDE)).status_code == 403
        await _giris(client, "kvkk_admin")
        r = await client.post(yol, json=GOVDE)
        assert r.status_code == 200, r.text


class TestKurallar:
    async def test_calisan_personel_409_ve_degismez(self, client, db, ortam):
        await _giris(client, "kvkk_admin")
        r = await client.post(f"/api/personel/{ortam['id']}/anonimlestir", json=GOVDE)
        assert r.status_code == 409
        kisi = await _taze(db, ortam["id"])
        assert kisi.personel_notu is not None and kisi.email is not None

    async def test_onaysiz_400_ikinci_kez_409(self, client, ortam):
        await _giris(client, "kvkk_admin")
        await _cikar(client, ortam)
        yol = f"/api/personel/{ortam['id']}/anonimlestir"
        assert (await client.post(yol, json={**GOVDE, "onay": False})).status_code == 400
        assert (await client.post(yol, json=GOVDE)).status_code == 200
        assert (await client.post(yol, json=GOVDE)).status_code == 409


class TestAnonimlestirme:
    async def test_kisisel_alanlar_temizlenir_kayit_ve_ad_kalir(self, client, db, ortam):
        await _giris(client, "kvkk_admin")
        # Kart okuması erişim kaydı üretir (korunmalı).
        assert (await client.get(f"/api/personel/{ortam['id']}")).status_code == 200
        await _cikar(client, ortam)
        r = await client.post(f"/api/personel/{ortam['id']}/anonimlestir", json=GOVDE)
        assert r.status_code == 200, r.text
        sonuc = r.json()
        assert set(sonuc["temizlenen_alanlar"]) >= {"personel_notu", "email", "ayrilis_nedeni"}
        assert sonuc["denetim_satiri"] >= 1

        kisi = await _taze(db, ortam["id"])
        assert kisi.full_name == "Gizli Personel"  # iş geçmişi için kalır
        assert kisi.personel_notu is None
        assert kisi.email is None
        assert kisi.ayrilis_nedeni == "DIGER"  # FESİH görünmez; tarih kalır
        assert kisi.ayrilis_tarihi == date(2026, 1, 10)

        satirlar = (
            await db.scalars(
                select(AuditLog)
                .where(AuditLog.entity == "users", AuditLog.entity_id == str(ortam["id"]))
                .execution_options(populate_existing=True)
            )
        ).all()
        cikis = next(s for s in satirlar if s.action == "personel.cikis")
        assert cikis.new_value == kvkk.DEGER_SILINDI  # olay durur, değer gider
        assert "FESIH" not in str(cikis.old_value) + str(cikis.new_value)
        erisim = [s for s in satirlar if s.action == "kisisel.eris"]
        assert erisim and all(s.new_value == {"amac": "personel kartı"} for s in erisim)
        kayit = next(s for s in satirlar if s.action == kvkk.PERSONEL_ANONIM_EYLEMI)
        assert kayit.is_personal_data is True

        # Anonimleştirilmiş personelin kartı notu/nedeni göstermez.
        kart = (await client.get(f"/api/personel/{ortam['id']}")).json()
        assert kart["personel_notu"] is None and kart["ayrilis_nedeni"] == "DIGER"


class TestDenetimVeVeriBulma:
    async def test_personel_degisikligi_kisisel_veri_olarak_denetlenir(self, client, db, ortam):
        await _giris(client, "ik_uzmani")
        r = await client.patch(
            f"/api/personel/{ortam['id']}", json={"unvan": "Kıdemli", "version": ortam["surum"]}
        )
        assert r.status_code == 200, r.text
        kisisel = await db.scalar(
            select(AuditLog.is_personal_data).where(
                AuditLog.action == "personel.guncelle", AuditLog.entity_id == str(ortam["id"])
            )
        )
        assert kisisel is True

    async def test_veri_bul_personeli_bulur(self, db, ortam):
        sonuc = await kvkk.veri_bul(db, "gizli personel")
        assert [p["id"] for p in sonuc["personel"]] == [ortam["id"]]
        sonuc = await kvkk.veri_bul(db, "KV-1")
        assert sonuc["personel"][0]["ayrildi"] is False


async def test_veri_dokumu_xlsx_personel_satiri(client, ortam):
    """İlgili kişiye verilen döküm (veri-bul.xlsx) personel kaydını da içerir."""
    from io import BytesIO

    from openpyxl import load_workbook

    await _giris(client, "kvkk_admin")
    r = await client.get("/api/kvkk/veri-bul.xlsx", params={"arama": "gizli.personel@example.com"})
    assert r.status_code == 200, r.text
    sayfa = load_workbook(BytesIO(r.content)).active
    satirlar = [[h.value for h in s] for s in sayfa.iter_rows(min_row=2)]
    personel = [s for s in satirlar if s[0] == "Personel"]
    assert personel and personel[0][1] == ortam["id"]
    assert "KV-1" in personel[0][2] and personel[0][4] == "gizli.personel@example.com"
