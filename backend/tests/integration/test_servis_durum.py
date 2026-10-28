"""Tek durum kapısı `durum_degistir`, uç kısıtları, damgalar ve kancalar (TS-021; E01-03).

Gerçek hikâye: mobilite iş emri doğduğu an TAMAMLANDI'dır ve onay alanı
doğrudan atanır; servis işi bunu KOPYALAMAZ. Her geçiş makine + uç kısıtı +
kanca zincirinden geçer; ihlalde kayıt DEĞİŞMEZ (db.refresh ile sınanır).
"""

import pytest
from servis_yardimci import giris, olay_sayisi, tazele, teknisyen
from sqlalchemy import select

from app.clock import FakeClock
from app.models import ServiceHold, ServiceResult
from app.services.teknik_servis import is_emirleri, kancalar
from app.services.teknik_servis.kancalar import ServisHatasi

pytestmark = pytest.mark.integration

SONUC = {
    "sonuc": "COZULDU",
    "cozum_kanali": "YERINDE",
    "yapilan_islem": "Kablo yenilendi",
    "sure_eksik_onay": True,
}  # süre kaydı yok (TS-076)


async def test_genel_saha_ilerlemesi_ve_ayni_durum(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op_d1", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac()
    await giris(client, "op_d1")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ISLEMDE"
    assert await olay_sayisi(db, so.id, "DURUM") == 1
    # Aynı durum 409 ve olay yazılmaz.
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 409
    assert await olay_sayisi(db, so.id, "DURUM") == 1
    # Kendi ucu olan hedefler genel uçtan 400.
    for hedef in ("PLANLANDI", "BEKLEMEDE", "TAMAMLANDI", "KAPATILDI", "IPTAL"):
        r = await client.post(f"/api/teknik-servis/isler/{so.id}/durum", json={"hedef": hedef})
        assert r.status_code == 400, hedef
    # Katalog dışı hedef 422.
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/durum", json={"hedef": "KARGODA"})
    assert r.status_code == 422
    # Beklenen durum uyuşmazlığı 409, kayıt değişmez.
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/durum",
        json={"hedef": "SAHADA", "beklenen_durum": "MUSTERI_TALEBI"},
    )
    assert r.status_code == 409
    so = await tazele(db, so)
    assert so.status == "ISLEMDE"


async def test_makine_disi_gecis_409_veri_degismez(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_d2", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac()
    await giris(client, "sef_d2")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/kapat", json={})
    assert r.status_code == 409
    assert "İzin verilenler" in r.json()["detail"]
    so = await tazele(db, so)
    assert so.status == "MUSTERI_TALEBI" and so.closed_at is None


async def test_kapat_iptal_yeniden_ac_yalniz_servis_kapat(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("op_d3", "SERVIS_OPERASYON", ["GUVENLIK"])
    tek = await teknisyen(birimli_kullanici_ac, "tek_d3")
    so = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[tek])
    for kisi in ("op_d3", "tek_d3"):
        await giris(client, kisi)
        r = await client.post(f"/api/teknik-servis/isler/{so.id}/kapat", json={})
        assert r.status_code == 403
        r = await client.post(f"/api/teknik-servis/isler/{so.id}/iptal", json={"gerekce": "deneme"})
        assert r.status_code == 403
        r = await client.post(
            f"/api/teknik-servis/isler/{so.id}/yeniden-ac", json={"gerekce": "deneme"}
        )
        assert r.status_code == 403
    so = await tazele(db, so)
    assert so.status == "TAMAMLANDI"


async def test_yasam_dongusu_damgalari(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_d4", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac()
    await giris(client, "sef_d4")
    ilk_an = client.clock.now()
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TAMAMLANDI"
    client.clock.advance(hours=2)
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/kapat", json={})
    assert r.status_code == 200
    so = await tazele(db, so)
    assert so.first_completed_at == ilk_an and so.closed_at is not None

    client.clock.advance(hours=3)  # oturum 12 saatte düşer
    # M1.7 (Faz A): kapanmış iş yeniden açılmaz (409); kayıt ve sonuç değişmez.
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/yeniden-ac", json={"gerekce": "Arıza sürüyor"}
    )
    assert r.status_code == 409, r.text
    so = await tazele(db, so)
    assert so.status == "KAPATILDI" and so.closed_at is not None
    assert so.first_completed_at == ilk_an
    assert so.reopen_count == 0
    sonuclar = (
        await db.scalars(select(ServiceResult).where(ServiceResult.service_order_id == so.id))
    ).all()
    assert len(sonuclar) == 1 and sonuclar[0].gecersiz_at is None


async def test_iptal_gerekce_ve_terminal(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_d5", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac()
    await giris(client, "sef_d5")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/iptal", json={})
    assert r.status_code == 422
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/iptal", json={"gerekce": "Müşteri vazgeçti"}
    )
    assert r.status_code == 200
    so = await tazele(db, so)
    assert so.status == "IPTAL" and so.cancel_reason == "Müşteri vazgeçti"
    assert so.cancelled_at is not None
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/yeniden-ac", json={"gerekce": "Geri al"}
    )
    assert r.status_code == 409
    r = await client.get(f"/api/teknik-servis/isler/{so.id}")
    assert r.json()["sonraki_durumlar"] == []


