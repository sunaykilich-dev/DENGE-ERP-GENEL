"""Ekipman değişiklik geçmişi, birleşik geçmiş, KVKK ve görev bağlantısı
(TS-051, TS-052, TS-057)."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.models import Account, AuditLog, ServiceOrderSerial, ServiceTimeEntry
from app.services import kvkk
from app.services.teknik_servis import ekipman as svc

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


async def _hesap(db, ad: str) -> Account:
    h = Account(title=ad, is_musteri=True)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def test_seri_degisikligi_gecmiste_kullanici_ile_gorunur(
    birimli_kullanici_ac, giris, db
) -> None:
    await birimli_kullanici_ac("sef_gc", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("tekn_gc", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    sef = await giris("sef_gc")
    hesap = await _hesap(db, "Geçmiş A.Ş.")
    r = await sef.post(
        URL,
        json={
            "birim": "GUVENLIK",
            "equipment_type": "XRAY",
            "account_id": hesap.id,
            "serial_no": "ESKI-1",
            "contact_name_raw": "Saha Sorumlusu Ayşe",
        },
    )
    kart = r.json()
    r = await sef.patch(
        f"{URL}/{kart['id']}",
        json={"version": kart["version"], "serial_no": "YENI-1", "contact_name_raw": "Mehmet Bey"},
    )
    assert r.status_code == 200, r.text

    # Teknisyen (ekipman.gor) geçmişi görür; sistem.denetim gerekmez.
    tekn = await giris("tekn_gc")
    satirlar = (await tekn.get(f"{URL}/{kart['id']}/degisiklikler")).json()
    seri = next(s for s in satirlar if s["eylem"] == "guncelle")
    assert seri["eski"] == {"serial_no": "ESKI-1"}
    assert seri["yeni"] == {"serial_no": "YENI-1"}
    assert seri["kullanici"] == "Sef_Gc"
    assert seri["kisisel"] is False
    irtibat = next(s for s in satirlar if s["eylem"] == "guncelle.irtibat")
    assert irtibat["kisisel"] is True
    assert irtibat["yeni"] == {"contact_name_raw": "Mehmet Bey"}
    # İrtibat ve seri AYRI satırda.
    assert "contact_name_raw" not in seri["yeni"]

    # KVKK: hesap anonimleştirilince irtibat değeri gider, seri geçmişi kalır.
    await kvkk.hesabi_anonimlestir(db, hesap.id, clock=_Saat(), gerekce="Silme talebi #1")
    await db.commit()
    from app.models import ServiceEquipment

    e = await db.get(ServiceEquipment, kart["id"])
    await db.refresh(e)
    assert e.contact_name_raw is None
    assert e.serial_no == "YENI-1"
    satirlar = (await tekn.get(f"{URL}/{kart['id']}/degisiklikler")).json()
    seri = next(s for s in satirlar if s["eylem"] == "guncelle")
    assert seri["yeni"] == {"serial_no": "YENI-1"}
    irtibat = next(s for s in satirlar if s["eylem"] == "guncelle.irtibat")
    assert irtibat["yeni"] == kvkk.DEGER_SILINDI


class _Saat:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


async def test_degisiklik_ucu_salt_okunur() -> None:
    from app.main import app

    yollar = app.openapi()["paths"]
    yol = yollar[f"{URL}/{{ekipman_id}}/degisiklikler"]
    assert set(yol) == {"get"}


async def test_birlesik_gecmis_sure_eksik_ve_metin_eslesmesi(
    birimli_kullanici_ac, giris, db, ekipman_ac, servis_isi_ac
) -> None:
    sef_kul = await birimli_kullanici_ac("sef_bg", "SERVIS_SEF", ["GUVENLIK"])
    sef = await giris("sef_bg")
    hesap = await _hesap(db, "Birleşik Geçmiş")
    e = await ekipman_ac(seri="KIM-1", musteri=hesap)
    sureli = await servis_isi_ac(musteri=hesap, equipment_id=e.id, konu="Süreli iş")
    suresiz = await servis_isi_ac(musteri=hesap, equipment_id=e.id, konu="Süresiz iş")
    metin = await servis_isi_ac(musteri=hesap, konu="Göçten gelen iş")
    db.add(ServiceOrderSerial(service_order_id=metin.id, seri_no="kim-1", seri_norm="KIM-1"))
    an = datetime(2025, 12, 1, 9, tzinfo=UTC)
    db.add_all(
        [
            ServiceTimeEntry(
                service_order_id=sureli.id,
                user_id=sef_kul.id,
                faaliyet="SAHA",
                started_at=an,
                ended_at=datetime(2025, 12, 1, 10, 30, tzinfo=UTC),
                kaynak="MANUEL",
                girildi_at=an,
            ),
            ServiceTimeEntry(
                service_order_id=sureli.id,
                user_id=sef_kul.id,
                faaliyet="MOLA",
                started_at=datetime(2025, 12, 1, 11, tzinfo=UTC),
                ended_at=datetime(2025, 12, 1, 12, tzinfo=UTC),
                kaynak="MANUEL",
                girildi_at=an,
            ),
        ]
    )
    await db.commit()

    olaylar = (await sef.get(f"{URL}/{e.id}/gecmis")).json()
    isler = {o["kaynak_id"]: o for o in olaylar if o["kaynak"] == "service_orders"}
    assert isler[sureli.id]["sure_dakika"] == 90  # MOLA hariç
    assert isler[sureli.id]["sure_eksik"] is False
    assert isler[suresiz.id]["sure_dakika"] is None
    assert isler[suresiz.id]["sure_eksik"] is True
    assert isler[metin.id]["eslesme"] == "METIN"
    assert isler[sureli.id]["eslesme"] == "KIMLIK"
    tarihler = [o["tarih"] for o in olaylar]
    assert tarihler == sorted(tarihler, reverse=True)


async def test_maliyet_anahtari_yalniz_maliyet_gorene(
    birimli_kullanici_ac, kullanici_ac, giris, db, ekipman_ac
) -> None:
    await birimli_kullanici_ac("sef_ml", "SERVIS_SEF", ["GUVENLIK"])
    await kullanici_ac("admin_ml", "ADMIN")
    e = await ekipman_ac(seri="ML-1")

    async def _parca(db_, ekipman, user):
        return [
            {
                "tarih": datetime(2025, 5, 1, tzinfo=UTC),
                "tur": "PARCA",
                "baslik": "Parça",
                "kaynak": "stock_movements",
                "kaynak_id": 1,
                "maliyet": 125.5,
            }
        ]

    svc.gecmis_kaynagi_kaydet(_parca)
    try:
        sef = await giris("sef_ml")
        olay = next(
            o for o in (await sef.get(f"{URL}/{e.id}/gecmis")).json() if o["tur"] == "PARCA"
        )
        assert "maliyet" not in olay
        admin = await giris("admin_ml")
        olay = next(
            o for o in (await admin.get(f"{URL}/{e.id}/gecmis")).json() if o["tur"] == "PARCA"
        )
        assert olay["maliyet"] == 125.5
    finally:
        svc.GECMIS_KAYNAKLARI.remove(_parca)


async def test_hata_atilan_yazmada_denetim_yok(birimli_kullanici_ac, giris, db, ekipman_ac) -> None:
    await birimli_kullanici_ac("sef_rb", "SERVIS_SEF", ["GUVENLIK"])
    sef = await giris("sef_rb")
    e = await ekipman_ac(seri="RB-1")
    once = (
        await db.scalars(select(AuditLog.id).where(AuditLog.entity == "service_equipment"))
    ).all()
    r = await sef.post(f"{URL}/{e.id}/durum", json={"hedef": "HURDA", "gerekce": "x"})
    assert r.status_code == 400
    r = await sef.patch(f"{URL}/{e.id}", json={"version": e.version, "lifecycle_status": "HURDA"})
    assert r.status_code in (200, 400)  # alan şemada yok → yok sayılır, değişiklik yok
    sonra = (
        await db.scalars(select(AuditLog.id).where(AuditLog.entity == "service_equipment"))
    ).all()
    assert sonra == once


async def test_gorev_baglantisi_ve_veri_bul(db, ekipman_ac) -> None:
    from app.services import gorevler

    e = await ekipman_ac(seri="GRV-1", contact_name_raw="Zeynep Yılmaz")
    etiket = await gorevler.baglanti_cozumle(db, {("ekipman", e.id)})
    assert etiket[("ekipman", e.id)]["etiket"] == f"#{e.id}"
    assert etiket[("ekipman", e.id)]["yol"] == f"/servis-ekipman/{e.id}"

    sonuc = await kvkk.veri_bul(db, "zeynep yılmaz")
    assert [s["id"] for s in sonuc["servis_ekipmanlari"]] == [e.id]
