"""Yönetici ilişkisi ve "Ekibim" süzgeci (TS-199, E13-17).

Kabul: "Ekibim" yalnız doğrudan bağlı ÇALIŞAN personeli gösterir ve kapsam dışı
kişiyi göstermez (yetki genişletmez); yönetici zinciri döngüsü 400; kapsam
dışı kişi/yönetici 404 ve veri değişmez; sürüm 409; yazma `personel.yaz`.
"""

from datetime import date

import pytest
from servis_yardimci import giris

pytestmark = pytest.mark.integration

P = "/api/personel"


@pytest.fixture
async def veri(client, db, kullanici_ac, birimli_kullanici_ac, rol_ac):
    await rol_ac("T_IK_A", ["personel.gor", "personel.yaz"], "KENDI_BIRIMI")
    sef_a = await birimli_kullanici_ac("sef_a", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    sef_b = await birimli_kullanici_ac("sef_b", "SERVIS_SEF", ["HABERLESME"], saha_rolu="SEF")
    ik_a = await birimli_kullanici_ac("ik_a", "T_IK_A", ["GUVENLIK"])
    tek1 = await birimli_kullanici_ac(
        "tek1", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    tek2 = await birimli_kullanici_ac(
        "tek2", "SERVIS_TEKNISYEN", ["HABERLESME"], saha_rolu="TEKNISYEN"
    )
    tek3 = await birimli_kullanici_ac(
        "tek3", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    eski = await birimli_kullanici_ac(
        "eski", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    # Doğrudan ORM ile kurulum (konu uç değil, süzgeç).
    tek1.yonetici_id = sef_a.id
    tek2.yonetici_id = sef_a.id  # başka birim: sef_a'nın kapsamı dışında
    eski.yonetici_id = sef_a.id
    eski.is_active = False
    eski.ayrilis_tarihi = date(2025, 12, 1)
    eski.ayrilis_nedeni = "ISTIFA"
    tek3.yonetici_id = sef_b.id  # yönetici başka birimde
    await db.commit()
    return {
        "sef_a": sef_a,
        "sef_b": sef_b,
        "ik_a": ik_a,
        "tek1": tek1,
        "tek2": tek2,
        "tek3": tek3,
        "eski": eski,
    }


async def test_ekibim_yalniz_dogrudan_bagli_ve_kapsamli(client, veri) -> None:
    await giris(client, "sef_a")
    r = await client.get(P, params={"ekibim": "true"})
    assert r.status_code == 200, r.text
    assert int(r.headers["X-Toplam-Kayit"]) == 1
    satirlar = r.json()
    assert [s["id"] for s in satirlar] == [veri["tek1"].id]
    assert satirlar[0]["acik_sayac_var"] is False
    assert satirlar[0]["yonetici"] == {"id": veri["sef_a"].id, "ad": "Sef_A"}
    # Yetki genişletmez: bağlı ama kapsam dışı kişi tek kayıtta da 404.
    assert (await client.get(f"{P}/{veri['tek2'].id}")).status_code == 404
    # Süzgeçsiz listede `acik_sayac_var` anahtarı yok.
    r = await client.get(P)
    assert all("acik_sayac_var" not in s for s in r.json())
    # Ayrılmış bağlı, açıkça istenirse görünür.
    r = await client.get(P, params={"ekibim": "true", "durum": "AYRILDI"})
    assert [s["id"] for s in r.json()] == [veri["eski"].id]


async def test_kapsam_disi_yonetici_maskelenir(client, veri) -> None:
    await giris(client, "sef_a")
    r = await client.get(f"{P}/{veri['tek3'].id}")
    assert r.status_code == 200, r.text
    assert r.json()["yonetici"] == {"id": None, "ad": "Kapsam dışı kişi"}
    await giris(client, "mudur")
    r = await client.get(f"{P}/{veri['tek3'].id}")
    assert r.json()["yonetici"] == {"id": veri["sef_b"].id, "ad": "Sef_B"}


async def test_yonetici_atama_kurallari(client, db, veri) -> None:
    await giris(client, "mudur")
    tek3 = veri["tek3"]
    r = await client.put(
        f"{P}/{tek3.id}/yonetici", json={"yonetici_id": veri["sef_a"].id, "version": tek3.version}
    )
    assert r.status_code == 200, r.text
    assert r.json()["yonetici"]["id"] == veri["sef_a"].id
    surum = r.json()["version"]
    # Eski sürüm 409.
    r = await client.put(
        f"{P}/{tek3.id}/yonetici", json={"yonetici_id": None, "version": surum - 1}
    )
    assert r.status_code == 409
    # Kendisi 400.
    r = await client.put(f"{P}/{tek3.id}/yonetici", json={"yonetici_id": tek3.id, "version": surum})
    assert r.status_code == 400
    # Döngü: sef_a'nın yöneticisi tek3 olamaz (tek3 → sef_a) → 400; dolaylı da.
    sef_a = veri["sef_a"]
    r = await client.put(
        f"{P}/{sef_a.id}/yonetici", json={"yonetici_id": tek3.id, "version": sef_a.version}
    )
    assert r.status_code == 400, r.text
    tek1 = veri["tek1"]
    r = await client.put(
        f"{P}/{tek1.id}/yonetici", json={"yonetici_id": tek3.id, "version": tek1.version}
    )
    assert r.status_code == 200, r.text  # tek1 → tek3 → sef_a (döngü yok)
    r = await client.put(
        f"{P}/{sef_a.id}/yonetici", json={"yonetici_id": tek1.id, "version": sef_a.version}
    )
    assert r.status_code == 400  # sef_a → tek1 → tek3 → sef_a döngüsü
    # Ayrılmış personel yönetici olamaz.
    r = await client.put(
        f"{P}/{tek3.id}/yonetici", json={"yonetici_id": veri["eski"].id, "version": surum}
    )
    assert r.status_code == 400
    # Kaldırma.
    r = await client.put(f"{P}/{tek3.id}/yonetici", json={"yonetici_id": None, "version": surum})
    assert r.status_code == 200 and r.json()["yonetici"] is None


async def test_rbac_ve_kapsam_disi_404_veri_degismez(client, db, veri) -> None:
    await giris(client, "sef_a")  # personel.yaz yok
    r = await client.put(
        f"{P}/{veri['tek1'].id}/yonetici", json={"yonetici_id": None, "version": 1}
    )
    assert r.status_code == 403

    await giris(client, "ik_a")  # KENDI_BIRIMI GUVENLIK, personel.yaz
    tek2 = veri["tek2"]
    r = await client.put(
        f"{P}/{tek2.id}/yonetici", json={"yonetici_id": None, "version": tek2.version}
    )
    assert r.status_code == 404
    await db.refresh(tek2)
    assert tek2.yonetici_id == veri["sef_a"].id
    # Gövdedeki yönetici kapsam dışı (başka birim) → 404, değişmez.
    tek1 = veri["tek1"]
    r = await client.put(
        f"{P}/{tek1.id}/yonetici", json={"yonetici_id": veri["sef_b"].id, "version": tek1.version}
    )
    assert r.status_code == 404
    await db.refresh(tek1)
    assert tek1.yonetici_id == veri["sef_a"].id
