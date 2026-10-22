"""Sunucu tarafı tek rapor/KPI motoru (E12-08, E12-11, E12-17/18).

Maddeler: TS-181, TS-184, TS-201. Doldurur: D3-A.

**Tek yol:** her rapor sayısı `kpi_sorgusu()`'ndan geçer = rapor süzgeci
(`filtre_uygula`, yalnız `service_orders` kolonları ve alt sorgular) + KPI
süzgeci (`panel.KPI_TANIMLARI`, `rapor_tanimlari` kaydı) + kapsam
(`kapsam.kapsam_isler`; `KENDI_MUSTERILERI` için `kapsam_musteri` karşılığı
`_is_kosulu` içinde). Rapor ucu kendi WHERE'ini kapsamsız KURAMAZ: `detay_sorgusu`
ve `kpi_sorgusu` kapsamı kendisi uygular. Sayı (`count`) ile liste (`sayfala`)
aynı sorgudan → "KPI sayısı = açılan liste `X-Toplam-Kayit`".

**Toplama SQL'de** (`count`, `sum`, `FILTER`, `GROUP BY`); ham süre satırları
toptan gönderilmez (JSON en çok `JSON_AZAMI_SATIR`). Python'da yalnız
gruplanmış satırlar birleştirilir (şehir adı normalizasyonu, lokasyon anahtarı).

**Doğrulama** (kontrol B14): katalog dışı değer Pydantic `Literal` ile 422
(API); tarih sırası ve 24 ay sınırı `RaporHatasi` → 400; kullanıcının birimi
olmayan `birim` ve izinsiz `teknisyen_id` → `RaporYetkiHatasi` → 403.

Kişi kırılımı / ham süre / iletişim yalnız `servis_rapor.personel` ile; para
alanı servis raporlarında YOKTUR (maliyet anahtarı hiçbir yanıtta yer almaz).
Mobilite raporları (`services/reports.py`) değişmez.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, case, distinct, func, select

from app.models import (
    Account,
    Address,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServiceResult,
    ServiceTimeEntry,
    User,
)
from app.models.teknik_servis import (
    DURUM_GRUPLARI,
    KISI_SAATE_DAHIL,
    ONCELIKLER,
    SERVIS_KATEGORILERI,
    SERVIS_TURLERI,
)
from app.permissions import BIRIMLER, SCOPE_ALL, SCOPE_OWN_JOBS
from app.services.normalize import il_normalize
from app.services.teknik_servis import kapsam, panel
from app.services.teknik_servis import rapor_tanimlari as rt
from app.services.teknik_servis.kancalar import ServisGirdiHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun_araligi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

_ACIK = sorted(DURUM_GRUPLARI["ACIK"])
_COZULDU = sorted(DURUM_GRUPLARI["COZULDU"])
RAPOR_DURUM_GRUPLARI = ("ACIK", "COZULDU", "IPTAL")
DURUM_GRUBU_ADLARI = {"ACIK": "Açık", "COZULDU": "Çözüldü", "IPTAL": "İptal"}
ONCELIK_ADLARI = {"KRITIK": "Kritik", "YUKSEK": "Yüksek", "NORMAL": "Normal"}
AY_ADLARI = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)  # fmt: skip


class RaporHatasi(ServisGirdiHatasi):
    """Tarih sırası / aralık sınırı / tanınmayan şehir → 400."""


class RaporYetkiHatasi(PermissionError):
    """Kullanıcının birimi olmayan birim, izinsiz kişi kırılımı → 403."""


# --- Filtre -------------------------------------------------------------------------------


@dataclass(frozen=True)
class RaporFiltresi:
    """Doğrulanmış rapor filtresi (`filtre_hazirla` üretir; elle kurulmaz).

    Boş tuple = "tümü" (yetkili olduğum bütün birimler — kapsam ayrıca
    uygulanır). `sehir_degerleri`: seçilen ile normalize olan, veritabanındaki
    ham `addresses.city` yazımları (SQL eşitliği; serbest metin LIKE yok).
    """

    baslangic: date
    bitis: date
    tarih_esasi: str = "ACILIS"
    kategori: tuple[str, ...] = ()
    birim: tuple[str, ...] = ()
    durum_grubu: tuple[str, ...] = ()
    tur: tuple[str, ...] = ()
    oncelik: tuple[str, ...] = ()
    musteri_id: int | None = None
    sef_id: int | None = None
    teknisyen_id: int | None = None
    sehir: str | None = None
    sehir_degerleri: tuple[str, ...] = field(default=(), compare=False)
    tekrar_gun: int | None = None

    @property
    def donem(self) -> str:
        return panel.aralik_metni(self.baslangic, self.bitis)

    @property
    def aralik(self):
        """UTC yarı açık `[bas, bit)` (Türkiye günleri, iki uç dahil)."""
        return yerel_gun_araligi(self.baslangic)[0], yerel_gun_araligi(self.bitis)[1]

    def onceki(self) -> RaporFiltresi:
        """Eşit uzunlukta bir önceki dönem (E12-18)."""
        gun = (self.bitis - self.baslangic).days
        bit = self.baslangic - timedelta(days=1)
        return replace(self, baslangic=bit - timedelta(days=gun), bitis=bit)

    def iso(self) -> dict[str, Any]:
        """Denetim kaydı ve yanıt için JSON'a yazılabilir filtre (tarih ISO)."""
        veri = asdict(self)
        veri.pop("sehir_degerleri", None)
        veri["baslangic"] = self.baslangic.isoformat()
        veri["bitis"] = self.bitis.isoformat()
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in veri.items()}


