"""Operasyon Merkezi panosu: dispeçerin "şu an neye müdahale etmeliyim" ekranı (2026-11-18).

Kullanıcı kararları (servis şefi işi dağıtır, plan sabah yapılır, günde
20-30 iş; en çok kaçan şey tayin edilmeyen iş):

- **Tayin bekleyenler:** `atanmamis` KPI'sıyla AYNI süzgeç (sayı = liste).
  Bekleme süresi işin açılışından itibaren MESAİ dakikasıdır
  (`sla_takvim.takvim_dakika`, mesai penceresi `servis_mesai_*`): gece ya da
  hafta sonu açılan iş mesai başlayınca saymaya başlar. Eşik ayardır:
  KRİTİK işte `servis_tayin_suresi_kritik_dk`, diğerlerinde
  `servis_tayin_suresi_dk`. Eşiği aşan iş "gecikti" olur; aynı hesap kalıcı
  `TAYIN_GECIKTI` bildirimini (ve anlık e-postayı) üretir (`tayin_gecikenler`).
- **Plandan sapanlar:** bugünkü planın başlangıç saati geçmiş ama hâlâ
  PLANLANDI olan işler (saat girilmemiş planda uyarı yok), beklenen bitişi
  geçmiş beklemeler (`bekleme_bitis_gecti`) ve vadesi geçen bakımlar
  (`vadesi_gecen_bakim`). Her tür en çok `SAPMA_SINIRI` satır, toplamıyla.
- **Ekip durumu:** `operasyon.is_yuku` kişileri; durum kişinin açık zaman
  sayacından: YOL → yolda, MOLA/sayaç yok → boşta, diğerleri → sahada.

Ayrı veri katmanı yok: süzgeçler panel KPI kaydından, satırlar
`operasyon.liste_satirlari`'ndan (kapsam ve maskeleme aynı).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models import ServiceOrder, ServicePlan
from app.services import settings as ayarlar
from app.services.teknik_servis import kapsam, operasyon, panel, sla, sla_takvim
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun_araligi

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

SAPMA_SINIRI = 5
_ONCELIK_SIRASI = {"KRITIK": 0, "YUKSEK": 1}


async def tayin_esikleri(db: AsyncSession) -> tuple[int, int]:
    """(kritik_dk, diger_dk) — Parametreler'den."""
    return (
        int(await ayarlar.get(db, "servis_tayin_suresi_kritik_dk") or 10),
        int(await ayarlar.get(db, "servis_tayin_suresi_dk") or 30),
    )


def _bekleme(
    acilis: datetime, oncelik: str, simdi: datetime, mesai, esikler: tuple[int, int]
) -> tuple[int, int]:
    """(mesai içinde geçen dk, eşik dk)."""
    esik = esikler[0] if oncelik == "KRITIK" else esikler[1]
    return sla_takvim.takvim_dakika(acilis, simdi, sla_takvim.TAKVIM_MESAI, mesai=mesai), esik


async def tayin_gecikenler(db: AsyncSession, clock: Clock) -> dict[int, str]:
    """Eşiği aşmış tayinsiz açık işler → iş no (KAPSAMSIZ; bildirim üretimi için).

    Ekrandaki "gecikti" ile aynı hesap: `atanmamis` süzgeci + mesai dakikası."""
    tanim = panel.kpi_suzgeci("atanmamis")
    stmt = tanim.suzgec(
        select(ServiceOrder.id, ServiceOrder.so_no, ServiceOrder.oncelik, ServiceOrder.created_at),
        None,
        clock,
        None,
    )
    esikler = await tayin_esikleri(db)
    mesai = await sla.mesai_takvimi(db)
    simdi = clock.now()
    sonuc: dict[int, str] = {}
    for so_id, so_no, oncelik, acilis in (await db.execute(stmt)).all():
        gecen, esik = _bekleme(acilis, oncelik, simdi, mesai, esikler)
        if gecen >= esik:
            sonuc[so_id] = so_no
    return sonuc


