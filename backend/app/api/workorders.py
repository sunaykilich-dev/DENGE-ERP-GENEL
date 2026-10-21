"""İş emirleri (= ziyaret) ve cihaz–araç ömür boyu geçmişi."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import (
    Account,
    Device,
    DeviceVehicleAssignment,
    PartnerSettlement,
    Product,
    SettlementLine,
    User,
    Vehicle,
    WorkOrder,
    WorkOrderItem,
)
from app.models.workorder import ODENMEME_NEDENLERI
from app.services import accounts as hesap_svc
from app.services import assignments as atama_svc
from app.services import audit
from app.services import workorders as svc

router = APIRouter(prefix="/api/is-emirleri", tags=["is emirleri"])

Okuyucu = Annotated[User, Depends(require_permission("isemri.gor"))]
Onaylayici = Annotated[User, Depends(require_permission("isemri.onayla"))]
Yazici = Annotated[User, Depends(require_permission("isemri.yaz"))]


class KalemOut(BaseModel):
    id: int
    device_id: int | None
    device_kimlik: str | None = None
    product_name: str | None = None
    action: str
    device_role: str | None
    payability: str
    non_payable_reason: str | None
    unit_price: float | None
    price_source: str | None

    model_config = {"from_attributes": True}


class IsEmriOut(BaseModel):
    id: int
    wo_no: str
    type: str
    status: str
    customer_id: int | None
    customer_title: str | None = None
    vehicle_id: int | None
    vehicle_plate: str | None = None
    odometer_km: int | None
    assigned_id: int | None
    assigned_title: str | None = None
    completed_at: datetime | None
    settlement_period: str
    travel_km: float | None
    travel_unit_price: float | None
    blokajli: bool = False
    kalemler: list[KalemOut] = []
    toplam_tutar: float = 0

    model_config = {"from_attributes": True}


class DonemOut(BaseModel):
    """Cihaz–araç dönemi — kabul kriterleri 2, 3 ve 6."""

    id: int
    device_id: int
    device_kimlik: str | None = None
    vehicle_id: int
    vehicle_plate: str | None = None
    customer_id: int | None
    valid_from: datetime
    valid_to: datetime | None
    removal_reason: str | None
    is_inferred: bool

    model_config = {"from_attributes": True}


async def _cikti(db: DbDep, wo: WorkOrder) -> IsEmriOut:
    out = IsEmriOut.model_validate(wo)
    out.blokajli = wo.blokajli
    if wo.customer_id:
        h = await db.get(Account, wo.customer_id)
        out.customer_title = h.title if h else None
    if wo.assigned_id:
        h = await db.get(Account, wo.assigned_id)
        out.assigned_title = h.title if h else None
    if wo.vehicle_id:
        a = await db.get(Vehicle, wo.vehicle_id)
        out.vehicle_plate = a.plate if a else None

    toplam = 0.0
    for k in wo.items:
        kk = KalemOut.model_validate(k)
        if k.device_id:
            c = await db.get(Device, k.device_id)
            kk.device_kimlik = c.kimlik if c else None
        if k.product_id:
            u = await db.get(Product, k.product_id)
            kk.product_name = u.name if u else None
        if k.payability == "ODENECEK":
            toplam += float(k.unit_price or 0)
        out.kalemler.append(kk)
    if wo.travel_km and wo.travel_unit_price:
        toplam += float(wo.travel_km) * float(wo.travel_unit_price)
    out.toplam_tutar = round(toplam, 2)
    return out


class KalemIn(BaseModel):
    kimlik: str | None = Field(default=None, max_length=32, description="IMEI ya da seri no")
    product_id: int | None = None
    action: str | None = None
    device_role: str | None = None
    channel_no: int | None = None
    payability: str = "KARAR_BEKLIYOR"
    non_payable_reason: str | None = Field(default=None, max_length=24)
    unit_price: Decimal | None = Field(default=None, ge=0)


class IsEmriIn(BaseModel):
    type: str = "MONTAJ"
    completed_at: date
    assigned_id: int | None = None
    customer_id: int | None = None
    plaka: str | None = Field(default=None, max_length=30)
    sase_no: str | None = Field(default=None, max_length=24)
    ruhsat_no: str | None = Field(default=None, max_length=24)
    odometer_km: int | None = Field(default=None, ge=0)
    # Dönem işin ayına EŞİT DEĞİL: iş bir ay yapılıp sonraki ayın hak
    # edişinde ödenebilir. Boş bırakılırsa işin ayı varsayılır.
    settlement_period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    travel_km: Decimal | None = Field(default=None, ge=0)
    travel_unit_price: Decimal | None = Field(default=None, ge=0)
    blokajli: bool = False
    notes: str | None = None
    kalemler: list[KalemIn] = Field(min_length=1)


@router.get("/form-verileri")
async def form_verileri(db: DbDep, _: Okuyucu) -> dict:
    """İş emri formunun açılışta ihtiyaç duyduğu referanslar — tek çağrıda.

    Eski uygulamada bu listeler ayrı ayrı çekiliyordu; form açılırken dört
    istek atmak yerine tek istek, seri girişte hissedilir fark yaratıyor.
    """
    urunler = (
        await db.scalars(
            select(Product)
            .where(Product.is_deleted.is_(False), Product.is_active.is_(True))
            .order_by(Product.name)
        )
    ).all()
    return {
        "montaj_noktalari": await svc.montaj_noktalari(db),
        "urunler": [
            {
                "id": u.id,
                "kod": u.code,
                "ad": u.name,
                "marka": u.brand,
                "aile": u.family,
                "identity_kind": u.identity_kind,
                # Ek kameralar ana cihaza bağlıdır; rol varsayılanı buna bakar.
                "varsayilan_rol": "YARDIMCI_KAMERA" if u.requires_parent else None,
            }
            for u in urunler
        ],
        "is_tipleri": list(svc.TIP_EYLEMI),
        "odenmeme_nedenleri": ODENMEME_NEDENLERI,
    }


@router.get("/imei-kontrol")
async def imei_kontrol(kimlik: str, db: DbDep, _: Okuyucu) -> dict:
    """Bu IMEI şu an başka araçta mı? Form doldurulurken uyarı gösterilir.

    Cihaz söküldüyse sorun yok; hâlâ takılı görünüyorsa kullanıcı yanlış
    IMEI yazmış olabilir. Kaydı ENGELLEMEZ, yalnız uyarır.
    """
    return {"cakisma": await svc.imei_cakismasi(db, kimlik)}


@router.get("/tarife-onizle")
async def tarife_onizle(
    db: DbDep,
    clock: ClockDep,
    _: Okuyucu,
    wo_tipi: str = "MONTAJ",
    montaj_noktasi_id: int | None = None,
    device_role: str | None = None,
    product_id: int | None = None,
    tarih: date | None = None,
) -> dict:
    """Kalemin tarifeden geleceği fiyat. Tarife BAĞLAYICI DEĞİL — öneridir."""
    an = datetime.combine(tarih or clock.now().date(), datetime.min.time(), tzinfo=UTC)
    return await svc.tarife_onizle(
        db,
        partner_id=montaj_noktasi_id,
        wo_tipi=wo_tipi,
        device_role=device_role,
        product_id=product_id,
        an=an,
    )


@router.post("", response_model=IsEmriOut, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: IsEmriIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> IsEmriOut:
    """Montaj/söküm kaydı: ziyaret + araç + cihaz dönemleri tek işlemde."""
    girdi = svc.IsEmriGirdisi(
        type=payload.type,
        completed_at=datetime.combine(payload.completed_at, datetime.min.time(), tzinfo=UTC),
        assigned_id=payload.assigned_id,
        customer_id=payload.customer_id,
        plaka=payload.plaka,
        sase_no=payload.sase_no,
        ruhsat_no=payload.ruhsat_no,
        odometer_km=payload.odometer_km,
        settlement_period=payload.settlement_period,
        travel_km=payload.travel_km,
        travel_unit_price=payload.travel_unit_price,
        blokajli=payload.blokajli,
        notes=payload.notes,
        kalemler=[svc.KalemGirdisi(**k.model_dump()) for k in payload.kalemler],
    )
    try:
        wo = await svc.olustur(db, girdi, clock=clock, user_id=user.id)
    except (svc.IsEmriHatasi, atama_svc.AtamaHatasi) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "work_orders",
        "olustur",
        entity_id=wo.id,
        new_value={
            "wo_no": wo.wo_no,
            "tip": wo.type,
            "donem": wo.settlement_period,
            "kalem": len(payload.kalemler),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()

    yeniden = await db.scalar(
        select(WorkOrder).where(WorkOrder.id == wo.id).options(selectinload(WorkOrder.items))
    )
    return await _cikti(db, yeniden)


@router.get("", response_model=list[IsEmriOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    donem: str | None = Query(default=None, description="YYYY-AA"),
    montaj_noktasi_id: int | None = None,
    arac_id: int | None = None,
    durum: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[IsEmriOut]:
    stmt = (
        select(WorkOrder)
        .where(WorkOrder.is_deleted.is_(False))
        .options(selectinload(WorkOrder.items))
        .order_by(WorkOrder.completed_at.desc().nullslast())
    )
    stmt = hesap_svc.kapsam_musteri(stmt, user, WorkOrder.customer_id)
    if donem:
        stmt = stmt.where(WorkOrder.settlement_period == donem)
    if montaj_noktasi_id:
        stmt = stmt.where(WorkOrder.assigned_id == montaj_noktasi_id)
    if arac_id:
        stmt = stmt.where(WorkOrder.vehicle_id == arac_id)
    if durum:
        stmt = stmt.where(WorkOrder.status == durum)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [await _cikti(db, wo) for (wo,) in satirlar]


@router.get("/cihaz/{device_id}/gecmis", response_model=list[DonemOut])
async def cihaz_gecmisi(device_id: int, db: DbDep, _: Okuyucu) -> list[DonemOut]:
    """Bu cihaz ömrü boyunca hangi araçlarda, hangi tarihlerde takılıydı."""
    kayitlar = (
        await db.scalars(
            select(DeviceVehicleAssignment)
            .where(DeviceVehicleAssignment.device_id == device_id)
            .order_by(DeviceVehicleAssignment.valid_from.desc())
        )
    ).all()
    return await _donem_ciktilari(db, kayitlar)


@router.get("/arac/{vehicle_id}/gecmis", response_model=list[DonemOut])
async def arac_gecmisi(
    vehicle_id: int, db: DbDep, _: Okuyucu, yalniz_takili: bool = False
) -> list[DonemOut]:
    """Kabul kriteri 3: bu araçta bugüne kadar hangi cihazlar takıldı."""
    kayitlar = await atama_svc.aracin_cihazlari(db, vehicle_id, yalniz_takili=yalniz_takili)
    return await _donem_ciktilari(db, kayitlar)


@router.get("/cihaz/{device_id}/tarihinde", response_model=DonemOut | None)
async def cihaz_tarihinde(device_id: int, an: datetime, db: DbDep, _: Okuyucu) -> DonemOut | None:
    """Kabul kriteri 2: X tarihinde bu cihaz hangi araçtaydı."""
    kayit = await atama_svc.arac_tarihinde(db, device_id, an)
    if kayit is None:
        return None
    return (await _donem_ciktilari(db, [kayit]))[0]


async def _donem_ciktilari(db: DbDep, kayitlar) -> list[DonemOut]:
    sonuc = []
    for k in kayitlar:
        out = DonemOut.model_validate(k)
        cihaz = await db.get(Device, k.device_id)
        arac = await db.get(Vehicle, k.vehicle_id)
        out.device_kimlik = cihaz.kimlik if cihaz else None
        out.vehicle_plate = arac.plate if arac else None
        sonuc.append(out)
    return sonuc


class OnayIn(BaseModel):
    onayla: bool = True


@router.post("/{wo_id}/onayla", response_model=IsEmriOut)
async def onayla(
    wo_id: int, payload: OnayIn, request: Request, db: DbDep, clock: ClockDep, user: Onaylayici
) -> IsEmriOut:
    """Tamamlanan işi onaylar — hak edişe bu onayla girer."""
    wo = await db.get(WorkOrder, wo_id, options=[selectinload(WorkOrder.items)])
    if wo is None or wo.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "İş emri bulunamadı")
    if wo.status not in ("TAMAMLANDI", "ONAYLANDI"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Yalnız tamamlanmış iş onaylanır (mevcut durum: {wo.status})",
        )
    bekleyen = [k for k in wo.items if k.payability == "KARAR_BEKLIYOR"]
    if bekleyen:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(bekleyen)} kalemin ödenip ödenmeyeceği belirlenmemiş — önce karar verin.",
        )
    wo.status = "ONAYLANDI"
    wo.approved_at = clock.now()
    wo.approved_by = user.id
    await audit.log(
        db,
        "work_orders",
        "onayla",
        entity_id=wo.id,
        new_value={"wo_no": wo.wo_no},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(wo, ["items"])
    return await _cikti(db, wo)


class KalemKararIn(BaseModel):
    payability: str
    non_payable_reason: str | None = None
    unit_price: float | None = None


class HakedisDonemiIn(BaseModel):
    settlement_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    gerekce: str = Field(min_length=5, max_length=300)


@router.patch("/{wo_id}/hakedis-donemi", response_model=IsEmriOut)
async def hakedis_donemini_degistir(
    wo_id: int,
    payload: HakedisDonemiIn,
    request: Request,
    db: DbDep,
    user: Annotated[User, Depends(require_permission("hakedis.yaz"))],
) -> IsEmriOut:
    """İşin hangi DÖNEMDE ödeneceğini değiştirir (iş tarihi değişmez).

    Kapanmış dönem değişmez (plan §3.3/3): ödenmiş bir döküme sonradan
    giren iş, hak edişini ancak dönemi ileri alınarak alabilir. Bu uç
    olmadan `donem-kapat` o kalemi hiçbir zaman yazamıyordu ve montaj
    noktası parasını alamıyordu.

    ZATEN KİLİTLİ bir dökümde satırı olan iş emri taşınamaz: ödenmiş tutar
    geriye dönük değişmemeli.
    """
    wo = await db.get(WorkOrder, wo_id)
    if wo is None or wo.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "İş emri bulunamadı")

    kilitli = await db.scalar(
        select(SettlementLine.id)
        .join(PartnerSettlement, PartnerSettlement.id == SettlementLine.settlement_id)
        .where(SettlementLine.work_order_id == wo_id, SettlementLine.locked_at.is_not(None))
        .limit(1)
    )
    if kilitli is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu iş emrinin ödenmiş bir dökümde satırı var; dönemi değiştirilemez. "
            "Düzeltme sonraki döneme ayrı bir satır olarak girer.",
        )

    eski_donem = wo.settlement_period
    wo.settlement_period = payload.settlement_period
    wo.updated_by = user.id
    await audit.log(
        db,
        "work_orders",
        "hakedis.donem.degistir",
        entity_id=wo.id,
        old_value={"settlement_period": eski_donem},
        new_value={"settlement_period": payload.settlement_period, "gerekce": payload.gerekce},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, wo)


@router.patch("/kalem/{kalem_id}", response_model=KalemOut)
async def kalem_karari(
    kalem_id: int,
    payload: KalemKararIn,
    request: Request,
    db: DbDep,
    user: Annotated[User, Depends(require_permission("isemri.yaz"))],
) -> KalemOut:
    """Kalemin ödenebilirliğini ve tutarını belirler.

    Tarife yalnız öneridir; burada girilen tutar bağlayıcıdır.
    """
    kalem = await db.get(WorkOrderItem, kalem_id)
    if kalem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kalem bulunamadı")
    # Kapanmış dönem yalnız DÖKÜM SATIRINI koruyordu, KAYNAĞI korumuyordu:
    # ödenmiş bir kalemin tutarı 350 → 99.999 yapılabiliyor, döküm 350'de
    # kalıyor ama dönem paneli 99.999'u gösteriyordu. Ödenen tutarla ekranda
    # görünen tutar kalıcı olarak ayrışıyordu — mutabakatı imkânsız kılan
    # türden bir sapma.
    kilitli = await db.scalar(
        select(SettlementLine.id)
        .where(SettlementLine.work_order_item_id == kalem_id, SettlementLine.locked_at.is_not(None))
        .limit(1)
    )
    if kilitli is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kalem ödenmiş bir hak ediş dökümünde; değiştirilemez. "
            "Düzeltme sonraki döneme ayrı bir satır olarak girer.",
        )
    if payload.payability == "ODENMEYECEK" and not payload.non_payable_reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ödenmeyecek kalemde neden zorunludur")
    kalem.payability = payload.payability
    kalem.non_payable_reason = payload.non_payable_reason
    if payload.unit_price is not None:
        kalem.unit_price = payload.unit_price
        kalem.price_source = "MANUEL"
    await audit.log_change(db, kalem, "karar", user_id=user.id, ip=client_ip(request))
    await db.commit()
    return KalemOut.model_validate(kalem)
