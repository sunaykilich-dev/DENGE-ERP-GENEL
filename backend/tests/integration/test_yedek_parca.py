"""Yedek parça ve servis stoğu: tek yazıcı, çıkış/iade/ters kayıt, transfer, sayım,
açılış, kart, talep, maliyet, mobilite sızıntı önlemi (TS-130…138)."""

import asyncio
import random
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import Integer, func, select, text
from sqlalchemy.exc import DBAPIError

from app.clock import FakeClock
from app.models import (
    AuditLog,
    Product,
    ServiceHold,
    ServiceOrder,
    ServiceOrderEvent,
    ServicePartRequest,
    StockMovement,
    User,
    Warehouse,
)
from app.services.teknik_servis import is_emirleri
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


@pytest.fixture
async def depo_ac(db):
    async def _make(code: str, *, birim=None, user=None, aktif=True) -> Warehouse:
        w = Warehouse(
            code=code,
            name=f"{code} Deposu",
            birim=birim,
            servis_deposu=True,
            location_type="TEKNISYEN" if user is not None else "BOLGE_DEPO",
            user_id=user.id if user is not None else None,
            is_active=aktif,
        )
        db.add(w)
        await db.commit()
        await db.refresh(w)
        return w

    return _make


@pytest.fixture
async def parca_ac(db):
    async def _make(code: str, *, min_stok=None, birim=None, aktif=True) -> Product:
        u = Product(
            code=code,
            name=f"{code} Parça",
            type="AKSESUAR",
            identity_kind="YOK",
            yedek_parca=True,
            min_stok=min_stok,
            birim=birim,
            is_active=aktif,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u

    return _make


@pytest.fixture
async def ortam(birimli_kullanici_ac, kullanici_ac, giris, depo_ac, parca_ac, servis_isi_ac):
    """Depocu (SERVIS_DEPO, GUVENLIK), yönetici (TUMU, maliyet görmez), admin
    (maliyet görür), GUVENLIK ortak depo, bir parça, açık bir servis işi."""
    depocu = await birimli_kullanici_ac("depocu", "SERVIS_DEPO", ["GUVENLIK"])
    await kullanici_ac("yonetici", "SERVIS_YONETICI")
    await kullanici_ac("admin_p", "ADMIN")
    depo = await depo_ac("SRV-G", birim="GUVENLIK")
    urun = await parca_ac("YP-1")
    so = await servis_isi_ac(birim="GUVENLIK")

    class Ortam:
        pass

    o = Ortam()
    o.depocu_u, o.depo, o.urun, o.so = depocu, depo, urun, so
    o.depocu = await giris("depocu")
    o.yonetici = await giris("yonetici")
    o.admin = await giris("admin_p")
    return o


async def _bakiye(db, urun, depo) -> int:
    return await svc.bakiye(db, urun.id, depo.id)


async def _giris(ist, depo, urun, adet, **ek):
    r = await ist.post(
        f"{URL}/giris",
        json={"depo_id": depo.id, "satirlar": [{"product_id": urun.id, "adet": adet, **ek}]},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _cikis(ist, so, depo, urun, adet):
    return await ist.post(
        f"{URL}/cikis",
        json={
            "service_order_id": so.id,
            "depo_id": depo.id,
            "satirlar": [{"product_id": urun.id, "adet": adet}],
        },
    )


async def _iade(ist, so, depo, urun, adet):
    return await ist.post(
        f"{URL}/iade",
        json={
            "service_order_id": so.id,
            "depo_id": depo.id,
            "satirlar": [{"product_id": urun.id, "adet": adet}],
        },
    )


# --- RBAC -----------------------------------------------------------------------------


async def test_rbac(ortam, kullanici_ac, birimli_kullanici_ac, giris) -> None:
    await kullanici_ac("montaj", "MONTAJ_KOORD")
    await birimli_kullanici_ac("tekn", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    montaj = await giris("montaj")
    assert (await montaj.get(f"{URL}/stok")).status_code == 403
    tekn = await giris("tekn")
    assert (await tekn.get(f"{URL}/stok")).status_code == 200
    r = await tekn.post(
        f"{URL}/giris",
        json={"depo_id": ortam.depo.id, "satirlar": [{"product_id": ortam.urun.id, "adet": 1}]},
    )
    assert r.status_code == 403
    assert (await tekn.get(f"{URL}/stok.xlsx")).status_code == 403
    assert (await tekn.post(f"{URL}/sayimlar", json={"depo_id": ortam.depo.id})).status_code == 403
    # Depo tanımı sistem.ayar ister (K15).
    r = await ortam.depocu.post(f"{URL}/depolar", json={"code": "X1", "name": "Xx Depo"})
    assert r.status_code == 403
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 2)


# --- Giriş / çıkış / iade (TS-130, 132, 133) ---------------------------------------------


async def test_giris_cikis_iade_net_sinir(ortam, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 10)
    r = await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 3)
    assert r.status_code == 201, r.text
    assert await _bakiye(db, ortam.urun, ortam.depo) == 7
    r = await _iade(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 4)
    assert r.status_code == 409 and "net" in r.json()["detail"]
    assert (await _iade(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 3)).status_code == 201
    assert await svc.net_cikis(db, ortam.so.id, ortam.urun.id) == 0
    # PARCA olayı birleşik geçmişte; maliyet anahtarı yok.
    olaylar = (
        await db.scalars(
            select(ServiceOrderEvent).where(
                ServiceOrderEvent.service_order_id == ortam.so.id,
                ServiceOrderEvent.olay_turu == "PARCA",
            )
        )
    ).all()
    assert len(olaylar) == 2 and "YP-1 × 3" in olaylar[0].ozet
    assert "unit_cost" not in str(olaylar[0].veri)
    # Denetim izi aynı transaction'da.
    assert await db.scalar(select(func.count()).where(AuditLog.action == "parca.cikis")) == 1


async def test_girdi_dogrulama(ortam) -> None:
    govde = {"depo_id": ortam.depo.id, "satirlar": [{"product_id": ortam.urun.id, "adet": 1}]}
    # İş emirli giriş yok (E11-03): alan 422.
    r = await ortam.depocu.post(f"{URL}/giris", json={**govde, "service_order_id": ortam.so.id})
    assert r.status_code == 422
    r = await ortam.depocu.post(
        f"{URL}/giris",
        json={**govde, "satirlar": [{"product_id": ortam.urun.id, "adet": 1.5}]},
    )
    assert r.status_code == 422
    r = await ortam.depocu.post(f"{URL}/giris", json={**govde, "document_no": "B" * 51})
    assert r.status_code == 422
    r = await ortam.depocu.post(f"{URL}/giris", json={**govde, "notes": "N" * 301})
    assert r.status_code == 422


async def test_kapali_ise_cikis_409(ortam, servis_isi_ac, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 10)
    for durum in ("TAMAMLANDI", "KAPATILDI", "IPTAL"):
        ek = {"cancel_reason": "Vazgeçildi"} if durum == "IPTAL" else {}
        so = await servis_isi_ac(birim="GUVENLIK", durum=durum, **ek)
        r = await _cikis(ortam.depocu, so, ortam.depo, ortam.urun, 1)
        assert r.status_code == 409
        assert r.json()["detail"] == "Kapalı iş emrine parça yazılamaz."
    for durum in ("BEKLEMEDE", "TEKRAR_ACILDI"):
        so = await servis_isi_ac(birim="GUVENLIK", durum=durum)
        assert (await _cikis(ortam.depocu, so, ortam.depo, ortam.urun, 1)).status_code == 201
    assert await _bakiye(db, ortam.urun, ortam.depo) == 8


async def test_stok_yetersiz_hicbir_satir_yazilmaz(ortam, parca_ac, db) -> None:
    ikinci = await parca_ac("YP-2")
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 5)
    once = await db.scalar(select(func.count()).select_from(StockMovement))
    r = await ortam.depocu.post(
        f"{URL}/cikis",
        json={
            "service_order_id": ortam.so.id,
            "depo_id": ortam.depo.id,
            "satirlar": [
                {"product_id": ortam.urun.id, "adet": 2},
                {"product_id": ikinci.id, "adet": 1},
            ],
        },
    )
    assert r.status_code == 409 and "Stok yetersiz" in r.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(StockMovement)) == once
    assert await _bakiye(db, ortam.urun, ortam.depo) == 5


