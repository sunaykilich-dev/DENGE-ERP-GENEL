"""Şirket bazlı ürün, stok ve hat (2026-11-23 sahip kararı)

Her şirket yalnız kendi kalemlerini görür: DENGE MOBİLİTE kendi ürün/cihaz/
hatlarını, DENGE TELEKOM kendi cihazlarını, DENGE ELEKTRONİK güvenlik
cihazlarını. Stok ve hat ekranları üç şirkete açılır, etkin şirkete süzülür.

- `products.sirket` (NULL = ORTAK ürün, her şirkette görünür);
- `sim_cards.sirket` (her hat tek şirkete aittir).

Cihazın ayrı sütunu yoktur: cihazın şirketi ürününkidir. Depo şirketi
`birim → birim_sirketleri` eşlemesinden gelir (NULL birim = ortak).

Veri: bütün mevcut hatlar → MOBILITE. Ürünlerden IMEI'li olanlar, SIM paketi
/ abonelik planı tipindekiler ve herhangi bir cihazın bağlı olduğu ürünler →
MOBILITE (canlı veri mobilite verisidir); kalanı ortak (NULL) kalır.

Kod listesi bu dosyada DONUKTUR (göç anının kopyası; `models/rbac.SIRKET_KODLARI`
ile aynı).

Revision ID: fcl000000001
Revises: fck000000001
Create Date: 2026-11-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fcl000000001"
down_revision: str | None = "fck000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIRKET_KODLARI = ("TELEKOM", "ELEKTRONIK", "MOBILITE")
_KISIT = "sirket IS NULL OR sirket IN (" + ", ".join(f"'{k}'" for k in SIRKET_KODLARI) + ")"

# (tablo, kısıt, indeks)
_TABLOLAR = (
    ("products", "ck_products_sirket", "ix_products_sirket"),
    ("sim_cards", "ck_sim_sirket", "ix_sim_sirket"),
)


def upgrade() -> None:
    for tablo, kisit, indeks in _TABLOLAR:
        op.add_column(tablo, sa.Column("sirket", sa.String(20), nullable=True))
        op.create_check_constraint(kisit, tablo, _KISIT)
        op.create_index(indeks, tablo, ["sirket"])

    op.execute("UPDATE sim_cards SET sirket = 'MOBILITE'")
    op.execute(
        """
        UPDATE products p
        SET sirket = 'MOBILITE'
        WHERE p.identity_kind = 'IMEI'
           OR p.type IN ('SIM_PAKETI', 'ABONELIK_PLANI')
           OR EXISTS (SELECT 1 FROM devices d WHERE d.product_id = p.id)
        """
    )


def downgrade() -> None:
    for tablo, kisit, indeks in reversed(_TABLOLAR):
        op.drop_index(indeks, table_name=tablo)
        op.drop_constraint(kisit, tablo, type_="check")
        op.drop_column(tablo, "sirket")
