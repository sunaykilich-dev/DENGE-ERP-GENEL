"""Erişim gözden geçirme listesi (TS-214, E13-16) — `/api/erisim-gozden`.

**Neden:** "kimde ne yetki var, kim aylardır girmiyor, kim ayrıldığı hâlde
hesabı açık" soruları bugüne kadar Kullanıcılar ekranında tek tek satır
açılarak cevaplanıyordu; periyodik erişim gözden geçirmesi (KVKK teknik
tedbir, ISO 27001 A.5.18) kayıt bırakmıyordu.

- KPI kutuları TIKLANABİLİR: kutudaki sayı, aynı `kpi` ile açılan listenin
  `X-Toplam-Kayit` toplamıdır — ikisi AYNI koşul fonksiyonundan (`_kosul`)
  üretilir, ayrı sayım yazılmaz.
- Ayrı tablo YOK: "gözden geçirildi" işareti yalnız denetim kaydıdır
  (`erisim.gozden_gecirildi`); listedeki son işaret tarihi denetimden okunur.
- Excel: `sistem.kullanici` + `rapor.disaaktar`, dışa aktarım denetime yazılır.

Yetki `sistem.kullanici` (yalnız ADMIN). Router `api/users.py` router'ına
bağlıdır (`main.py` Dalga 4'te D4-S'te donmuş).
"""

from datetime import date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, exists, false, func, or_, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import AuditLog, LoginAttempt, Role, RolePermission, User, UserPermission
from app.permissions import YUKSEK_YETKILI_IZINLER
from app.services import audit
from app.services import export as export_svc
from app.services import settings as ayar_svc
from app.services.teknik_servis import kapsam

router = APIRouter(prefix="/erisim-gozden", tags=["erisim-gozden"])

Yonetici = Annotated[User, Depends(require_permission("sistem.kullanici"))]
Disaaktaran = Annotated[User, Depends(require_permission("sistem.kullanici", "rapor.disaaktar"))]

# Hassas = yüksek yetki + maliyet görme (E13-16).
HASSAS_IZINLER = frozenset(YUKSEK_YETKILI_IZINLER | {"maliyet.gor"})
GOZDEN_GECIRILDI = "erisim.gozden_gecirildi"
# Eşik `erisim_girissiz_gun` ayarından okunur (varsayılan 60); bu sabit yalnız
# ayar okunamazsa kullanılır. Sorgu parametresi `gun` ile de değiştirilebilir.
# Güvenlik sabiti DEĞİLDİR (E13-16).
GIRISSIZ_GUN_VARSAYILAN = 60
_TR = ZoneInfo("Europe/Istanbul")

KPI_TANIMLARI: dict[str, tuple[str, str]] = {
    "hassas_izin": (
        "Hassas izin",
        "Sistem yönetimi, denetim, KVKK ya da maliyet görme izni olan aktif hesaplar",
    ),
    "sapma": ("Rolünden farklı", "Kişiye özel kalıcı istisnası ya da yürürlükte vekâleti olanlar"),
    "uzun_girissiz": ("Uzun süredir girişsiz", "Girişi açık ama eşikten uzun süredir girmeyenler"),
    "ayrilmis_hesap_acik": ("Ayrılmış, hesabı açık", "Ayrılış tarihi dolu ama girişi açık"),
    "kilitli": ("Kilitli", "Hatalı denemeler nedeniyle kilitli hesaplar"),
}


async def _girissiz_gun(db, gun: int | None) -> int:
    if gun is not None:
        return gun
    try:
        return int(await ayar_svc.get(db, "erisim_girissiz_gun"))
    except KeyError:
        return GIRISSIZ_GUN_VARSAYILAN


def _aktif_hesap() -> ColumnElement[bool]:
    return and_(User.is_active.is_(True), User.giris_acik.is_(True))


def _yururlukte(an: datetime) -> ColumnElement[bool]:
    return or_(
        UserPermission.bitis_at.is_(None),
        and_(UserPermission.baslangic_at <= an, UserPermission.bitis_at > an),
    )


