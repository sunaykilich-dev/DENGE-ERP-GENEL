"""Toplu fiyat güncelleme partisi (plan §5 D9b).

Yüzlerce aboneliğe aynı anda zam yapmak, tek tek düzenlemekle kıyaslanamaz
bir hata riski taşır. Bu yüzden akış üç adımdır: **önizle → onayla → bildir.**

Parti kaydı, uygulanan her ücret satırına `price_batch_id` ile bağlanır.
Bunun iki karşılığı var: "bu zam kimlere uygulandı" tek sorguyla çıkar ve
henüz yürürlüğe girmemiş bir parti bütünüyle geri alınabilir.

**Taahhütlü sözleşmeler otomatik hariç tutulur.** Taahhüt karşılığı verilen
%89 indirimi taahhüt süresi içinde bozmak, sözleşmeye aykırı olurdu; bu
kararın kullanıcıya bırakılacak bir yanı yok.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin

PARTI_DURUMLARI = ("TASLAK", "UYGULANDI", "GERI_ALINDI")

# YUZDE: mevcut ücret × (1 + oran/100); TUTAR: mevcut + tutar; SABIT: tutar.
ZAM_YONTEMLERI = ("YUZDE", "TUTAR", "SABIT")


class PriceBatch(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "price_batches"
    __table_args__ = (
        CheckConstraint("status IN ('TASLAK','UYGULANDI','GERI_ALINDI')", name="ck_parti_durum"),
        CheckConstraint("method IN ('YUZDE','TUTAR','SABIT')", name="ck_parti_yontem"),
        Index("ix_parti_durum", "status"),
    )

    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(12), server_default=text("'TASLAK'"))
    method: Mapped[str] = mapped_column(String(8))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    valid_from: Mapped[date] = mapped_column(Date)
    # Hangi kümeye uygulandığı — önizleme ile uygulamanın aynı kümeyi
    # seçtiğini garantilemek için saklanır.
    criteria: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # Yuvarlama: kuruşlu zam listesi okunaksız olur, ekip genelde tam TL ister.
    round_to: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default=text("0.01"))

    affected_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    excluded_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    mrr_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))

    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)
