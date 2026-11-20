"""Telsiz atölyesinde kargo/teslim öncesi seri okutma (KARARLAR 2026-11-20 §4).

- Okutma olmadan kargoya verilmez (400).
- Yanlış/eksik seri açıklamasız 400; açıklamalı kabul edilir, teslim notuna
  ve uyarıya yazılır.
- Doğru seri (büyük/küçük harf, boşluk farkı önemsiz) açıklama istemez.
"""

import pytest
from atolye_yardimci import detay, gec, kabul_et, sef, teslim_govdesi, teslime_hazirla
from servis_yardimci import giris, musteri
from sqlalchemy import select

from app.models import WorkshopRecord

pytestmark = [pytest.mark.integration, pytest.mark.saha_ulasim]

KARGO = {"teslim_tipi": "KARGO", "kargo_firmasi": "Yurtiçi", "takip_no": "123"}


async def _kayit(db, so_id: int) -> WorkshopRecord:
    db.expire_all()
    return await db.scalar(select(WorkshopRecord).where(WorkshopRecord.service_order_id == so_id))


async def test_kargoda_seri_okutulur_fark_aciklama_ister(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id, seri="SN-7788")
    so_id = d["so_id"]
    await teslime_hazirla(client, db, so_id)

    await gec(client, so_id, "KARGOYA_VERILDI", 400, teslim=KARGO)
    await gec(
        client, so_id, "KARGOYA_VERILDI", 400, teslim={**KARGO, "okutulan_seriler": ["SN-9999"]}
    )
    r = await gec(
        client,
        so_id,
        "KARGOYA_VERILDI",
        teslim={
            **KARGO,
            "okutulan_seriler": ["SN-9999"],
            "seri_aciklama": "Müşteriye yedek cihaz gönderildi",
        },
    )
    assert r.json()["uyarilar"] and "SN-7788" in r.json()["uyarilar"][0]
    kayit = await _kayit(db, so_id)
    assert "yedek cihaz" in (kayit.delivery_note or "")


async def test_dogru_seri_aciklama_istemez(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id, seri="SN-1234")
    so_id = d["so_id"]
    await teslime_hazirla(client, db, so_id)
    dd = await detay(client, so_id)
    r = await gec(
        client,
        so_id,
        "TESLIM_EDILDI",
        teslim={**teslim_govdesi(dd), "okutulan_seriler": [" sn-1234 "]},
        sure_eksik_onay=True,
    )
    assert not r.json()["uyarilar"]
