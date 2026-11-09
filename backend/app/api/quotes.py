"""Teklif yönetimi: versiyonlama, iskonto onayı, gönderim, online kabul.

**Dalga 2 (TS-140…148):** birimli (teknik servis) teklif aynı tabloda ve aynı
uçlardadır (`birim` dolu). Bütün tek kayıt uçları `svc.teklif_al` ile kaydı
alır: silinmiş ya da kapsam dışı teklif 404 ve hiçbir yazma yapılmaz (canlıda
`revize/iskonto-onayla/pdf/gonder/karar` kapsamı hiç sormuyordu, G1). Yazan
uçlar ayrıca alan ayrımına bakar: birimli teklife yalnız servis rolü/birim
üyesi, satış teklifine yalnız servis dışı rol yazar (B4).

Yeni uçlar: `PUT /{id}` (taslak düzenleme), `onaya-gonder`, `onayla`
(`teklif.onayla`), `geri-cevir`, `iptal`, `elle-gonderildi`, `gonderimler`,
`gecmis`, `ozet` (KPI kutuları), `disa-aktar.xlsx`. Satış akışı aynen: satış
teklifinde iç onay ve iptal yok (409), iskonto onayı ve karar canlı kuralla.
"""

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
    sayfala,
)
from app.config import get_config
from app.models import Account, Quote, QuoteLine, QuoteSend, QuoteVersion, ServiceOrder, User
from app.models.quote import KAYIP_NEDENLERI
from app.services import audit, belgeler, iskonto, mail
from app.services import export as export_svc
from app.services import quotes as svc
from app.services import settings as ayar_svc
from app.services.pdf import PdfUretilemedi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teklifler", tags=["teklif"])

Okuyucu = Annotated[User, Depends(require_permission("teklif.gor"))]
Yazici = Annotated[User, Depends(require_permission("teklif.yaz"))]
# S1.4: Satış Müdürü (`teklif.iskonto_onayla`, kendi limitine kadar) ya da
# Genel Müdür/ADMIN (`teklif.iskonto_ust_onay`, sınırsız).
Onaylayici = Annotated[
    User,
    Depends(require_any_permission("teklif.iskonto_onayla", "teklif.iskonto_ust_onay")),
]
IcOnaylayici = Annotated[User, Depends(require_permission("teklif.onayla"))]
# Excel: `teklif.gor` + (satış `rapor.disaaktar` | servis `servis_rapor.disaaktar`, KD-06).
_AKTARIM_KAPISI = Depends(require_any_permission("rapor.disaaktar", "servis_rapor.disaaktar"))

EPOSTA_KALIBI = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


@contextmanager
def _hatalar() -> Iterator[None]:
    """Servis hatası → HTTP (404 kapsam, 403 ikinci izin, 400 girdi, 409 kural)."""
    try:
        yield
    except svc.TeklifKapsamDisi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except svc.TeklifYetkiHatasi as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except svc.TeklifGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except svc.TeklifKuralHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ServisGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ServisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# --- Şemalar ------------------------------------------------------------------------


class KalemIn(BaseModel):
    item_type: str = "URUN"
    product_id: int | None = None
    # Şema 500'e kadar kabul eder; satış teklifinde 300 sınırı servis
    # katmanında (sipariş kalemi 300 — E07 kontrol B9).
    description: str | None = Field(default=None, max_length=500)
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
    # Birimli teklif: kalemin ait olduğu servis işi (çoklu PB bulgusu, K18).
    service_order_id: int | None = None


class TeklifIn(BaseModel):
    customer_id: int
    title: str | None = Field(default=None, max_length=200)
    currency: str = Field(default="TRY", min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0)
    fx_date: date | None = None
    valid_until: date | None = None
    kalemler: list[KalemIn] = Field(default_factory=list, max_length=200)
    # --- birimli (teknik servis) teklif ---
    birim: str | None = Field(default=None, max_length=20)
    service_order_id: int | None = None
    contact_id: int | None = None
    address_id: int | None = None
    # Kabulde açılacak servis işi türü (işe bağlı olmayan servis teklifi).
    servis_turu: str | None = Field(default=None, max_length=20)


class TeklifDuzenleIn(TeklifIn):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"customer_id": 1, "version": 1, "kalemler": []}]}
    )

    version: int


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
    service_order_id: int | None = None

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
    approved_at: datetime | None = None
    approved_by: int | None = None
    sent_channel: str | None = None
    sent_note: str | None = None
    public_url: str | None = None
    kalemler: list[KalemOut] = []

    model_config = {"from_attributes": True}


