"""Eski sistemdeki AD METNİ ile kaydedilmiş personelin kullanıcıya eşlemesi.

V1.20.1'de iş ataması, zaman kaydı ve eğitim katılımı kişiyi kimlikle değil
serbest ad metniyle tutuyordu (`WorkOrders.AssignedName`,
`TimeEntries.PersonnelName`). Aynı kişi "Ali Veli", "ALİ VELİ", "A. Veli"
olarak üç farklı yazımla geçiyor. Göç bu metni bir `users` kimliğine
bağlamadan kişi bazlı hiçbir sayı (kişi-saat, iş adedi) doğru çıkmaz.

Eşleme UYDURULMAZ: sistem ad benzerliğinden ÖNERİ üretir
(`durum='ONERI'`), insan onaylar (`ONAYLANDI`) ya da reddeder. Onaylanmamış
satırın kayıtları "eşleşmeyen personel" olarak göç raporunda kalır (E13-08).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin

AD_ESLEME_DURUMLARI = ("ONERI", "ONAYLANDI", "ESLESMEDI", "REDDEDILDI")


class PersonnelNameMap(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    __tablename__ = "personnel_name_maps"
    __table_args__ = (
        CheckConstraint(
            "durum IN (" + ", ".join(f"'{d}'" for d in AD_ESLEME_DURUMLARI) + ")",
            name="ck_pnm_durum",
        ),
        # Aynı kaynak alandaki aynı normalize ad tek satırdır: göç tekrar
        # koşunca öneri çoğalmaz, onay kaybolmaz.
        UniqueConstraint("kaynak_sistem", "kaynak_alan", "normal_ad", name="uq_pnm_kaynak"),
    )

    kaynak_sistem: Mapped[str] = mapped_column(String(30))  # ör. V1_20_1
    kaynak_alan: Mapped[str] = mapped_column(String(60))  # ör. TimeEntries.PersonnelName
    # Ham metin değişmez; gösterim ve iz için.
    kaynak_ad: Mapped[str] = mapped_column(String(150))
    normal_ad: Mapped[str] = mapped_column(String(150))
    kayit_sayisi: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    onerilen_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    onaylanan_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    durum: Mapped[str] = mapped_column(String(12), server_default=text("'ONERI'"), default="ONERI")
    onaylayan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    onay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
