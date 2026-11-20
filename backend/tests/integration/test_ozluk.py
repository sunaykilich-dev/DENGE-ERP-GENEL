"""Personel özlük dosyası (2026-11-20, kullanıcı isteği).

- İK türleri yönetir ve belge yükler; personel yalnız kendi belgesini görür.
- Saha şefi iş bazlı erişir: kapsamındaki işe aktif atanmış personelin,
  türü "işte paylaşılabilir" olan belgeleri; diğer türler ve işsiz erişim 404.
- Gece dosya temizliği depoya yazan her tabloyu kullanımda sayar (İK
  belgeleri dahil; eskiden yalnız ekler sayılıyordu).
"""

import pytest
from servis_yardimci import giris
from sqlalchemy import select

from app.models import OzlukBelgeTuru
from app.models.ozluk import VARSAYILAN_OZLUK_TURLERI

pytestmark = pytest.mark.integration

OZ = "/api/ozluk"
PDF = b"%PDF-1.4\n% ozluk testi\n"


async def _tur_id(db, ad: str) -> int:
    return await db.scalar(select(OzlukBelgeTuru.id).where(OzlukBelgeTuru.ad == ad))


async def _yukle(client, kisi_id: int, tur_id: int, ad: str = "belge.pdf"):
    return await client.post(
        f"{OZ}/kisi/{kisi_id}",
        data={"tur_id": str(tur_id)},
        files={"dosya": (ad, PDF, "application/pdf")},
    )


@pytest.fixture
async def turler(db):
    """Migration tohumu (test temizliği tabloyu boşaltır)."""
    for i, (ad, paylasim) in enumerate(VARSAYILAN_OZLUK_TURLERI):
        db.add(OzlukBelgeTuru(ad=ad, sira=(i + 1) * 10, is_paylasimi=paylasim))
    await db.commit()


