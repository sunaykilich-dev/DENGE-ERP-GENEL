"""bakım sözleşmesi karar tarihi

Kullanıcı isteği (2026-11-05): sözleşme karar tarihleri sonradan toplu
verilecek; sistem yıllık bakım adedine göre hangi ayda bakım yapılacağını
hesaplayıp PB işlerini zamanı gelince otomatik açacak.

Yalnız EKLEME: `maintenance_contracts.decision_date` (DATE, NULL = karar
tarihi girilmedi). Takvim mantığı `app.services.teknik_servis.bakim_karar`.

BEDEL / GERİ ALMA: downgrade sütunu düşürür; girilmiş karar tarihleri kaybolur
(başlangıç tarihi `valid_from` ve hesaplanmış dönemler kalır).

Revision ID: f4a000000001
Revises: f3a000000001
Create Date: 2026-11-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a000000001"
down_revision: str | None = "f3a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("maintenance_contracts", sa.Column("decision_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("maintenance_contracts", "decision_date")
