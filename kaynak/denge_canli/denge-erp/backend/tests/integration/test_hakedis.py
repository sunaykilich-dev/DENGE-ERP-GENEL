"""Tarife çözümlemesi, hak ediş hesabı, dönem kapanışı ve ödeme."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.clock import FakeClock
from app.models import (
    Account,
    InstallationPartner,
    PartnerSettlement,
    PartnerTariff,
    SettlementLine,
    WorkOrder,
    WorkOrderItem,
)
from app.services import settlements as svc
from app.services import tariffs
from app.services.settlements import VergiProfili, hesapla, yuvarla

pytestmark = pytest.mark.integration


def _an(yil: int, ay: int, gun: int = 1) -> datetime:
    return datetime(yil, ay, gun, 12, tzinfo=UTC)


@pytest.fixture
async def nokta_ac(db):
    async def _make(ad: str, belge_tipi: str = "FATURA") -> Account:
        h = Account(title=ad, is_montaj_noktasi=True)
        db.add(h)
        await db.flush()
        db.add(InstallationPartner(account_id=h.id, document_type=belge_tipi))
        await db.commit()
        await db.refresh(h)
        return h

    return _make


class TestTarifeCozumlemesi:
    async def test_tarih_gecerli_olan_tarifeyi_secer(self, db, nokta_ac):
        """Fiyat değişince eski işler ESKİ fiyattan hesaplanır (brief §4.7)."""
        n = await nokta_ac("Test Montaj")
        db.add(
            PartnerTariff(
                partner_id=n.id,
                work_type="ATS_MONTAJ",
                product_group="*",
                unit_price=Decimal("250"),
                valid_from=_an(2026, 1),
                valid_to=_an(2026, 4),
            )
        )
        db.add(
            PartnerTariff(
                partner_id=n.id,
                work_type="ATS_MONTAJ",
                product_group="*",
                unit_price=Decimal("350"),
                valid_from=_an(2026, 4),
            )
        )
        await db.commit()

        mart, _ = await tariffs.birim_fiyat(
            db, partner_id=n.id, work_type="ATS_MONTAJ", product_group="*", an=_an(2026, 3, 10)
        )
        nisan, _ = await tariffs.birim_fiyat(
            db, partner_id=n.id, work_type="ATS_MONTAJ", product_group="*", an=_an(2026, 4, 15)
        )
        assert mart == Decimal("250")
        assert nisan == Decimal("350")

    async def test_noktaya_ozel_tarife_geneli_gecer(self, db, nokta_ac):
        n = await nokta_ac("Test Montaj")
        db.add(
            PartnerTariff(
                partner_id=None,
                work_type="ATS_MONTAJ",
                product_group="*",
                unit_price=Decimal("350"),
                valid_from=_an(2026, 1),
            )
        )
        db.add(
            PartnerTariff(
                partner_id=n.id,
                work_type="ATS_MONTAJ",
                product_group="*",
                unit_price=Decimal("400"),
                valid_from=_an(2026, 1),
            )
        )
        await db.commit()
        fiyat, kaynak = await tariffs.birim_fiyat(
            db, partner_id=n.id, work_type="ATS_MONTAJ", product_group="*", an=_an(2026, 6)
        )
        assert fiyat == Decimal("400")
        assert kaynak == "TARIFE"

    async def test_tarife_yoksa_yok_doner(self, db, nokta_ac):
        n = await nokta_ac("Test Montaj")
        fiyat, kaynak = await tariffs.birim_fiyat(
            db, partner_id=n.id, work_type="ATS_MONTAJ", product_group="*", an=_an(2026, 6)
        )
        assert fiyat is None and kaynak == "YOK"

    async def test_cakisan_tarife_donemi_reddedilir(self, db, nokta_ac):
        from sqlalchemy.exc import IntegrityError

        n = await nokta_ac("Test Montaj")
        db.add(
            PartnerTariff(
                partner_id=n.id,
                work_type="ATS_MONTAJ",
                product_group="*",
                unit_price=Decimal("250"),
                valid_from=_an(2026, 1),
                valid_to=_an(2026, 6),
            )
        )
        await db.commit()
        db.add(
            PartnerTariff(
                partner_id=n.id,
                work_type="ATS_MONTAJ",
                product_group="*",
                unit_price=Decimal("350"),
                valid_from=_an(2026, 3),
            )
        )
        with pytest.raises(IntegrityError, match="ex_tarife_cakisma"):
            await db.commit()


class TestVergiHesabi:
    """DİKKAT: oranlar mali müşavir teyidi bekliyor; test ettiği şey FORMÜL."""

    def test_fatura_stopajsiz_kdv_eklenir(self):
        s = hesapla(
            brut=Decimal("1000"),
            kesinti=Decimal("0"),
            profil=VergiProfili("FATURA", kdv_oran=Decimal("0.20")),
        )
        assert s.kdv == Decimal("200.00")
        assert s.stopaj == Decimal("0")
        assert s.net == Decimal("1200.00")

    def test_serbest_meslek_makbuzu(self):
        s = hesapla(
            brut=Decimal("1000"),
            kesinti=Decimal("0"),
            profil=VergiProfili(
                "SERBEST_MESLEK_MAKBUZU",
                kdv_oran=Decimal("0.20"),
                stopaj_oran=Decimal("0.20"),
                damga_oran=Decimal("0.00759"),
            ),
        )
        assert s.kdv == Decimal("200.00")
        assert s.stopaj == Decimal("200.00")
        assert s.damga == Decimal("7.59")
        assert s.net == Decimal("992.41")

    def test_kesinti_matrahi_dusurur(self):
        s = hesapla(
            brut=Decimal("1000"),
            kesinti=Decimal("250"),
            profil=VergiProfili("FATURA", kdv_oran=Decimal("0.20")),
        )
        assert s.kdv == Decimal("150.00"), "KDV kesinti sonrası matrah üzerinden"
        assert s.net == Decimal("900.00")

    def test_belirsiz_belge_tipinde_kesinti_yok(self):
        s = hesapla(brut=Decimal("1000"), kesinti=Decimal("0"), profil=VergiProfili("BELIRSIZ"))
        assert s.net == Decimal("1000.00")

    def test_yuvarlama_kurusa_half_up(self):
        """Muhasebe 1 kuruşu tartışır; yöntem testle çivilenmiştir."""
        assert yuvarla(Decimal("7.585")) == Decimal("7.59")
        assert yuvarla(Decimal("7.584")) == Decimal("7.58")
        assert yuvarla(Decimal("0.005")) == Decimal("0.01")

    def test_oranlar_dokume_dondurulur(self):
        s = hesapla(
            brut=Decimal("100"),
            kesinti=Decimal("0"),
            profil=VergiProfili("FATURA", kdv_oran=Decimal("0.20")),
        )
        assert s.snapshot["kdv_oran"] == "0.20"
        assert s.snapshot["belge_tipi"] == "FATURA"


class TestDonemKapanisi:
    async def _is_emri(self, db, nokta, *, donem="2026-06", tutar=350, odenebilir=True, yol=None):
        wo = WorkOrder(
            wo_no=f"WO-{donem}-{nokta.id}-{tutar}",
            type="MONTAJ",
            status="ONAYLANDI",
            assigned_type="MONTAJ_NOKTASI",
            assigned_id=nokta.id,
            settlement_period=donem,
            completed_at=_an(2026, 6, 15),
            travel_km=Decimal(str(yol)) if yol else None,
            travel_unit_price=Decimal("10") if yol else None,
        )
        db.add(wo)
        await db.flush()
        db.add(
            WorkOrderItem(
                work_order_id=wo.id,
                action="TAKILDI",
                device_role="BIRINCIL_TAKIP",
                payability="ODENECEK" if odenebilir else "ODENMEYECEK",
                non_payable_reason=None if odenebilir else "KENDI_SATISI",
                unit_price=Decimal(str(tutar)),
                price_source="TARIFE",
            )
        )
        await db.commit()
        return wo

    async def test_dokum_uretilir_ve_toplanir(self, db, seeded, nokta_ac):
        n = await nokta_ac("Test Montaj")
        await self._is_emri(db, n, tutar=350)
        await self._is_emri(db, n, tutar=1000)
        dokumler = (await svc.donem_kapat(db, period="2026-06", clock=FakeClock())).dokumler
        await db.commit()
        assert len(dokumler) == 1
        assert Decimal(str(dokumler[0].gross_amount)) == Decimal("1350.00")

    async def test_odenmeyecek_kalem_dokume_girmez(self, db, seeded, nokta_ac):
        n = await nokta_ac("Test Montaj")
        await self._is_emri(db, n, tutar=350, odenebilir=True)
        await self._is_emri(db, n, tutar=999, odenebilir=False)
        dokumler = (await svc.donem_kapat(db, period="2026-06", clock=FakeClock())).dokumler
        await db.commit()
        assert Decimal(str(dokumler[0].gross_amount)) == Decimal("350.00")

    async def test_yol_ucreti_ziyaret_basina_eklenir(self, db, seeded, nokta_ac):
        n = await nokta_ac("Test Montaj")
        await self._is_emri(db, n, tutar=350, yol=25)
        dokumler = (await svc.donem_kapat(db, period="2026-06", clock=FakeClock())).dokumler
        await db.commit()
        # 350 hizmet + 25 km × 10 TL
        assert Decimal(str(dokumler[0].gross_amount)) == Decimal("600.00")

    async def test_tekrar_kapatma_kopya_satir_uretmez(self, db, seeded, nokta_ac):
        n = await nokta_ac("Test Montaj")
        await self._is_emri(db, n, tutar=350)
        await svc.donem_kapat(db, period="2026-06", clock=FakeClock())
        await db.commit()
        await svc.donem_kapat(db, period="2026-06", clock=FakeClock())
        await db.commit()
        satir = (await db.scalars(select(SettlementLine))).all()
        assert len(satir) == 1

    async def test_odenmis_donem_yeniden_kapatilmaz(self, db, seeded, nokta_ac):
        """Kapanmış dönem DEĞİŞMEZ; düzeltme sonraki döneme devreder."""
        n = await nokta_ac("Test Montaj")
        await self._is_emri(db, n, tutar=350)
        dokumler = (await svc.donem_kapat(db, period="2026-06", clock=FakeClock())).dokumler
        dokumler[0].status = "ODENDI"
        await db.commit()

        await self._is_emri(db, n, tutar=999)
        sonuc = await svc.donem_kapat(db, period="2026-06", clock=FakeClock())
        await db.commit()

        d = await db.scalar(select(PartnerSettlement))
        assert Decimal(str(d.gross_amount)) == Decimal("350.00"), "ödenmiş dönem değişti"
        # ...ama düşen kalem SESSİZCE ATILMAMALI: montaj noktası o işin
        # parasını alamayacak, bunu birinin görmesi gerekiyor.
        assert len(sonuc.kilitli_atlanan) == 1, "kilitli döneme düşen kalem raporlanmadı"
        assert sonuc.kilitli_atlanan[0]["tutar"] == 999.0

    async def test_kilitlenen_satirlar_isaretlenir(self, db, seeded, nokta_ac):
        n = await nokta_ac("Test Montaj")
        await self._is_emri(db, n, tutar=350)
        dokumler = (await svc.donem_kapat(db, period="2026-06", clock=FakeClock())).dokumler
        await svc.kilitle(db, dokumler[0], FakeClock())
        await db.commit()
        satir = await db.scalar(select(SettlementLine))
        assert satir.locked_at is not None


class TestDonemPaneli:
    """Panel, kaydı OLMAYAN dönemde de çalışmalı.

    Boş bir dizinin `sum()`'ı `Decimal` değil `int 0` döndürüyor ve kuruş
    yuvarlaması `int` üzerinde patlıyordu: ekip içinde bulunulan aya bakınca
    (henüz iş girilmemişken) hak ediş paneli 500 veriyordu. Projenin kritik
    yolundaki ekran, en sık açılacağı anda çöküyordu.
    """

    async def test_kayitsiz_donem_sifir_dondurur(self, db):
        panel = await svc.donem_paneli(db, "2099-01")
        assert panel["kalem"] == 0
        assert panel["genel_toplam"] == Decimal("0.00")
        assert panel["tutar"] == Decimal("0.00")
        assert panel["yol_tutari"] == Decimal("0.00")
        assert panel["noktalar"] == []
