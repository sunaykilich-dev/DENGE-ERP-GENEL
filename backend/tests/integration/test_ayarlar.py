"""Parametre yönetimi: hassas alan maskeleme ve vergi oranlarının kaynağı."""

import pytest
from sqlalchemy import select

from app.models import Setting
from app.services import settings as settings_service

pytestmark = pytest.mark.integration


async def _admin_girisi(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await client.post("/api/auth/login", json={"username": "yonetici", "password": "parola1234"})


async def test_vergi_oranlari_koda_gomulu_degil(client, kullanici_ac):
    """Brief §4.7 madde 6: tüm oranlar ayarlardan değiştirilebilir olmalı."""
    await _admin_girisi(client, kullanici_ac)
    r = await client.get("/api/ayarlar")
    assert r.status_code == 200
    ayarlar = r.json()
    for anahtar in (
        "kdv_oran_varsayilan",
        "stopaj_smm_oran",
        "damga_vergisi_oran",
        "stopaj_gider_pusulasi_oran",
        "iskonto_onay_esigi_yuzde",
    ):
        assert anahtar in ayarlar, f"{anahtar} ayarlarda yok"


async def test_hassas_alan_maskelenir_ve_maske_geri_yazilmaz(client, kullanici_ac, db):
    await _admin_girisi(client, kullanici_ac)

    r = await client.patch("/api/ayarlar", json={"values": {"platform_api_key": "gizli-anahtar"}})
    assert r.status_code == 200
    assert r.json()["platform_api_key"] == "********"  # arayüze sır sızmaz

    # DB'de düz metin durmamalı
    row = await db.scalar(select(Setting).where(Setting.key == "platform_api_key"))
    assert row is not None
    assert row.value != "gizli-anahtar"
    assert str(row.value).startswith("enc:v1:")

    # Gerçek değer dahili okumada çözülüyor
    assert await settings_service.get(db, "platform_api_key") == "gizli-anahtar"

    # Maskeyi geri gönderen istemci sırrı EZMEMELİ
    await client.patch(
        "/api/ayarlar", json={"values": {"platform_api_key": "********", "smtp_port": 25}}
    )
    db.expire_all()
    assert await settings_service.get(db, "platform_api_key") == "gizli-anahtar"
    assert await settings_service.get(db, "smtp_port") == 25


async def test_bilinmeyen_ayar_reddedilir(client, kullanici_ac):
    await _admin_girisi(client, kullanici_ac)
    r = await client.patch("/api/ayarlar", json={"values": {"uydurma_ayar": 1}})
    assert r.status_code == 400


async def test_ayar_degisikligi_denetime_yazilir_ama_sir_yazilmaz(client, kullanici_ac, db):
    from app.models import AuditLog

    await _admin_girisi(client, kullanici_ac)
    await client.patch(
        "/api/ayarlar",
        json={"values": {"iskonto_onay_esigi_yuzde": 25.0, "platform_api_key": "cok-gizli"}},
    )
    kayit = await db.scalar(select(AuditLog).where(AuditLog.entity == "settings"))
    assert kayit is not None
    assert kayit.new_value["iskonto_onay_esigi_yuzde"] == 25.0
    assert "cok-gizli" not in str(kayit.new_value)


async def test_ayar_izni_olmayan_goremez(client, kullanici_ac):
    await kullanici_ac("depocu", "DEPO")
    await client.post("/api/auth/login", json={"username": "depocu", "password": "parola1234"})
    assert (await client.get("/api/ayarlar")).status_code == 403
