"""Planlı bakım raporları ve KPI'ları (E04-18, E04-19, E12-12; TS-185).

**Tek fonksiyon, tek tanım.** Dönem tamamlama raporu `donem_tamamlama`
(sorgusu `donem_tamamlama_sorgusu`) yalnız burada hesaplanır; bakım ekranı,
servis raporları sekmesi (D3-A `GET /raporlar/bakim-tamamlama`) ve Excel aynı
fonksiyonu çağırır — E12 ikinci kopya yazmaz (E12-12 kontrol kararı).

**Sayı = liste.** Her KPI kutusu bir liste süzgecidir: sayısı, tıklanınca
açılan listenin `?kpi=<kod>` ile çağrıldığında kullandığı AYNI sorgudan sayılır
(`kpi_liste_sorgusu`). Yüzde KPI'larda (uyum, uygunsuzluk oranı) liste
PAYDADIR; kutu `pay` ve `payda`yı da döner. Kapsam sorgunun içindedir:
dönemler sözleşme kapsamıyla (`bakim.donem_kapsami`: birim + müşteri), PB
işleri servis işi kapsamıyla (`kapsam.kapsam_isler`) süzülür — başka birimin
dönemi ne sayıda ne listede ne Excel'de görünür.

**Ölçüm kuralları:**
- Dönem satırı = `maintenance_periods`; payda = döneme bağlı PB işleri (iptal
  hariç — `uq_so_pb_cihaz_donem` sayesinde cihaz başına tek iş), pay = Çözüldü
  grubundakiler. Durum `closed_at/closing_kind`'dan; kapanmamışsa "Açık".
  Tamamlanma tarihi dönemin `closed_at`'ı (plan kapanışı), işlerin değil.
- Geciken: kapanmamış ve hedef + `bakim_tolerans_gun` geçmiş (uyarı ve dönem
  listesiyle aynı koşul, `bakim.gecikme_kosulu`).
- Uyum oranı: AKTIF sözleşmede vadesi + toleransı dolmuş YA DA kapanmış
  dönemler paydadır (göç başlangıç kapanışı hariç); pay, toleransı aşmadan
  sayılan bir kapanışla (TAMAMLANDI/KISMI) kapanmış olanlardır.
- Süre kaydı eksik PB: zaman modülünün tek tanımı (`zaman.sure_eksik_ifadesi`).
  Tahmini süre gerçek süre yerine KULLANILMAZ; kayıt yoksa "eksik"tir, 0 değil.
- "Bakım yapıldı, aksiyon açık": formu tamamlanmış ama açık uygunsuzluk aksiyonu
  yüzünden kapanmamış PB (E04 S1 kararı: yönetim taahhüdün fiilen yerine
  getirildiğini görür).
- Onaysız kapanış: çözülmüş PB'de geçerli müşteri onayı yok ya da yalnız
  "Alınamadı" onayı var.

**Para alanı YOKTUR** (sözleşme ücreti, PB maliyeti): bakım raporu yalnız
adet/oran/gün taşır. Saat yalnız `Clock` / `yerel_zaman`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, and_, case, cast, exists, func, literal, not_, or_, select
from sqlalchemy.orm import aliased

from app.models import (
    Account,
    MaintenanceContract,
    MaintenanceExclusionRequest,
    MaintenanceForm,
    MaintenanceNonconformity,
    MaintenancePeriod,
    MaintenanceVisit,
    ServiceApproval,
    ServiceOrder,
)
from app.models.servis_bakim import DONEM_SAYILAN_KAPANISLAR
from app.models.teknik_servis import DURUM_GRUPLARI
from app.permissions import BIRIMLER
from app.services import settings as ayar_svc
from app.services.teknik_servis import bakim, kapsam
from app.services.teknik_servis.yerel_zaman import SAAT_DILIMI, yerel_bugun, yerel_gun

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

_ACIK = sorted(DURUM_GRUPLARI["ACIK"])
_COZULDU = sorted(DURUM_GRUPLARI["COZULDU"])
_KAPALI = sorted(DURUM_GRUPLARI["KAPALI"])
# Rapor aralığı sınırı (E12-08: 24 ay; daha uzunu 400).
AZAMI_AY = 24
# Excel satır sınırı (E12 `servis_rapor_excel_azami_satir` varsayılanı).
EXCEL_AZAMI_SATIR = 50_000
# Açık uygunsuzluk aksiyon yaşı kovaları (gün, üst sınır dahil).
YAS_KOVALARI = (7, 30, 90)
KAPANIS_ADLARI = {
    "TAMAMLANDI": "Tamamlandı",
    "KISMI": "Kısmi",
    "YAPILAMADI": "Yapılamadı",
    "GOC_BASLANGIC": "Göç başlangıcı",
}


class BakimRaporHatasi(ValueError):
    """Rapor parametresi hatası (tarih sırası, 24 ay, bilinmeyen KPI/birim) → 400."""


class BakimRaporYetkiHatasi(PermissionError):
    """Kullanıcının yetkili olmadığı birim istendi → 403."""


# =============================================================================
# KPI tanımları (motor kaydı — E12-08; D3-A defteri bunları okur)
# =============================================================================


@dataclass(frozen=True)
class BakimKpiTanimi:
    """Bakım KPI'sı. `liste` kutuya tıklanınca açılan listenin türüdür:
    `sozlesmeler | donemler | uygunsuzluklar | kapsam-disi` mevcut sekmeler,
    `pb` ve `donem-tamamlama` rapor sekmesindeki listeler."""

    kod: str
    baslik: str
    tanim: str
    birim: str  # adet | yuzde | gun
    liste: str
    yol: str
    adim: int = 1  # E04-18 (1) / E04-19 (2)
    kategori: str = "PLANLI_BAKIM"
    kisisel: bool = False


def _rapor_yolu(kod: str) -> str:
    return f"/bakim?sekme=raporlar&kpi={kod}"


KPI_TANIMLARI: dict[str, BakimKpiTanimi] = {
    t.kod: t
    for t in (
        BakimKpiTanimi(
            "AKTIF_SOZLESME",
            "Aktif Sözleşme",
            "Durumu AKTIF olan bakım sözleşmeleri",
            "adet",
            "sozlesmeler",
            "/bakim?sekme=sozlesmeler&durum=AKTIF",
        ),
        BakimKpiTanimi(
            "TEYIT_BEKLEYEN",
            "Teyit Bekleyen",
            "Tarih/kapsam teyidi bekleyen sözleşmeler",
            "adet",
            "sozlesmeler",
            "/bakim?sekme=sozlesmeler&durum=TEYIT_BEKLIYOR",
        ),
        BakimKpiTanimi(
            "VADESI_GELEN",
            "Vadesi Gelen Dönem",
            "AKTIF sözleşmede hedef tarihi bugün ya da geçmiş, kapanmamış dönemler",
            "adet",
            "donemler",
            "/bakim?sekme=donemler&vadesi_gelen=1",
        ),
        BakimKpiTanimi(
            "GECIKEN_DONEM",
            "Geciken Dönem",
            "AKTIF sözleşmede hedef + tolerans günü geçmiş, kapanmamış dönemler",
            "adet",
            "donemler",
            "/bakim?sekme=donemler&gecikmis=1",
        ),
        BakimKpiTanimi(
            "ACIK_PB",
            "Açık PB",
            "Henüz çözülmemiş ve iptal edilmemiş planlı bakım işleri (cihaz başına)",
            "adet",
            "pb",
            _rapor_yolu("ACIK_PB"),
        ),
        BakimKpiTanimi(
            "TAMAMLANAN_PB",
            "Tamamlanan PB Cihazı",
            "Çözüldü grubundaki (Tamamlandı/Kapatıldı) planlı bakım işleri",
            "adet",
            "pb",
            _rapor_yolu("TAMAMLANAN_PB"),
        ),
        BakimKpiTanimi(
            "UYUM_ORANI",
            "Uyum Oranı (%)",
            "Vadesi ve toleransı dolmuş ya da kapanmış dönemlerden toleransı aşmadan "
            "kapananların oranı (AKTIF sözleşme; göç başlangıcı hariç)",
            "yuzde",
            "donem-tamamlama",
            _rapor_yolu("UYUM_ORANI"),
        ),
        BakimKpiTanimi(
            "SURE_EKSIK_PB",
            "Süre Kaydı Eksik PB",
            "Çözülmüş ama zaman kaydı eksik ya da kısmi planlı bakım işleri "
            "(tahmini süre yerine konmaz)",
            "adet",
            "pb",
            _rapor_yolu("SURE_EKSIK_PB"),
        ),
        BakimKpiTanimi(
            "BAKIM_YAPILDI_AKSIYON_ACIK",
            "Bakım Yapıldı, Aksiyon Açık",
            "Formu tamamlanmış ama açık uygunsuzluk aksiyonu nedeniyle kapanmamış PB işleri",
            "adet",
            "pb",
            _rapor_yolu("BAKIM_YAPILDI_AKSIYON_ACIK"),
        ),
        BakimKpiTanimi(
            "ACIK_UYGUNSUZLUK",
            "Açık Uygunsuzluk",
            "Kapanmamış uygunsuzluk aksiyonları",
            "adet",
            "uygunsuzluklar",
            "/bakim?sekme=uygunsuzluklar&durum=ACIK",
        ),
        BakimKpiTanimi(
            "KAPSAM_DISI_TALEBI",
            "Kapsam Dışı Talebi",
            "Karar bekleyen kapsam dışı talepleri",
            "adet",
            "kapsam-disi",
            "/bakim?sekme=kapsam-disi&durum=TALEP",
        ),
        # --- Adım 2 (E04-19) ---------------------------------------------------
        BakimKpiTanimi(
            "UYGUNSUZLUK_ORANI",
            "Uygunsuzluk Oranı (%)",
            "Bakımı yapılmış (tamamlama ziyareti olan) PB işlerinden en az bir "
            "uygunsuzluk bulunanların oranı",
            "yuzde",
            "pb",
            _rapor_yolu("UYGUNSUZLUK_ORANI"),
            adim=2,
        ),
        BakimKpiTanimi(
            "ONAYSIZ_KAPANIS",
            "Onaysız Kapanış",
            "Çözülmüş PB işlerinden geçerli müşteri onayı olmayan ya da onayı 'Alınamadı' olanlar",
            "adet",
            "pb",
            _rapor_yolu("ONAYSIZ_KAPANIS"),
            adim=2,
        ),
        BakimKpiTanimi(
            "AKSIYON_YASI",
            "Açık Aksiyon Yaşı (gün)",
            "Açık uygunsuzluk aksiyonlarının ortalama yaşı (açılıştan bugüne gün)",
            "gun",
            "uygunsuzluklar",
            "/bakim?sekme=uygunsuzluklar&durum=ACIK",
            adim=2,
        ),
    )
}
PB_KPILERI = tuple(k for k, t in KPI_TANIMLARI.items() if t.liste == "pb")
DONEM_KPILERI = ("UYUM_ORANI",)


# =============================================================================
# Süzgeç
# =============================================================================


@dataclass
class BakimRaporFiltresi:
    """Rapor süzgeci. Tarihler dönemin HEDEF tarihine uygulanır (yerel gün)."""

    baslangic: date | None = None
    bitis: date | None = None
    birim: str | None = None
    sozlesme_id: int | None = None
    musteri_id: int | None = None
    kpi: str | None = None


def filtre_dogrula(f: BakimRaporFiltresi, user: User) -> BakimRaporFiltresi:
    """Girdi kuralları (E12-08 ile aynı): tarih sırası ve 24 ay → 400, katalog
    dışı birim/KPI → 400, yetkisiz birim → 403."""
    if f.baslangic and f.bitis:
        if f.baslangic > f.bitis:
            raise BakimRaporHatasi("Başlangıç tarihi bitişten sonra olamaz")
        ay = (f.bitis.year * 12 + f.bitis.month) - (f.baslangic.year * 12 + f.baslangic.month)
        if ay >= AZAMI_AY:
            raise BakimRaporHatasi(f"Rapor aralığı en çok {AZAMI_AY} ay olabilir")
    if f.birim:
        f.birim = f.birim.strip().upper()
        if f.birim not in BIRIMLER:
            raise BakimRaporHatasi(f"Bilinmeyen birim: {f.birim}")
        if kapsam.birim_disinda_mi(user, f.birim, birimsiz_gorunur=False):
            raise BakimRaporYetkiHatasi("Bu birimin raporunu görme yetkiniz yok")
    if f.kpi and f.kpi not in KPI_TANIMLARI:
        raise BakimRaporHatasi(f"Bilinmeyen bakım KPI'sı: {f.kpi}")
    return f


def _donem_suzgeci(stmt: Select, f: BakimRaporFiltresi) -> Select:
    if f.baslangic:
        stmt = stmt.where(MaintenancePeriod.target_date >= f.baslangic)
    if f.bitis:
        stmt = stmt.where(MaintenancePeriod.target_date <= f.bitis)
    if f.birim:
        stmt = stmt.where(MaintenanceContract.birim == f.birim)
    if f.sozlesme_id is not None:
        stmt = stmt.where(MaintenanceContract.id == f.sozlesme_id)
    if f.musteri_id is not None:
        stmt = stmt.where(MaintenanceContract.account_id == f.musteri_id)
    return stmt


async def tolerans_gun(db: AsyncSession) -> int:
    return int(await ayar_svc.get(db, "bakim_tolerans_gun") or 0)


# =============================================================================
# Dönem tamamlama (E12-12 — tek fonksiyon)
# =============================================================================


def _pb_sayilari():
    """Dönem başına PB sayıları (cihaz başına tek iş)."""
    so = ServiceOrder
    return (
        select(
            so.maintenance_period_id.label("donem_id"),
            func.count().filter(so.status != "IPTAL").label("payda"),
            func.count().filter(so.status.in_(_COZULDU)).label("pay"),
            func.count().filter(so.status == "IPTAL").label("iptal"),
            func.count().filter(so.status.in_(_ACIK)).label("acik"),
        )
        .where(
            so.tur == "PB",
            so.is_deleted.is_(False),
            so.maintenance_period_id.is_not(None),
        )
        .group_by(so.maintenance_period_id)
        .subquery("pb_sayilari")
    )


def degerlendirilen_kosulu(bugun: date, tolerans: int):
    """Uyum paydası: AKTIF sözleşmede kapanmış ya da toleransı dolmuş dönem
    (göç başlangıcı kapanışı hariç)."""
    return and_(
        MaintenanceContract.status == "AKTIF",
        or_(
            MaintenancePeriod.closing_kind.is_(None),
            MaintenancePeriod.closing_kind != "GOC_BASLANGIC",
        ),
        or_(
            MaintenancePeriod.closed_at.is_not(None),
            MaintenancePeriod.target_date < bugun - timedelta(days=tolerans),
        ),
    )


def uyumlu_kosulu(tolerans: int):
    """Uyum payı: sayılan bir kapanışla (TAMAMLANDI/KISMI) ve kapanış Türkiye
    günü hedef + toleransı aşmadan kapanan dönem."""
    kapanis_gunu = cast(func.timezone(SAAT_DILIMI, MaintenancePeriod.closed_at), Date)
    return and_(
        MaintenancePeriod.closed_at.is_not(None),
        MaintenancePeriod.closing_kind.in_(sorted(DONEM_SAYILAN_KAPANISLAR - {"GOC_BASLANGIC"})),
        kapanis_gunu <= MaintenancePeriod.target_date + tolerans,
    )


def donem_tamamlama_sorgusu(
    user: User, f: BakimRaporFiltresi, *, bugun: date, tolerans: int
) -> Select:
    """Dönem tamamlama satırlarının sorgusu (kapsamlı, açık ORDER BY).

    `f.kpi == "UYUM_ORANI"` → uyum paydası (değerlendirilen dönemler).
    """
    pb = _pb_sayilari()
    stmt = (
        select(
            MaintenancePeriod,
            MaintenanceContract.contract_no,
            MaintenanceContract.birim,
            MaintenanceContract.status.label("sozlesme_durumu"),
            Account.title.label("musteri"),
            func.coalesce(pb.c.payda, 0).label("payda"),
            func.coalesce(pb.c.pay, 0).label("pay"),
            func.coalesce(pb.c.iptal, 0).label("iptal"),
            func.coalesce(pb.c.acik, 0).label("acik"),
            case((uyumlu_kosulu(tolerans), literal(True)), else_=literal(False)).label("uyumlu"),
        )
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .outerjoin(Account, Account.id == MaintenanceContract.account_id)
        .outerjoin(pb, pb.c.donem_id == MaintenancePeriod.id)
        .where(
            MaintenancePeriod.is_deleted.is_(False),
            MaintenanceContract.is_deleted.is_(False),
        )
        .order_by(MaintenancePeriod.target_date, MaintenanceContract.contract_no)
    )
    stmt = bakim.donem_kapsami(stmt, user)
    stmt = _donem_suzgeci(stmt, f)
    if f.kpi == "UYUM_ORANI":
        stmt = stmt.where(degerlendirilen_kosulu(bugun, tolerans))
    return stmt


def _yuzde_metni(pay: int, payda: int) -> str | None:
    if not payda:
        return None
    return f"%{100 * pay / payda:.1f}".replace(".", ",")


def donem_satiri(r: Any, *, bugun: date, tolerans: int) -> dict[str, Any]:
    """Sorgu satırı → rapor satırı (ekran, Excel ve servis raporu aynı biçim)."""
    d: MaintenancePeriod = r[0]
    pay, payda = int(r.pay), int(r.payda)
    durum = KAPANIS_ADLARI.get(d.closing_kind, d.closing_kind) if d.closed_at else "Açık"
    oran = round(100 * pay / payda, 1) if payda else None
    yuzde = _yuzde_metni(pay, payda)
    return {
        "donem_id": d.id,
        "contract_id": d.contract_id,
        "contract_no": r.contract_no,
        "musteri": r.musteri,
        "birim": r.birim,
        "sozlesme_durumu": r.sozlesme_durumu,
        "dongu_baslangici": yerel_gun(d.cycle_start).isoformat(),
        "sequence_no": d.sequence_no,
        "target_date": d.target_date.isoformat(),
        "pb_toplam": payda,
        "pb_tamamlanan": pay,
        "pb_acik": int(r.acik),
        "pb_iptal": int(r.iptal),
        "oran": oran,
        "oran_metni": f"{yuzde} ({pay}/{payda}) — {durum}" if yuzde else f"— (0/0) — {durum}",
        "durum": durum,
        "closing_kind": d.closing_kind,
        "tamamlanma_tarihi": yerel_gun(d.closed_at).isoformat() if d.closed_at else None,
        "gecikmis": d.closed_at is None and d.target_date < bugun - timedelta(days=tolerans),
        "uyumlu": bool(r.uyumlu),
    }


async def donem_tamamlama(
    db: AsyncSession, user: User, clock: Clock, f: BakimRaporFiltresi | None = None
) -> dict[str, Any]:
    """Planlı bakım tamamlama raporu (E12-12) — bakım ekranı, servis raporları
    ve Excel bu fonksiyonu çağırır. Sayfalanmamış; liste ucu sayfalı sürümü
    `donem_tamamlama_sorgusu` ile aynı sorgudan üretir."""
    f = filtre_dogrula(f or BakimRaporFiltresi(), user)
    bugun = yerel_bugun(clock)
    tolerans = await tolerans_gun(db)
    satirlar = [
        donem_satiri(r, bugun=bugun, tolerans=tolerans)
        for r in (
            await db.execute(donem_tamamlama_sorgusu(user, f, bugun=bugun, tolerans=tolerans))
        ).all()
    ]
    pay = sum(s["pb_tamamlanan"] for s in satirlar)
    payda = sum(s["pb_toplam"] for s in satirlar)
    return {
        "generated_at": clock.now(),
        "tolerans_gun": tolerans,
        "satirlar": satirlar,
        "toplam": {
            "donem": len(satirlar),
            "acik_donem": sum(1 for s in satirlar if s["durum"] == "Açık"),
            "geciken_donem": sum(1 for s in satirlar if s["gecikmis"]),
            "pb_toplam": payda,
            "pb_tamamlanan": pay,
            "oran": round(100 * pay / payda, 1) if payda else None,
        },
    }


# =============================================================================
# PB işi listeleri (KPI süzgeçleri)
# =============================================================================


def _gecerli_onay_var():
    """Geçerli (geçersiz kılınmamış) ve 'Alınamadı' olmayan müşteri onayı."""
    yeni = aliased(ServiceApproval)
    return exists().where(
        ServiceApproval.service_order_id == ServiceOrder.id,
        ServiceApproval.tur != "ALINAMADI",
        ~exists().where(yeni.gecersiz_kilan_id == ServiceApproval.id),
    )


def _tamamlama_ziyareti_var():
    return exists().where(
        MaintenanceVisit.service_order_id == ServiceOrder.id,
        MaintenanceVisit.tur == "TAMAMLAMA",
    )


def _uygunsuzluk_var(*, yalniz_acik: bool = False):
    kosullar = [
        MaintenanceNonconformity.service_order_id == ServiceOrder.id,
        MaintenanceNonconformity.is_deleted.is_(False),
    ]
    if yalniz_acik:
        kosullar.append(MaintenanceNonconformity.status == "ACIK")
    return exists().where(*kosullar)


def pb_kpi_kosulu(kod: str):
    """PB KPI'sının `service_orders` satır koşulu (sayı ve liste AYNI)."""
    from app.services.teknik_servis import zaman

    if kod == "ACIK_PB":
        return ServiceOrder.status.in_(_ACIK)
    if kod == "TAMAMLANAN_PB":
        return ServiceOrder.status.in_(_COZULDU)
    if kod == "SURE_EKSIK_PB":
        return and_(ServiceOrder.status.in_(_COZULDU), zaman.sure_eksik_ifadesi())
    if kod == "BAKIM_YAPILDI_AKSIYON_ACIK":
        return and_(
            ServiceOrder.status.not_in(_KAPALI),
            exists().where(
                MaintenanceForm.service_order_id == ServiceOrder.id,
                MaintenanceForm.status == "TAMAMLANDI",
                MaintenanceForm.is_deleted.is_(False),
            ),
            _uygunsuzluk_var(yalniz_acik=True),
        )
    if kod == "UYGUNSUZLUK_ORANI":  # payda: bakımı yapılmış PB
        return _tamamlama_ziyareti_var()
    if kod == "ONAYSIZ_KAPANIS":
        return and_(ServiceOrder.status.in_(_COZULDU), not_(_gecerli_onay_var()))
    raise BakimRaporHatasi(f"Bu listede bilinmeyen KPI: {kod}")


