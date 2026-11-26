"""Haberleşme atölyesi (E05): kabul, teşhis, onarım, test, onay, teslim, kargo.

**Tek karar: 1 atölye kaydı = 1 cihaz = 1 servis işi** (E05 §1.1). Eski
sistemdeki hataların ortak kökü atölye kaydıyla iş emrinin iki ayrı durum, iki
ayrı atama, iki ayrı seri taşımasıydı. Burada:

- İş kimliği, müşteri, birim, ATAMA, zaman, parça, bekleme, olay geçmişi ve
  ekler servis işindedir (`service_orders`, kategori ATOLYE).
  `service_order_id` NOT NULL + `uq_atolye_servis_isi` → 1:1.
- Seri/marka/model ekipman kütüğündedir (`service_equipment`, tek kaynak).
  Bileşik FK `fk_atolye_servis_ekipman` (`service_order_id`, `equipment_id`)
  → `service_orders(id, equipment_id)` ON UPDATE CASCADE: işin ekipmanı
  düzeltilince atölye kaydı da kendiliğinden izler, iki kaynak ayrışamaz.
- Garanti TARİHLERİ ekipmandadır; kayıt yalnız kabulde dondurulan durum ve
  bitiş anlık görüntüsünü taşır (RMA kalıbı, E05 kontrol B7).
- Arıza kategorisi ayrı liste değil, birim bazlı katalogdur
  (`service_fault_reasons`, HABERLESME tohumu; E05 kontrol B9).
- RMA köprüsü YOK (E05-24 revised): Denge'nin sattığı mobilite cihazı canlı
  RMA ekranından yürür.

Atölye durumu `ATOLYE` makinesiyle yalnız `services/teknik_servis/atolye.py`
içinden ilerler; servis işinin durumu eşlemeyle aynı transaction'da yürür.
`repair_amount` yalnız `sees_cost` (maliyet.gor) sahibine görünür/yazılır.
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
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
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


def _in(sutun: str, degerler: tuple[str, ...], *, bos: bool = False) -> str:
    liste = ", ".join(f"'{d}'" for d in degerler)
    return f"{sutun} IS NULL OR {sutun} IN ({liste})" if bos else f"{sutun} IN ({liste})"


# --- Sözlükler (E05 §2.1, kontrol düzeltmeleriyle) ------------------------------
# TEST_KONTROL ve KARGOYA_VERILDI ATÖLYE durumlarıdır; servis işinde yoktur
# (KD-13: servis işi atölyedeyken yalnız ATOLYEDE/BEKLEMEDE görünür).
ATOLYE_DURUMLARI = (
    "KABUL_EDILDI",
    "TESHISTE",
    "ONAY_BEKLIYOR",
    "ONARIMDA",
    "PARCA_BEKLIYOR",
    "DIS_SERVISTE",
    "TEST_KONTROL",
    "TESLIME_HAZIR",
    "ONARILMADAN_IADE",
    "KARGOYA_VERILDI",
    "TESLIM_EDILDI",
    "IPTAL",
)
ATOLYE_ACIK_OLMAYAN = ("TESLIM_EDILDI", "IPTAL")
# KIRALAMA_TAKIP: kiralık cihaz dönüş kontrolünden gelen kayıt (E05-27/TS-102).
ATOLYE_SERVIS_TURLERI = (
    "ARIZA_ONARIMI",
    "GARANTI_ONARIMI",
    "DIS_SERVIS",
    "YAZILIM_FREKANS",
    "KIRALAMA_TAKIP",
)
# Yalnız API `Literal`'i ve ekran listesi: ekipman `brand` serbest metindir,
# karşılaştırma büyük/küçük harf duyarsız (E05-20). Kolon/CHECK YOK.
ATOLYE_MARKALARI = ("HYTERA", "HYT", "HQT", "MOTOROLA", "KIRISUN", "ASELSAN", "DIGER")
ATOLYE_TESLIM_TIPLERI = ("ELDEN", "KARGO", "KURYE", "SAHA")
ATOLYE_GARANTI_DURUMLARI = ("GARANTI_ICI", "GARANTI_DISI", "ONARIM_GARANTISI", "BELIRSIZ")
ATOLYE_ONARIM_KATEGORILERI = (
    "PARCA_DEGISIMI",
    "LEHIM_KART_ONARIMI",
    "YAZILIM_YUKLEME",
    "FREKANS_PROGRAMLAMA",
    "TEMIZLIK_BAKIM",
    "AYAR_KALIBRASYON",
    "ISLEM_YAPILMADI",
    "DIGER",
)
ATOLYE_TEST_SONUCLARI = ("GECTI", "KALDI")
ATOLYE_ONAY_KARARLARI = ("ONAYLANDI", "REDDEDILDI", "ONAY_GEREKMEZ")
ATOLYE_ONAY_KANALLARI = ("TELEFON", "EPOSTA", "YAZILI", "TEKLIF")
# Sıra = kabul ekranındaki kutucuk sırası (2026-11-24 sahip listesi; eski
# türler KILIF/HARICI_MIKROFON/KABLO sahip kararıyla seçilebilir kalır).
# Kodlar değişmez: SARJ_UNITESI "Şarj yuvası", SARJ_ADAPTORU "Adaptör",
# KEMER_KLIPSI "Klips" olarak yalnız ADI değişti (eski kayıtlar bozulmaz).
AKSESUAR_TURLERI = (
    "SARJ_ADAPTORU",
    "SARJ_UNITESI",
    "SARJ_KABLOSU",
    "SARJ_TAKIMI",
    "BATARYA",
    "ASKI_IPI",
    "ANTEN",
    "KAPAK",
    "KEMER_KLIPSI",
    "SIM",
    "KUTU",
    "SPEAKER_MIKROFON",
    "KULAKLIK",
    "KILIF",
    "HARICI_MIKROFON",
    "KABLO",
    "DIGER",
)

_ACIK_KAYIT = "status NOT IN ('TESLIM_EDILDI', 'IPTAL') AND NOT is_deleted"


class WorkshopRecord(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Atölye kaydı (TS-090). Zaman damgaları sunucu Clock'undan; istemciden
    alınmaz (M05-13). `completed_at` ilk TESLIME_HAZIR/ONARILMADAN_IADE'de bir
    kez yazılır. Kişisel veri: `delivered_to_name`, `approved_by_name` (KVKK
    anonimleştirme kapsamı; olay geçmişine YAZILMAZ)."""

    __tablename__ = "workshop_records"
    __table_args__ = (
        UniqueConstraint("atolye_no", name="uq_atolye_no"),
        UniqueConstraint("service_order_id", name="uq_atolye_servis_isi"),
        UniqueConstraint("source_system", "source_ref", name="uq_atolye_kaynak"),
        ForeignKeyConstraint(
            ["service_order_id", "equipment_id"],
            ["service_orders.id", "service_orders.equipment_id"],
            name="fk_atolye_servis_ekipman",
            onupdate="CASCADE",
        ),
        CheckConstraint(_in("service_type", ATOLYE_SERVIS_TURLERI), name="ck_atolye_servis_turu"),
        CheckConstraint(_in("status", ATOLYE_DURUMLARI), name="ck_atolye_durum"),
        CheckConstraint(_in("receive_type", ATOLYE_TESLIM_TIPLERI), name="ck_atolye_kabul_tipi"),
        CheckConstraint(_in("warranty_status", ATOLYE_GARANTI_DURUMLARI), name="ck_atolye_garanti"),
        CheckConstraint(
            _in("repair_category", ATOLYE_ONARIM_KATEGORILERI, bos=True), name="ck_atolye_onarim"
        ),
        CheckConstraint(_in("test_result", ATOLYE_TEST_SONUCLARI, bos=True), name="ck_atolye_test"),
        CheckConstraint(
            _in("approval_decision", ATOLYE_ONAY_KARARLARI, bos=True),
            name="ck_atolye_onay_karari",
        ),
        CheckConstraint(
            _in("approval_channel", ATOLYE_ONAY_KANALLARI, bos=True),
            name="ck_atolye_onay_kanali",
        ),
        CheckConstraint(
            "approval_decision IS DISTINCT FROM 'ONAY_GEREKMEZ' OR approval_note IS NOT NULL",
            name="ck_atolye_onay_gerekce",
        ),
        CheckConstraint("repair_amount IS NULL OR repair_amount >= 0", name="ck_atolye_bedel"),
        CheckConstraint(
            _in("delivery_type", ATOLYE_TESLIM_TIPLERI, bos=True), name="ck_atolye_teslim_tipi"
        ),
        CheckConstraint(
            "external_returned_at IS NULL OR external_sent_at IS NULL "
            "OR external_returned_at >= external_sent_at",
            name="ck_atolye_dis_servis_tarih",
        ),
        CheckConstraint(
            "status <> 'KARGOYA_VERILDI' OR (delivery_type = 'KARGO' "
            "AND cargo_tracking_no IS NOT NULL AND cargo_company IS NOT NULL)",
            name="ck_atolye_kargo",
        ),
        CheckConstraint(
            "status <> 'TESLIM_EDILDI' OR (delivered_to_name IS NOT NULL "
            "AND delivered_at IS NOT NULL AND delivery_type IS NOT NULL)",
            name="ck_atolye_teslim",
        ),
        CheckConstraint(
            "status NOT IN ('TESLIME_HAZIR', 'ONARILMADAN_IADE', 'KARGOYA_VERILDI', "
            "'TESLIM_EDILDI') OR completed_at IS NOT NULL",
            name="ck_atolye_tamamlanma",
        ),
        # Aynı cihaza ikinci AÇIK kayıt DB'de de engelli (M05-06); servis
        # önce sorar ve mevcut `atolye_no` ile 409 döner.
        Index(
            "uq_atolye_acik_ekipman",
            "equipment_id",
            unique=True,
            postgresql_where=text(_ACIK_KAYIT),
        ),
        Index("ix_atolye_durum", "status", "received_at"),
        Index(
            "ix_atolye_tahmini_bitis",
            "estimated_finish_date",
            postgresql_where=text(_ACIK_KAYIT),
        ),
        Index("ix_atolye_grup", "intake_group_no"),
    )

    # AT-YYYYAA-NNNNNN (`atolye_no_seq`, plan §1.6).
    atolye_no: Mapped[str] = mapped_column(String(24))
    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_equipment.id", ondelete="RESTRICT")
    )
    # Toplu kabul grubu (salt sayı, `atolye_kabul_grubu_seq`): N cihaz, N kayıt,
    # N servis işi, tek fiş (TS-100).
    intake_group_no: Mapped[int | None] = mapped_column(BigInteger)
    service_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'KABUL_EDILDI'"), default="KABUL_EDILDI"
    )

    # --- Kabul --------------------------------------------------------------
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    receive_type: Mapped[str] = mapped_column(String(10))
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id", ondelete="SET NULL")
    )
    customer_complaint: Mapped[str] = mapped_column(Text)
    physical_condition: Mapped[str | None] = mapped_column(Text)
    estimated_finish_date: Mapped[date | None] = mapped_column(Date)
    # Kabulde HESAPLANIR ve DONDURULUR; tarihler ekipmanda (tek kaynak).
    warranty_status: Mapped[str] = mapped_column(
        String(20), server_default=text("'BELIRSIZ'"), default="BELIRSIZ"
    )
    warranty_end_snapshot: Mapped[date | None] = mapped_column(Date)

    # --- Teşhis / onarım / test ------------------------------------------------
    fault_reason_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_fault_reasons.id", ondelete="RESTRICT")
    )
    diagnosis_note: Mapped[str | None] = mapped_column(Text)
    diagnosed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    diagnosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_repairable: Mapped[bool | None] = mapped_column(Boolean)
    repair_category: Mapped[str | None] = mapped_column(String(30))
    repair_note: Mapped[str | None] = mapped_column(Text)
    test_result: Mapped[str | None] = mapped_column(String(10))
    tested_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Müşteri onayı (ücretli onarım, TS-094) ---------------------------------
    approval_decision: Mapped[str | None] = mapped_column(String(16))
    approval_channel: Mapped[str | None] = mapped_column(String(10))
    approved_by_name: Mapped[str | None] = mapped_column(String(120))
    approval_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)
    # Fiyat alanı: yalnız `sees_cost` okur/yazar; yetkisizde anahtar YOK (TS-092).
    repair_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # --- Teslim / kargo -----------------------------------------------------
    delivery_type: Mapped[str | None] = mapped_column(String(10))
    cargo_company: Mapped[str | None] = mapped_column(String(60))
    cargo_tracking_no: Mapped[str | None] = mapped_column(String(60))
    cargo_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_to_name: Mapped[str | None] = mapped_column(String(120))
    delivery_note: Mapped[str | None] = mapped_column(Text)

    # --- Dış servis (üretici/distribütör; RMA köprüsü yok) ------------------------
    external_vendor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    external_rma_no: Mapped[str | None] = mapped_column(String(60))
    external_sent_at: Mapped[date | None] = mapped_column(Date)
    external_returned_at: Mapped[date | None] = mapped_column(Date)

    # --- Eski alanlar (yalnız serbest metin; Logo CRM kapsam dışı) ----------------
    logo_form_no: Mapped[str | None] = mapped_column(String(80))
    logo_main_service_no: Mapped[str | None] = mapped_column(String(80))
    integration_company: Mapped[str | None] = mapped_column(String(150))
    project_name: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(Text)

    # Kiralık cihaz köprüsü (TS-102; kolon d2a000000007'de açılır).
    rental_asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("rental_assets.id", ondelete="SET NULL", name="fk_atolye_kiralik_cihaz"),
    )


