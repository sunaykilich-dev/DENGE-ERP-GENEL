"""Bakım sözleşmesi, kapsam, dönem modeli, eşleştirme, uyarılar (E04, TS-060/061/063/069).

**Kapsam tür+adet girilir, kalem başına bir cihaz saklanır.** "2 X-Ray + 3 Kapı
Dedektörü" beş `maintenance_contract_items` satırıdır; "1 cihaz = 1 PB" kuralı
böylece tek kısmi tekil indeksle (`uq_so_pb_cihaz_donem`) zorlanır. Adet
azaltma satırı SİLMEZ, `valid_to` yazar (geçmiş dönemin PB'si o kaleme bağlı
kalır); artışta yeni satırın `sira`sı kapalılar dahil max+1'dir
(`uq_mci_sira` kapalı satırla çakışmasın).

**Dönem sayacı saklanmaz.** "Yapılan dönem (n/frekans)" döngüdeki kapanmış
dönemlerden sayılır (`DONEM_SAYILAN_KAPANISLAR`). Döngü takvim yılı değil
sözleşme yılıdır: `valid_from + k yıl`. Hedef tarihler döngü başından eşit
aralıkla (12/frekans ay) ya da sabit aylardan hesaplanır; bitiş sonrası
dönem üretilmez. Elle değiştirilen hedef (`target_manual`) bir daha
yeniden hesaplanmaz.

**Ücret** (`fee_per_visit`, `contract_total`, `legacy_fee_text`) yalnız
`maliyet.gor ∧ bakim.yaz` ile yazılır ve `sees_cost` false iken yanıtta
ANAHTAR OLARAK YOKTUR (API katmanı `ucret_alanlari`'nı çıkarır).

**Tesis çakışması (E14-11):** aynı tesiste dönemi kesişen ikinci AKTIF
sözleşme 409 alır; bilinçli istisna `cakisma_onayi + gerekce` ile geçilir ve
denetime yazılır. EXCLUDE konmadı: onaylı istisna gerekir.

**Otomatik üretim bayrağı** (`bakim_otomatik_uretim`) sözleşme–ekipman
eşleştirmesi %100 olmadan açılamaz (409, TS-063): eksik eşleşmeyle açılırsa
worker sessizce eksik PB üretir (kalem ekipmansız → atlanır).

Durum yalnız `BAKIM_SOZLESMESI` makinesiyle değişir. Saat yalnız `Clock` /
`yerel_zaman`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select

from app.models import (
    Account,
    Address,
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenanceExclusionRequest,
    MaintenancePeriod,
    ServiceEquipment,
    ServiceOrder,
    User,
)
from app.models.servis_bakim import (
    BAKIM_CIHAZ_TURLERI,
    DONEM_SAYILAN_KAPANISLAR,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.permissions import BIRIMLER, SCOPE_ALL
from app.services import accounts as hesap_svc
from app.services import audit
from app.services import settings as ayar_svc
from app.services.statemachine import BAKIM_SOZLESMESI, IzinsizGecis
from app.services.teknik_servis import ana_veri, ek_kapsam, kapsam, numara
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import YEREL, yerel_bugun, yerel_gun
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

# Ücret alanları: `sees_cost` false iken yanıtta anahtar olarak YOK.
UCRET_ALANLARI = ("fee_per_visit", "contract_total", "currency", "legacy_fee_text")
# Kapsam satırı adet sınırı (tek sözleşmede tür başına). Göçte görülen en büyük
# değer 11; 200 yazım hatasını ("600 X-RAY") yakalamaya yeter.
AZAMI_ADET = 200
# Bitişi yaklaşan sözleşme uyarı eşiği (gün). `DEFAULTS`'ta anahtarı yok
# (plan §1.9 ayar listesi dondu); kod sabiti — ayar talebi raporda.
BITIS_UYARI_GUN = 60

_ACIK = DURUM_GRUPLARI["ACIK"]


class BakimHatasi(ServisHatasi):
    """Bakım kural ihlali → 409. `veri` 409 gövdesine eklenir (çakışma listesi)."""

    def __init__(self, mesaj: str, *, veri: dict[str, Any] | None = None) -> None:
        super().__init__(mesaj)
        self.veri = veri or {}


class BakimKapsamDisi(LookupError):
    """Kayıt yok ya da kullanıcının kapsamı dışında → 404 (yazma yok)."""


@dataclass
class SozlesmeGirdisi:
    birim: str
    account_id: int | None
    address_id: int | None = None
    contact_id: int | None = None
    responsible_user_id: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    annual_frequency: int | None = None
    fixed_months: list[int] | None = None
    # {"XRAY": 2, "KAPI_DEDEKTORU": 3}
    kapsam: dict[str, int] = field(default_factory=dict)
    notes: str | None = None
    cakisma_onayi: bool = False
    cakisma_gerekcesi: str | None = None


# =============================================================================
# Takvim (saf fonksiyonlar — `tests/unit/test_bakim_takvim.py`)
# =============================================================================


def ay_ekle(gun: date, ay: int) -> date:
    """`gun`e `ay` ay ekler; ay sonu kırpılır (31 Ocak + 1 ay = 28/29 Şubat)."""
    toplam = gun.year * 12 + (gun.month - 1) + ay
    yil, ay_no = divmod(toplam, 12)
    ay_no += 1
    return date(yil, ay_no, min(gun.day, calendar.monthrange(yil, ay_no)[1]))


def dongu_baslangiclari(bas: date, bit: date) -> list[date]:
    """Sözleşme döngüleri: `bas + k yıl` (k = 0, 1, …) ve `< bit`.

    Döngü takvim yılı değildir: 01.06.2026 başlangıçlı sözleşmede 02.01.2027
    hâlâ ilk döngüdür (E04-05). 29 Şubat başlangıç → sonraki yıllarda 28 Şubat.
    """
    sonuc: list[date] = []
    k = 0
    while True:
        gun = ay_ekle(bas, 12 * k)
        if gun >= bit:
            return sonuc
        sonuc.append(gun)
        k += 1


def hedef_tarihler(dongu_bas: date, frekans: int, sabit_aylar: list[int] | None) -> list[date]:
    """Bir döngünün hedef tarihleri (kronolojik).

    Sabit aylar verilmişse her ay döngü içindeki İLK karşılığına düşer (gün =
    döngü başı günü, ay sonu kırpılır); verilmemişse eşit aralık
    (`12 * i // frekans` ay): 01.06.2026, frekans 3 → 01.06, 01.10, 01.02.
    """
    if frekans < 1 or frekans > 12:
        raise ServisGirdiHatasi("Yıllık bakım adedi 1 ile 12 arasında olmalı")
    if sabit_aylar:
        gunler = []
        for ay in sorted(set(sabit_aylar)):
            fark = (ay - dongu_bas.month) % 12
            gunler.append(ay_ekle(dongu_bas, fark))
        return sorted(gunler)
    return [ay_ekle(dongu_bas, (12 * i) // frekans) for i in range(frekans)]


def donem_plani(
    bas: date, bit: date, frekans: int, sabit_aylar: list[int] | None
) -> list[tuple[date, int, date]]:
    """`(döngü başı, sıra, hedef)` üçlüleri; hedefi bitiş gününe eşit/sonra olan
    dönem üretilmez (sözleşme yarı açık `[valid_from, valid_to)`)."""
    plan: list[tuple[date, int, date]] = []
    for dongu in dongu_baslangiclari(bas, bit):
        for sira, hedef in enumerate(hedef_tarihler(dongu, frekans, sabit_aylar), start=1):
            if hedef < bit:
                plan.append((dongu, sira, hedef))
    return plan


def yerel_gece(gun: date) -> datetime:
    """Türkiye gününün başlangıç anı (UTC)."""
    return datetime.combine(gun, time.min, tzinfo=YEREL).astimezone(UTC)


def _ayni_an(a: datetime, b: datetime) -> bool:
    return a.astimezone(UTC) == b.astimezone(UTC)


def guncel_dongu(donem_baslari: list[datetime], an: datetime) -> datetime | None:
    """`an`ı içeren döngünün başı (döngüler artan sırada)."""
    secili = None
    for bas in sorted(donem_baslari):
        if bas <= an:
            secili = bas
    return secili


# =============================================================================
# Kapsam yardımcıları
# =============================================================================


def sozlesme_kapsami(stmt: Select, user: User) -> Select:
    """Sözleşme listelerine birim + müşteri kapsamı (sayı = sızıntı)."""
    stmt = kapsam.kapsam_birim(stmt, user, MaintenanceContract.birim, birimsiz_gorunur=False)
    return hesap_svc.kapsam_musteri(stmt, user, MaintenanceContract.account_id)


async def sozlesme_disinda_mi(db: AsyncSession, user: User, sozlesme: MaintenanceContract) -> bool:
    if kapsam.birim_disinda_mi(user, sozlesme.birim, birimsiz_gorunur=False):
        return True
    return await hesap_svc.kapsam_disinda_mi(db, user, sozlesme.account_id)


async def kapsamli_sozlesme(
    db: AsyncSession, user: User, sozlesme_id: int, *, kilitle: bool = False
) -> MaintenanceContract:
    """Sözleşmeyi kapsamla getirir; yok/silinmiş/kapsam dışı → `BakimKapsamDisi`."""
    stmt = select(MaintenanceContract).where(
        MaintenanceContract.id == sozlesme_id, MaintenanceContract.is_deleted.is_(False)
    )
    if kilitle:
        stmt = stmt.with_for_update()
    sozlesme = await db.scalar(stmt)
    if sozlesme is None or await sozlesme_disinda_mi(db, user, sozlesme):
        raise BakimKapsamDisi("Bakım sözleşmesi bulunamadı")
    return sozlesme


async def kapsamli_donem(
    db: AsyncSession, sozlesme: MaintenanceContract, donem_id: int
) -> MaintenancePeriod:
    donem = await db.get(MaintenancePeriod, donem_id)
    if donem is None or donem.is_deleted or donem.contract_id != sozlesme.id:
        raise BakimKapsamDisi("Bakım dönemi bulunamadı")
    return donem


# =============================================================================
# Doğrulamalar
# =============================================================================


def _birim_dogrula(user: User, birim: str) -> None:
    if birim not in BIRIMLER:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {birim}")
    if kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        # Kapsam dışı birime kayıt açmak = kaydı görünmez yapmak (404, plan §1.2).
        raise BakimKapsamDisi("Birim bulunamadı")


def _kapsam_dogrula(kapsam_girdisi: dict[str, int]) -> dict[str, int]:
    temiz: dict[str, int] = {}
    for tur, adet in kapsam_girdisi.items():
        if tur not in BAKIM_CIHAZ_TURLERI:
            raise ServisGirdiHatasi(
                f"Bilinmeyen cihaz türü: {tur} (geçerliler: {', '.join(BAKIM_CIHAZ_TURLERI)})"
            )
        if isinstance(adet, bool) or not isinstance(adet, int) or not 0 <= adet <= AZAMI_ADET:
            raise ServisGirdiHatasi(f"{tur} adedi 0 ile {AZAMI_ADET} arasında olmalı")
        temiz[tur] = adet
    return temiz


def _takvim_dogrula(
    valid_from: datetime | None,
    valid_to: datetime | None,
    frekans: int | None,
    sabit_aylar: list[int] | None,
) -> None:
    for an in (valid_from, valid_to):
        if an is not None and an.tzinfo is None:
            raise ServisGirdiHatasi("Tarih saat dilimi bilgisi taşımalı")
    if valid_from is not None and valid_to is not None and valid_to <= valid_from:
        raise ServisGirdiHatasi("Sözleşme bitişi başlangıçtan sonra olmalı")
    if frekans is not None and not 1 <= frekans <= 12:
        raise ServisGirdiHatasi("Yıllık bakım adedi 1 ile 12 arasında olmalı")
    if sabit_aylar:
        if any(not 1 <= a <= 12 for a in sabit_aylar):
            raise ServisGirdiHatasi("Sabit aylar 1 ile 12 arasında olmalı")
        if len(set(sabit_aylar)) != len(sabit_aylar):
            raise ServisGirdiHatasi("Sabit aylarda tekrar olamaz")
        if frekans is None or len(sabit_aylar) != frekans:
            raise ServisGirdiHatasi("Sabit ay sayısı yıllık bakım adediyle aynı olmalı")


async def _musteri_lokasyon_dogrula(
    db: AsyncSession,
    user: User,
    account_id: int | None,
    address_id: int | None,
    contact_id: int | None,
) -> None:
    if account_id is not None and await hesap_svc.kapsam_disinda_mi(db, user, account_id):
        raise BakimKapsamDisi("Müşteri bulunamadı")
    try:
        _, adres, _ = await ana_veri.lokasyon_dogrula(db, account_id, address_id, contact_id)
    except ana_veri.AnaVeriHatasi as exc:
        raise ServisGirdiHatasi(exc.mesaj) from exc
    if adres is not None and adres.kind != "TESIS":
        # Sözleşmede "Tesis" ve "Sözleşme Tarafı (Cari)" ayrı alanlardır (E14-11):
        # cari merkez/fatura adresi gidilen yer olarak seçilemez.
        raise ServisGirdiHatasi("Sözleşme lokasyonu bir tesis olmalı (merkez/fatura adresi değil)")


async def _sorumlu_dogrula(db: AsyncSession, user: User, sorumlu_id: int | None) -> None:
    if sorumlu_id is None:
        return
    kisi = await db.get(User, sorumlu_id)
    if kisi is None or await kapsam.personel_disinda_mi(db, user, sorumlu_id):
        raise BakimKapsamDisi("Sorumlu personel bulunamadı")
    if not kisi.is_active:
        raise ServisGirdiHatasi("Sorumlu personel aktif değil")


async def donem_cakismalari(
    db: AsyncSession,
    user: User,
    *,
    address_id: int | None,
    valid_from: datetime | None,
    valid_to: datetime | None,
    haric_id: int | None = None,
) -> list[dict[str, Any]]:
    """Aynı tesiste dönemi kesişen AKTIF sözleşmeler (E14-11).

    Kapsam dışı sözleşmenin numarası maskelenir: 409 gövdesi de bir okuma
    yoludur, başka birimin sözleşme numarası buradan sızmamalı.
    """
    if address_id is None or valid_from is None or valid_to is None:
        return []
    stmt = select(MaintenanceContract).where(
        MaintenanceContract.address_id == address_id,
        MaintenanceContract.status == "AKTIF",
        MaintenanceContract.is_deleted.is_(False),
        MaintenanceContract.valid_from < valid_to,
        MaintenanceContract.valid_to > valid_from,
    )
    if haric_id is not None:
        stmt = stmt.where(MaintenanceContract.id != haric_id)
    sonuc = []
    for s in (await db.scalars(stmt.order_by(MaintenanceContract.id))).all():
        gizli = await sozlesme_disinda_mi(db, user, s)
        sonuc.append(
            {
                "id": None if gizli else s.id,
                "contract_no": "(kapsam dışı sözleşme)" if gizli else s.contract_no,
                "valid_from": None if gizli else s.valid_from.isoformat(),
                "valid_to": None if gizli else s.valid_to.isoformat(),
            }
        )
    return sonuc


async def _cakisma_kontrol(
    db: AsyncSession,
    user: User,
    sozlesme: MaintenanceContract,
    *,
    onay: bool,
    gerekce: str | None,
    ip: str | None = None,
) -> None:
    cakisanlar = await donem_cakismalari(
        db,
        user,
        address_id=sozlesme.address_id,
        valid_from=sozlesme.valid_from,
        valid_to=sozlesme.valid_to,
        haric_id=sozlesme.id,
    )
    if not cakisanlar:
        return
    if not onay:
        raise BakimHatasi(
            "Aynı tesiste dönemi çakışan aktif bakım sözleşmesi var. Bilinçli istisnaysa "
            "onaylayıp gerekçe yazın.",
            veri={"kod": "DONEM_CAKISMA", "cakisanlar": cakisanlar},
        )
    if not (gerekce or "").strip():
        raise ServisGirdiHatasi("Çakışma onayı için gerekçe zorunlu")
    await audit.log(
        db,
        "maintenance_contracts",
        "bakim.sozlesme.cakisma_onayi",
        entity_id=sozlesme.id,
        new_value={
            "gerekce": gerekce.strip(),
            "cakisanlar": [c["contract_no"] for c in cakisanlar],
        },
        user_id=user.id,
        ip=ip,
    )


# =============================================================================
# Sözleşme yazma
# =============================================================================


def _kalem(
    sozlesme: MaintenanceContract, tur: str, sira: int, valid_from: datetime | None, user: User
) -> MaintenanceContractItem:
    return MaintenanceContractItem(
        contract_id=sozlesme.id,
        equipment_type=tur,
        sira=sira,
        valid_from=valid_from,
        created_by=user.id,
        updated_by=user.id,
    )


async def sozlesme_olustur(
    db: AsyncSession,
    girdi: SozlesmeGirdisi,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> MaintenanceContract:
    """TASLAK sözleşme + tür/adet kalemleri. Aktifleştirme ayrı adımdır
    (`durum_degistir`); dönemler AKTIF olunca hesaplanır."""
    _birim_dogrula(user, girdi.birim)
    if girdi.account_id is None:
        raise ServisGirdiHatasi("Müşteri (sözleşme tarafı cari) seçilmedi")
    await _musteri_lokasyon_dogrula(db, user, girdi.account_id, girdi.address_id, girdi.contact_id)
    await _sorumlu_dogrula(db, user, girdi.responsible_user_id)
    _takvim_dogrula(girdi.valid_from, girdi.valid_to, girdi.annual_frequency, girdi.fixed_months)
    kapsam_girdisi = _kapsam_dogrula(girdi.kapsam)

    sozlesme = MaintenanceContract(
        contract_no=await numara.bakim_sozlesme_no(db),
        birim=girdi.birim,
        account_id=girdi.account_id,
        address_id=girdi.address_id,
        contact_id=girdi.contact_id,
        responsible_user_id=girdi.responsible_user_id,
        valid_from=girdi.valid_from,
        valid_to=girdi.valid_to,
        annual_frequency=girdi.annual_frequency,
        fixed_months=sorted(girdi.fixed_months) if girdi.fixed_months else None,
        status="TASLAK",
        notes=girdi.notes,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(sozlesme)
    await db.flush()
    # Tesis çakışması AKTİF sözleşmeler arasında aranır (E14-11): TASLAK
    # kayıt serbestçe açılır, kontrol aktifleştirmede yapılır.
    for tur, adet in kapsam_girdisi.items():
        for sira in range(1, adet + 1):
            db.add(_kalem(sozlesme, tur, sira, girdi.valid_from, user))
    await db.flush()
    await audit.log(
        db,
        "maintenance_contracts",
        "bakim.sozlesme.olustur",
        entity_id=sozlesme.id,
        new_value={
            "contract_no": sozlesme.contract_no,
            "birim": sozlesme.birim,
            "account_id": sozlesme.account_id,
            "address_id": sozlesme.address_id,
            "kapsam": kapsam_girdisi,
        },
        user_id=user.id,
        ip=ip,
    )
    return sozlesme


_DUZENLENEBILIR = (
    "birim",
    "account_id",
    "address_id",
    "contact_id",
    "responsible_user_id",
    "valid_from",
    "valid_to",
    "annual_frequency",
    "fixed_months",
    "notes",
)


async def pb_sayisi(db: AsyncSession, sozlesme_id: int, *, yalniz_acik: bool = False) -> int:
    stmt = (
        select(func.count(ServiceOrder.id))
        .join(MaintenanceContractItem, MaintenanceContractItem.id == ServiceOrder.contract_item_id)
        .where(
            MaintenanceContractItem.contract_id == sozlesme_id,
            ServiceOrder.tur == "PB",
            ServiceOrder.is_deleted.is_(False),
        )
    )
    if yalniz_acik:
        stmt = stmt.where(ServiceOrder.status.in_(sorted(_ACIK)))
    return int(await db.scalar(stmt) or 0)


async def sozlesme_guncelle(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    degisiklikler: dict,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> MaintenanceContract:
    """Alan düzeltmesi. Tarih/frekans değişirse PB'si olmayan, elle
    değiştirilmemiş dönemler yeniden hesaplanır. PB üretilmiş sözleşmede
    müşteri/tesis/birim değişmez (409): açık PB yabancı tesise düşerdi."""
    cakisma_onayi = bool(degisiklikler.pop("cakisma_onayi", False))
    cakisma_gerekcesi = degisiklikler.pop("cakisma_gerekcesi", None)
    bilinmeyen = set(degisiklikler) - set(_DUZENLENEBILIR)
    if bilinmeyen:
        raise ServisGirdiHatasi(f"Düzenlenemeyen alan: {', '.join(sorted(bilinmeyen))}")
    yeni = {k: v for k, v in degisiklikler.items() if getattr(sozlesme, k) != v}
    if not yeni:
        return sozlesme

    if "birim" in yeni:
        if yeni["birim"] not in BIRIMLER:
            raise ServisGirdiHatasi(f"Bilinmeyen birim: {yeni['birim']}")
        if kapsam.birim_degisimi_yasak_mi(user, sozlesme.birim, yeni["birim"]):
            raise BakimKapsamDisi("Birim bulunamadı")
    if {"birim", "account_id", "address_id"} & set(yeni) and await pb_sayisi(db, sozlesme.id):
        raise BakimHatasi(
            "Bu sözleşmeden planlı bakım işi üretildi; müşteri, tesis ve birim "
            "değiştirilemez. Yeni sözleşme açın."
        )
    hesap = yeni.get("account_id", sozlesme.account_id)
    if {"account_id", "address_id", "contact_id"} & set(yeni):
        await _musteri_lokasyon_dogrula(
            db,
            user,
            hesap,
            yeni.get("address_id", sozlesme.address_id),
            yeni.get("contact_id", sozlesme.contact_id),
        )
    if "responsible_user_id" in yeni:
        await _sorumlu_dogrula(db, user, yeni["responsible_user_id"])
    takvim = {
        k: yeni.get(k, getattr(sozlesme, k))
        for k in ("valid_from", "valid_to", "annual_frequency", "fixed_months")
    }
    _takvim_dogrula(
        takvim["valid_from"],
        takvim["valid_to"],
        takvim["annual_frequency"],
        takvim["fixed_months"],
    )
    if sozlesme.status == "AKTIF" and (
        takvim["valid_from"] is None
        or takvim["valid_to"] is None
        or takvim["annual_frequency"] is None
    ):
        raise ServisGirdiHatasi("Aktif sözleşmede başlangıç, bitiş ve yıllık adet boş bırakılamaz")

    eski_bas = sozlesme.valid_from
    for k, v in yeni.items():
        setattr(sozlesme, k, sorted(v) if k == "fixed_months" and v else v)
    sozlesme.updated_by = user.id
    await audit.log_change(db, sozlesme, "bakim.sozlesme.guncelle", user_id=user.id, ip=ip)
    await db.flush()

    if {"address_id", "valid_from", "valid_to"} & set(yeni) and sozlesme.status == "AKTIF":
        await _cakisma_kontrol(
            db, user, sozlesme, onay=cakisma_onayi, gerekce=cakisma_gerekcesi, ip=ip
        )
    if "valid_from" in yeni:
        await _ilk_kalemleri_tasi(db, sozlesme, eski_bas)
    if sozlesme.status == "AKTIF" and {
        "valid_from",
        "valid_to",
        "annual_frequency",
        "fixed_months",
    } & set(yeni):
        await donemleri_hesapla(db, sozlesme, clock)
    return sozlesme


async def _ilk_kalemleri_tasi(
    db: AsyncSession, sozlesme: MaintenanceContract, eski_bas: datetime | None
) -> None:
    """Sözleşmeyle birlikte açılmış (tarihsiz ya da eski başlangıçlı) açık
    kalemlerin başlangıcını sözleşme başlangıcına çeker."""
    if sozlesme.valid_from is None:
        return
    kosul = MaintenanceContractItem.valid_from.is_(None)
    if eski_bas is not None:
        kosul = or_(kosul, MaintenanceContractItem.valid_from == eski_bas)
    kalemler = (
        await db.scalars(
            select(MaintenanceContractItem).where(
                MaintenanceContractItem.contract_id == sozlesme.id,
                MaintenanceContractItem.is_deleted.is_(False),
                MaintenanceContractItem.valid_to.is_(None),
                kosul,
            )
        )
    ).all()
    for k in kalemler:
        k.valid_from = sozlesme.valid_from
    await db.flush()


@dataclass
class DurumSonucu:
    sozlesme: MaintenanceContract
    acik_pb_isleri: list[str] = field(default_factory=list)


async def durum_degistir(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    hedef: str,
    *,
    user: User,
    clock: Clock,
    cakisma_onayi: bool = False,
    cakisma_gerekcesi: str | None = None,
    ip: str | None = None,
) -> DurumSonucu:
    """`BAKIM_SOZLESMESI` makinesiyle durum. AKTIF: tarih/adet/müşteri zorunlu,
    tesis çakışması kontrol edilir, dönemler hesaplanır. PASIF: hiçbir şey
    silinmez; açık PB işleri yanıtta listelenir (E14-11 kabul 3)."""
    try:
        BAKIM_SOZLESMESI.dogrula(sozlesme.status, hedef)
    except IzinsizGecis as exc:
        raise BakimHatasi(str(exc)) from exc
    if hedef == "AKTIF":
        eksik = [
            ad
            for ad, deger in (
                ("müşteri", sozlesme.account_id),
                ("başlangıç tarihi", sozlesme.valid_from),
                ("bitiş tarihi", sozlesme.valid_to),
                ("yıllık bakım adedi", sozlesme.annual_frequency),
            )
            if deger is None
        ]
        if eksik:
            raise ServisGirdiHatasi(f"Aktifleştirmek için eksik: {', '.join(eksik)}")
        await _cakisma_kontrol(
            db, user, sozlesme, onay=cakisma_onayi, gerekce=cakisma_gerekcesi, ip=ip
        )
    onceki = sozlesme.status
    sozlesme.status = hedef
    sozlesme.updated_by = user.id
    await audit.log(
        db,
        "maintenance_contracts",
        "bakim.sozlesme.durum",
        entity_id=sozlesme.id,
        old_value={"status": onceki},
        new_value={"status": hedef},
        user_id=user.id,
        ip=ip,
    )
    await db.flush()
    sonuc = DurumSonucu(sozlesme)
    if hedef == "AKTIF":
        await _ilk_kalemleri_tasi(db, sozlesme, None)
        await donemleri_hesapla(db, sozlesme, clock)
    else:
        sonuc.acik_pb_isleri = list(
            (
                await db.scalars(
                    select(ServiceOrder.so_no)
                    .join(
                        MaintenanceContractItem,
                        MaintenanceContractItem.id == ServiceOrder.contract_item_id,
                    )
                    .where(
                        MaintenanceContractItem.contract_id == sozlesme.id,
                        ServiceOrder.tur == "PB",
                        ServiceOrder.is_deleted.is_(False),
                        ServiceOrder.status.in_(sorted(_ACIK)),
                    )
                    .order_by(ServiceOrder.so_no)
                )
            ).all()
        )
    return sonuc


async def acik_kalemler(db: AsyncSession, sozlesme_id: int) -> list[MaintenanceContractItem]:
    return list(
        (
            await db.scalars(
                select(MaintenanceContractItem)
                .where(
                    MaintenanceContractItem.contract_id == sozlesme_id,
                    MaintenanceContractItem.is_deleted.is_(False),
                    MaintenanceContractItem.valid_to.is_(None),
                )
                .order_by(MaintenanceContractItem.equipment_type, MaintenanceContractItem.sira)
            )
        ).all()
    )


def kapsam_ozeti(kalemler: list[MaintenanceContractItem]) -> dict[str, int]:
    ozet: dict[str, int] = {}
    for k in kalemler:
        ozet[k.equipment_type] = ozet.get(k.equipment_type, 0) + 1
    return ozet


async def kapsam_guncelle(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    hedef_kapsam: dict[str, int],
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> dict[str, int]:
    """Tür+adet farkını uygular. Artış: yeni kalem (sıra = kapalılar dahil
    max+1). Azalış: en büyük sıralı, açık PB'si OLMAYAN kalem kapanır
    (`valid_to`); yeterli kalem kapanamıyorsa 409 + PB listesi."""
    hedef_kapsam = _kapsam_dogrula(hedef_kapsam)
    simdi = clock.now()
    kalemler = await acik_kalemler(db, sozlesme.id)
    mevcut = kapsam_ozeti(kalemler)
    onceki = dict(mevcut)
    for tur in BAKIM_CIHAZ_TURLERI:
        if tur not in hedef_kapsam:
            continue
        istenen, var = hedef_kapsam[tur], mevcut.get(tur, 0)
        if istenen > var:
            en_buyuk = await db.scalar(
                select(func.max(MaintenanceContractItem.sira)).where(
                    MaintenanceContractItem.contract_id == sozlesme.id,
                    MaintenanceContractItem.equipment_type == tur,
                )
            )
            baslangic = sozlesme.valid_from
            if sozlesme.status == "AKTIF" and baslangic is not None and baslangic < simdi:
                baslangic = simdi
            for i in range(istenen - var):
                db.add(_kalem(sozlesme, tur, int(en_buyuk or 0) + i + 1, baslangic, user))
        elif istenen < var:
            adaylar = sorted(
                (k for k in kalemler if k.equipment_type == tur), key=lambda k: -k.sira
            )
            kapanacak: list[MaintenanceContractItem] = []
            engelli: list[str] = []
            for k in adaylar:
                if len(kapanacak) == var - istenen:
                    break
                acik_pb = await db.scalar(
                    select(ServiceOrder.so_no).where(
                        ServiceOrder.contract_item_id == k.id,
                        ServiceOrder.tur == "PB",
                        ServiceOrder.is_deleted.is_(False),
                        ServiceOrder.status.in_(sorted(_ACIK)),
                    )
                )
                if acik_pb:
                    engelli.append(acik_pb)
                    continue
                kapanacak.append(k)
            if len(kapanacak) < var - istenen:
                raise BakimHatasi(
                    "Açık planlı bakım işi olan cihaz kapsamdan çıkarılamaz; önce işi "
                    "tamamlayın ya da Kapsam Dışı talebiyle iptal ettirin.",
                    veri={"kod": "ACIK_PB", "isler": engelli},
                )
            for k in kapanacak:
                if k.valid_from is None or k.valid_from >= simdi:
                    # Hiç yürürlüğe girmemiş kalem: geçmişi yok, yumuşak silinir.
                    k.is_deleted = True
                    k.deleted_at = simdi
                    k.deleted_by = user.id
                else:
                    k.valid_to = simdi
                k.updated_by = user.id
    await db.flush()
    yeni = kapsam_ozeti(await acik_kalemler(db, sozlesme.id))
    if yeni != onceki:
        await audit.log(
            db,
            "maintenance_contracts",
            "bakim.kapsam.degistir",
            entity_id=sozlesme.id,
            old_value={"kapsam": onceki},
            new_value={"kapsam": yeni},
            user_id=user.id,
            ip=ip,
        )
    return yeni


async def ucret_guncelle(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    degisiklikler: dict,
    *,
    user: User,
    ip: str | None = None,
) -> MaintenanceContract:
    """Ücret alanları — yetki (`maliyet.gor ∧ bakim.yaz`) API kapısında."""
    for k, v in degisiklikler.items():
        if k not in ("fee_per_visit", "contract_total", "currency"):
            raise ServisGirdiHatasi(f"Ücret ucu yalnız ücret alanlarını değiştirir: {k}")
        if k != "currency" and v is not None and v < 0:
            raise ServisGirdiHatasi("Ücret negatif olamaz")
        setattr(sozlesme, k, v)
    sozlesme.updated_by = user.id
    await audit.log_change(db, sozlesme, "bakim.sozlesme.ucret", user_id=user.id, ip=ip)
    await db.flush()
    return sozlesme


# =============================================================================
# Dönem modeli (TS-061)
# =============================================================================


async def donemleri_hesapla(
    db: AsyncSession, sozlesme: MaintenanceContract, clock: Clock
) -> list[MaintenancePeriod]:
    """Döngüden dönem satırları (idempotent).

    Eksik dönem eklenir; PB'si olmayan, kapanmamış ve elle değiştirilmemiş
    dönemin hedefi güncellenir; plandan düşen dönem PB'si yoksa fiziksel
    silinir (hiçbir kayıt ona bağlı değil; yumuşak silme `uq_mp_donem`'i
    yeniden açılışta kilitlerdi). PB'si olan dönem asla silinmez.
    """
    if (
        sozlesme.valid_from is None
        or sozlesme.valid_to is None
        or sozlesme.annual_frequency is None
    ):
        return []
    bas, bit = yerel_gun(sozlesme.valid_from), yerel_gun(sozlesme.valid_to)
    plan = donem_plani(bas, bit, sozlesme.annual_frequency, sozlesme.fixed_months)
    mevcutlar = (
        await db.scalars(
            select(MaintenancePeriod).where(
                MaintenancePeriod.contract_id == sozlesme.id,
                MaintenancePeriod.is_deleted.is_(False),
            )
        )
    ).all()
    pbli = set(
        (
            await db.scalars(
                select(ServiceOrder.maintenance_period_id).where(
                    ServiceOrder.maintenance_period_id.in_([d.id for d in mevcutlar] or [0]),
                    ServiceOrder.is_deleted.is_(False),
                )
            )
        ).all()
    )
    anahtar = {(d.cycle_start.astimezone(UTC), d.sequence_no): d for d in mevcutlar}
    planli: set[tuple[datetime, int]] = set()
    for dongu, sira, hedef in plan:
        an = yerel_gece(dongu)
        planli.add((an, sira))
        donem = anahtar.get((an, sira))
        if donem is None:
            db.add(
                MaintenancePeriod(
                    contract_id=sozlesme.id,
                    cycle_start=an,
                    sequence_no=sira,
                    target_date=hedef,
                )
            )
        elif (
            donem.target_date != hedef
            and not donem.target_manual
            and donem.closed_at is None
            and donem.id not in pbli
        ):
            donem.target_date = hedef
    for (an, sira), donem in anahtar.items():
        if (an, sira) not in planli and donem.id not in pbli and donem.closed_at is None:
            await db.delete(donem)
    await db.flush()
    return list(
        (
            await db.scalars(
                select(MaintenancePeriod)
                .where(
                    MaintenancePeriod.contract_id == sozlesme.id,
                    MaintenancePeriod.is_deleted.is_(False),
                )
                .order_by(MaintenancePeriod.cycle_start, MaintenancePeriod.sequence_no)
            )
        ).all()
    )


async def donem_sayaci(
    db: AsyncSession, sozlesme: MaintenanceContract, clock: Clock
) -> dict[str, Any]:
    """Güncel döngüde yapılan dönem / frekans — saklanmaz, kapanışlardan sayılır."""
    donemler = (
        await db.scalars(
            select(MaintenancePeriod).where(
                MaintenancePeriod.contract_id == sozlesme.id,
                MaintenancePeriod.is_deleted.is_(False),
            )
        )
    ).all()
    dongu = guncel_dongu(list({d.cycle_start for d in donemler}), clock.now())
    if dongu is None:
        return {"yapilan": 0, "frekans": sozlesme.annual_frequency, "dongu_baslangici": None}
    yapilan = sum(
        1
        for d in donemler
        if _ayni_an(d.cycle_start, dongu) and d.closing_kind in DONEM_SAYILAN_KAPANISLAR
    )
    sonraki = min(
        (d.target_date for d in donemler if d.closed_at is None),
        default=None,
    )
    return {
        "yapilan": yapilan,
        "frekans": sozlesme.annual_frequency,
        "dongu_baslangici": yerel_gun(dongu).isoformat(),
        "sonraki_hedef": sonraki.isoformat() if sonraki else None,
    }


async def hedef_tarih_degistir(
    db: AsyncSession,
    donem: MaintenancePeriod,
    hedef: date,
    gerekce: str,
    *,
    user: User,
    ip: str | None = None,
) -> MaintenancePeriod:
    if not (gerekce or "").strip():
        raise ServisGirdiHatasi("Hedef tarih değişikliği için gerekçe zorunlu")
    if donem.closed_at is not None:
        raise BakimHatasi("Kapanmış dönemin hedef tarihi değiştirilemez")
    donem.target_date = hedef
    donem.target_manual = True
    donem.target_change_reason = gerekce.strip()
    donem.updated_by = user.id
    await audit.log_change(db, donem, "bakim.donem.hedef_degistir", user_id=user.id, ip=ip)
    await db.flush()
    return donem


def gecikme_kosulu(bugun: date, tolerans: int):
    """Geciken dönem: açık ve hedef + tolerans < bugün."""
    return and_(
        MaintenancePeriod.closed_at.is_(None),
        MaintenancePeriod.is_deleted.is_(False),
        MaintenancePeriod.target_date < bugun - timedelta(days=tolerans),
    )


def donem_kapsami(stmt: Select, user: User) -> Select:
    """Dönem listelerine sözleşme kapsamı (sözleşmeye JOIN eden sorgu)."""
    return sozlesme_kapsami(stmt, user)


# =============================================================================
# Eşleştirme (TS-063)
# =============================================================================


async def _bagli_ekipmanlar(db: AsyncSession, haric_kalem: int | None = None) -> dict[int, str]:
    """Açık bir sözleşme kalemine bağlı ekipman → sözleşme no."""
    stmt = (
        select(MaintenanceContractItem.equipment_id, MaintenanceContract.contract_no)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenanceContractItem.contract_id)
        .where(
            MaintenanceContractItem.equipment_id.is_not(None),
            MaintenanceContractItem.is_deleted.is_(False),
            MaintenanceContractItem.valid_to.is_(None),
            MaintenanceContract.is_deleted.is_(False),
        )
    )
    if haric_kalem is not None:
        stmt = stmt.where(MaintenanceContractItem.id != haric_kalem)
    return {eid: no for eid, no in (await db.execute(stmt)).all()}


def _ekipman_satiri(e: ServiceEquipment) -> dict[str, Any]:
    return {
        "id": e.id,
        "equipment_type": e.equipment_type,
        "serial_no": e.serial_no,
        "brand": e.brand,
        "model": e.model,
        "zone": e.zone,
        "address_id": e.address_id,
    }


def _aday_sorgusu(sozlesme: MaintenanceContract, tur: str):
    stmt = select(ServiceEquipment).where(
        ServiceEquipment.is_deleted.is_(False),
        ServiceEquipment.is_active.is_(True),
        ServiceEquipment.merged_into_id.is_(None),
        ServiceEquipment.lifecycle_status != "HURDA",
        ServiceEquipment.birim == sozlesme.birim,
        ServiceEquipment.account_id == sozlesme.account_id,
        ServiceEquipment.equipment_type == tur,
    )
    if sozlesme.address_id is not None:
        stmt = stmt.where(
            or_(
                ServiceEquipment.address_id == sozlesme.address_id,
                ServiceEquipment.address_id.is_(None),
            )
        )
    return stmt.order_by(ServiceEquipment.serial_key, ServiceEquipment.id)


async def eslestirme_onerileri(
    db: AsyncSession, sozlesme: MaintenanceContract, user: User
) -> list[dict[str, Any]]:
    """Açık kalemler + ekipman adayları. Aday: aynı birim, aynı cari, aynı tür,
    sözleşme tesisinde (ya da tesisi girilmemiş), başka açık kaleme bağlı
    olmayan aktif ekipman. Türde TEK aday kaldıysa ilk eşleşmemiş kaleme
    öneri olarak konur; birden çok aday listede kalır, karar şefindir (sistem
    tahmin etmez, E03-D03)."""
    kalemler = await acik_kalemler(db, sozlesme.id)
    bagli = await _bagli_ekipmanlar(db)
    ekipman_idleri = [k.equipment_id for k in kalemler if k.equipment_id]
    bagli_ekipmanlar = {
        e.id: e
        for e in (
            await db.scalars(
                select(ServiceEquipment).where(ServiceEquipment.id.in_(ekipman_idleri or [0]))
            )
        ).all()
    }
    adaylar_tur: dict[str, list[ServiceEquipment]] = {}
    for tur in {k.equipment_type for k in kalemler if k.equipment_id is None}:
        adaylar_tur[tur] = [
            e for e in (await db.scalars(_aday_sorgusu(sozlesme, tur))).all() if e.id not in bagli
        ]
    oneri_verildi: set[str] = set()
    satirlar = []
    for k in kalemler:
        adaylar = adaylar_tur.get(k.equipment_type, []) if k.equipment_id is None else []
        oneri = None
        if k.equipment_id is None and len(adaylar) == 1 and k.equipment_type not in oneri_verildi:
            oneri = adaylar[0].id
            oneri_verildi.add(k.equipment_type)
        ekipman = bagli_ekipmanlar.get(k.equipment_id) if k.equipment_id else None
        satirlar.append(
            {
                "kalem_id": k.id,
                "equipment_type": k.equipment_type,
                "sira": k.sira,
                "pb_uygun": k.pb_uygun,
                "equipment_id": k.equipment_id,
                "ekipman": _ekipman_satiri(ekipman) if ekipman else None,
                "oneri_id": oneri,
                "adaylar": [_ekipman_satiri(e) for e in adaylar],
            }
        )
    return satirlar


async def eslestir(
    db: AsyncSession,
    sozlesme: MaintenanceContract,
    eslesmeler: list[tuple[int, int | None]],
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> None:
    """Şef onayı: kaleme ekipman bağlar (None = bağı kaldırır).

    Ekipman aynı cari/birim/türde olmalı (400), başka açık kaleme bağlı olamaz
    (409; `ex_mci_ekipman_cakisma` yarışta son savunma). Açık PB'si olan
    kalemin ekipmanı değiştirilemez (409): sahadaki form başka cihazı
    gösterirdi.
    """
    kalemler = {k.id: k for k in await acik_kalemler(db, sozlesme.id)}
    degisen: list[dict[str, Any]] = []
    for kalem_id, ekipman_id in eslesmeler:
        kalem = kalemler.get(kalem_id)
        if kalem is None:
            raise ServisGirdiHatasi(f"Kalem #{kalem_id} bu sözleşmenin açık kalemi değil")
        if kalem.equipment_id == ekipman_id:
            continue
        acik_pb = await db.scalar(
            select(ServiceOrder.so_no).where(
                ServiceOrder.contract_item_id == kalem.id,
                ServiceOrder.tur == "PB",
                ServiceOrder.is_deleted.is_(False),
                ServiceOrder.status.in_(sorted(_ACIK)),
            )
        )
        if acik_pb:
            raise BakimHatasi(
                f"{acik_pb} açıkken kalemin ekipmanı değiştirilemez",
                veri={"kod": "ACIK_PB", "isler": [acik_pb]},
            )
        if ekipman_id is not None:
            ekipman = await db.get(ServiceEquipment, ekipman_id)
            if (
                ekipman is None
                or ekipman.is_deleted
                or kapsam.birim_disinda_mi(user, ekipman.birim, birimsiz_gorunur=False)
            ):
                raise BakimKapsamDisi("Ekipman bulunamadı")
            if (
                ekipman.account_id != sozlesme.account_id
                or ekipman.birim != sozlesme.birim
                or ekipman.equipment_type != kalem.equipment_type
            ):
                raise ServisGirdiHatasi(
                    "Ekipman sözleşmenin carisine, birimine ve kalem türüne uymuyor"
                )
            if not ekipman.is_active or ekipman.merged_into_id is not None:
                raise ServisGirdiHatasi("Pasif/birleştirilmiş ekipman bağlanamaz")
            baska = (await _bagli_ekipmanlar(db, haric_kalem=kalem.id)).get(ekipman_id)
            if baska:
                raise BakimHatasi(
                    f"Ekipman zaten {baska} sözleşmesinin kapsamında",
                    veri={"kod": "EKIPMAN_BAGLI", "sozlesme": baska},
                )
        degisen.append({"kalem_id": kalem.id, "eski": kalem.equipment_id, "yeni": ekipman_id})
        kalem.equipment_id = ekipman_id
        kalem.updated_by = user.id
    await db.flush()
    if degisen:
        await audit.log(
            db,
            "maintenance_contracts",
            "bakim.kapsam.eslestir",
            entity_id=sozlesme.id,
            new_value={"eslesmeler": degisen},
            user_id=user.id,
            ip=ip,
        )


async def eslestirme_orani(db: AsyncSession, user: User | None = None) -> dict[str, Any]:
    """AKTIF sözleşmelerin PB'ye uygun açık kalemlerinde ekipman bağı oranı.

    `user` verilirse kapsamlı (ekran), verilmezse genel (ayar kapısı).
    Kalem yoksa oran 100 sayılır: eşleştirilecek bir şey yoktur.
    """
    stmt = (
        select(
            func.count(MaintenanceContractItem.id),
            func.count(MaintenanceContractItem.equipment_id),
        )
        .join(MaintenanceContract, MaintenanceContract.id == MaintenanceContractItem.contract_id)
        .where(
            MaintenanceContract.status == "AKTIF",
            MaintenanceContract.is_deleted.is_(False),
            MaintenanceContractItem.is_deleted.is_(False),
            MaintenanceContractItem.valid_to.is_(None),
            MaintenanceContractItem.pb_uygun.is_(True),
        )
    )
    if user is not None:
        stmt = sozlesme_kapsami(stmt, user)
    toplam, eslesen = (await db.execute(stmt)).one()
    toplam, eslesen = int(toplam or 0), int(eslesen or 0)
    yuzde = 100.0 if toplam == 0 else round(100.0 * eslesen / toplam, 1)
    return {"toplam": toplam, "eslesen": eslesen, "yuzde": yuzde}


async def otomatik_uretim_ayarla(
    db: AsyncSession, acik: bool, *, user: User, ip: str | None = None
) -> dict[str, Any]:
    """`bakim_otomatik_uretim` yalnız bu kapıdan açılır: eşleştirme %100
    değilse 409. Genel ayar olduğu için tüm birimleri gören (TUMU) kullanıcı
    değiştirir — birim şefi diğer birimlerin eksiğini göremez."""
    if user.role is None or user.role.scope != SCOPE_ALL:
        raise PermissionError("Otomatik üretimi yalnız tüm birimleri gören kullanıcı değiştirir")
    oran = await eslestirme_orani(db)
    if acik and oran["yuzde"] < 100:
        raise BakimHatasi(
            f"Sözleşme–ekipman eşleştirmesi %{oran['yuzde']} ({oran['eslesen']}/"
            f"{oran['toplam']}). Otomatik PB üretimi eşleştirme %100 olmadan açılamaz.",
            veri={"kod": "ESLESTIRME_EKSIK", "oran": oran},
        )
    onceki = bool(await ayar_svc.get(db, "bakim_otomatik_uretim"))
    if onceki != acik:
        await ayar_svc.set_many(db, {"bakim_otomatik_uretim": acik}, user.id)
        await audit.log(
            db,
            "settings",
            "bakim.otomatik_uretim",
            old_value={"bakim_otomatik_uretim": onceki},
            new_value={"bakim_otomatik_uretim": acik, "oran": oran},
            user_id=user.id,
            ip=ip,
        )
    return {"acik": acik, "oran": oran}


# =============================================================================
# Uyarılar (TS-069) — `s/uyarilar.py` toplayıcısına kayıtlı, birim kapsamlı
# =============================================================================


async def bitis_uyari_gun(db: AsyncSession) -> int:
    """`bakim_sozlesme_bitis_uyari_gun` ayarı (uyarı ve liste süzgeci AYNI değeri kullanır)."""
    deger = await ayar_svc.get(db, "bakim_sozlesme_bitis_uyari_gun")
    return int(deger) if deger is not None else BITIS_UYARI_GUN


async def bakim_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Geciken dönem, teyit bekleyen ve bitişi yaklaşan sözleşme."""
    bugun = yerel_bugun(clock)
    tolerans = int(await ayar_svc.get(db, "bakim_tolerans_gun") or 0)
    geciken = await db.scalar(
        sozlesme_kapsami(
            select(func.count(MaintenancePeriod.id))
            .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
            .where(
                MaintenanceContract.is_deleted.is_(False),
                MaintenanceContract.status == "AKTIF",
                gecikme_kosulu(bugun, tolerans),
            ),
            user,
        )
    )
    teyit = await db.scalar(
        sozlesme_kapsami(
            select(func.count(MaintenanceContract.id)).where(
                MaintenanceContract.is_deleted.is_(False),
                MaintenanceContract.status == "TEYIT_BEKLIYOR",
            ),
            user,
        )
    )
    simdi = clock.now()
    bitis_gun = await bitis_uyari_gun(db)
    biten = await db.scalar(
        sozlesme_kapsami(
            select(func.count(MaintenanceContract.id)).where(
                MaintenanceContract.is_deleted.is_(False),
                MaintenanceContract.status == "AKTIF",
                MaintenanceContract.valid_to > simdi,
                MaintenanceContract.valid_to <= simdi + timedelta(days=bitis_gun),
            ),
            user,
        )
    )
    return [
        Uyari(
            kod="BAKIM_GECIKEN_DONEM",
            baslik="Geciken bakım dönemi",
            adet=int(geciken or 0),
            yol="/bakim?sekme=donemler&gecikmis=1",
            onem="uyari",
            aciklama=f"Hedef tarihi {tolerans} günlük toleransı aşmış, kapanmamış dönemler.",
        ),
        Uyari(
            kod="BAKIM_TEYIT_BEKLEYEN",
            baslik="Teyit bekleyen bakım sözleşmesi",
            adet=int(teyit or 0),
            yol="/bakim?durum=TEYIT_BEKLIYOR",
            aciklama="Göç ya da ayrıştırmadan gelen, tarihi/kapsamı teyit edilmemiş sözleşmeler.",
        ),
        Uyari(
            kod="BAKIM_BITISI_YAKLASAN",
            baslik="Bitişi yaklaşan bakım sözleşmesi",
            adet=int(biten or 0),
            yol="/bakim?suresi_doluyor=1",
            aciklama=f"{bitis_gun} gün içinde biten aktif sözleşmeler.",
        ),
    ]


