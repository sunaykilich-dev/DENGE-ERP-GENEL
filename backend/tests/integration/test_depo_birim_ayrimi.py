"""Servis depoları birimlere tamamen ayrı (kullanıcı isteği 2026-11-09).

"Depo işlerini haberleşme güvenlik diye tamamen ayır, teknisyenler diğer
birimlerin deposunu görmesin." Sınananlar:

- Teknisyen/şef başka birimin deposunu listede, seçim kutusunda, stok ve
  hareket sorgusunda görmez; yönetici (TUMU) hepsini görür.
- Kimlikle doğrudan erişim (çıkış, iade, sayım, giriş, depo güncelleme,
  satın alma mal kabulü) başka birimin deposunda 404 ve hiçbir şey yazılmaz.
- İki birime üye kişi ya da yönetici bile Güvenlik deposundan Haberleşme
  işine parça çıkamaz, birimler arası transfer yapamaz (409).
- Servis deposu birimsiz açılamaz; tek birimli tanımlayıcıda birim kendiliğinden.
- Migration eşlemesi: araç deposu sahibinin birimi, ad/kod ipucu, belirsiz boş.
"""

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.clock import FakeClock
from app.models import AuditLog, Product, StockCount, StockMovement, Warehouse
from app.services.teknik_servis import parca as svc

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/parca"


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


