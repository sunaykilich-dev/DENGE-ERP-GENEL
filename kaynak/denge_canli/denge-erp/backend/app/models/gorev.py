"""Görev panosu — pano / kolon / etiket / kart / üye / yorum.

Kart bir ERP kaydına BAĞLANABİLİR ama bağlanmak ZORUNDA DEĞİLDİR (kullanıcı
kararı, 30 Eyl 2026). "Vergi levhalarını topla" gibi hiçbir kayda karşılık
gelmeyen işler de panoda durmalı; öte yandan "şu iş emrini kapat" kartının
kayda tıklanabilmesi panoyu ERP'nin parçası yapan şey.

Bağlantı POLİMORFİK (`entity` + `entity_id`) — `audit_logs` ile aynı desen.
Her kayıt tipi için ayrı FK kolonu açmak on kolonluk bir tablo üretirdi ve
yeni bir tip eklemek migration gerektirirdi. Bedeli: veritabanı bütünlüğü
zorlamaz, kaynak kayıt silinirse kart öksüz kalır — bu yüzden bağlantı
çözülürken kaydın hâlâ var olup olmadığı KONTROL EDİLİR ve yoksa kart
"kaynak kayıt silinmiş" der (bkz. `services/gorevler.py`).
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin, VersionedMixin

ONCELIKLER = ("DUSUK", "NORMAL", "YUKSEK", "ACIL")


class Board(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """Pano. Ekip/konu başına bir tane: "Montaj Planı", "Ay Sonu Kapanışı"…"""

    __tablename__ = "boards"
    __table_args__ = (Index("ix_pano_sira", "sira"),)

    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(300))
    sira: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Arşiv silme DEĞİLDİR: pano kapanır ama kartları ve geçmişi durur.
    # Bitmiş bir işin panosunu silmek, o işin nasıl yürüdüğünü de siler.
    arsivlendi: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    kolonlar: Mapped[list["BoardColumn"]] = relationship(
        back_populates="pano",
        cascade="all, delete-orphan",
        order_by="BoardColumn.sira",
        lazy="selectin",
    )
    etiketler: Mapped[list["BoardLabel"]] = relationship(
        back_populates="pano",
        cascade="all, delete-orphan",
        order_by="BoardLabel.sira",
        lazy="selectin",
    )


class BoardColumn(Base, PkMixin, TimestampMixin):
    """Panonun kolonu (liste). Kolonlar pano başına serbesttir."""

    __tablename__ = "board_columns"
    __table_args__ = (Index("ix_kolon_pano", "board_id", "sira"),)

    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(60))
    sira: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Bu kolona düşen kart "bitti" sayılır: panel sayımı ve kartın üstü çizili
    # görünmesi buna bakar. Kolon adına ("Bitti", "Tamam", "Done") bakmak
    # kırılgandı — kullanıcı kolonu yeniden adlandırdığında sessizce bozulurdu.
    bitis_mi: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Aynı anda kaç kart olabilir. NULL = sınırsız. Aşıldığında engellenmez,
    # arayüzde uyarı çıkar: sert kural işi durdurur, uyarı düşündürür.
    wip_limit: Mapped[int | None] = mapped_column(Integer)

    pano: Mapped[Board] = relationship(back_populates="kolonlar")


class BoardLabel(Base, PkMixin, TimestampMixin):
    """Pano etiketi. Renk zorunlu, AD DEĞİL.

    Trello'da da öyle: yeni pano altı renkle ve adsız gelir, isteyen adlandırır.
    Ad zorunlu olsaydı hızlı bir işaretleme için önce isim düşünmek gerekirdi.
    """

    __tablename__ = "board_labels"
    __table_args__ = (Index("ix_etiket_pano", "board_id", "sira"),)

    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE"), index=True
    )
    ad: Mapped[str | None] = mapped_column(String(40))
    renk: Mapped[str] = mapped_column(String(20))
    sira: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    pano: Mapped[Board] = relationship(back_populates="etiketler")


class CardMember(Base):
    """Kartın ilgili kişisi. ÇOKLU — bir işte birden fazla kişi olur.

    Tek `assignee_id` kolonu vardı ve gerçek iş buna uymuyordu: bir montajda
    koordinatör, tekniker ve satış temsilcisi aynı anda ilgili olabiliyor.
    Tek kişi seçmek, kalanları kartın dışında bırakıyordu.
    """

    __tablename__ = "card_members"

    card_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class CardLabel(Base):
    """Karta yapıştırılmış etiket."""

    __tablename__ = "card_labels"

    card_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board_labels.id", ondelete="CASCADE"), primary_key=True
    )


class Card(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """Kart = tek bir iş."""

    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("oncelik IN ('DUSUK','NORMAL','YUKSEK','ACIL')", name="ck_kart_oncelik"),
        # Bağlantı ya tamamen var ya hiç yok; yarım bağlantı sessizce
        # çözümlenemeyen bir karta yol açardı.
        CheckConstraint(
            "(entity IS NULL AND entity_id IS NULL) "
            "OR (entity IS NOT NULL AND entity_id IS NOT NULL)",
            name="ck_kart_baglanti_tam",
        ),
        Index("ix_kart_kolon", "column_id", "sira"),
        Index("ix_kart_baglanti", "entity", "entity_id"),
    )

    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE"), index=True
    )
    column_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board_columns.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    sira: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    due_date: Mapped[date | None] = mapped_column(Date)
    oncelik: Mapped[str] = mapped_column(String(10), server_default=text("'NORMAL'"))

    # ERP kaydına polimorfik bağlantı; ikisi birlikte dolar ya da ikisi de boş.
    entity: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)

    # Kart bitiş kolonuna İLK taşındığında damgalanır. Kolonun `bitis_mi`
    # bayrağından türetmek yetmiyor: kart sonradan geri çekilse de "ne zaman
    # bitmişti" sorusunun cevabı kalmalı.
    tamamlandi_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    yorumlar: Mapped[list["CardComment"]] = relationship(
        back_populates="kart",
        cascade="all, delete-orphan",
        order_by="CardComment.created_at",
    )
    # Yalnız CASCADE silme için; okuma API'de AÇIK sorguyla yapılır. Adları
    # `uyeler`/`etiketler` olsaydı KartOut'un aynı adlı alanlarıyla çakışır ve
    # `model_validate` bağ satırlarını çıktı şeması sanardı.
    uye_baglari: Mapped[list[CardMember]] = relationship(cascade="all, delete-orphan")
    etiket_baglari: Mapped[list[CardLabel]] = relationship(cascade="all, delete-orphan")


class CardComment(Base, PkMixin, TimestampMixin):
    """Kart yorumu. Düzenlenemez ve silinemez — konuşma kaydı budanmaz."""

    __tablename__ = "card_comments"

    card_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    metin: Mapped[str] = mapped_column(Text)

    kart: Mapped[Card] = relationship(back_populates="yorumlar")
