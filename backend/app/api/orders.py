"""Sipariş: tekliften dönüşüm, IMEI rezervasyonu, sevkiyat."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import (
    Account,
    Device,
    Order,
    OrderLine,
    OrderReservation,
    Product,
    Quote,
    QuoteVersion,
    Transfer,
    User,
)
from app.services import audit
from app.services import orders as svc
from app.services.quotes import kalem_alanlari
from app.services.statemachine import SIPARIS, IzinsizGecis

router = APIRouter(prefix="/api/siparisler", tags=["siparis"])

Okuyucu = Annotated[User, Depends(require_permission("siparis.gor"))]
Yazici = Annotated[User, Depends(require_permission("siparis.yaz"))]


# --- Şemalar ------------------------------------------------------------------


class KalemIn(BaseModel):
    item_type: str = "URUN"
    product_id: int | None = None
    description: str | None = Field(default=None, max_length=300)
    qty: Decimal = Decimal("1")
    unit_price: Decimal | None = None
    # KDV oranı KESİR olarak saklanır (0.20 = %20); iskonto YÜZDEDİR (5 = %5).
    # İkisi farklı ölçekte olduğu için sınır konmazsa "vat_rate: 20" gönderen
    # bir istemci Numeric(5,4) taşmasıyla 500 alırdı.
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=1)


class SiparisIn(BaseModel):
    customer_id: int
    order_date: date | None = None
    requested_date: date | None = None
    currency: str = "TRY"
    fx_rate: Decimal | None = None
    fx_date: date | None = None
    notes: str | None = None
    kalemler: list[KalemIn] = Field(default_factory=list)


class SiparisGuncelle(BaseModel):
    requested_date: date | None = None
    notes: str | None = None
    version: int


class RezervasyonOut(BaseModel):
    id: int
    order_line_id: int
    device_id: int
    kimlik: str | None = None
    reserved_at: datetime
    shipped_at: datetime | None = None
    transfer_id: int | None = None


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
    qty_shipped: Decimal
    rezerve_adet: int = 0
    # Kimlik taşımayan ürünlerde (kablo, montaj hizmeti) rezervasyon anlamsız.
    kimlik_gerekir: bool = True

    model_config = {"from_attributes": True}


class SiparisOut(BaseModel):
    id: int
    order_no: str
    customer_id: int
    customer_title: str | None = None
    quote_id: int | None
    owner_id: int | None
    status: str
    order_date: date
    requested_date: date | None
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    vat_total: Decimal
    grand_total: Decimal
    notes: str | None
    version: int
    sonraki_durumlar: list[str] = []
    kalemler: list[KalemOut] = []
    rezervasyonlar: list[RezervasyonOut] = []

    model_config = {"from_attributes": True}


class UygunCihazOut(BaseModel):
    id: int
    imei: str | None
    serial_no: str | None
    product_id: int | None
    status: str


# --- Yardımcılar --------------------------------------------------------------


async def _kalem_ciktisi(db: DbDep, kalem: OrderLine, rezerve: int) -> KalemOut:
    out = KalemOut.model_validate(kalem)
    out.rezerve_adet = rezerve
    if kalem.product_id:
        urun = await db.get(Product, kalem.product_id)
        out.kimlik_gerekir = bool(urun and urun.identity_kind != "YOK")
    else:
        out.kimlik_gerekir = False
    return out


async def _cikti(db: DbDep, s: Order, *, detay: bool = True) -> SiparisOut:
    out = SiparisOut.model_validate(s)
    h = await db.get(Account, s.customer_id)
    out.customer_title = h.title if h else None
    out.sonraki_durumlar = sorted(SIPARIS.sonraki(s.status))
    if not detay:
        return out

    # Asenkron bağlamda ilişkiye erişmek tembel yükleme tetikler; açık sorgu.
    kalemler = (
        await db.scalars(
            select(OrderLine)
            .where(OrderLine.order_id == s.id)
            .order_by(OrderLine.sort_order, OrderLine.id)
        )
    ).all()
    rezervasyonlar = (
        await db.scalars(
            select(OrderReservation)
            .where(OrderReservation.order_id == s.id)
            .order_by(OrderReservation.id)
        )
    ).all()

    acik_sayac: dict[int, int] = {}
    for r in rezervasyonlar:
        if r.released_at is None:
            acik_sayac[r.order_line_id] = acik_sayac.get(r.order_line_id, 0) + 1

    out.kalemler = [await _kalem_ciktisi(db, k, acik_sayac.get(k.id, 0)) for k in kalemler]

    kimlikler = {
        c.id: (c.imei or c.serial_no)
        for c in (
            await db.scalars(
                select(Device).where(Device.id.in_([r.device_id for r in rezervasyonlar] or [0]))
            )
        ).all()
    }
    out.rezervasyonlar = [
        RezervasyonOut(
            id=r.id,
            order_line_id=r.order_line_id,
            device_id=r.device_id,
            kimlik=kimlikler.get(r.device_id),
            reserved_at=r.reserved_at,
            shipped_at=r.shipped_at,
            transfer_id=r.transfer_id,
        )
        for r in rezervasyonlar
        if r.released_at is None or r.shipped_at is not None
    ]
    return out


async def _getir(db: DbDep, siparis_id: int, user: User) -> Order:
    s = await db.get(Order, siparis_id)
    if s is None or s.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sipariş bulunamadı")
    if user.role.scope == "KENDI_MUSTERILERI" and s.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sipariş bulunamadı")
    return s


async def _kalemleri_yaz(db: DbDep, siparis: Order, kalemler: list[KalemIn]) -> None:
    for sira, k in enumerate(kalemler):
        try:
            veri = await kalem_alanlari(db, **k.model_dump())
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        db.add(OrderLine(order_id=siparis.id, sort_order=sira, **veri))
    await db.flush()


# --- Uçlar --------------------------------------------------------------------


@router.get("", response_model=list[SiparisOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    durum: str | None = None,
    musteri_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SiparisOut]:
    stmt = select(Order).where(Order.is_deleted.is_(False)).order_by(Order.id.desc()).limit(limit)
    if user.role.scope == "KENDI_MUSTERILERI":
        stmt = stmt.where(Order.owner_id == user.id)
    if durum:
        stmt = stmt.where(Order.status == durum)
    if musteri_id:
        stmt = stmt.where(Order.customer_id == musteri_id)
    return [await _cikti(db, s, detay=False) for s in (await db.scalars(stmt)).all()]


@router.get("/bekleyen-sevkiyat")
async def bekleyen_sevkiyat(db: DbDep, user: Okuyucu) -> list[dict]:
    """Depo iş listesi: onaylanmış ama tamamen sevk edilmemiş siparişler."""
    return await svc.bekleyen_sevkiyat(db)


@router.get("/{siparis_id}", response_model=SiparisOut)
async def getir(siparis_id: int, db: DbDep, user: Okuyucu) -> SiparisOut:
    return await _cikti(db, await _getir(db, siparis_id, user))


@router.get("/{siparis_id}/uygun-cihazlar", response_model=list[UygunCihazOut])
async def uygun_cihazlar(
    siparis_id: int,
    kalem_id: int,
    db: DbDep,
    user: Okuyucu,
    ara: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[UygunCihazOut]:
    """Kaleme rezerve EDİLEBİLİR cihazlar — arayüze imkânsız seçenek sunulmaz.

    Başka bir siparişte açık rezervasyonu olan cihaz listede görünmez.
    """
    await _getir(db, siparis_id, user)
    kalem = await db.get(OrderLine, kalem_id)
    if kalem is None or kalem.order_id != siparis_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kalem bulunamadı")

    rezerveli = select(OrderReservation.device_id).where(OrderReservation.released_at.is_(None))
    stmt = (
        select(Device)
        .where(
            Device.is_deleted.is_(False),
            Device.status.in_(svc.REZERVE_EDILEBILIR),
            Device.id.not_in(rezerveli),
        )
        .order_by(Device.id)
        .limit(limit)
    )
    if kalem.product_id:
        stmt = stmt.where(Device.product_id == kalem.product_id)
    if ara:
        stmt = stmt.where((Device.imei.ilike(f"%{ara}%")) | (Device.serial_no.ilike(f"%{ara}%")))
    return [
        UygunCihazOut.model_validate(c, from_attributes=True)
        for c in (await db.scalars(stmt)).all()
    ]


@router.post("", response_model=SiparisOut, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: SiparisIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> SiparisOut:
    siparis = Order(
        order_no=await svc.numara_uret(db, clock),
        customer_id=payload.customer_id,
        owner_id=user.id,
        order_date=payload.order_date or clock.now().date(),
        requested_date=payload.requested_date,
        currency=payload.currency,
        fx_rate=payload.fx_rate,
        fx_date=payload.fx_date,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(siparis)
    await db.flush()
    await _kalemleri_yaz(db, siparis, payload.kalemler)
    await svc.hesapla(db, siparis)

    await audit.log(
        db,
        "orders",
        "olustur",
        entity_id=siparis.id,
        new_value={"no": siparis.order_no, "musteri": siparis.customer_id},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, siparis)


@router.post(
    "/tekliften/{teklif_id}", response_model=SiparisOut, status_code=status.HTTP_201_CREATED
)
async def tekliften(
    teklif_id: int,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
    istenen_tarih: date | None = None,
) -> SiparisOut:
    """Kabul edilmiş teklif versiyonundan sipariş açar (kabul kriteri 8).

    Teklif kapsam dışıysa 404 (teklif uçlarıyla aynı kural). Birimli (teknik
    servis) teklif siparişe DÖNÜŞMEZ (K17): kabul edilen servis teklifi iş
    gelirine akar, satış siparişi ve sevkiyat zincirine girmez → 409.
    """
    from app.services import quotes as teklif_svc

    teklif = await db.get(Quote, teklif_id)
    if teklif is None or teklif.is_deleted or teklif_svc.teklif_kapsam_disinda_mi(user, teklif):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teklif bulunamadı")
    if teklif_svc.birimli_mi(teklif):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Teknik servis teklifi siparişe dönüştürülemez; kabul geliri servis işine yazılır",
        )
    versiyon = (
        await db.get(QuoteVersion, teklif.current_version_id) if teklif.current_version_id else None
    )
    if versiyon is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Teklifin güncel versiyonu yok")
    try:
        siparis = await svc.tekliften_olustur(
            db, teklif, versiyon, clock=clock, user_id=user.id, istenen_tarih=istenen_tarih
        )
    except svc.SiparisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "orders",
        "tekliften",
        entity_id=siparis.id,
        new_value={"no": siparis.order_no, "teklif": teklif.quote_no},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, siparis)


@router.patch("/{siparis_id}", response_model=SiparisOut)
async def guncelle(
    siparis_id: int,
    payload: SiparisGuncelle,
    request: Request,
    db: DbDep,
    user: Yazici,
) -> SiparisOut:
    s = await _getir(db, siparis_id, user)
    # İSTEMCİNİN version DEĞERİ KAYDA ATANMAZ. Atandığında SQLAlchemy'nin
    # `WHERE version = :eski` koşulu her zaman tutuyor, iyimser kilitleme
    # tamamen devre dışı kalıyordu: bayat bir sürümle gelen istek 200 dönüp
    # aradaki değişikliği sessizce eziyor, sayaç geriye gidiyordu (ölçüldü:
    # 4 -> 1). Doğru davranış, uyuşmazlıkta 409 (plan §3.3/1).
    if payload.version != s.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. "
            "Sayfayı yenileyip değişikliğinizi tekrar uygulayın.",
        )
    # PATCH kısmi güncellemedir: gönderilmeyen alan DEĞİŞMEZ. Koşulsuz
    # atama, yalnız notu değiştiren bir istekte `requested_date` alanını
    # NULL'lıyordu — kullanıcının dokunmadığı veri sessizce siliniyordu.
    for alan, deger in payload.model_dump(exclude={"version"}, exclude_unset=True).items():
        setattr(s, alan, deger)
    s.updated_by = user.id
    await audit.log_change(db, s, "guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    return await _cikti(db, s)


@router.put("/{siparis_id}/kalemler", response_model=SiparisOut)
async def kalemleri_degistir(
    siparis_id: int,
    kalemler: list[KalemIn],
    request: Request,
    db: DbDep,
    user: Yazici,
) -> SiparisOut:
    """Kalemleri toptan değiştirir — yalnız TASLAK siparişte.

    Onaylanmış siparişin içeriği değişmez: rezervasyon ve sevkiyat ona
    dayanıyor olabilir.
    """
    s = await _getir(db, siparis_id, user)
    if s.status != "TASLAK":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{s.status} durumundaki siparişin kalemleri değiştirilemez.",
        )
    for k in (await db.scalars(select(OrderLine).where(OrderLine.order_id == s.id))).all():
        await db.delete(k)
    await db.flush()
    await _kalemleri_yaz(db, s, kalemler)
    await svc.hesapla(db, s)
    await audit.log(
        db,
        "orders",
        "kalem.degistir",
        entity_id=s.id,
        new_value={"adet": len(kalemler), "toplam": float(s.grand_total)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, s)


@router.post("/{siparis_id}/onayla", response_model=SiparisOut)
async def onayla(
    siparis_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> SiparisOut:
    s = await _getir(db, siparis_id, user)
    try:
        SIPARIS.dogrula(s.status, "ONAYLANDI")
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    kalem_var = await db.scalar(select(OrderLine.id).where(OrderLine.order_id == s.id).limit(1))
    if kalem_var is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Kalemi olmayan sipariş onaylanamaz.")

    s.status = "ONAYLANDI"
    s.approved_at = clock.now()
    s.updated_by = user.id
    await audit.log(
        db,
        "orders",
        "onayla",
        entity_id=s.id,
        new_value={"no": s.order_no},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, s)


class IptalIn(BaseModel):
    neden: str = Field(min_length=3, max_length=200)


@router.post("/{siparis_id}/iptal", response_model=SiparisOut)
async def iptal(
    siparis_id: int,
    payload: IptalIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> SiparisOut:
    """Siparişi iptal eder; açık rezervasyonlar serbest kalır."""
    s = await _getir(db, siparis_id, user)
    try:
        s = await svc.iptal_et(
            db,
            s,
            clock=clock,
            neden=payload.neden,
            user_id=user.id,
            ip=client_ip(request),
        )
    except svc.SiparisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "orders",
        "iptal",
        entity_id=s.id,
        new_value={"no": s.order_no, "neden": payload.neden},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, s)


class RezerveIn(BaseModel):
    kalem_id: int
    # IMEI veya seri no — barkod okutarak ya da listeden seçerek.
    kimlikler: list[str] = Field(default_factory=list)
    device_ids: list[int] = Field(default_factory=list)


@router.post("/{siparis_id}/rezerve", response_model=SiparisOut)
async def rezerve_et(
    siparis_id: int,
    payload: RezerveIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> SiparisOut:
    s = await _getir(db, siparis_id, user)
    kalem = await db.get(OrderLine, payload.kalem_id)
    if kalem is None or kalem.order_id != s.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kalem bulunamadı")

    device_ids = list(payload.device_ids)
    if payload.kimlikler:
        cihazlar = (
            await db.scalars(
                select(Device).where(
                    (Device.imei.in_(payload.kimlikler))
                    | (Device.serial_no.in_(payload.kimlikler)),
                    Device.is_deleted.is_(False),
                )
            )
        ).all()
        bulunan = {c.imei for c in cihazlar if c.imei} | {
            c.serial_no for c in cihazlar if c.serial_no
        }
        eksik = [k for k in payload.kimlikler if k not in bulunan]
        if eksik:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{len(eksik)} kimlik sistemde bulunamadı: {', '.join(eksik[:5])}"
                + (" …" if len(eksik) > 5 else ""),
            )
        device_ids += [c.id for c in cihazlar]
    if not device_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rezerve edilecek cihaz seçilmedi")

    try:
        rezervasyonlar = await svc.rezerve_et(
            db,
            s,
            kalem,
            device_ids,
            clock=clock,
            user_id=user.id,
            ip=client_ip(request),
        )
    except svc.SiparisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "orders",
        "rezerve",
        entity_id=s.id,
        new_value={"kalem": kalem.id, "adet": len(rezervasyonlar)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, s)


class RezervasyonBirakIn(BaseModel):
    neden: str | None = Field(default=None, max_length=200)


@router.post("/rezervasyon/{rezervasyon_id}/birak", response_model=SiparisOut)
async def rezervasyon_birak(
    rezervasyon_id: int,
    payload: RezervasyonBirakIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> SiparisOut:
    rez = await db.get(OrderReservation, rezervasyon_id)
    if rez is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rezervasyon bulunamadı")
    s = await _getir(db, rez.order_id, user)
    try:
        await svc.rezervasyon_birak(
            db,
            rez,
            clock=clock,
            neden=payload.neden,
            user_id=user.id,
            ip=client_ip(request),
        )
    except svc.SiparisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "orders",
        "rezerve.birak",
        entity_id=s.id,
        new_value={"cihaz": rez.device_id, "neden": payload.neden},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, s)


class SevkIn(BaseModel):
    rezervasyon_ids: list[int] = Field(default_factory=list)
    from_warehouse_id: int | None = None
    belge_no: str | None = Field(default=None, max_length=40)


class SevkOut(BaseModel):
    transfer_id: int
    transfer_no: str
    adet: int
    siparis: SiparisOut


@router.post("/{siparis_id}/sevk", response_model=SevkOut)
async def sevk_et(
    siparis_id: int,
    payload: SevkIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> SevkOut:
    """Rezerve cihazları sevk eder; stok transfer belgesi üretilir.

    `rezervasyon_ids` boşsa siparişin TÜM açık rezervasyonları sevk edilir.
    """
    s = await _getir(db, siparis_id, user)
    acik = await svc.acik_rezervasyonlar(db, s.id)
    if payload.rezervasyon_ids:
        secili = [r for r in acik if r.id in set(payload.rezervasyon_ids)]
        if len(secili) != len(set(payload.rezervasyon_ids)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Seçilen rezervasyonların bir kısmı açık değil"
            )
    else:
        secili = acik

    try:
        transfer = await svc.sevk_et(
            db,
            s,
            secili,
            clock=clock,
            from_warehouse_id=payload.from_warehouse_id,
            belge_no=payload.belge_no,
            teslim_eden=user.full_name,
            user_id=user.id,
            ip=client_ip(request),
        )
    except svc.SiparisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "orders",
        "sevk",
        entity_id=s.id,
        new_value={"transfer": transfer.transfer_no, "adet": len(secili)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return SevkOut(
        transfer_id=transfer.id,
        transfer_no=transfer.transfer_no,
        adet=len(secili),
        siparis=await _cikti(db, s),
    )


class TeslimIn(BaseModel):
    received_by: str | None = Field(default=None, max_length=120)


@router.post("/sevkiyat/{transfer_id}/teslim", response_model=SiparisOut)
async def teslim_et(
    transfer_id: int,
    payload: TeslimIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> SiparisOut:
    """Sevkiyatı teslim alındı işaretler; konum ve sahiplik güncellenir."""
    transfer = await db.get(Transfer, transfer_id)
    if transfer is None or transfer.order_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sipariş sevkiyatı bulunamadı")
    s = await _getir(db, transfer.order_id, user)
    try:
        adet = await svc.teslim_et(db, transfer, clock=clock, teslim_alan=payload.received_by)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "orders",
        "teslim",
        entity_id=s.id,
        new_value={"transfer": transfer.transfer_no, "cihaz": adet},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, s)
