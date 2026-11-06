"""İK "Bordro ve Belgeler": personele bordro ve imzalanacak belge gönderimi.

Kullanıcı isteği (2026-11-06): İK aylık bordroyu ve imzalanması gereken
form/talimat/taahhütnameleri personele gönderir; personel kendi ekranından
görür, onaylar ya da gerekçeli itiraz eder; İK kim gördü/onayladı/bekliyor
takip eder (Kolaysoft PEYK benzeri). Kararlar: KARARLAR_2026-10-28 §11.

**Kişi = `users`** (ayrı personel tablosu açılmaz, E13 K-01).

Tablolar:
- `ik_belge_sablonlari`: tekrar gönderilen form/talimat/taahhütname dosyası.
- `ik_gonderimler`: bir gönderim turu (ör. "2026-10 bordrosu", "İSG talimatı").
- `ik_belgeler`: kişi başına belge ve güncel durumu.
- `ik_belge_olaylari`: SADECE EKLEME olay zinciri (görüldü, onay, itiraz...).
  Her satır önceki satırın özetini taşır (`onceki_ozet` → `kayit_ozeti`);
  veritabanı tetikleyicisi UPDATE/DELETE'i reddeder (migration f8a000000001).
  Böylece imza kaydı sonradan değiştirilirse zincir kırılır ve görünür.

Dosyalar `services/storage.py` deposunda (içerik adresli, sha256). Belgenin
özeti dosyanın sha256'sıdır; imza bu özete atılır.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin

# BORDRO ayrı izinle (`bordro.yonet`) yönetilir; diğerleri `ik_belge.yonet`.
BELGE_TURLERI = ("BORDRO", "FORM", "TALIMAT", "TAAHHUTNAME", "KVKK", "DIGER")
SABLON_TURLERI = tuple(t for t in BELGE_TURLERI if t != "BORDRO")
BELGE_DURUMLARI = ("GONDERILDI", "GORULDU", "ONAYLANDI", "ITIRAZ", "GERI_ALINDI")
# Yanıt verilmiş ya da geri alınmış belge bir daha değişmez.
SON_DURUMLAR = ("ONAYLANDI", "ITIRAZ", "GERI_ALINDI")
OLAY_TURLERI = (
    "GONDERILDI",
    "GORULDU",
    "ONAYLANDI",
    "ITIRAZ",
    "HATIRLATMA",
    "GERI_ALINDI",
)
DOGRULAMA_YOLLARI = ("PAROLA", "TOTP")


def _in(sutun: str, degerler: tuple) -> str:
    return f"{sutun} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


class _DosyaAlanlari:
    dosya_adi: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(400))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))


class IkBelgeSablonu(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin, _DosyaAlanlari):
    __tablename__ = "ik_belge_sablonlari"
    __table_args__ = (CheckConstraint(_in("tur", SABLON_TURLERI), name="ck_ik_sablon_tur"),)

    ad: Mapped[str] = mapped_column(String(150))
    tur: Mapped[str] = mapped_column(String(15))
    aciklama: Mapped[str | None] = mapped_column(Text)
    aktif: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)


class IkGonderim(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "ik_gonderimler"
    __table_args__ = (
        CheckConstraint(_in("tur", BELGE_TURLERI), name="ck_ik_gonderim_tur"),
        CheckConstraint(
            "donem IS NULL OR donem ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_ik_gonderim_donem"
        ),
        # Bordronun dönemi zorunlu: takip ve "aynı ay iki kez" uyarısı buna bakar.
        CheckConstraint("tur <> 'BORDRO' OR donem IS NOT NULL", name="ck_ik_gonderim_bordro_donem"),
        Index("ix_ik_gonderim_tur_donem", "tur", "donem"),
    )

    tur: Mapped[str] = mapped_column(String(15))
    baslik: Mapped[str] = mapped_column(String(200))
    donem: Mapped[str | None] = mapped_column(String(7))
    aciklama: Mapped[str | None] = mapped_column(Text)
    son_tarih: Mapped[date | None] = mapped_column(Date)
    sablon_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ik_belge_sablonlari.id", ondelete="SET NULL")
    )


class IkBelge(Base, PkMixin, TimestampMixin, VersionedMixin, _DosyaAlanlari):
    __tablename__ = "ik_belgeler"
    __table_args__ = (
        CheckConstraint(_in("durum", BELGE_DURUMLARI), name="ck_ik_belge_durum"),
        CheckConstraint(
            "durum <> 'ITIRAZ' OR length(btrim(coalesce(itiraz_gerekcesi, ''))) >= 5",
            name="ck_ik_belge_itiraz_gerekce",
        ),
        # Bir gönderimde kişi başına tek belge (bordro: kişi başına bir PDF).
        UniqueConstraint("gonderim_id", "user_id", name="uq_ik_belge_kisi"),
        Index("ix_ik_belge_kisi_durum", "user_id", "durum"),
    )

    gonderim_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ik_gonderimler.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    durum: Mapped[str] = mapped_column(
        String(12), server_default=text("'GONDERILDI'"), default="GONDERILDI"
    )
    gonderildi_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    goruldu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    yanit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    itiraz_gerekcesi: Mapped[str | None] = mapped_column(Text)
    hatirlatma_sayisi: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    son_hatirlatma_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IkBelgeOlayi(Base, PkMixin):
    """Değiştirilemez olay kaydı (imza kanıtı). Yalnız ekleme."""

    __tablename__ = "ik_belge_olaylari"
    __table_args__ = (
        CheckConstraint(_in("olay", OLAY_TURLERI), name="ck_ik_olay_tur"),
        CheckConstraint(
            "dogrulama IS NULL OR " + _in("dogrulama", DOGRULAMA_YOLLARI),
            name="ck_ik_olay_dogrulama",
        ),
        Index("ix_ik_olay_belge", "belge_id", "id"),
    )

    belge_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ik_belgeler.id", ondelete="RESTRICT")
    )
    olay: Mapped[str] = mapped_column(String(12))
    # İşlemi yapan (personel ya da İK). Kişi silinmez; anonimleştirilir.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    dogrulama: Mapped[str | None] = mapped_column(String(10))
    belge_ozeti: Mapped[str] = mapped_column(String(64))
    aciklama: Mapped[str | None] = mapped_column(Text)
    onceki_ozet: Mapped[str | None] = mapped_column(String(64))
    kayit_ozeti: Mapped[str] = mapped_column(String(64), unique=True)
