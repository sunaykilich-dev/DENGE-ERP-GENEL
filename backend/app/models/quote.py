"""Fiyat teklifi (brief §4.9).

**Revizyon = yeni versiyon.** Her değişiklik yeni bir versiyon açar, eski
versiyon KİLİTLENİR ve görüntülenebilir kalır. Müşteriye gönderilen belgenin
sonradan değişmesi, "ben başka bir fiyat görmüştüm" tartışmasının kaynağıdır.

**Fiyat ve KDV versiyona dondurulur.** Ürün kartındaki liste fiyatı veya
ayarlardaki KDV oranı sonradan değişse de gönderilmiş teklif aynı kalır
(plan §3.3/2).

Online kabul dışa açık bir sunucu ister; veri modeli hazır, `public_token`
üretiliyor ve kabul/red kaydı tutuluyor. Yerel kurulumda link açılamaz ama
kabul elle de işaretlenebilir — kim, ne zaman işaretledi loglanır.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionedMixin,
)
from app.models.rbac import birim_check

TEKLIF_DURUMLARI = (
    "TASLAK",
    "ONAY_BEKLIYOR",  # eşik üstü iskonto → satış müdürü onayı; birimli: iç onay
    "ONAYLANDI",  # yalnız birimli (servis) teklif: iç onaydan geçti (Dalga 2)
    "GONDERILDI",
    "GORUNTULENDI",
    "REVIZE_EDILDI",
    "KABUL",
    "RED",
    "SURESI_DOLDU",
    "SIPARISE_DONUSTU",
    "IPTAL",  # yalnız birimli teklif; gerekçe zorunlu (Dalga 2)
)

# Kabul edilen servis teklifinin açacağı servis işi türü (KARARLAR 2026-11-05
# §9.4). PB/ATOLYE yalnız sistem açar; TOPLAMA kiralamanındır — burada yok.
TEKLIF_IS_TURLERI = ("PLANSIZ_BAKIM", "ARIZA", "DESTEK", "KURULUM", "KESIF", "DEMONTAJ", "TASIMA")

# Kaybedilme nedeni kataloğu (KARARLAR 2026-11-09 S2.1). Kod KALICIDIR (rapor
# kırılımı ve `ck_quote_kayip_kod` buna bakar); "DIGER" seçilirse açıklama
# (`lost_reason`) zorunludur. Eski serbest metin kayıtları migration
# `fcsatis00001` ile DIGER + açıklama olarak taşındı.
KAYIP_NEDENLERI: dict[str, str] = {
    "FIYAT_YUKSEK": "Fiyat yüksek",
    "RAKIP": "Rakip tercih edildi",
    "BUTCE_YOK": "Bütçe yok veya ertelendi",
    "TEKNIK_UYGUNSUZ": "Teknik uygunsuzluk",
    "TESLIM_SURESI": "Teslim süresi",
    "YANIT_YOK": "Müşteri yanıt vermedi",
    "DIGER": "Diğer",
}

# ISCILIK: birimli servis teklifinde işçilik kalemi (DB CHECK'i yok).
KALEM_TIPLERI = ("URUN", "PAKET", "HIZMET", "ABONELIK", "SIM_PAKETI", "SERBEST", "ISCILIK")
# Gönderim kanalı (elle gönderimde not zorunlu; E07-05).
GONDERIM_KANALLARI = ("EPOSTA", "ELDEN", "KARGO", "HARICI_EPOSTA", "DIGER")
GONDERIM_SONUCLARI = ("BASARILI", "HATA")
# Satış teklifi kalemi 300'de kalır (sipariş kalemi 300); 500 yalnız birimli
# teklifte servis katmanında kabul edilir (E07 kontrol B9).
BIRIMLI_KALEM_ACIKLAMA_UZUNLUGU = 500


class Quote(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    """Satış teklifi ve (Dalga 2) birimli teknik servis teklifi — TEK tablo (KD-32).

    `birim IS NULL` = satış teklifi: canlı akış AYNEN sürer, satış panel/rapor
    yalnız bunları sayar. `birim` dolu = servis teklifi: iç onay, `TEKLIF`
    makinesi ve birim kapsamı devreye girer. `ck_quote_durum`'a ONAYLANDI ve
    IPTAL eklenmesi plan §1.12'nin onaylı istisnasıdır (yalnız ekleme).
    """

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("quote_no", name="uq_quote_no"),
        CheckConstraint(
            "status IN ('TASLAK','ONAY_BEKLIYOR','ONAYLANDI','GONDERILDI','GORUNTULENDI',"
            "'REVIZE_EDILDI','KABUL','RED','SURESI_DOLDU','SIPARISE_DONUSTU','IPTAL')",
            name="ck_quote_durum",
        ),
        Index("ix_quote_musteri", "customer_id"),
        Index("ix_quote_durum", "status"),
        # --- Dalga 2 (d2a000000005) ---------------------------------------
        CheckConstraint(birim_check("birim", bos_olabilir=True), name="ck_quote_birim"),
        CheckConstraint(
            "status <> 'IPTAL' OR cancel_reason IS NOT NULL", name="ck_quote_iptal_neden"
        ),
        Index("ix_quote_servis_isi", "service_order_id"),
        Index("ix_quote_birim_durum_tarih", "birim", "status", "created_at"),
        CheckConstraint(
            "servis_turu IS NULL OR servis_turu IN ("
            + ", ".join(f"'{t}'" for t in TEKLIF_IS_TURLERI)
            + ")",
            name="ck_quote_servis_turu",
        ),
        # --- Satış takibi (fcsatis00001, KARARLAR 2026-11-09 S2.1) -----------
        CheckConstraint(
            "lost_reason_kod IS NULL OR lost_reason_kod IN ("
            + ", ".join(f"'{k}'" for k in KAYIP_NEDENLERI)
            + ")",
            name="ck_quote_kayip_kod",
        ),
        CheckConstraint(
            "lost_reason_kod IS NULL OR lost_reason_kod <> 'DIGER' OR lost_reason IS NOT NULL",
            name="ck_quote_kayip_diger_aciklama",
        ),
    )

    quote_no: Mapped[str] = mapped_column(String(24))
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), server_default=text("'TASLAK'"))
    current_version_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str | None] = mapped_column(String(200))
    # Kayıp nedeni zorunlu (brief §4.8 satış hunisi). S2.1'den beri neden
    # `lost_reason_kod` kataloğundan seçilir; bu alan açıklamadır (DIGER'de
    # zorunlu).
    lost_reason: Mapped[str | None] = mapped_column(String(200))
    lost_reason_kod: Mapped[str | None] = mapped_column(String(20))
    # Teklifin ilgili olduğu tesis (E14-15). Servis işinden açılan teklifte
    # sunucu işten kopyalar; satış teklifinde boştur, bugünkü davranış aynı.
    address_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("addresses.id", ondelete="SET NULL", name="fk_quotes_adres"),
        index=True,
    )

    # --- Birimli servis teklifi (Dalga 2; hepsi nullable, plan §1.12) --------
    birim: Mapped[str | None] = mapped_column(String(20))
    service_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_orders.id", ondelete="SET NULL", name="fk_quotes_servis_isi"),
    )
    # Müşteri irtibatı (kişisel veri; PDF ve varsayılan alıcı).
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id", ondelete="SET NULL", name="fk_quotes_irtibat")
    )
    # Onaya gönderen; öz-onay yasağı buna ve `owner_id`'ye bakar.
    submitted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_quotes_onaya_gonderen")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_quotes_iptal_eden")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    # Kabulde açılacak servis işi türü (yalnız işe bağlı OLMAYAN birimli
    # teklif). NULL = kabulde iş açılmaz (eski davranış).
    servis_turu: Mapped[str | None] = mapped_column(String(20))

    versions: Mapped[list["QuoteVersion"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", lazy="selectin"
    )


class QuoteVersion(Base, PkMixin, TimestampMixin, ActorMixin):
    __tablename__ = "quote_versions"
    __table_args__ = (
        UniqueConstraint("quote_id", "version_no", name="uq_quote_version"),
        UniqueConstraint("public_token", name="uq_quote_token"),
        CheckConstraint("version_no > 0", name="ck_qv_versiyon"),
        Index("ix_qv_quote", "quote_id"),
        CheckConstraint(
            "sent_channel IS NULL OR sent_channel IN ("
            + ", ".join(f"'{k}'" for k in GONDERIM_KANALLARI)
            + ")",
            name="ck_qv_gonderim_kanali",
        ),
    )

    quote_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("quotes.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    currency: Mapped[str] = mapped_column(String(3), server_default=text("'TRY'"))
    # Döviz teklifte kur ve kur tarihi YAZAR (brief §4.9). TCMB'den otomatik
    # çekilebilir ama yerel kurulumda elle girilir; hangisi olduğu kaydedilir.
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fx_date: Mapped[date | None] = mapped_column(Date)
    fx_source: Mapped[str | None] = mapped_column(String(10))  # TCMB | MANUEL

    valid_until: Mapped[date | None] = mapped_column(Date)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    vat_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    # En yüksek kalem iskontosu — onay eşiği buna bakar.
    max_discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    discount_approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    discount_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Dışa açık link jetonu — müşteri teklifi bununla görüntüler ve kabul eder.
    public_token: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(String(300))
    # Kabul/red linkten mi geldi yoksa ekip mi işaretledi — ikisi aynı şey değil.
    decision_channel: Mapped[str | None] = mapped_column(String(10))  # LINK | ELLE

    # Gönderilen versiyon bir daha değişmez.
    is_locked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)

    # --- Dalga 2: iç onay SÜRÜM bazında (revizyon onayı yeniden ister) ------
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_qv_onaylayan")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_channel: Mapped[str | None] = mapped_column(String(16))
    sent_note: Mapped[str | None] = mapped_column(String(300))

    quote: Mapped[Quote] = relationship(back_populates="versions")
    lines: Mapped[list["QuoteLine"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", lazy="selectin"
    )


class QuoteLine(Base, PkMixin):
    __tablename__ = "quote_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_ql_adet"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100", name="ck_ql_iskonto"),
        Index("ix_ql_version", "version_id"),
        Index("ix_ql_servis_isi", "service_order_id"),
    )

    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quote_versions.id", ondelete="CASCADE")
    )
    item_type: Mapped[str] = mapped_column(String(16), server_default=text("'URUN'"))
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="SET NULL")
    )
    # 300 → 500 genişletme (Dalga 2, onaylı istisna KD-33); satış şeması 300'de
    # kalır, 500 yalnız birimli teklif kaleminde kabul edilir.
    description: Mapped[str] = mapped_column(String(500))
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default=text("1"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    # KDV oranı kalem bazında DONDURULUR: ayar sonradan değişse de bu teklif
    # aynı kalır.
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Kalemin ait olduğu servis işi (birden çok PB bulgusu tek teklifte). Boşsa
    # kalem teklifin `service_order_id`'sine sayılır.
    service_order_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_orders.id", ondelete="SET NULL", name="fk_ql_servis_isi"),
    )

    version: Mapped[QuoteVersion] = relationship(back_populates="lines")


class QuoteSend(Base, PkMixin, TimestampMixin, ActorMixin):
    """Teklif gönderim günlüğü (E07-06) — yalnız ekleme; düzenleme/silme ucu yok.

    Başarısız deneme ve hız sınırı sorgusu `audit_logs` üzerinden zor
    yapılırdı (K16). `hata_ozeti` sınıflandırılmış özettir (SMTP_KAPALI,
    SMTP_BAGLANTI, SMTP_KIMLIK, SMTP_RED); istisna metni ve sunucu adresi
    YAZILMAZ. `alicilar` kişisel veridir (KVKK anonimleştirmesi kapsamında).
    """

    __tablename__ = "quote_sends"
    __table_args__ = (
        CheckConstraint(
            "kanal IN (" + ", ".join(f"'{k}'" for k in GONDERIM_KANALLARI) + ")",
            name="ck_qsend_kanal",
        ),
        CheckConstraint(
            "alicilar IS NULL OR cardinality(alicilar) <= 3", name="ck_qsend_alici_sayisi"
        ),
        CheckConstraint(
            "sonuc IN (" + ", ".join(f"'{s}'" for s in GONDERIM_SONUCLARI) + ")",
            name="ck_qsend_sonuc",
        ),
        Index("ix_qsend_teklif", "quote_id"),
        Index("ix_qsend_kullanici_zaman", "created_by", "created_at"),
    )

    quote_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("quotes.id", ondelete="CASCADE"))
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quote_versions.id", ondelete="CASCADE")
    )
    kanal: Mapped[str] = mapped_column(String(16))
    alicilar: Mapped[list[str] | None] = mapped_column(ARRAY(String(254)))
    cc: Mapped[str | None] = mapped_column(String(254))
    sonuc: Mapped[str] = mapped_column(String(10))
    hata_ozeti: Mapped[str | None] = mapped_column(String(300))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    notlar: Mapped[str | None] = mapped_column(String(300))
