"""Planlama takvimi, plansız havuz, planlama KPI'ları, Excel ve uyarıları (E02-05/06/19/24/25,
TS-042/049).

- **Tarih aralıklı yükleme:** takvim en çok 62 gün (kod sabiti; ay görünümü +
  komşu haftalar sığar). Daha uzun aralık 400 — tüm planları tek seferde
  çekmek 10.000 işte ekranı kilitlerdi.
- **Kapsam:** her liste, sayı, Excel ve uyarı `kapsam.kapsam_isler` ile
  süzülür (KENDI_BIRIMI → birim, KENDI_ISLERI → aktif atama/plan üyeliği);
  sayı da bir sızıntıdır.
- **Sayı = liste (E02-06):** her KPI tek bir sorgu üreticisinden gelir;
  kutudaki sayı ile `/kpi-liste?kod=` `X-Toplam-Kayit` aynı sorgunun
  `count()`'udur.
- **Havuz gruplaması** yalnız sunucuda: `ana_veri.lokasyon_anahtari`
  (lokasyon) ya da normalize il/ilçe (şehir). İstemci kendi
  normalizasyonunu yazmaz (E02 K-05).
- **Çakışma bayrağı** birim süzgecinden bağımsız hesaplanır (cakisma.py).
- **İrtibat gizliliği (E02-24):** irtibat adı/telefonu ve açık adres
  `servis.irtibat_gor` ya da işin ekibinde olmayan kullanıcıya **null** döner;
  il/ilçe görünür kalır (havuz gruplaması için).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, func, or_, select

from app.models import (
    Account,
    Address,
    Contact,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderSerial,
    ServicePlan,
    ServicePlanMember,
    ServiceVehicle,
    ServiceVisit,
    User,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.services import settings as ayar_svc
from app.services.normalize import normalize_seri, tr_normkey, unvan_anahtari
from app.services.teknik_servis import ana_veri, cakisma, kapsam
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi
from app.services.teknik_servis.yerel_zaman import YEREL, yerel_bugun, yerel_gun_araligi
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

TAKVIM_AZAMI_GUN = 62
KAPALI = tuple(sorted(DURUM_GRUPLARI["KAPALI"]))
COZULDU = tuple(sorted(DURUM_GRUPLARI["COZULDU"]))
# Ekran sekmeleri: Servis (PB dışı) / Bakım (PB) / Tümü.
TURLER = ("SERVIS", "BAKIM")
GRUPLAMALAR = ("lokasyon", "sehir")
SEHIR_YOK = "Şehir girilmemiş"
PLAN_BEKLEYEN_ANAHTARI = "servis_plan_bekleyen_uyari_gun"

# KPI kaydı: kod → (başlık, tanım). Sıra ekrandaki sıradır.
KPI_TANIMLARI: dict[str, tuple[str, str]] = {
    "bugun_planli": ("Bugün planlı", "Seçili günde aktif planı olan açık işler"),
    "hafta_planli": ("Bu hafta planlı", "Seçili günün haftasında (Pzt–Paz) planlı açık işler"),
    "havuz": ("Plansız havuz", "Aktif planı olmayan açık işler"),
    "cakismali": (
        "Çakışmalı plan",
        "Haftada sahadaki kişi/araç ya da müsaitlik bloğu yüzünden çakışan planlar",
    ),
    "saat_belirsiz": ("Saati belirsiz", "Haftada başlangıç saati girilmemiş planlar"),
    "bugun_tamamlanan": (
        "Bugün planlı, tamamlanan",
        "Seçili günde planı olan ve tamamlanmış/kapatılmış işler",
    ),
}


class TakvimGirdiHatasi(ServisGirdiHatasi):
    """Takvim/havuz girdi hatası → 400."""


class TakvimKapsamDisi(LookupError):
    """Kullanıcının kapsamı dışındaki birim parametresi → 404."""


# --- Ortak süzgeçler ---------------------------------------------------------------


def aralik_dogrula(baslangic: date, bitis: date) -> None:
    if bitis < baslangic:
        raise TakvimGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if (bitis - baslangic).days + 1 > TAKVIM_AZAMI_GUN:
        raise TakvimGirdiHatasi(f"Takvim aralığı en çok {TAKVIM_AZAMI_GUN} gün olabilir")


def _tur_dogrula(tur: str | None) -> str | None:
    if tur in (None, "", "TUMU"):
        return None
    if tur not in TURLER:
        raise TakvimGirdiHatasi(f"Geçersiz tür: {tur} (SERVIS, BAKIM ya da TUMU)")
    return tur


def _suz(stmt: Select, user: User, *, birim: str | None, tur: str | None) -> Select:
    """Kapsam + birim + tür süzgeci (bütün liste/sayı sorguları bunu kullanır)."""
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    if birim:
        stmt = stmt.where(ServiceOrder.birim == birim)
    tur = _tur_dogrula(tur)
    if tur == "BAKIM":
        stmt = stmt.where(ServiceOrder.tur == "PB")
    elif tur == "SERVIS":
        stmt = stmt.where(ServiceOrder.tur != "PB")
    return stmt


def plan_sorgusu(user: User, *, birim: str | None = None, tur: str | None = None) -> Select:
    """Aktif plan + iş satırları (kapsamlı)."""
    stmt = (
        select(ServicePlan, ServiceOrder)
        .join(ServiceOrder, ServiceOrder.id == ServicePlan.service_order_id)
        .where(
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
            ServiceOrder.is_deleted.is_(False),
        )
    )
    return _suz(stmt, user, birim=birim, tur=tur)


def _hafta(gun: date) -> tuple[date, date]:
    pazartesi = gun - timedelta(days=gun.weekday())
    return pazartesi, pazartesi + timedelta(days=6)


def _gunler_utc(bas: date, bit: date) -> tuple[datetime, datetime]:
    return yerel_gun_araligi(bas)[0], yerel_gun_araligi(bit)[1]


# --- Satır üretimi -------------------------------------------------------------------


async def _plan_satirlari(
    db: AsyncSession, user: User, satirlar: list[tuple[ServicePlan, ServiceOrder]]
) -> list[dict[str, Any]]:
    if not satirlar:
        return []
    planlar = [p for p, _ in satirlar]
    isler = [so for _, so in satirlar]
    plan_idler = [p.id for p in planlar]
    so_idler = [so.id for so in isler]

    uyeler: dict[int, list[dict[str, Any]]] = {}
    for uye, ad in (
        await db.execute(
            select(ServicePlanMember, User.full_name)
            .join(User, User.id == ServicePlanMember.user_id)
            .where(ServicePlanMember.plan_id.in_(plan_idler))
            .order_by(ServicePlanMember.plan_id, ServicePlanMember.rol, User.full_name)
        )
    ).all():
        uyeler.setdefault(uye.plan_id, []).append(
            {"user_id": uye.user_id, "ad": ad, "rol": uye.rol, "sahaya_gidiyor": uye.sahaya_gidiyor}
        )

    ziyaretler = dict(
        (
            await db.execute(
                select(ServiceVisit.id, ServiceVisit.visit_no).where(
                    ServiceVisit.id.in_({p.visit_id for p in planlar if p.visit_id})
                )
            )
        ).all()
    )
    araclar = dict(
        (
            await db.execute(
                select(ServiceVehicle.id, ServiceVehicle.plate).where(
                    ServiceVehicle.id.in_({p.vehicle_id for p in planlar if p.vehicle_id})
                )
            )
        ).all()
    )
    erteleme = dict(
        (
            await db.execute(
                select(ServicePlan.service_order_id, func.count())
                .where(
                    ServicePlan.service_order_id.in_(so_idler),
                    ServicePlan.change_type.in_(("ERTELEME", "YENIDEN_PLAN")),
                    ServicePlan.is_deleted.is_(False),
                )
                .group_by(ServicePlan.service_order_id)
            )
        ).all()
    )

    gunler = [p.plan_date for p in planlar]
    bas, bit = _gunler_utc(min(gunler), max(gunler))
    # Gece yarısını aşan planlar komşu günle de çakışabilir: pencere bir gün geniş.
    bayraklar = await cakisma.aralik_bayraklari(
        db, bas - timedelta(days=1), bit + timedelta(days=1)
    )

    satir_detay = await _is_detaylari(db, user, isler)
    sonuc = []
    for plan, so in satirlar:
        d = satir_detay[so.id]
        sonuc.append(
            {
                "plan_id": plan.id,
                **d,
                "plan_tarihi": plan.plan_date.isoformat(),
                "baslangic_saati": plan.start_time.strftime("%H:%M") if plan.start_time else None,
                "sure_dk": plan.duration_min,
                "starts_at": plan.starts_at.isoformat() if plan.starts_at else None,
                "ends_at": plan.ends_at.isoformat() if plan.ends_at else None,
                "ziyaret_id": plan.visit_id,
                "ziyaret_no": ziyaretler.get(plan.visit_id),
                "kart_anahtari": f"Z{plan.visit_id}" if plan.visit_id else f"I{so.id}",
                "arac_id": plan.vehicle_id,
                "arac_plaka": araclar.get(plan.vehicle_id),
                "ekip": uyeler.get(plan.id, []),
                "saha_bolgesi": plan.site_area,
                "saha_notu": plan.site_note,
                "plan_notu": plan.plan_note,
                "degisim": plan.change_type,
                "cakisma": plan.id in bayraklar,
                "cakisma_gecildi": plan.conflict_override_note is not None,
                "erteleme_sayisi": erteleme.get(so.id, 0),
            }
        )
    return sonuc


async def _irtibat_gorulen_isler(db: AsyncSession, user: User, so_idler: list[int]) -> set[int]:
    """İrtibatı görebileceği işler: izin ya da işin ekibinde olmak (E02-24)."""
    if user.has("servis.irtibat_gor"):
        return set(so_idler)
    atanan = set(
        await db.scalars(
            select(ServiceOrderAssignment.service_order_id).where(
                ServiceOrderAssignment.service_order_id.in_(so_idler),
                ServiceOrderAssignment.user_id == user.id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    )
    planli = set(
        await db.scalars(
            select(ServicePlan.service_order_id)
            .join(ServicePlanMember, ServicePlanMember.plan_id == ServicePlan.id)
            .where(
                ServicePlan.service_order_id.in_(so_idler),
                ServicePlan.is_active.is_(True),
                ServicePlanMember.user_id == user.id,
            )
        )
    )
    return atanan | planli


async def _is_detaylari(
    db: AsyncSession, user: User, isler: list[ServiceOrder]
) -> dict[int, dict[str, Any]]:
    """İş + müşteri + lokasyon + (izinliyse) irtibat alanları."""
    so_idler = [so.id for so in isler]
    musteriler = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(
                    Account.id.in_({so.customer_id for so in isler if so.customer_id})
                )
            )
        ).all()
    )
    adresler = {
        a.id: a
        for a in (
            await db.scalars(
                select(Address).where(
                    Address.id.in_({so.address_id for so in isler if so.address_id})
                )
            )
        ).all()
    }
    kisiler = {
        k.id: k
        for k in (
            await db.scalars(
                select(Contact).where(
                    Contact.id.in_({so.contact_id for so in isler if so.contact_id})
                )
            )
        ).all()
    }
    gorulen = await _irtibat_gorulen_isler(db, user, so_idler)
    sonuc: dict[int, dict[str, Any]] = {}
    for so in isler:
        adres = adresler.get(so.address_id) if so.address_id else None
        kisi = kisiler.get(so.contact_id) if so.contact_id else None
        # İrtibat aynı müşteriye ait değilse gösterilmez (yanlış kişiyi aratmasın).
        if kisi is not None and kisi.account_id != so.customer_id:
            kisi = None
        gorur = so.id in gorulen
        sonuc[so.id] = {
            "is_id": so.id,
            "so_no": so.so_no,
            "birim": so.birim,
            "tur": so.tur,
            "kategori": so.kategori,
            "oncelik": so.oncelik,
            "durum": so.status,
            "kapali": so.status in KAPALI,
            "konu": so.konu,
            "musteri_id": so.customer_id,
            "musteri": musteriler.get(so.customer_id) or so.customer_name_raw,
            "lokasyon_id": so.address_id,
            "lokasyon": (adres.site_name or adres.label) if adres else so.location_raw,
            "il": adres.city if adres else None,
            "ilce": adres.district if adres else None,
            "acik_adres": (adres.line if adres else None) if gorur else None,
            "irtibat_adi": ((kisi.full_name if kisi else so.iletisim_ad) if gorur else None),
            "irtibat_telefon": ((kisi.phone if kisi else so.iletisim_telefon) if gorur else None),
        }
    return sonuc


# --- Takvim -----------------------------------------------------------------------


def takvim_sorgusu(
    user: User, baslangic: date, bitis: date, *, birim: str | None = None, tur: str | None = None
) -> Select:
    aralik_dogrula(baslangic, bitis)
    return (
        plan_sorgusu(user, birim=birim, tur=tur)
        .where(ServicePlan.plan_date >= baslangic, ServicePlan.plan_date <= bitis)
        .order_by(
            ServicePlan.plan_date,
            ServicePlan.start_time.is_(None),
            ServicePlan.start_time,
            ServicePlan.visit_id,
            ServicePlan.id,
        )
    )


async def takvim(
    db: AsyncSession,
    user: User,
    clock: Clock,
    baslangic: date,
    bitis: date,
    *,
    birim: str | None = None,
    tur: str | None = None,
) -> list[dict[str, Any]]:
    """Aralıktaki aktif plan satırları. Kapalı işlerin planı SÜZÜLMEZ, `kapali`
    bayrağıyla döner (takvimde soluk, salt okunur — E02-23)."""
    satirlar = (
        await db.execute(takvim_sorgusu(user, baslangic, bitis, birim=birim, tur=tur))
    ).all()
    return await _plan_satirlari(db, user, [(p, so) for p, so in satirlar])


# --- Havuz --------------------------------------------------------------------------


def havuz_sorgusu(
    user: User,
    *,
    birim: str | None = None,
    tur: str | None = None,
    q: str | None = None,
    gruplama: str = "lokasyon",
) -> Select:
    """Aktif planı olmayan açık işler (kapsamlı)."""
    if gruplama not in GRUPLAMALAR:
        raise TakvimGirdiHatasi(f"Geçersiz gruplama: {gruplama} (lokasyon ya da sehir)")
    aktif = select(ServicePlan.service_order_id).where(
        ServicePlan.is_active.is_(True), ServicePlan.is_deleted.is_(False)
    )
    stmt = (
        select(ServiceOrder)
        .outerjoin(Account, Account.id == ServiceOrder.customer_id)
        .outerjoin(Address, Address.id == ServiceOrder.address_id)
        .where(
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.status.not_in(KAPALI),
            ServiceOrder.id.not_in(aktif),
        )
    )
    stmt = _suz(stmt, user, birim=birim, tur=tur)
    arama = (q or "").strip()
    if arama:
        kosullar = [ServiceOrder.so_no.ilike(f"%{arama}%")]
        if anahtar := tr_normkey(arama):
            kosullar.append(Account.title_key.contains(anahtar, autoescape=True))
        if tesis := unvan_anahtari(arama):
            kosullar.append(Address.site_key.contains(tesis, autoescape=True))
        if seri := normalize_seri(arama):
            kosullar.append(
                ServiceOrder.id.in_(
                    select(ServiceOrderSerial.service_order_id).where(
                        ServiceOrderSerial.is_active.is_(True),
                        ServiceOrderSerial.seri_norm.contains(seri, autoescape=True),
                    )
                )
            )
        stmt = stmt.where(or_(*kosullar))
    if gruplama == "sehir":
        return stmt.order_by(
            Address.city.is_(None), Address.city, Address.district, ServiceOrder.id
        )
    return stmt.order_by(Account.title, ServiceOrder.address_id, ServiceOrder.id)


def _grup(so: ServiceOrder, d: dict[str, Any], gruplama: str) -> tuple[str, str]:
    if gruplama == "sehir":
        il, ilce = d.get("il"), d.get("ilce")
        if not il:
            return "SEHIR_YOK", SEHIR_YOK
        return f"{tr_normkey(il)}|{tr_normkey(ilce)}", f"{il}{' / ' + ilce if ilce else ''}"
    anahtar = ana_veri.lokasyon_anahtari(so)
    etiket = " / ".join(x for x in (d.get("musteri"), d.get("lokasyon")) if x) or so.so_no
    if anahtar is None:
        return f"IS|{so.id}", etiket
    return "|".join(str(x) for x in anahtar), etiket


async def havuz_satirlari(
    db: AsyncSession, user: User, clock: Clock, isler: list[ServiceOrder], gruplama: str
) -> list[dict[str, Any]]:
    detay = await _is_detaylari(db, user, isler)
    bugun = yerel_bugun(clock)
    sonuc = []
    for so in isler:
        d = detay[so.id]
        anahtar, etiket = _grup(so, d, gruplama)
        sonuc.append(
            {
                **d,
                "acilis": so.created_at.isoformat() if so.created_at else None,
                "yas_gun": (bugun - so.created_at.astimezone(YEREL).date()).days
                if so.created_at
                else None,
                "grup_anahtari": anahtar,
                "grup_etiketi": etiket,
            }
        )
    return sonuc


async def _sayfa(db: AsyncSession, stmt: Select, limit: int, offset: int):
    toplam = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    satirlar = (await db.execute(stmt.limit(limit).offset(offset))).all()
    return int(toplam or 0), satirlar


async def havuz(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    gruplama: str = "lokasyon",
    birim: str | None = None,
    tur: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """(toplam, sayfa satırları); grup anahtarı sunucuda üretilir."""
    stmt = havuz_sorgusu(user, birim=birim, tur=tur, q=q, gruplama=gruplama)
    toplam, satirlar = await _sayfa(db, stmt, limit, offset)
    return toplam, await havuz_satirlari(db, user, clock, [r[0] for r in satirlar], gruplama)


# --- KPI (sayı = liste) --------------------------------------------------------------


async def kpi_sorgusu(
    db: AsyncSession,
    user: User,
    kod: str,
    gun: date,
    *,
    birim: str | None = None,
    tur: str | None = None,
) -> Select:
    """KPI kodunun TEK sorgusu; sayı ve liste buradan türer."""
    if kod not in KPI_TANIMLARI:
        raise TakvimGirdiHatasi(f"Bilinmeyen KPI: {kod}")
    if kod == "havuz":
        return havuz_sorgusu(user, birim=birim, tur=tur)
    pzt, paz = _hafta(gun)
    stmt = plan_sorgusu(user, birim=birim, tur=tur)
    acik = ServiceOrder.status.not_in(KAPALI)
    hafta = and_(ServicePlan.plan_date >= pzt, ServicePlan.plan_date <= paz)
    if kod == "bugun_planli":
        stmt = stmt.where(ServicePlan.plan_date == gun, acik)
    elif kod == "hafta_planli":
        stmt = stmt.where(hafta, acik)
    elif kod == "saat_belirsiz":
        stmt = stmt.where(hafta, acik, ServicePlan.start_time.is_(None))
    elif kod == "bugun_tamamlanan":
        stmt = stmt.where(ServicePlan.plan_date == gun, ServiceOrder.status.in_(COZULDU))
    elif kod == "cakismali":
        bas, bit = _gunler_utc(pzt, paz)
        idler = await cakisma.aralik_bayraklari(db, bas, bit)
        stmt = stmt.where(hafta, acik, ServicePlan.id.in_(sorted(idler) or [-1]))
    return stmt.order_by(ServicePlan.plan_date, ServicePlan.start_time, ServicePlan.id)


async def planlama_kpi(
    db: AsyncSession,
    user: User,
    clock: Clock,
    gun: date,
    *,
    birim: str | None = None,
    tur: str | None = None,
) -> list[dict[str, Any]]:
    sonuc = []
    for kod, (baslik, tanim) in KPI_TANIMLARI.items():
        stmt = await kpi_sorgusu(db, user, kod, gun, birim=birim, tur=tur)
        adet = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        sonuc.append({"kod": kod, "baslik": baslik, "tanim": tanim, "deger": int(adet or 0)})
    return sonuc


async def kpi_listesi(
    db: AsyncSession,
    user: User,
    clock: Clock,
    kod: str,
    gun: date,
    *,
    birim: str | None = None,
    tur: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    stmt = await kpi_sorgusu(db, user, kod, gun, birim=birim, tur=tur)
    toplam, satirlar = await _sayfa(db, stmt, limit, offset)
    if kod == "havuz":
        return toplam, await havuz_satirlari(db, user, clock, [r[0] for r in satirlar], "lokasyon")
    return toplam, await _plan_satirlari(db, user, [(p, so) for p, so in satirlar])


# --- Excel (E02-19) ----------------------------------------------------------------

EXCEL_BASLIKLARI = [
    "İş No",
    "Birim",
    "Tür",
    "Müşteri",
    "Lokasyon",
    "İl",
    "İlçe",
    "Plan Tarihi",
    "Saat",
    "Planlanan süre (dk)",
    "Ziyaret No",
    "Şef",
    "Teknisyenler",
    "Araç",
    "Durum",
    "Çakışma",
    "Erteleme Sayısı",
]


def excel_satirlari(satirlar: list[dict[str, Any]], *, irtibatli: bool) -> tuple[list, list]:
    """Takvim satırlarından Excel; irtibat kolonları yalnız izinliye eklenir.

    Tarih METİN değil gerçek tarih hücresidir; süre "planlanan"dır, gerçek
    süre DEĞİLDİR (başlık bunu söyler).
    """
    basliklar = list(EXCEL_BASLIKLARI)
    if irtibatli:
        basliklar += ["Saha Yetkilisi", "Telefon"]
    tablo = []
    for s in satirlar:
        sefler = ", ".join(u["ad"] for u in s["ekip"] if u["rol"] == "SEF")
        teknisyenler = ", ".join(u["ad"] for u in s["ekip"] if u["rol"] == "TEKNISYEN")
        satir = [
            s["so_no"],
            s["birim"],
            "Bakım" if s["tur"] == "PB" else "Servis",
            s["musteri"],
            s["lokasyon"],
            s["il"],
            s["ilce"],
            date.fromisoformat(s["plan_tarihi"]),
            s["baslangic_saati"] or "Belirsiz",
            s["sure_dk"],
            s["ziyaret_no"],
            sefler,
            teknisyenler,
            s["arac_plaka"],
            s["durum"],
            "Evet" if s["cakisma"] else "",
            s["erteleme_sayisi"],
        ]
        if irtibatli:
            satir += [s["irtibat_adi"], s["irtibat_telefon"]]
        tablo.append(satir)
    return basliklar, tablo


# --- Uyarılar (E02-25, TS-049) -------------------------------------------------------


async def _say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def planlama_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Yarın planı, bekleyen yaşlı iş, çakışmalı plan, saati belirsiz plan.

    Her sayı kullanıcının kapsamıyla süzülür (birim + KENDI_ISLERI);
    sayı da bir sızıntıdır. Hesaplanır, saklanmaz.
    """
    bugun = yerel_bugun(clock)
    yarin = bugun + timedelta(days=1)
    yedi = bugun + timedelta(days=6)
    acik = ServiceOrder.status.not_in(KAPALI)
    uyarilar: list[Uyari] = []

    yarin_adet = await _say(db, plan_sorgusu(user).where(ServicePlan.plan_date == yarin, acik))
    uyarilar.append(
        Uyari(
            kod="servis.yarin_plan",
            baslik="Yarın planlı servis işi",
            adet=yarin_adet,
            yol=f"/servis-planlama?gun={yarin.isoformat()}",
            onem="bilgi",
        )
    )

    try:
        esik_gun = int(await ayar_svc.get(db, PLAN_BEKLEYEN_ANAHTARI) or 3)
    except KeyError:  # pragma: no cover - ayar kataloğu Dalga 0'da sabit
        esik_gun = 3
    esik = datetime.combine(bugun - timedelta(days=esik_gun), time.min, tzinfo=YEREL).astimezone(
        UTC
    )
    bekleyen = await _say(db, havuz_sorgusu(user).where(ServiceOrder.created_at < esik))
    uyarilar.append(
        Uyari(
            kod="servis.plan_bekleyen",
            baslik=f"{esik_gun} günden uzun süredir plan bekleyen iş",
            adet=bekleyen,
            yol="/servis-planlama?kpi=havuz",
            onem="uyari",
        )
    )

    hafta = and_(ServicePlan.plan_date >= bugun, ServicePlan.plan_date <= yedi)
    bas, bit = _gunler_utc(bugun, yedi)
    idler = await cakisma.aralik_bayraklari(db, bas, bit)
    cakisan = 0
    if idler:
        cakisan = await _say(
            db,
            plan_sorgusu(user).where(
                hafta,
                acik,
                ServicePlan.id.in_(sorted(idler)),
                ServicePlan.conflict_override_note.is_(None),
            ),
        )
    uyarilar.append(
        Uyari(
            kod="servis.plan_cakisma",
            baslik="Önümüzdeki 7 günde gerekçesiz çakışan plan",
            adet=cakisan,
            yol="/servis-planlama?kpi=cakismali",
            onem="uyari",
        )
    )
    belirsiz = await _say(
        db, plan_sorgusu(user).where(hafta, acik, ServicePlan.start_time.is_(None))
    )
    uyarilar.append(
        Uyari(
            kod="servis.saat_belirsiz",
            baslik="Önümüzdeki 7 günde saati belirsiz plan",
            adet=belirsiz,
            yol="/servis-planlama?kpi=saat_belirsiz",
            onem="bilgi",
        )
    )
    return uyarilar


ts_uyarilar.kaydet("planlama", "servis.gor", planlama_uyarilari)
