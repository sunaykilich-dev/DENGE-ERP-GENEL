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
