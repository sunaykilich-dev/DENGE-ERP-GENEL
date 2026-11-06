"""FORA dosyasından cihaz–araç eşleştirmesi (tarihsiz).

Şema `8c41d2b7e903` ile tarihsiz döneme izin veriyor. Buradaki testler iki
şeyi çiviliyor: tarihsiz satır cihazın GERÇEK geçmişiyle çakışmıyor, ve
tarihli bir kayıt tarihsiz bir tahminle değiştirilmiyor.
"""

from datetime import UTC, datetime

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.migration.fora_cihaz_arac import oku, uygula
from app.models import DeviceVehicleAssignment, Vehicle

pytestmark = pytest.mark.integration

BASLIK = ["FirmName", "Plate", "DeviceNo", "Cihat tipi", "GsmNo"]


def _dosya(tmp_path, satirlar):
    wb = Workbook()
    ws = wb.active
    ws.append(BASLIK)
    for s in satirlar:
        ws.append(s)
    yol = tmp_path / "fora.xlsx"
    wb.save(yol)
    return yol


async def _arac(db, plaka: str) -> Vehicle:
    v = Vehicle(plate=plaka)
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


async def test_tarihsiz_donem_yazilir(tmp_path, db, cihaz_ac):
    cihaz = await cihaz_ac(imei="353201356899374")
    arac = await _arac(db, "34ABC123")
    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"]]
    )
    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()

    assert sayac["eslesme"] == 1
    kayit = await db.scalar(select(DeviceVehicleAssignment))
    assert kayit.device_id == cihaz.id
    assert kayit.vehicle_id == arac.id
    assert kayit.valid_from is None, "tarih uydurulmamalı"
    assert kayit.is_inferred is False, "tahmin değil; tarih HİÇ yok"


async def test_plakasi_cozulemeyen_satir_arac_acmaz(tmp_path, db, cihaz_ac):
    """'MONTAJDA' ve plaka yerine yazılmış IMEI sessizce araç üretmemeli."""
    await cihaz_ac(imei="353201356899374")
    await cihaz_ac(imei="353201356899382")
    yol = _dosya(
        tmp_path,
        [
            ["FİRMA A.Ş.", "MONTAJDA", "35320135689937419", "armoli", "5497117542"],
            ["FİRMA A.Ş.", "861100063757146", "35320135689938219", "armoli", "5497117543"],
        ],
    )
    sonuc = oku(yol)
    assert sonuc.karantina["plaka_cozulemedi"] == 2
    await uygula(db, sonuc, yaz=True)
    await db.commit()
    assert (await db.scalars(select(Vehicle))).all() == []
    assert (await db.scalars(select(DeviceVehicleAssignment))).all() == []


async def test_erpde_olmayan_plaka_icin_arac_acilmaz(tmp_path, db, cihaz_ac):
    await cihaz_ac(imei="353201356899374")
    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34XYZ999", "35320135689937419", "armoli", "5497117542"]]
    )
    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()
    assert sayac["arac_erpde_yok"] == 1
    assert (await db.scalars(select(Vehicle))).all() == []


async def test_mevcut_tarihli_donem_korunur(tmp_path, db, cihaz_ac):
    cihaz = await cihaz_ac(imei="353201356899374")
    eski = await _arac(db, "34ESKI01")
    await _arac(db, "34ABC123")
    db.add(
        DeviceVehicleAssignment(
            device_id=cihaz.id, vehicle_id=eski.id, valid_from=datetime(2025, 1, 1, tzinfo=UTC)
        )
    )
    await db.commit()

    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"]]
    )
    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()

    assert sayac["cihazin_zaten_araci_var"] == 1
    kayitlar = (await db.scalars(select(DeviceVehicleAssignment))).all()
    assert len(kayitlar) == 1
    assert kayitlar[0].vehicle_id == eski.id


async def test_ayni_imei_iki_plakada_ise_satir_alinmaz(tmp_path, db, cihaz_ac):
    """Bir cihaz aynı anda tek araçta olabilir; hangisi doğru bilinemez."""
    await cihaz_ac(imei="353201356899374")
    await _arac(db, "34ABC123")
    await _arac(db, "34ABC124")
    yol = _dosya(
        tmp_path,
        [
            ["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"],
            ["FİRMA A.Ş.", "34ABC124", "35320135689937419", "armoli", "5497117543"],
        ],
    )
    sonuc = oku(yol)
    assert sonuc.karantina["imei_birden_cok_plakada"] == 2
    await uygula(db, sonuc, yaz=True)
    await db.commit()
    assert (await db.scalars(select(DeviceVehicleAssignment))).all() == []


async def test_ikinci_kosuda_yeni_satir_yazilmaz(tmp_path, db, cihaz_ac):
    await cihaz_ac(imei="353201356899374")
    await _arac(db, "34ABC123")
    yol = _dosya(
        tmp_path, [["FİRMA A.Ş.", "34ABC123", "35320135689937419", "armoli", "5497117542"]]
    )
    await uygula(db, oku(yol), yaz=True)
    await db.commit()
    sayac = await uygula(db, oku(yol), yaz=True)
    await db.commit()
    assert sayac["cihazin_zaten_araci_var"] == 1
    assert len((await db.scalars(select(DeviceVehicleAssignment))).all()) == 1


async def test_tarihsiz_donem_gercek_gecmisle_cakismaz(db, cihaz_ac):
    """EXCLUDE kısmi: `tstzrange(NULL,NULL)` sonsuz aralık sayılsaydı,
    tarihsiz tek bir satır cihazın bütün geçmişini kilitlerdi."""
    cihaz = await cihaz_ac(imei="353201356899374")
    a1 = await _arac(db, "34AAA111")
    a2 = await _arac(db, "34BBB222")
    db.add(
        DeviceVehicleAssignment(
            device_id=cihaz.id,
            vehicle_id=a1.id,
            valid_from=datetime(2024, 1, 1, tzinfo=UTC),
            valid_to=datetime(2024, 6, 1, tzinfo=UTC),
        )
    )
    await db.commit()
    db.add(DeviceVehicleAssignment(device_id=cihaz.id, vehicle_id=a2.id, valid_from=None))
    await db.commit()
    assert len((await db.scalars(select(DeviceVehicleAssignment))).all()) == 2


async def test_ayni_cihazda_iki_acik_donem_reddedilir(db, cihaz_ac):
    """Tarihsiz satırlar EXCLUDE'un dışında; tekillik kısmi indeksle korunur."""
    cihaz = await cihaz_ac(imei="353201356899374")
    a1 = await _arac(db, "34AAA111")
    a2 = await _arac(db, "34BBB222")
    db.add(DeviceVehicleAssignment(device_id=cihaz.id, vehicle_id=a1.id, valid_from=None))
    await db.commit()
    db.add(DeviceVehicleAssignment(device_id=cihaz.id, vehicle_id=a2.id, valid_from=None))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_baslangici_bilinmeyen_donem_kapatilamaz(db, cihaz_ac):
    cihaz = await cihaz_ac(imei="353201356899374")
    arac = await _arac(db, "34AAA111")
    db.add(
        DeviceVehicleAssignment(
            device_id=cihaz.id,
            vehicle_id=arac.id,
            valid_from=None,
            valid_to=datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
