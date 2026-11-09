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
- `GET /analiz.xlsx?kirilim=is|musteri` (maliyet.gor + servis_rapor.disaaktar) —
  aynı `analiz()` çıktısı; eksik tutar boş hücre, 0 değil (TS-197, E07-22)
- `GET /fatura-devri` (tahsilat.gor), `GET /fatura-devri.xlsx` (+ servis_rapor.disaaktar),
  `POST /fatura-devri/isaretle`, `POST /fatura-devri/{so_id}/geri-al` (tahsilat.yaz)
  — "Faturaya iletildi" işareti; işaret sonrası gelir kilidi (TS-197, E07-26)
- `GET /teklif-donusumu` (teklif.gor + servis_rapor.gor), `.xlsx` (+ disaaktar) —
  birimli teklif dönüşümü, "Teklifler" sayfası (TS-197, E07-24)

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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import ServiceLaborRate, ServiceOrder, User
from app.services import export as export_svc
from app.services.teknik_servis import fatura_devri, kapsam
from app.services.teknik_servis import maliyet as svc
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teknik-servis/maliyet", tags=["servis-maliyet"])

MaliyetOkuyucu = Annotated[User, Depends(require_permission("maliyet.gor"))]
MaliyetYazici = Annotated[User, Depends(require_permission("maliyet.gor", "maliyet.yaz"))]
AnalizOkuyucu = Annotated[User, Depends(require_permission("maliyet.gor", "servis_rapor.gor"))]
# KD-06: teknik servis Excel'leri `<modül>.gor + servis_rapor.disaaktar` ister.
AnalizAktarici = Annotated[
    User, Depends(require_permission("maliyet.gor", "servis_rapor.disaaktar"))
]
DevirOkuyucu = Annotated[User, Depends(require_permission("tahsilat.gor"))]
DevirYazici = Annotated[User, Depends(require_permission("tahsilat.yaz"))]
DevirAktarici = Annotated[
    User, Depends(require_permission("tahsilat.gor", "servis_rapor.disaaktar"))
]
DonusumOkuyucu = Annotated[User, Depends(require_permission("teklif.gor", "servis_rapor.gor"))]
DonusumAktarici = Annotated[
    User, Depends(require_permission("teklif.gor", "servis_rapor.disaaktar"))
]
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@contextmanager
def _hatalar() -> Iterator[None]:
    try:
        yield
    except fatura_devri.FaturaDevriHatasi as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"mesaj": str(exc), "sorunlu_isler": exc.sorunlu}
        ) from exc
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


def _iso(deger: Any) -> Any:
    return deger.isoformat() if isinstance(deger, date) else deger


async def _disaaktarim_denetimi(
    db: DbDep, request: Request, user: User, rapor: str, filtreler: dict[str, Any], satir: int
) -> None:
    """Excel indirmesi denetim izine (filtreler ISO) — tek yardımcı `rapor_excel`."""
    from app.services.teknik_servis import rapor_excel

    await rapor_excel.disa_aktarim_denetimi(
        db,
        user=user,
        ip=client_ip(request),
        rapor=rapor,
        filtreler={k: _iso(v) for k, v in filtreler.items() if v not in (None, "")},
        satir_sayisi=satir,
        kapsam=user.role.scope if user.role is not None else "",
        kisisel_sayfalar=[],
    )
    await db.commit()


_DURUM_ADLARI = {
    "TAM": "Tam",
    "SURE_EKSIK": "Süre kaydı eksik",
    "TARIFE_EKSIK": "Tarife eksik",
    "MALIYET_EKSIK": "Maliyet eksik",
    "YOK": "Parça yok",
    "KAYIT_YOK": "Gelir kaydı yok",
    "SOZLESME_KAPSAMI": "Sözleşme kapsamı",
    "HESAPLANDI": "Hesaplandı",
    "HESAPLANAMADI": "Hesaplanamadı",
}


def _ad(kod: str | None) -> str | None:
    return _DURUM_ADLARI.get(kod, kod) if kod else kod


