"""Sipariş, IMEI rezervasyonu ve sevkiyat (brief §4.10).

**Sipariş teklifin dondurulmuş halidir.** Kabul edilen teklif versiyonundan
kalem kalem kopyalanır; teklif sonradan revize edilse bile sipariş değişmez.
Fiyat ve KDV burada da kalem bazında donar (plan §3.3/2).

**Rezervasyon cihaz bazındadır, adet bazında değil.** "3 adet L300" rezerve
etmek sevkiyat gününe kadar hangi IMEI'nin gideceğini belirsiz bırakır;
ERP'nin cevaplaması gereken soru ise "bu IMEI kime söz verildi". Bir cihaz
aynı anda tek açık rezervasyonda durabilir — kısmi tekil indeksle zorlanır.

**Sevkiyat ayrı bir tablo DEĞİL:** stok modülündeki `transfers` belgesi
kullanılır (tip `SATIS`). İkinci bir sevk mekanizması, konum geçmişini iki
ayrı yoldan yazmak ve er geç ikisinin ayrışması demekti.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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

SIPARIS_DURUMLARI = (
    "TASLAK",
    "ONAYLANDI",
    "REZERVE",
    "KISMI_SEVK",
    "SEVK_EDILDI",
    "TAMAMLANDI",
    "IPTAL",
)


class Order(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_order_no"),
        CheckConstraint(
            "status IN ('TASLAK','ONAYLANDI','REZERVE','KISMI_SEVK','SEVK_EDILDI',"
            "'TAMAMLANDI','IPTAL')",
            name="ck_order_durum",
        ),
        Index("ix_order_musteri", "customer_id"),
        Index("ix_order_durum", "status"),
    )

    order_no: Mapped[str] = mapped_column(String(24))
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    # Tekliften dönüştüyse izi burada kalır; doğrudan açılan sipariş de olur.
    quote_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quotes.id", ondelete="SET NULL")
    )
    quote_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quote_versions.id", ondelete="SET NULL")
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), server_default=text("'TASLAK'"))

    order_date: Mapped[date] = mapped_column(Date)
    requested_date: Mapped[date | None] = mapped_column(Date)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))

    currency: Mapped[str] = mapped_column(String(3), server_default=text("'TRY'"))
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fx_date: Mapped[date | None] = mapped_column(Date)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    vat_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))

    notes: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderLine(Base, PkMixin):
    __tablename__ = "order_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_ol_adet"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100", name="ck_ol_iskonto"),
        CheckConstraint("qty_shipped <= qty", name="ck_ol_sevk_asimi"),
        Index("ix_ol_order", "order_id"),
    )

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"))
    item_type: Mapped[str] = mapped_column(String(16), server_default=text("'URUN'"))
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(String(300))
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default=text("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    # Kısmi sevkiyat: rezerve ve sevk edilen adet rezervasyonlardan türetilir
    # ama sorguyu ucuzlatmak için burada da tutulur.
    qty_shipped: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    order: Mapped[Order] = relationship(back_populates="lines")


class OrderReservation(Base, PkMixin, TimestampMixin, ActorMixin):
    """Bir IMEI'nin bir sipariş kalemine bağlanması.

    Açık rezervasyon = `released_at IS NULL`. Sevkiyat rezervasyonu tüketir:
    `shipped_at` yazılır ve aynı anda `released_at` de yazılır, böylece cihaz
    kısmi tekil indeksi serbest bırakır ve "sevk edilmiş cihaz hâlâ rezerve
    görünüyor" durumu oluşmaz.
    """

    __tablename__ = "order_reservations"
    __table_args__ = (
        # Bir cihaz aynı anda tek açık rezervasyonda durabilir.
        Index(
            "uq_rez_acik_cihaz",
            "device_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        Index("ix_rez_kalem", "order_line_id"),
        Index("ix_rez_order", "order_id"),
    )

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"))
    order_line_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("order_lines.id", ondelete="CASCADE")
    )
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="RESTRICT")
    )
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(200))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transfer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transfers.id", ondelete="SET NULL")
    )
