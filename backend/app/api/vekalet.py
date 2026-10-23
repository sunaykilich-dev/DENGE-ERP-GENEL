"""Süreli vekâlet (TS-213, E13-15, E07-D03) — `/api/vekalet`.

**Neden:** izne çıkan müdürün planlama/onay işini birine birkaç günlüğüne
bırakmak için bugüne kadar iki yol vardı: ya kişiye kalıcı istisna yazılıyor
ve geri almak unutuluyordu, ya da müdürün parolası paylaşılıyordu. Vekâlet,
`user_permissions` satırının SÜRELİ hâlidir (`baslangic_at`/`bitis_at`/
`veren_id`, d4a000000002): süre dolunca istek anındaki kontrol izni kendiliğinden
düşürür, worker'a bağlı değildir.

Kurallar (`services/yetki.py`):
- yalnız `vekalet.ver` sahibi verir (SERVIS_YONETICI, ADMIN);
- `VEKALETE_KAPALI` izinler verilemez (403 + `yetki.ret` denetimi);
- veren yalnız KENDİ kalıcı etkin izinlerinin alt kümesini verir (403);
- en fazla 30 gün (400; şemada `ck_user_permissions_vekalet`), kendine 400;
- alıcı kapsam dışındaysa 404 (personel kapsamı, `kapsam.personel_disinda_mi`);
- verme ve iptalde alıcının oturumları düşer (yetki değişti).

İptal: veren ya da ADMIN. Başlamamış vekâlet silinir, başlamış olan `an`
anında biter (satır denetim için kalır).

Router `main.py`'ye değil `api/users.py` router'ına bağlıdır (Dalga 4'te
`main.py` D4-S'te donmuş; yol yine `/api/vekalet`).
"""

from datetime import datetime, timedelta
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import User, UserPermission
from app.models.rbac import VEKALET_AZAMI_GUN
from app.permissions import PERMISSIONS, VEKALETE_KAPALI
from app.services import audit, yetki
from app.services import auth as auth_service
from app.services.teknik_servis import kapsam

router = APIRouter(prefix="/vekalet", tags=["vekalet"])

Verici = Annotated[User, Depends(require_permission("vekalet.ver"))]

VEKALET_DURUMLARI = ("BASLAMADI", "YURURLUKTE", "SONA_ERDI")


class VekaletIn(BaseModel):
    izinler: list[str] = Field(min_length=1, max_length=20)
    # Boşsa ŞİMDİ başlar; geçmiş bir an verilirse de şimdiye çekilir (geriye
    # dönük yetki verilmez).
    baslangic_at: datetime | None = None
    bitis_at: datetime
    gerekce: str = Field(min_length=5, max_length=300)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "izinler": ["servis.planla"],
                    "bitis_at": "2026-01-20T18:00:00+03:00",
                    "gerekce": "Yıllık izin süresince planlama vekâleti",
                }
            ]
        }
    }


class VekaletIptalIn(BaseModel):
    izin: str = Field(min_length=3, max_length=50)

    model_config = {"json_schema_extra": {"examples": [{"izin": "servis.planla"}]}}


class VerilebilirIzin(BaseModel):
    kod: str
    modul: str
    aciklama: str


class VekaletOut(BaseModel):
    personel_id: int
    personel_adi: str
    izin: str
    izin_aciklama: str
    baslangic_at: datetime
    bitis_at: datetime
    gerekce: str | None
    veren_id: int | None
    veren_adi: str | None
    durum: str


def _durum(satir: UserPermission, an: datetime) -> str:
    if satir.bitis_at <= an:
        return "SONA_ERDI"
    if satir.baslangic_at > an:
        return "BASLAMADI"
    return "YURURLUKTE"


def _cikti(satir: UserPermission, kisi_adi: str, veren_adi: str | None, an: datetime) -> VekaletOut:
    return VekaletOut(
        personel_id=satir.user_id,
        personel_adi=kisi_adi,
        izin=satir.permission_code,
        izin_aciklama=PERMISSIONS.get(satir.permission_code, ("", satir.permission_code))[1],
        baslangic_at=satir.baslangic_at,
        bitis_at=satir.bitis_at,
        gerekce=satir.gerekce,
        veren_id=satir.veren_id,
        veren_adi=veren_adi,
        durum=_durum(satir, an),
    )


