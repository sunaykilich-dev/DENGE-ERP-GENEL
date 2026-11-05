"""Planlı bakım: sözleşme, kapsam cihazı, dönem, üretim turu, dijital form,
ziyaret, uygunsuzluk ve kapsam dışı talebi (E04).

**1 cihaz = 1 PB iş emri** (korunacak iş kararı). Kullanıcı "2 X-Ray +
3 Kapı Dedektörü" girer; servis bunu 5 KALEM satırına açar — her satır bir
fiziksel cihazdır. Böylece kural tek bir kısmi tekil indeksle zorlanır
(`service_orders.uq_so_pb_cihaz_donem` = kalem + dönem).

**Dönem sayacı SAKLANMAZ:** "yapılan dönem (n/frekans)" döngüdeki kapanmış
dönemlerden sayılır. Saklanan sayaç yıl devrinde sıfırlanmayı ya da yanlış
devri unutan her yolda yanlış kalırdı.

**Sözleşme döngüsü takvim yılı değildir:** dönem anahtarı `valid_from + k yıl`
(`cycle_start`); 01.06 başlangıçlı sözleşmede ocak ayı hâlâ ilk döngüdür.

**Tarihsiz kayıt uydurulmaz:** tarihi bilinmeyen göç sözleşmesi
`TEYIT_BEKLIYOR` + NULL tarihle gelir; kalem EXCLUDE'u tarihsiz satırı
kapsamaz (sonsuz aralık her şeyle çakışırdı).

Ücret alanları (`fee_per_visit`, `contract_total`, `legacy_fee_text`)
`sees_cost` false iken yanıtta ANAHTAR OLARAK YOKTUR.
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
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, ExcludeConstraint
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


def _in(sutun: str, degerler: tuple[str, ...], *, bos: bool = False) -> str:
    liste = ", ".join(f"'{d}'" for d in degerler)
    return f"{sutun} IS NULL OR {sutun} IN ({liste})" if bos else f"{sutun} IN ({liste})"


BAKIM_SOZLESME_DURUMLARI = ("TASLAK", "TEYIT_BEKLIYOR", "AKTIF", "PASIF")
# Yeni tür ancak kontrol şablonu verildiğinde (E04-22, ertelendi) eklenir.
BAKIM_CIHAZ_TURLERI = ("XRAY", "KAPI_DEDEKTORU")
DONEM_KAPANIS_TURLERI = ("TAMAMLANDI", "KISMI", "YAPILAMADI", "GOC_BASLANGIC")
# Döngü sayacına giren kapanışlar (sayaç saklanmaz, bunlardan sayılır).
DONEM_SAYILAN_KAPANISLAR = frozenset({"TAMAMLANDI", "KISMI", "GOC_BASLANGIC"})
URETIM_TETIKLERI = ("ELLE", "WORKER", "EKSIK_TAMAMLA", "TOPLU_AC")
BAKIM_SONUCLARI = ("TAMAMLANDI", "UYGUNSUZLUK_VAR", "KONTROL_EDILEMEDI", "TEKRAR_GIDILECEK")
BAKIM_FORM_DURUMLARI = ("TASLAK", "TAMAMLANDI")
KONTROL_SONUCLARI = ("BEKLIYOR", "UYGUN", "UYGUNSUZ", "KONTROL_EDILEMEDI")
BAKIM_ZIYARET_TURLERI = ("TAMAMLAMA", "YENIDEN_ACMA")
UYGUNSUZLUK_AKSIYONLARI = ("YERINDE_GIDERILDI", "TEKLIF", "ARIZA_IS_EMRI", "MUSTERI_KAYNAKLI")
# Uygunsuzluk önemi (rol testi tur 2, 5_teknisyen B3): servis işi öncelik
# sözlüğüyle hizalı + DUSUK; KRİTİK bulgudan açılan arıza işi KRİTİK öncelikli.
UYGUNSUZLUK_ONEMLERI = ("DUSUK", "NORMAL", "YUKSEK", "KRITIK")
# Bakım formu ölçüm alanları (opsiyonel, sayısal, birimli): alan → (etiket, birim).
BAKIM_OLCUMLERI: dict[str, tuple[str, str]] = {
    "olcum_kv": ("Jeneratör gerilimi", "kV"),
    "olcum_ma": ("Jeneratör akımı", "mA"),
    "olcum_penetrasyon_mm": ("Penetrasyon", "mm"),
    "olcum_doz_usv": ("Doz (yüzey/tünel)", "µSv/h"),
    "olcum_voltaj_v": ("Besleme voltajı (AC)", "V"),
}
UYGUNSUZLUK_DURUMLARI = ("ACIK", "KAPALI")
KAPSAM_DISI_NEDENLERI = ("SOKULMUS", "ERISIM_YOK", "TASINMIS", "MUSTERI_IPTAL")
KAPSAM_DISI_DURUMLARI = ("TALEP", "ONAYLANDI", "REDDEDILDI")
KUTUK_FARK_DURUMLARI = ("ACIK", "UYGULANDI", "YOK_SAYILDI")

_KALEM_ARALIGI = literal_column("tstzrange(valid_from, valid_to, '[)')")


class MaintenanceContract(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Bakım sözleşmesi. Numara `BAKIM-NNNN` (`seq_bakim_sozlesme_no`);
    göçteki `BAKIM-00NN` korunur, sequence göçten sonra `setval(max)`.

    Sözleşme tarafı = cari (`account_id`); gidilen yer = tesis (`address_id`).
    İkisi farklı olabilir (E14-11): PB işinin lokasyonu tesis olur, carinin
    merkez adresi DEĞİL. `account_id` yalnız TEYIT_BEKLIYOR'da boş olabilir.
    """

    __tablename__ = "maintenance_contracts"
    __table_args__ = (
        UniqueConstraint("contract_no", name="uq_mc_no"),
        UniqueConstraint("source_system", "source_ref", name="uq_mc_kaynak"),
        CheckConstraint(birim_check("birim"), name="ck_mc_birim"),
        CheckConstraint(_in("status", BAKIM_SOZLESME_DURUMLARI), name="ck_mc_durum"),
        CheckConstraint(
            "account_id IS NOT NULL OR status = 'TEYIT_BEKLIYOR'", name="ck_mc_musteri_teyit"
        ),
        CheckConstraint("valid_to > valid_from", name="ck_mc_aralik"),
        CheckConstraint(
            "status <> 'AKTIF' OR (valid_from IS NOT NULL AND valid_to IS NOT NULL "
            "AND annual_frequency IS NOT NULL)",
            name="ck_mc_aktif_tarih",
        ),
        CheckConstraint("annual_frequency BETWEEN 1 AND 12", name="ck_mc_frekans"),
        CheckConstraint(
            "fixed_months IS NULL OR (cardinality(fixed_months) = annual_frequency "
            "AND fixed_months <@ ARRAY[1,2,3,4,5,6,7,8,9,10,11,12]::smallint[])",
            name="ck_mc_sabit_ay",
        ),
        CheckConstraint(
            "status <> 'TEYIT_BEKLIYOR' OR teyit_gerekcesi IS NOT NULL",
            name="ck_mc_teyit_gerekce",
        ),
        CheckConstraint(
            "(fee_per_visit IS NULL OR fee_per_visit >= 0) "
            "AND (contract_total IS NULL OR contract_total >= 0)",
            name="ck_mc_ucret",
        ),
        Index("ix_mc_musteri", "account_id"),
        Index("ix_mc_durum_bitis", "status", "valid_to"),
        Index("ix_mc_adres", "address_id"),
    )

    contract_no: Mapped[str] = mapped_column(String(30))
    birim: Mapped[str] = mapped_column(
        String(20), server_default=text("'GUVENLIK'"), default="GUVENLIK"
    )
    account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    customer_name_raw: Mapped[str | None] = mapped_column(String(250))
    site_name_raw: Mapped[str | None] = mapped_column(String(250))
    address_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("addresses.id", ondelete="SET NULL")
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id", ondelete="SET NULL")
    )
    responsible_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sözleşme karar tarihi (yerel gün). Verildiğinde başlangıç bu gün olur;
    # bakım ayları buradan yıllık adede göre hesaplanır (`bakim_karar`).
    decision_date: Mapped[date | None] = mapped_column(Date)
    annual_frequency: Mapped[int | None] = mapped_column(SmallInteger)
    fixed_months: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'TASLAK'"), default="TASLAK"
    )
    teyit_gerekcesi: Mapped[str | None] = mapped_column(Text)
    # --- Ücret (yalnız sees_cost) ---
    fee_per_visit: Mapped[float | None] = mapped_column(Numeric(14, 2))
    contract_total: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'TRY'"), default="TRY")
    legacy_fee_text: Mapped[str | None] = mapped_column(Text)
    # --- Eski serbest metinler (salt okunur iz) ---
    legacy_products_text: Mapped[str | None] = mapped_column(Text)
    legacy_period_text: Mapped[str | None] = mapped_column(Text)
    legacy_frequency_text: Mapped[str | None] = mapped_column(Text)
    legacy_completed_count: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)


