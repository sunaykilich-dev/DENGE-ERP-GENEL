"""Rapor hesapları: kişi-saat, süre hareketleri, SLA/bekleme, tekrar arıza,
yeniden açılan (E12-05, E12-13…15, E09-14).

Maddeler: TS-186, TS-187 (D3-A), TS-189 kişi-saat ortak fonksiyonu (D3-B
çağırır: `kisi_saat_toplami`, `kisi_saat_personel`, `sure_hareketleri` —
imzalar sabit). Doldurur: D3-A.

**Kişi-saat** yalnız gerçek zaman kayıtlarından: iptal edilmemiş, KAPALI
(`ended_at` dolu), `KISI_SAATE_DAHIL` faaliyetli (mola hariç) bölümler; süre
kayıtları iş tarihine değil **faaliyet başlangıcına** göre süzülür (eski R-92).
Kayıt yoksa değer `None` ("eksik"), 0 DEĞİL; tahmini süre (plan süresi)
hiçbir hesapta gerçek süre yerine kullanılmaz. Göçten gelen ve kullanıcıyla
eşleşmemiş kayıtlar "Eşleşmemiş: <ad>" satırındadır (E12-D03).

**SLA** yalnız GUNLUK_SERVIS; E10 alanları okunur, hesaplanmaz (`sla_sonuc`,
`gecikme_nedeni`, `sla_durdurulan_dk`, `cozum_hedef_at`). Ölçülemedi ve
damgasız paydada yok, ayrı satır. "Geciken açık" Operasyon Merkezi'nin
`sla_asildi` KPI'sının AYNISIDIR (anlık). CSV açılmaz.

**Tekrar arıza** onaylı oranı kök neden teyidinden (`AYNI_ARIZA`), aday ayrı
etiket; yeniden açılan iş tekrar arıza sayılmaz (bağ kullanılır, olay değil).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, distinct, func, select

from app.models import (
    Account,
    Address,
    ServiceHold,
    ServiceHoldReason,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServiceTimeEntry,
    User,
)
from app.models.teknik_servis import GECIKME_NEDENLERI, KISI_SAATE_DAHIL, ZAMAN_FAALIYETLERI
from app.permissions import BIRIMLER
from app.services import settings as ayarlar
from app.services.normalize import il_normalize
from app.services.teknik_servis import kapsam, panel
from app.services.teknik_servis import rapor_motoru as rm
from app.services.teknik_servis import rapor_tanimlari as rt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

KISI_FAALIYETLERI = tuple(f for f in ZAMAN_FAALIYETLERI if f in KISI_SAATE_DAHIL)
GECIKME_NEDENI_ADLARI = {
    "MALZEME_TEDARIK": "Malzeme tedariki",
    "MUSTERI_KAYNAKLI": "Müşteri kaynaklı",
    "ULASIM": "Ulaşım",
    "PERSONEL_YETERSIZ": "Personel yetersiz",
    "YOGUNLUK": "Yoğunluk",
    "TEKNIK_ZORLUK": "Teknik zorluk",
    "DIGER": "Diğer",
}
# Ad tablosu = `GECIKME_NEDENLERI` (tek sözlük; `t/unit/test_servis_rapor_tanimlari.py`).
GECIKME_KODLARI = GECIKME_NEDENLERI


def _saniye():
    return func.extract("epoch", ServiceTimeEntry.ended_at - ServiceTimeEntry.started_at)


def _saat(sn) -> float | None:
    return round(float(sn) / 3600.0, 2) if sn is not None else None


def personel_izni(user: User) -> None:
    if not user.has("servis_rapor.personel"):
        raise rm.RaporYetkiHatasi("Kişi bazlı süre için yetkiniz yok (servis_rapor.personel)")


# --- Kişi-saat (TS-189 ortak) ---------------------------------------------------------------


def sure_sorgusu(user: User, f: rm.RaporFiltresi, *secim) -> Select:
    """Kişi-saate dahil, geçerli, kapalı bölümler: başlangıcı dönemde, işi
    rapor süzgecinde ve kapsamda. `teknisyen_id` süzgeci kişinin KENDİ
    kayıtlarına uygulanır."""
    bas, bit = f.aralik
    stmt = select(*(secim or (ServiceTimeEntry.id,))).where(
        ServiceTimeEntry.is_deleted.is_(False),
        ServiceTimeEntry.ended_at.is_not(None),
        ServiceTimeEntry.faaliyet.in_(KISI_FAALIYETLERI),
        ServiceTimeEntry.started_at >= bas,
        ServiceTimeEntry.started_at < bit,
        ServiceTimeEntry.service_order_id.in_(rm.temel_kimlikler(user, f)),
    )
    if f.teknisyen_id is not None:
        stmt = stmt.where(ServiceTimeEntry.user_id == f.teknisyen_id)
    return stmt


async def kisi_saat_toplami(db: AsyncSession, user: User, f: rm.RaporFiltresi) -> dict[str, Any]:
    """Toplam kişi-saat ve faaliyet kırılımı (kişisel DEĞİL: toplamdır).

    Kayıt yoksa `toplam_saat=None` — ekranda "—", Excel'de boş hücre."""
    satirlar = (
        await db.execute(
            sure_sorgusu(
                user,
                f,
                ServiceTimeEntry.faaliyet,
                func.sum(_saniye()),
                func.count(ServiceTimeEntry.id),
            ).group_by(ServiceTimeEntry.faaliyet)
        )
    ).all()
    farkli_is = await db.scalar(
        select(func.count(distinct(ServiceTimeEntry.service_order_id))).where(
            ServiceTimeEntry.id.in_(sure_sorgusu(user, f))
        )
    )
    toplam = sum(float(sn) for _, sn, _ in satirlar) if satirlar else None
    return {
        "toplam_saat": _saat(toplam),
        "faaliyet": {fa: _saat(sn) for fa, sn, _ in satirlar},
        "kayit": sum(int(a) for _, _, a in satirlar),
        "farkli_is": int(farkli_is or 0),
    }


