"""faz a: kiralama cakisma uyarisi, ofis agi kisiti, istemci turune gore oturum

KARARLAR 2026-10-28 §7 Faz A, maddeler 4 ve 8. Üç bağımsız şema değişikliği
tek migration'da (paket kuralı: Faz A-g bir migration):

1. **M10.1 — kiralamada çifte rezervasyon uyarıdır, engel değil.** Aynı seri
   kiralık cihazın tarihleri çakışan iki AKTİF tahsisini reddeden
   `ex_rtahsis_cihaz_cakisma` (EXCLUDE USING gist) kaldırılır. Servis katmanı
   çakışmayı 409 + liste ile bildirir; kullanıcı gerekçe yazıp onaylarsa kayıt
   yapılır ve gerekçe denetim izine düşer. Çakışma sorgusu hızlı kalsın diye
   AYNI ifade ve koşulla GiST indeksi açılır: `ix_rtahsis_cihaz_aralik`
   (`asset_id`, `daterange(baslangic, bitis, '[)')`, yalnız AKTİF seri satır).

2. **G3.8 — rol bazlı erişim yeri.** `roles.yalniz_ofis` (varsayılan false):
   bu roldeki kullanıcı yalnız `ofis_ag_listesi` ayarındaki CIDR'lardan
   girer/istek atar; liste boşsa kısıt yok (kurulum günü kimse kilitlenmez).
   Muhasebe rolü (`MUHASEBE_DESTEK`) migration'da işaretlenir — özelleştirilmiş
   olsa da: karar role aittir, izin listesine değil. Diğer roller false.

3. **G3.7 — masaüstünde kısa, mobilde uzun oturum.** `sessions.istemci`
   (`MASAUSTU` | `MOBIL`, varsayılan MASAUSTU; `ck_sessions_istemci`). Süreyi
   sunucu seçer (`services/auth.OTURUM_SURELERI`, kod sabiti); mevcut açık
   oturumlar masaüstü sayılır, davranışları değişmez.

BEDEL / GERİ ALMA: downgrade EXCLUDE kısıtını yeniden kurar; o ana kadar
gerekçeyle onaylanmış çakışan AKTİF tahsis varsa kısıt kurulamaz — downgrade
bunu önce sayar ve açık mesajla DURUR (çakışmaları kapatmadan geri alınamaz;
sessizce satır silmek kiralama geçmişini bozardı). Kolonlar düşer: ofis
kısıtı ve mobil oturum süresi kalkar (açık mobil oturumlar masaüstü süresine
döner, bir sonraki istekte süresi geçmişse düşer).

Revision ID: e1a000000003
Revises: e1a000000002
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1a000000003"
down_revision: str | None = "e1a000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARALIK = "daterange(baslangic, bitis, '[)')"
_AKTIF_SERI = "asset_id IS NOT NULL AND durum = 'AKTIF'"


def upgrade() -> None:
    # 1) M10.1
    op.execute("ALTER TABLE rental_allocations DROP CONSTRAINT ex_rtahsis_cihaz_cakisma")
    op.create_index(
        "ix_rtahsis_cihaz_aralik",
        "rental_allocations",
        ["asset_id", sa.text(_ARALIK)],
        postgresql_using="gist",
        postgresql_where=sa.text(_AKTIF_SERI),
    )

    # 2) G3.8
    op.add_column(
        "roles",
        sa.Column("yalniz_ofis", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute("UPDATE roles SET yalniz_ofis = true WHERE code = 'MUHASEBE_DESTEK'")

    # 3) G3.7
    op.add_column(
        "sessions",
        sa.Column(
            "istemci", sa.String(length=10), server_default=sa.text("'MASAUSTU'"), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_sessions_istemci", "sessions", "istemci IN ('MASAUSTU', 'MOBIL')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_sessions_istemci", "sessions", type_="check")
    op.drop_column("sessions", "istemci")
    op.drop_column("roles", "yalniz_ofis")

    baglanti = op.get_bind()
    cakisan = baglanti.execute(
        sa.text(
            "SELECT count(*) FROM rental_allocations a JOIN rental_allocations b "
            "ON a.asset_id = b.asset_id AND a.id < b.id "
            "WHERE a.durum = 'AKTIF' AND b.durum = 'AKTIF' AND a.asset_id IS NOT NULL "
            "AND daterange(a.baslangic, a.bitis, '[)') && daterange(b.baslangic, b.bitis, '[)')"
        )
    ).scalar_one()
    if cakisan:
        raise RuntimeError(
            f"{cakisan} çift AKTİF kiralık cihaz tahsisi var (M10.1 gerekçeli onay). "
            "ex_rtahsis_cihaz_cakisma geri kurulamaz; önce bu tahsisleri çözün/kapatın."
        )
    op.drop_index("ix_rtahsis_cihaz_aralik", table_name="rental_allocations")
    op.create_exclude_constraint(
        "ex_rtahsis_cihaz_cakisma",
        "rental_allocations",
        (sa.column("asset_id"), "="),
        (sa.literal_column(_ARALIK), "&&"),
        where=sa.text(_AKTIF_SERI),
        using="gist",
    )
