"""bakım üretim turu: TOPLU_AC tetiği

Kullanıcı isteği (2026-11-05): yıllık bakımlar bekleyen iş emri olarak
görünür; yönetici seçip "iş emirlerini aç" deyince topluca açılır. Toplu açma
turu `maintenance_generation_runs.tetik = 'TOPLU_AC'` ile kaydedilir.

Yalnız CHECK kısıtı genişler (`ck_mgr_tetik`). Servis:
`app.services.teknik_servis.bakim_is_emri`.

BEDEL / GERİ ALMA: downgrade, TOPLU_AC turlarını `ELLE` olarak yeniden
etiketleyip eski kısıtı kurar (tur kaydı silinmez, tetik ayrımı kaybolur).

Revision ID: f5a000000001
Revises: f4a000000001
Create Date: 2026-11-05

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f5a000000001"
down_revision: str | None = "f4a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_mgr_tetik", "maintenance_generation_runs", type_="check")
    op.create_check_constraint(
        "ck_mgr_tetik",
        "maintenance_generation_runs",
        "tetik IN ('ELLE', 'WORKER', 'EKSIK_TAMAMLA', 'TOPLU_AC')",
    )


def downgrade() -> None:
    op.execute("UPDATE maintenance_generation_runs SET tetik = 'ELLE' WHERE tetik = 'TOPLU_AC'")
    op.drop_constraint("ck_mgr_tetik", "maintenance_generation_runs", type_="check")
    op.create_check_constraint(
        "ck_mgr_tetik",
        "maintenance_generation_runs",
        "tetik IN ('ELLE', 'WORKER', 'EKSIK_TAMAMLA')",
    )