class MaintenanceContractItem(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Kapsam kalemi = 1 fiziksel cihaz.

    Ekipman bağı NULL olabilir (ilk eşleştirme şef onayıyla, TS-063); PB
    yalnız `equipment_id` dolu ve `pb_uygun` kalemde üretilir. FK RESTRICT:
    SET NULL, bağlı ekipman silinince PB zincirini sessizce koparırdı.
    Aynı ekipman aynı anda iki sözleşmede kapsamda olamaz
    (`ex_mci_ekipman_cakisma`). Adet azaltma satırı silmez, `valid_to` yazar;
    yeni kalemin `sira`sı kapalılar dahil max+1 verilir.
    """

    __tablename__ = "maintenance_contract_items"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_mci_kaynak"),
        CheckConstraint(_in("equipment_type", BAKIM_CIHAZ_TURLERI), name="ck_mci_tur"),
        CheckConstraint("sira >= 1", name="ck_mci_sira"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_mci_aralik"),
        CheckConstraint("valid_from IS NOT NULL OR valid_to IS NULL", name="ck_mci_tarihsiz_acik"),
        Index(
            "uq_mci_sira",
            "contract_id",
            "equipment_type",
            "sira",
            unique=True,
            postgresql_where=text("NOT is_deleted"),
        ),
        ExcludeConstraint(
            ("equipment_id", "="),
            (_KALEM_ARALIGI, "&&"),
            name="ex_mci_ekipman_cakisma",
            using="gist",
            where=text("valid_from IS NOT NULL AND equipment_id IS NOT NULL AND NOT is_deleted"),
        ),
        Index("ix_mci_ekipman", "equipment_id"),
    )

    contract_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maintenance_contracts.id", ondelete="CASCADE"), index=True
    )
    equipment_type: Mapped[str] = mapped_column(String(30))
    sira: Mapped[int] = mapped_column(SmallInteger)
    equipment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_equipment.id", ondelete="RESTRICT")
    )
    pb_uygun: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MaintenanceGenerationRun(Base, PkMixin, TimestampMixin, ActorMixin):
    """PB üretim turu — DEĞİŞMEZ. `created_by` NULL = worker.

    Atlanan sözleşmeler gerekçesiyle (`skipped`: SURESI_DOLMUS, EKIPMAN_YOK,
    SABLON_YOK ...) saklanır: "neden PB açılmadı" sorusu sonradan
    cevaplanabilsin.
    """

    __tablename__ = "maintenance_generation_runs"
    __table_args__ = (CheckConstraint(_in("tetik", URETIM_TETIKLERI), name="ck_mgr_tetik"),)

    tetik: Mapped[str] = mapped_column(String(16))
    generated_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    skipped: Mapped[list | None] = mapped_column(JSONB)
    parametreler: Mapped[dict | None] = mapped_column(JSONB)


class MaintenancePeriod(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Bakım dönemi. Hedef tarih elle değiştirilirse gerekçe zorunlu ve bir
    daha yeniden hesaplanmaz (`target_manual`)."""

    __tablename__ = "maintenance_periods"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_mp_kaynak"),
        UniqueConstraint("contract_id", "cycle_start", "sequence_no", name="uq_mp_donem"),
        CheckConstraint("sequence_no >= 1", name="ck_mp_sira"),
        CheckConstraint(
            "NOT target_manual OR target_change_reason IS NOT NULL", name="ck_mp_elle_gerekce"
        ),
        CheckConstraint(_in("closing_kind", DONEM_KAPANIS_TURLERI, bos=True), name="ck_mp_kapanis"),
        CheckConstraint("(closed_at IS NULL) = (closing_kind IS NULL)", name="ck_mp_kapanis_cift"),
        Index("ix_mp_hedef", "target_date"),
    )

    contract_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maintenance_contracts.id", ondelete="CASCADE"), index=True
    )
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sequence_no: Mapped[int] = mapped_column(SmallInteger)
    target_date: Mapped[date] = mapped_column(Date)
    target_manual: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    target_change_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closing_kind: Mapped[str | None] = mapped_column(String(16))
    generation_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maintenance_generation_runs.id", ondelete="SET NULL")
    )