async def _reddet(
    db, request: Request, aktor: User, hedef_id: int, durum: int, mesaj: str, ayrinti: dict
) -> NoReturn:
    """Ret de bir güvenlik olayıdır: denetime yazılır, sonra HTTP hatası."""
    await audit.log(
        db,
        "users",
        "yetki.ret",
        entity_id=hedef_id,
        new_value={"neden": mesaj, "islem": "vekalet", **ayrinti},
        user_id=aktor.id,
        ip=client_ip(request),
    )
    await db.commit()
    raise HTTPException(durum, mesaj)


async def _hedef(db, aktor: User, personel_id: int) -> User:
    """Alıcı/kişi: yoksa ya da aktörün personel kapsamı dışındaysa 404."""
    hedef = await db.get(User, personel_id)
    if hedef is None or await kapsam.personel_disinda_mi(db, aktor, personel_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    return hedef


async def _kisi_vekaletleri(db, hedef: User, an: datetime) -> list[VekaletOut]:
    veren = aliased(User)
    satirlar = (
        await db.execute(
            select(UserPermission, veren.full_name)
            .outerjoin(veren, veren.id == UserPermission.veren_id)
            .where(UserPermission.user_id == hedef.id, UserPermission.bitis_at.is_not(None))
            .order_by(UserPermission.bitis_at.desc(), UserPermission.permission_code)
        )
    ).all()
    return [_cikti(s, hedef.full_name, veren_adi, an) for s, veren_adi in satirlar]


@router.get("/verilebilir", response_model=list[VerilebilirIzin])
async def verilebilir_izinler(user: Verici) -> list[VerilebilirIzin]:
    """Bu kullanıcının vekâlet olarak verebileceği izinler (kendi kalıcı
    izinleri − `VEKALETE_KAPALI`)."""
    kodlar = sorted(yetki.kalici_etkin_izinler(user) - VEKALETE_KAPALI)
    return [
        VerilebilirIzin(kod=k, modul=PERMISSIONS[k][0], aciklama=PERMISSIONS[k][1])
        for k in kodlar
        if k in PERMISSIONS
    ]


@router.get("", response_model=list[VekaletOut])
async def vekalet_listesi(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Verici,
    durum: str | None = Query(None, pattern="^(BASLAMADI|YURURLUKTE|SONA_ERDI)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[VekaletOut]:
    """Kapsamdaki personelin vekâletleri, en yeni bitiş önce. Toplam
    `X-Toplam-Kayit` başlığında."""
    an = clock.now()
    kisi = aliased(User)
    veren = aliased(User)
    stmt = (
        select(UserPermission, kisi.full_name, veren.full_name)
        .join(kisi, kisi.id == UserPermission.user_id)
        .outerjoin(veren, veren.id == UserPermission.veren_id)
        .where(UserPermission.bitis_at.is_not(None))
        .order_by(UserPermission.bitis_at.desc(), UserPermission.user_id)
    )
    stmt = kapsam.kapsam_personel(stmt, user, UserPermission.user_id)
    if durum == "SONA_ERDI":
        stmt = stmt.where(UserPermission.bitis_at <= an)
    elif durum == "BASLAMADI":
        stmt = stmt.where(UserPermission.baslangic_at > an)
    elif durum == "YURURLUKTE":
        stmt = stmt.where(UserPermission.baslangic_at <= an, UserPermission.bitis_at > an)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [_cikti(s, kisi_adi, veren_adi, an) for s, kisi_adi, veren_adi in satirlar]


@router.get("/{personel_id}", response_model=list[VekaletOut])
async def kisi_vekaletleri(
    personel_id: int, db: DbDep, clock: ClockDep, user: Verici
) -> list[VekaletOut]:
    hedef = await _hedef(db, user, personel_id)
    return await _kisi_vekaletleri(db, hedef, clock.now())


@router.post("/{personel_id}", response_model=list[VekaletOut], status_code=status.HTTP_201_CREATED)
async def vekalet_ver(
    personel_id: int,
    payload: VekaletIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Verici,
) -> list[VekaletOut]:
    """Süreli vekâlet verir. Alıcının açık oturumları düşer."""
    hedef = await _hedef(db, user, personel_id)
    if hedef.id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kendinize vekâlet veremezsiniz.")
    try:
        yetki.hedef_kontrol(user, hedef)
    except yetki.YetkiHatasi as e:
        await _reddet(db, request, user, hedef.id, status.HTTP_403_FORBIDDEN, str(e), {})
    if not hedef.giris_yapabilir_mi():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Girişi kapalı ya da ayrılmış kişiye vekâlet verilemez."
        )
    izinler = sorted(set(payload.izinler))
    if bilinmeyen := [k for k in izinler if k not in PERMISSIONS]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bilinmeyen izin: {', '.join(bilinmeyen)}"
        )
    kapali, eksik = yetki.vekalet_verilemeyenler(user, izinler)
    if kapali:
        await _reddet(
            db,
            request,
            user,
            hedef.id,
            status.HTTP_403_FORBIDDEN,
            f"Bu izinler vekâletle verilemez: {', '.join(kapali)}",
            {"izinler": kapali},
        )
    if eksik:
        await _reddet(
            db,
            request,
            user,
            hedef.id,
            status.HTTP_403_FORBIDDEN,
            f"Sizde kalıcı olarak bulunmayan izinler devredilemez: {', '.join(eksik)}",
            {"izinler": eksik},
        )

    an = clock.now()
    for zaman in (payload.baslangic_at, payload.bitis_at):
        if zaman is not None and zaman.tzinfo is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Zaman saat dilimiyle verilmeli (ör. +03:00)."
            )
    baslangic = max(payload.baslangic_at or an, an)
    bitis = payload.bitis_at
    if bitis <= baslangic:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bitiş, başlangıçtan sonra olmalı.")
    if bitis - baslangic > timedelta(days=VEKALET_AZAMI_GUN):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Vekâlet en fazla {VEKALET_AZAMI_GUN} gün olabilir."
        )

    rol_izinleri = {rp.permission_code for rp in hedef.role.permissions}
    mevcut = {ui.permission_code: ui for ui in hedef.izin_istisnalari}
    cakisma: list[str] = []
    for kod in izinler:
        satir = mevcut.get(kod)
        if satir is not None and not satir.sureli_mi:
            cakisma.append(f"{kod}: kişiye özel kalıcı {'izin' if satir.allow else 'kısıt'} var")
        elif satir is not None and satir.bitis_at > an:
            cakisma.append(f"{kod}: süren ya da başlayacak bir vekâlet var; önce iptal edin")
        elif kod in rol_izinleri:
            cakisma.append(f"{kod}: rolünde zaten var")
    if cakisma:
        raise HTTPException(status.HTTP_409_CONFLICT, "; ".join(cakisma))

    for kod in izinler:
        satir = mevcut.get(kod)
        if satir is None:
            satir = UserPermission(user_id=hedef.id, permission_code=kod)
            hedef.izin_istisnalari.append(satir)
        # Süresi dolmuş eski vekâlet satırı yeniden kullanılır (PK kişi+izin);
        # eski dönem denetim kaydında kalır.
        satir.allow = True
        satir.gerekce = payload.gerekce
        satir.baslangic_at = baslangic
        satir.bitis_at = bitis
        satir.veren_id = user.id
    await db.flush()
    await auth_service.revoke_all_sessions(db, hedef.id)
    await audit.log(
        db,
        "users",
        "vekalet.ver",
        entity_id=hedef.id,
        new_value={
            "izinler": izinler,
            "baslangic": yetki.zaman_metni(baslangic),
            "bitis": yetki.zaman_metni(bitis),
            "veren_id": user.id,
            "gerekce": payload.gerekce,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _kisi_vekaletleri(db, hedef, an)


@router.post("/{personel_id}/iptal", response_model=list[VekaletOut])
async def vekalet_iptal(
    personel_id: int,
    payload: VekaletIptalIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Verici,
) -> list[VekaletOut]:
    """Vekâleti erken bitirir (veren ya da sistem yöneticisi)."""
    hedef = await _hedef(db, user, personel_id)
    an = clock.now()
    satir = next(
        (
            ui
            for ui in hedef.izin_istisnalari
            if ui.permission_code == payload.izin and ui.sureli_mi
        ),
        None,
    )
    if satir is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bu izin için vekâlet yok")
    if satir.veren_id != user.id and not yetki.admin_mi(user):
        await _reddet(
            db,
            request,
            user,
            hedef.id,
            status.HTTP_403_FORBIDDEN,
            "Vekâleti yalnız veren ya da sistem yöneticisi iptal edebilir.",
            {"izin": payload.izin},
        )
    if satir.bitis_at <= an:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu vekâletin süresi zaten dolmuş.")
    await yetki.vekaleti_sonlandir(
        db, satir, an=an, aktor_id=user.id, ip=client_ip(request), neden="iptal"
    )
    await auth_service.revoke_all_sessions(db, hedef.id)
    await db.commit()
    await db.refresh(hedef)
    return await _kisi_vekaletleri(db, hedef, an)
