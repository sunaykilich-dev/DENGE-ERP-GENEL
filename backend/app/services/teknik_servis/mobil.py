"""Benim İşlerim: teknisyenin tek mobil ekranı ve "Bugünüm" özeti (E09-04/05, TS-077/078).

Tek uç (`GET /api/teknik-servis/benim-islerim`), tek sayfa; ayrı
"Ziyaretlerim" yok (E09-D01: E02-14 ve E10-16 bu sayfaya indirgendi). Gün
yerel (Europe/Istanbul) — 23:30 UTC'de planlı iş Türkiye'de ertesi gündür.
Çevrimdışı yok (K19): sunucu saati kullanıldığı için çevrimdışı basış
biriktirilmez.

**Kimin işi:** varsayılan görünüm kişinin AKTİF ATAMASI ya da aktif plan
üyeliği olan açık işlerdir (rol adına bakılmaz; şef de önce kendi işlerini
görür). "Tümü" yalnız `servis.planla` sahibine açılır ve yine
`kapsam_isler` ile süzülür.

**Ziyaret kartı:** aynı plan günü + `lokasyon_anahtari` (birim + tesis)
tek kartta toplanır; 17 PB'lik bakım ziyareti tek kart, her iş ayrı
seçilir. Anahtar `ana_veri.lokasyon_anahtari`'dan gelir, burada yeniden
yazılmaz (plan §1.5).

**Fiyat/maliyet alanı YOK** (kart ve liste); irtibat telefonu yalnız
`servis.irtibat_gor` ya da işe atanmış kişiye açık, diğerinde maskeli.

Dalga 2'de SLA bloğu D2-G tarafından eklenir (`sla` anahtarı).
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, exists, or_, select

from app.models import (
    Account,
    Address,
    Contact,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServicePlan,
    ServicePlanMember,
    ServiceTimeEntry,
)
from app.models.teknik_servis import DURUM_GRUPLARI, KISI_SAATE_DAHIL
from app.services import kvkk
from app.services import settings as ayarlar
from app.services.teknik_servis import ana_veri, kapsam, yerel_zaman, zaman

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

GRUPLAR = (
    ("GECIKEN", "Geciken"),
    ("BUGUN", "Bugün"),
    ("YARIN", "Yarın"),
    ("SONRA", "Sonraki günler"),
    ("PLANSIZ", "Plansız"),
)
GORUNUMLER = ("benim", "tumu")
# "Tümü" görünümünde bir ekranı boğmamak için üst sınır (liste uyarıyla kesilir).
TUMU_UST_SINIR = 500
BUGUNUM_GERI_GUN = 31


class MobilYetkiHatasi(PermissionError):
    """`tumu` görünümü `servis.planla` ister → 403."""


class MobilGirdiHatasi(ValueError):
    """Geçersiz gün / görünüm → 400."""


def _kendi_isleri_kosulu(user: User):
    atanan = select(ServiceOrderAssignment.service_order_id).where(
        ServiceOrderAssignment.user_id == user.id,
        ServiceOrderAssignment.removed_at.is_(None),
    )
    planli = (
        select(ServicePlan.service_order_id)
        .join(ServicePlanMember, ServicePlanMember.plan_id == ServicePlan.id)
        .where(
            ServicePlanMember.user_id == user.id,
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
        )
    )
    return ServiceOrder.id.in_(atanan.union(planli))


def _aktif_plan_join():
    return and_(
        ServicePlan.service_order_id == ServiceOrder.id,
        ServicePlan.is_active.is_(True),
        ServicePlan.is_deleted.is_(False),
    )


async def _aktif_atama_kumesi(db: AsyncSession, user: User, so_idler: list[int]) -> set[int]:
    if not so_idler:
        return set()
    return set(
        (
            await db.scalars(
                select(ServiceOrderAssignment.service_order_id).where(
                    ServiceOrderAssignment.user_id == user.id,
                    ServiceOrderAssignment.removed_at.is_(None),
                    ServiceOrderAssignment.service_order_id.in_(so_idler),
                )
            )
        ).all()
    )


def _bolum_ozeti(bolum: ServiceTimeEntry | None, so_no: str | None) -> dict[str, Any] | None:
    if bolum is None:
        return None
    return {
        "id": bolum.id,
        "version": bolum.version,
        "service_order_id": bolum.service_order_id,
        "so_no": so_no,
        "faaliyet": bolum.faaliyet,
        "bekleme_nedeni": bolum.bekleme_nedeni,
        "started_at": bolum.started_at,
    }


async def benim_sayacim(db: AsyncSession, user: User, clock: Clock) -> dict[str, Any]:
    """Hafif "benim sayacım" (bant ve kart): tek sorgu, süre özeti HESAPLANMAZ.

    `izinli_dugmeler` sunucuda hesaplanır ki istemci kuralı kopyalamasın.
    """
    an = clock.now()
    satir = (
        await db.execute(
            select(ServiceTimeEntry, ServiceOrder.so_no)
            .join(ServiceOrder, ServiceOrder.id == ServiceTimeEntry.service_order_id)
            .where(
                ServiceTimeEntry.user_id == user.id,
                ServiceTimeEntry.ended_at.is_(None),
                ServiceTimeEntry.is_deleted.is_(False),
            )
        )
    ).first()
    bolum, so_no = (satir[0], satir[1]) if satir else (None, None)
    return {
        "sunucu_zamani": an,
        "acik_bolum": _bolum_ozeti(bolum, so_no),
        **await dugme_bilgisi(db, bolum, an),
    }


async def dugme_bilgisi(
    db: AsyncSession, bolum: ServiceTimeEntry | None, an: datetime
) -> dict[str, Any]:
    """Açık bölüme göre hangi düğmelerin geçerli olduğu (E09 §4 akış tablosu)."""
    if bolum is None:
        return {
            "izinli_dugmeler": ["YOLA_CIKTIM", "SAHAYA_VARDIM", "DIGER"],
            "geri_alma_bitis": None,
            "uzun_sayac": False,
        }
    geri_dk = int(await ayarlar.get(db, "zaman_geri_alma_dk"))
    esik_saat = int(await ayarlar.get(db, "zaman_uzun_sayac_uyari_saat"))
    dugmeler: list[str] = []
    if bolum.faaliyet == "YOL":
        dugmeler.append("SAHAYA_VARDIM")
    if bolum.faaliyet in ("MOLA", "BEKLEME"):
        dugmeler.append("DEVAM")
    else:
        dugmeler += ["MOLA", "BEKLEME"]
    if bolum.faaliyet not in ("YOL", "MOLA"):
        dugmeler.append("SONRAKI_ISE_GEC")
    dugmeler += ["DEGISTIR", "BITIR", "UNUTTUM"]
    geri_bitis = bolum.started_at + timedelta(minutes=geri_dk)
    if an < geri_bitis:
        dugmeler.append("GERI_AL")
    return {
        "izinli_dugmeler": dugmeler,
        "geri_alma_bitis": geri_bitis if an < geri_bitis else None,
        "uzun_sayac": zaman.uzun_sayac_mi(bolum, an, esik_saat),
    }


def _grup(plan_gunu: date | None, bugun: date) -> str:
    if plan_gunu is None:
        return "PLANSIZ"
    if plan_gunu < bugun:
        return "GECIKEN"
    if plan_gunu == bugun:
        return "BUGUN"
    if plan_gunu == bugun + timedelta(days=1):
        return "YARIN"
    return "SONRA"


async def benim_islerim(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    gun: date | None = None,
    gorunum: str = "benim",
) -> dict[str, Any]:
    """Bugün/Yarın planlı işler, ziyaret kartları, aktif sayaç bandı, `sunucu_zamani`."""
    if gorunum not in GORUNUMLER:
        raise MobilGirdiHatasi(f"Geçersiz görünüm: {gorunum}")
    if gorunum == "tumu" and not user.has("servis.planla"):
        raise MobilYetkiHatasi("'Tümü' görünümü için yetkiniz yok (servis.planla)")
    bugun = gun or yerel_zaman.yerel_bugun(clock)

    stmt = (
        select(ServiceOrder, ServicePlan, Address, Account.title)
        .outerjoin(ServicePlan, _aktif_plan_join())
        .outerjoin(Address, Address.id == ServiceOrder.address_id)
        .outerjoin(Account, Account.id == ServiceOrder.customer_id)
        .where(
            ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
            ServiceOrder.is_deleted.is_(False),
        )
    )
    if gorunum == "benim":
        stmt = stmt.where(_kendi_isleri_kosulu(user))
    # "benim"de de kapsam uygulanır: birim üyeliği kaldırılmış kişi eski
    # biriminin işini atama sürse bile görmesin (KENDI_ISLERI zaten atamaya bakar).
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    stmt = stmt.order_by(
        ServicePlan.plan_date.asc().nulls_last(),
        ServicePlan.starts_at.asc().nulls_last(),
        ServiceOrder.so_no,
    ).limit(TUMU_UST_SINIR + 1)
    satirlar = (await db.execute(stmt)).all()
    kesildi = len(satirlar) > TUMU_UST_SINIR
    satirlar = satirlar[:TUMU_UST_SINIR]

    so_idler = [s[0].id for s in satirlar]
    ozetler = await zaman.sure_ozeti_toplu(db, so_idler)
    atanan = await _aktif_atama_kumesi(db, user, so_idler)

    gruplar: dict[str, OrderedDict[Any, dict[str, Any]]] = {k: OrderedDict() for k, _ in GRUPLAR}
    for so, plan, adres, musteri in satirlar:
        plan_gunu = plan.plan_date if plan is not None else None
        grup = _grup(plan_gunu, bugun)
        lok = ana_veri.lokasyon_anahtari(so)
        anahtar = (plan_gunu, lok) if lok is not None else (plan_gunu, ("IS", so.id))
        kart = gruplar[grup].get(anahtar)
        if kart is None:
            kart = {
                "anahtar": "|".join(str(p) for p in (plan_gunu, *(lok or ("IS", so.id)))),
                "plan_tarihi": plan_gunu,
                "musteri": musteri,
                "lokasyon": (adres.site_name or adres.label)
                if adres is not None
                else so.location_raw,
                "il": adres.city if adres is not None else None,
                "ilce": adres.district if adres is not None else None,
                "isler": [],
            }
            gruplar[grup][anahtar] = kart
        ozet = ozetler.get(so.id)
        kart["isler"].append(
            {
                "id": so.id,
                "so_no": so.so_no,
                "tur": so.tur,
                "birim": so.birim,
                "durum": so.status,
                "oncelik": so.oncelik,
                "konu": so.konu,
                "plan_baslangic": plan.starts_at if plan is not None else None,
                "plan_sure_dk": plan.duration_min if plan is not None else None,
                "bana_atanmis": so.id in atanan,
                "sayac_acilabilir": so.status in DURUM_GRUPLARI["SAYAC_ACILABILIR"],
                "kisi_saat_dk": ozet.kisi_saat_dk if ozet else None,
                "sure_durumu": ozet.sure_durumu if ozet else None,
            }
        )

    return {
        **await benim_sayacim(db, user, clock),
        "bugun": bugun,
        "gorunum": gorunum,
        "kesildi": kesildi,
        "gruplar": [
            {"kod": kod, "baslik": baslik, "ziyaretler": list(gruplar[kod].values())}
            for kod, baslik in GRUPLAR
        ],
    }


async def is_karti(db: AsyncSession, user: User, clock: Clock, so: ServiceOrder) -> dict[str, Any]:
    """Tek sayfa mobil iş kartı (erişim — 404 — API'de çözülmüştür).

    İçerik: adres, saha yetkilisi (maske kuralıyla), seri, plan notu, ulaşım
    notu, süre özeti, açık sayaç ve düğmeler. FİYAT/MALİYET ALANI YOKTUR.
    """
    adres = await db.get(Address, so.address_id) if so.address_id else None
    musteri = await db.scalar(select(Account.title).where(Account.id == so.customer_id))
    plan = await db.scalar(
        select(ServicePlan).where(
            ServicePlan.service_order_id == so.id,
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
        )
    )
    atanmis = bool(await _aktif_atama_kumesi(db, user, [so.id]))
    telefon_acik = atanmis or user.has("servis.irtibat_gor")

    irtibat_ad, irtibat_tel = so.iletisim_ad, so.iletisim_telefon
    if so.contact_id:
        kisi = await db.get(Contact, so.contact_id)
        if kisi is not None:
            irtibat_ad = irtibat_ad or kisi.full_name
            irtibat_tel = irtibat_tel or kisi.phone
    if not telefon_acik:
        irtibat_tel = kvkk.maskele(irtibat_tel)

    adres_metni = None
    if adres is not None:
        adres_metni = ", ".join(p for p in (adres.line, adres.district, adres.city) if p) or None
    sayac = await benim_sayacim(db, user, clock)
    ozet = await zaman.sure_ozeti(db, so.id)
    bu_isteki = sayac["acik_bolum"] and sayac["acik_bolum"]["service_order_id"] == so.id
    return {
        "sunucu_zamani": sayac["sunucu_zamani"],
        "id": so.id,
        "so_no": so.so_no,
        "tur": so.tur,
        "birim": so.birim,
        "durum": so.status,
        "oncelik": so.oncelik,
        "konu": so.konu,
        "aciklama": so.aciklama,
        "musteri": musteri,
        "lokasyon": (adres.site_name or adres.label) if adres is not None else so.location_raw,
        "adres": adres_metni,
        "il": adres.city if adres is not None else None,
        "ilce": adres.district if adres is not None else None,
        "ulasim_notu": adres.access_note if adres is not None else None,
        "irtibat_ad": irtibat_ad,
        "irtibat_telefon": irtibat_tel,
        "telefon_maskeli": not telefon_acik,
        "seriler": [s.seri_no for s in so.seriler if s.is_active],
        "equipment_id": so.equipment_id,
        "bakim_formu": so.tur == "PB",
        "plan": (
            {
                "plan_tarihi": plan.plan_date,
                "baslangic": plan.starts_at,
                "sure_dk": plan.duration_min,
                "plan_notu": plan.plan_note,
                "saha_alani": plan.site_area,
                "saha_notu": plan.site_note,
            }
            if plan is not None
            else None
        ),
        "bana_atanmis": atanmis,
        "sayac_acilabilir": so.status in DURUM_GRUPLARI["SAYAC_ACILABILIR"],
        "sure_ozeti": {
            "kisi_saat_dk": ozet.kisi_saat_dk,
            "sure_durumu": ozet.sure_durumu,
            "eksik_kisiler": list(ozet.eksik_kisiler),
            "mola_dk": ozet.mola_dk,
        },
        "acik_bolum": sayac["acik_bolum"],
        "acik_bolum_bu_iste": bool(bu_isteki),
        "izinli_dugmeler": sayac["izinli_dugmeler"],
        "geri_alma_bitis": sayac["geri_alma_bitis"],
        "uzun_sayac": sayac["uzun_sayac"],
    }


async def bugunum(
    db: AsyncSession, user: User, clock: Clock, *, gun: date | None = None
) -> dict[str, Any]:
    """Gün özeti ve gün sonu "süre kaydı eksik" listesi — YALNIZ kişinin kendisi.

    Eksik listesi: kişinin aktif ataması olan, o gün planlı ya da o gün kişinin
    durumunu değiştirdiği, süre BEKLENEN (`zaman.calisilmis_ifadesi`, aynı
    tanım) ve kişinin o gün kişi-saate dahil bölümü olmayan işler. "0 dk"
    yazılmaz — iş listede "Süre kaydı eksik" olarak durur.
    """
    bugun = yerel_zaman.yerel_bugun(clock)
    gun = gun or bugun
    if gun > bugun:
        raise MobilGirdiHatasi("İleri bir gün seçilemez")
    if gun < bugun - timedelta(days=BUGUNUM_GERI_GUN):
        raise MobilGirdiHatasi(f"En çok {BUGUNUM_GERI_GUN} gün geriye bakılabilir")
    bas, bit = yerel_zaman.yerel_gun_araligi(gun)

    bolumler = (
        await db.execute(
            select(ServiceTimeEntry, ServiceOrder.so_no)
            .join(ServiceOrder, ServiceOrder.id == ServiceTimeEntry.service_order_id)
            .where(
                ServiceTimeEntry.user_id == user.id,
                ServiceTimeEntry.started_at >= bas,
                ServiceTimeEntry.started_at < bit,
            )
            .order_by(ServiceTimeEntry.started_at)
        )
    ).all()

    kisi_saat_sn = 0.0
    kapali_var = False
    faaliyet_sn: dict[str, float] = {}
    mola_sn = 0.0
    mola_var = False
    satirlar = []
    for b, so_no in bolumler:
        sure_dk = round((b.ended_at - b.started_at).total_seconds() / 60) if b.ended_at else None
        satirlar.append(
            {
                "id": b.id,
                "service_order_id": b.service_order_id,
                "so_no": so_no,
                "faaliyet": b.faaliyet,
                "started_at": b.started_at,
                "ended_at": b.ended_at,
                "sure_dk": sure_dk,
                "kaynak": b.kaynak,
                "iptal_turu": b.iptal_turu,
            }
        )
        if b.is_deleted or b.ended_at is None:
            continue
        sn = (b.ended_at - b.started_at).total_seconds()
        if b.faaliyet in KISI_SAATE_DAHIL:
            kapali_var = True
            kisi_saat_sn += sn
            faaliyet_sn[b.faaliyet] = faaliyet_sn.get(b.faaliyet, 0.0) + sn
        else:
            mola_var = True
            mola_sn += sn

    gun_bolumu = exists().where(
        ServiceTimeEntry.service_order_id == ServiceOrder.id,
        ServiceTimeEntry.user_id == user.id,
        ServiceTimeEntry.is_deleted.is_(False),
        ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
        ServiceTimeEntry.started_at >= bas,
        ServiceTimeEntry.started_at < bit,
    )
    plani_bugun = exists().where(
        ServicePlan.service_order_id == ServiceOrder.id,
        ServicePlan.is_active.is_(True),
        ServicePlan.is_deleted.is_(False),
        ServicePlan.plan_date == gun,
    )
    durumu_degistirdi = exists().where(
        ServiceOrderEvent.service_order_id == ServiceOrder.id,
        ServiceOrderEvent.olay_turu == "DURUM",
        ServiceOrderEvent.user_id == user.id,
        ServiceOrderEvent.olusma_zamani >= bas,
        ServiceOrderEvent.olusma_zamani < bit,
    )
    atanmis = exists().where(
        ServiceOrderAssignment.service_order_id == ServiceOrder.id,
        ServiceOrderAssignment.user_id == user.id,
        ServiceOrderAssignment.removed_at.is_(None),
    )
    eksik = (
        await db.execute(
            select(ServiceOrder.id, ServiceOrder.so_no, ServiceOrder.status, ServiceOrder.konu)
            .where(
                atanmis,
                or_(plani_bugun, durumu_degistirdi),
                zaman.calisilmis_ifadesi(),
                ~gun_bolumu,
            )
            .order_by(ServiceOrder.so_no)
        )
    ).all()

    return {
        "sunucu_zamani": clock.now(),
        "gun": gun,
        "bolumler": satirlar,
        "kisi_saat_dk": round(kisi_saat_sn / 60) if kapali_var else None,
        "faaliyet_dk": {f: round(s / 60) for f, s in faaliyet_sn.items()},
        "mola_dk": round(mola_sn / 60) if mola_var else None,
        "sure_eksik_isler": [{"id": i, "so_no": n, "durum": d, "konu": k} for i, n, d, k in eksik],
    }
