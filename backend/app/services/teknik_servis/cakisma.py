"""Plan çakışma motoru — tek kaynak (E02-15, E02-10, TS-045).

**Neden tek motor:** plan yazımı (`PUT /plan`, toplu plan, yeniden plan),
önizleme (`POST /kontrol`), takvim bayrakları, `cakismali` KPI'ı ve planlama
uyarısı aynı soruyu sorar: "bu kişi/araç bu aralıkta başka bir işte mi?".
Her biri kendi sorgusunu yazsaydı takvim bayrağı ile kayıt anındaki 409
ayrışırdı (bayrak yok ama kayıt reddediliyor ya da tersi).

Kurallar:

- **Birim kapsamını AŞAR, yanıt aşmaz** (E02 K-06): haberleşme işinde
  10:00–12:00'de olan kişi POC işinde 11:00'e yazılırsa çakışma yakalanır;
  ama çakışan iş kullanıcının kapsamı dışındaysa iş no ve müşteri dönmez
  (`maskeli=True`), yalnız tür, birim ve saat aralığı döner.
- Kişi kümesi yalnız `sahaya_gidiyor` üyelerdir: şef varsayılan olarak
  sorumludur, sahaya gitmez ve çakışmaya girmez (E02-10).
- Aynı ziyaretin işleri birbiriyle çakışmaz (birlikte gidilir).
- Saati belirsiz plan (`starts_at IS NULL`) çakışmaya girmez.
- Kapalı işlerin planı aday değildir (E02-23).
- Müsaitlik bloğu (`service_unavailability`) da çakışmadır (`MUSAITLIK`).
- 409 gövdesi `{detail, kod: 'PLAN_CAKISMA', cakismalar}`; `servis.planla`
  sahibi ≥10 karakter gerekçeyle geçer (E02 K-04).

**Eşzamanlılık:** iki şef aynı anda aynı kişiyi çakışan saate yazarsa ikisi
de "çakışma yok" görüp kaydedebilirdi. Yazmadan önce adayın değdiği her
İstanbul günü için transaction ölçekli advisory lock GÜN SIRALI alınır
(`gun_kilitleri`); ikinci istek birincinin commit'ini bekler, satırını görür
ve 409 alır. Süre 1440 dk'ya kadar çıktığından gece yarısını aşan plan iki
günü birden kilitler.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select, text

from app.models import (
    ServiceOrder,
    ServicePlan,
    ServicePlanMember,
    ServiceUnavailability,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.services.teknik_servis import kapsam
from app.services.teknik_servis.kancalar import ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_an, yerel_gun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User

CAKISMA_KODU = "PLAN_CAKISMA"
CAKISMA_TURLERI = ("KISI", "ARAC", "MUSAITLIK")
# Gerekçe en az bu kadar karakter: "ok", "." gibi geçiştirmeler kabul edilmez.
GEREKCE_ASGARI = 10
_KAPALI = tuple(sorted(DURUM_GRUPLARI["KAPALI"]))


@dataclass(frozen=True)
class Cakisma:
    """Tek çakışma. `maskeli` ise iş no / plan kimliği dönmez (kapsam dışı)."""

    tur: str  # KISI | ARAC | MUSAITLIK
    baslangic: datetime
    bitis: datetime
    user_id: int | None = None
    arac_id: int | None = None
    plan_id: int | None = None
    so_no: str | None = None
    birim: str | None = None
    maskeli: bool = False

    def sozluk(self) -> dict[str, Any]:
        d = asdict(self)
        d["baslangic"] = self.baslangic.isoformat()
        d["bitis"] = self.bitis.isoformat()
        d["saat_araligi"] = (
            f"{yerel_an(self.baslangic):%d.%m.%Y %H:%M}–{yerel_an(self.bitis):%H:%M}"
        )
        return d


class PlanCakismasi(ServisHatasi):
    """Çakışma → 409 + `cakismalar` listesi (gerekçeyle geçilebilir)."""

    def __init__(self, mesaj: str, cakismalar: Sequence[Cakisma]) -> None:
        super().__init__(mesaj)
        self.cakismalar = list(cakismalar)

    def govde(self) -> dict[str, Any]:
        return {
            "detail": str(self),
            "kod": CAKISMA_KODU,
            "cakismalar": [c.sozluk() for c in self.cakismalar],
        }


# --- Saf fonksiyonlar (DB'siz; unit testle sınanır) ----------------------------


def ortusur(a_bas: datetime, a_bit: datetime, b_bas: datetime, b_bit: datetime) -> bool:
    """Yarı açık aralıklar `[bas, bit)` örtüşüyor mu? Uç uca değmek çakışma değildir."""
    return a_bas < b_bit and b_bas < a_bit


@dataclass(frozen=True)
class Aday:
    """Takvim bayrağı için bellek içi plan özeti."""

    plan_id: int
    baslangic: datetime | None
    bitis: datetime | None
    visit_id: int | None
    sahadakiler: frozenset[int]
    arac_id: int | None


def ortusen_planlar(
    adaylar: Iterable[Aday], musaitlik: Iterable[tuple[int, datetime, datetime]] = ()
) -> set[int]:
    """Kişi, araç ya da müsaitlik bloğu yüzünden çakışan plan kimlikleri.

    Saati belirsiz plan aday değildir; aynı ziyaretteki iki plan birbirine
    çakışma vermez. `musaitlik`: `(user_id, bas, bit)` blokları.
    """
    zamanli = sorted(
        (a for a in adaylar if a.baslangic is not None and a.bitis is not None),
        key=lambda a: a.baslangic,
    )
    sonuc: set[int] = set()
    for i, a in enumerate(zamanli):
        for b in zamanli[i + 1 :]:
            if b.baslangic >= a.bitis:
                break  # sıralı: sonrakiler de başlamadan a bitmiş
            if a.visit_id is not None and a.visit_id == b.visit_id:
                continue
            ortak_kisi = a.sahadakiler & b.sahadakiler
            ortak_arac = a.arac_id is not None and a.arac_id == b.arac_id
            if (ortak_kisi or ortak_arac) and ortusur(a.baslangic, a.bitis, b.baslangic, b.bitis):
                sonuc.update((a.plan_id, b.plan_id))
    bloklar = list(musaitlik)
    for a in zamanli:
        for kisi, bas, bit in bloklar:
            if kisi in a.sahadakiler and ortusur(a.baslangic, a.bitis, bas, bit):
                sonuc.add(a.plan_id)
                break
    return sonuc


def dokunulan_gunler(
    baslangic: datetime | None, bitis: datetime | None, plan_gunu: date
) -> list[date]:
    """Advisory lock anahtar kümesi: aralığın değdiği bütün İstanbul günleri.

    Saati belirsiz plan yalnız kendi gününü kilitler. Bitiş anı yarı açık:
    tam gece yarısında biten plan ertesi günü kilitlemez.
    """
    if baslangic is None or bitis is None:
        return [plan_gunu]
    ilk = yerel_gun(baslangic)
    son = yerel_gun(bitis - timedelta(microseconds=1))
    gunler = {plan_gunu}
    gun = ilk
    while gun <= son:
        gunler.add(gun)
        gun += timedelta(days=1)
    return sorted(gunler)


# --- Veritabanı ------------------------------------------------------------------


async def gun_kilitleri(db: AsyncSession, gunler: Iterable[date]) -> None:
    """Günleri SIRALI kilitler (deadlock önlemi); transaction bitince düşer."""
    for gun in sorted(set(gunler)):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:anahtar, 0))"),
            {"anahtar": f"servis_plan:{gun.isoformat()}"},
        )


async def _maskeli_mi(db: AsyncSession, goren: User, so: ServiceOrder) -> bool:
    return await kapsam.is_erisimi_yok_mu(db, goren, so)


async def cakismalari_bul(
    db: AsyncSession,
    user_idler: Sequence[int],
    baslangic: datetime | None,
    bitis: datetime | None,
    *,
    goren: User,
    arac_id: int | None = None,
    haric_plan_idler: Sequence[int] = (),
    haric_so_idler: Sequence[int] = (),
    visit_id: int | None = None,
) -> list[Cakisma]:
    """Aralıkta sahadaki kişilerle / araçla çakışan aktif planlar + müsaitlik.

    - `haric_plan_idler`: yeniden planlanan işlerin kendi (eski) planları.
    - `haric_so_idler`: aynı istekte birlikte planlanan işler (aynı ziyaret).
    - `visit_id`: aynı ziyaretin diğer planları çakışma sayılmaz.
    Saat belirsizse (`baslangic is None`) boş liste döner.
    """
    if baslangic is None or bitis is None:
        return []
    kisiler = sorted(set(user_idler))
    if not kisiler and arac_id is None:
        return []

    kaynak_kosullari = []
    if kisiler:
        kaynak_kosullari.append(
            ServicePlan.id.in_(
                select(ServicePlanMember.plan_id).where(
                    ServicePlanMember.user_id.in_(kisiler),
                    ServicePlanMember.sahaya_gidiyor.is_(True),
                )
            )
        )
    if arac_id is not None:
        kaynak_kosullari.append(ServicePlan.vehicle_id == arac_id)

    stmt = (
        select(ServicePlan, ServiceOrder)
        .join(ServiceOrder, ServiceOrder.id == ServicePlan.service_order_id)
        .where(
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
            ServicePlan.starts_at.is_not(None),
            ServicePlan.starts_at < bitis,
            ServicePlan.ends_at > baslangic,
            ServiceOrder.status.not_in(_KAPALI),
            or_(*kaynak_kosullari),
        )
        .order_by(ServicePlan.starts_at, ServicePlan.id)
    )
    if haric_plan_idler:
        stmt = stmt.where(ServicePlan.id.not_in(list(haric_plan_idler)))
    if haric_so_idler:
        stmt = stmt.where(ServicePlan.service_order_id.not_in(list(haric_so_idler)))
    if visit_id is not None:
        stmt = stmt.where(or_(ServicePlan.visit_id.is_(None), ServicePlan.visit_id != visit_id))

    satirlar = (await db.execute(stmt)).all()
    plan_idler = [p.id for p, _ in satirlar]
    uyeler: dict[int, set[int]] = {}
    if plan_idler and kisiler:
        for plan_id, uid in (
            await db.execute(
                select(ServicePlanMember.plan_id, ServicePlanMember.user_id).where(
                    ServicePlanMember.plan_id.in_(plan_idler),
                    ServicePlanMember.user_id.in_(kisiler),
                    ServicePlanMember.sahaya_gidiyor.is_(True),
                )
            )
        ).all():
            uyeler.setdefault(plan_id, set()).add(uid)

    sonuc: list[Cakisma] = []
    maske_onbellek: dict[int, bool] = {}
    for plan, so in satirlar:
        if so.id not in maske_onbellek:
            maske_onbellek[so.id] = await _maskeli_mi(db, goren, so)
        maskeli = maske_onbellek[so.id]
        ortak = dict(
            baslangic=plan.starts_at,
            bitis=plan.ends_at,
            plan_id=None if maskeli else plan.id,
            so_no=None if maskeli else so.so_no,
            birim=so.birim,
            maskeli=maskeli,
        )
        for uid in sorted(uyeler.get(plan.id, ())):
            sonuc.append(Cakisma(tur="KISI", user_id=uid, **ortak))
        if arac_id is not None and plan.vehicle_id == arac_id:
            sonuc.append(Cakisma(tur="ARAC", arac_id=arac_id, **ortak))

    if kisiler:
        bloklar = (
            await db.scalars(
                select(ServiceUnavailability)
                .where(
                    ServiceUnavailability.user_id.in_(kisiler),
                    ServiceUnavailability.is_deleted.is_(False),
                    ServiceUnavailability.starts_at < bitis,
                    ServiceUnavailability.ends_at > baslangic,
                )
                .order_by(ServiceUnavailability.starts_at, ServiceUnavailability.id)
            )
        ).all()
        for b in bloklar:
            # Bloğun türü/notu dönmez: izin nedeni kişisel veridir.
            sonuc.append(
                Cakisma(tur="MUSAITLIK", user_id=b.user_id, baslangic=b.starts_at, bitis=b.ends_at)
            )
    return sonuc


async def aralik_bayraklari(db: AsyncSession, baslangic: datetime, bitis: datetime) -> set[int]:
    """Aralıktaki BÜTÜN birimlerin aktif planları arasında çakışan plan kimlikleri.

    Takvim bayrağı, `cakismali` KPI'ı ve uyarı bunu kullanır; birim süzgecinden
    bağımsızdır (bayrak, ekranda görünmeyen başka birimin işi yüzünden de
    yanar — E02-15 kabulü).
    """
    planlar = (
        await db.execute(
            select(
                ServicePlan.id,
                ServicePlan.starts_at,
                ServicePlan.ends_at,
                ServicePlan.visit_id,
                ServicePlan.vehicle_id,
            )
            .join(ServiceOrder, ServiceOrder.id == ServicePlan.service_order_id)
            .where(
                ServicePlan.is_active.is_(True),
                ServicePlan.is_deleted.is_(False),
                ServicePlan.starts_at.is_not(None),
                ServicePlan.starts_at < bitis,
                ServicePlan.ends_at > baslangic,
                ServiceOrder.status.not_in(_KAPALI),
            )
        )
    ).all()
    if not planlar:
        return set()
    idler = [p.id for p in planlar]
    sahadakiler: dict[int, set[int]] = {}
    for plan_id, uid in (
        await db.execute(
            select(ServicePlanMember.plan_id, ServicePlanMember.user_id).where(
                ServicePlanMember.plan_id.in_(idler), ServicePlanMember.sahaya_gidiyor.is_(True)
            )
        )
    ).all():
        sahadakiler.setdefault(plan_id, set()).add(uid)
    adaylar = [
        Aday(
            plan_id=p.id,
            baslangic=p.starts_at,
            bitis=p.ends_at,
            visit_id=p.visit_id,
            sahadakiler=frozenset(sahadakiler.get(p.id, ())),
            arac_id=p.vehicle_id,
        )
        for p in planlar
    ]
    kisiler = sorted({u for s in sahadakiler.values() for u in s})
    bloklar: list[tuple[int, datetime, datetime]] = []
    if kisiler:
        bloklar = [
            (b.user_id, b.starts_at, b.ends_at)
            for b in (
                await db.execute(
                    select(
                        ServiceUnavailability.user_id,
                        ServiceUnavailability.starts_at,
                        ServiceUnavailability.ends_at,
                    ).where(
                        ServiceUnavailability.user_id.in_(kisiler),
                        ServiceUnavailability.is_deleted.is_(False),
                        and_(
                            ServiceUnavailability.starts_at < bitis,
                            ServiceUnavailability.ends_at > baslangic,
                        ),
                    )
                )
            ).all()
        ]
    return ortusen_planlar(adaylar, bloklar)


def gerekce_gecerli_mi(gerekce: str | None) -> bool:
    return bool(gerekce) and len(gerekce.strip()) >= GEREKCE_ASGARI


__all__ = [
    "CAKISMA_KODU",
    "Aday",
    "Cakisma",
    "PlanCakismasi",
    "aralik_bayraklari",
    "cakismalari_bul",
    "dokunulan_gunler",
    "gerekce_gecerli_mi",
    "gun_kilitleri",
    "ortusen_planlar",
    "ortusur",
]
