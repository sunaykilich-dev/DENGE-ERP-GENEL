"""İş bazlı maliyet ve gelir (E07): işçilik tarifesi ve iş finansı.

**Maliyet alanları servis işinden YAPISAL olarak ayrıdır:** `service_orders`
çıktısı fiyat/maliyet anahtarı taşımaz; gelir, diğer maliyet ve fatura devri
1:1 ayrı tabloda (`service_order_financials`) durur ve yalnız `maliyet.gor`
sahibine döner (`maliyet.yaz` ile yazılır).

**NULL ≠ 0** (E07-12): satır yoksa ya da `gelir` NULL ise "gelir girilmedi"dir;
ücretsiz garanti işi `gelir_kaynagi='UCRETSIZ_GARANTI'` ve `gelir=0` ile
açıkça ayrılır. Tarife tanımsızken işçilik sessizce 0 hesaplanmaz
(`TARIFE_EKSIK`, E07-11); tarife 0 girilemez.

Tarife yarı açık tarih aralığıdır; aynı birimde çakışan iki tarife olamaz
(`ex_iscilik_tarife_cakisma`). Hatalı ileri tarihli satır silinmez,
`valid_to = valid_from` ile (boş aralık) gerekçeli kapatılır.
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
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin
from app.models.rbac import birim_check

GELIR_KAYNAKLARI = ("TEKLIF", "ELLE", "SOZLESME", "UCRETSIZ_GARANTI")
# Maliyet analizi satır durumu (hesaplanır, saklanmaz; E07-10).
MALIYET_DURUMLARI = ("TAM", "SURE_EKSIK", "MALIYET_EKSIK", "TARIFE_EKSIK")

_TARIFE_ARALIGI = literal_column("daterange(valid_from, valid_to, '[)')")


class ServiceLaborRate(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """Birim saatlik iç maliyet tarifesi (E07-20). Silme yok."""

    __tablename__ = "service_labor_rates"
    __table_args__ = (
        CheckConstraint(birim_check("birim"), name="ck_iscilik_tarife_birim"),
        # `>=`: valid_to = valid_from boş aralıktır ve hatalı satırı kapatır (B8).
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="ck_iscilik_tarife_aralik"
        ),
        CheckConstraint("hourly_cost > 0", name="ck_iscilik_tarife_pozitif"),
        ExcludeConstraint(
            ("birim", "="),
            (_TARIFE_ARALIGI, "&&"),
            name="ex_iscilik_tarife_cakisma",
            using="gist",
        ),
        Index(
            "uq_iscilik_tarife_acik",
            "birim",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    birim: Mapped[str] = mapped_column(String(20))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    hourly_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Geçmiş tarihli girişte zorunlu (servis; `sistem.ayar` + gerekçe).
    gerekce: Mapped[str | None] = mapped_column(String(300))


class ServiceOrderFinancial(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """İş geliri, diğer maliyet ve fatura devri — servis işiyle 1:1 (E07-12/26).

    Satır ilk gelir girişinde ya da teklif kabulünde açılır; eşzamanlı iki
    açılış `uq_sof_is` ile 409 olur. `fatura_iletildi_at` doluyken gelir ve
    maliyet yazımı 409'dur (E07-D04).
    """

    __tablename__ = "service_order_financials"
    __table_args__ = (
        UniqueConstraint("service_order_id", name="uq_sof_is"),
        CheckConstraint("gelir IS NULL OR gelir >= 0", name="ck_sof_gelir_negatif"),
        CheckConstraint(
            "gelir_kaynagi IS NULL OR gelir_kaynagi IN ("
            + ", ".join(f"'{k}'" for k in GELIR_KAYNAKLARI)
            + ")",
            name="ck_sof_gelir_kaynagi",
        ),
        CheckConstraint(
            "(gelir IS NULL) = (gelir_kaynagi IS NULL)", name="ck_sof_gelir_kaynak_tutarli"
        ),
        CheckConstraint(
            "gelir_kaynagi IS NULL OR gelir_kaynagi NOT IN ('ELLE', 'UCRETSIZ_GARANTI') "
            "OR gelir_notu IS NOT NULL",
            name="ck_sof_gelir_notu",
        ),
        CheckConstraint(
            "gelir_kaynagi IS DISTINCT FROM 'UCRETSIZ_GARANTI' OR gelir = 0",
            name="ck_sof_ucretsiz_sifir",
        ),
        CheckConstraint("diger_maliyet IS NULL OR diger_maliyet >= 0", name="ck_sof_diger_negatif"),
        CheckConstraint(
            "diger_maliyet IS NULL OR diger_maliyet_notu IS NOT NULL", name="ck_sof_diger_notu"
        ),
        # Devri yapan kişi yalnız devir anıyla birlikte (kişi silinirse SET NULL).
        CheckConstraint(
            "fatura_iletildi_by IS NULL OR fatura_iletildi_at IS NOT NULL",
            name="ck_sof_fatura_devri",
        ),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    gelir: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    gelir_kaynagi: Mapped[str | None] = mapped_column(String(16))
    gelir_notu: Mapped[str | None] = mapped_column(Text)
    diger_maliyet: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    diger_maliyet_notu: Mapped[str | None] = mapped_column(Text)
    fatura_iletildi_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fatura_iletildi_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    fatura_notu: Mapped[str | None] = mapped_column(String(300))


__all__ = [
    "GELIR_KAYNAKLARI",
    "MALIYET_DURUMLARI",
    "ServiceLaborRate",
    "ServiceOrderFinancial",
]
