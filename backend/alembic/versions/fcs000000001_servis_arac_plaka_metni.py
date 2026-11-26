"""Servis işinde elle yazılan plaka (KARARLAR 2026-11-25)

Şirket aracında plaka araç havuzunda yoksa metin olarak saklanır; havuzdaki
plakayla eşleşirse ayrıca servis_arac_id de dolar.

Not: ilk hâli `fci000000001` kimliğiyle yazılmıştı; aynı kimlik paralel dalda
(`fci000000001_tayin_gecikti_bildirimi`) kullanıldığı için birleştirmede zincirin
sonuna taşındı. Sütun `IF NOT EXISTS` ile eklenir: eski kimlikle bu sütunu almış
bir veritabanı da sorunsuz yükselir.

Revision ID: fcs000000001
Revises: fcr000000001
Create Date: 2026-11-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "fcs000000001"
down_revision: str | Sequence[str] | None = "fcr000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE service_orders ADD COLUMN IF NOT EXISTS arac_plaka VARCHAR(20)")
    # Önceden havuzdan seçilmiş araçların plakası metne de yazılır.
    op.execute(
        "UPDATE service_orders so SET arac_plaka = v.plate "
        "FROM service_vehicles v WHERE so.servis_arac_id = v.id AND so.arac_plaka IS NULL"
    )


def downgrade() -> None:
    op.drop_column("service_orders", "arac_plaka")
