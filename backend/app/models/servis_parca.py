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
  KARSILANDI yalnız talepten sonraki çıkışlarla hesaplanır. **Amir onayı
  (2026-11-09, fbb000000001):** teknisyen işin biriminin deposundan
  (`warehouse_id`) ister → ONAY_BEKLIYOR; şef (`parca.talep_onay`) tek adımda
  onaylar (ACIK, depo hazırlar) ya da gerekçeyle reddeder (REDDEDILDI).
  Onay yetkisi olanın kendi talebi doğrudan ACIK açılır.

Durumlar `STOK_SAYIM` / `PARCA_TALEBI` makineleriyle ilerler.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
# ONAY_BEKLIYOR → (amir onayı) ACIK: depo hazırlar/teslim eder → KARSILANDI.
# ONAY_BEKLIYOR → REDDEDILDI (gerekçeli). ONAY_BEKLIYOR/ACIK → IPTAL.
PARCA_TALEP_DURUMLARI = ("ONAY_BEKLIYOR", "ACIK", "KARSILANDI", "REDDEDILDI", "IPTAL")
# "Açık" sayılan durumlar: iş + parça başına tek açık talep, iş kapanınca IPTAL.
PARCA_TALEP_ACIK_DURUMLAR = ("ONAY_BEKLIYOR", "ACIK")


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
        CheckConstraint(
            "durum <> 'REDDEDILDI' OR red_nedeni IS NOT NULL", name="ck_parca_talep_red"
        ),
        Index(
            "uq_parca_talep_acik",
            "service_order_id",
            "product_id",
            unique=True,
            postgresql_where=text("durum IN ('ONAY_BEKLIYOR', 'ACIK') AND NOT is_deleted"),
        ),
        Index("ix_parca_talep_urun_durum", "product_id", "durum"),
        # S5.3 ikmal talebi: işe bağlı değil, hedefi araç deposu (fbd000000001).
        CheckConstraint(
            "service_order_id IS NOT NULL OR hedef_depo_id IS NOT NULL",
            name="ck_parca_talep_is_ya_da_ikmal",
        ),
        Index(
            "uq_parca_talep_ikmal_acik",
            "hedef_depo_id",
            "product_id",
            unique=True,
            postgresql_where=text(
                "service_order_id IS NULL AND durum IN ('ONAY_BEKLIYOR', 'ACIK') AND NOT is_deleted"
            ),
        ),
    )

    # İkmal talebinde NULL (S5.3); o zaman `hedef_depo_id` doludur.
    service_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    # İkmal talebinin hedefi: teknisyenin araç deposu (teslim = transfer).
    hedef_depo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_parca_talep_hedef_depo"),
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    adet: Mapped[int] = mapped_column(Integer)
    durum: Mapped[str] = mapped_column(String(16), server_default=text("'ACIK'"), default="ACIK")
    # Talep edilen depo (işin birimi; eski talepte NULL).
    warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT", name="fk_parca_talep_depo")
    )
    onaylayan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_parca_talep_onaylayan")
    )
    onay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    red_nedeni: Mapped[str | None] = mapped_column(String(200))
    karsilanma_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    iptal_nedeni: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(String(500))
    # İsteğe bağlı MALZEME beklemesi (E01 `beklet()` ile açılır).
    hold_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_holds.id", ondelete="SET NULL")
    )


# --- S5 sahada parça al-ver (KARARLAR 2026-11-09 S5, fbd000000001) ---------------

KULLANIM_ONAY_DURUMLARI = ("BEKLIYOR", "ONAYLANDI", "REDDEDILDI")
ZIMMET_DURUMLARI = ("ACIK", "CEVAPLANDI")


