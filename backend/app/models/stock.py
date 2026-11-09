"""Stok, transfer ve cihaz konum/sahiplik geçmişi (brief §4.3).

**Konsinye YOK** (kilitlenen karar: bayiye satış peşin). Bu yüzden sahiplik
dört değere iner ve brief'teki `BAYI_KONSINYE` kullanılmaz.

Konum ve sahiplik AYRI iki boyut: bir cihaz fiziksel olarak bayide dururken
ticari olarak Denge'nin malı olabilir (sevk edildi, fatura kesilmedi). Tek
alanda birleştirmek bu ayrımı kaybettirirdi.

Geçmiş tarihlidir: "bu cihaz geçmişte hangi tarihte neredeydi" sorusu
(brief §4.3) ancak böyle cevaplanır.
"""

import uuid
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
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)
from app.models.rbac import birim_check

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
    """Depo/lokasyon tanımı — merkez, bölge ve teknisyen araç stoğu.

    **Teknik servis genişlemesi (Dalga 2, d2a000000003, plan §1.12):** aynı
    tablo kiralama depolarını (`kiralama_deposu`) ve servis/yedek parça
    depolarını (`servis_deposu`) da taşır; bir depo ikisi birden olamaz
    (`ck_warehouse_tur_tekil`). Mevcut satırlar iki bayrakta da false kalır
    ve mobilite uçları (`/api/stok/depolar`, hareket/transfer) YALNIZ iki
    bayrağı da false olan depoları görür/kabul eder — aksi hâlde mobilite
    cihazı kiralama deposuna yazılabilirdi (E06-D01, E11-D01). Kiralama
    deposunda `birim` NULL = ortak depo. Servis deposu birimsiz OLAMAZ
    (kullanıcı isteği 2026-11-09: Haberleşme/Güvenlik depoları tamamen ayrı,
    `ck_warehouse_servis_birim_zorunlu`; görünürlük `teknik_servis.parca.depo_kosulu`).
    """

    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("code", name="uq_warehouse_code"),
        CheckConstraint(birim_check("birim", bos_olabilir=True), name="ck_warehouse_birim"),
        CheckConstraint("NOT (servis_deposu AND kiralama_deposu)", name="ck_warehouse_tur_tekil"),
        # Birim ayrımı (2026-11-09, fba000000001): servis deposu birimsiz olamaz.
        # Canlıda NOT VALID eklenir; eşlenemeyen eski satır güncellenene dek kalır.
        CheckConstraint(
            "NOT servis_deposu OR birim IS NOT NULL", name="ck_warehouse_servis_birim_zorunlu"
        ),
    )

    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    location_type: Mapped[str] = mapped_column(String(20), server_default=text("'BOLGE_DEPO'"))
    # Teknisyen araç stoğu için kullanıcı, bayi/montaj noktası için hesap.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # --- Teknik servis (Dalga 2) -------------------------------------------
    birim: Mapped[str | None] = mapped_column(String(20))
    kiralama_deposu: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    servis_deposu: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )


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


# Servis (yedek parça) defteri hareket türleri (E11-01, Dalga 2). NULL = canlı
# mobilite hareketi; canlı `reason` CHECK'i DEĞİŞMEZ, tür ayrı kolondadır ve
# tür → (neden, işaret) eşlemesi şemada kilitlidir (`ck_stok_hareket_tur_yon`).
SERVIS_HAREKET_TURLERI = (
    "GIRIS",
    "ACILIS",
    "CIKIS_SERVIS",
    "IADE_SERVIS",
    "ZAYI",
    "TERS_KAYIT",
    "TRANSFER_CIKIS",
    "TRANSFER_GIRIS",
    "SAYIM_FAZLASI",
    "SAYIM_EKSIGI",
)
# (tür → canlı neden, işaret) — servis yazıcısı ve CHECK aynı tablodan.
SERVIS_HAREKET_YONU: dict[str, tuple[str, int]] = {
    "GIRIS": ("GIRIS", 1),
    "ACILIS": ("GIRIS", 1),
    "IADE_SERVIS": ("GIRIS", 1),
    "CIKIS_SERVIS": ("CIKIS", -1),
    "ZAYI": ("CIKIS", -1),
    "TRANSFER_CIKIS": ("TRANSFER", -1),
    "TRANSFER_GIRIS": ("TRANSFER", 1),
    "SAYIM_FAZLASI": ("SAYIM", 1),
    "SAYIM_EKSIGI": ("SAYIM", -1),
}