def _tekil(degerler) -> tuple[str, ...]:
    return tuple(dict.fromkeys(d for d in (degerler or ()) if d))


async def filtre_hazirla(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    baslangic: date | None = None,
    bitis: date | None = None,
    tarih_esasi: str = "ACILIS",
    kategori=(),
    birim=(),
    durum_grubu=(),
    tur=(),
    oncelik=(),
    musteri_id: int | None = None,
    sef_id: int | None = None,
    teknisyen_id: int | None = None,
    sehir: str | None = None,
    tekrar_gun: int | None = None,
) -> RaporFiltresi:
    """Ham parametreleri doğrular. Varsayılan dönem: içinde bulunulan ay
    (Türkiye günü). Sözlük doğrulaması API'de (`Literal`, 422) yapılır; burada
    yalnız iş kuralı ve yetki vardır — servis doğrudan çağrılsa da güvenli
    kalsın diye sözlükler burada da denetlenir (400)."""
    bugun = yerel_bugun(clock)
    bitis = bitis or (bugun if baslangic is None or baslangic <= bugun else baslangic)
    baslangic = baslangic or bitis.replace(day=1)
    try:
        panel.aralik_gunleri(panel.aralik_metni(baslangic, bitis))
    except panel.PanelHatasi as exc:
        raise RaporHatasi(str(exc)) from None
    if tarih_esasi not in rt.TARIH_ESASLARI:
        raise RaporHatasi(f"Bilinmeyen tarih esası: {tarih_esasi}")
    for ad, degerler, katalog in (
        ("kategori", kategori, SERVIS_KATEGORILERI),
        ("birim", birim, BIRIMLER),
        ("durum grubu", durum_grubu, RAPOR_DURUM_GRUPLARI),
        ("tür", tur, SERVIS_TURLERI),
        ("öncelik", oncelik, ONCELIKLER),
    ):
        bilinmeyen = [d for d in degerler or () if d not in katalog]
        if bilinmeyen:
            raise RaporHatasi(f"Bilinmeyen {ad}: {', '.join(bilinmeyen)}")
    birim = _tekil(birim)
    if user.role is None or user.role.scope != SCOPE_ALL:
        yetkisiz = [b for b in birim if b not in kapsam.kullanici_birimleri(user)]
        if yetkisiz:
            raise RaporYetkiHatasi(f"Bu birimin raporunu görme yetkiniz yok: {', '.join(yetkisiz)}")
    if teknisyen_id is not None and not user.has("servis_rapor.personel"):
        raise RaporYetkiHatasi("Kişi bazlı süzgeç için yetkiniz yok (servis_rapor.personel)")
    if tekrar_gun is not None and not rt.TEKRAR_GUN_ALT <= tekrar_gun <= rt.TEKRAR_GUN_UST:
        raise RaporHatasi(
            f"Tekrar arıza penceresi {rt.TEKRAR_GUN_ALT}–{rt.TEKRAR_GUN_UST} gün olmalı"
        )
    sehir_adi = None
    sehir_degerleri: tuple[str, ...] = ()
    if sehir:
        sehir_adi = il_normalize(sehir)
        if sehir_adi is None:
            raise RaporHatasi(f"Tanınmayan il: {sehir}")
        hamlar = (
            await db.scalars(select(Address.city).where(Address.city.is_not(None)).distinct())
        ).all()
        sehir_degerleri = tuple(sorted(h for h in hamlar if il_normalize(h) == sehir_adi))
    return RaporFiltresi(
        baslangic=baslangic,
        bitis=bitis,
        tarih_esasi=tarih_esasi,
        kategori=_tekil(kategori),
        birim=birim,
        durum_grubu=_tekil(durum_grubu),
        tur=_tekil(tur),
        oncelik=_tekil(oncelik),
        musteri_id=musteri_id,
        sef_id=sef_id,
        teknisyen_id=teknisyen_id,
        sehir=sehir_adi,
        sehir_degerleri=sehir_degerleri,
        tekrar_gun=tekrar_gun,
    )


def durum_grubu_ifadesi():
    """Rapor durum grubu SQL ifadesi (`DURUM_GRUPLARI`'ndan; elle liste yok)."""
    return case(
        (ServiceOrder.status.in_(_COZULDU), "COZULDU"),
        (ServiceOrder.status == "IPTAL", "IPTAL"),
        else_="ACIK",
    )


def _sef_ifadesi():
    """İşin aktif şefi (sorumlu önce, en son atanan)."""
    return (
        select(ServiceOrderAssignment.user_id)
        .where(
            ServiceOrderAssignment.service_order_id == ServiceOrder.id,
            ServiceOrderAssignment.removed_at.is_(None),
            ServiceOrderAssignment.rol == "SEF",
        )
        .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id.desc())
        .limit(1)
        .correlate(ServiceOrder)
        .scalar_subquery()
    )


def _kanal_ifadesi():
    return (
        select(ServiceResult.cozum_kanali)
        .where(
            ServiceResult.service_order_id == ServiceOrder.id,
            ServiceResult.gecersiz_at.is_(None),
        )
        .order_by(ServiceResult.id.desc())
        .limit(1)
        .correlate(ServiceOrder)
        .scalar_subquery()
    )


