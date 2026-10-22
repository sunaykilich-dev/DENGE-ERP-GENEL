"""Planlı bakım raporları ve KPI'ları (TS-185: E12-12, E04-18, E04-19).

Kabul: dönem tamamlama satırı sayımı cihaz PB işlerinden, tarih plan
kapanışından (AKYAKA 17 cihaz → `%88,2 (15/17) — Açık`); 10 vadeli dönemin
7'si toleransla → %70, geciken 3; her KPI sayısı = açılan listenin
`X-Toplam-Kayit`'ı; başka birim sayıya girmez; para alanı yok; `bakim.gor`
yoksa 403; Excel `servis_rapor.disaaktar` ister ve denetime yazılır.
"""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO

import pytest
from bakim_yardimci import ONEK, giris
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import (
    AuditLog,
    MaintenanceContractItem,
    MaintenanceForm,
    MaintenanceNonconformity,
    MaintenancePeriod,
    MaintenanceVisit,
)
from app.services.teknik_servis import bakim_raporlari

pytestmark = pytest.mark.integration

RAPOR = f"{ONEK}/raporlar"
_AN = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def kisiler(birimli_kullanici_ac):
    return {
        "sef": await birimli_kullanici_ac("sef_r", "SERVIS_SEF", ["GUVENLIK"]),
        "sef_h": await birimli_kullanici_ac("sef_rh", "SERVIS_SEF", ["HABERLESME"]),
        "op": await birimli_kullanici_ac("op_r", "SERVIS_OPERASYON", ["GUVENLIK"]),
    }


async def _sozlesme(sozlesme_ac, birim="GUVENLIK"):
    return await sozlesme_ac(
        birim=birim,
        status="AKTIF",
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        valid_to=datetime(2027, 1, 1, tzinfo=UTC),
        annual_frequency=4,
    )


async def _donem(db, sozlesme, sira, hedef, *, kapanis=None, tur=None):
    d = MaintenancePeriod(
        contract_id=sozlesme.id,
        cycle_start=datetime(2025, 1, 1, tzinfo=UTC),
        sequence_no=sira,
        target_date=hedef,
        closed_at=kapanis,
        closing_kind=tur if kapanis else None,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


async def _pb(db, servis_isi_ac, sozlesme, donem, sira, durum, **kw):
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=sira)
    db.add(kalem)
    await db.commit()
    if durum == "IPTAL":
        kw.setdefault("cancel_reason", "Kapsam dışı onaylandı")
    if durum in ("TAMAMLANDI", "KAPATILDI"):
        kw.setdefault("completed_at", _AN)
    return await servis_isi_ac(
        birim=sozlesme.birim,
        tur="PB",
        durum=durum,
        contract_item_id=kalem.id,
        maintenance_period_id=donem.id,
        **kw,
    )


async def _form(db, so, *, uygunsuz=(), ziyaret=False):
    form = MaintenanceForm(
        service_order_id=so.id,
        template_code="XRAY",
        template_version=1,
        status="TAMAMLANDI",
        bakim_sonucu="UYGUNSUZLUK_VAR" if uygunsuz else "TAMAMLANDI",
        completed_at=_AN,
    )
    db.add(form)
    await db.flush()
    if ziyaret:
        db.add(
            MaintenanceVisit(
                form_id=form.id,
                service_order_id=so.id,
                visit_no=1,
                visited_at=_AN,
                tur="TAMAMLAMA",
            )
        )
    for kod in uygunsuz:
        db.add(
            MaintenanceNonconformity(
                form_id=form.id,
                service_order_id=so.id,
                check_code=kod,
                check_label=f"Madde {kod}",
                description="Uygunsuz",
            )
        )
    await db.commit()
    return form


