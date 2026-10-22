"""Kurulu ekipman kütüğü: tek yazma kapısı, geçmiş, seri eşleşmesi (E03, TS-050…057).

**Tek yazma kapısı (E03-D02):** bütün modüller (atölye bul-veya-aç dahil)
ekipmanı yalnız `olustur` / `guncelle` / `durum_degistir` ile yazar. Mükerrer
kuralı, kapsam, müşteri-lokasyon-irtibat tutarlılığı ve denetim izi bu yüzden
TEK yerde durur; ikinci bir yazma yolu ikinci bir mükerrer kuralı demekti.

**Mükerrer anahtarı** (tip, `tr_normkey(marka)`, `normalize_seri(seri)`):
"SMITHS" ile "Smiths Detection" ayrı marka sayılırdı, bu yüzden marka da
normalize edilir. Kısmi UNIQUE indeks KULLANILMAZ: göçteki 38 mükerrer seri
grubu aktif kalmak zorunda. Kontrol `pg_advisory_xact_lock` ile sıraya
sokulur (iki eşzamanlı ekleme ikisi de "yok" görüp ikiz kayıt açmasın) ve
"farklı cihaz" gerekçesiyle (`duplicate_ack_reason`) geçilebilir.

**Denetim izi (E03-03):** irtibat alanları (`contact_id`, `contact_name_raw`)
AYRI satıra `is_personal_data=True` ile yazılır, geri kalanı ayrı satıra
`False`. KVKK maskelemesi satırın bütün değerini sildiği için ikisi aynı
satırda olsaydı hesap anonimleştirildiğinde seri no geçmişi de yok olurdu.

**Kapsam:** ekipman birimli varlıktır (plan §1.2): `kapsam_birim` +
`kapsam_musteri`. Kapsam dışı tek kayıt 404 ve hiçbir yazma yapılmaz.
"Serviste" rozeti saklanmaz; açık ARIZA servis işinden hesaplanır.
"""

from __future__ import annotations

import calendar
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    func,
    literal,
    or_,
    select,
)

