"""Saha / Zaman Takibi yönetim ekranı ve veri disiplini sütunları (TS-189, E09-14/15).

Kilitlenen riskler:
- **Sayı = liste:** her KPI kutusunun adedi açılan listenin `X-Toplam-Kayit`,
  dakikası `X-Toplam-Dakika` başlığıyla AYNI sorgudan gelir (parametrik).
- **Eksik ≠ 0:** kaydı olmayan kişide kişi-saat ve canlı oranı BOŞ ("%0" değil).
- **Kişi sütunları** (`user_id`, kişi adı, personel dağılımı, Excel "Personel"
  sayfası) `servis_rapor.personel` olmadan ANAHTAR olarak yok (TS-182).
- **Kapsam:** A birimi şefi B biriminin sayaçlarını, kayıtlarını ve sayılarını
  görmez; yetkisiz birim parametresi 403.
- Mobilite `rapor.gor` değil `servis_rapor.gor` (KD-06): teknisyen 403.
"""

import io
from datetime import timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from zaman_ortam import SABAH, TS, dk, giris, ortam_kur

from app.models import AuditLog, ServiceTimeEntry

pytestmark = pytest.mark.integration

Z = f"{TS}/zaman"
SAAT = timedelta(hours=1)


@pytest.fixture
async def o(client, db, birimli_kullanici_ac):
    client.clock.set(SABAH)
    return await ortam_kur(db, birimli_kullanici_ac)


async def _bolum(db, so, kisi, faaliyet, bas, bit=None, *, kaynak=None, girildi=None, **kw):
    b = ServiceTimeEntry(
        service_order_id=so.id,
        user_id=kisi.id,
        faaliyet=faaliyet,
        started_at=bas,
        ended_at=bit,
        kaynak=kaynak or ("CANLI" if bit is None else "MANUEL"),
        kapanis_turu=kw.pop("kapanis_turu", "BITIR" if (bit and kaynak == "CANLI") else None),
        girildi_at=girildi or bit or bas,
        created_by=kisi.id,
        **kw,
    )
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return b


async def _veri(db, o, servis_isi_ac):
    """GUVENLIK: tek (3 CANLI 120 dk + 1 MANUEL 60 dk + MOLA 15 + geri alınan),
    tek2 (gecikmeli MANUEL 60 + düzeltilmiş 60 + iptal), şef açık uzun sayaç;
    tamamlanmış süresiz iş. HABERLESME: kapsam dışı bölüm."""
    so_a = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    so_b = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek2])
    so_c = await servis_isi_ac(durum="SAHADA", atananlar=[o.sef])
    so_d = await servis_isi_ac(durum="TAMAMLANDI", atananlar=[o.tek], completed_at=SABAH - SAAT)
    so_h = await servis_isi_ac(birim="HABERLESME", durum="SAHADA", atananlar=[o.sef_b])
    t = SABAH
    await _bolum(db, so_a, o.tek, "SAHA", t - 6 * SAAT, t - 6 * SAAT + dk(40), kaynak="CANLI")
    await _bolum(db, so_a, o.tek, "SAHA", t - 5 * SAAT, t - 5 * SAAT + dk(40), kaynak="CANLI")
    await _bolum(db, so_a, o.tek, "YOL", t - 4 * SAAT, t - 4 * SAAT + dk(40), kaynak="CANLI")
    await _bolum(db, so_a, o.tek, "SAHA", t - 3 * SAAT, t - 2 * SAAT, kaynak="MANUEL", girildi=t)
    await _bolum(db, so_a, o.tek, "MOLA", t - 2 * SAAT, t - 2 * SAAT + dk(15), kaynak="CANLI")
    await _bolum(
        db,
        so_a,
        o.tek,
        "YOL",
        t - dk(90),
        t - dk(85),
        kaynak="CANLI",
        is_deleted=True,
        iptal_turu="GERI_ALINDI",
    )
    gecikmis = t - timedelta(days=2)
    await _bolum(
        db, so_b, o.tek2, "SAHA", gecikmis - SAAT, gecikmis, kaynak="MANUEL", girildi=t,
        gerekce="Sonradan girildi",
    )  # fmt: skip
    await _bolum(
        db,
        so_b,
        o.tek2,
        "SAHA",
        t - 9 * SAAT,
        t - 8 * SAAT,
        kaynak="KULLANICI_DUZELTMESI",
        kapanis_turu="UNUTULDU",
        gerekce="Unuttum",
    )
    await _bolum(
        db,
        so_b,
        o.tek2,
        "SAHA",
        t - 7 * SAAT,
        t - 6 * SAAT,
        kaynak="MANUEL",
        is_deleted=True,
        iptal_turu="KAYIT_IPTAL",
        iptal_gerekcesi="Yanlış iş",
    )
    await _bolum(db, so_c, o.sef, "SAHA", t - 11 * SAAT, kaynak="CANLI")  # açık, uzun
    await _bolum(db, so_h, o.sef_b, "SAHA", t - 3 * SAAT, t - 2 * SAAT, kaynak="CANLI")
    return so_a, so_b, so_c, so_d, so_h


