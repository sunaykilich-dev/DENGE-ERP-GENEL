"""Servis raporları yetki ve kişisel veri (TS-182, E12-09).

- 403/200 matrisi: SERVIS_TEKNISYEN (servis_rapor.gor yok) ve SATIS (servis.gor
  yok) 403; YONETIM ekranı görür ama kişi kırılımı ve Excel 403; SERVIS_SEF ve
  SERVIS_YONETICI 200.
- `servis_rapor.personel` yoksa kişi kırılımı/ham süre/iletişim anahtarları
  yanıtta ve Excel'de HİÇ yoktur (boş değer değil).
- Para alanı hiçbir rapor yanıtında anahtar olarak yoktur.
- Her Excel indirmesi tek denetim satırı; kişisel sayfa varsa
  `is_personal_data=True`, filtreler ISO.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from openpyxl import load_workbook
from servis_rapor_ortam import DONEM, R, anahtarlar, giris, kullanicilar, para_anahtari_var
from sqlalchemy import select

from app.models import AuditLog, ServiceResult, ServiceTimeEntry
from app.services.teknik_servis import rapor_tanimlari as rt

pytestmark = pytest.mark.integration

AN = datetime(2026, 3, 10, 8, 0, tzinfo=UTC)
JSON_UCLARI = (
    "/tanimlar",
    "/ozet",
    "/kirilim",
    "/sla",
    "/tekrar-ariza",
    "/yeniden-acilan",
    "/trend",
)


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac, rol_ac, servis_isi_ac, lokasyon_ac):
    k = await kullanicilar(db, kullanici_ac, birimli_kullanici_ac)
    # Excel izni olan ama kişisel izni olmayan rol (SERVIS_YONETICI kopyası gibi).
    await rol_ac(
        "T_RAPOR_KISISELSIZ",
        ["servis.gor", "servis_rapor.gor", "servis_rapor.disaaktar"],
        "TUMU",
    )
    await kullanici_ac("aktarici", "T_RAPOR_KISISELSIZ")
    tesis = await lokasyon_ac(il="Ankara")
    so = await servis_isi_ac(
        durum="TAMAMLANDI",
        lokasyon=tesis,
        musteri=None,
        atananlar=[k["tek1"]],
        created_at=AN,
        completed_at=AN.replace(hour=12),
        first_completed_at=AN.replace(hour=12),
        iletisim_ad="Saha Yetkilisi",
        iletisim_telefon="+905321112233",
    )
    db.add(
        ServiceResult(
            service_order_id=so.id, sonuc="COZULDU", cozum_kanali="YERINDE", yapilan_islem="Tamam"
        )
    )
    db.add(
        ServiceTimeEntry(
            service_order_id=so.id,
            user_id=k["tek1"].id,
            faaliyet="SAHA",
            started_at=AN,
            ended_at=AN.replace(hour=10),
            kaynak="MANUEL",
            girildi_at=AN,
            konum_notu="Kat 3 kapı",
            aciklama="Teknisyen notu",
        )
    )
    await db.commit()
    return k, so


@pytest.mark.parametrize(
    ("kullanici", "uc", "beklenen"),
    [
        ("tek1", "/ozet", 403),
        ("satis", "/ozet", 403),
        ("yonetim", "/ozet", 200),
        ("yonetim", "/kisi-saat", 403),
        ("yonetim", "/sure-hareketleri", 403),
        ("yonetim", "/kitap.xlsx", 403),
        ("sef_g", "/ozet", 200),
        ("sef_g", "/kisi-saat", 200),
        ("sef_g", "/kitap.xlsx", 200),
        ("mudur", "/sure-hareketleri", 200),
        ("mudur", "/kpi-liste?kpi=rapor_gelen", 200),
        ("tek1", "/kpi-liste?kpi=rapor_gelen", 403),
    ],
)
async def test_yetki_matrisi(client, ortam, kullanici, uc, beklenen):
    await giris(client, kullanici)
    r = await _al(client, uc)
    assert r.status_code == beklenen, r.text


async def _al(client, uc: str, **ek):
    """`?kpi=` gibi uç sorgusunu dönem parametreleriyle birleştirir (httpx
    `params` URL'deki sorguyu ezer)."""
    yol, _, sorgu = uc.partition("?")
    params = {**DONEM, **ek}
    if sorgu:
        params.update(dict(p.split("=", 1) for p in sorgu.split("&")))
    return await client.get(f"{R}{yol}", params=params)


async def test_kisisel_anahtar_izinsizde_yok(client, ortam):
    """YONETIM (servis_rapor.personel yok): kişisel anahtar ve teknisyen boyutu yok."""
    await giris(client, "yonetim")
    for uc in JSON_UCLARI:
        r = await client.get(f"{R}{uc}", params=DONEM)
        assert r.status_code == 200, (uc, r.text)
        assert not (anahtarlar(r.json()) & rt.kisisel_anahtarlar()), uc
    r = await client.get(f"{R}/kirilim", params={**DONEM, "boyut": "teknisyen"})
    assert r.status_code == 403
    r = await client.get(f"{R}/ozet", params={**DONEM, "teknisyen_id": 1})
    assert r.status_code == 403
    r = await client.get(f"{R}/tanimlar")
    assert "teknisyen" not in {b["kod"] for b in r.json()["boyutlar"]}
    r = await client.get(f"{R}/kpi-liste", params={**DONEM, "kpi": "rapor_gelen"})
    assert not (
        anahtarlar(r.json()) & (rt.kisisel_anahtarlar() | {"iletisim_ad", "iletisim_telefon"})
    )


async def test_para_anahtari_hicbir_yanitta_yok(client, ortam):
    for kullanici in ("mudur", "yonetim"):
        await giris(client, kullanici)
        for uc in (*JSON_UCLARI, "/kpi-liste?kpi=rapor_cozulen"):
            r = await _al(client, uc)
            assert r.status_code == 200, (uc, r.text)
            assert para_anahtari_var(r.json()) == [], uc


async def test_excel_kisisel_sayfa_ve_denetim(client, db, ortam):
    # Kişisel izinsiz aktarıcı: kişisel sayfa/sütun YOK, denetim kişisel değil.
    await giris(client, "aktarici")
    r = await client.get(f"{R}/kitap.xlsx", params=DONEM)
    assert r.status_code == 200, r.text
    kitap = load_workbook(BytesIO(r.content))
    for ad in ("Personel KPI", "Süre Hareketleri", "Veri_Sureler"):
        assert ad not in kitap.sheetnames
    basliklar = [h.value for h in kitap["Günlük Servis"][1]]
    assert "Saha Telefonu" not in basliklar and "Saha Yetkilisi" not in basliklar
    # Kişisel izinli yönetici: sayfalar ve iletişim sütunu var; telefon METİN.
    await giris(client, "mudur")
    r = await client.get(f"{R}/kitap.xlsx", params=DONEM)
    kitap = load_workbook(BytesIO(r.content))
    assert {"Personel KPI", "Süre Hareketleri", "Veri_Sureler"} <= set(kitap.sheetnames)
    ws = kitap["Günlük Servis"]
    basliklar = [h.value for h in ws[1]]
    tel = ws.cell(row=2, column=basliklar.index("Saha Telefonu") + 1)
    assert tel.value == "+905321112233" and tel.data_type == "s"
    sure = kitap["Süre Hareketleri"]
    sb = [h.value for h in sure[1]]
    assert sure.cell(row=2, column=sb.index("Konum Notu") + 1).value == "Kat 3 kapı"
    kayitlar = (
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "servis_rapor.disaaktar")
            .order_by(AuditLog.id)
        )
    ).all()
    assert [k.is_personal_data for k in kayitlar] == [False, True]
    assert kayitlar[0].new_value["kisisel_sayfalar"] == []
    assert kayitlar[1].new_value["filtreler"]["bitis"] == "2026-03-31"
    assert kayitlar[1].entity == "servis_rapor"


async def test_sure_hareketleri_sayfali_ve_sinirli(client, ortam):
    await giris(client, "mudur")
    r = await client.get(f"{R}/sure-hareketleri", params={**DONEM, "limit": 1})
    assert r.status_code == 200, r.text
    assert int(r.headers["X-Toplam-Kayit"]) == 1
    assert r.json()[0]["konum_notu"] == "Kat 3 kapı"
    r = await client.get(f"{R}/sure-hareketleri", params={**DONEM, "limit": 201})
    assert r.status_code == 422  # hiçbir JSON uç 200'den fazla ham satır dönmez
