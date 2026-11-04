"""Paylaşılan kayıt noktaları, ayarlar ve belge numarası (TS-011, TS-012).

Teknik servisin her modülü canlı ERP'nin ortak yerlerine (ek uçları, uyarı
zili, genel arama, görev panosu, içe aktarma, parametreler) kendi dosyasından
kaydolur. Bu testler kayıt defterlerinin SÖZLEŞMESİNİ sınar: kayıt olmadan
erişim yok (fail-closed), izinsiz kullanıcı ne sonucu ne SAYIYI görür, canlı
davranış (hesap ekleri, mobilite uyarıları) değişmez.
"""

import re
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.api import search as arama_api
from app.models import Account, Attachment, Setting
from app.services import gorevler as gorev_svc
from app.services import imports as ice
from app.services.teknik_servis import ek_kapsam, numara
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.uyarilar import Uyari

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"0" * 64
SAHTE_JPEG = b"<html><script>alert(1)</script></html>"


async def _giris(client, username: str) -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _ek_say(db) -> int:
    return await db.scalar(select(func.count()).select_from(Attachment))


async def _yukle(client, entity: str, kimlik: int, icerik: bytes, kind: str = "SERVIS_ONCESI"):
    return await client.post(
        f"/api/ekler/{entity}/{kimlik}",
        params={"kind": kind},
        files={"file": ("foto.jpg", icerik, "image/jpeg")},
    )


_OZET: dict[str, str] = {}


@pytest.fixture
async def kisiler(db, rol_ac):
    """Dört test kullanıcısı. Parola özeti bir kez hesaplanır (argon2 yavaş)."""
    from app.models import User
    from app.services import auth as auth_service

    if "ozet" not in _OZET:
        _OZET["ozet"] = auth_service.hash_password("parola1234")
    roller = {
        "temsilci": await rol_ac("T_TEMSILCI", ["hesap.gor", "lokasyon.yaz"], "KENDI_MUSTERILERI"),
        "yonetici": await rol_ac(
            "T_YONETICI",
            ["hesap.gor", "hesap.yaz", "lokasyon.yaz", "servis.gor", "servis.yaz"],
            "TUMU",
        ),
        # Gerçek SERVIS_TEKNISYEN gibi: hesap.gor YOK, ürün/cihaz okur (KD-09).
        "teknisyen": await rol_ac(
            "T_TEKNISYEN", ["servis.gor", "urun.gor", "cihaz.gor"], "KENDI_ISLERI"
        ),
        "aramasiz": await rol_ac("T_ARAMASIZ", ["gorev.gor"], "TUMU"),
    }
    kisiler = {}
    for ad, rol in roller.items():
        kisi = User(full_name=ad.title(), username=ad, password_hash=_OZET["ozet"], role_id=rol.id)
        db.add(kisi)
        await db.commit()
        await db.refresh(kisi)
        kisiler[ad] = kisi
    return kisiler


# --- Ekler: kapsam kayıt defteri ---------------------------------------------------


