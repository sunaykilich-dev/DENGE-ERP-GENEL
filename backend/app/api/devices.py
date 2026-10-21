"""Cihazlar — kart, liste, durum geçişi."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import (
    Attachment,
    Device,
    DeviceStatusHistory,
    Product,
    SimCard,
    SimDeviceHistory,
    User,
)
from app.schemas.devices import (
    CihazIn,
    CihazKarti,
    CihazOut,
    DurumDegistirIn,
    DurumGecmisi,
    HatOzeti,
)
from app.services import accounts as hesap_svc
from app.services import audit
from app.services import devices as svc
from app.services.statemachine import CIHAZ, IzinsizGecis

router = APIRouter(prefix="/api/cihazlar", tags=["cihazlar"])

Okuyucu = Annotated[User, Depends(require_permission("cihaz.gor"))]
Yazici = Annotated[User, Depends(require_permission("cihaz.yaz"))]


def _cikti(cihaz: Device, urun: Product | None) -> CihazOut:
    out = CihazOut.model_validate(cihaz)
    out.kimlik = cihaz.kimlik
    out.sonraki_durumlar = sorted(CIHAZ.sonraki(cihaz.status))
    if urun is not None:
        out.product_code, out.product_name, out.product_family = urun.code, urun.name, urun.family
    return out


@router.get("", response_model=list[CihazOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    q: str | None = Query(default=None, description="IMEI, seri no veya ürün adı"),
    durum: str | None = None,
    kimligi_gecici: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[CihazOut]:
    stmt = (
        select(Device, Product)
        .join(Product, Product.id == Device.product_id)
        .where(Device.is_deleted.is_(False))
        .order_by(Device.id.desc())
    )
    stmt = hesap_svc.kapsam_musteri(stmt, user, Device.current_customer_id)
    if q:
        stmt = stmt.where(
            or_(
                Device.imei.startswith(q),
                Device.serial_no.ilike(f"%{q}%"),
                Product.name.ilike(f"%{q}%"),
            )
        )
    if durum:
        stmt = stmt.where(Device.status == durum)
    if kimligi_gecici:
        stmt = stmt.where(Device.is_identity_provisional.is_(True))

    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    cikti = [_cikti(c, u) for c, u in satirlar]
    await _baglantilari_doldur(db, [c for c, _u in satirlar], cikti)
    return cikti


async def _baglantilari_doldur(db: DbDep, cihazlar: list[Device], cikti: list[CihazOut]) -> None:
    """Listeye hat, araç ve müşteri bilgisini ekler.

    Üç TOPLU sorgu kullanılır; cihaz başına ayrı sorgu (N+1) 500 satırlık bir
    listede sayfayı saniyelerce bekletirdi. Kaynak, tarihli tablolardan
    türetilmiş `current_*` alanları — doğruluk kaynağı yine tarihli tablodur
    (bkz. devices.uzlastir).
    """
    from app.models import Account, SimCard, Vehicle

    async def _harita(model, kimlikler: set[int], *alanlar):
        if not kimlikler:
            return {}
        satirlar = (
            await db.execute(select(model.id, *alanlar).where(model.id.in_(kimlikler)))
        ).all()
        return {r[0]: r[1:] for r in satirlar}

    hatlar = await _harita(
        SimCard,
        {c.current_sim_id for c in cihazlar if c.current_sim_id},
        SimCard.msisdn,
        SimCard.iccid,
    )
    araclar = await _harita(
        Vehicle, {c.current_vehicle_id for c in cihazlar if c.current_vehicle_id}, Vehicle.plate
    )
    musteriler = await _harita(
        Account, {c.current_customer_id for c in cihazlar if c.current_customer_id}, Account.title
    )

    for cihaz, out in zip(cihazlar, cikti, strict=True):
        if hat := hatlar.get(cihaz.current_sim_id or 0):
            out.hat_msisdn, out.hat_iccid = hat
        if arac := araclar.get(cihaz.current_vehicle_id or 0):
            (out.arac_plaka,) = arac
        if musteri := musteriler.get(cihaz.current_customer_id or 0):
            (out.musteri_unvan,) = musteri


@router.get("/{kimlik}", response_model=CihazKarti)
async def kart(kimlik: str, db: DbDep, _: Okuyucu) -> CihazKarti:
    """IMEI, seri no veya id ile cihaz kartı — kabul kriteri 1."""
    kosul = or_(Device.imei == kimlik, Device.serial_no == kimlik)
    if kimlik.isdigit() and len(kimlik) < 15:
        kosul = or_(kosul, Device.id == int(kimlik))

    satir = (
        await db.execute(
            select(Device, Product)
            .join(Product, Product.id == Device.product_id)
            .where(kosul, Device.is_deleted.is_(False))
        )
    ).first()
    if satir is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"'{kimlik}' ile cihaz bulunamadı")
    cihaz, urun = satir

    karti = CihazKarti.model_validate(_cikti(cihaz, urun).model_dump())

    # Takılı hat — doğruluk kaynağı tarihli tablo, denormalize alan değil.
    acik = await svc.aktif_hat(db, cihaz.id)
    if acik is not None:
        hat = await db.get(SimCard, acik.sim_id)
        if hat is not None:
            karti.hat = HatOzeti.model_validate(hat)
        # Eşleşme ICCID'den geldi, aktivasyon anı kaynakta yoktu. Ekranda
        # boş bir tarih göstermek yerine bunu AÇIKÇA söyle: ekip gerçek
        # tarihi girebilsin, kimse uydurulmuş bir tarihe güvenmesin.
        karti.hat_baslangici_bilinmiyor = acik.valid_from is None
    karti.hat_gecmisi_adedi = (
        await db.scalar(
            select(func.count())
            .select_from(SimDeviceHistory)
            .where(SimDeviceHistory.device_id == cihaz.id)
        )
        or 0
    )

    # Ek kameralar (ana cihazın kanalları)
    altlar = (
        await db.execute(
            select(Device, Product)
            .join(Product, Product.id == Device.product_id)
            .where(Device.parent_device_id == cihaz.id, Device.is_deleted.is_(False))
            .order_by(Device.channel_no)
        )
    ).all()
    karti.alt_cihazlar = [_cikti(c, u) for c, u in altlar]

    if cihaz.parent_device_id:
        ana = await db.get(Device, cihaz.parent_device_id)
        karti.parent_kimlik = ana.kimlik if ana else None

    gecmis = (
        await db.scalars(
            select(DeviceStatusHistory)
            .where(DeviceStatusHistory.device_id == cihaz.id)
            .order_by(DeviceStatusHistory.changed_at.desc())
            .limit(50)
        )
    ).all()
    karti.durum_gecmisi = [DurumGecmisi.model_validate(g) for g in gecmis]

    karti.ek_adedi = (
        await db.scalar(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.entity == "devices", Attachment.entity_id == cihaz.id)
        )
        or 0
    )
    return karti


@router.post("", response_model=CihazOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: CihazIn, request: Request, db: DbDep, user: Yazici) -> CihazOut:
    try:
        identity_kind = await svc.kimlik_dogrula(
            db, payload.product_id, payload.imei, payload.serial_no
        )
    except svc.KimlikHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    cihaz = Device(**payload.model_dump(), identity_kind=identity_kind, created_by=user.id)
    db.add(cihaz)
    await db.flush()
    await audit.log(
        db,
        "devices",
        "olustur",
        entity_id=cihaz.id,
        new_value={"kimlik": cihaz.kimlik, "urun": payload.product_id},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    urun = await db.get(Product, cihaz.product_id)
    return _cikti(cihaz, urun)


@router.post("/{cihaz_id}/durum", response_model=CihazOut)
async def durum_degistir(
    cihaz_id: int,
    payload: DurumDegistirIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> CihazOut:
    cihaz = await db.get(Device, cihaz_id)
    if cihaz is None or cihaz.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cihaz bulunamadı")
    try:
        await svc.durum_degistir(
            db,
            cihaz,
            payload.to_status,
            clock=clock,
            user_id=user.id,
            neden=payload.reason,
            ip=client_ip(request),
        )
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    urun = await db.get(Product, cihaz.product_id)
    return _cikti(cihaz, urun)


@router.post("/uzlastir")
async def uzlastir(
    request: Request,
    db: DbDep,
    user: Annotated[User, Depends(require_permission("sistem.goc"))],
    yaz: bool = True,
) -> dict:
    """Türetilmiş "şu an" alanlarını tarihli tablolardan yeniden hesaplar.

    `yaz=false` ile yalnız farkı raporlar. Gece koşan iş bu ucu kullanır;
    göçten sonra bir kez elle çalıştırmak da gerekir.
    """
    sonuc = await svc.uzlastir(db, yaz=yaz, user_id=user.id)
    if yaz and sonuc["farkli"]:
        await audit.log(
            db,
            "devices",
            "uzlastir",
            new_value={"incelenen": sonuc["incelenen"], "farkli": sonuc["farkli"]},
            user_id=user.id,
            ip=client_ip(request),
        )
    await db.commit()
    return sonuc
