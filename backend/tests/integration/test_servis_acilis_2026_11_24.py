"""2026-11-24 sahip istekleri: servis açılışı ve kullanıcı silme.

- Lokasyon isteğe bağlı (talep eden ad/telefon zorunlu kalır).
- Talep kanalı ELDEN / KARGO (migration fco000000001).
- Açılışta tayin: `servis.planla` olan ekibi işle birlikte verir; tayin
  reddedilirse iş de açılmaz (tek işlem).
- Kullanıcı silme: izsiz hesap kalıcı silinir; izi olan 409 (pasifleştir).
"""

import pytest
from servis_yardimci import giris, teknisyen
from sqlalchemy import func, select

from app.models import ServiceOrder, User

pytestmark = pytest.mark.integration

IS = "/api/teknik-servis/isler"


def _govde(hesap_id: int, **kw) -> dict:
    govde = {
        "birim": "GUVENLIK",
        "tur": "DESTEK",
        "konu": "Cihaz arızalı geldi",
        "customer_id": hesap_id,
        "talep_kanali": "ELDEN",
        "iletisim_ad": "Getiren Kişi",
        "iletisim_telefon": "+905321112233",
    }
    govde.update(kw)
    return govde


async def test_lokasyonsuz_elden_ve_kargo_acilir(client, birimli_kullanici_ac, lokasyon_ac) -> None:
    await birimli_kullanici_ac("op_lok", "SERVIS_OPERASYON", ["GUVENLIK"])
    lok = await lokasyon_ac()
    await giris(client, "op_lok")
    r = await client.post(IS, json=_govde(lok.account_id))
    assert r.status_code == 201, r.text
    assert r.json()["address_id"] is None
    assert r.json()["talep_kanali"] == "ELDEN"
    r = await client.post(IS, json=_govde(lok.account_id, talep_kanali="KARGO", konu="Kargo"))
    assert r.status_code == 201, r.text
    # Talep eden kişi hâlâ zorunlu.
    r = await client.post(IS, json=_govde(lok.account_id, iletisim_ad=None, konu="Adsız"))
    assert r.status_code == 400 and "adı" in r.json()["detail"]
    r = await client.get(f"{IS}/form-verileri")
    kanallar = {k["kod"]: k["ad"] for k in r.json()["talep_kanallari"]}
    assert kanallar["ELDEN"] == "Elden teslim" and kanallar["KARGO"] == "Kargo"


