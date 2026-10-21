from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditLog(Base):
    """Denetim izi — brief §8 "değiştirilemez şekilde loglanır".

    Kaynak projeden farkı: orada tek bir `detail` alanı vardı. Brief §5
    `entity` / `entity_id` / `old_value` / `new_value` istiyor; transfer,
    sök-tak, durum değişikliği, hak ediş onayı, iskonto onayı ve fiyat
    değişikliğinde "ne neye dönüştü" sorusu bu alanlarla cevaplanır.

    Bu tabloya yalnız INSERT yapılır. UPDATE/DELETE yolu uygulama kodunda
    yoktur; veritabanı seviyesinde de uygulama kullanıcısından bu haklar
    alınır (deploy/db-least-privilege.sql).
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        # "Bu kaydın geçmişi" sorgusu — cihaz kartı, iş emri, döküm ekranları.
        Index("ix_audit_logs_entity", "entity", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    entity: Mapped[str] = mapped_column(String(60))  # ör: "devices", "settlements"
    entity_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(60))  # ör: "olustur", "durum.degistir"
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # KVKK: kişisel veriye (plaka, iletişim, IBAN) erişim de loglanır.
    is_personal_data: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
