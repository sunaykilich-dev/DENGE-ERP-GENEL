"""Kayıt bazlı kapsam (plan §3.4) YAZMA uçlarında da geçerli olmalı.

Gerçek bir açıktan doğdu: satış temsilcisi kendi portföyü DIŞINDAKİ bir
hesabı `PATCH /api/hesaplar/{id}` ile değiştirdiğinde kayıt gerçekten
değişiyor, cevap ise 404 dönüyordu. Kapsam filtresi yalnız en sondaki
`getir()` çağrısında, yani `commit()`ten SONRA uygulanıyordu; ne kullanıcı ne
denetçi yazmanın geçtiğini görebiliyordu.

Aynı boşluk kişi (KVKK kapsamında kişisel veri), ek/belge ve mükerrer aday
uçlarında da vardı. Ek kimlikleri sıralı olduğu için belge ucu pratikte tüm
arşivin taranmasına açıktı — vergi levhaları dahil.
"""

import pytest

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


@pytest.fixture
async def kapsam_ortami(client, db, kullanici_ac):
    """İki satış temsilcisi ve her birine ait birer hesap."""
    from app.models import Account
    from app.services.normalize import tr_normkey

    benim = await kullanici_ac("kapsam_satis", "SATIS")
    digeri = await kullanici_ac("kapsam_satis2", "SATIS")

    hesaplar = {}
    for ad, sahip in (("KAPSAM BENIM", benim), ("KAPSAM DIGERI", digeri)):
        h = Account(
            title=ad,
            title_key=tr_normkey(ad),
            is_musteri=True,
            sales_rep_id=sahip.id,
        )
        db.add(h)
        await db.flush()
        hesaplar[ad] = h
    await db.commit()
    await _giris(client, "kapsam_satis")
    return {"benim": hesaplar["KAPSAM BENIM"], "digeri": hesaplar["KAPSAM DIGERI"], "kul": benim}


class TestHesapKapsami:
    async def test_kapsam_disi_patch_yazmiyor(self, client, db, kapsam_ortami):
        """404 dönmek YETMEZ; yazmanın da GERÇEKLEŞMEMESİ gerekir."""
        hedef = kapsam_ortami["digeri"]
        cevap = await client.patch(f"/api/hesaplar/{hedef.id}", json={"notes": "SIZMA"})
        assert cevap.status_code == 404

        await db.refresh(hedef)
        assert hedef.notes is None, "kapsam dışı hesaba yazma geçti (cevap 404 olsa da)"

    async def test_kendi_hesabini_duzenleyebilir(self, client, kapsam_ortami):
        h = kapsam_ortami["benim"]
        cevap = await client.patch(f"/api/hesaplar/{h.id}", json={"notes": "kendi kaydım"})
        assert cevap.status_code == 200

    async def test_temsilci_atamasi_degistirilemez(self, client, kapsam_ortami):
        """Aksi halde kullanıcı hesabı kendine atayıp kapsamını genişletir."""
        h = kapsam_ortami["benim"]
        cevap = await client.patch(f"/api/hesaplar/{h.id}", json={"sales_rep_id": 1})
        assert cevap.status_code == 403

    async def test_mukerrer_adaylari_kapsamli(self, client, kapsam_ortami):
        """Kapsam dışı id'de unvan/VKN/telefon sızdıran bir yan yoldu."""
        hedef = kapsam_ortami["digeri"]
        cevap = await client.get(f"/api/hesaplar/{hedef.id}/mukerrer-adaylari")
        assert cevap.status_code == 404


class TestKisiKapsami:
    async def test_kapsam_disi_hesaba_kisi_eklenemez(self, client, kapsam_ortami):
        hedef = kapsam_ortami["digeri"]
        cevap = await client.post(
            f"/api/hesaplar/{hedef.id}/kisiler",
            json={"full_name": "SIZMA KISI", "is_primary": False},
        )
        assert cevap.status_code == 404

    async def test_kapsam_disi_kisi_silinemez(self, client, db, kapsam_ortami):
        """Yol `hesap_id` taşımadığı için kontrol tamamen unutulmuştu."""
        from app.models import Contact

        kisi = Contact(account_id=kapsam_ortami["digeri"].id, full_name="BAŞKASININ YETKİLİSİ")
        db.add(kisi)
        await db.commit()

        assert (await client.delete(f"/api/hesaplar/kisiler/{kisi.id}")).status_code == 404
        assert (
            await client.patch(f"/api/hesaplar/kisiler/{kisi.id}", json={"full_name": "değişti"})
        ).status_code == 404

        await db.refresh(kisi)
        assert kisi.full_name == "BAŞKASININ YETKİLİSİ"


