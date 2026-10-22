"""Atölye kişisel verilerinin KVKK kapsamı (TS-101; E05-D03).

Teslim alan ve onaylayan adı: kayıtta durur, olay geçmişine YAZILMAZ (olay
satırı silinemez), denetime `is_personal_data=True` ayrı satırla gider; hesap
anonimleştirilince kayıttan silinir ve denetim değerleri maskelenir.
"""

import pytest
from atolye_yardimci import (
    atolye_olaylari,
    detay,
    gec,
    kabul_et,
    sef,
    teslim_govdesi,
    teslime_hazirla,
)
from servis_yardimci import giris, musteri
from sqlalchemy import select

from app.models import AuditLog, WorkshopRecord
from app.services import kvkk
from app.services.teknik_servis import atolye, gecmis

pytestmark = pytest.mark.integration


async def test_anonimlestirme_teslim_alan_ve_onaylayani_temizler(
    client, db, birimli_kullanici_ac
) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so_id = d["so_id"]
    await teslime_hazirla(client, db, so_id)  # approved_by_name = "Onaylayan Kişi"
    dd = await detay(client, so_id)
    await gec(client, so_id, "TESLIM_EDILDI", teslim=teslim_govdesi(dd), sure_eksik_onay=True)
    for o in await atolye_olaylari(db, so_id):
        metin = (o.ozet + str(o.veri)).casefold()
        assert "onaylayan kişi" not in metin and "teslim alan kişi" not in metin
    kisisel = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.entity == "workshop_records", AuditLog.is_personal_data.is_(True)
            )
        )
    ).all()
    assert kisisel and any("Teslim Alan Kişi" in str(a.new_value) for a in kisisel)
    bulunan = await kvkk.veri_bul(db, "Teslim Alan")
    assert bulunan["atolye_kayitlari"]

    sonuc = await kvkk.hesabi_anonimlestir(
        db, hesap.id, clock=client.clock, gerekce="KVKK silme talebi #12"
    )
    await db.commit()
    assert sonuc["atolye_kisisel"] == 1
    kayit = await db.scalar(
        select(WorkshopRecord)
        .where(WorkshopRecord.service_order_id == so_id)
        .execution_options(populate_existing=True)
    )
    # Teslim edilmiş kayıtta ad zorunlu (ck_atolye_teslim): işaretle değiştirilir.
    assert kayit.delivered_to_name == kvkk.ANONIM_ISARETI and kayit.approved_by_name is None
    for a in (
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.entity == "workshop_records", AuditLog.is_personal_data.is_(True))
            .execution_options(populate_existing=True)
        )
    ).all():
        assert a.new_value == kvkk.DEGER_SILINDI


async def test_olay_yazici_kisisel_anahtari_reddeder(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    d = await kabul_et(client, hesap.id)
    so, kayit = await atolye.kapsamli_kayit(db, await _kullanici(db, "atl_sef"), d["so_id"])
    with pytest.raises(gecmis.KisiselVeriHatasi):
        await atolye.olay_yaz(
            db, so, kayit, "NOT", "x", user=None, clock=client.clock,
            veri={"delivered_to_name": "Ali Veli"},
        )  # fmt: skip
    await db.rollback()


async def _kullanici(db, ad: str):
    from app.models import User

    return await db.scalar(select(User).where(User.username == ad))
