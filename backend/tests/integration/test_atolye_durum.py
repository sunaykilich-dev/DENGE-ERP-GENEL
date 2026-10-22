"""Atölye çekirdeği: kabul, ATOLYE makinesi, servis işi eşlemesi, iş kuralları.

Maddeler: TS-090/093/094/096/098.

Gerçek hikâye (E05 §1.1): eski sistemde atölye kaydı ile iş emri iki ayrı
durum, iki ayrı atama ve iki ayrı seri taşıyordu; iptal edilen atölye kaydının
iş emri açık kalıyordu. Burada her atölye geçişi servis işini AYNI
transaction'da yürütür ve genel servis uçları atölye işinde kilitlidir.
"""

import re

import pytest
from atolye_yardimci import (
    ATOLYE_NO_DESENI,
    ONEK,
    ariza_nedeni_id,
    atolye_olaylari,
    detay,
    duzelt,
    gec,
    kabul_et,
    kabul_govdesi,
    olay_say,
    sef,
    teshis_et,
    teslim_govdesi,
    teslime_hazirla,
)
from servis_yardimci import giris, musteri, teknisyen
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    Quote,
    ServiceEquipment,
    ServiceHold,
    ServiceOrder,
    ServiceOrderSerial,
    ServiceResult,
    ServiceTimeEntry,
    WorkshopRecord,
)
from app.services.teknik_servis import atolye

pytestmark = pytest.mark.integration


async def _kayit(db, so_id: int) -> WorkshopRecord:
    return await db.scalar(
        select(WorkshopRecord)
        .where(WorkshopRecord.service_order_id == so_id)
        .execution_options(populate_existing=True)
    )


async def _so(db, so_id: int) -> ServiceOrder:
    return await db.get(ServiceOrder, so_id, populate_existing=True)


