"""Teklif kapsamı ve birimi, sayfalama, sunucu doğrulaması ve yuvarlama (TS-140);
satış panel/raporunun birimli tekliflerden ayrılması ve servis teklifinin
siparişe dönüşmemesi (TS-144).

Kalıp "iki birimden iki şef" (00 §6.3/7): GUVENLIK şefi HABERLESME teklifini
göremez ve DEĞİŞTİREMEZ — 404 ve `db.refresh` ile veri aynı.
"""

from decimal import Decimal

import pytest
from servis_teklif_yardimci import KALEM, elle_gonder, kapat, musteri, onayli, oturum, teklif_ac
from sqlalchemy import func, select

from app.models import AuditLog, Quote, QuoteLine, QuoteVersion

pytestmark = pytest.mark.integration


@pytest.fixture
async def ortam(client, db, birimli_kullanici_ac, kullanici_ac):
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_h", "SERVIS_SEF", ["HABERLESME"])
    await birimli_kullanici_ac("mudur", "SERVIS_YONETICI", ["GUVENLIK"])
    await kullanici_ac("satis1", "SATIS")
    await kullanici_ac("satis2", "SATIS")
    await kullanici_ac("smd", "SATIS_MUDURU")
    ist = {ad: await oturum(ad) for ad in ("sef_g", "sef_h", "mudur", "satis1", "satis2", "smd")}
    ist["musteri"] = await musteri(db)
    yield ist
    await kapat(*(v for k, v in ist.items() if k != "musteri"))


async def _anlik(db, teklif_id: int) -> dict:
    t = await db.get(Quote, teklif_id)
    await db.refresh(t)
    v = await db.get(QuoteVersion, t.current_version_id)
    await db.refresh(v)
    kalemler = (
        await db.scalars(select(QuoteLine.unit_price).where(QuoteLine.version_id == v.id))
    ).all()
    return {
        "status": t.status,
        "version": t.version,
        "surum": t.current_version_id,
        "surum_sayisi": await db.scalar(
            select(func.count()).where(QuoteVersion.quote_id == teklif_id)
        ),
        "kalemler": sorted(kalemler),
        "denetim": await db.scalar(select(func.count()).select_from(AuditLog)),
    }


