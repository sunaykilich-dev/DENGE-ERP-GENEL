"""Bakım fişi ve onarım fişi (KARARLAR 2026-11-09 S6) — servis formundan AYRI şablonlar.

Veri servis formuyla aynı kaynaktan gelir (`onay._is_bolumu`: müşteri,
lokasyon, ekip, sonuç, süre, kontrol listesi, müşteri onayı); bunun üstüne
işe yazılan parça çıkışları eklenir. Şablonlar: `bakim_fisi.html`,
`onarim_fisi.html`.

* **Hangi iş:** bakım fişi planlı/plansız bakım işi (`PB`, `PLANSIZ_BAKIM`);
  onarım fişi arıza ve atölye işi (`ARIZA`, `ATOLYE`). Diğer türde 409 —
  o işin belgesi servis formudur.
* **Fiyat:** varsayılan FİYATSIZ (sahada müşteriye imzalatılan belge). İstek
  `fiyatli=true` ise ve kullanıcı tutar görebiliyorsa (`fatura_devri.tutar_gorur_mu`:
  `teklif.gor` ya da `maliyet.gor`) işin hizmet bedeli (gelir, KDV hariç)
  basılır. Parça MALİYETİ (alış) hiçbir koşulda basılmaz — müşteri belgesidir.
* **Süre:** kayıt yoksa "Süre kaydı eksik" (0 değil; korunacak karar).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models import Product, ServiceOrder, StockMovement
from app.models.servis_maliyet import ServiceOrderFinancial
from app.services.teknik_servis.kancalar import ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

BAKIM_TURLERI = ("PB", "PLANSIZ_BAKIM")
ONARIM_TURLERI = ("ARIZA", "ATOLYE")
FIS_TURLERI = {
    "bakim": (BAKIM_TURLERI, "BAKIM FİŞİ", "bakim_fisi.html", "bakım"),
    "onarim": (ONARIM_TURLERI, "ONARIM FİŞİ", "onarim_fisi.html", "onarım"),
}


class FisTuruUyumsuz(ServisHatasi):
    """İşin türü bu fişe uymuyor (409)."""


async def parcalar(db: AsyncSession, so_id: int) -> list[dict[str, Any]]:
    """İşe yazılan parçaların NET kullanımı (çıkış − iade, ters kayıt dahil)."""
    satirlar = (
        await db.execute(
            select(Product.code, Product.name, Product.birim, func.sum(-StockMovement.qty))
            .join(Product, Product.id == StockMovement.product_id)
            .where(StockMovement.service_order_id == so_id)
            .group_by(Product.code, Product.name, Product.birim)
            .order_by(Product.name)
        )
    ).all()
    from app.services.irsaliye import BIRIM_ADLARI

    return [
        {
            "kod": kod,
            "ad": ad,
            "miktar": int(net),
            "birim": BIRIM_ADLARI.get(birim or "ADET", "Adet"),
        }
        for kod, ad, birim, net in satirlar
        if net and net > 0
    ]


async def baglam(
    db: AsyncSession, so: ServiceOrder, tur: str, *, fiyatli: bool, clock: Clock
) -> dict[str, Any]:
    from app.services.pdf import tl
    from app.services.teknik_servis import onay

    turler, baslik, _sablon, ad = FIS_TURLERI[tur]
    if so.tur not in turler:
        raise FisTuruUyumsuz(
            f"Bu iş {onay.SERVIS_TURU_ADLARI.get(so.tur, so.tur)} türünde; {ad} fişi "
            "basılmaz. Servis formunu kullanın."
        )
    bolum = await onay._is_bolumu(db, so)
    bolum["parcalar"] = await parcalar(db, so.id)
    bedel = None
    if fiyatli:
        fin = await db.scalar(
            select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so.id)
        )
        bedel = tl(fin.gelir) if fin is not None and fin.gelir is not None else "Tutar kaydı yok"
    return {
        "firma": await onay._firma(db),
        "baslik": baslik,
        "belge_tarihi": yerel_bugun(clock).strftime("%d.%m.%Y"),
        "s": bolum,
        "fiyatli": fiyatli,
        "hizmet_bedeli": bedel,
        "bakim_kodu": so.tur,
    }


async def pdf(
    db: AsyncSession, so: ServiceOrder, tur: str, *, fiyatli: bool, clock: Clock
) -> bytes:
    from app.services.pdf import pdf_uret_async

    sablon = FIS_TURLERI[tur][2]
    return await pdf_uret_async(sablon, **await baglam(db, so, tur, fiyatli=fiyatli, clock=clock))


def tutar_hakki(user) -> bool:
    from app.services.teknik_servis.fatura_devri import tutar_gorur_mu

    return tutar_gorur_mu(user)
