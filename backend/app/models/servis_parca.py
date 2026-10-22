"""Yedek parça: stok sayımı ve parça talebi (E11).

**Parça hareketleri ayrı tabloda DEĞİL** — canlı serisiz stok defterine
(`stock_movements`) `hareket_turu` ile yazılır (tek stok yazıcısı, plan §1.12,
E11-01). Bu dosya yalnız defterin yanındaki iki iş nesnesini taşır:

- **Sayım** (`stock_counts` + satırlar): açılış anı görüntüsü (`sistem_adet`)
  ve onay anındaki adet ayrı tutulur; onaysız sayım hiçbir bakiyeyi
  değiştirmez, farkı onay anındaki `SAYIM_FAZLASI/EKSIGI` hareketleri yazar.
  Depo başına tek açık sayım (`uq_stok_sayim_acik`). Numara
  `SAY-YYYYAA-NNNNNN` (`stock_count_no_seq`, OWNED BY stock_counts.id).
- **Parça talebi** (`service_part_requests`): açık servis işi için; MALZEME
  beklemesine (`hold_id`) isteğe bağlı bağlanır, iş kapanınca IPTAL olur.
  KARSILANDI yalnız talepten sonraki çıkışlarla hesaplanır.

Durumlar `STOK_SAYIM` / `PARCA_TALEBI` makineleriyle ilerler.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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

SAYIM_DURUMLARI = ("ACIK", "ONAYLANDI", "IPTAL")
PARCA_TALEP_DURUMLARI = ("ACIK", "KARSILANDI", "IPTAL")


def _in(sutun: str, degerler: tuple[str, ...]) -> str:
    return f"{sutun} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


class StockCount(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    """Depo sayımı (E11-17). Onay gerekçesiz olamaz (`ck_stok_sayim_onay`)."""

    __tablename__ = "stock_counts"
    __table_args__ = (
        UniqueConstraint("count_no", name="uq_stok_sayim_no"),
        CheckConstraint(_in("durum", SAYIM_DURUMLARI), name="ck_stok_sayim_durum"),
        CheckConstraint(
            "durum <> 'ONAYLANDI' OR (onaylayan_id IS NOT NULL AND onay_at IS NOT NULL "
            "AND length(trim(coalesce(gerekce, ''))) > 0)",
            name="ck_stok_sayim_onay",
        ),
        Index(
            "uq_stok_sayim_acik",
            "warehouse_id",
            unique=True,
            postgresql_where=text("durum = 'ACIK' AND NOT is_deleted"),
        ),
    )

    count_no: Mapped[str] = mapped_column(String(24))
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    durum: Mapped[str] = mapped_column(String(12), server_default=text("'ACIK'"), default="ACIK")
    # Clock'tan (açılış anı görüntüsünün zamanı).
    baslangic_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    onaylayan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    onay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gerekce: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)


class StockCountLine(Base, PkMixin, TimestampMixin):
    """Sayım satırı: açılış görüntüsü, sayılan, onay anındaki sistem adedi."""

    __tablename__ = "stock_count_lines"
    __table_args__ = (
        UniqueConstraint("stock_count_id", "product_id", name="uq_stok_sayim_satir"),
        CheckConstraint("sayilan_adet IS NULL OR sayilan_adet >= 0", name="ck_stok_sayim_sayilan"),
    )

    stock_count_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stock_counts.id", ondelete="CASCADE")
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    sistem_adet: Mapped[int] = mapped_column(Integer)
    sayilan_adet: Mapped[int | None] = mapped_column(Integer)
    onay_anindaki_adet: Mapped[int | None] = mapped_column(Integer)


class ServicePartRequest(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin
):
    """Servis işi için parça talebi (E11-19, daraltılmış). İş + ürün başına
    tek açık talep (`uq_parca_talep_acik`)."""

    __tablename__ = "service_part_requests"
    __table_args__ = (
        CheckConstraint(_in("durum", PARCA_TALEP_DURUMLARI), name="ck_parca_talep_durum"),
        CheckConstraint("adet > 0", name="ck_parca_talep_adet"),
        CheckConstraint(
            "durum <> 'IPTAL' OR iptal_nedeni IS NOT NULL", name="ck_parca_talep_iptal"
        ),
        Index(
            "uq_parca_talep_acik",
            "service_order_id",
            "product_id",
            unique=True,
            postgresql_where=text("durum = 'ACIK' AND NOT is_deleted"),
        ),
        Index("ix_parca_talep_urun_durum", "product_id", "durum"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    adet: Mapped[int] = mapped_column(Integer)
    durum: Mapped[str] = mapped_column(String(12), server_default=text("'ACIK'"), default="ACIK")
    karsilanma_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    iptal_nedeni: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(String(500))
    # İsteğe bağlı MALZEME beklemesi (E01 `beklet()` ile açılır).
    hold_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_holds.id", ondelete="SET NULL")
    )


__all__ = [
    "PARCA_TALEP_DURUMLARI",
    "SAYIM_DURUMLARI",
    "ServicePartRequest",
    "StockCount",
    "StockCountLine",
]
