"""Eğitim göçü: V1 eğitim/yetkinlik tabloları → `training_*`, `competencies` (TS-206, E08 K17).

    uv run python -m app.migration.egitim onizleme|uygula|rapor --kaynak <döküm> [--cikti x.xlsx]
    make goc-egitim-onizleme / goc-egitim-uygula / goc-egitim-rapor KAYNAK=<döküm>

**Kişi = `users`** (ayrı personel tablosu yok). V1 `Personnel` satırı şu
sırayla kullanıcıya bağlanır, bağ UYDURULMAZ:

1. `Personnel.ErpUserId` → `ErpUsers.Username` → aynı kullanıcı adlı `users`
   satırı (büyük/küçük harf duyarsız);
2. yoksa İK'nın ONAYLADIĞI ad eşlemesi (`personnel_name_maps`, TS-170) —
   aynı ad iki farklı kişiye onaylıysa belirsizdir, bağlanmaz;
3. ikisi de yoksa kişinin bütün eğitim satırları KARANTİNADA kalır.
   **Otomatik kullanıcı açılmaz** (`--girissiz-ac` yok; girişsiz personel
   önce `personel` profiliyle açılır, sonra göç yeniden koşulur). Uygulama
   modunda eşleşmeyen adlar `Personnel.FullName` alanıyla öneri olarak
   `personnel_name_maps`'e yazılır (karar İK'dadır).

Sıra zorunludur: kurs → kurs maddesi → yetkinlik → yetkinlik değerlendirmesi
→ oturum → katılım → plan. Bağımlı satır, üst kaydı bu koşuda aktarılacak ya
da daha önce aktarılmışsa hazırdır; yoksa karantinadır. Eski
`PersonnelCompetencies` satırı `kaynak='GOC'` ile ilk geçmiş satırı olur.
Saha gözlemleri (`TrainingObservations`) aktarılmaz: sonuç ve madde puanı
yeni kurallarla sunucuda hesaplanır (E08-05); satırlar karantina listesinde
gerekçesiyle görünür.

İdempotent: her hedefte `uq_<tablo>_kaynak` (+ kod/kişi tekilliği) için
`ON CONFLICT DO NOTHING`; ikinci koşu 0 yeni satır. Ekranda aynı kodla
açılmış kurs/yetkinlik EZİLMEZ (karantina). Uzlaşma tablo bazında:
`kaynak = aktarılan + karantina + reddedilen`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx
from app.migration.servis_goc import birim_esle
from app.migration.servis_kaynak import (
    GOC_SISTEMI,
    AdimSonucu,
    KaynakDizini,
    KaynakHatasi,
    bit,
    gun,
    kaynak_ref,
    metin,
    mevcut_refler,
    tamsayi,
    yerel_an,
)
from app.models import (
    Competency,
    CompetencyAssessment,
    TrainingAttendance,
    TrainingCourse,
    TrainingCriterion,
    TrainingPlan,
    TrainingSession,
    User,
)
from app.services import audit
from app.services.normalize import tr_normkey
from app.services.teknik_servis import ad_esleme

ALAN_PERSONEL = "Personnel.FullName"
GOZLEM_NEDENI = (
    "Gözlem göçü yok: sonuç ve madde puanları yeni kurallarla hesaplanır (E08-05); "
    "gerekirse elle girilir"
)

KATEGORI_ESLEME = {
    "teknik": "TEKNIK",
    "isg": "ISG",
    "is guvenligi": "ISG",
    "is sagligi ve guvenligi": "ISG",
    "kisisel gelisim": "KISISEL_GELISIM",
    "is sureci": "IS_SURECI",
    "surec": "IS_SURECI",
}
PLAN_DURUM_ESLEME = {
    "planlandi": "PLANLANDI",
    "ertelendi": "ERTELENDI",
    "basarisiz": "BASARISIZ_TEKRAR",
    "basarisiz tekrar": "BASARISIZ_TEKRAR",
    "tamamlandi": "TAMAMLANDI",
    "iptal": "IPTAL",
}


@dataclass
class Taslak:
    """Yazılmaya hazır satır. `ust`: kolon → üst kaydın kaynak ref'i (id yazmada çözülür)."""

    ref: str
    degerler: dict[str, Any]
    ust: dict[str, tuple[str, str]] = field(default_factory=dict)  # kolon → (hedef, ref)


