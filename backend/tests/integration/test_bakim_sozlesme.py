"""Bakım sözleşmesi yönetimi (TS-060, E04-02, E04-D04, E14-11).

Korunan kurallar: tür+adet kapsam kalem başına bir cihaz olarak saklanır;
ücret yalnız `maliyet.gor` ile görünür ve yazılır (görmeyenin yanıtında
ANAHTAR YOK, gönderirse 403 ve hiçbir şey yazılmaz); aynı tesiste dönemi
çakışan ikinci aktif sözleşme 409 + onaylı istisna; kapsam dışı birimin
sözleşmesine her uç 404 döner ve kayıt DEĞİŞMEZ.
"""

import re

import pytest
from bakim_yardimci import (
    BAKIM_NO_DESENI,
    ONEK,
    giris,
    hepsini_eslestir,
    ortam_kur,
    sozlesme_ac,
    sozlesme_govdesi,
)
from sqlalchemy import func, select

from app.models import AuditLog, MaintenanceContract, MaintenanceContractItem, MaintenancePeriod

pytestmark = pytest.mark.integration


@pytest.fixture
async def kisiler(birimli_kullanici_ac, kullanici_ac):
    return {
        "sef": await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"]),
        "sef_h": await birimli_kullanici_ac("sef_h", "SERVIS_SEF", ["HABERLESME"]),
        "tek": await birimli_kullanici_ac(
            "tek_g", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "admin": await kullanici_ac("admin_b", "ADMIN"),
        "yonetim": await kullanici_ac("yonetim_b", "YONETIM"),
    }


async def test_sozlesme_tur_adet_kalemlere_acilir_ve_aktiflesir(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac)
    await giris(client, "sef_g")
    r = await client.post(f"{ONEK}/sozlesmeler", json=sozlesme_govdesi(o))
    assert r.status_code == 201, r.text
    s = r.json()
    assert re.match(BAKIM_NO_DESENI, s["contract_no"])
    assert s["status"] == "TASLAK"
    assert s["kapsam"] == {"XRAY": 2, "KAPI_DEDEKTORU": 3}
    kalem_sayisi = await db.scalar(
        select(func.count(MaintenanceContractItem.id)).where(
            MaintenanceContractItem.contract_id == s["id"]
        )
    )
    assert kalem_sayisi == 5  # 2 X-Ray + 3 kapı = 5 fiziksel cihaz satırı
    assert sorted(s["sonraki_durumlar"]) == ["AKTIF", "PASIF"]

    r = await client.post(f"{ONEK}/sozlesmeler/{s['id']}/durum", json={"hedef": "AKTIF"})
    assert r.status_code == 200, r.text
    donemler = (
        await db.scalars(select(MaintenancePeriod).where(MaintenancePeriod.contract_id == s["id"]))
    ).all()
    assert sorted(d.target_date.isoformat() for d in donemler) == ["2026-01-01", "2026-07-01"]
    # Aynı makine: AKTIF → TASLAK yok.
    r = await client.post(f"{ONEK}/sozlesmeler/{s['id']}/durum", json={"hedef": "TASLAK"})
    assert r.status_code == 409


async def test_eksik_tarihle_aktiflestirme_400(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_g")
    s = await sozlesme_ac(client, o, aktif=False, bitis=None)
    r = await client.post(f"{ONEK}/sozlesmeler/{s['id']}/durum", json={"hedef": "AKTIF"})
    assert r.status_code == 400
    assert "bitiş" in r.json()["detail"]


async def test_rbac_okuma_yazma(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "tek_g")  # teknisyen sözleşme listesini görmez (M04-14)
    assert (await client.get(f"{ONEK}/sozlesmeler")).status_code == 403
    assert (await client.post(f"{ONEK}/sozlesmeler", json=sozlesme_govdesi(o))).status_code == 403
    await giris(client, "yonetim_b")  # YONETIM yalnız okur
    assert (await client.get(f"{ONEK}/sozlesmeler")).status_code == 200
    assert (await client.post(f"{ONEK}/sozlesmeler", json=sozlesme_govdesi(o))).status_code == 403
    await giris(client, "sef_g")
    assert (await client.post(f"{ONEK}/sozlesmeler", json=sozlesme_govdesi(o))).status_code == 201
    r = await client.get(f"{ONEK}/sozlesmeler")
    assert r.status_code == 200 and r.headers["X-Toplam-Kayit"] == "1"


async def test_ucret_gormeyene_anahtar_yok_gonderirse_403(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_g")
    once = await db.scalar(select(func.count(MaintenanceContract.id)))
    r = await client.post(f"{ONEK}/sozlesmeler", json=sozlesme_govdesi(o, fee_per_visit="1500.00"))
    assert r.status_code == 403
    assert await db.scalar(select(func.count(MaintenanceContract.id))) == once

    s = await sozlesme_ac(client, o, aktif=False)
    for anahtar in ("fee_per_visit", "contract_total", "legacy_fee_text", "currency"):
        assert anahtar not in s
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/ucret", json={"fee_per_visit": "10"})
    assert r.status_code == 403  # ücret ucu maliyet.gor ∧ bakim.yaz

    await giris(client, "admin_b")
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/ucret",
        json={"fee_per_visit": "1500.00", "contract_total": "3000.00", "currency": "TRY"},
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["fee_per_visit"]) == 1500.0

    await giris(client, "sef_g")
    liste = (await client.get(f"{ONEK}/sozlesmeler")).json()
    assert all("fee_per_visit" not in s for s in liste)
    detay = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}")).json()
    assert "contract_total" not in detay


async def test_iyimser_kilit_409(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_g")
    s = await sozlesme_ac(client, o, aktif=False)
    r = await client.patch(
        f"{ONEK}/sozlesmeler/{s['id']}", json={"version": s["version"], "notes": "ilk"}
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"{ONEK}/sozlesmeler/{s['id']}", json={"version": s["version"], "notes": "eski sürüm"}
    )
    assert r.status_code == 409


async def test_kapsam_disi_birim_404_ve_veri_degismez(client, db, kisiler, lokasyon_ac, ekipman_ac):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_g")
    s = await sozlesme_ac(client, o, aktif=False)
    kayit = await db.get(MaintenanceContract, s["id"])

    await giris(client, "sef_h")  # HABERLESME şefi
    denetim_once = await db.scalar(select(func.count(AuditLog.id)))
    assert (await client.get(f"{ONEK}/sozlesmeler")).headers["X-Toplam-Kayit"] == "0"
    assert (await client.get(f"{ONEK}/sozlesmeler/{s['id']}")).status_code == 404
    r = await client.patch(f"{ONEK}/sozlesmeler/{s['id']}", json={"version": 1, "notes": "x"})
    assert r.status_code == 404
    r = await client.post(f"{ONEK}/sozlesmeler/{s['id']}/durum", json={"hedef": "AKTIF"})
    assert r.status_code == 404
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/kapsam", json={"kapsam": {"XRAY": 5}})
    assert r.status_code == 404
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme", json={"eslesmeler": []})
    assert r.status_code == 404
    # Başka birime sözleşme açmak da 404 (kayıt görünmez olurdu).
    r = await client.post(f"{ONEK}/sozlesmeler", json=sozlesme_govdesi(o, birim="GUVENLIK"))
    assert r.status_code == 404

    await db.refresh(kayit)
    assert kayit.status == "TASLAK" and kayit.notes is None and kayit.version == s["version"]
    assert await db.scalar(select(func.count(AuditLog.id))) == denetim_once


async def test_ayni_tesiste_cakisan_donem_409_onayla_gecer(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_g")
    ilk = await sozlesme_ac(client, o)
    ikinci = await sozlesme_ac(client, o, aktif=False, baslangic="2026-06-01", bitis="2027-06-01")
    r = await client.post(f"{ONEK}/sozlesmeler/{ikinci['id']}/durum", json={"hedef": "AKTIF"})
    assert r.status_code == 409
    govde = r.json()["detail"]
    assert govde["kod"] == "DONEM_CAKISMA"
    assert govde["cakisanlar"][0]["contract_no"] == ilk["contract_no"]
    r = await client.post(
        f"{ONEK}/sozlesmeler/{ikinci['id']}/durum",
        json={"hedef": "AKTIF", "cakisma_onayi": True},
    )
    assert r.status_code == 400  # gerekçe zorunlu
    r = await client.post(
        f"{ONEK}/sozlesmeler/{ikinci['id']}/durum",
        json={"hedef": "AKTIF", "cakisma_onayi": True, "cakisma_gerekcesi": "Ek bina"},
    )
    assert r.status_code == 200, r.text
    assert (
        await db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.action == "bakim.sozlesme.cakisma_onayi")
        )
        == 1
    )


async def test_kapsam_azaltma_valid_to_yazar_artis_yeni_sira(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=2, kapi=0)
    await giris(client, "sef_g")
    s = await sozlesme_ac(client, o)
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/kapsam", json={"kapsam": {"XRAY": 1}})
    assert r.status_code == 200 and r.json()["kapsam"] == {"XRAY": 1}
    kapali = await db.scalar(
        select(MaintenanceContractItem).where(
            MaintenanceContractItem.contract_id == s["id"],
            MaintenanceContractItem.valid_to.is_not(None),
        )
    )
    assert kapali is not None and kapali.sira == 2 and not kapali.is_deleted
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/kapsam", json={"kapsam": {"XRAY": 2}})
    assert r.status_code == 200
    siralar = sorted(
        (
            await db.scalars(
                select(MaintenanceContractItem.sira).where(
                    MaintenanceContractItem.contract_id == s["id"],
                    MaintenanceContractItem.valid_to.is_(None),
                )
            )
        ).all()
    )
    assert siralar == [1, 3]  # kapalı sıra 2 yeniden kullanılmaz (uq_mci_sira)


async def test_acik_pb_kalemi_kapsamdan_cikarilamaz_ve_pasif_listeler(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_g")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    r = await client.post(f"{ONEK}/uretim")
    assert r.status_code == 200 and r.json()["generated"] == 1
    r = await client.put(f"{ONEK}/sozlesmeler/{s['id']}/kapsam", json={"kapsam": {"XRAY": 0}})
    assert r.status_code == 409
    assert r.json()["detail"]["kod"] == "ACIK_PB"
    r = await client.post(f"{ONEK}/sozlesmeler/{s['id']}/durum", json={"hedef": "PASIF"})
    assert r.status_code == 200
    assert len(r.json()["acik_pb_isleri"]) == 1  # E14-11 kabul 3: pasifleme açık PB'leri listeler
    # Pasif sözleşme üretime girmez.
    r = await client.post(f"{ONEK}/uretim")
    assert r.json()["generated"] == 0


async def test_uyarilar_ve_kpi_birim_kapsamli_sayi_liste_esit(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    """TS-069: geciken dönem / teyit bekleyen uyarıları birim kapsamlı; KPI
    kutusu sayısı açtığı listenin `X-Toplam-Kayit`'iyle aynı."""
    from app.models import MaintenanceContract as MC
    from app.services.teknik_servis import bakim

    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_g")
    # 2025 başlangıçlı: 01.01.2025 ve 01.07.2025 dönemleri açık ve gecikmiş.
    await sozlesme_ac(client, o, baslangic="2025-01-01", bitis="2026-06-01")
    db.add(
        MC(
            contract_no="BAKIM-9001",
            birim="GUVENLIK",
            status="TEYIT_BEKLIYOR",
            teyit_gerekcesi="Göç: dönem metni ayrıştırılamadı",
            customer_name_raw="Eski Müşteri",
        )
    )
    await db.commit()

    uyarilar = {
        u.kod: u.adet for u in await bakim.bakim_uyarilari(db, kisiler["sef"], client.clock)
    }
    assert uyarilar["BAKIM_GECIKEN_DONEM"] == 2
    assert uyarilar["BAKIM_TEYIT_BEKLEYEN"] == 1
    yabanci = {
        u.kod: u.adet for u in await bakim.bakim_uyarilari(db, kisiler["sef_h"], client.clock)
    }
    assert yabanci["BAKIM_GECIKEN_DONEM"] == 0 and yabanci["BAKIM_TEYIT_BEKLEYEN"] == 0

    ozet = (await client.get(f"{ONEK}/ozet")).json()
    kutular = {k["kod"]: k["deger"] for k in ozet["kutular"]}
    r = await client.get(f"{ONEK}/donemler", params={"gecikmis": "true"})
    assert kutular["GECIKEN_DONEM"] == int(r.headers["X-Toplam-Kayit"]) == 2
    r = await client.get(f"{ONEK}/sozlesmeler", params={"durum": "TEYIT_BEKLIYOR"})
    assert kutular["TEYIT_BEKLEYEN"] == int(r.headers["X-Toplam-Kayit"]) == 1
    await giris(client, "sef_h")
    kutular = {k["kod"]: k["deger"] for k in (await client.get(f"{ONEK}/ozet")).json()["kutular"]}
    assert kutular["GECIKEN_DONEM"] == 0 and kutular["TEYIT_BEKLEYEN"] == 0