async def test_pasif_parca_ve_depo(ortam, parca_ac, depo_ac, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 5)
    assert (await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 2)).status_code == 201
    urun = await db.get(Product, ortam.urun.id)
    urun.is_active = False
    await db.commit()
    assert (await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 1)).status_code == 409
    assert (await _iade(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 1)).status_code == 201
    pasif = await depo_ac("SRV-P", birim="GUVENLIK", aktif=False)
    yeni = await parca_ac("YP-9")
    r = await ortam.depocu.post(
        f"{URL}/giris",
        json={"depo_id": pasif.id, "satirlar": [{"product_id": yeni.id, "adet": 1}]},
    )
    assert r.status_code == 409


# --- Ters kayıt (TS-132) ------------------------------------------------------------------


async def test_ters_kayit_kurallari(ortam, servis_isi_ac, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 10)
    r = await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 3)
    cikis_id = r.json()[0]["id"]
    # Gerekçesiz 422.
    r = await ortam.depocu.post(f"{URL}/ters-kayit", json={"hareket_id": cikis_id})
    assert r.status_code == 422
    r = await ortam.depocu.post(
        f"{URL}/ters-kayit", json={"hareket_id": cikis_id, "gerekce": "Yanlış iş"}
    )
    assert r.status_code == 201, r.text
    ters_id = r.json()[0]["id"]
    assert await _bakiye(db, ortam.urun, ortam.depo) == 10
    assert await svc.net_cikis(db, ortam.so.id, ortam.urun.id) == 0
    # İkinci kez ve ters kaydın ters kaydı 409.
    r = await ortam.depocu.post(
        f"{URL}/ters-kayit", json={"hareket_id": cikis_id, "gerekce": "Tekrar"}
    )
    assert r.status_code == 409
    r = await ortam.depocu.post(f"{URL}/ters-kayit", json={"hareket_id": ters_id, "gerekce": "Xxx"})
    assert r.status_code == 409