class MaintenanceForm(Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin):
    """PB işinin dijital bakım formu (iş başına bir).

    PB serisi `service_order_serials`'ta tutulur (tek kaynak, E04 kontrol #8);
    form yalnız sahada görülen bölgeyi ve kütük farkını taşır. Şablon maddeleri
    üretimde forma KOPYALANIR: şablon sonradan değişse de eski formun metni
    değişmez. Tamamlayan kişi KİMLİKTİR (`completed_by`), ad metni değil.
    """

    __tablename__ = "maintenance_forms"
    __table_args__ = (
        UniqueConstraint("service_order_id", name="uq_mf_is_emri"),
        CheckConstraint(_in("status", BAKIM_FORM_DURUMLARI), name="ck_mf_durum"),
        CheckConstraint(_in("bakim_sonucu", BAKIM_SONUCLARI, bos=True), name="ck_mf_sonuc"),
        CheckConstraint(
            _in("kutuk_fark_durumu", KUTUK_FARK_DURUMLARI, bos=True), name="ck_mf_kutuk_fark"
        ),
        CheckConstraint(
            "status <> 'TAMAMLANDI' OR (bakim_sonucu IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_mf_tamamlama",
        ),
        CheckConstraint(
            "coalesce(olcum_kv, 0) >= 0 AND coalesce(olcum_ma, 0) >= 0 "
            "AND coalesce(olcum_penetrasyon_mm, 0) >= 0 AND coalesce(olcum_doz_usv, 0) >= 0 "
            "AND coalesce(olcum_voltaj_v, 0) >= 0",
            name="ck_mf_olcum_negatif",
        ),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="CASCADE")
    )
    template_code: Mapped[str] = mapped_column(String(30))
    template_version: Mapped[int] = mapped_column(SmallInteger)
    zone: Mapped[str | None] = mapped_column(String(120))
    kutuk_fark_durumu: Mapped[str | None] = mapped_column(String(12))
    performed_work: Mapped[str | None] = mapped_column(Text)
    technician_note: Mapped[str | None] = mapped_column(Text)
    # Katalog dışı parça notu (stok parça kullanımı yedek parça modülünde).
    parts_text: Mapped[str | None] = mapped_column(Text)
    bakim_sonucu: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(12), server_default=text("'TASLAK'"), default="TASLAK"
    )
    completed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Ölçümler (f3a000000001; opsiyonel, NULL = ölçülmedi, 0 değil). Birimler
    # `BAKIM_OLCUMLERI`'nde; negatif değer `ck_mf_olcum_negatif` ile reddedilir.
    olcum_kv: Mapped[float | None] = mapped_column(Numeric(7, 2))
    olcum_ma: Mapped[float | None] = mapped_column(Numeric(7, 2))
    olcum_penetrasyon_mm: Mapped[float | None] = mapped_column(Numeric(7, 2))
    olcum_doz_usv: Mapped[float | None] = mapped_column(Numeric(9, 3))
    olcum_voltaj_v: Mapped[float | None] = mapped_column(Numeric(7, 2))


