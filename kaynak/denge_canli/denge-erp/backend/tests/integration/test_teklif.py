"""Teklif: versiyonlama, iskonto onayı, süre, online kabul."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.clock import FakeClock
from app.models import Account, Quote, QuoteLine, QuoteVersion
from app.services import quotes as svc

pytestmark = pytest.mark.integration


@pytest.fixture
async def musteri_ac(db):
    async def _make(ad: str = "Test Müşteri", email: str | None = "musteri@ornek.com") -> Account:
        h = Account(title=ad, is_musteri=True, email=email)
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


async def _giris(client, kullanici_ac, username="satisci", rol="SATIS"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


class TestHesaplama:
    async def test_kalem_bazinda_iskonto_ve_kdv(self, client, kullanici_ac, musteri_ac, urun_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {"product_id": u.id, "qty": 2, "discount_pct": 10},
                    {
                        "item_type": "HIZMET",
                        "description": "Montaj",
                        "qty": 2,
                        "unit_price": 350,
                        "vat_rate": 0.20,
                    },
                ],
            },
        )
        assert r.status_code == 201, r.text
        v = r.json()["guncel"]
        # 2×1000 = 2000 brüt, %10 iskonto → 1800; montaj 700. Ara toplam 2700.
        assert Decimal(v["subtotal"]) == Decimal("2700.00")
        assert Decimal(v["discount_total"]) == Decimal("200.00")
        assert Decimal(v["vat_total"]) == Decimal("500.00")
        assert Decimal(v["grand_total"]) == Decimal("3000.00")

    async def test_kdv_kalem_bazinda_farkli_olabilir(self, client, kullanici_ac, musteri_ac):
        """Tek genel oran uygulamak farklı KDV'li kalemleri bozardı."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {
                        "item_type": "SERBEST",
                        "description": "A",
                        "qty": 1,
                        "unit_price": 100,
                        "vat_rate": 0.20,
                    },
                    {
                        "item_type": "SERBEST",
                        "description": "B",
                        "qty": 1,
                        "unit_price": 100,
                        "vat_rate": 0.01,
                    },
                ],
            },
        )
        assert Decimal(r.json()["guncel"]["vat_total"]) == Decimal("21.00")

    async def test_urunsuz_kalemde_aciklama_zorunlu(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={"customer_id": m.id, "kalemler": [{"item_type": "SERBEST", "qty": 1}]},
        )
        assert r.status_code == 400


class TestVersiyonlama:
    async def test_revizyon_yeni_versiyon_acar_eskisini_kilitler(
        self, client, kullanici_ac, musteri_ac, db
    ):
        """Müşteriye gönderilen belge sonradan değişmemeli."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 1000}
                ],
            },
        )
        teklif_id = r.json()["id"]
        ilk_versiyon_id = r.json()["guncel"]["id"]

        rev = await client.post(
            f"/api/teklifler/{teklif_id}/revize",
            json={
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 900}
                ]
            },
        )
        assert rev.status_code == 200
        assert rev.json()["guncel"]["version_no"] == 2
        assert rev.json()["versiyon_sayisi"] == 2
        assert Decimal(rev.json()["guncel"]["subtotal"]) == Decimal("900.00")

        eski = await db.get(QuoteVersion, ilk_versiyon_id)
        await db.refresh(eski)
        assert eski.is_locked is True, "eski versiyon kilitlenmedi"
        assert Decimal(str(eski.subtotal)) == Decimal("1000.00"), "eski versiyon değişti"

    async def test_kabul_edilmis_teklif_revize_edilemez(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 100}
                ],
            },
        )
        tid = r.json()["id"]
        await client.post(f"/api/teklifler/{tid}/karar", json={"kabul": True})
        rev = await client.post(
            f"/api/teklifler/{tid}/revize",
            json={
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 90}
                ]
            },
        )
        assert rev.status_code == 409

    async def test_revizyon_kaynak_fiyatlari_tasir(
        self, client, kullanici_ac, musteri_ac, urun_ac, db
    ):
        """Revizyonda ürün kartındaki GÜNCEL fiyat değil, müşteriye gösterilen
        fiyat esastır."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        r = await client.post(
            "/api/teklifler",
            json={"customer_id": m.id, "kalemler": [{"product_id": u.id, "qty": 1}]},
        )
        tid = r.json()["id"]

        # Ürün fiyatı sonradan değişiyor
        u.list_price = Decimal("2500")
        await db.commit()

        t = await db.get(Quote, tid)
        onceki = await db.get(QuoteVersion, t.current_version_id)
        yeni = await svc.yeni_versiyon(db, t, clock=FakeClock(), kaynak=onceki)
        await db.commit()
        kalem = await db.scalar(select(QuoteLine).where(QuoteLine.version_id == yeni.id))
        assert Decimal(str(kalem.unit_price)) == Decimal("1000.00")


