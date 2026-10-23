"""Süreli vekâlet (TS-213, E13-15, E07-D03).

Gerçek hikâye: izne çıkan servis müdürünün planlama işini birine birkaç
günlüğüne bırakmanın tek yolu kalıcı istisnaydı; geri almak unutuluyor ve
"rolünden farklı" rozeti aylarca kalıyordu. Vekâlet aynı satırın süreli
hâlidir: süre dolunca istek anındaki kontrol izni düşürür (worker'a bağlı
değil), verilemeyecek izinler (maliyet, hak ediş ödeme/onay, sistem) 403'tür.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Session, UserPermission

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def _bitis(client, **kw) -> str:
    return (client.clock.now() + timedelta(**kw)).isoformat()


async def _hazirla(client, kullanici_ac, birimli_kullanici_ac):
    mudur = await kullanici_ac("mudur", "SERVIS_YONETICI")
    sef = await birimli_kullanici_ac("sef", "SERVIS_SEF", ["GUVENLIK"])
    await _giris(client, "mudur")
    return mudur, sef


async def _ver(client, kisi_id: int, izinler, **sure):
    return await client.post(
        f"/api/vekalet/{kisi_id}",
        json={
            "izinler": izinler,
            "bitis_at": _bitis(client, **(sure or {"days": 3})),
            "gerekce": "Yıllık izin vekâleti",
        },
    )


async def test_vekalet_verilir_alicinin_oturumu_duser_ve_izin_gelir(
    client, kullanici_ac, birimli_kullanici_ac, db
):
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    from app.services import auth as auth_service

    await auth_service.create_session(db, sef, client.clock)
    await db.commit()
    assert (
        await db.scalar(select(func.count()).select_from(Session).where(Session.user_id == sef.id))
        == 1
    )

    r = await _ver(client, sef.id, ["servis.tanim"])
    assert r.status_code == 201, r.text
    satir = r.json()[0]
    assert satir["izin"] == "servis.tanim" and satir["durum"] == "YURURLUKTE"
    assert satir["veren_adi"] == "Mudur"

    # Alıcının açık oturumu düştü (yetki değişti).
    assert (
        await db.scalar(select(func.count()).select_from(Session).where(Session.user_id == sef.id))
        == 0
    )

    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "vekalet.ver"))
    assert kayit.new_value["izinler"] == ["servis.tanim"]
    assert kayit.entity_id == str(sef.id)

    await client.post("/api/auth/logout")
    await _giris(client, "sef")
    me = (await client.get("/api/auth/me")).json()
    assert "servis.tanim" in me["permissions"]


async def test_vekalete_kapali_izin_403_ve_ret_denetimde(
    client, kullanici_ac, birimli_kullanici_ac, db
):
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    # maliyet.gor ve teklif.onayla vekâlete kapalı (müdürde teklif.onayla VAR).
    for izin in ("teklif.onayla", "maliyet.gor", "vekalet.ver"):
        r = await _ver(client, sef.id, [izin])
        assert r.status_code == 403, (izin, r.text)
    ret = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "yetki.ret")
    )
    assert ret == 3
    assert await db.scalar(select(func.count()).select_from(UserPermission)) == 0


async def test_verenin_sahip_olmadigi_izin_403(client, kullanici_ac, birimli_kullanici_ac):
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    r = await _ver(client, sef.id, ["hakedis.gor"])  # müdürde yok
    assert r.status_code == 403
    assert "kalıcı olarak bulunmayan" in r.json()["detail"]


async def test_vekaletle_gelen_izin_zincirleme_devredilemez(
    client, kullanici_ac, birimli_kullanici_ac, db
):
    """Veren yalnız KALICI izinlerini verir: vekâletle gelen izin devredilemez."""
    mudur, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    yonetici2 = await kullanici_ac("mudur2", "SERVIS_YONETICI")
    db.add(
        UserPermission(
            user_id=yonetici2.id,
            permission_code="rapor.gor",
            allow=True,
            gerekce="test vekâleti",
            baslangic_at=client.clock.now() - timedelta(hours=1),
            bitis_at=client.clock.now() + timedelta(days=1),
            veren_id=None,
        )
    )
    await db.commit()
    await client.post("/api/auth/logout")
    await _giris(client, "mudur2")
    assert "rapor.gor" in (await client.get("/api/auth/me")).json()["permissions"]
    r = await _ver(client, sef.id, ["rapor.gor"])
    assert r.status_code == 403


async def test_otuz_bir_gun_400_ve_kendine_400(client, kullanici_ac, birimli_kullanici_ac):
    mudur, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    r = await _ver(client, sef.id, ["servis.tanim"], days=31)
    assert r.status_code == 400
    assert "30 gün" in r.json()["detail"]
    assert (await _ver(client, sef.id, ["servis.tanim"], days=30)).status_code == 201
    r = await _ver(client, mudur.id, ["servis.tanim"])
    assert r.status_code == 400


async def test_rolunde_olan_izin_ve_cift_vekalet_409(client, kullanici_ac, birimli_kullanici_ac):
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.planla"])).status_code == 409  # rolünde var
    assert (await _ver(client, sef.id, ["servis.tanim"])).status_code == 201
    assert (await _ver(client, sef.id, ["servis.tanim"])).status_code == 409  # süren vekâlet


async def test_sure_dolunca_ayni_oturumda_403(client, kullanici_ac, birimli_kullanici_ac):
    """FakeClock bitişi geçince sunucu yeniden başlamadan izin düşer."""
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.tanim"], hours=2)).status_code == 201
    await client.post("/api/auth/logout")
    await _giris(client, "sef")
    me = (await client.get("/api/auth/me")).json()
    assert "servis.tanim" in me["permissions"]

    client.clock.advance(hours=2, minutes=1)
    me = (await client.get("/api/auth/me")).json()
    assert "servis.tanim" not in me["permissions"]


async def test_baslamamis_vekalet_sayilmaz(client, kullanici_ac, birimli_kullanici_ac):
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    r = await client.post(
        f"/api/vekalet/{sef.id}",
        json={
            "izinler": ["servis.tanim"],
            "baslangic_at": _bitis(client, days=1),
            "bitis_at": _bitis(client, days=2),
            "gerekce": "Haftaya izin",
        },
    )
    assert r.status_code == 201
    assert r.json()[0]["durum"] == "BASLAMADI"
    await client.post("/api/auth/logout")
    await _giris(client, "sef")
    assert "servis.tanim" not in (await client.get("/api/auth/me")).json()["permissions"]


async def test_iptal_yalniz_veren_ya_da_admin_ve_denetimde(
    client, kullanici_ac, birimli_kullanici_ac, db
):
    mudur, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.tanim"])).status_code == 201
    await kullanici_ac("mudur2", "SERVIS_YONETICI")
    await client.post("/api/auth/logout")
    await _giris(client, "mudur2")
    r = await client.post(f"/api/vekalet/{sef.id}/iptal", json={"izin": "servis.tanim"})
    assert r.status_code == 403

    await client.post("/api/auth/logout")
    await _giris(client, "mudur")
    client.clock.advance(minutes=5)
    r = await client.post(f"/api/vekalet/{sef.id}/iptal", json={"izin": "servis.tanim"})
    assert r.status_code == 200, r.text
    assert r.json()[0]["durum"] == "SONA_ERDI"
    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "vekalet.iptal"))
    assert kayit is not None and kayit.new_value["izin"] == "servis.tanim"
    # İkinci iptal 409.
    r = await client.post(f"/api/vekalet/{sef.id}/iptal", json={"izin": "servis.tanim"})
    assert r.status_code == 409


async def test_suresi_dolmus_vekalet_yeniden_verilebilir(
    client, kullanici_ac, birimli_kullanici_ac
):
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.tanim"], hours=1)).status_code == 201
    client.clock.advance(hours=2)
    await client.post("/api/auth/logout")
    await _giris(client, "mudur")
    assert (await _ver(client, sef.id, ["servis.tanim"], hours=3)).status_code == 201


async def test_kalici_istisna_ucu_vekaleti_silmez(client, kullanici_ac, birimli_kullanici_ac, db):
    """`PUT /kullanicilar/{id}/izinler` toptan yazıyordu; vekâlet satırını da siliyordu."""
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.tanim"])).status_code == 201
    await kullanici_ac("patron", "ADMIN")
    await client.post("/api/auth/logout")
    await _giris(client, "patron")
    r = await client.put(
        f"/api/kullanicilar/{sef.id}/izinler",
        json=[{"permission_code": "rma.yaz", "allow": True, "gerekce": "RMA desteği"}],
    )
    assert r.status_code == 200
    kodlar = {
        (u.permission_code, u.bitis_at is not None)
        for u in (await db.scalars(select(UserPermission))).all()
    }
    assert kodlar == {("rma.yaz", False), ("servis.tanim", True)}
    assert len((await client.get(f"/api/kullanicilar/{sef.id}/izinler")).json()) == 1
    satir = next(
        s for s in (await client.get("/api/kullanicilar")).json() if s["username"] == "sef"
    )
    assert satir["sapma_sayisi"] == 1 and satir["vekalet_sayisi"] == 1


async def test_kapsam_disi_personele_404(client, kullanici_ac, birimli_kullanici_ac, rol_ac, db):
    """Birim kapsamlı vekâlet veren başka birimin kişisine 404 alır, hiçbir şey yazılmaz."""
    await rol_ac("T_VEKIL_SEF", ["vekalet.ver", "servis.tanim"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("birim_sef", "T_VEKIL_SEF", ["GUVENLIK"])
    yabanci = await birimli_kullanici_ac("yabanci", "SERVIS_SEF", ["HABERLESME"])
    await _giris(client, "birim_sef")
    once = await db.scalar(select(func.count()).select_from(AuditLog))
    r = await _ver(client, yabanci.id, ["servis.tanim"])
    assert r.status_code == 404
    assert (await client.get(f"/api/vekalet/{yabanci.id}")).status_code == 404
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == once
    assert await db.scalar(select(func.count()).select_from(UserPermission)) == 0


async def test_yetkisiz_rol_403(client, kullanici_ac, birimli_kullanici_ac):
    sef = await birimli_kullanici_ac("sef", "SERVIS_SEF", ["GUVENLIK"])
    await _giris(client, "sef")
    assert (await client.get("/api/vekalet")).status_code == 403
    assert (await _ver(client, sef.id, ["servis.gor"])).status_code == 403


async def test_liste_ve_verilebilir(client, kullanici_ac, birimli_kullanici_ac):
    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.tanim"])).status_code == 201
    r = await client.get("/api/vekalet", params={"durum": "YURURLUKTE"})
    assert r.status_code == 200
    assert r.headers["X-Toplam-Kayit"] == "1"
    verilebilir = {i["kod"] for i in (await client.get("/api/vekalet/verilebilir")).json()}
    assert "servis.tanim" in verilebilir
    assert not verilebilir & {"teklif.onayla", "vekalet.ver", "maliyet.gor"}


async def test_isten_cikista_vekaletler_biter(client, kullanici_ac, birimli_kullanici_ac, db):
    """İşten çıkış erişimi: ayrılan kişiye verilen ve onun verdiği vekâlet biter."""
    mudur, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.tanim"])).status_code == 201
    await kullanici_ac("patron", "ADMIN")
    await client.post("/api/auth/logout")
    await _giris(client, "patron")
    client.clock.advance(minutes=10)
    await db.refresh(mudur)
    r = await client.post(
        f"/api/personel/{mudur.id}/cikis",
        json={
            "ayrilis_tarihi": client.clock.now().date().isoformat(),
            "ayrilis_nedeni": "ISTIFA",
            "version": mudur.version,
        },
    )
    assert r.status_code == 200, r.text
    satir = await db.scalar(select(UserPermission).where(UserPermission.user_id == sef.id))
    await db.refresh(satir)
    assert satir.bitis_at == client.clock.now()
    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "vekalet.iptal"))
    assert kayit.new_value["neden"] == "isten_cikis"


async def test_worker_sona_ermeyi_bir_kez_yazar(client, kullanici_ac, birimli_kullanici_ac, db):
    from app import worker

    _, sef = await _hazirla(client, kullanici_ac, birimli_kullanici_ac)
    assert (await _ver(client, sef.id, ["servis.tanim"], hours=1)).status_code == 201
    client.clock.advance(hours=2)
    ozet = await worker.vekalet_sona_erme(db, client.clock)
    await db.commit()
    assert "yeni denetim kaydı=1" in ozet
    ozet = await worker.vekalet_sona_erme(db, client.clock)
    await db.commit()
    assert "yeni denetim kaydı=0" in ozet
    assert (
        await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "vekalet.sona_erdi")
        )
        == 1
    )
    assert {g.ad for g in worker.GOREVLER} >= {"vekalet-sona-erme"}


def test_iso_karsilastirma_utc():
    from app.services.yetki import zaman_metni

    an = datetime(2026, 1, 1, 12, tzinfo=UTC)
    from zoneinfo import ZoneInfo

    assert zaman_metni(an) == zaman_metni(an.astimezone(ZoneInfo("Europe/Istanbul")))
