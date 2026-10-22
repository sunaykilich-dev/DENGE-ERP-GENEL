"""Servis Paneli ve tek KPI tanım kaydı (TS-035, E01-14) + servis uyarıları ve
arama (TS-037, E01-18).

Ana kural "sayı = liste": her kutunun sayısı, aynı süzgeçle açılan
`/isler?kpi=<kod>` listesinin `X-Toplam-Kayit` başlığına eşittir. Birim
kapsamı kutuya da uygulanır (A biriminin şefi B'nin işini saymaz); PB işleri
servis kutularına girmez, bakım kutularında sayılır.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.models import (
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceHold,
    ServiceOrderSerial,
    ServicePlan,
    ServiceResult,
    ServiceTimeEntry,
)
from app.services.teknik_servis import panel

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)  # FakeClock başlangıcı (yerel 03:00)


async def _giris(client, username: str) -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


def _kutular(govde) -> dict[str, dict]:
    return {k["kod"]: k for k in govde["kutular"]}


async def _liste_toplami(client, kod: str, **params) -> int:
    r = await client.get("/api/teknik-servis/isler", params={"kpi": kod, "limit": 1, **params})
    assert r.status_code == 200, r.text
    return int(r.headers["X-Toplam-Kayit"])


async def _pb_isi(db, servis_isi_ac, sozlesme_ac, *, birim="GUVENLIK", durum="PLANLAMADA", hedef):
    sozlesme = await sozlesme_ac(birim=birim)
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=AN, sequence_no=1, target_date=hedef
    )
    db.add_all([kalem, donem])
    await db.commit()
    return await servis_isi_ac(
        birim=birim,
        tur="PB",
        durum=durum,
        seriler=[],
        contract_item_id=kalem.id,
        maintenance_period_id=donem.id,
        created_at=AN,
    )


@pytest.fixture
async def veri(client, db, birimli_kullanici_ac, kullanici_ac, servis_isi_ac, sozlesme_ac):
    """GUVENLIK biriminde her kutuya düşen işler + HABERLESME'de gürültü."""
    tek = await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    await birimli_kullanici_ac("sef_a", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_b", "SERVIS_SEF", ["HABERLESME"])
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    await kullanici_ac("satis", "SATIS")

    async def ac(**kw):
        kw.setdefault("created_at", AN)
        return await servis_isi_ac(**kw)

    isler = {
        "talep": await ac(durum="MUSTERI_TALEBI", oncelik="KRITIK"),
        "planlandi": await ac(durum="PLANLANDI", atananlar=[tek]),
        "yolda": await ac(durum="YOLA_CIKILDI", atananlar=[tek]),
        "sahada": await ac(durum="SAHADA", atananlar=[tek]),
        "islemde": await ac(durum="ISLEMDE", atananlar=[tek]),
        "atolye": await ac(durum="ATOLYEDE", tur="ATOLYE", atananlar=[tek]),
        "bekleme": await ac(durum="BEKLEMEDE", atananlar=[tek]),
        "tamam": await ac(
            durum="TAMAMLANDI",
            atananlar=[tek],
            completed_at=AN - timedelta(days=5),
            first_completed_at=AN - timedelta(days=5),
            reported_at=AN - timedelta(days=6),
        ),
        "uzaktan": await ac(
            durum="KAPATILDI",
            completed_at=AN - timedelta(hours=1),
            first_completed_at=AN - timedelta(hours=1),
            closed_at=AN - timedelta(minutes=30),
        ),
        "eski_acik": await ac(durum="PLANLAMADA", created_at=AN - timedelta(days=40)),
        # Gürültü: başka birim (şef A'ya görünmez) ve iptal.
        "haberlesme": await ac(birim="HABERLESME", durum="MUSTERI_TALEBI", oncelik="KRITIK"),
        "iptal": await ac(durum="IPTAL", cancel_reason="Vazgeçildi", cancelled_at=AN),
    }
    isler["pb"] = await _pb_isi(db, servis_isi_ac, sozlesme_ac, hedef=date(2025, 12, 1))
    # Bekleme 10 gündür sürüyor (uzun beklemede uyarısı).
    db.add(
        ServiceHold(
            service_order_id=isler["bekleme"].id,
            neden="MALZEME",
            onceki_durum="ISLEMDE",
            started_at=AN - timedelta(days=10),
            sla_durdurur=False,
        )
    )
    db.add(
        ServiceResult(
            service_order_id=isler["uzaktan"].id,
            sonuc="COZULDU",
            cozum_kanali="TELEFON",
            yapilan_islem="Telefonla çözüldü",
        )
    )
    db.add(
        ServicePlan(
            service_order_id=isler["planlandi"].id,
            plan_date=date(2026, 1, 1),
            duration_min=60,
            change_type="ILK_PLAN",
        )
    )
    await db.commit()
    return isler


async def test_her_kutu_sayisi_liste_toplamina_esit(client, veri):
    """Kabul (1): her KPI için `/panel` sayısı = `/isler?kpi=` `X-Toplam-Kayit`
    (şef A ve yönetici için ayrı ayrı; uyarı KPI'ları dahil)."""
    for kullanici in ("sef_a", "mudur"):
        await _giris(client, kullanici)
        r = await client.get("/api/teknik-servis/panel")
        assert r.status_code == 200, r.text
        kutular = _kutular(r.json())
        assert set(kutular) == {k for k, t in panel.KPI_TANIMLARI.items() if t.grup != "UYARI"}
        for kod, kutu in kutular.items():
            assert kutu["yol"].startswith(f"/servis-isleri?kpi={kod}")
            assert kutu["deger"] == await _liste_toplami(client, kod), (kullanici, kod)


async def test_kutu_degerleri_ve_birim_kapsami(client, veri):
    await _giris(client, "sef_a")
    k = _kutular((await client.get("/api/teknik-servis/panel")).json())
    # Kabul (3): 1 YOLA_CIKILDI + 1 SAHADA + 1 ISLEMDE → sahada 3.
    assert k["sahada"]["deger"] == 3
    assert k["plan_bekleyen"]["deger"] == 2  # talep + eski_acik (HABERLESME sayılmaz)
    assert k["kritik_acik"]["deger"] == 1  # yalnız GUVENLIK'teki
    assert k["atanmamis"]["deger"] == 2
    assert k["atolyede"]["deger"] == 1
    assert k["beklemede"]["deger"] == 1
    assert k["kapanis_bekleyen"]["deger"] == 1
    assert k["bugun_planli"]["deger"] == 1
    # Kabul (4): PB işi servis "açık" kutusunda YOK, bakım kutusunda VAR.
    assert k["acik"]["deger"] == 8
    assert k["bakim_acik"]["deger"] == 1
    assert k["bakim_geciken"]["deger"] == 1
    # Dönemsel (varsayılan "bu ay" = Ocak 2026 yerel)
    assert k["tamamlanan"]["deger"] == 1  # 'tamam' Aralık'ta tamamlandı
    assert k["uzaktan_cozulen"]["deger"] == 1
    # Kabul (6): HABERLESME şefi GUVENLIK işini saymaz.
    await _giris(client, "sef_b")
    kb = _kutular((await client.get("/api/teknik-servis/panel")).json())
    assert kb["acik"]["deger"] == 1
    assert kb["kritik_acik"]["deger"] == 1
    assert kb["sahada"]["deger"] == 0


async def test_donem_secimi_ve_olcumler(client, veri):
    await _giris(client, "mudur")
    ay = (await client.get("/api/teknik-servis/panel", params={"donem": "ay"})).json()
    son30 = (await client.get("/api/teknik-servis/panel", params={"donem": "son30"})).json()
    assert _kutular(ay)["tamamlanan"]["deger"] == 1
    assert _kutular(son30)["tamamlanan"]["deger"] == 2
    assert _kutular(son30)["tamamlanan"]["yol"].endswith("&donem=son30")
    assert son30["olcumler"]["uzaktan_oran_yuzde"] == 50.0
    assert son30["olcumler"]["cozum_olculen"] == 2
    assert son30["olcumler"]["cozum_tahmini"] == 1  # 'uzaktan'da reported_at yok
    assert son30["olcumler"]["ortalama_cozum_saat"] is not None
    r = await client.get("/api/teknik-servis/panel", params={"donem": "yil"})
    assert r.status_code == 400
    await _giris(client, "sef_b")  # birimde tamamlanan iş yok
    bos = (await client.get("/api/teknik-servis/panel", params={"donem": "son30"})).json()
    assert bos["olcumler"]["ortalama_cozum_saat"] is None  # 0 değil
    assert bos["olcumler"]["uzaktan_oran_yuzde"] is None


async def test_sure_kaydi_eksik_kutusu(client, db, veri):
    """Kabul (5): süre kaydı olmayan iş "eksik" kutusunda; kaydı olan değil."""
    await _giris(client, "mudur")
    once = _kutular(
        (await client.get("/api/teknik-servis/panel", params={"donem": "son30"})).json()
    )
    assert once["sure_eksik"]["deger"] == 2
    db.add(
        ServiceTimeEntry(
            service_order_id=veri["tamam"].id,
            user_id=veri["tamam"].atamalar[0].user_id,
            faaliyet="SAHA",
            started_at=AN - timedelta(days=5, hours=2),
            ended_at=AN - timedelta(days=5, hours=1),
            kaynak="MANUEL",
            girildi_at=AN - timedelta(days=5),
        )
    )
    await db.commit()
    sonra = _kutular(
        (await client.get("/api/teknik-servis/panel", params={"donem": "son30"})).json()
    )
    assert sonra["sure_eksik"]["deger"] == 1


async def test_tekrar_ariza_ayni_seri(client, db, servis_isi_ac, kullanici_ac):
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    ilk = await servis_isi_ac(durum="KAPATILDI", created_at=AN - timedelta(days=10))
    ikinci = await servis_isi_ac(durum="MUSTERI_TALEBI", created_at=AN)
    for so in (ilk, ikinci):
        db.add(ServiceOrderSerial(service_order_id=so.id, seri_no="sn-77", seri_norm="x"))
    await db.commit()
    await _giris(client, "mudur")
    k = _kutular((await client.get("/api/teknik-servis/panel")).json())
    assert k["tekrar_ariza"]["deger"] == 1
    assert await _liste_toplami(client, "tekrar_ariza") == 1


async def test_rbac_ve_bilinmeyen_kpi(client, veri):
    await _giris(client, "satis")
    assert (await client.get("/api/teknik-servis/panel")).status_code == 403
    await _giris(client, "sef_a")
    r = await client.get("/api/teknik-servis/isler", params={"kpi": "uydurma"})
    assert r.status_code == 400


def test_kpi_kaydi_tutarli():
    """Kayıt sözleşmesi: aynı kod iki farklı tanımla kaydedilemez; servis
    kutuları PB saymaz (süzgeç ifadesinde `tur != 'PB'`)."""
    tanim = panel.KPI_TANIMLARI["acik"]
    panel.kpi_kaydet(tanim)  # aynı tanım: sorun yok
    with pytest.raises(ValueError, match="zaten kayıtlı"):
        panel.kpi_kaydet(panel.KpiTanimi("acik", "Başka", "", tanim.suzgec, grup="BAKIM"))
    from sqlalchemy import select

    from app.models import ServiceOrder

    metin = str(tanim.suzgec(select(ServiceOrder.id)).compile())
    assert "tur !=" in metin


# --- Uyarılar (E01-18) ---------------------------------------------------------------


async def test_servis_uyarilari_kapsamli_ve_izinli(client, veri):
    await _giris(client, "sef_a")
    govde = (await client.get("/api/raporlar/uyarilar")).json()
    uyarilar = {u["kod"]: u for u in govde["uyarilar"]}
    # Kabul (1): B biriminin kritik işi A'nın uyarısında yok.
    assert uyarilar["servis.kritik_atanmamis"]["adet"] == 1
    assert uyarilar["servis.kritik_atanmamis"]["onem"] == "kritik"
    assert uyarilar["servis.kritik_atanmamis"]["yol"] == "/servis-isleri?kpi=kritik_atanmamis"
    assert uyarilar["servis.kapanis_gecikmis"]["adet"] == 1
    assert uyarilar["servis.uzun_beklemede"]["adet"] == 1
    for kod in ("kritik_atanmamis", "kapanis_gecikmis", "uzun_beklemede"):
        assert uyarilar[f"servis.{kod}"]["adet"] == await _liste_toplami(client, kod)
    # Kabul (2): servis.gor olmayan servis uyarısı görmez.
    await _giris(client, "satis")
    govde = (await client.get("/api/raporlar/uyarilar")).json()
    assert not [u for u in govde["uyarilar"] if u["kod"].startswith("servis.")]


# --- Genel arama (E01-18 (4)) ---------------------------------------------------------


async def test_servis_arama_kapsamli(db, veri, birimli_kullanici_ac):
    from sqlalchemy import select

    from app.models import User

    sef_a = await db.scalar(select(User).where(User.username == "sef_a"))
    hab = veri["haberlesme"]
    db.add(ServiceOrderSerial(service_order_id=veri["talep"].id, seri_no="AB-12/7", seri_norm="x"))
    db.add(ServiceOrderSerial(service_order_id=hab.id, seri_no="AB-12/9", seri_norm="x"))
    await db.commit()
    sonuc = await panel.servis_ara(db, sef_a, "ab-12", 20)
    assert [s["id"] for s in sonuc] == [veri["talep"].id]  # başka birimin işi YOK
    assert sonuc[0]["yol"] == f"/servis-isleri/{veri['talep'].id}"
    no = await panel.servis_ara(db, sef_a, hab.so_no, 20)
    assert no == []
    kendi = await panel.servis_ara(db, sef_a, veri["talep"].so_no, 20)
    assert [s["id"] for s in kendi] == [veri["talep"].id]