def pb_isleri_sorgusu(user: User, f: BakimRaporFiltresi) -> Select:
    """PB işleri (dönem + sözleşme bilgisiyle). `f.kpi` PB KPI'sıysa onun
    süzgeci uygulanır. Kapsam: servis işi kapsamı (`kapsam_isler`)."""
    stmt = (
        select(
            ServiceOrder,
            MaintenancePeriod.target_date,
            MaintenancePeriod.id.label("donem_id"),
            MaintenanceContract.contract_no,
            MaintenanceContract.id.label("contract_id"),
            Account.title.label("musteri"),
            _uygunsuzluk_var().label("uygunsuzluk_var"),
            _gecerli_onay_var().label("onay_var"),
        )
        .join(MaintenancePeriod, MaintenancePeriod.id == ServiceOrder.maintenance_period_id)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .outerjoin(Account, Account.id == ServiceOrder.customer_id)
        .where(ServiceOrder.tur == "PB", ServiceOrder.is_deleted.is_(False))
        .order_by(MaintenancePeriod.target_date, ServiceOrder.so_no)
    )
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    stmt = _donem_suzgeci(stmt, f)
    if f.kpi:
        stmt = stmt.where(pb_kpi_kosulu(f.kpi))
    return stmt


async def pb_satirlari(db: AsyncSession, satirlar: list[Any]) -> list[dict[str, Any]]:
    """PB listesi satırları + süre özeti (tek kaynak `zaman.sure_ozeti_toplu`)."""
    from app.services.teknik_servis import zaman

    ozetler = await zaman.sure_ozeti_toplu(db, [r[0].id for r in satirlar])
    sonuc = []
    for r in satirlar:
        so: ServiceOrder = r[0]
        ozet = ozetler.get(so.id)
        sonuc.append(
            {
                "so_id": so.id,
                "so_no": so.so_no,
                "status": so.status,
                "birim": so.birim,
                "musteri": r.musteri,
                "contract_id": r.contract_id,
                "contract_no": r.contract_no,
                "donem_id": r.donem_id,
                "target_date": r.target_date.isoformat(),
                "completed_at": so.completed_at,
                # Kayıt yoksa None ("eksik"); tahmini süre yerine konmaz.
                "kisi_saat_dk": ozet.kisi_saat_dk if ozet else None,
                "sure_durumu": ozet.sure_durumu if ozet else None,
                "uygunsuzluk_var": bool(r.uygunsuzluk_var),
                "onay_var": bool(r.onay_var),
            }
        )
    return sonuc


