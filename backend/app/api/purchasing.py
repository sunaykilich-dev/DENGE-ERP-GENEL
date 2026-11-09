"""Satın alma, ithalat dosyası, landed cost ve BTK IMEI takibi."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sees_cost
from app.models import (
    Account,
    GoodsReceipt,
    ImportFile,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    User,
)
from app.models.purchase import DAGITIM_ANAHTARLARI, ITHALAT_DURUMLARI
from app.services import audit
from app.services import export as export_svc
from app.services import purchasing as svc
from app.services.statemachine import SATINALMA, IzinsizGecis

router = APIRouter(prefix="/api/satinalma", tags=["satinalma"])

Okuyucu = Annotated[User, Depends(require_permission("satinalma.gor"))]
Yazici = Annotated[User, Depends(require_permission("satinalma.yaz"))]


# --- Şemalar ------------------------------------------------------------------


class KalemIn(BaseModel):
    product_id: int
    description: str | None = Field(default=None, max_length=300)
    qty: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    unit_weight_kg: Decimal | None = None


class SiparisIn(BaseModel):
    supplier_id: int
    order_date: date | None = None
    expected_date: date | None = None
    currency: str = "USD"
    fx_rate: Decimal | None = None
    fx_date: date | None = None
    notes: str | None = None
    kalemler: list[KalemIn] = Field(default_factory=list)


class KalemOut(BaseModel):
    id: int
    product_id: int
    urun_kodu: str | None = None
    # Ürünün kimlik türü (IMEI | SERI_NO | YOK); YOK → mal kabul adetle (TS-196).
    kimlik_turu: str | None = None
    description: str | None
    qty: Decimal
    unit_price: Decimal
    qty_received: Decimal
    unit_weight_kg: Decimal | None

    model_config = {"from_attributes": True}


class SiparisOut(BaseModel):
    id: int
    po_no: str
    supplier_id: int
    supplier_title: str | None = None
    status: str
    order_date: date
    expected_date: date | None
    currency: str
    fx_rate: Decimal | None
    subtotal: Decimal
    notes: str | None
    version: int
    sonraki_durumlar: list[str] = []
    kalemler: list[KalemOut] = []

    model_config = {"from_attributes": True}


class MalKabulIn(BaseModel):
    """IMEI/seri kalemde `kimlikler`; serisiz kalemde `adet` (TS-196, E11-D02)."""

    kalem_id: int
    kimlikler: list[str] = Field(default_factory=list)
    adet: int | None = Field(default=None, gt=0)
    import_file_id: int | None = None
    warehouse_id: int | None = None


class IthalatIn(BaseModel):
    purchase_order_id: int | None = None
    supplier_id: int | None = None
    invoice_no: str | None = Field(default=None, max_length=60)
    invoice_date: date | None = None
    incoterm: str | None = Field(default=None, max_length=10)
    customs_declaration_no: str | None = Field(default=None, max_length=40)
    cleared_at: date | None = None
    currency: str = "USD"
    fx_rate: Decimal | None = None
    goods_value_try: Decimal = Decimal("0")
    freight_try: Decimal = Decimal("0")
    insurance_try: Decimal = Decimal("0")
    customs_duty_try: Decimal = Decimal("0")
    other_tax_try: Decimal = Decimal("0")
    broker_fee_try: Decimal = Decimal("0")
    inland_freight_try: Decimal = Decimal("0")
    other_cost_try: Decimal = Decimal("0")
    allocation_key: str = "TUTAR"
    notes: str | None = None

    def dogrula(self) -> None:
        if self.allocation_key not in DAGITIM_ANAHTARLARI:
            raise ValueError(f"Dağıtım anahtarı {DAGITIM_ANAHTARLARI} içinden olmalı")


class IthalatOut(BaseModel):
    id: int
    file_no: str
    purchase_order_id: int | None
    supplier_id: int | None
    status: str
    invoice_no: str | None
    invoice_date: date | None
    incoterm: str | None
    customs_declaration_no: str | None
    cleared_at: date | None
    currency: str
    fx_rate: Decimal | None
    goods_value_try: Decimal
    freight_try: Decimal
    insurance_try: Decimal
    customs_duty_try: Decimal
    other_tax_try: Decimal
    broker_fee_try: Decimal
    inland_freight_try: Decimal
    other_cost_try: Decimal
    allocation_key: str
    allocated_at: date | None
    allocated_device_count: int
    notes: str | None
    version: int
    toplam_masraf: Decimal = Decimal("0")

    model_config = {"from_attributes": True}


class BtkKayitIn(BaseModel):
    device_ids: list[int] = Field(min_length=1)
    referans: str | None = Field(default=None, max_length=60)


# --- Yardımcılar --------------------------------------------------------------


async def _siparis_ciktisi(db: DbDep, s: PurchaseOrder, *, detay: bool = True) -> SiparisOut:
    out = SiparisOut.model_validate(s)
    h = await db.get(Account, s.supplier_id)
    out.supplier_title = h.title if h else None
    out.sonraki_durumlar = sorted(SATINALMA.sonraki(s.status))
    if detay:
        kalemler = (
            await db.scalars(
                select(PurchaseOrderLine)
                .where(PurchaseOrderLine.purchase_order_id == s.id)
                .order_by(PurchaseOrderLine.sort_order, PurchaseOrderLine.id)
            )
        ).all()
        urunler = {
            u.id: u
            for u in (
                await db.scalars(
                    select(Product).where(Product.id.in_([k.product_id for k in kalemler] or [0]))
                )
            ).all()
        }
        cikti = []
        for k in kalemler:
            ko = KalemOut.model_validate(k)
            ko.urun_kodu = urunler[k.product_id].code if k.product_id in urunler else None
            ko.kimlik_turu = (
                urunler[k.product_id].identity_kind if k.product_id in urunler else None
            )
            cikti.append(ko)
        out.kalemler = cikti
    return out


def _ithalat_ciktisi(d: ImportFile) -> IthalatOut:
    out = IthalatOut.model_validate(d)
    out.toplam_masraf = svc.dosya_toplami(d)
    return out


async def _siparis(db: DbDep, siparis_id: int) -> PurchaseOrder:
    s = await db.get(PurchaseOrder, siparis_id)
    if s is None or s.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Satın alma siparişi bulunamadı")
    return s


# --- Satın alma siparişi ------------------------------------------------------


@router.get("/siparisler", response_model=list[SiparisOut])
async def siparisleri_listele(
    db: DbDep,
    user: Okuyucu,
    durum: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SiparisOut]:
    stmt = (
        select(PurchaseOrder)
        .where(PurchaseOrder.is_deleted.is_(False))
        .order_by(PurchaseOrder.id.desc())
        .limit(limit)
    )
    if durum:
        stmt = stmt.where(PurchaseOrder.status == durum)
    return [await _siparis_ciktisi(db, s, detay=False) for s in (await db.scalars(stmt)).all()]


@router.get("/siparisler/{siparis_id}", response_model=SiparisOut)
async def siparis_getir(siparis_id: int, db: DbDep, user: Okuyucu) -> SiparisOut:
    return await _siparis_ciktisi(db, await _siparis(db, siparis_id))


@router.post("/siparisler", response_model=SiparisOut, status_code=status.HTTP_201_CREATED)
async def siparis_ac(
    payload: SiparisIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> SiparisOut:
    tedarikci = await db.get(Account, payload.supplier_id)
    if tedarikci is None or tedarikci.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tedarikçi bulunamadı")
    if not tedarikci.is_tedarikci:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{tedarikci.title} hesabı tedarikçi olarak işaretli değil.",
        )

    siparis = PurchaseOrder(
        po_no=await svc.numara_uret(db, clock, PurchaseOrder, "SA"),
        supplier_id=payload.supplier_id,
        order_date=payload.order_date or clock.now().date(),
        expected_date=payload.expected_date,
        currency=payload.currency,
        fx_rate=payload.fx_rate,
        fx_date=payload.fx_date,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(siparis)
    await db.flush()
    for sira, k in enumerate(payload.kalemler):
        db.add(PurchaseOrderLine(purchase_order_id=siparis.id, sort_order=sira, **k.model_dump()))
    await db.flush()
    await svc.siparis_hesapla(db, siparis)

    await audit.log(
        db,
        "purchase_orders",
        "olustur",
        entity_id=siparis.id,
        new_value={"no": siparis.po_no, "tedarikci": tedarikci.title},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _siparis_ciktisi(db, siparis)


@router.post("/siparisler/{siparis_id}/durum", response_model=SiparisOut)
async def siparis_durum(
    siparis_id: int, payload: dict, request: Request, db: DbDep, user: Yazici
) -> SiparisOut:
    s = await _siparis(db, siparis_id)
    hedef = str(payload.get("durum", ""))
    onceki = s.status
    try:
        SATINALMA.dogrula(onceki, hedef)
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if hedef == "SIPARIS_VERILDI" and not await db.scalar(
        select(PurchaseOrderLine.id).where(PurchaseOrderLine.purchase_order_id == s.id).limit(1)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Kalemi olmayan sipariş verilemez.")

    s.status = hedef
    s.updated_by = user.id
    await audit.log(
        db,
        "purchase_orders",
        "durum.degistir",
        entity_id=s.id,
        old_value={"status": onceki},
        new_value={"status": hedef},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _siparis_ciktisi(db, s)


@router.post("/siparisler/{siparis_id}/mal-kabul")
async def mal_kabul(
    siparis_id: int,
    payload: MalKabulIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict:
    """IMEI listesini stoğa alır. İthalat dosyası verilirse cihazlar ITHALATTA doğar.
    Serisiz kalem `adet` ile kabul edilir (servis deposuna maliyet dondurularak)."""
    s = await _siparis(db, siparis_id)
    kalem = await db.get(PurchaseOrderLine, payload.kalem_id)
    if kalem is None or kalem.purchase_order_id != s.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kalem bulunamadı")
    kimlikler = [k.strip() for k in payload.kimlikler if k.strip()]
    if not kimlikler and payload.adet is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Kimlik listesi ya da (serisiz kalemde) adet girilmeli"
        )
    if payload.warehouse_id is not None:
        # Servis deposu birim kapsamlıdır (2026-11-09): başka birimin deposuna
        # mal kabul girilemez; varlığı gizlenir (404). Mobilite deposu değişmez.
        from app.models import Warehouse
        from app.services.teknik_servis import parca

        depo = await db.get(Warehouse, payload.warehouse_id)
        if depo is not None and depo.servis_deposu:
            try:
                await parca.depo_getir(db, user, depo.id)
            except parca.ParcaBulunamadi as exc:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Depo bulunamadı") from exc

    try:
        fis = await svc.mal_kabul(
            db,
            s,
            kalem=kalem,
            kimlikler=kimlikler,
            clock=clock,
            import_file_id=payload.import_file_id,
            warehouse_id=payload.warehouse_id,
            user_id=user.id,
            adet=payload.adet,
        )
    except svc.SatinAlmaHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "goods_receipts",
        "olustur",
        entity_id=fis.id,
        new_value={"no": fis.receipt_no, "siparis": s.po_no, "adet": fis.device_count},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {
        "fis_no": fis.receipt_no,
        "adet": fis.device_count,
        "siparis": await _siparis_ciktisi(db, s),
    }


@router.get("/siparisler/{siparis_id}/mal-kabuller")
async def mal_kabulleri(siparis_id: int, db: DbDep, user: Okuyucu) -> list[dict]:
    await _siparis(db, siparis_id)
    fisler = (
        await db.scalars(
            select(GoodsReceipt)
            .where(GoodsReceipt.purchase_order_id == siparis_id)
            .order_by(GoodsReceipt.id)
        )
    ).all()
    return [
        {
            "id": f.id,
            "receipt_no": f.receipt_no,
            "received_at": f.received_at,
            "device_count": f.device_count,
            "import_file_id": f.import_file_id,
        }
        for f in fisler
    ]


# --- İthalat dosyası ----------------------------------------------------------


@router.get("/ithalat", response_model=list[IthalatOut])
async def ithalat_listele(
    db: DbDep, user: Okuyucu, durum: str | None = None, limit: int = Query(default=50, ge=1, le=200)
) -> list[IthalatOut]:
    stmt = (
        select(ImportFile)
        .where(ImportFile.is_deleted.is_(False))
        .order_by(ImportFile.id.desc())
        .limit(limit)
    )
    if durum:
        stmt = stmt.where(ImportFile.status == durum)
    return [_ithalat_ciktisi(d) for d in (await db.scalars(stmt)).all()]


@router.post("/ithalat", response_model=IthalatOut, status_code=status.HTTP_201_CREATED)
async def ithalat_ac(
    payload: IthalatIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> IthalatOut:
    try:
        payload.dogrula()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    dosya = ImportFile(
        file_no=await svc.numara_uret(db, clock, ImportFile, "ITH"),
        **payload.model_dump(),
        created_by=user.id,
    )
    db.add(dosya)
    await db.flush()
    await audit.log(
        db,
        "import_files",
        "olustur",
        entity_id=dosya.id,
        new_value={"no": dosya.file_no, "fatura": dosya.invoice_no},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _ithalat_ciktisi(dosya)


class IthalatGuncelle(IthalatIn):
    status: str = "ACIK"
    version: int = 1


@router.patch("/ithalat/{dosya_id}", response_model=IthalatOut)
async def ithalat_guncelle(
    dosya_id: int, payload: IthalatGuncelle, request: Request, db: DbDep, user: Yazici
) -> IthalatOut:
    dosya = await db.get(ImportFile, dosya_id)
    if dosya is None or dosya.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "İthalat dosyası bulunamadı")
    try:
        payload.dogrula()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if payload.status not in ITHALAT_DURUMLARI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Durum {ITHALAT_DURUMLARI} içinden olmalı"
        )

    # İSTEMCİNİN version DEĞERİ KAYDA ATANMAZ. Atandığında SQLAlchemy'nin
    # `WHERE version = :eski` koşulu her zaman tutuyor, iyimser kilitleme
    # tamamen devre dışı kalıyordu: bayat bir sürümle gelen istek 200 dönüp
    # aradaki değişikliği sessizce eziyor, sayaç geriye gidiyordu (ölçüldü:
    # 4 -> 1). Doğru davranış, uyuşmazlıkta 409 (plan §3.3/1).
    if payload.version != dosya.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. "
            "Sayfayı yenileyip değişikliğinizi tekrar uygulayın.",
        )
    for alan, deger in payload.model_dump(exclude={"version"}).items():
        setattr(dosya, alan, deger)
    dosya.updated_by = user.id
    await audit.log_change(db, dosya, "guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    return _ithalat_ciktisi(dosya)


@router.post("/ithalat/{dosya_id}/landed-cost")
async def landed_cost(
    dosya_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict:
    """Masrafları cihazlara dağıtır. Yeniden çalıştırılabilir."""
    dosya = await db.get(ImportFile, dosya_id)
    if dosya is None or dosya.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "İthalat dosyası bulunamadı")
    try:
        sonuc = await svc.landed_cost_dagit(db, dosya, clock=clock, user_id=user.id)
    except svc.SatinAlmaHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.log(
        db,
        "import_files",
        "landed_cost",
        entity_id=dosya.id,
        new_value={
            "toplam": float(sonuc["dosya_toplami"]),
            "cihaz": sonuc["cihaz_sayisi"],
            "anahtar": sonuc["anahtar"],
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {**sonuc, "dosya": _ithalat_ciktisi(dosya)}


@router.get("/ithalat/{dosya_id}/cihazlar")
async def ithalat_cihazlari(db: DbDep, dosya_id: int, user: Okuyucu) -> list[dict]:
    """Dosyaya bağlı cihazlar ve birim maliyetleri.

    Maliyet YETKİYE BAĞLI (plan §3.4): `maliyet.gor` izni olmayan kullanıcı
    listeyi görür ama tutarı görmez.
    """
    from app.models import Device

    cihazlar = (
        await db.scalars(
            select(Device)
            .where(Device.import_file_id == dosya_id, Device.is_deleted.is_(False))
            .order_by(Device.id)
        )
    ).all()
    goster = sees_cost(user)
    return [
        {
            "device_id": c.id,
            "kimlik": c.imei or c.serial_no,
            "status": c.status,
            "btk_status": c.btk_status,
            "landed_cost_try": (float(c.landed_cost_try) if c.landed_cost_try else None)
            if goster
            else None,
        }
        for c in cihazlar
    ]


# --- BTK ----------------------------------------------------------------------


@router.get("/btk/bekleyenler")
async def btk_bekleyenler(db: DbDep, user: Okuyucu) -> list[dict]:
    """BTK IMEI kaydı bekleyen cihazlar (brief §4.13)."""
    return await svc.btk_bekleyenler(db)


@router.get("/btk/bekleyenler.xlsx")
async def btk_xlsx(
    db: DbDep, user: Annotated[User, Depends(require_permission("rapor.disaaktar"))]
) -> Response:
    """BTK'ya sunulacak IMEI listesi."""
    satirlar = await svc.btk_bekleyenler(db)
    basliklar = [
        "IMEI",
        "Seri No",
        "Ürün Kodu",
        "Ürün Adı",
        "CE Belgesi",
        "TSE Belgesi",
        "Uygunluk Belgesi",
        "İthalat Dosyası",
        "Gümrük Beyanname No",
    ]
    tablo = [
        [
            s["imei"] or "",
            s["serial_no"] or "",
            s["urun_kodu"],
            s["urun_adi"],
            s["ce_belgesi"] or "",
            s["tse_belgesi"] or "",
            s["uygunluk_belgesi"] or "",
            s["ithalat_dosyasi"] or "",
            s["gumruk_beyanname"] or "",
        ]
        for s in satirlar
    ]
    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, tablo, "BTK Bekleyen"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="btk-bekleyen.xlsx"'},
    )


@router.post("/btk/kaydet")
async def btk_kaydet(
    payload: BtkKayitIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict:
    adet = await svc.btk_kaydet(
        db,
        payload.device_ids,
        referans=payload.referans,
        clock=clock,
        user_id=user.id,
    )
    await audit.log(
        db,
        "devices",
        "btk.kaydet",
        new_value={"adet": adet, "referans": payload.referans},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {"kaydedilen": adet}
