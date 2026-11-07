"""Servis işine kütükten cihaz bilgisi (KARARLAR §12).

Kullanıcı isteği (2026-11-06):
- Haberleşme arıza işinde kayıtlı frekans o seri/röle için kütükten (ya da o
  serinin son röle montaj kaydından) işe otomatik gelir.
- Güvenlik arıza işinde X-ray / kapı dedektörü seri numarası kütükten gelir.
- Kütükte yoksa teknisyen girer; girilmeden iş KAPATILAMAZ (409).
- Teknisyenin frekansı kütükte boşsa kütüğe yazılır; doluysa ezilmez.
"""

import pytest
from servis_yardimci import acilis, giris, musteri, tazele

from app.models import ServiceRoleMontaj

pytestmark = pytest.mark.integration

IS = "/api/teknik-servis/isler"
FREKANS = {"role_tx": "440.1250", "role_rx": "450.1250", "calisma_modu": "DIJITAL"}


async def test_guvenlik_seri_kutukten_gelir_ve_ekipman_baglanir(
    client, db, birimli_kullanici_ac, ekipman_ac
) -> None:
    await birimli_kullanici_ac("op_g", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db, "Kütük AVM")
    xray = await ekipman_ac(musteri=hesap, tip="XRAY", seri="XR-77")
    await ekipman_ac(musteri=hesap, tip="KAPI_DEDEKTORU", seri="MD-88")
    await giris(client, "op_g")

    # İş açma formunun kütük seçicisi müşterinin cihazlarını getirir.
    r = await client.get(
        f"{IS}/kutuk-cihazlari", params={"birim": "GUVENLIK", "musteri_id": hesap.id}
    )
    assert r.status_code == 200, r.text
    assert sorted(c["serial_no"] for c in r.json()) == ["MD-88", "XR-77"]

    # Seri yazılınca kütükteki ekipmana bağlanır; kural sağlanmıştır.
    r = await client.post(IS, json=acilis(hesap, seriler=["xr-77"]))
    assert r.status_code == 201, r.text
    is_ = r.json()
    assert is_["equipment_id"] == xray.id
    assert is_["cihaz_bilgisi_kurali"] == "SERI"
    assert is_["cihaz_bilgisi_eksik"] == []

    # Seri girilmeden açılan iş: eksik görünür.
    r = await client.post(IS, json=acilis(hesap, konu="Kapı ötmüyor"))
    assert r.status_code == 201, r.text
    assert r.json()["cihaz_bilgisi_eksik"] == ["Cihaz seri numarası"]


