"""servis işine kütükten cihaz bilgisi: kayıtlı frekans

Kullanıcı isteği (2026-11-06): Haberleşme arıza işinde müşterinin kayıtlı
frekansı o seri/röle için kütükten alınıp işe otomatik gelsin; Güvenlikte
X-ray / kapı dedektörü seri numarası kütükten gelsin; kütükte yoksa iş
kapatılmadan teknisyen girsin (KARARLAR 2026-10-28 §12).

Yalnız EKLEME:
- `service_equipment.frekans` (JSONB, boş olabilir): kütükteki kayıtlı frekans.
- `service_frekans_bilgisi`: arıza işine kopyalanan frekans (iş başına bir
  kayıt, kaynak KUTUK / ROLE_MONTAJ / TEKNISYEN, iyimser kilit).

Güvenlik seri numarası için tablo yok: seri, işin mevcut seri listesinde
(`service_order_serials`) tutulur.

BEDEL / GERİ ALMA: downgrade tabloyu ve sütunu düşürür; kütüğe ve işlere
girilmiş frekanslar kaybolur. İşler ve kapanışları etkilenmez.

Revision ID: f9a000000001
Revises: f7a000000001
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f9a000000001"
down_revision: str | None = "f7a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("service_equipment", sa.Column("frekans", postgresql.JSONB(), nullable=True))
    op.create_table(
        "service_frekans_bilgisi",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "service_order_id",
            sa.BigInteger(),
            sa.ForeignKey("service_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("seri_no", sa.String(200), nullable=True),
        sa.Column(
            "equipment_id",
            sa.BigInteger(),
            sa.ForeignKey("service_equipment.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kaynak", sa.String(20), nullable=False),
        sa.Column(
            "frekans",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("service_order_id", name="uq_sfb_is"),
        sa.CheckConstraint("kaynak IN ('KUTUK', 'ROLE_MONTAJ', 'TEKNISYEN')", name="ck_sfb_kaynak"),
    )


def downgrade() -> None:
    op.drop_table("service_frekans_bilgisi")
    op.drop_column("service_equipment", "frekans")
