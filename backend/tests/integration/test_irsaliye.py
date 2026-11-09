"""İrsaliye, serisiz sevk, muhasebe devri, Logo dökümü, sipariş onayı ve servis fişleri.

KARARLAR 2026-11-09 S4.3 / S4.4 / S6.
"""

import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import (
    Account,
    Address,
    AuditLog,
    BelgeSayaci,
    Irsaliye,
    Order,
    StockMovement,
    Transfer,
    Warehouse,
)

pytestmark = pytest.mark.integration

URL = "/api/irsaliyeler"


async def _giris(client, kullanici_ac, username: str, rol: str) -> None:
    await kullanici_ac(username, rol)
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _oturum(client, username: str) -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


@pytest.fixture
def pdf_html(monkeypatch):
    """PDF motoru yerine şablonun HTML'ini döndürür: şablon GERÇEK bağlamla
    işlenir (eksik anahtar/şablon hatası yakalanır), Pango gerekmez."""
    from app.services import pdf as pdf_svc

    async def _sahte(sablon: str, **baglam):
        return pdf_svc.html_uret(sablon, **baglam).encode("utf-8")

    monkeypatch.setattr(pdf_svc, "pdf_uret_async", _sahte)


@pytest.fixture
async def ortam(db, urun_ac, cihaz_ac):
    """Müşteri (adresli), IMEI ürünü + 3 cihaz, serisiz aksesuar ve depo."""
    m = Account(title="Şirin Lojistik A.Ş.", is_musteri=True, tax_no="1234567890")
    db.add(m)
    await db.commit()
    await db.refresh(m)
    db.add(Address(account_id=m.id, line="Atatürk Cad. No:1", district="Çankaya", city="Ankara"))
    depo = Warehouse(code="MRK", name="Merkez Depo", location_type="MERKEZ_DEPO")
    db.add(depo)
    await db.commit()
    await db.refresh(depo)
    cihazli = await urun_ac("L300", "IMEI", list_price=Decimal("1000"), vat_rate=Decimal("0.20"))
    aksesuar = await urun_ac("KBL1", "YOK", list_price=Decimal("50"), vat_rate=Decimal("0.20"))
    cihazlar = [await cihaz_ac(imei=f"86000000000900{i}", urun=cihazli) for i in range(3)]
    db.add(StockMovement(product_id=aksesuar.id, warehouse_id=depo.id, qty=10, reason="GIRIS"))
    await db.commit()
    return {"m": m, "depo": depo, "cihazli": cihazli, "aksesuar": aksesuar, "cihazlar": cihazlar}


async def _siparis(client, o, *, cihaz_adet=2, aksesuar_adet=5) -> dict:
    kalemler = []
    if cihaz_adet:
        kalemler.append({"product_id": o["cihazli"].id, "qty": cihaz_adet})
    if aksesuar_adet:
        kalemler.append({"product_id": o["aksesuar"].id, "qty": aksesuar_adet})
    r = await client.post("/api/siparisler", json={"customer_id": o["m"].id, "kalemler": kalemler})
    assert r.status_code == 201, r.text
    onay = await client.post(f"/api/siparisler/{r.json()['id']}/onayla")
    assert onay.status_code == 200, onay.text
    return onay.json()


def _kalem(s: dict, urun_id: int) -> dict:
    return next(k for k in s["kalemler"] if k["product_id"] == urun_id)


async def _rezerve(client, s, o, imeiler):
    r = await client.post(
        f"/api/siparisler/{s['id']}/rezerve",
        json={"kalem_id": _kalem(s, o["cihazli"].id)["id"], "kimlikler": imeiler},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _bakiye(db, urun_id: int) -> int:
    return int(
        await db.scalar(
            select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
                StockMovement.product_id == urun_id
            )
        )
    )