def _kutular(r) -> dict[str, dict]:
    assert r.status_code == 200, r.text
    return {k["kod"]: k for k in r.json()["kpi"]}


async def test_kpi_sayisi_liste_toplamina_esit(client, db, o, servis_isi_ac) -> None:
    """E09-14 kabul 1: her KPI = açılan listenin toplamı (adet ve dakika)."""
    await _veri(db, o, servis_isi_ac)
    await giris(client, "sef_a")
    k = _kutular(await client.get(f"{Z}/ozet"))
    assert k["kisi_saat"]["deger"] == 300 and k["kisi_saat"]["adet"] == 6
    assert k["mola"]["deger"] == 15  # bilgi; kişi-saate EKLENMEZ
    assert k["yol"]["deger"] == 40 and k["saha"]["deger"] == 260
    assert k["bekleme"]["deger"] is None and k["bekleme"]["adet"] == 0  # eksik ≠ 0
    assert k["aktif_sayac"]["deger"] == 1 and k["uzun_sayac"]["deger"] == 1
    assert k["farkli_is"]["deger"] == 3 and k["sure_eksik"]["deger"] == 1
    assert k["canli_orani"]["deger"] == 40.0
    for kod, kutu in k.items():
        if kutu["liste"] == "kayitlar":
            r = await client.get(f"{Z}/kayitlar", params={"kpi": kod, "limit": 200})
            assert r.status_code == 200, (kod, r.text)
            assert int(r.headers["X-Toplam-Kayit"]) == kutu["adet"] == len(r.json()), kod
            if kutu["birim"] == "dk":
                beklenen = "" if kutu["deger"] is None else str(kutu["deger"])
                assert r.headers["X-Toplam-Dakika"] == beklenen, kod
        elif kutu["liste"] == "isler":
            r = await client.get(f"{Z}/isler", params={"kpi": kod})
            assert r.status_code == 200, (kod, r.text)
            assert int(r.headers["X-Toplam-Kayit"]) == kutu["deger"] == len(r.json()), kod
    # Katalog dışı KPI 422 (sessizce boş liste dönmez).
    assert (await client.get(f"{Z}/kayitlar", params={"kpi": "yok"})).status_code == 422


async def test_personel_dagilimi_ve_disiplin_sutunlari(client, db, o, servis_isi_ac) -> None:
    """E09-15: 3 CANLI (120 dk) + 1 MANUEL (60 dk) → %66,7; gecikmeli manuel,
    düzeltilen, iptal, geri alınan sayılır; dakikasız kişide oran BOŞ."""
    await _veri(db, o, servis_isi_ac)
    await giris(client, "sef_a")
    r = await client.get(f"{Z}/ozet")
    kisiler = {p["user_id"]: p for p in r.json()["personel"]}
    tek = kisiler[o.tek.id]
    assert tek["kisi_saat_dk"] == 180 and tek["canli_orani"] == 66.7
    assert tek["mola_dk"] == 15 and tek["manuel_sayisi"] == 1
    assert tek["geri_alinan_sayisi"] == 1 and tek["gecikmeli_manuel_sayisi"] == 0
    tek2 = kisiler[o.tek2.id]
    assert tek2["gecikmeli_manuel_sayisi"] == 1
    assert tek2["duzeltilen_sayisi"] == 1 and tek2["iptal_sayisi"] == 1
    assert tek2["canli_orani"] == 0.0  # dakikası var, CANLI yok → gerçek %0
    sef = kisiler[o.sef.id]  # yalnız açık sayaç
    assert sef["kisi_saat_dk"] is None and sef["canli_orani"] is None
    assert o.sef_b.id not in kisiler  # kapsam dışı birim
    # Kişi süzgeci aynı uçtan (ayrı uç yok).
    r = await client.get(f"{Z}/ozet", params={"kullanici_id": o.tek.id})
    assert _kutular(r)["kisi_saat"]["deger"] == 180


