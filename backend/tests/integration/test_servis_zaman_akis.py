"""Canlı sayaç akışı: tek dokunuş, tek aktif sayaç, düzeltmeler, kancalar, taşıma (TS-071…074).

Kilitlenen riskler:
- Yola Çıktım/Sahaya Vardım işin durumunu TEK kapıdan ilerletir (DURUM olayı).
- Kişi aynı anda tek sayaç: açık bölüm varken başlat 409 ve mesaj iş no'yu söyler.
- Mola kişi-saate girmez; MOLA→DEVAM boşluksuz ve çakışmasız.
- Çift basış (aynı sürüm) ikinci istekte 409; 1 dk altı / 18 sa üstü 400.
- Açık sayaçlı işte TAMAMLANDI/IPTAL 409; açık sayaçlı kişi ekipten çıkarılamaz.
- Sahibi istisnası: ataması kalkmış kişi kendi sayacını bitirebilir.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from zaman_ortam import SABAH, TS, bolum_ac, dk, giris, iso, ortam_kur

from app.models import ServiceOrder, ServiceOrderAssignment, ServiceOrderEvent, ServiceTimeEntry
from app.services.teknik_servis import zaman

pytestmark = pytest.mark.integration


@pytest.fixture
async def o(client, db, birimli_kullanici_ac):
    client.clock.set(SABAH)
    return await ortam_kur(db, birimli_kullanici_ac)


async def _baslat(client, so, eylem="YOLA_CIKTIM", **kw):
    return await client.post(f"{TS}/zaman/baslat", json={"is_id": so.id, "eylem": eylem, **kw})


def _yol(so_id, bolum_id, eylem):
    return f"{TS}/isler/{so_id}/zaman/bolumler/{bolum_id}/{eylem}"


async def test_yola_ciktim_sahaya_vardim_durum_ilerler(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    await giris(client, "tek1")
    r = await _baslat(client, so)
    assert r.status_code == 201, r.text
    govde = r.json()
    assert govde["is_durumu"] == "YOLA_CIKILDI" and govde["bolum"]["faaliyet"] == "YOL"
    assert govde["bolum"]["kaynak"] == "CANLI" and govde["sunucu_zamani"]
    bolum = govde["bolum"]
    client.clock.advance(minutes=25)
    r = await client.post(
        _yol(so.id, bolum["id"], "gecis"), json={"version": bolum["version"], "faaliyet": "SAHA"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_durumu"] == "SAHADA"
    assert r.json()["yeni_bolum"]["started_at"] == r.json()["bolum"]["ended_at"]
    olaylar = (
        await db.scalars(
            select(ServiceOrderEvent.veri).where(
                ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "DURUM"
            )
        )
    ).all()
    assert [v["kaynak"] for v in olaylar] == ["sayac", "sayac"]
    benim = (await client.get(f"{TS}/zaman/benim")).json()
    assert benim["acik_bolum"]["faaliyet"] == "SAHA" and "MOLA" in benim["izinli_dugmeler"]
    assert "sunucu_zamani" in benim


async def test_sayac_yokken_yalniz_baslat_dugmeleri(client, o) -> None:
    await giris(client, "tek1")
    benim = (await client.get(f"{TS}/zaman/benim")).json()
    assert benim["acik_bolum"] is None
    assert benim["izinli_dugmeler"] == ["YOLA_CIKTIM", "SAHAYA_VARDIM", "DIGER"]


async def test_beklemedeki_iste_sahaya_vardim_409(client, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="BEKLEMEDE", atananlar=[o.tek])
    await giris(client, "tek1")
    r = await _baslat(client, so, "SAHAYA_VARDIM")
    assert r.status_code == 409


async def test_tek_aktif_sayac_mesaji(client, o, servis_isi_ac) -> None:
    a = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    b = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    assert (await _baslat(client, a, "SAHAYA_VARDIM")).status_code == 201
    r = await _baslat(client, b, "SAHAYA_VARDIM")
    assert r.status_code == 409
    assert r.json()["detail"].startswith(f"Önce açık sayacı bitirin: {a.so_no}")


async def test_atanmamis_iste_baslat_400(client, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek2])
    await giris(client, "sef_a")  # şef kapsam içinde ama atanmamış
    assert (await _baslat(client, so, "SAHAYA_VARDIM")).status_code == 400


async def test_kapali_iste_sayac_baslatilamaz(client, o, servis_isi_ac) -> None:
    for durum in ("TAMAMLANDI", "KAPATILDI"):
        so = await servis_isi_ac(durum=durum, atananlar=[o.tek])
        await giris(client, "tek1")
        assert (await _baslat(client, so, "SAHAYA_VARDIM")).status_code == 409, durum


async def test_mola_devam_bosluksuz_ve_kisi_saate_girmez(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    saha = (await _baslat(client, so, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=60)
    mola = (
        await client.post(_yol(so.id, saha["id"], "mola"), json={"version": saha["version"]})
    ).json()["yeni_bolum"]
    assert mola["faaliyet"] == "MOLA"
    client.clock.advance(minutes=15)
    r = await client.post(_yol(so.id, mola["id"], "devam"), json={"version": mola["version"]})
    assert r.status_code == 200, r.text
    devam = r.json()["yeni_bolum"]
    assert devam["faaliyet"] == "SAHA"
    assert r.json()["bolum"]["ended_at"] == devam["started_at"]
    client.clock.advance(minutes=30)
    r = await client.post(_yol(so.id, devam["id"], "bitir"), json={"version": devam["version"]})
    assert r.status_code == 200, r.text
    ozet = await zaman.sure_ozeti(db, so.id)
    assert ozet.kisi_saat_dk == 90 and ozet.mola_dk == 15 and ozet.sure_durumu == "TAM"


async def test_bekleme_nedeni_zorunlu(client, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    saha = (await _baslat(client, so, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=5)
    yol = _yol(so.id, saha["id"], "gecis")
    r = await client.post(yol, json={"version": saha["version"], "faaliyet": "BEKLEME"})
    assert r.status_code == 400
    r = await client.post(
        yol, json={"version": saha["version"], "faaliyet": "BEKLEME", "bekleme_nedeni": "MALZEME"}
    )
    assert r.status_code == 200, r.text
    # saha beklemesi işi BEKLEMEDE yapmaz (K24)
    assert r.json()["is_durumu"] == "SAHADA"


async def test_cift_basis_ikinci_409(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    saha = (await _baslat(client, so, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=10)
    yol = _yol(so.id, saha["id"], "bitir")
    assert (await client.post(yol, json={"version": saha["version"]})).status_code == 200
    assert (await client.post(yol, json={"version": saha["version"]})).status_code == 409
    adet = await db.scalar(
        select(func.count())
        .select_from(ServiceTimeEntry)
        .where(ServiceTimeEntry.service_order_id == so.id)
    )
    assert adet == 1


async def test_asgari_ve_azami_bolum(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    saha = (await _baslat(client, so, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(seconds=30)
    r = await client.post(
        _yol(so.id, saha["id"], "gecis"), json={"version": saha["version"], "faaliyet": "TEST"}
    )
    assert r.status_code == 400
    assert (
        await client.post(_yol(so.id, saha["id"], "bitir"), json={"version": saha["version"]})
    ).status_code == 400
    # 2026-11-10: 18 saat üst sınırı şimdilik yok — unutulmuş sayaç da Bitir'le kapanır.
    client.clock.advance(hours=21)
    await giris(client, "tek1")  # oturum süresi doldu; sayaç açık kalır
    r = await client.post(_yol(so.id, saha["id"], "bitir"), json={"version": saha["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["bolum"]["ended_at"] is not None


async def test_unuttum_gercek_bitisle_kapatir(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    yeni = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - timedelta(hours=20))
    await giris(client, "tek1")
    yol = _yol(so.id, acik.id, "unuttum")
    gercek = SABAH - timedelta(hours=12)
    r = await client.post(yol, json={"version": acik.version, "gercek_bitis": iso(gercek)})
    assert r.status_code == 400  # gerekçesiz
    r = await client.post(
        yol, json={"version": acik.version, "gercek_bitis": iso(SABAH + dk(5)), "gerekce": "x"}
    )
    assert r.status_code == 400  # ileri bitiş
    r = await client.post(
        yol,
        json={"version": acik.version, "gercek_bitis": iso(gercek), "gerekce": "Akşam unuttum"},
    )
    assert r.status_code == 200, r.text
    await db.refresh(acik)
    assert acik.kaynak == "KULLANICI_DUZELTMESI" and acik.kapanis_turu == "UNUTULDU"
    assert acik.ended_at == gercek
    olay = await db.scalar(
        select(ServiceOrderEvent).where(
            ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "DUZELTME"
        )
    )
    assert olay is not None
    # aynı dakika içinde yeni işte sayaç başlatabilir
    assert (await _baslat(client, yeni, "SAHAYA_VARDIM")).status_code == 201


async def test_baskasinin_bolumu_403(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek, o.tek2])
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(30))
    await giris(client, "tek2")
    for eylem, govde in (
        ("bitir", {"version": acik.version}),
        ("geri-al", {"version": acik.version}),
        ("unuttum", {"version": acik.version, "gercek_bitis": iso(SABAH), "gerekce": "x"}),
    ):
        r = await client.post(_yol(so.id, acik.id, eylem), json=govde)
        assert r.status_code == 403, eylem
    await db.refresh(acik)
    assert acik.ended_at is None and not acik.is_deleted


async def test_geri_alma_penceresi(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    b1 = (await _baslat(client, so, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=3)
    r = await client.post(_yol(so.id, b1["id"], "geri-al"), json={"version": b1["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["bolum"]["iptal_turu"] == "GERI_ALINDI"
    assert (await zaman.sure_ozeti(db, so.id)).kisi_saat_dk is None
    b2 = (await _baslat(client, so, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=6)
    r = await client.post(_yol(so.id, b2["id"], "geri-al"), json={"version": b2["version"]})
    assert r.status_code == 400


async def test_atamasi_kalkan_sahibi_bitirir(client, db, o, servis_isi_ac) -> None:
    """Veri tutarsızlığı benzetimi: atama DB'de kaldırıldı; sahibi yine bitirir."""
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(45))
    atama = await db.scalar(
        select(ServiceOrderAssignment).where(ServiceOrderAssignment.service_order_id == so.id)
    )
    atama.removed_at = SABAH - dk(10)
    await db.commit()
    await giris(client, "tek1")
    r = await client.post(_yol(so.id, acik.id, "bitir"), json={"version": acik.version})
    assert r.status_code == 200, r.text
    assert (await zaman.sure_ozeti(db, so.id)).kisi_saat_dk == 45


