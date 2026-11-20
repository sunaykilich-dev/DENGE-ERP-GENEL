"""Otomatik sicil numarası (KARARLAR 2026-11-20 §8).

- Sicil boş bırakılan yeni personel en büyük sayısal sicilin bir fazlasını alır.
- Toplu numaralama sicilsizleri işe giriş tarihine göre (boşlar sonda) sıralar,
  var olan sicile dokunmaz; önizleme yazmaz.
- Elle verilmiş sayısal olmayan sicil sayaca karışmaz.
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import Role, User

pytestmark = pytest.mark.integration


async def _giris(client, username: str):
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _personel(db, ad: str, **kw) -> User:
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_TEKNISYEN"))
    kisi = User(
        full_name=ad,
        username=ad.lower().replace(" ", "."),
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA",
        role_id=rol.id,
        giris_acik=False,
        **kw,
    )
    db.add(kisi)
    await db.commit()
    await db.refresh(kisi)
    return kisi


async def test_yeni_personel_sicili_otomatik_ilerler(client, db, kullanici_ac):
    await kullanici_ac("ik1", "IK")
    await _personel(db, "Eski Bir", sicil_no="0007")
    await _personel(db, "Elle Verilmis", sicil_no="G-99")
    await _giris(client, "ik1")

    r = await client.get("/api/personel/sicil/sonraki")
    assert r.status_code == 200, r.text
    assert r.json()["sicil_no"] == "0008"

    r = await client.post("/api/personel", json={"full_name": "Yeni Gelen", "birimler": []})
    assert r.status_code == 201, r.text
    assert r.json()["sicil_no"] == "0008"

    # Elle verilen sicil yine kabul edilir.
    r = await client.post(
        "/api/personel", json={"full_name": "Elle Sicilli", "sicil_no": "0100", "birimler": []}
    )
    assert r.status_code == 201, r.text
    r = await client.get("/api/personel/sicil/sonraki")
    assert r.json()["sicil_no"] == "0101"


async def test_toplu_numaralama_sirket_gecmisine_gore(client, db, kullanici_ac):
    ik = await kullanici_ac("ik2", "IK")
    ik.sicil_no = "0001"
    await db.commit()
    yeni = await _personel(db, "Yeni Kisi", ise_giris_tarihi=date(2024, 5, 1))
    eski = await _personel(db, "Eski Kisi", ise_giris_tarihi=date(2010, 1, 15))
    tarihsiz = await _personel(db, "Tarihsiz Kisi")
    await _giris(client, "ik2")

    r = await client.post("/api/personel/sicil/numarala", json={"uygula": False})
    assert r.status_code == 200, r.text
    satirlar = {s["id"]: s["sicil_no"] for s in r.json()["satirlar"]}
    assert satirlar[eski.id] == "0002"
    assert satirlar[yeni.id] == "0003"
    assert satirlar[tarihsiz.id] == "0004"
    await db.refresh(eski)
    assert eski.sicil_no is None  # önizleme yazmaz

    r = await client.post("/api/personel/sicil/numarala", json={"uygula": True})
    assert r.status_code == 200, r.text
    for kisi, beklenen in ((eski, "0002"), (yeni, "0003"), (tarihsiz, "0004")):
        await db.refresh(kisi)
        assert kisi.sicil_no == beklenen
    await db.refresh(ik)
    assert ik.sicil_no == "0001"


async def test_numaralama_tum_kapsam_ister(client, birimli_kullanici_ac):
    await birimli_kullanici_ac("sef1", "SERVIS_SEF")
    await _giris(client, "sef1")
    r = await client.post("/api/personel/sicil/numarala", json={"uygula": False})
    assert r.status_code == 403