class TestEkKapsami:
    async def test_yabanci_tesisin_eki_404_ve_yazilmaz(self, client, db, kisiler, lokasyon_ac):
        temsilci = kisiler["temsilci"]
        yabanci = await lokasyon_ac()
        kendi_hesap = Account(title="Kendi Müşterim", is_musteri=True, sales_rep_id=temsilci.id)
        db.add(kendi_hesap)
        await db.commit()
        kendi = await lokasyon_ac(kendi_hesap)

        await _giris(client, "temsilci")
        assert (await client.get(f"/api/ekler/addresses/{yabanci.id}")).status_code == 404
        once = await _ek_say(db)
        assert (await _yukle(client, "addresses", yabanci.id, JPEG)).status_code == 404
        assert await _ek_say(db) == once
        assert (await client.get(f"/api/ekler/addresses/{kendi.id}")).status_code == 200
        assert (await _yukle(client, "addresses", kendi.id, JPEG)).status_code == 201

    async def test_kapsam_fonksiyonu_yoksa_ts_eki_reddedilir(
        self, client, db, kisiler, servis_isi_ac, monkeypatch
    ):
        """Fail-closed: kural kaydolmadan servis işi ekleri TUMU kapsamlıya bile açılmaz."""
        monkeypatch.delitem(ek_kapsam.SAHIP_KAPSAMLARI, "service_orders", raising=False)
        so = await servis_isi_ac()
        await _giris(client, "yonetici")
        assert (await client.get(f"/api/ekler/service_orders/{so.id}")).status_code == 404
        assert (await _yukle(client, "service_orders", so.id, JPEG)).status_code == 404
        assert await _ek_say(db) == 0

    async def test_kayitli_kapsam_fonksiyonu_okuma_yazma_ayrimiyla_cagrilir(
        self, client, db, kisiler, servis_isi_ac, monkeypatch
    ):
        from app.models import ServiceOrder

        cagrilar: list[tuple[int, bool]] = []

        async def _yalniz_guvenlik(db_, user, kimlik, yazma):
            cagrilar.append((kimlik, yazma))
            so = await db_.get(ServiceOrder, kimlik)
            return so is None or so.birim == "GUVENLIK"

        monkeypatch.setitem(ek_kapsam.SAHIP_KAPSAMLARI, "service_orders", _yalniz_guvenlik)
        bizim = await servis_isi_ac(birim="GUVENLIK")
        oteki = await servis_isi_ac(birim="HABERLESME")
        await _giris(client, "yonetici")

        assert (await client.get(f"/api/ekler/service_orders/{bizim.id}")).status_code == 200
        assert (await client.get(f"/api/ekler/service_orders/{oteki.id}")).status_code == 404
        assert (await _yukle(client, "service_orders", oteki.id, JPEG)).status_code == 404
        r = await _yukle(client, "service_orders", bizim.id, JPEG)
        assert r.status_code == 201, r.text
        assert (oteki.id, True) in cagrilar and (bizim.id, False) in cagrilar
        assert await _ek_say(db) == 1

    async def test_ayni_tur_iki_farkli_kuralla_kaydedilemez(self) -> None:
        async def _a(*_):
            return True

        with pytest.raises(ValueError, match="zaten kayıtlı"):
            ek_kapsam.kaydet("accounts", _a)

    async def test_ts_ekinde_icerik_turuyle_uyusmali(self, client, db, kisiler, lokasyon_ac):
        tesis = await lokasyon_ac()
        hesap = await db.get(Account, tesis.account_id)
        await _giris(client, "yonetici")

        r = await _yukle(client, "addresses", tesis.id, SAHTE_JPEG)
        assert r.status_code == 422
        assert "uyuşmuyor" in r.json()["detail"]
        assert (await _yukle(client, "addresses", tesis.id, JPEG)).status_code == 201
        # Canlı tür (hesap) davranışı DEĞİŞMEDİ: yalnız MIME beyaz listesi.
        r = await _yukle(client, "accounts", hesap.id, SAHTE_JPEG, kind="DIGER")
        assert r.status_code == 201, r.text

    async def test_bilinmeyen_ek_turu_reddedilir(self, client, kisiler, lokasyon_ac):
        tesis = await lokasyon_ac()
        await _giris(client, "yonetici")
        r = await _yukle(client, "addresses", tesis.id, JPEG, kind="MUSTERI_IMZASI")
        assert r.status_code == 400


# --- Uyarı zili -------------------------------------------------------------------


class TestUyariKayitDefteri:
    async def test_izinli_kullanici_gorur_izinsiz_sayiyi_bile_gormez(
        self, client, kisiler, monkeypatch
    ):
        monkeypatch.setitem(ts_uyarilar._KAYIT, "servis", [])

        async def _gecikmis(db, user, clock):
            return [Uyari(kod="servis.test_gecikme", baslik="Geciken iş", adet=3, yol="/x")]

        async def _bos(db, user, clock):
            return [Uyari(kod="servis.test_bos", baslik="Boş", adet=0, yol="/x")]

        ts_uyarilar.kaydet("servis", "servis.gor", _gecikmis)
        ts_uyarilar.kaydet("servis", "servis.gor", _bos)

        await _giris(client, "teknisyen")
        govde = (await client.get("/api/raporlar/uyarilar")).json()
        kodlar = {u["kod"] for u in govde["uyarilar"]}
        assert "servis.test_gecikme" in kodlar
        assert "servis.test_bos" not in kodlar  # adet 0 gösterilmez
        assert govde["toplam"] >= 3

        await _giris(client, "temsilci")
        govde = (await client.get("/api/raporlar/uyarilar")).json()
        assert "servis.test_gecikme" not in {u["kod"] for u in govde["uyarilar"]}

    def test_kayit_kurallari(self) -> None:
        async def _f(*_):
            return []

        with pytest.raises(ValueError, match="Bilinmeyen uyarı alanı"):
            ts_uyarilar.kaydet("yok_boyle", "servis.gor", _f)
        with pytest.raises(ValueError, match="izinsiz"):
            ts_uyarilar.kaydet("servis", (), _f)


