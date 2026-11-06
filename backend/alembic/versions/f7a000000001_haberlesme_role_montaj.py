"""haberleşme saha işi: işin niteliği ve röle montaj bilgileri

Kullanıcı isteği (2026-11-06): "Repeater Montaj Bilgileri" kütüğünün
sütunları Haberleşme kurulum/montaj işlerinde zorunlu alan olsun;
doldurulmazsa iş kapatılamasın. Haberleşme saha işi açılırken işin niteliği
çoktan seçmeli seçilir (`service_orders.nitelikler`, `ck_so_nitelikler`).
Var olan Haberleşme işlerinin niteliği türünden doldurulur.

Yalnız EKLEME: `service_role_montaj` (iş başına bir kayıt, alanlar JSONB,
iyimser kilit). Alan listesi ve zorunluluk kuralı kodda
(`services/teknik_servis/role_montaj.ALANLAR`): kütüğe sütun eklenince
şema değişmez.

BEDEL / GERİ ALMA: downgrade tabloyu ve nitelik sütununu düşürür; girilmiş
montaj bilgileri ve nitelik seçimleri kaybolur. İşler ve kapanışları etkilenmez.

Revision ID: f7a000000001
Revises: f6a000000001
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f7a000000001"
down_revision: str | None = "f6a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NITELIKLER = ("KURULUM", "MONTAJ", "DEMONTAJ", "ARIZA", "BAKIM", "PROGRAMLAMA", "KESIF", "DIGER")
# Var olan işlere türden varsayılan nitelik (`role_montaj.TUR_NITELIGI` ile aynı).
_TUR_NITELIGI = {
    "KURULUM": "KURULUM",
    "DEMONTAJ": "DEMONTAJ",
    "ARIZA": "ARIZA",
    "PB": "BAKIM",
    "PLANSIZ_BAKIM": "BAKIM",
    "KESIF": "KESIF",
}


def upgrade() -> None:
    op.add_column(
        "service_orders",
        sa.Column("nitelikler", postgresql.ARRAY(sa.String(length=20)), nullable=True),
    )
    op.create_check_constraint(
        "ck_so_nitelikler",
        "service_orders",
        "nitelikler IS NULL OR (cardinality(nitelikler) > 0 AND nitelikler <@ ARRAY["
        + ", ".join(f"'{n}'" for n in _NITELIKLER)
        + "]::varchar[])",
    )
    durum = " ".join(f"WHEN '{t}' THEN '{n}'" for t, n in _TUR_NITELIGI.items())
    # Değerler yukarıdaki sabitlerden; kullanıcı girdisi yok.
    sql = (
        "UPDATE service_orders SET nitelikler = ARRAY[CASE tur "  # noqa: S608
        + durum
        + " ELSE 'DIGER' END]::varchar[] WHERE birim = 'HABERLESME' AND tur <> 'ATOLYE'"
    )
    op.execute(sql)
    op.create_table(
        "service_role_montaj",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "service_order_id",
            sa.BigInteger(),
            sa.ForeignKey("service_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "alanlar",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.UniqueConstraint("service_order_id", name="uq_srm_is"),
    )


def downgrade() -> None:
    op.drop_table("service_role_montaj")
    op.drop_constraint("ck_so_nitelikler", "service_orders", type_="check")
    op.drop_column("service_orders", "nitelikler")