async def test_varsayilan_aralik_31_gun(client, db, o, servis_isi_ac) -> None:
    """E09-14 kabul 2: parametresiz çağrı son 31 gün; daha eski bölüm yok."""
    so = await servis_isi_ac(durum="SAHADA", atananlar=[o.tek])
    eski = SABAH - timedelta(days=31)
    yeni = SABAH - timedelta(days=30)
    await _bolum(db, so, o.tek, "SAHA", eski, eski + SAAT, kaynak="MANUEL", gerekce="x")
    await _bolum(db, so, o.tek, "SAHA", yeni, yeni + SAAT, kaynak="MANUEL", gerekce="x")
    await giris(client, "sef_a")
    r = await client.get(f"{Z}/kayitlar")
    assert r.headers["X-Toplam-Kayit"] == "1"
    r = await client.get(f"{Z}/kayitlar", params={"bas": "2026-01-01"})
    assert r.headers["X-Toplam-Kayit"] == "2"
    r = await client.get(f"{Z}/ozet", params={"bas": "2026-03-10", "bit": "2026-03-01"})
    assert r.status_code == 400
    r = await client.get(f"{Z}/ozet", params={"bas": "2024-01-01", "bit": "2026-03-01"})
    assert r.status_code == 400  # 366 günden uzun


async def test_birim_kapsami(client, db, o, servis_isi_ac) -> None:
    """E09-14 kabul 3: B birimi şefi A biriminin sayaçlarını/kayıtlarını/sayılarını görmez."""
    *_, so_h = await _veri(db, o, servis_isi_ac)
    await giris(client, "sef_b")
    k = _kutular(await client.get(f"{Z}/ozet"))
    assert k["kisi_saat"]["deger"] == 60 and k["aktif_sayac"]["deger"] == 0
    assert k["farkli_is"]["deger"] == 1 and k["sure_eksik"]["deger"] == 0
    r = await client.get(f"{Z}/aktif")
    assert r.json()["sayaclar"] == []
    r = await client.get(f"{Z}/kayitlar")
    assert r.headers["X-Toplam-Kayit"] == "1"
    assert [s["so_no"] for s in r.json()] == [so_h.so_no]
    # Yetkisiz birim parametresi 403; kapsam dışı kişi süzgeci 404.
    assert (await client.get(f"{Z}/ozet", params={"birim": "GUVENLIK"})).status_code == 403
    r = await client.get(f"{Z}/kayitlar", params={"kullanici_id": o.tek.id})
    assert r.status_code == 404
    assert (await client.get(f"{Z}/ozet", params={"birim": "YOK"})).status_code == 400


async def test_aktif_sayaclar_uzun_isaretli(client, db, o, servis_isi_ac) -> None:
    await _veri(db, o, servis_isi_ac)
    await giris(client, "sef_a")
    r = await client.get(f"{Z}/aktif")
    assert r.status_code == 200
    (sayac,) = r.json()["sayaclar"]
    assert sayac["uzun"] is True and sayac["kisi_adi"] and sayac["gecen_dk"] == 660
    assert sayac["sure_dk"] is None and r.json()["sunucu_zamani"]


async def test_rbac_teknisyen_ve_operasyon_403(client, o) -> None:
    """E09-14 kabul 4: `servis_rapor.gor` olmayan 403 (mobilite `rapor.gor` değil)."""
    for kullanici in ("tek1", "operasyon"):
        await giris(client, kullanici)
        for yol in ("ozet", "aktif", "kayitlar", "kayitlar.xlsx"):
            assert (await client.get(f"{Z}/{yol}")).status_code == 403, (kullanici, yol)
        r = await client.get(f"{Z}/isler", params={"kpi": "farkli_is"})
        assert r.status_code == 403
    await giris(client, "sef_a")
    for yol in ("ozet", "aktif", "kayitlar", "kayitlar.xlsx"):
        assert (await client.get(f"{Z}/{yol}")).status_code == 200, yol