class TestBirimKapsami:
    async def test_baska_birimin_teklifi_404_ve_veri_degismez(self, ortam, db):
        t = await teklif_ac(ortam["sef_g"], ortam["musteri"].id)
        await ortam["sef_g"].post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})
        once = await _anlik(db, t["id"])
        h = ortam["sef_h"]
        tid = t["id"]
        istekler = [
            ("GET", f"/api/teklifler/{tid}", None),
            ("GET", f"/api/teklifler/{tid}/pdf", None),
            ("GET", f"/api/teklifler/{tid}/gecmis", None),
            ("GET", f"/api/teklifler/{tid}/gonderimler", None),
            ("POST", f"/api/teklifler/{tid}/onaya-gonder", {}),
            ("POST", f"/api/teklifler/{tid}/karar", {"kabul": True}),
            ("POST", f"/api/teklifler/{tid}/revize", {"kalemler": [KALEM]}),
            ("POST", f"/api/teklifler/{tid}/iptal", {"neden": "başkasının teklifi"}),
            ("POST", f"/api/teklifler/{tid}/elle-gonderildi", {"kanal": "ELDEN", "not": "x y z"}),
            ("POST", f"/api/teklifler/{tid}/gonder", {}),
            (
                "PUT",
                f"/api/teklifler/{tid}",
                {"customer_id": ortam["musteri"].id, "version": 1, "kalemler": [KALEM]},
            ),
        ]
        for yontem, yol, govde in istekler:
            r = await h.request(yontem, yol, json=govde)
            assert r.status_code == 404, (yontem, yol, r.status_code, r.text)
        assert await _anlik(db, t["id"]) == once

    async def test_liste_ve_toplam_yalniz_kendi_birimi(self, ortam):
        for _ in range(3):
            await teklif_ac(ortam["sef_g"], ortam["musteri"].id)
        await teklif_ac(ortam["sef_h"], ortam["musteri"].id, birim="HABERLESME")
        await teklif_ac(ortam["satis1"], ortam["musteri"].id, birim=None)

        r = await ortam["sef_h"].get("/api/teklifler")
        assert r.headers["X-Toplam-Kayit"] == "1"
        assert {t["birim"] for t in r.json()} == {"HABERLESME"}
        r = await ortam["sef_g"].get("/api/teklifler?limit=2")
        assert r.headers["X-Toplam-Kayit"] == "3" and len(r.json()) == 2
        r2 = await ortam["sef_g"].get("/api/teklifler?limit=2&offset=2")
        assert len(r2.json()) == 1
        # Satış temsilcisi yalnız kendi (satış) teklifini görür; servis teklifi yok.
        r = await ortam["satis1"].get("/api/teklifler")
        assert r.headers["X-Toplam-Kayit"] == "1" and r.json()[0]["birim"] is None
        # TUMU kapsamlı satış müdürü: tur=SATIS / SERVIS süzgeci.
        satis = await ortam["smd"].get("/api/teklifler?tur=SATIS")
        servis = await ortam["smd"].get("/api/teklifler?tur=SERVIS")
        assert satis.headers["X-Toplam-Kayit"] == "1"
        assert servis.headers["X-Toplam-Kayit"] == "4"
        assert all(t["birim"] for t in servis.json())

    async def test_51_teklif_ulasilabilir(self, ortam, db):
        """Canlıda liste yalnız son 50 teklifi veriyordu (G7)."""
        from app.models import QuoteVersion as QV

        for i in range(51):
            q = Quote(quote_no=f"TKF2026-9{i:04d}", customer_id=ortam["musteri"].id, birim=None)
            db.add(q)
            await db.flush()
            v = QV(quote_id=q.id, version_no=1, public_token=f"jeton-{i:04d}-xxxxxxxxxxxx")
            db.add(v)
            await db.flush()
            q.current_version_id = v.id
        await db.commit()
        r = await ortam["smd"].get("/api/teklifler?limit=50&offset=50")
        assert r.headers["X-Toplam-Kayit"] == "51" and len(r.json()) == 1


