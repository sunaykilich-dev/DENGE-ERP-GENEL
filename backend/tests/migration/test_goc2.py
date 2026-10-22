"""Göç-2 (D3-G): atölye/kiralama pilot raporu, kiralık envanter profili, eğitim göçü,
SLA geri doldurma, eski parça metni ve eşleştirme Faz 2 (TS-205…208).

Döküm `tests/fixtures/goc_v1_d3/*.csv` SAHTE verilerdir.
"""

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select, text

from app.clock import FakeClock
from app.migration import (
    atolye_saglik,
    egitim,
    servis_sla_geri_doldur,
    servis_uzlasma,
)
from app.migration.ana_veri_olcum import salt_okunur
from app.migration.servis_kaynak import GOC_SISTEMI, KaynakDizini
from app.models import (
    Account,
    CompetencyAssessment,
    PersonnelNameMap,
    Product,
    RentalAsset,
    RentalCatalogItem,
    RentalInventoryMovement,
    ServiceEquipment,
    ServiceOrder,
    ServiceOrderEvent,
    ServiceSlaPolicy,
    StockMovement,
    TrainingAttendance,
    TrainingCourse,
    TrainingCriterion,
    TrainingPlan,
    Warehouse,
)
from app.services import imports as ice
from app.services import settings as ayarlar
from app.services.imports import kiralama_goc
from app.services.imports.musteri_eslestirme import MusteriEslestirmeProfili, faz2_adaylari
from app.services.teknik_servis import veri_kalitesi
from tests.migration.goc_ortami import goc_ortami, kisi_ac

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "goc_v1_d3"


async def _say(db, model, *kosul) -> int:
    stmt = select(func.count()).select_from(model)
    for k in kosul:
        stmt = stmt.where(k)
    return int(await db.scalar(stmt) or 0)


def _xlsx(satirlar: list[list]) -> bytes:
    wb = Workbook()
    for s in satirlar:
        wb.active.append(s)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def _servis_gocu(db) -> None:
    await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), adimlar=("servis", "parca"), uygula=True)
    await db.commit()


# --- TS-205: atölye sağlık raporu (salt okunur) ----------------------------------------


async def test_atolye_saglik_salt_okunur_ve_kisi_eslemesi(seeded, engine):
    db = seeded
    ort = await goc_ortami(db)
    async with salt_okunur(engine) as conn:
        kisiler = await atolye_saglik.kisi_haritasi(conn)
        with pytest.raises(Exception):  # noqa: B017 — salt okunur transaction yazmayı reddeder
            await conn.execute(text("UPDATE users SET full_name = full_name"))
    assert kisiler["ALI VELI"] == ort.ali.id
    rapor = atolye_saglik.saglik_raporu(KaynakDizini(FIXTURE), kisiler)
    assert rapor.sayilar["ESLESMEYEN_ATANAN"] == 1


# --- TS-205: kiralık envanter profili (kararsız uyumsuz satır aktarılmaz) ---------------


async def _kiralama_kurulum(db):
    depo = Warehouse(code="GOC-KIR", name="Göç Kiralık", kiralama_deposu=True)
    seri = Product(code="KR-XRAY", name="X-Ray Kiralık", identity_kind="SERI_NO")
    toplu = Product(code="KR-BARIYER", name="Bariyer", identity_kind="YOK")
    db.add_all([depo, seri, toplu])
    await db.flush()
    db.add_all(
        [
            RentalCatalogItem(product_id=seri.id, birim="GUVENLIK"),
            RentalCatalogItem(product_id=toplu.id, birim="GUVENLIK"),
        ]
    )
    await db.commit()
    return depo


async def _envanter_uygula(db, satirlar, kararlar=None):
    profil = kiralama_goc.KiralikEnvanterGocProfili()
    okuma = ice.oku("envanter.xlsx", _xlsx(satirlar), profil)
    staged = [s.sozluk() for s in await profil.dogrula(db, okuma.satirlar)]
    sayac = await profil.yaz(db, staged, clock=FakeClock(), user_id=None, kararlar=kararlar or {})
    await db.commit()
    return staged, sayac


