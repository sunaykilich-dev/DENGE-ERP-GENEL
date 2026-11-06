"""Rol testi düzeltmeleri — tur 2 (KARARLAR 2026-11-04 §7).

Bulgu kaynakları `analiz/rol_testi/5_teknisyen_saha_atolye.md` (B…),
`6_satis_onay_finans_depo.md` (Y…/O…), `2_menu_link_yonetim.md` (B-08/B-12).
Şirket ayrımına bağlı testler `sirket_ayrimi` işaretlidir.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from bakim_yardimci import ONEK as BAKIM
from bakim_yardimci import ata as bakim_ata
from bakim_yardimci import hepsini_eslestir, ortam_kur, pb_isleri, sozlesme_ac, tum_uygun
from servis_yardimci import giris, tazele, teknisyen
from sqlalchemy import select

from app.models import (
    Account,
    KullaniciSirketi,
    MaintenanceContract,
    MaintenanceNonconformity,
    MaintenanceVisit,
    ServiceOrder,
    ServiceOrderSerial,
    ServiceResult,
    ServiceTimeEntry,
)
from app.models.servis_maliyet import ServiceOrderFinancial
from app.permissions import YALNIZ_OFIS_ROLLERI, permissions_of
from app.services.teknik_servis import bekletme

pytestmark = pytest.mark.integration
sirketli = pytest.mark.sirket_ayrimi

TS = "/api/teknik-servis"
IS = f"{TS}/isler"


async def _sonuc(db, so, sonuc: str = "COZULDU") -> None:
    db.add(
        ServiceResult(
            service_order_id=so.id, sonuc=sonuc, cozum_kanali="YERINDE", yapilan_islem="İşlem"
        )
    )
    await db.commit()


async def _kpi_idler(client, kpi: str) -> list[int]:
    r = await client.get(IS, params={"kpi": kpi})
    assert r.status_code == 200, r.text
    ids = [x["id"] for x in r.json()]
    assert int(r.headers["X-Toplam-Kayit"]) == len(ids)  # sayı = liste
    return ids


# --- 7.1 Teklif / parça dönüşü planlama kuyruğuna --------------------------------------


async def test_teklif_ve_parca_donusu_planlamaya_doner_ve_uyari(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "t2_tek")
    sef = await birimli_kullanici_ac("t2_sef", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac(durum="ISLEMDE", atananlar=[tek])
    parca = await servis_isi_ac(durum="SAHADA", atananlar=[tek])
    ekipten = await servis_isi_ac(durum="ISLEMDE", atananlar=[tek])
    for is_, neden in ((so, "TEKLIF"), (parca, "MALZEME"), (ekipten, "MALZEME")):
        await bekletme.beklet(db, is_, neden, user=sef, clock=client.clock, sistem=True)
    await db.commit()

    # Ekip dışı kişi (satış destek kararı / depo çıkışı yerine şef) bitirir → PLANLAMADA.
    for is_ in (so, parca):
        await bekletme.beklemeyi_bitir(db, is_, user=sef, clock=client.clock, not_="karar")
    # Ekipteki teknisyen (kendi araç deposundan parça) → önceki durum.
    await bekletme.beklemeyi_bitir(db, ekipten, user=tek, clock=client.clock)
    await db.commit()
    assert (await tazele(db, so)).status == "PLANLAMADA"
    assert (await tazele(db, parca)).status == "PLANLAMADA"
    assert (await tazele(db, ekipten)).status == "ISLEMDE"

    await giris(client, "t2_sef")
    assert sorted(await _kpi_idler(client, "planlamaya_donen")) == sorted([so.id, parca.id])
    # Zil: aynı KPI'nın sayısı (sorumlu teknisyen de kendi kapsamında görür).
    r = await client.get("/api/raporlar/uyarilar")
    assert r.status_code == 200, r.text
    zil = {u["kod"]: u["adet"] for u in r.json()["uyarilar"]}
    assert zil.get("servis.planlamaya_donen") == 2
    await giris(client, "t2_tek")
    assert sorted(await _kpi_idler(client, "planlamaya_donen")) == sorted([so.id, parca.id])


# --- 7.2 / 7.3 Kalite kapısı, reddi, toplu onay ------------------------------------------


async def test_fatura_devri_kalite_onayi_ister(
    client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await kullanici_ac("t2_fin", "FINANS_YONETICI")
    so = await servis_isi_ac(durum="TAMAMLANDI", completed_at=client.clock.now())
    db.add(
        ServiceOrderFinancial(
            service_order_id=so.id, gelir=Decimal("1000"), gelir_kaynagi="ELLE", gelir_notu="x"
        )
    )
    await db.commit()
    await giris(client, "t2_fin")
    r = await client.get(f"{TS}/maliyet/fatura-devri")
    assert r.status_code == 200, r.text
    assert so.id not in [x["so_id"] for x in r.json()]
    r = await client.post(f"{TS}/maliyet/fatura-devri/isaretle", json={"is_idler": [so.id]})
    assert r.status_code == 409
    so.kalite_onay_at = client.clock.now()
    await db.commit()
    r = await client.get(f"{TS}/maliyet/fatura-devri")
    assert so.id in [x["so_id"] for x in r.json()]


async def test_kalite_reddi_ise_geri_alir(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "t2_tek_k")
    await birimli_kullanici_ac("t2_yon_k", "SERVIS_YONETICI", ["GUVENLIK"])
    so = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[tek])
    await _sonuc(db, so)
    await giris(client, "t2_tek_k")
    r = await client.post(
        f"{IS}/{so.id}/kalite-reddi", json={"version": so.version, "gerekce": "x" * 12}
    )
    assert r.status_code == 403  # izin yok
    await giris(client, "t2_yon_k")
    r = await client.post(
        f"{IS}/{so.id}/kalite-reddi", json={"version": so.version, "gerekce": "kısa"}
    )
    assert r.status_code == 400
    r = await client.post(
        f"{IS}/{so.id}/kalite-reddi",
        json={"version": so.version - 1, "gerekce": "Etiket eksik kaldı"},
    )
    assert r.status_code == 409
    r = await client.post(
        f"{IS}/{so.id}/kalite-reddi",
        json={"version": so.version, "gerekce": "Etiket eksik kaldı", "hedef": "ISLEMDE"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ISLEMDE"
    so = await tazele(db, so)
    assert so.kalite_red_at is not None and so.kalite_red_gerekcesi == "Etiket eksik kaldı"
    gecerli = await db.scalar(
        select(ServiceResult.id).where(
            ServiceResult.service_order_id == so.id, ServiceResult.gecersiz_at.is_(None)
        )
    )
    assert gecerli is None  # sonuç geçersiz kılındı
    assert await _kpi_idler(client, "kalite_reddedilen") == [so.id]
    # Genel durum ucu tamamlanmış işi geri alamaz (yalnız kalite reddi).
    diger = await servis_isi_ac(durum="TAMAMLANDI")
    r = await client.post(f"{IS}/{diger.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code in (400, 409)
    assert (await tazele(db, diger)).status == "TAMAMLANDI"


async def test_toplu_kalite_onayi_kismi_sonuc(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "t2_tek_t")
    await birimli_kullanici_ac("t2_sef_t", "SERVIS_SEF", ["GUVENLIK"])
    a = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[tek])
    b = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[tek])
    acik = await servis_isi_ac(durum="ISLEMDE")
    yabanci = await servis_isi_ac(durum="TAMAMLANDI", birim="HABERLESME")
    await giris(client, "t2_sef_t")
    r = await client.post(
        f"{IS}/toplu-kalite-onayi",
        json={
            "isler": [
                {"id": a.id, "version": a.version},
                {"id": b.id, "version": b.version - 1},
                {"id": acik.id, "version": acik.version},
                {"id": yabanci.id, "version": yabanci.version},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()["onaylanan"]] == [a.id]
    atlanan = {x["id"]: x for x in r.json()["atlanan"]}
    assert set(atlanan) == {b.id, acik.id, yabanci.id}
    assert atlanan[yabanci.id]["so_no"] is None  # kapsam dışı iş no sızmaz
    assert (await tazele(db, a)).kalite_onay_at is not None
    assert (await tazele(db, b)).kalite_onay_at is None


# --- 7.4 Yola çıkışı geri alma ----------------------------------------------------------


async def test_yanlis_baslattim_ve_yonetici_geri_alma(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "t2_tek_y")
    await birimli_kullanici_ac("t2_yon_y", "SERVIS_YONETICI", ["GUVENLIK"])
    so = await servis_isi_ac(durum="PLANLANDI", atananlar=[tek])
    await giris(client, "t2_tek_y")
    r = await client.post(f"{TS}/zaman/baslat", json={"is_id": so.id, "eylem": "YOLA_CIKTIM"})
    assert r.status_code == 201, r.text
    bolum = r.json()["bolum"]
    r = await client.post(
        f"{IS}/{so.id}/zaman/bolumler/{bolum['id']}/geri-al", json={"version": bolum["version"]}
    )
    assert r.status_code == 200, r.text
    assert (await tazele(db, so)).status == "PLANLANDI"

    r = await client.post(f"{TS}/zaman/baslat", json={"is_id": so.id, "eylem": "YOLA_CIKTIM"})
    assert r.status_code == 201, r.text
    client.clock.advance(minutes=30)  # geri alma penceresi geçti
    so = await tazele(db, so)
    assert so.status == "YOLA_CIKILDI"
    await giris(client, "t2_yon_y")
    detay = (await client.get(f"{IS}/{so.id}")).json()
    gecis = next(g for g in detay["gecisler"] if g["hedef"] == "PLANLANDI")
    assert gecis["uc"] == "yola_cikis_geri_al" and gecis["yetkili"] is True
    r = await client.post(
        f"{IS}/{so.id}/yola-cikis-geri-al", json={"version": so.version, "gerekce": "kısa"}
    )
    assert r.status_code == 422
    r = await client.post(
        f"{IS}/{so.id}/yola-cikis-geri-al",
        json={"version": so.version, "gerekce": "Yanlış işe basıldı"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PLANLANDI"
    acik = await db.scalar(
        select(ServiceTimeEntry).where(
            ServiceTimeEntry.service_order_id == so.id, ServiceTimeEntry.is_deleted.is_(False)
        )
    )
    assert acik is None  # açık YOL sayacı iptal edildi (kişi-saate girmez)


# --- 7.5 Bakım formu: sözleşmesiz bakım, ölçüm, önem --------------------------------------


async def test_sozlesmesiz_bakimda_form_olcum_ve_kritik_bulgu(
    client, db, birimli_kullanici_ac, servis_isi_ac, ekipman_ac
) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "t2_tek_b")
    await birimli_kullanici_ac("t2_sef_b", "SERVIS_SEF", ["GUVENLIK"])
    ekipman = await ekipman_ac(tip="XRAY", seri="XR-T2-1")
    musteri = await db.get(Account, ekipman.account_id)
    so = await servis_isi_ac(
        tur="PLANSIZ_BAKIM",
        durum="ISLEMDE",
        atananlar=[tek],
        musteri=musteri,
        equipment_id=ekipman.id,
    )
    cihazsiz = await servis_isi_ac(tur="PLANSIZ_BAKIM", durum="ISLEMDE", atananlar=[tek])
    await giris(client, "t2_tek_b")
    assert (await client.get(f"{BAKIM}/formlar/{cihazsiz.id}")).status_code == 404
    r = await client.get(f"{BAKIM}/formlar/{so.id}")
    assert r.status_code == 200, r.text
    form = r.json()
    assert form["form"]["baslik"] == "DİJİTAL TEKNİK SERVİS / BAKIM FORMU"
    assert len(form["maddeler"]) == 11
    assert {t["alan"] for t in form["olcum_tanimlari"]} >= {"olcum_kv", "olcum_doz_usv"}
    kontroller = tum_uygun(form, XR_ESTOP=("UYGUNSUZ", "Acil stop butonu kırık"))
    for k in kontroller:
        if k["kod"] == "XR_ESTOP":
            k["onem"] = "KRITIK"
    govde = {
        "version": form["form"]["version"],
        "seri_no": "XR-T2-1",
        "zone": "Giriş",
        "performed_work": "Bakım",
        "technician_note": "Acil stop kırık",
        "bakim_sonucu": "UYGUNSUZLUK_VAR",
        "olcum_kv": "160.5",
        "olcum_doz_usv": "0.12",
        "kontroller": kontroller,
    }
    r = await client.put(f"{BAKIM}/formlar/{so.id}", json={**govde, "olcum_ma": "-1"})
    assert r.status_code == 422  # negatif ölçüm
    r = await client.put(f"{BAKIM}/formlar/{so.id}", json=govde)
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["form"]["olcum_kv"])) == Decimal("160.5")
    assert r.json()["form"]["olcum_ma"] is None  # ölçülmedi, 0 değil
    r = await client.post(
        f"{BAKIM}/formlar/{so.id}/onay", json={"tur": "ALINAMADI", "eksik_nedeni": "Yetkili yok"}
    )
    assert r.status_code == 201, r.text
    r = await client.post(f"{BAKIM}/formlar/{so.id}/tamamla", json={"sure_eksik_onay": True})
    assert r.status_code == 200, r.text
    assert r.json()["acilan_uygunsuzluk"] == 1
    ziyaret = await db.scalar(
        select(MaintenanceVisit).where(MaintenanceVisit.service_order_id == so.id)
    )
    assert ziyaret.olcumler["olcum_kv"].startswith("160.5")
    nc = await db.scalar(
        select(MaintenanceNonconformity).where(MaintenanceNonconformity.service_order_id == so.id)
    )
    assert nc.onem == "KRITIK"

    await giris(client, "t2_sef_b")
    r = await client.post(f"{BAKIM}/formlar/{so.id}/uygunsuzluklar/{nc.id}/ariza-isi")
    assert r.status_code == 200, r.text
    ariza = await db.get(ServiceOrder, r.json()["ariza_isi"]["id"])
    await db.refresh(ariza)
    assert ariza.oncelik == "KRITIK"
    assert ariza.konu == "Bakım bulgusu: Acil stop butonu kırık"
    assert ariza.iliski_turu == "BAKIM_BULGUSU"


# --- 7.6 Bakım ücreti ve PB geliri ----------------------------------------------------------


async def test_bakim_ucreti_finans_yoneticisi_ve_pb_geliri(
    client, db, kullanici_ac, birimli_kullanici_ac, lokasyon_ac, ekipman_ac
) -> None:
    await birimli_kullanici_ac("sef_f", "SERVIS_SEF", ["GUVENLIK"])
    tek = await birimli_kullanici_ac(
        "tek_f", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    await kullanici_ac("t2_fin_u", "FINANS_YONETICI")
    await kullanici_ac("t2_smd", "SATIS_MUDURU")
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0)
    await giris(client, "sef_f")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    assert (await client.post(f"{BAKIM}/uretim")).status_code == 200
    [pb] = await pb_isleri(db, s["id"])

    await giris(client, "t2_smd")  # maliyet.gor var, bakim.yaz/tahsilat.yaz yok
    r = await client.put(f"{BAKIM}/sozlesmeler/{s['id']}/ucret", json={"fee_per_visit": "1500.00"})
    assert r.status_code == 403
    await giris(client, "t2_fin_u")
    r = await client.put(f"{BAKIM}/sozlesmeler/{s['id']}/ucret", json={"fee_per_visit": "1500.00"})
    assert r.status_code == 200, r.text
    soz = await db.get(MaintenanceContract, s["id"])
    await db.refresh(soz)
    assert soz.fee_per_visit == Decimal("1500.00")

    await bakim_ata(db, pb, tek)
    await giris(client, "tek_f")
    form = (await client.get(f"{BAKIM}/formlar/{pb.id}")).json()
    r = await client.put(
        f"{BAKIM}/formlar/{pb.id}",
        json={
            "version": form["form"]["version"],
            "zone": "Giriş",
            "performed_work": "Bakım",
            "technician_note": "Sorun yok",
            "bakim_sonucu": "TAMAMLANDI",
            "kontroller": tum_uygun(form),
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{BAKIM}/formlar/{pb.id}/onay", json={"tur": "ALINAMADI", "eksik_nedeni": "Yetkili yok"}
    )
    assert r.status_code == 201, r.text
    r = await client.post(f"{BAKIM}/formlar/{pb.id}/tamamla", json={"sure_eksik_onay": True})
    assert r.status_code == 200, r.text
    fin = await db.scalar(
        select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == pb.id)
    )
    assert fin is not None and fin.gelir == Decimal("1500.00") and fin.gelir_kaynagi == "SOZLESME"


# --- 7.7 / 7.18 İzinler ---------------------------------------------------------------------


def test_maliyet_ve_ofis_izinleri() -> None:
    assert "maliyet.gor" in permissions_of("SERVIS_YONETICI")
    assert "maliyet.gor" not in permissions_of("MUHASEBE_DESTEK")
    assert "maliyet.gor" in permissions_of("FINANS_YONETICI")
    assert "servis.gor" in permissions_of("SATIS")
    assert "FINANS_YONETICI" in YALNIZ_OFIS_ROLLERI


async def test_finans_uzmani_maliyet_goremez(client, db, kullanici_ac, servis_isi_ac) -> None:
    await kullanici_ac("t2_muh", "MUHASEBE_DESTEK")
    so = await servis_isi_ac(durum="TAMAMLANDI")
    await giris(client, "t2_muh")
    assert (await client.get(f"{TS}/maliyet/isler/{so.id}")).status_code == 403


# --- 7.8 Satış: kendi müşterilerinin işleri ---------------------------------------------------


async def test_satis_kendi_musterisinin_islerini_gorur(
    client, db, kullanici_ac, servis_isi_ac
) -> None:
    satis = await kullanici_ac("t2_satis", "SATIS")
    benim = Account(title="Satışın Müşterisi", is_musteri=True, sales_rep_id=satis.id)
    diger = await kullanici_ac("t2_satis_d", "SATIS")
    baska = Account(title="Başka Müşteri", is_musteri=True, sales_rep_id=diger.id)
    db.add_all([benim, baska])
    await db.commit()
    is_benim = await servis_isi_ac(musteri=benim)
    is_baska = await servis_isi_ac(musteri=baska)
    await giris(client, "t2_satis")
    r = await client.get(IS)
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [is_benim.id]
    assert (await client.get(f"{IS}/{is_benim.id}")).status_code == 200
    assert (await client.get(f"{IS}/{is_baska.id}")).status_code == 404
    # Göremediği müşteriye teklif açamaz (yanıt "yok" ile aynı).
    r = await client.post("/api/teklifler", json={"customer_id": baska.id, "kalemler": []})
    assert r.status_code in (400, 404)
    assert "Müşteri bulunamadı" in r.text


@sirketli
async def test_satis_kapsami_sirket_ayrimi_ve_gorunur_birimler(
    client, db, kullanici_ac, servis_isi_ac
) -> None:
    satis = await kullanici_ac("t2_satis_s", "SATIS")
    db.add(KullaniciSirketi(user_id=satis.id, sirket_kod="ELEKTRONIK"))
    benim = Account(title="Satış Müşterisi 2", is_musteri=True, sales_rep_id=satis.id)
    db.add(benim)
    await db.commit()
    elk = await servis_isi_ac(musteri=benim, birim="GUVENLIK")
    tel = await servis_isi_ac(musteri=benim, birim="HABERLESME")
    await giris(client, "t2_satis_s")
    me = (await client.get("/api/auth/me")).json()
    assert me["aktif_sirket"] == "ELEKTRONIK"
    assert "POC" not in me["gorunur_birimler"]
    ids = [x["id"] for x in (await client.get(IS)).json()]
    assert elk.id in ids and tel.id not in ids
    assert (await client.get(f"{IS}/{tel.id}")).status_code == 404


# --- 7.9 / 7.10 Liste süzgeci ve süre eksik ---------------------------------------------------


async def test_sonuc_suzgeci_ve_kismi_sure_eksik(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    from zaman_ortam import bolum_ac

    t1 = await teknisyen(birimli_kullanici_ac, "t2_t1")
    t2 = await teknisyen(birimli_kullanici_ac, "t2_t2")
    await birimli_kullanici_ac("t2_sef_s", "SERVIS_SEF", ["GUVENLIK"])
    teklif = await servis_isi_ac(durum="BEKLEMEDE")
    await _sonuc(db, teklif, "TEKLIF_SUNULACAK")
    simdi = client.clock.now()
    kismi = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[t1, t2], completed_at=simdi)
    await bolum_ac(db, kismi, t1, "SAHA", simdi - timedelta(hours=2), simdi - timedelta(hours=1))
    await giris(client, "t2_sef_s")
    r = await client.get(IS, params={"sonuc": "TEKLIF_SUNULACAK"})
    assert [x["id"] for x in r.json()] == [teklif.id]
    assert (await client.get(IS, params={"sonuc": "UYDURMA"})).status_code == 400
    assert kismi.id in await _kpi_idler(client, "sure_eksik")
    # Zaman Takibi KPI listesi de aynı işi sayar.
    gun = simdi.date().isoformat()
    r = await client.get(f"{TS}/zaman/isler", params={"kpi": "sure_eksik", "bas": gun, "bit": gun})
    assert r.status_code == 200, r.text
    assert kismi.id in [x["id"] for x in r.json()]


# --- 7.11 / 7.12 / 7.13 Tayin ve bağlı iş -----------------------------------------------------


async def test_atolye_ustasi_kendine_tayin_ve_sure(
    client, db, birimli_kullanici_ac, kullanici_ac
) -> None:
    from atolye_yardimci import kabul_et

    await birimli_kullanici_ac("t2_usta", "ATOLYE", ["HABERLESME"])
    hesap = Account(title="Atölye Müşterisi", is_musteri=True)
    db.add(hesap)
    await db.commit()
    await giris(client, "t2_usta")
    kayit = await kabul_et(client, hesap.id)  # birim gönderilmedi → kullanıcının birimi
    so_id = kayit["service_order_id"] if "service_order_id" in kayit else kayit["so_id"]
    usta = await db.scalar(select(ServiceOrder.created_by).where(ServiceOrder.id == so_id))
    r = await client.post(
        f"{TS}/atolye/{so_id}/ata",
        json={"atamalar": [{"user_id": usta, "rol": "TEKNISYEN", "is_lead": True}]},
    )
    assert r.status_code == 200, r.text
    so = await db.get(ServiceOrder, so_id)
    assert so.birim == "HABERLESME"
    # Tamir bedeli izinsiz gönderilirse 403 (sessiz yok sayma değil).
    d = (await client.get(f"{TS}/atolye/{so_id}")).json()
    r = await client.patch(
        f"{TS}/atolye/{so_id}", json={"version": d["version"], "repair_amount": "1500"}
    )
    assert r.status_code == 403
    r = await client.get(f"{TS}/atolye/form-verileri", params={"birim": "GUVENLIK"})
    assert r.status_code == 200
    assert "XRAY" in r.json()["ekipman_tipleri"] and r.json()["markalar"][-1] == "DIGER"


async def test_ekipte_sonuc_girebilen_yoksa_uyari(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    from urllib.parse import unquote

    saha = await birimli_kullanici_ac(
        "t2_saha", "SAHA_SORUMLUSU", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    await birimli_kullanici_ac("t2_sef_u", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac(durum="PLANLAMADA")
    await giris(client, "t2_sef_u")
    r = await client.put(
        f"{IS}/{so.id}/atama",
        json={"atamalar": [{"user_id": saha.id, "rol": "TEKNISYEN", "is_lead": True}]},
    )
    assert r.status_code == 200, r.text
    assert "sonuç girebilecek" in unquote(r.headers.get("X-Atama-Uyarilari", ""))


async def test_teknisyen_actigi_bagli_isi_gorur(
    client, db, birimli_kullanici_ac, servis_isi_ac, lokasyon_ac
) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "t2_tek_bg")
    lok = await lokasyon_ac()
    hesap = await db.get(Account, lok.account_id)
    eski = await servis_isi_ac(
        musteri=hesap,
        lokasyon=lok,
        durum="TAMAMLANDI",
        atananlar=[tek],
        iletisim_ad="Saha Yetkilisi",
        iletisim_telefon="+905321112233",
        talep_kanali="TELEFON",
        seri=None,
    )
    db.add(ServiceOrderSerial(service_order_id=eski.id, seri_no="BG-1", seri_norm=""))
    await db.commit()
    await giris(client, "t2_tek_bg")
    r = await client.post(
        f"{IS}/{eski.id}/bagli-yeni-is",
        json={"konu": "Arıza tekrarladı", "iliski_turu": "TEKRAR_ARIZA"},
    )
    assert r.status_code == 201, r.text
    yeni = r.json()["id"]
    r = await client.get(f"{IS}/{yeni}")
    assert r.status_code == 200, r.text
    so = await db.get(ServiceOrder, yeni)
    assert so.iliski_turu == "TEKRAR_ARIZA" and so.iliskili_is_id == eski.id


# --- 7.16 / 7.17 Ana Panel: tek açık tanımı ve POC kartı -----------------------------------


async def test_ana_panel_tek_acik_tanimi(client, db, kullanici_ac, servis_isi_ac) -> None:
    await kullanici_ac("t2_yon_ap", "SERVIS_YONETICI")
    await servis_isi_ac(durum="ISLEMDE")
    await giris(client, "t2_yon_ap")
    r = await client.get(f"{TS}/ana-panel")
    assert r.status_code == 200, r.text
    veri = r.json()
    acik = next(k for k in veri["kpiler"] if k["kod"] == "acik_is")["deger"]
    assert veri["grafikler"]["acik_toplam"] == acik
    assert sum(b["deger"] for b in veri["grafikler"]["bolum_is_yuku"]) == acik


@sirketli
async def test_poc_karti_yalniz_telekomda(client, db, kullanici_ac) -> None:
    yon = await kullanici_ac("t2_yon_poc", "SERVIS_YONETICI")
    for kod in ("ELEKTRONIK", "TELEKOM"):
        db.add(KullaniciSirketi(user_id=yon.id, sirket_kod=kod))
    await db.commit()
    await giris(client, "t2_yon_poc")
    for kod, beklenen in (("ELEKTRONIK", False), ("TELEKOM", True)):
        r = await client.put("/api/oturum/aktif-sirket", json={"kod": kod})
        assert r.status_code == 200, r.text
        kartlar = [k["kod"] for k in (await client.get(f"{TS}/ana-panel")).json()["kpiler"]]
        assert ("poc_acik" in kartlar) is beklenen, kod
        assert ("POC" in (await client.get("/api/auth/me")).json()["gorunur_birimler"]) is beklenen


def test_bekleme_donus_kurali() -> None:
    """`_donus_durumu` saf kuralı."""
    assert bekletme._donus_durumu("ISLEMDE", "TEKLIF") == "PLANLAMADA"  # noqa: SLF001
    assert bekletme._donus_durumu("ISLEMDE", "MALZEME", ekip_ici=True) == "ISLEMDE"  # noqa: SLF001
    assert bekletme._donus_durumu("ATOLYEDE", "TEKLIF") == "ATOLYEDE"  # noqa: SLF001
    assert bekletme._donus_durumu("ISLEMDE", "MUSTERI_ONAYI") == "ISLEMDE"  # noqa: SLF001