# =============================================================================
# KPI değerleri (yönetim özeti kutuları)
# =============================================================================


async def _say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


def _sozlesme_sayisi(user: User, durum: str) -> Select:
    stmt = select(MaintenanceContract.id).where(
        MaintenanceContract.is_deleted.is_(False), MaintenanceContract.status == durum
    )
    return bakim.sozlesme_kapsami(stmt, user)


def _donem_sayisi(user: User) -> Select:
    stmt = (
        select(MaintenancePeriod.id)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .where(
            MaintenancePeriod.is_deleted.is_(False),
            MaintenanceContract.is_deleted.is_(False),
            MaintenanceContract.status == "AKTIF",
        )
    )
    return bakim.donem_kapsami(stmt, user)


def acik_uygunsuzluk_sorgusu(user: User) -> Select:
    """Açık uygunsuzluk aksiyonları (uygunsuzluk listesinin `durum=ACIK` süzgeci)."""
    stmt = select(MaintenanceNonconformity).where(
        MaintenanceNonconformity.status == "ACIK",
        MaintenanceNonconformity.is_deleted.is_(False),
    )
    return kapsam.kapsam_isler(stmt, user, MaintenanceNonconformity.service_order_id)


async def kpi_degerleri(
    db: AsyncSession, user: User, clock: Clock, *, adimlar: tuple[int, ...] = (1, 2)
) -> list[dict[str, Any]]:
    """Kutular: `{kod, baslik, tanim, birim, deger, yol, pay?, payda?}`.

    Adet KPI'larında `deger` = kutunun açtığı listenin `X-Toplam-Kayit`'ı;
    yüzde KPI'larında `payda` = açılan listenin toplamı. Ölçülemeyen yüzde
    (payda 0) `None`'dır — "0" gösterilmez.
    """
    bugun = yerel_bugun(clock)
    tolerans = await tolerans_gun(db)
    kutular: list[dict[str, Any]] = []
    for t in KPI_TANIMLARI.values():
        if t.adim not in adimlar:
            continue
        kutu: dict[str, Any] = {
            "kod": t.kod,
            "baslik": t.baslik,
            "tanim": t.tanim,
            "birim": t.birim,
            "yol": t.yol,
        }
        if t.kod == "AKTIF_SOZLESME":
            kutu["deger"] = await _say(db, _sozlesme_sayisi(user, "AKTIF"))
        elif t.kod == "TEYIT_BEKLEYEN":
            kutu["deger"] = await _say(db, _sozlesme_sayisi(user, "TEYIT_BEKLIYOR"))
        elif t.kod == "VADESI_GELEN":
            kutu["deger"] = await _say(
                db,
                _donem_sayisi(user).where(
                    MaintenancePeriod.closed_at.is_(None), MaintenancePeriod.target_date <= bugun
                ),
            )
        elif t.kod == "GECIKEN_DONEM":
            kutu["deger"] = await _say(
                db, _donem_sayisi(user).where(bakim.gecikme_kosulu(bugun, tolerans))
            )
        elif t.kod == "UYUM_ORANI":
            alt = donem_tamamlama_sorgusu(
                user, BakimRaporFiltresi(kpi="UYUM_ORANI"), bugun=bugun, tolerans=tolerans
            ).subquery()
            payda, pay = (
                await db.execute(select(func.count(), func.count().filter(alt.c.uyumlu)))
            ).one()
            kutu.update(_oran(int(pay or 0), int(payda or 0)))
        elif t.kod == "UYGUNSUZLUK_ORANI":
            alt = pb_isleri_sorgusu(user, BakimRaporFiltresi(kpi="UYGUNSUZLUK_ORANI")).subquery()
            payda, pay = (
                await db.execute(select(func.count(), func.count().filter(alt.c.uygunsuzluk_var)))
            ).one()
            kutu.update(_oran(int(pay or 0), int(payda or 0)))
        elif t.liste == "pb":
            kutu["deger"] = await _say(db, pb_isleri_sorgusu(user, BakimRaporFiltresi(kpi=t.kod)))
        elif t.kod == "ACIK_UYGUNSUZLUK":
            kutu["deger"] = await _say(db, acik_uygunsuzluk_sorgusu(user))
        elif t.kod == "KAPSAM_DISI_TALEBI":
            kutu["deger"] = await _say(
                db,
                kapsam.kapsam_isler(
                    select(MaintenanceExclusionRequest.id).where(
                        MaintenanceExclusionRequest.status == "TALEP",
                        MaintenanceExclusionRequest.is_deleted.is_(False),
                    ),
                    user,
                    MaintenanceExclusionRequest.service_order_id,
                ),
            )
        elif t.kod == "AKSIYON_YASI":
            yas = await aksiyon_yaslari(db, user, clock)
            kutu["deger"] = yas["ortalama_gun"]
            kutu["payda"] = yas["adet"]
        kutular.append(kutu)
    return kutular