class TestYazmaAyrimi:
    async def test_birimli_teklif_acma_kurallari(self, ortam):
        # Kendi birimi 201; başka birim 404; satış rolü birimli açamaz 403.
        await teklif_ac(ortam["sef_g"], ortam["musteri"].id)
        await teklif_ac(ortam["sef_g"], ortam["musteri"].id, birim="HABERLESME", beklenen=404)
        await teklif_ac(ortam["satis1"], ortam["musteri"].id, beklenen=403)
        # Servis rolü satış (birimsiz) teklifi açamaz (B4).
        await teklif_ac(ortam["sef_g"], ortam["musteri"].id, birim=None, beklenen=403)

    async def test_satis_mudurunun_servis_teklifine_yazmasi_404(self, ortam, db):
        t = await teklif_ac(ortam["sef_g"], ortam["musteri"].id)
        once = await _anlik(db, t["id"])
        assert (await ortam["smd"].get(f"/api/teklifler/{t['id']}")).status_code == 200
        r = await ortam["smd"].post(f"/api/teklifler/{t['id']}/onaya-gonder", json={})
        assert r.status_code == 404
        r = await ortam["smd"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        assert r.status_code == 404
        assert await _anlik(db, t["id"]) == once

    async def test_satis_temsilcisi_baskasinin_teklifini_degistiremez(self, ortam, db):
        """Canlı açık (G1): SATIS kimlik numarasıyla başkasının teklifini revize ediyordu."""
        t = await teklif_ac(ortam["satis1"], ortam["musteri"].id, birim=None)
        once = await _anlik(db, t["id"])
        s2 = ortam["satis2"]
        assert (
            await s2.post(f"/api/teklifler/{t['id']}/revize", json={"kalemler": [KALEM]})
        ).status_code == 404
        assert (await s2.post(f"/api/teklifler/{t['id']}/gonder", json={})).status_code == 404
        assert (
            await s2.post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        ).status_code == 404
        assert (await s2.get(f"/api/teklifler/{t['id']}/pdf")).status_code == 404
        assert await _anlik(db, t["id"]) == once

    async def test_servis_servisisi_baska_birim_404(self, ortam, db, servis_isi_ac):
        so = await servis_isi_ac(musteri=ortam["musteri"], birim="HABERLESME")
        r = await ortam["sef_g"].post(
            "/api/teklifler",
            json={
                "customer_id": ortam["musteri"].id,
                "birim": "GUVENLIK",
                "kalemler": [{**KALEM, "service_order_id": so.id}],
            },
        )
        assert r.status_code == 404
        assert await db.scalar(select(func.count()).select_from(Quote)) == 0


class TestDogrulama:
    @pytest.mark.parametrize(
        ("degisiklik", "beklenen"),
        [
            ({"kalemler": [{**KALEM, "qty": -1}]}, 422),
            ({"kalemler": [{**KALEM, "discount_pct": 150}]}, 422),
            ({"kalemler": [{**KALEM, "vat_rate": 0.37}]}, 400),
            ({"kalemler": [{**KALEM, "description": ""}]}, 400),
            ({"valid_until": "2025-12-31"}, 400),
            ({"currency": "EUR"}, 400),
            ({"kalemler": [dict(KALEM)] * 201}, 422),
        ],
    )
    async def test_birimli_hatalar_500_degil_ve_kayit_yok(self, ortam, db, degisiklik, beklenen):
        govde = {"customer_id": ortam["musteri"].id, "birim": "GUVENLIK", "kalemler": [KALEM]}
        govde.update(degisiklik)
        r = await ortam["sef_g"].post("/api/teklifler", json=govde)
        assert r.status_code == beklenen, r.text
        assert await db.scalar(select(func.count()).select_from(Quote)) == 0

    async def test_birimli_500_karakter_satis_300(self, ortam):
        uzun = "A" * 500
        t = await teklif_ac(
            ortam["sef_g"], ortam["musteri"].id, kalemler=[{**KALEM, "description": uzun}]
        )
        assert t["guncel"]["kalemler"][0]["description"] == uzun
        await teklif_ac(
            ortam["satis1"],
            ortam["musteri"].id,
            birim=None,
            kalemler=[{**KALEM, "description": "B" * 301}],
            beklenen=400,
        )

    async def test_iki_hane_yuvarlama(self, ortam):
        """3 × 33,333 TL: satır 33,33; iskontosuz teklifte 0,01 'iskonto' doğmaz (G3)."""
        kalem = {**KALEM, "unit_price": "33.333", "vat_rate": 0}
        t = await teklif_ac(ortam["sef_g"], ortam["musteri"].id, kalemler=[kalem] * 3)
        g = t["guncel"]
        assert {Decimal(k["line_total"]) for k in g["kalemler"]} == {Decimal("33.33")}
        assert Decimal(g["discount_total"]) == Decimal("0.00")
        toplam = sum(Decimal(k["line_total"]) for k in g["kalemler"])
        assert Decimal(g["subtotal"]) == toplam + Decimal(g["discount_total"])
        assert Decimal(g["grand_total"]) == Decimal(g["subtotal"]) - Decimal(
            g["discount_total"]
        ) + Decimal(g["vat_total"])


class TestSatistanAyrim:
    async def test_panel_ve_donusum_sayilari_degismez(self, ortam, db, kullanici_ac):
        await kullanici_ac("yonetim", "ADMIN")
        adm = await oturum("yonetim")
        try:
            # Bir satış teklifi gönderilmiş durumda.
            s = await teklif_ac(ortam["satis1"], ortam["musteri"].id, birim=None)
            q = await db.get(Quote, s["id"])
            q.status = "GONDERILDI"
            await db.commit()
            panel_once = (await adm.get("/api/raporlar/dashboard")).json()["bekleyen_teklif"]
            donusum_once = (await adm.get("/api/raporlar/teklif-donusumu")).json()

            for _ in range(5):
                t = await teklif_ac(ortam["sef_g"], ortam["musteri"].id)
                await onayli(ortam["sef_g"], ortam["mudur"], t["id"])
                await elle_gonder(ortam["sef_g"], t["id"])
            await ortam["sef_g"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})

            panel = (await adm.get("/api/raporlar/dashboard")).json()["bekleyen_teklif"]
            donusum = (await adm.get("/api/raporlar/teklif-donusumu")).json()
            assert panel == panel_once == 1
            assert donusum["toplam_teklif"] == donusum_once["toplam_teklif"]
            assert donusum["kazanilan"] == donusum_once["kazanilan"]
            servis = (await adm.get("/api/raporlar/teklif-donusumu?birim=GUVENLIK")).json()
            assert servis["toplam_teklif"] == 5 and servis["kazanilan"] == 1
        finally:
            await kapat(adm)

    async def test_servis_teklifi_siparise_donusmez(self, ortam, db, kullanici_ac):
        await kullanici_ac("yonetici", "ADMIN")
        adm = await oturum("yonetici")
        try:
            t = await teklif_ac(ortam["sef_g"], ortam["musteri"].id)
            await onayli(ortam["sef_g"], ortam["mudur"], t["id"])
            await elle_gonder(ortam["sef_g"], t["id"])
            await ortam["sef_g"].post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
            r = await adm.post(f"/api/siparisler/tekliften/{t['id']}")
            assert r.status_code == 409
            q = await db.get(Quote, t["id"])
            await db.refresh(q)
            assert q.status == "KABUL"
        finally:
            await kapat(adm)


