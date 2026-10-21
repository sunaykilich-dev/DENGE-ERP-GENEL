"""Personel kartı ve birim üyeliği (TS-002, TS-008; E13-03/05/06).

Personel = kullanıcı: girişi olmayan saha personeli de bir `users` satırıdır.
Testlerin kilitlediği riskler:

- İK'nın personel kartı üzerinden yetki verememesi: rol/parola/giriş bu
  uçlarda YOK; üst yetkili (ADMIN) hedefin adı ve birimi İK tarafından
  değiştirilemez (403).
- Kapsam: birim şefi başka birimin personelini GÖREMEZ (404) ve kapsam dışı
  karta yazma 404 dönerken arkada GERÇEKLEŞMEZ (`db.refresh` ile).
- KVKK: e-posta, kullanıcı adı ve personel notu yalnız `personel.yaz`
  sahibine döner — diğerlerinde anahtar olarak yoktur; kart okuması ve
  Excel denetime kişisel veri olarak yazılır.
- Yeniden aktifleştirme giriş hesabını AÇMAZ (E13-03).
"""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Role, Session, User, UserPermission, UserUnit

pytestmark = pytest.mark.integration

GIZLI = {"email", "username", "personel_notu", "ayrilis_nedeni"}


async def _giris(client, username: str, password: str = "parola1234"):
    cevap = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert cevap.status_code == 200, cevap.text
    return cevap


async def _birim(db, kisi: User, *birimler: str, birincil: str | None = None) -> None:
    birincil = birincil or (birimler[0] if birimler else None)
    for b in birimler:
        db.add(UserUnit(user_id=kisi.id, birim=b, is_primary=b == birincil))
    await db.commit()


async def _personel(db, ad: str, *birimler: str, saha_rolu: str = "TEKNISYEN", **kw) -> User:
    """Girişsiz saha personeli (SERVIS_TEKNISYEN rolünde)."""
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
    kisi = User(
        full_name=ad,
        username=kw.pop("username", ad.lower().replace(" ", ".")),
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA",
        role_id=rol.id,
        giris_acik=kw.pop("giris_acik", False),
        saha_rolu=saha_rolu,
        **kw,
    )
    db.add(kisi)
    await db.commit()
    await db.refresh(kisi)
    if birimler:
        await _birim(db, kisi, *birimler)
    return kisi


async def _istisna(db, kisi: User, kod: str, allow: bool = True) -> None:
    db.add(UserPermission(user_id=kisi.id, permission_code=kod, allow=allow, gerekce="test"))
    await db.commit()


@pytest.fixture
async def ortam(client, db, kullanici_ac):
    """İK (TUMU), Güvenlik şefi (KENDI_BIRIMI) ve iki birimde birer personel."""
    ik = await kullanici_ac("ik_uzmani", "IK")
    sef = await kullanici_ac("guv_sef", "SERVIS_SEF")
    await _birim(db, sef, "GUVENLIK")
    guv = await _personel(db, "Guvenlik Teknisyen", "GUVENLIK", sicil_no="G-1")
    poc = await _personel(db, "Poc Teknisyen", "POC", sicil_no="P-1")
    return {"ik": ik, "sef": sef, "guv": guv, "poc": poc}


# --- RBAC ------------------------------------------------------------------------