async def test_kiralik_envanter_kararsiz_uyumsuz_aktarilmaz(seeded):
    db = seeded
    depo = await _kiralama_kurulum(db)
    dizin = KaynakDizini(FIXTURE)
    u = kiralama_goc.uzlastirma(dizin)
    satirlar = [kiralama_goc.KARAR_BASLIKLARI]
    for s in kiralama_goc.envanter_karar_satirlari(dizin, u):
        s = list(s)
        s[2] = depo.id
        if s[0] in ("RentalInventory:1001", "RentalInventory:1002", "RentalInventory:1003"):
            s[7] = "KONTROLDE"  # Kirada girişte seçilemez: göç sorumlusu seçer
        satirlar.append(s)

    staged, sayac = await _envanter_uygula(db, satirlar)
    durum = {s["veri"]["ref"]: s for s in staged}
    assert durum["RentalInventory:1003"]["cakisma"]["tip"] == "uyumsuzluk"
    assert durum["RentalInventory:1001"]["cakisma"] is not None
    assert durum["RentalInventory:1004"]["cakisma"] is None
    assert all(not s["hatalar"] for s in staged), [s["hatalar"] for s in staged]
    # Kararsız uyumsuz iki satır yazılmadı; 1002, 1004 (seri) ve 1005 (toplu) yazıldı.
    assert sayac["eklendi"] == 3
    refler = set(
        (
            await db.scalars(
                select(RentalAsset.source_ref).where(RentalAsset.source_system == GOC_SISTEMI)
            )
        ).all()
    )
    assert refler == {"RentalInventory:1002", "RentalInventory:1004"}
    toplu = await db.scalar(
        select(RentalInventoryMovement).where(
            RentalInventoryMovement.asset_id.is_(None), RentalInventoryMovement.kind == "GIRIS"
        )
    )
    assert toplu.qty == 5 and toplu.to_durum == "HAZIR"

    # Açık kararla uyumsuz satır aktarılır; ikinci koşu 0 yeni.
    karar = {durum["RentalInventory:1003"]["satir_no"]: "guncelle"}
    _, ikinci = await _envanter_uygula(db, satirlar, karar)
    assert ikinci["eklendi"] == 1 and ikinci["onaylanan_uyumsuz"] == 1
    _, ucuncu = await _envanter_uygula(db, satirlar, karar)
    assert ucuncu["eklendi"] == 0
    assert await _say(db, RentalAsset) == 3
    assert await _say(db, RentalInventoryMovement) == 4


# --- TS-206: eğitim göçü -------------------------------------------------------------


async def test_egitim_gocu_eslesme_karantina_idempotent(seeded):
    db = seeded
    ort = await goc_ortami(db)
    mkaya = await kisi_ac(db, "M. Kaya", "mkaya")
    await db.commit()
    dizin = KaynakDizini(FIXTURE)
    kosu = await egitim.hazirla(db, dizin)
    await egitim.yukle(db, kosu, dizin=dizin)
    await db.commit()

    b = kosu.baglam
    assert b.kisiler[1] == ort.ali.id and b.kisi_nedeni[1] == "ERP_KULLANICI"
    assert b.kisiler[3] == mkaya.id  # kullanıcı adı büyük/küçük harf duyarsız
    assert b.kisiler[2] is None and b.kisiler[4] is None  # otomatik kullanıcı YOK
    assert await _say(db, TrainingCourse) == 2  # kategorisi eşlenmeyen kurs karantinada
    maddeler = (await db.scalars(select(TrainingCriterion).order_by(TrainingCriterion.sira))).all()
    assert [m.metin for m in maddeler] == ["Eldiven kullanır", "Kask takar"]
    cas = (await db.scalars(select(CompetencyAssessment))).all()
    assert [(c.user_id, c.kaynak) for c in cas] == [(ort.ali.id, "GOC")]
    assert {a.user_id for a in (await db.scalars(select(TrainingAttendance))).all()} == {
        ort.ali.id,
        mkaya.id,
    }
    planlar = {p.source_ref: p for p in (await db.scalars(select(TrainingPlan))).all()}
    assert set(planlar) == {"TrainingPlans:1", "TrainingPlans:2"}
    assert planlar["TrainingPlans:2"].status == "TAMAMLANDI"
    # Eşleşmeyen ad İK'ya öneri olarak düştü (karar verilmedi).
    oneriler = (
        await db.scalars(
            select(PersonnelNameMap.kaynak_ad).where(
                PersonnelNameMap.kaynak_alan == egitim.ALAN_PERSONEL,
                # `Personnel.FullName` artık ad eşleme alanı (Dalga 3 bütünleştirme):
                # ortamın ONAYLI satırı (Ali Veli) öneri değildir.
                PersonnelNameMap.durum != "ONAYLANDI",
            )
        )
    ).all()
    assert set(oneriler) == {"Ayşe Yılmaz", "Can Demir"}

    satirlar = await egitim.uzlasma(db, kosu)
    assert all(u["tutarli"] for u in satirlar), satirlar
    tablo = {u["kaynak_tablo"]: u for u in satirlar}
    assert (tablo["TrainingCourses"]["aktarilan"], tablo["TrainingCourses"]["karantina"]) == (2, 1)
    assert tablo["TrainingObservations"]["karantina"] == 1

    sayilar = [await _say(db, m) for m in (TrainingCourse, CompetencyAssessment, TrainingPlan)]
    ikinci = await egitim.hazirla(db, dizin)
    await egitim.yukle(db, ikinci, dizin=dizin)
    await db.commit()
    assert all(s.yeni == 0 for s in ikinci.sonuclar)
    assert sayilar == [
        await _say(db, m) for m in (TrainingCourse, CompetencyAssessment, TrainingPlan)
    ]
    assert egitim.rapor_xlsx(ikinci, satirlar, dizin)[:2] == b"PK"


