"""tarihsiz cihaz-hat eslesmesi

Kaynak dosyada cihazın ICCID'si var ama SIM'in ne zaman takıldığı yok.
2.446 cihaz bu durumda: eşleşme BİLİNİYOR, başlangıcı bilinmiyor.

Uydurulmuş bir tarih (ör. dosyanın dışa aktarım anı) yazmak garanti
başlangıcını ve hat maliyeti dönemlerini sessizce yanlışlar — bu bir kez
yapıldı ve kullanıcı kararıyla geri alındı. Onun yerine `valid_from` NULL
olabiliyor ve tarihsiz satır bir zaman aralığı İDDİA ETMİYOR.

Şema sonuçları:

* İki EXCLUDE kısıtı KISMİ hale gelir (`WHERE valid_from IS NOT NULL`).
  Aksi halde `tstzrange(NULL, NULL)` "sonsuzdan sonsuza" olur ve aynı
  cihazın gerçek geçmişiyle çakışırdı.
* "Bir cihazda aynı anda tek hat" kuralı EXCLUDE'dan çıktığı için iki
  kısmi TEKİL indeksle ayrıca çivilenir (açık dönem = `valid_to IS NULL`).
  Mevcut veride ihlal yok (kontrol edildi: 0 cihaz, 0 hat).
* Başlangıcı bilinmeyen dönem KAPATILAMAZ: uzunluğu hakkında hiçbir şey
  söylenemeyen bir aralık hak ediş ve maliyet hesabında sessizce yanlış
  sonuç üretir.

Revision ID: 5d1a029e1a46
Revises: 41651ced0b78
Create Date: 2026-09-25 10:08:06.989314

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5d1a029e1a46"
down_revision: str | None = "41651ced0b78"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "sim_device_history",
        "valid_from",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
    )

    # EXCLUDE kısıtlarını KISMİ hale getir: yalnız tarihli satırlar.
    # `type_="exclude"` Alembic'te yok; EXCLUDE kısıtları ham SQL ile düşer.
    op.execute("ALTER TABLE sim_device_history DROP CONSTRAINT ex_sim_cihaz_hat_cakisma")
    op.execute("ALTER TABLE sim_device_history DROP CONSTRAINT ex_sim_cihaz_cihaz_cakisma")
    op.execute(
        "ALTER TABLE sim_device_history ADD CONSTRAINT ex_sim_cihaz_hat_cakisma "
        "EXCLUDE USING gist (sim_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&) "
        "WHERE (valid_from IS NOT NULL)"
    )
    op.execute(
        "ALTER TABLE sim_device_history ADD CONSTRAINT ex_sim_cihaz_cihaz_cakisma "
        "EXCLUDE USING gist (device_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&) "
        "WHERE (valid_from IS NOT NULL)"
    )

    op.create_index(
        "uq_sdh_acik_cihaz",
        "sim_device_history",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "uq_sdh_acik_hat",
        "sim_device_history",
        ["sim_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_check_constraint(
        "ck_sim_cihaz_tarihsiz_acik",
        "sim_device_history",
        "valid_from IS NOT NULL OR valid_to IS NULL",
    )


def downgrade() -> None:
    # Tarihsiz satırlar geri dönüşte yaşayamaz: `valid_from` zorunlu olacak.
    # Silinmeleri VERİ KAYBIDIR ama alternatif, uydurulmuş bir tarihle
    # yazmaktır — sürüm geri alınırken sessizce yanlış veri üretmektense
    # kaybı görünür kılmak yeğdir.
    op.execute("DELETE FROM sim_device_history WHERE valid_from IS NULL")

    op.drop_constraint("ck_sim_cihaz_tarihsiz_acik", "sim_device_history", type_="check")
    op.drop_index(
        "uq_sdh_acik_hat",
        table_name="sim_device_history",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_index(
        "uq_sdh_acik_cihaz",
        table_name="sim_device_history",
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    # `type_="exclude"` Alembic'te yok; EXCLUDE kısıtları ham SQL ile düşer.
    op.execute("ALTER TABLE sim_device_history DROP CONSTRAINT ex_sim_cihaz_hat_cakisma")
    op.execute("ALTER TABLE sim_device_history DROP CONSTRAINT ex_sim_cihaz_cihaz_cakisma")
    op.execute(
        "ALTER TABLE sim_device_history ADD CONSTRAINT ex_sim_cihaz_hat_cakisma "
        "EXCLUDE USING gist (sim_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)"
    )
    op.execute(
        "ALTER TABLE sim_device_history ADD CONSTRAINT ex_sim_cihaz_cihaz_cakisma "
        "EXCLUDE USING gist (device_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)"
    )

    op.alter_column(
        "sim_device_history",
        "valid_from",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
    )