class TestIskontoOnayi:
    async def test_esik_ustu_iskonto_gonderimi_engeller(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {
                        "item_type": "SERBEST",
                        "description": "A",
                        "qty": 1,
                        "unit_price": 1000,
                        "discount_pct": 25,  # varsayılan eşik %10
                    }
                ],
            },
        )
        assert r.json()["onay_gerekiyor"] is True
        gonder = await client.post(f"/api/teklifler/{r.json()['id']}/gonder", json={})
        assert gonder.status_code == 409
        assert "onay eşiğini aşıyor" in gonder.json()["detail"]

    async def test_satis_temsilcisi_kendi_iskontosunu_onaylayamaz(
        self, client, kullanici_ac, musteri_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {
                        "item_type": "SERBEST",
                        "description": "A",
                        "qty": 1,
                        "unit_price": 1000,
                        "discount_pct": 25,
                    }
                ],
            },
        )
        onay = await client.post(f"/api/teklifler/{r.json()['id']}/iskonto-onayla")
        assert onay.status_code == 403, "satış temsilcisinde iskonto onay izni olmamalı"

    async def test_satis_muduru_onaylar(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {
                        "item_type": "SERBEST",
                        "description": "A",
                        "qty": 1,
                        "unit_price": 1000,
                        "discount_pct": 25,
                    }
                ],
            },
        )
        onay = await client.post(f"/api/teklifler/{r.json()['id']}/iskonto-onayla")
        assert onay.status_code == 200
        assert onay.json()["onay_gerekiyor"] is False


class TestKapsam:
    async def test_satis_temsilcisi_baskasinin_teklifini_goremez(
        self, client, kullanici_ac, musteri_ac
    ):
        await _giris(client, kullanici_ac, "satisci1", "SATIS")
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 100}
                ],
            },
        )
        tid = r.json()["id"]
        await client.post("/api/auth/logout")

        await _giris(client, kullanici_ac, "satisci2", "SATIS")
        assert (await client.get(f"/api/teklifler/{tid}")).status_code == 404
        assert (await client.get("/api/teklifler")).json() == []