@pytest.fixture
async def ortam(db, turler, kullanici_ac, birimli_kullanici_ac, servis_isi_ac):
    await kullanici_ac("oz_ik", "IK")
    tek = await birimli_kullanici_ac(
        "oz_tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    diger = await birimli_kullanici_ac(
        "oz_diger", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    await birimli_kullanici_ac("oz_sef", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    so = await servis_isi_ac(durum="PLANLANDI", atananlar=[tek])
    await db.commit()
    return {"tek": tek, "diger": diger, "so": so}


async def test_tohum_turler_ve_ik_tur_yonetimi(client, db, ortam) -> None:
    await giris(client, "oz_ik")
    turler = (await client.get(f"{OZ}/turler")).json()
    assert len(turler) == 13
    assert {t["ad"] for t in turler if t["is_paylasimi"]} == {
        "Eğitim Belgeleri",
        "Ehliyet",
        "İSG",
        "SRC Belgesi",
    }
    r = await client.post(f"{OZ}/turler", json={"ad": "Sağlık Raporu", "is_paylasimi": True})
    assert r.status_code == 201, r.text
    assert (await client.post(f"{OZ}/turler", json={"ad": "sağlık raporu"})).status_code == 409
    yeni = r.json()
    r = await client.patch(
        f"{OZ}/turler/{yeni['id']}", json={"version": yeni["version"], "aktif": False}
    )
    assert r.status_code == 200 and r.json()["aktif"] is False
    assert len((await client.get(f"{OZ}/turler")).json()) == 13

    await giris(client, "oz_tek")
    assert (await client.post(f"{OZ}/turler", json={"ad": "Deneme"})).status_code == 403


async def test_ik_yukler_personel_kendi_belgesini_gorur(client, db, ortam) -> None:
    kimlik = await _tur_id(db, "Kimlik")
    await giris(client, "oz_ik")
    r = await _yukle(client, ortam["tek"].id, kimlik, "kimlik.pdf")
    assert r.status_code == 201, r.text
    belge_id = r.json()["id"]
    liste = (await client.get(f"{OZ}/kisi/{ortam['tek'].id}")).json()
    assert [b["dosya_adi"] for b in liste["belgeler"]] == ["kimlik.pdf"]

    await giris(client, "oz_tek")
    benim = (await client.get(f"{OZ}/benim")).json()
    assert [b["id"] for b in benim["belgeler"]] == [belge_id]
    r = await client.get(f"{OZ}/belgeler/{belge_id}/dosya")
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["cache-control"].startswith("no-store")
    # Personel yükleyemez ve başkasının dosyasını göremez.
    assert (await _yukle(client, ortam["tek"].id, kimlik)).status_code == 403

    await giris(client, "oz_diger")
    assert (await client.get(f"{OZ}/belgeler/{belge_id}/dosya")).status_code == 404
    assert (await client.get(f"{OZ}/benim")).json()["belgeler"] == []


async def test_sef_is_bazli_yalniz_paylasilabilir_tur(client, db, ortam) -> None:
    await giris(client, "oz_ik")
    src = (await _yukle(client, ortam["tek"].id, await _tur_id(db, "SRC Belgesi"))).json()
    kimlik = (await _yukle(client, ortam["tek"].id, await _tur_id(db, "Kimlik"))).json()
    diger = (await _yukle(client, ortam["diger"].id, await _tur_id(db, "SRC Belgesi"))).json()

    await giris(client, "oz_sef")
    so_id = ortam["so"].id
    r = await client.get(f"{OZ}/is/{so_id}")
    assert r.status_code == 200, r.text
    kisiler = r.json()["kisiler"]
    # Yalnız işe atanmış kişi, yalnız paylaşılabilir tür.
    assert [k["user_id"] for k in kisiler] == [ortam["tek"].id]
    assert [b["id"] for b in kisiler[0]["belgeler"]] == [src["id"]]

    assert (await client.get(f"{OZ}/belgeler/{src['id']}/dosya?is_id={so_id}")).status_code == 200
    # Paylaşılmayan tür, işe atanmamış kişi ve işsiz erişim kapalı.
    for belge_id, sorgu in (
        (kimlik["id"], f"?is_id={so_id}"),
        (diger["id"], f"?is_id={so_id}"),
        (src["id"], ""),
    ):
        r = await client.get(f"{OZ}/belgeler/{belge_id}/dosya{sorgu}")
        assert r.status_code == 404, (belge_id, sorgu)
    # Şef İK listesini göremez.
    assert (await client.get(f"{OZ}/kisi/{ortam['tek'].id}")).status_code == 403


async def test_dosya_temizligi_ik_ve_ozluk_dosyalarini_korur(
    db, seeded, turler, kullanici_ac, monkeypatch
) -> None:
    from app import worker
    from app.clock import FakeClock
    from app.models import IkBelgeSablonu, OzlukBelgesi
    from app.services import storage as depo

    gorulen: dict[str, set[str]] = {}

    def _yakala(kullanilan, *, en_az_yas_saat):
        gorulen["k"] = set(kullanilan)
        return 0

    monkeypatch.setattr(depo, "yetimleri_temizle", _yakala)
    tur_id = await _tur_id(db, "Kimlik")
    kisi = await kullanici_ac("oz_temiz", "IK")
    db.add(
        OzlukBelgesi(
            user_id=kisi.id, tur_id=tur_id, dosya_adi="a.pdf", storage_path="aa/bb/ozluk.pdf",
            mime_type="application/pdf", size_bytes=1, sha256="0" * 64,
        )
    )  # fmt: skip
    db.add(
        IkBelgeSablonu(
            ad="İSG talimatı", tur="TALIMAT", dosya_adi="t.pdf", storage_path="aa/bb/ik.pdf",
            mime_type="application/pdf", size_bytes=1, sha256="0" * 64,
        )
    )  # fmt: skip
    await db.flush()
    await worker.ek_dosya_temizligi(db, FakeClock())
    assert {"aa/bb/ozluk.pdf", "aa/bb/ik.pdf"} <= gorulen["k"]


async def test_yalniz_belge_turleri_ve_kaldirilan_tur_adi(client, db, ortam) -> None:
    """Rol testi 2026-11-20: .txt reddedilir; kaldırılan türdeki belge gerçek
    tür adıyla klasörlenir ("Kaldırılmış tür" diye toplanmaz)."""
    src_id = await _tur_id(db, "SRC Belgesi")
    await giris(client, "oz_ik")
    r = await client.post(
        f"{OZ}/kisi/{ortam['tek'].id}",
        data={"tur_id": str(src_id)},
        files={"dosya": ("not.txt", b"metin", "text/plain")},
    )
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
    assert (await _yukle(client, ortam["tek"].id, src_id)).status_code == 201
    tur = next(t for t in (await client.get(f"{OZ}/turler")).json() if t["id"] == src_id)
    r = await client.patch(
        f"{OZ}/turler/{src_id}", json={"version": tur["version"], "aktif": False}
    )
    assert r.status_code == 200, r.text

    await giris(client, "oz_tek")
    turler = {t["id"]: t for t in (await client.get(f"{OZ}/benim")).json()["turler"]}
    assert turler[src_id]["ad"] == "SRC Belgesi" and turler[src_id]["aktif"] is False