from app.models import (
    Account,
    Address,
    Attachment,
    AuditLog,
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenanceVisit,
    Product,
    ServiceEquipment,
    ServiceOrder,
    ServiceOrderSerial,
    ServiceTimeEntry,
    User,
)
from app.models.servis_ekipman import (
    EKIPMAN_DURUMLARI,
    EKIPMAN_TIPLERI,
    GARANTI_KAYNAKLARI,
    model_anahtari,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.permissions import BIRIMLER
from app.services import audit, kvkk
from app.services import settings as ayar_svc
from app.services.accounts import kapsam_disinda_mi, kapsam_musteri
from app.services.normalize import normalize_seri, tr_normkey
from app.services.statemachine import SERVIS_EKIPMANI, IzinsizGecis
from app.services.teknik_servis import ek_kapsam
from app.services.teknik_servis.ana_veri import lokasyon_dogrula, unvan_anahtari
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.kapsam import (
    birim_degisimi_yasak_mi,
    birim_disinda_mi,
    kapsam_birim,
)
from app.services.teknik_servis.yerel_zaman import yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


ENTITY = "service_equipment"

# Toplu işlemlerin üst sınırları (E03-09, E03-11). Excel üst sınırı içe
# aktarma çekirdeğinin `MAKS_SATIR` emsali; aşılırsa "filtreyi daraltın".
TOPLU_UST_SINIR = 200
EXCEL_UST_SINIR = 20_000
GEREKCE_ASGARI = 5

# Denetimde KİŞİSEL VERİ sayılan alanlar — ayrı satıra yazılır (E03-03).
IRTIBAT_ALANLARI = frozenset({"contact_id", "contact_name_raw"})

# `guncelle` ile yazılabilen alanlar. Durum (`lifecycle_status`) yalnız
# `durum_degistir`, aktiflik yalnız `pasife_al/aktife_al` ile değişir: makine
# ve zorunlu gerekçe atlanamasın.
GUNCELLENEBILIR = frozenset(
    {
        "birim",
        "equipment_type",
        "account_id",
        "address_id",
        "contact_id",
        "contact_name_raw",
        "product_id",
        "brand",
        "model",
        "serial_no",
        "zone",
        "delivery_date",
        "install_date",
        "warranty_start",
        "warranty_end",
        "warranty_source",
        "duplicate_ack_reason",
        "notes",
    }
)

DURUM_ETIKETLERI = {
    "KURULU": "Kurulu",
    "KURULUM_BEKLIYOR": "Kurulum bekliyor",
    "DEVRE_DISI": "Devre dışı",
    "HURDA": "Hurda",
    "BILINMIYOR": "Bilinmiyor",
}


class EkipmanHatasi(ServisHatasi):
    """Ekipman kural ihlali → 409. `veri` 409 gövdesine konur (ör. mükerrer kayıtlar)."""

    def __init__(self, mesaj: str, *, veri: dict[str, Any] | None = None):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.veri = veri or {}


class EkipmanBulunamadi(LookupError):
    """Ekipman yok ya da kullanıcının kapsamı dışında → 404 (KD-05)."""


@dataclass
class EkipmanGirdisi:
    birim: str
    equipment_type: str
    account_id: int | None = None
    address_id: int | None = None
    contact_id: int | None = None
    contact_name_raw: str | None = None
    product_id: int | None = None
    brand: str | None = None
    model: str | None = None
    serial_no: str | None = None
    zone: str | None = None
    delivery_date: date | None = None
    install_date: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    warranty_source: str | None = None
    lifecycle_status: str = "BILINMIYOR"
    duplicate_ack_reason: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Eslesme:
    durum: Literal["TEK", "BELIRSIZ", "YOK"]
    ekipman_id: int | None = None


# --- Yardımcılar -----------------------------------------------------------------


def _kirp(deger: Any) -> Any:
    if isinstance(deger, str):
        return deger.strip() or None
    return deger


def _json(deger: Any) -> Any:
    if deger is None or isinstance(deger, str | int | float | bool):
        return deger
    if isinstance(deger, date | datetime):
        return deger.isoformat()
    return str(deger)


def _gerekce(gerekce: str | None) -> str:
    metin = (gerekce or "").strip()
    if len(metin) < GEREKCE_ASGARI:
        raise ServisGirdiHatasi(f"Gerekçe zorunlu (en az {GEREKCE_ASGARI} karakter)")
    return metin


def ay_ekle(baslangic: date, ay: int) -> date:
    """Takvim ayı ekler; ayın son gününü taşmaz (31.01 + 1 ay = 28/29.02)."""
    yil, kalan = divmod(baslangic.month - 1 + ay, 12)
    yil += baslangic.year
    ay_no = kalan + 1
    gun = min(baslangic.day, calendar.monthrange(yil, ay_no)[1])
    return date(yil, ay_no, gun)


def garanti_durumu(ekipman: ServiceEquipment, bugun: date) -> str:
    """Hesaplanan rozet (saklanmaz): GECERLI | BITTI | BILINMIYOR (E03-08)."""
    if ekipman.warranty_end is None:
        return "BILINMIYOR"
    return "GECERLI" if ekipman.warranty_end >= bugun else "BITTI"


def ekipman_kosulu(user: User) -> Callable[[Select], Select]:
    """Liste süzgeci: birim + müşteri kapsamı (plan §1.2)."""

    def _uygula(stmt: Select) -> Select:
        stmt = kapsam_birim(stmt, user, ServiceEquipment.birim, birimsiz_gorunur=False)
        return kapsam_musteri(stmt, user, ServiceEquipment.account_id)

    return _uygula


async def erisim_yok_mu(db: AsyncSession, user: User, ekipman: ServiceEquipment) -> bool:
    """Tek kayıt: kapsam dışı ya da silinmiş mi? (liste süzgecinin aynısı)."""
    if ekipman.is_deleted:
        return True
    if birim_disinda_mi(user, ekipman.birim, birimsiz_gorunur=False):
        return True
    return await kapsam_disinda_mi(db, user, ekipman.account_id)


async def kapsamli_ekipman(db: AsyncSession, user: User, ekipman_id: int) -> ServiceEquipment:
    """Ekipmanı kapsamıyla getirir; yoksa ya da kapsam dışıysa `EkipmanBulunamadi`.

    Kontrol YAZMADAN ÖNCE yapılır: `db.get` kapsamı atlar (canlı
    `test_kapsam_guvenligi` dersi: yanıt 404 ama yazma geçmişti).
    """
    ekipman = await db.get(ServiceEquipment, ekipman_id)
    if ekipman is None or await erisim_yok_mu(db, user, ekipman):
        raise EkipmanBulunamadi("Ekipman bulunamadı")
    return ekipman


def _birim_dogrula(birim: str | None) -> str:
    if birim not in BIRIMLER:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {birim}")
    return birim


def _tip_dogrula(tip: str | None) -> str:
    if tip not in EKIPMAN_TIPLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen ekipman tipi: {tip}")
    return tip


def _tarihleri_dogrula(
    *,
    install_date: date | None,
    warranty_start: date | None,
    warranty_end: date | None,
    warranty_source: str | None,
    bugun: date,
) -> None:
    """Şema CHECK'lerinin Türkçe 400'ü + şemada olmayan "gelecek kurulum" kuralı."""
    if install_date is not None and install_date > bugun:
        raise ServisGirdiHatasi("Kurulum tarihi bugünden ileri olamaz")
    if warranty_start and warranty_end and warranty_end < warranty_start:
        raise ServisGirdiHatasi("Garanti bitişi başlangıçtan önce olamaz")
    if warranty_source is not None and warranty_source not in GARANTI_KAYNAKLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen garanti kaynağı: {warranty_source}")


async def _musteri_dogrula(
    db: AsyncSession,
    user: User,
    account_id: int | None,
    address_id: int | None,
    contact_id: int | None,
) -> None:
    """Hesap-adres-irtibat tutarlılığı (E03-D04) + müşteri kapsamı.

    API ile açılan kayıtta müşteri zorunludur (plan §1.5); tutarlılık tek
    doğrulayıcıdan (`ana_veri.lokasyon_dogrula`, 400) geçer. Kapsam dışı
    müşteri 404: başka temsilcinin carisine kayıt açılamaz.
    """
    if account_id is not None and await kapsam_disinda_mi(db, user, account_id):
        raise EkipmanBulunamadi("Müşteri bulunamadı")
    await lokasyon_dogrula(db, account_id, address_id, contact_id)


async def _urun_dogrula(db: AsyncSession, product_id: int | None) -> Product | None:
    if product_id is None:
        return None
    urun = await db.get(Product, product_id)
    if urun is None or urun.is_deleted:
        raise ServisGirdiHatasi("Ürün bulunamadı")
    return urun


async def mukerrer_kontrol(
    db: AsyncSession,
    user: User,
    *,
    tip: str,
    marka: str | None,
    seri: str | None,
    gerekce: str | None,
    haric_id: int | None = None,
) -> None:
    """Aynı (tip, marka anahtarı, seri anahtarı) ile aktif başka kayıt varsa 409.

    Advisory lock transaction sonuna kadar tutulur: iki eşzamanlı istek aynı
    anahtarda sıraya girer, ikincisi birincinin kaydını görür. Seri no boşsa
    kontrol yapılmaz (kayıt "Seri no eksik" listesine düşer). Kapsam dışı
    mükerrerin kimliği verilmez — 409 gövdesi de bir okuma yoludur.
    """
    seri_anahtari = normalize_seri(seri) if seri else None
    if not seri_anahtari:
        return
    marka_anahtari = (tr_normkey(marka) or None) if marka else None
    kilit = f"svceq|{tip}|{marka_anahtari or ''}|{seri_anahtari}"
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(kilit))))

    stmt = select(ServiceEquipment).where(
        ServiceEquipment.equipment_type == tip,
        ServiceEquipment.brand_key.is_not_distinct_from(marka_anahtari),
        ServiceEquipment.serial_key == seri_anahtari,
        ServiceEquipment.is_active.is_(True),
        ServiceEquipment.is_deleted.is_(False),
    )
    if haric_id is not None:
        stmt = stmt.where(ServiceEquipment.id != haric_id)
    mevcutlar = (await db.scalars(stmt.order_by(ServiceEquipment.id))).all()
    if not mevcutlar or (gerekce or "").strip():
        return
    gorunen = [e.id for e in mevcutlar if not await erisim_yok_mu(db, user, e)]
    if gorunen:
        mesaj = "Aynı seri no ile aktif kayıt var: " + ", ".join(f"#{i}" for i in gorunen)
    else:
        mesaj = "Aynı seri no ile başka bir birimde aktif kayıt var"
    raise EkipmanHatasi(
        mesaj + ". Farklı bir cihazsa gerekçeyle onaylayın.",
        veri={
            "kod": "MUKERRER_SERI",
            "mevcut": gorunen,
            "kapsam_disi": len(mevcutlar) - len(gorunen),
        },
    )


async def _denetim_yaz(
    db: AsyncSession,
    ekipman: ServiceEquipment,
    eylem: str,
    *,
    eski: dict[str, Any] | None,
    yeni: dict[str, Any] | None,
    user_id: int | None,
    ip: str | None = None,
) -> None:
    """Değişikliği İKİ satıra böler: genel alanlar ve irtibat (kişisel veri)."""
    eski = eski or {}
    yeni = yeni or {}
    hesap = {"hesap": ekipman.account_id}
    genel_eski = {k: v for k, v in eski.items() if k not in IRTIBAT_ALANLARI}
    genel_yeni = {k: v for k, v in yeni.items() if k not in IRTIBAT_ALANLARI}
    kisisel_eski = {k: v for k, v in eski.items() if k in IRTIBAT_ALANLARI}
    kisisel_yeni = {k: v for k, v in yeni.items() if k in IRTIBAT_ALANLARI}
    if genel_eski or genel_yeni:
        await audit.log(
            db,
            ENTITY,
            eylem,
            entity_id=ekipman.id,
            old_value={**hesap, **genel_eski} if genel_eski else None,
            new_value={**hesap, **genel_yeni},
            user_id=user_id,
            ip=ip,
        )
    if kisisel_eski or kisisel_yeni:
        await audit.log(
            db,
            ENTITY,
            f"{eylem}.irtibat",
            entity_id=ekipman.id,
            old_value={**hesap, **kisisel_eski} if kisisel_eski else None,
            new_value={**hesap, **kisisel_yeni},
            user_id=user_id,
            ip=ip,
            is_personal_data=True,
        )


# --- Yazma kapısı (TS-050) -------------------------------------------------------


