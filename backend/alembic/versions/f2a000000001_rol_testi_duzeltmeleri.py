"""rol testi düzeltmeleri: pano şirketi, şef sorumlu

KARARLAR 2026-11-04 §6 (rol testi düzeltmeleri). Tek migration:

1. **`boards.sirket_kod`** (FK `sirketler.kod`, NULL olabilir, indeksli): görev
   panosu açıldığı etkin şirkete aittir ve yalnız o şirket seçiliyken görünür
   (rol testi S1). Var olan panolar DENGE MOBİLİTE'ye yazılır: şirket ayrımından
   önceki canlı sistem mobilite şirketidir (f1a000000001'in varsayılan üyelik
   kuralıyla aynı gerekçe). NULL yalnız süzgeçsiz sistem yolunda kalır.
2. **Şef sorumlu olabilir** (rol testi B1): `ck_soa_sorumlu_teknisyen`
   ("sorumlu yalnız TEKNISYEN") kaldırılır, yerine `ck_soa_sorumlu_rol`
   ("sorumlu TEKNISYEN ya da SEF") kurulur. Tek sorumlu kuralı
   (`uq_soa_tek_sorumlu`) değişmez.

İzin değişiklikleri (`servis.kurulum_ac`, `servis.gecis_kaydi`, `atolye.kabul`,
rol izin listeleri) şema değildir: `app.seeds.dev` senkronu
(`sync_permissions` / `sync_roles`, özelleştirilmemiş roller) uygular.

BEDEL / GERİ ALMA: downgrade sütunu düşürür (panolar yeniden bütün şirketlerde
görünür). Aktif ya da geçmiş ŞEF sorumlu satırı varsa eski kısıt kurulamaz —
downgrade bunları sayar ve açık mesajla DURUR (sessizce değiştirmek tayin
geçmişini bozardı).

Revision ID: f2a000000001
Revises: f1a000000001
Create Date: 2026-11-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a000000001"
down_revision: str | None = "f1a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOBILITE = "MOBILITE"


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column(
            "sirket_kod",
            sa.String(length=20),
            sa.ForeignKey("sirketler.kod", ondelete="RESTRICT", name="fk_boards_sirket_kod"),
            nullable=True,
        ),
    )
    op.create_index("ix_boards_sirket_kod", "boards", ["sirket_kod"])
    op.execute(
        sa.text(
            "UPDATE boards SET sirket_kod = :m "
            "WHERE sirket_kod IS NULL AND EXISTS (SELECT 1 FROM sirketler WHERE kod = :m)"
        ).bindparams(m=MOBILITE)
    )

    op.drop_constraint("ck_soa_sorumlu_teknisyen", "service_order_assignments", type_="check")
    op.create_check_constraint(
        "ck_soa_sorumlu_rol",
        "service_order_assignments",
        "NOT is_lead OR rol IN ('TEKNISYEN', 'SEF')",
    )


def downgrade() -> None:
    baglanti = op.get_bind()
    sef_sorumlu = baglanti.execute(
        sa.text("SELECT count(*) FROM service_order_assignments WHERE is_lead AND rol = 'SEF'")
    ).scalar_one()
    if sef_sorumlu:
        raise RuntimeError(
            f"{sef_sorumlu} tayin satırında şef sorumlu; eski kısıt "
            "(sorumlu yalnız TEKNISYEN) kurulamaz. Önce bu satırları düzeltin."
        )
    op.drop_constraint("ck_soa_sorumlu_rol", "service_order_assignments", type_="check")
    op.create_check_constraint(
        "ck_soa_sorumlu_teknisyen",
        "service_order_assignments",
        "NOT is_lead OR rol = 'TEKNISYEN'",
    )
    op.drop_index("ix_boards_sirket_kod", table_name="boards")
    op.drop_column("boards", "sirket_kod")