async def kisi_saat_personel(
    db: AsyncSession, user: User, f: rm.RaporFiltresi
) -> list[dict[str, Any]]:
    """Teknisyen × faaliyet kişi-saat (KİŞİSEL — `servis_rapor.personel`).

    Satırlar: süre kaydı olanlar (göç eşleşmemişler "Eşleşmemiş: ad") ∪ detay
    kümesindeki işlere atanmış ama dönemde hiç kaydı olmayan teknisyenler
    (`kisi_saat=None`, not "Süre kaydı yok"). Toplam saate göre azalan.
    """
    personel_izni(user)
    gruplar = (
        await db.execute(
            sure_sorgusu(
                user,
                f,
                ServiceTimeEntry.user_id,
                ServiceTimeEntry.kaynak_personel_adi,
                ServiceTimeEntry.faaliyet,
                func.sum(_saniye()),
                func.count(ServiceTimeEntry.id),
            ).group_by(
                ServiceTimeEntry.user_id,
                ServiceTimeEntry.kaynak_personel_adi,
                ServiceTimeEntry.faaliyet,
            )
        )
    ).all()
    is_sayilari = dict(
        (
            await db.execute(
                sure_sorgusu(
                    user,
                    f,
                    ServiceTimeEntry.user_id,
                    func.count(distinct(ServiceTimeEntry.service_order_id)),
                )
                .where(ServiceTimeEntry.user_id.is_not(None))
                .group_by(ServiceTimeEntry.user_id)
            )
        ).all()
    )
    kisiler: dict[Any, dict[str, Any]] = {}
    for uid, ham_ad, faaliyet, sn, adet in gruplar:
        anahtar = uid if uid is not None else f"E:{(ham_ad or '').strip().upper()}"
        satir = kisiler.setdefault(
            anahtar,
            {
                "user_id": uid,
                "ham_ad": ham_ad,
                "sn": 0.0,
                "kayit": 0,
                **dict.fromkeys(KISI_FAALIYETLERI),
            },
        )
        satir["sn"] += float(sn or 0)
        satir["kayit"] += int(adet)
        satir[faaliyet] = round((satir[faaliyet] or 0) + float(sn or 0) / 3600.0, 2)
    # Atanmış ama kaydı olmayan teknisyenler ("eksik").
    atananlar = set(
        (
            await db.scalars(
                select(ServiceOrderAssignment.user_id)
                .where(
                    ServiceOrderAssignment.rol == "TEKNISYEN",
                    ServiceOrderAssignment.service_order_id.in_(rm.detay_sorgusu(user, f)),
                )
                .distinct()
            )
        ).all()
    )
    if f.teknisyen_id is not None:
        atananlar &= {f.teknisyen_id}
    adlar = dict(
        (
            await db.execute(
                select(User.id, User.full_name).where(
                    User.id.in_({k for k in kisiler if isinstance(k, int)} | atananlar or {0})
                )
            )
        ).all()
    )
    sonuc = []
    for s in kisiler.values():
        sonuc.append(
            {
                "user_id": s["user_id"],
                "personel": adlar.get(s["user_id"], "?")
                if s["user_id"] is not None
                else f"Eşleşmemiş: {(s['ham_ad'] or '').strip()}",
                "kisi_saat": _saat(s["sn"]),
                "farkli_is": int(is_sayilari.get(s["user_id"], 0))
                if s["user_id"] is not None
                else None,
                "kayit": s["kayit"],
                **{fa: s[fa] for fa in KISI_FAALIYETLERI},
                "not": None,
            }
        )
    for uid in sorted(atananlar - {k for k in kisiler if isinstance(k, int)}):
        sonuc.append(
            {
                "user_id": uid,
                "personel": adlar.get(uid, "?"),
                "kisi_saat": None,
                "farkli_is": 0,
                "kayit": 0,
                **dict.fromkeys(KISI_FAALIYETLERI),
                "not": "Süre kaydı yok (eksik)",
            }
        )
    sonuc.sort(key=lambda r: (-(r["kisi_saat"] or -1), r["personel"]))
    return sonuc


