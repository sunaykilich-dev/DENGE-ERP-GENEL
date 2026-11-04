"""Saha zaman kaydı: sayaç, manuel kayıt, düzeltme, süre özeti (E09, TS-070…076).

**Tek tablo** (`service_time_entries`): canlı sayaç bölümü, elle girilen kayıt,
mola ve düzeltme aynı tabloda. Kişi aynı anda iki yerde olamaz: servis
YAZMADAN ÖNCE çakışan bölümü ve açık sayacı sorgular ve okunur mesaj verir
("10:00-10:30 MOLA (SRV-…) ile çakışıyor"); `ex_ste_kisi_cakisma` ve
`uq_ste_acik_kisi` yalnız eşzamanlı yarışın son savunmasıdır (E09 kontrol B7 —
global kısıt eşleyicisi kişi/iş adı veremez).

**Kayıt yoksa süre "eksik"tir, 0 DEĞİL** (`kisi_saat_dk=None`,
`sure_durumu=EKSIK`); `or 0` / `coalesce(...,0)` yasaktır (TS-075, birim
testiyle kilitli). Mola kişi-saate girmez (`KISI_SAATE_DAHIL`).

**GECIS sırası: kapat → flush → ekle.** Aynı flush'ta UPDATE ve INSERT birlikte
gitseydi `uq_ste_acik_kisi` ve EXCLUDE bir an iki açık bölüm görebilirdi;
açık `flush` sırayı kesinleştirir.

**Sahibi istisnası** (E09 §3.2): kişi KENDİ açık bölümünü iş erişimine ve
atamaya bakılmadan bitirebilir, geri alabilir, unuttum ile kapatabilir —
ataması kaldırılmış teknisyenin sayacı açık kalıp kişi-saati şişirmesin.
Başkasının bölümü 403.

**Worker sayacı asla kapatmaz** (K16): uydurma bitiş saati yazılmaz; uzun
sayaç yalnız uyarı üretir (`zaman_uyarilari`).

**İş başlat/bitir konumu (G7.8, Faz A):** canlı bölüm açılırken (`baslat`,
`gecis` yeni bölümü) ve kapanırken (`bitir`, `gecis` eski bölümü) istemcinin
okuduğu konum `bas_*` / `bit_*` kolonlarına yazılır. Konum gelmezse durum
`ALINAMADI` olur ("Konum bilgisi alınamadı"); işlem ASLA engellenmez.
Sürekli konum takibi yoktur (G10.3).

Servis katmanı commit yapmaz; commit API'dedir. Denetim izi ve olay geçmişi
aynı transaction'da, commit'ten önce yazılır.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, exists, func, not_, or_, select

from app.models import (
    ServiceHoldReason,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServiceResult,
    ServiceTimeEntry,
    User,
)
from app.models.teknik_servis import DURUM_GRUPLARI, KISI_SAATE_DAHIL
from app.services import audit
from app.services import settings as ayarlar
from app.services.teknik_servis import kancalar, kapsam, yerel_zaman
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


# --- Hata sınıfları (API → HTTP kodu) ---------------------------------------------


class ZamanHatasi(ServisHatasi):
    """Zaman kaydı kural ihlali → 409 (açık mesaj: hangi sayaç, hangi iş)."""


class ZamanGirdiHatasi(ServisGirdiHatasi):
    """Girdi hatası (gelecek bitiş, 1 dk altı, gerekçesiz düzeltme ...) → 400."""


class ZamanYetkiHatasi(PermissionError):
    """Başkasının bölümü / başkası adına kayıt (servis.planla yok) → 403."""


class ZamanKapsamDisi(LookupError):
    """Kayıt bulunamadı ya da kapsam dışı → 404 (varlığı sızdırılmaz)."""


# --- Sabitler ------------------------------------------------------------------------

# 18 saatlik bölüm sınırı kod sabitidir ve `ck_ste_azami_sure` ile aynıdır
# (plan §1.9: şemaya bağlı sınır ayardan değiştirilemez).
AZAMI_BOLUM = timedelta(hours=18)

# Hiç çalışılmamış ya da çalışmanın durumdan anlaşılamadığı durumlar: kayıt
# yoksa "eksik" DEĞİL, "beklenmiyor". Telefonla çözülen ya da planda bekleyen
# işi eksik saymak sayacı şişirirdi (E09 §2.4, denetimin "şişik sayaç" bulgusu).
# BEKLEMEDE ve TEKRAR_ACILDI da burada: iş sahaya hiç çıkmadan beklemeye
# alınabilir / yeniden açılabilir; tamamlandığında zaten EKSIK olarak görünür.
BEKLENMIYOR_DURUMLAR = frozenset(
    {"MUSTERI_TALEBI", "PLANLAMADA", "PLANLANDI", "BEKLEMEDE", "TEKRAR_ACILDI", "IPTAL"}
)
# Sahaya gidilmeden çözülen işlerde süre beklenmez (E01-06 çözüm kanalı).
UZAKTAN_KANALLAR = frozenset({"UZAKTAN", "TELEFON"})

SURE_DURUMLARI = ("TAM", "KISMI", "EKSIK", "BEKLENMIYOR")
SURE_EKSIK_DURUMLARI = frozenset({"EKSIK", "KISMI"})

# K4: sayaç yalnız bu geçişleri sürer (kaynak='sayac'); diğer durumlar değişmez.
_OTOMATIK_DURUM: dict[str, tuple[frozenset[str], str]] = {
    "YOL": (frozenset({"PLANLANDI"}), "YOLA_CIKILDI"),
    "SAHA": (frozenset({"PLANLANDI", "YOLA_CIKILDI"}), "SAHADA"),
}

FAALIYET_ADLARI = {
    "YOL": "Yol",
    "SAHA": "Saha",
    "UZAKTAN": "Uzaktan",
    "ATOLYE": "Atölye",
    "TEST": "Test",
    "BEKLEME": "Bekleme",
    "MOLA": "Mola",
    "DIGER": "Diğer",
}


# --- Veri sınıfları ---------------------------------------------------------------------


@dataclass
class ManuelKayitGirdisi:
    faaliyet: str
    started_at: datetime
    ended_at: datetime
    user_id: int | None = None  # başkası adına: servis.planla
    bekleme_nedeni: str | None = None
    gerekce: str | None = None
    konum_notu: str | None = None
    aciklama: str | None = None


KONUM_ALINAMADI_METNI = "Konum bilgisi alınamadı"


@dataclass(frozen=True)
class KonumOkuma:
    """İstemcinin `getCurrentPosition` okuması (G7.8). Koordinat yoksa
    (izin reddi, zaman aşımı, GPS yok) durum ALINAMADI'dır."""

    enlem: float | None = None
    boylam: float | None = None
    dogruluk_m: float | None = None

    @property
    def alindi(self) -> bool:
        """Koordinat var ve geçerli aralıkta mı (NaN/aralık dışı = alınamadı;
        konum hatası işlemi ASLA engellemez)."""
        if self.enlem is None or self.boylam is None:
            return False
        return -90 <= self.enlem <= 90 and -180 <= self.boylam <= 180


def _konum_yaz(bolum: ServiceTimeEntry, on: str, konum: KonumOkuma | None) -> None:
    """`bas`/`bit` konumunu yazar; konum yoksa ya da geçersizse ALINAMADI."""
    if konum is not None and konum.alindi:
        dogruluk = konum.dogruluk_m
        if dogruluk is not None and not (0 <= dogruluk <= 1_000_000):
            dogruluk = None  # NaN/uydurma doğruluk yazılmaz
        setattr(bolum, f"{on}_enlem", Decimal(str(round(konum.enlem, 6))))  # type: ignore[arg-type]
        setattr(bolum, f"{on}_boylam", Decimal(str(round(konum.boylam, 6))))  # type: ignore[arg-type]
        setattr(bolum, f"{on}_dogruluk_m", round(dogruluk) if dogruluk is not None else None)
        setattr(bolum, f"{on}_konum_durumu", "ALINDI")
    else:
        setattr(bolum, f"{on}_enlem", None)
        setattr(bolum, f"{on}_boylam", None)
        setattr(bolum, f"{on}_dogruluk_m", None)
        setattr(bolum, f"{on}_konum_durumu", "ALINAMADI")


def konum_ozeti(bolum: ServiceTimeEntry, on: str, *, koordinat: bool) -> dict[str, Any] | None:
    """Ekran için konum: durum + metin; koordinat yalnız yetkili görene."""
    durum = getattr(bolum, f"{on}_konum_durumu")
    if durum is None:
        return None
    if durum != "ALINDI":
        return {"durum": durum, "metin": KONUM_ALINAMADI_METNI}
    sonuc: dict[str, Any] = {"durum": durum, "metin": "Konum alındı"}
    if koordinat:
        sonuc.update(
            {
                "enlem": float(getattr(bolum, f"{on}_enlem")),
                "boylam": float(getattr(bolum, f"{on}_boylam")),
                "dogruluk_m": getattr(bolum, f"{on}_dogruluk_m"),
            }
        )
    return sonuc


@dataclass(frozen=True)
class SureOzeti:
    """Tek kaynak süre özeti; kayıt yoksa `kisi_saat_dk=None` (0 DEĞİL).

    Ekran, liste, Excel, panel KPI'sı, bakım formu ve rapor bu nesneyi
    `sure_ozeti_toplu` üzerinden alır; ikinci bir hesap yazılmaz (E09-D02).
    """

    kisi_saat_dk: int | None
    sure_durumu: str  # TAM | KISMI | EKSIK | BEKLENMIYOR
    eksik_kisiler: tuple[str, ...] = ()
    mola_dk: int | None = None
    faaliyet_kirilimi: dict[str, int] = field(default_factory=dict)
    kisi_bazli: dict[int, int] = field(default_factory=dict)
    ilk_yol_at: datetime | None = None
    ilk_varis_at: datetime | None = None
    son_bitis_at: datetime | None = None
    sapma_dk: int | None = None
    acik_bolum_sayisi: int = 0

    @property
    def sure_eksik(self) -> bool:
        """`sure_eksik_ifadesi()` SQL tanımının Python karşılığı."""
        return self.sure_durumu in SURE_EKSIK_DURUMLARI


# --- Küçük yardımcılar --------------------------------------------------------------------


def _dk(sure: timedelta) -> int:
    """Süre → tam dakika (yuvarlanmış). Negatif süre üretilmez (CHECK)."""
    return round(sure.total_seconds() / 60)


