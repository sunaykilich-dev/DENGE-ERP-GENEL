"""İrsaliye (sevk irsaliyesi) ve boşluksuz belge numarası (KARARLAR 2026-11-09 S4.3).

**Bu e-İrsaliye DEĞİLDİR.** GİB entegrasyonu Faz D'de gelecek; burada
depodan şirket dışına çıkan malın numaralı, basılabilir kâğıt irsaliyesi
üretilir.

**Ne zaman oluşur:** stok `transfers` belgesi şirket DIŞINA (müşteri, bayi,
montaj noktası, dış servis) giden bir sevkiyat olduğunda aynı işlemde
(`services/irsaliye.olustur`). Satış siparişi sevki ve Stok ekranındaki dış
transfer bu yoldan geçer. Bir transferin TEK irsaliyesi olur (tekil kısıt).

**Numara boşluksuzdur:** `belge_sayaclari` satırı (seri, yıl) aynı işlemde
`INSERT … ON CONFLICT DO UPDATE … RETURNING` ile artırılır. Satır kilidi
işlem bitene kadar tutulur; işlem geri alınırsa sayaç da geri alınır, numara
yanmaz. İrsaliye silinmez; hatalı irsaliye gerekçeyle İPTAL edilir ve numarası
iptal olarak görünür kalır (numara yeniden kullanılmaz).

**Alıcı bilgisi dondurulur:** unvan, VKN ve adres irsaliye anındaki hâliyle
yazılır; cari kartı sonradan değişse de basılan belge değişmez.

**Muhasebe devri (S4.4):** Logo entegrasyonu YOK (ürün/sürüm bilinmiyor).
"Muhasebeye devredildi" işareti servis işlerindeki fatura devri kalıbıyla
aynıdır: kim/ne zaman/not, gerekçeli geri alma, denetim izi.
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
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin

IRSALIYE_DURUMLARI = ("DUZENLENDI", "IPTAL")


class BelgeSayaci(Base):
    """(seri, yıl) başına son verilen numara — boşluksuz belge numarası."""

    __tablename__ = "belge_sayaclari"
    __table_args__ = (CheckConstraint("son_no >= 0", name="ck_belge_sayaci_pozitif"),)

    seri: Mapped[str] = mapped_column(String(10), primary_key=True)
    yil: Mapped[int] = mapped_column(Integer, primary_key=True)
    son_no: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Irsaliye(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "irsaliyeler"
    __table_args__ = (
        UniqueConstraint("irsaliye_no", name="uq_irsaliye_no"),
        UniqueConstraint("yil", "sira", name="uq_irsaliye_yil_sira"),
        UniqueConstraint("transfer_id", name="uq_irsaliye_transfer"),
        CheckConstraint("durum IN ('DUZENLENDI','IPTAL')", name="ck_irsaliye_durum"),
        CheckConstraint(
            "durum <> 'IPTAL' OR length(trim(coalesce(iptal_nedeni, ''))) > 0",
            name="ck_irsaliye_iptal_nedeni",
        ),
        Index("ix_irsaliye_order", "order_id"),
        Index("ix_irsaliye_alici", "alici_account_id"),
        Index("ix_irsaliye_tarih", "duzenleme_tarihi"),
    )

    irsaliye_no: Mapped[str] = mapped_column(String(20))
    yil: Mapped[int] = mapped_column(Integer)
    sira: Mapped[int] = mapped_column(Integer)
    durum: Mapped[str] = mapped_column(String(16), server_default=text("'DUZENLENDI'"))

    transfer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transfers.id", ondelete="RESTRICT")
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL")
    )

    # Alıcı — irsaliye anındaki hâliyle dondurulur.
    alici_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    alici_unvan: Mapped[str] = mapped_column(String(200))
    alici_vkn: Mapped[str | None] = mapped_column(String(11))
    alici_vergi_dairesi: Mapped[str | None] = mapped_column(String(80))
    alici_adres: Mapped[str | None] = mapped_column(String(400))
    hedef_konum: Mapped[str] = mapped_column(String(20))

    cikis_depo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="SET NULL")
    )
    cikis_depo_adi: Mapped[str | None] = mapped_column(String(100))

    duzenleme_tarihi: Mapped[date] = mapped_column(Date)
    sevk_tarihi: Mapped[date] = mapped_column(Date)
    teslim_eden: Mapped[str | None] = mapped_column(String(120))
    notlar: Mapped[str | None] = mapped_column(Text)

    iptal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    iptal_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300))

    # S4.4 — "muhasebeye devredildi" işareti (Logo entegrasyonu değil).
    muhasebe_devri_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    muhasebe_devri_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    muhasebe_notu: Mapped[str | None] = mapped_column(String(300))

    kalemler: Mapped[list["IrsaliyeKalemi"]] = relationship(
        back_populates="irsaliye",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="IrsaliyeKalemi.sira",
    )


class IrsaliyeKalemi(Base, PkMixin):
    """İrsaliye satırı. Seri numaraları METİN olarak tutulur (korunacak karar)."""

    __tablename__ = "irsaliye_kalemleri"
    __table_args__ = (
        CheckConstraint("miktar > 0", name="ck_irsaliye_kalem_miktar"),
        Index("ix_irsaliye_kalem_irsaliye", "irsaliye_id"),
    )

    irsaliye_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("irsaliyeler.id", ondelete="CASCADE")
    )
    sira: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="SET NULL")
    )
    order_line_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("order_lines.id", ondelete="SET NULL")
    )
    stock_movement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stock_movements.id", ondelete="SET NULL")
    )
    urun_kodu: Mapped[str | None] = mapped_column(String(40))
    aciklama: Mapped[str] = mapped_column(String(300))
    miktar: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    birim: Mapped[str] = mapped_column(String(10), server_default=text("'ADET'"))
    # Virgülle ayrılmış IMEI / seri no listesi (metin; baştaki sıfır korunur).
    seri_nolar: Mapped[str | None] = mapped_column(Text)
    # Siparişten gelen satış fiyatı (dondurulmuş). Yalnız fiyat görme yetkisi
    # olana basılır/aktarılır; maliyet (alış) burada HİÇ tutulmaz.
    birim_fiyat: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    iskonto_yuzde: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    kdv_orani: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))

    irsaliye: Mapped[Irsaliye] = relationship(back_populates="kalemler")