async def test_acilista_tayin(client, db, birimli_kullanici_ac, lokasyon_ac) -> None:
    await birimli_kullanici_ac("sef_ac", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("op_ac", "SERVIS_OPERASYON", ["GUVENLIK"])
    tek = await teknisyen(birimli_kullanici_ac, "tek_ac")
    lok = await lokasyon_ac()
    tayin = [{"user_id": tek.id, "rol": "TEKNISYEN", "is_lead": True}]

    # Tayin yetkisi olmayan (servis.planla yok) ekip veremez; iş de açılmaz.
    await giris(client, "op_ac")
    once = await db.scalar(select(func.count()).select_from(ServiceOrder))
    r = await client.post(IS, json=_govde(lok.account_id, atamalar=tayin))
    assert r.status_code == 403
    assert await db.scalar(select(func.count()).select_from(ServiceOrder)) == once

    await giris(client, "sef_ac")
    r = await client.post(IS, json=_govde(lok.account_id, atamalar=tayin))
    assert r.status_code == 201, r.text
    so = r.json()
    assert so["status"] == "PLANLANDI"
    ekip = (await client.get(f"{IS}/{so['id']}/ekip")).json()
    assert [(e["user_id"], e["is_lead"]) for e in ekip] == [(tek.id, True)]

    # Geçersiz tayin (iki sorumlu) → hiçbir şey yazılmaz.
    tek2 = await teknisyen(birimli_kullanici_ac, "tek_ac2")
    once = await db.scalar(select(func.count()).select_from(ServiceOrder))
    r = await client.post(
        IS,
        json=_govde(
            lok.account_id,
            konu="İki sorumlu",
            atamalar=[*tayin, {"user_id": tek2.id, "rol": "TEKNISYEN", "is_lead": True}],
        ),
    )
    assert r.status_code in (400, 409), r.text
    assert await db.scalar(select(func.count()).select_from(ServiceOrder)) == once


async def test_kullanici_silme(client, db, kullanici_ac) -> None:
    admin = await kullanici_ac("yonetici_sil", "ADMIN")
    bos = await kullanici_ac("yanlis_acilan", "DEPO")
    izli = await kullanici_ac("calisan", "DEPO")
    admin_id, izli_id, bos_id = admin.id, izli.id, bos.id
    await giris(client, "calisan")  # giriş izi bırakır
    await giris(client, "yonetici_sil")

    r = await client.delete(f"/api/kullanicilar/{admin_id}")
    assert r.status_code == 400

    r = await client.delete(f"/api/kullanicilar/{izli_id}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["kod"] == "KAYITLI_KULLANICI"
    assert await db.scalar(select(User.id).where(User.id == izli_id)) == izli_id

    r = await client.delete(f"/api/kullanicilar/{bos_id}")
    assert r.status_code == 204, r.text
    db.expire_all()
    assert await db.scalar(select(User).where(User.id == bos_id)) is None
    r = await client.delete(f"/api/kullanicilar/{bos_id}")
    assert r.status_code == 404

    # Kullanıcı yönetimi yetkisi olmayan silemez.
    await giris(client, "calisan")
    r = await client.delete(f"/api/kullanicilar/{admin_id}")
    assert r.status_code == 403


# --- Çoklu cihaz ve cihaz başına bilgi (fcp000000001) ------------------------------


async def test_coklu_cihaz_ve_cihaz_bilgisi(client, db, birimli_kullanici_ac, lokasyon_ac) -> None:
    await birimli_kullanici_ac("op_coklu", "SERVIS_OPERASYON", ["GUVENLIK"])
    lok = await lokasyon_ac()
    await giris(client, "op_coklu")
    r = await client.post(
        IS,
        json=_govde(
            lok.account_id,
            tur="ARIZA",
            seriler=["SN-A1", "SN-B2", "SN-C3"],
            cihaz_bilgileri=[
                {
                    "seri_no": "sn-a1",
                    "cihaz_durumu": "ARIZALI",
                    "cihaz_durumu_aciklama": "Ekran kırık",
                    "musteri_sikayeti": "Açılmıyor",
                    "notlar": "Garantisi bitmiş",
                },
                {"seri_no": "SN-B2", "cihaz_durumu": "CALISIYOR"},
            ],
        ),
    )
    assert r.status_code == 201, r.text
    so = r.json()
    cihazlar = {c["seri_no"]: c for c in so["seriler"]}
    assert set(cihazlar) == {"SN-A1", "SN-B2", "SN-C3"}
    assert cihazlar["SN-A1"]["cihaz_durumu_adi"] == "Arızalı"
    assert cihazlar["SN-A1"]["musteri_sikayeti"] == "Açılmıyor"
    assert cihazlar["SN-C3"]["cihaz_durumu"] is None

    # Sonradan düzenleme (yalnız gönderilen alan).
    seri_id = cihazlar["SN-C3"]["id"]
    r = await client.patch(
        f"{IS}/{so['id']}/cihazlar/{seri_id}",
        json={"cihaz_durumu": "HASARLI", "onarim_bilgisi": "Kasa değişti"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["onarim_bilgisi"] == "Kasa değişti"
    r = await client.patch(f"{IS}/{so['id']}/cihazlar/{seri_id}", json={"cihaz_durumu": "YOK"})
    assert r.status_code == 422

    # Onarım fişi: durum + onarım basılır, şikâyet/not BASILMAZ.
    from app.clock import RealClock
    from app.models import ServiceOrder
    from app.services.teknik_servis import servis_fisleri

    is_ = await db.get(ServiceOrder, so["id"])
    b = await servis_fisleri.baglam(db, is_, "onarim", fiyatli=False, clock=RealClock())
    fis = {c["seri_no"]: c for c in b["s"]["cihazlar"]}
    assert fis["SN-A1"]["cihaz_durumu"] == "Arızalı"
    assert fis["SN-C3"]["onarim_bilgisi"] == "Kasa değişti"
    assert all("musteri_sikayeti" not in c and "notlar" not in c for c in fis.values())

    # İşte olmayan seriye bilgi → 400, iş açılmaz.
    r = await client.post(
        IS,
        json=_govde(
            lok.account_id,
            konu="Yanlış seri",
            seriler=["SN-X"],
            cihaz_bilgileri=[{"seri_no": "SN-Y", "notlar": "?"}],
        ),
    )
    assert r.status_code == 400
