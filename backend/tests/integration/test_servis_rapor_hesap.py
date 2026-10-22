"""Rapor parametre doğrulaması ve hesap kuralları (TS-181, TS-184, TS-186, TS-187, TS-201).

- Katalog dışı parametre 422 (`Literal`), tarih sırası / 24 ay 400, yetkisiz
  birim 403 (kontrol B14).
- Varsayılan dönem içinde bulunulan ay (FakeClock, Türkiye günü).
- Tekrar arıza penceresi istekte 7–180; özel pencerede Servis İşleri yolu yok.
- Tarih esası PLAN detay kümesini plan tarihine göre süzer.
- Atölye iptali açık sayılmaz; panel rapor KPI'larını kutu olarak çizmez.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from servis_rapor_ortam import DONEM, R, giris, kullanicilar

from app.models import ServicePlan, ServiceResult

pytestmark = pytest.mark.integration


def _z(gun: int, saat: int = 8, ay: int = 3) -> datetime:
    return datetime(2026, ay, gun, saat, tzinfo=UTC)


@pytest.fixture
async def ortam(client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac):
    k = await kullanicilar(db, kullanici_ac, birimli_kullanici_ac)
    eski = await servis_isi_ac(
        durum="KAPATILDI",
        created_at=_z(1),
        completed_at=_z(2),
        first_completed_at=_z(2),
        closed_at=_z(3),
    )
    db.add(
        ServiceResult(
            service_order_id=eski.id, sonuc="COZULDU", cozum_kanali="YERINDE", yapilan_islem="Tamam"
        )
    )
    yeni = await servis_isi_ac(
        durum="MUSTERI_TALEBI",
        created_at=_z(20),
        iliskili_is_id=eski.id,
        iliski_turu="TEKRAR_ARIZA",
        tekrar_ariza_aday=True,
        tekrar_ariza_teyit="AYNI_ARIZA",
    )
    planli = await servis_isi_ac(durum="PLANLANDI", created_at=_z(1, ay=2))
    db.add(ServicePlan(service_order_id=planli.id, plan_date=date(2026, 3, 5), duration_min=60,
                       change_type="ILK_PLAN"))  # fmt: skip
    atolye_iptal = await servis_isi_ac(
        tur="ATOLYE",
        durum="IPTAL",
        created_at=_z(4),
        cancelled_at=_z(6),
        cancel_reason="Atölye kaydı iptal",
    )
    await db.commit()
    return k, {"eski": eski, "yeni": yeni, "planli": planli, "atolye_iptal": atolye_iptal}


@pytest.mark.parametrize(
    ("params", "kod"),
    [
        ({"baslangic": "2026-03-31", "bitis": "2026-03-01"}, 400),
        ({"baslangic": "2024-01-01", "bitis": "2026-01-31"}, 400),
        ({**DONEM, "sehir": "Atlantis"}, 400),
        ({**DONEM, "kategori": "XYZ"}, 422),
        ({**DONEM, "birim": "UZAY"}, 422),
        ({**DONEM, "durum_grubu": "KAPALI"}, 422),
        ({**DONEM, "tarih_esasi": "DUN"}, 422),
        ({**DONEM, "tekrar_gun": 200}, 422),
        ({**DONEM, "tekrar_gun": 6}, 422),
        ({**DONEM, "baslangic": "2026-02-30"}, 422),
    ],
)
async def test_parametre_dogrulama(client, ortam, params, kod):
    await giris(client, "mudur")
    r = await client.get(f"{R}/ozet", params=params)
    assert r.status_code == kod, r.text


async def test_bilinmeyen_kpi_ve_boyut_422(client, ortam):
    await giris(client, "mudur")
    r = await client.get(f"{R}/kpi-liste", params={**DONEM, "kpi": "yok_boyle"})
    assert r.status_code == 422
    r = await client.get(f"{R}/kirilim", params={**DONEM, "boyut": "renk"})
    assert r.status_code == 422


async def test_yetkisiz_birim_403_ve_kapsam(client, ortam):
    await giris(client, "sef_g")
    r = await client.get(f"{R}/ozet", params={**DONEM, "birim": "HABERLESME"})
    assert r.status_code == 403
    r = await client.get(f"{R}/ozet", params={**DONEM, "birim": "GUVENLIK"})
    assert r.status_code == 200
    # HABERLEŞME şefi GÜVENLİK işlerini saymaz (sayı = sızıntı).
    await giris(client, "sef_h")
    r = await client.get(f"{R}/ozet", params=DONEM)
    degerler = {k["kod"]: k["deger"] for k in r.json()["kpiler"]}
    assert degerler["rapor_gelen"] == 0 and degerler["rapor_cozulen"] == 0
    assert r.json()["kapsam"] == "Birimler: Haberleşme"


async def test_varsayilan_donem_bu_ay(client, ortam):
    await giris(client, "mudur")
    r = await client.get(f"{R}/ozet")
    assert r.status_code == 200, r.text
    govde = r.json()
    # Ay başı → bugün (FakeClock 2026-01-01); önceki dönem eşit uzunlukta.
    assert govde["donem"]["donem"] == "20260101-20260101"
    assert govde["onceki_donem"]["donem"] == "20251231-20251231"


async def test_tekrar_ariza_penceresi(client, ortam):
    await giris(client, "mudur")
    r = await client.get(f"{R}/tekrar-ariza", params=DONEM)
    govde = r.json()
    kpi = {k["kod"]: k for k in govde["kpiler"]}
    assert govde["gun"] == 30
    assert kpi["rapor_tekrar_ariza_onayli"]["deger"] == 1
    assert govde["onayli_oran"] == 100.0
    assert govde["satirlar"][0]["sonraki_isler"] == [ortam[1]["yeni"].so_no]
    # 7 günlük pencerede (yeni iş 18 gün sonra) onaylı tekrar yok; Servis
    # İşleri ekranı özel pencereyi taşıyamaz → yol yok, liste rapordan.
    r = await client.get(f"{R}/tekrar-ariza", params={**DONEM, "tekrar_gun": 7})
    kpi = {k["kod"]: k for k in r.json()["kpiler"]}
    assert kpi["rapor_tekrar_ariza_onayli"]["deger"] == 0
    assert kpi["rapor_tekrar_ariza_onayli"]["isler_yolu"] is None
    r = await client.get(
        f"{R}/kpi-liste", params={**DONEM, "tekrar_gun": 7, "kpi": "rapor_tekrar_ariza_onayli"}
    )
    assert r.headers["X-Toplam-Kayit"] == "0"


async def test_tarih_esasi_plan_ve_atolye_iptali(client, ortam):
    await giris(client, "mudur")
    r = await client.get(f"{R}/kirilim", params={**DONEM, "tarih_esasi": "PLAN", "boyut": "birim"})
    assert r.status_code == 200, r.text
    assert r.json()["toplam"] == 1  # yalnız 05.03 planlı iş (Şubat'ta açılmış)
    r = await client.get(f"{R}/ozet", params=DONEM)
    govde = r.json()
    degerler = {k["kod"]: k["deger"] for k in govde["kpiler"]}
    assert degerler["rapor_iptal"] == 1
    # Dönem sonu açık: yeni (talep) + planlı; iptal atölye işi DEĞİL.
    assert degerler["rapor_donem_sonu_acik"] == 2
    r = await client.get(
        f"{R}/kpi-liste", params={**DONEM, "kpi": "rapor_donem_sonu_acik", "limit": 50}
    )
    assert ortam[1]["atolye_iptal"].so_no not in {s["so_no"] for s in r.json()}


async def test_panel_rapor_kpilerini_kutu_cizmez_ve_aralik_donemi(client, ortam):
    await giris(client, "mudur")
    r = await client.get("/api/teknik-servis/panel")
    assert r.status_code == 200, r.text
    assert not [k for k in r.json()["kutular"] if k["kod"].startswith("rapor_")]
    # Servis İşleri listesi rapor aralığını tanır; ters aralık 400.
    r = await client.get(
        "/api/teknik-servis/isler", params={"kpi": "rapor_gelen", "donem": "20260301-20260331"}
    )
    assert r.status_code == 200 and r.headers["X-Toplam-Kayit"] == "3"
    r = await client.get(
        "/api/teknik-servis/isler", params={"kpi": "rapor_gelen", "donem": "20260331-20260301"}
    )
    assert r.status_code == 400


async def test_trend_on_iki_ay(client, ortam):
    await giris(client, "mudur")
    r = await client.get(f"{R}/trend", params=DONEM)
    assert r.status_code == 200, r.text
    satirlar = r.json()["satirlar"]
    assert len(satirlar) == 12
    assert satirlar[-1]["ay"] == "2026-03" and satirlar[0]["ay"] == "2025-04"
    mart = satirlar[-1]
    assert mart["gelen"] == 3 and mart["cozulen"] == 1 and mart["iptal"] == 1
    assert mart["kisi_saat"] is None  # süre kaydı yok → "—", 0 değil
    subat = satirlar[-2]
    assert subat["gelen"] == 1 and subat["donem_sonu_acik"] == 1
