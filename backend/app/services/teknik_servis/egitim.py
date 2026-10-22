"""Eğitim çekirdeği: katalog, toplu plan, oturum/katılım, plan kuralları (E08).

Maddeler: TS-150…152, TS-158 (çekirdek, tamamlama kuralı, düzeltme/iptal,
toplu katılım). Servis yalnız `flush` yapar; `commit` API'dedir ve denetim
izi aynı transaction'da, commit'ten ÖNCE yazılır.

**Kişi = `users`** (E08 K1): eğitimin öznesi kullanıcıdır; birim
`user_units`'ten, kapsam `kapsam.kapsam_personel` ile. "Çalışan personel"
= `is_active AND ayrilis_tarihi IS NULL`; girişsiz personel (`giris_acik =
false`) BİLEREK süzülmez — sahadaki stajyerin de eğitim planı vardır
(E08 kontrol §1/3).

**Plan tamamlama kuralı (E08-04, TS-151) tek fonksiyondadır**
(`katilim_isle`): tek kişilik katılım ucu ve toplu katılım aynı kuralı
kullanır. "Katıldı" → aynı kişi+kurs için `plan_yili <= oturum yılı` olan
açık planlardan EN ESKİSİ (`plan_yili, hedef_tarih, id`) TAMAMLANDI olur;
sonraki yılın planı önceki yılın oturumuyla kapanmaz. "Katılmadı"ya
düzeltme, bu oturumla kapanan planı PLANLANDI'ya geri açar (makinedeki tek
geri geçiş; önceki ERTELENDI/BASARISIZ_TEKRAR etiketi kaybolur, hedef tarih
korunur — kontrol §2/6).

**Hata sınıfları:** `EgitimHatasi` kural (409), `EgitimGirdiHatasi` girdi
(400; toplu katılımda `satir` taşır), `EgitimBulunamadi` kapsam dışı / yok
(404), `EgitimYasak` başka birimin katalog öğesi (403, K4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    TrainingAttendance,
    TrainingCourse,
    TrainingCriterion,
    TrainingPlan,
    TrainingSession,
    User,
)
from app.models.egitim import EGITIM_KATEGORILERI, PLAN_DURUMLARI
from app.models.rbac import BIRIM_KODLARI
from app.services import audit
from app.services import settings as ayar_svc
from app.services.statemachine import EGITIM_PLANI, IzinsizGecis
from app.services.teknik_servis import kapsam
from app.services.teknik_servis.yerel_zaman import yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


# Açık (tamamlanmayı bekleyen) plan durumları — tamamlama, uyarı ve KPI aynı küme.
ACIK_PLAN_DURUMLARI = ("PLANLANDI", "ERTELENDI", "BASARISIZ_TEKRAR")
TOPLU_KATILIM_UST_SINIR = 300
if not set(ACIK_PLAN_DURUMLARI) <= set(PLAN_DURUMLARI):  # pragma: no cover - sözlük kilidi
    raise RuntimeError("ACIK_PLAN_DURUMLARI, PLAN_DURUMLARI'nın alt kümesi olmalı")


class EgitimHatasi(ValueError):
    """Eğitim iş kuralı ihlali → 409 (girdi hatası 400)."""

    kod = 409

    def __init__(self, mesaj: str, *, satir: int | None = None) -> None:
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.satir = satir


class EgitimGirdiHatasi(EgitimHatasi):
    """Girdi hatası (ileri tarih, pasif kurs, gerekçesiz iptal) → 400."""

    kod = 400


class EgitimBulunamadi(EgitimHatasi):
    """Kayıt yok ya da kapsam dışı → 404 (kimlik taranamasın, KD-05)."""

    kod = 404


class EgitimYasak(EgitimHatasi):
    """Gövdedeki katalog öğesi başka birimin → 403 (K4)."""

    kod = 403


# --- Ortak yardımcılar -------------------------------------------------------------


def calisan_kosulu():
    """Çalışan personel: aktif ve ayrılmamış. `giris_acik` süzülmez (E13)."""
    return and_(User.is_active.is_(True), User.ayrilis_tarihi.is_(None))


def birim_dogrula(birim: str | None) -> str | None:
    if birim is None or birim == "":
        return None
    deger = birim.strip().upper()
    if deger not in BIRIM_KODLARI:
        raise EgitimGirdiHatasi(f"Bilinmeyen birim: {birim}")
    return deger


async def kisi_getir(db: AsyncSession, user: User, kisi_id: int) -> User:
    """Kapsamdaki kişi; yoksa ya da kapsam dışıysa 404 (veri değişmez)."""
    kisi = await db.get(User, kisi_id)
    if kisi is None or await kapsam.personel_disinda_mi(db, user, kisi_id):
        raise EgitimBulunamadi("Personel bulunamadı")
    return kisi


async def kurs_getir(db: AsyncSession, kurs_id: int) -> TrainingCourse:
    kurs = await db.get(TrainingCourse, kurs_id)
    if kurs is None or kurs.is_deleted:
        raise EgitimBulunamadi("Eğitim (kurs) bulunamadı")
    return kurs


def kurs_birimi_dogrula(user: User, birim: str | None) -> None:
    """Başka birimin kursu/yetkinliği → 403 (katalog gizli değildir, K4)."""
    if kapsam.katalog_birim_yasak_mi(user, birim):
        raise EgitimYasak("Bu kayıt başka bir birimin kataloğunda; işlem yetkiniz yok.")


async def kullanilabilir_kurs(db: AsyncSession, user: User, kurs_id: int) -> TrainingCourse:
    """Plan/oturum/gözlemde başvurulan kurs: var, aktif (400) ve birimi yasak değil (403)."""
    kurs = await kurs_getir(db, kurs_id)
    kurs_birimi_dogrula(user, kurs.birim)
    if not kurs.is_active:
        raise EgitimGirdiHatasi(f"'{kurs.baslik}' pasif bir eğitim; plan/oturum açılamaz.")
    return kurs


def _gerekce(deger: str | None, ne: str) -> str:
    temiz = (deger or "").strip()
    if not temiz:
        raise EgitimGirdiHatasi(f"{ne} için gerekçe zorunlu.")
    return temiz


def _gecis(mevcut: str, hedef: str) -> None:
    try:
        EGITIM_PLANI.dogrula(mevcut, hedef)
    except IzinsizGecis as exc:
        raise EgitimHatasi(str(exc)) from exc


# --- Katalog (TS-150 / TS-152) -----------------------------------------------------

KURS_ALANLARI = (
    "kod",
    "baslik",
    "kategori",
    "birim",
    "sure_saat",
    "zorunlu",
    "neden",
    "hedef_davranis",
    "basari_olcutu",
    "gozlem_esik_yuzde",
    "sinav_gecme_puani",
    "yenileme_ay",
    "is_active",
)


def _kurs_alanlari_dogrula(alanlar: dict[str, Any]) -> dict[str, Any]:
    temiz = {k: v for k, v in alanlar.items() if k in KURS_ALANLARI}
    if "kod" in temiz:
        temiz["kod"] = (temiz["kod"] or "").strip().upper()
        if not temiz["kod"]:
            raise EgitimGirdiHatasi("Eğitim kodu boş olamaz.")
    if "baslik" in temiz:
        temiz["baslik"] = (temiz["baslik"] or "").strip()
        if not temiz["baslik"]:
            raise EgitimGirdiHatasi("Eğitim adı boş olamaz.")
    if "kategori" in temiz and temiz["kategori"] not in EGITIM_KATEGORILERI:
        raise EgitimGirdiHatasi(f"Bilinmeyen kategori: {temiz['kategori']}")
    if "birim" in temiz:
        temiz["birim"] = birim_dogrula(temiz["birim"])
    return temiz


async def _kod_cakisiyor(db: AsyncSession, model, kod: str, haric_id: int | None) -> bool:
    stmt = select(model.id).where(model.kod == kod)
    if haric_id is not None:
        stmt = stmt.where(model.id != haric_id)
    return (await db.scalar(stmt)) is not None


async def kurs_olustur(
    db: AsyncSession, alanlar: dict[str, Any], *, user: User, ip: str | None = None
) -> TrainingCourse:
    temiz = _kurs_alanlari_dogrula(alanlar)
    kurs_birimi_dogrula(user, temiz.get("birim"))
    if await _kod_cakisiyor(db, TrainingCourse, temiz["kod"], None):
        raise EgitimHatasi(f"'{temiz['kod']}' kodlu eğitim zaten var.")
    kurs = TrainingCourse(**temiz, created_by=user.id, updated_by=user.id)
    db.add(kurs)
    await db.flush()
    await audit.log(
        db,
        "training_courses",
        "olustur",
        entity_id=kurs.id,
        new_value={"kod": kurs.kod, "baslik": kurs.baslik, "birim": kurs.birim},
        user_id=user.id,
        ip=ip,
    )
    return kurs


async def kurs_guncelle(
    db: AsyncSession,
    kurs: TrainingCourse,
    alanlar: dict[str, Any],
    *,
    user: User,
    ip: str | None = None,
) -> TrainingCourse:
    """Metin/eşik/pasifleme (TS-152). Başka birimin kursu ve kursu başka
    birime taşımak 403. Pasif kurs plan/oturum/gözlem seçiminde gelmez;
    geçmiş kayıtlar ve puanları değişmez."""
    kurs_birimi_dogrula(user, kurs.birim)
    temiz = _kurs_alanlari_dogrula(alanlar)
    if "birim" in temiz:
        kurs_birimi_dogrula(user, temiz["birim"])
    if "kod" in temiz and await _kod_cakisiyor(db, TrainingCourse, temiz["kod"], kurs.id):
        raise EgitimHatasi(f"'{temiz['kod']}' kodlu eğitim zaten var.")
    for k, v in temiz.items():
        setattr(kurs, k, v)
    kurs.updated_by = user.id
    await audit.log_change(db, kurs, "guncelle", user_id=user.id, ip=ip)
    await db.flush()
    return kurs


async def kriter_ekle(
    db: AsyncSession,
    kurs: TrainingCourse,
    *,
    metin: str,
    is_critical: bool,
    user: User,
    ip: str | None = None,
) -> TrainingCriterion:
    kurs_birimi_dogrula(user, kurs.birim)
    metin = (metin or "").strip()
    if not metin:
        raise EgitimGirdiHatasi("Gözlem maddesi metni boş olamaz.")
    sira = int(
        await db.scalar(
            select(func.coalesce(func.max(TrainingCriterion.sira), 0)).where(
                TrainingCriterion.course_id == kurs.id
            )
        )
        or 0
    )
    kriter = TrainingCriterion(
        course_id=kurs.id,
        sira=sira + 1,
        metin=metin,
        is_critical=is_critical,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(kriter)
    await db.flush()
    await audit.log(
        db,
        "training_criteria",
        "olustur",
        entity_id=kriter.id,
        new_value={"course_id": kurs.id, "sira": kriter.sira, "kritik": is_critical},
        user_id=user.id,
        ip=ip,
    )
    return kriter


async def kriter_guncelle(
    db: AsyncSession,
    kriter: TrainingCriterion,
    alanlar: dict[str, Any],
    *,
    user: User,
    ip: str | None = None,
) -> TrainingCriterion:
    """Silme ucu YOK: puanlanmış madde silinmez, pasife alınır (TS-152)."""
    kurs = await kurs_getir(db, kriter.course_id)
    kurs_birimi_dogrula(user, kurs.birim)
    if "metin" in alanlar:
        metin = (alanlar["metin"] or "").strip()
        if not metin:
            raise EgitimGirdiHatasi("Gözlem maddesi metni boş olamaz.")
        kriter.metin = metin
    for alan in ("is_critical", "is_active"):
        if alan in alanlar and alanlar[alan] is not None:
            setattr(kriter, alan, bool(alanlar[alan]))
    kriter.updated_by = user.id
    await audit.log_change(db, kriter, "guncelle", user_id=user.id, ip=ip)
    await db.flush()
    return kriter


# --- Toplu yıllık plan (TS-150) ------------------------------------------------------


@dataclass
class TopluPlanGirdisi:
    course_id: int
    plan_yili: int
    user_ids: list[int]
    hedef_tarih: date | None = None
    gelisim_hedefi: str | None = None


async def toplu_plan(
    db: AsyncSession, veri: TopluPlanGirdisi, *, user: User, clock: Clock, ip: str | None = None
) -> dict[str, Any]:
    """Kişi + kurs + yıl; İPTAL dışı tekillik (indeks çıkarımlı ON CONFLICT);
    üst sınır ayardan.

    Mevcut (iptal edilmemiş) kişi+kurs+yıl planı ATLANIR ve sayılır; iptal
    edilen yıl yeniden planlanabilir (kontrol §2/3). Kapsam dışı kişi 404 —
    hiçbir plan yazılmaz (hepsi ya da hiçbiri). Mükerrer atlama
    `ON CONFLICT (user_id, course_id, plan_yili) WHERE ...` ile: önce okuyup
    sonra yazmak eşzamanlı iki istekte çift plan üretirdi.
    """
    ust = int(await ayar_svc.get(db, "egitim_toplu_plan_ust_sinir"))
    kisiler = list(dict.fromkeys(veri.user_ids))
    if not kisiler:
        raise EgitimGirdiHatasi("En az bir personel seçin.")
    if len(kisiler) > ust:
        raise EgitimGirdiHatasi(
            f"Tek seferde en çok {ust} kişiye plan açılabilir ({len(kisiler)})."
        )
    if not 2020 <= veri.plan_yili <= 2100:
        raise EgitimGirdiHatasi("Plan yılı 2020–2100 arasında olmalı.")
    kurs = await kullanilabilir_kurs(db, user, veri.course_id)
    hedef = veri.hedef_tarih or date(veri.plan_yili, 12, 15)
    if hedef.year != veri.plan_yili:
        raise EgitimGirdiHatasi("Hedef tarih plan yılı içinde olmalı.")

    # Kapsam: listede görünmeyen kişiye plan açılamaz (404, hiçbir şey yazılmaz).
    kapsamli = select(User.id).where(User.id.in_(kisiler))
    kapsamli = kapsam.kapsam_personel(kapsamli, user, User.id)
    bulunan = set((await db.scalars(kapsamli)).all())
    if eksik := [k for k in kisiler if k not in bulunan]:
        raise EgitimBulunamadi(f"Personel bulunamadı: {eksik[0]}")
    ayrilan = (
        await db.scalars(select(User.id).where(User.id.in_(kisiler), ~calisan_kosulu()))
    ).all()
    if ayrilan:
        raise EgitimGirdiHatasi("Ayrılmış ya da pasif personele plan açılamaz.")

    satirlar = [
        {
            "user_id": k,
            "course_id": kurs.id,
            "plan_yili": veri.plan_yili,
            "hedef_tarih": hedef,
            "gelisim_hedefi": veri.gelisim_hedefi,
            "status": "PLANLANDI",
            "created_by": user.id,
            "updated_by": user.id,
        }
        for k in kisiler
    ]
    stmt = (
        pg_insert(TrainingPlan)
        .values(satirlar)
        .on_conflict_do_nothing(
            index_elements=["user_id", "course_id", "plan_yili"],
            index_where=text("NOT is_deleted AND status <> 'IPTAL'"),
        )
        .returning(TrainingPlan.id)
    )
    olusan = list((await db.scalars(stmt)).all())
    await audit.log(
        db,
        "training_plans",
        "toplu_olustur",
        new_value={
            "course_id": kurs.id,
            "plan_yili": veri.plan_yili,
            "olusan": len(olusan),
            "atlanan": len(kisiler) - len(olusan),
        },
        user_id=user.id,
        ip=ip,
    )
    return {"olusan": len(olusan), "atlanan": len(kisiler) - len(olusan), "plan_idler": olusan}


async def plan_getir(db: AsyncSession, user: User, kisi_id: int, plan_id: int) -> TrainingPlan:
    """URL'deki kişi kapsamda ve plan o kişinin; aksi 404."""
    await kisi_getir(db, user, kisi_id)
    plan = await db.get(TrainingPlan, plan_id)
    if plan is None or plan.is_deleted or plan.user_id != kisi_id:
        raise EgitimBulunamadi("Plan bulunamadı")
    return plan