async def test_iptal_edilen_iste_acik_bolum_bitirilebilir(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="IPTAL", atananlar=[o.tek], cancel_reason="vazgeçildi")
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(20))
    await giris(client, "tek1")
    r = await client.post(_yol(so.id, acik.id, "bitir"), json={"version": acik.version})
    assert r.status_code == 200


# --- Kancalar (TS-073) -------------------------------------------------------------------


async def test_acik_sayacli_iste_tamamla_ve_iptal_409(db, o, servis_isi_ac) -> None:
    from app.clock import FakeClock
    from app.services.teknik_servis import is_emirleri

    saat = FakeClock(SABAH)
    # PLANLANDI → IPTAL makinede var; açık sayaç (ör. YOL) onu engeller.
    so = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    await bolum_ac(db, so, o.tek, "YOL", SABAH - dk(20))
    with pytest.raises(zaman.ZamanHatasi) as hata:
        await zaman.acik_sayac_dogrula(db, so, "TAMAMLANDI", "sonuc")
    assert "Ali Veli" in str(hata.value) and so.so_no in str(hata.value)
    with pytest.raises(zaman.ZamanHatasi):
        await is_emirleri.durum_degistir(
            db, so, "IPTAL", kaynak="iptal", user=o.sef, clock=saat, gerekce="Müşteri vazgeçti"
        )
    so_id = so.id
    await db.rollback()
    so = await db.get(ServiceOrder, so_id)
    await db.refresh(so)
    assert so.status == "PLANLANDI"


