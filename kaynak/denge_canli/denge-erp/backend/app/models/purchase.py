"""Satın alma, ithalat dosyası ve landed cost (brief §4.13).

**Landed cost dağıtımı bir KARAR değil, bir hesaptır ve dondurulur.** Masraf
toplamı mal kabuldeki cihazlara dağıtılıp her IMEI'nin `landed_cost_try`
alanına yazılır. Dosya sonradan güncellenirse yeniden dağıtılır ve fark
raporlanır; geçmiş dağıtımı sessizce değiştirmek, satılmış cihazların
maliyetini geriye dönük bozardı.

**Dağıtım anahtarı seçilebilir** (tutar / adet / ağırlık) çünkü hangi
masrafın neye göre dağıtılacağı masrafın cinsine bağlı: navlun ağırlıkla,
gümrük vergisi mal bedeliyle, müşavirlik ücreti adetle orantılıdır.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
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

SATINALMA_DURUMLARI = (
    "TASLAK",
    "SIPARIS_VERILDI",
    "KISMI_TESLIM",
    "TESLIM_ALINDI",
    "IPTAL",
)

ITHALAT_DURUMLARI = ("ACIK", "GUMRUKTE", "TAMAMLANDI", "IPTAL")

# Masrafın hangi ölçüye göre dağıtılacağı.
DAGITIM_ANAHTARLARI = ("TUTAR", "ADET", "AGIRLIK")


class PurchaseOrder(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("po_no", name="uq_po_no"),
        CheckConstraint(
            "status IN ('TASLAK','SIPARIS_VERILDI','KISMI_TESLIM','TESLIM_ALINDI','IPTAL')",
            name="ck_po_durum",
        ),
        Index("ix_po_tedarikci", "supplier_id"),
        Index("ix_po_durum", "status"),
    )

    po_no: Mapped[str] = mapped_column(String(24))
    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), server_default=text("'TASLAK'"))

    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)

    # Alış çoğunlukla dövizle; kur SİPARİŞ ANINDA dondurulur, maliyet
    # hesabı sonradan değişen kurla oynamaz.
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fx_date: Mapped[date | None] = mapped_column(Date)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseOrderLine(Base, PkMixin):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_pol_adet"),
        CheckConstraint("qty_received <= qty", name="ck_pol_teslim_asimi"),
        Index("ix_pol_order", "purchase_order_id"),
    )

    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="CASCADE")
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    description: Mapped[str | None] = mapped_column(String(300))
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    qty_received: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default=text("0"))
    # Ağırlık yalnız landed cost dağıtımı için; girilmezse ağırlık anahtarı
    # kullanılamaz ve dağıtım adete düşer.
    unit_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class ImportFile(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    """İthalat dosyası — mal bedeli dışındaki tüm masraflar burada toplanır."""

    __tablename__ = "import_files"
    __table_args__ = (
        UniqueConstraint("file_no", name="uq_import_file_no"),
        CheckConstraint(
            "status IN ('ACIK','GUMRUKTE','TAMAMLANDI','IPTAL')", name="ck_ithalat_durum"
        ),
        Index("ix_ithalat_durum", "status"),
    )

    file_no: Mapped[str] = mapped_column(String(24))
    purchase_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="SET NULL"), index=True
    )
    supplier_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(12), server_default=text("'ACIK'"))

    invoice_no: Mapped[str | None] = mapped_column(String(60))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    incoterm: Mapped[str | None] = mapped_column(String(10))  # FOB, CIF, EXW…
    customs_declaration_no: Mapped[str | None] = mapped_column(String(40))  # GTB beyanname
    cleared_at: Mapped[date | None] = mapped_column(Date)

    currency: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # --- Masraf kalemleri (hepsi TL) ---------------------------------------
    goods_value_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    freight_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    insurance_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    customs_duty_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    other_tax_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    broker_fee_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    inland_freight_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    other_cost_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))

    allocation_key: Mapped[str] = mapped_column(String(10), server_default=text("'TUTAR'"))
    allocated_at: Mapped[date | None] = mapped_column(Date)
    allocated_device_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    notes: Mapped[str | None] = mapped_column(Text)


class GoodsReceipt(Base, PkMixin, TimestampMixin, ActorMixin):
    """Mal kabul — IMEI listesi bu belgeyle stoğa girer."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("receipt_no", name="uq_receipt_no"),
        Index("ix_receipt_po", "purchase_order_id"),
    )

    receipt_no: Mapped[str] = mapped_column(String(24))
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("purchase_orders.id", ondelete="CASCADE")
    )
    import_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("import_files.id", ondelete="SET NULL"), index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="SET NULL")
    )
    received_at: Mapped[date] = mapped_column(Date)
    device_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)
