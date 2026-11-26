"""Özlük dosyası: İK onayı bekleyen belgeler (2026-11-23 sahip kararı).

Personel kendi dosyasına belge yükleyince belge `ONAY_BEKLIYOR` olur. İK'ya
bildirim saklanmaz, HESAPLANIR (`services/uyarilar.topla`, "izin.onay"
emsali): her yükleme bekleyen sayısını bir artırır, karar verilince düşer.
Sayı İK'nın personel kapsamıyla süzülür (sayı = sızıntı).
"""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OzlukBelgesi, User
from app.services.teknik_servis import kapsam

IK_IZNI = "ik_belge.yonet"
ONAY_BEKLIYOR = "ONAY_BEKLIYOR"
ONAYLANDI = "ONAYLANDI"
REDDEDILDI = "REDDEDILDI"


def bekleyen_kosulu(stmt: Select, user: User) -> Select:
    """Kapsamdaki, silinmemiş, onay bekleyen belgeler."""
    stmt = stmt.where(OzlukBelgesi.durum == ONAY_BEKLIYOR, OzlukBelgesi.is_deleted.is_(False))
    return kapsam.kapsam_personel(stmt, user, OzlukBelgesi.user_id)


async def bekleyen_sayisi(db: AsyncSession, user: User) -> int:
    if not user.has(IK_IZNI):
        return 0
    stmt = bekleyen_kosulu(select(func.count()).select_from(OzlukBelgesi), user)
    return int(await db.scalar(stmt) or 0)