def _kosul(kpi: str, an: datetime, gun: int) -> ColumnElement[bool]:
    """KPI'nın kullanıcı koşulu — kutu sayısı ve liste AYNI fonksiyondan."""
    if kpi == "hassas_izin":
        rolde = exists().where(
            RolePermission.role_id == User.role_id,
            RolePermission.permission_code.in_(sorted(HASSAS_IZINLER)),
        )
        istisnada = exists().where(
            UserPermission.user_id == User.id,
            UserPermission.allow.is_(True),
            UserPermission.permission_code.in_(sorted(HASSAS_IZINLER)),
            _yururlukte(an),
        )
        return and_(_aktif_hesap(), or_(rolde, istisnada))
    if kpi == "sapma":
        return and_(
            _aktif_hesap(),
            exists().where(UserPermission.user_id == User.id, _yururlukte(an)),
        )
    if kpi == "uzun_girissiz":
        sinir = an - timedelta(days=gun)
        return and_(_aktif_hesap(), func.coalesce(User.son_giris_at, User.created_at) < sinir)
    if kpi == "ayrilmis_hesap_acik":
        return and_(User.ayrilis_tarihi.is_not(None), User.giris_acik.is_(True))
    if kpi == "kilitli":
        return exists().where(
            LoginAttempt.username == User.username, LoginAttempt.kilitlendi_at.is_not(None)
        )
    return false()


def _sorgu(user: User, kpi: str | None, an: datetime, gun: int, q: str | None):
    stmt = select(User).order_by(User.full_name)
    stmt = kapsam.kapsam_personel(stmt, user, User.id)
    if kpi:
        stmt = stmt.where(_kosul(kpi, an, gun))
    if q:
        desen = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(desen), User.username.ilike(desen)))
    return stmt


class KpiSatiri(BaseModel):
    kod: str
    baslik: str
    aciklama: str
    adet: int


class ErisimOzeti(BaseModel):
    girissiz_gun: int
    kpiler: list[KpiSatiri]


class ErisimSatiri(BaseModel):
    id: int
    full_name: str
    username: str
    rol_kodu: str
    rol_adi: str
    is_active: bool
    giris_acik: bool
    son_giris_at: datetime | None
    ayrilis_tarihi: date | None
    kilitli: bool
    mfa_enabled: bool
    hassas_izinler: list[str]
    sapma_sayisi: int
    vekalet_sayisi: int
    son_gozden_gecirme_at: datetime | None = None
    son_gozden_geciren: str | None = None


class GozdenGecirIn(BaseModel):
    not_: str | None = Field(default=None, alias="not", max_length=300)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {"examples": [{"not": "Çeyrek dönem gözden geçirmesi"}]},
    }


def _kpi_dogrula(kpi: str | None) -> None:
    if kpi is not None and kpi not in KPI_TANIMLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen gösterge: {kpi}")


async def _satirlar(db, kisiler: list[User], an: datetime) -> list[ErisimSatiri]:
    if not kisiler:
        return []
    kilitli = set(
        (
            await db.scalars(
                select(LoginAttempt.username).where(
                    LoginAttempt.username.in_([k.username for k in kisiler]),
                    LoginAttempt.kilitlendi_at.is_not(None),
                )
            )
        ).all()
    )
    son = (
        select(AuditLog.entity_id, func.max(AuditLog.id).label("son_id"))
        .where(
            AuditLog.entity == "users",
            AuditLog.action == GOZDEN_GECIRILDI,
            AuditLog.entity_id.in_([str(k.id) for k in kisiler]),
        )
        .group_by(AuditLog.entity_id)
        .subquery()
    )
    isaretler = {
        eid: (zaman, ad)
        for eid, zaman, ad in (
            await db.execute(
                select(AuditLog.entity_id, AuditLog.created_at, User.full_name)
                .join(son, son.c.son_id == AuditLog.id)
                .outerjoin(User, User.id == AuditLog.user_id)
            )
        ).all()
    }
    sonuc = []
    for k in kisiler:
        k.izin_anini_ata(an)
        etkin = set(k.etkin_izinler())
        zaman, ad = isaretler.get(str(k.id), (None, None))
        sonuc.append(
            ErisimSatiri(
                id=k.id,
                full_name=k.full_name,
                username=k.username,
                rol_kodu=k.role.code,
                rol_adi=k.role.name,
                is_active=k.is_active,
                giris_acik=k.giris_acik,
                son_giris_at=k.son_giris_at,
                ayrilis_tarihi=k.ayrilis_tarihi,
                kilitli=k.username in kilitli,
                mfa_enabled=k.mfa_enabled,
                hassas_izinler=sorted(etkin & HASSAS_IZINLER),
                sapma_sayisi=sum(1 for i in k.izin_istisnalari if not i.sureli_mi),
                vekalet_sayisi=sum(
                    1 for i in k.izin_istisnalari if i.sureli_mi and i.gecerli_mi(an)
                ),
                son_gozden_gecirme_at=zaman,
                son_gozden_geciren=ad,
            )
        )
    return sonuc