async def test_akyaka_17_cihaz_satiri_ve_para_alani_yok(
    client, db, kisiler, sozlesme_ac, servis_isi_ac
):
    s = await _sozlesme(sozlesme_ac)
    d = await _donem(db, s, 1, date(2026, 3, 1))
    for i in range(1, 18):
        await _pb(db, servis_isi_ac, s, d, i, "TAMAMLANDI" if i <= 15 else "PLANLAMADA")
    await _pb(db, servis_isi_ac, s, d, 18, "IPTAL")  # iptal paydaya girmez

    await giris(client, "sef_r")
    r = await client.get(f"{RAPOR}/donem-tamamlama")
    assert r.status_code == 200, r.text
    [satir] = r.json()
    assert satir["oran_metni"] == "%88,2 (15/17) — Açık"
    assert (satir["pb_toplam"], satir["pb_tamamlanan"], satir["pb_iptal"]) == (17, 15, 1)
    assert satir["tamamlanma_tarihi"] is None
    for anahtar in ("fee_per_visit", "contract_total", "ucret", "tutar", "maliyet"):
        assert anahtar not in r.text

    # Tek fonksiyon: servis raporu / Excel aynı sonucu alır.
    rapor = await bakim_raporlari.donem_tamamlama(db, kisiler["sef"], client.clock)
    assert rapor["satirlar"][0]["oran_metni"] == satir["oran_metni"]

    # Kapanınca tarih plan kapanışından gelir.
    donem = await db.get(MaintenancePeriod, d.id)
    donem.closed_at = datetime(2026, 3, 5, 10, tzinfo=UTC)
    donem.closing_kind = "KISMI"
    await db.commit()
    [satir] = (await client.get(f"{RAPOR}/donem-tamamlama")).json()
    assert satir["durum"] == "Kısmi" and satir["tamamlanma_tarihi"] == "2026-03-05"


async def test_bakim_gor_yoksa_403(client, kisiler):
    await giris(client, "op_r")  # SERVIS_OPERASYON: bakim.gor yok
    for yol in ("donem-tamamlama", "pb-isleri", "uygunsuzluk", "bakim.xlsx"):
        assert (await client.get(f"{RAPOR}/{yol}")).status_code == 403
    assert (await client.get(f"{ONEK}/ozet")).status_code == 403


async def test_uyum_yuzde_70_geciken_3_sayi_liste(client, db, kisiler, sozlesme_ac):
    s = await _sozlesme(sozlesme_ac)
    client.clock.set(datetime(2026, 6, 1, 9, tzinfo=UTC))
    for i in range(1, 11):
        hedef = date(2026, 1, 1) + timedelta(days=7 * i)
        kapanis = (
            datetime.combine(hedef + timedelta(days=10), datetime.min.time(), tzinfo=UTC)
            if i <= 7
            else None
        )
        await _donem(db, s, i, hedef, kapanis=kapanis, tur="TAMAMLANDI")
    await _donem(db, s, 11, date(2026, 7, 1))  # vadesi gelmemiş → paydada yok

    await giris(client, "sef_r")
    kutular = {k["kod"]: k for k in (await client.get(f"{ONEK}/ozet")).json()["kutular"]}
    uyum = kutular["UYUM_ORANI"]
    assert uyum["deger"] == 70.0 and (uyum["pay"], uyum["payda"]) == (7, 10)
    r = await client.get(f"{RAPOR}/donem-tamamlama", params={"kpi": "UYUM_ORANI"})
    assert int(r.headers["X-Toplam-Kayit"]) == uyum["payda"]
    assert sum(1 for x in r.json() if x["uyumlu"]) == 7
    r = await client.get(f"{ONEK}/donemler", params={"gecikmis": "true"})
    assert kutular["GECIKEN_DONEM"]["deger"] == int(r.headers["X-Toplam-Kayit"]) == 3

    # Başka birimin şefi bu sözleşmeyi saymaz.
    await giris(client, "sef_rh")
    kutular = {k["kod"]: k for k in (await client.get(f"{ONEK}/ozet")).json()["kutular"]}
    assert kutular["UYUM_ORANI"]["deger"] is None and kutular["GECIKEN_DONEM"]["deger"] == 0


