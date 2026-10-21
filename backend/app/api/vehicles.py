"""Araçlar."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import DbDep, client_ip, require_permission, sayfala
from app.models import Account, User, Vehicle
from app.models.vehicle import ARAC_TIPLERI
from app.services import accounts as hesap_svc
from app.services import audit, normalize

router = APIRouter(prefix="/api/araclar", tags=["araclar"])

Okuyucu = Annotated[User, Depends(require_permission("arac.gor"))]
Yazici = Annotated[User, Depends(require_permission("arac.yaz"))]


class AracIn(BaseModel):
    plate: str
    chassis_no: str | None = Field(default=None, max_length=24)
    registration_no: str | None = Field(default=None, max_length=24)
    brand: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    model_year: int | None = Field(default=None, ge=1950, le=2100)
    vehicle_type: str | None = None
    customer_id: int | None = None
    is_school_service: bool = False
    notes: str | None = None

    @field_validator("plate")
    @classmethod
    def _plaka(cls, v: str) -> str:
        return normalize.normalize_plate(v)

    @field_validator("vehicle_type")
    @classmethod
    def _tip(cls, v: str | None) -> str | None:
        if v and v not in ARAC_TIPLERI:
            raise ValueError(f"Araç tipi {ARAC_TIPLERI} içinden olmalı")
        return v


class AracPatch(AracIn):
    plate: str | None = None
    version: int | None = None


class AracOut(BaseModel):
    id: int
    plate: str
    is_plate_verified: bool
    chassis_no: str | None
    registration_no: str | None
    brand: str | None
    model: str | None
    model_year: int | None
    vehicle_type: str | None
    customer_id: int | None
    customer_title: str | None = None
    is_school_service: bool
    notes: str | None
    version: int

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AracOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    q: str | None = Query(default=None, description="Plaka, şase veya ruhsat no"),
    musteri_id: int | None = None,
    okul_servisi: bool = False,
    dogrulanmamis: bool = Query(
        default=False, description="Yalnız standart plaka biçimi tutmayan araçlar"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[AracOut]:
    stmt = (
        select(Vehicle, Account.title)
        .join(Account, Account.id == Vehicle.customer_id, isouter=True)
        .where(Vehicle.is_deleted.is_(False))
        .order_by(Vehicle.plate)
    )
    stmt = hesap_svc.kapsam_musteri(stmt, user, Vehicle.customer_id)
    if q:
        anahtar = normalize.tr_normkey(q).replace(" ", "")
        stmt = stmt.where(
            or_(
                Vehicle.plate_key.contains(anahtar),
                Vehicle.chassis_no.ilike(f"%{q}%"),
                Vehicle.registration_no.ilike(f"%{q}%"),
            )
        )
    if musteri_id:
        stmt = stmt.where(Vehicle.customer_id == musteri_id)
    if okul_servisi:
        stmt = stmt.where(Vehicle.is_school_service.is_(True))
    if dogrulanmamis:
        stmt = stmt.where(Vehicle.is_plate_verified.is_(False))

    sonuc = []
    for arac, unvan in await sayfala(db, response, stmt, limit=limit, offset=offset):
        out = AracOut.model_validate(arac)
        out.customer_title = unvan
        sonuc.append(out)
    return sonuc


@router.post("", response_model=AracOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: AracIn, request: Request, db: DbDep, user: Yazici) -> AracOut:
    if await db.scalar(select(Vehicle).where(Vehicle.plate == payload.plate)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{payload.plate} plakası zaten kayıtlı")
    arac = Vehicle(**payload.model_dump(), created_by=user.id)
    db.add(arac)
    await db.flush()
    await audit.log(
        db,
        "vehicles",
        "olustur",
        entity_id=arac.id,
        new_value={"plate": arac.plate},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,  # plaka kişisel veri (brief §8 KVKK)
    )
    await db.commit()
    return AracOut.model_validate(arac)


@router.patch("/{arac_id}", response_model=AracOut)
async def guncelle(
    arac_id: int, payload: AracPatch, request: Request, db: DbDep, user: Yazici
) -> AracOut:
    arac = await db.get(Vehicle, arac_id)
    if arac is None or arac.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Araç bulunamadı")
    if await hesap_svc.kapsam_disinda_mi(db, user, arac.customer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Araç bulunamadı")
    if payload.version is not None and payload.version != arac.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    for alan, deger in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(arac, alan, deger)
    arac.updated_by = user.id
    await audit.log_change(
        db, arac, "guncelle", user_id=user.id, ip=client_ip(request), is_personal_data=True
    )
    await db.commit()
    return AracOut.model_validate(arac)
