"""Toplu fiyat güncelleme: önizle → onayla → bildir."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import Account, PriceBatch, Subscription, User
from app.models.pricing import ZAM_YONTEMLERI
from app.services import audit, mail
from app.services import pricing as svc

router = APIRouter(prefix="/api/toplu-zam", tags=["abonelik"])

Okuyucu = Annotated[User, Depends(require_permission("abonelik.gor"))]
Yazici = Annotated[User, Depends(require_permission("abonelik.yaz"))]


class Kriterler(BaseModel):
    customer_ids: list[int] = Field(default_factory=list)
    product_ids: list[int] = Field(default_factory=list)
    billing_periods: list[str] = Field(default_factory=list)
    subscription_ids: list[int] = Field(default_factory=list)
    # Bu tarihten önce başlamış sözleşmeler — "eski müşterilere zam".
    baslangic_once: date | None = None


class ZamIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    method: str = "YUZDE"
    value: Decimal
    valid_from: date
    round_to: Decimal = Decimal("1")
    criteria: Kriterler = Field(default_factory=Kriterler)
    notes: str | None = None

    def dogrula(self) -> None:
        if self.method not in ZAM_YONTEMLERI:
            raise ValueError(f"Zam yöntemi {ZAM_YONTEMLERI} içinden olmalı")


class PartiOut(BaseModel):
    id: int
    title: str
    status: str
    method: str
    value: Decimal
    valid_from: date
    round_to: Decimal
    criteria: dict
    affected_count: int
    excluded_count: int
    mrr_delta: Decimal
    applied_at: object = None
    reverted_at: object = None
    notified_at: object = None
    notified_count: int
    notes: str | None
    version: int

    model_config = {"from_attributes": True}


def _kriter_sozlugu(k: Kriterler) -> dict:
    veri = k.model_dump(exclude_none=True)
    if veri.get("baslangic_once"):
        veri["baslangic_once"] = veri["baslangic_once"].isoformat()
    return {anahtar: deger for anahtar, deger in veri.items() if deger}


@router.get("", response_model=list[PartiOut])
async def listele(
    db: DbDep, user: Okuyucu, limit: int = Query(default=50, ge=1, le=200)
) -> list[PartiOut]:
    return [
        PartiOut.model_validate(p)
        for p in (
            await db.scalars(select(PriceBatch).order_by(PriceBatch.id.desc()).limit(limit))
        ).all()
    ]


@router.post("/onizle")
async def onizle(payload: ZamIn, db: DbDep, user: Yazici) -> dict:
    """Hiçbir şey yazmadan zammın kime ne yapacağını gösterir."""
    try:
        payload.dogrula()
        return await svc.onizle(
            db,
            kriterler=_kriter_sozlugu(payload.criteria),
            yontem=payload.method,
            deger=payload.value,
            valid_from=payload.valid_from,
            yuvarlama=payload.round_to,
        )
    except (ValueError, svc.ZamHatasi) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("", response_model=PartiOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: ZamIn, request: Request, db: DbDep, user: Yazici) -> PartiOut:
    """Zam partisini TASLAK olarak kaydeder; henüz hiçbir ücret değişmez."""
    try:
        payload.dogrula()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    parti = PriceBatch(
        title=payload.title,
        method=payload.method,
        value=payload.value,
        valid_from=payload.valid_from,
        round_to=payload.round_to,
        criteria=_kriter_sozlugu(payload.criteria),
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(parti)
    await db.flush()
    await audit.log(
        db,
        "price_batches",
        "olustur",
        entity_id=parti.id,
        new_value={"baslik": parti.title, "yontem": parti.method, "deger": float(parti.value)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return PartiOut.model_validate(parti)


@router.get("/{parti_id}")
async def getir(parti_id: int, db: DbDep, user: Okuyucu) -> dict:
    """Partiyi ve kendi kriterlerine göre güncel önizlemesini döner."""
    parti = await db.get(PriceBatch, parti_id)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zam partisi bulunamadı")
    cikti = {"parti": PartiOut.model_validate(parti)}
    if parti.status == "TASLAK":
        cikti["onizleme"] = await svc.onizle(
            db,
            kriterler=parti.criteria or {},
            yontem=parti.method,
            deger=Decimal(str(parti.value)),
            valid_from=parti.valid_from,
            yuvarlama=Decimal(str(parti.round_to)),
        )
    return cikti


@router.post("/{parti_id}/uygula")
async def uygula(parti_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici) -> dict:
    """Partiyi uygular: ücret dönemleri açılır, MRR olayları yazılır."""
    parti = await db.get(PriceBatch, parti_id)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zam partisi bulunamadı")
    try:
        sonuc = await svc.uygula(db, parti, clock=clock, user_id=user.id)
    except svc.ZamHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "price_batches",
        "uygula",
        entity_id=parti.id,
        new_value={
            "etkilenen": parti.affected_count,
            "haric": parti.excluded_count,
            "mrr_delta": float(parti.mrr_delta),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {"parti": PartiOut.model_validate(parti), "sonuc": sonuc}


@router.post("/{parti_id}/geri-al", response_model=PartiOut)
async def geri_al(
    parti_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> PartiOut:
    """Yürürlüğe girmemiş partiyi bütünüyle geri alır."""
    parti = await db.get(PriceBatch, parti_id)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zam partisi bulunamadı")
    try:
        adet = await svc.geri_al(db, parti, clock=clock, user_id=user.id)
    except svc.ZamHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "price_batches",
        "geri.al",
        entity_id=parti.id,
        new_value={"geri_alinan": adet},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return PartiOut.model_validate(parti)


@router.post("/{parti_id}/bildir")
async def bildir(parti_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici) -> dict:
    """Zamdan etkilenen müşterilere bilgilendirme e-postası gönderir.

    Uygulanmamış parti bildirilmez — müşteriye henüz kesinleşmemiş bir zammı
    duyurmak, geri alındığında güveni bozar.
    """
    parti = await db.get(PriceBatch, parti_id)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zam partisi bulunamadı")
    if parti.status != "UYGULANDI":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Yalnız uygulanmış parti müşterilere bildirilebilir."
        )

    from app.models import SubscriptionPrice

    satirlar = (
        await db.execute(
            select(SubscriptionPrice, Subscription, Account)
            .join(Subscription, Subscription.id == SubscriptionPrice.subscription_id)
            .join(Account, Account.id == Subscription.customer_id)
            .where(SubscriptionPrice.price_batch_id == parti.id)
        )
    ).all()

    # Müşteri başına TEK e-posta: aynı zam 40 aboneliğe uygulandıysa
    # müşteriye 40 mesaj gitmesi kabul edilemez.
    gruplar: dict[int, dict] = {}
    for fiyat, abonelik, hesap in satirlar:
        g = gruplar.setdefault(hesap.id, {"hesap": hesap, "satir": []})
        g["satir"].append((abonelik, fiyat))

    gonderilen, atlanan = 0, []
    for hesap_id, g in gruplar.items():
        hesap = g["hesap"]
        if not hesap.email:
            atlanan.append({"account_id": hesap_id, "title": hesap.title, "neden": "E-posta yok"})
            continue
        dokum = "\n".join(
            f"  · {a.subscription_no} — {a.title or 'Abonelik'}: "
            f"{f.unit_price} {a.currency} ({a.billing_period.replace('_', ' ').lower()})"
            for a, f in sorted(g["satir"], key=lambda x: x[0].subscription_no)
        )
        try:
            await mail.gonder(
                db,
                alici=hesap.email,
                konu=f"Abonelik ücret güncellemesi — {parti.valid_from:%d.%m.%Y}",
                govde=(
                    f"Sayın {hesap.title},\n\n"
                    f"{parti.valid_from:%d.%m.%Y} tarihinden geçerli olmak üzere "
                    "abonelik ücretleriniz aşağıdaki gibi güncellenmiştir:\n\n"
                    f"{dokum}\n\n"
                    "Bilginize sunarız.\nDenge Mobilite"
                ),
            )
            gonderilen += 1
        except mail.MailKapali:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "E-posta ayarları yapılmadan bildirim gönderilemez (Parametreler → SMTP).",
            ) from None

    parti.notified_at = clock.now()
    parti.notified_count = gonderilen
    await audit.log(
        db,
        "price_batches",
        "bildir",
        entity_id=parti.id,
        new_value={"gonderilen": gonderilen, "atlanan": len(atlanan)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {"gonderilen": gonderilen, "atlanan": atlanan}
