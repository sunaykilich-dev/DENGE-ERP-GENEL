"""Hat iş kuralları: paket geçmişi, senkron ve raporlar."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.integrations.base import HatDurumu
from app.models import Device, Product, SimCard, SimDeviceHistory, SimPlanHistory, User
from app.services import settings as ayar_svc
from app.services import sirket_kapsami as kapsam

# Elle girilmiş alanlar operatör senkronunda EZİLMEZ.
MANUEL = "MANUEL"
API = "API"


async def paket_degistir(
    db: AsyncSession,
    hat: SimCard,
    *,
    clock: Clock,
    plan_name: str | None = None,
    data_allowance_mb: int | None = None,
    enabled_network_tech: list[str] | None = None,
    monthly_cost: Decimal | None = None,
    an: datetime | None = None,
) -> SimPlanHistory:
    """Yeni paket dönemi açar, öncekini kapatır.

    Brief §4.4: "hangi tarihte hangi paket, kaç GB, hangi teknoloji açıktı"
    sorusu ancak tarihli kayıtla cevaplanır.
    """
    zaman = an or clock.now()
    if zaman.tzinfo is None:
        zaman = zaman.replace(tzinfo=UTC)

    acik = await db.scalar(
        select(SimPlanHistory).where(
            SimPlanHistory.sim_id == hat.id, SimPlanHistory.valid_to.is_(None)
        )
    )
    if acik is not None:
        acik.valid_to = zaman

    kayit = SimPlanHistory(
        sim_id=hat.id,
        plan_name=plan_name,
        data_allowance_mb=data_allowance_mb,
        enabled_network_tech=enabled_network_tech,
        monthly_cost=monthly_cost,
        valid_from=zaman,
    )
    db.add(kayit)
    hat.plan_name = plan_name
    hat.data_allowance_mb = data_allowance_mb
    if enabled_network_tech is not None:
        hat.enabled_network_tech = enabled_network_tech
    await db.flush()
    return kayit


async def senkron_uygula(
    db: AsyncSession, hat: SimCard, durum: HatDurumu, clock: Clock
) -> list[str]:
    """Operatörden gelen değerleri uygular; ELLE GİRİLEN alanları korur.

    Brief §4.4: "Elle girilen değer, API boş döndüğünde silinmez." Buradaki
    kural bir adım daha ileri: elle girilmiş bir alan, API DOLU dönse bile
    ezilmez — aksi halde ekibin düzelttiği değer her gece geri alınırdı.
    Ezilmesi isteniyorsa alan `field_sources`'tan kaldırılır.
    """
    kaynaklar = dict(hat.field_sources or {})
    degisen: list[str] = []

    for alan, deger in durum.dolu_alanlar().items():
        if alan == "commitment_end":
            continue
        if kaynaklar.get(alan) == MANUEL:
            continue
        if getattr(hat, alan, None) != deger:
            setattr(hat, alan, deger)
            degisen.append(alan)
        kaynaklar[alan] = API

    if durum.commitment_end and kaynaklar.get("commitment_end_date") != MANUEL:
        try:
            hat.commitment_end_date = date.fromisoformat(durum.commitment_end)
            kaynaklar["commitment_end_date"] = API
            degisen.append("commitment_end_date")
        except ValueError:
            pass

    hat.field_sources = kaynaklar
    hat.usage_synced_at = clock.now()
    await db.flush()
    return degisen


# --- Raporlar ----------------------------------------------------------------
#
# Şirket bazlı (fcl000000001): `user` verilirse hatlar etkin şirkete, cihazlar
# ürünün şirketine süzülür. `user=None` (gece işi, worker) = süzgeç yok.


def _hat(user: User | None):
    return kapsam.hat_kosulu(user) if user is not None else None


def _urun(user: User | None):
    return kapsam.urun_kosulu(user) if user is not None else None


async def kota_uyarilari(db: AsyncSession, *, user: User | None = None) -> list[dict]:
    """Kotasının %80'ini veya tamamını kullanan hatlar (brief §4.4)."""
    ayarlar = await ayar_svc.get_all(db)
    esik1 = int(ayarlar["kota_uyari_yuzde_1"])
    esik2 = int(ayarlar["kota_uyari_yuzde_2"])
    stmt = select(SimCard).where(
        SimCard.is_deleted.is_(False),
        SimCard.data_allowance_mb.is_not(None),
        SimCard.data_allowance_mb > 0,
        SimCard.data_used_mb.is_not(None),
    )
    satirlar = (await db.scalars(kapsam.uygula(stmt, _hat(user)))).all()
    sonuc = []
    for h in satirlar:
        yuzde = round(100 * (h.data_used_mb or 0) / h.data_allowance_mb)
        if yuzde < esik1:
            continue
        sonuc.append(
            {
                "sim_id": h.id,
                "iccid": h.iccid,
                "msisdn": h.msisdn,
                "yuzde": yuzde,
                "seviye": "ASILDI" if yuzde >= esik2 else "UYARI",
                "data_allowance_mb": h.data_allowance_mb,
                "data_used_mb": h.data_used_mb,
            }
        )
    return sorted(sonuc, key=lambda x: -x["yuzde"])