@dataclass
class Baglam:
    """Hazırlık boyunca paylaşılan eşlemeler."""

    kisiler: dict[int, int | None]  # PersonnelId → user_id (None = eşleşmedi)
    kisi_nedeni: dict[int, str]
    hazir: dict[str, set[str]] = field(default_factory=dict)  # hedef tablo → aktarılmış/planlı ref
    kodlar: dict[str, dict[str, str | None]] = field(default_factory=dict)  # tablo → kod → ref


@dataclass
class Adim:
    kaynak_tablo: str
    kimlik: str
    hedef_tablo: str
    model: Any
    kur: Callable[[dict[str, Any], str, Baglam, AdimSonucu], Taslak | None]


def _ondalik_saat(ham: Any) -> Decimal | None:
    if ham is None or not str(ham).strip():
        return None
    try:
        return Decimal(str(ham).strip().replace(",", ".")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    except InvalidOperation as exc:
        raise ValueError(f"süre okunamadı: {ham}") from exc


def _sinirli(deger: str | None, sinir: int, ad: str) -> str | None:
    """Kolona sığmayan metin KESİLMEZ: ValueError → karantina (kayıp yok)."""
    if deger is not None and len(deger) > sinir:
        raise ValueError(f"{ad} {sinir} karakteri aşıyor")
    return deger


def _kisi(s: dict[str, Any], b: Baglam) -> tuple[int | None, str | None]:
    pid = tamsayi(s.get("PersonnelId"))
    if pid is None:
        return None, "PersonnelId yok"
    if pid not in b.kisiler:
        return None, f"Personnel:{pid} dökümde yok"
    uid = b.kisiler[pid]
    if uid is None:
        return None, f"Personel eşleşmedi (Personnel:{pid}: {b.kisi_nedeni.get(pid, '')})"
    return uid, None


def _ust(b: Baglam, hedef: str, tablo: str, kimlik: Any) -> str | None:
    ref = kaynak_ref(tablo, kimlik)
    return ref if ref in b.hazir.get(hedef, set()) else None


def _kod_carpismasi(b: Baglam, tablo: str, kod: str, ref: str) -> bool:
    """Aynı kod hedefte başka (ekrandan ya da başka kaynak satırdan) kayıtla var mı?"""
    kodlar = b.kodlar.setdefault(tablo, {})
    if kod in kodlar and kodlar[kod] != ref:
        return True
    kodlar[kod] = ref
    return False


# --- Satır kurucular --------------------------------------------------------------


def _kurs(s: dict[str, Any], ref: str, b: Baglam, sonuc: AdimSonucu) -> Taslak | None:
    kod = metin(s.get("CourseCode"))
    if not kod:
        sonuc.karantinaya(ref, "Kurs kodu yok")
        return None
    kategori = KATEGORI_ESLEME.get(tr_normkey(s.get("Category")))
    if kategori is None:
        sonuc.karantinaya(ref, f"Eşlenemeyen kategori: {s.get('Category')}")
        return None
    birim_ham = metin(s.get("UnitCode"))
    birim = birim_esle(birim_ham) if birim_ham else None
    if birim_ham and birim is None:
        sonuc.karantinaya(ref, f"Eşlenemeyen birim: {birim_ham}")
        return None
    try:
        sure = _ondalik_saat(s.get("DurationHours")) or Decimal("2.0")
        degerler = {
            "kod": _sinirli(kod, 30, "Kurs kodu"),
            "baslik": _sinirli(metin(s.get("Title")) or kod, 200, "Başlık"),
        }
    except ValueError as exc:
        sonuc.karantinaya(ref, str(exc))
        return None
    if not Decimal("0.5") <= sure <= Decimal("24"):
        sonuc.karantinaya(ref, f"Süre 0,5–24 saat dışında: {sure}")
        return None
    if _kod_carpismasi(b, "training_courses", kod, ref):
        sonuc.karantinaya(ref, f"'{kod}' kodlu kurs zaten var (ekrandaki kayıt ezilmez)")
        return None
    degerler.update(
        {
            "kategori": kategori,
            "birim": birim,
            "sure_saat": sure,
            "zorunlu": bit(s.get("Mandatory")),
            "is_active": bit(s.get("IsActive"), varsayilan=True),
            "neden": metin(s.get("Reason")),
            "hedef_davranis": metin(s.get("TargetBehavior")),
            "basari_olcutu": metin(s.get("SuccessMetric")),
        }
    )
    return Taslak(ref, degerler)


def _madde(s: dict[str, Any], ref: str, b: Baglam, sonuc: AdimSonucu) -> Taslak | None:
    kurs = _ust(b, "training_courses", "TrainingCourses", s.get("CourseId"))
    if kurs is None:
        sonuc.karantinaya(ref, f"Kursu aktarılmamış (TrainingCourses:{s.get('CourseId')})")
        return None
    try:
        madde = _sinirli(metin(s.get("CriterionText")), 300, "Madde metni")
    except ValueError as exc:
        sonuc.karantinaya(ref, str(exc))
        return None
    if not madde:
        sonuc.karantinaya(ref, "Madde metni yok")
        return None
    return Taslak(
        ref,
        {"metin": madde, "is_critical": bit(s.get("IsCritical")), "_sira": s.get("SortOrder")},
        {"course_id": ("training_courses", kurs)},
    )


def _yetkinlik(s: dict[str, Any], ref: str, b: Baglam, sonuc: AdimSonucu) -> Taslak | None:
    kod = metin(s.get("Code"))
    birim_ham = metin(s.get("UnitCode"))
    birim = birim_esle(birim_ham) if birim_ham else None
    hedef = tamsayi(s.get("SuggestedTargetLevel")) or 3
    try:
        kod = _sinirli(kod, 20, "Yetkinlik kodu")
        ad = _sinirli(metin(s.get("Name")) or kod, 150, "Yetkinlik adı")
    except ValueError as exc:
        sonuc.karantinaya(ref, str(exc))
        return None
    if not kod:
        sonuc.karantinaya(ref, "Yetkinlik kodu yok")
        return None
    if birim_ham and birim is None:
        sonuc.karantinaya(ref, f"Eşlenemeyen birim: {birim_ham}")
        return None
    if not 1 <= hedef <= 4:
        sonuc.karantinaya(ref, f"Önerilen hedef 1–4 dışında: {hedef}")
        return None
    if _kod_carpismasi(b, "competencies", kod, ref):
        sonuc.karantinaya(ref, f"'{kod}' kodlu yetkinlik zaten var (ekrandaki kayıt ezilmez)")
        return None
    return Taslak(
        ref,
        {
            "kod": kod,
            "ad": ad,
            "birim": birim,
            "onerilen_hedef": hedef,
            "is_critical": bit(s.get("IsCritical")),
        },
    )


def _degerlendirme(s: dict[str, Any], ref: str, b: Baglam, sonuc: AdimSonucu) -> Taslak | None:
    uid, neden = _kisi(s, b)
    if uid is None:
        sonuc.karantinaya(ref, neden or "")
        return None
    yetkinlik = _ust(b, "competencies", "CompetencyCatalog", s.get("CompetencyId"))
    if yetkinlik is None:
        sonuc.karantinaya(
            ref, f"Yetkinliği aktarılmamış (CompetencyCatalog:{s.get('CompetencyId')})"
        )
        return None
    mevcut, hedef = tamsayi(s.get("CurrentLevel")), tamsayi(s.get("TargetLevel"))
    if mevcut is None or hedef is None or not (1 <= mevcut <= 4 and 1 <= hedef <= 4):
        sonuc.karantinaya(ref, "Seviye 1–4 dışında ya da boş")
        return None
    try:
        tarih = gun(s.get("AssessedAt"))
        sonraki = gun(s.get("NextReviewDate"))
        degerlendiren = _sinirli(metin(s.get("AssessedBy")), 100, "Değerlendiren")
    except ValueError as exc:
        sonuc.karantinaya(ref, str(exc))
        return None
    if tarih is None:
        sonuc.karantinaya(ref, "Değerlendirme tarihi yok (tarih uydurulmaz)")
        return None
    return Taslak(
        ref,
        {
            "user_id": uid,
            "mevcut_seviye": mevcut,
            "hedef_seviye": hedef,
            "degerlendirme_tarihi": tarih,
            "assessed_by_ad": degerlendiren,
            "kanit": metin(s.get("Evidence")),
            "kaynak": "GOC",
            "sonraki_degerlendirme": sonraki,
        },
        {"competency_id": ("competencies", yetkinlik)},
    )


def _oturum(s: dict[str, Any], ref: str, b: Baglam, sonuc: AdimSonucu) -> Taslak | None:
    kurs = _ust(b, "training_courses", "TrainingCourses", s.get("CourseId"))
    if kurs is None:
        sonuc.karantinaya(ref, f"Kursu aktarılmamış (TrainingCourses:{s.get('CourseId')})")
        return None
    try:
        tarih = gun(s.get("SessionDate"))
        sure = _ondalik_saat(s.get("DurationHours"))
        egitmen = _sinirli(metin(s.get("TrainerName")), 120, "Eğitmen")
        yer = _sinirli(metin(s.get("Location")), 200, "Yer")
    except ValueError as exc:
        sonuc.karantinaya(ref, str(exc))
        return None
    if tarih is None:
        sonuc.karantinaya(ref, "Oturum tarihi yok")
        return None
    if sure is None or not Decimal("0.5") <= sure <= Decimal("24"):
        sonuc.karantinaya(ref, f"Süre 0,5–24 saat dışında: {s.get('DurationHours')}")
        return None
    return Taslak(
        ref,
        {
            "oturum_tarihi": tarih,
            "egitmen_ad": egitmen,
            "sure_saat": sure,
            "yer": yer,
            "notlar": metin(s.get("Notes")),
        },
        {"course_id": ("training_courses", kurs)},
    )


def _katilim(s: dict[str, Any], ref: str, b: Baglam, sonuc: AdimSonucu) -> Taslak | None:
    uid, neden = _kisi(s, b)
    if uid is None:
        sonuc.karantinaya(ref, neden or "")
        return None
    oturum = _ust(b, "training_sessions", "TrainingSessions", s.get("TrainingSessionId"))
    if oturum is None:
        sonuc.karantinaya(
            ref, f"Oturumu aktarılmamış (TrainingSessions:{s.get('TrainingSessionId')})"
        )
        return None
    on, son = tamsayi(s.get("ScoreBefore")), tamsayi(s.get("ScoreAfter"))
    if any(p is not None and not 0 <= p <= 100 for p in (on, son)):
        sonuc.karantinaya(ref, "Puan 0–100 dışında")
        return None
    return Taslak(
        ref,
        {
            "user_id": uid,
            "katildi": bit(s.get("Attended"), varsayilan=True),
            "on_puan": on,
            "son_puan": son,
            "notlar": metin(s.get("Notes")),
        },
        {"session_id": ("training_sessions", oturum)},
    )


def _plan(s: dict[str, Any], ref: str, b: Baglam, sonuc: AdimSonucu) -> Taslak | None:
    uid, neden = _kisi(s, b)
    if uid is None:
        sonuc.karantinaya(ref, neden or "")
        return None
    kurs = _ust(b, "training_courses", "TrainingCourses", s.get("CourseId"))
    if kurs is None:
        sonuc.karantinaya(ref, f"Kursu aktarılmamış (TrainingCourses:{s.get('CourseId')})")
        return None
    durum = PLAN_DURUM_ESLEME.get(tr_normkey(s.get("Status") or "Planlandı"))
    if durum is None:
        sonuc.karantinaya(ref, f"Eşlenemeyen plan durumu: {s.get('Status')}")
        return None
    yil = tamsayi(s.get("PlanYear"))
    try:
        hedef = gun(s.get("DueDate"))
        tamam = yerel_an(s.get("CompletedAt"))
    except ValueError as exc:
        sonuc.karantinaya(ref, str(exc))
        return None
    if yil is None or not 2020 <= yil <= 2100:
        sonuc.karantinaya(ref, f"Plan yılı 2020–2100 dışında: {s.get('PlanYear')}")
        return None
    if hedef is None:
        sonuc.karantinaya(ref, "Hedef tarih yok (tarih uydurulmaz)")
        return None
    if durum == "TAMAMLANDI" and tamam is None:
        sonuc.karantinaya(ref, "Tamamlandı ama tamamlanma tarihi yok (tarih uydurulmaz)")
        return None
    return Taslak(
        ref,
        {
            "user_id": uid,
            "plan_yili": yil,
            "hedef_tarih": hedef,
            "gelisim_hedefi": metin(s.get("PersonalGoal")),
            "status": durum,
            "durum_gerekcesi": (
                "Göç: eski sistemdeki durum" if durum in ("ERTELENDI", "IPTAL") else None
            ),
            "completed_on": tamam.date() if durum == "TAMAMLANDI" and tamam else None,
        },
        {"course_id": ("training_courses", kurs)},
    )


ADIMLAR: tuple[Adim, ...] = (
    Adim("TrainingCourses", "CourseId", "training_courses", TrainingCourse, _kurs),
    Adim("TrainingCriteria", "CriterionId", "training_criteria", TrainingCriterion, _madde),
    Adim("CompetencyCatalog", "CompetencyId", "competencies", Competency, _yetkinlik),
    Adim(
        "PersonnelCompetencies",
        "PersonnelCompetencyId",
        "competency_assessments",
        CompetencyAssessment,
        _degerlendirme,
    ),
    Adim("TrainingSessions", "TrainingSessionId", "training_sessions", TrainingSession, _oturum),
    Adim(
        "TrainingAttendance",
        "TrainingAttendanceId",
        "training_attendance",
        TrainingAttendance,
        _katilim,
    ),
    Adim("TrainingPlans", "TrainingPlanId", "training_plans", TrainingPlan, _plan),
)
GOZLEM_TABLOSU = "TrainingObservations"


# --- Kişi eşleme ----------------------------------------------------------------------


async def kisi_eslemesi(db: AsyncSession, dizin: KaynakDizini) -> Baglam:
    """`Personnel` → users (ErpUserId → Username, sonra onaylı ad eşlemesi)."""
    erp = {
        k: (metin(u.get("Username")) or "").casefold()
        for u in dizin.tablo("ErpUsers", zorunlu=False)
        if (k := tamsayi(u.get("UserId"))) is not None
    }
    kullanici_adlari: dict[str, int] = {
        ad.casefold(): uid for uid, ad in (await db.execute(select(User.id, User.username))).all()
    }
    alanlar = tuple(dict.fromkeys((*ad_esleme.KAYNAK_ALANLARI, ALAN_PERSONEL)))
    adlar = ad_esleme.ada_gore(await ad_esleme.onayli_harita(db, alanlar), alanlar)
    kisiler: dict[int, int | None] = {}
    nedenler: dict[int, str] = {}
    for p in dizin.tablo("Personnel", zorunlu=False):
        pid = tamsayi(p.get("PersonnelId"))
        if pid is None:
            continue
        erp_id = tamsayi(p.get("ErpUserId"))
        kullanici = erp.get(erp_id) if erp_id is not None else None
        if kullanici and kullanici in kullanici_adlari:
            kisiler[pid] = kullanici_adlari[kullanici]
            nedenler[pid] = "ERP_KULLANICI"
            continue
        norm = ad_esleme.normal_ad(p.get("FullName"))
        if norm in adlar and adlar[norm] is not None:
            kisiler[pid] = adlar[norm]
            nedenler[pid] = "ONAYLI_AD"
            continue
        kisiler[pid] = None
        if norm in adlar:
            nedenler[pid] = "ad iki farklı kişiye onaylı (belirsiz)"
        elif erp_id is not None and kullanici:
            nedenler[pid] = f"ErpUsers '{kullanici}' kullanıcı adı sistemde yok; onaylı ad yok"
        else:
            nedenler[pid] = "ErpUserId yok/eşleşmedi; onaylı ad eşlemesi yok"
    return Baglam(kisiler=kisiler, kisi_nedeni=nedenler)


async def _ref_kimlikleri(db: AsyncSession, model: Any) -> dict[str, int]:
    return dict(
        (
            await db.execute(
                select(model.source_ref, model.id).where(model.source_system == GOC_SISTEMI)
            )
        )
        .tuples()
        .all()
    )


async def _kod_haritasi(db: AsyncSession, model: Any) -> dict[str, str | None]:
    return {
        kod: (ref if sistem == GOC_SISTEMI else None)
        for kod, sistem, ref in (
            await db.execute(select(model.kod, model.source_system, model.source_ref))
        ).all()
    }


# --- Hazırla / yükle ----------------------------------------------------------------


@dataclass
class Kosu:
    sonuclar: list[AdimSonucu] = field(default_factory=list)
    baglam: Baglam | None = None


async def hazirla(db: AsyncSession, dizin: KaynakDizini) -> Kosu:
    """Hiçbir şey yazmaz. Üst kaydı bu koşuda aktarılacak satır da hazır sayılır."""
    b = await kisi_eslemesi(db, dizin)
    b.kodlar = {
        "training_courses": await _kod_haritasi(db, TrainingCourse),
        "competencies": await _kod_haritasi(db, Competency),
    }
    kosu = Kosu(baglam=b)
    for adim in ADIMLAR:
        satirlar = dizin.tablo(adim.kaynak_tablo, zorunlu=False)
        sonuc = AdimSonucu(adim.kaynak_tablo, adim.hedef_tablo, kaynak=len(satirlar))
        var = await mevcut_refler(db, adim.hedef_tablo, adim.kaynak_tablo)
        gorulen: set[str] = set()
        for sira, s in enumerate(satirlar, start=1):
            kimlik = tamsayi(s.get(adim.kimlik))
            if kimlik is None:
                sonuc.reddet(f"{adim.kaynak_tablo} satır {sira}", f"{adim.kimlik} yok")
                continue
            ref = kaynak_ref(adim.kaynak_tablo, kimlik)
            if ref in gorulen:
                sonuc.reddet(ref, "dökümde aynı kimlik iki kez")
                continue
            gorulen.add(ref)
            if ref in var:
                # Daha önce aktarılmış: yeniden kurulmaz (kod çakışması sanılmasın).
                sonuc.aktarilacak.append(Taslak(ref, {}))
                continue
            t = adim.kur(s, ref, b, sonuc)
            if t is not None:
                sonuc.aktarilacak.append(t)
        b.hazir[adim.hedef_tablo] = var | {t.ref for t in sonuc.aktarilacak}
        sonuc.mevcut = sum(1 for t in sonuc.aktarilacak if t.ref in var)
        sonuc.yeni = len(sonuc.aktarilacak) - sonuc.mevcut
        kosu.sonuclar.append(sonuc)
    gozlemler = dizin.tablo(GOZLEM_TABLOSU, zorunlu=False)
    gozlem = AdimSonucu(GOZLEM_TABLOSU, "training_observations", kaynak=len(gozlemler))
    for sira, s in enumerate(gozlemler, start=1):
        kimlik = tamsayi(s.get("ObservationId"))
        if kimlik is None:
            gozlem.reddet(f"{GOZLEM_TABLOSU} satır {sira}", "ObservationId yok")
        else:
            gozlem.karantinaya(kaynak_ref(GOZLEM_TABLOSU, kimlik), GOZLEM_NEDENI)
    kosu.sonuclar.append(gozlem)
    return kosu


async def yukle(
    db: AsyncSession, kosu: Kosu, *, dizin: KaynakDizini | None = None, user_id: int | None = None
) -> Kosu:
    """Adımları sırayla yazar (commit ÇAĞIRANDA). Yalnız ilk kez gelen satır eklenir."""
    modeller = {a.hedef_tablo: a.model for a in ADIMLAR}
    for adim, sonuc in zip(ADIMLAR, kosu.sonuclar, strict=False):
        idler: dict[str, dict[str, int]] = {}
        sira_sayaci: dict[int, int] = {}
        eklenen = 0
        sirali = sorted(
            (t for t in sonuc.aktarilacak if t.degerler),
            key=lambda t: (str(t.ust), tamsayi(t.degerler.get("_sira")) or 0, t.ref),
        )
        for t in sirali:
            degerler = {k: v for k, v in t.degerler.items() if not k.startswith("_")}
            eksik = False
            for kolon, (hedef, ust_ref) in t.ust.items():
                if hedef not in idler:
                    idler[hedef] = await _ref_kimlikleri(db, modeller[hedef])
                if ust_ref not in idler[hedef]:
                    eksik = True
                    break
                degerler[kolon] = idler[hedef][ust_ref]
            if eksik:
                continue
            if adim.model is TrainingCriterion:
                kurs_id = degerler["course_id"]
                if kurs_id not in sira_sayaci:
                    sira_sayaci[kurs_id] = int(
                        await db.scalar(
                            select(func.coalesce(func.max(TrainingCriterion.sira), 0)).where(
                                TrainingCriterion.course_id == kurs_id
                            )
                        )
                        or 0
                    )
                sira_sayaci[kurs_id] += 1
                degerler["sira"] = sira_sayaci[kurs_id]
            stmt = (
                insert(adim.model.__table__)
                .values(
                    **degerler,
                    source_system=GOC_SISTEMI,
                    source_ref=t.ref,
                    created_by=user_id,
                    **({"updated_by": user_id} if hasattr(adim.model, "updated_by") else {}),
                )
                .on_conflict_do_nothing()
                .returning(adim.model.__table__.c.id)
            )
            if (await db.execute(stmt)).scalar() is not None:
                eklenen += 1
        sonuc.yeni = eklenen
        sonuc.mevcut = len(sonuc.aktarilacak) - eklenen
        await audit.log(db, adim.hedef_tablo, "goc.egitim", new_value=sonuc.ozet(), user_id=user_id)
    b = kosu.baglam
    if dizin is not None and b is not None:
        adlar = {
            tamsayi(p.get("PersonnelId")): metin(p.get("FullName"))
            for p in dizin.tablo("Personnel", zorunlu=False)
        }
        await ad_esleme.oneri_kaydet(
            db,
            [
                (ALAN_PERSONEL, adlar.get(pid) or "")
                for pid, uid in b.kisiler.items()
                if uid is None
            ],
            user_id=user_id,
        )
    return kosu


async def uzlasma(db: AsyncSession, kosu: Kosu) -> list[dict[str, Any]]:
    """Tablo bazında `kaynak = aktarılan + karantina + reddedilen`; bekleyen 0 olmalı."""
    satirlar: list[dict[str, Any]] = []
    for s in kosu.sonuclar:
        var = await mevcut_refler(db, s.hedef_tablo, s.kaynak_tablo)
        aktarilacak = {t.ref for t in s.aktarilacak}
        karantina = {r for r, _ in s.karantina}
        aktarilan = len((aktarilacak | karantina) & var)
        karantina_kalan = len(karantina - var)
        bekleyen = len(aktarilacak - var)
        toplam = aktarilan + karantina_kalan + len(s.reddedilen) + bekleyen
        satirlar.append(
            {
                "kaynak_tablo": s.kaynak_tablo,
                "hedef_tablo": s.hedef_tablo,
                "kaynak": s.kaynak,
                "aktarilan": aktarilan,
                "karantina": karantina_kalan,
                "reddedilen": len(s.reddedilen),
                "bekleyen": bekleyen,
                "tutarli": s.kaynak == toplam and bekleyen == 0,
            }
        )
    return satirlar


def rapor_xlsx(kosu: Kosu, uzlasma_satirlari: list[dict[str, Any]], dizin: KaynakDizini) -> bytes:
    ozet = Sayfa(
        [
            "Kaynak Tablo",
            "Hedef Tablo",
            "Kaynak",
            "Aktarılan",
            "Karantina",
            "Reddedilen",
            "Bekleyen",
            "Tutarlı",
        ],
        [
            [
                u["kaynak_tablo"],
                u["hedef_tablo"],
                u["kaynak"],
                u["aktarilan"],
                u["karantina"],
                u["reddedilen"],
                u["bekleyen"],
                "EVET" if u["tutarli"] else "HAYIR",
            ]
            for u in uzlasma_satirlari
        ],
    )
    karantina = Sayfa(["Kaynak Tablo", "Kaynak Ref", "Neden"])
    reddedilen = Sayfa(["Kaynak Tablo", "Kaynak", "Neden"])
    for s in kosu.sonuclar:
        karantina.satirlar += [[s.kaynak_tablo, r, n] for r, n in s.karantina]
        reddedilen.satirlar += [[s.kaynak_tablo, r, n] for r, n in s.reddedilen]
    b = kosu.baglam
    personel = Sayfa(["Personnel Id", "Ad", "Kullanıcı Id", "Yöntem / Neden"])
    if b is not None:
        adlar = {
            tamsayi(p.get("PersonnelId")): metin(p.get("FullName"))
            for p in dizin.tablo("Personnel", zorunlu=False)
        }
        personel.satirlar = [
            [pid, adlar.get(pid), uid, b.kisi_nedeni.get(pid)]
            for pid, uid in sorted(b.kisiler.items())
        ]
    return cok_sayfali_xlsx(
        {"Uzlasma": ozet, "Karantina": karantina, "Reddedilen": reddedilen, "Personel": personel}
    )


async def _calistir(args: argparse.Namespace) -> int:
    from app.db import get_engine, get_session_factory

    dizin = KaynakDizini(args.kaynak)
    engine = get_engine()
    try:
        async with get_session_factory()() as db:
            kosu = await hazirla(db, dizin)
            if args.mod == "uygula":
                await yukle(db, kosu, dizin=dizin)
                await db.commit()
            satirlar = await uzlasma(db, kosu)
            if args.mod != "uygula":
                await db.rollback()
    finally:
        await engine.dispose()
    print("=" * 96)
    print(
        f"EĞİTİM GÖÇÜ — {args.mod.upper()}"
        + (" (HİÇBİR ŞEY YAZILMADI)" if args.mod != "uygula" else "")
    )
    print("=" * 96)
    for s, u in zip(kosu.sonuclar, satirlar, strict=True):
        print(
            f"{u['kaynak_tablo']:24s}{u['kaynak']:>8}{u['aktarilan']:>11}{u['karantina']:>11}"
            f"{u['reddedilen']:>12}{u['bekleyen']:>10}{s.yeni:>7}  "
            + ("TUTARLI" if u["tutarli"] else ("UYGULANMADI" if args.mod == "onizleme" else "FARK"))
        )
    if args.cikti:
        args.cikti.write_bytes(rapor_xlsx(kosu, satirlar, dizin))
        print(f"\nUzlaşma raporu: {args.cikti}")
    if args.mod == "rapor" and not all(u["tutarli"] for u in satirlar):
        return 2
    return 0


def komut_satiri(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Eğitim göçü (Göç-2) ve uzlaşma")
    ayr.add_argument("mod", choices=("onizleme", "uygula", "rapor"), nargs="?", default="onizleme")
    ayr.add_argument("--kaynak", type=Path, required=True, help="CSV döküm dizini")
    ayr.add_argument("--cikti", type=Path, help="Uzlaşma raporu xlsx")
    args = ayr.parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(_calistir(args))
    except KaynakHatasi as exc:
        print(f"Kaynak okunamadı: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(komut_satiri())