async def test_tuketilmis_girisin_ters_kaydi_409(ortam, db) -> None:
    g = await _giris(ortam.depocu, ortam.depo, ortam.urun, 3)
    assert (await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 2)).status_code == 201
    r = await ortam.depocu.post(
        f"{URL}/ters-kayit", json={"hareket_id": g[0]["id"], "gerekce": "Yanlış giriş"}
    )
    assert r.status_code == 409 and "Stok yetersiz" in r.json()["detail"]
    assert await _bakiye(db, ortam.urun, ortam.depo) == 1


async def test_kapali_iste_iade_ters_kaydi_409(ortam, db, client) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 5)
    await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 2)
    r = await _iade(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 1)
    iade_id = r.json()[0]["id"]
    so = await db.get(ServiceOrder, ortam.so.id)
    so.status = "KAPATILDI"
    await db.commit()
    r = await ortam.depocu.post(
        f"{URL}/ters-kayit", json={"hareket_id": iade_id, "gerekce": "Yanlış iade"}
    )
    assert r.status_code == 409
    # Kapalı işte çıkışın ters kaydı (stoğa geri alma) serbest.
    cikis_id = await db.scalar(
        select(StockMovement.id).where(StockMovement.hareket_turu == "CIKIS_SERVIS")
    )
    r = await ortam.depocu.post(
        f"{URL}/ters-kayit", json={"hareket_id": cikis_id, "gerekce": "Kullanılmadı"}
    )
    # Net çıkış 1 (2 − 1 iade); 2'lik ters kayıt neti eksiye düşürür → 409.
    assert r.status_code == 409


async def test_defter_degistirilemez(ortam, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 2)
    hareket_id = await db.scalar(select(StockMovement.id))
    with pytest.raises(DBAPIError):
        await db.execute(
            text("UPDATE stock_movements SET qty = 5 WHERE id = :i"), {"i": hareket_id}
        )
    await db.rollback()
    with pytest.raises(DBAPIError):
        await db.execute(text("DELETE FROM stock_movements WHERE id = :i"), {"i": hareket_id})
    await db.rollback()
    # Mobilite satırı (hareket_turu NULL) bugünkü gibi güncellenebilir.
    mobil = Product(code="MOB-1", name="Mobil kablo", type="AKSESUAR", identity_kind="YOK")
    db.add(mobil)
    await db.flush()
    await db.execute(
        text("INSERT INTO stock_movements (product_id, qty, reason) VALUES (:p, 3, 'GIRIS')"),
        {"p": mobil.id},
    )
    await db.execute(text("UPDATE stock_movements SET notes = 'x' WHERE hareket_turu IS NULL"))
    await db.commit()


# --- Eşzamanlılık (TS-130) -------------------------------------------------------------------


async def test_eszamanli_iki_cikistan_biri_409(ortam, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 1)
    r1, r2 = await asyncio.gather(
        _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 1),
        _cikis(ortam.yonetici, ortam.so, ortam.depo, ortam.urun, 1),
    )
    assert sorted([r1.status_code, r2.status_code]) == [201, 409]
    assert await _bakiye(db, ortam.urun, ortam.depo) == 0


