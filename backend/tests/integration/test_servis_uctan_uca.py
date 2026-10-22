"""Dalga 1 geçidi: uçtan uca senaryolar (plan §3, Dalga 1 çıkış koşulu).

(a) Arıza işi: aç → planla (ekip) → Yola Çıktım → Sahaya Vardım → sayaç
    bitir → (onay zorunlu) sonuç 409 → müşteri onayı → sonuç/TAMAMLANDI →
    kapat. Paketler arası kancalar gerçekten bağlı mı: planlama ekibi
    `atama.ata` ile yazar, sayaç durumu tek kapıdan ilerletir, açık sayaç
    tamamlamayı keser (D1-G kancası), onay zorunluluğu (D1-C kancası) sonuç
    ucunda çalışır, süre özeti tam çıkar.
(b) Planlı bakım: sözleşme → ekipman eşleştirme → otomatik üretim kapısı →
    worker iki kez (idempotent: yine aynı PB sayısı) → toplu plan → saha
    sayacı → form + onay → tamamla → dönem kapanışı.

Her iki senaryo da mobilite tablolarına, panosuna ve uyarılarına dokunmaz
(TS-028 aynı ölçümle).
"""

from __future__ import annotations

import re

import pytest
from bakim_yardimci import ONEK as BAKIM
from bakim_yardimci import hepsini_eslestir, ortam_kur, pb_isleri, sozlesme_ac, tum_uygun
from servis_yardimci import SRV_DESENI, giris
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import (
    Device,
    MaintenancePeriod,
    MaintenanceVisit,
    PartnerSettlement,
    Payment,
    ServiceOrder,
    ServiceOrderEvent,
    ServicePlan,
    SettlementLine,
    User,
    Vehicle,
    WorkOrder,
    WorkOrderItem,
)
from app.services import reports, uyarilar
from app.services import settings as ayar_svc
from app.services.teknik_servis import uyarilar as ts_uyarilar

pytestmark = pytest.mark.integration

TS = "/api/teknik-servis"
IS = f"{TS}/isler"
PLAN = f"{TS}/planlama"

_MOBILITE = (WorkOrder, WorkOrderItem, PartnerSettlement, SettlementLine, Payment, Device, Vehicle)


async def _mobilite_ozeti(db, admin: User) -> dict:
    clock = FakeClock()
    ts_kodlari = {u.kod for u in await ts_uyarilar.topla(db, admin, clock)}
    return {
        "sayilar": {
            m.__tablename__: await db.scalar(select(func.count()).select_from(m)) for m in _MOBILITE
        },
        "pano": await reports.dashboard(db, clock),
        "uyarilar": sorted(
            (u.kod, u.adet)
            for u in (await uyarilar.topla(db, clock, admin)).uyarilar
            if u.kod not in ts_kodlari
        ),
    }


