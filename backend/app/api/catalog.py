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
from app.services import audit, sirketler
from app.services import sirket_kapsami as kapsam
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
async def markalar(db: DbDep, user: Okuyucu) -> list[dict]:
    """Katalogdaki markalar ve her markanın modelleri — filtre kutusu için.

    Şirket bazlı (fcl000000001): ortak ürünler + etkin şirketin ürünleri."""
    stmt = (
        select(Product.brand, Product.model, Product.id)
        .where(Product.is_deleted.is_(False), Product.is_active.is_(True))
        .order_by(Product.brand.nulls_last(), Product.model)
    )
    satirlar = (await db.execute(kapsam.uygula(stmt, kapsam.urun_kosulu(user)))).all()
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
    user: Okuyucu,
    q: str | None = None,
    tip: str | None = None,
    marka: str | None = None,
    model: str | None = None,
    pasifler: bool = False,
    yedek_parca: bool | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[UrunOut]:
    stmt = (
        select(Product)
        .where(Product.is_deleted.is_(False))
        .options(selectinload(Product.bundle_items).selectinload(ProductBundleItem.product))
        .order_by(Product.brand.nulls_last(), Product.model, Product.name)
        .limit(limit)
    )
    stmt = kapsam.uygula(stmt, kapsam.urun_kosulu(user))
    if not pasifler:
        stmt = stmt.where(Product.is_active.is_(True))
    if tip:
        stmt = stmt.where(Product.type == tip)
    if yedek_parca is not None:
        stmt = stmt.where(Product.yedek_parca.is_(yedek_parca))
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
async def getir(urun_id: int, db: DbDep, user: Okuyucu) -> UrunOut:
    urun = await db.scalar(
        select(Product)
        .where(Product.id == urun_id, Product.is_deleted.is_(False))
        .options(selectinload(Product.bundle_items).selectinload(ProductBundleItem.product))
    )
    # Başka şirketin ürünü yokmuş gibi 404 (fcl000000001).
    if urun is None or not kapsam.urun_gorunur_mu(user, urun.sirket):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ürün bulunamadı")
    out = _cikti(urun)
    out.stok_adedi = await _stok_adedi(db, urun, user)
    return out


async def _stok_adedi(db: DbDep, urun: Product, user: User) -> int:
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
            kapsam.uygula(
                select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
                    StockMovement.product_id == urun.id
                ),
                # Ortak ürünün adedi yalnız görünür (ortak/etkin şirket) depolardan.
                kapsam.depo_id_kosulu(user, StockMovement.warehouse_id),
            )
        )
    ) or 0


def _sirket_yazilabilir_mi(user: User, sirket: str | None) -> None:
    """Ürüne yazılacak şirket: null (ortak) ya da ETKİN şirket. Başka şirkete
    damgalanan ürün yazan kullanıcıdan kaybolurdu; o şirkete geçip yazılır."""
    if sirket is None or kapsam.urun_gorunur_mu(user, sirket):
        return
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "Ürün yalnız etkin şirkete ya da ortak (boş) olarak kaydedilebilir. "
        "Başka şirketin ürünü için üst çubuktaki şirket seçiciden o şirkete geçin.",
    )


@router.post("", response_model=UrunOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: UrunIn, request: Request, db: DbDep, user: Yazici) -> UrunOut:
    if await db.scalar(select(Product).where(Product.code == payload.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{payload.code}' kodlu ürün zaten var")
    veri = payload.model_dump()
    # Gönderilmezse etkin şirket; açıkça null = ortak ürün (fcl000000001).
    if "sirket" not in payload.model_fields_set:
        veri["sirket"] = sirketler.aktif_sirket(user)
    _sirket_yazilabilir_mi(user, veri["sirket"])
    urun = Product(**veri, created_by=user.id)
    db.add(urun)
    await db.flush()
    await audit.log(
        db,
        "products",
        "olustur",
        entity_id=urun.id,
        new_value={
            "code": urun.code,
            "name": urun.name,
            "identity_kind": urun.identity_kind,
            "sirket": urun.sirket,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(urun, ["bundle_items"])
    return _cikti(urun)


async def _envanterli_kimlik_korumasi(db: DbDep, urun: Product) -> None:
    """Envanterli üründe `identity_kind` değişikliği 409 (TS-118, E06-16; E11-12).

    Yalnız teknik servis defterleri sorulur: kiralık envanter (seri ya da
    toplu hareket) ve servis yedek parça defteri. Toplu bakiyesi olan ürün
    seri takipliye çevrilirse bakiye anlamsızlaşır; kiralık cihazın kimlik
    tipi değişirse seri kuralı kırılır. Mobilite ürünlerinin bugünkü
    davranışı DEĞİŞMEZ (cihaz kimlik tutarlılığı zaten bileşik FK'de).
    """
    from sqlalchemy import func

    from app.models import RentalAsset, RentalInventoryMovement, StockMovement

    kiralik = await db.scalar(
        select(func.count()).select_from(RentalAsset).where(RentalAsset.product_id == urun.id)
    )
    kiralik_hareket = await db.scalar(
        select(func.count())
        .select_from(RentalInventoryMovement)
        .where(RentalInventoryMovement.product_id == urun.id)
    )
    servis_kosulu = [StockMovement.product_id == urun.id]
    if not urun.yedek_parca:
        servis_kosulu.append(StockMovement.hareket_turu.is_not(None))
    servis = await db.scalar(select(func.count()).where(*servis_kosulu))
    if kiralik or kiralik_hareket or servis:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{urun.code} için kiralık envanter ya da servis stoğu kaydı var; seri takibi "
            "(kimlik tipi) değiştirilemez.",
        )


@router.patch("/{urun_id}", response_model=UrunOut)
async def guncelle(
    urun_id: int, payload: UrunPatch, request: Request, db: DbDep, user: Yazici
) -> UrunOut:
    urun = await db.get(Product, urun_id, options=[selectinload(Product.bundle_items)])
    if urun is None or urun.is_deleted or not kapsam.urun_gorunur_mu(user, urun.sirket):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ürün bulunamadı")
    if payload.version is not None and payload.version != urun.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    degisen = payload.model_dump(exclude_unset=True, exclude={"version"})
    if degisen.get("code") and degisen["code"] != urun.code:
        if await db.scalar(select(Product.id).where(Product.code == degisen["code"])):
            raise HTTPException(status.HTTP_409_CONFLICT, "Bu ürün kodu zaten kayıtlı.")
    if "sirket" in degisen:
        _sirket_yazilabilir_mi(user, degisen["sirket"])
    if degisen.get("identity_kind") and degisen["identity_kind"] != urun.identity_kind:
        await _envanterli_kimlik_korumasi(db, urun)
    for alan, deger in degisen.items():
        setattr(urun, alan, deger)
    urun.updated_by = user.id
    await audit.log_change(db, urun, "guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    await db.refresh(urun, ["bundle_items"])
    return _cikti(urun)
