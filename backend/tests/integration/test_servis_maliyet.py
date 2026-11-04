"""İş bazlı maliyet: gelir/diğer maliyet (TS-145), eksik veri ayrımı ve işçilik
tarifesi (TS-146), maliyet analizi (TS-149).

Kuralların özü "eksik veri 0 değildir": süre kaydı olmayan iş SURE_EKSIK,
tarifesi olmayan birim TARIFE_EKSIK, maliyeti bilinmeyen parça MALIYET_EKSIK;
toplamlara yalnız tam işler girer. Gelir NULL ≠ 0; ücretsiz garanti açıkça 0.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from servis_teklif_yardimci import kapat, musteri, oturum
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    ServiceLaborRate,
    ServiceOrderFinancial,
    ServiceTimeEntry,
    StockMovement,
    Warehouse,
)

pytestmark = pytest.mark.integration

EKIM = datetime(2025, 10, 15, 9, 0, tzinfo=UTC)
KASIM = datetime(2025, 11, 15, 9, 0, tzinfo=UTC)


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac, rol_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await kullanici_ac("smd", "SATIS_MUDURU")
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    await rol_ac(
        "T_MALIYET_BIRIM", ["maliyet.gor", "maliyet.yaz", "servis_rapor.gor"], "KENDI_BIRIMI"
    )
    await birimli_kullanici_ac("maliyetci_h", "T_MALIYET_BIRIM", ["HABERLESME"])
    teknisyen = await birimli_kullanici_ac("tekn", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    ist = {ad: await oturum(ad) for ad in ("yonetici", "smd", "sef_g", "maliyetci_h")}
    ist["musteri"] = await musteri(db)
    ist["teknisyen"] = teknisyen
    yield ist
    await kapat(*(ist[a] for a in ("yonetici", "smd", "sef_g", "maliyetci_h")))


async def _tarife(db, birim, bas, bit, saatlik):
    db.add(ServiceLaborRate(birim=birim, valid_from=bas, valid_to=bit, hourly_cost=saatlik))
    await db.commit()


async def _sure(db, so, kisi, bas, saat=2.0, *, acik=False):
    db.add(
        ServiceTimeEntry(
            service_order_id=so.id,
            user_id=kisi.id,
            faaliyet="SAHA",
            started_at=bas,
            ended_at=None if acik else bas + timedelta(hours=saat),
            kaynak="CANLI" if acik else "MANUEL",
            girildi_at=bas,
        )
    )
    await db.commit()


async def _kapali_is(servis_isi_ac, ortam, *, birim="GUVENLIK", tur="ARIZA", an=EKIM, **kw):
    return await servis_isi_ac(
        musteri=ortam["musteri"],
        birim=birim,
        tur=tur,
        durum="TAMAMLANDI",
        completed_at=an + timedelta(hours=8),
        **kw,
    )


async def _finans(ist, so_id):
    r = await ist.get(f"/api/teknik-servis/maliyet/isler/{so_id}")
    assert r.status_code == 200, r.text
    return r.json()


class TestIscilik:
    async def test_tarih_bazli_tarife_ekim_ve_kasim(self, ortam, db, servis_isi_ac):
        await _tarife(db, "GUVENLIK", date(2025, 10, 1), date(2025, 11, 1), Decimal("500"))
        so = await _kapali_is(servis_isi_ac, ortam, an=KASIM)
        await _sure(db, so, ortam["teknisyen"], EKIM)
        await _sure(db, so, ortam["teknisyen"], KASIM)
        once = await _finans(ortam["yonetici"], so.id)
        assert once["iscilik_durumu"] == "TARIFE_EKSIK" and once["iscilik"] is None

        await _tarife(db, "GUVENLIK", date(2025, 11, 1), None, Decimal("600"))
        f = await _finans(ortam["yonetici"], so.id)
        assert f["iscilik_durumu"] == "TAM"
        assert Decimal(f["iscilik"]) == Decimal("2200.00")  # 2×500 + 2×600
        assert f["sure_dk"] == 240

    async def test_sonraki_tarife_gecmis_isi_degistirmez(self, ortam, db, servis_isi_ac):
        await _tarife(db, "GUVENLIK", date(2025, 10, 1), None, Decimal("500"))
        so = await _kapali_is(servis_isi_ac, ortam)
        await _sure(db, so, ortam["teknisyen"], EKIM)
        once = (await _finans(ortam["yonetici"], so.id))["iscilik"]
        r = await ortam["yonetici"].post(
            "/api/teknik-servis/maliyet/tarifeler",
            json={"birim": "GUVENLIK", "valid_from": "2025-11-01", "hourly_cost": 600,
                  "gerekce": "Yeni yıl tarifesi"},
        )  # fmt: skip
        assert r.status_code == 201, r.text
        assert (await _finans(ortam["yonetici"], so.id))["iscilik"] == once == "1000.00"

    async def test_sure_kaydi_yok_ve_acik_bolum_sure_eksik(self, ortam, db, servis_isi_ac):
        await _tarife(db, "GUVENLIK", date(2025, 1, 1), None, Decimal("500"))
        bos = await _kapali_is(servis_isi_ac, ortam)
        f = await _finans(ortam["yonetici"], bos.id)
        assert f["iscilik"] is None and f["iscilik_durumu"] == "SURE_EKSIK"
        assert f["fark"] is None and f["durum"] == "SURE_EKSIK"

        acik = await _kapali_is(servis_isi_ac, ortam)
        await _sure(db, acik, ortam["teknisyen"], EKIM, acik=True)
        assert (await _finans(ortam["yonetici"], acik.id))["iscilik_durumu"] == "SURE_EKSIK"

    async def test_tarifesiz_birim_tarife_eksik(self, ortam, db, servis_isi_ac):
        so = await _kapali_is(servis_isi_ac, ortam, birim="HABERLESME")
        await _sure(db, so, ortam["teknisyen"], EKIM, 3)
        f = await _finans(ortam["yonetici"], so.id)
        assert f["iscilik"] is None and f["iscilik_durumu"] == "TARIFE_EKSIK"


class TestMalzeme:
    async def test_net_cikis_ve_maliyet_eksik(self, ortam, db, servis_isi_ac, urun_ac):
        await _tarife(db, "GUVENLIK", date(2025, 1, 1), None, Decimal("600"))
        depo = Warehouse(code="SRV-G", name="Servis G", birim="GUVENLIK", servis_deposu=True)
        db.add(depo)
        urun = await urun_ac("YP-1", "YOK")
        so = await _kapali_is(servis_isi_ac, ortam)
        await _sure(db, so, ortam["teknisyen"], EKIM, 1)
        ortak = {"product_id": urun.id, "warehouse_id": depo.id, "service_order_id": so.id}
        db.add_all(
            [
                StockMovement(**ortak, qty=-3, reason="CIKIS", hareket_turu="CIKIS_SERVIS",
                              unit_cost=Decimal("10.5")),
                StockMovement(**ortak, qty=1, reason="GIRIS", hareket_turu="IADE_SERVIS",
                              unit_cost=Decimal("10.5")),
            ]
        )  # fmt: skip
        await db.commit()
        f = await _finans(ortam["yonetici"], so.id)
        assert f["malzeme_durumu"] == "TAM" and Decimal(f["malzeme"]) == Decimal("21.00")

        db.add(
            StockMovement(**ortak, qty=-1, reason="CIKIS", hareket_turu="CIKIS_SERVIS",
                          unit_cost=None)
        )  # fmt: skip
        await db.commit()
        f = await _finans(ortam["yonetici"], so.id)
        assert f["malzeme"] is None and f["malzeme_durumu"] == "MALIYET_EKSIK"
        assert f["fark"] is None

    async def test_parcasiz_is_malzeme_sifir_tam(self, ortam, db, servis_isi_ac):
        so = await _kapali_is(servis_isi_ac, ortam)
        f = await _finans(ortam["yonetici"], so.id)
        assert f["malzeme_durumu"] == "YOK" and f["malzeme"] == "0.00"


class TestGelir:
    async def test_not_zorunlu_reddedilen_istek_iz_birakmaz(self, ortam, db, servis_isi_ac):
        so = await _kapali_is(servis_isi_ac, ortam)
        once = await db.scalar(select(func.count()).select_from(AuditLog))
        r = await ortam["yonetici"].put(
            f"/api/teknik-servis/maliyet/isler/{so.id}/gelir",
            json={"kaynak": "ELLE", "tutar": 1000},
        )
        assert r.status_code == 400
        assert await db.scalar(select(func.count()).select_from(ServiceOrderFinancial)) == 0
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == once

    async def test_gelir_yok_ucretsiz_garanti_ve_fark(self, ortam, db, servis_isi_ac):
        await _tarife(db, "GUVENLIK", date(2025, 1, 1), None, Decimal("600"))
        so = await _kapali_is(servis_isi_ac, ortam)
        await _sure(db, so, ortam["teknisyen"], EKIM, 1)
        y = ortam["yonetici"]
        r = await y.put(
            f"/api/teknik-servis/maliyet/isler/{so.id}/diger-maliyet",
            json={"tutar": 100, "not": "Otopark"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["gelir"] is None and r.json()["gelir_durumu"] == "KAYIT_YOK"
        assert r.json()["fark"] is None

        r = await y.put(
            f"/api/teknik-servis/maliyet/isler/{so.id}/gelir",
            json={"kaynak": "UCRETSIZ_GARANTI", "tutar": 999, "not": "Garanti kapsamı",
                  "version": r.json()["finans_version"]},
        )  # fmt: skip
        assert r.status_code == 200, r.text
        assert r.json()["gelir"] == "0.00" and r.json()["gelir_durumu"] == "UCRETSIZ_GARANTI"
        assert Decimal(r.json()["fark"]) == Decimal("-700.00")  # 0 − (0 + 600 + 100)

    async def test_gecmis_uc_kayit(self, ortam, servis_isi_ac):
        so = await _kapali_is(servis_isi_ac, ortam)
        y = ortam["yonetici"]
        for tutar in (100, 200, 300):
            r = await y.put(
                f"/api/teknik-servis/maliyet/isler/{so.id}/gelir",
                json={"kaynak": "ELLE", "tutar": tutar, "not": f"Düzeltme {tutar}"},
            )
            assert r.status_code == 200, r.text
        gecmis = (await y.get(f"/api/teknik-servis/maliyet/isler/{so.id}/gecmis")).json()
        assert len(gecmis) == 3
        assert gecmis[-1]["eski"]["gelir"] == "200.00" and gecmis[-1]["yeni"]["gelir"] == "300.00"
        assert all(g["kullanici"] for g in gecmis)
        assert gecmis[-1]["yeni"]["gelir_notu"] == "Düzeltme 300"

    async def test_fatura_sonrasi_409_ve_deger_ayni(self, ortam, client, db, servis_isi_ac):
        so = await _kapali_is(servis_isi_ac, ortam)
        db.add(
            ServiceOrderFinancial(
                service_order_id=so.id,
                gelir=Decimal("500"),
                gelir_kaynagi="ELLE",
                gelir_notu="ilk",
                fatura_iletildi_at=client.clock.now(),
            )
        )
        await db.commit()
        r = await ortam["yonetici"].put(
            f"/api/teknik-servis/maliyet/isler/{so.id}/gelir",
            json={"kaynak": "ELLE", "tutar": 900, "not": "değişiklik"},
        )
        assert r.status_code == 409 and "faturaya iletildi" in r.json()["detail"]
        r = await ortam["yonetici"].put(
            f"/api/teknik-servis/maliyet/isler/{so.id}/diger-maliyet",
            json={"tutar": 5, "not": "x"},
        )
        assert r.status_code == 409
        fin = await db.scalar(
            select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so.id)
        )
        await db.refresh(fin)
        assert fin.gelir == Decimal("500.00") and fin.diger_maliyet is None


class TestYetkiVeKapsam:
    async def test_rbac(self, ortam, servis_isi_ac):
        so = await _kapali_is(servis_isi_ac, ortam)
        yol = f"/api/teknik-servis/maliyet/isler/{so.id}"
        # Servis şefinde maliyet izni yok (KD-11).
        assert (await ortam["sef_g"].get(yol)).status_code == 403
        assert (
            await ortam["sef_g"].get("/api/teknik-servis/maliyet/analiz?donem=2025-10")
        ).status_code == 403
        # Satış müdürü görür ama yazamaz (maliyet.yaz yalnız ADMIN + istisna).
        assert (await ortam["smd"].get(yol)).status_code == 200
        r = await ortam["smd"].put(f"{yol}/gelir", json={"kaynak": "ELLE", "tutar": 1, "not": "x"})
        assert r.status_code == 403
        # Analiz `servis_rapor.gor` de ister (menü ile aynı çift).
        assert (
            await ortam["smd"].get("/api/teknik-servis/maliyet/analiz?donem=2025-10")
        ).status_code == 403

    async def test_kapsam_disi_is_404_ve_yazma_yok(self, ortam, db, servis_isi_ac):
        so = await _kapali_is(servis_isi_ac, ortam, birim="GUVENLIK")
        h = ortam["maliyetci_h"]
        yol = f"/api/teknik-servis/maliyet/isler/{so.id}"
        assert (await h.get(yol)).status_code == 404
        assert (await h.get(f"{yol}/gecmis")).status_code == 404
        r = await h.put(f"{yol}/gelir", json={"kaynak": "ELLE", "tutar": 1, "not": "x"})
        assert r.status_code == 404
        r = await h.put(f"{yol}/diger-maliyet", json={"tutar": 1, "not": "x"})
        assert r.status_code == 404
        assert await db.scalar(select(func.count()).select_from(ServiceOrderFinancial)) == 0


class TestTarife:
    async def test_tarife_kurallari(self, ortam, db):
        y = ortam["yonetici"]
        yol = "/api/teknik-servis/maliyet/tarifeler"
        r = await y.post(
            yol, json={"birim": "GUVENLIK", "valid_from": "2026-02-01", "hourly_cost": 0}
        )
        assert r.status_code == 422
        r = await y.post(
            yol, json={"birim": "GUVENLIK", "valid_from": "2026-02-01", "hourly_cost": 500}
        )
        assert r.status_code == 201, r.text
        ilk = r.json()
        # Açık tarifeden önce başlayan yeni tarife 409.
        r = await y.post(
            yol, json={"birim": "GUVENLIK", "valid_from": "2026-01-15", "hourly_cost": 450}
        )
        assert r.status_code == 409
        r = await y.post(
            yol, json={"birim": "GUVENLIK", "valid_from": "2026-03-01", "hourly_cost": 550}
        )
        assert r.status_code == 201
        ikinci = r.json()
        liste = (await y.get(f"{yol}?birim=GUVENLIK")).json()
        assert next(t for t in liste if t["id"] == ilk["id"])["valid_to"] == "2026-03-01"

        # Henüz başlamamış ikinci tarife kapatılır; öncül yeniden açılır.
        r = await y.post(
            f"{yol}/kapat",
            json={
                "tarife_id": ikinci["id"],
                "version": ikinci["version"],
                "gerekce": "Hatalı giriş",
            },
        )
        assert r.status_code == 200, r.text
        liste = {t["id"]: t for t in (await y.get(f"{yol}?birim=GUVENLIK")).json()}
        assert liste[ikinci["id"]]["kapatildi"] is True
        assert liste[ilk["id"]]["valid_to"] is None

    async def test_gecmis_tarih_yetki_ve_gerekce(self, ortam):
        h = ortam["maliyetci_h"]
        yol = "/api/teknik-servis/maliyet/tarifeler"
        govde = {"birim": "HABERLESME", "valid_from": "2025-12-01", "hourly_cost": 400}
        # sistem.ayar yok → 400.
        assert (await h.post(yol, json={**govde, "gerekce": "geriye"})).status_code == 400
        # ADMIN gerekçesiz 400, gerekçeyle 201.
        assert (await ortam["yonetici"].post(yol, json=govde)).status_code == 400
        r = await ortam["yonetici"].post(yol, json={**govde, "gerekce": "Eski dönem düzeltmesi"})
        assert r.status_code == 201
        # Birim kapsamı: HABERLESME kullanıcısı GUVENLIK tarifesi açamaz (404).
        r = await h.post(
            yol, json={"birim": "GUVENLIK", "valid_from": "2026-05-01", "hourly_cost": 1}
        )
        assert r.status_code == 404
        assert {t["birim"] for t in (await h.get(yol)).json()} == {"HABERLESME"}

    async def test_tarife_eksik_uyarisi_birim_kapsamli(self, ortam, db):
        await _tarife(db, "GUVENLIK", date(2025, 1, 1), None, Decimal("500"))
        uyari = (await ortam["maliyetci_h"].get("/api/raporlar/uyarilar")).json()["uyarilar"]
        eksik = next(u for u in uyari if u["kod"] == "maliyet.tarife_eksik")
        assert eksik["adet"] == 1 and eksik["aciklama"] == "HABERLESME"
        uyari = (await ortam["yonetici"].get("/api/raporlar/uyarilar")).json()["uyarilar"]
        # 6 birim (BARIYER, KARARLAR 2026-11-04 §1) − GUVENLIK = 5 (önceden 5 birim − 1 = 4).
        assert next(u for u in uyari if u["kod"] == "maliyet.tarife_eksik")["adet"] == 5


class TestAnaliz:
    async def test_suzgec_ozet_ve_kapsam(self, ortam, db, servis_isi_ac):
        await _tarife(db, "GUVENLIK", date(2025, 1, 1), None, Decimal("600"))
        await _tarife(db, "HABERLESME", date(2025, 1, 1), None, Decimal("300"))
        g1 = await _kapali_is(servis_isi_ac, ortam)
        g2 = await _kapali_is(servis_isi_ac, ortam)
        await _kapali_is(servis_isi_ac, ortam, tur="DESTEK")
        h1 = await _kapali_is(servis_isi_ac, ortam, birim="HABERLESME")
        await _kapali_is(servis_isi_ac, ortam, an=KASIM)  # dönem dışı
        for gun, so in enumerate((g1, g2, h1)):
            await _sure(db, so, ortam["teknisyen"], EKIM + timedelta(days=gun), 1)
        y = ortam["yonetici"]
        for so, gelir in ((g1, 1000), (h1, 800)):
            r = await y.put(
                f"/api/teknik-servis/maliyet/isler/{so.id}/gelir",
                json={"kaynak": "ELLE", "tutar": gelir, "not": "fatura"},
            )
            assert r.status_code == 200

        r = await y.get("/api/teknik-servis/maliyet/analiz?donem=2025-10&birim=GUVENLIK&tur=ARIZA")
        assert r.status_code == 200, r.text
        v = r.json()
        assert {s["so_id"] for s in v["satirlar"]} == {g1.id, g2.id}
        tam = [s for s in v["satirlar"] if s["fark"] is not None]
        assert [s["so_id"] for s in tam] == [g1.id]
        ozet = v["ozet"]
        assert len(ozet) == 1 and ozet[0]["adet"] == 2 and ozet[0]["tam_adet"] == 1
        assert ozet[0]["gelir_yok"] == 1
        assert Decimal(ozet[0]["fark"]) == sum(Decimal(s["fark"]) for s in tam)
        assert Decimal(v["genel"]["fark"]) == Decimal("400.00")

        tum = (await y.get("/api/teknik-servis/maliyet/analiz?donem=2025-10")).json()
        assert len(tum["satirlar"]) == 4
        assert tum["genel"]["sure_eksik"] == 1  # DESTEK işinde süre yok
        eksik = (
            await y.get("/api/teknik-servis/maliyet/analiz?donem=2025-10&durum=SURE_EKSIK")
        ).json()
        assert len(eksik["satirlar"]) == 1

        # Kişisel istisnayla maliyet gören HABERLESME kullanıcısı GUVENLIK görmez.
        h = (
            await ortam["maliyetci_h"].get("/api/teknik-servis/maliyet/analiz?donem=2025-10")
        ).json()
        assert {s["birim"] for s in h["satirlar"]} == {"HABERLESME"}

    async def test_donem_sinirlari(self, ortam):
        y = ortam["yonetici"]
        onek = "/api/teknik-servis/maliyet/analiz"
        assert (await y.get(onek)).status_code == 400
        assert (await y.get(f"{onek}?baslangic=2025-01-01&bitis=2026-01-31")).status_code == 400
        assert (await y.get(f"{onek}?baslangic=2025-01-01&bitis=2025-12-31")).status_code == 200
        assert (await y.get(f"{onek}?donem=2025-13")).status_code == 400
