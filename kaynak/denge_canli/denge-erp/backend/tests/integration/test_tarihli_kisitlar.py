"""Tarihli kayıt çakışma kısıtları — ERP'nin veritabanı seviyesindeki çekirdeği.

Bu testler `btree_gist` uzantısı ve PostgreSQL 17 olmadan koşamaz; planın
Docker kararı tam olarak bunun için alındı (gömülü `pgserver` PG 16.2
getiriyor ve `btree_gist` içermiyor).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import SimDeviceHistory, SimPlanHistory

pytestmark = pytest.mark.integration


def _an(gun: int, saat: int = 0) -> datetime:
    return datetime(2026, 3, gun, saat, tzinfo=UTC)


class TestHatCihazEslesmesi:
    async def test_bir_hat_ayni_anda_iki_cihazda_olamaz(self, db, hat_ac, cihaz_ac):
        hat = await hat_ac("8990011234567890123")
        c1 = await cihaz_ac(imei="111111111111111")
        c2 = await cihaz_ac(imei="222222222222222")

        db.add(SimDeviceHistory(sim_id=hat.id, device_id=c1.id, valid_from=_an(1)))
        await db.commit()

        db.add(SimDeviceHistory(sim_id=hat.id, device_id=c2.id, valid_from=_an(5)))
        with pytest.raises(IntegrityError, match="ex_sim_cihaz_hat_cakisma"):
            await db.commit()

    async def test_bir_cihazda_ayni_anda_iki_hat_olamaz(self, db, hat_ac, cihaz_ac):
        h1 = await hat_ac("8990011234567890123")
        h2 = await hat_ac("8990011234567890124")
        cihaz = await cihaz_ac(imei="111111111111111")

        db.add(SimDeviceHistory(sim_id=h1.id, device_id=cihaz.id, valid_from=_an(1)))
        await db.commit()

        db.add(SimDeviceHistory(sim_id=h2.id, device_id=cihaz.id, valid_from=_an(5)))
        with pytest.raises(IntegrityError, match="ex_sim_cihaz_cihaz_cakisma"):
            await db.commit()

    async def test_kapanmis_donemden_sonra_yeni_donem_acilir(self, db, hat_ac, cihaz_ac):
        hat = await hat_ac("8990011234567890123")
        c1 = await cihaz_ac(imei="111111111111111")
        c2 = await cihaz_ac(imei="222222222222222")

        db.add(
            SimDeviceHistory(sim_id=hat.id, device_id=c1.id, valid_from=_an(1), valid_to=_an(10))
        )
        db.add(SimDeviceHistory(sim_id=hat.id, device_id=c2.id, valid_from=_an(10)))
        await db.commit()  # hata beklenmiyor

    async def test_bitisik_donemler_gecerli(self, db, hat_ac, cihaz_ac):
        """`[)` yarı açık aralık: bir dönemin bitişi diğerinin başlangıcına
        EŞİT olabilir. `[]` kullanılsaydı aynı gün sök-tak yapılan gerçek
        kayıtlar reddedilirdi — göç verisinde bu durum var."""
        hat = await hat_ac("8990011234567890123")
        c1 = await cihaz_ac(imei="111111111111111")
        c2 = await cihaz_ac(imei="222222222222222")
        an = _an(7, 14)

        db.add(SimDeviceHistory(sim_id=hat.id, device_id=c1.id, valid_from=_an(1), valid_to=an))
        db.add(SimDeviceHistory(sim_id=hat.id, device_id=c2.id, valid_from=an, valid_to=_an(20)))
        await db.commit()

    async def test_gecmis_donemler_de_cakisamaz(self, db, hat_ac, cihaz_ac):
        """Geriye dönük düzeltme yapılırken eski dönemlerin çakışması da
        engellenmeli — yoksa 'X tarihinde bu hat neredeydi' iki cevap verir."""
        hat = await hat_ac("8990011234567890123")
        c1 = await cihaz_ac(imei="111111111111111")
        c2 = await cihaz_ac(imei="222222222222222")

        db.add(
            SimDeviceHistory(sim_id=hat.id, device_id=c1.id, valid_from=_an(1), valid_to=_an(20))
        )
        await db.commit()

        db.add(
            SimDeviceHistory(sim_id=hat.id, device_id=c2.id, valid_from=_an(10), valid_to=_an(15))
        )
        with pytest.raises(IntegrityError):
            await db.commit()

    async def test_ters_aralik_reddedilir(self, db, hat_ac, cihaz_ac):
        hat = await hat_ac("8990011234567890123")
        cihaz = await cihaz_ac(imei="111111111111111")
        db.add(
            SimDeviceHistory(
                sim_id=hat.id, device_id=cihaz.id, valid_from=_an(20), valid_to=_an(10)
            )
        )
        with pytest.raises(IntegrityError, match="ck_sim_cihaz_aralik"):
            await db.commit()


class TestPaketGecmisi:
    async def test_ayni_hatta_cakisan_paket_donemi_olamaz(self, db, hat_ac):
        hat = await hat_ac("8990011234567890123")
        db.add(
            SimPlanHistory(sim_id=hat.id, plan_name="100MB", valid_from=_an(1), valid_to=_an(20))
        )
        await db.commit()
        db.add(SimPlanHistory(sim_id=hat.id, plan_name="50GB", valid_from=_an(10)))
        with pytest.raises(IntegrityError):
            await db.commit()

    async def test_ayni_hatta_tek_acik_paket_donemi(self, db, hat_ac):
        """Açık dönem kısmi tekil indeksle de korunur — EXCLUDE'a ek güvenlik
        ağı: 'şu an hangi paket' sorusunun iki cevabı olamaz."""
        hat = await hat_ac("8990011234567890123")
        db.add(SimPlanHistory(sim_id=hat.id, plan_name="100MB", valid_from=_an(1)))
        await db.commit()
        db.add(SimPlanHistory(sim_id=hat.id, plan_name="50GB", valid_from=_an(1)))
        with pytest.raises(IntegrityError):
            await db.commit()

    async def test_farkli_hatlar_etkilenmez(self, db, hat_ac):
        h1 = await hat_ac("8990011234567890123")
        h2 = await hat_ac("8990011234567890124")
        db.add(SimPlanHistory(sim_id=h1.id, plan_name="100MB", valid_from=_an(1)))
        db.add(SimPlanHistory(sim_id=h2.id, plan_name="50GB", valid_from=_an(1)))
        await db.commit()
