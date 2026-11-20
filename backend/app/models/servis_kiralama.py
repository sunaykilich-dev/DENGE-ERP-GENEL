"""Kiralama ve kiralık cihaz envanteri (E06).

**Kiralık cihaz `devices`'a ve servis kütüğüne YAZILMAZ** (KD-31): global
`uq_devices_seri` ve mobilite stok raporu bozulurdu. Kiralık envanter ayrı
tablodur; IMEI'li ürün ve MOBILITE/ARAC_TAKIP birimi buraya giremez (E06-D05:
o birimlerin kiralık cihazı canlıda `MUSTERI_KIRALIK` sahipliğiyle izlenir) —
seri takipli kiralık cihaz yalnız `SERI_NO` kimlik tipindedir, bileşik FK
`fk_rasset_urun_kimlik` ürünün kimlik tipini kilitler.

**Müşteri = hesap, lokasyon = adres** (plan §1.5); ürün = `products`; depo =
`warehouses(kiralama_deposu=true)`. Kalem ≠ tahsis: kalem "kaç adet istendi",
tahsis "hangi depodan hangi cihaz / kaç adet, hangi tarihlerde" (E06-04).
Aynı seri cihazın çakışan tarihlerde ikinci AKTİF tahsisi M10.1 (KARARLAR
2026-10-28) ile engel değil UYARIDIR: servis 409 + çakışma listesi döner,
gerekçeli onayla kaydedilir. Eski `ex_rtahsis_cihaz_cakisma` kısıtı
`e1a000000003` ile kalktı; çakışma sorgusu aynı ifadeli GiST indeksini
(`ix_rtahsis_cihaz_aralik`, `daterange '[)'`) kullanır.

**Toplu bakiye saklanmaz**, hareket defterinden hesaplanır
(`rental_inventory_movements`, ekleme-yalnız; `trg_rhareket_degismez`).
`rental_assets.durum/warehouse_id` yalnız sorgu kolaylığı için tutulan
denormalize alanlardır; doğruluk kaynağı hareket zinciridir.

Kiralama durumu yalnız `KIRALAMA` makinesiyle, `services/teknik_servis/
kiralama.py` aşama uçlarından ilerler; PUT durum kabul etmez. Fiyat alanı YOK.

Dalga 3 (D3-S, `d3a000000001`): depo sayımı `rental_counts` /
`rental_count_lines` — onaysız sayım hiçbir şeyi değiştirmez.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)
from app.models.rbac import birim_check
from app.services import normalize as _normalize


def _in(sutun: str, degerler: tuple[str, ...], *, bos: bool = False) -> str:
    liste = ", ".join(f"'{d}'" for d in degerler)
    return f"{sutun} IS NULL OR {sutun} IN ({liste})" if bos else f"{sutun} IN ({liste})"


# --- Sözlükler (E06 §2.1) -------------------------------------------------------
KIRALAMA_DURUMLARI = (
    "TALEP",
    "PLANLANDI",
    "HAZIRLANIYOR",
    "SEVK_EDILDI",
    "KURULUM_YAPILDI",
    "DEVREYE_ALINDI",
    "TOPLANDI",
    "DEPOYA_ALINDI",
    "KAPANDI",
    "IPTAL",
)
# HURDA: envanterden gerekçeli çıkış (E06-D02); MUSTERIDE durum değil, nottur.
KIRALIK_DURUMLARI = ("HAZIR", "HAZIR_DEGIL", "KONTROLDE", "KIRADA", "KAYIP", "ATOLYEDE", "HURDA")
KIRALIK_HAREKET_TURLERI = (
    "GIRIS",
    "TRANSFER",
    "TAHSIS",
    "TAHSIS_COZ",
    "SEVK",
    "IADE",
    "KAYIP",
    "BULUNDU",
    "KONTROL",
    "ATOLYE",
    "DUZENLEME",
    "SAYIM",
    "DUZELTME",
    "DEGISIM",
    "HURDA",
)
TAHSIS_DURUMLARI = ("AKTIF", "KAPANDI", "COZULDU")
KONTROL_SONUCLARI = ("UYGUN", "EKSIK", "ARIZALI")
IRTIBAT_ROLLERI = ("SATIN_ALMA", "SAHA_OPERASYON", "TEKNIK_SORUMLU", "DIGER")
KIRALAMA_OLAY_TURLERI = (
    "OLUSTUR",
    "DURUM",
    "ASAMA",
    "TAHSIS",
    "SEVK",
    "IADE",
    "KONTROL",
    "IPTAL",
    "DUZELTME",
    "TARIH",
    "SORUMLU",
    "KALEM",
    "IRTIBAT",
    "NOT",
)
# Kiralamaya bağlanabilen servis işi türleri (E06-19, `uq_so_kiralama_tur_acik`).
KIRALAMA_SERVIS_TURLERI = ("KURULUM", "TOPLAMA")
# Kiralık envanter ve kiralama bu birimlerde YOK (E06-D05).
KIRALAMA_DISI_BIRIMLER = ("MOBILITE", "ARAC_TAKIP")
# Kiralama deposu fiziksel sayımı (E06-22 b; Dalga 3). `KIRALIK_SAYIM` makinesi.
KIRALIK_SAYIM_DURUMLARI = ("ACIK", "ONAYLANDI", "IPTAL")

_MOBILITE_DISI = "birim NOT IN ('MOBILITE', 'ARAC_TAKIP')"
_TAHSIS_ARALIGI = literal_column("daterange(baslangic, bitis, '[)')")


class RentalCatalogItem(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    """Kiralama kataloğu PROFİLİ — ayrı ürün tablosu değil (`products`'a bağlı).

    Birim kiralık envanterin birimini belirler (envanter satırı birimi buradan
    kopyalar ve değişmez). Seed canlı kataloğa yazmaz; profil ekrandan ya da
    göçle açılır (E06-16 revised).
    """

    __tablename__ = "rental_catalog_items"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_rcat_urun"),
        CheckConstraint(birim_check("birim"), name="ck_rcat_birim"),
        CheckConstraint(_MOBILITE_DISI, name="ck_rcat_mobilite_disi"),
        CheckConstraint("sira >= 0", name="ck_rcat_sira"),
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    birim: Mapped[str] = mapped_column(String(20))
    kategori: Mapped[str | None] = mapped_column(String(40))
    sira: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class RentalAsset(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Seri takipli kiralık cihaz (toplu ürün satır açmaz, bakiyesi defterden).

    `serial_key` tek normalizasyon fonksiyonundandır (`normalize_seri`);
    seri METİN. `birim` katalog profilinden kopyalanır, değişmez.
    """

    __tablename__ = "rental_assets"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_rasset_kaynak"),
        # Ürünün kimlik tipi değişirse kiralık cihaz tutarsız kalmasın (RESTRICT).
        ForeignKeyConstraint(
            ["product_id", "identity_kind"],
            ["products.id", "products.identity_kind"],
            name="fk_rasset_urun_kimlik",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        # Yalnız SERI_NO: IMEI'li ürün kiralık envantere girerse aynı cihaz hem
        # `devices`'ta hem burada olurdu (E06 kontrol §2.2/11).
        CheckConstraint(
            "identity_kind = 'SERI_NO' AND serial_no IS NOT NULL", name="ck_rasset_seri_takipli"
        ),
        CheckConstraint(_in("durum", KIRALIK_DURUMLARI), name="ck_rasset_durum"),
        CheckConstraint(birim_check("birim"), name="ck_rasset_birim"),
        CheckConstraint(_MOBILITE_DISI, name="ck_rasset_mobilite_disi"),
        Index(
            "uq_rasset_urun_seri",
            "product_id",
            "serial_key",
            unique=True,
            postgresql_where=text("NOT is_deleted"),
        ),
        Index("ix_rasset_depo_durum", "warehouse_id", "durum"),
        Index("ix_rasset_seri", "serial_key"),
    )

    product_id: Mapped[int] = mapped_column(BigInteger)
    identity_kind: Mapped[str] = mapped_column(
        String(10), server_default=text("'SERI_NO'"), default="SERI_NO"
    )
    serial_no: Mapped[str] = mapped_column(String(200))
    serial_key: Mapped[str] = mapped_column(String(200))
    birim: Mapped[str] = mapped_column(String(20))
    # KIRADA/KAYIP/HURDA'da son depo; sorgu kolaylığı (doğruluk = hareket zinciri).
    warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    durum: Mapped[str] = mapped_column(String(16), server_default=text("'HAZIR'"), default="HAZIR")
    eksik_notu: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    # Cihaza yapıştırılan karekodun değişmez kodu (KARARLAR 2026-11-20 §3);
    # ilk etiket basımında üretilir. Karekod ERP'deki etiket sayfasını açar.
    etiket_kodu: Mapped[str | None] = mapped_column(String(24), unique=True)


class Rental(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Kiralama başlığı (TS-110). Numara `KIR-YYYYAA-NNNNNN` (`rental_no_seq`,
    OWNED BY rentals.id). `bitis` iade günüdür (yarı açık aralık)."""

    __tablename__ = "rentals"
    __table_args__ = (
        UniqueConstraint("rental_no", name="uq_rental_no"),
        UniqueConstraint("source_system", "source_ref", name="uq_rental_kaynak"),
        CheckConstraint(birim_check("birim"), name="ck_rental_birim"),
        CheckConstraint(_MOBILITE_DISI, name="ck_rental_mobilite_disi"),
        CheckConstraint(_in("status", KIRALAMA_DURUMLARI), name="ck_rental_durum"),
        CheckConstraint("bitis > baslangic", name="ck_rental_tarih"),
        CheckConstraint(
            "status <> 'IPTAL' OR iptal_gerekcesi IS NOT NULL", name="ck_rental_iptal_gerekce"
        ),
        Index("ix_rental_durum_bitis", "status", "bitis"),
        Index("ix_rental_musteri", "customer_id"),
    )

    rental_no: Mapped[str] = mapped_column(String(24))
    birim: Mapped[str] = mapped_column(String(20))
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    address_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("addresses.id", ondelete="SET NULL")
    )
    # Adres kartı olmayan yer (etkinlik alanı gibi).
    lokasyon_metni: Mapped[str | None] = mapped_column(String(300))
    proje_adi: Mapped[str | None] = mapped_column(String(200))
    baslangic: Mapped[date] = mapped_column(Date)
    bitis: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'TALEP'"), default="TALEP")
    sorumlu_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Kaynak teklif — yalnız referans; `quotes`'a yazım yok.
    quote_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quotes.id", ondelete="SET NULL")
    )
    iptal_gerekcesi: Mapped[str | None] = mapped_column(String(500))
    kapanis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class RentalItem(Base, PkMixin, TimestampMixin, ActorMixin):
    """Kiralama kalemi: ürün + istenen adet."""

    __tablename__ = "rental_items"
    __table_args__ = (
        UniqueConstraint("rental_id", "product_id", name="uq_ritem_urun"),
        CheckConstraint("qty > 0", name="ck_ritem_adet"),
    )

    rental_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rentals.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    qty: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(300))


class RentalContact(Base, PkMixin, TimestampMixin, ActorMixin):
    """Kiralama irtibatı = müşterinin `contacts` kaydı (kişi müşterinin kişisi
    olmalı — servis kuralı). Değişiklik denetimde `is_personal_data=True`."""

    __tablename__ = "rental_contacts"
    __table_args__ = (
        UniqueConstraint("rental_id", "contact_id", "rol", name="uq_rcontact"),
        CheckConstraint(_in("rol", IRTIBAT_ROLLERI), name="ck_rcontact_rol"),
    )

    rental_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rentals.id", ondelete="CASCADE"))
    contact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contacts.id", ondelete="RESTRICT")
    )
    rol: Mapped[str] = mapped_column(String(20))


class RentalAllocation(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """Tahsis: kalemin hangi depodan, hangi cihaz/kaç adetle karşılandığı (E06-04).

    Seri cihazda `qty=1`; toplu üründe adet. Sevk/iade/kayıp sayaçları
    tamamlanma koşulunun kaynağıdır: her AKTİF tahsiste
    `iade_adet + kayip_adet = sevk_adet` olunca kiralama depoya alınmış sayılır.
    """

    __tablename__ = "rental_allocations"
    __table_args__ = (
        CheckConstraint(
            "(asset_id IS NOT NULL AND qty = 1) OR (asset_id IS NULL AND qty > 0)",
            name="ck_rtahsis_seri_adet",
        ),
        CheckConstraint("sevk_adet >= 0 AND sevk_adet <= qty", name="ck_rtahsis_sevk"),
        CheckConstraint(
            "iade_adet >= 0 AND kayip_adet >= 0 AND iade_adet + kayip_adet <= sevk_adet",
            name="ck_rtahsis_iade",
        ),
        CheckConstraint(_in("durum", TAHSIS_DURUMLARI), name="ck_rtahsis_durum"),
        CheckConstraint("bitis > baslangic", name="ck_rtahsis_tarih"),
        # M10.1: çifte rezervasyon uyarı + gerekçe ile serbest; EXCLUDE kısıtı
        # yerine çakışma sorgusuna hizmet eden aynı ifadeli GiST indeksi.
        Index(
            "ix_rtahsis_cihaz_aralik",
            "asset_id",
            _TAHSIS_ARALIGI,
            postgresql_using="gist",
            postgresql_where=text("asset_id IS NOT NULL AND durum = 'AKTIF'"),
        ),
        Index("ix_rtahsis_urun_depo", "product_id", "from_warehouse_id", "durum"),
        Index("ix_rtahsis_kiralama", "rental_id"),
    )

    rental_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rentals.id", ondelete="RESTRICT")
    )
    rental_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rental_items.id", ondelete="RESTRICT")
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_assets.id", ondelete="RESTRICT")
    )
    from_warehouse_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    qty: Mapped[int] = mapped_column(Integer)
    sevk_adet: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    iade_adet: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    kayip_adet: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    # Kiralamadan kopya; uzatmada güncellenir.
    baslangic: Mapped[date] = mapped_column(Date)
    bitis: Mapped[date] = mapped_column(Date)
    durum: Mapped[str] = mapped_column(String(10), server_default=text("'AKTIF'"), default="AKTIF")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sahada cihaz değişimi izi (E06-20).
    replaced_allocation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_allocations.id", ondelete="SET NULL")
    )
    # Karekodla teslim okutma (KARARLAR 2026-11-20 §3): gidişte müşteriye,
    # dönüşte depoya teslim alındığı telefondan okutulup kapatılır.
    gidis_teslim_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gidis_teslim_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    donus_teslim_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    donus_teslim_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class RentalCheck(Base, PkMixin, TimestampMixin, ActorMixin):
    """Dönüş kontrol kaydı (E06-11): UYGUN dışında açıklama zorunlu. ARIZALI
    seri cihaz atölye kabul fonksiyonuyla (KIRALAMA_TAKIP) atölyeye gider."""

    __tablename__ = "rental_checks"
    __table_args__ = (
        CheckConstraint(_in("sonuc", KONTROL_SONUCLARI), name="ck_rkontrol_sonuc"),
        CheckConstraint(
            "sonuc = 'UYGUN' OR length(trim(coalesce(aciklama, ''))) > 0",
            name="ck_rkontrol_aciklama",
        ),
        CheckConstraint("asset_id IS NULL OR qty = 1", name="ck_rkontrol_seri_adet"),
        CheckConstraint("qty > 0", name="ck_rkontrol_adet"),
        Index("ix_rkontrol_urun_depo", "product_id", "warehouse_id"),
    )

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_assets.id", ondelete="RESTRICT")
    )
    warehouse_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    qty: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    sonuc: Mapped[str] = mapped_column(String(10))
    aciklama: Mapped[str | None] = mapped_column(String(500))
    rental_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rentals.id", ondelete="RESTRICT")
    )
    workshop_record_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("workshop_records.id", ondelete="SET NULL")
    )


class RentalInventoryMovement(Base, PkMixin, TimestampMixin, ActorMixin):
    """Kiralık envanter hareket defteri — EKLEME-YALNIZ (E06-03).

    Tek yazıcı `kiralik_envanter.hareket_yaz()`; düzeltme ters hareketle
    (`reverses_id`, bir hareket yalnız bir kez ters çevrilir). İş kolonları
    `trg_rhareket_degismez` ile UPDATE/DELETE'e kapalıdır (yalnız
    `created_by/updated_by/updated_at` değişebilir).

    Toplu bakiye: Σqty[to_depo, to_durum] − Σqty[from_depo, from_durum]
    (asset_id IS NULL). KIRADA/KAYIP için depo NULL.
    """

    __tablename__ = "rental_inventory_movements"
    __table_args__ = (
        CheckConstraint(_in("kind", KIRALIK_HAREKET_TURLERI), name="ck_rhareket_tur"),
        CheckConstraint("qty > 0", name="ck_rhareket_adet"),
        CheckConstraint("asset_id IS NULL OR qty = 1", name="ck_rhareket_seri_adet"),
        CheckConstraint(
            "("
            + _in("from_durum", KIRALIK_DURUMLARI, bos=True)
            + ") AND ("
            + _in("to_durum", KIRALIK_DURUMLARI, bos=True)
            + ")",
            name="ck_rhareket_durumlar",
        ),
        CheckConstraint("reverses_id <> id", name="ck_rhareket_kendini_ceviremez"),
        Index(
            "uq_rhareket_ters",
            "reverses_id",
            unique=True,
            postgresql_where=text("reverses_id IS NOT NULL"),
        ),
        Index("ix_rhareket_giris", "product_id", "to_warehouse_id", "to_durum"),
        Index("ix_rhareket_cikis", "product_id", "from_warehouse_id", "from_durum"),
        Index("ix_rhareket_cihaz", "asset_id", "at"),
        Index("ix_rhareket_kiralama", "rental_id"),
    )

    # Clock'tan (FakeClock ile sınanabilsin).
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16))
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_assets.id", ondelete="RESTRICT")
    )
    qty: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    from_warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    to_warehouse_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    from_durum: Mapped[str | None] = mapped_column(String(16))
    to_durum: Mapped[str | None] = mapped_column(String(16))
    rental_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rentals.id", ondelete="RESTRICT")
    )
    allocation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_allocations.id", ondelete="RESTRICT")
    )
    check_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_checks.id", ondelete="RESTRICT")
    )
    reverses_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_inventory_movements.id", ondelete="RESTRICT")
    )
    note: Mapped[str | None] = mapped_column(String(300))


class RentalEvent(Base, PkMixin, TimestampMixin, ActorMixin):
    """Kiralama olay geçmişi — ekleme-yalnız. Aşama geri alma son olayı
    `geri_alinan_event_id` ile işaretler (bir olay yalnız bir kez geri alınır).
    `eski/yeni` yalnız durum/tarih/sorumlu taşır; kişisel veri YAZILMAZ."""

    __tablename__ = "rental_events"
    __table_args__ = (
        CheckConstraint(_in("tur", KIRALAMA_OLAY_TURLERI), name="ck_revent_tur"),
        Index(
            "uq_revent_geri_alma",
            "geri_alinan_event_id",
            unique=True,
            postgresql_where=text("geri_alinan_event_id IS NOT NULL"),
        ),
        Index("ix_revent_kiralama", "rental_id", "at"),
    )

    rental_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rentals.id", ondelete="RESTRICT")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tur: Mapped[str] = mapped_column(String(12))
    onceki_durum: Mapped[str | None] = mapped_column(String(20))
    yeni_durum: Mapped[str | None] = mapped_column(String(20))
    alan: Mapped[str | None] = mapped_column(String(40))
    eski: Mapped[dict | None] = mapped_column(JSONB)
    yeni: Mapped[dict | None] = mapped_column(JSONB)
    service_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="SET NULL")
    )
    ekip_user_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    gerekce: Mapped[str | None] = mapped_column(String(500))
    geri_alinan_event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_events.id", ondelete="RESTRICT")
    )


class RentalCount(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    """Kiralama deposu fiziksel sayımı (E06-22 b, TS-195; Dalga 3, D3-S).

    Depo başına tek AÇIK sayım (`uq_rsayim_acik`). **Onaysız sayım hiçbir
    durumu/bakiyeyi değiştirmez**; fark (`GET .../fark`) okuma anında hareket
    defterinden hesaplanır ve saklanmaz. Onayda yalnız onaylı satırlar
    `kind=SAYIM` hareketi yazar (eksik seri → KAYIP, toplu fark → düzeltme);
    yazım tek yazıcı `kiralik_envanter.hareket_yaz()` üzerindendir. Durum
    `KIRALIK_SAYIM` makinesiyle ilerler. Numara üretilmez (iç belge).
    """

    __tablename__ = "rental_counts"
    __table_args__ = (
        CheckConstraint(_in("durum", KIRALIK_SAYIM_DURUMLARI), name="ck_rsayim_durum"),
        CheckConstraint(
            "durum <> 'ONAYLANDI' OR (onaylayan_id IS NOT NULL AND onay_at IS NOT NULL)",
            name="ck_rsayim_onay",
        ),
        CheckConstraint(
            "durum <> 'IPTAL' OR length(trim(coalesce(iptal_gerekcesi, ''))) > 0",
            name="ck_rsayim_iptal",
        ),
        Index(
            "uq_rsayim_acik",
            "warehouse_id",
            unique=True,
            postgresql_where=text("durum = 'ACIK' AND NOT is_deleted"),
        ),
    )

    warehouse_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    durum: Mapped[str] = mapped_column(String(12), server_default=text("'ACIK'"), default="ACIK")
    # Clock'tan (sayım başlangıcı; fark bu andan sonraki hareketleri ayrıca gösterir).
    baslangic_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    onaylayan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    onay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    iptal_gerekcesi: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)


class RentalCountLine(Base, PkMixin, TimestampMixin, ActorMixin):
    """Sayım satırı — üç biçim (CHECK ile ayrışır, tekillik kısmi indekslerle):

    - **kayıtlı seri cihaz:** `asset_id` dolu, `sayilan_adet` 0/1;
    - **sistemde olmayan seri:** `asset_id` NULL, `serial_text` dolu (anahtar
      `serial_key`, tek normalizasyon fonksiyonu `normalize_seri`), adet 0/1;
    - **toplu ürün:** `asset_id` ve `serial_text` NULL, `sayilan_adet` ≥ 0.

    "Sistemde olup sayılmayan" satır AÇILMAZ; farkta hesaplanır.
    """

    __tablename__ = "rental_count_lines"
    __table_args__ = (
        CheckConstraint("sayilan_adet >= 0", name="ck_rsayim_satir_adet"),
        CheckConstraint(
            "asset_id IS NULL OR serial_text IS NULL", name="ck_rsayim_satir_tek_kimlik"
        ),
        CheckConstraint(
            "(asset_id IS NULL AND serial_text IS NULL) OR sayilan_adet IN (0, 1)",
            name="ck_rsayim_satir_seri_adet",
        ),
        Index(
            "uq_rsayim_satir_cihaz",
            "rental_count_id",
            "asset_id",
            unique=True,
            postgresql_where=text("asset_id IS NOT NULL"),
        ),
        Index(
            "uq_rsayim_satir_seri",
            "rental_count_id",
            "product_id",
            "serial_key",
            unique=True,
            postgresql_where=text("asset_id IS NULL AND serial_key IS NOT NULL"),
        ),
        Index(
            "uq_rsayim_satir_toplu",
            "rental_count_id",
            "product_id",
            unique=True,
            postgresql_where=text("asset_id IS NULL AND serial_key IS NULL"),
        ),
    )

    rental_count_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rental_counts.id", ondelete="CASCADE")
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT")
    )
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rental_assets.id", ondelete="RESTRICT")
    )
    serial_text: Mapped[str | None] = mapped_column(String(200))
    serial_key: Mapped[str | None] = mapped_column(String(200))
    sayilan_adet: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    notes: Mapped[str | None] = mapped_column(String(300))


# Seri anahtarı tek normalizasyon fonksiyonundan (servis işi `seri_norm` ile aynı).
@event.listens_for(RentalAsset, "before_insert")
@event.listens_for(RentalAsset, "before_update")
def _kiralik_seri_anahtari(_mapper, _connection, target: RentalAsset) -> None:
    target.serial_no = (target.serial_no or "").strip()
    target.serial_key = _normalize.normalize_seri(target.serial_no)


@event.listens_for(RentalCountLine, "before_insert")
@event.listens_for(RentalCountLine, "before_update")
def _sayim_seri_anahtari(_mapper, _connection, target: RentalCountLine) -> None:
    metin = (target.serial_text or "").strip()
    target.serial_text = metin or None
    target.serial_key = _normalize.normalize_seri(metin) if metin else None


__all__ = [
    "IRTIBAT_ROLLERI",
    "KIRALAMA_DISI_BIRIMLER",
    "KIRALAMA_DURUMLARI",
    "KIRALAMA_OLAY_TURLERI",
    "KIRALAMA_SERVIS_TURLERI",
    "KIRALIK_DURUMLARI",
    "KIRALIK_HAREKET_TURLERI",
    "KIRALIK_SAYIM_DURUMLARI",
    "KONTROL_SONUCLARI",
    "TAHSIS_DURUMLARI",
    "Rental",
    "RentalAllocation",
    "RentalAsset",
    "RentalCatalogItem",
    "RentalCheck",
    "RentalContact",
    "RentalCount",
    "RentalCountLine",
    "RentalEvent",
    "RentalInventoryMovement",
    "RentalItem",
]
