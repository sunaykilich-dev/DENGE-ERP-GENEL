"""Servis maliyet ve gelir uçları (TS-145, TS-146, TS-149).

Yollar (`/api/teknik-servis/maliyet` öneki):

- `GET /tarifeler` (maliyet.gor) — kullanıcının birimlerinin işçilik tarifeleri
- `POST /tarifeler` (maliyet.gor + maliyet.yaz) — geçmiş tarih `sistem.ayar` + gerekçe
- `POST /tarifeler/kapat` (maliyet.gor + maliyet.yaz) — henüz başlamamış tarifeyi
  boş aralıkla kapatır (kimlik GÖVDEDE: tarife birim kapsamlıdır ama kapsam
  taramasının yol parametresi sözleşmesinde karşılığı yok; gövdeli uçta kapsam
  servis içinde denetlenir, dışı 404)
- `GET /isler/{so_id}` (maliyet.gor) — iş finansı (tek kaynak `is_finansi`)
- `PUT /isler/{so_id}/gelir`, `PUT /isler/{so_id}/diger-maliyet` (maliyet.gor +
  maliyet.yaz) — fatura devrinden sonra 409
- `GET /isler/{so_id}/gecmis` (maliyet.gor) — gelir/maliyet değişiklik geçmişi
- `GET /analiz` (maliyet.gor + servis_rapor.gor) — dönem zorunlu, ≤ 12 ay

İzinler (plan §1.3, KD-11): `maliyet.gor` rol kümesi değişmez; `maliyet.yaz`
yalnız ADMIN rolünde, ihtiyaç sahibine kişi bazlı istisna. Her `{so_id}`
ucunda iş kapsam dışı → 404 ve hiçbir yazma yapılmaz. Bütün çıktılar zaten
`maliyet.gor` ister; iş detayı ve listeler fiyat/maliyet anahtarını başka bir
uçta TAŞIMAZ (servis işi çıktısı yapısal olarak ayrı).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import ServiceLaborRate, ServiceOrder, User
from app.services.teknik_servis import kapsam
from app.services.teknik_servis import maliyet as svc
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teknik-servis/maliyet", tags=["servis-maliyet"])

MaliyetOkuyucu = Annotated[User, Depends(require_permission("maliyet.gor"))]
MaliyetYazici = Annotated[User, Depends(require_permission("maliyet.gor", "maliyet.yaz"))]
AnalizOkuyucu = Annotated[User, Depends(require_permission("maliyet.gor", "servis_rapor.gor"))]


@contextmanager
def _hatalar() -> Iterator[None]:
    try:
        yield
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ServisGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ServisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


async def _is_al(db: DbDep, so_id: int, user: User) -> ServiceOrder:
    """Kapsam dışı/silinmiş iş → 404 (yazmadan ÖNCE)."""
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    return so


# --- Şemalar ------------------------------------------------------------------------


class TarifeOut(BaseModel):
    id: int
    version: int
    birim: str
    valid_from: date
    valid_to: date | None
    hourly_cost: Decimal
    gerekce: str | None
    created_at: datetime
    created_by: int | None
    giren: str | None = None
    kapatildi: bool = False

    model_config = {"from_attributes": True}


class TarifeIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"birim": "GUVENLIK", "valid_from": "2027-01-01", "hourly_cost": 500}]
        }
    )

    birim: str = Field(max_length=20)
    valid_from: date
    hourly_cost: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    gerekce: str | None = Field(default=None, max_length=300)


class TarifeKapatIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"tarife_id": 1, "version": 1, "gerekce": "Yanlış tarihle girildi"}]
        }
    )

    tarife_id: int
    version: int
    gerekce: str = Field(max_length=300)


class GelirIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [{"kaynak": "ELLE", "tutar": 1000, "not": "Elle gelir", "version": 1}]
        },
    )

    kaynak: Literal["ELLE", "UCRETSIZ_GARANTI", "SOZLESME", "TEKLIF", "YOK"]
    tutar: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    not_: str | None = Field(default=None, alias="not", max_length=1000)
    version: int | None = None


class DigerMaliyetIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"examples": [{"tutar": 250, "not": "Konaklama", "version": 1}]},
    )

    tutar: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    not_: str | None = Field(default=None, alias="not", max_length=1000)
    version: int | None = None


class IsFinansiOut(BaseModel):
    so_id: int
    so_no: str
    birim: str
    tur: str
    sure_dk: int | None
    iscilik: Decimal | None
    iscilik_durumu: str
    malzeme: Decimal | None
    malzeme_durumu: str
    diger: Decimal
    diger_maliyet: Decimal | None
    diger_maliyet_notu: str | None = None
    gelir: Decimal | None
    gelir_kaynagi: str | None
    gelir_durumu: str
    gelir_notu: str | None = None
    fark: Decimal | None
    fark_durumu: str
    durum: str
    fatura_iletildi_at: datetime | None
    finans_version: int | None


async def _finans_cikti(db: DbDep, so: ServiceOrder) -> IsFinansiOut:
    from app.models import ServiceOrderFinancial

    veri = (await svc.is_finansi_toplu(db, [so.id]))[so.id].sozluk()
    fin = await db.scalar(
        select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so.id)
    )
    return IsFinansiOut(
        **veri,
        so_no=so.so_no,
        birim=so.birim,
        tur=so.tur,
        diger_maliyet_notu=fin.diger_maliyet_notu if fin else None,
        gelir_notu=fin.gelir_notu if fin else None,
    )


# --- Tarifeler (TS-146) ----------------------------------------------------------------


@router.get("/tarifeler", response_model=list[TarifeOut])
async def tarifeler(db: DbDep, user: MaliyetOkuyucu, birim: str | None = None) -> list[TarifeOut]:
    from app.services.quotes import kullanici_adlari

    with _hatalar():
        satirlar = await svc.tarifeler(db, user, birim)
    adlar = await kullanici_adlari(db, {t.created_by for t in satirlar})
    sonuc = []
    for t in satirlar:
        out = TarifeOut.model_validate(t)
        out.giren = adlar.get(t.created_by) if t.created_by else None
        out.kapatildi = t.valid_to is not None and t.valid_to == t.valid_from
        sonuc.append(out)
    return sonuc


@router.post("/tarifeler", response_model=TarifeOut, status_code=status.HTTP_201_CREATED)
async def tarife_ekle(
    payload: TarifeIn, request: Request, db: DbDep, clock: ClockDep, user: MaliyetYazici
) -> TarifeOut:
    with _hatalar():
        t = await svc.tarife_ekle(
            db,
            birim=payload.birim,
            valid_from=payload.valid_from,
            hourly_cost=payload.hourly_cost,
            gerekce=payload.gerekce,
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    await db.commit()
    await db.refresh(t)
    out = TarifeOut.model_validate(t)
    out.giren = user.full_name
    return out


@router.post("/tarifeler/kapat", response_model=TarifeOut)
async def tarife_kapat(
    payload: TarifeKapatIn, request: Request, db: DbDep, clock: ClockDep, user: MaliyetYazici
) -> TarifeOut:
    t = await db.get(ServiceLaborRate, payload.tarife_id)
    if t is None or kapsam.birim_disinda_mi(user, t.birim, birimsiz_gorunur=False):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tarife bulunamadı")
    with _hatalar():
        await svc.tarife_kapat(
            db,
            t,
            gerekce=payload.gerekce,
            version=payload.version,
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    await db.commit()
    await db.refresh(t)
    out = TarifeOut.model_validate(t)
    out.kapatildi = True
    return out


# --- İş finansı (TS-145) -----------------------------------------------------------------


@router.get("/isler/{so_id}", response_model=IsFinansiOut)
async def is_finansi(so_id: int, db: DbDep, user: MaliyetOkuyucu) -> IsFinansiOut:
    so = await _is_al(db, so_id, user)
    return await _finans_cikti(db, so)


@router.put("/isler/{so_id}/gelir", response_model=IsFinansiOut)
async def gelir_yaz(
    so_id: int,
    payload: GelirIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: MaliyetYazici,
) -> IsFinansiOut:
    so = await _is_al(db, so_id, user)
    with _hatalar():
        await svc.gelir_yaz(db, so, payload, user=user, clock=clock, ip=client_ip(request))
    await db.commit()
    return await _finans_cikti(db, so)


@router.put("/isler/{so_id}/diger-maliyet", response_model=IsFinansiOut)
async def diger_maliyet_yaz(
    so_id: int,
    payload: DigerMaliyetIn,
    request: Request,
    db: DbDep,
    user: MaliyetYazici,
) -> IsFinansiOut:
    so = await _is_al(db, so_id, user)
    with _hatalar():
        await svc.diger_maliyet_yaz(
            db,
            so,
            tutar=payload.tutar,
            not_=payload.not_,
            version=payload.version,
            user=user,
            ip=client_ip(request),
        )
    await db.commit()
    return await _finans_cikti(db, so)


@router.get("/isler/{so_id}/gecmis")
async def gelir_gecmisi(so_id: int, db: DbDep, user: MaliyetOkuyucu) -> list[dict[str, Any]]:
    so = await _is_al(db, so_id, user)
    return await svc.gelir_gecmisi(db, so)


# --- Analiz (TS-149) --------------------------------------------------------------------


@router.get("/analiz")
async def analiz(
    db: DbDep,
    user: AnalizOkuyucu,
    donem: str | None = None,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    tur: str | None = None,
    musteri_id: int | None = None,
    durum: str | None = None,
) -> dict[str, Any]:
    """Dönem/birim/tür/müşteri süzgeçli maliyet analizi; birim × tür özeti.

    `durum` KPI kutuları içindir (TAM, SURE_EKSIK, TARIFE_EKSIK, MALIYET_EKSIK,
    GELIR_YOK, SOZLESME_KAPSAMI). Eksik tutar `null` döner, 0 yazılmaz.
    """
    with _hatalar():
        bas, bit = svc.donem_araligi(donem, baslangic, bitis)
        return await svc.analiz(
            db,
            user,
            svc.AnalizFiltresi(
                baslangic=bas, bitis=bit, birim=birim, tur=tur, musteri_id=musteri_id, durum=durum
            ),
        )
