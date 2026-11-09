"""Satış takibi uçları (KARARLAR 2026-11-09 S1, S2, S3, S4.1, S4.2).

- Keşif iste (`teklif.kesif_iste`) ve kabul edilen teklif/siparişten kurulum
  ya da teslimat işi (`teklif.servis_isi_ac`): satış rolü servis işini
  YALNIZ bu dar uçlardan açar; teklif/sipariş yazma kapsamı da aranır.
- Bağlı işler ve aşamaları, keşif sonucu, keşif fotoğrafları ve keşif raporu
  PDF'i teklif okuma kapsamından verilir (FİYATSIZ; maliyet hiç taşınmaz).
- Tekliflerim (S2.2), Satışlarımın durumu (S4.2), kaybedilme nedeni kataloğu
  (S2.1), iskonto kişi limitleri (S1.2; rol limitleri genel ayar ucundan).

Her uç sunucu tarafında izin denetler; kapsam dışı teklif/sipariş/iş 404.
"""

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
)
from app.models import Attachment, Role, RolePermission, ServiceOrder, User
from app.models.quote import KAYIP_NEDENLERI
from app.services import audit, iskonto, sirketler
from app.services import quotes as teklif_svc
from app.services import satis_takip as svc
from app.services.pdf import PdfUretilemedi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/satis-takip", tags=["satis-takip"])

TeklifOkuyucu = Annotated[User, Depends(require_permission("teklif.gor"))]
SiparisOkuyucu = Annotated[User, Depends(require_permission("siparis.gor"))]
KesifIsteyen = Annotated[User, Depends(require_permission("teklif.kesif_iste"))]
IsAcan = Annotated[User, Depends(require_permission("teklif.servis_isi_ac"))]
AyarYoneticisi = Annotated[User, Depends(require_permission("sistem.ayar"))]
MusteriOkuyucu = Annotated[User, Depends(require_any_permission("servis.gor", "teklif.gor"))]


@contextmanager
def _hatalar():
    try:
        yield
    except teklif_svc.TeklifKapsamDisi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except teklif_svc.TeklifYetkiHatasi as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except teklif_svc.TeklifGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except teklif_svc.TeklifKuralHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ServisGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ServisHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def _mobilite_kapisi(user: User) -> None:
    """Sipariş ekranı yalnız DENGE MOBİLİTE etkinken açılır (`MOBILITE_KAPISI`)."""
    if not sirketler.mobilite_acik_mi(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"kod": "SIRKET_DISI_MODUL", "mesaj": "Siparişler yalnız DENGE MOBİLİTE seçiliyken"},
        )


# --- Şemalar ------------------------------------------------------------------------


class BagliIsOut(BaseModel):
    service_order_id: int
    so_no: str
    bag_turu: str
    bag_adi: str
    tur: str
    tur_adi: str
    birim: str
    birim_adi: str
    oncelik: str
    durum: str
    durum_adi: str
    asama: str
    asama_adi: str
    askida_nedeni: str | None = None
    plan_tarihi: date | None = None
    hedef_tarih: date | None = None
    tamamlanma: datetime | None = None
    acilis: datetime | None = None


class KesifIn(BaseModel):
    birim: str | None = Field(default=None, max_length=20)
    oncelik: Literal["NORMAL", "YUKSEK"] = "NORMAL"
    hedef_tarih: date | None = None
    aciklama: str | None = Field(default=None, max_length=1000)
    address_id: int | None = None


class SatisIsiIn(KesifIn):
    tur: Literal["KURULUM", "TESLIMAT"] = "KURULUM"


class AcilanIsOut(BaseModel):
    service_order_id: int
    so_no: str
    isler: list[BagliIsOut]


def _istek(p: KesifIn) -> svc.IsIstegi:
    return svc.IsIstegi(
        birim=p.birim,
        oncelik=p.oncelik,
        hedef_tarih=p.hedef_tarih,
        aciklama=p.aciklama,
        address_id=p.address_id,
    )


# --- Katalog ------------------------------------------------------------------------


@router.get("/kayip-nedenleri")
async def kayip_nedenleri(_: TeklifOkuyucu) -> list[dict]:
    """S2.1 kaybedilme nedeni kataloğu (DIGER'de açıklama zorunlu)."""
    return [
        {"kod": k, "ad": a, "aciklama_zorunlu": k == "DIGER"} for k, a in KAYIP_NEDENLERI.items()
    ]


