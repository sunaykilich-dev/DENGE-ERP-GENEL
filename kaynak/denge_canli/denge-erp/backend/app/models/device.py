"""Cihazlar — IMEI/seri no bazlı tekil kayıt.

KİMLİK KURALI VERİTABANINDA ZORLANIR. `identity_kind` ürün kartından
kopyalanır ve bileşik yabancı anahtarla (`product_id`, `identity_kind`) ürüne
bağlanır; üstüne CHECK kısıtı gelir:

    identity_kind='IMEI'    → imei NOT NULL
    identity_kind='SERI_NO' → serial_no NOT NULL

Böylece "IMEI zorunlu" kuralı yalnız serviste değil şemada yaşar: hatalı bir
uç, elle yazılmış bir SQL ya da göç betiği bile IMEI'siz bir takip cihazı
kaydedemez. Ürünün kimlik tipi değişirse FK `ON UPDATE CASCADE` ile cihazlara
yansır ve CHECK tutarsız satırı anında yakalar.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)

# Brief §4.2 durum listesi.
CIHAZ_DURUMLARI = (
    "ITHALATTA",
    "STOKTA",
    "TEST_EDILDI",
    "REZERVE",
    "SEVK_EDILDI",
    "MONTAJ_BEKLIYOR",
    "AKTIF",
    "SOKULDU",
    "ARIZALI",
    "RMA",
    "TAMIRDE",
    "YENIDEN_STOKTA",
    "HURDA",
    "KAYIP_CALINTI",
)

BTK_DURUMLARI = ("KAYITLI", "BEKLIYOR", "GEREKMIYOR")

# Aracdaki rolü — takip platformuna hangi cihazın bağlanacağını belirler.
# Platform araç başına TEK cihaz kabul ettiği sürece (vehicles.device_id UNIQUE)
# yalnız BIRINCIL_TAKIP gönderilir.
CIHAZ_ROLLERI = ("BIRINCIL_TAKIP", "KAMERA", "YARDIMCI_KAMERA", "AKSESUAR")


class Device(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    __tablename__ = "devices"
    __table_args__ = (
        # Ürünün kimlik tipi cihaza kopyalanır ve ürünle tutarlı kalmaya
        # zorlanır. Ürün kartında tip değişirse cihazlara da yansır.
        ForeignKeyConstraint(
            ["product_id", "identity_kind"],
            ["products.id", "products.identity_kind"],
            name="fk_devices_urun_kimlik",
            onupdate="CASCADE",
        ),
        CheckConstraint(
            "(identity_kind = 'IMEI' AND imei IS NOT NULL) OR "
            "(identity_kind = 'SERI_NO' AND serial_no IS NOT NULL) OR "
            "(identity_kind = 'YOK')",
            name="ck_devices_kimlik_zorunlu",
        ),
        # IMEI tekil — ama yalnız dolu olanlar arasında (ek kameralarda yok).
        Index("uq_devices_imei", "imei", unique=True, postgresql_where=text("imei IS NOT NULL")),
        Index(
            "uq_devices_seri",
            "serial_no",
            unique=True,
            postgresql_where=text("serial_no IS NOT NULL"),
        ),
        UniqueConstraint("source_system", "source_ref", name="uq_devices_kaynak"),
        CheckConstraint("id <> parent_device_id", name="ck_devices_kendi_ebeveyni_olamaz"),
        Index("ix_devices_durum", "status"),
        Index("ix_devices_ebeveyn", "parent_device_id"),
    )

    # --- Kimlik ---
    imei: Mapped[str | None] = mapped_column(String(15))
    serial_no: Mapped[str | None] = mapped_column(String(40))
    identity_kind: Mapped[str] = mapped_column(String(10), server_default=text("'IMEI'"))
    # Göçte IMEI'si bulunamayan 45 kayıt bu bayrakla girer; arayüzde "kimliği
    # geçici" rozetiyle görünür ve düzeltme listesine düşer.
    is_identity_provisional: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # --- Ek kamera → ana cihaz kanalı ---
    parent_device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="SET NULL")
    )
    channel_no: Mapped[int | None] = mapped_column(Integer)
    device_role: Mapped[str | None] = mapped_column(String(20))

    # --- Durum ---
    status: Mapped[str] = mapped_column(String(20), server_default=text("'STOKTA'"))

    # --- Denormalize "şu an" alanları -------------------------------------
    # Tarihli tablolardan TÜRETİLİR; gece çalışan uzlaşma işi farkı raporlar.
    # Doğruluk kaynağı daima tarihli tablodur (plan §3.2).
    current_sim_id: Mapped[int | None] = mapped_column(BigInteger)
    current_vehicle_id: Mapped[int | None] = mapped_column(BigInteger)
    current_customer_id: Mapped[int | None] = mapped_column(BigInteger)

    # --- Ticari / mevzuat ---
    landed_cost_try: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # Landed cost hangi dosyadan dağıtıldı — dosya güncellenince yeniden
    # dağıtım bu bağdan bulunur.
    import_file_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    goods_receipt_id: Mapped[int | None] = mapped_column(BigInteger)

    btk_status: Mapped[str] = mapped_column(String(12), server_default=text("'GEREKMIYOR'"))
    btk_registered_at: Mapped[date | None] = mapped_column(Date)
    btk_reference: Mapped[str | None] = mapped_column(String(60))
    first_activation_date: Mapped[date | None] = mapped_column(Date)
    warranty_end_date: Mapped[date | None] = mapped_column(Date)

    platform_device_id: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    product: Mapped["object"] = relationship(
        "Product",
        lazy="raise",
        primaryjoin="Device.product_id == Product.id",
        foreign_keys=[product_id],
    )

    @property
    def kimlik(self) -> str:
        """Ekranda ve raporlarda cihazı temsil eden değer."""
        return self.imei or self.serial_no or f"#{self.id}"


class DeviceStatusHistory(Base, PkMixin):
    """Durum geçiş günlüğü — kim, ne zaman, neden (brief §4.2)."""

    __tablename__ = "device_status_history"
    __table_args__ = (Index("ix_dsh_device", "device_id", "changed_at"),)

    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(200))
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    changed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