async def plan_ertele(
    db: AsyncSession,
    plan: TrainingPlan,
    *,
    yeni_tarih: date,
    gerekce: str | None,
    user: User,
    ip: str | None = None,
) -> TrainingPlan:
    """Erteleme: eski tarih `onceki_hedef_tarih`'te ve denetimde (TS-152).

    İkinci erteleme durum değil yalnız tarih değiştirir; makine aynı duruma
    geçişi reddettiği için ERTELENDI→ERTELENDI makineden geçirilmez
    (kontrol §2/5).
    """
    gerekce = _gerekce(gerekce, "Erteleme")
    if plan.status not in ACIK_PLAN_DURUMLARI:
        raise EgitimHatasi(f"{plan.status} durumundaki plan ertelenemez.")
    if plan.status != "ERTELENDI":
        _gecis(plan.status, "ERTELENDI")
        plan.status = "ERTELENDI"
    plan.onceki_hedef_tarih = plan.hedef_tarih
    plan.hedef_tarih = yeni_tarih
    plan.durum_gerekcesi = gerekce[:500]
    plan.updated_by = user.id
    await audit.log_change(db, plan, "ertele", user_id=user.id, ip=ip, is_personal_data=True)
    await db.flush()
    return plan


async def plan_iptal(
    db: AsyncSession, plan: TrainingPlan, *, gerekce: str | None, user: User, ip: str | None = None
) -> TrainingPlan:
    """İptal KPI, uyarı ve takipten düşer; aynı kişi+kurs+yıl yeniden planlanabilir."""
    gerekce = _gerekce(gerekce, "İptal")
    _gecis(plan.status, "IPTAL")
    plan.status = "IPTAL"
    plan.durum_gerekcesi = gerekce[:500]
    plan.updated_by = user.id
    await audit.log_change(db, plan, "iptal", user_id=user.id, ip=ip, is_personal_data=True)
    await db.flush()
    return plan


