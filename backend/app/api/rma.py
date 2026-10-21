"""RMA / garanti / teknik servis."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import Account, Device, RmaCase, User, Vehicle
from app.models.service import COZUM_TIPLERI
from app.services import audit
from app.services import rma as svc
from app.services.statemachine import RMA, IzinsizGecis

router = APIRouter(prefix="/api/rma", tags=["rma"])

Okuyucu = Annotated[User, Depends(require_permission("rma.gor"))]
Yazici = Annotated[User, Depends(require_permission("rma.yaz"))]


class RmaIn(BaseModel):
    # Cihaz IMEI/seri no ile de bulunabilsin: servis masasında elde IMEI olur.
    device_id: int | None = None
    kimlik: str | None = None
    fault_description: str = Field(min_length=3)
    received_at: date | None = None
    customer_id: int | None = None
    vehicle_id: int | None = None
    notes: str | None = None


class CozumIn(BaseModel):
    resolution: str
    resolution_note: str | None = None
    cost: Decimal | None = None
    replacement_device_id: int | None = None
    replacement_kimlik: str | None = None


class DurumIn(BaseModel):
    durum: str


class TedarikciIn(BaseModel):
    supplier_id: int | None = None
    supplier_rma_no: str | None = Field(default=None, max_length=60)
    sent_to_supplier_at: date | None = None
    returned_from_supplier_at: date | None = None
    version: int


class RmaOut(BaseModel):
    id: int
    rma_no: str
    device_id: int
    device_kimlik: str | None = None
    customer_id: int | None
    customer_title: str | None = None
    vehicle_id: int | None
    vehicle_plate: str | None = None
    status: str
    received_at: date
    fault_description: str
    warranty_status: str
    warranty_end_date: date | None
    resolution: str | None
    resolution_note: str | None
    replacement_device_id: int | None
    replacement_kimlik: str | None = None
    cost: Decimal | None
    supplier_id: int | None
    supplier_rma_no: str | None
    sent_to_supplier_at: date | None
    returned_from_supplier_at: date | None
    closed_at: datetime | None
    notes: str | None
    version: int
    sonraki_durumlar: list[str] = []

    model_config = {"from_attributes": True}


async def _kimlik(db: DbDep, device_id: int | None) -> str | None:
    if device_id is None:
        return None
    c = await db.get(Device, device_id)
    return (c.imei or c.serial_no) if c else None


async def _cikti(db: DbDep, k: RmaCase) -> RmaOut:
    out = RmaOut.model_validate(k)
    out.device_kimlik = await _kimlik(db, k.device_id)
    out.replacement_kimlik = await _kimlik(db, k.replacement_device_id)
    if k.customer_id:
        h = await db.get(Account, k.customer_id)
        out.customer_title = h.title if h else None
    if k.vehicle_id:
        a = await db.get(Vehicle, k.vehicle_id)
        out.vehicle_plate = a.plate if a else None
    out.sonraki_durumlar = sorted(RMA.sonraki(k.status))
    return out


async def _cihaz_bul(db: DbDep, device_id: int | None, kimlik: str | None) -> Device:
    if device_id:
        cihaz = await db.get(Device, device_id)
    elif kimlik:
        cihaz = await db.scalar(
            select(Device).where((Device.imei == kimlik) | (Device.serial_no == kimlik))
        )
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cihaz seçilmedi (IMEI ya da seri no)")
    if cihaz is None or cihaz.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cihaz bulunamadı")
    return cihaz


@router.get("", response_model=list[RmaOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    durum: str | None = None,
    cihaz_id: int | None = None,
    musteri_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RmaOut]:
    stmt = (
        select(RmaCase)
        .where(RmaCase.is_deleted.is_(False))
        .order_by(RmaCase.id.desc())
        .limit(limit)
    )
    if durum:
        stmt = stmt.where(RmaCase.status == durum)
    if cihaz_id:
        stmt = stmt.where(RmaCase.device_id == cihaz_id)
    if musteri_id:
        stmt = stmt.where(RmaCase.customer_id == musteri_id)
    return [await _cikti(db, k) for k in (await db.scalars(stmt)).all()]


@router.get("/ariza-orani")
async def ariza_orani(
    db: DbDep, clock: ClockDep, user: Okuyucu, gun: int = Query(default=365, ge=1, le=3650)
) -> list[dict]:
    """Model bazında arıza oranı — payda o modeldeki toplam cihaz."""
    return await svc.ariza_orani(db, gun=gun, clock=clock)


@router.get("/{rma_id}", response_model=RmaOut)
async def getir(rma_id: int, db: DbDep, user: Okuyucu) -> RmaOut:
    k = await db.get(RmaCase, rma_id)
    if k is None or k.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis kaydı bulunamadı")
    return await _cikti(db, k)


@router.post("", response_model=RmaOut, status_code=status.HTTP_201_CREATED)
async def ac(payload: RmaIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici) -> RmaOut:
    """Servis kaydı açar; garanti durumu OTOMATİK hesaplanıp dondurulur."""
    cihaz = await _cihaz_bul(db, payload.device_id, payload.kimlik)
    try:
        kayit = await svc.ac(
            db,
            cihaz=cihaz,
            ariza=payload.fault_description,
            gelis=payload.received_at or clock.now().date(),
            clock=clock,
            customer_id=payload.customer_id,
            vehicle_id=payload.vehicle_id,
            user_id=user.id,
        )
    except svc.RmaHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    kayit.notes = payload.notes

    await audit.log(
        db,
        "rma_cases",
        "ac",
        entity_id=kayit.id,
        new_value={
            "no": kayit.rma_no,
            "cihaz": cihaz.imei or cihaz.serial_no,
            "garanti": kayit.warranty_status,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, kayit)


@router.post("/{rma_id}/durum", response_model=RmaOut)
async def durum_degistir(
    rma_id: int,
    payload: DurumIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> RmaOut:
    k = await db.get(RmaCase, rma_id)
    if k is None or k.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis kaydı bulunamadı")
    onceki = k.status
    try:
        RMA.dogrula(onceki, payload.durum)
        if payload.durum == "KAPANDI":
            await svc.kapat(db, k, clock=clock, user_id=user.id)
        else:
            await svc.durum_ilerlet(db, k, payload.durum, clock=clock, user_id=user.id)
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except svc.RmaHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "rma_cases",
        "durum.degistir",
        entity_id=k.id,
        old_value={"status": onceki},
        new_value={"status": k.status},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, k)


@router.post("/{rma_id}/coz", response_model=RmaOut)
async def coz(
    rma_id: int,
    payload: CozumIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> RmaOut:
    """Çözümü işler. DEĞİŞİMDE araç/hat/müşteri bağı yeni cihaza taşınır."""
    k = await db.get(RmaCase, rma_id)
    if k is None or k.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis kaydı bulunamadı")
    if payload.resolution not in COZUM_TIPLERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Çözüm {COZUM_TIPLERI} içinden olmalı")

    yeni_id = payload.replacement_device_id
    if yeni_id is None and payload.replacement_kimlik:
        yeni_id = (await _cihaz_bul(db, None, payload.replacement_kimlik)).id

    try:
        await svc.coz(
            db,
            k,
            cozum=payload.resolution,
            clock=clock,
            not_=payload.resolution_note,
            maliyet=payload.cost,
            yeni_cihaz_id=yeni_id,
            user_id=user.id,
        )
    except svc.RmaHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "rma_cases",
        "coz",
        entity_id=k.id,
        new_value={
            "cozum": k.resolution,
            "yeni_cihaz": await _kimlik(db, k.replacement_device_id),
            "maliyet": float(k.cost) if k.cost else None,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, k)


@router.patch("/{rma_id}/tedarikci", response_model=RmaOut)
async def tedarikci_bilgisi(
    rma_id: int,
    payload: TedarikciIn,
    request: Request,
    db: DbDep,
    user: Yazici,
) -> RmaOut:
    """Üreticiye garanti iadesi takibi (brief §4.12)."""
    k = await db.get(RmaCase, rma_id)
    if k is None or k.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis kaydı bulunamadı")
    # İSTEMCİNİN version DEĞERİ KAYDA ATANMAZ. Atandığında SQLAlchemy'nin
    # `WHERE version = :eski` koşulu her zaman tutuyor, iyimser kilitleme
    # tamamen devre dışı kalıyordu: bayat bir sürümle gelen istek 200 dönüp
    # aradaki değişikliği sessizce eziyor, sayaç geriye gidiyordu (ölçüldü:
    # 4 -> 1). Doğru davranış, uyuşmazlıkta 409 (plan §3.3/1).
    if payload.version != k.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. "
            "Sayfayı yenileyip değişikliğinizi tekrar uygulayın.",
        )
    for alan, deger in payload.model_dump(exclude={"version"}, exclude_unset=True).items():
        setattr(k, alan, deger)
    k.updated_by = user.id
    await audit.log_change(db, k, "tedarikci", user_id=user.id, ip=client_ip(request))
    await db.commit()
    return await _cikti(db, k)
