"""Müşteri ana verisinin servis genişletmesi (TS-014, E14-01 revised, E14-D01).

Gerçek ihtiyaçtan: servis personeli müşteriyi bulamadığı için işi
açamıyordu; çözüm ona `hesap.yaz` (IBAN/VKN düzenleme) vermek DEĞİL — ad + il
ile doğrulanmamış hızlı kayıt ve mali alan taşımayan hafif arama. Testler bu
sınırı kilitler: teknisyen müşteri arar ama VKN/telefon görmez, hızlı kayıt
doğrulanmış doğamaz, VKN çakışması yalnız VKN değişince sorulur.
"""

import pytest
from sqlalchemy import select

from app.models import Account, Address, AuditLog, UserPermission
from app.services.normalize import tr_normkey

pytestmark = pytest.mark.integration

ANA = "/api/teknik-servis/ana-veri"


async def _giris(client, kullanici_ac, username: str, rol: str):
    kul = await kullanici_ac(username, rol)
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text
    return kul


async def _cikis(client):
    await client.post("/api/auth/logout")
    client.cookies.clear()


async def _hesap(db, ad: str, **kw) -> Account:
    varsayilan = {"is_musteri": True}
    varsayilan.update(kw)
    h = Account(title=ad, title_key=tr_normkey(ad), **varsayilan)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _izin_ver(db, user, kod: str):
    db.add(UserPermission(user_id=user.id, permission_code=kod, allow=True, gerekce="test"))
    await db.commit()


async def _denetim(db, eylem: str) -> list[AuditLog]:
    return list((await db.scalars(select(AuditLog).where(AuditLog.action == eylem))).all())