def _oran(pay: int, payda: int) -> dict[str, Any]:
    return {
        "deger": round(100 * pay / payda, 1) if payda else None,
        "pay": pay,
        "payda": payda,
    }


# =============================================================================
# Uygunsuzluk analizi (E04-19)
# =============================================================================


async def aksiyon_yaslari(db: AsyncSession, user: User, clock: Clock) -> dict[str, Any]:
    """Açık uygunsuzluk aksiyonlarının yaşı: ortalama, en eski, kovalar.

    Yaş = açılış Türkiye gününden bugüne gün; sayılar açık aksiyon listesinin
    (`durum=ACIK`) aynı kapsamlı sorgusundan.
    """
    bugun = yerel_bugun(clock)
    acik = acik_uygunsuzluk_sorgusu(user).subquery()
    acilis = cast(func.timezone(SAAT_DILIMI, acik.c.created_at), Date)
    yas = literal(bugun, Date) - acilis
    kovalar = []
    alt = 0
    ifadeler = []
    for ust in YAS_KOVALARI:
        ifadeler.append(func.count().filter(and_(yas >= alt, yas <= ust)))
        kovalar.append(f"{alt}-{ust}")
        alt = ust + 1
    ifadeler.append(func.count().filter(yas >= alt))
    kovalar.append(f"{alt}+")
    satir = (await db.execute(select(func.count(), func.avg(yas), func.max(yas), *ifadeler))).one()
    adet = int(satir[0] or 0)
    return {
        "adet": adet,
        "ortalama_gun": round(float(satir[1]), 1) if adet and satir[1] is not None else None,
        "en_eski_gun": int(satir[2]) if adet and satir[2] is not None else None,
        "kovalar": [
            {"kova": k, "adet": int(a or 0)} for k, a in zip(kovalar, satir[3:], strict=True)
        ],
    }


