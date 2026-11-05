"""Planlı bakım iş emirleri: bekleyen liste + yönetici seçimiyle toplu açma
(2026-11-05, `bakim_is_emri`).

Korunan kurallar: yıllık bakımlar açılmadan önce "bekleyen iş emri" olarak
listelenir (dönem × açılacak cihaz), DB'ye taslak iş yazılmaz; otomatik görev
kapalıyken hiçbir şey kendiliğinden açılmaz; yönetici seçtiği dönemleri vade
penceresinden bağımsız açar (cihaz başına 1 PB, ikinci açma 0); önizleme
yazmaz; eşleşmemiş cihaz açılmaz ve listede uyarı olarak görünür; başka
birimin dönemi görünmez ve açılamaz ("bulunamadı").
"""

from datetime import UTC, datetime

import pytest
from bakim_yardimci import ONEK, giris, hepsini_eslestir, ortam_kur, pb_isleri, sozlesme_ac
from sqlalchemy import func, select

from app.models import AuditLog, MaintenanceGenerationRun
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


async def _kararli_sozlesme(client, o, *, eslestir: bool = True) -> dict:
    s = await sozlesme_ac(client, o, aktif=False, baslangic=None, bitis=None, annual_frequency=3)
    if eslestir:
        await hepsini_eslestir(client, s["id"], o)
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi", json={"karar_tarihi": "2026-12-15"}
    )
    assert r.status_code == 200, r.text
    return s


async def test_bekleyen_is_emirleri_listelenir_secilenler_topluca_acilir(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    client.clock.set(BUGUN)
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=2, ad="Liste AVM")
    await giris(client, "sef_k")
    s = await _kararli_sozlesme(client, o)

    # Otomatik görev kapalı (varsayılan): vade gelse de kendiliğinden açılmaz.
    client.clock.set(datetime(2026, 11, 20, 9, tzinfo=UTC))
    await bakim_uretim.pb_uretimi_gorevi(db, client.clock)
    await db.commit()
    assert await pb_isleri(db, s["id"]) == []

    await giris(client, "sef_k")  # saat ilerledi; oturum yenilenir
    r = await client.get(f"{ONEK}/planli-isler")
    assert r.status_code == 200, r.text
    liste = r.json()
    assert [x["hedef"] for x in liste["satirlar"]] == ["2026-12-15", "2027-04-15", "2027-08-15"]
    ilk = liste["satirlar"][0]
    assert ilk["musteri"] == "Liste AVM" and ilk["durum"] == "ILK_TURDA"
    assert (ilk["planli"], ilk["acilan"], ilk["acilacak"], ilk["eslesmemis"]) == (3, 0, 3, 0)
    assert {t["tur"]: t["adet"] for t in ilk["turler"]} == {"KAPI_DEDEKTORU": 2, "XRAY": 1}
    assert liste["satirlar"][1]["durum"] == "ILERIDE"
    assert liste["toplam_acilacak"] == 9
    secim = [ilk["donem_id"], liste["satirlar"][1]["donem_id"]]

    # Önizleme: kaç iş açılacağını söyler, hiçbir şey yazmaz.
    r = await client.post(f"{ONEK}/planli-isler/ac", json={"donem_idleri": secim, "onizleme": True})
    assert r.status_code == 200, r.text
    on = r.json()
    assert on["onizleme"] is True and on["acilan"] == 6 and on["is_emirleri"] == []
    assert await pb_isleri(db, s["id"]) == []
    assert not await db.scalar(
        select(func.count(MaintenanceGenerationRun.id)).where(
            MaintenanceGenerationRun.tetik == "TOPLU_AC"
        )
    )

    # Gerçek açma: ikinci dönem (Nisan) vade penceresi dışında olsa da açılır.
    r = await client.post(f"{ONEK}/planli-isler/ac", json={"donem_idleri": secim})
    assert r.status_code == 200, r.text
    ac = r.json()
    assert ac["acilan"] == 6 and len(ac["is_emirleri"]) == 6
    assert [x["acilan"] for x in ac["satirlar"]] == [3, 3]
    isler = await pb_isleri(db, s["id"])
    assert len(isler) == 6 and {so.status for so in isler} == {"PLANLAMADA"}
    run = await db.get(MaintenanceGenerationRun, ac["run_id"])
    assert run.tetik == "TOPLU_AC" and run.created_by == kisiler["sef"].id
    assert await db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "bakim.uret", AuditLog.entity_id == str(ac["run_id"])
        )
    )

    # Açılanlar varsayılan listeden düşer; tüm liste ACILDI gösterir.
    r = await client.get(f"{ONEK}/planli-isler")
    assert [x["hedef"] for x in r.json()["satirlar"]] == ["2027-08-15"]
    r = await client.get(f"{ONEK}/planli-isler", params={"yalniz_acilmamis": False})
    durumlar = {x["hedef"]: (x["durum"], x["acilan"]) for x in r.json()["satirlar"]}
    assert durumlar["2026-12-15"] == ("ACILDI", 3)

    # İkinci açma idempotent: 0 yeni iş.
    r = await client.post(f"{ONEK}/planli-isler/ac", json={"donem_idleri": secim})
    assert r.status_code == 200 and r.json()["acilan"] == 0
    assert len(await pb_isleri(db, s["id"])) == 6

    # Ufuk: `bit` öncesindeki dönemler.
    r = await client.get(
        f"{ONEK}/planli-isler", params={"bit": "2027-05-01", "yalniz_acilmamis": False}
    )
    assert [x["hedef"] for x in r.json()["satirlar"]] == ["2026-12-15", "2027-04-15"]


