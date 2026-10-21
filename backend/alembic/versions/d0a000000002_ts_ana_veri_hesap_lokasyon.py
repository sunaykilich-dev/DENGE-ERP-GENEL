"""ts ana veri hesap lokasyon (teknik servis Dalga 0, migration 2/7)

NEDEN: Servis müşterisi = `accounts(is_musteri)`, gidilen yer = carinin
`addresses(kind='TESIS')` satırı (plan §1.5). Ayrı `customers`/`sites` tablosu
ikinci bir kimlik kaynağı olurdu; teklif, servis işi, sözleşme ve kiralama
aynı satıra bağlanmalı. Bunun için:

* `accounts`: doğrulama (`is_verified`, hızlı eklenen müşteri `false` doğar),
  muhasebe cari kodu (`dis_referans`, yalnız metin), ekrandan birleştirme
  hedefi (`merged_into_id`).
* `addresses`: tür (MERKEZ/FATURA/SEVK/TESIS), tesis adı ve anahtarı (trgm),
  erişim notu, birincil irtibat, aktif/doğrulama bayrakları, aktör, iyimser
  kilit ve göç kimliği.
* `contacts.address_id`: lokasyon irtibatı.
* `account_aliases` (takma ad, global tekil anahtar), `account_merges`
  (değişmez birleştirme kaydı).
* `quotes.address_id`: servis teklifinin tesisi (E14-15).

BEDEL / ONAYLI İSTİSNA (plan §1.12, KD-33): `addresses.line` NOT NULL
kaldırılır — yalnız TESIS satırı adres metni olmadan kurulabilir; diğer
türlerde eski kural `ck_addresses_satir` ile korunur (var olan bütün
satırlar dolu, kısıt sorunsuz kurulur). Var olan adresler MERKEZ olur,
hesaplar doğrulanmış sayılır: mobilite davranışı değişmez. Downgrade, adres
metni olmayan TESIS satırı varsa DURUR (NOT NULL geri konamaz; satırı
silmek veriyi uydurmadan kaybetmek olurdu) — önce elle düzeltilmelidir.

Revision ID: d0a000000002
Revises: d0a000000001
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d0a000000002"
down_revision: str | None = "d0a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _zaman_ve_aktor() -> list[sa.Column]:
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
    ]


def upgrade() -> None:
    # --- accounts -----------------------------------------------------------
    op.add_column(
        "accounts",
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("accounts", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("accounts", sa.Column("verified_by", sa.BigInteger(), nullable=True))
    op.add_column("accounts", sa.Column("dis_referans", sa.String(length=40), nullable=True))
    op.add_column("accounts", sa.Column("merged_into_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_accounts_dis_referans", "accounts", ["dis_referans"], unique=False)
    op.create_foreign_key(
        "fk_accounts_birlesti",
        "accounts",
        "accounts",
        ["merged_into_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_accounts_dogrulayan",
        "accounts",
        "users",
        ["verified_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_accounts_birlesen_silinmis", "accounts", "merged_into_id IS NULL OR is_deleted"
    )
    op.create_check_constraint("ck_accounts_kendine_birlesemez", "accounts", "merged_into_id <> id")

    # --- addresses ------------------------------------------------------------
    op.add_column(
        "addresses",
        sa.Column("kind", sa.String(length=10), server_default=sa.text("'MERKEZ'"), nullable=False),
    )
    op.add_column("addresses", sa.Column("site_name", sa.String(length=200), nullable=True))
    op.add_column("addresses", sa.Column("site_key", sa.String(length=200), nullable=True))
    op.add_column("addresses", sa.Column("access_note", sa.Text(), nullable=True))
    op.add_column("addresses", sa.Column("primary_contact_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "addresses",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "addresses",
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("addresses", sa.Column("created_by", sa.BigInteger(), nullable=True))
    op.add_column("addresses", sa.Column("updated_by", sa.BigInteger(), nullable=True))
    op.add_column(
        "addresses",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("addresses", sa.Column("source_system", sa.String(length=20), nullable=True))
    op.add_column("addresses", sa.Column("source_ref", sa.String(length=64), nullable=True))
    # ONAYLI İSTİSNA: yalnız TESIS'te boş olabilir (ck_addresses_satir).
    op.alter_column("addresses", "line", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "ck_addresses_tur", "addresses", "kind IN ('MERKEZ', 'FATURA', 'SEVK', 'TESIS')"
    )
    op.create_check_constraint(
        "ck_addresses_satir", "addresses", "kind = 'TESIS' OR line IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_addresses_tesis_adi", "addresses", "kind <> 'TESIS' OR site_name IS NOT NULL"
    )
    op.create_index(
        "ix_addresses_hesap_tur", "addresses", ["account_id", "kind", "is_active"], unique=False
    )
    op.create_index(
        "ix_addresses_tesis_trgm",
        "addresses",
        [sa.literal_column("site_key gin_trgm_ops")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_unique_constraint("uq_addresses_kaynak", "addresses", ["source_system", "source_ref"])
    op.create_index(
        "uq_addresses_tesis_aktif",
        "addresses",
        ["account_id", "site_key"],
        unique=True,
        postgresql_where=sa.text("kind = 'TESIS' AND is_active"),
    )
    op.create_foreign_key(
        "fk_addresses_birincil_irtibat",
        "addresses",
        "contacts",
        ["primary_contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_addresses_created_by", "addresses", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_addresses_updated_by", "addresses", "users", ["updated_by"], ["id"], ondelete="SET NULL"
    )

    # --- contacts / quotes --------------------------------------------------------
    op.add_column("contacts", sa.Column("address_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_contacts_adres", "contacts", ["address_id"], unique=False)
    op.create_foreign_key(
        "fk_contacts_adres", "contacts", "addresses", ["address_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("quotes", sa.Column("address_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_quotes_address_id", "quotes", ["address_id"], unique=False)
    op.create_foreign_key(
        "fk_quotes_adres", "quotes", "addresses", ["address_id"], ["id"], ondelete="SET NULL"
    )

    # --- yeni tablolar -----------------------------------------------------------
    op.create_table(
        "account_aliases",
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("address_id", sa.BigInteger(), nullable=True),
        sa.Column("alias_text", sa.String(length=250), nullable=False),
        sa.Column("alias_key", sa.String(length=250), nullable=False),
        sa.Column("kaynak", sa.String(length=12), nullable=False),
        sa.Column("kaynak_tablo", sa.String(length=40), nullable=True),
        *_zaman_ve_aktor(),
        sa.CheckConstraint(
            "kaynak IN ('ELLE', 'ESLESTIRME', 'BIRLESTIRME', 'GOC')",
            name="ck_account_aliases_kaynak",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias_key", name="uq_account_aliases_anahtar"),
    )
    op.create_index(
        "ix_account_aliases_account_id", "account_aliases", ["account_id"], unique=False
    )
    op.create_index(
        "ix_account_aliases_trgm",
        "account_aliases",
        [sa.literal_column("alias_key gin_trgm_ops")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "account_merges",
        sa.Column("tur", sa.String(length=10), nullable=False),
        sa.Column("kaynak_id", sa.BigInteger(), nullable=False),
        sa.Column("hedef_id", sa.BigInteger(), nullable=False),
        sa.Column("gerekce", sa.Text(), nullable=False),
        sa.Column("onizleme", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tasinan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("doldurulan_alanlar", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("eklenen_roller", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_zaman_ve_aktor(),
        sa.CheckConstraint("tur IN ('HESAP', 'LOKASYON')", name="ck_account_merges_tur"),
        sa.CheckConstraint("kaynak_id <> hedef_id", name="ck_account_merges_farkli"),
        sa.CheckConstraint("length(trim(gerekce)) >= 5", name="ck_account_merges_gerekce"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    baglanti = op.get_bind()
    adressiz = baglanti.execute(
        sa.text("SELECT count(*) FROM addresses WHERE line IS NULL")
    ).scalar_one()
    if adressiz:
        raise RuntimeError(
            f"{adressiz} adres satırında adres metni yok (hızlı eklenen TESIS). "
            "addresses.line yeniden NOT NULL yapılamaz; önce bu satırlara adres "
            "metni girin. Veri uydurulmadan otomatik geri dönüş yapılmaz."
        )

    op.drop_table("account_merges")
    op.drop_index("ix_account_aliases_trgm", table_name="account_aliases")
    op.drop_index("ix_account_aliases_account_id", table_name="account_aliases")
    op.drop_table("account_aliases")

    op.drop_constraint("fk_quotes_adres", "quotes", type_="foreignkey")
    op.drop_index("ix_quotes_address_id", table_name="quotes")
    op.drop_column("quotes", "address_id")
    op.drop_constraint("fk_contacts_adres", "contacts", type_="foreignkey")
    op.drop_index("ix_contacts_adres", table_name="contacts")
    op.drop_column("contacts", "address_id")

    op.drop_constraint("fk_addresses_updated_by", "addresses", type_="foreignkey")
    op.drop_constraint("fk_addresses_created_by", "addresses", type_="foreignkey")
    op.drop_constraint("fk_addresses_birincil_irtibat", "addresses", type_="foreignkey")
    op.drop_index("uq_addresses_tesis_aktif", table_name="addresses")
    op.drop_constraint("uq_addresses_kaynak", "addresses", type_="unique")
    op.drop_index("ix_addresses_tesis_trgm", table_name="addresses")
    op.drop_index("ix_addresses_hesap_tur", table_name="addresses")
    op.drop_constraint("ck_addresses_tesis_adi", "addresses", type_="check")
    op.drop_constraint("ck_addresses_satir", "addresses", type_="check")
    op.drop_constraint("ck_addresses_tur", "addresses", type_="check")
    op.alter_column("addresses", "line", existing_type=sa.Text(), nullable=False)
    for kolon in (
        "source_ref",
        "source_system",
        "version",
        "updated_by",
        "created_by",
        "is_verified",
        "is_active",
        "primary_contact_id",
        "access_note",
        "site_key",
        "site_name",
        "kind",
    ):
        op.drop_column("addresses", kolon)

    op.drop_constraint("ck_accounts_kendine_birlesemez", "accounts", type_="check")
    op.drop_constraint("ck_accounts_birlesen_silinmis", "accounts", type_="check")
    op.drop_constraint("fk_accounts_dogrulayan", "accounts", type_="foreignkey")
    op.drop_constraint("fk_accounts_birlesti", "accounts", type_="foreignkey")
    op.drop_index("ix_accounts_dis_referans", table_name="accounts")
    for kolon in ("merged_into_id", "dis_referans", "verified_by", "verified_at", "is_verified"):
        op.drop_column("accounts", kolon)
