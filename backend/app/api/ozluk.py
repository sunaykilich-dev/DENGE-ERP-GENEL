"""Personel özlük dosyası uçları (2026-11-20, kullanıcı isteği).

Erişim (kullanıcı kararı; modele bkz. `models/ozluk.py`):

- `ik_belge.yonet` (İK): türleri yönetir; kapsamındaki personelin belgelerini
  yükler, görür, siler.
- Personelin kendisi: kendi belgelerini görür ve indirir (`/benim`); kendi
  dosyasına belge yükler (`POST /benim`, 2026-11-23). Bu belge İK onaylayana
  dek `ONAY_BEKLIYOR`dır: işte paylaşılmaz, geçerli belge sayılmaz.
- İK onay bekleyenleri listeler (`/bekleyenler`), onaylar ya da gerekçeyle
  reddeder. Bildirim hesaplanır (`services/ozluk.py`, uyarı "ozluk.onay").
- İş bazlı (`servis.planla` ya da `operasyon.gor`, iş kapsamda): işe aktif
  atanmış personelin, türü `is_paylasimi` olan belgelerini görür ve indirir.

Her görüntüleme/indirme kişisel veri olarak denetime yazılır.

Yollar (`/api/ozluk`):
- `GET /turler` (oturum) · `POST /turler`, `PATCH /turler/{id}` (İK)
- `GET /benim` · `POST /benim` (kendi yüklemesi, dosya)
- `GET /kisi/{user_id}` (İK) · `POST /kisi/{user_id}` (İK, dosya)
- `GET /bekleyenler` (İK) · `POST /belgeler/{id}/onayla`, `POST /belgeler/{id}/reddet` (İK)
- `DELETE /belgeler/{id}` (İK) · `GET /belgeler/{id}/dosya[?is_id=]`
- `GET /is/{so_id}` (iş bazlı ekip belgeleri)
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.attachments import _dosya_adi_basligi
from app.api.deps import (
    ClockDep,
    CurrentUser,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
)
from app.models import (
    OzlukBelgesi,
    OzlukBelgeTuru,
    ServiceOrder,
    ServiceOrderAssignment,
    User,
)
from app.services import audit
from app.services import ozluk as ozluk_svc
from app.services import storage as depo
from app.services.teknik_servis import kapsam

router = APIRouter(prefix="/api/ozluk", tags=["ozluk"])

IK_IZNI = "ik_belge.yonet"
IkYonetici = Annotated[User, Depends(require_permission(IK_IZNI))]
IsBazli = Annotated[User, Depends(require_any_permission("servis.planla", "operasyon.gor"))]


# --- Şemalar ---------------------------------------------------------------------------


class TurGirdisi(BaseModel):
    ad: str = Field(min_length=2, max_length=80)
    is_paylasimi: bool = False


class TurDegisikligi(BaseModel):
    version: int
    ad: str | None = Field(default=None, min_length=2, max_length=80)
    is_paylasimi: bool | None = None
    aktif: bool | None = None
    sira: int | None = Field(default=None, ge=0, le=10_000)


class KararGirdisi(BaseModel):
    version: int


class RedGirdisi(BaseModel):
    version: int
    gerekce: str = Field(min_length=3, max_length=500)


def _tur(t: OzlukBelgeTuru) -> dict[str, Any]:
    return {
        "id": t.id,
        "ad": t.ad,
        "sira": t.sira,
        "aktif": t.aktif,
        "is_paylasimi": t.is_paylasimi,
        "version": t.version,
    }


def _belge(b: OzlukBelgesi) -> dict[str, Any]:
    return {
        "id": b.id,
        "user_id": b.user_id,
        "tur_id": b.tur_id,
        "dosya_adi": b.dosya_adi,
        "mime_type": b.mime_type,
        "size_bytes": b.size_bytes,
        "gecerlilik_bitis": b.gecerlilik_bitis,
        "aciklama": b.aciklama,
        "created_at": b.created_at,
        "durum": b.durum,
        "red_gerekcesi": b.red_gerekcesi,
        "karar_at": b.karar_at,
        "version": b.version,
    }


# --- Yardımcılar -----------------------------------------------------------------------


async def _turler(db, *, tumu: bool = False) -> list[OzlukBelgeTuru]:
    stmt = select(OzlukBelgeTuru).order_by(OzlukBelgeTuru.sira, OzlukBelgeTuru.ad)
    if not tumu:
        stmt = stmt.where(OzlukBelgeTuru.aktif.is_(True))
    return list((await db.scalars(stmt)).all())


async def _dosya_turleri(db, belgeler) -> list[OzlukBelgeTuru]:
    """Etkin türler + kaldırılmış ama kişide belgesi olan türler (gerçek adıyla
    klasörlenir; "Kaldırılmış tür" diye toplanmaz — rol testi 2026-11-20)."""
    turler = await _turler(db)
    eksik = {b.tur_id for b in belgeler} - {t.id for t in turler}
    if eksik:
        turler += (
            await db.scalars(select(OzlukBelgeTuru).where(OzlukBelgeTuru.id.in_(eksik)))
        ).all()
    return turler


# Özlük belgesi: PDF, fotoğraf ya da Word (arayüzün söylediği). Depo .txt/.csv/
# .xlsx'i de kabul eder; özlükte bunlar belge değildir (rol testi 2026-11-20).
OZLUK_TIPLERI = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)


async def _dosyayi_yaz(dosya: UploadFile) -> tuple[str, Any]:
    """Yüklenen dosyayı denetleyip depoya yazar (İK ve kişi yüklemesi aynı kural)."""
    ad = depo.temiz_ad(dosya.filename or "belge")
    try:
        icerik = await depo.sinirli_oku(dosya)
        mime = depo.mime_coz(dosya.content_type or "", ad)
        if mime not in OZLUK_TIPLERI:
            raise depo.DepoHatasi(
                "Yalnız PDF, fotoğraf (JPG, PNG, WEBP, HEIC) ya da Word (DOCX) yüklenebilir"
            )
        return ad, depo.yaz(icerik, mime_type=mime)
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


async def _etkin_tur(db, tur_id: int) -> OzlukBelgeTuru:
    tur = await db.get(OzlukBelgeTuru, tur_id)
    if tur is None or not tur.aktif:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçerli bir belge türü seçin")
    return tur


async def _kisi_kapsamda_mi(db, user: User, kisi_id: int) -> bool:
    """İK için: personel kapsamındaki kişi mi (personel listesiyle aynı kural)."""
    stmt = kapsam.kapsam_personel(select(User.id).where(User.id == kisi_id), user, User.id)
    return (await db.scalar(stmt)) is not None


async def _kisi_belgeleri(
    db, kisi_id: int, tur_idler: set[int] | None = None, *, yalniz_onayli: bool = False
) -> list:
    stmt = select(OzlukBelgesi).where(
        OzlukBelgesi.user_id == kisi_id, OzlukBelgesi.is_deleted.is_(False)
    )
    if tur_idler is not None:
        stmt = stmt.where(OzlukBelgesi.tur_id.in_(tur_idler))
    if yalniz_onayli:
        stmt = stmt.where(OzlukBelgesi.durum == ozluk_svc.ONAYLANDI)
    return list((await db.scalars(stmt.order_by(OzlukBelgesi.created_at.desc()))).all())


async def _is_ve_ekip(db, user: User, so_id: int) -> tuple[ServiceOrder, set[int]]:
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    ekip = set(
        (
            await db.scalars(
                select(ServiceOrderAssignment.user_id).where(
                    ServiceOrderAssignment.service_order_id == so_id,
                    ServiceOrderAssignment.removed_at.is_(None),
                )
            )
        ).all()
    )
    return so, ekip


async def _gorme(db, request: Request, user: User, kisi_id: int, eylem: str, **ek) -> None:
    await audit.log(
        db,
        "ozluk_belgeleri",
        eylem,
        entity_id=kisi_id,
        new_value=ek or None,
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )


# --- Türler ----------------------------------------------------------------------------


@router.get("/turler")
async def turler(db: DbDep, user: CurrentUser, tumu: bool = False) -> list[dict[str, Any]]:
    """Belge türleri; `tumu=true` (yalnız İK) kaldırılmışları da döner."""
    return [_tur(t) for t in await _turler(db, tumu=tumu and user.has(IK_IZNI))]


@router.post("/turler", status_code=status.HTTP_201_CREATED)
async def tur_ekle(
    payload: TurGirdisi, request: Request, db: DbDep, user: IkYonetici
) -> dict[str, Any]:
    ad = payload.ad.strip()
    if await db.scalar(
        select(OzlukBelgeTuru.id).where(
            func.lower(OzlukBelgeTuru.ad) == ad.lower(), OzlukBelgeTuru.aktif.is_(True)
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Bu adla bir tür zaten var: {ad}")
    sira = int(await db.scalar(select(func.coalesce(func.max(OzlukBelgeTuru.sira), 0))) or 0)
    tur = OzlukBelgeTuru(
        ad=ad, is_paylasimi=payload.is_paylasimi, sira=sira + 10, created_by=user.id
    )
    db.add(tur)
    await db.flush()
    await audit.log(
        db, "ozluk_belge_turleri", "create", entity_id=tur.id, new_value=_tur(tur),
        user_id=user.id, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return _tur(tur)


@router.patch("/turler/{tur_id}")
async def tur_degistir(
    tur_id: int, payload: TurDegisikligi, request: Request, db: DbDep, user: IkYonetici
) -> dict[str, Any]:
    tur = await db.get(OzlukBelgeTuru, tur_id)
    if tur is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belge türü bulunamadı")
    if tur.version != payload.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin"
        )
    eski = _tur(tur)
    degisen = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "ad" in degisen:
        degisen["ad"] = degisen["ad"].strip()
        cakisan = await db.scalar(
            select(OzlukBelgeTuru.id).where(
                func.lower(OzlukBelgeTuru.ad) == degisen["ad"].lower(),
                OzlukBelgeTuru.aktif.is_(True),
                OzlukBelgeTuru.id != tur.id,
            )
        )
        if cakisan:
            raise HTTPException(status.HTTP_409_CONFLICT, "Bu adla bir tür zaten var")
    for alan, deger in degisen.items():
        setattr(tur, alan, deger)
    tur.updated_by = user.id
    await db.flush()
    await audit.log(
        db, "ozluk_belge_turleri", "update", entity_id=tur.id, old_value=eski,
        new_value=_tur(tur), user_id=user.id, ip=client_ip(request),
    )  # fmt: skip
    await db.commit()
    return _tur(tur)


# --- Kişi belgeleri --------------------------------------------------------------------


@router.get("/benim")
async def benim(db: DbDep, user: CurrentUser) -> dict[str, Any]:
    """Personelin kendi özlük belgeleri; onay bekleyen ve reddedilenler dahil
    (durum ve red gerekçesiyle). Silme İK'dadır."""
    belgeler = await _kisi_belgeleri(db, user.id)
    return {
        "turler": [_tur(t) for t in await _dosya_turleri(db, belgeler)],
        "belgeler": [_belge(b) for b in belgeler],
    }


