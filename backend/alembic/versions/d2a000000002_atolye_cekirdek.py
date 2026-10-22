"""atolye cekirdek (teknik servis Dalga 2, migration 2/7)

NEDEN: 1 atölye kaydı = 1 cihaz = 1 servis işi (`uq_atolye_servis_isi`).
Eski sistemde atölye kaydı ile iş emri iki durum, iki atama, iki seri
taşıyordu; burada iş kimliği/atama/zaman/parça servis işinde, seri ekipman
kütüğünde kalır. Bileşik FK `fk_atolye_servis_ekipman` (ON UPDATE CASCADE)
atölye kaydının ekipmanını işin ekipmanına kilitler — hedefi için
`service_orders` üzerinde `uq_so_id_ekipman` açılır. Aynı cihaza ikinci açık
kayıt `uq_atolye_acik_ekipman` ile DB'de de engellidir. Garanti tarihleri
ekipmanda; kayıt yalnız kabulde dondurulan durumu taşır. Arıza nedeni birim
bazlı katalogdur (FK).

BEDEL: Yalnız yeni tablolar + Dalga 0 tablosu `service_orders`'a bir benzersiz
kısıt (id zaten tekil olduğundan veri doğrulaması her zaman geçer).
Downgrade atölye kayıtlarını ve aksesuarları siler.

Revision ID: d2a000000002
Revises: d2a000000001
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a000000002"
down_revision: str | None = "d2a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Bileşik FK hedefi: atölye kaydının ekipmanı işin ekipmanıyla aynı kalır.
    op.create_unique_constraint("uq_so_id_ekipman", "service_orders", ["id", "equipment_id"])
    op.create_table(
        "workshop_records",
        sa.Column("atolye_no", sa.String(length=24), nullable=False),
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("equipment_id", sa.BigInteger(), nullable=False),
        sa.Column("intake_group_no", sa.BigInteger(), nullable=True),
        sa.Column("service_type", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'KABUL_EDILDI'"), nullable=False
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_by", sa.BigInteger(), nullable=True),
        sa.Column("receive_type", sa.String(length=10), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("customer_complaint", sa.Text(), nullable=False),
        sa.Column("physical_condition", sa.Text(), nullable=True),
        sa.Column("estimated_finish_date", sa.Date(), nullable=True),
        sa.Column(
            "warranty_status",
            sa.String(length=20),
            server_default=sa.text("'BELIRSIZ'"),
            nullable=False,
        ),
        sa.Column("warranty_end_snapshot", sa.Date(), nullable=True),
        sa.Column("fault_reason_id", sa.BigInteger(), nullable=True),
        sa.Column("diagnosis_note", sa.Text(), nullable=True),
        sa.Column("diagnosed_by", sa.BigInteger(), nullable=True),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_repairable", sa.Boolean(), nullable=True),
        sa.Column("repair_category", sa.String(length=30), nullable=True),
        sa.Column("repair_note", sa.Text(), nullable=True),
        sa.Column("test_result", sa.String(length=10), nullable=True),
        sa.Column("tested_by", sa.BigInteger(), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_decision", sa.String(length=16), nullable=True),
        sa.Column("approval_channel", sa.String(length=10), nullable=True),
        sa.Column("approved_by_name", sa.String(length=120), nullable=True),
        sa.Column("approval_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("repair_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("delivery_type", sa.String(length=10), nullable=True),
        sa.Column("cargo_company", sa.String(length=60), nullable=True),
        sa.Column("cargo_tracking_no", sa.String(length=60), nullable=True),
        sa.Column("cargo_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_to_name", sa.String(length=120), nullable=True),
        sa.Column("delivery_note", sa.Text(), nullable=True),
        sa.Column("external_vendor_id", sa.BigInteger(), nullable=True),
        sa.Column("external_rma_no", sa.String(length=60), nullable=True),
        sa.Column("external_sent_at", sa.Date(), nullable=True),
        sa.Column("external_returned_at", sa.Date(), nullable=True),
        sa.Column("logo_form_no", sa.String(length=80), nullable=True),
        sa.Column("logo_main_service_no", sa.String(length=80), nullable=True),
        sa.Column("integration_company", sa.String(length=150), nullable=True),
        sa.Column("project_name", sa.String(length=150), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "approval_channel IS NULL OR approval_channel IN ('TELEFON', 'EPOSTA', 'YAZILI', 'TEKLIF')",
            name="ck_atolye_onay_kanali",
        ),
        sa.CheckConstraint(
            "approval_decision IS DISTINCT FROM 'ONAY_GEREKMEZ' OR approval_note IS NOT NULL",
            name="ck_atolye_onay_gerekce",
        ),
        sa.CheckConstraint(
            "approval_decision IS NULL OR approval_decision IN ('ONAYLANDI', 'REDDEDILDI', 'ONAY_GEREKMEZ')",
            name="ck_atolye_onay_karari",
        ),
        sa.CheckConstraint(
            "delivery_type IS NULL OR delivery_type IN ('ELDEN', 'KARGO', 'KURYE', 'SAHA')",
            name="ck_atolye_teslim_tipi",
        ),
        sa.CheckConstraint(
            "receive_type IN ('ELDEN', 'KARGO', 'KURYE', 'SAHA')", name="ck_atolye_kabul_tipi"
        ),
        sa.CheckConstraint(
            "repair_category IS NULL OR repair_category IN ('PARCA_DEGISIMI', 'LEHIM_KART_ONARIMI', 'YAZILIM_YUKLEME', 'FREKANS_PROGRAMLAMA', 'TEMIZLIK_BAKIM', 'AYAR_KALIBRASYON', 'ISLEM_YAPILMADI', 'DIGER')",
            name="ck_atolye_onarim",
        ),
        sa.CheckConstraint(
            "service_type IN ('ARIZA_ONARIMI', 'GARANTI_ONARIMI', 'DIS_SERVIS', 'YAZILIM_FREKANS', 'KIRALAMA_TAKIP')",
            name="ck_atolye_servis_turu",
        ),
        sa.CheckConstraint(
            "status <> 'KARGOYA_VERILDI' OR (delivery_type = 'KARGO' AND cargo_tracking_no IS NOT NULL AND cargo_company IS NOT NULL)",
            name="ck_atolye_kargo",
        ),
        sa.CheckConstraint(
            "status <> 'TESLIM_EDILDI' OR (delivered_to_name IS NOT NULL AND delivered_at IS NOT NULL AND delivery_type IS NOT NULL)",
            name="ck_atolye_teslim",
        ),
        sa.CheckConstraint(
            "status IN ('KABUL_EDILDI', 'TESHISTE', 'ONAY_BEKLIYOR', 'ONARIMDA', 'PARCA_BEKLIYOR', 'DIS_SERVISTE', 'TEST_KONTROL', 'TESLIME_HAZIR', 'ONARILMADAN_IADE', 'KARGOYA_VERILDI', 'TESLIM_EDILDI', 'IPTAL')",
            name="ck_atolye_durum",
        ),
        sa.CheckConstraint(
            "status NOT IN ('TESLIME_HAZIR', 'ONARILMADAN_IADE', 'KARGOYA_VERILDI', 'TESLIM_EDILDI') OR completed_at IS NOT NULL",
            name="ck_atolye_tamamlanma",
        ),
        sa.CheckConstraint(
            "test_result IS NULL OR test_result IN ('GECTI', 'KALDI')", name="ck_atolye_test"
        ),
        sa.CheckConstraint(
            "warranty_status IN ('GARANTI_ICI', 'GARANTI_DISI', 'ONARIM_GARANTISI', 'BELIRSIZ')",
            name="ck_atolye_garanti",
        ),
        sa.CheckConstraint(
            "external_returned_at IS NULL OR external_sent_at IS NULL OR external_returned_at >= external_sent_at",
            name="ck_atolye_dis_servis_tarih",
        ),
        sa.CheckConstraint("repair_amount IS NULL OR repair_amount >= 0", name="ck_atolye_bedel"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["diagnosed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["service_equipment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["external_vendor_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["fault_reason_id"], ["service_fault_reasons.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["service_order_id", "equipment_id"],
            ["service_orders.id", "service_orders.equipment_id"],
            name="fk_atolye_servis_ekipman",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tested_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("atolye_no", name="uq_atolye_no"),
        sa.UniqueConstraint("service_order_id", name="uq_atolye_servis_isi"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_atolye_kaynak"),
    )
    op.create_index("ix_atolye_durum", "workshop_records", ["status", "received_at"], unique=False)
    op.create_index("ix_atolye_grup", "workshop_records", ["intake_group_no"], unique=False)
    op.create_index(
        "ix_atolye_tahmini_bitis",
        "workshop_records",
        ["estimated_finish_date"],
        unique=False,
        postgresql_where=sa.text("status NOT IN ('TESLIM_EDILDI', 'IPTAL') AND NOT is_deleted"),
    )
    op.create_index(
        "uq_atolye_acik_ekipman",
        "workshop_records",
        ["equipment_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('TESLIM_EDILDI', 'IPTAL') AND NOT is_deleted"),
    )
    op.create_table(
        "workshop_accessories",
        sa.Column("workshop_record_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=120), nullable=True),
        sa.Column("qty", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("returned", sa.Boolean(), nullable=True),
        sa.Column("return_note", sa.String(length=300), nullable=True),
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
            "kind <> 'DIGER' OR description IS NOT NULL", name="ck_atolye_aksesuar_aciklama"
        ),
        sa.CheckConstraint(
            "kind IN ('BATARYA', 'SARJ_UNITESI', 'SARJ_ADAPTORU', 'ANTEN', 'KEMER_KLIPSI', 'KILIF', 'KULAKLIK', 'HARICI_MIKROFON', 'KABLO', 'DIGER')",
            name="ck_atolye_aksesuar_tur",
        ),
        sa.CheckConstraint("qty > 0", name="ck_atolye_aksesuar_adet"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workshop_record_id"], ["workshop_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_atolye_aksesuar_kayit", "workshop_accessories", ["workshop_record_id"], unique=False
    )

    # --- Numara serileri (plan §1.6), tabloya bağlı: RESTART IDENTITY sıfırlar --
    op.execute("CREATE SEQUENCE atolye_no_seq OWNED BY workshop_records.id")
    op.execute("CREATE SEQUENCE atolye_kabul_grubu_seq OWNED BY workshop_records.id")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS atolye_kabul_grubu_seq")
    op.execute("DROP SEQUENCE IF EXISTS atolye_no_seq")
    op.drop_index("ix_atolye_aksesuar_kayit", table_name="workshop_accessories")
    op.drop_table("workshop_accessories")
    op.drop_index(
        "uq_atolye_acik_ekipman",
        table_name="workshop_records",
        postgresql_where=sa.text("status NOT IN ('TESLIM_EDILDI', 'IPTAL') AND NOT is_deleted"),
    )
    op.drop_index(
        "ix_atolye_tahmini_bitis",
        table_name="workshop_records",
        postgresql_where=sa.text("status NOT IN ('TESLIM_EDILDI', 'IPTAL') AND NOT is_deleted"),
    )
    op.drop_index("ix_atolye_grup", table_name="workshop_records")
    op.drop_index("ix_atolye_durum", table_name="workshop_records")
    op.drop_table("workshop_records")
    op.drop_constraint("uq_so_id_ekipman", "service_orders", type_="unique")
