"""Servis işinde elle yazılan plaka (KARARLAR 2026-11-25)

Şirket aracında plaka araç havuzunda yoksa metin olarak saklanır; havuzdaki
plakayla eşleşirse ayrıca servis_arac_id de dolar.

Revision ID: fci000000001
Revises: fch000000001
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fci000000001"
down_revision: str | Sequence[str] | None = "fch000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("service_orders", sa.Column("arac_plaka", sa.String(20)))
    # Önceden havuzdan seçilmiş araçların plakası metne de yazılır.
    op.execute(
        "UPDATE service_orders so SET arac_plaka = v.plate "
        "FROM service_vehicles v WHERE so.servis_arac_id = v.id AND so.arac_plaka IS NULL"
    )


def downgrade() -> None:
    op.drop_column("service_orders", "arac_plaka")
