"""Altın KPI seti (TS-183, E12-07) ve "sayı = liste = Excel" çapraz testleri (TS-181).

Beklenen tablo (`fixtures/servis_rapor_beklenen.json`) elle hesaplandı; altı
filtre kombinasyonunda `/ozet` değerleri tabloya, her KPI `/kpi-liste`
toplamına ve (taşınabilen süzgeçte) Servis İşleri `/isler?kpi=&donem=`
toplamına, Yönetim Özeti Excel'ine eşit olmalı.
"""

from __future__ import annotations

from io import BytesIO
from urllib.parse import parse_qsl, urlsplit

import pytest
from openpyxl import load_workbook
from servis_rapor_ortam import BEKLENEN, DONEM, R, altin_kur, giris, servis_rapor_seed
from sqlalchemy import func, select

from app.models import AuditLog, ServiceOrder, ServiceTimeEntry

pytestmark = pytest.mark.integration


@pytest.fixture
async def altin(client, db, kullanici_ac, birimli_kullanici_ac):
    seed, kisiler = await altin_kur(db, kullanici_ac, birimli_kullanici_ac)
    return seed, kisiler


def _params(komb: dict) -> dict:
    return {**DONEM, **komb["params"]}


async def _ozet(client, komb) -> dict:
    await giris(client, komb["kullanici"])
    r = await client.get(f"{R}/ozet", params=_params(komb))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("komb", BEKLENEN["kombinasyonlar"], ids=lambda k: k["ad"])
async def test_beklenen_tablo_esit(client, altin, komb):
    govde = await _ozet(client, komb)
    degerler = {k["kod"]: k["deger"] for k in govde["kpiler"]}
    assert {k: degerler[k] for k in komb["kpi"]} == komb["kpi"]
    olcum = {o["kod"]: o["deger"] for o in govde["olcumler"]}
    assert {k: olcum[k] for k in komb["olcum"]} == komb["olcum"]
    if "onceki" in komb:
        onceki = {k["kod"]: k["onceki"] for k in govde["kpiler"]}
        assert {k: onceki[k] for k in komb["onceki"]} == komb["onceki"]
    if "toplamlar" in komb:
        t = govde["toplamlar"]
        assert {k: t[k] for k in komb["toplamlar"]} == komb["toplamlar"]
    # Toplam eşitliği her filtrede (Açık + Çözüldü + İptal = Toplam).
    t = govde["toplamlar"]
    assert t["esit"] and t["toplam"] == t["acik"] + t["cozuldu"] + t["iptal"]
    assert govde["generated_at"].startswith("2026-01-01")
    assert govde["kapsam"]


@pytest.mark.parametrize("komb", BEKLENEN["kombinasyonlar"], ids=lambda k: k["ad"])
async def test_kpi_sayisi_liste_toplamina_esit(client, altin, komb):
    """Her KPI: `/ozet` değeri = `/kpi-liste` `X-Toplam-Kayit` = Servis İşleri
    `/isler?kpi=&donem=` `X-Toplam-Kayit` (süzgeç taşınabiliyorsa)."""
    govde = await _ozet(client, komb)
    for kpi in govde["kpiler"]:
        r = await client.get(
            f"{R}/kpi-liste", params={**_params(komb), "kpi": kpi["kod"], "limit": 1}
        )
        assert r.status_code == 200, r.text
        assert int(r.headers["X-Toplam-Kayit"]) == kpi["deger"], kpi["kod"]
        yol = kpi["isler_yolu"]
        assert (yol is not None) == komb["isler_ekrani"], kpi["kod"]
        if yol is None:
            continue
        sorgu = dict(parse_qsl(urlsplit(yol).query))
        r = await client.get("/api/teknik-servis/isler", params={**sorgu, "limit": 1})
        assert r.status_code == 200, r.text
        assert int(r.headers["X-Toplam-Kayit"]) == kpi["deger"], (kpi["kod"], yol)


async def test_kirilim_beklenen_ve_toplam_esit(client, altin):
    await giris(client, "mudur")
    for boyut, beklenen in BEKLENEN["kirilim_A"].items():
        r = await client.get(f"{R}/kirilim", params={**DONEM, "boyut": boyut})
        assert r.status_code == 200, r.text
        govde = r.json()
        assert {s["ad"]: s["toplam"] for s in govde["satirlar"]} == beklenen, boyut
        assert govde["toplam_esit"] is True
        assert govde["toplam"] == 27


async def test_lokasyon_kirilimi_eslesmeyen_ve_bos(client, altin):
    """Göç işi (müşteri eşleşmemiş) "Eşleştirilmemiş: …" satırında; Şubat'ı da
    kapsayan seçimde görünür."""
    await giris(client, "mudur")
    r = await client.get(
        f"{R}/kirilim",
        params={"baslangic": "2026-02-01", "bitis": "2026-03-31", "boyut": "musteri"},
    )
    assert r.status_code == 200, r.text
    adlar = {s["ad"] for s in r.json()["satirlar"]}
    assert "Eşleştirilmemiş: Gama Ltd" in adlar
    r = await client.get(
        f"{R}/kirilim",
        params={"baslangic": "2026-02-01", "bitis": "2026-03-31", "boyut": "lokasyon"},
    )
    satirlar = {s["ad"]: s for s in r.json()["satirlar"]}
    assert "Eşleştirilmemiş: Gama Depo" in satirlar
    assert satirlar["Akyaka AVM"]["sehir"] == "Muğla"
    assert satirlar["Akyaka AVM"]["kisi_saat"] == 6.0


