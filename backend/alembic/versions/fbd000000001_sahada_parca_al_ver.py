"""S5 sahada onarımda parça al-ver: kullanım onayı, sökülen parça, araç ikmali

KARARLAR_2026-11-09_satis_depo_belge.md S5 (D6.7):
- `service_part_usage_reviews` (S5.1): teknisyenin araç deposundan işe
  çıkışı anında yazılır; şef sonradan onaylar. Ret = fark kaydı + zimmet
  sorusu (`zimmet_durumu`), teknisyen açıklar.
- `service_removed_parts` (S5.2): sökülen/arızalı parça işe yazılır; karar
  zorunlu (IADE_TAMIR, IADE_HURDA, MUSTERIDE); iadede depo zorunlu. Stok
  defterine YAZILMAZ (arızalı parça kullanılabilir stok değildir).
- `service_part_requests` (S5.3): `service_order_id` boş olabilir; yeni
  `hedef_depo_id` (araç deposu ikmali). Kural: iş ya da hedef depo dolu;
  hedef depo + parça başına tek açık ikmal talebi.

YALNIZ EKLEME + bir kolonun NOT NULL'unun kaldırılması. BEDEL / GERİ ALMA:
downgrade iki tabloyu düşürür (onay/zimmet ve sökülen parça kayıtları
kaybolur); işe bağlı olmayan ikmal talepleri SİLİNİR (NOT NULL geri gelir).

Revision ID: fbd000000001
Revises: fbc000000001
Create Date: 2026-11-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fbd000000001"
down_revision: str | None = "fbc000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _zaman() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "service_part_usage_reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "stock_movement_id",
            sa.BigInteger(),
            sa.ForeignKey("stock_movements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "service_order_id",
            sa.BigInteger(),
            sa.ForeignKey("service_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.BigInteger(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.BigInteger(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("adet", sa.Integer(), nullable=False),
        sa.Column("kullanan_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("durum", sa.String(12), nullable=False, server_default=sa.text("'BEKLIYOR'")),
        sa.Column("onaylayan_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("onay_at", sa.DateTime(timezone=True)),
        sa.Column("red_nedeni", sa.String(200)),
        sa.Column("zimmet_durumu", sa.String(12)),
        sa.Column("zimmet_aciklama", sa.String(500)),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        *_zaman(),
        sa.UniqueConstraint("stock_movement_id", name="uq_parca_kullanim_hareket"),
        sa.CheckConstraint(
            "durum IN ('BEKLIYOR', 'ONAYLANDI', 'REDDEDILDI')", name="ck_parca_kullanim_durum"
        ),
        sa.CheckConstraint(
            "durum <> 'REDDEDILDI' OR (red_nedeni IS NOT NULL AND zimmet_durumu IS NOT NULL)",
            name="ck_parca_kullanim_red",
        ),
        sa.CheckConstraint(
            "zimmet_durumu IS NULL OR zimmet_durumu IN ('ACIK', 'CEVAPLANDI')",
            name="ck_parca_kullanim_zimmet",
        ),
        sa.CheckConstraint(
            "zimmet_durumu IS DISTINCT FROM 'CEVAPLANDI' OR zimmet_aciklama IS NOT NULL",
            name="ck_parca_kullanim_zimmet_cevap",
        ),
        sa.CheckConstraint("adet > 0", name="ck_parca_kullanim_adet"),
    )
    op.create_index("ix_parca_kullanim_durum", "service_part_usage_reviews", ["durum"])

    op.create_table(
        "service_removed_parts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "service_order_id",
            sa.BigInteger(),
            sa.ForeignKey("service_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id", ondelete="RESTRICT")),
        sa.Column("tanim", sa.String(160)),
        sa.Column("seri_no", sa.String(80)),
        sa.Column("adet", sa.Integer(), nullable=False),
        sa.Column("karar", sa.String(12), nullable=False),
        sa.Column(
            "warehouse_id", sa.BigInteger(), sa.ForeignKey("warehouses.id", ondelete="RESTRICT")
        ),
        sa.Column("notes", sa.String(500)),
        sa.Column("teslim_alindi", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "teslim_alan_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_zaman(),
        sa.CheckConstraint(
            "karar IN ('IADE_TAMIR', 'IADE_HURDA', 'MUSTERIDE')", name="ck_sokulen_karar"
        ),
        sa.CheckConstraint("adet > 0", name="ck_sokulen_adet"),
        sa.CheckConstraint(
            "product_id IS NOT NULL OR length(trim(coalesce(tanim, ''))) > 0",
            name="ck_sokulen_tanim",
        ),
        sa.CheckConstraint(
            "karar = 'MUSTERIDE' OR warehouse_id IS NOT NULL", name="ck_sokulen_iade_depo"
        ),
    )
    op.create_index("ix_sokulen_is", "service_removed_parts", ["service_order_id"])

    op.alter_column("service_part_requests", "service_order_id", nullable=True)
    op.add_column("service_part_requests", sa.Column("hedef_depo_id", sa.BigInteger()))
    op.create_foreign_key(
        "fk_parca_talep_hedef_depo",
        "service_part_requests",
        "warehouses",
        ["hedef_depo_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_parca_talep_is_ya_da_ikmal",
        "service_part_requests",
        "service_order_id IS NOT NULL OR hedef_depo_id IS NOT NULL",
    )
    op.create_index(
        "uq_parca_talep_ikmal_acik",
        "service_part_requests",
        ["hedef_depo_id", "product_id"],
        unique=True,
        postgresql_where=sa.text(
            "service_order_id IS NULL AND durum IN ('ONAY_BEKLIYOR', 'ACIK') AND NOT is_deleted"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_parca_talep_ikmal_acik", table_name="service_part_requests")
    op.drop_constraint("ck_parca_talep_is_ya_da_ikmal", "service_part_requests", type_="check")
    op.drop_constraint("fk_parca_talep_hedef_depo", "service_part_requests", type_="foreignkey")
    op.drop_column("service_part_requests", "hedef_depo_id")
    op.execute("DELETE FROM service_part_requests WHERE service_order_id IS NULL")
    op.alter_column("service_part_requests", "service_order_id", nullable=False)
    op.drop_index("ix_sokulen_is", table_name="service_removed_parts")
    op.drop_table("service_removed_parts")
    op.drop_index("ix_parca_kullanim_durum", table_name="service_part_usage_reviews")
    op.drop_table("service_part_usage_reviews")
