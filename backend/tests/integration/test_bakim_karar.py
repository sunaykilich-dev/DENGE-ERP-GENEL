"""Sözleşme karar tarihinden bakım takvimi (2026-11-05, `bakim_karar`).

Korunan kurallar: karar tarihi = başlangıç, bitiş verilmezse +12 ay; bakım
ayları yıllık adede göre eşit aralıkla (tek kaynak `bakim.donem_plani`);
önizleme hiçbir şey yazmaz; güncel döngüden önceki geçmiş dönemler ve güncel
döngüde `yapilan_adet` kadarı "sistem öncesi" (GOC_BASLANGIC) kapanır, kalan
geçmiş dönem gecikmiş kalır; PB'ler hemen değil, açılış penceresinde worker
ile açılır (cihaz başına 1). Toplu girişte satır hatası diğerlerini durdurmaz,
kapsam dışı sözleşme "bulunamadı" olarak döner ve değişmez.
"""

from datetime import UTC, date, datetime

import pytest
from bakim_yardimci import ONEK, giris, hepsini_eslestir, ortam_kur, pb_isleri, sozlesme_ac
from sqlalchemy import func, select

from app.models import AuditLog, MaintenanceContract, MaintenancePeriod
from app.services import settings as ayar_svc
from app.services.teknik_servis import bakim_uretim

pytestmark = pytest.mark.integration

BUGUN = datetime(2026, 11, 5, 9, tzinfo=UTC)


@pytest.fixture
async def kisiler(birimli_kullanici_ac, kullanici_ac):
    return {
        "sef": await birimli_kullanici_ac("sef_k", "SERVIS_SEF", ["GUVENLIK"]),
        "sef_h": await birimli_kullanici_ac("sefh_k", "SERVIS_SEF", ["HABERLESME"]),
        "tek": await birimli_kullanici_ac(
            "tek_k", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "yonetim": await kullanici_ac("yonetim_k", "YONETIM"),
    }


async def _donemler(db, sozlesme_id: int) -> list[MaintenancePeriod]:
    return list(
        (
            await db.scalars(
                select(MaintenancePeriod)
                .where(MaintenancePeriod.contract_id == sozlesme_id)
                .order_by(MaintenancePeriod.target_date)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def _tarihsiz_sozlesme(client, o, frekans: int = 3) -> dict:
    return await sozlesme_ac(
        client, o, aktif=False, baslangic=None, bitis=None, annual_frequency=frekans
    )


async def test_karar_tarihi_onizleme_yazmaz_uygula_aylari_hesaplar(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    client.clock.set(BUGUN)
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=2)
    await giris(client, "sef_k")
    s = await _tarihsiz_sozlesme(client, o)
    await hepsini_eslestir(client, s["id"], o)
    denetim_once = await db.scalar(select(func.count(AuditLog.id)))

    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi",
        json={"karar_tarihi": "2026-12-15", "onizleme": True},
    )
    assert r.status_code == 200, r.text
    on = r.json()
    assert on["onizleme"] is True and on["status"] == "AKTIF"
    assert [d["hedef"] for d in on["donemler"]] == ["2026-12-15", "2027-04-15", "2027-08-15"]
    assert on["bitis"] == "2027-12-15"
    # Açılış: hedef − 30 gün (varsayılan `bakim_on_acilis_gun`), bugün henüz değil.
    assert on["donemler"][0]["durum"] == "ILERIDE"
    assert on["donemler"][0]["pb_acilis"] == "2026-11-15"
    assert on["ilk_turda_pb"] == 0 and on["cihaz_sayisi"] == 3 and on["eslesen_cihaz"] == 3

    kayit = await db.get(MaintenanceContract, s["id"])
    await db.refresh(kayit)
    assert kayit.status == "TASLAK" and kayit.decision_date is None and kayit.valid_from is None
    assert await _donemler(db, s["id"]) == []
    assert await db.scalar(select(func.count(AuditLog.id))) == denetim_once

    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi",
        json={"karar_tarihi": "2026-12-15", "version": kayit.version},
    )
    assert r.status_code == 200, r.text
    await db.refresh(kayit)
    assert kayit.status == "AKTIF" and kayit.decision_date == date(2026, 12, 15)
    assert [d.target_date.isoformat() for d in await _donemler(db, s["id"])] == [
        "2026-12-15",
        "2027-04-15",
        "2027-08-15",
    ]
    assert await db.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == "bakim.sozlesme.karar_tarihi")
    )
    detay = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}")).json()
    assert detay["karar_tarihi"] == "2026-12-15" and detay["baslangic"] == "2026-12-15"

    # Hemen PB açılmaz; açılış günü gelince otomatik görev cihaz başına 1 PB açar.
    await ayar_svc.set_many(db, {"bakim_otomatik_uretim": True}, None)
    await db.commit()
    client.clock.set(datetime(2026, 11, 10, 9, tzinfo=UTC))
    await bakim_uretim.pb_uretimi_gorevi(db, client.clock)
    await db.commit()
    assert await pb_isleri(db, s["id"]) == []
    client.clock.set(datetime(2026, 11, 16, 9, tzinfo=UTC))
    ozet = await bakim_uretim.pb_uretimi_gorevi(db, client.clock)
    await db.commit()
    assert ozet.startswith("3 PB"), ozet
    isler = await pb_isleri(db, s["id"])
    assert len(isler) == 3
    assert {so.so_no[3:9] for so in isler} == {"202612"}  # Aralık dönemi


