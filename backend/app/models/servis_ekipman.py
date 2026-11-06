"""Kurulu ekipman kütüğü (E03): X-Ray, kapı dedektörü, telsiz ...

**Neden `devices` değil** (00 §5, plan §6.3): `devices` mobilite STOK yaşam
döngüsüdür (STOKTA→...→AKTIF), global `uq_devices_seri` ve stok değeri
raporu taşır. Müşteri malı kurulu ekipmanı oraya yazmak hem tekil indeksi
(üreticiler arası seri çakışır) hem stok raporlarını bozardı. Mobilite/Araç
Takip cihazı da kütükteyse `device_id` salt referanstır.

**Seri no METİN ve tekil DEĞİL:** baştaki sıfır, iç boşluk, `-./` korunur;
kaynakta 38 seri 96 satırda tekrarlanıyor (farklı müşteri, yeniden kurulum).
Mükerrer tespiti (tip + marka anahtarı + seri anahtarı) advisory lock ile
servis katmanında yapılır ve "farklı cihaz" gerekçesiyle geçilebilir
(`duplicate_ack_reason`).

"Serviste" durumu SAKLANMAZ: açık ARIZA servis işinden hesaplanır; saklansa
iş kapanınca güncellemeyi unutan her yol yanlış rozet bırakırdı.
"""

import re
from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)
from app.models.rbac import birim_check
from app.services import normalize as _normalize
from app.services.normalize import tr_normkey


def _in(sutun: str, degerler: tuple[str, ...], *, bos: bool = False) -> str:
    liste = ", ".join(f"'{d}'" for d in degerler)
    return f"{sutun} IS NULL OR {sutun} IN ({liste})" if bos else f"{sutun} IN ({liste})"


# Telsiz türleri Dalga 2 atölye kabulü için şimdiden açık (E05-D01): CHECK
# sonradan genişletilirse migration'ı elle drop+create yazmak gerekirdi.
EKIPMAN_TIPLERI = (
    "XRAY",
    "KAPI_DEDEKTORU",
    "EL_DEDEKTORU",
    "DIGER_GUVENLIK",
    "TELSIZ",
    "ROLE_TEKRARLAYICI",
    "TELSIZ_DIGER",
    "DIGER",
)
EKIPMAN_DURUMLARI = ("KURULU", "KURULUM_BEKLIYOR", "DEVRE_DISI", "HURDA", "BILINMIYOR")
GARANTI_KAYNAKLARI = ("BELGE", "HESAPLANDI", "BILINMIYOR")
# device_id yalnız mobilite stoğunda karşılığı olabilecek birimlerde (RMA
# köprüsü haberleşme atölyesi için de gerekli — E03 kontrol E03-02).
CIHAZ_BAGLANABILIR_BIRIMLER = ("MOBILITE", "ARAC_TAKIP", "HABERLESME")


def model_anahtari(model: str | None) -> str | None:
    """Model filtresi anahtarı: Türkçe katlama, boşluk ve `-` atılır.

    "SC 5030 A" ile "SC-5030 A" aynı modeldir (E03-10c).
    """
    if not model:
        return None
    return re.sub(r"[\s\-]+", "", tr_normkey(model)) or None


