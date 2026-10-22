"""Servis işi göçü ve uzlaşma (TS-174, TS-176, TS-177).

Örnek dökümle uçtan uca: kütük → servis işleri → plan → zaman, sonra
uzlaşma. Kabul:

- eski numara korunur; müşteri eşleşmezse `customer_id` NULL + ham metin;
- POC durumu çözüm kanalına taşınır, eşlenemeyen durum/tür karantinada ve
  raporda; kanalı bilinmeyen kapalı işe sonuç UYDURULMAZ;
- olay geçmişi kaynak log'dan; atama yalnız onaylı ad eşlemesiyle;
- zaman kaydı: eşleşmeyen ad `user_id NULL + kaynak_personel_adi`, çakışan
  satır `GOC_CAKISMA` olarak saklanır (atılmaz), eski iptal `GOC_IPTAL`;
- her tablo için `kaynak = aktarılan + karantina + reddedilen`;
- ikinci koşu 0 yeni satır.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.migration import servis_uzlasma
from app.migration.servis_kaynak import GOC_SISTEMI, KaynakDizini
from app.models import (
    ServiceEquipment,
    ServiceHold,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServiceOrderSerial,
    ServicePlan,
    ServiceResult,
    ServiceTimeEntry,
    ServiceVisit,
)
from tests.migration.goc_ortami import FIXTURE, goc_ortami

pytestmark = pytest.mark.integration


async def _say(db, model) -> int:
    return int(await db.scalar(select(func.count()).select_from(model)) or 0)


async def _is(db, ref: str) -> ServiceOrder:
    return await db.scalar(
        select(ServiceOrder).where(
            ServiceOrder.source_system == GOC_SISTEMI, ServiceOrder.source_ref == ref
        )
    )


async def _goc(db, **kw):
    kosu = await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), uygula=True, **kw)
    await db.commit()
    return kosu


async def test_uctan_uca_goc_ve_uzlasma(seeded):
    db = seeded
    ort = await goc_ortami(db)
    kosu = await _goc(db)

    assert await _say(db, ServiceEquipment) == 5
    assert await _say(db, ServiceOrder) == 6
    assert await _say(db, ServicePlan) == 4
    assert await _say(db, ServiceVisit) == 1
    assert await _say(db, ServiceTimeEntry) == 5

    kapali = await _is(db, "WorkOrders:101")
    assert kapali.so_no == "SRV-202601-0001"  # eski numara korunur
    assert kapali.status == "KAPATILDI" and kapali.customer_id == ort.akyaka.id
    assert kapali.first_completed_at is not None and kapali.closed_at is not None
    # Yerel 09:30 → 06:30 UTC (aynı an; naif değer UTC sanılsaydı 3 saat kayardı).
    assert kapali.created_at == datetime(2026, 1, 5, 6, 30, tzinfo=UTC)
    ekipman = await db.scalar(
        select(ServiceEquipment.id).where(ServiceEquipment.source_ref == "SecurityDevices:1")
    )
    assert kapali.equipment_id == ekipman
    seriler = (
        await db.scalars(
            select(ServiceOrderSerial.seri_no).where(
                ServiceOrderSerial.service_order_id == kapali.id
            )
        )
    ).all()
    assert sorted(seriler) == ["00123-A", "00123-B"]
    olaylar = (
        await db.scalars(
            select(ServiceOrderEvent)
            .where(ServiceOrderEvent.service_order_id == kapali.id)
            .order_by(ServiceOrderEvent.olusma_zamani, ServiceOrderEvent.id)
        )
    ).all()
    assert [o.olay_turu for o in olaylar] == ["OLUSTUR", "DURUM", "DURUM", "DURUM", "DURUM"]
    assert all("Ali" not in o.ozet for o in olaylar)  # olay geçmişine kişi adı yazılmaz
    # Kanalı bilinmeyen kapalı iş: sonuç uydurulmaz.
    assert (
        await db.scalar(select(ServiceResult.id).where(ServiceResult.service_order_id == kapali.id))
        is None
    )
    atamalar = (
        await db.scalars(
            select(ServiceOrderAssignment).where(
                ServiceOrderAssignment.service_order_id == kapali.id
            )
        )
    ).all()
    assert [(a.user_id, a.is_lead) for a in atamalar] == [(ort.ali.id, True)]

    telefon = await _is(db, "WorkOrders:102")
    sonuc = await db.scalar(
        select(ServiceResult).where(ServiceResult.service_order_id == telefon.id)
    )
    assert telefon.tur == "DESTEK" and sonuc.cozum_kanali == "TELEFON" and sonuc.sonuc == "COZULDU"
    acik_poc = await _is(db, "WorkOrders:103")
    assert acik_poc.status == "ISLEMDE" and acik_poc.customer_id == ort.lojistik.id
    iptal = await _is(db, "WorkOrders:106")
    assert iptal.status == "IPTAL" and iptal.cancel_reason and iptal.cancelled_at
    bekleyen = await _is(db, "WorkOrders:107")
    bekleme = await db.scalar(
        select(ServiceHold).where(ServiceHold.service_order_id == bekleyen.id)
    )
    assert bekleyen.status == "BEKLEMEDE" and bekleme.released_at is None
    assert bekleme.onceki_durum == "SAHADA" and bekleme.neden == "DIGER"
    assert await _is(db, "WorkOrders:104") is None  # planlı bakım karantinada
    assert await _is(db, "WorkOrders:105") is None  # eşlenemeyen durum karantinada

    zaman = {z.source_ref: z for z in (await db.scalars(select(ServiceTimeEntry))).all()}
    assert zaman["WorkOrderTimeLogs:801"].user_id == ort.ali.id
    assert not zaman["WorkOrderTimeLogs:801"].is_deleted
    cakisan = zaman["WorkOrderTimeLogs:802"]
    assert (
        cakisan.user_id == ort.ali.id and cakisan.is_deleted and cakisan.iptal_turu == "GOC_CAKISMA"
    )
    bilinmeyen = zaman["WorkOrderTimeLogs:803"]
    assert bilinmeyen.user_id is None and bilinmeyen.kaynak_personel_adi == "Bilinmeyen Kişi"
    assert bilinmeyen.faaliyet == "BEKLEME" and bilinmeyen.bekleme_nedeni == "DIGER"
    assert zaman["WorkOrderTimeLogs:804"].iptal_turu == "GOC_IPTAL"
    assert zaman["WorkOrderLiveSessions:901"].faaliyet == "MOLA"

    satirlar = await servis_uzlasma.uzlasma(db, kosu)
    assert all(u["tutarli"] for u in satirlar), satirlar
    tablolar = {u["kaynak_tablo"]: u for u in satirlar}
    assert (
        tablolar["WorkOrders"]["kaynak"],
        tablolar["WorkOrders"]["aktarilan"],
        tablolar["WorkOrders"]["karantina"],
        tablolar["WorkOrders"]["reddedilen"],
    ) == (9, 6, 2, 1)
    assert (tablolar["WorkOrderPlans"]["aktarilan"], tablolar["WorkOrderPlans"]["karantina"]) == (
        4,
        1,
    )
    ornekler = await servis_uzlasma.ornek_isler(db)
    assert len(ornekler) == 5
    rapor = servis_uzlasma.rapor_xlsx(kosu, satirlar, ornekler)
    assert rapor[:2] == b"PK"
    assert servis_uzlasma.servis_karantina_xlsx(kosu)[:2] == b"PK"


async def test_ikinci_kosu_sifir_yeni_satir(seeded):
    db = seeded
    await goc_ortami(db)
    await _goc(db)
    sayilar = [
        await _say(db, m)
        for m in (ServiceEquipment, ServiceOrder, ServiceOrderEvent, ServicePlan, ServiceTimeEntry)
    ]
    ikinci = await _goc(db)
    assert all(s.yeni == 0 for s in ikinci.sonuclar)
    assert sayilar == [
        await _say(db, m)
        for m in (ServiceEquipment, ServiceOrder, ServiceOrderEvent, ServicePlan, ServiceTimeEntry)
    ]


async def test_onizleme_hicbir_sey_yazmaz(seeded):
    db = seeded
    await goc_ortami(db)
    kosu = await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), uygula=False)
    await db.rollback()
    assert await _say(db, ServiceOrder) == 0 and await _say(db, ServiceEquipment) == 0
    servis = next(s for s in kosu.sonuclar if s.kaynak_tablo == "WorkOrders")
    assert servis.yeni == 6


async def test_birim_bazli_gecis_provasi(seeded):
    """Yalnız GUVENLIK aktarılır; diğer birimler ertelenir ve uzlaşmada sayılır."""
    db = seeded
    await goc_ortami(db)
    kosu = await _goc(db, adimlar=("servis",), birimler=frozenset({"GUVENLIK"}))
    birimler = set((await db.scalars(select(ServiceOrder.birim))).all())
    assert birimler == {"GUVENLIK"}
    satir = (await servis_uzlasma.uzlasma(db, kosu))[0]
    assert satir["ertelenen"] == 2 and satir["tutarli"]  # iki POC işi
    sonraki = await _goc(db, adimlar=("servis",), birimler=frozenset({"POC"}))
    assert sonraki.sonuclar[0].yeni == 2


async def test_eski_numara_cakisirsa_yeni_seri_ve_aciklamada_iz(seeded, servis_isi_ac):
    db = seeded
    await goc_ortami(db)
    var = await servis_isi_ac()
    var.so_no = "SRV-202601-0001"
    await db.commit()
    await _goc(db, adimlar=("servis",))
    gocen = await _is(db, "WorkOrders:101")
    assert gocen.so_no != "SRV-202601-0001"
    assert "Eski no: SRV-202601-0001" in (gocen.aciklama or "")
