"""Personel özlük dosyası (2026-11-20, kullanıcı isteği).

İK her personele türüne göre belge yükler (kimlik, adli sicil, SRC, ehliyet,
İSG...); tür listesini İK yönetir (yeni tür ekler, adını değiştirir,
kaldırır). Erişim (kullanıcı kararı):

- İK (`ik_belge.yonet`): hepsini yönetir.
- Personelin kendisi: kendi belgelerini görür, silemez.
- Saha şefi / koordinatör: yalnız **iş bazlı** — kapsamındaki bir servis
  işine atanmış personelin, türü "işte paylaşılabilir" işaretli belgeleri
  (ör. müşteri sahaya girişte SRC/İSG ister). Her açılış denetime yazılır.

Personelin kendi yüklemesi (2026-11-23 sahip kararı): kişi kendi dosyasına
belge yükler; belge `ONAY_BEKLIYOR` durumunda saklanır ve İK onaylayana dek o
türün geçerli belgesi SAYILMAZ (işte paylaşılmaz). İK onaylar ya da gerekçeyle
reddeder; reddedilen belge gerekçesiyle kişiye görünür kalır, kişi yeniden
yükleyebilir. İK'nın kendi yüklediği belge doğrudan `ONAYLANDI`dır.

Kişi = `users` (ayrı personel tablosu yok, E13 K-01). Dosyalar
`services/storage.py` deposunda; `storage_path` sütunu sayesinde gece dosya
temizliği bu dosyaları kullanımda sayar.
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
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, SoftDeleteMixin, TimestampMixin, VersionedMixin

# Tohum (migration): görseldeki klasörler; işte paylaşılabilirler sahaya giriş
# belgeleri. İK sonradan değiştirebilir.
VARSAYILAN_OZLUK_TURLERI: tuple[tuple[str, bool], ...] = (
    ("Adli sicil kaydı", False),
    ("Askerlik Belgesi", False),
    ("Belirsiz Süreli İş Sözleşmesi", False),
    ("Eğitim Belgeleri", True),
    ("Ehliyet", True),
    ("Görev Tanımı", False),
    ("İkametgah", False),
    ("İSG", True),
    ("Kimlik", False),
    ("Nüfus Kayıt Örneği", False),
    ("Personel Bilgi Formu", False),
    ("SGK Giriş Bildirgesi", False),
    ("SRC Belgesi", True),
)


# Belge durumu. Yalnız ONAYLANDI geçerli belgedir (işte paylaşılır, klasörde
# sayılır); diğer ikisi yalnız kişiye ve İK'ya görünür.
OZLUK_DURUMLARI = ("ONAY_BEKLIYOR", "ONAYLANDI", "REDDEDILDI")
_DURUM_KISITI = "durum IN (" + ", ".join(f"'{d}'" for d in OZLUK_DURUMLARI) + ")"


class OzlukBelgeTuru(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "ozluk_belge_turleri"
    __table_args__ = (
        Index("uq_ozluk_tur_ad", text("lower(ad)"), unique=True, postgresql_where=text("aktif")),
    )

    ad: Mapped[str] = mapped_column(String(80))
    sira: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    # Saha şefi/koordinatör, işe atanmış personelin bu türdeki belgesini iş
    # üzerinden görebilir mi.
    is_paylasimi: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)


class OzlukBelgesi(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    __tablename__ = "ozluk_belgeleri"
    __table_args__ = (
        Index("ix_ozluk_belge_kisi", "user_id", "tur_id"),
        CheckConstraint(_DURUM_KISITI, name="ck_ozluk_belge_durum"),
        CheckConstraint(
            "durum <> 'REDDEDILDI' OR red_gerekcesi IS NOT NULL", name="ck_ozluk_belge_red"
        ),
        # İK'nın "onay bekleyen" listesi ve uyarı sayısı.
        Index(
            "ix_ozluk_belge_bekleyen",
            "user_id",
            postgresql_where=text("durum = 'ONAY_BEKLIYOR' AND NOT is_deleted"),
        ),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    tur_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ozluk_belge_turleri.id"))
    dosya_adi: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(400))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    # Süreli belgeler (SRC, ehliyet, İSG eğitimi) için; boş = süresiz.
    gecerlilik_bitis: Mapped[date | None] = mapped_column(Date)
    aciklama: Mapped[str | None] = mapped_column(Text)
    durum: Mapped[str] = mapped_column(
        String(20), server_default=text("'ONAYLANDI'"), default="ONAYLANDI"
    )
    # İK kararı (onay/red); İK'nın kendi yüklemesinde boş kalır.
    karar_veren_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    karar_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    red_gerekcesi: Mapped[str | None] = mapped_column(String(500))
