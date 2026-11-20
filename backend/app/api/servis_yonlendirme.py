"""Yönlendirmeler (KARARLAR 2026-11-20 §5–6).

- `GET  /api/teknik-servis/yonlendirmeler` — müdür hepsini, şef kendisine
  yönlendirilenleri görür (`acik=false` planlananları da getirir).
- `GET  /api/teknik-servis/yonlendirmeler/adaylar?birim=` — birimin
  yöneticisi/şefi olabilecek kişiler (`servis.yonlendir`).
- `POST /api/teknik-servis/yonlendirmeler/{id}/yonlendir` — müdür birime
  yönlendirir (`servis.yonlendir`, iyimser kilit).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import User
from app.services.teknik_servis import yonlendirme as svc
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teknik-servis/yonlendirmeler", tags=["teknik-servis"])

Okuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
Yonlendirici = Annotated[User, Depends(require_permission(svc.YONLENDIRME_IZNI))]


def _hata(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.YonlendirmeBulunamadi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, ServisGirdiHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("")
async def liste(db: DbDep, user: Okuyucu, acik: bool = Query(default=True)) -> list[dict[str, Any]]:
    return await svc.liste(db, user, svc.Suzgec(acik=acik))


@router.get("/adaylar")
async def adaylar(db: DbDep, user: Yonlendirici, birim: str = Query(max_length=20)) -> list[dict]:
    return await svc.adaylar(db, birim)


class YonlendirIn(BaseModel):
    hedef_user_id: int
    version: int
    not_: str | None = Field(default=None, max_length=500, alias="not")

    model_config = {"populate_by_name": True}


@router.post("/{kayit_id}/yonlendir")
async def yonlendir(
    kayit_id: int,
    payload: YonlendirIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yonlendirici,
) -> dict[str, Any]:
    try:
        kayit = await svc.kapsamli(db, user, kayit_id)
        await svc.yonlendir(
            db,
            kayit,
            payload.hedef_user_id,
            not_=payload.not_,
            version=payload.version,
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except (ServisHatasi, ServisGirdiHatasi) as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"id": kayit.id, "durum": kayit.durum, "version": kayit.version}
