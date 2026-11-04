"""Hak ediş dökümleri — ay sonu kapanışı, onay, kesinti, itiraz, ödeme."""

import re
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    donem_dogrula,
    require_permission,
    sayfala,
)
from app.models import (
    Account,
    InstallationPartner,
    PartnerSettlement,
    Payment,
    SettlementDispute,
    SettlementLine,
    User,
)
from app.services import audit, belgeler, mail
from app.services import export as export_svc
from app.services import settings as ayar_svc
from app.services import settlements as svc
from app.services.pdf import PdfUretilemedi
from app.services.statemachine import IzinsizGecis, StateMachine

router = APIRouter(prefix="/api/hakedis", tags=["hak edis"])

_DONEM_BICIMI = re.compile(r"^\d{4}-\d{2}$")

Okuyucu = Annotated[User, Depends(require_permission("hakedis.gor"))]
Yazici = Annotated[User, Depends(require_permission("hakedis.yaz"))]
Onaylayici = Annotated[User, Depends(require_permission("hakedis.onayla"))]
Odeyici = Annotated[User, Depends(require_permission("hakedis.ode"))]

# Döküm durum akışı (brief §4.7 madde 7).
DOKUM = StateMachine(
    ad="Hak ediş dökümü",
    gecisler={
        "TASLAK": frozenset({"ONAY_BEKLIYOR"}),
        "ONAY_BEKLIYOR": frozenset({"ONAYLANDI", "ITIRAZDA", "TASLAK"}),
        "ONAYLANDI": frozenset({"ODEME_BEKLIYOR", "ITIRAZDA"}),
        "ITIRAZDA": frozenset({"ONAY_BEKLIYOR", "TASLAK"}),
        "ODEME_BEKLIYOR": frozenset({"ODENDI", "ITIRAZDA"}),
        "ODENDI": frozenset(),  # terminal — kapanmış dönem değişmez
    },
)


class SatirOut(BaseModel):
    id: int
    work_order_id: int | None
    work_type: str
    description: str | None
    unit_price: float
    quantity: float
    amount: float
    price_source: str | None
    is_deduction: bool
    deduction_reason: str | None
    locked_at: datetime | None

    model_config = {"from_attributes": True}


class DokumOut(BaseModel):
    id: int
    partner_id: int
    partner_title: str | None = None
    billing_account_id: int | None
    billing_title: str | None = None
    belge_tipi: str | None = None
    period: str
    status: str
    sonraki_durumlar: list[str] = []
    gross_amount: float
    deduction_amount: float
    withholding_amount: float
    stamp_tax_amount: float
    vat_amount: float
    net_payable: float
    tax_snapshot: dict | None
    partner_document_no: str | None
    partner_document_date: date | None
    approved_at: datetime | None
    sent_at: datetime | None
    paid_at: datetime | None
    satir_adedi: int = 0
    eksik_alanlar: list[str] = []
    version: int

    model_config = {"from_attributes": True}


class DokumDetay(DokumOut):
    satirlar: list[SatirOut] = []


async def _cikti(db: DbDep, d: PartnerSettlement, detay: bool = False) -> DokumOut:
    out = (DokumDetay if detay else DokumOut).model_validate(d)
    out.sonraki_durumlar = sorted(DOKUM.sonraki(d.status))
    hesap = await db.get(Account, d.partner_id)
    if hesap:
        out.partner_title = hesap.title
        # Döküm e-posta ile gönderilecek ve ödeme listesi IBAN'dan üretilecek.
        eksik = []
        if not hesap.email:
            eksik.append("e-posta")
        if not hesap.iban:
            eksik.append("IBAN")
        if not hesap.tax_no:
            eksik.append("VKN/TCKN")
        out.eksik_alanlar = eksik
    if d.billing_account_id:
        b = await db.get(Account, d.billing_account_id)
        out.billing_title = b.title if b else None
    ortak = await db.get(InstallationPartner, d.partner_id)
    out.belge_tipi = ortak.document_type if ortak else None
    out.satir_adedi = (
        await db.scalar(
            select(func.count())
            .select_from(SettlementLine)
            .where(SettlementLine.settlement_id == d.id)
        )
        or 0
    )
    if detay:
        out.satirlar = [SatirOut.model_validate(s) for s in d.lines]
    return out


