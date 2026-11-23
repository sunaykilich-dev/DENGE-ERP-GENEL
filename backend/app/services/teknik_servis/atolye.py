"""Atölye: kabul, durum, teslim, garanti, seri geçmişi, aksesuar, belge bağlamı (E05).

Maddeler: TS-090…101 (+ TS-102 atölye kancası). D2-B.

**Tek karar (E05 §1.1): 1 atölye kaydı = 1 cihaz = 1 servis işi.** Kabul
servis işini (`tur='ATOLYE'`, kategori ATOLYE) ve atölye kaydını AYNI
transaction'da açar; yetim ATOLYE işi oluşamaz (genel açılış ucu bu türü
zaten reddeder: `TUR_KURALLARI['ATOLYE'].yalniz_sistem`). İş kimliği, müşteri,
birim, ATAMA, zaman, parça, bekleme, olay geçmişi ve ekler servis işindedir;
seri/marka/model ekipman kütüğündedir (bileşik FK `fk_atolye_servis_ekipman`).

**Durum tek yerden yürür.** Atölye durumu `ATOLYE` makinesiyle yalnız
`durum_degistir` içinde ilerler; servis işinin durumu aynı transaction'da
eşlemeyle (`SERVIS_DURUMU`) yürür (E05 kontrol B1/B3):

| Atölye | Servis işi |
|---|---|
| açık durumlar (KABUL…KARGOYA_VERILDI, bekleme dışı) | ATOLYEDE |
| ONAY / PARCA / DIS_SERVIS bekleyen | BEKLEMEDE — E01 `beklet()` (BEKLEME_NEDENI) |
| TESLIM_EDILDI | TAMAMLANDI (`kaynak='atolye'`, sonuç kanalı ATOLYE) |
| IPTAL | IPTAL (gerekçe `cancel_reason`) |

KAPATILDI otomatik değildir (E01 K1: hiçbir iş otomatik kapanmaz; şef kapatır).
Geri alma geçişleri servis işini etkilemez.

**Genel uçlar kilitli (TS-090):** `durum_dogrula` kancası
(`atolye_gecis_dogrula`) ATOLYE türündeki işte `atolye` (bu modül), `kapat`
(şefin TAMAMLANDI→KAPATILDI'sı) ve bu modülün sürdüğü `bekleme` dışındaki
her kaynağı 409 + yönlendirmeyle reddeder: genel durum, bekleme aç/kapat,
sonuç, iptal ve yeniden açma. "Bu modülün sürdüğü bekleme", süreç içi bir
`ContextVar` ile ayırt edilir (eşzamanlı istekler karışmaz).

**Kişisel veri (TS-101):** `delivered_to_name` ve `approved_by_name` olay
geçmişine YAZILMAZ (olay satırı silinemez, anonimleştirilemez); denetime
`is_personal_data=True` ayrı satırla yazılır ve hesap anonimleştirilince
temizlenir/maskelenir (kancalar dosyanın sonunda).

**Fiyat (TS-092):** `repair_amount` yalnız `maliyet.gor` sahibince okunur ve
yazılır; izinsiz kullanıcının gönderdiği tutar SESSİZCE yok sayılır, olay
geçmişine tutar hiç yazılmaz, belge bağlamına anahtar olarak girmez.

Saat yalnız Clock'tan (`received_at`, `delivered_at`, `cargo_sent_at`,
`completed_at` istemciden alınmaz). Servis fonksiyonları `flush` eder,
`commit` ETMEZ; transaction sınırı API'dir.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select, text
from sqlalchemy import update as sa_update

from app.models import (
    Account,
    Contact,
    Product,
    Quote,
    ServiceEquipment,
    ServiceFaultReason,
    ServiceOrder,
    ServiceOrderEvent,
    StockMovement,
    WorkshopAccessory,
    WorkshopRecord,
)
from app.models.servis_atolye import (
    AKSESUAR_TURLERI,
    ATOLYE_ACIK_OLMAYAN,
    ATOLYE_DURUMLARI,
    ATOLYE_ONARIM_KATEGORILERI,
    ATOLYE_ONAY_KANALLARI,
    ATOLYE_ONAY_KARARLARI,
    ATOLYE_SERVIS_TURLERI,
    ATOLYE_TESLIM_TIPLERI,
    ATOLYE_TEST_SONUCLARI,
)
from app.models.servis_ekipman import EKIPMAN_TIPLERI
from app.services import audit, kvkk
from app.services import settings as ayar_svc
from app.services.normalize import normalize_seri, tr_normkey
from app.services.statemachine import ATOLYE, IzinsizGecis
from app.services.teknik_servis import (
    atama,
    bekletme,
    ekipman,
    gecmis,
    is_emirleri,
    kancalar,
    kapsam,
    sonuc,
    zaman,
)
from app.services.teknik_servis.ana_veri import AnaVeriHatasi, lokasyon_dogrula
from app.services.teknik_servis.atolye_rapor import DURUM_ADLARI, SERVIS_TURU_ADLARI
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_an, yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

ENTITY = "workshop_records"
VARSAYILAN_BIRIM = "HABERLESME"
VARSAYILAN_TIP = "TELSIZ"
TOPLU_KABUL_UST_SINIR = 100
GEREKCE_UZUNLUGU = 500


class AtolyeHatasi(ServisHatasi):
    """Atölye iş kuralı ihlali → API 409. `veri` 409 gövdesine konur (aday listesi)."""

    def __init__(self, mesaj: str, *, veri: dict[str, Any] | None = None):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.veri = veri or {}


class AtolyeYetkiHatasi(ServisHatasi):
    """Geçiş için ek izin yok (iptal/geri alma `servis.kapat`) → API 403."""


class AtolyeBulunamadi(LookupError):
    """Kayıt yok ya da kapsam dışı → 404 (hiçbir yazma yapılmadan)."""


# --- Eşleme (TS-090; meta-test `tests/unit/test_atolye_esleme.py`) ------------------

# Atölye durumu → servis işi hedef durumu.
SERVIS_DURUMU: dict[str, str] = {
    "KABUL_EDILDI": "ATOLYEDE",
    "TESHISTE": "ATOLYEDE",
    "ONAY_BEKLIYOR": "BEKLEMEDE",
    "ONARIMDA": "ATOLYEDE",
    "PARCA_BEKLIYOR": "BEKLEMEDE",
    "DIS_SERVISTE": "BEKLEMEDE",
    "TEST_KONTROL": "ATOLYEDE",
    "TESLIME_HAZIR": "ATOLYEDE",
    "ONARILMADAN_IADE": "ATOLYEDE",
    "KARGOYA_VERILDI": "ATOLYEDE",
    "TESLIM_EDILDI": "TAMAMLANDI",
    "IPTAL": "IPTAL",
}
# BEKLEMEDE'ye eşlenen atölye durumu → E01 bekleme nedeni (katalog kodu).
BEKLEME_NEDENI: dict[str, str] = {
    "ONAY_BEKLIYOR": "MUSTERI_ONAYI",
    "PARCA_BEKLIYOR": "MALZEME",
    "DIS_SERVISTE": "DIS_SERVIS",
}
# Geri alma geçişleri: gerekçe + `servis.kapat`; servis işini etkilemez.
GERI_ALMALAR: frozenset[tuple[str, str]] = frozenset(
    {
        ("TESLIME_HAZIR", "ONARIMDA"),
        ("ONARILMADAN_IADE", "TESHISTE"),
        ("KARGOYA_VERILDI", "TESLIME_HAZIR"),
    }
)
# Onarılamaz / reddedilmiş kayıtta gidilemeyen hedefler.
ONARIM_HEDEFLERI = frozenset(
    {"ONAY_BEKLIYOR", "ONARIMDA", "PARCA_BEKLIYOR", "DIS_SERVISTE", "TEST_KONTROL", "TESLIME_HAZIR"}
)
TAMAMLANMA_DURUMLARI = frozenset({"TESLIME_HAZIR", "ONARILMADAN_IADE"})

ONARIM_ADLARI: dict[str, str] = {
    "PARCA_DEGISIMI": "Parça değişimi",
    "LEHIM_KART_ONARIMI": "Lehim / kart onarımı",
    "YAZILIM_YUKLEME": "Yazılım yükleme",
    "FREKANS_PROGRAMLAMA": "Frekans programlama",
    "TEMIZLIK_BAKIM": "Temizlik / bakım",
    "AYAR_KALIBRASYON": "Ayar / kalibrasyon",
    "ISLEM_YAPILMADI": "İşlem yapılmadı",
    "DIGER": "Diğer",
}
AKSESUAR_ADLARI: dict[str, str] = {
    "BATARYA": "Batarya",
    "SARJ_UNITESI": "Şarj ünitesi",
    "SARJ_ADAPTORU": "Şarj adaptörü",
    "ANTEN": "Anten",
    "KEMER_KLIPSI": "Kemer klipsi",
    "KILIF": "Kılıf",
    "KULAKLIK": "Kulaklık",
    "HARICI_MIKROFON": "Harici mikrofon",
    "KABLO": "Kablo",
    "DIGER": "Diğer",
}
TESLIM_TIPI_ADLARI: dict[str, str] = {
    "ELDEN": "Elden",
    "KARGO": "Kargo",
    "KURYE": "Kurye",
    "SAHA": "Sahada",
}

# Olay geçmişine yazılamayan anahtarlar (kişisel veri; satır silinemez).
OLAY_YASAK_ANAHTARLAR = frozenset(
    {"delivered_to_name", "approved_by_name", "teslim_alan", "onaylayan"}
)
# Denetimde ayrı, `is_personal_data=True` satıra giden alanlar.
KISISEL_ALANLAR = frozenset({"delivered_to_name", "approved_by_name"})

# PATCH ile düzeltilebilen alanlar ve olay grubu.
ALAN_GRUPLARI: dict[str, str] = {
    "customer_complaint": "GENEL",
    "physical_condition": "GENEL",
    "estimated_finish_date": "GENEL",
    "logo_form_no": "GENEL",
    "logo_main_service_no": "GENEL",
    "integration_company": "GENEL",
    "project_name": "GENEL",
    "notes": "GENEL",
    "fault_reason_id": "TESHIS",
    "diagnosis_note": "TESHIS",
    "is_repairable": "TESHIS",
    "repair_category": "ONARIM",
    "repair_note": "ONARIM",
    "test_result": "TEST",
    "approval_decision": "ONAY",
    "approval_channel": "ONAY",
    "approved_by_name": "ONAY",
    "approval_note": "ONAY",
    "repair_amount": "BEDEL",
    "external_vendor_id": "DIS_SERVIS",
    "external_rma_no": "DIS_SERVIS",
    "external_sent_at": "DIS_SERVIS",
    "external_returned_at": "DIS_SERVIS",
}
DUZELTILEBILIR = frozenset(ALAN_GRUPLARI)

# Bu modülün kendi sürdüğü E01 bekleme geçişi (genel bekleme ucu ise kilitli).
_ATOLYE_SURUYOR: ContextVar[bool] = ContextVar("atolye_suruyor", default=False)


@contextlib.contextmanager
def _atolye_suruyor() -> Iterator[None]:
    belirtec = _ATOLYE_SURUYOR.set(True)
    try:
        yield
    finally:
        _ATOLYE_SURUYOR.reset(belirtec)


# --- Girdi sınıfları -----------------------------------------------------------------


@dataclass
class EkipmanSecimi:
    """Kabul edilen cihaz: kütükten seçilmiş (`ekipman_id`) ya da tip+marka+seri ile
    bul-veya-aç. Garanti tarihleri yalnız YENİ açılan ekipmana yazılır."""

    ekipman_id: int | None = None
    tip: str = VARSAYILAN_TIP
    marka: str | None = None
    model: str | None = None
    seri: str | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    mukerrer_gerekce: str | None = None


@dataclass
class AksesuarGirdisi:
    kind: str
    qty: int = 1
    description: str | None = None


@dataclass
class KabulGirdisi:
    customer_id: int
    service_type: str
    receive_type: str
    customer_complaint: str
    ekipman: EkipmanSecimi = field(default_factory=EkipmanSecimi)
    birim: str = VARSAYILAN_BIRIM
    address_id: int | None = None
    contact_id: int | None = None
    oncelik: str = "NORMAL"
    physical_condition: str | None = None
    estimated_finish_date: date | None = None
    aksesuarlar: list[AksesuarGirdisi] = field(default_factory=list)
    notes: str | None = None
    logo_form_no: str | None = None
    logo_main_service_no: str | None = None
    integration_company: str | None = None
    project_name: str | None = None
    # Sistem çağrıları (toplu kabul, kiralama köprüsü TS-102).
    intake_group_no: int | None = None
    rental_asset_id: int | None = None
    # Seri okutma (2026-11-23): cihaz serisinin nasıl girildiği (`seri_okutma.SeriOkuma`;
    # `seri_no` yok sayılır, kütükteki seri kullanılır). Tekil ekran kabulünde
    # `okutma_denetimi` açıktır; toplu ve kiralık kabul kural dışıdır.
    seri_okuma: Any | None = None
    okutma_denetimi: bool = False


@dataclass
class AksesuarIadesi:
    id: int
    returned: bool
    not_: str | None = None


@dataclass
class TeslimGirdisi:
    teslim_alan: str | None = None
    teslim_tipi: str | None = None
    kargo_firmasi: str | None = None
    takip_no: str | None = None
    aksesuar_iade: list[AksesuarIadesi] = field(default_factory=list)
    aciklama: str | None = None
    # KARARLAR 2026-11-20 §4: telsiz biriminde kargo/teslim öncesi seri okutma.
    okutulan_seriler: list[str] | None = None
    seri_aciklama: str | None = None


def _bos(deger: Any) -> Any:
    if isinstance(deger, str):
        return deger.strip() or None
    return deger


def _json(deger: Any) -> Any:
    if deger is None or isinstance(deger, str | int | float | bool):
        return deger
    if isinstance(deger, date | datetime):
        return deger.isoformat()
    return str(deger)


# --- Numara ---------------------------------------------------------------------------


async def atolye_no_uret(db: AsyncSession, clock: Clock) -> str:
    """`AT-YYYYAA-NNNNNN` (`atolye_no_seq`, plan §1.6). Ay kabul anının Türkiye ayı."""
    sira = int(await db.scalar(text("SELECT nextval('atolye_no_seq')")))
    return f"AT-{yerel_bugun(clock):%Y%m}-{sira:06d}"


async def kabul_grubu_no(db: AsyncSession) -> int:
    """Toplu kabul grubu (salt sayı, `atolye_kabul_grubu_seq`)."""
    return int(await db.scalar(text("SELECT nextval('atolye_kabul_grubu_seq')")))


# --- Kapsam ---------------------------------------------------------------------------


async def kayit_getir(db: AsyncSession, so_id: int) -> WorkshopRecord | None:
    return await db.scalar(
        select(WorkshopRecord).where(
            WorkshopRecord.service_order_id == so_id, WorkshopRecord.is_deleted.is_(False)
        )
    )


async def kapsamli_kayit(
    db: AsyncSession, user: User, so_id: int
) -> tuple[ServiceOrder, WorkshopRecord]:
    """Servis işi KAPSAMIYLA, sonra atölye kaydı; yoksa `AtolyeBulunamadi` (404).

    Kapsam kontrolü kayıt aranmadan ÖNCE: kapsam dışı işin atölye kaydı olup
    olmadığı da sızmasın.
    """
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise AtolyeBulunamadi("Atölye kaydı bulunamadı")
    kayit = await kayit_getir(db, so.id)
    if kayit is None:
        raise AtolyeBulunamadi("Atölye kaydı bulunamadı")
    return so, kayit


# --- Ekipman bul-veya-aç ve garanti (TS-097) -------------------------------------------


async def ekipman_adaylari(
    db: AsyncSession, user: User, *, tip: str, marka: str | None, seri: str | None
) -> list[ServiceEquipment]:
    """Kapsam içi aktif ekipmanlar: tip + marka anahtarı + seri anahtarı (E03 normalleştirici)."""
    seri_anahtari = normalize_seri(seri) if seri else None
    if not seri_anahtari:
        return []
    marka_anahtari = (tr_normkey(marka) or None) if marka else None
    stmt = select(ServiceEquipment).where(
        ServiceEquipment.equipment_type == tip,
        ServiceEquipment.brand_key.is_not_distinct_from(marka_anahtari),
        ServiceEquipment.serial_key == seri_anahtari,
        ServiceEquipment.is_active.is_(True),
        ServiceEquipment.is_deleted.is_(False),
    )
    stmt = ekipman.ekipman_kosulu(user)(stmt)
    return list((await db.scalars(stmt.order_by(ServiceEquipment.id))).all())


async def ekipman_bul_veya_ac(
    db: AsyncSession,
    secim: EkipmanSecimi,
    *,
    birim: str,
    customer_id: int,
    address_id: int | None,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceEquipment:
    """Kütükten seçili ekipman ya da (tip, marka, seri) eşleşmesi; yoksa E03 tek
    yazma kapısıyla (`ekipman.olustur`) açar. `ekipman.yaz` izni ARANMAZ
    (E05-D01: kabul personeli HABERLESME ekipmanı açabilir); birim kapsamı
    ekipman servisinde yine uygulanır.

    Kapsam içinde birden çok aktif eşleşme → 409 + aday listesi.
    """
    if secim.ekipman_id is not None:
        try:
            e = await ekipman.kapsamli_ekipman(db, user, secim.ekipman_id)
        except ekipman.EkipmanBulunamadi as exc:
            raise AtolyeBulunamadi("Ekipman bulunamadı") from exc
        if not e.is_active:
            raise AtolyeHatasi("Pasif ekipman için atölye kaydı açılamaz")
        if e.birim != birim:
            raise ServisGirdiHatasi("Ekipman bu birime ait değil")
        if not e.serial_no:
            raise ServisGirdiHatasi("Seri numarası olmayan ekipman atölyeye alınamaz")
        return e
    if secim.tip not in EKIPMAN_TIPLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen ekipman tipi: {secim.tip}")
    marka = _bos(secim.marka)
    seri = _bos(secim.seri)
    if not marka:
        raise ServisGirdiHatasi("Marka zorunlu")
    if not seri:
        raise ServisGirdiHatasi("Seri numarası zorunlu")
    adaylar = await ekipman_adaylari(db, user, tip=secim.tip, marka=marka, seri=seri)
    if len(adaylar) > 1:
        raise AtolyeHatasi(
            "Bu seri numarasıyla birden çok aktif ekipman var; listeden birini seçin",
            veri={
                "kod": "COKLU_EKIPMAN",
                "adaylar": [
                    {
                        "id": e.id,
                        "tip": e.equipment_type,
                        "marka": e.brand,
                        "model": e.model,
                        "seri": e.serial_no,
                        "account_id": e.account_id,
                    }
                    for e in adaylar
                ],
            },
        )
    if adaylar:
        return adaylar[0]
    try:
        return await ekipman.olustur(
            db,
            ekipman.EkipmanGirdisi(
                birim=birim,
                equipment_type=secim.tip,
                account_id=customer_id,
                address_id=address_id,
                brand=marka,
                model=_bos(secim.model),
                serial_no=seri,
                warranty_start=secim.warranty_start,
                warranty_end=secim.warranty_end,
                duplicate_ack_reason=_bos(secim.mukerrer_gerekce),
            ),
            user=user,
            clock=clock,
            ip=ip,
        )
    except ekipman.EkipmanBulunamadi as exc:
        raise AtolyeBulunamadi(str(exc) or "Bulunamadı") from exc
    except ekipman.EkipmanHatasi as exc:
        raise AtolyeHatasi(exc.mesaj, veri=exc.veri) from exc
    except AnaVeriHatasi as exc:
        if exc.kod == 409:
            raise AtolyeHatasi(exc.mesaj, veri=exc.veri) from exc
        raise ServisGirdiHatasi(exc.mesaj) from exc


async def acik_kayit(db: AsyncSession, equipment_id: int) -> WorkshopRecord | None:
    return await db.scalar(
        select(WorkshopRecord).where(
            WorkshopRecord.equipment_id == equipment_id,
            WorkshopRecord.status.not_in(ATOLYE_ACIK_OLMAYAN),
            WorkshopRecord.is_deleted.is_(False),
        )
    )


async def _tekrar_gelis_gun(db: AsyncSession) -> int:
    return int(await ayar_svc.get(db, "atolye_tekrar_gelis_gun"))


async def son_onarim(
    db: AsyncSession, equipment_id: int, clock: Clock, *, haric_id: int | None = None
) -> WorkshopRecord | None:
    """Pencere (`atolye_tekrar_gelis_gun`) içinde ONARILARAK teslim edilmiş son kayıt."""
    sinir = clock.now() - timedelta(days=await _tekrar_gelis_gun(db))
    stmt = select(WorkshopRecord).where(
        WorkshopRecord.equipment_id == equipment_id,
        WorkshopRecord.status == "TESLIM_EDILDI",
        WorkshopRecord.test_result == "GECTI",
        WorkshopRecord.delivered_at >= sinir,
        WorkshopRecord.is_deleted.is_(False),
    )
    if haric_id is not None:
        stmt = stmt.where(WorkshopRecord.id != haric_id)
    return await db.scalar(stmt.order_by(WorkshopRecord.delivered_at.desc()).limit(1))


async def garanti_hesapla(
    db: AsyncSession, e: ServiceEquipment, clock: Clock
) -> tuple[str, date | None]:
    """Kabulde HESAPLANIR ve DONDURULUR (RMA kalıbı; tarihler ekipmanda, E05 kontrol B7).

    - ekipmanın garanti bitişi yok → BELIRSIZ ("Garanti Değil" varsayılanı yazılmaz);
    - bitiş ≥ kabul günü → GARANTI_ICI; bitiş < kabul günü → GARANTI_DISI;
    - üretici garantisi dışında ve aynı cihaz pencere içinde onarılarak
      teslim edilmişse → ONARIM_GARANTISI (Denge'nin kendi onarım garantisi).
    """
    bugun = yerel_bugun(clock)
    bitis = e.warranty_end
    if bitis is None:
        durum = "BELIRSIZ"
    elif bitis >= bugun:
        durum = "GARANTI_ICI"
    else:
        durum = "GARANTI_DISI"
    if durum != "GARANTI_ICI" and await son_onarim(db, e.id, clock) is not None:
        durum = "ONARIM_GARANTISI"
    return durum, bitis


# --- Olay ve denetim ---------------------------------------------------------------------


async def olay_yaz(
    db: AsyncSession,
    so: ServiceOrder,
    kayit: WorkshopRecord,
    alt_tur: str,
    ozet: str,
    *,
    user: User | None,
    clock: Clock,
    veri: dict[str, Any] | None = None,
    serbest_metin: str | None = None,
) -> ServiceOrderEvent:
    """ATOLYE olayı (`veri.alt_tur` ile ayrım; E05 kontrol B10).

    Teslim alan ve onaylayan ADI olaya yazılamaz: anahtar olarak verilirse
    `KisiselVeriHatasi`; kullanıcının yazdığı serbest metinde (gerekçe)
    geçerse 400.
    """
    yuk = {"alt_tur": alt_tur, "atolye_no": kayit.atolye_no, **(veri or {})}
    yasak = sorted(k for k in yuk if str(k).lower() in OLAY_YASAK_ANAHTARLAR)
    if yasak:
        raise gecmis.KisiselVeriHatasi(
            f"Olay geçmişine kişisel veri yazılamaz ({', '.join(yasak)})"
        )
    kucuk = (serbest_metin or "").casefold()
    for ad in (kayit.delivered_to_name, kayit.approved_by_name):
        if kucuk and ad and len(ad.strip()) >= 3 and ad.strip().casefold() in kucuk:
            raise ServisGirdiHatasi("Gerekçeye teslim alan ya da onaylayan adı yazılamaz")
    try:
        return await gecmis.olay_yaz(db, so, "ATOLYE", ozet, user=user, clock=clock, veri=yuk)
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Gerekçeye irtibat adı veya telefonu yazılamaz") from exc


async def _denetim(
    db: AsyncSession,
    kayit: WorkshopRecord,
    so: ServiceOrder,
    eylem: str,
    *,
    eski: dict[str, Any] | None,
    yeni: dict[str, Any] | None,
    user: User | None,
    ip: str | None,
) -> None:
    """Genel alanlar ve kişisel alanlar AYRI satıra (kişisel olan maskelenebilsin)."""
    eski, yeni = eski or {}, yeni or {}
    hesap = {"hesap": so.customer_id}
    genel_e = {k: v for k, v in eski.items() if k not in KISISEL_ALANLAR}
    genel_y = {k: v for k, v in yeni.items() if k not in KISISEL_ALANLAR}
    kisi_e = {k: v for k, v in eski.items() if k in KISISEL_ALANLAR}
    kisi_y = {k: v for k, v in yeni.items() if k in KISISEL_ALANLAR}
    kimlik = user.id if user is not None else None
    if genel_e or genel_y or not (kisi_e or kisi_y):
        await audit.log(
            db,
            ENTITY,
            eylem,
            entity_id=kayit.id,
            old_value={**hesap, **genel_e} if genel_e else None,
            new_value={**hesap, "atolye_no": kayit.atolye_no, **genel_y},
            user_id=kimlik,
            ip=ip,
        )
    if kisi_e or kisi_y:
        await audit.log(
            db,
            ENTITY,
            f"{eylem}.kisisel",
            entity_id=kayit.id,
            old_value={**hesap, **kisi_e} if kisi_e else None,
            new_value={**hesap, **kisi_y},
            user_id=kimlik,
            ip=ip,
            is_personal_data=True,
        )


# --- Aksesuar (TS-096) ---------------------------------------------------------------------


def aksesuar_dogrula(satirlar: list[AksesuarGirdisi]) -> list[AksesuarGirdisi]:
    temiz = []
    for s in satirlar:
        if s.kind not in AKSESUAR_TURLERI:
            raise ServisGirdiHatasi(f"Bilinmeyen aksesuar türü: {s.kind}")
        if s.qty is None or int(s.qty) <= 0:
            raise ServisGirdiHatasi("Aksesuar adedi en az 1 olmalı")
        aciklama = _bos(s.description)
        if s.kind == "DIGER" and not aciklama:
            raise ServisGirdiHatasi("'Diğer' aksesuarda açıklama zorunlu")
        temiz.append(AksesuarGirdisi(kind=s.kind, qty=int(s.qty), description=aciklama))
    return temiz


async def aksesuarlar(db: AsyncSession, kayit: WorkshopRecord) -> list[WorkshopAccessory]:
    return list(
        (
            await db.scalars(
                select(WorkshopAccessory)
                .where(WorkshopAccessory.workshop_record_id == kayit.id)
                .order_by(WorkshopAccessory.id)
            )
        ).all()
    )


async def _aksesuar_ekle(
    db: AsyncSession, kayit: WorkshopRecord, satirlar: list[AksesuarGirdisi], user: User
) -> None:
    for s in satirlar:
        db.add(
            WorkshopAccessory(
                workshop_record_id=kayit.id,
                kind=s.kind,
                qty=s.qty,
                description=s.description,
                created_by=user.id,
            )
        )
    await db.flush()


async def aksesuarlari_yaz(
    db: AsyncSession,
    kayit: WorkshopRecord,
    so: ServiceOrder,
    satirlar: list[AksesuarGirdisi],
    *,
    version: int,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> list[WorkshopAccessory]:
    """Listenin TAMAMINI değiştirir; teslim/iptal sonrası 409, sürüm uyuşmazlığı 409."""
    if version != kayit.version:
        raise AtolyeHatasi("Kayıt başka bir kullanıcı tarafından değiştirildi; yenileyin")
    if kayit.status in ATOLYE_ACIK_OLMAYAN:
        raise AtolyeHatasi("Teslim edilmiş ya da iptal edilmiş kaydın aksesuarları değişmez")
    temiz = aksesuar_dogrula(satirlar)
    mevcut = await aksesuarlar(db, kayit)
    eski = [{"kind": a.kind, "qty": a.qty, "description": a.description} for a in mevcut]
    for a in mevcut:
        await db.delete(a)
    await db.flush()
    await _aksesuar_ekle(db, kayit, temiz, user)
    kayit.updated_by = user.id  # sürüm artar (iyimser kilit)
    await db.flush()
    yeni = [{"kind": a.kind, "qty": a.qty, "description": a.description} for a in temiz]
    await _denetim(
        db,
        kayit,
        so,
        "atolye.aksesuar",
        eski={"aksesuarlar": eski},
        yeni={"aksesuarlar": yeni},
        user=user,
        ip=ip,
    )
    await olay_yaz(
        db,
        so,
        kayit,
        "AKSESUAR",
        f"Aksesuar listesi güncellendi ({len(temiz)} satır)",
        user=user,
        clock=clock,
        veri={"satir": len(temiz)},
    )
    return await aksesuarlar(db, kayit)


# --- Kabul (TS-090/096/097/100) -----------------------------------------------------------


def _kabul_dogrula(veri: KabulGirdisi) -> None:
    if veri.service_type not in ATOLYE_SERVIS_TURLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen servis türü: {veri.service_type}")
    if veri.receive_type not in ATOLYE_TESLIM_TIPLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen kabul tipi: {veri.receive_type}")
    sikayet = _bos(veri.customer_complaint)
    if not sikayet or len(sikayet) < 3:
        raise ServisGirdiHatasi("Müşteri şikâyeti en az 3 karakter olmalı")


def _konu(e: ServiceEquipment, sikayet: str) -> str:
    cihaz = " ".join(x for x in (e.brand, e.model) if x) or "Cihaz"
    metin = f"Atölye: {cihaz} — {sikayet}"
    return metin if len(metin) <= 200 else metin[:199] + "…"


async def kabul(
    db: AsyncSession,
    veri: KabulGirdisi,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> WorkshopRecord:
    """İş + kayıt tek transaction; ATOLYE kategorili servis işi açar, numara `atolye_no_seq`.

    - birim kullanıcının kapsamı dışında → 404 (`AtolyeBulunamadi`);
    - müşteri kapsam dışı → 404; müşteri-lokasyon-irtibat tutarsız → 400;
    - aynı cihazın açık atölye kaydı → 409 (kapsam içindeyse mevcut numarayla);
    - durum istemciden ALINMAZ: kayıt KABUL_EDILDI, servis işi ATOLYEDE doğar;
      kabul anı sunucu Clock'u.
    """
    from app.services.accounts import kapsam_disinda_mi

    _kabul_dogrula(veri)
    if kapsam.birim_disinda_mi(user, veri.birim, birimsiz_gorunur=False):
        raise AtolyeBulunamadi("Birim bulunamadı")
    if await kapsam_disinda_mi(db, user, veri.customer_id):
        raise AtolyeBulunamadi("Müşteri bulunamadı")
    try:
        await lokasyon_dogrula(db, veri.customer_id, veri.address_id, veri.contact_id)
    except AnaVeriHatasi as exc:
        raise ServisGirdiHatasi(exc.mesaj) from exc
    temiz_aksesuar = aksesuar_dogrula(veri.aksesuarlar)
    e = await ekipman_bul_veya_ac(
        db,
        veri.ekipman,
        birim=veri.birim,
        customer_id=veri.customer_id,
        address_id=veri.address_id,
        user=user,
        clock=clock,
        ip=ip,
    )
    mevcut = await acik_kayit(db, e.id)
    if mevcut is not None:
        mevcut_so = await db.get(ServiceOrder, mevcut.service_order_id)
        gorunur = mevcut_so is not None and not await kapsam.is_erisimi_yok_mu(db, user, mevcut_so)
        raise AtolyeHatasi(
            f"Bu cihazın açık atölye kaydı var: {mevcut.atolye_no}"
            if gorunur
            else "Bu cihazın başka bir birimde açık atölye kaydı var",
            veri={
                "kod": "ACIK_KAYIT",
                "atolye_no": mevcut.atolye_no if gorunur else None,
                "so_id": mevcut.service_order_id if gorunur else None,
            },
        )
    durum, bitis = await garanti_hesapla(db, e, clock)
    sikayet = _bos(veri.customer_complaint)
    try:
        so = await is_emirleri.olustur(
            db,
            is_emirleri.ServisIsiGirdisi(
                birim=veri.birim,
                tur="ATOLYE",
                konu=_konu(e, sikayet),
                customer_id=veri.customer_id,
                address_id=veri.address_id,
                contact_id=veri.contact_id,
                oncelik=veri.oncelik,
                aciklama=sikayet,
                seriler=[e.serial_no] if e.serial_no else [],
                equipment_id=e.id,
                seri_okumalari=[replace(veri.seri_okuma, seri_no=e.serial_no)]
                if veri.seri_okuma is not None and e.serial_no
                else [],
                okutma_denetimi=veri.okutma_denetimi,
            ),
            user=user,
            clock=clock,
        )
        await is_emirleri.durum_degistir(
            db, so, "ATOLYEDE", kaynak="atolye", user=user, clock=clock
        )
    except is_emirleri.IsEmriKapsamDisi as exc:
        raise AtolyeBulunamadi(str(exc)) from exc
    simdi = clock.now()
    kayit = WorkshopRecord(
        atolye_no=await atolye_no_uret(db, clock),
        service_order_id=so.id,
        equipment_id=e.id,
        intake_group_no=veri.intake_group_no,
        service_type=veri.service_type,
        status="KABUL_EDILDI",
        received_at=simdi,
        received_by=user.id,
        receive_type=veri.receive_type,
        contact_id=veri.contact_id,
        customer_complaint=sikayet,
        physical_condition=_bos(veri.physical_condition),
        estimated_finish_date=veri.estimated_finish_date,
        warranty_status=durum,
        warranty_end_snapshot=bitis,
        notes=_bos(veri.notes),
        logo_form_no=_bos(veri.logo_form_no),
        logo_main_service_no=_bos(veri.logo_main_service_no),
        integration_company=_bos(veri.integration_company),
        project_name=_bos(veri.project_name),
        rental_asset_id=veri.rental_asset_id,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(kayit)
    await db.flush()
    await _aksesuar_ekle(db, kayit, temiz_aksesuar, user)
    await olay_yaz(
        db,
        so,
        kayit,
        "KABUL",
        f"Atölyeye kabul edildi: {kayit.atolye_no} ({SERVIS_TURU_ADLARI[kayit.service_type]})",
        user=user,
        clock=clock,
        veri={
            "service_type": kayit.service_type,
            "warranty_status": durum,
            "aksesuar": len(temiz_aksesuar),
            "kabul_grubu": kayit.intake_group_no,
        },
    )
    await _denetim(
        db,
        kayit,
        so,
        "atolye.kabul",
        eski=None,
        yeni={
            "so_no": so.so_no,
            "equipment_id": e.id,
            "service_type": kayit.service_type,
            "warranty_status": durum,
            "kabul_grubu": kayit.intake_group_no,
        },
        user=user,
        ip=ip,
    )
    return kayit


async def toplu_kabul(
    db: AsyncSession,
    ortak: KabulGirdisi,
    cihazlar: list[tuple[EkipmanSecimi, list[AksesuarGirdisi], str | None]],
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> list[WorkshopRecord]:
    """Aynı müşteriden N cihaz → N kayıt + N servis işi, ortak kabul grubu (TS-100).

    Hepsi ya da hiçbiri: bir cihazda hata (açık kayıt 409, çoklu eşleşme 409 ...)
    tüm transaction'ı düşürür (çağıran commit etmez). Gruptaki aynı seri iki
    kez verilirse 400.
    """
    if not cihazlar:
        raise ServisGirdiHatasi("En az bir cihaz girilmeli")
    if len(cihazlar) > TOPLU_KABUL_UST_SINIR:
        raise ServisGirdiHatasi(f"Toplu kabulde en çok {TOPLU_KABUL_UST_SINIR} cihaz olur")
    anahtarlar = [
        (s.ekipman_id, s.tip, tr_normkey(s.marka or ""), normalize_seri(s.seri or ""))
        for s, _, _ in cihazlar
    ]
    if len(set(anahtarlar)) != len(anahtarlar):
        raise ServisGirdiHatasi("Aynı cihaz grupta iki kez girilmiş")
    grup = await kabul_grubu_no(db)
    kayitlar = []
    for secim, aksesuar, sikayet in cihazlar:
        tek = KabulGirdisi(
            **{
                **ortak.__dict__,
                "ekipman": secim,
                "aksesuarlar": aksesuar,
                "customer_complaint": sikayet or ortak.customer_complaint,
                "intake_group_no": grup,
            }
        )
        kayitlar.append(await kabul(db, tek, user=user, clock=clock, ip=ip))
    return kayitlar


async def kiralik_kabul(
    db: AsyncSession,
    cihaz: Any,
    *,
    aciklama: str,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> WorkshopRecord:
    """Arızalı dönen kiralık cihaz → KIRALAMA_TAKIP atölye kaydı (TS-102, E05-27).

    Kiralama modülünün dönüş kontrolü çağırır; cihazın envanter hareketini
    (HAZIR_DEGIL → ATOLYEDE) kiralama tarafı yazar, bu fonksiyon yalnız olağan
    kabul kapısından (`kabul`) geçer — kapsam, açık kayıt engeli, olay ve
    denetim aynı kalır. Müşteri = cihazın son kiralamasının kiracısı (E05-27);
    kiralanmamış cihaz için atölye kaydı açılamaz (409). Ekipman kütükte
    (tip, marka, seri) ile bulunur ya da açılır; marka ürün kartından gelir.
    """
    from app.models import Product, Rental, RentalAllocation

    kiraci = await db.scalar(
        select(Rental.customer_id)
        .join(RentalAllocation, RentalAllocation.rental_id == Rental.id)
        .where(RentalAllocation.asset_id == cihaz.id)
        .order_by(RentalAllocation.id.desc())
        .limit(1)
    )
    if kiraci is None:
        raise AtolyeHatasi(
            "Cihaz hiç kiralanmamış; atölye kaydı kiracı olmadan açılamaz, "
            "cihazı atölyeye olağan kabulle alın"
        )
    urun = await db.get(Product, cihaz.product_id)
    marka = _bos(getattr(urun, "brand", None)) or _bos(getattr(urun, "name", None)) or "—"
    sikayet = _bos(aciklama) or "Arızalı"
    return await kabul(
        db,
        KabulGirdisi(
            customer_id=int(kiraci),
            service_type="KIRALAMA_TAKIP",
            receive_type="ELDEN",
            customer_complaint=f"Kiralık dönüş kontrolü: {sikayet}"[:500],
            birim=cihaz.birim,
            ekipman=EkipmanSecimi(
                tip=VARSAYILAN_TIP if cihaz.birim == VARSAYILAN_BIRIM else "DIGER",
                marka=marka[:60],
                model=_bos(getattr(urun, "model", None)),
                seri=cihaz.serial_no,
            ),
            rental_asset_id=cihaz.id,
        ),
        user=user,
        clock=clock,
        ip=ip,
    )


# --- Düzeltme (PATCH, TS-093/094/098)---------------------------------------------------------


async def _ariza_nedeni_dogrula(db: AsyncSession, so: ServiceOrder, neden_id: int | None) -> None:
    if neden_id is None:
        return
    neden = await db.get(ServiceFaultReason, neden_id)
    if neden is None or not neden.is_active:
        raise ServisGirdiHatasi("Arıza nedeni katalogda yok ya da pasif")
    if neden.birim != so.birim:
        raise ServisGirdiHatasi("Arıza nedeni bu işin birimine ait değil")


async def guncelle(
    db: AsyncSession,
    kayit: WorkshopRecord,
    so: ServiceOrder,
    degisiklikler: dict[str, Any],
    *,
    version: int,
    user: User,
    clock: Clock,
    maliyet_gorur: bool,
    ip: str | None = None,
) -> WorkshopRecord:
    """Tanımlayıcı/veri alanlarını düzeltir; DURUM DEĞİŞMEZ (durum yalnız `durum_degistir`).

    - sürüm uyuşmazlığı 409; teslim/iptal edilmiş kayıt 409;
    - `repair_amount`: `maliyet_gorur` değilse SESSİZCE yok sayılır;
    - teşhis/test/onay alanı değişince ilgili kişi ve an Clock'tan damgalanır;
    - `ONAY_GEREKMEZ` gerekçesiz 400; dış servis dönüş < gönderim 400;
    - olay yalnız teşhis/onarım/test/onay/dış servis grubunda ve ALAN ADLARIYLA
      yazılır (tutar ve onaylayan adı olaya girmez).
    """
    if version != kayit.version:
        raise AtolyeHatasi("Kayıt başka bir kullanıcı tarafından değiştirildi; yenileyin")
    if kayit.status in ATOLYE_ACIK_OLMAYAN:
        raise AtolyeHatasi("Teslim edilmiş ya da iptal edilmiş atölye kaydı düzeltilemez")
    veri = {k: _bos(v) for k, v in degisiklikler.items() if k in DUZELTILEBILIR}
    if not maliyet_gorur:
        veri.pop("repair_amount", None)
    yeni = {k: v for k, v in veri.items() if getattr(kayit, k) != v}
    if not yeni:
        return kayit

    def son(alan: str) -> Any:
        return yeni[alan] if alan in yeni else getattr(kayit, alan)

    if "customer_complaint" in yeni and (
        not yeni["customer_complaint"] or len(yeni["customer_complaint"]) < 3
    ):
        raise ServisGirdiHatasi("Müşteri şikâyeti en az 3 karakter olmalı")
    if "fault_reason_id" in yeni:
        await _ariza_nedeni_dogrula(db, so, yeni["fault_reason_id"])
    if "repair_category" in yeni and yeni["repair_category"] not in (
        None,
        *ATOLYE_ONARIM_KATEGORILERI,
    ):
        raise ServisGirdiHatasi(f"Bilinmeyen onarım kategorisi: {yeni['repair_category']}")
    if "test_result" in yeni and yeni["test_result"] not in (None, *ATOLYE_TEST_SONUCLARI):
        raise ServisGirdiHatasi(f"Bilinmeyen test sonucu: {yeni['test_result']}")
    if "approval_decision" in yeni and yeni["approval_decision"] not in (
        None,
        *ATOLYE_ONAY_KARARLARI,
    ):
        raise ServisGirdiHatasi(f"Bilinmeyen onay kararı: {yeni['approval_decision']}")
    if "approval_channel" in yeni and yeni["approval_channel"] not in (
        None,
        *ATOLYE_ONAY_KANALLARI,
    ):
        raise ServisGirdiHatasi(f"Bilinmeyen onay kanalı: {yeni['approval_channel']}")
    if son("approval_decision") == "ONAY_GEREKMEZ" and not son("approval_note"):
        raise ServisGirdiHatasi("'Onay gerekmez' kararında gerekçe (onay notu) zorunlu")
    if "repair_amount" in yeni and yeni["repair_amount"] is not None:
        if Decimal(str(yeni["repair_amount"])) < 0:
            raise ServisGirdiHatasi("Tamir bedeli eksi olamaz")
    gonderim, donus = son("external_sent_at"), son("external_returned_at")
    if gonderim and donus and donus < gonderim:
        raise ServisGirdiHatasi("Dış servis dönüş tarihi gönderimden önce olamaz")
    if yeni.get("external_vendor_id") is not None:
        tedarikci = await db.get(Account, yeni["external_vendor_id"])
        if tedarikci is None or tedarikci.is_deleted:
            raise ServisGirdiHatasi("Dış servis firması bulunamadı")

    simdi = clock.now()
    eski = {k: _json(getattr(kayit, k)) for k in yeni}
    for alan, deger in yeni.items():
        setattr(kayit, alan, deger)
    gruplar = {ALAN_GRUPLARI[k] for k in yeni}
    if "TESHIS" in gruplar:
        kayit.diagnosed_by, kayit.diagnosed_at = user.id, simdi
    if "test_result" in yeni:
        kayit.tested_by = user.id if yeni["test_result"] else None
        kayit.tested_at = simdi if yeni["test_result"] else None
    if {"approval_decision", "approval_channel"} & set(yeni):
        kayit.approval_at = simdi if kayit.approval_decision else None
    kayit.updated_by = user.id
    await db.flush()
    await _denetim(
        db,
        kayit,
        so,
        "atolye.guncelle",
        eski=eski,
        yeni={k: _json(v) for k, v in yeni.items()},
        user=user,
        ip=ip,
    )
    olay_gruplari = sorted(gruplar - {"GENEL", "BEDEL"})
    if olay_gruplari:
        await olay_yaz(
            db,
            so,
            kayit,
            olay_gruplari[0] if len(olay_gruplari) == 1 else "GUNCELLE",
            "Atölye bilgisi güncellendi: "
            + ", ".join(sorted(k for k in yeni if k != "repair_amount")),
            user=user,
            clock=clock,
            veri={
                "alanlar": sorted(
                    k for k in yeni if k not in KISISEL_ALANLAR and k != "repair_amount"
                )
            },
        )
    return kayit


async def ekipman_duzelt(
    db: AsyncSession,
    kayit: WorkshopRecord,
    so: ServiceOrder,
    *,
    marka: str | None,
    model: str | None,
    seri: str | None,
    gerekce: str,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> WorkshopRecord:
    """Seri/marka/model düzeltmesi TEK kaynakta (TS-090, E05-15): ekipman E03'ün yazma
    kapısıyla (`ekipman.guncelle`), işin seri satırı E01'in yazıcısıyla
    (`is_emirleri.serileri_yaz`) güncellenir; atölye kaydı ekipmanı FK ile
    izler. Olay servis işi geçmişine (`ATOLYE`/`DUZELTME`) + denetim.
    """
    gerekce = _bos(gerekce)
    if not gerekce or len(gerekce) < 5:
        raise ServisGirdiHatasi("Düzeltme gerekçesi zorunlu (en az 5 karakter)")
    e = await db.get(ServiceEquipment, kayit.equipment_id)
    degisiklik = {}
    if marka is not None and _bos(marka) != e.brand:
        degisiklik["brand"] = _bos(marka)
    if model is not None and _bos(model) != e.model:
        degisiklik["model"] = _bos(model)
    if seri is not None and _bos(seri) != e.serial_no:
        if not _bos(seri):
            raise ServisGirdiHatasi("Seri numarası boş bırakılamaz")
        degisiklik["serial_no"] = _bos(seri)
    if not degisiklik:
        return kayit
    eski_seri = e.serial_no
    try:
        await ekipman.guncelle(db, e, degisiklik, user=user, clock=clock, ip=ip)
    except ekipman.EkipmanHatasi as exc:
        raise AtolyeHatasi(exc.mesaj, veri=exc.veri) from exc
    if "serial_no" in degisiklik:
        # Kapalı işte `servis.kapat` + gerekçe kuralı E01'de uygulanır.
        await is_emirleri.serileri_yaz(
            db, so, [e.serial_no], user=user, clock=clock, gerekce=gerekce
        )
    kayit.updated_by = user.id
    await db.flush()
    await olay_yaz(
        db,
        so,
        kayit,
        "DUZELTME",
        f"Cihaz bilgisi düzeltildi ({', '.join(sorted(degisiklik))}) — gerekçe: {gerekce}",
        user=user,
        clock=clock,
        veri={"alanlar": sorted(degisiklik), "eski_seri": eski_seri, "yeni_seri": e.serial_no},
        serbest_metin=gerekce,
    )
    return kayit


# --- Durum (TS-090/093/094/096/098) ---------------------------------------------------------


async def _bagli_teklif_kabul_mu(db: AsyncSession, so: ServiceOrder) -> bool:
    return (
        await db.scalar(
            select(Quote.id)
            .where(
                Quote.service_order_id == so.id,
                Quote.status == "KABUL",
                Quote.is_deleted.is_(False),
            )
            .limit(1)
        )
    ) is not None


def _gerekce_gerekli(onceki: str, hedef: str) -> bool:
    return hedef == "IPTAL" or (onceki, hedef) in GERI_ALMALAR


async def gecis_engeli(
    db: AsyncSession, so: ServiceOrder, kayit: WorkshopRecord, hedef: str
) -> tuple[str, bool] | None:
    """İş kuralı ön kontrolü (makine geçişinden sonra): (metin, girdi_eksik_mi) ya da None.

    Eksik GİRDİ (teşhis alanları, dış servis firması/tarihi) API'de 400, kural
    ihlali (onaysız onarım, KALDI testinden sonra teslime hazır) 409 olur.

    Teslim/kargo GİRDİSİ gerektiren kurallar (`teslim`) burada değil,
    `durum_degistir`'de 400 olarak sınanır.
    """
    onceki = kayit.status
    if hedef == "IPTAL" or (onceki, hedef) in GERI_ALMALAR:
        return None
    if onceki == "TESHISTE" and (kayit.fault_reason_id is None or kayit.is_repairable is None):
        return "Teşhis tamamlanmadı: arıza nedeni ve onarılabilirlik girilmeli", True
    if kayit.is_repairable is False and hedef in ONARIM_HEDEFLERI:
        return "Onarılamaz işaretli cihaz yalnız onarılmadan iade edilir ya da iptal edilir", False
    if kayit.approval_decision == "REDDEDILDI" and hedef in ONARIM_HEDEFLERI:
        return "Müşteri onarımı reddetti: yalnız onarılmadan iade ya da iptal", False
    if hedef == "ONARIMDA" and onceki in ("TESHISTE", "ONAY_BEKLIYOR"):
        onayli = kayit.approval_decision in ("ONAYLANDI", "ONAY_GEREKMEZ")
        if kayit.warranty_status != "GARANTI_ICI" and not onayli:
            if not await _bagli_teklif_kabul_mu(db, so):
                return (
                    "Garanti içi olmayan cihazda onarım için müşteri onayı gerekli "
                    "(onaylandı / onay gerekmez ya da kabul edilmiş teklif)",
                    False,
                )
    if hedef == "TESLIME_HAZIR":
        if kayit.test_result != "GECTI":
            return "Test sonucu 'Geçti' olmadan teslime hazır yapılamaz", False
        if not kayit.repair_category:
            return "Onarım kategorisi girilmeden teslime hazır yapılamaz", False
    if hedef == "DIS_SERVISTE" and (kayit.external_vendor_id is None or not kayit.external_sent_at):
        return "Dış servise göndermek için firma ve gönderim tarihi girilmeli", True
    return None


def _yetkili_mi(user: User, onceki: str, hedef: str) -> bool:
    if not user.has("atolye.yaz"):
        return False
    return not _gerekce_gerekli(onceki, hedef) or user.has("servis.kapat")


async def sonraki_durumlar(
    db: AsyncSession, so: ServiceOrder, kayit: WorkshopRecord, user: User
) -> list[dict[str, Any]]:
    """Ekrana sunulan hedefler: makine ∩ izin ∩ iş kuralı ön kontrolü."""
    sonuc = []
    for hedef in [d for d in ATOLYE_DURUMLARI if d in ATOLYE.sonraki(kayit.status)]:
        sonuc.append(
            {
                "hedef": hedef,
                "ad": DURUM_ADLARI[hedef],
                "yetkili": _yetkili_mi(user, kayit.status, hedef),
                "gerekce_zorunlu": _gerekce_gerekli(kayit.status, hedef),
                "geri_alma": (kayit.status, hedef) in GERI_ALMALAR,
                "teslim_bilgisi": hedef in ("KARGOYA_VERILDI", "TESLIM_EDILDI"),
                "engel": (engel := await gecis_engeli(db, so, kayit, hedef)) and engel[0],
            }
        )
    return sonuc


async def _servis_isini_esle(
    db: AsyncSession,
    so: ServiceOrder,
    hedef: str,
    *,
    user: User,
    clock: Clock,
    gerekce: str | None,
) -> None:
    """Atölye hedefinin servis işi karşılığı (E01 fonksiyonlarıyla; alan doğrudan atanmaz)."""
    servis_hedefi = SERVIS_DURUMU[hedef]
    with _atolye_suruyor():
        if servis_hedefi == "BEKLEMEDE":
            neden = BEKLEME_NEDENI[hedef]
            aktif = await bekletme.aktif_bekleme(db, so)
            if aktif is not None and aktif.neden == neden and so.status == "BEKLEMEDE":
                return
            if so.status == "BEKLEMEDE":
                await bekletme.beklemeyi_bitir(db, so, user=user, clock=clock)
            await bekletme.beklet(
                db,
                so,
                neden,
                user=user,
                clock=clock,
                aciklama=f"Atölye: {DURUM_ADLARI[hedef]}",
                sistem=True,
            )
            return
        if so.status == "BEKLEMEDE" and servis_hedefi != "IPTAL":
            await bekletme.beklemeyi_bitir(db, so, user=user, clock=clock)
        if so.status == servis_hedefi:
            return
        await is_emirleri.durum_degistir(
            db, so, servis_hedefi, kaynak="atolye", user=user, clock=clock, gerekce=gerekce
        )


async def _onarilarak_mi(db: AsyncSession, so: ServiceOrder, kayit: WorkshopRecord) -> bool:
    """Teslim edilen cihaz onarıldı mı: son TESLIME_HAZIR/ONARILMADAN_IADE girişi hangisi."""
    if kayit.status == "TESLIME_HAZIR":
        return True
    if kayit.status == "ONARILMADAN_IADE":
        return False
    son = await db.scalar(
        select(ServiceOrderEvent.veri["yeni"].astext)
        .where(
            ServiceOrderEvent.service_order_id == so.id,
            ServiceOrderEvent.olay_turu == "ATOLYE",
            ServiceOrderEvent.veri["alt_tur"].astext == "DURUM",
            ServiceOrderEvent.veri["yeni"].astext.in_(sorted(TAMAMLANMA_DURUMLARI)),
        )
        .order_by(ServiceOrderEvent.olusma_zamani.desc(), ServiceOrderEvent.id.desc())
        .limit(1)
    )
    return son == "TESLIME_HAZIR"


async def _teslim_uygula(
    db: AsyncSession,
    so: ServiceOrder,
    kayit: WorkshopRecord,
    hedef: str,
    teslim: TeslimGirdisi | None,
    *,
    user: User,
    clock: Clock,
) -> tuple[dict[str, Any], list[str]]:
    """Kargo/teslim girdisini doğrular ve kayda yazar. (denetim değerleri, uyarılar)."""
    teslim = teslim or TeslimGirdisi()
    tip = _bos(teslim.teslim_tipi)
    if tip is not None and tip not in ATOLYE_TESLIM_TIPLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen teslim tipi: {tip}")
    simdi = clock.now()
    yeni: dict[str, Any] = {}
    uyarilar: list[str] = []
    seri_notu = await _seri_okutma_dogrula(db, so, teslim)
    if seri_notu:
        uyarilar.append(seri_notu)
    if hedef == "KARGOYA_VERILDI":
        firma, takip = _bos(teslim.kargo_firmasi), _bos(teslim.takip_no)
        if (tip or "KARGO") != "KARGO":
            raise ServisGirdiHatasi("Kargoya verilen cihazın teslim tipi Kargo olmalı")
        if not firma or not takip:
            raise ServisGirdiHatasi("Kargo firması ve takip numarası zorunlu")
        kayit.delivery_type, kayit.cargo_company, kayit.cargo_tracking_no = "KARGO", firma, takip
        kayit.cargo_sent_at = simdi
        if seri_notu:
            kayit.delivery_note = seri_notu
        yeni = {"delivery_type": "KARGO", "cargo_company": firma, "cargo_tracking_no": takip}
        if seri_notu:
            yeni["seri_farki"] = True
        return yeni, uyarilar
    # TESLIM_EDILDI
    alan = _bos(teslim.teslim_alan)
    if not alan:
        raise ServisGirdiHatasi("Teslim alan kişinin adı zorunlu")
    tip = tip or kayit.delivery_type
    if tip is None:
        raise ServisGirdiHatasi("Teslim tipi zorunlu")
    satirlar = await aksesuarlar(db, kayit)
    isaret = {i.id: i for i in teslim.aksesuar_iade}
    bilinmeyen = set(isaret) - {a.id for a in satirlar}
    if bilinmeyen:
        raise ServisGirdiHatasi("Aksesuar listesi güncel değil; sayfayı yenileyin")
    eksik_isaret = [a for a in satirlar if a.id not in isaret]
    if eksik_isaret:
        raise ServisGirdiHatasi(
            "Teslimde her aksesuar işaretlenmeli: "
            + ", ".join(AKSESUAR_ADLARI.get(a.kind, a.kind) for a in eksik_isaret)
        )
    eksikler = [a for a in satirlar if not isaret[a.id].returned]
    aciklama = _bos(teslim.aciklama)
    if eksikler and not aciklama:
        raise ServisGirdiHatasi("İade edilmeyen aksesuar var; teslim açıklaması zorunlu")
    for a in satirlar:
        a.returned = isaret[a.id].returned
        a.return_note = _bos(isaret[a.id].not_)
    if eksikler:
        uyarilar.append(
            "Eksik aksesuarla teslim edildi: "
            + ", ".join(AKSESUAR_ADLARI.get(a.kind, a.kind) for a in eksikler)
        )
    kayit.delivered_to_name = alan
    kayit.delivery_type = tip
    kayit.delivered_at = simdi
    notlar = [n for n in (aciklama, seri_notu) if n]
    kayit.delivery_note = " / ".join(notlar) if notlar else None
    yeni = {"delivered_to_name": alan, "delivery_type": tip, "eksik_aksesuar": len(eksikler)}
    if seri_notu:
        yeni["seri_farki"] = True
    return yeni, uyarilar


TELSIZ_BIRIMLERI = frozenset({"HABERLESME", "POC"})


async def _seri_okutma_dogrula(
    db: AsyncSession, so: ServiceOrder, teslim: TeslimGirdisi
) -> str | None:
    """Telsiz biriminde kargoya verirken/teslim ederken seriler yeniden okutulur.

    Okutulan seri kayıttakinden farklı ya da eksikse açıklama zorunlu (400);
    açıklamalı fark teslim notuna ve uyarıya yazılır (KARARLAR 2026-11-20 §4).
    Kayıtta seri yoksa okutma istenmez.
    """
    from app.services import settings as ayar_svc

    if so.birim not in TELSIZ_BIRIMLERI:
        return None
    if not await ayar_svc.get(db, "atolye_teslim_seri_okutma"):
        return None
    beklenen = {normalize_seri(s.seri_no): s.seri_no for s in so.seriler if s.removed_at is None}
    if not beklenen:
        return None
    okutulan = {
        normalize_seri(x): x.strip() for x in (teslim.okutulan_seriler or []) if x and x.strip()
    }
    if not okutulan:
        raise ServisGirdiHatasi("Cihazın seri numarası okutulmalı")
    eksik = [v for k, v in beklenen.items() if k not in okutulan]
    yanlis = [v for k, v in okutulan.items() if k not in beklenen]
    if not eksik and not yanlis:
        return None
    parcalar = []
    if eksik:
        parcalar.append("okutulmayan: " + ", ".join(eksik))
    if yanlis:
        parcalar.append("kayıtta olmayan: " + ", ".join(yanlis))
    fark = "; ".join(parcalar)
    aciklama = _bos(teslim.seri_aciklama)
    if not aciklama:
        raise ServisGirdiHatasi(f"Seri numarası tutmuyor ({fark}); açıklama zorunlu")
    return f"Seri okutma farkı ({fark}): {aciklama}"


async def durum_degistir(
    db: AsyncSession,
    kayit: WorkshopRecord,
    hedef: str,
    *,
    user: User,
    clock: Clock,
    gerekce: str | None = None,
    teslim: TeslimGirdisi | None = None,
    sure_eksik_onay: bool = False,
    ip: str | None = None,
) -> list[str]:
    """ATOLYE makinesi + iş kuralları + servis işi eşlemesi (kaynak='atolye').

    Hata sırası (hiçbiri yazmadan önce değil; API commit etmediği için yarım
    iş kalmaz): bilinmeyen hedef 400 → makine 409 (izinli liste) → izin 403
    (iptal/geri alma `servis.kapat`) → gerekçe 400 → iş kuralı 409 → teslim
    girdisi 400 → servis işi kuralları (açık sayaç, süre eksik onayı) 409.
    Uyarı listesi döner (ör. eksik aksesuarla teslim).
    """
    if hedef not in ATOLYE_DURUMLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen atölye durumu: {hedef}")
    onceki = kayit.status
    try:
        ATOLYE.dogrula(onceki, hedef)
    except IzinsizGecis:
        izinli = ", ".join(DURUM_ADLARI[d] for d in ATOLYE_DURUMLARI if d in ATOLYE.sonraki(onceki))
        if onceki == hedef:
            raise AtolyeHatasi(f"Kayıt zaten '{DURUM_ADLARI[hedef]}' durumunda") from None
        raise AtolyeHatasi(
            f"'{DURUM_ADLARI[onceki]}' durumundan '{DURUM_ADLARI[hedef]}' durumuna geçilemez. "
            f"İzin verilenler: {izinli or 'yok (terminal durum)'}",
            veri={"izinli": [d for d in ATOLYE_DURUMLARI if d in ATOLYE.sonraki(onceki)]},
        ) from None
    so = await db.get(ServiceOrder, kayit.service_order_id)
    if _gerekce_gerekli(onceki, hedef) and not user.has("servis.kapat"):
        raise AtolyeYetkiHatasi("Bu işlem için yetkiniz yok (servis.kapat)")
    gerekce = _bos(gerekce)
    if _gerekce_gerekli(onceki, hedef) and not gerekce:
        raise ServisGirdiHatasi("Bu geçiş için gerekçe zorunlu")
    if gerekce is not None and len(gerekce) > GEREKCE_UZUNLUGU:
        raise ServisGirdiHatasi(f"Gerekçe en çok {GEREKCE_UZUNLUGU} karakter olabilir")
    engel = await gecis_engeli(db, so, kayit, hedef)
    if engel:
        mesaj, girdi_eksik = engel
        raise ServisGirdiHatasi(mesaj) if girdi_eksik else AtolyeHatasi(mesaj)

    simdi = clock.now()
    denetim_yeni: dict[str, Any] = {"status": hedef}
    uyarilar: list[str] = []
    if hedef in ("KARGOYA_VERILDI", "TESLIM_EDILDI"):
        ek, uyarilar = await _teslim_uygula(db, so, kayit, hedef, teslim, user=user, clock=clock)
        denetim_yeni.update(ek)
    if (onceki, hedef) == ("TESLIME_HAZIR", "ONARIMDA"):
        # Geri alma = yeniden onarım: eski "Geçti" yeni bir test olmadan geçerli sayılmaz.
        kayit.test_result, kayit.tested_by, kayit.tested_at = None, None, None
    if hedef in TAMAMLANMA_DURUMLARI and kayit.completed_at is None:
        kayit.completed_at = simdi  # yalnız ilk kez; sonra değişmez

    if hedef == "TESLIM_EDILDI":
        onarildi = await _onarilarak_mi(db, so, kayit)
        yapilan = kayit.repair_note or (
            ONARIM_ADLARI.get(kayit.repair_category or "", "")
            if onarildi
            else "Onarılmadan iade edildi"
        )
        try:
            await sonuc.sonuc_kaydet(
                db,
                so,
                sonuc.SonucGirdisi(
                    sonuc="COZULDU" if onarildi else "COZULEMEDI",
                    cozum_kanali="ATOLYE",
                    yapilan_islem=yapilan or ("Atölyede onarıldı" if onarildi else "İade edildi"),
                    ariza_nedeni_id=kayit.fault_reason_id,
                ),
                user=user,
                clock=clock,
            )
        except gecmis.KisiselVeriHatasi as exc:
            raise ServisGirdiHatasi("Onarım notuna irtibat adı/telefonu yazılamaz") from exc
        await zaman.sure_eksik_kapanis_dogrula(db, so, onay=sure_eksik_onay, user=user, clock=clock)
    kayit.status = hedef
    kayit.updated_by = user.id
    await db.flush()
    await _servis_isini_esle(db, so, hedef, user=user, clock=clock, gerekce=gerekce)

    ozet = f"Atölye: {DURUM_ADLARI[onceki]} → {DURUM_ADLARI[hedef]}"
    if gerekce:
        ozet += f" — gerekçe: {gerekce}"
    await olay_yaz(
        db,
        so,
        kayit,
        "DURUM",
        ozet,
        user=user,
        clock=clock,
        veri={
            "onceki": onceki,
            "yeni": hedef,
            "geri_alma": (onceki, hedef) in GERI_ALMALAR,
            "servis_durumu": so.status,
        },
        serbest_metin=gerekce,
    )
    await _denetim(
        db,
        kayit,
        so,
        "atolye.durum.degistir",
        eski={"status": onceki},
        yeni={**denetim_yeni, **({"gerekce": gerekce} if gerekce else {})},
        user=user,
        ip=ip,
    )
    if hedef == "TESLIM_EDILDI":
        for fn in TESLIM_KANCALARI:
            await fn(db, kayit, user, clock)
    return uyarilar


# --- Atama (TS-091/100) ---------------------------------------------------------------------


async def ata(
    db: AsyncSession,
    so: ServiceOrder,
    atamalar: list[atama.AtamaSatiri],
    *,
    user: User,
    clock: Clock,
) -> None:
    """E01 `atama.ata` (tek atama kaynağı; atölye kaydı atama alanı TUTMAZ)."""
    await atama.ata(db, so, atamalar, user=user, clock=clock)


async def toplu_ata(
    db: AsyncSession,
    so_idler: list[int],
    atamalar: list[atama.AtamaSatiri],
    *,
    mod: str,
    user: User,
    clock: Clock,
) -> list[ServiceOrder]:
    """Seçili atölye kayıtlarının servis işlerine aynı ekip (hepsi ya da hiçbiri).

    Atölye kaydı olmayan iş 404 (hangisi söylenmez); kapsam/kapalı/birim
    kuralları `atama.toplu_ata`'dadır.
    """
    kimlikler = list(dict.fromkeys(so_idler))
    bulunan = set(
        (
            await db.scalars(
                select(WorkshopRecord.service_order_id).where(
                    WorkshopRecord.service_order_id.in_(kimlikler),
                    WorkshopRecord.is_deleted.is_(False),
                )
            )
        ).all()
    )
    if bulunan != set(kimlikler):
        raise atama.AtamaKapsamDisi("Seçilen kayıtlardan biri bulunamadı")
    return await atama.toplu_ata(db, kimlikler, atamalar, mod=mod, user=user, clock=clock)


# --- Seri geçmişi (TS-097) ---------------------------------------------------------------------


async def seri_gecmisi(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    ekipman_id: int | None = None,
    tip: str | None = None,
    marka: str | None = None,
    seri: str | None = None,
) -> dict[str, Any]:
    """Aynı cihazın önceki atölye kayıtları (kapsam dışı kayıt ne görünür ne sayılır).

    `tekrar_gelis`: pencere içinde onarılarak teslim edilmiş kayıt var →
    kabul ekranı "onarım garantisi olabilir" uyarısını gösterir. Bayrak
    saklanmaz; tarih ve ekipmandan türetilir.
    """
    if ekipman_id is not None:
        try:
            ekipmanlar = [await ekipman.kapsamli_ekipman(db, user, ekipman_id)]
        except ekipman.EkipmanBulunamadi as exc:
            raise AtolyeBulunamadi("Ekipman bulunamadı") from exc
    else:
        if tip is not None and tip not in EKIPMAN_TIPLERI:
            raise ServisGirdiHatasi(f"Bilinmeyen ekipman tipi: {tip}")
        ekipmanlar = await ekipman_adaylari(
            db, user, tip=tip or VARSAYILAN_TIP, marka=marka, seri=seri
        )
    if not ekipmanlar:
        return {"ekipmanlar": [], "kayitlar": [], "tekrar_gelis": False, "acik_kayit": None}
    idler = [e.id for e in ekipmanlar]
    stmt = (
        select(WorkshopRecord, ServiceOrder)
        .join(ServiceOrder, ServiceOrder.id == WorkshopRecord.service_order_id)
        .where(WorkshopRecord.equipment_id.in_(idler), WorkshopRecord.is_deleted.is_(False))
        .order_by(WorkshopRecord.received_at.desc())
    )
    stmt = kapsam.kapsam_isler(stmt, user, WorkshopRecord.service_order_id)
    satirlar = list((await db.execute(stmt)).all())
    neden_idler = {k.fault_reason_id for k, _ in satirlar if k.fault_reason_id}
    nedenler = dict(
        (
            await db.execute(
                select(ServiceFaultReason.id, ServiceFaultReason.ad).where(
                    ServiceFaultReason.id.in_(neden_idler or {0})
                )
            )
        ).all()
    )
    sinir = clock.now() - timedelta(days=await _tekrar_gelis_gun(db))
    tekrar = any(
        k.status == "TESLIM_EDILDI"
        and k.test_result == "GECTI"
        and k.delivered_at is not None
        and k.delivered_at >= sinir
        for k, _ in satirlar
    )
    acik = next((k for k, _ in satirlar if k.status not in ATOLYE_ACIK_OLMAYAN), None)
    return {
        "ekipmanlar": [
            {
                "id": e.id,
                "tip": e.equipment_type,
                "marka": e.brand,
                "model": e.model,
                "seri": e.serial_no,
                "warranty_end": e.warranty_end,
            }
            for e in ekipmanlar
        ],
        "kayitlar": [
            {
                "so_id": so.id,
                "atolye_no": k.atolye_no,
                "so_no": so.so_no,
                "received_at": k.received_at,
                "status": k.status,
                "ariza_nedeni": nedenler.get(k.fault_reason_id) if k.fault_reason_id else None,
                "repair_category": k.repair_category,
                "test_result": k.test_result,
                "delivered_at": k.delivered_at,
                "warranty_status": k.warranty_status,
            }
            for k, so in satirlar
        ],
        "tekrar_gelis": tekrar,
        "acik_kayit": (
            {"so_id": acik.service_order_id, "atolye_no": acik.atolye_no} if acik else None
        ),
        "pencere_gun": await _tekrar_gelis_gun(db),
    }


# --- Detay yardımcıları (parça, süre, teklif — salt okunur, TS-099) -----------------------------


async def parcalar(
    db: AsyncSession, so: ServiceOrder, *, maliyet_gorur: bool
) -> list[dict[str, Any]]:
    """Servis işine bağlı stok hareketleri (salt okunur). Maliyet anahtarı yalnız `maliyet.gor`."""
    satirlar = (
        await db.execute(
            select(StockMovement, Product.code, Product.name)
            .join(Product, Product.id == StockMovement.product_id)
            .where(StockMovement.service_order_id == so.id)
            .order_by(StockMovement.id)
        )
    ).all()
    sonuc = []
    for h, kod, ad in satirlar:
        satir = {
            "id": h.id,
            "urun_kodu": kod,
            "urun_adi": ad,
            "miktar": h.qty,
            "hareket_turu": h.hareket_turu,
            "created_at": h.created_at,
        }
        if maliyet_gorur:
            satir["birim_maliyet"] = h.unit_cost
        sonuc.append(satir)
    return sonuc


async def teklifler(db: AsyncSession, so: ServiceOrder) -> list[dict[str, Any]]:
    """Bağlı teklifler (numara + durum; tutar YOK — teklif ekranı ayrıca yetkilidir)."""
    return [
        {"id": q.id, "quote_no": q.quote_no, "status": q.status}
        for q in (
            await db.scalars(
                select(Quote)
                .where(Quote.service_order_id == so.id, Quote.is_deleted.is_(False))
                .order_by(Quote.id)
            )
        ).all()
    ]


# --- Belge bağlamı (TS-095; KD-18: bağlam modül servisinde) -----------------------------------


def _tarih(an: datetime | date | None, *, saat: bool = True) -> str | None:
    if an is None:
        return None
    if isinstance(an, datetime):
        yerel = yerel_an(an)
        return yerel.strftime("%d.%m.%Y %H:%M" if saat else "%d.%m.%Y")
    return an.strftime("%d.%m.%Y")


async def belge_verisi(db: AsyncSession, kayit: WorkshopRecord) -> dict[str, Any]:
    """PDF için kaydın düz sözlüğü (tutar DAHİL; bağlam fonksiyonu süzer)."""
    from app.models import User as Kullanici
    from app.services import belgeler

    so = await db.get(ServiceOrder, kayit.service_order_id)
    e = await db.get(ServiceEquipment, kayit.equipment_id)
    hesap = await db.get(Account, so.customer_id) if so.customer_id else None
    kisi = await db.get(Contact, kayit.contact_id) if kayit.contact_id else None
    kabul_eden = await db.get(Kullanici, kayit.received_by) if kayit.received_by else None
    neden = (
        await db.get(ServiceFaultReason, kayit.fault_reason_id) if kayit.fault_reason_id else None
    )
    return {
        "firma": belgeler.firma_bilgisi(await belgeler.ayar_haritasi(db)),
        "atolye_no": kayit.atolye_no,
        "so_no": so.so_no,
        "kabul_grubu": kayit.intake_group_no,
        "kabul_tarihi": _tarih(kayit.received_at),
        "kabul_eden": kabul_eden.full_name if kabul_eden else None,
        "kabul_tipi": TESLIM_TIPI_ADLARI.get(kayit.receive_type, kayit.receive_type),
        "musteri": hesap.title if hesap else so.customer_name_raw,
        "irtibat": kisi.full_name if kisi else None,
        "servis_turu": SERVIS_TURU_ADLARI.get(kayit.service_type, kayit.service_type),
        "cihaz": {
            "tip": e.equipment_type,
            "marka": e.brand,
            "model": e.model,
            "seri": e.serial_no,
        },
        "sikayet": kayit.customer_complaint,
        "fiziksel_durum": kayit.physical_condition,
        "tahmini_bitis": _tarih(kayit.estimated_finish_date),
        "garanti": kayit.warranty_status,
        "garanti_bitis": _tarih(kayit.warranty_end_snapshot),
        "aksesuarlar": [
            {
                "tur": AKSESUAR_ADLARI.get(a.kind, a.kind),
                "aciklama": a.description,
                "adet": a.qty,
                "iade": a.returned,
                "iade_notu": a.return_note,
            }
            for a in await aksesuarlar(db, kayit)
        ],
        "ariza_nedeni": neden.ad if neden else None,
        "teshis": kayit.diagnosis_note,
        "onarim": ONARIM_ADLARI.get(kayit.repair_category or "", None),
        "onarim_notu": kayit.repair_note,
        "test": kayit.test_result,
        "durum": DURUM_ADLARI.get(kayit.status, kayit.status),
        "teslim_alan": kayit.delivered_to_name,
        "teslim_tipi": TESLIM_TIPI_ADLARI.get(kayit.delivery_type or "", None),
        "teslim_tarihi": _tarih(kayit.delivered_at),
        "kargo_firmasi": kayit.cargo_company,
        "takip_no": kayit.cargo_tracking_no,
        "teslim_notu": kayit.delivery_note,
        "tamir_bedeli": kayit.repair_amount,
    }


def _baglam(kayit: dict[str, Any], baslik: str, *, goster_bedel: bool) -> dict[str, Any]:
    veri = dict(kayit)
    bedel = veri.pop("tamir_bedeli", None)
    baglam = {"baslik": baslik, "kayitlar": [veri], "toplu": False, "firma": veri.pop("firma")}
    if goster_bedel and bedel is not None:
        baglam["tamir_bedeli"] = bedel
    return baglam


def kabul_fisi_baglami(kayit: Any, *, goster_bedel: bool) -> dict[str, Any]:
    """PDF bağlamı; `goster_bedel` false ise tutar anahtarı bağlama hiç girmez.

    `kayit`: `belge_verisi` çıktısı (async yükleme ayrı; bu fonksiyon saftır).
    """
    return _baglam(kayit, "CİHAZ KABUL FİŞİ", goster_bedel=goster_bedel)


def teslim_tutanagi_baglami(kayit: Any, *, goster_bedel: bool) -> dict[str, Any]:
    """Teslim tutanağı bağlamı (aynı tutar kuralı)."""
    return _baglam(kayit, "CİHAZ TESLİM TUTANAĞI", goster_bedel=goster_bedel)


def grup_fisi_baglami(kayitlar: list[dict[str, Any]]) -> dict[str, Any]:
    """Toplu kabul fişi: N cihaz, tek fiş. Tutar hiç girmez (kabulde bedel yoktur)."""
    temiz = []
    firma = None
    for k in kayitlar:
        veri = dict(k)
        veri.pop("tamir_bedeli", None)
        firma = veri.pop("firma")
        temiz.append(veri)
    return {"baslik": "TOPLU CİHAZ KABUL FİŞİ", "kayitlar": temiz, "toplu": True, "firma": firma}


# --- Kancalar ----------------------------------------------------------------------------------


async def atolye_gecis_dogrula(db: AsyncSession, so: Any, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası: ATOLYE türündeki işte genel uçlar 409 (yalnız
    kaynak='atolye').

    İzinliler: `atolye` (bu modül), `kapat` (şef TAMAMLANDI→KAPATILDI) ve bu
    modülün sürdüğü `bekleme`. Genel durum, bekleme aç/kapat, sonuç, iptal,
    yeniden açma → 409 + "Atölye ekranından" yönlendirmesi. Atölye kaynağı da
    ATOLYE dışı işte kullanılamaz.
    """
    if so.tur != "ATOLYE":
        if kaynak == "atolye":
            raise AtolyeHatasi("Atölye geçişi yalnız atölye işinde kullanılır")
        return
    if kaynak in ("atolye", "kapat"):
        return
    if kaynak == "bekleme" and _ATOLYE_SURUYOR.get():
        return
    atolye_no = await db.scalar(
        select(WorkshopRecord.atolye_no).where(WorkshopRecord.service_order_id == so.id)
    )
    raise AtolyeHatasi(
        "Bu işin durumu Atölye ekranından değişir" + (f" ({atolye_no})" if atolye_no else ""),
        veri={"kod": "ATOLYE_YONLENDIR", "yol": f"/atolye/{so.id}"},
    )


# TS-102: teslimde çağrılan modül kancaları (kiralama envanteri kendi dosyasından kaydolur).
TeslimKancasi = Callable[["AsyncSession", WorkshopRecord, "User", "Clock"], Awaitable[None]]
TESLIM_KANCALARI: list[TeslimKancasi] = []


def teslim_kancasi_kaydet(fn: TeslimKancasi) -> TeslimKancasi:
    """Atölye kaydı TESLIM_EDILDI olunca aynı transaction'da çağrılır (idempotent kayıt).

    Kiralık cihaz köprüsü (D2-C, TS-102) kaydın `rental_asset_id`'sine bakıp
    envanter hareketini yazar; atölye modülü kiralama tablosuna dokunmaz.
    """
    if fn not in TESLIM_KANCALARI:
        TESLIM_KANCALARI.append(fn)
    return fn


async def _ekipman_gecmisi(db: AsyncSession, e: ServiceEquipment, user: User) -> list[dict]:
    """Ekipman kartı birleşik geçmişine atölye kayıtları (kapsam içi)."""
    stmt = (
        select(WorkshopRecord, ServiceOrder.so_no)
        .join(ServiceOrder, ServiceOrder.id == WorkshopRecord.service_order_id)
        .where(WorkshopRecord.equipment_id == e.id, WorkshopRecord.is_deleted.is_(False))
    )
    stmt = kapsam.kapsam_isler(stmt, user, WorkshopRecord.service_order_id)
    return [
        {
            "tarih": k.received_at,
            "tur": "ATOLYE",
            "baslik": f"{k.atolye_no} · {so_no} · {DURUM_ADLARI.get(k.status, k.status)}",
            "durum": k.status,
            "kaynak": ENTITY,
            "kaynak_id": k.id,
            "sure_dakika": None,
            "sure_eksik": False,
            "eslesme": "KIMLIK",
        }
        for k, so_no in (await db.execute(stmt)).all()
    ]


async def _kvkk_anonimlestir(db: AsyncSession, account_id: int, clock: Clock) -> dict[str, int]:
    """Hesabın atölye kayıtlarında teslim alan ve onaylayan adı temizlenir (TS-101).

    Teslim edilmiş kayıtta `ck_atolye_teslim` teslim alan adını zorunlu tutar
    (teslim yapıldığı bilgisi ticari kayıttır): ad anonim işaretiyle
    değiştirilir; diğer kayıtlarda ve onaylayanda NULL yapılır.
    """
    from sqlalchemy import case

    sonuc = await db.execute(
        sa_update(WorkshopRecord)
        .where(
            WorkshopRecord.service_order_id.in_(
                select(ServiceOrder.id).where(ServiceOrder.customer_id == account_id)
            ),
            (WorkshopRecord.delivered_to_name.is_not(None))
            | (WorkshopRecord.approved_by_name.is_not(None)),
        )
        .values(
            delivered_to_name=case(
                (WorkshopRecord.status == "TESLIM_EDILDI", kvkk.ANONIM_ISARETI), else_=None
            ),
            approved_by_name=None,
        )
        .execution_options(synchronize_session=False)
    )
    return {"atolye_kisisel": sonuc.rowcount or 0}


async def _kvkk_denetim_kosulu(db: AsyncSession, account_id: int) -> list:
    idler = list(
        (
            await db.scalars(
                select(WorkshopRecord.id).where(
                    WorkshopRecord.service_order_id.in_(
                        select(ServiceOrder.id).where(ServiceOrder.customer_id == account_id)
                    )
                )
            )
        ).all()
    )
    return [kvkk.denetim_hesap_kosulu(ENTITY, account_id, idler)]


async def _kvkk_veri_bul(db: AsyncSession, arama: kvkk.VeriBulAramasi) -> list[dict]:
    """İlgili kişi başvurusu: atölye kayıtlarında teslim alan / onaylayan adı."""
    if not arama.anahtar and not arama.hesap_idleri:
        return []
    kosullar = []
    if arama.anahtar:
        kosullar.append(kvkk._sql_katla(WorkshopRecord.delivered_to_name).contains(arama.anahtar))
        kosullar.append(kvkk._sql_katla(WorkshopRecord.approved_by_name).contains(arama.anahtar))
    if arama.hesap_idleri:
        kosullar.append(
            and_(
                ServiceOrder.customer_id.in_(arama.hesap_idleri),
                (WorkshopRecord.delivered_to_name.is_not(None))
                | (WorkshopRecord.approved_by_name.is_not(None)),
            )
        )
    from sqlalchemy import or_

    satirlar = (
        await db.execute(
            select(WorkshopRecord, ServiceOrder.customer_id)
            .join(ServiceOrder, ServiceOrder.id == WorkshopRecord.service_order_id)
            .where(or_(*kosullar))
            .order_by(WorkshopRecord.id)
            .limit(200)
        )
    ).all()
    return [
        {
            "id": k.id,
            "atolye_no": k.atolye_no,
            "hesap_id": hesap_id,
            "teslim_alan": k.delivered_to_name,
            "onaylayan": k.approved_by_name,
        }
        for k, hesap_id in satirlar
    ]


kancalar.kaydet("durum_dogrula", atolye_gecis_dogrula)
ekipman.gecmis_kaynagi_kaydet(_ekipman_gecmisi)
kvkk.anonimlestirme_kaydet(_kvkk_anonimlestir)
kvkk.denetim_maske_kaydet(ENTITY, _kvkk_denetim_kosulu)
kvkk.veri_bul_kaydet("atolye_kayitlari", _kvkk_veri_bul)

__all__ = [
    "BEKLEME_NEDENI",
    "GERI_ALMALAR",
    "SERVIS_DURUMU",
    "AtolyeBulunamadi",
    "AtolyeHatasi",
    "AtolyeYetkiHatasi",
]
