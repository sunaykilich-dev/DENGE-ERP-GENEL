"""Montaj noktası hak edişi (brief §4.7).

Üç tasarım kararı gerçek veriden çıktı:

1. **Tarife bağlayıcı değil, öneri.** Aynı montaj noktası + aynı iş tipinde
   250/350/400 TL, bir kayıtta 2.750 TL var. Tarifeden gelen fiyatı zorlamak
   ay sonu dökümünü gerçek ödemeyle tutmaz hale getirirdi. `unit_price` elle
   geçersiz kılınabilir ve `price_source` bunu kaydeder.

2. **Vergi oranları satıra dondurulur** (`tax_snapshot`). Ayarlardan oran
   değişince geçmiş dökümler DEĞİŞMEZ.

3. **Kapanmış dönem değişmez.** `ODENDI` olan dökümün satırları kilitlenir;
   düzeltme sonraki döneme devreden AYRI bir satır olarak girer
   (`correction_of_line_id`). Kilidi kırma yolu yoktur — denetim izi
   anlamını korusun diye.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)

# Hak ediş iş tipleri. Brief'teki BOLGE_FARKI ve EK_UCRET gerçek veride hiç
# kullanılmamış; YOL_KM ise ziyaret başına eklenen gerçek bir kalem.
HAK_EDIS_IS_TIPLERI = (
    "ATS_MONTAJ",
    # OBD soketine takılan ATS: kablolama yok, bu yüzden ayrı (ve ucuz) kalem.
    "OBD_ATS_MONTAJ",
    "DASHCAM_MONTAJ",
    "HARICI_KAMERA_MONTAJ",
    "SOKUM",
    "SOK_TAK",
    "DEGISIM",
    "ARIZA",
    "KESIF",
    "YOL_KM",
)

# Cihaz rolü → hak ediş iş tipi. TEK KAYNAK: hem iş emri girişindeki fiyat
# önizlemesi hem ay sonu döküm bunu kullanır. İki serviste ayrı ayrı yazılıydı
# ve "ayrışırsa girişte önizlenen fiyatla ödenen fiyat tutmaz" diye not
# düşülmüştü; ayrışma ihtimalini bırakmamak için buraya taşındı.
ROL_IS_TIPI = {
    "KAMERA": "DASHCAM_MONTAJ",
    "YARDIMCI_KAMERA": "HARICI_KAMERA_MONTAJ",
    "AKSESUAR": "HARICI_KAMERA_MONTAJ",
    "OBD_TAKIP": "OBD_ATS_MONTAJ",
}

# İş emri tipi doğrudan iş tipi olan durumlar (rol'e bakılmaz).
ROLDEN_BAGIMSIZ = ("SOKUM", "SOK_TAK", "DEGISIM", "ARIZA", "KESIF")


def is_tipi_coz(wo_tipi: str, device_role: str | None) -> str:
    """İş emri tipi + cihaz rolünden hak ediş iş tipini türetir."""
    if wo_tipi in ROLDEN_BAGIMSIZ:
        return wo_tipi
    return ROL_IS_TIPI.get((device_role or "").upper(), "ATS_MONTAJ")


DOKUM_DURUMLARI = (
    "TASLAK",
    "ONAY_BEKLIYOR",
    "ONAYLANDI",
    "ITIRAZDA",
    "ODEME_BEKLIYOR",
    "ODENDI",
)

_TARIFE_ARALIK = literal_column("tstzrange(valid_from, valid_to, '[)')")


class PartnerTariff(Base, PkMixin, TimestampMixin, ActorMixin):
    """Tarihli tarife. `partner_id` NULL = genel varsayılan tarife.

    Fiyat değişince eski işler ESKİ fiyattan hesaplanır (brief §4.7):
    tarife çözümlemesi işin tamamlanma tarihine bakar.
    """

    __tablename__ = "partner_tariffs"
    __table_args__ = (
        # Aynı (nokta, iş tipi, ürün grubu) için çakışan dönem olamaz.
        # partner_id NULL olduğunda EXCLUDE devreye girmez (NULL = NULL değil),
        # bu yüzden genel tarifeler için ayrı kısmi tekillik indeksi var.
        ExcludeConstraint(
            ("partner_id", "="),
            ("work_type", "="),
            ("product_group", "="),
            (_TARIFE_ARALIK, "&&"),
            name="ex_tarife_cakisma",
            using="gist",
        ),
        Index(
            "uq_genel_tarife_acik",
            "work_type",
            "product_group",
            unique=True,
            postgresql_where=text("partner_id IS NULL AND valid_to IS NULL"),
        ),
        CheckConstraint("unit_price >= 0", name="ck_tarife_fiyat"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_tarife_aralik"),
    )

    partner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    work_type: Mapped[str] = mapped_column(String(24))
    # Ürün grubu = ürün ailesi (L300, GS900, DAHUA…). Brief'te araç tipi de
    # vardı; gerçek tarifede araç tipi boyutu HİÇ YOK, eklenmedi.
    product_group: Mapped[str] = mapped_column(String(40), server_default=text("'*'"))
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class PartnerSettlement(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin, SourceMixin):
    """Ay sonu hak ediş dökümü (montaj noktası × dönem)."""

    __tablename__ = "partner_settlements"
    __table_args__ = (
        UniqueConstraint("partner_id", "period", name="uq_dokum_nokta_donem"),
        UniqueConstraint("source_system", "source_ref", name="uq_dokum_kaynak"),
        CheckConstraint("period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_dokum_donem_bicimi"),
        CheckConstraint(
            "status IN ('TASLAK','ONAY_BEKLIYOR','ONAYLANDI','ITIRAZDA','ODEME_BEKLIYOR','ODENDI')",
            name="ck_dokum_durum",
        ),
        Index("ix_dokum_donem", "period"),
    )

    partner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    # Fatura başka tüzel kişi adına kesilebiliyor (montaj noktası kartındaki
    # varsayılan buraya kopyalanır, döküm bazında değiştirilebilir).
    billing_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    period: Mapped[str] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'TASLAK'"))

    gross_amount: Mapped[float] = mapped_column(Numeric(14, 2), server_default=text("0"))
    deduction_amount: Mapped[float] = mapped_column(Numeric(14, 2), server_default=text("0"))
    withholding_amount: Mapped[float] = mapped_column(Numeric(14, 2), server_default=text("0"))
    stamp_tax_amount: Mapped[float] = mapped_column(Numeric(14, 2), server_default=text("0"))
    vat_amount: Mapped[float] = mapped_column(Numeric(14, 2), server_default=text("0"))
    net_payable: Mapped[float] = mapped_column(Numeric(14, 2), server_default=text("0"))

    # Hesaplama anındaki oranlar ve belge tipi. Ayarlar sonradan değişse de
    # bu döküm aynı sonucu üretir.
    tax_snapshot: Mapped[dict | None] = mapped_column(JSONB)

    partner_document_no: Mapped[str | None] = mapped_column(String(40))
    partner_document_date: Mapped[date | None] = mapped_column(Date)

    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["SettlementLine"]] = relationship(
        back_populates="settlement", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def kilitli(self) -> bool:
        return self.status == "ODENDI"


class SettlementLine(Base, PkMixin, TimestampMixin):
    __tablename__ = "settlement_lines"
    __table_args__ = (
        # Bir iş emri kalemi aynı dökümde iki kez görünemez (ay sonu kapanışı
        # tekrar çalıştırılırsa kopya üretmesin).
        Index(
            "uq_sl_kalem",
            "settlement_id",
            "work_order_item_id",
            unique=True,
            postgresql_where=text("work_order_item_id IS NOT NULL AND NOT is_deduction"),
        ),
        CheckConstraint("quantity > 0", name="ck_sl_adet"),
        Index("ix_sl_dokum", "settlement_id"),
    )

    settlement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("partner_settlements.id", ondelete="CASCADE")
    )
    work_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("work_orders.id", ondelete="SET NULL")
    )
    work_order_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("work_order_items.id", ondelete="SET NULL")
    )
    work_type: Mapped[str] = mapped_column(String(24))
    description: Mapped[str | None] = mapped_column(String(300))
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2))
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), server_default=text("1"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    price_source: Mapped[str | None] = mapped_column(String(10))

    is_deduction: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    deduction_reason: Mapped[str | None] = mapped_column(String(200))

    # Kapanmış dönem düzeltmesi: eski satır DEĞİŞMEZ, yeni dönemde bunu
    # işaret eden bir düzeltme satırı açılır.
    correction_of_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("settlement_lines.id", ondelete="SET NULL")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    settlement: Mapped[PartnerSettlement] = relationship(back_populates="lines")


class SettlementDispute(Base, PkMixin, TimestampMixin, ActorMixin):
    """Montaj noktasının itirazı (brief §4.7 madde 4)."""

    __tablename__ = "settlement_disputes"

    settlement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("partner_settlements.id", ondelete="CASCADE"), index=True
    )
    line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("settlement_lines.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'ACIK'"))
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base, PkMixin, TimestampMixin, ActorMixin):
    """Ödeme/tahsilat kaydı.

    Genel muhasebe kapsam dışı; burada tutulan "hangi hak ediş/abonelik ne
    zaman ne kadar ödendi" bilgisi. Bu olmadan "3 aydır ödemedi, aboneliği
    askıya al" kararı sistemde tetiklenemez ve kârlılık raporları
    faturalananı gösterir, tahsil edileni değil.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_payment_tutar"),
        CheckConstraint("direction IN ('GELEN','GIDEN')", name="ck_payment_yon"),
        Index("ix_payment_hesap", "account_id", "paid_at"),
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    # GIDEN = montaj noktasına ödeme, GELEN = müşteriden tahsilat
    direction: Mapped[str] = mapped_column(String(6))
    settlement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("partner_settlements.id", ondelete="SET NULL"), index=True
    )
    # Tahsilat neyin karşılığı: abonelik ve/veya dönem. İkisi de boşsa
    # "hesaba mahsuben" genel tahsilattır — bakiyeye yine girer.
    subscription_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    period: Mapped[str | None] = mapped_column(String(7))  # YYYY-AA
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[date] = mapped_column(Date)
    method: Mapped[str | None] = mapped_column(String(20))  # HAVALE, NAKIT, CEK…
    reference: Mapped[str | None] = mapped_column(String(80))  # dekont no
    notes: Mapped[str | None] = mapped_column(Text)
