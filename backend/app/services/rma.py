"""RMA iş kuralları: garanti kararı, durum akışı, değişim devri.

Garanti kararı **açılış anında hesaplanır ve donar** — sonradan garanti
tarihi düzeltilse bile açılmış kaydın kararı değişmez (bkz. model başlığı).

Cihaz durumu RMA akışına BAĞLIDIR (brief §4.12): `ARIZALI → RMA → TAMIRDE →
YENIDEN_STOKTA | HURDA`. Durum geçişleri her zaman durum makinesinden
yürütülür; RMA ekranından cihaz durumuna doğrudan atama yapılmaz.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Device, Product, RmaCase
from app.services import settings as ayar_svc
from app.services.devices import durum_degistir, garanti_bitisi
from app.services.statemachine import CIHAZ, IzinsizGecis

# RMA durumu → cihazın olması gereken durumu. Kapanışta çözüm belirler.
RMA_CIHAZ_DURUMU = {
    "ACIK": "ARIZALI",
    "INCELEMEDE": "RMA",
    "TAMIRDE": "TAMIRDE",
    "TEDARIKCIDE": "RMA",
}

COZUM_CIHAZ_DURUMU = {
    "TAMIR": "YENIDEN_STOKTA",
    "DEGISIM": "HURDA",
    "IADE": "YENIDEN_STOKTA",
    "ONARILMADI": "HURDA",
    "HURDAYA_AYRILDI": "HURDA",
}


class RmaHatasi(ValueError):
    """RMA kurallarına aykırı işlem."""


async def garanti_karari(
    db: AsyncSession, cihaz: Device, *, gelis: date
) -> tuple[str, date | None]:
    """Cihazın geliş tarihindeki garanti durumunu ve bitişini döner.

    Garanti başlangıcı İLK AKTİVASYONDUR, satın alma değil: cihaz depoda
    beklerken garanti yakmak müşteri lehine olmayan ama gerçeğe de uymayan
    bir sonuç verirdi.
    """
    if cihaz.warranty_end_date:
        bitis = cihaz.warranty_end_date
    elif cihaz.first_activation_date:
        urun = await db.get(Product, cihaz.product_id)
        ay = (
            urun.warranty_months
            if urun and urun.warranty_months
            else int(await ayar_svc.get(db, "varsayilan_garanti_ay"))
        )
        bitis = garanti_bitisi(cihaz.first_activation_date, ay)
    else:
        # Aktivasyon tarihi yok (göçten gelen cihazların bir kısmı):
        # "garanti dışı" demek haksızlık, "garanti içi" demek uydurma olurdu.
        return "BELIRSIZ", None

    return ("GARANTI_ICI" if gelis <= bitis else "GARANTI_DISI"), bitis


async def numara_uret(db: AsyncSession, clock: Clock) -> str:
    sira = (await db.scalar(select(RmaCase.id).order_by(RmaCase.id.desc()).limit(1)) or 0) + 1
    return f"RMA{clock.now():%Y}-{sira:05d}"


async def ac(
    db: AsyncSession,
    *,
    cihaz: Device,
    ariza: str,
    gelis: date,
    clock: Clock,
    customer_id: int | None = None,
    vehicle_id: int | None = None,
    user_id: int | None = None,
) -> RmaCase:
    """RMA kaydı açar ve cihazı ARIZALI'ya çeker.

    Aynı cihaz için açık RMA varsa ikincisi açılmaz: iki ayrı kayıt, aynı
    cihazın durumunu iki yerden sürüklemek demekti.
    """
    acik = await db.scalar(
        select(RmaCase).where(
            RmaCase.device_id == cihaz.id,
            RmaCase.is_deleted.is_(False),
            RmaCase.status.notin_(("KAPANDI", "IPTAL")),
        )
    )
    if acik is not None:
        raise RmaHatasi(f"Bu cihazın açık servis kaydı zaten var: {acik.rma_no}")

    durum, bitis = await garanti_karari(db, cihaz, gelis=gelis)
    kayit = RmaCase(
        rma_no=await numara_uret(db, clock),
        device_id=cihaz.id,
        customer_id=customer_id or cihaz.current_customer_id,
        vehicle_id=vehicle_id or cihaz.current_vehicle_id,
        received_at=gelis,
        fault_description=ariza,
        warranty_status=durum,
        warranty_end_date=bitis,
        created_by=user_id,
    )
    db.add(kayit)
    await db.flush()

    await _cihazi_hizala(db, cihaz, "ARIZALI", clock=clock, user_id=user_id, kayit=kayit)
    return kayit


async def durum_ilerlet(
    db: AsyncSession,
    kayit: RmaCase,
    hedef: str,
    *,
    clock: Clock,
    user_id: int | None = None,
) -> RmaCase:
    """RMA durumunu ilerletir ve cihazı ona göre hizalar."""
    if kayit.status in ("KAPANDI", "IPTAL"):
        raise RmaHatasi(f"{kayit.status} durumundaki kayıt değiştirilemez.")
    if hedef == "COZULDU" and not kayit.resolution:
        raise RmaHatasi("Çözüm girilmeden kayıt çözüldü sayılamaz.")

    kayit.status = hedef
    cihaz = await db.get(Device, kayit.device_id)
    hedef_cihaz = RMA_CIHAZ_DURUMU.get(hedef)
    if cihaz is not None and hedef_cihaz:
        await _cihazi_hizala(db, cihaz, hedef_cihaz, clock=clock, user_id=user_id, kayit=kayit)
    await db.flush()
    return kayit


async def coz(
    db: AsyncSession,
    kayit: RmaCase,
    *,
    cozum: str,
    clock: Clock,
    not_: str | None = None,
    maliyet=None,
    yeni_cihaz_id: int | None = None,
    user_id: int | None = None,
) -> RmaCase:
    """Çözümü işler; DEĞİŞİMDE yeni cihazı eskinin yerine devreder.

    Değişimde araç, hat ve müşteri bağı yeni IMEI'ye taşınır; eski–yeni
    ilişkisi `replacement_device_id`'de kalır (brief §4.12).
    """
    if kayit.status in ("KAPANDI", "IPTAL"):
        raise RmaHatasi(f"{kayit.status} durumundaki kayıt değiştirilemez.")
    if cozum == "DEGISIM" and not yeni_cihaz_id:
        raise RmaHatasi("Değişim çözümünde yerine geçecek cihaz seçilmeli.")
    if kayit.warranty_status == "GARANTI_ICI" and maliyet and maliyet > 0:
        raise RmaHatasi(
            "Garanti içi kayda müşteri bedeli yazılamaz; garanti durumu 'garanti dışı' "
            "değilse ücret çıkmamalı."
        )

    kayit.resolution = cozum
    kayit.resolution_note = not_
    kayit.cost = maliyet
    kayit.replacement_device_id = yeni_cihaz_id

    eski = await db.get(Device, kayit.device_id)
    if cozum == "DEGISIM" and yeni_cihaz_id:
        await _devret(db, eski, yeni_cihaz_id, clock=clock, user_id=user_id, kayit=kayit)

    hedef = COZUM_CIHAZ_DURUMU.get(cozum)
    if eski is not None and hedef:
        await _cihazi_hizala(db, eski, hedef, clock=clock, user_id=user_id, kayit=kayit)

    kayit.status = "COZULDU"
    await db.flush()
    return kayit


async def kapat(
    db: AsyncSession, kayit: RmaCase, *, clock: Clock, user_id: int | None = None
) -> RmaCase:
    if kayit.status != "COZULDU":
        raise RmaHatasi("Yalnız çözülmüş kayıt kapatılabilir.")
    kayit.status = "KAPANDI"
    kayit.closed_at = clock.now()
    kayit.updated_by = user_id
    await db.flush()
    return kayit


async def _devret(
    db: AsyncSession,
    eski: Device | None,
    yeni_id: int,
    *,
    clock: Clock,
    user_id: int | None,
    kayit: RmaCase,
) -> None:
    """Değişimde araç/hat/müşteri bağını yeni cihaza taşır."""
    from app.services import assignments as atama_svc
    from app.services.devices import hat_tak

    yeni = await db.get(Device, yeni_id)
    if yeni is None:
        raise RmaHatasi(f"Yerine geçecek cihaz bulunamadı: {yeni_id}")
    if yeni.id == (eski.id if eski else None):
        raise RmaHatasi("Cihaz kendisiyle değiştirilemez.")
    if eski is None:
        return

    acik = await atama_svc.acik_donem(db, eski.id)
    simdi = clock.now()

    hat_kaydi = None
    if eski.current_sim_id:
        from app.models import SimDeviceHistory

        hat_kaydi = await db.scalar(
            select(SimDeviceHistory).where(
                SimDeviceHistory.device_id == eski.id, SimDeviceHistory.valid_to.is_(None)
            )
        )
        if hat_kaydi is not None:
            if hat_kaydi.valid_from >= simdi:
                raise RmaHatasi(
                    f"Hat eşleşmesi {hat_kaydi.valid_from:%d.%m.%Y %H:%M} tarihinde "
                    "başlıyor; değişim bu andan sonra kaydedilmeli."
                )
            hat_kaydi.valid_to = simdi
            eski.current_sim_id = None
            await db.flush()

    if acik is not None:
        await atama_svc.sok(
            db, device_id=eski.id, clock=clock, neden=f"RMA değişimi ({kayit.rma_no})"
        )
        # Yeni cihaz aynı araca, aynı müşteriyle takılır.
        for adim in CIHAZ.yol(yeni.status, "AKTIF"):
            try:
                await durum_degistir(
                    db, yeni, adim, clock=clock, user_id=user_id, neden=f"RMA {kayit.rma_no}"
                )
            except IzinsizGecis:
                break
        await atama_svc.tak(
            db,
            device_id=yeni.id,
            vehicle_id=acik.vehicle_id,
            clock=clock,
            customer_id=acik.customer_id,
            installed_by_type=acik.installed_by_type,
            installed_by_id=acik.installed_by_id,
            an=simdi,
        )

    if hat_kaydi is not None:
        await hat_tak(db, device_id=yeni.id, sim_id=hat_kaydi.sim_id, clock=clock)


async def _cihazi_hizala(
    db: AsyncSession,
    cihaz: Device,
    hedef: str,
    *,
    clock: Clock,
    user_id: int | None,
    kayit: RmaCase,
) -> None:
    """Cihazı hedef duruma, makinenin izin verdiği en kısa yoldan götürür."""
    for adim in CIHAZ.yol(cihaz.status, hedef):
        try:
            await durum_degistir(
                db, cihaz, adim, clock=clock, user_id=user_id, neden=f"RMA {kayit.rma_no}"
            )
        except IzinsizGecis:
            break


# --- Raporlar -----------------------------------------------------------------


async def ariza_orani(
    db: AsyncSession, *, gun: int = 365, clock: Clock | None = None
) -> list[dict]:
    """Model bazında arıza oranı (brief §4.12).

    Payda: o modelden sistemdeki TOPLAM cihaz. Yalnız arıza sayısını
    listelemek çok satan modeli kötü gösterirdi.
    """
    bugun = clock.now().date() if clock else date.today()
    baslangic = bugun - timedelta(days=gun)

    toplamlar = dict(
        (
            await db.execute(
                select(Device.product_id, func.count())
                .where(Device.is_deleted.is_(False))
                .group_by(Device.product_id)
            )
        ).all()
    )
    arizalar = dict(
        (
            await db.execute(
                select(Device.product_id, func.count(func.distinct(RmaCase.id)))
                .join(Device, Device.id == RmaCase.device_id)
                .where(RmaCase.is_deleted.is_(False), RmaCase.received_at >= baslangic)
                .group_by(Device.product_id)
            )
        ).all()
    )
    urunler = {
        u.id: u for u in (await db.scalars(select(Product).where(Product.id.in_(toplamlar)))).all()
    }

    sonuc = [
        {
            "product_id": pid,
            "urun_kodu": urunler[pid].code if pid in urunler else str(pid),
            "urun_adi": urunler[pid].name if pid in urunler else "",
            "cihaz_sayisi": toplam,
            "rma_sayisi": arizalar.get(pid, 0),
            "ariza_orani": round(arizalar.get(pid, 0) / toplam * 100, 2) if toplam else 0.0,
        }
        for pid, toplam in toplamlar.items()
    ]
    sonuc.sort(key=lambda x: x["ariza_orani"], reverse=True)
    return sonuc
