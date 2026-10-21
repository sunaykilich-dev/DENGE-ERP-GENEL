"""RMA / garanti / teknik servis (brief §4.12).

**Garanti durumu OTOMATİK belirlenir ama DONDURULUR.** Kayıt açılırken
cihazın garanti bitişine bakılıp `warranty_status` yazılır; sonradan garanti
tarihi düzeltilse bile açılmış kaydın kararı değişmez. Aksi halde "bu iş
garanti kapsamındaydı, neden ücret çıkmış" tartışması çözülemezdi.

**Değişimde eski–yeni ilişkisi saklanır** (`replacement_device_id`): yeni
IMEI aracın, hattın ve aboneliğin yerine geçerken eskisinin izi kaybolmaz —
model bazında arıza oranı raporu buna dayanır.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionedMixin,
)

RMA_DURUMLARI = (
    "ACIK",
    "INCELEMEDE",
    "TAMIRDE",
    "TEDARIKCIDE",
    "COZULDU",
    "KAPANDI",
    "IPTAL",
)

# Garanti kararı üç değerli: "belirsiz" gerçek bir durum — aktivasyon tarihi
# bilinmeyen göç cihazlarında garanti başlangıcı hesaplanamıyor.
GARANTI_DURUMLARI = ("GARANTI_ICI", "GARANTI_DISI", "BELIRSIZ")

COZUM_TIPLERI = ("TAMIR", "DEGISIM", "IADE", "ONARILMADI", "HURDAYA_AYRILDI")


class RmaCase(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    __tablename__ = "rma_cases"
    __table_args__ = (
        UniqueConstraint("rma_no", name="uq_rma_no"),
        CheckConstraint(
            "status IN ('ACIK','INCELEMEDE','TAMIRDE','TEDARIKCIDE','COZULDU','KAPANDI','IPTAL')",
            name="ck_rma_durum",
        ),
        CheckConstraint(
            "warranty_status IN ('GARANTI_ICI','GARANTI_DISI','BELIRSIZ')",
            name="ck_rma_garanti",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN "
            "('TAMIR','DEGISIM','IADE','ONARILMADI','HURDAYA_AYRILDI')",
            name="ck_rma_cozum",
        ),
        Index("ix_rma_cihaz", "device_id"),
        Index("ix_rma_durum", "status"),
    )

    rma_no: Mapped[str] = mapped_column(String(24))
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="RESTRICT")
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(12), server_default=text("'ACIK'"))

    received_at: Mapped[date] = mapped_column(Date)
    fault_description: Mapped[str] = mapped_column(Text)
    # Kayıt anında hesaplanıp dondurulur (yukarıdaki not).
    warranty_status: Mapped[str] = mapped_column(String(12), server_default=text("'BELIRSIZ'"))
    warranty_end_date: Mapped[date | None] = mapped_column(Date)

    resolution: Mapped[str | None] = mapped_column(String(20))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    replacement_device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="SET NULL")
    )
    # Garanti dışı işin müşteriye yansıyan bedeli.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Üreticiye garanti iadesi takibi (brief §4.12).
    supplier_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    supplier_rma_no: Mapped[str | None] = mapped_column(String(60))
    sent_to_supplier_at: Mapped[date | None] = mapped_column(Date)
    returned_from_supplier_at: Mapped[date | None] = mapped_column(Date)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
