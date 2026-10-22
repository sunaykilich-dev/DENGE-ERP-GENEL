"""Yetkinlik kataloğu ve değerlendirme geçmişi (E08-03/16/17/19).

Maddeler: TS-150 (değerlendirme geçmişi), TS-160 (katalog yönetimi), TS-198
(kurs↔yetkinlik bağı + "yeniden değerlendir" listesi E08-16 P3; servis işi
türü → asgari yetkinlik eşlemesi ve atamada YALNIZ UYARI E08-22 — kanca
`atama_uyarilari`, atama engellenmez, K11).

**Yalnız ekleme (K15):** `competency_assessments` satırı düzeltilmez; yeni
değerlendirme yeni satırdır, geçmiş kaybolmaz. "Güncel seviye" tablosu
AÇILMAZ — `DISTINCT ON (user_id, competency_id) ORDER BY
degerlendirme_tarihi DESC, id DESC` ile okunur (`ix_cas_son`). Sayfalı
matriste sıralama açıkça `user_id, competency_id` ile tekilleştirilir:
`sayfala`'nın PK kırılması ham kolonlu sorguya eklenmez (kontrol §2/8).

**Kapsam:** başka birimin yetkinliğine yazma/değerlendirme 403 (katalog
gizli değildir); kişi kapsam dışı 404; pasif yetkinlik 400; öz-değerlendirme
409 (personel = kullanıcı olduğu için doğrudan uygulanır, E08-17). Kritik
yetkinlikte kanıt zorunlu (400).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, delete, exists, func, or_, select

from app.models import (
    Competency,
    CompetencyAssessment,
    CourseCompetency,
    ServiceCompetencyRequirement,
    TrainingObservation,
    User,
)
from app.services import audit
from app.services.teknik_servis import kancalar, kapsam
from app.services.teknik_servis.egitim import (
    EgitimBulunamadi,
    EgitimGirdiHatasi,
    EgitimHatasi,
    _kod_cakisiyor,
    _tarih_dogrula,
    birim_dogrula,
    calisan_kosulu,
    kisi_getir,
    kurs_birimi_dogrula,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


def guncel_alt_sorgu():
    """Kişi × yetkinlik başına SON değerlendirme (DISTINCT ON alt sorgusu)."""
    return (
        select(CompetencyAssessment)
        .distinct(CompetencyAssessment.user_id, CompetencyAssessment.competency_id)
        .order_by(
            CompetencyAssessment.user_id,
            CompetencyAssessment.competency_id,
            CompetencyAssessment.degerlendirme_tarihi.desc(),
            CompetencyAssessment.id.desc(),
        )
        .subquery("son_cas")
    )


async def guncel_seviyeler(db: AsyncSession, user_ids: list[int]) -> list[Any]:
    """DISTINCT ON (user_id, competency_id) son değerlendirme."""
    if not user_ids:
        return []
    stmt = (
        select(CompetencyAssessment)
        .where(CompetencyAssessment.user_id.in_(user_ids))
        .distinct(CompetencyAssessment.user_id, CompetencyAssessment.competency_id)
        .order_by(
            CompetencyAssessment.user_id,
            CompetencyAssessment.competency_id,
            CompetencyAssessment.degerlendirme_tarihi.desc(),
            CompetencyAssessment.id.desc(),
        )
    )
    return list((await db.scalars(stmt)).all())


def matris_sorgusu(
    user: User,
    *,
    birim: str | None = None,
    kisi_id: int | None = None,
    competency_id: int | None = None,
    hedef_alti: bool = False,
    yalniz_kritik: bool = False,
) -> Select:
    """Yetkinlik matrisi satırları (kişi × yetkinlik güncel seviyesi).

    KPI "hedefin altında" ve liste AYNI fonksiyondan (sayı = liste). Kapsam
    `kapsam_personel`; ayrılan personel ve pasif yetkinlik dışarıda.
    """
    from app.models import UserUnit

    son = guncel_alt_sorgu()
    stmt = (
        select(
            son.c.id,
            son.c.user_id,
            User.full_name.label("ad"),
            son.c.competency_id,
            Competency.kod,
            Competency.ad.label("yetkinlik"),
            Competency.is_critical,
            Competency.birim,
            son.c.mevcut_seviye,
            son.c.hedef_seviye,
            son.c.degerlendirme_tarihi,
            son.c.sonraki_degerlendirme,
            son.c.kaynak,
        )
        .join(User, User.id == son.c.user_id)
        .join(Competency, Competency.id == son.c.competency_id)
        .where(calisan_kosulu(), Competency.is_deleted.is_(False))
        .order_by(User.full_name, son.c.user_id, Competency.kod, son.c.competency_id)
    )
    stmt = kapsam.kapsam_personel(stmt, user, son.c.user_id)
    if birim:
        stmt = stmt.where(
            select(UserUnit.user_id)
            .where(UserUnit.user_id == son.c.user_id, UserUnit.birim == birim_dogrula(birim))
            .exists()
        )
    if kisi_id is not None:
        stmt = stmt.where(son.c.user_id == kisi_id)
    if competency_id is not None:
        stmt = stmt.where(son.c.competency_id == competency_id)
    if hedef_alti:
        stmt = stmt.where(son.c.mevcut_seviye < son.c.hedef_seviye, Competency.is_active.is_(True))
    if yalniz_kritik:
        stmt = stmt.where(Competency.is_critical.is_(True))
    return stmt


# --- Katalog (TS-160) ------------------------------------------------------------------

YETKINLIK_ALANLARI = ("kod", "ad", "birim", "onerilen_hedef", "is_critical", "is_active")


def _alanlar(alanlar: dict[str, Any]) -> dict[str, Any]:
    temiz = {k: v for k, v in alanlar.items() if k in YETKINLIK_ALANLARI}
    if "kod" in temiz:
        temiz["kod"] = (temiz["kod"] or "").strip().upper()
        if not temiz["kod"]:
            raise EgitimGirdiHatasi("Yetkinlik kodu boş olamaz.")
    if "ad" in temiz:
        temiz["ad"] = (temiz["ad"] or "").strip()
        if not temiz["ad"]:
            raise EgitimGirdiHatasi("Yetkinlik adı boş olamaz.")
    if "birim" in temiz:
        temiz["birim"] = birim_dogrula(temiz["birim"])
    if temiz.get("onerilen_hedef") is not None and not 1 <= temiz["onerilen_hedef"] <= 4:
        raise EgitimGirdiHatasi("Önerilen hedef 1–4 arasında olmalı.")
    return temiz


async def yetkinlik_olustur(
    db: AsyncSession, alanlar: dict[str, Any], *, user: User, ip: str | None = None
) -> Competency:
    temiz = _alanlar(alanlar)
    kurs_birimi_dogrula(user, temiz.get("birim"))
    if await _kod_cakisiyor(db, Competency, temiz["kod"], None):
        raise EgitimHatasi(f"'{temiz['kod']}' kodlu yetkinlik zaten var.")
    y = Competency(**temiz, created_by=user.id, updated_by=user.id)
    db.add(y)
    await db.flush()
    await audit.log(
        db,
        "competencies",
        "olustur",
        entity_id=y.id,
        new_value={"kod": y.kod, "ad": y.ad, "birim": y.birim},
        user_id=user.id,
        ip=ip,
    )
    return y


async def yetkinlik_getir(db: AsyncSession, yetkinlik_id: int) -> Competency:
    y = await db.get(Competency, yetkinlik_id)
    if y is None or y.is_deleted:
        raise EgitimBulunamadi("Yetkinlik bulunamadı")
    return y


async def yetkinlik_guncelle(
    db: AsyncSession, y: Competency, alanlar: dict[str, Any], *, user: User, ip: str | None = None
) -> Competency:
    """Başka birimin yetkinliği ya da başka birime taşıma 403. Pasif yetkinlik
    matris formunda seçilmez, geçmişte görünür."""
    kurs_birimi_dogrula(user, y.birim)
    temiz = _alanlar(alanlar)
    if "birim" in temiz:
        kurs_birimi_dogrula(user, temiz["birim"])
    if "kod" in temiz and await _kod_cakisiyor(db, Competency, temiz["kod"], y.id):
        raise EgitimHatasi(f"'{temiz['kod']}' kodlu yetkinlik zaten var.")
    for k, v in temiz.items():
        setattr(y, k, v)
    y.updated_by = user.id
    await audit.log_change(db, y, "guncelle", user_id=user.id, ip=ip)
    await db.flush()
    return y


# --- Değerlendirme (TS-150, E08-03) ------------------------------------------------------


@dataclass
class DegerlendirmeGirdisi:
    user_id: int
    competency_id: int
    mevcut_seviye: int
    hedef_seviye: int | None = None
    degerlendirme_tarihi: date | None = None
    kanit: str | None = None
    observation_id: int | None = None
    sonraki_degerlendirme: date | None = None


async def degerlendirme_ekle(
    db: AsyncSession,
    veri: DegerlendirmeGirdisi,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> tuple[CompetencyAssessment, list[str]]:
    from app.services.teknik_servis.yerel_zaman import yerel_bugun

    if veri.user_id == user.id:
        raise EgitimHatasi("Kendi yetkinliğinizi değerlendiremezsiniz.")
    await kisi_getir(db, user, veri.user_id)
    y = await yetkinlik_getir(db, veri.competency_id)
    kurs_birimi_dogrula(user, y.birim)
    if not y.is_active:
        raise EgitimGirdiHatasi(f"'{y.ad}' pasif bir yetkinlik; değerlendirilemez.")
    hedef = veri.hedef_seviye if veri.hedef_seviye is not None else y.onerilen_hedef
    for seviye in (veri.mevcut_seviye, hedef):
        if not 1 <= seviye <= 4:
            raise EgitimGirdiHatasi("Seviye 1–4 arasında olmalı.")
    tarih = veri.degerlendirme_tarihi or yerel_bugun(clock)
    _tarih_dogrula(tarih, clock, "Değerlendirme")
    kanit = (veri.kanit or "").strip() or None
    if y.is_critical and not kanit:
        raise EgitimGirdiHatasi("Kritik yetkinlikte kanıt/açıklama zorunlu.")
    kaynak = "YONETICI"
    if veri.observation_id is not None:
        gozlem = await db.get(TrainingObservation, veri.observation_id)
        if gozlem is None or gozlem.user_id != veri.user_id or gozlem.is_deleted:
            raise EgitimGirdiHatasi("Gözlem bu kişiye ait değil.")
        kaynak = "GOZLEM"
    kayit = CompetencyAssessment(
        user_id=veri.user_id,
        competency_id=y.id,
        mevcut_seviye=veri.mevcut_seviye,
        hedef_seviye=hedef,
        degerlendirme_tarihi=tarih,
        assessed_by_user_id=user.id,
        assessed_by_ad=(user.full_name or "")[:100],
        kanit=kanit,
        kaynak=kaynak,
        observation_id=veri.observation_id,
        sonraki_degerlendirme=veri.sonraki_degerlendirme,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(kayit)
    await db.flush()
    await audit.log(
        db,
        "competency_assessments",
        "olustur",
        entity_id=kayit.id,
        new_value={
            "user_id": kayit.user_id,
            "competency_id": y.id,
            "mevcut": kayit.mevcut_seviye,
            "hedef": hedef,
        },
        user_id=user.id,
        ip=ip,
        is_personal_data=True,
    )
    uyarilar = []
    if hedef < veri.mevcut_seviye:
        uyarilar.append("Hedef seviye mevcut seviyenin altında.")
    return kayit, uyarilar


async def gecmis(db: AsyncSession, kisi_id: int) -> list[tuple[CompetencyAssessment, Competency]]:
    """Kişinin bütün değerlendirmeleri, yeniden eskiye (zaman çizelgesi)."""
    return [
        (a, c)
        for a, c in (
            await db.execute(
                select(CompetencyAssessment, Competency)
                .join(Competency, Competency.id == CompetencyAssessment.competency_id)
                .where(CompetencyAssessment.user_id == kisi_id)
                .order_by(
                    CompetencyAssessment.degerlendirme_tarihi.desc(),
                    CompetencyAssessment.id.desc(),
                )
            )
        ).all()
    ]


# =============================================================================
# Kurs ↔ yetkinlik bağı ve "yeniden değerlendir" listesi (E08-16 P3, TS-198)
# =============================================================================


async def kurs_yetkinlikleri(db: AsyncSession, kurs_id: int) -> list[Competency]:
    """Kursa bağlı yetkinlikler (kurs kartında gösterilir)."""
    return list(
        (
            await db.scalars(
                select(Competency)
                .join(CourseCompetency, CourseCompetency.competency_id == Competency.id)
                .where(CourseCompetency.course_id == kurs_id, Competency.is_deleted.is_(False))
                .order_by(Competency.kod)
            )
        ).all()
    )


async def kurs_yetkinlik_bagla(
    db: AsyncSession,
    kurs_id: int,
    yetkinlik_idler: list[int],
    *,
    user: User,
    ip: str | None = None,
) -> list[Competency]:
    """Kursun yetkinlik bağlarını verilen kümeyle DEĞİŞTİRİR.

    Başka birimin kursu/yetkinliği 403 (K4); pasif yetkinlik bağlanamaz (400).
    Bağ yalnız "yeniden değerlendir" listesini besler — seviye otomatik
    değişmez (K18). Değişiklik denetime yazılır.
    """
    from app.services.teknik_servis.egitim import kurs_getir

    kurs = await kurs_getir(db, kurs_id)
    kurs_birimi_dogrula(user, kurs.birim)
    hedef = sorted(set(yetkinlik_idler))
    for yid in hedef:
        y = await yetkinlik_getir(db, yid)
        kurs_birimi_dogrula(user, y.birim)
        if not y.is_active:
            raise EgitimGirdiHatasi(f"'{y.ad}' pasif bir yetkinlik; kursa bağlanamaz.")
    mevcut = set(
        (
            await db.scalars(
                select(CourseCompetency.competency_id).where(CourseCompetency.course_id == kurs.id)
            )
        ).all()
    )
    for yid in mevcut - set(hedef):
        await db.execute(
            delete(CourseCompetency).where(
                CourseCompetency.course_id == kurs.id, CourseCompetency.competency_id == yid
            )
        )
    for yid in set(hedef) - mevcut:
        db.add(CourseCompetency(course_id=kurs.id, competency_id=yid))
    if mevcut != set(hedef):
        await audit.log(
            db,
            "course_competencies",
            "guncelle",
            entity_id=kurs.id,
            old_value={"yetkinlikler": sorted(mevcut)},
            new_value={"yetkinlikler": hedef},
            user_id=user.id,
            ip=ip,
        )
    await db.flush()
    return await kurs_yetkinlikleri(db, kurs.id)


def yeniden_degerlendir_sorgusu(
    user: User, *, birim: str | None = None, kisi_id: int | None = None
) -> Select:
    """Aşama 90 BAŞARILI gözlemi olup, gözlem tarihinden SONRA o kursa bağlı
    yetkinlikte değerlendirmesi olmayan kişi × yetkinlik (hesaplanır, K18).

    Kişi × yetkinlik başına EN SON başarılı 90. gün gözlemi esas alınır;
    değerlendirme girilince satır listeden düşer. Kapsam `kapsam_personel`;
    ayrılan personel, iptal gözlem, pasif yetkinlik dışarıda.
    """
    from app.models import TrainingCourse, UserUnit

    son = (
        select(
            TrainingObservation.user_id.label("user_id"),
            CourseCompetency.competency_id.label("competency_id"),
            func.max(TrainingObservation.gozlem_tarihi).label("gozlem_tarihi"),
        )
        .join(CourseCompetency, CourseCompetency.course_id == TrainingObservation.course_id)
        .where(
            TrainingObservation.asama == 90,
            TrainingObservation.sonuc == "BASARILI",
            TrainingObservation.cancelled_at.is_(None),
            TrainingObservation.is_deleted.is_(False),
        )
        .group_by(TrainingObservation.user_id, CourseCompetency.competency_id)
        .subquery("son_basarili_90")
    )
    sonraki_degerlendirme = exists().where(
        CompetencyAssessment.user_id == son.c.user_id,
        CompetencyAssessment.competency_id == son.c.competency_id,
        CompetencyAssessment.degerlendirme_tarihi >= son.c.gozlem_tarihi,
    )
    kurslar = (
        select(func.string_agg(TrainingCourse.baslik, ", "))
        .join(CourseCompetency, CourseCompetency.course_id == TrainingCourse.id)
        .where(CourseCompetency.competency_id == son.c.competency_id)
        .scalar_subquery()
    )
    stmt = (
        select(
            son.c.user_id,
            User.full_name.label("ad"),
            son.c.competency_id,
            Competency.kod,
            Competency.ad.label("yetkinlik"),
            Competency.is_critical,
            son.c.gozlem_tarihi,
            kurslar.label("kurslar"),
        )
        .join(User, User.id == son.c.user_id)
        .join(Competency, Competency.id == son.c.competency_id)
        .where(
            calisan_kosulu(),
            Competency.is_active.is_(True),
            Competency.is_deleted.is_(False),
            ~sonraki_degerlendirme,
        )
        .order_by(son.c.gozlem_tarihi, User.full_name, son.c.user_id, son.c.competency_id)
    )
    stmt = kapsam.kapsam_personel(stmt, user, son.c.user_id)
    if birim:
        stmt = stmt.where(
            exists().where(
                UserUnit.user_id == son.c.user_id, UserUnit.birim == birim_dogrula(birim)
            )
        )
    if kisi_id is not None:
        stmt = stmt.where(son.c.user_id == kisi_id)
    return stmt


# =============================================================================
# Servis işi türü → asgari yetkinlik ve atama uyarısı (E08-22, TS-198)
# =============================================================================


async def gereksinimler(
    db: AsyncSession, *, birim: str | None = None, tur: str | None = None
) -> list[tuple[ServiceCompetencyRequirement, Competency]]:
    stmt = (
        select(ServiceCompetencyRequirement, Competency)
        .join(Competency, Competency.id == ServiceCompetencyRequirement.competency_id)
        .order_by(
            ServiceCompetencyRequirement.birim,
            ServiceCompetencyRequirement.tur,
            Competency.kod,
        )
    )
    if birim:
        stmt = stmt.where(ServiceCompetencyRequirement.birim == birim_dogrula(birim))
    if tur:
        stmt = stmt.where(ServiceCompetencyRequirement.tur == tur)
    return [(g, c) for g, c in (await db.execute(stmt)).all()]


@dataclass
class GereksinimSatiri:
    competency_id: int
    min_seviye: int
    course_id: int | None = None


async def gereksinim_kaydet(
    db: AsyncSession,
    birim: str,
    tur: str,
    satirlar: list[GereksinimSatiri],
    *,
    user: User,
    ip: str | None = None,
) -> list[tuple[ServiceCompetencyRequirement, Competency]]:
    """`(birim, tür)` eşlemesini verilen satırlarla DEĞİŞTİRİR (boş liste = eşleme yok).

    Birim yetkisi: başka birimin eşlemesi 403. Yetkinlik/kurs başka birimin
    kataloğundaysa 403, pasif yetkinlik 400, tür katalog dışıysa 400.
    """
    from app.models import TrainingCourse
    from app.models.teknik_servis import SERVIS_TURLERI
    from app.services.teknik_servis.egitim import kurs_getir

    birim_kodu = birim_dogrula(birim)
    if birim_kodu is None:
        raise EgitimGirdiHatasi("Birim zorunlu.")
    if tur not in SERVIS_TURLERI:
        raise EgitimGirdiHatasi(f"Bilinmeyen servis işi türü: {tur}")
    kurs_birimi_dogrula(user, birim_kodu)
    goruldu: set[int] = set()
    for s in satirlar:
        if s.competency_id in goruldu:
            raise EgitimGirdiHatasi("Aynı yetkinlik iki kez yazılamaz.")
        goruldu.add(s.competency_id)
        if not 1 <= s.min_seviye <= 4:
            raise EgitimGirdiHatasi("Asgari seviye 1–4 arasında olmalı.")
        y = await yetkinlik_getir(db, s.competency_id)
        kurs_birimi_dogrula(user, y.birim)
        if not y.is_active:
            raise EgitimGirdiHatasi(f"'{y.ad}' pasif bir yetkinlik.")
        if s.course_id is not None:
            kurs: TrainingCourse = await kurs_getir(db, s.course_id)
            kurs_birimi_dogrula(user, kurs.birim)
    eski = [
        {"competency_id": g.competency_id, "min_seviye": g.min_seviye, "course_id": g.course_id}
        for g, _ in await gereksinimler(db, birim=birim_kodu, tur=tur)
    ]
    await db.execute(
        delete(ServiceCompetencyRequirement).where(
            ServiceCompetencyRequirement.birim == birim_kodu,
            ServiceCompetencyRequirement.tur == tur,
        )
    )
    await db.flush()
    for s in satirlar:
        db.add(
            ServiceCompetencyRequirement(
                birim=birim_kodu,
                tur=tur,
                competency_id=s.competency_id,
                min_seviye=s.min_seviye,
                course_id=s.course_id,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    await db.flush()
    await audit.log(
        db,
        "service_competency_requirements",
        "guncelle",
        entity_id=f"{birim_kodu}:{tur}",
        old_value={"satirlar": eski},
        new_value={
            "satirlar": [
                {
                    "competency_id": s.competency_id,
                    "min_seviye": s.min_seviye,
                    "course_id": s.course_id,
                }
                for s in satirlar
            ]
        },
        user_id=user.id,
        ip=ip,
    )
    return await gereksinimler(db, birim=birim_kodu, tur=tur)


async def _kurs_gecerli_mi(db: AsyncSession, user_id: int, kurs: Any, bugun: date) -> bool:
    """Kişinin bu kursu geçerli olarak tamamlamış mı: en son tamamlanan plan
    (yenileme süresi varsa süresi dolmamış) ya da iptal edilmemiş, süresi
    dolmamış belge. Tek tanım `egitim_rapor` geçerlilik kuralıyla aynıdır."""
    from app.models import PersonnelCertificate, TrainingPlan
    from app.services.teknik_servis.bakim import ay_ekle

    son = await db.scalar(
        select(func.max(TrainingPlan.completed_on)).where(
            TrainingPlan.user_id == user_id,
            TrainingPlan.course_id == kurs.id,
            TrainingPlan.status == "TAMAMLANDI",
            TrainingPlan.is_deleted.is_(False),
        )
    )
    if son is not None and (kurs.yenileme_ay is None or ay_ekle(son, kurs.yenileme_ay) >= bugun):
        return True
    belge = await db.scalar(
        select(PersonnelCertificate.id)
        .where(
            PersonnelCertificate.user_id == user_id,
            PersonnelCertificate.course_id == kurs.id,
            PersonnelCertificate.cancelled_at.is_(None),
            or_(
                PersonnelCertificate.gecerlilik_bitis.is_(None),
                PersonnelCertificate.gecerlilik_bitis >= bugun,
            ),
        )
        .limit(1)
    )
    return belge is not None


async def atama_uyarilari(
    db: AsyncSession,
    so: Any,
    user_ids: tuple[int, ...] | list[int],
    *,
    clock: Clock | None = None,
) -> list[str]:
    """Atanan teknisyenler için yetkinlik/belge uyarıları (E08-22, K11).

    YALNIZ OKUR; atamayı ENGELLEMEZ. İşin `(birim, tür)` eşlemesi boşsa boş
    liste. Her kişi için: güncel seviye < asgari (ya da hiç değerlendirme
    yok), eşlemedeki zorunlu kursun geçerli tamamlanması/belgesi yok, kişide
    açık kritik düzeltici faaliyet var. PB işlerinde de iş başına değerlendirilir
    (toplu atamada çağıran her iş için ayrı çağırır); PB üretimine dokunulmaz.

    `kancalar.atama_uyarilari` imzasında saat yok (plan §1.8); çağıran saat
    vermezse gerçek saat (`RealClock`) kullanılır — yalnız belge geçerliliği
    için.
    """
    from app.clock import RealClock
    from app.models import TrainingCorrectiveAction, TrainingCourse
    from app.services.teknik_servis.yerel_zaman import yerel_bugun

    kimlikler = sorted({int(i) for i in user_ids})
    if not kimlikler or so is None:
        return []
    esleme = await gereksinimler(db, birim=so.birim, tur=so.tur)
    acik_kritik = set(
        (
            await db.scalars(
                select(TrainingCorrectiveAction.user_id).where(
                    TrainingCorrectiveAction.user_id.in_(kimlikler),
                    TrainingCorrectiveAction.status == "ACIK",
                )
            )
        ).all()
    )
    if not esleme and not acik_kritik:
        return []
    bugun = yerel_bugun(clock or RealClock())
    adlar = dict(
        (await db.execute(select(User.id, User.full_name).where(User.id.in_(kimlikler)))).all()
    )
    seviyeler = {
        (a.user_id, a.competency_id): a.mevcut_seviye for a in await guncel_seviyeler(db, kimlikler)
    }
    kurslar: dict[int, Any] = {}
    uyarilar: list[str] = []
    for uid in kimlikler:
        ad = adlar.get(uid) or f"#{uid}"
        for g, c in esleme:
            seviye = seviyeler.get((uid, c.id))
            if seviye is None:
                uyarilar.append(
                    f"{ad}: {c.ad} ({c.kod}) yetkinliği değerlendirilmemiş; "
                    f"bu iş için asgari seviye {g.min_seviye}."
                )
            elif seviye < g.min_seviye:
                uyarilar.append(
                    f"{ad}: {c.ad} ({c.kod}) seviyesi {seviye}, bu iş için asgari {g.min_seviye}."
                )
            if g.course_id is not None:
                if g.course_id not in kurslar:
                    kurslar[g.course_id] = await db.get(TrainingCourse, g.course_id)
                kurs = kurslar[g.course_id]
                if kurs is not None and not await _kurs_gecerli_mi(db, uid, kurs, bugun):
                    uyarilar.append(
                        f"{ad}: '{kurs.baslik}' eğitimi tamamlanmamış ya da geçerliliği dolmuş."
                    )
        if uid in acik_kritik:
            uyarilar.append(f"{ad}: açık kritik düzeltici faaliyeti var.")
    return uyarilar


async def _atama_uyarisi_kancasi(db: AsyncSession, so: Any, user_ids: tuple[int, ...]) -> list[str]:
    """`kancalar.atama_uyarilari` kaydı (imza plan §1.8)."""
    return await atama_uyarilari(db, so, user_ids)


kancalar.kaydet("atama_uyarilari", _atama_uyarisi_kancasi)