def _sehir_ifadesi():
    return (
        select(Address.city)
        .where(Address.id == ServiceOrder.address_id)
        .correlate(ServiceOrder)
        .scalar_subquery()
    )


def filtre_uygula(stmt: Select, f: RaporFiltresi) -> Select:
    """Rapor süzgeci: yalnız `service_orders` kolonları ve alt sorgular (JOIN yok;
    `sayfala` sayımı ve KPI süzgeçleri bozulmasın). Tarih bu fonksiyonda YOK —
    tarih KPI süzgecinin (`donem`) ya da `detay_kosulu`'nun işidir."""
    stmt = stmt.where(ServiceOrder.is_deleted.is_(False))
    if f.birim:
        stmt = stmt.where(ServiceOrder.birim.in_(f.birim))
    if f.kategori:
        stmt = stmt.where(ServiceOrder.kategori.in_(f.kategori))
    if f.tur:
        stmt = stmt.where(ServiceOrder.tur.in_(f.tur))
    if f.oncelik:
        stmt = stmt.where(ServiceOrder.oncelik.in_(f.oncelik))
    if f.durum_grubu:
        stmt = stmt.where(durum_grubu_ifadesi().in_(f.durum_grubu))
    if f.musteri_id is not None:
        stmt = stmt.where(ServiceOrder.customer_id == f.musteri_id)
    if f.sef_id is not None:
        stmt = stmt.where(_sef_ifadesi() == f.sef_id)
    if f.teknisyen_id is not None:
        # Tam eşleşme (users.id): "Ali Veli" seçimi "Aliye"yi getirmez (E12-11).
        stmt = stmt.where(
            ServiceOrder.id.in_(
                select(ServiceOrderAssignment.service_order_id).where(
                    ServiceOrderAssignment.user_id == f.teknisyen_id,
                    ServiceOrderAssignment.removed_at.is_(None),
                )
            )
        )
    if f.sehir is not None:
        stmt = stmt.where(_sehir_ifadesi().in_(f.sehir_degerleri or ("\x00",)))
    return stmt


def detay_kosulu(f: RaporFiltresi):
    """Tarih esası: detay listesi ve kırılımlar bu tarihe göre süzülür."""
    bas, bit = f.aralik
    if f.tarih_esasi == "COZUM":
        return (ServiceOrder.completed_at >= bas) & (ServiceOrder.completed_at < bit)
    if f.tarih_esasi == "KAPANIS":
        return (ServiceOrder.closed_at >= bas) & (ServiceOrder.closed_at < bit)
    if f.tarih_esasi == "PLAN":
        return ServiceOrder.id.in_(
            select(ServicePlan.service_order_id).where(
                ServicePlan.is_active.is_(True),
                ServicePlan.is_deleted.is_(False),
                ServicePlan.plan_date >= f.baslangic,
                ServicePlan.plan_date <= f.bitis,
            )
        )
    return (ServiceOrder.created_at >= bas) & (ServiceOrder.created_at < bit)


def detay_sorgusu(user: User, f: RaporFiltresi, *secim) -> Select:
    """Detay kümesi (tarih esasına göre) — kapsamlı. Varsayılan seçim iş kimliği."""
    stmt = select(*(secim or (ServiceOrder.id,)))
    stmt = filtre_uygula(stmt, f).where(detay_kosulu(f))
    return kapsam.kapsam_isler(stmt, user, ServiceOrder.id)


def temel_kimlikler(user: User, f: RaporFiltresi) -> Select:
    """Tarihsiz, kapsamlı iş kümesi (süre kayıtları kendi tarihine göre süzülür)."""
    return kapsam.kapsam_isler(filtre_uygula(select(ServiceOrder.id), f), user, ServiceOrder.id)


# --- KPI ----------------------------------------------------------------------------------


def kpi_tanimi(user: User, kod: str) -> panel.KpiTanimi:
    """Kayıtlı KPI; bilinmeyen → 400, izni yoksa → 403 (kişisel dahil)."""
    tanim = panel.kpi_suzgeci(kod)
    if not user.has(tanim.izin) or (tanim.kisisel and not user.has("servis_rapor.personel")):
        raise RaporYetkiHatasi(f"Bu göstergeyi görme yetkiniz yok: {kod}")
    return tanim


def _suzgec(tanim: panel.KpiTanimi, f: RaporFiltresi):
    """İstekte tekrar arıza penceresi verildiyse aynı tanımın o penceredeki hâli."""
    if f.tekrar_gun is not None and tanim.kod in (
        "rapor_tekrar_ariza_onayli",
        "rapor_tekrar_ariza_aday",
    ):
        return rt.tekrar_ariza_suzgeci(onayli=tanim.kod.endswith("onayli"), gun=f.tekrar_gun)
    return tanim.suzgec


def kpi_sorgusu(
    tanim: panel.KpiTanimi,
    user: User,
    clock: Clock,
    f: RaporFiltresi,
    *secim,
    donem: str | None = None,
) -> Select:
    """Sayı ve listenin TEK sorgusu (rapor süzgeci + KPI süzgeci + kapsam)."""
    stmt = select(*(secim or (ServiceOrder.id,)))
    stmt = filtre_uygula(stmt, f)
    donem = donem or f.donem
    stmt = _suzgec(tanim, f)(stmt, user, clock, donem if tanim.donemsel else None)
    return kapsam.kapsam_isler(stmt, user, ServiceOrder.id)