async def test_pb_kpi_sayisi_liste_toplamina_esit_ve_kapsamli(
    client, db, kisiler, sozlesme_ac, servis_isi_ac
):
    s = await _sozlesme(sozlesme_ac)
    d = await _donem(db, s, 1, date(2026, 2, 1))
    acik = await _pb(db, servis_isi_ac, s, d, 1, "PLANLAMADA")
    await _pb(db, servis_isi_ac, s, d, 2, "TAMAMLANDI")  # süre yok + onaysız
    bekleyen = await _pb(db, servis_isi_ac, s, d, 3, "BEKLEMEDE")
    await _form(db, bekleyen, uygunsuz=("XR_BELT",), ziyaret=True)
    # Başka birim: sayılara girmemeli.
    sh = await _sozlesme(sozlesme_ac, "HABERLESME")
    dh = await _donem(db, sh, 1, date(2026, 2, 1))
    await _pb(db, servis_isi_ac, sh, dh, 1, "TAMAMLANDI")
    await _pb(db, servis_isi_ac, sh, dh, 2, "PLANLAMADA")

    await giris(client, "sef_r")
    kutular = {k["kod"]: k for k in (await client.get(f"{ONEK}/ozet")).json()["kutular"]}
    beklenen = {
        "ACIK_PB": 2,  # PLANLAMADA + BEKLEMEDE
        "TAMAMLANAN_PB": 1,
        "SURE_EKSIK_PB": 1,
        "ONAYSIZ_KAPANIS": 1,
        "BAKIM_YAPILDI_AKSIYON_ACIK": 1,
    }
    for kod, deger in beklenen.items():
        r = await client.get(f"{RAPOR}/pb-isleri", params={"kpi": kod})
        assert r.status_code == 200, r.text
        assert kutular[kod]["deger"] == int(r.headers["X-Toplam-Kayit"]) == deger, kod
    # Süre kaydı yok: "eksik" (null), 0 değil.
    r = await client.get(f"{RAPOR}/pb-isleri", params={"kpi": "SURE_EKSIK_PB"})
    assert r.json()[0]["kisi_saat_dk"] is None
    oran = kutular["UYGUNSUZLUK_ORANI"]
    r = await client.get(f"{RAPOR}/pb-isleri", params={"kpi": "UYGUNSUZLUK_ORANI"})
    assert (oran["pay"], oran["payda"], oran["deger"]) == (1, 1, 100.0)
    assert int(r.headers["X-Toplam-Kayit"]) == oran["payda"]
    r = await client.get(f"{ONEK}/uygunsuzluklar", params={"durum": "ACIK"})
    assert kutular["ACIK_UYGUNSUZLUK"]["deger"] == int(r.headers["X-Toplam-Kayit"]) == 1
    assert acik.id in {x["so_id"] for x in (await client.get(f"{RAPOR}/pb-isleri")).json()}

    await giris(client, "sef_rh")
    kutular = {k["kod"]: k for k in (await client.get(f"{ONEK}/ozet")).json()["kutular"]}
    assert kutular["ACIK_PB"]["deger"] == 1 and kutular["TAMAMLANAN_PB"]["deger"] == 1
    assert kutular["BAKIM_YAPILDI_AKSIYON_ACIK"]["deger"] == 0


async def test_motor_kaydi_isler_listesiyle_ayni_sayi(
    client, db, kisiler, sozlesme_ac, servis_isi_ac
):
    """D3-A rapor motoru kaydı: `/isler?kpi=rapor_bakim_*&donem=` sayısı =
    bakım raporu PB listesinin aynı süzgeci (ikinci tanım yok)."""
    from app.services.teknik_servis import panel

    assert "rapor_bakim_tamamlanan_pb" in panel.KPI_TANIMLARI
    assert panel.KPI_TANIMLARI["rapor_bakim_tamamlanan_pb"].izin == "bakim.gor"
    s = await _sozlesme(sozlesme_ac)
    d = await _donem(db, s, 1, date(2026, 2, 1))
    await _pb(db, servis_isi_ac, s, d, 1, "TAMAMLANDI")
    await _pb(db, servis_isi_ac, s, d, 2, "PLANLAMADA")
    d2 = await _donem(db, s, 2, date(2026, 5, 1))
    await _pb(db, servis_isi_ac, s, d2, 3, "TAMAMLANDI")

    await giris(client, "sef_r")
    r = await client.get(
        "/api/teknik-servis/isler",
        params={"kpi": "rapor_bakim_tamamlanan_pb", "donem": "20260101-20260331"},
    )
    assert r.status_code == 200, r.text
    rapor = await client.get(
        f"{RAPOR}/pb-isleri",
        params={"kpi": "TAMAMLANAN_PB", "baslangic": "2026-01-01", "bitis": "2026-03-31"},
    )
    assert int(r.headers["X-Toplam-Kayit"]) == int(rapor.headers["X-Toplam-Kayit"]) == 1


