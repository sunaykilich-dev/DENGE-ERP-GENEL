"""Birleşim: satış/irsaliye/Ana Panel paketleri (fce) + depo oturumu (fbd)

`fce000000001` (KARARLAR_2026-11-09 S1–S4, S6, S8) ile depo oturumunun
zinciri (fbb parça talebi amir onayı → fbc roles.version → fbd S5 sahada
parça al-ver) aynı `fba000000001` üzerinden ayrıldı. Yalnız zinciri tek
head'e bağlar; şema değiştirmez.

Revision ID: fcf000000001
Revises: fce000000001, fbd000000001
Create Date: 2026-11-09

"""

from collections.abc import Sequence

revision: str = "fcf000000001"
down_revision: str | Sequence[str] | None = ("fce000000001", "fbd000000001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
