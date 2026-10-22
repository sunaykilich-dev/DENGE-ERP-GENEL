"""Birimli (teknik servis) teklif akışı: iç onay, TEKLIF makinesi, karar, revizyon,
public link kuralı, servis işi köprüsü ve gelir aktarımı (TS-141, TS-147, TS-148).

Senaryolar plan §2.3 kabul ölçütlerinden ve E07 kontrol düzeltmelerinden
(B1, B2, B6, D01, D04, K9) türetildi. Satış akışının değişmediği
`test_teklif.py` ile ayrıca kilitlidir.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from servis_teklif_yardimci import KALEM, elle_gonder, kapat, musteri, onayli, oturum, teklif_ac
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    Quote,
    QuoteVersion,
    ServiceHold,
    ServiceOrder,
    ServiceOrderFinancial,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def ortam(client, db, birimli_kullanici_ac):
    """Hazırlayan şef (GUVENLIK), iki teknik servis müdürü (onaylayıcı)."""
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("mudur1", "SERVIS_YONETICI", ["GUVENLIK"])
    await birimli_kullanici_ac("mudur2", "SERVIS_YONETICI", ["GUVENLIK"])
    sef = await oturum("sef_g")
    mudur1 = await oturum("mudur1")
    mudur2 = await oturum("mudur2")
    m = await musteri(db)
    yield {"sef": sef, "mudur1": mudur1, "mudur2": mudur2, "musteri": m}
    await kapat(sef, mudur1, mudur2)


async def _yenile(db, model, kimlik):
    nesne = await db.get(model, kimlik)
    await db.refresh(nesne)
    return nesne


class TestIcOnay:
    async def test_tam_akis_ve_gecmis(self, ortam, client, db):
        sef, mudur = ortam["sef"], ortam["mudur1"]
        t = await teklif_ac(sef, ortam["musteri"].id)
        assert t["birim"] == "GUVENLIK" and t["status"] == "TASLAK"
        assert t["sonraki_durumlar"] == ["IPTAL", "ONAY_BEKLIYOR"]

        r = await sef.post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})
        assert r.status_code == 200 and r.json()["status"] == "ONAY_BEKLIYOR"
        # Şefte teklif.onayla yok (rol kataloğu).
        assert (await sef.post(f"/api/teklifler/{t['id']}/onayla")).status_code == 403
        r = await mudur.post(f"/api/teklifler/{t['id']}/onayla")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ONAYLANDI"
        assert r.json()["approved_by_ad"]
        assert r.json()["guncel"]["approved_at"] is not None

        r = await elle_gonder(sef, t["id"])
        assert r["status"] == "GONDERILDI"
        r = await sef.post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "KABUL"

        gecmis = (await sef.get(f"/api/teklifler/{t['id']}/gecmis")).json()
        gecisler = [(g["eski_durum"], g["yeni_durum"]) for g in gecmis if g["eylem"] == "durum"]
        assert ("TASLAK", "ONAY_BEKLIYOR") in gecisler
        assert ("ONAY_BEKLIYOR", "ONAYLANDI") in gecisler
        assert ("ONAYLANDI", "GONDERILDI") in gecisler
        assert all(g["kullanici"] for g in gecmis if g["eylem"] == "durum")
        assert any(g["eylem"] == "karar" and g["yeni_durum"] == "KABUL" for g in gecmis)

    async def test_oz_onay_yasak_ayar_kapaliyken_serbest(self, ortam, client, db):
        from app.services import settings as ayar_svc

        mudur = ortam["mudur1"]
        t = await teklif_ac(mudur, ortam["musteri"].id)
        await mudur.post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})
        r = await mudur.post(f"/api/teklifler/{t['id']}/onayla")
        assert r.status_code == 403
        assert "onaylayamazsınız" in r.json()["detail"]

        await ayar_svc.set_many(db, {"teklif_oz_onay_yasak": False}, None)
        await db.commit()
        assert (await mudur.post(f"/api/teklifler/{t['id']}/onayla")).status_code == 200

    async def test_taslaktan_karar_409_ve_veri_degismez(self, ortam, db):
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id)
        r = await ortam["sef"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        assert r.status_code == 409
        q = await _yenile(db, Quote, t["id"])
        assert q.status == "TASLAK"
        v = await _yenile(db, QuoteVersion, q.current_version_id)
        assert v.accepted_at is None

    async def test_onaysiz_gonderim_409(self, ortam):
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id)
        r = await ortam["sef"].post(
            f"/api/teklifler/{t['id']}/elle-gonderildi", json={"kanal": "ELDEN", "not": "elden"}
        )
        assert r.status_code == 409
        r = await ortam["sef"].post(f"/api/teklifler/{t['id']}/gonder", json={})
        assert r.status_code == 409

    async def test_iskonto_onayla_yan_kapisi_kapali(self, ortam, client, db, kullanici_ac):
        """Satış müdürü iskonto onayıyla servis teklifinin iç onayını atlayamaz (B2)."""
        await kullanici_ac("satis_muduru", "SATIS_MUDURU")
        smd = await oturum("satis_muduru")
        try:
            kalem = {**KALEM, "discount_pct": 30}
            t = await teklif_ac(ortam["sef"], ortam["musteri"].id, kalemler=[kalem])
            r = await smd.post(f"/api/teklifler/{t['id']}/iskonto-onayla")
            # Satış müdürü birimli teklife yazamaz (B4) → 404; yazabilen bir
            # onaylayıcı da olsa birimli teklifte 409 döner.
            assert r.status_code == 404
            r = await ortam["mudur1"].post(f"/api/teklifler/{t['id']}/iskonto-onayla")
            assert r.status_code == 409
            # İç onay iskontoyu da kapsar (K4).
            await onayli(ortam["sef"], ortam["mudur1"], t["id"])
            q = await _yenile(db, Quote, t["id"])
            v = await _yenile(db, QuoteVersion, q.current_version_id)
            assert v.discount_approved_at is not None
        finally:
            await kapat(smd)

    async def test_geri_cevir_neden_zorunlu_ve_onay_silinir(self, ortam, db):
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id)
        await onayli(ortam["sef"], ortam["mudur1"], t["id"])
        r = await ortam["mudur1"].post(f"/api/teklifler/{t['id']}/geri-cevir", json={})
        assert r.status_code == 400
        r = await ortam["mudur1"].post(
            f"/api/teklifler/{t['id']}/geri-cevir", json={"neden": "Fiyat güncellenecek"}
        )
        assert r.status_code == 200 and r.json()["status"] == "TASLAK"
        assert r.json()["guncel"]["approved_at"] is None

    async def test_red_nedeni_zorunlu(self, ortam):
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id)
        await onayli(ortam["sef"], ortam["mudur1"], t["id"])
        await elle_gonder(ortam["sef"], t["id"])
        r = await ortam["sef"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": False})
        assert r.status_code == 400

    async def test_satis_teklifinde_ic_onay_ve_iptal_yok(self, ortam, client, kullanici_ac):
        await kullanici_ac("satisci", "SATIS")
        s = await oturum("satisci")
        try:
            t = await teklif_ac(s, ortam["musteri"].id, birim=None)
            assert t["sonraki_durumlar"] == []
            assert (await s.post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})).status_code == 409
            r = await s.post(f"/api/teklifler/{t['id']}/iptal", json={"neden": "vazgeçildi"})
            assert r.status_code == 409
        finally:
            await kapat(s)


class TestSureVeRevizyon:
    async def test_etkin_durum_suresi_doldu_status_degismez(self, ortam, client, db):
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id)
        await onayli(ortam["sef"], ortam["mudur1"], t["id"])
        await elle_gonder(ortam["sef"], t["id"])
        q = await _yenile(db, Quote, t["id"])
        v = await _yenile(db, QuoteVersion, q.current_version_id)
        v.valid_until = client.clock.now().date() - timedelta(days=1)
        await db.commit()

        r = (await ortam["sef"].get(f"/api/teklifler/{t['id']}")).json()
        assert r["status"] == "GONDERILDI"
        assert r["etkin_durum"] == "SURESI_DOLDU"
        assert "KABUL" not in r["sonraki_durumlar"]
        karar = await ortam["sef"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        assert karar.status_code == 409

    async def test_birimli_revize_taslaga_doner_ve_yeniden_onay_ister(self, ortam, db):
        sef = ortam["sef"]
        t = await teklif_ac(sef, ortam["musteri"].id)
        # Onay sürecindeki teklif revize edilemez.
        await sef.post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})
        r = await sef.post(f"/api/teklifler/{t['id']}/revize", json={"kalemler": [KALEM]})
        assert r.status_code == 409
        await ortam["mudur1"].post(f"/api/teklifler/{t['id']}/onayla")
        await elle_gonder(sef, t["id"])
        r0 = (await sef.get(f"/api/teklifler/{t['id']}")).json()["guncel"]

        r = await sef.post(
            f"/api/teklifler/{t['id']}/revize",
            json={"kalemler": [{**KALEM, "unit_price": 1500}]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "TASLAK"
        assert r.json()["guncel"]["version_no"] == 2
        assert r.json()["teklif_no_gosterim"].endswith("-R1")
        eski = await _yenile(db, QuoteVersion, r0["id"])
        assert eski.is_locked is True
        # Yeniden onaylanmadan gönderilemez.
        r = await sef.post(
            f"/api/teklifler/{t['id']}/elle-gonderildi", json={"kanal": "ELDEN", "not": "elden"}
        )
        assert r.status_code == 409


class TestTaslakDuzenleme:
    async def test_put_tutari_yeniden_hesaplar_surum_artmaz(self, ortam):
        sef = ortam["sef"]
        t = await teklif_ac(sef, ortam["musteri"].id)
        r = await sef.put(
            f"/api/teklifler/{t['id']}",
            json={
                "customer_id": ortam["musteri"].id,
                "birim": "GUVENLIK",
                "version": t["version"],
                "title": "Güncel başlık",
                "kalemler": [{**KALEM, "unit_price": 2000}],
            },
        )
        assert r.status_code == 200, r.text
        assert Decimal(r.json()["guncel"]["grand_total"]) == Decimal("2400.00")
        assert r.json()["versiyon_sayisi"] == 1
        assert r.json()["version"] == t["version"] + 1
        assert r.json()["title"] == "Güncel başlık"

        # Eski `version` ile ikinci düzenleme 409 (iyimser kilit).
        r2 = await sef.put(
            f"/api/teklifler/{t['id']}",
            json={
                "customer_id": ortam["musteri"].id,
                "birim": "GUVENLIK",
                "version": t["version"],
                "kalemler": [KALEM],
            },
        )
        assert r2.status_code == 409

    async def test_put_yalniz_taslakta(self, ortam):
        sef = ortam["sef"]
        t = await teklif_ac(sef, ortam["musteri"].id)
        await sef.post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})
        guncel = (await sef.get(f"/api/teklifler/{t['id']}")).json()
        r = await sef.put(
            f"/api/teklifler/{t['id']}",
            json={
                "customer_id": ortam["musteri"].id,
                "birim": "GUVENLIK",
                "version": guncel["version"],
                "kalemler": [KALEM],
            },
        )
        assert r.status_code == 409


class TestPublicLink:
    async def _gonderilmis(self, ortam):
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id)
        await onayli(ortam["sef"], ortam["mudur1"], t["id"])
        g = await elle_gonder(ortam["sef"], t["id"])
        return t, g

    async def _jeton(self, db, surum_id):
        return (await _yenile(db, QuoteVersion, surum_id)).public_token

    async def test_eski_surum_jetonu_karar_almaz(self, ortam, client, db):
        t, g = await self._gonderilmis(ortam)
        r0_jeton = await self._jeton(db, g["guncel"]["id"])
        r = await ortam["sef"].post(f"/api/teklifler/{t['id']}/revize", json={"kalemler": [KALEM]})
        assert r.status_code == 200
        bak = await client.get(f"/api/public/teklif/{r0_jeton}")
        assert bak.status_code == 200
        assert bak.json()["karar_verilebilir"] is False
        assert "güncel" in bak.json()["uyari"]
        karar = await client.post(f"/api/public/teklif/{r0_jeton}/karar", json={"kabul": True})
        assert karar.status_code == 409
        assert (await _yenile(db, Quote, t["id"])).status == "TASLAK"

    async def test_iptal_edilen_teklif_jetonu_409(self, ortam, client, db):
        t, g = await self._gonderilmis(ortam)
        jeton = await self._jeton(db, g["guncel"]["id"])
        r = await ortam["sef"].post(
            f"/api/teklifler/{t['id']}/iptal", json={"neden": "Müşteri vazgeçti"}
        )
        assert r.status_code == 200 and r.json()["status"] == "IPTAL"
        karar = await client.post(f"/api/public/teklif/{jeton}/karar", json={"kabul": True})
        assert karar.status_code == 409
        assert (await _yenile(db, Quote, t["id"])).status == "IPTAL"

    async def test_taslaga_cevrilen_teklifin_eski_jetonu_409(self, ortam, client, db):
        t, g = await self._gonderilmis(ortam)
        jeton = await self._jeton(db, g["guncel"]["id"])
        await ortam["sef"].post(f"/api/teklifler/{t['id']}/revize", json={"kalemler": [KALEM]})
        await ortam["sef"].post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})
        await ortam["mudur1"].post(
            f"/api/teklifler/{t['id']}/geri-cevir", json={"neden": "Yeniden hesaplanacak"}
        )
        karar = await client.post(f"/api/public/teklif/{jeton}/karar", json={"kabul": True})
        assert karar.status_code == 409

    async def test_public_kabul_gelir_ve_denetim_kullanicisiz(
        self, ortam, client, db, servis_isi_ac
    ):
        so = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK")
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, service_order_id=so.id)
        await onayli(ortam["sef"], ortam["mudur1"], t["id"])
        g = await elle_gonder(ortam["sef"], t["id"])
        jeton = await self._jeton(db, g["guncel"]["id"])
        r = await client.post(f"/api/public/teklif/{jeton}/karar", json={"kabul": True})
        assert r.status_code == 200, r.text
        fin = await db.scalar(
            select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so.id)
        )
        assert fin is not None and fin.gelir == Decimal("1000.00")
        assert fin.gelir_kaynagi == "TEKLIF"
        kayit = await db.scalar(
            select(AuditLog).where(
                AuditLog.entity == "service_order_financials", AuditLog.action == "gelir.teklif"
            )
        )
        assert kayit is not None and kayit.user_id is None


class TestServisIsiKopru:
    async def test_isten_acilan_teklif_musteri_adres_kopyalanir(
        self, ortam, db, servis_isi_ac, lokasyon_ac
    ):
        tesis = await lokasyon_ac(ortam["musteri"])
        so = await servis_isi_ac(musteri=ortam["musteri"], lokasyon=tesis, birim="GUVENLIK")
        t = await teklif_ac(
            ortam["sef"], ortam["musteri"].id, birim=None, service_order_id=so.id
        )
        assert t["birim"] == "GUVENLIK"
        assert t["address_id"] == tesis.id
        assert t["so_no"] == so.so_no
        liste = await ortam["sef"].get(f"/api/teklifler?servis_isi_id={so.id}")
        assert [x["id"] for x in liste.json()] == [t["id"]]

    async def test_baska_musterinin_isi_400(self, ortam, db, servis_isi_ac):
        diger = await musteri(db, "Başka Müşteri Ltd.")
        so = await servis_isi_ac(musteri=diger, birim="GUVENLIK")
        r = await ortam["sef"].post(
            "/api/teklifler",
            json={"customer_id": ortam["musteri"].id, "service_order_id": so.id, "kalemler": []},
        )
        assert r.status_code == 400
        assert await db.scalar(select(func.count()).select_from(Quote)) == 0

    async def test_beklet_ile_onaya_gonderim_isi_bekletir_kabulde_kalkar(
        self, ortam, db, servis_isi_ac
    ):
        so = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK", durum="ISLEMDE")
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, service_order_id=so.id)
        r = await ortam["sef"].post(
            f"/api/teklifler/{t['id']}/onaya-gonder", json={"beklet": True}
        )
        assert r.status_code == 200, r.text
        so = await _yenile(db, ServiceOrder, so.id)
        assert so.status == "BEKLEMEDE"
        bekleme = await db.scalar(select(ServiceHold).where(ServiceHold.service_order_id == so.id))
        assert bekleme.neden == "TEKLIF" and bekleme.quote_id == t["id"]

        await ortam["mudur1"].post(f"/api/teklifler/{t['id']}/onayla")
        await elle_gonder(ortam["sef"], t["id"])
        r = await ortam["sef"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        assert r.status_code == 200, r.text
        so = await _yenile(db, ServiceOrder, so.id)
        assert so.status == "ISLEMDE"
        await db.refresh(bekleme)
        assert bekleme.released_at is not None

    async def test_baska_nedenli_bekleme_kabulde_kalir(self, ortam, client, db, servis_isi_ac):
        from app.services.teknik_servis import bekletme

        so = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK", durum="ISLEMDE")
        await bekletme.beklet(db, so, "MALZEME", user=None, clock=client.clock)
        await db.commit()
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, service_order_id=so.id)
        r = await ortam["sef"].post(
            f"/api/teklifler/{t['id']}/onaya-gonder", json={"beklet": True}
        )
        assert r.status_code == 200
        assert any("başka nedenli" in u for u in r.json()["uyarilar"])
        await ortam["mudur1"].post(f"/api/teklifler/{t['id']}/onayla")
        await elle_gonder(ortam["sef"], t["id"])
        await ortam["sef"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        so = await _yenile(db, ServiceOrder, so.id)
        assert so.status == "BEKLEMEDE"
        aktif = await db.scalar(
            select(ServiceHold).where(
                ServiceHold.service_order_id == so.id, ServiceHold.released_at.is_(None)
            )
        )
        assert aktif.neden == "MALZEME"

    async def test_sonuc_beklemesine_teklif_baglanir(self, ortam, client, db, servis_isi_ac):
        """TEKLIF_SUNULACAK sonucunun açtığı TEKLIF beklemesine teklif bağlanır."""
        from app.services.teknik_servis import bekletme

        so = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK", durum="ISLEMDE")
        await bekletme.beklet(db, so, "TEKLIF", user=None, clock=client.clock)
        await db.commit()
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, service_order_id=so.id)
        bekleme = await db.scalar(select(ServiceHold).where(ServiceHold.service_order_id == so.id))
        await db.refresh(bekleme)
        assert bekleme.quote_id == t["id"]


class TestGelir:
    async def _kabul(self, ortam, teklif_id):
        await onayli(ortam["sef"], ortam["mudur1"], teklif_id)
        await elle_gonder(ortam["sef"], teklif_id)
        r = await ortam["sef"].post(f"/api/teklifler/{teklif_id}/karar", json={"kabul": True})
        assert r.status_code == 200, r.text
        return r.json()

    async def _gelir(self, db, so_id):
        fin = await db.scalar(
            select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so_id)
        )
        if fin is not None:
            await db.refresh(fin)
        return fin

    async def test_kdv_haric_net_ikinci_kabul_toplanir_iptal_geri_alir(
        self, ortam, db, servis_isi_ac
    ):
        so = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK")
        t1 = await teklif_ac(
            ortam["sef"],
            ortam["musteri"].id,
            service_order_id=so.id,
            kalemler=[{**KALEM, "unit_price": 10000}],
        )
        await self._kabul(ortam, t1["id"])
        fin = await self._gelir(db, so.id)
        assert fin.gelir == Decimal("10000.00") and fin.gelir_kaynagi == "TEKLIF"

        t2 = await teklif_ac(
            ortam["sef"],
            ortam["musteri"].id,
            service_order_id=so.id,
            kalemler=[{**KALEM, "unit_price": 2500}],
        )
        await self._kabul(ortam, t2["id"])
        assert (await self._gelir(db, so.id)).gelir == Decimal("12500.00")

        # KABUL'den iptal yalnız teklif.onayla (şef 403, müdür 200).
        r = await ortam["sef"].post(f"/api/teklifler/{t2['id']}/iptal", json={"neden": "Hata var"})
        assert r.status_code == 403
        r = await ortam["mudur1"].post(
            f"/api/teklifler/{t2['id']}/iptal", json={"neden": "Müşteri vazgeçti"}
        )
        assert r.status_code == 200, r.text
        assert (await self._gelir(db, so.id)).gelir == Decimal("10000.00")

    async def test_elle_gelir_korunur_uyari_doner(self, ortam, db, servis_isi_ac):
        so = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK")
        db.add(
            ServiceOrderFinancial(
                service_order_id=so.id,
                gelir=Decimal("12000"),
                gelir_kaynagi="ELLE",
                gelir_notu="Elle girildi",
            )
        )
        await db.commit()
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, service_order_id=so.id)
        cikti = await self._kabul(ortam, t["id"])
        assert any("elle girilmiş gelir korundu" in u for u in cikti["uyarilar"])
        assert (await self._gelir(db, so.id)).gelir == Decimal("12000.00")

    async def test_fatura_sonrasi_iptal_409(self, ortam, client, db, servis_isi_ac):
        so = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK")
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, service_order_id=so.id)
        await self._kabul(ortam, t["id"])
        fin = await self._gelir(db, so.id)
        fin.fatura_iletildi_at = client.clock.now()
        await db.commit()
        r = await ortam["mudur1"].post(
            f"/api/teklifler/{t['id']}/iptal", json={"neden": "Müşteri vazgeçti"}
        )
        assert r.status_code == 409
        assert "faturaya iletildi" in r.json()["detail"]
        assert (await _yenile(db, Quote, t["id"])).status == "KABUL"
        assert (await self._gelir(db, so.id)).gelir == Decimal("1000.00")

    async def test_iki_isli_teklif_her_ise_kendi_kalemi(self, ortam, db, servis_isi_ac):
        so1 = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK")
        so2 = await servis_isi_ac(musteri=ortam["musteri"], birim="GUVENLIK")
        t = await teklif_ac(
            ortam["sef"],
            ortam["musteri"].id,
            service_order_id=so1.id,
            kalemler=[
                {**KALEM, "unit_price": 300, "service_order_id": so1.id},
                {**KALEM, "unit_price": 700, "service_order_id": so2.id},
            ],
        )
        await self._kabul(ortam, t["id"])
        assert (await self._gelir(db, so1.id)).gelir == Decimal("300.00")
        assert (await self._gelir(db, so2.id)).gelir == Decimal("700.00")

    async def test_pb_bulgusu_kabulunde_duzeltici_is_acilir(
        self, ortam, client, db, servis_isi_ac, sozlesme_ac
    ):
        from app.models import MaintenanceContractItem, MaintenancePeriod, ServiceOrderSerial

        sozlesme = await sozlesme_ac(musteri=ortam["musteri"])
        kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
        an = client.clock.now()
        donem = MaintenancePeriod(
            contract_id=sozlesme.id, cycle_start=an, sequence_no=1, target_date=an.date()
        )
        db.add_all([kalem, donem])
        await db.commit()
        pb = await servis_isi_ac(
            musteri=ortam["musteri"],
            birim="GUVENLIK",
            tur="PB",
            durum="TAMAMLANDI",
            contract_item_id=kalem.id,
            maintenance_period_id=donem.id,
        )
        db.add(ServiceOrderSerial(service_order_id=pb.id, seri_no="XR-001", seri_norm="XR-001"))
        await db.commit()
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, service_order_id=pb.id)
        await self._kabul(ortam, t["id"])

        duzeltici = await db.scalar(
            select(ServiceOrder).where(
                ServiceOrder.iliskili_is_id == pb.id, ServiceOrder.iliski_turu == "DEVAM"
            )
        )
        assert duzeltici is not None and duzeltici.tur == "PLANSIZ_BAKIM"
        assert duzeltici.status == "PLANLAMADA"
        assert (await self._gelir(db, duzeltici.id)).gelir == Decimal("1000.00")
        # PB işine gelir yazılmaz (K9): sözleşme kapsamı olarak kalır.
        assert await self._gelir(db, pb.id) is None
