"""Dijital bakım formu, PB koruması, kapsam dışı, uygunsuzluk, yeniden açma
ve dönem kapanışı (TS-064…068).

Korunan kurallar: BEKLIYOR madde ile tamamlama 409; UYGUNSUZ/KONTROL
EDİLEMEDİ madde notu zorunlu (400); her başarılı tamamlamada değişmez ziyaret
satırı (taslak kaydı ziyaret yazmaz); PB genel uçtan TAMAMLANDI/IPTAL olamaz
(409, Kapsam Dışı yolu); açık uygunsuzluk varken PB TAMAMLANDI olamaz; kişi
kendi kapsam dışı talebini onaylayamaz; iptal PB aynı cihaz–dönem için
yeniden üretilmez; yeniden açma formu TASLAK'a ve dönemi açığa döndürür.
"""

import pytest
from bakim_yardimci import (
    ONEK,
    ata,
    giris,
    hepsini_eslestir,
    ortam_kur,
    pb_isleri,
    sozlesme_ac,
    tum_uygun,
)
from sqlalchemy import func, select

from app.models import (
    MaintenanceForm,
    MaintenanceNonconformity,
    MaintenancePeriod,
    MaintenanceVisit,
    ServiceHold,
    ServiceOrder,
)

pytestmark = pytest.mark.integration

# Faz A (M1.10/M9.4): süre kaydı olmayan PB kapanışı uyarı ister; bu testler
# formu konu alır, süre uyarısı `test_servis_faz_a` ve bütünleştirme testinde.
SURE_ONAY = {"sure_eksik_onay": True}

IS = "/api/teknik-servis/isler"


