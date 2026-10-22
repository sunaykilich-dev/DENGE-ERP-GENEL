"""PB üretim motoru, worker ve önizleme (TS-062, E04-06/07/08).

1 cihaz × 1 dönem = 1 PB; aynı tur iki kez koşunca 0 yeni PB (worker yeniden
denemesi güvenli). Önizleme aynı motoru SAVEPOINT içinde koşar ve hiçbir
şey yazmaz. Bozuk/eksik sözleşme gerekçeyle `skipped`'e düşer, diğerleri
üretilir. Worker `bakim_otomatik_uretim=False` iken üretmez.
"""

import re

import pytest
from bakim_yardimci import (
    ONEK,
    PB_DESENI,
    giris,
    hepsini_eslestir,
    ortam_kur,
    pb_isleri,
    pb_sayisi,
    sozlesme_ac,
)
from sqlalchemy import func, select

from app.models import (
    MaintenanceForm,
    MaintenanceFormCheck,
    MaintenanceGenerationRun,
    MaintenancePeriod,
    ServiceOrderSerial,
)
from app.services import settings as ayar_svc
from app.services.teknik_servis import bakim_uretim

pytestmark = pytest.mark.integration


@pytest.fixture
async def kisiler(birimli_kullanici_ac):
    return {
        "sef": await birimli_kullanici_ac("sef_u", "SERVIS_SEF", ["GUVENLIK"]),
        "sef_h": await birimli_kullanici_ac("sefh_u", "SERVIS_SEF", ["HABERLESME"]),
        "tek": await birimli_kullanici_ac(
            "tek_u", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
    }


async def test_iki_xray_uc_kapi_bes_pb_ikinci_tur_sifir(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=2, kapi=3)
    await giris(client, "sef_u")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)

    r = await client.post(f"{ONEK}/uretim")
    assert r.status_code == 200, r.text
    assert r.json()["generated"] == 5  # yalnız vadesi gelen ilk dönem (01.01.2026)
    isler = await pb_isleri(db, s["id"])
    assert len(isler) == 5
    assert all(re.match(PB_DESENI, so.so_no) for so in isler)
    assert all(so.status == "PLANLAMADA" and so.kategori == "PLANLI_BAKIM" for so in isler)
    assert all(so.created_by == kisiler["sef"].id for so in isler)  # tetikleyen kayıtlı
    assert {so.so_no[3:9] for so in isler} == {"202601"}  # numara = dönemin hedef ayı
    # Şablon maddeleri forma kopyalandı: X-Ray 11, kapı dedektörü 10.
    sayilar = sorted(
        (
            await db.execute(
                select(MaintenanceForm.template_code, func.count(MaintenanceFormCheck.id))
                .join(MaintenanceFormCheck, MaintenanceFormCheck.form_id == MaintenanceForm.id)
                .group_by(MaintenanceForm.id, MaintenanceForm.template_code)
            )
        ).all()
    )
    assert sayilar == [("KAPI_DEDEKTORU", 10)] * 3 + [("XRAY", 11)] * 2
    seriler = (await db.scalars(select(ServiceOrderSerial.seri_no))).all()
    assert len(seriler) == 5  # PB serisi kütükten, servis işi seri tablosunda

    r = await client.post(f"{ONEK}/uretim")
    assert r.json()["generated"] == 0
    assert await pb_sayisi(db) == 5
    tur = await db.scalar(
        select(MaintenanceGenerationRun).order_by(MaintenanceGenerationRun.id.desc()).limit(1)
    )
    assert tur.tetik == "ELLE" and tur.created_by == kisiler["sef"].id


