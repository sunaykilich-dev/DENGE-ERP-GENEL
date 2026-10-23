"""Denetim kaydının DB seviyesinde değişmezliği ve gerçek IP (TS-211, E13-12).

Tetikleyicinin kendisi `tests/migration/test_ts_sema_d4.py`'de sınanır; burada
UYGULAMA yolları: kullanıcı düzenleme kaydı artık kişisel veri işaretli
(`is_personal_data`) — işaretsiz satır tetikleyici yüzünden bir daha
maskelenemezdi (E13-D03) —, personel/hesap KVKK imhası tetikleyiciyle
birlikte çalışır, müsaitlik notu ve servis e-posta kutusu kişi imhasına girer,
güvenilen vekil sunucunun bildirdiği istemci IP'si denetime yazılır.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, ServiceMailOutbox, ServiceUnavailability, User
from app.services import audit, kvkk

pytestmark = pytest.mark.integration


async def _giris(client, username: str):
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def test_uygulama_baglantisinda_update_ve_delete_reddedilir(db, seeded, kullanici_ac):
    kisi = await kullanici_ac("depocu", "DEPO")
    await audit.log(db, "users", "giris", entity_id=kisi.id, user_id=kisi.id)
    await db.commit()
    kimlik = await db.scalar(select(func.max(AuditLog.id)))
    with pytest.raises(DBAPIError, match="değiştirilemez"):
        await db.execute(text("UPDATE audit_logs SET action = 'x' WHERE id = :i"), {"i": kimlik})
    await db.rollback()
    with pytest.raises(DBAPIError, match="silinemez"):
        await db.execute(text("DELETE FROM audit_logs WHERE id = :i"), {"i": kimlik})
    await db.rollback()
    assert await db.scalar(select(AuditLog.action).where(AuditLog.id == kimlik)) == "giris"


async def test_kullanici_duzenleme_kaydi_kisisel_veri_ve_parola_yok(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.patch(
        f"/api/kullanicilar/{hedef.id}",
        json={
            "full_name": "Depo Sorumlusu",
            "email": "depo@ornek.com",
            "password": "yeni-parola-123",
        },
    )
    assert r.status_code == 200, r.text
    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "users", AuditLog.action == "guncelle")
    )
    assert kayit.is_personal_data is True
    assert kayit.new_value["password_hash"] == "***"
    assert "yeni-parola-123" not in str(kayit.new_value)


async def test_personel_anonimlestirme_tetikleyiciyle_calisir_ve_kancalari_kosar(
    client, kullanici_ac, db
):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("teknisyen", "SERVIS_TEKNISYEN")
    await _giris(client, "yonetici")
    # Ad/e-posta değişikliği (artık kişisel veri işaretli) — sonra maskelenebilmeli.
    await client.patch(f"/api/kullanicilar/{hedef.id}", json={"email": "teknisyen@ornek.com"})
    # Müsaitlik bloğu + notu ve denetim kaydı (planlama servisinin yazdığı biçim).
    an = datetime(2026, 1, 5, 9, tzinfo=UTC)
    blok = ServiceUnavailability(
        user_id=hedef.id,
        starts_at=an,
        ends_at=an + timedelta(hours=8),
        tur="IZIN",
        note="Doktor raporu",
    )
    db.add(blok)
    await db.flush()
    await audit.log(
        db,
        "service_unavailability",
        "olustur",
        entity_id=blok.id,
        new_value={"user_id": hedef.id, "tur": "IZIN", "not": "Doktor raporu"},
        is_personal_data=True,
    )
    db.add(
        ServiceMailOutbox(
            tur="ANLIK", user_id=hedef.id, alici="teknisyen@ornek.com", konu="SLA", govde="..."
        )
    )
    kisi = await db.get(User, hedef.id)
    await db.refresh(kisi)  # PATCH sürümü artırdı (iyimser kilit)
    kisi.is_active = False
    kisi.giris_acik = False
    kisi.ayrilis_tarihi = date(2026, 1, 10)
    kisi.ayrilis_nedeni = "ISTIFA"
    await db.commit()

    sonuc = await kvkk.personeli_anonimlestir(
        db, hedef.id, clock=client.clock, gerekce="KVKK başvuru 2026/1", aktor_id=None
    )
    await db.commit()
    assert sonuc["musaitlik_notu"] == 1
    assert sonuc["eposta_kutusu"] == 1
    assert sonuc["denetim_satiri"] >= 2

    await db.refresh(blok)
    assert blok.note is None and blok.is_deleted is False  # blok durur, not gider
    assert await db.scalar(select(func.count()).select_from(ServiceMailOutbox)) == 0
    degerler = str(
        [
            (k.old_value, k.new_value)
            for k in (await db.scalars(select(AuditLog))).all()
            if k.action != kvkk.PERSONEL_ANONIM_EYLEMI
        ]
    )
    assert "teknisyen@ornek.com" not in degerler
    assert "Doktor raporu" not in degerler


async def test_hesap_anonimlestirme_tetikleyiciyle_calisir(client, db, seeded):
    from app.models import Account

    hesap = Account(title="Ali Veli Ltd", is_musteri=True, phone="+905321112233")
    db.add(hesap)
    await db.flush()
    await audit.log(
        db,
        "accounts",
        "guncelle",
        entity_id=hesap.id,
        new_value={"phone": "+905321112233"},
        is_personal_data=True,
    )
    await db.commit()
    sonuc = await kvkk.hesabi_anonimlestir(
        db, hesap.id, clock=client.clock, gerekce="Silme talebi 12"
    )
    await db.commit()
    assert sonuc["denetim_satiri"] >= 1
    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "accounts", AuditLog.action == "guncelle")
    )
    await db.refresh(kayit)
    assert kayit.new_value == kvkk.DEGER_SILINDI


async def test_kvkk_imha_bayragi_transaction_icinde_kurulur(db, seeded):
    await kvkk.imha_bayragini_kur(db)
    assert await db.scalar(text("SELECT current_setting('denge.kvkk_imha', true)")) == "1"
    await db.commit()
    # SET LOCAL: transaction bitince düşer.
    assert await db.scalar(text("SELECT current_setting('denge.kvkk_imha', true)")) in (None, "")


def _vekilli_istemci(istemci_ip: str):
    """uvicorn'un `--proxy-headers --forwarded-allow-ips` katmanı (compose ile aynı)."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    from app.main import app

    sarili = ProxyHeadersMiddleware(app, trusted_hosts="172.18.0.1")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sarili, client=(istemci_ip, 51000)),
        base_url="http://test",
        headers={"X-Requested-With": "fetch", "X-Forwarded-For": "203.0.113.5"},
    )


@pytest.mark.parametrize(
    ("kaynak", "beklenen"), [("172.18.0.1", "203.0.113.5"), ("10.9.9.9", "10.9.9.9")]
)
async def test_guvenilen_vekilden_gelen_ip_denetime_yazilir(
    client, kullanici_ac, db, kaynak, beklenen
):
    """Güvenilen vekil (Docker ağ geçidi) başlığı aktarır; güvenilmeyen kaynaktan
    gelen `X-Forwarded-For` yok sayılır (sahte IP yazdırılamaz)."""
    kisi = await kullanici_ac("depocu", "DEPO")
    async with _vekilli_istemci(kaynak) as ist:
        r = await ist.post("/api/auth/login", json={"username": "depocu", "password": "parola1234"})
        assert r.status_code == 200, r.text
    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.action == "giris", AuditLog.entity_id == str(kisi.id))
    )
    assert str(kayit.ip) == beklenen
