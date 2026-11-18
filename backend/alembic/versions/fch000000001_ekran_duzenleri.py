"""Ekran düzeni: kullanıcının ekran kutucuklarını kişiselleştirmesi

Kullanıcı isteği (2026-11-18): Zaman Takibi, Planlama, Personel… ekranlarındaki
sayı kutucukları kompaktlaştı ve her kullanıcı kutucukların sırasını, boyutunu
ve görünürlüğünü kendine göre ayarlayabilsin.

YALNIZ EKLEME: tek yeni tablo `ekran_duzenleri` (kullanıcı + ekran kodu başına
bir satır). Satır yoksa ekran varsayılan düzenle açılır (davranış değişmez).
İzin eklenmez: kişi yalnız kendi düzenini okur/yazar; kutucuğun verisi ekranın
kendi ucundan ve iznine göre gelir.

BEDEL / GERİ ALMA: downgrade tabloyu düşürür; kaydedilmiş kişisel ekran
düzenleri KAYBOLUR, herkes varsayılana döner (yalnız tercih verisi).

Revision ID: fch000000001
Revises: fcg000000001
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "fch000000001"
down_revision: str | Sequence[str] | None = "fcg000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ekran_duzenleri",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ekran", sa.String(40), nullable=False),
        sa.Column(
            "kutular",
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
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.UniqueConstraint("user_id", "ekran", name="uq_ekran_duzeni_kullanici_ekran"),
        sa.CheckConstraint("jsonb_typeof(kutular) = 'array'", name="ck_ekran_duzeni_liste"),
    )


def downgrade() -> None:
    op.drop_table("ekran_duzenleri")
