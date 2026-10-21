"""Servis planlaması: ziyaret, plan satırı, ekip, servis aracı, müsaitlik (E02).

**Plan satırı silinmez, yenisiyle değişir.** Erteleme, ekip değişimi ve
yeniden planlama yeni bir `service_plans` satırı açar; eskisi
`is_active=false` + `cancelled_at` alır. "Bu iş kaç kez ertelendi, neden"
sorusu ancak böyle cevaplanır. Tek aktif plan şemada zorlanır
(`uq_svcplan_aktif`): eşzamanlı iki planlama isteğinde biri 409 alır.

**Ziyaret ayrı tablo** (`service_visits`): eski sistemde serbest metin
`RouteGroupNo` yüzünden ayrılmış işler habersiz taşınıyordu (E02 K-03).

**Adres/irtibat plana kopyalanmaz**: işin kendi `address_id/contact_id`
alanları tek kaynaktır (E02 kontrol 2.1); plana yalnız ziyarete özgü
`site_area/site_note` kalır. Telefon KVKK gereği hiç kopyalanmaz.

Ekip = `service_plan_members`; iş ataması (`service_order_assignments`)
ile senkronu `planlama.ekip_degisti` kancası sağlar (E02-D01).
"""

from datetime import date, datetime, time

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
    Time,
    UniqueConstraint,
    event,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
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
from app.models.vehicle import plaka_anahtari


def _in(sutun: str, degerler: tuple[str, ...], *, bos: bool = False) -> str:
    liste = ", ".join(f"'{d}'" for d in degerler)
    return f"{sutun} IS NULL OR {sutun} IN ({liste})" if bos else f"{sutun} IN ({liste})"


PLAN_DEGISIM_TURLERI = ("ILK_PLAN", "ERTELEME", "EKIP_DEGISIMI", "YENIDEN_PLAN")
# Erteleme / geri alma / yeniden planlama nedeni — iki kolon aynı sözlüğü kullanır.
PLAN_NEDENLERI = (
    "MUSTERI_TALEBI",
    "PERSONEL_YOK",
    "ARAC_YOK",
    "MALZEME_BEKLENIYOR",
    "HAVA_ERISIM",
    "ONCEKI_IS_UZADI",
    "DIGER",
)
PLAN_UYE_ROLLERI = ("SEF", "TEKNISYEN")
# Sağlık raporu ayrı tür değildir (E02 K-11, KVKK özel nitelikli veri).
MUSAITLIK_TURLERI = ("IZIN", "EGITIM", "OFIS", "DIGER")

# Plan süresi sınırı kod sabitidir, ayar değil (plan §1.9).
PLAN_SURE_ALT_DK = 15
PLAN_SURE_UST_DK = 1440