async def test_ters_sirali_cok_satirli_cikis_kilitlenmez(ortam, parca_ac, db) -> None:
    b = await parca_ac("YP-B")
    for u in (ortam.urun, b):
        await _giris(ortam.depocu, ortam.depo, u, 10)

    async def _coklu(ist, sira):
        return await ist.post(
            f"{URL}/cikis",
            json={
                "service_order_id": ortam.so.id,
                "depo_id": ortam.depo.id,
                "satirlar": [{"product_id": u.id, "adet": 1} for u in sira],
            },
        )

    sonuclar = await asyncio.wait_for(
        asyncio.gather(
            *[
                _coklu(
                    ortam.depocu if i % 2 else ortam.yonetici, [ortam.urun, b][:: 1 - 2 * (i % 2)]
                )
                for i in range(6)
            ]
        ),
        timeout=60,
    )
    assert all(r.status_code == 201 for r in sonuclar), [r.text for r in sonuclar]
    assert await _bakiye(db, ortam.urun, ortam.depo) == 4
    assert await _bakiye(db, b, ortam.depo) == 4


async def test_sabit_tohumlu_rastgele_dizi_net_cikis_eksiye_dusmez(
    ortam, servis_isi_ac, db
) -> None:
    """E11-03/E11-20: hypothesis yerine sabit tohum. Çıkış, iade ve ters kayıt
    rastgele sırayla; hiçbir anda net çıkış ya da bakiye eksi olmaz."""
    is_idler = [ortam.so.id, (await servis_isi_ac(birim="GUVENLIK")).id]
    uid, urun_id, depo_id = ortam.depocu_u.id, ortam.urun.id, ortam.depo.id
    clock = FakeClock()
    rnd = random.Random(20261022)

    async def _kullanici():
        # Geri almadan sonra nesneler bayatlar; kullanıcı her adımda tazelenir.
        return await db.get(User, uid, populate_existing=True)

    await svc.hareket_yaz(
        db,
        tur="GIRIS",
        satirlar=[svc.Satir(urun_id, 30)],
        user=await _kullanici(),
        clock=clock,
        warehouse_id=depo_id,
    )
    await db.commit()
    basarili = 0
    for _ in range(80):
        user = await _kullanici()
        so = await db.get(ServiceOrder, rnd.choice(is_idler), populate_existing=True)
        depo = await db.get(Warehouse, depo_id, populate_existing=True)
        islem = rnd.choice(("cikis", "iade", "ters"))
        try:
            if islem == "cikis":
                await svc.cikis_yap(
                    db,
                    so=so,
                    depo=depo,
                    satirlar=[svc.Satir(urun_id, rnd.randint(1, 4))],
                    user=user,
                    clock=clock,
                )
            elif islem == "iade":
                await svc.iade_al(
                    db,
                    so=so,
                    depo=depo,
                    satirlar=[svc.Satir(urun_id, rnd.randint(1, 4))],
                    user=user,
                    clock=clock,
                )
            else:
                adaylar = (
                    await db.scalars(
                        select(StockMovement).where(
                            StockMovement.hareket_turu.in_(("CIKIS_SERVIS", "IADE_SERVIS"))
                        )
                    )
                ).all()
                if not adaylar:
                    continue
                await svc.ters_kayit(
                    db, hareket=rnd.choice(adaylar), gerekce="Rastgele", user=user, clock=clock
                )
            await db.commit()
            basarili += 1
        except (svc.ParcaHatasi, svc.ServisGirdiHatasi):
            await db.rollback()
        for s in is_idler:
            assert await svc.net_cikis(db, s, urun_id) >= 0
        assert await svc.bakiye(db, urun_id, depo_id) >= 0
    assert basarili > 20
    # Defter tutarlı: bakiye = giriş − Σnet çıkış.
    toplam_net = sum([await svc.net_cikis(db, s, urun_id) for s in is_idler])
    assert await svc.bakiye(db, urun_id, depo_id) == 30 - toplam_net


# --- Transfer ve sayım (TS-137) -----------------------------------------------------------------


