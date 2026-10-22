"""Kiralama testlerinin ortak yardımcıları (D2-C, TS-110…122).

Kurulum (depo, ürün, katalog profili, müşteri) doğrudan ORM ile yapılır;
akış (giriş, kiralama, tahsis, sevk, iade) GERÇEK uçlardan geçer ki testin
konusu uç olsun. Paylaşılan `conftest.py` donmuş olduğu için yardımcılar
fixture değil, düz fonksiyondur.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import func, select

from app.models import (
    Account,
    Product,
    RentalAsset,
    RentalCatalogItem,
    RentalInventoryMovement,
    Warehouse,
)

URL = "/api/kiralama"
NUMARA = r"^KIR-\d{6}-\d{6,}$"


async def istemci(username: str) -> httpx.AsyncClient:
    """Oturum açmış ayrı istemci (çerezler karışmasın)."""
    from app.main import app

    ist = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
    r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text
    return ist


async def depo_ac(
    db, kod: str, *, birim: str | None = None, kiralama: bool = True, servis: bool = False
) -> Warehouse:
    depo = Warehouse(
        code=kod, name=f"{kod} Deposu", birim=birim, kiralama_deposu=kiralama, servis_deposu=servis
    )
    db.add(depo)
    await db.commit()
    await db.refresh(depo)
    return depo


async def kiralik_urun_ac(
    db, kod: str, *, seri: bool, birim: str = "GUVENLIK", katalog: bool = True
) -> Product:
    urun = Product(code=kod, name=f"{kod} Kiralık", identity_kind="SERI_NO" if seri else "YOK")
    db.add(urun)
    await db.flush()
    if katalog:
        db.add(RentalCatalogItem(product_id=urun.id, birim=birim, kategori="Test"))
    await db.commit()
    await db.refresh(urun)
    return urun


async def musteri_ac(db, ad: str = "Kiralama Müşterisi A.Ş.", *, musteri: bool = True) -> Account:
    # Müşteri olmayan hesap en az bir başka rol taşır (`ck_accounts_en_az_bir_rol`).
    hesap = Account(title=ad, is_musteri=musteri, is_tedarikci=not musteri)
    db.add(hesap)
    await db.commit()
    await db.refresh(hesap)
    return hesap


async def stok_gir(
    ist: httpx.AsyncClient,
    urun: Product,
    depo: Warehouse,
    *,
    seriler: list[str] | None = None,
    adet: int | None = None,
    durum: str = "HAZIR",
) -> dict[str, Any]:
    r = await ist.post(
        f"{URL}/envanter",
        json={
            "product_id": urun.id,
            "depo_id": depo.id,
            "durum": durum,
            "seriler": seriler,
            "adet": adet,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def kiralama_ac(
    ist: httpx.AsyncClient,
    musteri: Account,
    kalemler: list[tuple[Product, int]],
    *,
    birim: str = "GUVENLIK",
    bas: str = "2026-11-01",
    bit: str = "2026-11-05",
    beklenen: int = 201,
    **ek: Any,
) -> dict[str, Any]:
    r = await ist.post(
        URL,
        json={
            "birim": birim,
            "customer_id": musteri.id,
            "baslangic": bas,
            "bitis": bit,
            "kalemler": [{"product_id": u.id, "qty": q} for u, q in kalemler],
            **ek,
        },
    )
    assert r.status_code == beklenen, r.text
    return r.json()


async def planla(ist: httpx.AsyncClient, k: dict) -> dict[str, Any]:
    r = await ist.post(f"{URL}/{k['id']}/planla")
    assert r.status_code == 200, r.text
    return r.json()


async def tahsis(ist: httpx.AsyncClient, k: dict, satirlar: list[dict], beklenen: int = 200):
    r = await ist.post(f"{URL}/{k['id']}/tahsis", json={"satirlar": satirlar})
    assert r.status_code == beklenen, r.text
    return r.json()


def kalem_id(k: dict, urun: Product) -> int:
    return next(x["id"] for x in k["kalemler"] if x["product_id"] == urun.id)


async def seri_idleri(db, urun: Product) -> list[int]:
    return list(
        (
            await db.scalars(
                select(RentalAsset.id)
                .where(RentalAsset.product_id == urun.id)
                .order_by(RentalAsset.id)
            )
        ).all()
    )


async def cihaz_durumlari(db, urun: Product) -> dict[str, int]:
    satirlar = (
        await db.execute(
            select(RentalAsset.durum, func.count())
            .where(RentalAsset.product_id == urun.id)
            .group_by(RentalAsset.durum)
        )
    ).all()
    return {d: int(a) for d, a in satirlar}


async def hareket_sayisi(db, *turler: str) -> int:
    stmt = select(func.count()).select_from(RentalInventoryMovement)
    if turler:
        stmt = stmt.where(RentalInventoryMovement.kind.in_(turler))
    return int(await db.scalar(stmt) or 0)


async def bakiye(db, urun: Product, depo: Warehouse | None, durum: str) -> int:
    from app.services.teknik_servis.kiralik_envanter import bakiye as _bakiye

    return await _bakiye(db, urun.id, depo.id if depo else None, durum)


async def hazir_kiralama(
    db,
    ist: httpx.AsyncClient,
    *,
    seri_adet: int = 0,
    toplu_adet: int = 0,
    depo: Warehouse | None = None,
    musteri: Account | None = None,
    birim: str = "GUVENLIK",
    on_ek: str = "K",
    bas: str = "2026-11-01",
    bit: str = "2026-11-05",
    sevk: bool = False,
) -> dict[str, Any]:
    """Planlanmış + tamamen tahsis edilmiş (istenirse sevk edilmiş) kiralama.

    Döner: kiralama kartı, ürünler, depo, cihaz kimlikleri.
    """
    depo = depo or await depo_ac(db, f"{on_ek}-D1", birim=birim)
    musteri = musteri or await musteri_ac(db, f"{on_ek} Müşteri")
    kalemler: list[tuple[Product, int]] = []
    seri_urun = toplu_urun = None
    cihazlar: list[int] = []
    if seri_adet:
        seri_urun = await kiralik_urun_ac(db, f"{on_ek}-SERI", seri=True, birim=birim)
        await stok_gir(ist, seri_urun, depo, seriler=[f"{on_ek}-S{i}" for i in range(seri_adet)])
        cihazlar = await seri_idleri(db, seri_urun)
        kalemler.append((seri_urun, seri_adet))
    if toplu_adet:
        toplu_urun = await kiralik_urun_ac(db, f"{on_ek}-TOPLU", seri=False, birim=birim)
        await stok_gir(ist, toplu_urun, depo, adet=toplu_adet)
        kalemler.append((toplu_urun, toplu_adet))
    k = await kiralama_ac(ist, musteri, kalemler, birim=birim, bas=bas, bit=bit)
    await planla(ist, k)
    satirlar = []
    if seri_urun is not None:
        satirlar.append({"kalem_id": kalem_id(k, seri_urun), "kiralik_idler": cihazlar})
    if toplu_urun is not None:
        satirlar.append(
            {"kalem_id": kalem_id(k, toplu_urun), "depo_id": depo.id, "adet": toplu_adet}
        )
    k = await tahsis(ist, k, satirlar)
    if sevk:
        r = await ist.post(f"{URL}/{k['id']}/sevk", json={})
        assert r.status_code == 200, r.text
        k = r.json()
    return {
        "k": k,
        "seri": seri_urun,
        "toplu": toplu_urun,
        "depo": depo,
        "musteri": musteri,
        "cihazlar": cihazlar,
    }
