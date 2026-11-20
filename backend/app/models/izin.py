"""Personel izin talebi ve onay basamakları (KARARLAR 2026-11-20 §7).

Onay zinciri org şemasından (`users.yonetici_id`) kurulur: birim şefi →
teknik müdür → GMY. Sırası gelen basamak 24 saat (`izin_onay_sure_saat`)
içinde karar vermezse SURE_ASIMI olur ve talep bir sonraki yöneticiye geçer.
E-postadaki düğme tek kullanımlık `token` ile karar sayfasını açar.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin

IZIN_TURLERI = ("YILLIK", "MAZERET", "UCRETSIZ", "RAPOR", "DIGER")
IZIN_TUR_ADLARI = {
    "YILLIK": "Yıllık izin",
    "MAZERET": "Mazeret izni",
    "UCRETSIZ": "Ücretsiz izin",
    "RAPOR": "Raporlu",
    "DIGER": "Diğer",
}
IZIN_DURUMLARI = ("BEKLIYOR", "ONAYLANDI", "REDDEDILDI", "IPTAL")
ONAY_DURUMLARI = ("SIRADA", "BEKLIYOR", "ONAYLANDI", "REDDEDILDI", "SURE_ASIMI", "IPTAL")


def _in(kolon: str, degerler: tuple[str, ...]) -> str:
    return f"{kolon} IN ({', '.join(repr(d) for d in degerler)})"


class IzinTalebi(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "izin_talepleri"
    __table_args__ = (
        CheckConstraint(_in("tur", IZIN_TURLERI), name="ck_izin_tur"),
        CheckConstraint(_in("durum", IZIN_DURUMLARI), name="ck_izin_durum"),
        CheckConstraint("bitis >= baslangic", name="ck_izin_tarih"),
        CheckConstraint("vekil_id <> personel_id", name="ck_izin_vekil_kendisi"),
        Index("ix_izin_personel", "personel_id", "baslangic"),
    )

    personel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    tur: Mapped[str] = mapped_column(String(10))
    baslangic: Mapped[date] = mapped_column(Date)
    bitis: Mapped[date] = mapped_column(Date)
    gun_sayisi: Mapped[int] = mapped_column(Integer)
    vekil_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    izin_ili: Mapped[str] = mapped_column(String(60))
    iletisim_tel: Mapped[str] = mapped_column(String(30))
    aciklama: Mapped[str | None] = mapped_column(Text)
    durum: Mapped[str] = mapped_column(
        String(12), server_default=text("'BEKLIYOR'"), default="BEKLIYOR"
    )
    sonuc_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    onaylar: Mapped[list["IzinOnayi"]] = relationship(
        lazy="selectin", order_by="IzinOnayi.sira", cascade="all, delete-orphan"
    )


class IzinOnayi(Base, PkMixin, TimestampMixin):
    __tablename__ = "izin_onaylari"
    __table_args__ = (
        CheckConstraint(_in("durum", ONAY_DURUMLARI), name="ck_izinonay_durum"),
        UniqueConstraint("talep_id", "sira", name="uq_izinonay_sira"),
        Index("ix_izinonay_bekleyen", "onaylayici_id", "durum"),
    )

    talep_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("izin_talepleri.id", ondelete="CASCADE")
    )
    sira: Mapped[int] = mapped_column(Integer)
    onaylayici_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    durum: Mapped[str] = mapped_column(String(12), server_default=text("'SIRADA'"), default="SIRADA")
    # Basamağın sırası geldiği an (24 saat buradan sayılır).
    aktif_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    karar_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aciklama: Mapped[str | None] = mapped_column(String(500))
    # E-posta düğmesinin tek kullanımlık anahtarı; karar verilince silinir.
    token: Mapped[str | None] = mapped_column(String(64), unique=True)