class TestOzetVeExcel:
    async def test_kpi_sayisi_liste_toplamina_esit(self, ortam, client, db):
        from datetime import timedelta

        sef = ortam["sef_g"]
        a = await teklif_ac(sef, ortam["musteri"].id)
        await sef.post(f"/api/teklifler/{a['id']}/onaya-gonder", json={})
        b = await teklif_ac(sef, ortam["musteri"].id)
        await onayli(sef, ortam["mudur"], b["id"])
        await elle_gonder(sef, b["id"])
        # b'nin geçerliliği 2 gün sonra dolacak → süresi yaklaşan.
        q = await db.get(Quote, b["id"])
        v = await db.get(QuoteVersion, q.current_version_id)
        v.valid_until = client.clock.now().date() + timedelta(days=2)
        await db.commit()

        ozet = (await sef.get("/api/teklifler/ozet?tur=SERVIS")).json()
        sayilar = {k["kod"]: k["deger"] for k in ozet["kpi"]}
        assert sayilar["onay_bekleyen"] == 1
        assert sayilar["suresi_yaklasan"] == 1
        for kod, deger in sayilar.items():
            r = await sef.get(f"/api/teklifler?tur=SERVIS&kpi={kod}")
            assert r.headers["X-Toplam-Kayit"] == str(deger), kod

        # Uyarı da aynı sayıyı verir (birimli + kapsamlı).
        uyari = (await sef.get("/api/raporlar/uyarilar")).json()
        kod_adet = {u["kod"]: u["adet"] for u in uyari["uyarilar"]}
        assert kod_adet.get("teklif.suresi_yaklasan") == 1
        # Başka birimin şefi saymaz.
        h = (await ortam["sef_h"].get("/api/teklifler/ozet")).json()
        assert all(k["deger"] == 0 for k in h["kpi"])

    async def test_excel_satiri_liste_toplamina_esit(self, ortam):
        import io

        from openpyxl import load_workbook

        for _ in range(2):
            await teklif_ac(ortam["sef_g"], ortam["musteri"].id)
        await teklif_ac(ortam["sef_h"], ortam["musteri"].id, birim="HABERLESME")
        r = await ortam["sef_g"].get("/api/teklifler/disa-aktar.xlsx")
        assert r.status_code == 200, r.text
        sayfa = load_workbook(io.BytesIO(r.content)).active
        liste = await ortam["sef_g"].get("/api/teklifler")
        assert sayfa.max_row - 1 == int(liste.headers["X-Toplam-Kayit"]) == 2
        # Excel izni olmayan (SATIS) 403.
        assert (await ortam["satis1"].get("/api/teklifler/disa-aktar.xlsx")).status_code == 403