async def test_transfer_grubu_ve_ters_kaydi(ortam, depo_ac, db) -> None:
    hedef = await depo_ac("SRV-G2", birim="GUVENLIK")
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 5)
    govde = {
        "kaynak_depo_id": ortam.depo.id,
        "hedef_depo_id": hedef.id,
        "satirlar": [{"product_id": ortam.urun.id, "adet": 3}],
    }
    r = await ortam.depocu.post(f"{URL}/transfer", json=govde)
    assert r.status_code == 201, r.text
    grup = r.json()["transfer_grup"]
    toplam = await db.scalar(
        select(func.sum(StockMovement.qty)).where(StockMovement.transfer_grup == grup)
    )
    assert toplam == 0
    assert await _bakiye(db, ortam.urun, hedef) == 3
    # Aynı depo / yetersiz stok 409 ve hiçbir şey yazılmaz.
    r = await ortam.depocu.post(f"{URL}/transfer", json={**govde, "hedef_depo_id": ortam.depo.id})
    assert r.status_code == 409
    r = await ortam.depocu.post(
        f"{URL}/transfer", json={**govde, "satirlar": [{"product_id": ortam.urun.id, "adet": 9}]}
    )
    assert r.status_code == 409
    assert await _bakiye(db, ortam.urun, ortam.depo) == 2
    # Bir bacağın ters kaydı iki bacağı birlikte çevirir, aynı grup.
    bacak = r_id = await db.scalar(
        select(StockMovement.id).where(StockMovement.hareket_turu == "TRANSFER_GIRIS")
    )
    r = await ortam.depocu.post(f"{URL}/ters-kayit", json={"hareket_id": bacak, "gerekce": "Geri"})
    assert r.status_code == 201, r.text
    assert len(r.json()) == 2 and all(h["transfer_grup"] == grup for h in r.json())
    assert await _bakiye(db, ortam.urun, ortam.depo) == 5 and r_id
    assert await _bakiye(db, ortam.urun, hedef) == 0