async def olustur(
    db: AsyncSession,
    girdi: EkipmanGirdisi,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceEquipment:
    """Yeni ekipman. Commit ÇAĞIRANIN işidir (denetim aynı transaction'da)."""
    birim = _birim_dogrula(girdi.birim)
    if birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        # Başka birime kayıt açmak kendi kapsamını genişletmek olurdu (plan §1.2).
        raise EkipmanBulunamadi("Birim kapsamınız dışında")
    tip = _tip_dogrula(girdi.equipment_type)
    if girdi.lifecycle_status not in SERVIS_EKIPMANI.baslangiclar:
        secenekler = ", ".join(sorted(SERVIS_EKIPMANI.baslangiclar))
        raise ServisGirdiHatasi(f"Yeni ekipman şu durumlardan biriyle açılır: {secenekler}")
    _tarihleri_dogrula(
        install_date=girdi.install_date,
        warranty_start=girdi.warranty_start,
        warranty_end=girdi.warranty_end,
        warranty_source=girdi.warranty_source,
        bugun=yerel_bugun(clock),
    )
    await _musteri_dogrula(db, user, girdi.account_id, girdi.address_id, girdi.contact_id)
    urun = await _urun_dogrula(db, girdi.product_id)

    marka = _kirp(girdi.brand)
    model = _kirp(girdi.model)
    if urun is not None:
        # Ürün seçildiyse ekranda görünen metin üründen gelir (E03 §1.1).
        marka = marka or _kirp(getattr(urun, "brand", None))
        model = model or urun.name
    seri = _kirp(girdi.serial_no)
    gerekce = _kirp(girdi.duplicate_ack_reason)
    await mukerrer_kontrol(db, user, tip=tip, marka=marka, seri=seri, gerekce=gerekce)

    ekipman = ServiceEquipment(
        birim=birim,
        equipment_type=tip,
        account_id=girdi.account_id,
        address_id=girdi.address_id,
        contact_id=girdi.contact_id,
        contact_name_raw=_kirp(girdi.contact_name_raw),
        product_id=girdi.product_id,
        brand=marka,
        model=model,
        serial_no=seri,
        zone=_kirp(girdi.zone),
        delivery_date=girdi.delivery_date,
        install_date=girdi.install_date,
        warranty_start=girdi.warranty_start,
        warranty_end=girdi.warranty_end,
        warranty_source=girdi.warranty_source
        or ("BELGE" if girdi.warranty_end is not None else None),
        lifecycle_status=girdi.lifecycle_status,
        duplicate_ack_reason=gerekce,
        notes=_kirp(girdi.notes),
        created_by=user.id,
    )
    db.add(ekipman)
    await db.flush()
    yeni = {
        a: _json(getattr(ekipman, a))
        for a in sorted(GUNCELLENEBILIR | {"lifecycle_status"})
        if getattr(ekipman, a) is not None
    }
    await _denetim_yaz(db, ekipman, "olustur", eski=None, yeni=yeni, user_id=user.id, ip=ip)
    return ekipman


async def guncelle(
    db: AsyncSession,
    ekipman: ServiceEquipment,
    degisiklikler: dict,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceEquipment:
    """Kısmi güncelleme. Kapsam (404) ve sürüm (409) kontrolü ÇAĞIRANDA yapılmış olmalı.

    - Birim değişirse hedef birim de kullanıcının kapsamında olmalı (404).
    - Hesap değişirse ve gövdede yeni adres/irtibat yoksa adres ve irtibat
      boşaltılır: eski müşterinin tesisi yeni müşterinin kaydında kalmasın.
    - Tip/marka/seri değişirse mükerrer kontrolü yeniden koşar.
    """
    bilinmeyen = set(degisiklikler) - GUNCELLENEBILIR
    if bilinmeyen:
        if bilinmeyen & {"lifecycle_status", "is_active"}:
            raise ServisGirdiHatasi(
                "Durum ve aktiflik bu uçtan değişmez; durum değiştir / pasife al kullanın"
            )
        raise ServisGirdiHatasi(f"Değiştirilemeyen alan: {', '.join(sorted(bilinmeyen))}")
    veri = {k: _kirp(v) for k, v in degisiklikler.items()}

    if "birim" in veri:
        _birim_dogrula(veri["birim"])
        if birim_degisimi_yasak_mi(user, ekipman.birim, veri["birim"]):
            raise EkipmanBulunamadi("Birim kapsamınız dışında")
    if "equipment_type" in veri:
        _tip_dogrula(veri["equipment_type"])

    hesap_degisti = "account_id" in veri and veri["account_id"] != ekipman.account_id
    if hesap_degisti:
        veri.setdefault("address_id", None)
        veri.setdefault("contact_id", None)
    if (
        hesap_degisti
        or (
            "address_id" in veri and veri["address_id"] != ekipman.address_id and veri["address_id"]
        )
        or (
            "contact_id" in veri and veri["contact_id"] != ekipman.contact_id and veri["contact_id"]
        )
    ):
        await _musteri_dogrula(
            db,
            user,
            veri.get("account_id", ekipman.account_id),
            veri.get("address_id", ekipman.address_id),
            veri.get("contact_id", ekipman.contact_id),
        )
    if "product_id" in veri and veri["product_id"] != ekipman.product_id:
        await _urun_dogrula(db, veri["product_id"])

    def son(alan: str) -> Any:
        return veri[alan] if alan in veri else getattr(ekipman, alan)

    _tarihleri_dogrula(
        install_date=son("install_date"),
        warranty_start=son("warranty_start"),
        warranty_end=son("warranty_end"),
        warranty_source=son("warranty_source"),
        bugun=yerel_bugun(clock),
    )
    kimlik_degisti = any(
        a in veri and veri[a] != getattr(ekipman, a)
        for a in ("equipment_type", "brand", "serial_no")
    )
    if kimlik_degisti and ekipman.is_active:
        await mukerrer_kontrol(
            db,
            user,
            tip=son("equipment_type"),
            marka=son("brand"),
            seri=son("serial_no"),
            gerekce=son("duplicate_ack_reason"),
            haric_id=ekipman.id,
        )

    eski: dict[str, Any] = {}
    yeni: dict[str, Any] = {}
    for alan, deger in veri.items():
        mevcut = getattr(ekipman, alan)
        if mevcut == deger:
            continue
        eski[alan] = _json(mevcut)
        yeni[alan] = _json(deger)
        setattr(ekipman, alan, deger)
    if not yeni:
        return ekipman
    ekipman.updated_by = user.id
    await db.flush()
    await _denetim_yaz(db, ekipman, "guncelle", eski=eski, yeni=yeni, user_id=user.id, ip=ip)
    return ekipman


async def pasife_al(
    db: AsyncSession,
    ekipman: ServiceEquipment,
    gerekce: str | None,
    *,
    user: User,
    ip: str | None = None,
) -> ServiceEquipment:
    """Kaydı geçersiz kılar (mükerrer/hatalı kayıt). Fiziksel durumdan AYRIDIR."""
    metin = _gerekce(gerekce)
    if not ekipman.is_active:
        raise EkipmanHatasi("Ekipman zaten pasif")
    ekipman.is_active = False
    ekipman.updated_by = user.id
    await db.flush()
    await _denetim_yaz(
        db,
        ekipman,
        "pasif",
        eski={"is_active": True},
        yeni={"is_active": False, "gerekce": metin},
        user_id=user.id,
        ip=ip,
    )
    return ekipman


async def aktife_al(
    db: AsyncSession,
    ekipman: ServiceEquipment,
    gerekce: str | None,
    *,
    user: User,
    ip: str | None = None,
    mukerrer_gerekcesi: str | None = None,
) -> ServiceEquipment:
    """Pasif kaydı yeniden geçerli yapar; mükerrer kuralı yeniden sınanır."""
    metin = _gerekce(gerekce)
    if ekipman.is_active:
        raise EkipmanHatasi("Ekipman zaten aktif")
    if ekipman.merged_into_id is not None:
        raise EkipmanHatasi(
            f"Kayıt #{ekipman.merged_into_id} ile birleştirilmiş; aktifleştirilemez"
        )
    ack = _kirp(mukerrer_gerekcesi) or ekipman.duplicate_ack_reason
    await mukerrer_kontrol(
        db,
        user,
        tip=ekipman.equipment_type,
        marka=ekipman.brand,
        seri=ekipman.serial_no,
        gerekce=ack,
        haric_id=ekipman.id,
    )
    if ack and ack != ekipman.duplicate_ack_reason:
        ekipman.duplicate_ack_reason = ack
    ekipman.is_active = True
    ekipman.updated_by = user.id
    await db.flush()
    await _denetim_yaz(
        db,
        ekipman,
        "aktif",
        eski={"is_active": False},
        yeni={"is_active": True, "gerekce": metin},
        user_id=user.id,
        ip=ip,
    )
    return ekipman


# --- Yaşam döngüsü (TS-055) ------------------------------------------------------


async def durum_degistir(
    db: AsyncSession,
    ekipman: ServiceEquipment,
    hedef: str,
    *,
    gerekce: str | None,
    tarih: date | None,
    clock: Clock,
    user: User,
    ip: str | None = None,
) -> ServiceEquipment:
    """Durum yalnız `SERVIS_EKIPMANI` makinesiyle ve GEREKÇEYLE değişir.

    Gerekçesiz istek 400 (kayıt değişmez), kural dışı geçiş 409. KURULU'ya
    geçişte kurulum tarihi boşsa istekteki tarih (yoksa yerel bugün) yazılır.
    DEVRE_DISI/HURDA'ya geçiş açık servis işlerini SİLMEZ; çağıran
    `acik_is_uyarilari` ile kullanıcıyı uyarır.
    """
    if hedef not in EKIPMAN_DURUMLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen durum: {hedef}")
    metin = _gerekce(gerekce)
    try:
        SERVIS_EKIPMANI.dogrula(ekipman.lifecycle_status, hedef)
    except IzinsizGecis as exc:
        raise EkipmanHatasi(str(exc)) from exc
    bugun = yerel_bugun(clock)
    if tarih is not None and tarih > bugun:
        raise ServisGirdiHatasi("Durum tarihi bugünden ileri olamaz")

    eski: dict[str, Any] = {"lifecycle_status": ekipman.lifecycle_status}
    yeni: dict[str, Any] = {"lifecycle_status": hedef, "gerekce": metin}
    if tarih is not None:
        yeni["tarih"] = tarih.isoformat()
    if hedef == "KURULU" and ekipman.install_date is None:
        ekipman.install_date = tarih or bugun
        eski["install_date"] = None
        yeni["install_date"] = ekipman.install_date.isoformat()
    ekipman.lifecycle_status = hedef
    ekipman.updated_by = user.id
    await db.flush()
    await _denetim_yaz(db, ekipman, "durum.degistir", eski=eski, yeni=yeni, user_id=user.id, ip=ip)
    return ekipman


async def toplu_durum_degistir(
    db: AsyncSession,
    ekipman_idleri: Iterable[int],
    hedef: str,
    *,
    gerekce: str | None,
    clock: Clock,
    user: User,
    ip: str | None = None,
) -> list[ServiceEquipment]:
    """Seçili ekipmanların durumunu tek gerekçeyle değiştirir — HEPSİ ya da HİÇBİRİ.

    Kapsam dışı/olmayan kimlik varsa 404, kural dışı geçiş varsa 409 + liste;
    her iki durumda hiçbir kayıt değişmez (kontrol yazmadan önce).
    """
    idler = list(dict.fromkeys(ekipman_idleri))
    if not idler:
        raise ServisGirdiHatasi("En az bir ekipman seçin")
    if len(idler) > TOPLU_UST_SINIR:
        raise ServisGirdiHatasi(f"Toplu işlemde en çok {TOPLU_UST_SINIR} ekipman seçilebilir")
    if hedef not in EKIPMAN_DURUMLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen durum: {hedef}")
    _gerekce(gerekce)
    kayitlar = [await kapsamli_ekipman(db, user, i) for i in idler]
    uymayan = [e for e in kayitlar if not SERVIS_EKIPMANI.izinli_mi(e.lifecycle_status, hedef)]
    if uymayan:
        liste = ", ".join(
            f"#{e.id} ({DURUM_ETIKETLERI.get(e.lifecycle_status, e.lifecycle_status)})"
            for e in uymayan
        )
        raise EkipmanHatasi(
            f"Şu ekipmanlar '{DURUM_ETIKETLERI[hedef]}' durumuna geçemez: {liste}",
            veri={"kod": "GECERSIZ_GECIS", "ekipmanlar": [e.id for e in uymayan]},
        )
    for e in kayitlar:
        await durum_degistir(
            db, e, hedef, gerekce=gerekce, tarih=None, clock=clock, user=user, ip=ip
        )
    return kayitlar


def _acik_ariza_kosulu() -> ColumnElement[bool]:
    return and_(
        ServiceOrder.tur == "ARIZA",
        ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
        ServiceOrder.is_deleted.is_(False),
    )


async def servistekiler(db: AsyncSession, ekipman_idleri: Iterable[int]) -> set[int]:
    """ "Serviste" rozeti: açık ARIZA servis işi olan ekipmanlar (hesaplanır, saklanmaz)."""
    idler = list(ekipman_idleri)
    if not idler:
        return set()
    stmt = select(ServiceOrder.equipment_id).where(
        ServiceOrder.equipment_id.in_(idler), _acik_ariza_kosulu()
    )
    return {i for i in (await db.scalars(stmt)).all() if i is not None}


async def acik_is_sayisi(db: AsyncSession, ekipman_id: int) -> int:
    """Ekipmana bağlı açık servis işi sayısı (kart özeti)."""
    return int(
        await db.scalar(
            select(func.count(ServiceOrder.id)).where(
                ServiceOrder.equipment_id == ekipman_id,
                ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
                ServiceOrder.is_deleted.is_(False),
            )
        )
        or 0
    )


async def acik_is_uyarilari(db: AsyncSession, ekipman: ServiceEquipment) -> list[str]:
    """DEVRE_DISI/HURDA sonrası: açık servis işleri silinmez, kullanıcı uyarılır."""
    if ekipman.lifecycle_status not in ("DEVRE_DISI", "HURDA"):
        return []
    nolar = (
        await db.scalars(
            select(ServiceOrder.so_no)
            .where(
                ServiceOrder.equipment_id == ekipman.id,
                ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
                ServiceOrder.is_deleted.is_(False),
            )
            .order_by(ServiceOrder.id)
        )
    ).all()
    if not nolar:
        return []
    return [f"Açık {len(nolar)} servis işi var: {', '.join(nolar[:10])}"]


# --- Seri ile eşleşme (TS-054) ---------------------------------------------------


async def seri_ile_bul(
    db: AsyncSession,
    ham_seri: str,
    *,
    account_id: int | None = None,
    user: User | None = None,
) -> Eslesme:
    """Tek normalize seri (`normalize_seri`) ile aktif ekipman eşleşmesi.

    `user` verilirse yalnız KAPSAM İÇİ kayıtlar sayılır: başka birimin kaydı
    ne öneri verir ne de "belirsiz" sonucuyla varlığını sızdırır. `account_id`
    verilirse (saha farkı otomatik bağlama) aynı müşteri şartı aranır.
    """
    anahtar = normalize_seri(ham_seri) if ham_seri else ""
    if not anahtar:
        return Eslesme("YOK")
    stmt = select(ServiceEquipment.id).where(
        ServiceEquipment.serial_key == anahtar,
        ServiceEquipment.is_active.is_(True),
        ServiceEquipment.is_deleted.is_(False),
    )
    if account_id is not None:
        stmt = stmt.where(ServiceEquipment.account_id == account_id)
    if user is not None:
        stmt = ekipman_kosulu(user)(stmt)
    idler = (await db.scalars(stmt.limit(2))).all()
    if len(idler) == 1:
        return Eslesme("TEK", idler[0])
    return Eslesme("BELIRSIZ") if idler else Eslesme("YOK")


# --- Sözleşme bağı (TS-056) ------------------------------------------------------


def _aktif_kalem_kosulu(an: datetime) -> ColumnElement[bool]:
    """ "Bağlı" = silinmemiş, tarih aralığı şu anı kapsayan, sözleşmesi pasif olmayan kalem."""
    return and_(
        MaintenanceContractItem.is_deleted.is_(False),
        MaintenanceContractItem.equipment_id.is_not(None),
        or_(MaintenanceContractItem.valid_from.is_(None), MaintenanceContractItem.valid_from <= an),
        or_(MaintenanceContractItem.valid_to.is_(None), MaintenanceContractItem.valid_to > an),
        MaintenanceContractItem.contract_id.in_(
            select(MaintenanceContract.id).where(
                MaintenanceContract.is_deleted.is_(False), MaintenanceContract.status != "PASIF"
            )
        ),
    )


async def aktif_sozlesmeler(
    db: AsyncSession, ekipman_idleri: Iterable[int], an: datetime
) -> dict[int, list[dict[str, Any]]]:
    """Ekipman başına aktif sözleşme kalemleri (`maintenance_contract_items`, salt okunur)."""
    idler = list(ekipman_idleri)
    if not idler:
        return {}
    stmt = (
        select(MaintenanceContractItem, MaintenanceContract.contract_no)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenanceContractItem.contract_id)
        .where(MaintenanceContractItem.equipment_id.in_(idler), _aktif_kalem_kosulu(an))
        .order_by(MaintenanceContractItem.id)
    )
    sonuc: dict[int, list[dict[str, Any]]] = {}
    for kalem, no in (await db.execute(stmt)).all():
        sonuc.setdefault(kalem.equipment_id, []).append(
            {"kalem_id": kalem.id, "sozlesme_id": kalem.contract_id, "sozlesme_no": no}
        )
    return sonuc


async def bagli_ekipman_sayilari(
    db: AsyncSession, sozlesme_idleri: Iterable[int], an: datetime
) -> dict[int, int]:
    """Sözleşme listesinin "Bağlı ekipman" sütunu (D1-F çağırır).

    Sözleşmenin plan/adet alanından AYRI gösterilir: "9 X-Ray sözleşmesi,
    7 bağlı ekipman" farkı görünür kalsın (E03-08).
    """
    idler = list(sozlesme_idleri)
    if not idler:
        return {}
    stmt = (
        select(MaintenanceContractItem.contract_id, func.count(MaintenanceContractItem.id))
        .where(MaintenanceContractItem.contract_id.in_(idler), _aktif_kalem_kosulu(an))
        .group_by(MaintenanceContractItem.contract_id)
    )
    return {k: int(n) for k, n in (await db.execute(stmt)).all()}


# --- Liste, KPI, Excel (TS-053) -----------------------------------------------------


@dataclass
class EkipmanSuzgeci:
    q: str | None = None
    birim: str | None = None
    tip: str | None = None
    marka: str | None = None
    model: str | None = None
    durum: str | None = None
    hesap_id: int | None = None
    lokasyon_id: int | None = None
    sozlesme_id: int | None = None
    garanti: str | None = None
    seri_eksik: bool | None = None
    lokasyonsuz: bool = False
    sozlesmesiz: bool = False
    serviste: bool | None = None
    pasifler_dahil: bool = False
    kpi: str | None = None
    idler: list[int] | None = field(default=None)


@dataclass(frozen=True)
class KpiTanimi:
    kod: str
    baslik: str
    tanim: str


# Kutu sırası ekrandaki sıradır. Her kutunun sayısı `?kpi=<kod>` listesinin
# `X-Toplam-Kayit`'ıdır — ikisi aynı `liste_sorgusu`ndan gelir (sayı = liste).
KPI_TANIMLARI: tuple[KpiTanimi, ...] = (
    KpiTanimi("toplam", "Toplam", "Kapsamınızdaki aktif ekipman kayıtları"),
    KpiTanimi("xray", "X-Ray", "Tipi X-Ray olan aktif ekipmanlar"),
    KpiTanimi("kapi_dedektoru", "Kapı Dedektörü", "Kapı tipi metal dedektörleri"),
    KpiTanimi("seri_mevcut", "Seri No Mevcut", "Seri numarası girilmiş kayıtlar"),
    KpiTanimi("seri_eksik", "Seri No Eksik", "Seri numarası boş kayıtlar"),
    KpiTanimi("garanti_bilinmiyor", "Garanti Bilinmiyor", "Garanti bitiş tarihi girilmemiş"),
    KpiTanimi("serviste", "Serviste", "Açık arıza servis işi olan ekipmanlar"),
)
KPI_KODLARI = frozenset(k.kod for k in KPI_TANIMLARI)
GARANTI_SUZGECLERI = ("GECERLI", "BITTI", "BILINMIYOR")


def _kpi_kosulu(kod: str) -> ColumnElement[bool] | None:
    if kod == "toplam":
        return None
    if kod == "xray":
        return ServiceEquipment.equipment_type == "XRAY"
    if kod == "kapi_dedektoru":
        return ServiceEquipment.equipment_type == "KAPI_DEDEKTORU"
    if kod == "seri_mevcut":
        return ServiceEquipment.serial_key.is_not(None)
    if kod == "seri_eksik":
        return ServiceEquipment.serial_key.is_(None)
    if kod == "garanti_bilinmiyor":
        return ServiceEquipment.warranty_end.is_(None)
    if kod == "serviste":
        return ServiceEquipment.id.in_(
            select(ServiceOrder.equipment_id).where(
                ServiceOrder.equipment_id.is_not(None), _acik_ariza_kosulu()
            )
        )
    raise ServisGirdiHatasi(f"Bilinmeyen KPI kodu: {kod}")


def liste_sorgusu(user: User, s: EkipmanSuzgeci, *, bugun: date, an: datetime) -> Select:
    """Liste, KPI özeti ve Excel'in ORTAK sorgusu (sayı = liste = Excel).

    Seçilen sütunlar: ekipman, müşteri unvanı, tesis adı, il. Müşteri ve tesis
    dış birleşimle gelir (1:1, sayımı çoğaltmaz).
    """
    stmt = (
        select(ServiceEquipment, Account.title, Address.site_name, Address.city)
        .outerjoin(Account, Account.id == ServiceEquipment.account_id)
        .outerjoin(Address, Address.id == ServiceEquipment.address_id)
        .where(ServiceEquipment.is_deleted.is_(False))
    )
    stmt = ekipman_kosulu(user)(stmt)
    if not s.pasifler_dahil:
        stmt = stmt.where(ServiceEquipment.is_active.is_(True))
    if s.idler is not None:
        stmt = stmt.where(ServiceEquipment.id.in_(s.idler or [0]))
    if s.birim:
        stmt = stmt.where(ServiceEquipment.birim == _birim_dogrula(s.birim))
    if s.tip:
        stmt = stmt.where(ServiceEquipment.equipment_type == _tip_dogrula(s.tip))
    if s.marka:
        stmt = stmt.where(ServiceEquipment.brand_key.contains(tr_normkey(s.marka)))
    if s.model:
        anahtar = model_anahtari(s.model)
        if anahtar:
            stmt = stmt.where(ServiceEquipment.model_key.contains(anahtar))
    if s.durum:
        if s.durum not in EKIPMAN_DURUMLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen durum: {s.durum}")
        stmt = stmt.where(ServiceEquipment.lifecycle_status == s.durum)
    if s.hesap_id is not None:
        stmt = stmt.where(ServiceEquipment.account_id == s.hesap_id)
    if s.lokasyon_id is not None:
        stmt = stmt.where(ServiceEquipment.address_id == s.lokasyon_id)
    if s.sozlesme_id is not None:
        stmt = stmt.where(
            ServiceEquipment.id.in_(
                select(MaintenanceContractItem.equipment_id).where(
                    MaintenanceContractItem.contract_id == s.sozlesme_id, _aktif_kalem_kosulu(an)
                )
            )
        )
    if s.sozlesmesiz:
        stmt = stmt.where(
            ServiceEquipment.id.not_in(
                select(MaintenanceContractItem.equipment_id).where(_aktif_kalem_kosulu(an))
            )
        )
    if s.garanti:
        if s.garanti not in GARANTI_SUZGECLERI:
            raise ServisGirdiHatasi(f"Bilinmeyen garanti süzgeci: {s.garanti}")
        if s.garanti == "BILINMIYOR":
            stmt = stmt.where(ServiceEquipment.warranty_end.is_(None))
        elif s.garanti == "GECERLI":
            stmt = stmt.where(ServiceEquipment.warranty_end >= bugun)
        else:
            stmt = stmt.where(ServiceEquipment.warranty_end < bugun)
    if s.seri_eksik is not None:
        stmt = stmt.where(
            ServiceEquipment.serial_key.is_(None)
            if s.seri_eksik
            else ServiceEquipment.serial_key.is_not(None)
        )
    if s.lokasyonsuz:
        stmt = stmt.where(ServiceEquipment.address_id.is_(None))
    if s.serviste is not None:
        kosul = _kpi_kosulu("serviste")
        stmt = stmt.where(kosul if s.serviste else ~kosul)  # type: ignore[operator]
    if s.kpi:
        kosul = _kpi_kosulu(s.kpi)
        if kosul is not None:
            stmt = stmt.where(kosul)
    if s.q and s.q.strip():
        stmt = stmt.where(_arama_kosulu(s.q))
    return stmt.order_by(ServiceEquipment.id.desc())


def _arama_kosulu(q: str) -> ColumnElement[bool]:
    """Seri (normalize), model anahtarı, müşteri unvanı, tesis adı, bölge."""
    metin = q.strip()
    kosullar: list[ColumnElement[bool]] = [ServiceEquipment.zone.ilike(f"%{metin}%")]
    seri = normalize_seri(metin)
    if seri:
        kosullar.append(ServiceEquipment.serial_key.contains(seri))
    model = model_anahtari(metin)
    if model:
        kosullar.append(ServiceEquipment.model_key.contains(model))
    unvan = tr_normkey(metin)
    if unvan:
        kosullar.append(
            ServiceEquipment.account_id.in_(
                select(Account.id).where(Account.title_key.contains(unvan))
            )
        )
    tesis = unvan_anahtari(metin)
    if tesis:
        kosullar.append(
            ServiceEquipment.address_id.in_(
                select(Address.id).where(Address.site_key.contains(tesis))
            )
        )
    return or_(*kosullar)


async def say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def ozet(db: AsyncSession, user: User, clock: Clock) -> list[dict[str, Any]]:
    """KPI kutuları: her biri `?kpi=<kod>` listesinin toplamıyla aynı sorgu."""
    bugun, an = yerel_bugun(clock), clock.now()
    sonuc = []
    for k in KPI_TANIMLARI:
        stmt = liste_sorgusu(user, EkipmanSuzgeci(kpi=k.kod), bugun=bugun, an=an)
        sonuc.append(
            {"kod": k.kod, "baslik": k.baslik, "tanim": k.tanim, "deger": await say(db, stmt)}
        )
    return sonuc


# --- Toplu garanti (TS-056) ------------------------------------------------------


async def toplu_garanti(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    idler: list[int] | None = None,
    birim: str | None = None,
    uygula: bool = False,
    ip: str | None = None,
) -> dict[str, Any]:
    """Garanti bitişi boş kayıtlara garanti hesaplar — önizleme ve uygulama AYNI fonksiyon.

    Başlangıç = kurulum tarihi, yoksa teslim tarihi; süre = ürün kartındaki
    `warranty_months`, ürün yoksa `servis_varsayilan_garanti_ay`. Kaynak
    `HESAPLANDI` yazılır; `BELGE` kaynaklı kayda dokunulmaz. Başlangıç tarihi
    olmayan kayıt hesaplanmaz (uydurma tarih yok), ayrıca sayılır.
    """
    if idler is not None and len(idler) > EXCEL_UST_SINIR:
        raise ServisGirdiHatasi("Seçim çok büyük")
    stmt = select(ServiceEquipment, Product.warranty_months).outerjoin(
        Product, Product.id == ServiceEquipment.product_id
    )
    stmt = ekipman_kosulu(user)(stmt).where(
        ServiceEquipment.is_deleted.is_(False),
        ServiceEquipment.is_active.is_(True),
        ServiceEquipment.warranty_end.is_(None),
        or_(
            ServiceEquipment.warranty_source.is_(None), ServiceEquipment.warranty_source != "BELGE"
        ),
    )
    if idler is not None:
        stmt = stmt.where(ServiceEquipment.id.in_(idler or [0]))
    if birim:
        stmt = stmt.where(ServiceEquipment.birim == _birim_dogrula(birim))
    varsayilan_ay = int(await ayar_svc.get(db, "servis_varsayilan_garanti_ay"))
    hesaplanan: list[tuple[ServiceEquipment, date, date, int]] = []
    tarihsiz = 0
    for ekipman, urun_ayi in (await db.execute(stmt.order_by(ServiceEquipment.id))).all():
        baslangic = ekipman.install_date or ekipman.delivery_date
        if baslangic is None:
            tarihsiz += 1
            continue
        ay = int(urun_ayi) if (ekipman.product_id is not None and urun_ayi) else varsayilan_ay
        hesaplanan.append((ekipman, baslangic, ay_ekle(baslangic, ay), ay))

    if uygula:
        for ekipman, baslangic, bitis, ay in hesaplanan:
            eski = {
                "warranty_start": _json(ekipman.warranty_start),
                "warranty_end": None,
                "warranty_source": ekipman.warranty_source,
            }
            ekipman.warranty_start = ekipman.warranty_start or baslangic
            ekipman.warranty_end = bitis
            ekipman.warranty_source = "HESAPLANDI"
            ekipman.updated_by = user.id
            await db.flush()
            await _denetim_yaz(
                db,
                ekipman,
                "garanti.toplu",
                eski=eski,
                yeni={
                    "warranty_start": _json(ekipman.warranty_start),
                    "warranty_end": bitis.isoformat(),
                    "warranty_source": "HESAPLANDI",
                    "ay": ay,
                },
                user_id=user.id,
                ip=ip,
            )
    return {
        "uygulandi": uygula,
        "satir_sayisi": len(hesaplanan),
        "baslangic_tarihsiz": tarihsiz,
        "ornekler": [
            {
                "id": e.id,
                "seri": e.serial_no,
                "baslangic": b.isoformat(),
                "bitis": bt.isoformat(),
                "ay": ay,
            }
            for e, b, bt, ay in hesaplanan[:50]
        ],
    }


# --- Birleşik geçmiş (TS-052) ----------------------------------------------------

# Ek olay kaynakları (Dalga 2: atölye, parça). Kaynak fonksiyonu
# `async fn(db, ekipman, user) -> list[dict]` döner; her satır en az
# `{tarih, tur, baslik, kaynak, kaynak_id}` taşır, isterse `maliyet`.
# `maliyet` anahtarı `sees_cost` olmayan kullanıcıda burada SİLİNİR —
# kaynak modülün hatırlamasına bırakılmaz.
GecmisKaynagi = Callable[["AsyncSession", ServiceEquipment, User], Awaitable[list[dict[str, Any]]]]
GECMIS_KAYNAKLARI: list[GecmisKaynagi] = []
MALIYET_ANAHTARLARI = ("maliyet", "birim_maliyet", "toplam_maliyet")


def gecmis_kaynagi_kaydet(fn: GecmisKaynagi) -> GecmisKaynagi:
    """Ekipman geçmişine yeni olay kaynağı ekler (idempotent; Dalga 2 modülleri)."""
    if fn not in GECMIS_KAYNAKLARI:
        GECMIS_KAYNAKLARI.append(fn)
    return fn


async def sure_ozetleri(db: AsyncSession, so_idleri: Iterable[int]) -> dict[int, int]:
    """İş başına kişi-dakika (MOLA hariç, iptal edilmemiş, kapanmış bölümler).

    Kayıt yoksa sözlükte ANAHTAR YOKTUR: çağıran bunu "süre eksik" okur,
    sıfır değil (plan TS-075: `or 0` yasağı).
    """
    idler = list(so_idleri)
    if not idler:
        return {}
    dakika = func.sum(
        func.extract("epoch", ServiceTimeEntry.ended_at - ServiceTimeEntry.started_at) / 60
    )
    stmt = (
        select(ServiceTimeEntry.service_order_id, dakika)
        .where(
            ServiceTimeEntry.service_order_id.in_(idler),
            ServiceTimeEntry.ended_at.is_not(None),
            ServiceTimeEntry.iptal_turu.is_(None),
            ServiceTimeEntry.faaliyet != "MOLA",
        )
        .group_by(ServiceTimeEntry.service_order_id)
    )
    return {
        so: int(round(float(dk))) for so, dk in (await db.execute(stmt)).all() if dk is not None
    }


async def _servis_isleri(
    db: AsyncSession, ekipman: ServiceEquipment, user: User
) -> list[dict[str, Any]]:
    """Ekipmana bağlı servis işleri (KIMLIK) + seri metniyle eşleşen eski işler (METIN)."""
    kimlik = select(ServiceOrder, literal("KIMLIK").label("eslesme")).where(
        ServiceOrder.equipment_id == ekipman.id, ServiceOrder.is_deleted.is_(False)
    )
    satirlar = list((await db.execute(kimlik)).all())
    if ekipman.serial_key:
        metin = select(ServiceOrder, literal("METIN").label("eslesme")).where(
            ServiceOrder.equipment_id.is_(None),
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.birim == ekipman.birim,
            ServiceOrder.id.in_(
                select(ServiceOrderSerial.service_order_id).where(
                    ServiceOrderSerial.seri_norm == ekipman.serial_key,
                    ServiceOrderSerial.is_active.is_(True),
                )
            ),
        )
        if ekipman.account_id is not None:
            metin = metin.where(ServiceOrder.customer_id == ekipman.account_id)
        satirlar += list((await db.execute(metin)).all())
    sureler = await sure_ozetleri(db, [so.id for so, _ in satirlar])
    sonuc = []
    for so, eslesme in satirlar:
        sure = sureler.get(so.id)
        sonuc.append(
            {
                "tarih": so.reported_at or so.created_at,
                "tur": "PB" if so.tur == "PB" else "SERVIS_ISI",
                "baslik": f"{so.so_no} · {so.tur} · {so.konu}",
                "durum": so.status,
                "kaynak": "service_orders",
                "kaynak_id": so.id,
                "sure_dakika": sure,
                "sure_eksik": sure is None,
                "eslesme": eslesme,
            }
        )
    return sonuc


async def _bakim_ziyaretleri(
    db: AsyncSession, ekipman: ServiceEquipment, user: User
) -> list[dict[str, Any]]:
    """PB işlerinin değişmez ziyaret satırları (`maintenance_visits`, salt okunur)."""
    stmt = (
        select(MaintenanceVisit, ServiceOrder.so_no)
        .join(ServiceOrder, ServiceOrder.id == MaintenanceVisit.service_order_id)
        .where(ServiceOrder.equipment_id == ekipman.id, ServiceOrder.is_deleted.is_(False))
    )
    return [
        {
            "tarih": z.visited_at,
            "tur": "BAKIM",
            "baslik": " · ".join(
                filter(
                    None,
                    [
                        so_no,
                        "Bakım ziyareti" if z.tur == "TAMAMLAMA" else "Yeniden açma",
                        z.bakim_sonucu,
                    ],
                )
            ),
            "kaynak": "maintenance_visits",
            "kaynak_id": z.id,
            "sure_dakika": None,
            "sure_eksik": False,
            "eslesme": "KIMLIK",
        }
        for z, so_no in (await db.execute(stmt)).all()
    ]


_EYLEM_ETIKETLERI = {
    "olustur": "Kayıt açıldı",
    "guncelle": "Kayıt düzenlendi",
    "durum.degistir": "Durum değişti",
    "pasif": "Pasife alındı",
    "aktif": "Aktifleştirildi",
    "garanti.toplu": "Garanti hesaplandı",
    "birlestir": "Birleştirildi",
    "saha.uygula": "Saha farkı uygulandı",
    "saha.yoksay": "Saha farkı yok sayıldı",
}


async def _kutuk_degisiklikleri(
    db: AsyncSession, ekipman: ServiceEquipment, user: User
) -> list[dict[str, Any]]:
    stmt = select(AuditLog).where(
        AuditLog.entity == ENTITY,
        AuditLog.entity_id == str(ekipman.id),
        AuditLog.is_personal_data.is_(False),
        AuditLog.action != "disaaktar",
    )
    return [
        {
            "tarih": k.created_at,
            "tur": "KUTUK",
            "baslik": _EYLEM_ETIKETLERI.get(k.action, k.action),
            "kaynak": "audit_logs",
            "kaynak_id": k.id,
            "sure_dakika": None,
            "sure_eksik": False,
            "eslesme": "KIMLIK",
        }
        for k in (await db.scalars(stmt)).all()
    ]


async def gecmis(db: AsyncSession, ekipman: ServiceEquipment, user: User) -> list[dict[str, Any]]:
    """Birleşik geçmiş (servis işi, bakım, kütük; Dalga 2'de atölye/parça). Tek fonksiyon.

    Tarih sırası YENİDEN ESKİYE. Maliyet anahtarları `sees_cost` (`maliyet.gor`)
    olmayan kullanıcıda satırdan tamamen çıkarılır — `None` değil, anahtar yok.
    """
    olaylar: list[dict[str, Any]] = []
    for kaynak in (_servis_isleri, _bakim_ziyaretleri, _kutuk_degisiklikleri, *GECMIS_KAYNAKLARI):
        olaylar.extend(await kaynak(db, ekipman, user))
    if not user.has("maliyet.gor"):
        for olay in olaylar:
            for anahtar in MALIYET_ANAHTARLARI:
                olay.pop(anahtar, None)
    olaylar.sort(key=lambda o: (o["tarih"], o["kaynak_id"]), reverse=True)
    return olaylar


async def degisiklikler(db: AsyncSession, ekipman: ServiceEquipment) -> list[dict[str, Any]]:
    """Kütük değişiklik geçmişi (`audit_logs`, TS-051): kim, ne zaman, eski → yeni.

    KVKK maskelemesi irtibat satırlarının DEĞERİNİ siler; satır (olay) ve seri
    değişiklikleri ayrı satırda olduğu için görünmeye devam eder.
    """
    stmt = (
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(
            AuditLog.entity == ENTITY,
            AuditLog.entity_id == str(ekipman.id),
            AuditLog.action.not_in(("disaaktar", "kisisel.eris")),
        )
        .order_by(AuditLog.id.desc())
    )

    def temiz(d: dict | None) -> dict:
        return {a: v for a, v in (d or {}).items() if a != "hesap"}

    sonuc = []
    for k, ad in (await db.execute(stmt)).all():
        sonuc.append(
            {
                "id": k.id,
                "zaman": k.created_at,
                "eylem": k.action,
                "etiket": _EYLEM_ETIKETLERI.get(k.action.removesuffix(".irtibat"), k.action),
                "kullanici_id": k.user_id,
                "kullanici": ad,
                "kisisel": k.is_personal_data,
                "eski": temiz(k.old_value),
                "yeni": temiz(k.new_value),
            }
        )
    return sonuc


async def ek_sayisi(db: AsyncSession, ekipman_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(Attachment.id)).where(
                Attachment.entity == ENTITY, Attachment.entity_id == ekipman_id
            )
        )
        or 0
    )