async def test_kisi_alanlari_personel_izni_olmadan_yok(
    client, db, o, servis_isi_ac, birimli_kullanici_ac
) -> None:
    """TS-182 / E09-D03: `servis_rapor.personel` yoksa kişi anahtarları YOK."""
    await _veri(db, o, servis_isi_ac)
    await birimli_kullanici_ac("depo", "SERVIS_DEPO", ["GUVENLIK"])
    await giris(client, "depo")
    r = await client.get(f"{Z}/ozet")
    assert r.status_code == 200 and "personel" not in r.json()
    assert _kutular(r)["kisi_saat"]["deger"] == 300  # toplamlar yine görünür
    r = await client.get(f"{Z}/kayitlar")
    assert r.json() and all("user_id" not in s and "kisi_adi" not in s for s in r.json())
    assert all("konum_notu" not in s and "gerekce" not in s for s in r.json())
    r = await client.get(f"{Z}/aktif")
    assert all("kisi_adi" not in s for s in r.json()["sayaclar"])
    r = await client.get(f"{Z}/kayitlar", params={"kullanici_id": o.tek.id})
    assert r.status_code == 403
    r = await client.get(f"{Z}/kayitlar.xlsx")
    assert r.status_code == 200
    kitap = load_workbook(io.BytesIO(r.content))
    assert kitap.sheetnames == ["Süre Kayıtları", "Özet"]
    basliklar = [h.value for h in kitap["Süre Kayıtları"][1]]
    assert "Personel" not in basliklar
    denetim = await db.scalar(
        select(AuditLog).where(AuditLog.action == "zaman.disa_aktar").order_by(AuditLog.id.desc())
    )
    assert denetim.is_personal_data is False


async def test_excel_ekranla_ayni_ve_bos_hucre(client, db, o, servis_isi_ac) -> None:
    """E09-14 kabul 5: Excel ve ekran aynı satır ve kişi-saat; MOLA ayrı ve
    hariç; açık bölümün süre hücresi BOŞ (0 değil); denetim satırı ISO süzgeçli."""
    await _veri(db, o, servis_isi_ac)
    await giris(client, "sef_a")
    liste = await client.get(f"{Z}/kayitlar", params={"limit": 200})
    r = await client.get(f"{Z}/kayitlar.xlsx")
    assert r.status_code == 200, r.text
    assert r.headers["X-Toplam-Kayit"] == liste.headers["X-Toplam-Kayit"] == "8"
    kitap = load_workbook(io.BytesIO(r.content))
    assert kitap.sheetnames == ["Süre Kayıtları", "Özet", "Personel"]
    kayit = kitap["Süre Kayıtları"]
    basliklar = [h.value for h in kayit[1]]
    sure_i = basliklar.index("Süre (dk)")
    sureler = [s[sure_i].value for s in kayit.iter_rows(min_row=2)]
    assert len(sureler) == 8 and sureler.count(None) == 1  # açık sayaç
    ozet = {s[0].value: s[1].value for s in kitap["Özet"].iter_rows(min_row=2)}
    assert ozet["Kişi-saat (dk)"] == 300 and ozet["Mola (dk, hariç)"] == 15
    personel = {s[0].value: s for s in kitap["Personel"].iter_rows(min_row=2)}
    sef_satiri = personel[o.sef.full_name]
    assert sef_satiri[1].value is None  # kişi-saat boş, 0 değil
    denetim = await db.scalar(
        select(AuditLog).where(AuditLog.action == "zaman.disa_aktar").order_by(AuditLog.id.desc())
    )
    assert denetim.is_personal_data is True
    assert denetim.new_value["bas"] == "2026-02-08" and denetim.new_value["satir"] == 8


async def test_uzun_sayac_uyarisi_zaman_takibine_goturur(client, db, o, servis_isi_ac) -> None:
    from app.services.teknik_servis import uyarilar as ts_uyarilar

    await _veri(db, o, servis_isi_ac)
    uyarilar = {u.kod: u for u in await ts_uyarilar.topla(db, o.sef, client.clock)}
    assert uyarilar["zaman.uzun_sayac"].yol == "/zaman-takibi?kpi=uzun_sayac"
    assert uyarilar["zaman.uzun_sayac"].adet == 1
