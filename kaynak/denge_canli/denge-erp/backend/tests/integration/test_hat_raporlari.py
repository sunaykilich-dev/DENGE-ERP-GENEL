"""Hat: paket geçmişi, operatör senkronu ve raporlar."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.clock import FakeClock
from app.integrations.base import HatDurumu
from app.models import SimPlanHistory
from app.services import sims as svc

pytestmark = pytest.mark.integration


def _an(gun: int = 1) -> datetime:
    return datetime(2026, 3, gun, 12, tzinfo=UTC)


class TestPaketGecmisi:
    async def test_yeni_paket_oncekini_kapatir(self, db, hat_ac):
        saat = FakeClock(_an(1))
        h = await hat_ac("8990011234567890123")
        await svc.paket_degistir(db, h, clock=saat, plan_name="100 MB", data_allowance_mb=100)
        saat.advance(days=30)
        await svc.paket_degistir(db, h, clock=saat, plan_name="50 GB", data_allowance_mb=51200)
        await db.commit()

        from sqlalchemy import select

        kayitlar = (
            await db.scalars(
                select(SimPlanHistory)
                .where(SimPlanHistory.sim_id == h.id)
                .order_by(SimPlanHistory.valid_from)
            )
        ).all()
        assert len(kayitlar) == 2
        assert kayitlar[0].valid_to is not None
        assert kayitlar[1].valid_to is None
        assert h.plan_name == "50 GB"


class TestSenkron:
    async def test_operator_verisi_uygulanir(self, db, hat_ac):
        h = await hat_ac("8990011234567890123")
        durum = HatDurumu(
            iccid=h.iccid,
            status="AKTIF",
            plan_name="50 GB",
            data_allowance_mb=51200,
            data_used_mb=1024,
            enabled_network_tech=["4G"],
        )
        degisen = await svc.senkron_uygula(db, h, durum, FakeClock())
        await db.commit()
        assert h.plan_name == "50 GB"
        assert h.data_used_mb == 1024
        assert set(degisen) >= {"plan_name", "data_used_mb"}
        assert h.field_sources["plan_name"] == svc.API

    async def test_elle_girilen_alan_ezilmez(self, db, hat_ac):
        """Ekibin düzelttiği değer her gece geri alınmamalı."""
        h = await hat_ac("8990011234567890123", plan_name="Elle Girilen 20 GB")
        h.field_sources = {"plan_name": svc.MANUEL}
        await db.commit()

        durum = HatDurumu(iccid=h.iccid, plan_name="Operatör Paketi", data_used_mb=500)
        await svc.senkron_uygula(db, h, durum, FakeClock())
        await db.commit()
        assert h.plan_name == "Elle Girilen 20 GB", "elle girilen paket ezildi"
        assert h.data_used_mb == 500, "elle girilmemiş alan güncellenmeliydi"

    async def test_operator_bos_donen_alani_silmez(self, db, hat_ac):
        """Brief §4.4: elle girilen değer, API boş döndüğünde silinmez."""
        h = await hat_ac("8990011234567890123", plan_name="20 GB", data_allowance_mb=20480)
        await db.commit()
        durum = HatDurumu(iccid=h.iccid, data_used_mb=100)  # paket alanı None
        await svc.senkron_uygula(db, h, durum, FakeClock())
        await db.commit()
        assert h.plan_name == "20 GB"
        assert h.data_allowance_mb == 20480


class TestRaporlar:
    async def test_kota_uyarisi_esiklere_gore(self, db, seeded, hat_ac):
        await hat_ac("8990011234567890121", data_allowance_mb=1000, data_used_mb=500)  # %50
        await hat_ac("8990011234567890122", data_allowance_mb=1000, data_used_mb=850)  # %85
        await hat_ac("8990011234567890123", data_allowance_mb=1000, data_used_mb=1200)  # %120
        uyarilar = await svc.kota_uyarilari(db)
        assert [u["seviye"] for u in uyarilar] == ["ASILDI", "UYARI"]
        assert uyarilar[0]["yuzde"] == 120

    async def test_2g_riski_cihaz_ve_hatti_birlikte_listeler(self, db, urun_ac, cihaz_ac, hat_ac):
        eski = await urun_ac("GS12", "IMEI", supported_network_tech=["2G"])
        yeni = await urun_ac("L300", "IMEI", supported_network_tech=["2G", "4G"])
        await cihaz_ac(imei="111111111111111", urun=eski, status="AKTIF")
        await cihaz_ac(imei="222222222222222", urun=yeni, status="AKTIF")
        await hat_ac("8990011234567890121", status="AKTIF", enabled_network_tech=["2G"])
        await hat_ac("8990011234567890122", status="AKTIF", enabled_network_tech=["2G", "4G"])

        risk = await svc.iki_g_riski(db)
        kimlikler = {r["kimlik"] for r in risk}
        assert "111111111111111" in kimlikler, "yalnız 2G cihaz listelenmeli"
        assert "222222222222222" not in kimlikler, "4G destekleyen cihaz risk değil"
        assert len([r for r in risk if r["tur"] == "HAT"]) == 1

    async def test_atil_hat_hic_senkron_edilmemisi_de_sayar(self, db, seeded, hat_ac):
        """Kullanım verisi gelmiyorsa maliyet görünmez kalmamalı."""
        await hat_ac("8990011234567890121", status="AKTIF")  # usage_synced_at None
        atil = await svc.atil_hatlar(db, FakeClock())
        assert len(atil) == 1
        assert atil[0]["neden"] == "Hiç senkron edilmedi"

    async def test_hat_karliligi(self, db, hat_ac):
        await hat_ac(
            "8990011234567890121",
            status="AKTIF",
            tariff_cost=Decimal("1.89"),
            package_cost=Decimal("12.54"),
            apn_cost=Decimal("0"),
            monthly_charge=Decimal("35.00"),
        )
        k = await svc.hat_karliligi(db)
        assert k["aktif_hat"] == 1
        assert k["aylik_maliyet"] == pytest.approx(14.43)
        assert k["aylik_marj"] == pytest.approx(20.57)

    async def test_taahhudu_bitenler(self, db, seeded, hat_ac):
        saat = FakeClock(_an(1))
        bugun = saat.now().date()
        await hat_ac("8990011234567890121", commitment_end_date=bugun + timedelta(days=30))
        await hat_ac("8990011234567890122", commitment_end_date=bugun + timedelta(days=400))
        liste = await svc.taahhudu_bitenler(db, saat)
        assert len(liste) == 1, "yalnız eşik içindeki taahhüt listelenmeli"
        assert liste[0]["kalan_gun"] == 30

    async def test_taahhut_bitmis_olanlar_da_gorunur(self, db, seeded, hat_ac):
        saat = FakeClock(_an(1))
        await hat_ac(
            "8990011234567890121", commitment_end_date=saat.now().date() - timedelta(days=5)
        )
        liste = await svc.taahhudu_bitenler(db, saat)
        assert liste[0]["kalan_gun"] == -5, "süresi geçmiş taahhüt gizlenmemeli"


async def test_paket_gecmisi_cakisamaz(db, hat_ac):
    """Aynı hatta iki açık paket dönemi olamaz."""
    from sqlalchemy.exc import IntegrityError

    h = await hat_ac("8990011234567890123")
    db.add(SimPlanHistory(sim_id=h.id, plan_name="A", valid_from=_an(1)))
    await db.commit()
    db.add(SimPlanHistory(sim_id=h.id, plan_name="B", valid_from=_an(5)))
    with pytest.raises(IntegrityError):
        await db.commit()


def test_adaptor_yapilandirilmamissa_sessiz_gecmez():
    """Operatör bağlantısı eksikse senkron boş dönmemeli — kullanıcı
    'çalıştı ama veri yok' sanmamalı."""
    import asyncio

    from app.integrations.turk_telekom import AdaptorHazirDegil, TurkTelekomAdaptoru

    a = TurkTelekomAdaptoru(base_url="", api_key="")
    with pytest.raises(AdaptorHazirDegil, match="yapılandırılmamış"):
        asyncio.run(a.hat_durumu("123"))
