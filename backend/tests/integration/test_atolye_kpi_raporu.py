"""Atölye KPI raporu, dış servis takibi ve atölye uyarıları (TS-194, E05-09/24/28).

Kurallar:
- çevrim = `completed_at − received_at` (tahmini bitiş kullanılmaz);
- dış servis süresi çevrimden AYRI; "dış servis hariç çevrim" ayrıca;
- süre kaydı yoksa kayıt "süre kaydı eksik" sayısında, işçilik ortalamasına girmez;
- her sayılabilir KPI'nın `sorgu`'su listeye gider ve `X-Toplam-Kayit` = değer;
- teslim alınmayan cihaz uyarısı eşik + 1 günde düşer; başka birim görmez.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from atolye_yardimci import ONEK, duzelt, gec, kabul_et, sef, teshis_et, teslime_hazirla
from openpyxl import load_workbook
from servis_yardimci import giris, musteri
from sqlalchemy import select

from app.models import Account, AuditLog, ServiceTimeEntry, User

pytestmark = pytest.mark.integration

RAPOR = f"{ONEK}/raporlar/kpi"


def _parametre(sorgu: dict) -> dict:
    return {k: v for k, v in sorgu.items() if v not in (None, False)}


async def _sure_ekle(db, so_id: int, user_id: int, dk: int) -> None:
    bas = datetime(2026, 1, 1, 10, tzinfo=UTC)
    db.add(
        ServiceTimeEntry(
            service_order_id=so_id,
            user_id=user_id,
            faaliyet="ATOLYE",
            started_at=bas,
            ended_at=bas + timedelta(minutes=dk),
            kaynak="CANLI",
            girildi_at=bas,
        )
    )
    await db.commit()


async def _iki_kayit(client, db, birimli_kullanici_ac):
    """K-1: 2 günde teslime hazır, 60 dk süre kaydı. K-2: dış servise gitmiş
    (4 gün), toplam çevrim 4 gün, süre kaydı yok."""
    sef_u = await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    tedarikci = Account(title="Üretici Servis A.Ş.", is_tedarikci=True)
    db.add(tedarikci)
    await db.commit()
    await giris(client, "atl_sef")
    k1 = await kabul_et(client, hesap.id, "K-1", estimated_finish_date="2026-01-02")
    client.clock.advance(days=2)
    await giris(client, "atl_sef")
    await teslime_hazirla(client, db, k1["so_id"])
    k2 = await kabul_et(client, hesap.id, "K-2")
    await teshis_et(client, db, k2["so_id"])
    await gec(client, k2["so_id"], "ONARIMDA")
    await duzelt(
        client,
        k2["so_id"],
        repair_category="PARCA_DEGISIMI",
        external_vendor_id=tedarikci.id,
        external_sent_at="2026-01-03",
        external_rma_no="RMA-77",
    )
    await gec(client, k2["so_id"], "DIS_SERVISTE")
    client.clock.advance(days=4)
    await giris(client, "atl_sef")
    await duzelt(client, k2["so_id"], external_returned_at="2026-01-07")
    await gec(client, k2["so_id"], "TEST_KONTROL")
    await duzelt(client, k2["so_id"], test_result="GECTI")
    await gec(client, k2["so_id"], "TESLIME_HAZIR")
    await _sure_ekle(db, k1["so_id"], sef_u.id, 60)
    return k1, k2, tedarikci


async def test_kpi_raporu_cevrim_dis_servis_sure_eksik_ve_sayi_liste(
    client, db, birimli_kullanici_ac
) -> None:
    _, _, tedarikci = await _iki_kayit(client, db, birimli_kullanici_ac)
    r = await client.get(RAPOR, params={"bas": "2026-01-01", "bit": "2026-01-31"})
    assert r.status_code == 200, r.text
    rapor = r.json()
    k = {x["kod"]: x for x in rapor["kutular"]}
    assert k["TAMAMLANAN"]["deger"] == 2
    assert Decimal(k["CEVRIM_ORT"]["deger"]) == Decimal("3.0")
    assert Decimal(k["CEVRIM_MEDYAN"]["deger"]) == Decimal("3.0")
    assert Decimal(k["CEVRIM_DIS_HARIC"]["deger"]) == Decimal("2.0")
    assert k["DIS_SERVIS"]["deger"] == 1
    assert Decimal(k["DIS_SERVIS_SURE"]["deger"]) == Decimal("4.0")
    assert k["SURE_EKSIK"]["deger"] == 1
    assert Decimal(k["ISCILIK_ORT"]["deger"]) == Decimal("60")
    assert k["DIS_SERVISTE"]["deger"] == 0
    # Sayı = liste: her sayılabilir kutunun süzgeci listeye gider.
    for kutu in rapor["kutular"]:
        if kutu["sorgu"] is None:
            continue
        liste = await client.get(ONEK, params=_parametre(kutu["sorgu"]))
        assert liste.status_code == 200, (kutu["kod"], liste.text)
        assert int(liste.headers["X-Toplam-Kayit"]) == kutu["deger"], kutu["kod"]
    # Kırılım: tek servis türü, aynı sayılar.
    (tur,) = rapor["servis_turu_kirilimi"]
    assert tur["servis_turu"] == "ARIZA_ONARIMI" and tur["adet"] == 2
    # Dış servis firmasına göre süzgeç.
    r = await client.get(ONEK, params={"tedarikci_id": tedarikci.id})
    assert r.headers["X-Toplam-Kayit"] == "1"
    # Dönem dışında tamamlanan sayılmaz.
    r = await client.get(RAPOR, params={"bas": "2026-01-04", "bit": "2026-01-31"})
    assert {x["kod"]: x["deger"] for x in r.json()["kutular"]}["TAMAMLANAN"] == 1


async def test_kpi_raporu_parametre_dogrulama_ve_rbac(
    client, db, birimli_kullanici_ac, kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    await birimli_kullanici_ac("atl_usta", "ATOLYE", ["HABERLESME"])
    await giris(client, "atl_sef")
    r = await client.get(RAPOR, params={"bas": "2026-02-01", "bit": "2026-01-01"})
    assert r.status_code == 400
    r = await client.get(RAPOR, params={"bas": "2023-01-01", "bit": "2026-01-01"})
    assert r.status_code == 400
    assert (await client.get(RAPOR, params={"servis_turu": "YOK"})).status_code == 400
    assert (await client.get(RAPOR)).status_code == 200
    # Atölye ustası `servis_rapor.gor` taşımaz: rapor 403, liste/özet 200.
    await giris(client, "atl_usta")
    assert (await client.get(RAPOR)).status_code == 403
    assert (await client.get(f"{RAPOR}.xlsx")).status_code == 403
    assert (await client.get(f"{ONEK}/ozet")).status_code == 200
    # Mobilite rolü atolye.gor taşımaz.
    await kullanici_ac("satisci_k", "SATIS")
    await giris(client, "satisci_k")
    assert (await client.get(RAPOR)).status_code == 403


async def test_kpi_excel_fiyatsiz_ve_denetimli(client, db, birimli_kullanici_ac) -> None:
    await _iki_kayit(client, db, birimli_kullanici_ac)
    r = await client.get(f"{RAPOR}.xlsx", params={"bas": "2026-01-01", "bit": "2026-01-31"})
    assert r.status_code == 200, r.text
    kitap = load_workbook(BytesIO(r.content))
    assert kitap.sheetnames == ["KPI", "Servis Türü", "Kayıtlar"]
    basliklar = [h.value for h in kitap["Kayıtlar"][1]]
    assert not any("Bedel" in str(b) or "Tutar" in str(b) for b in basliklar)
    kayitlar = list(kitap["Kayıtlar"].iter_rows(min_row=2, values_only=True))
    assert len(kayitlar) == 2 and r.headers["X-Toplam-Kayit"] == "2"
    sure = {s[0][-1:]: s[8] for s in kayitlar}
    assert set(sure.values()) == {"Tam", "Eksik"}
    denetim = await db.scalar(
        select(AuditLog).where(AuditLog.action == "atolye.kpi_disa_aktar").order_by(AuditLog.id)
    )
    assert denetim is not None
    assert denetim.new_value["bas"] == "2026-01-01" and denetim.new_value["satir"] == 2


async def test_teslim_alinmayan_uyarisi_ve_birim_kapsami(
    client, db, birimli_kullanici_ac, kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    await sef(birimli_kullanici_ac, "guv_sef", birimler=("GUVENLIK",))
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    k = await kabul_et(client, hesap.id, "U-1")
    await teslime_hazirla(client, db, k["so_id"])

    async def _adet(kod: str) -> int:
        r = await client.get("/api/raporlar/uyarilar")
        assert r.status_code == 200, r.text
        return next((u["adet"] for u in r.json()["uyarilar"] if u["kod"] == kod), 0)

    client.clock.advance(days=30)

    await giris(client, "atl_sef")
    assert await _adet("atolye.teslim_alinmadi") == 0
    client.clock.advance(days=1, minutes=1)
    await giris(client, "atl_sef")
    assert await _adet("atolye.teslim_alinmadi") == 1
    # Uyarının açtığı liste aynı sayıyı verir; KPI kutusu da.
    r = await client.get(ONEK, params={"teslim_alinmayan": "true"})
    assert r.headers["X-Toplam-Kayit"] == "1"
    kutular = {x["kod"]: x["deger"] for x in (await client.get(f"{ONEK}/ozet")).json()}
    assert kutular["TESLIM_ALINMADI"] == 1
    # Başka birim şefi bu sayıyı görmez; atolye.gor'süz kullanıcıda blok yok.
    await giris(client, "guv_sef")
    assert await _adet("atolye.teslim_alinmadi") == 0
    assert (await client.get(ONEK, params={"teslim_alinmayan": "true"})).headers[
        "X-Toplam-Kayit"
    ] == "0"
    await kullanici_ac("satisci_u", "SATIS")
    await giris(client, "satisci_u")
    r = await client.get("/api/raporlar/uyarilar")
    assert all(not u["kod"].startswith("atolye.") for u in r.json()["uyarilar"])


async def test_kpi_raporu_baska_birimi_saymaz(client, db, birimli_kullanici_ac) -> None:
    await _iki_kayit(client, db, birimli_kullanici_ac)
    await sef(birimli_kullanici_ac, "guv_sef2", birimler=("GUVENLIK",))
    await giris(client, "guv_sef2")
    r = await client.get(RAPOR, params={"bas": "2026-01-01", "bit": "2026-01-31"})
    k = {x["kod"]: x["deger"] for x in r.json()["kutular"]}
    assert k["TAMAMLANAN"] == 0 and k["SURE_EKSIK"] == 0 and k["CEVRIM_ORT"] is None
    assert r.json()["servis_turu_kirilimi"] == []
    kullanici = await db.scalar(select(User).where(User.username == "guv_sef2"))
    assert kullanici is not None
