"""SIM / hat yönetimi ve tarihli geçmişleri.

Bu dosya ERP'nin veritabanı seviyesindeki en önemli kısıtlarını taşıyor:
`EXCLUDE USING gist (... WITH =, tstzrange(...) WITH &&)`. Bu kısıt olmadan
"bir hat aynı anda iki cihazda" gibi imkânsız durumlar sessizce veriye girer
ve "X tarihinde bu hat hangi cihazdaydı" sorusu cevapsız kalır.

Aralık `[)` (yarı açık) seçildi: aynı gün sök-tak yapılan gerçek kayıtlar
`[]` ile kısıta takılırdı — göç verisinde bu durum var.

Hat maliyeti TEK SAYI DEĞİL. Türk Telekom tarifesi üç kalemden oluşuyor:
temel tarife + veri paketi + APN, her biri ayrı indirimle (örn. 1,89 + 12,54
+ 0 = 14,43 TL). İndirim %89 ve TAAHHÜDE BAĞLI: taahhüt düşerse aynı hat
131,16 TL'ye çıkar. Bu yüzden kalemler ayrı tutulur ve taahhüt bitişi izlenir.
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, ExcludeConstraint
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
from app.models.rbac import sirket_check

HAT_DURUMLARI = ("STOKTA", "TEST", "AKTIF", "ASKIDA", "IPTAL")
OPERATORLER = ("TURK_TELEKOM", "TURKCELL", "VODAFONE", "DIGER")

# Tarihli tabloların ortak çakışma kısıtı — yarı açık aralık.
_ARALIK = literal_column("tstzrange(valid_from, valid_to, '[)')")


class SimCard(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    __tablename__ = "sim_cards"
    __table_args__ = (
        UniqueConstraint("iccid", name="uq_sim_iccid"),
        Index("uq_sim_msisdn", "msisdn", unique=True, postgresql_where=text("msisdn IS NOT NULL")),
        UniqueConstraint("source_system", "source_ref", name="uq_sim_kaynak"),
        CheckConstraint(
            "status IN ('STOKTA','TEST','AKTIF','ASKIDA','IPTAL')", name="ck_sim_durum"
        ),
        Index("ix_sim_durum", "status"),
        Index("ix_sim_taahhut", "commitment_end_date"),
        # Şirket bazlı hat (fcl000000001).
        CheckConstraint(sirket_check("sirket"), name="ck_sim_sirket"),
        Index("ix_sim_sirket", "sirket"),
    )

    iccid: Mapped[str] = mapped_column(String(20))
    msisdn: Mapped[str | None] = mapped_column(String(16))  # E.164
    imsi: Mapped[str | None] = mapped_column(String(20))
    operator: Mapped[str] = mapped_column(String(20), server_default=text("'TURK_TELEKOM'"))
    apn: Mapped[str | None] = mapped_column(String(60))

    enabled_network_tech: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)))
    last_seen_network_tech: Mapped[str | None] = mapped_column(String(10))

    status: Mapped[str] = mapped_column(String(10), server_default=text("'STOKTA'"))

    # --- Paket ve kullanım ---
    plan_name: Mapped[str | None] = mapped_column(String(80))
    data_allowance_mb: Mapped[int | None] = mapped_column(Integer)
    data_used_mb: Mapped[int | None] = mapped_column(Integer)
    usage_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Maliyet kalemleri (tek sayı değil) ---
    tariff_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    package_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    apn_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    monthly_charge: Mapped[float | None] = mapped_column(Numeric(10, 2))  # müşteriye yansıyan

    # --- Taahhüt ---
    commitment_months: Mapped[int | None] = mapped_column(Integer)
    commitment_end_date: Mapped[date | None] = mapped_column(Date)
    discount_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))

    activated_at: Mapped[date | None] = mapped_column(Date)
    deactivated_at: Mapped[date | None] = mapped_column(Date)

    # Alan bazında kaynak: {"data_used_mb": "API", "plan_name": "MANUEL"}.
    # Brief tek bir `data_source` alanı öngörüyordu; gerçekte ICCID API'den,
    # paket elle gelebiliyor. Operatör bir alanı boş döndüğünde elle girilen
    # değerin ÜZERİNE YAZILMAMASI bu haritayla sağlanır (brief §4.4).
    field_sources: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    # Şablon "Not" sütununu belgeliyor ve içe aktarma onu `SimCard(**alanlar)`
    # ile geçiriyordu; kolon olmadığı için dolu Not sütunu olan her dosya
    # uygula adımında 500 veriyordu (güncelleme yolu ise sessizce yutuyordu).
    notes: Mapped[str | None] = mapped_column(Text)

    # Hattın ait olduğu şirket (fcl000000001). Her hat TEK şirkete aittir;
    # API yeni hatta etkin şirketi yazar. Python varsayılanı DENGE MOBİLİTE:
    # göç/içe aktarma yükleyicileri yalnız mobilite verisi taşır ve damgasız
    # (NULL) hat hiçbir şirkette görünmezdi.
    sirket: Mapped[str | None] = mapped_column(String(20), default="MOBILITE")

    @property
    def aylik_maliyet(self) -> float:
        return float((self.tariff_cost or 0) + (self.package_cost or 0) + (self.apn_cost or 0))


class SimPlanHistory(Base, PkMixin):
    """Paket değişiklik geçmişi — hangi tarihte hangi paket, kaç GB, hangi
    teknoloji açıktı (brief §4.4)."""

    __tablename__ = "sim_plan_history"
    __table_args__ = (
        ExcludeConstraint(
            ("sim_id", "="),
            (_ARALIK, "&&"),
            name="ex_sim_plan_cakisma",
            using="gist",
        ),
        Index(
            "uq_sim_plan_acik",
            "sim_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_sim_plan_aralik"),
    )

    sim_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sim_cards.id", ondelete="CASCADE"), index=True
    )
    plan_name: Mapped[str | None] = mapped_column(String(80))
    data_allowance_mb: Mapped[int | None] = mapped_column(Integer)
    enabled_network_tech: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)))
    monthly_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SimDeviceHistory(Base, PkMixin):
    """Hat ↔ cihaz eşleşme geçmişi.

    İKİ çakışma kısıtı var ve ikisi de gerekli:
    - bir hat aynı anda tek cihazda,
    - bir cihazda aynı anda tek hat.
    """

    __tablename__ = "sim_device_history"
    __table_args__ = (
        # Çakışma kısıtları YALNIZ TARİHLİ satırlara uygulanır. Başlangıcı
        # bilinmeyen satır bir zaman aralığı iddia etmez; `tstzrange(NULL, NULL)`
        # "sonsuzdan sonsuza" demek olurdu ve aynı cihazın gerçek geçmişiyle
        # çakışırdı. Tekillik onlarda aşağıdaki kısmi indekslerle korunur.
        ExcludeConstraint(
            ("sim_id", "="),
            (_ARALIK, "&&"),
            name="ex_sim_cihaz_hat_cakisma",
            using="gist",
            where=text("valid_from IS NOT NULL"),
        ),
        ExcludeConstraint(
            ("device_id", "="),
            (_ARALIK, "&&"),
            name="ex_sim_cihaz_cihaz_cakisma",
            using="gist",
            where=text("valid_from IS NOT NULL"),
        ),
        # "Bir cihazda aynı anda tek hat" kuralı tarihsiz satırlar için de
        # geçerli olmalı; EXCLUDE artık onları görmediği için açık dönem
        # tekilliği ayrıca çivilenir.
        Index(
            "uq_sdh_acik_cihaz", "device_id", unique=True, postgresql_where=text("valid_to IS NULL")
        ),
        Index("uq_sdh_acik_hat", "sim_id", unique=True, postgresql_where=text("valid_to IS NULL")),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_sim_cihaz_aralik"),
        # Başlangıcı bilinmeyen bir dönem KAPATILAMAZ: uzunluğu hakkında
        # hiçbir şey söylenemeyen bir aralık, hak ediş ve maliyet
        # hesaplarında sessizce yanlış sonuç üretir.
        CheckConstraint(
            "valid_from IS NOT NULL OR valid_to IS NULL", name="ck_sim_cihaz_tarihsiz_acik"
        ),
        Index("ix_sdh_sim", "sim_id", "valid_from"),
        Index("ix_sdh_device", "device_id", "valid_from"),
    )

    sim_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sim_cards.id", ondelete="CASCADE"))
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"))
    # NULL = eşleşme BİLİNİYOR ama ne zaman başladığı bilinmiyor. Kaynak
    # dosyada cihazın ICCID'si var, aktivasyon anı yok; uydurulmuş bir tarih
    # yazmak (ör. dosyanın dışa aktarım anı) garanti başlangıcını ve hat
    # maliyeti dönemlerini sessizce yanlışlardı — bu bir kez yapıldı ve
    # kullanıcı kararıyla geri alındı.
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Göçte çıkarımla kapatılan dönemler işaretlenir; arayüzde "tarih tahmini"
    # rozetiyle görünür ki ekip düzeltebilsin.
    is_inferred: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