async def test_gecmis_karar_onceki_dongu_ve_yapilan_adet_sistem_oncesi_kalan_gecikmis(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    client.clock.set(BUGUN)
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=1)
    await giris(client, "sef_k")
    s = await _tarihsiz_sozlesme(client, o)
    await hepsini_eslestir(client, s["id"], o)

    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi",
        json={"karar_tarihi": "2025-03-01", "sure_ay": 24, "yapilan_adet": 1},
    )
    assert r.status_code == 200, r.text
    sonuc = r.json()
    durumlar = {d["hedef"]: d["durum"] for d in sonuc["donemler"]}
    assert durumlar == {
        # Önceki döngü (03.2025–03.2026) sistem öncesi.
        "2025-03-01": "SISTEM_ONCESI",
        "2025-07-01": "SISTEM_ONCESI",
        "2025-11-01": "SISTEM_ONCESI",
        # Güncel döngüde 1 bakım yapılmış; kalan iki geçmiş dönem gecikmiş.
        "2026-03-01": "SISTEM_ONCESI",
        "2026-07-01": "GECIKMIS",
        "2026-11-01": "GECIKMIS",
    }
    assert sonuc["sistem_oncesi_kapanan"] == 4
    assert sonuc["gecikmis_donem"] == 2
    assert sonuc["ilk_turda_pb"] == 4  # 2 dönem × 2 cihaz
    kapali = [d for d in await _donemler(db, s["id"]) if d.closed_at is not None]
    assert {d.closing_kind for d in kapali} == {"GOC_BASLANGIC"} and len(kapali) == 4

    # Aynı karar tekrar uygulanınca yeni kapanış olmaz (idempotent).
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi",
        json={"karar_tarihi": "2025-03-01", "sure_ay": 24, "yapilan_adet": 1},
    )
    assert r.status_code == 200 and r.json()["sistem_oncesi_kapanan"] == 0


async def test_toplu_karar_satir_hatasi_digerlerini_durdurmaz_kapsam_disi_bulunamadi(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    client.clock.set(BUGUN)
    o1 = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0, ad="Birinci AVM")
    o2 = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=0, kapi=2, ad="İkinci AVM")
    oh = await ortam_kur(
        db, lokasyon_ac, ekipman_ac, birim="HABERLESME", xray=1, kapi=0, ad="Telsiz Müşterisi"
    )
    await giris(client, "sefh_k")
    sh = await sozlesme_ac(client, oh, aktif=False, birim="HABERLESME", baslangic=None, bitis=None)
    await giris(client, "sef_k")
    s1 = await _tarihsiz_sozlesme(client, o1, frekans=2)
    s2 = await _tarihsiz_sozlesme(client, o2, frekans=4)
    govde = {
        "satirlar": [
            {"contract_no": s1["contract_no"], "karar_tarihi": "2027-01-10"},
            {"sozlesme_id": s2["id"], "karar_tarihi": "2027-02-01", "sure_ay": 12},
            {"contract_no": "YOK-0001", "karar_tarihi": "2027-01-01"},
            {"sozlesme_id": sh["id"], "karar_tarihi": "2027-01-01"},
            {"sozlesme_id": s1["id"], "karar_tarihi": "2027-01-01", "bitis": "2026-12-01"},
        ]
    }
    r = await client.post(f"{ONEK}/karar-tarihleri", json=govde)  # varsayılan önizleme
    assert r.status_code == 200, r.text
    on = r.json()
    assert on["onizleme"] is True
    assert [s["sonuc"] for s in on["satirlar"]] == ["TAMAM", "TAMAM", "HATA", "HATA", "HATA"]
    assert on["satirlar"][2]["hata"] == on["satirlar"][3]["hata"] == "Sözleşme bulunamadı"
    assert "Bitiş" in on["satirlar"][4]["hata"]
    assert on["satirlar"][0]["musteri"] == "Birinci AVM"
    assert [d["hedef"] for d in on["satirlar"][1]["donemler"]] == [
        "2027-02-01",
        "2027-05-01",
        "2027-08-01",
        "2027-11-01",
    ]
    assert on["ozet"]["tamam"] == 2 and on["ozet"]["donem"] == 6
    for sid in (s1["id"], s2["id"], sh["id"]):
        kayit = await db.get(MaintenanceContract, sid)
        await db.refresh(kayit)
        assert kayit.decision_date is None and kayit.status == "TASLAK"

    govde["onizleme"] = False
    r = await client.post(f"{ONEK}/karar-tarihleri", json=govde)
    assert r.status_code == 200, r.text
    assert r.json()["ozet"]["tamam"] == 2
    k1 = await db.get(MaintenanceContract, s1["id"])
    kh = await db.get(MaintenanceContract, sh["id"])
    await db.refresh(k1)
    await db.refresh(kh)
    # Son satır s1'e geçersiz bitiş verdi: o satır geri alındı, ilk satır kaldı.
    assert k1.decision_date == date(2027, 1, 10) and k1.status == "AKTIF"
    assert kh.decision_date is None and kh.status == "TASLAK"


