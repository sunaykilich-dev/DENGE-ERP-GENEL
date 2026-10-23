"""Erişim gözden geçirme listesi (TS-214, E13-16).

KPI kutusu sayısı = aynı `kpi` ile açılan listenin `X-Toplam-Kayit` toplamı
(ikisi aynı koşul fonksiyonundan). "Gözden geçirildi" işareti yalnız denetim
kaydıdır; listede tarihle görünür. Excel `sistem.kullanici` + `rapor.disaaktar`.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, UserPermission

pytestmark = pytest.mark.integration


async def _giris(client, username: str):
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _kurulum(client, kullanici_ac, db):
    await kullanici_ac("patron", "ADMIN")  # hassas (ADMIN)
    await kullanici_ac("finans", "MUHASEBE_DESTEK")  # hassas (maliyet.gor)
    istisnali = await kullanici_ac("istisnali", "DEPO")  # sapma
    db.add(
        UserPermission(user_id=istisnali.id, permission_code="rma.yaz", allow=True, gerekce="test")
    )
    eski = await kullanici_ac("eski", "DEPO")  # uzun girişsiz
    eski.son_giris_at = client.clock.now() - timedelta(days=90)
    ayrilan = await kullanici_ac("ayrilan", "DEPO")  # ayrılmış, hesap açık
    ayrilan.ayrilis_tarihi = date(2025, 12, 1)
    ayrilan.ayrilis_nedeni = "ISTIFA"
    await kullanici_ac("kilitlenen", "DEPO")
    await db.commit()
    for _ in range(5):
        await client.post("/api/auth/login", json={"username": "kilitlenen", "password": "yanlis"})
    await _giris(client, "patron")


async def test_kpi_sayisi_liste_toplamina_esit(client, kullanici_ac, db):
    await _kurulum(client, kullanici_ac, db)
    ozet = await client.get("/api/erisim-gozden/ozet")
    assert ozet.status_code == 200, ozet.text
    kutular = {k["kod"]: k["adet"] for k in ozet.json()["kpiler"]}
    assert set(kutular) == {
        "hassas_izin",
        "sapma",
        "uzun_girissiz",
        "ayrilmis_hesap_acik",
        "kilitli",
    }
    for kod, adet in kutular.items():
        r = await client.get("/api/erisim-gozden", params={"kpi": kod, "limit": 200})
        assert r.status_code == 200
        assert int(r.headers["X-Toplam-Kayit"]) == adet, kod
        assert len(r.json()) == adet, kod

    adlar = {
        kod: {
            s["username"]
            for s in (await client.get("/api/erisim-gozden", params={"kpi": kod})).json()
        }
        for kod in kutular
    }
    assert {"patron", "finans"} <= adlar["hassas_izin"]
    assert "istisnali" in adlar["sapma"]
    assert "eski" in adlar["uzun_girissiz"]
    assert adlar["ayrilmis_hesap_acik"] == {"ayrilan"}
    assert adlar["kilitli"] == {"kilitlenen"}


async def test_gozden_gecirildi_isareti_denetimde_ve_listede(client, kullanici_ac, db):
    await _kurulum(client, kullanici_ac, db)
    finans = next(
        s for s in (await client.get("/api/erisim-gozden")).json() if s["username"] == "finans"
    )
    assert finans["son_gozden_gecirme_at"] is None
    r = await client.post(
        f"/api/erisim-gozden/{finans['id']}/gozden-gecirildi", json={"not": "Q1 kontrolü"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["son_gozden_gecirme_at"] is not None
    assert r.json()["son_gozden_geciren"] == "Patron"
    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "erisim.gozden_gecirildi"))
    assert kayit.entity_id == str(finans["id"])
    assert kayit.new_value["not"] == "Q1 kontrolü"
    assert "maliyet.gor" in kayit.new_value["hassas_izinler"]
    yeniden = next(
        s for s in (await client.get("/api/erisim-gozden")).json() if s["username"] == "finans"
    )
    assert yeniden["son_gozden_gecirme_at"] is not None


async def test_excel_ve_yetki(client, kullanici_ac, db):
    await _kurulum(client, kullanici_ac, db)
    r = await client.get("/api/erisim-gozden/excel", params={"kpi": "hassas_izin"})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "erisim.disaaktar"))

    await client.post("/api/auth/logout")
    await _giris(client, "finans")  # rapor.disaaktar var, sistem.kullanici yok
    assert (await client.get("/api/erisim-gozden/excel")).status_code == 403
    assert (await client.get("/api/erisim-gozden")).status_code == 403
    assert (await client.get("/api/erisim-gozden/ozet")).status_code == 403


async def test_bilinmeyen_kpi_400(client, kullanici_ac, db):
    await kullanici_ac("patron", "ADMIN")
    await _giris(client, "patron")
    assert (await client.get("/api/erisim-gozden", params={"kpi": "uydurma"})).status_code == 400


async def test_girissiz_esik_sorgu_parametresiyle_degisir(client, kullanici_ac, db):
    await _kurulum(client, kullanici_ac, db)
    r60 = (await client.get("/api/erisim-gozden/ozet")).json()
    assert r60["girissiz_gun"] == 60
    r120 = (await client.get("/api/erisim-gozden/ozet", params={"gun": 120})).json()
    adet = {k["kod"]: k["adet"] for k in r120["kpiler"]}["uzun_girissiz"]
    adet60 = {k["kod"]: k["adet"] for k in r60["kpiler"]}["uzun_girissiz"]
    assert adet < adet60  # 90 gündür girmeyen 120 eşiğinde sayılmaz
