"""İşten çıkış akışı (TS-165; E13-09, E08-D02).

Kilitlenen riskler:

- Önizleme HİÇBİR ŞEY yazmaz; açık işleri, açık sayacı, oturumları ve eğitim
  kayıtlarını gösterir.
- Uygulama TEK transaction: personel ve giriş kapanır, oturumlar 401 alır,
  açık işlerdeki atamalar `removed_at` alır, iş durumları DEĞİŞMEZ; kapalı
  işin ataması geçmiştir, dokunulmaz.
- Açık sayaç KAPATILMAZ ve süre üretilmez (E13 K-11); kişi o işin ekibinden
  çıkarılmaz (`ekip_degisiyor` kuralı). Uyarı merkezi "inceleme bekliyor"
  sayar, görev panosunda kişi adı taşımayan inceleme kartı açılır.
- Ekip değişikliği planlamaya yansır (aktif planda EKIP_DEGISIMI).
- Sorumlusu kalmayan iş "Atanmamış" listesine düşer.
- Kurallar: kendisi 400, üst yetkili 403, sürüm / zaten ayrılmış 409; bir
  adım hata verirse HİÇBİR adım kalmaz (rollback).
- Kapsam dışı kişi 404 ve veri değişmez.
- Sorumlusu ayrılan açık düzeltici faaliyet uyarıda sayılır (E08-D02).
- Ardından aktifleştirme girişi AÇMAZ.

Test oturumundaki ORM nesneleri API'nin ayrı oturumunda değişir; bu yüzden
ortam düz değerler (kimlik, numara) taşır ve kayıtlar her kontrolde tazelenir.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import (
    AuditLog,
    Card,
    Role,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServicePlan,
    ServicePlanMember,
    ServiceTimeEntry,
    TrainingCorrectiveAction,
    TrainingCourse,
    TrainingObservation,
    User,
    UserUnit,
)
from app.services import auth as auth_service
from app.services.teknik_servis import kancalar
from app.services.teknik_servis import personel as personel_svc

pytestmark = pytest.mark.integration

AN = datetime(2025, 12, 31, 22, 0, tzinfo=UTC)
CIKIS_IZINLERI = ["personel.gor", "personel.cikis", "servis.gor", "servis.planla"]


async def _giris(client, username: str, password: str = "parola1234"):
    cevap = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert cevap.status_code == 200, cevap.text
    return cevap


def _yeni_istemci() -> httpx.AsyncClient:
    from app.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )


async def _taze(db, model, kimlik: int):
    kayit = await db.get(model, kimlik)
    await db.refresh(kayit)
    return kayit


async def _personel(db, ad: str, birim: str = "GUVENLIK", *, giris: bool = False) -> User:
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
    kisi = User(
        full_name=ad,
        username=ad.lower().replace(" ", "."),
        password_hash=auth_service.hash_password("parola1234"),
        role_id=rol.id,
        giris_acik=giris,
        saha_rolu="TEKNISYEN",
        ise_giris_tarihi=date(2024, 1, 1),
    )
    db.add(kisi)
    await db.commit()
    db.add(UserUnit(user_id=kisi.id, birim=birim, is_primary=True))
    await db.commit()
    await db.refresh(kisi)
    return kisi


@pytest.fixture
async def ortam(client, db, rol_ac, kullanici_ac, birimli_kullanici_ac, servis_isi_ac):
    """İK (TUMU), Güvenlik ve Haberleşme birim yöneticileri (KENDI_BIRIMI);
    Güvenlik teknisyeni dört işte: tek başına (1), ekip arkadaşıyla + aktif
    plan (2), açık sayaçlı (3), kapalı (4)."""
    await rol_ac("T_CIKIS_BIRIM", CIKIS_IZINLERI, "KENDI_BIRIMI")
    ik = await kullanici_ac("ik_uzmani", "IK")
    await birimli_kullanici_ac("guv_mudur", "T_CIKIS_BIRIM", ["GUVENLIK"])
    await birimli_kullanici_ac("hab_mudur", "T_CIKIS_BIRIM", ["HABERLESME"])
    tek = await _personel(db, "Ayrilan Teknisyen", giris=True)
    diger = await _personel(db, "Kalan Teknisyen")

    is1 = await servis_isi_ac(atananlar=[tek], durum="PLANLAMADA")
    is2 = await servis_isi_ac(atananlar=[tek, diger], durum="PLANLANDI")
    is3 = await servis_isi_ac(atananlar=[tek], durum="SAHADA")
    is4 = await servis_isi_ac(atananlar=[tek], durum="TAMAMLANDI")

    plan = ServicePlan(
        service_order_id=is2.id,
        plan_date=date(2026, 1, 5),
        duration_min=60,
        change_type="ILK_PLAN",
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    db.add_all(
        [
            ServicePlanMember(plan_id=plan.id, user_id=tek.id, rol="TEKNISYEN"),
            ServicePlanMember(plan_id=plan.id, user_id=diger.id, rol="TEKNISYEN"),
        ]
    )
    bolum = ServiceTimeEntry(
        service_order_id=is3.id,
        user_id=tek.id,
        faaliyet="SAHA",
        started_at=AN,
        kaynak="CANLI",
        girildi_at=AN,
    )
    db.add(bolum)
    await db.commit()
    isler = [is1, is2, is3, is4]
    return SimpleNamespace(
        ik_id=ik.id,
        tek_id=tek.id,
        tek_kadi=tek.username,
        tek_ad=tek.full_name,
        tek_surum=tek.version,
        diger_id=diger.id,
        is_id=[s.id for s in isler],
        is_no=[s.so_no for s in isler],
        bolum_id=bolum.id,
    )


async def _aktif_atama(db, so_id: int, user_id: int) -> bool:
    return (
        await db.scalar(
            select(ServiceOrderAssignment.id).where(
                ServiceOrderAssignment.service_order_id == so_id,
                ServiceOrderAssignment.user_id == user_id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    ) is not None


def _govde(surum: int, **kw) -> dict:
    return {"ayrilis_tarihi": "2026-01-10", "ayrilis_nedeni": "ISTIFA", "version": surum, **kw}


async def _cikis(client, o) -> dict:
    r = await client.post(f"/api/personel/{o.tek_id}/cikis", json=_govde(o.tek_surum))
    assert r.status_code == 200, r.text
    return r.json()


async def _kullanici(db, username: str) -> User:
    return await db.scalar(
        select(User).where(User.username == username).execution_options(populate_existing=True)
    )


# --- RBAC ---------------------------------------------------------------------------


class TestYetki:
    async def test_cikis_izni_olmayan_403(self, client, ortam, birimli_kullanici_ac):
        await birimli_kullanici_ac("guv_sef", "SERVIS_SEF", ["GUVENLIK"])
        await _giris(client, "guv_sef")
        o = ortam
        assert (await client.get(f"/api/personel/{o.tek_id}/cikis-onizleme")).status_code == 403
        r = await client.post(f"/api/personel/{o.tek_id}/cikis", json=_govde(o.tek_surum))
        assert r.status_code == 403

    async def test_ik_ve_birim_yoneticisi_onizler_200(self, client, ortam):
        await _giris(client, "ik_uzmani")
        assert (await client.get(f"/api/personel/{ortam.tek_id}/cikis-onizleme")).status_code == 200
        await _giris(client, "guv_mudur")
        assert (await client.get(f"/api/personel/{ortam.tek_id}/cikis-onizleme")).status_code == 200


# --- Önizleme -------------------------------------------------------------------------


class TestOnizleme:
    async def test_acik_isler_sayac_ve_oturum_gorunur_hicbir_sey_yazilmaz(self, client, db, ortam):
        o = ortam
        ayri = _yeni_istemci()
        try:
            await _giris(ayri, o.tek_kadi)
        finally:
            await ayri.aclose()

        await _giris(client, "ik_uzmani")
        once = await db.scalar(select(func.count()).select_from(AuditLog))
        r = await client.get(f"/api/personel/{o.tek_id}/cikis-onizleme")
        assert r.status_code == 200, r.text
        v = r.json()
        isler = {i["so_no"]: i for i in v["aktif_isler"]}
        # Kapalı iş (4) listede yok.
        assert set(isler) == set(o.is_no[:3])
        assert isler[o.is_no[2]]["sayac_acik"] is True
        assert isler[o.is_no[0]]["sayac_acik"] is False
        assert isler[o.is_no[0]]["sorumlu"] is True
        assert v["acik_sayac"]["bolum_id"] == o.bolum_id
        assert v["acik_sayac"]["so_no"] == o.is_no[2]
        assert v["acik_oturum_sayisi"] == 1
        assert v["gorev_karti_acilacak"] is True
        assert v["zaten_ayrildi"] is False
        assert any("KAPATILMAZ" in u for u in v["uyarilar"])

        assert await db.scalar(select(func.count()).select_from(AuditLog)) == once
        assert (await _taze(db, User, o.tek_id)).is_active is True

    async def test_kapsam_disi_isler_numarasiz_sayilir(self, client, db, ortam, servis_isi_ac):
        """Kişinin başka birimdeki işi yöneticinin kapsamı dışında: sayılır, gösterilmez."""
        o = ortam
        db.add(UserUnit(user_id=o.tek_id, birim="HABERLESME", is_primary=False))
        await db.commit()
        hab_is = await servis_isi_ac(birim="HABERLESME", atananlar=[SimpleNamespace(id=o.tek_id)])
        hab_no = hab_is.so_no
        await _giris(client, "guv_mudur")
        v = (await client.get(f"/api/personel/{o.tek_id}/cikis-onizleme")).json()
        assert hab_no not in {i["so_no"] for i in v["aktif_isler"]}
        assert v["kapsam_disi_is_sayisi"] == 1


# --- Uygulama -------------------------------------------------------------------------


class TestUygulama:
    async def test_cikis_tek_transactionda_uygulanir(self, client, db, ortam):
        o = ortam
        ayri = _yeni_istemci()
        await _giris(ayri, o.tek_kadi)
        assert (await ayri.get("/api/auth/me")).status_code == 200
        bolum_sayisi = await db.scalar(select(func.count()).select_from(ServiceTimeEntry))

        await _giris(client, "ik_uzmani")
        sonuc = await _cikis(client, o)
        assert set(sonuc["cikarilan_isler"]) == {o.is_no[0], o.is_no[1]}
        assert sonuc["ekipte_kalan_isler"] == [o.is_no[2]]
        assert sonuc["acik_sayac_bolum_id"] == o.bolum_id
        assert sonuc["gorev_karti_id"] is not None
        assert sonuc["kapanan_oturum"] == 1

        # Personel ve giriş kapandı; oturum 401.
        try:
            assert (await ayri.get("/api/auth/me")).status_code == 401
        finally:
            await ayri.aclose()
        kisi = await _taze(db, User, o.tek_id)
        assert kisi.is_active is False and kisi.giris_acik is False
        assert kisi.ayrilis_tarihi == date(2026, 1, 10)
        assert kisi.ayrilis_nedeni == "ISTIFA"
        assert kisi.ayrilisi_yapan_id == o.ik_id

        # Atamalar: 1 ve 2 kapandı (satır silinmedi), 3 (açık sayaç) ve 4 (kapalı iş) duruyor.
        assert not await _aktif_atama(db, o.is_id[0], o.tek_id)
        assert not await _aktif_atama(db, o.is_id[1], o.tek_id)
        assert await _aktif_atama(db, o.is_id[2], o.tek_id)
        assert await _aktif_atama(db, o.is_id[3], o.tek_id)
        assert await _aktif_atama(db, o.is_id[1], o.diger_id)
        kapanan = (
            await db.execute(
                select(ServiceOrderAssignment.removed_at, ServiceOrderAssignment.removed_by).where(
                    ServiceOrderAssignment.service_order_id == o.is_id[0],
                    ServiceOrderAssignment.user_id == o.tek_id,
                )
            )
        ).one()
        assert kapanan.removed_at is not None and kapanan.removed_by == o.ik_id

        # İş durumları değişmedi.
        durumlar = dict(
            (
                await db.execute(
                    select(ServiceOrder.id, ServiceOrder.status).where(ServiceOrder.id.in_(o.is_id))
                )
            ).all()
        )
        assert [durumlar[i] for i in o.is_id] == ["PLANLAMADA", "PLANLANDI", "SAHADA", "TAMAMLANDI"]

        # Açık sayaç KAPANMADI, süre satırı oluşmadı.
        assert (await _taze(db, ServiceTimeEntry, o.bolum_id)).ended_at is None
        assert await db.scalar(select(func.count()).select_from(ServiceTimeEntry)) == bolum_sayisi

        # ATAMA olayı ("İşten çıkış"), kişi adı yok.
        ozet = await db.scalar(
            select(ServiceOrderEvent.ozet).where(
                ServiceOrderEvent.service_order_id == o.is_id[0],
                ServiceOrderEvent.olay_turu == "ATAMA",
            )
        )
        assert ozet is not None and "İşten çıkış" in ozet
        assert o.tek_ad not in ozet

        # Denetim kişisel veri olarak.
        kisisel = await db.scalar(
            select(AuditLog.is_personal_data).where(
                AuditLog.action == "personel.cikis", AuditLog.entity_id == str(o.tek_id)
            )
        )
        assert kisisel is True

    async def test_planlama_ekip_degisimi_yansir(self, client, db, ortam):
        o = ortam
        await _giris(client, "ik_uzmani")
        await _cikis(client, o)
        aktif = (
            await db.execute(
                select(ServicePlan.id, ServicePlan.change_type).where(
                    ServicePlan.service_order_id == o.is_id[1], ServicePlan.is_active.is_(True)
                )
            )
        ).one()
        assert aktif.change_type == "EKIP_DEGISIMI"
        uyeler = set(
            await db.scalars(
                select(ServicePlanMember.user_id).where(ServicePlanMember.plan_id == aktif.id)
            )
        )
        assert uyeler == {o.diger_id}

    async def test_atanmamis_listesine_duser(self, client, ortam):
        o = ortam
        await _giris(client, "ik_uzmani")
        await _cikis(client, o)
        await _giris(client, "guv_mudur")
        r = await client.get("/api/teknik-servis/isler", params={"kpi": "atanmamis"})
        assert r.status_code == 200, r.text
        nolar = {s["so_no"] for s in r.json()}
        assert o.is_no[0] in nolar  # tek başınaydı
        assert o.is_no[1] not in nolar  # ekip arkadaşı kaldı
        assert o.is_no[2] not in nolar  # açık sayaç: kişi ekipte kaldı

    async def test_gorev_karti_kisi_adi_tasimaz(self, client, db, ortam):
        o = ortam
        await _giris(client, "ik_uzmani")
        sonuc = await _cikis(client, o)
        kart = await _taze(db, Card, sonuc["gorev_karti_id"])
        assert kart.entity == "servis_isi" and kart.entity_id == o.is_id[2]
        assert o.tek_ad not in kart.title
        assert o.tek_ad not in (kart.description or "")
        assert o.is_no[2] in kart.description
        assert o.is_no[0] in kart.description

    async def test_uyari_merkezi_inceleme_bekliyor_sayar(self, client, db, ortam):
        o = ortam
        saat = FakeClock()
        guv = await _kullanici(db, "guv_mudur")
        hab = await _kullanici(db, "hab_mudur")
        assert (await personel_svc.cikis_sayac_uyarisi(db, guv, saat))[0].adet == 0
        await _giris(client, "ik_uzmani")
        await _cikis(client, o)
        assert (await personel_svc.cikis_sayac_uyarisi(db, guv, saat))[0].adet == 1
        # Başka birimin yöneticisi saymaz (uyarı sayısı da sızıntıdır).
        assert (await personel_svc.cikis_sayac_uyarisi(db, hab, saat))[0].adet == 0

    async def test_ardindan_aktiflestirme_girisi_acmaz(self, client, ortam):
        o = ortam
        await _giris(client, "ik_uzmani")
        await _cikis(client, o)
        r = await client.post(f"/api/personel/{o.tek_id}/aktiflestir")
        assert r.status_code == 200, r.text
        assert r.json()["giris_acik"] is False
        ayri = _yeni_istemci()
        try:
            r = await ayri.post(
                "/api/auth/login", json={"username": o.tek_kadi, "password": "parola1234"}
            )
            assert r.status_code == 401
        finally:
            await ayri.aclose()


# --- Kurallar ve geri alma ---------------------------------------------------------------


class TestKurallar:
    async def test_kendisi_400(self, client, db, ortam):
        ik = await _taze(db, User, ortam.ik_id)
        await _giris(client, "ik_uzmani")
        r = await client.post(f"/api/personel/{ik.id}/cikis", json=_govde(ik.version))
        assert r.status_code == 400

    async def test_ust_yetkili_hedef_ik_403(self, client, db, ortam, kullanici_ac):
        admin = await kullanici_ac("yonetici2", "ADMIN")
        admin_id, surum = admin.id, admin.version
        await _giris(client, "ik_uzmani")
        r = await client.post(f"/api/personel/{admin_id}/cikis", json=_govde(surum))
        assert r.status_code == 403
        assert (await _taze(db, User, admin_id)).is_active is True

    async def test_surum_neden_ve_tarih_hatalari(self, client, db, ortam):
        o = ortam
        yol = f"/api/personel/{o.tek_id}/cikis"
        await _giris(client, "ik_uzmani")
        assert (await client.post(yol, json=_govde(o.tek_surum + 5))).status_code == 409
        r = await client.post(yol, json=_govde(o.tek_surum, ayrilis_nedeni="KACTI"))
        assert r.status_code == 400
        r = await client.post(yol, json=_govde(o.tek_surum, ayrilis_tarihi="2020-01-01"))
        assert r.status_code == 400  # işe girişten önce
        kisi = await _taze(db, User, o.tek_id)
        assert kisi.is_active is True and kisi.ayrilis_tarihi is None
        assert await _aktif_atama(db, o.is_id[0], o.tek_id)

    async def test_zaten_ayrilmis_409(self, client, db, ortam):
        o = ortam
        await _giris(client, "ik_uzmani")
        await _cikis(client, o)
        surum = (await _taze(db, User, o.tek_id)).version
        r = await client.post(f"/api/personel/{o.tek_id}/cikis", json=_govde(surum))
        assert r.status_code == 409

    async def test_adim_hatasinda_hicbir_sey_uygulanmaz(self, client, db, ortam):
        """Ekip kancası hata verirse personel, atama, oturum ve kart geri alınır."""
        o = ortam

        async def _patlayan(db_, so, yeni_ekip, clock):
            raise kancalar.ServisHatasi("Test: plan senkronu başarısız")

        kancalar.kaydet("ekip_degisti", _patlayan)
        try:
            await _giris(client, "ik_uzmani")
            r = await client.post(f"/api/personel/{o.tek_id}/cikis", json=_govde(o.tek_surum))
        finally:
            kancalar._KAYIT["ekip_degisti"].remove(_patlayan)
        assert r.status_code == 409, r.text
        kisi = await _taze(db, User, o.tek_id)
        assert kisi.is_active is True and kisi.giris_acik is True
        assert kisi.ayrilis_tarihi is None
        assert await _aktif_atama(db, o.is_id[0], o.tek_id)
        assert await db.scalar(select(func.count()).select_from(Card)) == 0
        sayi = await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "personel.cikis")
        )
        assert sayi == 0


# --- Kapsam ----------------------------------------------------------------------------------


class TestKapsam:
    async def test_baska_birim_yoneticisi_404_ve_veri_degismez(self, client, db, ortam):
        o = ortam
        await _giris(client, "hab_mudur")
        assert (await client.get(f"/api/personel/{o.tek_id}/cikis-onizleme")).status_code == 404
        r = await client.post(f"/api/personel/{o.tek_id}/cikis", json=_govde(o.tek_surum))
        assert r.status_code == 404
        kisi = await _taze(db, User, o.tek_id)
        assert kisi.is_active is True and kisi.ayrilis_tarihi is None
        assert kisi.version == o.tek_surum
        assert await _aktif_atama(db, o.is_id[0], o.tek_id)


# --- Eğitim (E08-D02) ---------------------------------------------------------------------


class TestEgitim:
    async def test_sorumlusuz_duzeltici_faaliyet_uyarisi(self, client, db, ortam):
        o = ortam
        kurs = TrainingCourse(kod="ISG-1", baslik="İSG", kategori="ISG", sure_saat=2)
        db.add(kurs)
        await db.flush()
        gozlem = TrainingObservation(
            user_id=o.diger_id,
            course_id=kurs.id,
            asama=30,
            gozlem_tarihi=date(2026, 1, 2),
            observer_user_id=o.tek_id,
            sonuc="KRITIK",
            kritik=True,
        )
        db.add(gozlem)
        await db.flush()
        faaliyet = TrainingCorrectiveAction(
            observation_id=gozlem.id,
            user_id=o.diger_id,
            course_id=kurs.id,
            sorumlu_user_id=o.tek_id,
            termin=date(2026, 2, 1),
        )
        db.add(faaliyet)
        await db.commit()
        faaliyet_id = faaliyet.id

        await _giris(client, "ik_uzmani")
        v = (await client.get(f"/api/personel/{o.tek_id}/cikis-onizleme")).json()
        assert v["egitim"]["sorumlu_oldugu_acik_faaliyet"] == 1
        assert any("sorumlusuz" in u for u in v["uyarilar"])

        ik = await _kullanici(db, "ik_uzmani")
        saat = FakeClock()
        assert (await personel_svc.sorumlusuz_faaliyet_uyarisi(db, ik, saat))[0].adet == 0
        await _cikis(client, o)
        assert (await personel_svc.sorumlusuz_faaliyet_uyarisi(db, ik, saat))[0].adet == 1
        # Faaliyet kaydı değişmedi (sorumlu geçmiş için kalır).
        f = await _taze(db, TrainingCorrectiveAction, faaliyet_id)
        assert f.status == "ACIK" and f.sorumlu_user_id == o.tek_id