async def test_on_conflict_ayni_kalem_donem_ikinci_ekleme_none(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    """Ön sorguyu atlayan yarış: `ON CONFLICT ... WHERE tur='PB'` çift PB'yi keser."""
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_u")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    await client.post(f"{ONEK}/uretim")
    [so] = await pb_isleri(db, s["id"])
    from app.clock import FakeClock
    from app.models import MaintenanceContract, MaintenanceContractItem, ServiceEquipment

    sozlesme = await db.get(MaintenanceContract, s["id"])
    donem = await db.get(MaintenancePeriod, so.maintenance_period_id)
    kalem = await db.get(MaintenanceContractItem, so.contract_item_id)
    ekipman = await db.get(ServiceEquipment, kalem.equipment_id)
    sonuc = await bakim_uretim._pb_ekle(
        db, sozlesme, donem, kalem, ekipman, user=None, clock=FakeClock()
    )
    assert sonuc is None
    await db.rollback()
    assert await pb_sayisi(db) == 1


async def test_onizleme_yazmaz(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=1)
    await giris(client, "sef_u")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    once_tur = await db.scalar(select(func.count(MaintenanceGenerationRun.id)))
    r = await client.post(f"{ONEK}/uretim/onizleme")
    assert r.status_code == 200, r.text
    veri = r.json()
    assert veri["uretilecek"][0]["pb_sayisi"] == 2
    assert veri["uretilecek"][0]["contract_no"] == s["contract_no"]
    assert await pb_sayisi(db) == 0
    assert await db.scalar(select(func.count(MaintenanceGenerationRun.id))) == once_tur


async def test_ekipmansiz_kalem_gerekceyle_atlanir_digerleri_uretilir(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_u")
    eksik = await sozlesme_ac(client, o)  # eşleştirilmedi → EKIPMAN_YOK
    o2 = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0, ad="İkinci Müşteri")
    tam = await sozlesme_ac(client, o2)
    await hepsini_eslestir(client, tam["id"], o2)
    suresi = await sozlesme_ac(
        client, o2, kapsam={"XRAY": 0}, baslangic="2024-01-01", bitis="2025-06-01"
    )
    r = await client.post(f"{ONEK}/uretim")
    assert r.status_code == 200
    veri = r.json()
    assert veri["generated"] == 1
    nedenler = {a["contract_no"]: a["neden_kodu"] for a in veri["skipped"]}
    assert nedenler[eksik["contract_no"]] == "EKIPMAN_YOK"
    assert nedenler[suresi["contract_no"]] == "SURESI_DOLMUS"


async def test_worker_ayar_kapaliyken_uretmez(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_u")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    from app.clock import FakeClock

    ozet = await bakim_uretim.pb_uretimi_gorevi(db, FakeClock())
    await db.commit()
    assert "kapalı" in ozet
    assert await pb_sayisi(db) == 0

    await ayar_svc.set_many(db, {"bakim_otomatik_uretim": True}, None)
    await db.commit()
    ozet = await bakim_uretim.pb_uretimi_gorevi(db, FakeClock())
    await db.commit()
    assert ozet.startswith("1 PB")
    [so] = await pb_isleri(db, s["id"])
    assert so.created_by is None  # worker = sistem
    tur = await db.scalar(
        select(MaintenanceGenerationRun).where(MaintenanceGenerationRun.tetik == "WORKER")
    )
    assert tur is not None and tur.created_by is None


async def test_eksik_pb_idempotent_ve_rbac(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=2, kapi=0)
    await giris(client, "sef_u")
    s = await sozlesme_ac(client, o)
    donemler = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}/donemler")).json()
    ikinci = donemler[1]  # 01.07.2026: vade penceresi dışında, elle tamamlanır
    await hepsini_eslestir(client, s["id"], o)
    yol = f"{ONEK}/sozlesmeler/{s['id']}/donemler/{ikinci['id']}/eksik-pb"
    r = await client.post(yol)
    assert r.status_code == 200, r.text
    assert r.json()["generated"] == 2
    assert (await client.post(yol)).json()["generated"] == 0

    await giris(client, "tek_u")
    assert (await client.post(yol)).status_code == 403
    assert (await client.post(f"{ONEK}/uretim")).status_code == 403
    await giris(client, "sefh_u")
    assert (await client.post(yol)).status_code == 404


async def test_elle_uretim_kullanici_kapsamiyla_sinirli(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_u")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    await giris(client, "sefh_u")  # HABERLESME şefi GUVENLIK sözleşmesini üretemez
    r = await client.post(f"{ONEK}/uretim")
    assert r.status_code == 200 and r.json()["generated"] == 0
    assert r.json()["skipped"] == []  # başka birimin sözleşmesi listede de görünmez
    assert await pb_sayisi(db) == 0


async def test_hedef_tarih_elle_gerekceyle_ve_yeniden_hesaplanmaz(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_u")
    s = await sozlesme_ac(client, o)
    donem = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}/donemler")).json()[1]
    yol = f"{ONEK}/sozlesmeler/{s['id']}/donemler/{donem['id']}/hedef-tarih"
    r = await client.patch(yol, json={"hedef_tarih": "2026-08-15", "gerekce": ""})
    assert r.status_code == 422  # gerekçe boş
    r = await client.patch(yol, json={"hedef_tarih": "2026-08-15", "gerekce": "Müşteri talebi"})
    assert r.status_code == 200 and r.json()["target_manual"] is True
    # Frekans değişse de elle tarih korunur.
    detay = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}")).json()
    r = await client.patch(
        f"{ONEK}/sozlesmeler/{s['id']}",
        json={"version": detay["version"], "annual_frequency": 2, "notes": "y"},
    )
    assert r.status_code == 200
    kayit = await db.get(MaintenancePeriod, donem["id"])
    await db.refresh(kayit)
    assert kayit.target_date.isoformat() == "2026-08-15"
