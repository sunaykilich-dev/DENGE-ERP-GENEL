"""Tamir bedeli gizliliği (TS-092; E05-18 KRİTİK).

`maliyet.gor` olmayan kullanıcıda `repair_amount` ANAHTAR olarak yoktur
(None değil): liste, detay, Excel, PDF bağlamı. Gönderdiği tutar sessizce yok
sayılır (403 değil, 200 ve DB değeri korunur). Olay geçmişi tutar içermez.
"""

from decimal import Decimal
from io import BytesIO

import pytest
from atolye_yardimci import ONEK, atolye_olaylari, duzelt, kabul_et, sef
from openpyxl import load_workbook
from servis_yardimci import giris, musteri
from sqlalchemy import select

from app.models import WorkshopRecord
from app.services.teknik_servis import atolye

pytestmark = pytest.mark.integration


async def _maliyetli(rol_ac, birimli_kullanici_ac):
    await rol_ac(
        "T_ATOLYE_MALIYET",
        ["atolye.gor", "atolye.yaz", "maliyet.gor", "servis_rapor.disaaktar"],
        "KENDI_BIRIMI",
    )
    return await birimli_kullanici_ac("mal_kisi", "T_ATOLYE_MALIYET", ["HABERLESME"])


async def test_maliyetsiz_kullanici_anahtari_hic_gormez_ve_yazamaz(
    client, db, birimli_kullanici_ac, rol_ac
) -> None:
    await sef(birimli_kullanici_ac)
    await _maliyetli(rol_ac, birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "mal_kisi")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await duzelt(client, so_id, repair_amount="150.50")
    assert (await client.get(f"{ONEK}/{so_id}")).json()["repair_amount"] == 150.5

    await giris(client, "atl_sef")
    detay = (await client.get(f"{ONEK}/{so_id}")).json()
    assert "repair_amount" not in detay
    assert all("repair_amount" not in s for s in (await client.get(ONEK)).json())
    # Sessizce yok sayılır.
    r = await duzelt(client, so_id, repair_amount="999")
    assert "repair_amount" not in r.json()
    kayit = await db.scalar(
        select(WorkshopRecord)
        .where(WorkshopRecord.service_order_id == so_id)
        .execution_options(populate_existing=True)
    )
    assert kayit.repair_amount == Decimal("150.50")
    # Excel: bedel sütunu yok.
    r = await client.get(f"{ONEK}/disaaktar")
    assert r.status_code == 200
    basliklar = [c.value for c in next(load_workbook(BytesIO(r.content)).active.iter_rows())]
    assert "Tamir Bedeli" not in basliklar
    # Olay geçmişinde tutar yok.
    for o in await atolye_olaylari(db, so_id):
        assert "150" not in o.ozet and "150" not in str(o.veri)

    # PDF bağlamı: anahtar bağlama hiç girmez; HTML'de ₺ yok.
    from app.services.pdf import html_uret

    veri = await atolye.belge_verisi(db, kayit)
    gizli = atolye.kabul_fisi_baglami(veri, goster_bedel=False)
    assert "tamir_bedeli" not in gizli
    html = html_uret("atolye_kabul_fisi.html", **gizli)
    assert "₺" not in html
    assert "Şikâyet" in html and "SN-0001" in html
    acik = atolye.teslim_tutanagi_baglami(veri, goster_bedel=True)
    assert acik["tamir_bedeli"] == Decimal("150.50")
    assert "₺" in html_uret("atolye_teslim_tutanagi.html", **acik)


async def test_maliyetli_excel_bedel_sutunu(client, db, birimli_kullanici_ac, rol_ac) -> None:
    await _maliyetli(rol_ac, birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "mal_kisi")
    d = await kabul_et(client, hesap.id)
    await duzelt(client, d["so_id"], repair_amount="75")
    r = await client.get(f"{ONEK}/disaaktar")
    satirlar = list(load_workbook(BytesIO(r.content)).active.iter_rows(values_only=True))
    assert satirlar[0][-1] == "Tamir Bedeli" and satirlar[1][-1] == 75
