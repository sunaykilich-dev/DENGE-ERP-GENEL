"""Eski ad bazlı kayıtların onaylı personel eşlemesi (TS-170, E13-08).

V1.20.1 kişiyi kimlikle değil AD METNİYLE tutuyordu (`WorkOrderAssignments.
AssignedName`, `WorkOrderTimeLogs.TechnicianName` ...). Aynı kişi "Ali Veli",
"ALİ VELİ", "Ali  Veli" olarak geçiyor; kişi bazlı her sayı (kişi-saat, iş
adedi) ancak bu metin bir `users` kimliğine bağlanınca doğru çıkar.

**Eşleme UYDURULMAZ.** Akış:

1. `oneri_kaydet` — göç betiği eski adları sayar; her (alan, normal ad) için
   `personnel_name_maps` satırı `ONERI` durumunda açılır. Öneri yalnız ÖNERİDİR:
   önce birebir normal ad, sonra trigram benzerliği (pg_trgm ile aynı
   algoritma, saf Python — sınanabilir ve DB'ye bağlı değil).
2. İK öneri Excel'ini inceler, `ad_esleme` içe aktarma profiliyle KARAR yükler
   (ONAYLANDI / REDDEDILDI / ESLESMEDI). Daha önce verilmiş karar öneri
   güncellemesinde EZİLMEZ.
3. `uygula` — yalnız `ONAYLANDI` satırlar göç tablolarına işlenir; ham metin
   (`kaynak_personel_adi`) korunur. İkinci koşu hiçbir satırı değiştirmez.

Servis fonksiyonları yalnız `flush` yapar; commit çağırandadır.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select

from app.models import PersonnelNameMap, ServiceTimeEntry, User
from app.services import audit
from app.services.normalize import tr_normkey

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

KAYNAK_SISTEM = "V1_20_1"
# Göç kaydının `source_system` değeri (plan §5.3).
GOC_SISTEMI = "DENGEERP_V1"

# Ad metni taşıyan eski kaynak alanlar. Zaman kaydı alanları `uygula` ile
# `service_time_entries`'e işlenir; atama alanı servis işi göçünde okunur.
ALAN_ATAMA = "WorkOrderAssignments.AssignedName"
ALAN_ZAMAN = "WorkOrderTimeLogs.TechnicianName"
ALAN_CANLI_OTURUM = "WorkOrderLiveSessions.TechnicianName"
ZAMAN_ALANLARI = (ALAN_ZAMAN, ALAN_CANLI_OTURUM)
KAYNAK_ALANLARI = (ALAN_ATAMA, ALAN_ZAMAN, ALAN_CANLI_OTURUM)

# Trigram önerisi eşiği. Altında öneri boş kalır (insan seçer).
ONERI_ESIGI = 0.5

YONTEM_BIREBIR = "BIREBIR"
YONTEM_TRGM = "TRGM"


def normal_ad(ham: str | None) -> str:
    """Türkçe katlanmış, tek boşluklu, BÜYÜK harf ad (eşleme anahtarı)."""
    return re.sub(r"\s+", " ", tr_normkey(ham)).strip().upper()[:150]


def _trigramlar(metin: str) -> set[str]:
    """pg_trgm ile aynı kural: her sözcük "  w " biçiminde doldurulur."""
    kume: set[str] = set()
    for sozcuk in re.findall(r"[0-9a-z]+", tr_normkey(metin)):
        dolu = f"  {sozcuk} "
        kume.update(dolu[i : i + 3] for i in range(len(dolu) - 2))
    return kume


def benzerlik(a: str, b: str) -> float:
    """pg_trgm `similarity()` karşılığı: |A∩B| / |A∪B|."""
    ta, tb = _trigramlar(a), _trigramlar(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass(frozen=True)
class Oneri:
    kaynak_ad: str
    normal_ad: str
    user_id: int | None
    kullanici_ad: str | None
    yontem: str | None
    skor: float


async def _kisiler(db: AsyncSession) -> list[tuple[int, str, bool]]:
    return [
        (uid, ad, aktif)
        for uid, ad, aktif in (
            await db.execute(select(User.id, User.full_name, User.is_active).order_by(User.id))
        ).all()
        if ad
    ]


def _oner(ad: str, kisiler: list[tuple[int, str, bool]]) -> Oneri:
    norm = normal_ad(ad)
    birebir = [k for k in kisiler if normal_ad(k[1]) == norm]
    if birebir:
        # Aynı adlı iki kişi: aktif olan önce; yine birden çoksa öneri YOK
        # (iki "Ali Veli" arasında seçim insana kalır).
        aktifler = [k for k in birebir if k[2]] or birebir
        if len(aktifler) == 1:
            return Oneri(ad, norm, aktifler[0][0], aktifler[0][1], YONTEM_BIREBIR, 1.0)
        return Oneri(ad, norm, None, None, None, 1.0)
    en_iyi: tuple[float, int, str] | None = None
    for uid, kad, _aktif in kisiler:
        skor = benzerlik(ad, kad)
        if skor >= ONERI_ESIGI and (en_iyi is None or skor > en_iyi[0]):
            en_iyi = (skor, uid, kad)
    if en_iyi is None:
        return Oneri(ad, norm, None, None, None, 0.0)
    return Oneri(ad, norm, en_iyi[1], en_iyi[2], YONTEM_TRGM, round(en_iyi[0], 3))


async def oneriler(db: AsyncSession, adlar: list[str]) -> list[dict[str, Any]]:
    """trgm yalnız öneri üretir; karar İK onayıyla `ad_esleme` profilinde."""
    kisiler = await _kisiler(db)
    return [_oner(ad, kisiler).__dict__ for ad in adlar]


async def oneri_kaydet(
    db: AsyncSession,
    kayitlar: Iterable[tuple[str, str]],
    *,
    user_id: int | None = None,
) -> dict[str, int]:
    """(kaynak_alan, ham ad) çiftlerinden öneri satırlarını açar/günceller.

    Aynı (alan, normal ad) tek satırdır (`uq_pnm_kaynak`); `kaynak_ad` en sık
    görülen yazımdır, `kayit_sayisi` toplam geçiştir. KARAR VERİLMİŞ satırın
    (ONAYLANDI/REDDEDILDI/ESLESMEDI) yalnız sayısı güncellenir; öneri ve karar
    korunur — göç yeniden koşunca İK'nın onayı kaybolmaz.
    """
    gruplar: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for alan, ham in kayitlar:
        ham = (ham or "").strip()
        if not ham:
            continue
        gruplar[(alan, normal_ad(ham))][ham] += 1

    sayac = {"yeni": 0, "guncellenen": 0, "karari_korunan": 0}
    if not gruplar:
        return sayac
    kisiler = await _kisiler(db)
    mevcut = {
        (m.kaynak_alan, m.normal_ad): m
        for m in (
            await db.scalars(
                select(PersonnelNameMap).where(PersonnelNameMap.kaynak_sistem == KAYNAK_SISTEM)
            )
        ).all()
    }
    for (alan, norm), yazimlar in sorted(gruplar.items()):
        kaynak_ad = yazimlar.most_common(1)[0][0][:150]
        adet = sum(yazimlar.values())
        satir = mevcut.get((alan, norm))
        if satir is None:
            oneri = _oner(kaynak_ad, kisiler)
            db.add(
                PersonnelNameMap(
                    kaynak_sistem=KAYNAK_SISTEM,
                    kaynak_alan=alan,
                    kaynak_ad=kaynak_ad,
                    normal_ad=norm,
                    kayit_sayisi=adet,
                    onerilen_user_id=oneri.user_id,
                    durum="ONERI",
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            sayac["yeni"] += 1
            continue
        if satir.durum != "ONERI":
            if satir.kayit_sayisi != adet:
                satir.kayit_sayisi = adet
            sayac["karari_korunan"] += 1
            continue
        oneri = _oner(satir.kaynak_ad, kisiler)
        if satir.kayit_sayisi != adet or satir.onerilen_user_id != oneri.user_id:
            satir.kayit_sayisi = adet
            satir.onerilen_user_id = oneri.user_id
            satir.updated_by = user_id
            sayac["guncellenen"] += 1
    await db.flush()
    return sayac


async def onayli_harita(
    db: AsyncSession, alanlar: Iterable[str] | None = None
) -> dict[tuple[str, str], int]:
    """(kaynak_alan, normal_ad) → onaylanan kullanıcı. Yalnız ONAYLANDI."""
    stmt = select(PersonnelNameMap).where(
        PersonnelNameMap.kaynak_sistem == KAYNAK_SISTEM,
        PersonnelNameMap.durum == "ONAYLANDI",
        PersonnelNameMap.onaylanan_user_id.is_not(None),
    )
    if alanlar is not None:
        stmt = stmt.where(PersonnelNameMap.kaynak_alan.in_(list(alanlar)))
    return {
        (m.kaynak_alan, m.normal_ad): m.onaylanan_user_id for m in (await db.scalars(stmt)).all()
    }


def ada_gore(harita: dict[tuple[str, str], int], alanlar: Iterable[str]) -> dict[str, int | None]:
    """Birden çok alanın onayını tek ad sözlüğünde birleştirir.

    Aynı ad iki alanda FARKLI kişiye onaylandıysa değer `None` olur (belirsiz,
    uygulanmaz ve raporlanır) — iki onaydan birini seçmek uydurma olurdu.
    """
    sonuc: dict[str, int | None] = {}
    alan_kumesi = set(alanlar)
    for (alan, norm), uid in harita.items():
        if alan not in alan_kumesi:
            continue
        if norm in sonuc and sonuc[norm] != uid:
            sonuc[norm] = None
        else:
            sonuc.setdefault(norm, uid)
    return sonuc


async def cakisan_var_mi(
    db: AsyncSession, user_id: int, bas, bit, *, haric_id: int | None = None
) -> bool:
    """Kişinin silinmemiş zaman kayıtlarında `[bas, bit)` ile kesişen var mı."""
    stmt = select(ServiceTimeEntry.id).where(
        ServiceTimeEntry.user_id == user_id,
        ServiceTimeEntry.is_deleted.is_(False),
        ServiceTimeEntry.started_at < bit,
        (ServiceTimeEntry.ended_at.is_(None)) | (ServiceTimeEntry.ended_at > bas),
    )
    if haric_id is not None:
        stmt = stmt.where(ServiceTimeEntry.id != haric_id)
    return await db.scalar(stmt.limit(1)) is not None


async def uygula(db: AsyncSession, *, clock: Clock, user_id: int | None = None) -> dict[str, int]:
    """Onaylı eşlemeyi göçle gelmiş, kişisi boş zaman kayıtlarına işler.

    Yalnız `user_id IS NULL AND kaynak_personel_adi IS NOT NULL` göç satırları
    taranır; ikinci koşuda bu küme ya boştur ya da hâlâ onaysız adlardır →
    0 değişiklik (idempotent). Ham ad metni korunur.

    Kişiye bağlanınca aynı kişinin başka kaydıyla çakışacak satır SİLİNMEZ:
    `GOC_CAKISMA` iptal türüyle saklanır (E09 K21) — çakışmayı EXCLUDE kısıtı
    zaten reddederdi, satırı atmak ise veri kaybı olurdu.
    """
    harita = ada_gore(await onayli_harita(db, ZAMAN_ALANLARI), ZAMAN_ALANLARI)
    sayac = {"baglanan": 0, "cakisma": 0, "eslesmeyen": 0, "belirsiz": 0}
    satirlar = (
        await db.scalars(
            select(ServiceTimeEntry)
            .where(
                and_(
                    ServiceTimeEntry.user_id.is_(None),
                    ServiceTimeEntry.kaynak_personel_adi.is_not(None),
                    ServiceTimeEntry.source_system == GOC_SISTEMI,
                )
            )
            .order_by(ServiceTimeEntry.started_at, ServiceTimeEntry.id)
        )
    ).all()
    for satir in satirlar:
        norm = normal_ad(satir.kaynak_personel_adi)
        if norm not in harita:
            sayac["eslesmeyen"] += 1
            continue
        hedef = harita[norm]
        if hedef is None:
            sayac["belirsiz"] += 1
            continue
        if not satir.is_deleted and await cakisan_var_mi(
            db, hedef, satir.started_at, satir.ended_at, haric_id=satir.id
        ):
            satir.is_deleted = True
            satir.iptal_turu = "GOC_CAKISMA"
            satir.iptal_gerekcesi = "Ad eşlemesi sonrası kişinin başka kaydıyla çakışıyor"
            sayac["cakisma"] += 1
        satir.user_id = hedef
        satir.updated_by = user_id
        await db.flush()
        sayac["baglanan"] += 1
    if sayac["baglanan"]:
        await audit.log(
            db,
            "service_time_entries",
            "ad_esleme.uygula",
            new_value={**sayac, "an": clock.now().isoformat()},
            user_id=user_id,
        )
    return sayac
