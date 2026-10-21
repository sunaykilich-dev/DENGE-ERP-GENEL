"""Sessiz veri kaybı ve bozulmasına karşı koruma testleri.

Buradaki her testin arkasında ölçülmüş bir davranış var. Ortak özellikleri:
**hata vermiyorlardı**. Kullanıcıya bir şey göstermeden kayıt eksiltiyor,
değer bozuyor ya da yazmayı sessizce eziyorlardı — canlıya çıktıktan sonra
"veriler gitti mi?" sorusunu doğuracak türden hatalar.
"""

import pytest

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


@pytest.fixture
async def yonetici(client, kullanici_ac):
    await kullanici_ac("butunluk_admin", "ADMIN")
    await _giris(client, "butunluk_admin")


class TestSayfalamaDeterminizmi:
    """Sayfalamada tekil olmayan sıralama, kayıt YUTAR.

    Ölçülen: `is-emirleri` yalnız `completed_at` ile sıralanıyordu (tek bir
    zaman damgasında 49 iş emri vardı). 1.232 kayıt sayfa sayfa gezildiğinde
    1.215 benzersiz kayıt geldi — **17 iş emri hiçbir sayfada görünmedi**.
    Hata yok, uyarı yok.
    """

    async def test_ayni_damgali_kayitlarda_sayfalar_cakismaz(
        self, client, db, yonetici, cihaz_ac, urun_ac
    ):
        from datetime import UTC, datetime

        from app.models import Account, WorkOrder
        from app.services.normalize import tr_normkey

        nokta = Account(title="SAYFA MN", title_key=tr_normkey("SAYFA MN"), is_montaj_noktasi=True)
        db.add(nokta)
        await db.flush()

        # Hepsi AYNI zaman damgası: kırılma yoksa sıralama belirsizdir.
        ayni_an = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
        for i in range(30):
            db.add(
                WorkOrder(
                    wo_no=f"SAYFA-{i:04d}",
                    type="MONTAJ",
                    status="TAMAMLANDI",
                    assigned_type="MONTAJ_NOKTASI",
                    assigned_id=nokta.id,
                    completed_at=ayni_an,
                    settlement_period="2026-06",
                )
            )
        await db.commit()

        toplam = int((await client.get("/api/is-emirleri?limit=1")).headers["X-Toplam-Kayit"])
        gorulen: list[int] = []
        offset = 0
        while offset < toplam:
            sayfa = (await client.get(f"/api/is-emirleri?limit=7&offset={offset}")).json()
            gorulen += [s["id"] for s in sayfa]
            offset += 7

        assert len(set(gorulen)) == toplam, (
            f"{toplam - len(set(gorulen))} kayıt hiçbir sayfada görünmedi"
        )