@router.get("/ozet", response_model=ErisimOzeti)
async def ozet(
    db: DbDep,
    clock: ClockDep,
    user: Yonetici,
    gun: int | None = Query(None, ge=7, le=365),
) -> ErisimOzeti:
    """KPI sayıları. Her sayı = `GET /api/erisim-gozden?kpi=<kod>` toplamı."""
    an = clock.now()
    esik = await _girissiz_gun(db, gun)
    kpiler = []
    for kod, (baslik, aciklama) in KPI_TANIMLARI.items():
        stmt = _sorgu(user, kod, an, esik, None)
        adet = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        kpiler.append(KpiSatiri(kod=kod, baslik=baslik, aciklama=aciklama, adet=adet or 0))
    return ErisimOzeti(girissiz_gun=esik, kpiler=kpiler)


@router.get("", response_model=list[ErisimSatiri])
async def liste(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Yonetici,
    kpi: str | None = None,
    q: str | None = Query(None, max_length=100),
    gun: int | None = Query(None, ge=7, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ErisimSatiri]:
    _kpi_dogrula(kpi)
    an = clock.now()
    stmt = _sorgu(user, kpi, an, await _girissiz_gun(db, gun), q)
    kisiler = [r[0] for r in await sayfala(db, response, stmt, limit=limit, offset=offset)]
    return await _satirlar(db, kisiler, an)


def _yerel(an: datetime | None) -> str:
    return an.astimezone(_TR).strftime("%d.%m.%Y %H:%M") if an else ""


@router.get("/excel")
async def excel(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Disaaktaran,
    kpi: str | None = None,
    gun: int | None = Query(None, ge=7, le=365),
) -> Response:
    """Gözden geçirme listesi Excel'i (aynı süzgeç, sayfalama yok)."""
    _kpi_dogrula(kpi)
    an = clock.now()
    esik = await _girissiz_gun(db, gun)
    kisiler = list((await db.scalars(_sorgu(user, kpi, an, esik, None))).all())
    satirlar = await _satirlar(db, kisiler, an)
    basliklar = [
        "Ad soyad",
        "Kullanıcı adı",
        "Rol",
        "Aktif",
        "Giriş açık",
        "Son giriş",
        "Ayrılış",
        "Kilitli",
        "MFA",
        "Hassas izinler",
        "Kalıcı istisna",
        "Vekâlet",
        "Son gözden geçirme",
        "Gözden geçiren",
    ]
    tablo: list[list[Any]] = [
        [
            s.full_name,
            s.username,
            s.rol_adi,
            "evet" if s.is_active else "hayır",
            "evet" if s.giris_acik else "hayır",
            _yerel(s.son_giris_at),
            s.ayrilis_tarihi.strftime("%d.%m.%Y") if s.ayrilis_tarihi else "",
            "evet" if s.kilitli else "",
            "açık" if s.mfa_enabled else "kapalı",
            ", ".join(s.hassas_izinler),
            s.sapma_sayisi,
            s.vekalet_sayisi,
            _yerel(s.son_gozden_gecirme_at),
            s.son_gozden_geciren or "",
        ]
        for s in satirlar
    ]
    await audit.log(
        db,
        "users",
        "erisim.disaaktar",
        new_value={"kpi": kpi, "satir": len(tablo), "girissiz_gun": esik},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, tablo, "Erişim gözden geçirme"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="erisim-gozden-gecirme.xlsx"'},
    )


@router.post("/{personel_id}/gozden-gecirildi", response_model=ErisimSatiri)
async def gozden_gecirildi(
    personel_id: int,
    payload: GozdenGecirIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yonetici,
) -> ErisimSatiri:
    """Kişinin erişimini "gözden geçirildi" olarak işaretler — YALNIZ denetim
    kaydı (ayrı tablo yok). Hesabın o anki yetki özeti kayda girer ki
    sonradan "neyi onayladık" sorusu cevaplanabilsin."""
    kisi = await db.get(User, personel_id)
    if kisi is None or await kapsam.personel_disinda_mi(db, user, personel_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")
    an = clock.now()
    kisi.izin_anini_ata(an)
    rol = await db.get(Role, kisi.role_id)
    await audit.log(
        db,
        "users",
        GOZDEN_GECIRILDI,
        entity_id=kisi.id,
        new_value={
            "not": payload.not_,
            "rol": rol.code if rol else None,
            "hassas_izinler": sorted(set(kisi.etkin_izinler()) & HASSAS_IZINLER),
            "istisna": sum(1 for i in kisi.izin_istisnalari if not i.sureli_mi),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return (await _satirlar(db, [kisi], an))[0]
