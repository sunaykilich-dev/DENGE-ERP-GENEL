"""RMA / garanti / teknik servis.

**Kapsam (TS-217):** liste ve tek kayıt uçları müşteri kapsamına tabidir.
Canlıda `rma.gor` izni olan satış temsilcisi (KENDI_MUSTERILERI) bütün RMA
kayıtlarını — başka temsilcilerin müşterilerine ait cihaz, araç plakası ve
arıza metniyle — listeleyebiliyor, kimlik numarasıyla tek tek açabiliyordu.
Kural cihaz/araç listeleriyle aynıdır (`accounts.kapsam_musteri`): müşterisi
portföyde olmayan kayıt görünmez ve yazılamaz (404, yazmadan ÖNCE);
müşterisiz kayıt (Denge stoğu) görünür. TUMU kapsamlı rollerde davranış
değişmez.

**Maliyet (M6.5, KARARLAR 2026-10-28 §7 Faz A/3):** `cost` alanı `maliyet.gor`
olmayan kullanıcıya hiçbir uçta (liste, tek kayıt, açılış/durum/çözüm/tedarikçi
yanıtı) dolu dönmez — `null` gelir (`api/sims._detay` kalıbı). Bu kullanıcı
çözümde dolu bir `cost` gönderirse 403 (sessizce yok saymak, "kaydettim"
sanılan bedeli kaybettirirdi; `api/bakim._ucret_yetkisi` kalıbı). Denetim
kaydındaki maliyet yalnız denetim izni olanlara açıktır.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala, sees_cost
from app.models import Account, Device, RmaCase, User, Vehicle
from app.models.service import COZUM_TIPLERI
from app.services import accounts as hesap_svc
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


async def _cikti(db: DbDep, k: RmaCase, user: User) -> RmaOut:
    out = RmaOut.model_validate(k)
    if not sees_cost(user):
        # Maliyet varsayılan gizli (M6.5): alan yanıtta boş döner, 0 yazılmaz.
        out.cost = None
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


async def _rma_al(db: DbDep, rma_id: int, user: User) -> RmaCase:
    """Tek kayıt: yok, silinmiş ya da müşteri kapsamı dışında → aynı 404.

    Kapsam yazmadan ÖNCE sorulur; "var ama göremezsin" ayrımı yapılmaz ki
    sıralı kimliklerle kayıt taranamasın (KD-05)."""
    k = await db.get(RmaCase, rma_id)
    if k is None or k.is_deleted or await hesap_svc.kapsam_disinda_mi(db, user, k.customer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis kaydı bulunamadı")
    return k


async def _cihaz_bul(db: DbDep, device_id: int | None, kimlik: str | None, user: User) -> Device:
    """Cihaz kimlik/IMEI ile; müşteri kapsamı dışındaki cihaz yokmuş gibi 404
    (cihaz kartıyla aynı kural, `api/devices.kart`)."""
    if device_id:
        cihaz = await db.get(Device, device_id)
    elif kimlik:
        cihaz = await db.scalar(
            select(Device).where((Device.imei == kimlik) | (Device.serial_no == kimlik))
        )
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cihaz seçilmedi (IMEI ya da seri no)")
    if (
        cihaz is None
        or cihaz.is_deleted
        or await hesap_svc.kapsam_disinda_mi(db, user, cihaz.current_customer_id)
    ):
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
    offset: int = Query(default=0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[RmaOut]:
    """Müşteri kapsamlı ve sayfalı liste; toplam `X-Toplam-Kayit` başlığında.

    Canlıda yalnız `limit` vardı: 50'den eski kayıtlar hiçbir sayfada
    görünmüyordu (sessiz kesme). Dönüş şekli (düz dizi) değişmez."""
    stmt = select(RmaCase).where(RmaCase.is_deleted.is_(False)).order_by(RmaCase.id.desc())
    stmt = hesap_svc.kapsam_musteri(stmt, user, RmaCase.customer_id)
    if durum:
        stmt = stmt.where(RmaCase.status == durum)
    if cihaz_id:
        stmt = stmt.where(RmaCase.device_id == cihaz_id)
    if musteri_id:
        stmt = stmt.where(RmaCase.customer_id == musteri_id)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [await _cikti(db, k, user) for (k,) in satirlar]


@router.get("/ariza-orani")
async def ariza_orani(
    db: DbDep, clock: ClockDep, user: Okuyucu, gun: int = Query(default=365, ge=1, le=3650)
) -> list[dict]:
    """Model bazında arıza oranı — payda o modeldeki toplam cihaz."""
    return await svc.ariza_orani(db, gun=gun, clock=clock)


@router.get("/{rma_id}", response_model=RmaOut)
async def getir(rma_id: int, db: DbDep, user: Okuyucu) -> RmaOut:
    k = await _rma_al(db, rma_id, user)
    return await _cikti(db, k, user)


@router.post("", response_model=RmaOut, status_code=status.HTTP_201_CREATED)
async def ac(payload: RmaIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici) -> RmaOut:
    """Servis kaydı açar; garanti durumu OTOMATİK hesaplanıp dondurulur."""
    cihaz = await _cihaz_bul(db, payload.device_id, payload.kimlik, user)
    if await hesap_svc.kapsam_disinda_mi(db, user, payload.customer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Müşteri bulunamadı")
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
    return await _cikti(db, kayit, user)


@router.post("/{rma_id}/durum", response_model=RmaOut)
async def durum_degistir(
    rma_id: int,
    payload: DurumIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> RmaOut:
    k = await _rma_al(db, rma_id, user)
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
    return await _cikti(db, k, user)


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
    k = await _rma_al(db, rma_id, user)
    if payload.cost is not None and not sees_cost(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Maliyet alanı için yetkiniz yok (maliyet.gor)"
        )
    if payload.resolution not in COZUM_TIPLERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Çözüm {COZUM_TIPLERI} içinden olmalı")

    yeni_id = payload.replacement_device_id
    if yeni_id is None and payload.replacement_kimlik:
        yeni_id = (await _cihaz_bul(db, None, payload.replacement_kimlik, user)).id
    elif yeni_id is not None:
        # Varlık/uygunluk kuralı serviste (değişmedi); burada yalnız kapsam.
        yeni = await db.get(Device, yeni_id)
        if yeni is not None and await hesap_svc.kapsam_disinda_mi(
            db, user, yeni.current_customer_id
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cihaz bulunamadı")

    try:
        await svc.coz(
            db,
            k,
            cozum=payload.resolution,
            clock=clock,
            not_=payload.resolution_note,
            # Maliyet görmeyen kullanıcının çözümü, başkasının girdiği bedeli
            # sessizce silmesin: mevcut değer korunur.
            maliyet=payload.cost if sees_cost(user) else k.cost,
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
    return await _cikti(db, k, user)


@router.patch("/{rma_id}/tedarikci", response_model=RmaOut)
async def tedarikci_bilgisi(
    rma_id: int,
    payload: TedarikciIn,
    request: Request,
    db: DbDep,
    user: Yazici,
) -> RmaOut:
    """Üreticiye garanti iadesi takibi (brief §4.12)."""
    k = await _rma_al(db, rma_id, user)
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
    return await _cikti(db, k, user)
