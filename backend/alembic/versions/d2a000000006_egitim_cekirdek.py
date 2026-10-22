"""egitim cekirdek (teknik servis Dalga 2, migration 6/7)

NEDEN: Eğitim öznesi `users.id`'dir (ayrı personel tablosu yok). Plan kişi +
kurs + yıl başına tektir ama İPTAL'i dışlar (iptal edilen yıl yeniden
planlanabilir). Yetkinlik değerlendirmesi SADECE EKLEME'dir (güncel seviye
`DISTINCT ON` ile, `ix_cas_son`); kritik İSG uygunsuzluğu gözlem başına tek
düzeltici faaliyet açar (`uq_tca_gozlem`). Öz-gözlem ve öz-değerlendirme
şemada da reddedilir. Gözlem servis işine doğrudan bağlanır
(`training_observations.service_order_id`, plan §6.2). Tohum YAZILMAZ:
katalog şirket içeriğidir, göçle gelir.

BEDEL: Yalnız yeni tablolar; canlı tablolara ve `users`'a kolon eklenmez.
Downgrade bütün eğitim kayıtlarını siler.

Revision ID: d2a000000006
Revises: d2a000000005
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a000000006"
down_revision: str | None = "d2a000000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_courses",
        sa.Column("kod", sa.String(length=30), nullable=False),
        sa.Column("baslik", sa.String(length=200), nullable=False),
        sa.Column("kategori", sa.String(length=20), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=True),
        sa.Column("sure_saat", sa.Numeric(precision=4, scale=1), nullable=False),
        sa.Column("zorunlu", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("neden", sa.Text(), nullable=True),
        sa.Column("hedef_davranis", sa.Text(), nullable=True),
        sa.Column("basari_olcutu", sa.Text(), nullable=True),
        sa.Column("gozlem_esik_yuzde", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("sinav_gecme_puani", sa.Integer(), nullable=True),
        sa.Column("yenileme_ay", sa.Integer(), nullable=True),
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
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "birim IS NULL OR birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_tc_birim",
        ),
        sa.CheckConstraint(
            "kategori IN ('TEKNIK', 'ISG', 'KISISEL_GELISIM', 'IS_SURECI')", name="ck_tc_kategori"
        ),
        sa.CheckConstraint(
            "gozlem_esik_yuzde IS NULL OR (gozlem_esik_yuzde >= 0 AND gozlem_esik_yuzde <= 100)",
            name="ck_tc_esik",
        ),
        sa.CheckConstraint(
            "sinav_gecme_puani IS NULL OR (sinav_gecme_puani >= 0 AND sinav_gecme_puani <= 100)",
            name="ck_tc_sinav",
        ),
        sa.CheckConstraint("sure_saat >= 0.5 AND sure_saat <= 24", name="ck_tc_sure"),
        sa.CheckConstraint(
            "yenileme_ay IS NULL OR (yenileme_ay >= 1 AND yenileme_ay <= 120)",
            name="ck_tc_yenileme",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kod", name="uq_tc_kod"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_tc_kaynak"),
    )
    op.create_table(
        "training_criteria",
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("sira", sa.Integer(), nullable=False),
        sa.Column("metin", sa.String(length=300), nullable=False),
        sa.Column("is_critical", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint("sira > 0", name="ck_tcr_sira"),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "sira", name="uq_tcr_kurs_sira"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_tcr_kaynak"),
    )
    op.create_table(
        "training_sessions",
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("oturum_tarihi", sa.Date(), nullable=False),
        sa.Column("egitmen_ad", sa.String(length=120), nullable=True),
        sa.Column("egitmen_user_id", sa.BigInteger(), nullable=True),
        sa.Column("sure_saat", sa.Numeric(precision=4, scale=1), nullable=False),
        sa.Column("yer", sa.String(length=200), nullable=True),
        sa.Column("notlar", sa.Text(), nullable=True),
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
        sa.CheckConstraint("sure_saat >= 0.5 AND sure_saat <= 24", name="ck_ts_sure"),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["egitmen_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_ts_kaynak"),
    )
    op.create_index(
        "ix_ts_kurs_tarih", "training_sessions", ["course_id", "oturum_tarihi"], unique=False
    )
    op.create_table(
        "training_plans",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_yili", sa.Integer(), nullable=False),
        sa.Column("hedef_tarih", sa.Date(), nullable=False),
        sa.Column("gelisim_hedefi", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'PLANLANDI'"), nullable=False
        ),
        sa.Column("durum_gerekcesi", sa.String(length=500), nullable=True),
        sa.Column("onceki_hedef_tarih", sa.Date(), nullable=True),
        sa.Column("completed_on", sa.Date(), nullable=True),
        sa.Column("completed_session_id", sa.BigInteger(), nullable=True),
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
            "(status = 'TAMAMLANDI') = (completed_on IS NOT NULL)", name="ck_tp_tamam"
        ),
        sa.CheckConstraint(
            "status IN ('PLANLANDI', 'ERTELENDI', 'BASARISIZ_TEKRAR', 'TAMAMLANDI', 'IPTAL')",
            name="ck_tp_durum",
        ),
        sa.CheckConstraint(
            "status NOT IN ('ERTELENDI', 'IPTAL') OR durum_gerekcesi IS NOT NULL",
            name="ck_tp_gerekce",
        ),
        sa.CheckConstraint("plan_yili >= 2020 AND plan_yili <= 2100", name="ck_tp_yil"),
        sa.ForeignKeyConstraint(
            ["completed_session_id"], ["training_sessions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_tp_kaynak"),
    )
    op.create_index("ix_tp_kisi", "training_plans", ["user_id"], unique=False)
    op.create_index("ix_tp_yil_durum", "training_plans", ["plan_yili", "status"], unique=False)
    op.create_index(
        "uq_tp_kisi_kurs_yil",
        "training_plans",
        ["user_id", "course_id", "plan_yili"],
        unique=True,
        postgresql_where=sa.text("NOT is_deleted AND status <> 'IPTAL'"),
    )
    op.create_table(
        "training_attendance",
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("katildi", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("on_puan", sa.Integer(), nullable=True),
        sa.Column("son_puan", sa.Integer(), nullable=True),
        sa.Column("notlar", sa.Text(), nullable=True),
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
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "(on_puan IS NULL OR (on_puan >= 0 AND on_puan <= 100)) AND (son_puan IS NULL OR (son_puan >= 0 AND son_puan <= 100))",
            name="ck_ta_puan",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["training_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "user_id", name="uq_ta_oturum_kisi"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_ta_kaynak"),
    )
    op.create_index("ix_ta_kisi", "training_attendance", ["user_id"], unique=False)
    op.create_table(
        "training_observations",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=True),
        sa.Column("asama", sa.SmallInteger(), nullable=False),
        sa.Column("gozlem_tarihi", sa.Date(), nullable=False),
        sa.Column("observer_user_id", sa.BigInteger(), nullable=True),
        sa.Column("gozlemci_ad", sa.String(length=100), nullable=True),
        sa.Column("service_order_id", sa.BigInteger(), nullable=True),
        sa.Column("birim", sa.String(length=20), nullable=True),
        sa.Column("puan", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("sonuc", sa.String(length=20), nullable=False),
        sa.Column("kritik", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notlar", sa.Text(), nullable=True),
        sa.Column("aksiyon_plani", sa.Text(), nullable=True),
        sa.Column("sonraki_izleme", sa.Date(), nullable=True),
        sa.Column("gordu_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("personel_yorumu", sa.String(length=900), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.BigInteger(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=300), nullable=True),
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
            "birim IS NULL OR birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_tob_birim",
        ),
        sa.CheckConstraint(
            "sonuc IN ('KRITIK', 'EKSIK_GOZLEM', 'BASARILI', 'GELISIM_GEREKLI')",
            name="ck_tob_sonuc",
        ),
        sa.CheckConstraint("(cancelled_at IS NULL) = (cancel_reason IS NULL)", name="ck_tob_iptal"),
        sa.CheckConstraint("asama IN (0, 30, 60, 90)", name="ck_tob_asama"),
        sa.CheckConstraint(
            "observer_user_id IS NULL OR observer_user_id <> user_id", name="ck_tob_oz_gozlem"
        ),
        sa.CheckConstraint("puan IS NULL OR (puan >= 0 AND puan <= 100)", name="ck_tob_puan"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["observer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_id"], ["training_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_tob_kaynak"),
    )
    op.create_index(
        "ix_tob_kisi_kurs_asama",
        "training_observations",
        ["user_id", "course_id", "asama"],
        unique=False,
    )
    op.create_index("ix_tob_servis", "training_observations", ["service_order_id"], unique=False)
    op.create_table(
        "training_observation_ratings",
        sa.Column("observation_id", sa.BigInteger(), nullable=False),
        sa.Column("criterion_id", sa.BigInteger(), nullable=False),
        sa.Column("puan", sa.SmallInteger(), nullable=False),
        sa.Column("gozlenmedi_gerekcesi", sa.String(length=300), nullable=True),
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
            "puan <> -1 OR gozlenmedi_gerekcesi IS NOT NULL", name="ck_tor_gozlenmedi"
        ),
        sa.CheckConstraint("puan IN (-1, 0, 1, 2)", name="ck_tor_puan"),
        sa.ForeignKeyConstraint(["criterion_id"], ["training_criteria.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["training_observations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", "criterion_id", name="uq_tor_gozlem_madde"),
    )
    op.create_table(
        "training_corrective_actions",
        sa.Column("observation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("sorumlu_user_id", sa.BigInteger(), nullable=True),
        sa.Column("termin", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default=sa.text("'ACIK'"), nullable=False),
        sa.Column("kapanis_turu", sa.String(length=20), nullable=True),
        sa.Column("closing_observation_id", sa.BigInteger(), nullable=True),
        sa.Column("kapanis_kaniti", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.BigInteger(), nullable=True),
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
            "(status <> 'KAPATILDI' OR (kapanis_turu IS NOT NULL AND closed_at IS NOT NULL)) AND (kapanis_turu IS DISTINCT FROM 'MANUEL' OR length(trim(coalesce(kapanis_kaniti, ''))) > 0) AND (kapanis_turu IS DISTINCT FROM 'OTOMATIK_GOZLEM' OR closing_observation_id IS NOT NULL)",
            name="ck_tca_kapanis",
        ),
        sa.CheckConstraint(
            "kapanis_turu IS NULL OR kapanis_turu IN ('MANUEL', 'OTOMATIK_GOZLEM')",
            name="ck_tca_kapanis_turu",
        ),
        sa.CheckConstraint("status IN ('ACIK', 'KAPATILDI')", name="ck_tca_durum"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["closing_observation_id"], ["training_observations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["training_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["sorumlu_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", name="uq_tca_gozlem"),
    )
    op.create_index(
        "ix_tca_acik",
        "training_corrective_actions",
        ["user_id", "course_id"],
        unique=False,
        postgresql_where=sa.text("status = 'ACIK'"),
    )
    op.create_table(
        "competencies",
        sa.Column("kod", sa.String(length=20), nullable=False),
        sa.Column("ad", sa.String(length=150), nullable=False),
        sa.Column("birim", sa.String(length=20), nullable=True),
        sa.Column("onerilen_hedef", sa.SmallInteger(), server_default=sa.text("3"), nullable=False),
        sa.Column("is_critical", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "birim IS NULL OR birim IN ('GUVENLIK', 'HABERLESME', 'POC', 'MOBILITE', 'ARAC_TAKIP')",
            name="ck_cmp_birim",
        ),
        sa.CheckConstraint("onerilen_hedef >= 1 AND onerilen_hedef <= 4", name="ck_cmp_hedef"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kod", name="uq_cmp_kod"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_cmp_kaynak"),
    )
    op.create_table(
        "competency_assessments",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("competency_id", sa.BigInteger(), nullable=False),
        sa.Column("mevcut_seviye", sa.SmallInteger(), nullable=False),
        sa.Column("hedef_seviye", sa.SmallInteger(), nullable=False),
        sa.Column("degerlendirme_tarihi", sa.Date(), nullable=False),
        sa.Column("assessed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("assessed_by_ad", sa.String(length=100), nullable=True),
        sa.Column("kanit", sa.Text(), nullable=True),
        sa.Column("kaynak", sa.String(length=12), nullable=False),
        sa.Column("observation_id", sa.BigInteger(), nullable=True),
        sa.Column("sonraki_degerlendirme", sa.Date(), nullable=True),
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
        sa.Column("source_system", sa.String(length=20), nullable=True),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "kaynak = 'GOC' OR assessed_by_user_id IS NOT NULL", name="ck_cas_kanit_kaynak"
        ),
        sa.CheckConstraint(
            "kaynak IN ('GOZLEM', 'SINAV', 'YONETICI', 'GOC')", name="ck_cas_kaynak"
        ),
        sa.CheckConstraint(
            "assessed_by_user_id IS NULL OR assessed_by_user_id <> user_id",
            name="ck_cas_oz_degerlendirme",
        ),
        sa.CheckConstraint(
            "mevcut_seviye >= 1 AND mevcut_seviye <= 4 AND hedef_seviye >= 1 AND hedef_seviye <= 4",
            name="ck_cas_seviye",
        ),
        sa.ForeignKeyConstraint(["assessed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["training_observations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_system", "source_ref", name="uq_cas_kaynak"),
    )
    op.create_index(
        "ix_cas_son",
        "competency_assessments",
        [
            "user_id",
            "competency_id",
            sa.literal_column("degerlendirme_tarihi DESC"),
            sa.literal_column("id DESC"),
        ],
        unique=False,
    )
    op.create_table(
        "personnel_certificates",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=True),
        sa.Column("belge_adi", sa.String(length=200), nullable=False),
        sa.Column("verilis_tarihi", sa.Date(), nullable=False),
        sa.Column("gecerlilik_bitis", sa.Date(), nullable=True),
        sa.Column("belge_no", sa.String(length=60), nullable=True),
        sa.Column("aciklama", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.BigInteger(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=300), nullable=True),
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
        sa.CheckConstraint("(cancelled_at IS NULL) = (cancel_reason IS NULL)", name="ck_pc_iptal"),
        sa.CheckConstraint(
            "gecerlilik_bitis IS NULL OR gecerlilik_bitis >= verilis_tarihi", name="ck_pc_aralik"
        ),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pc_bitis",
        "personnel_certificates",
        ["gecerlilik_bitis"],
        unique=False,
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )
    op.create_index("ix_pc_kisi", "personnel_certificates", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pc_kisi", table_name="personnel_certificates")
    op.drop_index(
        "ix_pc_bitis",
        table_name="personnel_certificates",
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )
    op.drop_table("personnel_certificates")
    op.drop_index("ix_cas_son", table_name="competency_assessments")
    op.drop_table("competency_assessments")
    op.drop_table("competencies")
    op.drop_index(
        "ix_tca_acik",
        table_name="training_corrective_actions",
        postgresql_where=sa.text("status = 'ACIK'"),
    )
    op.drop_table("training_corrective_actions")
    op.drop_table("training_observation_ratings")
    op.drop_index("ix_tob_servis", table_name="training_observations")
    op.drop_index("ix_tob_kisi_kurs_asama", table_name="training_observations")
    op.drop_table("training_observations")
    op.drop_index("ix_ta_kisi", table_name="training_attendance")
    op.drop_table("training_attendance")
    op.drop_index(
        "uq_tp_kisi_kurs_yil",
        table_name="training_plans",
        postgresql_where=sa.text("NOT is_deleted AND status <> 'IPTAL'"),
    )
    op.drop_index("ix_tp_yil_durum", table_name="training_plans")
    op.drop_index("ix_tp_kisi", table_name="training_plans")
    op.drop_table("training_plans")
    op.drop_index("ix_ts_kurs_tarih", table_name="training_sessions")
    op.drop_table("training_sessions")
    op.drop_table("training_criteria")
    op.drop_table("training_courses")
