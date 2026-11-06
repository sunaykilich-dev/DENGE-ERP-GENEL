"""Satın alma, mal kabul, ithalat dosyası, landed cost ve BTK."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Account, Device
from app.services.purchasing import dosya_toplami

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username="yonetici", rol="ADMIN"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


@pytest.fixture
async def tedarikci_ac(db):
    sayac = {"n": 0}

    async def _make(ad: str | None = None, tedarikci: bool = True) -> Account:
        sayac["n"] += 1
        h = Account(
            title=ad or f"TEDARIKCI {sayac['n']}",
            title_key=(ad or f"tedarikci {sayac['n']}").lower(),
            is_tedarikci=tedarikci,
            is_musteri=not tedarikci,
        )
        db.add(h)
        await db.commit()
        await db.refresh(h)
        return h

    return _make


async def _siparis_ac(client, tedarikci, urun, adet=10, fiyat=100, agirlik=None):
    kalem = {"product_id": urun.id, "qty": adet, "unit_price": fiyat}
    if agirlik is not None:
        kalem["unit_weight_kg"] = agirlik
    r = await client.post(
        "/api/satinalma/siparisler",
        json={"supplier_id": tedarikci.id, "currency": "USD", "kalemler": [kalem]},
    )
    assert r.status_code == 201, r.text
    s = r.json()
    v = await client.post(
        f"/api/satinalma/siparisler/{s['id']}/durum", json={"durum": "SIPARIS_VERILDI"}
    )
    assert v.status_code == 200, v.text
    return v.json()


class TestSatinAlmaSiparisi:
    async def test_toplam_hesaplanir(self, client, kullanici_ac, tedarikci_ac, urun_ac):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        r = await client.post(
            "/api/satinalma/siparisler",
            json={
                "supplier_id": t.id,
                "kalemler": [{"product_id": u.id, "qty": 10, "unit_price": 42.5}],
            },
        )
        assert r.status_code == 201, r.text
        assert Decimal(r.json()["subtotal"]) == Decimal("425.00")
        assert r.json()["status"] == "TASLAK"

    async def test_tedarikci_olmayan_hesap_reddedilir(
        self, client, kullanici_ac, tedarikci_ac, urun_ac
    ):
        await _giris(client, kullanici_ac)
        musteri = await tedarikci_ac("SADECE MUSTERI", tedarikci=False)
        u = await urun_ac("L300", "IMEI")
        r = await client.post(
            "/api/satinalma/siparisler",
            json={
                "supplier_id": musteri.id,
                "kalemler": [{"product_id": u.id, "qty": 1, "unit_price": 1}],
            },
        )
        assert r.status_code == 400
        assert "tedarikçi olarak işaretli değil" in r.json()["detail"]

    async def test_kalemsiz_siparis_verilemez(self, client, kullanici_ac, tedarikci_ac):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        r = await client.post(
            "/api/satinalma/siparisler", json={"supplier_id": t.id, "kalemler": []}
        )
        v = await client.post(
            f"/api/satinalma/siparisler/{r.json()['id']}/durum",
            json={"durum": "SIPARIS_VERILDI"},
        )
        assert v.status_code == 409

    async def test_gecersiz_gecis_reddedilir(self, client, kullanici_ac, tedarikci_ac, urun_ac):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        r = await client.post(
            "/api/satinalma/siparisler",
            json={
                "supplier_id": t.id,
                "kalemler": [{"product_id": u.id, "qty": 1, "unit_price": 1}],
            },
        )
        # TASLAK'tan doğrudan TESLIM_ALINDI'ya geçilemez.
        v = await client.post(
            f"/api/satinalma/siparisler/{r.json()['id']}/durum",
            json={"durum": "TESLIM_ALINDI"},
        )
        assert v.status_code == 409


class TestMalKabul:
    async def test_imei_listesi_stoga_girer(self, client, kullanici_ac, tedarikci_ac, urun_ac, db):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=3)

        r = await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000001", "860000000000002", "860000000000003"],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["adet"] == 3
        assert r.json()["siparis"]["status"] == "TESLIM_ALINDI"

        adet = await db.scalar(
            select(func.count()).select_from(Device).where(Device.status == "STOKTA")
        )
        assert adet == 3

    async def test_kismi_teslim(self, client, kullanici_ac, tedarikci_ac, urun_ac):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=5)

        r = await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000010"]},
        )
        assert r.json()["siparis"]["status"] == "KISMI_TESLIM"
        assert Decimal(r.json()["siparis"]["kalemler"][0]["qty_received"]) == Decimal("1")

    async def test_adet_asimi_reddedilir(self, client, kullanici_ac, tedarikci_ac, urun_ac):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=1)
        r = await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000020", "860000000000021"],
            },
        )
        assert r.status_code == 409
        assert "kalan adet" in r.json()["detail"]

    async def test_kayitli_imei_ikinci_kez_kabul_edilmez(
        self, client, kullanici_ac, tedarikci_ac, urun_ac, cihaz_ac
    ):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000030", urun=u)
        s = await _siparis_ac(client, t, u, adet=2)
        r = await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000030"]},
        )
        assert r.status_code == 409
        assert "zaten kayıtlı" in r.json()["detail"]

    async def test_taslak_siparise_mal_kabul_yapilmaz(
        self, client, kullanici_ac, tedarikci_ac, urun_ac
    ):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        r = await client.post(
            "/api/satinalma/siparisler",
            json={
                "supplier_id": t.id,
                "kalemler": [{"product_id": u.id, "qty": 1, "unit_price": 1}],
            },
        )
        s = r.json()
        m = await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000040"]},
        )
        assert m.status_code == 409

    async def test_seri_nolu_urun(self, client, kullanici_ac, tedarikci_ac, urun_ac, db):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("HMW3200LP", "SERI_NO")
        s = await _siparis_ac(client, t, u, adet=2)
        r = await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["SN-1", "SN-2"]},
        )
        assert r.status_code == 200, r.text
        assert await db.scalar(select(Device).where(Device.serial_no == "SN-1")) is not None


class TestIthalatVeLandedCost:
    async def _dosya(self, client, **kw):
        veri = {
            "invoice_no": "INV-2026-1",
            "goods_value_try": 100000,
            "freight_try": 12000,
            "customs_duty_try": 8000,
            "allocation_key": "ADET",
        }
        veri.update(kw)
        r = await client.post("/api/satinalma/ithalat", json=veri)
        assert r.status_code == 201, r.text
        return r.json()

    async def test_toplam_masraf_hesaplanir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        d = await self._dosya(client)
        assert Decimal(d["toplam_masraf"]) == Decimal("120000.00")

    async def test_ithalattaki_cihaz_stokta_gorunmez(
        self, client, kullanici_ac, tedarikci_ac, urun_ac, db
    ):
        """Gümrükteki mal rezerve edilebilir görünmemeli."""
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=2)
        d = await self._dosya(client, purchase_order_id=s["id"])

        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000100", "860000000000101"],
                "import_file_id": d["id"],
            },
        )
        cihaz = await db.scalar(select(Device).where(Device.imei == "860000000000100"))
        assert cihaz.status == "ITHALATTA"
        assert cihaz.import_file_id == d["id"]
        # İthal cihaz BTK kaydı bekler.
        assert cihaz.btk_status == "BEKLIYOR"

    async def test_adet_bazli_dagitim(self, client, kullanici_ac, tedarikci_ac, urun_ac, db):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=4)
        d = await self._dosya(client, purchase_order_id=s["id"], allocation_key="ADET")
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": [f"86000000000011{i}" for i in range(4)],
                "import_file_id": d["id"],
            },
        )

        r = await client.post(f"/api/satinalma/ithalat/{d['id']}/landed-cost")
        assert r.status_code == 200, r.text
        assert r.json()["cihaz_sayisi"] == 4
        assert Decimal(r.json()["birim_ortalama"]) == Decimal("30000.00")

        maliyetler = [
            c.landed_cost_try
            for c in (
                await db.scalars(select(Device).where(Device.import_file_id == d["id"]))
            ).all()
        ]
        assert all(Decimal(str(m)) == Decimal("30000.00") for m in maliyetler)

    async def test_yuvarlama_artigi_kaybolmaz(
        self, client, kullanici_ac, tedarikci_ac, urun_ac, db
    ):
        """Dosya toplamı = cihaz maliyetleri toplamı; muhasebe bunu kontrol eder."""
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=3)
        d = await self._dosya(
            client,
            purchase_order_id=s["id"],
            goods_value_try=1000,
            freight_try=0.01,
            customs_duty_try=0,
            allocation_key="ADET",
        )
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": [f"86000000000012{i}" for i in range(3)],
                "import_file_id": d["id"],
            },
        )
        await client.post(f"/api/satinalma/ithalat/{d['id']}/landed-cost")

        toplam = sum(
            Decimal(str(c.landed_cost_try))
            for c in (
                await db.scalars(select(Device).where(Device.import_file_id == d["id"]))
            ).all()
        )
        assert toplam == Decimal("1000.01")

    async def test_tutar_bazli_dagitim_pahaliya_daha_cok_yazar(
        self, client, kullanici_ac, tedarikci_ac, urun_ac, db
    ):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        ucuz = await urun_ac("KABLO", "SERI_NO")
        pahali = await urun_ac("L300", "IMEI")

        r = await client.post(
            "/api/satinalma/siparisler",
            json={
                "supplier_id": t.id,
                "kalemler": [
                    {"product_id": ucuz.id, "qty": 1, "unit_price": 10},
                    {"product_id": pahali.id, "qty": 1, "unit_price": 90},
                ],
            },
        )
        s = r.json()
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/durum", json={"durum": "SIPARIS_VERILDI"}
        )
        d = await self._dosya(
            client,
            purchase_order_id=s["id"],
            goods_value_try=1000,
            freight_try=0,
            customs_duty_try=0,
            allocation_key="TUTAR",
        )
        for kalem, kimlik in zip(s["kalemler"], ["SN-UCUZ", "860000000000130"], strict=True):
            await client.post(
                f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
                json={
                    "kalem_id": kalem["id"],
                    "kimlikler": [kimlik],
                    "import_file_id": d["id"],
                },
            )
        await client.post(f"/api/satinalma/ithalat/{d['id']}/landed-cost")

        ucuz_c = await db.scalar(select(Device).where(Device.serial_no == "SN-UCUZ"))
        pahali_c = await db.scalar(select(Device).where(Device.imei == "860000000000130"))
        assert Decimal(str(ucuz_c.landed_cost_try)) == Decimal("100.00")
        assert Decimal(str(pahali_c.landed_cost_try)) == Decimal("900.00")

    async def test_cihazsiz_dosya_dagitilamaz(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        d = await self._dosya(client)
        r = await client.post(f"/api/satinalma/ithalat/{d['id']}/landed-cost")
        assert r.status_code == 409
        assert "mal kabul" in r.json()["detail"]

    async def test_yeniden_dagitilabilir(self, client, kullanici_ac, tedarikci_ac, urun_ac, db):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=2)
        d = await self._dosya(
            client,
            purchase_order_id=s["id"],
            goods_value_try=1000,
            freight_try=0,
            customs_duty_try=0,
            allocation_key="ADET",
        )
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000140", "860000000000141"],
                "import_file_id": d["id"],
            },
        )
        dagitim = await client.post(f"/api/satinalma/ithalat/{d['id']}/landed-cost")

        # Navlun faturası sonradan geldi. Dağıtım dosyayı DEĞİŞTİRDİĞİ için
        # sürüm ilerledi; istemci güncel sürümle yazar — ilk yükleme anındaki
        # sürümle gelen istek iyimser kilide takılır (ve takılmalıdır).
        guncel_surum = dagitim.json()["dosya"]["version"]
        guncel = await client.patch(
            f"/api/satinalma/ithalat/{d['id']}",
            json={
                **{k: v for k, v in d.items() if k in {"allocation_key", "invoice_no"}},
                "goods_value_try": 1000,
                "freight_try": 200,
                "status": "ACIK",
                "version": guncel_surum,
            },
        )
        assert guncel.status_code == 200, guncel.text
        await client.post(f"/api/satinalma/ithalat/{d['id']}/landed-cost")

        cihaz = await db.scalar(select(Device).where(Device.imei == "860000000000140"))
        await db.refresh(cihaz)
        assert Decimal(str(cihaz.landed_cost_try)) == Decimal("600.00")

    async def test_gecersiz_dagitim_anahtari(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await client.post("/api/satinalma/ithalat", json={"allocation_key": "HACIM"})
        assert r.status_code == 400


class TestMaliyetGorunurlugu:
    async def test_maliyet_yetkisiz_gizlenir(self, client, kullanici_ac, tedarikci_ac, urun_ac):
        """Maliyet VARSAYILAN OLARAK gizli (plan §3.4)."""
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=1)
        r = await client.post("/api/satinalma/ithalat", json={"goods_value_try": 500})
        d = r.json()
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000150"],
                "import_file_id": d["id"],
            },
        )
        await client.post(f"/api/satinalma/ithalat/{d['id']}/landed-cost")

        yetkili = await client.get(f"/api/satinalma/ithalat/{d['id']}/cihazlar")
        assert yetkili.json()[0]["landed_cost_try"] == 500.0

        await client.post("/api/auth/logout")
        await _giris(client, kullanici_ac, "depocu", "DEPO")
        # DEPO'da satinalma.gor var ama maliyet.gor yok.
        depo = await client.get(f"/api/satinalma/ithalat/{d['id']}/cihazlar")
        assert depo.status_code == 200
        assert depo.json()[0]["landed_cost_try"] is None
        assert depo.json()[0]["kimlik"] == "860000000000150"


class TestBtk:
    async def test_bekleyen_listesi_ve_kayit(self, client, kullanici_ac, tedarikci_ac, urun_ac, db):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI", ce_document_ref="CE-2026-01")
        s = await _siparis_ac(client, t, u, adet=2)
        r = await client.post("/api/satinalma/ithalat", json={"customs_declaration_no": "GTB-9"})
        d = r.json()
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000200", "860000000000201"],
                "import_file_id": d["id"],
            },
        )

        bekleyen = await client.get("/api/satinalma/btk/bekleyenler")
        assert bekleyen.status_code == 200, bekleyen.text
        assert len(bekleyen.json()) == 2
        satir = bekleyen.json()[0]
        assert satir["ce_belgesi"] == "CE-2026-01"
        assert satir["gumruk_beyanname"] == "GTB-9"

        kaydet = await client.post(
            "/api/satinalma/btk/kaydet",
            json={"device_ids": [x["device_id"] for x in bekleyen.json()], "referans": "BTK-77"},
        )
        assert kaydet.json()["kaydedilen"] == 2

        assert (await client.get("/api/satinalma/btk/bekleyenler")).json() == []
        cihaz = await db.scalar(select(Device).where(Device.imei == "860000000000200"))
        await db.refresh(cihaz)
        assert cihaz.btk_status == "KAYITLI"
        assert cihaz.btk_reference == "BTK-77"

    async def test_yurt_ici_alim_btk_gerektirmez(
        self, client, kullanici_ac, tedarikci_ac, urun_ac, db
    ):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=1)
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={"kalem_id": s["kalemler"][0]["id"], "kimlikler": ["860000000000210"]},
        )
        cihaz = await db.scalar(select(Device).where(Device.imei == "860000000000210"))
        assert cihaz.btk_status == "GEREKMIYOR"
        assert (await client.get("/api/satinalma/btk/bekleyenler")).json() == []

    async def test_xlsx_indirilebilir(self, client, kullanici_ac, tedarikci_ac, urun_ac):
        await _giris(client, kullanici_ac)
        t = await tedarikci_ac()
        u = await urun_ac("L300", "IMEI")
        s = await _siparis_ac(client, t, u, adet=1)
        d = (await client.post("/api/satinalma/ithalat", json={})).json()
        await client.post(
            f"/api/satinalma/siparisler/{s['id']}/mal-kabul",
            json={
                "kalem_id": s["kalemler"][0]["id"],
                "kimlikler": ["860000000000220"],
                "import_file_id": d["id"],
            },
        )
        r = await client.get("/api/satinalma/btk/bekleyenler.xlsx")
        assert r.status_code == 200
        assert r.content[:2] == b"PK"


class TestYetki:
    async def test_satis_satinalma_goremez(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        assert (await client.get("/api/satinalma/siparisler")).status_code == 403

    async def test_depo_satinalma_gorur_yazamaz(self, client, kullanici_ac, tedarikci_ac):
        await _giris(client, kullanici_ac, "depocu", "DEPO")
        assert (await client.get("/api/satinalma/siparisler")).status_code == 200
        r = await client.post("/api/satinalma/siparisler", json={"supplier_id": 1, "kalemler": []})
        assert r.status_code == 403


class TestSafHesap:
    def test_dosya_toplami(self):
        from app.models import ImportFile

        d = ImportFile(
            file_no="X",
            goods_value_try=Decimal("1000"),
            freight_try=Decimal("120.50"),
            insurance_try=Decimal("0"),
            customs_duty_try=Decimal("80"),
            other_tax_try=Decimal("0"),
            broker_fee_try=Decimal("250"),
            inland_freight_try=Decimal("0"),
            other_cost_try=Decimal("49.50"),
        )
        assert dosya_toplami(d) == Decimal("1500.00")