# --- Genel arama ---------------------------------------------------------------------


class TestAramaKayitDefteri:
    async def test_hesap_izni_olmayan_servis_kullanicisi_arayabilir(self, client, kisiler):
        await _giris(client, "teknisyen")
        r = await client.get("/api/arama", params={"q": "ACME"})
        assert r.status_code == 200
        assert all(s["tur"] != "HESAP" for s in r.json())

    async def test_hicbir_arayici_izni_yoksa_403(self, client, kisiler):
        await _giris(client, "aramasiz")
        assert (await client.get("/api/arama", params={"q": "ACME"})).status_code == 403

    async def test_kayitli_arayici_yalniz_izinliye_calisir(self, client, kisiler, monkeypatch):
        monkeypatch.setattr(arama_api, "ARAYICILAR", list(arama_api.ARAYICILAR))

        @arama_api.arayici_kaydet("servis.gor")
        async def _servis_ara(db, user, terim, limit):  # kendi izin kontrolü YOK
            return [
                arama_api.AramaSonucu(tur="SERVIS_ISI", id=1, baslik=terim, yol="/servis-isleri/1")
            ]

        assert arama_api.ARAYICILAR[-1] is _servis_ara
        await _giris(client, "teknisyen")
        sonuc = (await client.get("/api/arama", params={"q": "SRV-1"})).json()
        assert [s["tur"] for s in sonuc] == ["SERVIS_ISI"]

        # Kapı geçse bile (hesap.gor) arayıcının izni yoksa sonucu gelmez.
        await _giris(client, "temsilci")
        sonuc = (await client.get("/api/arama", params={"q": "SRV-1"})).json()
        assert "SERVIS_ISI" not in {s["tur"] for s in sonuc}


# --- Parametreler ------------------------------------------------------------------------


class TestAyarSinirlari:
    @pytest.fixture
    async def admin(self, client, kullanici_ac):
        await kullanici_ac("ayarci", "ADMIN")
        await _giris(client, "ayarci")

    @pytest.mark.parametrize(
        ("anahtar", "deger", "mesaj"),
        [
            ("servis_toplu_atama_ust_sinir", 0, "arasında"),
            ("servis_toplu_atama_ust_sinir", "150", "tam sayı"),
            ("servis_toplu_atama_ust_sinir", True, "tam sayı"),
            ("bakim_otomatik_uretim", "evet", "true/false"),
            ("servis_onay_zorunlu_turler", ["PB", "UYDURMA"], "UYDURMA"),
            ("servis_gunluk_ozet_saati", "25:00", "SS:DD"),
            ("servis_sla_yururluk_at", "2026-11-01T00:00:00", "saat dilimi"),
            ("servis_sla_yururluk_at", "yarin", "ISO"),
        ],
    )
    async def test_sinir_disi_400_turkce(self, client, admin, anahtar, deger, mesaj):
        r = await client.patch("/api/ayarlar", json={"values": {anahtar: deger}})
        assert r.status_code == 400, r.text
        assert mesaj in r.json()["detail"]
        assert not r.json()["detail"].startswith("'")  # KeyError tırnağı sızmadı

    async def test_gecerli_deger_kaydedilir(self, client, admin):
        r = await client.patch(
            "/api/ayarlar",
            json={
                "values": {
                    "servis_toplu_atama_ust_sinir": 151,
                    "servis_onay_zorunlu_turler": ["PB", "ARIZA", "PB"],
                    "servis_sla_yururluk_at": "2026-11-01T00:00:00+03:00",
                    "bakim_otomatik_uretim": True,
                }
            },
        )
        assert r.status_code == 200, r.text
        govde = r.json()
        assert govde["servis_toplu_atama_ust_sinir"] == 151
        assert govde["servis_onay_zorunlu_turler"] == ["PB", "ARIZA"]
        assert govde["servis_sla_yururluk_at"] == "2026-11-01T00:00:00+03:00"

    async def test_bir_anahtar_hataliysa_hicbiri_yazilmaz(self, client, db, admin):
        r = await client.patch(
            "/api/ayarlar",
            json={"values": {"servis_ek_silme_saat": 12, "servis_eposta_deneme": 99}},
        )
        assert r.status_code == 400
        assert await db.get(Setting, "servis_ek_silme_saat") is None

    async def test_eski_anahtarlarin_davranisi_degismedi(self, client, admin):
        """Sınır tablosu yalnız yeni anahtarlarda: canlı eşik serbest kalır."""
        r = await client.patch("/api/ayarlar", json={"values": {"atil_hat_gun": "45"}})
        assert r.status_code == 200
        r = await client.patch("/api/ayarlar", json={"values": {"yok_boyle": 1}})
        assert r.status_code == 400