class TeklifOut(BaseModel):
    id: int
    quote_no: str
    customer_id: int
    customer_title: str | None = None
    owner_id: int | None
    owner_ad: str | None = None
    status: str
    title: str | None
    lost_reason: str | None
    # Kaybedilme nedeni kodu ve adı (S2.1).
    lost_reason_kod: str | None = None
    lost_reason_adi: str | None = None
    version: int
    onay_gerekiyor: bool = False
    # İskonto yetkisi (S1): oran = max(kalem, toplam), limit = hazırlayanın
    # limiti, kademe = onay kimde (SATIS_MUDURU | GENEL_MUDUR).
    iskonto_orani: Decimal | None = None
    iskonto_limiti: Decimal | None = None
    iskonto_onay_kademesi: str | None = None
    iskonto_onay_kademesi_adi: str | None = None
    guncel: VersiyonOut | None = None
    versiyon_sayisi: int = 0
    # --- Dalga 2 ---
    birim: str | None = None
    service_order_id: int | None = None
    so_no: str | None = None
    contact_id: int | None = None
    address_id: int | None = None
    servis_turu: str | None = None
    etkin_durum: str | None = None
    sonraki_durumlar: list[str] = []
    submitted_by: int | None = None
    submitted_by_ad: str | None = None
    submitted_at: datetime | None = None
    approved_by_ad: str | None = None
    cancel_reason: str | None = None
    cancelled_at: datetime | None = None
    teklif_no_gosterim: str | None = None
    uyarilar: list[str] = []

    model_config = {"from_attributes": True}


async def _ciktilar(db: DbDep, teklifler: list[Quote], clock: ClockDep) -> list[TeklifOut]:
    """Toplu çıktı: müşteri adları, sürüm sayıları, güncel sürüm ve kalemler
    tek sorgularla (liste N+1 üretmez)."""
    if not teklifler:
        return []
    bugun = svc.bugun_yerel(clock)
    idler = [t.id for t in teklifler]
    musteriler = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(
                    Account.id.in_({t.customer_id for t in teklifler})
                )
            )
        ).all()
    )
    sayilar = dict(
        (
            await db.execute(
                select(QuoteVersion.quote_id, func.count())
                .where(QuoteVersion.quote_id.in_(idler))
                .group_by(QuoteVersion.quote_id)
            )
        ).all()
    )
    surum_idleri = [t.current_version_id for t in teklifler if t.current_version_id]
    surumler = {
        v.id: v
        for v in (
            await db.scalars(select(QuoteVersion).where(QuoteVersion.id.in_(surum_idleri)))
        ).all()
    }
    kalemler: dict[int, list[QuoteLine]] = defaultdict(list)
    for k in (
        await db.scalars(
            select(QuoteLine)
            .where(QuoteLine.version_id.in_(surum_idleri))
            .order_by(QuoteLine.sort_order, QuoteLine.id)
        )
    ).all():
        kalemler[k.version_id].append(k)
    so_nolar = dict(
        (
            await db.execute(
                select(ServiceOrder.id, ServiceOrder.so_no).where(
                    ServiceOrder.id.in_({t.service_order_id for t in teklifler})
                )
            )
        ).all()
    )
    adlar = await svc.kullanici_adlari(
        db,
        {t.owner_id for t in teklifler}
        | {t.submitted_by for t in teklifler}
        | {v.approved_by for v in surumler.values()},
    )
    tablo = await iskonto.rol_limitleri(db)
    hazirlayanlar = await iskonto.hazirlayanlar(db, teklifler)
    taban = get_config().public_base_url
    sonuc = []
    for t in teklifler:
        out = TeklifOut.model_validate(t)
        out.customer_title = musteriler.get(t.customer_id)
        out.versiyon_sayisi = sayilar.get(t.id, 0)
        out.owner_ad = adlar.get(t.owner_id) if t.owner_id else None
        out.submitted_by_ad = adlar.get(t.submitted_by) if t.submitted_by else None
        out.so_no = so_nolar.get(t.service_order_id) if t.service_order_id else None
        out.lost_reason_adi = KAYIP_NEDENLERI.get(t.lost_reason_kod or "")
        v = surumler.get(t.current_version_id) if t.current_version_id else None
        out.etkin_durum = svc.etkin_durum(t, v, bugun)
        out.sonraki_durumlar = svc.sonraki_durumlar(t, v, bugun)
        if v is not None:
            vout = VersiyonOut.model_validate(v)
            vout.kalemler = [KalemOut.model_validate(k) for k in kalemler[v.id]]
            if v.public_token:
                vout.public_url = svc.public_url(taban, v.public_token)
            out.guncel = vout
            d = iskonto.durum_hesapla(v, hazirlayanlar.get(t.owner_id or 0), tablo)
            out.onay_gerekiyor = d.onay_bekliyor
            out.iskonto_orani = d.oran
            out.iskonto_limiti = d.limit
            out.iskonto_onay_kademesi = d.kademe
            out.iskonto_onay_kademesi_adi = d.kademe_adi
            out.approved_by_ad = adlar.get(v.approved_by) if v.approved_by else None
            out.teklif_no_gosterim = svc.teklif_no_gosterim(t, v)
        sonuc.append(out)
    return sonuc


async def _cikti(
    db: DbDep, t: Quote, clock: ClockDep, *, uyarilar: list[str] | None = None
) -> TeklifOut:
    await db.refresh(t)
    out = (await _ciktilar(db, [t], clock))[0]
    out.uyarilar = uyarilar or []
    return out


async def _al(db: DbDep, teklif_id: int, user: User, *, yazma: bool = False) -> Quote:
    with _hatalar():
        return await svc.teklif_al(db, teklif_id, user, yazma=yazma)


async def _guncel_versiyon(db: DbDep, t: Quote) -> QuoteVersion:
    with _hatalar():
        return await svc.guncel_versiyon(db, t)


