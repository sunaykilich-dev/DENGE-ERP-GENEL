"""Kalıcı SLA bildirimi üretimi (worker, 5 dk), temizlik ve zil rozeti (E10-05, TS-083).

Doldurdu: D2-G.

**Rozet sayısı ANLIK hesaplanır** (E10 kontrol B6; canlı ilke "uyarılar
hesaplanır, saklanmaz"): zil satırları Operasyon KPI'larının kapsamlı
sayısıdır (`panel.kpi_sayisi`), tıklanınca aynı listeye gider. Böylece Servis
Paneli "SLA aşıldı", Operasyon Merkezi ve zil worker turunu beklemeden aynı
sayıyı verir.

**`service_alerts` dar olay günlüğüdür:** yalnız "görüldü" işareti ve
(Dalga 3) e-posta tekilliği içindir. Worker her turda koşulları SQL'de bulur:
koşul var ama açık kayıt yoksa ekler (`uq_salert_acik` + ON CONFLICT DO
NOTHING → iki tur çoğaltmaz), açık kayıt var ama koşul kalktıysa kapatır
(`KOSUL_KALKTI`; iş kapandıysa `IS_KAPANDI`). Birim/müşteri saklanmaz: kapsam
okuma anında `service_orders` JOIN'iyle uygulanır.

GERIYE_DONUK (göç geri doldurması) işler bildirim üretmez. `servis_uyari_uretimi_acik`
kapalıysa üretim hiçbir şey yazmaz. Temizlik yalnız KAPALI ve
`servis_uyari_saklama_gun`'den eski kayıtları siler; açık kayıt silinmez.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models import ServiceAlert, ServiceHold, ServiceOrder
from app.models.teknik_servis import DURUM_GRUPLARI
from app.services import settings as ayarlar
from app.services.teknik_servis import panel
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

TAYIN_GECIKTI = "tayin_gecikti"

# Bildirim kodu → (KPI kodu, önem, başlık kalıbı). KPI süzgeci koşulun TEK tanımıdır.
# TAYIN_GECIKTI mesai dakikasına bağlı olduğundan SQL KPI'sı değildir; koşulu
# Operasyon panosuyla aynı hesaptan gelir (`operasyon_pano.tayin_gecikenler`).
KOSULLAR: dict[str, tuple[str, str, str]] = {
    "SLA_ASILDI": ("sla_asildi", "KRITIK", "{so_no}: SLA çözüm hedefi aşıldı"),
    "SLA_RISK": ("sla_riskte", "UYARI", "{so_no}: SLA çözüm hedefi riskte"),
    "MUDAHALE_ASILDI": ("mudahale_asildi", "UYARI", "{so_no}: müdahale hedefi aşıldı"),
    "BEKLEME_BITIS_GECTI": (
        "bekleme_bitis_gecti",
        "UYARI",
        "{so_no}: beklemenin beklenen bitişi geçti",
    ),
    "PB_VADE_GECTI": ("vadesi_gecen_bakim", "UYARI", "{so_no}: bakım vadesi geçti"),
    "TAYIN_GECIKTI": (TAYIN_GECIKTI, "UYARI", "{so_no}: tayin süresi aşıldı"),
}

# Zil satırları (anlık): (KPI kodu, onem, açıklama). Sıra sabittir.
_ROZET = (
    ("sla_asildi", "kritik", "Çözüm hedefi geçmiş servis işleri."),
    ("sla_riskte", "uyari", "Çözüm hedef süresinin risk eşiği dolmuş servis işleri."),
    ("mudahale_asildi", "uyari", "Müdahale hedefi geçmiş, ilk müdahalesi yapılmamış işler."),
    ("bekleme_bitis_gecti", "uyari", "Beklenen bitiş zamanı geçmiş iş beklemeleri."),
)


async def _kosul_isleri(db: AsyncSession, kpi: str, clock: Clock) -> dict[int, str]:
    """KPI koşulunu sağlayan işler → iş no (kapsamsız; bildirim kaydı ortaktır)."""
    if kpi == TAYIN_GECIKTI:
        from app.services.teknik_servis.operasyon_pano import tayin_gecikenler

        return await tayin_gecikenler(db, clock)
    tanim = panel.kpi_suzgeci(kpi)
    stmt = tanim.suzgec(select(ServiceOrder.id, ServiceOrder.so_no), None, clock, None)
    return {i: n for i, n in (await db.execute(stmt)).all()}


async def uret(db: AsyncSession, clock: Clock) -> int:
    """Açık işler için `service_alerts` satırı (uq_salert_acik; ON CONFLICT DO NOTHING).
    Yeni açılan kayıt sayısını döner; kapanan sayısı `son_ozet`'e yazılır."""
    son_ozet.clear()
    if not await ayarlar.get(db, "servis_uyari_uretimi_acik"):
        son_ozet.update({"kapali": True})
        return 0
    simdi = clock.now()
    acilan = kapanan = 0
    for kod, (kpi, onem, kalip) in KOSULLAR.items():
        isteneler = await _kosul_isleri(db, kpi, clock)
        acik = dict(
            (
                await db.execute(
                    select(ServiceAlert.service_order_id, ServiceAlert.id).where(
                        ServiceAlert.kod == kod, ServiceAlert.kapanis_at.is_(None)
                    )
                )
            ).all()
        )
        yeni = [i for i in isteneler if i not in acik]
        if yeni:
            sonuc = await db.execute(
                insert(ServiceAlert)
                .values(
                    [
                        {
                            "kod": kod,
                            "service_order_id": i,
                            "onem": onem,
                            "baslik": kalip.format(so_no=isteneler[i])[:200],
                            "acilis_at": simdi,
                        }
                        for i in yeni
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=["kod", "service_order_id"],
                    index_where=ServiceAlert.kapanis_at.is_(None),
                )
                .returning(ServiceAlert.id)
            )
            acilan += len(sonuc.all())
        kalkan = [alert_id for so_id, alert_id in acik.items() if so_id not in isteneler]
        if kalkan:
            kapali_isler = set(
                (
                    await db.scalars(
                        select(ServiceAlert.id)
                        .join(ServiceOrder, ServiceOrder.id == ServiceAlert.service_order_id)
                        .where(
                            ServiceAlert.id.in_(kalkan),
                            (ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["KAPALI"])))
                            | ServiceOrder.is_deleted.is_(True),
                        )
                    )
                ).all()
            )
            for alert_id in kalkan:
                await db.execute(
                    update(ServiceAlert)
                    .where(ServiceAlert.id == alert_id, ServiceAlert.kapanis_at.is_(None))
                    .values(
                        kapanis_at=simdi,
                        kapanis_nedeni="IS_KAPANDI" if alert_id in kapali_isler else "KOSUL_KALKTI",
                    )
                )
            kapanan += len(kalkan)
    await db.flush()
    toplam_acik = int(
        await db.scalar(
            select(func.count()).select_from(ServiceAlert).where(ServiceAlert.kapanis_at.is_(None))
        )
        or 0
    )
    tutarsiz = await tutarsiz_bekleme_sayisi(db)
    son_ozet.update(
        {"acilan": acilan, "kapanan": kapanan, "acik": toplam_acik, "tutarsiz_bekleme": tutarsiz}
    )
    return acilan


