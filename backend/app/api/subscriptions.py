"""Abonelik ve sözleşme: tarihli ücret, kıst tahakkuk, MRR ve churn."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import Account, Subscription, SubscriptionEvent, SubscriptionPrice, User
from app.models.subscription import (
    FATURA_PERIYOTLARI,
    YENILEME_TIPLERI,
)
from app.services import audit
from app.services import export as export_svc
from app.services import settings as ayar_svc
from app.services import subscriptions as svc
from app.services.statemachine import ABONELIK, IzinsizGecis

router = APIRouter(prefix="/api/abonelikler", tags=["abonelik"])

Okuyucu = Annotated[User, Depends(require_permission("abonelik.gor"))]
Yazici = Annotated[User, Depends(require_permission("abonelik.yaz"))]


# --- Şemalar ------------------------------------------------------------------


class AbonelikIn(BaseModel):
    customer_id: int
    title: str | None = Field(default=None, max_length=200)
    vehicle_id: int | None = None
    device_id: int | None = None
    sim_id: int | None = None
    product_id: int | None = None
    order_id: int | None = None
    billing_period: str = "AYLIK"
    currency: str = "TRY"
    # KDV oranı KESİR (0.20 = %20) — Numeric(5,4) taşmasını engeller.
    vat_rate: Decimal | None = Field(default=None, ge=0, le=1)
    # `FiyatIn`'de `ge=0` vardı, burada yoktu: sözleşme negatif ücretle
    # açılabiliyor ve MRR'ı aşağı çekiyordu.
    unit_price: Decimal = Field(ge=0)
    start_date: date
    end_date: date | None = None
    commitment_end_date: date | None = None
    renewal_type: str = "OTOMATIK"
    renewal_months: int = 12
    notice_days: int = 30
    notes: str | None = None

    def dogrula(self) -> None:
        if self.billing_period not in FATURA_PERIYOTLARI:
            raise ValueError(f"Fatura periyodu {FATURA_PERIYOTLARI} içinden olmalı")
        if self.renewal_type not in YENILEME_TIPLERI:
            raise ValueError(f"Yenileme tipi {YENILEME_TIPLERI} içinden olmalı")


class AbonelikGuncelle(BaseModel):
    title: str | None = None
    vehicle_id: int | None = None
    device_id: int | None = None
    sim_id: int | None = None
    end_date: date | None = None
    commitment_end_date: date | None = None
    renewal_type: str | None = None
    renewal_months: int | None = None
    notice_days: int | None = None
    notes: str | None = None
    version: int


class FiyatOut(BaseModel):
    id: int
    unit_price: Decimal
    valid_from: date
    valid_to: date | None
    change_reason: str | None

    model_config = {"from_attributes": True}


class OlayOut(BaseModel):
    id: int
    event_type: str
    event_date: date
    mrr_before: Decimal
    mrr_after: Decimal
    mrr_delta: Decimal
    reason: str | None

    model_config = {"from_attributes": True}


class AbonelikOut(BaseModel):
    id: int
    subscription_no: str
    customer_id: int
    customer_title: str | None = None
    title: str | None
    vehicle_id: int | None
    device_id: int | None
    sim_id: int | None
    product_id: int | None
    order_id: int | None
    status: str
    billing_period: str
    currency: str
    vat_rate: Decimal
    start_date: date
    end_date: date | None
    commitment_end_date: date | None
    renewal_type: str
    renewal_months: int
    notice_days: int
    cancel_reason: str | None
    notes: str | None
    version: int
    guncel_fiyat: Decimal | None = None
    aylik_tutar: Decimal | None = None
    taahhut_devam: bool = False
    sonraki_durumlar: list[str] = []
    fiyat_gecmisi: list[FiyatOut] = []
    olaylar: list[OlayOut] = []

    model_config = {"from_attributes": True}


# --- Yardımcılar --------------------------------------------------------------


async def _cikti(db: DbDep, a: Subscription, clock, *, detay: bool = True) -> AbonelikOut:
    out = AbonelikOut.model_validate(a)
    h = await db.get(Account, a.customer_id)
    out.customer_title = h.title if h else None
    out.sonraki_durumlar = sorted(ABONELIK.sonraki(a.status))

    bugun = clock.now().date()
    out.taahhut_devam = bool(a.commitment_end_date and a.commitment_end_date >= bugun)
    fiyat = await svc.gecerli_fiyat(db, a.id, max(bugun, a.start_date))
    if fiyat is not None:
        out.guncel_fiyat = Decimal(str(fiyat.unit_price))
        out.aylik_tutar = svc.aylik_tutar(fiyat.unit_price, a.billing_period)

    if detay:
        out.fiyat_gecmisi = [
            FiyatOut.model_validate(f)
            for f in (
                await db.scalars(
                    select(SubscriptionPrice)
                    .where(SubscriptionPrice.subscription_id == a.id)
                    .order_by(SubscriptionPrice.valid_from)
                )
            ).all()
        ]
        out.olaylar = [
            OlayOut.model_validate(o)
            for o in (
                await db.scalars(
                    select(SubscriptionEvent)
                    .where(SubscriptionEvent.subscription_id == a.id)
                    .order_by(SubscriptionEvent.event_date, SubscriptionEvent.id)
                )
            ).all()
        ]
    return out


async def _getir(db: DbDep, abonelik_id: int) -> Subscription:
    a = await db.get(Subscription, abonelik_id)
    if a is None or a.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Abonelik bulunamadı")
    return a


# --- Uçlar --------------------------------------------------------------------


@router.get("", response_model=list[AbonelikOut])
async def listele(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    musteri_id: int | None = None,
    arac_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AbonelikOut]:
    stmt = (
        select(Subscription)
        .where(Subscription.is_deleted.is_(False))
        .order_by(Subscription.id.desc())
        .limit(limit)
    )
    if durum:
        stmt = stmt.where(Subscription.status == durum)
    if musteri_id:
        stmt = stmt.where(Subscription.customer_id == musteri_id)
    if arac_id:
        stmt = stmt.where(Subscription.vehicle_id == arac_id)
    return [await _cikti(db, a, clock, detay=False) for a in (await db.scalars(stmt)).all()]


@router.get("/yenilenecekler")
async def yenilenecekler(
    db: DbDep, clock: ClockDep, user: Okuyucu, gun: int | None = None
) -> list[dict]:
    """Bitişine yaklaşan sözleşmeler — varsayılan eşik ayarlardan gelir."""
    esik = gun or int(await ayar_svc.get(db, "abonelik_yenileme_hatirlatma_gun"))
    return await svc.yenilenecekler(db, clock, gun=esik)


@router.get("/mrr")
async def mrr(db: DbDep, clock: ClockDep, user: Okuyucu, tarih: date | None = None) -> dict:
    gun = tarih or clock.now().date()
    return {"tarih": gun, "mrr": await svc.mrr(db, gun)}


@router.get("/mrr/{donem}")
async def mrr_hareketi(donem: str, db: DbDep, user: Okuyucu) -> dict:
    """Dönem içindeki MRR değişiminin olay tipine göre dökümü ve churn oranı."""
    try:
        svc.donem_araligi(donem)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dönem 'YYYY-AA' olmalı") from exc
    return await svc.mrr_hareketi(db, donem)


@router.get("/tahakkuk/{donem}")
async def tahakkuk(donem: str, db: DbDep, user: Okuyucu) -> dict:
    """Aylık abonelik tahakkuk listesi — kıst hesaplı."""
    try:
        svc.donem_araligi(donem)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dönem 'YYYY-AA' olmalı") from exc
    satirlar = await svc.donem_tahakkuku(db, donem)
    return {
        "donem": donem,
        "satir": len(satirlar),
        "toplam_matrah": sum((s["tutar"] for s in satirlar), Decimal("0")),
        "toplam_kdv": sum((s["kdv"] for s in satirlar), Decimal("0")),
        "toplam": sum((s["toplam"] for s in satirlar), Decimal("0")),
        "satirlar": satirlar,
    }


@router.get("/tahakkuk/{donem}/xlsx")
async def tahakkuk_xlsx(
    donem: str, db: DbDep, user: Annotated[User, Depends(require_permission("rapor.disaaktar"))]
) -> Response:
    """Aylık tahakkuk Excel'i — muhasebeye aktarılacak satırlar."""
    try:
        svc.donem_araligi(donem)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dönem 'YYYY-AA' olmalı") from exc
    satirlar = await svc.donem_tahakkuku(db, donem)
    basliklar = [
        "Abonelik No",
        "Cari Kodu",
        "Cari Ünvanı",
        "Açıklama",
        "Periyot",
        "Birim Fiyat",
        "Aylık Tutar",
        "Aktif Gün",
        "Dönem Gün",
        "Kıst",
        "Matrah",
        "KDV Oranı",
        "KDV",
        "Toplam",
        "Para Birimi",
    ]
    tablo = [
        [
            s["subscription_no"],
            f"M{s['customer_id']:05d}",
            s["customer_title"],
            s["title"] or "",
            s["billing_period"],
            s["birim_fiyat"],
            s["aylik_tutar"],
            s["aktif_gun"],
            s["donem_gun"],
            "Evet" if s["kist"] else "Hayır",
            s["tutar"],
            s["kdv_orani"],
            s["kdv"],
            s["toplam"],
            s["currency"],
        ]
        for s in satirlar
    ]
    icerik = await export_svc.satirlari_xlsx_async(basliklar, tablo, f"Tahakkuk {donem}")
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="tahakkuk-{donem}.xlsx"'},
    )