async def test_guvenlik_seri_yoksa_teknisyen_girmeden_kapanmaz(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("mud_g", "SERVIS_YONETICI", ["GUVENLIK"])
    so = await servis_isi_ac(durum="TAMAMLANDI", seri=None)
    await db.commit()
    await giris(client, "mud_g")

    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 409 and "seri numarası" in r.json()["detail"]

    r = await client.put(f"{IS}/{so.id}/cihaz-bilgisi", json={"seri_no": " "})
    assert r.status_code == 400
    r = await client.put(f"{IS}/{so.id}/cihaz-bilgisi", json={"seri_no": "XR-SAHA-1"})
    assert r.status_code == 200, r.text
    assert r.json()["seri_no"] == "XR-SAHA-1" and r.json()["eksikler"] == []

    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 200, r.text
    assert (await tazele(db, so)).status == "KAPATILDI"


async def test_haberlesme_frekans_kutukten_gelir(
    client, db, birimli_kullanici_ac, ekipman_ac
) -> None:
    await birimli_kullanici_ac("op_h", "SERVIS_OPERASYON", ["HABERLESME"])
    hesap = await musteri(db, "Röle Müşterisi")
    role = await ekipman_ac(
        birim="HABERLESME", musteri=hesap, tip="ROLE_TEKRARLAYICI", seri="RL-1", frekans=FREKANS
    )
    await giris(client, "op_h")

    r = await client.get(
        f"{IS}/kutuk-cihazlari", params={"birim": "HABERLESME", "musteri_id": hesap.id}
    )
    assert [c["frekans"]["role_tx"] for c in r.json()] == ["440.1250"]

    r = await client.post(
        IS,
        json=acilis(
            hesap, birim="HABERLESME", konu="Röle çekmiyor", nitelikler=["ARIZA"], seriler=["RL-1"]
        ),
    )
    assert r.status_code == 201, r.text
    is_ = r.json()
    assert is_["equipment_id"] == role.id
    assert is_["cihaz_bilgisi_kurali"] == "FREKANS" and is_["cihaz_bilgisi_eksik"] == []
    r = await client.get(f"{IS}/{is_['id']}/cihaz-bilgisi")
    d = r.json()
    assert d["kaynak"] == "KUTUK"
    assert d["frekans"] == FREKANS
    assert d["ekipman"]["id"] == role.id


async def test_haberlesme_frekans_son_role_montaj_kaydindan_gelir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op_h2", "SERVIS_OPERASYON", ["HABERLESME"])
    hesap = await musteri(db, "Montajlı Müşteri")
    kurulum = await servis_isi_ac(
        birim="HABERLESME", tur="KURULUM", musteri=hesap, nitelikler=["KURULUM"]
    )
    db.add(
        ServiceRoleMontaj(
            service_order_id=kurulum.id,
            alanlar={"role_seri_no": " rl2 ", "role_tx": "427.1", "role_rx": "417.1"},
        )
    )
    await db.commit()
    await giris(client, "op_h2")
    r = await client.post(
        IS,
        json=acilis(
            hesap, birim="HABERLESME", konu="Röle arızası", nitelikler=["ARIZA"], seriler=["RL2"]
        ),
    )
    assert r.status_code == 201, r.text
    d = (await client.get(f"{IS}/{r.json()['id']}/cihaz-bilgisi")).json()
    assert d["kaynak"] == "ROLE_MONTAJ"
    assert (d["frekans"]["role_tx"], d["frekans"]["role_rx"]) == ("427.1", "417.1")
    assert d["eksikler"] == []


async def test_frekans_yoksa_teknisyen_girer_kutuk_ogrenir_ezilmez(
    client, db, birimli_kullanici_ac, servis_isi_ac, ekipman_ac
) -> None:
    await birimli_kullanici_ac("mud_h", "SERVIS_YONETICI", ["HABERLESME"])
    hesap = await musteri(db, "Frekanssız Müşteri")
    role = await ekipman_ac(birim="HABERLESME", musteri=hesap, tip="ROLE_TEKRARLAYICI", seri="RL-3")
    so = await servis_isi_ac(
        birim="HABERLESME",
        musteri=hesap,
        durum="TAMAMLANDI",
        nitelikler=["ARIZA"],
        seri=None,
        equipment_id=role.id,
    )
    await db.commit()
    await giris(client, "mud_h")

    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 409 and "frekans" in r.json()["detail"]

    r = await client.put(f"{IS}/{so.id}/cihaz-bilgisi", json={"frekans": {"role_tx": "çok"}})
    assert r.status_code == 400
    r = await client.put(f"{IS}/{so.id}/cihaz-bilgisi", json={"frekans": {"yok": "1"}})
    assert r.status_code == 400
    # Kısmi giriş serbest; kapanış yine engelli.
    r = await client.put(f"{IS}/{so.id}/cihaz-bilgisi", json={"frekans": {"role_tx": "460,5"}})
    assert r.status_code == 200, r.text
    assert r.json()["eksikler"] == ["Röle RX frekansı (MHz)"]
    surum = r.json()["version"]
    await db.refresh(role)
    assert role.frekans is None, "eksik frekans kütüğe yazılmaz"

    r = await client.put(
        f"{IS}/{so.id}/cihaz-bilgisi",
        json={"frekans": {"role_tx": "460.5", "role_rx": "470.5"}, "version": 99},
    )
    assert r.status_code == 409
    r = await client.put(
        f"{IS}/{so.id}/cihaz-bilgisi",
        json={"frekans": {"role_tx": "460.5", "role_rx": "470.5"}, "version": surum},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kaynak"] == "TEKNISYEN" and r.json()["eksikler"] == []
    await db.refresh(role)
    assert role.frekans == {"role_tx": "460.5", "role_rx": "470.5"}, "kütük öğrendi"

    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 200, r.text
    r = await client.put(
        f"{IS}/{so.id}/cihaz-bilgisi", json={"frekans": {"role_tx": "1"}, "version": surum + 1}
    )
    assert r.status_code == 409, "kapanmış işte değişmez"

    # Kütük doluyken farklı saha frekansı kütüğü EZMEZ.
    ikinci = await servis_isi_ac(
        birim="HABERLESME",
        musteri=hesap,
        durum="TAMAMLANDI",
        nitelikler=["ARIZA"],
        seri=None,
        equipment_id=role.id,
    )
    await db.commit()
    r = await client.put(
        f"{IS}/{ikinci.id}/cihaz-bilgisi",
        json={"frekans": {"role_tx": "111.1", "role_rx": "222.2"}},
    )
    assert r.status_code == 200, r.text
    await db.refresh(role)
    assert role.frekans == {"role_tx": "460.5", "role_rx": "470.5"}


async def test_kural_disi_isler_serbest_kapanir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("mud_g2", "SERVIS_YONETICI", ["GUVENLIK"])
    kurulum = await servis_isi_ac(tur="KURULUM", durum="TAMAMLANDI", seri=None)
    gecis = await servis_isi_ac(durum="TAMAMLANDI", seri=None, sla_kaynak="GECIS")
    await db.commit()
    await giris(client, "mud_g2")
    r = await client.get(f"{IS}/{kurulum.id}")
    assert r.json()["cihaz_bilgisi_kurali"] is None
    assert r.json()["cihaz_bilgisi_eksik"] is None
    r = await client.put(f"{IS}/{kurulum.id}/cihaz-bilgisi", json={"seri_no": "X"})
    assert r.status_code == 400
    for so in (kurulum, gecis):
        r = await client.post(f"{IS}/{so.id}/kapat", json={})
        assert r.status_code == 200, r.text


async def test_kutuk_cihazlari_kapsam_disi_birimi_gostermez(
    client, db, birimli_kullanici_ac, ekipman_ac
) -> None:
    await birimli_kullanici_ac("op_h3", "SERVIS_OPERASYON", ["HABERLESME"])
    hesap = await musteri(db, "Karma Müşteri")
    await ekipman_ac(musteri=hesap, tip="XRAY", seri="XR-9")
    await giris(client, "op_h3")
    r = await client.get(
        f"{IS}/kutuk-cihazlari", params={"birim": "GUVENLIK", "musteri_id": hesap.id}
    )
    assert r.status_code == 200 and r.json() == []
