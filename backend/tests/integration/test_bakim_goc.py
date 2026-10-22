"""Bakım sözleşmesi göçü ve teyit profili (TS-173; E04-03, E04-04, E04-D03).

Kabul:
- TEYIT_BEKLIYOR dışındaki (ekrandan yönetilen) kayıt "korundu": "güncelle"
  kararı verilse bile yazılmaz;
- adet 11 → 8 düzeltmesinde 3 kalem SİLİNMEZ, `valid_to` alır;
- ücret kolonları yalnız `maliyet.gor` sahibinde yazılır;
- birden çok müşteri adayı → karantina; eşleşmeyen müşteri hesapsız teyit;
- eski numara korunur, sequence ilerler; aynı dosya ikinci kez 0 yeni.
"""

import io
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.clock import FakeClock
from app.migration import bakim_sozlesme as mg
from app.migration.servis_kaynak import KaynakDizini
from app.models import Account, MaintenanceContract, MaintenanceContractItem
from app.services import imports as ice
from app.services.imports.bakim_sozlesme import SUTUNLAR, BakimSozlesmeProfili
from app.services.teknik_servis import numara
from tests.migration.goc_ortami import FIXTURE

pytestmark = pytest.mark.integration

BASLIKLAR = [s.baslik for s in SUTUNLAR]


def _satir(**alanlar) -> list:
    return [alanlar.get(s.alan) for s in SUTUNLAR]


def _xlsx(satirlar: list[list]) -> bytes:
    wb = Workbook()
    wb.active.append(BASLIKLAR)
    for s in satirlar:
        wb.active.append(s)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def _uygula(db, satirlar, *, user_id=None, kararlar=None, clock=None):
    profil = BakimSozlesmeProfili()
    okuma = ice.oku("bakim.xlsx", _xlsx(satirlar), profil)
    staged = [s.sozluk() for s in await profil.dogrula(db, okuma.satirlar)]
    sayac = await profil.yaz(
        db,
        staged,
        clock=clock or FakeClock(datetime(2026, 6, 1, tzinfo=UTC)),
        user_id=user_id,
        kararlar=kararlar or {},
    )
    await db.commit()
    return staged, sayac


async def _hesaplar(db):
    akyaka = Account(title="Akyaka Park AVM", is_musteri=True)
    ortak1 = Account(title="Ortak Ad", is_musteri=True)
    ortak2 = Account(title="ORTAK AD Ltd", is_musteri=True)  # unvan anahtarı aynı ("ortak ad")
    db.add_all([akyaka, ortak1, ortak2])
    await db.commit()
    return akyaka


async def _aktif_kalem(db, sozlesme_id: int, tur: str = "XRAY") -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(MaintenanceContractItem)
            .where(
                MaintenanceContractItem.contract_id == sozlesme_id,
                MaintenanceContractItem.equipment_type == tur,
                MaintenanceContractItem.is_deleted.is_(False),
                MaintenanceContractItem.valid_to.is_(None),
            )
        )
        or 0
    )


async def test_teyit_listesi_yuklenir_eski_no_korunur_ikinci_kez_sifir(seeded):
    db = seeded
    akyaka = await _hesaplar(db)
    satirlar, _ = mg.teyit_satirlari(KaynakDizini(FIXTURE).tablo("MaintenanceContracts"))
    staged, sayac = await _uygula(db, satirlar)
    assert sayac["eklendi"] == 3, staged
    s11 = await db.scalar(
        select(MaintenanceContract).where(
            MaintenanceContract.source_ref == "MaintenanceContracts:11"
        )
    )
    assert s11.contract_no == "BAKIM-0011" and s11.status == "TEYIT_BEKLIYOR"
    assert s11.account_id == akyaka.id
    assert s11.legacy_products_text == "9 X-RAY + 8 KAPI DEDEKTÖRÜ"
    assert s11.fee_per_visit is None and s11.legacy_fee_text is None  # ücret kolonu yok
    assert await _aktif_kalem(db, s11.id) == 9
    assert await _aktif_kalem(db, s11.id, "KAPI_DEDEKTORU") == 8
    pasif = await db.scalar(
        select(MaintenanceContract).where(
            MaintenanceContract.source_ref == "MaintenanceContracts:13"
        )
    )
    # Müşterisi eşleşmeyen eski pasif sözleşme hesapsız PASIF olamaz: teyit bekler.
    assert pasif.status == "TEYIT_BEKLIYOR" and pasif.account_id is None
    assert "PASIF" in pasif.teyit_gerekcesi
    # Sequence göçteki en büyük numaradan sonra devam eder.
    nolar = (await db.scalars(select(MaintenanceContract.contract_no))).all()
    en_buyuk = max(int(n.split("-")[1]) for n in nolar)
    assert int((await numara.bakim_sozlesme_no(db)).split("-")[1]) > en_buyuk
    await db.rollback()

    staged, sayac = await _uygula(db, satirlar)
    assert sayac["eklendi"] == 0 and sayac["guncellendi"] == 0
    assert all(s["cakisma"] for s in staged)