async def test_kabul_is_ve_kayit_tek_islemde_durum_istemciden_alinmaz(
    client, db, birimli_kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    govde = kabul_govdesi(hesap.id, " 00ab12 ")
    govde.update(status="TESLIM_EDILDI", received_at="2020-01-01T00:00:00Z")
    r = await client.post(ONEK, json=govde)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "KABUL_EDILDI"
    assert re.match(ATOLYE_NO_DESENI, d["atolye_no"])
    kayit = await _kayit(db, d["so_id"])
    assert kayit.received_at == client.clock.now()
    so = await _so(db, d["so_id"])
    assert (so.tur, so.kategori, so.status, so.birim) == (
        "ATOLYE",
        "ATOLYE",
        "ATOLYEDE",
        "HABERLESME",
    )
    assert so.equipment_id == kayit.equipment_id
    ekipman = await db.get(ServiceEquipment, kayit.equipment_id)
    assert ekipman.serial_no == "00ab12"  # baştaki sıfır korunur
    seriler = (
        await db.scalars(
            select(ServiceOrderSerial.seri_no).where(ServiceOrderSerial.service_order_id == so.id)
        )
    ).all()
    assert seriler == ["00ab12"]
    assert len(await atolye_olaylari(db, so.id, "KABUL")) == 1
    assert len(d["aksesuarlar"]) == 2 and d["warranty_status"] == "BELIRSIZ"


async def test_makine_disi_gecis_409_izinli_liste_veri_degismez(
    client, db, birimli_kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    r = await gec(client, d["so_id"], "TESLIM_EDILDI", 409)
    assert "İzin verilenler" in r.json()["detail"]["mesaj"]
    assert set(r.json()["detail"]["izinli"]) == {"TESHISTE", "IPTAL"}
    kayit = await _kayit(db, d["so_id"])
    assert kayit.status == "KABUL_EDILDI" and kayit.delivered_at is None
    assert len(await atolye_olaylari(db, d["so_id"], "DURUM")) == 0


async def test_tam_akis_bekleme_senkronu_ve_teslim(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await gec(client, so_id, "TESHISTE")
    # Teşhis eksik → TESHISTE'den çıkış 400.
    await gec(client, so_id, "ONAY_BEKLIYOR", 400)
    await duzelt(client, so_id, fault_reason_id=await ariza_nedeni_id(db), is_repairable=True)
    await gec(client, so_id, "ONAY_BEKLIYOR")
    so = await _so(db, so_id)
    assert so.status == "BEKLEMEDE"
    bekleme = await db.scalar(
        select(ServiceHold).where(
            ServiceHold.service_order_id == so_id, ServiceHold.released_at.is_(None)
        )
    )
    assert bekleme.neden == "MUSTERI_ONAYI" and bekleme.onceki_durum == "ATOLYEDE"
    # Garanti belirsiz + onaysız → onarım 409.
    await gec(client, so_id, "ONARIMDA", 409)
    await duzelt(
        client,
        so_id,
        approval_decision="ONAYLANDI",
        approval_channel="TELEFON",
        approved_by_name="Ahmet Yılmaz",
    )
    client.clock.advance(minutes=30)
    await gec(client, so_id, "ONARIMDA")
    so = await _so(db, so_id)
    assert so.status == "ATOLYEDE"
    bekleme = await db.get(ServiceHold, bekleme.id, populate_existing=True)
    assert bekleme.released_at is not None and bekleme.sure_dk == 30
    await gec(client, so_id, "PARCA_BEKLIYOR")
    assert (await _so(db, so_id)).status == "BEKLEMEDE"
    await gec(client, so_id, "ONARIMDA")
    await duzelt(client, so_id, repair_category="PARCA_DEGISIMI")
    await gec(client, so_id, "TEST_KONTROL")
    await duzelt(client, so_id, test_result="GECTI")
    await gec(client, so_id, "TESLIME_HAZIR")
    kayit = await _kayit(db, so_id)
    tamamlanma = kayit.completed_at
    assert tamamlanma == client.clock.now()
    # Teslimde süre kaydı yoksa onay istenir (TS-076).
    dd = await detay(client, so_id)
    r = await gec(client, so_id, "TESLIM_EDILDI", 409, teslim=teslim_govdesi(dd))
    assert "Süre kaydı eksik" in r.json()["detail"]
    client.clock.advance(hours=1)
    r = await gec(client, so_id, "TESLIM_EDILDI", teslim=teslim_govdesi(dd), sure_eksik_onay=True)
    assert r.json()["uyarilar"] == []
    kayit = await _kayit(db, so_id)
    assert kayit.status == "TESLIM_EDILDI" and kayit.delivered_at == client.clock.now()
    assert kayit.completed_at == tamamlanma  # bir kez yazılır
    so = await _so(db, so_id)
    assert so.status == "TAMAMLANDI"
    sonuc = await db.scalar(
        select(ServiceResult).where(
            ServiceResult.service_order_id == so_id, ServiceResult.gecersiz_at.is_(None)
        )
    )
    assert (sonuc.sonuc, sonuc.cozum_kanali) == ("COZULDU", "ATOLYE")
    # Her geçerli geçiş 1 ATOLYE/DURUM olayı + 1 denetim satırı.
    durum_olaylari = await atolye_olaylari(db, so_id, "DURUM")
    assert len(durum_olaylari) == 8
    denetim = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity == "workshop_records", AuditLog.action == "atolye.durum.degistir")
    )
    assert denetim == 8
    # Onaylayan ve teslim alan adı olaya YAZILMAZ.
    for o in await atolye_olaylari(db, so_id):
        metin = (o.ozet + str(o.veri)).casefold()
        assert "ahmet" not in metin and "teslim alan kişi" not in metin
    # Teslimden sonra aksesuar değişikliği ve düzeltme 409.
    r = await client.put(
        f"{ONEK}/{so_id}/aksesuarlar", json={"version": kayit.version, "aksesuarlar": []}
    )
    assert r.status_code == 409
    await duzelt(client, so_id, 409, notes="geç not")
    # Şef kapatır (genel kapat ucu atölye işinde açık).
    r = await client.post(f"/api/teknik-servis/isler/{so_id}/kapat", json={})
    assert r.status_code == 200, r.text


async def test_onarilamaz_cihaz_yalniz_iade_ve_sonuc_cozulemedi(
    client, db, birimli_kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teshis_et(client, db, so_id, onarilabilir=False)
    await gec(client, so_id, "ONARIMDA", 409)
    await gec(client, so_id, "ONARILMADAN_IADE")
    dd = await detay(client, so_id)
    await gec(
        client, so_id, "KARGOYA_VERILDI", 400, teslim={"teslim_tipi": "KARGO", "kargo_firmasi": "X"}
    )
    await gec(
        client,
        so_id,
        "KARGOYA_VERILDI",
        teslim={"teslim_tipi": "KARGO", "kargo_firmasi": "Yurtiçi", "takip_no": "123"},
    )
    kayit = await _kayit(db, so_id)
    assert kayit.cargo_sent_at == client.clock.now()
    await gec(
        client,
        so_id,
        "TESLIM_EDILDI",
        teslim=teslim_govdesi(dd, teslim_tipi=None),
        sure_eksik_onay=True,
    )
    sonuc = await db.scalar(select(ServiceResult).where(ServiceResult.service_order_id == so_id))
    assert sonuc.sonuc == "COZULEMEDI"


async def test_kaldi_testinden_sonra_teslime_hazir_409(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teshis_et(client, db, so_id)
    await gec(client, so_id, "ONARIMDA")
    await duzelt(client, so_id, repair_category="LEHIM_KART_ONARIMI")
    await gec(client, so_id, "TEST_KONTROL")
    await duzelt(client, so_id, test_result="KALDI")
    r = await gec(client, so_id, "TESLIME_HAZIR", 409)
    assert "Geçti" in r.json()["detail"]
    assert (await _kayit(db, so_id)).status == "TEST_KONTROL"


async def test_bagli_teklif_kabul_onay_sayilir(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teshis_et(client, db, so_id, onay=False)
    await gec(client, so_id, "ONARIMDA", 409)
    db.add(
        Quote(
            quote_no="TKF2026-T1",
            customer_id=hesap.id,
            status="KABUL",
            birim="HABERLESME",
            service_order_id=so_id,
        )
    )
    await db.commit()
    await gec(client, so_id, "ONARIMDA")
    dd = await detay(client, so_id)
    assert dd["teklifler"][0]["status"] == "KABUL"
    assert "total" not in str(dd["teklifler"])


async def test_onay_gerekmez_gerekcesiz_400(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    await duzelt(client, d["so_id"], 400, approval_decision="ONAY_GEREKMEZ")
    await duzelt(
        client, d["so_id"], approval_decision="ONAY_GEREKMEZ", approval_note="Garanti kapsamı"
    )


async def test_iptal_servis_kapat_ve_gerekce_ister_servis_isi_iptal(
    client, db, birimli_kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    await birimli_kullanici_ac("atl_usta", "ATOLYE", ["HABERLESME"])
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teshis_et(client, db, so_id)
    await gec(client, so_id, "PARCA_BEKLIYOR")
    ozet = {k["kod"]: k["deger"] for k in (await client.get(f"{ONEK}/ozet")).json()}
    assert ozet["ACIK"] == 1
    await giris(client, "atl_usta")  # servis.kapat yok
    r = await gec(client, so_id, "IPTAL", 403, gerekce="Müşteri vazgeçti")
    assert "servis.kapat" in r.json()["detail"]
    await giris(client, "atl_sef")
    await gec(client, so_id, "IPTAL", 400)
    await gec(client, so_id, "IPTAL", gerekce="Müşteri vazgeçti")
    so = await _so(db, so_id)
    assert so.status == "IPTAL" and so.cancel_reason == "Müşteri vazgeçti"
    acik = await db.scalar(
        select(func.count())
        .select_from(ServiceHold)
        .where(ServiceHold.service_order_id == so_id, ServiceHold.released_at.is_(None))
    )
    assert acik == 0
    ozet = {k["kod"]: k["deger"] for k in (await client.get(f"{ONEK}/ozet")).json()}
    assert ozet["ACIK"] == 0
    olay = (await atolye_olaylari(db, so_id, "DURUM"))[-1]
    assert "Müşteri vazgeçti" in olay.ozet


async def test_geri_alma_gerekceli_servis_isini_etkilemez(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    await birimli_kullanici_ac("atl_usta2", "ATOLYE", ["HABERLESME"])
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teslime_hazirla(client, db, so_id)
    tamamlanma = (await _kayit(db, so_id)).completed_at
    durum_olay = await olay_say(db, so_id, "DURUM")
    await giris(client, "atl_usta2")
    await gec(client, so_id, "ONARIMDA", 403, gerekce="Ses sorunu sürüyor")
    await giris(client, "atl_sef")
    await gec(client, so_id, "ONARIMDA", 400)
    client.clock.advance(hours=1)
    await gec(client, so_id, "ONARIMDA", gerekce="Ses sorunu sürüyor")
    kayit = await _kayit(db, so_id)
    assert kayit.status == "ONARIMDA" and kayit.completed_at == tamamlanma
    assert kayit.test_result is None  # yeniden test şart
    assert (await _so(db, so_id)).status == "ATOLYEDE"
    assert await olay_say(db, so_id, "DURUM") == durum_olay  # servis işi değişmedi


async def test_genel_servis_uclari_atolye_isinde_kilitli(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    is_ucu = f"/api/teknik-servis/isler/{so_id}"
    r = await client.post(f"{is_ucu}/bekleme", json={"neden": "MALZEME"})
    assert r.status_code == 409 and "Atölye ekranından" in r.json()["detail"]
    r = await client.post(f"{is_ucu}/iptal", json={"gerekce": "Genel iptal"})
    assert r.status_code == 409
    r = await client.post(
        f"{is_ucu}/sonuc",
        json={
            "sonuc": "COZULDU",
            "cozum_kanali": "ATOLYE",
            "yapilan_islem": "x",
            "sure_eksik_onay": True,
        },
    )
    assert r.status_code == 409
    so = await _so(db, so_id)
    assert so.status == "ATOLYEDE"
    sonuc_sayisi = await db.scalar(
        select(func.count())
        .select_from(ServiceResult)
        .where(ServiceResult.service_order_id == so_id)
    )
    assert sonuc_sayisi == 0
    # Genel açılıştan ATOLYE işi açılamaz (yetim iş yok).
    r = await client.post(
        "/api/teknik-servis/isler",
        json={
            "birim": "HABERLESME",
            "tur": "ATOLYE",
            "konu": "Deneme",
            "customer_id": hesap.id,
            "seriler": ["X1"],
        },
    )
    assert r.status_code == 400
    yetim = await db.scalar(
        select(func.count())
        .select_from(ServiceOrder)
        .where(
            ServiceOrder.tur == "ATOLYE",
            ~ServiceOrder.id.in_(select(WorkshopRecord.service_order_id)),
        )
    )
    assert yetim == 0


async def test_kargo_teslim_aksesuar_kurallari(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teslime_hazirla(client, db, so_id)
    dd = await detay(client, so_id)
    await gec(
        client, so_id, "TESLIM_EDILDI", 400, teslim={"teslim_tipi": "ELDEN"}, sure_eksik_onay=True
    )
    # İşaretlenmemiş aksesuar 400.
    yarim = teslim_govdesi(dd)
    yarim["aksesuar_iade"] = yarim["aksesuar_iade"][:1]
    await gec(client, so_id, "TESLIM_EDILDI", 400, teslim=yarim, sure_eksik_onay=True)
    # Eksik aksesuar açıklamasız 400; açıklamalı 200 + uyarı.
    await gec(
        client,
        so_id,
        "TESLIM_EDILDI",
        400,
        teslim=teslim_govdesi(dd, eksik=True),
        sure_eksik_onay=True,
    )
    r = await gec(
        client,
        so_id,
        "TESLIM_EDILDI",
        teslim=teslim_govdesi(dd, eksik=True, aciklama="Batarya müşteride kaldı"),
        sure_eksik_onay=True,
    )
    assert r.json()["uyarilar"] and "Batarya" in r.json()["uyarilar"][0]
    iadeler = {a["kind"]: a["returned"] for a in r.json()["aksesuarlar"]}
    assert iadeler == {"BATARYA": False, "ANTEN": True}
    kayit = await _kayit(db, so_id)
    assert kayit.delivered_to_name == "Teslim Alan Kişi"


async def test_acik_sayacla_teslim_409(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    tek = await teknisyen(birimli_kullanici_ac, "atl_tek", ["HABERLESME"])
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    r = await client.post(
        f"{ONEK}/{so_id}/ata", json={"atamalar": [{"user_id": tek.id, "is_lead": True}]}
    )
    assert r.status_code == 200, r.text
    await teslime_hazirla(client, db, so_id)
    db.add(
        ServiceTimeEntry(
            service_order_id=so_id,
            user_id=tek.id,
            faaliyet="ATOLYE",
            started_at=client.clock.now(),
            kaynak="CANLI",
            girildi_at=client.clock.now(),
        )
    )
    await db.commit()
    dd = await detay(client, so_id)
    r = await gec(
        client, so_id, "TESLIM_EDILDI", 409, teslim=teslim_govdesi(dd), sure_eksik_onay=True
    )
    assert "Açık sayaç" in r.json()["detail"]
    kayit = await _kayit(db, so_id)
    assert kayit.status == "TESLIME_HAZIR" and kayit.delivered_to_name is None


async def test_iyimser_kilit_ve_sunucu_zamanlari(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    r = await client.patch(
        f"{ONEK}/{so_id}",
        json={"version": d["version"], "notes": "ilk", "received_at": "2020-01-01T00:00:00Z"},
    )
    assert r.status_code == 200
    r = await client.patch(f"{ONEK}/{so_id}", json={"version": d["version"], "notes": "ikinci"})
    assert r.status_code == 409 and "yenileyin" in r.json()["detail"]
    kayit = await _kayit(db, so_id)
    assert kayit.notes == "ilk" and kayit.received_at == client.clock.now()
    # Durum yarışı: ekranın gördüğü durum değişmişse 409.
    await gec(client, so_id, "TESHISTE", 409, beklenen_durum="TESHISTE")


async def test_ekipman_duzeltme_tek_kaynak(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id, "00A-12")
    so_id = d["so_id"]
    r = await client.put(f"{ONEK}/{so_id}/ekipman", json={"seri": "00A-123", "gerekce": "kısa"})
    assert r.status_code == 400
    r = await client.put(
        f"{ONEK}/{so_id}/ekipman", json={"seri": "00A-123", "gerekce": "Etiket yanlış okunmuş"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["ekipman"]["seri"] == "00A-123"
    seriler = (
        await db.scalars(
            select(ServiceOrderSerial.seri_no).where(
                ServiceOrderSerial.service_order_id == so_id, ServiceOrderSerial.is_active.is_(True)
            )
        )
    ).all()
    assert seriler == ["00A-123"]
    assert len(await atolye_olaylari(db, so_id, "DUZELTME")) == 1
    gecmis = (
        await client.get(f"{ONEK}/seri-gecmisi", params={"marka": "hytera", "seri": "00a-123"})
    ).json()
    assert [k["so_id"] for k in gecmis["kayitlar"]] == [so_id]


async def test_acik_kayit_engeli_ve_seri_normalizasyonu(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id, " ab12 ")
    r = await client.post(ONEK, json=kabul_govdesi(hesap.id, "AB12", ekipman={"marka": "HYTERA"}))
    assert r.status_code == 409
    assert d["atolye_no"] in r.json()["detail"]["mesaj"]
    # Baştaki sıfır farklı cihazdır.
    await kabul_et(client, hesap.id, "0AB12")
    # Farklı marka aynı seri farklı cihazdır.
    await kabul_et(client, hesap.id, "AB12", ekipman={"marka": "MOTOROLA"})
    sayi = await db.scalar(select(func.count()).select_from(WorkshopRecord))
    assert sayi == 3


async def test_coklu_aktif_eslesme_409_aday_listesi(
    client, db, birimli_kullanici_ac, ekipman_ac
) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    for _ in range(2):
        await ekipman_ac(
            birim="HABERLESME", musteri=hesap, tip="TELSIZ", seri="DUP-1", brand="HYTERA"
        )
    await giris(client, "atl_sef")
    r = await client.post(ONEK, json=kabul_govdesi(hesap.id, "DUP-1"))
    assert r.status_code == 409
    assert r.json()["detail"]["kod"] == "COKLU_EKIPMAN"
    assert len(r.json()["detail"]["adaylar"]) == 2
    secilen = r.json()["detail"]["adaylar"][1]["id"]
    r = await client.post(ONEK, json=kabul_govdesi(hesap.id, ekipman={"ekipman_id": secilen}))
    assert r.status_code == 201, r.text
    assert r.json()["ekipman"]["id"] == secilen


async def test_garanti_kabulde_dondurulur(client, db, birimli_kullanici_ac, ekipman_ac) -> None:
    from datetime import timedelta

    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    bugun = client.clock.now().date()
    ici = await ekipman_ac(
        birim="HABERLESME", musteri=hesap, tip="TELSIZ", seri="G-1", brand="HYTERA",
        warranty_end=bugun + timedelta(days=10),
    )  # fmt: skip
    disi = await ekipman_ac(
        birim="HABERLESME", musteri=hesap, tip="TELSIZ", seri="G-2", brand="HYTERA",
        warranty_end=bugun - timedelta(days=10),
    )  # fmt: skip
    await giris(client, "atl_sef")
    a = await kabul_et(client, hesap.id, ekipman={"ekipman_id": ici.id})
    b = await kabul_et(client, hesap.id, ekipman={"ekipman_id": disi.id})
    assert a["warranty_status"] == "GARANTI_ICI" and b["warranty_status"] == "GARANTI_DISI"
    # Bitiş < başlangıç ile yeni ekipman 400.
    r = await client.post(
        ONEK,
        json=kabul_govdesi(
            hesap.id, "G-3", ekipman={"warranty_start": "2026-05-01", "warranty_end": "2026-01-01"}
        ),
    )
    assert r.status_code == 400
    # Onarılarak teslim edilen cihaz pencere içinde dönerse ONARIM_GARANTISI.
    await teslime_hazirla(client, db, b["so_id"])
    dd = await detay(client, b["so_id"])
    await gec(client, b["so_id"], "TESLIM_EDILDI", teslim=teslim_govdesi(dd), sure_eksik_onay=True)
    client.clock.advance(days=20)
    await giris(client, "atl_sef")  # oturum 12 saatte düşer
    gecmis = (await client.get(f"{ONEK}/seri-gecmisi", params={"ekipman_id": disi.id})).json()
    assert gecmis["tekrar_gelis"] is True
    c = await kabul_et(client, hesap.id, ekipman={"ekipman_id": disi.id})
    assert c["warranty_status"] == "ONARIM_GARANTISI" and c["tekrar_gelis"] is True
    # Ekipmanın garanti tarihi sonradan düzeltilse de kayıttaki durum değişmez.
    disi.warranty_end = bugun + timedelta(days=400)
    await db.commit()
    assert (await detay(client, c["so_id"]))["warranty_status"] == "ONARIM_GARANTISI"


async def test_aksesuar_satirlari(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    r = await client.post(
        ONEK,
        json=kabul_govdesi(hesap.id, aksesuarlar=[{"kind": "DIGER", "qty": 1}]),
    )
    assert r.status_code == 400
    r = await client.post(
        ONEK, json=kabul_govdesi(hesap.id, aksesuarlar=[{"kind": "ANTEN", "qty": 0}])
    )
    assert r.status_code == 400
    d = await kabul_et(client, hesap.id)
    alti = [{"kind": k, "qty": 1} for k in ("BATARYA", "ANTEN", "KILIF", "KULAKLIK", "KABLO")]
    alti.append({"kind": "DIGER", "qty": 2, "description": "Yedek klips"})
    r = await client.put(
        f"{ONEK}/{d['so_id']}/aksesuarlar", json={"version": d["version"], "aksesuarlar": alti}
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["aksesuarlar"]) == 6
    assert len(await atolye_olaylari(db, d["so_id"], "AKSESUAR")) == 1


async def test_dis_servis_bilgisi_zorunlu(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    tedarikci = await musteri(db, "Üretici A.Ş.", is_tedarikci=True)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teshis_et(client, db, so_id)
    await gec(client, so_id, "DIS_SERVISTE", 400)
    await duzelt(
        client, so_id, 400, external_sent_at="2026-01-10", external_returned_at="2026-01-05"
    )
    await duzelt(client, so_id, external_vendor_id=tedarikci.id, external_sent_at="2026-01-10")
    await gec(client, so_id, "DIS_SERVISTE")
    bekleme = await db.scalar(
        select(ServiceHold).where(
            ServiceHold.service_order_id == so_id, ServiceHold.released_at.is_(None)
        )
    )
    assert bekleme.neden == "DIS_SERVIS"


async def test_toplu_kabul_hepsi_ya_da_hicbiri(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    ortak = {
        "customer_id": hesap.id,
        "service_type": "ARIZA_ONARIMI",
        "receive_type": "KARGO",
        "customer_complaint": "Toplu gelen arızalı telsizler",
    }
    cihazlar = [{"marka": "HYTERA", "seri": f"T-{i}"} for i in range(12)]
    r = await client.post(f"{ONEK}/toplu-kabul", json={**ortak, "cihazlar": cihazlar})
    assert r.status_code == 201, r.text
    grup = r.json()["kabul_grubu"]
    assert len(r.json()["kayitlar"]) == 12
    assert len({k["so_id"] for k in r.json()["kayitlar"]}) == 12
    assert {k["intake_group_no"] for k in r.json()["kayitlar"]} == {grup}
    liste = await client.get(ONEK, params={"kabul_grubu": grup})
    assert liste.headers["X-Toplam-Kayit"] == "12"
    # Gruptaki bir seri açık kayıtlıysa hiçbiri açılmaz.
    once = await db.scalar(select(func.count()).select_from(WorkshopRecord))
    r = await client.post(
        f"{ONEK}/toplu-kabul",
        json={
            **ortak,
            "cihazlar": [{"marka": "HYTERA", "seri": "YENI-1"}, {"marka": "HYTERA", "seri": "T-3"}],
        },
    )
    assert r.status_code == 409
    assert await db.scalar(select(func.count()).select_from(WorkshopRecord)) == once
    # Grup fişi bağlamı: tek fiş, N cihaz, tutar yok.
    kayitlar = (
        await db.scalars(select(WorkshopRecord).where(WorkshopRecord.intake_group_no == grup))
    ).all()
    baglam = atolye.grup_fisi_baglami([await atolye.belge_verisi(db, k) for k in kayitlar])
    assert len(baglam["kayitlar"]) == 12 and "tamir_bedeli" not in baglam


async def test_atama_ve_toplu_atama_e01_kaynagindan(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("atl_kabul", "ATOLYE", ["HABERLESME"])
    tek = await teknisyen(birimli_kullanici_ac, "atl_tek2", ["HABERLESME"])
    hesap = await musteri(db)
    await giris(client, "atl_kabul")
    a = await kabul_et(client, hesap.id, "AT-A")
    b = await kabul_et(client, hesap.id, "AT-B")
    r = await client.post(
        f"{ONEK}/toplu-ata",
        json={
            "so_idler": [a["so_id"], b["so_id"]],
            "atamalar": [{"user_id": tek.id, "is_lead": True}],
        },
    )
    assert r.status_code == 200, r.text
    liste = (await client.get(ONEK, params={"teknisyen_id": tek.id})).json()
    assert {s["so_id"] for s in liste} == {a["so_id"], b["so_id"]}
    assert liste[0]["sorumlu"]["id"] == tek.id
    # Teknisyen kendi kullanıcısıyla işi servis işleri listesinde görür.
    await giris(client, "atl_tek2")
    r = await client.get("/api/teknik-servis/isler")
    assert {s["id"] for s in r.json()} >= {a["so_id"], b["so_id"]}


async def test_teslim_kancasi_ayni_islemde_cagrilir(client, db, birimli_kullanici_ac) -> None:
    cagrilar: list[int] = []

    async def _kanca(db_, kayit, user, clock):
        cagrilar.append(kayit.id)

    atolye.teslim_kancasi_kaydet(_kanca)
    try:
        await sef(birimli_kullanici_ac)
        hesap = await musteri(db)
        await giris(client, "atl_sef")
        d = await kabul_et(client, hesap.id)
        await teslime_hazirla(client, db, d["so_id"])
        dd = await detay(client, d["so_id"])
        await gec(
            client, d["so_id"], "TESLIM_EDILDI", teslim=teslim_govdesi(dd), sure_eksik_onay=True
        )
        assert cagrilar == [d["kayit_id"]]
    finally:
        atolye.TESLIM_KANCALARI.remove(_kanca)


async def test_detay_parca_ve_sure_salt_okunur(client, db, birimli_kullanici_ac, urun_ac) -> None:
    from app.models import StockMovement, Warehouse

    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    assert d["sure"]["kisi_saat_dk"] is None  # kayıt yoksa 0 yazılmaz
    urun = await urun_ac("PARCA-1", "YOK", yedek_parca=True)
    depo = Warehouse(
        code="SRV-HAB", name="Haberleşme servis", servis_deposu=True, birim="HABERLESME"
    )
    db.add(depo)
    await db.flush()
    for _ in range(2):
        db.add(
            StockMovement(
                product_id=urun.id,
                warehouse_id=depo.id,
                qty=-1,
                reason="CIKIS",
                hareket_turu="CIKIS_SERVIS",
                service_order_id=d["so_id"],
                unit_cost=12.5,
            )
        )
    await db.commit()
    dd = await detay(client, d["so_id"])
    assert len(dd["parcalar"]) == 2
    assert "birim_maliyet" not in dd["parcalar"][0]
