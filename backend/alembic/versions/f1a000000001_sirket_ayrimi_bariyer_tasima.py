"""şirket ayrımı, Set Bariyer birimi, Taşıma servis türü

KARARLAR 2026-11-04 §1-3. Tek migration (paket kuralı):

1. **Şirketler.** `sirketler` (kod, ad, aktif; DENGE TELEKOM / ELEKTRONİK /
   MOBİLİTE), `birim_sirketleri` (birim → şirket; her birim tek şirkette),
   `kullanici_sirketleri` (kullanıcı ↔ şirket). Ayrım anahtarı birimdir:
   kayıt tablolarına sütun EKLENMEZ, kapsam birim kümesi etkin şirketin
   birimleriyle kesiştirilir (`services/teknik_servis/kapsam.py`).
2. **Etkin şirket oturumda:** `sessions.aktif_sirket` (FK, NULL = üyelik yok).
3. **Veri göçü:** kullanıcının şirketleri birim üyeliklerinden türetilir;
   birimi olmayan ADMIN ve TUMU kapsamlı kullanıcıya bütün şirketler; kalan
   herkese DENGE MOBİLİTE (canlı sistem mobilite şirketidir — canlı
   kullanıcılar ekranlarını kaybetmesin). Açık oturumların etkin şirketi aynı
   varsayılan kuralla (`services/sirketler.varsayilan_sirket`) doldurulur:
   birincil birimin şirketi → MOBİLİTE → ilk üyelik.
4. **BARIYER birimi ("Set Bariyer", DENGE ELEKTRONİK):** bütün `ck_*_birim`
   kısıtları yeni kod kümesiyle yeniden kurulur (autogenerate CHECK
   değişikliğini görmez; liste `models.rbac.BIRIM_KODLARI` ile unit testte kilitli).
5. **TASIMA servis türü ("Taşıma"):** `ck_so_tur` ve `ck_scr_tur` yeniden kurulur.
6. `MUHASEBE_DESTEK` rolünün görünen adı "Finans Uzmanı" (yalnız ad hâlâ
   varsayılansa; elle değiştirilmiş ada dokunulmaz).

BEDEL / GERİ ALMA: downgrade şirket tablolarını ve oturum sütununu düşürür
(şirket ayrımı kalkar, herkes eski kapsamına döner). BARIYER birimli ya da
TASIMA türlü kayıt varsa eski kısıtlar kurulamaz — downgrade bunları sayar ve
açık mesajla DURUR (sessizce silmek iş geçmişini bozardı).

Revision ID: f1a000000001
Revises: e1a000000003
Create Date: 2026-11-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a000000001"
down_revision: str | None = "e1a000000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESKI_BIRIMLER = ("GUVENLIK", "HABERLESME", "POC", "MOBILITE", "ARAC_TAKIP")
YENI_BIRIMLER = (*ESKI_BIRIMLER, "BARIYER")

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
)
YENI_TURLER = (*ESKI_TURLER, "TASIMA")

SIRKETLER = (
    ("TELEKOM", "DENGE TELEKOM"),
    ("ELEKTRONIK", "DENGE ELEKTRONİK"),
    ("MOBILITE", "DENGE MOBİLİTE"),
)
BIRIM_SIRKETLERI = (
    ("HABERLESME", "TELEKOM"),
    ("POC", "TELEKOM"),
    ("GUVENLIK", "ELEKTRONIK"),
    ("BARIYER", "ELEKTRONIK"),
    ("MOBILITE", "MOBILITE"),
    ("ARAC_TAKIP", "MOBILITE"),
)
MOBILITE = "MOBILITE"

# (tablo, kısıt, birim boş olabilir mi) — modellerdeki `birim_check(...)` çağrıları.
BIRIM_KISITLARI = (
    ("user_units", "ck_user_units_birim", False),
    ("service_orders", "ck_so_birim", False),
    ("service_fault_reasons", "ck_sfr_birim", False),
    ("service_sla_policies", "ck_slap_birim", True),
    ("competencies", "ck_cmp_birim", True),
    ("service_labor_rates", "ck_iscilik_tarife_birim", False),
    ("training_courses", "ck_tc_birim", True),
    ("warehouses", "ck_warehouse_birim", True),
    ("service_competency_requirements", "ck_scr_birim", False),
    ("rental_assets", "ck_rasset_birim", False),
    ("rental_catalog_items", "ck_rcat_birim", False),
    ("service_vehicles", "ck_svcarac_birim", True),
    ("service_visits", "ck_svcvisit_birim", False),
    ("maintenance_contracts", "ck_mc_birim", False),
    ("service_equipment", "ck_svceq_birim", False),
    ("quotes", "ck_quote_birim", True),
    ("training_observations", "ck_tob_birim", True),
    ("rentals", "ck_rental_birim", False),
)


def _in(sutun: str, degerler: Sequence[str], *, bos: bool = False) -> str:
    ifade = f"{sutun} IN (" + ", ".join(f"'{d}'" for d in degerler) + ")"
    return f"{sutun} IS NULL OR {ifade}" if bos else ifade


def _birim_kisitlari(birimler: Sequence[str]) -> None:
    for tablo, ad, bos in BIRIM_KISITLARI:
        op.drop_constraint(ad, tablo, type_="check")
        op.create_check_constraint(ad, tablo, _in("birim", birimler, bos=bos))


def _tur_kisitlari(turler: Sequence[str]) -> None:
    op.drop_constraint("ck_so_tur", "service_orders", type_="check")
    op.create_check_constraint("ck_so_tur", "service_orders", _in("tur", sorted(turler)))
    op.drop_constraint("ck_scr_tur", "service_competency_requirements", type_="check")
    op.create_check_constraint("ck_scr_tur", "service_competency_requirements", _in("tur", turler))


def _veri_gocu() -> None:
    """Üyelik ve açık oturumların etkin şirketi (bkz. modül açıklaması §3)."""
    baglanti = op.get_bind()
    birim_sirketi = dict(BIRIM_SIRKETLERI)
    sira = [k for k, _ in SIRKETLER]
    kullanicilar = baglanti.execute(
        sa.text(
            "SELECT u.id, r.code, r.scope FROM users u JOIN roles r ON r.id = u.role_id"
        )
    ).all()
    birimler: dict[int, list[tuple[str, bool]]] = {}
    for user_id, birim, birincil in baglanti.execute(
        sa.text("SELECT user_id, birim, is_primary FROM user_units")
    ).all():
        birimler.setdefault(user_id, []).append((birim, birincil))

    varsayilan: dict[int, str | None] = {}
    satirlar = []
    for user_id, rol, kapsam in kullanicilar:
        uye_birimler = birimler.get(user_id, [])
        if uye_birimler:
            uyelik = {birim_sirketi[b] for b, _ in uye_birimler if b in birim_sirketi}
        elif rol == "ADMIN" or kapsam == "TUMU":
            uyelik = set(sira)
        else:
            uyelik = {MOBILITE}
        if rol == "ADMIN":
            uyelik = set(sira)
        uyeler = [k for k in sira if k in uyelik]
        satirlar += [{"u": user_id, "s": k} for k in uyeler]
        birincil = next((b for b, p in uye_birimler if p), None)
        if birincil is not None and birim_sirketi.get(birincil) in uyeler:
            varsayilan[user_id] = birim_sirketi[birincil]
        elif MOBILITE in uyeler:
            varsayilan[user_id] = MOBILITE
        else:
            varsayilan[user_id] = uyeler[0] if uyeler else None
    if satirlar:
        baglanti.execute(
            sa.text("INSERT INTO kullanici_sirketleri (user_id, sirket_kod) VALUES (:u, :s)"),
            satirlar,
        )
    guncel = [{"u": u, "s": s} for u, s in varsayilan.items() if s is not None]
    if guncel:
        baglanti.execute(
            sa.text("UPDATE sessions SET aktif_sirket = :s WHERE user_id = :u"), guncel
        )


def upgrade() -> None:
    # 4-5) Önce kod kümeleri: birim_sirketleri BARIYER satırını taşır.
    _birim_kisitlari(YENI_BIRIMLER)
    _tur_kisitlari(YENI_TURLER)

    # 1) Şirket tabloları
    op.create_table(
        "sirketler",
        sa.Column("kod", sa.String(length=20), primary_key=True),
        sa.Column("ad", sa.String(length=80), nullable=False),
        sa.Column("aktif", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(_in("kod", [k for k, _ in SIRKETLER]), name="ck_sirketler_kod"),
    )
    op.bulk_insert(
        sa.table("sirketler", sa.column("kod"), sa.column("ad")),
        [{"kod": k, "ad": a} for k, a in SIRKETLER],
    )
    zaman = (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_table(
        "birim_sirketleri",
        sa.Column("birim", sa.String(length=20), primary_key=True),
        sa.Column(
            "sirket_kod",
            sa.String(length=20),
            sa.ForeignKey("sirketler.kod", ondelete="RESTRICT"),
            nullable=False,
        ),
        *(c.copy() for c in zaman),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint(_in("birim", YENI_BIRIMLER), name="ck_birim_sirketleri_birim"),
    )
    op.create_index("ix_birim_sirketleri_sirket_kod", "birim_sirketleri", ["sirket_kod"])
    op.bulk_insert(
        sa.table("birim_sirketleri", sa.column("birim"), sa.column("sirket_kod")),
        [{"birim": b, "sirket_kod": s} for b, s in BIRIM_SIRKETLERI],
    )
    op.create_table(
        "kullanici_sirketleri",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "sirket_kod",
            sa.String(length=20),
            sa.ForeignKey("sirketler.kod", ondelete="CASCADE"),
            primary_key=True,
        ),
        *(c.copy() for c in zaman),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )

    # 2) Etkin şirket oturumda
    op.add_column(
        "sessions",
        sa.Column(
            "aktif_sirket",
            sa.String(length=20),
            sa.ForeignKey("sirketler.kod", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 3) Veri göçü
    _veri_gocu()

    # 6) Rol adı
    op.execute(
        "UPDATE roles SET name = 'Finans Uzmanı' "
        "WHERE code = 'MUHASEBE_DESTEK' AND name = 'Muhasebe Destek'"
    )


def downgrade() -> None:
    baglanti = op.get_bind()
    sorunlar = []
    for tablo, _ad, _bos in BIRIM_KISITLARI:
        n = baglanti.execute(
            sa.text(f"SELECT count(*) FROM {tablo} WHERE birim = 'BARIYER'")  # noqa: S608
        ).scalar()
        if n:
            sorunlar.append(f"{tablo}: {n} BARIYER satırı")
    for tablo in ("service_orders", "service_competency_requirements"):
        n = baglanti.execute(
            sa.text(f"SELECT count(*) FROM {tablo} WHERE tur = 'TASIMA'")  # noqa: S608
        ).scalar()
        if n:
            sorunlar.append(f"{tablo}: {n} TASIMA satırı")
    if sorunlar:
        raise RuntimeError(
            "f1a000000001 geri alınamaz: yeni birim/tür kullanılmış ("
            + "; ".join(sorunlar)
            + "). Önce bu kayıtları taşıyın ya da kapatın."
        )
    op.execute(
        "UPDATE roles SET name = 'Muhasebe Destek' "
        "WHERE code = 'MUHASEBE_DESTEK' AND name = 'Finans Uzmanı'"
    )
    op.drop_column("sessions", "aktif_sirket")
    op.drop_table("kullanici_sirketleri")
    op.drop_index("ix_birim_sirketleri_sirket_kod", table_name="birim_sirketleri")
    op.drop_table("birim_sirketleri")
    op.drop_table("sirketler")
    _tur_kisitlari(ESKI_TURLER)
    _birim_kisitlari(ESKI_BIRIMLER)