async def test_sayim_onayi_ve_sapma(ortam, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 10)
    r = await ortam.depocu.post(f"{URL}/sayimlar", json={"depo_id": ortam.depo.id})
    assert r.status_code == 201, r.text
    sayim = r.json()
    assert sayim["count_no"].startswith("SAY-")
    assert sayim["satirlar"][0]["sistem_adet"] == 10
    # Aynı depoda ikinci açık sayım 409.
    r = await ortam.depocu.post(f"{URL}/sayimlar", json={"depo_id": ortam.depo.id})
    assert r.status_code == 409
    r = await ortam.depocu.put(
        f"{URL}/sayim/satirlar",
        json={
            "sayim_id": sayim["id"],
            "satirlar": [{"product_id": ortam.urun.id, "sayilan_adet": 8}],
        },
    )
    assert r.status_code == 200
    # Onaysız sayım bakiyeyi değiştirmez.
    assert await _bakiye(db, ortam.urun, ortam.depo) == 10
    # Sayım sırasında 1 çıkış: onay 409 + sapma listesi.
    await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 1)
    r = await ortam.depocu.post(
        f"{URL}/sayim/onayla", json={"sayim_id": sayim["id"], "gerekce": "Dönem sonu"}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["sapmalar"][0]["onay_anindaki_adet"] == 9
    assert await _bakiye(db, ortam.urun, ortam.depo) == 9
    r = await ortam.depocu.post(
        f"{URL}/sayim/onayla",
        json={"sayim_id": sayim["id"], "gerekce": "Dönem sonu", "degisimi_kabul": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "ONAYLANDI"
    assert await _bakiye(db, ortam.urun, ortam.depo) == 8
    fark = await db.scalar(
        select(StockMovement).where(StockMovement.hareket_turu == "SAYIM_EKSIGI")
    )
    assert fark.qty == -1 and fark.stock_count_id == sayim["id"]
    # Sayım farkının ters kaydı yasak.
    r = await ortam.depocu.post(f"{URL}/ters-kayit", json={"hareket_id": fark.id, "gerekce": "Xxx"})
    assert r.status_code == 409


# --- Açılış (TS-134) ------------------------------------------------------------------------


async def test_acilis_hepsi_ya_hic(ortam, parca_ac, kullanici_ac, giris, db) -> None:
    ikinci = await parca_ac("YP-A2")
    satirlar = [
        {"product_id": ortam.urun.id, "depo_id": ortam.depo.id, "adet": 5, "unit_cost": "12.5"},
        {"product_id": 987654, "depo_id": ortam.depo.id, "adet": 1},
    ]
    r = await ortam.depocu.post(f"{URL}/acilis", json={"satirlar": satirlar})
    assert r.status_code == 409
    assert r.json()["detail"]["hatalar"][0]["satir_no"] == 2
    assert await db.scalar(select(func.count()).select_from(StockMovement)) == 0
    satirlar[1]["product_id"] = ikinci.id
    r = await ortam.depocu.post(f"{URL}/acilis", json={"satirlar": satirlar})
    assert r.status_code == 201, r.text
    assert await _bakiye(db, ortam.urun, ortam.depo) == 5
    # Aynı (parça, depo) ikinci açılış reddedilir.
    r = await ortam.depocu.post(f"{URL}/acilis", json={"satirlar": satirlar[:1]})
    assert r.status_code == 409
    await kullanici_ac("tekn_x", "SERVIS_TEKNISYEN")
    tekn = await giris("tekn_x")
    assert (await tekn.post(f"{URL}/acilis", json={"satirlar": satirlar})).status_code == 403


async def test_acilis_profili(ortam, db, parca_ac) -> None:
    from app.services.imports.parca_acilis import PROFIL

    kullanici_id, urun_id, depo_id = ortam.depocu_u.id, ortam.urun.id, ortam.depo.id
    sonuc = await PROFIL.dogrula(
        db,
        [
            {"parca_kodu": "YP-1", "depo_kodu": "SRV-G", "adet": "4"},
            {"parca_kodu": "YP-1", "depo_kodu": "SRV-G", "adet": "1,5"},
        ],
    )
    assert sonuc[0].gecerli and not sonuc[1].gecerli
    staged = [r.sozluk() for r in sonuc]
    with pytest.raises(ValueError, match="satır 2"):
        await PROFIL.yaz(db, staged, clock=FakeClock(), user_id=kullanici_id, kararlar={})
    await db.rollback()
    sonuc = await PROFIL.dogrula(db, [{"parca_kodu": "YP-1", "depo_kodu": "SRV-G", "adet": "4"}])
    sayac = await PROFIL.yaz(
        db, [r.sozluk() for r in sonuc], clock=FakeClock(), user_id=kullanici_id, kararlar={}
    )
    assert sayac["eklendi"] == 1
    await db.commit()
    assert await svc.bakiye(db, urun_id, depo_id) == 4


# --- Kart, az stok, uyarı (TS-135) ------------------------------------------------------------


async def test_kart_ac_ve_stok_alanlari(ortam, db) -> None:
    r = await ortam.depocu.post(
        f"{URL}/kartlar", json={"code": "YP-K1", "name": "Kablo", "birim": "METRE"}
    )
    assert r.status_code == 201, r.text
    kart = r.json()
    urun = await db.get(Product, kart["id"])
    assert (urun.type, urun.identity_kind, urun.yedek_parca) == ("AKSESUAR", "YOK", True)
    assert urun.list_price is None
    r = await ortam.depocu.post(f"{URL}/kartlar", json={"code": "YP-K1", "name": "Kablo 2"})
    assert r.status_code == 409 and r.json()["detail"] == "Bu parça kodu zaten kayıtlı."
    r = await ortam.depocu.post(
        f"{URL}/kartlar", json={"code": "YP-K2", "name": "Kablo", "list_price": 5}
    )
    assert r.status_code == 422
    r = await ortam.depocu.patch(
        f"{URL}/kartlar", json={"product_id": kart["id"], "version": kart["version"], "min_stok": 4}
    )
    assert r.status_code == 200 and r.json()["min_stok"] == 4
    r = await ortam.depocu.patch(
        f"{URL}/kartlar", json={"product_id": kart["id"], "version": kart["version"], "min_stok": 1}
    )
    assert r.status_code == 409
    r = await ortam.depocu.patch(
        f"{URL}/kartlar",
        json={"product_id": kart["id"], "version": kart["version"] + 1, "is_active": False},
    )
    assert r.status_code == 422
    # METRE birimli parçada tam sayı adet serbest.
    m = await db.get(Product, kart["id"])
    await _giris(ortam.depocu, ortam.depo, m, 3)


async def test_az_stok_toplam_bazli_ve_uyari(
    ortam, depo_ac, parca_ac, birimli_kullanici_ac, giris, client
) -> None:
    ikinci_depo = await depo_ac("SRV-G3", birim="GUVENLIK")
    p = await parca_ac("YP-AZ", min_stok=3)
    await _giris(ortam.depocu, ortam.depo, p, 5)
    # Depo1=5, Depo2=0, asgari 3 → toplam bazlı YETERLI.
    r = await ortam.depocu.get(f"{URL}/stok", params={"durum": "AZ"})
    assert r.headers["X-Toplam-Kayit"] == "0"
    assert svc.stok_durumu(5, 3) == "YETERLI"
    await _cikis(ortam.depocu, ortam.so, ortam.depo, p, 3)
    r = await ortam.depocu.get(f"{URL}/stok", params={"durum": "AZ"})
    assert r.headers["X-Toplam-Kayit"] == "1"
    satir = r.json()[0]
    assert (
        satir["toplam"] == 2
        and satir["durum"] == "AZ"
        and ikinci_depo.id not in [d["depo_id"] for d in satir["depolar"]]
    )
    uyarilar = (await ortam.depocu.get("/api/raporlar/uyarilar")).json()
    az = [u for u in uyarilar["uyarilar"] if u["kod"] == "parca.az_stok"]
    assert az and az[0]["adet"] == 1
    # Teknisyen (parca.yonet yok) uyarıyı görmez.
    await birimli_kullanici_ac("tekn_u", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    tekn = await giris("tekn_u")
    t_uyari = (await tekn.get("/api/raporlar/uyarilar")).json()["uyarilar"]
    assert not [u for u in t_uyari if u["kod"] == "parca.az_stok"]
    # Eşik üstüne çıkınca uyarı kendiliğinden kaybolur.
    await _giris(ortam.depocu, ortam.depo, p, 5)
    uyarilar = (await ortam.depocu.get("/api/raporlar/uyarilar")).json()["uyarilar"]
    assert not [u for u in uyarilar if u["kod"] == "parca.az_stok"]
    ozet = (await ortam.depocu.get(f"{URL}/stok/ozet")).json()
    assert ozet["az_stok"] == 0 and ozet["bugun_cikis"] == 1


async def test_az_stok_sql_ve_python_ayni(db) -> None:
    """`durum_ifadesi` (liste/KPI/uyarı) ile `stok_durumu` aynı sonucu verir."""
    from sqlalchemy import literal

    for toplam in (-2, 0, 1, 2, 3, 5):
        for asgari in (None, 0, 3):
            sql = await db.scalar(
                select(svc.durum_ifadesi(literal(toplam), literal(asgari, type_=Integer)))
            )
            assert sql == svc.stok_durumu(toplam, asgari), (toplam, asgari)


# --- Talep (TS-138) ----------------------------------------------------------------------------


async def test_talep_malzeme_beklemesi_ve_karsilanma(
    ortam, birimli_kullanici_ac, giris, servis_isi_ac, db
) -> None:
    tekn_u = await birimli_kullanici_ac("tekn_t", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    so = await servis_isi_ac(birim="GUVENLIK", atananlar=[tekn_u])
    tekn = await giris("tekn_t")
    govde = {"service_order_id": so.id, "product_id": ortam.urun.id, "adet": 2, "isi_beklet": True}
    r = await tekn.post(f"{URL}/talepler", json=govde)
    assert r.status_code == 201, r.text
    talep_id = r.json()["id"]
    await db.refresh(so)
    assert so.status == "BEKLEMEDE"
    assert (await tekn.post(f"{URL}/talepler", json=govde)).status_code == 409
    # Talep depo listesinde; parça gelince talep sahibine uyarı.
    liste = await ortam.depocu.get(f"{URL}/talepler", params={"durum": "ACIK"})
    assert liste.headers["X-Toplam-Kayit"] == "1"
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 5)
    geldi = [
        u
        for u in (await tekn.get("/api/raporlar/uyarilar")).json()["uyarilar"]
        if u["kod"] == "parca.geldi"
    ]
    assert geldi and geldi[0]["adet"] == 1
    # Talepten sonraki çıkışlar karşılar; bekleme biter.
    assert (await _cikis(ortam.depocu, so, ortam.depo, ortam.urun, 1)).status_code == 201
    talep = await db.get(ServicePartRequest, talep_id)
    await db.refresh(talep)
    assert talep.durum == "ACIK"
    assert (await _cikis(ortam.depocu, so, ortam.depo, ortam.urun, 1)).status_code == 201
    await db.refresh(talep)
    await db.refresh(so)
    assert talep.durum == "KARSILANDI" and so.status == "MUSTERI_TALEBI"
    bekleme = await db.get(ServiceHold, talep.hold_id)
    assert bekleme.released_at is not None


async def test_onceki_cikis_talebi_karsilamaz_ve_is_kapaninca_iptal(
    ortam, servis_isi_ac, db
) -> None:
    so = await servis_isi_ac(birim="GUVENLIK")
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 5)
    await _cikis(ortam.depocu, so, ortam.depo, ortam.urun, 3)
    r = await ortam.depocu.post(
        f"{URL}/talepler", json={"service_order_id": so.id, "product_id": ortam.urun.id, "adet": 2}
    )
    talep = await db.get(ServicePartRequest, r.json()["id"])
    assert talep.durum == "ACIK"
    so_db = await db.get(ServiceOrder, so.id)
    await is_emirleri.durum_degistir(
        db, so_db, "IPTAL", kaynak="iptal", user=None, clock=FakeClock(), gerekce="Vazgeçildi"
    )
    await db.commit()
    await db.refresh(talep)
    assert talep.durum == "IPTAL" and "IPTAL" in talep.iptal_nedeni


# --- Maliyet (TS-130) --------------------------------------------------------------------------


async def test_maliyet_dondurulur_ve_yalniz_gorene_doner(ortam, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 2, unit_cost="10")
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 2, unit_cost="20")
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 2)  # maliyetsiz: ortalamaya girmez
    assert await svc.birim_maliyet(db, ortam.urun.id) == Decimal("15.0000")
    # Maliyet görmeyen (SERVIS_YONETICI) yanıtında anahtar YOK.
    r = await _cikis(ortam.yonetici, ortam.so, ortam.depo, ortam.urun, 1)
    assert r.status_code == 201 and "unit_cost" not in r.json()[0] and "tutar" not in r.json()[0]
    h = await db.get(StockMovement, r.json()[0]["id"])
    assert h.unit_cost == Decimal("15.0000")
    liste = (await ortam.yonetici.get(f"{URL}/hareketler")).json()
    assert all("unit_cost" not in x and "tutar" not in x for x in liste)
    parcalar = (await ortam.yonetici.get(f"{URL}/isler/{ortam.so.id}/parcalar")).json()
    assert all("unit_cost" not in x for x in parcalar["hareketler"])
    assert all("tutar" not in x for x in parcalar["ozet"])
    # Admin (maliyet.gor) görür.
    liste = (await ortam.admin.get(f"{URL}/hareketler", params={"tur": "CIKIS_SERVIS"})).json()
    assert liste[0]["unit_cost"] == 15.0 and liste[0]["tutar"] == 15.0
    parcalar = (await ortam.admin.get(f"{URL}/isler/{ortam.so.id}/parcalar")).json()
    assert parcalar["ozet"][0]["net"] == 1 and parcalar["ozet"][0]["tutar"] == 15.0


async def test_maliyetsiz_parca_null(ortam, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 2)
    r = await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 1)
    h = await db.get(StockMovement, r.json()[0]["id"])
    assert h.unit_cost is None


