"""Atölye kabulü geliştirmeleri (2026-11-24 sahip belgesi)

- Aksesuar türleri: Şarj kablosu, Şarj takımı, Askı ipi, Kapak, SIM, Kutu,
  Speaker mikrofon eklenir (`ck_atolye_aksesuar_tur`). Eski kodlar kalır;
  yalnız adları değişti (uygulamada).
- Ekipman tipi: ARAC_TELSIZI ve AKSESUAR (`ck_svceq_tip`).
- `atolye_modelleri`: marka başına model listesi; kütükteki mevcut
  marka+model çiftleriyle tohumlanır.
- `users.varsayilan_is_turu`: yeni servis kaydında hazır gelen iş türü.
- İzin `atolye.model_ekle` uygulama açılışındaki rol senkronuyla iner.

Revision ID: fcq000000001
Revises: fcp000000001
Create Date: 2026-11-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fcq000000001"
down_revision: str | None = "fcp000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AKS_ESKI = (
    "BATARYA",
    "SARJ_UNITESI",
    "SARJ_ADAPTORU",
    "ANTEN",
    "KEMER_KLIPSI",
    "KILIF",
    "KULAKLIK",
    "HARICI_MIKROFON",
    "KABLO",
    "DIGER",
)
_AKS_YENI = (
    "SARJ_ADAPTORU",
    "SARJ_UNITESI",
    "SARJ_KABLOSU",
    "SARJ_TAKIMI",
    "BATARYA",
    "ASKI_IPI",
    "ANTEN",
    "KAPAK",
    "KEMER_KLIPSI",
    "SIM",
    "KUTU",
    "SPEAKER_MIKROFON",
    "KULAKLIK",
    "KILIF",
    "HARICI_MIKROFON",
    "KABLO",
    "DIGER",
)
_TIP_ESKI = (
    "XRAY",
    "KAPI_DEDEKTORU",
    "EL_DEDEKTORU",
    "DIGER_GUVENLIK",
    "TELSIZ",
    "ROLE_TEKRARLAYICI",
    "TELSIZ_DIGER",
    "DIGER",
)
_TIP_YENI = (*_TIP_ESKI, "ARAC_TELSIZI", "AKSESUAR")


def _in(sutun: str, degerler: tuple[str, ...]) -> str:
    return f"{sutun} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_atolye_aksesuar_tur", "workshop_accessories", type_="check")
    op.create_check_constraint(
        "ck_atolye_aksesuar_tur", "workshop_accessories", _in("kind", _AKS_YENI)
    )
    op.drop_constraint("ck_svceq_tip", "service_equipment", type_="check")
    op.create_check_constraint(
        "ck_svceq_tip", "service_equipment", _in("equipment_type", _TIP_YENI)
    )

    op.create_table(
        "atolye_modelleri",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("marka", sa.String(60), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index(
        "uq_atolye_modeli",
        "atolye_modelleri",
        [sa.text("lower(marka)"), sa.text("lower(model)")],
        unique=True,
    )
    # Kütükteki mevcut çiftler (aynı adın büyük/küçük harf varyantlarından biri).
    op.execute(
        """
        INSERT INTO atolye_modelleri (marka, model)
        SELECT DISTINCT ON (lower(btrim(brand)), lower(btrim(model))) btrim(brand), btrim(model)
        FROM service_equipment
        WHERE NOT is_deleted AND brand IS NOT NULL AND model IS NOT NULL
          AND btrim(brand) <> '' AND btrim(model) <> ''
          AND length(btrim(brand)) <= 60 AND length(btrim(model)) <= 80
        ORDER BY lower(btrim(brand)), lower(btrim(model)), btrim(model)
        """
    )

    op.add_column("users", sa.Column("varsayilan_is_turu", sa.String(20)))


def downgrade() -> None:
    op.drop_column("users", "varsayilan_is_turu")
    op.drop_index("uq_atolye_modeli", table_name="atolye_modelleri")
    op.drop_table("atolye_modelleri")
    op.execute(
        "UPDATE service_equipment SET equipment_type = 'TELSIZ_DIGER' "
        "WHERE equipment_type IN ('ARAC_TELSIZI', 'AKSESUAR')"
    )
    op.drop_constraint("ck_svceq_tip", "service_equipment", type_="check")
    op.create_check_constraint(
        "ck_svceq_tip", "service_equipment", _in("equipment_type", _TIP_ESKI)
    )
    # Yeni türler eskilerde yok: "Diğer" + açıklamada eski kod (bilgi kalır).
    eski_tur = _in("kind", _AKS_ESKI)
    op.execute(
        "UPDATE workshop_accessories SET description = COALESCE(description, kind), "  # noqa: S608
        f"kind = 'DIGER' WHERE NOT ({eski_tur})"
    )
    op.drop_constraint("ck_atolye_aksesuar_tur", "workshop_accessories", type_="check")
    op.create_check_constraint(
        "ck_atolye_aksesuar_tur", "workshop_accessories", _in("kind", _AKS_ESKI)
    )
