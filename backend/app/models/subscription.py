"""Abonelik ve sözleşme (brief §4.11).

**Abonelik ücreti tarihlidir.** Tek `unit_price` kolonu, "geçen ay ne kadar
tahakkuk etmişti" sorusunu cevaplayamaz ve D9b'nin toplu zam aracı geçmişi
sessizce bozardı. Ücret `subscription_prices` içinde `[)` yarı açık
aralıklarla durur, çakışma EXCLUDE ile engellenir.

**MRR olay tablosuyla tutulur.** Ay sonunda tüm abonelikleri tarayıp fark
almak yerine her değişiklik (`YENI`, `ARTIS`, `AZALIS`, `ASKI`, `GERI_DONUS`,
`IPTAL`) kendi MRR etkisini yazar. Churn ve büyüme böyle açıklanabilir olur:
"bu ay MRR neden düştü" sorusunun cevabı satır satır durur.

**Kıst hesap gün bazlıdır:** dönemdeki aktif gün / dönemdeki toplam gün.
Ayların 28–31 gün çekmesi bu yüzden kendiliğinden doğru çalışır.
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
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionedMixin,
)

ABONELIK_DURUMLARI = ("TASLAK", "AKTIF", "ASKIDA", "IPTAL", "SONA_ERDI")

# Fatura periyodu aylık MRR'a normalize edilir (YILLIK/12, UC_AYLIK/3).
FATURA_PERIYOTLARI = ("AYLIK", "UC_AYLIK", "ALTI_AYLIK", "YILLIK")
PERIYOT_AY = {"AYLIK": 1, "UC_AYLIK": 3, "ALTI_AYLIK": 6, "YILLIK": 12}

YENILEME_TIPLERI = ("OTOMATIK", "MANUEL", "YOK")

MRR_OLAYLARI = ("YENI", "ARTIS", "AZALIS", "ASKI", "GERI_DONUS", "IPTAL", "SONA_ERDI")

_FIYAT_ARALIK = literal_column("daterange(valid_from, valid_to, '[)')")


class Subscription(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("subscription_no", name="uq_subscription_no"),
        CheckConstraint(
            "status IN ('TASLAK','AKTIF','ASKIDA','IPTAL','SONA_ERDI')",
            name="ck_sub_durum",
        ),
        CheckConstraint(
            "billing_period IN ('AYLIK','UC_AYLIK','ALTI_AYLIK','YILLIK')",
            name="ck_sub_periyot",
        ),
        CheckConstraint("renewal_type IN ('OTOMATIK','MANUEL','YOK')", name="ck_sub_yenileme"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_sub_tarih"),
        Index("ix_sub_musteri", "customer_id"),
        Index("ix_sub_durum", "status"),
        Index("ix_sub_arac", "vehicle_id"),
        Index("ix_sub_cihaz", "device_id"),
    )

    subscription_no: Mapped[str] = mapped_column(String(24))
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    # Abonelik çoğunlukla araç başınadır; cihaz ve hat bağı izlenebilirlik için.
    vehicle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="SET NULL")
    )
    sim_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sim_cards.id", ondelete="SET NULL")
    )
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="SET NULL")
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL")
    )

    status: Mapped[str] = mapped_column(String(12), server_default=text("'TASLAK'"))
    title: Mapped[str | None] = mapped_column(String(200))

    billing_period: Mapped[str] = mapped_column(String(12), server_default=text("'AYLIK'"))
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'TRY'"))
    # KDV oranı sözleşmeye DONDURULUR (plan §3.3/2).
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))

    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    # Taahhüt bitmeden toplu zam uygulanmaz — D9b bu alana bakar.
    commitment_end_date: Mapped[date | None] = mapped_column(Date)
    renewal_type: Mapped[str] = mapped_column(String(10), server_default=text("'OTOMATIK'"))
    renewal_months: Mapped[int] = mapped_column(Integer, server_default=text("12"))
    notice_days: Mapped[int] = mapped_column(Integer, server_default=text("30"))
    auto_suspend_on_debt: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Churn analizi bu alanla anlam kazanır; iptal nedeni zorunlu tutulur.
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    prices: Mapped[list["SubscriptionPrice"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )


class SubscriptionPrice(Base, PkMixin, TimestampMixin, ActorMixin):
    """Abonelik ücretinin tarihli geçmişi — `[)` yarı açık aralık."""

    __tablename__ = "subscription_prices"
    __table_args__ = (
        ExcludeConstraint(
            ("subscription_id", "="),
            (_FIYAT_ARALIK, "&&"),
            name="ex_sub_fiyat_cakisma",
            using="gist",
        ),
        Index(
            "uq_sub_fiyat_acik",
            "subscription_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_sub_fiyat_aralik"),
        CheckConstraint("unit_price >= 0", name="ck_sub_fiyat_negatif"),
    )

    subscription_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="CASCADE")
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    # "Neden değişti" — toplu zam, sözleşme yenileme, elle düzeltme.
    change_reason: Mapped[str | None] = mapped_column(String(200))
    price_batch_id: Mapped[int | None] = mapped_column(BigInteger)

    subscription: Mapped[Subscription] = relationship(back_populates="prices")


class SubscriptionEvent(Base, PkMixin, TimestampMixin, ActorMixin):
    """MRR olay kaydı — aylık yinelenen gelirin neden değiştiğinin izi."""

    __tablename__ = "subscription_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('YENI','ARTIS','AZALIS','ASKI','GERI_DONUS','IPTAL','SONA_ERDI')",
            name="ck_sub_olay_tip",
        ),
        Index("ix_sub_olay_tarih", "event_date"),
        Index("ix_sub_olay_abonelik", "subscription_id"),
    )

    subscription_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="CASCADE")
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(12))
    event_date: Mapped[date] = mapped_column(Date)
    # Aylığa normalize edilmiş etki: yeni abonelik +, iptal −.
    mrr_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    mrr_before: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    mrr_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    reason: Mapped[str | None] = mapped_column(String(200))
    # Toplu güncellemeyle yazıldıysa partisi — geri alma bunu kullanır.
    price_batch_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