@pytest.fixture
async def kisiler(birimli_kullanici_ac):
    return {
        "sef": await birimli_kullanici_ac("sef_f", "SERVIS_SEF", ["GUVENLIK"]),
        "sef2": await birimli_kullanici_ac("sef2_f", "SERVIS_SEF", ["GUVENLIK"]),
        "tek": await birimli_kullanici_ac(
            "tek_f", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "tek2": await birimli_kullanici_ac(
            "tek2_f", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
    }


async def _pb_kur(client, db, lokasyon_ac, ekipman_ac, *, xray=1, kapi=0):
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=xray, kapi=kapi)
    await giris(client, "sef_f")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    r = await client.post(f"{ONEK}/uretim")
    assert r.status_code == 200, r.text
    return s, await pb_isleri(db, s["id"])


async def _alinamadi_onayi(client, so_id: int) -> None:
    r = await client.post(
        f"{ONEK}/formlar/{so_id}/onay", json={"tur": "ALINAMADI", "eksik_nedeni": "Yetkili yok"}
    )
    assert r.status_code == 201, r.text


async def _doldur(client, so_id: int, **ozel) -> dict:
    form = (await client.get(f"{ONEK}/formlar/{so_id}")).json()
    r = await client.put(
        f"{ONEK}/formlar/{so_id}",
        json={
            "version": form["form"]["version"],
            "zone": "Giriş Kapısı",
            "performed_work": "Periyodik bakım yapıldı",
            "technician_note": "Sorun yok",
            "bakim_sonucu": "UYGUNSUZLUK_VAR" if ozel else "TAMAMLANDI",
            "kontroller": tum_uygun(form, **ozel),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_atanmamis_teknisyen_404_ve_veri_degismez(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await ata(db, so, kisiler["tek"])
    await giris(client, "tek2_f")
    assert (await client.get(f"{ONEK}/formlar/{so.id}")).status_code == 404
    r = await client.put(f"{ONEK}/formlar/{so.id}", json={"version": 1, "zone": "X"})
    assert r.status_code == 404
    assert (await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)).status_code == 404
    form = await db.scalar(select(MaintenanceForm).where(MaintenanceForm.service_order_id == so.id))
    await db.refresh(form)
    assert form.zone != "X" and form.version == 1

    await giris(client, "tek_f")
    r = await client.get(f"{ONEK}/formlar/{so.id}")
    assert r.status_code == 200
    veri = r.json()
    assert veri["form"]["baslik"] == "DİJİTAL TEKNİK SERVİS / PLANLI BAKIM FORMU"
    assert len(veri["maddeler"]) == 11
    assert "fee_per_visit" not in str(veri)  # formda maliyet alanı yok


async def test_not_zorunlu_400_bekleyen_madde_409_taslak_ziyaret_yazmaz(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await ata(db, so, kisiler["tek"])
    await giris(client, "tek_f")
    form = (await client.get(f"{ONEK}/formlar/{so.id}")).json()
    r = await client.put(
        f"{ONEK}/formlar/{so.id}",
        json={
            "version": form["form"]["version"],
            "kontroller": [{"kod": "XR_EXT", "sonuc": "UYGUNSUZ", "not": " "}],
        },
    )
    assert r.status_code == 400  # not zorunlu
    r = await client.put(
        f"{ONEK}/formlar/{so.id}",
        json={
            "version": form["form"]["version"],
            "zone": "Giriş",
            "kontroller": [{"kod": "XR_EXT", "sonuc": "UYGUN"}],
        },
    )
    assert r.status_code == 200
    assert await db.scalar(select(func.count(MaintenanceVisit.id))) == 0  # taslak ziyaret değil
    r = await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)
    assert r.status_code == 409
    assert r.json()["detail"]["kod"] == "BEKLEYEN_MADDE"


async def test_tamamlama_onay_ister_ziyaret_yazar_donemi_kapatir(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await ata(db, so, kisiler["tek"])
    await giris(client, "tek_f")
    await _doldur(client, so.id)
    r = await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)
    assert r.status_code == 409  # servis_onay_zorunlu_turler = ["PB"]
    assert "onay" in r.text
    await _alinamadi_onayi(client, so.id)
    r = await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)
    assert r.status_code == 200, r.text
    assert r.json()["so"]["status"] == "TAMAMLANDI"
    assert r.json()["form"]["status"] == "TAMAMLANDI"
    await db.refresh(so)
    assert so.status == "TAMAMLANDI"
    ziyaret = await db.scalar(
        select(MaintenanceVisit).where(MaintenanceVisit.service_order_id == so.id)
    )
    assert ziyaret.tur == "TAMAMLAMA" and ziyaret.technician_user_id == kisiler["tek"].id
    assert len(ziyaret.checks) == 11
    donem = await db.get(MaintenancePeriod, so.maintenance_period_id)
    await db.refresh(donem)
    assert donem.closing_kind == "TAMAMLANDI" and donem.closed_at is not None
    # Tamamlanmış form tekrar tamamlanamaz.
    assert (await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)).status_code == 409


async def test_pb_genel_uctan_tamamlanamaz_ve_iptal_edilemez(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await giris(client, "sef_f")
    r = await client.post(
        f"{IS}/{so.id}/sonuc",
        json={"sonuc": "COZULDU", "cozum_kanali": "YERINDE", "yapilan_islem": "x"},
    )
    assert r.status_code == 409, r.text
    r = await client.post(f"{IS}/{so.id}/iptal", json={"gerekce": "Gerek kalmadı"})
    assert r.status_code == 409
    assert "Kapsam Dışı" in r.text
    await db.refresh(so)
    assert so.status == "PLANLAMADA"


async def test_uygunsuzluk_beklemeye_alir_kapaninca_tamamlar(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await ata(db, so, kisiler["tek"])
    await giris(client, "tek_f")
    await _doldur(client, so.id, XR_BELT=("UYGUNSUZ", "Bant yırtık"))
    await _alinamadi_onayi(client, so.id)
    r = await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)
    assert r.status_code == 200, r.text
    assert r.json()["acilan_uygunsuzluk"] == 1
    await db.refresh(so)
    assert so.status == "BEKLEMEDE"
    bekleme = await db.scalar(
        select(ServiceHold).where(
            ServiceHold.service_order_id == so.id, ServiceHold.released_at.is_(None)
        )
    )
    assert bekleme.neden == "BAKIM_UYGUNSUZLUK"
    nc = await db.scalar(
        select(MaintenanceNonconformity).where(MaintenanceNonconformity.service_order_id == so.id)
    )
    assert nc.description == "Bant yırtık" and nc.status == "ACIK"
    donem = await db.get(MaintenancePeriod, so.maintenance_period_id)
    await db.refresh(donem)
    assert donem.closed_at is None  # açık aksiyon dönemi açık tutar

    # Teknisyen aksiyonu kapatamaz; şef kapatır → PB TAMAMLANDI.
    yol = f"{ONEK}/formlar/{so.id}/uygunsuzluklar/{nc.id}"
    assert (await client.post(f"{yol}/kapat", json={"not": "Değişti"})).status_code == 403
    await giris(client, "sef_f")
    r = await client.patch(yol, json={"version": nc.version, "action_type": "TEKLIF"})
    assert r.status_code == 409  # teklif aksiyonu Dalga 2'de
    r = await client.patch(yol, json={"version": nc.version, "action_type": "YERINDE_GIDERILDI"})
    assert r.status_code == 200, r.text
    r = await client.post(f"{yol}/kapat", json={"not": "Bant değiştirildi"})
    assert r.status_code == 200, r.text
    await db.refresh(so)
    assert so.status == "TAMAMLANDI"
    await db.refresh(donem)
    assert donem.closing_kind == "TAMAMLANDI"


async def test_uygunsuzluktan_bagli_ariza_isi(client, db, kisiler, lokasyon_ac, ekipman_ac):
    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await ata(db, so, kisiler["tek"])
    await giris(client, "tek_f")
    await _doldur(client, so.id, XR_IMG=("UYGUNSUZ", "Görüntü bozuk"))
    await _alinamadi_onayi(client, so.id)
    await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)
    nc = await db.scalar(
        select(MaintenanceNonconformity).where(MaintenanceNonconformity.service_order_id == so.id)
    )
    await giris(client, "sef_f")
    r = await client.post(f"{ONEK}/formlar/{so.id}/uygunsuzluklar/{nc.id}/ariza-isi")
    assert r.status_code == 200, r.text
    ariza = await db.get(ServiceOrder, r.json()["ariza_isi"]["id"])
    assert ariza.tur == "ARIZA" and ariza.iliski_turu == "BAKIM_BULGUSU"
    assert ariza.iliskili_is_id == so.id
    r = await client.post(f"{ONEK}/formlar/{so.id}/uygunsuzluklar/{nc.id}/ariza-isi")
    assert r.status_code == 409  # tek bağ


async def test_kapsam_disi_kendi_onayi_409_kismi_donem_ve_yeniden_uretilmez(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    s, isler = await _pb_kur(client, db, lokasyon_ac, ekipman_ac, xray=2)
    birinci, ikinci = isler
    await giris(client, "sef_f")
    r = await client.post(
        f"{ONEK}/formlar/{ikinci.id}/kapsam-disi",
        json={"neden": "SOKULMUS", "aciklama": "Cihaz sökülmüş"},
    )
    assert r.status_code == 201, r.text
    talep = r.json()["kapsam_disi"][0]
    yol = f"{ONEK}/formlar/{ikinci.id}/kapsam-disi/{talep['id']}/karar"
    r = await client.post(yol, json={"onay": True})
    assert r.status_code == 409  # kendi talebi
    await giris(client, "sef2_f")
    r = await client.post(yol, json={"onay": True, "not": "Uygun"})
    assert r.status_code == 200, r.text
    await db.refresh(ikinci)
    assert ikinci.status == "IPTAL" and ikinci.cancel_reason.startswith("Kapsam dışı")
    donem = await db.get(MaintenancePeriod, birinci.maintenance_period_id)
    await db.refresh(donem)
    assert donem.closed_at is None  # biri hâlâ açık: onaylı talep dönemi kapatmaz tek başına

    # Diğer cihaz tamamlanınca dönem KISMI kapanır.
    await giris(client, "sef_f")
    await _doldur(client, birinci.id)
    await _alinamadi_onayi(client, birinci.id)
    assert (
        await client.post(f"{ONEK}/formlar/{birinci.id}/tamamla", json=SURE_ONAY)
    ).status_code == 200
    await db.refresh(donem)
    assert donem.closing_kind == "KISMI"
    # İptal edilen cihaz-dönem yeniden üretilmez.
    r = await client.post(f"{ONEK}/sozlesmeler/{s['id']}/donemler/{donem.id}/eksik-pb")
    assert r.json()["generated"] == 0


async def test_tamamlanan_pb_yeniden_acilmaz_bagli_ariza_isi_acilir(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    """M1.7 (Faz A): tamamlanan PB yeniden açılmaz (409; form ve dönem
    değişmez); devamı PB'ye bağlı ARIZA işi olarak açılır (1 cihaz = 1 PB korunur)."""
    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await giris(client, "sef_f")
    await _doldur(client, so.id)
    await _alinamadi_onayi(client, so.id)
    assert (await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)).status_code == 200
    donem = await db.get(MaintenancePeriod, so.maintenance_period_id)
    await db.refresh(donem)
    kapanis = donem.closed_at
    assert kapanis is not None

    r = await client.post(f"{IS}/{so.id}/yeniden-ac", json={"gerekce": "Bölge yanlış yazılmış"})
    assert r.status_code == 409, r.text
    form = await db.scalar(select(MaintenanceForm).where(MaintenanceForm.service_order_id == so.id))
    await db.refresh(form)
    assert form.status != "TASLAK" and form.completed_at is not None
    await db.refresh(donem)
    assert donem.closed_at == kapanis
    assert await db.scalar(select(func.count(MaintenanceVisit.id))) == 1

    r = await client.post(
        f"{IS}/{so.id}/bagli-yeni-is",
        json={
            "konu": "Bölge yanlış yazılmış, tekrar bakılacak",
            "talep_kanali": "TELEFON",
            "iletisim_ad": "Tesis Sorumlusu",
            "iletisim_telefon": "+905321112233",
        },
    )
    assert r.status_code == 201, r.text
    yeni = r.json()
    assert yeni["tur"] == "ARIZA" and yeni["onceki_is_id"] == so.id
    assert len(yeni["seriler"]) == 1
    await db.refresh(donem)
    assert donem.closed_at == kapanis  # yeni iş dönemi açmaz


async def test_donem_uzlastirmasi_idempotent(client, db, kisiler, lokasyon_ac, ekipman_ac):
    from app.clock import FakeClock
    from app.services.teknik_servis import bakim_formu

    _, [so] = await _pb_kur(client, db, lokasyon_ac, ekipman_ac)
    await giris(client, "sef_f")
    await _doldur(client, so.id)
    await _alinamadi_onayi(client, so.id)
    await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)
    # Kancayı atlayan bir yol dönemi bozmuş olsun: gece uzlaştırması düzeltir.
    donem = await db.get(MaintenancePeriod, so.maintenance_period_id)
    donem.closed_at = None
    donem.closing_kind = None
    await db.commit()
    ozet = await bakim_formu.donem_uzlastirma_gorevi(db, FakeClock())
    await db.commit()
    assert "1 kapanış düzeltildi" in ozet
    ozet = await bakim_formu.donem_uzlastirma_gorevi(db, FakeClock())
    assert "0 kapanış düzeltildi" in ozet


async def test_sahada_farkli_seri_kutuk_farki_exclude_tamamlamayi_bloke_etmez(
    client, db, kisiler, lokasyon_ac, ekipman_ac
):
    """E04-17: sahadaki seri başka sözleşmede kapsamdaki ekipmanınsa bağ
    kurulamaz (EXCLUDE) ama tamamlama BLOKE OLMAZ; uyarı döner, kütük farkı açılır."""
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=2, kapi=0)
    birinci, ikinci = o.ekipmanlar["XRAY"]
    await giris(client, "sef_f")
    s1 = await sozlesme_ac(client, o, kapsam={"XRAY": 1})
    s2 = await sozlesme_ac(client, o, aktif=False, kapsam={"XRAY": 1})
    for s, e in ((s1, birinci), (s2, ikinci)):
        kalem = (await client.get(f"{ONEK}/sozlesmeler/{s['id']}/eslestirme")).json()["kalemler"][0]
        r = await client.put(
            f"{ONEK}/sozlesmeler/{s['id']}/eslestirme",
            json={"eslesmeler": [{"kalem_id": kalem["kalem_id"], "equipment_id": e.id}]},
        )
        assert r.status_code == 200, r.text
    await client.post(f"{ONEK}/uretim")
    [so] = await pb_isleri(db, s1["id"])
    form = (await client.get(f"{ONEK}/formlar/{so.id}")).json()
    r = await client.put(
        f"{ONEK}/formlar/{so.id}",
        json={
            "version": form["form"]["version"],
            "seri_no": ikinci.serial_no,
            "zone": "Giriş",
            "technician_note": "Etiket farklı",
            "bakim_sonucu": "TAMAMLANDI",
            "kontroller": tum_uygun(form),
        },
    )
    assert r.status_code == 200, r.text
    await _alinamadi_onayi(client, so.id)
    r = await client.post(f"{ONEK}/formlar/{so.id}/tamamla", json=SURE_ONAY)
    assert r.status_code == 200, r.text
    assert any("başka bir sözleşmenin kapsamında" in u for u in r.json()["uyarilar"])
    assert r.json()["form"]["kutuk_fark_durumu"] == "ACIK"
    await db.refresh(so)
    assert so.status == "TAMAMLANDI" and so.equipment_id == birinci.id
