"""Test altyapısı.

Üç şey kaynak projeden bilinçli olarak farklı (plan §7):

1. **Gömülü Postgres YOK.** `pgserver` PostgreSQL 16.2 getiriyor ve uzantı
   listesinde `btree_gist` yok; ERP'nin çekirdek kısıtı
   `EXCLUDE USING gist (device_id WITH =, tstzrange(...) WITH &&)`
   o uzantı olmadan yazılamaz. Testler Compose'daki PostgreSQL 17'ye bağlanır.

2. **Şema `alembic upgrade head` ile kurulur**, `Base.metadata.create_all` ile
   değil. Böylece her koşu migration zincirini de doğrular — 60 tabloya
   çıkacak bir şemada kısmi indeks/EXCLUDE kısıtlarını conftest'e elle
   kopyalamak sürdürülemezdi.

3. **AYRI VERİTABANI.** Testler asla geliştirme veritabanına dokunmaz:
   `dengeerp` yerine `dengeerp_test`. Her test öncesi tablolar boşaltılır.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — modellerin tamamı metadata'ya kaydolsun
from app.config import get_config

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Windows geliştirme makinesi: psycopg async ProactorEventLoop ile çalışmaz.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Referans tabloları dahil her şey temizlenir; alembic_version kalır.
_TRUNCATE = """
TRUNCATE TABLE audit_logs, attachments, sim_device_history, sim_plan_history,
               sim_cards, device_status_history, devices, vehicles,
               product_bundle_items, products, installation_partners,
               contacts, addresses, accounts, sessions, login_attempts,
               settings, card_comments, card_members, card_labels, cards,
               board_labels, board_columns, boards,
               user_permissions, users, role_permissions, roles, permissions,
               service_visits, service_vehicles, service_unavailability,
               maintenance_generation_runs, account_merges,
               rental_catalog_items, rental_inventory_movements, stock_count_lines,
               service_alert_reads, training_observation_ratings,
               rental_counts, rental_count_lines, service_notification_prefs,
               service_mail_outbox, course_competencies, service_competency_requirements,
               belge_sayaclari
RESTART IDENTITY CASCADE
"""


def _test_database_url() -> str:
    """TEST_DATABASE_URL verilmişse onu, yoksa geliştirme URL'sinin `_test`
    eklenmiş halini kullanır. Aynı veritabanına ASLA düşmez."""
    if env := os.getenv("TEST_DATABASE_URL"):
        return env
    parts = urlsplit(get_config().database_url)
    dev_db = parts.path.lstrip("/")
    return urlunsplit(parts._replace(path=f"/{dev_db}_test"))


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = _test_database_url()
    assert url != get_config().database_url, "Test veritabanı geliştirme veritabanıyla aynı olamaz"
    return url


@pytest.fixture(scope="session", autouse=True)
def _schema(test_db_url: str) -> None:
    """Test veritabanını (yoksa) oluşturur ve migration'ları uygular."""
    parts = urlsplit(test_db_url)
    db_name = parts.path.lstrip("/")
    admin_url = urlunsplit(parts._replace(path="/postgres"))

    import psycopg

    sync_admin = admin_url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(sync_admin, autocommit=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
            ).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{db_name}"')
    except psycopg.OperationalError as exc:  # pragma: no cover - ortam hatası
        pytest.skip(f"PostgreSQL'e bağlanılamadı ({exc}). 'make db' ile ayağa kaldırın.")

    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": test_db_url},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session", autouse=True)
