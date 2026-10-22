"""servis kiralama atolye bagi (teknik servis Dalga 2, migration 7/7)

NEDEN: Kiralama kurulum/toplama işleri servis işine bağlanır
(`service_orders.rental_id`); kiralama + tür başına tek AÇIK iş
(`uq_so_kiralama_tur_acik`; TAMAMLANDI açık sayılır çünkü yeniden açılabilir —
aksi hâlde ikinci iş açılır ve ilk iş TEKRAR_ACILDI olunca tekil indeks
patlardı). Kiralık cihaz atölyeye KIRALAMA_TAKIP kaydıyla gider
(`workshop_records.rental_asset_id`). Bağlar ayrı migration'dadır çünkü
atölye (2) ve kiralama (3) tabloları birbirinden önce/sonra açılır.
`work_orders`'a hiçbir şey yazılmaz.

BEDEL: Yalnız Dalga 0/2 yeni tablolarına iki nullable kolon. Downgrade
bağları siler (kayıtlar kalır).

Revision ID: d2a000000007
Revises: d2a000000006
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a000000007"
down_revision: str | None = "d2a000000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("service_orders", sa.Column("rental_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_so_kiralama", "service_orders", "rentals", ["rental_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(
        "uq_so_kiralama_tur_acik",
        "service_orders",
        ["rental_id", "tur"],
        unique=True,
        postgresql_where=sa.text(
            "rental_id IS NOT NULL AND status NOT IN ('KAPATILDI', 'IPTAL') AND NOT is_deleted"
        ),
    )
    op.add_column("workshop_records", sa.Column("rental_asset_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_atolye_kiralik_cihaz",
        "workshop_records",
        "rental_assets",
        ["rental_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_atolye_kiralik_cihaz", "workshop_records", type_="foreignkey")
    op.drop_column("workshop_records", "rental_asset_id")
    op.drop_index("uq_so_kiralama_tur_acik", table_name="service_orders")
    op.drop_constraint("fk_so_kiralama", "service_orders", type_="foreignkey")
    op.drop_column("service_orders", "rental_id")
