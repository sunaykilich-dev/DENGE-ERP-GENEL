"""İş emri ve cihaz–araç ömür boyu geçmişi.

**İŞ EMRİ = ZİYARET.** Brief iş emrini cihaz başına varsayıyordu; gerçek veri
bunu çürütüyor: araçların %96,8'inde birden fazla cihaz var ve 771 ziyaretin
683'ünde aynı araca aynı gün 3-4 cihaz takılıyor (tipik set: araç kamerası +
ek kamera + araç takip). Cihaz başına iş emri açmak araç bilgisini (plaka,
şase, ruhsat, km) üç kez girdirirdi — bugünkü Excel'in acısı aynen taşınırdı.

Bu yüzden: bir iş emri = araç + tarih + montaj noktası; içinde n adet
**cihaz kalemi**; hak ediş satırı KALEM başına, artı ziyaret başına bir
yol (km) satırı.

Ödenebilirlik kalemde tutulur: işlerin %22,8'i ödenmiyor (kendi satışı,
müşteriden tahsil edildi). "Tamamlanan iş otomatik hak edişe girer"
varsayımı ay sonunda fazla ödemeye yol açardı.
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
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)

IS_EMRI_TIPLERI = (
    "MONTAJ",
    "SOKUM",
    "SOK_TAK",
    "DEGISIM",  # brief'te yoktu; Esenyurt verisinde 257 satır
    "ARIZA",
    "KESIF",
    "BAKIM",
)

IS_EMRI_DURUMLARI = ("ACIK", "ATANDI", "YOLDA", "BASLADI", "TAMAMLANDI", "ONAYLANDI", "IPTAL")

KALEM_EYLEMLERI = ("TAKILDI", "SOKULDU", "DEGISTIRILDI", "KONTROL")

# Ödenmeme nedenleri — kaynak veride üç kategori, 306 kayıt.
ODENMEME_NEDENLERI = (
    "KENDI_SATISI",  # müşteri/bayi kendi aracına kendi montajını yaptı
    "MUSTERIDEN_TAHSIL",  # ücret doğrudan müşteriden alındı
    "GARANTI_KAPSAMI",
    "HATALI_MONTAJ",
    "DIGER",
)

ATAMA_TIPLERI = ("IC_TEKNISYEN", "MONTAJ_NOKTASI")

_ARALIK = literal_column("tstzrange(valid_from, valid_to, '[)')")


class WorkOrder(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint("wo_no", name="uq_wo_no"),
        UniqueConstraint("source_system", "source_ref", name="uq_wo_kaynak"),
        CheckConstraint(
            "type IN ('MONTAJ','SOKUM','SOK_TAK','DEGISIM','ARIZA','KESIF','BAKIM')",
            name="ck_wo_tip",
        ),
        CheckConstraint(
            "status IN ('ACIK','ATANDI','YOLDA','BASLADI','TAMAMLANDI','ONAYLANDI','IPTAL')",
            name="ck_wo_durum",
        ),
        CheckConstraint("settlement_period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_wo_donem_bicimi"),
        Index("ix_wo_donem", "settlement_period", "assigned_id"),
        Index("ix_wo_arac", "vehicle_id", "completed_at"),
        Index("ix_wo_durum", "status"),
    )

    wo_no: Mapped[str] = mapped_column(String(24))
    type: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12), server_default=text("'ACIK'"))

    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    # Km araca değil İŞE aittir: aynı araç farklı tarihlerde farklı km'dedir.
    odometer_km: Mapped[int | None] = mapped_column(Integer)

    assigned_type: Mapped[str | None] = mapped_column(String(20))
    assigned_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )

    # HAK EDİŞ DÖNEMİ ≠ İŞ TARİHİ. Kaynak veride 17 kayıtta ayrışıyor: iş bir
    # ay yapılıp sonraki ayın hak edişinde ödenmiş. İkisini aynılaştırmak o
    # kayıtların parasını yanlış aya taşır.
    settlement_period: Mapped[str] = mapped_column(String(7))

    # Yol/mobil km ücreti — ziyaret başına tek satır (hak edişin ~%8,6'sı).
    travel_km: Mapped[float | None] = mapped_column(Numeric(10, 2))
    travel_unit_price: Mapped[float | None] = mapped_column(Numeric(10, 2))

    notes: Mapped[str | None] = mapped_column(Text)
    # Blokaj (röle ile marş kesme) burada: ürün değil montaj özelliği.
    # İşlerin %21,1'i blokajlı ve fiyatı farklı.
    form_data: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    items: Mapped[list["WorkOrderItem"]] = relationship(
        back_populates="work_order", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def blokajli(self) -> bool:
        return bool((self.form_data or {}).get("blokajli"))


class WorkOrderItem(Base, PkMixin, TimestampMixin, SourceMixin):
    """Ziyaretteki tek bir cihaz kalemi. Hak ediş satırı buradan üretilir."""

    __tablename__ = "work_order_items"
    __table_args__ = (
        CheckConstraint(
            "action IN ('TAKILDI','SOKULDU','DEGISTIRILDI','KONTROL')", name="ck_woi_eylem"
        ),
        CheckConstraint(
            "payability IN ('ODENECEK','ODENMEYECEK','KARAR_BEKLIYOR')",
            name="ck_woi_odenebilirlik",
        ),
        CheckConstraint(
            "payability <> 'ODENMEYECEK' OR non_payable_reason IS NOT NULL",
            name="ck_woi_odenmeme_nedeni_zorunlu",
        ),
        Index("ix_woi_wo", "work_order_id"),
        Index("ix_woi_device", "device_id"),
        # Göç kalem seviyesinde de tekrar çalıştırılabilir olmalı: ilk
        # koşuda cihaz kaydı henüz açılmamışsa device_id boş kalır ve
        # sonraki koşuda tamamlanır.
        UniqueConstraint("source_system", "source_ref", name="uq_woi_kaynak"),
    )

    work_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("work_orders.id", ondelete="CASCADE")
    )
    # Cihaz kaydı açılamamış olabilir (IMEI bulunamadı) — kalem yine de durur,
    # yoksa iş emri eksik görünürdü.
    device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="SET NULL")
    )
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="SET NULL")
    )
    sim_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sim_cards.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(14), server_default=text("'TAKILDI'"))
    device_role: Mapped[str | None] = mapped_column(String(20))
    channel_no: Mapped[int | None] = mapped_column(Integer)

    # Ödenebilirlik: tamamlanan iş OTOMATİK hak edişe girmez.
    payability: Mapped[str] = mapped_column(String(16), server_default=text("'KARAR_BEKLIYOR'"))
    non_payable_reason: Mapped[str | None] = mapped_column(String(24))

    # Tarife bağlayıcı değil: aynı nokta + aynı iş tipinde 250/350/400,
    # bir kayıtta 2.750 TL. Elle girilen tutar tarifeyi geçersiz kılar.
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_source: Mapped[str | None] = mapped_column(String(10))  # TARIFE | MANUEL | GOC

    notes: Mapped[str | None] = mapped_column(Text)

    work_order: Mapped[WorkOrder] = relationship(back_populates="items")


class DeviceVehicleAssignment(Base, PkMixin, TimestampMixin):
    """Cihaz–araç ömür boyu geçmişi (brief §4.5).

    Tek çakışma kısıtı CİHAZ üzerindedir: bir cihaz aynı anda tek araçta
    olabilir. TERSİ KISITLANMAZ — bir araçta aynı anda birden fazla cihaz
    normaldir ve gerçek veride kuraldır.
    """

    __tablename__ = "device_vehicle_assignments"
    __table_args__ = (
        # KISMİ: yalnız tarihli satırlar. `tstzrange(NULL, NULL)` "sonsuzdan
        # sonsuza" demektir ve tarihsiz tek bir satır cihazın bütün gerçek
        # geçmişiyle çakışırdı.
        ExcludeConstraint(
            ("device_id", "="),
            (_ARALIK, "&&"),
            name="ex_dva_cihaz_cakisma",
            using="gist",
            where=text("valid_from IS NOT NULL"),
        ),
        # "Bir cihaz aynı anda tek araçta" kuralı EXCLUDE kısmileşince ondan
        # çıktı; açık dönem tekilliği burada çivilenir.
        Index(
            "uq_dva_acik_donem",
            "device_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_dva_aralik"),
        # Başlangıcı bilinmeyen dönem KAPATILAMAZ: uzunluğu hakkında hiçbir
        # şey söylenemeyen bir aralık, garanti ve hak ediş hesabında sessizce
        # yanlış sonuç üretir.
        CheckConstraint("valid_from IS NOT NULL OR valid_to IS NULL", name="ck_dva_tarihsiz_acik"),
        Index("ix_dva_arac", "vehicle_id", "valid_from"),
        Index("ix_dva_musteri", "customer_id"),
    )

    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"))
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="CASCADE")
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    sim_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sim_cards.id", ondelete="SET NULL")
    )

    installed_by_type: Mapped[str | None] = mapped_column(String(20))
    installed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    install_work_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("work_orders.id", ondelete="SET NULL")
    )
    removal_work_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("work_orders.id", ondelete="SET NULL")
    )

    # NULL = "bu cihaz bu araçta, ama ne zamandan beri bilinmiyor". Kaynak
    # dosyalarda montaj anı yok; uydurulmuş bir tarih garanti başlangıcını ve
    # cihaz zaman çizelgesini sessizce yanlışlar.
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_reason: Mapped[str | None] = mapped_column(String(200))

    # Kaynakta söküm kayıtları tutarsız: 124 IMEI birden çok işte, 83'ü farklı
    # plakalarda ve aralarda tek bir söküm kaydı yok. Dönemler çıkarımla
    # kapatılır; bu bayrak arayüzde "tarih tahmini" rozetiyle görünür ki ekip
    # düzeltebilsin (brief §4.5 geriye dönük düzeltme kaydı).
    is_inferred: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corrected_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    recorded_at: Mapped[date | None] = mapped_column(Date)