# --- Liste, özet, Excel (TS-148, E07-18/19) ------------------------------------------


def _filtre(
    durum: str | None,
    musteri_id: int | None,
    tur: str | None,
    birim: str | None,
    kpi: str | None,
    tarih_bas: date | None,
    tarih_bit: date | None,
    tarih_alani: str,
    servis_isi_id: int | None,
    hazirlayan_id: int | None,
    q: str | None,
    idler: list[int] | None = None,
    kesif: str | None = None,
) -> svc.TeklifFiltresi:
    return svc.TeklifFiltresi(
        durum=durum,
        musteri_id=musteri_id,
        tur=tur,
        birim=birim,
        kpi=kpi,
        tarih_bas=tarih_bas,
        tarih_bit=tarih_bit,
        tarih_alani=tarih_alani,
        servis_isi_id=servis_isi_id,
        hazirlayan_id=hazirlayan_id,
        q=(q or "").strip() or None,
        idler=idler or [],
        kesif=kesif,
    )


@router.get("/belge-basligi")
async def belge_basligi(db: DbDep, _: Okuyucu) -> dict:
    """Teklif formundaki CANLI A4 önizlemesinin başlık bilgileri.

    Önizleme ile basılan PDF aynı kaynaktan beslenir; ayrı yerlerden
    okunsaydı ekranda görünen teklifle müşteriye giden teklif ayrışırdı.
    """
    ayarlar = await belgeler.ayar_haritasi(db)
    return {
        "firma": belgeler.firma_bilgisi(ayarlar),
        "sartlar": ayarlar.get("teklif_ticari_sartlar") or belgeler.VARSAYILAN_SARTLAR,
        "kdv_varsayilan": float(ayarlar.get("kdv_oran_varsayilan") or 0.20),
        "birimli_kdv_oranlari": [float(o) for o in svc.BIRIMLI_KDV_ORANLARI],
    }


@router.get("", response_model=list[TeklifOut])
async def listele(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    musteri_id: int | None = None,
    tur: Literal["SATIS", "SERVIS"] | None = None,
    birim: str | None = None,
    kpi: str | None = None,
    tarih_bas: date | None = None,
    tarih_bit: date | None = None,
    tarih_alani: Literal["olusturma", "gonderim"] = "olusturma",
    servis_isi_id: int | None = None,
    hazirlayan_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    kesif: Literal["TAMAMLANDI", "ACIK"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TeklifOut]:
    """Sunucu tarafı süzgeç + sayfalama; toplam `X-Toplam-Kayit` başlığında
    (gövde canlıdaki gibi dizi). Canlıdaki "yalnız son 50" sınırı kalktı (G7)."""
    f = _filtre(
        durum, musteri_id, tur, birim, kpi, tarih_bas, tarih_bit, tarih_alani,
        servis_isi_id, hazirlayan_id, q, kesif=kesif,
    )  # fmt: skip
    with _hatalar():
        bugun = svc.bugun_yerel(clock)
        takip = int(await ayar_svc.get(db, "teklif_takip_uyari_gun"))
        stmt = svc.liste_sorgusu(user, f, bugun, takip)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _ciktilar(db, [r[0] for r in satirlar], clock)


@router.get("/ozet")
async def ozet(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    tur: Literal["SATIS", "SERVIS"] | None = None,
    birim: str | None = None,
    musteri_id: int | None = None,
    servis_isi_id: int | None = None,
    hazirlayan_id: int | None = None,
) -> dict:
    """Tıklanabilir KPI kutuları; her sayı `?kpi=<kod>` listesinin toplamına eşit."""
    f = _filtre(
        None, musteri_id, tur, birim, None, None, None, "olusturma",
        servis_isi_id, hazirlayan_id, None,
    )  # fmt: skip
    with _hatalar():
        sayilar = await svc.ozet(db, user, f, clock)
    return {
        "kpi": [
            {"kod": k, "baslik": svc.KPI_ADLARI[k], "deger": sayilar[k]} for k in svc.KPI_KODLARI
        ],
        "takip_gun": int(await ayar_svc.get(db, "teklif_takip_uyari_gun")),
    }


@router.get("/disa-aktar.xlsx", dependencies=[_AKTARIM_KAPISI])
async def disa_aktar(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    musteri_id: int | None = None,
    tur: Literal["SATIS", "SERVIS"] | None = None,
    birim: str | None = None,
    kpi: str | None = None,
    tarih_bas: date | None = None,
    tarih_bit: date | None = None,
    tarih_alani: Literal["olusturma", "gonderim"] = "olusturma",
    servis_isi_id: int | None = None,
    hazirlayan_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    idler: Annotated[list[int] | None, Query(max_length=500)] = None,
) -> Response:
    """Liste süzgeçleriyle AYNI sorgu (satır sayısı = `X-Toplam-Kayit`).
    `idler` çoklu seçimle "Seçilileri Excel'e aktar" içindir."""
    f = _filtre(
        durum, musteri_id, tur, birim, kpi, tarih_bas, tarih_bit, tarih_alani,
        servis_isi_id, hazirlayan_id, q, idler,
    )  # fmt: skip
    with _hatalar():
        bugun = svc.bugun_yerel(clock)
        takip = int(await ayar_svc.get(db, "teklif_takip_uyari_gun"))
        stmt = svc.liste_sorgusu(user, f, bugun, takip)
    teklifler = list((await db.scalars(stmt)).unique().all())
    ciktilar = await _ciktilar(db, teklifler, clock)
    basliklar = [
        "No", "Rev", "Birim", "Müşteri", "Servis İşi", "Durum", "Etkin Durum", "Hazırlayan",
        "Onaylayan", "Geçerlilik", "Ara Toplam", "İskonto", "KDV", "Genel Toplam", "Döviz",
        "Gönderim Tarihi", "Karar Tarihi",
    ]  # fmt: skip
    satirlar = []
    for o in ciktilar:
        g = o.guncel
        karar = (g.accepted_at or g.rejected_at) if g else None
        satirlar.append(
            [
                o.quote_no,
                f"R{g.version_no - 1}" if g else "",
                o.birim or "Satış",
                o.customer_title,
                o.so_no,
                svc.DURUM_ADLARI.get(o.status, o.status),
                svc.DURUM_ADLARI.get(o.etkin_durum or "", o.etkin_durum),
                o.owner_ad,
                o.approved_by_ad,
                g.valid_until if g else None,
                g.subtotal if g else None,
                g.discount_total if g else None,
                g.vat_total if g else None,
                g.grand_total if g else None,
                g.currency if g else None,
                g.sent_at.date() if g and g.sent_at else None,
                karar.date() if karar else None,
            ]
        )
    await audit.log(
        db,
        "quotes",
        "disa_aktar",
        new_value={"satir": len(satirlar), "tur": tur, "birim": birim, "kpi": kpi},
        user_id=user.id,
    )
    await db.commit()
    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, satirlar, "Teklifler"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Teklifler.xlsx"'},
    )


