"""Zaman bölümü 18 saat üst sınırı şimdilik kaldırıldı

2026-11-10 kullanıcı kararı: uzun süre açık kalmış sayaç "Bitir" ile
kapatılamıyordu ("Bölüm 18 saati aşamaz"). Sınır şimdilik kalkar; uzun sayaç
uyarısı yerinde durur. Downgrade kısıtı NOT VALID ekler: aradaki dönemde 18
saati aşan kayıtlar oluşmuş olabilir, onları bozmaz, yalnız yenileri denetler.

Revision ID: fcg000000001
Revises: fcf000000001
Create Date: 2026-11-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "fcg000000001"
down_revision: str | Sequence[str] | None = "fcf000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_ste_azami_sure", "service_time_entries", type_="check")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE service_time_entries ADD CONSTRAINT ck_ste_azami_sure "
        "CHECK (ended_at IS NULL OR ended_at <= started_at + interval '18 hours') NOT VALID"
    )