@router.get("", response_model=list[DokumOut])
async def listele(
    db: DbDep,
    _: Okuyucu,
    donem: str | None = Query(default=None, description="YYYY-AA"),
    durum: str | None = None,
    montaj_noktasi_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    response: Response = None,  # type: ignore[assignment]
) -> list[DokumOut]:
    donem_dogrula(donem)
    # Diğer tüm liste uçları `sayfala()` kullanıyor; bu uç sert `limit` ile
    # kalmıştı. Bugün 83 döküm var, her kapanan dönem 30-40 ekliyor: 500'ü
    # aştığı ay arayüz gerisini sessizce göstermeyecekti.
    stmt = select(PartnerSettlement).order_by(PartnerSettlement.period.desc(), PartnerSettlement.id)
    if donem:
        stmt = stmt.where(PartnerSettlement.period == donem)
    if durum:
        stmt = stmt.where(PartnerSettlement.status == durum)
    if montaj_noktasi_id:
        stmt = stmt.where(PartnerSettlement.partner_id == montaj_noktasi_id)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [await _cikti(db, d) for (d,) in satirlar]


@router.get("/ozet")
async def donem_ozeti(db: DbDep, _: Okuyucu) -> list[dict]:
    """Dönem bazında toplam — canlı uygulamayla karşılaştırma ekranı."""
    satirlar = (
        await db.execute(
            select(
                PartnerSettlement.period,
                func.count(func.distinct(PartnerSettlement.id)),
                func.coalesce(func.sum(PartnerSettlement.gross_amount), 0),
                func.coalesce(func.sum(PartnerSettlement.net_payable), 0),
            )
            .group_by(PartnerSettlement.period)
            .order_by(PartnerSettlement.period.desc())
        )
    ).all()
    return [
        {"donem": p, "dokum": adet, "brut": float(brut), "net": float(net)}
        for p, adet, brut, net in satirlar
    ]


@router.get("/panel/{donem}")
async def donem_paneli(donem: str, db: DbDep, _: Okuyucu) -> dict:
    """Ay özeti + gözden geçirilmesi gerekenler (canlı uygulamadaki panel).

    Dökümler oluşmadan ÖNCE bakılır: buradaki her uyarı hak edişin eksik ya
    da fazla ödenmesine yol açar ve döküm çıktıktan sonra düzeltmek pahalıdır
    — kapanmış dönem değişmez, düzeltme sonraki aya ayrı satır olarak girer.
    """
    if not _DONEM_BICIMI.match(donem):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dönem 'YYYY-AA' olmalı")
    return await svc.donem_paneli(db, donem)


@router.get("/{dokum_id}", response_model=DokumDetay)
async def getir(dokum_id: int, db: DbDep, _: Okuyucu) -> DokumDetay:
    d = await db.get(PartnerSettlement, dokum_id, options=[selectinload(PartnerSettlement.lines)])
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Döküm bulunamadı")
    return await _cikti(db, d, detay=True)


class DonemKapatIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    montaj_noktasi_id: int | None = None