def _dosya_dizini(tmp_path_factory) -> None:
    """Ek yükleme testleri geliştirme dosya dizinine YAZMAMALI.

    `FILES_DIR` oturum başına geçici bir dizine çevrilir; aksi halde her test
    koşusu `var/files` altına çöp bırakırdı ve "aynı içerik bir kez saklanır"
    testi önceki koşudan kalan dosyayla yanıltıcı biçimde geçerdi.
    """
    from app.config import get_config

    get_config.cache_clear()
    os.environ["FILES_DIR"] = str(tmp_path_factory.mktemp("files"))
    # Testler MFA'sız kullanıcılarla iş mantığını sınıyor; zorunluluk açık
    # kalsaydı hepsi kurulum kapısına takılırdı. Kapının KENDİSİ ayrıca test
    # ediliyor (tests/integration/test_mfa_zorunlulugu.py), orada açılıyor.
    os.environ["MFA_ZORUNLU"] = "false"
    get_config.cache_clear()


@pytest_asyncio.fixture
async def engine(test_db_url: str):
    engine = create_async_engine(test_db_url)
    async with engine.begin() as conn:
        await conn.execute(text(_TRUNCATE))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _saha_ulasim_varsayilan(request, monkeypatch):
    """Saha ulaşım/km zorunluluğu (KARARLAR 2026-11-20 §1) varsayılan testlerde KAPALI.

    Var olan yüzlerce test GÜVENLİK işini ulaşım girmeden işleme alıp
    tamamlıyor. Kural kendi testinde `@pytest.mark.saha_ulasim` ile açık sınanır.
    """
    if request.node.get_closest_marker("saha_ulasim") is not None:
        return
    from app.services import settings as ayarlar

    monkeypatch.setitem(ayarlar.DEFAULTS, "servis_saha_ulasim_zorunlu", False)
    # Telsiz atölyesinde teslim öncesi seri okutma (§4) aynı işaretle açılır.
    monkeypatch.setitem(ayarlar.DEFAULTS, "atolye_teslim_seri_okutma", False)


@pytest.fixture(autouse=True)
def _seri_okutma_varsayilan(request, monkeypatch):
    """Cihazlı işte açılış/kapanış seri okutması (2026-11-23) varsayılan testlerde KAPALI.

    Var olan yüzlerce test arıza/kurulum işini serisiz ya da kaynaksız seriyle
    açıp tamamlıyor. Kural kendi testlerinde `@pytest.mark.seri_okutma` ile
    gerçek varsayılanıyla (açık) sınanır (`tests/integration/test_seri_okutma.py`).
    """
    if request.node.get_closest_marker("seri_okutma") is not None:
        return
    from app.services import settings as ayarlar

    monkeypatch.setitem(ayarlar.DEFAULTS, "servis_seri_okutma_zorunlu", False)


@pytest.fixture(autouse=True)
def _sirket_ayrimi_varsayilan(request, monkeypatch):
    """Şirket ayrımı (KARARLAR 2026-11-04 §1) varsayılan testlerde NÖTR.

    Var olan yüzlerce test, şirket kavramı yokken yazıldı: TUMU kapsamlı
    yönetici aynı testte GUVENLIK (ELEKTRONİK) ve HABERLESME (TELEKOM) işini
    birlikte görür, mobilite testleri teknik servis kullanıcısıyla aynı
    oturumda cihaz ekranını açar. Şirket tek bir etkin değere bağlı olduğu için
    bu testlere "makul" bir varsayılan şirket yoktur. Bu yüzden şirket
    süzgecinin TEK noktası (`services/sirketler.etkin_birimler`) ve mobilite
    kapısı (`mobilite_acik_mi`) varsayılan testlerde süzgeçsiz sürüme çevrilir;
    birim kapsamı, fail-closed ve sayı = liste kuralları aynen sınanır.

    Şirket ayrımının KENDİSİ `@pytest.mark.sirket_ayrimi` işaretli testlerde
    gerçek kodla sınanır (`tests/integration/test_sirket_ayrimi.py`). MFA
    zorunluluğu da aynı kalıpla kapatılıp kendi testinde açılıyor.
    """
    if request.node.get_closest_marker("sirket_ayrimi") is not None:
        return
    from app.services import sirketler

    monkeypatch.setattr(sirketler, "etkin_birimler", lambda user: None)
    monkeypatch.setattr(sirketler, "mobilite_acik_mi", lambda user: True)


