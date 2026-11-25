"""Ana Panel (master dashboard) — KARARLAR 2026-11-04 §4.

Launchpad'in yerini alan ana sayfanın TEK veri kaynağı: KPI kartları, birim
bazında canlı operasyon özeti, aktif işler, canlı ekip durumu, birimler arası
bekleyen aksiyonlar ve grafikler. Ayrı bir sayım katmanı YOKTUR:

**Sayı = liste.** Tıklanabilir her sayı (KPI kartı, birim kartındaki sayılar,
grafik dilimleri) `is_emirleri.liste_sorgusu` ile, tıklanınca açılan
`/servis-isleri?...` listesinin `ListeFiltresi`'nin AYNISIYLA hesaplanır
(`_parametreler` → hem `ListeFiltresi` hem `liste_yolu`). Liste ucu da aynı
fonksiyonu çağırdığı için kart "12" deyip liste 9 satır gösteremez. KPI
süzgeçleri `panel.KPI_TANIMLARI` kaydından gelir; mevcut tanımı olanlar
(`acik`, `bakim_bu_ay_planli`, `kritik_acik`, `beklemede`) aynen kullanılır,
yalnız iki birleşik kutu bu kayda eklenir (`sla_riskli`, `onay_bekleyen`;
grup `ANA_PANEL` → Servis Paneli'nde ikinci kez çizilmez).

**Kapsam:** her iş sayısı/listesi `liste_sorgusu` → `kapsam.kapsam_isler`;
personel `kapsam.kapsam_personel`; görünür birimler `kapsam.birim_disinda_mi`.
Bu modül kendi birim süzgecini YAZMAZ: kapsam.py'ye eklenen "etkin şirket"
kesişimi buraya kendiliğinden yansır. Para/maliyet alanı DÖNMEZ (fatura devri
yalnız "bekleyen işaret" olarak, tutarsız gelir).

**Süzgeçler** → liste parametreleri: `birim`, `durum_grubu`, `personel_id` →
`teknisyen_id` (aktif tayin), `sef_id` → `sef_id` (aktif ŞEF tayini),
`lokasyon_id` → `adres_id`. `bas`/`bit` iş açılış tarihini süzmez, **dönemi**
belirler (`panel` rapor dönemi `YYYYAAGG-YYYYAAGG`): anlık kutular (açık iş,
askıdaki iş ...) dönemden bağımsızdır; dönem tamamlanan iş, dönemde açılan iş
ve karşılaştırma başlangıcı için kullanılır. Varsayılan: bu ayın 1'i → bugün.

**Önceki değer (varsayım, gerekçe):** durum geçmişi anlık sayı olarak
saklanmadığından açık/kritik/POC kutularında önceki değer, dönem başında açık
olan işlerin zaman damgalarından (`created_at` < dönem başı ve kapanış/iptal
anı dönem başından sonra ya da yok) yeniden kurulur; askıdaki kayıtlarda
dönem başında süren bekleme kayıtlarından. Planlı bakımda karşılaştırma
"hedefe göre"dir (bu aya hedef tarihi düşen PB işleri). SLA riski, bekleyen
onay ve sahadaki ekip için geçmiş anlık durum bilinmez → `None` ("0" değil).
Durum grubu süzgeci seçiliyken geçmiş durum bilinmediğinden önceki değer
verilmez.

**Sahadaki ekip:** aktif = açık (bitmemiş, iptal edilmemiş) zaman kaydı olan
saha personeli; GPS yok (Faz D). Ekip satırları ve "kim nerede" bilgisi
operasyonel veridir → yalnız `operasyon.gor` (Operasyon Merkezi personel
sekmesiyle aynı kapı); sayı herkese döner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from sqlalchemy import (
    Select,
    String,
    and_,
    distinct,
    exists,
    func,
    literal,
    not_,
    null,
    or_,
    select,
)

from app.models import (
    Address,
    MaintenancePeriod,
    ServiceEquipment,
    ServiceHold,
    ServiceHoldReason,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServicePlan,
    ServiceTimeEntry,
    ServiceUnavailability,
    ServiceVehicle,
    User,
    UserUnit,
)
from app.models.servis_maliyet import ServiceOrderFinancial
from app.models.teknik_servis import DURUM_GRUPLARI, SERVIS_DURUMLARI
from app.permissions import ATANABILIR_SAHA_ROLLERI, BIRIMLER
from app.services.teknik_servis import (
    fatura_devri,
    is_emirleri,
    kapsam,
    operasyon,
    panel,
    sla,
)
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun_araligi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

_ACIK = sorted(DURUM_GRUPLARI["ACIK"])
_COZULDU = sorted(DURUM_GRUPLARI["COZULDU"])
# PB tamamlanma halkası: bu ay planlı bakımın durum kırılımı (IPTAL hariç tam bölüntü).
_PB_DEVAM = sorted(DURUM_GRUPLARI["SAHA"] | {"ATOLYEDE", "BEKLEMEDE"})
_PB_BEKLEYEN = sorted({"MUSTERI_TALEBI", "PLANLAMADA", "PLANLANDI", "TEKRAR_ACILDI"})

AKTIF_IS_SAYISI = 10
AKSIYON_SAYISI = 10
YAKLASAN_BAKIM_SAYISI = 5
EKIP_AZAMI = 200
LOKASYON_SECENEK_AZAMI = 100

DURUM_GRUBU_ADLARI: dict[str, str] = {
    "ACIK": "Açık",
    "SAHA": "Sahada",
    "COZULDU": "Çözülen",
    "KAPALI": "Kapalı",
    "SAYAC_ACILABILIR": "Çalışılabilir",
}

# Bekleme nedeni → işin beklediği birim (birimler arası aksiyon). Katalog
# tablosu (ServiceHoldReason) yeni neden alabilir; eşlemesi olmayan "Diğer".
BEKLEME_HEDEF_BIRIMI: dict[str, str] = {
    "MALZEME": "Depo",
    "DIS_SERVIS": "Satın Alma",
    "TEKLIF": "Satış",
    "MUSTERI_ONAYI": "Müşteri",
    "MUSTERI_ERISIMI": "Müşteri",
    "PERSONEL": "Planlama",
    "BAKIM_UYGUNSUZLUK": "Teknik Servis",
}

EKIP_DURUM_ADLARI: dict[str, str] = {
    "SAHADA": "Sahada",
    "UZAKTAN": "Uzaktan",
    "ATOLYEDE": "Atölyede",
    "MUSAIT": "Müsait",
    "IZINLI": "İzinli",
}
_EKIP_SIRASI = {k: i for i, k in enumerate(EKIP_DURUM_ADLARI)}
_FAALIYET_DURUMU = {
    "YOL": "SAHADA",
    "SAHA": "SAHADA",
    "UZAKTAN": "UZAKTAN",
    "ATOLYE": "ATOLYEDE",
    "TEST": "ATOLYEDE",
}
_MUSAITLIK_ADLARI = {"EGITIM": "Eğitimde", "OFIS": "Ofiste", "DIGER": "Müsait değil"}
_GUN_ADLARI = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")


# --- Ana panele özel KPI'lar (tek KPI kaydına eklenir) --------------------------------


def _s_sla_riskli(stmt, user=None, clock=None, donem=None):
    """SLA riskte VEYA aşılmış açık işler (operasyon `sla_riskte` ∪ `sla_asildi`)."""
    if clock is None:
        raise panel.PanelHatasi("SLA kutusu saate bağlı; clock verilmeli")
    ifade = sla.sla_ifadeleri(clock.now(), sla.ayar_tam_ifadesi("servis_sla_risk_yuzde"))
    return operasyon._acik_servis(stmt).where(  # noqa: SLF001 - aynı paket, tek tanım
        ServiceOrder.cozum_hedef_at.is_not(None),
        operasyon._bildirim_kaynagi(),  # noqa: SLF001
        ifade["durum"].in_(("RISKTE", "ASILDI")),
    )


def _s_servis_isleri(stmt, user=None, clock=None, donem=None):
    """Tek "açık iş" tanımı (rol testi tur 2, 2_menu B-08 / 6_satis D3): Ana
    Panel'in durum dağılımı, bölüm iş yükü ve aktif işler tablosu "Açık İş
    Emirleri" KPI'sıyla (`acik`) AYNI tabanı kullanır — PB hariç. Planlı bakım
    kendi kartında/grafiğinde (`bakim_bu_ay_planli`)."""
    return stmt.where(ServiceOrder.is_deleted.is_(False), ServiceOrder.tur != "PB")


def _s_onay_bekleyen(stmt, user=None, clock=None, donem=None):
    """Tamamlanmış, kapanış onayı (ekip lideri/kalite ya da müdür son onayı)
    bekleyen işler; PB hariç (`kapanis_bekleyen` ile aynı taban).

    2026-11-25 (kullanıcı isteği): KAPATILMIŞ iş onay bölümünde görünmez;
    eskiden kalite onayı verilmeden kapanan işler de "kalite bekleyen" diye
    buraya düşüyordu. Kapananlar `kapanan_isler` bölümündedir.
    """
    return stmt.where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.tur != "PB",
        ServiceOrder.status == "TAMAMLANDI",
    )


def _s_kapanan_isler(stmt, user=None, clock=None, donem=None):
    """Kapatılmış (son onayı verilmiş) işler; PB hariç. Servis İşleri altındaki
    "Kapanan İşler" bölümü (2026-11-25)."""
    return stmt.where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.tur != "PB",
        ServiceOrder.status == "KAPATILDI",
    )


for _t in (
    panel.KpiTanimi("sla_riskli", "SLA riski olan işler", "Çözüm hedefinin risk eşiği dolmuş ya da hedefi geçmiş açık işler (SLA riskte + aşıldı); PB hariç.", _s_sla_riskli, grup="ANA_PANEL", vurgu="kritik"),  # noqa: E501
    panel.KpiTanimi("onay_bekleyen", "Bekleyen onaylar", "Şef kapanışı (TAMAMLANDI) ya da kalite onayı bekleyen işler; PB hariç.", _s_onay_bekleyen, grup="ANA_PANEL", vurgu="uyari"),  # noqa: E501
    panel.KpiTanimi("kapanan_isler", "Kapanan işler", "Son onayı verilip kapatılmış işler; PB hariç.", _s_kapanan_isler, grup="ANA_PANEL"),  # noqa: E501
    panel.KpiTanimi("servis_isleri", "Servis işleri", "Silinmemiş servis işleri; PB hariç (Ana Panel dağılımlarının tabanı).", _s_servis_isleri, grup="ANA_PANEL"),  # noqa: E501
):  # fmt: skip
    panel.kpi_kaydet(_t)


# --- Süzgeç -----------------------------------------------------------------------------


@dataclass(frozen=True)
class AnaPanelSuzgeci:
    birim: str | None
    durum_grubu: str | None
    sef_id: int | None
    personel_id: int | None
    lokasyon_id: int | None
    bas: date
    bit: date

    @property
    def donem(self) -> str:
        return panel.aralik_metni(self.bas, self.bit)


def suzgec_hazirla(
    user: User,
    clock: Clock,
    *,
    birim: str | None = None,
    durum_grubu: str | None = None,
    sef_id: int | None = None,
    personel_id: int | None = None,
    lokasyon_id: int | None = None,
    bas: date | None = None,
    bit: date | None = None,
) -> AnaPanelSuzgeci:
    """Doğrulama: bilinmeyen birim/durum grubu, ters ya da 24 aydan uzun dönem →
    `PanelHatasi` (400); kapsam dışı birim → `PermissionError` (403, panel kuralı)."""
    birim = panel.birim_dogrula(user, birim)
    if durum_grubu in ("", None):
        durum_grubu = None
    elif durum_grubu not in DURUM_GRUPLARI:
        raise panel.PanelHatasi(f"Bilinmeyen durum grubu: {durum_grubu}")
    bugun = yerel_bugun(clock)
    bas = bas or bugun.replace(day=1)
    bit = bit or max(bugun, bas)
    panel.donem_dogrula(panel.aralik_metni(bas, bit))
    return AnaPanelSuzgeci(birim, durum_grubu, sef_id, personel_id, lokasyon_id, bas, bit)


def _parametreler(s: AnaPanelSuzgeci, **ek: Any) -> dict[str, Any]:
    """Liste parametreleri (ad = `/isler` sorgu parametresi = `ListeFiltresi` alanı)."""
    p: dict[str, Any] = {
        "birim": s.birim,
        "durum_grubu": s.durum_grubu,
        "teknisyen_id": s.personel_id,
        "sef_id": s.sef_id,
        "adres_id": s.lokasyon_id,
    }
    p.update(ek)
    return {k: v for k, v in p.items() if v not in (None, False, "", [], ())}


def liste_yolu(p: dict[str, Any]) -> str:
    """Parametrelerden `/servis-isleri?...` (ön yüz liste ekranı aynı adları okur)."""
    ciftler: list[tuple[str, str]] = []
    for k, v in p.items():
        if isinstance(v, list | tuple):
            ciftler += [(k, str(x)) for x in v]
        elif v is True:
            ciftler.append((k, "true"))
        elif isinstance(v, date):
            ciftler.append((k, v.isoformat()))
        else:
            ciftler.append((k, str(v)))
    return "/servis-isleri?" + urlencode(ciftler)


def _sorgu(user: User, clock: Clock, p: dict[str, Any]) -> Select:
    """Liste ucunun sorgusunun AYNISI (sıralamasız) — sayım ve gruplama tabanı."""
    alanlar = dict(p)
    if "durum" in alanlar:
        alanlar["durum"] = list(alanlar["durum"])
    return is_emirleri.liste_sorgusu(user, is_emirleri.ListeFiltresi(**alanlar), clock).order_by(
        None
    )


def _kimlikler(stmt: Select) -> Select:
    return stmt.with_only_columns(ServiceOrder.id)


async def _say(db: AsyncSession, stmt: Select) -> int:
    return int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


async def _grupla(db: AsyncSession, stmt: Select, sutun) -> dict[str, int]:
    q = select(sutun, func.count()).where(ServiceOrder.id.in_(_kimlikler(stmt))).group_by(sutun)
    return {k: int(v) for k, v in (await db.execute(q)).all()}


def gorunur_birimler(user: User, s: AnaPanelSuzgeci) -> list[str]:
    """Kullanıcının görebileceği birimler — kapsam yardımcısından (şirket kesişimi
    kapsam.py'de uygulanırsa burada da uygulanır)."""
    if s.birim:
        return [s.birim]
    return [b for b in BIRIMLER if not kapsam.birim_disinda_mi(user, b, birimsiz_gorunur=False)]


def _yuzde_degisim(deger: int, onceki: int | None) -> float | None:
    if onceki is None or onceki == 0:
        return None
    return round((deger - onceki) * 100.0 / onceki, 1)


# --- KPI kartları -------------------------------------------------------------------------


def _acik_anda(an: datetime):
    """`an` anında açık olan iş (zaman damgalarından yeniden kurulum)."""
    kapanis = func.coalesce(
        ServiceOrder.completed_at, ServiceOrder.cancelled_at, ServiceOrder.closed_at
    )
    return and_(ServiceOrder.created_at < an, or_(kapanis.is_(None), kapanis >= an))


async def _onceki_acik(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci, **ek: Any
) -> int | None:
    if s.durum_grubu:
        return None
    an = yerel_gun_araligi(s.bas)[0]
    p = _parametreler(s, kapali_dahil=True, **ek)
    stmt = _sorgu(user, clock, p).where(ServiceOrder.tur != "PB", _acik_anda(an))
    return await _say(db, stmt)


async def _onceki_askida(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> int | None:
    if s.durum_grubu:
        return None
    an = yerel_gun_araligi(s.bas)[0]
    stmt = _sorgu(user, clock, _parametreler(s, kapali_dahil=True)).where(
        ServiceOrder.tur != "PB",
        exists().where(
            ServiceHold.service_order_id == ServiceOrder.id,
            ServiceHold.started_at < an,
            or_(ServiceHold.released_at.is_(None), ServiceHold.released_at >= an),
        ),
    )
    return await _say(db, stmt)


async def _bakim_hedefi(db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci) -> int:
    """Bu aya hedef tarihi düşen (İPTAL olmayan) PB işleri — "hedefe göre"."""
    bugun = yerel_bugun(clock)
    ilk = bugun.replace(day=1)
    sonraki = (ilk + timedelta(days=32)).replace(day=1)
    stmt = _sorgu(user, clock, _parametreler(s, tur="PB", kapali_dahil=True)).where(
        ServiceOrder.status != "IPTAL",
        exists().where(
            MaintenancePeriod.id == ServiceOrder.maintenance_period_id,
            MaintenancePeriod.target_date >= ilk,
            MaintenancePeriod.target_date < sonraki,
        ),
    )
    return await _say(db, stmt)


def _personel_sorgusu(user: User, s: AnaPanelSuzgeci) -> Select:
    """Saha personeli (aktif, tayin edilebilir rol) — kapsam_personel ile."""
    stmt = select(User.id).where(
        User.is_active.is_(True), User.saha_rolu.in_(ATANABILIR_SAHA_ROLLERI)
    )
    stmt = kapsam.kapsam_personel(stmt, user, User.id)
    if s.birim:
        stmt = stmt.where(exists().where(UserUnit.user_id == User.id, UserUnit.birim == s.birim))
    if s.personel_id is not None:
        stmt = stmt.where(User.id == s.personel_id)
    return stmt


def _acik_sayac_kosulu():
    return and_(ServiceTimeEntry.ended_at.is_(None), ServiceTimeEntry.is_deleted.is_(False))


async def _kpi(
    db: AsyncSession,
    user: User,
    clock: Clock,
    s: AnaPanelSuzgeci,
    kod: str,
    ad: str,
    kpi_kodu: str,
    *,
    onceki: int | None = None,
    karsilastirma: str | None = None,
    **ek: Any,
) -> dict[str, Any]:
    tanim = panel.kpi_suzgeci(kpi_kodu)
    p = _parametreler(s, kpi=kpi_kodu, **ek)
    deger = await _say(db, _sorgu(user, clock, p))
    return {
        "kod": kod,
        "ad": ad,
        "tanim": tanim.tanim,
        "deger": deger,
        "toplam": None,
        "onceki_deger": onceki,
        "degisim_yuzde": _yuzde_degisim(deger, onceki),
        "karsilastirma": karsilastirma if onceki is not None else None,
        "vurgu": tanim.vurgu,
        "liste_yolu": liste_yolu(p),
    }


async def kpiler(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> list[dict[str, Any]]:
    donem_basi = "dönem başına göre"
    sonuc = [
        await _kpi(
            db, user, clock, s, "acik_is", "Açık İş Emirleri", "acik",
            onceki=await _onceki_acik(db, user, clock, s), karsilastirma=donem_basi,
        ),
        await _kpi(
            db, user, clock, s, "planli_bakim", "Planlı Bakım Bu Ay", "bakim_bu_ay_planli",
            onceki=await _bakim_hedefi(db, user, clock, s), karsilastirma="hedefe göre",
        ),
        await _kpi(
            db, user, clock, s, "acil_ariza", "Acil / Kritik Arıza", "kritik_acik",
            onceki=await _onceki_acik(db, user, clock, s, oncelik="KRITIK"),
            karsilastirma=donem_basi,
        ),
    ]  # fmt: skip
    # POC kartı = `acik` KPI'sı + birim POC. Başka birim süzülmüşse POC işi yoktur.
    # Rol testi tur 2 (2_menu B-12): POC birimi etkin şirkette (kapsamda) yoksa
    # kart HİÇ dönmez (ELEKTRONİK/MOBİLİTE'de "0" kartı yanıltıcıydı).
    poc_gorunur = not kapsam.birim_disinda_mi(user, "POC", birimsiz_gorunur=False)
    if poc_gorunur and s.birim in (None, "POC"):
        sonuc.append(
            await _kpi(
                db, user, clock, s, "poc_acik", "POC Açık Talep", "acik", birim="POC",
                onceki=await _onceki_acik(db, user, clock, s, birim="POC"),
                karsilastirma=donem_basi,
            )
        )  # fmt: skip
    elif poc_gorunur:
        sonuc.append(
            {
                "kod": "poc_acik",
                "ad": "POC Açık Talep",
                "tanim": panel.KPI_TANIMLARI["acik"].tanim,
                "deger": 0,
                "toplam": None,
                "onceki_deger": None,
                "degisim_yuzde": None,
                "karsilastirma": None,
                "vurgu": "normal",
                "liste_yolu": None,
            }
        )
    sonuc.append(await _kpi(db, user, clock, s, "sla_riski", "SLA Riski Olan İşler", "sla_riskli"))

    personel = _personel_sorgusu(user, s)
    toplam = await _say(db, personel)
    aktif = int(
        await db.scalar(
            select(func.count(distinct(ServiceTimeEntry.user_id))).where(
                ServiceTimeEntry.user_id.in_(personel), _acik_sayac_kosulu()
            )
        )
        or 0
    )
    sonuc.append(
        {
            "kod": "sahadaki_ekip",
            "ad": "Sahadaki Ekip",
            "tanim": "Açık (bitmemiş) zaman kaydı olan saha personeli / kapsamınızdaki aktif "
            "saha personeli. Konum (GPS) değil, zaman kaydı esas alınır.",
            "deger": aktif,
            "toplam": toplam,
            "onceki_deger": None,
            "degisim_yuzde": None,
            "karsilastirma": None,
            "vurgu": "normal",
            "liste_yolu": "/operasyon?sekme=personel" if user.has("operasyon.gor") else None,
        }
    )
    sonuc.append(
        await _kpi(
            db, user, clock, s, "askida", "Askıdaki Kayıtlar", "beklemede",
            onceki=await _onceki_askida(db, user, clock, s), karsilastirma=donem_basi,
        )
    )  # fmt: skip
    sonuc.append(
        await _kpi(db, user, clock, s, "bekleyen_onay", "Bekleyen Onaylar", "onay_bekleyen")
    )
    return sonuc


# --- Birim özeti ---------------------------------------------------------------------------


async def birim_ozeti(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> list[dict[str, Any]]:
    """Birim kartları: her sayı `kpi=<kod>&birim=<b>` listesinin toplamı."""
    olculer = {
        "acik": {"kpi": "acik"},
        "sahada": {"kpi": "sahada"},
        "atolyede": {"kpi": "atolyede"},
        "tamamlanan": {"kpi": "tamamlanan", "donem": s.donem},
        "donem_is_emri": {"bas": s.bas, "bit": s.bit, "kapali_dahil": True},
    }
    sayilar: dict[str, dict[str, int]] = {}
    for ad, ek in olculer.items():
        sayilar[ad] = await _grupla(
            db, _sorgu(user, clock, _parametreler(s, **ek)), ServiceOrder.birim
        )
    birimler = gorunur_birimler(user, s)
    # Kapsamda görünen ama birimi üyelikte olmayan iş (KENDI_ISLERI: birimler
    # arası destek) da kart alır; toplamlar listeyle ayrışmasın.
    for d in sayilar.values():
        for b in d:
            if b not in birimler:
                birimler.append(b)
    satirlar = []
    for b in birimler:
        deger = {ad: sayilar[ad].get(b, 0) for ad in olculer}
        payda = deger["acik"] + deger["tamamlanan"]
        satirlar.append(
            {
                "birim": b,
                "ad": BIRIMLER.get(b, b),
                **deger,
                # Varsayım: tamamlanma = dönemde tamamlanan / (tamamlanan + açık).
                "tamamlanma_yuzde": round(deger["tamamlanan"] * 100.0 / payda) if payda else None,
                "yollar": {
                    ad: liste_yolu(_parametreler(s, birim=b, **ek)) for ad, ek in olculer.items()
                },
            }
        )
    return satirlar


# --- Aktif işler ---------------------------------------------------------------------------


def _ekipman_metni(tip: str | None, marka: str | None, model: str | None) -> str | None:
    parca = " ".join(x for x in (marka, model) if x)
    return parca or tip


async def aktif_isler(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> dict[str, Any]:
    p = _parametreler(s, durum_grubu=s.durum_grubu or "ACIK", kpi="servis_isleri")
    stmt = (
        _sorgu(user, clock, p)
        .where(ServiceOrder.status.in_(_ACIK))
        .order_by(ServiceOrder.updated_at.desc(), ServiceOrder.id.desc())
        .limit(AKTIF_IS_SAYISI)
    )
    sos = list((await db.scalars(stmt)).all())
    idler = [so.id for so in sos]
    musteriler = await is_emirleri.musteri_ozetleri(
        db, {s_.customer_id for s_ in sos if s_.customer_id}
    )
    lokasyonlar = await is_emirleri.lokasyon_ozetleri(
        db, {s_.address_id for s_ in sos if s_.address_id}
    )
    ekipmanlar: dict[int, str | None] = {}
    ekipman_idler = {s_.equipment_id for s_ in sos if s_.equipment_id}
    if ekipman_idler:
        for eid, tip, marka, model in (
            await db.execute(
                select(
                    ServiceEquipment.id,
                    ServiceEquipment.equipment_type,
                    ServiceEquipment.brand,
                    ServiceEquipment.model,
                ).where(ServiceEquipment.id.in_(ekipman_idler))
            )
        ).all():
            ekipmanlar[eid] = _ekipman_metni(tip, marka, model)
    kisiler: dict[int, list[tuple[str, int, str, bool]]] = {i: [] for i in idler}
    araclar: dict[int, str | None] = {}
    if idler:
        for so_id, rol, kisi_id, ad, lead in (
            await db.execute(
                select(
                    ServiceOrderAssignment.service_order_id,
                    ServiceOrderAssignment.rol,
                    User.id,
                    User.full_name,
                    ServiceOrderAssignment.is_lead,
                )
                .join(User, User.id == ServiceOrderAssignment.user_id)
                .where(
                    ServiceOrderAssignment.service_order_id.in_(idler),
                    ServiceOrderAssignment.removed_at.is_(None),
                )
                .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id)
            )
        ).all():
            kisiler[so_id].append((rol, kisi_id, ad, lead))
        for so_id, plaka, eski in (
            await db.execute(
                select(
                    ServicePlan.service_order_id,
                    ServiceVehicle.plate,
                    ServicePlan.legacy_vehicle_text,
                )
                .outerjoin(ServiceVehicle, ServiceVehicle.id == ServicePlan.vehicle_id)
                .where(
                    ServicePlan.service_order_id.in_(idler),
                    ServicePlan.is_active.is_(True),
                    ServicePlan.is_deleted.is_(False),
                )
            )
        ).all():
            araclar[so_id] = plaka or eski
    sla_bloklari = await sla.sla_bloklari(db, sos, clock)
    satirlar = []
    for so in sos:
        ekip = kisiler.get(so.id, [])
        blok = sla_bloklari.get(so.id) or {}
        musteri = musteriler.get(so.customer_id) if so.customer_id else None
        lokasyon = lokasyonlar.get(so.address_id) if so.address_id else None
        satirlar.append(
            {
                "id": so.id,
                "no": so.so_no,
                "tur": so.tur,
                "tur_adi": is_emirleri.TUR_ADLARI.get(so.tur, so.tur),
                "birim": so.birim,
                "birim_adi": BIRIMLER.get(so.birim, so.birim),
                "ekipman": ekipmanlar.get(so.equipment_id) if so.equipment_id else None,
                "alt_sistem": so.sistem,
                "musteri": musteri["title"] if musteri else so.customer_name_raw,
                "lokasyon": lokasyon["ad"] if lokasyon else None,
                "tayin_edilen_sef": [{"id": k, "ad": a} for rol, k, a, _ in ekip if rol == "SEF"],
                # Sorumlu şef (yalnız şefin sahaya gittiği iş, B1) de tayinli
                # personeldir; aksi halde Set Bariyer satırı hep "—" görünürdü.
                "tayin_edilen_personel": [
                    {"id": k, "ad": a, "sorumlu": lead}
                    for rol, k, a, lead in ekip
                    if rol == "TEKNISYEN" or lead
                ],
                "arac": araclar.get(so.id),
                "durum": so.status,
                "durum_adi": is_emirleri.DURUM_ADLARI.get(so.status, so.status),
                "oncelik": so.oncelik,
                "son_guncelleme": so.updated_at,
                "sla": {
                    "durum": blok.get("durum"),
                    "ad": blok.get("ad"),
                    "kalan_dk": blok.get("kalan_dk"),
                    "olculur": bool(blok.get("olculur")),
                },
                "yol": f"/servis-isleri/{so.id}",
            }
        )
    return {"satirlar": satirlar, "liste_yolu": liste_yolu(p)}


# --- Canlı ekip durumu ----------------------------------------------------------------------


async def ekip_durumu(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> dict[str, Any]:
    if not user.has("operasyon.gor"):
        return {"gorunur": False, "satirlar": [], "ozet": [], "liste_yolu": None}
    kimlik_sorgusu = _personel_sorgusu(user, s)
    kisiler = (
        await db.execute(
            select(User.id, User.full_name, User.saha_rolu)
            .where(User.id.in_(kimlik_sorgusu))
            .order_by(User.full_name, User.id)
            .limit(EKIP_AZAMI)
        )
    ).all()
    kimlikler = [k[0] for k in kisiler]
    birimleri: dict[int, list[str]] = {k: [] for k in kimlikler}
    sayaclar: dict[int, tuple[Any, ...]] = {}
    musaitlik: dict[int, str] = {}
    simdi = clock.now()
    if kimlikler:
        for uid, b in (
            await db.execute(
                select(UserUnit.user_id, UserUnit.birim)
                .where(UserUnit.user_id.in_(kimlikler))
                .order_by(UserUnit.is_primary.desc(), UserUnit.birim)
            )
        ).all():
            birimleri[uid].append(b)
        for satir in (
            await db.execute(
                select(
                    ServiceTimeEntry.user_id,
                    ServiceTimeEntry.faaliyet,
                    ServiceTimeEntry.started_at,
                    ServiceOrder.id,
                    ServiceOrder.so_no,
                    ServiceOrder.kategori,
                    func.coalesce(Address.site_name, Address.label),
                )
                .join(ServiceOrder, ServiceOrder.id == ServiceTimeEntry.service_order_id)
                .outerjoin(Address, Address.id == ServiceOrder.address_id)
                .where(ServiceTimeEntry.user_id.in_(kimlikler), _acik_sayac_kosulu())
            )
        ).all():
            sayaclar[satir[0]] = satir[1:]
        for uid, tur in (
            await db.execute(
                select(ServiceUnavailability.user_id, ServiceUnavailability.tur).where(
                    ServiceUnavailability.user_id.in_(kimlikler),
                    ServiceUnavailability.is_deleted.is_(False),
                    ServiceUnavailability.starts_at <= simdi,
                    ServiceUnavailability.ends_at > simdi,
                )
            )
        ).all():
            musaitlik[uid] = tur
    gorunen: set[int] = set()
    if sayaclar:
        is_idler = [v[2] for v in sayaclar.values()]
        gorunen = set(
            (
                await db.scalars(
                    kapsam.kapsam_isler(
                        select(ServiceOrder.id).where(ServiceOrder.id.in_(is_idler)),
                        user,
                        ServiceOrder.id,
                    )
                )
            ).all()
        )
    satirlar = []
    for uid, ad, saha_rolu in kisiler:
        sayac = sayaclar.get(uid)
        is_bilgisi = None
        sure_dk = None
        aciklama = None
        if sayac is not None:
            faaliyet, baslangic, so_id, so_no, kategori, lokasyon = sayac
            durum = _FAALIYET_DURUMU.get(faaliyet) or (
                "ATOLYEDE" if kategori == "ATOLYE" else "SAHADA"
            )
            gizli = so_id not in gorunen
            is_bilgisi = {
                "id": None if gizli else so_id,
                "no": "Kapsam dışı iş" if gizli else so_no,
                "lokasyon": None if gizli else lokasyon,
            }
            sure_dk = max(0, int((simdi - baslangic).total_seconds() // 60))
        elif musaitlik.get(uid) == "IZIN":
            durum = "IZINLI"
            aciklama = "Bugün izinli"
        else:
            durum = "MUSAIT"
            if uid in musaitlik:
                aciklama = _MUSAITLIK_ADLARI.get(musaitlik[uid], musaitlik[uid])
        satirlar.append(
            {
                "user_id": uid,
                "ad": ad,
                "saha_rolu": saha_rolu,
                "birimler": [BIRIMLER.get(b, b) for b in birimleri.get(uid, [])],
                "durum": durum,
                "durum_adi": EKIP_DURUM_ADLARI[durum],
                "is_": is_bilgisi,
                "aciklama": aciklama,
                "sure_dk": sure_dk,
            }
        )
    satirlar.sort(key=lambda r: (_EKIP_SIRASI[r["durum"]], -(r["sure_dk"] or 0), r["ad"] or ""))
    ozet = [
        {"durum": k, "ad": a, "adet": sum(1 for r in satirlar if r["durum"] == k)}
        for k, a in EKIP_DURUM_ADLARI.items()
    ]
    return {
        "gorunur": True,
        "satirlar": satirlar,
        "ozet": ozet,
        "liste_yolu": "/operasyon?sekme=personel",
    }


# --- Birimler arası bekleyen aksiyonlar -----------------------------------------------------


async def bekleyen_aksiyonlar(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> dict[str, Any]:
    """Mevcut durum/askı verisinden türetilir (yeni tablo yok):

    - aktif iş beklemesi (askı nedeni → hedef birim, `BEKLEME_HEDEF_BIRIMI`),
    - TAMAMLANDI → şef kapanış onayı, KAPATILDI ∧ kalite onayı yok → kalite,
    - ATOLYEDE → atölye (bekleme başlangıcı = son ATÖLYEDE geçişi),
    - fatura devri bekleyen → Mali İşler (yalnız `tahsilat.gor`; tutar YOK).
    """
    taban = _kimlikler(_sorgu(user, clock, _parametreler(s, kapali_dahil=True)))
    toplam_sutun = func.count().over().label("toplam")
    kaynaklar: list[tuple[str | None, Select]] = []
    kaynaklar.append(
        (
            None,  # hedef birim satırdaki nedenden
            select(
                ServiceOrder.id,
                ServiceOrder.so_no,
                ServiceOrder.birim,
                ServiceHold.started_at,
                ServiceHold.neden,
                func.coalesce(ServiceHoldReason.ad, ServiceHold.neden),
                toplam_sutun,
            )
            .join(
                ServiceHold,
                and_(
                    ServiceHold.service_order_id == ServiceOrder.id,
                    ServiceHold.released_at.is_(None),
                ),
            )
            .outerjoin(ServiceHoldReason, ServiceHoldReason.kod == ServiceHold.neden)
            .where(ServiceOrder.id.in_(taban))
            .order_by(ServiceHold.started_at)
            .limit(AKSIYON_SAYISI),
        )
    )

    def _basit(hedef: str, aciklama: str, an, *kosullar) -> tuple[str, Select]:
        return (
            hedef,
            select(
                ServiceOrder.id,
                ServiceOrder.so_no,
                ServiceOrder.birim,
                an,
                null(),
                literal(aciklama, String),
                toplam_sutun,
            )
            .where(ServiceOrder.id.in_(taban), *kosullar)
            .order_by(an)
            .limit(AKSIYON_SAYISI),
        )

    kaynaklar.append(
        _basit(
            "Şef (kapanış onayı)",
            "Kapanış onayı bekliyor",
            func.coalesce(ServiceOrder.completed_at, ServiceOrder.updated_at),
            ServiceOrder.status == "TAMAMLANDI",
        )
    )
    kaynaklar.append(
        _basit(
            "Kalite",
            "Kalite onayı bekliyor",
            func.coalesce(ServiceOrder.closed_at, ServiceOrder.updated_at),
            ServiceOrder.status == "KAPATILDI",
            is_emirleri.kalite_kosulu("BEKLEYEN"),
        )
    )
    atolye_ani = (
        select(func.max(ServiceOrderEvent.olusma_zamani))
        .where(
            ServiceOrderEvent.service_order_id == ServiceOrder.id,
            ServiceOrderEvent.yeni_durum == "ATOLYEDE",
        )
        .correlate(ServiceOrder)
        .scalar_subquery()
    )
    kaynaklar.append(
        _basit(
            "Atölye",
            "Atölyede işlem bekliyor",
            func.coalesce(atolye_ani, ServiceOrder.updated_at),
            ServiceOrder.status == "ATOLYEDE",
        )
    )
    if user.has("tahsilat.gor"):
        kaynaklar.append(
            _basit(
                "Mali İşler",
                "Fatura devri bekliyor",
                func.coalesce(ServiceOrder.completed_at, ServiceOrder.closed_at),
                # `fatura_devri.uygun_kosulu` gelir kolonlarını JOIN'li sorgu için
                # yazar; burada JOIN yok → gelir koşulu EXISTS içinde (aynı tanım).
                ServiceOrder.status.in_(_COZULDU),
                fatura_devri.kalite_kapisi(),
                or_(
                    fatura_devri._kabul_teklif_var(),  # noqa: SLF001 - tek tanım
                    exists().where(
                        ServiceOrderFinancial.service_order_id == ServiceOrder.id,
                        fatura_devri._gelirli(),  # noqa: SLF001
                    ),
                ),
                not_(
                    exists().where(
                        ServiceOrderFinancial.service_order_id == ServiceOrder.id,
                        ServiceOrderFinancial.fatura_iletildi_at.is_not(None),
                    )
                ),
            )
        )
    simdi = clock.now()
    satirlar: list[dict[str, Any]] = []
    ozet: dict[str, int] = {}
    for hedef, sorgu in kaynaklar:
        for so_id, so_no, birim, an, neden, aciklama, toplam in (await db.execute(sorgu)).all():
            hedef_birim = hedef or BEKLEME_HEDEF_BIRIMI.get(neden or "", "Diğer")
            if hedef is not None:
                ozet[hedef_birim] = int(toplam)
            satirlar.append(
                {
                    "kayit_id": so_id,
                    "kayit_no": so_no,
                    "aciklama": aciklama,
                    "kaynak_birim": BIRIMLER.get(birim, birim),
                    "hedef_birim": hedef_birim,
                    "bekleme_baslangic": an,
                    "bekleme_dk": (max(0, int((simdi - an).total_seconds() // 60)) if an else None),
                    "yol": f"/servis-isleri/{so_id}",
                }
            )
    # Askı kaynağının hedef kırılımı ayrı sayılır (bir sorguda birden çok hedef).
    for neden, adet in (
        await db.execute(
            select(ServiceHold.neden, func.count())
            .where(ServiceHold.released_at.is_(None), ServiceHold.service_order_id.in_(taban))
            .group_by(ServiceHold.neden)
        )
    ).all():
        hedef_birim = BEKLEME_HEDEF_BIRIMI.get(neden, "Diğer")
        ozet[hedef_birim] = ozet.get(hedef_birim, 0) + int(adet)
    satirlar.sort(key=lambda r: -(r["bekleme_dk"] or 0))
    return {
        "satirlar": satirlar[:AKSIYON_SAYISI],
        "ozet": [
            {"hedef_birim": k, "adet": v} for k, v in sorted(ozet.items(), key=lambda x: -x[1])
        ],
        "toplam": sum(ozet.values()),
    }


# --- Grafikler ------------------------------------------------------------------------------


async def grafikler(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> dict[str, Any]:
    # Tek "açık" tanımı (B-08): dağılım, iş yükü ve aktif işler PB hariç
    # (`servis_isleri` KPI süzgeci; liste yolu da aynı süzgeci taşır).
    taban = "servis_isleri"
    durumlar = await _grupla(
        db,
        _sorgu(user, clock, _parametreler(s, kapali_dahil=True, kpi=taban)),
        ServiceOrder.status,
    )
    gosterilen = [d for d in SERVIS_DURUMLARI if d in DURUM_GRUPLARI["ACIK"] or d == "TAMAMLANDI"]
    durum_dagilimi = [
        {
            "kod": d,
            "ad": is_emirleri.DURUM_ADLARI[d],
            "deger": durumlar.get(d, 0),
            "liste_yolu": liste_yolu(_parametreler(s, durum=[d], kpi=taban)),
        }
        for d in gosterilen
    ]

    yuk_grubu = s.durum_grubu or "ACIK"
    yuk = await _grupla(
        db,
        _sorgu(user, clock, _parametreler(s, durum_grubu=yuk_grubu, kpi=taban)),
        ServiceOrder.birim,
    )
    birimler = gorunur_birimler(user, s) + [b for b in yuk if b not in gorunur_birimler(user, s)]
    bolum_is_yuku = [
        {
            "birim": b,
            "ad": BIRIMLER.get(b, b),
            "deger": yuk.get(b, 0),
            "liste_yolu": liste_yolu(_parametreler(s, durum_grubu=yuk_grubu, birim=b, kpi=taban)),
        }
        for b in birimler
    ]

    # Planlı bakım (bu ay planlı = `bakim_bu_ay_planli` KPI'sı) durum kırılımı.
    pb = await _grupla(
        db, _sorgu(user, clock, _parametreler(s, kpi="bakim_bu_ay_planli")), ServiceOrder.status
    )
    parcalar = (
        ("tamamlanan", "Tamamlanan", _COZULDU),
        ("devam_eden", "Devam Eden", _PB_DEVAM),
        ("planlanan", "Planlanan", _PB_BEKLEYEN),
    )
    pb_parcalar = [
        {
            "kod": kod,
            "ad": ad,
            "deger": sum(pb.get(d, 0) for d in durumlar_),
            "liste_yolu": liste_yolu(_parametreler(s, kpi="bakim_bu_ay_planli", durum=durumlar_)),
        }
        for kod, ad, durumlar_ in parcalar
    ]
    pb_toplam = sum(pb.values())
    pb_tamam = pb_parcalar[0]["deger"]
    pb_yuzde = round(pb_tamam * 100.0 / pb_toplam) if pb_toplam else None

    # Haftalık plan: bu haftanın (Pzt–Paz) aktif planları, iş başına bir.
    bugun = yerel_bugun(clock)
    pazartesi = bugun - timedelta(days=bugun.weekday())
    gunler = [pazartesi + timedelta(days=i) for i in range(7)]
    plan_taban = _kimlikler(
        _sorgu(user, clock, _parametreler(s, kapali_dahil=True)).where(
            ServiceOrder.status != "IPTAL"
        )
    )
    plan_sayilari = dict(
        (
            await db.execute(
                select(ServicePlan.plan_date, func.count(distinct(ServicePlan.service_order_id)))
                .where(
                    ServicePlan.is_active.is_(True),
                    ServicePlan.is_deleted.is_(False),
                    ServicePlan.plan_date >= gunler[0],
                    ServicePlan.plan_date <= gunler[-1],
                    ServicePlan.service_order_id.in_(plan_taban),
                )
                .group_by(ServicePlan.plan_date)
            )
        ).all()
    )
    haftalik_plan = [
        {
            "tarih": g,
            "gun_adi": _GUN_ADLARI[g.weekday()],
            "adet": int(plan_sayilari.get(g, 0)),
            "bugun": g == bugun,
            "liste_yolu": f"/servis-planlama?gun={g.isoformat()}",
        }
        for g in gunler
    ]

    # Aylık bakım takvimi: yaklaşan (bugün ve sonrası) aktif planlı açık PB işleri.
    yaklasan_sorgu = (
        select(
            ServicePlan.plan_date,
            ServiceOrder.id,
            ServiceOrder.so_no,
            ServiceOrder.customer_id,
            ServiceOrder.customer_name_raw,
            ServiceOrder.konu,
            ServiceOrder.sistem,
        )
        .join(ServiceOrder, ServiceOrder.id == ServicePlan.service_order_id)
        .where(
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
            ServicePlan.plan_date >= bugun,
            ServicePlan.service_order_id.in_(
                _kimlikler(
                    _sorgu(
                        user, clock, _parametreler(s, tur="PB", durum_grubu=s.durum_grubu or "ACIK")
                    ).where(ServiceOrder.status.in_(_ACIK))
                )
            ),
        )
        .order_by(ServicePlan.plan_date, ServiceOrder.id)
        .limit(YAKLASAN_BAKIM_SAYISI)
    )
    yaklasan_satirlar = (await db.execute(yaklasan_sorgu)).all()
    musteriler = await is_emirleri.musteri_ozetleri(
        db, {r.customer_id for r in yaklasan_satirlar if r.customer_id}
    )
    yaklasan = [
        {
            "tarih": r.plan_date,
            "id": r.id,
            "no": r.so_no,
            "musteri": (musteriler.get(r.customer_id) or {}).get("title") or r.customer_name_raw,
            "aciklama": r.sistem or r.konu,
            "yol": f"/servis-isleri/{r.id}",
        }
        for r in yaklasan_satirlar
    ]
    return {
        "durum_dagilimi": durum_dagilimi,
        "acik_toplam": sum(
            x["deger"] for x in durum_dagilimi if x["kod"] in DURUM_GRUPLARI["ACIK"]
        ),
        "bolum_is_yuku": bolum_is_yuku,
        "planli_bakim": {
            "toplam": pb_toplam,
            "tamamlanan": pb_tamam,
            "yuzde": pb_yuzde,
            "parcalar": pb_parcalar,
            "liste_yolu": liste_yolu(_parametreler(s, kpi="bakim_bu_ay_planli")),
        },
        "haftalik_plan": haftalik_plan,
        "aylik_bakim": {
            "ay": bugun.replace(day=1),
            "planlanan": pb_toplam,
            "tamamlanan": pb_tamam,
            "kalan": pb_toplam - pb_tamam,
            "yuzde": pb_yuzde,
            "yaklasan": yaklasan,
        },
    }


# --- Süzgeç seçenekleri ---------------------------------------------------------------------


async def secenekler(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> dict[str, Any]:
    """Süzgeç çubuğunun seçenekleri — süzgeçten bağımsız, yalnız kapsamla."""
    bos = AnaPanelSuzgeci(None, None, None, None, None, s.bas, s.bit)
    kisi_sorgusu = _personel_sorgusu(user, bos)
    kisiler = (
        await db.execute(
            select(User.id, User.full_name, User.saha_rolu)
            .where(User.id.in_(kisi_sorgusu))
            .order_by(User.full_name, User.id)
            .limit(EKIP_AZAMI)
        )
    ).all()
    acik_isler = _kimlikler(_sorgu(user, clock, {"durum_grubu": "ACIK"}))
    lokasyonlar = (
        await db.execute(
            select(Address.id, func.coalesce(Address.site_name, Address.label), Address.city)
            .join(ServiceOrder, ServiceOrder.address_id == Address.id)
            .where(ServiceOrder.id.in_(acik_isler))
            .group_by(Address.id)
            .order_by(func.count().desc(), Address.id)
            .limit(LOKASYON_SECENEK_AZAMI)
        )
    ).all()
    return {
        "birimler": [{"kod": b, "ad": BIRIMLER[b]} for b in gorunur_birimler(user, bos)],
        "durum_gruplari": [{"kod": k, "ad": a} for k, a in DURUM_GRUBU_ADLARI.items()],
        "sefler": [{"id": i, "ad": a} for i, a, rol in kisiler if rol == "SEF"],
        "personel": [{"id": i, "ad": a} for i, a, _ in kisiler],
        "lokasyonlar": [
            {"id": i, "ad": f"{a} ({il})" if il else (a or f"#{i}")} for i, a, il in lokasyonlar
        ],
    }


# --- Bütün yanıt ----------------------------------------------------------------------------


async def ana_panel(
    db: AsyncSession, user: User, clock: Clock, s: AnaPanelSuzgeci
) -> dict[str, Any]:
    return {
        "guncelleme_zamani": clock.now(),
        "donem": {"bas": s.bas, "bit": s.bit, "aralik": s.donem},
        "suzgec": {
            "birim": s.birim,
            "durum_grubu": s.durum_grubu,
            "sef_id": s.sef_id,
            "personel_id": s.personel_id,
            "lokasyon_id": s.lokasyon_id,
        },
        "kpiler": await kpiler(db, user, clock, s),
        "birim_ozeti": await birim_ozeti(db, user, clock, s),
        "aktif_isler": await aktif_isler(db, user, clock, s),
        "ekip_durumu": await ekip_durumu(db, user, clock, s),
        "bekleyen_aksiyonlar": await bekleyen_aksiyonlar(db, user, clock, s),
        "grafikler": await grafikler(db, user, clock, s),
        "secenekler": await secenekler(db, user, clock, s),
    }


__all__ = [
    "AnaPanelSuzgeci",
    "ana_panel",
    "liste_yolu",
    "suzgec_hazirla",
]
