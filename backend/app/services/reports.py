"""Yönetim dashboard'u ve raporlar (brief §4.14).

**Her rakamın kaynağı tek olmalı.** Dashboard, modüllerin kendi servislerini
çağırır; aynı sayıyı ikinci kez hesaplamaz. MRR aboneliklerin olay
tablosundan, hak ediş dökümlerden, stok cihaz durumlarından gelir — burada
yeniden türetmek, iki ekranın farklı sayı göstermesi demekti.

**Maliyet içeren raporlar `maliyet.gor` iznine tabidir** (plan §3.4).
Servis katmanı tutarı hesaplar; gizleme kararı API katmanında verilir,
çünkü yetkiyi bilen orası.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Account,
    Device,
    Order,
    PartnerSettlement,
    Quote,
    SettlementLine,
    Subscription,
    WorkOrder,
    WorkOrderItem,
)
from app.services import subscriptions as abonelik_svc
from app.services.quotes import yuvarla

# Sahada çalışan sayılan durumlar.
SAHADA = ("AKTIF", "MONTAJ_BEKLIYOR")
STOKTA_SAYILAN = ("STOKTA", "TEST_EDILDI", "YENIDEN_STOKTA", "ITHALATTA")


def _ay_araligi(gun: date) -> tuple[date, date]:
    return abonelik_svc.donem_araligi(f"{gun:%Y-%m}")


async def dashboard(db: AsyncSession, clock: Clock) -> dict:
    """Yönetim panelinin tek çağrıda dönen özeti."""
    bugun = clock.now().date()
    ay_bas, ay_son = _ay_araligi(bugun)
    donem = f"{bugun:%Y-%m}"

    cihaz_durumlari = dict(
        (
            await db.execute(
                select(Device.status, func.count())
                .where(Device.is_deleted.is_(False))
                .group_by(Device.status)
            )
        ).all()
    )
    sahada = sum(cihaz_durumlari.get(d, 0) for d in SAHADA)
    stokta = sum(cihaz_durumlari.get(d, 0) for d in STOKTA_SAYILAN)

    # Stok değeri landed cost'tan; girilmemişse 0 sayılır ve ayrıca kaç
    # cihazın maliyetinin bilinmediği raporlanır — "stok değeri 0" ile
    # "maliyeti girilmemiş" aynı şey değil.
    stok_degeri, maliyetsiz = (
        await db.execute(
            select(
                func.coalesce(func.sum(Device.landed_cost_try), 0),
                func.count().filter(Device.landed_cost_try.is_(None)),
            ).where(Device.is_deleted.is_(False), Device.status.in_(STOKTA_SAYILAN))
        )
    ).one()

    aylik_montaj = await db.scalar(
        select(func.count(func.distinct(WorkOrderItem.id)))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(
            WorkOrder.is_deleted.is_(False),
            WorkOrder.completed_at.is_not(None),
            func.date(WorkOrder.completed_at) >= ay_bas,
            func.date(WorkOrder.completed_at) <= ay_son,
            WorkOrderItem.action.in_(("TAKILDI", "DEGISTI")),
        )
    )

    bekleyen_teklif, teklif_tutari = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.grand_total), 0))
            .select_from(Quote)
            .outerjoin(Order, Order.quote_id == Quote.id)
            .where(
                Quote.is_deleted.is_(False),
                # Satış paneli yalnız satış tekliflerini sayar (E07-D02): birimli
                # servis teklifleri buraya karışsaydı "bekleyen teklif" şişerdi.
                Quote.birim.is_(None),
                Quote.status.in_(("GONDERILDI", "GORUNTULENDI", "REVIZE_EDILDI")),
            )
        )
    ).one()
    del teklif_tutari  # teklif tutarı versiyonda; burada yalnız adet anlamlı

    bekleyen_hakedis, hakedis_tutari = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(PartnerSettlement.net_payable), 0),
            ).where(PartnerSettlement.status.in_(("ONAYLANDI", "ODEME_BEKLIYOR")))
        )
    ).one()

    mrr = await abonelik_svc.mrr(db, bugun)
    hareket = await abonelik_svc.mrr_hareketi(db, donem)

    aktif_abonelik = await db.scalar(
        select(func.count()).where(
            Subscription.is_deleted.is_(False), Subscription.status == "AKTIF"
        )
    )

    return {
        "tarih": bugun,
        "donem": donem,
        "sahadaki_cihaz": sahada,
        "stoktaki_cihaz": stokta,
        "cihaz_durumlari": cihaz_durumlari,
        "stok_degeri_try": yuvarla(Decimal(str(stok_degeri or 0))),
        "maliyeti_girilmemis_cihaz": maliyetsiz,
        "aylik_montaj": aylik_montaj or 0,
        "aktif_abonelik": aktif_abonelik or 0,
        "mrr": mrr,
        "arr": yuvarla(mrr * 12),
        "churn_yuzde": hareket["churn_yuzde"],
        "bekleyen_teklif": bekleyen_teklif,
        "bekleyen_hakedis_adet": bekleyen_hakedis,
        "bekleyen_hakedis_tutar": yuvarla(Decimal(str(hakedis_tutari or 0))),
    }


def _teklif_turu(birim: str | None):
    """Varsayılan (birim None) SATIŞ teklifleridir — canlı sayılar değişmez
    (E07-D02); `birim` verilirse yalnız o birimin servis teklifleri."""
    return Quote.birim.is_(None) if birim is None else Quote.birim == birim


async def teklif_donusumu(
    db: AsyncSession,
    *,
    gun: int = 365,
    clock: Clock,
    birim: str | None = None,
    user=None,
) -> dict:
    """Teklif dönüşüm oranı — kaç teklif siparişe döndü.

    `birim` verilirse servis teklifleri (kullanıcı verilirse `teklif_kapsami`
    ile süzülür); servis teklifinde IPTAL kaybedilen sayılmaz, ayrı verilir.
    Varsayılan çağrı (`birim=None`) SATIŞ tekliflerinin canlı sonucunu AYNEN
    verir (E07-24 kontrol kararı); hesaplanan "süresi doldu" (`etkin_durum`),
    tutar ve yanıt günü yalnız birimli raporda (`servis_teklif_donusumu`).
    """
    if birim is not None:
        return await servis_teklif_donusumu(db, gun=gun, clock=clock, birim=birim, user=user)
    baslangic = clock.now().date() - timedelta(days=gun)
    stmt = (
        select(Quote.status, func.count())
        .where(
            Quote.is_deleted.is_(False),
            _teklif_turu(birim),
            func.date(Quote.created_at) >= baslangic,
        )
        .group_by(Quote.status)
    )
    if user is not None and birim is not None:
        from app.services.quotes import teklif_kapsami

        stmt = teklif_kapsami(stmt, user)
    satirlar = dict((await db.execute(stmt)).all())
    toplam = sum(satirlar.values())
    kazanilan = satirlar.get("KABUL", 0) + satirlar.get("SIPARISE_DONUSTU", 0)
    kaybedilen = satirlar.get("RED", 0) + satirlar.get("SURESI_DOLDU", 0)
    karara_baglanan = kazanilan + kaybedilen

    kayip_nedenleri = (
        await db.execute(
            select(Quote.lost_reason, func.count())
            .where(
                Quote.is_deleted.is_(False),
                _teklif_turu(birim),
                Quote.status == "RED",
                Quote.lost_reason.is_not(None),
                func.date(Quote.created_at) >= baslangic,
            )
            .group_by(Quote.lost_reason)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()

    return {
        "gun": gun,
        "birim": birim,
        "iptal": satirlar.get("IPTAL", 0),
        "toplam_teklif": toplam,
        "durumlar": satirlar,
        "kazanilan": kazanilan,
        "kaybedilen": kaybedilen,
        # Karara bağlanmamış teklif paydaya girmez: henüz cevap bekleyen
        # teklifi "kaybedilmiş" saymak dönüşüm oranını olduğundan kötü
        # gösterirdi.
        "donusum_yuzde": (round(kazanilan / karara_baglanan * 100, 2) if karara_baglanan else None),
        "kayip_nedenleri": [{"neden": n, "adet": a} for n, a in kayip_nedenleri],
    }


# --- Servis (birimli) teklif dönüşümü (E07-24, TS-197) -----------------------------------


def _servis_teklif_sorgusu(*, gun: int, clock: Clock, birim: str, user=None):
    """Birimli tekliflerin güncel sürümle birleşik sorgusu + etkin durum.

    Revizyon aynı teklifin sürümüdür: teklif BİR kez sayılır (güncel sürüm).
    Kapsam `teklif_kapsami` (KENDI_BIRIMI kullanıcıda başka birim girmez).
    """
    from app.models import QuoteVersion
    from app.services.quotes import etkin_durum_ifadesi, teklif_kapsami
    from app.services.teknik_servis.yerel_zaman import yerel_bugun

    bugun = yerel_bugun(clock)
    baslangic = bugun - timedelta(days=gun)
    durum = etkin_durum_ifadesi(bugun).label("etkin_durum")
    stmt = (
        select(
            Quote.id,
            Quote.quote_no,
            Quote.birim,
            Quote.created_at,
            Quote.lost_reason,
            durum,
            Account.title.label("musteri"),
            QuoteVersion.sent_at,
            QuoteVersion.accepted_at,
            QuoteVersion.rejected_at,
            QuoteVersion.grand_total,
            QuoteVersion.vat_total,
            QuoteVersion.currency,
            QuoteVersion.fx_rate,
        )
        .outerjoin(QuoteVersion, QuoteVersion.id == Quote.current_version_id)
        .outerjoin(Account, Account.id == Quote.customer_id)
        .where(
            Quote.is_deleted.is_(False),
            Quote.birim == birim,
            func.date(Quote.created_at) >= baslangic,
        )
        .order_by(Quote.created_at, Quote.id)
    )
    if user is not None:
        stmt = teklif_kapsami(stmt, user)
    return stmt


def _net_tl(r) -> Decimal | None:
    """Güncel sürümün KDV hariç, iskonto sonrası TL tutarı (kur yoksa None)."""
    if r.grand_total is None:
        return None
    net = Decimal(str(r.grand_total)) - Decimal(str(r.vat_total or 0))
    if r.currency != "TRY":
        if r.fx_rate is None:
            return None
        net *= Decimal(str(r.fx_rate))
    return yuvarla(net)


async def servis_teklif_satirlari(
    db: AsyncSession, *, gun: int, clock: Clock, birim: str, user=None
) -> list[dict]:
    """Excel "Teklifler" sayfası: rapor toplamıyla AYNI sorgunun satırları."""
    satirlar = []
    for r in (
        await db.execute(_servis_teklif_sorgusu(gun=gun, clock=clock, birim=birim, user=user))
    ).all():
        karar = r.accepted_at or r.rejected_at
        satirlar.append(
            {
                "quote_no": r.quote_no,
                "birim": r.birim,
                "musteri": r.musteri,
                "olusturma": r.created_at,
                "durum": r.etkin_durum,
                "gonderim": r.sent_at,
                "karar": karar,
                "yanit_gun": (
                    round((karar - r.sent_at).total_seconds() / 86400, 1)
                    if karar is not None and r.sent_at is not None
                    else None
                ),
                "net_tl": _net_tl(r),
                "kayip_nedeni": r.lost_reason if r.etkin_durum == "RED" else None,
            }
        )
    return satirlar


async def servis_teklif_donusumu(
    db: AsyncSession, *, gun: int = 365, clock: Clock, birim: str, user=None
) -> dict:
    """Birimli teklif dönüşüm raporu (E07-24).

    Oran = kazanılan / (kazanılan + kaybedilen); kaybedilen = RED + hesaplanan
    SURESI_DOLDU; IPTAL kaybedilen sayılmaz, ayrı verilir. Ek alanlar:
    gönderilen adet, kabul tutarı (KDV hariç net TL), ortalama yanıt günü.
    """
    alt = _servis_teklif_sorgusu(gun=gun, clock=clock, birim=birim, user=user).subquery()
    durumlar = {
        d: int(a)
        for d, a in (
            await db.execute(
                select(alt.c.etkin_durum, func.count()).select_from(alt).group_by(alt.c.etkin_durum)
            )
        ).all()
    }
    kabul = alt.c.etkin_durum.in_(("KABUL", "SIPARISE_DONUSTU"))
    net = (alt.c.grand_total - alt.c.vat_total) * case(
        (alt.c.currency == "TRY", 1), else_=alt.c.fx_rate
    )
    karar_ani = func.coalesce(alt.c.accepted_at, alt.c.rejected_at)
    gonderilen, kabul_net, kabul_eksik, ort_yanit = (
        await db.execute(
            select(
                func.count().filter(alt.c.sent_at.is_not(None)),
                func.sum(net).filter(kabul),
                func.count().filter(and_(kabul, net.is_(None))),
                func.avg(func.extract("epoch", karar_ani - alt.c.sent_at) / 86400).filter(
                    and_(karar_ani.is_not(None), alt.c.sent_at.is_not(None))
                ),
            ).select_from(alt)
        )
    ).one()
    nedenler = (
        await db.execute(
            select(alt.c.lost_reason, func.count())
            .select_from(alt)
            .where(alt.c.etkin_durum == "RED", alt.c.lost_reason.is_not(None))
            .group_by(alt.c.lost_reason)
            .order_by(func.count().desc(), alt.c.lost_reason)
            .limit(10)
        )
    ).all()
    kazanilan = durumlar.get("KABUL", 0) + durumlar.get("SIPARISE_DONUSTU", 0)
    kaybedilen = durumlar.get("RED", 0) + durumlar.get("SURESI_DOLDU", 0)
    karara_baglanan = kazanilan + kaybedilen
    return {
        "gun": gun,
        "birim": birim,
        "iptal": durumlar.get("IPTAL", 0),
        "toplam_teklif": sum(durumlar.values()),
        "durumlar": durumlar,
        "gonderilen_adet": int(gonderilen or 0),
        "kazanilan": kazanilan,
        "kaybedilen": kaybedilen,
        "donusum_yuzde": (round(kazanilan / karara_baglanan * 100, 2) if karara_baglanan else None),
        "kabul_tutari_net": yuvarla(Decimal(str(kabul_net))) if kabul_net is not None else None,
        "kabul_tutari_eksik": int(kabul_eksik or 0),
        "ort_yanit_gun": round(float(ort_yanit), 1) if ort_yanit is not None else None,
        "kayip_nedenleri": [{"neden": n, "adet": a} for n, a in nedenler],
    }


async def montaj_noktasi_performansi(db: AsyncSession, *, donem: str | None = None) -> list[dict]:
    """Montaj noktası başına iş adedi ve hak ediş maliyeti."""
    stmt = (
        select(
            PartnerSettlement.partner_id,
            Account.title,
            func.count(func.distinct(PartnerSettlement.id)).label("dokum"),
            func.coalesce(func.sum(PartnerSettlement.gross_amount), 0).label("brut"),
            func.coalesce(func.sum(PartnerSettlement.net_payable), 0).label("net"),
        )
        .join(Account, Account.id == PartnerSettlement.partner_id)
        .group_by(PartnerSettlement.partner_id, Account.title)
    )
    if donem:
        stmt = stmt.where(PartnerSettlement.period == donem)

    satirlar = (await db.execute(stmt)).all()

    is_sayilari = dict(
        (
            await db.execute(
                select(PartnerSettlement.partner_id, func.count(SettlementLine.id))
                .join(SettlementLine, SettlementLine.settlement_id == PartnerSettlement.id)
                .where(
                    SettlementLine.is_deduction.is_(False),
                    *([PartnerSettlement.period == donem] if donem else []),
                )
                .group_by(PartnerSettlement.partner_id)
            )
        ).all()
    )

    sonuc = [
        {
            "partner_id": pid,
            "unvan": unvan,
            "dokum_sayisi": dokum,
            "is_sayisi": is_sayilari.get(pid, 0),
            "brut": yuvarla(Decimal(str(brut))),
            "net": yuvarla(Decimal(str(net))),
            "is_basina_maliyet": (
                yuvarla(Decimal(str(brut)) / Decimal(is_sayilari[pid]))
                if is_sayilari.get(pid)
                else None
            ),
        }
        for pid, unvan, dokum, brut, net in satirlar
    ]
    sonuc.sort(key=lambda x: x["brut"], reverse=True)
    return sonuc


async def musteri_geliri(db: AsyncSession, clock: Clock, *, limit: int = 100) -> list[dict]:
    """Müşteri başına gelir: abonelik tahakkuku + sevk edilmiş sipariş."""
    from app.services import payments as tahsilat_svc

    abonelikler = await tahsilat_svc.abonelik_tahakkuklari(db, clock)
    siparisler = dict(
        (
            await db.execute(
                select(Order.customer_id, func.coalesce(func.sum(Order.grand_total), 0))
                .where(
                    Order.is_deleted.is_(False),
                    Order.status.in_(tahsilat_svc.BORC_DOGURAN_SIPARIS),
                )
                .group_by(Order.customer_id)
            )
        ).all()
    )
    hesap_idleri = set(abonelikler) | set(siparisler)
    if not hesap_idleri:
        return []

    unvanlar = {
        h.id: h.title
        for h in (await db.scalars(select(Account).where(Account.id.in_(hesap_idleri)))).all()
    }
    cihazlar = dict(
        (
            await db.execute(
                select(Device.current_customer_id, func.count())
                .where(
                    Device.is_deleted.is_(False),
                    Device.current_customer_id.in_(hesap_idleri),
                )
                .group_by(Device.current_customer_id)
            )
        ).all()
    )

    sonuc = []
    for hid in hesap_idleri:
        abonelik = abonelikler.get(hid, Decimal("0"))
        siparis = yuvarla(Decimal(str(siparisler.get(hid, 0))))
        sonuc.append(
            {
                "account_id": hid,
                "unvan": unvanlar.get(hid, str(hid)),
                "abonelik_geliri": abonelik,
                "siparis_geliri": siparis,
                "toplam_gelir": yuvarla(abonelik + siparis),
                "cihaz_sayisi": cihazlar.get(hid, 0),
            }
        )
    sonuc.sort(key=lambda x: x["toplam_gelir"], reverse=True)
    return sonuc[:limit]


async def cihaz_omur_boyu(db: AsyncSession, device_id: int) -> dict:
    """Bir cihazın ömür boyu geliri ve marjı (brief §4.14).

    Gelir: aboneliklerinin tahakkuku + hattın müşteriye yansıyan ücreti.
    Maliyet: landed cost + hattın Denge'ye maliyeti + montaj hak edişi.
    """
    from app.models import SimCard, SimDeviceHistory

    cihaz = await db.get(Device, device_id)
    if cihaz is None:
        raise ValueError(f"Cihaz bulunamadı: {device_id}")

    # Montaj hak edişi: bu cihaz için ödenen satırlar.
    montaj_maliyeti = await db.scalar(
        select(func.coalesce(func.sum(SettlementLine.amount), 0))
        .join(WorkOrderItem, WorkOrderItem.id == SettlementLine.work_order_item_id)
        .where(WorkOrderItem.device_id == device_id, SettlementLine.is_deduction.is_(False))
    )

    abonelik_geliri = Decimal("0")
    abonelikler = (
        await db.scalars(
            select(Subscription).where(
                Subscription.device_id == device_id, Subscription.is_deleted.is_(False)
            )
        )
    ).all()
    for a in abonelikler:
        fiyat = await abonelik_svc.gecerli_fiyat(db, a.id, a.start_date)
        if fiyat is not None:
            abonelik_geliri += abonelik_svc.aylik_tutar(fiyat.unit_price, a.billing_period)

    hat_geliri = hat_maliyeti = Decimal("0")
    hatlar = (
        await db.scalars(
            select(SimCard)
            .join(SimDeviceHistory, SimDeviceHistory.sim_id == SimCard.id)
            .where(SimDeviceHistory.device_id == device_id)
            .distinct()
        )
    ).all()
    for h in hatlar:
        hat_geliri += Decimal(str(h.monthly_charge or 0))
        hat_maliyeti += sum(
            (Decimal(str(getattr(h, a) or 0)) for a in ("tariff_cost", "package_cost", "apn_cost")),
            Decimal("0"),
        )

    cihaz_maliyeti = Decimal(str(cihaz.landed_cost_try or 0))
    montaj = yuvarla(Decimal(str(montaj_maliyeti or 0)))
    aylik_gelir = yuvarla(abonelik_geliri + hat_geliri)
    aylik_maliyet = yuvarla(hat_maliyeti)

    return {
        "device_id": device_id,
        "kimlik": cihaz.imei or cihaz.serial_no,
        "status": cihaz.status,
        "cihaz_maliyeti": yuvarla(cihaz_maliyeti),
        "montaj_maliyeti": montaj,
        "tek_seferlik_maliyet": yuvarla(cihaz_maliyeti + montaj),
        "aylik_gelir": aylik_gelir,
        "aylik_maliyet": aylik_maliyet,
        "aylik_marj": yuvarla(aylik_gelir - aylik_maliyet),
        # Başabaş: tek seferlik maliyeti kaç ayda çıkarır. Aylık marj sıfır
        # veya eksiyse cihaz kendini hiç amorti etmiyor demektir.
        "basabas_ay": (
            int((cihaz_maliyeti + montaj) / (aylik_gelir - aylik_maliyet)) + 1
            if aylik_gelir > aylik_maliyet
            else None
        ),
    }


async def hareketsiz_stok(db: AsyncSession, clock: Clock, *, gun: int = 180) -> list[dict]:
    """Uzun süredir hareket görmemiş stok (brief §4.14)."""
    from app.models import DeviceCustodyHistory, Product

    sinir = clock.now() - timedelta(days=gun)
    satirlar = (
        await db.execute(
            select(Device, Product, DeviceCustodyHistory.valid_from)
            .join(Product, Product.id == Device.product_id)
            .outerjoin(
                DeviceCustodyHistory,
                (DeviceCustodyHistory.device_id == Device.id)
                & (DeviceCustodyHistory.valid_to.is_(None)),
            )
            .where(
                Device.is_deleted.is_(False),
                Device.status.in_(STOKTA_SAYILAN),
                (DeviceCustodyHistory.valid_from < sinir)
                | (DeviceCustodyHistory.valid_from.is_(None)),
            )
            .order_by(DeviceCustodyHistory.valid_from)
        )
    ).all()

    simdi = clock.now()
    return [
        {
            "device_id": c.id,
            "kimlik": c.imei or c.serial_no,
            "urun_kodu": u.code,
            "status": c.status,
            "bekleme_gun": (simdi - baslangic).days if baslangic else None,
            "landed_cost_try": c.landed_cost_try,
        }
        for c, u, baslangic in satirlar
    ]