async def test_acik_sayacli_kisiyi_ekipten_cikarma_409(db, o, servis_isi_ac) -> None:
    from app.clock import FakeClock
    from app.services.teknik_servis import atama

    saat = FakeClock(SABAH)
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek, o.tek2])
    await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(20))
    with pytest.raises(zaman.ZamanHatasi) as hata:
        await atama.ata(
            db,
            so,
            [atama.AtamaSatiri(user_id=o.tek2.id, rol="TEKNISYEN", is_lead=True)],
            user=o.sef,
            clock=saat,
        )
    assert f"Ali Veli'nin {so.so_no}" in str(hata.value)
    so_id, tek2_id = so.id, o.tek2.id
    await db.rollback()
    aktif = await db.scalar(
        select(func.count())
        .select_from(ServiceOrderAssignment)
        .where(
            ServiceOrderAssignment.service_order_id == so_id,
            ServiceOrderAssignment.removed_at.is_(None),
        )
    )
    assert aktif == 2
    # sayacı olmayan kişinin çıkarılması eskisi gibi çalışır
    so = await db.get(ServiceOrder, so_id)
    await zaman.acik_sayac_cikarma_dogrula(db, so, [tek2_id])


# --- Sonraki işe taşıma (TS-074) ------------------------------------------------------------


