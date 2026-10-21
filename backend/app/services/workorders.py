"""İş emri (= ziyaret) girişi.

Canlı hak ediş uygulamasında **bir kayıt = bir cihaz**. ERP'de ise
**iş emri = bir ziyaret** ve içinde n cihaz kalemi var. Bu ayrım gerçek
veriden geldi: araçların %96,8'inde birden fazla cihaz var ve hak ediş
KALEM başına ödeniyor; tek kayda indirgemek ya işi ya parayı kaybettirirdi.

Bu modül eski formun **giriş hızını** korur: montaj noktası seçilince tarife
ve yetkili doluyor, cihaz modeli seçilince montaj türü geliyor, tek çağrıda
araç + cihaz + dönem + kalem yazılıyor. Farkı, aynı ziyarete ikinci bir cihaz
satırı eklenebilmesi.

**Hiçbir şey hak edişe otomatik girmez.** Kalem `payability` taşır; döküm
üretimi yalnız `ODENECEK` kalemleri alır (bkz. services/settlements.py).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Account,
    Device,
    Product,
    Vehicle,
    WorkOrder,
    WorkOrderItem,
)
from app.models.settlement import is_tipi_coz
from app.models.vehicle import plaka_anahtari
from app.services import assignments as atama_svc
from app.services import devices as cihaz_svc
from app.services import tariffs as tarife_svc
from app.services.normalize import normalize_plate, tr_normkey
from app.services.statemachine import CIHAZ, IzinsizGecis

# İş emri tipi → kalemin varsayılan eylemi. Kullanıcı kalem bazında
# değiştirebilir (sök-tak ziyaretinde bir cihaz sökülüp biri takılır).
TIP_EYLEMI = {
    "MONTAJ": "TAKILDI",
    "SOKUM": "SOKULDU",
    "SOK_TAK": "TAKILDI",
    "DEGISIM": "DEGISTIRILDI",
    "ARIZA": "KONTROL",
    "KESIF": "KONTROL",
    "BAKIM": "KONTROL",
}


# Cihaz rolü → hak ediş iş tipi. Tarife bu tipe göre çözülür; aynı eşleme
# döküm üretiminde de kullanılıyor (settlements._is_tipi) — ikisi ayrışırsa
# önizlenen fiyatla ödenen fiyat tutmazdı.
class IsEmriHatasi(ValueError):
    """İş emri girişi kurallara aykırı."""


@dataclass
class KalemGirdisi:
    kimlik: str | None = None
    product_id: int | None = None
    action: str | None = None
    device_role: str | None = None
    channel_no: int | None = None
    payability: str = "KARAR_BEKLIYOR"
    non_payable_reason: str | None = None
    unit_price: Decimal | None = None
    sim_kimlik: str | None = None


@dataclass
class IsEmriGirdisi:
    type: str
    completed_at: datetime
    assigned_id: int | None = None
    customer_id: int | None = None
    plaka: str | None = None
    sase_no: str | None = None
    ruhsat_no: str | None = None
    odometer_km: int | None = None
    settlement_period: str | None = None
    travel_km: Decimal | None = None
    travel_unit_price: Decimal | None = None
    blokajli: bool = False
    notes: str | None = None
    kalemler: list[KalemGirdisi] = field(default_factory=list)


def donem_cikar(an: datetime) -> str:
    """Varsayılan hak ediş dönemi işin ayıdır — ama BAĞLI DEĞİLDİR.

    Kaynak veride 17 kayıtta ayrışıyor: iş bir ay yapılıp sonraki ayın
    hak edişinde ödenmiş. Bu yüzden alan ayrı ve elle değiştirilebilir.
    """
    return f"{an:%Y-%m}"


async def _wo_no(db: AsyncSession, an: datetime) -> str:
    sira = (await db.scalar(select(func.count()).select_from(WorkOrder))) or 0
    return f"IS{an:%Y}-{sira + 1:05d}"


async def arac_bul_ya_ac(
    db: AsyncSession,
    *,
    plaka: str | None,
    sase_no: str | None = None,
    ruhsat_no: str | None = None,
    customer_id: int | None = None,
    user_id: int | None = None,
) -> Vehicle | None:
    """Plakadan aracı bulur, yoksa açar.

    Arama `plate_key` üzerinden: `normalize_plate` BÜYÜK harf döndürür ama
    anahtar `tr_normkey` ile küçüktür. İkisini karıştırmak mükerrer araç
    üretiyordu (bkz. models/vehicle.plaka_anahtari).
    """
    if not plaka and not sase_no:
        return None

    if plaka:
        try:
            duzgun = normalize_plate(plaka)
        except ValueError:
            duzgun = plaka.strip().upper()  # standart dışı plaka (iş makinesi)
        anahtar = plaka_anahtari(duzgun)
        mevcut = await db.scalar(
            select(Vehicle).where(Vehicle.plate_key == anahtar, Vehicle.is_deleted.is_(False))
        )
        if mevcut is not None:
            # Eksik alanlar tamamlanır, dolu olanlar EZİLMEZ: sahadan gelen
            # yeni bilgi eklensin ama düzeltilmiş kayıt geri alınmasın.
            if sase_no and not mevcut.chassis_no:
                mevcut.chassis_no = sase_no
            if ruhsat_no and not mevcut.registration_no:
                mevcut.registration_no = ruhsat_no
            if customer_id and not mevcut.customer_id:
                mevcut.customer_id = customer_id
            return mevcut
    else:
        duzgun = None

    if not duzgun and sase_no:
        mevcut = await db.scalar(
            select(Vehicle).where(Vehicle.chassis_no == sase_no, Vehicle.is_deleted.is_(False))
        )
        if mevcut is not None:
            return mevcut

    arac = Vehicle(
        plate=duzgun or f"SASE-{sase_no}",
        chassis_no=sase_no,
        registration_no=ruhsat_no,
        customer_id=customer_id,
        created_by=user_id,
    )
    db.add(arac)
    await db.flush()
    return arac


async def cihaz_bul(db: AsyncSession, kimlik: str) -> Device | None:
    temiz = (kimlik or "").strip()
    if not temiz:
        return None
    return await db.scalar(
        select(Device).where(
            or_(Device.imei == temiz, Device.serial_no == temiz), Device.is_deleted.is_(False)
        )
    )


async def cihaz_bul_ya_ac(
    db: AsyncSession, *, kimlik: str, product_id: int | None, user_id: int | None = None
) -> Device:
    """Kimlikten cihazı bulur; yoksa verilen ürün altında açar.

    Ürünün kimlik politikası zorlanır (`devices.kimlik_dogrula`): IMEI tipinde
    bir üründe seri no gibi bir değerle cihaz açılamaz. Sahte kimlik
    üretilmez — kimlik boşsa kalem cihazsız kalır, kayıt yine de durur.
    """
    mevcut = await cihaz_bul(db, kimlik)
    if mevcut is not None:
        return mevcut
    if not product_id:
        raise IsEmriHatasi(f"'{kimlik}' sistemde yok; yeni cihaz açmak için ürün seçilmeli.")

    urun = await db.get(Product, product_id)
    if urun is None or urun.is_deleted:
        raise IsEmriHatasi(f"Ürün bulunamadı: {product_id}")

    imei = seri = None
    if urun.identity_kind == "IMEI":
        imei = kimlik.strip()
    else:
        seri = kimlik.strip()
    try:
        kimlik_tipi = await cihaz_svc.kimlik_dogrula(
            db, product_id=product_id, imei=imei, serial_no=seri
        )
    except ValueError as exc:
        raise IsEmriHatasi(str(exc)) from exc

    cihaz = Device(
        product_id=product_id,
        identity_kind=kimlik_tipi,
        imei=imei,
        serial_no=seri,
        status="STOKTA",
        created_by=user_id,
    )
    db.add(cihaz)
    await db.flush()
    return cihaz


async def _durum_gecir(
    db: AsyncSession, cihaz: Device, hedef: str, clock: Clock, an: datetime | None = None
) -> None:
    """Cihazı hedef duruma taşır; doğrudan geçiş yoksa ARA DURUMLARDAN geçer.

    Stoktaki bir cihaz doğrudan AKTIF olamaz (STOKTA → SEVK_EDILDI → AKTIF).
    Montaj kaydı girerken kullanıcıya "önce sevk edin" dedirtmek, sahadaki
    gerçeği kaydetmeyi zorlaştırırdı; zincir burada otomatik yürütülür ve
    her adım durum geçmişine yazılır.
    """
    if cihaz.status == hedef:
        return
    yol = CIHAZ.yol(cihaz.status, hedef)
    if not yol:
        raise IsEmriHatasi(
            f"{cihaz.imei or cihaz.serial_no}: '{cihaz.status}' durumundan '{hedef}' durumuna "
            "geçilemiyor."
        )
    for adim in yol:
        try:
            await cihaz_svc.durum_degistir(db, cihaz, adim, clock=clock, neden="İş emri", an=an)
        except IzinsizGecis as exc:  # pragma: no cover - `yol` zaten doğruluyor
            raise IsEmriHatasi(str(exc)) from exc


async def olustur(
    db: AsyncSession,
    girdi: IsEmriGirdisi,
    *,
    clock: Clock,
    user_id: int | None = None,
) -> WorkOrder:
    """Ziyareti, araç ve cihaz kayıtlarını, dönemleri tek işlemde yazar."""
    if girdi.type not in TIP_EYLEMI:
        raise IsEmriHatasi(f"Bilinmeyen iş tipi: {girdi.type}")
    if not girdi.kalemler:
        raise IsEmriHatasi("En az bir cihaz kalemi gerekli")

    an = girdi.completed_at
    if an.tzinfo is None:
        an = an.replace(tzinfo=UTC)

    arac = await arac_bul_ya_ac(
        db,
        plaka=girdi.plaka,
        sase_no=girdi.sase_no,
        ruhsat_no=girdi.ruhsat_no,
        customer_id=girdi.customer_id,
        user_id=user_id,
    )

    wo = WorkOrder(
        wo_no=await _wo_no(db, an),
        type=girdi.type,
        status="TAMAMLANDI",
        customer_id=girdi.customer_id,
        vehicle_id=arac.id if arac else None,
        odometer_km=girdi.odometer_km,
        assigned_type="MONTAJ_NOKTASI" if girdi.assigned_id else None,
        assigned_id=girdi.assigned_id,
        completed_at=an,
        settlement_period=girdi.settlement_period or donem_cikar(an),
        travel_km=girdi.travel_km,
        travel_unit_price=girdi.travel_unit_price,
        notes=girdi.notes,
        form_data={"blokajli": girdi.blokajli},
        created_by=user_id,
    )
    db.add(wo)
    await db.flush()

    for sira, k in enumerate(girdi.kalemler, start=1):
        await _kalem_yaz(db, wo, k, sira=sira, arac=arac, clock=clock, user_id=user_id)

    await db.flush()
    return wo


async def _kalem_yaz(
    db: AsyncSession,
    wo: WorkOrder,
    k: KalemGirdisi,
    *,
    sira: int,
    arac: Vehicle | None,
    clock: Clock,
    user_id: int | None,
) -> WorkOrderItem:
    eylem = k.action or TIP_EYLEMI[wo.type]
    cihaz = None
    if k.kimlik:
        cihaz = await cihaz_bul_ya_ac(db, kimlik=k.kimlik, product_id=k.product_id, user_id=user_id)

    urun_id = k.product_id or (cihaz.product_id if cihaz else None)
    urun = await db.get(Product, urun_id) if urun_id else None

    fiyat, kaynak = k.unit_price, "MANUEL"
    if fiyat is None:
        fiyat, kaynak = await tarife_svc.birim_fiyat(
            db,
            partner_id=wo.assigned_id,
            work_type=_is_tipi(wo.type, k.device_role),
            product_group=urun.family if urun else None,
            an=wo.completed_at,
        )

    if k.payability == "ODENMEYECEK" and not k.non_payable_reason:
        raise IsEmriHatasi(
            f"{sira}. kalem ödenmeyecek işaretli; neden seçilmeli "
            "(veritabanı kısıtı gerekçesiz reddediyor)."
        )

    kalem = WorkOrderItem(
        work_order_id=wo.id,
        device_id=cihaz.id if cihaz else None,
        product_id=urun_id,
        action=eylem,
        device_role=k.device_role,
        channel_no=k.channel_no,
        payability=k.payability,
        non_payable_reason=k.non_payable_reason if k.payability == "ODENMEYECEK" else None,
        unit_price=fiyat,
        price_source=kaynak if fiyat is not None else None,
    )
    db.add(kalem)
    await db.flush()

    if cihaz is None:
        return kalem

    # --- Cihaz–araç dönemi ve durum ---
    if eylem in ("TAKILDI", "DEGISTIRILDI") and arac is not None:
        await _durum_gecir(db, cihaz, "AKTIF", clock, an=wo.completed_at)
        await atama_svc.tak(
            db,
            device_id=cihaz.id,
            vehicle_id=arac.id,
            customer_id=wo.customer_id,
            installed_by_type=wo.assigned_type,
            installed_by_id=wo.assigned_id,
            work_order_id=wo.id,
            clock=clock,
            an=wo.completed_at,
        )
    elif eylem == "SOKULDU":
        await atama_svc.sok(
            db,
            device_id=cihaz.id,
            clock=clock,
            an=wo.completed_at,
            neden=f"{wo.wo_no} söküm",
        )
        await _durum_gecir(db, cihaz, "SOKULDU", clock, an=wo.completed_at)

    return kalem


def _is_tipi(wo_tipi: str, rol: str | None) -> str:
    return is_tipi_coz(wo_tipi, rol)


async def imei_cakismasi(db: AsyncSession, kimlik: str) -> dict | None:
    """Bu IMEI şu an başka bir araçta mı?

    Eski uygulamanın en sevilen uyarısı: cihaz söküldüyse sorun yok, ama
    hâlâ takılı görünüyorsa kullanıcı yanlış IMEI yazmış olabilir.
    """
    cihaz = await cihaz_bul(db, kimlik)
    if cihaz is None:
        return None
    acik = await atama_svc.acik_donem(db, cihaz.id)
    if acik is None:
        return None
    arac = await db.get(Vehicle, acik.vehicle_id)
    musteri = await db.get(Account, acik.customer_id) if acik.customer_id else None
    return {
        "device_id": cihaz.id,
        "status": cihaz.status,
        "plaka": arac.plate if arac else None,
        "musteri": musteri.title if musteri else None,
        "takildi": acik.valid_from,
    }


async def montaj_noktalari(db: AsyncSession) -> list[dict]:
    """Form için montaj noktaları: yetkili ve yol birim fiyatıyla birlikte."""
    from app.models import Contact, InstallationPartner

    satirlar = (
        await db.execute(
            select(Account, InstallationPartner)
            .outerjoin(InstallationPartner, InstallationPartner.account_id == Account.id)
            .where(Account.is_montaj_noktasi.is_(True), Account.is_deleted.is_(False))
            .order_by(Account.title)
        )
    ).all()
    idler = [h.id for h, _ in satirlar]
    kisiler: dict[int, Contact] = {}
    if idler:
        for k in (
            await db.scalars(
                select(Contact)
                .where(Contact.account_id.in_(idler))
                .order_by(Contact.is_primary.desc(), Contact.id)
            )
        ).all():
            kisiler.setdefault(k.account_id, k)

    return [
        {
            "id": h.id,
            "unvan": h.title,
            "yetkili": kisiler[h.id].full_name if h.id in kisiler else None,
            "telefon": (kisiler[h.id].phone if h.id in kisiler else None) or h.phone,
            "yol_birim_fiyat": p.km_unit_price if p else None,
        }
        for h, p in satirlar
    ]


async def tarife_onizle(
    db: AsyncSession,
    *,
    partner_id: int | None,
    wo_tipi: str,
    device_role: str | None,
    product_id: int | None,
    an: datetime,
) -> dict:
    """Kalem için tarifeden gelecek fiyat — form doldurulurken gösterilir."""
    urun = await db.get(Product, product_id) if product_id else None
    fiyat, kaynak = await tarife_svc.birim_fiyat(
        db,
        partner_id=partner_id,
        work_type=_is_tipi(wo_tipi, device_role),
        product_group=urun.family if urun else None,
        an=an,
    )
    return {
        "is_tipi": _is_tipi(wo_tipi, device_role),
        "unit_price": fiyat,
        "kaynak": kaynak,
    }


def normalize_anahtar(metin: str) -> str:
    return tr_normkey(metin)
