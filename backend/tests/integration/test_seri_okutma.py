"""Servis işinde seri okutma zorunluluğu (2026-11-23 sahip kararı, `seri_okutma`).

- Cihazlı işte (arıza, bakım, kurulum, atölye) açılışta en az bir seri ve her
  serinin kaynağı: OKUTMA ya da ELLE + sabit listeden neden (DIGER'de açıklama).
- Kapanışta (sonuçla TAMAMLANDI) cihaz serisi okutulur; açılıştakinden farklıysa
  engellenmez, uyarı + geçmiş notu.
- Cihazsız türler, ayar kapalıyken, telefon/uzaktan kanalda kapanış ve Excel içe
  aktarma profili kural dışıdır.
"""

import io
from types import SimpleNamespace

import pytest
from atolye_yardimci import ONEK as ATOLYE
from atolye_yardimci import kabul_govdesi
from atolye_yardimci import sef as atolye_sefi
from openpyxl import Workbook
from servis_yardimci import acilis, giris, musteri, teknisyen
from sqlalchemy import select

from app.models import (
    Account,
    ServiceOrder,
    ServiceOrderEvent,
    ServiceOrderSerial,
    ServiceResult,
)
from app.services import settings as ayar_svc

pytestmark = [pytest.mark.integration, pytest.mark.seri_okutma]

IS = "/api/teknik-servis/isler"
OKUTULDU = {"seri_no": "SN-100", "okuma_kaynagi": "OKUTMA"}
SONUC = {
    "sonuc": "COZULDU",
    "cozum_kanali": "YERINDE",
    "yapilan_islem": "Kart değişti",
    "sure_eksik_onay": True,
}


async def _seri_satiri(db, so_id: int) -> ServiceOrderSerial:
    db.expire_all()
    return await db.scalar(
        select(ServiceOrderSerial).where(ServiceOrderSerial.service_order_id == so_id)
    )