async def say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def kpi_sayisi(
    db: AsyncSession,
    tanim: panel.KpiTanimi,
    user: User,
    clock: Clock,
    f: RaporFiltresi,
    *,
    donem: str | None = None,
) -> int:
    return await say(db, kpi_sorgusu(tanim, user, clock, f, donem=donem))


def kpi_liste_sorgusu(user: User, clock: Clock, f: RaporFiltresi, kod: str) -> Select:
    """`/raporlar/kpi-liste?kpi=` — `/ozet` sayısının listesi (sayfalanır)."""
    tanim = kpi_tanimi(user, kod)
    return kpi_sorgusu(tanim, user, clock, f, ServiceOrder).order_by(ServiceOrder.created_at.desc())


def isler_yolu(kod: str, f: RaporFiltresi) -> str | None:
    """Servis İşleri ekranında AYNI listeyi açan yol (`/isler?kpi=&donem=`).

    Yalnız o ekranın taşıyabildiği süzgeçlerle mümkündür; çoklu birim,
    kategori, şef, şehir ya da özel tekrar penceresi varsa None (rapor kendi
    `kpi-liste` listesini açar — sayı yine aynı süzgeçten)."""
    if (
        len(f.birim) > 1
        or len(f.tur) > 1
        or len(f.oncelik) > 1
        or len(f.durum_grubu) > 1
        or f.kategori
        or f.sef_id is not None
        or f.sehir is not None
        or f.tekrar_gun is not None
    ):
        return None
    yol = f"/servis-isleri?kpi={kod}&donem={f.donem}"
    for ad, deger in (
        ("birim", f.birim[0] if f.birim else None),
        ("tur", f.tur[0] if f.tur else None),
        ("oncelik", f.oncelik[0] if f.oncelik else None),
        ("durum_grubu", f.durum_grubu[0] if f.durum_grubu else None),
        ("musteri_id", f.musteri_id),
        ("teknisyen_id", f.teknisyen_id),
    ):
        if deger is not None:
            yol += f"&{ad}={deger}"
    return yol


def kapsam_metni(user: User) -> str:
    """Yanıtta ve Excel'de "bu rapor kimin gözüyle" (E12-08 kabul 4)."""
    kapsam_kodu = user.role.scope if user.role is not None else None
    if kapsam_kodu == SCOPE_ALL:
        return "Tüm birimler"
    birimler = ", ".join(BIRIMLER.get(b, b) for b in sorted(kapsam.kullanici_birimleri(user)))
    if kapsam_kodu == SCOPE_OWN_JOBS:
        return f"Atandığım işler ({birimler or 'birim yok'})"
    return f"Birimler: {birimler or 'yok'}"


def _fark(deger, onceki) -> tuple[Any, Any]:
    if deger is None or onceki is None:
        return None, None
    fark = round(deger - onceki, 2) if isinstance(deger, float) else deger - onceki
    yuzde = round(100.0 * (deger - onceki) / onceki, 1) if onceki else None
    return fark, yuzde


def _oran(pay: int | None, payda: int | None) -> float | None:
    if not payda or pay is None:
        return None
    return round(100.0 * pay / payda, 1)


async def _olcumler(
    db: AsyncSession, user: User, clock: Clock, f: RaporFiltresi, sayilar: dict[str, int]
) -> dict[str, Any]:
    from app.services.teknik_servis import rapor_hesap

    ks = await rapor_hesap.kisi_saat_toplami(db, user, f)
    sure = await rapor_hesap.cozum_suresi(db, user, clock, f)
    s = sayilar.get
    ziyaret_paydasi = None
    if s("rapor_cozulen") is not None:
        ziyaret_paydasi = await say(
            db,
            kpi_sorgusu(panel.KPI_TANIMLARI["rapor_cozulen"], user, clock, f).where(
                ServiceOrder.kategori == rt.SLA_KATEGORISI,
                ~rt.uzaktan_kosulu(),
                rt.saha_gun_sayisi() > 0,
            ),
        )
    return {
        "kisi_saat": ks["toplam_saat"],
        "uzaktan_oran": _oran(s("rapor_uzaktan_cozulen"), s("rapor_cozulen")),
        "yeniden_acilma_orani": _oran(s("rapor_yeniden_acilan"), s("rapor_ilk_cozulen")),
        "tekrar_ariza_orani": _oran(s("rapor_tekrar_ariza_onayli"), s("rapor_tekrar_payda")),
        "tekrar_ziyaret_orani": _oran(s("rapor_tekrar_ziyaret"), ziyaret_paydasi),
        "sla_uyum": _oran(
            s("rapor_sla_zamaninda"),
            (s("rapor_sla_zamaninda") or 0) + (s("rapor_sla_asildi") or 0),
        ),
        "cozum_suresi_ort": sure["ortalama_saat"],
        "cozum_suresi_medyan": sure["medyan_saat"],
    }


async def _sayilar(db: AsyncSession, user: User, clock: Clock, f: RaporFiltresi) -> dict[str, int]:
    return {t.kod: await kpi_sayisi(db, t, user, clock, f) for t in rt.rapor_kpileri(user)}


