"""Hatlar (SIM) — kart, liste, cihaza takma, taahhüt izleme."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_permission,
    sayfala,
    sees_cost,
)
from app.integrations.registry import operator_adaptoru
from app.integrations.turk_telekom import AdaptorHazirDegil
from app.models import Device, SimCard, User
from app.models.sim import OPERATORLER
from app.schemas.devices import HatOzeti
from app.services import audit, normalize
from app.services import devices as cihaz_svc
from app.services import settings as ayar_svc
from app.services import sims as sim_svc
from app.services.statemachine import HAT, IzinsizGecis

router = APIRouter(prefix="/api/hatlar", tags=["hatlar"])

Okuyucu = Annotated[User, Depends(require_permission("hat.gor"))]
Yazici = Annotated[User, Depends(require_permission("hat.yaz"))]


class HatIn(BaseModel):
    iccid: str
    msisdn: str | None = None
    imsi: str | None = Field(default=None, max_length=20)
    operator: str = "TURK_TELEKOM"
    apn: str | None = None
    enabled_network_tech: list[str] | None = None
    plan_name: str | None = None
    data_allowance_mb: int | None = None
    tariff_cost: float | None = None
    package_cost: float | None = None
    apn_cost: float | None = None
    monthly_charge: float | None = None
    commitment_months: int | None = None
    commitment_end_date: date | None = None
    discount_rate: float | None = None

    @field_validator("iccid")
    @classmethod
    def _iccid(cls, v: str) -> str:
        return normalize.normalize_iccid(v)

    @field_validator("msisdn")
    @classmethod
    def _msisdn(cls, v: str | None) -> str | None:
        return normalize.normalize_msisdn(v) if v else None

    @field_validator("operator")
    @classmethod
    def _op(cls, v: str) -> str:
        if v not in OPERATORLER:
            raise ValueError(f"Operatör {OPERATORLER} içinden olmalı")
        return v


class HatDetay(HatOzeti):
    apn: str | None = None
    imsi: str | None = None
    tariff_cost: float | None = None
    package_cost: float | None = None
    apn_cost: float | None = None
    aylik_maliyet: float = 0
    monthly_charge: float | None = None
    discount_rate: float | None = None
    commitment_months: int | None = None
    taahhut_kalan_gun: int | None = None
    takili_cihaz_kimligi: str | None = None
    iccid_saglamasi: bool = True
    # ICCID kaynakta yoktu; göç MSISDN'den yer tutucu yazdı. "Sağlaması
    # tutmuyor" ile aynı şey DEĞİL — biri operatörden istenecek eksik bilgi,
    # diğeri şüpheli veri.
    iccid_eksik: bool = False
    sonraki_durumlar: list[str] = []
    version: int = 1


class HatTakIn(BaseModel):
    device_id: int


def _iccid_eksik(hat: SimCard) -> bool:
    return (hat.field_sources or {}).get("iccid") == "EKSIK"


# Yetkisiz kullanıcıdan gizlenen maliyet alanları (plan §3.4).
MALIYET_ALANLARI = ("tariff_cost", "package_cost", "apn_cost", "aylik_maliyet")


def _detay(hat: SimCard, bugun: date, *, maliyet: bool = True) -> HatDetay:
    d = HatDetay.model_validate(hat)
    d.aylik_maliyet = hat.aylik_maliyet
    d.sonraki_durumlar = sorted(HAT.sonraki(hat.status))
    d.iccid_eksik = _iccid_eksik(hat)
    # Bilinmeyen ICCID'de sağlama sorusu anlamsız: şüphe üretme.
    d.iccid_saglamasi = True if d.iccid_eksik else normalize.iccid_luhn_ok(hat.iccid)
    if hat.commitment_end_date:
        d.taahhut_kalan_gun = (hat.commitment_end_date - bugun).days
    if not maliyet:
        # Kârlılık raporu `maliyet.gor` istiyordu ama AYNI SAYILAR liste
        # ucundan herkese gidiyordu: depo, satış, teknik servis ve hat
        # sorumlusu hattın tarife/paket/APN maliyetini görüyordu.
        for alan in MALIYET_ALANLARI:
            setattr(d, alan, None)
    return d


@router.get("", response_model=list[HatDetay])
async def listele(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    q: str | None = None,
    durum: str | None = None,
    taahhudu_bitenler: bool = Query(
        default=False, description="Taahhüdü yaklaşan hatlar (ayarlardaki gün eşiği)"
    ),
    iccid_eksik: bool = Query(
        default=False, description="ICCID'si göçten kalan yer tutucu olan hatlar"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[HatDetay]:
    bugun = clock.now().date()
    stmt = select(SimCard).where(SimCard.is_deleted.is_(False)).order_by(SimCard.iccid)
    if q:
        rakam = "".join(ch for ch in q if ch.isdigit())
        kosullar = [SimCard.iccid.startswith(rakam)] if rakam else []
        kosullar.append(SimCard.msisdn.contains(rakam or q))
        kosullar.append(SimCard.plan_name.ilike(f"%{q}%"))
        stmt = stmt.where(or_(*kosullar))
    if durum:
        stmt = stmt.where(SimCard.status == durum)
    if iccid_eksik:
        # Göç ICCID'si olmayan hatta `field_sources.iccid = "EKSIK"` yazdı;
        # gerçek ICCID girilince bu işaret kalkar.
        stmt = stmt.where(SimCard.field_sources["iccid"].astext == "EKSIK")
    if taahhudu_bitenler:
        # İndirim taahhüde bağlı: taahhüt düşerse aynı hat kat kat pahalı olur.
        esik = int(await ayar_svc.get(db, "hat_taahhut_uyari_gun"))
        stmt = stmt.where(
            SimCard.commitment_end_date.is_not(None),
            SimCard.commitment_end_date <= bugun + timedelta(days=esik),
        )
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    goster = sees_cost(user)
    return [_detay(h, bugun, maliyet=goster) for (h,) in satirlar]


@router.post("", response_model=HatDetay, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: HatIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> HatDetay:
    if await db.scalar(select(SimCard).where(SimCard.iccid == payload.iccid)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu ICCID zaten kayıtlı")
    hat = SimCard(**payload.model_dump(), created_by=user.id)
    db.add(hat)
    await db.flush()
    await audit.log(
        db,
        "sim_cards",
        "olustur",
        entity_id=hat.id,
        new_value={"iccid": hat.iccid, "operator": hat.operator},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,  # MSISDN kişisel veri
    )
    await db.commit()
    return _detay(hat, clock.now().date(), maliyet=sees_cost(user))


@router.post("/{hat_id}/tak", response_model=HatDetay)
async def cihaza_tak(
    hat_id: int, payload: HatTakIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> HatDetay:
    """Hattı cihaza takar; her iki taraftaki açık dönemi kapatır."""
    hat = await db.get(SimCard, hat_id)
    cihaz = await db.get(Device, payload.device_id)
    if hat is None or cihaz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hat veya cihaz bulunamadı")

    await cihaz_svc.hat_tak(db, device_id=cihaz.id, sim_id=hat.id, clock=clock)
    await audit.log(
        db,
        "sim_device_history",
        "tak",
        entity_id=hat.id,
        new_value={"iccid": hat.iccid, "cihaz": cihaz.kimlik},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _detay(hat, clock.now().date(), maliyet=sees_cost(user))


@router.post("/{hat_id}/durum", response_model=HatDetay)
async def durum_degistir(
    hat_id: int,
    payload: dict,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> HatDetay:
    hat = await db.get(SimCard, hat_id)
    if hat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hat bulunamadı")
    hedef = payload.get("to_status", "")
    try:
        HAT.dogrula(hat.status, hedef)
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    onceki, hat.status = hat.status, hedef
    await audit.log(
        db,
        "sim_cards",
        "durum.degistir",
        entity_id=hat.id,
        old_value={"status": onceki},
        new_value={"status": hedef},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _detay(hat, clock.now().date(), maliyet=sees_cost(user))


# --- Paket geçmişi ve senkron ------------------------------------------------


class PaketIn(BaseModel):
    plan_name: str | None = None
    data_allowance_mb: int | None = None
    enabled_network_tech: list[str] | None = None
    monthly_cost: float | None = None


@router.post("/{hat_id}/paket", response_model=HatDetay)
async def paket_degistir(
    hat_id: int, payload: PaketIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> HatDetay:
    """Yeni paket dönemi açar; önceki dönem kapanır ve geçmişte kalır."""
    hat = await db.get(SimCard, hat_id)
    if hat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hat bulunamadı")
    await sim_svc.paket_degistir(
        db,
        hat,
        clock=clock,
        plan_name=payload.plan_name,
        data_allowance_mb=payload.data_allowance_mb,
        enabled_network_tech=payload.enabled_network_tech,
        monthly_cost=payload.monthly_cost,
    )
    # Elle girilen paket, gece senkronunda ezilmesin.
    kaynaklar = dict(hat.field_sources or {})
    for alan in ("plan_name", "data_allowance_mb", "enabled_network_tech"):
        kaynaklar[alan] = sim_svc.MANUEL
    hat.field_sources = kaynaklar

    await audit.log(
        db,
        "sim_cards",
        "paket.degistir",
        entity_id=hat.id,
        new_value={"plan": payload.plan_name, "mb": payload.data_allowance_mb},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _detay(hat, clock.now().date(), maliyet=sees_cost(user))


@router.get("/{hat_id}/paket-gecmisi")
async def paket_gecmisi(hat_id: int, db: DbDep, _: Okuyucu) -> list[dict]:
    from app.models import SimPlanHistory

    kayitlar = (
        await db.scalars(
            select(SimPlanHistory)
            .where(SimPlanHistory.sim_id == hat_id)
            .order_by(SimPlanHistory.valid_from.desc())
        )
    ).all()
    return [
        {
            "plan_name": k.plan_name,
            "data_allowance_mb": k.data_allowance_mb,
            "enabled_network_tech": k.enabled_network_tech,
            "monthly_cost": float(k.monthly_cost) if k.monthly_cost else None,
            "valid_from": k.valid_from,
            "valid_to": k.valid_to,
        }
        for k in kayitlar
    ]


@router.post("/senkron")
async def senkronize_et(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Annotated[User, Depends(require_permission("hat.senkron"))],
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Operatörden hat bilgilerini çeker. Elle girilen alanlar korunur."""
    adaptor = await operator_adaptoru(db)
    hatlar = (
        await db.scalars(select(SimCard).where(SimCard.is_deleted.is_(False)).limit(limit))
    ).all()
    try:
        durumlar = {d.iccid: d for d in await adaptor.toplu_durum([h.iccid for h in hatlar])}
    except AdaptorHazirDegil as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    guncellenen = 0
    for hat in hatlar:
        durum = durumlar.get(hat.iccid)
        if durum is None:
            continue
        if await sim_svc.senkron_uygula(db, hat, durum, clock):
            guncellenen += 1

    await audit.log(
        db,
        "sim_cards",
        "senkron",
        new_value={"adaptor": adaptor.ad, "sorgulanan": len(hatlar), "guncellenen": guncellenen},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {
        "adaptor": adaptor.ad,
        "sorgulanan": len(hatlar),
        "operatorden_donen": len(durumlar),
        "guncellenen": guncellenen,
    }


# --- Raporlar ----------------------------------------------------------------


def _maliyeti_gizle(satirlar: list[dict], alanlar: tuple[str, ...], user: User) -> list[dict]:
    if sees_cost(user):
        return satirlar
    return [{**s, **{a: None for a in alanlar if a in s}} for s in satirlar]


@router.get("/rapor/kota")
async def rapor_kota(db: DbDep, _: Okuyucu) -> list[dict]:
    return await sim_svc.kota_uyarilari(db)


@router.get("/rapor/2g-riski")
async def rapor_2g(db: DbDep, _: Okuyucu) -> list[dict]:
    """Yalnız 2G/3G destekleyen cihaz ve hatlar — hem risk hem satış fırsatı."""
    return await sim_svc.iki_g_riski(db)


@router.get("/rapor/atil")
async def rapor_atil(db: DbDep, clock: ClockDep, user: Okuyucu) -> list[dict]:
    satirlar = await sim_svc.atil_hatlar(db, clock)
    return _maliyeti_gizle(satirlar, ("aylik_maliyet",), user)


@router.get("/rapor/karlilik")
async def rapor_karlilik(
    db: DbDep,
    user: Annotated[User, Depends(require_permission("maliyet.gor"))],
) -> dict:
    """Maliyet içerdiği için ayrı izin ister."""
    sonuc = await sim_svc.hat_karliligi(db)
    sonuc["cihaza_takili_olmayan"] = await sim_svc.cihazsiz_hatlar(db)
    return sonuc


@router.get("/rapor/taahhut")
async def rapor_taahhut(db: DbDep, clock: ClockDep, user: Okuyucu) -> list[dict]:
    satirlar = await sim_svc.taahhudu_bitenler(db, clock)
    return _maliyeti_gizle(satirlar, ("indirimli_maliyet",), user)