def _saat(an: datetime | None) -> str:
    return yerel_zaman.yerel_an(an).strftime("%H:%M") if an is not None else "…"


def _aralik_metni(bolum: ServiceTimeEntry) -> str:
    gun = yerel_zaman.yerel_an(bolum.started_at).strftime("%d.%m.%Y")
    return f"{gun} {_saat(bolum.started_at)}-{_saat(bolum.ended_at)}"


async def _ayar(db: AsyncSession, anahtar: str) -> Any:
    return await ayarlar.get(db, anahtar)


def gecerli_bolum() -> ColumnElement[bool]:
    """İptal edilmemiş bölüm koşulu (iptal = yumuşak silme)."""
    return ServiceTimeEntry.is_deleted.is_(False)


async def _so_no(db: AsyncSession, so_id: int) -> str:
    return await db.scalar(select(ServiceOrder.so_no).where(ServiceOrder.id == so_id)) or "?"


async def _ad(db: AsyncSession, user_id: int | None) -> str:
    if user_id is None:
        return "?"
    return await db.scalar(select(User.full_name).where(User.id == user_id)) or "?"


def _sahibi_mi(bolum: ServiceTimeEntry, user: User) -> None:
    if bolum.user_id != user.id:
        raise ZamanYetkiHatasi("Yalnız kendi sayacınızı yönetebilirsiniz")


def _acik_mi(bolum: ServiceTimeEntry) -> None:
    if bolum.is_deleted or bolum.ended_at is not None:
        raise ZamanHatasi("Bu sayaç bölümü artık açık değil; ekranı yenileyin.")