async def _depo(db, code, birim, *, user=None) -> Warehouse:
    w = Warehouse(
        code=code,
        name=f"{code} Deposu",
        birim=birim,
        servis_deposu=True,
        location_type="TEKNISYEN" if user is not None else "BOLGE_DEPO",
        user_id=user.id if user is not None else None,
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


async def _anlik(db) -> dict:
    return {
        "hareket": await db.scalar(select(func.count()).select_from(StockMovement)),
        "toplam": await db.scalar(select(func.coalesce(func.sum(StockMovement.qty), 0))),
        "sayim": await db.scalar(select(func.count()).select_from(StockCount)),
        "denetim": await db.scalar(select(func.count()).select_from(AuditLog)),
        "depo": await db.scalar(select(func.count()).select_from(Warehouse)),
    }


class Ortam:
    pass


@pytest.fixture
async def o(db, birimli_kullanici_ac, kullanici_ac, servis_isi_ac, giris):
    """Haberleşme ve Güvenlik: birer depo, birer teknisyen (araç depolu), şef,
    iş; iki birime üye depocu; TUMU yönetici."""
    x = Ortam()
    x.tekn_h_u = await birimli_kullanici_ac("tekn_h", "SERVIS_TEKNISYEN", ["HABERLESME"])
    x.tekn_g_u = await birimli_kullanici_ac("tekn_g", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_h", "SERVIS_SEF", ["HABERLESME"])
    x.cift_u = await birimli_kullanici_ac("depo_hg", "SERVIS_DEPO", ["HABERLESME", "GUVENLIK"])
    await kullanici_ac("yonetici", "SERVIS_YONETICI")
    x.hab = await _depo(db, "SRV-HAB", "HABERLESME")
    x.guv = await _depo(db, "SRV-GUV", "GUVENLIK")
    x.arac_h = await _depo(db, "ARAC-H", "HABERLESME", user=x.tekn_h_u)
    x.arac_g = await _depo(db, "ARAC-G", "GUVENLIK", user=x.tekn_g_u)
    x.urun = Product(
        code="YP-B", name="Birim Parçası", type="AKSESUAR", identity_kind="YOK", yedek_parca=True
    )
    db.add(x.urun)
    await db.commit()
    for depo in (x.hab, x.guv, x.arac_h, x.arac_g):
        await svc.hareket_yaz(
            db,
            tur="GIRIS",
            satirlar=[svc.Satir(x.urun.id, 5)],
            user=x.cift_u,
            clock=FakeClock(),
            warehouse_id=depo.id,
        )
    await db.commit()
    x.is_h = await servis_isi_ac(birim="HABERLESME", atananlar=[x.tekn_h_u])
    x.is_g = await servis_isi_ac(birim="GUVENLIK", atananlar=[x.tekn_g_u])
    x.tekn_h = await giris("tekn_h")
    x.tekn_g = await giris("tekn_g")
    x.sef_h = await giris("sef_h")
    x.cift = await giris("depo_hg")
    x.yonetici = await giris("yonetici")
    return x


def _kodlar(r) -> list[str]:
    assert r.status_code == 200, r.text
    return sorted(d["code"] for d in r.json())


async def test_baska_birimin_deposu_listede_gorunmez(o) -> None:
    assert _kodlar(await o.tekn_h.get(f"{URL}/depolar")) == ["ARAC-H", "SRV-HAB"]
    assert _kodlar(await o.tekn_g.get(f"{URL}/depolar")) == ["ARAC-G", "SRV-GUV"]
    assert _kodlar(await o.sef_h.get(f"{URL}/depolar?pasifler=true")) == ["ARAC-H", "SRV-HAB"]
    # İki birime üye ve tüm birimleri gören (TUMU) hepsini görür.
    hepsi = ["ARAC-G", "ARAC-H", "SRV-GUV", "SRV-HAB"]
    assert _kodlar(await o.cift.get(f"{URL}/depolar")) == hepsi
    assert _kodlar(await o.yonetici.get(f"{URL}/depolar")) == hepsi


async def test_stok_ve_hareket_sorgusunda_baska_birim_yok(o) -> None:
    satir = (await o.sef_h.get(f"{URL}/stok")).json()[0]
    assert satir["toplam"] == 10  # SRV-HAB + ARAC-H
    assert {d["depo_kodu"] for d in satir["depolar"]} == {"SRV-HAB", "ARAC-H"}
    # Başka birimin deposu kimlikle sorgulansa da stok/hareket dönmez.
    r = await o.sef_h.get(f"{URL}/stok?depo_id={o.guv.id}")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert all(s["toplam"] == 0 for s in r.json())
    r = await o.sef_h.get(f"{URL}/hareketler?depo_id={o.guv.id}")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        govde = r.json()
        satirlar = govde["satirlar"] if isinstance(govde, dict) else govde
        assert satirlar == []
    assert (await o.yonetici.get(f"{URL}/stok")).json()[0]["toplam"] == 20


async def test_kimlikle_baska_birim_deposu_404_veri_degismez(o, db) -> None:
    istekler = [
        (
            o.tekn_h,
            "POST",
            f"{URL}/cikis",
            {
                "service_order_id": o.is_h.id,
                "depo_id": o.guv.id,
                "satirlar": [{"product_id": o.urun.id, "adet": 1}],
            },
        ),
        (
            o.tekn_h,
            "POST",
            f"{URL}/cikis",
            {
                "service_order_id": o.is_h.id,
                "depo_id": o.arac_g.id,
                "satirlar": [{"product_id": o.urun.id, "adet": 1}],
            },
        ),
        (
            o.sef_h,
            "POST",
            f"{URL}/iade",
            {
                "service_order_id": o.is_h.id,
                "depo_id": o.guv.id,
                "satirlar": [{"product_id": o.urun.id, "adet": 1}],
            },
        ),
    ]
    for ist, yontem, yol, govde in istekler:
        once = await _anlik(db)
        r = await ist.request(yontem, yol, json=govde)
        assert r.status_code == 404, (yol, r.status_code, r.text)
        assert await _anlik(db) == once, yol
    # Kendi biriminin deposundan çıkış olur.
    r = await o.tekn_h.post(
        f"{URL}/cikis",
        json={
            "service_order_id": o.is_h.id,
            "depo_id": o.arac_h.id,
            "satirlar": [{"product_id": o.urun.id, "adet": 1}],
        },
    )
    assert r.status_code == 201, r.text


async def test_tek_birimli_depocu_baska_birim_deposuna_yazamaz(
    o, db, birimli_kullanici_ac, giris
) -> None:
    await birimli_kullanici_ac("depo_h", "SERVIS_DEPO", ["HABERLESME"])
    depo_h = await giris("depo_h")
    satir = [{"product_id": o.urun.id, "adet": 1}]
    istekler = [
        ("POST", f"{URL}/giris", {"depo_id": o.guv.id, "satirlar": satir}),
        ("POST", f"{URL}/zayi", {"depo_id": o.guv.id, "satirlar": satir, "gerekce": "Kırık"}),
        ("POST", f"{URL}/sayimlar", {"depo_id": o.guv.id}),
        (
            "POST",
            f"{URL}/transfer",
            {"kaynak_depo_id": o.guv.id, "hedef_depo_id": o.hab.id, "satirlar": satir},
        ),
    ]
    for yontem, yol, govde in istekler:
        once = await _anlik(db)
        r = await depo_h.request(yontem, yol, json=govde)
        assert r.status_code == 404, (yol, r.status_code, r.text)
        assert await _anlik(db) == once, yol


async def test_birimler_arasi_cikis_ve_transfer_409(o, db) -> None:
    """Her iki depoyu da gören kişi bile stokları karıştıramaz."""
    satir = [{"product_id": o.urun.id, "adet": 1}]
    for ist in (o.cift, o.yonetici):
        istekler = [
            (
                f"{URL}/cikis",
                {"service_order_id": o.is_h.id, "depo_id": o.guv.id, "satirlar": satir},
            ),
            (
                f"{URL}/iade",
                {"service_order_id": o.is_g.id, "depo_id": o.hab.id, "satirlar": satir},
            ),
            (
                f"{URL}/transfer",
                {"kaynak_depo_id": o.guv.id, "hedef_depo_id": o.hab.id, "satirlar": satir},
            ),
        ]
        for yol, govde in istekler:
            once = await _anlik(db)
            r = await ist.post(yol, json=govde)
            assert r.status_code == 409, (yol, r.status_code, r.text)
            assert "birim" in r.text.lower()
            assert await _anlik(db) == once, yol
    # Aynı birim içinde transfer serbest.
    r = await o.cift.post(
        f"{URL}/transfer",
        json={"kaynak_depo_id": o.hab.id, "hedef_depo_id": o.arac_h.id, "satirlar": satir},
    )
    assert r.status_code == 201, r.text


async def test_depo_tanimi_birim_zorunlu(o, db, birimli_kullanici_ac, rol_ac, giris) -> None:
    await rol_ac("T_AYAR_HAB", ["sistem.ayar", "parca.gor"], "KENDI_BIRIMI")
    await rol_ac("T_AYAR_TUM", ["sistem.ayar", "parca.gor"], "TUMU")
    await birimli_kullanici_ac("ayar_h", "T_AYAR_HAB", ["HABERLESME"])
    await birimli_kullanici_ac("ayar_t", "T_AYAR_TUM", [])
    ayar_h = await giris("ayar_h")
    ayar_t = await giris("ayar_t")

    # Tek birimli tanımlayıcı birimi seçmek zorunda değil: kendi birimi yazılır.
    r = await ayar_h.post(f"{URL}/depolar", json={"code": "SRV-H2", "name": "Hab İkinci"})
    assert r.status_code == 201, r.text
    assert r.json()["birim"] == "HABERLESME"
    # Başka birime depo açamaz (varlığı gizli: 404).
    r = await ayar_h.post(
        f"{URL}/depolar", json={"code": "SRV-G2", "name": "Guv İkinci", "birim": "GUVENLIK"}
    )
    assert r.status_code == 404
    # Tüm birimleri gören tanımlayıcı birim seçmeli (rastgele atanmaz).
    r = await ayar_t.post(f"{URL}/depolar", json={"code": "SRV-X", "name": "Birimsiz"})
    assert r.status_code == 400 and "birim" in r.text.lower()
    # Araç deposu: teknisyenin birimi kendiliğinden; başka birim 400.
    r = await ayar_t.post(
        f"{URL}/depolar",
        json={
            "code": "ARAC-G9",
            "name": "Araç G9",
            "location_type": "TEKNISYEN",
            "user_id": o.tekn_g_u.id,
        },
    )
    assert r.status_code == 201 and r.json()["birim"] == "GUVENLIK", r.text
    r = await ayar_t.post(
        f"{URL}/depolar",
        json={
            "code": "ARAC-G8",
            "name": "Araç G8",
            "birim": "HABERLESME",
            "location_type": "TEKNISYEN",
            "user_id": o.tekn_g_u.id,
        },
    )
    assert r.status_code == 400, r.text
    # Birim boşaltılamaz; hareketi olan depo başka birime taşınamaz.
    r = await ayar_t.patch(f"{URL}/depolar", json={"depo_id": o.hab.id, "birim": None})
    assert r.status_code == 400
    r = await ayar_t.patch(f"{URL}/depolar", json={"depo_id": o.hab.id, "birim": "GUVENLIK"})
    assert r.status_code == 409
    await db.refresh(o.hab)
    assert o.hab.birim == "HABERLESME"
    # Şema da birimsiz servis deposunu reddeder.
    with pytest.raises(DBAPIError, match="ck_warehouse_servis_birim_zorunlu"):
        await db.execute(
            text("INSERT INTO warehouses (code, name, servis_deposu) VALUES ('Z1', 'Zz', true)")
        )
    await db.rollback()


async def test_mal_kabul_baska_birim_servis_deposuna_404(
    client, db, kullanici_ac, urun_ac, rol_ac, birimli_kullanici_ac, giris
) -> None:
    from test_satinalma_parca import _ortam as sa_ortam

    s, parca, servis_g, _, _ = await sa_ortam(client, db, kullanici_ac, urun_ac, doviz="TRY")
    hab = await _depo(db, "SA-HAB", "HABERLESME")
    await rol_ac("T_SA_HAB", ["satinalma.gor", "satinalma.yaz"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("sa_hab", "T_SA_HAB", ["HABERLESME"])
    sa_hab = await giris("sa_hab")
    kalem_id = s["kalemler"][0]["id"]
    once = await _anlik(db)
    r = await sa_hab.post(
        f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
        json={"kalem_id": kalem_id, "adet": 1, "warehouse_id": servis_g.id},
    )
    assert r.status_code == 404, r.text
    assert await _anlik(db) == once
    r = await sa_hab.post(
        f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
        json={"kalem_id": kalem_id, "adet": 1, "warehouse_id": hab.id},
    )
    assert r.status_code == 200, r.text
    assert await svc.bakiye(db, parca.id, hab.id) == 1


async def test_migration_eslemesi(client, db, birimli_kullanici_ac) -> None:
    """fba000000001 eşlemesi: araç deposu → sahibinin birincil birimi; ad/kod
    ipucu; belirsiz olan BOŞ kalır (rastgele atanmaz). Kısıt geçici düşürülüp
    işlem geri alınır (DDL Postgres'te işlem içindedir)."""
    import importlib.util
    from pathlib import Path

    yol = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "fba000000001_servis_deposu_birim_ayrimi.py"
    )
    spec = importlib.util.spec_from_file_location("mig_fba", yol)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    sahip = await birimli_kullanici_ac(
        "esle_t", "SERVIS_TEKNISYEN", ["HABERLESME", "GUVENLIK"], birincil="HABERLESME"
    )
    await db.execute(text("ALTER TABLE warehouses DROP CONSTRAINT ck_warehouse_servis_birim_zorunlu"))
    await db.execute(
        text(
            "INSERT INTO warehouses (code, name, servis_deposu, location_type, user_id) VALUES "
            "('ARAC-E', 'Araç', true, 'TEKNISYEN', :u), "
            "('HAB-MRK', 'Merkez', true, 'BOLGE_DEPO', NULL), "
            "('D-1', 'Güvenlik Sistemleri Deposu', true, 'BOLGE_DEPO', NULL), "
            "('D-2', 'Ortak Depo', true, 'BOLGE_DEPO', NULL), "
            "('HAB-GUV', 'Karma', true, 'BOLGE_DEPO', NULL), "
            "('MOB-1', 'Mobilite', false, 'BOLGE_DEPO', NULL)"
        ),
        {"u": sahip.id},
    )
    kalan = await db.run_sync(lambda s: mig.esle(s.connection()))
    birimler = dict(
        (await db.execute(text("SELECT code, birim FROM warehouses ORDER BY code"))).all()
    )
    await db.rollback()
    assert birimler == {
        "ARAC-E": "HABERLESME",
        "HAB-MRK": "HABERLESME",
        "D-1": "GUVENLIK",
        "D-2": None,
        "HAB-GUV": None,
        "MOB-1": None,  # mobilite deposuna dokunulmaz
    }
    assert sorted(k[1] for k in kalan) == ["D-2", "HAB-GUV"]
    # Geri alındı: kısıt yerinde.
    with pytest.raises(DBAPIError, match="ck_warehouse_servis_birim_zorunlu"):
        await db.execute(
            text("INSERT INTO warehouses (code, name, servis_deposu) VALUES ('Z2', 'Zz', true)")
        )
    await db.rollback()