@pytest.fixture
async def kisiler(kullanici_ac, birimli_kullanici_ac, db):
    admin = await kullanici_ac("admin_uu", "ADMIN")
    yonetici = await kullanici_ac("mudur_uu", "SERVIS_YONETICI")
    sef = await birimli_kullanici_ac("sef_uu", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    tek = await birimli_kullanici_ac(
        "tek_uu", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    tek.full_name = "Ali Veli"
    await db.commit()
    return {"admin": admin, "yonetici": yonetici, "sef": sef, "tek": tek}


async def _durum(db, so_id: int) -> str:
    so = await db.get(ServiceOrder, so_id)
    await db.refresh(so)
    return so.status


async def _sayac_akisi(client, so_id: int, *, yol: bool = True) -> dict:
    """Teknisyenin tek dokunuş akışı: (Yola Çıktım → 30 dk →) Sahaya Vardım →
    45 dk → Bitir. Kapanmamış sayaç döndürmez."""
    eylem = "YOLA_CIKTIM" if yol else "SAHAYA_VARDIM"
    r = await client.post(f"{TS}/zaman/baslat", json={"is_id": so_id, "eylem": eylem})
    assert r.status_code == 201, r.text
    bolum = r.json()["bolum"]
    if yol:
        assert r.json()["is_durumu"] == "YOLA_CIKILDI"
        client.clock.advance(minutes=30)
        r = await client.post(
            f"{IS}/{so_id}/zaman/bolumler/{bolum['id']}/gecis",
            json={"version": bolum["version"], "faaliyet": "SAHA"},
        )
        assert r.status_code == 200, r.text
        bolum = r.json()["yeni_bolum"]
    assert r.json()["is_durumu"] == "SAHADA"
    client.clock.advance(minutes=45)
    return bolum


async def _bitir(client, so_id: int, bolum: dict) -> None:
    r = await client.post(
        f"{IS}/{so_id}/zaman/bolumler/{bolum['id']}/bitir", json={"version": bolum["version"]}
    )
    assert r.status_code == 200, r.text


# --- (a) Arıza işi ---------------------------------------------------------------------


async def test_ariza_isi_acilistan_kapanisa(client, db, kisiler, lokasyon_ac) -> None:
    from app.models import Account

    hesap = Account(title="Uçtan Uca Müşteri A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    tesis = await lokasyon_ac(hesap, ad="Merkez Tesis")
    once = await _mobilite_ozeti(db, kisiler["admin"])
    # Arıza işinde de müşteri onayı zorunlu olsun: D1-C kancası sonuçta çalışmalı.
    await ayar_svc.set_many(db, {"servis_onay_zorunlu_turler": ["PB", "ARIZA"]}, None)
    await db.commit()

    # 1) Şef işi açar.
    await giris(client, "sef_uu")
    r = await client.post(
        IS,
        json={
            "birim": "GUVENLIK",
            "tur": "ARIZA",
            "konu": "Kamera görüntü vermiyor",
            "customer_id": hesap.id,
            "address_id": tesis.id,
            "talep_kanali": "TELEFON",
            "iletisim_ad": "Saha Yetkilisi",
            "iletisim_telefon": "+905321112233",
            "seriler": ["CAM-UU-1"],
        },
    )
    assert r.status_code == 201, r.text
    so = r.json()
    assert re.match(SRV_DESENI, so["so_no"]) and so["status"] == "MUSTERI_TALEBI"
    so_id = so["id"]

    # Teknisyen atanmadan önce işi görmez (KENDI_ISLERI → 404).
    await giris(client, "tek_uu")
    assert (await client.get(f"{IS}/{so_id}")).status_code == 404

    # 2) Şef planlar; ekip planlama ucundan `atama.ata` ile yazılır.
    await giris(client, "sef_uu")
    r = await client.put(
        f"{PLAN}/isler/{so_id}/plan",
        json={
            "plan_tarihi": "2026-01-01",
            "baslangic_saati": "10:00",
            "sure_dk": 90,
            "ekip": {"teknisyen_idler": [kisiler["tek"].id], "sorumlu_id": kisiler["tek"].id},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "PLANLANDI"
    ekip = (await client.get(f"{IS}/{so_id}/ekip")).json()
    assert [(e["user_id"], e["is_lead"]) for e in ekip] == [(kisiler["tek"].id, True)]

    # 3) Teknisyen: Yola Çıktım → Sahaya Vardım (durum sayaçla ilerler).
    await giris(client, "tek_uu")
    detay = (await client.get(f"{IS}/{so_id}")).json()
    assert detay["status"] == "PLANLANDI"
    benim = (await client.get(f"{TS}/benim-islerim")).json()
    assert so_id in {k["id"] for k in _kartlar(benim)}
    bolum = await _sayac_akisi(client, so_id)
    assert await _durum(db, so_id) == "SAHADA"

    # 4) Açık sayaç varken tamamlama 409 (D1-G kancası) ve iş değişmez.
    sonuc = {"sonuc": "COZULDU", "cozum_kanali": "YERINDE", "yapilan_islem": "Kablo yenilendi"}
    r = await client.post(f"{IS}/{so_id}/sonuc", json=sonuc)
    assert r.status_code == 409, r.text
    assert await _durum(db, so_id) == "SAHADA"
    await _bitir(client, so_id, bolum)

    # 5) Onay zorunlu → onaysız sonuç 409; onaydan sonra TAMAMLANDI.
    r = await client.post(f"{IS}/{so_id}/sonuc", json=sonuc)
    assert r.status_code == 409 and "onay" in r.text.lower(), r.text
    assert await _durum(db, so_id) == "SAHADA"
    r = await client.post(
        f"{IS}/{so_id}/onay", json={"tur": "SOZLU", "imzalayan_ad": "Ayşe Yetkili"}
    )
    assert r.status_code == 201, r.text
    zaman = (await client.get(f"{IS}/{so_id}/zaman")).json()["sure_ozeti"]
    assert zaman["sure_durumu"] == "TAM" and zaman["kisi_saat_dk"] == 75
    r = await client.post(f"{IS}/{so_id}/sonuc", json=sonuc)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TAMAMLANDI" and r.json()["first_completed_at"]

    # Teknisyen kapatamaz (servis.kapat yok).
    assert (await client.post(f"{IS}/{so_id}/kapat", json={})).status_code == 403

    # 6) Şef kapatır.
    await giris(client, "sef_uu")
    r = await client.post(f"{IS}/{so_id}/kapat", json={"beklenen_durum": "TAMAMLANDI"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "KAPATILDI"
    gecmis = (await client.get(f"{IS}/{so_id}/gecmis")).json()
    turler = {o["olay_turu"] for o in gecmis}
    assert {"DURUM", "PLAN", "ATAMA"} <= turler
    durumlar = [o["yeni_durum"] for o in gecmis if o["olay_turu"] == "DURUM"]
    for beklenen in ("PLANLANDI", "YOLA_CIKILDI", "SAHADA", "TAMAMLANDI", "KAPATILDI"):
        assert beklenen in durumlar, (beklenen, durumlar)
    # Olay geçmişinde irtibat/imzalayan adı yok (kişisel veri olay_yaz'da reddedilir).
    olay_metni = " ".join(
        (o or "") for o in (await db.scalars(select(ServiceOrderEvent.ozet))).all()
    )
    assert "Ayşe Yetkili" not in olay_metni

    assert await _mobilite_ozeti(db, kisiler["admin"]) == once


def _kartlar(benim: dict) -> list[dict]:
    """`/benim-islerim` gruplarındaki kartlar (ziyaret kartının işleri dahil)."""
    kartlar: list[dict] = []
    for grup in benim["gruplar"]:
        for ziyaret in grup["ziyaretler"]:
            kartlar.extend(ziyaret["isler"])
    return kartlar


# --- (b) Planlı bakım ---------------------------------------------------------------------


async def test_planli_bakim_sozlesmeden_donem_kapanisina(
    client, db, kisiler, lokasyon_ac, ekipman_ac
) -> None:
    from app import worker

    once = await _mobilite_ozeti(db, kisiler["admin"])
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=1, ad="Bakım Uçtan Uca")

    # 1) Sözleşme (şef) — aktif.
    await giris(client, "sef_uu")
    s = await sozlesme_ac(client, o)
    assert s["status"] == "AKTIF"

    # 2) Otomatik üretim eşleştirme %100 olmadan açılamaz (yönetici; genel ayar ucu da kapalı).
    await giris(client, "mudur_uu")
    r = await client.put(f"{BAKIM}/otomatik-uretim", json={"acik": True})
    assert r.status_code == 409, r.text
    await giris(client, "admin_uu")
    r = await client.patch("/api/ayarlar", json={"values": {"bakim_otomatik_uretim": True}})
    assert r.status_code == 409, r.text  # genel ayar ucu kapıyı delmez
    assert await ayar_svc.get(db, "bakim_otomatik_uretim") is False

    # 3) Şef eşleştirir; yönetici otomatik üretimi açar.
    await giris(client, "sef_uu")
    await hepsini_eslestir(client, s["id"], o)
    await giris(client, "mudur_uu")
    r = await client.put(f"{BAKIM}/otomatik-uretim", json={"acik": True})
    assert r.status_code == 200, r.text

    # 4) Worker iki kez: ikinci tur 0 yeni PB (idempotent).
    ozet = await worker.pb_uretimi(db, FakeClock())
    await db.commit()
    assert ozet.startswith("2 PB"), ozet
    await worker.pb_uretimi(db, FakeClock())
    await db.commit()
    isler = await pb_isleri(db, s["id"])
    assert len(isler) == 2
    assert all(so.status == "PLANLAMADA" and so.created_by is None for so in isler)
    donem_id = isler[0].maintenance_period_id
    assert {so.maintenance_period_id for so in isler} == {donem_id}

    # 5) Şef iki PB'yi tek ziyarette planlar + teknisyeni atar.
    await giris(client, "sef_uu")
    r = await client.post(
        f"{PLAN}/toplu-plan",
        json={
            "is_idler": [so.id for so in isler],
            "plan_tarihi": "2026-01-01",
            "baslangic_saati": "10:00",
            "sure_dk": 120,
            "ekip": {"teknisyen_idler": [kisiler["tek"].id]},
        },
    )
    assert r.status_code == 201, r.text
    plan_ziyaretleri = set(
        await db.scalars(
            select(ServicePlan.visit_id).where(
                ServicePlan.service_order_id.in_([so.id for so in isler]),
                ServicePlan.is_active.is_(True),
            )
        )
    )
    assert plan_ziyaretleri == {r.json()["ziyaret_id"]}

    # 6) Teknisyen her PB'de: sayaç → form → onay → tamamla.
    await giris(client, "tek_uu")
    for sira, so in enumerate(isler):
        bolum = await _sayac_akisi(client, so.id, yol=(sira == 0))
        form = (await client.get(f"{BAKIM}/formlar/{so.id}")).json()
        govde = {
            "version": form["form"]["version"],
            "zone": "Giriş Kapısı",
            "performed_work": "Periyodik bakım yapıldı",
            "technician_note": "Sorun yok",
            "bakim_sonucu": "TAMAMLANDI",
            "kontroller": tum_uygun(form),
        }
        r = await client.put(f"{BAKIM}/formlar/{so.id}", json=govde)
        assert r.status_code == 200, r.text
        r = await client.post(
            f"{BAKIM}/formlar/{so.id}/onay",
            json={"tur": "ALINAMADI", "eksik_nedeni": "Yetkili yok"},
        )
        assert r.status_code == 201, r.text
        # Açık sayaçla tamamlama 409; sayaç bitince tamamlanır.
        assert (await client.post(f"{BAKIM}/formlar/{so.id}/tamamla")).status_code == 409
        await _bitir(client, so.id, bolum)
        r = await client.post(f"{BAKIM}/formlar/{so.id}/tamamla")
        assert r.status_code == 200, r.text
        assert r.json()["so"]["status"] == "TAMAMLANDI"

    # 7) Dönem kapanışı ve değişmez ziyaret kayıtları.
    donem = await db.get(MaintenancePeriod, donem_id)
    await db.refresh(donem)
    assert donem.closing_kind == "TAMAMLANDI" and donem.closed_at is not None
    ziyaret_sayisi = await db.scalar(
        select(func.count(MaintenanceVisit.id)).where(
            MaintenanceVisit.service_order_id.in_([so.id for so in isler])
        )
    )
    assert ziyaret_sayisi == 2

    # Uzlaştırma görevi fark bulmaz; worker yeniden koşsa da yeni PB açılmaz.
    await worker.bakim_donem_uzlastirma(db, FakeClock())
    await worker.pb_uretimi(db, FakeClock())
    await db.commit()
    assert len(await pb_isleri(db, s["id"])) == 2
    await db.refresh(donem)
    assert donem.closing_kind == "TAMAMLANDI"

    assert await _mobilite_ozeti(db, kisiler["admin"]) == once