async def sure_hareketleri(
    db: AsyncSession,
    user: User,
    f: rm.RaporFiltresi,
    *,
    limit: int | None = rt.JSON_AZAMI_SATIR,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Ham süre satırları (KİŞİSEL). JSON uçta sayfalı (en çok 200); Excel'de
    `limit=None` ile `EXCEL_AZAMI_SATIR` sınırı çağıranda uygulanır."""
    personel_izni(user)
    kimlikler = sure_sorgusu(user, f)
    toplam = await rm.say(db, kimlikler)
    stmt = (
        select(ServiceTimeEntry, ServiceOrder, User.full_name, Address, Account.title)
        .join(ServiceOrder, ServiceOrder.id == ServiceTimeEntry.service_order_id)
        .outerjoin(User, User.id == ServiceTimeEntry.user_id)
        .outerjoin(Address, Address.id == ServiceOrder.address_id)
        .outerjoin(Account, Account.id == ServiceOrder.customer_id)
        .where(ServiceTimeEntry.id.in_(kimlikler))
        .order_by(ServiceTimeEntry.started_at, ServiceTimeEntry.id)
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    from app.services.teknik_servis import is_emirleri, zaman

    satirlar = []
    for bolum, so, ad, adres, musteri in (await db.execute(stmt)).all():
        sn = (bolum.ended_at - bolum.started_at).total_seconds()
        satirlar.append(
            {
                "id": bolum.id,
                "so_no": so.so_no,
                "kategori": is_emirleri.KATEGORI_ADLARI.get(so.kategori, so.kategori),
                "birim": BIRIMLER.get(so.birim, so.birim),
                "personel": ad or f"Eşleşmemiş: {bolum.kaynak_personel_adi or ''}".strip(),
                "musteri": musteri or so.customer_name_raw,
                "sehir": (il_normalize(adres.city) or adres.city) if adres else None,
                "lokasyon": (adres.site_name or adres.label) if adres else so.location_raw,
                "faaliyet": zaman.FAALIYET_ADLARI.get(bolum.faaliyet, bolum.faaliyet),
                "baslangic": bolum.started_at,
                "bitis": bolum.ended_at,
                "sure_dk": round(sn / 60),
                "saat": round(sn / 3600.0, 2),
                "konum_notu": bolum.konum_notu,
                "aciklama": bolum.aciklama,
                "kaynak": bolum.kaynak,
            }
        )
    return satirlar, toplam


# --- Çözüm süresi ve SLA (TS-186) ---------------------------------------------------------------


def _sla_kumesi(user: User, clock: Clock, f: rm.RaporFiltresi) -> Select:
    """İlk çözümü dönemde olan, iptal edilmemiş günlük servis işleri (kapsamlı)."""
    bas, bit = f.aralik
    stmt = rm.filtre_uygula(select(ServiceOrder.id), f).where(
        ServiceOrder.kategori == rt.SLA_KATEGORISI,
        ServiceOrder.status != "IPTAL",
        ServiceOrder.first_completed_at >= bas,
        ServiceOrder.first_completed_at < bit,
    )
    return kapsam.kapsam_isler(stmt, user, ServiceOrder.id)


async def cozum_suresi(
    db: AsyncSession, user: User, clock: Clock, f: rm.RaporFiltresi
) -> dict[str, Any]:
    """Günlük servis çözüm süresi (saat): bildirim (yoksa SLA başlangıcı, yoksa
    açılış) → ilk çözüm, SLA'yı durduran bekleme düşülür. İş yoksa None."""
    baslangic = func.coalesce(
        ServiceOrder.reported_at, ServiceOrder.sla_baslangic_at, ServiceOrder.created_at
    )
    sure = (
        func.extract("epoch", ServiceOrder.first_completed_at - baslangic) / 3600.0
        - func.coalesce(ServiceOrder.sla_durdurulan_dk, 0) / 60.0
    )
    ort, medyan, adet = (
        await db.execute(
            select(
                func.avg(sure),
                func.percentile_cont(0.5).within_group(sure),
                func.count(),
            ).where(ServiceOrder.id.in_(_sla_kumesi(user, clock, f)))
        )
    ).one()
    return {
        "ortalama_saat": round(float(ort), 1) if adet and ort is not None else None,
        "medyan_saat": round(float(medyan), 1) if adet and medyan is not None else None,
        "olculen": int(adet or 0),
    }


_SLA_KODLARI = (
    "rapor_sla_zamaninda",
    "rapor_sla_asildi",
    "rapor_sla_olculemedi",
    "rapor_sla_damgasiz",
)


async def sla_raporu(
    db: AsyncSession, user: User, clock: Clock, f: rm.RaporFiltresi
) -> dict[str, Any]:
    """SLA ve bekleme raporu (yalnız GUNLUK_SERVIS)."""
    sayilar = {}
    kpiler = []
    for kod in _SLA_KODLARI:
        tanim = panel.KPI_TANIMLARI[kod]
        sayilar[kod] = await rm.kpi_sayisi(db, tanim, user, clock, f)
        kpiler.append(
            {
                "kod": kod,
                "baslik": tanim.baslik,
                "tanim": tanim.tanim,
                "deger": sayilar[kod],
                "kpi": kod,
                "isler_yolu": rm.isler_yolu(kod, f),
            }
        )
    zamaninda, asildi = sayilar["rapor_sla_zamaninda"], sayilar["rapor_sla_asildi"]
    geciken = panel.KPI_TANIMLARI.get("sla_asildi")
    # Operasyon Merkezi'nin "SLA aşıldı" sayacıyla AYNI süzgeç (anlık; dönemden
    # bağımsız) — panel/operasyon ile rapor aynı veride aynı sayıyı verir.
    geciken_acik = None
    if geciken is not None:
        geciken_acik = await rm.say(db, rm.kpi_sorgusu(geciken, user, clock, f))
    asilan = rm.kpi_sorgusu(panel.KPI_TANIMLARI["rapor_sla_asildi"], user, clock, f)
    nedenler = dict(
        (
            await db.execute(
                select(ServiceOrder.gecikme_nedeni, func.count())
                .where(ServiceOrder.id.in_(asilan))
                .group_by(ServiceOrder.gecikme_nedeni)
            )
        ).all()
    )
    oncelik_satirlari = []
    for oncelik in ("KRITIK", "YUKSEK", "NORMAL"):
        satir: dict[str, Any] = {"oncelik": oncelik, "ad": rm.ONCELIK_ADLARI[oncelik]}
        for kod in _SLA_KODLARI:
            stmt = rm.kpi_sorgusu(panel.KPI_TANIMLARI[kod], user, clock, f).where(
                ServiceOrder.oncelik == oncelik
            )
            satir[kod.removeprefix("rapor_sla_")] = await rm.say(db, stmt)
        satir["uyum_yuzde"] = rm._oran(satir["zamaninda"], satir["zamaninda"] + satir["asildi"])
        oncelik_satirlari.append(satir)
    return {
        "kpiler": kpiler,
        "uyum_yuzde": rm._oran(zamaninda, zamaninda + asildi),
        "olculen": zamaninda + asildi,
        "geciken_acik": geciken_acik,
        "geciken_acik_kpi": "sla_asildi" if geciken is not None else None,
        "cozum_suresi": await cozum_suresi(db, user, clock, f),
        "gecikme_nedenleri": [
            {"kod": k, "ad": GECIKME_NEDENI_ADLARI.get(k, k) if k else "Girilmemiş", "adet": int(a)}
            for k, a in sorted(nedenler.items(), key=lambda x: -x[1])
        ],
        "oncelik_kirilimi": oncelik_satirlari,
        "bekleme_nedenleri": await bekleme_nedenleri(db, user, clock, f),
        "generated_at": clock.now(),
        "kapsam": rm.kapsam_metni(user),
    }


async def bekleme_nedenleri(
    db: AsyncSession, user: User, clock: Clock, f: rm.RaporFiltresi
) -> list[dict[str, Any]]:
    """Dönemde BAŞLAYAN iş beklemeleri (günlük servis): adet ve toplam saat
    (bitmemiş bekleme rapor anına kadar sayılır); SLA'yı durdurup durdurmadığı."""
    bas, bit = f.aralik
    isler = rm.temel_kimlikler(user, f).where(ServiceOrder.kategori == rt.SLA_KATEGORISI)
    bitis = func.coalesce(ServiceHold.released_at, clock.now())
    satirlar = (
        await db.execute(
            select(
                ServiceHold.neden,
                func.count(),
                func.sum(func.extract("epoch", bitis - ServiceHold.started_at)),
                func.bool_or(ServiceHold.sla_durdurur),
            )
            .where(
                ServiceHold.started_at >= bas,
                ServiceHold.started_at < bit,
                ServiceHold.service_order_id.in_(isler),
            )
            .group_by(ServiceHold.neden)
        )
    ).all()
    adlar = dict((await db.execute(select(ServiceHoldReason.kod, ServiceHoldReason.ad))).all())
    return sorted(
        (
            {
                "kod": neden,
                "ad": adlar.get(neden, neden),
                "adet": int(adet),
                "toplam_saat": _saat(sn),
                "sla_durdurur": bool(durdurur),
            }
            for neden, adet, sn, durdurur in satirlar
        ),
        key=lambda r: -r["adet"],
    )


# --- Tekrar arıza / ziyaret (TS-187) --------------------------------------------------------------


async def tekrar_gun(db: AsyncSession, f: rm.RaporFiltresi) -> int:
    if f.tekrar_gun is not None:
        return f.tekrar_gun
    return int(await ayarlar.get(db, "servis_tekrar_ariza_gun") or 30)


async def tekrar_ariza_raporu(
    db: AsyncSession, user: User, clock: Clock, f: rm.RaporFiltresi
) -> dict[str, Any]:
    """Onaylı oran (teyit AYNI_ARIZA) + onaysız aday satırı + tekrar ziyaret."""
    sayilar: dict[str, int] = {}
    for kod in (
        "rapor_tekrar_payda",
        "rapor_tekrar_ariza_onayli",
        "rapor_tekrar_ariza_aday",
        "rapor_tekrar_ziyaret",
        "rapor_ziyaret_kaydi_yok",
    ):
        sayilar[kod] = await rm.kpi_sayisi(db, panel.KPI_TANIMLARI[kod], user, clock, f)
    payda = sayilar["rapor_tekrar_payda"]
    satirlar = []
    for kod, etiket in (
        ("rapor_tekrar_ariza_onayli", "Onaylı (aynı arıza)"),
        ("rapor_tekrar_ariza_aday", "Aday (onaysız)"),
    ):
        stmt = rm.kpi_sorgusu(panel.KPI_TANIMLARI[kod], user, clock, f, ServiceOrder)
        for so in (
            await db.scalars(stmt.order_by(ServiceOrder.completed_at).limit(rt.JSON_AZAMI_SATIR))
        ).all():
            satirlar.append({"so": so, "etiket": etiket})
    sonrakiler = await _sonraki_isler(db, user, [s["so"].id for s in satirlar])
    from app.services.teknik_servis import is_emirleri

    return {
        "gun": await tekrar_gun(db, f),
        "kpiler": [
            {
                "kod": kod,
                "baslik": panel.KPI_TANIMLARI[kod].baslik,
                "tanim": panel.KPI_TANIMLARI[kod].tanim,
                "deger": deger,
                "kpi": kod,
                "isler_yolu": rm.isler_yolu(kod, f),
            }
            for kod, deger in sayilar.items()
        ],
        "onayli_oran": rm._oran(sayilar["rapor_tekrar_ariza_onayli"], payda),
        "aday_oran": rm._oran(sayilar["rapor_tekrar_ariza_aday"], payda),
        "satirlar": [
            {
                "id": s["so"].id,
                "so_no": s["so"].so_no,
                "birim": BIRIMLER.get(s["so"].birim, s["so"].birim),
                "kategori": is_emirleri.KATEGORI_ADLARI.get(s["so"].kategori, s["so"].kategori),
                "cozum": s["so"].completed_at,
                "etiket": s["etiket"],
                "sonraki_isler": sonrakiler.get(s["so"].id, []),
            }
            for s in satirlar
        ],
        "generated_at": clock.now(),
        "kapsam": rm.kapsam_metni(user),
    }


async def _sonraki_isler(db: AsyncSession, user: User, idler: list[int]) -> dict[int, list[str]]:
    """Tekrar arıza işinin numarası — kapsam dışındaysa numara verilmez."""
    if not idler:
        return {}
    stmt = select(ServiceOrder.id, ServiceOrder.iliskili_is_id, ServiceOrder.so_no).where(
        ServiceOrder.iliskili_is_id.in_(idler),
        ServiceOrder.is_deleted.is_(False),
        (ServiceOrder.iliski_turu == "TEKRAR_ARIZA") | ServiceOrder.tekrar_ariza_aday.is_(True),
    )
    gorunur = set(
        (
            await db.scalars(
                kapsam.kapsam_isler(
                    select(ServiceOrder.id).where(ServiceOrder.iliskili_is_id.in_(idler)),
                    user,
                    ServiceOrder.id,
                )
            )
        ).all()
    )
    sonuc: dict[int, list[str]] = defaultdict(list)
    for kimlik, ana, no in (await db.execute(stmt.order_by(ServiceOrder.id))).all():
        sonuc[ana].append(no if kimlik in gorunur else "Kapsam dışı iş")
    return sonuc


# --- Yeniden açılan (E12-15) ---------------------------------------------------------------------


def _gerekce(ozet: str) -> str | None:
    _, ayrac, gerekce = ozet.partition("— gerekçe:")
    return gerekce.strip() or None if ayrac else None


async def yeniden_acilan_raporu(
    db: AsyncSession,
    user: User,
    clock: Clock,
    f: rm.RaporFiltresi,
    *,
    limit: int | None = rt.JSON_AZAMI_SATIR,
) -> dict[str, Any]:
    """Sayı = iş (bir iş iki kez açılsa bir); liste = olay (iki satır). PB ayrı."""
    sayilar = {
        kod: await rm.kpi_sayisi(db, panel.KPI_TANIMLARI[kod], user, clock, f)
        for kod in ("rapor_ilk_cozulen", "rapor_yeniden_acilan", "rapor_yeniden_acilan_pb")
    }
    bas, bit = f.aralik
    olay_sorgusu = (
        select(ServiceOrderEvent, ServiceOrder)
        .join(ServiceOrder, ServiceOrder.id == ServiceOrderEvent.service_order_id)
        .where(
            ServiceOrderEvent.olay_turu == "DURUM",
            ServiceOrderEvent.yeni_durum == "TEKRAR_ACILDI",
            ServiceOrderEvent.olusma_zamani >= bas,
            ServiceOrderEvent.olusma_zamani < bit,
            ServiceOrderEvent.service_order_id.in_(rm.temel_kimlikler(user, f)),
        )
        .order_by(ServiceOrderEvent.olusma_zamani, ServiceOrderEvent.id)
    )
    olay_sayisi = await rm.say(db, olay_sorgusu.with_only_columns(ServiceOrderEvent.id))
    if limit is not None:
        olay_sorgusu = olay_sorgusu.limit(limit)
    from app.services.teknik_servis import is_emirleri

    olaylar = []
    for olay, so in (await db.execute(olay_sorgusu)).all():
        ilk = so.first_completed_at
        olaylar.append(
            {
                "id": so.id,
                "so_no": so.so_no,
                "kategori": is_emirleri.KATEGORI_ADLARI.get(so.kategori, so.kategori),
                "pb": so.tur == "PB",
                "ilk_cozum": ilk,
                "yeniden_acilis": olay.olusma_zamani,
                "gun_farki": (olay.olusma_zamani - ilk).days if ilk is not None else None,
                "gerekce": _gerekce(olay.ozet),
            }
        )
    return {
        "ilk_cozulen": sayilar["rapor_ilk_cozulen"],
        "yeniden_acilan": sayilar["rapor_yeniden_acilan"],
        "yeniden_acilan_pb": sayilar["rapor_yeniden_acilan_pb"],
        "oran": rm._oran(sayilar["rapor_yeniden_acilan"], sayilar["rapor_ilk_cozulen"]),
        "olay_sayisi": olay_sayisi,
        "olaylar": olaylar,
        "generated_at": clock.now(),
        "kapsam": rm.kapsam_metni(user),
    }


__all__ = [
    "bekleme_nedenleri",
    "cozum_suresi",
    "kisi_saat_personel",
    "kisi_saat_toplami",
    "sla_raporu",
    "sure_hareketleri",
    "sure_sorgusu",
    "tekrar_ariza_raporu",
    "yeniden_acilan_raporu",
]
