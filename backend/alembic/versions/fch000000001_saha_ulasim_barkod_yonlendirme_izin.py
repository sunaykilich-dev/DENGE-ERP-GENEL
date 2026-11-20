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


def _ortak() -> list[sa.Column]:
    """Timestamp + Actor + Versioned karışımlarının kolonları."""
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
    ]


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
        op.add_column(
            "rental_allocations", sa.Column(f"{yon}_teslim_at", sa.DateTime(timezone=True))
        )
        op.add_column(
            "rental_allocations",
            sa.Column(
                f"{yon}_teslim_by",
                sa.BigInteger,
                sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_ralloc_{yon}_teslim_by"),
            ),
        )
    # §5-6 yönlendirme
    op.create_table(
        "servis_yonlendirmeleri",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("kaynak", sa.String(10), nullable=False),
        sa.Column(
            "service_order_id",
            sa.BigInteger,
            sa.ForeignKey("service_orders.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column(
            "rental_id", sa.BigInteger, sa.ForeignKey("rentals.id", ondelete="CASCADE"), unique=True
        ),
        sa.Column("birim", sa.String(20), nullable=False),
        sa.Column("durum", sa.String(10), nullable=False, server_default=sa.text("'MUDURDE'")),
        sa.Column("sozlesme_detay", sa.Text),
        sa.Column("talep_notu", sa.Text),
        sa.Column("hedef_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("yonlendiren_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("yonlendirme_at", sa.DateTime(timezone=True)),
        sa.Column("mudur_notu", sa.String(500)),
        *_ortak(),
        sa.CheckConstraint("kaynak IN ('SATIS','KIRALAMA')", name="ck_syon_kaynak"),
        sa.CheckConstraint("durum IN ('MUDURDE','BIRIMDE')", name="ck_syon_durum"),
        sa.CheckConstraint(
            "(service_order_id IS NOT NULL)::int + (rental_id IS NOT NULL)::int = 1",
            name="ck_syon_tek_hedef",
        ),
    )
    # §7 izin talebi
    op.create_table(
        "izin_talepleri",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "personel_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tur", sa.String(10), nullable=False),
        sa.Column("baslangic", sa.Date, nullable=False),
        sa.Column("bitis", sa.Date, nullable=False),
        sa.Column("gun_sayisi", sa.Integer, nullable=False),
        sa.Column(
            "vekil_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("izin_ili", sa.String(60), nullable=False),
        sa.Column("iletisim_tel", sa.String(30), nullable=False),
        sa.Column("aciklama", sa.Text),
        sa.Column("durum", sa.String(12), nullable=False, server_default=sa.text("'BEKLIYOR'")),
        sa.Column("sonuc_at", sa.DateTime(timezone=True)),
        *_ortak(),
        sa.CheckConstraint(
            "tur IN ('YILLIK', 'MAZERET', 'UCRETSIZ', 'RAPOR', 'DIGER')", name="ck_izin_tur"
        ),
        sa.CheckConstraint(
            "durum IN ('BEKLIYOR', 'ONAYLANDI', 'REDDEDILDI', 'IPTAL')", name="ck_izin_durum"
        ),
        sa.CheckConstraint("bitis >= baslangic", name="ck_izin_tarih"),
        sa.CheckConstraint("vekil_id <> personel_id", name="ck_izin_vekil_kendisi"),
    )
    op.create_index("ix_izin_personel", "izin_talepleri", ["personel_id", "baslangic"])
    op.create_table(
        "izin_onaylari",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "talep_id",
            sa.BigInteger,
            sa.ForeignKey("izin_talepleri.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sira", sa.Integer, nullable=False),
        sa.Column(
            "onaylayici_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("durum", sa.String(12), nullable=False, server_default=sa.text("'SIRADA'")),
        sa.Column("aktif_at", sa.DateTime(timezone=True)),
        sa.Column("karar_at", sa.DateTime(timezone=True)),
        sa.Column("aciklama", sa.String(500)),
        sa.Column("token", sa.String(64), unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "durum IN ('SIRADA', 'BEKLIYOR', 'ONAYLANDI', 'REDDEDILDI', 'SURE_ASIMI', 'IPTAL')",
            name="ck_izinonay_durum",
        ),
        sa.UniqueConstraint("talep_id", "sira", name="uq_izinonay_sira"),
    )
    op.create_index("ix_izinonay_bekleyen", "izin_onaylari", ["onaylayici_id", "durum"])


def downgrade() -> None:
    op.drop_table("izin_onaylari")
    op.drop_table("izin_talepleri")
    op.drop_table("servis_yonlendirmeleri")
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
