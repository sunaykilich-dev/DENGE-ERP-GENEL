"""Satış: iskonto limitleri ve kademeli onay, kaybedilme nedeni, Tekliflerim,
keşif isteği ve raporu, satıştan kurulum/teslimat işi, Satışlarımın durumu
(KARARLAR 2026-11-09 S1, S2, S3, S4.1, S4.2).

Her kullanıcı kendi çerezini taşıyan ayrı istemciyle oturum açar
(`servis_teklif_yardimci.oturum`): hazırlayan ≠ onaylayan senaryoları için.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from servis_teklif_yardimci import kapat, musteri, oturum
from sqlalchemy import select

from app.clock import FakeClock
from app.models import (
    Attachment,
    AuditLog,
    Quote,
    QuoteVersion,
    SatisIsBagi,
    ServiceHold,
    ServiceOrder,
    ServiceResult,
    User,
)
from app.services import satis_takip
from app.services import settings as ayar_svc

pytestmark = pytest.mark.integration

ONEK = "/api/satis-takip"
# `quotes.created_at` veritabanı saatinden (now()) gelir, FakeClock'tan değil.
GENIS = {"tarih_bas": "2025-01-01", "tarih_bit": "2035-12-31"}


def _kalem(iskonto: float = 0, fiyat: float = 1000) -> dict:
    return {
        "item_type": "SERBEST",
        "description": "Telsiz sistemi",
        "qty": 1,
        "unit_price": fiyat,
        "discount_pct": iskonto,
        "vat_rate": 0.20,
    }


async def _teklif(ist, musteri_id: int, *kalemler: dict, **kw) -> dict:
    r = await ist.post(
        "/api/teklifler",
        json={"customer_id": musteri_id, "kalemler": list(kalemler) or [_kalem()], **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _elle_gonder(ist, teklif_id: int):
    return await ist.post(
        f"/api/teklifler/{teklif_id}/elle-gonderildi", json={"kanal": "ELDEN", "not": "elden"}
    )


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac):
    await kullanici_ac("satisci", "SATIS")
    await kullanici_ac("satisci2", "SATIS")
    await kullanici_ac("smudur", "SATIS_MUDURU")
    await kullanici_ac("yonetici", "ADMIN")
    await kullanici_ac("finans", "FINANS_YONETICI")
    await birimli_kullanici_ac("gsef", "SERVIS_SEF", ["GUVENLIK"])
    ist = {ad: await oturum(ad) for ad in ("satisci", "satisci2", "smudur", "yonetici", "finans")}
    ist["gsef"] = await oturum("gsef")
    ist["musteri"] = await musteri(db, "Satış Takip Müşterisi A.Ş.")
    yield ist
    await kapat(*(v for k, v in ist.items() if k != "musteri"))


# =====================================================================================
# S1 — İskonto limitleri ve kademeli onay
# =====================================================================================


class TestIskontoLimiti:
    async def test_limit_altinda_onay_adimi_yok(self, ortam):
        """S1.6: limitin (%10) altındaki teklif hiçbir onaya takılmaz."""
        t = await _teklif(ortam["satisci"], ortam["musteri"].id, _kalem(8))
        assert t["onay_gerekiyor"] is False
        assert t["iskonto_onay_kademesi"] is None
        assert Decimal(t["iskonto_limiti"]) == Decimal("10")
        r = await _elle_gonder(ortam["satisci"], t["id"])
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "GONDERILDI"

    async def test_limit_ustu_mudur_onaylar_sonra_gonderilir(self, ortam):
        t = await _teklif(ortam["satisci"], ortam["musteri"].id, _kalem(15), _kalem(5))
        assert t["onay_gerekiyor"] is True
        assert Decimal(t["iskonto_orani"]) == Decimal("15.00")
        assert t["iskonto_onay_kademesi"] == "SATIS_MUDURU"
        r = await ortam["satisci"].post(f"/api/teklifler/{t['id']}/gonder", json={})
        assert r.status_code == 409 and "Satış Müdürü" in r.json()["detail"]
        r = await _elle_gonder(ortam["satisci"], t["id"])
        assert r.status_code == 409
        # Onay satış müdürüne düşer.
        assert (
            await ortam["satisci"].post(f"/api/teklifler/{t['id']}/iskonto-onayla")
        ).status_code == 403
        r = await ortam["smudur"].post(f"/api/teklifler/{t['id']}/iskonto-onayla")
        assert r.status_code == 200, r.text
        assert r.json()["onay_gerekiyor"] is False
        assert (
            await ortam["smudur"].post(f"/api/teklifler/{t['id']}/iskonto-onayla")
        ).status_code == 409
        r = await _elle_gonder(ortam["satisci"], t["id"])
        assert r.status_code == 200, r.text

    async def test_mudur_limiti_ustu_genel_mudure_gider(self, ortam, db):
        """S1.4 kademeli: %30 > müdür limiti %25 → müdür onaylayamaz, ADMIN onaylar."""
        t = await _teklif(ortam["satisci"], ortam["musteri"].id, _kalem(30))
        assert t["iskonto_onay_kademesi"] == "GENEL_MUDUR"
        assert t["iskonto_onay_kademesi_adi"] == "Genel Müdür"
        r = await ortam["smudur"].post(f"/api/teklifler/{t['id']}/iskonto-onayla")
        assert r.status_code == 403
        assert "limitinizi" in r.json()["detail"]
        r = await ortam["yonetici"].post(f"/api/teklifler/{t['id']}/iskonto-onayla")
        assert r.status_code == 200, r.text
        kayit = await db.scalar(
            select(AuditLog).where(
                AuditLog.entity == "quotes",
                AuditLog.action == "iskonto.onayla",
                AuditLog.entity_id == str(t["id"]),
            )
        )
        assert kayit.new_value["kademe"] == "GENEL_MUDUR"

    async def test_mudurun_kendi_limiti(self, ortam):
        """Satış müdürü %25'e kadar onaysız; üstünü kendisi onaylayamaz."""
        t = await _teklif(ortam["smudur"], ortam["musteri"].id, _kalem(25))
        assert t["onay_gerekiyor"] is False
        t2 = await _teklif(ortam["smudur"], ortam["musteri"].id, _kalem(26))
        assert t2["iskonto_onay_kademesi"] == "GENEL_MUDUR"
        r = await ortam["smudur"].post(f"/api/teklifler/{t2['id']}/iskonto-onayla")
        assert r.status_code == 403

    async def test_kisi_limiti_rol_limitinin_yerine_gecer(self, ortam, db):
        """S1.2: kişiye özel limit (yalnız sistem.ayar; iyimser kilit)."""
        u = await db.scalar(select(User).where(User.username == "satisci"))
        r = await ortam["satisci"].put(
            f"{ONEK}/iskonto-limitleri/kisi/{u.id}",
            json={"iskonto_limiti_yuzde": 20, "version": u.version},
        )
        assert r.status_code == 403
        r = await ortam["yonetici"].put(
            f"{ONEK}/iskonto-limitleri/kisi/{u.id}",
            json={"iskonto_limiti_yuzde": 20, "version": u.version},
        )
        assert r.status_code == 200, r.text
        assert Decimal(r.json()["etkin_limit"]) == Decimal("20")
        eski = r.json()["version"] - 1
        r = await ortam["yonetici"].put(
            f"{ONEK}/iskonto-limitleri/kisi/{u.id}",
            json={"iskonto_limiti_yuzde": 30, "version": eski},
        )
        assert r.status_code == 409
        t = await _teklif(ortam["satisci"], ortam["musteri"].id, _kalem(15))
        assert t["onay_gerekiyor"] is False
        liste = (await ortam["yonetici"].get(f"{ONEK}/iskonto-limitleri")).json()
        assert liste["rol_limitleri"]["SATIS"] == 10
        satir = next(k for k in liste["kisiler"] if k["id"] == u.id)
        assert Decimal(satir["kisi_limiti"]) == Decimal("20")
        assert await db.scalar(
            select(AuditLog.id).where(
                AuditLog.entity == "users", AuditLog.action == "iskonto_limiti"
            )
        )

    async def test_rol_limitleri_ayardan_degisir(self, ortam):
        r = await ortam["yonetici"].patch(
            "/api/ayarlar",
            json={
                "values": {
                    "iskonto_rol_limitleri": {
                        "SATIS": 5,
                        "SATIS_DESTEK": 5,
                        "SATIS_MUDURU": 25,
                        "DIGER": 10,
                    }
                }
            },
        )
        assert r.status_code == 200, r.text
        t = await _teklif(ortam["satisci"], ortam["musteri"].id, _kalem(8))
        assert t["onay_gerekiyor"] is True
        r = await ortam["yonetici"].patch(
            "/api/ayarlar", json={"values": {"iskonto_rol_limitleri": {"SATIS": 101}}}
        )
        assert r.status_code == 400
        r = await ortam["yonetici"].patch(
            "/api/ayarlar", json={"values": {"iskonto_rol_limitleri": {"satis": 5}}}
        )
        assert r.status_code == 400

    async def test_fiyat_degisince_onay_duser(self, ortam):
        """S1.5: onaydan sonra fiyat/iskonto değişirse onay düşer; yalnız başlık
        değişikliği onayı korur."""
        t = await _teklif(ortam["satisci"], ortam["musteri"].id, _kalem(15))
        r = await ortam["smudur"].post(f"/api/teklifler/{t['id']}/iskonto-onayla")
        assert r.status_code == 200
        govde = {"customer_id": ortam["musteri"].id, "kalemler": [_kalem(15)]}
        r = await ortam["satisci"].put(
            f"/api/teklifler/{t['id']}",
            json={**govde, "title": "Yeni başlık", "version": r.json()["version"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["onay_gerekiyor"] is False
        r = await ortam["satisci"].put(
            f"/api/teklifler/{t['id']}",
            json={**govde, "kalemler": [_kalem(18)], "version": r.json()["version"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["onay_gerekiyor"] is True
        gecmis = (await ortam["satisci"].get(f"/api/teklifler/{t['id']}/gecmis")).json()
        assert any(g["eylem"] == "iskonto.onay_dustu" for g in gecmis)


# =====================================================================================
# S2 — Kaybedilme nedeni, Tekliflerim, hatırlatma
# =====================================================================================


class TestKayipNedeni:
    async def test_katalogdan_secilir_diger_aciklama_ister(self, ortam):
        s = ortam["satisci"]
        katalog = (await s.get(f"{ONEK}/kayip-nedenleri")).json()
        assert [k["kod"] for k in katalog][-1] == "DIGER"
        assert len(katalog) == 7
        t = await _teklif(s, ortam["musteri"].id)
        await _elle_gonder(s, t["id"])
        yol = f"/api/teklifler/{t['id']}/karar"
        assert (await s.post(yol, json={"kabul": False})).status_code == 400
        r = await s.post(yol, json={"kabul": False, "kayip_nedeni_kod": "DIGER"})
        assert r.status_code == 400
        r = await s.post(yol, json={"kabul": False, "kayip_nedeni_kod": "UYDURMA"})
        assert r.status_code == 400
        r = await s.post(yol, json={"kabul": False, "kayip_nedeni_kod": "RAKIP"})
        assert r.status_code == 200, r.text
        assert r.json()["lost_reason_kod"] == "RAKIP"
        assert r.json()["lost_reason_adi"] == "Rakip tercih edildi"

    async def test_kodsuz_metin_diger_olur(self, ortam, db):
        s = ortam["satisci"]
        t = await _teklif(s, ortam["musteri"].id)
        await _elle_gonder(s, t["id"])
        r = await s.post(
            f"/api/teklifler/{t['id']}/karar",
            json={"kabul": False, "red_nedeni": "Proje iptal oldu"},
        )
        assert r.status_code == 200, r.text
        q = await db.get(Quote, t["id"])
        await db.refresh(q)
        assert (q.lost_reason_kod, q.lost_reason) == ("DIGER", "Proje iptal oldu")


class TestTekliflerim:
    async def _hazirla(self, ortam, db):
        s, m = ortam["satisci"], ortam["musteri"].id
        kazanilan = await _teklif(s, m)
        await _elle_gonder(s, kazanilan["id"])
        await s.post(f"/api/teklifler/{kazanilan['id']}/karar", json={"kabul": True})
        for kod in ("RAKIP", "RAKIP", "FIYAT_YUKSEK"):
            t = await _teklif(s, m)
            await _elle_gonder(s, t["id"])
            await s.post(
                f"/api/teklifler/{t['id']}/karar", json={"kabul": False, "kayip_nedeni_kod": kod}
            )
        dolan = await _teklif(s, m)
        await _elle_gonder(s, dolan["id"])
        q = await db.get(Quote, dolan["id"])
        v = await db.get(QuoteVersion, q.current_version_id)
        v.valid_until = date(2025, 12, 1)
        await db.commit()
        await _teklif(s, m)  # açık
        await _teklif(ortam["satisci2"], m)  # başka satışçı

    async def test_kendi_tekliflerim_ve_oranlar(self, ortam, db):
        await self._hazirla(ortam, db)
        r = await ortam["satisci"].get(f"{ONEK}/tekliflerim", params=GENIS)
        assert r.status_code == 200, r.text
        v = r.json()
        o = v["ozet"]
        assert (o["toplam"], o["acik"], o["kazanilan"], o["kaybedilen"], o["suresi_dolan"]) == (
            6, 1, 1, 3, 1,
        )  # fmt: skip
        assert o["kazanma_orani"] == 20.0 and o["kayip_orani"] == 60.0
        assert v["kayip_nedenleri"][0] == {
            "kod": "RAKIP",
            "neden": "Rakip tercih edildi",
            "adet": 2,
        }
        assert v["satiscilar"] == []
        # Dönem dışı: hiçbir teklif.
        r = await ortam["satisci"].get(
            f"{ONEK}/tekliflerim", params={"tarih_bas": "2020-01-01", "tarih_bit": "2020-06-30"}
        )
        assert r.json()["ozet"]["toplam"] == 0

    async def test_ekip_kirilimi_yalniz_mudurde(self, ortam, db):
        await self._hazirla(ortam, db)
        assert (
            await ortam["satisci"].get(f"{ONEK}/tekliflerim", params={"ekip": True})
        ).status_code == 403
        r = await ortam["smudur"].get(
            f"{ONEK}/tekliflerim",
            params={"ekip": True, **GENIS},
        )
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["ozet"]["toplam"] == 7
        satirlar = {s["ad"]: s for s in v["satiscilar"]}
        assert satirlar["Satisci"]["toplam"] == 6
        assert satirlar["Satisci2"]["acik"] == 1

    async def test_suresi_yaklasan_hatirlatma(self, ortam, db):
        s = ortam["satisci"]
        t = await _teklif(s, ortam["musteri"].id)
        await _elle_gonder(s, t["id"])
        q = await db.get(Quote, t["id"])
        v = await db.get(QuoteVersion, q.current_version_id)
        v.valid_until = date(2026, 1, 3)
        await db.commit()
        uyarilar = (await s.get("/api/raporlar/uyarilar")).json()["uyarilar"]
        kodlar = {u["kod"]: u["adet"] for u in uyarilar}
        assert kodlar.get("satis.teklif_suresi_yaklasan") == 1
        # Başka satışçıya hatırlatılmaz.
        diger = (await ortam["satisci2"].get("/api/raporlar/uyarilar")).json()["uyarilar"]
        assert "satis.teklif_suresi_yaklasan" not in {u["kod"] for u in diger}

    async def test_iskonto_onayi_mudure_hatirlatilir(self, ortam):
        t = await _teklif(ortam["satisci"], ortam["musteri"].id, _kalem(15))
        await ortam["satisci"].post(f"/api/teklifler/{t['id']}/gonder", json={})
        mudur = {
            u["kod"]: u["adet"]
            for u in (await ortam["smudur"].get("/api/raporlar/uyarilar")).json()["uyarilar"]
        }
        assert mudur.get("satis.iskonto_onay_bekleyen") == 1


# =====================================================================================
# S3 — Keşif
# =====================================================================================


class TestKesif:
    async def test_kesif_iste_planlamada_normal_hedef_5_is_gunu(self, ortam, db):
        s = ortam["satisci"]
        t = await _teklif(s, ortam["musteri"].id)
        yol = f"{ONEK}/teklif/{t['id']}/kesif"
        assert (await s.post(yol, json={})).status_code == 400  # birim seçilmedi
        assert (await s.post(yol, json={"birim": "POC"})).status_code == 400
        assert (
            await s.post(yol, json={"birim": "GUVENLIK", "oncelik": "KRITIK"})
        ).status_code == 422
        r = await s.post(yol, json={"birim": "GUVENLIK", "oncelik": "YUKSEK"})
        assert r.status_code == 201, r.text
        so = await db.get(ServiceOrder, r.json()["service_order_id"])
        assert (so.tur, so.kategori, so.status, so.oncelik) == (
            "KESIF", "PROJE", "PLANLAMADA", "YUKSEK",
        )  # fmt: skip
        assert so.cozum_hedef_at is None and so.sla_policy_id is None
        bag = await db.scalar(select(SatisIsBagi).where(SatisIsBagi.service_order_id == so.id))
        # FakeClock 2026-01-01 (Perşembe) + 5 iş günü = 2026-01-08.
        assert bag.hedef_tarih == date(2026, 1, 8)
        assert "08.01.2026" in so.aciklama
        isler = r.json()["isler"]
        assert [(i["bag_turu"], i["asama"]) for i in isler] == [("KESIF", "PLANLAMA_BEKLIYOR")]
        # Açık keşif varken ikincisi yok.
        assert (await s.post(yol, json={"birim": "GUVENLIK"})).status_code == 409

    async def test_dar_izin_ve_kapsam(self, ortam):
        s = ortam["satisci"]
        t = await _teklif(s, ortam["musteri"].id)
        # Satış rolü genel servis işi açamaz (S3.1: yalnız dar izin).
        r = await s.post(
            "/api/teknik-servis/isler",
            json={"birim": "GUVENLIK", "tur": "KESIF", "konu": "x", "customer_id": 1},
        )
        assert r.status_code == 403
        # İzni olmayan rol (finans) 403; başka satışçı 404.
        yol = f"{ONEK}/teklif/{t['id']}/kesif"
        assert (await ortam["finans"].post(yol, json={"birim": "GUVENLIK"})).status_code == 403
        assert (await ortam["satisci2"].post(yol, json={"birim": "GUVENLIK"})).status_code == 404
        assert (await ortam["satisci2"].get(f"{ONEK}/teklif/{t['id']}/isler")).status_code == 404

    async def test_birimli_teklifte_birim_tekliften(self, ortam, db):
        sef = ortam["gsef"]
        t = await _teklif(sef, ortam["musteri"].id, birim="GUVENLIK")
        # Şefte teklif.kesif_iste yok.
        r = await sef.post(f"{ONEK}/teklif/{t['id']}/kesif", json={})
        assert r.status_code == 403

    async def test_sonuc_fotograf_rapor_ve_bildirim(self, ortam, db):
        from app.services import pdf as pdf_svc
        from app.services import storage as depo

        s = ortam["satisci"]
        t = await _teklif(s, ortam["musteri"].id, title="Otopark kamera")
        r = await s.post(f"{ONEK}/teklif/{t['id']}/kesif", json={"birim": "HABERLESME"})
        so_id = r.json()["service_order_id"]
        # Teknisyen sahada raporu girer ve fotoğraf yükler (servis akışının sonucu).
        so = await db.get(ServiceOrder, so_id)
        so.status = "TAMAMLANDI"
        so.completed_at = datetime(2026, 1, 5, 10, tzinfo=UTC)
        db.add(
            ServiceResult(
                service_order_id=so_id,
                sonuc="TEKLIF_SUNULACAK",
                cozum_kanali="YERINDE",
                yapilan_islem="Çatıya 2 direk gerekli; kablo güzergâhı 40 m.",
            )
        )
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
            b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01"
            b"\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        kayit = depo.yaz(png, mime_type="image/png")
        ek = Attachment(
            entity="service_orders",
            entity_id=so_id,
            kind="SERVIS_SONRASI",
            file_name="cati.png",
            storage_path=kayit.storage_path,
            mime_type="image/png",
            size_bytes=kayit.size_bytes,
            sha256=kayit.sha256,
        )
        db.add(ek)
        await db.commit()

        r = await s.get(f"{ONEK}/teklif/{t['id']}/isler/{so_id}/sonuc")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["tamamlandi"] is True and "direk" in v["rapor"]
        assert [e["dosya_adi"] for e in v["ekler"]] == ["cati.png"] and v["ekler"][0]["gorsel"]
        r = await s.get(f"{ONEK}/teklif/{t['id']}/isler/{so_id}/ekler/{ek.id}")
        assert r.status_code == 200 and r.content == png
        assert (
            await ortam["satisci2"].get(f"{ONEK}/teklif/{t['id']}/isler/{so_id}/ekler/{ek.id}")
        ).status_code == 404
        isler = (await s.get(f"{ONEK}/teklif/{t['id']}/isler")).json()
        assert isler[0]["asama"] == "TAMAMLANDI"
        # S3.3: satışçıya bildirim (uyarı merkezi).
        uyarilar = (await s.get("/api/raporlar/uyarilar")).json()["uyarilar"]
        kodlar = {u["kod"]: u["adet"] for u in uyarilar}
        assert kodlar.get("satis.kesif_tamamlandi") == 1
        liste = await s.get("/api/teklifler", params={"kesif": "TAMAMLANDI"})
        assert [x["id"] for x in liste.json()] == [t["id"]]
        # Keşif raporu PDF: içerik (HTML) + uç (WeasyPrint yoksa 503).
        q = await db.get(Quote, t["id"])
        baglam = await satis_takip.kesif_raporu_baglami(db, q, so, clock=FakeClock())
        html = pdf_svc.html_uret("kesif_raporu.html", **baglam)
        assert "KEŞİF RAPORU" in html and "direk" in html and "data:image/png;base64" in html
        assert "Otopark kamera" in html
        r = await s.get(f"{ONEK}/teklif/{t['id']}/isler/{so_id}/kesif-raporu.pdf")
        assert r.status_code in (200, 503), r.text
        if r.status_code == 200:
            assert r.content.startswith(b"%PDF")


# =====================================================================================
# S4.1 / S4.2 — Satış sonrası işler ve aşama takibi
# =====================================================================================


class TestSatisSonrasi:
    async def test_kabul_edilen_tekliften_coklu_is_ve_asamalar(self, ortam, db):
        s = ortam["satisci"]
        t = await _teklif(s, ortam["musteri"].id)
        await s.post(f"{ONEK}/teklif/{t['id']}/kesif", json={"birim": "GUVENLIK"})
        yol = f"{ONEK}/teklif/{t['id']}/is"
        assert (
            await s.post(yol, json={"tur": "KURULUM", "birim": "GUVENLIK"})
        ).status_code == 409  # kabul edilmeden
        await _elle_gonder(s, t["id"])
        await s.post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        assert (await s.post(yol, json={"tur": "ARIZA", "birim": "GUVENLIK"})).status_code == 422
        assert (await s.post(yol, json={"tur": "KURULUM"})).status_code == 400
        r = await s.post(
            yol, json={"tur": "KURULUM", "birim": "GUVENLIK", "hedef_tarih": "2026-01-20"}
        )
        assert r.status_code == 201, r.text
        kurulum = await db.get(ServiceOrder, r.json()["service_order_id"])
        assert (kurulum.tur, kurulum.status, kurulum.kategori) == ("KURULUM", "PLANLAMADA", "PROJE")
        r = await s.post(yol, json={"tur": "TESLIMAT", "birim": "BARIYER"})
        assert r.status_code == 201, r.text
        teslimat = await db.get(ServiceOrder, r.json()["service_order_id"])
        assert teslimat.tur == "TESLIMAT"
        isler = r.json()["isler"]
        assert [i["bag_turu"] for i in isler] == ["KESIF", "KURULUM", "TESLIMAT"]
        # Aşama: kurulum yolda, teslimat askıda (neden ile).
        kurulum.status = "YOLA_CIKILDI"
        teslimat.status = "BEKLEMEDE"
        db.add(
            ServiceHold(
                service_order_id=teslimat.id,
                neden="MALZEME",
                aciklama="Bariyer gelmedi",
                onceki_durum="PLANLAMADA",
                started_at=datetime(2026, 1, 2, tzinfo=UTC),
                sla_durdurur=False,
            )
        )
        await db.commit()
        isler = {i["bag_turu"]: i for i in (await s.get(f"{ONEK}/teklif/{t['id']}/isler")).json()}
        assert isler["KURULUM"]["asama"] == "YOLDA"
        assert isler["TESLIMAT"]["asama"] == "ASKIDA"
        assert isler["TESLIMAT"]["askida_nedeni"] == "Malzeme bekleniyor: Bariyer gelmedi"
        assert isler["KURULUM"]["hedef_tarih"] == "2026-01-20"
        # Maliyet/fiyat taşınmaz.
        assert not any("maliyet" in k or "tutar" in k for k in isler["KURULUM"])

    async def test_siparisten_is_ve_satislarim(self, ortam, db, urun_ac):
        s = ortam["satisci"]
        u = await urun_ac("KMR-1", "YOK", list_price=Decimal("500"))
        t = await _teklif(s, ortam["musteri"].id, {"product_id": u.id, "qty": 2})
        await _elle_gonder(s, t["id"])
        await s.post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        await s.post(f"{ONEK}/teklif/{t['id']}/is", json={"tur": "TESLIMAT", "birim": "GUVENLIK"})
        r = await s.post(f"/api/siparisler/tekliften/{t['id']}")
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        yol = f"{ONEK}/siparis/{sid}/is"
        assert (await s.post(yol, json={"tur": "KURULUM", "birim": "GUVENLIK"})).status_code == 409
        assert (await s.post(f"/api/siparisler/{sid}/onayla")).status_code == 200
        r = await s.post(yol, json={"tur": "KURULUM", "birim": "GUVENLIK"})
        assert r.status_code == 201, r.text
        assert [i["bag_turu"] for i in r.json()["isler"]] == ["TESLIMAT", "KURULUM"]
        bag = await db.scalar(
            select(SatisIsBagi).where(SatisIsBagi.service_order_id == r.json()["service_order_id"])
        )
        assert (bag.order_id, bag.quote_id) == (sid, t["id"])
        # Teklif ekranı siparişten açılan işi de görür.
        teklif_isleri = (await s.get(f"{ONEK}/teklif/{t['id']}/isler")).json()
        assert len(teklif_isleri) == 2
        # Başka satışçı siparişi göremez.
        assert (await ortam["satisci2"].get(f"{ONEK}/siparis/{sid}/isler")).status_code == 404
        assert (
            await ortam["satisci2"].post(yol, json={"tur": "KURULUM", "birim": "GUVENLIK"})
        ).status_code == 404

        # S4.2 Satışlarımın durumu: sipariş satırı (teklif tekrar edilmez).
        r = await s.get(f"{ONEK}/satislarim")
        assert r.status_code == 200, r.text
        satirlar = r.json()
        assert [(x["kaynak"], x["no"]) for x in satirlar] == [("SIPARIS", satirlar[0]["no"])]
        assert satirlar[0]["genel_asama"] == "DEVAM" and len(satirlar[0]["isler"]) == 2
        assert (await ortam["satisci2"].get(f"{ONEK}/satislarim")).json() == []
        assert (await s.get(f"{ONEK}/satislarim", params={"ekip": True})).status_code == 403
        assert (
            len((await ortam["smudur"].get(f"{ONEK}/satislarim", params={"ekip": True})).json())
            == 1
        )

    async def test_musteri_karti_isleri(self, ortam, db):
        s = ortam["satisci"]
        # Müşteri kartı müşteri kapsamıyla: satış temsilcisi yalnız kendi müşterisini görür.
        m = await db.get(type(ortam["musteri"]), ortam["musteri"].id)
        m.sales_rep_id = await db.scalar(select(User.id).where(User.username == "satisci"))
        await db.commit()
        t = await _teklif(s, ortam["musteri"].id)
        await s.post(f"{ONEK}/teklif/{t['id']}/kesif", json={"birim": "GUVENLIK"})
        assert (
            await ortam["satisci2"].get(f"{ONEK}/musteri/{ortam['musteri'].id}/isler")
        ).status_code == 404
        r = await s.get(f"{ONEK}/musteri/{ortam['musteri'].id}/isler")
        assert r.status_code == 200, r.text
        assert [i["tur"] for i in r.json()] == ["KESIF"]
        assert (
            await ortam["finans"].get(f"{ONEK}/musteri/{ortam['musteri'].id}/isler")
        ).status_code in (200,)


def test_asama_eslemesi_tam() -> None:
    from app.models.teknik_servis import SERVIS_DURUMLARI

    for d in SERVIS_DURUMLARI:
        assert satis_takip.asama(d) in satis_takip.ASAMA_ADLARI
    assert satis_takip.asama("SAHADA") == "SAHADA"
    assert satis_takip.asama("ISLEMDE") == "SAHADA"
    assert satis_takip.asama("KAPATILDI") == "TAMAMLANDI"


def test_kesif_hedef_tarihi_gecerlilikten_turetilir() -> None:
    bugun = date(2026, 1, 1)
    assert satis_takip.kesif_hedef_tarihi(bugun, None) == date(2026, 1, 8)
    assert satis_takip.kesif_hedef_tarihi(bugun, date(2026, 1, 5)) == date(2026, 1, 5)
    assert satis_takip.kesif_hedef_tarihi(bugun, date(2025, 12, 1)) == date(2026, 1, 8)
    assert satis_takip.kesif_hedef_tarihi(bugun, bugun + timedelta(days=30)) == date(2026, 1, 8)


async def test_varsayilan_rol_limitleri(db) -> None:
    tablo = await ayar_svc.get(db, "iskonto_rol_limitleri")
    assert (tablo["SATIS"], tablo["SATIS_DESTEK"], tablo["SATIS_MUDURU"]) == (10, 5, 25)
