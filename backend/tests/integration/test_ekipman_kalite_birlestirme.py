"""Ekipman veri kalitesi, birleştirme, saha farkı ve analitik KPI (TS-188/TS-191,
E03-13/14/15)."""

import httpx
import pytest
from sqlalchemy import func, select, text

from app.models import (
    AuditLog,
    MaintenanceContractItem,
    ServiceResult,
)

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/ekipman"


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


@pytest.fixture
async def yonetici(birimli_kullanici_ac, giris):
    await birimli_kullanici_ac("ek_yon", "SERVIS_SEF", ["GUVENLIK"])
    return await giris("ek_yon")


async def _musteri(db, ad):
    from app.models import Account

    h = Account(title=ad, is_musteri=True)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _kalite(ist) -> dict[str, int]:
    r = await ist.get(f"{URL}/veri-kalitesi")
    assert r.status_code == 200, r.text
    return {k["kod"]: k["deger"] for k in r.json()}


# --- Veri kalitesi: sayı = liste --------------------------------------------------------


async def test_kalite_sayilari_liste_toplamina_esit(yonetici, ekipman_ac, db) -> None:
    m = await _musteri(db, "Kalite Müşterisi")
    await ekipman_ac(musteri=m, seri="DUP-1", brand="Smiths")
    await ekipman_ac(musteri=m, seri="dup-1", brand="SMITHS")  # aynı anahtar
    await ekipman_ac(musteri=m, seri=None)
    await ekipman_ac(musteri=m, seri="X-9", lifecycle_status="KURULU")
    # Başka birim kapsama girmez.
    await ekipman_ac(birim="HABERLESME", seri=None)

    sayilar = await _kalite(yonetici)
    for kod in (
        "seri_eksik",
        "lokasyonsuz",
        "hesapsiz",
        "sozlesmesiz_kurulu",
        "durum_bilinmiyor",
        "mukerrer",
    ):  # noqa: E501
        r = await yonetici.get(URL, params={"kalite": kod})
        assert r.status_code == 200, r.text
        assert int(r.headers["X-Toplam-Kayit"]) == sayilar[kod], kod
    assert sayilar["seri_eksik"] == 1
    assert sayilar["mukerrer"] == 2
    assert sayilar["sozlesmesiz_kurulu"] == 1

    r = await yonetici.get(f"{URL}/mukerrer-gruplar")
    assert int(r.headers["X-Toplam-Kayit"]) == sayilar["mukerrer_grup"] == 1
    assert len(r.json()[0]["kayitlar"]) == 2

    # DB GROUP BY ile aynı (kabul 1).
    db_grup = await db.scalar(
        text(
            "select count(*) from (select 1 from service_equipment where is_active and "
            "not is_deleted and serial_key is not null and duplicate_ack_reason is null "
            "and birim = 'GUVENLIK' group by equipment_type, brand_key, serial_key "
            "having count(*) > 1) g"
        )
    )
    assert db_grup == sayilar["mukerrer_grup"]
    assert (await yonetici.get(URL, params={"kalite": "yok_boyle"})).status_code == 400


async def test_kalite_salt_okuma(yonetici, ekipman_ac, db) -> None:
    await ekipman_ac(seri=None)
    once = await db.scalar(select(func.count()).select_from(AuditLog))
    await _kalite(yonetici)
    await yonetici.get(f"{URL}/mukerrer-gruplar")
    await yonetici.get(f"{URL}/saha-farklari")
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == once


# --- Birleştirme (E03-13) -------------------------------------------------------------