async def en_sik_uygunsuzluklar(
    db: AsyncSession, user: User, f: BakimRaporFiltresi, *, adet: int = 5
) -> list[dict[str, Any]]:
    """En sık uygunsuz bulunan kontrol maddeleri (dönem hedef tarihi süzgeciyle)."""
    stmt = (
        select(
            MaintenanceNonconformity.check_code,
            func.max(MaintenanceNonconformity.check_label).label("madde"),
            func.count().label("adet"),
            func.count().filter(MaintenanceNonconformity.status == "ACIK").label("acik"),
        )
        .join(ServiceOrder, ServiceOrder.id == MaintenanceNonconformity.service_order_id)
        .join(MaintenancePeriod, MaintenancePeriod.id == ServiceOrder.maintenance_period_id)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .where(MaintenanceNonconformity.is_deleted.is_(False))
        .group_by(MaintenanceNonconformity.check_code)
        .order_by(func.count().desc(), MaintenanceNonconformity.check_code)
        .limit(adet)
    )
    stmt = kapsam.kapsam_isler(stmt, user, MaintenanceNonconformity.service_order_id)
    stmt = _donem_suzgeci(stmt, f)
    return [
        {"check_code": r.check_code, "madde": r.madde, "adet": int(r.adet), "acik": int(r.acik)}
        for r in (await db.execute(stmt)).all()
    ]