# --- Hareket geçmişi, Excel (TS-136) ------------------------------------------------------------


async def test_hareket_gecmisi_suzgec_excel(ortam, kullanici_ac, giris) -> None:
    await ortam.depocu.post(
        f"{URL}/giris",
        json={
            "depo_id": ortam.depo.id,
            "document_no": "IRS-2026-777",
            "notes": '=HYPERLINK("http://x")',
            "satirlar": [{"product_id": ortam.urun.id, "adet": 4}],
        },
    )
    await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 1)
    r = await ortam.depocu.get(f"{URL}/hareketler", params={"belge": "2026-77"})
    assert r.headers["X-Toplam-Kayit"] == "1" and r.json()[0]["document_no"] == "IRS-2026-777"
    r = await ortam.depocu.get(f"{URL}/hareketler", params={"so_no": ortam.so.so_no})
    assert r.headers["X-Toplam-Kayit"] == "1" and r.json()[0]["tur"] == "CIKIS_SERVIS"
    r = await ortam.depocu.get(f"{URL}/hareketler.xlsx")
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.content)).active
    notlar = [c.value for c in ws["I"]]
    assert '=HYPERLINK("http://x")' in notlar
    hucre = next(c for c in ws["I"] if c.value == '=HYPERLINK("http://x")')
    assert hucre.data_type == "s"
    basliklar = [c.value for c in ws[1]]
    assert "Birim maliyet" not in basliklar


