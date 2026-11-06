"""Abonelik: tarihli ücret, kıst hesap, aylık tahakkuk, MRR ve churn."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Account, SubscriptionEvent, SubscriptionPrice
from app.services import subscriptions as svc

pytestmark = pytest.mark.integration


@pytest.fixture
async def musteri_ac(db):
    sayac = {"n": 0}

    async def _make(ad: str | None = None) -> Account:
        sayac["n"] += 1
        h = Account(title=ad or f"Abone {sayac['n']}", is_musteri=True, email="abone@ornek.com")
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


async def _giris(client, kullanici_ac, username="mudur", rol="SATIS_MUDURU"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


async def _abonelik_ac(client, musteri, **kw):
    veri = {
        "customer_id": musteri.id,
        "title": "Platform aboneliği",
        "billing_period": "AYLIK",
        "vat_rate": 0.20,
        "unit_price": 300,
        "start_date": "2026-01-01",
    }
    veri.update(kw)
    r = await client.post("/api/abonelikler", json=veri)
    assert r.status_code == 201, r.text
    return r.json()


async def _aktif(client, abonelik_id, tarih=None):
    r = await client.post(
        f"/api/abonelikler/{abonelik_id}/durum",
        json={"durum": "AKTIF", "tarih": tarih},
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- Saf hesap testleri (DB'siz) ---------------------------------------------


class TestAylikTutar:
    def test_yillik_on_ikiye_bolunur(self):
        assert svc.aylik_tutar(Decimal("12000"), "YILLIK") == Decimal("1000.00")

    def test_uc_aylik_uce_bolunur(self):
        assert svc.aylik_tutar(Decimal("900"), "UC_AYLIK") == Decimal("300.00")

    def test_aylik_aynen_kalir(self):
        assert svc.aylik_tutar(Decimal("299.99"), "AYLIK") == Decimal("299.99")

    def test_yuvarlama_yarim_yukari(self):
        # 1000/3 = 333,333… → 333,33; 1000/6 = 166,666… → 166,67
        assert svc.aylik_tutar(Decimal("1000"), "UC_AYLIK") == Decimal("333.33")
        assert svc.aylik_tutar(Decimal("1000"), "ALTI_AYLIK") == Decimal("166.67")


class TestKistHesap:
    def test_tam_ay_orantisiz_yazilir(self):
        """31/31 çarpımı kuruş kaydırabilir; tam ayda orantı uygulanmaz."""
        tutar = svc.kist_tutar(
            Decimal("333.33"),
            donem_bas=date(2026, 1, 1),
            donem_son=date(2026, 1, 31),
            aktif_gun=31,
        )
        assert tutar == Decimal("333.33")

    def test_ay_ortasi_baslangic(self):
        # 15 Mart'ta başlayan abonelik Mart'ın 17 gününü öder (15–31 dahil).
        tutar = svc.kist_tutar(
            Decimal("300"),
            donem_bas=date(2026, 3, 1),
            donem_son=date(2026, 3, 31),
            aktif_gun=17,
        )
        assert tutar == Decimal("164.52")  # 300 × 17/31

    def test_subat_28_gun_uzerinden(self):
        tutar = svc.kist_tutar(
            Decimal("280"),
            donem_bas=date(2026, 2, 1),
            donem_son=date(2026, 2, 28),
            aktif_gun=14,
        )
        assert tutar == Decimal("140.00")

    def test_sifir_gun_sifir_tutar(self):
        assert svc.kist_tutar(
            Decimal("300"),
            donem_bas=date(2026, 3, 1),
            donem_son=date(2026, 3, 31),
            aktif_gun=0,
        ) == Decimal("0")


class TestDonemAraligi:
    def test_ay_sonu_dogru_hesaplanir(self):
        assert svc.donem_araligi("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
        assert svc.donem_araligi("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
        assert svc.donem_araligi("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))


# --- Yaşam döngüsü ------------------------------------------------------------


class TestOlusturmaVeAktivasyon:
    async def test_taslak_dogar_ve_mrr_uretmez(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        assert a["status"] == "TASLAK"
        assert Decimal(a["guncel_fiyat"]) == Decimal("300.00")

        mrr = await client.get("/api/abonelikler/mrr", params={"tarih": "2026-01-31"})
        assert Decimal(mrr.json()["mrr"]) == Decimal("0")

    async def test_aktiflesince_mrr_olayi_yazilir(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        out = await _aktif(client, a["id"], "2026-01-01")
        assert out["status"] == "AKTIF"

        olaylar = (
            await db.scalars(
                select(SubscriptionEvent).where(SubscriptionEvent.subscription_id == a["id"])
            )
        ).all()
        assert [o.event_type for o in olaylar] == ["YENI"]
        assert olaylar[0].mrr_delta == Decimal("300.00")
        assert olaylar[0].mrr_before == Decimal("0")

    async def test_yillik_abonelik_mrr_on_ikide_bir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, billing_period="YILLIK", unit_price=12000)
        await _aktif(client, a["id"], "2026-01-01")

        mrr = await client.get("/api/abonelikler/mrr", params={"tarih": "2026-01-15"})
        assert Decimal(mrr.json()["mrr"]) == Decimal("1000.00")

    async def test_fiyatsiz_aktiflestirilemez(self, client, kullanici_ac, musteri_ac, db):
        """Ücret tanımlanmadan MRR'a girmek, geliri uydurmak olurdu."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, start_date="2026-06-01")
        # Ücret 2026-06-01'de başlıyor; ondan önceki bir tarihte geçerli fiyat yok.
        r = await client.post(
            f"/api/abonelikler/{a['id']}/durum",
            json={"durum": "AKTIF", "tarih": "2026-05-01"},
        )
        assert r.status_code == 409
        assert "ücreti" in r.json()["detail"]

    async def test_iptal_nedeni_zorunlu(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")
        r = await client.post(
            f"/api/abonelikler/{a['id']}/durum", json={"durum": "IPTAL", "tarih": "2026-02-01"}
        )
        assert r.status_code == 409
        assert "neden" in r.json()["detail"].lower()

    async def test_gecersiz_gecis_reddedilir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")
        await client.post(
            f"/api/abonelikler/{a['id']}/durum",
            json={"durum": "IPTAL", "tarih": "2026-02-01", "neden": "Araç satıldı"},
        )
        # IPTAL terminal: geri dönüş yok.
        r = await client.post(
            f"/api/abonelikler/{a['id']}/durum", json={"durum": "AKTIF", "tarih": "2026-03-01"}
        )
        assert r.status_code == 409


class TestTarihliUcret:
    async def test_zam_yeni_donem_acar_eskisini_kapatir(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")

        r = await client.post(
            f"/api/abonelikler/{a['id']}/fiyat",
            json={"unit_price": 400, "valid_from": "2026-04-01", "neden": "Yıllık zam"},
        )
        assert r.status_code == 200, r.text

        fiyatlar = (
            await db.scalars(
                select(SubscriptionPrice)
                .where(SubscriptionPrice.subscription_id == a["id"])
                .order_by(SubscriptionPrice.valid_from)
            )
        ).all()
        assert len(fiyatlar) == 2
        assert fiyatlar[0].valid_to == date(2026, 4, 1)
        assert fiyatlar[1].valid_to is None

    async def test_gecmise_donuk_fiyat_yazilamaz(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        r = await client.post(
            f"/api/abonelikler/{a['id']}/fiyat",
            json={"unit_price": 400, "valid_from": "2025-12-01"},
        )
        assert r.status_code == 409

    async def test_taahhut_suresince_zam_yapilamaz(self, client, kullanici_ac, musteri_ac):
        """%89 indirim taahhüde bağlı; taahhütlü sözleşme zamdan muaf."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, commitment_end_date="2026-12-31")
        r = await client.post(
            f"/api/abonelikler/{a['id']}/fiyat",
            json={"unit_price": 400, "valid_from": "2026-04-01"},
        )
        assert r.status_code == 409
        assert "Taahhüt" in r.json()["detail"]

    async def test_zam_artis_olayi_yazar(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")
        await client.post(
            f"/api/abonelikler/{a['id']}/fiyat",
            json={"unit_price": 400, "valid_from": "2026-04-01"},
        )
        olaylar = (
            await db.scalars(
                select(SubscriptionEvent)
                .where(SubscriptionEvent.subscription_id == a["id"])
                .order_by(SubscriptionEvent.id)
            )
        ).all()
        assert [o.event_type for o in olaylar] == ["YENI", "ARTIS"]
        assert olaylar[1].mrr_delta == Decimal("100.00")

    async def test_taslak_aboneligin_zammi_mrr_olayi_uretmez(
        self, client, kullanici_ac, musteri_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await client.post(
            f"/api/abonelikler/{a['id']}/fiyat",
            json={"unit_price": 400, "valid_from": "2026-04-01"},
        )
        olay = await db.scalar(
            select(SubscriptionEvent).where(SubscriptionEvent.subscription_id == a["id"])
        )
        assert olay is None

    async def test_fiyat_patch_ile_degistirilemez(self, client, kullanici_ac, musteri_ac):
        """Ücreti başlık güncellemesinden değiştirmek tarihli geçmişi baypas ederdi."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        r = await client.patch(
            f"/api/abonelikler/{a['id']}",
            json={"version": a["version"], "unit_price": 9999, "notes": "not"},
        )
        assert r.status_code == 200
        assert Decimal(r.json()["guncel_fiyat"]) == Decimal("300.00")


class TestTahakkuk:
    async def test_tam_ay_tam_tutar(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")

        r = await client.get("/api/abonelikler/tahakkuk/2026-01")
        assert r.status_code == 200, r.text
        veri = r.json()
        assert veri["satir"] == 1
        satir = veri["satirlar"][0]
        assert satir["kist"] is False
        assert Decimal(satir["tutar"]) == Decimal("300.00")
        assert Decimal(satir["kdv"]) == Decimal("60.00")
        assert Decimal(satir["toplam"]) == Decimal("360.00")

    async def test_ay_ortasi_baslangic_kist(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, start_date="2026-03-15")
        await _aktif(client, a["id"], "2026-03-15")

        r = await client.get("/api/abonelikler/tahakkuk/2026-03")
        satir = r.json()["satirlar"][0]
        assert satir["kist"] is True
        assert satir["aktif_gun"] == 17
        assert satir["donem_gun"] == 31
        assert Decimal(satir["tutar"]) == Decimal("164.52")

    async def test_baslamadan_onceki_ayda_satir_yok(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, start_date="2026-03-15")
        await _aktif(client, a["id"], "2026-03-15")
        r = await client.get("/api/abonelikler/tahakkuk/2026-02")
        assert r.json()["satir"] == 0

    async def test_askidaki_gunler_dusulur(self, client, kullanici_ac, musteri_ac):
        """Askı aralığı olay kayıtlarından çıkarılır; ayrı askı tablosu yok."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")
        # 11 Mart'ta askıya alındı, 21 Mart'ta geri döndü → 10 gün askıda.
        await client.post(
            f"/api/abonelikler/{a['id']}/durum", json={"durum": "ASKIDA", "tarih": "2026-03-11"}
        )
        await client.post(
            f"/api/abonelikler/{a['id']}/durum", json={"durum": "AKTIF", "tarih": "2026-03-21"}
        )

        r = await client.get("/api/abonelikler/tahakkuk/2026-03")
        satir = r.json()["satirlar"][0]
        assert satir["aktif_gun"] == 21  # 31 − 10
        assert Decimal(satir["tutar"]) == Decimal("203.23")  # 300 × 21/31

    async def test_iptal_edilen_ay_kist_hesaplanir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")
        await client.post(
            f"/api/abonelikler/{a['id']}/durum",
            json={"durum": "IPTAL", "tarih": "2026-04-10", "neden": "Araç satıldı"},
        )

        r = await client.get("/api/abonelikler/tahakkuk/2026-04")
        satir = r.json()["satirlar"][0]
        assert satir["aktif_gun"] == 10
        assert Decimal(satir["tutar"]) == Decimal("100.00")  # 300 × 10/30

        sonraki = await client.get("/api/abonelikler/tahakkuk/2026-05")
        assert sonraki.json()["satir"] == 0

    async def test_zam_sonrasi_ay_yeni_fiyattan(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")
        await client.post(
            f"/api/abonelikler/{a['id']}/fiyat",
            json={"unit_price": 400, "valid_from": "2026-04-01"},
        )

        mart = await client.get("/api/abonelikler/tahakkuk/2026-03")
        nisan = await client.get("/api/abonelikler/tahakkuk/2026-04")
        assert Decimal(mart.json()["satirlar"][0]["tutar"]) == Decimal("300.00")
        assert Decimal(nisan.json()["satirlar"][0]["tutar"]) == Decimal("400.00")

    async def test_yillik_abonelik_aylik_tahakkuk_eder(self, client, kullanici_ac, musteri_ac):
        """Tahakkuk esası: yıllık bedel aylara bölünür."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, billing_period="YILLIK", unit_price=12000)
        await _aktif(client, a["id"], "2026-01-01")

        r = await client.get("/api/abonelikler/tahakkuk/2026-01")
        assert Decimal(r.json()["satirlar"][0]["tutar"]) == Decimal("1000.00")

    async def test_toplamlar_satirlarla_tutar(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        for _ in range(3):
            m = await musteri_ac()
            a = await _abonelik_ac(client, m)
            await _aktif(client, a["id"], "2026-01-01")

        r = await client.get("/api/abonelikler/tahakkuk/2026-01")
        veri = r.json()
        assert veri["satir"] == 3
        assert Decimal(veri["toplam_matrah"]) == Decimal("900.00")
        assert Decimal(veri["toplam_kdv"]) == Decimal("180.00")
        assert Decimal(veri["toplam"]) == Decimal("1080.00")

    async def test_gecersiz_donem_400(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        assert (await client.get("/api/abonelikler/tahakkuk/2026")).status_code == 400

    async def test_xlsx_indirilebilir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")

        r = await client.get("/api/abonelikler/tahakkuk/2026-01/xlsx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"  # xlsx = zip
        assert "tahakkuk-2026-01.xlsx" in r.headers["content-disposition"]


class TestMrrVeChurn:
    async def test_mrr_olay_toplamindan_gelir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        for _ in range(2):
            m = await musteri_ac()
            a = await _abonelik_ac(client, m)
            await _aktif(client, a["id"], "2026-01-01")

        r = await client.get("/api/abonelikler/mrr", params={"tarih": "2026-01-31"})
        assert Decimal(r.json()["mrr"]) == Decimal("600.00")

    async def test_iptal_mrr_dusurur_ve_churn_hesaplanir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        abonelikler = []
        for _ in range(4):
            m = await musteri_ac()
            a = await _abonelik_ac(client, m)
            await _aktif(client, a["id"], "2026-01-01")
            abonelikler.append(a)

        await client.post(
            f"/api/abonelikler/{abonelikler[0]['id']}/durum",
            json={"durum": "IPTAL", "tarih": "2026-02-10", "neden": "Filo küçüldü"},
        )

        r = await client.get("/api/abonelikler/mrr/2026-02")
        veri = r.json()
        assert Decimal(veri["baslangic_mrr"]) == Decimal("1200.00")
        assert Decimal(veri["bitis_mrr"]) == Decimal("900.00")
        assert veri["hareket"]["IPTAL"]["adet"] == 1
        assert Decimal(veri["hareket"]["IPTAL"]["delta"]) == Decimal("-300.00")
        assert Decimal(veri["churn_yuzde"]) == Decimal("25.00")

    async def test_askidan_donus_geri_donus_olayi(self, client, kullanici_ac, musteri_ac, db):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m)
        await _aktif(client, a["id"], "2026-01-01")
        await client.post(
            f"/api/abonelikler/{a['id']}/durum", json={"durum": "ASKIDA", "tarih": "2026-02-01"}
        )
        await client.post(
            f"/api/abonelikler/{a['id']}/durum", json={"durum": "AKTIF", "tarih": "2026-03-01"}
        )

        olaylar = (
            await db.scalars(
                select(SubscriptionEvent)
                .where(SubscriptionEvent.subscription_id == a["id"])
                .order_by(SubscriptionEvent.id)
            )
        ).all()
        assert [o.event_type for o in olaylar] == ["YENI", "ASKI", "GERI_DONUS"]
        assert olaylar[1].mrr_after == Decimal("0")
        assert olaylar[2].mrr_after == Decimal("300.00")

    async def test_bos_donemde_churn_tanimsiz(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await client.get("/api/abonelikler/mrr/2026-05")
        assert r.json()["churn_yuzde"] is None


class TestYenileme:
    async def test_bitis_tarihi_ay_sayisinca_uzar(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, end_date="2026-12-31")
        await _aktif(client, a["id"], "2026-01-01")

        r = await client.post(f"/api/abonelikler/{a['id']}/yenile", json={"ay": 12})
        assert r.status_code == 200, r.text
        assert r.json()["end_date"] == "2027-12-31"

    async def test_ay_sonu_kisa_aya_kirpilir(self, client, kullanici_ac, musteri_ac):
        """31 Ocak + 1 ay = 28 Şubat; naif tarih aritmetiği burada patlar."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, end_date="2026-01-31")
        await _aktif(client, a["id"], "2026-01-01")

        r = await client.post(f"/api/abonelikler/{a['id']}/yenile", json={"ay": 1})
        assert r.json()["end_date"] == "2026-02-28"

    async def test_yenilemeye_kapali_sozlesme_uzatilmaz(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, end_date="2026-12-31", renewal_type="YOK")
        await _aktif(client, a["id"], "2026-01-01")
        r = await client.post(f"/api/abonelikler/{a['id']}/yenile", json={})
        assert r.status_code == 409

    async def test_yenilenecekler_listesi(self, client, kullanici_ac, musteri_ac):
        # Saat girişten ÖNCE ileri alınır; sonra alınsa oturum süresi dolmuş olurdu.
        client.clock.set(datetime(2026, 12, 15, tzinfo=UTC))
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        a = await _abonelik_ac(client, m, end_date="2026-12-31")
        await _aktif(client, a["id"], "2026-01-01")

        uzak = await musteri_ac()
        b = await _abonelik_ac(client, uzak, end_date="2027-12-31")
        await _aktif(client, b["id"], "2026-01-01")

        r = await client.get("/api/abonelikler/yenilenecekler", params={"gun": 30})
        idler = [x["subscription_id"] for x in r.json()]
        assert a["id"] in idler
        assert b["id"] not in idler
        satir = next(x for x in r.json() if x["subscription_id"] == a["id"])
        assert satir["kalan_gun"] == 16


class TestYetki:
    async def test_satis_temsilcisi_abonelik_yazamaz(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        m = await musteri_ac()
        r = await client.post(
            "/api/abonelikler",
            json={
                "customer_id": m.id,
                "vat_rate": 0.20,
                "unit_price": 300,
                "start_date": "2026-01-01",
            },
        )
        assert r.status_code == 403

    async def test_satis_temsilcisi_abonelik_gorur(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        assert (await client.get("/api/abonelikler")).status_code == 200

    async def test_hat_sorumlusu_abonelik_goremez(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "hatci", "HAT_SORUMLUSU")
        assert (await client.get("/api/abonelikler")).status_code == 403


class TestDogrulama:
    async def test_gecersiz_periyot_reddedilir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/abonelikler",
            json={
                "customer_id": m.id,
                "billing_period": "HAFTALIK",
                "vat_rate": 0.20,
                "unit_price": 300,
                "start_date": "2026-01-01",
            },
        )
        assert r.status_code == 400

    async def test_kdv_verilmezse_ayardan_gelir(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post(
            "/api/abonelikler",
            json={"customer_id": m.id, "unit_price": 300, "start_date": "2026-01-01"},
        )
        assert r.status_code == 201
        assert Decimal(r.json()["vat_rate"]) == Decimal("0.2000")
