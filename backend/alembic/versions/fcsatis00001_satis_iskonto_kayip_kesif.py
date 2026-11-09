"""satış: iskonto limitleri, kaybedilme nedeni kataloğu, keşif ve satıştan servis işi

KARARLAR 2026-11-09 S1, S2, S3, S4.1, S4.2.

1. **İskonto limitleri (S1):** `users.iskonto_limiti_yuzde` (kişi limiti, NULL =
   rol limiti). Tek genel eşik (`settings.iskonto_onay_esigi_yuzde`) rol
   tablosuna (`iskonto_rol_limitleri`) emilir: eski eşik tabloda olmayan
   rollerin limiti ("DIGER") olur — o rollerin bugünkü davranışı değişmez;
   satış rolleri karar değerlerini alır (SATIS 10, SATIS_DESTEK 5,
   SATIS_MUDURU 25). Eski satır silinir.
2. **Kaybedilme nedeni (S2.1):** `quotes.lost_reason_kod` + katalog CHECK'i.
   Eski serbest metin kayıtları "DIGER" + açıklama (`lost_reason` aynen) olur.
   Boş metin (yalnız boşluk) NULL'a çekilir. DIGER'de açıklama zorunlu (CHECK).
3. **Satış ↔ servis işi bağı (S3/S4):** `satis_is_baglari` — teklife ve/veya
   siparişe birden çok iş (keşif, kurulum, teslimat). `quotes.service_order_id`
   aynen kalır (anlamı farklı; bağlı işler listesi ikisini birleştirir).
4. **TESLIMAT servis işi türü (S4.1):** `ck_so_tur` ve `ck_scr_tur` yeniden kurulur.

GERİ ALMA: TESLIMAT türlü iş varsa tür kısıtı eski haline dönemez — downgrade
sayar ve durur. Kayıp kodları silinir (açıklama metni kalır); eşik ayarı DIGER
değeriyle geri yazılır.

Revision ID: fcsatis00001
Revises: fba000000001
Create Date: 2026-11-09

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fcsatis00001"
down_revision: str | None = "fba000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESKI_TURLER = (
    "ARIZA",
    "PLANSIZ_BAKIM",
    "DESTEK",
    "PB",
    "ATOLYE",
    "KURULUM",
    "TOPLAMA",
    "KESIF",
    "DEMONTAJ",
    "TASIMA",
)
YENI_TURLER = (*ESKI_TURLER, "TESLIMAT")

KAYIP_KODLARI = (
    "FIYAT_YUKSEK",
    "RAKIP",
    "BUTCE_YOK",
    "TEKNIK_UYGUNSUZ",
    "TESLIM_SURESI",
    "YANIT_YOK",
    "DIGER",
)
BAG_TURLERI = ("KESIF", "KURULUM", "TESLIMAT")
ROL_LIMITLERI = {"SATIS": 10, "SATIS_DESTEK": 5, "SATIS_MUDURU": 25}
ESKI_ANAHTAR = "iskonto_onay_esigi_yuzde"
YENI_ANAHTAR = "iskonto_rol_limitleri"
VARSAYILAN_ESIK = 10


def _in(sutun: str, degerler: Sequence[str], *, bos: bool = False) -> str:
    ifade = f"{sutun} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"
    return f"{sutun} IS NULL OR {ifade}" if bos else ifade


def _tur_kisitlari(turler: Sequence[str]) -> None:
    op.drop_constraint("ck_so_tur", "service_orders", type_="check")
    op.create_check_constraint("ck_so_tur", "service_orders", _in("tur", sorted(turler)))
    op.drop_constraint("ck_scr_tur", "service_competency_requirements", type_="check")
    op.create_check_constraint("ck_scr_tur", "service_competency_requirements", _in("tur", turler))


def _ayar_gocu() -> None:
    baglanti = op.get_bind()
    eski = baglanti.execute(
        sa.text("SELECT value FROM settings WHERE key = :k"), {"k": ESKI_ANAHTAR}
    ).scalar()
    var_mi = baglanti.execute(
        sa.text("SELECT 1 FROM settings WHERE key = :k"), {"k": YENI_ANAHTAR}
    ).scalar()
    if eski is not None and not var_mi:
        try:
            esik = float(eski)
        except (TypeError, ValueError):
            esik = float(VARSAYILAN_ESIK)
        tablo = {**ROL_LIMITLERI, "DIGER": round(min(max(esik, 0.0), 100.0), 2)}
        baglanti.execute(
            sa.text(
                "INSERT INTO settings (key, value, created_at, updated_at) "
                "VALUES (:k, CAST(:v AS jsonb), now(), now())"
            ),
            {"k": YENI_ANAHTAR, "v": json.dumps(tablo)},
        )
    baglanti.execute(sa.text("DELETE FROM settings WHERE key = :k"), {"k": ESKI_ANAHTAR})


def upgrade() -> None:
    # 1. Kişi iskonto limiti
    op.add_column("users", sa.Column("iskonto_limiti_yuzde", sa.Numeric(5, 2), nullable=True))
    op.create_check_constraint(
        "ck_users_iskonto_limiti",
        "users",
        "iskonto_limiti_yuzde IS NULL OR "
        "(iskonto_limiti_yuzde >= 0 AND iskonto_limiti_yuzde <= 100)",
    )
    _ayar_gocu()

    # 2. Kaybedilme nedeni kataloğu
    op.add_column("quotes", sa.Column("lost_reason_kod", sa.String(20), nullable=True))
    op.execute("UPDATE quotes SET lost_reason = NULL WHERE trim(lost_reason) = ''")
    op.execute("UPDATE quotes SET lost_reason_kod = 'DIGER' WHERE lost_reason IS NOT NULL")
    op.create_check_constraint(
        "ck_quote_kayip_kod", "quotes", _in("lost_reason_kod", KAYIP_KODLARI, bos=True)
    )
    op.create_check_constraint(
        "ck_quote_kayip_diger_aciklama",
        "quotes",
        "lost_reason_kod IS NULL OR lost_reason_kod <> 'DIGER' OR lost_reason IS NOT NULL",
    )

    # 3. Satış ↔ servis işi bağı
    op.create_table(
        "satis_is_baglari",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("quote_id", sa.BigInteger(), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("bag_turu", sa.String(12), nullable=False),
        sa.Column("hedef_tarih", sa.Date(), nullable=True),
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
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["quote_id"], ["quotes.id"], ondelete="CASCADE", name="fk_satis_bag_teklif"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], ondelete="CASCADE", name="fk_satis_bag_siparis"
        ),
        sa.ForeignKeyConstraint(
            ["service_order_id"],
            ["service_orders.id"],
            ondelete="RESTRICT",
            name="fk_satis_bag_servis_isi",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("service_order_id", name="uq_satis_bag_is"),
        sa.CheckConstraint(
            "quote_id IS NOT NULL OR order_id IS NOT NULL", name="ck_satis_bag_kaynak"
        ),
        sa.CheckConstraint(_in("bag_turu", BAG_TURLERI), name="ck_satis_bag_turu"),
    )
    op.create_index("ix_satis_bag_teklif", "satis_is_baglari", ["quote_id"])
    op.create_index("ix_satis_bag_siparis", "satis_is_baglari", ["order_id"])

    # 4. TESLIMAT servis işi türü
    _tur_kisitlari(YENI_TURLER)


def downgrade() -> None:
    baglanti = op.get_bind()
    sorunlar = []
    for tablo in ("service_orders", "service_competency_requirements"):
        n = baglanti.execute(
            sa.text(f"SELECT count(*) FROM {tablo} WHERE tur = 'TESLIMAT'")  # noqa: S608
        ).scalar()
        if n:
            sorunlar.append(f"{tablo}: {n} TESLIMAT satırı")
    if sorunlar:
        raise RuntimeError(
            "TESLIMAT türlü kayıt var; tür kısıtı geri alınamaz: " + "; ".join(sorunlar)
        )
    _tur_kisitlari(ESKI_TURLER)

    op.drop_index("ix_satis_bag_siparis", table_name="satis_is_baglari")
    op.drop_index("ix_satis_bag_teklif", table_name="satis_is_baglari")
    op.drop_table("satis_is_baglari")

    op.drop_constraint("ck_quote_kayip_diger_aciklama", "quotes", type_="check")
    op.drop_constraint("ck_quote_kayip_kod", "quotes", type_="check")
    op.drop_column("quotes", "lost_reason_kod")

    tablo = baglanti.execute(
        sa.text("SELECT value FROM settings WHERE key = :k"), {"k": YENI_ANAHTAR}
    ).scalar()
    if isinstance(tablo, dict) and "DIGER" in tablo:
        baglanti.execute(
            sa.text(
                "INSERT INTO settings (key, value, created_at, updated_at) "
                "VALUES (:k, CAST(:v AS jsonb), now(), now()) ON CONFLICT (key) DO NOTHING"
            ),
            {"k": ESKI_ANAHTAR, "v": json.dumps(tablo["DIGER"])},
        )
    baglanti.execute(sa.text("DELETE FROM settings WHERE key = :k"), {"k": YENI_ANAHTAR})

    op.drop_constraint("ck_users_iskonto_limiti", "users", type_="check")
    op.drop_column("users", "iskonto_limiti_yuzde")
