"""Plan yazımı: tekli/toplu plan, geri alma, yeniden plan, saha önerisi (E02, TS-040…048).

**Plan satırı silinmez, yenisiyle değişir** (E02 K-09). Erteleme, ekip
değişimi ve yeniden planlama yeni bir `service_plans` satırı açar; eskisi
`is_active=false` + `cancelled_at` alır. Geri alma yeni satır açmaz; kapanan
satır `cancel_reason/cancel_note` taşır. Tek aktif plan şemada zorlanır
(`uq_svcplan_aktif`).

**Durum geri çekilmez (E02-02, KRİTİK):** MUSTERI_TALEBI/PLANLAMADA/
TEKRAR_ACILDI → PLANLANDI (`kaynak='planla'`); saha, atölye ya da bekleme
durumundaki işte yalnız plan güncellenir, durum korunur; kapalı işte 409 ve
hiçbir satır yazılmaz. Geri almada yalnız PLANLANDI → PLANLAMADA olur; diğer
açık durumlar DEĞİŞMEZ (sahadaki işi geri almak onu talebe düşürmemeli).
Durum geçişi yalnız `is_emirleri.durum_degistir` ile.

**Kilit sırası:** (1) iş satırları id sıralı `FOR UPDATE` (aynı işe iki plan
isteği sıraya girer; ikincisi `beklenen_aktif_plan_id` uyuşmazlığıyla 409
alır), (2) etkilenen İstanbul günleri için advisory lock (çakışma kontrolü
ile yazım arasında başka planlama araya giremez), (3) çakışma kontrolü,
(4) yazım. Servis yalnız `flush` eder; commit uçtadır (tek transaction —
hata olursa ne plan ne ekip değişir).

**Ekip tek kaynak (E02-D01):** ekip ataması `atama.ata` ile yazılır; plan
üyeleri atamaların kopyasıdır. Planlama dışından (iş ekranı, toplu atama)
ekip değişince `ekip_degisti` kancası aktif planda EKIP_DEGISIMI satırı
açar.

**Adres/irtibat plana kopyalanmaz** (E02 kontrol 2.1): işin kendi
`address_id/contact_id` alanları tek kaynaktır; plana yalnız ziyarete özgü
`site_area/site_note` yazılır.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select, update

from app.models import (
    Address,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServicePlanMember,
    ServiceUnavailability,
    ServiceVehicle,
    ServiceVisit,
)
from app.models.servis_planlama import PLAN_NEDENLERI, PLAN_SURE_ALT_DK, PLAN_SURE_UST_DK
from app.models.teknik_servis import DURUM_GRUPLARI
from app.services import audit, kvkk
from app.services import settings as ayar_svc
from app.services.teknik_servis import (
    ana_veri,
    atama,
    cakisma,
    gecmis,
    is_emirleri,
    kancalar,
    kapsam,
    numara,
)
from app.services.teknik_servis.atama import AtamaSatiri
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import YEREL

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

KAPALI = DURUM_GRUPLARI["KAPALI"]
# Planlama bu durumlarda işi PLANLANDI'ya taşır; diğer açık durumlarda durum korunur.
PLANLANDIYA_GECER = frozenset({"MUSTERI_TALEBI", "PLANLAMADA", "TEKRAR_ACILDI"})
TOPLU_UST_SINIR_ANAHTARI = "servis_toplu_atama_ust_sinir"
TOPLU_VARSAYILAN_UST_SINIR = 150

# Planlama kendi ekip yazımını yaparken `ekip_degisti` kancası ikinci bir
# EKIP_DEGISIMI satırı açmasın.
_PLAN_YAZILIYOR: ContextVar[bool] = ContextVar("servis_plan_yaziliyor", default=False)


class PlanlamaHatasi(ServisHatasi):
    """Planlama kural ihlali → 409. `is_nolari` toplu işlemde sorunlu işler."""

    def __init__(self, mesaj: str, is_nolari: Sequence[str] = ()) -> None:
        super().__init__(mesaj)
        self.is_nolari = list(is_nolari)


class PlanlamaGirdiHatasi(ServisGirdiHatasi):
    """Girdi hatası (katalog dışı neden, atanamaz kişi, geçersiz süre) → 400."""


class PlanlamaBulunamadi(LookupError):
    """Kayıt yok ya da kapsam dışı → 404 (varlığı sızdırılmaz)."""


@dataclass
class PlanGirdisi:
    """Plan yazım girdisi (API şeması `PlanIn` bunu üretir).

    `ekip=None`: mevcut ekip korunur (iş atamaları plana kopyalanır).
    `sahaya_giden_sefler=None`: önceki plandaki "şef sahaya gidiyor" bayrağı
    korunur. `beklenen_aktif_plan_id`: istemcinin gördüğü aktif plan —
    uyuşmazsa 409 (iki şefin ardışık kaydı birbirini sessizce ezmesin;
    iş satırının `version`'ı durum değişmeyen planlamada artmadığı için
    iyimser kilit plan kimliğine bağlandı, E02 kontrol #10).
    """

    plan_date: date
    duration_min: int
    start_time: time | None = None
    ekip: list[AtamaSatiri] | None = None
    sahaya_giden_sefler: list[int] | None = None
    vehicle_id: int | None = None
    site_area: str | None = None
    site_note: str | None = None
    plan_note: str | None = None
    change_reason: str | None = None
    change_note: str | None = None
    conflict_override_note: str | None = None
    # Yalnız tekli planda karşılaştırılır; toplu/yeniden planda her işin
    # aktif planı sunucuda kilit altında okunur.
    beklenen_aktif_plan_id: int | None = None


# --- Yardımcılar -------------------------------------------------------------------


def saat_araligi(
    gun: date, baslangic: time | None, sure_dk: int
) -> tuple[datetime | None, datetime | None]:
    """Yerel (İstanbul) gün + saat → UTC `[starts_at, ends_at)`; saat yoksa (None, None)."""
    if baslangic is None:
        return None, None
    bas = datetime.combine(gun, baslangic, tzinfo=YEREL)
    return bas, bas + timedelta(minutes=sure_dk)


def _sure_dogrula(sure: int) -> None:
    if not PLAN_SURE_ALT_DK <= sure <= PLAN_SURE_UST_DK:
        raise PlanlamaGirdiHatasi(
            f"Plan süresi {PLAN_SURE_ALT_DK}–{PLAN_SURE_UST_DK} dk arasında olmalı"
        )


def _neden_dogrula(neden: str | None, not_: str | None) -> None:
    if neden is None:
        return
    if neden not in PLAN_NEDENLERI:
        raise PlanlamaGirdiHatasi(f"Geçersiz neden: {neden} (geçerli: {', '.join(PLAN_NEDENLERI)})")
    if neden == "DIGER" and not (not_ or "").strip():
        raise PlanlamaGirdiHatasi("'Diğer' nedeninde açıklama zorunlu")


def _metin(deger: str | None) -> str | None:
    return (deger.strip() or None) if isinstance(deger, str) else deger


async def _isi_kilitle(db: AsyncSession, so_id: int) -> ServiceOrder:
    so = await db.scalar(
        select(ServiceOrder)
        .where(ServiceOrder.id == so_id, ServiceOrder.is_deleted.is_(False))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if so is None:
        raise PlanlamaBulunamadi("Servis işi bulunamadı")
    return so


async def aktif_plan(db: AsyncSession, so_id: int) -> ServicePlan | None:
    return await db.scalar(
        select(ServicePlan).where(
            ServicePlan.service_order_id == so_id,
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
        )
    )


async def plan_uyeleri(db: AsyncSession, plan_idler: Sequence[int]) -> dict[int, list]:
    """plan_id → üye satırları (rol sırası: şef önce)."""
    if not plan_idler:
        return {}
    satirlar = (
        await db.scalars(
            select(ServicePlanMember)
            .where(ServicePlanMember.plan_id.in_(list(plan_idler)))
            .order_by(ServicePlanMember.plan_id, ServicePlanMember.rol, ServicePlanMember.id)
        )
    ).all()
    sonuc: dict[int, list] = {}
    for s in satirlar:
        sonuc.setdefault(s.plan_id, []).append(s)
    return sonuc


async def _arac_dogrula(db: AsyncSession, arac_id: int | None, birim: str) -> None:
    """Araç aktif ve işin birimine (ya da ortak havuza) ait olmalı; aksi 409."""
    if arac_id is None:
        return
    arac = await db.get(ServiceVehicle, arac_id)
    if arac is None or arac.is_deleted or not arac.is_active:
        raise PlanlamaHatasi("Seçilen servis aracı aktif değil")
    if arac.birim is not None and arac.birim != birim:
        raise PlanlamaHatasi("Seçilen servis aracı bu birimin havuzunda değil")


async def _ekip_dogrula(db: AsyncSession, ekip: Sequence[AtamaSatiri], birim: str) -> None:
    """Atama kuralının AYNISI (TS-025 tek kaynak; `atama` modülünün doğrulayıcıları).

    Çakışma kontrolünden ve hiçbir yazımdan ÖNCE çağrılır: ayrılmış/pasif/
    saha rolsüz kişi 400, işin biriminde olmayan kişi 409 (E01-12 kabul 8).
    Planlama ayrı bir ölçüt yazsaydı "planda var, atamada yok" ayrışması
    doğardı.
    """
    atama.satirlari_dogrula(ekip)  # aynı katmanın tek kural kaynağı
    await atama.atanabilirlik_dogrula(db, birim, {s.user_id for s in ekip})


def _ekip_kumesi(satirlar: Sequence[Any]) -> set[tuple[int, str, bool]]:
    return {(s.user_id, s.rol, bool(getattr(s, "is_lead", False))) for s in satirlar}


async def _uyeleri_yaz(
    db: AsyncSession,
    plan: ServicePlan,
    ekip: Sequence[Any],
    sahaya_giden_sefler: set[int],
) -> None:
    for satir in ekip:
        sahada = satir.rol == "TEKNISYEN" or satir.user_id in sahaya_giden_sefler
        db.add(
            ServicePlanMember(
                plan_id=plan.id, user_id=satir.user_id, rol=satir.rol, sahaya_gidiyor=sahada
            )
        )


def _sahadakiler(ekip: Sequence[Any], sahaya_giden_sefler: set[int]) -> list[int]:
    return sorted(
        {s.user_id for s in ekip if s.rol == "TEKNISYEN" or s.user_id in sahaya_giden_sefler}
    )


async def _onceki_sahaya_gidenler(db: AsyncSession, plan: ServicePlan | None) -> set[int]:
    if plan is None:
        return set()
    return set(
        await db.scalars(
            select(ServicePlanMember.user_id).where(
                ServicePlanMember.plan_id == plan.id,
                ServicePlanMember.rol == "SEF",
                ServicePlanMember.sahaya_gidiyor.is_(True),
            )
        )
    )


async def _cakisma_kontrol(
    db: AsyncSession,
    *,
    sahadakiler: Sequence[int],
    baslangic: datetime | None,
    bitis: datetime | None,
    arac_id: int | None,
    user: User,
    gerekce: str | None,
    haric_plan_idler: Sequence[int] = (),
    haric_so_idler: Sequence[int] = (),
    visit_id: int | None = None,
) -> list[cakisma.Cakisma]:
    """Çakışma varsa ve gerekçe yoksa PlanCakismasi (409). Gerekçe yetersizse 400."""
    bulunan = await cakisma.cakismalari_bul(
        db,
        sahadakiler,
        baslangic,
        bitis,
        goren=user,
        arac_id=arac_id,
        haric_plan_idler=haric_plan_idler,
        haric_so_idler=haric_so_idler,
        visit_id=visit_id,
    )
    if not bulunan:
        return []
    if not gerekce:
        raise cakisma.PlanCakismasi(
            "Plan başka bir işle ya da müsaitlik bloğuyla çakışıyor. "
            "Gerekçe yazarak kaydedebilirsiniz.",
            bulunan,
        )
    if not cakisma.gerekce_gecerli_mi(gerekce):
        raise PlanlamaGirdiHatasi(
            f"Çakışma gerekçesi en az {cakisma.GEREKCE_ASGARI} karakter olmalı"
        )
    if not user.has("servis.planla"):  # savunma: uç zaten servis.planla ister
        raise PlanlamaHatasi("Çakışmayı geçme yetkiniz yok")
    return bulunan


async def _durum_planla(db: AsyncSession, so: ServiceOrder, *, user: User, clock: Clock) -> None:
    if so.status in PLANLANDIYA_GECER:
        await is_emirleri.durum_degistir(
            db, so, "PLANLANDI", kaynak="planla", user=user, clock=clock
        )


def _plan_ozeti(plan: ServicePlan) -> dict[str, Any]:
    return {
        "plan_id": plan.id,
        "ziyaret_id": plan.visit_id,
        "plan_tarihi": plan.plan_date.isoformat(),
        "baslangic_saati": plan.start_time.strftime("%H:%M") if plan.start_time else None,
        "sure_dk": plan.duration_min,
        "arac_id": plan.vehicle_id,
        "degisim": plan.change_type,
        "neden": plan.change_reason,
    }


async def _plan_olayi(
    db: AsyncSession,
    so: ServiceOrder,
    plan: ServicePlan,
    onceki: ServicePlan | None,
    ekip: Sequence[Any],
    *,
    user: User | None,
    clock: Clock,
    islem: str,
    cakismalar: Sequence[cakisma.Cakisma] = (),
) -> None:
    """PLAN olayı (kişisel veri yok: kişiler kimlikle, not metni yok)."""
    veri: dict[str, Any] = {
        "islem": islem,
        **_plan_ozeti(plan),
        "ekip": [{"user_id": s.user_id, "rol": s.rol} for s in ekip],
    }
    if onceki is not None:
        veri["onceki"] = _plan_ozeti(onceki)
    if cakismalar:
        veri["cakisma_gecildi"] = True
        veri["cakisma_sayisi"] = len(cakismalar)
    saat = plan.start_time.strftime("%H:%M") if plan.start_time else "saat belirsiz"
    ozet = {
        "ILK_PLAN": f"Planlandı: {plan.plan_date:%d.%m.%Y} {saat}",
        "ERTELEME": f"Ertelendi: {plan.plan_date:%d.%m.%Y} {saat}",
        "YENIDEN_PLAN": f"Yeniden planlandı: {plan.plan_date:%d.%m.%Y} {saat}",
        "EKIP_DEGISIMI": f"Plan güncellendi (ekip/araç): {plan.plan_date:%d.%m.%Y} {saat}",
    }[plan.change_type]
    if cakismalar:
        ozet += " — çakışma gerekçeyle geçildi"
    await gecmis.olay_yaz(db, so, "PLAN", ozet, user=user, clock=clock, veri=veri)


async def _ekibi_yaz(
    db: AsyncSession, so: ServiceOrder, ekip: Sequence[AtamaSatiri], *, user: User, clock: Clock
) -> None:
    """Ekip farklıysa `atama.ata` (tek kaynak); aynıysa ATAMA gürültüsü üretilmez."""
    mevcut = await atama.aktif_ekip(db, so)
    if _ekip_kumesi(mevcut) == _ekip_kumesi(ekip):
        return
    belirtec = _PLAN_YAZILIYOR.set(True)
    try:
        await atama.ata(db, so, list(ekip), user=user, clock=clock)
    finally:
        _PLAN_YAZILIYOR.reset(belirtec)


async def _toplu_ust_sinir(db: AsyncSession) -> int:
    try:
        deger = await ayar_svc.get(db, TOPLU_UST_SINIR_ANAHTARI)
    except KeyError:  # pragma: no cover - ayar kataloğu Dalga 0'da sabit
        return TOPLU_VARSAYILAN_UST_SINIR
    return int(deger or TOPLU_VARSAYILAN_UST_SINIR)


async def _isleri_kilitle(
    db: AsyncSession, is_idler: Sequence[int], user: User
) -> list[ServiceOrder]:
    """Id sıralı FOR UPDATE (deadlock önlemi); eksik ya da kapsam dışı → 404."""
    idler = sorted(set(is_idler))
    if not idler:
        raise PlanlamaGirdiHatasi("En az bir iş seçilmeli")
    ust = await _toplu_ust_sinir(db)
    if len(idler) > ust:
        raise PlanlamaGirdiHatasi(f"Tek seferde en çok {ust} iş planlanabilir")
    isler = (
        await db.scalars(
            select(ServiceOrder)
            .where(ServiceOrder.id.in_(idler), ServiceOrder.is_deleted.is_(False))
            .order_by(ServiceOrder.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    if len(isler) != len(idler):
        raise PlanlamaBulunamadi("Seçilen işlerden biri bulunamadı")
    erisilebilir = set(
        await db.scalars(
            kapsam.kapsam_isler(
                select(ServiceOrder.id).where(ServiceOrder.id.in_(idler)), user, ServiceOrder.id
            )
        )
    )
    if erisilebilir != set(idler):
        raise PlanlamaBulunamadi("Seçilen işlerden biri bulunamadı")
    return list(isler)


def _kural(isler: Sequence[ServiceOrder], kosul, mesaj: str) -> None:
    sorunlu = [so.so_no for so in isler if kosul(so)]
    if sorunlu:
        raise PlanlamaHatasi(f"{mesaj}: {', '.join(sorunlu)}", sorunlu)


def _tek_deger(isler: Sequence[ServiceOrder], anahtar, mesaj: str) -> None:
    degerler = {anahtar(so) for so in isler}
    if len(degerler) > 1:
        ilk = anahtar(isler[0])
        sorunlu = [so.so_no for so in isler if anahtar(so) != ilk]
        raise PlanlamaHatasi(f"{mesaj}: {', '.join(sorunlu)}", sorunlu)


async def _ziyaret_ac(
    db: AsyncSession, ornek: ServiceOrder, gun: date, *, user: User, notlar: str | None = None
) -> ServiceVisit:
    ziyaret = ServiceVisit(
        visit_no=await numara.belge_no(db, "service_visit_no_seq", "ZYR", gun),
        birim=ornek.birim,
        customer_id=ornek.customer_id,
        address_id=ornek.address_id,
        notes=notlar,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(ziyaret)
    await db.flush()
    return ziyaret


def _yeni_plan(
    so: ServiceOrder,
    girdi: PlanGirdisi,
    *,
    degisim: str,
    visit_id: int | None,
    user_id: int | None,
    cakisma_notu: str | None,
) -> ServicePlan:
    bas, bit = saat_araligi(girdi.plan_date, girdi.start_time, girdi.duration_min)
    return ServicePlan(
        service_order_id=so.id,
        visit_id=visit_id,
        is_active=True,
        plan_date=girdi.plan_date,
        start_time=girdi.start_time,
        duration_min=girdi.duration_min,
        starts_at=bas,
        ends_at=bit,
        vehicle_id=girdi.vehicle_id,
        site_area=_metin(girdi.site_area),
        site_note=_metin(girdi.site_note),
        plan_note=_metin(girdi.plan_note),
        change_type=degisim,
        change_reason=girdi.change_reason if degisim != "ILK_PLAN" else None,
        change_note=_metin(girdi.change_note) if degisim != "ILK_PLAN" else None,
        conflict_override_note=cakisma_notu,
        created_by=user_id,
        updated_by=user_id,
    )


async def _pasifle(
    db: AsyncSession,
    plan: ServicePlan,
    an: datetime,
    user_id: int | None,
    *,
    neden: str | None = None,
    not_: str | None = None,
) -> None:
    plan.is_active = False
    plan.cancelled_at = an
    plan.updated_by = user_id
    if neden is not None:
        plan.cancel_reason = neden
        plan.cancel_note = _metin(not_)
    # Yeni aktif satır aynı flush'ta eklenirse kısmi tekil indeks çakışmasın.
    await db.flush()


# --- Tekli plan (TS-040/041) ---------------------------------------------------------


async def planla(
    db: AsyncSession, so: ServiceOrder, girdi: PlanGirdisi, *, user: User, clock: Clock
) -> ServicePlan:
    """Tekli plan + ekip (tek transaction). Kapsam kontrolü çağıranındır (404)."""
    so = await _isi_kilitle(db, so.id)
    if so.status in KAPALI:
        raise PlanlamaHatasi(f"Kapalı işe ({so.status}) plan yapılamaz", [so.so_no])
    _sure_dogrula(girdi.duration_min)
    _neden_dogrula(girdi.change_reason, girdi.change_note)

    onceki = await aktif_plan(db, so.id)
    if (onceki.id if onceki else None) != girdi.beklenen_aktif_plan_id:
        raise PlanlamaHatasi(
            "Bu işin planı siz görüntülerken değişti. Sayfayı yenileyip tekrar deneyin."
        )

    # Değişim türü: tarih/saat değiştiyse erteleme (neden zorunlu); değilse
    # ekip/araç/süre/not güncellemesi (EKIP_DEGISIMI, nedensiz).
    if onceki is None:
        degisim = "ILK_PLAN"
    elif (onceki.plan_date, onceki.start_time) != (girdi.plan_date, girdi.start_time):
        degisim = "ERTELEME"
        if not girdi.change_reason:
            raise PlanlamaHatasi("Plan tarihi/saati değişiyor: erteleme nedeni zorunlu")
    else:
        degisim = "EKIP_DEGISIMI"

    await _arac_dogrula(db, girdi.vehicle_id, so.birim)
    if girdi.ekip is not None:
        await _ekip_dogrula(db, girdi.ekip, so.birim)
        ekip: Sequence[Any] = list(girdi.ekip)
    else:
        ekip = await atama.aktif_ekip(db, so)
    sahaya_giden = (
        set(girdi.sahaya_giden_sefler)
        if girdi.sahaya_giden_sefler is not None
        else await _onceki_sahaya_gidenler(db, onceki)
    )
    sahadakiler = _sahadakiler(ekip, sahaya_giden)

    bas, bit = saat_araligi(girdi.plan_date, girdi.start_time, girdi.duration_min)
    await cakisma.gun_kilitleri(db, cakisma.dokunulan_gunler(bas, bit, girdi.plan_date))
    gecilen = await _cakisma_kontrol(
        db,
        sahadakiler=sahadakiler,
        baslangic=bas,
        bitis=bit,
        arac_id=girdi.vehicle_id,
        user=user,
        gerekce=girdi.conflict_override_note,
        haric_so_idler=[so.id],
        visit_id=onceki.visit_id if onceki and degisim == "EKIP_DEGISIMI" else None,
    )

    # Ziyaret: tekli planda istemciden alınmaz. Gün/saat aynıysa ziyaret
    # korunur; değişiyorsa ve ziyarette başka iş kalıyorsa iş ziyaretten ayrılır.
    visit_id = onceki.visit_id if onceki else None
    if onceki is not None and visit_id is not None and degisim == "ERTELEME":
        baska = await db.scalar(
            select(func.count())
            .select_from(ServicePlan)
            .where(
                ServicePlan.visit_id == visit_id,
                ServicePlan.is_active.is_(True),
                ServicePlan.is_deleted.is_(False),
                ServicePlan.service_order_id != so.id,
            )
        )
        if baska:
            visit_id = None

    an = clock.now()
    if onceki is not None:
        await _pasifle(db, onceki, an, user.id)
    if girdi.ekip is not None:
        await _ekibi_yaz(db, so, girdi.ekip, user=user, clock=clock)

    plan = _yeni_plan(
        so,
        girdi,
        degisim=degisim,
        visit_id=visit_id,
        user_id=user.id,
        cakisma_notu=_metin(girdi.conflict_override_note) if gecilen else None,
    )
    db.add(plan)
    await db.flush()
    await _uyeleri_yaz(db, plan, ekip, sahaya_giden)
    await _durum_planla(db, so, user=user, clock=clock)
    await _plan_olayi(
        db, so, plan, onceki, ekip, user=user, clock=clock, islem="PLANLA", cakismalar=gecilen
    )
    await audit.log(
        db,
        "service_plans",
        "planla",
        entity_id=plan.id,
        old_value=_plan_ozeti(onceki) if onceki else None,
        new_value={**_plan_ozeti(plan), "so_id": so.id, "cakisma_gecildi": bool(gecilen)},
        user_id=user.id,
    )
    await db.flush()
    return plan


# --- Geri alma ve geçmiş (TS-044) ----------------------------------------------------


async def plani_geri_al(
    db: AsyncSession,
    so: ServiceOrder,
    neden: str | None,
    *,
    not_: str | None,
    user: User,
    clock: Clock,
) -> ServicePlan:
    """Aktif planı kapatır; yalnız PLANLANDI → PLANLAMADA (`kaynak='plan_geri_al'`).

    Nedensiz geri alma 409; kapalı işte 409; aktif plan yoksa 409.
    Sahada/atölyede/beklemedeki işin durumu DEĞİŞMEZ.
    """
    so = await _isi_kilitle(db, so.id)
    if so.status in KAPALI:
        raise PlanlamaHatasi(f"Kapalı işin ({so.status}) planı geri alınamaz", [so.so_no])
    if not neden:
        raise PlanlamaHatasi("Planı geri almak için neden zorunlu")
    _neden_dogrula(neden, not_)
    plan = await aktif_plan(db, so.id)
    if plan is None:
        raise PlanlamaHatasi("Bu işin aktif planı yok")
    await _pasifle(db, plan, clock.now(), user.id, neden=neden, not_=not_)
    if so.status == "PLANLANDI":
        await is_emirleri.durum_degistir(
            db, so, "PLANLAMADA", kaynak="plan_geri_al", user=user, clock=clock
        )
    await gecmis.olay_yaz(
        db,
        so,
        "PLAN",
        f"Plan geri alındı ({plan.plan_date:%d.%m.%Y})",
        user=user,
        clock=clock,
        veri={"islem": "GERI_AL", "neden": neden, **_plan_ozeti(plan)},
    )
    await audit.log(
        db,
        "service_plans",
        "geri_al",
        entity_id=plan.id,
        new_value={"so_id": so.id, "neden": neden},
        user_id=user.id,
    )
    await db.flush()
    return plan


async def plan_gecmisi(db: AsyncSession, so: ServiceOrder) -> list[ServicePlan]:
    """Aktif ve pasif BÜTÜN plan satırları, eskiden yeniye."""
    return list(
        (
            await db.scalars(
                select(ServicePlan)
                .where(ServicePlan.service_order_id == so.id, ServicePlan.is_deleted.is_(False))
                .order_by(ServicePlan.created_at, ServicePlan.id)
            )
        ).all()
    )


# --- Toplu plan (TS-043) -------------------------------------------------------------


async def toplu_planla(
    db: AsyncSession, is_idler: Sequence[int], girdi: PlanGirdisi, *, user: User, clock: Clock
) -> ServiceVisit:
    """Aynı birim + müşteri + lokasyon, plansız açık işler → TEK ziyaret, iş başına plan.

    İşler birleştirilmez (1 cihaz = 1 PB iş emri korunur). Kural ihlalinde
    409 + iş no listesi ve hiçbir satır yazılmaz.
    """
    isler = await _isleri_kilitle(db, is_idler, user)
    _sure_dogrula(girdi.duration_min)
    _kural(isler, lambda so: so.status in KAPALI, "Kapalı/iptal işler planlanamaz")
    planlilar = set(
        await db.scalars(
            select(ServicePlan.service_order_id).where(
                ServicePlan.service_order_id.in_([so.id for so in isler]),
                ServicePlan.is_active.is_(True),
                ServicePlan.is_deleted.is_(False),
            )
        )
    )
    _kural(
        isler,
        lambda so: so.id in planlilar,
        "Zaten planlı işler toplu plana alınamaz (yeniden planlayın)",
    )
    _tek_deger(isler, lambda so: so.birim, "Seçilen işler farklı birimlerde")
    _tek_deger(isler, lambda so: so.customer_id, "Seçilen işler farklı müşterilerde")
    if len(isler) > 1:
        _kural(
            isler,
            lambda so: ana_veri.lokasyon_anahtari(so) is None,
            "Lokasyonu belirsiz işler toplu planlanamaz",
        )
    _tek_deger(isler, ana_veri.lokasyon_anahtari, "Seçilen işler farklı lokasyonlarda")

    ornek = isler[0]
    if not girdi.ekip:
        raise PlanlamaGirdiHatasi("Toplu planda en az bir şef ya da teknisyen seçilmeli")
    await _ekip_dogrula(db, girdi.ekip, ornek.birim)
    await _arac_dogrula(db, girdi.vehicle_id, ornek.birim)
    sahaya_giden = set(girdi.sahaya_giden_sefler or ())
    sahadakiler = _sahadakiler(girdi.ekip, sahaya_giden)

    bas, bit = saat_araligi(girdi.plan_date, girdi.start_time, girdi.duration_min)
    await cakisma.gun_kilitleri(db, cakisma.dokunulan_gunler(bas, bit, girdi.plan_date))
    gecilen = await _cakisma_kontrol(
        db,
        sahadakiler=sahadakiler,
        baslangic=bas,
        bitis=bit,
        arac_id=girdi.vehicle_id,
        user=user,
        gerekce=girdi.conflict_override_note,
        haric_so_idler=[so.id for so in isler],
    )

    ziyaret = await _ziyaret_ac(
        db, ornek, girdi.plan_date, user=user, notlar=_metin(girdi.plan_note)
    )
    for so in isler:
        await _ekibi_yaz(db, so, girdi.ekip, user=user, clock=clock)
        plan = _yeni_plan(
            so,
            girdi,
            degisim="ILK_PLAN",
            visit_id=ziyaret.id,
            user_id=user.id,
            cakisma_notu=_metin(girdi.conflict_override_note) if gecilen else None,
        )
        db.add(plan)
        await db.flush()
        await _uyeleri_yaz(db, plan, girdi.ekip, sahaya_giden)
        await _durum_planla(db, so, user=user, clock=clock)
        await _plan_olayi(
            db,
            so,
            plan,
            None,
            girdi.ekip,
            user=user,
            clock=clock,
            islem="TOPLU_PLAN",
            cakismalar=gecilen,
        )
    await audit.log(
        db,
        "service_visits",
        "toplu_planla",
        entity_id=ziyaret.id,
        new_value={
            "ziyaret_no": ziyaret.visit_no,
            "is_idler": [so.id for so in isler],
            "plan_tarihi": girdi.plan_date.isoformat(),
            "cakisma_gecildi": bool(gecilen),
        },
        user_id=user.id,
    )
    await db.flush()
    return ziyaret


# --- Yeniden plan (TS-046) -----------------------------------------------------------


async def yeniden_planla(
    db: AsyncSession, is_idler: Sequence[int], girdi: PlanGirdisi, *, user: User, clock: Clock
) -> list[ServicePlan]:
    """Ziyaret kartında seçili işleri tek işlemde taşır.

    - Yalnız gönderilen işler taşınır; ziyarette kalan seçilmemiş iş eski
      planında kalır.
    - Tarih/saat değişen işte YENIDEN_PLAN (neden zorunlu, aksi 409); yalnız
      ekip/araç/süre değişen işte EKIP_DEGISIMI.
    - Seçilenler bir ziyaretin TÜM aktif işleriyse ziyaret korunur; aksi
      halde seçilenler yeni ziyarete ayrılır (tek işse ziyaretsiz kalır).
    """
    isler = await _isleri_kilitle(db, is_idler, user)
    _sure_dogrula(girdi.duration_min)
    _neden_dogrula(girdi.change_reason, girdi.change_note)
    _kural(isler, lambda so: so.status in KAPALI, "Kapalı/iptal işler yeniden planlanamaz")
    eski: dict[int, ServicePlan] = {}
    for so in isler:
        plan = await aktif_plan(db, so.id)
        if plan is not None:
            eski[so.id] = plan
    _kural(isler, lambda so: so.id not in eski, "Aktif planı olmayan işler (önce planlayın)")
    _tek_deger(isler, lambda so: so.birim, "Seçilen işler farklı birimlerde")

    degisenler = {
        so.id
        for so in isler
        if (eski[so.id].plan_date, eski[so.id].start_time) != (girdi.plan_date, girdi.start_time)
    }
    if degisenler and not girdi.change_reason:
        sorunlu = [so.so_no for so in isler if so.id in degisenler]
        raise PlanlamaHatasi("Tarih/saat değişiyor: yeniden planlama nedeni zorunlu", sorunlu)

    ornek = isler[0]
    await _arac_dogrula(db, girdi.vehicle_id, ornek.birim)
    if girdi.ekip is not None:
        await _ekip_dogrula(db, girdi.ekip, ornek.birim)

    # Ziyaret kararı.
    ziyaretler = {eski[so.id].visit_id for so in isler}
    secilen = {so.id for so in isler}
    korunan_ziyaret: int | None = None
    if len(ziyaretler) == 1 and None not in ziyaretler:
        vid = next(iter(ziyaretler))
        ziyaret_isleri = set(
            await db.scalars(
                select(ServicePlan.service_order_id).where(
                    ServicePlan.visit_id == vid,
                    ServicePlan.is_active.is_(True),
                    ServicePlan.is_deleted.is_(False),
                )
            )
        )
        if ziyaret_isleri == secilen:
            korunan_ziyaret = vid
    yeni_ziyaret_gerekli = korunan_ziyaret is None and len(isler) > 1
    if yeni_ziyaret_gerekli:
        _tek_deger(
            isler, ana_veri.lokasyon_anahtari, "Farklı lokasyondaki işler tek ziyarette taşınamaz"
        )
        _kural(
            isler,
            lambda so: ana_veri.lokasyon_anahtari(so) is None,
            "Lokasyonu belirsiz işler birlikte taşınamaz",
        )
    tekil_ziyaret: int | None = None
    if korunan_ziyaret is None and len(isler) == 1:
        # Tek iş: ziyarette başka aktif iş yoksa ziyaret onunla kalır.
        vid = eski[ornek.id].visit_id
        if vid is not None:
            baska = await db.scalar(
                select(func.count())
                .select_from(ServicePlan)
                .where(
                    ServicePlan.visit_id == vid,
                    ServicePlan.is_active.is_(True),
                    ServicePlan.is_deleted.is_(False),
                    ServicePlan.service_order_id != ornek.id,
                )
            )
            tekil_ziyaret = None if baska else vid

    # Ekip: verilmediyse her iş kendi ekibini korur.
    ekipler: dict[int, Sequence[Any]] = {}
    sahaya: dict[int, set[int]] = {}
    for so in isler:
        ekipler[so.id] = (
            list(girdi.ekip) if girdi.ekip is not None else await atama.aktif_ekip(db, so)
        )
        sahaya[so.id] = (
            set(girdi.sahaya_giden_sefler)
            if girdi.sahaya_giden_sefler is not None
            else await _onceki_sahaya_gidenler(db, eski[so.id])
        )
    sahadakiler = sorted({u for so in isler for u in _sahadakiler(ekipler[so.id], sahaya[so.id])})

    bas, bit = saat_araligi(girdi.plan_date, girdi.start_time, girdi.duration_min)
    gunler = set(cakisma.dokunulan_gunler(bas, bit, girdi.plan_date))
    await cakisma.gun_kilitleri(db, gunler)
    gecilen = await _cakisma_kontrol(
        db,
        sahadakiler=sahadakiler,
        baslangic=bas,
        bitis=bit,
        arac_id=girdi.vehicle_id,
        user=user,
        gerekce=girdi.conflict_override_note,
        haric_so_idler=sorted(secilen),
        visit_id=korunan_ziyaret,
    )

    an = clock.now()
    if korunan_ziyaret is not None:
        hedef_ziyaret: int | None = korunan_ziyaret
    elif yeni_ziyaret_gerekli:
        hedef_ziyaret = (await _ziyaret_ac(db, ornek, girdi.plan_date, user=user)).id
    else:
        hedef_ziyaret = tekil_ziyaret

    yeni_planlar: list[ServicePlan] = []
    for so in isler:
        onceki = eski[so.id]
        await _pasifle(db, onceki, an, user.id)
        if girdi.ekip is not None:
            await _ekibi_yaz(db, so, girdi.ekip, user=user, clock=clock)
        degisim = "YENIDEN_PLAN" if so.id in degisenler else "EKIP_DEGISIMI"
        plan = _yeni_plan(
            so,
            girdi,
            degisim=degisim,
            visit_id=hedef_ziyaret,
            user_id=user.id,
            cakisma_notu=_metin(girdi.conflict_override_note) if gecilen else None,
        )
        if degisim == "EKIP_DEGISIMI":
            plan.change_reason = girdi.change_reason
            plan.change_note = _metin(girdi.change_note) if girdi.change_reason else None
        db.add(plan)
        await db.flush()
        await _uyeleri_yaz(db, plan, ekipler[so.id], sahaya[so.id])
        # Durum korunur (E02-02): yeniden plan durumu geri çekmez.
        await _plan_olayi(
            db,
            so,
            plan,
            onceki,
            ekipler[so.id],
            user=user,
            clock=clock,
            islem="YENIDEN_PLAN",
            cakismalar=gecilen,
        )
        yeni_planlar.append(plan)
    await audit.log(
        db,
        "service_plans",
        "yeniden_planla",
        new_value={
            "is_idler": sorted(secilen),
            "plan_tarihi": girdi.plan_date.isoformat(),
            "ziyaret_id": hedef_ziyaret,
            "cakisma_gecildi": bool(gecilen),
        },
        user_id=user.id,
    )
    await db.flush()
    return yeni_planlar


# --- Ekip senkronu kancası (E02-D01) ------------------------------------------------


async def ekip_degisti(
    db: AsyncSession, so: ServiceOrder, yeni_ekip: Sequence[Any], clock: Clock
) -> None:
    """`ekip_degisti` kancası: aktif planda EKIP_DEGISIMI satırı açar.

    Plan tarihi/saati/aracı aynen kopyalanır; üyeler = yeni ekip. Aktif plan
    yoksa hiçbir şey yapmaz (plansız iş: ekip yalnız atamada durur). Planlama
    kendi yazımında bu kancayı devre dışı bırakır (çift satır olmasın).
    Önceki planın kapanış anı kancanın `clock`'undan (Dalga 2'de imzaya
    eklendi; önceden atama damgalarından türetiliyordu).
    """
    if _PLAN_YAZILIYOR.get():
        return
    onceki = await aktif_plan(db, so.id)
    if onceki is None:
        return
    ekip = [s for s in yeni_ekip if getattr(s, "removed_at", None) is None]
    eski_uyeler = (await plan_uyeleri(db, [onceki.id])).get(onceki.id, [])
    if {(u.user_id, u.rol) for u in eski_uyeler} == {(s.user_id, s.rol) for s in ekip}:
        return  # yalnız sorumlu değişti: plan ekibi aynı
    sahaya_giden = {u.user_id for u in eski_uyeler if u.rol == "SEF" and u.sahaya_gidiyor}
    an = clock.now()
    yapan = next(
        (getattr(s, "assigned_by", None) for s in ekip if getattr(s, "assigned_by", None)), None
    )
    onceki.is_active = False
    onceki.cancelled_at = an
    await db.flush()
    plan = ServicePlan(
        service_order_id=so.id,
        visit_id=onceki.visit_id,
        is_active=True,
        plan_date=onceki.plan_date,
        start_time=onceki.start_time,
        duration_min=onceki.duration_min,
        starts_at=onceki.starts_at,
        ends_at=onceki.ends_at,
        vehicle_id=onceki.vehicle_id,
        site_area=onceki.site_area,
        site_note=onceki.site_note,
        plan_note=onceki.plan_note,
        change_type="EKIP_DEGISIMI",
        created_by=yapan,
        updated_by=yapan,
    )
    db.add(plan)
    await db.flush()
    await _uyeleri_yaz(db, plan, ekip, sahaya_giden)
    await db.flush()


# --- Saha önerisi (TS-047) -----------------------------------------------------------


async def irtibat_gorur(db: AsyncSession, user: User, so: ServiceOrder) -> bool:
    """Saha irtibatı (ad, telefon, açık adres) görülebilir mi? (E02-24)

    `servis.irtibat_gor` izni ya da işte aktif ataması / aktif plan üyeliği.
    """
    if user.has("servis.irtibat_gor"):
        return True
    atanmis = await db.scalar(
        select(ServiceOrderAssignment.id).where(
            ServiceOrderAssignment.service_order_id == so.id,
            ServiceOrderAssignment.user_id == user.id,
            ServiceOrderAssignment.removed_at.is_(None),
        )
    )
    if atanmis is not None:
        return True
    uye = await db.scalar(
        select(ServicePlanMember.id)
        .join(ServicePlan, ServicePlan.id == ServicePlanMember.plan_id)
        .where(
            ServicePlan.service_order_id == so.id,
            ServicePlan.is_active.is_(True),
            ServicePlanMember.user_id == user.id,
        )
    )
    return uye is not None


async def _ayni_lokasyon_son_plani(db: AsyncSession, so: ServiceOrder) -> ServicePlan | None:
    anahtar = ana_veri.lokasyon_anahtari(so)
    if anahtar is None or so.customer_id is None:
        return None
    stmt = (
        select(ServicePlan, ServiceOrder)
        .join(ServiceOrder, ServiceOrder.id == ServicePlan.service_order_id)
        .where(
            ServicePlan.is_deleted.is_(False),
            ServiceOrder.customer_id == so.customer_id,
            ServiceOrder.birim == so.birim,
            or_(ServicePlan.site_area.is_not(None), ServicePlan.site_note.is_not(None)),
        )
        .order_by(ServicePlan.created_at.desc(), ServicePlan.id.desc())
        .limit(200)
    )
    if so.address_id is not None:
        stmt = stmt.where(ServiceOrder.address_id == so.address_id)
    for plan, aday in (await db.execute(stmt)).all():
        if ana_veri.lokasyon_anahtari(aday) == anahtar:
            return plan
    return None


async def saha_onerisi(db: AsyncSession, so: ServiceOrder, user: User) -> dict[str, Any]:
    """Aynı müşteri + lokasyonun son planından ve tesis kaydından saha önerisi.

    - Alan bazında `{alan, deger, kaynak}`; kayıt yoksa alan dönmez (tahmin yok).
    - Adres ve irtibat YALNIZ işin müşterisine ait tesisten gelir; kütükteki
      ham ad (`contact_name_raw`) önerilmez (E14 K3).
    - Telefon yalnız irtibat görme yetkisinde (E02-24).
    """
    alanlar: list[dict[str, Any]] = []
    gorur = await irtibat_gorur(db, user, so)
    if so.address_id is not None:
        adres = await db.get(Address, so.address_id)
        if adres is not None and adres.account_id == so.customer_id:
            kaynak = await ana_veri.saha_onerisi_kaynak(db, so.address_id)
            if kaynak:
                for alan, deger in (
                    ("tesis_adi", kaynak["tesis_adi"]),
                    ("il", kaynak["il"]),
                    ("ilce", kaynak["ilce"]),
                    ("acik_adres", kaynak["adres"] if gorur else None),
                    ("erisim_notu", kaynak["erisim_notu"]),
                ):
                    if deger:
                        alanlar.append({"alan": alan, "deger": deger, "kaynak": "LOKASYON"})
                kisi = kaynak.get("irtibat")
                if kisi and gorur:
                    alanlar.append(
                        {"alan": "irtibat_id", "deger": kisi["id"], "kaynak": "LOKASYON"}
                    )
                    alanlar.append(
                        {"alan": "irtibat_adi", "deger": kisi["ad"], "kaynak": "LOKASYON"}
                    )
                    if kisi.get("telefon"):
                        alanlar.append(
                            {
                                "alan": "irtibat_telefon",
                                "deger": kisi["telefon"],
                                "kaynak": "LOKASYON",
                            }
                        )
    onceki = await _ayni_lokasyon_son_plani(db, so)
    if onceki is not None:
        for alan, deger in (("saha_bolgesi", onceki.site_area), ("saha_notu", onceki.site_note)):
            if deger:
                alanlar.append({"alan": alan, "deger": deger, "kaynak": "ONCEKI_PLAN"})
    return {"is_id": so.id, "alanlar": alanlar}


# --- Müsaitlik blokları (TS-190, E02-20) ----------------------------------------------
#
# Bordro/izin modülü DEĞİLDİR: yalnız "bu kişi bu aralıkta sahaya çıkamaz"
# bilgisini tutar; çakışma motoru `MUSAITLIK` türü üretir (gerekçeyle geçilir).
# Zaman/kişi-saat raporları bu tabloyu OKUMAZ.
#
# **Sağlık bilgisi yazılmaz** (E02 K-11, KVKK m.6 özel nitelikli veri): tür
# listesinde "sağlık raporu" yoktur (IZIN altında); not ≤200 karakterdir ve
# sağlık çağrıştıran sözcük içeren not 400 ile reddedilir. Not yalnız
# planlayıcıya ve kişinin kendisine görünür.
#
# **Aynı kilit:** blok yazımı/silimi, plan yazımının aldığı gün kilitlerini
# (`cakisma.gun_kilitleri`) aynı sırayla alır. Böylece "plan kaydı çakışma
# yok gördü" ile "aynı ana blok girildi" yarışamaz; ikinci istek birincinin
# commit'ini bekler ve onu görür.

MUSAITLIK_NOT_AZAMI = 200
MUSAITLIK_AZAMI_GUN = 62
# Küçük harf + Türkçe katlama sonrası alt dize araması. Kesin bir sözlük
# değil, uyarı amaçlı süzgeçtir: amaç kazara yazılan teşhisi kaydetmemektir.
_SAGLIK_SOZCUKLERI = (
    "hasta",
    "hastane",
    "ameliyat",
    "doktor",
    "teşhis",
    "teshis",
    "tedavi",
    "ilaç",
    "ilac",
    "sağlık raporu",
    "saglik raporu",
    "raporlu",
    "hamile",
    "gebelik",
    "psikiyatri",
    "psikolog",
    "kanser",
    "covid",
    "grip",
    "fizik tedavi",
)
SAGLIK_UYARISI = (
    "Müsaitlik notuna sağlık bilgisi (hastalık, teşhis, rapor nedeni) yazılmaz; "
    "'İzin' türünü seçip notu boş bırakın."
)


def _katla(metin: str) -> str:
    return metin.replace("I", "ı").replace("İ", "i").lower()


def saglik_bilgisi_var_mi(not_: str | None) -> bool:
    """Not sağlık çağrıştıran bir sözcük içeriyor mu? (KVKK m.6 koruması)"""
    if not not_:
        return False
    metin = _katla(not_)
    return any(s in metin for s in _SAGLIK_SOZCUKLERI)


def musaitlik_notu_dogrula(not_: str | None) -> str | None:
    """Not ≤200 ve sağlık bilgisi içermez; boşluk → None."""
    temiz = (not_ or "").strip() or None
    if temiz is None:
        return None
    if len(temiz) > MUSAITLIK_NOT_AZAMI:
        raise PlanlamaGirdiHatasi(f"Not en çok {MUSAITLIK_NOT_AZAMI} karakter olabilir")
    if saglik_bilgisi_var_mi(temiz):
        raise PlanlamaGirdiHatasi(SAGLIK_UYARISI)
    return temiz


def _farkinda(an: datetime) -> None:
    if an.tzinfo is None or an.tzinfo.utcoffset(an) is None:
        raise PlanlamaGirdiHatasi("Saat dilimi bilgisi olmayan zaman kabul edilmez")


async def _blok_gun_kilitleri(db: AsyncSession, bas: datetime, bit: datetime) -> None:
    from app.services.teknik_servis.yerel_zaman import yerel_gun

    await cakisma.gun_kilitleri(db, cakisma.dokunulan_gunler(bas, bit, yerel_gun(bas)))


def _blok_denetim(blok: ServiceUnavailability) -> dict[str, Any]:
    return {
        "user_id": blok.user_id,
        "baslangic": blok.starts_at.isoformat(),
        "bitis": blok.ends_at.isoformat(),
        "tur": blok.tur,
        "not": blok.note,
    }


async def musaitlik_ekle(
    db: AsyncSession,
    *,
    kisi_id: int,
    baslangic: datetime,
    bitis: datetime,
    tur: str,
    not_: str | None,
    user: User,
    ip: str | None = None,
) -> tuple[ServiceUnavailability, list[cakisma.Cakisma]]:
    """Blok açar; kişinin kapsamı (404) API'de çözülmüştür.

    Dönüş: (blok, aynı aralıktaki planlar — bilgi: plan sahibine "bu kişinin
    planı var" uyarısı; blok yine yazılır, planlar çakışmalı bayrağı alır).
    """
    from app.models.servis_planlama import MUSAITLIK_TURLERI

    if tur not in MUSAITLIK_TURLERI:
        raise PlanlamaGirdiHatasi(f"Geçersiz müsaitlik türü: {tur}")
    _farkinda(baslangic)
    _farkinda(bitis)
    if bitis <= baslangic:
        raise PlanlamaGirdiHatasi("Bitiş, başlangıçtan sonra olmalı")
    if bitis - baslangic > timedelta(days=MUSAITLIK_AZAMI_GUN):
        raise PlanlamaGirdiHatasi(
            f"Bir blok en çok {MUSAITLIK_AZAMI_GUN} gün olabilir; daha uzununu parçalayın"
        )
    temiz_not = musaitlik_notu_dogrula(not_)
    await _blok_gun_kilitleri(db, baslangic, bitis)
    cakisan = await db.scalar(
        select(ServiceUnavailability)
        .where(
            ServiceUnavailability.user_id == kisi_id,
            ServiceUnavailability.is_deleted.is_(False),
            ServiceUnavailability.starts_at < bitis,
            ServiceUnavailability.ends_at > baslangic,
        )
        .limit(1)
    )
    if cakisan is not None:
        raise PlanlamaHatasi(
            "Bu kişinin aynı aralıkta başka bir müsaitlik bloğu var "
            f"({_yerel_metin(cakisan.starts_at)}–{_yerel_metin(cakisan.ends_at)})"
        )
    blok = ServiceUnavailability(
        user_id=kisi_id,
        starts_at=baslangic,
        ends_at=bitis,
        tur=tur,
        note=temiz_not,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(blok)
    await db.flush()
    await audit.log(
        db,
        "service_unavailability",
        "olustur",
        entity_id=blok.id,
        new_value=_blok_denetim(blok),
        user_id=user.id,
        ip=ip,
        is_personal_data=True,
    )
    planlar = [
        c
        for c in await cakisma.cakismalari_bul(db, [kisi_id], baslangic, bitis, goren=user)
        if c.tur != "MUSAITLIK"
    ]
    return blok, planlar


async def musaitlik_sil(
    db: AsyncSession,
    blok: ServiceUnavailability,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceUnavailability:
    """Yumuşak siler (EXCLUDE `WHERE NOT is_deleted`); çakışma uyarısı kalkar."""
    if blok.is_deleted:
        raise PlanlamaHatasi("Bu blok zaten silinmiş")
    await _blok_gun_kilitleri(db, blok.starts_at, blok.ends_at)
    eski = _blok_denetim(blok)
    blok.is_deleted = True
    blok.deleted_at = clock.now()
    blok.deleted_by = user.id
    blok.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        "service_unavailability",
        "sil",
        entity_id=blok.id,
        old_value=eski,
        user_id=user.id,
        ip=ip,
        is_personal_data=True,
    )
    return blok


async def musaitlik_listesi(
    db: AsyncSession,
    user: User,
    baslangic: date,
    bitis: date,
    *,
    birim: str | None = None,
    kisi_id: int | None = None,
) -> list[dict[str, Any]]:
    """Aralıkla örtüşen bloklar. Planlayıcı: kapsamındaki personel; diğerleri
    yalnız KENDİ blokları. Not yalnız planlayıcıya ve kişinin kendisine."""
    from app.models import User as Kullanici
    from app.models import UserUnit
    from app.services.teknik_servis.yerel_zaman import yerel_gun_araligi

    if bitis < baslangic:
        raise PlanlamaGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if (bitis - baslangic).days + 1 > MUSAITLIK_AZAMI_GUN:
        raise PlanlamaGirdiHatasi(f"Aralık en çok {MUSAITLIK_AZAMI_GUN} gün olabilir")
    alt, _ = yerel_gun_araligi(baslangic)
    _, ust = yerel_gun_araligi(bitis)
    stmt = (
        select(ServiceUnavailability, Kullanici.full_name)
        .join(Kullanici, Kullanici.id == ServiceUnavailability.user_id)
        .where(
            ServiceUnavailability.is_deleted.is_(False),
            ServiceUnavailability.starts_at < ust,
            ServiceUnavailability.ends_at > alt,
        )
        .order_by(ServiceUnavailability.starts_at, ServiceUnavailability.id)
    )
    planlayici = user.has("servis.planla")
    if planlayici:
        stmt = kapsam.kapsam_personel(stmt, user, ServiceUnavailability.user_id)
    else:
        stmt = stmt.where(ServiceUnavailability.user_id == user.id)
    if birim:
        stmt = stmt.where(
            ServiceUnavailability.user_id.in_(
                select(UserUnit.user_id).where(UserUnit.birim == birim)
            )
        )
    if kisi_id is not None:
        stmt = stmt.where(ServiceUnavailability.user_id == kisi_id)
    sonuc = []
    for blok, ad in (await db.execute(stmt)).all():
        sonuc.append(
            {
                "id": blok.id,
                "version": blok.version,
                "user_id": blok.user_id,
                "ad": ad,
                "baslangic": blok.starts_at.isoformat(),
                "bitis": blok.ends_at.isoformat(),
                "tur": blok.tur,
                "not": blok.note if (planlayici or blok.user_id == user.id) else None,
            }
        )
    return sonuc


def _yerel_metin(an: datetime) -> str:
    return an.astimezone(YEREL).strftime("%d.%m.%Y %H:%M")


# --- KVKK (E02-D05, TS-049) ---------------------------------------------------------


async def _plan_metinlerini_anonimlestir(db: AsyncSession, account_id: int, _clock: Clock) -> dict:
    """Hesap anonimleştirilirken o müşterinin plan ve ziyaret serbest metinleri silinir.

    Saha notu, bölge, plan notu, değişim/iptal notu ve çakışma gerekçesi
    kişi adı/telefonu taşıyabilir ("kapıda Ahmet Bey'i arayın"). Satırlar
    DURUR (plan geçmişi ve raporlar sayıyla çalışır); yalnız metin gider.
    """
    so_idler = select(ServiceOrder.id).where(ServiceOrder.customer_id == account_id)
    sonuc = await db.execute(
        update(ServicePlan)
        .where(ServicePlan.service_order_id.in_(so_idler))
        .values(
            site_area=None,
            site_note=None,
            plan_note=None,
            change_note=None,
            cancel_note=None,
            conflict_override_note=None,
            version=ServicePlan.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    ziyaret = await db.execute(
        update(ServiceVisit)
        .where(ServiceVisit.customer_id == account_id, ServiceVisit.notes.is_not(None))
        .values(notes=None, version=ServiceVisit.version + 1)
        .execution_options(synchronize_session=False)
    )
    return {"servis_plan_notu": sonuc.rowcount or 0, "servis_ziyaret_notu": ziyaret.rowcount or 0}


kvkk.anonimlestirme_kaydet(_plan_metinlerini_anonimlestir)
kancalar.kaydet("ekip_degisti", ekip_degisti)

__all__ = [
    "KAPALI",
    "PLANLANDIYA_GECER",
    "PlanGirdisi",
    "PlanlamaBulunamadi",
    "PlanlamaGirdiHatasi",
    "PlanlamaHatasi",
    "aktif_plan",
    "ekip_degisti",
    "irtibat_gorur",
    "musaitlik_ekle",
    "musaitlik_listesi",
    "musaitlik_notu_dogrula",
    "musaitlik_sil",
    "plan_gecmisi",
    "plan_uyeleri",
    "plani_geri_al",
    "planla",
    "saat_araligi",
    "saha_onerisi",
    "saglik_bilgisi_var_mi",
    "toplu_planla",
    "yeniden_planla",
]
