"""Hesap/lokasyon birleştirme, müşteri kartı servis sekmesi, kapsam bilgisi (TS-192,
E14-07/E14-12/E14-17)."""

import httpx
import pytest
from sqlalchemy import func, select

from app.models import (
    Account,
    AccountAlias,
    AccountMerge,
    Address,
    Contact,
    ServiceOrder,
)

pytestmark = pytest.mark.integration

ANA = "/api/teknik-servis/ana-veri"


@pytest.fixture
async def giris(client):
    from app.main import app

    acik: list[httpx.AsyncClient] = []

    async def _ac(username: str) -> httpx.AsyncClient:
        ist = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Requested-With": "fetch"},
        )
        r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
        assert r.status_code == 200, r.text
        acik.append(ist)
        return ist

    yield _ac
    for ist in acik:
        await ist.aclose()


@pytest.fixture
async def yonetici(birimli_kullanici_ac, giris):
    await birimli_kullanici_ac("av_yon", "SERVIS_YONETICI", ["GUVENLIK"])
    return await giris("av_yon")


async def _taze(db, model, kimlik):
    nesne = await db.get(model, kimlik)
    await db.refresh(nesne)
    return nesne


async def _hesap(db, ad, **kw) -> Account:
    h = Account(title=ad, is_musteri=True, **kw)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


# --- Birleştirme ----------------------------------------------------------------------


