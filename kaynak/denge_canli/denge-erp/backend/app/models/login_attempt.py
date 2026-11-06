from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LoginAttempt(Base):
    """Kullanıcı adı bazında başarısız giriş sayacı — brute-force kilidi için.

    Kilit SÜRELİ DEĞİL: eşik aşılınca hesap kapanır ve ancak bir yönetici
    açabilir (kullanıcı kararı, 23 Eyl 2026). Süreli kilitte saldırgan 15
    dakika bekleyip kaldığı yerden devam edebiliyordu.

    Bunun bilinen bedeli: kullanıcı adını bilen biri o hesabı kasten
    kilitleyebilir. Karşılığı IP seviyesinde fail2ban ve yöneticinin tek
    tıkla açabilmesi; yönetici de kilitlenirse `python -m app.yonetim
    kilit-ac <kullanıcı>` sunucudan açar.
    """

    __tablename__ = "login_attempts"

    username: Mapped[str] = mapped_column(String(50), primary_key=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    # NULL = kilitli değil. Dolu = bu anda kilitlendi, yönetici açana dek kapalı.
    kilitlendi_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
