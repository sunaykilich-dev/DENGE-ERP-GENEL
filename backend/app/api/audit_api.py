"""Denetim izi görüntüleme (izin: sistem.denetim)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DbDep, require_permission
from app.models import AuditLog, User

router = APIRouter(prefix="/api/denetim", tags=["denetim"])

AuditReader = Annotated[User, Depends(require_permission("sistem.denetim"))]


@router.get("")
async def list_audit(
    db: DbDep,
    _: AuditReader,
    entity: str | None = None,
    entity_id: str | None = None,
    user_id: int | None = None,
    action: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None, description="Sayfalama: bu id'den eskiler"),
) -> list[dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)

    rows = (await db.scalars(stmt)).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "entity": r.entity,
            "entity_id": r.entity_id,
            "action": r.action,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "is_personal_data": r.is_personal_data,
            "ip": r.ip,
            "created_at": r.created_at,
        }
        for r in rows
    ]