async def iki_g_riski(db: AsyncSession, *, user: User | None = None) -> list[dict]:
    """Yalnız 2G/3G destekleyen cihazlar ve yalnız 2G açık hatlar.

    Mevcut mobil şebeke yetkilendirmeleri 30 Nisan 2029'da bitiyor; bu liste
    hem risk hem de cihaz değişimi için satış fırsatı listesidir (brief §4.4).
    """
    modern = {"4G", "LTE_M", "NB_IOT"}

    # Cihaz tarafı: ürünün desteklediği şebekelerde modern teknoloji yok.
    cihaz_stmt = (
        select(Device, Product)
        .join(Product, Product.id == Device.product_id)
        .where(
            Device.is_deleted.is_(False),
            Device.status.in_(("AKTIF", "MONTAJ_BEKLIYOR", "STOKTA")),
            Product.supported_network_tech.is_not(None),
            ~Product.supported_network_tech.overlap(list(modern)),
        )
    )
    cihazlar = (await db.execute(kapsam.uygula(cihaz_stmt, _urun(user)))).all()

    sonuc = [
        {
            "tur": "CIHAZ",
            "id": c.id,
            "kimlik": c.kimlik,
            "urun": u.name,
            "destekledigi": u.supported_network_tech,
            "musteri_id": c.current_customer_id,
        }
        for c, u in cihazlar
    ]

    hat_stmt = select(SimCard).where(
        SimCard.is_deleted.is_(False),
        SimCard.status == "AKTIF",
        SimCard.enabled_network_tech.is_not(None),
        ~SimCard.enabled_network_tech.overlap(list(modern)),
    )
    hatlar = (await db.scalars(kapsam.uygula(hat_stmt, _hat(user)))).all()
    sonuc += [
        {
            "tur": "HAT",
            "id": h.id,
            "kimlik": h.msisdn or h.iccid,
            "urun": h.plan_name,
            "destekledigi": h.enabled_network_tech,
            "musteri_id": None,
        }
        for h in hatlar
    ]
    return sonuc


