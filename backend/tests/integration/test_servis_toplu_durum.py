"""Servis İşleri listesinden hızlı durum (2026-11-18, kullanıcı isteği).

Liste satırı kullanıcının yetkili olduğu geçişleri (`gecisler`) taşır; ön yüz
sağ tık / ⋯ menüsünü bundan kurar. Toplu uç (`/isler/toplu-durum`) yalnız
genel saha durumlarını kabul eder ve her işi tekli `/durum` ucunun kuralıyla
ayrı ayrı sınar: uymayan iş nedeniyle atlanır, diğerleri taşınır.
"""

from __future__ import annotations

import pytest
from servis_yardimci import giris, tazele

pytestmark = pytest.mark.integration

LISTE = "/api/teknik-servis/isler"
TOPLU = "/api/teknik-servis/isler/toplu-durum"


def _govde(hedef: str, *isler, surum_farki: int = 0) -> dict:
    return {
        "hedef": hedef,
        "isler": [{"id": s.id, "version": s.version + surum_farki} for s in isler],
    }


async def test_liste_satiri_yetkili_gecisleri_tasir(
    client, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("hd_mudur", "SERVIS_YONETICI", ["GUVENLIK"])
    so = await servis_isi_ac(birim="GUVENLIK", durum="PLANLAMADA")
    await giris(client, "hd_mudur")
    r = await client.get(LISTE)
    assert r.status_code == 200, r.text
    satir = next(x for x in r.json() if x["id"] == so.id)
    hedefler = {(g["uc"], g["hedef"]) for g in satir["gecisler"]}
    assert ("genel", "ISLEMDE") in hedefler
    assert ("planla", "PLANLANDI") in hedefler
    assert all(g["yetkili"] for g in satir["gecisler"])


async def test_toplu_durum_uygun_olanlari_tasir_digerlerini_atlar(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("hd_sef", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    a = await servis_isi_ac(birim="GUVENLIK", durum="PLANLAMADA")
    b = await servis_isi_ac(birim="GUVENLIK", durum="PLANLANDI")
    bitmis = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI")
    baska_birim = await servis_isi_ac(birim="HABERLESME", durum="PLANLAMADA")

    await giris(client, "hd_sef")
    r = await client.post(TOPLU, json=_govde("ISLEMDE", a, b, bitmis, baska_birim))
    assert r.status_code == 200, r.text
    sonuc = r.json()
    assert {x["id"] for x in sonuc["tasinan"]} == {a.id, b.id}
    atlanan = {x["id"]: x for x in sonuc["atlanan"]}
    assert set(atlanan) == {bitmis.id, baska_birim.id}
    # Kapsam dışı iş varlığı sızdırılmaz.
    assert atlanan[baska_birim.id]["so_no"] is None
    assert (await tazele(db, a)).status == "ISLEMDE"
    assert (await tazele(db, b)).status == "ISLEMDE"
    assert (await tazele(db, bitmis)).status == "TAMAMLANDI"


async def test_toplu_durum_eski_surum_atlanir(client, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("hd_sef2", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    so = await servis_isi_ac(birim="GUVENLIK", durum="PLANLAMADA")
    await giris(client, "hd_sef2")
    r = await client.post(TOPLU, json=_govde("ISLEMDE", so, surum_farki=3))
    assert r.status_code == 200
    assert not r.json()["tasinan"]
    assert r.json()["atlanan"][0]["neden"].startswith("Kayıt başka biri")


async def test_toplu_durum_bilgi_isteyen_hedef_ve_yetkisiz_reddedilir(
    client, birimli_kullanici_ac, kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("hd_sef3", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    await kullanici_ac("hd_finans", "FINANS_YONETICI")
    so = await servis_isi_ac(birim="GUVENLIK", durum="PLANLAMADA")

    await giris(client, "hd_sef3")
    # Planla/bekleme/sonuç/iptal bilgi ister: toplu uçtan verilmez (422).
    for hedef in ("PLANLANDI", "BEKLEMEDE", "TAMAMLANDI", "IPTAL"):
        r = await client.post(TOPLU, json=_govde(hedef, so))
        assert r.status_code == 422, hedef

    await giris(client, "hd_finans")  # servis.yaz yok
    r = await client.post(TOPLU, json=_govde("ISLEMDE", so))
    assert r.status_code == 403