async def test_hesap_birlestirme_onizleme_uygula(
    yonetici, db, lokasyon_ac, servis_isi_ac, ekipman_ac
) -> None:
    hedef = await _hesap(db, "Akyaka Park AVM A.Ş.")
    kaynak = await _hesap(db, "AKYAKA OTOPARK ISLETME", tax_no="1234567890")
    tesis = await lokasyon_ac(kaynak, ad="Akyaka Otopark")
    db.add(Contact(account_id=kaynak.id, full_name="Saha Kişi", address_id=tesis.id))
    await db.commit()
    so = await servis_isi_ac(musteri=kaynak, lokasyon=tesis)
    so.coverage_status = "KAPSAM_DISI"
    so.coverage_snapshot = {"kapsam_durumu": "KAPSAM_DISI"}
    await db.commit()
    e = await ekipman_ac(musteri=kaynak, lokasyon=tesis)

    govde = {"tur": "HESAP", "kaynak_id": kaynak.id, "hedef_id": hedef.id}
    once = await db.scalar(select(func.count()).select_from(AccountMerge))
    on = await yonetici.post(f"{ANA}/birlestirme/onizle", json=govde)
    assert on.status_code == 200, on.text
    plan = on.json()
    assert plan["engeller"] == []
    assert plan["tasinacak"]["service_orders.customer_id"] == 1
    assert plan["tasinacak"]["addresses.account_id"] == 1
    assert plan["doldurulacak"] == {"tax_no": "1234567890"}
    assert await db.scalar(select(func.count()).select_from(AccountMerge)) == once  # yazmaz

    # Beklenen uyuşmazsa 409, hiçbir şey taşınmaz.
    r = await yonetici.post(
        f"{ANA}/birlestirme/uygula",
        json={**govde, "gerekce": "Aynı firma", "beklenen": {"x.y": 1}},
    )
    assert r.status_code == 409
    await db.refresh(so)
    assert so.customer_id == kaynak.id

    r = await yonetici.post(
        f"{ANA}/birlestirme/uygula",
        json={**govde, "gerekce": "Aynı firma iki kayıt", "beklenen": plan["tasinacak"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["tasinan"] == plan["tasinacak"]  # kabul 2

    so = await _taze(db, ServiceOrder, so.id)
    assert so.customer_id == hedef.id
    assert so.coverage_snapshot == {"kapsam_durumu": "KAPSAM_DISI"}  # anlık görüntü değişmez
    assert (await _taze(db, Address, tesis.id)).account_id == hedef.id
    k = await _taze(db, Account, kaynak.id)
    assert k.is_deleted and k.merged_into_id == hedef.id
    assert (await _taze(db, Account, hedef.id)).tax_no == "1234567890"
    assert (await _taze(db, type(e), e.id)).account_id == hedef.id
    takma = await db.scalar(select(AccountAlias).where(AccountAlias.kaynak == "BIRLESTIRME"))
    assert takma is not None and takma.account_id == hedef.id

    # Kaynak unvanıyla arama hedefi bulur (kabul 6).
    ara = await yonetici.get(f"{ANA}/musteri-ara", params={"q": "otopark isletme"})
    assert hedef.id in [x["id"] for x in ara.json()]
    kayitlar = await yonetici.get(f"{ANA}/birlestirmeler")
    assert kayitlar.json()[0]["kaynak_id"] == kaynak.id


async def test_hakedis_referansli_hesap_409(yonetici, db) -> None:
    from app.models import InstallationPartner

    hedef = await _hesap(db, "Hedef Ltd")
    kaynak = await _hesap(db, "Montaj Noktası Ltd", is_montaj_noktasi=True)
    db.add(InstallationPartner(account_id=kaynak.id))
    await db.commit()
    govde = {"tur": "HESAP", "kaynak_id": kaynak.id, "hedef_id": hedef.id}
    plan = (await yonetici.post(f"{ANA}/birlestirme/onizle", json=govde)).json()
    assert plan["engeller"]
    r = await yonetici.post(
        f"{ANA}/birlestirme/uygula",
        json={**govde, "gerekce": "Deneme birleştirme", "beklenen": plan["tasinacak"]},
    )
    assert r.status_code == 409
    await db.refresh(kaynak)
    assert not kaynak.is_deleted


async def test_gecersiz_hedef_400_ve_rbac(yonetici, db, birimli_kullanici_ac, giris) -> None:
    a = await _hesap(db, "Pasif Hedef", is_active=False)
    b = await _hesap(db, "Kaynak X")
    r = await yonetici.post(
        f"{ANA}/birlestirme/onizle", json={"tur": "HESAP", "kaynak_id": b.id, "hedef_id": a.id}
    )
    assert r.status_code == 400
    r = await yonetici.post(
        f"{ANA}/birlestirme/onizle", json={"tur": "HESAP", "kaynak_id": b.id, "hedef_id": b.id}
    )
    assert r.status_code == 400
    await birimli_kullanici_ac("av_sef", "SERVIS_SEF", ["GUVENLIK"])
    sef = await giris("av_sef")
    r = await sef.post(
        f"{ANA}/birlestirme/onizle", json={"tur": "HESAP", "kaynak_id": b.id, "hedef_id": a.id}
    )
    assert r.status_code == 403


async def test_yapay_hata_hicbir_satir_tasinmaz(yonetici, db, servis_isi_ac, monkeypatch) -> None:
    from app.services import hesap_birlestir

    hedef = await _hesap(db, "Atomik Hedef")
    kaynak = await _hesap(db, "Atomik Kaynak")
    so = await servis_isi_ac(musteri=kaynak)
    govde = {"tur": "HESAP", "kaynak_id": kaynak.id, "hedef_id": hedef.id}
    plan = (await yonetici.post(f"{ANA}/birlestirme/onizle", json=govde)).json()

    gercek = hesap_birlestir.referans_kolonlari
    cagri = {"n": 0}

    async def bozuk(db_, tablo):
        cagri["n"] += 1
        sonuc = await gercek(db_, tablo)
        if cagri["n"] >= 2:  # uygulamadaki ikinci okuma: araya bozuk kolon girer
            return [*sonuc[:1], ("yok_tablo", "kolon"), *sonuc[1:]]
        return sonuc

    monkeypatch.setattr(hesap_birlestir, "referans_kolonlari", bozuk)
    with pytest.raises(Exception):  # noqa: B017 - ham SQL hatası, uç 500 döner
        await yonetici.post(
            f"{ANA}/birlestirme/uygula",
            json={**govde, "gerekce": "Atomik deneme", "beklenen": plan["tasinacak"]},
        )
    assert (await _taze(db, ServiceOrder, so.id)).customer_id == kaynak.id
    assert not (await _taze(db, Account, kaynak.id)).is_deleted


async def test_lokasyon_birlestirme(yonetici, db, lokasyon_ac, servis_isi_ac) -> None:
    h = await _hesap(db, "Lokasyon Sahibi")
    hedef = await lokasyon_ac(h, ad="Merkez Bina")
    kaynak = await lokasyon_ac(h, ad="Merkez Bina Blok A")
    so = await servis_isi_ac(musteri=h, lokasyon=kaynak)
    govde = {"tur": "LOKASYON", "kaynak_id": kaynak.id, "hedef_id": hedef.id}
    plan = (await yonetici.post(f"{ANA}/birlestirme/onizle", json=govde)).json()
    r = await yonetici.post(
        f"{ANA}/birlestirme/uygula",
        json={**govde, "gerekce": "Aynı bina", "beklenen": plan["tasinacak"]},
    )
    assert r.status_code == 201, r.text
    assert (await _taze(db, ServiceOrder, so.id)).address_id == hedef.id
    assert not (await _taze(db, Address, kaynak.id)).is_active


# --- Servis kartı (E14-07) ---------------------------------------------------------------


async def test_servis_karti_acik_is_liste_ile_ayni(
    yonetici, db, lokasyon_ac, servis_isi_ac, birimli_kullanici_ac, giris
) -> None:
    h = await _hesap(db, "Kart Müşterisi")
    t = await lokasyon_ac(h, ad="Kart Tesisi")
    await servis_isi_ac(musteri=h, lokasyon=t)
    await servis_isi_ac(musteri=h)
    await servis_isi_ac(musteri=h, birim="HABERLESME")
    await servis_isi_ac(musteri=h, durum="IPTAL", cancel_reason="test")

    await birimli_kullanici_ac("av_sef", "SERVIS_SEF", ["GUVENLIK"])
    sef = await giris("av_sef")
    canli_once = await sef.get(f"/api/hesaplar/{h.id}/kart")
    r = await sef.get(f"{ANA}/musteriler/{h.id}/servis-karti")
    assert r.status_code == 200, r.text
    kart = r.json()
    liste = await sef.get(
        "/api/teknik-servis/isler", params={"musteri_id": h.id, "durum_grubu": "ACIK"}
    )
    assert kart["acik_is_sayisi"] == int(liste.headers["X-Toplam-Kayit"]) == 2  # birim kapsamı
    assert kart["lokasyonlar"][0]["acik_is"] == 1
    for anahtar in ("toplam", "ucret", "bedel"):
        assert anahtar not in str(kart.get("sozlesmeler", []))
    canli_sonra = await sef.get(f"/api/hesaplar/{h.id}/kart")
    assert canli_once.json() == canli_sonra.json()

    await birimli_kullanici_ac("av_tekn", "SERVIS_TEKNISYEN", ["GUVENLIK"])
    tekn = await giris("av_tekn")
    assert (await tekn.get(f"{ANA}/musteriler/{h.id}/servis-karti")).status_code == 403


async def test_servis_karti_ucret_yalniz_maliyet_gorende(
    db, client, birimli_kullanici_ac, giris, sozlesme_ac, kullanici_ac
) -> None:
    h = await _hesap(db, "Ücret Müşterisi")
    await sozlesme_ac(musteri=h, fee_per_visit=100)
    # Şef maliyet görmez; TS Yöneticisi G4.4 / §7.7 ile görür.
    await birimli_kullanici_ac("av_s2", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    s = await giris("av_s2")
    kart = (await s.get(f"{ANA}/musteriler/{h.id}/servis-karti")).json()
    assert kart["sozlesmeler"] and "ucret" not in kart["sozlesmeler"][0]
    await birimli_kullanici_ac("av_y2", "SERVIS_YONETICI", ["GUVENLIK"])
    y = await giris("av_y2")
    kart = (await y.get(f"{ANA}/musteriler/{h.id}/servis-karti")).json()
    assert kart["sozlesmeler"][0]["ucret"] == 100.0
    await kullanici_ac("av_admin", "ADMIN")
    adm = await giris("av_admin")
    kart = (await adm.get(f"{ANA}/musteriler/{h.id}/servis-karti")).json()
    assert kart["sozlesmeler"][0]["ucret"] == 100.0


async def test_bos_kartta_aciklama(yonetici, db) -> None:
    h = await _hesap(db, "Boş Müşteri")
    kart = (await yonetici.get(f"{ANA}/musteriler/{h.id}/servis-karti")).json()
    assert "Eşleştirme" in kart["aciklama"]


# --- Kapsam bilgisi ve anlık görüntü (E14-17) ------------------------------------------------


async def test_kapsam_bilgisi_tutar_yok_tarihsiz_bilinmiyor(
    yonetici, db, lokasyon_ac, sozlesme_ac
) -> None:
    h = await _hesap(db, "Kapsam Müşterisi")
    t = await lokasyon_ac(h, ad="Kapsam Tesisi")
    await sozlesme_ac(
        musteri=h, lokasyon=t, status="TEYIT_BEKLIYOR", teyit_gerekcesi="Göç", fee_per_visit=50
    )
    r = await yonetici.get(f"{ANA}/kapsam-bilgisi", params={"hesap_id": h.id, "lokasyon_id": t.id})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["kapsam_durumu"] == "BILINMIYOR"
    assert b["aktif_sozlesmeler"][0]["donem"] == "Dönem bilgisi yok"
    assert "ucret" not in r.text and "tutar" not in r.text


async def test_acilista_kapsam_damgasi_bir_kez(yonetici, db) -> None:
    h = await _hesap(db, "Damga Müşterisi")
    tesis = Address(account_id=h.id, kind="TESIS", label="Tesis", site_name="Damga Tesisi")
    db.add(tesis)
    await db.commit()
    r = await yonetici.post(
        "/api/teknik-servis/isler",
        json={
            "birim": "GUVENLIK",
            "tur": "ARIZA",
            "konu": "Damga",
            "customer_id": h.id,
            "talep_kanali": "TELEFON",
            "iletisim_ad": "Saha Yetkilisi",
            "iletisim_telefon": "+905321112233",
            "address_id": tesis.id,
        },
    )
    assert r.status_code in (200, 201), r.text
    so = await _taze(db, ServiceOrder, r.json()["id"])
    assert so.coverage_status == "KAPSAM_DISI"
    assert so.coverage_snapshot["kapsam_durumu"] == "KAPSAM_DISI"