@router.get("/{abonelik_id}", response_model=AbonelikOut)
async def getir(abonelik_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> AbonelikOut:
    return await _cikti(db, await _getir(db, abonelik_id), clock)


@router.post("", response_model=AbonelikOut, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: AbonelikIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> AbonelikOut:
    """Abonelik açar. TASLAK olarak doğar; MRR'a aktifleşince girer."""
    try:
        payload.dogrula()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    kdv = payload.vat_rate
    if kdv is None:
        kdv = Decimal(str(await ayar_svc.get(db, "kdv_oran_varsayilan")))

    abonelik = Subscription(
        subscription_no=await svc.numara_uret(db, clock),
        customer_id=payload.customer_id,
        title=payload.title,
        vehicle_id=payload.vehicle_id,
        device_id=payload.device_id,
        sim_id=payload.sim_id,
        product_id=payload.product_id,
        order_id=payload.order_id,
        billing_period=payload.billing_period,
        currency=payload.currency,
        vat_rate=kdv,
        start_date=payload.start_date,
        end_date=payload.end_date,
        commitment_end_date=payload.commitment_end_date,
        renewal_type=payload.renewal_type,
        renewal_months=payload.renewal_months,
        notice_days=payload.notice_days,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(abonelik)
    await db.flush()
    await svc.fiyat_yaz(
        db,
        abonelik,
        unit_price=payload.unit_price,
        valid_from=payload.start_date,
        neden="Sözleşme açılışı",
        user_id=user.id,
    )

    await audit.log(
        db,
        "subscriptions",
        "olustur",
        entity_id=abonelik.id,
        new_value={"no": abonelik.subscription_no, "musteri": abonelik.customer_id},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, abonelik, clock)


@router.patch("/{abonelik_id}", response_model=AbonelikOut)
async def guncelle(
    abonelik_id: int,
    payload: AbonelikGuncelle,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> AbonelikOut:
    """Sözleşme başlığını günceller. Ücret buradan DEĞİŞMEZ — /fiyat ucu var.

    Ücreti burada değiştirmek tarihli geçmişi baypas ederdi.
    """
    a = await _getir(db, abonelik_id)
    if payload.renewal_type and payload.renewal_type not in YENILEME_TIPLERI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Yenileme tipi {YENILEME_TIPLERI} içinden olmalı"
        )
    # İSTEMCİNİN version DEĞERİ KAYDA ATANMAZ. Atandığında SQLAlchemy'nin
    # `WHERE version = :eski` koşulu her zaman tutuyor, iyimser kilitleme
    # tamamen devre dışı kalıyordu: bayat bir sürümle gelen istek 200 dönüp
    # aradaki değişikliği sessizce eziyor, sayaç geriye gidiyordu (ölçüldü:
    # 4 -> 1). Doğru davranış, uyuşmazlıkta 409 (plan §3.3/1).
    if payload.version != a.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. "
            "Sayfayı yenileyip değişikliğinizi tekrar uygulayın.",
        )
    for alan, deger in payload.model_dump(exclude={"version"}, exclude_unset=True).items():
        setattr(a, alan, deger)
    a.updated_by = user.id
    await audit.log_change(db, a, "guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    return await _cikti(db, a, clock)


class FiyatIn(BaseModel):
    unit_price: Decimal = Field(ge=0)
    valid_from: date
    neden: str | None = Field(default=None, max_length=200)


@router.post("/{abonelik_id}/fiyat", response_model=AbonelikOut)
async def fiyat_degistir(
    abonelik_id: int,
    payload: FiyatIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> AbonelikOut:
    """Yeni ücret dönemi açar ve MRR'ı buna göre günceller."""
    a = await _getir(db, abonelik_id)
    if a.commitment_end_date and a.commitment_end_date >= payload.valid_from:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Taahhüt {a.commitment_end_date:%d.%m.%Y} tarihine kadar sürüyor; "
            "bu tarihten önce ücret değiştirilemez.",
        )
    try:
        await svc.fiyat_yaz(
            db,
            a,
            unit_price=payload.unit_price,
            valid_from=payload.valid_from,
            neden=payload.neden,
            user_id=user.id,
        )
    except svc.AbonelikHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if a.status == "AKTIF":
        yeni = svc.aylik_tutar(payload.unit_price, a.billing_period)
        onceki = await svc.mrr_simdiki(db, a.id)
        await svc.olay_yaz(
            db,
            a,
            tip="ARTIS" if yeni >= onceki else "AZALIS",
            tarih=payload.valid_from,
            yeni_mrr=yeni,
            neden=payload.neden,
            user_id=user.id,
        )

    await audit.log(
        db,
        "subscriptions",
        "fiyat",
        entity_id=a.id,
        new_value={"fiyat": float(payload.unit_price), "baslangic": str(payload.valid_from)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, a, clock)


class DurumIn(BaseModel):
    durum: str
    tarih: date | None = None
    neden: str | None = Field(default=None, max_length=200)


@router.post("/{abonelik_id}/durum", response_model=AbonelikOut)
async def durum_degistir(
    abonelik_id: int,
    payload: DurumIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> AbonelikOut:
    """Durum geçişi + MRR olayı tek işlemde."""
    a = await _getir(db, abonelik_id)
    onceki = a.status
    try:
        await svc.durum_degistir(
            db,
            a,
            payload.durum,
            clock=clock,
            tarih=payload.tarih,
            neden=payload.neden,
            user_id=user.id,
        )
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except svc.AbonelikHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "subscriptions",
        "durum.degistir",
        entity_id=a.id,
        old_value={"status": onceki},
        new_value={"status": a.status, "neden": payload.neden},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, a, clock)


class YenileIn(BaseModel):
    ay: int | None = Field(default=None, ge=1, le=60)


@router.post("/{abonelik_id}/yenile", response_model=AbonelikOut)
async def yenile(
    abonelik_id: int,
    payload: YenileIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> AbonelikOut:
    a = await _getir(db, abonelik_id)
    eski_bitis = a.end_date
    try:
        await svc.yenile(db, a, clock=clock, ay=payload.ay, user_id=user.id)
    except svc.AbonelikHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "subscriptions",
        "yenile",
        entity_id=a.id,
        old_value={"end_date": str(eski_bitis) if eski_bitis else None},
        new_value={"end_date": str(a.end_date)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, a, clock)
