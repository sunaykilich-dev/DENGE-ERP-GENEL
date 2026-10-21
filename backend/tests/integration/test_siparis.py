"""Sipariş: tekliften dönüşüm, IMEI rezervasyonu, kısmi sevkiyat."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Account, Device, DeviceCustodyHistory, Order, OrderReservation

pytestmark = pytest.mark.integration


@pytest.fixture
async def musteri_ac(db):
    async def _make(ad: str = "Sipariş Müşterisi") -> Account:
        h = Account(title=ad, is_musteri=True, email="siparis@ornek.com")
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


async def _giris(client, kullanici_ac, username="satisci", rol="SATIS"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


async def _siparis_ac(client, musteri, urun, adet=3):
    r = await client.post(
        "/api/siparisler",
        json={
            "customer_id": musteri.id,
            "kalemler": [{"product_id": urun.id, "qty": adet}],
        },
    )
    assert r.status_code == 201, r.text
    s = r.json()
    onay = await client.post(f"/api/siparisler/{s['id']}/onayla")
    assert onay.status_code == 200, onay.text
    return onay.json()


class TestOlusturma:
    async def test_kalem_toplamlari_dondurulur(self, client, kullanici_ac, musteri_ac, urun_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        r = await client.post(
            "/api/siparisler",
            json={"customer_id": m.id, "kalemler": [{"product_id": u.id, "qty": 2}]},
        )
        assert r.status_code == 201, r.text
        s = r.json()
        assert Decimal(s["subtotal"]) == Decimal("2000.00")
        assert Decimal(s["vat_total"]) == Decimal("400.00")
        assert Decimal(s["grand_total"]) == Decimal("2400.00")
        assert s["status"] == "TASLAK"

    async def test_urun_kaleminde_elle_fiyat_aciklamayi_dusurmez(
        self, client, kullanici_ac, musteri_ac, urun_ac
    ):
        """Fiyatı elle verilen ürün kalemi, açıklamasını ürün kartından alır."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        r = await client.post(
            "/api/siparisler",
            json={
                "customer_id": m.id,
                "kalemler": [{"product_id": u.id, "qty": 1, "unit_price": 1250}],
            },
        )
        assert r.status_code == 201, r.text
        kalem = r.json()["kalemler"][0]
        assert Decimal(kalem["unit_price"]) == Decimal("1250.00")
        assert kalem["description"] == "L300 Ürün"

    async def test_kalemsiz_siparis_onaylanmaz(self, client, kullanici_ac, musteri_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        r = await client.post("/api/siparisler", json={"customer_id": m.id, "kalemler": []})
        sid = r.json()["id"]
        onay = await client.post(f"/api/siparisler/{sid}/onayla")
        assert onay.status_code == 409

    async def test_onaylanan_siparisin_kalemleri_degismez(
        self, client, kullanici_ac, musteri_ac, urun_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        s = await _siparis_ac(client, m, u)
        r = await client.put(
            f"/api/siparisler/{s['id']}/kalemler",
            json=[{"product_id": u.id, "qty": 9}],
        )
        assert r.status_code == 409


class TestTekliftenDonusum:
    async def _kabul_edilmis_teklif(self, client, m, u):
        r = await client.post(
            "/api/teklifler",
            json={"customer_id": m.id, "kalemler": [{"product_id": u.id, "qty": 2}]},
        )
        tid = r.json()["id"]
        await client.post(f"/api/teklifler/{tid}/gonder", json={})
        await client.post(f"/api/teklifler/{tid}/karar", json={"kabul": True})
        return tid

    async def test_kalemler_kopyalanir_ve_teklif_isaretlenir(
        self, client, kullanici_ac, musteri_ac, urun_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        tid = await self._kabul_edilmis_teklif(client, m, u)

        r = await client.post(f"/api/siparisler/tekliften/{tid}")
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["quote_id"] == tid
        assert len(s["kalemler"]) == 1
        assert Decimal(s["grand_total"]) == Decimal("2400.00")

        teklif = await client.get(f"/api/teklifler/{tid}")
        assert teklif.json()["status"] == "SIPARISE_DONUSTU"

    async def test_ayni_teklif_iki_kez_siparise_donmez(
        self, client, kullanici_ac, musteri_ac, urun_ac
    ):
        """Mükerrer sevkiyatın en kolay yolu budur; engellenmeli."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        tid = await self._kabul_edilmis_teklif(client, m, u)

        assert (await client.post(f"/api/siparisler/tekliften/{tid}")).status_code == 201
        ikinci = await client.post(f"/api/siparisler/tekliften/{tid}")
        assert ikinci.status_code == 409
        assert "zaten" in ikinci.json()["detail"]

    async def test_kabul_edilmemis_teklif_donusmez(self, client, kullanici_ac, musteri_ac, urun_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        r = await client.post(
            "/api/teklifler",
            json={"customer_id": m.id, "kalemler": [{"product_id": u.id, "qty": 1}]},
        )
        tid = r.json()["id"]
        assert (await client.post(f"/api/siparisler/tekliften/{tid}")).status_code == 409


class TestRezervasyon:
    async def test_imei_ile_rezerve_ve_cihaz_durumu(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        c = await cihaz_ac(imei="860000000000001", urun=u)
        s = await _siparis_ac(client, m, u)

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000001"]},
        )
        assert r.status_code == 200, r.text
        cikti = r.json()
        assert cikti["status"] == "REZERVE"
        assert cikti["kalemler"][0]["rezerve_adet"] == 1
        assert cikti["rezervasyonlar"][0]["kimlik"] == "860000000000001"

        await db.refresh(c)
        assert c.status == "REZERVE"

    async def test_ayni_cihaz_iki_siparise_rezerve_edilemez(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        await cihaz_ac(imei="860000000000002", urun=u)
        s1 = await _siparis_ac(client, m, u)
        s2 = await _siparis_ac(client, m, u)

        ilk = await client.post(
            f"/api/siparisler/{s1['id']}/rezerve",
            json={"kalem_id": s1["kalemler"][0]["id"], "kimlikler": ["860000000000002"]},
        )
        assert ilk.status_code == 200
        ikinci = await client.post(
            f"/api/siparisler/{s2['id']}/rezerve",
            json={"kalem_id": s2["kalemler"][0]["id"], "kimlikler": ["860000000000002"]},
        )
        assert ikinci.status_code == 409

    async def test_kalem_adedinden_fazla_rezerve_edilemez(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        for i in range(3):
            await cihaz_ac(imei=f"86000000000010{i}", urun=u)
        s = await _siparis_ac(client, m, u, adet=2)

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000100", "860000000000101", "860000000000102"],
            },
        )
        assert r.status_code == 409
        assert "kalan adet" in r.json()["detail"]

    async def test_baska_urunun_cihazi_rezerve_edilemez(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u1 = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        u2 = await urun_ac("CDR8213", "IMEI", list_price=Decimal("2000"), vat_rate=Decimal("0.20"))
        await cihaz_ac(imei="860000000000200", urun=u2)
        s = await _siparis_ac(client, m, u1)

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000200"]},
        )
        assert r.status_code == 409
        assert "ürüne ait değil" in r.json()["detail"]

    async def test_uygun_cihazlar_rezerveliyi_gostermez(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac
    ):
        """Arayüze imkânsız seçenek sunulmaz (prototipin */candidates deseni)."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        await cihaz_ac(imei="860000000000300", urun=u)
        await cihaz_ac(imei="860000000000301", urun=u)
        s = await _siparis_ac(client, m, u)
        kalem_id = s["kalemler"][0]["id"]

        once = await client.get(
            f"/api/siparisler/{s['id']}/uygun-cihazlar", params={"kalem_id": kalem_id}
        )
        assert len(once.json()) == 2

        await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": kalem_id, "kimlikler": ["860000000000300"]},
        )
        sonra = await client.get(
            f"/api/siparisler/{s['id']}/uygun-cihazlar", params={"kalem_id": kalem_id}
        )
        kalanlar = [c["imei"] for c in sonra.json()]
        assert kalanlar == ["860000000000301"]

    async def test_birakilan_rezervasyon_cihazi_stoga_dondurur(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        c = await cihaz_ac(imei="860000000000400", urun=u)
        s = await _siparis_ac(client, m, u)

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000400"]},
        )
        rez_id = r.json()["rezervasyonlar"][0]["id"]

        b = await client.post(
            f"/api/siparisler/rezervasyon/{rez_id}/birak", json={"neden": "Müşteri erteledi"}
        )
        assert b.status_code == 200, b.text
        # Tek rezervasyon bırakılınca sipariş REZERVE'den ONAYLANDI'ya döner.
        assert b.json()["status"] == "ONAYLANDI"

        await db.refresh(c)
        assert c.status == "STOKTA"


class TestSevkiyat:
    async def test_kismi_sevk_ve_tamamlanma(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        for i in range(2):
            await cihaz_ac(imei=f"86000000000050{i}", urun=u)
        s = await _siparis_ac(client, m, u, adet=2)
        kalem_id = s["kalemler"][0]["id"]

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": kalem_id, "kimlikler": ["860000000000500", "860000000000501"]},
        )
        rezler = r.json()["rezervasyonlar"]

        ilk = await client.post(
            f"/api/siparisler/{s['id']}/sevk", json={"rezervasyon_ids": [rezler[0]["id"]]}
        )
        assert ilk.status_code == 200, ilk.text
        assert ilk.json()["siparis"]["status"] == "KISMI_SEVK"
        assert Decimal(ilk.json()["siparis"]["kalemler"][0]["qty_shipped"]) == Decimal("1")

        ikinci = await client.post(f"/api/siparisler/{s['id']}/sevk", json={})
        assert ikinci.json()["siparis"]["status"] == "SEVK_EDILDI"

        transfer_id = ikinci.json()["transfer_id"]
        teslim = await client.post(
            f"/api/siparisler/sevkiyat/{transfer_id}/teslim", json={"received_by": "Depo"}
        )
        assert teslim.status_code == 200, teslim.text
        # Son parti teslim alınınca sipariş TAMAMLANDI olur.
        assert teslim.json()["status"] == "TAMAMLANDI"

    async def test_teslim_sahipligi_musteriye_gecirir(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        c = await cihaz_ac(imei="860000000000600", urun=u)
        s = await _siparis_ac(client, m, u, adet=1)

        await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000600"]},
        )
        sevk = await client.post(f"/api/siparisler/{s['id']}/sevk", json={})
        await client.post(f"/api/siparisler/sevkiyat/{sevk.json()['transfer_id']}/teslim", json={})

        konum = await db.scalar(
            select(DeviceCustodyHistory).where(
                DeviceCustodyHistory.device_id == c.id,
                DeviceCustodyHistory.valid_to.is_(None),
            )
        )
        assert konum is not None
        assert konum.location_type == "MUSTERI"
        assert konum.ownership == "MUSTERI_SATILDI"
        assert konum.account_id == m.id

    async def test_sevk_sonrasi_rezervasyon_geri_alinmaz(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        await cihaz_ac(imei="860000000000700", urun=u)
        s = await _siparis_ac(client, m, u, adet=1)

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000700"]},
        )
        rez_id = r.json()["rezervasyonlar"][0]["id"]
        await client.post(f"/api/siparisler/{s['id']}/sevk", json={})

        b = await client.post(f"/api/siparisler/rezervasyon/{rez_id}/birak", json={})
        assert b.status_code == 409


class TestIptal:
    async def test_iptal_acik_rezervasyonlari_birakir(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        c = await cihaz_ac(imei="860000000000800", urun=u)
        s = await _siparis_ac(client, m, u, adet=1)
        await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000800"]},
        )

        r = await client.post(
            f"/api/siparisler/{s['id']}/iptal", json={"neden": "Müşteri vazgeçti"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "IPTAL"

        await db.refresh(c)
        assert c.status == "STOKTA"
        acik = await db.scalar(
            select(OrderReservation).where(
                OrderReservation.order_id == s["id"], OrderReservation.released_at.is_(None)
            )
        )
        assert acik is None


class TestYetki:
    async def test_satis_temsilcisi_baskasinin_siparisini_gormez(
        self, client, kullanici_ac, musteri_ac, urun_ac, db
    ):
        await _giris(client, kullanici_ac, "satisci1", "SATIS")
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        r = await client.post(
            "/api/siparisler",
            json={"customer_id": m.id, "kalemler": [{"product_id": u.id, "qty": 1}]},
        )
        sid = r.json()["id"]

        await client.post("/api/auth/logout")
        await _giris(client, kullanici_ac, "satisci2", "SATIS")
        assert (await client.get(f"/api/siparisler/{sid}")).status_code == 404

    async def test_depo_siparis_goremez(self, client, kullanici_ac):
        """DEPO rolünde siparis.gor yok — sevkiyat listesi de kapalı."""
        await _giris(client, kullanici_ac, "depocu", "DEPO")
        assert (await client.get("/api/siparisler")).status_code == 403


class TestCihazDurumZinciri:
    async def test_arizali_cihaz_rezerve_edilemez(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        await cihaz_ac(imei="860000000000900", urun=u, status="ARIZALI")
        s = await _siparis_ac(client, m, u, adet=1)

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000900"]},
        )
        assert r.status_code == 409
        assert "ARIZALI" in r.json()["detail"]

    async def test_sevk_cihazi_sevk_edildi_yapar(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        c = await cihaz_ac(imei="860000000001000", urun=u)
        s = await _siparis_ac(client, m, u, adet=1)
        await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000001000"]},
        )
        await client.post(f"/api/siparisler/{s['id']}/sevk", json={})

        await db.refresh(c)
        assert c.status == "SEVK_EDILDI"
        # Rezervasyon sevkiyatla TÜKETİLİR; cihaz kısmi tekil indeksi serbest bırakır.
        acik = await db.scalar(
            select(OrderReservation).where(
                OrderReservation.device_id == c.id, OrderReservation.released_at.is_(None)
            )
        )
        assert acik is None


class TestBekleyenSevkiyat:
    async def test_depo_is_listesi_kalan_adedi_gosterir(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac, "mudur", "SATIS_MUDURU")
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        await cihaz_ac(imei="860000000001100", urun=u)
        s = await _siparis_ac(client, m, u, adet=2)
        await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000001100"]},
        )
        await client.post(f"/api/siparisler/{s['id']}/sevk", json={})

        r = await client.get("/api/siparisler/bekleyen-sevkiyat")
        assert r.status_code == 200, r.text
        satir = next(x for x in r.json() if x["order_id"] == s["id"])
        assert Decimal(str(satir["toplam_adet"])) == Decimal("2")
        assert Decimal(str(satir["sevk_adet"])) == Decimal("1")
        assert Decimal(str(satir["kalan_adet"])) == Decimal("1")


class TestIdempotentlikVeSayim:
    async def test_siparis_numarasi_tekil(self, client, kullanici_ac, musteri_ac, urun_ac, db):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        for _ in range(3):
            await client.post(
                "/api/siparisler",
                json={"customer_id": m.id, "kalemler": [{"product_id": u.id, "qty": 1}]},
            )
        nolar = [s.order_no for s in (await db.scalars(select(Order))).all()]
        assert len(nolar) == len(set(nolar)) == 3


class TestKimliksizUrun:
    async def test_kimlik_tasimayan_urunde_rezervasyon_beklenmez(
        self, client, kullanici_ac, musteri_ac, urun_ac
    ):
        """Kablo/hizmet kaleminde IMEI ayrılmaz; arayüz bunu bayraktan bilir."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("KABLO", "YOK", list_price=Decimal("50"), vat_rate=Decimal("0.20"))
        r = await client.post(
            "/api/siparisler",
            json={"customer_id": m.id, "kalemler": [{"product_id": u.id, "qty": 5}]},
        )
        assert r.json()["kalemler"][0]["kimlik_gerekir"] is False


class TestCihazBulunamadi:
    async def test_olmayan_imei_acik_hata_verir(self, client, kullanici_ac, musteri_ac, urun_ac):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        s = await _siparis_ac(client, m, u, adet=1)
        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["999999999999999"]},
        )
        assert r.status_code == 400
        assert "bulunamadı" in r.json()["detail"]


class TestSeriNoluCihaz:
    async def test_seri_no_ile_rezerve(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        """Ek kameraların IMEI'si yok; kimlik seri numarası (plan §2/1)."""
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac(
            "HMW3200LP", "SERI_NO", list_price=Decimal("800"), vat_rate=Decimal("0.20")
        )
        c = await cihaz_ac(serial_no="SN-0001", urun=u)
        s = await _siparis_ac(client, m, u, adet=1)

        r = await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["SN-0001"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["rezervasyonlar"][0]["kimlik"] == "SN-0001"
        await db.refresh(c)
        assert c.status == "REZERVE"


class TestDevre:
    async def test_iptal_edilen_siparis_yeniden_iptal_edilmez(
        self, client, kullanici_ac, musteri_ac, urun_ac
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        s = await _siparis_ac(client, m, u, adet=1)
        assert (
            await client.post(f"/api/siparisler/{s['id']}/iptal", json={"neden": "test"})
        ).status_code == 200
        ikinci = await client.post(f"/api/siparisler/{s['id']}/iptal", json={"neden": "test"})
        assert ikinci.status_code == 409


class TestDeviceSayimi:
    async def test_sevk_edilmis_cihaz_uygun_listesinde_cikmaz(
        self, client, kullanici_ac, musteri_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        m = await musteri_ac()
        u = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
        await cihaz_ac(imei="860000000001200", urun=u)
        s = await _siparis_ac(client, m, u, adet=1)
        kalem_id = s["kalemler"][0]["id"]
        await client.post(
            f"/api/siparisler/{s['id']}/rezerve",
            json={"kalem_id": kalem_id, "kimlikler": ["860000000001200"]},
        )
        await client.post(f"/api/siparisler/{s['id']}/sevk", json={})

        # Rezervasyon serbest kaldı ama cihaz SEVK_EDILDI: durum filtresi tutar.
        r = await client.get(
            f"/api/siparisler/{s['id']}/uygun-cihazlar", params={"kalem_id": kalem_id}
        )
        assert [c["imei"] for c in r.json()] == []
        kalan = await db.scalar(select(Device).where(Device.imei == "860000000001200"))
        assert kalan.status == "SEVK_EDILDI"
