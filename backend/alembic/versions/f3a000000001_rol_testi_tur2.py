"""rol testi tur 2: bakım ölçümleri, uygunsuzluk önemi, kalite reddi

KARARLAR 2026-11-04 §7 (rol testi düzeltmeleri — tur 2). Tek migration, yalnız
EKLEME (veri değiştirmez):

1. **Bakım formu ölçümleri** (`maintenance_forms.olcum_*`, NUMERIC, NULL =
   ölçülmedi — 0 değil): jeneratör kV/mA, penetrasyon (mm), doz (µSv/h),
   besleme voltajı (V). Negatif değer `ck_mf_olcum_negatif` ile reddedilir.
   Tamamlama anındaki değerler `maintenance_visits.olcumler` (JSONB) ile
   değişmez ziyaret kaydına kopyalanır.
2. **Uygunsuzluk önemi** (`maintenance_form_checks.onem`,
   `maintenance_nonconformities.onem`; DUSUK/NORMAL/YUKSEK/KRITIK, NULL olabilir):
   KRİTİK bulgudan açılan arıza işi KRİTİK öncelik alır.
3. **Kalite reddi** (`service_orders.kalite_red_at/by/gerekcesi`): son reddin
   izi; ret işi düzeltme için açık duruma döndürür (makine kenarı kodda).

İzin değişiklikleri (SERVIS_YONETICI `maliyet.gor`, MUHASEBE_DESTEK'ten
`maliyet.gor` çıkışı, SATIS `servis.gor`, FINANS_YONETICI yalnız ofis) şema
değildir: `app.seeds.dev` senkronu (özelleştirilmemiş roller) uygular.

BEDEL / GERİ ALMA: downgrade sütunları düşürür; girilmiş ölçüm, önem ve ret
izi kaybolur (ret ayrıntısı iş geçmişinde ve denetimde kalır).

Revision ID: f3a000000001
Revises: f2a000000001
Create Date: 2026-11-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f3a000000001"
down_revision: str | None = "f2a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLCUMLER = (
    ("olcum_kv", sa.Numeric(7, 2)),
    ("olcum_ma", sa.Numeric(7, 2)),
    ("olcum_penetrasyon_mm", sa.Numeric(7, 2)),
    ("olcum_doz_usv", sa.Numeric(9, 3)),
    ("olcum_voltaj_v", sa.Numeric(7, 2)),
)
_ONEM = "onem IS NULL OR onem IN ('DUSUK', 'NORMAL', 'YUKSEK', 'KRITIK')"


def upgrade() -> None:
    for ad, tur in _OLCUMLER:
        op.add_column("maintenance_forms", sa.Column(ad, tur, nullable=True))
    op.create_check_constraint(
        "ck_mf_olcum_negatif",
        "maintenance_forms",
        "coalesce(olcum_kv, 0) >= 0 AND coalesce(olcum_ma, 0) >= 0 "
        "AND coalesce(olcum_penetrasyon_mm, 0) >= 0 AND coalesce(olcum_doz_usv, 0) >= 0 "
        "AND coalesce(olcum_voltaj_v, 0) >= 0",
    )
    op.add_column(
        "maintenance_visits",
        sa.Column("olcumler", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("maintenance_form_checks", sa.Column("onem", sa.String(10), nullable=True))
    op.create_check_constraint("ck_mfc_onem", "maintenance_form_checks", _ONEM)
    op.add_column("maintenance_nonconformities", sa.Column("onem", sa.String(10), nullable=True))
    op.create_check_constraint("ck_mnc_onem", "maintenance_nonconformities", _ONEM)

    op.add_column(
        "service_orders", sa.Column("kalite_red_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "service_orders",
        sa.Column(
            "kalite_red_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_so_kalite_red_by"),
            nullable=True,
        ),
    )
    op.add_column(
        "service_orders", sa.Column("kalite_red_gerekcesi", sa.String(500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("service_orders", "kalite_red_gerekcesi")
    op.drop_column("service_orders", "kalite_red_by")
    op.drop_column("service_orders", "kalite_red_at")
    op.drop_constraint("ck_mnc_onem", "maintenance_nonconformities", type_="check")
    op.drop_column("maintenance_nonconformities", "onem")
    op.drop_constraint("ck_mfc_onem", "maintenance_form_checks", type_="check")
    op.drop_column("maintenance_form_checks", "onem")
    op.drop_column("maintenance_visits", "olcumler")
    op.drop_constraint("ck_mf_olcum_negatif", "maintenance_forms", type_="check")
    for ad, _ in reversed(_OLCUMLER):
        op.drop_column("maintenance_forms", ad)
