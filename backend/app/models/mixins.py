"""Tüm ana tabloların paylaştığı kolonlar ve davranışlar.

Plan §3.3'teki dört kesişen karardan ikisi burada uygulanır:
- İyimser kilitleme (`VersionedMixin`) — 6-15 kişi eşzamanlı çalışacak.
- Denetim alanları + yumuşak silme — brief §5 ortak alanlar.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class TimestampMixin:
    """created_at / updated_at — veritabanı tarafında damgalanır."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class ActorMixin:
    """created_by / updated_by — brief §5 ortak alanlar.

    NULL = sistem/worker tarafından oluşturuldu (göç, gece işleri).
    """

    @declared_attr
    def created_by(cls) -> Mapped[int | None]:  # noqa: N805
        return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    @declared_attr
    def updated_by(cls) -> Mapped[int | None]:  # noqa: N805
        return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SoftDeleteMixin:
    """Yumuşak silme. Kim sildiği de tutulur — mevcut hak ediş uygulamasında
    `silen` alanı vardı, brief'in düz `is_deleted`'ı bu bilgiyi kaybediyordu.
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    @declared_attr
    def deleted_at(cls) -> Mapped[datetime | None]:  # noqa: N805
        return mapped_column(DateTime(timezone=True))

    @declared_attr
    def deleted_by(cls) -> Mapped[int | None]:  # noqa: N805
        return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class VersionedMixin:
    """İyimser kilitleme.

    SQLAlchemy her UPDATE'e `WHERE version = :eski` ekler ve etkilenen satır
    yoksa StaleDataError atar. Bunsuz, iki kişi aynı kaydı açtığında son
    kaydedenin dışındaki değişiklik SESSİZCE kaybolur.

    API katmanı StaleDataError'ı 409 Conflict'e çevirir (bkz. app/main.py).
    """

    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"), default=1
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict:  # noqa: N805
        return {"version_id_col": cls.__table__.c.version}


class PkMixin:
    """BIGINT kimlik. UUID yerine bigint: tablolar arası JOIN yoğun, indeksler
    küçük kalsın. Dışarıya açılan kaynaklar (teklif linki) ayrıca jeton taşır.
    """

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)


class SourceMixin:
    """Veri göçü kimliği.

    Göç betiği tekrar çalıştırılabilir olmalı (plan §6): canlı uygulama
    geliştirme boyunca çalışmaya devam edecek, delta defalarca aktarılacak ve
    kesin geçiş yarıda kalırsa baştan koşulabilmeli. Her göç edilen satır
    kaynağını taşır; tekrar koşuda bu çift üzerinden UPSERT yapılır.

    `source_system` NULL = kayıt arayüzden elle girildi.

    Kısıtı her tablo kendi `__table_args__` içinde yazar:
    `UniqueConstraint("source_system", "source_ref")`. Mixin'e koymak
    tabloların kendi kısıtlarıyla çakışıyordu.
    """

    source_system: Mapped[str | None] = mapped_column(String(20))
    source_ref: Mapped[str | None] = mapped_column(String(64))