@router.post("/benim", status_code=status.HTTP_201_CREATED)
async def kendi_yuklemesi(
    request: Request,
    db: DbDep,
    user: CurrentUser,
    tur_id: Annotated[int, Form()],
    dosya: Annotated[UploadFile, File()],
    gecerlilik_bitis: Annotated[date | None, Form()] = None,
    aciklama: Annotated[str | None, Form(max_length=500)] = None,
) -> dict[str, Any]:
    """Personel kendi dosyasına belge yükler (kişi kendisi; izin gerekmez).
    Belge İK onaylayana dek `ONAY_BEKLIYOR`dır; İK'ya uyarı olarak düşer."""
    tur = await _etkin_tur(db, tur_id)
    ad, kayit = await _dosyayi_yaz(dosya)
    belge = OzlukBelgesi(
        user_id=user.id,
        tur_id=tur.id,
        dosya_adi=ad,
        storage_path=kayit.storage_path,
        mime_type=kayit.mime_type,
        size_bytes=kayit.size_bytes,
        sha256=kayit.sha256,
        gecerlilik_bitis=gecerlilik_bitis,
        aciklama=(aciklama or "").strip() or None,
        durum=ozluk_svc.ONAY_BEKLIYOR,
        created_by=user.id,
    )
    db.add(belge)
    await db.flush()
    await _gorme(db, request, user, user.id, "kendi_yukle", belge_id=belge.id, tur=tur.ad)
    await db.commit()
    return _belge(belge)


