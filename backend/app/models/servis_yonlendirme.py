"""Satış/kiralama talebinin teknik servise yönlendirilmesi (KARARLAR 2026-11-20 §5–6).

Onaylı satıştan açılan kurulum/teslimat işi ya da onaylanan kiralama talebi
teknik servis müdürüne düşer (MUDURDE); müdür birimin yöneticisine/şefine
yönlendirir (BIRIMDE). Planlamayı kilitlemez: iş planlanınca ya da kiralama
TALEP'ten çıkınca kayıt "planlandı" sayılır (okuma anında hesaplanır).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin

YONLENDIRME_KAYNAKLARI = ("SATIS", "KIRALAMA")
YONLENDIRME_DURUMLARI = ("MUDURDE", "BIRIMDE")


class ServisYonlendirme(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "servis_yonlendirmeleri"
    __table_args__ = (
        CheckConstraint("kaynak IN ('SATIS','KIRALAMA')", name="ck_syon_kaynak"),
        CheckConstraint("durum IN ('MUDURDE','BIRIMDE')", name="ck_syon_durum"),
        CheckConstraint(
            "(service_order_id IS NOT NULL)::int + (rental_id IS NOT NULL)::int = 1",
            name="ck_syon_tek_hedef",
        ),
    )

    kaynak: Mapped[str] = mapped_column(String(10))
    service_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="CASCADE"), unique=True
    )
    rental_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rentals.id", ondelete="CASCADE"), unique=True
    )
    birim: Mapped[str] = mapped_column(String(20))
    durum: Mapped[str] = mapped_column(
        String(10), server_default=text("'MUDURDE'"), default="MUDURDE"
    )
    # Satışın sözleşme / taahhüt ayrıntıları ve talep notu (satışçının yazdığı).
    sozlesme_detay: Mapped[str | None] = mapped_column(Text)
    talep_notu: Mapped[str | None] = mapped_column(Text)
    hedef_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    yonlendiren_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    yonlendirme_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mudur_notu: Mapped[str | None] = mapped_column(String(500))