async def atil_hatlar(db: AsyncSession, clock: Clock, *, user: User | None = None) -> list[dict]:
    """Aktif olduğu halde uzun süredir veri göndermeyen hatlar (gereksiz maliyet).

    Kullanım verisi operatörden gelmediği sürece `usage_synced_at` boş kalır;
    o hatlar da "bilinmiyor" olarak listelenir — sessizce atlanmaz, çünkü
    gereksiz maliyetin görünmemesi bu raporun varlık sebebini ortadan kaldırır.
    """
    gun = int(await ayar_svc.get(db, "atil_hat_gun"))
    sinir = clock.now() - timedelta(days=gun)
    stmt = select(SimCard).where(
        SimCard.is_deleted.is_(False),
        SimCard.status == "AKTIF",
        or_(
            SimCard.usage_synced_at.is_(None),
            SimCard.usage_synced_at < sinir,
            SimCard.data_used_mb == 0,
        ),
    )
    hatlar = (await db.scalars(kapsam.uygula(stmt, _hat(user)))).all()
    return [
        {
            "sim_id": h.id,
            "iccid": h.iccid,
            "msisdn": h.msisdn,
            "aylik_maliyet": h.aylik_maliyet,
            "son_senkron": h.usage_synced_at,
            "neden": "Hiç senkron edilmedi" if h.usage_synced_at is None else "Veri yok",
        }
        for h in hatlar
    ]


async def hat_karliligi(db: AsyncSession, *, user: User | None = None) -> dict:
    """Müşteriden alınan hat ücreti − operatör maliyeti (brief §4.4)."""
    satir = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(SimCard.monthly_charge), 0),
                func.coalesce(
                    func.sum(
                        func.coalesce(SimCard.tariff_cost, 0)
                        + func.coalesce(SimCard.package_cost, 0)
                        + func.coalesce(SimCard.apn_cost, 0)
                    ),
                    0,
                ),
            ).where(
                SimCard.is_deleted.is_(False),
                SimCard.status == "AKTIF",
                *([k] if (k := _hat(user)) is not None else []),
            )
        )
    ).one()
    adet, gelir, maliyet = satir[0], Decimal(str(satir[1])), Decimal(str(satir[2]))
    return {
        "aktif_hat": adet,
        "aylik_gelir": float(gelir),
        "aylik_maliyet": float(maliyet),
        "aylik_marj": float(gelir - maliyet),
        "marj_yuzde": float(round(100 * (gelir - maliyet) / gelir, 2)) if gelir else None,
    }


async def taahhudu_bitenler(
    db: AsyncSession, clock: Clock, *, user: User | None = None
) -> list[dict]:
    """Taahhüdü yaklaşan hatlar.

    İndirim taahhüde bağlı (%89): taahhüt düşerse aynı hat 14,43 TL'den
    131,16 TL'ye çıkar. Bu rapor olmadan maliyet artışı fatura geldiğinde
    fark edilir.
    """
    gun = int(await ayar_svc.get(db, "hat_taahhut_uyari_gun"))
    bugun = clock.now().date()
    stmt = (
        select(SimCard)
        .where(
            SimCard.is_deleted.is_(False),
            SimCard.commitment_end_date.is_not(None),
            SimCard.commitment_end_date <= bugun + timedelta(days=gun),
        )
        .order_by(SimCard.commitment_end_date)
    )
    hatlar = (await db.scalars(kapsam.uygula(stmt, _hat(user)))).all()
    return [
        {
            "sim_id": h.id,
            "msisdn": h.msisdn,
            "iccid": h.iccid,
            "bitis": h.commitment_end_date,
            "kalan_gun": (h.commitment_end_date - bugun).days,
            "indirimli_maliyet": h.aylik_maliyet,
            "indirim_orani": float(h.discount_rate) if h.discount_rate else None,
        }
        for h in hatlar
    ]


async def cihazsiz_hatlar(db: AsyncSession, *, user: User | None = None) -> int:
    """Hiçbir cihaza takılı olmayan aktif hat sayısı."""
    takili = select(SimDeviceHistory.sim_id).where(SimDeviceHistory.valid_to.is_(None))
    stmt = (
        select(func.count())
        .select_from(SimCard)
        .where(
            SimCard.is_deleted.is_(False),
            SimCard.status == "AKTIF",
            SimCard.id.not_in(takili),
        )
    )
    return (await db.scalar(kapsam.uygula(stmt, _hat(user)))) or 0
