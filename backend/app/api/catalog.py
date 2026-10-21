"""Ürün kataloğu.

`identity_kind` bu modülün en önemli alanı: cihaz kaydında IMEI'nin zorunlu
olup olmayacağını ürün belirler (bkz. models/catalog.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbDep, client_ip, require_permission
from app.models import Product, ProductBundleItem, User
from app.schemas.catalog import PaketKalemi, UrunIn, UrunOut, UrunPatch
from app.services import audit
from app.services.normalize import tr_normkey

router = APIRouter(prefix="/api/urunler", tags=["katalog"])

Okuyucu = Annotated[User, Depends(require_permission("urun.gor"))]
Yazici = Annotated[User, Depends(require_permission("urun.yaz"))]


def _cikti(urun: Product) -> UrunOut:
    out = UrunOut.model_validate(urun)
    out.paket_kalemleri = [
        PaketKalemi(
            product_id=k.product_id,
            product_code=k.product.code if k.product else None,
            product_name=k.product.name if k.product else None,
            quantity=k.quantity,
            price_share=float(k.price_share) if k.price_share is not None else None,
        )
        for k in urun.bundle_items
    ]
    return out


@router.get("/markalar")
async def markalar(db: DbDep, _: Okuyucu) -> list[dict]:
    """Katalogdaki markalar ve her markanın modelleri — filtre kutusu için."""
    satirlar = (
        await db.execute(
            select(Product.brand, Product.model, Product.id)
            .where(Product.is_deleted.is_(False), Product.is_active.is_(True))
            .order_by(Product.brand.nulls_last(), Product.model)
        )
    ).all()
    gruplar: dict[str, list[str]] = {}
    for marka, model, _pid in satirlar:
        # Markası girilmemiş ürünler kaybolmasın: kendi grubunda toplanır.
        gruplar.setdefault(marka or "", []).append(model or "")
    return [
        {"marka": m, "modeller": sorted({x for x in modeller if x})}
        for m, modeller in gruplar.items()
    ]


@router.get("", response_model=list[UrunOut])
async def listele(
    db: DbDep,
    _: Okuyucu,
    q: str | None = None,
    tip: str | None = None,
    marka: str | None = None,
    model: str | None = None,
    pasifler: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[UrunOut]:
    stmt = (
        select(Product)
        .where(Product.is_deleted.is_(False))
        .options(selectinload(Product.bundle_items).selectinload(ProductBundleItem.product))
        .order_by(Product.brand.nulls_last(), Product.model, Product.name)
        .limit(limit)
    )
    if not pasifler:
        stmt = stmt.where(Product.is_active.is_(True))
    if tip:
        stmt = stmt.where(Product.type == tip)
    if marka:
        # "(markasız)" filtresi: boş dize markası girilmemişleri seçer.
        stmt = stmt.where(Product.brand.is_(None) if marka == "-" else Product.brand == marka)
    if model:
        stmt = stmt.where(Product.model == model)
    if q:
        anahtar = tr_normkey(q)
        stmt = stmt.where(
            Product.name_key.contains(anahtar)
            | Product.code.ilike(f"%{q}%")
            | Product.brand.ilike(f"%{q}%")
            | Product.model.ilike(f"%{q}%")
        )
    urunler = (await db.scalars(stmt)).all()
    return [_cikti(u) for u in urunler]


@router.get("/{urun_id}", response_model=UrunOut)
async def getir(urun_id: int, db: DbDep, _: Okuyucu) -> UrunOut:
    urun = await db.scalar(
        select(Product)
        .where(Product.id == urun_id, Product.is_deleted.is_(False))
        .options(selectinload(Product.bundle_items).selectinload(ProductBundleItem.product))
    )
    if urun is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ürün bulunamadı")
    out = _cikti(urun)
    out.stok_adedi = await _stok_adedi(db, urun)
    return out


async def _stok_adedi(db: DbDep, urun: Product) -> int:
    """Serilide eldeki cihaz sayısı, serisizde hareket toplamı."""
    from sqlalchemy import func

    from app.models import Device, StockMovement
    from app.services.stock import ELDEKI

    if urun.identity_kind in ("IMEI", "SERI_NO"):
        return (
            await db.scalar(
                select(func.count()).where(
                    Device.product_id == urun.id,
                    Device.is_deleted.is_(False),
                    Device.status.in_(ELDEKI),
                )
            )
        ) or 0
    return (
        await db.scalar(
            select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
                StockMovement.product_id == urun.id
            )
        )
    ) or 0


@router.post("", response_model=UrunOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: UrunIn, request: Request, db: DbDep, user: Yazici) -> UrunOut:
    if await db.scalar(select(Product).where(Product.code == payload.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{payload.code}' kodlu ürün zaten var")
    urun = Product(**payload.model_dump(), created_by=user.id)
    db.add(urun)
    await db.flush()
    await audit.log(
        db,
        "products",
        "olustur",
        entity_id=urun.id,
        new_value={"code": urun.code, "name": urun.name, "identity_kind": urun.identity_kind},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(urun, ["bundle_items"])
    return _cikti(urun)


@router.patch("/{urun_id}", response_model=UrunOut)
async def guncelle(
    urun_id: int, payload: UrunPatch, request: Request, db: DbDep, user: Yazici
) -> UrunOut:
    urun = await db.get(Product, urun_id, options=[selectinload(Product.bundle_items)])
    if urun is None or urun.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ürün bulunamadı")
    if payload.version is not None and payload.version != urun.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    for alan, deger in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(urun, alan, deger)
    urun.updated_by = user.id
    await audit.log_change(db, urun, "guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    await db.refresh(urun, ["bundle_items"])
    return _cikti(urun)