async def toplamlar(db: AsyncSession, user: User, f: RaporFiltresi) -> dict[str, Any]:
    """Detay kümesinin durum grubu dağılımı; `toplam = acik + cozuldu + iptal`.

    Tanımsız durum canlı tabloda oluşamaz (`ck_so_durum`, kontrol B13); göç
    karantinasındaki tanımsızlar Veri Kalitesi sayfasındadır (D3-C)."""
    grup = durum_grubu_ifadesi()
    satir = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(grup == "ACIK"),
                func.count().filter(grup == "COZULDU"),
                func.count().filter(grup == "IPTAL"),
            ).where(ServiceOrder.id.in_(detay_sorgusu(user, f)))
        )
    ).one()
    toplam, acik, cozuldu, iptal = (int(x or 0) for x in satir)
    return {
        "toplam": toplam,
        "acik": acik,
        "cozuldu": cozuldu,
        "iptal": iptal,
        "tanimsiz": 0,
        "esit": toplam == acik + cozuldu + iptal,
    }


async def kategori_ozeti(
    db: AsyncSession, user: User, clock: Clock, f: RaporFiltresi
) -> list[dict[str, Any]]:
    """Kategori ayrımı (eski "Günlük Servis / Planlı Bakım" ikilisi): gelen,
    çözülen, dönem sonu açık — her biri ilgili KPI'nın AYNI süzgecinden."""
    from app.services.teknik_servis import is_emirleri

    sonuc = {
        k: {"kategori": k, "ad": is_emirleri.KATEGORI_ADLARI.get(k, k)} for k in SERVIS_KATEGORILERI
    }
    for kod, alan in (
        ("rapor_gelen", "gelen"),
        ("rapor_cozulen", "cozulen"),
        ("rapor_donem_sonu_acik", "donem_sonu_acik"),
    ):
        tanim = panel.KPI_TANIMLARI[kod]
        stmt = kpi_sorgusu(tanim, user, clock, f, ServiceOrder.kategori, func.count())
        for kategori, adet in (await db.execute(stmt.group_by(ServiceOrder.kategori))).all():
            sonuc[kategori][alan] = int(adet)
    return [
        {"gelen": 0, "cozulen": 0, "donem_sonu_acik": 0, **v}
        for k, v in sonuc.items()
        if not f.kategori or k in f.kategori
    ]


async def gecmis_degisebilir_mi(db: AsyncSession, user: User, f: RaporFiltresi) -> bool:
    """Olay geçmişi olmayan göç işi var mı (dönem sonu açık yedek kurala düşer)."""
    stmt = temel_kimlikler(user, f).where(ServiceOrder.source_system.is_not(None)).limit(1)
    return (await db.scalar(stmt)) is not None


async def ozet(db: AsyncSession, user: User, clock: Clock, f: RaporFiltresi) -> dict[str, Any]:
    """Yönetim özeti: KPI'lar (önceki dönemle), ölçüler, toplam eşitliği."""
    onceki_f = f.onceki()
    sayilar = await _sayilar(db, user, clock, f)
    onceki_sayilar = await _sayilar(db, user, clock, onceki_f)
    olcum = await _olcumler(db, user, clock, f, sayilar)
    onceki_olcum = await _olcumler(db, user, clock, onceki_f, onceki_sayilar)

    kpiler = []
    for t in rt.rapor_kpileri(user):
        fark, yuzde = _fark(sayilar[t.kod], onceki_sayilar[t.kod])
        kpiler.append(
            {
                "kod": t.kod,
                "baslik": t.baslik,
                "tanim": t.tanim,
                "bolum": rt.RAPOR_KPI_BOLUMU[t.kod],
                "olcu_birimi": t.olcu_birimi,
                "vurgu": t.vurgu,
                "deger": sayilar[t.kod],
                "onceki": onceki_sayilar[t.kod],
                "fark": fark,
                "fark_yuzde": yuzde,
                "kpi": t.kod,
                "isler_yolu": isler_yolu(t.kod, f),
            }
        )
    olcumler = []
    for kod, o in rt.OLCULER.items():
        fark, yuzde = _fark(olcum[kod], onceki_olcum[kod])
        olcumler.append(
            {
                "kod": kod,
                "baslik": o.baslik,
                "tanim": o.tanim,
                "olcu_birimi": o.olcu_birimi,
                "deger": olcum[kod],
                "onceki": onceki_olcum[kod],
                "fark": fark,
                "fark_yuzde": yuzde,
                "pay": o.pay,
                "payda": o.payda,
                # Kişi-saat ölçülemediyse kaç çözülmüş işte süre eksik (0 değil "—").
                "eksik": sayilar.get("rapor_sure_eksik") if kod == "kisi_saat" else None,
            }
        )
    return {
        "generated_at": clock.now(),
        "filtreler": f.iso(),
        "kapsam": kapsam_metni(user),
        "donem": {"baslangic": f.baslangic, "bitis": f.bitis, "donem": f.donem},
        "onceki_donem": {
            "baslangic": onceki_f.baslangic,
            "bitis": onceki_f.bitis,
            "donem": onceki_f.donem,
        },
        "bolumler": [{"kod": k, "ad": a} for k, a in rt.BOLUMLER.items()],
        "kpiler": kpiler,
        "olcumler": olcumler,
        "toplamlar": await toplamlar(db, user, f),
        "kategoriler": await kategori_ozeti(db, user, clock, f),
        "eksik_veri_is": sayilar.get("rapor_sure_eksik", 0),
        "gecmis_degisebilir": await gecmis_degisebilir_mi(db, user, f),
    }