@router.get("/{teklif_id}", response_model=TeklifOut)
async def getir(teklif_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> TeklifOut:
    t = await _al(db, teklif_id, user)
    return await _cikti(db, t, clock)


# --- Oluşturma ve taslak düzenleme (TS-140/148) -----------------------------------------


def _baslik(payload: TeklifIn) -> svc.BaslikGirdisi:
    return svc.BaslikGirdisi(
        customer_id=payload.customer_id,
        birim=payload.birim,
        service_order_id=payload.service_order_id,
        contact_id=payload.contact_id,
        address_id=payload.address_id,
        currency=payload.currency,
        fx_rate=payload.fx_rate,
        valid_until=payload.valid_until,
        servis_turu=payload.servis_turu,
    )


@router.post("", response_model=TeklifOut, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: TeklifIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    baslik = _baslik(payload)
    with _hatalar():
        so = await svc.baslik_dogrula(db, user, baslik, clock)
    sira = (await db.scalar(select(Quote.id).order_by(Quote.id.desc()).limit(1)) or 0) + 1
    teklif = Quote(
        quote_no=f"TKF{clock.now():%Y}-{sira:05d}",
        customer_id=payload.customer_id,
        owner_id=user.id,
        title=payload.title,
        created_by=user.id,
        birim=baslik.birim,
        service_order_id=so.id if so is not None else None,
        contact_id=baslik.contact_id,
        address_id=baslik.address_id,
        servis_turu=baslik.servis_turu,
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

    with _hatalar():
        await svc.kalemleri_yaz(
            db, user, versiyon, [k.model_dump() for k in payload.kalemler], teklif=teklif
        )
        await svc.versiyon_hesapla(db, versiyon)
        uyarilar = await svc.bekleme_bagla(db, teklif, user=user, clock=clock, beklet=False)

    await audit.log(
        db,
        "quotes",
        "olustur",
        entity_id=teklif.id,
        new_value={
            "no": teklif.quote_no,
            "musteri": payload.customer_id,
            "birim": teklif.birim,
            "servis_isi": teklif.service_order_id,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, teklif, clock, uyarilar=uyarilar)


@router.put("/{teklif_id}", response_model=TeklifOut)
async def duzenle(
    teklif_id: int,
    payload: TeklifDuzenleIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> TeklifOut:
    """TASLAK teklifi yerinde düzenler (sürüm sayısı artmaz; başlık `version`
    artar). Diğer durumlarda 409 — gönderilmiş teklif revizyonla değişir."""
    t = await _al(db, teklif_id, user, yazma=True)
    with _hatalar():
        eski, yeni = await svc.taslak_guncelle(
            db,
            t,
            user,
            baslik=_baslik(payload),
            title=payload.title,
            fx_date=payload.fx_date,
            kalemler=[k.model_dump() for k in payload.kalemler],
            version=payload.version,
            clock=clock,
        )
    await audit.log(
        db,
        "quotes",
        "guncelle",
        entity_id=t.id,
        old_value={"tutar": str(eski)},
        new_value={"tutar": str(yeni)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, t, clock)


class RevizyonIn(BaseModel):
    kalemler: list[KalemIn] = Field(max_length=200)
    valid_until: date | None = None
    notes: str | None = None


@router.post("/{teklif_id}/revize", response_model=TeklifOut)
async def revize_et(
    teklif_id: int, payload: RevizyonIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    """Yeni versiyon açar. Eski versiyon KİLİTLENİR ve görüntülenebilir kalır.

    Birimli teklifte yalnız gönderilmiş/ret/süresi dolmuş iken; durum TASLAK
    olur ve yeniden iç onay gerekir (kontrol B2). Satışta canlı davranış.
    """
    t = await _al(db, teklif_id, user, yazma=True)
    onceki = await _guncel_versiyon(db, t)
    with _hatalar():
        hedef = await svc.revize_kurali(t, onceki, svc.bugun_yerel(clock))
        if t.birim and payload.valid_until and payload.valid_until < svc.bugun_yerel(clock):
            raise svc.TeklifGirdiHatasi("Geçerlilik tarihi geçmiş bir gün olamaz")
    yeni = await svc.yeni_versiyon(db, t, clock=clock, kaynak=onceki)

    # Kaynak versiyondan kopyalanan kalemler silinir, yenileri yazılır.
    for k in (await db.scalars(select(QuoteLine).where(QuoteLine.version_id == yeni.id))).all():
        await db.delete(k)
    await db.flush()
    with _hatalar():
        await svc.kalemleri_yaz(
            db, user, yeni, [k.model_dump() for k in payload.kalemler], teklif=t
        )
    if payload.valid_until:
        yeni.valid_until = payload.valid_until
    yeni.notes = payload.notes
    await svc.versiyon_hesapla(db, yeni)

    if hedef == "TASLAK":
        with _hatalar():
            await svc.gecis(
                db, t, "TASLAK", user_id=user.id, neden="Revizyon", ip=client_ip(request)
            )
    else:
        t.status = hedef
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
    return await _cikti(db, t, clock)


@router.post("/{teklif_id}/iskonto-onayla", response_model=TeklifOut)
async def iskonto_onayla(
    teklif_id: int, request: Request, db: DbDep, clock: ClockDep, user: Onaylayici
) -> TeklifOut:
    t = await _al(db, teklif_id, user, yazma=True)
    if svc.birimli_mi(t):
        # Yan kapı (kontrol B2): satış müdürünün iskonto onayı servis teklifinin
        # iç onayını atlayamaz.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Servis teklifinde iskonto iç onayla birlikte verilir; 'Onayla' kullanın",
        )
    v = await _guncel_versiyon(db, t)
    d = await iskonto.durum(db, t, v)
    if not d.onay_gerekli:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu teklifte onay gerektiren iskonto yok")
    if d.onaylandi:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu sürümün iskontosu zaten onaylı")
    if not iskonto.onaylayabilir_mi(user, d.oran, await iskonto.rol_limitleri(db)):
        # Kademeli onay (S1.4): müdür kendi limitinin üstünü onaylayamaz.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"%{d.oran} iskonto onay limitinizi aşıyor; Genel Müdür ya da sistem "
            "yöneticisi onaylar.",
        )
    v.discount_approved_by = user.id
    v.discount_approved_at = clock.now()
    if t.status == "ONAY_BEKLIYOR":
        t.status = "TASLAK"
    await audit.log(
        db,
        "quotes",
        "iskonto.onayla",
        entity_id=t.id,
        new_value={
            "iskonto_yuzde": str(d.oran),
            "limit": str(d.limit),
            "kademe": d.kademe,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, t, clock)


@router.get("/{teklif_id}/pdf")
async def teklif_pdf(teklif_id: int, db: DbDep, user: Okuyucu) -> Response:
    t = await _al(db, teklif_id, user)
    v = await _guncel_versiyon(db, t)
    try:
        icerik = await svc.teklif_pdf(db, t, v)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{t.quote_no}.pdf"'},
    )


# --- İç onay akışı (TS-141) ----------------------------------------------------------


class OnayaGonderIn(BaseModel):
    beklet: bool = False


class NedenIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"neden": "Fiyat güncellenecek"}]})

    neden: str | None = Field(default=None, max_length=300)


@router.post("/{teklif_id}/onaya-gonder", response_model=TeklifOut)
async def onaya_gonder(
    teklif_id: int,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
    payload: OnayaGonderIn | None = None,
) -> TeklifOut:
    t = await _al(db, teklif_id, user, yazma=True)
    with _hatalar():
        uyarilar = await svc.onaya_gonder(
            db,
            t,
            user=user,
            clock=clock,
            beklet=bool(payload and payload.beklet),
            ip=client_ip(request),
        )
    await db.commit()
    return await _cikti(db, t, clock, uyarilar=uyarilar)


@router.post("/{teklif_id}/onayla", response_model=TeklifOut)
async def onayla(
    teklif_id: int, request: Request, db: DbDep, clock: ClockDep, user: IcOnaylayici
) -> TeklifOut:
    t = await _al(db, teklif_id, user, yazma=True)
    with _hatalar():
        await svc.onayla(db, t, user=user, clock=clock, ip=client_ip(request))
    await db.commit()
    return await _cikti(db, t, clock)


@router.post("/{teklif_id}/geri-cevir", response_model=TeklifOut)
async def geri_cevir(
    teklif_id: int,
    payload: NedenIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IcOnaylayici,
) -> TeklifOut:
    t = await _al(db, teklif_id, user, yazma=True)
    with _hatalar():
        await svc.geri_cevir(db, t, user=user, neden=payload.neden, ip=client_ip(request))
    await db.commit()
    return await _cikti(db, t, clock)


@router.post("/{teklif_id}/iptal", response_model=TeklifOut)
async def iptal(
    teklif_id: int,
    payload: NedenIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> TeklifOut:
    """Birimli teklif iptali (neden zorunlu). KABUL'den iptal `teklif.onayla`
    ister ve iş faturaya iletildiyse 409 (E07-D04)."""
    t = await _al(db, teklif_id, user, yazma=True)
    with _hatalar():
        uyarilar = await svc.iptal(
            db, t, user=user, clock=clock, neden=payload.neden, ip=client_ip(request)
        )
    await db.commit()
    return await _cikti(db, t, clock, uyarilar=uyarilar)


@router.get("/{teklif_id}/gecmis")
async def gecmis(teklif_id: int, db: DbDep, user: Okuyucu) -> list[dict]:
    """Durum ve eylem geçmişi (`audit_logs`; ayrı tablo yok, K16)."""
    t = await _al(db, teklif_id, user)
    return await svc.gecmis(db, t)


# --- Gönderim (TS-142) ---------------------------------------------------------------


class GonderIn(BaseModel):
    # Geriye uyumlu tek alıcı; yeni istemci `alicilar` gönderir (en çok 3).
    alici: str | None = Field(default=None, pattern=EPOSTA_KALIBI, max_length=254)
    alicilar: list[Annotated[str, Field(pattern=EPOSTA_KALIBI, max_length=254)]] = Field(
        default_factory=list
    )
    mesaj: str | None = Field(default=None, max_length=2000)


async def _gonderim_izni(db: DbDep, t: Quote, v: QuoteVersion, *, yeniden_serbest: bool) -> bool:
    """Gönderim kuralı; dönüş = bu ilk gönderim mi (durum değişecek mi).

    Birimli: ONAYLANDI ilk gönderimdir; GONDERILDI/GORUNTULENDI yeniden
    gönderimdir (durum değişmez). Satış: iskonto onayı kuralı aynen (elle
    gönderim de bu kuralı atlayamaz, E07-05).
    """
    if svc.birimli_mi(t):
        if t.status == "ONAYLANDI":
            return True
        if t.status in svc.YENIDEN_GONDERILEBILIR and yeniden_serbest:
            return False
        raise HTTPException(status.HTTP_409_CONFLICT, "Teklif onaylanmadan gönderilemez")
    d = await iskonto.durum(db, t, v)
    if d.onay_bekliyor:
        raise HTTPException(status.HTTP_409_CONFLICT, _onay_mesaji(d))
    return t.status not in ("GONDERILDI", "GORUNTULENDI")


def _onay_mesaji(d: iskonto.IskontoDurumu) -> str:
    return (
        f"%{d.oran} iskonto onay eşiğini aşıyor (limit %{d.limit}); "
        f"{d.kademe_adi} onayı olmadan gönderilemez."
    )


async def _gonderim_hizi_denetle(db: DbDep, user: User, clock: ClockDep) -> None:
    """Kullanıcı başına dakikada en çok `teklif_gonderim_dakika_limiti` (10)
    e-posta gönderimi (TS-215, E07-25); aşılırsa 429 ve HİÇBİR ŞEY yazılmaz.

    Sayım `quote_sends` üzerinden (başarısız deneme de SMTP'ye gitmiştir,
    sayılır). Tek API kopyası ve tek worker olduğu için DB sayımı yeterli;
    pencere Clock ile ölçülür (`_gonderim_kaydet` satırın zamanını
    Clock'tan yazar), böylece FakeClock testinde de aynı kural geçerlidir.
    """
    from datetime import timedelta

    sinir = int(await ayar_svc.get(db, "teklif_gonderim_dakika_limiti"))
    sayi = await db.scalar(
        select(func.count())
        .select_from(QuoteSend)
        .where(
            QuoteSend.created_by == user.id,
            QuoteSend.kanal == "EPOSTA",
            QuoteSend.created_at > clock.now() - timedelta(seconds=60),
        )
    )
    if (sayi or 0) >= sinir:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Çok fazla gönderim; bir dakika sonra tekrar deneyin",
        )


async def _gonderim_kaydet(db: DbDep, clock: ClockDep, *args, **kw) -> QuoteSend:
    """`svc.gonderim_kaydet` + satır zamanı Clock'tan (hız sınırı penceresi;
    elle gönderim de aynı yoldan yazılır ki günlük sırası tek saatten gelsin)."""
    kayit = await svc.gonderim_kaydet(db, *args, **kw)
    kayit.created_at = clock.now()
    return kayit


@router.post("/{teklif_id}/gonder", response_model=TeklifOut)
async def gonder(
    teklif_id: int, payload: GonderIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    """Teklifi PDF ekiyle e-postalar ve versiyonu kilitler (en çok 3 alıcı,
    gönderene CC). Her deneme `quote_sends`'e yazılır — başarısız deneme de
    (durum değişmeden) commit edilir; hata ayrıntısı yalnız sunucu logunda.
    Dakikada 10 gönderimden fazlası 429 (TS-215); e-postadaki PDF'in
    SHA-256'sı gönderim satırında (`pdf_sha256`, E07-09)."""
    t = await _al(db, teklif_id, user, yazma=True)
    v = await _guncel_versiyon(db, t)
    await _gonderim_hizi_denetle(db, user, clock)

    if not svc.birimli_mi(t):
        d = await iskonto.durum(db, t, v)
        if d.onay_bekliyor:
            # Canlı davranış: limit üstü iskontolu satış teklifi onaya düşer
            # (kademe: satış müdürü ya da genel müdür, S1.4).
            t.status = "ONAY_BEKLIYOR"
            await db.commit()
            raise HTTPException(status.HTTP_409_CONFLICT, _onay_mesaji(d))
    ilk = await _gonderim_izni(db, t, v, yeniden_serbest=True)

    musteri = await db.get(Account, t.customer_id)
    alicilar = list(dict.fromkeys([*([payload.alici] if payload.alici else []), *payload.alicilar]))
    if not alicilar:
        irtibat = None
        if t.contact_id:
            from app.models import Contact

            irtibat = await db.get(Contact, t.contact_id)
        varsayilan = (irtibat.email if irtibat else None) or (musteri.email if musteri else None)
        alicilar = [varsayilan] if varsayilan else []
    if not alicilar:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Müşterinin e-posta adresi kayıtlı değil. Hesap kartından ekleyin "
            "veya gönderim ekranında adres girin.",
        )
    if len(alicilar) > svc.AZAMI_ALICI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"En çok {svc.AZAMI_ALICI} alıcıya gönderilebilir"
        )
    cc = [user.email] if getattr(user, "email", None) else []
    try:
        pdf = await svc.teklif_pdf(db, t, v)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    link = svc.public_url(get_config().public_base_url, v.public_token or "")
    no = svc.teklif_no_gosterim(t, v)
    try:
        await mail.gonder(
            db,
            alici=alicilar,
            cc=cc or None,
            konu=f"Fiyat Teklifi · {no}",
            govde=(
                (f"{payload.mesaj}\n\n" if payload.mesaj else "")
                + f"Sayın {musteri.title if musteri else ''},\n\n"
                f"{no} numaralı teklifimiz ektedir.\n"
                + (f"Geçerlilik: {v.valid_until:%d.%m.%Y}\n" if v.valid_until else "")
                + f"Genel toplam: {v.grand_total} {v.currency}\n\n"
                f"Teklifi görüntülemek ve yanıtlamak için: {link}\n\n"
                "Denge Mobilite"
            ),
            ekler=[(f"{no}.pdf", pdf, "application/pdf")],
        )
    except mail.MailKapali as exc:
        # Başarısız deneme görünür olsun: günlük satırı commit edilir, teklif
        # durumu değişmez. Kullanıcı genel mesaj alır (ayrıntı logda).
        await _gonderim_kaydet(
            db,
            clock,
            t,
            v,
            kanal="EPOSTA",
            sonuc="HATA",
            user_id=user.id,
            alicilar=alicilar,
            cc=cc[0] if cc else None,
            hata_ozeti=exc.sinif,
            pdf=pdf,
        )
        await db.commit()
        mesaj = str(exc) if exc.sinif == "SMTP_KAPALI" else mail.GENEL_HATA_MESAJI
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, mesaj) from exc

    await _gonderim_kaydet(
        db,
        clock,
        t,
        v,
        kanal="EPOSTA",
        sonuc="BASARILI",
        user_id=user.id,
        alicilar=alicilar,
        cc=cc[0] if cc else None,
        pdf=pdf,
    )
    if ilk:
        v.sent_at = clock.now()
        v.is_locked = True
        v.sent_channel = "EPOSTA"
        if svc.birimli_mi(t):
            with _hatalar():
                await svc.gecis(
                    db, t, "GONDERILDI", user_id=user.id, kanal="EPOSTA", ip=client_ip(request)
                )
        else:
            t.status = "GONDERILDI"
    await audit.log(
        db,
        "quotes",
        "gonder",
        entity_id=t.id,
        new_value={
            "alici": alicilar,
            "versiyon": v.version_no,
            "kanal": "EPOSTA",
            "yeniden": not ilk,
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return await _cikti(db, t, clock)


class ElleGonderIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"examples": [{"kanal": "ELDEN", "not": "Müşteriye elden verildi"}]},
    )

    kanal: Literal["ELDEN", "KARGO", "HARICI_EPOSTA", "DIGER"]
    not_: str = Field(default="", alias="not", max_length=300)