@router.get("/bekleyenler")
async def bekleyenler(request: Request, db: DbDep, user: IkYonetici) -> list[dict[str, Any]]:
    """İK: kapsamındaki personelin onay bekleyen belgeleri (eskiden yeniye)."""
    stmt = ozluk_svc.bekleyen_kosulu(
        select(OzlukBelgesi, User.full_name, OzlukBelgeTuru.ad)
        .join(User, User.id == OzlukBelgesi.user_id)
        .join(OzlukBelgeTuru, OzlukBelgeTuru.id == OzlukBelgesi.tur_id),
        user,
    ).order_by(OzlukBelgesi.created_at)
    satirlar = (await db.execute(stmt)).all()
    if satirlar:
        kisiler = sorted({b.user_id for b, _, _ in satirlar})
        await _gorme(db, request, user, 0, "bekleyen_listesi", kisiler=kisiler)
        await db.commit()
    return [{**_belge(b), "kisi_adi": ad, "tur_adi": tur_ad} for b, ad, tur_ad in satirlar]


async def _karar_belgesi(db, user: User, belge_id: int, version: int) -> OzlukBelgesi:
    belge = await db.get(OzlukBelgesi, belge_id)
    if belge is None or belge.is_deleted or not await _kisi_kapsamda_mi(db, user, belge.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belge bulunamadı")
    if belge.version != version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin"
        )
    if belge.durum != ozluk_svc.ONAY_BEKLIYOR:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu belge onay beklemiyor")
    return belge