class TestYetki:
    async def test_personel_gor_olmayan_403(self, client, kullanici_ac):
        await kullanici_ac("satisci", "SATIS")
        await _giris(client, "satisci")
        assert (await client.get("/api/personel")).status_code == 403
        assert (await client.get("/api/personel/ozet")).status_code == 403

    async def test_ik_listeler_200(self, client, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.get("/api/personel")
        assert cevap.status_code == 200
        assert cevap.headers["X-Toplam-Kayit"] == "4"  # ik, şef, iki personel

    async def test_yazma_izni_olmayan_403(self, client, ortam):
        """Şef `personel.gor` taşır ama `personel.yaz` taşımaz."""
        await _giris(client, "guv_sef")
        p = ortam["guv"]
        assert (
            await client.post("/api/personel", json={"full_name": "Yeni Kisi"})
        ).status_code == 403
        assert (
            await client.patch(f"/api/personel/{p.id}", json={"unvan": "X", "version": p.version})
        ).status_code == 403
        assert (
            await client.put(f"/api/personel/{p.id}/birimler", json={"birimler": []})
        ).status_code == 403
        assert (await client.post(f"/api/personel/{p.id}/aktiflestir")).status_code == 403


# --- Girişsiz personel açılışı ----------------------------------------------------


class TestPersonelAcilisi:
    async def test_ik_girissiz_personel_acar(self, client, db, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.post(
            "/api/personel",
            json={
                "full_name": "Yeni Stajyer",
                "sicil_no": "S-77",
                "saha_rolu": "STAJYER",
                "unvan": "Stajyer",
                "ise_giris_tarihi": "2026-09-01",
                "birimler": [{"birim": "GUVENLIK", "birincil": True}],
            },
        )
        assert cevap.status_code == 201, cevap.text
        veri = cevap.json()
        assert veri["giris_acik"] is False
        assert veri["rol"]["code"] == "SERVIS_TEKNISYEN"
        assert veri["username"].startswith("p.")
        assert veri["birincil_birim"] == "GUVENLIK"

        kisi = await db.get(User, veri["id"])
        assert kisi.password_hash.startswith("$argon2")
        # Rastgele sırrın özeti: bilinen hiçbir parola tutmaz, 500 de doğurmaz.
        from app.services import auth as auth_service

        assert auth_service.verify_password("parola1234", kisi.password_hash) is False

        denetim = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "personel.olustur", AuditLog.entity_id == str(kisi.id)
            )
        )
        assert denetim is not None and denetim.is_personal_data is True

    async def test_ayni_sicil_ikinci_kez_409(self, client, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.post(
            "/api/personel", json={"full_name": "Baska Kisi", "sicil_no": "G-1"}
        )
        assert cevap.status_code == 409

    async def test_katalog_disi_birim_400(self, client, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.post(
            "/api/personel",
            json={"full_name": "Baska Kisi", "birimler": [{"birim": "UZAY", "birincil": True}]},
        )
        assert cevap.status_code == 400

    async def test_gecersiz_saha_rolu_400(self, client, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.post(
            "/api/personel", json={"full_name": "Baska Kisi", "saha_rolu": "MUDUR"}
        )
        assert cevap.status_code == 400


# --- Kart görünümü ve KVKK ---------------------------------------------------------


class TestKartGorunumu:
    async def test_yazma_izni_yoksa_gizli_alan_anahtari_yok(self, client, ortam):
        await _giris(client, "guv_sef")
        liste = (await client.get("/api/personel")).json()
        assert liste, "şef kendi biriminin personelini görmeli"
        for satir in liste:
            assert not (GIZLI & set(satir)), f"gizli alan sızdı: {GIZLI & set(satir)}"
        kart = (await client.get(f"/api/personel/{ortam['guv'].id}")).json()
        assert not (GIZLI & set(kart))

    async def test_yazma_izni_olan_gizli_alanlari_gorur(self, client, ortam):
        await _giris(client, "ik_uzmani")
        kart = (await client.get(f"/api/personel/{ortam['guv'].id}")).json()
        assert GIZLI <= set(kart)

    async def test_fiyat_maliyet_anahtari_yok(self, client, ortam):
        await _giris(client, "ik_uzmani")
        kart = (await client.get(f"/api/personel/{ortam['guv'].id}")).json()
        yasak = [k for k in kart if any(s in k for s in ("maliyet", "fiyat", "cost", "price"))]
        assert yasak == []

    async def test_kart_okumasi_kvkk_erisim_loguna_yazilir(self, client, db, ortam):
        await _giris(client, "ik_uzmani")
        await client.get(f"/api/personel/{ortam['guv'].id}")
        kayit = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "kisisel.eris", AuditLog.entity_id == str(ortam["guv"].id)
            )
        )
        assert kayit is not None and kayit.is_personal_data is True


# --- Kapsam ------------------------------------------------------------------------


class TestKapsam:
    async def test_sef_yalniz_kendi_birimini_gorur(self, client, ortam):
        await _giris(client, "guv_sef")
        cevap = await client.get("/api/personel")
        adlar = {s["full_name"] for s in cevap.json()}
        assert "Guvenlik Teknisyen" in adlar
        assert "Poc Teknisyen" not in adlar
        # Birimsiz İK kullanıcısı birim kapsamlı şefe görünmez.
        assert "Ik_Uzmani" not in adlar

    async def test_baska_birimin_karti_404(self, client, ortam):
        await _giris(client, "guv_sef")
        assert (await client.get(f"/api/personel/{ortam['poc'].id}")).status_code == 404

    async def test_birimsiz_sef_hicbir_sey_gormez(self, client, kullanici_ac, ortam):
        await kullanici_ac("birimsiz_sef", "SERVIS_SEF")
        await _giris(client, "birimsiz_sef")
        cevap = await client.get("/api/personel")
        assert cevap.status_code == 200
        assert cevap.json() == [] and cevap.headers["X-Toplam-Kayit"] == "0"
        assert (await client.get(f"/api/personel/{ortam['guv'].id}")).status_code == 404

    async def test_kapsam_disi_yazma_404_ve_veri_degismez(self, client, db, ortam):
        """404 dönmek YETMEZ; yazmanın da GERÇEKLEŞMEMESİ gerekir.

        Şefe istisnayla `personel.yaz` verilir; böylece yetki kapısını geçer
        ve kapsam kontrolünün kendisi sınanır.
        """
        await _istisna(db, ortam["sef"], "personel.yaz")
        await _giris(client, "guv_sef")
        hedef = ortam["poc"]

        cevap = await client.patch(
            f"/api/personel/{hedef.id}", json={"unvan": "SIZMA", "version": hedef.version}
        )
        assert cevap.status_code == 404
        cevap = await client.put(
            f"/api/personel/{hedef.id}/birimler",
            json={"birimler": [{"birim": "GUVENLIK", "birincil": True}]},
        )
        assert cevap.status_code == 404

        await db.refresh(hedef)
        await db.refresh(hedef, ["birimler"])
        assert hedef.unvan is None
        assert [u.birim for u in hedef.birimler] == ["POC"]

    async def test_kapsamli_yazar_kisiyi_baska_birime_tasiyamaz(self, client, db, ortam):
        """Kendi birimindeki kişiyi kapsamı dışındaki birime eklemek 404."""
        await _istisna(db, ortam["sef"], "personel.yaz")
        await _giris(client, "guv_sef")
        hedef = ortam["guv"]
        cevap = await client.put(
            f"/api/personel/{hedef.id}/birimler",
            json={"birimler": [{"birim": "GUVENLIK", "birincil": True}, {"birim": "POC"}]},
        )
        assert cevap.status_code == 404
        await db.refresh(hedef, ["birimler"])
        assert [u.birim for u in hedef.birimler] == ["GUVENLIK"]

    async def test_kapsam_disi_aktiflestirme_404_ve_veri_degismez(self, client, db, ortam):
        await _istisna(db, ortam["sef"], "personel.yaz")
        hedef = ortam["poc"]
        hedef.is_active = False
        hedef.ayrilis_tarihi = date(2026, 9, 30)
        hedef.ayrilis_nedeni = "ISTIFA"
        await db.commit()
        await _giris(client, "guv_sef")
        assert (await client.post(f"/api/personel/{hedef.id}/aktiflestir")).status_code == 404
        await db.refresh(hedef)
        assert hedef.is_active is False


# --- Birim üyeliği (TS-002) ---------------------------------------------------------


class TestBirimUyeligi:
    async def test_birimleri_yazar_oturumu_duser_denetime_yazar(self, client, db, ortam):
        from app.services import auth as auth_service

        hedef = ortam["guv"]
        await auth_service.create_session(db, hedef, client.clock)
        await db.commit()

        await _giris(client, "ik_uzmani")
        cevap = await client.put(
            f"/api/personel/{hedef.id}/birimler",
            json={"birimler": [{"birim": "POC", "birincil": True}, {"birim": "GUVENLIK"}]},
        )
        assert cevap.status_code == 200, cevap.text
        assert cevap.json() == [
            {"birim": "GUVENLIK", "birincil": False},
            {"birim": "POC", "birincil": True},
        ]
        oturum = await db.scalar(
            select(func.count()).select_from(Session).where(Session.user_id == hedef.id)
        )
        assert oturum == 0, "kapsam değişti; eski oturum düşmeliydi"
        denetim = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "birim.degistir", AuditLog.entity_id == str(hedef.id)
            )
        )
        assert denetim is not None and denetim.is_personal_data is True

    async def test_katalog_disi_birim_400(self, client, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.put(
            f"/api/personel/{ortam['guv'].id}/birimler",
            json={"birimler": [{"birim": "UZAY", "birincil": True}]},
        )
        assert cevap.status_code == 400

    async def test_iki_birincil_409(self, client, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.put(
            f"/api/personel/{ortam['guv'].id}/birimler",
            json={
                "birimler": [
                    {"birim": "GUVENLIK", "birincil": True},
                    {"birim": "POC", "birincil": True},
                ]
            },
        )
        assert cevap.status_code == 409

    async def test_birincilsiz_birim_400(self, client, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.put(
            f"/api/personel/{ortam['guv'].id}/birimler",
            json={"birimler": [{"birim": "GUVENLIK"}]},
        )
        assert cevap.status_code == 400

    async def test_kendi_birimini_degistiremez_403(self, client, db, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.put(
            f"/api/personel/{ortam['ik'].id}/birimler",
            json={"birimler": [{"birim": "GUVENLIK", "birincil": True}]},
        )
        assert cevap.status_code == 403
        assert (
            await db.scalar(
                select(func.count()).select_from(UserUnit).where(UserUnit.user_id == ortam["ik"].id)
            )
        ) == 0

    async def test_ust_yetkili_hedefin_birimi_ik_tarafindan_yazilamaz(
        self, client, db, kullanici_ac, ortam
    ):
        yonetici = await kullanici_ac("sistem_yon", "ADMIN")
        await _giris(client, "ik_uzmani")
        cevap = await client.put(
            f"/api/personel/{yonetici.id}/birimler",
            json={"birimler": [{"birim": "GUVENLIK", "birincil": True}]},
        )
        assert cevap.status_code == 403

    async def test_birimler_auth_me_ciktisinda(self, client, db, ortam, kullanici_ac):
        """`/api/auth/me` birimleri ve birincil birimi döner (ön yüz seçicileri)."""
        teknisyen = await kullanici_ac("girisli_tek", "SERVIS_TEKNISYEN")
        await _giris(client, "ik_uzmani")
        cevap = await client.put(
            f"/api/personel/{teknisyen.id}/birimler",
            json={"birimler": [{"birim": "MOBILITE"}, {"birim": "ARAC_TAKIP", "birincil": True}]},
        )
        assert cevap.status_code == 200
        await client.post("/api/auth/logout")
        await _giris(client, "girisli_tek")
        ben = (await client.get("/api/auth/me")).json()
        assert ben["birimler"] == ["ARAC_TAKIP", "MOBILITE"]
        assert ben["birincil_birim"] == "ARAC_TAKIP"

    async def test_birimler_bosaltilabilir(self, client, db, ortam):
        await _giris(client, "ik_uzmani")
        cevap = await client.put(f"/api/personel/{ortam['guv'].id}/birimler", json={"birimler": []})
        assert cevap.status_code == 200 and cevap.json() == []


# --- Kart güncelleme (TS-008) --------------------------------------------------------


class TestKartGuncelleme:
    async def test_surum_zorunlu_ve_cakisma_409(self, client, ortam):
        await _giris(client, "ik_uzmani")
        p = ortam["guv"]
        assert (await client.patch(f"/api/personel/{p.id}", json={"unvan": "X"})).status_code == 422
        cevap = await client.patch(
            f"/api/personel/{p.id}", json={"unvan": "X", "version": p.version + 5}
        )
        assert cevap.status_code == 409

    async def test_guncelleme_kisisel_veri_olarak_denetlenir(self, client, db, ortam):
        await _giris(client, "ik_uzmani")
        p = ortam["guv"]
        cevap = await client.patch(
            f"/api/personel/{p.id}",
            json={"full_name": "Guvenlik Teknisyen Yeni", "sicil_no": "G-9", "version": p.version},
        )
        assert cevap.status_code == 200, cevap.text
        assert cevap.json()["full_name"] == "Guvenlik Teknisyen Yeni"
        denetim = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "personel.guncelle", AuditLog.entity_id == str(p.id)
            )
        )
        assert denetim is not None and denetim.is_personal_data is True
        assert denetim.new_value["sicil_no"] == "G-9"

    async def test_baska_kisinin_sicili_409(self, client, ortam):
        await _giris(client, "ik_uzmani")
        p = ortam["guv"]
        cevap = await client.patch(
            f"/api/personel/{p.id}", json={"sicil_no": "P-1", "version": p.version}
        )
        assert cevap.status_code == 409

    async def test_rol_ve_giris_bu_uctan_degismez(self, client, db, ortam):
        """Şemada olmayan alan yok sayılır; rol/giriş kullanıcı yönetiminin işi."""
        await _giris(client, "ik_uzmani")
        p = ortam["guv"]
        cevap = await client.patch(
            f"/api/personel/{p.id}",
            json={"unvan": "Usta", "giris_acik": True, "role_code": "ADMIN", "version": p.version},
        )
        assert cevap.status_code == 200
        await db.refresh(p)
        assert p.giris_acik is False
        rol = await db.get(Role, p.role_id)
        assert rol.code == "SERVIS_TEKNISYEN"

    async def test_ust_yetkili_hedefte_ad_403_unvan_serbest(self, client, db, kullanici_ac, ortam):
        yonetici = await kullanici_ac("sistem_yon2", "ADMIN")
        await _giris(client, "ik_uzmani")
        cevap = await client.patch(
            f"/api/personel/{yonetici.id}",
            json={"full_name": "Degistirilmis Ad", "version": yonetici.version},
        )
        assert cevap.status_code == 403
        await db.refresh(yonetici)
        assert yonetici.full_name == "Sistem_Yon2"

        cevap = await client.patch(
            f"/api/personel/{yonetici.id}",
            json={"unvan": "Genel Müdür", "version": yonetici.version},
        )
        assert cevap.status_code == 200

    async def test_admin_ust_yetkili_hedefin_adini_degistirebilir(
        self, client, kullanici_ac, ortam
    ):
        await kullanici_ac("ana_yonetici", "ADMIN")
        diger = await kullanici_ac("diger_yonetici", "ADMIN")
        await _giris(client, "ana_yonetici")
        cevap = await client.patch(
            f"/api/personel/{diger.id}",
            json={"full_name": "Diger Yonetici", "version": diger.version},
        )
        assert cevap.status_code == 200


# --- Yeniden aktifleştirme (E13-03) ---------------------------------------------------


class TestAktiflestirme:
    async def test_aktiflestirme_girisi_acmaz(self, client, db, ortam):
        p = ortam["guv"]
        p.is_active = False
        p.ayrilis_tarihi = date(2026, 9, 30)
        p.ayrilis_nedeni = "ISTIFA"
        await db.commit()

        await _giris(client, "ik_uzmani")
        cevap = await client.post(f"/api/personel/{p.id}/aktiflestir")
        assert cevap.status_code == 200, cevap.text
        veri = cevap.json()
        assert veri["giris_acik"] is False
        assert "ayrıca" in veri["mesaj"]

        await db.refresh(p)
        assert p.is_active is True and p.ayrilis_tarihi is None and p.ayrilis_nedeni is None
        assert p.giris_acik is False
        denetim = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "personel.aktiflestir", AuditLog.entity_id == str(p.id)
            )
        )
        assert denetim is not None and denetim.is_personal_data is True

    async def test_calisan_personel_aktiflestirilemez_409(self, client, ortam):
        await _giris(client, "ik_uzmani")
        assert (
            await client.post(f"/api/personel/{ortam['guv'].id}/aktiflestir")
        ).status_code == 409