async def test_birlestirme_acik_is_varken_409_ve_degismez(
    yonetici, ekipman_ac, servis_isi_ac, db
) -> None:
    m = await _musteri(db, "Birleştir A")
    ana = await ekipman_ac(musteri=m, seri="BRL-1")
    ikincil = await ekipman_ac(musteri=m, seri="BRL-1")
    so = await servis_isi_ac(musteri=m, durum="PLANLAMADA", equipment_id=ikincil.id)

    r = await yonetici.post(
        f"{URL}/{ikincil.id}/birlestir", json={"ana_id": ana.id, "gerekce": "Aynı cihaz"}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["servis_isleri"][0]["so_no"] == so.so_no
    await db.refresh(ikincil)
    assert ikincil.is_active and ikincil.merged_into_id is None


async def test_birlestirme_acik_sozlesme_kalemi_409(yonetici, ekipman_ac, sozlesme_ac, db) -> None:
    m = await _musteri(db, "Birleştir K")
    ana = await ekipman_ac(musteri=m, seri="BRL-K")
    ikincil = await ekipman_ac(musteri=m, seri="BRL-K")
    s = await sozlesme_ac(musteri=m)
    db.add(
        MaintenanceContractItem(
            contract_id=s.id, equipment_type="XRAY", sira=1, equipment_id=ikincil.id
        )
    )
    await db.commit()
    r = await yonetici.post(
        f"{URL}/{ikincil.id}/birlestir", json={"ana_id": ana.id, "gerekce": "Aynı cihaz"}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["sozlesme_kalemleri"]
    e = await yonetici.get(f"{URL}/{ikincil.id}/birlestirme-engelleri")
    assert e.json()["sozlesme_kalemleri"]


async def test_birlestirme_basarili_pb_degismez_gecmise_yazilir(
    yonetici, ekipman_ac, servis_isi_ac, db
) -> None:
    m = await _musteri(db, "Birleştir B")
    ana = await ekipman_ac(musteri=m, seri="BRL-2")
    ikincil = await ekipman_ac(musteri=m, seri="BRL-2")
    pb = await servis_isi_ac(musteri=m, durum="KAPATILDI", equipment_id=ikincil.id)
    pb_no = pb.so_no

    r = await yonetici.post(
        f"{URL}/{ikincil.id}/birlestir", json={"ana_id": ana.id, "gerekce": "Aynı cihaz iki kayıt"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == ana.id
    await db.refresh(ikincil)
    assert ikincil.merged_into_id == ana.id and not ikincil.is_active
    await db.refresh(pb)
    assert pb.so_no == pb_no and pb.equipment_id == ikincil.id  # PB numarası/bağı değişmez
    for e in (ikincil, ana):
        d = await yonetici.get(f"{URL}/{e.id}/degisiklikler")
        assert any(x["eylem"] == "birlestir" for x in d.json())
    # Birleşmiş kayıt mükerrer listesinden düşer.
    sayilar = await _kalite(yonetici)
    assert sayilar["mukerrer_grup"] == 0
    # Kendisiyle / gerekçesiz.
    assert (
        await yonetici.post(
            f"{URL}/{ana.id}/birlestir", json={"ana_id": ana.id, "gerekce": "xxxxx"}
        )
    ).status_code == 400


async def test_birlestirme_ana_kapsam_disi_404(yonetici, ekipman_ac, db) -> None:
    ikincil = await ekipman_ac(seri="BRL-3")
    yabanci = await ekipman_ac(birim="HABERLESME", seri="BRL-3")
    r = await yonetici.post(
        f"{URL}/{ikincil.id}/birlestir", json={"ana_id": yabanci.id, "gerekce": "Aynı cihaz"}
    )
    assert r.status_code == 404
    await db.refresh(ikincil)
    assert ikincil.is_active


async def test_birlestirme_rbac(birimli_kullanici_ac, giris, ekipman_ac) -> None:
    await birimli_kullanici_ac("ek_tekn", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    tekn = await giris("ek_tekn")
    e = await ekipman_ac(seri="RB-1")
    a = await ekipman_ac(seri="RB-2")
    r = await tekn.post(f"{URL}/{e.id}/birlestir", json={"ana_id": a.id, "gerekce": "xxxxxx"})
    assert r.status_code == 403
    assert (await tekn.get(f"{URL}/veri-kalitesi")).status_code == 200


# --- Saha farkı (E03-14) ----------------------------------------------------------------


async def _sonuc(db, so, *, seri=None, bolge=None, durum="ACIK", user_id=None):
    s = ServiceResult(
        service_order_id=so.id,
        sonuc="COZULDU",
        cozum_kanali="YERINDE",
        yapilan_islem="Kontrol",
        saha_seri_no=seri,
        saha_bolge=bolge,
        kutuk_fark_durumu=durum,
        created_by=user_id,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_saha_farki_uygula_ve_gecmis(yonetici, ekipman_ac, servis_isi_ac, kullanici_ac, db):
    tekn = await kullanici_ac("saha_tekn", "SERVIS_TEKNISYEN")
    m = await _musteri(db, "Saha Müşterisi")
    e = await ekipman_ac(musteri=m, seri=None)
    so = await servis_isi_ac(musteri=m, durum="TAMAMLANDI", equipment_id=e.id)
    await _sonuc(db, so, seri="ABC-001", bolge="B Kapısı", user_id=tekn.id)

    liste = await yonetici.get(f"{URL}/saha-farklari")
    assert int(liste.headers["X-Toplam-Kayit"]) == 1
    assert liste.json()[0]["saha_seri"] == "ABC-001"
    await db.refresh(e)
    assert e.serial_no is None  # kapanış kütüğü değiştirmez (kabul 1)

    r = await yonetici.post(f"{URL}/saha-farklari/{so.id}/uygula")
    assert r.status_code == 200, r.text
    assert r.json()["serial_no"] == "ABC-001"
    d = await yonetici.get(f"{URL}/{e.id}/degisiklikler")
    kayit = next(x for x in d.json() if x["eylem"] == "saha.uygula")
    assert kayit["yeni"]["teknisyen_id"] == tekn.id and kayit["yeni"]["onaylayan_id"]
    assert int((await yonetici.get(f"{URL}/saha-farklari")).headers["X-Toplam-Kayit"]) == 0


async def test_saha_farki_cakisan_seri_409_yoksay(yonetici, ekipman_ac, servis_isi_ac, db):
    m = await _musteri(db, "Saha Çakışma")
    await ekipman_ac(musteri=m, seri="ABC-002")
    e = await ekipman_ac(musteri=m, seri="ESKI-1")
    so = await servis_isi_ac(musteri=m, durum="TAMAMLANDI", equipment_id=e.id)
    sonuc = await _sonuc(db, so, seri="abc-002")

    r = await yonetici.post(f"{URL}/saha-farklari/{so.id}/uygula")
    assert r.status_code == 409, r.text
    await db.refresh(e)
    assert e.serial_no == "ESKI-1"

    r = await yonetici.post(
        f"{URL}/saha-farklari/{so.id}/yoksay", json={"gerekce": "Etiket hatalı"}
    )
    assert r.status_code == 204, r.text
    await db.refresh(sonuc)
    assert sonuc.kutuk_fark_durumu == "YOK_SAYILDI"
    d = await yonetici.get(f"{URL}/{e.id}/degisiklikler")
    assert any(x["eylem"] == "saha.yoksay" and x["yeni"]["gerekce"] for x in d.json())


async def test_kapanista_otomatik_bagla_tek_eslesme(servis_isi_ac, ekipman_ac, db) -> None:
    """Kapanış kancası: aynı müşteri + birimde TEK eşleşme → işe bağlanır; kütük
    seriyle aynıysa fark kapanır (sahte fark listede kalmaz)."""
    from app.clock import FakeClock
    from app.services.teknik_servis import ekipman

    m = await _musteri(db, "Oto Bağla")
    e = await ekipman_ac(musteri=m, seri="OTO-1")
    await ekipman_ac(seri="OTO-1")  # başka müşteri: eşleşmeyi bozmaz
    so = await servis_isi_ac(musteri=m, durum="TAMAMLANDI")
    sonuc = await _sonuc(db, so, seri=" oto-1 ")
    await ekipman._saha_farki_kapanista(db, so, "SAHADA", "TAMAMLANDI", "sonuc", FakeClock())
    await db.commit()
    await db.refresh(so)
    await db.refresh(sonuc)
    assert so.equipment_id == e.id
    assert sonuc.kutuk_fark_durumu is None

    # İki aday → bağlanmaz, fark açık kalır.
    m2 = await _musteri(db, "Oto Belirsiz")
    await ekipman_ac(musteri=m2, seri="OTO-2")
    await ekipman_ac(musteri=m2, seri="OTO-2", brand="Farklı")
    so2 = await servis_isi_ac(musteri=m2, durum="TAMAMLANDI")
    s2 = await _sonuc(db, so2, seri="OTO-2")
    await ekipman._saha_farki_kapanista(db, so2, "SAHADA", "TAMAMLANDI", "sonuc", FakeClock())
    await db.commit()
    await db.refresh(so2)
    await db.refresh(s2)
    assert so2.equipment_id is None and s2.kutuk_fark_durumu == "ACIK"


# --- Analitik KPI (E03-15) ---------------------------------------------------------------


async def test_analitik_kpi_sayi_liste_ve_ayar(
    yonetici, ekipman_ac, servis_isi_ac, sozlesme_ac, db
):
    m = await _musteri(db, "KPI Müşterisi")
    gecikmis = await ekipman_ac(musteri=m, seri="KPI-1", lifecycle_status="KURULU")
    s = await sozlesme_ac(musteri=m)
    db.add(
        MaintenanceContractItem(
            contract_id=s.id, equipment_type="XRAY", sira=1, equipment_id=gecikmis.id
        )
    )
    tekrar = await ekipman_ac(musteri=m, seri="KPI-2")
    serisiz = await ekipman_ac(musteri=m, seri=None)
    await db.commit()
    for eq in (tekrar, tekrar, serisiz, serisiz):
        await servis_isi_ac(musteri=m, durum="MUSTERI_TALEBI", equipment_id=eq.id)

    ozet = {k["kod"]: k["deger"] for k in (await yonetici.get(f"{URL}/ozet")).json()}
    for kod in ("bakim_gecikmis", "tekrar_ariza"):
        r = await yonetici.get(URL, params={"kpi": kod})
        assert int(r.headers["X-Toplam-Kayit"]) == ozet[kod], kod
    ids = [x["id"] for x in (await yonetici.get(URL, params={"kpi": "tekrar_ariza"})).json()]
    assert tekrar.id in ids and serisiz.id not in ids  # seri no'suz sayılmaz
    assert gecikmis.id in [
        x["id"] for x in (await yonetici.get(URL, params={"kpi": "bakim_gecikmis"})).json()
    ]  # noqa: E501

    # Eşik ayardan: 3'e çıkınca tekrar arıza listesinden düşer.
    from app.services import settings as ayar_svc

    await ayar_svc.set_many(db, {"ekipman_tekrar_ariza_esik": 3}, user_id=None)
    await db.commit()
    ozet2 = {k["kod"]: k["deger"] for k in (await yonetici.get(f"{URL}/ozet")).json()}
    assert ozet2["tekrar_ariza"] == ozet["tekrar_ariza"] - 1
