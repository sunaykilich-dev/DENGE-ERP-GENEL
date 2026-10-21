"""tarihsiz cihaz-arac eslesmesi

FORA dosyasında cihazın plakası var ama ARACA NE ZAMAN takıldığı yok.
2.783 cihaz bu durumda: eşleşme BİLİNİYOR, başlangıcı bilinmiyor. `fora.py`
göçü bu yüzden cihaz–araç bağını hiç kurmamıştı ("dosyada plaka var ama tarih
yok; cihaz–araç dönemi tarihsiz açılamaz").

Uydurulmuş bir tarih (ör. dosyanın dışa aktarım anı) yazmak garanti
başlangıcını ve cihaz zaman çizelgesini sessizce yanlışlar — bu bir kez
yapıldı ve kullanıcı kararıyla geri alındı. Cihaz–hat tarafında aynı karar
`5d1a029e1a46` ile verildi; bu göç onun cihaz–araç karşılığıdır.

Şema sonuçları:

* `ex_dva_cihaz_cakisma` KISMİ hale gelir (`WHERE valid_from IS NOT NULL`).
  Aksi halde `tstzrange(NULL, NULL)` "sonsuzdan sonsuza" olur ve tarihsiz tek
  bir satır o cihazın bütün gerçek geçmişiyle çakışırdı.
* "Bir cihaz aynı anda tek araçta" kuralı EXCLUDE'dan çıktığı için zaten var
  olan `uq_dva_acik_donem` kısmi tekil indeksiyle korunur (açık dönem =
  `valid_to IS NULL`). Mevcut veride ihlal yok (kontrol edildi: 0 cihaz).
* Başlangıcı bilinmeyen dönem KAPATILAMAZ — `ck_dva_tarihsiz_acik`.

**Bedeli açıkça yazılsın:** `valid_from` artık zorunlu değil, yani "cihaz ne
zamandan beri bu araçta" sorusu bazı satırlarda cevapsız. Karşılığında 2.783
cihazın hangi araçta olduğu ilk kez görünür oluyor; bugüne kadar bu bilgi
hiçbir ekranda yoktu. Gerçek tarihler geldiğinde satırlar doldurulur.

Revision ID: 8c41d2b7e903
Revises: 6f5fc466ff52
Create Date: 2026-09-28 15:10:00.000000

"""

from collections.abc import Sequence

from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8c41d2b7e903"
down_revision: str | None = "6f5fc466ff52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "device_vehicle_assignments",
        "valid_from",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
    )

    # `type_="exclude"` Alembic'te yok; EXCLUDE kısıtları ham SQL ile düşer.
    op.execute("ALTER TABLE device_vehicle_assignments DROP CONSTRAINT ex_dva_cihaz_cakisma")
    op.execute(
        "ALTER TABLE device_vehicle_assignments ADD CONSTRAINT ex_dva_cihaz_cakisma "
        "EXCLUDE USING gist (device_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&) "
        "WHERE (valid_from IS NOT NULL)"
    )
    op.create_check_constraint(
        "ck_dva_tarihsiz_acik",
        "device_vehicle_assignments",
        "valid_from IS NOT NULL OR valid_to IS NULL",
    )


def downgrade() -> None:
    # Tarihsiz satırlar geri dönüşte yaşayamaz. Silinmeleri VERİ KAYBIDIR ama
    # alternatif, uydurulmuş bir tarihle yazmaktır — kaybı görünür kılmak,
    # sessizce yanlış veri üretmekten yeğdir.
    op.execute("DELETE FROM device_vehicle_assignments WHERE valid_from IS NULL")

    op.drop_constraint("ck_dva_tarihsiz_acik", "device_vehicle_assignments", type_="check")
    op.execute("ALTER TABLE device_vehicle_assignments DROP CONSTRAINT ex_dva_cihaz_cakisma")
    op.execute(
        "ALTER TABLE device_vehicle_assignments ADD CONSTRAINT ex_dva_cihaz_cakisma "
        "EXCLUDE USING gist (device_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)"
    )
    op.alter_column(
        "device_vehicle_assignments",
        "valid_from",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
    )