async def test_parametre_dogrulama_400_403(client, kisiler):
    await giris(client, "sef_r")
    yol = f"{RAPOR}/donem-tamamlama"
    r = await client.get(yol, params={"baslangic": "2026-05-01", "bitis": "2026-01-01"})
    assert r.status_code == 400
    r = await client.get(yol, params={"baslangic": "2024-01-01", "bitis": "2026-02-01"})
    assert r.status_code == 400  # 25 ay
    assert (await client.get(yol, params={"birim": "XYZ"})).status_code == 400
    assert (await client.get(yol, params={"birim": "HABERLESME"})).status_code == 403
    assert (await client.get(yol, params={"kpi": "ACIK_PB"})).status_code == 400
    r = await client.get(f"{RAPOR}/pb-isleri", params={"kpi": "YOK_BOYLE"})
    assert r.status_code == 400


async def test_uygunsuzluk_analizi_en_sik_ve_yas(client, db, kisiler, sozlesme_ac, servis_isi_ac):
    s = await _sozlesme(sozlesme_ac)
    d = await _donem(db, s, 1, date(2026, 2, 1))
    for i, kodlar in enumerate((("A", "B"), ("A",), ("A", "C")), start=1):
        so = await _pb(db, servis_isi_ac, s, d, i, "BEKLEMEDE")
        await _form(db, so, uygunsuz=kodlar)
    client.clock.set(datetime.now(UTC) + timedelta(days=10))
    await giris(client, "sef_r")
    r = await client.get(f"{RAPOR}/uygunsuzluk")
    assert r.status_code == 200, r.text
    veri = r.json()
    assert [x["check_code"] for x in veri["en_sik"]][:1] == ["A"]
    assert veri["en_sik"][0]["adet"] == 3
    yas = veri["aksiyon_yasi"]
    assert yas["adet"] == 5 and yas["ortalama_gun"] is not None
    assert sum(k["adet"] for k in yas["kovalar"]) == 5


async def test_excel_izin_denetim_ve_sayfalar(
    client, db, kisiler, kullanici_ac, sozlesme_ac, servis_isi_ac
):
    s = await _sozlesme(sozlesme_ac)
    d = await _donem(db, s, 1, date(2026, 3, 1))
    await _pb(db, servis_isi_ac, s, d, 1, "TAMAMLANDI")
    await kullanici_ac("yonetim_r", "YONETIM")  # bakim.gor var, disaaktar yok
    await giris(client, "yonetim_r")
    assert (await client.get(f"{RAPOR}/bakim.xlsx")).status_code == 403

    await giris(client, "sef_r")
    r = await client.get(f"{RAPOR}/bakim.xlsx", params={"baslangic": "2026-01-01"})
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames[:2] == ["Dönem Tamamlama", "Geciken Dönemler"]
    ws = wb["Dönem Tamamlama"]
    basliklar = [h.value for h in ws[1]]
    assert not any("cret" in str(b) or "Tutar" in str(b) for b in basliklar)
    assert ws.max_row == 2 and ws.cell(row=2, column=1).value == s.contract_no
    kayit = await db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "servis_rapor.disaaktar", AuditLog.entity == "servis_rapor")
        .order_by(AuditLog.id.desc())
    )
    assert kayit is not None and kayit.new_value["rapor"] == "bakim"
    assert kayit.new_value["filtreler"]["baslangic"] == "2026-01-01"
    assert not kayit.is_personal_data
