"""Personel toplu yükleme profili (TS-010; E13-04).

Gerçek personel listesi depoya GİRMEZ: liste depo dışındaki Excel'den canlı
İçe Aktarma çerçevesiyle yüklenir; örnek dosya (`tests/fixtures/
personel_ornek.xlsx`) SAHTE adlıdır. Kilitlenen kurallar:

- yeni kayıt girişsiz (`giris_acik=false`), rol SERVIS_TEKNISYEN, parola
  özeti rastgele bir sırrın GEÇERLİ argon2 özeti;
- eşleşme sicil no → kullanıcı adı; aynı dosya ikinci kez uygulanınca
  0 yeni satır (varsayılan karar "atla");
- güncelleme rol/izin/parola/girişe DOKUNMAZ; üst yetkili kullanıcıyla
  eşleşen satır hata olur;
- tahmin yazılmaz: saha rolü/birim yalnız açık sütundan.
"""

import io
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import Role, User
from app.services import imports as ice
from app.services.imports.personel import PersonelProfili

pytestmark = pytest.mark.integration

ORNEK = Path(__file__).resolve().parents[1] / "fixtures" / "personel_ornek.xlsx"


def _xlsx(satirlar: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for s in satirlar:
        ws.append(s)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def _onizle_ve_uygula(db, icerik: bytes, kararlar: dict[int, str] | None = None):
    profil = PersonelProfili()
    okuma = ice.oku("personel.xlsx", icerik, profil)
    staged = [s.sozluk() for s in await profil.dogrula(db, okuma.satirlar)]
    sayac = await profil.yaz(db, staged, clock=FakeClock(), user_id=None, kararlar=kararlar or {})
    await db.commit()
    return staged, sayac


async def _personel_sayisi(db) -> int:
    return int(await db.scalar(select(func.count()).select_from(User)) or 0)


class TestOrnekDosya:
    def test_ornek_dosya_sahte_adli(self):
        """Depoda gerçek ad yok: örnek dosyadaki bütün adlar 'Örnek' ile başlar."""
        profil = PersonelProfili()
        okuma = ice.oku("personel_ornek.xlsx", ORNEK.read_bytes(), profil)
        assert len(okuma.satirlar) == 4
        assert all(s["ad"].startswith("Örnek ") for s in okuma.satirlar)

    async def test_seed_personel_uretmez(self, seeded):
        """Migration ve seed yalnız rol/izin üretir; personel satırı yok."""
        assert await _personel_sayisi(seeded) == 0


class TestYukleme:
    async def test_yeni_kayitlar_girissiz_ve_dogru_rolde(self, seeded):
        db = seeded
        staged, sayac = await _onizle_ve_uygula(db, ORNEK.read_bytes())
        assert [s["hatalar"] for s in staged] == [[], [], [], []]
        assert sayac["eklendi"] == 4

        rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
        kisiler = (await db.scalars(select(User).order_by(User.id))).all()
        assert len(kisiler) == 4
        from app.services import auth as auth_service

        for k in kisiler:
            assert k.giris_acik is False
            assert k.role_id == rol.id
            assert k.password_hash.startswith("$argon2")
            assert auth_service.verify_password("parola1234", k.password_hash) is False

        sef = next(k for k in kisiler if k.sicil_no == "T-0001")
        assert sef.username == "p.t0001"
        assert sef.saha_rolu == "SEF"
        assert str(sef.ise_giris_tarihi) == "2024-02-01"
        await db.refresh(sef, ["birimler"])
        assert [(u.birim, u.is_primary) for u in sef.birimler] == [("GUVENLIK", True)]

        iki = next(k for k in kisiler if k.sicil_no == "T-0002")
        await db.refresh(iki, ["birimler"])
        assert sorted((u.birim, u.is_primary) for u in iki.birimler) == [
            ("GUVENLIK", False),
            ("POC", True),
        ]
        ofis = next(k for k in kisiler if k.sicil_no is None)
        assert ofis.username == "ornek.ofis"
        await db.refresh(ofis, ["birimler"])
        assert ofis.birimler == []  # tahmin yok: sütun boşsa birim yazılmaz

    async def test_ikinci_uygulama_sifir_yeni_satir(self, seeded):
        db = seeded
        await _onizle_ve_uygula(db, ORNEK.read_bytes())
        once = await _personel_sayisi(db)

        staged, sayac = await _onizle_ve_uygula(db, ORNEK.read_bytes())
        assert all(s["cakisma"] for s in staged), "eşleşen satır çakışma olarak işaretlenmeli"
        assert sayac["eklendi"] == 0 and sayac["guncellendi"] == 0
        assert await _personel_sayisi(db) == once

    async def test_guncelleme_rol_ve_girise_dokunmaz(self, seeded, kullanici_ac):
        db = seeded
        girisli = await kullanici_ac("girisli.tek", "SERVIS_SEF")
        girisli.sicil_no = "T-9000"
        await db.commit()

        icerik = _xlsx(
            [
                ["Ad Soyad", "Sicil No", "Ünvan", "Saha Rolü"],
                ["Örnek Yeni Ad", "T-9000", "Kıdemli Teknisyen", "TEKNISYEN"],
            ]
        )
        staged, sayac = await _onizle_ve_uygula(db, icerik, kararlar={1: "guncelle"})
        assert staged[0]["cakisma"]["kayit_id"] == girisli.id
        assert sayac["guncellendi"] == 1

        await db.refresh(girisli)
        assert girisli.unvan == "Kıdemli Teknisyen"
        assert girisli.saha_rolu == "TEKNISYEN"
        assert girisli.giris_acik is True
        rol = await db.get(Role, girisli.role_id)
        assert rol.code == "SERVIS_SEF"

    async def test_ust_yetkili_ile_eslesen_satir_hata(self, seeded, kullanici_ac):
        db = seeded
        await kullanici_ac("yonetici", "ADMIN")
        icerik = _xlsx([["Ad Soyad", "Kullanıcı Adı"], ["Örnek Sizma", "yonetici"]])
        staged, sayac = await _onizle_ve_uygula(db, icerik, kararlar={1: "guncelle"})
        assert staged[0]["hatalar"]
        assert sayac["guncellendi"] == 0
        yonetici = await db.scalar(select(User).where(User.username == "yonetici"))
        assert yonetici.full_name == "Yonetici"

    async def test_gecersiz_degerler_satir_hatasi(self, seeded):
        icerik = _xlsx(
            [
                ["Ad Soyad", "Sicil No", "Saha Rolü", "Birimler", "Birincil Birim"],
                ["Örnek Bir", "X-1", "MUDUR", "", ""],
                ["Örnek İki", "X-2", "TEKNISYEN", "GUVENLIK, UZAY", ""],
                ["Örnek Üç", "X-3", "TEKNISYEN", "GUVENLIK, POC", ""],
                ["Örnek Dört", "X-3", "TEKNISYEN", "", ""],
            ]
        )
        staged, sayac = await _onizle_ve_uygula(seeded, icerik)
        assert all(s["hatalar"] for s in staged), [s["hatalar"] for s in staged]
        assert sayac["eklendi"] == 0


class TestCerceveKaydi:
    """Profilin İçe Aktarma çerçevesine kaydı (`sv/imports/__init__.py`, D0-B dosyası)."""

    @pytest.fixture(autouse=True)
    def _kayitli_mi(self):
        if "personel" not in ice.PROFILLER:
            pytest.skip("personel profili PROFILLER'e henüz kaydedilmedi (D0-B talebi)")

    def test_izin_personel_yaz(self):
        assert ice.PROFIL_IZINLERI["personel"] == "personel.yaz"

    async def test_yetkisiz_403_yetkili_201(self, client, kullanici_ac):
        await kullanici_ac("guv_sef", "SERVIS_SEF")
        await kullanici_ac("ik_uzmani", "IK")
        dosya = {
            "file": (
                "personel.xlsx",
                ORNEK.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        }
        await client.post("/api/auth/login", json={"username": "guv_sef", "password": "parola1234"})
        assert (await client.post("/api/ice-aktarma/personel", files=dosya)).status_code == 403
        await client.post("/api/auth/logout")

        await client.post(
            "/api/auth/login", json={"username": "ik_uzmani", "password": "parola1234"}
        )
        cevap = await client.post("/api/ice-aktarma/personel", files=dosya)
        assert cevap.status_code == 201, cevap.text
        parti = cevap.json()["parti"]
        uygula = await client.post(f"/api/ice-aktarma/partiler/{parti['id']}/uygula", json={})
        assert uygula.status_code == 200
        assert uygula.json()["sonuc"]["eklendi"] == 4
