"""İK bordro ve belgeler: gönderim, kişi belgesi, değiştirilemez olay zinciri

Kullanıcı isteği (2026-11-06): İK bordroyu ve imzalanacak form/talimat/
taahhütnameleri personele gönderir, personel onaylar ya da itiraz eder, İK
takip eder (Kolaysoft PEYK benzeri). Kararlar: KARARLAR_2026-10-28 §11.

YALNIZ EKLEME: dört yeni tablo. `ik_belge_olaylari` için UPDATE/DELETE'i
reddeden tetikleyici: imza kanıtı uygulama hatasıyla da değiştirilemesin.
(TRUNCATE tetikleyiciye takılmaz; test temizliği ve geri alma çalışır.)

BEDEL / GERİ ALMA: downgrade dört tabloyu düşürür; gönderilmiş bordrolar ve
imza kanıtları KAYBOLUR (dosyalar depoda kalır). Canlıda geri almadan önce
`ik_belge_olaylari` dışa aktarılmalıdır.

Revision ID: f8a000000001
Revises: f7a000000001
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8a000000001"
down_revision: str | None = "f7a000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TURLER = ("BORDRO", "FORM", "TALIMAT", "TAAHHUTNAME", "KVKK", "DIGER")
_SABLON_TURLERI = tuple(t for t in _TURLER if t != "BORDRO")
_DURUMLAR = ("GONDERILDI", "GORULDU", "ONAYLANDI", "ITIRAZ", "GERI_ALINDI")
_OLAYLAR = ("GONDERILDI", "GORULDU", "ONAYLANDI", "ITIRAZ", "HATIRLATMA", "GERI_ALINDI")


def _in(sutun: str, degerler: tuple) -> str:
    return f"{sutun} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"


def _zaman():
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _aktor():
    return [
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    ]


def _surum():
    return sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)


def _dosya():
    return [
        sa.Column("dosya_adi", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(400), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
    ]


def _pk():
    return sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "ik_belge_sablonlari",
        _pk(),
        sa.Column("ad", sa.String(150), nullable=False),
        sa.Column("tur", sa.String(15), nullable=False),
        sa.Column("aciklama", sa.Text()),
        sa.Column("aktif", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_dosya(),
        *_zaman(),
        *_aktor(),
        _surum(),
        sa.CheckConstraint(_in("tur", _SABLON_TURLERI), name="ck_ik_sablon_tur"),
    )
    op.create_table(
        "ik_gonderimler",
        _pk(),
        sa.Column("tur", sa.String(15), nullable=False),
        sa.Column("baslik", sa.String(200), nullable=False),
        sa.Column("donem", sa.String(7)),
        sa.Column("aciklama", sa.Text()),
        sa.Column("son_tarih", sa.Date()),
        sa.Column(
            "sablon_id",
            sa.BigInteger(),
            sa.ForeignKey("ik_belge_sablonlari.id", ondelete="SET NULL"),
        ),
        *_zaman(),
        *_aktor(),
        _surum(),
        sa.CheckConstraint(_in("tur", _TURLER), name="ck_ik_gonderim_tur"),
        sa.CheckConstraint(
            "donem IS NULL OR donem ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_ik_gonderim_donem"
        ),
        sa.CheckConstraint(
            "tur <> 'BORDRO' OR donem IS NOT NULL", name="ck_ik_gonderim_bordro_donem"
        ),
    )
    op.create_index("ix_ik_gonderim_tur_donem", "ik_gonderimler", ["tur", "donem"])
    op.create_table(
        "ik_belgeler",
        _pk(),
        sa.Column(
            "gonderim_id",
            sa.BigInteger(),
            sa.ForeignKey("ik_gonderimler.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("durum", sa.String(12), server_default=sa.text("'GONDERILDI'"), nullable=False),
        sa.Column("gonderildi_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("goruldu_at", sa.DateTime(timezone=True)),
        sa.Column("yanit_at", sa.DateTime(timezone=True)),
        sa.Column("itiraz_gerekcesi", sa.Text()),
        sa.Column("hatirlatma_sayisi", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("son_hatirlatma_at", sa.DateTime(timezone=True)),
        *_dosya(),
        *_zaman(),
        _surum(),
        sa.CheckConstraint(_in("durum", _DURUMLAR), name="ck_ik_belge_durum"),
        sa.CheckConstraint(
            "durum <> 'ITIRAZ' OR length(btrim(coalesce(itiraz_gerekcesi, ''))) >= 5",
            name="ck_ik_belge_itiraz_gerekce",
        ),
        sa.UniqueConstraint("gonderim_id", "user_id", name="uq_ik_belge_kisi"),
    )
    op.create_index("ix_ik_belgeler_gonderim_id", "ik_belgeler", ["gonderim_id"])
    op.create_index("ix_ik_belge_kisi_durum", "ik_belgeler", ["user_id", "durum"])
    op.create_table(
        "ik_belge_olaylari",
        _pk(),
        sa.Column(
            "belge_id",
            sa.BigInteger(),
            sa.ForeignKey("ik_belgeler.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("olay", sa.String(12), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("dogrulama", sa.String(10)),
        sa.Column("belge_ozeti", sa.String(64), nullable=False),
        sa.Column("aciklama", sa.Text()),
        sa.Column("onceki_ozet", sa.String(64)),
        sa.Column("kayit_ozeti", sa.String(64), nullable=False, unique=True),
        sa.CheckConstraint(_in("olay", _OLAYLAR), name="ck_ik_olay_tur"),
        sa.CheckConstraint(
            "dogrulama IS NULL OR dogrulama IN ('PAROLA', 'TOTP')", name="ck_ik_olay_dogrulama"
        ),
    )
    op.create_index("ix_ik_olay_belge", "ik_belge_olaylari", ["belge_id", "id"])
    op.execute(
        """
        CREATE FUNCTION ik_belge_olayi_degismez() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ik_belge_olaylari değiştirilemez (yalnız ekleme)'
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ik_belge_olayi_degismez
        BEFORE UPDATE OR DELETE ON ik_belge_olaylari
        FOR EACH ROW EXECUTE FUNCTION ik_belge_olayi_degismez();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ik_belge_olayi_degismez ON ik_belge_olaylari")
    op.execute("DROP FUNCTION IF EXISTS ik_belge_olayi_degismez()")
    op.drop_table("ik_belge_olaylari")
    op.drop_table("ik_belgeler")
    op.drop_table("ik_gonderimler")
    op.drop_table("ik_belge_sablonlari")
