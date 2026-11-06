"""İçe aktarma partisi.

Yüklenen dosyanın DOĞRULANMIŞ hali `staged_rows` içinde durur. Neden
saklanıyor: önizleme ile onay arasında dakikalar geçebilir ve kullanıcı
onayladığında tam olarak GÖRDÜĞÜ satırların yazılması gerekir. Dosyayı
onay anında yeniden ayrıştırmak, arada değişmiş bir kayıt yüzünden
başka bir sonuç üretebilirdi.

Parti go-live'dan sonra da kalır: "bu cihazlar sisteme ne zaman, hangi
dosyayla, kim tarafından girdi" sorusunun tek cevabı budur.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin

PARTI_DURUMLARI = ("HAZIR", "AKTARILDI", "IPTAL")


class ImportBatch(Base, PkMixin, TimestampMixin, ActorMixin):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("status IN ('HAZIR','AKTARILDI','IPTAL')", name="ck_import_durum"),
        Index("ix_import_profil", "profile", "status"),
    )

    profile: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(260))
    status: Mapped[str] = mapped_column(String(12), server_default=text("'HAZIR'"))

    total_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Dosyada dolu ama okunamayan satır (tanınan sütuna düşmeyen, başlığın
    # üstünde kalan). Sıfırdan büyükse kullanıcıya gösterilir: sessizce atılan
    # satır, hata vermeyen ve kimsenin fark etmediği veri kaybıdır.
    dropped_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    valid_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    conflict_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Uygulama sonrası gerçekleşen sayılar.
    created_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    updated_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    skipped_rows: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    staged_rows: Mapped[list | None] = mapped_column(JSONB)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
