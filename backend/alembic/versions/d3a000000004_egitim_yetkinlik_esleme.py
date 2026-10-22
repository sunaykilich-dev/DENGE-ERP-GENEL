"""egitim yetkinlik esleme (teknik servis Dalga 3, migration 3/3)

NEDEN: Kurs ↔ yetkinlik bağı (`course_competencies`, E08-16 P3) "yeniden
değerlendir" listesini besler; servis işi türü → asgari yetkinlik eşlemesi
(`service_competency_requirements`, E08-22 P3) atamada YALNIZ UYARI üretir
(K11: atama engellenmez). Eşleme birim + tür + yetkinlik başına tektir
(`uq_scr_birim_tur_yetkinlik`); tür kümesi servis işi CHECK'iyle aynı
tuple'dan (`SERVIS_TURLERI`).

Zincir: `d3a000000003` (MESAI takvimi) TS-200 MESAI kararı verilmediği için
ATLANDI (plan §4.3, KD-23); bu revizyon doğrudan `d3a000000002`'ye bağlıdır.
Karar sonradan verilirse mesai tabloları zincirin SONUNA yeni bir ek
revizyonla gelir (`d3a0000000NN`, NN=10…19) — bu dosya değiştirilmez.

BEDEL: İki yeni tablo; eğitim çekirdeğine yalnız FK. Seviye kendiliğinden
değişmez, `competency_assessments` yalnız-ekleme kalır. Downgrade eşlemeleri
siler.

Revision ID: d3a000000004
Revises: d3a000000002
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3a000000004"
down_revision: str | None = "d3a000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SERVIS_TURLERI = (
    "ARIZA",
    "PLANSIZ_BAKIM",
    "DESTEK",
    "PB",
    "ATOLYE",
    "KURULUM",
    "TOPLAMA",
    "KESIF",
    "DEMONTAJ",
)
_BIRIMLER = ("GUVENLIK", "HABERLESME", "POC", "MOBILITE", "ARAC_TAKIP")


def _in(sutun: str, degerler: tuple[str, ...]) -> str:
    return f"{sutun} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


def upgrade() -> None:
    op.create_table(
        "course_competencies",
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("competency_id", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("course_id", "competency_id", name="pk_course_competencies"),
    )
    op.create_index("ix_ccmp_yetkinlik", "course_competencies", ["competency_id"])

    op.create_table(
        "service_competency_requirements",
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("tur", sa.String(length=20), nullable=False),
        sa.Column("competency_id", sa.BigInteger(), nullable=False),
        sa.Column("min_seviye", sa.SmallInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=True),
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
        sa.CheckConstraint("min_seviye >= 1 AND min_seviye <= 4", name="ck_scr_seviye"),
        sa.CheckConstraint(_in("birim", _BIRIMLER), name="ck_scr_birim"),
        sa.CheckConstraint(_in("tur", tuple(sorted(_SERVIS_TURLERI))), name="ck_scr_tur"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("birim", "tur", "competency_id", name="uq_scr_birim_tur_yetkinlik"),
    )


def downgrade() -> None:
    op.drop_table("service_competency_requirements")
    op.drop_index("ix_ccmp_yetkinlik", table_name="course_competencies")
    op.drop_table("course_competencies")
