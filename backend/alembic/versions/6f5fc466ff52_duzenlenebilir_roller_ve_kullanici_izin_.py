"""duzenlenebilir roller ve kullanici izin istisnalari

Yetki modeli iki düzeyde düzenlenebilir hale gelir (kullanıcı kararı,
25 Eyl 2026):

* `roles.ozellestirildi` — yönetici bir rolün izinlerini elle değiştirdiyse
  açılıştaki katalog senkronu o role ARTIK DOKUNMAZ. Aksi halde düzenleme
  her yeniden başlatmada sessizce geri alınırdı. Bedeli: koda yeni bir izin
  eklendiğinde özelleştirilmiş rollere kendiliğinden inmez; seed bunu log'a
  UYARI olarak yazar.
* `user_permissions` — kullanıcıya özel istisna. `allow=true` rolde olmayan
  izni verir, `allow=false` rolden geleni geri alır. Her istisna gerekçe
  taşır; aynı roldeki iki kişinin neden farklı şey gördüğü yazılı olmalı.

Revision ID: 6f5fc466ff52
Revises: 5d1a029e1a46
Create Date: 2026-09-25 16:58:40.251675

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6f5fc466ff52"
down_revision: str | None = "5d1a029e1a46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_permissions",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_code", sa.String(length=50), nullable=False),
        sa.Column("allow", sa.Boolean(), nullable=False),
        sa.Column("gerekce", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["permission_code"], ["permissions.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "permission_code"),
    )
    op.add_column(
        "roles",
        sa.Column("ozellestirildi", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("roles", "ozellestirildi")
    op.drop_table("user_permissions")
