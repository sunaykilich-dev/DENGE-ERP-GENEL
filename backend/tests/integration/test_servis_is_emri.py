"""Servis işi açılışı, detay, olay geçmişi, mükerrer kontrolü ve bağlı iş
(TS-020, TS-022, TS-029, TS-030; E01-02/04/09/11).

Gerçek hikâye: eski sistemde iş "kim açtı, ne zaman, hangi kanaldan" bilgisi
serbest metindi ve aynı cihaz için üç ayrı açık iş birikebiliyordu. Burada
açılış tek kapıdan geçer: birim kapsamı, müşteri/lokasyon tutarlılığı,
mükerrer seri ve silinemez olay geçmişi.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest
from servis_yardimci import SRV_DESENI, acilis, giris, musteri, olay_sayisi, tazele
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models import Address, AuditLog, ServiceOrder, ServiceOrderEvent

pytestmark = pytest.mark.integration


async def test_acilis_yetki_ve_numara(client, db, kullanici_ac, birimli_kullanici_ac) -> None:
    await kullanici_ac("satis1", "SATIS")
    await birimli_kullanici_ac("op1", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db)

    await giris(client, "satis1")
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id))
    assert r.status_code == 403

    await giris(client, "op1")
    r = await client.post(
        "/api/teknik-servis/isler", json=acilis(hesap.id, seriler=[" 00123-a/1 ", "00123-A/1"])
    )
    assert r.status_code == 201, r.text
    is_ = r.json()
    assert re.match(SRV_DESENI, is_["so_no"])
    assert is_["status"] == "MUSTERI_TALEBI"
    assert is_["kategori"] == "GUNLUK_SERVIS"
    # Seri girildiği gibi (yalnız baş/son boşluk) ve norm ile tekilleştirildi.
    assert [s["seri_no"] for s in is_["seriler"]] == ["00123-a/1"]
    assert is_["seriler"][0]["seri_norm"] == "00123-A/1"
    assert await olay_sayisi(db, is_["id"], "OLUSTUR") == 1
    denetim = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity == "service_orders", AuditLog.action == "olustur")
    )
    assert denetim == 1


async def test_sistem_turu_ekrandan_acilamaz(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("op2", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "op2")
    for tur in ("PB", "ATOLYE"):
        r = await client.post(
            "/api/teknik-servis/isler", json=acilis(hesap.id, tur=tur, seriler=["SN-1"])
        )
        assert r.status_code == 400, r.text
    assert await db.scalar(select(func.count()).select_from(ServiceOrder)) == 0


async def test_birim_kapsami_acilista(client, db, kullanici_ac, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    await kullanici_ac("mudur", "SERVIS_YONETICI")  # TUMU, birimsiz
    hesap = await musteri(db)

    await giris(client, "sef_g")
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, birim="HABERLESME"))
    assert r.status_code == 404
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, birim="XYZ"))
    assert r.status_code == 400

    await giris(client, "mudur")
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, birim="HABERLESME"))
    assert r.status_code == 201, r.text


async def test_musteri_lokasyon_ve_talep_dogrulamasi(
    client, db, birimli_kullanici_ac, lokasyon_ac
) -> None:
    await birimli_kullanici_ac("op3", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db)
    baska_tesis = await lokasyon_ac()  # başka hesabın tesisi
    tedarikci = await musteri(db, "Tedarikçi", is_musteri=False, is_tedarikci=True)
    await giris(client, "op3")

    r = await client.post(
        "/api/teknik-servis/isler", json=acilis(hesap.id, address_id=baska_tesis.id)
    )
    assert r.status_code == 400
    assert "lokasyon" in r.json()["detail"]
    r = await client.post("/api/teknik-servis/isler", json=acilis(tedarikci.id))
    assert r.status_code == 400
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, talep_kanali=None))
    assert r.status_code == 400
    r = await client.post(
        "/api/teknik-servis/isler",
        json=acilis(hesap.id, iletisim_ad=None, iletisim_telefon=None),
    )
    assert r.status_code == 400
    # Bildirim zamanı: ileri 400, 7 günden eski 400, 6 gün önce 201.
    simdi = client.clock.now()
    for an, kod in (
        (simdi + timedelta(days=1), 400),
        (simdi - timedelta(days=8), 400),
        (simdi - timedelta(days=6), 201),
    ):
        r = await client.post(
            "/api/teknik-servis/isler", json=acilis(hesap.id, reported_at=an.isoformat())
        )
        assert r.status_code == kod, (an, r.text)


async def test_mukerrer_seri_409_ve_gecis(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("op4", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "op4")
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, seriler=["  abc-01 "]))
    assert r.status_code == 201
    ilk = r.json()

    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, seriler=["ABC-01"]))
    assert r.status_code == 409
    detay = r.json()["detail"]
    assert detay["kod"] == "MUKERRER"
    assert [m["so_no"] for m in detay["mevcut_isler"]] == [ilk["so_no"]]

    r = await client.post(
        "/api/teknik-servis/isler", json=acilis(hesap.id, seriler=["ABC-01"], mukerrer_gec=True)
    )
    assert r.status_code == 201
    yeni = r.json()
    assert any(u["kod"] == "MUKERRER_GECILDI" for u in yeni["uyarilar"])
    # Aynı müşteride açık iş yalnız uyarıdır.
    assert any(u["kod"] == "AYNI_LOKASYON" for u in yeni["uyarilar"])
    assert await olay_sayisi(db, yeni["id"], "NOT") == 1


async def test_kapsam_disi_mukerrerde_numara_sizmaz(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    from app.models import ServiceOrderSerial

    await birimli_kullanici_ac("op5", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db)
    yabanci = await servis_isi_ac(birim="HABERLESME")
    db.add(ServiceOrderSerial(service_order_id=yabanci.id, seri_no="GIZLI-9", seri_norm="GIZLI-9"))
    await db.commit()

    await giris(client, "op5")
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, seriler=["gizli-9"]))
    assert r.status_code == 409
    detay = r.json()["detail"]
    assert detay["mevcut_isler"] == []
    assert detay["kapsam_disi_var"] is True
    assert yabanci.so_no not in detay["mesaj"]
    # Kapalı işteki aynı seri engellemez.
    yabanci.status = "IPTAL"
    yabanci.cancel_reason = "test"
    await db.commit()
    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap.id, seriler=["gizli-9"]))
    assert r.status_code == 201


async def test_detay_kapsam_ve_sonraki_durumlar(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_d", "SERVIS_SEF", ["GUVENLIK"])
    benim = await servis_isi_ac(birim="GUVENLIK")
    yabanci = await servis_isi_ac(birim="HABERLESME")
    await giris(client, "sef_d")
    r = await client.get(f"/api/teknik-servis/isler/{benim.id}")
    assert r.status_code == 200
    detay = r.json()
    assert "IPTAL" in detay["sonraki_durumlar"]
    assert "KAPATILDI" not in detay["sonraki_durumlar"]
    assert {g["hedef"]: g["uc"] for g in detay["gecisler"]}["TAMAMLANDI"] == "sonuc"
    r = await client.get(f"/api/teknik-servis/isler/{yabanci.id}")
    assert r.status_code == 404


async def test_not_durumu_ve_surumu_degistirmez(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op6", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac(iletisim_telefon="+905551112233")
    surum, durum = so.version, so.status
    await giris(client, "op6")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/notlar", json={"metin": "Aranacak"})
    assert r.status_code == 201
    so = await tazele(db, so)
    assert (so.version, so.status) == (surum, durum)
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/notlar", json={"metin": "Ara: +905551112233"}
    )
    assert r.status_code == 400
    r = await client.get(f"/api/teknik-servis/isler/{so.id}/gecmis")
    assert r.status_code == 200
    assert [o["olay_turu"] for o in r.json()] == ["NOT"]
    assert r.json()[0]["kullanici"]["ad"] == "Op6"


async def test_olay_tablosu_guncellenemez_silinemez(db, servis_isi_ac) -> None:
    from app.clock import FakeClock
    from app.services.teknik_servis import gecmis

    so = await servis_isi_ac()
    olay = await gecmis.olay_yaz(db, so, "NOT", "deneme", user=None, clock=FakeClock())
    await db.commit()
    olay_id = olay.id
    for sql in (
        "UPDATE service_order_events SET ozet = 'x' WHERE id = :i",
        "DELETE FROM service_order_events WHERE id = :i",
    ):
        with pytest.raises(DBAPIError):
            await db.execute(text(sql), {"i": olay_id})
        await db.rollback()
    assert await db.scalar(
        select(ServiceOrderEvent.ozet).where(ServiceOrderEvent.id == olay_id)
    ) == ("deneme")


async def test_bagli_is_iliskisi(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("op7", "SERVIS_OPERASYON", ["GUVENLIK"])
    a = await servis_isi_ac(konu="A")
    b = await servis_isi_ac(konu="B")
    yabanci = await servis_isi_ac(birim="HABERLESME")
    await giris(client, "op7")

    r = await client.put(
        f"/api/teknik-servis/isler/{a.id}/iliski",
        json={"iliskili_is_id": b.id, "iliski_turu": "TEKRAR_ARIZA"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["iliskili_isler"]["ust"]["so_no"] == b.so_no
    assert await olay_sayisi(db, a.id, "ILISKI") == 1
    assert await olay_sayisi(db, b.id, "ILISKI") == 1
    r = await client.get(f"/api/teknik-servis/isler/{b.id}")
    assert [x["so_no"] for x in r.json()["iliskili_isler"]["alt"]] == [a.so_no]

    # Kendine bağ 409; döngü 409; kapsam dışı hedef 404 ve iş değişmez.
    r = await client.put(
        f"/api/teknik-servis/isler/{a.id}/iliski",
        json={"iliskili_is_id": a.id, "iliski_turu": "DEVAM"},
    )
    assert r.status_code == 409
    r = await client.put(
        f"/api/teknik-servis/isler/{b.id}/iliski",
        json={"iliskili_is_id": a.id, "iliski_turu": "DEVAM"},
    )
    assert r.status_code == 409
    r = await client.put(
        f"/api/teknik-servis/isler/{a.id}/iliski",
        json={"iliskili_is_id": yabanci.id, "iliski_turu": "DEVAM"},
    )
    assert r.status_code == 404
    a = await tazele(db, a)
    assert a.iliskili_is_id == b.id

    # Kapsam dışı işe (sistemce) kurulmuş bağ maskeli görünür.
    a.iliskili_is_id, a.iliski_turu = yabanci.id, "TEKRAR_ARIZA"
    await db.commit()
    r = await client.get(f"/api/teknik-servis/isler/{a.id}")
    ust = r.json()["iliskili_isler"]["ust"]
    assert ust["kapsam_disi"] is True and ust["id"] is None
    assert yabanci.so_no not in r.text


async def test_uzaktan_cozuldu_tek_istek(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("op8", "SERVIS_OPERASYON", ["GUVENLIK"])
    await birimli_kullanici_ac("sef8", "SERVIS_SEF", ["GUVENLIK"])
    hesap = await musteri(db)
    govde = acilis(
        hesap.id, tur="DESTEK", cozum_kanali="TELEFON", yapilan_islem="Telefonla yönlendirildi"
    )
    await giris(client, "op8")
    r = await client.post("/api/teknik-servis/isler/uzaktan-cozuldu", json=govde)
    assert r.status_code == 201, r.text
    is_ = r.json()
    assert is_["status"] == "TAMAMLANDI"
    assert is_["sonuc"]["cozum_kanali"] == "TELEFON"
    r = await client.get(f"/api/teknik-servis/isler/{is_['id']}/gecmis")
    turler = [o["olay_turu"] for o in r.json()]
    assert turler == ["OLUSTUR", "DURUM"]
    assert "Telefonla" in r.json()[1]["ozet"]
    # İş otomatik kapanmaz; şef kapatır.
    await giris(client, "sef8")
    r = await client.post(f"/api/teknik-servis/isler/{is_['id']}/kapat", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "KAPATILDI"


async def test_uzaktan_cozuldu_izin(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("sef9", "SERVIS_SEF", ["GUVENLIK"])  # uzaktan_coz var
    await birimli_kullanici_ac("tek9", "SERVIS_TEKNISYEN", ["GUVENLIK"])  # yok
    hesap = await musteri(db)
    govde = acilis(hesap.id, cozum_kanali="UZAKTAN", yapilan_islem="Uzaktan bağlanıldı")
    await giris(client, "tek9")
    r = await client.post("/api/teknik-servis/isler/uzaktan-cozuldu", json=govde)
    assert r.status_code == 403
    await giris(client, "sef9")
    r = await client.post(
        "/api/teknik-servis/isler/uzaktan-cozuldu", json={**govde, "cozum_kanali": "YERINDE"}
    )
    assert r.status_code == 422
    r = await client.post("/api/teknik-servis/isler/uzaktan-cozuldu", json=govde)
    assert r.status_code == 201


async def test_lokasyonlu_acilis_ve_ayni_lokasyon_uyarisi(
    client, db, birimli_kullanici_ac, lokasyon_ac
) -> None:
    await birimli_kullanici_ac("op10", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db)
    tesis: Address = await lokasyon_ac(hesap, ad="Akyaka AVM")
    await giris(client, "op10")
    r = await client.post(
        "/api/teknik-servis/isler",
        json=acilis(
            hesap.id, address_id=tesis.id, reported_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat()
        ),
    )
    assert r.status_code == 201
    assert r.json()["lokasyon"]["ad"] == "Akyaka AVM"
    r = await client.get(
        "/api/teknik-servis/isler/mukerrer-kontrol",
        params={"musteri_id": hesap.id, "adres_id": tesis.id},
    )
    assert r.status_code == 200
    assert len(r.json()["ayni_lokasyon"]) == 1
