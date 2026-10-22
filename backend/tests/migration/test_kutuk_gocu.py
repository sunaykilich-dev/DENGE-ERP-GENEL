"""Ekipman kütüğü göçü (TS-172; E03-04, E03-10).

Kabul: `ON CONFLICT DO NOTHING (uq_svceq_kaynak)` — ikinci koşu satır sayısını
değiştirmez ve ekrandan yapılmış düzeltmeyi (seri no, pasif, durum) EZMEZ;
teslim tarihi metinden DATE; mükerrer seriler AKTİF kalır ve veri kalitesi
uyarısına düşer; karantina raporu eşleşmeyen müşteri / seri no'suz / geçersiz
tarih adetlerini verir.
"""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.migration import yukle_kutuk
from app.migration.servis_kaynak import GOC_SISTEMI, KaynakDizini
from app.models import AuditLog, ServiceEquipment
from tests.migration.goc_ortami import FIXTURE, goc_ortami

pytestmark = pytest.mark.integration


async def _kos(db):
    sonuc = await yukle_kutuk.hazirla(db, KaynakDizini(FIXTURE))
    await yukle_kutuk.yukle(db, sonuc)
    await db.commit()
    return sonuc


async def _sayi(db) -> int:
    return int(await db.scalar(select(func.count()).select_from(ServiceEquipment)) or 0)


async def test_ilk_yukleme_kurallari(seeded):
    db = seeded
    ort = await goc_ortami(db)
    sonuc = await _kos(db)
    assert sonuc.yeni == 5 and len(sonuc.reddedilen) == 1 and sonuc.tutarli
    assert await _sayi(db) == 5

    satirlar = {
        e.source_ref: e
        for e in (
            await db.scalars(
                select(ServiceEquipment).where(ServiceEquipment.source_system == GOC_SISTEMI)
            )
        ).all()
    }
    xray = satirlar["SecurityDevices:1"]
    assert xray.equipment_type == "XRAY"
    assert xray.delivery_date == date(2020, 9, 9) and xray.delivery_date_raw == "44083"
    assert xray.serial_no == "00123-A" and xray.serial_key == "00123-A"
    assert xray.account_id == ort.akyaka.id
    assert xray.model_key == "hiscan6040"  # "HI-SCAN 6040" ile "HISCAN 6040" aynı model

    # Mükerrer seri: iki satır da aktif yüklenir (veri kalitesine düşer).
    mukerrer = [e for e in satirlar.values() if e.serial_key == "KD-777"]
    assert len(mukerrer) == 2 and all(e.is_active for e in mukerrer)
    assert satirlar["SecurityDevices:3"].address_id == ort.depo.id
    # Okunamayan tarih uydurulmaz, ham metin korunur.
    assert satirlar["SecurityDevices:4"].delivery_date is None
    assert satirlar["SecurityDevices:4"].delivery_date_raw == "00.00.2015"
    # Eşleşmeyen müşteri: bağ yok, ham metin var.
    hurda = satirlar["SecurityDevices:5"]
    assert hurda.account_id is None and hurda.customer_name_raw == "Bilinmeyen Müşteri Ltd"
    assert hurda.is_active is False and hurda.lifecycle_status == "HURDA"

    uyarilar = sonuc.uyari_sayilari()
    assert uyarilar["MUSTERI_ESLESMEDI"] == 1
    assert uyarilar["SERISIZ"] == 1
    assert uyarilar["TESLIM_TARIHI_OKUNAMADI"] == 2
    assert await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "goc.kutuk")
    )


async def test_ikinci_kosu_sifir_yeni_ve_ekran_duzeltmesi_korunur(seeded):
    db = seeded
    await goc_ortami(db)
    await _kos(db)
    ekipman = await db.scalar(
        select(ServiceEquipment).where(ServiceEquipment.source_ref == "SecurityDevices:2")
    )
    ekipman.serial_no = "KD-777-DUZELTILDI"
    ekipman.is_active = False
    ekipman.lifecycle_status = "DEVRE_DISI"
    await db.commit()

    onizleme = await yukle_kutuk.hazirla(db, KaynakDizini(FIXTURE))
    assert onizleme.yeni == 0 and onizleme.mevcut == 5
    ikinci = await _kos(db)
    assert ikinci.yeni == 0
    assert await _sayi(db) == 5
    await db.refresh(ekipman)
    assert ekipman.serial_no == "KD-777-DUZELTILDI"
    assert ekipman.is_active is False and ekipman.lifecycle_status == "DEVRE_DISI"