async def test_beklemeden_iptalde_bekleme_ayni_islemde_kapanir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_d6", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac()
    await giris(client, "sef_d6")
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/bekleme", json={"neden": "MALZEME"})
    assert r.status_code == 200, r.text
    client.clock.advance(minutes=45)
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/iptal", json={"gerekce": "Parça gelmedi"}
    )
    assert r.status_code == 200
    bekleme = await db.scalar(select(ServiceHold).where(ServiceHold.service_order_id == so.id))
    assert bekleme.released_at is not None
    assert bekleme.otomatik_kapandi is True
    assert bekleme.sure_dk == 45


async def test_servis_katmani_uc_kisiti_ve_kancalar(db, servis_isi_ac, kullanici_ac) -> None:
    clock = FakeClock()
    so = await servis_isi_ac()
    with pytest.raises(ValueError):
        await is_emirleri.durum_degistir(db, so, "ISLEMDE", kaynak="yok", user=None, clock=clock)
    # TAMAMLANDI yalnız sonuç/uzaktan/atölye/bakım formu kaynağından.
    with pytest.raises(is_emirleri.IsEmriHatasi):
        await is_emirleri.durum_degistir(
            db, so, "TAMAMLANDI", kaynak="genel", user=None, clock=clock
        )
    # Sonuçsuz TAMAMLANDI (atölye yolu bile) 409.
    with pytest.raises(ServisHatasi, match="Sonuç girilmeden"):
        await is_emirleri.durum_degistir(
            db, so, "TAMAMLANDI", kaynak="atolye", user=None, clock=clock
        )
    await db.rollback()

    # durum_dogrula kancası yazmadan ÖNCE koşar: reddederse kayıt değişmez.
    async def _reddet(db_, so_, hedef, kaynak):
        if hedef == "ISLEMDE":
            raise ServisHatasi("kanca reddetti")

    kancalar.kaydet("durum_dogrula", _reddet)
    try:
        so = await tazele(db, so)
        with pytest.raises(ServisHatasi, match="kanca reddetti"):
            await is_emirleri.durum_degistir(
                db, so, "ISLEMDE", kaynak="genel", user=None, clock=clock
            )
        await db.rollback()
    finally:
        kancalar._KAYIT["durum_dogrula"].remove(_reddet)
    so = await tazele(db, so)
    assert so.status == "MUSTERI_TALEBI"
    assert await olay_sayisi(db, so.id) == 0

    # durum_degisti kancası onceki/hedef/kaynak ile çağrılır.
    cagrilar = []

    async def _kaydet(db_, so_, onceki, hedef, kaynak, clock_):
        cagrilar.append((onceki, hedef, kaynak))

    kancalar.kaydet("durum_degisti", _kaydet)
    try:
        await is_emirleri.durum_degistir(
            db, so, "PLANLAMADA", kaynak="genel", user=None, clock=clock
        )
        await db.commit()
    finally:
        kancalar._KAYIT["durum_degisti"].remove(_kaydet)
    assert cagrilar == [("MUSTERI_TALEBI", "PLANLAMADA", "genel")]


async def test_kapsam_disi_durum_404_veri_degismez(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_d7", "SERVIS_SEF", ["GUVENLIK"])
    yabanci = await servis_isi_ac(birim="HABERLESME", durum="TAMAMLANDI")
    await giris(client, "sef_d7")
    for yol, govde in (
        ("durum", {"hedef": "ISLEMDE"}),
        ("kapat", {}),
        ("iptal", {"gerekce": "deneme"}),
        ("yeniden-ac", {"gerekce": "deneme"}),
    ):
        r = await client.post(f"/api/teknik-servis/isler/{yabanci.id}/{yol}", json=govde)
        assert r.status_code == 404, yol
    yabanci = await tazele(db, yabanci)
    assert yabanci.status == "TAMAMLANDI" and yabanci.closed_at is None
    assert await olay_sayisi(db, yabanci.id) == 0
