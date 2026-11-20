"""İzin talepleri (KARARLAR 2026-11-20 §7).

Oturumlu uçlar `/api/izin`; e-postadaki düğmenin açtığı karar sayfası için
oturumsuz uçlar `/api/public/izin/{token}` (tek kullanımlık anahtar).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field

from app.api.deps import ClockDep, CurrentUser, DbDep, client_ip, require_permission
from app.models import IzinOnayi, IzinTalebi, User
from app.services import izin as svc

router = APIRouter(prefix="/api/izin", tags=["izin"])
public_router = APIRouter(prefix="/api/public/izin", tags=["izin (public)"])

Yonetici = Annotated[User, Depends(require_permission(svc.YONETIM_IZNI))]


def _hata(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.IzinGirdiHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, svc.IzinYetkiHatasi):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, svc.IzinBulunamadi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


_HATALAR = (svc.IzinGirdiHatasi, svc.IzinYetkiHatasi, svc.IzinBulunamadi, svc.IzinHatasi)


class TalepIn(BaseModel):
    tur: Literal["YILLIK", "MAZERET", "UCRETSIZ", "RAPOR", "DIGER"]
    baslangic: date
    bitis: date
    vekil_id: int | None = None
    izin_ili: str | None = Field(default=None, max_length=60)
    iletisim_tel: str | None = Field(default=None, max_length=30)
    aciklama: str | None = Field(default=None, max_length=2000)
    personel_id: int | None = None


class KararIn(BaseModel):
    karar: Literal["ONAY", "RED"]
    aciklama: str | None = Field(default=None, max_length=500)


async def _gorebilir(db, t: IzinTalebi, user: User) -> bool:
    return (
        t.personel_id == user.id
        or user.has(svc.YONETIM_IZNI)
        or any(o.onaylayici_id == user.id for o in t.onaylar)
    )


async def _talep(db, talep_id: int, user: User) -> IzinTalebi:
    t = await db.get(IzinTalebi, talep_id)
    if t is None or not await _gorebilir(db, t, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "İzin talebi bulunamadı")
    return t


@router.get("/benim")
async def benim(db: DbDep, user: CurrentUser) -> list[dict[str, Any]]:
    return [await svc.cikti(db, t) for t in await svc.benim(db, user)]


@router.get("/onayimda")
async def onayimda(
    db: DbDep, user: CurrentUser, hepsi: bool = Query(default=False)
) -> list[dict[str, Any]]:
    return [await svc.cikti(db, t) for t in await svc.onayimda(db, user, hepsi=hepsi)]


@router.get("/tum")
async def tumu(
    db: DbDep, user: Yonetici, durum: str | None = Query(default=None, max_length=12)
) -> list[dict[str, Any]]:
    return [await svc.cikti(db, t) for t in await svc.tumu(db, durum=durum)]


@router.get("/vekil-adaylari")
async def vekil_adaylari(db: DbDep, user: CurrentUser) -> list[dict[str, Any]]:
    return [a for a in await svc.vekil_adaylari(db) if a["id"] != user.id]


@router.get("/ozet")
async def ozet(db: DbDep, user: CurrentUser) -> dict[str, int]:
    return {"onayimda": await svc.bekleyen_sayisi(db, user)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: TalepIn, request: Request, db: DbDep, clock: ClockDep, user: CurrentUser
) -> dict[str, Any]:
    try:
        t = await svc.olustur(
            db,
            svc.TalepGirdisi(**payload.model_dump()),
            aktor=user,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await svc.cikti(db, t)


@router.get("/{talep_id}")
async def getir(talep_id: int, db: DbDep, user: CurrentUser) -> dict[str, Any]:
    return await svc.cikti(db, await _talep(db, talep_id, user))


@router.post("/{talep_id}/iptal")
async def iptal(
    talep_id: int, request: Request, db: DbDep, clock: ClockDep, user: CurrentUser
) -> dict[str, Any]:
    t = await _talep(db, talep_id, user)
    try:
        await svc.iptal(db, t, user=user, clock=clock, ip=client_ip(request))
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await svc.cikti(db, t)


@router.post("/onay/{onay_id}/karar")
async def karar(
    onay_id: int,
    payload: KararIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: CurrentUser,
) -> dict[str, Any]:
    o = await db.get(IzinOnayi, onay_id)
    if o is None or o.onaylayici_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Onay basamağı bulunamadı")
    try:
        t = await svc.karar_ver(
            db,
            o,
            payload.karar == "ONAY",
            aciklama=payload.aciklama,
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await svc.cikti(db, t)


# --- E-posta bağlantısı (oturumsuz, tek kullanımlık anahtar) -----------------------------

Anahtar = Annotated[str, Path(min_length=20, max_length=64)]


@public_router.get("/{token}")
async def public_getir(token: Anahtar, db: DbDep) -> dict[str, Any]:
    """Karar sayfası: talebin özeti. Telefon ve açıklama gösterilmez (oturumsuz)."""
    try:
        o = await svc.token_ile(db, token)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    t = await db.get(IzinTalebi, o.talep_id)
    c = await svc.cikti(db, t, tam=False)
    onayci = next((x["onaylayici"] for x in c["onaylar"] if x["id"] == o.id), None)
    return {
        "personel": c["personel"],
        "tur_adi": c["tur_adi"],
        "baslangic": c["baslangic"],
        "bitis": c["bitis"],
        "gun_sayisi": c["gun_sayisi"],
        "vekil": c["vekil"],
        "izin_ili": c["izin_ili"],
        "onaylayici": onayci,
        "basamak": o.sira,
        "basamak_sayisi": len(c["onaylar"]),
    }


@public_router.post("/{token}/karar")
async def public_karar(
    token: Anahtar, payload: KararIn, request: Request, db: DbDep, clock: ClockDep
) -> dict[str, str]:
    try:
        o = await svc.token_ile(db, token)
        t = await svc.karar_ver(
            db,
            o,
            payload.karar == "ONAY",
            aciklama=payload.aciklama,
            user=None,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"durum": t.durum, "durum_adi": svc.DURUM_ADLARI.get(t.durum, t.durum)}
