"""servis sla ve uyari (teknik servis Dalga 2, migration 1/7)

NEDEN: SLA hedefi işe AÇILIŞTA damgalanır ve dondurulur (politika sonradan
değişse de açık işin hedefi değişmez); ilk hedef (`cozum_hedef_ilk_at`) bir
daha değişmez, güncel hedef yalnız SLA durduran bekleme bitince ve öncelik/
birim düzeltmesinde ileri alınır. SLA yalnız GUNLUK_SERVIS'te ölçülür
(`ck_so_pb_sla`: PB ve atölye işine politika ve hedef şemada da yazılamaz;
bu türlere/türlerden geçiş yasak olduğundan kısıt güvenlidir). Sonuç
ilk TAMAMLANDI'da donar, yeniden açılış silmez. Politika kataloğu
`service_sla_policies` (KRITIK 12 / YUKSEK 24 / NORMAL 72 saat, 7/24 tohumu);
`users`'a FK taşımaz ki test temizliği tohumu silmesin. `service_alerts`
yalnız "görüldü" ve e-posta tekilliği için dar olay günlüğüdür (rozet anlık
hesaplanır; birim/müşteri denormalize edilmez, plan §6.3).

BEDEL: `service_orders` (Dalga 0 yeni tablosu) 16 nullable/default'lu kolon
ve 7 CHECK alır; canlı mobilite tablolarına dokunulmaz. Downgrade SLA
damgalarını, bildirimleri ve politika değişikliklerini siler.

Revision ID: d2a000000001
Revises: d0a000000007
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a000000001"
down_revision: str | None = "d0a000000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_sla_policies",
        sa.Column("oncelik", sa.String(length=10), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=True),
        sa.Column("cozum_saat", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("mudahale_saat", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column(
            "takvim_turu", sa.String(length=10), server_default=sa.text("'7_24'"), nullable=False
        ),
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
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "birim IS NULL OR birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_slap_birim",
        ),
        sa.CheckConstraint("oncelik IN ('KRITIK', 'NORMAL', 'YUKSEK')", name="ck_slap_oncelik"),
        sa.CheckConstraint("takvim_turu IN ('7_24', 'MESAI')", name="ck_slap_takvim"),
        sa.CheckConstraint("cozum_saat > 0", name="ck_slap_cozum_pozitif"),
        sa.CheckConstraint(
            "mudahale_saat IS NULL OR mudahale_saat > 0", name="ck_slap_mudahale_pozitif"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_slap_aktif",
        "service_sla_policies",
        ["oncelik", sa.literal_column("COALESCE(birim, '*')")],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "service_alerts",
        sa.Column("kod", sa.String(length=30), nullable=False),
        sa.Column("service_order_id", sa.BigInteger(), nullable=False),
        sa.Column("onem", sa.String(length=10), nullable=False),
        sa.Column("baslik", sa.String(length=200), nullable=False),
        sa.Column("acilis_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kapanis_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kapanis_nedeni", sa.String(length=30), nullable=True),
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
        sa.CheckConstraint(
            "kod IN ('BEKLEME_BITIS_GECTI', 'MUDAHALE_ASILDI', 'PB_VADE_GECTI', 'SLA_ASILDI', 'SLA_RISK')",
            name="ck_salert_kod",
        ),
        sa.CheckConstraint("onem IN ('BILGI', 'KRITIK', 'UYARI')", name="ck_salert_onem"),
        sa.CheckConstraint(
            "kapanis_at IS NULL OR kapanis_at >= acilis_at", name="ck_salert_aralik"
        ),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_salert_acilis", "service_alerts", ["acilis_at"], unique=False)
    op.create_index("ix_salert_is", "service_alerts", ["service_order_id"], unique=False)
    op.create_index(
        "uq_salert_acik",
        "service_alerts",
        ["kod", "service_order_id"],
        unique=True,
        postgresql_where=sa.text("kapanis_at IS NULL"),
    )
    op.create_table(
        "service_alert_reads",
        sa.Column("alert_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("goruldu_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["service_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alert_id", "user_id", name="pk_salert_okundu"),
    )

    # --- Tohum: KRITIK 12 / YUKSEK 24 / NORMAL 72 saat, 7/24, tüm birimler ----
    politika = sa.table(
        "service_sla_policies",
        sa.column("oncelik", sa.String),
        sa.column("cozum_saat", sa.Numeric),
        sa.column("takvim_turu", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        politika,
        [
            {"oncelik": "KRITIK", "cozum_saat": 12, "takvim_turu": "7_24", "is_active": True},
            {"oncelik": "YUKSEK", "cozum_saat": 24, "takvim_turu": "7_24", "is_active": True},
            {"oncelik": "NORMAL", "cozum_saat": 72, "takvim_turu": "7_24", "is_active": True},
        ],
    )

    # --- service_orders: SLA kolonları (hepsi nullable / default'lu) ---------
    op.add_column("service_orders", sa.Column("sla_policy_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "service_orders", sa.Column("sla_baslangic_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("service_orders", sa.Column("cozum_hedef_dk", sa.Integer(), nullable=True))
    op.add_column("service_orders", sa.Column("mudahale_hedef_dk", sa.Integer(), nullable=True))
    op.add_column(
        "service_orders", sa.Column("sla_takvim_turu", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "service_orders", sa.Column("cozum_hedef_ilk_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "service_orders", sa.Column("cozum_hedef_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "service_orders", sa.Column("mudahale_hedef_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "service_orders", sa.Column("ilk_mudahale_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("service_orders", sa.Column("sla_sonuc", sa.String(length=12), nullable=True))
    op.add_column("service_orders", sa.Column("sla_durdurulan_dk", sa.Integer(), nullable=True))
    op.add_column("service_orders", sa.Column("sla_kaynak", sa.String(length=14), nullable=True))
    op.add_column(
        "service_orders", sa.Column("gecikme_nedeni", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "service_orders", sa.Column("gecikme_aciklama", sa.String(length=300), nullable=True)
    )
    op.add_column(
        "service_orders",
        sa.Column(
            "tekrar_ariza_aday", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "service_orders", sa.Column("tekrar_ariza_teyit", sa.String(length=20), nullable=True)
    )
    op.create_foreign_key(
        "fk_so_sla_politikasi",
        "service_orders",
        "service_sla_policies",
        ["sla_policy_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_so_pb_sla",
        "service_orders",
        "tur NOT IN ('PB', 'ATOLYE') OR (sla_policy_id IS NULL AND cozum_hedef_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_so_sla_takvim",
        "service_orders",
        "sla_takvim_turu IS NULL OR sla_takvim_turu IN ('7_24', 'MESAI')",
    )
    op.create_check_constraint(
        "ck_so_sla_sonuc",
        "service_orders",
        "sla_sonuc IS NULL OR sla_sonuc IN ('ASILDI', 'OLCULEMEDI', 'ZAMANINDA')",
    )
    op.create_check_constraint(
        "ck_so_sla_kaynak",
        "service_orders",
        "sla_kaynak IS NULL OR sla_kaynak IN ('CANLI', 'GECIS', 'GERIYE_DONUK')",
    )
    op.create_check_constraint(
        "ck_so_gecikme_neden",
        "service_orders",
        "gecikme_nedeni IS NULL OR gecikme_nedeni IN ('DIGER', 'MALZEME_TEDARIK', 'MUSTERI_KAYNAKLI', 'PERSONEL_YETERSIZ', 'TEKNIK_ZORLUK', 'ULASIM', 'YOGUNLUK')",
    )
    op.create_check_constraint(
        "ck_so_gecikme_diger",
        "service_orders",
        "gecikme_nedeni IS DISTINCT FROM 'DIGER' OR gecikme_aciklama IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_so_tekrar_teyit",
        "service_orders",
        "tekrar_ariza_teyit IS NULL OR tekrar_ariza_teyit IN ('AYNI_ARIZA', 'FARKLI_ARIZA', 'KULLANICI_HATASI')",
    )
    op.create_index(
        "ix_so_sla_hedef",
        "service_orders",
        ["cozum_hedef_at"],
        unique=False,
        postgresql_where=sa.text(
            "status NOT IN ('TAMAMLANDI', 'KAPATILDI', 'IPTAL') AND NOT is_deleted"
        ),
    )
    op.create_index(
        "ix_so_tekrar_aday",
        "service_orders",
        ["tekrar_ariza_aday"],
        unique=False,
        postgresql_where=sa.text("tekrar_ariza_aday"),
    )


def downgrade() -> None:
    op.drop_index("ix_so_tekrar_aday", table_name="service_orders")
    op.drop_index("ix_so_sla_hedef", table_name="service_orders")
    op.drop_constraint("ck_so_tekrar_teyit", "service_orders", type_="check")
    op.drop_constraint("ck_so_gecikme_diger", "service_orders", type_="check")
    op.drop_constraint("ck_so_gecikme_neden", "service_orders", type_="check")
    op.drop_constraint("ck_so_sla_kaynak", "service_orders", type_="check")
    op.drop_constraint("ck_so_sla_sonuc", "service_orders", type_="check")
    op.drop_constraint("ck_so_sla_takvim", "service_orders", type_="check")
    op.drop_constraint("ck_so_pb_sla", "service_orders", type_="check")
    op.drop_constraint("fk_so_sla_politikasi", "service_orders", type_="foreignkey")
    op.drop_column("service_orders", "tekrar_ariza_teyit")
    op.drop_column("service_orders", "tekrar_ariza_aday")
    op.drop_column("service_orders", "gecikme_aciklama")
    op.drop_column("service_orders", "gecikme_nedeni")
    op.drop_column("service_orders", "sla_kaynak")
    op.drop_column("service_orders", "sla_durdurulan_dk")
    op.drop_column("service_orders", "sla_sonuc")
    op.drop_column("service_orders", "ilk_mudahale_at")
    op.drop_column("service_orders", "mudahale_hedef_at")
    op.drop_column("service_orders", "cozum_hedef_at")
    op.drop_column("service_orders", "cozum_hedef_ilk_at")
    op.drop_column("service_orders", "sla_takvim_turu")
    op.drop_column("service_orders", "mudahale_hedef_dk")
    op.drop_column("service_orders", "cozum_hedef_dk")
    op.drop_column("service_orders", "sla_baslangic_at")
    op.drop_column("service_orders", "sla_policy_id")
    op.drop_table("service_alert_reads")
    op.drop_index(
        "uq_salert_acik",
        table_name="service_alerts",
        postgresql_where=sa.text("kapanis_at IS NULL"),
    )
    op.drop_index("ix_salert_is", table_name="service_alerts")
    op.drop_index("ix_salert_acilis", table_name="service_alerts")
    op.drop_table("service_alerts")
    op.drop_index(
        "uq_slap_aktif", table_name="service_sla_policies", postgresql_where=sa.text("is_active")
    )
    op.drop_table("service_sla_policies")
