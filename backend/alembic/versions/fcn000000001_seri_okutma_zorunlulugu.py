"""Servis işi seri okutma: okuma kaynağı ve elle giriş gerekçesi

2026-11-23 sahip kararı: cihazlı servis işinde (arıza, bakım, kurulum, atölye,
cihazlı planlı bakım) seri numarası açılışta ve kapanışta okutulur (telefon
kamerası ya da el okuyucu). Elle yazılırsa sabit listeden gerekçe zorunlu.

- `service_order_serials`: `okuma_kaynagi` (OKUTMA/ELLE), `elle_gerekce`
  (ETIKET_YOK/CIHAZ_YANINDA_DEGIL/DIGER), `elle_aciklama` (DIGER'de zorunlu).
- `service_results`: kapanışta okutulan seri ve kaynağı (`kapanis_*`).

Var olan satırlar NULL kalır (= eski kayıt, kaynak bilinmiyor): geçmiş
"okutuldu" diye işaretlenip tahrif edilmez. Downgrade sütunları ve kısıtları
düşürür (bilgi kaybı yalnız yeni sütunlardadır).

Revision ID: fcn000000001
Revises: fcm000000001
Create Date: 2026-11-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fcn000000001"
down_revision: str | None = "fcm000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Göç anının kopyası (`models/teknik_servis._okuma_kisitlari`).
_SERI_KISITLARI = {
    "ck_sos_okuma": "okuma_kaynagi IS NULL OR okuma_kaynagi IN ('ELLE', 'OKUTMA')",
    "ck_sos_elle_gerekce": (
        "(okuma_kaynagi IS DISTINCT FROM 'ELLE' AND elle_gerekce IS NULL) OR "
        "(okuma_kaynagi = 'ELLE' AND elle_gerekce IN "
        "('CIHAZ_YANINDA_DEGIL', 'DIGER', 'ETIKET_YOK'))"
    ),
    "ck_sos_elle_aciklama": (
        "elle_gerekce IS DISTINCT FROM 'DIGER' OR coalesce(length(trim(elle_aciklama)), 0) > 0"
    ),
}
_SONUC_KISITLARI = {
    "ck_sr_kapanis_seri": "(kapanis_seri_no IS NULL) = (kapanis_okuma_kaynagi IS NULL)",
    "ck_sr_kapanis_okuma": (
        "kapanis_okuma_kaynagi IS NULL OR kapanis_okuma_kaynagi IN ('ELLE', 'OKUTMA')"
    ),
    "ck_sr_kapanis_elle_gerekce": (
        "(kapanis_okuma_kaynagi IS DISTINCT FROM 'ELLE' AND kapanis_elle_gerekce IS NULL) OR "
        "(kapanis_okuma_kaynagi = 'ELLE' AND kapanis_elle_gerekce IN "
        "('CIHAZ_YANINDA_DEGIL', 'DIGER', 'ETIKET_YOK'))"
    ),
    "ck_sr_kapanis_elle_aciklama": (
        "kapanis_elle_gerekce IS DISTINCT FROM 'DIGER' OR "
        "coalesce(length(trim(kapanis_elle_aciklama)), 0) > 0"
    ),
}


def upgrade() -> None:
    op.add_column(
        "service_order_serials", sa.Column("okuma_kaynagi", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "service_order_serials", sa.Column("elle_gerekce", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "service_order_serials", sa.Column("elle_aciklama", sa.String(length=200), nullable=True)
    )
    for ad, ifade in _SERI_KISITLARI.items():
        op.create_check_constraint(ad, "service_order_serials", ifade)

    op.add_column(
        "service_results", sa.Column("kapanis_seri_no", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "service_results", sa.Column("kapanis_okuma_kaynagi", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "service_results", sa.Column("kapanis_elle_gerekce", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "service_results", sa.Column("kapanis_elle_aciklama", sa.String(length=200), nullable=True)
    )
    for ad, ifade in _SONUC_KISITLARI.items():
        op.create_check_constraint(ad, "service_results", ifade)


def downgrade() -> None:
    for ad in _SONUC_KISITLARI:
        op.drop_constraint(ad, "service_results", type_="check")
    for sutun in (
        "kapanis_elle_aciklama",
        "kapanis_elle_gerekce",
        "kapanis_okuma_kaynagi",
        "kapanis_seri_no",
    ):
        op.drop_column("service_results", sutun)
    for ad in _SERI_KISITLARI:
        op.drop_constraint(ad, "service_order_serials", type_="check")
    for sutun in ("elle_aciklama", "elle_gerekce", "okuma_kaynagi"):
        op.drop_column("service_order_serials", sutun)
