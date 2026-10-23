"""sureli vekalet (teknik servis Dalga 4, migration 2/2)

NEDEN: Şef izne çıktığında müdür, başka bir kullanıcıya 1–30 günlük ek izin
verir; süre bitince ek yetki KENDİLİĞİNDEN düşer, kayıt kalır (E13-15,
M13-04, TS-213). Ayrı bir `user_delegations` tablosu yerine canlı
`user_permissions` istisna satırı süreyle genişletilir (plan §1.12): yetki
kontrolü (`User.has`) zaten bu satırları kullanıcıyla birlikte yüklüyor, ikinci
bir kaynak N+1 ve "iki yerde izin" karmaşası doğururdu.

Yeni kolonlar (hepsi NULL olabilir; mevcut satırlar KALICI istisna olarak
aynen kalır):

* `baslangic_at`, `bitis_at` — vekâlet aralığı `[baslangic_at, bitis_at)`.
* `veren_id` — vekâleti veren (iptal ve erişim gözden geçirme için; veren
  silinirse SET NULL, satır kalır).

`ck_user_permissions_vekalet`: ya ikisi de boş (kalıcı istisna) ya ikisi de
dolu; süreli satır YALNIZ izin VERİR (`allow`, süreli geri alma anlamsız) ve
süre (0, 30 gün] aralığındadır. Vekâlete kapalı izinler (`VEKALETE_KAPALI`)
ve "verenin kendi etkin izinlerinin alt kümesi" kuralı API katmanındadır
(D4-A) — CHECK katalogla bağlanamaz.

Süresi dolan satırlar SİLİNMEZ; `User.has()` geçerlilik anını (`Clock`) bilmeden
süreli satırı hiç saymaz (fail-closed). `ix_user_permissions_bitis` süresi
dolanları bulan günlük denetim işine hizmet eder.

BEDEL: Canlı `user_permissions` üç nullable kolon + bir CHECK + bir kısmi
indeks alır; mevcut satırlar CHECK'i sağlar (üç kolon da NULL). Downgrade
süreli satırları SİLER (eski şemada süre kavramı yok; kalsalardı kalıcı izne
dönüşürlerdi — sessiz yetki yükseltmesi), sonra kolonları düşürür.

Revision ID: d4a000000002
Revises: d4a000000001
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a000000002"
down_revision: str | None = "d4a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Plan TS-213 / M13-04: vekâlet en fazla 30 gün. `models/rbac.VEKALET_AZAMI_GUN`
# ile aynı (birim testi kilitler).
VEKALET_AZAMI_GUN = 30


def upgrade() -> None:
    op.add_column(
        "user_permissions",
        sa.Column("baslangic_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_permissions",
        sa.Column("bitis_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_permissions",
        sa.Column("veren_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_permissions_veren",
        "user_permissions",
        "users",
        ["veren_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_user_permissions_vekalet",
        "user_permissions",
        "(baslangic_at IS NULL AND bitis_at IS NULL) OR ("
        "baslangic_at IS NOT NULL AND bitis_at IS NOT NULL AND allow "
        "AND bitis_at > baslangic_at "
        f"AND bitis_at <= baslangic_at + interval '{VEKALET_AZAMI_GUN} days')",
    )
    op.create_index(
        "ix_user_permissions_bitis",
        "user_permissions",
        ["bitis_at"],
        postgresql_where=sa.text("bitis_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_user_permissions_bitis", table_name="user_permissions")
    op.execute("DELETE FROM user_permissions WHERE bitis_at IS NOT NULL")
    op.drop_constraint("ck_user_permissions_vekalet", "user_permissions", type_="check")
    op.drop_constraint("fk_user_permissions_veren", "user_permissions", type_="foreignkey")
    op.drop_column("user_permissions", "veren_id")
    op.drop_column("user_permissions", "bitis_at")
    op.drop_column("user_permissions", "baslangic_at")
