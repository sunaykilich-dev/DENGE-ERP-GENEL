"""`devices.uzlastir` — türetilmiş `current_*` alanlarının yeniden hesabı.

Bu alanlar yalnız sorguyu ucuzlatmak için var; doğruluk kaynağı tarihli
tablolardır. Uzlaştırma yanlış türetirse alanı SESSİZCE siler, çünkü işini
yapıyor sanır. Gerçekte olan buydu: takip platformundan gelen cihazların
plakası yok, sahipliği zimmetten belli; uzlaştırma yalnız araç atamasına
baktığı için 9.945 cihazın müşterisini sildi.
"""

from datetime import UTC, datetime

import pytest

from app.clock import FakeClock
from app.models import Account
from app.services import devices as svc
from app.services import stock as stok_svc

pytestmark = pytest.mark.integration


@pytest.fixture
async def musteri_ac(db):
    async def _make(ad: str) -> Account:
        h = Account(title=ad, is_musteri=True)
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


class TestUzlastirma:
    async def test_aracsiz_cihazin_musterisi_zimmetten_gelir(self, db, cihaz_ac, musteri_ac):
        saat = FakeClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
        c = await cihaz_ac(imei="111111111111111")
        m = await musteri_ac("Plakasız Müşteri")
        await stok_svc.konum_ata(
            db,
            device_id=c.id,
            location_type="MUSTERI",
            account_id=m.id,
            ownership="MUSTERI_SATILDI",
            clock=saat,
        )
        c.current_customer_id = m.id
        await db.commit()

        sonuc = await svc.uzlastir(db, yaz=True)
        await db.refresh(c)
        assert c.current_customer_id == m.id, "zimmetli cihazın müşterisi silinmemeli"
        assert sonuc["farkli"] == 0

    async def test_depodaki_cihazin_musterisi_olmaz(self, db, cihaz_ac):
        saat = FakeClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
        c = await cihaz_ac(imei="222222222222222")
        await stok_svc.konum_ata(
            db, device_id=c.id, location_type="MERKEZ_DEPO", clock=saat, ownership="DENGE"
        )
        await db.commit()

        await svc.uzlastir(db, yaz=True)
        await db.refresh(c)
        assert c.current_customer_id is None

    async def test_ikinci_kosu_bir_sey_degistirmez(self, db, cihaz_ac, musteri_ac):
        """Gece işi her gece koşacak; ikinci koşu fark bulmamalı."""
        saat = FakeClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
        c = await cihaz_ac(imei="333333333333333")
        m = await musteri_ac("Tekrar Müşterisi")
        await stok_svc.konum_ata(
            db,
            device_id=c.id,
            location_type="MUSTERI",
            account_id=m.id,
            ownership="MUSTERI_SATILDI",
            clock=saat,
        )
        await db.commit()

        await svc.uzlastir(db, yaz=True)
        await db.commit()
        ikinci = await svc.uzlastir(db, yaz=True)
        assert ikinci["farkli"] == 0
