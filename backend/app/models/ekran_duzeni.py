"""Ekran düzeni: kullanıcının bir ekrandaki sayı kutucuklarını kişiselleştirmesi.

Kullanıcı isteği (2026-11-18): Zaman Takibi, Planlama, Personel… ekranlarındaki
kutucuklar "kullanıcı kendi isteğine göre kişiselleştirebilsin; kutuların
boyutu-konumu ona bırakılsın". Ana Panel'in düzeni (`ana_panel_duzenleri`)
ayrıdır: orada bileşen kataloğu ve rol varsayılanı vardır. Burada yalnız
kişisel sıra/boyut/gizleme tutulur; kutucuğun verisi ve izni ekranın kendi
ucundadır (düzen veri açmaz).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PkMixin, TimestampMixin, VersionedMixin


class EkranDuzeni(Base, PkMixin, TimestampMixin, VersionedMixin):
    __tablename__ = "ekran_duzenleri"
    __table_args__ = (
        UniqueConstraint("user_id", "ekran", name="uq_ekran_duzeni_kullanici_ekran"),
        CheckConstraint("jsonb_typeof(kutular) = 'array'", name="ck_ekran_duzeni_liste"),
    )

    # Kullanıcı silinirse düzeni de gider (kişisel tercih; iş kaydı değil).
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    ekran: Mapped[str] = mapped_column(String(40), nullable=False)
    kutular: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
