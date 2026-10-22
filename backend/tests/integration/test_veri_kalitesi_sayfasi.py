"""Veri Kalitesi sayfası (TS-188, E12-16/E14-18) ve seri → mobilite cihaz bağı
(TS-193, E01-10)."""

from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import (
    Account,
    AuditLog,
    Device,
    ImportBatch,
    ServiceOrder,
    ServiceOrderSerial,
)
from app.services.teknik_servis import rapor_kalite

pytestmark = pytest.mark.integration

ANA = "/api/teknik-servis/ana-veri"


@pytest.fixture
async def giris(client):
    from app.main import app

    acik: list[httpx.AsyncClient] = []

    async def _ac(username: str) -> httpx.AsyncClient:
        ist = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Requested-With": "fetch"},
        )
        r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
        assert r.status_code == 200, r.text
        acik.append(ist)
        return ist

    yield _ac
    for ist in acik:
        await ist.aclose()


async def _hesap(db, ad, **kw):
    h = Account(title=ad, is_musteri=True, **kw)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _tum_tablolar(db) -> dict[str, int]:
    return {
        m.__tablename__: await db.scalar(select(func.count()).select_from(m))
        for m in (ServiceOrder, Account, AuditLog, ServiceOrderSerial)
    }


async def test_her_kontrol_sayisi_liste_toplamina_esit_ve_salt_okuma(
    birimli_kullanici_ac, giris, db, servis_isi_ac, lokasyon_ac, ekipman_ac
) -> None:
    await birimli_kullanici_ac("vk_yon", "SERVIS_SEF", ["GUVENLIK"])
    y = await giris("vk_yon")
    m = await _hesap(db, "Kalite A.Ş.", is_verified=False)
    await _hesap(db, "KALITE AŞ")
    await _hesap(db, "Vergi Bir", tax_no="1111111111")
    await _hesap(db, "Vergi İki", tax_no="1111111111")
    await servis_isi_ac(musteri=m, durum="TAMAMLANDI")  # çözüm zamanı + süre eksik
    await servis_isi_ac(musteri=m, tur="ATOLYE", durum="PLANLANDI")  # seri eksik
    await servis_isi_ac(musteri=m, birim="HABERLESME")  # kapsam dışı
    await ekipman_ac(musteri=m, seri=None)
    db.add(
        ImportBatch(
            profile="servis_isleri",
            filename="karantina.xlsx",
            status="HAZIR",
            staged_rows=[
                {
                    "satir_no": 1,
                    "ham": {"ref": "WorkOrders:1", "birim": "GUVENLIK"},
                    "hatalar": ["Durum seçilmeli"],
                },  # noqa: E501
                {
                    "satir_no": 2,
                    "ham": {"ref": "WorkOrders:2", "birim": "HABERLESME"},
                    "hatalar": ["x"],
                },  # noqa: E501
                {"satir_no": 3, "ham": {"ref": "WorkOrders:3", "birim": "GUVENLIK"}, "hatalar": []},
            ],
        )
    )
    await db.commit()

    once = await _tum_tablolar(db)
    r = await y.get(f"{ANA}/veri-kalitesi")
    assert r.status_code == 200, r.text
    kontroller = r.json()["kontroller"]
    kodlar = {k["kod"]: k for k in kontroller}
    assert {"tanimsiz_durum", "cozum_zamani_eksik", "seri_eksik", "mukerrer_unvan"} <= set(kodlar)
    assert kodlar["tanimsiz_durum"]["deger"] == 1  # HABERLESME satırı kapsam dışı
    assert kodlar["seri_eksik"]["deger"] == 1
    assert kodlar["mukerrer_vkn"]["deger"] == 1
    assert kodlar["ekipman_seri_eksik"]["hedef"].startswith("/servis-ekipman")
    for kod, k in kodlar.items():
        if kod.startswith("ekipman_"):
            continue
        liste = await y.get(f"{ANA}/veri-kalitesi/liste", params={"kontrol": kod})
        assert liste.status_code == 200, (kod, liste.text)
        assert int(liste.headers["X-Toplam-Kayit"]) == k["deger"], kod
    sonra = await _tum_tablolar(db)
    assert once == sonra  # sayfa hiçbir veriyi değiştirmez

    x = await y.get(f"{ANA}/veri-kalitesi/liste.xlsx", params={"kontrol": "seri_eksik"})
    assert x.status_code == 200
    ws = load_workbook(BytesIO(x.content)).active
    assert ws.max_row - 1 == kodlar["seri_eksik"]["deger"]
    denetim = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "ana_veri.disaaktar")
    )
    assert denetim == 1
    assert (await y.get(f"{ANA}/veri-kalitesi/liste", params={"kontrol": "yok"})).status_code == 400