@router.post("/belgeler/{belge_id}/onayla")
async def onayla(
    belge_id: int,
    payload: KararGirdisi,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IkYonetici,
) -> dict[str, Any]:
    belge = await _karar_belgesi(db, user, belge_id, payload.version)
    belge.durum = ozluk_svc.ONAYLANDI
    belge.karar_veren_id = user.id
    belge.karar_at = clock.now()
    belge.updated_by = user.id
    await db.flush()
    await _gorme(db, request, user, belge.user_id, "onayla", belge_id=belge.id)
    await db.commit()
    return _belge(belge)


@router.post("/belgeler/{belge_id}/reddet")
async def reddet(
    belge_id: int,
    payload: RedGirdisi,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IkYonetici,
) -> dict[str, Any]:
    gerekce = payload.gerekce.strip()
    if len(gerekce) < 3:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Red gerekçesi yazın")
    belge = await _karar_belgesi(db, user, belge_id, payload.version)
    belge.durum = ozluk_svc.REDDEDILDI
    belge.red_gerekcesi = gerekce
    belge.karar_veren_id = user.id
    belge.karar_at = clock.now()
    belge.updated_by = user.id
    await db.flush()
    await _gorme(db, request, user, belge.user_id, "reddet", belge_id=belge.id)
    await db.commit()
    return _belge(belge)