class WorkshopAccessory(Base, PkMixin, TimestampMixin, ActorMixin):
    """Kabulde alınan aksesuar satırı (eski `Accessory1..5` kaldırıldı; satır
    sayısı sınırsız). Teslimde `returned` işaretlenir; teslimden sonra satırlar
    kilitlidir (servis 409)."""

    __tablename__ = "workshop_accessories"
    __table_args__ = (
        CheckConstraint(_in("kind", AKSESUAR_TURLERI), name="ck_atolye_aksesuar_tur"),
        CheckConstraint(
            "kind <> 'DIGER' OR description IS NOT NULL", name="ck_atolye_aksesuar_aciklama"
        ),
        CheckConstraint("qty > 0", name="ck_atolye_aksesuar_adet"),
        Index("ix_atolye_aksesuar_kayit", "workshop_record_id"),
    )

    workshop_record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workshop_records.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(String(120))
    qty: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    # NULL = teslimde henüz işaretlenmedi.
    returned: Mapped[bool | None] = mapped_column(Boolean)
    return_note: Mapped[str | None] = mapped_column(String(300))


class AtolyeModeli(Base, PkMixin, TimestampMixin, ActorMixin):
    """Kabul ekranındaki model listesi (2026-11-24 sahip kararı).

    Marka başına model adları; `atolye.model_ekle` izni olan kullanıcı listede
    olmayan modeli kabul ekranından ekler. Marka, kütükte yazıldığı gibidir
    (telsiz birimlerinde sözlük kodu, ör. HYTERA; "Diğer" markada gerçek ad).
    Liste yalnız seçim kolaylığıdır: kabul serbest model metnini yine kabul
    eder (eski kayıtlar ve içe aktarma bozulmasın)."""

    __tablename__ = "atolye_modelleri"
    __table_args__ = (
        Index("uq_atolye_modeli", text("lower(marka)"), text("lower(model)"), unique=True),
    )

    marka: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(80))


__all__ = [
    "AKSESUAR_TURLERI",
    "AtolyeModeli",
    "ATOLYE_ACIK_OLMAYAN",
    "ATOLYE_DURUMLARI",
    "ATOLYE_GARANTI_DURUMLARI",
    "ATOLYE_MARKALARI",
    "ATOLYE_ONARIM_KATEGORILERI",
    "ATOLYE_ONAY_KANALLARI",
    "ATOLYE_ONAY_KARARLARI",
    "ATOLYE_SERVIS_TURLERI",
    "ATOLYE_TESLIM_TIPLERI",
    "ATOLYE_TEST_SONUCLARI",
    "WorkshopAccessory",
    "WorkshopRecord",
]
