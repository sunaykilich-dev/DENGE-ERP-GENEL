"""Ana Panel düzeni (KARARLAR 2026-11-09 S8): kişisel ve rol varsayılanı.

Tek tablo, iki sahip türü: satır ya bir KULLANICININ kendi düzenidir
(`user_id`) ya da bir ROLÜN varsayılan düzenidir (`role_id`); ikisi birden ya
da hiçbiri olamaz (`ck_ana_panel_duzen_sahibi`). Her sahibin en fazla bir
düzeni vardır (kısmi tekil indeksler).

Etkin düzen sırası: kullanıcının kendi düzeni → rolünün varsayılanı → sistem
varsayılanı (koddaki `services/ana_panel_duzeni.SISTEM_VARSAYILANI`, bugünkü
panel). Hiç satır yoksa davranış bugünküyle aynıdır; satır silmek
"varsayılana dön"dür.

`bilesenler` sıralı bir JSON listesidir: `[{"kod", "boyut", "gorunur"}]`.
Bileşen kodları ve izinleri `services/ana_panel_duzeni.BILESENLER`
kaydındadır; şema kodları SABİTLEMEZ (yeni bileşen migration gerektirmesin),
doğrulama servis katmanında yapılır ve okumada bilinmeyen/izinsiz kod düşer.
"""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin


class AnaPanelDuzeni(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "ana_panel_duzenleri"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (role_id IS NULL)", name="ck_ana_panel_duzen_sahibi"),
        CheckConstraint("jsonb_typeof(bilesenler) = 'array'", name="ck_ana_panel_duzen_liste"),
        Index(
            "uq_ana_panel_duzen_kullanici",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_ana_panel_duzen_rol",
            "role_id",
            unique=True,
            postgresql_where=text("role_id IS NOT NULL"),
        ),
    )

    # Kullanıcı/rol silinirse düzeni de gider (kişisel tercih; iş kaydı değil).
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    role_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE")
    )
    bilesenler: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
