"""Stok: konum/sahiplik geçmişi, transfer, bayi stoğu."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.clock import FakeClock
from app.models import Account, DeviceCustodyHistory, Transfer, TransferItem
from app.services import stock as svc

pytestmark = pytest.mark.integration


def _an(gun: int) -> datetime:
    return datetime(2026, 3, gun, 12, tzinfo=UTC)


@pytest.fixture
async def bayi_ac(db):
    async def _make(ad: str) -> Account:
        h = Account(title=ad, is_bayi=True)
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


class TestKonumGecmisi:
    async def test_cihaz_ayni_anda_iki_yerde_olamaz(self, db, cihaz_ac):
        c = await cihaz_ac(imei="111111111111111")
        db.add(DeviceCustodyHistory(device_id=c.id, location_type="MERKEZ_DEPO", valid_from=_an(1)))
        await db.commit()
        db.add(DeviceCustodyHistory(device_id=c.id, location_type="BAYI", valid_from=_an(5)))
        with pytest.raises(IntegrityError, match="ex_custody_cakisma"):
            await db.commit()

    async def test_konum_degisikligi_sahipligi_korur(self, db, cihaz_ac, bayi_ac):
        """Depo→bayi sevkinde cihaz hâlâ Denge'nin malı olabilir; konum ve
        sahiplik ayrı boyutlar."""
        saat = FakeClock(_an(1))
        c = await cihaz_ac(imei="111111111111111")
        b = await bayi_ac("İzmir Bayi")
        await svc.konum_ata(
            db, device_id=c.id, location_type="MERKEZ_DEPO", clock=saat, ownership="DENGE"
        )
        saat.advance(days=5)
        yeni = await svc.konum_ata(
            db, device_id=c.id, location_type="BAYI", account_id=b.id, clock=saat
        )
        await db.commit()
        assert yeni.ownership == "DENGE", "konum değişikliği mülkiyeti değiştirmemeli"

    async def test_sahiplik_acikca_degistirilir(self, db, cihaz_ac, bayi_ac):
        saat = FakeClock(_an(1))
        c = await cihaz_ac(imei="111111111111111")
        b = await bayi_ac("İzmir Bayi")
        await svc.konum_ata(db, device_id=c.id, location_type="MERKEZ_DEPO", clock=saat)
        saat.advance(days=5)
        yeni = await svc.konum_ata(
            db,
            device_id=c.id,
            location_type="BAYI",
            account_id=b.id,
            ownership="BAYI_SATILDI",
            clock=saat,
        )
        await db.commit()
        assert yeni.ownership == "BAYI_SATILDI"

    async def test_gecmis_tarihte_neredeydi(self, db, cihaz_ac, bayi_ac):
        """Brief §4.3: geçmişteki herhangi bir tarihte cihazın nerede olduğu
        sorgulanabilir."""
        c = await cihaz_ac(imei="111111111111111")
        b = await bayi_ac("İzmir Bayi")
        db.add(
            DeviceCustodyHistory(
                device_id=c.id,
                location_type="MERKEZ_DEPO",
                valid_from=_an(1),
                valid_to=_an(10),
            )
        )
        db.add(
            DeviceCustodyHistory(
                device_id=c.id, location_type="BAYI", account_id=b.id, valid_from=_an(10)
            )
        )
        await db.commit()

        assert (await svc.konum_tarihinde(db, c.id, _an(5))).location_type == "MERKEZ_DEPO"
        assert (await svc.konum_tarihinde(db, c.id, _an(20))).location_type == "BAYI"

    async def test_geriye_donuk_kayit_reddedilir(self, db, cihaz_ac):
        """Mevcut kaydın başlangıcından eski bir konum, kısıta takılmadan
        önce anlaşılır bir hatayla durdurulur."""
        saat = FakeClock(_an(10))
        c = await cihaz_ac(imei="111111111111111")
        await svc.konum_ata(db, device_id=c.id, location_type="MERKEZ_DEPO", clock=saat)
        with pytest.raises(svc.TransferHatasi, match="eski olamaz"):
            await svc.konum_ata(db, device_id=c.id, location_type="BAYI", clock=saat, an=_an(5))


class TestTransfer:
    async def _transfer(self, db, cihazlar, bayi, *, sahiplik="BAYI_SATILDI") -> Transfer:
        t = Transfer(
            transfer_no="TR202603-00001",
            type="SATIS",
            status="YOLDA",
            from_location_type="MERKEZ_DEPO",
            to_location_type="BAYI",
            to_account_id=bayi.id,
            new_ownership=sahiplik,
        )
        db.add(t)
        await db.flush()
        for c in cihazlar:
            db.add(TransferItem(transfer_id=t.id, device_id=c.id))
        await db.commit()
        return t

    async def test_teslim_tum_cihazlarin_konumunu_gunceller(self, db, cihaz_ac, bayi_ac):
        saat = FakeClock(_an(1))
        cihazlar = [await cihaz_ac(imei=f"11111111111111{i}") for i in range(3)]
        b = await bayi_ac("İzmir Bayi")
        for c in cihazlar:
            await svc.konum_ata(db, device_id=c.id, location_type="MERKEZ_DEPO", clock=saat)
        await db.commit()

        t = await self._transfer(db, cihazlar, b)
        saat.advance(days=3)
        adet = await svc.transferi_teslim_et(db, t, clock=saat)
        await db.commit()

        assert adet == 3
        assert t.status == "TESLIM_EDILDI"
        for c in cihazlar:
            konum = await svc.acik_konum(db, c.id)
            assert konum.location_type == "BAYI"
            assert konum.ownership == "BAYI_SATILDI"
            assert konum.transfer_id == t.id

    async def test_iki_kez_teslim_edilemez(self, db, cihaz_ac, bayi_ac):
        saat = FakeClock(_an(1))
        c = await cihaz_ac(imei="111111111111111")
        b = await bayi_ac("İzmir Bayi")
        t = await self._transfer(db, [c], b)
        await svc.transferi_teslim_et(db, t, clock=saat)
        await db.commit()
        with pytest.raises(svc.TransferHatasi, match="zaten teslim"):
            await svc.transferi_teslim_et(db, t, clock=saat)

    async def test_bos_transfer_teslim_edilemez(self, db, bayi_ac):
        b = await bayi_ac("İzmir Bayi")
        t = Transfer(
            transfer_no="TR-BOS",
            type="SATIS",
            status="YOLDA",
            from_location_type="MERKEZ_DEPO",
            to_location_type="BAYI",
            to_account_id=b.id,
        )
        db.add(t)
        await db.commit()
        with pytest.raises(svc.TransferHatasi, match="hiç cihaz yok"):
            await svc.transferi_teslim_et(db, t, clock=FakeClock())


class TestBayiStogu:
    async def test_bayi_bazinda_adet_ve_sahiplik(self, db, cihaz_ac, bayi_ac):
        saat = FakeClock(_an(1))
        b = await bayi_ac("İzmir Bayi")
        for i in range(2):
            c = await cihaz_ac(imei=f"22222222222222{i}")
            await svc.konum_ata(
                db,
                device_id=c.id,
                location_type="BAYI",
                account_id=b.id,
                ownership="BAYI_SATILDI",
                clock=saat,
            )
        await db.commit()
        stok = await svc.bayi_stogu(db)
        assert len(stok) == 1
        assert stok[0]["adet"] == 2
        assert stok[0]["ownership"] == "BAYI_SATILDI"
        # Unvan sorgudan gelir: iki ayrı uç bunu tek tek hesap çekerek
        # dolduruyordu ve biri hiç doldurmuyordu.
        assert stok[0]["account_title"] == "İzmir Bayi"

    async def test_yaslanan_stok_esige_gore(self, db, seeded, cihaz_ac, bayi_ac):
        saat = FakeClock(_an(1))
        b = await bayi_ac("İzmir Bayi")
        eski = await cihaz_ac(imei="111111111111111")
        yeni = await cihaz_ac(imei="222222222222222")
        await svc.konum_ata(
            db, device_id=eski.id, location_type="BAYI", account_id=b.id, clock=saat
        )
        saat.advance(days=200)
        await svc.konum_ata(
            db, device_id=yeni.id, location_type="BAYI", account_id=b.id, clock=saat
        )
        await db.commit()

        # Varsayılan eşik 90 gün
        yaslananlar = await svc.yaslanan_stok(db, saat)
        assert [y["kimlik"] for y in yaslananlar] == ["111111111111111"]
        assert yaslananlar[0]["bekleme_gunu"] == 200