async def kapsam_disi_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Karar bekleyen kapsam dışı talepleri — kişinin KENDİ talebi hariç
    (kendi talebini onaylayamaz; sayıya girmesi yanlış iş gösterirdi)."""
    adet = await db.scalar(
        kapsam.kapsam_isler(
            select(func.count(MaintenanceExclusionRequest.id)).where(
                MaintenanceExclusionRequest.status == "TALEP",
                MaintenanceExclusionRequest.is_deleted.is_(False),
                MaintenanceExclusionRequest.requested_by != user.id,
            ),
            user,
            MaintenanceExclusionRequest.service_order_id,
        )
    )
    return [
        Uyari(
            kod="BAKIM_KAPSAM_DISI_TALEBI",
            baslik="Karar bekleyen kapsam dışı talebi",
            adet=int(adet or 0),
            yol="/bakim?sekme=kapsam-disi",
            onem="uyari",
            aciklama="Cihazın bakım döneminden çıkarılması için şef kararı bekleniyor.",
        )
    ]


# =============================================================================
# Ek kapsamı ve KVKK (kayıt noktaları)
# =============================================================================


async def _sozlesme_ek_kapsami(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    """`maintenance_contracts` ekleri: sözleşmenin birim + müşteri kapsamı."""
    sozlesme = await db.get(MaintenanceContract, entity_id)
    if sozlesme is None:
        return True  # varlık kontrolü API'de (404)
    if sozlesme.is_deleted:
        return False
    return not await sozlesme_disinda_mi(db, user, sozlesme)


async def _kvkk_denetim_kosullari(db: AsyncSession, account_id: int) -> list:
    """Hesap anonimleştirilirken sözleşme denetim satırları da maskelenir:
    `log_change` irtibat bağını ve serbest notları taşıyabilir."""
    from app.services import kvkk

    idler = list(
        (
            await db.scalars(
                select(MaintenanceContract.id).where(MaintenanceContract.account_id == account_id)
            )
        ).all()
    )
    return [kvkk.denetim_hesap_kosulu("maintenance_contracts", account_id, idler)]


async def _kvkk_metinleri_anonimlestir(db: AsyncSession, account_id: int, _clock: Clock) -> dict:
    """TS-069: hesap anonimleştirilirken bakım serbest metinleri silinir.

    Sözleşme notu ve ham müşteri/tesis adı (bireysel müşteride kişinin adı),
    form teknisyen notu ve kapsam dışı talep açıklaması kişi adı/telefonu
    taşıyabilir ("Ahmet Bey'e teslim edildi"). Satırlar DURUR (dönem, PB ve
    ziyaret geçmişi sayıyla çalışır); yalnız metin gider.
    """
    from sqlalchemy import update

    from app.models import MaintenanceExclusionRequest, MaintenanceForm, ServiceOrder
    from app.services import kvkk

    sozlesme = await db.execute(
        update(MaintenanceContract)
        .where(MaintenanceContract.account_id == account_id)
        .values(
            notes=None,
            customer_name_raw=None,
            site_name_raw=None,
            version=MaintenanceContract.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    so_idler = select(ServiceOrder.id).where(ServiceOrder.customer_id == account_id)
    form = await db.execute(
        update(MaintenanceForm)
        .where(
            MaintenanceForm.service_order_id.in_(so_idler),
            MaintenanceForm.technician_note.is_not(None),
        )
        .values(technician_note=None, version=MaintenanceForm.version + 1)
        .execution_options(synchronize_session=False)
    )
    talep = await db.execute(
        update(MaintenanceExclusionRequest)
        .where(MaintenanceExclusionRequest.service_order_id.in_(so_idler))
        # `description` NOT NULL + boş olamaz (ck_mer_aciklama): işaretle değiştirilir.
        .values(description=kvkk.ANONIM_ISARETI, decision_note=None)
        .execution_options(synchronize_session=False)
    )
    return {
        "bakim_sozlesme_notu": sozlesme.rowcount or 0,
        "bakim_form_notu": form.rowcount or 0,
        "bakim_kapsam_disi_notu": talep.rowcount or 0,
    }


def sozlesme_satiri(
    sozlesme: MaintenanceContract,
    *,
    musteri: Account | None,
    tesis: Address | None,
    clock: Clock,
    maliyet: bool,
) -> dict[str, Any]:
    """Liste/detay ortak çıktısı. Ücret alanları `maliyet` false iken YOK."""
    satir: dict[str, Any] = {
        "id": sozlesme.id,
        "contract_no": sozlesme.contract_no,
        "birim": sozlesme.birim,
        "status": sozlesme.status,
        "sonraki_durumlar": sorted(BAKIM_SOZLESMESI.sonraki(sozlesme.status)),
        "account_id": sozlesme.account_id,
        "musteri": musteri.title if musteri else sozlesme.customer_name_raw,
        "address_id": sozlesme.address_id,
        "tesis": (tesis.site_name or tesis.label) if tesis else sozlesme.site_name_raw,
        "il": tesis.city if tesis else None,
        "contact_id": sozlesme.contact_id,
        "responsible_user_id": sozlesme.responsible_user_id,
        # Sözleşme dönemi yerel gün olarak (yarı açık: bitiş günü kapsam dışı).
        "baslangic": yerel_gun(sozlesme.valid_from).isoformat() if sozlesme.valid_from else None,
        "bitis": yerel_gun(sozlesme.valid_to).isoformat() if sozlesme.valid_to else None,
        "annual_frequency": sozlesme.annual_frequency,
        "fixed_months": sozlesme.fixed_months,
        "suresi_doldu": bool(sozlesme.valid_to and sozlesme.valid_to <= clock.now()),
        "teyit_gerekcesi": sozlesme.teyit_gerekcesi,
        "notes": sozlesme.notes,
        "version": sozlesme.version,
    }
    if maliyet:
        satir.update({k: getattr(sozlesme, k) for k in UCRET_ALANLARI})
    return satir


# --- Kayıtlar (modül sonu; `s/__init__` sabit sırayla import eder) -----------------

ts_uyarilar.kaydet("bakim", "bakim.gor", bakim_uyarilari)
ts_uyarilar.kaydet("bakim", "bakim.onayla", kapsam_disi_uyarilari)
ek_kapsam.kaydet("maintenance_contracts", _sozlesme_ek_kapsami)


def _kvkk_kaydet() -> None:
    from app.services import kvkk

    kvkk.denetim_maske_kaydet("maintenance_contracts", _kvkk_denetim_kosullari)
    kvkk.anonimlestirme_kaydet(_kvkk_metinleri_anonimlestir)


_kvkk_kaydet()
