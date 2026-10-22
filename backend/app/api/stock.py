"""Stok: transferler, konum/sahiplik geçmişi, bayi stoğu."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import (
    Account,
    Device,
    DeviceCustodyHistory,
    Transfer,
    TransferItem,
    User,
    Warehouse,
)
from app.models.stock import KONUM_TIPLERI, SAHIPLIK_DURUMLARI, TRANSFER_TIPLERI
from app.services import audit
from app.services import devices as cihaz_svc
from app.services import stock as svc
from app.services.statemachine import IzinsizGecis

router = APIRouter(prefix="/api/stok", tags=["stok"])

Okuyucu = Annotated[User, Depends(require_permission("cihaz.gor"))]
Transferci = Annotated[User, Depends(require_permission("cihaz.transfer"))]
Yazici = Annotated[User, Depends(require_permission("cihaz.yaz"))]


class TransferIn(BaseModel):
    type: str
    from_location_type: str
    from_warehouse_id: int | None = None
    from_account_id: int | None = None
    to_location_type: str
    to_warehouse_id: int | None = None
    to_account_id: int | None = None
    new_ownership: str | None = None
    document_no: str | None = Field(default=None, max_length=40)
    notes: str | None = None
    # IMEI/seri no listesi — barkod okutarak veya Excel'den yapıştırarak.
    kimlikler: list[str] = Field(min_length=1)

    def dogrula(self) -> None:
        if self.type not in TRANSFER_TIPLERI:
            raise ValueError(f"Transfer tipi {TRANSFER_TIPLERI} içinden olmalı")
        for alan, deger in (
            ("from_location_type", self.from_location_type),
            ("to_location_type", self.to_location_type),
        ):
            if deger not in KONUM_TIPLERI:
                raise ValueError(f"{alan} {KONUM_TIPLERI} içinden olmalı")
        if self.new_ownership and self.new_ownership not in SAHIPLIK_DURUMLARI:
            raise ValueError(f"Sahiplik {SAHIPLIK_DURUMLARI} içinden olmalı")


class TransferKalemOut(BaseModel):
    device_id: int
    kimlik: str | None = None


class TransferOut(BaseModel):
    id: int
    transfer_no: str
    type: str
    status: str
    from_location_type: str
    to_location_type: str
    to_account_title: str | None = None
    new_ownership: str | None
    document_no: str | None
    shipped_at: date | None
    delivered_at: date | None
    notes: str | None
    kalemler: list[TransferKalemOut] = []
    version: int

    model_config = {"from_attributes": True}


class KonumOut(BaseModel):
    id: int
    device_id: int
    location_type: str
    account_id: int | None
    account_title: str | None = None
    warehouse_id: int | None
    ownership: str
    valid_from: datetime
    valid_to: datetime | None
    notes: str | None

    model_config = {"from_attributes": True}


async def _transfer_cikti(db: DbDep, t: Transfer) -> TransferOut:
    out = TransferOut.model_validate(t)
    if t.to_account_id:
        h = await db.get(Account, t.to_account_id)
        out.to_account_title = h.title if h else None
    for k in t.items:
        c = await db.get(Device, k.device_id)
        out.kalemler.append(TransferKalemOut(device_id=k.device_id, kimlik=c.kimlik if c else None))
    return out


@router.get("/transferler", response_model=list[TransferOut])
async def transferleri_listele(
    db: DbDep, _: Okuyucu, durum: str | None = None, limit: int = Query(default=50, ge=1, le=200)
) -> list[TransferOut]:
    stmt = (
        select(Transfer)
        .options(selectinload(Transfer.items))
        .order_by(Transfer.id.desc())
        .limit(limit)
    )
    if durum:
        stmt = stmt.where(Transfer.status == durum)
    return [await _transfer_cikti(db, t) for t in (await db.scalars(stmt)).all()]


@router.post("/transferler", response_model=TransferOut, status_code=status.HTTP_201_CREATED)
async def transfer_olustur(
    payload: TransferIn, request: Request, db: DbDep, clock: ClockDep, user: Transferci
) -> TransferOut:
    """IMEI/seri no listesiyle transfer açar.

    Tanınmayan kimlik varsa transfer HİÇ oluşturulmaz — yarım bir sevk
    belgesi, sahada eksik cihazla karşılaşmak demektir.
    """
    try:
        payload.dogrula()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    for depo_id in (payload.from_warehouse_id, payload.to_warehouse_id):
        depo = await db.get(Warehouse, depo_id) if depo_id is not None else None
        if depo is not None and (depo.servis_deposu or depo.kiralama_deposu):
            # Cihaz transferi mobilite akışıdır; servis/kiralama depoları ayrı
            # defter tutar (E06-D01, E11-D01).
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Servis ve kiralama depoları mobilite transferinde kullanılamaz.",
            )

    kimlikler = [k.strip() for k in payload.kimlikler if k.strip()]
    cihazlar = (
        await db.scalars(
            select(Device).where(
                (Device.imei.in_(kimlikler)) | (Device.serial_no.in_(kimlikler)),
                Device.is_deleted.is_(False),
            )
        )
    ).all()
    bulunan = {c.imei for c in cihazlar if c.imei} | {c.serial_no for c in cihazlar if c.serial_no}
    eksik = [k for k in kimlikler if k not in bulunan]
    if eksik:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{len(eksik)} kimlik sistemde bulunamadı: {', '.join(eksik[:5])}"
            + (" …" if len(eksik) > 5 else ""),
        )

    sira = (await db.scalar(select(Transfer.id).order_by(Transfer.id.desc()).limit(1)) or 0) + 1
    transfer = Transfer(
        transfer_no=f"TR{clock.now():%Y%m}-{sira:05d}",
        status="YOLDA",
        shipped_at=clock.now().date(),
        delivered_by=user.full_name,
        created_by=user.id,
        **payload.model_dump(exclude={"kimlikler"}),
    )
    db.add(transfer)
    await db.flush()
    # Sevk edilen cihaz DEPODA DEĞİLDİR. Durum değişmediği için cihaz hem
    # bayiye yolda görünüyor hem başka bir müşteri siparişine rezerve
    # edilebiliyordu (ÇİFT TAHSİS) ve merkez stok özeti onu hâlâ "elde"
    # sayıyordu. Geçiş tek yoldan yapılır: kural kontrolü + geçmiş + denetim.
    atlanan: list[str] = []
    for c in cihazlar:
        db.add(TransferItem(transfer_id=transfer.id, device_id=c.id))
        if c.status == "SEVK_EDILDI":
            continue
        try:
            await cihaz_svc.durum_degistir(
                db,
                c,
                "SEVK_EDILDI",
                clock=clock,
                user_id=user.id,
                neden=f"Transfer {transfer.transfer_no}",
                ip=client_ip(request),
            )
        except IzinsizGecis:
            # Ör. ARIZALI ya da HURDA cihaz. Sevk belgesi yine de oluşur ama
            # sessiz kalmaz: hangi cihazın durumunun değişmediği bildirilir.
            atlanan.append(c.kimlik or str(c.id))
    await db.flush()

    await audit.log(
        db,
        "transfers",
        "olustur",
        entity_id=transfer.id,
        new_value={
            "no": transfer.transfer_no,
            "adet": len(cihazlar),
            "tip": transfer.type,
            **({"durumu_degismeyen": atlanan} if atlanan else {}),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(transfer, ["items"])
    return await _transfer_cikti(db, transfer)


class TeslimIn(BaseModel):
    received_by: str | None = None


@router.post("/transferler/{transfer_id}/teslim", response_model=TransferOut)
async def transfer_teslim(
    transfer_id: int,
    payload: TeslimIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Transferci,
) -> TransferOut:
    """Teslimi kaydeder ve tüm cihazların konumunu TEK işlemde günceller."""
    t = await db.get(Transfer, transfer_id, options=[selectinload(Transfer.items)])
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer bulunamadı")
    try:
        adet = await svc.transferi_teslim_et(db, t, clock=clock, teslim_alan=payload.received_by)
    except svc.TransferHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "transfers",
        "teslim",
        entity_id=t.id,
        new_value={"no": t.transfer_no, "cihaz": adet},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(t, ["items"])
    return await _transfer_cikti(db, t)


@router.get("/cihaz/{device_id}/konum-gecmisi", response_model=list[KonumOut])
async def konum_gecmisi(device_id: int, db: DbDep, _: Okuyucu) -> list[KonumOut]:
    kayitlar = (
        await db.scalars(
            select(DeviceCustodyHistory)
            .where(DeviceCustodyHistory.device_id == device_id)
            .order_by(DeviceCustodyHistory.valid_from.desc())
        )
    ).all()
    sonuc = []
    for k in kayitlar:
        out = KonumOut.model_validate(k)
        if k.account_id:
            h = await db.get(Account, k.account_id)
            out.account_title = h.title if h else None
        sonuc.append(out)
    return sonuc


@router.get("/cihaz/{device_id}/tarihinde", response_model=KonumOut | None)
async def konum_tarihinde(device_id: int, an: datetime, db: DbDep, _: Okuyucu) -> KonumOut | None:
    """'Bu cihaz o gün neredeydi' — brief §4.3."""
    kayit = await svc.konum_tarihinde(db, device_id, an)
    if kayit is None:
        return None
    out = KonumOut.model_validate(kayit)
    if kayit.account_id:
        h = await db.get(Account, kayit.account_id)
        out.account_title = h.title if h else None
    return out


class StokHareketIn(BaseModel):
    product_id: int
    qty: int = Field(description="Eksi değer çıkıştır")
    reason: str = "GIRIS"
    warehouse_id: int | None = None
    document_no: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=300)


@router.get("/ozet")
async def ozet(db: DbDep, _: Okuyucu, tip: str | None = None) -> list[dict]:
    """Denge stoğu, model bazında: hangi üründen kaç adet var, nerede duruyor."""
    return await svc.denge_stogu(db, urun_tipi=tip)


@router.post("/hareket", status_code=status.HTTP_201_CREATED)
async def stok_hareketi(payload: StokHareketIn, request: Request, db: DbDep, user: Yazici) -> dict:
    """Serisiz ürüne (aksesuar, kablo) giriş/çıkış/sayım hareketi."""
    try:
        hareket = await svc.stok_hareketi(db, **payload.model_dump(), user_id=user.id)
    except svc.TransferHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await audit.log(
        db,
        "stock_movements",
        "olustur",
        entity_id=hareket.id,
        new_value=payload.model_dump(),
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {"id": hareket.id, "product_id": hareket.product_id, "qty": hareket.qty}


@router.get("/hareketler")
async def stok_hareketleri(
    db: DbDep, _: Okuyucu, product_id: int | None = None, limit: int = 200
) -> list[dict]:
    from app.models import Product, StockMovement

    # Servis defteri satırları (`hareket_turu` dolu) burada LİSTELENMEZ: bu uç
    # `cihaz.gor` ile ve kapsamsız açık; servis işine bağlı parça hareketi,
    # notu ve belge no birim/müşteri kapsamı olmadan sızardı (E11-D01).
    # Servis hareketleri yalnız `/api/teknik-servis/parca/hareketler`'den.
    stmt = (
        select(StockMovement, Product.code, Product.name)
        .join(Product, Product.id == StockMovement.product_id)
        .where(StockMovement.hareket_turu.is_(None))
        .order_by(StockMovement.id.desc())
        .limit(min(limit, 500))
    )
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    return [
        {
            "id": h.id,
            "product_id": h.product_id,
            "urun_kodu": kod,
            "urun_adi": ad,
            "qty": h.qty,
            "reason": h.reason,
            "document_no": h.document_no,
            "notes": h.notes,
            "created_at": h.created_at,
        }
        for h, kod, ad in (await db.execute(stmt)).all()
    ]


@router.get("/bayi-stogu")
async def bayi_stogu(db: DbDep, _: Okuyucu, account_id: int | None = None) -> list[dict]:
    return await svc.bayi_stogu(db, account_id=account_id)


@router.get("/yaslanan")
async def yaslanan(db: DbDep, clock: ClockDep, _: Okuyucu) -> list[dict]:
    """Eşik günden uzun süredir bayide bekleyen cihazlar."""
    satirlar = await svc.yaslanan_stok(db, clock)
    for s in satirlar:
        h = await db.get(Account, s["account_id"]) if s["account_id"] else None
        s["account_title"] = h.title if h else None
    return satirlar


@router.get("/depolar")
async def depolar(db: DbDep, _: Okuyucu) -> list[dict]:
    # Yalnız mobilite depoları: servis ve kiralama depoları kendi ekranlarında
    # (E11-D01, E06-D01); burada listelenseydi mobilite hareketi oraya girilirdi.
    kayitlar = (
        await db.scalars(
            select(Warehouse)
            .where(
                Warehouse.is_active.is_(True),
                Warehouse.servis_deposu.is_(False),
                Warehouse.kiralama_deposu.is_(False),
            )
            .order_by(Warehouse.name)
        )
    ).all()
    return [
        {"id": w.id, "code": w.code, "name": w.name, "location_type": w.location_type}
        for w in kayitlar
    ]
