"""Ana Panel düzeni: kişisel ve rol varsayılanı düzen tablosu

Kullanıcı isteği (2026-11-09): "ana paneli kullanıcı istediği gibi
düzenleyebilsin custom olarak ayarla". Kararlar: KARARLAR_2026-11-09 S8
(kişisel düzen sunucuda, bileşen yetkisi, rol varsayılanı) ve
KARARLAR_2026-10-28 G7.2/G7.3/G8.1.

YALNIZ EKLEME: tek yeni tablo `ana_panel_duzenleri`. Satır ya bir kullanıcının
(`user_id`) ya da bir rolün (`role_id`) düzenidir; her sahibin en fazla bir
satırı olur. Satır yoksa Ana Panel bugünkü düzenle açılır (davranış değişmez).
Yeni izin `panel.yonet` katalogdan (`app/permissions.py`) seed ile iner;
migration izin satırı yazmaz (diğer izinlerle aynı yol).

BEDEL / GERİ ALMA: downgrade tabloyu düşürür; kullanıcıların ve rollerin
kaydettiği panel düzenleri KAYBOLUR, herkes sistem varsayılanına döner (veri
kaybı yalnız tercih verisidir, iş kaydı değildir).

Revision ID: fcd000000001
Revises: fba000000001
Create Date: 2026-11-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "fcd000000001"
down_revision: str | None = "fba000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ana_panel_duzenleri",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("role_id", sa.BigInteger(), sa.ForeignKey("roles.id", ondelete="CASCADE")),
        sa.Column(
            "bilesenler",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (role_id IS NULL)", name="ck_ana_panel_duzen_sahibi"
        ),
        sa.CheckConstraint("jsonb_typeof(bilesenler) = 'array'", name="ck_ana_panel_duzen_liste"),
    )
    op.create_index(
        "uq_ana_panel_duzen_kullanici",
        "ana_panel_duzenleri",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ana_panel_duzen_rol",
        "ana_panel_duzenleri",
        ["role_id"],
        unique=True,
        postgresql_where=sa.text("role_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ana_panel_duzen_rol", table_name="ana_panel_duzenleri")
    op.drop_index("uq_ana_panel_duzen_kullanici", table_name="ana_panel_duzenleri")
    op.drop_table("ana_panel_duzenleri")
