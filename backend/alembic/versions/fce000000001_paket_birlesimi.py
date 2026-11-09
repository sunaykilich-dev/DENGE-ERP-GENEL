"""Birleşim: Ana Panel düzeni + irsaliye/muhasebe devri + satış paketi

Üç paket (KARARLAR_2026-11-09 S1–S4.2, S4.3–S6, S8) ayrı dallarda aynı
`fba000000001` üzerine geliştirildi. Bu revizyon yalnız zinciri tek head'e
bağlar; şema değiştirmez. Üç paketin tabloları birbirinden bağımsızdır,
sıra önemsizdir.

Revision ID: fce000000001
Revises: fca000000001, fcd000000001, fcsatis00001
Create Date: 2026-11-09

"""

from collections.abc import Sequence

revision: str = "fce000000001"
down_revision: str | Sequence[str] | None = ("fca000000001", "fcd000000001", "fcsatis00001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
