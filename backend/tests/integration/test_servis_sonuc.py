"""Kapanış sonucu, çözüm kanalı ve arıza nedeni kataloğu (TS-024; E01-06).

Gerçek hikâye: eski sistemde POC'nin "Telefonla Destek / Uzaktan / Yerinde"
durumları, iş kapanınca nasıl çözüldüğü bilgisini durum adına gömüyordu;
"uzaktan çözülen oran" hesaplanamıyordu. Burada sonuç ve kanal ayrı, kanal
zorunlu, sonuçsuz TAMAMLANDI yok.
"""

import uuid

import pytest
from servis_yardimci import giris, tazele, teknisyen
from sqlalchemy import select

from app.models import ServiceFaultReason, ServiceHold

pytestmark = pytest.mark.integration

SONUC = {
    "sonuc": "COZULDU",
    "cozum_kanali": "YERINDE",
    "yapilan_islem": "Adaptör değişti",
    "sure_eksik_onay": True,
}  # süre kaydı yok (TS-076)


async def test_sonuc_izinleri_ve_teknisyen_kapatamaz(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op_s1", "SERVIS_OPERASYON", ["GUVENLIK"])
    tek = await teknisyen(birimli_kullanici_ac, "tek_s1")
    so = await servis_isi_ac(durum="SAHADA", atananlar=[tek])
    await giris(client, "op_s1")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 403
    await giris(client, "tek_s1")
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/sonuc", json={**SONUC, "cozum_kanali": "UCAN"}
    )
    assert r.status_code == 422
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TAMAMLANDI"
    assert r.json()["sonuc"]["cozum_kanali"] == "YERINDE"
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/kapat", json={})
    assert r.status_code == 403


async def test_beklemedeki_is_sonucla_tamamlanamaz(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_s2", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac()
    await giris(client, "sef_s2")
    await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme", json={"neden": "MALZEME"})
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 409
    so = await tazele(db, so)
    assert so.status == "BEKLEMEDE" and so.completed_at is None


async def test_tekrar_gidilecek_ve_teklif_sunulacak(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_s3", "SERVIS_SEF", ["GUVENLIK"])
    a = await servis_isi_ac()
    b = await servis_isi_ac(durum="SAHADA")
    await giris(client, "sef_s3")
    r = await client.post(
        f"/api/teknik-servis/isler/{a.id}/sonuc", json={**SONUC, "sonuc": "TEKRAR_GIDILECEK"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "PLANLAMADA"
    r = await client.post(
        f"/api/teknik-servis/isler/{b.id}/sonuc", json={**SONUC, "sonuc": "TEKLIF_SUNULACAK"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "BEKLEMEDE"
    hold = await db.scalar(select(ServiceHold).where(ServiceHold.service_order_id == b.id))
    assert hold.neden == "TEKLIF" and hold.released_at is None


async def test_ariza_nedeni_birim_bazli(
    client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_s4", "SERVIS_SEF", ["GUVENLIK"])
    await kullanici_ac("mud_s4", "SERVIS_YONETICI")
    ad = f"Test nedeni {uuid.uuid4().hex[:8]}"
    await giris(client, "sef_s4")
    r = await client.put(
        "/api/teknik-servis/tanimlar/ariza-nedenleri", json={"birim": "GUVENLIK", "ad": ad}
    )
    assert r.status_code == 403  # servis.tanim yok

    await giris(client, "mud_s4")
    try:
        r = await client.put(
            "/api/teknik-servis/tanimlar/ariza-nedenleri", json={"birim": "HABERLESME", "ad": ad}
        )
        assert r.status_code == 200, r.text
        neden = r.json()
        r = await client.put(
            "/api/teknik-servis/tanimlar/ariza-nedenleri", json={"birim": "HABERLESME", "ad": ad}
        )
        assert r.status_code == 409
        r = await client.put(
            "/api/teknik-servis/tanimlar/ariza-nedenleri",
            json={"id": neden["id"], "birim": "HABERLESME", "ad": ad, "sira": 5,
                  "version": neden["version"]},
        )  # fmt: skip
        assert r.status_code == 200 and r.json()["sira"] == 5

        # Başka birimin nedeni sonuçta 400.
        await giris(client, "sef_s4")
        so = await servis_isi_ac()
        r = await client.post(
            f"/api/teknik-servis/isler/{so.id}/sonuc",
            json={**SONUC, "ariza_nedeni_id": neden["id"]},
        )
        assert r.status_code == 400
        # Şef yalnız kendi biriminin listesini görür (tohum 8 neden).
        r = await client.get("/api/teknik-servis/tanimlar/ariza-nedenleri")
        assert r.status_code == 200
        assert {n["birim"] for n in r.json()} == {"GUVENLIK"}
        guvenlik = r.json()[0]["id"]
        r = await client.post(
            f"/api/teknik-servis/isler/{so.id}/sonuc", json={**SONUC, "ariza_nedeni_id": guvenlik}
        )
        assert r.status_code == 200
        assert r.json()["sonuc"]["ariza_nedeni"] is not None
    finally:
        satir = await db.scalar(select(ServiceFaultReason).where(ServiceFaultReason.ad == ad))
        if satir is not None:
            await db.delete(satir)
            await db.commit()


async def test_sure_kaydi_eksikse_onay_istenir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    """TS-076 kancası sonuç yolunda: süre kaydı yoksa onaysız 409, hiçbir şey yazılmaz."""
    from app.models import ServiceResult

    await birimli_kullanici_ac("sef_s5", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac(durum="SAHADA")
    await giris(client, "sef_s5")
    govde = {k: v for k, v in SONUC.items() if k != "sure_eksik_onay"}
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=govde)
    assert r.status_code == 409
    assert "Süre kaydı eksik" in r.json()["detail"]
    so = await tazele(db, so)
    assert so.status == "SAHADA"
    assert (await db.scalars(select(ServiceResult))).all() == []
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200
    assert r.json()["status"] == "TAMAMLANDI"
