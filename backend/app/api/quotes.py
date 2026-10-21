"""Teklif yönetimi: versiyonlama, iskonto onayı, gönderim, online kabul."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.config import get_config
from app.models import Account, Quote, QuoteLine, QuoteVersion, User
from app.services import audit, belgeler, mail
from app.services import quotes as svc
from app.services.pdf import PdfUretilemedi

router = APIRouter(prefix="/api/teklifler", tags=["teklif"])

Okuyucu = Annotated[User, Depends(require_permission("teklif.gor"))]
Yazici = Annotated[User, Depends(require_permission("teklif.yaz"))]
Onaylayici = Annotated[User, Depends(require_permission("teklif.iskonto_onayla"))]


class KalemIn(BaseModel):
    item_type: str = "URUN"
    product_id: int | None = None
    description: str | None = Field(default=None, max_length=300)
    # Adet ve fiyat sınırsızdı: `unit_price: -999` geçiyor ve teklifin genel
    # toplamı EKSİYE düşüyordu; negatif adet ise DB kısıtına takılıp 500
    # veriyordu. İskonto zaten 0-100 ile sınırlı — eksik olan buydu.
    qty: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    # KDV oranı KESİR olarak saklanır (0.20 = %20); iskonto YÜZDEDİR (5 = %5).
    # İkisi farklı ölçekte olduğu için sınır konmazsa "vat_rate: 20" gönderen
    # bir istemci Numeric(5,4) taşmasıyla 500 alırdı.
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=1)


class TeklifIn(BaseModel):
    customer_id: int
    title: str | None = Field(default=None, max_length=200)
    currency: str = "TRY"
    fx_rate: Decimal | None = None
    fx_date: date | None = None
    valid_until: date | None = None
    kalemler: list[KalemIn] = Field(default_factory=list)


class KalemOut(BaseModel):
    id: int
    item_type: str
    product_id: int | None
    description: str
    qty: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    vat_rate: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class VersiyonOut(BaseModel):
    id: int
    version_no: int
    currency: str
    fx_rate: Decimal | None
    fx_date: date | None
    fx_source: str | None
    valid_until: date | None
    subtotal: Decimal
    discount_total: Decimal
    vat_total: Decimal
    grand_total: Decimal
    max_discount_pct: Decimal
    discount_approved_at: datetime | None
    sent_at: datetime | None
    viewed_at: datetime | None
    accepted_at: datetime | None
    rejected_at: datetime | None
    reject_reason: str | None
    decision_channel: str | None
    is_locked: bool
    public_url: str | None = None
    kalemler: list[KalemOut] = []

    model_config = {"from_attributes": True}


class TeklifOut(BaseModel):
    id: int
    quote_no: str
    customer_id: int
    customer_title: str | None = None
    owner_id: int | None
    status: str
    title: str | None
    lost_reason: str | None
    version: int
    onay_gerekiyor: bool = False
    guncel: VersiyonOut | None = None
    versiyon_sayisi: int = 0

    model_config = {"from_attributes": True}


async def _cikti(db: DbDep, t: Quote, *, detay: bool = True) -> TeklifOut:
    out = TeklifOut.model_validate(t)
    h = await db.get(Account, t.customer_id)
    out.customer_title = h.title if h else None
    # İlişkiye erişim asenkron bağlamda tembel yükleme tetikler (MissingGreenlet);
    # sayım açık sorguyla alınır.
    out.versiyon_sayisi = (
        await db.scalar(
            select(func.count()).select_from(QuoteVersion).where(QuoteVersion.quote_id == t.id)
        )
        or 0
    )
    if detay and t.current_version_id:
        # db.get kimlik haritasındaki nesneyi döndürdüğünde yükleyici seçenekleri
        # uygulanmaz; kalemler bu yüzden açık sorguyla çekilir.
        v = await db.get(QuoteVersion, t.current_version_id)
        if v is not None:
            vout = VersiyonOut.model_validate(v)
            satirlar = (
                await db.scalars(
                    select(QuoteLine)
                    .where(QuoteLine.version_id == v.id)
                    .order_by(QuoteLine.sort_order, QuoteLine.id)
                )
            ).all()
            vout.kalemler = [KalemOut.model_validate(k) for k in satirlar]
            if v.public_token:
                vout.public_url = svc.public_url(get_config().public_base_url, v.public_token)
            out.guncel = vout
            out.onay_gerekiyor = (
                await svc.onay_gerekiyor_mu(db, v) and v.discount_approved_at is None
            )
    return out


async def _guncel_versiyon(db: DbDep, t: Quote) -> QuoteVersion:
    v = await db.get(QuoteVersion, t.current_version_id) if t.current_version_id else None
    if v is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Teklifin güncel versiyonu yok")
    return v


@router.get("/belge-basligi")
async def belge_basligi(db: DbDep, _: Okuyucu) -> dict:
    """Teklif formundaki CANLI A4 önizlemesinin başlık bilgileri.

    Önizleme ile basılan PDF aynı kaynaktan beslenir; ayrı yerlerden
    okunsaydı ekranda görünen teklifle müşteriye giden teklif ayrışırdı.
    """
    from app.services import belgeler

    ayarlar = await belgeler.ayar_haritasi(db)
    return {
        "firma": belgeler.firma_bilgisi(ayarlar),
        "sartlar": ayarlar.get("teklif_ticari_sartlar") or belgeler.VARSAYILAN_SARTLAR,
        "kdv_varsayilan": float(ayarlar.get("kdv_oran_varsayilan") or 0.20),
    }


@router.get("", response_model=list[TeklifOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    durum: str | None = None,
    musteri_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TeklifOut]:
    stmt = select(Quote).where(Quote.is_deleted.is_(False)).order_by(Quote.id.desc()).limit(limit)
    # Satış temsilcisi yalnız kendi tekliflerini görür.
    if user.role.scope == "KENDI_MUSTERILERI":
        stmt = stmt.where(Quote.owner_id == user.id)
    if durum:
        stmt = stmt.where(Quote.status == durum)
    if musteri_id:
        stmt = stmt.where(Quote.customer_id == musteri_id)
    return [await _cikti(db, t) for t in (await db.scalars(stmt)).all()]


@router.get("/{teklif_id}", response_model=TeklifOut)
async def getir(teklif_id: int, db: DbDep, user: Okuyucu) -> TeklifOut:
    t = await db.get(Quote, teklif_id)
    if t is None or t.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    if user.role.scope == "KENDI_MUSTERILERI" and t.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    return await _cikti(db, t)


@router.post("", response_model=TeklifOut, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: TeklifIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    sira = (await db.scalar(select(Quote.id).order_by(Quote.id.desc()).limit(1)) or 0) + 1
    teklif = Quote(
        quote_no=f"TKF{clock.now():%Y}-{sira:05d}",
        customer_id=payload.customer_id,
        owner_id=user.id,
        title=payload.title,
        created_by=user.id,
    )
    db.add(teklif)
    await db.flush()

    versiyon = await svc.yeni_versiyon(db, teklif, clock=clock)
    versiyon.currency = payload.currency
    versiyon.fx_rate = payload.fx_rate
    versiyon.fx_date = payload.fx_date
    versiyon.fx_source = "MANUEL" if payload.fx_rate else None
    if payload.valid_until:
        versiyon.valid_until = payload.valid_until

    await _kalemleri_yaz(db, versiyon, payload.kalemler)
    await svc.versiyon_hesapla(db, versiyon)

    await audit.log(
        db,
        "quotes",
        "olustur",
        entity_id=teklif.id,
        new_value={"no": teklif.quote_no, "musteri": payload.customer_id},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, teklif)


async def _kalemleri_yaz(db: DbDep, versiyon: QuoteVersion, kalemler: list[KalemIn]) -> None:
    for sira, k in enumerate(kalemler):
        try:
            veri = await svc.kalem_alanlari(db, **k.model_dump())
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        db.add(QuoteLine(version_id=versiyon.id, sort_order=sira, **veri))
    await db.flush()


class RevizyonIn(BaseModel):
    kalemler: list[KalemIn]
    valid_until: date | None = None
    notes: str | None = None


@router.post("/{teklif_id}/revize", response_model=TeklifOut)
async def revize_et(
    teklif_id: int, payload: RevizyonIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    """Yeni versiyon açar. Eski versiyon KİLİTLENİR ve görüntülenebilir kalır."""
    t = await db.get(Quote, teklif_id)
    if t is None or t.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    if t.status in ("KABUL", "SIPARISE_DONUSTU"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Kabul edilmiş teklif revize edilemez; yeni teklif açın.",
        )
    onceki = await _guncel_versiyon(db, t)
    yeni = await svc.yeni_versiyon(db, t, clock=clock, kaynak=onceki)

    # Kaynak versiyondan kopyalanan kalemler silinir, yenileri yazılır.
    for k in (await db.scalars(select(QuoteLine).where(QuoteLine.version_id == yeni.id))).all():
        await db.delete(k)
    await db.flush()
    await _kalemleri_yaz(db, yeni, payload.kalemler)
    if payload.valid_until:
        yeni.valid_until = payload.valid_until
    yeni.notes = payload.notes
    await svc.versiyon_hesapla(db, yeni)

    t.status = "REVIZE_EDILDI"
    await audit.log(
        db,
        "quotes",
        "revize",
        entity_id=t.id,
        old_value={"versiyon": onceki.version_no, "tutar": str(onceki.grand_total)},
        new_value={"versiyon": yeni.version_no, "tutar": str(yeni.grand_total)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, t)


@router.post("/{teklif_id}/iskonto-onayla", response_model=TeklifOut)
async def iskonto_onayla(
    teklif_id: int, request: Request, db: DbDep, clock: ClockDep, user: Onaylayici
) -> TeklifOut:
    t = await db.get(Quote, teklif_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    v = await _guncel_versiyon(db, t)
    if not await svc.onay_gerekiyor_mu(db, v):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu teklifte onay gerektiren iskonto yok")
    v.discount_approved_by = user.id
    v.discount_approved_at = clock.now()
    if t.status == "ONAY_BEKLIYOR":
        t.status = "TASLAK"
    await audit.log(
        db,
        "quotes",
        "iskonto.onayla",
        entity_id=t.id,
        new_value={"iskonto_yuzde": str(v.max_discount_pct)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, t)


@router.get("/{teklif_id}/pdf")
async def teklif_pdf(teklif_id: int, db: DbDep, _: Okuyucu) -> Response:
    t = await db.get(Quote, teklif_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    v = await _guncel_versiyon(db, t)
    try:
        icerik = await belgeler.teklif_pdf(db, t, v)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{t.quote_no}.pdf"'},
    )


class GonderIn(BaseModel):
    alici: str | None = None
    mesaj: str | None = None


@router.post("/{teklif_id}/gonder", response_model=TeklifOut)
async def gonder(
    teklif_id: int, payload: GonderIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    """Teklifi PDF ekiyle e-postalar ve versiyonu kilitler."""
    t = await db.get(Quote, teklif_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    v = await _guncel_versiyon(db, t)

    if await svc.onay_gerekiyor_mu(db, v) and v.discount_approved_at is None:
        t.status = "ONAY_BEKLIYOR"
        await db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"%{v.max_discount_pct} iskonto onay eşiğini aşıyor; "
            "satış müdürü onayı olmadan gönderilemez.",
        )

    musteri = await db.get(Account, t.customer_id)
    alici = payload.alici or (musteri.email if musteri else None)
    if not alici:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Müşterinin e-posta adresi kayıtlı değil. Hesap kartından ekleyin "
            "veya gönderim ekranında adres girin.",
        )
    try:
        pdf = await belgeler.teklif_pdf(db, t, v)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    link = svc.public_url(get_config().public_base_url, v.public_token or "")
    try:
        await mail.gonder(
            db,
            alici=alici,
            konu=f"Fiyat Teklifi · {t.quote_no}",
            govde=(
                f"Sayın {musteri.title if musteri else ''},\n\n"
                f"{t.quote_no} numaralı teklifimiz ektedir.\n"
                f"Geçerlilik: {v.valid_until:%d.%m.%Y}\n"
                f"Genel toplam: {v.grand_total} {v.currency}\n\n"
                f"Teklifi görüntülemek ve yanıtlamak için: {link}\n\n"
                "Denge Mobilite"
            ),
            ekler=[(f"{t.quote_no}.pdf", pdf, "application/pdf")],
        )
    except mail.MailKapali as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    v.sent_at = clock.now()
    v.is_locked = True
    t.status = "GONDERILDI"
    await audit.log(
        db,
        "quotes",
        "gonder",
        entity_id=t.id,
        new_value={"alici": alici, "versiyon": v.version_no},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return await _cikti(db, t)


class KararIn(BaseModel):
    kabul: bool
    red_nedeni: str | None = Field(default=None, max_length=300)


@router.post("/{teklif_id}/karar", response_model=TeklifOut)
async def karar(
    teklif_id: int, payload: KararIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    """Kabul/red kaydını ELLE işaretler.

    Online kabul dışa açık sunucu gerektirdiği için yerel kurulumda kullanılan
    yol budur; kararın linkten mi ekipten mi geldiği ayrıca kaydedilir.
    """
    t = await db.get(Quote, teklif_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    if not payload.kabul and not payload.red_nedeni:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Red nedeni zorunludur")
    v = await _guncel_versiyon(db, t)
    await svc.karar_ver(
        db,
        v,
        kabul=payload.kabul,
        clock=clock,
        kanal="ELLE",
        red_nedeni=payload.red_nedeni,
    )
    await audit.log(
        db,
        "quotes",
        "karar",
        entity_id=t.id,
        new_value={"kabul": payload.kabul, "kanal": "ELLE", "neden": payload.red_nedeni},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, t)