async def test_egitim_ekrandaki_ayni_kodlu_kurs_ezilmez(seeded):
    db = seeded
    await goc_ortami(db)
    db.add(TrainingCourse(kod="ISG-01", baslik="Ekranda açıldı", kategori="ISG", sure_saat=1))
    await db.commit()
    kosu = await egitim.hazirla(db, KaynakDizini(FIXTURE))
    kurs = kosu.sonuclar[0]
    assert ("TrainingCourses:1", "'ISG-01' kodlu kurs zaten var (ekrandaki kayıt ezilmez)") in (
        kurs.karantina
    )
    await db.rollback()


# --- TS-207: SLA geri doldurma --------------------------------------------------------


async def _politika(db):
    if not await db.scalar(select(func.count()).select_from(ServiceSlaPolicy)):
        db.add_all(
            [
                ServiceSlaPolicy(oncelik="KRITIK", cozum_saat=12),
                ServiceSlaPolicy(oncelik="YUKSEK", cozum_saat=24),
                ServiceSlaPolicy(oncelik="NORMAL", cozum_saat=72),
            ]
        )
        await db.commit()


async def test_sla_geri_doldurma_rapor_yazmaz_uygula_idempotent(seeded):
    db = seeded
    await goc_ortami(db)
    await _politika(db)
    await _servis_gocu(db)
    kapali = await db.scalar(
        select(ServiceOrder).where(ServiceOrder.source_ref == "WorkOrders:201")
    )
    acik = await db.scalar(select(ServiceOrder).where(ServiceOrder.source_ref == "WorkOrders:202"))
    surumler = (kapali.version, acik.version)
    # Göç-1 düzeltmesi: DURUM olaylarının yeni durumu boş yazılmaz (executemany anahtarı).
    yeni_durumlar = (
        await db.scalars(
            select(ServiceOrderEvent.yeni_durum).where(
                ServiceOrderEvent.service_order_id == kapali.id,
                ServiceOrderEvent.olay_turu == "DURUM",
            )
        )
    ).all()
    assert "SAHADA" in yeni_durumlar and "KAPATILDI" in yeni_durumlar

    # Rapor modu: yürürlük yok → açık iş yazılmaz; hiçbir şey değişmez.
    rapor = await servis_sla_geri_doldur.hazirla(db)
    servis_sla_geri_doldur.kaynak_raporu(rapor, KaynakDizini(FIXTURE))
    await db.rollback()
    assert rapor.sayilar["OLCULEMEDI"] == 1 and rapor.sayilar["YURURLUK_YOK"] == 1
    assert rapor.geriye_donuk_sayilari  # GERİYE DÖNÜK yalnız raporda
    assert {r[1] for r in rapor.bekleme_nedenleri} == {"MALZEME", "DIGER"}
    assert ["Garip", "NORMAL", 1, "KATALOG DIŞI — göçte NORMAL yazıldı"] in rapor.oncelik_eslemesi
    for so in (kapali, acik):
        await db.refresh(so)
    assert (kapali.version, acik.version) == surumler
    assert kapali.sla_sonuc is None and acik.sla_kaynak is None
    assert servis_sla_geri_doldur.rapor_xlsx(rapor)[:2] == b"PK"

    yururluk = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    await ayarlar.set_many(db, {"servis_sla_yururluk_at": yururluk.isoformat()}, None)
    await db.commit()
    plan = await servis_sla_geri_doldur.hazirla(db)
    degisen = await servis_sla_geri_doldur.uygula(db, plan, clock=FakeClock())
    await db.commit()
    assert degisen == 2
    await db.refresh(kapali)
    await db.refresh(acik)
    assert kapali.sla_sonuc == "OLCULEMEDI" and kapali.sla_kaynak is None
    assert kapali.cozum_hedef_at is None  # kapalı tarihsel işe hedef yazılmaz
    assert kapali.ilk_mudahale_at == datetime(2026, 2, 2, 8, 0, tzinfo=UTC)  # eski log
    assert acik.sla_kaynak == "GECIS" and acik.sla_baslangic_at == yururluk
    assert acik.cozum_hedef_at == datetime(2026, 3, 2, 9, 0, tzinfo=UTC)  # YUKSEK 24 sa
    assert acik.cozum_hedef_ilk_at == acik.cozum_hedef_at

    ikinci = await servis_sla_geri_doldur.hazirla(db)
    assert await servis_sla_geri_doldur.uygula(db, ikinci, clock=FakeClock()) == 0
    await db.commit()


