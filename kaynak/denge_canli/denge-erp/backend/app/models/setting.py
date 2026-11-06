from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin


class Setting(Base, TimestampMixin):
    """Operasyonel parametreler — stopaj/damga/KDV oranları, iskonto onay
    eşiği, kota uyarı yüzdeleri, garanti süresi, entegrasyon kimlik bilgileri.

    Hassas anahtarlar (`SENSITIVE_KEYS`) şifreli saklanır ve API'de maskelenir.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
