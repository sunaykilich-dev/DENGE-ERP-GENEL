"""Tek kayıt kapsamı, KENDI_ISLERI, telefon maskeleme (TS-027; E01-20, E01-01 kabul).

Gerçek hikâye: canlıdaki kapsam açığı tek kayıt uçlarındaydı — liste
süzülüyordu ama `db.get()` ile alınan kayıt kapsamı hiç sormuyordu; yanıt
404 olsa bile yazma geçmişti. Burada atanmamış teknisyen her uçta 404 alır
ve kayıt DEĞİŞMEZ (db.refresh); telefonu yalnız yazma/irtibat izni olan görür.
"""

import pytest
from servis_yardimci import giris, olay_sayisi, tazele, teknisyen
from sqlalchemy import func, select

from app.models import AuditLog, ServiceHold, ServiceOrderAssignment, ServiceResult

pytestmark = pytest.mark.integration

TELEFON = "+905321112233"


async def test_atanmamis_teknisyen_her_ucta_404_veri_degismez(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await teknisyen(birimli_kullanici_ac, "tek_k1")
    diger = await teknisyen(birimli_kullanici_ac, "tek_k2")
    so = await servis_isi_ac(atananlar=[diger], iletisim_telefon=TELEFON)
    once = (so.status, so.version, so.konu)
    await giris(client, "tek_k1")
    denetim_once = await db.scalar(select(func.count()).select_from(AuditLog))
    uclar = [
        ("GET", f"/isler/{so.id}", None),
        ("GET", f"/isler/{so.id}/gecmis", None),
        ("GET", f"/isler/{so.id}/beklemeler", None),
        ("GET", f"/isler/{so.id}/ekip", None),
        ("GET", f"/isler/{so.id}/onaylar", None),
        ("PATCH", f"/isler/{so.id}", {"version": so.version, "konu": "x"}),
        ("POST", f"/isler/{so.id}/durum", {"hedef": "ISLEMDE"}),
        ("POST", f"/isler/{so.id}/notlar", {"metin": "x"}),
        ("POST", f"/isler/{so.id}/bekleme", {"neden": "MALZEME"}),
        ("POST", f"/isler/{so.id}/bekleme/bitir", {}),
        ("POST", f"/isler/{so.id}/sonuc",
         {"sonuc": "COZULDU", "cozum_kanali": "YERINDE", "yapilan_islem": "x"}),
        ("PUT", f"/isler/{so.id}/seriler", {"seriler": ["X1"]}),
        ("PUT", f"/isler/{so.id}/iliski", {"iliskili_is_id": None}),
    ]  # fmt: skip
    for yontem, yol, govde in uclar:
        r = await client.request(yontem, f"/api/teknik-servis{yol}", json=govde)
        assert r.status_code == 404, (yontem, yol, r.status_code)
    so = await tazele(db, so)
    assert (so.status, so.version, so.konu) == once
    assert await olay_sayisi(db, so.id) == 0
    assert (await db.scalars(select(ServiceHold))).all() == []
    assert (await db.scalars(select(ServiceResult))).all() == []
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == denetim_once
    r = await client.get("/api/teknik-servis/isler")
    assert r.json() == [] and r.headers["X-Toplam-Kayit"] == "0"


async def test_izin_ayrimi_tamamla_ve_kapat(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op_k3", "SERVIS_OPERASYON", ["GUVENLIK"])  # tamamla yok
    await birimli_kullanici_ac("atolye_k3", "ATOLYE", ["GUVENLIK"])  # kapat yok
    so = await servis_isi_ac(durum="SAHADA")
    tam = await servis_isi_ac(durum="TAMAMLANDI")
    await giris(client, "op_k3")
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/sonuc",
        json={"sonuc": "COZULDU", "cozum_kanali": "YERINDE", "yapilan_islem": "x"},
    )
    assert r.status_code == 403
    await giris(client, "atolye_k3")
    r = await client.post(f"/api/teknik-servis/isler/{tam.id}/kapat", json={})
    assert r.status_code == 403
    assert (await tazele(db, tam)).status == "TAMAMLANDI"


async def test_telefon_maskeleme(
    client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await kullanici_ac("yon_k4", "YONETIM")  # yalnız servis.gor
    await birimli_kullanici_ac("sef_k4", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac(iletisim_telefon=TELEFON, iletisim_ad="Saha Yetkilisi")
    await giris(client, "yon_k4")
    liste = (await client.get("/api/teknik-servis/isler")).json()
    detay = (await client.get(f"/api/teknik-servis/isler/{so.id}")).json()
    assert liste[0]["iletisim_telefon"] == "**********233"
    assert detay["iletisim_telefon"] == "**********233"
    assert TELEFON not in (await client.get(f"/api/teknik-servis/isler/{so.id}")).text
    await giris(client, "sef_k4")
    detay = (await client.get(f"/api/teknik-servis/isler/{so.id}")).json()
    assert detay["iletisim_telefon"] == TELEFON


async def test_teknisyen_hesaplara_erisemez(client, birimli_kullanici_ac) -> None:
    await teknisyen(birimli_kullanici_ac, "tek_k5")
    await giris(client, "tek_k5")
    r = await client.get("/api/hesaplar")
    assert r.status_code == 403


async def test_birimsiz_kapsamli_kullanici_hicbir_sey_gormez(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_k6", "SERVIS_SEF", [])
    so = await servis_isi_ac()
    await giris(client, "sef_k6")
    r = await client.get("/api/teknik-servis/isler")
    assert r.json() == []
    assert (await client.get(f"/api/teknik-servis/isler/{so.id}")).status_code == 404


async def test_atanmis_teknisyen_yalniz_kendi_isini_gorur_ve_yazar(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "tek_k7")
    benim = await servis_isi_ac(atananlar=[tek])
    await servis_isi_ac()
    await giris(client, "tek_k7")
    r = await client.get("/api/teknik-servis/isler")
    assert [x["id"] for x in r.json()] == [benim.id]
    r = await client.post(f"/api/teknik-servis/isler/{benim.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 200
    # Atama kaldırılınca kapsam da kalkar.
    satir = await db.scalar(
        select(ServiceOrderAssignment).where(ServiceOrderAssignment.service_order_id == benim.id)
    )
    satir.removed_at = client.clock.now()
    await db.commit()
    assert (await client.get(f"/api/teknik-servis/isler/{benim.id}")).status_code == 404