class ServicePartUsageReview(Base, PkMixin, TimestampMixin, VersionedMixin):
    """S5.1: teknisyenin araç deposundan işe çıkışının şef onayı (sonradan).

    Çıkış anında yazılır, iş beklemez (D6.7); bu kayıt yalnız onayı taşır.
    Defter satırı (`stock_movements`) değiştirilemez olduğu için onay ayrı
    tabloda. Şef reddederse kayıt FARK KAYDIDIR: gerekçe zorunlu ve zimmet
    sorusu açılır (`zimmet_durumu=ACIK`); teknisyen açıklama yazınca
    CEVAPLANDI. Stok ters kaydı gerekiyorsa depo ayrıca ters kayıt yapar.
    """

    __tablename__ = "service_part_usage_reviews"
    __table_args__ = (
        UniqueConstraint("stock_movement_id", name="uq_parca_kullanim_hareket"),
        CheckConstraint(_in("durum", KULLANIM_ONAY_DURUMLARI), name="ck_parca_kullanim_durum"),
        CheckConstraint(
            "durum <> 'REDDEDILDI' OR (red_nedeni IS NOT NULL AND zimmet_durumu IS NOT NULL)",
            name="ck_parca_kullanim_red",
        ),
        CheckConstraint(
            "zimmet_durumu IS NULL OR " + _in("zimmet_durumu", ZIMMET_DURUMLARI),
            name="ck_parca_kullanim_zimmet",
        ),
        CheckConstraint(
            "zimmet_durumu IS DISTINCT FROM 'CEVAPLANDI' OR zimmet_aciklama IS NOT NULL",
            name="ck_parca_kullanim_zimmet_cevap",
        ),
        CheckConstraint("adet > 0", name="ck_parca_kullanim_adet"),
        Index("ix_parca_kullanim_durum", "durum"),
    )

    stock_movement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stock_movements.id", ondelete="RESTRICT")
    )
    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    adet: Mapped[int] = mapped_column(Integer)
    kullanan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    durum: Mapped[str] = mapped_column(
        String(12), server_default=text("'BEKLIYOR'"), default="BEKLIYOR"
    )
    onaylayan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    onay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    red_nedeni: Mapped[str | None] = mapped_column(String(200))
    zimmet_durumu: Mapped[str | None] = mapped_column(String(12))
    zimmet_aciklama: Mapped[str | None] = mapped_column(String(500))


SOKULEN_KARARLARI = ("IADE_TAMIR", "IADE_HURDA", "MUSTERIDE")


class ServiceRemovedPart(Base, PkMixin, TimestampMixin, ActorMixin):
    """S5.2: arızalı/sökülen parça iş emrine yazılır; karar ZORUNLU.

    Depoya iade (tamir edilebilir ya da hurda) ya da müşteride kaldı.
    Arızalı parça kullanılabilir stoğa GİRMEZ (stok defterine yazılmaz):
    depoya fiziksel iade ve tamir/hurda ayrımı izlenir, bakiye şişmez.
    """

    __tablename__ = "service_removed_parts"
    __table_args__ = (
        CheckConstraint(_in("karar", SOKULEN_KARARLARI), name="ck_sokulen_karar"),
        CheckConstraint("adet > 0", name="ck_sokulen_adet"),
        CheckConstraint(
            "product_id IS NOT NULL OR length(trim(coalesce(tanim, ''))) > 0",
            name="ck_sokulen_tanim",
        ),
        CheckConstraint(
            "karar = 'MUSTERIDE' OR warehouse_id IS NOT NULL", name="ck_sokulen_iade_depo"
        ),
        Index("ix_sokulen_is", "service_order_id"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    tanim: Mapped[str | None] = mapped_column(String(160))
    # Seri no METİN (baştaki sıfırlar korunur).
    seri_no: Mapped[str | None] = mapped_column(String(80))
    adet: Mapped[int] = mapped_column(Integer)
    karar: Mapped[str] = mapped_column(String(12))
    warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    notes: Mapped[str | None] = mapped_column(String(500))
    # Depo teslim aldı mı (iade kararında; teslim alan `teslim_alan_id`).
    teslim_alindi: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    teslim_alan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


__all__ = [
    "KULLANIM_ONAY_DURUMLARI",
    "PARCA_TALEP_ACIK_DURUMLAR",
    "PARCA_TALEP_DURUMLARI",
    "SAYIM_DURUMLARI",
    "SOKULEN_KARARLARI",
    "ServicePartRequest",
    "ServicePartUsageReview",
    "ServiceRemovedPart",
    "StockCount",
    "StockCountLine",
    "ZIMMET_DURUMLARI",
]