# --- Kayıt noktaları (TS-057) ----------------------------------------------------


async def _ek_kapsami(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    """Ekipman eklerinin kapsamı = ekipmanın kapsamı (başka birim/müşteri → 404)."""
    ekipman = await db.get(ServiceEquipment, entity_id)
    if ekipman is None:
        return True  # varlık kontrolü API'de
    return not await erisim_yok_mu(db, user, ekipman)


async def _kvkk_anonimlestir(db: AsyncSession, account_id: int, clock: Clock) -> dict[str, int]:
    """Hesap anonimleştirilince bağlı ekipmanların ham irtibat adını temizler."""
    kayitlar = (
        await db.scalars(
            select(ServiceEquipment).where(
                ServiceEquipment.account_id == account_id,
                ServiceEquipment.contact_name_raw.is_not(None),
            )
        )
    ).all()
    for e in kayitlar:
        e.contact_name_raw = None
    return {"ekipman_irtibat": len(kayitlar)}


async def irtibat_imha(
    db: AsyncSession,
    ekipman: ServiceEquipment,
    *,
    gerekce: str,
    user: User,
    ip: str | None = None,
) -> int:
    """KVKK ilgili kişi talebi (TS-057): ekipmandaki ham irtibat adını ve
    kayıtlı irtibat bağını siler; geçmiş denetim satırlarındaki irtibat
    DEĞERLERİ maskelenir (olayın kendisi kalır).

    Hesabı OLMAYAN (göçten gelen) ekipman hesap anonimleştirmesine girmez;
    veri bulma onu buluyordu ama silecek yol yoktu. Maskelenen satır sayısını
    döner. Gerekçe (başvuru referansı) zorunlu.
    """
    from sqlalchemy import update as sa_update

    from app.models import AuditLog

    gerekce = _gerekce(gerekce)
    temizlenen = sorted(a for a in IRTIBAT_ALANLARI if getattr(ekipman, a) is not None)
    ekipman.contact_name_raw = None
    ekipman.contact_id = None
    ekipman.updated_by = user.id
    await db.flush()
    sonuc = await db.execute(
        sa_update(AuditLog)
        .where(
            AuditLog.entity == ENTITY,
            AuditLog.entity_id == str(ekipman.id),
            AuditLog.is_personal_data.is_(True),
        )
        .values(old_value=kvkk.DEGER_SILINDI, new_value=kvkk.DEGER_SILINDI)
    )
    await audit.log(
        db,
        ENTITY,
        "kvkk.irtibat_imha",
        entity_id=ekipman.id,
        # Değerler DEĞİL, yalnız hangi alanların temizlendiği yazılır.
        new_value={"alanlar": temizlenen, "gerekce": gerekce},
        user_id=user.id,
        ip=ip,
    )
    return sonuc.rowcount or 0


async def _kvkk_denetim_kosulu(db: AsyncSession, account_id: int) -> list[ColumnElement[bool]]:
    """Hesabın ekipmanlarına ait KİŞİSEL denetim satırları (yalnız irtibat satırları
    `is_personal_data=True` olduğundan seri/durum geçmişi maskelenmez)."""
    idler = list(
        (
            await db.scalars(
                select(ServiceEquipment.id).where(ServiceEquipment.account_id == account_id)
            )
        ).all()
    )
    return [kvkk.denetim_hesap_kosulu(ENTITY, account_id, idler)]


async def _kvkk_veri_bul(db: AsyncSession, arama: kvkk.VeriBulAramasi) -> list[dict]:
    """İlgili kişi başvurusu: ekipmandaki ham irtibat adı (hesapsız kayıt dahil)."""
    kosullar: list[ColumnElement[bool]] = []
    if arama.anahtar:
        kosullar.append(kvkk._sql_katla(ServiceEquipment.contact_name_raw).contains(arama.anahtar))
    if arama.hesap_idleri:
        kosullar.append(
            and_(
                ServiceEquipment.account_id.in_(arama.hesap_idleri),
                ServiceEquipment.contact_name_raw.is_not(None),
            )
        )
    if not kosullar:
        return []
    kayitlar = (
        await db.scalars(
            select(ServiceEquipment)
            .where(ServiceEquipment.is_deleted.is_(False), or_(*kosullar))
            .order_by(ServiceEquipment.id)
            .limit(200)
        )
    ).all()
    return [
        {
            "id": e.id,
            "birim": e.birim,
            "hesap_id": e.account_id,
            "seri": e.serial_no,
            "irtibat": e.contact_name_raw,
        }
        for e in kayitlar
    ]


ek_kapsam.kaydet(ENTITY, _ek_kapsami)
kvkk.anonimlestirme_kaydet(_kvkk_anonimlestir)
kvkk.denetim_maske_kaydet(ENTITY, _kvkk_denetim_kosulu)
kvkk.veri_bul_kaydet("servis_ekipmanlari", _kvkk_veri_bul)