class MaintenanceFormCheck(Base, PkMixin, TimestampMixin, VersionedMixin):
    """Form kontrol maddesi. UYGUNSUZ ve KONTROL_EDILEMEDI not ister."""

    __tablename__ = "maintenance_form_checks"
    __table_args__ = (
        UniqueConstraint("form_id", "check_code", name="uq_mfc_madde"),
        CheckConstraint(_in("result", KONTROL_SONUCLARI), name="ck_mfc_sonuc"),
        CheckConstraint(
            "result NOT IN ('UYGUNSUZ', 'KONTROL_EDILEMEDI') "
            "OR length(trim(coalesce(note, ''))) > 0",
            name="ck_mfc_not_zorunlu",
        ),
        CheckConstraint(_in("onem", UYGUNSUZLUK_ONEMLERI, bos=True), name="ck_mfc_onem"),
    )

    form_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maintenance_forms.id", ondelete="CASCADE")
    )
    check_code: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(300))
    sira: Mapped[int] = mapped_column(SmallInteger)
    result: Mapped[str] = mapped_column(
        String(20), server_default=text("'BEKLIYOR'"), default="BEKLIYOR"
    )
    note: Mapped[str | None] = mapped_column(Text)
    checked_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Uygunsuz maddenin önemi (f3a000000001); tamamlamada aksiyona kopyalanır.
    onem: Mapped[str | None] = mapped_column(String(10))