@router.get("/kisi/{kisi_id}")
async def kisi(kisi_id: int, request: Request, db: DbDep, user: IkYonetici) -> dict[str, Any]:
    if not await _kisi_kapsamda_mi(db, user, kisi_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    belgeler = await _kisi_belgeleri(db, kisi_id)
    await _gorme(db, request, user, kisi_id, "liste")
    await db.commit()
    return {
        "turler": [_tur(t) for t in await _dosya_turleri(db, belgeler)],
        "belgeler": [_belge(b) for b in belgeler],
    }


@router.post("/kisi/{kisi_id}", status_code=status.HTTP_201_CREATED)
async def yukle(
    kisi_id: int,
    request: Request,
    db: DbDep,
    user: IkYonetici,
    tur_id: Annotated[int, Form()],
    dosya: Annotated[UploadFile, File()],
    gecerlilik_bitis: Annotated[date | None, Form()] = None,
    aciklama: Annotated[str | None, Form(max_length=500)] = None,
) -> dict[str, Any]:
    if not await _kisi_kapsamda_mi(db, user, kisi_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    tur = await _etkin_tur(db, tur_id)
    ad, kayit = await _dosyayi_yaz(dosya)
    # İK'nın yüklediği belge doğrudan onaylıdır (bugünkü akış).
    belge = OzlukBelgesi(
        user_id=kisi_id,
        tur_id=tur.id,
        dosya_adi=ad,
        storage_path=kayit.storage_path,
        mime_type=kayit.mime_type,
        size_bytes=kayit.size_bytes,
        sha256=kayit.sha256,
        gecerlilik_bitis=gecerlilik_bitis,
        aciklama=(aciklama or "").strip() or None,
        created_by=user.id,
    )
    db.add(belge)
    await db.flush()
    await _gorme(db, request, user, kisi_id, "yukle", belge_id=belge.id, tur=tur.ad)
    await db.commit()
    return _belge(belge)


@router.delete("/belgeler/{belge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def sil(belge_id: int, request: Request, db: DbDep, clock: ClockDep, user: IkYonetici):
    belge = await db.get(OzlukBelgesi, belge_id)
    if belge is None or belge.is_deleted or not await _kisi_kapsamda_mi(db, user, belge.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belge bulunamadı")
    belge.is_deleted = True
    belge.deleted_at = clock.now()
    belge.deleted_by = user.id
    await _gorme(db, request, user, belge.user_id, "sil", belge_id=belge.id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/belgeler/{belge_id}/dosya")
async def dosya(
    belge_id: int, request: Request, db: DbDep, user: CurrentUser, is_id: int | None = None
) -> Response:
    """Belgeyi açar. İzin: İK (kapsam), kişinin kendisi ya da `is_id` ile iş bazlı
    (iş kapsamda, kişi işe aktif atanmış, tür işte paylaşılabilir, belge İK
    onaylı)."""
    belge = await db.get(OzlukBelgesi, belge_id)
    if belge is None or belge.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belge bulunamadı")
    izinli = belge.user_id == user.id or (
        user.has(IK_IZNI) and await _kisi_kapsamda_mi(db, user, belge.user_id)
    )
    is_bazli = user.has("servis.planla") or user.has("operasyon.gor")
    if not izinli and is_id is not None and is_bazli:
        _, ekip = await _is_ve_ekip(db, user, is_id)
        tur = await db.get(OzlukBelgeTuru, belge.tur_id)
        izinli = (
            belge.user_id in ekip
            and belge.durum == ozluk_svc.ONAYLANDI
            and tur is not None
            and tur.aktif
            and tur.is_paylasimi
        )
    if not izinli:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belge bulunamadı")
    await _gorme(db, request, user, belge.user_id, "goruntule", belge_id=belge.id, is_id=is_id)
    await db.commit()
    try:
        yol = depo.yol(belge.storage_path)
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(
        content=yol.read_bytes(),
        media_type=belge.mime_type,
        headers={
            "Content-Disposition": f"inline; {_dosya_adi_basligi(belge.dosya_adi)}",
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )


# --- İş bazlı erişim -------------------------------------------------------------------


@router.get("/is/{so_id}")
async def is_ekibi(so_id: int, request: Request, db: DbDep, user: IsBazli) -> dict[str, Any]:
    """Servis işine aktif atanmış personelin işte paylaşılabilir, İK onaylı belgeleri."""
    _, ekip = await _is_ve_ekip(db, user, so_id)
    turler = [t for t in await _turler(db) if t.is_paylasimi]
    tur_idler = {t.id for t in turler}
    kisiler = []
    if ekip and tur_idler:
        for kisi in (
            await db.scalars(select(User).where(User.id.in_(ekip)).order_by(User.full_name))
        ).all():
            belgeler = await _kisi_belgeleri(db, kisi.id, tur_idler, yalniz_onayli=True)
            kisiler.append(
                {
                    "user_id": kisi.id,
                    "ad": kisi.full_name,
                    "belgeler": [_belge(b) for b in belgeler],
                }
            )
        await _gorme(db, request, user, 0, "is_listesi", is_id=so_id, kisiler=sorted(ekip))
        await db.commit()
    return {"turler": [_tur(t) for t in turler], "kisiler": kisiler}
