"""Ana Panel düzeni uçları (KARARLAR 2026-11-09 S8).

Kişisel düzen (S8.1) — oturum yeter, izin gerekmez; bileşenler izinle süzülür:
- `GET    /api/ana-panel/duzen`  etkin düzen + varsayılan + izinli katalog
- `PUT    /api/ana-panel/duzen`  kaydet (`version`: iyimser kilit; ilk kayıtta null)
- `DELETE /api/ana-panel/duzen?version=`  "Varsayılana dön"

Rol varsayılanı (S8.3, G7.3) — `panel.yonet`:
- `GET    /api/ana-panel/rol-duzenleri`
- `GET    /api/ana-panel/rol-duzenleri/{rol_kodu}`
- `PUT    /api/ana-panel/rol-duzenleri/{rol_kodu}`
- `DELETE /api/ana-panel/rol-duzenleri/{rol_kodu}?version=`

Hata kodları: bilinmeyen/tekrarlı bileşen 400; izinsiz bileşen 403; sürüm
uyuşmazlığı 409; bilinmeyen rol 404. İş kuralı `services/ana_panel_duzeni.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbDep, client_ip, require_permission
from app.models import Role, User
from app.services import ana_panel_duzeni as svc

router = APIRouter(prefix="/api/ana-panel", tags=["ana-panel"])

RolDuzenleyici = Annotated[User, Depends(require_permission(svc.ROL_DUZENI_IZNI))]


# --- Şemalar ----------------------------------------------------------------------------------


class BilesenOgesi(BaseModel):
    kod: str = Field(min_length=1, max_length=40)
    boyut: Literal["DAR", "GENIS"]
    gorunur: bool = True


class DuzenGirdisi(BaseModel):
    bilesenler: list[BilesenOgesi] = Field(max_length=len(svc.BILESENLER))
    # Kayıtlı düzenin sürümü; ilk kayıtta (varsayılandan başlanıyorsa) null.
    version: int | None = None


class KatalogOgesi(BaseModel):
    kod: str
    ad: str
    aciklama: str
    grup: str
    tur: str
    varsayilan_boyut: str
    veri: str


class VarsayilanDuzen(BaseModel):
    kaynak: str
    bilesenler: list[BilesenOgesi]


class DuzenYaniti(BaseModel):
    # KULLANICI | ROL | SISTEM
    kaynak: str
    version: int | None
    bilesenler: list[BilesenOgesi]
    varsayilan: VarsayilanDuzen
    katalog: list[KatalogOgesi]
    rol_duzenleyebilir: bool


class RolSatiri(BaseModel):
    rol_kodu: str
    rol_adi: str
    ozel: bool
    version: int | None


class RolDuzenYaniti(BaseModel):
    rol_kodu: str
    rol_adi: str
    # ROL | SISTEM
    kaynak: str
    version: int | None
    bilesenler: list[BilesenOgesi]
    sistem_varsayilani: list[BilesenOgesi]
    katalog: list[KatalogOgesi]


# --- Yardımcılar ------------------------------------------------------------------------------


@contextmanager
def _hatalar() -> Iterator[None]:
    try:
        yield
    except svc.DuzenYetkiHatasi as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except svc.DuzenHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except svc.DuzenCakismasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


async def _rol(db: DbDep, rol_kodu: str) -> Role:
    rol = await svc.rol_getir(db, rol_kodu)
    if rol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rol bulunamadı")
    return rol


def _ogeler(girdi: DuzenGirdisi) -> list[dict]:
    return [o.model_dump() for o in girdi.bilesenler]


# --- Kişisel düzen ----------------------------------------------------------------------------


@router.get("/duzen", response_model=DuzenYaniti)
async def duzen(db: DbDep, user: CurrentUser) -> dict:
    return await svc.etkin_duzen(db, user)


@router.put("/duzen", response_model=DuzenYaniti)
async def duzen_kaydet(girdi: DuzenGirdisi, request: Request, db: DbDep, user: CurrentUser) -> dict:
    with _hatalar():
        sonuc = await svc.kaydet(db, user, _ogeler(girdi), girdi.version, ip=client_ip(request))
    await db.commit()
    return sonuc


@router.delete("/duzen", response_model=DuzenYaniti)
async def duzen_sifirla(
    request: Request, db: DbDep, user: CurrentUser, version: int | None = None
) -> dict:
    with _hatalar():
        sonuc = await svc.sifirla(db, user, version, ip=client_ip(request))
    await db.commit()
    return sonuc


# --- Rol varsayılanı --------------------------------------------------------------------------


@router.get("/rol-duzenleri", response_model=list[RolSatiri])
async def rol_duzenleri(db: DbDep, _: RolDuzenleyici) -> list[dict]:
    return await svc.rol_listesi(db)


@router.get("/rol-duzenleri/{rol_kodu}", response_model=RolDuzenYaniti)
async def rol_duzeni(rol_kodu: str, db: DbDep, user: RolDuzenleyici) -> dict:
    return await svc.rol_duzeni(db, await _rol(db, rol_kodu), user)


@router.put("/rol-duzenleri/{rol_kodu}", response_model=RolDuzenYaniti)
async def rol_duzeni_kaydet(
    rol_kodu: str, girdi: DuzenGirdisi, request: Request, db: DbDep, user: RolDuzenleyici
) -> dict:
    rol = await _rol(db, rol_kodu)
    with _hatalar():
        sonuc = await svc.rol_kaydet(
            db, rol, user, _ogeler(girdi), girdi.version, ip=client_ip(request)
        )
    await db.commit()
    return sonuc


@router.delete("/rol-duzenleri/{rol_kodu}", response_model=RolDuzenYaniti)
async def rol_duzeni_sifirla(
    rol_kodu: str,
    request: Request,
    db: DbDep,
    user: RolDuzenleyici,
    version: int | None = None,
) -> dict:
    rol = await _rol(db, rol_kodu)
    with _hatalar():
        sonuc = await svc.rol_sifirla(db, rol, user, version, ip=client_ip(request))
    await db.commit()
    return sonuc
