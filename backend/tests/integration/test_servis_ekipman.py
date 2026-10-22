"""Ekipman kütüğü: yazma kapısı, mükerrer, durum, liste/KPI/Excel, öneri, garanti
(TS-050, TS-053, TS-054, TS-055, TS-056)."""

from datetime import UTC, date, datetime
from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models import (
    Account,
    AuditLog,
    Contact,
    MaintenanceContractItem,
    ServiceEquipment,
)
from app.services.teknik_servis import ekipman as svc

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/ekipman"


@pytest.fixture
async def giris(client):
    """Ayrı çerezli istemci açar: `await giris("kullanici")`."""
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


async def _musteri(db, ad: str) -> Account:
    hesap = Account(title=ad, is_musteri=True)
    db.add(hesap)
    await db.commit()
    await db.refresh(hesap)
    return hesap


async def _denetim_sayisi(db) -> int:
    return await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.entity == "service_equipment")
    )


@pytest.fixture
async def sef(birimli_kullanici_ac, giris):
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    return await giris("sef_g")


# --- RBAC ---------------------------------------------------------------------------


async def test_rbac_okuma_yazma(birimli_kullanici_ac, kullanici_ac, giris, db) -> None:
    await kullanici_ac("montaj", "MONTAJ_KOORD")
    await birimli_kullanici_ac("tekn", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    await birimli_kullanici_ac("sef1", "SERVIS_SEF", ["GUVENLIK"])
    hesap = await _musteri(db, "RBAC Müşteri")
    govde = {"birim": "GUVENLIK", "equipment_type": "XRAY", "account_id": hesap.id}

    montaj = await giris("montaj")
    assert (await montaj.get(URL)).status_code == 403

    tekn = await giris("tekn")
    assert (await tekn.get(URL)).status_code == 200
    assert (await tekn.post(URL, json=govde)).status_code == 403
    # Excel ayrı izin ister (servis_rapor.disaaktar) — teknisyende yok.
    assert (await tekn.get(f"{URL}/liste.xlsx")).status_code == 403

    sef = await giris("sef1")
    r = await sef.post(URL, json=govde)
    assert r.status_code == 201, r.text
    assert (
        await tekn.post(f"{URL}/{r.json()['id']}/pasif", json={"gerekce": "deneme x"})
    ).status_code == 403


# --- TS-050: metin seri, mükerrer, sürüm, hesap tutarlılığı ------------------------


async def test_seri_metin_olarak_saklanir(sef, db) -> None:
    hesap = await _musteri(db, "Metin Seri")
    r = await sef.post(
        URL,
        json={
            "birim": "GUVENLIK",
            "equipment_type": "XRAY",
            "account_id": hesap.id,
            "serial_no": "00123/A-7",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["serial_no"] == "00123/A-7"
    e = await db.get(ServiceEquipment, r.json()["id"])
    assert e.serial_key == "00123/A-7"
    assert e.created_by is not None


async def test_mukerrer_seri_409_gerekceyle_201(sef, db) -> None:
    hesap = await _musteri(db, "Mükerrer A.Ş.")
    temel = {"birim": "GUVENLIK", "equipment_type": "XRAY", "account_id": hesap.id}
    r1 = await sef.post(URL, json={**temel, "brand": "SMITHS", "serial_no": "abc-001"})
    assert r1.status_code == 201
    once = await _denetim_sayisi(db)

    # Marka yazımı ve seri boşluğu farklı — aynı anahtar.
    r2 = await sef.post(URL, json={**temel, "brand": "Smiths", "serial_no": " ABC-001 "})
    assert r2.status_code == 409, r2.text
    assert r1.json()["id"] in r2.json()["detail"]["mevcut"]
    assert await _denetim_sayisi(db) == once  # rollback: yarım işlem loglanmaz

    # Farklı tip mükerrer değildir.
    r3 = await sef.post(
        URL,
        json={
            **temel,
            "equipment_type": "KAPI_DEDEKTORU",
            "brand": "Smiths",
            "serial_no": "ABC-001",
        },
    )
    assert r3.status_code == 201

    r4 = await sef.post(
        URL,
        json={
            **temel,
            "brand": "Smiths",
            "serial_no": "ABC-001",
            "duplicate_ack_reason": "Farklı cihaz, etiket hatası",
        },
    )
    assert r4.status_code == 201, r4.text


async def test_mukerrer_baska_birimde_kimlik_vermez(sef, db, ekipman_ac) -> None:
    hesap = await _musteri(db, "Başka Birim Müşteri")
    await ekipman_ac(birim="HABERLESME", tip="XRAY", seri="GIZLI-1", brand="X", musteri=hesap)
    r = await sef.post(
        URL,
        json={
            "birim": "GUVENLIK",
            "equipment_type": "XRAY",
            "account_id": hesap.id,
            "brand": "X",
            "serial_no": "gizli-1",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["mevcut"] == []
    assert r.json()["detail"]["kapsam_disi"] == 1


async def test_surum_uyusmazligi_409(sef, db) -> None:
    hesap = await _musteri(db, "Sürüm")
    r = await sef.post(
        URL, json={"birim": "GUVENLIK", "equipment_type": "XRAY", "account_id": hesap.id}
    )
    kimlik, surum = r.json()["id"], r.json()["version"]
    assert (
        await sef.patch(f"{URL}/{kimlik}", json={"version": surum, "zone": "A"})
    ).status_code == 200
    r2 = await sef.patch(f"{URL}/{kimlik}", json={"version": surum, "zone": "B"})
    assert r2.status_code == 409
    e = await db.get(ServiceEquipment, kimlik)
    await db.refresh(e)
    assert e.zone == "A"


async def test_hesap_adres_irtibat_tutarliligi(sef, db, lokasyon_ac) -> None:
    hesap_a = await _musteri(db, "Hesap A")
    hesap_b = await _musteri(db, "Hesap B")
    tesis_a = await lokasyon_ac(hesap_a, ad="A Tesisi")
    tesis_b = await lokasyon_ac(hesap_b, ad="B Tesisi")
    kisi_a = Contact(account_id=hesap_a.id, full_name="Ali Veli")
    db.add(kisi_a)
    await db.commit()

    # Başka hesabın adresi 400.
    r = await sef.post(
        URL,
        json={
            "birim": "GUVENLIK",
            "equipment_type": "XRAY",
            "account_id": hesap_a.id,
            "address_id": tesis_b.id,
        },
    )
    assert r.status_code == 400

    r = await sef.post(
        URL,
        json={
            "birim": "GUVENLIK",
            "equipment_type": "XRAY",
            "account_id": hesap_a.id,
            "address_id": tesis_a.id,
            "contact_id": kisi_a.id,
        },
    )
    assert r.status_code == 201
    kart = r.json()
    assert kart["lokasyon_adi"] == "A Tesisi"
    assert kart["irtibat_adi"] == "Ali Veli"

    # Hesap değişince eski adres/irtibat kalmaz.
    r = await sef.patch(
        f"{URL}/{kart['id']}", json={"version": kart["version"], "account_id": hesap_b.id}
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_id"] == hesap_b.id
    assert r.json()["address_id"] is None
    assert r.json()["contact_id"] is None


async def test_tarih_kurallari_400(sef, db) -> None:
    hesap = await _musteri(db, "Tarih")
    temel = {"birim": "GUVENLIK", "equipment_type": "XRAY", "account_id": hesap.id}
    r = await sef.post(
        URL, json={**temel, "warranty_start": "2025-05-01", "warranty_end": "2025-01-01"}
    )
    assert r.status_code == 400
    # FakeClock 2026-01-01: gelecekteki kurulum reddedilir.
    r = await sef.post(URL, json={**temel, "install_date": "2026-03-01"})
    assert r.status_code == 400
    r = await sef.post(URL, json={**temel, "lifecycle_status": "HURDA"})
    assert r.status_code == 400


async def test_pasif_aktif_gerekce(sef, db) -> None:
    hesap = await _musteri(db, "Pasif")
    r = await sef.post(
        URL, json={"birim": "GUVENLIK", "equipment_type": "XRAY", "account_id": hesap.id}
    )
    kimlik = r.json()["id"]
    assert (await sef.post(f"{URL}/{kimlik}/pasif", json={"gerekce": ""})).status_code == 400
    r = await sef.post(f"{URL}/{kimlik}/pasif", json={"gerekce": "Hatalı kayıt"})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (
        await sef.post(f"{URL}/{kimlik}/pasif", json={"gerekce": "Yine pasif"})
    ).status_code == 409
    # Pasif kayıt listede varsayılan olarak görünmez.
    liste = await sef.get(URL)
    assert kimlik not in [s["id"] for s in liste.json()]
    liste = await sef.get(URL, params={"pasifler_dahil": "true"})
    assert kimlik in [s["id"] for s in liste.json()]
    r = await sef.post(f"{URL}/{kimlik}/aktif", json={"gerekce": "Yanlışlıkla pasif"})
    assert r.status_code == 200 and r.json()["is_active"] is True


# --- TS-055: yaşam döngüsü ve "Serviste" rozeti -------------------------------------


async def test_durum_gerekce_makine_ve_kurulum_tarihi(sef, db) -> None:
    hesap = await _musteri(db, "Durum")
    r = await sef.post(
        URL, json={"birim": "GUVENLIK", "equipment_type": "XRAY", "account_id": hesap.id}
    )
    kimlik = r.json()["id"]
    assert r.json()["lifecycle_status"] == "BILINMIYOR"
    assert "KURULU" in r.json()["sonraki_durumlar"]

    r = await sef.post(f"{URL}/{kimlik}/durum", json={"hedef": "KURULU"})
    assert r.status_code == 400
    e = await db.get(ServiceEquipment, kimlik)
    await db.refresh(e)
    assert e.lifecycle_status == "BILINMIYOR"

    r = await sef.post(
        f"{URL}/{kimlik}/durum", json={"hedef": "KURULU", "gerekce": "Kurulum yapıldı"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle_status"] == "KURULU"
    assert r.json()["install_date"] == "2026-01-01"

    # KURULU → HURDA makinede yok.
    r = await sef.post(f"{URL}/{kimlik}/durum", json={"hedef": "HURDA", "gerekce": "Hurdaya ayır"})
    assert r.status_code == 409


async def test_hurda_acik_isi_silmez_uyarir_ve_serviste_hesaplanir(
    sef, db, ekipman_ac, servis_isi_ac
) -> None:
    e = await ekipman_ac(seri="SRV-1", lifecycle_status="KURULU")
    so = await servis_isi_ac(tur="ARIZA", equipment_id=e.id)
    kart = (await sef.get(f"{URL}/{e.id}")).json()
    assert kart["serviste"] is True
    assert kart["acik_is_sayisi"] == 1
    kpi = await sef.get(URL, params={"kpi": "serviste"})
    assert [s["id"] for s in kpi.json()] == [e.id]

    r = await sef.post(f"{URL}/{e.id}/durum", json={"hedef": "DEVRE_DISI", "gerekce": "Söküldü"})
    assert r.status_code == 200
    assert r.json()["uyarilar"] and so.so_no in r.json()["uyarilar"][0]
    r = await sef.post(f"{URL}/{e.id}/durum", json={"hedef": "HURDA", "gerekce": "Onarılamaz"})
    assert r.status_code == 200
    await db.refresh(so)
    assert so.is_deleted is False and so.status == "MUSTERI_TALEBI"


async def test_toplu_durum_hepsi_ya_da_hicbiri(sef, db, ekipman_ac) -> None:
    a = await ekipman_ac(seri="T-1", lifecycle_status="BILINMIYOR")
    b = await ekipman_ac(seri="T-2", lifecycle_status="KURULU")
    yabanci = await ekipman_ac(birim="HABERLESME", seri="T-3")

    # KURULU → HURDA geçersiz: hiçbiri değişmez.
    r = await sef.post(
        f"{URL}/toplu-durum",
        json={"idler": [a.id, b.id], "hedef": "HURDA", "gerekce": "Toplu hurda"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["ekipmanlar"] == [b.id]
    await db.refresh(a)
    assert a.lifecycle_status == "BILINMIYOR"

    # Kapsam dışı kimlik: 404, hiçbiri değişmez.
    r = await sef.post(
        f"{URL}/toplu-durum",
        json={"idler": [a.id, yabanci.id], "hedef": "DEVRE_DISI", "gerekce": "Toplu"},
    )
    assert r.status_code == 404
    await db.refresh(a)
    assert a.lifecycle_status == "BILINMIYOR"

    r = await sef.post(
        f"{URL}/toplu-durum",
        json={"idler": [a.id, b.id], "hedef": "DEVRE_DISI", "gerekce": "Tesis kapandı"},
    )
    assert r.status_code == 200, r.text
    assert {s["lifecycle_status"] for s in r.json()} == {"DEVRE_DISI"}
    assert (
        await sef.post(f"{URL}/toplu-durum", json={"idler": list(range(1, 202)), "hedef": "KURULU"})
    ).status_code == 422


# --- TS-053: liste, KPI = liste, Excel ----------------------------------------------


async def test_kpi_sayisi_liste_toplamina_esit(sef, ekipman_ac) -> None:
    await ekipman_ac(seri="K-1", tip="XRAY")
    await ekipman_ac(seri=None, tip="KAPI_DEDEKTORU")
    await ekipman_ac(seri="K-3", tip="XRAY", warranty_end=date(2027, 1, 1))
    await ekipman_ac(birim="HABERLESME", seri="K-4")  # kapsam dışı

    ozet = (await sef.get(f"{URL}/ozet")).json()
    degerler = {k["kod"]: k["deger"] for k in ozet}
    assert degerler["toplam"] == 3
    assert degerler["xray"] == 2
    assert degerler["seri_eksik"] == 1
    for k in ozet:
        r = await sef.get(URL, params={"kpi": k["kod"]})
        assert int(r.headers["X-Toplam-Kayit"]) == k["deger"], k["kod"]
    assert (await sef.get(URL, params={"kpi": "yok"})).status_code == 400


async def test_liste_suzgec_ve_sayfalama(sef, db, ekipman_ac, lokasyon_ac) -> None:
    hesap = await _musteri(db, "Akyaka Güvenlik")
    tesis = await lokasyon_ac(hesap, ad="Akyaka AVM")
    for i in range(7):
        await ekipman_ac(seri=f"P-{i:03d}", musteri=hesap, lokasyon=tesis, model="SC-5030 A")
    sayfa1 = await sef.get(URL, params={"limit": 5})
    assert sayfa1.headers["X-Toplam-Kayit"] == "7"
    sayfa2 = await sef.get(URL, params={"limit": 5, "offset": 5})
    kimlikler = {s["id"] for s in sayfa1.json()} | {s["id"] for s in sayfa2.json()}
    assert len(kimlikler) == 7

    assert (await sef.get(URL, params={"model": "SC 5030 A"})).headers["X-Toplam-Kayit"] == "7"
    assert (await sef.get(URL, params={"q": "p-003"})).headers["X-Toplam-Kayit"] == "1"
    assert (await sef.get(URL, params={"q": "akyaka"})).headers["X-Toplam-Kayit"] == "7"
    assert (await sef.get(URL, params={"lokasyonsuz": "true"})).headers["X-Toplam-Kayit"] == "0"
    satir = sayfa1.json()[0]
    assert satir["hesap_unvan"] == "Akyaka Güvenlik" and satir["lokasyon_adi"] == "Akyaka AVM"


async def test_excel_satir_sayisi_ve_metin_seri(sef, db, ekipman_ac) -> None:
    await ekipman_ac(seri="00123")
    await ekipman_ac(seri="=1+1")
    await ekipman_ac(seri="X-9", tip="KAPI_DEDEKTORU")
    liste = await sef.get(URL, params={"tip": "XRAY"})
    r = await sef.get(f"{URL}/liste.xlsx", params={"tip": "XRAY"})
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.content)).active
    satirlar = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(satirlar) == int(liste.headers["X-Toplam-Kayit"]) == 2
    seriler = {s[5] for s in satirlar}
    assert "00123" in seriler and "=1+1" in seriler  # metin; formül değil
    denetim = await db.scalar(
        select(AuditLog).where(
            AuditLog.entity == "service_equipment", AuditLog.action == "disaaktar"
        )
    )
    assert denetim.new_value["satir"] == 2


# --- TS-054: seri ile öneri -----------------------------------------------------------


async def test_seri_onerisi_tek_belirsiz_kapsam(sef, db, ekipman_ac, lokasyon_ac) -> None:
    hesap = await _musteri(db, "Öneri")
    tesis = await lokasyon_ac(hesap, ad="Öneri Tesisi")
    e = await ekipman_ac(seri="ABC-001", musteri=hesap, lokasyon=tesis)
    r = (await sef.get(f"{URL}/oneri", params={"seri": " abc-001 "})).json()
    assert r["durum"] == "TEK" and r["ekipman"]["id"] == e.id
    assert r["ekipman"]["lokasyon_adi"] == "Öneri Tesisi"

    # Sıfır ve ayraç korunur.
    await ekipman_ac(seri="00123")
    assert (await sef.get(f"{URL}/oneri", params={"seri": "123"})).json()["durum"] == "YOK"
    await ekipman_ac(seri="AB-1")
    assert (await sef.get(f"{URL}/oneri", params={"seri": "AB1"})).json()["durum"] == "YOK"

    # Başka birimin kaydı öneri vermez ve varlığını sızdırmaz.
    await ekipman_ac(birim="HABERLESME", seri="GIZ-9")
    assert (await sef.get(f"{URL}/oneri", params={"seri": "GIZ-9"})).json()["durum"] == "YOK"

    await ekipman_ac(seri="abc-001", duplicate_ack_reason="farklı cihaz")
    r = (await sef.get(f"{URL}/oneri", params={"seri": "ABC-001"})).json()
    assert r["durum"] == "BELIRSIZ" and r["ekipman"] is None


async def test_seri_ile_bul_hesap_sarti(db, ekipman_ac) -> None:
    a = await _musteri(db, "S-A")
    b = await _musteri(db, "S-B")
    e = await ekipman_ac(seri="Z-1", musteri=a)
    assert (await svc.seri_ile_bul(db, "z-1", account_id=a.id)).ekipman_id == e.id
    assert (await svc.seri_ile_bul(db, "z-1", account_id=b.id)).durum == "YOK"


# --- TS-056: garanti ve sözleşme bağı -----------------------------------------------------


async def test_toplu_garanti_onizleme_uygulama_belge_korunur(sef, db, ekipman_ac, urun_ac) -> None:
    urun = await urun_ac("XR-URUN", "YOK", warranty_months=12)
    hesap_disi = await ekipman_ac(seri="G-1", install_date=date(2024, 1, 31), product_id=urun.id)
    varsayilan = await ekipman_ac(seri="G-2", delivery_date=date(2024, 3, 1))
    tarihsiz = await ekipman_ac(seri="G-3")
    belge = await ekipman_ac(
        seri="G-4",
        install_date=date(2024, 1, 1),
        warranty_source="BELGE",
    )

    onizleme = (await sef.post(f"{URL}/garanti/toplu-hesapla", json={})).json()
    assert onizleme["uygulandi"] is False
    assert onizleme["satir_sayisi"] == 2
    assert onizleme["baslangic_tarihsiz"] == 1
    await db.refresh(hesap_disi)
    assert hesap_disi.warranty_end is None  # önizleme yazmaz

    uygulama = (await sef.post(f"{URL}/garanti/toplu-hesapla?uygula=true", json={})).json()
    assert uygulama["satir_sayisi"] == onizleme["satir_sayisi"]
    for e in (hesap_disi, varsayilan, tarihsiz, belge):
        await db.refresh(e)
    assert hesap_disi.warranty_end == date(2025, 1, 31)
    assert hesap_disi.warranty_source == "HESAPLANDI"
    assert varsayilan.warranty_end == date(2026, 3, 1)  # 24 ay (ayar)
    assert tarihsiz.warranty_end is None
    assert belge.warranty_end is None and belge.warranty_source == "BELGE"

    kart = (await sef.get(f"{URL}/{varsayilan.id}")).json()
    assert kart["garanti_durumu"] == "GECERLI"
    kart = (await sef.get(f"{URL}/{hesap_disi.id}")).json()
    assert kart["garanti_durumu"] == "BITTI"
    kart = (await sef.get(f"{URL}/{tarihsiz.id}")).json()
    assert kart["garanti_durumu"] == "BILINMIYOR"


async def test_sozlesme_bagi_ayri_sayilir(sef, db, ekipman_ac, sozlesme_ac) -> None:
    e1 = await ekipman_ac(seri="B-1")
    e2 = await ekipman_ac(seri="B-2")
    await ekipman_ac(seri="B-3")
    sozlesme = await sozlesme_ac(
        status="AKTIF",
        valid_from=datetime(2025, 6, 1, tzinfo=UTC),
        valid_to=datetime(2026, 6, 1, tzinfo=UTC),
        annual_frequency=4,
    )
    for sira, e in enumerate((e1, e2), start=1):
        db.add(
            MaintenanceContractItem(
                contract_id=sozlesme.id,
                equipment_type="XRAY",
                sira=sira,
                equipment_id=e.id,
                valid_from=datetime(2025, 6, 1, tzinfo=UTC),
            )
        )
    await db.commit()

    kart = (await sef.get(f"{URL}/{e1.id}")).json()
    assert kart["sozlesme_sayisi"] == 1
    assert kart["aktif_sozlesmeler"][0]["sozlesme_no"] == sozlesme.contract_no
    r = await sef.get(URL, params={"sozlesme_id": sozlesme.id})
    assert r.headers["X-Toplam-Kayit"] == "2"
    r = await sef.get(URL, params={"sozlesmesiz": "true"})
    assert r.headers["X-Toplam-Kayit"] == "1"
    sayilar = await svc.bagli_ekipman_sayilari(db, [sozlesme.id], datetime(2026, 1, 1, tzinfo=UTC))
    assert sayilar == {sozlesme.id: 2}