class TestIyimserKilit:
    """İstemcinin `version` değeri kayda ATANMAMALI.

    Atandığında SQLAlchemy'nin `WHERE version = :eski` koşulu her zaman
    tutuyor ve iyimser kilitleme tamamen devre dışı kalıyordu: bayat bir
    sürümle gelen istek 200 dönüp aradaki değişikliği sessizce eziyor, sayaç
    geriye gidiyordu (ölçüldü: 4 → 1).
    """

    @pytest.fixture
    async def siparis(self, db, yonetici):
        from datetime import date

        from app.models import Account, Order
        from app.services.normalize import tr_normkey

        m = Account(title="KILIT MUS", title_key=tr_normkey("KILIT MUS"), is_musteri=True)
        db.add(m)
        await db.flush()
        s = Order(
            order_no="SIP-KILIT-1",
            customer_id=m.id,
            status="TASLAK",
            order_date=date(2026, 9, 1),
            requested_date=date(2026, 10, 5),
            notes="ilk",
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s

    async def test_bayat_surum_409_verir(self, client, db, siparis):
        await client.patch(f"/api/siparisler/{siparis.id}", json={"version": 1, "notes": "a"})
        cevap = await client.patch(
            f"/api/siparisler/{siparis.id}", json={"version": 1, "notes": "eski sürümle"}
        )
        assert cevap.status_code == 409

        await db.refresh(siparis)
        assert siparis.notes == "a", "bayat istek aradaki değişikliği ezdi"

    async def test_surum_geriye_gitmez(self, client, db, siparis):
        await client.patch(f"/api/siparisler/{siparis.id}", json={"version": -5, "notes": "x"})
        await db.refresh(siparis)
        assert siparis.version >= 1, "istemci sürüm sayacını geri aldı"

    async def test_patch_gonderilmeyen_alani_silmez(self, client, db, siparis):
        """PATCH kısmi güncellemedir; yalnız notu değiştiren istek tarihi
        NULL'lıyordu — kullanıcının dokunmadığı veri sessizce siliniyordu."""
        from datetime import date

        cevap = await client.patch(
            f"/api/siparisler/{siparis.id}", json={"version": siparis.version, "notes": "yeni not"}
        )
        assert cevap.status_code == 200
        await db.refresh(siparis)
        assert siparis.requested_date == date(2026, 10, 5)


class TestGirdiSinirlari:
    """Kullanıcı hatası 4xx olmalı, 500 değil."""

    @pytest.mark.parametrize(
        "yol",
        [
            "/api/cihazlar?limit=-1",
            "/api/hesaplar?limit=-1",
            "/api/araclar?limit=-1",
            "/api/hatlar?limit=-1",
            "/api/is-emirleri?limit=-1",
        ],
    )
    async def test_negatif_limit_500_vermez(self, client, yonetici, yol):
        assert (await client.get(yol)).status_code == 422

    @pytest.mark.parametrize("donem", ["2026/06", "ÇÖĞ", 'A"B', "abc", "2026-13", "2026-00"])
    async def test_gecersiz_donem_400(self, client, yonetici, donem):
        """Doğrulanmayan dönem Excel sayfa adına ve HTTP başlığına giriyordu:
        `/` sayfa adı hatasıyla, Türkçe harf latin-1 kodlamasıyla 500."""
        cevap = await client.get("/api/raporlar/montaj-noktasi.xlsx", params={"donem": donem})
        assert cevap.status_code == 400

    async def test_gecersiz_donem_hakedis_excel(self, client, yonetici):
        assert (await client.get("/api/hakedis/donem/abc/excel")).status_code == 400
        assert (await client.get("/api/hakedis/donem/2026-13/excel")).status_code == 400

    async def test_devasa_id_500_vermez(self, client, yonetici):
        cevap = await client.get("/api/raporlar/cihaz-omur-boyu/99999999999999999999")
        assert cevap.status_code == 422

    async def test_negatif_tahsilat_reddedilir(self, client, db, yonetici):
        """Sıfır engelliydi ama negatif geçiyordu ve bakiyeyi ters bozuyordu."""
        from datetime import date

        from app.models import Account
        from app.services.normalize import tr_normkey

        h = Account(title="TAHS MUS", title_key=tr_normkey("TAHS MUS"), is_musteri=True)
        db.add(h)
        await db.commit()

        cevap = await client.post(
            "/api/tahsilat",
            json={
                "account_id": h.id,
                "amount": -5000,
                "paid_at": str(date(2026, 9, 1)),
                "method": "HAVALE",
            },
        )
        assert cevap.status_code in (400, 422)

    async def test_mukerrer_imei_409(self, client, db, yonetici, cihaz_ac, urun_ac):
        """Kısıt ihlali kullanıcı hatasıdır; 500 değil 409 döner."""
        urun = await urun_ac("KISIT-1")
        await cihaz_ac(imei="860000000000123", urun=urun)
        cevap = await client.post(
            "/api/cihazlar", json={"product_id": urun.id, "imei": "860000000000123"}
        )
        assert cevap.status_code == 409


class TestExcelKacisi:
    """Formül kaçışı DEĞERİ BOZMAMALI.

    Eski çözüm metnin başına tek tırnak ekliyordu ("Excel göstermez" diye).
    XLSX'te bu doğru değil: tırnak ancak `quotePrefix` stiliyle gizlenir, düz
    metne eklendiğinde METNİN PARÇASI olur. KVKK veri dökümündeki HER telefon
    `'+905321112233` olarak çıkıyordu — ERP tüm numaraları `+90…` biçimine
    getirdiği için istisnasız hepsi.
    """

    def test_telefon_bozulmaz(self):
        import io

        from openpyxl import load_workbook

        from app.services import export as svc

        icerik = svc.satirlari_xlsx(
            ["Ad", "Telefon"],
            [["ACME", "+905321112233"], ["-EKSI", "@at"]],
            "Test",
        )
        ws = load_workbook(io.BytesIO(icerik)).active
        assert ws.cell(2, 2).value == "+905321112233"
        assert ws.cell(3, 1).value == "-EKSI"
        assert ws.cell(3, 2).value == "@at"

    def test_formul_metin_olarak_yazilir(self):
        import io

        from openpyxl import load_workbook

        from app.services import export as svc

        icerik = svc.satirlari_xlsx(["Unvan"], [['=HYPERLINK("http://x","t")']], "Test")
        h = load_workbook(io.BytesIO(icerik)).active.cell(2, 1)
        assert h.data_type == "s", "metin formül hücresine dönüştü"
        assert h.value == '=HYPERLINK("http://x","t")', "değer değişti"


class TestKvkkSaklama:
    """`NOT IN (NULL içeren alt sorgu)` HER SATIR İÇİN UNKNOWN döner.

    `work_orders.customer_id` alanında NULL satırlar olduğu için saklama
    süresi listesi DAİMA BOŞ geliyordu; KVKK'nın "süresi dolanı imha et"
    ayağı sessizce hiç çalışmadı.
    """

    async def test_null_musteri_listeyi_bosaltmaz(self, client, db, yonetici):
        from datetime import UTC, datetime

        from app.models import Account, WorkOrder
        from app.services.normalize import tr_normkey

        eski = Account(title="SAKLAMA ESKI", title_key=tr_normkey("SAKLAMA ESKI"), is_musteri=True)
        db.add(eski)
        # Müşterisi OLMAYAN bir iş emri: alt sorguya NULL sokan kayıt.
        db.add(
            WorkOrder(
                wo_no="SAKLAMA-NULL",
                type="MONTAJ",
                status="TAMAMLANDI",
                customer_id=None,
                completed_at=datetime(2026, 9, 1, tzinfo=UTC),
                settlement_period="2026-09",
            )
        )
        await db.commit()

        cevap = await client.get("/api/kvkk/saklama-suresi-dolanlar")
        assert cevap.status_code == 200
        veri = cevap.json()
        assert veri["adet"] > 0, "NULL'lu alt sorgu listeyi tamamen boşalttı"
        assert any(k["account_id"] == eski.id for k in veri["kayitlar"])


class TestKapanmisDonem:
    """Kapanmış dönem KAYNAĞI da korumalı, yalnız döküm satırını değil.

    Ölçülen: ödenmiş bir kalemin tutarı 350 → 99.999 yapılabiliyordu. Döküm
    350'de kalıyor ama dönem paneli 99.999 gösteriyordu; ödenen tutarla
    ekrandaki tutar kalıcı olarak ayrışıyordu.
    """

    async def test_odenmis_kalem_degistirilemez(self, client, db, yonetici):
        from datetime import UTC, datetime

        from app.models import (
            Account,
            InstallationPartner,
            PartnerSettlement,
            SettlementLine,
            WorkOrder,
            WorkOrderItem,
        )
        from app.services.normalize import tr_normkey

        nokta = Account(
            title="KAPALI MN", title_key=tr_normkey("KAPALI MN"), is_montaj_noktasi=True
        )
        db.add(nokta)
        await db.flush()
        db.add(InstallationPartner(account_id=nokta.id))

        wo = WorkOrder(
            wo_no="KAPALI-1",
            type="MONTAJ",
            status="TAMAMLANDI",
            assigned_type="MONTAJ_NOKTASI",
            assigned_id=nokta.id,
            completed_at=datetime(2026, 6, 1, tzinfo=UTC),
            settlement_period="2026-06",
        )
        db.add(wo)
        await db.flush()
        kalem = WorkOrderItem(
            work_order_id=wo.id, action="TAKILDI", payability="ODENECEK", unit_price=350
        )
        db.add(kalem)
        dokum = PartnerSettlement(
            partner_id=nokta.id, period="2026-06", status="ODENDI", gross_amount=350
        )
        db.add(dokum)
        await db.flush()
        db.add(
            SettlementLine(
                settlement_id=dokum.id,
                work_order_id=wo.id,
                work_order_item_id=kalem.id,
                work_type="MONTAJ",
                unit_price=350,
                quantity=1,
                amount=350,
                locked_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        await db.commit()

        cevap = await client.patch(
            f"/api/is-emirleri/kalem/{kalem.id}",
            json={"payability": "ODENECEK", "unit_price": 99999},
        )
        assert cevap.status_code == 409
        await db.refresh(kalem)
        assert float(kalem.unit_price) == 350.0


class TestUyariMerkezi:
    """Zamana bağlı uyarılar KULLANICIYA ulaşmalı.

    Worker bunları gecede bir hesaplayıp log'a yazıyordu ve orada kalıyordu.
    Hat taahhüdü bitince aynı hattın aylık maliyeti kat kat artıyor; uyarının
    değeri birine ulaşmasında.
    """

    async def test_uyarilar_izne_tabi(self, client, db, kullanici_ac):
        """Görmediğin modülün uyarısını da görmezsin — sayı da sızıntıdır."""
        from app.models import Account, InstallationPartner
        from app.services.normalize import tr_normkey

        nokta = Account(title="UYARI MN", title_key=tr_normkey("UYARI MN"), is_montaj_noktasi=True)
        db.add(nokta)
        await db.flush()
        db.add(InstallationPartner(account_id=nokta.id, document_type="BELIRSIZ"))
        await db.commit()

        await kullanici_ac("uyari_admin", "ADMIN")
        await _giris(client, "uyari_admin")
        yonetici = (await client.get("/api/raporlar/uyarilar")).json()
        kodlar = {u["kod"] for u in yonetici["uyarilar"]}
        assert "hakedis.belge_tipi" in kodlar, "belge tipi uyarısı üretilmedi"

        await client.post("/api/auth/logout")
        await kullanici_ac("uyari_depo", "DEPO")
        await _giris(client, "uyari_depo")
        depo = (await client.get("/api/raporlar/uyarilar")).json()
        depo_kodlar = {u["kod"] for u in depo["uyarilar"]}
        assert "hakedis.belge_tipi" not in depo_kodlar, "hakediş uyarısı yetkisize sızdı"

    async def test_uyari_satiri_gidilecek_ekrani_tasir(self, client, yonetici):
        veri = (await client.get("/api/raporlar/uyarilar")).json()
        for u in veri["uyarilar"]:
            assert u["yol"].startswith("/"), "uyarı bir ekrana bağlı değil"
            assert u["adet"] > 0
            assert u["onem"] in ("bilgi", "uyari", "kritik")


class TestTarihsizEslesme:
    """Eşleşme biliniyor, başlangıcı bilinmiyor.

    Kaynak dosyada cihazın ICCID'si var ama aktivasyon anı yok. Uydurulmuş
    bir tarih (dosyanın dışa aktarım anı gibi) garanti başlangıcını ve hat
    maliyeti dönemlerini sessizce yanlışlar; bu bir kez yapıldı ve kullanıcı
    kararıyla geri alındı. `valid_from = NULL` satır bir zaman aralığı
    İDDİA ETMEZ.
    """

    @pytest.fixture
    async def cihaz_ve_hat(self, db, yonetici, cihaz_ac, hat_ac):
        cihaz = await cihaz_ac(imei="860000000007001")
        hat = await hat_ac("8990011234500007001")
        return cihaz, hat

    async def test_tarihsiz_acik_donem_yazilabilir(self, db, cihaz_ve_hat):
        from sqlalchemy import select

        from app.models import SimDeviceHistory

        cihaz, hat = cihaz_ve_hat
        db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
        await db.commit()

        kayit = await db.scalar(
            select(SimDeviceHistory).where(SimDeviceHistory.device_id == cihaz.id)
        )
        assert kayit.valid_from is None
        assert kayit.valid_to is None

    async def test_tarihsiz_donem_kapatilamaz(self, db, cihaz_ve_hat):
        """Uzunluğu bilinmeyen aralık, hesaplarda sessizce yanlış sonuç verir."""
        from datetime import UTC, datetime

        from sqlalchemy.exc import IntegrityError

        from app.models import SimDeviceHistory

        cihaz, hat = cihaz_ve_hat
        db.add(
            SimDeviceHistory(
                sim_id=hat.id,
                device_id=cihaz.id,
                valid_from=None,
                valid_to=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_cihaz_basina_tek_acik_donem(self, db, cihaz_ve_hat, hat_ac):
        """EXCLUDE artık tarihsiz satırları görmüyor; tekillik kısmi indeksle."""
        from sqlalchemy.exc import IntegrityError

        from app.models import SimDeviceHistory

        cihaz, hat = cihaz_ve_hat
        ikinci = await hat_ac("8990011234500007002")
        db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
        db.add(SimDeviceHistory(sim_id=ikinci.id, device_id=cihaz.id, valid_from=None))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_uzlastirma_tarihsiz_eslesmeyi_gorur(self, db, cihaz_ve_hat):
        """`current_sim_id` tarihli tablodan türer; tarihsiz satır da sayılır."""
        from app.models import SimDeviceHistory
        from app.services import devices as svc

        cihaz, hat = cihaz_ve_hat
        db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
        await db.commit()

        await svc.uzlastir(db, yaz=True)
        await db.commit()
        await db.refresh(cihaz)
        assert cihaz.current_sim_id == hat.id

    async def test_yeni_hat_takilinca_tarihsiz_satir_silinir(self, db, cihaz_ve_hat, hat_ac):
        """Kapatılamayan satır, yerini yeni eşleşmeye bırakırken silinir."""
        from sqlalchemy import select

        from app.clock import FakeClock
        from app.models import SimDeviceHistory
        from app.services import devices as svc

        cihaz, hat = cihaz_ve_hat
        db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
        await db.commit()

        yeni = await hat_ac("8990011234500007003")
        await svc.hat_tak(db, device_id=cihaz.id, sim_id=yeni.id, clock=FakeClock())
        await db.commit()

        kalanlar = (
            await db.scalars(select(SimDeviceHistory).where(SimDeviceHistory.device_id == cihaz.id))
        ).all()
        assert len(kalanlar) == 1
        assert kalanlar[0].sim_id == yeni.id
        assert kalanlar[0].valid_from is not None


class TestTarifeYonetimi:
    """Tarife TARİHLİDİR: fiyat değişince geçmiş işler eski fiyattan hesaplanır.

    Tarifeler bugüne kadar yalnız göç betiğiyle yazılabiliyordu; ekranı yoktu.
    Betikle yapılabilen ama ekranda yapılamayan iş, pratikte yapılmıyor.
    """

    @pytest.fixture
    async def nokta(self, db, yonetici):
        from app.models import Account, InstallationPartner
        from app.services.normalize import tr_normkey

        h = Account(title="TARIFE MN", title_key=tr_normkey("TARIFE MN"), is_montaj_noktasi=True)
        db.add(h)
        await db.flush()
        db.add(InstallationPartner(account_id=h.id))
        await db.commit()
        return h

    async def test_yeni_fiyat_eskisini_kapatir(self, client, db, nokta):
        # Saat İLERLETİLMEZ: oturum ömrü 4 saat, 10 gün ilerletmek testi
        # 401'e düşürürdü. Yürürlük tarihi zaten açıkça verilebiliyor.
        ilk = await client.post(
            "/api/tarifeler",
            json={
                "partner_id": nokta.id,
                "work_type": "ATS_MONTAJ",
                "unit_price": 350,
                "valid_from": "2026-01-01T00:00:00Z",
            },
        )
        assert ilk.status_code == 201, ilk.text

        ikinci = await client.post(
            "/api/tarifeler",
            json={
                "partner_id": nokta.id,
                "work_type": "ATS_MONTAJ",
                "unit_price": 420,
                "valid_from": "2026-01-11T00:00:00Z",
            },
        )
        assert ikinci.status_code == 201, ikinci.text

        hepsi = (await client.get(f"/api/tarifeler?montaj_noktasi_id={nokta.id}")).json()
        bizim = [t for t in hepsi if t["partner_id"] == nokta.id]
        assert len(bizim) == 2, "eski tarife silindi ya da kapanmadı"
        acik = [t for t in bizim if t["valid_to"] is None]
        assert len(acik) == 1 and acik[0]["unit_price"] == 420

    async def test_gecmis_is_eski_fiyattan(self, client, db, nokta):
        """Fiyat değişimi KAPANMIŞ dönemi etkilemez."""
        from datetime import UTC, datetime

        from app.services.tariffs import tarife_bul

        await client.post(
            "/api/tarifeler",
            json={
                "partner_id": nokta.id,
                "work_type": "SOKUM",
                "unit_price": 200,
                "valid_from": "2026-01-01T00:00:00Z",
            },
        )
        await client.post(
            "/api/tarifeler",
            json={
                "partner_id": nokta.id,
                "work_type": "SOKUM",
                "unit_price": 300,
                "valid_from": "2026-06-01T00:00:00Z",
            },
        )
        eski = await tarife_bul(
            db,
            partner_id=nokta.id,
            work_type="SOKUM",
            product_group=None,
            an=datetime(2026, 3, 1, tzinfo=UTC),
        )
        yeni = await tarife_bul(
            db,
            partner_id=nokta.id,
            work_type="SOKUM",
            product_group=None,
            an=datetime(2026, 7, 1, tzinfo=UTC),
        )
        assert float(eski.unit_price) == 200.0, "geçmiş iş yeni fiyattan hesaplandı"
        assert float(yeni.unit_price) == 300.0

    async def test_bilinmeyen_is_tipi_reddedilir(self, client, nokta):
        cevap = await client.post(
            "/api/tarifeler",
            json={"partner_id": nokta.id, "work_type": "KEYFIMCE", "unit_price": 1},
        )
        assert cevap.status_code == 400


class TestRolYetkiGorunurlugu:
    """Rol seçimi kör bir tercih olmamalı.

    Yönetici "Satış Temsilcisi" ile "Satış Müdürü" arasındaki farkı ancak
    kodu okuyarak bilebiliyordu; bilinmeyen yetkinin verilmesi, gereğinden
    geniş yetkinin en sık sebebidir.
    """

    async def test_rol_sayfa_ve_izinleri_doner(self, client, yonetici):
        veri = (await client.get("/api/roller/SATIS/yetkiler")).json()
        assert veri["scope"] == "KENDI_MUSTERILERI"
        assert "Hesaplar" in veri["sayfalar"]
        assert "Kullanıcılar" not in veri["sayfalar"], "yetkisi olmayan sayfa listelendi"
        assert any(i["kod"] == "teklif.yaz" for i in veri["izinler"])
        assert not any(i["kod"] == "hakedis.ode" for i in veri["izinler"])

    async def test_izin_katalogu_tek_kaynaktan(self, client, yonetici):
        """Açıklamalar `app/permissions.py`den gelir; arayüzde kopyalanmaz."""
        from app.permissions import PERMISSIONS

        veri = (await client.get("/api/roller/ADMIN/yetkiler")).json()
        for i in veri["izinler"]:
            assert i["aciklama"] == PERMISSIONS[i["kod"]][1]

    async def test_olmayan_rol_404(self, client, yonetici):
        assert (await client.get("/api/roller/YOK/yetkiler")).status_code == 404
