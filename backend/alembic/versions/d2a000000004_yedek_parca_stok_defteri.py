"""yedek parca stok defteri (teknik servis Dalga 2, migration 4/7)

NEDEN: Servis parçası canlı serisiz stok defterine (`stock_movements`) yazılır
— tek stok yazıcısı, iki defter yok (E11-01). Canlı `ck_stok_hareket_neden`
DEĞİŞTİRİLMEDEN ayrıntılı tür ayrı kolonda (`hareket_turu`) tutulur ve tür →
(neden, işaret) eşlemesi şemada kilitlenir (`ck_stok_hareket_tur_yon`).
Servis satırları değiştirilemez/silinemez (`trg_stok_hareket_degismez`,
yalnız `hareket_turu IS NOT NULL`); düzeltme tek seferlik ters kayıttır
(`uq_stok_hareket_ters`); (parça, depo) başına tek açılış
(`uq_stok_hareket_acilis`). Birim maliyet hareket anında dondurulur
(`unit_cost Numeric(14,4)`, KD-25). Parça kartı bayrağı/ölçü birimi/asgari
stok `products`'a eklenir; sayım ve parça talebi yeni tablolardır.

BEDEL: CANLI `stock_movements` 7, `products` 3 kolon alır (hepsi nullable ya
da server_default'lu); yeni CHECK'ler yalnız yeni kolonları sınar (mevcut
satırlarda `hareket_turu IS NULL`, `yedek_parca=false`). Mobilite satırlarının
davranışı değişmez (tetikleyici WHEN koşuludur). Downgrade servis defteri
satırlarını, sayımları ve parça taleplerini siler.

Revision ID: d2a000000004
Revises: d2a000000003
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a000000004"
down_revision: str | None = "d2a000000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- products (CANLI tablo, plan §1.12): default'lu/nullable kolon ----------
    op.add_column(
        "products",
        sa.Column("yedek_parca", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("products", sa.Column("birim", sa.String(length=10), nullable=True))
    op.add_column("products", sa.Column("min_stok", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_products_birim",
        "products",
        "birim IS NULL OR birim IN ('ADET', 'METRE', 'TAKIM', 'LITRE', 'PAKET', 'KUTU')",
    )
    op.create_check_constraint(
        "ck_products_min_stok", "products", "min_stok IS NULL OR min_stok >= 0"
    )
    op.create_check_constraint(
        "ck_products_yedek_parca_serisiz", "products", "NOT yedek_parca OR identity_kind = 'YOK'"
    )

    # --- Sayım ve parça talebi -------------------------------------------------
    op.create_table(
        "stock_counts",
        sa.Column("count_no", sa.String(length=24), nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("durum", sa.String(length=12), server_default=sa.text("'ACIK'"), nullable=False),
        sa.Column("baslangic_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("onaylayan_id", sa.BigInteger(), nullable=True),
        sa.Column("onay_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gerekce", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint(
            "durum <> 'ONAYLANDI' OR (onaylayan_id IS NOT NULL AND onay_at IS NOT NULL AND length(trim(coalesce(gerekce, ''))) > 0)",
            name="ck_stok_sayim_onay",
        ),
        sa.CheckConstraint("durum IN ('ACIK', 'ONAYLANDI', 'IPTAL')", name="ck_stok_sayim_durum"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["onaylayan_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("count_no", name="uq_stok_sayim_no"),
    )
    op.create_index(
        "uq_stok_sayim_acik",
        "stock_counts",
        ["warehouse_id"],
        unique=True,
        postgresql_where=sa.text("durum = 'ACIK' AND NOT is_deleted"),
    )
    op.create_table(
        "stock_count_lines",
        sa.Column("stock_count_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("sistem_adet", sa.Integer(), nullable=False),
        sa.Column("sayilan_adet", sa.Integer(), nullable=True),
        sa.Column("onay_anindaki_adet", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "sayilan_adet IS NULL OR sayilan_adet >= 0", name="ck_stok_sayim_sayilan"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_count_id"], ["stock_counts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_count_id", "product_id", name="uq_stok_sayim_satir"),
    )
    op.create_table(
        "service_part_requests",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("adet", sa.Integer(), nullable=False),
        sa.Column("durum", sa.String(length=12), server_default=sa.text("'ACIK'"), nullable=False),
        sa.Column("karsilanma_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("iptal_nedeni", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("hold_id", sa.BigInteger(), nullable=True),
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
        sa.CheckConstraint(
            "durum <> 'IPTAL' OR iptal_nedeni IS NOT NULL", name="ck_parca_talep_iptal"
        ),
        sa.CheckConstraint("durum IN ('ACIK', 'KARSILANDI', 'IPTAL')", name="ck_parca_talep_durum"),
        sa.CheckConstraint("adet > 0", name="ck_parca_talep_adet"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["hold_id"], ["service_holds.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_parca_talep_urun_durum", "service_part_requests", ["product_id", "durum"], unique=False
    )
    op.create_index(
        "uq_parca_talep_acik",
        "service_part_requests",
        ["service_order_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("durum = 'ACIK' AND NOT is_deleted"),
    )
    op.execute("CREATE SEQUENCE stock_count_no_seq OWNED BY stock_counts.id")

    # --- stock_movements (CANLI tablo): servis defteri kolonları ----------------
    op.add_column("stock_movements", sa.Column("hareket_turu", sa.String(length=20), nullable=True))
    op.add_column("stock_movements", sa.Column("service_order_id", sa.BigInteger(), nullable=True))
    op.add_column("stock_movements", sa.Column("reversal_of_id", sa.BigInteger(), nullable=True))
    op.add_column("stock_movements", sa.Column("transfer_grup", sa.UUID(), nullable=True))
    op.add_column("stock_movements", sa.Column("stock_count_id", sa.BigInteger(), nullable=True))
    op.add_column("stock_movements", sa.Column("part_request_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "stock_movements", sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=True)
    )
    op.create_foreign_key(
        "fk_stok_hareket_servis_isi",
        "stock_movements",
        "service_orders",
        ["service_order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_stok_hareket_ters",
        "stock_movements",
        "stock_movements",
        ["reversal_of_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_stok_hareket_sayim",
        "stock_movements",
        "stock_counts",
        ["stock_count_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_stok_hareket_parca_talebi",
        "stock_movements",
        "service_part_requests",
        ["part_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_stok_hareket_tur",
        "stock_movements",
        "hareket_turu IS NULL OR hareket_turu IN ('GIRIS', 'ACILIS', 'CIKIS_SERVIS', 'IADE_SERVIS', 'ZAYI', 'TERS_KAYIT', 'TRANSFER_CIKIS', 'TRANSFER_GIRIS', 'SAYIM_FAZLASI', 'SAYIM_EKSIGI')",
    )
    op.create_check_constraint(
        "ck_stok_hareket_tur_yon",
        "stock_movements",
        "hareket_turu IS NULL OR (hareket_turu = 'GIRIS' AND reason = 'GIRIS' AND qty > 0) OR (hareket_turu = 'ACILIS' AND reason = 'GIRIS' AND qty > 0) OR (hareket_turu = 'IADE_SERVIS' AND reason = 'GIRIS' AND qty > 0) OR (hareket_turu = 'CIKIS_SERVIS' AND reason = 'CIKIS' AND qty < 0) OR (hareket_turu = 'ZAYI' AND reason = 'CIKIS' AND qty < 0) OR (hareket_turu = 'TRANSFER_CIKIS' AND reason = 'TRANSFER' AND qty < 0) OR (hareket_turu = 'TRANSFER_GIRIS' AND reason = 'TRANSFER' AND qty > 0) OR (hareket_turu = 'SAYIM_FAZLASI' AND reason = 'SAYIM' AND qty > 0) OR (hareket_turu = 'SAYIM_EKSIGI' AND reason = 'SAYIM' AND qty < 0) OR (hareket_turu = 'TERS_KAYIT' AND reversal_of_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_stok_hareket_servis_isi",
        "stock_movements",
        "hareket_turu IS NULL OR hareket_turu NOT IN ('CIKIS_SERVIS', 'IADE_SERVIS') OR service_order_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_stok_hareket_depo",
        "stock_movements",
        "hareket_turu IS NULL OR warehouse_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_stok_hareket_ters_gerekce",
        "stock_movements",
        "hareket_turu IS DISTINCT FROM 'TERS_KAYIT' OR length(trim(coalesce(notes, ''))) > 0",
    )
    op.create_check_constraint(
        "ck_stok_hareket_transfer",
        "stock_movements",
        "hareket_turu IS NULL OR hareket_turu NOT IN ('TRANSFER_CIKIS', 'TRANSFER_GIRIS') OR transfer_grup IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_stok_hareket_maliyet", "stock_movements", "unit_cost IS NULL OR unit_cost >= 0"
    )
    op.create_index(
        "uq_stok_hareket_ters",
        "stock_movements",
        ["reversal_of_id"],
        unique=True,
        postgresql_where=sa.text("reversal_of_id IS NOT NULL"),
    )
    op.create_index(
        "uq_stok_hareket_acilis",
        "stock_movements",
        ["product_id", "warehouse_id"],
        unique=True,
        postgresql_where=sa.text("hareket_turu = 'ACILIS'"),
    )
    op.create_index(
        "ix_stok_hareket_servis",
        "stock_movements",
        ["service_order_id"],
        unique=False,
        postgresql_where=sa.text("service_order_id IS NOT NULL"),
    )

    # --- Servis defteri değişmez: yalnız hareket_turu dolu satırlar korunur ----
    op.execute(
        """
        CREATE FUNCTION trg_stok_hareket_degismez() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Servis stok hareketi silinemez; ters kayıt yazın';
            END IF;
            IF (to_jsonb(NEW) - 'created_by' - 'updated_by' - 'updated_at')
               IS DISTINCT FROM (to_jsonb(OLD) - 'created_by' - 'updated_by' - 'updated_at') THEN
                RAISE EXCEPTION 'Servis stok hareketi değiştirilemez; ters kayıt yazın';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_stok_hareket_degismez
        BEFORE UPDATE OR DELETE ON stock_movements
        FOR EACH ROW WHEN (OLD.hareket_turu IS NOT NULL)
        EXECUTE FUNCTION trg_stok_hareket_degismez()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_stok_hareket_degismez ON stock_movements")
    op.execute("DROP FUNCTION IF EXISTS trg_stok_hareket_degismez()")
    # Servis defteri satırları mobilite defterinde anlamsız: önce onlar silinir
    # (tetikleyici yukarıda düştü), sonra kolonlar.
    op.execute("DELETE FROM stock_movements WHERE hareket_turu IS NOT NULL")
    op.drop_index("ix_stok_hareket_servis", table_name="stock_movements")
    op.drop_index("uq_stok_hareket_acilis", table_name="stock_movements")
    op.drop_index("uq_stok_hareket_ters", table_name="stock_movements")
    op.drop_constraint("ck_stok_hareket_maliyet", "stock_movements", type_="check")
    op.drop_constraint("ck_stok_hareket_transfer", "stock_movements", type_="check")
    op.drop_constraint("ck_stok_hareket_ters_gerekce", "stock_movements", type_="check")
    op.drop_constraint("ck_stok_hareket_depo", "stock_movements", type_="check")
    op.drop_constraint("ck_stok_hareket_servis_isi", "stock_movements", type_="check")
    op.drop_constraint("ck_stok_hareket_tur_yon", "stock_movements", type_="check")
    op.drop_constraint("ck_stok_hareket_tur", "stock_movements", type_="check")
    op.drop_constraint("fk_stok_hareket_parca_talebi", "stock_movements", type_="foreignkey")
    op.drop_constraint("fk_stok_hareket_sayim", "stock_movements", type_="foreignkey")
    op.drop_constraint("fk_stok_hareket_ters", "stock_movements", type_="foreignkey")
    op.drop_constraint("fk_stok_hareket_servis_isi", "stock_movements", type_="foreignkey")
    op.drop_column("stock_movements", "unit_cost")
    op.drop_column("stock_movements", "part_request_id")
    op.drop_column("stock_movements", "stock_count_id")
    op.drop_column("stock_movements", "transfer_grup")
    op.drop_column("stock_movements", "reversal_of_id")
    op.drop_column("stock_movements", "service_order_id")
    op.drop_column("stock_movements", "hareket_turu")
    op.execute("DROP SEQUENCE IF EXISTS stock_count_no_seq")
    op.drop_index(
        "uq_parca_talep_acik",
        table_name="service_part_requests",
        postgresql_where=sa.text("durum = 'ACIK' AND NOT is_deleted"),
    )
    op.drop_index("ix_parca_talep_urun_durum", table_name="service_part_requests")
    op.drop_table("service_part_requests")
    op.drop_table("stock_count_lines")
    op.drop_index(
        "uq_stok_sayim_acik",
        table_name="stock_counts",
        postgresql_where=sa.text("durum = 'ACIK' AND NOT is_deleted"),
    )
    op.drop_table("stock_counts")
    op.drop_constraint("ck_products_yedek_parca_serisiz", "products", type_="check")
    op.drop_constraint("ck_products_min_stok", "products", type_="check")
    op.drop_constraint("ck_products_birim", "products", type_="check")
    op.drop_column("products", "min_stok")
    op.drop_column("products", "birim")
    op.drop_column("products", "yedek_parca")
