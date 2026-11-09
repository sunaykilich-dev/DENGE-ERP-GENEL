"""parça talebi amir onayı: teknisyen depodan ister, şef onaylar, depo teslim eder

Kullanıcı isteği (2026-11-09): "teknisyenler yedek parça taleplerini sistem
üzerinden amir onayı ile depodan talep edebilecekleri kurguyu düzenle".

`service_part_requests` genişler (YALNIZ EKLEME + kısıt genişletme):
- `durum` String(12) → String(16); yeni durumlar ONAY_BEKLIYOR, REDDEDILDI
  (`ck_parca_talep_durum` yeniden yazılır).
- `warehouse_id` (talep edilen depo, FK RESTRICT), `onaylayan_id` (FK users,
  SET NULL), `onay_at`, `red_nedeni`; `ck_parca_talep_red` (red gerekçeli).
- `uq_parca_talep_acik`: iş + parça başına tek açık talep artık
  ONAY_BEKLIYOR ve ACIK'ı birlikte sayar.

Mevcut ACIK talepler ACIK kalır (onaysız açılmış eski talepler; depo boş).

İzinler (aynı gün, teknisyen menüsü sadeleşti): `parca.talep_onay` ve
`takip.gor` (ana panel, servis paneli, planlama panosu, takip listeleri).
Kod kataloğu açılışta `seeds.dev.sync_roles` ile senkronlanır; ancak arayüzden
ÖZELLEŞTİRİLMİŞ roller senkrona girmez. Onlar bugünkü erişimini kaybetmesin
diye burada da eklenir: `takip.gor` → `servis.gor` taşıyan her rol
(SERVIS_TEKNISYEN hariç); `parca.talep_onay` → SERVIS_SEF, SERVIS_YONETICI.

BEDEL / GERİ ALMA: downgrade ONAY_BEKLIYOR talepleri IPTAL'e, REDDEDILDI
talepleri IPTAL'e (neden red gerekçesi) çevirir, sütunları düşürür; onay
kaydı (kim/ne zaman) kaybolur.

Revision ID: fbb000000001
Revises: fba000000001
Create Date: 2026-11-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fbb000000001"
down_revision: str | None = "fba000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLO = "service_part_requests"
_YENI = ("ONAY_BEKLIYOR", "ACIK", "KARSILANDI", "REDDEDILDI", "IPTAL")
_ESKI = ("ACIK", "KARSILANDI", "IPTAL")


def _in(degerler: tuple[str, ...]) -> str:
    return "durum IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


_IZINLER = {
    "takip.gor": (
        "Teknik Servis",
        "Ana panel, servis paneli, planlama panosu ve takip listelerini görür",
    ),
    "parca.talep_onay": (
        "Yedek Parça",
        "Kendi biriminin teknisyenlerinin depo parça taleplerini onaylar ya da reddeder",
    ),
}


def _izinleri_ekle() -> None:
    baglanti = op.get_bind()
    for kod, (modul, aciklama) in _IZINLER.items():
        baglanti.execute(
            sa.text(
                "INSERT INTO permissions (code, module, description) VALUES (:k, :m, :a) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"k": kod, "m": modul, "a": aciklama},
        )
    baglanti.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_code) "
            "SELECT DISTINCT rp.role_id, 'takip.gor' FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id "
            "WHERE rp.permission_code = 'servis.gor' AND r.code <> 'SERVIS_TEKNISYEN' "
            "ON CONFLICT DO NOTHING"
        )
    )
    baglanti.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_code) "
            "SELECT id, 'parca.talep_onay' FROM roles "
            "WHERE code IN ('SERVIS_SEF', 'SERVIS_YONETICI') ON CONFLICT DO NOTHING"
        )
    )


def upgrade() -> None:
    _izinleri_ekle()
    op.alter_column(_TABLO, "durum", type_=sa.String(16), existing_type=sa.String(12))
    op.drop_constraint("ck_parca_talep_durum", _TABLO, type_="check")
    op.create_check_constraint("ck_parca_talep_durum", _TABLO, _in(_YENI))
    op.add_column(_TABLO, sa.Column("warehouse_id", sa.BigInteger(), nullable=True))
    op.add_column(_TABLO, sa.Column("onaylayan_id", sa.BigInteger(), nullable=True))
    op.add_column(_TABLO, sa.Column("onay_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_TABLO, sa.Column("red_nedeni", sa.String(200), nullable=True))
    op.create_foreign_key(
        "fk_parca_talep_depo", _TABLO, "warehouses", ["warehouse_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_parca_talep_onaylayan", _TABLO, "users", ["onaylayan_id"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        "ck_parca_talep_red", _TABLO, "durum <> 'REDDEDILDI' OR red_nedeni IS NOT NULL"
    )
    op.drop_index("uq_parca_talep_acik", table_name=_TABLO)
    op.create_index(
        "uq_parca_talep_acik",
        _TABLO,
        ["service_order_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("durum IN ('ONAY_BEKLIYOR', 'ACIK') AND NOT is_deleted"),
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_code IN ('takip.gor', 'parca.talep_onay')"
    )
    op.execute(
        f"UPDATE {_TABLO} SET durum = 'IPTAL', "
        "iptal_nedeni = coalesce(red_nedeni, 'Onay akışı geri alındı') "
        "WHERE durum IN ('ONAY_BEKLIYOR', 'REDDEDILDI')"
    )
    op.drop_index("uq_parca_talep_acik", table_name=_TABLO)
    op.create_index(
        "uq_parca_talep_acik",
        _TABLO,
        ["service_order_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("durum = 'ACIK' AND NOT is_deleted"),
    )
    op.drop_constraint("ck_parca_talep_red", _TABLO, type_="check")
    op.drop_constraint("fk_parca_talep_onaylayan", _TABLO, type_="foreignkey")
    op.drop_constraint("fk_parca_talep_depo", _TABLO, type_="foreignkey")
    for sutun in ("red_nedeni", "onay_at", "onaylayan_id", "warehouse_id"):
        op.drop_column(_TABLO, sutun)
    op.drop_constraint("ck_parca_talep_durum", _TABLO, type_="check")
    op.create_check_constraint("ck_parca_talep_durum", _TABLO, _in(_ESKI))
    op.alter_column(_TABLO, "durum", type_=sa.String(12), existing_type=sa.String(16))