class ServiceEquipment(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    __tablename__ = "service_equipment"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_svceq_kaynak"),
        CheckConstraint(birim_check("birim"), name="ck_svceq_birim"),
        CheckConstraint(_in("equipment_type", EKIPMAN_TIPLERI), name="ck_svceq_tip"),
        CheckConstraint(_in("lifecycle_status", EKIPMAN_DURUMLARI), name="ck_svceq_durum"),
        CheckConstraint(
            _in("warranty_source", GARANTI_KAYNAKLARI, bos=True), name="ck_svceq_garanti_kaynagi"
        ),
        CheckConstraint(
            "warranty_end IS NULL OR warranty_start IS NULL OR warranty_end >= warranty_start",
            name="ck_svceq_garanti_aralik",
        ),
        CheckConstraint("merged_into_id <> id", name="ck_svceq_kendine_birlesemez"),
        CheckConstraint("merged_into_id IS NULL OR NOT is_active", name="ck_svceq_birlesen_pasif"),
        CheckConstraint(
            "device_id IS NULL OR " + _in("birim", CIHAZ_BAGLANABILIR_BIRIMLER),
            name="ck_svceq_cihaz_birim",
        ),
        # Bir mobilite cihazı kütükte tek ekipmana karşılık gelir.
        Index(
            "uq_svceq_cihaz",
            "device_id",
            unique=True,
            postgresql_where=text("device_id IS NOT NULL AND NOT is_deleted"),
        ),
        Index("ix_svceq_seri", "serial_key"),
        Index("ix_svceq_seri_trgm", text("serial_key gin_trgm_ops"), postgresql_using="gin"),
        Index("ix_svceq_tip_marka_model", "equipment_type", "brand_key", "model_key"),
        Index("ix_svceq_hesap", "account_id"),
        Index("ix_svceq_adres", "address_id"),
        Index("ix_svceq_birim_durum", "birim", "lifecycle_status"),
    )

    birim: Mapped[str] = mapped_column(String(20))
    equipment_type: Mapped[str] = mapped_column(String(30))
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="SET NULL")
    )
    brand: Mapped[str | None] = mapped_column(String(60))
    # tr_normkey(brand): "SMITHS" ile "Smiths" aynı marka (mükerrer anahtarı).
    brand_key: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    model_key: Mapped[str | None] = mapped_column(String(80))
    # Kaynaktaki ham ürün metni — değiştirilmez.
    product_raw: Mapped[str | None] = mapped_column(Text)
    serial_no: Mapped[str | None] = mapped_column(String(200))
    # normalize_seri(serial_no) — servis işi `seri_norm` ile AYNI fonksiyon.
    serial_key: Mapped[str | None] = mapped_column(String(200))

    account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    customer_name_raw: Mapped[str | None] = mapped_column(String(200))
    address_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("addresses.id", ondelete="SET NULL")
    )
    location_raw: Mapped[str | None] = mapped_column(Text)
    zone: Mapped[str | None] = mapped_column(String(120))
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id", ondelete="SET NULL")
    )
    # Kişisel veri: denetimde AYRI satır, is_personal_data=True (E03-03).
    contact_name_raw: Mapped[str | None] = mapped_column(String(120))

    delivery_date: Mapped[date | None] = mapped_column(Date)
    delivery_date_raw: Mapped[str | None] = mapped_column(String(100))
    install_date: Mapped[date | None] = mapped_column(Date)
    warranty_start: Mapped[date | None] = mapped_column(Date)
    warranty_end: Mapped[date | None] = mapped_column(Date)
    warranty_source: Mapped[str | None] = mapped_column(String(12))

    lifecycle_status: Mapped[str] = mapped_column(
        String(20), server_default=text("'BILINMIYOR'"), default="BILINMIYOR"
    )
    # Kayıt geçerli mi (mükerrer/hatalı kayıt pasifi) — fiziksel durumdan AYRI.
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    merged_into_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_equipment.id", ondelete="SET NULL")
    )
    duplicate_ack_reason: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    # Kayıtlı frekans (Haberleşme röle/telsiz; KARARLAR §12). Anahtarlar
    # `cihaz_bilgisi.FREKANS_ALANLARI`; arıza işine buradan kopyalanır.
    frekans: Mapped[dict | None] = mapped_column(JSONB)


@event.listens_for(ServiceEquipment, "before_insert")
@event.listens_for(ServiceEquipment, "before_update")
def _ekipman_anahtarlari(_mapper, _connection, target: ServiceEquipment) -> None:
    target.brand_key = tr_normkey(target.brand) or None if target.brand else None
    target.model_key = model_anahtari(target.model)
    target.serial_key = (
        _normalize.normalize_seri(target.serial_no) or None if target.serial_no else None
    )