@router.post("/{teklif_id}/elle-gonderildi", response_model=TeklifOut)
async def elle_gonderildi(
    teklif_id: int,
    payload: ElleGonderIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> TeklifOut:
    """SMTP yokken (ya da elden/kargoyla) gönderildi işareti: kanal + not
    zorunlu; onay kuralı `gonder` ile aynı. Sonrasında public link karar alır."""
    t = await _al(db, teklif_id, user, yazma=True)
    v = await _guncel_versiyon(db, t)
    notlar = payload.not_.strip()
    if len(notlar) < 3:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gönderim notu zorunlu (en az 3 karakter)")
    ilk = await _gonderim_izni(db, t, v, yeniden_serbest=True)
    try:
        pdf: bytes | None = await svc.teklif_pdf(db, t, v)
    except PdfUretilemedi:
        pdf = None  # özet yazılamaz; gönderim kaydı yine düşer
    # Zaman Clock'tan: gönderim günlüğünün sırası e-posta satırlarıyla tutarlı kalsın.
    await _gonderim_kaydet(
        db,
        clock,
        t,
        v,
        kanal=payload.kanal,
        sonuc="BASARILI",
        user_id=user.id,
        pdf=pdf,
        notlar=notlar,
    )
    if ilk:
        v.sent_at = clock.now()
        v.is_locked = True
        v.sent_channel = payload.kanal
        v.sent_note = notlar
        if svc.birimli_mi(t):
            with _hatalar():
                await svc.gecis(
                    db,
                    t,
                    "GONDERILDI",
                    user_id=user.id,
                    kanal=payload.kanal,
                    neden=notlar,
                    ip=client_ip(request),
                )
        else:
            t.status = "GONDERILDI"
    await audit.log(
        db,
        "quotes",
        "elle_gonderildi",
        entity_id=t.id,
        new_value={
            "kanal": payload.kanal,
            "neden": notlar,
            "versiyon": v.version_no,
            "yeniden": not ilk,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, t, clock)


class GonderimOut(BaseModel):
    id: int
    version_id: int
    kanal: str
    alicilar: list[str] | None
    cc: str | None
    sonuc: str
    hata_ozeti: str | None
    pdf_sha256: str | None
    notlar: str | None
    created_at: datetime
    created_by: int | None
    gonderen: str | None = None

    model_config = {"from_attributes": True}


@router.get("/{teklif_id}/gonderimler", response_model=list[GonderimOut])
async def gonderimler(teklif_id: int, db: DbDep, user: Okuyucu) -> list[GonderimOut]:
    t = await _al(db, teklif_id, user)
    kayitlar = (
        await db.scalars(
            select(QuoteSend)
            .where(QuoteSend.quote_id == t.id)
            .order_by(QuoteSend.created_at, QuoteSend.id)
        )
    ).all()
    adlar = await svc.kullanici_adlari(db, {k.created_by for k in kayitlar})
    sonuc = []
    for k in kayitlar:
        out = GonderimOut.model_validate(k)
        out.gonderen = adlar.get(k.created_by) if k.created_by else None
        sonuc.append(out)
    return sonuc


# --- Karar (TS-141/147) --------------------------------------------------------------


class KararIn(BaseModel):
    kabul: bool
    red_nedeni: str | None = Field(default=None, max_length=300)
    # Kaybedilme nedeni kodu (S2.1, `KAYIP_NEDENLERI`); DIGER'de açıklama
    # (`red_nedeni`) zorunlu. Kodsuz ret DIGER + açıklama sayılır.
    kayip_nedeni_kod: str | None = Field(default=None, max_length=20)


@router.post("/{teklif_id}/karar", response_model=TeklifOut)
async def karar(
    teklif_id: int, payload: KararIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> TeklifOut:
    """Kabul/red kaydını ELLE işaretler.

    Online kabul dışa açık sunucu gerektirdiği için yerel kurulumda kullanılan
    yol budur; kararın linkten mi ekipten mi geldiği ayrıca kaydedilir.
    Birimli teklifte makine (TASLAK→KABUL 409) ve süre denetlenir; kabulde
    gelir aktarılır, PB bulgusunun düzeltici işi açılır, teklif beklemesi
    kapanır. Satış teklifinde canlı davranış değişmez.
    """
    t = await _al(db, teklif_id, user, yazma=True)
    if not payload.kabul:
        with _hatalar():
            svc.kayip_nedeni_dogrula(payload.kayip_nedeni_kod, payload.red_nedeni)
    v = await _guncel_versiyon(db, t)
    uyarilar: list[str] = []
    with _hatalar():
        if svc.birimli_mi(t):
            from app.services.teknik_servis import maliyet

            svc.karar_dogrula(t, v, svc.bugun_yerel(clock), kabul=payload.kabul)
            if payload.kabul:
                await maliyet.fatura_kilidi_dogrula(db, t)
        await svc.karar_ver(
            db,
            v,
            kabul=payload.kabul,
            clock=clock,
            kanal="ELLE",
            red_nedeni=payload.red_nedeni,
            kayip_kod=payload.kayip_nedeni_kod,
        )
        if payload.kabul:
            uyarilar = await svc.kabul_sonrasi(db, t, user=user, clock=clock)
        else:
            uyarilar = await svc.ret_sonrasi(db, t, user=user, clock=clock)
    await audit.log(
        db,
        "quotes",
        "karar",
        entity_id=t.id,
        new_value={
            "kabul": payload.kabul,
            "kanal": "ELLE",
            "neden": payload.red_nedeni,
            "kayip_kod": t.lost_reason_kod if not payload.kabul else None,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _cikti(db, t, clock, uyarilar=uyarilar)
