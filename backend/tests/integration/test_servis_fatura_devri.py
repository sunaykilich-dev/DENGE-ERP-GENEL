"""Maliyet Excel'i, fatura devri işareti, teklif dönüşüm raporu (TS-197).

Kabul: (E07-26) kabul teklifli / gelirli kapanmış iş listede; işaretlenince
listeden düşer, "İletilenler"de kim/ne zaman ile görünür; `tahsilat.gor`
olmayan 403; kapsam dışı bir kimlik içeren toplu istek 409 ve HİÇBİR satır
işaretlenmez; işaret sonrası gelir kilidi (409). (E07-22) `servis_rapor.
disaaktar` olmayan 403; durum sütunları var, eksik tutar boş; müşteri adı
formül olarak yazılmaz. (E07-24) 10 gönderilen: 6 kabul, 2 ret, 2 süresi
dolan → %60; revizyon bir kez sayılır; başka birim girmez; "Teklifler" satırı
= toplam; satış raporu değişmez.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO

import pytest
from bakim_yardimci import giris
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import Account, AuditLog, Quote, QuoteVersion
from app.models.servis_maliyet import ServiceOrderFinancial

pytestmark = pytest.mark.integration

ONEK = "/api/teknik-servis/maliyet"
_AN = datetime(2026, 1, 1, 8, tzinfo=UTC)


@pytest.fixture
async def ortam(db, kullanici_ac, birimli_kullanici_ac, rol_ac):
    await rol_ac("T_DEVIR", ["tahsilat.gor", "tahsilat.yaz"], "KENDI_BIRIMI")
    return {
        "muhasebe": await kullanici_ac("muh_f", "MUHASEBE_DESTEK"),
        "admin": await kullanici_ac("adm_f", "ADMIN"),
        "devirci": await birimli_kullanici_ac("devir_f", "T_DEVIR", ["GUVENLIK"]),
        "sef": await birimli_kullanici_ac("sef_f2", "SERVIS_SEF", ["GUVENLIK"]),
    }


async def _gelirli_is(
    db, servis_isi_ac, *, birim="GUVENLIK", durum="TAMAMLANDI", gelir="1000", kalite=True
):
    # Kalite kapısı (KARARLAR 2026-11-04 §7.2): devre yalnız kalite onaylı iş düşer.
    so = await servis_isi_ac(
        birim=birim, durum=durum, completed_at=_AN, kalite_onay_at=_AN if kalite else None
    )
    db.add(
        ServiceOrderFinancial(
            service_order_id=so.id,
            gelir=Decimal(gelir),
            gelir_kaynagi="ELLE",
            gelir_notu="Elle gelir",
        )
    )
    await db.commit()
    return so


async def test_fatura_devri_akisi_kilit_ve_geri_alma(client, db, ortam, servis_isi_ac):
    client.clock.set(datetime(2026, 2, 3, 10, tzinfo=UTC))
    so1 = await _gelirli_is(db, servis_isi_ac)
    so2 = await servis_isi_ac(
        birim="GUVENLIK", durum="KAPATILDI", completed_at=_AN, kalite_onay_at=_AN
    )
    db.add(
        Quote(
            quote_no="TKF-DEVIR-1",
            customer_id=so2.customer_id,
            birim="GUVENLIK",
            status="KABUL",
            service_order_id=so2.id,
        )
    )
    await db.commit()
    await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI")  # gelirsiz: listede yok
    await _gelirli_is(db, servis_isi_ac, kalite=False)  # kalite onaysız: listede yok
    await _gelirli_is(db, servis_isi_ac, durum="ISLEMDE")  # açık: listede yok
    yabanci = await _gelirli_is(db, servis_isi_ac, birim="HABERLESME")

    await giris(client, "sef_f2")
    assert (await client.get(f"{ONEK}/fatura-devri")).status_code == 403

    await giris(client, "muh_f")
    r = await client.get(f"{ONEK}/fatura-devri")
    assert r.status_code == 200, r.text
    assert int(r.headers["X-Toplam-Kayit"]) == 3  # so1, so2, yabanci (TUMU)
    satirlar = {x["so_id"]: x for x in r.json()}
    assert satirlar[so2.id]["teklifler"] == ["TKF-DEVIR-1"]
    assert satirlar[so1.id]["tutar"] == "1000.00"  # teklif.gor/maliyet.gor var

    # KENDI_BIRIMI devirci: tutar anahtarı yok, yabancı iş görünmez.
    await giris(client, "devir_f")
    r = await client.get(f"{ONEK}/fatura-devri")
    assert int(r.headers["X-Toplam-Kayit"]) == 2
    assert all("tutar" not in x for x in r.json())
    r = await client.post(f"{ONEK}/fatura-devri/isaretle", json={"is_idler": [so1.id, yabanci.id]})
    assert r.status_code == 409
    assert r.json()["detail"]["sorunlu_isler"] == [yabanci.id]
    for so in (so1, yabanci):
        fin = await db.scalar(
            select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so.id)
        )
        await db.refresh(fin)
        assert fin.fatura_iletildi_at is None  # hiçbiri işaretlenmedi

    r = await client.post(
        f"{ONEK}/fatura-devri/isaretle", json={"is_idler": [so1.id], "not": "Şubat faturası"}
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"{ONEK}/fatura-devri")
    assert {x["so_id"] for x in r.json()} == {so2.id}
    r = await client.get(f"{ONEK}/fatura-devri", params={"durum": "iletildi"})
    [iletilen] = r.json()
    assert iletilen["so_id"] == so1.id and iletilen["iletti"] == ortam["devirci"].full_name
    assert iletilen["fatura_iletildi_at"].startswith("2026-02-03")

    # Gelir kilidi: işaret sonrası gelir yazılamaz.
    await giris(client, "adm_f")
    r = await client.put(
        f"{ONEK}/isler/{so1.id}/gelir", json={"kaynak": "ELLE", "tutar": 5, "not": "x"}
    )
    assert r.status_code == 409

    await giris(client, "devir_f")
    r = await client.post(f"{ONEK}/fatura-devri/{yabanci.id}/geri-al", json={"gerekce": "x"})
    assert r.status_code == 404  # kapsam dışı
    r = await client.post(f"{ONEK}/fatura-devri/{so1.id}/geri-al", json={"gerekce": " "})
    assert r.status_code == 400
    r = await client.post(f"{ONEK}/fatura-devri/{so1.id}/geri-al", json={"gerekce": "Yanlış"})
    assert r.status_code == 200, r.text
    r = await client.post(f"{ONEK}/fatura-devri/{so1.id}/geri-al", json={"gerekce": "Yine"})
    assert r.status_code == 409  # işaretsiz
    r = await client.get(f"{ONEK}/fatura-devri")
    assert {x["so_id"] for x in r.json()} == {so1.id, so2.id}
    eylemler = set(
        (
            await db.scalars(
                select(AuditLog.action).where(AuditLog.entity == "service_order_financials")
            )
        ).all()
    )
    assert {"fatura.iletildi", "fatura.geri_al"} <= eylemler


async def test_analiz_xlsx_izin_durum_sutunlari_ve_formul(client, db, ortam, servis_isi_ac):
    musteri = Account(title='=HYPERLINK("http://kotu")', is_musteri=True)
    db.add(musteri)
    await db.commit()
    so = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI", musteri=musteri)
    so.completed_at = datetime(2026, 1, 10, 9, tzinfo=UTC)
    await db.commit()

    await giris(client, "muh_f")  # maliyet.gor var, servis_rapor.disaaktar yok
    assert (await client.get(f"{ONEK}/analiz.xlsx", params={"donem": "2026-01"})).status_code == 403

    await giris(client, "adm_f")
    r = await client.get(f"{ONEK}/analiz.xlsx", params={"donem": "2026-01"})
    assert r.status_code == 200, r.text
    ws = load_workbook(BytesIO(r.content)).active
    basliklar = [h.value for h in ws[1]]
    for ad in ("İşçilik Durumu", "Malzeme Durumu", "Gelir Durumu", "Fark Durumu"):
        assert ad in basliklar
    satir = {basliklar[i]: ws.cell(row=2, column=i + 1) for i in range(len(basliklar))}
    assert satir["İşçilik"].value is None  # süre kaydı yok → boş, 0 değil
    assert satir["İşçilik Durumu"].value == "Süre kaydı eksik"
    assert satir["Müşteri"].data_type == "s"
    assert str(satir["Müşteri"].value).startswith("=HYPERLINK")

    r = await client.get(f"{ONEK}/analiz.xlsx", params={"donem": "2026-01", "kirilim": "musteri"})
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.content)).active
    assert ws.cell(row=2, column=2).value == 1  # iş adedi
    assert ws.cell(row=2, column=8).value is None  # tam iş yok → fark boş
    assert (await client.get(f"{ONEK}/analiz.xlsx")).status_code == 400  # dönem zorunlu


async def _teklif(db, musteri_id, no, birim, durum, *, gecerlilik=None, surum=1, **kw):
    t = Quote(quote_no=no, customer_id=musteri_id, birim=birim, status=durum, **kw)
    db.add(t)
    await db.flush()
    son = None
    for n in range(1, surum + 1):
        son = QuoteVersion(
            quote_id=t.id,
            version_no=n,
            valid_until=gecerlilik,
            sent_at=_AN,
            accepted_at=datetime(2026, 1, 3, 8, tzinfo=UTC) if durum == "KABUL" else None,
            rejected_at=datetime(2026, 1, 5, 8, tzinfo=UTC) if durum == "RED" else None,
            subtotal=Decimal("100"),
            grand_total=Decimal("120"),
            vat_total=Decimal("20"),
        )
        db.add(son)
        await db.flush()
    t.current_version_id = son.id
    await db.commit()
    return t


async def test_teklif_donusumu_yuzde_60_kapsam_ve_excel(client, db, ortam):
    musteri = Account(title="Dönüşüm Müşterisi", is_musteri=True)
    db.add(musteri)
    await db.commit()
    for i in range(6):
        await _teklif(db, musteri.id, f"TKF-K{i}", "GUVENLIK", "KABUL", surum=2 if i == 0 else 1)
    for i in range(2):
        await _teklif(db, musteri.id, f"TKF-R{i}", "GUVENLIK", "RED", lost_reason="Fiyat")
    for i in range(2):  # süresi dolmuş ama worker işaretlememiş
        await _teklif(
            db, musteri.id, f"TKF-S{i}", "GUVENLIK", "GONDERILDI", gecerlilik=date(2025, 12, 1)
        )
    await _teklif(db, musteri.id, "TKF-H1", "HABERLESME", "KABUL")
    satis_once = None

    await giris(client, "adm_f")
    satis_once = (await client.get("/api/raporlar/teklif-donusumu")).json()

    await giris(client, "sef_f2")
    r = await client.get(f"{ONEK}/teklif-donusumu", params={"birim": "GUVENLIK"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["toplam_teklif"] == 10 and v["gonderilen_adet"] == 10
    assert (v["kazanilan"], v["kaybedilen"]) == (6, 4)
    assert v["donusum_yuzde"] == 60.0
    assert v["kabul_tutari_net"] == "600.00"
    assert v["ort_yanit_gun"] is not None
    assert (
        await client.get(f"{ONEK}/teklif-donusumu", params={"birim": "HABERLESME"})
    ).status_code == 403
    assert (await client.get(f"{ONEK}/teklif-donusumu", params={"birim": "XX"})).status_code == 400

    r = await client.get(f"{ONEK}/teklif-donusumu.xlsx", params={"birim": "GUVENLIK"})
    assert r.status_code == 200, r.text
    ws = load_workbook(BytesIO(r.content))["Teklifler"]
    assert ws.max_row - 1 == v["toplam_teklif"]

    await giris(client, "adm_f")
    assert (await client.get("/api/raporlar/teklif-donusumu")).json() == satis_once


async def test_fatura_devri_disaaktarim_finans_uzmani_ve_izin_kapisi(
    client, db, ortam, rol_ac, kullanici_ac, servis_isi_ac
):
    """Dışa aktarım: `tahsilat.gor` VE (`rapor.disaaktar` VEYA `servis_rapor.disaaktar`).

    Finans Uzmanı (MUHASEBE_DESTEK) `rapor.disaaktar` taşır, `servis_rapor.
    disaaktar` taşımaz; ekranı açtığı halde Excel/CSV alamıyordu (UI/UX denetimi T7).
    """
    so = await _gelirli_is(db, servis_isi_ac)

    await giris(client, "muh_f")
    r = await client.get(f"{ONEK}/fatura-devri.xlsx")
    assert r.status_code == 200, r.text
    ws = load_workbook(BytesIO(r.content)).active
    assert ws.max_row == 2 and ws.cell(2, 1).value == so.so_no
    r = await client.get(f"{ONEK}/fatura-devri.xlsx", params={"bicim": "csv"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")

    # tahsilat.gor var, hiçbir dışa aktarım izni yok → 403.
    await rol_ac("T_DEVIR_OKU", ["tahsilat.gor"], "TUMU")
    await kullanici_ac("devir_oku", "T_DEVIR_OKU")
    await giris(client, "devir_oku")
    assert (await client.get(f"{ONEK}/fatura-devri")).status_code == 200
    assert (await client.get(f"{ONEK}/fatura-devri.xlsx")).status_code == 403

    # Dışa aktarım izni var ama tahsilat.gor yok → 403.
    await rol_ac("T_AKTAR", ["rapor.disaaktar", "servis_rapor.disaaktar"], "TUMU")
    await kullanici_ac("aktar_x", "T_AKTAR")
    await giris(client, "aktar_x")
    assert (await client.get(f"{ONEK}/fatura-devri.xlsx")).status_code == 403