# --- Kırılım (TS-184) ------------------------------------------------------------------------

BASIT_BOYUTLAR = ("birim", "kategori", "tur", "oncelik", "durum_grubu", "sef", "cozum_kanali")


def _basit_ifade(boyut: str):
    return {
        "birim": lambda: ServiceOrder.birim,
        "kategori": lambda: ServiceOrder.kategori,
        "tur": lambda: ServiceOrder.tur,
        "oncelik": lambda: ServiceOrder.oncelik,
        "durum_grubu": durum_grubu_ifadesi,
        "sef": _sef_ifadesi,
        "cozum_kanali": _kanal_ifadesi,
    }[boyut]()


def _metrikler(sure_sutunu):
    from app.services.teknik_servis import zaman

    kimlik = distinct(ServiceOrder.id)
    grup = durum_grubu_ifadesi()
    return [
        func.count(kimlik).label("toplam"),
        func.count(kimlik).filter(grup == "ACIK").label("acik"),
        func.count(kimlik).filter(grup == "COZULDU").label("cozuldu"),
        func.count(kimlik).filter(grup == "IPTAL").label("iptal"),
        func.count(kimlik).filter(ServiceOrder.status == "BEKLEMEDE").label("beklemede"),
        func.count(kimlik).filter(ServiceOrder.oncelik == "KRITIK").label("kritik"),
        func.count(kimlik)
        .filter(grup == "COZULDU", zaman.sure_eksik_ifadesi())
        .label("sure_eksik"),
        func.sum(sure_sutunu).label("sn"),
    ]


_METRIK_ADLARI = ("toplam", "acik", "cozuldu", "iptal", "beklemede", "kritik", "sure_eksik")


def _sure_alt_sorgusu(kisi_bazli: bool):
    """İş (ve kişi) başına kişi-saate dahil, kapalı, geçerli saniye — tüm tarihler."""
    saniye = func.extract("epoch", ServiceTimeEntry.ended_at - ServiceTimeEntry.started_at)
    kolonlar = [ServiceTimeEntry.service_order_id.label("so_id")]
    if kisi_bazli:
        kolonlar.append(ServiceTimeEntry.user_id.label("uid"))
    return (
        select(*kolonlar, func.sum(saniye).label("sn"))
        .where(
            ServiceTimeEntry.is_deleted.is_(False),
            ServiceTimeEntry.ended_at.is_not(None),
            ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
        )
        .group_by(*kolonlar)
        .subquery()
    )


def _saat(sn) -> float | None:
    return round(float(sn) / 3600.0, 2) if sn is not None else None


def _topla(hedef: dict[str, Any], kaynak: dict[str, Any]) -> None:
    for ad in _METRIK_ADLARI:
        hedef[ad] = hedef.get(ad, 0) + kaynak[ad]
    if kaynak["sn"] is not None:
        hedef["sn"] = (hedef.get("sn") or 0) + float(kaynak["sn"])
    else:
        hedef.setdefault("sn", None)


async def _adlar(db: AsyncSession, model, kimlikler, sutun) -> dict[int, str]:
    kimlikler = {k for k in kimlikler if k is not None}
    if not kimlikler:
        return {}
    return dict((await db.execute(select(model.id, sutun).where(model.id.in_(kimlikler)))).all())


async def _etiketler(db: AsyncSession, boyut: str, anahtarlar) -> dict[Any, str]:
    from app.services.teknik_servis import is_emirleri, sonuc

    if boyut == "birim":
        return {a: BIRIMLER.get(a, a) for a in anahtarlar}
    if boyut == "kategori":
        return {a: is_emirleri.KATEGORI_ADLARI.get(a, a) for a in anahtarlar}
    if boyut == "tur":
        return {a: is_emirleri.TUR_ADLARI.get(a, a) for a in anahtarlar}
    if boyut == "oncelik":
        return {a: ONCELIK_ADLARI.get(a, a) for a in anahtarlar}
    if boyut == "durum_grubu":
        return {a: DURUM_GRUBU_ADLARI.get(a, a) for a in anahtarlar}
    if boyut == "cozum_kanali":
        return {a: sonuc.KANAL_ADLARI.get(a, a) if a else "Sonuç girilmemiş" for a in anahtarlar}
    if boyut in ("sef", "teknisyen"):
        adlar = await _adlar(db, User, anahtarlar, User.full_name)
        bos = "Şef atanmamış" if boyut == "sef" else "Teknisyen atanmamış"
        return {a: adlar.get(a, "?") if a is not None else bos for a in anahtarlar}
    raise KeyError(boyut)


