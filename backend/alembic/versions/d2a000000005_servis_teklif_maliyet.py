"""servis teklif ve maliyet (teknik servis Dalga 2, migration 5/7)

NEDEN: Teklif TEK tablodur (KD-32): `quotes.birim` NULL = satış teklifi
(canlı akış aynen), dolu = birimli teknik servis teklifi (iç onay, TEKLIF
makinesi, birim kapsamı). Ayrı "servis_durumu" kolonu iki durum alanı
doğurur, panel/rapor/public uç hangisine bakacağını bilemezdi; bu yüzden
`ck_quote_durum`'a ONAYLANDI ve IPTAL EKLENİR (plan §1.12 onaylı istisna).
İç onay sürüm bazındadır (`quote_versions.approved_*`); gönderim günlüğü
`quote_sends`. İş bazlı gelir/diğer maliyet servis işinden YAPISAL olarak
ayrı tabloda (`service_order_financials`, NULL ≠ 0); işçilik tarifesi
tarihli ve çakışmasız (`ex_iscilik_tarife_cakisma`). Aktif TEKLIF
beklemesine teklif bağı `service_holds.quote_id`.

BEDEL: CANLI `quotes` 8, `quote_versions` 4, `quote_lines` 1 nullable kolon
alır; `quote_lines.description` 300 → 500 genişler (onaylı istisna, tablo
yeniden yazılmaz). Downgrade VERİ KAYBEDER: ONAYLANDI → TASLAK, IPTAL → RED
(iptal gerekçesi `lost_reason`'a taşınır), 300 karakteri aşan kalem
açıklamaları kesilir; gönderim günlüğü, tarifeler ve iş finansı silinir.

Revision ID: d2a000000005
Revises: d2a000000004
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d2a000000005"
down_revision: str | None = "d2a000000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- quotes (CANLI tablo): birimli servis teklifi kolonları (nullable) -------
    op.add_column("quotes", sa.Column("birim", sa.String(length=20), nullable=True))
    op.add_column("quotes", sa.Column("service_order_id", sa.BigInteger(), nullable=True))
    op.add_column("quotes", sa.Column("contact_id", sa.BigInteger(), nullable=True))
    op.add_column("quotes", sa.Column("submitted_by", sa.BigInteger(), nullable=True))
    op.add_column("quotes", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("quotes", sa.Column("cancelled_by", sa.BigInteger(), nullable=True))
    op.add_column("quotes", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("quotes", sa.Column("cancel_reason", sa.String(length=300), nullable=True))
    op.create_foreign_key(
        "fk_quotes_servis_isi",
        "quotes",
        "service_orders",
        ["service_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_quotes_irtibat", "quotes", "contacts", ["contact_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_quotes_onaya_gonderen", "quotes", "users", ["submitted_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_quotes_iptal_eden", "quotes", "users", ["cancelled_by"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        "ck_quote_birim",
        "quotes",
        "birim IS NULL OR birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
    )
    op.create_check_constraint(
        "ck_quote_iptal_neden", "quotes", "status <> 'IPTAL' OR cancel_reason IS NOT NULL"
    )
    op.create_index("ix_quote_servis_isi", "quotes", ["service_order_id"], unique=False)
    op.create_index(
        "ix_quote_birim_durum_tarih", "quotes", ["birim", "status", "created_at"], unique=False
    )
    # İSTİSNA (plan §1.12, KD-32): durum kümesine ONAYLANDI ve IPTAL EKLENİR;
    # hiçbir değer çıkarılmaz, satış akışı yeni değerlere ulaşmaz.
    op.drop_constraint("ck_quote_durum", "quotes", type_="check")
    op.create_check_constraint(
        "ck_quote_durum",
        "quotes",
        "status IN ('TASLAK','ONAY_BEKLIYOR','ONAYLANDI','GONDERILDI','GORUNTULENDI','REVIZE_EDILDI','KABUL','RED','SURESI_DOLDU','SIPARISE_DONUSTU','IPTAL')",
    )

    # --- quote_versions / quote_lines (CANLI) -------------------------------------
    op.add_column("quote_versions", sa.Column("approved_by", sa.BigInteger(), nullable=True))
    op.add_column(
        "quote_versions", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("quote_versions", sa.Column("sent_channel", sa.String(length=16), nullable=True))
    op.add_column("quote_versions", sa.Column("sent_note", sa.String(length=300), nullable=True))
    op.create_foreign_key(
        "fk_qv_onaylayan", "quote_versions", "users", ["approved_by"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        "ck_qv_gonderim_kanali",
        "quote_versions",
        "sent_channel IS NULL OR sent_channel IN ('EPOSTA', 'ELDEN', 'KARGO', 'HARICI_EPOSTA', 'DIGER')",
    )
    op.add_column("quote_lines", sa.Column("service_order_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_ql_servis_isi",
        "quote_lines",
        "service_orders",
        ["service_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_ql_servis_isi", "quote_lines", ["service_order_id"], unique=False)
    # İSTİSNA (KD-33): 300 → 500 genişletme (PG'de yalnız metadata; satış
    # şeması 300'de kalır, 500 yalnız birimli teklif kaleminde).
    op.alter_column(
        "quote_lines",
        "description",
        existing_type=sa.String(length=300),
        type_=sa.String(length=500),
        existing_nullable=False,
    )

    # --- Gönderim günlüğü, işçilik tarifesi, iş finansı -------------------------------
    op.create_table(
        "quote_sends",
        sa.Column("quote_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("kanal", sa.String(length=16), nullable=False),
        sa.Column("alicilar", postgresql.ARRAY(sa.String(length=254)), nullable=True),
        sa.Column("cc", sa.String(length=254), nullable=True),
        sa.Column("sonuc", sa.String(length=10), nullable=False),
        sa.Column("hata_ozeti", sa.String(length=300), nullable=True),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("notlar", sa.String(length=300), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
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
        sa.CheckConstraint(
            "kanal IN ('EPOSTA', 'ELDEN', 'KARGO', 'HARICI_EPOSTA', 'DIGER')", name="ck_qsend_kanal"
        ),
        sa.CheckConstraint("sonuc IN ('BASARILI', 'HATA')", name="ck_qsend_sonuc"),
        sa.CheckConstraint(
            "alicilar IS NULL OR cardinality(alicilar) <= 3", name="ck_qsend_alici_sayisi"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["quote_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qsend_kullanici_zaman", "quote_sends", ["created_by", "created_at"], unique=False
    )
    op.create_index("ix_qsend_teklif", "quote_sends", ["quote_id"], unique=False)
    op.create_table(
        "service_labor_rates",
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("hourly_cost", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("gerekce", sa.String(length=300), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
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
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.column("birim"), "="),
            (sa.literal_column("daterange(valid_from, valid_to, '[)')"), "&&"),
            using="gist",
            name="ex_iscilik_tarife_cakisma",
        ),
        sa.CheckConstraint(
            "birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_iscilik_tarife_birim",
        ),
        sa.CheckConstraint("hourly_cost > 0", name="ck_iscilik_tarife_pozitif"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="ck_iscilik_tarife_aralik"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_iscilik_tarife_acik",
        "service_labor_rates",
        ["birim"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_table(
        "service_order_financials",
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("gelir", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("gelir_kaynagi", sa.String(length=16), nullable=True),
        sa.Column("gelir_notu", sa.Text(), nullable=True),
        sa.Column("diger_maliyet", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("diger_maliyet_notu", sa.Text(), nullable=True),
        sa.Column("fatura_iletildi_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fatura_iletildi_by", sa.BigInteger(), nullable=True),
        sa.Column("fatura_notu", sa.String(length=300), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
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
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "gelir_kaynagi IS DISTINCT FROM 'UCRETSIZ_GARANTI' OR gelir = 0",
            name="ck_sof_ucretsiz_sifir",
        ),
        sa.CheckConstraint(
            "gelir_kaynagi IS NULL OR gelir_kaynagi IN ('TEKLIF', 'ELLE', 'SOZLESME', 'UCRETSIZ_GARANTI')",
            name="ck_sof_gelir_kaynagi",
        ),
        sa.CheckConstraint(
            "gelir_kaynagi IS NULL OR gelir_kaynagi NOT IN ('ELLE', 'UCRETSIZ_GARANTI') OR gelir_notu IS NOT NULL",
            name="ck_sof_gelir_notu",
        ),
        sa.CheckConstraint(
            "(gelir IS NULL) = (gelir_kaynagi IS NULL)", name="ck_sof_gelir_kaynak_tutarli"
        ),
        sa.CheckConstraint(
            "diger_maliyet IS NULL OR diger_maliyet >= 0", name="ck_sof_diger_negatif"
        ),
        sa.CheckConstraint(
            "diger_maliyet IS NULL OR diger_maliyet_notu IS NOT NULL", name="ck_sof_diger_notu"
        ),
        sa.CheckConstraint(
            "fatura_iletildi_by IS NULL OR fatura_iletildi_at IS NOT NULL",
            name="ck_sof_fatura_devri",
        ),
        sa.CheckConstraint("gelir IS NULL OR gelir >= 0", name="ck_sof_gelir_negatif"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fatura_iletildi_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_order_id", name="uq_sof_is"),
    )

    # --- service_holds (Dalga 0 tablosu): aktif TEKLIF beklemesine teklif bağı ----
    op.add_column("service_holds", sa.Column("quote_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_hold_teklif", "service_holds", "quotes", ["quote_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_hold_teklif", "service_holds", type_="foreignkey")
    op.drop_column("service_holds", "quote_id")
    op.drop_table("service_order_financials")
    op.drop_index(
        "uq_iscilik_tarife_acik",
        table_name="service_labor_rates",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_table("service_labor_rates")
    op.drop_index("ix_qsend_teklif", table_name="quote_sends")
    op.drop_index("ix_qsend_kullanici_zaman", table_name="quote_sends")
    op.drop_table("quote_sends")
    # 500 → 300: uzun açıklamalar KESİLİR (veri kaybı, docstring'de).
    op.execute(
        "UPDATE quote_lines SET description = left(description, 300) "
        "WHERE length(description) > 300"
    )
    op.alter_column(
        "quote_lines",
        "description",
        existing_type=sa.String(length=500),
        type_=sa.String(length=300),
        existing_nullable=False,
    )
    op.drop_index("ix_ql_servis_isi", table_name="quote_lines")
    op.drop_constraint("fk_ql_servis_isi", "quote_lines", type_="foreignkey")
    op.drop_column("quote_lines", "service_order_id")
    op.drop_constraint("ck_qv_gonderim_kanali", "quote_versions", type_="check")
    op.drop_constraint("fk_qv_onaylayan", "quote_versions", type_="foreignkey")
    op.drop_column("quote_versions", "sent_note")
    op.drop_column("quote_versions", "sent_channel")
    op.drop_column("quote_versions", "approved_at")
    op.drop_column("quote_versions", "approved_by")
    # Durum eşlemesi (veri kaybı, docstring'de): ONAYLANDI → TASLAK, IPTAL → RED.
    op.execute("UPDATE quotes SET status = 'TASLAK' WHERE status = 'ONAYLANDI'")
    op.execute(
        "UPDATE quotes SET status = 'RED', "
        "lost_reason = left(COALESCE(lost_reason, cancel_reason, 'İptal'), 200) "
        "WHERE status = 'IPTAL'"
    )
    op.drop_constraint("ck_quote_durum", "quotes", type_="check")
    op.create_check_constraint(
        "ck_quote_durum",
        "quotes",
        "status IN ('TASLAK','ONAY_BEKLIYOR','GONDERILDI','GORUNTULENDI','REVIZE_EDILDI','KABUL','RED','SURESI_DOLDU','SIPARISE_DONUSTU')",
    )
    op.drop_index("ix_quote_birim_durum_tarih", table_name="quotes")
    op.drop_index("ix_quote_servis_isi", table_name="quotes")
    op.drop_constraint("ck_quote_iptal_neden", "quotes", type_="check")
    op.drop_constraint("ck_quote_birim", "quotes", type_="check")
    op.drop_constraint("fk_quotes_iptal_eden", "quotes", type_="foreignkey")
    op.drop_constraint("fk_quotes_onaya_gonderen", "quotes", type_="foreignkey")
    op.drop_constraint("fk_quotes_irtibat", "quotes", type_="foreignkey")
    op.drop_constraint("fk_quotes_servis_isi", "quotes", type_="foreignkey")
    op.drop_column("quotes", "cancel_reason")
    op.drop_column("quotes", "cancelled_at")
    op.drop_column("quotes", "cancelled_by")
    op.drop_column("quotes", "submitted_at")
    op.drop_column("quotes", "submitted_by")
    op.drop_column("quotes", "contact_id")
    op.drop_column("quotes", "service_order_id")
    op.drop_column("quotes", "birim")