# --- KPI ve Excel ----------------------------------------------------------------------


class TestKpiVeExcel:
    async def test_kpi_sayisi_liste_toplamina_esit(self, client, db, ortam):
        await _personel(
            db,
            "Ayrilmis Kisi",
            "GUVENLIK",
            is_active=False,
            ayrilis_tarihi=date(2026, 1, 1),
            ayrilis_nedeni="DIGER",
        )
        await _personel(db, "Rolsuz Kisi", "GUVENLIK", saha_rolu=None)
        await _personel(db, "Birimsiz Kisi")
        await _giris(client, "ik_uzmani")
        kutular = (await client.get("/api/personel/ozet")).json()
        assert kutular
        for kutu in kutular:
            parametre = {
                k: str(v).lower() if isinstance(v, bool) else v for k, v in kutu["suzgec"].items()
            }
            liste = await client.get("/api/personel", params=parametre)
            assert liste.status_code == 200
            assert int(liste.headers["X-Toplam-Kayit"]) == kutu["adet"], kutu["kod"]
        adet = {k["kod"]: k["adet"] for k in kutular}
        assert adet["SAHA_GUVENLIK"] == 1  # ayrılmış ve saha rolsüz sayılmaz
        assert adet["SAHA_ROLU_EKSIK"] >= 1
        assert adet["BIRIMSIZ"] >= 1

    async def test_kapsamli_kullanicinin_kpi_sayisi_kapsamli(self, client, ortam):
        await _giris(client, "guv_sef")
        adet = {k["kod"]: k["adet"] for k in (await client.get("/api/personel/ozet")).json()}
        assert adet["SAHA_POC"] == 0, "sayı = sızıntı: başka birimin personeli sayılmamalı"
        assert adet["BIRIMSIZ"] == 0

    async def test_excel_yetkisi_ve_gizli_sutunlar(self, client, db, kullanici_ac, ortam):
        from io import BytesIO

        from openpyxl import load_workbook

        await kullanici_ac("satisci2", "SATIS")
        await _giris(client, "satisci2")
        assert (await client.get("/api/personel/liste.xlsx")).status_code == 403
        await client.post("/api/auth/logout")

        await _giris(client, "guv_sef")
        cevap = await client.get("/api/personel/liste.xlsx")
        assert cevap.status_code == 200
        basliklar = [h.value for h in load_workbook(BytesIO(cevap.content)).active[1]]
        assert "Kullanıcı Adı" not in basliklar and "E-posta" not in basliklar
        await client.post("/api/auth/logout")

        await _giris(client, "ik_uzmani")
        cevap = await client.get("/api/personel/liste.xlsx")
        assert cevap.status_code == 200
        basliklar = [h.value for h in load_workbook(BytesIO(cevap.content)).active[1]]
        assert "Kullanıcı Adı" in basliklar
        denetim = await db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "personel.disa_aktar")
            .order_by(AuditLog.id.desc())
        )
        assert denetim is not None and denetim.is_personal_data is True