@router.get("/analiz.xlsx")
async def analiz_xlsx(
    request: Request,
    db: DbDep,
    user: AnalizAktarici,
    donem: str | None = None,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    tur: str | None = None,
    musteri_id: int | None = None,
    durum: str | None = None,
    kirilim: Literal["is", "musteri"] = "is",
) -> Response:
    """Maliyet analizi Excel'i (E07-22): AYNI `analiz()` çıktısı. Durum
    sütunları her zaman var; eksik tutar boş hücre (0 yazılmaz). `kirilim=
    musteri` yalnız tam satırların tutarlarını müşteri bazında toplar —
    toplamı iş kırılımı toplamına eşittir. Metin hücresi formüle dönmez."""
    with _hatalar():
        bas, bit = svc.donem_araligi(donem, baslangic, bitis)
        veri = await svc.analiz(
            db,
            user,
            svc.AnalizFiltresi(
                baslangic=bas, bitis=bit, birim=birim, tur=tur, musteri_id=musteri_id, durum=durum
            ),
        )
    S = export_svc.Sutun
    durum_sutunlari = [
        S("İşçilik Durumu"),
        S("Malzeme Durumu"),
        S("Gelir Durumu"),
        S("Fark Durumu"),
    ]
    if kirilim == "is":
        sutunlar = [
            S("İş No"),
            S("Birim"),
            S("Tür"),
            S("Müşteri"),
            S("Kapanış", "tarih"),
            S("Süre (dk)", "tamsayi"),
            S("İşçilik", "ondalik"),
            S("Malzeme", "ondalik"),
            S("Diğer", "ondalik"),
            S("Gelir", "ondalik"),
            S("Fark", "ondalik"),
            *durum_sutunlari,
        ]
        satirlar = [
            [
                s["so_no"],
                s["birim"],
                s["tur"],
                s["musteri"],
                s["kapanis_tarihi"],
                s["sure_dk"],
                s["iscilik"],
                s["malzeme"],
                s["diger"],
                s["gelir"],
                s["fark"],
                _ad(s["iscilik_durumu"]),
                _ad(s["malzeme_durumu"]),
                _ad(s["gelir_durumu"]),
                _ad(s["fark_durumu"]),
            ]
            for s in veri["satirlar"]
        ]
    else:
        gruplar: dict[tuple, dict[str, Any]] = {}
        for s in veri["satirlar"]:
            g = gruplar.setdefault(
                (s["musteri_id"], s["musteri"]),
                {
                    "adet": 0,
                    "tam": 0,
                    "iscilik": Decimal("0"),
                    "malzeme": Decimal("0"),
                    "diger": Decimal("0"),
                    "gelir": Decimal("0"),
                    "fark": Decimal("0"),
                    "sure_eksik": 0,
                    "maliyet_eksik": 0,
                    "gelir_yok": 0,
                    "tarife_eksik": 0,
                },
            )
            g["adet"] += 1
            g["sure_eksik"] += s["iscilik_durumu"] == "SURE_EKSIK"
            g["tarife_eksik"] += s["iscilik_durumu"] == "TARIFE_EKSIK"
            g["maliyet_eksik"] += s["malzeme_durumu"] == "MALIYET_EKSIK"
            g["gelir_yok"] += s["gelir_durumu"] in ("KAYIT_YOK", "SOZLESME_KAPSAMI")
            if s["fark"] is not None:  # toplamlar yalnız tam satırlardan (E07-21)
                g["tam"] += 1
                for a in ("iscilik", "malzeme", "diger", "gelir", "fark"):
                    g[a] += Decimal(str(s[a]))
        sutunlar = [
            S("Müşteri"),
            S("İş Adedi", "tamsayi"),
            S("Tam İş", "tamsayi"),
            S("İşçilik", "ondalik"),
            S("Malzeme", "ondalik"),
            S("Diğer", "ondalik"),
            S("Gelir", "ondalik"),
            S("Fark", "ondalik"),
            S("Süre Eksik", "tamsayi"),
            S("Tarife Eksik", "tamsayi"),
            S("Maliyet Eksik", "tamsayi"),
            S("Gelir Yok", "tamsayi"),
        ]
        satirlar = [
            [
                ad or "Müşteri belirtilmemiş",
                g["adet"],
                g["tam"],
                *(g[a] if g["tam"] else None for a in ("iscilik", "malzeme", "diger", "gelir")),
                g["fark"] if g["tam"] else None,
                g["sure_eksik"],
                g["tarife_eksik"],
                g["maliyet_eksik"],
                g["gelir_yok"],
            ]
            for (_, ad), g in sorted(gruplar.items(), key=lambda x: str(x[0][1] or ""))
        ]
    await _disaaktarim_denetimi(
        db,
        request,
        user,
        "maliyet_analiz",
        {
            "baslangic": bas,
            "bitis": bit,
            "birim": birim,
            "tur": tur,
            "musteri_id": musteri_id,
            "durum": durum,
            "kirilim": kirilim,
        },
        len(satirlar),
    )
    icerik = await export_svc.sayfalari_xlsx_async(
        [export_svc.Sayfa("Maliyet Analizi", sutunlar, satirlar)]
    )
    return Response(
        content=icerik,
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="servis-maliyet-{kirilim}.xlsx"'},
    )