class TestHizliEkleme:
    async def test_dogrulanmamis_musteri_ve_tesis_acar(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        r = await client.post(
            f"{ANA}/hizli-musteri",
            json={
                "unvan": "  Akyaka Park Yönetimi  ",
                "il": "istanbul",
                "tesis_adi": "Akyaka AVM",
                # Gövdede doğrulanmış gönderilse de yok sayılır.
                "is_verified": True,
            },
        )
        assert r.status_code == 201, r.text
        v = r.json()
        assert v["hesap"]["dogrulandi"] is False
        assert v["hesap"]["unvan"] == "Akyaka Park Yönetimi"  # kırpıldı
        assert v["lokasyon"]["dogrulandi"] is False

        hesap = await db.get(Account, v["hesap"]["id"])
        await db.refresh(hesap)
        assert hesap.is_musteri is True and hesap.is_verified is False
        tesis = await db.get(Address, v["lokasyon"]["id"])
        assert tesis.kind == "TESIS" and tesis.line is None and tesis.account_id == hesap.id
        assert await _denetim(db, "hesap.hizli_olustur")

    @pytest.mark.parametrize("rol", ["SERVIS_TEKNISYEN", "SERVIS_SEF", "ATOLYE"])
    async def test_ts_saha_rolleri_hizli_ekleyemez(self, client, kullanici_ac, db, rol):
        """G10.2 (KARARLAR 2026-10-28): müşteri kartını yalnız Mİ / satış destek /
        muhasebe / yöneticiler açar; operasyon KARARLAR 2026-11-04 §6.5 ile
        eklendi (hızlı kart doğrulanmamış doğar). `hesap.kart_yaz` ve `hesap.yaz` yok → 403
        (form "Hızlı ekle"yi de göstermez), kayıt AÇILMAZ."""
        await _giris(client, kullanici_ac, "tskisi", rol)
        r = await client.post(f"{ANA}/hizli-musteri", json={"unvan": "Yeni Firma", "il": "Ankara"})
        assert r.status_code == 403
        assert (await db.scalar(select(Account).where(Account.title == "Yeni Firma"))) is None

    async def test_hesap_yazan_mobilite_kullanicisi_de_kart_acar(self, client, kullanici_ac, db):
        """`hesap.yaz` (Hesaplar ekranının kart yetkisi) TS kapısını da açar;
        `servis.yaz` artık gerekmez (KARARLAR 2026-11-04 §6.5, rol testi B2)."""
        await _giris(client, kullanici_ac, "satismud", "SATIS_MUDURU")
        r = await client.post(
            f"{ANA}/hizli-musteri", json={"unvan": "Satış Firması", "il": "Ankara"}
        )
        assert r.status_code == 201, r.text

    async def test_benzer_unvan_409_onayla_201(self, client, kullanici_ac, db):
        mevcut = await _hesap(db, "G4S ELEKTRONİK SİSTEMLERİ A.Ş.")
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        govde = {"unvan": "G4S Elektronik Sistemleri Anonim Şirketi", "il": "İstanbul"}

        r = await client.post(f"{ANA}/hizli-musteri", json=govde)
        assert r.status_code == 409, r.text
        adaylar = r.json()["detail"]["adaylar"]
        assert [a["id"] for a in adaylar] == [mevcut.id]
        # Aday satırı da hafif: mali alan yok.
        assert "tax_no" not in adaylar[0] and "phone" not in adaylar[0]

        r = await client.post(f"{ANA}/hizli-musteri", json={**govde, "onay_benzer": True})
        assert r.status_code == 201, r.text

    async def test_takma_addan_benzer_bulunur(self, client, kullanici_ac, db):
        """Birleştirilmiş eski yazım hedef hesabı gösterir."""
        from app.models import AccountAlias

        hedef = await _hesap(db, "MERKEZ GÜVENLİK HİZMETLERİ")
        db.add(AccountAlias(account_id=hedef.id, alias_text="Akyaka Park AVM", kaynak="ELLE"))
        await db.commit()
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        r = await client.post(
            f"{ANA}/hizli-musteri", json={"unvan": "AKYAKA PARK AVM", "il": "Muğla"}
        )
        assert r.status_code == 409
        assert r.json()["detail"]["adaylar"][0]["eslesen"] == "takma_ad"

    @pytest.mark.parametrize("unvan", ["", "   ", "x" * 201])
    async def test_gecersiz_unvan_422(self, client, kullanici_ac, unvan):
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        r = await client.post(f"{ANA}/hizli-musteri", json={"unvan": unvan, "il": "Ankara"})
        assert r.status_code == 422

    async def test_bilinmeyen_il_400(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        r = await client.post(
            f"{ANA}/hizli-musteri", json={"unvan": "Yok İl Firması", "il": "Atlantis"}
        )
        assert r.status_code == 400
        assert (await db.scalar(select(Account).where(Account.title == "Yok İl Firması"))) is None


class TestHafifArama:
    async def test_teknisyen_arar_ama_mali_alan_gormez(self, client, kullanici_ac, db):
        await _hesap(
            db,
            "ÖZEL GÜVENLİK LTD",
            tax_no="1234567890",
            phone="+905321112233",
            email="a@b.com",
            region="İstanbul",
        )
        await _giris(client, kullanici_ac, "teknisyen", "SERVIS_TEKNISYEN")

        # Canlı Hesaplar ekranı teknisyene kapalı (KD-09).
        assert (await client.get("/api/hesaplar")).status_code == 403

        r = await client.get(f"{ANA}/musteri-ara", params={"q": "özel güv"})
        assert r.status_code == 200, r.text
        satir = r.json()[0]
        assert set(satir) == {"id", "unvan", "il", "dogrulandi", "eslesen"}
        for yasak in ("tax_no", "iban", "phone", "email", "kisiler", "vkn", "telefon"):
            assert yasak not in satir
        assert satir["il"] == "İstanbul" and satir["eslesen"] == "unvan"

    async def test_vkn_ile_bulur_degerini_vermez(self, client, kullanici_ac, db):
        await _hesap(db, "VERGİ İLE ARANAN", tax_no="9876543210")
        await _giris(client, kullanici_ac, "teknisyen", "SERVIS_TEKNISYEN")
        r = await client.get(f"{ANA}/musteri-ara", params={"q": "98765"})
        assert r.status_code == 200
        assert r.json()[0]["eslesen"] == "vkn"
        assert "9876543210" not in r.text

    async def test_tesis_adindan_bulur(self, client, kullanici_ac, db):
        h = await _hesap(db, "XYZ YÖNETİM")
        db.add(Address(account_id=h.id, kind="TESIS", site_name="Piazza AVM", city="Samsun"))
        await db.commit()
        await _giris(client, kullanici_ac, "teknisyen", "SERVIS_TEKNISYEN")
        r = await client.get(f"{ANA}/musteri-ara", params={"q": "PİAZZA"})
        assert [(s["id"], s["eslesen"]) for s in r.json()] == [(h.id, "tesis")]

    async def test_silinmis_ve_musteri_olmayan_donmez(self, client, kullanici_ac, db):
        await _hesap(db, "SİLİNMİŞ ARAMA", is_deleted=True)
        await _hesap(db, "TEDARİKÇİ ARAMA", is_musteri=False, is_tedarikci=True)
        await _giris(client, kullanici_ac, "teknisyen", "SERVIS_TEKNISYEN")
        r = await client.get(f"{ANA}/musteri-ara", params={"q": "arama"})
        assert r.json() == []

    async def test_servis_izni_olmayan_403(self, client, kullanici_ac):
        # SATIS §7.8 ile servis.gor aldı; servis izni olmayan rol: finans uzmanı.
        await _giris(client, kullanici_ac, "finans_uzm", "MUHASEBE_DESTEK")
        assert (await client.get(f"{ANA}/musteri-ara", params={"q": "abc"})).status_code == 403

    async def test_yanitta_fiyat_anahtari_yok(self, client, kullanici_ac, db):
        """Maliyet görmeyen rolde fiyat/maliyet anahtarı yanıtta hiç yok."""
        await _hesap(db, "FİYATSIZ MÜŞTERİ")
        await _giris(client, kullanici_ac, "teknisyen", "SERVIS_TEKNISYEN")
        r = await client.get(f"{ANA}/musteri-ara", params={"q": "fiyatsiz"})
        for yasak in ("maliyet", "fiyat", "tutar", "grand_total", "unit_cost"):
            assert yasak not in r.text


class TestVknCakismasi:
    async def test_ayni_vkn_409_onay_ile_201(self, client, kullanici_ac, db):
        mevcut = await _hesap(db, "İLK FİRMA", tax_no="1111111111")
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        govde = {"title": "İKİNCİ ŞUBE", "is_musteri": True, "tax_no": "1111111111"}

        r = await client.post("/api/hesaplar", json=govde)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["mevcut"] == [{"id": mevcut.id, "title": "İLK FİRMA"}]

        r = await client.post("/api/hesaplar", json={**govde, "vkn_cakisma_onayi": True})
        assert r.status_code == 400  # gerekçesiz onay yok

        r = await client.post(
            "/api/hesaplar",
            json={
                **govde,
                "vkn_cakisma_onayi": True,
                "vkn_cakisma_gerekce": "Aynı firmanın şubesi",
            },
        )
        assert r.status_code == 201, r.text
        kayitlar = await _denetim(db, "vkn.cakisma.onay")
        assert len(kayitlar) == 1 and kayitlar[0].entity_id == str(r.json()["id"])

    async def test_vkn_degismeyen_patch_200(self, client, kullanici_ac, db):
        """Ön yüz formun tamamını gönderiyor; aynı VKN'li çiftte telefon
        değiştirmek onaya bağlanmamalı (E14 B1)."""
        await _hesap(db, "ŞUBE A", tax_no="2222222222")
        b = await _hesap(db, "ŞUBE B", tax_no="2222222222")
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        r = await client.patch(
            f"/api/hesaplar/{b.id}",
            json={"title": "ŞUBE B", "tax_no": "2222222222", "phone": "05321234567", "version": 1},
        )
        assert r.status_code == 200, r.text

    async def test_cakisan_vkne_degistirme_409_ve_yazmaz(self, client, kullanici_ac, db):
        await _hesap(db, "SAHİBİ", tax_no="3333333333")
        b = await _hesap(db, "DEĞİŞEN", tax_no="4444444444")
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        r = await client.patch(f"/api/hesaplar/{b.id}", json={"tax_no": "3333333333"})
        assert r.status_code == 409
        await db.refresh(b)
        assert b.tax_no == "4444444444"

    async def test_dogrulama_alanlari_hesap_formundan_yazilamaz(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        r = await client.post(
            "/api/hesaplar",
            json={
                "title": "FORM HESABI",
                "is_musteri": True,
                "is_verified": False,
                "merged_into_id": 1,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["is_verified"] is True
        h = await _hesap(db, "HIZLI AÇILMIŞ", is_verified=False)
        r = await client.patch(f"/api/hesaplar/{h.id}", json={"is_verified": True})
        assert r.status_code == 200
        await db.refresh(h)
        assert h.is_verified is False

    async def test_cari_kodu_yazilir_ve_doner(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        r = await client.post(
            "/api/hesaplar",
            json={"title": "CARİLİ", "is_musteri": True, "dis_referans": "120.01.005"},
        )
        assert r.status_code == 201
        assert r.json()["dis_referans"] == "120.01.005"


class TestDogrulama:
    async def test_birlestir_izniyle_dogrulanir(self, client, kullanici_ac, db):
        h = await _hesap(db, "DOĞRULANACAK", is_verified=False)
        await _giris(client, kullanici_ac, "operasyon", "SERVIS_OPERASYON")
        assert (await client.post(f"/api/hesaplar/{h.id}/dogrula")).status_code == 403
        await _cikis(client)

        yonetici = await _giris(client, kullanici_ac, "yonetici", "SERVIS_YONETICI")
        r = await client.post(f"/api/hesaplar/{h.id}/dogrula")
        assert r.status_code == 200, r.text
        assert r.json()["is_verified"] is True
        await db.refresh(h)
        assert h.verified_by == yonetici.id and h.verified_at is not None
        assert await _denetim(db, "hesap.dogrula")
        assert (await client.post(f"/api/hesaplar/{h.id}/dogrula")).status_code == 409

    async def test_dogrulanmamis_filtresi(self, client, kullanici_ac, db):
        await _hesap(db, "DOĞRU OLAN")
        acik = await _hesap(db, "DOĞRULANMAMIŞ OLAN", is_verified=False)
        await _giris(client, kullanici_ac, "admin", "ADMIN")
        r = await client.get("/api/hesaplar", params={"dogrulanmamis": "true"})
        assert [h["id"] for h in r.json()] == [acik.id]
        assert r.headers["X-Toplam-Kayit"] == "1"

    async def test_kapsam_disi_dogrulama_404_ve_yazmaz(self, client, kullanici_ac, db):
        satis = await _giris(client, kullanici_ac, "satis", "SATIS")
        await _izin_ver(db, satis, "hesap.birlestir")
        digeri = await kullanici_ac("satis2", "SATIS")
        h = await _hesap(db, "BAŞKASININ", is_verified=False, sales_rep_id=digeri.id)
        r = await client.post(f"/api/hesaplar/{h.id}/dogrula")
        assert r.status_code == 404
        await db.refresh(h)
        assert h.is_verified is False


class TestServisMusteriDuzenleme:
    async def test_mobilite_hesabi_409_ve_yazmaz(self, client, kullanici_ac, db):
        nokta = await _hesap(db, "MONTAJ NOKTASI X", is_montaj_noktasi=True)
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        r = await client.patch(
            f"{ANA}/musteriler/{nokta.id}", json={"title": "DEĞİŞTİ", "version": nokta.version}
        )
        assert r.status_code == 409
        await db.refresh(nokta)
        assert nokta.title == "MONTAJ NOKTASI X"

    async def test_musteri_duzeltilir(self, client, kullanici_ac, db):
        h = await _hesap(db, "YAZIM HATALI")
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        r = await client.patch(
            f"{ANA}/musteriler/{h.id}",
            json={"title": "Yazım Düzeltildi", "region": "izmir", "version": h.version},
        )
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Yazım Düzeltildi"
        assert set(r.json()) == {
            "id",
            "title",
            "region",
            "phone",
            "email",
            "dis_referans",
            "sla_takvim_turu",  # Faz A (TS-200): müşteri sözleşmesinin SLA takvimi
            "is_verified",
            "version",
        }
        assert await _denetim(db, "servis.musteri.guncelle")

    @pytest.mark.parametrize("rol", ["SERVIS_TEKNISYEN", "SERVIS_SEF"])
    async def test_ts_rolleri_kart_duzeltemez_403(self, client, kullanici_ac, db, rol):
        """G10.2: kart künyesi düzeltmesi de müşteri kartı değişikliğidir."""
        h = await _hesap(db, "TEKNİSYEN DÜZENLEYEMEZ")
        await _giris(client, kullanici_ac, "tskisi", rol)
        r = await client.patch(f"{ANA}/musteriler/{h.id}", json={"title": "X Y", "version": 1})
        assert r.status_code == 403
        await db.refresh(h)
        assert h.title == "TEKNİSYEN DÜZENLEYEMEZ"

    async def test_kapsam_disi_404_ve_yazmaz(self, client, kullanici_ac, db):
        satis = await _giris(client, kullanici_ac, "satis", "SATIS")
        await _izin_ver(db, satis, "lokasyon.yaz")
        digeri = await kullanici_ac("satis2", "SATIS")
        h = await _hesap(db, "KAPSAM DIŞI MÜŞTERİ", sales_rep_id=digeri.id)
        r = await client.patch(f"{ANA}/musteriler/{h.id}", json={"title": "SIZMA", "version": 1})
        assert r.status_code == 404
        await db.refresh(h)
        assert h.title == "KAPSAM DIŞI MÜŞTERİ"

    async def test_eski_surum_409(self, client, kullanici_ac, db):
        h = await _hesap(db, "SÜRÜMLÜ")
        await _giris(client, kullanici_ac, "tsmudur", "SERVIS_YONETICI")
        r = await client.patch(f"{ANA}/musteriler/{h.id}", json={"title": "YENİ", "version": 99})
        assert r.status_code == 409


class TestMevcutHesaplar:
    async def test_orm_ile_acilan_hesap_dogrulanmis_dogar(self, db):
        """Göç/seed/mobilite yolu: varsayılan doğrulanmış (migration server_default)."""
        h = await _hesap(db, "MOBİLİTE MÜŞTERİSİ")
        assert h.is_verified is True


class TestDogrulanmamisUyarisi:
    async def test_yalniz_suresi_gecenler_ve_izinliye(self, seeded, kullanici_ac, db):
        """Uyarı `hesap_dogrulanmamis_uyari_gun` (7) günden eski kayıtları sayar."""
        from datetime import UTC, datetime

        from app.clock import FakeClock
        from app.services.teknik_servis import ana_veri
        from app.services.teknik_servis import uyarilar as ts_uyarilar

        eski = datetime(2026, 1, 1, tzinfo=UTC)
        yeni = datetime(2026, 1, 9, tzinfo=UTC)
        h = await _hesap(db, "ESKİ HIZLI", is_verified=False, created_at=eski)
        await _hesap(db, "YENİ HIZLI", is_verified=False, created_at=yeni)
        db.add(
            Address(
                account_id=h.id,
                kind="TESIS",
                site_name="Eski Tesis",
                city="Ankara",
                is_verified=False,
                created_at=eski,
            )
        )
        await db.commit()
        saat = FakeClock(datetime(2026, 1, 10, tzinfo=UTC))

        yonetici = await kullanici_ac("yonetici", "SERVIS_YONETICI")
        assert await ana_veri.dogrulanmamis_sayilari(db, yonetici, saat) == {
            "hesap": 1,
            "lokasyon": 1,
        }
        kodlar = {u.kod for u in await ts_uyarilar.topla(db, yonetici, saat)}
        assert {"hesap_dogrulanmamis", "lokasyon_dogrulanmamis"} <= kodlar

        teknisyen = await kullanici_ac("teknisyen", "SERVIS_TEKNISYEN")
        kodlar = {u.kod for u in await ts_uyarilar.topla(db, teknisyen, saat)}
        assert "hesap_dogrulanmamis" not in kodlar
