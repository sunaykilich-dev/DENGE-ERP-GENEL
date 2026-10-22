"""Operasyon Merkezi: sayaçlar, SLA sıralı liste, personel iş yükü (TS-082, E10-08/09/10/14).

Ana kural "sayı = liste": her sayaç `/operasyon/isler?kpi=` ve `/isler?kpi=`
`X-Toplam-Kayit` ile aynıdır (tek KPI kaydı). Birim kapsamı sayaca da uygulanır;
PB işleri servis sayaçlarında yok, "vadesi geçen bakım"da var (vade = hedef +
tolerans). Kişi bazlı çalışılan dakika yalnız `servis_rapor.personel` ile döner.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from servis_yardimci import giris

from app.models import (
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceHold,
    ServicePlan,
    ServicePlanMember,
    ServiceTimeEntry,
)

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)  # FakeClock başlangıcı (yerel 03:00)
TS = "/api/teknik-servis"


def _sla(bas_saat_once: float, sure_saat: int = 12) -> dict:
    bas = AN - timedelta(hours=bas_saat_once)
    hedef = bas + timedelta(hours=sure_saat)
    return {
        "sla_baslangic_at": bas,
        "cozum_hedef_at": hedef,
        "cozum_hedef_ilk_at": hedef,
        "sla_kaynak": "CANLI",
        "created_at": bas,
    }


async def _pb(db, servis_isi_ac, sozlesme_ac, hedef: date):
    sozlesme = await sozlesme_ac()
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=AN, sequence_no=1, target_date=hedef
    )
    db.add_all([kalem, donem])
    await db.commit()
    return await servis_isi_ac(
        tur="PB",
        durum="PLANLAMADA",
        contract_item_id=kalem.id,
        maintenance_period_id=donem.id,
    )


@pytest.fixture
async def veri(client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac, sozlesme_ac):
    tek = await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    tek_b = await birimli_kullanici_ac(
        "tek_b", "SERVIS_TEKNISYEN", ["HABERLESME"], saha_rolu="TEKNISYEN"
    )
    await birimli_kullanici_ac("sef_a", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    await birimli_kullanici_ac("op_a", "SERVIS_OPERASYON", ["GUVENLIK"])
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    await kullanici_ac("yonetim", "YONETIM")
    await kullanici_ac("satis", "SATIS")
    isler = {
        "asildi": await servis_isi_ac(
            durum="ISLEMDE", oncelik="KRITIK", atananlar=[tek], **_sla(13)
        ),  # noqa: E501
        "riskte": await servis_isi_ac(durum="PLANLANDI", **_sla(11)),
        "zamaninda": await servis_isi_ac(durum="MUSTERI_TALEBI", **_sla(1, 24)),
        "durduruldu": await servis_isi_ac(durum="BEKLEMEDE", **_sla(14)),
        "damgasiz": await servis_isi_ac(durum="MUSTERI_TALEBI"),
        "b_asildi": await servis_isi_ac(
            birim="HABERLESME", durum="SAHADA", atananlar=[tek_b], **_sla(20)
        ),  # noqa: E501
        "pb_gecmis": await _pb(db, servis_isi_ac, sozlesme_ac, date(2025, 11, 1)),
        "pb_toleransta": await _pb(db, servis_isi_ac, sozlesme_ac, date(2025, 12, 20)),
    }
    isler["tek_id"] = tek.id
    db.add(
        ServiceHold(
            service_order_id=isler["durduruldu"].id,
            neden="MUSTERI_ONAYI",
            onceki_durum="ISLEMDE",
            started_at=AN - timedelta(hours=2),
            sla_durdurur=True,
            beklenen_bitis_at=AN - timedelta(hours=1),
        )
    )
    plan = ServicePlan(
        service_order_id=isler["asildi"].id,
        plan_date=date(2026, 1, 1),
        duration_min=60,
        change_type="ILK_PLAN",
    )
    db.add(plan)
    await db.flush()
    db.add(ServicePlanMember(plan_id=plan.id, user_id=tek.id, rol="TEKNISYEN"))
    db.add(
        ServiceTimeEntry(
            service_order_id=isler["asildi"].id,
            user_id=tek.id,
            faaliyet="SAHA",
            started_at=AN - timedelta(hours=2),
            ended_at=AN - timedelta(hours=1, minutes=30),
            kaynak="MANUEL",
            girildi_at=AN,
        )
    )
    db.add(
        ServiceTimeEntry(
            service_order_id=isler["b_asildi"].id,
            user_id=tek_b.id,
            faaliyet="SAHA",
            started_at=AN - timedelta(minutes=20),
            kaynak="CANLI",
            girildi_at=AN,
        )
    )
    await db.commit()
    return isler


async def _toplam(client, yol: str, **params) -> int:
    r = await client.get(yol, params={"limit": 1, **params})
    assert r.status_code == 200, r.text
    return int(r.headers["X-Toplam-Kayit"])


async def test_rbac(client, veri) -> None:
    """E10-14: teknisyen ve satış 403; şef, operasyon uzmanı, yönetim 200."""
    for kullanici, beklenen in (
        ("tek", 403),
        ("satis", 403),
        ("sef_a", 200),
        ("op_a", 200),
        ("yonetim", 200),
    ):
        await giris(client, kullanici)
        for yol in ("ozet", "isler", "personel"):
            r = await client.get(f"{TS}/operasyon/{yol}")
            assert r.status_code == beklenen, (kullanici, yol, r.text)


async def test_sayac_liste_esitligi_ve_degerler(client, veri) -> None:
    """Kabul (1)(3)(4)(7): sayaç = operasyon listesi = servis listesi; PB servis sayacında yok."""
    beklenen = {
        "sef_a": {"sla_asildi": 1, "sla_riskte": 1, "sla_durduruldu": 1, "vadesi_gecen_bakim": 1},
        "mudur": {"sla_asildi": 2, "sla_riskte": 1, "sla_durduruldu": 1, "vadesi_gecen_bakim": 1},
    }
    for kullanici, degerler in beklenen.items():
        await giris(client, kullanici)
        r = await client.get(f"{TS}/operasyon/ozet")
        assert r.status_code == 200, r.text
        sayaclar = {s["kod"]: s for s in r.json()["sayaclar"]}
        for kod, deger in degerler.items():
            assert sayaclar[kod]["deger"] == deger, (kullanici, kod)
        assert sayaclar["bekleme_bitis_gecti"]["deger"] == 1
        for kod, s in sayaclar.items():
            assert s["yol"].startswith(f"/operasyon?kpi={kod}")
            assert s["deger"] == await _toplam(client, f"{TS}/operasyon/isler", kpi=kod), kod
            assert s["deger"] == await _toplam(client, f"{TS}/isler", kpi=kod), kod
        # Servis Paneli aynı KPI kaydından aynı sayıyı verir (K15).
        panel = {k["kod"]: k["deger"] for k in (await client.get(f"{TS}/panel")).json()["kutular"]}
        assert panel["sla_asildi"] == sayaclar["sla_asildi"]["deger"]


async def test_birim_ve_oncelik_suzgeci(client, veri) -> None:
    await giris(client, "mudur")
    r = await client.get(f"{TS}/operasyon/ozet", params={"birim": "HABERLESME"})
    sayaclar = {s["kod"]: s["deger"] for s in r.json()["sayaclar"]}
    assert sayaclar["sla_asildi"] == 1 and sayaclar["sla_riskte"] == 0
    r = await client.get(f"{TS}/operasyon/ozet", params={"oncelik": "kritik"})
    assert {s["kod"]: s["deger"] for s in r.json()["sayaclar"]}["sla_asildi"] == 1
    assert (await client.get(f"{TS}/operasyon/ozet", params={"oncelik": "Acil"})).status_code == 400
    assert (await client.get(f"{TS}/operasyon/isler", params={"kpi": "yok"})).status_code == 400
    await giris(client, "sef_a")
    r = await client.get(f"{TS}/operasyon/ozet", params={"birim": "HABERLESME"})
    assert r.status_code == 403


async def test_liste_sla_sirali(client, veri) -> None:
    """Kabul (2): en acil (en küçük kalan) önce; durdurulan sonra; damgasız en sonda."""
    await giris(client, "sef_a")
    r = await client.get(f"{TS}/operasyon/isler", params={"kpi": "acik", "limit": 50})
    assert r.status_code == 200, r.text
    satirlar = r.json()
    nolar = [s["id"] for s in satirlar]
    assert nolar[:2] == [veri["asildi"].id, veri["riskte"].id]
    durumlar = [s["sla"]["durum"] for s in satirlar]
    assert durumlar.index("DURDURULDU") > durumlar.index("ZAMANINDA")
    assert durumlar[-1] == "OLCULEMEDI"
    assert satirlar[0]["sla"]["kalan_dk"] == -60
    assert satirlar[0]["sorumlu"]["id"] is not None
    for s in satirlar:  # fiyat/maliyet alanı yok
        assert not ({"fiyat", "tutar", "maliyet", "unit_price"} & set(s))
    # Teknisyen süzgeci.
    r = await client.get(
        f"{TS}/operasyon/isler", params={"kpi": "acik", "teknisyen_id": veri["tek_id"]}
    )
    assert [s["id"] for s in r.json()] == [veri["asildi"].id]


async def test_vade_tolerans(client, veri) -> None:
    """E10-10: tolerans içindeki PB (hedef + 30 gün geçmemiş) vadesi geçmiş sayılmaz."""
    await giris(client, "mudur")
    r = await client.get(f"{TS}/operasyon/isler", params={"kpi": "vadesi_gecen_bakim"})
    satirlar = r.json()
    assert [s["id"] for s in satirlar] == [veri["pb_gecmis"].id]
    assert satirlar[0]["sla"]["durum"] == "SLA_DISI_PB"
    assert satirlar[0]["sla"]["vade_ay"] == "Aralık 2025"


async def test_personel_is_yuku(client, veri) -> None:
    """E10-09: kişi bazlı; başka birim personeli görünmez; çalışılan dk yalnız
    `servis_rapor.personel` ile (anahtar olarak yok)."""
    await giris(client, "sef_a")
    r = await client.get(f"{TS}/operasyon/personel")
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["kisi_saat_gorunur"] is True
    satirlar = {s["ad"]: s for s in govde["personel"]}
    assert "Tek_B" not in satirlar and "Tek" in satirlar
    tek = satirlar["Tek"]
    assert tek["bugun_planli"] == 1 and tek["yarin_planli"] == 0 and tek["acik_atanmis"] == 1
    assert tek["acik_sayac"] is None
    # 22:00-22:30 UTC = yerel 01:00-01:30 → Türkiye gününe göre BUGÜN.
    assert tek["bugun_calisilan_dk"] == 30
    assert satirlar["Sef_A"]["bugun_calisilan_dk"] is None  # kayıt yok → eksik, 0 değil

    await giris(client, "op_a")  # operasyon uzmanı: servis_rapor.personel yok
    govde = (await client.get(f"{TS}/operasyon/personel")).json()
    assert govde["kisi_saat_gorunur"] is False
    assert all("bugun_calisilan_dk" not in s for s in govde["personel"])

    await giris(client, "mudur")
    satirlar = {
        s["ad"]: s for s in (await client.get(f"{TS}/operasyon/personel")).json()["personel"]
    }  # noqa: E501
    assert satirlar["Tek_B"]["acik_sayac"]["so_no"] == veri["b_asildi"].so_no
    assert satirlar["Tek_B"]["acik_sayac"]["faaliyet"] == "SAHA"


async def test_sla_karti_kapsam_disi_404_veri_degismez(client, db, veri) -> None:
    await giris(client, "sef_a")
    hedef = veri["b_asildi"]
    once = (hedef.version, hedef.gecikme_nedeni)
    assert (await client.get(f"{TS}/operasyon/isler/{hedef.id}/sla")).status_code == 404
    r = await client.put(
        f"{TS}/operasyon/isler/{hedef.id}/kapanis-bilgisi", json={"gecikme_nedeni": "ULASIM"}
    )
    assert r.status_code == 404
    await db.refresh(hedef)
    assert (hedef.version, hedef.gecikme_nedeni) == once
    r = await client.get(f"{TS}/operasyon/isler/{veri['asildi'].id}/sla")
    assert r.status_code == 200 and r.json()["sla"]["durum"] == "ASILDI"
