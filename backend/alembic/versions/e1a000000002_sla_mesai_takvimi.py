"""SLA mesai takvimi: hesap/lokasyon takvim türü + SQL mesai dakikası (Faz A-1, TS-200)

NEDEN: Karar 2026-10-28 §7 Faz A madde 1 (M5.1, M5.4, M12.2): SLA sayımı
müşteri sözleşmesine bağlıdır — kimi müşteri 7/24, kimi MESAI (hafta içi
08:30–18:00, Europe/Istanbul; resmî/dinî tatiller FARK ETMEZ, tatil tablosu
yok). Lokasyona özel SLA (M12.2) hesabın değerini ezer. Öncelik:
lokasyon → hesap → SLA politikası (`service_sla_policies.takvim_turu`) → 7/24.
Sonuç iş açılışında `service_orders.sla_takvim_turu`'na DONDURULUR (kolon
d2a000000001'den beri var; yeni kolon gerekmez).

Yeni şema:

* `accounts.sla_takvim_turu`, `addresses.sla_takvim_turu` — NULL olabilir
  (NULL = üst düzeyden devral). Mevcut satırlar NULL kalır → davranış
  değişmez (politikalar bugün hep 7/24).
* `ck_accounts_sla_takvim`, `ck_addresses_sla_takvim` — değer sözlüğü
  (`models/teknik_servis.SLA_TAKVIM_TURLERI`).
* `servis_mesai_dk(bas, bit, gun_bas_dk, gun_bit_dk)` SQL fonksiyonu —
  Python `sla_takvim.takvim_dakika(..., "MESAI")` ile AYNI hesap (hafta içi,
  yerel saat, saniyeler toplanır sonra dakikaya aşağı yuvarlanır). Operasyon
  Merkezi'nin "SLA riskte" sayacı liste sorgusunun içinde hesaplandığı için
  (`sla.sla_ifadeleri`) mesai oranı SQL'de de gerekli; ikisinin aynı sonucu
  verdiği `test_servis_sla_mesai` ile sınanır.

BEDEL: Canlı `accounts` ve `addresses` tablolarına birer nullable kolon +
CHECK. Mobilite kodu bu kolonları okumaz/yazmaz. Downgrade kolonları ve
fonksiyonu düşürür; MESAI damgalı açık işlerin hedefi işte durduğu için
bozulmaz, ancak politika MESAI ise eski kod 409 verir (eski davranış).

Revision ID: e1a000000002
Revises: d4a000000002
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1a000000002"
down_revision: str | None = "d4a000000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `models/teknik_servis.SLA_TAKVIM_TURLERI` ile aynı (birim testi kilitler).
SLA_TAKVIM_TURLERI = ("7_24", "MESAI")
_DEGERLER = ", ".join(f"'{t}'" for t in SLA_TAKVIM_TURLERI)

MESAI_FONKSIYONU = """
CREATE OR REPLACE FUNCTION servis_mesai_dk(
    p_bas timestamptz, p_bit timestamptz, p_gun_bas integer, p_gun_bit integer
) RETURNS integer
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN p_bas IS NULL OR p_bit IS NULL THEN NULL
        WHEN p_bit <= p_bas THEN 0
        ELSE floor(coalesce(sum(GREATEST(0, extract(epoch FROM
                LEAST(p_bit, (g.gun + make_interval(mins => p_gun_bit))
                             AT TIME ZONE 'Europe/Istanbul')
              - GREATEST(p_bas, (g.gun + make_interval(mins => p_gun_bas))
                             AT TIME ZONE 'Europe/Istanbul')
             ))), 0) / 60)::integer
    END
    FROM generate_series(
        date_trunc('day', p_bas AT TIME ZONE 'Europe/Istanbul'),
        date_trunc('day', p_bit AT TIME ZONE 'Europe/Istanbul'),
        interval '1 day'
    ) AS g(gun)
    -- Hafta içi (Pzt=1 … Cum=5); tatiller karar gereği fark etmez.
    WHERE extract(isodow FROM g.gun) BETWEEN 1 AND 5
$$
"""


def upgrade() -> None:
    for tablo in ("accounts", "addresses"):
        op.add_column(tablo, sa.Column("sla_takvim_turu", sa.String(10), nullable=True))
        op.create_check_constraint(
            f"ck_{tablo}_sla_takvim",
            tablo,
            f"sla_takvim_turu IS NULL OR sla_takvim_turu IN ({_DEGERLER})",
        )
    op.execute(MESAI_FONKSIYONU)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS servis_mesai_dk(timestamptz, timestamptz, integer, integer)")
    for tablo in ("addresses", "accounts"):
        op.drop_constraint(f"ck_{tablo}_sla_takvim", tablo, type_="check")
        op.drop_column(tablo, "sla_takvim_turu")
