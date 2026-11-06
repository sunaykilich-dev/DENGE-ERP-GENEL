"""Cihaz iş kuralları."""

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Device, DeviceStatusHistory, Product, SimDeviceHistory
from app.services import audit
from app.services.statemachine import CIHAZ


class EslemeHatasi(ValueError):
    """Cihaz–hat eşleşmesi kurallarına aykırı işlem."""


class KimlikHatasi(ValueError):
    """Ürünün kimlik politikasına aykırı cihaz kaydı."""


async def kimlik_dogrula(
    db: AsyncSession, product_id: int, imei: str | None, serial_no: str | None
) -> str:
    """Ürünün kimlik tipini döndürür ve gerekli alanın dolu olduğunu doğrular.

    Veritabanı da aynı kuralı CHECK ile zorluyor; buradaki kontrol kullanıcıya
    anlaşılır bir mesaj vermek için. İkisi birden var çünkü şema kuralı
    garanti eder, servis kuralı ANLATIR.
    """
    urun = await db.get(Product, product_id)
    if urun is None:
        raise KimlikHatasi(f"Ürün bulunamadı: {product_id}")
    if urun.identity_kind == "IMEI" and not imei:
        raise KimlikHatasi(
            f"'{urun.name}' IMEI ile takip edilen bir üründür; IMEI boş bırakılamaz."
        )
    if urun.identity_kind == "SERI_NO" and not serial_no:
        raise KimlikHatasi(
            f"'{urun.name}' seri numarasıyla takip edilir (bu üründe IMEI fiziksel olarak "
            "yoktur); seri no boş bırakılamaz."
        )
    return urun.identity_kind


async def durum_degistir(
    db: AsyncSession,
    cihaz: Device,
    hedef: str,
    *,
    clock: Clock,
    user_id: int | None = None,
    neden: str | None = None,
    ip: str | None = None,
    an: datetime | None = None,
) -> None:
    """Tek geçiş yolu. Kural kontrolü + geçmiş kaydı + denetim izi birlikte.

    Durum alanına doğrudan atama yapılmamalı — bu fonksiyon atlanırsa
    "HURDA'dan AKTIF'e" gibi imkânsız geçişler sessizce mümkün olur.

    `an` verilirse geçiş O ANDA olmuş sayılır. Geçmiş tarihli bir montaj
    kaydı girilirken şart: aksi halde ilk aktivasyon (ve dolayısıyla garanti
    başlangıcı) kaydın GİRİLDİĞİ güne kayar, işin yapıldığı güne değil.
    """
    CIHAZ.dogrula(cihaz.status, hedef)
    onceki = cihaz.status
    cihaz.status = hedef
    zaman = an or clock.now()

    db.add(
        DeviceStatusHistory(
            device_id=cihaz.id,
            from_status=onceki,
            to_status=hedef,
            reason=neden,
            changed_at=zaman,
            changed_by=user_id,
        )
    )
    # İlk aktivasyon tarihi garanti hesabının başlangıcıdır; bir kez yazılır.
    if hedef == "AKTIF" and cihaz.first_activation_date is None:
        cihaz.first_activation_date = zaman.date()

    await audit.log(
        db,
        "devices",
        "durum.degistir",
        entity_id=cihaz.id,
        old_value={"status": onceki},
        new_value={"status": hedef, "neden": neden},
        user_id=user_id,
        ip=ip,
    )
    await db.flush()


def garanti_bitisi(baslangic: date, ay: int) -> date:
    """Garanti cihaza bağlıdır; araç değişse de süre değişmez (brief §4.5)."""
    yil, kalan = divmod(baslangic.month - 1 + ay, 12)
    return baslangic.replace(year=baslangic.year + yil, month=kalan + 1, day=min(baslangic.day, 28))


async def aktif_hat(db: AsyncSession, device_id: int) -> SimDeviceHistory | None:
    """Cihazda ŞU AN takılı hat — doğruluk kaynağı tarihli tablodur."""
    return await db.scalar(
        select(SimDeviceHistory).where(
            SimDeviceHistory.device_id == device_id, SimDeviceHistory.valid_to.is_(None)
        )
    )


async def hat_tarihinde(db: AsyncSession, device_id: int, an: datetime) -> SimDeviceHistory | None:
    """'X tarihinde bu cihazda hangi hat vardı' — kabul kriteri 2'nin hat ayağı."""
    an = an if an.tzinfo else an.replace(tzinfo=UTC)
    return await db.scalar(
        select(SimDeviceHistory).where(
            SimDeviceHistory.device_id == device_id,
            SimDeviceHistory.valid_from <= an,
            (SimDeviceHistory.valid_to.is_(None)) | (SimDeviceHistory.valid_to > an),
        )
    )


