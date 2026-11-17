"""İş Emri Onayı modülü (2026-11-10): onaya gelen işler birim birim.

Ekran (`/is-emri-onayi`) yeni uç açmaz; Ana Panel "Bekleyen Onaylar"
süzgecini (`kpi=onay_bekleyen`) birimle daraltır. Burada sınanan: birim
sekmesi yalnız o birimin onay bekleyen (TAMAMLANDI ya da kalite onayı
bekleyen) işlerini getirir; açık iş gelmez (PB hariçliği Ana Panel
testlerinde). Ön yüz kaydı (menü,
rota, izinler katalogda) ayrıca denetlenir.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from servis_yardimci import giris

from app.permissions import PERMISSIONS, ROLES

pytestmark = pytest.mark.integration

LISTE = "/api/teknik-servis/isler"
ON_YUZ = Path(__file__).resolve().parents[3] / "frontend" / "src"


async def test_birim_sekmesi_yalniz_o_birimin_onay_bekleyenlerini_getirir(
    client, kullanici_ac, servis_isi_ac
) -> None:
    await kullanici_ac("onayci_m", "SERVIS_YONETICI")
    guv = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI")
    await servis_isi_ac(birim="GUVENLIK", durum="SAHADA")  # açık: onaya gitmedi
    await servis_isi_ac(birim="HABERLESME", durum="PLANLANDI")  # açık
    hab = await servis_isi_ac(birim="HABERLESME", durum="TAMAMLANDI")

    await giris(client, "onayci_m")
    for birim, beklenen in (("GUVENLIK", guv.id), ("HABERLESME", hab.id)):
        r = await client.get(LISTE, params={"kpi": "onay_bekleyen", "birim": birim})
        assert r.status_code == 200, r.text
        assert [k["id"] for k in r.json()] == [beklenen], birim
        assert r.headers["X-Toplam-Kayit"] == "1"


def test_on_yuz_kaydi_ve_izinler() -> None:
    if not ON_YUZ.is_dir():
        pytest.skip("frontend/src yok (yalnız backend)")
    uygulamalar = (ON_YUZ / "fiori" / "uygulamalar.ts").read_text(encoding="utf-8")
    blok = uygulamalar[uygulamalar.index('id: "/is-emri-onayi"') :]
    blok = blok[: blok.index("}")]
    izinler = re.findall(r'"([a-z_]+\.[a-z_]+)"', blok[blok.index("izin:") :])
    assert izinler == ["servis.kalite_onay", "servis.son_onay"]
    assert set(izinler) <= set(PERMISSIONS)
    # Onay yetkisi olan bir rol ekranı görür; teknisyen görmez.
    assert "servis.son_onay" in ROLES["SERVIS_YONETICI"][1]
    assert not set(izinler) & set(ROLES["SERVIS_TEKNISYEN"][1])
    assert 'sayfa("/is-emri-onayi")' in (ON_YUZ / "fiori" / "menu.ts").read_text(encoding="utf-8")
    rotalar = (ON_YUZ / "main.tsx").read_text(encoding="utf-8")
    assert 'path="/is-emri-onayi"' in rotalar and 'path="/is-emri-onayi/:id"' in rotalar


TOPLU = "/api/teknik-servis/isler/toplu-onay"


async def test_toplu_onay_once_lider_sonra_mudur(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    """2026-11-17: çoklu seçilen işlere onaylayanın sıradaki adımı verilir.
    Zincir açıkken: lider (şef) toplu kalite onayı verir ama kapatamaz;
    müdür toplu son onayla kapatır. Teknisyen toplu onay ucuna giremez."""
    from servis_yardimci import tazele

    from app.services import settings as ayar_svc

    await birimli_kullanici_ac("mudur_t", "SERVIS_YONETICI", ["GUVENLIK"])
    await birimli_kullanici_ac("lider_t", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    await birimli_kullanici_ac("tek_t", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    a = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI")
    b = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI")
    acik = await servis_isi_ac(birim="GUVENLIK", durum="SAHADA")
    await ayar_svc.set_many(db, {"servis_kapanis_onay_zinciri": True}, None)
    await db.commit()

    def govde(*isler):
        return {"isler": [{"id": s.id, "version": s.version} for s in isler]}

    await giris(client, "tek_t")
    r = await client.post(TOPLU, json=govde(a))
    assert r.status_code == 403

    await giris(client, "lider_t")
    r = await client.post(TOPLU, json=govde(a, b, acik))
    assert r.status_code == 200, r.text
    sonuc = r.json()
    assert {(o["id"], o["adim"]) for o in sonuc["onaylanan"]} == {
        (a.id, "kalite"),
        (b.id, "kalite"),
    }
    assert [x["id"] for x in sonuc["atlanan"]] == [acik.id]
    a, b = await tazele(db, a), await tazele(db, b)
    assert a.kalite_onay_at is not None and a.status == "TAMAMLANDI"

    # Lider ikinci kez: son onay müdürde, işler atlanır ve açık kalır.
    r = await client.post(TOPLU, json=govde(a, b))
    assert r.status_code == 200 and not r.json()["onaylanan"]
    assert all("servis.son_onay" in x["neden"] for x in r.json()["atlanan"])

    await giris(client, "mudur_t")
    r = await client.post(TOPLU, json=govde(a, b))
    assert r.status_code == 200, r.text
    assert {o["adim"] for o in r.json()["onaylanan"]} == {"kapanis"}
    assert (await tazele(db, a)).status == "KAPATILDI"
    assert (await tazele(db, b)).status == "KAPATILDI"


async def test_toplu_onay_eski_surum_atlanir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("lider_s", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    so = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI")
    await giris(client, "lider_s")
    r = await client.post(TOPLU, json={"isler": [{"id": so.id, "version": so.version + 5}]})
    assert r.status_code == 200
    assert r.json()["atlanan"][0]["neden"].startswith("Kayıt başka biri")


def test_ikon_seridi_kaldirildi_onay_ekrani_coklu_secimli() -> None:
    """2026-11-17: dairesel kategori ikon şeridi hiçbir ekranda yok; Servis
    İşleri kategori vermez (tür sol menüde); onay ekranı toplu onay modunda."""
    if not ON_YUZ.is_dir():
        pytest.skip("frontend/src yok")
    seritci = (ON_YUZ / "fiori" / "KategoriSeridi.tsx").read_text(encoding="utf-8")
    assert "fl-kategori-daire" not in seritci and "<Select" in seritci
    servis = (ON_YUZ / "pages" / "ServisIsleriPage.tsx").read_text(encoding="utf-8")
    assert "kategoriler = []," in servis
    assert "teknikServisApi.topluOnay" in servis
    onay = (ON_YUZ / "pages" / "IsEmriOnayiPage.tsx").read_text(encoding="utf-8")
    assert re.search(r"^\s*onayEkrani\s*$", onay, re.M)
    for f in (ON_YUZ / "pages").glob("*.tsx"):
        assert "fl-kategori-daire" not in f.read_text(encoding="utf-8"), f.name