class ServiceVisit(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Ziyaret: aynı müşteri + lokasyon + günde birlikte gidilen işler.

    Numara `ZYR-YYYYAA-NNNNNN`, `service_visit_no_seq`'ten (plan §1.6);
    eski `TPL-…` değeri `source_ref` olur.
    """

    __tablename__ = "service_visits"
    __table_args__ = (
        UniqueConstraint("visit_no", name="uq_svcvisit_no"),
        UniqueConstraint("source_system", "source_ref", name="uq_svcvisit_kaynak"),
        CheckConstraint(birim_check("birim"), name="ck_svcvisit_birim"),
    )

    visit_no: Mapped[str] = mapped_column(String(24))
    birim: Mapped[str] = mapped_column(String(20))
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    address_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("addresses.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(String(1000))


class ServiceVehicle(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    """Servis araç havuzu (E02-17).

    Mobilite `vehicles` tablosu MÜŞTERİ araçlarıdır (takip cihazı takılan);
    servis ekibinin kullandığı araç orada değil. Araç mobilite filosunda da
    varsa `vehicle_id` salt referanstır — `vehicles`'a yazılmaz.
    `birim` NULL = ortak havuz.
    """

    __tablename__ = "service_vehicles"
    __table_args__ = (
        Index(
            "uq_svcarac_plaka",
            "plate_key",
            unique=True,
            postgresql_where=text("NOT is_deleted"),
        ),
        CheckConstraint(birim_check("birim", bos_olabilir=True), name="ck_svcarac_birim"),
    )

    plate: Mapped[str] = mapped_column(String(20))
    plate_key: Mapped[str] = mapped_column(String(20))
    birim: Mapped[str | None] = mapped_column(String(20))
    assigned_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)


class ServicePlan(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Plan satırı. Planlayan kişi `created_by`'dır (ayrı kolon yok).

    Tarihsiz plan yoktur (`plan_date` NOT NULL). Saat belirsizse
    `start_time` NULL; `starts_at/ends_at` Europe/Istanbul'dan hesaplanıp
    sorgu ve çakışma için tutulur.
    """

    __tablename__ = "service_plans"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_svcplan_kaynak"),
        Index(
            "uq_svcplan_aktif",
            "service_order_id",
            unique=True,
            postgresql_where=text("is_active AND NOT is_deleted"),
        ),
        Index("ix_svcplan_tarih", "plan_date", postgresql_where=text("is_active")),
        Index("ix_svcplan_ziyaret", "visit_id"),
        CheckConstraint(
            f"duration_min BETWEEN {PLAN_SURE_ALT_DK} AND {PLAN_SURE_UST_DK}",
            name="ck_svcplan_sure",
        ),
        CheckConstraint(
            "(start_time IS NULL) = (starts_at IS NULL) "
            "AND (ends_at IS NULL OR ends_at > starts_at)",
            name="ck_svcplan_saat",
        ),
        CheckConstraint(_in("change_type", PLAN_DEGISIM_TURLERI), name="ck_svcplan_degisim"),
        CheckConstraint(_in("change_reason", PLAN_NEDENLERI, bos=True), name="ck_svcplan_neden"),
        CheckConstraint(
            _in("cancel_reason", PLAN_NEDENLERI, bos=True), name="ck_svcplan_iptal_neden"
        ),
        # İlk plan ve salt ekip değişimi nedensizdir; erteleme/yeniden plan
        # nedensiz olamaz. Göç satırının nedeni bilinmiyorsa uydurulmaz.
        CheckConstraint(
            "change_type IN ('ILK_PLAN', 'EKIP_DEGISIMI') OR change_reason IS NOT NULL "
            "OR source_system IS NOT NULL",
            name="ck_svcplan_neden_zorunlu",
        ),
        CheckConstraint(
            "change_reason IS NULL OR change_reason <> 'DIGER' OR change_note IS NOT NULL",
            name="ck_svcplan_diger_not",
        ),
        CheckConstraint(
            "is_active OR cancelled_at IS NOT NULL OR is_deleted", name="ck_svcplan_pasif"
        ),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT"), index=True
    )
    visit_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_visits.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    plan_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    duration_min: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vehicle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_vehicles.id", ondelete="SET NULL")
    )
    # Yalnız göç: eşleşmeyen plaka uydurulmaz.
    legacy_vehicle_text: Mapped[str | None] = mapped_column(String(30))
    site_area: Mapped[str | None] = mapped_column(String(200))
    site_note: Mapped[str | None] = mapped_column(String(500))
    plan_note: Mapped[str | None] = mapped_column(String(1000))
    change_type: Mapped[str] = mapped_column(String(16))
    change_reason: Mapped[str | None] = mapped_column(String(24))
    change_note: Mapped[str | None] = mapped_column(String(500))
    # Gerekçeyle geçilen çakışma (servis.planla).
    conflict_override_note: Mapped[str | None] = mapped_column(String(500))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(24))
    cancel_note: Mapped[str | None] = mapped_column(String(500))


class ServicePlanMember(Base, PkMixin, TimestampMixin):
    """Plan ekibi. Satır değişmez: ekip değişince yeni plan satırı açılır.

    Şef varsayılan olarak sahaya GİTMEZ (sorumlu); yalnız `sahaya_gidiyor`
    ise çakışma kontrolüne girer (E02-10). Teknisyen her zaman sahadadır.
    """

    __tablename__ = "service_plan_members"
    __table_args__ = (
        UniqueConstraint("plan_id", "user_id", name="uq_svcplanuye"),
        Index("ix_svcplanuye_kullanici", "user_id"),
        CheckConstraint(_in("rol", PLAN_UYE_ROLLERI), name="ck_svcplanuye_rol"),
        CheckConstraint(
            "rol <> 'TEKNISYEN' OR sahaya_gidiyor", name="ck_svcplanuye_teknisyen_sahada"
        ),
    )

    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_plans.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    rol: Mapped[str] = mapped_column(String(10))
    sahaya_gidiyor: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class ServiceUnavailability(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin
):
    """Personel müsaitlik bloğu (izin, eğitim, ofis). Aynı kişide çakışmaz."""

    __tablename__ = "service_unavailability"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_svcmusait_aralik"),
        CheckConstraint(_in("tur", MUSAITLIK_TURLERI), name="ck_svcmusait_tur"),
        ExcludeConstraint(
            ("user_id", "="),
            (literal_column("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            name="ex_svcmusait_cakisma",
            using="gist",
            where=text("NOT is_deleted"),
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tur: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(String(300))


@event.listens_for(ServiceVehicle, "before_insert")
@event.listens_for(ServiceVehicle, "before_update")
def _servis_arac_anahtari(_mapper, _connection, target: ServiceVehicle) -> None:
    target.plate_key = plaka_anahtari(target.plate)
