"""faz A servis işi kuralları: bağlı yeni iş, kalite onayı, iş başlat/bitir konumu

NEDEN (KARARLAR_2026-10-28 §7 Faz A madde 2, 6, 7):

* **M1.7 — kapanmış iş yeniden açılmaz.** Yeniden açma geçişi kullanıcıya
  kapatıldı; yerine kapanmış işe bağlı YENİ iş açılır. `onceki_is_id`
  (`fk_so_onceki_is`, SET NULL) yeni işten öncekine bağdır. Ayrı kolon
  seçildi: `iliskili_is_id` kullanıcının seçtiği mükerrer/tekrar arıza/devam
  bağıdır ve tek üst bağ taşır; "öncekinin devamı" onu ezmemeli.
  `TEKRAR_ACILDI` durumu katalogda kalır (eski kayıtlar okunur, eski yeniden
  açılmış işler ilerleyebilir).
* **D3.4 + G4.6 — kalite onayı.** Yeni durum AÇILMADI (durum makinesi,
  SLA ve raporlar etkilenmesin): `kalite_onay_at`, `kalite_onaylayan_id`
  (`fk_so_kalite_onaylayan`, SET NULL), `kalite_notu`. Görevler ayrılığı
  (tayinli/süre kaydı olan kişi onaylayamaz) servis katmanındadır — CHECK
  başka tabloya bakamaz. Olay geçmişine `KALITE` türü eklenir (`ck_soe_tur`).
* **G7.8 — iş başlat/bitir konumu.** Canlı zaman bölümünün açıldığı ve
  kapandığı anın konumu (`bas_*`, `bit_*`: enlem, boylam, doğruluk, durum).
  Konum alınamazsa durum `ALINAMADI` yazılır ve ekranda "Konum bilgisi
  alınamadı" görünür; koordinat uydurulmaz (`ck_ste_*_konum`). Sürekli konum
  takibi YOK (G10.3: açık rıza gelene kadar).

BEDEL: Hepsi nullable kolon; mevcut satırlar CHECK'leri sağlar (yeni
kolonlar NULL). `ck_soe_tur` genişletilir (yalnız değer ekleme). Downgrade
`KALITE` olaylarını SİLEMEZ (olay tablosu salt eklemedir, tetikleyici
reddeder): böyle olay varsa downgrade bilerek hata verir — veri kaybı yerine
dur.

Revision ID: e1a000000001
Revises: d4a000000002
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1a000000001"
down_revision: str | None = "d4a000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ESKI_OLAYLAR = (
    "ATAMA",
    "ATOLYE",
    "BEKLEME",
    "BEKLEME_BITTI",
    "DURUM",
    "DUZELTME",
    "EK",
    "EK_SIL",
    "ILISKI",
    "NOT",
    "OLUSTUR",
    "ONAY",
    "PARCA",
    "PLAN",
    "SERI",
    "SLA",
    "SONUC",
    "TEKLIF",
)
_YENI_OLAYLAR = tuple(sorted((*_ESKI_OLAYLAR, "KALITE")))


def _olay_check(degerler: tuple[str, ...]) -> str:
    return "olay_turu IN (" + ", ".join(f"'{d}'" for d in sorted(degerler)) + ")"


def _konum_kosulu(on: str) -> str:
    """`models/teknik_servis._konum_kosulu` ile AYNI metin (birim testi kilitler)."""
    return (
        f"({on}_konum_durumu IS NULL OR {on}_konum_durumu IN ('ALINDI', 'ALINAMADI')) AND ("
        f"({on}_konum_durumu = 'ALINDI' AND {on}_enlem BETWEEN -90 AND 90 "
        f"AND {on}_boylam BETWEEN -180 AND 180 "
        f"AND ({on}_dogruluk_m IS NULL OR {on}_dogruluk_m >= 0)) OR "
        f"({on}_konum_durumu IS DISTINCT FROM 'ALINDI' AND {on}_enlem IS NULL "
        f"AND {on}_boylam IS NULL AND {on}_dogruluk_m IS NULL))"
    )


def upgrade() -> None:
    # --- M1.7: bağlı yeni iş ------------------------------------------------
    op.add_column("service_orders", sa.Column("onceki_is_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_so_onceki_is",
        "service_orders",
        "service_orders",
        ["onceki_is_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint("ck_so_onceki_kendisi", "service_orders", "onceki_is_id <> id")
    op.create_index("ix_so_onceki_is", "service_orders", ["onceki_is_id"])

    # --- D3.4 / G4.6: kalite onayı -------------------------------------------
    op.add_column(
        "service_orders",
        sa.Column("kalite_onay_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "service_orders", sa.Column("kalite_onaylayan_id", sa.BigInteger(), nullable=True)
    )
    op.add_column("service_orders", sa.Column("kalite_notu", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        "fk_so_kalite_onaylayan",
        "service_orders",
        "users",
        ["kalite_onaylayan_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_so_kalite_onay",
        "service_orders",
        "kalite_onaylayan_id IS NULL OR kalite_onay_at IS NOT NULL",
    )
    op.drop_constraint("ck_soe_tur", "service_order_events", type_="check")
    op.create_check_constraint("ck_soe_tur", "service_order_events", _olay_check(_YENI_OLAYLAR))

    # --- G7.8: iş başlat/bitir konumu ----------------------------------------
    for on in ("bas", "bit"):
        op.add_column(
            "service_time_entries",
            sa.Column(f"{on}_enlem", sa.Numeric(9, 6), nullable=True),
        )
        op.add_column(
            "service_time_entries",
            sa.Column(f"{on}_boylam", sa.Numeric(9, 6), nullable=True),
        )
        op.add_column(
            "service_time_entries",
            sa.Column(f"{on}_dogruluk_m", sa.Integer(), nullable=True),
        )
        op.add_column(
            "service_time_entries",
            sa.Column(f"{on}_konum_durumu", sa.String(length=10), nullable=True),
        )
        op.create_check_constraint(
            f"ck_ste_{on}_konum", "service_time_entries", _konum_kosulu(on)
        )


def downgrade() -> None:
    for on in ("bit", "bas"):
        op.drop_constraint(f"ck_ste_{on}_konum", "service_time_entries", type_="check")
        for kolon in ("konum_durumu", "dogruluk_m", "boylam", "enlem"):
            op.drop_column("service_time_entries", f"{on}_{kolon}")

    # KALITE olayı varsa yeni CHECK kurulamaz: bilerek hata (olaylar silinemez).
    op.drop_constraint("ck_soe_tur", "service_order_events", type_="check")
    op.create_check_constraint("ck_soe_tur", "service_order_events", _olay_check(_ESKI_OLAYLAR))
    op.drop_constraint("ck_so_kalite_onay", "service_orders", type_="check")
    op.drop_constraint("fk_so_kalite_onaylayan", "service_orders", type_="foreignkey")
    op.drop_column("service_orders", "kalite_notu")
    op.drop_column("service_orders", "kalite_onaylayan_id")
    op.drop_column("service_orders", "kalite_onay_at")

    op.drop_index("ix_so_onceki_is", table_name="service_orders")
    op.drop_constraint("ck_so_onceki_kendisi", "service_orders", type_="check")
    op.drop_constraint("fk_so_onceki_is", "service_orders", type_="foreignkey")
    op.drop_column("service_orders", "onceki_is_id")
