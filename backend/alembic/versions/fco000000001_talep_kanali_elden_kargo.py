"""Servis talep kanalı: ELDEN ve KARGO

2026-11-24 sahip kararı: servis kaydı açılırken talep kanalı "Elden teslim"
ya da "Kargo" seçilebilmeli (cihazı müşteri getirir ya da gönderir).
`ck_so_kanal` iki değerle genişler. Downgrade eski kısıta döner; bu iki
değeri taşıyan satır varsa önce DIGER'e çekilir (bilgi kaybı yalnız kanalda).

Revision ID: fco000000001
Revises: fcn000000001
Create Date: 2026-11-24

"""

from collections.abc import Sequence

from alembic import op

revision: str = "fco000000001"
down_revision: str | None = "fcn000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ESKI = ("BAKIM_OTOMATIK", "DIGER", "EPOSTA", "SAHADA_BILDIRILDI", "TELEFON", "WHATSAPP")
_YENI = tuple(sorted((*_ESKI, "ELDEN", "KARGO")))


def _kosul(degerler: tuple[str, ...]) -> str:
    return "talep_kanali IS NULL OR talep_kanali IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_so_kanal", "service_orders", type_="check")
    op.create_check_constraint("ck_so_kanal", "service_orders", _kosul(_YENI))


def downgrade() -> None:
    op.execute(
        "UPDATE service_orders SET talep_kanali = 'DIGER' WHERE talep_kanali IN ('ELDEN', 'KARGO')"
    )
    op.drop_constraint("ck_so_kanal", "service_orders", type_="check")
    op.create_check_constraint("ck_so_kanal", "service_orders", _kosul(_ESKI))
