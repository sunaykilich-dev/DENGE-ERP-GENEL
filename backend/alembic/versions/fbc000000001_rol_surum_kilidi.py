"""roles.version: rol–izin düzenleme ekranında iyimser kilit

Kullanıcı isteği (2026-11-09): "erişilebilen sayfalar ve izin verilen
aksiyonlar düzenlenebilsin admin tarafından". Rol–izin eşlemesi zaten
`role_permissions`'ta ve `PATCH /api/roller/{kod}` ile yazılıyordu; eksik olan
eşzamanlı düzenlemeye karşı kilitti. İki yönetici aynı rolü açıp kaydederse
ikincisi 409 alır (SQLAlchemy `version_id_col`).

YALNIZ EKLEME. BEDEL / GERİ ALMA: downgrade sütunu düşürür; kilit kalkar.

Revision ID: fbc000000001
Revises: fbb000000001
Create Date: 2026-11-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fbc000000001"
down_revision: str | None = "fbb000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roles", sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1"))
    )


def downgrade() -> None:
    op.drop_column("roles", "version")