# --- TS-208: eski parça metni ve eşleştirme Faz 2 ---------------------------------------


async def test_parca_metni_not_olayi_stok_hareketi_yok_idempotent(seeded):
    db = seeded
    await goc_ortami(db)
    stok_once = await _say(db, StockMovement)
    await _servis_gocu(db)
    notlar = (
        await db.scalars(
            select(ServiceOrderEvent).where(
                ServiceOrderEvent.olay_turu == "NOT",
                ServiceOrderEvent.veri["goc"].astext == GOC_SISTEMI,
            )
        )
    ).all()
    metinler = {n.veri["kaynak"]: n for n in notlar}
    assert set(metinler) == {"MaintenanceDeviceItems:501", "MaintenanceDeviceItems:504"}
    assert metinler["MaintenanceDeviceItems:501"].veri["parca_metni"] == (
        '2 adet sigorta, 1 röle; "kablo" 3m  '
    )
    uzun = metinler["MaintenanceDeviceItems:504"]
    assert len(uzun.ozet) == 500 and len(uzun.veri["parca_metni"]) > 500
    assert await _say(db, StockMovement) == stok_once  # E11-21: stok hareketi yok

    kosu = await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), adimlar=("parca",), uygula=True)
    await db.commit()
    assert all(s.yeni == 0 for s in kosu.sonuclar)
    satirlar = await servis_uzlasma.uzlasma(db, kosu)
    assert all(u["tutarli"] for u in satirlar), satirlar
    mdi = next(u for u in satirlar if u["kaynak_tablo"] == "MaintenanceDeviceItems")
    assert (mdi["kaynak"], mdi["aktarilan"], mdi["karantina"]) == (4, 2, 2)


async def test_eslestirme_faz2_servis_isi_ve_diger_birim_ekipman(seeded):
    db = seeded
    await goc_ortami(db)
    await _servis_gocu(db)
    hedef = Account(title="Bilinmeyen Firma A.Ş.", is_musteri=True)
    db.add(hedef)
    await db.commit()
    adaylar = await faz2_adaylari(db, "servis_isi")
    is_202 = await db.scalar(
        select(ServiceOrder).where(ServiceOrder.source_ref == "WorkOrders:202")
    )
    satir = next(r for r in adaylar if r["id"] == is_202.id)
    assert satir["tablo"] == "service_orders" and satir["musteri"] == "Bilinmeyen Firma"
    surum = is_202.version
    await db.refresh(is_202)
    assert is_202.version == surum  # aday üretimi veriyi değiştirmez

    ekipman = ServiceEquipment(
        birim="HABERLESME", equipment_type="TELSIZ", serial_no="H-1", customer_name_raw="BF"
    )
    db.add(ekipman)
    await db.commit()
    profil = MusteriEslestirmeProfili()
    basliklar = list(veri_kalitesi.ADAY_BASLIKLARI)
    dosya = [
        basliklar,
        ["service_orders", is_202.id, *[None] * 7, "E", hedef.id, None, "Kuzey Kapı"],
        ["service_equipment", ekipman.id, *[None] * 7, "E", hedef.id, None, None],
    ]
    okuma = ice.oku("faz2.xlsx", _xlsx(dosya), profil)
    staged = [s.sozluk() for s in await profil.dogrula(db, okuma.satirlar)]
    assert [s["hatalar"] for s in staged] == [[], []]  # Faz 2: Güvenlik dışı birim serbest
    sayac = await profil.yaz(db, staged, clock=FakeClock(), user_id=None, kararlar={})
    await db.commit()
    assert sayac["tablolar"]["service_orders"]["yazilan"] == 1
    await db.refresh(is_202)
    assert is_202.customer_id == hedef.id and is_202.address_id is not None
    assert is_202.customer_name_raw == "Bilinmeyen Firma"  # ham metin korunur
    ikinci = await profil.yaz(db, staged, clock=FakeClock(), user_id=None, kararlar={})
    assert ikinci["guncellendi"] == 0
