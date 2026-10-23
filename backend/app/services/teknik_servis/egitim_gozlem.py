"""Saha gözlemi, sonuç hesabı, düzeltici faaliyet (E08-05/07/08/09/15/17).

Maddeler: TS-151, TS-152, TS-155, TS-156, TS-157.

**Sonuç sunucuda hesaplanır** (`sonuc_hesapla`, saf fonksiyon): istemcinin
gönderdiği puan/sonuç yok sayılır. Sıra K7: kritik maddede 0 → KRITIK;
kritik madde gözlenmedi (-1, gerekçeli) → EKSIK_GOZLEM; puan ≥ eşik →
BASARILI; diğer → GELISIM_GEREKLI. Puan = 100 × Σpuan / (cevaplanan × 2);
-1 paydaya girmez (R-84: 2,2,1,-1 → %83,33).

**Düzeltici faaliyet (K10, TS-155):** KRITIK gözlem aynı transaction'da
TEK faaliyet açar (`uq_tca_gozlem`); sorumlu = gözlemci, termin = gözlem
tarihi + `egitim_duzeltici_termin_gun`. Aynı kişi+kurs için sonraki tarihli,
iptal edilmemiş ve faaliyetin kritik maddelerinin TÜMÜNÜ 2 alan gözlem onu
otomatik kapatır (`OTOMATIK_GOZLEM`, bağlantı saklanır). Gözlem iptali bağlı
faaliyeti KAPATMAZ (sessiz kayıp yok; yalnız manuel kapanır).

**Kimlik (TS-156):** gözlemci sunucuda `user`'dır; öz-gözlem 409. Servis
işi bağı yalnız `service_orders`'a (K5); kapsam dışı iş 404. Birim anlık
görüntüsü: iş varsa işin birimi, yoksa kursun, yoksa gözlenenin birincil
birimi (kontrol K3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models import (
    ServiceOrder,
    ServiceOrderAssignment,
    TrainingCorrectiveAction,
    TrainingCriterion,
    TrainingObservation,
    TrainingObservationRating,
    TrainingPlan,
    User,
)
from app.models.egitim import GOZLEM_ASAMALARI, MADDE_PUANLARI
from app.services import audit
from app.services import settings as ayar_svc
from app.services.statemachine import DUZELTICI_FAALIYET, IzinsizGecis
from app.services.teknik_servis import ek_kapsam, kapsam
from app.services.teknik_servis.egitim import (
    EgitimBulunamadi,
    EgitimGirdiHatasi,
    EgitimHatasi,
    EgitimYasak,
    _tarih_dogrula,
    kisi_getir,
    kullanilabilir_kurs,
)

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


@dataclass(frozen=True)
class MaddePuani:
    criterion_id: int
    puan: int
    gozlenmedi_gerekcesi: str | None = None


def sonuc_hesapla(puanlar: list[Any], kriterler: list[Any], esik_yuzde: float) -> tuple[Any, str]:
    """KRITIK → EKSIK_GOZLEM → BASARILI (≥ eşik) → GELISIM_GEREKLI (sunucuda).

    `puanlar`: `criterion_id, puan, gozlenmedi_gerekcesi` taşıyan nesneler;
    `kriterler`: kursun maddeleri (`id, is_critical, is_active`). Döner:
    `(puan: Decimal | None, sonuc)`; puan iki ondalık, hiçbir madde
    cevaplanmadıysa None. Doğrulama hataları `EgitimGirdiHatasi` (400):
    kursa ait olmayan/pasif/tekrarlanan madde, kapsam dışı puan, gerekçesiz
    -1, cevaplanmamış kritik madde (ön yüzde kritik maddede varsayılan yok),
    tüm maddeler -1.
    """
    kriter_sozlugu = {k.id: k for k in kriterler}
    gorulen: set[int] = set()
    toplam = 0
    cevaplanan = 0
    kritik_sifir = False
    kritik_gozlenmedi = False
    for p in puanlar:
        kriter = kriter_sozlugu.get(p.criterion_id)
        if kriter is None:
            raise EgitimGirdiHatasi("Gözlem maddesi bu eğitime ait değil.")
        if not kriter.is_active:
            raise EgitimGirdiHatasi("Pasif gözlem maddesi puanlanamaz.")
        if p.criterion_id in gorulen:
            raise EgitimGirdiHatasi("Aynı gözlem maddesi iki kez puanlanmış.")
        gorulen.add(p.criterion_id)
        if p.puan not in MADDE_PUANLARI:
            raise EgitimGirdiHatasi("Madde puanı -1, 0, 1 ya da 2 olmalı.")
        if p.puan == -1:
            if not (p.gozlenmedi_gerekcesi or "").strip():
                raise EgitimGirdiHatasi("Gözlenmeyen madde için gerekçe zorunlu.")
            if kriter.is_critical:
                kritik_gozlenmedi = True
            continue
        cevaplanan += 1
        toplam += p.puan
        if kriter.is_critical and p.puan == 0:
            kritik_sifir = True
    eksik_kritik = [k for k in kriterler if k.is_critical and k.is_active and k.id not in gorulen]
    if eksik_kritik:
        raise EgitimGirdiHatasi("Kritik maddelerin hepsi puanlanmalı (gözlenmediyse gerekçeyle).")
    if cevaplanan == 0:
        raise EgitimGirdiHatasi("En az bir madde gözlenmiş olmalı.")
    puan = (Decimal(100 * toplam) / Decimal(cevaplanan * 2)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if kritik_sifir:
        return puan, "KRITIK"
    if kritik_gozlenmedi:
        return puan, "EKSIK_GOZLEM"
    if puan >= Decimal(str(esik_yuzde)):
        return puan, "BASARILI"
    return puan, "GELISIM_GEREKLI"


@dataclass
class GozlemGirdisi:
    user_id: int
    course_id: int
    asama: int
    gozlem_tarihi: date
    puanlar: list[MaddePuani] = field(default_factory=list)
    plan_id: int | None = None
    service_order_id: int | None = None
    notlar: str | None = None
    aksiyon_plani: str | None = None
    sonraki_izleme: date | None = None


async def _esik(db: AsyncSession, kurs) -> float:
    if kurs.gozlem_esik_yuzde is not None:
        return float(kurs.gozlem_esik_yuzde)
    return float(await ayar_svc.get(db, "egitim_gozlem_basari_esigi_yuzde"))


async def kurs_kriterleri(db: AsyncSession, kurs_id: int) -> list[TrainingCriterion]:
    return list(
        (
            await db.scalars(
                select(TrainingCriterion)
                .where(TrainingCriterion.course_id == kurs_id)
                .order_by(TrainingCriterion.sira, TrainingCriterion.id)
            )
        ).all()
    )


async def servis_isi_getir(db: AsyncSession, user: User, so_id: int) -> ServiceOrder:
    """Gövdedeki servis işi: yok/silinmiş/kapsam dışı → 404 (K4)."""
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise EgitimBulunamadi("Servis işi bulunamadı")
    return so


async def _kritik_sifirlar(db: AsyncSession, gozlem_id: int) -> set[int]:
    """Gözlemin 0 alan kritik maddeleri (faaliyetin kapsamı; ayrı tabloda tutulmaz)."""
    return set(
        (
            await db.scalars(
                select(TrainingObservationRating.criterion_id)
                .join(
                    TrainingCriterion,
                    TrainingCriterion.id == TrainingObservationRating.criterion_id,
                )
                .where(
                    TrainingObservationRating.observation_id == gozlem_id,
                    TrainingObservationRating.puan == 0,
                    TrainingCriterion.is_critical.is_(True),
                )
            )
        ).all()
    )


async def _faaliyetleri_otomatik_kapat(
    db: AsyncSession, gozlem: TrainingObservation, puanlar: dict[int, int], *, user: User, clock
) -> list[int]:
    acik = (
        await db.execute(
            select(TrainingCorrectiveAction, TrainingObservation.gozlem_tarihi)
            .join(
                TrainingObservation,
                TrainingObservation.id == TrainingCorrectiveAction.observation_id,
            )
            .where(
                TrainingCorrectiveAction.user_id == gozlem.user_id,
                TrainingCorrectiveAction.course_id == gozlem.course_id,
                TrainingCorrectiveAction.status == "ACIK",
                TrainingCorrectiveAction.observation_id != gozlem.id,
            )
            .with_for_update(of=TrainingCorrectiveAction)
        )
    ).all()
    kapanan: list[int] = []
    for faaliyet, tarih in acik:
        if tarih >= gozlem.gozlem_tarihi:
            continue  # yalnız SONRAKİ tarihli gözlem kapatır
        maddeler = await _kritik_sifirlar(db, faaliyet.observation_id)
        if not maddeler or any(puanlar.get(m) != 2 for m in maddeler):
            continue
        DUZELTICI_FAALIYET.dogrula(faaliyet.status, "KAPATILDI")
        faaliyet.status = "KAPATILDI"
        faaliyet.kapanis_turu = "OTOMATIK_GOZLEM"
        faaliyet.closing_observation_id = gozlem.id
        faaliyet.closed_at = clock.now()
        faaliyet.closed_by = user.id
        faaliyet.updated_by = user.id
        await audit.log_change(
            db, faaliyet, "otomatik_kapat", user_id=user.id, is_personal_data=True
        )
        kapanan.append(faaliyet.id)
    return kapanan


async def gozlem_kaydet(
    db: AsyncSession, veri: GozlemGirdisi, *, user: User, clock: Clock, ip: str | None = None
) -> tuple[TrainingObservation, list[str], TrainingCorrectiveAction | None]:
    """Öz-gözlem 409; servis işi kapsam dışı 404; birim işten anlık görüntü.

    Döner: (gözlem, yanıt uyarıları, açılan faaliyet). Uyarılar kaydı
    ENGELLEMEZ (tamamlanmadan önceki takip gözlemi, aynı aşamada ikinci
    gözlem, atama dışı kişi — E08-08/15).
    """
    if veri.user_id == user.id:
        raise EgitimHatasi("Kendi gözleminizi giremezsiniz.")
    kisi = await kisi_getir(db, user, veri.user_id)
    kurs = await kullanilabilir_kurs(db, user, veri.course_id)
    so = None
    if veri.service_order_id is not None:
        so = await servis_isi_getir(db, user, veri.service_order_id)
    if veri.asama not in GOZLEM_ASAMALARI:
        raise EgitimGirdiHatasi("Gözlem aşaması 0, 30, 60 ya da 90 olmalı.")
    _tarih_dogrula(veri.gozlem_tarihi, clock, "Gözlem")

    uyarilar: list[str] = []
    plan = None
    if veri.plan_id is not None:
        plan = await db.get(TrainingPlan, veri.plan_id)
        if (
            plan is None
            or plan.is_deleted
            or plan.user_id != veri.user_id
            or plan.course_id != veri.course_id
        ):
            raise EgitimGirdiHatasi("Plan bu kişi ve eğitime ait değil.")
    elif veri.asama > 0:
        plan = await db.scalar(
            select(TrainingPlan)
            .where(
                TrainingPlan.user_id == veri.user_id,
                TrainingPlan.course_id == veri.course_id,
                TrainingPlan.status == "TAMAMLANDI",
                TrainingPlan.is_deleted.is_(False),
            )
            .order_by(TrainingPlan.completed_on.desc(), TrainingPlan.id.desc())
            .limit(1)
        )
    if veri.asama > 0:
        if plan is None or plan.completed_on is None:
            uyarilar.append(
                "Bu kişi için tamamlanmış eğitim planı yok; takip gözlemi plana bağlanmadı."
            )
        elif veri.gozlem_tarihi < plan.completed_on:
            uyarilar.append(
                "Gözlem tarihi eğitimin tamamlanma tarihinden önce; bu gözlem takibi kapatmaz."
            )
    ayni = select(TrainingObservation.id).where(
        TrainingObservation.user_id == veri.user_id,
        TrainingObservation.course_id == veri.course_id,
        TrainingObservation.asama == veri.asama,
        TrainingObservation.cancelled_at.is_(None),
        TrainingObservation.is_deleted.is_(False),
    )
    ayni = ayni.where(
        TrainingObservation.plan_id == plan.id
        if plan is not None
        else TrainingObservation.plan_id.is_(None)
    )
    if (await db.scalar(ayni.limit(1))) is not None:
        uyarilar.append("Bu aşamada zaten bir gözlem var; takipte en son gözlem esas alınır.")
    if so is not None:
        atama = await db.scalar(
            select(ServiceOrderAssignment.id).where(
                ServiceOrderAssignment.service_order_id == so.id,
                ServiceOrderAssignment.user_id == veri.user_id,
            )
        )
        if atama is None:
            uyarilar.append("Gözlenen kişinin bu servis işinde tayini yok.")

    kriterler = await kurs_kriterleri(db, kurs.id)
    puan, sonuc = sonuc_hesapla(veri.puanlar, kriterler, await _esik(db, kurs))
    birim = so.birim if so is not None else (kurs.birim or kisi.birincil_birim)

    gozlem = TrainingObservation(
        user_id=veri.user_id,
        course_id=kurs.id,
        plan_id=plan.id if plan is not None else None,
        asama=veri.asama,
        gozlem_tarihi=veri.gozlem_tarihi,
        observer_user_id=user.id,
        gozlemci_ad=(user.full_name or "")[:100],
        service_order_id=so.id if so is not None else None,
        birim=birim,
        puan=puan,
        sonuc=sonuc,
        kritik=sonuc == "KRITIK",
        notlar=veri.notlar,
        aksiyon_plani=veri.aksiyon_plani,
        sonraki_izleme=veri.sonraki_izleme,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(gozlem)
    await db.flush()
    for p in veri.puanlar:
        db.add(
            TrainingObservationRating(
                observation_id=gozlem.id,
                criterion_id=p.criterion_id,
                puan=p.puan,
                gozlenmedi_gerekcesi=(p.gozlenmedi_gerekcesi or None) if p.puan == -1 else None,
            )
        )
    await db.flush()
    await audit.log(
        db,
        "training_observations",
        "olustur",
        entity_id=gozlem.id,
        new_value={
            "user_id": gozlem.user_id,
            "course_id": gozlem.course_id,
            "asama": gozlem.asama,
            "puan": str(puan) if puan is not None else None,
            "sonuc": sonuc,
            "service_order_id": gozlem.service_order_id,
        },
        user_id=user.id,
        ip=ip,
        is_personal_data=True,
    )

    faaliyet = None
    if sonuc == "KRITIK":
        gun = int(await ayar_svc.get(db, "egitim_duzeltici_termin_gun"))
        faaliyet = TrainingCorrectiveAction(
            observation_id=gozlem.id,
            user_id=gozlem.user_id,
            course_id=gozlem.course_id,
            sorumlu_user_id=user.id,
            termin=gozlem.gozlem_tarihi + timedelta(days=gun),
            status="ACIK",
            created_by=user.id,
            updated_by=user.id,
        )
        db.add(faaliyet)
        await db.flush()
        await audit.log(
            db,
            "training_corrective_actions",
            "olustur",
            entity_id=faaliyet.id,
            new_value={"observation_id": gozlem.id, "termin": str(faaliyet.termin)},
            user_id=user.id,
            ip=ip,
            is_personal_data=True,
        )
    puan_sozlugu = {p.criterion_id: p.puan for p in veri.puanlar}
    kapanan = await _faaliyetleri_otomatik_kapat(db, gozlem, puan_sozlugu, user=user, clock=clock)
    if kapanan:
        uyarilar.append(f"{len(kapanan)} açık düzeltici faaliyet bu gözlemle kapandı.")
    await db.flush()
    return gozlem, uyarilar, faaliyet


async def gozlem_getir(
    db: AsyncSession, user: User, kisi_id: int, gozlem_id: int
) -> TrainingObservation:
    await kisi_getir(db, user, kisi_id)
    gozlem = await db.get(TrainingObservation, gozlem_id)
    if gozlem is None or gozlem.is_deleted or gozlem.user_id != kisi_id:
        raise EgitimBulunamadi("Gözlem bulunamadı")
    return gozlem


async def gozlem_iptal(
    db: AsyncSession,
    gozlem: TrainingObservation,
    *,
    gerekce: str | None,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> TrainingObservation:
    """Gerekçeli iptal (TS-152): gözlemci kendi gözlemini `egitim.gozlem` ile,
    diğerleri `egitim.yaz` ile. İptal edilen gözlem KPI, takip ve rapordan
    düşer, kartta "iptal — gerekçe" görünür. Bağlı açık faaliyet AÇIK kalır."""
    kendi = gozlem.observer_user_id == user.id and user.has("egitim.gozlem")
    if not (kendi or user.has("egitim.yaz")):
        raise EgitimYasak("Başkasının gözlemini yalnız eğitim yöneticisi (egitim.yaz) iptal eder.")
    temiz = (gerekce or "").strip()
    if not temiz:
        raise EgitimGirdiHatasi("Gözlem iptali için gerekçe zorunlu.")
    if gozlem.cancelled_at is not None:
        raise EgitimHatasi("Gözlem zaten iptal edilmiş.")
    gozlem.cancelled_at = clock.now()
    gozlem.cancelled_by = user.id
    gozlem.cancel_reason = temiz[:300]
    gozlem.updated_by = user.id
    await audit.log_change(db, gozlem, "iptal", user_id=user.id, ip=ip, is_personal_data=True)
    await db.flush()
    return gozlem


async def gordum(
    db: AsyncSession,
    gozlem_id: int,
    *,
    yorum: str | None,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> TrainingObservation:
    """Personelin "Gördüm" onayı (TS-157): başkasının gözlemi 404, ikinci
    onay 409 (geri alınamaz), denetime yazılır."""
    gozlem = await db.get(TrainingObservation, gozlem_id)
    if gozlem is None or gozlem.is_deleted or gozlem.user_id != user.id:
        raise EgitimBulunamadi("Gözlem bulunamadı")
    if gozlem.cancelled_at is not None:
        raise EgitimHatasi("İptal edilmiş gözlem onaylanamaz.")
    if gozlem.gordu_at is not None:
        raise EgitimHatasi("Bu gözlemi zaten onayladınız; onay geri alınamaz.")
    gozlem.gordu_at = clock.now()
    gozlem.personel_yorumu = (yorum or "").strip()[:900] or None
    await audit.log_change(db, gozlem, "gordum", user_id=user.id, ip=ip, is_personal_data=True)
    await db.flush()
    return gozlem


# --- Düzeltici faaliyet (TS-155) ---------------------------------------------------


async def faaliyet_getir(
    db: AsyncSession, user: User, kisi_id: int, faaliyet_id: int
) -> TrainingCorrectiveAction:
    await kisi_getir(db, user, kisi_id)
    faaliyet = await db.get(TrainingCorrectiveAction, faaliyet_id)
    if faaliyet is None or faaliyet.user_id != kisi_id:
        raise EgitimBulunamadi("Düzeltici faaliyet bulunamadı")
    return faaliyet


async def faaliyet_kapat(
    db: AsyncSession,
    faaliyet: TrainingCorrectiveAction,
    *,
    kanit: str | None,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> TrainingCorrectiveAction:
    """Manuel kapanış: `egitim.yaz` + kanıt metni (boş → 400)."""
    temiz = (kanit or "").strip()
    if not temiz:
        raise EgitimGirdiHatasi("Manuel kapanış için kanıt/açıklama zorunlu.")
    try:
        DUZELTICI_FAALIYET.dogrula(faaliyet.status, "KAPATILDI")
    except IzinsizGecis as exc:
        raise EgitimHatasi("Düzeltici faaliyet zaten kapatılmış.") from exc
    faaliyet.status = "KAPATILDI"
    faaliyet.kapanis_turu = "MANUEL"
    faaliyet.kapanis_kaniti = temiz
    faaliyet.closed_at = clock.now()
    faaliyet.closed_by = user.id
    faaliyet.updated_by = user.id
    await audit.log_change(
        db, faaliyet, "manuel_kapat", user_id=user.id, ip=ip, is_personal_data=True
    )
    await db.flush()
    return faaliyet


# --- Ek kapsamı (plan §1.11; eğitim dalları D2-F) ------------------------------------
#
# Kişisel performans eki: okuma `egitim.detay` + personel kapsamı. İstisna
# (kontrol §2/10, K12): kişi KENDİ gözleminin/belgesinin ekini
# `egitim.kendim` ile görür; başkasınınki 404. Yazma her zaman kapsamlı.


async def _kisisel_ek_kapsami(
    db: AsyncSession, user: User, sahip_kisi: int | None, yazma: bool
) -> bool:
    if sahip_kisi is None:
        return True  # kayıt yok: varlık kontrolü API'de (404)
    kapsamda = not await kapsam.personel_disinda_mi(db, user, sahip_kisi)
    if yazma:
        return kapsamda
    if user.has("egitim.detay") and kapsamda:
        return True
    return sahip_kisi == user.id and user.has("egitim.kendim")


async def _gozlem_eki(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    kisi = await db.scalar(
        select(TrainingObservation.user_id).where(TrainingObservation.id == entity_id)
    )
    return await _kisisel_ek_kapsami(db, user, kisi, yazma)


async def _faaliyet_eki(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    kisi = await db.scalar(
        select(TrainingCorrectiveAction.user_id).where(TrainingCorrectiveAction.id == entity_id)
    )
    return await _kisisel_ek_kapsami(db, user, kisi, yazma)


async def _belge_eki(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    from app.models import PersonnelCertificate

    kisi = await db.scalar(
        select(PersonnelCertificate.user_id).where(PersonnelCertificate.id == entity_id)
    )
    return await _kisisel_ek_kapsami(db, user, kisi, yazma)


ek_kapsam.kaydet("training_observations", _gozlem_eki)
ek_kapsam.kaydet("training_corrective_actions", _faaliyet_eki)
ek_kapsam.kaydet("personnel_certificates", _belge_eki)