# --- Görev panosu ----------------------------------------------------------------------


async def test_gorev_karti_servis_kayitlarina_baglanir(
    db, seeded, kullanici_ac, servis_isi_ac, ekipman_ac, sozlesme_ac
):
    so = await servis_isi_ac()
    ekipman = await ekipman_ac(seri="GIZLI-SERI")
    sozlesme = await sozlesme_ac()
    okuyan = await kullanici_ac("gorev_okuyan", "ADMIN")
    sonuc = await gorev_svc.baglanti_cozumle(
        db,
        {("servis_isi", so.id), ("ekipman", ekipman.id), ("bakim_sozlesme", sozlesme.id)},
        okuyan,
    )
    assert sonuc[("servis_isi", so.id)] == {
        "ad": "Servis İşi",
        "etiket": so.so_no,
        "yol": f"/servis-isleri/{so.id}",
        "var": True,
    }
    # Ekipman kartı seri numarası/müşteri taşımaz (görevlerde kapsam yok).
    assert sonuc[("ekipman", ekipman.id)]["etiket"] == f"#{ekipman.id}"
    assert "GIZLI" not in str(sonuc[("ekipman", ekipman.id)])
    assert sonuc[("bakim_sozlesme", sozlesme.id)]["etiket"] == sozlesme.contract_no
    assert sonuc[("bakim_sozlesme", sozlesme.id)]["yol"] == f"/bakim?sozlesme={sozlesme.id}"


async def test_kayit_tipleri_ucu_yeni_tipleri_listeler(client, kullanici_ac):
    await kullanici_ac("gorevci", "ADMIN")
    await _giris(client, "gorevci")
    r = await client.get("/api/gorevler/kayit-tipleri")
    assert r.status_code == 200
    assert {"servis_isi", "ekipman", "bakim_sozlesme"} <= {t["kod"] for t in r.json()}


# --- İçe aktarma profilleri ----------------------------------------------------------------


def test_teknik_servis_profilleri_listenin_sonunda() -> None:
    kodlar = list(ice.PROFILLER)
    assert kodlar[:9] == [
        "hesap", "cihaz", "hat", "arac", "cihaz_hat", "cihaz_arac", "cihaz_zimmet",
        "tarife", "abonelik",
    ]  # fmt: skip
    assert set(ice.PROFILLER) == set(ice.PROFIL_IZINLERI)
    if "personel" not in ice.PROFILLER:
        pytest.skip("personel profili henüz teslim edilmedi (D0-D)")
    assert kodlar[9] == "personel"
    assert ice.PROFIL_IZINLERI["personel"] == "personel.yaz"


# --- Belge numarası (TS-011) ------------------------------------------------------------------


class TestBelgeNo:
    async def test_bicim_ve_artan_sira(self, db):
        a = await numara.belge_no(db, "service_order_no_seq", "SRV", date(2026, 10, 21))
        b = await numara.belge_no(db, "service_order_no_seq", "PB", date(2026, 10, 21))
        assert re.match(numara.NUMARA_DESENI, a) and re.match(numara.NUMARA_DESENI, b)
        assert a.startswith("SRV-202610-") and b.startswith("PB-202610-")
        # SRV ve PB ORTAK sıradan çeker (plan §1.6).
        assert int(b.rsplit("-", 1)[1]) == int(a.rsplit("-", 1)[1]) + 1

    async def test_ay_turkiye_gununden(self, db):
        """31 Ekim 22:30 UTC Türkiye'de 1 Kasım'dır: numara KASIM ayını taşır."""
        an = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)
        no = await numara.belge_no(db, "service_visit_no_seq", "ZYR", an)
        assert no.startswith("ZYR-202611-")

    @pytest.mark.parametrize(
        ("sekans", "onek"),
        [
            ("service_order_no_seq", "ZYR"),  # yanlış seri
            ("yok_seq", "SRV"),
            ("service_order_no_seq", "srv"),
            ("service_order_no_seq", "SRV; DROP"),
        ],
    )
    async def test_gecersiz_seri_ya_da_onek(self, db, sekans, onek):
        with pytest.raises(ValueError):
            await numara.belge_no(db, sekans, onek, date(2026, 1, 1))

    async def test_bakim_sozlesme_no(self, db):
        no = await numara.bakim_sozlesme_no(db)
        assert re.match(numara.BAKIM_SOZLESME_DESENI, no)
