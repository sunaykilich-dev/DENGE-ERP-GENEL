"""Fiyat teklifi (brief §4.9).

**Revizyon = yeni versiyon.** Her değişiklik yeni bir versiyon açar, eski
versiyon KİLİTLENİR ve görüntülenebilir kalır. Müşteriye gönderilen belgenin
sonradan değişmesi, "ben başka bir fiyat görmüştüm" tartışmasının kaynağıdır.

**Fiyat ve KDV versiyona dondurulur.** Ürün kartındaki liste fiyatı veya
ayarlardaki KDV oranı sonradan değişse de gönderilmiş teklif aynı kalır
(plan §3.3/2).

Online kabul dışa açık bir sunucu ister; veri modeli hazır, `public_token`
üretiliyor ve kabul/red kaydı tutuluyor. Yerel kurulumda link açılamaz ama
kabul elle de işaretlenebilir — kim, ne zaman işaretledi loglanır.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionedMixin,
)

TEKLIF_DURUMLARI = (
    "TASLAK",
    "ONAY_BEKLIYOR",  # eşik üstü iskonto → satış müdürü onayı
    "GONDERILDI",
    "GORUNTULENDI",
    "REVIZE_EDILDI",
    "KABUL",
    "RED",
    "SURESI_DOLDU",
    "SIPARISE_DONUSTU",
)

KALEM_TIPLERI = ("URUN", "PAKET", "HIZMET", "ABONELIK", "SIM_PAKETI", "SERBEST")


class Quote(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("quote_no", name="uq_quote_no"),
        CheckConstraint(
            "status IN ('TASLAK','ONAY_BEKLIYOR','GONDERILDI','GORUNTULENDI','REVIZE_EDILDI',"
            "'KABUL','RED','SURESI_DOLDU','SIPARISE_DONUSTU')",
            name="ck_quote_durum",
        ),
        Index("ix_quote_musteri", "customer_id"),
        Index("ix_quote_durum", "status"),
    )

    quote_no: Mapped[str] = mapped_column(String(24))
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), server_default=text("'TASLAK'"))
    current_version_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(String(200))
    # Kayıp nedeni zorunlu (brief §4.8 satış hunisi).
    lost_reason: Mapped[str | None] = mapped_column(String(200))

    versions: Mapped[list["QuoteVersion"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", lazy="selectin"
    )


class QuoteVersion(Base, PkMixin, TimestampMixin, ActorMixin):
    __tablename__ = "quote_versions"
    __table_args__ = (
        UniqueConstraint("quote_id", "version_no", name="uq_quote_version"),
        UniqueConstraint("public_token", name="uq_quote_token"),
        CheckConstraint("version_no > 0", name="ck_qv_versiyon"),
        Index("ix_qv_quote", "quote_id"),
    )

    quote_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("quotes.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    currency: Mapped[str] = mapped_column(String(3), server_default=text("'TRY'"))
    # Döviz teklifte kur ve kur tarihi YAZAR (brief §4.9). TCMB'den otomatik
    # çekilebilir ama yerel kurulumda elle girilir; hangisi olduğu kaydedilir.
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fx_date: Mapped[date | None] = mapped_column(Date)
    fx_source: Mapped[str | None] = mapped_column(String(10))  # TCMB | MANUEL

    valid_until: Mapped[date | None] = mapped_column(Date)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    vat_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    # En yüksek kalem iskontosu — onay eşiği buna bakar.
    max_discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    discount_approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    discount_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Dışa açık link jetonu — müşteri teklifi bununla görüntüler ve kabul eder.
    public_token: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(String(300))
    # Kabul/red linkten mi geldi yoksa ekip mi işaretledi — ikisi aynı şey değil.
    decision_channel: Mapped[str | None] = mapped_column(String(10))  # LINK | ELLE

    # Gönderilen versiyon bir daha değişmez.
    is_locked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)

    quote: Mapped[Quote] = relationship(back_populates="versions")
    lines: Mapped[list["QuoteLine"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", lazy="selectin"
    )


class QuoteLine(Base, PkMixin):
    __tablename__ = "quote_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_ql_adet"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100", name="ck_ql_iskonto"),
        Index("ix_ql_version", "version_id"),
    )

    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quote_versions.id", ondelete="CASCADE")
    )
    item_type: Mapped[str] = mapped_column(String(16), server_default=text("'URUN'"))
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(String(300))
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default=text("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    # KDV oranı kalem bazında DONDURULUR: ayar sonradan değişse de bu teklif
    # aynı kalır.
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    version: Mapped[QuoteVersion] = relationship(back_populates="lines")