async def test_personel_kisi_saat_ve_eksik_satiri(client, altin):
    await giris(client, "mudur")
    r = await client.get(f"{R}/kisi-saat", params=DONEM)
    assert r.status_code == 200, r.text
    govde = r.json()
    satirlar = {s["personel"]: s for s in govde["satirlar"]}
    for ad, beklenen in BEKLENEN["personel_A"].items():
        assert {k: satirlar[ad][k] for k in beklenen} == beklenen, ad
    # Kişi toplamı (eksik satır None) = genel kişi-saat.
    assert sum(s["kisi_saat"] or 0 for s in govde["satirlar"]) == govde["toplam"]["toplam_saat"]
    assert "MOLA" not in satirlar["Ali Veli"]  # mola kişi-saate girmez
    # J1: SAHA 2 + 1, J4: SAHA 1 + 1,5 → 5,5; YOL 0,5.
    assert satirlar["Ali Veli"]["SAHA"] == 5.5 and satirlar["Ali Veli"]["YOL"] == 0.5


async def test_yeniden_acilan_olay_listesi(client, altin):
    await giris(client, "mudur")
    r = await client.get(f"{R}/yeniden-acilan", params=DONEM)
    assert r.status_code == 200, r.text
    govde = r.json()
    beklenen = BEKLENEN["yeniden_acilan_A"]
    assert govde["olay_sayisi"] == beklenen["olay_sayisi"]
    olay = govde["olaylar"][0]
    assert olay["gun_farki"] == beklenen["gun_farki"]
    assert olay["gerekce"] == beklenen["gerekce"]
    assert govde["oran"] == 20.0
    # Yeniden açılan iş tekrar arıza sayılmaz (bağ yok).
    r = await client.get(f"{R}/tekrar-ariza", params=DONEM)
    no = {s["so_no"] for s in r.json()["satirlar"]}
    assert olay["so_no"] not in no


async def test_ekran_ile_excel_esit(client, db, altin):
    await giris(client, "mudur")
    ozet = (await client.get(f"{R}/ozet", params=DONEM)).json()
    r = await client.get(f"{R}/kitap.xlsx", params=DONEM)
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].endswith('servis-raporu-20260301-20260331.xlsx"')
    kitap = load_workbook(BytesIO(r.content))
    ws = kitap["Yönetim Özeti"]
    excel = {}
    for satir in ws.iter_rows(values_only=True):
        if satir and satir[0] and satir[1] is not None:
            excel[satir[0]] = satir[1]
    for k in ozet["kpiler"]:
        assert excel[k["baslik"]] == k["deger"], k["kod"]
    kisi_saat = next(o for o in ozet["olcumler"] if o["kod"] == "kisi_saat")["deger"]
    assert excel["Gerçek kişi-saat"] == kisi_saat == 9.0
    # Tipli veri tablosu: satır = detay toplamı; Excel Tablosu ref = veri + 1.
    veri = kitap["Veri_IsEmirleri"]
    assert veri.max_row - 1 == ozet["toplamlar"]["toplam"] == int(r.headers["X-Toplam-Kayit"])
    assert "Veri_IsEmirleri" in veri.tables
    assert veri.tables["Veri_IsEmirleri"].ref.endswith(str(veri.max_row))
    # Aylık özet Mart satırı kişi-saat = Yönetim Özeti.
    aylik = {s[0]: s for s in kitap["Aylık Özet"].iter_rows(min_row=2, values_only=True)}
    assert aylik["Mart 2026"][5] == 9.0
    assert aylik["Mart 2026"][1] == 27
    # Seri no metin olarak (sıfırlı ve 19 haneli) korunur.
    basliklar = [h.value for h in veri[1]]
    seri_sutun = basliklar.index("Seri No") + 1
    seriler = {
        veri.cell(row=i, column=seri_sutun).value: veri.cell(row=i, column=seri_sutun).data_type
        for i in range(2, veri.max_row + 1)
    }
    assert seriler["0012345"] == "s"
    assert seriler["1234567890123456789"] == "s"
    # Kişisel sayfalar yetkili kullanıcıda var.
    for ad in ("Personel KPI", "Süre Hareketleri", "Veri_Sureler"):
        assert ad in kitap.sheetnames
    # Denetim: tek satır, filtreler ISO, kişisel veri işaretli.
    kayitlar = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "servis_rapor.disaaktar"))
    ).all()
    assert len(kayitlar) == 1
    assert kayitlar[0].is_personal_data is True
    assert kayitlar[0].new_value["filtreler"]["baslangic"] == "2026-03-01"
    assert kayitlar[0].new_value["satir_sayisi"] == 27


async def test_seed_idempotent_ve_koruma(db, altin):
    seed, kisiler = altin
    is_sayisi = await db.scalar(select(func.count()).select_from(ServiceOrder))
    sure_sayisi = await db.scalar(select(func.count()).select_from(ServiceTimeEntry))
    await servis_rapor_seed.kur(db, kisiler)
    assert await db.scalar(select(func.count()).select_from(ServiceOrder)) == is_sayisi
    assert await db.scalar(select(func.count()).select_from(ServiceTimeEntry)) == sure_sayisi
    assert servis_rapor_seed._DB_KALIBI.search("dengeerp") is None
    assert servis_rapor_seed._DB_KALIBI.search("dengeerp_test")
    assert servis_rapor_seed._DB_KALIBI.search("dengeerp_test_a")
