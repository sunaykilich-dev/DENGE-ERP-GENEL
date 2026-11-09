"""İrsaliyeler: liste, PDF, iptal, muhasebe devri, Logo dökümü (KARARLAR 2026-11-09 S4.3/S4.4).

İrsaliye bu uçlardan AÇILMAZ: sevkiyatla (sipariş sevki, Stok ekranındaki
dış transfer) aynı işlemde üretilir. Görme: `siparis.gor` ya da `cihaz.gor`
(depo); `KENDI_MUSTERILERI` kapsamı yalnız kendi siparişinin irsaliyesini
görür. Fiyat anahtarları/kolonları yalnız `irsaliye.fiyat_gorur_mu` ile.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import ClockDep, DbDep, client_ip, require_any_permission, require_permission
from app.models import User
from app.services import audit, muhasebe_aktarim
from app.services import irsaliye as svc
from app.services.pdf import PdfUretilemedi

router = APIRouter(prefix="/api/irsaliyeler", tags=["irsaliye"])

Okuyucu = Annotated[User, Depends(require_any_permission("siparis.gor", "cihaz.gor"))]
Iptalci = Annotated[User, Depends(require_any_permission("siparis.yaz", "cihaz.transfer"))]
Devredici = Annotated[User, Depends(require_permission("tahsilat.yaz"))]
Aktarici = Annotated[User, Depends(require_permission("rapor.disaaktar"))]

_DONEM = r"^\d{4}-(0[1-9]|1[0-2])$"


def _okuma_hakki(user: User) -> None:
    if not (user.has("siparis.gor") or user.has("cihaz.gor")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Bu işlem için yetkiniz yok (siparis.gor veya cihaz.gor)"
        )


async def _getir(db: DbDep, irsaliye_id: int, user: User):
    irs = await svc.kapsamli_getir(db, irsaliye_id, user)
    if irs is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "İrsaliye bulunamadı")
    return irs


def _suzgec(**kw: Any) -> svc.IrsaliyeSuzgeci:
    temiz = {k: (v or None) if isinstance(v, str) else v for k, v in kw.items()}
    return svc.IrsaliyeSuzgeci(**temiz)


@router.get("")
async def listele(
    db: DbDep,
    user: Okuyucu,
    order_id: int | None = None,
    transfer_id: int | None = None,
    devir: Literal["bekleyen", "devredildi"] | None = None,
    durum: Literal["DUZENLENDI", "IPTAL"] | None = None,
    donem: str | None = Query(default=None, pattern=_DONEM),
    ara: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    stmt = svc.liste_sorgusu(
        user,
        _suzgec(
            order_id=order_id,
            transfer_id=transfer_id,
            devir=devir,
            durum=durum,
            donem=donem,
            ara=ara,
        ),
    ).limit(limit)
    kayitlar = list((await db.scalars(stmt)).all())
    adlar = await svc.kullanici_adlari(db, {k.muhasebe_devri_by for k in kayitlar})
    return [svc.cikti(k, user, adlar) for k in kayitlar]


@router.get("/logo-aktarim")
async def logo_aktarim(
    request: Request,
    db: DbDep,
    user: Aktarici,
    devir: Literal["bekleyen", "devredildi"] | None = "bekleyen",
    donem: str | None = Query(default=None, pattern=_DONEM),
    bicim: Literal["xlsx", "csv"] = "xlsx",
) -> Response:
    """Logo'ya aktarılabilir irsaliye dökümü (satır bazlı). Logo API'si DEĞİL."""
    _okuma_hakki(user)
    kayitlar = list(
        (await db.scalars(svc.liste_sorgusu(user, _suzgec(devir=devir, donem=donem)))).all()
    )
    kayitlar.sort(key=lambda i: (i.yil, i.sira))
    sutunlar, satirlar = await muhasebe_aktarim.irsaliye_tablosu(db, user, kayitlar)
    icerik, medya, uzanti = await muhasebe_aktarim.dosya_uret(
        bicim, "İrsaliyeler", sutunlar, satirlar
    )
    await audit.log(
        db,
        "irsaliyeler",
        "logo_aktarim",
        new_value={
            "devir": devir,
            "donem": donem,
            "bicim": bicim,
            "satir": len(satirlar),
            "fiyatli": svc.fiyat_gorur_mu(user),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    ad = f"irsaliye-logo-{devir or 'tumu'}.{uzanti}"
    return Response(
        content=icerik,
        media_type=medya,
        headers={"Content-Disposition": f'attachment; filename="{ad}"'},
    )


class DevretIn(BaseModel):
    irsaliye_idler: list[int] = Field(min_length=1, max_length=200)
    not_: str | None = Field(default=None, alias="not", max_length=300)

    model_config = {"populate_by_name": True}


class GerekceIn(BaseModel):
    gerekce: str = Field(min_length=1, max_length=300)


class IptalIn(BaseModel):
    neden: str = Field(min_length=3, max_length=300)
    version: int


@router.post("/muhasebe-devri")
async def muhasebe_devret(
    payload: DevretIn, request: Request, db: DbDep, clock: ClockDep, user: Devredici
) -> dict:
    """Toplu "muhasebeye devredildi"; biri uygun değilse TAMAMI 409 (`sorunlu`)."""
    _okuma_hakki(user)
    try:
        idler = await svc.devret(
            db, user, payload.irsaliye_idler, not_=payload.not_, clock=clock, ip=client_ip(request)
        )
    except svc.IrsaliyeGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except svc.IrsaliyeHatasi as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"mesaj": str(exc), "sorunlu": exc.sorunlu}
        ) from exc
    await db.commit()
    return {"devredilen": idler}


@router.get("/{irsaliye_id}")
async def getir(irsaliye_id: int, db: DbDep, user: Okuyucu) -> dict[str, Any]:
    irs = await _getir(db, irsaliye_id, user)
    adlar = await svc.kullanici_adlari(db, {irs.muhasebe_devri_by})
    return svc.cikti(irs, user, adlar)


@router.get("/{irsaliye_id}/pdf")
async def pdf(irsaliye_id: int, db: DbDep, user: Okuyucu, fiyatli: bool = False) -> Response:
    """İrsaliye PDF'i. `fiyatli=true` yalnız fiyat görme yetkisi olana uygulanır;
    yetkisizde sessizce fiyatsız basılır (belge yine alınabilsin)."""
    irs = await _getir(db, irsaliye_id, user)
    try:
        icerik = await svc.pdf_uret(db, irs, fiyatli=fiyatli and svc.fiyat_gorur_mu(user))
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{irs.irsaliye_no}.pdf"'},
    )


@router.post("/{irsaliye_id}/iptal")
async def iptal(
    irsaliye_id: int, payload: IptalIn, request: Request, db: DbDep, clock: ClockDep, user: Iptalci
) -> dict[str, Any]:
    """Belgeyi gerekçeyle iptal eder; numara iptal olarak kalır. Stok geri
    alınmaz (iade transferiyle kaydedilir)."""
    _okuma_hakki(user)
    irs = await _getir(db, irsaliye_id, user)
    try:
        await svc.iptal_et(
            db,
            irs,
            neden=payload.neden,
            version=payload.version,
            clock=clock,
            user_id=user.id,
            ip=client_ip(request),
        )
    except svc.IrsaliyeGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except svc.IrsaliyeHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return svc.cikti(irs, user)


@router.post("/{irsaliye_id}/muhasebe-devri/geri-al")
async def muhasebe_devri_geri_al(
    irsaliye_id: int, payload: GerekceIn, request: Request, db: DbDep, user: Devredici
) -> dict[str, Any]:
    _okuma_hakki(user)
    irs = await _getir(db, irsaliye_id, user)
    try:
        await svc.devri_geri_al(db, user, irs, gerekce=payload.gerekce, ip=client_ip(request))
    except svc.IrsaliyeGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except svc.IrsaliyeHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return svc.cikti(irs, user)