# --- Mobilite sızıntı önlemi (TS-131, E11-D01) ----------------------------------------------------


async def test_mobilite_uclari_servis_defterini_gormez(ortam, kullanici_ac, giris, db) -> None:
    await _giris(ortam.depocu, ortam.depo, ortam.urun, 6)
    await _cikis(ortam.depocu, ortam.so, ortam.depo, ortam.urun, 2)
    mobil_depo = Warehouse(code="MOB-D", name="Mobil Depo")
    db.add(mobil_depo)
    await db.commit()
    await kullanici_ac("depo_m", "DEPO")
    mobil = await giris("depo_m")
    r = await mobil.post(
        "/api/stok/hareket",
        json={"product_id": ortam.urun.id, "qty": 1, "warehouse_id": ortam.depo.id},
    )
    assert r.status_code == 409
    r = await mobil.post(
        "/api/stok/hareket",
        json={"product_id": ortam.urun.id, "qty": 1, "warehouse_id": mobil_depo.id},
    )
    assert r.status_code == 201
    hareketler = (await mobil.get("/api/stok/hareketler")).json()
    assert len(hareketler) == 1 and hareketler[0]["qty"] == 1
    depolar = [d["code"] for d in (await mobil.get("/api/stok/depolar")).json()]
    assert "MOB-D" in depolar and "SRV-G" not in depolar
    ozet = {s["kod"]: s for s in (await mobil.get("/api/stok/ozet")).json()}
    # "Elde" tek toplam (4 servis + 1 mobil); servis deposundaki kısım ayrı.
    assert ozet["YP-1"]["elde"] == 5 and ozet["YP-1"]["servis_deposunda"] == 4
