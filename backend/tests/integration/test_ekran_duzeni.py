"""Kişisel ekran kutucuk düzeni (2026-11-18): herkes yalnız kendi düzenini
okur/yazar; satır yoksa `kutular` null (ekran varsayılanı); sıfırlama satırı
siler; yinelenen kod tekilleşir; geçersiz ekran/boyut 422."""

from __future__ import annotations

import pytest
from servis_yardimci import giris

pytestmark = pytest.mark.integration

YOL = "/api/ekran-duzeni/zaman-takibi"


async def test_kisisel_duzen_kaydet_oku_sifirla(client, kullanici_ac) -> None:
    await kullanici_ac("ed_a", "SERVIS_SEF")
    await kullanici_ac("ed_b", "SERVIS_SEF")
    await giris(client, "ed_a")

    r = await client.get(YOL)
    assert r.status_code == 200, r.text
    assert r.json() == {"ekran": "zaman-takibi", "kutular": None}

    govde = {
        "kutular": [
            {"kod": "aktif_sayac", "boyut": "GENIS"},
            {"kod": "mola", "gizli": True},
            {"kod": "aktif_sayac", "gizli": True},  # yinelenen: ilki kalır
        ]
    }
    r = await client.put(YOL, json=govde)
    assert r.status_code == 200, r.text
    beklenen = [
        {"kod": "aktif_sayac", "gizli": False, "boyut": "GENIS"},
        {"kod": "mola", "gizli": True, "boyut": "DAR"},
    ]
    assert r.json()["kutular"] == beklenen
    assert (await client.get(YOL)).json()["kutular"] == beklenen

    # Güncelleme aynı satırı değiştirir.
    r = await client.put(YOL, json={"kutular": [{"kod": "mola"}]})
    assert r.json()["kutular"] == [{"kod": "mola", "gizli": False, "boyut": "DAR"}]

    # Başka kullanıcı bu düzeni görmez; başka ekran ayrı.
    await giris(client, "ed_b")
    assert (await client.get(YOL)).json()["kutular"] is None
    await giris(client, "ed_a")
    assert (await client.get("/api/ekran-duzeni/servis-planlama")).json()["kutular"] is None

    r = await client.delete(YOL)
    assert r.status_code == 200 and r.json()["kutular"] is None
    assert (await client.get(YOL)).json()["kutular"] is None


async def test_gecersiz_girdi_ve_oturumsuz(client, kullanici_ac) -> None:
    r = await client.get(YOL)
    assert r.status_code == 401

    await kullanici_ac("ed_c", "IK")
    await giris(client, "ed_c")
    assert (await client.get("/api/ekran-duzeni/Büyük_Harf")).status_code == 422
    r = await client.put(YOL, json={"kutular": [{"kod": "x", "boyut": "DEV"}]})
    assert r.status_code == 422
    r = await client.put(YOL, json={"kutular": [{"kod": f"k{i}"} for i in range(61)]})
    assert r.status_code == 422
