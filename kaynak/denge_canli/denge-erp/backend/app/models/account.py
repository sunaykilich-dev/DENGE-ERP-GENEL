"""Hesaplar: müşteri, bayi, montaj noktası, tedarikçi.

Brief §4.8 tek bir `account_type` enum'ı öngörüyordu. Gerçek veri bunu
çürütüyor: AUTOLAND kendi aracına kendi montajını yapan bir rent-a-car —
yani aynı anda hem MÜŞTERİ hem MONTAJ NOKTASI. Aynı işaret beş montaj
noktasında daha var. Bu yüzden tip tekil enum değil, BAYRAK SETİ.

Ayrıca müşterilerin %40,5'inde bayi adı firma adının içine parantezle
gömülmüş durumda (`BZL OTOMOTİV (GAZİANTEP EVA)`). Göçte ayrıştırılıp
`parent_dealer_id`'ye yazılacak; bayi bazında ciro raporu ancak böyle çıkar.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)
from app.services.normalize import tr_normkey

# Belge tipi — hak edişte kesintileri belirler (brief §4.7 madde 6).
BELGE_TIPLERI = ("FATURA", "SERBEST_MESLEK_MAKBUZU", "GIDER_PUSULASI", "BELIRSIZ")

SEGMENTLER = (
    "BIREYSEL",
    "KURUMSAL_FILO",
    "OKUL_SERVISI",
    "KIRALAMA",
    "LOJISTIK",
    "KAMU",
    "HYTERA_BAYI",  # telsiz iş kolu — araç takip bayileriyle karışmasın
    "DIGER",
)


class Account(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "is_musteri OR is_bayi OR is_montaj_noktasi OR is_tedarikci",
            name="ck_accounts_en_az_bir_rol",
        ),
        CheckConstraint("id <> parent_dealer_id", name="ck_accounts_kendi_bayisi_olamaz"),
        # Aynı ada iki kayıt açılmasın diye değil (unvanlar benzeşebiliyor),
        # mükerrer ADAYI bulmak için: göçte 44 montaj noktasından 5 çift
        # birleştirilecek. pg_trgm benzerlik araması bu indeksi kullanır.
        Index("ix_accounts_title_trgm", text("title_key gin_trgm_ops"), postgresql_using="gin"),
        Index("ix_accounts_tax_no", "tax_no"),
        UniqueConstraint("source_system", "source_ref", name="uq_accounts_kaynak"),
    )

    title: Mapped[str] = mapped_column(String(200))
    # tr_normkey(title) — arama ve mükerrer tespiti bunun üzerinden yapılır.
    # Uygulama katmanında doldurulur; Türkçe katlama SQL'de güvenilir değil.
    title_key: Mapped[str] = mapped_column(String(200), index=True)

    # --- Roller (bayrak seti) ---
    is_musteri: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_bayi: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_montaj_noktasi: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_tedarikci: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # Müşteri hangi bayi üzerinden geldi. Bayi paneli ileride eklenirse
    # kapsam bu alandan türetilir.
    parent_dealer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )

    # --- Mali kimlik ---
    tax_no: Mapped[str | None] = mapped_column(String(11))
    tax_office: Mapped[str | None] = mapped_column(String(80))
    iban: Mapped[str | None] = mapped_column(String(26))

    # --- Ticari ---
    segment: Mapped[str | None] = mapped_column(String(30))
    region: Mapped[str | None] = mapped_column(String(60))
    sales_rep_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # --- İletişim (birincil; ayrıntısı contacts tablosunda) ---
    email: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(16))  # E.164

    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    parent_dealer: Mapped["Account | None"] = relationship(remote_side="Account.id")
    # installation_partners tablosunun accounts'a İKİ yabancı anahtarı var
    # (account_id ve billing_account_id: fatura başka tüzel kişi adına
    # kesilebiliyor). Hangisinin bu ilişkiyi kurduğu açıkça yazılmalı.
    partner: Mapped["InstallationPartner | None"] = relationship(
        back_populates="account",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="InstallationPartner.account_id",
    )

    @property
    def roller(self) -> list[str]:
        adlar = []
        if self.is_musteri:
            adlar.append("MUSTERI")
        if self.is_bayi:
            adlar.append("BAYI")
        if self.is_montaj_noktasi:
            adlar.append("MONTAJ_NOKTASI")
        if self.is_tedarikci:
            adlar.append("TEDARIKCI")
        return adlar


class InstallationPartner(Base, TimestampMixin):
    """Montaj noktasının hak edişe özgü bilgileri (accounts ile 1:1)."""

    __tablename__ = "installation_partners"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('FATURA','SERBEST_MESLEK_MAKBUZU','GIDER_PUSULASI','BELIRSIZ')",
            name="ck_partner_belge_tipi",
        ),
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    document_type: Mapped[str] = mapped_column(String(30), server_default=text("'BELIRSIZ'"))

    # Montaj noktası bazen BAŞKA bir tüzel kişi üzerinden fatura kesiyor.
    # Kaynak veride bu alan (ftKesenFirma) hiç doldurulmamış ama Excel
    # şablonunda var — ihtiyaç beyan edilmiş. Varsayılan olarak boş; dolu
    # olduğunda hak ediş dökümü bu hesabın adına düzenlenir.
    billing_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )

    # Yol ücreti birim fiyatı (TL/km). Tarifeler ayrı ve tarihli tabloda;
    # bu, ziyaret başına eklenen YOL_KM satırının varsayılan birim fiyatı.
    km_unit_price: Mapped[float | None] = mapped_column()

    account: Mapped[Account] = relationship(back_populates="partner", foreign_keys=[account_id])


class Contact(Base, PkMixin, TimestampMixin):
    __tablename__ = "contacts"

    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(80))  # görev
    phone: Mapped[str | None] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(160))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)


class Address(Base, PkMixin, TimestampMixin):
    __tablename__ = "addresses"

    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(40), server_default=text("'Merkez'"))
    line: Mapped[str] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(60))
    city: Mapped[str | None] = mapped_column(String(60))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# `title_key` unutulmasın diye ORM olayına bağlanır: API, seed ve veri göçü
# hepsi aynı yoldan geçer. Serviste elle set etmek, bir çağrı yerini unuttuğunda
# aramayı sessizce bozardı.
@event.listens_for(Account, "before_insert")
@event.listens_for(Account, "before_update")
def _hesap_anahtari(_mapper, _connection, target: Account) -> None:
    target.title_key = tr_normkey(target.title)