# --- Oturum (TS-150 / TS-151 / TS-152) -------------------------------------------------


def _tarih_dogrula(tarih: date, clock: Clock, ne: str = "Oturum") -> None:
    """İleri tarih reddi Türkiye gününe göre (00:00–03:00 UTC kayması, K25)."""
    if tarih > yerel_bugun(clock):
        raise EgitimGirdiHatasi(f"{ne} tarihi bugünden ileri olamaz.")


async def oturum_olustur(
    db: AsyncSession,
    alanlar: dict[str, Any],
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> TrainingSession:
    kurs = await kullanilabilir_kurs(db, user, alanlar["course_id"])
    _tarih_dogrula(alanlar["oturum_tarihi"], clock)
    sure = alanlar.get("sure_saat") or kurs.sure_saat
    oturum = TrainingSession(
        course_id=kurs.id,
        oturum_tarihi=alanlar["oturum_tarihi"],
        egitmen_ad=alanlar.get("egitmen_ad"),
        egitmen_user_id=alanlar.get("egitmen_user_id"),
        sure_saat=Decimal(str(sure)),
        yer=alanlar.get("yer"),
        notlar=alanlar.get("notlar"),
        created_by=user.id,
        updated_by=user.id,
    )
    if oturum.egitmen_user_id is not None and await db.get(User, oturum.egitmen_user_id) is None:
        raise EgitimGirdiHatasi("Eğitmen kullanıcısı bulunamadı.")
    db.add(oturum)
    await db.flush()
    await audit.log(
        db,
        "training_sessions",
        "olustur",
        entity_id=oturum.id,
        new_value={"course_id": kurs.id, "tarih": str(oturum.oturum_tarihi)},
        user_id=user.id,
        ip=ip,
    )
    return oturum


async def oturum_getir(db: AsyncSession, user: User, oturum_id: int) -> TrainingSession:
    """Oturum yok/silinmiş → 404; kursu başka birimin → 403 (yazma uçları)."""
    oturum = await db.get(TrainingSession, oturum_id)
    if oturum is None or oturum.is_deleted:
        raise EgitimBulunamadi("Oturum bulunamadı")
    kurs = await kurs_getir(db, oturum.course_id)
    kurs_birimi_dogrula(user, kurs.birim)
    return oturum


async def _katilim_var_mi(db: AsyncSession, oturum_id: int) -> bool:
    return (
        await db.scalar(
            select(TrainingAttendance.id).where(TrainingAttendance.session_id == oturum_id).limit(1)
        )
    ) is not None


async def oturum_guncelle(
    db: AsyncSession,
    oturum: TrainingSession,
    alanlar: dict[str, Any],
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> TrainingSession:
    """Tarih değişince bu oturumla kapanan planların `completed_on`'u aynı
    transaction'da güncellenir; katılımlı oturumda YIL değişikliği 409
    (plan eşleşmesi değişirdi — kontrol §2/7)."""
    if "oturum_tarihi" in alanlar and alanlar["oturum_tarihi"] != oturum.oturum_tarihi:
        yeni: date = alanlar["oturum_tarihi"]
        _tarih_dogrula(yeni, clock)
        if yeni.year != oturum.oturum_tarihi.year and await _katilim_var_mi(db, oturum.id):
            raise EgitimHatasi(
                "Katılım girilmiş oturumun yılı değiştirilemez; oturumu yeni yıl için ayrıca açın."
            )
        oturum.oturum_tarihi = yeni
        planlar = (
            await db.scalars(
                select(TrainingPlan).where(
                    TrainingPlan.completed_session_id == oturum.id,
                    TrainingPlan.status == "TAMAMLANDI",
                )
            )
        ).all()
        for p in planlar:
            p.completed_on = yeni
            p.updated_by = user.id
            await audit.log_change(
                db, p, "oturum_tarihi_duzelt", user_id=user.id, ip=ip, is_personal_data=True
            )
    for alan in ("egitmen_ad", "egitmen_user_id", "yer", "notlar"):
        if alan in alanlar:
            setattr(oturum, alan, alanlar[alan])
    if alanlar.get("sure_saat") is not None:
        oturum.sure_saat = Decimal(str(alanlar["sure_saat"]))
    oturum.updated_by = user.id
    await audit.log_change(db, oturum, "guncelle", user_id=user.id, ip=ip)
    await db.flush()
    return oturum


async def oturum_sil(
    db: AsyncSession, oturum: TrainingSession, *, user: User, clock: Clock, ip: str | None = None
) -> None:
    """Katılımsız oturum yumuşak silinir; katılımlı oturum 409."""
    if await _katilim_var_mi(db, oturum.id):
        raise EgitimHatasi("Katılım girilmiş oturum silinemez.")
    oturum.is_deleted = True
    oturum.deleted_at = clock.now()
    oturum.deleted_by = user.id
    await audit.log_change(db, oturum, "sil", user_id=user.id, ip=ip)
    await db.flush()


# --- Katılım ve plan tamamlama (TS-151 / TS-158) ------------------------------------------


@dataclass
class KatilimSatiri:
    user_id: int
    katildi: bool = True
    on_puan: int | None = None
    son_puan: int | None = None
    notlar: str | None = None


def _puan_dogrula(puan: int | None) -> None:
    if puan is not None and not 0 <= puan <= 100:
        raise EgitimGirdiHatasi("Sınav puanı 0–100 arasında olmalı.")


async def _plan_tamamla(
    db: AsyncSession,
    oturum: TrainingSession,
    kurs: TrainingCourse,
    satir: KatilimSatiri,
    *,
    user: User,
    ip: str | None,
) -> TrainingPlan | None:
    """En eski açık planı kapatır (yoksa plan OLUŞTURULMAZ)."""
    zaten = await db.scalar(
        select(TrainingPlan).where(
            TrainingPlan.completed_session_id == oturum.id,
            TrainingPlan.user_id == satir.user_id,
            TrainingPlan.status == "TAMAMLANDI",
        )
    )
    if zaten is not None:
        return zaten
    plan = await db.scalar(
        select(TrainingPlan)
        .where(
            TrainingPlan.user_id == satir.user_id,
            TrainingPlan.course_id == oturum.course_id,
            TrainingPlan.plan_yili <= oturum.oturum_tarihi.year,
            TrainingPlan.status.in_(ACIK_PLAN_DURUMLARI),
            TrainingPlan.is_deleted.is_(False),
        )
        .order_by(TrainingPlan.plan_yili, TrainingPlan.hedef_tarih, TrainingPlan.id)
        .limit(1)
        .with_for_update()
    )
    if plan is None:
        return None
    esik = kurs.sinav_gecme_puani
    if esik is not None and satir.son_puan is not None and satir.son_puan < esik:
        # P3 (K9): sınav eşiği doluysa ve son puan altındaysa tekrar gerekir.
        if plan.status != "BASARISIZ_TEKRAR":
            _gecis(plan.status, "BASARISIZ_TEKRAR")
            plan.status = "BASARISIZ_TEKRAR"
    else:
        _gecis(plan.status, "TAMAMLANDI")
        plan.status = "TAMAMLANDI"
        plan.completed_on = oturum.oturum_tarihi
        plan.completed_session_id = oturum.id
    plan.updated_by = user.id
    await audit.log_change(db, plan, "katilim", user_id=user.id, ip=ip, is_personal_data=True)
    return plan


async def _plani_geri_ac(
    db: AsyncSession, oturum: TrainingSession, kisi_id: int, *, user: User, ip: str | None
) -> None:
    """ "Katılmadı" düzeltmesi: bu oturumla kapanan plan PLANLANDI'ya döner."""
    planlar = (
        await db.scalars(
            select(TrainingPlan).where(
                TrainingPlan.completed_session_id == oturum.id,
                TrainingPlan.user_id == kisi_id,
                TrainingPlan.status == "TAMAMLANDI",
            )
        )
    ).all()
    for p in planlar:
        _gecis(p.status, "PLANLANDI")
        p.status = "PLANLANDI"
        p.completed_on = None
        p.completed_session_id = None
        p.updated_by = user.id
        await audit.log_change(
            db, p, "katilim_geri_al", user_id=user.id, ip=ip, is_personal_data=True
        )


async def katilim_isle(
    db: AsyncSession,
    oturum: TrainingSession,
    satir: KatilimSatiri,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> TrainingAttendance:
    """Tek kişinin katılımını yazar ve plan kuralını uygular (TEK fonksiyon).

    Kişi kapsam dışı → 404 (`EgitimBulunamadi`; toplu uç bunu satır
    numaralı 400'e çevirir). Var olan katılım satırı DÜZELTİLİR (silme yok).
    """
    _tarih_dogrula(oturum.oturum_tarihi, clock)
    _puan_dogrula(satir.on_puan)
    _puan_dogrula(satir.son_puan)
    kurs = await kurs_getir(db, oturum.course_id)
    await kisi_getir(db, user, satir.user_id)
    kayit = await db.scalar(
        select(TrainingAttendance).where(
            TrainingAttendance.session_id == oturum.id,
            TrainingAttendance.user_id == satir.user_id,
        )
    )
    onceki_katildi = kayit.katildi if kayit is not None else None
    if kayit is None:
        kayit = TrainingAttendance(
            session_id=oturum.id,
            user_id=satir.user_id,
            created_by=user.id,
        )
        db.add(kayit)
    kayit.katildi = satir.katildi
    kayit.on_puan = satir.on_puan
    kayit.son_puan = satir.son_puan
    kayit.notlar = satir.notlar
    kayit.updated_by = user.id
    await db.flush()
    if onceki_katildi is None:
        await audit.log(
            db,
            "training_attendance",
            "olustur",
            entity_id=kayit.id,
            new_value={"session_id": oturum.id, "user_id": satir.user_id, "katildi": satir.katildi},
            user_id=user.id,
            ip=ip,
            is_personal_data=True,
        )
    else:
        await audit.log_change(db, kayit, "duzelt", user_id=user.id, ip=ip, is_personal_data=True)

    if satir.katildi:
        if onceki_katildi is True:
            # Puan düzeltmesi: eşik (P3) sonucu değişebilir → planı yeniden değerlendir.
            await _plani_geri_ac(db, oturum, satir.user_id, user=user, ip=ip)
        await _plan_tamamla(db, oturum, kurs, satir, user=user, ip=ip)
    elif onceki_katildi is True:
        await _plani_geri_ac(db, oturum, satir.user_id, user=user, ip=ip)
    await db.flush()
    return kayit


async def katilim_kaydet(
    db: AsyncSession,
    oturum: TrainingSession,
    satirlar: list[KatilimSatiri],
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> list[TrainingAttendance]:
    """Toplu katılım; en eski açık plan tamamlanır; ilk hatada 0 satır.

    Her satır `katilim_isle`'den geçer (tek kişilik uçla AYNI kural). İlk
    hatada `EgitimGirdiHatasi(satir=n)` atılır (1 tabanlı); API commit etmez,
    transaction geri alınır — hiçbir satır yazılmaz.
    """
    if len(satirlar) > TOPLU_KATILIM_UST_SINIR:
        raise EgitimGirdiHatasi(f"Tek seferde en çok {TOPLU_KATILIM_UST_SINIR} satır girilebilir.")
    gorulen: set[int] = set()
    sonuc: list[TrainingAttendance] = []
    for sira, satir in enumerate(satirlar, start=1):
        if satir.user_id in gorulen:
            raise EgitimGirdiHatasi("Aynı kişi listede iki kez var.", satir=sira)
        gorulen.add(satir.user_id)
        try:
            sonuc.append(await katilim_isle(db, oturum, satir, user=user, clock=clock, ip=ip))
        except EgitimHatasi as exc:
            mesaj = (
                "Personel kapsamınızda değil." if isinstance(exc, EgitimBulunamadi) else exc.mesaj
            )
            raise EgitimGirdiHatasi(mesaj, satir=sira) from exc
    return sonuc


async def aday_katilimcilar(
    db: AsyncSession, oturum: TrainingSession, user: User
) -> list[dict[str, Any]]:
    """Kursun oturum yılında açık planı olan kapsamdaki çalışan kişiler +
    oturumun mevcut katılım satırları (plan dışı kişiler de eklenebilir)."""
    yil = oturum.oturum_tarihi.year
    plan_sahipleri = (
        select(User.id, User.full_name, TrainingPlan.id.label("plan_id"))
        .join(TrainingPlan, TrainingPlan.user_id == User.id)
        .where(
            TrainingPlan.course_id == oturum.course_id,
            TrainingPlan.plan_yili <= yil,
            TrainingPlan.status.in_(ACIK_PLAN_DURUMLARI),
            TrainingPlan.is_deleted.is_(False),
            calisan_kosulu(),
        )
        .order_by(User.full_name, User.id, TrainingPlan.plan_yili)
    )
    plan_sahipleri = kapsam.kapsam_personel(plan_sahipleri, user, User.id)
    mevcut = select(TrainingAttendance, User.full_name).join(
        User, User.id == TrainingAttendance.user_id
    )
    mevcut = mevcut.where(TrainingAttendance.session_id == oturum.id).order_by(User.full_name)
    mevcut = kapsam.kapsam_personel(mevcut, user, User.id)

    satirlar: dict[int, dict[str, Any]] = {}
    for kid, ad, plan_id in (await db.execute(plan_sahipleri)).all():
        satirlar.setdefault(
            kid,
            {
                "user_id": kid,
                "ad": ad,
                "plan_id": plan_id,
                "planli": True,
                "katilim_id": None,
                "katildi": None,
                "on_puan": None,
                "son_puan": None,
                "notlar": None,
                "version": None,
            },
        )
    for k, ad in (await db.execute(mevcut)).all():
        satir = satirlar.setdefault(
            k.user_id,
            {"user_id": k.user_id, "ad": ad, "plan_id": None, "planli": False},
        )
        satir.update(
            katilim_id=k.id,
            katildi=k.katildi,
            on_puan=k.on_puan,
            son_puan=k.son_puan,
            notlar=k.notlar,
            version=k.version,
        )
    return sorted(satirlar.values(), key=lambda s: (s["ad"] or "", s["user_id"]))


# --- Belgeler (TS-159) ----------------------------------------------------------------------


async def belge_olustur(
    db: AsyncSession, alanlar: dict[str, Any], *, user: User, ip: str | None = None
):
    """Elle girilen personel belgesi/sertifikası (E08-11). Numara üretilmez."""
    from app.models import PersonnelCertificate

    await kisi_getir(db, user, alanlar["user_id"])
    if alanlar.get("course_id") is not None:
        kurs = await kurs_getir(db, alanlar["course_id"])
        kurs_birimi_dogrula(user, kurs.birim)
    bitis = alanlar.get("gecerlilik_bitis")
    if bitis is not None and bitis < alanlar["verilis_tarihi"]:
        raise EgitimGirdiHatasi("Geçerlilik bitişi veriliş tarihinden önce olamaz.")
    ad = (alanlar.get("belge_adi") or "").strip()
    if not ad:
        raise EgitimGirdiHatasi("Belge adı boş olamaz.")
    belge = PersonnelCertificate(
        user_id=alanlar["user_id"],
        course_id=alanlar.get("course_id"),
        belge_adi=ad,
        verilis_tarihi=alanlar["verilis_tarihi"],
        gecerlilik_bitis=bitis,
        belge_no=alanlar.get("belge_no"),
        aciklama=alanlar.get("aciklama"),
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(belge)
    await db.flush()
    await audit.log(
        db,
        "personnel_certificates",
        "olustur",
        entity_id=belge.id,
        new_value={"user_id": belge.user_id, "belge_adi": belge.belge_adi},
        user_id=user.id,
        ip=ip,
        is_personal_data=True,
    )
    return belge


async def belge_getir(db: AsyncSession, user: User, kisi_id: int, belge_id: int):
    from app.models import PersonnelCertificate

    await kisi_getir(db, user, kisi_id)
    belge = await db.get(PersonnelCertificate, belge_id)
    if belge is None or belge.user_id != kisi_id:
        raise EgitimBulunamadi("Belge bulunamadı")
    return belge


async def belge_iptal(
    db: AsyncSession, belge, *, gerekce: str | None, user: User, clock: Clock, ip: str | None = None
):
    gerekce = _gerekce(gerekce, "Belge iptali")
    if belge.cancelled_at is not None:
        raise EgitimHatasi("Belge zaten iptal edilmiş.")
    belge.cancelled_at = clock.now()
    belge.cancelled_by = user.id
    belge.cancel_reason = gerekce[:300]
    belge.updated_by = user.id
    await audit.log_change(db, belge, "iptal", user_id=user.id, ip=ip, is_personal_data=True)
    await db.flush()
    return belge
