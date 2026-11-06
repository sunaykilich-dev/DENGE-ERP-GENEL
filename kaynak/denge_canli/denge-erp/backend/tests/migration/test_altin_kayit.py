"""ALTIN KAYIT TESTİ — göçün kuruşu kuruşuna doğruluğu.

Bu, projenin en önemli testi. D5 sonrası ERP ve canlı hak ediş uygulaması bir
ay PARALEL koşacak ve iki rapor karşılaştırılacak; fark açıklanamazsa ekip
ERP'nin rakamına güvenmez ve uygulamayı kullanmaz. Bu tek başına projeyi
batırır.

Girdi: canlı veritabanının anonimleştirilmiş kopyası. Plaka, firma, IMEI'nin
son haneleri maskeli; tarih, tutar, montaj noktası adı, ödeme durumu ve dönem
AYNEN korunuyor — test tam olarak bunları doğruluyor.

Beklenen değerler `tests/fixtures/altin/hakedis-anonim.db` üzerinden bu
oturumda ölçüldü ve canlı veritabanıyla karşılaştırılarak doğrulandı.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.migration.hazirla import hazirla
from app.migration.hazirla_envanter import hakedis_envanteri
from app.migration.hazirla_isemri import isemirlerini_hazirla
from app.migration.kaynak_hakedis import HakedisKaynagi
from app.migration.yukle import uygula
from app.migration.yukle_isemri import isemirlerini_yaz
from app.models import (
    Account,
    Device,
    DeviceVehicleAssignment,
    PartnerSettlement,
    SettlementLine,
    WorkOrder,
    WorkOrderItem,
)
from app.services import devices as cihaz_svc

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[1] / "fixtures" / "altin" / "hakedis-anonim.db"

# --- Beklenen değerler -------------------------------------------------------
BEKLENEN_IS_KAYDI = 1235
BEKLENEN_ODENECEK_KALEM = 932
BEKLENEN_ODENMEYECEK_KALEM = 281
BEKLENEN_KARAR_BEKLEYEN = 22
BEKLENEN_GENEL_TOPLAM = Decimal("552825.00")

# Döküm sayısı 84 DEĞİL 83: `ANTALYA RAMAZAN CULLU` ile `ANTALYA RAMAZAN ÇULLU`
# 2026-02'de ikisi de iş yapmış; montaj noktası birleştirmesi sonrası tek
# döküme iniyorlar. Para toplamı değişmiyor — birleştirme kasıtlı.
BEKLENEN_DOKUM = 83

BEKLENEN_DONEMLER = {
    "2026-01": (208, Decimal("152700.00")),
    "2026-02": (190, Decimal("98475.00")),
    "2026-03": (132, Decimal("60950.00")),
    # Nisan: küçük harfli "ödenecek" 3 kaydın dahil edilmesi kararıyla
    # 146/86.300 yerine 149/89.300. Canlı uygulama bu 3 kaydı tam eşleşme
    # yaptığı için hak edişe HİÇ almamıştı.
    "2026-04": (149, Decimal("89300.00")),
    "2026-05": (150, Decimal("96000.00")),
    "2026-06": (91, Decimal("51100.00")),
    "2026-07": (12, Decimal("4300.00")),
}


@pytest.fixture(scope="module")
def kaynak() -> HakedisKaynagi:
    if not FIXTURE.exists():
        pytest.skip(
            f"Altın kayıt fixture'ı yok: {FIXTURE}\n"
            "Üretmek için: uv run python tests/fixtures/anonimlestir.py"
        )
    return HakedisKaynagi(yol=FIXTURE)


async def _gocu_calistir(db, kaynak: HakedisKaynagi) -> dict[str, int]:
    sonuc = hazirla(kaynak)
    isler = kaynak.isler()
    hakedis_envanteri(isler, sonuc)
    taslaklar = isemirlerini_hazirla(isler, sonuc)
    sayac = await uygula(db, sonuc)
    sayac.update(await isemirlerini_yaz(db, taslaklar, sonuc))
    # `main()` ile aynı sıra: göç türetilmiş alanları da uzlaştırır.
    uzlasma = await cihaz_svc.uzlastir(db)
    sayac["uzlastirilan_cihaz"] = uzlasma["farkli"]
    await db.commit()
    return sayac


async def _toplamlar(db) -> dict:
    dokum = await db.scalar(select(func.count()).select_from(PartnerSettlement))
    satir = await db.scalar(select(func.count()).select_from(SettlementLine))
    toplam = await db.scalar(select(func.coalesce(func.sum(SettlementLine.amount), 0)))
    brut = await db.scalar(select(func.coalesce(func.sum(PartnerSettlement.gross_amount), 0)))
    return {
        "dokum": dokum,
        "satir": satir,
        "toplam": Decimal(str(toplam)),
        "brut": Decimal(str(brut)),
    }


class TestAltinKayit:
    async def test_genel_toplam_kurusu_kurusuna(self, db, seeded, kaynak):
        """En kritik iddia: hak ediş toplamı canlı uygulamayla aynı."""
        await _gocu_calistir(db, kaynak)
        t = await _toplamlar(db)
        assert t["toplam"] == BEKLENEN_GENEL_TOPLAM
        assert t["brut"] == BEKLENEN_GENEL_TOPLAM, "döküm brütleri satır toplamıyla tutmuyor"

    async def test_donem_bazinda_tutar_ve_is_adedi(self, db, seeded, kaynak):
        await _gocu_calistir(db, kaynak)
        for donem, (beklenen_is, beklenen_tutar) in BEKLENEN_DONEMLER.items():
            satirlar = (
                await db.execute(
                    select(
                        func.count().filter(SettlementLine.work_type != "YOL_KM"),
                        func.coalesce(func.sum(SettlementLine.amount), 0),
                    )
                    .select_from(SettlementLine)
                    .join(
                        PartnerSettlement,
                        PartnerSettlement.id == SettlementLine.settlement_id,
                    )
                    .where(PartnerSettlement.period == donem)
                )
            ).one()
            assert satirlar[0] == beklenen_is, f"{donem} iş adedi"
            assert Decimal(str(satirlar[1])) == beklenen_tutar, f"{donem} tutarı"

    async def test_dokum_sayisi(self, db, seeded, kaynak):
        await _gocu_calistir(db, kaynak)
        assert (await _toplamlar(db))["dokum"] == BEKLENEN_DOKUM

    async def test_odenebilirlik_dagilimi(self, db, seeded, kaynak):
        """İşlerin %22,8'i ödenmiyor; bu karar kalemde tutulur."""
        await _gocu_calistir(db, kaynak)
        dagilim = dict(
            (
                await db.execute(
                    select(WorkOrderItem.payability, func.count()).group_by(
                        WorkOrderItem.payability
                    )
                )
            ).all()
        )
        assert dagilim["ODENECEK"] == BEKLENEN_ODENECEK_KALEM
        assert dagilim["ODENMEYECEK"] == BEKLENEN_ODENMEYECEK_KALEM
        assert dagilim["KARAR_BEKLIYOR"] == BEKLENEN_KARAR_BEKLEYEN

    async def test_hicbir_kayit_kaybolmadi(self, db, seeded, kaynak):
        """1235 = iş emri kalemi. Kayıp satır sessizce düşmüş demektir."""
        await _gocu_calistir(db, kaynak)
        kalem = await db.scalar(select(func.count()).select_from(WorkOrderItem))
        assert kalem == BEKLENEN_IS_KAYDI

    async def test_goc_iki_kez_kosunca_degismez(self, db, seeded, kaynak):
        """İdempotentlik: canlı uygulama geliştirme boyunca çalışmaya devam
        edecek ve delta defalarca aktarılacak."""
        ilk = await _gocu_calistir(db, kaynak)
        ilk_toplam = await _toplamlar(db)

        ikinci = await _gocu_calistir(db, kaynak)
        ikinci_toplam = await _toplamlar(db)

        assert ikinci_toplam == ilk_toplam
        assert ikinci["is_emri"] == ilk["is_emri"]
        assert ikinci["kalem"] == ilk["kalem"]

        kalem = await db.scalar(select(func.count()).select_from(WorkOrderItem))
        assert kalem == BEKLENEN_IS_KAYDI, "ikinci koşu kopya kalem üretti"

    async def test_montaj_noktalari_birlestirildi(self, db, seeded, kaynak):
        await _gocu_calistir(db, kaynak)
        adet = await db.scalar(
            select(func.count()).select_from(Account).where(Account.is_montaj_noktasi.is_(True))
        )
        assert adet == 39, "44 montaj noktası 39'a inmeliydi (5 birleştirme)"

    async def test_odenmeyecek_kalemler_hak_edise_girmez(self, db, seeded, kaynak):
        """Bu kural olmadan ay sonu dökümüne 303 iş fazladan girer ve montaj
        noktasına fazla ödeme yapılır."""
        await _gocu_calistir(db, kaynak)
        sizanlar = await db.scalar(
            select(func.count())
            .select_from(SettlementLine)
            .join(WorkOrderItem, WorkOrderItem.id == SettlementLine.work_order_item_id)
            .where(WorkOrderItem.payability != "ODENECEK")
        )
        assert sizanlar == 0

    async def test_donem_isten_bagimsiz(self, db, seeded, kaynak):
        """17 kayıtta `ay` ≠ iş tarihinin ayı: iş bir ay yapılıp sonraki ayın
        hak edişinde ödenmiş. İkisini aynılaştırmak parayı yanlış aya taşır."""
        await _gocu_calistir(db, kaynak)
        ayrisanlar = await db.scalar(
            select(func.count())
            .select_from(WorkOrder)
            .where(
                WorkOrder.completed_at.is_not(None),
                func.to_char(WorkOrder.completed_at, "YYYY-MM") != WorkOrder.settlement_period,
            )
        )
        assert ayrisanlar > 0, "dönem iş tarihinden türetilmiş olmamalı"

    async def test_cihaz_arac_donemleri_cakismiyor(self, db, seeded, kaynak):
        """Çakışma kısıtı veritabanında; bu test çıkarım algoritmasının onu
        ihlal etmeden çalıştığını kanıtlar (kısıt ihlali olsaydı göç patlardı)."""
        await _gocu_calistir(db, kaynak)
        donem = await db.scalar(select(func.count()).select_from(DeviceVehicleAssignment))
        assert donem > 0

        acik_fazlasi = (
            await db.execute(
                select(DeviceVehicleAssignment.device_id, func.count())
                .where(DeviceVehicleAssignment.valid_to.is_(None))
                .group_by(DeviceVehicleAssignment.device_id)
                .having(func.count() > 1)
            )
        ).all()
        assert acik_fazlasi == [], "bir cihazın birden fazla açık dönemi var"

    async def test_turetilmis_alanlar_gocte_doldurulur(self, db, seeded, kaynak):
        """Göç, `devices.current_*` ve `first_activation_date` alanlarını da
        doldurmalı.

        Bu bir gerileme testi: göç bunları bir süre doldurmadı ve sonucu
        ancak RMA ekranında görüldü — garanti başlangıcı
        `first_activation_date`'ten hesaplandığı için göçten gelen HER
        cihazın garanti kararı "belirsiz" çıkıyordu. Uzlaştırmayı ayrı bir
        elle adım olarak bırakmak, bir gün unutulacağı anlamına gelir.
        """
        await _gocu_calistir(db, kaynak)

        # Açık bir araç dönemi olan her cihazda `current_vehicle_id` dolu olmalı.
        eksik_arac = await db.scalar(
            select(func.count())
            .select_from(Device)
            .join(
                DeviceVehicleAssignment,
                DeviceVehicleAssignment.device_id == Device.id,
            )
            .where(
                DeviceVehicleAssignment.valid_to.is_(None),
                Device.current_vehicle_id.is_(None),
            )
        )
        assert eksik_arac == 0, "açık araç dönemi olan cihazda current_vehicle_id boş"

        # Hiç montaj görmüş cihazın ilk aktivasyon tarihi bilinmeli.
        eksik_aktivasyon = await db.scalar(
            select(func.count())
            .select_from(Device)
            .join(
                DeviceVehicleAssignment,
                DeviceVehicleAssignment.device_id == Device.id,
            )
            .where(Device.first_activation_date.is_(None))
        )
        assert eksik_aktivasyon == 0, "montaj görmüş cihazda first_activation_date boş"