@router.get("/asamalar")
async def asamalar(_: TeklifOkuyucu) -> list[dict]:
    return [{"kod": k, "ad": a} for k, a in svc.ASAMA_ADLARI.items()]


# --- Teklif: bağlı işler, keşif, kurulum/teslimat ------------------------------------


async def _teklif(db: DbDep, teklif_id: int, user: User, *, yazma: bool = False):
    with _hatalar():
        return await teklif_svc.teklif_al(db, teklif_id, user, yazma=yazma)


@router.get("/teklif/{teklif_id}/isler", response_model=list[BagliIsOut])
async def teklif_isleri(teklif_id: int, db: DbDep, user: TeklifOkuyucu) -> list[BagliIsOut]:
    t = await _teklif(db, teklif_id, user)
    return [BagliIsOut(**r) for r in await svc.teklif_bagli_isler(db, t)]


@router.post(
    "/teklif/{teklif_id}/kesif", response_model=AcilanIsOut, status_code=status.HTTP_201_CREATED
)
async def kesif_iste(
    teklif_id: int,
    payload: KesifIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: KesifIsteyen,
) -> AcilanIsOut:
    """S3.1: teklife bağlı KESIF işi (PLANLAMADA, KRITIK yok, SLA yok)."""
    if not user.has("teklif.gor"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Teklif görme yetkiniz yok")
    t = await _teklif(db, teklif_id, user, yazma=True)
    with _hatalar():
        so = await svc.kesif_iste(db, t, _istek(payload), user=user, clock=clock)
    await db.commit()
    return AcilanIsOut(
        service_order_id=so.id,
        so_no=so.so_no,
        isler=[BagliIsOut(**r) for r in await svc.teklif_bagli_isler(db, t)],
    )


@router.post(
    "/teklif/{teklif_id}/is", response_model=AcilanIsOut, status_code=status.HTTP_201_CREATED
)
async def tekliften_is_ac(
    teklif_id: int,
    payload: SatisIsiIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IsAcan,
) -> AcilanIsOut:
    """S4.1: kabul edilen tekliften kurulum/teslimat işi (birden çok olabilir)."""
    if not user.has("teklif.gor"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Teklif görme yetkiniz yok")
    t = await _teklif(db, teklif_id, user, yazma=True)
    with _hatalar():
        so = await svc.tekliften_is_ac(db, t, payload.tur, _istek(payload), user=user, clock=clock)
    await db.commit()
    return AcilanIsOut(
        service_order_id=so.id,
        so_no=so.so_no,
        isler=[BagliIsOut(**r) for r in await svc.teklif_bagli_isler(db, t)],
    )


async def _bagli_is(db: DbDep, teklif_id: int, so_id: int, user: User):
    t = await _teklif(db, teklif_id, user)
    with _hatalar():
        so = await svc.bagli_is_al(db, t, so_id)
    return t, so


@router.get("/teklif/{teklif_id}/isler/{so_id}/sonuc")
async def is_sonucu(teklif_id: int, so_id: int, db: DbDep, user: TeklifOkuyucu) -> dict:
    """S3.3: keşif (ya da bağlı iş) sonucu: teknisyen raporu ve ekler (fiyatsız)."""
    _, so = await _bagli_is(db, teklif_id, so_id, user)
    return await svc.is_sonucu(db, so)


@router.get("/teklif/{teklif_id}/isler/{so_id}/ekler/{ek_id}")
async def is_eki(
    teklif_id: int, so_id: int, ek_id: int, db: DbDep, user: TeklifOkuyucu
) -> Response:
    """Bağlı işin fotoğrafı/belgesi — teklif kapsamından (servis işi ekranı gerekmez)."""
    from app.services import storage as depo

    _, so = await _bagli_is(db, teklif_id, so_id, user)
    ek = await db.get(Attachment, ek_id)
    if ek is None or ek.entity != "service_orders" or ek.entity_id != so.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ek bulunamadı")
    try:
        yol = depo.yol(ek.storage_path)
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    icerde = ek.mime_type in depo.GORSEL_TIPLERI or ek.mime_type == "application/pdf"
    from urllib.parse import quote as url_kodla

    return Response(
        content=yol.read_bytes(),
        media_type=ek.mime_type,
        headers={
            "Content-Disposition": (
                f"{'inline' if icerde else 'attachment'}; "
                f"filename*=UTF-8''{url_kodla(ek.file_name)}"
            ),
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )


@router.get("/teklif/{teklif_id}/isler/{so_id}/kesif-raporu.pdf")
async def kesif_raporu(
    teklif_id: int, so_id: int, db: DbDep, clock: ClockDep, user: TeklifOkuyucu
) -> Response:
    """S3.3 keşif raporu PDF'i (fiyatsız; fotoğraflar gömülü)."""
    t, so = await _bagli_is(db, teklif_id, so_id, user)
    if so.tur != "KESIF":
        raise HTTPException(status.HTTP_409_CONFLICT, "Keşif raporu yalnız keşif işinde vardır")
    try:
        icerik = await svc.kesif_raporu_pdf(db, t, so, clock=clock)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="Kesif-{so.so_no}.pdf"'},
    )


# --- Sipariş: bağlı işler, kurulum/teslimat (S4.1/S4.2) -----------------------------------


@router.get("/siparis/{siparis_id}/isler", response_model=list[BagliIsOut])
async def siparis_isleri(siparis_id: int, db: DbDep, user: SiparisOkuyucu) -> list[BagliIsOut]:
    _mobilite_kapisi(user)
    with _hatalar():
        s = await svc.siparis_al(db, siparis_id, user)
    return [BagliIsOut(**r) for r in await svc.siparis_bagli_isler(db, s)]


@router.post(
    "/siparis/{siparis_id}/is", response_model=AcilanIsOut, status_code=status.HTTP_201_CREATED
)
async def siparisten_is_ac(
    siparis_id: int,
    payload: SatisIsiIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IsAcan,
) -> AcilanIsOut:
    if not user.has("siparis.gor"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sipariş görme yetkiniz yok")
    _mobilite_kapisi(user)
    with _hatalar():
        s = await svc.siparis_al(db, siparis_id, user)
        so = await svc.siparisten_is_ac(db, s, payload.tur, _istek(payload), user=user, clock=clock)
    await db.commit()
    return AcilanIsOut(
        service_order_id=so.id,
        so_no=so.so_no,
        isler=[BagliIsOut(**r) for r in await svc.siparis_bagli_isler(db, s)],
    )


# --- Müşteri kartı: servis işleri ve aşamaları (S4.2) --------------------------------------


@router.get("/musteri/{musteri_id}/isler", response_model=list[BagliIsOut])
async def musteri_isleri(
    musteri_id: int, db: DbDep, user: MusteriOkuyucu, limit: int = 100
) -> list[BagliIsOut]:
    """Müşterinin bakım/onarım/kurulum işleri ve aşamaları (fiyatsız).

    Servis rolü kendi iş kapsamıyla (`kapsam_isler`) görür; satış rolü müşteri
    kapsamıyla (kendi müşterisi) ve etkin şirketin birimleriyle süzülür.
    """
    from app.services import accounts
    from app.services.teknik_servis import kapsam

    if not user.has("hesap.gor") or await accounts.kapsam_disinda_mi(db, user, musteri_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Müşteri bulunamadı")
    stmt = select(ServiceOrder.id).where(
        ServiceOrder.customer_id == musteri_id, ServiceOrder.is_deleted.is_(False)
    )
    if user.has("servis.gor"):
        stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    else:
        birimler = sirketler.etkin_birimler(user)
        if birimler is not None:
            stmt = stmt.where(ServiceOrder.birim.in_(sorted(birimler)))
    idler = (
        await db.scalars(stmt.order_by(ServiceOrder.id.desc()).limit(min(max(limit, 1), 300)))
    ).all()
    satirlar = [(i, "MUSTERI", None) for i in idler]
    sonuc = await svc._is_ozetleri(db, satirlar)
    for r in sonuc:
        r["bag_adi"] = r["tur_adi"]
    return [BagliIsOut(**r) for r in sonuc]


# --- Tekliflerim / Satışlarımın durumu ----------------------------------------------------


@router.get("/tekliflerim")
async def tekliflerim(
    db: DbDep,
    clock: ClockDep,
    user: TeklifOkuyucu,
    tarih_bas: date | None = None,
    tarih_bit: date | None = None,
    tur: Literal["SATIS", "SERVIS"] | None = None,
    ekip: bool = False,
    hazirlayan_id: int | None = None,
) -> dict:
    """S2.2: açık/kazanılan/kaybedilen/süresi dolan, oranlar ve nedene göre
    kayıp. `ekip=true` satışçı kırılımıdır ve `teklif.ekip_ozet` ister."""
    if (ekip or hazirlayan_id is not None) and not user.has("teklif.ekip_ozet"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ekip görünümü için yetkiniz yok")
    with _hatalar():
        return await svc.tekliflerim(
            db,
            user,
            clock,
            tarih_bas=tarih_bas,
            tarih_bit=tarih_bit,
            tur=tur,
            ekip=ekip or hazirlayan_id is not None,
            hazirlayan_id=hazirlayan_id,
        )


@router.get("/satislarim")
async def satislarim(
    db: DbDep,
    clock: ClockDep,
    user: TeklifOkuyucu,
    ekip: bool = False,
    hazirlayan_id: int | None = None,
) -> list[dict]:
    """S4.2: kabul edilen teklif ve siparişlerim, bağlı işleri ve aşamaları."""
    if (ekip or hazirlayan_id is not None) and not user.has("teklif.ekip_ozet"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ekip görünümü için yetkiniz yok")
    return await svc.satislarim(
        db, user, clock, ekip=ekip or hazirlayan_id is not None, hazirlayan_id=hazirlayan_id
    )


# --- İskonto limitleri (S1.1/S1.2) -------------------------------------------------------


class KisiLimitiOut(BaseModel):
    id: int
    ad: str
    rol: str | None
    rol_adi: str | None
    rol_limiti: Decimal
    kisi_limiti: Decimal | None
    etkin_limit: Decimal
    version: int


class KisiLimitiIn(BaseModel):
    iskonto_limiti_yuzde: Decimal | None = Field(default=None, ge=0, le=100)
    version: int


async def _kisi_satiri(u: User, tablo: dict[str, Decimal]) -> KisiLimitiOut:
    return KisiLimitiOut(
        id=u.id,
        ad=u.full_name,
        rol=u.role.code if u.role else None,
        rol_adi=u.role.name if u.role else None,
        rol_limiti=iskonto.rol_limiti(u.role.code if u.role else None, tablo),
        kisi_limiti=u.iskonto_limiti_yuzde,
        etkin_limit=iskonto.kisi_limiti(u, tablo),
        version=u.version,
    )


@router.get("/iskonto-limitleri")
async def iskonto_limitleri(db: DbDep, _: AyarYoneticisi) -> dict:
    """Rol limitleri (ayar `iskonto_rol_limitleri`) + teklif hazırlayan
    kullanıcıların kişi limitleri. Rol limitleri genel ayar ucundan yazılır."""
    tablo = await iskonto.rol_limitleri(db)
    yazan_roller = select(RolePermission.role_id).where(
        RolePermission.permission_code == "teklif.yaz"
    )
    kullanicilar = (
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True), User.role_id.in_(yazan_roller))
            .order_by(User.full_name)
        )
    ).all()
    roller = (await db.execute(select(Role.code, Role.name).where(Role.id.in_(yazan_roller)))).all()
    return {
        "rol_limitleri": {k: float(v) for k, v in tablo.items()},
        "roller": [{"kod": k, "ad": a} for k, a in sorted(roller)],
        "kisiler": [await _kisi_satiri(u, tablo) for u in kullanicilar],
    }


@router.put("/iskonto-limitleri/kisi/{user_id}", response_model=KisiLimitiOut)
async def kisi_limiti_yaz(
    user_id: int, payload: KisiLimitiIn, request: Request, db: DbDep, admin: AyarYoneticisi
) -> KisiLimitiOut:
    """S1.2 kişiye özel limit (NULL = rol limiti). İyimser kilit `version`."""
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")
    if payload.version != u.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin"
        )
    eski = u.iskonto_limiti_yuzde
    u.iskonto_limiti_yuzde = payload.iskonto_limiti_yuzde
    await audit.log(
        db,
        "users",
        "iskonto_limiti",
        entity_id=u.id,
        old_value={"iskonto_limiti_yuzde": str(eski) if eski is not None else None},
        new_value={
            "iskonto_limiti_yuzde": (
                str(payload.iskonto_limiti_yuzde)
                if payload.iskonto_limiti_yuzde is not None
                else None
            )
        },
        user_id=admin.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(u)
    return await _kisi_satiri(u, await iskonto.rol_limitleri(db))
