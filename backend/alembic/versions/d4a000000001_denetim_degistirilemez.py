"""denetim degistirilemez (teknik servis Dalga 4, migration 1/2)

NEDEN: Denetim izi "değiştirilemez şekilde loglanır" (brief §8) ama bugüne
kadar bu yalnız uygulama kodunun UPDATE/DELETE yazmamasına ve
`deploy/db-least-privilege.sql`'deki hak kısıtına dayanıyordu (TS-211,
E13-12). Hak kısıtı kurulumda unutulursa ya da uygulama rolü yanlışlıkla
sahip rolüyle çalışırsa satırlar sessizce silinebilir/değiştirilebilirdi.
`trg_audit_degistirilemez` kuralı veritabanının kendisine taşır:

* **DELETE her zaman reddedilir** (satır tetikleyicisi; hangi rolle
  bağlanılırsa bağlanılsın).
* **UPDATE yalnız iki dar durumda geçer**, başka her değişiklik reddedilir:
  1. KVKK maskelemesi: `is_personal_data` satırında `old_value` /
     `new_value` YALNIZ `{"kvkk": "<metin>"}` biçimli maske nesnesine (ya da
     NULL'a) çevrilebilir. Kimlik, varlık, eylem, IP ve zaman sabit kalır —
     olayın kendisi korunur, yalnız kişisel veri DEĞERİ yok edilir
     (`services/kvkk.py` hesap/personel imhası, ekipman irtibat imhası ve
     Dalga 4 kancaları bu yolu kullanır). Maske dışında bir değere yazmak
     (kaydı "düzeltmek", sahte değer koymak) reddedilir: kural "yalnız
     yok etmeye izin ver, değiştirmeye verme"dir.
  2. `user_id` → NULL: `audit_logs.user_id` yabancı anahtarı `ON DELETE SET
     NULL`; test/doğrulama kullanıcısı silinince (`yonetim.py`) satır KALIR,
     yalnız "kim" alanı boşalır. Bu, FK eyleminin kendisidir.

  Bayrak (`SET LOCAL denge.kvkk_imha`) koşulu BİLİNÇLİ olarak aranmaz: içerik
  kuralı bayraktan güçlüdür (bayrak her kod yolundan kurulabilir; içerik
  kuralı ise yalnız değer yok etmeye izin verir) ve bayrağı kurmayan mevcut
  imha yolları (ör. `teknik_servis/ekipman.py`) Dalga 4'te sahipsiz olduğu
  için kırılmaz. Uygulama bayrağı yine de kurabilir; zararsızdır.

* TRUNCATE kapsam dışıdır (satır tetikleyicisi tetiklenmez): test altyapısı
  tabloyu TRUNCATE ile boşaltır; canlıda uygulama rolünün TRUNCATE hakkı
  `db-least-privilege.sql` ile alınır.

BEDEL: Her UPDATE/DELETE için satır başına bir PL/pgSQL çağrısı — tabloya
yalnız INSERT yazıldığı için pratikte yalnız KVKK imhasında koşar. Yanlışlıkla
denetim satırı silmeye çalışan bakım betiği artık hata alır (bilinçli).
Downgrade yalnız tetikleyiciyi ve fonksiyonu düşürür; veri değişmez.

Revision ID: d4a000000001
Revises: d3a000000004
Create Date: 2026-10-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a000000001"
down_revision: str | None = "d3a000000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# KVKK maske nesnesinin TEK anahtarı. `services/kvkk.DEGER_SILINDI`
# (`{"kvkk": "değer imha edildi"}`) bu anahtarı taşımak ZORUNDA —
# `tests/unit/test_ts_sema_d4.py` iki yerin uyumunu kilitler.
MASKE_ANAHTARI = "kvkk"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION trg_audit_degistirilemez() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Denetim kaydı silinemez (audit_logs değiştirilemez)'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            -- Olayın kimliği sabit: yalnız user_id (FK SET NULL) ve değer
            -- alanları dokunulabilir; geri kalan her kolon aynı kalmalı.
            IF (to_jsonb(NEW) - 'user_id' - 'old_value' - 'new_value')
               IS DISTINCT FROM (to_jsonb(OLD) - 'user_id' - 'old_value' - 'new_value') THEN
                RAISE EXCEPTION 'Denetim kaydı değiştirilemez'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            IF NEW.user_id IS DISTINCT FROM OLD.user_id AND NEW.user_id IS NOT NULL THEN
                RAISE EXCEPTION 'Denetim kaydının kullanıcısı değiştirilemez'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            IF NEW.old_value IS DISTINCT FROM OLD.old_value
               OR NEW.new_value IS DISTINCT FROM OLD.new_value THEN
                IF NOT OLD.is_personal_data THEN
                    RAISE EXCEPTION 'Kişisel veri taşımayan denetim kaydı maskelenemez'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                IF (NEW.old_value IS DISTINCT FROM OLD.old_value
                    AND NEW.old_value IS NOT NULL
                    AND NOT (jsonb_typeof(NEW.old_value) = 'object'
                             AND NEW.old_value ? '{MASKE_ANAHTARI}'
                             AND (NEW.old_value - '{MASKE_ANAHTARI}') = '{{}}'::jsonb))
                   OR (NEW.new_value IS DISTINCT FROM OLD.new_value
                    AND NEW.new_value IS NOT NULL
                    AND NOT (jsonb_typeof(NEW.new_value) = 'object'
                             AND NEW.new_value ? '{MASKE_ANAHTARI}'
                             AND (NEW.new_value - '{MASKE_ANAHTARI}') = '{{}}'::jsonb)) THEN
                    RAISE EXCEPTION 'Denetim kaydı yalnız KVKK maskesiyle güncellenebilir'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_degistirilemez
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION trg_audit_degistirilemez()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_degistirilemez ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS trg_audit_degistirilemez()")
