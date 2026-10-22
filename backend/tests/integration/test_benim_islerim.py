"""Benim İşlerim (tek mobil ekran) ve "Bugünüm" (TS-077/078).

Kilitlenen riskler:
- Teknisyen yalnız KENDİNE atanmış açık işleri görür; "Tümü" yalnız
  `servis.planla` ile ve yalnız kendi biriminde.
- Gün YEREL: 23:30 UTC'de dünkü plan GECIKEN grubundadır.
- Aynı gün + tesis tek ziyaret kartı; her iş ayrı seçilebilir.
- Kart yanıtında fiyat/tutar/maliyet anahtarı yok; kapsam dışı kart 404.
- Bugünüm yalnız kişinin kendisi; süre eksik listesi "0 dk" yazmaz,
  telefonla çözülen iş listede yok.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from zaman_ortam import SABAH, TS, bolum_ac, dk, giris, ortam_kur

from app.models import ServiceOrderEvent, ServicePlan, ServicePlanMember, ServiceResult

pytestmark = pytest.mark.integration


@pytest.fixture
async def o(client, db, birimli_kullanici_ac):
    client.clock.set(SABAH)
    return await ortam_kur(db, birimli_kullanici_ac)


async def _plan(db, so, gun: date, *, saat: int | None = None, uyeler=()):
    # `start_time` yerel saat; `starts_at` UTC (Türkiye UTC+3).
    bas = datetime(gun.year, gun.month, gun.day, saat - 3, 0, tzinfo=UTC) if saat else None
    plan = ServicePlan(
        service_order_id=so.id,
        plan_date=gun,
        start_time=time(saat, 0) if saat else None,
        starts_at=bas,
        ends_at=bas + timedelta(minutes=60) if bas else None,
        duration_min=60,
        change_type="ILK_PLAN",
    )
    db.add(plan)
    await db.flush()
    for kisi in uyeler:
        db.add(ServicePlanMember(plan_id=plan.id, user_id=kisi.id, rol="TEKNISYEN"))
    await db.commit()
    return plan


def _isler(govde, grup=None):
    return [
        i["so_no"]
        for g in govde["gruplar"]
        if grup is None or g["kod"] == grup
        for z in g["ziyaretler"]
        for i in z["isler"]
    ]


async def test_teknisyen_yalniz_kendi_islerini_gorur(client, db, o, servis_isi_ac) -> None:
    benim = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    baskasi = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek2])
    kapali = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek])
    await giris(client, "tek1")
    r = await client.get(f"{TS}/benim-islerim")
    assert r.status_code == 200, r.text
    gorunen = _isler(r.json())
    assert benim.so_no in gorunen
    assert baskasi.so_no not in gorunen and kapali.so_no not in gorunen
    assert r.json()["sunucu_zamani"] and r.json()["acik_bolum"] is None
    # "Tümü" teknisyene kapalı
    assert (await client.get(f"{TS}/benim-islerim?gorunum=tumu")).status_code == 403


async def test_sef_varsayilan_kendi_tumu_biriminde(client, db, o, servis_isi_ac) -> None:
    guv = await servis_isi_ac(birim="GUVENLIK", durum="PLANLANDI", atananlar=[o.tek])
    hab = await servis_isi_ac(birim="HABERLESME", durum="PLANLANDI", atananlar=[o.tek2])
    await giris(client, "sef_a")
    assert _isler((await client.get(f"{TS}/benim-islerim")).json()) == []
    tumu = _isler((await client.get(f"{TS}/benim-islerim?gorunum=tumu")).json())
    assert guv.so_no in tumu and hab.so_no not in tumu


async def test_gruplar_yerel_gun_ve_siralama(client, db, o, servis_isi_ac) -> None:
    # 23:30 UTC = yerel ertesi gün 02:30
    gece = datetime(2026, 3, 10, 23, 30, tzinfo=UTC)
    client.clock.set(gece)
    dun = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    bugun_gec = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    bugun_erken = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    yarin = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    plansiz = await servis_isi_ac(durum="MUSTERI_TALEBI", atananlar=[o.tek])
    await _plan(db, dun, date(2026, 3, 10), saat=10)
    await _plan(db, bugun_gec, date(2026, 3, 11), saat=15)
    await _plan(db, bugun_erken, date(2026, 3, 11), saat=9)
    await _plan(db, yarin, date(2026, 3, 12), saat=9)
    await giris(client, "tek1")
    govde = (await client.get(f"{TS}/benim-islerim")).json()
    assert govde["bugun"] == "2026-03-11"
    assert _isler(govde, "GECIKEN") == [dun.so_no]
    assert _isler(govde, "BUGUN") == [bugun_erken.so_no, bugun_gec.so_no]
    assert _isler(govde, "YARIN") == [yarin.so_no]
    assert _isler(govde, "PLANSIZ") == [plansiz.so_no]


async def test_ayni_tesis_ayni_gun_tek_ziyaret_karti(
    client, db, o, lokasyon_ac, servis_isi_ac
) -> None:
    tesis = await lokasyon_ac()
    isler = []
    for _ in range(3):
        so = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek], lokasyon=tesis)
        await _plan(db, so, date(2026, 3, 10), saat=11)
        isler.append(so)
    await giris(client, "tek1")
    govde = (await client.get(f"{TS}/benim-islerim")).json()
    bugun = next(g for g in govde["gruplar"] if g["kod"] == "BUGUN")
    assert len(bugun["ziyaretler"]) == 1
    assert sorted(i["id"] for i in bugun["ziyaretler"][0]["isler"]) == sorted(s.id for s in isler)


async def test_plan_uyeligi_de_gorunur(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="PLANLANDI")
    await _plan(db, so, date(2026, 3, 10), uyeler=[o.tek])
    await giris(client, "tek1")
    assert so.so_no in _isler((await client.get(f"{TS}/benim-islerim")).json())


def _anahtarlar(nesne) -> set[str]:
    if isinstance(nesne, dict):
        return set(nesne) | {a for v in nesne.values() for a in _anahtarlar(v)}
    if isinstance(nesne, list):
        return {a for v in nesne for a in _anahtarlar(v)}
    return set()


async def test_kart_fiyatsiz_ve_kapsamli(client, db, o, lokasyon_ac, servis_isi_ac) -> None:
    tesis = await lokasyon_ac(line="Atatürk Cad. 1", district="Kadıköy", access_note="B kapısı")
    so = await servis_isi_ac(
        durum="SAHADA",
        atananlar=[o.tek],
        lokasyon=tesis,
        iletisim_ad="Saha Yetkilisi",
        iletisim_telefon="+905321112233",
    )
    baskasi = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek2])
    await giris(client, "tek1")
    r = await client.get(f"{TS}/benim-islerim/{so.id}")
    assert r.status_code == 200, r.text
    kart = r.json()
    yasak = {a for a in _anahtarlar(kart) if any(k in a for k in ("fiyat", "tutar", "maliyet"))}
    assert not yasak
    assert kart["ulasim_notu"] == "B kapısı" and "Kadıköy" in kart["adres"]
    assert kart["irtibat_telefon"] == "+905321112233"  # atanmış kişi görür
    assert "YOLA_CIKTIM" in kart["izinli_dugmeler"]
    assert (await client.get(f"{TS}/benim-islerim/{baskasi.id}")).status_code == 404


async def test_rbac_benim_islerim(client, o) -> None:
    await giris(client, "operasyon")  # servis.gor var, zaman.yaz yok
    assert (await client.get(f"{TS}/benim-islerim")).status_code == 403
    assert (await client.get(f"{TS}/zaman/bugunum")).status_code == 403
    await giris(client, "tek1")
    assert (await client.get(f"{TS}/benim-islerim")).status_code == 200


# --- Bugünüm (TS-078) --------------------------------------------------------------------------


async def test_bugunum_toplamlar_ve_eksik_listesi(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(180), SABAH - dk(120), kaynak="CANLI")
    await bolum_ac(db, so, o.tek, "MOLA", SABAH - dk(120), SABAH - dk(105), kaynak="CANLI")
    await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(105), SABAH - dk(75), kaynak="CANLI")
    # başka teknisyenin bölümü yanıtta görünmez
    await bolum_ac(db, so, o.tek2, "SAHA", SABAH - dk(60), SABAH - dk(30))

    tamamlanan = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek])
    uzaktan = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek])
    db.add(
        ServiceResult(
            service_order_id=uzaktan.id,
            sonuc="COZULDU",
            cozum_kanali="TELEFON",
            yapilan_islem="Telefonla",
        )
    )
    for is_ in (tamamlanan, uzaktan):
        db.add(
            ServiceOrderEvent(
                service_order_id=is_.id,
                olay_turu="DURUM",
                eski_durum="SAHADA",
                yeni_durum="TAMAMLANDI",
                ozet="Sahada → Tamamlandı",
                user_id=o.tek.id,
                olusma_zamani=SABAH - dk(20),
            )
        )
    await db.commit()

    await giris(client, "tek1")
    r = await client.get(f"{TS}/zaman/bugunum")
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["kisi_saat_dk"] == 90 and govde["mola_dk"] == 15
    assert {b["faaliyet"] for b in govde["bolumler"]} == {"SAHA", "MOLA"}
    assert len(govde["bolumler"]) == 3
    eksik = [i["so_no"] for i in govde["sure_eksik_isler"]]
    assert eksik == [tamamlanan.so_no]
    assert (await client.get(f"{TS}/zaman/bugunum?user_id={o.tek2.id}")).status_code == 422


async def test_bugunum_kayitsiz_gun_null(client, o) -> None:
    await giris(client, "tek1")
    govde = (await client.get(f"{TS}/zaman/bugunum")).json()
    assert govde["kisi_saat_dk"] is None and govde["mola_dk"] is None
    ileri = (SABAH + timedelta(days=2)).date().isoformat()
    assert (await client.get(f"{TS}/zaman/bugunum?gun={ileri}")).status_code == 400