async def _aktif_atamali_mi(db: AsyncSession, so_id: int, user_id: int) -> bool:
    return (
        await db.scalar(
            select(ServiceOrderAssignment.id).where(
                ServiceOrderAssignment.service_order_id == so_id,
                ServiceOrderAssignment.user_id == user_id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
        is not None
    )


async def _hic_atanmis_mi(db: AsyncSession, so_id: int, user_id: int) -> bool:
    return (
        await db.scalar(
            select(ServiceOrderAssignment.id)
            .where(
                ServiceOrderAssignment.service_order_id == so_id,
                ServiceOrderAssignment.user_id == user_id,
            )
            .limit(1)
        )
        is not None
    )


async def _bekleme_nedeni_dogrula(db: AsyncSession, faaliyet: str, neden: str | None) -> None:
    """BEKLEME faaliyetinde neden zorunlu ve iş bekleme kataloğundan (K24)."""
    if faaliyet != "BEKLEME":
        if neden is not None:
            raise ZamanGirdiHatasi("Bekleme nedeni yalnız BEKLEME faaliyetinde girilir")
        return
    if not neden:
        raise ZamanGirdiHatasi("Bekleme faaliyeti için neden seçin")
    kayit = await db.scalar(select(ServiceHoldReason).where(ServiceHoldReason.kod == neden))
    if kayit is None or not kayit.is_active or kayit.sadece_sistem:
        raise ZamanGirdiHatasi(f"Geçersiz bekleme nedeni: {neden}")


async def acik_bolum(
    db: AsyncSession, user_id: int, *, kilitle: bool = False
) -> ServiceTimeEntry | None:
    """Kişinin açık (canlı) bölümü; `kilitle` → `SELECT ... FOR UPDATE`."""
    stmt = select(ServiceTimeEntry).where(
        ServiceTimeEntry.user_id == user_id,
        ServiceTimeEntry.ended_at.is_(None),
        gecerli_bolum(),
    )
    if kilitle:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def _acik_bolum_yok(db: AsyncSession, user: User) -> None:
    """Tek aktif sayaç: açık bölüm varsa hangi işte olduğunu söyleyerek 409."""
    mevcut = await acik_bolum(db, user.id, kilitle=True)
    if mevcut is not None:
        raise ZamanHatasi(
            f"Önce açık sayacı bitirin: {await _so_no(db, mevcut.service_order_id)} "
            f"({FAALIYET_ADLARI.get(mevcut.faaliyet, mevcut.faaliyet)}, "
            f"{_saat(mevcut.started_at)}'dan beri)"
        )


async def cakisan_bolum(
    db: AsyncSession,
    user_id: int,
    bas: datetime,
    bit: datetime | None,
    *,
    haric_id: int | None = None,
) -> ServiceTimeEntry | None:
    """`[bas, bit)` ile çakışan geçerli bölüm (açık bölümün bitişi = sonsuz).

    EXCLUDE kısıtının (`tstzrange(started_at, ended_at, '[)') &&`) birebir
    karşılığıdır; ardışık bölümler (bitiş = başlangıç) çakışmaz.
    """
    kosullar = [
        ServiceTimeEntry.user_id == user_id,
        gecerli_bolum(),
        or_(ServiceTimeEntry.ended_at.is_(None), ServiceTimeEntry.ended_at > bas),
    ]
    if bit is not None:
        kosullar.append(ServiceTimeEntry.started_at < bit)
    if haric_id is not None:
        kosullar.append(ServiceTimeEntry.id != haric_id)
    return await db.scalar(
        select(ServiceTimeEntry).where(*kosullar).order_by(ServiceTimeEntry.started_at).limit(1)
    )


async def _cakisma_yok(
    db: AsyncSession, user_id: int, bas: datetime, bit: datetime | None, *, haric_id=None
) -> None:
    cakisan = await cakisan_bolum(db, user_id, bas, bit, haric_id=haric_id)
    if cakisan is not None:
        raise ZamanHatasi(
            f"{_aralik_metni(cakisan)} {cakisan.faaliyet} "
            f"({await _so_no(db, cakisan.service_order_id)}) ile çakışıyor"
        )


async def _sure_sinirlari(db: AsyncSession, bas: datetime, bit: datetime) -> None:
    """Asgari bölüm (ayar) ve azami 18 saat (kod sabiti)."""
    asgari = timedelta(minutes=int(await _ayar(db, "zaman_asgari_bolum_dk")))
    if bit - bas < asgari:
        raise ZamanGirdiHatasi(
            f"Bölüm en az {int(asgari.total_seconds() // 60)} dakika olmalı; yanlış "
            "başlattıysanız ilk dakikalarda 'Yanlış başlattım' ile geri alın."
        )
    if bit - bas > AZAMI_BOLUM:
        raise ZamanGirdiHatasi(
            "Bölüm 18 saati aşamaz. Sayacı unuttuysanız 'Unuttum' ile gerçek bitiş saatini girin."
        )


def _sayac_acilabilir(so: ServiceOrder) -> None:
    if so.status not in DURUM_GRUPLARI["SAYAC_ACILABILIR"]:
        raise ZamanHatasi(
            f"{so.so_no} {so.status} durumunda; bu işte sayaç başlatılamaz "
            "(kapalı ya da beklemedeki iş)."
        )


async def _durum_isle(
    db: AsyncSession, so: ServiceOrder, faaliyet: str, user: User, clock: Clock
) -> None:
    """K4: Yola Çıktım → YOLA_CIKILDI, Sahaya Vardım → SAHADA (tek kapıdan)."""
    kural = _OTOMATIK_DURUM.get(faaliyet)
    if kural is None or so.status not in kural[0]:
        return
    from app.services.teknik_servis import is_emirleri

    await is_emirleri.durum_degistir(db, so, kural[1], kaynak="sayac", user=user, clock=clock)


async def _yeni_bolum(
    db: AsyncSession,
    so: ServiceOrder,
    faaliyet: str,
    *,
    user: User,
    an: datetime,
    onceki: ServiceTimeEntry | None = None,
    bekleme_nedeni: str | None = None,
    konum_notu: str | None = None,
) -> ServiceTimeEntry:
    bolum = ServiceTimeEntry(
        service_order_id=so.id,
        user_id=user.id,
        faaliyet=faaliyet,
        bekleme_nedeni=bekleme_nedeni,
        started_at=an,
        ended_at=None,
        kaynak="CANLI",
        onceki_bolum_id=onceki.id if onceki is not None else None,
        girildi_at=an,
        konum_notu=konum_notu,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(bolum)
    await db.flush()
    return bolum


async def _olay(
    db: AsyncSession,
    so_id: int,
    olay_turu: str,
    ozet: str,
    *,
    user: User,
    clock: Clock,
    veri: dict[str, Any],
) -> None:
    """Zaman düzeltmeleri iş geçmişine `DUZELTME`/`NOT` ile yazılır (K10)."""
    from app.services.teknik_servis import gecmis

    so = await db.get(ServiceOrder, so_id)
    await gecmis.olay_yaz(db, so, olay_turu, ozet, user=user, clock=clock, veri=veri)


def _denetim_degeri(bolum: ServiceTimeEntry) -> dict[str, Any]:
    return {
        "service_order_id": bolum.service_order_id,
        "user_id": bolum.user_id,
        "faaliyet": bolum.faaliyet,
        "started_at": bolum.started_at.isoformat() if bolum.started_at else None,
        "ended_at": bolum.ended_at.isoformat() if bolum.ended_at else None,
        "kaynak": bolum.kaynak,
        "kapanis_turu": bolum.kapanis_turu,
        "iptal_turu": bolum.iptal_turu,
        "gerekce": bolum.gerekce or bolum.iptal_gerekcesi,
    }


async def _denetle(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    eylem: str,
    *,
    user: User,
    eski: dict[str, Any] | None = None,
) -> None:
    await audit.log(
        db,
        "service_time_entries",
        eylem,
        entity_id=bolum.id,
        old_value=eski,
        new_value=_denetim_degeri(bolum),
        user_id=user.id,
        # Konum notu ve başlat/bitir konumu kişinin nerede olduğunu söyler
        # (KVKK, E09 kontrol E09-01; G7.8).
        is_personal_data=bool(bolum.konum_notu)
        or "ALINDI" in (bolum.bas_konum_durumu, bolum.bit_konum_durumu),
    )


# --- Canlı sayaç (TS-071) -------------------------------------------------------------------


async def baslat(
    db: AsyncSession,
    so: ServiceOrder,
    faaliyet: str,
    *,
    user: User,
    clock: Clock,
    konum_notu: str | None = None,
    bekleme_nedeni: str | None = None,
    konum: KonumOkuma | None = None,
) -> ServiceTimeEntry:
    """Yeni canlı bölüm açar. İş erişimi (404) API'de çözülmüştür.

    Kurallar: iş `SAYAC_ACILABILIR` (409), kişi işte aktif atamalı (400), kişinin
    açık bölümü yok (409, hangi işte olduğu yazılır). Yola Çıktım/Sahaya Vardım
    işin durumunu `durum_degistir(kaynak='sayac')` ile ilerletir.
    """
    _sayac_acilabilir(so)
    if not await _aktif_atamali_mi(db, so.id, user.id):
        raise ZamanGirdiHatasi(f"{so.so_no} işine tayin edilmediğiniz için sayaç başlatamazsınız")
    await _bekleme_nedeni_dogrula(db, faaliyet, bekleme_nedeni)
    await _acik_bolum_yok(db, user)
    an = clock.now()
    # Açık bölüm yokken bile ileri tarihli manuel kayıt olamaz (bitiş ≤ şimdi),
    # ama geçmişte bitip şimdiye uzanan kayıt yoktur; yine de EXCLUDE'tan önce
    # okunur mesaj için sorgulanır.
    await _cakisma_yok(db, user.id, an, None)
    bolum = await _yeni_bolum(
        db,
        so,
        faaliyet,
        user=user,
        an=an,
        bekleme_nedeni=bekleme_nedeni,
        konum_notu=konum_notu,
    )
    _konum_yaz(bolum, "bas", konum)
    await db.flush()
    await _durum_isle(db, so, faaliyet, user, clock)
    await kancalar.zaman_bolumu_acildi(db, bolum)
    return bolum


async def bitir(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    *,
    user: User,
    clock: Clock,
    aciklama: str | None = None,
    konum: KonumOkuma | None = None,
) -> ServiceTimeEntry:
    """Sahibi açık bölümünü kapatır (atama/erişim aranmaz; iş IPTAL olsa bile)."""
    _sahibi_mi(bolum, user)
    _acik_mi(bolum)
    an = clock.now()
    await _sure_sinirlari(db, bolum.started_at, an)
    bolum.ended_at = an
    bolum.kapanis_turu = "BITIR"
    bolum.updated_by = user.id
    _konum_yaz(bolum, "bit", konum)
    if aciklama:
        bolum.aciklama = aciklama
    await db.flush()
    return bolum


async def gecis(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    yeni_faaliyet: str,
    *,
    user: User,
    clock: Clock,
    hedef_is: ServiceOrder | None = None,
    bekleme_nedeni: str | None = None,
    konum: KonumOkuma | None = None,
) -> ServiceTimeEntry:
    """Faaliyet değiştir / mola / devam / sonraki işe taşı (kapat → flush → ekle).

    Aynı konum okuması eski bölümün bitişine ve yeni bölümün başlangıcına
    yazılır (G7.8).

    `hedef_is` verilirse (TS-074) bölüm o işte aynı anda devam eder: hedef
    `SAYAC_ACILABILIR` ve kişiye aktif atanmış olmalı (değilse 409); hedef
    işin erişimi (404) API'de çözülür. Hedefte hata olursa kaynak bölüm açık
    kalır (aynı transaction geri alınır).
    """
    _sahibi_mi(bolum, user)
    _acik_mi(bolum)
    kaynak_so = await db.get(ServiceOrder, bolum.service_order_id)
    if hedef_is is not None:
        if hedef_is.id == bolum.service_order_id:
            raise ZamanGirdiHatasi("Sayaç zaten bu işte; başka bir iş seçin")
        hedef = hedef_is
        _sayac_acilabilir(hedef)
        if not await _aktif_atamali_mi(db, hedef.id, user.id):
            raise ZamanHatasi(f"{hedef.so_no} işine tayin edilmediğiniz için sayaç oraya taşınamaz")
    else:
        hedef = kaynak_so
        if yeni_faaliyet == bolum.faaliyet and bekleme_nedeni == bolum.bekleme_nedeni:
            raise ZamanGirdiHatasi("Sayaç zaten bu faaliyette")
        _sayac_acilabilir(hedef)
    await _bekleme_nedeni_dogrula(db, yeni_faaliyet, bekleme_nedeni)
    an = clock.now()
    await _sure_sinirlari(db, bolum.started_at, an)

    bolum.ended_at = an
    bolum.kapanis_turu = "GECIS"
    bolum.updated_by = user.id
    _konum_yaz(bolum, "bit", konum)
    await db.flush()  # kapat → flush → ekle (uq_ste_acik_kisi / EXCLUDE sırası)
    yeni = await _yeni_bolum(
        db,
        hedef,
        yeni_faaliyet,
        user=user,
        an=an,
        onceki=bolum,
        bekleme_nedeni=bekleme_nedeni,
        konum_notu=bolum.konum_notu if hedef_is is None else None,
    )
    _konum_yaz(yeni, "bas", konum)
    await db.flush()
    await _durum_isle(db, hedef, yeni_faaliyet, user, clock)
    await kancalar.zaman_bolumu_acildi(db, yeni)
    return yeni


async def mola(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    *,
    user: User,
    clock: Clock,
    konum: KonumOkuma | None = None,
) -> ServiceTimeEntry:
    if bolum.faaliyet == "MOLA":
        raise ZamanGirdiHatasi("Zaten moladasınız")
    return await gecis(db, bolum, "MOLA", user=user, clock=clock, konum=konum)


async def devam_faaliyeti(db: AsyncSession, bolum: ServiceTimeEntry) -> str:
    """Mola/bekleme öncesindeki son faaliyet (zincirde geriye yürür; yoksa SAHA)."""
    adim = bolum
    gorulen: set[int] = set()
    while adim.onceki_bolum_id is not None and adim.onceki_bolum_id not in gorulen:
        gorulen.add(adim.onceki_bolum_id)
        onceki = await db.get(ServiceTimeEntry, adim.onceki_bolum_id)
        if onceki is None:
            break
        if onceki.service_order_id != bolum.service_order_id:
            break  # taşınmış bölüm: önceki işin faaliyeti bu işe taşınmaz
        if onceki.faaliyet not in ("MOLA", "BEKLEME"):
            return onceki.faaliyet
        adim = onceki
    return "SAHA"


async def devam(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    *,
    user: User,
    clock: Clock,
    konum: KonumOkuma | None = None,
) -> ServiceTimeEntry:
    if bolum.faaliyet not in ("MOLA", "BEKLEME"):
        raise ZamanGirdiHatasi("Devam yalnız mola ya da bekleme sonrasında kullanılır")
    _sahibi_mi(bolum, user)
    faaliyet = await devam_faaliyeti(db, bolum)
    return await gecis(db, bolum, faaliyet, user=user, clock=clock, konum=konum)


# --- Düzeltmeler (TS-072) -------------------------------------------------------------------


async def geri_al(
    db: AsyncSession, bolum: ServiceTimeEntry, *, user: User, clock: Clock
) -> ServiceTimeEntry:
    """İlk `zaman_geri_alma_dk` dakikada yanlış başlatılan bölümü iptal eder.

    Satır silinmez (`GERI_ALINDI` iz bırakır), kişi-saate girmez. GECIS ile
    açılmışsa önceki bölüm YENİDEN AÇILMAZ (öngörülebilir; boşluk ≤ 5 dk).
    """
    _sahibi_mi(bolum, user)
    _acik_mi(bolum)
    an = clock.now()
    pencere = timedelta(minutes=int(await _ayar(db, "zaman_geri_alma_dk")))
    if an >= bolum.started_at + pencere:
        raise ZamanGirdiHatasi(
            f"Geri alma yalnız ilk {int(pencere.total_seconds() // 60)} dakikada yapılabilir; "
            "sayacı bitirin ya da 'Unuttum' ile düzeltin."
        )
    eski = _denetim_degeri(bolum)
    bolum.is_deleted = True
    bolum.deleted_at = an
    bolum.deleted_by = user.id
    bolum.iptal_turu = "GERI_ALINDI"
    bolum.updated_by = user.id
    await db.flush()
    await _denetle(db, bolum, "geri_al", user=user, eski=eski)
    await _sayac_durumunu_geri_al(db, bolum, user=user, clock=clock)
    return bolum


async def _sayac_durumunu_geri_al(
    db: AsyncSession, bolum: ServiceTimeEntry, *, user: User, clock: Clock
) -> None:
    """Rol testi tur 2 (5_teknisyen B1): "Yanlış başlattım" ile geri alınan YOL
    bölümü işi YOLA_CIKILDI'ya taşımışsa ve işte başka geçerli bölüm kalmadıysa
    iş PLANLANDI'ya döner (makinedeki "yanlış basış" kenarı, `kaynak='sayac'`).
    Başka biri yola çıkmış ya da kayıt girmişse durum korunur."""
    if bolum.faaliyet != "YOL":
        return
    so = await db.get(ServiceOrder, bolum.service_order_id)
    if so is None or so.status != "YOLA_CIKILDI":
        return
    kalan = await db.scalar(
        select(ServiceTimeEntry.id)
        .where(ServiceTimeEntry.service_order_id == so.id, gecerli_bolum())
        .limit(1)
    )
    if kalan is not None:
        return
    from app.services.teknik_servis import is_emirleri

    await is_emirleri.durum_degistir(db, so, "PLANLANDI", kaynak="sayac", user=user, clock=clock)


async def yola_cikisi_geri_al(
    db: AsyncSession, so: ServiceOrder, *, gerekce: str, user: User, clock: Clock
) -> list[int]:
    """Yönetici/şef yola çıkışı geri alır (rol testi tur 2 Y6): işin açık YOL
    sayaçları gerekçeyle iptal edilir (`yonetici_kapat`, kişi-saate girmez),
    iş YOLA_CIKILDI → PLANLANDI (`kaynak='yola_cikis_geri_al'`, gerekçe DURUM
    olayına yazılır). Açık SAHA/diğer sayaç varsa 409: o kişi sahadadır."""
    gerekce = (gerekce or "").strip()
    if len(gerekce) < 10:
        raise ZamanGirdiHatasi("Yola çıkışı geri almak için gerekçe yazın (en az 10 karakter)")
    acik = list(
        (
            await db.scalars(
                select(ServiceTimeEntry).where(
                    ServiceTimeEntry.service_order_id == so.id,
                    ServiceTimeEntry.ended_at.is_(None),
                    gecerli_bolum(),
                )
            )
        ).all()
    )
    diger = [b for b in acik if b.faaliyet != "YOL"]
    if diger:
        raise ZamanHatasi(
            "Bu işte yol dışında açık sayaç var; kişi sahada görünüyor. Önce o sayacı kapatın."
        )
    iptaller: list[int] = []
    for bolum in acik:
        await yonetici_kapat(
            db, bolum, None, f"Yola çıkış geri alındı: {gerekce}", user=user, clock=clock
        )
        iptaller.append(bolum.id)
    from app.services.teknik_servis import is_emirleri

    await is_emirleri.durum_degistir(
        db, so, "PLANLANDI", kaynak="yola_cikis_geri_al", user=user, clock=clock, gerekce=gerekce
    )
    return iptaller


async def unuttum(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    gercek_bitis: datetime,
    gerekce: str,
    *,
    user: User,
    clock: Clock,
) -> ServiceTimeEntry:
    """Sahibi açık sayacını gerçek bitişle kapatır (KULLANICI_DUZELTMESI).

    E09 kontrol B18: ön koşul (>10 sa / gün değişmiş) YOK — 15:00'te işi bırakıp
    19:00'da fark eden teknisyen 4 saatlik sahte süre yazmak zorunda kalmasın.
    Gerekçe zorunlu; kayıt disiplin sütununda "düzeltilmiş" sayılır.
    """
    _sahibi_mi(bolum, user)
    _acik_mi(bolum)
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise ZamanGirdiHatasi("Gerçek bitişle kapatmak için gerekçe yazın")
    _farkindalik(gercek_bitis)
    an = clock.now()
    if gercek_bitis <= bolum.started_at:
        raise ZamanGirdiHatasi("Gerçek bitiş, sayacın başlangıcından sonra olmalı")
    if gercek_bitis > an:
        raise ZamanGirdiHatasi("Gerçek bitiş ileri bir saat olamaz")
    await _sure_sinirlari(db, bolum.started_at, gercek_bitis)
    eski = _denetim_degeri(bolum)
    bolum.ended_at = gercek_bitis
    bolum.kaynak = "KULLANICI_DUZELTMESI"
    bolum.kapanis_turu = "UNUTULDU"
    bolum.gerekce = gerekce[:300]
    bolum.updated_by = user.id
    await db.flush()
    await _denetle(db, bolum, "kullanici_duzeltme", user=user, eski=eski)
    await _olay(
        db,
        bolum.service_order_id,
        "DUZELTME",
        f"Unutulan sayaç gerçek bitişle kapatıldı ({_aralik_metni(bolum)} {bolum.faaliyet})",
        user=user,
        clock=clock,
        veri={"alan": "zaman", "bolum_id": bolum.id, "tur": "UNUTULDU"},
    )
    return bolum


async def yonetici_kapat(
    db: AsyncSession,
    bolum: ServiceTimeEntry,
    gercek_bitis: datetime | None,
    gerekce: str,
    *,
    user: User,
    clock: Clock,
) -> ServiceTimeEntry:
    """Uzun/unutulmuş sayacı yönetici kapatır (`servis.planla` + iş erişimi API'de).

    Gerçek bitiş yoksa bölüm İPTAL edilir (kişi-saat oluşmaz); varsa
    `YONETICI_DUZELTMESI` ile kapanır. MOLA düzeltilse de MOLA kalır.
    """
    _acik_mi(bolum)
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise ZamanGirdiHatasi("Yönetici düzeltmesi için gerekçe zorunlu")
    an = clock.now()
    eski = _denetim_degeri(bolum)
    if gercek_bitis is None:
        bolum.is_deleted = True
        bolum.deleted_at = an
        bolum.deleted_by = user.id
        bolum.iptal_turu = "YONETICI_IPTAL"
        bolum.iptal_gerekcesi = gerekce[:300]
        eylem, ozet = "yonetici_iptal", "Açık sayaç yönetici tarafından iptal edildi"
    else:
        _farkindalik(gercek_bitis)
        if gercek_bitis <= bolum.started_at:
            raise ZamanGirdiHatasi("Gerçek bitiş, sayacın başlangıcından sonra olmalı")
        if gercek_bitis > an:
            raise ZamanGirdiHatasi("Gerçek bitiş ileri bir saat olamaz")
        if gercek_bitis - bolum.started_at > AZAMI_BOLUM:
            raise ZamanGirdiHatasi("Bölüm 18 saati aşamaz")
        bolum.ended_at = gercek_bitis
        bolum.kaynak = "YONETICI_DUZELTMESI"
        bolum.kapanis_turu = "YONETICI"
        bolum.gerekce = gerekce[:300]
        eylem, ozet = "yonetici_duzeltme", "Açık sayaç yönetici tarafından gerçek bitişle kapatıldı"
    bolum.updated_by = user.id
    await db.flush()
    await _denetle(db, bolum, eylem, user=user, eski=eski)
    await _olay(
        db,
        bolum.service_order_id,
        "DUZELTME",
        f"{ozet} ({await _ad(db, bolum.user_id)}, {bolum.faaliyet})",
        user=user,
        clock=clock,
        veri={"alan": "zaman", "bolum_id": bolum.id, "tur": eylem.upper()},
    )
    return bolum


def _farkindalik(an: datetime) -> None:
    if an.tzinfo is None or an.tzinfo.utcoffset(an) is None:
        raise ZamanGirdiHatasi("Saat dilimi bilgisi olmayan zaman kabul edilmez")


# --- Manuel kayıt ve kayıt iptali (TS-070) ------------------------------------------------------


async def manuel_kaydet(
    db: AsyncSession, so: ServiceOrder, girdi: ManuelKayitGirdisi, user: User, clock: Clock
) -> ServiceTimeEntry:
    """Elle süre kaydı (kaynak=MANUEL). İş erişimi (404) API'de çözülür.

    - başkası adına ya da `zaman_manuel_geri_gun`'den eski: `servis.planla` (403 / 400);
    - bitiş ileri olamaz, aralık ≤ 18 sa; bitişi eşikten eski kayıtta gerekçe (400);
    - kişi işte aktif atamalı (yönetici geçmiş atamalı kişi adına da girebilir) (400);
    - IPTAL işe kayıt 409; çakışma okunur mesajla 409 (EXCLUDE son savunma).
    """
    yonetici = user.has("servis.planla")
    kisi_id = girdi.user_id if girdi.user_id is not None else user.id
    if kisi_id != user.id and not yonetici:
        raise ZamanYetkiHatasi("Başkası adına süre kaydı için yetkiniz yok (servis.planla)")
    if so.status == "IPTAL":
        raise ZamanHatasi(f"{so.so_no} iptal edilmiş; bu işe süre kaydı girilemez")
    _farkindalik(girdi.started_at)
    _farkindalik(girdi.ended_at)
    an = clock.now()
    bas, bit = girdi.started_at, girdi.ended_at
    if bit > an:
        raise ZamanGirdiHatasi("Bitiş saati ileri bir zaman olamaz")
    if bit <= bas:
        raise ZamanGirdiHatasi("Bitiş, başlangıçtan sonra olmalı")
    if bit - bas > AZAMI_BOLUM:
        raise ZamanGirdiHatasi("Bir kayıt 18 saati aşamaz; birden fazla kayıt girin")
    esik = timedelta(minutes=int(await _ayar(db, "zaman_manuel_gerekce_esik_dk")))
    gerekce = (girdi.gerekce or "").strip() or None
    if an - bit > esik and gerekce is None:
        raise ZamanGirdiHatasi(
            f"Bitişi {int(esik.total_seconds() // 60)} dakikadan eski kayıt için gerekçe yazın"
        )
    if not yonetici:
        geri_gun = int(await _ayar(db, "zaman_manuel_geri_gun"))
        sinir = yerel_zaman.yerel_bugun(clock) - timedelta(days=geri_gun)
        if yerel_zaman.yerel_gun(bas) < sinir:
            raise ZamanGirdiHatasi(
                f"En çok {geri_gun} gün öncesine kayıt girebilirsiniz; daha eskisi için "
                "şefinize başvurun."
            )
    if yonetici and kisi_id != user.id:
        atamali = await _hic_atanmis_mi(db, so.id, kisi_id)
    else:
        atamali = await _aktif_atamali_mi(db, so.id, kisi_id)
    if not atamali:
        raise ZamanGirdiHatasi(f"Kişi {so.so_no} işine tayin edilmiş değil")
    await _bekleme_nedeni_dogrula(db, girdi.faaliyet, girdi.bekleme_nedeni)
    await _cakisma_yok(db, kisi_id, bas, bit)
    kayit = ServiceTimeEntry(
        service_order_id=so.id,
        user_id=kisi_id,
        faaliyet=girdi.faaliyet,
        bekleme_nedeni=girdi.bekleme_nedeni,
        started_at=bas,
        ended_at=bit,
        kaynak="MANUEL",
        gerekce=gerekce[:300] if gerekce else None,
        girildi_at=an,
        konum_notu=girdi.konum_notu,
        aciklama=girdi.aciklama,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(kayit)
    await db.flush()
    await _denetle(db, kayit, "olustur", user=user)
    return kayit


async def kaydi_iptal_et(
    db: AsyncSession, kayit: ServiceTimeEntry, gerekce: str | None, user: User, clock: Clock
) -> ServiceTimeEntry:
    """Kapalı kaydı yönetici iptal eder (`servis.planla` API'de); satır silinmez."""
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise ZamanGirdiHatasi("İptal gerekçesi zorunlu")
    if kayit.is_deleted:
        raise ZamanHatasi("Bu kayıt zaten iptal edilmiş")
    if kayit.ended_at is None:
        raise ZamanHatasi("Açık sayaç bu işlemle iptal edilemez; 'Kapat / Düzelt' kullanın")
    an = clock.now()
    eski = _denetim_degeri(kayit)
    kayit.is_deleted = True
    kayit.deleted_at = an
    kayit.deleted_by = user.id
    kayit.iptal_turu = "KAYIT_IPTAL"
    kayit.iptal_gerekcesi = gerekce[:300]
    kayit.updated_by = user.id
    await db.flush()
    await _denetle(db, kayit, "iptal", user=user, eski=eski)
    await _olay(
        db,
        kayit.service_order_id,
        "DUZELTME",
        f"Süre kaydı iptal edildi ({_aralik_metni(kayit)} {kayit.faaliyet}, "
        f"{await _ad(db, kayit.user_id)})",
        user=user,
        clock=clock,
        veri={"alan": "zaman", "bolum_id": kayit.id, "tur": "KAYIT_IPTAL"},
    )
    return kayit


# --- Kancalar (TS-073) ------------------------------------------------------------------------


async def acik_sayaclar(
    db: AsyncSession, is_idler: Iterable[int], user_idler: Iterable[int] | None = None
) -> list[tuple[str, int, str]]:
    """Açık sayaçlar: `(so_no, user_id, ad)` — tek sorgu."""
    is_idler = list(is_idler)
    if not is_idler:
        return []
    stmt = (
        select(ServiceOrder.so_no, ServiceTimeEntry.user_id, User.full_name)
        .join(ServiceOrder, ServiceOrder.id == ServiceTimeEntry.service_order_id)
        .join(User, User.id == ServiceTimeEntry.user_id)
        .where(
            ServiceTimeEntry.service_order_id.in_(is_idler),
            ServiceTimeEntry.ended_at.is_(None),
            gecerli_bolum(),
        )
        .order_by(ServiceOrder.so_no, User.full_name)
    )
    if user_idler is not None:
        user_idler = list(user_idler)
        if not user_idler:
            return []
        stmt = stmt.where(ServiceTimeEntry.user_id.in_(user_idler))
    return [(s, u, a) for s, u, a in (await db.execute(stmt)).all()]


async def acik_sayac_dogrula(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası: TAMAMLANDI/IPTAL'de açık sayaç → 409.

    Onayla geçilemez (TS-076 onayı yalnız eksik süreyi kabul eder).
    """
    if hedef not in ("TAMAMLANDI", "IPTAL"):
        return
    acik = await acik_sayaclar(db, [so.id])
    if acik:
        kisiler = ", ".join(a for _, _, a in acik)
        raise ZamanHatasi(f"Açık sayaç var: {kisiler} ({so.so_no}). Önce sayacı bitirin.")


async def acik_sayac_cikarma_dogrula(
    db: AsyncSession, so: ServiceOrder, cikan_user_ids: Sequence[int]
) -> None:
    """`ekip_degisiyor` kancası: açık sayaçlı kişiyi ekipten çıkarma → 409."""
    acik = await acik_sayaclar(db, [so.id], cikan_user_ids)
    if acik:
        parcalar = [f"{iyelik(ad)} {so_no}" for so_no, _, ad in acik]
        raise ZamanHatasi(f"Önce {', '.join(parcalar)} işindeki sayacını bitirin veya iptal edin.")


_UNLULER = "aeıioöuüAEIİOÖUÜ"


def iyelik(ad: str) -> str:
    """Türkçe tamlayan eki: "Ali Veli" → "Ali Veli'nin", "Ayşe Kaya" → "Ayşe Kaya'nın".

    Mesaj okunur olsun diye (kontrol B7); son ünlüye göre büyük ünlü uyumu.
    """
    son_unlu = next((h for h in reversed(ad) if h in _UNLULER), "e").lower()
    ek = {"a": "ın", "ı": "ın", "e": "in", "i": "in", "o": "un", "u": "un", "ö": "ün", "ü": "ün"}
    ek_ = ek.get(son_unlu, "in")
    return f"{ad}'{'n' if ad and ad[-1] in _UNLULER else ''}{ek_}"


# --- Süre özeti (TS-075) ------------------------------------------------------------------------


def _uzaktan_cozum_ifadesi() -> ColumnElement[bool]:
    return exists().where(
        ServiceResult.service_order_id == ServiceOrder.id,
        ServiceResult.gecersiz_at.is_(None),
        ServiceResult.cozum_kanali.in_(sorted(UZAKTAN_KANALLAR)),
    )


def _dahil_bolum_var(kisi_sutunu=None) -> ColumnElement[bool]:
    kosullar = [
        ServiceTimeEntry.service_order_id == ServiceOrder.id,
        gecerli_bolum(),
        ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
    ]
    if kisi_sutunu is not None:
        kosullar.append(ServiceTimeEntry.user_id == kisi_sutunu)
    return exists().where(*kosullar)


def _eksik_teknisyen_var() -> ColumnElement[bool]:
    return exists().where(
        ServiceOrderAssignment.service_order_id == ServiceOrder.id,
        ServiceOrderAssignment.removed_at.is_(None),
        ServiceOrderAssignment.rol == "TEKNISYEN",
        not_(_dahil_bolum_var(ServiceOrderAssignment.user_id)),
    )


def calisilmis_ifadesi() -> ColumnElement[bool]:
    """Süre BEKLENEN iş: çalışılmış durumda ve uzaktan/telefonla çözülmemiş."""
    return and_(
        ServiceOrder.status.not_in(sorted(BEKLENMIYOR_DURUMLAR)),
        not_(_uzaktan_cozum_ifadesi()),
    )


def sure_eksik_ifadesi() -> ColumnElement[bool]:
    """SQL tarafı "süre eksik" (= `sure_durumu ∈ {EKSIK, KISMI}`) — Python tanımıyla
    eşit (parametrik test `t/unit/test_zaman_hesap.py` + entegrasyon eşitlik testi).

    `service_orders` satırına uygulanır (panel KPI, liste süzgeci, rapor):
    - EKSIK: çalışılmış iş ve kişi-saate dahil geçerli bölüm yok;
    - KISMI: bölüm var ama aktif TEKNISYEN atamalarından birinin bölümü yok
      (iş IPTAL değil, uzaktan çözülmemiş).
    """
    var = _dahil_bolum_var()
    return or_(
        and_(calisilmis_ifadesi(), not_(var)),
        and_(
            var,
            ServiceOrder.status != "IPTAL",
            not_(_uzaktan_cozum_ifadesi()),
            _eksik_teknisyen_var(),
        ),
    )


def sure_durumu_hesapla(
    *,
    durum: str,
    uzaktan_cozum: bool,
    dahil_bolumu_olanlar: set[int],
    teknisyenler: dict[int, str],
) -> tuple[str, tuple[str, ...]]:
    """Saf kural (birim testli): `(sure_durumu, eksik_kisiler)`.

    `dahil_bolumu_olanlar`: kişi-saate dahil (MOLA dışı) geçerli bölümü olan
    kişiler (açık bölüm dahil). `teknisyenler`: aktif TEKNISYEN atamaları.
    """
    if not dahil_bolumu_olanlar:
        if durum in BEKLENMIYOR_DURUMLAR or uzaktan_cozum:
            return "BEKLENMIYOR", ()
        return "EKSIK", tuple(sorted(teknisyenler.values()))
    if durum == "IPTAL" or uzaktan_cozum:
        return ("BEKLENMIYOR" if durum == "IPTAL" else "TAM"), ()
    eksik = tuple(sorted(ad for uid, ad in teknisyenler.items() if uid not in dahil_bolumu_olanlar))
    return ("KISMI", eksik) if eksik else ("TAM", ())


async def sure_ozeti_toplu(db: AsyncSession, so_idler: Sequence[int]) -> dict[int, SureOzeti]:
    """İş başına süre özeti — ekran, liste, Excel, KPI ve uyarının TEK kaynağı.

    Toplama SQL'de yapılır (iş+kişi+faaliyet kırılımı tek sorgu); kişi-saat
    yalnız KAPALI, iptal edilmemiş, MOLA dışı bölümlerden. Kapalı bölüm yoksa
    `kisi_saat_dk=None` — 0 yazılmaz.
    """
    idler = sorted({int(i) for i in so_idler})
    if not idler:
        return {}
    saniye = func.extract("epoch", ServiceTimeEntry.ended_at - ServiceTimeEntry.started_at)
    satirlar = (
        await db.execute(
            select(
                ServiceTimeEntry.service_order_id,
                ServiceTimeEntry.user_id,
                ServiceTimeEntry.faaliyet,
                func.sum(saniye),
                func.count(ServiceTimeEntry.id),
                func.count(ServiceTimeEntry.ended_at),
                func.min(ServiceTimeEntry.started_at),
                func.max(ServiceTimeEntry.ended_at),
            )
            .where(ServiceTimeEntry.service_order_id.in_(idler), gecerli_bolum())
            .group_by(
                ServiceTimeEntry.service_order_id,
                ServiceTimeEntry.user_id,
                ServiceTimeEntry.faaliyet,
            )
        )
    ).all()
    isler = {
        i: (d, sure)
        for i, d, sure in (
            await db.execute(
                select(ServiceOrder.id, ServiceOrder.status, ServicePlan.duration_min)
                .outerjoin(
                    ServicePlan,
                    and_(
                        ServicePlan.service_order_id == ServiceOrder.id,
                        ServicePlan.is_active.is_(True),
                        ServicePlan.is_deleted.is_(False),
                    ),
                )
                .where(ServiceOrder.id.in_(idler))
            )
        ).all()
    }
    teknisyenler: dict[int, dict[int, str]] = defaultdict(dict)
    for so_id, uid, ad in (
        await db.execute(
            select(
                ServiceOrderAssignment.service_order_id,
                ServiceOrderAssignment.user_id,
                User.full_name,
            )
            .join(User, User.id == ServiceOrderAssignment.user_id)
            .where(
                ServiceOrderAssignment.service_order_id.in_(idler),
                ServiceOrderAssignment.removed_at.is_(None),
                ServiceOrderAssignment.rol == "TEKNISYEN",
            )
        )
    ).all():
        teknisyenler[so_id][uid] = ad
    uzaktan = set(
        (
            await db.scalars(
                select(ServiceResult.service_order_id).where(
                    ServiceResult.service_order_id.in_(idler),
                    ServiceResult.gecersiz_at.is_(None),
                    ServiceResult.cozum_kanali.in_(sorted(UZAKTAN_KANALLAR)),
                )
            )
        ).all()
    )

    toplam_sn: dict[int, float] = defaultdict(float)
    kapali_var: dict[int, bool] = defaultdict(bool)
    mola_sn: dict[int, float] = defaultdict(float)
    mola_var: dict[int, bool] = defaultdict(bool)
    kirilim: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    kisi: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    dahil_kisiler: dict[int, set[int]] = defaultdict(set)
    ilk_yol: dict[int, datetime] = {}
    ilk_varis: dict[int, datetime] = {}
    son_bitis: dict[int, datetime] = {}
    acik: dict[int, int] = defaultdict(int)
    for so_id, uid, faaliyet, sn, adet, kapali, ilk, son in satirlar:
        acik[so_id] += int(adet) - int(kapali)
        if son is not None and (so_id not in son_bitis or son > son_bitis[so_id]):
            son_bitis[so_id] = son
        if faaliyet == "YOL" and (so_id not in ilk_yol or ilk < ilk_yol[so_id]):
            ilk_yol[so_id] = ilk
        if faaliyet == "SAHA" and (so_id not in ilk_varis or ilk < ilk_varis[so_id]):
            ilk_varis[so_id] = ilk
        if faaliyet not in KISI_SAATE_DAHIL:
            if kapali:
                mola_var[so_id] = True
                mola_sn[so_id] += float(sn)
            continue
        if uid is not None:
            dahil_kisiler[so_id].add(uid)
        if kapali:
            kapali_var[so_id] = True
            toplam_sn[so_id] += float(sn)
            kirilim[so_id][faaliyet] += float(sn)
            if uid is not None:
                kisi[so_id][uid] += float(sn)

    sonuc: dict[int, SureOzeti] = {}
    for so_id in idler:
        if so_id not in isler:
            continue
        durum, tahmini = isler[so_id]
        sure_durumu, eksikler = sure_durumu_hesapla(
            durum=durum,
            uzaktan_cozum=so_id in uzaktan,
            dahil_bolumu_olanlar=dahil_kisiler[so_id],
            teknisyenler=teknisyenler[so_id],
        )
        kisi_saat = round(toplam_sn[so_id] / 60) if kapali_var[so_id] else None
        sonuc[so_id] = SureOzeti(
            kisi_saat_dk=kisi_saat,
            sure_durumu=sure_durumu,
            eksik_kisiler=eksikler,
            mola_dk=round(mola_sn[so_id] / 60) if mola_var[so_id] else None,
            faaliyet_kirilimi={f: round(s / 60) for f, s in kirilim[so_id].items()},
            kisi_bazli={u: round(s / 60) for u, s in kisi[so_id].items()},
            ilk_yol_at=ilk_yol.get(so_id),
            ilk_varis_at=ilk_varis.get(so_id),
            son_bitis_at=son_bitis.get(so_id),
            sapma_dk=(kisi_saat - tahmini) if kisi_saat is not None and tahmini else None,
            acik_bolum_sayisi=acik[so_id],
        )
    return sonuc


async def sure_ozeti(db: AsyncSession, so_id: int) -> SureOzeti:
    """Tek iş için `sure_ozeti_toplu` (ayrı hesap yok)."""
    return (await sure_ozeti_toplu(db, [so_id]))[so_id]


# --- Kapanışta "süre kaydı eksik" onayı (TS-076) ------------------------------------


async def sure_eksik_kapanis_dogrula(
    db: AsyncSession,
    so: ServiceOrder,
    *,
    onay: bool,
    user: User | None,
    clock: Clock,
) -> SureOzeti:
    """TAMAMLANDI'ya götüren uçlar (sonuç, bakım formu, atölye) çağırır.

    Süre EKSIK/KISMI ve `sure_eksik_onay` yoksa 409 — iş ENGELLENMEZ, istemci
    onay penceresi gösterip onayla yeniden gönderir (E09-12). Onaylı kapanışta
    geçmişe NOT yazılır. Açık sayaç kuralı (`acik_sayac_dogrula`) ayrıdır ve
    onayla geçilemez. BEKLENMIYOR (telefonla çözüm) sorulmaz.
    """
    ozet = await sure_ozeti(db, so.id)
    # M1.10/M9.4 (Faz A): iş sahaya hiç çıkmadan (MUSTERI_TALEBI/PLANLANDI ...)
    # sonuçlanırsa özet o an "beklenmiyor" der, ama TAMAMLANDI olunca rapor
    # onu "süre eksik" sayar. Kapanışta hedef duruma göre bakılır: hiç bölüm
    # yoksa ve çözüm uzaktan/telefonla değilse uyarı verilir (engel değil).
    sessiz_eksik = (
        ozet.sure_durumu == "BEKLENMIYOR"
        and ozet.kisi_saat_dk is None
        and so.status in BEKLENMIYOR_DURUMLAR
        and so.status != "IPTAL"
        and not await db.scalar(
            select(
                exists().where(
                    ServiceResult.service_order_id == so.id,
                    ServiceResult.gecersiz_at.is_(None),
                    ServiceResult.cozum_kanali.in_(sorted(UZAKTAN_KANALLAR)),
                )
            )
        )
    )
    if not ozet.sure_eksik and not sessiz_eksik:
        return ozet
    if ozet.eksik_kisiler:
        kimler = ", ".join(ozet.eksik_kisiler)
    else:
        kimler = "işte hiç süre kaydı yok"
    if not onay:
        raise ZamanHatasi(f"Süre kaydı eksik: {kimler}. Onaylayarak kapatın.")
    from app.services.teknik_servis import gecmis

    await gecmis.olay_yaz(
        db,
        so,
        "NOT",
        f"Süre kaydı eksik olarak kapatıldı: {kimler}",
        user=user,
        clock=clock,
        veri={"alan": "zaman", "sure_durumu": "EKSIK" if sessiz_eksik else ozet.sure_durumu},
    )
    return ozet


# --- Uyarılar (TS-072) ----------------------------------------------------------------


async def _uzun_sayac_kosulu(db: AsyncSession, clock: Clock) -> ColumnElement[bool]:
    """Açık bölüm `zaman_uzun_sayac_uyari_saat`'ten uzun ya da dünden kalmış."""
    saat = int(await _ayar(db, "zaman_uzun_sayac_uyari_saat"))
    an = clock.now()
    bugun_bas, _ = yerel_zaman.yerel_gun_araligi(yerel_zaman.yerel_bugun(clock))
    return and_(
        ServiceTimeEntry.ended_at.is_(None),
        gecerli_bolum(),
        or_(
            ServiceTimeEntry.started_at <= an - timedelta(hours=saat),
            ServiceTimeEntry.started_at < bugun_bas,
        ),
    )


async def uzun_sayac_sorgusu(db: AsyncSession, user: User, clock: Clock):
    """Kapsamlı uzun sayaç listesi (uyarı sayısı = bu listenin satır sayısı)."""
    stmt = select(ServiceTimeEntry).where(await _uzun_sayac_kosulu(db, clock))
    return kapsam.kapsam_isler(stmt, user, ServiceTimeEntry.service_order_id)


async def zaman_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Any]:
    """Uzun açık sayaç (yönetici: kapsamlı; herkes: kendi). Ack yok (K7):
    sayaç kapanınca uyarı kendiliğinden kaybolur. Worker kapatmaz (K16)."""
    sonuc: list[Uyari] = []
    if user.has("servis.planla"):
        stmt = await uzun_sayac_sorgusu(db, user, clock)
        # COUNT her zaman bir satır döner (NULL değil); süre değil, adet.
        adet = await db.scalar(select(func.count()).select_from(stmt.subquery()))
        sonuc.append(
            Uyari(
                kod="zaman.uzun_sayac",
                baslik="Uzun süredir açık sayaç",
                adet=int(adet),
                # Zaman Takibi ekranı açılabiliyorsa liste oradadır (TS-189);
                # açılamıyorsa ekip görünümü (sayı aynı sorgudan).
                yol=(
                    "/zaman-takibi?kpi=uzun_sayac"
                    if user.has("servis_rapor.gor")
                    else "/benim-islerim?gorunum=tumu"
                ),
                onem="kritik",
                aciklama="Gerçek bitişle düzeltin ya da iptal edin; sayaç kendiliğinden kapanmaz.",
            )
        )
    return sonuc


async def kendi_uzun_sayac_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Any]:
    kosul = await _uzun_sayac_kosulu(db, clock)
    adet = await db.scalar(
        select(func.count())
        .select_from(ServiceTimeEntry)
        .where(kosul, ServiceTimeEntry.user_id == user.id)
    )
    return [
        Uyari(
            kod="zaman.kendi_uzun_sayac",
            baslik="Sayacınız uzun süredir açık",
            adet=int(adet),
            yol="/benim-islerim",
            onem="uyari",
            aciklama="Unuttuysanız gerçek bitiş saatini girin.",
        )
    ]


def uzun_sayac_mi(bolum: ServiceTimeEntry, an: datetime, esik_saat: int) -> bool:
    """Tek bölüm için uyarı koşulu (bant ve kart bunu gösterir)."""
    if bolum.ended_at is not None or bolum.is_deleted:
        return False
    return an - bolum.started_at >= timedelta(hours=esik_saat) or (
        yerel_zaman.yerel_gun(bolum.started_at) < yerel_zaman.yerel_gun(an)
    )


# --- Zaman Takibi yönetim ekranı (TS-189, E09-14/15) --------------------------------
#
# **Sayı = liste:** her KPI tek bir sorgu üreticisinden gelir (`kpi_sorgusu`);
# kutudaki adet `GET /zaman/kayitlar?kpi=` (ya da iş KPI'larında
# `GET /zaman/isler?kpi=`) `X-Toplam-Kayit` başlığıyla, dakika toplamı
# `X-Toplam-Dakika` başlığıyla AYNI sorgunun toplamıdır. Excel de aynı sorguyu
# kullanır (ekran ≠ Excel olamaz).
#
# **Kişi-saat ortak fonksiyonu:** `personel_dagilimi` kişi bazlı kişi-saati ve
# veri disiplini sütunlarını TEK sorguda üretir; rapor motorunun
# `/kisi-saat` kırılımı (E12) ikinci bir sorgu yazmaz, bunu çağırır.
#
# **Eksik ≠ 0:** kayıt yoksa dakika toplamı `None` döner; oran paydası 0 ise
# oran `None` ("%0" değil, E09-15 kabul 4). Tahmini (plan) süre burada HİÇ
# kullanılmaz.
#
# **Kişi sütunları** (`user_id`, kişi adı, konum notu, gerekçe, personel
# dağılımı) yalnız `servis_rapor.personel` ile; bu modül veriyi üretir, anahtarı
# yanıttan çıkarmak API'nin işidir (`kisi_alanlari`).

ZAMAN_RAPOR_AZAMI_GUN = 366
ZAMAN_EXCEL_UST_SINIR = 20_000
DAKIKA_BASLIGI = "X-Toplam-Dakika"
# Kayıt (bölüm) listesi açan KPI'lar ve iş listesi açan KPI'lar ayrıdır; oran
# KPI'sı liste açmaz (oranın "listesi" yoktur).
KAYIT_KPI_KODLARI = ("kisi_saat", "yol", "saha", "bekleme", "mola", "aktif_sayac", "uzun_sayac")
IS_KPI_KODLARI = ("farkli_is", "sure_eksik")
# kod → (başlık, tanım, birim: "dk" | "adet" | "oran")
ZAMAN_KPI_TANIMLARI: dict[str, tuple[str, str, str]] = {
    "kisi_saat": (
        "Kişi-saat (dk)",
        "Aralıkta başlayan, kapanmış, iptal edilmemiş bölümler; MOLA hariç. Kayıt yoksa boş.",
        "dk",
    ),
    "yol": ("Yol (dk)", "Kapanmış YOL bölümlerinin toplamı", "dk"),
    "saha": ("Saha (dk)", "Kapanmış SAHA bölümlerinin toplamı", "dk"),
    "bekleme": ("Bekleme (dk)", "Kapanmış BEKLEME bölümlerinin toplamı", "dk"),
    "mola": ("Mola (dk, hariç)", "Bilgi amaçlı; kişi-saate EKLENMEZ", "dk"),
    "farkli_is": ("Farklı iş", "Aralıkta süre kaydı olan farklı servis işi sayısı", "adet"),
    "aktif_sayac": ("Aktif sayaç", "Şu an açık olan sayaçlar (tarih süzgecinden bağımsız)", "adet"),
    "uzun_sayac": (
        "Uzun sayaç",
        "Uyarı eşiğinden uzun ya da dünden kalan açık sayaçlar",
        "adet",
    ),
    "sure_eksik": (
        "Süre kaydı eksik iş",
        "Aralıkta tamamlanan ve süre kaydı eksik/kısmi olan işler (telefonla çözüm hariç)",
        "adet",
    ),
    "canli_orani": (
        "Canlı oranı (%)",
        "CANLI sayaç dakikası ÷ toplam kişi-saat; kayıt yoksa boş",
        "oran",
    ),
}
_FAALIYET_KPI = {"yol": "YOL", "saha": "SAHA", "bekleme": "BEKLEME", "mola": "MOLA"}
DUZELTME_KAYNAKLARI = ("KULLANICI_DUZELTMESI", "YONETICI_DUZELTMESI")
IPTAL_TURLERI_DISIPLIN = ("YONETICI_IPTAL", "KAYIT_IPTAL")


@dataclass(frozen=True)
class ZamanSuzgeci:
    """Yönetim ekranı süzgeci; tarih aralığı Türkiye günü, `started_at`'e göre."""

    bas: date
    bit: date
    birim: str | None = None
    kullanici_id: int | None = None
    faaliyet: str | None = None

    def iso(self) -> dict[str, Any]:
        """Denetim kaydı için ISO biçimli süzgeç (TS-182)."""
        return {
            "bas": self.bas.isoformat(),
            "bit": self.bit.isoformat(),
            "birim": self.birim,
            "kullanici_id": self.kullanici_id,
            "faaliyet": self.faaliyet,
        }


async def zaman_suzgeci(
    db: AsyncSession,
    clock: Clock,
    *,
    bas: date | None = None,
    bit: date | None = None,
    birim: str | None = None,
    kullanici_id: int | None = None,
    faaliyet: str | None = None,
) -> ZamanSuzgeci:
    """Varsayılan aralık son `zaman_rapor_varsayilan_gun` gün (bugün dahil).

    Bitiş başlangıçtan önce ya da aralık 366 günden uzunsa 400.
    """
    bugun = yerel_zaman.yerel_bugun(clock)
    if bit is None:
        bit = bugun
    if bas is None:
        gun = int(await _ayar(db, "zaman_rapor_varsayilan_gun"))
        bas = bit - timedelta(days=max(gun, 1) - 1)
    if bit < bas:
        raise ZamanGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if (bit - bas).days + 1 > ZAMAN_RAPOR_AZAMI_GUN:
        raise ZamanGirdiHatasi(f"Tarih aralığı en çok {ZAMAN_RAPOR_AZAMI_GUN} gün olabilir")
    if faaliyet is not None and faaliyet not in FAALIYET_ADLARI:
        raise ZamanGirdiHatasi(f"Bilinmeyen faaliyet: {faaliyet}")
    return ZamanSuzgeci(bas=bas, bit=bit, birim=birim, kullanici_id=kullanici_id, faaliyet=faaliyet)


def _aralik_kosulu(f: ZamanSuzgeci) -> ColumnElement[bool]:
    alt, _ = yerel_zaman.yerel_gun_araligi(f.bas)
    _, ust = yerel_zaman.yerel_gun_araligi(f.bit)
    return and_(ServiceTimeEntry.started_at >= alt, ServiceTimeEntry.started_at < ust)


def _ortak_suzgec(stmt: Select, user: User, f: ZamanSuzgeci, *, faaliyet: bool = True) -> Select:
    """İş kapsamı (birim / kendi işleri / müşteri) + birim + kişi + faaliyet."""
    stmt = kapsam.kapsam_isler(stmt, user, ServiceTimeEntry.service_order_id)
    if f.birim:
        stmt = stmt.where(
            ServiceTimeEntry.service_order_id.in_(
                select(ServiceOrder.id).where(ServiceOrder.birim == f.birim)
            )
        )
    if f.kullanici_id is not None:
        stmt = stmt.where(ServiceTimeEntry.user_id == f.kullanici_id)
    if faaliyet and f.faaliyet:
        stmt = stmt.where(ServiceTimeEntry.faaliyet == f.faaliyet)
    return stmt


def kayit_sorgusu(user: User, f: ZamanSuzgeci, *, iptaller: bool = False) -> Select:
    """Aralıkta BAŞLAYAN bölümler (kapsamlı). `iptaller` → iptal/geri alınanlar da."""
    stmt = select(ServiceTimeEntry).where(_aralik_kosulu(f))
    if not iptaller:
        stmt = stmt.where(gecerli_bolum())
    return _ortak_suzgec(stmt, user, f)


def _kapali_dahil() -> ColumnElement[bool]:
    return and_(
        ServiceTimeEntry.ended_at.is_not(None),
        ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
    )


async def kpi_kayit_sorgusu(db: AsyncSession, user: User, f: ZamanSuzgeci, kod: str, clock: Clock):
    """Bölüm listesi açan KPI'ın TEK sorgusu (sayı, liste, Excel buradan)."""
    if kod not in KAYIT_KPI_KODLARI:
        raise ZamanGirdiHatasi(f"Bilinmeyen KPI: {kod}")
    if kod == "aktif_sayac":
        stmt = select(ServiceTimeEntry).where(ServiceTimeEntry.ended_at.is_(None), gecerli_bolum())
        return _ortak_suzgec(stmt, user, f)
    if kod == "uzun_sayac":
        stmt = select(ServiceTimeEntry).where(await _uzun_sayac_kosulu(db, clock))
        return _ortak_suzgec(stmt, user, f)
    stmt = kayit_sorgusu(user, f)
    if kod == "kisi_saat":
        return stmt.where(_kapali_dahil())
    return stmt.where(
        ServiceTimeEntry.ended_at.is_not(None),
        ServiceTimeEntry.faaliyet == _FAALIYET_KPI[kod],
    )


def _bitmis_tarih_kosulu(f: ZamanSuzgeci) -> ColumnElement[bool]:
    alt, _ = yerel_zaman.yerel_gun_araligi(f.bas)
    _, ust = yerel_zaman.yerel_gun_araligi(f.bit)
    return and_(ServiceOrder.completed_at >= alt, ServiceOrder.completed_at < ust)


def kpi_is_sorgusu(user: User, f: ZamanSuzgeci, kod: str) -> Select:
    """İş listesi açan KPI'ın TEK sorgusu (`service_orders` satırları)."""
    if kod not in IS_KPI_KODLARI:
        raise ZamanGirdiHatasi(f"Bilinmeyen KPI: {kod}")
    if kod == "farkli_is":
        bolumlu = select(ServiceTimeEntry.service_order_id).where(
            _aralik_kosulu(f), gecerli_bolum()
        )
        bolumlu = _ortak_suzgec(bolumlu, user, f)
        stmt = select(ServiceOrder).where(ServiceOrder.id.in_(bolumlu))
    else:
        stmt = select(ServiceOrder).where(
            ServiceOrder.is_deleted.is_(False),
            _bitmis_tarih_kosulu(f),
            sure_eksik_ifadesi(),
        )
        stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
        if f.birim:
            stmt = stmt.where(ServiceOrder.birim == f.birim)
        if f.kullanici_id is not None:
            stmt = stmt.where(
                ServiceOrder.id.in_(
                    select(ServiceOrderAssignment.service_order_id).where(
                        ServiceOrderAssignment.user_id == f.kullanici_id,
                        ServiceOrderAssignment.removed_at.is_(None),
                    )
                )
            )
    return stmt.order_by(ServiceOrder.id)


async def adet_ve_dakika(db: AsyncSession, stmt: Select) -> tuple[int, int | None]:
    """Bölüm sorgusunun (adet, kapalı bölüm dakika toplamı). Kayıt yoksa dakika None.

    Liste başlığı ve KPI kutusu bu fonksiyonla sayılır (aynı yuvarlama).
    """
    alt = stmt.order_by(None).subquery()
    satir = (
        await db.execute(
            select(
                func.count(),
                func.sum(func.extract("epoch", alt.c.ended_at - alt.c.started_at)),
            ).select_from(alt)
        )
    ).one()
    # COUNT hiçbir zaman NULL dönmez; dakika toplamı ise kayıt yoksa NULL kalır.
    adet, sn = int(satir[0]), satir[1]
    return adet, (round(float(sn) / 60) if sn is not None else None)


async def _adet(db: AsyncSession, stmt: Select) -> int:
    return int(await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())))


async def zaman_ozeti(
    db: AsyncSession, user: User, f: ZamanSuzgeci, clock: Clock
) -> list[dict[str, Any]]:
    """KPI kutuları: `{kod, baslik, tanim, birim, deger, adet, liste}`.

    `adet` = açılan listenin `X-Toplam-Kayit`; dakika KPI'larında `deger` =
    listenin `X-Toplam-Dakika` (kayıt yoksa None).
    """
    sonuc: list[dict[str, Any]] = []
    for kod, (baslik, tanim, birim) in ZAMAN_KPI_TANIMLARI.items():
        deger: float | int | None
        adet: int | None = None
        liste: str | None = None
        if kod in KAYIT_KPI_KODLARI:
            adet, dakika = await adet_ve_dakika(
                db, await kpi_kayit_sorgusu(db, user, f, kod, clock)
            )
            deger = dakika if birim == "dk" else adet
            liste = "kayitlar"
        elif kod in IS_KPI_KODLARI:
            adet = await _adet(db, kpi_is_sorgusu(user, f, kod))
            deger = adet
            liste = "isler"
        else:  # canli_orani
            deger = await _canli_orani(db, user, f)
        sonuc.append(
            {
                "kod": kod,
                "baslik": baslik,
                "tanim": tanim,
                "birim": birim,
                "deger": deger,
                "adet": adet,
                "liste": liste,
            }
        )
    return sonuc


def canli_orani_hesapla(canli_sn: float | None, toplam_sn: float | None) -> float | None:
    """CANLI ÷ toplam (yüzde, 1 ondalık). Payda 0/yok → None ("%0" değil)."""
    if not toplam_sn:
        return None
    canli = float(canli_sn) if canli_sn is not None else 0.0  # payda var, CANLI yok
    return round(100 * canli / float(toplam_sn), 1)


async def _canli_orani(db: AsyncSession, user: User, f: ZamanSuzgeci) -> float | None:
    alt = kayit_sorgusu(user, f).where(_kapali_dahil()).order_by(None).subquery()
    sure = func.extract("epoch", alt.c.ended_at - alt.c.started_at)
    toplam, canli = (
        await db.execute(
            select(
                func.sum(sure),
                func.sum(sure).filter(alt.c.kaynak == "CANLI"),
            ).select_from(alt)
        )
    ).one()
    return canli_orani_hesapla(canli, toplam)


async def personel_dagilimi(db: AsyncSession, user: User, f: ZamanSuzgeci) -> list[dict[str, Any]]:
    """Kişi bazlı kişi-saat + veri disiplini sütunları (E09-15) — TEK sorgu.

    Kişi-saat ortak fonksiyonudur (rapor motorunun kişi-saat kırılımı bunu
    çağırır). İptal/geri alınan bölümler yalnız disiplin sayılarına girer;
    süre sütunları iptal edilmemiş, kapanmış bölümlerdendir. Gecikmeli manuel:
    `girildi_at - ended_at > zaman_gecikmeli_manuel_saat`.
    """
    esik = timedelta(hours=int(await _ayar(db, "zaman_gecikmeli_manuel_saat")))
    alt = kayit_sorgusu(user, f, iptaller=True).order_by(None).subquery()
    c = alt.c
    gecerli = c.is_deleted.is_(False)
    kapali = and_(gecerli, c.ended_at.is_not(None))
    dahil = and_(kapali, c.faaliyet.in_(sorted(KISI_SAATE_DAHIL)))
    sure = func.extract("epoch", c.ended_at - c.started_at)

    def faaliyet_sn(kod: str):
        return func.sum(sure).filter(kapali, c.faaliyet == kod)

    stmt = (
        select(
            c.user_id,
            func.max(c.kaynak_personel_adi),
            func.sum(sure).filter(dahil),
            func.sum(sure).filter(dahil, c.kaynak == "CANLI"),
            faaliyet_sn("YOL"),
            faaliyet_sn("SAHA"),
            faaliyet_sn("BEKLEME"),
            faaliyet_sn("MOLA"),
            func.count(func.distinct(c.service_order_id)).filter(gecerli),
            func.count().filter(gecerli, c.kaynak == "MANUEL"),
            func.count().filter(
                gecerli,
                c.kaynak == "MANUEL",
                c.ended_at.is_not(None),
                c.girildi_at - c.ended_at > esik,
            ),
            func.count().filter(gecerli, c.kaynak.in_(DUZELTME_KAYNAKLARI)),
            func.count().filter(c.iptal_turu.in_(IPTAL_TURLERI_DISIPLIN)),
            func.count().filter(c.iptal_turu == "GERI_ALINDI"),
        )
        .select_from(alt)
        .group_by(c.user_id)
    )
    satirlar = (await db.execute(stmt)).all()
    adlar = dict(
        (
            await db.execute(
                select(User.id, User.full_name).where(
                    User.id.in_({s[0] for s in satirlar if s[0] is not None} or {0})
                )
            )
        ).all()
    )

    def dk_(sn) -> int | None:
        return round(float(sn) / 60) if sn is not None else None

    sonuc = []
    for (
        uid,
        kaynak_ad,
        dahil_sn,
        canli_sn,
        yol_sn,
        saha_sn,
        bekleme_sn,
        mola_sn,
        is_sayisi,
        manuel,
        gecikmeli,
        duzeltilen,
        iptal,
        geri_alinan,
    ) in satirlar:
        sonuc.append(
            {
                "user_id": uid,
                "ad": adlar.get(uid) if uid is not None else (kaynak_ad or "Eşleşmemiş (göç)"),
                "kisi_saat_dk": dk_(dahil_sn),
                "yol_dk": dk_(yol_sn),
                "saha_dk": dk_(saha_sn),
                "bekleme_dk": dk_(bekleme_sn),
                "mola_dk": dk_(mola_sn),
                "is_sayisi": int(is_sayisi),
                "canli_orani": canli_orani_hesapla(canli_sn, dahil_sn),
                "manuel_sayisi": int(manuel),
                "gecikmeli_manuel_sayisi": int(gecikmeli),
                "duzeltilen_sayisi": int(duzeltilen),
                "iptal_sayisi": int(iptal),
                "geri_alinan_sayisi": int(geri_alinan),
            }
        )
    # Kişi-saati olmayan (eksik) en sona; 0 varsayılmaz.
    sonuc.sort(
        key=lambda s: (
            s["kisi_saat_dk"] is None,
            -s["kisi_saat_dk"] if s["kisi_saat_dk"] is not None else 0,
            s["ad"] or "",
        )
    )
    return sonuc


async def kayit_satirlari(
    db: AsyncSession, bolumler: Sequence[ServiceTimeEntry], clock: Clock
) -> list[dict[str, Any]]:
    """Bölüm satırları (kişi alanları DAHİL; izinsizde API çıkarır)."""
    if not bolumler:
        return []
    so_idler = {b.service_order_id for b in bolumler}
    isler = {
        i: (no, birim)
        for i, no, birim in (
            await db.execute(
                select(ServiceOrder.id, ServiceOrder.so_no, ServiceOrder.birim).where(
                    ServiceOrder.id.in_(so_idler)
                )
            )
        ).all()
    }
    adlar = dict(
        (
            await db.execute(
                select(User.id, User.full_name).where(
                    User.id.in_({b.user_id for b in bolumler if b.user_id} or {0})
                )
            )
        ).all()
    )
    esik_saat = int(await _ayar(db, "zaman_uzun_sayac_uyari_saat"))
    gecikme = timedelta(hours=int(await _ayar(db, "zaman_gecikmeli_manuel_saat")))
    an = clock.now()
    sonuc = []
    for b in bolumler:
        no, birim = isler.get(b.service_order_id, ("?", None))
        sure = _dk(b.ended_at - b.started_at) if b.ended_at is not None else None
        sonuc.append(
            {
                "id": b.id,
                "version": b.version,
                "service_order_id": b.service_order_id,
                "so_no": no,
                "birim": birim,
                "faaliyet": b.faaliyet,
                "bekleme_nedeni": b.bekleme_nedeni,
                "started_at": b.started_at,
                "ended_at": b.ended_at,
                "sure_dk": sure,
                "gecen_dk": _dk(an - b.started_at) if b.ended_at is None else None,
                "uzun": uzun_sayac_mi(b, an, esik_saat),
                "kaynak": b.kaynak,
                "kapanis_turu": b.kapanis_turu,
                "girildi_at": b.girildi_at,
                "gecikmeli": (
                    b.kaynak == "MANUEL"
                    and b.ended_at is not None
                    and b.girildi_at - b.ended_at > gecikme
                ),
                "iptal_turu": b.iptal_turu,
                # --- kişi alanları (servis_rapor.personel) ---
                "user_id": b.user_id,
                "kisi_adi": adlar.get(b.user_id) if b.user_id else b.kaynak_personel_adi,
                "konum_notu": b.konum_notu,
                "gerekce": b.gerekce or b.iptal_gerekcesi,
                "aciklama": b.aciklama,
            }
        )
    return sonuc


KISI_ALANLARI = ("user_id", "kisi_adi", "konum_notu", "gerekce", "aciklama")


def kisi_alanlari_cikar(satirlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`servis_rapor.personel` yoksa kişi alanları ANAHTAR olarak yok (TS-182)."""
    return [{k: v for k, v in s.items() if k not in KISI_ALANLARI} for s in satirlar]


async def is_satirlari(db: AsyncSession, isler: Sequence[ServiceOrder]) -> list[dict[str, Any]]:
    """İş KPI listesi satırları; süre `sure_ozeti_toplu`'dan (tek kaynak)."""
    ozetler = await sure_ozeti_toplu(db, [s.id for s in isler])
    sonuc = []
    for s in isler:
        o = ozetler.get(s.id)
        sonuc.append(
            {
                "id": s.id,
                "so_no": s.so_no,
                "birim": s.birim,
                "tur": s.tur,
                "durum": s.status,
                "konu": s.konu,
                "completed_at": s.completed_at,
                "kisi_saat_dk": o.kisi_saat_dk if o else None,
                "sure_durumu": o.sure_durumu if o else None,
            }
        )
    return sonuc


# --- Kanca ve uyarı kayıtları (dosyanın EN ALTINDA, plan §1.8) ----------------------

kancalar.kaydet("durum_dogrula", acik_sayac_dogrula)
kancalar.kaydet("ekip_degisiyor", acik_sayac_cikarma_dogrula)


def _uyari_kaydi() -> None:
    from app.services.teknik_servis import uyarilar as ts_uyarilar

    ts_uyarilar.kaydet("zaman", "servis.planla", zaman_uyarilari)
    ts_uyarilar.kaydet("zaman", "zaman.yaz", kendi_uzun_sayac_uyarisi)


_uyari_kaydi()
