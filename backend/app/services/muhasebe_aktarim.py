"""Logo'ya aktarılabilir irsaliye ve sipariş dökümü — Excel ve CSV (KARARLAR 2026-11-09 S4.4).

**Logo entegrasyonu DEĞİLDİR.** Logo'nun muhasebe ürünü ve sürümü hâlâ
bilinmiyor (10-28 §6/6); API Faz D'de, ürün öğrenilince gelecek. Burada
Logo'nun Excel/CSV aktarım ekranına verilebilecek, SATIR BAZLI (fiş başlığı
her satırda tekrar eden) düz bir döküm üretilir. Kolon adları Logo Tiger/Go
aktarım alanlarının Türkçe adlarına yakın seçildi; ürün belli olunca eşleme
şablonu Logo tarafında bir kez kurulur.

* **Cari kodu:** hesabın `dis_referans`'ı (Logo cari kodu girilmişse), yoksa
  `CR` + 6 haneli ERP kimliği — her dışa aktarımda aynı kalır.
* **Fiyat:** irsaliyede birim fiyat/iskonto/KDV kolonları yalnız
  `irsaliye.fiyat_gorur_mu` sahibine eklenir (kolon hiç yazılmaz). Maliyet
  (alış fiyatı) hiçbir dökümde yoktur.
* **CSV:** `;` ayraçlı, UTF-8 BOM'lu (Türkçe Excel ve Logo aktarımı `İ, ş, ğ`
  harflerini bozmadan okusun), ondalık ayıracı virgül. `= + - @` ile başlayan
  METİN hücresinin başına `'` eklenir (CSV'de formül enjeksiyonu; sayılar
  sayı olarak yazıldığı için etkilenmez).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models import Account, Order, OrderLine, Product
from app.services import export as export_svc
from app.services.irsaliye import BIRIM_ADLARI, cari_kodu, fiyat_gorur_mu

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Irsaliye, User

S = export_svc.Sutun
FORMUL_BASI = ("=", "+", "-", "@", "\t", "\r")


def _fis_turu(irs: Irsaliye) -> str:
    if irs.order_id is not None or irs.hedef_konum in ("MUSTERI", "BAYI"):
        return "Toptan Satış İrsaliyesi"
    return "Sevk İrsaliyesi"


async def _hesaplar(db: AsyncSession, idler: set[int | None]) -> dict[int, Account]:
    temiz = [i for i in idler if i is not None]
    if not temiz:
        return {}
    return {h.id: h for h in (await db.scalars(select(Account).where(Account.id.in_(temiz))))}


async def irsaliye_tablosu(
    db: AsyncSession, user: User, irsaliyeler: list[Irsaliye]
) -> tuple[list[Any], list[list[Any]]]:
    """(sütunlar, satırlar) — her irsaliye kalemi bir satır."""
    fiyat = fiyat_gorur_mu(user)
    hesaplar = await _hesaplar(db, {i.alici_account_id for i in irsaliyeler})
    siparis_nolari = {
        o.id: o.order_no
        for o in (
            await db.scalars(
                select(Order).where(Order.id.in_([i.order_id for i in irsaliyeler if i.order_id]))
            )
        )
    }
    sutunlar: list[Any] = [
        S("Fiş Türü"),
        S("İrsaliye No"),
        S("İrsaliye Tarihi", "tarih"),
        S("Sevk Tarihi", "tarih"),
        S("Cari Kodu"),
        S("Cari Ünvanı"),
        S("VKN/TCKN"),
        S("Vergi Dairesi"),
        S("Sevk Adresi"),
        S("Ambar"),
        S("Satır No", "tamsayi"),
        S("Malzeme Kodu"),
        S("Malzeme Açıklaması"),
        S("Miktar", "ondalik"),
        S("Birim"),
        S("Seri/Lot No"),
    ]
    if fiyat:
        sutunlar += [S("Birim Fiyat", "ondalik"), S("İskonto %", "ondalik"), S("KDV %", "ondalik")]
    sutunlar += [S("Sipariş No"), S("Durum"), S("Muhasebe Devri", "zaman"), S("Açıklama")]

    satirlar: list[list[Any]] = []
    for irs in irsaliyeler:
        hesap = hesaplar.get(irs.alici_account_id or 0)
        for k in irs.kalemler:
            satir: list[Any] = [
                _fis_turu(irs),
                irs.irsaliye_no,
                irs.duzenleme_tarihi,
                irs.sevk_tarihi,
                cari_kodu(irs.alici_account_id, hesap.dis_referans if hesap else None),
                irs.alici_unvan,
                irs.alici_vkn,
                irs.alici_vergi_dairesi,
                irs.alici_adres,
                irs.cikis_depo_adi,
                k.sira,
                k.urun_kodu,
                k.aciklama,
                k.miktar,
                BIRIM_ADLARI.get(k.birim, k.birim),
                k.seri_nolar,
            ]
            if fiyat:
                satir += [
                    k.birim_fiyat,
                    k.iskonto_yuzde,
                    Decimal(str(k.kdv_orani)) * 100 if k.kdv_orani is not None else None,
                ]
            satir += [
                siparis_nolari.get(irs.order_id or 0),
                "İptal" if irs.durum == "IPTAL" else "Düzenlendi",
                irs.muhasebe_devri_at,
                irs.notlar,
            ]
            satirlar.append(satir)
    return sutunlar, satirlar


SIPARIS_DURUM_ADLARI = {
    "TASLAK": "Taslak",
    "ONAYLANDI": "Onaylandı",
    "REZERVE": "Rezerve",
    "KISMI_SEVK": "Kısmi sevk",
    "SEVK_EDILDI": "Sevk edildi",
    "TAMAMLANDI": "Tamamlandı",
    "IPTAL": "İptal",
}


async def siparis_tablosu(
    db: AsyncSession, siparisler: list[Order]
) -> tuple[list[Any], list[list[Any]]]:
    """Sipariş satırları. Sipariş fiyatı `siparis.gor` sahibine zaten açıktır."""
    from app.models import Irsaliye

    idler = [s.id for s in siparisler]
    hesaplar = await _hesaplar(db, {s.customer_id for s in siparisler})
    kalemler: dict[int, list[OrderLine]] = {}
    for k in (
        await db.scalars(
            select(OrderLine)
            .where(OrderLine.order_id.in_(idler or [0]))
            .order_by(OrderLine.order_id, OrderLine.sort_order, OrderLine.id)
        )
    ).all():
        kalemler.setdefault(k.order_id, []).append(k)
    urunler = {
        u.id: u
        for u in (
            await db.scalars(
                select(Product).where(
                    Product.id.in_(
                        [k.product_id for ks in kalemler.values() for k in ks if k.product_id]
                        or [0]
                    )
                )
            )
        )
    }
    irsaliyeler: dict[int, list[str]] = {}
    for oid, no in (
        await db.execute(
            select(Irsaliye.order_id, Irsaliye.irsaliye_no)
            .where(Irsaliye.order_id.in_(idler or [0]), Irsaliye.durum == "DUZENLENDI")
            .order_by(Irsaliye.id)
        )
    ).all():
        irsaliyeler.setdefault(oid, []).append(no)

    sutunlar: list[Any] = [
        S("Sipariş No"),
        S("Sipariş Tarihi", "tarih"),
        S("Cari Kodu"),
        S("Cari Ünvanı"),
        S("VKN/TCKN"),
        S("Satır No", "tamsayi"),
        S("Malzeme Kodu"),
        S("Açıklama"),
        S("Miktar", "ondalik"),
        S("Sevk Edilen", "ondalik"),
        S("Birim"),
        S("Birim Fiyat", "ondalik"),
        S("İskonto %", "ondalik"),
        S("KDV %", "ondalik"),
        S("Satır Tutarı (KDV hariç)", "ondalik"),
        S("Döviz"),
        S("Kur", "ondalik"),
        S("Durum"),
        S("İrsaliye No"),
        S("Muhasebe Devri", "zaman"),
    ]
    satirlar: list[list[Any]] = []
    for s in siparisler:
        hesap = hesaplar.get(s.customer_id)
        for i, k in enumerate(kalemler.get(s.id, []), start=1):
            urun = urunler.get(k.product_id or 0)
            satirlar.append(
                [
                    s.order_no,
                    s.order_date,
                    cari_kodu(s.customer_id, hesap.dis_referans if hesap else None),
                    hesap.title if hesap else None,
                    hesap.tax_no if hesap else None,
                    i,
                    urun.code if urun else None,
                    k.description,
                    k.qty,
                    k.qty_shipped,
                    BIRIM_ADLARI.get(urun.birim or "ADET", "Adet") if urun else "Adet",
                    k.unit_price,
                    k.discount_pct,
                    Decimal(str(k.vat_rate)) * 100,
                    k.line_total,
                    s.currency,
                    s.fx_rate,
                    SIPARIS_DURUM_ADLARI.get(s.status, s.status),
                    ", ".join(irsaliyeler.get(s.id, [])) or None,
                    s.muhasebe_devri_at,
                ]
            )
    return sutunlar, satirlar


# --- Biçimler ----------------------------------------------------------------------


def _csv_hucre(deger: Any, tip: str) -> str:
    from zoneinfo import ZoneInfo

    if deger is None or deger == "":
        return ""
    if isinstance(deger, datetime):
        if deger.tzinfo is not None:
            deger = deger.astimezone(ZoneInfo("Europe/Istanbul"))
        return deger.strftime("%d.%m.%Y %H:%M") if tip == "zaman" else deger.strftime("%d.%m.%Y")
    if isinstance(deger, date):
        return deger.strftime("%d.%m.%Y")
    if tip in ("ondalik", "tamsayi") and isinstance(deger, (int, float, Decimal)):
        d = Decimal(str(deger))
        metin = f"{d:f}" if tip == "tamsayi" else f"{d.quantize(Decimal('0.01')):f}"
        return metin.replace(".", ",")
    metin = str(deger)
    if metin.startswith(FORMUL_BASI):
        metin = "'" + metin
    return metin


def csv_uret(sutunlar: list[Any], satirlar: list[list[Any]]) -> bytes:
    tampon = io.StringIO()
    yazici = csv.writer(tampon, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    yazici.writerow([s.baslik for s in sutunlar])
    for satir in satirlar:
        yazici.writerow([_csv_hucre(d, s.tip) for d, s in zip(satir, sutunlar, strict=False)])
    return ("﻿" + tampon.getvalue()).encode("utf-8")


async def dosya_uret(
    bicim: str, sayfa_adi: str, sutunlar: list[Any], satirlar: list[list[Any]]
) -> tuple[bytes, str, str]:
    """(içerik, medya tipi, uzantı)."""
    if bicim == "csv":
        return csv_uret(sutunlar, satirlar), "text/csv; charset=utf-8", "csv"
    icerik = await export_svc.sayfalari_xlsx_async(
        [export_svc.Sayfa(sayfa_adi, sutunlar, satirlar, otomatik_filtre=True)]
    )
    return (
        icerik,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    )
