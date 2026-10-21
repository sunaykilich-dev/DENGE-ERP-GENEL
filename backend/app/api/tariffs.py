"""Montaj noktası tarifeleri — iş tipi başına hak ediş birim fiyatı.

Tarifeler bugüne kadar YALNIZ göç betiğiyle yazılabiliyordu; ekranı yoktu.
Oysa fiyat değişimi sık ve sıradan bir iş: yeni bir montaj noktasıyla
anlaşılıyor, bir noktanın fiyatı güncelleniyor. Betikle yapılabilen ama
ekranda yapılamayan her iş, pratikte yapılmıyor demektir.

**Tarife TARİHLİDİR ve GEÇMİŞE DOKUNULMAZ.** Fiyat değiştirmek, eski satırı
düzenlemek değil; yürürlükteki tarifeyi kapatıp yenisini açmaktır. Hak ediş
çözümlemesi işin TAMAMLANMA tarihine bakar (`tariffs.tarife_bul`), dolayısıyla
geçmiş aylar yeni fiyattan yeniden hesaplanmaz. Satırı düzenlemek bunu bozardı:
kapanmış bir dönem sessizce başka bir tutara kayardı.

**Genel tarife (`partner_id = NULL`) tabandır.** 35 montaj noktasının 30'u
aynı fiyatı kullanıyor; noktaya özel satır yalnız istisna için açılır ve
çözümlemede genelin üstünde tutulur.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import Account, PartnerTariff, User
from app.models.settlement import HAK_EDIS_IS_TIPLERI
from app.services import audit
from app.services.tariffs import HERHANGI

router = APIRouter(prefix="/api/tarifeler", tags=["tarife"])

Okuyucu = Annotated[User, Depends(require_permission("hakedis.gor"))]
Yazici = Annotated[User, Depends(require_permission("hakedis.yaz"))]


class TarifeOut(BaseModel):
    id: int
    partner_id: int | None
    partner_title: str | None = None
    work_type: str
    product_group: str
    unit_price: float
    valid_from: datetime
    valid_to: datetime | None
    notes: str | None
    genel: bool = False

    model_config = {"from_attributes": True}


class TarifeIn(BaseModel):
    partner_id: int | None = None
    work_type: str
    product_group: str = HERHANGI
    unit_price: float = Field(ge=0)
    # Yürürlük tarihi verilmezse bugün. Geçmiş tarih SERBEST: sözleşme geriye
    # dönük imzalanmış olabilir ve hak ediş çözümlemesi buna bakar.
    valid_from: datetime | None = None
    notes: str | None = Field(default=None, max_length=300)


def _cikti(t: PartnerTariff, unvan: str | None) -> TarifeOut:
    out = TarifeOut.model_validate(t)
    out.partner_title = unvan
    out.genel = t.partner_id is None
    return out


@router.get("/is-tipleri")
async def is_tipleri(_: Okuyucu) -> list[str]:
    """Hak edişe giren iş tipleri — ekran bunları kod içine gömmesin."""
    return list(HAK_EDIS_IS_TIPLERI)


@router.get("", response_model=list[TarifeOut])
async def listele(
    db: DbDep,
    _: Okuyucu,
    montaj_noktasi_id: int | None = None,
    yururlukte: bool = Query(default=False, description="Yalnız açık tarifeler"),
) -> list[TarifeOut]:
    """Tarifeler. `montaj_noktasi_id` verilirse o noktanınkiler + GENEL taban.

    Genel tarife de döner: ekranda "bu noktada özel fiyat yok, genelden
    350,00 ₺ uygulanıyor" demek, boş bir liste göstermekten yararlıdır.
    """
    stmt = (
        select(PartnerTariff, Account.title)
        .join(Account, Account.id == PartnerTariff.partner_id, isouter=True)
        .order_by(
            PartnerTariff.partner_id.nulls_first(),
            PartnerTariff.work_type,
            PartnerTariff.valid_from.desc(),
        )
    )
    if montaj_noktasi_id is not None:
        stmt = stmt.where(
            or_(
                PartnerTariff.partner_id == montaj_noktasi_id,
                PartnerTariff.partner_id.is_(None),
            )
        )
    if yururlukte:
        stmt = stmt.where(PartnerTariff.valid_to.is_(None))
    return [_cikti(t, unvan) for t, unvan in (await db.execute(stmt)).all()]


@router.post("", response_model=TarifeOut, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: TarifeIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TarifeOut:
    """Yeni tarife açar; aynı kapsamdaki YÜRÜRLÜKTEKİ tarifeyi kapatır.

    Kapatma zorunlu: `ex_tarife_cakisma` iki açık dönemi zaten reddederdi ama
    kullanıcıya çıplak bir veritabanı hatası göstermek yerine doğru işlemi
    yapmak gerekir. Eski satır SİLİNMEZ — geçmiş işler ondan hesaplandı.
    """
    if payload.work_type not in HAK_EDIS_IS_TIPLERI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"İş tipi {HAK_EDIS_IS_TIPLERI} içinden olmalı"
        )
    if payload.partner_id is not None:
        nokta = await db.get(Account, payload.partner_id)
        if nokta is None or nokta.is_deleted or not nokta.is_montaj_noktasi:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Montaj noktası bulunamadı")

    baslangic = payload.valid_from or clock.now()
    if baslangic.tzinfo is None:
        baslangic = baslangic.replace(tzinfo=UTC)

    acik = (
        await db.scalars(
            select(PartnerTariff).where(
                PartnerTariff.partner_id.is_(None)
                if payload.partner_id is None
                else PartnerTariff.partner_id == payload.partner_id,
                PartnerTariff.work_type == payload.work_type,
                PartnerTariff.product_group == payload.product_group,
                PartnerTariff.valid_to.is_(None),
            )
        )
    ).all()
    for eski in acik:
        if eski.valid_from >= baslangic:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Yürürlükteki tarife {eski.valid_from:%d.%m.%Y} tarihinde başlıyor; "
                "yeni tarife bu tarihten SONRA yürürlüğe girmeli.",
            )
        eski.valid_to = baslangic

    tarife = PartnerTariff(
        partner_id=payload.partner_id,
        work_type=payload.work_type,
        product_group=payload.product_group,
        unit_price=payload.unit_price,
        valid_from=baslangic,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(tarife)
    await db.flush()
    await audit.log(
        db,
        "partner_tariffs",
        "olustur",
        entity_id=tarife.id,
        new_value={
            "nokta": payload.partner_id,
            "is_tipi": payload.work_type,
            "fiyat": payload.unit_price,
            "yururluk": str(baslangic.date()),
            "kapatilan": [e.id for e in acik],
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    unvan = None
    if tarife.partner_id:
        nokta = await db.get(Account, tarife.partner_id)
        unvan = nokta.title if nokta else None
    return _cikti(tarife, unvan)


@router.post("/{tarife_id}/kapat", response_model=TarifeOut)
async def kapat(
    tarife_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TarifeOut:
    """Tarifeyi yürürlükten kaldırır (silmez).

    Noktaya özel bir tarife kapatılınca o nokta GENEL tarifeye düşer —
    fiyatsız kalmaz.
    """
    tarife = await db.get(PartnerTariff, tarife_id)
    if tarife is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tarife bulunamadı")
    if tarife.valid_to is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu tarife zaten kapalı")

    simdi = clock.now()
    if tarife.valid_from >= simdi:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Tarife bugünden sonra başlıyor; kapatmak yerine yenisini açın.",
        )
    tarife.valid_to = simdi
    tarife.updated_by = user.id
    await audit.log(
        db,
        "partner_tariffs",
        "kapat",
        entity_id=tarife.id,
        old_value={"fiyat": float(tarife.unit_price)},
        new_value={"bitis": str(simdi.date())},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    unvan = None
    if tarife.partner_id:
        nokta = await db.get(Account, tarife.partner_id)
        unvan = nokta.title if nokta else None
    return _cikti(tarife, unvan)