class TestSiparisSevkiIrsaliye:
    async def test_sevk_numarali_irsaliye_ve_serisiz_stok_dusumu(
        self, client, db, kullanici_ac, ortam
    ):
        o = ortam
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        s = await _siparis(client, o)
        await _rezerve(client, s, o, ["860000000009000", "860000000009001"])

        r = await client.post(
            f"/api/siparisler/{s['id']}/sevk",
            json={
                "from_warehouse_id": o["depo"].id,
                "serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 3}],
            },
        )
        assert r.status_code == 200, r.text
        sevk = r.json()
        assert sevk["irsaliye_no"] == "IRS2026-000001"
        assert sevk["siparis"]["status"] == "KISMI_SEVK"  # 2 aksesuar kaldı

        irs = (await client.get(f"{URL}/{sevk['irsaliye_id']}")).json()
        assert irs["alici_unvan"] == "Şirin Lojistik A.Ş."
        assert irs["alici_vkn"] == "1234567890"
        assert "Çankaya" in irs["alici_adres"]
        assert irs["cikis_depo_adi"] == "Merkez Depo"
        cihaz_satiri = next(k for k in irs["kalemler"] if k["product_id"] == o["cihazli"].id)
        assert Decimal(cihaz_satiri["miktar"]) == 2
        assert cihaz_satiri["seri_nolar"] == "860000000009000, 860000000009001"
        aks = next(k for k in irs["kalemler"] if k["product_id"] == o["aksesuar"].id)
        assert Decimal(aks["miktar"]) == 3
        # Satışçı sipariş fiyatını görür → irsaliye satırında da var.
        assert Decimal(aks["birim_fiyat"]) == Decimal("50.00")

        # Serisiz kalem stoktan düştü; hareketin belge no'su irsaliye no.
        assert await _bakiye(db, o["aksesuar"].id) == 7
        hareket = await db.scalar(
            select(StockMovement).where(
                StockMovement.product_id == o["aksesuar"].id, StockMovement.qty < 0
            )
        )
        assert hareket.document_no == "IRS2026-000001" and hareket.reason == "CIKIS"
        assert hareket.warehouse_id == o["depo"].id

        transfer = await db.get(Transfer, sevk["transfer_id"])
        assert transfer.document_no == "IRS2026-000001"
        assert (await client.get(f"/api/siparisler/{s['id']}")).json()["irsaliyeler"][0][
            "irsaliye_no"
        ] == "IRS2026-000001"

        # Kalan aksesuarlar ikinci sevkle: numara boşluksuz devam eder; yalnız
        # serisiz sevk (açık rezervasyon yok) sipariş tamamen sevk edilir.
        r2 = await client.post(
            f"/api/siparisler/{s['id']}/sevk",
            json={
                "from_warehouse_id": o["depo"].id,
                "yalniz_secilenler": True,
                "serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 2}],
            },
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["irsaliye_no"] == "IRS2026-000002"
        assert r2.json()["siparis"]["status"] == "SEVK_EDILDI"
        assert await _bakiye(db, o["aksesuar"].id) == 5

        # Cihazsız sevkiyat da teslim alınabilir (konum güncellenecek cihaz yok).
        t2 = r2.json()["transfer_id"]
        teslim = await client.post(f"/api/siparisler/sevkiyat/{t2}/teslim", json={})
        assert teslim.status_code == 200, teslim.text

        log = await db.scalar(
            select(AuditLog).where(AuditLog.entity == "irsaliyeler", AuditLog.action == "olustur")
        )
        assert log is not None

    async def test_stok_yetersizse_sevk_reddedilir_numara_yanmaz(
        self, client, db, kullanici_ac, ortam
    ):
        o = ortam
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        s = await _siparis(client, o, cihaz_adet=0, aksesuar_adet=20)
        kalem = _kalem(s, o["aksesuar"].id)["id"]

        r = await client.post(
            f"/api/siparisler/{s['id']}/sevk",
            json={"from_warehouse_id": o["depo"].id, "serisiz": [{"kalem_id": kalem, "adet": 11}]},
        )
        assert r.status_code == 409
        assert "Stok yetersiz" in r.json()["detail"]
        assert await _bakiye(db, o["aksesuar"].id) == 10
        assert await db.scalar(select(func.count()).select_from(Irsaliye)) == 0
        assert await db.scalar(select(func.count()).select_from(BelgeSayaci)) == 0

        ok = await client.post(
            f"/api/siparisler/{s['id']}/sevk",
            json={"from_warehouse_id": o["depo"].id, "serisiz": [{"kalem_id": kalem, "adet": 4}]},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["irsaliye_no"] == "IRS2026-000001"

    async def test_serisiz_sevk_kurallari(self, client, db, kullanici_ac, ortam):
        o = ortam
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        s = await _siparis(client, o, cihaz_adet=1, aksesuar_adet=2)
        sevk = f"/api/siparisler/{s['id']}/sevk"
        # Kalan adetten fazla
        r = await client.post(
            sevk, json={"serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 3}]}
        )
        assert r.status_code == 409 and "kalan adet" in r.json()["detail"]
        # Seri numaralı kalem serisiz sevk edilemez
        r = await client.post(
            sevk, json={"serisiz": [{"kalem_id": _kalem(s, o["cihazli"].id)["id"], "adet": 1}]}
        )
        assert r.status_code == 409 and "seri numaralı" in r.json()["detail"]
        # Hiçbir şey seçilmedi
        r = await client.post(sevk, json={"yalniz_secilenler": True})
        assert r.status_code == 409
        # Servis deposundan satış sevki yok
        sd = Warehouse(code="SRV", name="Servis", servis_deposu=True, birim="GUVENLIK")
        db.add(sd)
        await db.commit()
        r = await client.post(
            sevk,
            json={
                "from_warehouse_id": sd.id,
                "serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 1}],
            },
        )
        assert r.status_code == 409


class TestStokTransferiIrsaliye:
    async def test_dis_transfer_irsaliye_uretir_ic_transfer_uretmez(
        self, client, db, kullanici_ac, ortam
    ):
        o = ortam
        bayi = Account(title="İzmir Bayi", is_bayi=True)
        db.add(bayi)
        await db.commit()
        await _giris(client, kullanici_ac, "depocu", "DEPO")

        alicisiz = await client.post(
            "/api/stok/transferler",
            json={
                "type": "SATIS",
                "from_location_type": "MERKEZ_DEPO",
                "to_location_type": "BAYI",
                "kimlikler": ["860000000009000"],
            },
        )
        assert alicisiz.status_code == 400
        assert await db.scalar(select(func.count()).select_from(Transfer)) == 0

        r = await client.post(
            "/api/stok/transferler",
            json={
                "type": "SATIS",
                "from_location_type": "MERKEZ_DEPO",
                "from_warehouse_id": o["depo"].id,
                "to_location_type": "BAYI",
                "to_account_id": bayi.id,
                "new_ownership": "BAYI_SATILDI",
                "kimlikler": ["860000000009000", "860000000009001"],
            },
        )
        assert r.status_code == 201, r.text
        t = r.json()
        assert t["irsaliye_no"] == "IRS2026-000001"
        assert t["document_no"] == "IRS2026-000001"
        irs = (await client.get(f"{URL}/{t['irsaliye_id']}")).json()
        assert irs["alici_unvan"] == "İzmir Bayi" and irs["hedef_konum"] == "BAYI"
        assert Decimal(irs["kalemler"][0]["miktar"]) == 2
        # Depo kullanıcısı sipariş fiyatı görmez; anahtar hiç yok.
        assert "birim_fiyat" not in irs["kalemler"][0]

        teknisyene = await client.post(
            "/api/stok/transferler",
            json={
                "type": "IC_TRANSFER",
                "from_location_type": "MERKEZ_DEPO",
                "to_location_type": "TEKNISYEN",
                "kimlikler": ["860000000009002"],
            },
        )
        assert teknisyene.status_code == 201, teknisyene.text
        assert teknisyene.json()["irsaliye_id"] is None
        assert await db.scalar(select(func.count()).select_from(Irsaliye)) == 1


class TestKapsamVeFiyat:
    async def test_satisci_baskasinin_irsaliyesini_goremez(self, client, db, kullanici_ac, ortam):
        o = ortam
        await _giris(client, kullanici_ac, "satis_a", "SATIS")
        s = await _siparis(client, o, cihaz_adet=0, aksesuar_adet=1)
        sevk = await client.post(
            f"/api/siparisler/{s['id']}/sevk",
            json={"serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 1}]},
        )
        irs_id = sevk.json()["irsaliye_id"]

        await _giris(client, kullanici_ac, "satis_b", "SATIS")
        assert (await client.get(f"{URL}/{irs_id}")).status_code == 404
        assert (await client.get(f"{URL}/{irs_id}/pdf")).status_code == 404
        assert (await client.get(URL)).json() == []

    async def test_pdf_fiyat_yalniz_yetkiliye(self, client, db, kullanici_ac, ortam, pdf_html):
        o = ortam
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        s = await _siparis(client, o, cihaz_adet=0, aksesuar_adet=2)
        sevk = await client.post(
            f"/api/siparisler/{s['id']}/sevk",
            json={"serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 2}]},
        )
        irs_id = sevk.json()["irsaliye_id"]

        fiyatsiz = (await client.get(f"{URL}/{irs_id}/pdf")).content.decode()
        assert "SEVK İRSALİYESİ" in fiyatsiz and "IRS2026-000001" in fiyatsiz
        assert "Şirin Lojistik A.Ş." in fiyatsiz
        assert "Birim fiyat" not in fiyatsiz
        fiyatli = (await client.get(f"{URL}/{irs_id}/pdf", params={"fiyatli": True})).content
        assert "Birim fiyat" in fiyatli.decode() and "50,00" in fiyatli.decode()

        # Depo kullanıcısı `fiyatli=true` istese de fiyatsız alır.
        await _giris(client, kullanici_ac, "depocu", "DEPO")
        depo = (await client.get(f"{URL}/{irs_id}/pdf", params={"fiyatli": True})).content
        assert "Birim fiyat" not in depo.decode()

    async def test_pdf_motoru_yoksa_503(self, client, kullanici_ac, ortam, monkeypatch):
        from app.services import pdf as pdf_svc

        async def _bozuk(*_a, **_k):
            raise pdf_svc.PdfUretilemedi("yok")

        monkeypatch.setattr(pdf_svc, "pdf_uret_async", _bozuk)
        o = ortam
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        s = await _siparis(client, o, cihaz_adet=0, aksesuar_adet=1)
        sevk = await client.post(
            f"/api/siparisler/{s['id']}/sevk",
            json={"serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 1}]},
        )
        assert (await client.get(f"{URL}/{sevk.json()['irsaliye_id']}/pdf")).status_code == 503
        assert (await client.get(f"/api/siparisler/{s['id']}/onay.pdf")).status_code == 503


class TestIptalVeMuhasebeDevri:
    async def _iki_irsaliye(self, client, kullanici_ac, o) -> list[dict]:
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        s = await _siparis(client, o, cihaz_adet=0, aksesuar_adet=2)
        sonuc = []
        for _ in range(2):
            r = await client.post(
                f"/api/siparisler/{s['id']}/sevk",
                json={"serisiz": [{"kalem_id": _kalem(s, o["aksesuar"].id)["id"], "adet": 1}]},
            )
            assert r.status_code == 200, r.text
            sonuc.append((await client.get(f"{URL}/{r.json()['irsaliye_id']}")).json())
        return sonuc

    async def test_iptal_numarayi_korur_ve_kilitlenir(self, client, kullanici_ac, ortam):
        ilk, ikinci = await self._iki_irsaliye(client, kullanici_ac, ortam)
        bayat = await client.post(
            f"{URL}/{ilk['id']}/iptal", json={"neden": "Hatalı adres", "version": 99}
        )
        assert bayat.status_code == 409
        r = await client.post(
            f"{URL}/{ilk['id']}/iptal", json={"neden": "Hatalı adres", "version": ilk["version"]}
        )
        assert r.status_code == 200, r.text
        assert r.json()["durum"] == "IPTAL" and r.json()["irsaliye_no"] == "IRS2026-000001"
        tekrar = await client.post(
            f"{URL}/{ilk['id']}/iptal", json={"neden": "Yine", "version": r.json()["version"]}
        )
        assert tekrar.status_code == 409
        # İptal edilen devre uygun değildir.
        await _giris(client, kullanici_ac, "finans", "MUHASEBE_DESTEK")
        bekleyen = (await client.get(URL, params={"devir": "bekleyen"})).json()
        assert [i["irsaliye_no"] for i in bekleyen] == ["IRS2026-000002"]

    async def test_devir_toplu_butun_ve_geri_alma(self, client, db, kullanici_ac, ortam):
        ilk, ikinci = await self._iki_irsaliye(client, kullanici_ac, ortam)
        # Satışçı devredemez
        r = await client.post(f"{URL}/muhasebe-devri", json={"irsaliye_idler": [ilk["id"]]})
        assert r.status_code == 403

        await _giris(client, kullanici_ac, "finans", "MUHASEBE_DESTEK")
        r = await client.post(
            f"{URL}/muhasebe-devri", json={"irsaliye_idler": [ilk["id"]], "not": "Kasım"}
        )
        assert r.status_code == 200, r.text
        # Biri zaten devredilmiş → tamamı 409, ikinci de işaretlenmez
        r = await client.post(
            f"{URL}/muhasebe-devri", json={"irsaliye_idler": [ilk["id"], ikinci["id"]]}
        )
        assert r.status_code == 409
        assert r.json()["detail"]["sorunlu"] == [ilk["id"]]
        assert (await client.get(f"{URL}/{ikinci['id']}")).json()["muhasebe_devri_at"] is None

        devredilen = (await client.get(URL, params={"devir": "devredildi"})).json()
        assert [i["id"] for i in devredilen] == [ilk["id"]]
        assert devredilen[0]["muhasebe_notu"] == "Kasım"
        assert devredilen[0]["muhasebe_devreden"] == "Finans"

        # Devredilmiş irsaliye iptal edilemez
        await _oturum(client, "satisci")
        guncel = (await client.get(f"{URL}/{ilk['id']}")).json()
        r = await client.post(
            f"{URL}/{ilk['id']}/iptal", json={"neden": "Deneme", "version": guncel["version"]}
        )
        assert r.status_code == 409

        await _oturum(client, "finans")
        assert (
            await client.post(f"{URL}/{ilk['id']}/muhasebe-devri/geri-al", json={"gerekce": ""})
        ).status_code == 422
        r = await client.post(
            f"{URL}/{ilk['id']}/muhasebe-devri/geri-al", json={"gerekce": "Yanlış dönem"}
        )
        assert r.status_code == 200 and r.json()["muhasebe_devri_at"] is None
        assert await db.scalar(
            select(AuditLog).where(
                AuditLog.entity == "irsaliyeler", AuditLog.action == "muhasebe.geri_al"
            )
        )

    async def test_logo_dokumu_xlsx_csv_ve_fiyat_kolonu(self, client, kullanici_ac, ortam):
        await self._iki_irsaliye(client, kullanici_ac, ortam)
        await _giris(client, kullanici_ac, "finans", "MUHASEBE_DESTEK")
        r = await client.get(f"{URL}/logo-aktarim", params={"devir": "bekleyen"})
        assert r.status_code == 200, r.text
        ws = load_workbook(io.BytesIO(r.content)).active
        basliklar = [h.value for h in ws[1]]
        assert basliklar[:3] == ["Fiş Türü", "İrsaliye No", "İrsaliye Tarihi"]
        assert "Birim Fiyat" in basliklar  # finans teklif/sipariş fiyatını görür
        assert [ws.cell(row=i, column=2).value for i in (2, 3)] == [
            "IRS2026-000001",
            "IRS2026-000002",
        ]
        assert ws.cell(row=2, column=6).value == "Şirin Lojistik A.Ş."

        csv_ = await client.get(f"{URL}/logo-aktarim", params={"bicim": "csv"})
        assert csv_.status_code == 200
        assert csv_.content.startswith(b"\xef\xbb\xbf")
        metin = csv_.content.decode("utf-8-sig")
        assert metin.splitlines()[0].startswith("Fiş Türü;İrsaliye No;")
        assert "IRS2026-000002" in metin and "Şirin Lojistik A.Ş." in metin
        assert ";50,00;" in metin

        # Depo: dışa aktarabilir ama fiyat kolonu yok.
        await _giris(client, kullanici_ac, "depocu", "DEPO")
        ws = load_workbook(io.BytesIO((await client.get(f"{URL}/logo-aktarim")).content)).active
        assert "Birim Fiyat" not in [h.value for h in ws[1]]


class TestSiparisBelgeleri:
    async def test_siparis_onayi_pdf(self, client, kullanici_ac, ortam, pdf_html):
        o = ortam
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        taslak = await client.post(
            "/api/siparisler",
            json={
                "customer_id": o["m"].id,
                "kalemler": [{"product_id": o["aksesuar"].id, "qty": 2}],
            },
        )
        assert (
            await client.get(f"/api/siparisler/{taslak.json()['id']}/onay.pdf")
        ).status_code == 409
        await client.post(f"/api/siparisler/{taslak.json()['id']}/onayla")
        r = await client.get(f"/api/siparisler/{taslak.json()['id']}/onay.pdf")
        assert r.status_code == 200
        html = r.content.decode()
        assert "SİPARİŞ ONAYI" in html and taslak.json()["order_no"] in html
        assert "Şirin Lojistik A.Ş." in html and "120,00" in html  # 2×50 + %20 KDV

    async def test_siparis_muhasebe_devri_ve_logo_dokumu(self, client, db, kullanici_ac, ortam):
        o = ortam
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        onayli = await _siparis(client, o, cihaz_adet=0, aksesuar_adet=2)
        taslak = (
            await client.post(
                "/api/siparisler",
                json={"customer_id": o["m"].id, "kalemler": [{"product_id": o["aksesuar"].id}]},
            )
        ).json()

        await _giris(client, kullanici_ac, "finans", "MUHASEBE_DESTEK")
        bekleyen = (await client.get("/api/siparisler/muhasebe-devri")).json()
        assert [s["id"] for s in bekleyen] == [onayli["id"]]  # taslak uygun değil

        r = await client.post(
            "/api/siparisler/muhasebe-devri", json={"siparis_idler": [onayli["id"], taslak["id"]]}
        )
        assert r.status_code == 409 and r.json()["detail"]["sorunlu"] == [taslak["id"]]
        r = await client.post(
            "/api/siparisler/muhasebe-devri", json={"siparis_idler": [onayli["id"]]}
        )
        assert r.status_code == 200, r.text
        siparis = await db.get(Order, onayli["id"])
        await db.refresh(siparis)
        assert siparis.muhasebe_devri_at is not None

        x = await client.get("/api/siparisler/muhasebe-aktarim", params={"devir": "devredildi"})
        assert x.status_code == 200, x.text
        ws = load_workbook(io.BytesIO(x.content)).active
        basliklar = [h.value for h in ws[1]]
        assert basliklar[0] == "Sipariş No" and "Satır Tutarı (KDV hariç)" in basliklar
        assert ws.cell(row=2, column=1).value == onayli["order_no"]
        assert ws.cell(row=2, column=7).value == "KBL1"

        r = await client.post(
            f"/api/siparisler/{onayli['id']}/muhasebe-devri/geri-al", json={"gerekce": "Hata"}
        )
        assert r.status_code == 200 and r.json()["muhasebe_devri_at"] is None

        # Satışçı devredemez, dökümü alamaz (rapor.disaaktar yok).
        await _oturum(client, "satisci")
        assert (
            await client.post("/api/siparisler/muhasebe-devri", json={"siparis_idler": [1]})
        ).status_code == 403
        assert (await client.get("/api/siparisler/muhasebe-aktarim")).status_code == 403


class TestServisFisleri:
    async def test_bakim_ve_onarim_fisi_ture_gore(
        self, client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac, urun_ac, pdf_html
    ):
        await birimli_kullanici_ac("tsm", "SERVIS_YONETICI", ["GUVENLIK"])
        await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"])
        ariza = await servis_isi_ac(tur="ARIZA", konu="Kapı açılmıyor", atananlar=())
        bakim = await servis_isi_ac(tur="PLANSIZ_BAKIM", konu="Yıllık bakım")

        # Parça çıkışı (servis defteri) onarım fişine net miktarla düşer.
        parca = await urun_ac("PRC1", "YOK")
        sd = Warehouse(code="SG1", name="Güvenlik Depo", servis_deposu=True, birim="GUVENLIK")
        db.add(sd)
        await db.commit()
        db.add(
            StockMovement(
                product_id=parca.id,
                warehouse_id=sd.id,
                qty=-2,
                reason="CIKIS",
                hareket_turu="CIKIS_SERVIS",
                service_order_id=ariza.id,
            )
        )
        await db.commit()

        await _oturum(client, "tsm")
        ts = "/api/teknik-servis/isler"
        r = await client.get(f"{ts}/{ariza.id}/onarim-fisi.pdf")
        assert r.status_code == 200, r.text
        html = r.content.decode()
        assert "ONARIM FİŞİ" in html and "Kapı açılmıyor" in html
        assert "PRC1" in html and "Süre kaydı eksik" in html
        assert "Hizmet bedeli" not in html
        assert (
            "Hizmet bedeli"
            in (
                await client.get(f"{ts}/{ariza.id}/onarim-fisi.pdf", params={"fiyatli": True})
            ).content.decode()
        )
        assert (await client.get(f"{ts}/{ariza.id}/bakim-fisi.pdf")).status_code == 409

        r = await client.get(f"{ts}/{bakim.id}/bakim-fisi.pdf")
        assert r.status_code == 200 and "BAKIM FİŞİ" in r.content.decode()
        assert (await client.get(f"{ts}/{bakim.id}/onarim-fisi.pdf")).status_code == 409

        # Teknisyen (tutar yetkisi yok) `fiyatli=true` istese de fiyatsız alır;
        # kapsamındaki iş olmalı — tayinsiz işte 404.
        await _oturum(client, "tek")
        r = await client.get(f"{ts}/{ariza.id}/onarim-fisi.pdf", params={"fiyatli": True})
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            assert "Hizmet bedeli" not in r.content.decode()


class TestGercekPdf:
    async def test_turkce_karakterler_gomulu_fontla(self, db, kullanici_ac, ortam):
        """Pango/Cairo olan ortamda (Docker) gerçek PDF: yazı tipleri gömülü."""
        try:
            import weasyprint  # noqa: F401
        except Exception:  # noqa: BLE001 — Windows'ta OSError dışı da olabilir
            pytest.skip("WeasyPrint sistem kitaplıkları bu makinede yok")
        from app.services.pdf import pdf_uret

        html_baglam = {
            "irs": type(
                "I",
                (),
                {
                    "irsaliye_no": "IRS2026-000001",
                    "alici_unvan": "Işık Çağrı Şeker Ğ Ü Ö İ",
                    "alici_vkn": None,
                    "alici_vergi_dairesi": None,
                    "alici_adres": "İstanbul",
                    "cikis_depo_adi": "Merkez",
                    "notlar": None,
                    "iptal_nedeni": None,
                    "teslim_eden": "Gökhan",
                },
            )(),
            "baslik": "SEVK İRSALİYESİ",
            "duzenleme_tarihi": "01.01.2026",
            "sevk_tarihi": "01.01.2026",
            "hedef": "Müşteri",
            "siparis_no": None,
            "transfer_no": None,
            "kalemler": [],
            "fiyatli": False,
            "toplam_miktar": "0",
            "iptal": False,
            "firma": {"unvan": "Denge", "adres": "Ataşehir", "telefon": "1"},
        }
        icerik = pdf_uret("irsaliye.html", **html_baglam)
        assert icerik.startswith(b"%PDF")
        assert b"/FontFile" in icerik  # yazı tipi PDF'e gömülü


class TestFaturaDevriCsv:
    async def test_fatura_devri_logo_csv(self, client, db, kullanici_ac, servis_isi_ac):
        from datetime import UTC, datetime

        from app.models.servis_maliyet import ServiceOrderFinancial

        await kullanici_ac("adm_csv", "ADMIN")
        so = await servis_isi_ac(
            birim="GUVENLIK",
            durum="TAMAMLANDI",
            completed_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
            kalite_onay_at=datetime(2026, 1, 1, 9, tzinfo=UTC),
        )
        db.add(
            ServiceOrderFinancial(
                service_order_id=so.id, gelir=Decimal("1234"), gelir_kaynagi="ELLE", gelir_notu="x"
            )
        )
        await db.commit()
        await _oturum(client, "adm_csv")
        r = await client.get(
            "/api/teknik-servis/maliyet/fatura-devri.xlsx", params={"bicim": "csv"}
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        metin = r.content.decode("utf-8-sig")
        baslik, satir = metin.splitlines()[:2]
        assert baslik.split(";")[0] == "İş No" and "Tutar (KDV hariç)" in baslik
        assert satir.startswith(so.so_no) and "1234,00" in satir
