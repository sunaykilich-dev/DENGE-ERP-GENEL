"""Saha işinde ulaşım ve araç km (KARARLAR 2026-11-20 §1).

- GÜVENLİK saha işi ulaşım girilmeden İŞLEMDE'ye alınamaz (400).
- Şirket aracında plaka + başlangıç km zorunlu; plaka araç havuzundan seçilir,
  plan aracı varsayılan olarak alınır.
- Yerinde tamamlamada son km zorunlu, başlangıçtan küçük olamaz; son km aracın
  son km'si olur.
- Toplu ulaşımda (uçak/metro) km istenmez; atölye işi ve diğer birimler kapsam dışı.
- Uzaktan çözümde yol yok: km istenmez.
"""

from __future__ import annotations

import pytest
from servis_yardimci import giris

from app.models.servis_planlama import ServiceVehicle

pytestmark = [pytest.mark.integration, pytest.mark.saha_ulasim]

ONEK = "/api/teknik-servis/isler"
SONUC = {
    "sonuc": "COZULDU",
    "cozum_kanali": "YERINDE",
    "yapilan_islem": "Kart değiştirildi",
    "sure_eksik_onay": True,
}


async def _arac(db, plaka: str = "34 ABC 123", son_km: int | None = 1000) -> ServiceVehicle:
    a = ServiceVehicle(plate=plaka, birim="GUVENLIK", son_km=son_km)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def test_sirket_araci_km_zorunlu(client, db, kullanici_ac, servis_isi_ac) -> None:
    await kullanici_ac("ulasim_m", "SERVIS_YONETICI")
    arac = await _arac(db)
    so = await servis_isi_ac(birim="GUVENLIK", durum="SAHADA")
    await giris(client, "ulasim_m")

    r = await client.post(f"{ONEK}/{so.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 400 and "ulaşım" in r.json()["detail"], r.text

    r = await client.get(f"{ONEK}/{so.id}/ulasim")
    assert r.status_code == 200 and r.json()["zorunlu"] is True

    # Plaka seçilmeden şirket aracı olmaz.
    r = await client.put(f"{ONEK}/{so.id}/ulasim", json={"ulasim_turu": "SIRKET_ARACI"})
    assert r.status_code == 400, r.text
    r = await client.put(
        f"{ONEK}/{so.id}/ulasim",
        json={"ulasim_turu": "SIRKET_ARACI", "servis_arac_id": arac.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["oneri_baslangic_km"] == 1000
    r = await client.post(f"{ONEK}/{so.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 400 and "km" in r.json()["detail"], r.text

    r = await client.put(
        f"{ONEK}/{so.id}/ulasim",
        json={"ulasim_turu": "SIRKET_ARACI", "servis_arac_id": arac.id, "baslangic_km": 1000},
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{ONEK}/{so.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 200, r.text

    # Son km girilmeden yerinde tamamlanmaz.
    r = await client.post(f"{ONEK}/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 400 and "son km" in r.json()["detail"], r.text
    r = await client.put(
        f"{ONEK}/{so.id}/ulasim",
        json={
            "ulasim_turu": "SIRKET_ARACI",
            "servis_arac_id": arac.id,
            "baslangic_km": 1000,
            "bitis_km": 990,
        },
    )
    assert r.status_code == 400, r.text
    r = await client.put(
        f"{ONEK}/{so.id}/ulasim",
        json={
            "ulasim_turu": "SIRKET_ARACI",
            "servis_arac_id": arac.id,
            "baslangic_km": 1000,
            "bitis_km": 1085,
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{ONEK}/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    await db.refresh(arac)
    assert arac.son_km == 1085

    # Tamamlanmış işin ulaşımı değişmez.
    r = await client.put(f"{ONEK}/{so.id}/ulasim", json={"ulasim_turu": "UCAK"})
    assert r.status_code == 409


async def test_toplu_ulasimda_km_istenmez(client, db, kullanici_ac, servis_isi_ac) -> None:
    await kullanici_ac("ulasim_m2", "SERVIS_YONETICI")
    so = await servis_isi_ac(birim="HABERLESME", durum="SAHADA", seri=None,
                             frekans={"frekans": "150.000"})  # fmt: skip
    await giris(client, "ulasim_m2")
    r = await client.put(
        f"{ONEK}/{so.id}/ulasim", json={"ulasim_turu": "UCAK", "baslangic_km": 5}
    )
    assert r.status_code == 200, r.text
    assert r.json()["baslangic_km"] is None  # toplu ulaşımda km tutulmaz
    r = await client.post(f"{ONEK}/{so.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 200, r.text


async def test_kapsam_disi_birim_ve_uzaktan_cozum(
    client, db, kullanici_ac, servis_isi_ac
) -> None:
    await kullanici_ac("ulasim_m3", "SERVIS_YONETICI")
    mob = await servis_isi_ac(birim="BARIYER", durum="SAHADA")
    guv = await servis_isi_ac(birim="GUVENLIK", durum="SAHADA")
    await giris(client, "ulasim_m3")
    r = await client.post(f"{ONEK}/{mob.id}/durum", json={"hedef": "ISLEMDE"})
    assert r.status_code == 200, r.text
    # Uzaktan çözüm: ulaşım girilmeden tamamlanır.
    r = await client.post(
        f"{ONEK}/{guv.id}/sonuc", json={**SONUC, "cozum_kanali": "UZAKTAN"}
    )
    assert r.status_code == 200, r.text
