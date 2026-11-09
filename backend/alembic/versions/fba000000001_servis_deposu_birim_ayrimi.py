"""servis depoları birimlere ayrılır: birimsiz (ortak) servis deposu kalmaz

Kullanıcı isteği (2026-11-09): "depo işlerini haberleşme güvenlik diye
tamamen ayır, teknisyenler diğer birimlerin deposunu görmesin". Görünürlük
kuralı kodda (`teknik_servis.parca.depo_kosulu`: birimsiz depo yalnız TUMU
kapsamına görünür); bu migration VERİYİ eşler ve kuralı şemaya yazar.

1. Birimi boş servis depolarını eşler (rastgele atama YOK):
   a. Teknisyen araç deposu (`user_id` dolu): sahibinin birincil birimi; birincil
      yoksa ve tek birim üyeliği varsa o birim.
   b. Kalanlar kod/ad ile: yalnız "HAB"/"HABERLE" geçiyorsa HABERLESME, yalnız
      "GUV"/"GÜV" geçiyorsa GUVENLIK. İkisi birden ya da hiçbiri → boş kalır.
   Eşlenemeyenler uyarı olarak loglanır; bulmak için:
   `SELECT id, code, name FROM warehouses WHERE servis_deposu AND birim IS NULL;`
   Bunlar yalnız tüm birimleri gören kullanıcılara görünür; yönetici
   Yedek Parça > Depolar ekranından birimini seçer.
2. `ck_warehouse_servis_birim_zorunlu` (servis deposu → birim zorunlu) eklenir. Eşlenemeyen
   satır kaldıysa NOT VALID eklenir (yeni/güncellenen satıra uygulanır), hepsi
   eşlendiyse doğrulanır.

Kiralama ve mobilite depolarına DOKUNULMAZ (`servis_deposu=false`).

BEDEL / GERİ ALMA: downgrade yalnız kısıtı düşürür; yapılan birim atamaları
geri alınmaz (hangi satırın önceden boş olduğu tutulmaz; atama zararsızdır).

Revision ID: fba000000001
Revises: faa000000001
Create Date: 2026-11-09

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fba000000001"
down_revision: str | None = "faa000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_log = logging.getLogger("alembic.runtime.migration")

_KISIT = "ck_warehouse_servis_birim_zorunlu"
_TR = str.maketrans("ÇĞİIÖŞÜçğıiöşü", "CGIIOSUCGIIOSU")


def _ada_gore(code: str, name: str) -> str | None:
    metin = f"{code} {name}".translate(_TR).upper()
    hab = "HAB" in metin
    guv = "GUV" in metin
    if hab and not guv:
        return "HABERLESME"
    if guv and not hab:
        return "GUVENLIK"
    return None


def esle(baglanti: sa.Connection) -> list[tuple[int, str, str]]:
    """Birimsiz servis depolarını eşler; eşlenemeyenleri döner (id, kod, ad)."""
    satirlar = baglanti.execute(
        sa.text(
            "SELECT id, code, name, user_id FROM warehouses "
            "WHERE servis_deposu AND birim IS NULL ORDER BY id"
        )
    ).all()
    kalan: list[tuple[int, str, str]] = []
    for depo_id, code, name, user_id in satirlar:
        birim = None
        if user_id is not None:
            uyelik = baglanti.execute(
                sa.text("SELECT birim, is_primary FROM user_units WHERE user_id = :u"),
                {"u": user_id},
            ).all()
            birincil = [b for b, p in uyelik if p] or [b for b, _ in uyelik]
            if len(birincil) == 1:
                birim = birincil[0]
        if birim is None:
            birim = _ada_gore(code or "", name or "")
        if birim is None:
            kalan.append((depo_id, code, name))
            continue
        baglanti.execute(
            sa.text("UPDATE warehouses SET birim = :b WHERE id = :i"), {"b": birim, "i": depo_id}
        )
        _log.info("Servis deposu %s (%s) → %s", code, depo_id, birim)
    return kalan


def upgrade() -> None:
    baglanti = op.get_bind()
    kalan = esle(baglanti)
    for depo_id, code, name in kalan:
        _log.warning(
            "Servis deposu birime eşlenemedi (elle seçilmeli): id=%s kod=%s ad=%s",
            depo_id,
            code,
            name,
        )
    op.execute(
        f"ALTER TABLE warehouses ADD CONSTRAINT {_KISIT} "
        "CHECK (NOT servis_deposu OR birim IS NOT NULL) NOT VALID"
    )
    if not kalan:
        op.execute(f"ALTER TABLE warehouses VALIDATE CONSTRAINT {_KISIT}")


def downgrade() -> None:
    op.execute(f"ALTER TABLE warehouses DROP CONSTRAINT IF EXISTS {_KISIT}")