class TestEkKapsami:
    async def test_kapsam_disi_hesabin_ekleri_gorunmez(self, client, kapsam_ortami):
        hedef = kapsam_ortami["digeri"]
        assert (await client.get(f"/api/ekler/accounts/{hedef.id}")).status_code == 404

    async def test_kapsam_disi_hesaba_ek_yuklenemez(self, client, kapsam_ortami):
        hedef = kapsam_ortami["digeri"]
        cevap = await client.post(
            f"/api/ekler/accounts/{hedef.id}",
            files={"file": ("a.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert cevap.status_code == 404

    async def test_kapsam_disi_belge_indirilemez(self, client, db, kapsam_ortami):
        """Ek kimlikleri sıralı; kapsam olmadan tüm arşiv taranabiliyordu."""
        from app.models import Attachment
        from app.services import storage as depo

        kayit = depo.yaz(b"%PDF-1.4\ngizli", mime_type="application/pdf")
        ek = Attachment(
            entity="accounts",
            entity_id=kapsam_ortami["digeri"].id,
            kind="DIGER",
            file_name="vergi-levhasi.pdf",
            storage_path=kayit.storage_path,
            mime_type=kayit.mime_type,
            size_bytes=kayit.size_bytes,
            sha256=kayit.sha256,
        )
        db.add(ek)
        await db.commit()

        assert (await client.get(f"/api/ekler/dosya/{ek.id}")).status_code == 404
        assert (await client.delete(f"/api/ekler/{ek.id}")).status_code == 404


class TestMaliyetGizleme:
    """Maliyet `maliyet.gor` iznine bağlı (plan §3.4).

    Kârlılık raporu doğru şekilde 403 veriyordu ama AYNI SAYILAR hat listesi
    ucundan herkese gidiyordu: depo, teknik servis ve hat sorumlusu hattın
    tarife/paket/APN maliyetini görüyordu.
    """

    async def test_hat_listesinde_maliyet_gizlenir(self, client, db, kullanici_ac, hat_ac):
        await hat_ac("8990011234500009999", tariff_cost=1250.50, package_cost=75.25)
        await kullanici_ac("kapsam_depo", "DEPO")
        await _giris(client, "kapsam_depo")

        cevap = await client.get("/api/hatlar?q=8990011234500009999")
        assert cevap.status_code == 200
        satir = cevap.json()[0]
        for alan in ("tariff_cost", "package_cost", "apn_cost", "aylik_maliyet"):
            assert satir[alan] is None, f"{alan} yetkisiz role sızdı"

    async def test_yetkili_maliyeti_gorur(self, client, db, kullanici_ac, hat_ac):
        await hat_ac("8990011234500008888", tariff_cost=1250.50)
        await kullanici_ac("kapsam_yonetim", "YONETIM")
        await _giris(client, "kapsam_yonetim")

        satir = (await client.get("/api/hatlar?q=8990011234500008888")).json()[0]
        assert satir["tariff_cost"] == 1250.50

    async def test_montaj_noktasi_raporu_hakedis_sizdirmaz(self, client, db, kapsam_ortami):
        """`/api/hakedis` 403 verirken bu rapor aynı tutarları açıyordu."""
        from app.models import InstallationPartner, PartnerSettlement

        nokta = kapsam_ortami["digeri"]
        nokta.is_montaj_noktasi = True
        db.add(InstallationPartner(account_id=nokta.id))
        db.add(
            PartnerSettlement(
                partner_id=nokta.id,
                period="2026-06",
                status="TASLAK",
                gross_amount=146950,
                net_payable=146950,
            )
        )
        await db.commit()

        cevap = await client.get("/api/raporlar/montaj-noktasi")
        assert cevap.status_code == 200
        satirlar = cevap.json()
        assert satirlar, "rapor boş: test hiçbir şey doğrulamıyor olurdu"
        for satir in satirlar:
            assert satir["brut"] is None
            assert satir["net"] is None
            assert satir["is_basina_maliyet"] is None

    async def test_montaj_noktasi_xlsx_yetkisize_kapali(self, client, kapsam_ortami):
        cevap = await client.get("/api/raporlar/montaj-noktasi.xlsx")
        assert cevap.status_code == 403


class TestKayitKapsamiGenisletildi:
    """Kapsam yalnız `accounts` tablosundaydı.

    Ölçülen: SATIS rolündeki kullanıcı 7.366 aracın ve 17.356 cihazın
    tamamını, müşteri unvanlarıyla birlikte, ADMIN ile birebir aynı
    görüyordu — ve `arac.yaz` izni olduğu için hepsini düzenleyebiliyordu.
    Bir atlatma değil, eksik tasarımdı.

    Kural: müşterisi kullanıcının portföyünde OLMAYAN kayıt görünmez;
    müşterisi OLMAYAN kayıt (Denge'nin kendi stoğu) görünür.
    """

    @pytest.fixture
    async def dolu_kapsam(self, db, kapsam_ortami, urun_ac, cihaz_ac):
        from app.models import Vehicle, WorkOrder
        from app.models.vehicle import plaka_anahtari

        benim, digeri = kapsam_ortami["benim"], kapsam_ortami["digeri"]
        urun = await urun_ac("KAPSAM-URUN")
        for plaka, sahip in (("34KPS001", benim), ("34KPS002", digeri)):
            db.add(Vehicle(plate=plaka, plate_key=plaka_anahtari(plaka), customer_id=sahip.id))
        # Sahipsiz araç: Denge'nin kendi kaydı, gizlenmemeli.
        db.add(Vehicle(plate="34KPS003", plate_key=plaka_anahtari("34KPS003")))
        for imei, sahip in (
            ("860000000009001", benim.id),
            ("860000000009002", digeri.id),
            ("860000000009003", None),
        ):
            await cihaz_ac(imei=imei, urun=urun, current_customer_id=sahip)
        for no, sahip in (("KPS-1", benim), ("KPS-2", digeri)):
            db.add(
                WorkOrder(
                    wo_no=no,
                    type="MONTAJ",
                    status="TAMAMLANDI",
                    customer_id=sahip.id,
                    settlement_period="2026-06",
                )
            )
        await db.commit()
        return kapsam_ortami

    async def test_arac_listesi_kapsamli(self, client, dolu_kapsam):
        plakalar = {a["plate"] for a in (await client.get("/api/araclar?q=34KPS")).json()}
        assert "34KPS001" in plakalar, "kendi müşterisinin aracı kayboldu"
        assert "34KPS002" not in plakalar, "başkasının müşterisinin aracı sızdı"
        assert "34KPS003" in plakalar, "sahipsiz araç (Denge stoğu) gizlendi"

    async def test_genel_aramada_arac_kapsamli(self, client, dolu_kapsam):
        r = await client.get("/api/arama", params={"q": "34KPS"})
        plakalar = {s["baslik"] for s in r.json() if s["tur"] == "ARAC"}
        assert plakalar == {"34KPS001", "34KPS003"}

    async def test_cihaz_listesi_kapsamli(self, client, dolu_kapsam):
        cevap = await client.get("/api/cihazlar?q=86000000000900")
        kimlikler = {c["kimlik"] for c in cevap.json()}
        assert "860000000009001" in kimlikler
        assert "860000000009002" not in kimlikler, "başkasının müşterisinin cihazı sızdı"
        assert "860000000009003" in kimlikler, "stok cihazı gizlendi"

    async def test_is_emri_listesi_kapsamli(self, client, dolu_kapsam):
        nolar = {w["wo_no"] for w in (await client.get("/api/is-emirleri?limit=200")).json()}
        assert "KPS-1" in nolar
        assert "KPS-2" not in nolar, "başkasının müşterisinin iş emri sızdı"

    async def test_kapsam_disi_arac_duzenlenemez(self, client, db, dolu_kapsam):
        from sqlalchemy import select

        from app.models import Vehicle

        arac = await db.scalar(select(Vehicle).where(Vehicle.plate == "34KPS002"))
        cevap = await client.patch(f"/api/araclar/{arac.id}", json={"notes": "SIZMA"})
        assert cevap.status_code == 404
        await db.refresh(arac)
        assert arac.notes is None, "kapsam dışı araca yazma geçti"

    async def test_sahipsiz_arac_duzenlenebilir(self, client, db, dolu_kapsam):
        from sqlalchemy import select

        from app.models import Vehicle

        arac = await db.scalar(select(Vehicle).where(Vehicle.plate == "34KPS003"))
        cevap = await client.patch(f"/api/araclar/{arac.id}", json={"notes": "stok kaydı"})
        assert cevap.status_code == 200


# --- Dalga 4 (TS-217): RMA ve cihaz kartı kapsamı, RMA eki, katalog uçları ----------

_PDF = b"%PDF-1.4\nrma"


class TestRmaVeCihazKapsami:
    """Canlı açık: liste kapsamlıydı, kart ve RMA kapsamsızdı.

    RMA listesi `limit` ile kesiliyor ve kapsam uygulamıyordu: `rma.gor`
    izni olan satış temsilcisi başka portföylerin RMA kaydını (cihaz IMEI'si,
    araç plakası, arıza metni) görüyor, tek kayıt ucundan sıralı kimlikle
    açabiliyordu. Cihaz kartı da aynı şekilde IMEI ya da kimlikle açılıyordu.
    """

    @pytest.fixture
    async def rma_ortami(self, client, db, rol_ac, kullanici_ac, urun_ac, cihaz_ac):
        from datetime import date

        from app.models import Account, RmaCase

        await rol_ac(
            "T_RMA_TEMSILCI",
            ["rma.gor", "rma.yaz", "cihaz.gor", "cihaz.yaz"],
            "KENDI_MUSTERILERI",
        )
        benim_kul = await kullanici_ac("rma_temsilci", "T_RMA_TEMSILCI")
        diger_kul = await kullanici_ac("rma_temsilci2", "T_RMA_TEMSILCI")
        benim = Account(title="RMA BENIM", is_musteri=True, sales_rep_id=benim_kul.id)
        digeri = Account(title="RMA DIGERI", is_musteri=True, sales_rep_id=diger_kul.id)
        db.add_all([benim, digeri])
        await db.commit()
        urun = await urun_ac("RMA-KAPSAM")
        cihazlar = {
            "benim": await cihaz_ac(
                imei="862000000000011", urun=urun, current_customer_id=benim.id
            ),
            "digeri": await cihaz_ac(
                imei="862000000000022", urun=urun, current_customer_id=digeri.id
            ),
            "stok": await cihaz_ac(imei="862000000000033", urun=urun),
        }
        kayitlar = {}
        for i, (ad, musteri) in enumerate(
            (("benim", benim), ("digeri", digeri), ("stok", None)), start=1
        ):
            k = RmaCase(
                rma_no=f"RMA-KPS-{i}",
                device_id=cihazlar[ad].id,
                customer_id=musteri.id if musteri else None,
                received_at=date(2026, 1, 10),
                fault_description="Açılmıyor",
            )
            db.add(k)
            kayitlar[ad] = k
        await db.commit()
        r = await _giris(client, "rma_temsilci")
        assert r.status_code == 200, r.text
        return {"rma": kayitlar, "cihaz": cihazlar}

    async def test_rma_listesi_kapsamli_ve_sayfali(self, client, rma_ortami):
        cevap = await client.get("/api/rma", params={"limit": 200})
        assert cevap.status_code == 200
        nolar = {k["rma_no"] for k in cevap.json()}
        assert "RMA-KPS-1" in nolar, "kendi müşterisinin RMA'sı kayboldu"
        assert "RMA-KPS-2" not in nolar, "başka portföyün RMA'sı sızdı"
        assert "RMA-KPS-3" in nolar, "müşterisiz (stok) RMA gizlendi"
        assert cevap.headers["X-Toplam-Kayit"] == "2"
        # Sayfalama: ikinci sayfa ilkinin devamı, kesme yok.
        s1 = (await client.get("/api/rma", params={"limit": 1, "offset": 0})).json()
        s2 = (await client.get("/api/rma", params={"limit": 1, "offset": 1})).json()
        assert {s1[0]["rma_no"], s2[0]["rma_no"]} == {"RMA-KPS-1", "RMA-KPS-3"}

    async def test_kapsam_disi_rma_404_ve_yazma_olmaz(self, client, db, rma_ortami):
        hedef = rma_ortami["rma"]["digeri"]
        assert (await client.get(f"/api/rma/{hedef.id}")).status_code == 404
        r = await client.patch(
            f"/api/rma/{hedef.id}/tedarikci",
            json={"supplier_rma_no": "SIZMA", "version": hedef.version},
        )
        assert r.status_code == 404
        r = await client.post(f"/api/rma/{hedef.id}/durum", json={"durum": "INCELEMEDE"})
        assert r.status_code == 404
        await db.refresh(hedef)
        assert hedef.supplier_rma_no is None
        assert hedef.status == "ACIK"

    async def test_kapsam_disi_cihazla_rma_acilamaz(self, client, rma_ortami):
        r = await client.post(
            "/api/rma",
            json={"kimlik": "862000000000022", "fault_description": "Sızma denemesi"},
        )
        assert r.status_code == 404

    async def test_kendi_rmasi_acilir(self, client, rma_ortami):
        k = rma_ortami["rma"]["benim"]
        assert (await client.get(f"/api/rma/{k.id}")).status_code == 200

    async def test_rmaya_ek_yuklenir_kapsam_disina_yuklenemez(self, client, rma_ortami):
        benim = rma_ortami["rma"]["benim"]
        digeri = rma_ortami["rma"]["digeri"]
        dosya = {"file": ("ariza.pdf", _PDF, "application/pdf")}
        r = await client.post(f"/api/ekler/rma_cases/{benim.id}", files=dosya)
        assert r.status_code == 201, r.text
        liste = await client.get(f"/api/ekler/rma_cases/{benim.id}")
        assert [e["file_name"] for e in liste.json()] == ["ariza.pdf"]
        r = await client.post(f"/api/ekler/rma_cases/{digeri.id}", files=dosya)
        assert r.status_code == 404
        assert (await client.get(f"/api/ekler/rma_cases/{digeri.id}")).status_code == 404

    async def test_rma_eki_izinsiz_role_kapali(self, client, db, kullanici_ac, rma_ortami):
        """`rma.gor` olmayan rol RMA ekini göremez (DEPO)."""
        await kullanici_ac("rma_depo", "DEPO")
        await _giris(client, "rma_depo")
        k = rma_ortami["rma"]["stok"]
        assert (await client.get(f"/api/ekler/rma_cases/{k.id}")).status_code == 403

    async def test_cihaz_karti_kapsamli(self, client, rma_ortami):
        c = rma_ortami["cihaz"]
        assert (await client.get("/api/cihazlar/862000000000011")).status_code == 200
        assert (await client.get("/api/cihazlar/862000000000033")).status_code == 200
        assert (await client.get("/api/cihazlar/862000000000022")).status_code == 404
        assert (await client.get(f"/api/cihazlar/{c['digeri'].id}")).status_code == 404

    async def test_genel_arama_cihazda_kapsamli(self, client, rma_ortami):
        """Genel arama kart/liste kuralının yan yoluydu (IMEI + ürün sızıyordu)."""
        r = await client.get("/api/arama", params={"q": "86200000000"})
        assert r.status_code == 200
        bulunan = {s["baslik"] for s in r.json() if s["tur"] == "CIHAZ"}
        assert bulunan == {"862000000000011", "862000000000033"}

    async def test_kapsam_disi_cihaz_durumu_degismez(self, client, db, rma_ortami):
        hedef = rma_ortami["cihaz"]["digeri"]
        once = hedef.status
        r = await client.post(
            f"/api/cihazlar/{hedef.id}/durum", json={"to_status": "ARIZALI", "reason": "x"}
        )
        assert r.status_code == 404
        await db.refresh(hedef)
        assert hedef.status == once

    async def test_kapsam_disi_cihaz_eki_gorunmez(self, client, rma_ortami):
        hedef = rma_ortami["cihaz"]["digeri"]
        assert (await client.get(f"/api/ekler/devices/{hedef.id}")).status_code == 404
        kendi = rma_ortami["cihaz"]["benim"]
        assert (await client.get(f"/api/ekler/devices/{kendi.id}")).status_code == 200


class TestKatalogUclariKapsami:
    """Arıza/bekleme nedeni katalog uçları (D4-B devri): kimlik yolda değil
    gövdede olduğu için `{id}` taraması (test_router_kapsam_taramasi) bu
    uçları görmüyordu. Kapsam burada elle ama kalıcı olarak sınanır; yeni bir
    `/tanimlar/*` ucu eklenirse `test_tanimlar_uclari_listede` kırmızı olur."""

    KAPSANAN = frozenset(
        {
            ("GET", "/api/teknik-servis/tanimlar/ariza-nedenleri"),
            ("PUT", "/api/teknik-servis/tanimlar/ariza-nedenleri"),
            ("GET", "/api/teknik-servis/tanimlar/bekleme-nedenleri"),
            ("PUT", "/api/teknik-servis/tanimlar/bekleme-nedenleri"),
        }
    )

    async def test_tanimlar_uclari_listede(self):
        from yetki_tarama import uclar

        from app.main import app

        tanimlar = {
            (u.yontem, u.yol) for u in uclar(app) if u.yol.startswith("/api/teknik-servis/tanimlar")
        }
        assert tanimlar == self.KAPSANAN, tanimlar ^ self.KAPSANAN

    @pytest.fixture
    async def katalog(self, client, db, rol_ac, birimli_kullanici_ac):
        from uuid import uuid4

        from app.models import ServiceFaultReason

        # Katalog tohum tablosudur (test arasında boşaltılmaz): ad benzersiz.
        ek = uuid4().hex[:8]
        await rol_ac("T_KATALOG", ["servis.gor", "servis.tanim"], "KENDI_BIRIMI")
        await birimli_kullanici_ac("katalog_g", "T_KATALOG", ["GUVENLIK"])
        g = ServiceFaultReason(birim="GUVENLIK", ad=f"KPS G {ek}", sira=1)
        h = ServiceFaultReason(birim="HABERLESME", ad=f"KPS H {ek}", sira=1)
        db.add_all([g, h])
        await db.commit()
        r = await _giris(client, "katalog_g")
        assert r.status_code == 200, r.text
        return {"g": g, "h": h}

    async def test_ariza_nedeni_listesi_birim_kapsamli(self, client, katalog):
        r = await client.get("/api/teknik-servis/tanimlar/ariza-nedenleri", params={"tumu": True})
        assert r.status_code == 200
        birimler = {n["birim"] for n in r.json()}
        assert birimler == {"GUVENLIK"}
        r = await client.get(
            "/api/teknik-servis/tanimlar/ariza-nedenleri", params={"birim": "HABERLESME"}
        )
        assert r.json() == []

    async def test_baska_birimin_nedeni_degistirilemez(self, client, db, katalog):
        h = katalog["h"]
        ad = h.ad
        govde = {"id": h.id, "ad": "SIZMA", "sira": 5, "is_active": False, "version": h.version}
        r = await client.put(
            "/api/teknik-servis/tanimlar/ariza-nedenleri", json={**govde, "birim": "HABERLESME"}
        )
        assert r.status_code == 403
        # Kendi birimini yazıp başka birimin kimliğini vermek de geçmez.
        r = await client.put(
            "/api/teknik-servis/tanimlar/ariza-nedenleri", json={**govde, "birim": "GUVENLIK"}
        )
        assert r.status_code in (400, 404)
        await db.refresh(h)
        assert (h.ad, h.sira, h.is_active, h.birim) == (ad, 1, True, "HABERLESME")

    async def test_bekleme_nedeni_yazimi_operasyon_yonet_ister(self, client, db, katalog):
        from sqlalchemy import select

        from app.models import ServiceHoldReason

        once = (await db.execute(select(ServiceHoldReason.kod, ServiceHoldReason.ad))).all()
        r = await client.put(
            "/api/teknik-servis/tanimlar/bekleme-nedenleri",
            json={
                "kod": "KPS_SIZMA",
                "ad": "Sızma",
                "sla_durdurur": True,
                "aciklama_zorunlu": False,
                "sira": 1,
                "is_active": True,
            },
        )
        assert r.status_code == 403
        sonra = (await db.execute(select(ServiceHoldReason.kod, ServiceHoldReason.ad))).all()
        assert sorted(once) == sorted(sonra)


class TestRaporExcelDenetimi:
    """Mobilite rapor Excel'leri denetime yazılır (TS-218, E12 K9)."""

    async def test_her_xlsx_denetim_satiri_yazar(self, client, db, kullanici_ac):
        from sqlalchemy import select

        from app.models import AuditLog

        await kullanici_ac("rapor_admin", "ADMIN")
        await _giris(client, "rapor_admin")
        for yol in (
            "/api/raporlar/musteri-geliri.xlsx",
            "/api/raporlar/hareketsiz-stok.xlsx",
            "/api/raporlar/montaj-noktasi.xlsx",
        ):
            r = await client.get(yol)
            assert r.status_code == 200, (yol, r.text)
        satirlar = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.entity == "raporlar", AuditLog.action == "disa_aktar"
                )
            )
        ).all()
        assert len(satirlar) == 3
        assert {s.new_value["rapor"] for s in satirlar} == {
            "Musteri Geliri",
            "Hareketsiz Stok 180g",
            "Montaj Noktasi Tumu",
        }
        assert all(s.user_id is not None for s in satirlar)

    async def test_yetkisiz_xlsx_denetime_yazmaz(self, client, db, kapsam_ortami):
        from sqlalchemy import func, select

        from app.models import AuditLog

        assert (await client.get("/api/raporlar/montaj-noktasi.xlsx")).status_code == 403
        sayi = await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.entity == "raporlar")
        )
        assert sayi == 0


