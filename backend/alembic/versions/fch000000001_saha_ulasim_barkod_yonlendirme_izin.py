"""Saha ulaşımı/km, kiralık etiket ve teslim, yönlendirme, izin talebi

KARARLAR 2026-11-20:
- §1 servis işinde ulaşım türü, servis aracı, başlangıç/son km; araçta son km.
- §3 kiralık cihaza değişmez etiket kodu; tahsiste gidiş/dönüş teslim damgası.
- §5–6 satış/kiralama talebinin teknik servis müdürüne ve birime yönlendirilmesi.
- §7 personel izin talebi ve onay basamakları.

Revision ID: fch000000001
Revises: fcg000000001
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fch000000001"
down_revision: str | Sequence[str] | None = "fcg000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # §1 saha ulaşımı
    op.add_column("service_orders", sa.Column("ulasim_turu", sa.String(16)))
    op.add_column(
        "service_orders",
        sa.Column(
            "servis_arac_id",
            sa.BigInteger,
            sa.ForeignKey("service_vehicles.id", ondelete="SET NULL", name="fk_so_servis_arac"),
        ),
    )
    op.add_column("service_orders", sa.Column("baslangic_km", sa.Integer))
    op.add_column("service_orders", sa.Column("bitis_km", sa.Integer))
    op.create_check_constraint(
        "ck_so_ulasim_turu",
        "service_orders",
        "ulasim_turu IS NULL OR ulasim_turu IN ('SIRKET_ARACI','UCAK','METRO','OTOBUS')",
    )
    op.create_check_constraint(
        "ck_so_km_sirasi",
        "service_orders",
        "bitis_km IS NULL OR baslangic_km IS NULL OR bitis_km >= baslangic_km",
    )
    op.add_column("service_vehicles", sa.Column("son_km", sa.Integer))
    # §3 kiralık cihaz etiketi ve teslim okutma
    op.add_column("rental_assets", sa.Column("etiket_kodu", sa.String(24)))
    op.create_unique_constraint("rental_assets_etiket_kodu_key", "rental_assets", ["etiket_kodu"])
    for yon in ("gidis", "donus"):
        op.add_column("rental_allocations", sa.Column(f"{yon}_teslim_at", sa.DateTime(timezone=True)))
        op.add_column(
            "rental_allocations",
            sa.Column(
                f"{yon}_teslim_by",
                sa.BigInteger,
                sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_ralloc_{yon}_teslim_by"),
            ),
        )
    # @@DEVAM@@


def downgrade() -> None:
    # @@GERI@@
    for yon in ("gidis", "donus"):
        op.drop_column("rental_allocations", f"{yon}_teslim_by")
        op.drop_column("rental_allocations", f"{yon}_teslim_at")
    op.drop_constraint("rental_assets_etiket_kodu_key", "rental_assets", type_="unique")
    op.drop_column("rental_assets", "etiket_kodu")
    op.drop_column("service_vehicles", "son_km")
    op.drop_constraint("ck_so_km_sirasi", "service_orders", type_="check")
    op.drop_constraint("ck_so_ulasim_turu", "service_orders", type_="check")
    op.drop_column("service_orders", "bitis_km")
    op.drop_column("service_orders", "baslangic_km")
    op.drop_column("service_orders", "servis_arac_id")
    op.drop_column("service_orders", "ulasim_turu")
