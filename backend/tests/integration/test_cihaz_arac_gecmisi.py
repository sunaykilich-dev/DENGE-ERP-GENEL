"""Cihaz–araç ömür boyu geçmişi — kabul kriterleri 2, 3 ve 6."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.clock import FakeClock
from app.models import DeviceVehicleAssignment, Vehicle
from app.services import assignments as svc

pytestmark = pytest.mark.integration


def _an(gun: int) -> datetime:
    return datetime(2026, 3, gun, 12, tzinfo=UTC)


@pytest.fixture
async def arac_ac(db):
    async def _make(plate: str) -> Vehicle:
        a = Vehicle(plate=plate)
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a

    return _make


class TestKisitlar:
    async def test_cihaz_ayni_anda_iki_aracta_olamaz(self, db, cihaz_ac, arac_ac):
        """Kural AÇIK dönem tekilliğiyle korunur (`uq_dva_acik_donem`).

        EXCLUDE kısıtı `8c41d2b7e903` ile KISMİ hale geldi (yalnız tarihli
        satırlar), bu yüzden burada önce kısmi tekil indeks devreye giriyor.
        Test kısıtın ADINA değil KURALA bakar: hangisinin önce yakaladığı
        indekslerin kuruluş sırasına bağlı bir ayrıntı.
        """
        c = await cihaz_ac(imei="111111111111111")
        a1 = await arac_ac("34ABC001")
        a2 = await arac_ac("34ABC002")
        db.add(DeviceVehicleAssignment(device_id=c.id, vehicle_id=a1.id, valid_from=_an(1)))
        await db.commit()
        db.add(DeviceVehicleAssignment(device_id=c.id, vehicle_id=a2.id, valid_from=_an(5)))
        with pytest.raises(IntegrityError, match="uq_dva_acik_donem|ex_dva_cihaz_cakisma"):
            await db.commit()
        await db.rollback()

    async def test_cakisan_kapali_donemler_reddedilir(self, db, cihaz_ac, arac_ac):
        """EXCLUDE'u YALNIZ BAŞINA sınar: iki dönem de KAPALI olduğu için
        açık dönem tekil indeksi devreye girmez, geriye çakışma kısıtı kalır.
        Kısmi EXCLUDE tarihli satırlarda hâlâ iş görüyor mu — asıl soru bu."""
        c = await cihaz_ac(imei="111111111111111")
        a1 = await arac_ac("34ABC001")
        a2 = await arac_ac("34ABC002")
        db.add(
            DeviceVehicleAssignment(
                device_id=c.id, vehicle_id=a1.id, valid_from=_an(1), valid_to=_an(10)
            )
        )
        await db.commit()
        db.add(
            DeviceVehicleAssignment(
                device_id=c.id, vehicle_id=a2.id, valid_from=_an(5), valid_to=_an(15)
            )
        )
        with pytest.raises(IntegrityError, match="ex_dva_cihaz_cakisma"):
            await db.commit()
        await db.rollback()

    async def test_bitisik_kapali_donemler_gecer(self, db, cihaz_ac, arac_ac):
        """Aynı gün sök–tak gerçek veride var; `[)` yarı açık aralık bunu
        çakışma saymamalı."""
        c = await cihaz_ac(imei="111111111111111")
        a1 = await arac_ac("34ABC001")
        a2 = await arac_ac("34ABC002")
        db.add(
            DeviceVehicleAssignment(
                device_id=c.id, vehicle_id=a1.id, valid_from=_an(1), valid_to=_an(10)
            )
        )
        db.add(
            DeviceVehicleAssignment(
                device_id=c.id, vehicle_id=a2.id, valid_from=_an(10), valid_to=_an(15)
            )
        )
        await db.commit()  # hata beklenmiyor

    async def test_tarihsiz_donem_gercek_gecmisi_kilitlemez(self, db, cihaz_ac, arac_ac):
        """`tstzrange(NULL, NULL)` sonsuz aralık sayılsaydı, başlangıcı
        bilinmeyen TEK bir satır cihazın bütün geçmişiyle çakışırdı."""
        c = await cihaz_ac(imei="111111111111111")
        a1 = await arac_ac("34ABC001")
        a2 = await arac_ac("34ABC002")
        db.add(
            DeviceVehicleAssignment(
                device_id=c.id, vehicle_id=a1.id, valid_from=_an(1), valid_to=_an(10)
            )
        )
        await db.commit()
        db.add(DeviceVehicleAssignment(device_id=c.id, vehicle_id=a2.id, valid_from=None))
        await db.commit()  # hata beklenmiyor

    async def test_bir_aracta_ayni_anda_birden_fazla_cihaz_OLABILIR(self, db, cihaz_ac, arac_ac):
        """Ters kısıt BİLİNÇLİ OLARAK yok: araçların %96,8'inde birden fazla
        cihaz var (tipik set: araç kamerası + ek kamera + araç takip)."""
        a = await arac_ac("34ABC001")
        for i in range(3):
            c = await cihaz_ac(imei=f"11111111111111{i}")
            db.add(DeviceVehicleAssignment(device_id=c.id, vehicle_id=a.id, valid_from=_an(1)))
        await db.commit()  # hata beklenmiyor

        takili = await svc.aracin_cihazlari(db, a.id, yalniz_takili=True)
        assert len(takili) == 3


class TestSorgular:
    async def test_x_tarihinde_hangi_aracta(self, db, cihaz_ac, arac_ac):
        """Kabul kriteri 2."""
        c = await cihaz_ac(imei="111111111111111")
        a1 = await arac_ac("34ABC001")
        a2 = await arac_ac("34ABC002")
        db.add(
            DeviceVehicleAssignment(
                device_id=c.id, vehicle_id=a1.id, valid_from=_an(1), valid_to=_an(10)
            )
        )
        db.add(DeviceVehicleAssignment(device_id=c.id, vehicle_id=a2.id, valid_from=_an(10)))
        await db.commit()

        assert (await svc.arac_tarihinde(db, c.id, _an(5))).vehicle_id == a1.id
        assert (await svc.arac_tarihinde(db, c.id, _an(20))).vehicle_id == a2.id
        # Sınır: dönem [) yarı açık, 10'unda ikinci araçta
        assert (await svc.arac_tarihinde(db, c.id, _an(10))).vehicle_id == a2.id
        assert await svc.arac_tarihinde(db, c.id, datetime(2025, 1, 1, tzinfo=UTC)) is None

    async def test_aracin_gecmisindeki_tum_cihazlar(self, db, cihaz_ac, arac_ac):
        """Kabul kriteri 3."""
        a = await arac_ac("34ABC001")
        c1 = await cihaz_ac(imei="111111111111111")
        c2 = await cihaz_ac(imei="222222222222222")
        db.add(
            DeviceVehicleAssignment(
                device_id=c1.id, vehicle_id=a.id, valid_from=_an(1), valid_to=_an(10)
            )
        )
        db.add(DeviceVehicleAssignment(device_id=c2.id, vehicle_id=a.id, valid_from=_an(10)))
        await db.commit()

        hepsi = await svc.aracin_cihazlari(db, a.id)
        assert len(hepsi) == 2
        takili = await svc.aracin_cihazlari(db, a.id, yalniz_takili=True)
        assert [t.device_id for t in takili] == [c2.id]


class TestSokTak:
    async def test_sok_tak_eski_kaydi_kapatir_yenisini_acar(self, db, cihaz_ac, arac_ac):
        """Kabul kriteri 6 — çakışan kayıt oluşmaz."""
        saat = FakeClock(_an(1))
        c = await cihaz_ac(imei="111111111111111")
        a1 = await arac_ac("34ABC001")
        a2 = await arac_ac("34ABC002")

        await svc.tak(db, device_id=c.id, vehicle_id=a1.id, clock=saat)
        await db.commit()

        saat.advance(days=30)
        await svc.tak(db, device_id=c.id, vehicle_id=a2.id, clock=saat)
        await db.commit()

        hepsi = await svc.aracin_cihazlari(db, a1.id)
        assert hepsi[0].valid_to is not None, "eski dönem kapanmadı"
        acik = await svc.acik_donem(db, c.id)
        assert acik.vehicle_id == a2.id

    async def test_ayni_araca_tekrar_takma_yeni_donem_acmaz(self, db, cihaz_ac, arac_ac):
        saat = FakeClock(_an(1))
        c = await cihaz_ac(imei="111111111111111")
        a = await arac_ac("34ABC001")
        ilk = await svc.tak(db, device_id=c.id, vehicle_id=a.id, clock=saat)
        saat.advance(days=5)
        ikinci = await svc.tak(db, device_id=c.id, vehicle_id=a.id, clock=saat)
        assert ilk.id == ikinci.id

    async def test_sokum_acik_donemi_kapatir(self, db, cihaz_ac, arac_ac):
        saat = FakeClock(_an(1))
        c = await cihaz_ac(imei="111111111111111")
        a = await arac_ac("34ABC001")
        await svc.tak(db, device_id=c.id, vehicle_id=a.id, clock=saat)
        saat.advance(days=10)
        kapanan = await svc.sok(db, device_id=c.id, clock=saat, neden="Araç satıldı")
        assert kapanan.valid_to is not None
        assert await svc.acik_donem(db, c.id) is None

    async def test_acik_donemi_olmayan_cihazi_sokmek_hata_degil(self, db, cihaz_ac):
        """Göçte söküm kaydı olup montajı olmayan satırlar var."""
        c = await cihaz_ac(imei="111111111111111")
        assert await svc.sok(db, device_id=c.id, clock=FakeClock()) is None


class TestCikarim:
    def test_sokum_kaydi_olmadan_donemler_turetilir(self):
        """124 IMEI birden çok işte, 83'ü farklı plakalarda ve aralarda tek
        bir söküm kaydı yok."""
        from datetime import date

        olaylar = [
            {"tarih": date(2026, 2, 13), "tip": "MONTAJ", "vehicle_id": 1},
            {"tarih": date(2026, 6, 23), "tip": "MONTAJ", "vehicle_id": 2},
        ]
        donemler = svc.donemleri_cikar(olaylar)
        assert donemler[0]["valid_to"] == date(2026, 6, 23)
        assert donemler[0]["is_inferred"] is True
        assert donemler[1]["valid_to"] is None
        assert donemler[1]["is_inferred"] is False

    def test_ayni_gun_sok_tak_sirasi(self):
        """Eşit tarihte SÖKÜM önce işlenir ki aynı gün sök-tak doğru çıksın."""
        from datetime import date

        olaylar = [
            {"tarih": date(2026, 3, 1), "tip": "MONTAJ", "vehicle_id": 1},
            {"tarih": date(2026, 3, 10), "tip": "MONTAJ", "vehicle_id": 2},
            {"tarih": date(2026, 3, 10), "tip": "SOKUM", "vehicle_id": 1},
        ]
        donemler = svc.donemleri_cikar(olaylar)
        assert len(donemler) == 2
        assert donemler[0]["valid_to"] == date(2026, 3, 10)

    def test_sifir_uzunluklu_donem_atilir(self):
        """[t, t) yarı açık aralıkta geçersizdir; kısıta takılmadan elenir."""
        from datetime import date

        olaylar = [
            {"tarih": date(2026, 3, 1), "tip": "MONTAJ", "vehicle_id": 1},
            {"tarih": date(2026, 3, 1), "tip": "SOKUM", "vehicle_id": 1},
        ]
        assert svc.donemleri_cikar(olaylar) == []


class TestUzlastirma:
    """`devices.current_*` tarihli tablodan türetilir (plan §3.2).

    Göç bu alanları doldurmamıştı; sonucu görünürdü — garanti başlangıcı
    `first_activation_date`'ten geldiği için göçten gelen her cihazın RMA
    garanti kararı "belirsiz" çıkıyordu.
    """

    async def test_acik_donem_alanlara_yansir(self, db, cihaz_ac, arac_ac):
        from app.services import assignments as atama_svc
        from app.services.devices import uzlastir

        c = await cihaz_ac(imei="860000000009001")
        a = await arac_ac("34UZL001")
        await atama_svc.tak(db, device_id=c.id, vehicle_id=a.id, clock=FakeClock())
        c.current_vehicle_id = None
        c.first_activation_date = None
        await db.flush()

        sonuc = await uzlastir(db)
        assert sonuc["farkli"] == 1
        await db.refresh(c)
        assert c.current_vehicle_id == a.id
        assert c.first_activation_date is not None

    async def test_yaz_false_hicbir_sey_yazmaz(self, db, cihaz_ac, arac_ac):
        from app.services import assignments as atama_svc
        from app.services.devices import uzlastir

        c = await cihaz_ac(imei="860000000009002")
        a = await arac_ac("34UZL002")
        await atama_svc.tak(db, device_id=c.id, vehicle_id=a.id, clock=FakeClock())
        c.current_vehicle_id = None
        await db.flush()

        sonuc = await uzlastir(db, yaz=False)
        assert sonuc["farkli"] == 1
        await db.refresh(c)
        assert c.current_vehicle_id is None

    async def test_ilk_aktivasyon_geri_alinmaz(self, db, cihaz_ac, arac_ac):
        """Garanti başlangıcı sonradan ileri kaymamalı."""
        from datetime import date

        from app.services import assignments as atama_svc
        from app.services.devices import uzlastir

        c = await cihaz_ac(imei="860000000009003", first_activation_date=date(2020, 1, 1))
        a = await arac_ac("34UZL003")
        await atama_svc.tak(db, device_id=c.id, vehicle_id=a.id, clock=FakeClock())
        await db.flush()

        await uzlastir(db)
        await db.refresh(c)
        assert c.first_activation_date == date(2020, 1, 1)