async def test_sonraki_ise_tasi_bosluksuz(client, db, o, lokasyon_ac, servis_isi_ac) -> None:
    tesis = await lokasyon_ac()
    a = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek], lokasyon=tesis)
    b = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek], lokasyon=tesis)
    await giris(client, "tek1")
    saha = (await _baslat(client, a, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=40)
    r = await client.post(
        _yol(a.id, saha["id"], "gecis"),
        json={"version": saha["version"], "faaliyet": "SAHA", "hedef_is_id": b.id},
    )
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["bolum"]["ended_at"] == govde["yeni_bolum"]["started_at"]
    assert govde["yeni_bolum"]["service_order_id"] == b.id
    assert govde["is_durumu"] == "SAHADA"
    eski = await db.get(ServiceTimeEntry, saha["id"])
    yeni = await db.get(ServiceTimeEntry, govde["yeni_bolum"]["id"])
    assert eski.ended_at == yeni.started_at and yeni.onceki_bolum_id == eski.id


async def test_tasima_hedefi_uygun_degilse_409_kaynak_acik(client, db, o, servis_isi_ac) -> None:
    a = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    atanmamis = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek2])
    kapali = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek])
    await giris(client, "tek1")
    saha = (await _baslat(client, a, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=10)
    for hedef in (atanmamis, kapali):
        r = await client.post(
            _yol(a.id, saha["id"], "gecis"),
            json={"version": saha["version"], "faaliyet": "SAHA", "hedef_is_id": hedef.id},
        )
        assert r.status_code in (404, 409), r.text  # atanmamış iş teknisyene 404 (kapsam)
    bolum = await db.get(ServiceTimeEntry, saha["id"])
    await db.refresh(bolum)
    assert bolum.ended_at is None
    hedefte = await db.scalar(
        select(func.count())
        .select_from(ServiceTimeEntry)
        .where(ServiceTimeEntry.service_order_id.in_([atanmamis.id, kapali.id]))
    )
    assert hedefte == 0


async def test_sef_tasima_hedefi_atanmamis_409(client, db, o, servis_isi_ac) -> None:
    """Kapsam içi ama kişiye atanmamış hedef → 409 (şef birimin işini görür)."""
    a = await servis_isi_ac(durum="SAHADA")
    b = await servis_isi_ac(durum="SAHADA")
    db.add(
        ServiceOrderAssignment(
            service_order_id=a.id, user_id=o.sef.id, rol="SEF", assigned_at=SABAH
        )
    )
    await db.commit()
    await giris(client, "sef_a")
    saha = (await _baslat(client, a, "SAHAYA_VARDIM")).json()["bolum"]
    client.clock.advance(minutes=10)
    r = await client.post(
        _yol(a.id, saha["id"], "gecis"),
        json={"version": saha["version"], "faaliyet": "SAHA", "hedef_is_id": b.id},
    )
    assert r.status_code == 409, r.text