async def tayin_sayilari(db: AsyncSession, user: User, clock: Clock) -> dict[str, int]:
    """Menü rozeti ve sekme başlığı için hafif sayım (kapsamlı, birimsiz)."""
    kimlikler = operasyon.sayac_sorgusu("atanmamis", user, clock)
    satirlar = (
        await db.execute(
            select(ServiceOrder.oncelik, ServiceOrder.created_at).where(
                ServiceOrder.id.in_(kimlikler)
            )
        )
    ).all()
    esikler = await tayin_esikleri(db)
    mesai = await sla.mesai_takvimi(db)
    simdi = clock.now()
    geciken = 0
    for oncelik, acilis in satirlar:
        gecen, esik = _bekleme(acilis, oncelik, simdi, mesai, esikler)
        geciken += gecen >= esik
    return {"bekleyen": len(satirlar), "geciken": geciken}


async def _isler(db: AsyncSession, kimlikler, sinir: int | None = None) -> list[ServiceOrder]:
    stmt = (
        select(ServiceOrder)
        .where(ServiceOrder.id.in_(kimlikler))
        .order_by(ServiceOrder.created_at, ServiceOrder.id)
    )
    if sinir:
        stmt = stmt.limit(sinir)
    return list((await db.scalars(stmt)).all())


async def _say(db: AsyncSession, kimlikler) -> int:
    return int(await db.scalar(select(func.count()).select_from(kimlikler.subquery())) or 0)


async def _tayin_bekleyenler(
    db: AsyncSession, user: User, clock: Clock, birim: str | None
) -> list[dict[str, Any]]:
    kimlikler = operasyon.sayac_sorgusu("atanmamis", user, clock, birim=birim)
    sos = await _isler(db, kimlikler)
    satirlar = await operasyon.liste_satirlari(db, sos, clock)
    esikler = await tayin_esikleri(db)
    mesai = await sla.mesai_takvimi(db)
    simdi = clock.now()
    for satir in satirlar:
        gecen, esik = _bekleme(satir["created_at"], satir["oncelik"], simdi, mesai, esikler)
        satir.update(bekleme_dk=gecen, esik_dk=esik, gecikti=gecen >= esik)
        satir.pop("sla", None)
    # Önce süresi geçenler, sonra öncelik, sonra en uzun bekleyen.
    satirlar.sort(
        key=lambda s: (
            not s["gecikti"],
            _ONCELIK_SIRASI.get(s["oncelik"], 2),
            -s["bekleme_dk"],
        )
    )
    return satirlar


async def _sapmalar(
    db: AsyncSession, user: User, clock: Clock, birim: str | None
) -> dict[str, Any]:
    simdi = clock.now()
    bugun = yerel_bugun(clock)
    # Bugün planlı + başlangıç saati geçmiş + hâlâ PLANLANDI (yola çıkılmamış).
    gec_plan = (
        select(ServiceOrder.id)
        .join(ServicePlan, ServicePlan.service_order_id == ServiceOrder.id)
        .where(
            ServiceOrder.id.in_(operasyon.sayac_sorgusu("bugun_planli", user, clock, birim=birim)),
            ServiceOrder.status == "PLANLANDI",
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
            ServicePlan.plan_date == bugun,
            ServicePlan.starts_at.is_not(None),
            ServicePlan.starts_at <= simdi,
        )
    )
    turler = (
        ("PLAN_SAATI", gec_plan),
        ("BEKLEME", operasyon.sayac_sorgusu("bekleme_bitis_gecti", user, clock, birim=birim)),
        ("BAKIM_VADESI", operasyon.sayac_sorgusu("vadesi_gecen_bakim", user, clock, birim=birim)),
    )
    satirlar: list[dict[str, Any]] = []
    toplamlar: dict[str, int] = {}
    for tur, kimlikler in turler:
        toplamlar[tur] = await _say(db, kimlikler)
        sos = await _isler(db, kimlikler, SAPMA_SINIRI)
        for satir in await operasyon.liste_satirlari(db, sos, clock):
            satir.pop("sla", None)
            satir["sapma"] = tur
            satirlar.append(satir)
    if satirlar:
        plan_saatleri = dict(
            (
                await db.execute(
                    select(ServicePlan.service_order_id, func.min(ServicePlan.starts_at))
                    .where(
                        ServicePlan.service_order_id.in_([s["id"] for s in satirlar]),
                        ServicePlan.is_active.is_(True),
                        ServicePlan.is_deleted.is_(False),
                        ServicePlan.plan_date == bugun,
                    )
                    .group_by(ServicePlan.service_order_id)
                )
            ).all()
        )
        for satir in satirlar:
            satir["plan_baslangic"] = plan_saatleri.get(satir["id"])
    return {"satirlar": satirlar, "toplamlar": toplamlar}


