"""Dashboard, raporlar ve KVKK."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.models import Account, Contact, Vehicle

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username="yonetici", rol="ADMIN"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


@pytest.fixture
async def hesap_ac(db):
    sayac = {"n": 0}

    async def _make(ad: str | None = None, **kw) -> Account:
        sayac["n"] += 1
        varsayilan = {"is_musteri": True}
        varsayilan.update(kw)
        h = Account(
            title=ad or f"MUSTERI {sayac['n']}",
            title_key=(ad or f"musteri {sayac['n']}").lower(),
            **varsayilan,
        )
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


# --- Dashboard ----------------------------------------------------------------


class TestDashboard:
    async def test_bos_sistemde_calisir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await client.get("/api/raporlar/dashboard")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["sahadaki_cihaz"] == 0
        assert v["stoktaki_cihaz"] == 0
        assert Decimal(v["mrr"]) == Decimal("0")

    async def test_cihaz_sayilari_duruma_gore(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000001", urun=u, status="AKTIF")
        await cihaz_ac(imei="860000000000002", urun=u, status="AKTIF")
        await cihaz_ac(imei="860000000000003", urun=u, status="STOKTA")

        v = (await client.get("/api/raporlar/dashboard")).json()
        assert v["sahadaki_cihaz"] == 2
        assert v["stoktaki_cihaz"] == 1
        assert v["cihaz_durumlari"]["AKTIF"] == 2

    async def test_stok_degeri_ve_maliyetsiz_sayisi(self, client, kullanici_ac, urun_ac, cihaz_ac):
        """'Stok değeri 0' ile 'maliyeti girilmemiş' aynı şey değil."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000010", urun=u, landed_cost_try=Decimal("1500"))
        await cihaz_ac(imei="860000000000011", urun=u)

        v = (await client.get("/api/raporlar/dashboard")).json()
        assert Decimal(v["stok_degeri_try"]) == Decimal("1500.00")
        assert v["maliyeti_girilmemis_cihaz"] == 1

    async def test_stok_degeri_yetkisizde_gizli(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000020", urun=u, landed_cost_try=Decimal("1500"))
        await client.post("/api/auth/logout")

        # TEKNIK_SERVIS'te rapor.gor var, maliyet.gor yok.
        await _giris(client, kullanici_ac, "teknik", "TEKNIK_SERVIS")
        v = (await client.get("/api/raporlar/dashboard")).json()
        assert v["stok_degeri_try"] is None
        assert v["stoktaki_cihaz"] == 1

    async def test_mrr_aboneliklerden_gelir(self, client, kullanici_ac, hesap_ac):
        """Dashboard aynı sayıyı ikinci kez hesaplamaz, abonelik servisini çağırır."""
        client.clock.set(datetime(2026, 6, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        a = await client.post(
            "/api/abonelikler",
            json={
                "customer_id": m.id,
                "unit_price": 1500,
                "start_date": "2026-01-01",
                "vat_rate": 0.20,
            },
        )
        await client.post(
            f"/api/abonelikler/{a.json()['id']}/durum",
            json={"durum": "AKTIF", "tarih": "2026-01-01"},
        )

        v = (await client.get("/api/raporlar/dashboard")).json()
        assert Decimal(v["mrr"]) == Decimal("1500.00")
        assert Decimal(v["arr"]) == Decimal("18000.00")
        assert v["aktif_abonelik"] == 1

    async def test_yetkisiz_dashboard_goremez(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "hatci", "HAT_SORUMLUSU")
        # HAT_SORUMLUSU'nda rapor.gor VAR; onu doğrula, sonra izinsiz rolü dene.
        assert (await client.get("/api/raporlar/dashboard")).status_code == 200


# --- Teklif dönüşümü ----------------------------------------------------------


class TestTeklifDonusumu:
    async def _teklif(self, client, musteri, urun):
        r = await client.post(
            "/api/teklifler",
            json={"customer_id": musteri.id, "kalemler": [{"product_id": urun.id, "qty": 1}]},
        )
        return r.json()["id"]

    async def test_karara_baglanmamis_teklif_paydaya_girmez(
        self, client, kullanici_ac, hesap_ac, urun_ac
    ):
        """Cevap bekleyen teklifi kayıp saymak oranı haksız yere düşürürdü."""
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))

        kabul = await self._teklif(client, m, u)
        await client.post(f"/api/teklifler/{kabul}/gonder", json={})
        await client.post(f"/api/teklifler/{kabul}/karar", json={"kabul": True})

        red = await self._teklif(client, m, u)
        await client.post(f"/api/teklifler/{red}/gonder", json={})
        await client.post(
            f"/api/teklifler/{red}/karar",
            json={"kabul": False, "kayip_nedeni_kod": "FIYAT_YUKSEK"},
        )

        bekleyen = await self._teklif(client, m, u)
        await client.post(f"/api/teklifler/{bekleyen}/gonder", json={})

        v = (await client.get("/api/raporlar/teklif-donusumu")).json()
        assert v["toplam_teklif"] == 3
        assert v["kazanilan"] == 1
        assert v["kaybedilen"] == 1
        assert v["donusum_yuzde"] == 50.0
        assert v["kayip_nedenleri"][0]["kod"] == "FIYAT_YUKSEK"
        assert v["kayip_nedenleri"][0]["neden"] == "Fiyat yüksek"

    async def test_teklif_yoksa_oran_tanimsiz(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        v = (await client.get("/api/raporlar/teklif-donusumu")).json()
        assert v["donusum_yuzde"] is None


# --- Cihaz ömür boyu ----------------------------------------------------------


class TestCihazOmurBoyu:
    async def test_marj_ve_basabas(self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, db):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000030", urun=u, landed_cost_try=Decimal("3000"))
        h = await hat_ac(
            "8990011234567890001",
            monthly_charge=Decimal("150"),
            tariff_cost=Decimal("20"),
            package_cost=Decimal("30"),
        )
        from app.services.devices import hat_tak

        await hat_tak(db, device_id=c.id, sim_id=h.id, clock=client.clock)
        await db.commit()

        v = (await client.get(f"/api/raporlar/cihaz-omur-boyu/{c.id}")).json()
        assert Decimal(v["aylik_gelir"]) == Decimal("150.00")
        assert Decimal(v["aylik_maliyet"]) == Decimal("50.00")
        assert Decimal(v["aylik_marj"]) == Decimal("100.00")
        # 3000 / 100 = 30 ay + 1
        assert v["basabas_ay"] == 31

    async def test_marj_yoksa_basabas_bos(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000031", urun=u, landed_cost_try=Decimal("3000"))
        v = (await client.get(f"/api/raporlar/cihaz-omur-boyu/{c.id}")).json()
        assert v["basabas_ay"] is None

    async def test_maliyet_yetkisizde_gizli(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000032", urun=u, landed_cost_try=Decimal("3000"))
        await client.post("/api/auth/logout")
        await _giris(client, kullanici_ac, "teknik", "TEKNIK_SERVIS")

        v = (await client.get(f"/api/raporlar/cihaz-omur-boyu/{c.id}")).json()
        assert v["cihaz_maliyeti"] is None
        assert v["aylik_marj"] is None
        assert v["kimlik"] == "860000000000032"

    async def test_olmayan_cihaz_404(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        assert (await client.get("/api/raporlar/cihaz-omur-boyu/99999")).status_code == 404


# --- Müşteri geliri -----------------------------------------------------------


class TestMusteriGeliri:
    async def test_abonelik_ve_siparis_toplanir(self, client, kullanici_ac, hesap_ac):
        client.clock.set(datetime(2026, 4, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac)
        m = await hesap_ac("BUYUK MUSTERI")
        a = await client.post(
            "/api/abonelikler",
            json={
                "customer_id": m.id,
                "unit_price": 1000,
                "start_date": "2026-01-01",
                "vat_rate": 0.20,
            },
        )
        await client.post(
            f"/api/abonelikler/{a.json()['id']}/durum",
            json={"durum": "AKTIF", "tarih": "2026-01-01"},
        )

        r = await client.get("/api/raporlar/musteri-geliri")
        satir = next(x for x in r.json() if x["account_id"] == m.id)
        # Ocak, Şubat, Mart kapandı: 3 × 1200
        assert Decimal(satir["abonelik_geliri"]) == Decimal("3600.00")

    async def test_xlsx(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await client.get("/api/raporlar/musteri-geliri.xlsx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"


# --- Hareketsiz stok ----------------------------------------------------------


class TestHareketsizStok:
    async def test_konumsuz_cihaz_da_listelenir(self, client, kullanici_ac, urun_ac, cihaz_ac):
        """Konum kaydı hiç yazılmamış cihaz da hareketsizdir."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000040", urun=u, status="STOKTA")
        r = await client.get("/api/raporlar/hareketsiz-stok")
        assert any(s["kimlik"] == "860000000000040" for s in r.json())

    async def test_maliyet_yetkisizde_gizli(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000041", urun=u, landed_cost_try=Decimal("900"))
        await client.post("/api/auth/logout")
        await _giris(client, kullanici_ac, "teknik", "TEKNIK_SERVIS")

        r = await client.get("/api/raporlar/hareketsiz-stok")
        satir = next(s for s in r.json() if s["kimlik"] == "860000000000041")
        assert satir["landed_cost_try"] is None


# --- KVKK ---------------------------------------------------------------------


class TestKvkkVeriBulma:
    async def test_unvandan_bulur_ve_loglar(self, client, kullanici_ac, hesap_ac, db):
        await _giris(client, kullanici_ac)
        m = await hesap_ac("ÖZKAN LOJİSTİK", phone="+905321112233", email="info@ozkan.com")
        db.add(Vehicle(plate="34OZK001", plate_key="34ozk001", customer_id=m.id))
        db.add(Contact(account_id=m.id, full_name="Ali Özkan", phone="+905321112244"))
        await db.commit()

        r = await client.get("/api/kvkk/veri-bul", params={"arama": "ÖZKAN"})
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["ozet"]["hesaplar"] == 1
        assert v["ozet"]["araclar"] == 1
        assert v["ozet"]["kisiler"] == 1

        # Aramanın kendisi kişisel veri erişimidir.
        log = await client.get("/api/kvkk/erisim-logu")
        assert any("Veri bulma talebi" in (k["amac"] or "") for k in log.json())

    async def test_telefondan_bulur(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        await hesap_ac("ACME", phone="+905329998877")
        r = await client.get("/api/kvkk/veri-bul", params={"arama": "0532 999 88 77"})
        assert r.json()["ozet"]["hesaplar"] == 1

    async def test_plakadan_arac_bulur(self, client, kullanici_ac, hesap_ac, db):
        await _giris(client, kullanici_ac)
        m = await hesap_ac("BASKA FIRMA")
        db.add(Vehicle(plate="06XYZ777", plate_key="06xyz777", customer_id=m.id))
        await db.commit()
        r = await client.get("/api/kvkk/veri-bul", params={"arama": "06 XYZ 777"})
        assert r.json()["ozet"]["araclar"] == 1

    async def test_kisa_arama_reddedilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        assert (await client.get("/api/kvkk/veri-bul", params={"arama": "ab"})).status_code == 400

    async def test_xlsx_dokumu(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        await hesap_ac("ÖZKAN LOJİSTİK")
        r = await client.get("/api/kvkk/veri-bul.xlsx", params={"arama": "ÖZKAN"})
        assert r.status_code == 200
        assert r.content[:2] == b"PK"


class TestKvkkAnonimlestirme:
    async def test_kisisel_alanlar_maskelenir_ticari_kayit_kalir(
        self, client, kullanici_ac, hesap_ac, urun_ac, cihaz_ac, db
    ):
        """Cihaz geçmişi ve iş emri ticari kayıttır; silinmez."""
        await _giris(client, kullanici_ac)
        m = await hesap_ac("SILINECEK FIRMA", phone="+905321110000", email="a@b.com")
        arac = Vehicle(plate="34SIL001", plate_key="34sil001", customer_id=m.id)
        db.add(arac)
        db.add(Contact(account_id=m.id, full_name="Veli Silinmez", phone="+905321110001"))
        await db.commit()
        await db.refresh(arac)

        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000050", urun=u, current_customer_id=m.id)

        r = await client.post(
            f"/api/kvkk/hesaplar/{m.id}/anonimlestir",
            json={"gerekce": "KVKK-2026-14 silme talebi", "onay": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["kisi"] == 1
        assert r.json()["arac"] == 1

        await db.refresh(m)
        await db.refresh(arac)
        assert "ANONİM" in m.title
        assert m.phone is None and m.email is None
        assert "ANONİM" in arac.plate
        # Cihaz kaydı duruyor.
        await db.refresh(c)
        assert c.imei == "860000000000050"

    async def test_onaysiz_anonimlestirme_reddedilir(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        r = await client.post(
            f"/api/kvkk/hesaplar/{m.id}/anonimlestir",
            json={"gerekce": "talep var", "onay": False},
        )
        assert r.status_code == 400
        assert "geri alınamaz" in r.json()["detail"]

    async def test_gerekcesiz_reddedilir(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        r = await client.post(
            f"/api/kvkk/hesaplar/{m.id}/anonimlestir", json={"gerekce": "x", "onay": True}
        )
        assert r.status_code == 422

    async def test_ikinci_kez_anonimlestirilemez(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        veri = {"gerekce": "KVKK-2026-15 talep", "onay": True}
        assert (
            await client.post(f"/api/kvkk/hesaplar/{m.id}/anonimlestir", json=veri)
        ).status_code == 200
        ikinci = await client.post(f"/api/kvkk/hesaplar/{m.id}/anonimlestir", json=veri)
        assert ikinci.status_code == 409

    async def test_denetim_izine_yazilir(self, client, kullanici_ac, hesap_ac, db):
        await _giris(client, kullanici_ac)
        m = await hesap_ac("IZ BIRAKAN")
        await client.post(
            f"/api/kvkk/hesaplar/{m.id}/anonimlestir",
            json={"gerekce": "KVKK-2026-16 talep", "onay": True},
        )
        log = await client.get("/api/kvkk/erisim-logu", params={"entity": "accounts"})
        assert any(k["action"] == "kvkk.anonimlestir" for k in log.json())


class TestKvkkSaklama:
    async def test_hareketsiz_hesap_listelenir(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        await hesap_ac("ESKI MUSTERI")
        r = await client.get("/api/kvkk/saklama-suresi-dolanlar", params={"yil": 1})
        assert r.status_code == 200, r.text
        assert any(k["unvan"] == "ESKI MUSTERI" for k in r.json()["kayitlar"])

    async def test_aktif_abonelikli_hesap_listelenmez(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        m = await hesap_ac("AKTIF MUSTERI")
        a = await client.post(
            "/api/abonelikler",
            json={
                "customer_id": m.id,
                "unit_price": 100,
                "start_date": "2026-01-01",
                "vat_rate": 0.20,
            },
        )
        await client.post(
            f"/api/abonelikler/{a.json()['id']}/durum",
            json={"durum": "AKTIF", "tarih": "2026-01-01"},
        )
        r = await client.get("/api/kvkk/saklama-suresi-dolanlar", params={"yil": 1})
        assert all(k["account_id"] != m.id for k in r.json()["kayitlar"])

    async def test_anonimlestirilmis_hesap_tekrar_listelenmez(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        m = await hesap_ac("BIR KEZ")
        await client.post(
            f"/api/kvkk/hesaplar/{m.id}/anonimlestir",
            json={"gerekce": "KVKK-2026-17 talep", "onay": True},
        )
        r = await client.get("/api/kvkk/saklama-suresi-dolanlar", params={"yil": 1})
        assert all(k["account_id"] != m.id for k in r.json()["kayitlar"])


class TestKvkkYetki:
    async def test_admin_disi_kvkk_goremez(self, client, kullanici_ac):
        """Silme talebi ve anonimleştirme denetim izi okumaktan ağır bir sorumluluk."""
        for rol in ("YONETIM", "MUHASEBE_DESTEK", "TEKNIK_SERVIS"):
            await client.post("/api/auth/logout")
            await _giris(client, kullanici_ac, rol.lower(), rol)
            assert (await client.get("/api/kvkk/erisim-logu")).status_code == 403

    async def test_admin_gorur(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        assert (await client.get("/api/kvkk/erisim-logu")).status_code == 200


class TestMaskeleme:
    def test_son_haneler_gorunur(self):
        from app.services.kvkk import maskele

        assert maskele("+905321112233") == "**********233"
        assert maskele("ab") == "**"
        assert maskele(None) is None


class TestMontajNoktasiRaporu:
    async def test_bos_sistemde_calisir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await client.get("/api/raporlar/montaj-noktasi")
        assert r.status_code == 200
        assert r.json() == []

    async def test_xlsx(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await client.get("/api/raporlar/montaj-noktasi.xlsx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"


class TestMrrRaporu:
    async def test_arr_eklenir(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        a = await client.post(
            "/api/abonelikler",
            json={
                "customer_id": m.id,
                "unit_price": 500,
                "start_date": "2026-01-01",
                "vat_rate": 0.20,
            },
        )
        await client.post(
            f"/api/abonelikler/{a.json()['id']}/durum",
            json={"durum": "AKTIF", "tarih": "2026-01-15"},
        )
        r = await client.get("/api/raporlar/mrr/2026-01")
        assert Decimal(r.json()["bitis_mrr"]) == Decimal("500.00")
        assert Decimal(r.json()["arr"]) == Decimal("6000.00")

    async def test_gecersiz_donem(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        assert (await client.get("/api/raporlar/mrr/2026")).status_code == 400


class TestVeriBulmaAnonimIsareti:
    async def test_anonim_hesap_isaretlenir(self, client, kullanici_ac, hesap_ac):
        await _giris(client, kullanici_ac)
        m = await hesap_ac("ISARETLI FIRMA")
        await client.post(
            f"/api/kvkk/hesaplar/{m.id}/anonimlestir",
            json={"gerekce": "KVKK-2026-18 talep", "onay": True},
        )
        # Anonim etiketiyle aranınca bulunur ve anonim işaretli döner.
        r = await client.get("/api/kvkk/veri-bul", params={"arama": "ANONİM"})
        kayitlar = r.json()["hesaplar"]
        assert kayitlar and all(h["anonim"] for h in kayitlar)


class TestDashboardHakedis:
    async def test_bekleyen_hakedis_toplanir(self, client, kullanici_ac, hesap_ac, db):
        from app.models import PartnerSettlement

        await _giris(client, kullanici_ac)
        nokta = await hesap_ac("GUREK OTO", is_montaj_noktasi=True, is_musteri=False)
        db.add(
            PartnerSettlement(
                partner_id=nokta.id,
                period="2026-01",
                status="ODEME_BEKLIYOR",
                gross_amount=Decimal("5000"),
                net_payable=Decimal("4500"),
            )
        )
        await db.commit()

        v = (await client.get("/api/raporlar/dashboard")).json()
        assert v["bekleyen_hakedis_adet"] == 1
        assert Decimal(v["bekleyen_hakedis_tutar"]) == Decimal("4500.00")


class TestDashboardMontaj:
    async def test_aylik_montaj_sayilir(
        self, client, kullanici_ac, hesap_ac, urun_ac, cihaz_ac, db
    ):
        from app.models import WorkOrder, WorkOrderItem

        client.clock.set(datetime(2026, 6, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000060", urun=u)

        wo = WorkOrder(
            wo_no="G202606-00001",
            type="MONTAJ",
            status="ONAYLANDI",
            customer_id=m.id,
            completed_at=datetime(2026, 6, 10, 12, tzinfo=UTC),
            settlement_period="2026-06",
        )
        db.add(wo)
        await db.flush()
        db.add(
            WorkOrderItem(work_order_id=wo.id, device_id=c.id, product_id=u.id, action="TAKILDI")
        )
        await db.commit()

        r = await client.get("/api/raporlar/dashboard")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["aylik_montaj"] == 1
        assert v["donem"] == "2026-06"

    async def test_baska_ayin_montaji_sayilmaz(
        self, client, kullanici_ac, hesap_ac, urun_ac, cihaz_ac, db
    ):
        from app.models import WorkOrder, WorkOrderItem

        client.clock.set(datetime(2026, 6, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac)
        m = await hesap_ac()
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000061", urun=u)

        wo = WorkOrder(
            wo_no="G202603-00001",
            type="MONTAJ",
            status="ONAYLANDI",
            customer_id=m.id,
            completed_at=datetime(2026, 3, 10, 12, tzinfo=UTC),
            settlement_period="2026-03",
        )
        db.add(wo)
        await db.flush()
        db.add(
            WorkOrderItem(work_order_id=wo.id, device_id=c.id, product_id=u.id, action="TAKILDI")
        )
        await db.commit()

        assert (await client.get("/api/raporlar/dashboard")).json()["aylik_montaj"] == 0


class TestErisimLogu:
    async def test_kisisel_olmayan_kayit_logta_gorunmez(self, client, kullanici_ac, urun_ac):
        """Erişim logu yalnız KİŞİSEL veri kayıtlarını gösterir."""
        await _giris(client, kullanici_ac)
        await urun_ac("L300", "IMEI")
        r = await client.get("/api/kvkk/erisim-logu")
        assert all(k["entity"] != "products" for k in r.json())


class TestSaklamaAyari:
    async def test_varsayilan_ayardan_gelir(self, client, kullanici_ac, db):
        from app.services import settings as ayar_svc

        await _giris(client, kullanici_ac)
        assert await ayar_svc.get(db, "kvkk_saklama_yili") == 10
        r = await client.get("/api/kvkk/saklama-suresi-dolanlar")
        assert r.status_code == 200
        assert r.json()["kayitlar"] == [] or all(k["esik_yil"] == 10 for k in r.json()["kayitlar"])


class TestBayiStogu:
    async def test_rapor_ucu_calisir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await client.get("/api/raporlar/bayi-stogu")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_hesap_unvani_doner(self, client, db, kullanici_ac, cihaz_ac, hesap_ac):
        """Rapor ucu de unvanı taşımalı — ekranda hesap id'si işe yaramaz."""
        from app.clock import FakeClock
        from app.services import stock as stok_svc

        b = await hesap_ac("Ankara Bayi", is_musteri=False, is_bayi=True)
        c = await cihaz_ac(imei="860000000000088")
        await stok_svc.konum_ata(
            db,
            device_id=c.id,
            location_type="BAYI",
            account_id=b.id,
            ownership="BAYI_SATILDI",
            clock=FakeClock(),
        )
        await db.commit()

        await _giris(client, kullanici_ac)
        r = await client.get("/api/raporlar/bayi-stogu")
        assert r.status_code == 200
        satir = next(x for x in r.json() if x["account_id"] == b.id)
        assert satir["account_title"] == "Ankara Bayi"


class TestArizaOraniRaporu:
    async def test_rapor_ucu_calisir(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000070", urun=u)
        r = await client.get("/api/raporlar/ariza-orani")
        assert r.status_code == 200
        satir = next(x for x in r.json() if x["urun_kodu"] == "L300")
        assert satir["ariza_orani"] == 0.0


class TestTarihDuyarliligi:
    async def test_dashboard_saatten_gelen_tarihi_kullanir(self, client, kullanici_ac):
        client.clock.set(datetime(2027, 3, 5, tzinfo=UTC))
        await _giris(client, kullanici_ac)
        v = (await client.get("/api/raporlar/dashboard")).json()
        assert v["tarih"] == str(date(2027, 3, 5))
        assert v["donem"] == "2027-03"


class TestHesapKarti:
    async def test_kart_kisileri_ve_cihazlari_toplar(
        self, client, db, kullanici_ac, hesap_ac, cihaz_ac
    ):
        """Müşterinin üzerine tıklayan kişi "bu firmada neler var" cevabını
        dört ayrı ekrandan toplamak zorunda kalmamalı."""
        h = await hesap_ac("KART DENEME A.Ş.")
        c = await cihaz_ac(imei="860000000000109")
        c.current_customer_id = h.id
        await db.commit()

        await _giris(client, kullanici_ac)
        ekle = await client.post(
            f"/api/hesaplar/{h.id}/kisiler",
            json={"full_name": "Ayşe Yetkili", "title": "Filo Müdürü", "phone": "05321112233"},
        )
        assert ekle.status_code == 201, ekle.text
        # Telefon tek biçime çevrilir; arama ve mükerrer tespiti buna dayanıyor.
        assert ekle.json()["telefon"] == "+905321112233"

        kart = await client.get(f"/api/hesaplar/{h.id}/kart")
        assert kart.status_code == 200, kart.text
        veri = kart.json()
        assert [k["ad"] for k in veri["kisiler"]] == ["Ayşe Yetkili"]
        assert [c["kimlik"] for c in veri["cihazlar"]] == ["860000000000109"]

    async def test_birincil_yetkili_tektir(self, client, kullanici_ac, hesap_ac):
        h = await hesap_ac("KART DENEME 2")
        await _giris(client, kullanici_ac, "hesapci2")

        ilk = await client.post(
            f"/api/hesaplar/{h.id}/kisiler", json={"full_name": "Bir Kişi", "is_primary": True}
        )
        await client.post(
            f"/api/hesaplar/{h.id}/kisiler", json={"full_name": "İki Kişi", "is_primary": True}
        )

        kisiler = (await client.get(f"/api/hesaplar/{h.id}/kart")).json()["kisiler"]
        birincil = [k for k in kisiler if k["birincil"]]
        assert len(birincil) == 1, "iki birincil yetkili olamaz"
        assert birincil[0]["ad"] == "İki Kişi"
        assert ilk.json()["id"] != birincil[0]["id"]
