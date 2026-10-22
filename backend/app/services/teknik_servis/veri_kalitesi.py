"""Ana veri ve servis verisi kalitesi listeleri (E14-09/18).

Maddeler: TS-171. İSKELET — D2-S yazdı (imza + docstring); doldurur: D2-I.
İmzalar plan §1.8/§4 sözleşmesidir; değiştirmek gerekirse D2-S'e talep açılır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User


async def eslestirme_adaylari(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Serbest metin müşteri/lokasyon → hesap/tesis aday listesi (`hesap.birlestir`)."""
    raise NotImplementedError("eslestirme_adaylari: henüz uygulanmadı")