async def uygunsuzluk_analizi(
    db: AsyncSession, user: User, clock: Clock, f: BakimRaporFiltresi | None = None
) -> dict[str, Any]:
    """KPI adım 2: uygunsuzluk oranı, en sık 5 madde, aksiyon yaşı, onaysız kapanış."""
    f = filtre_dogrula(f or BakimRaporFiltresi(), user)
    oran_f = BakimRaporFiltresi(**{**f.__dict__, "kpi": "UYGUNSUZLUK_ORANI"})
    alt = pb_isleri_sorgusu(user, oran_f).subquery()
    payda, pay = (
        await db.execute(select(func.count(), func.count().filter(alt.c.uygunsuzluk_var)))
    ).one()
    onaysiz_f = BakimRaporFiltresi(**{**f.__dict__, "kpi": "ONAYSIZ_KAPANIS"})
    return {
        "generated_at": clock.now(),
        "uygunsuzluk_orani": _oran(int(pay or 0), int(payda or 0)),
        "en_sik": await en_sik_uygunsuzluklar(db, user, f),
        "aksiyon_yasi": await aksiyon_yaslari(db, user, clock),
        "onaysiz_kapanis": await _say(db, pb_isleri_sorgusu(user, onaysiz_f)),
    }


# =============================================================================
# Excel (E04-18/19) — tek yardımcı `services/export.py` (tipli, formül korumalı)
# =============================================================================