class TestSureDolmasi:
    async def test_gecerliligi_gecen_teklif_isaretlenir(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 100}
                ],
            },
        )
        t = await db.get(Quote, r.json()["id"])
        t.status = "GONDERILDI"
        v = await db.get(QuoteVersion, t.current_version_id)
        saat = FakeClock()
        v.valid_until = saat.now().date() - timedelta(days=1)
        await db.commit()

        adet = await svc.suresi_dolanlari_isaretle(db, saat)
        await db.commit()
        await db.refresh(t)
        assert adet == 1
        assert t.status == "SURESI_DOLDU"

    async def test_kabul_edilmis_teklif_suresi_dolmaz(self, client, kullanici_ac, musteri_ac, db):
        """Tamamlanmış işi geçersiz göstermek olurdu."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 100}
                ],
            },
        )
        tid = r.json()["id"]
        await client.post(f"/api/teklifler/{tid}/karar", json={"kabul": True})
        t = await db.get(Quote, tid)
        v = await db.get(QuoteVersion, t.current_version_id)
        saat = FakeClock()
        v.valid_until = saat.now().date() - timedelta(days=1)
        await db.commit()

        await svc.suresi_dolanlari_isaretle(db, saat)
        await db.commit()
        await db.refresh(t)
        assert t.status == "KABUL"


class TestOnlineKabul:
    async def _gonderilmis_teklif(self, client, db, musteri_ac, kullanici_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {
                        "item_type": "SERBEST",
                        "description": "Araç takip",
                        "qty": 3,
                        "unit_price": 1000,
                    }
                ],
            },
        )
        t = await db.get(Quote, r.json()["id"])
        v = await db.get(QuoteVersion, t.current_version_id)
        # Gönderimi taklit et (SMTP yok)
        v.sent_at = FakeClock().now()
        t.status = "GONDERILDI"
        await db.commit()
        return t, v

    async def test_gecersiz_jeton_404(self, client, seeded):
        r = await client.get("/api/public/teklif/" + "x" * 24)
        assert r.status_code == 404

    async def test_goruntuleme_kaydedilir(self, client, db, musteri_ac, kullanici_ac):
        t, v = await self._gonderilmis_teklif(client, db, musteri_ac, kullanici_ac)
        r = await client.get(f"/api/public/teklif/{v.public_token}")
        assert r.status_code == 200
        assert r.json()["quote_no"] == t.quote_no
        assert r.json()["karar_verilebilir"] is True

        await db.refresh(v)
        await db.refresh(t)
        assert v.viewed_at is not None
        assert t.status == "GORUNTULENDI"

    async def test_acik_uc_ic_bilgi_sizdirmaz(self, client, db, musteri_ac, kullanici_ac):
        """Maliyet, iç not, teklif sahibi gibi alanlar müşteriye gitmemeli."""
        _, v = await self._gonderilmis_teklif(client, db, musteri_ac, kullanici_ac)
        govde = (await client.get(f"/api/public/teklif/{v.public_token}")).json()
        yasak = {"owner_id", "created_by", "notes", "cost", "landed_cost_try", "public_token"}
        assert not (set(govde) & yasak)

    async def test_musteri_kabul_edebilir(self, client, db, musteri_ac, kullanici_ac):
        t, v = await self._gonderilmis_teklif(client, db, musteri_ac, kullanici_ac)
        r = await client.post(f"/api/public/teklif/{v.public_token}/karar", json={"kabul": True})
        assert r.status_code == 200
        await db.refresh(t)
        await db.refresh(v)
        assert t.status == "KABUL"
        assert v.decision_channel == "LINK", "kararın hangi kanaldan geldiği kaydedilmeli"
        assert v.is_locked is True

    async def test_iki_kez_karar_verilemez(self, client, db, musteri_ac, kullanici_ac):
        _, v = await self._gonderilmis_teklif(client, db, musteri_ac, kullanici_ac)
        await client.post(f"/api/public/teklif/{v.public_token}/karar", json={"kabul": True})
        ikinci = await client.post(
            f"/api/public/teklif/{v.public_token}/karar", json={"kabul": False, "red_nedeni": "x"}
        )
        assert ikinci.status_code == 409

    async def test_red_nedeni_zorunlu(self, client, db, musteri_ac, kullanici_ac):
        _, v = await self._gonderilmis_teklif(client, db, musteri_ac, kullanici_ac)
        r = await client.post(f"/api/public/teklif/{v.public_token}/karar", json={"kabul": False})
        assert r.status_code == 400

    async def test_gonderilmemis_teklif_karar_kabul_etmez(
        self, client, db, musteri_ac, kullanici_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/teklifler",
            json={
                "customer_id": m.id,
                "kalemler": [
                    {"item_type": "SERBEST", "description": "A", "qty": 1, "unit_price": 100}
                ],
            },
        )
        t = await db.get(Quote, r.json()["id"])
        v = await db.get(QuoteVersion, t.current_version_id)
        karar = await client.post(
            f"/api/public/teklif/{v.public_token}/karar", json={"kabul": True}
        )
        assert karar.status_code == 409
