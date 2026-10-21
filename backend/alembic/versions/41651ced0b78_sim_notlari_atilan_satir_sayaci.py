"""sim notlari, atilan satir sayaci

İki eksik kolon:

* `sim_cards.notes` — içe aktarma şablonu "Not" sütununu belgeliyor ve
  profil değeri `SimCard(**alanlar)` ile geçiriyordu; kolon olmadığı için
  Not sütunu dolu her dosya uygula adımında 500 veriyordu.
* `import_batches.dropped_rows` — dosyada dolu ama okunamayan satır sayısı.
  Bu satırlar sayılmadan atılıyordu; kullanıcı 5 satırlık dosyada
  "2 satır okundu" görüp eksiğin nerede olduğunu anlayamıyordu.

Revision ID: 41651ced0b78
Revises: 052eebc771f1
Create Date: 2026-09-23 16:06:34.262014

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "41651ced0b78"
down_revision: Union[str, None] = "052eebc771f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "import_batches",
        sa.Column("dropped_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("sim_cards", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sim_cards", "notes")
    op.drop_column("import_batches", "dropped_rows")