class MaintenanceVisit(Base, PkMixin, TimestampMixin, ActorMixin):
    """Her başarılı tamamlama (ve yeniden açma) için DEĞİŞMEZ ziyaret satırı.

    Form yeniden açılıp düzeltilse de "o gün sahada ne kaydedildi" kanıtı
    kalır. Teknisyen kimlikle tutulur, ad tutulmaz.
    """

    __tablename__ = "maintenance_visits"
    __table_args__ = (
        UniqueConstraint("form_id", "visit_no", name="uq_mv_no"),
        CheckConstraint(_in("tur", BAKIM_ZIYARET_TURLERI), name="ck_mv_tur"),
        CheckConstraint(_in("bakim_sonucu", BAKIM_SONUCLARI, bos=True), name="ck_mv_sonuc"),
        CheckConstraint(
            "tur <> 'YENIDEN_ACMA' OR length(trim(coalesce(gerekce, ''))) > 0",
            name="ck_mv_acma_gerekce",
        ),
        Index("ix_mv_is", "service_order_id"),
    )

    form_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maintenance_forms.id", ondelete="RESTRICT")
    )
    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    visit_no: Mapped[int] = mapped_column(SmallInteger)
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    technician_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    tur: Mapped[str] = mapped_column(String(14))
    bakim_sonucu: Mapped[str | None] = mapped_column(String(20))
    serial_no: Mapped[str | None] = mapped_column(String(200))
    zone: Mapped[str | None] = mapped_column(String(120))
    performed_work: Mapped[str | None] = mapped_column(Text)
    checks: Mapped[list | None] = mapped_column(JSONB)
    approval_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_approvals.id", ondelete="SET NULL")
    )
    gerekce: Mapped[str | None] = mapped_column(Text)
    # Tamamlama anındaki ölçümler (değişmez kanıt; f3a000000001). NULL = ölçüm yok.
    olcumler: Mapped[dict | None] = mapped_column(JSONB)


class MaintenanceNonconformity(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin
):
    """Uygunsuzluk aksiyonu. Açık aksiyon varken PB TAMAMLANDI olamaz."""

    __tablename__ = "maintenance_nonconformities"
    __table_args__ = (
        CheckConstraint(_in("action_type", UYGUNSUZLUK_AKSIYONLARI, bos=True), name="ck_mnc_tur"),
        CheckConstraint(_in("status", UYGUNSUZLUK_DURUMLARI), name="ck_mnc_durum"),
        CheckConstraint(_in("onem", UYGUNSUZLUK_ONEMLERI, bos=True), name="ck_mnc_onem"),
        CheckConstraint(
            "status <> 'KAPALI' OR (closing_note IS NOT NULL AND closed_by IS NOT NULL "
            "AND closed_at IS NOT NULL)",
            name="ck_mnc_kapanis",
        ),
        Index("ix_mnc_is", "service_order_id"),
    )

    form_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maintenance_forms.id", ondelete="RESTRICT")
    )
    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    check_code: Mapped[str] = mapped_column(String(30))
    check_label: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    # Bulgunun önemi (f3a000000001); KRİTİK → bağlı arıza işi KRİTİK öncelik.
    onem: Mapped[str | None] = mapped_column(String(10))
    action_type: Mapped[str | None] = mapped_column(String(20))
    responsible_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    linked_service_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="SET NULL")
    )
    linked_quote_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quotes.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(10), server_default=text("'ACIK'"), default="ACIK")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    closing_note: Mapped[str | None] = mapped_column(Text)


class MaintenanceExclusionRequest(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin
):
    """Cihazın dönem dışı bırakılması talebi (E04-11).

    Kişi kendi talebini onaylayamaz (`ck_mer_kendi_onayi`). Onayda PB işi
    `durum_degistir(IPTAL, kaynak='kapsam_disi')` ile kapanır ve aynı
    cihaz-dönem için yeniden üretilmez.
    """

    __tablename__ = "maintenance_exclusion_requests"
    __table_args__ = (
        CheckConstraint(_in("reason_code", KAPSAM_DISI_NEDENLERI), name="ck_mer_neden"),
        CheckConstraint(_in("status", KAPSAM_DISI_DURUMLARI), name="ck_mer_durum"),
        CheckConstraint(
            "decided_by IS NULL OR decided_by <> requested_by", name="ck_mer_kendi_onayi"
        ),
        CheckConstraint("length(trim(description)) > 0", name="ck_mer_aciklama"),
        Index(
            "uq_mer_acik",
            "service_order_id",
            unique=True,
            postgresql_where=text("status = 'TALEP' AND NOT is_deleted"),
        ),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    contract_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maintenance_contract_items.id", ondelete="RESTRICT")
    )
    maintenance_period_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maintenance_periods.id", ondelete="RESTRICT")
    )
    reason_code: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(12), server_default=text("'TALEP'"), default="TALEP")
    decided_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