async def kirilim(
    db: AsyncSession,
    user: User,
    clock: Clock,
    f: RaporFiltresi,
    boyut: str,
    ikinci: str | None = None,
) -> dict[str, Any]:
    """Detay kümesinin `boyut` kırılımı (+ isteğe bağlı ikinci basit boyut).

    Tek değerli boyutlarda satır toplamı = detay toplamı (`toplam_esit`).
    Teknisyen çok değerlidir (bir iş birden çok teknisyende sayılır) ve
    `servis_rapor.personel` ister. Müşteri/şehir/lokasyon E14 anahtarlarıyla
    (`ana_veri.lokasyon_anahtari`, `il_normalize`) gruplanır; eşleşmeyen ham
    metin "Eşleştirilmemiş: …" satırında, boş değer "… belirtilmemiş"tedir.
    """
    if boyut not in rt.BOYUTLAR or (ikinci is not None and ikinci not in BASIT_BOYUTLAR):
        raise RaporHatasi(f"Bilinmeyen kırılım boyutu: {boyut}")
    if boyut in rt.KISISEL_BOYUTLAR and not user.has("servis_rapor.personel"):
        raise RaporYetkiHatasi("Kişi bazlı kırılım için yetkiniz yok (servis_rapor.personel)")
    kimlikler = detay_sorgusu(user, f)
    toplam_is = await say(db, kimlikler)

    if boyut == "teknisyen":
        sure = _sure_alt_sorgusu(kisi_bazli=True)
        atama = (
            select(
                ServiceOrderAssignment.service_order_id.label("so_id"),
                ServiceOrderAssignment.user_id.label("uid"),
            )
            .where(
                ServiceOrderAssignment.removed_at.is_(None),
                ServiceOrderAssignment.rol == "TEKNISYEN",
            )
            .distinct()
            .subquery()
        )
        anahtar_kolonlari = [atama.c.uid]
        stmt = (
            select(atama.c.uid, *_metrikler(sure.c.sn))
            .select_from(ServiceOrder)
            .outerjoin(atama, atama.c.so_id == ServiceOrder.id)
            .outerjoin(sure, (sure.c.so_id == ServiceOrder.id) & (sure.c.uid == atama.c.uid))
        )
    else:
        sure = _sure_alt_sorgusu(kisi_bazli=False)
        if boyut in BASIT_BOYUTLAR:
            anahtar_kolonlari = [_basit_ifade(boyut).label("k1")]
        elif boyut == "musteri":
            anahtar_kolonlari = [ServiceOrder.customer_id, ServiceOrder.customer_name_raw]
        elif boyut == "sehir":
            anahtar_kolonlari = [_sehir_ifadesi().label("sehir")]
        else:  # lokasyon
            anahtar_kolonlari = [
                ServiceOrder.birim,
                ServiceOrder.address_id,
                ServiceOrder.customer_id,
                ServiceOrder.location_raw,
                ServiceOrder.customer_name_raw,
            ]
        if ikinci is not None:
            anahtar_kolonlari.append(_basit_ifade(ikinci).label("k2"))
        stmt = (
            select(*anahtar_kolonlari, *_metrikler(sure.c.sn))
            .select_from(ServiceOrder)
            .outerjoin(sure, sure.c.so_id == ServiceOrder.id)
        )
    stmt = stmt.where(ServiceOrder.id.in_(kimlikler)).group_by(*anahtar_kolonlari)
    ham = (await db.execute(stmt)).all()
    anahtar_sayisi = len(anahtar_kolonlari)
    satirlar_ham = [
        (
            tuple(s[:anahtar_sayisi]),
            dict(zip((*_METRIK_ADLARI, "sn"), s[anahtar_sayisi:], strict=True)),
        )
        for s in ham
    ]
    birlesik = await _birlestir(db, boyut, ikinci, satirlar_ham)
    satirlar = []
    for v in birlesik.values():
        v["kisi_saat"] = _saat(v.pop("sn"))
        satirlar.append(v)
    satirlar.sort(key=lambda r: (-r["toplam"], str(r["ad"]), str(r.get("ikinci_ad") or "")))
    toplam_satir = sum(r["toplam"] for r in satirlar)
    return {
        "boyut": boyut,
        "boyut_adi": rt.BOYUTLAR[boyut],
        "ikinci": ikinci,
        "satirlar": satirlar,
        "toplam": toplam_is,
        "toplam_esit": None if boyut in rt.KISISEL_BOYUTLAR else toplam_satir == toplam_is,
        "generated_at": clock.now(),
        "kapsam": kapsam_metni(user),
    }


