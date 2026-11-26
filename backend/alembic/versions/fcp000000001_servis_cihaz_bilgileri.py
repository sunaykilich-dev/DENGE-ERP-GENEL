"""Servis işinde cihaz başına bilgi: not, müşteri şikayeti, durum, onarım

2026-11-24 sahip kararı: bir servis işine birden fazla cihaz eklenebilir ve
her cihazın kendi bilgisi tutulur (`service_order_serials`):

- `notlar`, `musteri_sikayeti`: yalnız personel görür.
- `cihaz_durumu` (CALISIYOR/ARIZALI/HASARLI/PARCA_EKSIK) + açıklaması ve
  `onarim_bilgisi`: onarım fişinde müşteriye basılır.

Var olan satırlar NULL kalır. Downgrade sütunları ve kısıtı düşürür.

Revision ID: fcp000000001
Revises: fco000000001
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fcp000000001"
down_revision: str | None = "fco000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "service_order_serials"


def upgrade() -> None:
    op.add_column(T, sa.Column("notlar", sa.Text(), nullable=True))
    op.add_column(T, sa.Column("musteri_sikayeti", sa.Text(), nullable=True))
    op.add_column(T, sa.Column("cihaz_durumu", sa.String(20), nullable=True))
    op.add_column(T, sa.Column("cihaz_durumu_aciklama", sa.String(500), nullable=True))
    op.add_column(T, sa.Column("onarim_bilgisi", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_sos_cihaz_durumu",
        T,
        "cihaz_durumu IS NULL OR cihaz_durumu IN "
        "('ARIZALI', 'CALISIYOR', 'HASARLI', 'PARCA_EKSIK')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sos_cihaz_durumu", T, type_="check")
    for sutun in (
        "onarim_bilgisi",
        "cihaz_durumu_aciklama",
        "cihaz_durumu",
        "musteri_sikayeti",
        "notlar",
    ):
        op.drop_column(T, sutun)
