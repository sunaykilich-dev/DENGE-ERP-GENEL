"""Ürün kataloğu.

En kritik alan `identity_kind`. Brief her cihazın IMEI'si olduğunu varsayıyordu;
gerçek veri bunu çürütüyor: Dahua HMW3200LP ve HAC serisi kameralar analog
(HDCVI) — modemleri ve SIM'leri yok, ana cihazın kanallarına kabloyla bağlanıyorlar.
898 montaj satırının 898'inde IMEI boş; bu bir personel hatası değil, donanımın
kendisi.

Çözüm: IMEI zorunluluğu ÜRÜNE bağlanır. `identity_kind='IMEI'` olan bir üründe
IMEI'siz cihaz kaydı sistem tarafından reddedilir (kullanıcının kuralı birebir
işler); `identity_kind='SERI_NO'` olan üründe seri no zorunlu olur.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
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
from app.models.rbac import sirket_check
from app.services.normalize import tr_normkey

URUN_TIPLERI = ("CIHAZ_SERILI", "AKSESUAR", "SIM_PAKETI", "ABONELIK_PLANI", "HIZMET")

# Cihazın sistemdeki doğal anahtarı ne olacak.
KIMLIK_TIPLERI = (
    "IMEI",  # takip cihazı, dashcam — modemi var
    "SERI_NO",  # analog ek kamera — IMEI'si fiziksel olarak yok
    "YOK",  # hizmet, abonelik planı, sayıyla takip edilen aksesuar
)

SEBEKE_TEKNOLOJILERI = ("2G", "3G", "4G", "LTE_M", "NB_IOT")

# Yedek parça ölçü birimleri (E11-11): tam sayı birimlerde ondalık reddedilir.
OLCU_BIRIMLERI = ("ADET", "METRE", "TAKIM", "LITRE", "PAKET", "KUTU")


class Product(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("code", name="uq_products_code"),
        # devices tablosundaki bileşik yabancı anahtarın hedefi: cihazın
        # kimlik tipi ürününkiyle tutarlı kalmaya ZORLANIR (bkz. device.py).
        UniqueConstraint("id", "identity_kind", name="uq_products_id_kimlik"),
        UniqueConstraint("source_system", "source_ref", name="uq_products_kaynak"),
        CheckConstraint(
            "type IN ('CIHAZ_SERILI','AKSESUAR','SIM_PAKETI','ABONELIK_PLANI','HIZMET')",
            name="ck_products_tip",
        ),
        CheckConstraint(
            "identity_kind IN ('IMEI','SERI_NO','YOK')", name="ck_products_kimlik_tipi"
        ),
        # Seri numarasıyla takip edilen ürün bir ana cihaza bağlanır (ek kamera
        # → dashcam kanalı). IMEI'li ürün kendi başına durur.
        CheckConstraint(
            "NOT requires_parent OR identity_kind = 'SERI_NO'",
            name="ck_products_ana_cihaz_seri_no_ile",
        ),
        # --- Teknik servis yedek parça (Dalga 2, d2a000000004) -------------
        CheckConstraint(
            "birim IS NULL OR birim IN (" + ", ".join(f"'{b}'" for b in OLCU_BIRIMLERI) + ")",
            name="ck_products_birim",
        ),
        CheckConstraint("min_stok IS NULL OR min_stok >= 0", name="ck_products_min_stok"),
        # Seri takipli ürün adetle izlenmez (yalnız yeni bayrağa uygulanır).
        CheckConstraint(
            "NOT yedek_parca OR identity_kind = 'YOK'", name="ck_products_yedek_parca_serisiz"
        ),
        # Şirket bazlı katalog (fcl000000001): NULL = ortak ürün.
        CheckConstraint(sirket_check("sirket"), name="ck_products_sirket"),
        Index("ix_products_sirket", "sirket"),
    )

    code: Mapped[str] = mapped_column(String(40))
    supplier_code: Mapped[str | None] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(160))
    name_key: Mapped[str] = mapped_column(String(160), index=True)  # tr_normkey(name)
    type: Mapped[str] = mapped_column(String(20), server_default=text("'CIHAZ_SERILI'"))
    # Marka ve model AYRI: katalog "Dahua CDR8213" diye tek metin tutuyordu ve
    # "elimde hangi Dahua ürünleri var" sorusu cevaplanamıyordu. `family` ürün
    # ailesidir (L300, GS900); `brand` üreticidir (Armoli, Dahua, Teltonika).
    brand: Mapped[str | None] = mapped_column(String(60), index=True)
    model: Mapped[str | None] = mapped_column(String(80))
    family: Mapped[str | None] = mapped_column(String(60))  # L300, GS900, DAHUA…

    identity_kind: Mapped[str] = mapped_column(String(10), server_default=text("'IMEI'"))
    # Ek kamera bir ana cihazın kanalına takılır; montajda ana cihaz seçilmesi
    # zorunlu olur ve "aracın arka kamerası arızalı" kaydı böyle tutulabilir.
    requires_parent: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    channel_count: Mapped[int | None] = mapped_column(Integer)  # MNVR/dashcam kanal sayısı

    supported_network_tech: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)))
    warranty_months: Mapped[int] = mapped_column(Integer, server_default=text("24"))
    is_112_approved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Okul servisi mevzuatı kapsamında kullanılabilir mi (brief §4.6).
    is_school_service_ready: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    vat_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    list_price: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'TRY'"))

    # Uygunluk belgeleri MODEL bazındadır (BTK IMEI kaydı ise cihaz bazında):
    # aynı CE belgesi binlerce IMEI'yi kapsar.
    ce_document_ref: Mapped[str | None] = mapped_column(String(120))
    tse_document_ref: Mapped[str | None] = mapped_column(String(120))
    conformity_document_ref: Mapped[str | None] = mapped_column(String(120))

    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    # Ürün görseli ve broşür/teknik doküman `attachments` tablosunda tutulur
    # (entity='products'); burada yalnız kapak görselinin ek kimliği durur ki
    # liste ekranı tek sorguda küçük resmi gösterebilsin.
    cover_attachment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attachments.id", ondelete="SET NULL")
    )

    # --- Teknik servis yedek parça (Dalga 2; canlı tabloya yalnız default'lu /
    # nullable kolon, plan §1.12). Yazma `parca.yonet` ucundan; `UrunIn/
    # UrunPatch`'e EKLENMEZ (yoksa `urun.yaz` ile parça yetkisi atlanırdı).
    yedek_parca: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    # Ölçü birimi (NULL = ADET); teknik servis BİRİMİ (GUVENLIK...) değildir.
    birim: Mapped[str | None] = mapped_column(String(10))
    # NULL/0 = az stok uyarısı yok.
    min_stok: Mapped[int | None] = mapped_column(Integer)

    # --- Şirket bazlı katalog (fcl000000001) ---------------------------------
    # Ürünün ait olduğu şirket (`permissions.SIRKETLER` kodu). NULL = ORTAK
    # ürün: her şirkette görünür. Cihazın şirketi ürününkidir (cihazda ayrı
    # sütun yok); görünürlük `services/sirket_kapsami.py`.
    sirket: Mapped[str | None] = mapped_column(String(20))

    bundle_items: Mapped[list["ProductBundleItem"]] = relationship(
        back_populates="bundle",
        foreign_keys="ProductBundleItem.bundle_id",
        cascade="all, delete-orphan",
    )

    @property
    def imei_zorunlu(self) -> bool:
        return self.identity_kind == "IMEI"


class ProductBundleItem(Base, PkMixin, TimestampMixin):
    """Set (paket) içeriği.

    Gerçek kurulum bir set: araç kamerası (CDR8213) + ek kamera (HMW3200LP) +
    araç takip (L300), aynı araca aynı gün. Set tek kalem olarak satılır,
    arka planda kalemlere ayrışır (brief §4.1).
    """

    __tablename__ = "product_bundle_items"
    __table_args__ = (
        UniqueConstraint("bundle_id", "product_id", name="uq_bundle_urun"),
        CheckConstraint("bundle_id <> product_id", name="ck_bundle_kendini_iceremez"),
        CheckConstraint("quantity > 0", name="ck_bundle_adet_pozitif"),
    )

    bundle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # Paket fiyatının bu kaleme düşen payı — kârlılık ve muhasebe dağıtımı için.
    price_share: Mapped[float | None] = mapped_column(Numeric(14, 2))

    bundle: Mapped[Product] = relationship(back_populates="bundle_items", foreign_keys=[bundle_id])
    product: Mapped[Product] = relationship(foreign_keys=[product_id])


@event.listens_for(Product, "before_insert")
@event.listens_for(Product, "before_update")
def _urun_anahtari(_mapper, _connection, target: Product) -> None:
    target.name_key = tr_normkey(target.name)
