"""Çalışma zamanında adaptör seçimi (ayarlardan)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import MockAdaptor, OperatorAdaptoru
from app.integrations.turk_telekom import TurkTelekomAdaptoru
from app.services import settings as ayar_svc

_MOCK = MockAdaptor()


async def operator_adaptoru(db: AsyncSession) -> OperatorAdaptoru:
    ayarlar = await ayar_svc.get_all(db)
    secim = ayarlar.get("operator_adaptor", "mock")
    if secim == "turk_telekom":
        return TurkTelekomAdaptoru(
            base_url=ayarlar.get("operator_base_url", ""),
            api_key=ayarlar.get("operator_api_key", ""),
        )
    return _MOCK