async def hat_tak(
    db: AsyncSession,
    *,
    device_id: int,
    sim_id: int,
    clock: Clock,
    is_inferred: bool = False,
    an: datetime | None = None,
) -> SimDeviceHistory:
    """Hattı cihaza takar; varsa önceki dönemi kapatır.

    Çakışma kısıtı zaten koruyor, ama açık dönemi kapatmadan yeni dönem
    açmaya çalışmak kullanıcıya anlamsız bir veritabanı hatası gösterirdi.

    `an` verilirse geçmişe dönük eşleştirme yazılır — sahada yıllardır
    takılı hatları içe aktarırken başlangıç tarihi dosyadan gelir.
    """
    simdi = an if an is not None else clock.now()
    if simdi.tzinfo is None:
        simdi = simdi.replace(tzinfo=UTC)
    for acik in (
        await db.scalars(
            select(SimDeviceHistory).where(
                (SimDeviceHistory.device_id == device_id) | (SimDeviceHistory.sim_id == sim_id),
                SimDeviceHistory.valid_to.is_(None),
            )
        )
    ).all():
        # BAŞLANGICI BİLİNMEYEN dönem kapatılamaz (`ck_sim_cihaz_tarihsiz_acik`):
        # uzunluğu hakkında hiçbir şey söylenemeyen bir aralık geriye dönük
        # hesaplarda sessizce yanlış sonuç verir. Böyle bir satır, yerini yeni
        # eşleşmeye bırakırken SİLİNİR — ve denetim izine yazılır, çünkü
        # "bu hat bu cihazdaydı" bilgisi kaybolur.
        if acik.valid_from is None:
            await db.delete(acik)
            await audit.log(
                db,
                "sim_device_history",
                "tarihsiz.esleme.kaldirildi",
                entity_id=acik.id,
                old_value={"sim_id": acik.sim_id, "device_id": acik.device_id},
                new_value={"neden": "yeni eşleşme yazıldı; başlangıcı bilinmiyordu"},
            )
            continue
        # Sıfır uzunlukta dönem aralık kısıtına çarpar; anlaşılır mesaj ver.
        if acik.valid_from >= simdi:
            raise EslemeHatasi(
                f"Açık eşleşme {acik.valid_from:%d.%m.%Y %H:%M} tarihinde başlıyor; "
                "yeni eşleşme bu andan SONRA olmalı."
            )
        acik.valid_to = simdi

    kayit = SimDeviceHistory(
        sim_id=sim_id, device_id=device_id, valid_from=simdi, is_inferred=is_inferred
    )
    db.add(kayit)
    await db.flush()

    cihaz = await db.get(Device, device_id)
    if cihaz is not None:
        cihaz.current_sim_id = sim_id
    return kayit


# --- Türetilmiş "şu an" alanlarının uzlaştırılması ---------------------------


async def uzlastir(db: AsyncSession, *, yaz: bool = True, user_id: int | None = None) -> dict:
    """`devices.current_*` ve `first_activation_date` alanlarını tarihli
    tablolardan yeniden türetir (plan §3.2).

    Doğruluk kaynağı DAİMA tarihli tablodur; bu alanlar yalnız sorguyu
    ucuzlatmak için var. Göç bunları doldurmamıştı ve sonucu görünürdü:
    garanti başlangıcı `first_activation_date`'ten geldiği için göçten gelen
    her cihazın RMA garanti kararı "belirsiz" çıkıyordu.

    `yaz=False` ile farkı yalnız raporlar — gece koşan iş bunu kullanır.
    """
    from app.models import DeviceCustodyHistory, DeviceVehicleAssignment

    araclar = {
        d.device_id: d
        for d in (
            await db.scalars(
                select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.valid_to.is_(None))
            )
        ).all()
    }
    hatlar = {
        h.device_id: h.sim_id
        for h in (
            await db.scalars(select(SimDeviceHistory).where(SimDeviceHistory.valid_to.is_(None)))
        ).all()
    }
    # Cihaz bir müşteriye araca takılmadan da geçebilir: takip platformundan
    # gelen 10.504 cihazın plakası yok, sahipliği ZİMMETTEN belli. Araç ataması
    # yoksa açık zimmet kullanılır; yoksa bu alan müşteriyi sessizce siliyordu.
    zimmetler = {
        z.device_id: z.account_id
        for z in (
            await db.scalars(
                select(DeviceCustodyHistory).where(DeviceCustodyHistory.valid_to.is_(None))
            )
        ).all()
        if z.account_id is not None
    }
    ilk_montajlar = dict(
        (
            await db.execute(
                select(
                    DeviceVehicleAssignment.device_id,
                    func.min(DeviceVehicleAssignment.valid_from),
                ).group_by(DeviceVehicleAssignment.device_id)
            )
        ).all()
    )

    farklar: list[dict] = []
    cihazlar = (await db.scalars(select(Device).where(Device.is_deleted.is_(False)))).all()

    for c in cihazlar:
        acik = araclar.get(c.id)
        hedef = {
            "current_vehicle_id": acik.vehicle_id if acik else None,
            "current_customer_id": (acik.customer_id if acik else None) or zimmetler.get(c.id),
            "current_sim_id": hatlar.get(c.id),
        }
        # İlk aktivasyon bir kez yazılır ve geri alınmaz: garanti başlangıcı
        # sonradan ileri kaymamalı.
        ilk = ilk_montajlar.get(c.id)
        if c.first_activation_date is None and ilk is not None:
            hedef["first_activation_date"] = ilk.date()

        degisen = {
            alan: (getattr(c, alan), deger)
            for alan, deger in hedef.items()
            if getattr(c, alan) != deger
        }
        if not degisen:
            continue
        farklar.append(
            {
                "device_id": c.id,
                "kimlik": c.imei or c.serial_no,
                "alanlar": {a: {"eski": e, "yeni": y} for a, (e, y) in degisen.items()},
            }
        )
        if yaz:
            for alan, (_eski, yeni_deger) in degisen.items():
                setattr(c, alan, yeni_deger)
            c.updated_by = user_id

    if yaz:
        await db.flush()
    return {"incelenen": len(cihazlar), "farkli": len(farklar), "farklar": farklar[:200]}