async def excel_sayfalari(
    db: AsyncSession, user: User, clock: Clock, f: BakimRaporFiltresi
) -> tuple[list[Any], int]:
    """Bakım raporu kitabının sayfaları ve toplam satır sayısı.

    Sayfalar ekrandaki AYNI fonksiyonlardan: Dönem Tamamlama, Geciken Dönemler,
    En Sık Uygunsuzluk, Açık Aksiyonlar, Tanımlar. Para kolonu yok. Satır
    sınırı aşılırsa `BakimRaporHatasi` (400, "süzgeci daraltın").
    """
    from app.services import export as export_svc

    S = export_svc.Sutun
    rapor = await donem_tamamlama(db, user, clock, f)
    donemler = rapor["satirlar"]
    if len(donemler) > EXCEL_AZAMI_SATIR:
        raise BakimRaporHatasi(
            f"{len(donemler)} satır var; Excel en çok {EXCEL_AZAMI_SATIR} satır alır. "
            "Süzgeci daraltın."
        )
    donem_sutunlari = [
        S("Sözleşme No"),
        S("Müşteri"),
        S("Birim"),
        S("Döngü Başı", "tarih"),
        S("Dönem Sırası", "tamsayi"),
        S("Hedef Tarih", "tarih"),
        S("PB (cihaz)", "tamsayi"),
        S("Tamamlanan", "tamsayi"),
        S("Açık", "tamsayi"),
        S("İptal", "tamsayi"),
        S("Oran (%)", "ondalik"),
        S("Durum"),
        S("Tamamlanma Tarihi", "tarih"),
        S("Gecikmiş"),
    ]

    def _donem(s: dict[str, Any]) -> list[Any]:
        return [
            s["contract_no"],
            s["musteri"],
            s["birim"],
            date.fromisoformat(s["dongu_baslangici"]),
            s["sequence_no"],
            date.fromisoformat(s["target_date"]),
            s["pb_toplam"],
            s["pb_tamamlanan"],
            s["pb_acik"],
            s["pb_iptal"],
            s["oran"],
            s["durum"],
            date.fromisoformat(s["tamamlanma_tarihi"]) if s["tamamlanma_tarihi"] else None,
            "Evet" if s["gecikmis"] else "Hayır",
        ]

    analiz = await uygunsuzluk_analizi(db, user, clock, f)
    bugun = yerel_bugun(clock)
    aksiyonlar = (
        await db.execute(
            select(
                MaintenanceNonconformity,
                ServiceOrder.so_no,
            )
            .join(ServiceOrder, ServiceOrder.id == MaintenanceNonconformity.service_order_id)
            .where(
                MaintenanceNonconformity.id.in_(
                    acik_uygunsuzluk_sorgusu(user).with_only_columns(MaintenanceNonconformity.id)
                )
            )
            .order_by(MaintenanceNonconformity.created_at, MaintenanceNonconformity.id)
            .limit(EXCEL_AZAMI_SATIR)
        )
    ).all()
    sayfalar = [
        export_svc.Sayfa("Dönem Tamamlama", donem_sutunlari, [_donem(s) for s in donemler]),
        export_svc.Sayfa(
            "Geciken Dönemler",
            donem_sutunlari,
            [_donem(s) for s in donemler if s["gecikmis"]],
        ),
        export_svc.Sayfa(
            "En Sık Uygunsuzluk",
            [S("Madde Kodu"), S("Madde"), S("Adet", "tamsayi"), S("Açık", "tamsayi")],
            [[r["check_code"], r["madde"], r["adet"], r["acik"]] for r in analiz["en_sik"]],
        ),
        export_svc.Sayfa(
            "Açık Aksiyonlar",
            [
                S("PB No"),
                S("Madde"),
                S("Açıklama"),
                S("Aksiyon Türü"),
                S("Hedef Tarih", "tarih"),
                S("Açılış", "tarih"),
                S("Yaş (gün)", "tamsayi"),
            ],
            [
                [
                    so_no,
                    n.check_label,
                    n.description,
                    n.action_type,
                    n.due_date,
                    n.created_at,
                    (bugun - yerel_gun(n.created_at)).days,
                ]
                for n, so_no in aksiyonlar
            ],
        ),
        export_svc.Sayfa(
            "Tanımlar",
            [S("Kod"), S("Gösterge"), S("Tanım"), S("Birim")],
            [[t.kod, t.baslik, t.tanim, t.birim] for t in KPI_TANIMLARI.values()]
            + [
                [
                    "NOT",
                    "Süre",
                    "Süre kaydı olmayan iş 'eksik' sayılır; tahmini süre yerine konmaz.",
                    "",
                ],
                [
                    "NOT",
                    "Tolerans",
                    f"Gecikme ve uyum hedef + {rapor['tolerans_gun']} gün toleransla ölçülür.",
                    "",
                ],
            ],
        ),
    ]
    toplam = sum(len(s.satirlar) for s in sayfalar)
    return sayfalar, toplam


