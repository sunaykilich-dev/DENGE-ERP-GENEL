"""Servis işi listesi: sunucu süzgeci, SQL kapsamı, sayfalama ve tipli Excel
(TS-026; E01-15, E12-06).

Gerçek hikâye: eski sistemde liste istemcide süzülüyordu ve Excel'de
`0012345` seri numarası `12345` sayısına dönüyordu. Burada süzgeç sunucuda,
kapsam SQL'de, `X-Toplam-Kayit` = Excel satır sayısı, seri ve telefon METİN.
"""

from datetime import date, timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook
from servis_yardimci import giris, teknisyen

from app.models import ServiceOrderSerial

pytestmark = pytest.mark.integration


async def _seri(db, so, seri):
    db.add(ServiceOrderSerial(service_order_id=so.id, seri_no=seri, seri_norm=seri))
    await db.commit()


async def test_excel_izni(client, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("op_x1", "SERVIS_OPERASYON", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_x1", "SERVIS_SEF", ["GUVENLIK"])
    await giris(client, "op_x1")
    assert (await client.get("/api/teknik-servis/isler.xlsx")).status_code == 403
    await giris(client, "sef_x1")
    assert (await client.get("/api/teknik-servis/isler.xlsx")).status_code == 200


async def test_varsayilan_liste_ve_arama(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_x2", "SERVIS_SEF", ["GUVENLIK"])
    simdi = client.clock.now()
    acik = await servis_isi_ac(konu="Turnike arızası")
    yeni_kapali = await servis_isi_ac(durum="KAPATILDI", closed_at=simdi - timedelta(days=10))
    eski_kapali = await servis_isi_ac(durum="KAPATILDI", closed_at=simdi - timedelta(days=120))
    await servis_isi_ac(birim="HABERLESME")
    await _seri(db, acik, "0012345")
    await giris(client, "sef_x2")
    r = await client.get("/api/teknik-servis/isler")
    assert sorted(x["id"] for x in r.json()) == sorted([acik.id, yeni_kapali.id])
    r = await client.get("/api/teknik-servis/isler", params={"kapali_dahil": True})
    assert eski_kapali.id in [x["id"] for x in r.json()]
    for q in ("0012345", "turnike", acik.so_no, "Servis Müşterisi"):
        r = await client.get("/api/teknik-servis/isler", params={"q": q})
        assert acik.id in [x["id"] for x in r.json()], q
    r = await client.get("/api/teknik-servis/isler", params={"durum_grubu": "KAPALI"})
    assert {x["id"] for x in r.json()} == {yeni_kapali.id, eski_kapali.id}
    r = await client.get("/api/teknik-servis/isler", params={"durum": "UCAN"})
    assert r.status_code == 400


async def test_sayfalar_arasinda_kayit_kaybi_yok(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_x3", "SERVIS_SEF", ["GUVENLIK"])
    for i in range(7):
        await servis_isi_ac(konu=f"İş {i}")
    await giris(client, "sef_x3")
    gorulen = []
    for offset in range(0, 7, 3):
        r = await client.get("/api/teknik-servis/isler", params={"limit": 3, "offset": offset})
        assert r.headers["X-Toplam-Kayit"] == "7"
        gorulen += [x["id"] for x in r.json()]
    assert len(gorulen) == len(set(gorulen)) == 7


async def test_excel_toplam_tipler_ve_maskeleme(
    client, db, rol_ac, kullanici_ac, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await rol_ac("T_RAPORCU", ["servis.gor", "servis_rapor.disaaktar"], "TUMU")
    await kullanici_ac("raporcu", "T_RAPORCU")
    tek = await teknisyen(birimli_kullanici_ac, "tek_x4")
    a = await servis_isi_ac(
        konu="=cmd|' /C calc'!A0",
        iletisim_telefon="+905321112233",
        atananlar=[tek],
        seri=None,
    )
    await servis_isi_ac(birim="HABERLESME", durum="ISLEMDE")
    await _seri(db, a, "0012345")
    await giris(client, "raporcu")
    liste = await client.get("/api/teknik-servis/isler")
    r = await client.get("/api/teknik-servis/isler.xlsx")
    assert r.status_code == 200
    assert r.headers["X-Toplam-Kayit"] == liste.headers["X-Toplam-Kayit"] == "2"
    wb = load_workbook(BytesIO(r.content))
    ws = wb["Servis İşleri"]
    basliklar = [h.value for h in ws[1]]
    satirlar = list(ws.iter_rows(min_row=2))
    assert len(satirlar) == 2
    satir = next(s for s in satirlar if s[0].value == a.so_no)
    hucre = dict(zip(basliklar, satir, strict=True))
    assert hucre["Seri No"].value == "0012345" and hucre["Seri No"].data_type == "s"
    assert hucre["Telefon"].value == "**********233"  # disaaktar var, servis.yaz yok
    assert hucre["Konu"].data_type == "s"  # formül değil
    assert hucre["Açılış"].is_date
    assert hucre["Sorumlu"].value == "Tek_X4"
    ozet = wb["Durum Özeti"]
    son = [h.value for h in list(ozet.iter_rows())[-1]]
    assert son[0] == "Toplam" and son[-1] == 2


async def test_kendi_isleri_listede_ve_excelde_ayni(
    client, db, rol_ac, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await rol_ac("T_TEK_RAPOR", ["servis.gor", "servis_rapor.disaaktar"], "KENDI_ISLERI")
    kisi = await birimli_kullanici_ac("tek_x5", "T_TEK_RAPOR", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    benim = await servis_isi_ac(atananlar=[kisi])
    await servis_isi_ac()
    await giris(client, "tek_x5")
    r = await client.get("/api/teknik-servis/isler")
    assert [x["id"] for x in r.json()] == [benim.id]
    r = await client.get("/api/teknik-servis/isler.xlsx")
    assert r.headers["X-Toplam-Kayit"] == "1"
    ws = load_workbook(BytesIO(r.content))["Servis İşleri"]
    assert [row[0].value for row in ws.iter_rows(min_row=2)] == [benim.so_no]


async def test_tarih_suzgeci_yerel_gun(client, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_x6", "SERVIS_SEF", ["GUVENLIK"])
    await servis_isi_ac()
    await giris(client, "sef_x6")
    r = await client.get(
        "/api/teknik-servis/isler", params={"bas": "2030-01-02", "bit": "2030-01-01"}
    )
    assert r.status_code == 400
    r = await client.get("/api/teknik-servis/isler", params={"bas": str(date(2000, 1, 1))})
    assert r.headers["X-Toplam-Kayit"] == "1"
