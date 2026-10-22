"""Kurulum/toplama işlerinin servis işine bağlanması (TS-120, E06-19).

İş servis işi çekirdeğiyle (`is_emirleri.olustur`) PLANLAMADA açılır ve
`rental_id` ile bağlanır; kiralama + tür başına tek açık iş
(`uq_so_kiralama_tur_acik`). Aşama olayında ekip işin atanmış personelidir,
süre zaman kaydından (kayıt yoksa EKSIK). İş TAMAMLANDI olunca aşama ÖNERİLİR,
otomatik yazılmaz. `work_orders`'a yazım yoktur.
"""

from datetime import datetime

import pytest
from kiralama_ortak import URL, hazir_kiralama, istemci
from sqlalchemy import func, select

from app.models import ServiceOrder, ServiceOrderAssignment, ServiceResult, WorkOrder

pytestmark = pytest.mark.integration


@pytest.fixture
async def ortam(client, kullanici_ac, birimli_kullanici_ac):
    await kullanici_ac("si_yon", "SERVIS_YONETICI")
    await birimli_kullanici_ac("si_op", "SERVIS_OPERASYON", ["GUVENLIK"])
    await birimli_kullanici_ac("si_depo", "KIRALAMA_DEPO", ["GUVENLIK"])
    ist = {ad: await istemci(ad) for ad in ("si_yon", "si_op", "si_depo")}
    yield ist
    for i in ist.values():
        await i.aclose()


async def test_kurulum_isi_acilir_baglanir_ve_ikinci_acik_is_409(ortam, db) -> None:
    ist = ortam["si_yon"]
    h = await hazir_kiralama(db, ist, seri_adet=2, on_ek="SI", sevk=True)
    k = h["k"]
    # İzin: kiralama.yaz + servis.yaz; KIRALAMA_DEPO'da yok → 403.
    r = await ortam["si_depo"].post(f"{URL}/{k['id']}/servis-isi", json={"tur": "KURULUM"})
    assert r.status_code == 403
    r = await ortam["si_op"].post(f"{URL}/{k['id']}/servis-isi", json={"tur": "KURULUM"})
    assert r.status_code == 201, r.text
    so = await db.get(ServiceOrder, r.json()["id"])
    assert so.rental_id == k["id"] and so.tur == "KURULUM" and so.status == "PLANLAMADA"
    assert so.birim == "GUVENLIK" and so.customer_id == h["musteri"].id
    assert k["rental_no"] in so.aciklama and "SI-S0" in so.aciklama and "SI-S1" in so.aciklama
    r = await ist.post(f"{URL}/{k['id']}/servis-isi", json={"tur": "KURULUM"})
    assert r.status_code == 409
    assert (await ist.post(f"{URL}/{k['id']}/servis-isi", json={"tur": "ARIZA"})).status_code == 400
    r = await ist.post(f"{URL}/{k['id']}/servis-isi", json={"tur": "TOPLAMA"})
    assert r.status_code == 201
    kart = (await ist.get(f"{URL}/{k['id']}")).json()
    assert {s["tur"] for s in kart["servis_isleri"]} == {"KURULUM", "TOPLAMA"}
    assert await db.scalar(select(func.count()).select_from(WorkOrder)) == 0


async def test_asama_ekibi_isin_atamasi_sure_eksik_ve_tamamlaninca_oneri(ortam, db, client) -> None:
    from app.services.teknik_servis import is_emirleri

    ist = ortam["si_yon"]
    h = await hazir_kiralama(db, ist, toplu_adet=3, on_ek="SA", sevk=True)
    k = h["k"]
    r = await ist.post(f"{URL}/{k['id']}/servis-isi", json={"tur": "KURULUM"})
    so = await db.get(ServiceOrder, r.json()["id"])
    from app.models import User

    kisi = await db.scalar(select(User).where(User.username == "si_op"))
    db.add(
        ServiceOrderAssignment(
            service_order_id=so.id,
            user_id=kisi.id,
            rol="TEKNISYEN",
            is_lead=True,
            assigned_at=datetime.fromisoformat("2026-01-01T09:00:00+00:00"),
        )
    )
    # Sonuçsuz TAMAMLANDI yok (servis işi kuralı): sonuç kaydı.
    db.add(
        ServiceResult(
            service_order_id=so.id,
            sonuc="COZULDU",
            cozum_kanali="YERINDE",
            yapilan_islem="Kurulum yapıldı",
        )
    )
    await db.commit()
    # Tamamlanınca öneri (aşama yazılmaz).
    await db.refresh(so)
    await is_emirleri.durum_degistir(
        db, so, "TAMAMLANDI", kaynak="sonuc", user=None, clock=client.clock
    )
    await db.commit()
    kart = (await ist.get(f"{URL}/{k['id']}")).json()
    assert kart["status"] == "SEVK_EDILDI"
    assert kart["onerilen_asama"] == "KURULUM_YAPILDI"
    gecmis = (await ist.get(f"{URL}/{k['id']}/gecmis")).json()
    oneri = [o for o in gecmis if o["alan"] == "asama_onerisi"]
    assert oneri and oneri[0]["yeni"]["oneri"] == "KURULUM_YAPILDI"
    # Onayı kiralama.asama sahibi verir; olay ekibi işin ataması, süre EKSIK.
    r = await ortam["si_op"].post(
        f"{URL}/{k['id']}/asama", json={"asama": "KURULUM_YAPILDI", "service_order_id": so.id}
    )
    assert r.status_code == 403  # SERVIS_OPERASYON'da kiralama.asama yok
    r = await ortam["si_depo"].post(
        f"{URL}/{k['id']}/asama", json={"asama": "KURULUM_YAPILDI", "service_order_id": so.id}
    )
    assert r.status_code == 200, r.text
    assert r.json()["onerilen_asama"] is None
    olay = next(o for o in (await ist.get(f"{URL}/{k['id']}/gecmis")).json() if o["tur"] == "ASAMA")
    assert olay["ekip_user_ids"] == [kisi.id]
    assert olay["service_order_id"] == so.id
    assert olay["yeni"]["sure_durumu"] in ("EKSIK", "BEKLENMIYOR")
    assert olay["yeni"]["kisi_saat_dk"] is None
    # Bağlı olmayan iş seçilemez.
    r = await ortam["si_depo"].post(
        f"{URL}/{k['id']}/asama", json={"asama": "TOPLANDI", "service_order_id": 987654}
    )
    assert r.status_code == 400


async def test_iptalde_bagli_acik_is_iptal_edilir(ortam, db) -> None:
    ist = ortam["si_yon"]
    h = await hazir_kiralama(db, ist, toplu_adet=1, on_ek="SC")
    k = h["k"]
    r = await ist.post(f"{URL}/{k['id']}/servis-isi", json={"tur": "KURULUM"})
    assert r.status_code == 201
    r = await ist.post(f"{URL}/{k['id']}/iptal", json={"gerekce": "Etkinlik iptal"})
    assert r.status_code == 200, r.text
    so = await db.scalar(select(ServiceOrder).where(ServiceOrder.rental_id == k["id"]))
    await db.refresh(so)
    assert so.status == "IPTAL" and "Etkinlik iptal" in so.cancel_reason
