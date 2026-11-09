"""İskonto yetkisi ve kademeli onay (KARARLAR 2026-11-09 S1; 10-28 G5.2/G5.5).

**Ölçü (S1.3):** teklifin iskonto oranı = en yüksek kalem iskontosu ile toplam
iskonto oranından (iskonto toplamı / brüt ara toplam) BÜYÜK olanı. Yalnız
kalem iskontosuna bakmak, her kaleme limitin hemen altında iskonto verip
toplamda aynı yere varmayı serbest bırakmazdı ama tersini (tek kalemde
büyük iskonto) yakalardı; ikisi birlikte ölçülür.

**Limit (S1.1/S1.2):** hazırlayanın (teklif sahibi) limiti = kişi limiti
(`users.iskonto_limiti_yuzde`) varsa o, yoksa rolünün limiti
(`iskonto_rol_limitleri` ayarı; tabloda olmayan rol → "DIGER").
`teklif.iskonto_ust_onay` sahibi (Genel Müdür, ADMIN) sınırsızdır.

**Kademe (S1.4):** oran ≤ limit → onay YOK (S1.6, tek adım bile yok).
Oran > limit → onay gerekir: oran satış müdürü rol limitinin içindeyse
"Satış Müdürü" kademesi, üstündeyse "Genel Müdür" kademesi. Onaylayan
`teklif.iskonto_onayla` ister ve oran KENDİ limitinin içinde olmalıdır
(müdür kendi limitinin üstünü onaylayamaz); `teklif.iskonto_ust_onay`
sahibi her oranı onaylar.

**Onayın düşmesi (S1.5):** onay sürüme yazılır (`discount_approved_*`).
Revizyon yeni sürüm açar (onay taşınmaz); taslağın yerinde düzenlenmesinde
fiyat/adet/iskonto değişirse onay silinir (`services/quotes.taslak_guncelle`).

Birimli (servis) teklifte iskonto iç onayla birlikte kapanır (K4, kararı
değişmedi): bu modül orada yalnız "iskonto onayı gerekli mi" sorusunu yanıtlar.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models import Quote, QuoteVersion, User
from app.services import settings as ayar_svc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SINIRSIZ = Decimal("100")
DIGER = "DIGER"
UST_ONAY_IZNI = "teklif.iskonto_ust_onay"
ONAY_IZNI = "teklif.iskonto_onayla"
KADEME_MUDUR = "SATIS_MUDURU"
KADEME_GENEL_MUDUR = "GENEL_MUDUR"
KADEME_ADLARI = {KADEME_MUDUR: "Satış Müdürü", KADEME_GENEL_MUDUR: "Genel Müdür"}
_VARSAYILAN_DIGER = Decimal("10")


def _yuzde(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def rol_limitleri(db: AsyncSession) -> dict[str, Decimal]:
    ham = await ayar_svc.get(db, "iskonto_rol_limitleri") or {}
    return {str(k): Decimal(str(v)) for k, v in dict(ham).items()}


def rol_limiti(rol_kodu: str | None, tablo: dict[str, Decimal]) -> Decimal:
    if rol_kodu is not None and rol_kodu in tablo:
        return tablo[rol_kodu]
    return tablo.get(DIGER, _VARSAYILAN_DIGER)


def kisi_limiti(user: User | None, tablo: dict[str, Decimal]) -> Decimal:
    """Kişinin iskonto üst limiti (yüzde). Sahipsiz teklif DIGER limitine tabidir."""
    if user is None:
        return rol_limiti(None, tablo)
    if user.has(UST_ONAY_IZNI):
        return SINIRSIZ
    if user.iskonto_limiti_yuzde is not None:
        return Decimal(str(user.iskonto_limiti_yuzde))
    return rol_limiti(user.role.code if user.role is not None else None, tablo)


def iskonto_orani(v: QuoteVersion) -> Decimal:
    """max(en yüksek kalem iskontosu, toplam iskonto oranı) — S1.3."""
    kalem = Decimal(str(v.max_discount_pct or 0))
    ara = Decimal(str(v.subtotal or 0))
    toplam = Decimal(str(v.discount_total or 0)) / ara * Decimal("100") if ara > 0 else Decimal("0")
    return _yuzde(max(kalem, toplam))


@dataclass
class IskontoDurumu:
    oran: Decimal
    limit: Decimal
    onay_gerekli: bool
    kademe: str | None
    onaylandi: bool

    @property
    def onay_bekliyor(self) -> bool:
        return self.onay_gerekli and not self.onaylandi

    @property
    def kademe_adi(self) -> str | None:
        return KADEME_ADLARI.get(self.kademe) if self.kademe else None


def durum_hesapla(
    v: QuoteVersion, hazirlayan: User | None, tablo: dict[str, Decimal]
) -> IskontoDurumu:
    oran = iskonto_orani(v)
    limit = kisi_limiti(hazirlayan, tablo)
    gerekli = oran > limit
    kademe = None
    if gerekli:
        kademe = KADEME_MUDUR if oran <= rol_limiti(KADEME_MUDUR, tablo) else KADEME_GENEL_MUDUR
    return IskontoDurumu(
        oran=oran,
        limit=limit,
        onay_gerekli=gerekli,
        kademe=kademe,
        onaylandi=v.discount_approved_at is not None,
    )


async def durum(db: AsyncSession, t: Quote, v: QuoteVersion) -> IskontoDurumu:
    hazirlayan = await db.get(User, t.owner_id) if t.owner_id else None
    return durum_hesapla(v, hazirlayan, await rol_limitleri(db))


async def hazirlayanlar(db: AsyncSession, teklifler: list[Quote]) -> dict[int, User]:
    """Toplu çıktı için teklif sahipleri (rol ilişkisi `selectin`; N+1 yok)."""
    idler = {t.owner_id for t in teklifler if t.owner_id}
    if not idler:
        return {}
    return {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(idler)))).all()}


def onaylayabilir_mi(user: User, oran: Decimal, tablo: dict[str, Decimal]) -> bool:
    """Onaylayan `teklif.iskonto_onayla` ister; oran kendi limitinin içinde
    olmalı ya da `teklif.iskonto_ust_onay` sahibi olmalı (S1.4)."""
    if not user.has(ONAY_IZNI) and not user.has(UST_ONAY_IZNI):
        return False
    return oran <= kisi_limiti(user, tablo)


def kalem_imzasi(kalemler) -> list[tuple]:
    """Onayı düşüren alanlar (S1.5): ürün, adet, birim fiyat, iskonto."""
    return sorted(
        (
            k.product_id or 0,
            str(Decimal(str(k.qty)).normalize()),
            str(Decimal(str(k.unit_price)).normalize()),
            str(Decimal(str(k.discount_pct)).normalize()),
        )
        for k in kalemler
    )
