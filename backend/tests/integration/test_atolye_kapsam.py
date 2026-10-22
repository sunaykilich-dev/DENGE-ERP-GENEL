"""Atölye kapsam ve yetki (TS-091; E05-19, E05-26).

"İki birimden iki şef" kalıbı: GUVENLIK şefi HABERLESME biriminin atölye
kaydını ne listede ne sayıda ne tek kayıtta ne PDF'te ne de ekte görebilir;
yazma denemesi 404 döner ve kayıt DEĞİŞMEZ (`db.refresh` ile sınanır).
"""

import pytest
from atolye_yardimci import ONEK, kabul_et, sef
from servis_yardimci import giris, musteri, teknisyen
from sqlalchemy import func, select

from app.models import AuditLog, WorkshopRecord

pytestmark = pytest.mark.integration


async def _kur(client, db, birimli_kullanici_ac):
    await sef(birimli_kullanici_ac, "hab_sef")
    await sef(birimli_kullanici_ac, "guv_sef", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "hab_sef")
    return await kabul_et(client, hesap.id)


async def test_baska_birim_sefi_hicbir_sey_goremez_ve_degistiremez(
    client, db, birimli_kullanici_ac
) -> None:
    d = await _kur(client, db, birimli_kullanici_ac)
    so_id = d["so_id"]
    kayit = await db.scalar(select(WorkshopRecord).where(WorkshopRecord.service_order_id == so_id))
    once = (kayit.version, kayit.notes, kayit.status)
    await giris(client, "guv_sef")
    denetim_once = await db.scalar(select(func.count()).select_from(AuditLog))
    r = await client.get(ONEK)
    assert r.status_code == 200 and r.json() == [] and r.headers["X-Toplam-Kayit"] == "0"
    ozet = {k["kod"]: k["deger"] for k in (await client.get(f"{ONEK}/ozet")).json()}
    assert ozet["ACIK"] == 0
    for yol in ("", "/kabul-fisi.pdf", "/teslim-tutanagi.pdf"):
        assert (await client.get(f"{ONEK}/{so_id}{yol}")).status_code == 404
    r = await client.patch(f"{ONEK}/{so_id}", json={"version": kayit.version, "notes": "sızma"})
    assert r.status_code == 404
    r = await client.post(f"{ONEK}/{so_id}/durum", json={"hedef": "TESHISTE"})
    assert r.status_code == 404
    r = await client.put(f"{ONEK}/{so_id}/aksesuarlar", json={"version": 1, "aksesuarlar": []})
    assert r.status_code == 404
    r = await client.get(f"/api/ekler/service_orders/{so_id}")
    assert r.status_code == 404
    gecmis = (await client.get(f"{ONEK}/seri-gecmisi", params={"marka": "HYTERA", "seri": "SN-0001"})).json()
    assert gecmis["kayitlar"] == []
    await db.refresh(kayit)
    assert (kayit.version, kayit.notes, kayit.status) == once
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == denetim_once


async def test_kendi_birimi_disina_kabul_404(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac, "guv_sef2", ["GUVENLIK"])
    hesap = await musteri(db)
    await giris(client, "guv_sef2")
    from atolye_yardimci import kabul_govdesi

    r = await client.post(ONEK, json=kabul_govdesi(hesap.id, birim="HABERLESME"))
    assert r.status_code == 404
    assert await db.scalar(select(func.count()).select_from(WorkshopRecord)) == 0


async def test_birimsiz_sef_fail_closed(client, db, birimli_kullanici_ac) -> None:
    await _kur(client, db, birimli_kullanici_ac)
    await birimli_kullanici_ac("bos_sef", "SERVIS_SEF", [])
    await giris(client, "bos_sef")
    r = await client.get(ONEK)
    assert r.json() == []


async def test_rbac_atolye_gor_olmayan_403(client, db, birimli_kullanici_ac) -> None:
    d = await _kur(client, db, birimli_kullanici_ac)
    # Teknisyen atölye ekranını değil, servis işini görür (atolye.gor yok).
    await teknisyen(birimli_kullanici_ac, "hab_tek", ["HABERLESME"])
    await giris(client, "hab_tek")
    assert (await client.get(ONEK)).status_code == 403
    assert (await client.get(f"{ONEK}/{d['so_id']}")).status_code == 403
    # YONETIM yalnız okur (atolye.gor otomatik), yazamaz.
    await birimli_kullanici_ac("yon", "YONETIM", [])
    await giris(client, "yon")
    assert (await client.get(ONEK)).status_code == 200
    r = await client.post(f"{ONEK}/{d['so_id']}/durum", json={"hedef": "TESHISTE"})
    assert r.status_code == 403
    # Atama `servis.planla` da ister: atolye.yaz'ı olup planla'sı olmayan 403.
    r = await client.post(f"{ONEK}/toplu-ata", json={"so_idler": [d["so_id"]], "atamalar": []})
    assert r.status_code == 403
    # Excel: servis_rapor.disaaktar olmayan ATOLYE rolü 403, şef 200.
    await birimli_kullanici_ac("hab_usta", "ATOLYE", ["HABERLESME"])
    await giris(client, "hab_usta")
    assert (await client.get(f"{ONEK}/disaaktar")).status_code == 403
    assert (await client.get(ONEK)).status_code == 200


async def test_toplu_atamada_kapsam_disi_kayit_404_hicbiri_degismez(
    client, db, birimli_kullanici_ac
) -> None:
    d = await _kur(client, db, birimli_kullanici_ac)
    await birimli_kullanici_ac("guv_usta", "ATOLYE", ["GUVENLIK"])
    tek = await teknisyen(birimli_kullanici_ac, "guv_tek", ["GUVENLIK"])
    await giris(client, "guv_usta")
    r = await client.post(
        f"{ONEK}/toplu-ata",
        json={"so_idler": [d["so_id"]], "atamalar": [{"user_id": tek.id, "is_lead": True}]},
    )
    assert r.status_code == 404
    await giris(client, "hab_sef")
    assert (await client.get(f"{ONEK}/{d['so_id']}")).json()["ekip"] == []
