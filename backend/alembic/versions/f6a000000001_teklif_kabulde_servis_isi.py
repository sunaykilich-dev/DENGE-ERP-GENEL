"""servis teklifi: kabulde açılacak iş türü

Kullanıcı isteği (2026-11-05): satış destek bakım ve teknik servis teklifi
hazırlar; teklif onaylanıp müşteri kabul edince iş teknik servise düşer ve
diğer işlerle aynı adımlardan geçer (müdür → ekip lideri → teknisyen → lider
onayı → müdür son onayı).

Yalnız EKLEME: `quotes.servis_turu` (NULL = kabulde iş açılmaz; eski
davranış) + `ck_quote_servis_turu`. Mantık `services/quotes.kabulde_is_ac`.
İki aşamalı kapanış bir ayardır (`servis_kapanis_onay_zinciri`), şema
değişikliği istemez.

BEDEL / GERİ ALMA: downgrade sütunu düşürür; seçilmiş iş türleri kaybolur,
kabulde açılmış işler ve teklif bağları (`service_order_id`) kalır.

Revision ID: f6a000000001
Revises: f5a000000001
Create Date: 2026-11-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a000000001"
down_revision: str | None = "f5a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TURLER = ("PLANSIZ_BAKIM", "ARIZA", "DESTEK", "KURULUM", "KESIF", "DEMONTAJ", "TASIMA")


def upgrade() -> None:
    op.add_column("quotes", sa.Column("servis_turu", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_quote_servis_turu",
        "quotes",
        "servis_turu IS NULL OR servis_turu IN (" + ", ".join(f"'{t}'" for t in _TURLER) + ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_quote_servis_turu", "quotes", type_="check")
    op.drop_column("quotes", "servis_turu")