# Son turun özeti (worker log satırı; süreç içi, kalıcı değil).
son_ozet: dict[str, Any] = {}


async def tutarsiz_bekleme_sayisi(db: AsyncSession) -> int:
    """E10-11 gece uzlaştırması: BEKLEMEDE olmayan ama aktif beklemesi olan iş sayısı (0 olmalı)."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ServiceHold)
            .join(ServiceOrder, ServiceOrder.id == ServiceHold.service_order_id)
            .where(ServiceHold.released_at.is_(None), ServiceOrder.status != "BEKLEMEDE")
        )
        or 0
    )


async def temizle(db: AsyncSession, clock: Clock) -> int:
    """`servis_uyari_saklama_gun`'den eski kapalı bildirimleri siler (açık olan silinmez)."""
    gun = int(await ayarlar.get(db, "servis_uyari_saklama_gun") or 90)
    sinir = clock.now() - timedelta(days=gun)
    sonuc = await db.execute(
        delete(ServiceAlert)
        .where(and_(ServiceAlert.kapanis_at.is_not(None), ServiceAlert.kapanis_at < sinir))
        .returning(ServiceAlert.id)
    )
    silinen = len(sonuc.all())
    await db.flush()
    return silinen


async def uretim_gorevi(db: AsyncSession, clock: Clock) -> str:
    """Worker `servis-sla-uyarilari` (5 dk) — log satırı döner."""
    await uret(db, clock)
    if son_ozet.get("kapali"):
        return "SLA bildirim üretimi kapalı (servis_uyari_uretimi_acik=false)"
    ozet = (
        f"açılan={son_ozet['acilan']} kapanan={son_ozet['kapanan']} açık={son_ozet['acik']}"
        f" tutarsız_bekleme={son_ozet['tutarsiz_bekleme']}"
    )
    if son_ozet["tutarsiz_bekleme"]:
        import logging

        logging.getLogger("denge.worker").warning(
            "UYARI: BEKLEMEDE olmayan %d işte aktif bekleme var", son_ozet["tutarsiz_bekleme"]
        )
    return ozet


async def temizlik_gorevi(db: AsyncSession, clock: Clock) -> str:
    """Worker `servis-uyari-temizligi` (24 sa)."""
    silinen = await temizle(db, clock)
    return f"{silinen} eski kapalı SLA bildirimi silindi"


# --- Zil (anlık, kapsamlı) ----------------------------------------------------------------


async def sla_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Zil satırları: KPI'nın kapsamlı anlık sayısı; yol Operasyon Merkezi (izin varsa)."""
    sonuc = []
    for kod, onem, aciklama in _ROZET:
        tanim = panel.kpi_suzgeci(kod)
        yol = f"/operasyon?kpi={kod}" if user.has("operasyon.gor") else panel.kpi_yolu(tanim)
        sonuc.append(
            Uyari(
                kod=f"sla.{kod}",
                baslik=tanim.baslik,
                adet=await panel.kpi_sayisi(db, kod, user, clock),
                yol=yol,
                onem=onem,
                aciklama=aciklama,
            )
        )
    return sonuc


ts_uyarilar.kaydet("sla", "servis.gor", sla_uyarilari)
