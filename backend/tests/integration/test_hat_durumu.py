"""Cihazda takılı olduğu hâlde 'STOKTA' görünen hatların düzeltilmesi.

İçe aktarma, cihazın İÇİNDE takılı bir hattı veritabanı varsayılanıyla
"STOKTA" bırakabiliyordu (`cihaz_sim_iccid` göçü durum yazmıyordu; 2.413 hat
böyle kalmıştı). Depoda olmadığı kanıtlı bir hattı stokta göstermek,
"kaç boş hattımız var" sorusunu doğrudan yanlışlar.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import SimCard, SimDeviceHistory
from app.yonetim import hat_durumu_duzelt

pytestmark = pytest.mark.integration


async def _hat(db, iccid: str, durum: str) -> SimCard:
    h = SimCard(iccid=iccid, msisdn=None, status=durum, operator="TURK_TELEKOM")
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def test_cihazda_takili_stokta_hat_aktife_cekilir(db, cihaz_ac):
    cihaz = await cihaz_ac(imei="111111111111111")
    hat = await _hat(db, "8990011234500000001", "STOKTA")
    db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
    await db.commit()

    assert await hat_durumu_duzelt(db, yaz=True) == 1
    await db.refresh(hat)
    assert hat.status == "AKTIF"


async def test_onizleme_hicbir_sey_yazmaz(db, cihaz_ac):
    cihaz = await cihaz_ac(imei="111111111111111")
    hat = await _hat(db, "8990011234500000001", "STOKTA")
    db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
    await db.commit()

    assert await hat_durumu_duzelt(db, yaz=False) == 0
    await db.refresh(hat)
    assert hat.status == "STOKTA"


async def test_donemi_kapanmis_hat_stokta_kalir(db, cihaz_ac):
    """Sökülmüş hat gerçekten depoya dönmüş olabilir; kanıt yok."""
    cihaz = await cihaz_ac(imei="111111111111111")
    hat = await _hat(db, "8990011234500000001", "STOKTA")
    db.add(
        SimDeviceHistory(
            sim_id=hat.id,
            device_id=cihaz.id,
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_to=datetime(2025, 6, 1, tzinfo=UTC),
        )
    )
    await db.commit()

    assert await hat_durumu_duzelt(db, yaz=True) == 0
    await db.refresh(hat)
    assert hat.status == "STOKTA"


async def test_hic_cihaza_takilmamis_hat_stokta_kalir(db):
    hat = await _hat(db, "8990011234500000001", "STOKTA")
    assert await hat_durumu_duzelt(db, yaz=True) == 0
    await db.refresh(hat)
    assert hat.status == "STOKTA"


async def test_bostaki_aktif_hat_stoktaya_CEKILMEZ(db):
    """Boşta duran AKTİF hat hata değil: operatörde açık, yani para yakıyor.

    Ters yönde "düzeltmek" bu sinyali siler — hat kârlılığı raporunun görmesi
    gereken tam olarak bu.
    """
    hat = await _hat(db, "8990011234500000001", "AKTIF")
    await hat_durumu_duzelt(db, yaz=True)
    await db.refresh(hat)
    assert hat.status == "AKTIF"


async def test_ikinci_kosuda_yapacak_is_kalmaz(db, cihaz_ac):
    cihaz = await cihaz_ac(imei="111111111111111")
    hat = await _hat(db, "8990011234500000001", "STOKTA")
    db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
    await db.commit()

    assert await hat_durumu_duzelt(db, yaz=True) == 1
    assert await hat_durumu_duzelt(db, yaz=True) == 0


async def test_yalniz_hatali_satirlara_dokunulur(db, cihaz_ac):
    """Aynı koşuda doğru durumdaki hatlar değişmemeli."""
    c1 = await cihaz_ac(imei="111111111111111")
    c2 = await cihaz_ac(imei="222222222222222")
    hatali = await _hat(db, "8990011234500000001", "STOKTA")
    dogru = await _hat(db, "8990011234500000002", "AKTIF")
    bosta = await _hat(db, "8990011234500000003", "STOKTA")
    db.add(SimDeviceHistory(sim_id=hatali.id, device_id=c1.id, valid_from=None))
    db.add(SimDeviceHistory(sim_id=dogru.id, device_id=c2.id, valid_from=None))
    await db.commit()

    assert await hat_durumu_duzelt(db, yaz=True) == 1
    for h in (hatali, dogru, bosta):
        await db.refresh(h)
    assert hatali.status == "AKTIF"
    assert dogru.status == "AKTIF"
    assert bosta.status == "STOKTA"
    kalan = (await db.scalars(select(SimCard).where(SimCard.status == "STOKTA"))).all()
    assert [h.id for h in kalan] == [bosta.id]