async def test_eslesmemis_cihaz_acilmaz_uyari_olarak_gorunur(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    client.clock.set(BUGUN)
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=1, ad="Eşleşmemiş AVM")
    await giris(client, "sef_k")
    s = await _kararli_sozlesme(client, o, eslestir=False)

    r = await client.get(f"{ONEK}/planli-isler")
    ilk = r.json()["satirlar"][0]
    assert (ilk["acilacak"], ilk["eslesmemis"]) == (0, 2)
    r = await client.post(f"{ONEK}/planli-isler/ac", json={"donem_idleri": [ilk["donem_id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["acilan"] == 0
    assert [a["neden_kodu"] for a in r.json()["atlanan"]] == ["EKIPMAN_YOK"]
    assert await pb_isleri(db, s["id"]) == []


async def test_planli_isler_rbac_ve_birim_kapsami(client, db, kisiler, lokasyon_ac, ekipman_ac):
    client.clock.set(BUGUN)
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0, ad="Yetki AVM")
    await giris(client, "sef_k")
    s = await _kararli_sozlesme(client, o)
    donem_id = (await client.get(f"{ONEK}/planli-isler")).json()["satirlar"][0]["donem_id"]

    await giris(client, "yonetim_k")  # üst yönetim görür, açamaz
    assert len((await client.get(f"{ONEK}/planli-isler")).json()["satirlar"]) == 3
    r = await client.post(f"{ONEK}/planli-isler/ac", json={"donem_idleri": [donem_id]})
    assert r.status_code == 403
    await giris(client, "tek_k")
    assert (await client.get(f"{ONEK}/planli-isler")).status_code == 403

    await giris(client, "sefh_k")  # başka birim: görmez, açamaz
    assert (await client.get(f"{ONEK}/planli-isler")).json()["satirlar"] == []
    r = await client.post(f"{ONEK}/planli-isler/ac", json={"donem_idleri": [donem_id]})
    assert r.status_code == 200, r.text
    assert r.json()["acilan"] == 0
    assert r.json()["satirlar"] == [{"donem_id": donem_id, "sonuc": "BULUNAMADI", "acilan": 0}]
    assert r.json()["atlanan"] == []  # başka birimin sözleşmesi sızmaz
    assert await pb_isleri(db, s["id"]) == []

    r = await client.post(f"{ONEK}/planli-isler/ac", json={"donem_idleri": []})
    assert r.status_code == 422
