"""Zaman kaydı: manuel kayıt, yönetici düzeltmesi, iptal, kapsam, süre özeti (TS-070/072/075/076).

Kilitlenen riskler:
- Çakışma yazmadan ÖNCE okunur mesajla reddedilir ("… MOLA (SRV-…) ile
  çakışıyor"); EXCLUDE yalnız son savunma.
- Geriye >2 gün ve başkası adına kayıt yalnız `servis.planla`;
  `sistem.kullanici` tek başına hiçbir zaman ucunu açmaz.
- Kapsam dışı iş: 404 ve veri DEĞİŞMEZ (`db.refresh`).
- Kayıt yoksa süre EKSİK'tir, 0 değil; SQL (`sure_eksik_ifadesi`) ve Python
  (`sure_ozeti_toplu`) tanımı aynı işleri "eksik" sayar.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from zaman_ortam import SABAH, TS, bolum_ac, dk, giris, iso, ortam_kur

from app.models import (
    AuditLog,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServiceResult,
    ServiceTimeEntry,
)
from app.services.teknik_servis import zaman

pytestmark = pytest.mark.integration


@pytest.fixture
async def o(client, db, birimli_kullanici_ac):
    client.clock.set(SABAH)
    return await ortam_kur(db, birimli_kullanici_ac)


async def _manuel(client, so, **govde):
    return await client.post(f"{TS}/isler/{so.id}/zaman", json=govde)


# --- Manuel kayıt (TS-070) ---------------------------------------------------------


async def test_manuel_gerekce_esigi(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    eski = await _manuel(
        client,
        so,
        faaliyet="SAHA",
        started_at=iso(SABAH - dk(120)),
        ended_at=iso(SABAH - dk(40)),
    )
    assert eski.status_code == 400, eski.text
    assert "gerekçe" in eski.json()["detail"]
    yeni = await _manuel(
        client,
        so,
        faaliyet="SAHA",
        started_at=iso(SABAH - dk(30)),
        ended_at=iso(SABAH - dk(10)),
    )
    assert yeni.status_code == 201, yeni.text
    bolum = yeni.json()["bolum"]
    assert bolum["kaynak"] == "MANUEL" and bolum["sure_dk"] == 20
    assert yeni.json()["sunucu_zamani"]
    # denetim: manuel kayıt commit'ten önce yazıldı
    adet = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.entity == "service_time_entries")
    )
    assert adet == 1


async def test_geri_gun_siniri_ve_yonetici(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    uc_gun_once = SABAH - timedelta(days=3)
    await giris(client, "tek1")
    r = await _manuel(
        client,
        so,
        faaliyet="SAHA",
        started_at=iso(uc_gun_once),
        ended_at=iso(uc_gun_once + dk(60)),
        gerekce="Sayaç açılmadı",
    )
    assert r.status_code == 400, r.text
    await giris(client, "sef_a")
    r = await _manuel(
        client,
        so,
        faaliyet="SAHA",
        started_at=iso(uc_gun_once),
        ended_at=iso(uc_gun_once + dk(60)),
        gerekce="Teknisyenin telefonu yoktu",
        user_id=o.tek.id,
    )
    assert r.status_code == 201, r.text
    kayit = await db.get(ServiceTimeEntry, r.json()["bolum"]["id"])
    assert kayit.user_id == o.tek.id and kayit.created_by == o.sef.id


async def test_teknisyen_baskasi_adina_403(client, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek, o.tek2])
    await giris(client, "tek1")
    r = await _manuel(
        client,
        so,
        faaliyet="SAHA",
        started_at=iso(SABAH - dk(20)),
        ended_at=iso(SABAH - dk(10)),
        user_id=o.tek2.id,
    )
    assert r.status_code == 403, r.text


async def test_mola_ile_cakisan_manuel_409_okunur_mesaj(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    # 10:00-10:30 (yerel) MOLA
    await bolum_ac(db, so, o.tek, "MOLA", SABAH - dk(60), SABAH - dk(30), kaynak="CANLI")
    await giris(client, "tek1")
    r = await _manuel(
        client,
        so,
        faaliyet="SAHA",
        started_at=iso(SABAH - dk(45)),
        ended_at=iso(SABAH - dk(5)),
    )
    assert r.status_code == 409, r.text
    mesaj = r.json()["detail"]
    assert "09:00-09:30" in mesaj and "MOLA" in mesaj and so.so_no in mesaj
    assert "ile çakışıyor" in mesaj


async def test_iptal_isine_manuel_409(client, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="IPTAL", atananlar=[o.tek], cancel_reason="müşteri vazgeçti")
    await giris(client, "tek1")
    r = await _manuel(
        client,
        so,
        faaliyet="SAHA",
        started_at=iso(SABAH - dk(20)),
        ended_at=iso(SABAH - dk(10)),
    )
    assert r.status_code == 409


async def test_ileri_bitis_400(client, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    r = await _manuel(
        client, so, faaliyet="SAHA", started_at=iso(SABAH), ended_at=iso(SABAH + dk(60))
    )
    assert r.status_code == 400


async def test_bekleme_nedensiz_400_ve_katalog(client, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await giris(client, "tek1")
    govde = {"faaliyet": "BEKLEME", "started_at": iso(SABAH - dk(20)), "ended_at": iso(SABAH)}
    assert (await _manuel(client, so, **govde)).status_code == 400
    assert (await _manuel(client, so, **govde, bekleme_nedeni="YOK_BOYLE")).status_code == 400
    # sadece_sistem neden kullanıcıdan alınmaz
    r = await _manuel(client, so, **govde, bekleme_nedeni="BAKIM_UYGUNSUZLUK")
    assert r.status_code == 400
    assert (await _manuel(client, so, **govde, bekleme_nedeni="MALZEME")).status_code == 201


async def test_kaynaksiz_insert_db_hatasi(db, o, servis_isi_ac) -> None:
    """Server default YOK: her INSERT kaynağını açıkça yazar."""
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    db.add(
        ServiceTimeEntry(
            service_order_id=so.id,
            user_id=o.tek.id,
            faaliyet="SAHA",
            started_at=SABAH - dk(30),
            ended_at=SABAH,
            girildi_at=SABAH,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


# --- Kayıt iptali ve yönetici düzeltmesi (TS-070/072) ------------------------------------


async def test_kayit_iptali_gerekce_ve_iz(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    kayit = await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(90), SABAH - dk(30))
    await giris(client, "sef_a")
    yol = f"{TS}/isler/{so.id}/zaman/kayitlar/{kayit.id}/iptal"
    assert (await client.post(yol, json={"gerekce": ""})).status_code == 400
    r = await client.post(yol, json={"gerekce": "Yanlış işe girilmiş"})
    assert r.status_code == 200, r.text
    await db.refresh(kayit)
    assert kayit.is_deleted and kayit.iptal_turu == "KAYIT_IPTAL"
    assert kayit.iptal_gerekcesi == "Yanlış işe girilmiş" and kayit.deleted_by == o.sef.id
    liste = (await client.get(f"{TS}/isler/{so.id}/zaman")).json()
    assert liste["bolumler"][0]["iptal"] is True  # satır silinmedi, görünür
    assert liste["sure_ozeti"]["kisi_saat_dk"] is None
    olay = await db.scalar(
        select(ServiceOrderEvent).where(
            ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "DUZELTME"
        )
    )
    assert olay is not None and olay.veri["bolum_id"] == kayit.id
    # teknisyen iptal edemez
    await giris(client, "tek1")
    assert (await client.post(yol, json={"gerekce": "x"})).status_code == 403


async def test_yonetici_kapat_duzeltme_ve_iptal(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - timedelta(hours=12))
    await giris(client, "sef_a")
    yol = f"{TS}/isler/{so.id}/zaman/bolumler/{acik.id}/yonetici-kapat"
    # bitiş başlangıçtan önce / ileri → 400
    r = await client.post(
        yol,
        json={"version": acik.version, "gercek_bitis": iso(SABAH + dk(5)), "gerekce": "x"},
    )
    assert r.status_code == 400
    r = await client.post(
        yol,
        json={
            "version": acik.version,
            "gercek_bitis": iso(SABAH - timedelta(hours=4)),
            "gerekce": "Akşam 18:00'de bitmiş",
        },
    )
    assert r.status_code == 200, r.text
    await db.refresh(acik)
    assert acik.kaynak == "YONETICI_DUZELTMESI" and acik.kapanis_turu == "YONETICI"
    assert acik.updated_by == o.sef.id
    ozet = await zaman.sure_ozeti(db, so.id)
    assert ozet.kisi_saat_dk == 8 * 60

    ikinci = await bolum_ac(db, so, o.tek, "MOLA", SABAH - dk(30))
    r = await client.post(
        f"{TS}/isler/{so.id}/zaman/bolumler/{ikinci.id}/yonetici-kapat",
        json={"version": ikinci.version, "gerekce": "Yanlış sayaç"},
    )
    assert r.status_code == 200, r.text
    await db.refresh(ikinci)
    assert ikinci.is_deleted and ikinci.iptal_turu == "YONETICI_IPTAL"


async def test_yalniz_sistem_kullanici_403(client, db, o, rol_ac, kullanici_ac, servis_isi_ac):
    await rol_ac("T_SISTEM", ["sistem.kullanici"])
    await kullanici_ac("sistemci", "T_SISTEM")
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(30))
    await giris(client, "sistemci")
    r = await client.post(
        f"{TS}/isler/{so.id}/zaman/bolumler/{acik.id}/yonetici-kapat",
        json={"version": acik.version, "gerekce": "x"},
    )
    assert r.status_code == 403
    r = await _manuel(
        client, so, faaliyet="SAHA", started_at=iso(SABAH - dk(20)), ended_at=iso(SABAH)
    )
    assert r.status_code == 403
    assert (await client.get(f"{TS}/zaman/benim")).status_code == 403


async def test_zaman_yaz_olmayan_403(client, o, servis_isi_ac) -> None:
    """SERVIS_OPERASYON `servis.yaz` taşır ama sahaya çıkmaz: sayacı yok (K20)."""
    so = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    await giris(client, "operasyon")
    assert (await client.get(f"{TS}/zaman/benim")).status_code == 403
    r = await client.post(f"{TS}/zaman/baslat", json={"is_id": so.id, "eylem": "YOLA_CIKTIM"})
    assert r.status_code == 403
    assert (await client.get(f"{TS}/isler/{so.id}/zaman")).status_code == 200


# --- Kapsam: 404 ve veri değişmez ----------------------------------------------------------


async def test_kapsam_disi_is_404_veri_degismez(client, db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(birim="GUVENLIK", durum="SAHADA", atananlar=[o.tek])
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - timedelta(hours=11))
    kapali = await bolum_ac(db, so, o.tek2, "SAHA", SABAH - dk(90), SABAH - dk(60))
    await giris(client, "sef_b")  # HABERLESME şefi
    istekler = [
        ("GET", f"{TS}/isler/{so.id}/zaman", None),
        (
            "POST",
            f"{TS}/isler/{so.id}/zaman",
            {
                "faaliyet": "SAHA",
                "started_at": iso(SABAH - dk(20)),
                "ended_at": iso(SABAH),
                "user_id": o.tek.id,
            },
        ),
        (
            "POST",
            f"{TS}/isler/{so.id}/zaman/bolumler/{acik.id}/yonetici-kapat",
            {"version": acik.version, "gerekce": "x"},
        ),
        (
            "POST",
            f"{TS}/isler/{so.id}/zaman/bolumler/{acik.id}/bitir",
            {"version": acik.version},
        ),
        (
            "POST",
            f"{TS}/isler/{so.id}/zaman/kayitlar/{kapali.id}/iptal",
            {"gerekce": "x"},
        ),
        ("POST", f"{TS}/zaman/baslat", {"is_id": so.id, "eylem": "SAHAYA_VARDIM"}),
        ("GET", f"{TS}/benim-islerim/{so.id}", None),
    ]
    for yontem, yol, govde in istekler:
        r = await client.request(yontem, yol, json=govde)
        assert r.status_code == 404, (yol, r.status_code, r.text)
    await db.refresh(acik)
    await db.refresh(kapali)
    await db.refresh(so)
    assert acik.ended_at is None and not acik.is_deleted and acik.version == 1
    assert not kapali.is_deleted and so.status == "SAHADA"
    adet = await db.scalar(
        select(func.count())
        .select_from(ServiceTimeEntry)
        .where(ServiceTimeEntry.service_order_id == so.id)
    )
    assert adet == 2


async def test_yabanci_bolum_kimligi_404(client, db, o, servis_isi_ac) -> None:
    """Bölüm başka işe aitse (`is_id` uyuşmuyor) 404 — iş üzerinden bölüm taranamaz."""
    a = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    b = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek2])
    yabanci = await bolum_ac(db, b, o.tek2, "SAHA", SABAH - dk(30))
    await giris(client, "sef_a")
    r = await client.post(
        f"{TS}/isler/{a.id}/zaman/bolumler/{yabanci.id}/yonetici-kapat",
        json={"version": 1, "gerekce": "x"},
    )
    assert r.status_code == 404


# --- Süre özeti: null anlamı ve SQL = Python (TS-075) ----------------------------------------


async def test_kayit_yoksa_eksik_sifir_degil(db, o, servis_isi_ac) -> None:
    calisilmis = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek])
    planli = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    ozet = await zaman.sure_ozeti_toplu(db, [calisilmis.id, planli.id])
    assert ozet[calisilmis.id].kisi_saat_dk is None
    assert ozet[calisilmis.id].sure_durumu == "EKSIK"
    assert ozet[calisilmis.id].eksik_kisiler == ("Ali Veli",)
    assert ozet[planli.id].sure_durumu == "BEKLENMIYOR"
    assert ozet[planli.id].sapma_dk is None


async def test_kismi_mola_haric_ilk_varis(db, o, servis_isi_ac) -> None:
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek, o.tek2])
    await bolum_ac(db, so, o.tek, "YOL", SABAH - dk(120), SABAH - dk(90), kaynak="CANLI")
    await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(90), SABAH - dk(30), kaynak="CANLI")
    await bolum_ac(db, so, o.tek, "MOLA", SABAH - dk(30), SABAH - dk(15), kaynak="CANLI")
    ozet = await zaman.sure_ozeti(db, so.id)
    assert ozet.sure_durumu == "KISMI" and ozet.eksik_kisiler == ("Ayşe Kaya",)
    assert ozet.kisi_saat_dk == 90 and ozet.mola_dk == 15
    assert ozet.faaliyet_kirilimi == {"YOL": 30, "SAHA": 60}
    assert ozet.ilk_varis_at == SABAH - dk(90) and ozet.ilk_yol_at == SABAH - dk(120)


async def test_sql_ve_python_eksik_tanimi_esit(db, o, servis_isi_ac) -> None:
    """Parametrik eşitlik: her senaryo için `sure_eksik_ifadesi()` ile
    `sure_ozeti_toplu(...).sure_eksik` aynı işleri seçer (E09-D02)."""
    senaryolar = {}
    senaryolar["tamam_kayitsiz"] = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek])
    senaryolar["planli_kayitsiz"] = await servis_isi_ac(durum="PLANLANDI", atananlar=[o.tek])
    senaryolar["iptal"] = await servis_isi_ac(
        durum="IPTAL", atananlar=[o.tek], cancel_reason="vazgeçildi"
    )
    tam = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await bolum_ac(db, tam, o.tek, "SAHA", SABAH - dk(60), SABAH - dk(30))
    senaryolar["tam"] = tam
    kismi = await servis_isi_ac(durum="KAPATILDI", atananlar=[o.tek, o.tek2])
    await bolum_ac(db, kismi, o.tek, "SAHA", SABAH - dk(200), SABAH - dk(150))
    senaryolar["kismi"] = kismi
    yalniz_mola = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek2])
    await bolum_ac(db, yalniz_mola, o.tek2, "MOLA", SABAH - dk(20), SABAH - dk(10))
    senaryolar["yalniz_mola"] = yalniz_mola
    iptal_kayit = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek2])
    await bolum_ac(
        db,
        iptal_kayit,
        o.tek2,
        "SAHA",
        SABAH - dk(300),
        SABAH - dk(280),
        is_deleted=True,
        iptal_turu="GERI_ALINDI",
    )
    senaryolar["iptal_edilmis_kayit"] = iptal_kayit
    uzaktan = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek])
    db.add(
        ServiceResult(
            service_order_id=uzaktan.id,
            sonuc="COZULDU",
            cozum_kanali="TELEFON",
            yapilan_islem="Telefonla çözüldü",
        )
    )
    await db.commit()
    senaryolar["uzaktan"] = uzaktan
    sef_atamali = await servis_isi_ac(durum="SAHADA")
    db.add(
        ServiceOrderAssignment(
            service_order_id=sef_atamali.id, user_id=o.sef.id, rol="SEF", assigned_at=SABAH
        )
    )
    await db.commit()
    await bolum_ac(db, sef_atamali, o.sef, "SAHA", SABAH - dk(400), SABAH - dk(380))
    senaryolar["yalniz_sef"] = sef_atamali

    idler = [s.id for s in senaryolar.values()]
    python = {i for i, oz in (await zaman.sure_ozeti_toplu(db, idler)).items() if oz.sure_eksik}
    from app.models import ServiceOrder

    sql = set(
        (
            await db.scalars(
                select(ServiceOrder.id).where(
                    ServiceOrder.id.in_(idler), zaman.sure_eksik_ifadesi()
                )
            )
        ).all()
    )
    assert sql == python
    beklenen = {
        senaryolar[k].id for k in ("tamam_kayitsiz", "kismi", "yalniz_mola", "iptal_edilmis_kayit")
    }
    assert python == beklenen


# --- Kapanışta süre eksik onayı (TS-076) ------------------------------------------------------


async def test_kapanis_sure_eksik_onayi(db, o, servis_isi_ac) -> None:
    from app.clock import FakeClock

    saat = FakeClock(SABAH)
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek, o.tek2])
    await bolum_ac(db, so, o.tek, "SAHA", SABAH - dk(60), SABAH - dk(30))
    with pytest.raises(zaman.ZamanHatasi) as hata:
        await zaman.sure_eksik_kapanis_dogrula(db, so, onay=False, user=o.tek, clock=saat)
    assert str(hata.value) == "Süre kaydı eksik: Ayşe Kaya. Onaylayarak kapatın."
    await zaman.sure_eksik_kapanis_dogrula(db, so, onay=True, user=o.tek, clock=saat)
    await db.commit()
    notlar = (
        await db.scalars(
            select(ServiceOrderEvent.ozet).where(
                ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "NOT"
            )
        )
    ).all()
    assert notlar == ["Süre kaydı eksik olarak kapatıldı: Ayşe Kaya"]
    # tam işte sorulmaz
    tam = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await bolum_ac(db, tam, o.tek, "SAHA", SABAH - dk(200), SABAH - dk(150))
    ozet = await zaman.sure_eksik_kapanis_dogrula(db, tam, onay=False, user=o.tek, clock=saat)
    assert ozet.sure_durumu == "TAM"


# --- Uzun sayaç uyarısı (TS-072) ----------------------------------------------------------


async def test_uzun_sayac_uyarisi_birim_kapsamli(db, o, servis_isi_ac) -> None:
    from app.clock import FakeClock
    from app.services.teknik_servis import uyarilar as ts_uyarilar

    saat = FakeClock(SABAH)
    so = await servis_isi_ac(birim="GUVENLIK", durum="SAHADA", atananlar=[o.tek])
    acik = await bolum_ac(db, so, o.tek, "SAHA", SABAH - timedelta(hours=11))

    def _adet(uyarilar, kod):
        return sum(u.adet for u in uyarilar if u.kod == kod)

    assert _adet(await ts_uyarilar.topla(db, o.sef, saat), "zaman.uzun_sayac") == 1
    assert _adet(await ts_uyarilar.topla(db, o.sef_b, saat), "zaman.uzun_sayac") == 0
    assert _adet(await ts_uyarilar.topla(db, o.tek, saat), "zaman.kendi_uzun_sayac") == 1
    assert _adet(await ts_uyarilar.topla(db, o.tek2, saat), "zaman.kendi_uzun_sayac") == 0
    # sayaç kapanınca uyarı kaybolur (ack yok, K7); worker kapatmaz
    acik.ended_at = SABAH - timedelta(hours=3)
    acik.kapanis_turu = "BITIR"
    await db.commit()
    assert _adet(await ts_uyarilar.topla(db, o.sef, saat), "zaman.uzun_sayac") == 0


async def test_dunden_kalan_kisa_sayac_da_uyarir(db, o, servis_isi_ac) -> None:
    """Gün değişmiş sayaç: 2 saatlik ama dünden (yerel) kalmış."""
    from app.clock import FakeClock

    gece = datetime(2026, 3, 10, 22, 30, tzinfo=UTC)  # yerel 11.03 01:30
    saat = FakeClock(gece)
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    await bolum_ac(db, so, o.tek, "SAHA", gece - timedelta(hours=2))  # yerel 10.03 23:30
    uyarilar = await zaman.zaman_uyarilari(db, o.sef, saat)
    assert uyarilar[0].adet == 1
