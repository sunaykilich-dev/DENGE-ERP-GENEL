"""FORA dosyasından cihaz–SIM eşleştirmesi.

Dosyanın üç tuzağı test edilir, çünkü üçü de sessizce yanlış sonuç üretirdi:
17 haneli IMEISV (ham değerle hiçbir cihaz bulunamaz), bozuk düzenli sıfır
IMEI satırları ve aynı numaranın birden çok cihazda görünmesi.
"""

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.migration.fora_cihaz_hat import oku, uygula
from app.models import SimCard, SimDeviceHistory

pytestmark = pytest.mark.integration

BASLIK = ["FirmName", "Plate", "DeviceNo", "Cihat tipi", "GsmNo"]


def _dosya(tmp_path, satirlar, *, pivot_once=False):
    wb = Workbook()
    if pivot_once:
        # Gerçek dosyada veri sayfası ÜÇÜNCÜ sırada; betik başlığa bakmalı.
        onc = wb.active
        onc.title = "Sayfa2"
        onc.append(["Satır Etiketleri", "armoli", "Genel Toplam"])
        ws = wb.create_sheet("Sayfa1")
    else:
        ws = wb.active
    ws.append(BASLIK)
    for s in satirlar:
        ws.append(s)
    yol = tmp_path / "fora.xlsx"
    wb.save(yol)
    return yol


async def test_imeisv_son_iki_hane_atilir(tmp_path, db, cihaz_ac):
    """DeviceNo 17 hane; IMEI ilk 15'tir. Ham değerle arama hiçbir şey bulmaz."""
    cihaz = await cihaz_ac(imei="353201356899374")
    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "teltonika", "5497117542"]]
    )
    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()

    assert sayac["eslesme"] == 1
    assert sayac.get("cihaz_erpde_yok", 0) == 0
    kayit = await db.scalar(select(SimDeviceHistory).where(SimDeviceHistory.device_id == cihaz.id))
    assert kayit is not None
    assert kayit.valid_from is None, "tarih uydurulmamalı"


async def test_olmayan_numara_icin_hat_acilir(tmp_path, db, cihaz_ac):
    """ICCID bilinmiyor; sistemdeki 6.501 hattın kullandığı yer tutucu yazılır."""
    await cihaz_ac(imei="353201356899374")
    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "teltonika", "5497117542"]]
    )
    await uygula(db, oku(yol), yaz=True)
    await db.commit()

    hat = await db.scalar(select(SimCard).where(SimCard.msisdn == "+905497117542"))
    assert hat is not None
    assert hat.iccid == "MSISDN:+905497117542"
    assert hat.field_sources["iccid"] == "EKSIK"
    assert hat.field_sources["operator"] == "VARSAYILAN"
    # Cihazın içinde takılı: depoda değil.
    assert hat.status == "AKTIF"


async def test_mevcut_hat_yeniden_acilmaz(tmp_path, db, cihaz_ac):
    await cihaz_ac(imei="353201356899374")
    db.add(
        SimCard(
            iccid="8990011234500000001",
            msisdn="+905497117542",
            status="AKTIF",
            operator="TURK_TELEKOM",
        )
    )
    await db.commit()

    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "teltonika", "5497117542"]]
    )
    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()

    assert sayac["mevcut_hat"] == 1
    assert sayac.get("yeni_hat", 0) == 0
    hatlar = (await db.scalars(select(SimCard).where(SimCard.msisdn == "+905497117542"))).all()
    assert len(hatlar) == 1, "aynı fiziksel SIM ikinci kez açılmamalı"


async def test_sifir_imei_satirlari_karantinaya(tmp_path, db):
    """Düzeni bozuk satır: plaka alanında IMEI, firma alanında 'DENGEMOBİL TEST'."""
    yol = _dosya(
        tmp_path,
        [
            ["DENGEMOBİL TEST", "MONTAJDA", "00000000000000003", "armoli", "0"],
            ["DENGEMOBİL TEST", "353201356899374", "00000000000000001", "armoli", "0"],
        ],
    )
    sonuc = oku(yol)
    assert sonuc.karantina["imei_gecersiz"] == 2
    assert sonuc.satirlar == []


async def test_ayni_numara_iki_cihazda_ise_satir_alinmaz(tmp_path, db, cihaz_ac):
    """Bir numara aynı anda iki SIM'de olamaz; hangisi doğru bilinemez."""
    await cihaz_ac(imei="353201356899374")
    await cihaz_ac(imei="353201356899382")
    yol = _dosya(
        tmp_path,
        [
            ["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"],
            ["FİRMA A.Ş.", "34ABC124", "35320135689938219", "armoli", "5497117542"],
        ],
    )
    sonuc = oku(yol)
    assert sonuc.karantina["numara_birden_cok_cihazda"] == 2
    sayac = await uygula(db, sonuc, yaz=True)
    await db.commit()
    assert sayac.get("eslesme", 0) == 0
    assert (await db.scalars(select(SimDeviceHistory))).all() == []


async def test_yer_tutucu_numara_yazilmaz(tmp_path, db, cihaz_ac):
    await cihaz_ac(imei="353201356899374")
    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "05555555555"]]
    )
    sonuc = oku(yol)
    assert sonuc.karantina["numara_yer_tutucu"] == 1
    sayac = await uygula(db, sonuc, yaz=True)
    await db.commit()
    assert sayac["numarasiz_satir"] == 1
    assert (await db.scalars(select(SimCard))).all() == []


async def test_mevcut_eslesmenin_uzerine_yazilmaz(tmp_path, db, cihaz_ac):
    """Tarihli gerçek kayıt, tarihsiz bir tahminle değiştirilmez."""
    from datetime import UTC, datetime

    cihaz = await cihaz_ac(imei="353201356899374")
    eski = SimCard(
        iccid="8990011234500000002", msisdn="+905550001111", status="AKTIF", operator="TURK_TELEKOM"
    )
    db.add(eski)
    await db.flush()
    db.add(
        SimDeviceHistory(
            sim_id=eski.id, device_id=cihaz.id, valid_from=datetime(2025, 1, 1, tzinfo=UTC)
        )
    )
    await db.commit()

    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"]]
    )
    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()

    assert sayac["cihazin_zaten_hatti_var"] == 1
    kayitlar = (
        await db.scalars(select(SimDeviceHistory).where(SimDeviceHistory.device_id == cihaz.id))
    ).all()
    assert len(kayitlar) == 1
    assert kayitlar[0].sim_id == eski.id


async def test_ayni_dosya_ikinci_kez_kosarsa_yeni_satir_yazmaz(tmp_path, db, cihaz_ac):
    await cihaz_ac(imei="353201356899374")
    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"]]
    )
    await uygula(db, oku(yol), yaz=True)
    await db.commit()
    ilk = len((await db.scalars(select(SimDeviceHistory))).all())

    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()
    assert sayac["cihazin_zaten_hatti_var"] == 1
    assert len((await db.scalars(select(SimDeviceHistory))).all()) == ilk


async def test_veri_sayfasi_basliktan_bulunur(tmp_path, db, cihaz_ac):
    """Dosyada pivot sayfaları önce geliyor; ilk sayfa veri sayfası DEĞİL."""
    await cihaz_ac(imei="353201356899374")
    yol = _dosya(
        tmp_path,
        [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"]],
        pivot_once=True,
    )
    sonuc = oku(yol)
    assert len(sonuc.satirlar) == 1
