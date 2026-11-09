"""irsaliye, boşluksuz belge sayacı ve sipariş muhasebe devri (KARARLAR 2026-11-09 S4.3/S4.4)

1. `belge_sayaclari` (seri, yıl → son_no): boşluksuz yıllık numara. Sayaç
   satırı belgeyle aynı işlemde artırılır; geri alınan işlem numara yakmaz.
2. `irsaliyeler` + `irsaliye_kalemleri`: depodan şirket dışına sevkte üretilen
   numaralı irsaliye (e-İrsaliye DEĞİL). Bir transferin tek irsaliyesi olur.
   Alıcı bilgisi dondurulur; satır fiyatı yalnız siparişten gelir (maliyet yok).
3. `orders.muhasebe_devri_at/by`, `orders.muhasebe_notu`: "muhasebeye
   devredildi" işareti (Logo entegrasyonu değil; fatura devri kalıbı).

Yalnız EKLEME yapar; mevcut satırlar ve kısıtlar değişmez. Geçmiş sevkiyatlar
için geriye dönük irsaliye ÜRETİLMEZ (numara o günün tarihine düşmez;
eski transferlerde elle yazılan `transfers.document_no` aynen kalır).

Geri alma: tablolar ve sipariş kolonları düşer (irsaliye verisi kaybolur).

Revision ID: fca000000001
Revises: fba000000001
Create Date: 2026-11-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fca000000001"
down_revision: str | None = "fba000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "belge_sayaclari",
        sa.Column("seri", sa.String(10), primary_key=True),
        sa.Column("yil", sa.Integer(), primary_key=True),
        sa.Column("son_no", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("son_no >= 0", name="ck_belge_sayaci_pozitif"),
    )

    op.create_table(
        "irsaliyeler",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("irsaliye_no", sa.String(20), nullable=False),
        sa.Column("yil", sa.Integer(), nullable=False),
        sa.Column("sira", sa.Integer(), nullable=False),
        sa.Column("durum", sa.String(16), server_default=sa.text("'DUZENLENDI'"), nullable=False),
        sa.Column(
            "transfer_id",
            sa.BigInteger(),
            sa.ForeignKey("transfers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id", ondelete="SET NULL")),
        sa.Column(
            "alici_account_id",
            sa.BigInteger(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("alici_unvan", sa.String(200), nullable=False),
        sa.Column("alici_vkn", sa.String(11)),
        sa.Column("alici_vergi_dairesi", sa.String(80)),
        sa.Column("alici_adres", sa.String(400)),
        sa.Column("hedef_konum", sa.String(20), nullable=False),
        sa.Column(
            "cikis_depo_id",
            sa.BigInteger(),
            sa.ForeignKey("warehouses.id", ondelete="SET NULL"),
        ),
        sa.Column("cikis_depo_adi", sa.String(100)),
        sa.Column("duzenleme_tarihi", sa.Date(), nullable=False),
        sa.Column("sevk_tarihi", sa.Date(), nullable=False),
        sa.Column("teslim_eden", sa.String(120)),
        sa.Column("notlar", sa.Text()),
        sa.Column("iptal_at", sa.DateTime(timezone=True)),
        sa.Column("iptal_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("iptal_nedeni", sa.String(300)),
        sa.Column("muhasebe_devri_at", sa.DateTime(timezone=True)),
        sa.Column(
            "muhasebe_devri_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("muhasebe_notu", sa.String(300)),
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
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.UniqueConstraint("irsaliye_no", name="uq_irsaliye_no"),
        sa.UniqueConstraint("yil", "sira", name="uq_irsaliye_yil_sira"),
        sa.UniqueConstraint("transfer_id", name="uq_irsaliye_transfer"),
        sa.CheckConstraint("durum IN ('DUZENLENDI','IPTAL')", name="ck_irsaliye_durum"),
        sa.CheckConstraint(
            "durum <> 'IPTAL' OR length(trim(coalesce(iptal_nedeni, ''))) > 0",
            name="ck_irsaliye_iptal_nedeni",
        ),
    )
    op.create_index("ix_irsaliye_order", "irsaliyeler", ["order_id"])
    op.create_index("ix_irsaliye_alici", "irsaliyeler", ["alici_account_id"])
    op.create_index("ix_irsaliye_tarih", "irsaliyeler", ["duzenleme_tarihi"])

    op.create_table(
        "irsaliye_kalemleri",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "irsaliye_id",
            sa.BigInteger(),
            sa.ForeignKey("irsaliyeler.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sira", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column(
            "order_line_id",
            sa.BigInteger(),
            sa.ForeignKey("order_lines.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "stock_movement_id",
            sa.BigInteger(),
            sa.ForeignKey("stock_movements.id", ondelete="SET NULL"),
        ),
        sa.Column("urun_kodu", sa.String(40)),
        sa.Column("aciklama", sa.String(300), nullable=False),
        sa.Column("miktar", sa.Numeric(12, 2), nullable=False),
        sa.Column("birim", sa.String(10), server_default=sa.text("'ADET'"), nullable=False),
        sa.Column("seri_nolar", sa.Text()),
        sa.Column("birim_fiyat", sa.Numeric(14, 2)),
        sa.Column("iskonto_yuzde", sa.Numeric(5, 2)),
        sa.Column("kdv_orani", sa.Numeric(5, 4)),
        sa.CheckConstraint("miktar > 0", name="ck_irsaliye_kalem_miktar"),
    )
    op.create_index("ix_irsaliye_kalem_irsaliye", "irsaliye_kalemleri", ["irsaliye_id"])

    op.add_column("orders", sa.Column("muhasebe_devri_at", sa.DateTime(timezone=True)))
    op.add_column(
        "orders",
        sa.Column(
            "muhasebe_devri_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
    )
    op.add_column("orders", sa.Column("muhasebe_notu", sa.String(300)))


def downgrade() -> None:
    op.drop_column("orders", "muhasebe_notu")
    op.drop_column("orders", "muhasebe_devri_by")
    op.drop_column("orders", "muhasebe_devri_at")
    op.drop_index("ix_irsaliye_kalem_irsaliye", table_name="irsaliye_kalemleri")
    op.drop_table("irsaliye_kalemleri")
    op.drop_index("ix_irsaliye_tarih", table_name="irsaliyeler")
    op.drop_index("ix_irsaliye_alici", table_name="irsaliyeler")
    op.drop_index("ix_irsaliye_order", table_name="irsaliyeler")
    op.drop_table("irsaliyeler")
    op.drop_table("belge_sayaclari")
