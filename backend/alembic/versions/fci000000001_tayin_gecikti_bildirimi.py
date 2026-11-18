"""Kalıcı bildirime TAYIN_GECIKTI kodu

2026-11-18 kullanıcı kararı (Operasyon Merkezi panosu): tayinsiz iş,
`servis_tayin_suresi_*` eşiğini mesai dakikasıyla aşınca kalıcı bildirim ve
anlık e-posta üretir. Yalnız `ck_salert_kod` kısıtı genişler; tablo ve veri
değişmez. Downgrade önce bu koddaki satırları siler (eski kısıt onları kabul
etmez); bunlar yeniden üretilebilir olay kayıtlarıdır.

Revision ID: fci000000001
Revises: fch000000001
Create Date: 2026-11-18

"""

from collections.abc import Sequence

from alembic import op

revision: str = "fci000000001"
down_revision: str | Sequence[str] | None = "fch000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ESKI = "'BEKLEME_BITIS_GECTI', 'MUDAHALE_ASILDI', 'PB_VADE_GECTI', 'SLA_ASILDI', 'SLA_RISK'"
_YENI = _ESKI + ", 'TAYIN_GECIKTI'"


def _kisit(kodlar: str) -> None:
    op.drop_constraint("ck_salert_kod", "service_alerts", type_="check")
    op.create_check_constraint("ck_salert_kod", "service_alerts", f"kod IN ({kodlar})")


def upgrade() -> None:
    _kisit(_YENI)


def downgrade() -> None:
    op.execute("DELETE FROM service_alerts WHERE kod = 'TAYIN_GECIKTI'")
    _kisit(_ESKI)