# =============================================================================
# Rapor motoru kaydı (D3-A `rapor_tanimlari.rapor_kpi_kaydet`, E12-08)
# =============================================================================
#
# Servis raporları ekranındaki bakım KPI'ları ikinci bir tanım YAZMAZ: PB
# işi süzgeçleri (`pb_kpi_kosulu`) motorun `/isler?kpi=<kod>&donem=` listesine
# kaydolur. Dönem, PB'nin bağlı olduğu bakım döneminin HEDEF tarihine
# uygulanır (Türkiye günü). Kutu yalnız `bakim.gor` sahibine görünür.

MOTOR_KPILERI: dict[str, tuple[str, str, str]] = {
    # motor kodu: (bakım KPI kodu, başlık, vurgu)
    "rapor_bakim_acik_pb": ("ACIK_PB", "Açık PB", "normal"),
    "rapor_bakim_tamamlanan_pb": ("TAMAMLANAN_PB", "Tamamlanan PB cihazı", "normal"),
    "rapor_bakim_sure_eksik_pb": ("SURE_EKSIK_PB", "Süre kaydı eksik PB", "uyari"),
    "rapor_bakim_aksiyon_acik": (
        "BAKIM_YAPILDI_AKSIYON_ACIK",
        "Bakım yapıldı, aksiyon açık",
        "uyari",
    ),
    "rapor_bakim_bakimi_yapilan": (
        "UYGUNSUZLUK_ORANI",
        "Bakımı yapılmış PB (uygunsuzluk oranı paydası)",
        "normal",
    ),
    "rapor_bakim_onaysiz_kapanis": ("ONAYSIZ_KAPANIS", "Onaysız PB kapanışı", "uyari"),
}


def _motor_suzgeci(bakim_kodu: str):
    from app.services.teknik_servis import panel

    def _s(stmt, user=None, clock=None, donem=None):
        if clock is None and not (donem and panel.ARALIK_KALIBI.match(donem)):
            raise panel.PanelHatasi("Bu KPI saate bağlı; clock verilmeli")
        bas, bit = panel.donem_araligi(donem, clock)
        donemler = select(MaintenancePeriod.id).where(
            MaintenancePeriod.is_deleted.is_(False),
            MaintenancePeriod.target_date >= yerel_gun(bas),
            MaintenancePeriod.target_date < yerel_gun(bit),
        )
        return stmt.where(
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.tur == "PB",
            ServiceOrder.maintenance_period_id.in_(donemler),
            pb_kpi_kosulu(bakim_kodu),
        )

    return _s


def _motora_kaydet() -> None:
    from app.services.teknik_servis import panel, rapor_tanimlari

    kaydet = getattr(rapor_tanimlari, "rapor_kpi_kaydet", None)
    if kaydet is None:  # pragma: no cover - D3-A defteri yoksa (iskelet) kayıt yok
        return
    for motor_kodu, (bakim_kodu, baslik, vurgu) in MOTOR_KPILERI.items():
        if motor_kodu in panel.KPI_TANIMLARI:
            continue
        kaydet(
            panel.KpiTanimi(
                motor_kodu,
                baslik,
                KPI_TANIMLARI[bakim_kodu].tanim
                + " Dönem, bakım döneminin hedef tarihine uygulanır.",
                _motor_suzgeci(bakim_kodu),
                izin="bakim.gor",
                grup="RAPOR",
                donemsel=True,
                vurgu=vurgu,
            ),
            "BAKIM",
        )


_motora_kaydet()


__all__ = [
    "AZAMI_AY",
    "DONEM_KPILERI",
    "EXCEL_AZAMI_SATIR",
    "KPI_TANIMLARI",
    "PB_KPILERI",
    "BakimKpiTanimi",
    "BakimRaporFiltresi",
    "BakimRaporHatasi",
    "BakimRaporYetkiHatasi",
    "aksiyon_yaslari",
    "donem_satiri",
    "donem_tamamlama",
    "donem_tamamlama_sorgusu",
    "en_sik_uygunsuzluklar",
    "excel_sayfalari",
    "filtre_dogrula",
    "kpi_degerleri",
    "pb_isleri_sorgusu",
    "pb_kpi_kosulu",
    "pb_satirlari",
    "uygunsuzluk_analizi",
]
