"""Bekleme akışı ve bekleme nedeni kataloğu (TS-023; E01-05, E10-03).

Gerçek hikâye: eski sistemde "beklemede" bir durum metniydi; neden, süre ve
işin nereden beklemeye alındığı kayboluyordu. Burada tek aktif bekleme,
katalogdan neden, süre (dk) ve önceki duruma dönüş vardır.
"""

import pytest
from servis_yardimci import giris, olay_sayisi, tazele
from sqlalchemy import select

from app.models import ServiceHold, ServiceHoldReason

pytestmark = pytest.mark.integration


async def test_beklet_bitir_onceki_duruma_doner(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op_b1", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac(durum="ISLEMDE")
    await giris(client, "op_b1")
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/bekleme",
        json={"neden": "MUSTERI_ONAYI", "aciklama": "Onay bekleniyor"},
    )
    assert r.status_code == 200, r.text
    detay = r.json()
    assert detay["status"] == "BEKLEMEDE"
    assert detay["bekleme"]["neden"] == "MUSTERI_ONAYI"
    assert detay["bekleme"]["sla_durdurur"] is True  # katalogdan donduruldu
    # İkinci bekleme 409.
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme", json={"neden": "MALZEME"})
    assert r.status_code == 409

    client.clock.advance(minutes=90)
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme/bitir", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ISLEMDE"
    assert r.json()["bekleme"] is None
    hold = await db.scalar(select(ServiceHold).where(ServiceHold.service_order_id == so.id))
    assert hold.sure_dk == 90 and hold.otomatik_kapandi is False
    assert await olay_sayisi(db, so.id, "BEKLEME") == 1
    assert await olay_sayisi(db, so.id, "BEKLEME_BITTI") == 1

    r = await client.get(f"/api/teknik-servis/isler/{so.id}/beklemeler")
    assert r.status_code == 200
    assert r.json()["toplam_dk"] == 90
    assert r.json()["beklemeler"][0]["neden_adi"] == "Müşteri onayı bekleniyor"
    # Beklemede olmayan işte bitir 409.
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme/bitir", json={})
    assert r.status_code == 409


async def test_neden_dogrulamalari(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("op_b2", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac()
    await giris(client, "op_b2")
    for govde in (
        {"neden": "UYDURMA"},
        {"neden": "BAKIM_UYGUNSUZLUK"},  # sadece sistem
        {"neden": "DIGER"},  # açıklama zorunlu
        {"neden": "MALZEME", "beklenen_bitis_at": "2025-12-01T09:00:00+03:00"},  # geçmiş
    ):
        r = await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme", json=govde)
        assert r.status_code == 400, govde
    so = await tazele(db, so)
    assert so.status == "MUSTERI_TALEBI"
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/bekleme",
        json={"neden": "DIGER", "aciklama": "Bina kapalı"},
    )
    assert r.status_code == 200


async def test_kapali_is_bekletilemez(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("op_b3", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac(durum="TAMAMLANDI")
    await giris(client, "op_b3")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme", json={"neden": "MALZEME"})
    assert r.status_code == 409
    assert (await db.scalars(select(ServiceHold))).all() == []


async def test_donulemeyen_onceki_durumda_planlamaya_doner(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op_b4", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac(durum="YOLA_CIKILDI")
    await giris(client, "op_b4")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme", json={"neden": "PERSONEL"})
    assert r.status_code == 200
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/bekleme/bitir", json={"not": "Ekip geldi"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "PLANLAMADA"
    r = await client.get(
        f"/api/teknik-servis/isler/{so.id}/gecmis", params={"tur": "BEKLEME_BITTI"}
    )
    assert "dönülemediği" in r.json()[0]["ozet"]


async def test_bekleme_katalogu_operasyon_yonet(
    client, db, kullanici_ac, birimli_kullanici_ac
) -> None:
    await birimli_kullanici_ac("sef_b5", "SERVIS_SEF", ["GUVENLIK"])
    await kullanici_ac("mud_b5", "SERVIS_YONETICI")
    govde = {"kod": "SAHA_KAPALI", "ad": "Saha kapalı", "sla_durdurur": True, "sira": 80}
    await giris(client, "sef_b5")
    r = await client.put("/api/teknik-servis/tanimlar/bekleme-nedenleri", json=govde)
    assert r.status_code == 403
    await giris(client, "mud_b5")
    try:
        r = await client.put("/api/teknik-servis/tanimlar/bekleme-nedenleri", json=govde)
        assert r.status_code == 200, r.text
        surum = r.json()["version"]
        r = await client.get("/api/teknik-servis/tanimlar/bekleme-nedenleri")
        assert "SAHA_KAPALI" in [n["kod"] for n in r.json()]
        assert "BAKIM_UYGUNSUZLUK" not in [n["kod"] for n in r.json()]
        # Eski sürüm 409; pasifleme seçilebilir listeden düşürür.
        r = await client.put(
            "/api/teknik-servis/tanimlar/bekleme-nedenleri",
            json={**govde, "is_active": False, "version": surum + 5},
        )
        assert r.status_code == 409
        r = await client.put(
            "/api/teknik-servis/tanimlar/bekleme-nedenleri",
            json={**govde, "is_active": False, "version": surum},
        )
        assert r.status_code == 200
        r = await client.get("/api/teknik-servis/tanimlar/bekleme-nedenleri")
        assert "SAHA_KAPALI" not in [n["kod"] for n in r.json()]
        r = await client.get("/api/teknik-servis/tanimlar/bekleme-nedenleri", params={"tumu": True})
        assert "SAHA_KAPALI" in [n["kod"] for n in r.json()]
        # Geçersiz kod 400.
        r = await client.put(
            "/api/teknik-servis/tanimlar/bekleme-nedenleri", json={**govde, "kod": "kötü kod"}
        )
        assert r.status_code == 400
    finally:
        # Katalog tablosu test temizliğinde boşalmaz (tohum korunur).
        satir = await db.scalar(
            select(ServiceHoldReason).where(ServiceHoldReason.kod == "SAHA_KAPALI")
        )
        if satir is not None:
            await db.delete(satir)
            await db.commit()
