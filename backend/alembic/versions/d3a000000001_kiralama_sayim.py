"""kiralama sayim (teknik servis Dalga 3, migration 1/3)

NEDEN: Kiralama deposunun fiziksel sayımı (E06-22 b, TS-195). Sayım ayrı bir
iş nesnesidir; **onaysız sayım hiçbir durumu/bakiyeyi değiştirmez** — fark
okuma anında hareket defterinden hesaplanır, onaylı satırlar tek yazıcı
(`kiralik_envanter.hareket_yaz`) ile `kind=SAYIM` hareketi yazar. Depo başına
tek açık sayım (`uq_rsayim_acik`): iki kişinin aynı depoyu aynı anda
saymasıyla çift KAYIP/düzeltme hareketi oluşamaz. Satır üç biçimlidir
(kayıtlı seri / sistemde olmayan seri / toplu ürün); her biçimin tekilliği
kendi kısmi indeksindedir.

BEDEL: Yalnız iki yeni tablo; mevcut kiralama tablolarına ve canlı tablolara
dokunulmaz. Downgrade sayımları ve satırlarını siler (yazılmış hareketler
defterde kalır — defter ekleme-yalnızdır).

Revision ID: d3a000000001
Revises: d2a000000007
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3a000000001"
down_revision: str | None = "d2a000000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _zaman() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "rental_counts",
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("durum", sa.String(length=12), server_default=sa.text("'ACIK'"), nullable=False),
        sa.Column("baslangic_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("onaylayan_id", sa.BigInteger(), nullable=True),
        sa.Column("onay_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("iptal_gerekcesi", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_zaman(),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("durum IN ('ACIK', 'ONAYLANDI', 'IPTAL')", name="ck_rsayim_durum"),
        sa.CheckConstraint(
            "durum <> 'ONAYLANDI' OR (onaylayan_id IS NOT NULL AND onay_at IS NOT NULL)",
            name="ck_rsayim_onay",
        ),
        sa.CheckConstraint(
            "durum <> 'IPTAL' OR length(trim(coalesce(iptal_gerekcesi, ''))) > 0",
            name="ck_rsayim_iptal",
        ),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["onaylayan_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_rsayim_acik",
        "rental_counts",
        ["warehouse_id"],
        unique=True,
        postgresql_where=sa.text("durum = 'ACIK' AND NOT is_deleted"),
    )

    op.create_table(
        "rental_count_lines",
        sa.Column("rental_count_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("serial_text", sa.String(length=200), nullable=True),
        sa.Column("serial_key", sa.String(length=200), nullable=True),
        sa.Column("sayilan_adet", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("notes", sa.String(length=300), nullable=True),
        *_zaman(),
        sa.CheckConstraint("sayilan_adet >= 0", name="ck_rsayim_satir_adet"),
        sa.CheckConstraint(
            "asset_id IS NULL OR serial_text IS NULL", name="ck_rsayim_satir_tek_kimlik"
        ),
        sa.CheckConstraint(
            "(asset_id IS NULL AND serial_text IS NULL) OR sayilan_adet IN (0, 1)",
            name="ck_rsayim_satir_seri_adet",
        ),
        sa.ForeignKeyConstraint(["rental_count_id"], ["rental_counts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["rental_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_rsayim_satir_cihaz",
        "rental_count_lines",
        ["rental_count_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NOT NULL"),
    )
    op.create_index(
        "uq_rsayim_satir_seri",
        "rental_count_lines",
        ["rental_count_id", "product_id", "serial_key"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NULL AND serial_key IS NOT NULL"),
    )
    op.create_index(
        "uq_rsayim_satir_toplu",
        "rental_count_lines",
        ["rental_count_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NULL AND serial_key IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_rsayim_satir_toplu", table_name="rental_count_lines")
    op.drop_index("uq_rsayim_satir_seri", table_name="rental_count_lines")
    op.drop_index("uq_rsayim_satir_cihaz", table_name="rental_count_lines")
    op.drop_table("rental_count_lines")
    op.drop_index("uq_rsayim_acik", table_name="rental_counts")
    op.drop_table("rental_counts")
