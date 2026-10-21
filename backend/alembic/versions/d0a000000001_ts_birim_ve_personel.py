"""ts birim ve personel (teknik servis Dalga 0, migration 1/7)

NEDEN: Teknik servis kayıtları birime göre kapsanır (KENDI_BIRIMI /
KENDI_ISLERI) ve personel = kullanıcıdır (ayrı `personnel` tablosu açılmaz,
plan §1.1, KD-03). Bunun için:

* `user_units` — kullanıcı–birim üyeliği (çoklu; tek birincil). Satırı
  olmayan birim kapsamlı kullanıcı hiçbir servis kaydı görmez (fail-closed).
* `users` personel kolonları — `giris_acik` (oturum açabilir mi; `is_active`
  kaydın canlı olmasıdır, ikisi ayrı), sicil, ünvan, saha rolü, ayrılış,
  yönetici, parola yaşam döngüsü alanları.
* `personnel_name_maps` — eski sistemde ad metniyle tutulan personelin
  onaylı kullanıcı eşlemesi (göç ön koşulu).

BEDEL: `users` canlı tablosuna yalnız nullable ya da varsayılanlı kolon
eklenir; mevcut kullanıcılar `giris_acik=true` olur (bugünkü davranış),
birim ve saha rolü UYDURULMAZ (boş kalır). Yeni CHECK'ler yalnız yeni
kolonlardadır; mevcut CHECK'lere dokunulmaz. Downgrade kolonları ve
tabloları düşürür: o ana kadar girilmiş personel bilgisi (sicil, ayrılış,
birim üyeliği) kaybolur — canlıda downgrade yok (KD-27), yedekten dönülür.

Revision ID: d0a000000001
Revises: b30e012dd879
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0a000000001"
down_revision: str | None = "b30e012dd879"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BIRIMLER = "'GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP'"


def upgrade() -> None:
    op.create_table(
        "personnel_name_maps",
        sa.Column("kaynak_sistem", sa.String(length=30), nullable=False),
        sa.Column("kaynak_alan", sa.String(length=60), nullable=False),
        sa.Column("kaynak_ad", sa.String(length=150), nullable=False),
        sa.Column("normal_ad", sa.String(length=150), nullable=False),
        sa.Column("kayit_sayisi", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("onerilen_user_id", sa.BigInteger(), nullable=True),
        sa.Column("onaylanan_user_id", sa.BigInteger(), nullable=True),
        sa.Column("durum", sa.String(length=12), server_default=sa.text("'ONERI'"), nullable=False),
        sa.Column("onaylayan_id", sa.BigInteger(), nullable=True),
        sa.Column("onay_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "durum IN ('ONERI', 'ONAYLANDI', 'ESLESMEDI', 'REDDEDILDI')", name="ck_pnm_durum"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["onaylanan_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["onaylayan_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["onerilen_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kaynak_sistem", "kaynak_alan", "normal_ad", name="uq_pnm_kaynak"),
    )
    op.create_table(
        "user_units",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint(f"birim IN ({_BIRIMLER})", name="ck_user_units_birim"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "birim"),
    )
    op.create_index(
        "uq_user_units_birincil",
        "user_units",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    # --- users: personel kolonları (hepsi nullable ya da varsayılanlı) -------
    op.add_column(
        "users",
        sa.Column("giris_acik", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("users", sa.Column("sicil_no", sa.String(length=30), nullable=True))
    op.add_column("users", sa.Column("unvan", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("saha_rolu", sa.String(length=12), nullable=True))
    op.add_column("users", sa.Column("ise_giris_tarihi", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("ayrilis_tarihi", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("ayrilis_nedeni", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("ayrilisi_yapan_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("yonetici_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("personel_notu", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "parola_degismeli", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "users", sa.Column("gecici_parola_bitis", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("parola_degisti_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("son_giris_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_users_sicil_no",
        "users",
        ["sicil_no"],
        unique=True,
        postgresql_where=sa.text("sicil_no IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_users_yonetici", "users", "users", ["yonetici_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_users_ayrilisi_yapan",
        "users",
        "users",
        ["ayrilisi_yapan_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Yeni CHECK'ler yalnız YENİ kolonlarda (mevcut kısıtlara dokunulmaz).
    op.create_check_constraint(
        "ck_users_saha_rolu",
        "users",
        "saha_rolu IS NULL OR saha_rolu IN ('SEF', 'TEKNISYEN', 'STAJYER', 'OFIS', 'YOK')",
    )
    op.create_check_constraint(
        "ck_users_ayrilis_nedeni",
        "users",
        "ayrilis_nedeni IS NULL OR ayrilis_nedeni IN "
        "('ISTIFA', 'FESIH', 'EMEKLILIK', 'SOZLESME_BITIMI', 'DIGER')",
    )
    op.create_check_constraint(
        "ck_users_ayrilis", "users", "(ayrilis_tarihi IS NULL) = (ayrilis_nedeni IS NULL)"
    )
    op.create_check_constraint(
        "ck_users_yonetici_kendisi", "users", "yonetici_id IS NULL OR yonetici_id <> id"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_yonetici_kendisi", "users", type_="check")
    op.drop_constraint("ck_users_ayrilis", "users", type_="check")
    op.drop_constraint("ck_users_ayrilis_nedeni", "users", type_="check")
    op.drop_constraint("ck_users_saha_rolu", "users", type_="check")
    op.drop_constraint("fk_users_ayrilisi_yapan", "users", type_="foreignkey")
    op.drop_constraint("fk_users_yonetici", "users", type_="foreignkey")
    op.drop_index("uq_users_sicil_no", table_name="users")
    for kolon in (
        "son_giris_at",
        "parola_degisti_at",
        "gecici_parola_bitis",
        "parola_degismeli",
        "personel_notu",
        "yonetici_id",
        "ayrilisi_yapan_id",
        "ayrilis_nedeni",
        "ayrilis_tarihi",
        "ise_giris_tarihi",
        "saha_rolu",
        "unvan",
        "sicil_no",
        "giris_acik",
    ):
        op.drop_column("users", kolon)
    op.drop_index("uq_user_units_birincil", table_name="user_units")
    op.drop_table("user_units")
    op.drop_table("personnel_name_maps")
