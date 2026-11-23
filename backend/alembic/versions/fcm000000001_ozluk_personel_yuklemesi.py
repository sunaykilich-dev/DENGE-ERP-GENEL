"""Özlük: personelin kendi yüklediği belge ve İK onayı

2026-11-23 sahip kararı: personel kendi özlük dosyasına belge yükler; belge
"onay bekliyor" durumunda saklanır ve İK onaylayana dek geçerli belge sayılmaz
(işte paylaşılmaz). İK onaylar ya da gerekçeyle reddeder.

`ozluk_belgeleri`ne durum + karar sütunları ve iyimser kilit (`version`)
eklenir. Mevcut satırların hepsi İK yüklemesidir → `ONAYLANDI` (sunucu
varsayılanı). Downgrade sütunları düşürür; onay bekleyen/reddedilen
belgeler önceki şemada ayırt edilemeyeceği için yumuşak silinir (İK
yüklemesi gibi görünüp işte paylaşılmasınlar).

Revision ID: fcm000000001
Revises: fcl000000001
Create Date: 2026-11-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fcm000000001"
down_revision: str | None = "fcl000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Göç anının kopyası (`models/ozluk.OZLUK_DURUMLARI`).
_DURUM_KISITI = "durum IN ('ONAY_BEKLIYOR', 'ONAYLANDI', 'REDDEDILDI')"
_TABLO = "ozluk_belgeleri"


def upgrade() -> None:
    op.add_column(
        _TABLO,
        sa.Column(
            "durum", sa.String(length=20), server_default=sa.text("'ONAYLANDI'"), nullable=False
        ),
    )
    op.add_column(_TABLO, sa.Column("karar_veren_id", sa.BigInteger(), nullable=True))
    op.add_column(_TABLO, sa.Column("karar_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_TABLO, sa.Column("red_gerekcesi", sa.String(length=500), nullable=True))
    op.add_column(
        _TABLO, sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)
    )
    op.create_foreign_key(
        "ozluk_belgeleri_karar_veren_id_fkey",
        _TABLO,
        "users",
        ["karar_veren_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint("ck_ozluk_belge_durum", _TABLO, _DURUM_KISITI)
    op.create_check_constraint(
        "ck_ozluk_belge_red", _TABLO, "durum <> 'REDDEDILDI' OR red_gerekcesi IS NOT NULL"
    )
    op.create_index(
        "ix_ozluk_belge_bekleyen",
        _TABLO,
        ["user_id"],
        postgresql_where=sa.text("durum = 'ONAY_BEKLIYOR' AND NOT is_deleted"),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ozluk_belgeleri SET is_deleted = true, deleted_at = now() "
        "WHERE durum <> 'ONAYLANDI' AND NOT is_deleted"
    )
    op.drop_index(
        "ix_ozluk_belge_bekleyen",
        table_name=_TABLO,
        postgresql_where=sa.text("durum = 'ONAY_BEKLIYOR' AND NOT is_deleted"),
    )
    op.drop_constraint("ck_ozluk_belge_red", _TABLO, type_="check")
    op.drop_constraint("ck_ozluk_belge_durum", _TABLO, type_="check")
    op.drop_constraint("ozluk_belgeleri_karar_veren_id_fkey", _TABLO, type_="foreignkey")
    op.drop_column(_TABLO, "version")
    op.drop_column(_TABLO, "red_gerekcesi")
    op.drop_column(_TABLO, "karar_at")
    op.drop_column(_TABLO, "karar_veren_id")
    op.drop_column(_TABLO, "durum")