def _tur_yon_ifadesi() -> str:
    parcalar = ["hareket_turu IS NULL"]
    for tur, (neden, isaret) in SERVIS_HAREKET_YONU.items():
        kosul = "qty > 0" if isaret > 0 else "qty < 0"
        parcalar.append(f"(hareket_turu = '{tur}' AND reason = '{neden}' AND {kosul})")
    # Ters kayıt orijinalin nedenini ve işaretin tersini taşır.
    parcalar.append("(hareket_turu = 'TERS_KAYIT' AND reversal_of_id IS NOT NULL)")
    return " OR ".join(parcalar)


class StockMovement(Base, PkMixin, TimestampMixin, ActorMixin):
    """Serisiz ürün stok hareketi. Eldeki adet = hareketlerin toplamı.

    **Teknik servis genişlemesi (Dalga 2, d2a000000004, plan §1.12):** yedek
    parça defteri aynı tabloya yazılır (tek stok yazıcısı
    `services/teknik_servis/parca.hareket_yaz`). Yeni kolonların hepsi
    nullable; yeni CHECK'ler yalnız yeni kolonları sınar (mevcut satırlarda
    `hareket_turu IS NULL`). Servis satırları (`hareket_turu IS NOT NULL`)
    `trg_stok_hareket_degismez` ile UPDATE/DELETE'e kapalıdır; mobilite
    satırlarının davranışı değişmez. `unit_cost` hareket anında dondurulan
    birim maliyettir (TL, hareketli ağırlıklı ortalama; yoksa NULL — 0
    yazılmaz) ve yalnız `sees_cost` sahibine döner (KD-25).
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('GIRIS','CIKIS','SAYIM','TRANSFER')", name="ck_stok_hareket_neden"
        ),
        CheckConstraint("qty <> 0", name="ck_stok_hareket_adet"),
        Index("ix_stok_hareket_urun", "product_id", "warehouse_id"),
        # --- Dalga 2: servis defteri --------------------------------------
        CheckConstraint(
            "hareket_turu IS NULL OR hareket_turu IN ("
            + ", ".join(f"'{t}'" for t in SERVIS_HAREKET_TURLERI)
            + ")",
            name="ck_stok_hareket_tur",
        ),
        CheckConstraint(_tur_yon_ifadesi(), name="ck_stok_hareket_tur_yon"),
        CheckConstraint(
            "hareket_turu IS NULL OR hareket_turu NOT IN ('CIKIS_SERVIS', 'IADE_SERVIS') "
            "OR service_order_id IS NOT NULL",
            name="ck_stok_hareket_servis_isi",
        ),
        CheckConstraint(
            "hareket_turu IS NULL OR warehouse_id IS NOT NULL", name="ck_stok_hareket_depo"
        ),
        CheckConstraint(
            "hareket_turu IS DISTINCT FROM 'TERS_KAYIT' OR length(trim(coalesce(notes, ''))) > 0",
            name="ck_stok_hareket_ters_gerekce",
        ),
        CheckConstraint(
            "hareket_turu IS NULL OR hareket_turu NOT IN ('TRANSFER_CIKIS', 'TRANSFER_GIRIS') "
            "OR transfer_grup IS NOT NULL",
            name="ck_stok_hareket_transfer",
        ),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_stok_hareket_maliyet"),
        # Ters kayıt tek seferlik.
        Index(
            "uq_stok_hareket_ters",
            "reversal_of_id",
            unique=True,
            postgresql_where=text("reversal_of_id IS NOT NULL"),
        ),
        # (parça, depo) başına tek açılış (TS-134).
        Index(
            "uq_stok_hareket_acilis",
            "product_id",
            "warehouse_id",
            unique=True,
            postgresql_where=text("hareket_turu = 'ACILIS'"),
        ),
        Index(
            "ix_stok_hareket_servis",
            "service_order_id",
            postgresql_where=text("service_order_id IS NOT NULL"),
        ),
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

    # --- Teknik servis defteri (Dalga 2; hepsi nullable) ----------------------
    hareket_turu: Mapped[str | None] = mapped_column(String(20))
    service_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_orders.id", ondelete="RESTRICT", name="fk_stok_hareket_servis_isi"),
    )
    reversal_of_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("stock_movements.id", ondelete="RESTRICT", name="fk_stok_hareket_ters"),
    )
    # Transferin iki bacağı (ve ters kayıtları) aynı grubu taşır.
    transfer_grup: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    stock_count_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("stock_counts.id", ondelete="RESTRICT", name="fk_stok_hareket_sayim"),
    )
    part_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "service_part_requests.id", ondelete="SET NULL", name="fk_stok_hareket_parca_talebi"
        ),
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
