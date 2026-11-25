"""Servis işinde cihaz başına aksesuar (2026-11-25 sahip isteği)

Yeni servis kaydındaki her cihaz kartında atölye kabulündeki aksesuar
kutucukları: `service_order_serials.aksesuarlar` JSONB
([{kind, qty, description}]); türler `servis_atolye.AKSESUAR_TURLERI`,
doğrulama uygulamada (`cihaz_notlari`).

Revision ID: fcr000000001
Revises: fcq000000001
Create Date: 2026-11-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "fcr000000001"
down_revision: str | None = "fcq000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("service_order_serials", sa.Column("aksesuarlar", JSONB))


def downgrade() -> None:
    op.drop_column("service_order_serials", "aksesuarlar")
