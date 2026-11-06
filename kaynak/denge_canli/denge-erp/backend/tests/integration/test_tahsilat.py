"""Tahsilat, hesap bakiyesi, gecikme takibi ve toplu fiyat güncelleme."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Account, SubscriptionEvent, SubscriptionPrice
from app.services import pricing as zam_svc

pytestmark = pytest.mark.integration


@pytest.fixture
async def musteri_ac(db):
    sayac = {"n": 0}

    async def _make(ad: str | None = None, email: str | None = "musteri@ornek.com") -> Account:
        sayac["n"] += 1
        h = Account(title=ad or f"Tahsilat Müşterisi {sayac['n']}", is_musteri=True, email=email)
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


async def _giris(client, kullanici_ac, username="muhasebe", rol="MUHASEBE_DESTEK"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


async def _abonelik(client, musteri, **kw):
    veri = {
        "customer_id": musteri.id,
        "title": "Platform",
        "billing_period": "AYLIK",
        "vat_rate": 0.20,
        "unit_price": 1000,
        "start_date": "2026-01-01",
    }
    veri.update(kw)
    r = await client.post("/api/abonelikler", json=veri)
    assert r.status_code == 201, r.text
    a = r.json()
    d = await client.post(
        f"/api/abonelikler/{a['id']}/durum",
        json={"durum": "AKTIF", "tarih": veri["start_date"]},
    )
    assert d.status_code == 200, d.text
    return a


# --- Saf hesap ----------------------------------------------------------------


class TestYeniFiyat:
    def test_yuzde_zam(self):
        assert zam_svc.yeni_fiyat(Decimal("1000"), yontem="YUZDE", deger=Decimal("25")) == Decimal(
            "1250.00"
        )

    def test_tutar_zam(self):
        assert zam_svc.yeni_fiyat(Decimal("1000"), yontem="TUTAR", deger=Decimal("150")) == Decimal(
            "1150.00"
        )

    def test_sabit_fiyat(self):
        assert zam_svc.yeni_fiyat(
            Decimal("1000"), yontem="SABIT", deger=Decimal("1750")
        ) == Decimal("1750.00")

    def test_tam_tl_yuvarlama(self):
        """Zam listesi ekipçe okunacak; kuruşlu tutar okunaksız olur."""
        assert zam_svc.yeni_fiyat(
            Decimal("333"), yontem="YUZDE", deger=Decimal("17"), yuvarlama=Decimal("1")
        ) == Decimal("390")

    def test_kurus_yuvarlama(self):
        assert zam_svc.yeni_fiyat(
            Decimal("333"), yontem="YUZDE", deger=Decimal("17"), yuvarlama=Decimal("0.01")
        ) == Decimal("389.61")

    def test_indirim_de_yapilabilir(self):
        assert zam_svc.yeni_fiyat(Decimal("1000"), yontem="YUZDE", deger=Decimal("-10")) == Decimal(
            "900.00"
        )

    def test_negatif_ucret_reddedilir(self):
        with pytest.raises(zam_svc.ZamHatasi):
            zam_svc.yeni_fiyat(Decimal("100"), yontem="TUTAR", deger=Decimal("-200"))

    def test_gecersiz_yontem(self):
        with pytest.raises(zam_svc.ZamHatasi):
            zam_svc.yeni_fiyat(Decimal("100"), yontem="CARPAN", deger=Decimal("2"))


# --- Tahsilat ve bakiye -------------------------------------------------------


class TestTahsilat:
    async def test_kayit_ve_listeleme(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/tahsilat",
            json={
                "account_id": m.id,
                "direction": "GELEN",
                "amount": 5000,
                "paid_at": "2026-02-10",
                "method": "HAVALE",
                "reference": "DEK-001",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["account_title"] == m.title

        liste = await client.get("/api/tahsilat", params={"hesap_id": m.id})
        assert len(liste.json()) == 1

    async def test_sifir_tutar_reddedilir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/tahsilat",
            json={"account_id": m.id, "amount": 0, "paid_at": "2026-02-10"},
        )
        assert r.status_code == 400

    async def test_gecersiz_yontem_reddedilir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/tahsilat",
            json={
                "account_id": m.id,
                "amount": 100,
                "paid_at": "2026-02-10",
                "method": "BITCOIN",
            },
        )
        assert r.status_code == 400

    async def test_silme_denetim_izine_yazilir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        m = await musteri_ac()
        r = await client.post(
            "/api/tahsilat",
            json={
                "account_id": m.id,
                "amount": 100,
                "paid_at": "2026-02-10",
                "reference": "DEK-SIL",
            },
        )
        tid = r.json()["id"]
        assert (await client.delete(f"/api/tahsilat/{tid}")).status_code == 204

        izler = await client.get("/api/denetim", params={"entity": "payments"})
        eylemler = [x["action"] for x in izler.json()]
        assert "sil" in eylemler


class TestBakiye:
    async def test_abonelik_tahakkuku_kapanmis_donemlerden(self, client, kullanici_ac, musteri_ac):
        """İçinde bulunulan ay henüz tamamlanmadığı için sayılmaz."""
        client.clock.set(datetime(2026, 4, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        m = await musteri_ac()
        await _abonelik(client, m)  # 1000 + KDV = 1200/ay

        r = await client.get(f"/api/tahsilat/bakiye/{m.id}")
        veri = r.json()
        # Ocak, Şubat, Mart kapandı; Nisan devam ediyor → 3 × 1200
        assert Decimal(veri["abonelik_tahakkuk"]) == Decimal("3600.00")
        assert Decimal(veri["musteri_bakiye"]) == Decimal("3600.00")

    async def test_tahsilat_bakiyeyi_dusurur(self, client, kullanici_ac, musteri_ac):
        client.clock.set(datetime(2026, 4, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        m = await musteri_ac()
        await _abonelik(client, m)
        await client.post(
            "/api/tahsilat",
            json={"account_id": m.id, "amount": 2400, "paid_at": "2026-03-01"},
        )

        r = await client.get(f"/api/tahsilat/bakiye/{m.id}")
        veri = r.json()
        assert Decimal(veri["tahsil_edilen"]) == Decimal("2400.00")
        assert Decimal(veri["musteri_bakiye"]) == Decimal("1200.00")
        assert veri["son_tahsilat"] == "2026-03-01"

    async def test_olmayan_hesap_404(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        assert (await client.get("/api/tahsilat/bakiye/999999")).status_code == 404


class TestGecikenler:
    async def test_hic_odemeyen_musteri_listelenir(self, client, kullanici_ac, musteri_ac):
        client.clock.set(datetime(2026, 4, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        m = await musteri_ac()
        a = await _abonelik(client, m)

        r = await client.get("/api/tahsilat/gecikenler")
        assert r.status_code == 200, r.text
        satir = next(x for x in r.json() if x["account_id"] == m.id)
        assert satir["gecen_gun"] is None  # hiç tahsilat yok
        assert satir["aktif_abonelik"] == 1
        assert satir["askiya_alma_onerilen"][0]["no"] == a["subscription_no"]

    async def test_yeni_odeyen_musteri_listelenmez(self, client, kullanici_ac, musteri_ac):
        client.clock.set(datetime(2026, 4, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        m = await musteri_ac()
        await _abonelik(client, m)
        await client.post(
            "/api/tahsilat",
            json={"account_id": m.id, "amount": 1000, "paid_at": "2026-04-10"},
        )

        r = await client.get("/api/tahsilat/gecikenler", params={"gun": 30})
        assert all(x["account_id"] != m.id for x in r.json())

    async def test_borcu_kapanan_musteri_listelenmez(self, client, kullanici_ac, musteri_ac):
        client.clock.set(datetime(2026, 4, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        m = await musteri_ac()
        await _abonelik(client, m)
        await client.post(
            "/api/tahsilat",
            json={"account_id": m.id, "amount": 3600, "paid_at": "2026-01-05"},
        )

        r = await client.get("/api/tahsilat/gecikenler", params={"gun": 30})
        assert all(x["account_id"] != m.id for x in r.json())

    async def test_askiya_alma_otomatik_yapilmaz(self, client, kullanici_ac, musteri_ac):
        """Öneri listesi abonelik durumunu DEĞİŞTİRMEZ."""
        client.clock.set(datetime(2026, 4, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac, "yonetici", "ADMIN")
        m = await musteri_ac()
        a = await _abonelik(client, m)
        await client.get("/api/tahsilat/gecikenler")

        durum = await client.get(f"/api/abonelikler/{a['id']}")
        assert durum.json()["status"] == "AKTIF"


# --- Toplu zam ----------------------------------------------------------------


class TestTopluZamOnizleme:
    async def test_onizleme_hicbir_sey_yazmaz(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        a = await _abonelik(client, m)

        r = await client.post(
            "/api/toplu-zam/onizle",
            json={
                "title": "2027 zammı",
                "method": "YUZDE",
                "value": 25,
                "valid_from": "2027-01-01",
            },
        )
        assert r.status_code == 200, r.text
        veri = r.json()
        assert veri["etkilenen_sayisi"] == 1
        assert Decimal(veri["etkilenen"][0]["eski_fiyat"]) == Decimal("1000.00")
        assert Decimal(veri["etkilenen"][0]["yeni_fiyat"]) == Decimal("1250.00")

        fiyatlar = (
            await db.scalars(
                select(SubscriptionPrice).where(SubscriptionPrice.subscription_id == a["id"])
            )
        ).all()
        assert len(fiyatlar) == 1  # hiçbir şey yazılmadı

    async def test_taahhutlu_sozlesme_haric_tutulur(self, client, kullanici_ac, musteri_ac):
        """%89 indirim taahhüde bağlı; süresi içinde bozulamaz."""
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m1 = await musteri_ac()
        m2 = await musteri_ac()
        await _abonelik(client, m1)
        await _abonelik(client, m2, commitment_end_date="2027-06-30")

        r = await client.post(
            "/api/toplu-zam/onizle",
            json={
                "title": "Zam denemesi",
                "method": "YUZDE",
                "value": 25,
                "valid_from": "2027-01-01",
            },
        )
        veri = r.json()
        assert veri["etkilenen_sayisi"] == 1
        assert veri["haric_sayisi"] == 1
        assert "Taahhüt" in veri["haric"][0]["neden"]

    async def test_taahhut_bitince_zam_kapsama_girer(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m, commitment_end_date="2026-12-31")

        r = await client.post(
            "/api/toplu-zam/onizle",
            json={
                "title": "Zam denemesi",
                "method": "YUZDE",
                "value": 25,
                "valid_from": "2027-01-01",
            },
        )
        assert r.json()["etkilenen_sayisi"] == 1

    async def test_iptal_edilmis_abonelik_zamlanmaz(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        a = await _abonelik(client, m)
        await client.post(
            f"/api/abonelikler/{a['id']}/durum",
            json={"durum": "IPTAL", "tarih": "2026-06-01", "neden": "Çıktı"},
        )

        r = await client.post(
            "/api/toplu-zam/onizle",
            json={
                "title": "Zam denemesi",
                "method": "YUZDE",
                "value": 25,
                "valid_from": "2027-01-01",
            },
        )
        assert r.json()["etkilenen_sayisi"] == 0

    async def test_musteri_kriteriyle_daraltma(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m1 = await musteri_ac()
        m2 = await musteri_ac()
        await _abonelik(client, m1)
        await _abonelik(client, m2)

        r = await client.post(
            "/api/toplu-zam/onizle",
            json={
                "title": "Zam denemesi",
                "method": "YUZDE",
                "value": 25,
                "valid_from": "2027-01-01",
                "criteria": {"customer_ids": [m1.id]},
            },
        )
        veri = r.json()
        assert veri["etkilenen_sayisi"] == 1
        assert veri["etkilenen"][0]["customer_id"] == m1.id

    async def test_mrr_farki_periyoda_gore_normalize(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m, billing_period="YILLIK", unit_price=12000)

        r = await client.post(
            "/api/toplu-zam/onizle",
            json={
                "title": "Zam denemesi",
                "method": "YUZDE",
                "value": 10,
                "valid_from": "2027-01-01",
            },
        )
        veri = r.json()
        # Yıllık 12000 → 13200; aylık karşılık 1000 → 1100, fark 100.
        assert Decimal(veri["etkilenen"][0]["fark"]) == Decimal("1200.00")
        assert Decimal(veri["mrr_delta"]) == Decimal("100.00")


class TestTopluZamUygulama:
    async def _parti(self, client, **kw):
        veri = {
            "title": "2027 yıllık zam",
            "method": "YUZDE",
            "value": 25,
            "valid_from": "2027-01-01",
            "round_to": 1,
        }
        veri.update(kw)
        r = await client.post("/api/toplu-zam", json=veri)
        assert r.status_code == 201, r.text
        return r.json()

    async def test_taslak_olarak_dogar_fiyat_degismez(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        a = await _abonelik(client, m)
        p = await self._parti(client)
        assert p["status"] == "TASLAK"

        detay = await client.get(f"/api/abonelikler/{a['id']}")
        assert Decimal(detay.json()["guncel_fiyat"]) == Decimal("1000.00")

    async def test_uygulama_ucret_donemi_acar_ve_mrr_yazar(
        self, client, kullanici_ac, musteri_ac, db
    ):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        a = await _abonelik(client, m)
        p = await self._parti(client)

        r = await client.post(f"/api/toplu-zam/{p['id']}/uygula")
        assert r.status_code == 200, r.text
        parti = r.json()["parti"]
        assert parti["status"] == "UYGULANDI"
        assert parti["affected_count"] == 1
        assert Decimal(parti["mrr_delta"]) == Decimal("250.00")

        fiyatlar = (
            await db.scalars(
                select(SubscriptionPrice)
                .where(SubscriptionPrice.subscription_id == a["id"])
                .order_by(SubscriptionPrice.valid_from)
            )
        ).all()
        assert len(fiyatlar) == 2
        assert fiyatlar[1].unit_price == Decimal("1250.00")
        assert fiyatlar[1].price_batch_id == p["id"]

        olaylar = (
            await db.scalars(
                select(SubscriptionEvent)
                .where(SubscriptionEvent.subscription_id == a["id"])
                .order_by(SubscriptionEvent.id)
            )
        ).all()
        assert [o.event_type for o in olaylar] == ["YENI", "ARTIS"]

    async def test_ayni_parti_iki_kez_uygulanmaz(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m)
        p = await self._parti(client)

        assert (await client.post(f"/api/toplu-zam/{p['id']}/uygula")).status_code == 200
        ikinci = await client.post(f"/api/toplu-zam/{p['id']}/uygula")
        assert ikinci.status_code == 409

    async def test_gelecek_tarihli_zam_tahakkuku_zamaninda_etkiler(
        self, client, kullanici_ac, musteri_ac
    ):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m)
        p = await self._parti(client)
        await client.post(f"/api/toplu-zam/{p['id']}/uygula")

        aralik = await client.get("/api/abonelikler/tahakkuk/2026-12")
        ocak = await client.get("/api/abonelikler/tahakkuk/2027-01")
        assert Decimal(aralik.json()["satirlar"][0]["tutar"]) == Decimal("1000.00")
        assert Decimal(ocak.json()["satirlar"][0]["tutar"]) == Decimal("1250.00")

    async def test_geri_alma_fiyati_ve_olayi_siler(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        a = await _abonelik(client, m)
        p = await self._parti(client)
        await client.post(f"/api/toplu-zam/{p['id']}/uygula")

        r = await client.post(f"/api/toplu-zam/{p['id']}/geri-al")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "GERI_ALINDI"

        fiyatlar = (
            await db.scalars(
                select(SubscriptionPrice).where(SubscriptionPrice.subscription_id == a["id"])
            )
        ).all()
        assert len(fiyatlar) == 1
        assert fiyatlar[0].valid_to is None  # kapatılan dönem yeniden açıldı

        olaylar = (
            await db.scalars(
                select(SubscriptionEvent).where(SubscriptionEvent.subscription_id == a["id"])
            )
        ).all()
        assert [o.event_type for o in olaylar] == ["YENI"]

    async def test_yururluge_girmis_zam_geri_alinmaz(self, client, kullanici_ac, musteri_ac):
        """Dönem tahakkuku çıkmış olabilir; geçmiş değişmez."""
        client.clock.set(datetime(2026, 7, 1, tzinfo=UTC))
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m)
        # Yürürlük tarihi bugünden ESKİ: zam çoktan işlemiş.
        p = await self._parti(client, valid_from="2026-06-01")
        await client.post(f"/api/toplu-zam/{p['id']}/uygula")

        r = await client.post(f"/api/toplu-zam/{p['id']}/geri-al")
        assert r.status_code == 409
        assert "geri alınamaz" in r.json()["detail"]

    async def test_uygulanmamis_parti_bildirilmez(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m)
        p = await self._parti(client)
        r = await client.post(f"/api/toplu-zam/{p['id']}/bildir")
        assert r.status_code == 409

    async def test_parti_detayi_onizlemeyi_tasir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m)
        p = await self._parti(client)

        r = await client.get(f"/api/toplu-zam/{p['id']}")
        assert r.json()["onizleme"]["etkilenen_sayisi"] == 1

    async def test_uygulama_sonrasi_ikinci_zam_haric_birakir(
        self, client, kullanici_ac, musteri_ac
    ):
        """Aynı tarihten ücreti zaten güncellenmiş sözleşme ikinci kez zamlanmaz."""
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        await _abonelik(client, m)
        p1 = await self._parti(client)
        await client.post(f"/api/toplu-zam/{p1['id']}/uygula")

        r = await client.post(
            "/api/toplu-zam/onizle",
            json={
                "title": "Zam denemesi",
                "method": "YUZDE",
                "value": 10,
                "valid_from": "2027-01-01",
            },
        )
        veri = r.json()
        assert veri["etkilenen_sayisi"] == 0
        assert "zaten" in veri["haric"][0]["neden"]


class TestYetki:
    async def test_satis_temsilcisi_tahsilat_goremez(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        assert (await client.get("/api/tahsilat")).status_code == 403

    async def test_muhasebe_toplu_zam_yapamaz(self, client, kullanici_ac):
        """Muhasebede abonelik.yaz yok; fiyat kararı satışın."""
        await _giris(client, kullanici_ac)
        assert (
            await client.post(
                "/api/toplu-zam",
                json={
                    "title": "Zam denemesi",
                    "method": "YUZDE",
                    "value": 5,
                    "valid_from": "2027-01-01",
                },
            )
        ).status_code == 403

    async def test_muhasebe_tahsilat_yazabilir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/tahsilat",
            json={"account_id": m.id, "amount": 100, "paid_at": "2026-02-10"},
        )
        assert r.status_code == 201