async def test_korundu_kurali_ve_adet_azaltma(seeded):
    db = seeded
    akyaka = await _hesaplar(db)
    ilk = _satir(
        kaynak="MaintenanceContracts:50",
        musteri="Akyaka Park AVM",
        baslangic="01.01.2026",
        bitis="31.12.2026",
        frekans=4,
        xray=11,
        kapi=0,
        durum="TEYIT_BEKLIYOR",
    )
    await _uygula(db, [ilk])
    sozlesme = await db.scalar(
        select(MaintenanceContract).where(
            MaintenanceContract.source_ref == "MaintenanceContracts:50"
        )
    )
    assert await _aktif_kalem(db, sozlesme.id) == 11

    duzeltme = _satir(**{**dict(zip([s.alan for s in SUTUNLAR], ilk, strict=True)), "xray": 8})
    staged, sayac = await _uygula(db, [duzeltme])
    assert staged[0]["cakisma"]["tip"] == "mevcut" and sayac["guncellendi"] == 0  # varsayılan atla
    staged, sayac = await _uygula(db, [duzeltme], kararlar={1: "guncelle"})
    assert sayac["guncellendi"] == 1
    assert await _aktif_kalem(db, sozlesme.id) == 8
    kapanan = (
        await db.scalars(
            select(MaintenanceContractItem).where(
                MaintenanceContractItem.contract_id == sozlesme.id,
                MaintenanceContractItem.valid_to.is_not(None),
            )
        )
    ).all()
    assert sorted(k.sira for k in kapanan) == [9, 10, 11]  # silinmedi, kapandı
    assert all(not k.is_deleted for k in kapanan)

    # Ekrandan AKTIF yapılmış kayıt: korundu; "güncelle" kararı da yazmaz.
    sozlesme.status = "AKTIF"
    sozlesme.account_id = akyaka.id
    await db.commit()
    yeni = _satir(**{**dict(zip([s.alan for s in SUTUNLAR], ilk, strict=True)), "xray": 2})
    staged, sayac = await _uygula(db, [yeni], kararlar={1: "guncelle"})
    assert staged[0]["cakisma"]["tip"] == "korundu"
    assert sayac["korundu"] == 1 and sayac["guncellendi"] == 0
    assert await _aktif_kalem(db, sozlesme.id) == 8


async def test_belirsiz_musteri_karantina_ucret_yalniz_maliyet_yetkisiyle(seeded, kullanici_ac):
    db = seeded
    await _hesaplar(db)
    satirlar = [
        _satir(kaynak="MaintenanceContracts:60", musteri="ORTAK AD", xray=1),
        _satir(
            kaynak="MaintenanceContracts:61",
            musteri="Hiç Bilinmeyen",
            xray=1,
            ucret_metin="5.000 TL",
        ),
    ]
    staged, sayac = await _uygula(db, satirlar)
    assert "Birden çok müşteri adayı" in staged[0]["hatalar"][0]
    assert sayac["eklendi"] == 1 and sayac["ucret_yok_sayildi"] == 1
    yazilan = await db.scalar(
        select(MaintenanceContract).where(
            MaintenanceContract.source_ref == "MaintenanceContracts:61"
        )
    )
    assert yazilan.account_id is None and yazilan.status == "TEYIT_BEKLIYOR"
    assert yazilan.legacy_fee_text is None

    admin = await kullanici_ac("admin", "ADMIN")
    satir = _satir(
        kaynak="MaintenanceContracts:62",
        musteri="Akyaka Park AVM",
        xray=1,
        ucret_metin="7.000 TL",
        ucret_toplam="7000",
    )
    _, sayac = await _uygula(db, [satir], user_id=admin.id)
    yazilan = await db.scalar(
        select(MaintenanceContract).where(
            MaintenanceContract.source_ref == "MaintenanceContracts:62"
        )
    )
    assert yazilan.legacy_fee_text == "7.000 TL" and float(yazilan.contract_total) == 7000.0
