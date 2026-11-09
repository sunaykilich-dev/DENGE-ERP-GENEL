"""Satış ile servis işi arasındaki bağ (KARARLAR 2026-11-09 S3, S4.1, S4.2).

Bir teklife ya da siparişe BİRDEN ÇOK servis işi bağlanabilir: keşif
(teklif aşamasında), kurulum ve teslimat (kabul/siparişten sonra). Eski
`quotes.service_order_id` sütunu tek işi taşır ve anlamı farklıdır (servis
teklifinin açıldığı iş / kabulde açılan iş; bekleme ve gelir aktarımı ona
bakar). O yüzden DEĞİŞMEZ; bağlı işler listesi ikisini birlikte gösterir
(`services/satis_takip.bagli_isler`).

Bir servis işi tek bir satış bağına sahiptir (`uq_satis_bag_is`): siparişten
açılan işte sipariş ve (varsa) siparişin teklifi aynı satırda tutulur; böylece
teklif ekranı siparişten açılan kurulumu da görür.
"""

from datetime import date

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin

# Bağ türü = satıştan açılan servis işinin türü (servis işi `tur` ile aynı kod).
SATIS_BAG_TURLERI = ("KESIF", "KURULUM", "TESLIMAT")


class SatisIsBagi(Base, PkMixin, TimestampMixin, ActorMixin):
    __tablename__ = "satis_is_baglari"
    __table_args__ = (
        UniqueConstraint("service_order_id", name="uq_satis_bag_is"),
        CheckConstraint("quote_id IS NOT NULL OR order_id IS NOT NULL", name="ck_satis_bag_kaynak"),
        CheckConstraint(
            "bag_turu IN (" + ", ".join(f"'{t}'" for t in SATIS_BAG_TURLERI) + ")",
            name="ck_satis_bag_turu",
        ),
        Index("ix_satis_bag_teklif", "quote_id"),
        Index("ix_satis_bag_siparis", "order_id"),
    )

    quote_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quotes.id", ondelete="CASCADE", name="fk_satis_bag_teklif")
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE", name="fk_satis_bag_siparis")
    )
    service_order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("service_orders.id", ondelete="RESTRICT", name="fk_satis_bag_servis_isi"),
    )
    bag_turu: Mapped[str] = mapped_column(String(12))
    # Satışçının istediği hedef tarih (keşifte varsayılan 5 iş günü, S3.2).
    # Servis işinde ayrı "hedef" sütunu yok (SLA hedefi PROJE işinde boş);
    # tarih işin açıklamasına da yazılır ki planlayan görsün.
    hedef_tarih: Mapped[date | None] = mapped_column(Date)
