"""Parametre yönetimi (izin: sistem.ayar).

Hassas anahtarlar arayüze MASKELENEREK döner; boş gönderilirse mevcut değer
korunur (kullanıcı sırrı görmeden diğer ayarları kaydedebilsin).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import DbDep, client_ip, require_permission
from app.models import User
from app.services import audit
from app.services import settings as settings_service

router = APIRouter(prefix="/api/ayarlar", tags=["ayarlar"])

SettingsAdmin = Annotated[User, Depends(require_permission("sistem.ayar"))]
MASK = "********"


class SettingsPatch(BaseModel):
    values: dict[str, Any]


def _mask(data: dict[str, Any]) -> dict[str, Any]:
    return {k: (MASK if k in settings_service.SENSITIVE_KEYS and v else v) for k, v in data.items()}


@router.get("")
async def read_settings(db: DbDep, _: SettingsAdmin) -> dict[str, Any]:
    return _mask(await settings_service.get_all(db))


@router.patch("")
async def update_settings(
    payload: SettingsPatch, request: Request, db: DbDep, admin: SettingsAdmin
) -> dict[str, Any]:
    incoming = dict(payload.values)
    # Maskeli gelen hassas alanı "değişmedi" kabul et — aksi halde arayüzü
    # açıp kaydeden kullanıcı sırrı MASK metniyle ezerdi.
    for key in list(incoming):
        if key in settings_service.SENSITIVE_KEYS and incoming[key] == MASK:
            del incoming[key]

    before = await settings_service.get_all(db)
    try:
        await settings_service.set_many(db, incoming, admin.id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    degisen = {k: v for k, v in incoming.items() if before.get(k) != v}
    if degisen:
        await audit.log(
            db,
            "settings",
            "guncelle",
            old_value=_mask({k: before.get(k) for k in degisen}),
            new_value=_mask(degisen),
            user_id=admin.id,
            ip=client_ip(request),
        )
    await db.commit()
    return _mask(await settings_service.get_all(db))
