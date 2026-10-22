"""Atölye listesi, yaşlandırma, KPI kutuları ve Excel (TS-098).

Kural "sayı = liste": her KPI kutusunun sayısı, kutunun açtığı süzgeçle
listenin `X-Toplam-Kayit` başlığına eşittir; Excel aynı süzgecin satırlarını
verir.
"""

from io import BytesIO

import pytest
from atolye_yardimci import ONEK, gec, kabul_et, sef
from openpyxl import load_workbook
from servis_yardimci import giris, musteri

pytestmark = pytest.mark.integration


async def test_kpi_sayisi_liste_toplamina_esit_ve_yaslandirma(
    client, db, birimli_kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    eski = await kabul_et(client, hesap.id, "Y-1", estimated_finish_date="2026-01-02")
    client.clock.advance(days=16)
    await giris(client, "atl_sef")
    yeni = await kabul_et(client, hesap.id, "Y-2")
    await gec(client, yeni["so_id"], "TESHISTE")
    ozet = (await client.get(f"{ONEK}/ozet")).json()
    kutular = {k["kod"]: k for k in ozet}
    assert kutular["ACIK"]["deger"] == 2
    assert kutular["YAS_15+"]["deger"] == 1 and kutular["YAS_0-3"]["deger"] == 1
    assert kutular["GECIKEN"]["deger"] == 1
    for k in ozet:
        r = await client.get(ONEK, params=k["sorgu"])
        assert r.status_code == 200, (k["kod"], r.text)
        assert int(r.headers["X-Toplam-Kayit"]) == k["deger"], k["kod"]
    satirlar = {s["so_id"]: s for s in (await client.get(ONEK)).json()}
    assert satirlar[eski["so_id"]]["bekleme_gunu"] == 16
    assert satirlar[eski["so_id"]]["geciken"] is True
    # Marka karşılaştırması harf duyarsız; bilinmeyen durum 400.
    r = await client.get(ONEK, params={"marka": "hytera"})
    assert r.headers["X-Toplam-Kayit"] == "2"
    assert (await client.get(ONEK, params={"durum": "YOK"})).status_code == 400
    assert (await client.get(ONEK, params={"q": "Y-2"})).headers["X-Toplam-Kayit"] == "1"


async def test_excel_satirlari_liste_ile_ayni(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    for i in range(3):
        await kabul_et(client, hesap.id, f"X-{i}")
    liste = await client.get(ONEK, params={"durum": "KABUL_EDILDI"})
    r = await client.get(f"{ONEK}/disaaktar", params={"durum": "KABUL_EDILDI"})
    assert r.status_code == 200
    satirlar = list(load_workbook(BytesIO(r.content)).active.iter_rows(values_only=True))[1:]
    assert {s[0] for s in satirlar} == {s["atolye_no"] for s in liste.json()}
    assert r.headers["X-Toplam-Kayit"] == liste.headers["X-Toplam-Kayit"] == "3"


async def test_form_verileri(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    await giris(client, "atl_sef")
    r = await client.get(f"{ONEK}/form-verileri")
    assert r.status_code == 200
    assert r.json()["ariza_nedenleri"]
    assert "HYTERA" in r.json()["markalar"]
