"""Servis lokasyonu (tesis), lokasyon irtibatı, takma ad, ortak doğrulayıcı (TS-015).

Lokasyon `addresses` satırıdır; bütün servis kayıtları ona FK ile bağlanacak.
Bu yüzden üç şey kilitlenir: (1) kapsam dışı lokasyon 404 döner VE yazma
gerçekleşmez, (2) aynı carinin aynı adlı iki aktif tesisi olamaz ("Akyaka
AVM" = "AKYAKA  AVM"), (3) servis kayıtlarının tek doğrulayıcısı yabancı
hesabın tesisini, pasif tesisi ve müşteri olmayan hesabı reddeder.
Teklif PDF'i ise TESIS satırlarını muhatap adresi diye basmaz.
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import (
    Account,
    AccountAlias,
    Address,
    AuditLog,
    Contact,
    Quote,
    QuoteVersion,
    UserPermission,
)
from app.services.normalize import tr_normkey
from app.services.teknik_servis import ana_veri

pytestmark = pytest.mark.integration


async def _giris(client, kullanici_ac, username: str, rol: str):
    kul = await kullanici_ac(username, rol)
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text
    return kul


async def _hesap(db, ad: str, **kw) -> Account:
    varsayilan = {"is_musteri": True}
    varsayilan.update(kw)
    h = Account(title=ad, title_key=tr_normkey(ad), **varsayilan)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _tesis(db, hesap: Account, ad: str, **kw) -> Address:
    a = Address(account_id=hesap.id, kind="TESIS", site_name=ad, city="İstanbul", **kw)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _lokasyon_ac(client, hesap_id: int, ad: str = "Akyaka AVM", **kw):
    govde = {"hesap_id": hesap_id, "kind": "TESIS", "site_name": ad, "city": "Muğla", **kw}
    return await client.post("/api/lokasyonlar", json=govde)


class TestLokasyonYazma:
    async def test_lokasyon_ve_irtibat_acilir(self, client, kullanici_ac, db):
        h = await _hesap(db, "AVM YÖNETİMİ")
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        r = await _lokasyon_ac(client, h.id, line="Kemeraltı Mah. 1", access_note="B girişi")
        assert r.status_code == 201, r.text
        lok = r.json()
        # Operasyonun açtığı tesis doğrulanmamış doğar (KARARLAR 2026-11-04 §6.5).
        assert lok["kind"] == "TESIS" and lok["is_verified"] is False and lok["city"] == "Muğla"

        r = await client.post(
            f"/api/lokasyonlar/{lok['id']}/kisiler",
            json={
                "full_name": "Saha Sorumlusu",
                "phone": "0532 111 22 33",
                "lokasyon_birincil": True,
            },
        )
        assert r.status_code == 201, r.text
        kisi = await db.get(Contact, r.json()["id"])
        assert kisi.address_id == lok["id"] and kisi.account_id == h.id
        assert kisi.phone == "+905321112233"
        adres = await db.get(Address, lok["id"])
        await db.refresh(adres)
        assert adres.primary_contact_id == kisi.id

        izler = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.entity == "contacts", AuditLog.entity_id == str(kisi.id)
                )
            )
        ).all()
        assert izler and all(i.is_personal_data for i in izler)
        assert (
            await db.scalar(select(AuditLog).where(AuditLog.action == "lokasyon.olustur"))
        ) is not None

    async def test_ayni_anahtarli_ikinci_aktif_tesis_409(self, client, kullanici_ac, db):
        h = await _hesap(db, "ÇİFT TESİS")
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        ilk = await _lokasyon_ac(client, h.id, "Akyaka  AVM")
        assert ilk.status_code == 201
        r = await _lokasyon_ac(client, h.id, "AKYAKA AVM")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["mevcut"]["id"] == ilk.json()["id"]

    async def test_tesis_adi_ve_il_zorunlu_bilinmeyen_il_400(self, client, kullanici_ac, db):
        h = await _hesap(db, "EKSİK ALANLI")
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        r = await client.post(
            "/api/lokasyonlar", json={"hesap_id": h.id, "kind": "TESIS", "city": "Muğla"}
        )
        assert r.status_code == 400
        r = await _lokasyon_ac(client, h.id, "Tesis X", city="Narnia")
        assert r.status_code == 400

    async def test_eski_surum_409_hesap_degisimi_400(self, client, kullanici_ac, db):
        h = await _hesap(db, "SÜRÜM HESABI")
        baska = await _hesap(db, "BAŞKA HESAP")
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        lok = (await _lokasyon_ac(client, h.id, "Sürüm Tesisi")).json()

        r = await client.patch(
            f"/api/lokasyonlar/{lok['id']}", json={"access_note": "yeni", "version": 99}
        )
        assert r.status_code == 409
        r = await client.patch(
            f"/api/lokasyonlar/{lok['id']}", json={"hesap_id": baska.id, "version": lok["version"]}
        )
        assert r.status_code == 400
        adres = await db.get(Address, lok["id"])
        await db.refresh(adres)
        assert adres.account_id == h.id and adres.access_note is None

        r = await client.patch(
            f"/api/lokasyonlar/{lok['id']}",
            json={"access_note": "Kat 2", "version": lok["version"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"] == lok["version"] + 1

    async def test_silme_ucu_yok_405(self, client, kullanici_ac, db):
        h = await _hesap(db, "SİLİNEMEZ")
        a = await _tesis(db, h, "Silinemez Tesis")
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        assert (await client.delete(f"/api/lokasyonlar/{a.id}")).status_code == 405

    async def test_pasif_lokasyon_dogrulayicida_400_ama_kart_acilir(self, client, kullanici_ac, db):
        h = await _hesap(db, "PASİF TESİSLİ")
        a = await _tesis(db, h, "Kapanan Şube")
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        r = await client.post(f"/api/lokasyonlar/{a.id}/pasif")
        assert r.status_code == 200 and r.json()["is_active"] is False

        hesap_id, lokasyon_id = h.id, a.id
        db.expire_all()  # test oturumu uçtaki yazmayı görsün
        with pytest.raises(ana_veri.AnaVeriHatasi) as hata:
            await ana_veri.lokasyon_dogrula(db, hesap_id, lokasyon_id)
        assert hata.value.kod == 400
        # Pasif lokasyona bağlı eski kayıtların kartı açılmaya devam eder.
        assert (await client.get(f"/api/lokasyonlar/{lokasyon_id}")).status_code == 200

    async def test_teknisyen_lokasyon_kartina_403_aramaya_200(self, client, kullanici_ac, db):
        h = await _hesap(db, "ARAMA HESABI")
        a = await _tesis(db, h, "Arama Tesisi")
        await _giris(client, kullanici_ac, "teknisyen", "SERVIS_TEKNISYEN")
        assert (await client.get(f"/api/lokasyonlar/{a.id}")).status_code == 403
        assert (await client.get("/api/lokasyonlar")).status_code == 403
        assert (await _lokasyon_ac(client, h.id, "Yeni")).status_code == 403
        r = await client.get(
            "/api/teknik-servis/ana-veri/lokasyon-ara", params={"hesap_id": h.id, "q": "arama"}
        )
        assert r.status_code == 200
        assert [x["id"] for x in r.json()] == [a.id]
        assert set(r.json()[0]) == {
            "id",
            "hesap_id",
            "tesis_adi",
            "ilce",
            "il",
            "aktif",
            "dogrulandi",
        }

    async def test_kart_acilisi_loglanir(self, client, kullanici_ac, db):
        h = await _hesap(db, "LOGLU")
        a = await _tesis(db, h, "Loglu Tesis")
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        r = await client.get(f"/api/lokasyonlar/{a.id}")
        assert r.status_code == 200 and r.json()["irtibatlar"] == []
        log = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "kisisel.eris", AuditLog.entity == "addresses"
            )
        )
        assert log is not None and log.new_value == {"amac": "lokasyon.kart"}

    async def test_irtibat_telefonu_degisikligi_maskeli_izlenir(self, client, kullanici_ac, db):
        h = await _hesap(db, "İRTİBATLI")
        a = await _tesis(db, h, "İrtibat Tesisi")
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        kisi = (
            await client.post(
                f"/api/lokasyonlar/{a.id}/kisiler",
                json={"full_name": "Ayşe Yılmaz", "phone": "05321112233"},
            )
        ).json()
        r = await client.patch(
            f"/api/lokasyonlar/kisiler/{kisi['id']}",
            json={"full_name": "Ayşe Yılmaz", "phone": "05329998877"},
        )
        assert r.status_code == 200, r.text
        iz = await db.scalar(
            select(AuditLog).where(AuditLog.entity == "contacts", AuditLog.action == "guncelle")
        )
        assert iz.is_personal_data is True
        assert iz.old_value["telefon"].endswith("233") and "+90532111" not in str(iz.old_value)
        assert iz.new_value["telefon"].endswith("877")

    async def test_hesap_geneli_kisi_bu_uctan_duzenlenmez(self, client, kullanici_ac, db):
        h = await _hesap(db, "HESAP KİŞİLİ")
        kisi = Contact(account_id=h.id, full_name="Muhasebe Kişisi")
        db.add(kisi)
        await db.commit()
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        r = await client.patch(f"/api/lokasyonlar/kisiler/{kisi.id}", json={"full_name": "Değişti"})
        assert r.status_code == 404

    async def test_dogrulama_birlestir_izni_ister(self, client, kullanici_ac, db):
        h = await _hesap(db, "TESİS DOĞRULAMA")
        a = await _tesis(db, h, "Hızlı Tesis", is_verified=False)
        await _giris(client, kullanici_ac, "yonetici", "SERVIS_YONETICI")
        r = await client.post(f"/api/lokasyonlar/{a.id}/dogrula")
        assert r.status_code == 200 and r.json()["is_verified"] is True
        assert (await client.post(f"/api/lokasyonlar/{a.id}/dogrula")).status_code == 409

    async def test_dogrulanmamis_filtresi(self, client, kullanici_ac, db):
        h = await _hesap(db, "FİLTRE")
        await _tesis(db, h, "Doğru")
        yeni = await _tesis(db, h, "Doğrulanmamış", is_verified=False)
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        r = await client.get("/api/lokasyonlar", params={"dogrulanmamis": "true"})
        assert [x["id"] for x in r.json()] == [yeni.id]
        assert r.headers["X-Toplam-Kayit"] == "1"


class TestLokasyonKapsami:
    @pytest.fixture
    async def ortam(self, client, kullanici_ac, db):
        satis = await _giris(client, kullanici_ac, "satis", "SATIS")
        db.add(UserPermission(user_id=satis.id, permission_code="lokasyon.yaz", allow=True))
        await db.commit()
        digeri = await kullanici_ac("satis2", "SATIS")
        benim = await _hesap(db, "BENİM HESABIM", sales_rep_id=satis.id)
        yabanci = await _hesap(db, "YABANCI HESAP", sales_rep_id=digeri.id)
        return {
            "benim": await _tesis(db, benim, "Benim Tesisim"),
            "yabanci": await _tesis(db, yabanci, "Yabancı Tesis"),
            "yabanci_hesap": yabanci,
        }

    async def test_liste_yalniz_kapsamdaki(self, client, ortam):
        r = await client.get("/api/lokasyonlar")
        assert [x["id"] for x in r.json()] == [ortam["benim"].id]

    async def test_kapsam_disi_get_404(self, client, ortam):
        assert (await client.get(f"/api/lokasyonlar/{ortam['yabanci'].id}")).status_code == 404
        h = ortam["yabanci_hesap"]
        assert (await client.get(f"/api/hesaplar/{h.id}/lokasyonlar")).status_code == 404

    async def test_kapsam_disi_patch_404_ve_yazmaz(self, client, db, ortam):
        hedef = ortam["yabanci"]
        r = await client.patch(
            f"/api/lokasyonlar/{hedef.id}", json={"access_note": "SIZMA", "version": hedef.version}
        )
        assert r.status_code == 404
        await db.refresh(hedef)
        assert hedef.access_note is None

    async def test_kapsam_disi_pasif_404_ve_yazmaz(self, client, db, ortam):
        hedef = ortam["yabanci"]
        assert (await client.post(f"/api/lokasyonlar/{hedef.id}/pasif")).status_code == 404
        await db.refresh(hedef)
        assert hedef.is_active is True

    async def test_kapsam_disi_irtibat_eklenemez(self, client, db, ortam):
        hedef = ortam["yabanci"]
        r = await client.post(f"/api/lokasyonlar/{hedef.id}/kisiler", json={"full_name": "Sızma"})
        assert r.status_code == 404
        sayi = (await db.scalars(select(Contact).where(Contact.address_id == hedef.id))).all()
        assert sayi == []

    async def test_kapsam_disi_hesaba_lokasyon_acilamaz(self, client, db, ortam):
        h = ortam["yabanci_hesap"]
        assert (await _lokasyon_ac(client, h.id, "Sızma Tesisi")).status_code == 404
        adet = (await db.scalars(select(Address).where(Address.account_id == h.id))).all()
        assert len(adet) == 1


class TestTakmaAd:
    async def test_cakisma_409_mevcut_hedef(self, client, kullanici_ac, db):
        a = await _hesap(db, "HEDEF A")
        b = await _hesap(db, "HEDEF B")
        await _giris(client, kullanici_ac, "yonetici", "SERVIS_YONETICI")
        r = await client.post(
            "/api/teknik-servis/ana-veri/takma-adlar",
            json={"hesap_id": a.id, "metin": "Akyaka Park AVM"},
        )
        assert r.status_code == 201, r.text
        r = await client.post(
            "/api/teknik-servis/ana-veri/takma-adlar",
            json={"hesap_id": b.id, "metin": "AKYAKA PARK  AVM"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["mevcut"]["hesap_id"] == a.id

    async def test_rbac_ve_silme_denetimi(self, client, kullanici_ac, db):
        a = await _hesap(db, "TAKMA RBAC")
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        r = await client.post(
            "/api/teknik-servis/ana-veri/takma-adlar", json={"hesap_id": a.id, "metin": "Eski Ad"}
        )
        assert r.status_code == 403
        await client.post("/api/auth/logout")
        client.cookies.clear()

        await _giris(client, kullanici_ac, "yonetici", "SERVIS_YONETICI")
        t = (
            await client.post(
                "/api/teknik-servis/ana-veri/takma-adlar",
                json={"hesap_id": a.id, "metin": "Eski Ad"},
            )
        ).json()
        liste = await client.get(
            "/api/teknik-servis/ana-veri/takma-adlar", params={"hesap_id": a.id}
        )
        assert [x["id"] for x in liste.json()] == [t["id"]]
        r = await client.delete(f"/api/teknik-servis/ana-veri/takma-adlar/{t['id']}")
        assert r.status_code == 204
        assert await db.get(AccountAlias, t["id"]) is None
        assert await db.scalar(select(AuditLog).where(AuditLog.action == "takma_ad.sil"))


class TestOrtakDogrulayici:
    async def test_kurallar(self, db):
        musteri = await _hesap(db, "DOĞRU MÜŞTERİ")
        baska = await _hesap(db, "BAŞKA MÜŞTERİ")
        tedarikci = await _hesap(db, "SADECE TEDARİKÇİ", is_musteri=False, is_tedarikci=True)
        pasif = await _hesap(db, "PASİF MÜŞTERİ", is_active=False)
        tesis = await _tesis(db, musteri, "Doğru Tesis")
        yabanci_tesis = await _tesis(db, baska, "Yabancı Tesis")
        kisi = Contact(account_id=musteri.id, full_name="Doğru Kişi")
        yabanci_kisi = Contact(account_id=baska.id, full_name="Yabancı Kişi")
        db.add_all([kisi, yabanci_kisi])
        await db.commit()

        hesap, adres, irtibat = await ana_veri.lokasyon_dogrula(db, musteri.id, tesis.id, kisi.id)
        assert (hesap.id, adres.id, irtibat.id) == (musteri.id, tesis.id, kisi.id)

        for args in (
            (musteri.id, yabanci_tesis.id, None),
            (musteri.id, None, yabanci_kisi.id),
            (tedarikci.id, None, None),
            (pasif.id, None, None),
            (None, None, None),
        ):
            with pytest.raises(ana_veri.AnaVeriHatasi) as hata:
                await ana_veri.lokasyon_dogrula(db, *args)
            assert hata.value.kod == 400


class TestSahaOnerisi:
    async def test_yalniz_tesis_satirindan_gelir(self, client, kullanici_ac, db):
        h = await _hesap(db, "UNVAN ADRES DEĞİLDİR")
        a = await _tesis(
            db, h, "Öneri Tesisi", line="Atatürk Cd. 5", access_note="Güvenlik kulübesi"
        )
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        r = await client.get(
            "/api/teknik-servis/ana-veri/saha-onerisi", params={"lokasyon_id": a.id}
        )
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["adres"] == "Atatürk Cd. 5" and v["erisim_notu"] == "Güvenlik kulübesi"
        assert "UNVAN" not in str(v.get("adres"))
        assert v["irtibat"] is None

    async def test_servis_yaz_olmayana_telefon_maskeli(self, client, kullanici_ac, db):
        h = await _hesap(db, "MASKELİ ÖNERİ")
        a = await _tesis(db, h, "Maske Tesisi")
        kisi = Contact(
            account_id=h.id, address_id=a.id, full_name="Saha Kişi", phone="+905321112233"
        )
        db.add(kisi)
        await db.commit()
        a.primary_contact_id = kisi.id
        await db.commit()
        # YONETIM: servis.gor + hesap.gor (otomatik .gor), servis.yaz YOK.
        await _giris(client, kullanici_ac, "yonetim", "YONETIM")
        r = await client.get(
            "/api/teknik-servis/ana-veri/saha-onerisi", params={"lokasyon_id": a.id}
        )
        assert r.status_code == 200, r.text
        assert r.json()["irtibat"]["telefon"].endswith("233")
        assert "+90532111" not in r.text

    async def test_teknisyen_kimlikle_okuyamaz(self, client, kullanici_ac, db):
        h = await _hesap(db, "TEKNİSYEN ÖNERİ")
        a = await _tesis(db, h, "Teknisyen Tesisi")
        await _giris(client, kullanici_ac, "teknisyen", "SERVIS_TEKNISYEN")
        r = await client.get(
            "/api/teknik-servis/ana-veri/saha-onerisi", params={"lokasyon_id": a.id}
        )
        assert r.status_code == 403


class TestTeklifPdfAdresi:
    async def _teklif(self, db, hesap: Account, **kw) -> tuple[Quote, QuoteVersion]:
        t = Quote(quote_no=f"TKF-{hesap.id}", customer_id=hesap.id, **kw)
        db.add(t)
        await db.flush()
        v = QuoteVersion(quote_id=t.id, version_no=1, valid_until=date(2026, 12, 31))
        db.add(v)
        await db.commit()
        return t, v

    async def test_tesis_atlanir_merkez_basilir(self, db):
        from app.services.belgeler import teklif_baglami

        h = await _hesap(db, "TEKLİF MÜŞTERİSİ")
        # Önce tesis açılıyor: sırasız sorgu onu basabilirdi.
        await _tesis(db, h, "AVM Tesisi", line="Tesis Yolu 1")
        db.add(Address(account_id=h.id, line="Merkez Sok. 3", district="Kadıköy", city="İstanbul"))
        await db.commit()
        t, v = await self._teklif(db, h)
        baglam = await teklif_baglami(db, t, v)
        assert baglam["adres"] == "Merkez Sok. 3 Kadıköy İstanbul"

    async def test_tek_merkez_adresli_bugunku_cikti(self, db):
        from app.services.belgeler import teklif_baglami

        h = await _hesap(db, "TEK ADRESLİ")
        db.add(Address(account_id=h.id, line="Tek Sok. 1", city="Ankara"))
        await db.commit()
        t, v = await self._teklif(db, h)
        assert (await teklif_baglami(db, t, v))["adres"] == "Tek Sok. 1 Ankara"

    async def test_teklife_bagli_tesis_basilir(self, db):
        from app.services.belgeler import teklif_baglami

        h = await _hesap(db, "SERVİS TEKLİFİ")
        db.add(Address(account_id=h.id, line="Merkez 9", city="İzmir"))
        tesis = await _tesis(db, h, "Servis Tesisi", line="Saha 7")
        t, v = await self._teklif(db, h, address_id=tesis.id)
        assert (await teklif_baglami(db, t, v))["adres"] == "Saha 7 İstanbul"
