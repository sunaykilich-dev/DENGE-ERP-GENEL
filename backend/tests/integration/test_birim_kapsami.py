"""Teknik servis birim kapsamı — gerçek sorgularla (TS-003, plan §1.2).

Liste süzgeci ile tek kayıt kontrolü aynı kuraldan türemeli: ayrışırlarsa
listede görünmeyen bir işe kimliğiyle ulaşılır (canlıdaki hesap açığının
aynısı: cevap 404, yazma geçmiş). Her test liste sayısını VE tek kayıt
kararını birlikte sınar.

Fail-closed (KD-04): birim kapsamlı rolde birimi olmayan kullanıcı hiçbir şey
görmez; bilinmeyen kapsam dizesi de hiçbir şey görmez.
"""

from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models import (
    Account,
    Role,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServicePlanMember,
    ServiceVehicle,
    User,
    UserUnit,
)
from app.services import auth as auth_service
from app.services.normalize import tr_normkey
from app.services.teknik_servis import kapsam

pytestmark = pytest.mark.integration

_AN = datetime(2026, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def kisi_ac(seeded, db):
    """Rol + birim üyelikleriyle kullanıcı; kapsam yardımcılarının girdisi."""

    async def _make(username: str, role_code: str, birimler: tuple[str, ...] = ()) -> User:
        rol = await db.scalar(select(Role).where(Role.code == role_code))
        assert rol is not None, role_code
        kisi = User(
            full_name=username.title(),
            username=username,
            password_hash=auth_service.hash_password("parola1234"),
            role_id=rol.id,
        )
        kisi.birimler = [UserUnit(birim=b, is_primary=i == 0) for i, b in enumerate(birimler)]
        db.add(kisi)
        await db.commit()
        await db.refresh(kisi)
        return kisi

    return _make


@pytest_asyncio.fixture
async def isler(db, kisi_ac):
    """İki birimde, iki müşteride üç iş. Müşteri A'nın temsilcisi `satisci`."""
    temsilci = await kisi_ac("satisci", "SATIS")
    hesaplar = []
    for ad, sahip in (("Musteri A", temsilci.id), ("Musteri B", None)):
        h = Account(title=ad, title_key=tr_normkey(ad), is_musteri=True, sales_rep_id=sahip)
        db.add(h)
        hesaplar.append(h)
    await db.flush()
    kayitlar = {}
    for kod, birim, hesap in (
        ("SRV-1", "GUVENLIK", hesaplar[0]),
        ("SRV-2", "POC", hesaplar[0]),
        ("SRV-3", "POC", hesaplar[1]),
    ):
        so = ServiceOrder(
            so_no=kod,
            birim=birim,
            tur="ARIZA",
            kategori="GUNLUK_SERVIS",
            konu="Arıza",
            customer_id=hesap.id,
        )
        db.add(so)
        kayitlar[kod] = so
    await db.commit()
    return kayitlar


async def _gorunen(db, kisi: User) -> set[str]:
    stmt = kapsam.kapsam_isler(select(ServiceOrder.so_no), kisi, ServiceOrder.id)
    return set((await db.scalars(stmt)).all())


async def _sayi(db, kisi: User) -> int:
    stmt = kapsam.kapsam_isler(select(func.count(ServiceOrder.id)), kisi, ServiceOrder.id)
    return await db.scalar(stmt)


# --- Servis işleri ---------------------------------------------------------------


async def test_tumu_kapsami_hepsini_gorur(db, kisi_ac, isler):
    yonetici = await kisi_ac("yonetici", "SERVIS_YONETICI")
    assert await _gorunen(db, yonetici) == {"SRV-1", "SRV-2", "SRV-3"}
    assert not await kapsam.is_erisimi_yok_mu(db, yonetici, isler["SRV-1"])


async def test_kendi_birimi_yalniz_kendi_birimini_gorur(db, kisi_ac, isler):
    sef = await kisi_ac("sef", "SERVIS_SEF", ("POC",))
    assert await _gorunen(db, sef) == {"SRV-2", "SRV-3"}
    assert await _sayi(db, sef) == 2, "sayı = liste (sayı da sızıntıdır)"
    assert await kapsam.is_erisimi_yok_mu(db, sef, isler["SRV-1"])
    assert not await kapsam.is_erisimi_yok_mu(db, sef, isler["SRV-2"])


async def test_ek_birim_de_dikkate_alinir(db, kisi_ac, isler):
    sef = await kisi_ac("sef", "SERVIS_SEF", ("POC", "GUVENLIK"))
    assert await _gorunen(db, sef) == {"SRV-1", "SRV-2", "SRV-3"}


async def test_birimsiz_kendi_birimi_hicbir_sey_goremez(db, kisi_ac, isler):
    sef = await kisi_ac("sef", "SERVIS_SEF")
    assert await _gorunen(db, sef) == set()
    assert await _sayi(db, sef) == 0
    for so in isler.values():
        assert await kapsam.is_erisimi_yok_mu(db, sef, so)


async def test_kendi_isleri_aktif_atama_ve_aktif_plan_uyeligi(db, kisi_ac, isler):
    tekn = await kisi_ac("tekn", "SERVIS_TEKNISYEN", ("GUVENLIK",))
    # SRV-1: aktif atama. SRV-2: çıkarılmış atama (görünmez). SRV-3: aktif plan üyeliği.
    db.add_all(
        [
            ServiceOrderAssignment(
                service_order_id=isler["SRV-1"].id,
                user_id=tekn.id,
                rol="TEKNISYEN",
                assigned_at=_AN,
            ),
            ServiceOrderAssignment(
                service_order_id=isler["SRV-2"].id,
                user_id=tekn.id,
                rol="TEKNISYEN",
                assigned_at=_AN,
                removed_at=_AN,
            ),
        ]
    )
    plan = ServicePlan(
        service_order_id=isler["SRV-3"].id,
        plan_date=date(2026, 1, 2),
        duration_min=60,
        change_type="ILK_PLAN",
    )
    db.add(plan)
    await db.flush()
    db.add(ServicePlanMember(plan_id=plan.id, user_id=tekn.id, rol="TEKNISYEN"))
    await db.commit()

    # Başka birimdeki (POC) işe atandıysa da görür: birimler arası destek.
    assert await _gorunen(db, tekn) == {"SRV-1", "SRV-3"}
    assert await kapsam.is_erisimi_yok_mu(db, tekn, isler["SRV-2"]), "çıkarılan atama kapsam vermez"

    # Plan pasiflenince (erteleme/iptal) üyelik kapsam vermez.
    plan.is_active = False
    plan.cancelled_at = _AN
    await db.commit()
    assert await _gorunen(db, tekn) == {"SRV-1"}


async def test_kendi_isleri_birimsizse_atansa_da_goremez(db, kisi_ac, isler):
    """Fail-closed: birim üyeliği verilmemiş teknisyen (eksik kurulum) hiçbir şey görmez."""
    tekn = await kisi_ac("tekn", "SERVIS_TEKNISYEN")
    db.add(
        ServiceOrderAssignment(
            service_order_id=isler["SRV-1"].id, user_id=tekn.id, rol="TEKNISYEN", assigned_at=_AN
        )
    )
    await db.commit()
    assert await _gorunen(db, tekn) == set()


async def test_kendi_musterileri_birimsizse_kendi_musterisinin_isleri(db, kisi_ac, isler):
    """KARARLAR 2026-11-04 §7.8 (TS-003 kabulünün yerine): birimsiz satış
    temsilcisi kendi müşterisinin işlerini görür (şirket ayrımı ayrıca sınanır),
    başka müşterinin işini görmez."""
    satisci = await db.scalar(select(User).where(User.username == "satisci"))
    assert await _gorunen(db, satisci) == {"SRV-1", "SRV-2"}
    assert not await kapsam.is_erisimi_yok_mu(db, satisci, isler["SRV-1"])
    assert await kapsam.is_erisimi_yok_mu(db, satisci, isler["SRV-3"])


async def test_kendi_musterileri_birimliyse_yalniz_kendi_musterisinin_birimindeki_is(
    db, kisi_ac, isler
):
    satisci = await db.scalar(select(User).where(User.username == "satisci"))
    db.add(UserUnit(user_id=satisci.id, birim="POC", is_primary=True))
    await db.commit()
    await db.refresh(satisci)
    # SRV-2: kendi müşterisi + POC. SRV-1 kendi müşterisi ama GUVENLIK; SRV-3 POC ama başkasının.
    assert await _gorunen(db, satisci) == {"SRV-2"}


async def test_bilinmeyen_kapsam_hicbir_sey_gormez(db, kisi_ac, isler):
    rol = Role(code="GARIP", name="Garip", scope="UYDURMA", is_system=False)
    db.add(rol)
    await db.commit()
    kisi = await kisi_ac("garip", "GARIP", ("POC",))
    assert await _gorunen(db, kisi) == set()
    araclar = kapsam.kapsam_birim(select(ServiceVehicle.id), kisi, ServiceVehicle.birim)
    assert (await db.scalars(araclar)).all() == []


async def test_bagli_tablo_is_kimligi_uzerinden_suzulur(db, kisi_ac, isler):
    """Plan/zaman/onay listeleri `service_order_id` kolonuyla süzülür."""
    for so in isler.values():
        db.add(
            ServicePlan(
                service_order_id=so.id,
                plan_date=date(2026, 1, 2),
                duration_min=60,
                change_type="ILK_PLAN",
            )
        )
    await db.commit()
    sef = await kisi_ac("sef", "SERVIS_SEF", ("GUVENLIK",))
    stmt = kapsam.kapsam_isler(select(ServicePlan), sef, ServicePlan.service_order_id)
    planlar = (await db.scalars(stmt)).all()
    assert [p.service_order_id for p in planlar] == [isler["SRV-1"].id]


# --- Diğer birimli varlıklar (birimi NULL olabilen: araç havuzu) ------------------


async def test_birimli_varlik_ortak_kayit_gorunur_baska_birim_gorunmez(db, kisi_ac):
    for plaka, birim in (("34 AA 1", "POC"), ("34 AA 2", "GUVENLIK"), ("34 AA 3", None)):
        db.add(ServiceVehicle(plate=plaka, birim=birim))
    await db.commit()

    async def _plakalar(kisi, **kw):
        stmt = kapsam.kapsam_birim(select(ServiceVehicle.plate), kisi, ServiceVehicle.birim, **kw)
        return set((await db.scalars(stmt)).all())

    sef = await kisi_ac("sef", "SERVIS_SEF", ("POC",))
    assert await _plakalar(sef) == {"34 AA 1", "34 AA 3"}
    assert await _plakalar(sef, birimsiz_gorunur=False) == {"34 AA 1"}
    assert await _plakalar(await kisi_ac("bos", "SERVIS_SEF")) == set()
    assert len(await _plakalar(await kisi_ac("yon", "SERVIS_YONETICI"))) == 3
    # KENDI_MUSTERILERI: birim kesişimi (birimsiz temsilci → hiçbiri).
    assert await _plakalar(await kisi_ac("satis2", "SATIS")) == set()


# --- Personel -----------------------------------------------------------------------


async def test_personel_kapsami_ortak_birim_ister_birimsiz_personel_gorunmez(db, kisi_ac):
    poc_sef = await kisi_ac("poc_sef", "SERVIS_SEF", ("POC",))
    poc_tekn = await kisi_ac("poc_tekn", "SERVIS_TEKNISYEN", ("POC",))
    cift = await kisi_ac("cift", "SERVIS_TEKNISYEN", ("MOBILITE", "POC"))
    guv = await kisi_ac("guv_tekn", "SERVIS_TEKNISYEN", ("GUVENLIK",))
    birimsiz = await kisi_ac("birimsiz", "DEPO")
    hepsi = {"poc_sef", "poc_tekn", "cift", "guv_tekn", "birimsiz"}

    async def _adlar(kisi):
        stmt = kapsam.kapsam_personel(
            select(User.username).where(User.username.in_(hepsi)), kisi, User.id
        )
        return set((await db.scalars(stmt)).all())

    assert await _adlar(poc_sef) == {"poc_sef", "poc_tekn", "cift"}
    assert await kapsam.personel_disinda_mi(db, poc_sef, guv.id)
    assert await kapsam.personel_disinda_mi(db, poc_sef, birimsiz.id)
    assert not await kapsam.personel_disinda_mi(db, poc_sef, cift.id)

    ik = await kisi_ac("ik", "IK")
    assert await _adlar(ik) == hepsi, "TUMU birimsiz personeli de görür"
    assert not await kapsam.personel_disinda_mi(db, ik, birimsiz.id)

    bos_sef = await kisi_ac("bos_sef", "SERVIS_SEF")
    assert await _adlar(bos_sef) == set()
    assert await kapsam.personel_disinda_mi(db, bos_sef, poc_tekn.id)