# --- Fatura devri (TS-197, E07-26) ------------------------------------------------------


class IsaretleIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"examples": [{"is_idler": [1], "not": "Ekim faturası"}]},
    )

    is_idler: list[int] = Field(min_length=1, max_length=fatura_devri.AZAMI_TOPLU)
    not_: str | None = Field(default=None, alias="not", max_length=300)


class GeriAlIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"gerekce": "Yanlış iş seçildi"}]})

    gerekce: str = Field(min_length=1, max_length=300)


def _devir_suzgeci(durum: str, donem: str | None, birim: str | None, musteri_id: int | None):
    return fatura_devri.DevirSuzgeci(
        durum=durum, donem=donem or None, birim=birim or None, musteri_id=musteri_id
    )


@router.get("/fatura-devri")
async def fatura_devri_listesi(
    response: Response,
    db: DbDep,
    user: DevirOkuyucu,
    durum: Literal["bekleyen", "iletildi"] = "bekleyen",
    donem: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    birim: str | None = None,
    musteri_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Faturaya iletilmeyi bekleyen ya da iletilmiş servis işleri. Tutar
    anahtarı yalnız `teklif.gor`/`maliyet.gor` sahibine döner."""
    with _hatalar():
        stmt = fatura_devri.liste_sorgusu(user, _devir_suzgeci(durum, donem, birim, musteri_id))
    kayitlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await fatura_devri.satirlar(db, user, list(kayitlar))


@router.get("/fatura-devri.xlsx")
async def fatura_devri_xlsx(
    request: Request,
    db: DbDep,
    user: DevirAktarici,
    durum: Literal["bekleyen", "iletildi"] = "bekleyen",
    donem: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    birim: str | None = None,
    musteri_id: int | None = None,
    bicim: Literal["xlsx", "csv"] = "xlsx",
) -> Response:
    """Fatura devri dökümü. `bicim=csv`: Logo aktarımı için `;` ayraçlı, UTF-8
    BOM'lu CSV (KARARLAR 2026-11-09 S4.4; Logo API'si DEĞİL)."""
    with _hatalar():
        stmt = fatura_devri.liste_sorgusu(user, _devir_suzgeci(durum, donem, birim, musteri_id))
    satirlar = await fatura_devri.satirlar(db, user, list((await db.execute(stmt)).all()))
    S = export_svc.Sutun
    sutunlar = [
        S("İş No"),
        S("Birim"),
        S("Tür"),
        S("Müşteri"),
        S("Kapanış", "tarih"),
        S("Gelir Kaynağı"),
        S("Teklifler"),
        S("İletildi", "zaman"),
        S("İleten"),
        S("Not"),
    ]
    tutar = fatura_devri.tutar_gorur_mu(user)
    if tutar:
        sutunlar.insert(7, S("Tutar (KDV hariç)", "ondalik"))
    tablo = []
    for s in satirlar:
        satir = [
            s["so_no"],
            s["birim"],
            s["tur"],
            s["musteri"],
            date.fromisoformat(s["kapanis_tarihi"]) if s["kapanis_tarihi"] else None,
            s["gelir_kaynagi"],
            ", ".join(s["teklifler"]),
            s["fatura_iletildi_at"],
            s["iletti"],
            s["fatura_notu"],
        ]
        if tutar:
            satir.insert(7, s["tutar"])
        tablo.append(satir)
    await _disaaktarim_denetimi(
        db,
        request,
        user,
        "fatura_devri",
        {"durum": durum, "donem": donem, "birim": birim, "musteri_id": musteri_id},
        len(tablo),
    )
    if bicim == "csv":
        from app.services.muhasebe_aktarim import csv_uret

        return Response(
            content=csv_uret(sutunlar, tablo),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="fatura-devri-{durum}.csv"'},
        )
    icerik = await export_svc.sayfalari_xlsx_async(
        [export_svc.Sayfa("Fatura Devri", sutunlar, tablo)]
    )
    return Response(
        content=icerik,
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="fatura-devri-{durum}.xlsx"'},
    )


@router.post("/fatura-devri/isaretle")
async def fatura_devri_isaretle(
    payload: IsaretleIn, request: Request, db: DbDep, clock: ClockDep, user: DevirYazici
) -> dict[str, Any]:
    """Toplu "Faturaya iletildi" işareti; bir kimlik uygun/kapsamda değilse
    TAMAMI 409 (`sorunlu_isler`) ve hiçbir satır işaretlenmez."""
    with _hatalar():
        idler = await fatura_devri.isaretle(
            db, user, payload.is_idler, not_=payload.not_, clock=clock, ip=client_ip(request)
        )
    await db.commit()
    return {"isaretlenen": idler}


@router.post("/fatura-devri/{so_id}/geri-al")
async def fatura_devri_geri_al(
    so_id: int, payload: GeriAlIn, request: Request, db: DbDep, user: DevirYazici
) -> dict[str, Any]:
    """Devri gerekçeyle geri alır (gelir kilidi kalkar). Kapsam dışı iş 404."""
    so = await _is_al(db, so_id, user)
    with _hatalar():
        await fatura_devri.geri_al(db, user, so, gerekce=payload.gerekce, ip=client_ip(request))
    await db.commit()
    return {"so_id": so.id, "geri_alindi": True}


# --- Teklif dönüşümü (TS-197, E07-24) ----------------------------------------------------


def _donusum_birimi(user: User, birim: str) -> str:
    from app.models.rbac import BIRIM_KODLARI

    birim = birim.strip().upper()
    if birim not in BIRIM_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {birim}")
    if kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu birimin raporunu görme yetkiniz yok")
    return birim


@router.get("/teklif-donusumu")
async def teklif_donusumu(
    db: DbDep,
    clock: ClockDep,
    user: DonusumOkuyucu,
    birim: str,
    gun: int = Query(default=365, ge=1, le=730),
) -> dict[str, Any]:
    """Birimli (servis) teklif dönüşümü: kabul oranı (karara bağlanan
    paydada; süresi dolan kaybedilen), iptal ayrı, gönderilen adet, kabul
    tutarı, ortalama yanıt günü. Satış raporu (`/api/raporlar`) değişmez."""
    from app.services import reports as rapor_svc

    birim = _donusum_birimi(user, birim)
    return await rapor_svc.servis_teklif_donusumu(db, gun=gun, clock=clock, birim=birim, user=user)


@router.get("/teklif-donusumu.xlsx")
async def teklif_donusumu_xlsx(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: DonusumAktarici,
    birim: str,
    gun: int = Query(default=365, ge=1, le=730),
) -> Response:
    """ "Teklifler" sayfası satır sayısı rapor toplamına eşittir (aynı sorgu)."""
    from app.services import reports as rapor_svc

    birim = _donusum_birimi(user, birim)
    ozet = await rapor_svc.servis_teklif_donusumu(db, gun=gun, clock=clock, birim=birim, user=user)
    satirlar = await rapor_svc.servis_teklif_satirlari(
        db, gun=gun, clock=clock, birim=birim, user=user
    )
    S = export_svc.Sutun
    sayfalar = [
        export_svc.Sayfa(
            "Özet",
            [S("Gösterge"), S("Değer")],
            [
                ["Birim", birim],
                ["Gün", str(gun)],
                ["Toplam teklif", str(ozet["toplam_teklif"])],
                ["Gönderilen", str(ozet["gonderilen_adet"])],
                ["Kazanılan", str(ozet["kazanilan"])],
                ["Kaybedilen (ret + süresi dolan)", str(ozet["kaybedilen"])],
                ["İptal (kaybedilen sayılmaz)", str(ozet["iptal"])],
                [
                    "Dönüşüm (%)",
                    str(ozet["donusum_yuzde"]) if ozet["donusum_yuzde"] is not None else "—",
                ],
                [
                    "Ort. yanıt (gün)",
                    str(ozet["ort_yanit_gun"]) if ozet["ort_yanit_gun"] is not None else "—",
                ],
            ],
        ),
        export_svc.Sayfa(
            "Teklifler",
            [
                S("Teklif No"),
                S("Birim"),
                S("Müşteri"),
                S("Oluşturma", "tarih"),
                S("Durum"),
                S("Gönderim", "tarih"),
                S("Karar", "tarih"),
                S("Yanıt (gün)", "ondalik"),
                S("Net Tutar (TL)", "ondalik"),
                S("Kayıp Nedeni"),
            ],
            [
                [
                    s["quote_no"],
                    s["birim"],
                    s["musteri"],
                    s["olusturma"],
                    s["durum"],
                    s["gonderim"],
                    s["karar"],
                    s["yanit_gun"],
                    s["net_tl"],
                    s["kayip_nedeni"],
                ]
                for s in satirlar
            ],
        ),
    ]
    await _disaaktarim_denetimi(
        db, request, user, "teklif_donusumu", {"birim": birim, "gun": gun}, len(satirlar)
    )
    icerik = await export_svc.sayfalari_xlsx_async(sayfalar)
    return Response(
        content=icerik,
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="teklif-donusumu-{birim}.xlsx"'},
    )
