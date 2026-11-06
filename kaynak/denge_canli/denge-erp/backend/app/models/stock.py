"""Stok, transfer ve cihaz konum/sahiplik geçmişi (brief §4.3).

**Konsinye YOK** (kilitlenen karar: bayiye satış peşin). Bu yüzden sahiplik
dört değere iner ve brief'teki `BAYI_KONSINYE` kullanılmaz.

Konum ve sahiplik AYRI iki boyut: bir cihaz fiziksel olarak bayide dururken
ticari olarak Denge'nin malı olabilir (sevk edildi, fatura kesilmedi). Tek
alanda birleştirmek bu ayrımı kaybettirirdi.

Geçmiş tarihlidir: "bu cihaz geçmişte hangi tarihte neredeydi" sorusu
(brief §4.3) ancak böyle cevaplanır.
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
    Integer,
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
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)

KONUM_TIPLERI = (
    "MERKEZ_DEPO",
    "BOLGE_DEPO",
    "TEKNISYEN",
    "MONTAJ_NOKTASI",
    "BAYI",
    "MUSTERI",
    "YOLDA",
    "SERVIS",
    "HURDA",
)

# Konsinye kapsam dışı — bayiye satış peşin.
SAHIPLIK_DURUMLARI = ("DENGE", "BAYI_SATILDI", "MUSTERI_SATILDI", "MUSTERI_KIRALIK")

TRANSFER_TIPLERI = ("SATIS", "IADE", "IC_TRANSFER", "SERVIS_GONDERIM", "SERVIS_DONUS")
TRANSFER_DURUMLARI = ("TASLAK", "YOLDA", "TESLIM_EDILDI", "IPTAL")

_ARALIK = literal_column("tstzrange(valid_from, valid_to, '[)')")


class Warehouse(Base, PkMixin, TimestampMixin):
    """Depo/lokasyon tanımı — merkez, bölge ve teknisyen araç stoğu."""

    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("code", name="uq_warehouse_code"),)

    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    location_type: Mapped[str] = mapped_column(String(20), server_default=text("'BOLGE_DEPO'"))
    # Teknisyen araç stoğu için kullanıcı, bayi/montaj noktası için hesap.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class DeviceCustodyHistory(Base, PkMixin, TimestampMixin):
    """Cihazın konum ve sahiplik geçmişi — tarihli.

    Çakışma kısıtı CİHAZ üzerinde: bir cihaz aynı anda tek yerde olabilir.
    """

    __tablename__ = "device_custody_history"
    __table_args__ = (
        ExcludeConstraint(
            ("device_id", "="), (_ARALIK, "&&"), name="ex_custody_cakisma", using="gist"
        ),
        Index(
            "uq_custody_acik",
            "device_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_custody_aralik"),
        CheckConstraint(
            "location_type IN ('MERKEZ_DEPO','BOLGE_DEPO','TEKNISYEN','MONTAJ_NOKTASI',"
            "'BAYI','MUSTERI','YOLDA','SERVIS','HURDA')",
            name="ck_custody_konum",
        ),
        CheckConstraint(
            "ownership IN ('DENGE','BAYI_SATILDI','MUSTERI_SATILDI','MUSTERI_KIRALIK')",
            name="ck_custody_sahiplik",
        ),
        Index("ix_custody_konum", "location_type", "account_id"),
    )

    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"))
    location_type: Mapped[str] = mapped_column(String(20))
    warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="SET NULL")
    )
    # Bayi/müşteri/montaj noktası konumlarında ilgili hesap.
    account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    ownership: Mapped[str] = mapped_column(String(20), server_default=text("'DENGE'"))
    transfer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transfers.id", ondelete="SET NULL")
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(300))


class Transfer(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin, SourceMixin):
    """Transfer belgesi — IMEI listesiyle toplu sevk/iade/zimmet."""

    __tablename__ = "transfers"
    __table_args__ = (
        UniqueConstraint("transfer_no", name="uq_transfer_no"),
        UniqueConstraint("source_system", "source_ref", name="uq_transfer_kaynak"),
        CheckConstraint(
            "type IN ('SATIS','IADE','IC_TRANSFER','SERVIS_GONDERIM','SERVIS_DONUS')",
            name="ck_transfer_tip",
        ),
        CheckConstraint(
            "status IN ('TASLAK','YOLDA','TESLIM_EDILDI','IPTAL')", name="ck_transfer_durum"
        ),
        Index("ix_transfer_durum", "status"),
    )

    transfer_no: Mapped[str] = mapped_column(String(24))
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'TASLAK'"))
    # Müşteri sevkiyatı bir siparişten doğar; ayrı bir "shipments" tablosu
    # yerine transfer belgesi kullanılır (bkz. app/models/order.py başlığı).
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )

    from_location_type: Mapped[str] = mapped_column(String(20))
    from_warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="SET NULL")
    )
    from_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    to_location_type: Mapped[str] = mapped_column(String(20))
    to_warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="SET NULL")
    )
    to_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    # Transferle birlikte sahiplik de değişiyorsa (bayiye satış gibi).
    new_ownership: Mapped[str | None] = mapped_column(String(20))

    document_no: Mapped[str | None] = mapped_column(String(40))
    shipped_at: Mapped[date | None] = mapped_column(Date)
    delivered_at: Mapped[date | None] = mapped_column(Date)
    delivered_by: Mapped[str | None] = mapped_column(String(120))
    received_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["TransferItem"]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan", lazy="selectin"
    )


class TransferItem(Base, PkMixin):
    __tablename__ = "transfer_items"
    __table_args__ = (
        UniqueConstraint("transfer_id", "device_id", name="uq_transfer_cihaz"),
        Index("ix_transfer_item_device", "device_id"),
    )

    transfer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transfers.id", ondelete="CASCADE")
    )
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="RESTRICT")
    )

    transfer: Mapped[Transfer] = relationship(back_populates="items")


# Seri numarasıyla takip EDİLMEYEN ürünlerin (aksesuar, kablo, montaj
# malzemesi) stok hareketleri. Bakiye ayrı bir kolonda TUTULMAZ, hareket
# toplamından hesaplanır: iki kaynak olsaydı zamanla birbirinden ayrışır ve
# hangisinin doğru olduğu tartışılırdı. Cihazlarda böyle bir tabloya gerek
# yok — orada her adedin kendi kaydı var (`devices`).
STOK_HAREKET_NEDENLERI = (
    "GIRIS",  # satın alma, iade, üretimden giriş
    "CIKIS",  # montajda kullanıldı, satıldı, zayi
    "SAYIM",  # fiziksel sayım düzeltmesi
    "TRANSFER",  # depolar arası
)


class StockMovement(Base, PkMixin, TimestampMixin, ActorMixin):
    """Serisiz ürün stok hareketi. Eldeki adet = hareketlerin toplamı."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('GIRIS','CIKIS','SAYIM','TRANSFER')", name="ck_stok_hareket_neden"
        ),
        CheckConstraint("qty <> 0", name="ck_stok_hareket_adet"),
        Index("ix_stok_hareket_urun", "product_id", "warehouse_id"),
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="SET NULL")
    )
    # Eksi değer çıkıştır; işaret nedenden DEĞİL adetten okunur, böylece
    # "SAYIM" hem artı hem eksi olabilir.
    qty: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(20), server_default=text("'GIRIS'"))
    document_no: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(String(300))
