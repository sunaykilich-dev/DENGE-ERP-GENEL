"""Denetim izi yazımı.

Kaynak projedeki tek satırlık `log()` burada ikiye ayrılır:
- `log()`   — serbest eylem kaydı (giriş, dışa aktarma, senkron tetikleme).
- `log_change()` — bir ORM nesnesinin değişen alanlarını eski/yeni olarak yazar.

İkincisi brief §8'in asıl istediği şey: transfer, sök-tak, durum değişikliği,
hak ediş onayı, iskonto onayı ve fiyat değişikliğinde "ne neye dönüştü".
"""

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

# Denetim kaydına asla düz metin olarak girmemesi gereken alanlar.
_REDACTED = {"password_hash", "totp_secret", "value"}


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k in _REDACTED else v) for k, v in data.items()}


async def log(
    db: AsyncSession,
    entity: str,
    action: str,
    *,
    entity_id: str | int | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    user_id: int | None = None,
    ip: str | None = None,
    is_personal_data: bool = False,
) -> None:
    """Çağıranın transaction'ı içinde flush edilir — işlem geri alınırsa
    denetim kaydı da geri alınır, yani yarım işlem loglanmaz."""
    db.add(
        AuditLog(
            user_id=user_id,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            action=action,
            old_value=_clean(old_value) if old_value else None,
            new_value=_clean(new_value) if new_value else None,
            ip=ip,
            is_personal_data=is_personal_data,
        )
    )
    await db.flush()


async def log_change(
    db: AsyncSession,
    obj: Any,
    action: str,
    *,
    user_id: int | None = None,
    ip: str | None = None,
    is_personal_data: bool = False,
) -> None:
    """Henüz flush edilmemiş bir ORM nesnesinin kirli alanlarını yazar.

    SQLAlchemy'nin değişiklik izleyicisinden eski/yeni değerleri okur; yalnız
    GERÇEKTEN değişen alanlar loglanır — "hiçbir şey değişmedi" kaydı üretmez.
    """
    state = inspect(obj)
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    for attr in state.mapper.column_attrs:
        hist = state.attrs[attr.key].history
        if not hist.has_changes():
            continue
        if hist.deleted:
            old[attr.key] = _jsonable(hist.deleted[0])
        if hist.added:
            new[attr.key] = _jsonable(hist.added[0])
    if not old and not new:
        return
    await log(
        db,
        entity=obj.__tablename__,
        action=action,
        entity_id=getattr(obj, "id", None),
        old_value=old or None,
        new_value=new or None,
        user_id=user_id,
        ip=ip,
        is_personal_data=is_personal_data,
    )


def _jsonable(value: Any) -> Any:
    """JSONB'ye yazılabilir hale getirir (tarih, Decimal, enum vb.)."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)