@router.post("/donem-kapat")
async def donem_kapat(
    payload: DonemKapatIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict:
    """Dönemdeki onaylı işlerden dökümleri üretir. Tekrar çalıştırılabilir;
    ÖDENMİŞ dökümlere dokunmaz.

    Dönüş iki parçalıdır: üretilen `dokumler` ve `kilitli_atlanan` —
    kapanmış bir döküme düştüğü için YAZILAMAYAN kalemler. İkincisi eskiden
    sessizce atılıyordu ve uç boş liste dönüyordu; montaj noktası o işin
    parasını hiç almıyordu.
    """
    sonuc = await svc.donem_kapat(
        db, period=payload.period, clock=clock, partner_id=payload.montaj_noktasi_id
    )
    await audit.log(
        db,
        "partner_settlements",
        "donem.kapat",
        new_value={
            "donem": payload.period,
            "dokum": len(sonuc.dokumler),
            "kilitli_atlanan": len(sonuc.kilitli_atlanan),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {
        "dokumler": [await _cikti(db, d) for d in sonuc.dokumler],
        "kilitli_atlanan": sonuc.kilitli_atlanan,
    }


class DurumIn(BaseModel):
    to_status: str
    note: str | None = None


@router.post("/{dokum_id}/durum", response_model=DokumOut)
async def durum_degistir(
    dokum_id: int,
    payload: DurumIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Onaylayici,
) -> DokumOut:
    d = await db.get(PartnerSettlement, dokum_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Döküm bulunamadı")
    try:
        DOKUM.dogrula(d.status, payload.to_status)
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if payload.to_status == "ONAY_BEKLIYOR":
        ortak = await db.get(InstallationPartner, d.partner_id)
        if ortak is None or ortak.document_type == "BELIRSIZ":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Montaj noktasının belge tipi belirsiz — kesintiler hesaplanamaz. "
                "Önce fatura / serbest meslek makbuzu / gider pusulası seçin.",
            )

    onceki, d.status = d.status, payload.to_status
    if payload.to_status == "ONAYLANDI":
        d.approved_at, d.approved_by = clock.now(), user.id
        await svc.dokum_tutarlarini_guncelle(db, d)
    await audit.log(
        db,
        "partner_settlements",
        "durum.degistir",
        entity_id=d.id,
        old_value={"status": onceki},
        new_value={"status": payload.to_status, "not": payload.note},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, d)


class KesintiIn(BaseModel):
    amount: float = Field(gt=0)
    reason: str = Field(min_length=3, max_length=200)


@router.post("/{dokum_id}/kesinti", response_model=DokumOut)
async def kesinti_ekle(
    dokum_id: int, payload: KesintiIn, request: Request, db: DbDep, user: Yazici
) -> DokumOut:
    """Kesinti satırı ekler (hatalı montaj, geri dönüş, eksik fotoğraf…)."""
    d = await db.get(PartnerSettlement, dokum_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Döküm bulunamadı")
    if d.kilitli:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ödenmiş dönem değiştirilemez. Düzeltme sonraki döneme devreden "
            "ayrı bir satır olarak girilmelidir.",
        )
    db.add(
        SettlementLine(
            settlement_id=d.id,
            work_type="KESINTI",
            description=payload.reason,
            unit_price=payload.amount,
            quantity=1,
            amount=payload.amount,
            is_deduction=True,
            deduction_reason=payload.reason,
        )
    )
    await db.flush()
    await svc.dokum_tutarlarini_guncelle(db, d)
    await audit.log(
        db,
        "partner_settlements",
        "kesinti.ekle",
        entity_id=d.id,
        new_value={"tutar": payload.amount, "neden": payload.reason},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, d)


class ItirazIn(BaseModel):
    description: str = Field(min_length=3)
    line_id: int | None = None


@router.post("/{dokum_id}/itiraz", response_model=DokumOut)
async def itiraz_ekle(
    dokum_id: int, payload: ItirazIn, request: Request, db: DbDep, user: Yazici
) -> DokumOut:
    d = await db.get(PartnerSettlement, dokum_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Döküm bulunamadı")
    db.add(
        SettlementDispute(
            settlement_id=d.id,
            line_id=payload.line_id,
            description=payload.description,
            created_by=user.id,
        )
    )
    if DOKUM.izinli_mi(d.status, "ITIRAZDA"):
        d.status = "ITIRAZDA"
    await audit.log(
        db,
        "settlement_disputes",
        "olustur",
        entity_id=d.id,
        new_value={"aciklama": payload.description[:200]},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, d)


class OdemeIn(BaseModel):
    amount: float = Field(gt=0)
    paid_at: date
    method: str | None = None
    reference: str | None = None
    partner_document_no: str | None = None
    partner_document_date: date | None = None
    # Tutar dökümün netinden farklıysa işlem reddedilir. Kasıtlı eksik/fazla
    # ödeme için açıkça işaretlenir ve gerekçesi denetim izine yazılır.
    farkli_tutar_onayi: bool = False
    fark_gerekcesi: str | None = Field(default=None, max_length=300)


@router.post("/{dokum_id}/ode", response_model=DokumOut)
async def ode(
    dokum_id: int, payload: OdemeIn, request: Request, db: DbDep, clock: ClockDep, user: Odeyici
) -> DokumOut:
    """Ödemeyi kaydeder ve dönemi KİLİTLER."""
    d = await db.get(PartnerSettlement, dokum_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Döküm bulunamadı")
    try:
        DOKUM.dogrula(d.status, "ODENDI")
    except IzinsizGecis as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # Tutar hiç kontrol edilmiyordu: 1.980,00 TL'lik bir döküm 1,00 TL ile
    # "ÖDENDİ" yapılıp KİLİTLENEBİLİYORDU. Dönem kilitlendiği için düzeltme
    # de mümkün olmuyor; montaj noktası 1.979 TL alacaklı kalıyordu.
    net = round(float(d.net_payable or 0), 2)
    if round(payload.amount, 2) != net and not payload.farkli_tutar_onayi:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Ödenen tutar dökümün netiyle uyuşmuyor (döküm {net:.2f}, girilen "
            f"{payload.amount:.2f}). Kasıtlıysa 'farkli_tutar_onayi' ile gerekçe girin.",
        )

    db.add(
        Payment(
            account_id=d.partner_id,
            direction="GIDEN",
            settlement_id=d.id,
            amount=payload.amount,
            paid_at=payload.paid_at,
            method=payload.method,
            reference=payload.reference,
            created_by=user.id,
        )
    )
    d.status = "ODENDI"
    d.paid_at = clock.now()
    if payload.partner_document_no:
        d.partner_document_no = payload.partner_document_no
        d.partner_document_date = payload.partner_document_date
    await svc.kilitle(db, d, clock)
    await audit.log(
        db,
        "partner_settlements",
        "ode",
        entity_id=d.id,
        new_value={
            "tutar": payload.amount,
            "tarih": str(payload.paid_at),
            "dokum_net": net,
            **(
                {"fark_gerekcesi": payload.fark_gerekcesi}
                if round(payload.amount, 2) != net
                else {}
            ),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, d)


# --- Belgeler ---------------------------------------------------------------


@router.get("/{dokum_id}/pdf")
async def dokum_pdf(dokum_id: int, db: DbDep, _: Okuyucu) -> Response:
    """Kurumsal şablonlu hak ediş dökümü PDF'i."""
    d = await db.get(PartnerSettlement, dokum_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Döküm bulunamadı")
    try:
        icerik = await belgeler.dokum_pdf(db, d)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    ad = f"hakedis-{d.period}-{d.partner_id}.pdf"
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{ad}"'},
    )


@router.post("/{dokum_id}/gonder", response_model=DokumOut)
async def dokum_gonder(
    dokum_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> DokumOut:
    """Dökümü montaj noktasına PDF ekiyle e-postalar."""
    d = await db.get(PartnerSettlement, dokum_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Döküm bulunamadı")
    hesap = await db.get(Account, d.partner_id)
    if hesap is None or not hesap.email:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{hesap.title if hesap else 'Montaj noktası'} için e-posta adresi kayıtlı değil. "
            "Hesap kartından ekleyin.",
        )
    try:
        pdf = await belgeler.dokum_pdf(db, d)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    try:
        await mail.gonder(
            db,
            alici=hesap.email,
            konu=f"Hak Ediş Dökümü · {d.period}",
            govde=(
                f"Sayın {hesap.title},\n\n"
                f"{d.period} dönemine ait hak ediş dökümünüz ektedir.\n"
                f"Net ödenecek tutar: {d.net_payable} TL\n\n"
                "İtirazlarınızı 7 gün içinde bildirmenizi rica ederiz.\n\n"
                "Denge Mobilite"
            ),
            ekler=[(f"hakedis-{d.period}.pdf", pdf, "application/pdf")],
        )
    except mail.MailKapali as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    d.sent_at = clock.now()
    await audit.log(
        db,
        "partner_settlements",
        "gonder",
        entity_id=d.id,
        new_value={"alici": hesap.email},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return await _cikti(db, d)


@router.get("/donem/{period}/excel")
async def odeme_listesi_excel(
    period: str,
    db: DbDep,
    user: Annotated[User, Depends(require_permission("rapor.disaaktar", "hakedis.gor"))],
) -> Response:
    """Muhasebe için ödeme listesi (kolon düzeni ayarlardaki şablona göre).

    Dışa aktarma, ekranın görüntüleme izniyle (`hakedis.gor`) aynı kapıdan
    geçer (rol testi S2): hak ediş ekranını göremeyen rol bayi ödeme listesini
    Excel olarak da alamaz. Şirket kapısı yönlendiricide (`MOBILITE_KAPISI`).
    """
    donem_dogrula(period)
    dokumler = (
        await db.scalars(
            select(PartnerSettlement)
            .where(PartnerSettlement.period == period)
            .order_by(PartnerSettlement.id)
        )
    ).all()
    kayitlar = []
    for d in dokumler:
        hesap = await db.get(Account, d.partner_id)
        ortak = await db.get(InstallationPartner, d.partner_id)
        matrah = float(d.gross_amount) - float(d.deduction_amount)
        kayitlar.append(
            {
                "cari_kodu": f"MN{d.partner_id:05d}",
                "unvan": hesap.title if hesap else "",
                "vkn": (hesap.tax_no if hesap else "") or "",
                "belge_tipi": (ortak.document_type if ortak else "BELIRSIZ"),
                "belge_no": d.partner_document_no or "",
                "belge_tarihi": d.partner_document_date.isoformat()
                if d.partner_document_date
                else "",
                "donem": d.period,
                "brut": float(d.gross_amount),
                "kesinti": float(d.deduction_amount),
                "matrah": matrah,
                "kdv": float(d.vat_amount),
                "stopaj": float(d.withholding_amount),
                "damga": float(d.stamp_tax_amount),
                "net": float(d.net_payable),
                "iban": (hesap.iban if hesap else "") or "",
                "aciklama": f"{d.period} hak edişi",
            }
        )

    sablon = await ayar_svc.get(db, "muhasebe_sablonu")
    icerik = await export_svc.sablonla_async(sablon, kayitlar, f"Hak Edis {period}")
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="hakedis-odeme-{period}.xlsx"'},
    )
