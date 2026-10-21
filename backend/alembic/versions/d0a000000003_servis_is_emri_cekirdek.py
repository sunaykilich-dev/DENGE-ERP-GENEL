"""servis is emri cekirdek (teknik servis Dalga 0, migration 3/7)

NEDEN: Teknik servis işi mobilite `work_orders` tablosuna YAZILMAZ (KD-01):
hak ediş dönem kapanışı, uyarı merkezi ve panel o tabloyu hak ediş
mantığıyla sayıyor; altın kayıt (932 iş / 552.825,00 TL) kirlenirdi. Servis
işi kendi tablolarında yaşar:

* `service_orders` (+ `service_order_no_seq`, OWNED BY: test temizliğinde
  `RESTART IDENTITY` sıfırlasın; yıl/ay başında sıfırlanmaz, eşzamanlılıkta
  çakışmaz — plan §1.6). Dalga 0'da bilinen bütün kolonlar burada açılır
  (`first_completed_at`, ham göç metinleri, kapsam anlık görüntüsü,
  `equipment_id/contract_item_id/maintenance_period_id`); bu üç bağın FK'leri
  hedef tablolarla birlikte 4. ve 6. migration'da eklenir.
* `service_order_events` — silinemez olay geçmişi; `trg_soe_salt_ekleme`
  UPDATE/DELETE'i reddeder (TRUNCATE tetiklemez, testler etkilenmez).
* `service_hold_reasons` (TOHUMLU katalog; CHECK değil FK — KD-14) ve
  `service_holds`; `service_fault_reasons` (birim bazlı tohum);
  `service_results`, `service_order_assignments`, `service_approvals`,
  `service_order_serials` (+ trgm GIN).

BEDEL: Yalnız yeni tablolar; canlı tablolara dokunulmaz. Downgrade bütün
servis işi verisini (olay geçmişi dahil) siler — canlıda downgrade yok,
yedekten dönülür (KD-27). Tohum satırları tabloyla birlikte gider.

Revision ID: d0a000000003
Revises: d0a000000002
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d0a000000003"
down_revision: str | None = "d0a000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tohumlar migration'a SABİT olarak yazılır (modelden import edilmez): model
# sözlüğü sonradan değişse de bu migration'ın ürettiği şema/veri değişmemeli.
_BIRIMLER = ("GUVENLIK", "HABERLESME", "POC", "MOBILITE", "ARAC_TAKIP")
# (kod, ad, sla_durdurur, aciklama_zorunlu, sadece_sistem, sira)
_BEKLEME_NEDENLERI = (
    ("MALZEME", "Malzeme bekleniyor", False, False, False, 10),
    ("MUSTERI_ONAYI", "Müşteri onayı bekleniyor", True, False, False, 20),
    ("TEKLIF", "Teklif onayı bekleniyor", True, False, False, 30),
    ("MUSTERI_ERISIMI", "Müşteri/saha erişimi yok", True, False, False, 40),
    ("PERSONEL", "Personel bekleniyor", False, False, False, 50),
    ("BAKIM_UYGUNSUZLUK", "Bakım uygunsuzluğu giderilecek", False, False, True, 60),
    ("DIS_SERVIS", "Dış servis/üretici bekleniyor", False, False, False, 70),
    ("DIGER", "Diğer", False, True, False, 90),
)
_ARIZA_NEDENLERI = (
    "Güç/Besleme",
    "Kablo/Bağlantı",
    "Donanım Arızası",
    "Yazılım/Yapılandırma",
    "Kullanıcı Hatası",
    "Çevresel/Fiziksel Hasar",
    "Arıza Bulunamadı",
    "Diğer",
)


def upgrade() -> None:
    op.create_table(
        "service_fault_reasons",
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("ad", sa.String(length=80), nullable=False),
        sa.Column("sira", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_sfr_birim",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("birim", "ad", name="uq_sfr_birim_ad"),
    )
    op.create_table(
        "service_hold_reasons",
        sa.Column("kod", sa.String(length=30), nullable=False),
        sa.Column("ad", sa.String(length=80), nullable=False),
        sa.Column("sla_durdurur", sa.Boolean(), nullable=False),
        sa.Column(
            "aciklama_zorunlu", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("sadece_sistem", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sira", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kod", name="uq_shr_kod"),
    )
    op.create_table(
        "service_orders",
        sa.Column("so_no", sa.String(length=24), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("tur", sa.String(length=20), nullable=False),
        sa.Column("kategori", sa.String(length=20), nullable=False),
        sa.Column(
            "oncelik", sa.String(length=10), server_default=sa.text("'NORMAL'"), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'MUSTERI_TALEBI'"),
            nullable=False,
        ),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("address_id", sa.BigInteger(), nullable=True),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("customer_name_raw", sa.String(length=250), nullable=True),
        sa.Column("location_raw", sa.Text(), nullable=True),
        sa.Column("iletisim_ad", sa.String(length=120), nullable=True),
        sa.Column("iletisim_telefon", sa.String(length=20), nullable=True),
        sa.Column("talep_kanali", sa.String(length=20), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proje", sa.String(length=120), nullable=True),
        sa.Column("sistem", sa.String(length=120), nullable=True),
        sa.Column("konu", sa.String(length=200), nullable=False),
        sa.Column("aciklama", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.BigInteger(), nullable=True),
        sa.Column("first_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.BigInteger(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.BigInteger(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("reopen_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("iliskili_is_id", sa.BigInteger(), nullable=True),
        sa.Column("iliski_turu", sa.String(length=20), nullable=True),
        sa.Column("work_order_id", sa.BigInteger(), nullable=True),
        sa.Column("rma_case_id", sa.BigInteger(), nullable=True),
        sa.Column("equipment_id", sa.BigInteger(), nullable=True),
        sa.Column("contract_item_id", sa.BigInteger(), nullable=True),
        sa.Column("maintenance_period_id", sa.BigInteger(), nullable=True),
        sa.Column("coverage_status", sa.String(length=12), nullable=True),
        sa.Column("coverage_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "(iliskili_is_id IS NULL) = (iliski_turu IS NULL) AND (iliski_turu IS NULL OR iliski_turu IN ('BAKIM_BULGUSU', 'DEVAM', 'MUKERRER', 'TEKRAR_ARIZA'))",
            name="ck_so_iliski",
        ),
        sa.CheckConstraint(
            "birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_so_birim",
        ),
        sa.CheckConstraint(
            "coverage_status IS NULL OR coverage_status IN ('BILINMIYOR', 'GARANTILI', 'KAPSAM_DISI', 'SOZLESMELI')",
            name="ck_so_kapsam",
        ),
        sa.CheckConstraint(
            "kategori IN ('ATOLYE', 'GUNLUK_SERVIS', 'PLANLI_BAKIM', 'PROJE')",
            name="ck_so_kategori",
        ),
        sa.CheckConstraint("oncelik IN ('KRITIK', 'NORMAL', 'YUKSEK')", name="ck_so_oncelik"),
        sa.CheckConstraint(
            "status <> 'IPTAL' OR cancel_reason IS NOT NULL", name="ck_so_iptal_gerekce"
        ),
        sa.CheckConstraint(
            "status IN ('ATOLYEDE', 'BEKLEMEDE', 'IPTAL', 'ISLEMDE', 'KAPATILDI', 'MUSTERI_TALEBI', 'PLANLAMADA', 'PLANLANDI', 'SAHADA', 'TAMAMLANDI', 'TEKRAR_ACILDI', 'YOLA_CIKILDI')",
            name="ck_so_durum",
        ),
        sa.CheckConstraint(
            "talep_kanali IS NULL OR talep_kanali IN ('BAKIM_OTOMATIK', 'DIGER', 'EPOSTA', 'SAHADA_BILDIRILDI', 'TELEFON', 'WHATSAPP')",
            name="ck_so_kanal",
        ),
        sa.CheckConstraint(
            "tur <> 'PB' OR (contract_item_id IS NOT NULL AND maintenance_period_id IS NOT NULL)",
            name="ck_so_pb_bag",
        ),
        sa.CheckConstraint(
            "tur IN ('ARIZA', 'ATOLYE', 'DEMONTAJ', 'DESTEK', 'KESIF', 'KURULUM', 'PB', 'PLANSIZ_BAKIM', 'TOPLAMA')",
            name="ck_so_tur",
        ),
        sa.CheckConstraint(
            "customer_id IS NOT NULL OR source_system IS NOT NULL", name="ck_so_musteri"
        ),
        sa.CheckConstraint(
            "first_completed_at IS NULL OR completed_at IS NULL OR completed_at >= first_completed_at",
            name="ck_so_ilk_cozum",
        ),
        sa.CheckConstraint("iliskili_is_id <> id", name="ck_so_kendine_bagli"),
        sa.CheckConstraint("reopen_count >= 0", name="ck_so_yeniden_acilma"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["iliskili_is_id"], ["service_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rma_case_id"], ["rma_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("so_no", name="uq_so_no"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_so_kaynak"),
    )
    op.create_index("ix_so_adres", "service_orders", ["address_id"], unique=False)
    op.create_index("ix_so_birim_durum", "service_orders", ["birim", "status"], unique=False)
    op.create_index("ix_so_durum_olusma", "service_orders", ["status", "created_at"], unique=False)
    op.create_index("ix_so_ekipman", "service_orders", ["equipment_id"], unique=False)
    op.create_index("ix_so_ilk_cozum", "service_orders", ["first_completed_at"], unique=False)
    op.create_index("ix_so_kapanis", "service_orders", ["closed_at"], unique=False)
    op.create_index("ix_so_musteri", "service_orders", ["customer_id"], unique=False)
    op.create_table(
        "service_approvals",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("tur", sa.String(length=12), nullable=False),
        sa.Column("imzalayan_ad", sa.String(length=120), nullable=True),
        sa.Column("imzalayan_unvan", sa.String(length=80), nullable=True),
        sa.Column("ek_id", sa.BigInteger(), nullable=True),
        sa.Column("eksik_nedeni", sa.String(length=300), nullable=True),
        sa.Column("gecersiz_kilan_id", sa.BigInteger(), nullable=True),
        sa.Column("onay_grubu", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("tur <> 'ALINAMADI' OR eksik_nedeni IS NOT NULL", name="ck_sa_neden"),
        sa.CheckConstraint(
            "tur IN ('ALINAMADI', 'BASILI_FORM', 'IMZA', 'SOZLU')", name="ck_sa_tur"
        ),
        sa.CheckConstraint(
            "tur NOT IN ('IMZA', 'BASILI_FORM') OR ek_id IS NOT NULL", name="ck_sa_ek"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ek_id"], ["attachments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["gecersiz_kilan_id"], ["service_approvals.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sa_grup", "service_approvals", ["onay_grubu"], unique=False)
    op.create_index("ix_sa_is", "service_approvals", ["service_order_id"], unique=False)
    op.create_table(
        "service_holds",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("neden", sa.String(length=30), nullable=False),
        sa.Column("aciklama", sa.String(length=500), nullable=True),
        sa.Column("onceki_durum", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_by", sa.BigInteger(), nullable=True),
        sa.Column("beklenen_bitis_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_durdurur", sa.Boolean(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.BigInteger(), nullable=True),
        sa.Column("sure_dk", sa.Integer(), nullable=True),
        sa.Column("sla_kayma_dk", sa.Integer(), nullable=True),
        sa.Column("kapanis_notu", sa.String(length=200), nullable=True),
        sa.Column(
            "otomatik_kapandi", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "neden <> 'DIGER' OR aciklama IS NOT NULL", name="ck_hold_diger_aciklama"
        ),
        sa.CheckConstraint(
            "onceki_durum IN ('ATOLYEDE', 'BEKLEMEDE', 'IPTAL', 'ISLEMDE', 'KAPATILDI', 'MUSTERI_TALEBI', 'PLANLAMADA', 'PLANLANDI', 'SAHADA', 'TAMAMLANDI', 'TEKRAR_ACILDI', 'YOLA_CIKILDI')",
            name="ck_hold_onceki_durum",
        ),
        sa.CheckConstraint("(released_at IS NULL) = (sure_dk IS NULL)", name="ck_hold_sure"),
        sa.CheckConstraint(
            "released_at IS NULL OR released_at >= started_at", name="ck_hold_aralik"
        ),
        sa.ForeignKeyConstraint(["neden"], ["service_hold_reasons.kod"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["released_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_hold_aktif",
        "service_holds",
        ["service_order_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_table(
        "service_order_assignments",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("rol", sa.String(length=10), nullable=False),
        sa.Column("is_lead", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_by", sa.BigInteger(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("NOT is_lead OR rol = 'TEKNISYEN'", name="ck_soa_sorumlu_teknisyen"),
        sa.CheckConstraint("rol IN ('SEF', 'TEKNISYEN')", name="ck_soa_rol"),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["removed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_soa_kullanici_aktif",
        "service_order_assignments",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "uq_soa_aktif",
        "service_order_assignments",
        ["service_order_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "uq_soa_tek_sorumlu",
        "service_order_assignments",
        ["service_order_id"],
        unique=True,
        postgresql_where=sa.text("is_lead AND removed_at IS NULL"),
    )
    op.create_table(
        "service_order_events",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("olay_turu", sa.String(length=20), nullable=False),
        sa.Column("eski_durum", sa.String(length=20), nullable=True),
        sa.Column("yeni_durum", sa.String(length=20), nullable=True),
        sa.Column("ozet", sa.String(length=500), nullable=False),
        sa.Column("veri", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("olusma_zamani", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.CheckConstraint(
            "olay_turu IN ('ATAMA', 'ATOLYE', 'BEKLEME', 'BEKLEME_BITTI', 'DURUM', 'DUZELTME', 'EK', 'EK_SIL', 'ILISKI', 'NOT', 'OLUSTUR', 'ONAY', 'PARCA', 'PLAN', 'SERI', 'SLA', 'SONUC', 'TEKLIF')",
            name="ck_soe_tur",
        ),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_soe_is_zaman",
        "service_order_events",
        ["service_order_id", "olusma_zamani"],
        unique=False,
    )
    op.create_table(
        "service_order_serials",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("seri_no", sa.String(length=200), nullable=False),
        sa.Column("seri_norm", sa.String(length=200), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("is_active OR removed_at IS NOT NULL", name="ck_sos_pasif"),
        sa.CheckConstraint("length(trim(seri_no)) > 0", name="ck_sos_seri_bos"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["removed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_service_order_serials_service_order_id"),
        "service_order_serials",
        ["service_order_id"],
        unique=False,
    )
    op.create_index("ix_sos_seri_norm", "service_order_serials", ["seri_norm"], unique=False)
    op.create_index(
        "ix_sos_seri_trgm",
        "service_order_serials",
        [sa.literal_column("seri_norm gin_trgm_ops")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "uq_sos_aktif",
        "service_order_serials",
        ["service_order_id", "seri_norm"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "service_results",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("sonuc", sa.String(length=20), nullable=False),
        sa.Column("cozum_kanali", sa.String(length=10), nullable=False),
        sa.Column("yapilan_islem", sa.Text(), nullable=False),
        sa.Column("ariza_nedeni_id", sa.BigInteger(), nullable=True),
        sa.Column("saha_seri_no", sa.String(length=200), nullable=True),
        sa.Column("saha_bolge", sa.String(length=120), nullable=True),
        sa.Column("kutuk_fark_durumu", sa.String(length=12), nullable=True),
        sa.Column("gecersiz_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gecersiz_by", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "cozum_kanali IN ('ATOLYE', 'TELEFON', 'UZAKTAN', 'YERINDE')", name="ck_sr_kanal"
        ),
        sa.CheckConstraint(
            "kutuk_fark_durumu IS NULL OR kutuk_fark_durumu IN ('ACIK', 'UYGULANDI', 'YOK_SAYILDI')",
            name="ck_sr_kutuk_fark",
        ),
        sa.CheckConstraint(
            "sonuc IN ('COZULDU', 'COZULEMEDI', 'TEKLIF_SUNULACAK', 'TEKRAR_GIDILECEK')",
            name="ck_sr_sonuc",
        ),
        sa.CheckConstraint("length(trim(yapilan_islem)) > 0", name="ck_sr_islem_bos"),
        sa.ForeignKeyConstraint(
            ["ariza_nedeni_id"], ["service_fault_reasons.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["gecersiz_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sr_is", "service_results", ["service_order_id"], unique=False)

    # --- Numara serisi: SRV-/PB- ortak sequence, tabloya bağlı ---------------
    op.execute("CREATE SEQUENCE service_order_no_seq OWNED BY service_orders.id")

    # --- Olay geçmişi yalnız eklenir -----------------------------------------
    op.execute(
        """
        CREATE FUNCTION trg_soe_salt_ekleme() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'service_order_events yalnız eklenebilir (% reddedildi)', TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_soe_salt_ekleme
        BEFORE UPDATE OR DELETE ON service_order_events
        FOR EACH ROW EXECUTE FUNCTION trg_soe_salt_ekleme()
        """
    )

    # --- Tohumlar --------------------------------------------------------------
    bekleme = sa.table(
        "service_hold_reasons",
        sa.column("kod", sa.String),
        sa.column("ad", sa.String),
        sa.column("sla_durdurur", sa.Boolean),
        sa.column("aciklama_zorunlu", sa.Boolean),
        sa.column("sadece_sistem", sa.Boolean),
        sa.column("sira", sa.SmallInteger),
    )
    op.bulk_insert(
        bekleme,
        [
            {
                "kod": kod,
                "ad": ad,
                "sla_durdurur": durdurur,
                "aciklama_zorunlu": aciklama,
                "sadece_sistem": sistem,
                "sira": sira,
            }
            for kod, ad, durdurur, aciklama, sistem, sira in _BEKLEME_NEDENLERI
        ],
    )
    ariza = sa.table(
        "service_fault_reasons",
        sa.column("birim", sa.String),
        sa.column("ad", sa.String),
        sa.column("sira", sa.SmallInteger),
    )
    op.bulk_insert(
        ariza,
        [
            {"birim": birim, "ad": ad, "sira": (i + 1) * 10}
            for birim in _BIRIMLER
            for i, ad in enumerate(_ARIZA_NEDENLERI)
        ],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_soe_salt_ekleme ON service_order_events")
    op.execute("DROP FUNCTION IF EXISTS trg_soe_salt_ekleme()")
    op.drop_index("ix_sr_is", table_name="service_results")
    op.drop_table("service_results")
    op.drop_index(
        "uq_sos_aktif", table_name="service_order_serials", postgresql_where=sa.text("is_active")
    )
    op.drop_index("ix_sos_seri_trgm", table_name="service_order_serials", postgresql_using="gin")
    op.drop_index("ix_sos_seri_norm", table_name="service_order_serials")
    op.drop_index(
        op.f("ix_service_order_serials_service_order_id"), table_name="service_order_serials"
    )
    op.drop_table("service_order_serials")
    op.drop_index("ix_soe_is_zaman", table_name="service_order_events")
    op.drop_table("service_order_events")
    op.drop_index(
        "uq_soa_tek_sorumlu",
        table_name="service_order_assignments",
        postgresql_where=sa.text("is_lead AND removed_at IS NULL"),
    )
    op.drop_index(
        "uq_soa_aktif",
        table_name="service_order_assignments",
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.drop_index(
        "ix_soa_kullanici_aktif",
        table_name="service_order_assignments",
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.drop_table("service_order_assignments")
    op.drop_index(
        "uq_hold_aktif", table_name="service_holds", postgresql_where=sa.text("released_at IS NULL")
    )
    op.drop_table("service_holds")
    op.drop_index("ix_sa_is", table_name="service_approvals")
    op.drop_index("ix_sa_grup", table_name="service_approvals")
    op.drop_table("service_approvals")
    op.drop_index("ix_so_musteri", table_name="service_orders")
    op.drop_index("ix_so_kapanis", table_name="service_orders")
    op.drop_index("ix_so_ilk_cozum", table_name="service_orders")
    op.drop_index("ix_so_ekipman", table_name="service_orders")
    op.drop_index("ix_so_durum_olusma", table_name="service_orders")
    op.drop_index("ix_so_birim_durum", table_name="service_orders")
    op.drop_index("ix_so_adres", table_name="service_orders")
    op.drop_table("service_orders")
    op.drop_table("service_hold_reasons")
    op.drop_table("service_fault_reasons")
    # ### end Alembic commands ###
