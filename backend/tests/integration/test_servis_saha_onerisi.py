"""Saha önerisi: aynı lokasyonun son planı + tesis kaydı (TS-047, E02-11, E14-16).

Kabul: adres/irtibat yalnız aynı müşteriye aitse; kütük ham adı öneri olmaz;
telefon (ve irtibat, açık adres) yalnız `servis.irtibat_gor` ya da işin
ekibindeyse; kayıt yoksa öneri boş (tahmin yok).
"""

import pytest
from planlama_yardim import ortam_fixture, oturum, plan_govdesi  # noqa: F401

from app.models import Account, Address, Contact

pytestmark = pytest.mark.integration


def _alanlar(yanit) -> dict:
    return {a["alan"]: (a["deger"], a["kaynak"]) for a in yanit.json()["alanlar"]}


async def test_oneri_lokasyon_ve_onceki_plandan(ortam, servis_isi_ac, db) -> None:
    kisi = Contact(
        account_id=ortam.musteri.id,
        full_name="Saha Yetkilisi",
        phone="+905321112233",
        address_id=ortam.lokasyon.id,
    )
    db.add(kisi)
    await db.flush()
    lok = await db.get(Address, ortam.lokasyon.id)
    lok.primary_contact_id = kisi.id
    lok.line = "Örnek Mah. 1. Sok. No:3"
    lok.access_note = "B kapısından giriş"
    await db.commit()

    eski = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    yeni = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef = await ortam.ist("sef_g")
    r = await sef.put(
        f"/api/teknik-servis/planlama/isler/{eski.id}/plan",
        json=plan_govdesi(saha_bolgesi="B Blok 2. kat", saha_notu="Otopark arka tarafta"),
    )
    assert r.status_code == 200, r.text

    r = await sef.get(f"/api/teknik-servis/planlama/isler/{yeni.id}/saha-onerisi")
    assert r.status_code == 200
    alanlar = _alanlar(r)
    assert alanlar["saha_bolgesi"] == ("B Blok 2. kat", "ONCEKI_PLAN")
    assert alanlar["saha_notu"] == ("Otopark arka tarafta", "ONCEKI_PLAN")
    assert alanlar["irtibat_telefon"] == ("+905321112233", "LOKASYON")
    assert alanlar["acik_adres"][0] == "Örnek Mah. 1. Sok. No:3"
    assert alanlar["il"][0] == "İstanbul"


async def test_irtibat_gor_izni_yoksa_telefon_ve_ad_yok(
    ortam, servis_isi_ac, db, rol_ac, kullanici_ac
) -> None:
    kisi = Contact(account_id=ortam.musteri.id, full_name="Gizli Kişi", phone="+905329998877")
    db.add(kisi)
    await db.flush()
    lok = await db.get(Address, ortam.lokasyon.id)
    lok.primary_contact_id = kisi.id
    await db.commit()
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    await rol_ac("T_PLANCI", ["servis.gor", "servis.planla"], "TUMU")
    await kullanici_ac("planci", "T_PLANCI")
    ist = await oturum("planci")
    try:
        r = await ist.get(f"/api/teknik-servis/planlama/isler/{so.id}/saha-onerisi")
    finally:
        await ist.aclose()
    assert r.status_code == 200
    alanlar = _alanlar(r)
    assert "irtibat_telefon" not in alanlar and "irtibat_adi" not in alanlar
    assert "acik_adres" not in alanlar
    assert "Gizli Kişi" not in r.text and "+905329998877" not in r.text
    assert alanlar["il"][0] == "İstanbul"  # il/ilçe görünür kalır


async def test_baska_musterinin_irtibati_onerilmez_kayit_yoksa_bos(
    ortam, servis_isi_ac, db
) -> None:
    yabanci = Account(title="Yabancı Firma", is_musteri=True)
    db.add(yabanci)
    await db.flush()
    kisi = Contact(account_id=yabanci.id, full_name="Yabancı Kişi", phone="+905320000000")
    db.add(kisi)
    await db.flush()
    lok = await db.get(Address, ortam.lokasyon.id)
    lok.primary_contact_id = kisi.id
    await db.commit()
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef = await ortam.ist("sef_g")
    r = await sef.get(f"/api/teknik-servis/planlama/isler/{so.id}/saha-onerisi")
    assert "Yabancı Kişi" not in r.text
    assert "saha_bolgesi" not in _alanlar(r)

    lokasyonsuz = await servis_isi_ac(musteri=ortam.musteri)
    r = await sef.get(f"/api/teknik-servis/planlama/isler/{lokasyonsuz.id}/saha-onerisi")
    assert r.status_code == 200 and r.json()["alanlar"] == []
    op = await ortam.ist("operasyon")  # servis.planla yok
    r = await op.get(f"/api/teknik-servis/planlama/isler/{so.id}/saha-onerisi")
    assert r.status_code == 403
