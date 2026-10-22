"""Eski ad bazlı kayıtların onaylı personel eşlemesi (E13-08).

Maddeler: TS-170. İSKELET — D2-S yazdı (imza + docstring); doldurur: D2-I.
İmzalar plan §1.8/§4 sözleşmesidir; değiştirmek gerekirse D2-S'e talep açılır.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def oneriler(db: AsyncSession, adlar: list[str]) -> list[dict[str, Any]]:
    """trgm yalnız öneri üretir; karar İK onayıyla `ad_esleme` profilinde."""
    raise NotImplementedError("oneriler: henüz uygulanmadı")