@pytest_asyncio.fixture
async def seeded(db):
    """Roller, izinler ve şirket kataloğu yüklenmiş veritabanı."""
    from app.seeds.dev import sync_permissions, sync_roles, sync_sirketler

    await sync_permissions(db)
    await sync_roles(db)
    await sync_sirketler(db)
    await db.commit()
    return db


@pytest_asyncio.fixture
async def client(session_factory, seeded):
    """Oturum çerezini taşıyan HTTP istemcisi; testler gerçek uçları çağırır."""
    import httpx

    from app.api.deps import get_clock
    from app.clock import FakeClock
    from app.db import get_session
    from app.main import app

    async def _session_override():
        async with session_factory() as s:
            yield s

    fake = FakeClock()
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_clock] = lambda: fake

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},  # CSRF başlığı
    ) as c:
        c.clock = fake  # testler zamanı ilerletebilsin
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def kullanici_ac(db):
    """Verilen rolde kullanıcı açan yardımcı."""
    from sqlalchemy import select

    from app.models import Role, User
    from app.services import auth as auth_service

    async def _make(username: str, role_code: str, password: str = "parola1234") -> User:
        role = await db.scalar(select(Role).where(Role.code == role_code))
        assert role is not None, f"rol yok: {role_code}"
        user = User(
            full_name=username.title(),
            username=username,
            password_hash=auth_service.hash_password(password),
            role_id=role.id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    return _make


@pytest_asyncio.fixture
async def urun_ac(db):
    """Verilen kimlik tipinde ürün açar."""
    from app.models import Product

    async def _make(code: str, identity_kind: str = "IMEI", **kw) -> Product:
        urun = Product(code=code, name=f"{code} Ürün", identity_kind=identity_kind, **kw)
        db.add(urun)
        await db.commit()
        await db.refresh(urun)
        return urun

    return _make


@pytest_asyncio.fixture
async def cihaz_ac(db, urun_ac):
    """Cihaz açar; ürün verilmezse IMEI tipinde bir ürün üretir."""
    from app.models import Device

    varsayilan: dict = {}

    async def _make(*, imei=None, serial_no=None, urun=None, **kw) -> Device:
        if urun is None:
            if "imei" not in varsayilan:
                varsayilan["imei"] = await urun_ac("TEST-IMEI", "IMEI")
            urun = varsayilan["imei"]
        cihaz = Device(
            imei=imei,
            serial_no=serial_no,
            product_id=urun.id,
            identity_kind=urun.identity_kind,
            **kw,
        )
        db.add(cihaz)
        await db.commit()
        await db.refresh(cihaz)
        return cihaz

    return _make


@pytest_asyncio.fixture
async def hat_ac(db):
    from app.models import SimCard

    async def _make(iccid: str, **kw) -> SimCard:
        hat = SimCard(iccid=iccid, **kw)
        db.add(hat)
        await db.commit()
        await db.refresh(hat)
        return hat

    return _make


# --- Teknik servis yardımcıları (TS-013) -------------------------------------------
#
# Kapsam testleri "iki birimden iki şef" kalıbıyla yazılır (00 §6.3/7): A
# birimindeki kullanıcı B birimindeki kaydı GÖREMEMELİ ve DEĞİŞTİREMEMELİ. Her
# test dosyası bu kayıtları kendi elle kursaydı zorunlu alanlar (kategori,
# numara, müşteri FK'si) dosyadan dosyaya ayrışırdı; yardımcılar tek yerde.
# Kayıtlar servis katmanını DEĞİL doğrudan ORM'yi kullanır: kapsam testinin
# konusu uç, kurulum değil — servis fonksiyonu henüz yazılmamış bir dalgada da
# çalışır.

_TEST_ANI = "2026-01-01T09:00:00+00:00"


@pytest_asyncio.fixture
async def rol_ac(db):
    """Teste özel rol açar: `rol_ac("T_SEF", ["servis.gor"], "KENDI_BIRIMI")`.

    İzin kodu katalogda yoksa (paralel paket henüz eklemediyse) `permissions`
    tablosuna da eklenir; böylece kapsam altyapısı rol kataloğundan bağımsız
    sınanır. Gerçek rol kataloğunun kendisi `test_permissions` ve yetki
    matrisiyle sınanır.
    """
    from sqlalchemy.dialects.postgresql import insert

    from app.models import Permission, Role, RolePermission

    async def _make(kod: str, izinler, kapsam: str = "TUMU") -> Role:
        for izin in izinler:
            await db.execute(
                insert(Permission)
                .values(code=izin, module="Test", description=f"test: {izin}")
                .on_conflict_do_nothing()
            )
        rol = Role(code=kod, name=kod.title(), scope=kapsam, is_system=False)
        rol.permissions = [RolePermission(permission_code=i) for i in izinler]
        db.add(rol)
        await db.commit()
        await db.refresh(rol)
        return rol

    return _make


@pytest_asyncio.fixture
async def birimli_kullanici_ac(db, kullanici_ac):
    """Rol + birim üyeliğiyle kullanıcı: `await birimli_kullanici_ac("sef_a", "SERVIS_SEF",
    ["GUVENLIK"])`. İlk birim birincildir (ya da `birincil=`). Birimsiz kullanıcı
    için `birimler=[]` (fail-closed testleri)."""
    from sqlalchemy import select

    from app.models import User, UserUnit

    async def _make(
        username: str,
        rol: str,
        birimler=("GUVENLIK",),
        *,
        birincil: str | None = None,
        saha_rolu: str | None = None,
        password: str = "parola1234",
    ) -> User:
        user = await kullanici_ac(username, rol, password)
        birincil = birincil or (birimler[0] if birimler else None)
        for b in birimler:
            db.add(UserUnit(user_id=user.id, birim=b, is_primary=(b == birincil)))
        if saha_rolu is not None:
            user.saha_rolu = saha_rolu
        kimlik = user.id
        await db.commit()
        # Birimler selectin ile yüklenir; ilişkiyi tazelemek için yeniden oku.
        db.expire(user)
        return await db.scalar(select(User).where(User.id == kimlik))

    return _make


async def _musteri(db, ad: str = "Test Müşteri A.Ş."):
    from app.models import Account

    hesap = Account(title=ad, is_musteri=True)
    db.add(hesap)
    await db.flush()
    return hesap


@pytest_asyncio.fixture
async def lokasyon_ac(db):
    """Müşteri tesisi (`addresses.kind='TESIS'`); hesap verilmezse açılır."""
    from app.models import Address

    sayac = {"n": 0}

    async def _make(hesap=None, *, ad: str | None = None, il: str = "İstanbul", **kw) -> Address:
        sayac["n"] += 1
        hesap = hesap or await _musteri(db, f"Lokasyon Müşterisi {sayac['n']}")
        adres = Address(
            account_id=hesap.id,
            kind="TESIS",
            label="Tesis",
            site_name=ad or f"Test Tesisi {sayac['n']}",
            city=il,
            **kw,
        )
        db.add(adres)
        await db.commit()
        await db.refresh(adres)
        return adres

    return _make


@pytest_asyncio.fixture
async def servis_isi_ac(db):
    """Servis işi açar (ORM ile). `atananlar` verilirse ilk kişi sorumlu
    teknisyen olur (KENDI_ISLERI kapsamı aktif atamaya bakar)."""
    from datetime import date, datetime

    from app.models import (
        ServiceFrekansBilgisi,
        ServiceOrder,
        ServiceOrderAssignment,
        ServiceOrderSerial,
    )
    from app.services.normalize import normalize_seri
    from app.services.teknik_servis import cihaz_bilgisi, numara
    from app.services.teknik_servis.is_emirleri import tur_kategorisi

    async def _make(
        *,
        birim: str = "GUVENLIK",
        musteri=None,
        lokasyon=None,
        tur: str = "ARIZA",
        durum: str = "MUSTERI_TALEBI",
        konu: str = "Test arızası",
        atananlar=(),
        seri: str | None = "TEST-SERI-1",
        frekans: dict | None = None,
        **kw,
    ) -> ServiceOrder:
        """`seri`/`frekans`: KARARLAR §12 kapanış kuralı olan arıza işine
        (Güvenlik → seri, Haberleşme → frekans) varsayılan cihaz bilgisi;
        kuralı sınayan test `seri=None` verir."""
        if musteri is None:
            musteri = await _musteri(db, f"Servis Müşterisi {birim}")
        onek = "PB" if tur == "PB" else "SRV"
        so = ServiceOrder(
            so_no=await numara.belge_no(db, "service_order_no_seq", onek, date(2026, 1, 1)),
            birim=birim,
            tur=tur,
            kategori=tur_kategorisi(tur),
            status=durum,
            customer_id=musteri.id,
            address_id=lokasyon.id if lokasyon is not None else None,
            konu=konu,
            **kw,
        )
        db.add(so)
        await db.flush()
        kural = cihaz_bilgisi.kural(so)
        if kural is not None and seri is not None:
            db.add(
                ServiceOrderSerial(
                    service_order_id=so.id, seri_no=seri, seri_norm=normalize_seri(seri)
                )
            )
            if kural == cihaz_bilgisi.FREKANS:
                db.add(
                    ServiceFrekansBilgisi(
                        service_order_id=so.id,
                        seri_no=seri,
                        kaynak="TEKNISYEN",
                        frekans=frekans or {"role_tx": "427.1125", "role_rx": "417.1125"},
                    )
                )
            await db.flush()
        an = datetime.fromisoformat(_TEST_ANI)
        for sira, kisi in enumerate(atananlar):
            db.add(
                ServiceOrderAssignment(
                    service_order_id=so.id,
                    user_id=kisi.id,
                    rol="TEKNISYEN",
                    is_lead=(sira == 0),
                    assigned_at=an,
                )
            )
        await db.commit()
        await db.refresh(so)
        return so

    return _make


@pytest_asyncio.fixture
async def ekipman_ac(db):
    """Kurulu ekipman (servis kütüğü) açar."""
    from app.models import ServiceEquipment

    async def _make(
        *,
        birim: str = "GUVENLIK",
        musteri=None,
        lokasyon=None,
        tip: str = "XRAY",
        seri: str | None = "SN-0001",
        **kw,
    ) -> ServiceEquipment:
        if musteri is None:
            musteri = await _musteri(db, f"Ekipman Müşterisi {birim}")
        ekipman = ServiceEquipment(
            birim=birim,
            equipment_type=tip,
            serial_no=seri,
            account_id=musteri.id,
            address_id=lokasyon.id if lokasyon is not None else None,
            **kw,
        )
        db.add(ekipman)
        await db.commit()
        await db.refresh(ekipman)
        return ekipman

    return _make


@pytest_asyncio.fixture
async def sozlesme_ac(db):
    """Bakım sözleşmesi açar (varsayılan TASLAK; numara `BAKIM-NNNN`)."""
    from app.models import MaintenanceContract
    from app.services.teknik_servis import numara

    async def _make(*, birim: str = "GUVENLIK", musteri=None, lokasyon=None, **kw):
        if musteri is None:
            musteri = await _musteri(db, f"Sözleşme Müşterisi {birim}")
        sozlesme = MaintenanceContract(
            contract_no=await numara.bakim_sozlesme_no(db),
            birim=birim,
            account_id=musteri.id,
            address_id=lokasyon.id if lokasyon is not None else None,
            **kw,
        )
        db.add(sozlesme)
        await db.commit()
        await db.refresh(sozlesme)
        return sozlesme

    return _make
