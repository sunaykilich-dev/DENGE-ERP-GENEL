"""Araçlar.

Brief'in `vehicles` tablosunda `ruhsat_no` ve `km` yoktu. Gerçek veride ikisi
de var ve mevcut uygulamada ZORUNLU alan: Esenyurt dosyasının 2.305/2.312
satırında km dolu. Ama km araca değil İŞE aittir — aynı araç farklı tarihlerde
farklı km'dedir. Bu yüzden `odometer_km` iş emrinde (D3), ruhsat no burada.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
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
from app.services.normalize import tr_normkey

# Takip platformundaki `vehicles.type` CHECK'i ile aynı değerler —
# iki sistem farklı liste kullanırsa araç eşleştirmesi kirlenir.
ARAC_TIPLERI = (
    "BINEK",
    "KAMYONET",
    "MINIBUS",
    "KAMYON",
    "OTOBUS",
    "IS_MAKINESI",
    "MOTOSIKLET",
    "DIGER",
)


class Vehicle(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    __tablename__ = "vehicles"
    __table_args__ = (
        # Plaka değişebiliyor (kaynak sütunun adı bile "Mevcut Plaka"), bu yüzden
        # plaka tek başına doğal anahtar DEĞİL — ama aynı anda iki araç aynı
        # plakayı taşıyamaz.
        UniqueConstraint("plate", name="uq_vehicles_plaka"),
        # Şase no 17 karakterse tekil olmalı; kaynak veride 4-15 karakterlik
        # dolgu değerler var, onlar kısıtın dışında kalsın.
        Index(
            "uq_vehicles_sase",
            "chassis_no",
            unique=True,
            postgresql_where=text("length(chassis_no) = 17"),
        ),
        CheckConstraint(
            "vehicle_type IS NULL OR vehicle_type IN "
            "('BINEK','KAMYONET','MINIBUS','KAMYON','OTOBUS','IS_MAKINESI','MOTOSIKLET','DIGER')",
            name="ck_vehicles_tip",
        ),
    )

    plate: Mapped[str] = mapped_column(String(30))
    # Filoda standart TR plakası OLMAYAN varlıklar var: iş makineleri
    # (KAZICI YÜKLEYİCİ-1) ve demirbaş numarasıyla anılan araçlar — 25
    # tekil değer, 78 montaj satırı. Bunları reddetmek araçları tamamen
    # kaybetmek olurdu; ham değer korunur ve doğrulanmamış işaretlenir.
    is_plate_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    plate_key: Mapped[str] = mapped_column(String(30), index=True)  # normalize edilmiş
    chassis_no: Mapped[str | None] = mapped_column(String(24))
    # Ruhsat no: kamu/belediye işlerinde evrak eşleştirmesi için kullanılıyor.
    registration_no: Mapped[str | None] = mapped_column(String(24))
    brand: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    model_year: Mapped[int | None] = mapped_column(Integer)
    vehicle_type: Mapped[str | None] = mapped_column(String(20))

    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    # Okul servisi mevzuatı: 112 onaylı cihaz kontrolü buna bakar (brief §4.6).
    is_school_service: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # Takip platformundaki karşılığı — ERP kanonik kaynak, platform beslenir.
    platform_vehicle_id: Mapped[str | None] = mapped_column(String(64))

    notes: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    customer: Mapped["object | None"] = relationship("Account", lazy="raise")


def plaka_anahtari(plaka: str) -> str:
    """Plakanın arama anahtarı — `normalize_plate` ile AYNI ŞEY DEĞİL.

    `normalize_plate` biçim doğrular ve BÜYÜK harf döner; anahtar ise
    `tr_normkey` üzerinden küçük harflidir. Arayan tarafın bu farkı tahmin
    etmesi, "kayıtlı aracı bulamama" hatasının kaynağıydı: aynı kuralı
    burada tutup dışarıya açıyoruz.
    """
    return tr_normkey(plaka).replace(" ", "")


@event.listens_for(Vehicle, "before_insert")
@event.listens_for(Vehicle, "before_update")
def _arac_anahtari(_mapper, _connection, target: Vehicle) -> None:
    target.plate_key = plaka_anahtari(target.plate)
