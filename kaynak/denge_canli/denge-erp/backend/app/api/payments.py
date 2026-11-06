"""Tahsilat, hesap bakiyesi ve ödeme gecikmesi takibi."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import Account, Payment, User
from app.services import audit
from app.services import payments as svc

router = APIRouter(prefix="/api/tahsilat", tags=["tahsilat"])

Okuyucu = Annotated[User, Depends(require_permission("tahsilat.gor"))]
Yazici = Annotated[User, Depends(require_permission("tahsilat.yaz"))]

YONTEMLER = ("HAVALE", "EFT", "NAKIT", "CEK", "SENET", "KREDI_KARTI", "MAHSUP")


class TahsilatIn(BaseModel):
    account_id: int
    direction: str = "GELEN"
    amount: Decimal
    paid_at: date
    method: str | None = None
    reference: str | None = Field(default=None, max_length=80)
    subscription_id: int | None = None
    order_id: int | None = None
    settlement_id: int | None = None
    period: str | None = Field(default=None, max_length=7)
    notes: str | None = None

    def dogrula(self) -> None:
        if self.direction not in ("GELEN", "GIDEN"):
            raise ValueError("Yön GELEN veya GIDEN olmalı")
        # Sıfır engelliydi ama NEGATİF geçiyordu: `-5.000` tutarlı bir
        # "tahsilat" bakiyeyi ters yönde bozuyordu. İade GİDEN yönüyle
        # kaydedilir; tutar her zaman pozitiftir.
        if self.amount <= 0:
            raise ValueError("Tutar sıfırdan büyük olmalı (iade için yön GİDEN seçilir)")
        if self.method and self.method not in YONTEMLER:
            raise ValueError(f"Ödeme yöntemi {YONTEMLER} içinden olmalı")


class TahsilatOut(BaseModel):
    id: int
    account_id: int
    account_title: str | None = None
    direction: str
    amount: Decimal
    paid_at: date
    method: str | None
    reference: str | None
    subscription_id: int | None
    order_id: int | None
    settlement_id: int | None
    period: str | None
    notes: str | None

    model_config = {"from_attributes": True}


async def _cikti(db: DbDep, p: Payment) -> TahsilatOut:
    out = TahsilatOut.model_validate(p)
    h = await db.get(Account, p.account_id)
    out.account_title = h.title if h else None
    return out


@router.get("", response_model=list[TahsilatOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    hesap_id: int | None = None,
    yon: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[TahsilatOut]:
    stmt = select(Payment).order_by(Payment.paid_at.desc(), Payment.id.desc()).limit(limit)
    if hesap_id:
        stmt = stmt.where(Payment.account_id == hesap_id)
    if yon:
        stmt = stmt.where(Payment.direction == yon)
    return [await _cikti(db, p) for p in (await db.scalars(stmt)).all()]


@router.get("/gecikenler")
async def gecikenler(
    db: DbDep, clock: ClockDep, user: Okuyucu, gun: int | None = None
) -> list[dict]:
    """Borcu olup uzun süredir ödeme yapmayan müşteriler.

    Abonelik askıya alma ÖNERİLİR — karar ekibin.
    """
    return await svc.gecikenler(db, clock, gun=gun)


@router.get("/bakiye/{hesap_id}")
async def bakiye(hesap_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> dict:
    """Hesabın ERP tarafındaki tahakkuk/tahsilat özeti.

    Resmî cari hesap Logo'da; buradaki rakam tahsilat takibi içindir.
    """
    try:
        return await svc.bakiye(db, hesap_id, clock)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("", response_model=TahsilatOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: TahsilatIn, request: Request, db: DbDep, user: Yazici) -> TahsilatOut:
    try:
        payload.dogrula()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if await db.get(Account, payload.account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hesap bulunamadı")

    kayit = Payment(**payload.model_dump(), created_by=user.id)
    db.add(kayit)
    await db.flush()
    await audit.log(
        db,
        "payments",
        "olustur",
        entity_id=kayit.id,
        new_value={
            "hesap": kayit.account_id,
            "yon": kayit.direction,
            "tutar": float(kayit.amount),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, kayit)


@router.delete("/{tahsilat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def sil(tahsilat_id: int, request: Request, db: DbDep, user: Yazici) -> None:
    """Yanlış girilen tahsilatı siler.

    Tahsilat kaydı muhasebe belgesi değil, takip kaydıdır; silinmesi denetim
    izine yazılır ve dekont numarası orada kalır.
    """
    kayit = await db.get(Payment, tahsilat_id)
    if kayit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tahsilat kaydı bulunamadı")
    await audit.log(
        db,
        "payments",
        "sil",
        entity_id=kayit.id,
        old_value={
            "hesap": kayit.account_id,
            "tutar": float(kayit.amount),
            "tarih": str(kayit.paid_at),
            "dekont": kayit.reference,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.delete(kayit)
    await db.commit()