async def test_rbac_ve_kontrol_izni(birimli_kullanici_ac, kullanici_ac, giris, db) -> None:
    await kullanici_ac("vk_montaj", "MONTAJ_KOORD")
    montaj = await giris("vk_montaj")
    assert (await montaj.get(f"{ANA}/veri-kalitesi")).status_code == 403
    # İK: servis_rapor.gor var, hesap.gor/servis.gor yok → hesap kontrolü 403 ve özette yok.
    await kullanici_ac("vk_depo", "IK")
    depo = await giris("vk_depo")
    r = await depo.get(f"{ANA}/veri-kalitesi")
    assert r.status_code == 200
    assert "dogrulanmamis_musteri" not in {k["kod"] for k in r.json()["kontroller"]}
    r = await depo.get(f"{ANA}/veri-kalitesi/liste", params={"kontrol": "dogrulanmamis_musteri"})
    assert r.status_code == 403
    # Excel servis_rapor.disaaktar ister.
    await birimli_kullanici_ac("vk_tekn", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    tekn = await giris("vk_tekn")
    r = await tekn.get(f"{ANA}/veri-kalitesi/liste.xlsx", params={"kontrol": "seri_eksik"})
    assert r.status_code == 403


async def test_birim_kapsami_sayilari_ayirir(
    birimli_kullanici_ac, giris, db, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("vk_sef_g", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("vk_sef_h", "SERVIS_SEF", ["HABERLESME"])
    g = await giris("vk_sef_g")
    h = await giris("vk_sef_h")
    m = await _hesap(db, "Birim Müşteri")
    await servis_isi_ac(musteri=m, birim="HABERLESME", tur="ATOLYE", durum="MUSTERI_TALEBI")
    sg = {k["kod"]: k["deger"] for k in (await g.get(f"{ANA}/veri-kalitesi")).json()["kontroller"]}
    sh = {k["kod"]: k["deger"] for k in (await h.get(f"{ANA}/veri-kalitesi")).json()["kontroller"]}
    assert sg["seri_eksik"] == 0 and sh["seri_eksik"] == 1


# --- TS-193: seri → mobilite cihaz kütüğü -------------------------------------------------


async def test_mobilite_isi_cihaz_kartinda_gorunur_devices_yazilmaz(
    kullanici_ac, giris, db, servis_isi_ac, cihaz_ac
) -> None:
    await kullanici_ac("vk_admin", "ADMIN")
    adm = await giris("vk_admin")
    cihaz = await cihaz_ac(imei="356938035643809")
    m = await _hesap(db, "Mobilite Müşteri")
    so = await servis_isi_ac(musteri=m, birim="MOBILITE")
    db.add(ServiceOrderSerial(service_order_id=so.id, seri_no="356938035643809"))
    yabanci = await servis_isi_ac(musteri=m, birim="MOBILITE", konu="Kütükte yok")
    db.add(ServiceOrderSerial(service_order_id=yabanci.id, seri_no="KUTUKTE-YOK-1"))
    guv = await servis_isi_ac(musteri=m, birim="GUVENLIK", konu="Güvenlik")
    db.add(ServiceOrderSerial(service_order_id=guv.id, seri_no="356938035643809"))
    await db.commit()
    cihaz_sayisi = await db.scalar(select(func.count()).select_from(Device))
    surum = cihaz.version

    r = await adm.get("/api/teknik-servis/cihaz-servis-isleri", params={"cihaz_id": cihaz.id})
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [so.id]  # güvenlik işi cihaz kütüğüne bakmaz
    assert int(r.headers["X-Toplam-Kayit"]) == 1

    e = await adm.get(f"/api/teknik-servis/isler/{so.id}/cihaz-eslesmeleri")
    assert e.json()[0]["cihaz_id"] == cihaz.id and e.json()[0]["durum"] == "TEK"
    e = await adm.get(f"/api/teknik-servis/isler/{yabanci.id}/cihaz-eslesmeleri")
    assert e.json()[0]["durum"] == "KUTUKTE_YOK"

    toplam, satirlar = await rapor_kalite.listele(
        db, await _kullanici(db, "vk_admin"), "kutukte_olmayan_seri", limit=50
    )
    assert toplam == 1 and satirlar[0]["id"] == yabanci.id

    assert await db.scalar(select(func.count()).select_from(Device)) == cihaz_sayisi
    await db.refresh(cihaz)
    assert cihaz.version == surum
    seri = await db.scalar(
        select(ServiceOrderSerial).where(ServiceOrderSerial.service_order_id == so.id)
    )
    assert seri.device_id is None  # okuma anında eşleşir, yazılmaz


async def _kullanici(db, ad):
    from app.models import User

    return await db.scalar(select(User).where(User.username == ad))


async def test_cihaz_servis_isleri_rbac(kullanici_ac, giris, cihaz_ac) -> None:
    await kullanici_ac("vk_satis", "SATIS")
    satis = await giris("vk_satis")
    cihaz = await cihaz_ac(imei="490154203237518")
    r = await satis.get("/api/teknik-servis/cihaz-servis-isleri", params={"cihaz_id": cihaz.id})
    assert r.status_code == 403
