"""Cihaz kimlik politikası — veritabanı seviyesinde zorlanır.

Kural kullanıcının kendi ifadesiyle: "IMEI kesinlikle zorunlu olmalı, cihazların
takibini IMEI olmadan yapamayız." Gerçek veri bir istisna gösterdi: Dahua
HMW3200LP ve HAC serisi analog kameraların modemi yok, 898 montaj satırının
898'inde IMEI boş. Çözüm kuralı gevşetmek değil, ÜRÜNE bağlamak oldu.

Bu testler kuralın serviste değil ŞEMADA yaşadığını kanıtlar: hatalı bir uç,
elle yazılmış SQL ya da göç betiği bile IMEI'siz takip cihazı kaydedemez.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Device

pytestmark = pytest.mark.integration


async def test_imei_urununde_imeisiz_kayit_reddedilir(db, urun_ac):
    urun = await urun_ac("L300", "IMEI")
    db.add(Device(product_id=urun.id, identity_kind="IMEI", imei=None))
    with pytest.raises(IntegrityError, match="ck_devices_kimlik_zorunlu"):
        await db.commit()


async def test_seri_no_urununde_seri_nosuz_kayit_reddedilir(db, urun_ac):
    urun = await urun_ac("DAHUA-HMW3200LP", "SERI_NO", requires_parent=True)
    db.add(Device(product_id=urun.id, identity_kind="SERI_NO", serial_no=None))
    with pytest.raises(IntegrityError, match="ck_devices_kimlik_zorunlu"):
        await db.commit()


async def test_ek_kamera_seri_no_ile_kaydedilir(db, urun_ac, cihaz_ac):
    """898 IMEI'siz kamera sisteme böyle girer."""
    urun = await urun_ac("DAHUA-HMW3200LP", "SERI_NO", requires_parent=True)
    kamera = await cihaz_ac(serial_no="BB06882PAG00032", urun=urun)
    assert kamera.imei is None
    assert kamera.kimlik == "BB06882PAG00032"


async def test_cihazin_kimlik_tipi_urununkinden_sapamaz(db, urun_ac):
    """Bileşik yabancı anahtar: cihaz 'ben IMEI'liyim' diyemez, ürünü öyle
    demiyorsa. Aksi halde uygulama hatası şemayı delerdi."""
    urun = await urun_ac("DAHUA-HMW3200LP", "SERI_NO", requires_parent=True)
    db.add(Device(product_id=urun.id, identity_kind="IMEI", imei="111111111111111"))
    with pytest.raises(IntegrityError, match="fk_devices_urun_kimlik"):
        await db.commit()


async def test_ayni_imei_iki_cihaza_verilemez(db, cihaz_ac):
    await cihaz_ac(imei="861100063834630")
    with pytest.raises(IntegrityError, match="uq_devices_imei"):
        await cihaz_ac(imei="861100063834630")


async def test_bos_imei_tekillik_kisitini_tetiklemez(db, urun_ac, cihaz_ac):
    """Kısmi indeks: IMEI'si olmayan ek kameralar birbirini engellemez —
    tam indeks olsaydı ikinci kamera kaydedilemezdi."""
    urun = await urun_ac("DAHUA-HMW3200LP", "SERI_NO", requires_parent=True)
    await cihaz_ac(serial_no="BB06882PAG00032", urun=urun)
    await cihaz_ac(serial_no="BB06882PAG00033", urun=urun)
    from sqlalchemy import func, select

    adet = await db.scalar(select(func.count()).select_from(Device))
    assert adet == 2


async def test_ana_cihaz_kanal_iliskisi(db, urun_ac, cihaz_ac):
    """Ek kamera ana cihazın kanalına bağlanır — 'aracın arka kamerası
    arızalı' kaydı bu sayede tutulabilir."""
    dashcam_urun = await urun_ac("DAHUA-CDR8213", "IMEI", channel_count=2)
    kamera_urun = await urun_ac("DAHUA-HMW3200LP", "SERI_NO", requires_parent=True)

    dashcam = await cihaz_ac(imei="861100063834630", urun=dashcam_urun, device_role="KAMERA")
    kamera = await cihaz_ac(
        serial_no="BB06882PAG00032",
        urun=kamera_urun,
        parent_device_id=dashcam.id,
        channel_no=2,
        device_role="YARDIMCI_KAMERA",
    )
    assert kamera.parent_device_id == dashcam.id
    assert kamera.channel_no == 2


async def test_cihaz_kendi_ebeveyni_olamaz(db, cihaz_ac):
    cihaz = await cihaz_ac(imei="861100063834630")
    cihaz.parent_device_id = cihaz.id
    with pytest.raises(IntegrityError, match="ck_devices_kendi_ebeveyni_olamaz"):
        await db.commit()
