"""İş emri, cihaz–araç dönemi ve hak ediş dökümlerinin yazılması."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration.esleme import kaynak_ref
from app.migration.hazirla_isemri import IsEmriTaslagi
from app.models import (
    Account,
    Device,
    PartnerSettlement,
    Product,
    SettlementLine,
    Vehicle,
    WorkOrder,
    WorkOrderItem,
)
from app.services.assignments import donemleri_cikar
from app.services.normalize import tr_normkey
from app.services.settlements import yuvarla

KAYNAK = "hakedis"


def _donem_son_gunu(donem: str) -> datetime:
    yil, ay = (int(p) for p in donem.split("-"))
    son = 31
    while True:
        try:
            return datetime(yil, ay, son, 12, tzinfo=UTC)
        except ValueError:
            son -= 1


async def isemirlerini_yaz(
    db: AsyncSession, taslaklar: list[IsEmriTaslagi], sonuc
) -> dict[str, int]:
    sayac = {"is_emri": 0, "kalem": 0, "donem_kaydi": 0, "dokum": 0, "hak_edis_satiri": 0}

    hesaplar = {h.title_key: h.id for h in (await db.scalars(select(Account))).all()}
    araclar = {a.plate: a.id for a in (await db.scalars(select(Vehicle))).all()}
    cihazlar = {c.imei: c.id for c in (await db.scalars(select(Device))).all() if c.imei}
    urunler = {u.code: u.id for u in (await db.scalars(select(Product))).all()}

    for sira, t in enumerate(taslaklar, start=1):
        ref = kaynak_ref("isemri", t.anahtar)
        wo = await db.scalar(
            select(WorkOrder).where(WorkOrder.source_system == KAYNAK, WorkOrder.source_ref == ref)
        )
        tamamlanma = (
            datetime.combine(t.tarih, datetime.min.time(), tzinfo=UTC).replace(hour=12)
            if t.tarih
            else _donem_son_gunu(t.donem)
        )
        nokta_id = hesaplar.get(tr_normkey(t.montaj_noktasi))
        alanlar = {
            "wo_no": f"G{t.donem.replace('-', '')}-{sira:05d}",
            "type": t.tip,
            "status": "ONAYLANDI",  # hepsi geçmiş, kapanmış iş
            "customer_id": hesaplar.get(tr_normkey(t.firma)),
            "vehicle_id": araclar.get(t.plaka),
            "odometer_km": t.km,
            "assigned_type": "MONTAJ_NOKTASI",
            "assigned_id": nokta_id,
            "completed_at": tamamlanma,
            "approved_at": tamamlanma,
            "settlement_period": t.donem,
            "travel_km": Decimal(str(t.travel_km)) if t.travel_km else None,
            "travel_unit_price": (
                Decimal(str(t.travel_unit_price)) if t.travel_unit_price else None
            ),
            "form_data": t.form_data,
        }
        if wo is None:
            wo = WorkOrder(source_system=KAYNAK, source_ref=ref, **alanlar)
            db.add(wo)
            await db.flush()
        else:
            for alan, deger in alanlar.items():
                setattr(wo, alan, deger)
        sayac["is_emri"] += 1

        # Kalem göçü de kaynak kimliğiyle idempotent: ilk koşuda cihaz kaydı
        # henüz açılmamışsa device_id boş kalır ve sonraki koşuda tamamlanır.
        var_olan = {
            k.source_ref: k
            for k in (
                await db.scalars(select(WorkOrderItem).where(WorkOrderItem.work_order_id == wo.id))
            ).all()
        }
        for kalem in t.kalemler:
            kalem_ref = kaynak_ref("kalem", kalem["kaynak_id"])
            alanlar_k = {
                "device_id": cihazlar.get(kalem["imei"]) if kalem["imei"] else None,
                "product_id": urunler.get(kalem["urun_kodu"] or ""),
                "action": kalem["action"],
                "device_role": kalem["device_role"],
                "payability": kalem["payability"],
                "non_payable_reason": kalem["non_payable_reason"],
                "unit_price": Decimal(str(kalem["unit_price"])),
                "price_source": "GOC",
                "notes": kalem["notes"],
            }
            mevcut = var_olan.get(kalem_ref)
            if mevcut is None:
                db.add(
                    WorkOrderItem(
                        work_order_id=wo.id,
                        source_system=KAYNAK,
                        source_ref=kalem_ref,
                        **alanlar_k,
                    )
                )
            else:
                for alan, deger in alanlar_k.items():
                    if deger is not None or getattr(mevcut, alan) is None:
                        setattr(mevcut, alan, deger)
            sayac["kalem"] += 1
        await db.flush()

    # Dönem çıkarımı TÜM iş emirleri yazıldıktan sonra, VERİTABANINDAKİ
    # kalemler üzerinden tek seferde koşar. Yalnız yeni oluşturulan kalemlerden
    # toplamak, ikinci koşuda hiç dönem üretmiyordu — ve iki kaynaktan gelen
    # kayıtlar için ayrı ayrı koşmak çakışan zaman çizelgeleri üretirdi.
    sayac["donem_kaydi"] = await _donemleri_yaz(db, sonuc)
    dokum, satir = await _dokumleri_yaz(db, taslaklar, hesaplar)
    sayac["dokum"], sayac["hak_edis_satiri"] = dokum, satir
    return sayac


async def _donemleri_yaz(db: AsyncSession, sonuc) -> int:
    """Cihaz–araç dönemlerini çıkarımla üretir ve yazar."""
    from app.models import DeviceVehicleAssignment

    satirlar = (
        await db.execute(
            select(WorkOrderItem, WorkOrder)
            .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
            .where(
                WorkOrderItem.device_id.is_not(None),
                WorkOrder.vehicle_id.is_not(None),
                WorkOrder.is_deleted.is_(False),
            )
        )
    ).all()

    cihaz_olaylari: dict[int, list[dict]] = {}
    for kalem, wo in satirlar:
        cihaz_olaylari.setdefault(kalem.device_id, []).append(
            {
                "tarih": wo.completed_at,
                "tip": wo.type,
                "vehicle_id": wo.vehicle_id,
                "customer_id": wo.customer_id,
                "installed_by_id": wo.assigned_id,
                "work_order_id": wo.id,
            }
        )

    yazilan = 0
    for cihaz_id, olaylar in cihaz_olaylari.items():
        var_mi = await db.scalar(
            select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.device_id == cihaz_id)
        )
        if var_mi is not None:
            continue
        for d in donemleri_cikar(olaylar):
            db.add(
                DeviceVehicleAssignment(
                    device_id=cihaz_id,
                    vehicle_id=d["vehicle_id"],
                    customer_id=d.get("customer_id"),
                    installed_by_type="MONTAJ_NOKTASI",
                    installed_by_id=d.get("installed_by_id"),
                    install_work_order_id=d.get("install_work_order_id"),
                    removal_work_order_id=d.get("removal_work_order_id"),
                    valid_from=d["valid_from"],
                    valid_to=d["valid_to"],
                    removal_reason=d.get("removal_reason"),
                    is_inferred=d["is_inferred"],
                )
            )
            yazilan += 1
        await db.flush()
    return yazilan


async def _dokumleri_yaz(
    db: AsyncSession, taslaklar: list[IsEmriTaslagi], hesaplar: dict
) -> tuple[int, int]:
    """Hak ediş dökümlerini ve satırlarını yazar.

    Kesinti/stopaj kaynakta YOK; geçmiş dökümler brütle girer ve
    `net_payable = gross`. Belge tipine göre kesinti YENİ dönemlerde
    uygulanır — geçmişi yeniden hesaplamak canlı uygulamayla tutmazdı.
    """
    dokum_sayisi = satir_sayisi = 0
    gruplar: dict[tuple[str, int], list[IsEmriTaslagi]] = {}
    for t in taslaklar:
        nokta_id = hesaplar.get(tr_normkey(t.montaj_noktasi))
        if nokta_id is None:
            continue
        if not any(k["payability"] == "ODENECEK" for k in t.kalemler):
            continue
        gruplar.setdefault((t.donem, nokta_id), []).append(t)

    for (donem, nokta_id), grup in gruplar.items():
        ref = kaynak_ref("dokum", f"{donem}|{nokta_id}")
        dokum = await db.scalar(
            select(PartnerSettlement).where(
                PartnerSettlement.source_system == KAYNAK,
                PartnerSettlement.source_ref == ref,
            )
        )
        if dokum is None:
            dokum = PartnerSettlement(
                source_system=KAYNAK,
                source_ref=ref,
                partner_id=nokta_id,
                period=donem,
                status="ODEME_BEKLIYOR",
                tax_snapshot={"belge_tipi": "GOC", "not": "Kaynakta kesinti/stopaj yok"},
            )
            db.add(dokum)
            await db.flush()
        dokum_sayisi += 1

        mevcut = await db.scalar(
            select(SettlementLine).where(SettlementLine.settlement_id == dokum.id).limit(1)
        )
        if mevcut is not None:
            continue

        brut = Decimal("0")
        for t in grup:
            wo = await db.scalar(
                select(WorkOrder).where(
                    WorkOrder.source_system == KAYNAK,
                    WorkOrder.source_ref == kaynak_ref("isemri", t.anahtar),
                )
            )
            kalemler = (
                await db.scalars(select(WorkOrderItem).where(WorkOrderItem.work_order_id == wo.id))
            ).all()
            for kalem in kalemler:
                if kalem.payability != "ODENECEK":
                    continue
                tutar = yuvarla(Decimal(str(kalem.unit_price or 0)))
                db.add(
                    SettlementLine(
                        settlement_id=dokum.id,
                        work_order_id=wo.id,
                        work_order_item_id=kalem.id,
                        work_type=_hak_edis_tipi(wo.type, kalem.device_role),
                        description=f"{wo.wo_no} · {kalem.action}",
                        unit_price=tutar,
                        quantity=1,
                        amount=tutar,
                        price_source="GOC",
                    )
                )
                brut += tutar
                satir_sayisi += 1

            if wo.travel_km and wo.travel_unit_price:
                km = Decimal(str(wo.travel_km))
                birim = Decimal(str(wo.travel_unit_price))
                tutar = yuvarla(km * birim)
                db.add(
                    SettlementLine(
                        settlement_id=dokum.id,
                        work_order_id=wo.id,
                        work_type="YOL_KM",
                        description=f"{wo.wo_no} · yol {km} km",
                        unit_price=birim,
                        quantity=km,
                        amount=tutar,
                        price_source="GOC",
                    )
                )
                brut += tutar
                satir_sayisi += 1

        dokum.gross_amount = yuvarla(brut)
        dokum.net_payable = yuvarla(brut)
        await db.flush()

    return dokum_sayisi, satir_sayisi


def _hak_edis_tipi(wo_tipi: str, rol: str | None) -> str:
    if wo_tipi in ("SOKUM", "SOK_TAK", "DEGISIM", "ARIZA", "KESIF"):
        return wo_tipi
    return {
        "KAMERA": "DASHCAM_MONTAJ",
        "YARDIMCI_KAMERA": "HARICI_KAMERA_MONTAJ",
    }.get(rol or "", "ATS_MONTAJ")