async def _birlestir(db, boyut, ikinci, satirlar_ham) -> dict[Any, dict[str, Any]]:
    """Gruplanmış SQL satırlarını görünen anahtara göre birleştirir."""
    from app.services.teknik_servis import ana_veri

    ikinci_etiket = {}
    if ikinci is not None:
        ikinci_etiket = await _etiketler(db, ikinci, {a[-1] for a, _ in satirlar_ham})
    sonuc: dict[Any, dict[str, Any]] = {}

    def ekle(anahtar, ad, metrik, ham_anahtar, **ek):
        ikinci_deger = ham_anahtar[-1] if ikinci is not None else None
        tam = (anahtar, ikinci_deger)
        hedef = sonuc.setdefault(
            tam,
            {
                "anahtar": "" if anahtar is None else str(anahtar),
                "ad": ad,
                **(
                    {"ikinci": ikinci_deger, "ikinci_ad": ikinci_etiket.get(ikinci_deger)}
                    if ikinci
                    else {}
                ),
                **ek,
            },
        )
        _topla(hedef, metrik)

    if boyut in BASIT_BOYUTLAR or boyut == "teknisyen":
        etiket = await _etiketler(db, boyut, {a[0] for a, _ in satirlar_ham})
        for a, m in satirlar_ham:
            ekle(a[0], etiket[a[0]], m, a)
    elif boyut == "musteri":
        adlar = await _adlar(db, Account, {a[0] for a, _ in satirlar_ham}, Account.title)
        for a, m in satirlar_ham:
            musteri_id, ham_ad = a[0], a[1]
            if musteri_id is not None:
                ekle(f"M{musteri_id}", adlar.get(musteri_id, "?"), m, a)
            elif ham_ad:
                ekle(f"E:{ham_ad.strip().upper()}", f"Eşleştirilmemiş: {ham_ad.strip()}", m, a)
            else:
                ekle("-", "Müşteri belirtilmemiş", m, a)
    elif boyut == "sehir":
        for a, m in satirlar_ham:
            ham_il = a[0]
            il = il_normalize(ham_il)
            if il is not None:
                ekle(il, il, m, a)
            elif ham_il and str(ham_il).strip():
                ekle(f"E:{ham_il.strip()}", f"Eşleştirilmemiş: {ham_il.strip()}", m, a)
            else:
                ekle("-", "Şehir belirtilmemiş", m, a)
    else:  # lokasyon
        adres_idler = {a[1] for a, _ in satirlar_ham}
        adresler = {
            r.id: r
            for r in (
                await db.scalars(select(Address).where(Address.id.in_(adres_idler or {0})))
            ).all()
        }
        musteri_adlari = await _adlar(
            db,
            Account,
            {a[2] for a, _ in satirlar_ham} | {r.account_id for r in adresler.values()},
            Account.title,
        )
        for a, m in satirlar_ham:
            birim, address_id, customer_id, location_raw, customer_raw = a[:5]
            kayit = {
                "birim": birim,
                "address_id": address_id,
                "customer_id": customer_id,
                "location_raw": location_raw,
                "customer_name_raw": customer_raw,
            }
            anahtar = ana_veri.lokasyon_anahtari(kayit)
            birim_adi = BIRIMLER.get(birim, birim)
            if anahtar is None:
                ekle(
                    f"{birim}|-",
                    "Lokasyon belirtilmemiş",
                    m,
                    a,
                    musteri=musteri_adlari.get(customer_id)
                    or (f"Eşleştirilmemiş: {customer_raw}" if customer_raw else "—"),
                    sehir="Şehir belirtilmemiş",
                    birim=birim_adi,
                )
            elif anahtar[1] == "L":
                adres = adresler.get(address_id)
                il = il_normalize(adres.city) if adres else None
                ekle(
                    "|".join(str(x) for x in anahtar),
                    (adres.site_name or adres.label or adres.line or f"Adres #{address_id}")
                    if adres
                    else f"Adres #{address_id}",
                    m,
                    a,
                    musteri=musteri_adlari.get(adres.account_id) if adres else None,
                    sehir=il
                    or (
                        f"Eşleştirilmemiş: {adres.city}"
                        if adres and adres.city
                        else "Şehir belirtilmemiş"
                    ),
                    birim=birim_adi,
                )
            else:
                ekle(
                    "|".join(str(x) for x in anahtar),
                    f"Eşleştirilmemiş: {(location_raw or customer_raw or '').strip()}",
                    m,
                    a,
                    musteri=musteri_adlari.get(customer_id)
                    or (f"Eşleştirilmemiş: {customer_raw}" if customer_raw else "—"),
                    sehir="Şehir belirtilmemiş",
                    birim=birim_adi,
                )
    return sonuc


# --- Trend (TS-201) ------------------------------------------------------------------------


def _ay_bas(gun: date) -> date:
    return gun.replace(day=1)


async def trend(db: AsyncSession, user: User, clock: Clock, f: RaporFiltresi) -> dict[str, Any]:
    """Bitiş ayıyla biten 12 takvim ayı: gelen, çözülen, iptal, dönem sonu açık
    (aynı KPI süzgeçleri) ve toplam kişi-saat (kayıt yoksa None, 0 değil)."""
    from app.services.teknik_servis import rapor_hesap

    son_ay = _ay_bas(f.bitis)
    aylar = [panel.ay_ekle(son_ay, -i) for i in range(11, -1, -1)]
    satirlar = []
    for ay in aylar:
        ay_son = panel.ay_ekle(ay, 1) - timedelta(days=1)
        ay_f = replace(f, baslangic=ay, bitis=ay_son)
        satir: dict[str, Any] = {
            "ay": f"{ay:%Y-%m}",
            "ay_adi": f"{AY_ADLARI[ay.month - 1]} {ay.year}",
            "donem": ay_f.donem,
        }
        for kod, alan in (
            ("rapor_gelen", "gelen"),
            ("rapor_cozulen", "cozulen"),
            ("rapor_iptal", "iptal"),
            ("rapor_donem_sonu_acik", "donem_sonu_acik"),
        ):
            satir[alan] = await kpi_sayisi(db, panel.KPI_TANIMLARI[kod], user, clock, ay_f)
        satir["kisi_saat"] = (await rapor_hesap.kisi_saat_toplami(db, user, ay_f))["toplam_saat"]
        satirlar.append(satir)
    return {
        "satirlar": satirlar,
        "gecmis_degisebilir": await gecmis_degisebilir_mi(db, user, f),
        "generated_at": clock.now(),
        "kapsam": kapsam_metni(user),
    }


__all__ = [
    "RaporFiltresi",
    "RaporHatasi",
    "RaporYetkiHatasi",
    "detay_sorgusu",
    "filtre_hazirla",
    "filtre_uygula",
    "isler_yolu",
    "kirilim",
    "kpi_liste_sorgusu",
    "kpi_sayisi",
    "kpi_sorgusu",
    "ozet",
    "trend",
]