class TestEkIcerikDenetimi:
    """Magic-byte denetiminin canlı ek sahiplerine yayılması (TS-218).

    Kuru koşu: ayar kapalıyken canlı türde uyuşmayan içerik KABUL edilir ama
    denetime yazılır ve rapora girer; ayar açılınca 422. Teknik servis
    türlerinde denetim her zaman zorunlu (Dalga 0 davranışı değişmedi)."""

    @pytest.fixture
    async def admin(self, client, db, kullanici_ac):
        from app.models import Account

        await kullanici_ac("ek_admin", "ADMIN")
        await _giris(client, "ek_admin")
        hesap = Account(title="EK HESAP", is_musteri=True)
        db.add(hesap)
        await db.commit()
        return hesap

    async def test_kuru_kosu_kabul_eder_ve_raporlar(self, client, db, admin):
        from sqlalchemy import select

        from app.models import AuditLog

        sahte = {"file": ("levha.pdf", b"<html>pdf degil</html>", "application/pdf")}
        r = await client.post(f"/api/ekler/accounts/{admin.id}", files=sahte)
        assert r.status_code == 201, r.text
        ek_id = r.json()["id"]
        kayit = await db.scalar(
            select(AuditLog).where(AuditLog.action == "ek.icerik_uyusmazligi_kuru")
        )
        assert kayit is not None and kayit.new_value["ek_id"] == ek_id

        rapor = (await client.get("/api/ekler/icerik-denetimi")).json()
        assert rapor["canli_turler_zorunlu"] is False
        assert rapor["kuru_kosu_kabul_edilen"] == 1
        assert [u["ek_id"] for u in rapor["uyusmayanlar"]] == [ek_id]
        assert rapor["tur_bazinda"] == {"application/pdf": 1}

    async def test_ayar_acilinca_canli_turde_red(self, client, db, admin):
        from app.services import settings as ayar_svc

        await ayar_svc.set_many(db, {"ek_icerik_denetimi_canli_turler": True}, user_id=None)
        await db.commit()
        sahte = {"file": ("levha.pdf", b"<html>pdf degil</html>", "application/pdf")}
        r = await client.post(f"/api/ekler/accounts/{admin.id}", files=sahte)
        assert r.status_code == 422
        dogru = {"file": ("levha.pdf", b"%PDF-1.4\nlevha", "application/pdf")}
        r = await client.post(f"/api/ekler/accounts/{admin.id}", files=dogru)
        assert r.status_code == 201

    async def test_rapor_yalniz_ayar_yetkilisine(self, client, kapsam_ortami):
        assert (await client.get("/api/ekler/icerik-denetimi")).status_code == 403