async def test_acilista_seri_ve_kaynak_zorunlu(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("sef_o1", "SERVIS_SEF", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "sef_o1")

    r = await client.post(IS, json=acilis(hesap))
    assert r.status_code == 400 and "seri numarası zorunlu" in r.json()["detail"]
    # Kaynağı bilinmeyen (yalnız metin) seri de yetmez.
    r = await client.post(IS, json=acilis(hesap, seriler=["SN-100"]))
    assert r.status_code == 400 and "okutulmalı" in r.json()["detail"]

    r = await client.post(IS, json=acilis(hesap, seri_okumalari=[OKUTULDU]))
    assert r.status_code == 201, r.text
    d = r.json()
    assert [s["seri_no"] for s in d["seriler"]] == ["SN-100"]
    assert d["seriler"][0]["okuma_kaynagi"] == "OKUTMA"
    assert d["seriler"][0]["okuma_etiketi"] == "Okutuldu"
    assert d["seri_okutma_zorunlu"] is True
    satir = await _seri_satiri(db, d["id"])
    assert satir.okuma_kaynagi == "OKUTMA" and satir.elle_gerekce is None


async def test_elle_giriste_neden_zorunlu(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("sef_o2", "SERVIS_SEF", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "sef_o2")

    elle = {"seri_no": "SN-200", "okuma_kaynagi": "ELLE"}
    r = await client.post(IS, json=acilis(hesap, seri_okumalari=[elle]))
    assert r.status_code == 400 and "neden" in r.json()["detail"]
    r = await client.post(
        IS, json=acilis(hesap, seri_okumalari=[{**elle, "elle_gerekce": "UYDURMA"}])
    )
    assert r.status_code == 422
    r = await client.post(
        IS, json=acilis(hesap, seri_okumalari=[{**elle, "elle_gerekce": "DIGER"}])
    )
    assert r.status_code == 400 and "açıklama" in r.json()["detail"]

    r = await client.post(
        IS, json=acilis(hesap, seri_okumalari=[{**elle, "elle_gerekce": "ETIKET_YOK"}])
    )
    assert r.status_code == 201, r.text
    assert r.json()["seriler"][0]["okuma_etiketi"] == "Elle: Etiket yok / okunmuyor"
    satir = await _seri_satiri(db, r.json()["id"])
    assert (satir.okuma_kaynagi, satir.elle_gerekce) == ("ELLE", "ETIKET_YOK")

    r = await client.post(
        IS,
        json=acilis(
            hesap,
            tur="KURULUM",
            seri_okumalari=[
                {
                    **elle,
                    "seri_no": "K-1",
                    "elle_gerekce": "DIGER",
                    "elle_aciklama": "Kutu açılmadı",
                }
            ],
        ),
    )
    assert r.status_code == 201, r.text
    assert r.json()["seriler"][0]["okuma_etiketi"] == "Elle: Kutu açılmadı"


async def test_cihazsiz_turler_ve_kapali_ayar_kural_disi(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("sef_o3", "SERVIS_SEF", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "sef_o3")
    for tur in ("DESTEK", "KESIF", "TOPLAMA", "TASIMA", "DEMONTAJ"):
        r = await client.post(IS, json=acilis(hesap, tur=tur))
        assert r.status_code == 201, (tur, r.text)
        assert r.json()["seri_okutma_zorunlu"] is False

    await ayar_svc.set_many(db, {"servis_seri_okutma_zorunlu": False}, None)
    await db.commit()
    r = await client.post(IS, json=acilis(hesap))
    assert r.status_code == 201, r.text
    r = await client.post(IS, json=acilis(hesap, tur="KURULUM", seriler=["SN-ESKI"]))
    assert r.status_code == 201, r.text
    assert r.json()["seriler"][0]["okuma_kaynagi"] is None
    r = await client.get(f"{IS}/form-verileri")
    assert r.json()["seri_okutma"]["zorunlu"] is False


async def test_telefonla_cozulen_ariza_elle_neden_ile_acilir(
    client, db, birimli_kullanici_ac
) -> None:
    await birimli_kullanici_ac("op_o4", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "op_o4")
    govde = acilis(hesap, cozum_kanali="TELEFON", yapilan_islem="Telefonla yönlendirildi")
    r = await client.post(f"{IS}/uzaktan-cozuldu", json=govde)
    assert r.status_code == 400
    r = await client.post(
        f"{IS}/uzaktan-cozuldu",
        json={
            **govde,
            "seri_okumalari": [
                {"seri_no": "SN-T1", "okuma_kaynagi": "ELLE", "elle_gerekce": "CIHAZ_YANINDA_DEGIL"}
            ],
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    # Telefonla çözümde kapanış okutması istenmez (cihaz yanında değil).
    assert d["status"] == "TAMAMLANDI"
    assert d["seriler"][0]["okuma_etiketi"].startswith("Elle: Cihaz yanımda değil")


async def test_kapanista_okutma_zorunlu_fark_uyarir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "tek_o5")
    a = await servis_isi_ac(durum="SAHADA", atananlar=[tek], seri="SN-100")
    b = await servis_isi_ac(durum="SAHADA", atananlar=[tek], seri="SN-300")
    a, b = SimpleNamespace(id=a.id), SimpleNamespace(id=b.id)  # expire_all sonrası güvenli
    await giris(client, "tek_o5")

    r = await client.post(f"{IS}/{a.id}/sonuc", json=SONUC)
    assert r.status_code == 400 and "okutun" in r.json()["detail"]
    r = await client.post(
        f"{IS}/{a.id}/sonuc",
        json={**SONUC, "kapanis_okuma": {"seri_no": "SN-100", "okuma_kaynagi": "ELLE"}},
    )
    assert r.status_code == 400
    db.expire_all()
    assert (await db.get(ServiceOrder, a.id)).status == "SAHADA"
    sayi = await db.scalar(select(ServiceResult.id).where(ServiceResult.service_order_id == a.id))
    assert sayi is None  # hata yolunda sonuç satırı kalmaz

    # Eski kayıt (kaynağı bilinmeyen açılış serisi) "eski kayıt" olarak kalır.
    r = await client.get(f"{IS}/{a.id}")
    assert r.json()["seriler"][0]["okuma_kaynagi"] is None
    assert r.json()["seriler"][0]["okuma_etiketi"] is None

    r = await client.post(
        f"{IS}/{a.id}/sonuc", json={**SONUC, "kapanis_okuma": {**OKUTULDU, "seri_no": "sn-100"}}
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "TAMAMLANDI"
    assert d["sonuc"]["kapanis_seri_no"] == "sn-100"
    assert d["sonuc"]["kapanis_okuma"]["etiket"] == "Okutuldu"
    assert d["sonuc"]["kapanis_seri_farkli"] is False

    # Farklı seri engellemez: uyarı + geçmiş notu.
    r = await client.post(
        f"{IS}/{b.id}/sonuc",
        json={
            **SONUC,
            "kapanis_okuma": {
                "seri_no": "SN-999",
                "okuma_kaynagi": "ELLE",
                "elle_gerekce": "ETIKET_YOK",
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TAMAMLANDI"
    assert r.json()["sonuc"]["kapanis_seri_farkli"] is True
    assert r.json()["sonuc"]["kapanis_okuma"]["etiket"] == "Elle: Etiket yok / okunmuyor"
    notlar = (
        await db.scalars(
            select(ServiceOrderEvent.ozet).where(
                ServiceOrderEvent.service_order_id == b.id, ServiceOrderEvent.olay_turu == "NOT"
            )
        )
    ).all()
    assert any("SN-999" in n and "farklı" in n for n in notlar)


async def test_kapanis_kural_disi_haller(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "tek_o6")
    uzaktan = await servis_isi_ac(durum="SAHADA", atananlar=[tek])
    destek = await servis_isi_ac(durum="SAHADA", atananlar=[tek], tur="DESTEK")
    gecis = await servis_isi_ac(durum="SAHADA", atananlar=[tek], sla_kaynak="GECIS")
    await giris(client, "tek_o6")
    r = await client.post(f"{IS}/{uzaktan.id}/sonuc", json={**SONUC, "cozum_kanali": "UZAKTAN"})
    assert r.status_code == 200, r.text
    for so in (destek, gecis):
        r = await client.post(f"{IS}/{so.id}/sonuc", json=SONUC)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "TAMAMLANDI"


async def test_kapali_ayarda_kapanis_okutmasi_istenmez(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await ayar_svc.set_many(db, {"servis_seri_okutma_zorunlu": False}, None)
    await db.commit()
    tek = await teknisyen(birimli_kullanici_ac, "tek_o7")
    so = await servis_isi_ac(durum="SAHADA", atananlar=[tek])
    await giris(client, "tek_o7")
    r = await client.post(f"{IS}/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    assert r.json()["seri_okutma_zorunlu"] is False


async def test_bagli_yeni_is_onceki_seriyi_devralir(
    client, db, birimli_kullanici_ac, servis_isi_ac, lokasyon_ac
) -> None:
    await birimli_kullanici_ac("sef_o8", "SERVIS_SEF", ["GUVENLIK"])
    lok = await lokasyon_ac()
    hesap = await db.get(Account, lok.account_id)
    so = await servis_isi_ac(
        musteri=hesap,
        lokasyon=lok,
        durum="KAPATILDI",
        iletisim_ad="Saha Yetkilisi",
        iletisim_telefon="+905321112233",
        talep_kanali="TELEFON",
        seri="CIHAZ-8",
    )
    await giris(client, "sef_o8")
    # Önceki işin serisi devralınır (yeniden okutma istenmez).
    r = await client.post(f"{IS}/{so.id}/bagli-yeni-is", json={"konu": "Arıza tekrarladı"})
    assert r.status_code == 201, r.text
    assert [s["seri_no"] for s in r.json()["seriler"]] == ["CIHAZ-8"]

    # Yeni (önceki işte olmayan) seri okutulmalı.
    r = await client.post(
        f"{IS}/{so.id}/bagli-yeni-is", json={"konu": "Başka", "seriler": ["YENI-1"]}
    )
    assert r.status_code == 400
    r = await client.post(
        f"{IS}/{so.id}/bagli-yeni-is",
        json={
            "konu": "Başka cihaz",
            "seriler": [],
            "seri_okumalari": [{"seri_no": "YENI-1", "okuma_kaynagi": "OKUTMA"}],
            "mukerrer_gec": True,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["seriler"][0]["okuma_kaynagi"] == "OKUTMA"


async def test_atolye_kabulunde_kaynak_zorunlu(client, db, birimli_kullanici_ac) -> None:
    await atolye_sefi(birimli_kullanici_ac, "atl_o9")
    hesap = await musteri(db)
    await giris(client, "atl_o9")
    r = await client.post(ATOLYE, json=kabul_govdesi(hesap.id, "SN-A1"))
    assert r.status_code == 400 and "okutulmalı" in r.json()["detail"]
    r = await client.post(
        ATOLYE, json=kabul_govdesi(hesap.id, "SN-A1", ekipman={"okuma_kaynagi": "OKUTMA"})
    )
    assert r.status_code == 201, r.text
    satir = await _seri_satiri(db, r.json()["so_id"])
    assert satir.seri_no == "SN-A1" and satir.okuma_kaynagi == "OKUTMA"


def _xlsx(satirlar: list[list]) -> bytes:
    wb = Workbook()
    for s in satirlar:
        wb.active.append(s)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def test_excel_ice_aktarma_kural_disi(client, db, kullanici_ac) -> None:
    db.add(Account(title="OKUTMA TEST A.Ş.", title_key="okutma test a.s.", is_musteri=True))
    await db.commit()
    await kullanici_ac("yonetici_o10", "ADMIN")
    await giris(client, "yonetici_o10")
    icerik = _xlsx(
        [
            ["Birim", "Tür", "Talep Tarihi", "Müşteri / Firma", "Lokasyon", "Talep Detayı",
             "Durum", "Personel"],
            ["GUVENLIK", "ARIZA", "01.10.2026", "OKUTMA TEST", "ANKARA", "SERİSİZ ARIZA",
             "TAMAMLANDI", ""],
            ["GUVENLIK", "KURULUM", "", "OKUTMA TEST", "ANKARA", "SERİSİZ KURULUM",
             "BEKLEMEDE", ""],
        ]
    )  # fmt: skip
    r = await client.post(
        "/api/ice-aktarma/servis_talep",
        files={
            "file": (
                "t.xlsx",
                icerik,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 201, r.text
    parti_id = r.json()["parti"]["id"]
    u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
    assert u.status_code == 200, u.text
    assert u.json()["sonuc"]["eklendi"] == 2
