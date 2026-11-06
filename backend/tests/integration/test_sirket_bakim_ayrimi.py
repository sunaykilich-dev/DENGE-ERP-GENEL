"""Planlı bakımda şirket ayrımı — DENGE TELEKOM, DENGE ELEKTRONİK'in planlı
bakımlarını görmez (kullanıcı isteği 2026-11-06, KARARLAR §12.6).

`sirket_ayrimi` işaretli: şirket süzgeci GERÇEK çalışır. Elektronik'in
(GUVENLIK) sözleşmesi, dönemleri ve açılmış PB işleri; Telekom'da çalışan üç
tip kullanıcı (yalnız TELEKOM üyesi yönetici, iki şirkete üye yönetici TELEKOM
etkinken, Haberleşme şefi) bakım uçlarının HİÇBİRİNDE sözleşme numarasını ya
da müşteri adını görmez; tek kayıt 404'tür. Pozitif kontrol: aynı yönetici
ELEKTRONİK'e geçince görür.
"""

from datetime import UTC, datetime

import pytest
from bakim_yardimci import ONEK, giris, hepsini_eslestir, ortam_kur, sozlesme_ac

from app.models import KullaniciSirketi

pytestmark = [pytest.mark.integration, pytest.mark.sirket_ayrimi]

BUGUN = datetime(2026, 11, 5, 9, tzinfo=UTC)
MUSTERI = "Elektronik Bakım AVM"


async def _uyelik(db, user, *kodlar: str) -> None:
    for kod in kodlar:
        db.add(KullaniciSirketi(user_id=user.id, sirket_kod=kod))
    await db.commit()


async def _sec(client, kod: str) -> None:
    r = await client.put("/api/oturum/aktif-sirket", json={"kod": kod})
    assert r.status_code == 200, r.text


LISTE_UCLARI = (
    f"{ONEK}/sozlesmeler",
    f"{ONEK}/donemler",
    f"{ONEK}/takvim?yil=2026",
    f"{ONEK}/takvim?yil=2027",
    f"{ONEK}/planli-isler",
    f"{ONEK}/ozet",
    f"{ONEK}/uretim-kayitlari",
    f"{ONEK}/uygunsuzluklar",
    f"{ONEK}/kapsam-disi",
    f"{ONEK}/raporlar/donem-tamamlama",
    f"{ONEK}/raporlar/pb-isleri",
    "/api/teknik-servis/isler?limit=200",
    "/api/teknik-servis/panel",
    "/api/raporlar/uyarilar",
    "/api/teknik-servis/ana-panel",
)


async def _hicbir_sey_gormez(client, sozlesme: dict, ekipman_id: int) -> None:
    for yol in LISTE_UCLARI:
        r = await client.get(yol)
        assert r.status_code in (200, 403), (yol, r.status_code, r.text[:200])
        assert sozlesme["contract_no"] not in r.text, yol
        assert MUSTERI not in r.text, yol
        if "X-Toplam-Kayit" in r.headers and yol.startswith(f"{ONEK}/sozlesmeler"):
            assert r.headers["X-Toplam-Kayit"] == "0"
    r = await client.get(f"{ONEK}/sozlesmeler/{sozlesme['id']}")
    assert r.status_code == 404
    r = await client.get(f"{ONEK}/sozlesmeler/{sozlesme['id']}/donemler")
    assert r.status_code == 404
    r = await client.get(f"{ONEK}/ekipman/{ekipman_id}/bakim-gecmisi")
    assert r.status_code == 404
    ozet = (await client.get(f"{ONEK}/ozet")).json()
    assert all(not k.get("deger") for k in ozet["kutular"]), ozet["kutular"]


async def test_telekom_elektronigin_planli_bakimlarini_gormez(
    client, db, birimli_kullanici_ac, kullanici_ac, lokasyon_ac, ekipman_ac
) -> None:
    client.clock.set(BUGUN)
    sef_e = await birimli_kullanici_ac("sef_e", "SERVIS_SEF", ["GUVENLIK"])
    await _uyelik(db, sef_e, "ELEKTRONIK")
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=1, ad=MUSTERI)
    await giris(client, "sef_e")
    s = await sozlesme_ac(client, o, aktif=False, baslangic=None, bitis=None, annual_frequency=2)
    await hepsini_eslestir(client, s["id"], o)
    r = await client.put(
        f"{ONEK}/sozlesmeler/{s['id']}/karar-tarihi", json={"karar_tarihi": "2026-11-20"}
    )
    assert r.status_code == 200, r.text
    s = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}")).json()
    liste = (await client.get(f"{ONEK}/planli-isler")).json()
    assert liste["satirlar"], "Elektronik şefi kendi planlı bakımını görür"
    r = await client.post(
        f"{ONEK}/planli-isler/ac", json={"donem_idleri": [liste["satirlar"][0]["donem_id"]]}
    )
    assert r.status_code == 200 and r.json()["acilan"] == 2, r.text
    ekipman_id = o.ekipmanlar["XRAY"][0].id

    # 1) Yalnız TELEKOM üyesi yönetici (TUMU kapsamı).
    yon_t = await kullanici_ac("yon_t", "SERVIS_YONETICI")
    await _uyelik(db, yon_t, "TELEKOM")
    await giris(client, "yon_t")
    await _hicbir_sey_gormez(client, s, ekipman_id)

    # 2) Haberleşme şefi (TELEKOM).
    sef_h = await birimli_kullanici_ac("sef_h", "SERVIS_SEF", ["HABERLESME"])
    await _uyelik(db, sef_h, "TELEKOM")
    await giris(client, "sef_h")
    await _hicbir_sey_gormez(client, s, ekipman_id)
    r = await client.post(
        f"{ONEK}/planli-isler/ac", json={"donem_idleri": [liste["satirlar"][1]["donem_id"]]}
    )
    assert r.status_code in (403, 404) or r.json().get("acilan") == 0, r.text

    # 3) İki şirkete üye yönetici: TELEKOM etkinken görmez, ELEKTRONİK'te görür.
    yon_c = await kullanici_ac("yon_c", "SERVIS_YONETICI")
    await _uyelik(db, yon_c, "TELEKOM", "ELEKTRONIK")
    await giris(client, "yon_c")
    await _sec(client, "TELEKOM")
    await _hicbir_sey_gormez(client, s, ekipman_id)
    await _sec(client, "ELEKTRONIK")
    r = await client.get(f"{ONEK}/sozlesmeler")
    assert r.headers["X-Toplam-Kayit"] == "1"
    assert s["contract_no"] in (await client.get(f"{ONEK}/planli-isler")).text
