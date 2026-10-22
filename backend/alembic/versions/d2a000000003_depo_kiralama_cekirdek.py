"""depo ve kiralama cekirdek (teknik servis Dalga 2, migration 3/7)

NEDEN: Kiralık cihaz `devices`'a ve servis kütüğüne YAZILMAZ (KD-31: global
`uq_devices_seri` ve mobilite stok raporu); ayrı envanter tablosu ve
ekleme-yalnız hareket defteri açılır (toplu bakiye hareketten hesaplanır,
`trg_rhareket_degismez`). Seri kiralık cihaz yalnız SERI_NO kimlik tipinde
ve MOBILITE/ARAC_TAKIP dışındadır (E06-D05); bileşik FK
`fk_rasset_urun_kimlik` ürünün kimlik tipini kilitler. Aynı cihaz çakışan
tarihlerde iki aktif tahsiste olamaz (`ex_rtahsis_cihaz_cakisma`, yarı açık
`daterange`). Kiralama ve servis depoları canlı `warehouses` tablosundadır:
`kiralama_deposu`/`servis_deposu` bayrakları ve `birim` (NULL = ortak);
bir depo ikisi birden olamaz (`ck_warehouse_tur_tekil`).

BEDEL: CANLI `warehouses` tablosuna üç kolon (iki bayrak server_default
false + nullable birim) ve yalnız yeni kolonları sınayan iki CHECK eklenir;
mevcut satırlar mobilite deposu olarak kalır, mevcut kısıtlara dokunulmaz.
Downgrade kiralama verisini ve depo bayraklarını siler.

Revision ID: d2a000000003
Revises: d2a000000002
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d2a000000003"
down_revision: str | None = "d2a000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- warehouses (CANLI tablo, plan §1.12): yalnız default'lu/nullable ----
    op.add_column("warehouses", sa.Column("birim", sa.String(length=20), nullable=True))
    op.add_column(
        "warehouses",
        sa.Column("kiralama_deposu", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "warehouses",
        sa.Column("servis_deposu", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        "ck_warehouse_birim",
        "warehouses",
        "birim IS NULL OR birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
    )
    op.create_check_constraint(
        "ck_warehouse_tur_tekil", "warehouses", "NOT (servis_deposu AND kiralama_deposu)"
    )

    # --- Kiralama ve kiralık envanter -----------------------------------------
    op.create_table(
        "rental_catalog_items",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("kategori", sa.String(length=40), nullable=True),
        sa.Column("sira", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_rcat_birim",
        ),
        sa.CheckConstraint("birim NOT IN ('MOBILITE', 'ARAC_TAKIP')", name="ck_rcat_mobilite_disi"),
        sa.CheckConstraint("sira >= 0", name="ck_rcat_sira"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_rcat_urun"),
    )
    op.create_table(
        "rental_assets",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "identity_kind",
            sa.String(length=10),
            server_default=sa.text("'SERI_NO'"),
            nullable=False,
        ),
        sa.Column("serial_no", sa.String(length=200), nullable=False),
        sa.Column("serial_key", sa.String(length=200), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=True),
        sa.Column("durum", sa.String(length=16), server_default=sa.text("'HAZIR'"), nullable=False),
        sa.Column("eksik_notu", sa.String(length=300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_rasset_birim",
        ),
        sa.CheckConstraint(
            "birim NOT IN ('MOBILITE', 'ARAC_TAKIP')", name="ck_rasset_mobilite_disi"
        ),
        sa.CheckConstraint(
            "durum IN ('HAZIR', 'HAZIR_DEGIL', 'KONTROLDE', 'KIRADA', 'KAYIP', 'ATOLYEDE', 'HURDA')",
            name="ck_rasset_durum",
        ),
        sa.CheckConstraint(
            "identity_kind = 'SERI_NO' AND serial_no IS NOT NULL", name="ck_rasset_seri_takipli"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["product_id", "identity_kind"],
            ["products.id", "products.identity_kind"],
            name="fk_rasset_urun_kimlik",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_rasset_kaynak"),
    )
    op.create_index(
        "ix_rasset_depo_durum", "rental_assets", ["warehouse_id", "durum"], unique=False
    )
    op.create_index("ix_rasset_seri", "rental_assets", ["serial_key"], unique=False)
    op.create_index(
        "uq_rasset_urun_seri",
        "rental_assets",
        ["product_id", "serial_key"],
        unique=True,
        postgresql_where=sa.text("NOT is_deleted"),
    )
    op.create_table(
        "rentals",
        sa.Column("rental_no", sa.String(length=24), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("address_id", sa.BigInteger(), nullable=True),
        sa.Column("lokasyon_metni", sa.String(length=300), nullable=True),
        sa.Column("proje_adi", sa.String(length=200), nullable=True),
        sa.Column("baslangic", sa.Date(), nullable=False),
        sa.Column("bitis", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'TALEP'"), nullable=False
        ),
        sa.Column("sorumlu_user_id", sa.BigInteger(), nullable=True),
        sa.Column("quote_id", sa.BigInteger(), nullable=True),
        sa.Column("iptal_gerekcesi", sa.String(length=500), nullable=True),
        sa.Column("kapanis_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_rental_birim",
        ),
        sa.CheckConstraint(
            "birim NOT IN ('MOBILITE', 'ARAC_TAKIP')", name="ck_rental_mobilite_disi"
        ),
        sa.CheckConstraint(
            "status <> 'IPTAL' OR iptal_gerekcesi IS NOT NULL", name="ck_rental_iptal_gerekce"
        ),
        sa.CheckConstraint(
            "status IN ('TALEP', 'PLANLANDI', 'HAZIRLANIYOR', 'SEVK_EDILDI', 'KURULUM_YAPILDI', 'DEVREYE_ALINDI', 'TOPLANDI', 'DEPOYA_ALINDI', 'KAPANDI', 'IPTAL')",
            name="ck_rental_durum",
        ),
        sa.CheckConstraint("bitis > baslangic", name="ck_rental_tarih"),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sorumlu_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rental_no", name="uq_rental_no"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_rental_kaynak"),
    )
    op.create_index("ix_rental_durum_bitis", "rentals", ["status", "bitis"], unique=False)
    op.create_index("ix_rental_musteri", "rentals", ["customer_id"], unique=False)
    op.create_table(
        "rental_items",
        sa.Column("rental_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
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
        sa.CheckConstraint("qty > 0", name="ck_ritem_adet"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rental_id", "product_id", name="uq_ritem_urun"),
    )
    op.create_table(
        "rental_contacts",
        sa.Column("rental_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
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
            "rol IN ('SATIN_ALMA', 'SAHA_OPERASYON', 'TEKNIK_SORUMLU', 'DIGER')",
            name="ck_rcontact_rol",
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rental_id", "contact_id", "rol", name="uq_rcontact"),
    )
    op.create_table(
        "rental_allocations",
        sa.Column("rental_id", sa.BigInteger(), nullable=False),
        sa.Column("rental_item_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("from_warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("sevk_adet", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("iade_adet", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("kayip_adet", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("baslangic", sa.Date(), nullable=False),
        sa.Column("bitis", sa.Date(), nullable=False),
        sa.Column("durum", sa.String(length=10), server_default=sa.text("'AKTIF'"), nullable=False),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_allocation_id", sa.BigInteger(), nullable=True),
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
            (sa.column("asset_id"), "="),
            (sa.literal_column("daterange(baslangic, bitis, '[)')"), "&&"),
            where=sa.text("asset_id IS NOT NULL AND durum = 'AKTIF'"),
            using="gist",
            name="ex_rtahsis_cihaz_cakisma",
        ),
        sa.CheckConstraint("durum IN ('AKTIF', 'KAPANDI', 'COZULDU')", name="ck_rtahsis_durum"),
        sa.CheckConstraint(
            "(asset_id IS NOT NULL AND qty = 1) OR (asset_id IS NULL AND qty > 0)",
            name="ck_rtahsis_seri_adet",
        ),
        sa.CheckConstraint("bitis > baslangic", name="ck_rtahsis_tarih"),
        sa.CheckConstraint(
            "iade_adet >= 0 AND kayip_adet >= 0 AND iade_adet + kayip_adet <= sevk_adet",
            name="ck_rtahsis_iade",
        ),
        sa.CheckConstraint("sevk_adet >= 0 AND sevk_adet <= qty", name="ck_rtahsis_sevk"),
        sa.ForeignKeyConstraint(["asset_id"], ["rental_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rental_item_id"], ["rental_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["replaced_allocation_id"], ["rental_allocations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rtahsis_kiralama", "rental_allocations", ["rental_id"], unique=False)
    op.create_index(
        "ix_rtahsis_urun_depo",
        "rental_allocations",
        ["product_id", "from_warehouse_id", "durum"],
        unique=False,
    )
    op.create_table(
        "rental_checks",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("qty", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("sonuc", sa.String(length=10), nullable=False),
        sa.Column("aciklama", sa.String(length=500), nullable=True),
        sa.Column("rental_id", sa.BigInteger(), nullable=True),
        sa.Column("workshop_record_id", sa.BigInteger(), nullable=True),
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
            "sonuc = 'UYGUN' OR length(trim(coalesce(aciklama, ''))) > 0",
            name="ck_rkontrol_aciklama",
        ),
        sa.CheckConstraint("sonuc IN ('UYGUN', 'EKSIK', 'ARIZALI')", name="ck_rkontrol_sonuc"),
        sa.CheckConstraint("asset_id IS NULL OR qty = 1", name="ck_rkontrol_seri_adet"),
        sa.CheckConstraint("qty > 0", name="ck_rkontrol_adet"),
        sa.ForeignKeyConstraint(["asset_id"], ["rental_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workshop_record_id"], ["workshop_records.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rkontrol_urun_depo", "rental_checks", ["product_id", "warehouse_id"], unique=False
    )
    op.create_table(
        "rental_inventory_movements",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("qty", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("from_warehouse_id", sa.BigInteger(), nullable=True),
        sa.Column("to_warehouse_id", sa.BigInteger(), nullable=True),
        sa.Column("from_durum", sa.String(length=16), nullable=True),
        sa.Column("to_durum", sa.String(length=16), nullable=True),
        sa.Column("rental_id", sa.BigInteger(), nullable=True),
        sa.Column("allocation_id", sa.BigInteger(), nullable=True),
        sa.Column("check_id", sa.BigInteger(), nullable=True),
        sa.Column("reverses_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
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
            "(from_durum IS NULL OR from_durum IN ('HAZIR', 'HAZIR_DEGIL', 'KONTROLDE', 'KIRADA', 'KAYIP', 'ATOLYEDE', 'HURDA')) AND (to_durum IS NULL OR to_durum IN ('HAZIR', 'HAZIR_DEGIL', 'KONTROLDE', 'KIRADA', 'KAYIP', 'ATOLYEDE', 'HURDA'))",
            name="ck_rhareket_durumlar",
        ),
        sa.CheckConstraint(
            "kind IN ('GIRIS', 'TRANSFER', 'TAHSIS', 'TAHSIS_COZ', 'SEVK', 'IADE', 'KAYIP', 'BULUNDU', 'KONTROL', 'ATOLYE', 'DUZENLEME', 'SAYIM', 'DUZELTME', 'DEGISIM', 'HURDA')",
            name="ck_rhareket_tur",
        ),
        sa.CheckConstraint("asset_id IS NULL OR qty = 1", name="ck_rhareket_seri_adet"),
        sa.CheckConstraint("qty > 0", name="ck_rhareket_adet"),
        sa.CheckConstraint("reverses_id <> id", name="ck_rhareket_kendini_ceviremez"),
        sa.ForeignKeyConstraint(["allocation_id"], ["rental_allocations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["rental_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["check_id"], ["rental_checks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reverses_id"], ["rental_inventory_movements.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["to_warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rhareket_cihaz", "rental_inventory_movements", ["asset_id", "at"], unique=False
    )
    op.create_index(
        "ix_rhareket_cikis",
        "rental_inventory_movements",
        ["product_id", "from_warehouse_id", "from_durum"],
        unique=False,
    )
    op.create_index(
        "ix_rhareket_giris",
        "rental_inventory_movements",
        ["product_id", "to_warehouse_id", "to_durum"],
        unique=False,
    )
    op.create_index(
        "ix_rhareket_kiralama", "rental_inventory_movements", ["rental_id"], unique=False
    )
    op.create_index(
        "uq_rhareket_ters",
        "rental_inventory_movements",
        ["reverses_id"],
        unique=True,
        postgresql_where=sa.text("reverses_id IS NOT NULL"),
    )
    op.create_table(
        "rental_events",
        sa.Column("rental_id", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tur", sa.String(length=12), nullable=False),
        sa.Column("onceki_durum", sa.String(length=20), nullable=True),
        sa.Column("yeni_durum", sa.String(length=20), nullable=True),
        sa.Column("alan", sa.String(length=40), nullable=True),
        sa.Column("eski", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("yeni", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("service_order_id", sa.BigInteger(), nullable=True),
        sa.Column("ekip_user_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("gerekce", sa.String(length=500), nullable=True),
        sa.Column("geri_alinan_event_id", sa.BigInteger(), nullable=True),
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
            "tur IN ('OLUSTUR', 'DURUM', 'ASAMA', 'TAHSIS', 'SEVK', 'IADE', 'KONTROL', 'IPTAL', 'DUZELTME', 'TARIH', 'SORUMLU', 'KALEM', 'IRTIBAT', 'NOT')",
            name="ck_revent_tur",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["geri_alinan_event_id"], ["rental_events.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revent_kiralama", "rental_events", ["rental_id", "at"], unique=False)
    op.create_index(
        "uq_revent_geri_alma",
        "rental_events",
        ["geri_alinan_event_id"],
        unique=True,
        postgresql_where=sa.text("geri_alinan_event_id IS NOT NULL"),
    )
    op.execute("CREATE SEQUENCE rental_no_seq OWNED BY rentals.id")

    # --- Hareket defteri ekleme-yalnız: iş kolonları değişmez, satır silinmez --
    op.execute(
        """
        CREATE FUNCTION trg_rhareket_degismez() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'rental_inventory_movements yalnız eklenebilir (DELETE reddedildi)';
            END IF;
            IF (to_jsonb(NEW) - 'created_by' - 'updated_by' - 'updated_at')
               IS DISTINCT FROM (to_jsonb(OLD) - 'created_by' - 'updated_by' - 'updated_at') THEN
                RAISE EXCEPTION 'rental_inventory_movements yalnız eklenebilir (UPDATE reddedildi)';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rhareket_degismez
        BEFORE UPDATE OR DELETE ON rental_inventory_movements
        FOR EACH ROW EXECUTE FUNCTION trg_rhareket_degismez()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_rhareket_degismez ON rental_inventory_movements")
    op.execute("DROP FUNCTION IF EXISTS trg_rhareket_degismez()")
    op.execute("DROP SEQUENCE IF EXISTS rental_no_seq")
    op.drop_index(
        "uq_revent_geri_alma",
        table_name="rental_events",
        postgresql_where=sa.text("geri_alinan_event_id IS NOT NULL"),
    )
    op.drop_index("ix_revent_kiralama", table_name="rental_events")
    op.drop_table("rental_events")
    op.drop_index(
        "uq_rhareket_ters",
        table_name="rental_inventory_movements",
        postgresql_where=sa.text("reverses_id IS NOT NULL"),
    )
    op.drop_index("ix_rhareket_kiralama", table_name="rental_inventory_movements")
    op.drop_index("ix_rhareket_giris", table_name="rental_inventory_movements")
    op.drop_index("ix_rhareket_cikis", table_name="rental_inventory_movements")
    op.drop_index("ix_rhareket_cihaz", table_name="rental_inventory_movements")
    op.drop_table("rental_inventory_movements")
    op.drop_index("ix_rkontrol_urun_depo", table_name="rental_checks")
    op.drop_table("rental_checks")
    op.drop_index("ix_rtahsis_urun_depo", table_name="rental_allocations")
    op.drop_index("ix_rtahsis_kiralama", table_name="rental_allocations")
    op.drop_table("rental_allocations")
    op.drop_table("rental_contacts")
    op.drop_table("rental_items")
    op.drop_index("ix_rental_musteri", table_name="rentals")
    op.drop_index("ix_rental_durum_bitis", table_name="rentals")
    op.drop_table("rentals")
    op.drop_index(
        "uq_rasset_urun_seri",
        table_name="rental_assets",
        postgresql_where=sa.text("NOT is_deleted"),
    )
    op.drop_index("ix_rasset_seri", table_name="rental_assets")
    op.drop_index("ix_rasset_depo_durum", table_name="rental_assets")
    op.drop_table("rental_assets")
    op.drop_table("rental_catalog_items")
    op.drop_constraint("ck_warehouse_tur_tekil", "warehouses", type_="check")
    op.drop_constraint("ck_warehouse_birim", "warehouses", type_="check")
    op.drop_column("warehouses", "servis_deposu")
    op.drop_column("warehouses", "kiralama_deposu")
    op.drop_column("warehouses", "birim")
