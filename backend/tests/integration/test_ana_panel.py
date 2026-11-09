"""Ana Panel (KARARLAR 2026-11-04 §4): `GET /api/teknik-servis/ana-panel`.

Ana kural "sayı = liste": her tıklanabilir sayı (KPI kartı, birim kartı,
grafik dilimi) `liste_yolu`'nun açtığı `/isler?...` listesinin
`X-Toplam-Kayit` başlığıyla aynıdır. Kapsam: başka birimin işi hiçbir sayıya
girmez; personel kapsam dışıysa ekipte görünmez. İzinsiz 403, boş VT 200 ve
sıfırlar; süzgeçler listeye aynen taşınır.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from servis_yardimci import giris
from sqlalchemy import insert

from app.models import (
    Account,
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceHold,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServiceTimeEntry,
)

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)  # FakeClock başlangıcı (yerel 03:00)
TS = "/api/teknik-servis"
YOL = f"{TS}/ana-panel"


def _sla(bas_saat_once: float, sure_saat: int = 12) -> dict:
    bas = AN - timedelta(hours=bas_saat_once)
    hedef = bas + timedelta(hours=sure_saat)
    return {
        "sla_baslangic_at": bas,
        "cozum_hedef_at": hedef,
        "cozum_hedef_ilk_at": hedef,
        "sla_kaynak": "CANLI",
    }


async def _pb(db, servis_isi_ac, sozlesme_ac, *, durum: str = "PLANLANDI"):
    """Bu aya (Ocak 2026) planlı PB işi: hedef 10 Ocak, aktif plan 5 Ocak."""
    sozlesme = await sozlesme_ac()
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=AN, sequence_no=1, target_date=date(2026, 1, 10)
    )
    db.add_all([kalem, donem])
    await db.commit()
    so = await servis_isi_ac(
        tur="PB", durum=durum, contract_item_id=kalem.id, maintenance_period_id=donem.id
    )
    db.add(
        ServicePlan(
            service_order_id=so.id,
            plan_date=date(2026, 1, 5),
            duration_min=60,
            change_type="ILK_PLAN",
        )
    )
    await db.commit()
    return so


@pytest.fixture
async def veri(
    db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac, sozlesme_ac, lokasyon_ac
) -> dict:
    sef = await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    tek = await birimli_kullanici_ac(
        "tek_g", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    tek_h = await birimli_kullanici_ac(
        "tek_h", "SERVIS_TEKNISYEN", ["HABERLESME"], saha_rolu="TEKNISYEN"
    )
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    await kullanici_ac("satis", "SATIS")
    lok = await lokasyon_ac(ad="BJK Plaza")
    isler = {
        "kritik": await servis_isi_ac(durum="MUSTERI_TALEBI", oncelik="KRITIK", atananlar=[tek]),
        "saha": await servis_isi_ac(durum="SAHADA", atananlar=[tek], lokasyon=lok),
        "atolye": await servis_isi_ac(tur="ATOLYE", durum="ATOLYEDE"),
        "askida": await servis_isi_ac(durum="BEKLEMEDE"),
        "sla": await servis_isi_ac(durum="PLANLANDI", **_sla(13)),
        "tamam": await servis_isi_ac(durum="TAMAMLANDI", completed_at=AN - timedelta(minutes=30)),
        "h_kritik": await servis_isi_ac(
            birim="HABERLESME", durum="ISLEMDE", oncelik="KRITIK", atananlar=[tek_h]
        ),
        "poc": await servis_isi_ac(birim="POC", durum="MUSTERI_TALEBI"),
        "pb": await _pb(db, servis_isi_ac, sozlesme_ac),
    }
    db.add(
        ServiceOrderAssignment(
            service_order_id=isler["kritik"].id,
            user_id=sef.id,
            rol="SEF",
            assigned_at=AN,
        )
    )
    db.add(
        ServiceHold(
            service_order_id=isler["askida"].id,
            neden="MALZEME",
            onceki_durum="ISLEMDE",
            started_at=AN - timedelta(hours=5),
            sla_durdurur=False,
        )
    )
    for kisi, so in ((tek, isler["saha"]), (tek_h, isler["h_kritik"])):
        db.add(
            ServiceTimeEntry(
                service_order_id=so.id,
                user_id=kisi.id,
                faaliyet="SAHA",
                started_at=AN - timedelta(minutes=20),
                kaynak="CANLI",
                girildi_at=AN,
            )
        )
    await db.commit()
    return {"isler": isler, "sef": sef, "tek": tek, "tek_h": tek_h, "lok": lok}


def _kpi(govde: dict) -> dict[str, dict]:
    return {k["kod"]: k for k in govde["kpiler"]}


async def _liste_toplami(client, yol: str) -> int:
    parca = urlsplit(yol)
    assert parca.path == "/servis-isleri", yol
    r = await client.get(f"{TS}/isler?{parca.query}&limit=1")
    assert r.status_code == 200, (yol, r.text)
    return int(r.headers["X-Toplam-Kayit"])


async def _sayi_liste_esit(client, govde: dict) -> int:
    """Gövdedeki her (sayı, /servis-isleri yolu) çiftini listeyle karşılaştırır."""
    ciftler: list[tuple[int, str]] = []
    for k in govde["kpiler"]:
        if k["liste_yolu"] and k["liste_yolu"].startswith("/servis-isleri"):
            ciftler.append((k["deger"], k["liste_yolu"]))
    for b in govde["birim_ozeti"]:
        for ad, yol in b["yollar"].items():
            ciftler.append((b[ad], yol))
    g = govde["grafikler"]
    ciftler += [(d["deger"], d["liste_yolu"]) for d in g["durum_dagilimi"]]
    ciftler += [(d["deger"], d["liste_yolu"]) for d in g["bolum_is_yuku"]]
    ciftler += [(d["deger"], d["liste_yolu"]) for d in g["planli_bakim"]["parcalar"]]
    ciftler.append((g["planli_bakim"]["toplam"], g["planli_bakim"]["liste_yolu"]))
    for deger, yol in ciftler:
        assert await _liste_toplami(client, yol) == deger, yol
    return len(ciftler)


# --- İzin ve boş veritabanı -------------------------------------------------------------------


async def test_izinsiz_403(client, kullanici_ac) -> None:
    await kullanici_ac("satis_x", "DEPO")  # SATIS artık servis.gor taşır (§7.8)
    await giris(client, "satis_x")
    r = await client.get(YOL)
    assert r.status_code == 403


async def test_bos_veritabaninda_200_ve_sifirlar(client, kullanici_ac) -> None:
    await kullanici_ac("mudur_bos", "SERVIS_YONETICI")
    await giris(client, "mudur_bos")
    r = await client.get(YOL)
    assert r.status_code == 200, r.text
    govde = r.json()
    assert {k["kod"] for k in govde["kpiler"]} == {
        "acik_is",
        "planli_bakim",
        "acil_ariza",
        "poc_acik",
        "sla_riski",
        "sahadaki_ekip",
        "askida",
        "bekleyen_onay",
    }
    assert all(k["deger"] == 0 for k in govde["kpiler"])
    assert _kpi(govde)["sahadaki_ekip"]["toplam"] == 0
    # Sıfır karşılaştırma tabanı "%" üretmez (0'a bölme yok, uydurma değişim yok).
    assert all(k["degisim_yuzde"] is None for k in govde["kpiler"])
    assert govde["aktif_isler"]["satirlar"] == []
    assert govde["bekleyen_aksiyonlar"] == {"satirlar": [], "ozet": [], "toplam": 0}
    assert all(b["acik"] == 0 and b["tamamlanma_yuzde"] is None for b in govde["birim_ozeti"])
    assert govde["grafikler"]["planli_bakim"]["yuzde"] is None
    assert len(govde["grafikler"]["haftalik_plan"]) == 7
    assert govde["donem"] == {
        "bas": "2026-01-01",
        "bit": "2026-01-01",
        "aralik": "20260101-20260101",
    }
    await _sayi_liste_esit(client, govde)


async def test_birimsiz_sef_fail_closed(client, birimli_kullanici_ac, veri) -> None:
    await birimli_kullanici_ac("sef_bos", "SERVIS_SEF", [])
    await giris(client, "sef_bos")
    r = await client.get(YOL)
    assert r.status_code == 200, r.text
    govde = r.json()
    assert all(k["deger"] == 0 for k in govde["kpiler"])
    assert govde["birim_ozeti"] == []
    assert govde["aktif_isler"]["satirlar"] == []


# --- Sayı = liste ve kapsam -----------------------------------------------------------------


async def test_yonetici_tum_birimler_ve_sayi_liste(client, veri) -> None:
    await giris(client, "mudur")
    r = await client.get(YOL)
    assert r.status_code == 200, r.text
    govde = r.json()
    k = _kpi(govde)
    assert k["acik_is"]["deger"] == 7  # PB ve TAMAMLANDI hariç
    assert k["acil_ariza"]["deger"] == 2
    assert k["poc_acik"]["deger"] == 1
    assert k["sla_riski"]["deger"] == 1
    assert k["askida"]["deger"] == 1
    assert k["bekleyen_onay"]["deger"] == 1
    assert k["planli_bakim"]["deger"] == 1
    assert k["planli_bakim"]["onceki_deger"] == 1  # hedef: bu aya hedefli PB
    assert k["planli_bakim"]["karsilastirma"] == "hedefe göre"
    assert (k["sahadaki_ekip"]["deger"], k["sahadaki_ekip"]["toplam"]) == (2, 3)
    assert k["sahadaki_ekip"]["liste_yolu"] == "/operasyon?sekme=personel"
    assert {b["birim"] for b in govde["birim_ozeti"]} >= {"GUVENLIK", "HABERLESME", "POC"}
    sayi = await _sayi_liste_esit(client, govde)
    assert sayi > 30


async def test_kapsam_baska_birimin_isi_sayilmaz(client, veri) -> None:
    await giris(client, "sef_g")
    r = await client.get(YOL)
    assert r.status_code == 200, r.text
    govde = r.json()
    k = _kpi(govde)
    assert k["acik_is"]["deger"] == 5
    assert k["acil_ariza"]["deger"] == 1  # HABERLESME kritiği sayılmaz
    # Rol testi tur 2 (B-12): POC kapsamda değilse kart hiç dönmez.
    assert "poc_acik" not in k
    assert (k["sahadaki_ekip"]["deger"], k["sahadaki_ekip"]["toplam"]) == (1, 2)
    assert [b["birim"] for b in govde["birim_ozeti"]] == ["GUVENLIK"]
    guv = govde["birim_ozeti"][0]
    assert (guv["acik"], guv["sahada"], guv["atolyede"], guv["tamamlanan"]) == (5, 1, 1, 1)
    assert guv["tamamlanma_yuzde"] == round(100 / 6)
    nolar = {s["no"] for s in govde["aktif_isler"]["satirlar"]}
    assert veri["isler"]["h_kritik"].so_no not in nolar
    assert veri["isler"]["poc"].so_no not in nolar
    assert veri["isler"]["saha"].so_no in nolar
    assert [b["birim"] for b in govde["grafikler"]["bolum_is_yuku"]] == ["GUVENLIK"]
    ekip = govde["ekip_durumu"]
    assert ekip["gorunur"] is True
    adlar = {s["ad"] for s in ekip["satirlar"]}
    assert "Tek_H" not in adlar
    tek_satir = next(s for s in ekip["satirlar"] if s["user_id"] == veri["tek"].id)
    assert tek_satir["durum"] == "SAHADA"
    assert tek_satir["is_"]["no"] == veri["isler"]["saha"].so_no
    assert tek_satir["is_"]["lokasyon"] == "BJK Plaza"
    assert tek_satir["sure_dk"] == 20
    sef_satir = next(s for s in ekip["satirlar"] if s["user_id"] == veri["sef"].id)
    assert sef_satir["durum"] == "MUSAIT"
    hedefler = {a["hedef_birim"]: a for a in govde["bekleyen_aksiyonlar"]["satirlar"]}
    assert hedefler["Depo"]["kayit_no"] == veri["isler"]["askida"].so_no
    assert hedefler["Depo"]["bekleme_dk"] == 300
    assert "Şef (kapanış onayı)" in hedefler
    assert "Mali İşler" not in hedefler  # tahsilat.gor yok; zaten uygun iş de yok
    await _sayi_liste_esit(client, govde)


async def test_aktif_is_satiri_tayin_ve_sla(client, veri) -> None:
    await giris(client, "sef_g")
    govde = (await client.get(YOL)).json()
    satirlar = {s["no"]: s for s in govde["aktif_isler"]["satirlar"]}
    kritik = satirlar[veri["isler"]["kritik"].so_no]
    assert [p["ad"] for p in kritik["tayin_edilen_personel"]] == ["Tek_G"]
    assert kritik["tayin_edilen_personel"][0]["sorumlu"] is True
    assert [p["ad"] for p in kritik["tayin_edilen_sef"]] == ["Sef_G"]
    assert kritik["arac"] is None
    sla = satirlar[veri["isler"]["sla"].so_no]["sla"]
    assert sla["durum"] == "ASILDI" and sla["olculur"] is True
    assert len(govde["aktif_isler"]["satirlar"]) <= 10
    # Maliyet/fiyat alanı yok.
    metin = str(govde).lower()
    for yasak in ("maliyet", "fiyat", "tutar", "gelir"):
        assert yasak not in metin


async def test_fatura_devri_bekleyen_tutarsiz_aksiyon(client, db, kullanici_ac, veri) -> None:
    """`tahsilat.gor` sahibine "Mali İşler" aksiyonu; gelir TUTARI dönmez."""
    from decimal import Decimal

    from app.models.servis_maliyet import ServiceOrderFinancial

    tamam = veri["isler"]["tamam"]
    db.add(
        ServiceOrderFinancial(
            service_order_id=tamam.id,
            gelir=Decimal("1234.56"),
            gelir_kaynagi="ELLE",
            gelir_notu="test",
        )
    )
    # Kalite kapısı (KARARLAR 2026-11-04 §7.2): yalnız kalite onaylı iş devre düşer.
    tamam.kalite_onay_at = tamam.completed_at
    await db.commit()
    await kullanici_ac("yonetim", "YONETIM")
    await giris(client, "yonetim")
    r = await client.get(YOL)
    assert r.status_code == 200, r.text
    aksiyonlar = r.json()["bekleyen_aksiyonlar"]
    mali = [a for a in aksiyonlar["satirlar"] if a["hedef_birim"] == "Mali İşler"]
    assert [a["kayit_no"] for a in mali] == [tamam.so_no]
    assert {"hedef_birim": "Mali İşler", "adet": 1} in aksiyonlar["ozet"]
    assert "1234" not in r.text
    # Teknisyen/şef (tahsilat.gor yok) bu aksiyonu görmez.
    await giris(client, "sef_g")
    hedefler = {
        a["hedef_birim"] for a in (await client.get(YOL)).json()["bekleyen_aksiyonlar"]["satirlar"]
    }
    assert "Mali İşler" not in hedefler


async def test_teknisyen_ana_panele_erisemez(client, veri) -> None:
    """2026-11-09: Ana Panel ekip yönetimi ekranı (`takip.gor`); saha teknisyeni
    işini "Benim İşlerim"den yürütür, menüde de görmez."""
    await giris(client, "tek_g")
    r = await client.get(YOL)
    assert r.status_code == 403, r.text


# --- Süzgeçler ------------------------------------------------------------------------------


async def test_suzgecler_listeye_aynen_tasinir(client, veri) -> None:
    await giris(client, "mudur")
    durumlar = [
        ({"birim": "HABERLESME"}, 1),
        ({"personel_id": veri["tek"].id}, 2),
        ({"sef_id": veri["sef"].id}, 1),
        ({"lokasyon_id": veri["lok"].id}, 1),
        ({"durum_grubu": "SAHA"}, 2),
    ]
    for params, beklenen in durumlar:
        r = await client.get(YOL, params=params)
        assert r.status_code == 200, (params, r.text)
        govde = r.json()
        assert _kpi(govde)["acik_is"]["deger"] == beklenen, params
        yol = _kpi(govde)["acik_is"]["liste_yolu"]
        for anahtar, deger in params.items():
            liste_adi = {"personel_id": "teknisyen_id", "lokasyon_id": "adres_id"}.get(
                anahtar, anahtar
            )
            assert f"{liste_adi}={deger}" in yol, (params, yol)
        await _sayi_liste_esit(client, govde)
    # Başka birim süzülünce POC kartı tıklanamaz ve sıfırdır.
    govde = (await client.get(YOL, params={"birim": "GUVENLIK"})).json()
    assert _kpi(govde)["poc_acik"] == {**_kpi(govde)["poc_acik"], "deger": 0, "liste_yolu": None}
    assert [b["birim"] for b in govde["birim_ozeti"]] == ["GUVENLIK"]


async def test_suzgec_dogrulamasi(client, veri) -> None:
    await giris(client, "sef_g")
    assert (await client.get(YOL, params={"birim": "HABERLESME"})).status_code == 403
    assert (await client.get(YOL, params={"birim": "YOK"})).status_code == 400
    assert (await client.get(YOL, params={"durum_grubu": "YOK"})).status_code == 400
    r = await client.get(YOL, params={"bas": "2026-02-01", "bit": "2026-01-01"})
    assert r.status_code == 400
    r = await client.get(YOL, params={"bas": "2023-01-01", "bit": "2026-01-01"})
    assert r.status_code == 400  # 24 aydan uzun dönem


async def test_donem_tamamlanani_ve_onceki_deger(client, veri) -> None:
    await giris(client, "mudur")
    # Dönem dışı (Şubat): Ocak'ta tamamlanan iş birim kartında sayılmaz.
    govde = (await client.get(YOL, params={"bas": "2026-02-01", "bit": "2026-02-28"})).json()
    guv = next(b for b in govde["birim_ozeti"] if b["birim"] == "GUVENLIK")
    assert guv["tamamlanan"] == 0
    assert "donem=20260201-20260228" in guv["yollar"]["tamamlanan"]
    await _sayi_liste_esit(client, govde)
    # Dönem başı bütün açılışlardan sonraya alınınca bugün açık işler o anda da
    # açıktır (önceki = şimdiki, değişim %0); Ocak'ta tamamlanan iş açık sayılmaz.
    govde = (await client.get(YOL, params={"bas": "2099-01-01", "bit": "2099-01-31"})).json()
    k = _kpi(govde)
    assert (k["acik_is"]["deger"], k["acik_is"]["onceki_deger"]) == (7, 7)
    assert k["acik_is"]["degisim_yuzde"] == 0.0
    assert k["acik_is"]["karsilastirma"] == "dönem başına göre"
    assert (k["askida"]["onceki_deger"], k["acil_ariza"]["onceki_deger"]) == (1, 2)
    assert k["sla_riski"]["onceki_deger"] is None
    # Durum grubu seçiliyken geçmiş durum bilinmez → önceki değer yok.
    govde = (await client.get(YOL, params={"durum_grubu": "ACIK"})).json()
    assert _kpi(govde)["acik_is"]["onceki_deger"] is None


# --- Performans (slow) ------------------------------------------------------------------------


@pytest.mark.slow
async def test_on_bin_iste_ana_panel_bir_saniyenin_altinda(
    client, db, kullanici_ac, birimli_kullanici_ac
) -> None:
    await kullanici_ac("mudur_hacim", "SERVIS_YONETICI")
    await birimli_kullanici_ac("sef_hacim", "SERVIS_SEF", ["GUVENLIK"])
    hesap = Account(title="Hacim Müşterisi A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    durumlar = ("MUSTERI_TALEBI", "PLANLANDI", "SAHADA", "TAMAMLANDI", "BEKLEMEDE", "KAPATILDI")
    satirlar = [
        {
            "so_no": f"SRV-202601-{i:06d}",
            "birim": ("GUVENLIK", "HABERLESME", "POC")[i % 3],
            "tur": "ARIZA",
            "kategori": "GUNLUK_SERVIS",
            "status": durumlar[i % len(durumlar)],
            "oncelik": "KRITIK" if i % 7 == 0 else "NORMAL",
            "customer_id": hesap.id,
            "konu": f"Hacim işi {i}",
            "reopen_count": 0,
            "created_at": AN - timedelta(minutes=i),
            "completed_at": AN - timedelta(minutes=i // 2) if i % 6 in (3, 5) else None,
        }
        for i in range(1, 10_001)
    ]
    await db.execute(insert(ServiceOrder), satirlar)
    await db.commit()
    for kullanici in ("mudur_hacim", "sef_hacim"):
        await giris(client, kullanici)
        await client.get(YOL)  # ısınma
        sureler = []
        for _ in range(3):
            bas = time.perf_counter()
            r = await client.get(YOL)
            sureler.append(time.perf_counter() - bas)
        assert r.status_code == 200, r.text
        print(f"ana-panel {kullanici} (sn): {', '.join(f'{s:.3f}' for s in sureler)}")
        assert min(sureler) < 1.0, f"ana panel {min(sureler):.3f} sn"
