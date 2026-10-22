"""Yetkinlik kataloğu ve değerlendirme geçmişi (E08-03/16/17/19).

Maddeler: TS-150 (değerlendirme geçmişi), TS-160 (katalog yönetimi).

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

from sqlalchemy import Select, select

from app.models import Competency, CompetencyAssessment, TrainingObservation, User
from app.services import audit
from app.services.teknik_servis import kapsam
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