async def test_yillik_takvim_kapsamli_ve_rbac(client, db, kisiler, lokasyon_ac, ekipman_ac):
    client.clock.set(BUGUN)
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=2, kapi=1, ad="Takvim AVM")
    await giris(client, "sef_k")
    s = await _tarihsiz_sozlesme(client, o)
    await hepsini_eslestir(client, s["id"], o)
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi", json={"karar_tarihi": "2026-12-15"}
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"{ONEK}/takvim", params={"yil": 2027})
    assert r.status_code == 200, r.text
    t = r.json()
    [satir] = t["satirlar"]
    assert satir["musteri"] == "Takvim AVM" and satir["karar_tarihi"] == "2026-12-15"
    assert satir["cihaz_sayisi"] == 3 and satir["eslesen_cihaz"] == 3
    dolu = {ay: v for ay, v in satir["aylar"].items() if v}
    assert sorted(dolu) == ["4", "8"]
    assert dolu["4"][0]["durum"] == "ILERIDE"
    assert t["aylar"][3] == {"ay": 4, "donem": 1, "cihaz": 3}
    r = await client.get(f"{ONEK}/takvim", params={"yil": 2026})
    assert [d["hedef"] for d in r.json()["satirlar"][0]["aylar"]["12"]] == ["2026-12-15"]

    await giris(client, "yonetim_k")  # yönetim okur, yazamaz
    assert (await client.get(f"{ONEK}/takvim", params={"yil": 2027})).status_code == 200
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi", json={"karar_tarihi": "2027-01-01"}
    )
    assert r.status_code == 403
    await giris(client, "tek_k")
    assert (await client.get(f"{ONEK}/takvim")).status_code == 403
    r = await client.post(
        f"{ONEK}/karar-tarihleri",
        json={"satirlar": [{"sozlesme_id": s["id"], "karar_tarihi": "2027-01-01"}]},
    )
    assert r.status_code == 403
    await giris(client, "sefh_k")  # başka birimin sözleşmesi takvimde görünmez
    assert (await client.get(f"{ONEK}/takvim", params={"yil": 2027})).json()["satirlar"] == []
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi", json={"karar_tarihi": "2027-01-01"}
    )
    assert r.status_code == 404


async def test_karar_tarihi_eski_surum_409_ve_adet_yoksa_400(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    client.clock.set(BUGUN)
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_k")
    s = await sozlesme_ac(client, o, aktif=False, baslangic=None, bitis=None, annual_frequency=None)
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi", json={"karar_tarihi": "2027-01-01"}
    )
    assert r.status_code == 400 and "Yıllık bakım adedi" in r.json()["detail"]
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi",
        json={"karar_tarihi": "2027-01-01", "yillik_adet": 2, "version": s["version"]},
    )
    assert r.status_code == 200, r.text
    assert [d["hedef"] for d in r.json()["donemler"]] == ["2027-01-01", "2027-07-01"]
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi",
        json={"karar_tarihi": "2027-02-01", "version": s["version"]},
    )
    assert r.status_code == 409
