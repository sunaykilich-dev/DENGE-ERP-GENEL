"""Cihaz–araç ömür boyu geçmişi (brief §4.5).

Kabul kriterleri 2, 3 ve 6'nın tamamı bu modülden cevaplanır:
  2. "X tarihinde bu cihaz hangi araçtaydı?"  → `arac_tarihinde`
  3. "Bu aracın geçmişindeki tüm cihazlar"     → `aracin_cihazlari`
  6. Sök-tak eski kaydı kapatır, yeni kaydı açar, çakışma olmaz → `tak`/`sok`
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Device, DeviceVehicleAssignment


class AtamaHatasi(ValueError):
    """Cihaz–araç dönemi kurallarına aykırı işlem."""


def _an(deger: datetime) -> datetime:
    return deger if deger.tzinfo else deger.replace(tzinfo=UTC)


async def acik_donem(db: AsyncSession, device_id: int) -> DeviceVehicleAssignment | None:
    return await db.scalar(
        select(DeviceVehicleAssignment).where(
            DeviceVehicleAssignment.device_id == device_id,
            DeviceVehicleAssignment.valid_to.is_(None),
        )
    )


async def arac_tarihinde(
    db: AsyncSession, device_id: int, an: datetime
) -> DeviceVehicleAssignment | None:
    """Kabul kriteri 2."""
    an = _an(an)
    return await db.scalar(
        select(DeviceVehicleAssignment).where(
            DeviceVehicleAssignment.device_id == device_id,
            DeviceVehicleAssignment.valid_from <= an,
            (DeviceVehicleAssignment.valid_to.is_(None)) | (DeviceVehicleAssignment.valid_to > an),
        )
    )


async def aracin_cihazlari(
    db: AsyncSession, vehicle_id: int, *, yalniz_takili: bool = False
) -> list[DeviceVehicleAssignment]:
    """Kabul kriteri 3 — aracın geçmişindeki TÜM cihazlar.

    Bir araçta aynı anda birden fazla cihaz olabilir; bu yüzden liste döner.
    """
    stmt = select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.vehicle_id == vehicle_id)
    if yalniz_takili:
        stmt = stmt.where(DeviceVehicleAssignment.valid_to.is_(None))
    return list((await db.scalars(stmt.order_by(DeviceVehicleAssignment.valid_from.desc()))).all())


async def tak(
    db: AsyncSession,
    *,
    device_id: int,
    vehicle_id: int,
    clock: Clock,
    customer_id: int | None = None,
    sim_id: int | None = None,
    installed_by_type: str | None = None,
    installed_by_id: int | None = None,
    work_order_id: int | None = None,
    an: datetime | None = None,
    is_inferred: bool = False,
) -> DeviceVehicleAssignment:
    """Cihazı araca takar. Açık dönem varsa ÖNCE kapatır.

    Çakışma kısıtı zaten koruyor ama açık dönemi kapatmadan yeni dönem
    açmaya çalışmak kullanıcıya anlaşılmaz bir veritabanı hatası gösterirdi.
    """
    zaman = _an(an or clock.now())
    onceki = await acik_donem(db, device_id)
    if onceki is not None:
        if onceki.vehicle_id == vehicle_id:
            return onceki  # zaten aynı araçta
        # Açık dönemi kendi başlangıcına (ya da öncesine) kapatmak sıfır
        # uzunlukta bir dönem üretir ve `ck_dva_aralik`'e çarpar. Aynı ANDA
        # iki araçta olmak zaten anlamsız; veritabanı hatası yerine açık
        # mesaj verilir.
        if onceki.valid_from >= zaman:
            raise AtamaHatasi(
                f"Cihaz {onceki.valid_from:%d.%m.%Y %H:%M} tarihinden beri zaten bir araçta; "
                "yeni montaj bu andan SONRA olmalı."
            )
        onceki.valid_to = zaman
        onceki.removal_reason = onceki.removal_reason or "Yeni montaj kaydı (çıkarım)"
        onceki.is_inferred = True

    kayit = DeviceVehicleAssignment(
        device_id=device_id,
        vehicle_id=vehicle_id,
        customer_id=customer_id,
        sim_id=sim_id,
        installed_by_type=installed_by_type,
        installed_by_id=installed_by_id,
        install_work_order_id=work_order_id,
        valid_from=zaman,
        is_inferred=is_inferred,
        recorded_at=zaman.date(),
    )
    db.add(kayit)
    await db.flush()

    cihaz = await db.get(Device, device_id)
    if cihaz is not None:
        cihaz.current_vehicle_id = vehicle_id
        cihaz.current_customer_id = customer_id
    return kayit


async def sok(
    db: AsyncSession,
    *,
    device_id: int,
    clock: Clock,
    work_order_id: int | None = None,
    neden: str | None = None,
    an: datetime | None = None,
) -> DeviceVehicleAssignment | None:
    """Açık dönemi kapatır. Açık dönem yoksa None döner (hata değil —
    göçte söküm kaydı olup montajı olmayan satırlar var)."""
    kayit = await acik_donem(db, device_id)
    if kayit is None:
        return None
    kayit.valid_to = _an(an or clock.now())
    kayit.removal_work_order_id = work_order_id
    kayit.removal_reason = neden
    await db.flush()

    cihaz = await db.get(Device, device_id)
    if cihaz is not None:
        cihaz.current_vehicle_id = None
    return kayit


def donemleri_cikar(olaylar: list[dict]) -> list[dict]:
    """Söküm kaydı olmayan veriden cihaz–araç dönemlerini türetir.

    Kaynakta söküm kayıtları tutarsız: 124 IMEI birden çok iş emrinde, 83'ü
    farklı plakalarda ve aralarda tek bir "Demontaj" satırı yok. Cihaz iki
    araçta aynı anda görünemeyeceği için dönemler çıkarımla kapatılır.

    AYNI GÜN SIRALAMASI iki gerçek duruma birden uymak zorunda:
      - 6 kayıtta cihaz aynı gün bir araçtan alınıp başkasına takılmış
        (sök-tak): SÖKÜM önce işlenmeli.
      - 2 kayıtta cihaz aynı gün takılıp aynı araçtan sökülmüş (başarısız
        montaj): MONTAJ önce işlenmeli.
    Ayırt edici işaret sökümün AÇIK DÖNEMLE aynı araca ait olup olmadığı;
    bu yüzden sıralama durumdan bağımsız değil, gün gün ve duruma duyarlı
    yapılır.

    `olaylar`: [{"tarih", "tip", "vehicle_id", ...}]
    Döner: [{"vehicle_id", "valid_from", "valid_to", "is_inferred", ...}]
    """
    MONTAJ_TIPLERI = {"MONTAJ", "SOK_TAK", "DEGISIM"}
    donemler: list[dict] = []
    acik: dict | None = None

    gunler: dict = {}
    for olay in olaylar:
        gunler.setdefault(olay["tarih"], []).append(olay)

    for tarih in sorted(gunler):
        gun = gunler[tarih]
        montajlar = [o for o in gun if o["tip"] in MONTAJ_TIPLERI]
        sokumler = [o for o in gun if o["tip"] == "SOKUM"]

        # Açık dönemin aracını söken kayıt varsa ÖNCE o işlenir (sök-tak);
        # kalan sökümler montajlardan sonraya bırakılır (aynı gün takılıp
        # sökülen cihaz).
        onceki_arac = acik["vehicle_id"] if acik else None
        once = [o for o in sokumler if o["vehicle_id"] == onceki_arac]
        sonra = [o for o in sokumler if o["vehicle_id"] != onceki_arac]

        for olay in [*once, *montajlar, *sonra]:
            if olay["tip"] in MONTAJ_TIPLERI:
                if acik is not None:
                    acik["valid_to"] = tarih
                    acik["is_inferred"] = True
                    acik["removal_reason"] = "ÇIKARIM: yeni montaj kaydı"
                acik = {
                    "vehicle_id": olay["vehicle_id"],
                    "customer_id": olay.get("customer_id"),
                    "sim_id": olay.get("sim_id"),
                    "installed_by_id": olay.get("installed_by_id"),
                    "install_work_order_id": olay.get("work_order_id"),
                    "valid_from": tarih,
                    "valid_to": None,
                    "is_inferred": False,
                    "removal_reason": None,
                }
                donemler.append(acik)
            elif acik is not None:
                acik["valid_to"] = tarih
                acik["removal_work_order_id"] = olay.get("work_order_id")
                acik["removal_reason"] = "Söküm iş emri"
                acik = None

    # Aynı gün açılıp kapanan sıfır uzunluklu dönemler atılır: yarı açık
    # aralıkta [t, t) geçersizdir ve veritabanı kısıtına takılır.
    return [d for d in donemler if d["valid_to"] is None or d["valid_to"] > d["valid_from"]]
