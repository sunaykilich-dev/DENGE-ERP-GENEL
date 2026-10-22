"""servis bildirim eposta (teknik servis Dalga 3, migration 2/3)

NEDEN: SLA aşımı için anlık e-posta ve günlük özet (E10-06, TS-200).
Kullanıcı tercihi (`service_notification_prefs`, satır yok = kapalı) ve giden
kutusu (`service_mail_outbox`). Tekillik ŞEMADADIR: aynı bildirim aynı kişiye
bir kez (`uq_smo_anlik`), kişi başına günde tek özet (`uq_smo_ozet`) — 5
dakikalık worker kaç tur koşarsa koşsun ikinci e-posta doğmaz. Deneme sayısı
şema tavanıyla sınırlı (`ck_smo_deneme`, işletme sınırı ayar
`servis_eposta_deneme`). Alıcı listesi saklanmaz (E10 K4).

BEDEL: İki yeni tablo; `service_alerts` ve `users`'a yalnız FK. `alici`
kişisel veridir (e-posta adresi); saklama worker temizliğiyle sınırlanır.
Downgrade kuyruğu ve tercihleri siler (gönderilmiş e-posta geri alınamaz,
yalnız kaydı düşer).

MESAI takvimi (`d3a000000003`, `service_work_calendar`/`service_holidays`)
bu zincirde YOK: TS-200 MESAI kararı verilmedi (KD-23 "koşullu"; plan §4.3
"verilmezse bu rev atlanır"). Sonraki revizyonun `down_revision`'ı bu
dosyadır.

Revision ID: d3a000000002
Revises: d3a000000001
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3a000000002"
down_revision: str | None = "d3a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_notification_prefs",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("anlik_eposta", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("gunluk_ozet", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "service_mail_outbox",
        sa.Column("tur", sa.String(length=12), nullable=False),
        sa.Column("alert_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("ozet_gunu", sa.Date(), nullable=True),
        sa.Column("alici", sa.String(length=160), nullable=False),
        sa.Column("konu", sa.String(length=200), nullable=False),
        sa.Column("govde", sa.Text(), nullable=False),
        sa.Column(
            "durum", sa.String(length=12), server_default=sa.text("'BEKLIYOR'"), nullable=False
        ),
        sa.Column("deneme", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("son_hata", sa.String(length=300), nullable=True),
        sa.Column("gonderildi_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("tur IN ('ANLIK', 'GUNLUK_OZET')", name="ck_smo_tur"),
        sa.CheckConstraint("durum IN ('BASARISIZ', 'BEKLIYOR', 'GONDERILDI')", name="ck_smo_durum"),
        sa.CheckConstraint("deneme >= 0 AND deneme <= 10", name="ck_smo_deneme"),
        sa.CheckConstraint(
            "tur <> 'GUNLUK_OZET' OR ozet_gunu IS NOT NULL", name="ck_smo_ozet_gunu"
        ),
        sa.CheckConstraint(
            "(durum = 'GONDERILDI') = (gonderildi_at IS NOT NULL)", name="ck_smo_gonderildi"
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["service_alerts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_smo_anlik",
        "service_mail_outbox",
        ["alert_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("tur = 'ANLIK'"),
    )
    op.create_index(
        "uq_smo_ozet",
        "service_mail_outbox",
        ["user_id", "ozet_gunu"],
        unique=True,
        postgresql_where=sa.text("tur = 'GUNLUK_OZET'"),
    )
    op.create_index(
        "ix_smo_bekleyen",
        "service_mail_outbox",
        ["created_at"],
        postgresql_where=sa.text("durum = 'BEKLIYOR'"),
    )


def downgrade() -> None:
    op.drop_index("ix_smo_bekleyen", table_name="service_mail_outbox")
    op.drop_index("uq_smo_ozet", table_name="service_mail_outbox")
    op.drop_index("uq_smo_anlik", table_name="service_mail_outbox")
    op.drop_table("service_mail_outbox")
    op.drop_table("service_notification_prefs")