def _ekip_durumu(acik_sayac: dict[str, Any] | None, musait_degil: dict | None = None) -> str:
    if acik_sayac is None or acik_sayac["faaliyet"] == "MOLA":
        # İzin/eğitim/ofis bloğundaki kişi boşta sayılmaz (tayine uygun değil).
        return "MUSAIT_DEGIL" if musait_degil else "BOSTA"
    return "YOLDA" if acik_sayac["faaliyet"] == "YOL" else "SAHADA"


async def pano(
    db: AsyncSession, user: User, clock: Clock, *, birim: str | None = None
) -> dict[str, Any]:
    birim = panel.birim_dogrula(user, birim)
    tayin = await _tayin_bekleyenler(db, user, clock, birim)
    sapma = await _sapmalar(db, user, clock, birim)
    ekip = []
    for kisi in await operasyon.is_yuku(db, user, clock, birim=birim):
        ekip.append(
            {
                "user_id": kisi["user_id"],
                "ad": kisi["ad"],
                "saha_rolu": kisi["saha_rolu"],
                "birimler": kisi["birimler"],
                "durum": _ekip_durumu(kisi["acik_sayac"], kisi["musait_degil"]),
                "acik_sayac": kisi["acik_sayac"],
                "musait_degil": kisi["musait_degil"],
                "bugun_planli": kisi["bugun_planli"],
                "acik_atanmis": kisi["acik_atanmis"],
            }
        )
    # Bugün TAMAMLANDI'ya geçen işler (Türkiye günü), kapsamlı.
    bas, bit = yerel_gun_araligi(yerel_bugun(clock))
    tamamlanan = select(ServiceOrder.id).where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.completed_at >= bas,
        ServiceOrder.completed_at < bit,
    )
    if birim:
        tamamlanan = tamamlanan.where(ServiceOrder.birim == birim)
    tamamlanan_bugun = await _say(db, kapsam.kapsam_isler(tamamlanan, user, ServiceOrder.id))
    esikler = await tayin_esikleri(db)
    return {
        "esikler": {"kritik_dk": esikler[0], "diger_dk": esikler[1]},
        "ozet": {
            "bugun_planli": await _say(
                db, operasyon.sayac_sorgusu("bugun_planli", user, clock, birim=birim)
            ),
            "bugun_tamamlanan": tamamlanan_bugun,
            "yolda": sum(1 for k in ekip if k["durum"] == "YOLDA"),
            "sahada": sum(1 for k in ekip if k["durum"] == "SAHADA"),
            "bosta": sum(1 for k in ekip if k["durum"] == "BOSTA"),
            "musait_degil": sum(1 for k in ekip if k["durum"] == "MUSAIT_DEGIL"),
            "tayin_bekleyen": len(tayin),
            "tayin_geciken": sum(1 for s in tayin if s["gecikti"]),
            "sapma": sum(sapma["toplamlar"].values()),
        },
        "tayin_bekleyenler": tayin,
        "sapmalar": sapma["satirlar"],
        "sapma_toplamlari": sapma["toplamlar"],
        "ekip": ekip,
    }
