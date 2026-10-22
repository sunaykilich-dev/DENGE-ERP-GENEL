"""Eğitim yönetim özeti, KPI tanımları, geçerlilik ve takip sorguları (E08-11/13/14/23).

Maddeler: TS-153, TS-159.

**Sayı = liste (E01-14 kalıbı):** her KPI kutusu bir LİSTE SÜZGECİDİR.
Kutunun sayısı, listenin `?kpi=<kod>` ile çağrıldığında kullandığı AYNI
sorgu fonksiyonundan sayılır (`kpi_sorgusu`); uyarı merkezi de aynı
fonksiyonları çağırır. Kapsam (`kapsam_personel`) sorgunun içindedir: başka
birimin personeli ne listede ne sayıda ne uyarıda görünür; birimsiz şefte
sonuç 0 (fail-closed).

**Hesaplanır, saklanmaz (K8):** 30/60/90 takibi (`takip_sorgusu`), belge ve
eğitim geçerliliği (`gecerlilik_sorgusu`) sorgudur; worker işi yoktur.
Hesaplanan listelerde sıralama açıkça tekilleştirilir (`sayfala`'nın PK
kırılması ham kolonlu sorguya eklenmez — kontrol §2/8).

**Personel süzgeci:** çalışan = aktif ve ayrılmamış; girişsiz personel
DAHİL, ayrılan HARİÇ (TS-159). İptal edilen plan/gözlem hiçbir sayıya girmez.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Date,
    Integer,
    Select,
    and_,
    case,
    cast,
    column,
    exists,
    func,
    literal,
    select,
    union_all,
    values,
)

from app.models import (
    PersonnelCertificate,
    TrainingCorrectiveAction,
    TrainingCourse,
    TrainingObservation,
    TrainingPlan,
    User,
    UserUnit,
)
from app.services import settings as ayar_svc
from app.services.teknik_servis import kapsam
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.egitim import ACIK_PLAN_DURUMLARI, birim_dogrula, calisan_kosulu
from app.services.teknik_servis.egitim_yetkinlik import matris_sorgusu
from app.services.teknik_servis.yerel_zaman import yerel_bugun
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

TAKIP_ASAMALARI = (30, 60, 90)
TAKIP_DURUMLARI = ("GECIKTI", "ZAMANI_GELDI", "YAKLASAN")
GECERLILIK_DURUMLARI = ("DOLDU", "DOLACAK", "GECERLI")


def _birim_uyesi(sutun, birim: str | None):
    if not birim:
        return None
    return exists().where(UserUnit.user_id == sutun, UserUnit.birim == birim_dogrula(birim))


def _kapsamli(stmt: Select, user: User, kisi_sutunu, birim: str | None) -> Select:
    stmt = kapsam.kapsam_personel(stmt, user, kisi_sutunu)
    kosul = _birim_uyesi(kisi_sutunu, birim)
    return stmt if kosul is None else stmt.where(kosul)


# --- Liste sorguları (liste, KPI, uyarı, Excel AYNI fonksiyon) -----------------------


@dataclass
class PlanSuzgeci:
    yil: int | None = None
    birim: str | None = None
    kurs_id: int | None = None
    durum: str | None = None
    kisi_id: int | None = None
    q: str | None = None
    acik: bool = False
    geciken: bool = False
    # Açık ve hedefi bugün + N günü geçmeyen planlar (uyarı `egitim.plan_vadesi`).
    vade_gun: int | None = None
    iptaller_dahil: bool = True


def plan_sorgusu(user: User, s: PlanSuzgeci, *, bugun: date) -> Select:
    """Yıllık plan listesi (kişi adı ve kurs ile)."""
    stmt = (
        select(
            TrainingPlan,
            User.full_name.label("ad"),
            TrainingCourse.kod.label("kurs_kod"),
            TrainingCourse.baslik.label("kurs"),
        )
        .join(User, User.id == TrainingPlan.user_id)
        .join(TrainingCourse, TrainingCourse.id == TrainingPlan.course_id)
        .where(TrainingPlan.is_deleted.is_(False))
        .order_by(TrainingPlan.plan_yili.desc(), TrainingPlan.hedef_tarih, User.full_name)
    )
    stmt = _kapsamli(stmt, user, TrainingPlan.user_id, s.birim)
    if s.yil is not None:
        stmt = stmt.where(TrainingPlan.plan_yili == s.yil)
    if s.kurs_id is not None:
        stmt = stmt.where(TrainingPlan.course_id == s.kurs_id)
    if s.durum:
        stmt = stmt.where(TrainingPlan.status == s.durum)
    elif not s.iptaller_dahil:
        stmt = stmt.where(TrainingPlan.status != "IPTAL")
    if s.kisi_id is not None:
        stmt = stmt.where(TrainingPlan.user_id == s.kisi_id)
    if s.q:
        desen = f"%{s.q.strip()}%"
        stmt = stmt.where(User.full_name.ilike(desen) | TrainingCourse.baslik.ilike(desen))
    if s.acik or s.geciken or s.vade_gun is not None:
        stmt = stmt.where(
            TrainingPlan.status.in_(ACIK_PLAN_DURUMLARI),
            calisan_kosulu(),
            TrainingCourse.is_active.is_(True),
        )
    if s.geciken:
        stmt = stmt.where(TrainingPlan.hedef_tarih < bugun)
    if s.vade_gun is not None:
        stmt = stmt.where(TrainingPlan.hedef_tarih <= bugun + timedelta(days=s.vade_gun))
    return stmt


@dataclass
class GozlemSuzgeci:
    yil: int | None = None
    birim: str | None = None
    kisi_id: int | None = None
    kurs_id: int | None = None
    asama: int | None = None
    sonuc: str | None = None
    service_order_id: int | None = None
    iptaller_dahil: bool = False


def gozlem_sorgusu(user: User, s: GozlemSuzgeci) -> Select:
    """Gözlem listesi. Yıl verilirse yıl ± 1 değil TAM yıl; liste ucu yıl
    verilmezse yıl ± 1 sınırını kendisi uygular (M08-16 özü)."""
    stmt = (
        select(
            TrainingObservation,
            User.full_name.label("ad"),
            TrainingCourse.baslik.label("kurs"),
        )
        .join(User, User.id == TrainingObservation.user_id)
        .join(TrainingCourse, TrainingCourse.id == TrainingObservation.course_id)
        .where(TrainingObservation.is_deleted.is_(False))
        .order_by(TrainingObservation.gozlem_tarihi.desc(), TrainingObservation.id.desc())
    )
    stmt = _kapsamli(stmt, user, TrainingObservation.user_id, s.birim)
    if not s.iptaller_dahil:
        stmt = stmt.where(TrainingObservation.cancelled_at.is_(None))
    if s.yil is not None:
        stmt = stmt.where(
            TrainingObservation.gozlem_tarihi >= date(s.yil, 1, 1),
            TrainingObservation.gozlem_tarihi < date(s.yil + 1, 1, 1),
        )
    if s.kisi_id is not None:
        stmt = stmt.where(TrainingObservation.user_id == s.kisi_id)
    if s.kurs_id is not None:
        stmt = stmt.where(TrainingObservation.course_id == s.kurs_id)
    if s.asama is not None:
        stmt = stmt.where(TrainingObservation.asama == s.asama)
    if s.sonuc:
        stmt = stmt.where(TrainingObservation.sonuc == s.sonuc)
    if s.service_order_id is not None:
        stmt = stmt.where(TrainingObservation.service_order_id == s.service_order_id)
    return stmt


@dataclass
class FaaliyetSuzgeci:
    durum: str | None = None
    gecikmis: bool = False
    birim: str | None = None
    kisi_id: int | None = None


def faaliyet_sorgusu(user: User, s: FaaliyetSuzgeci, *, bugun: date) -> Select:
    """Düzeltici faaliyet listesi (gözlem iptal bilgisiyle)."""
    stmt = (
        select(
            TrainingCorrectiveAction,
            User.full_name.label("ad"),
            TrainingCourse.baslik.label("kurs"),
            TrainingObservation.gozlem_tarihi,
            TrainingObservation.cancelled_at.label("gozlem_iptal_at"),
        )
        .join(User, User.id == TrainingCorrectiveAction.user_id)
        .join(TrainingCourse, TrainingCourse.id == TrainingCorrectiveAction.course_id)
        .join(
            TrainingObservation, TrainingObservation.id == TrainingCorrectiveAction.observation_id
        )
        .order_by(TrainingCorrectiveAction.termin, TrainingCorrectiveAction.id)
    )
    stmt = _kapsamli(stmt, user, TrainingCorrectiveAction.user_id, s.birim)
    if s.durum:
        stmt = stmt.where(TrainingCorrectiveAction.status == s.durum)
    if s.gecikmis:
        stmt = stmt.where(
            TrainingCorrectiveAction.status == "ACIK", TrainingCorrectiveAction.termin < bugun
        )
    if s.kisi_id is not None:
        stmt = stmt.where(TrainingCorrectiveAction.user_id == s.kisi_id)
    if s.durum == "ACIK" or s.gecikmis:
        stmt = stmt.where(calisan_kosulu())
    return stmt


def takip_sorgusu(
    user: User,
    clock: Clock,
    *,
    pencere_gun: int = 7,
    durumlar: tuple[str, ...] = TAKIP_DURUMLARI,
    birim: str | None = None,
    kisi_id: int | None = None,
) -> Select:
    """30/60/90 takip listesi (açık ORDER BY).

    TAMAMLANDI ve silinmemiş plan × (30, 60, 90); vade = `completed_on + N`.
    Takibi kapatan gözlem: aynı kişi+kurs+aşama, `gozlem_tarihi >=
    completed_on`, iptal edilmemiş (K19: önceki yılın gözlemi saymaz; iptal
    edilen gözlem takibi yeniden açar). Pasif kurs/ayrılan personel dışarıda.
    Durum: GECIKTI (vade < bugün), ZAMANI_GELDI (= bugün), YAKLASAN
    (≤ bugün + pencere). Uç ve uyarı aynı fonksiyondan sayılır.
    """
    bugun = yerel_bugun(clock)
    asamalar = values(column("asama", Integer), name="asamalar").data(
        [(a,) for a in TAKIP_ASAMALARI]
    )
    vade = (TrainingPlan.completed_on + asamalar.c.asama).label("vade")
    durum = case(
        (TrainingPlan.completed_on + asamalar.c.asama < bugun, literal("GECIKTI")),
        (TrainingPlan.completed_on + asamalar.c.asama == bugun, literal("ZAMANI_GELDI")),
        else_=literal("YAKLASAN"),
    ).label("durum")
    kapatan = exists().where(
        TrainingObservation.user_id == TrainingPlan.user_id,
        TrainingObservation.course_id == TrainingPlan.course_id,
        TrainingObservation.asama == asamalar.c.asama,
        TrainingObservation.gozlem_tarihi >= TrainingPlan.completed_on,
        TrainingObservation.cancelled_at.is_(None),
        TrainingObservation.is_deleted.is_(False),
    )
    stmt = (
        select(
            TrainingPlan.id.label("plan_id"),
            TrainingPlan.user_id,
            User.full_name.label("ad"),
            TrainingPlan.course_id,
            TrainingCourse.baslik.label("kurs"),
            asamalar.c.asama,
            TrainingPlan.completed_on,
            vade,
            durum,
        )
        .select_from(TrainingPlan)
        .join(asamalar, literal(True))
        .join(User, User.id == TrainingPlan.user_id)
        .join(TrainingCourse, TrainingCourse.id == TrainingPlan.course_id)
        .where(
            TrainingPlan.status == "TAMAMLANDI",
            TrainingPlan.is_deleted.is_(False),
            TrainingPlan.completed_on.is_not(None),
            TrainingCourse.is_active.is_(True),
            TrainingCourse.is_deleted.is_(False),
            calisan_kosulu(),
            ~kapatan,
            TrainingPlan.completed_on + asamalar.c.asama <= bugun + timedelta(days=pencere_gun),
        )
        .order_by(vade, TrainingPlan.id, asamalar.c.asama)
    )
    stmt = _kapsamli(stmt, user, TrainingPlan.user_id, birim)
    secili = [d for d in durumlar if d in TAKIP_DURUMLARI]
    if set(secili) != set(TAKIP_DURUMLARI):
        stmt = stmt.where(durum.in_(secili))
    if kisi_id is not None:
        stmt = stmt.where(TrainingPlan.user_id == kisi_id)
    return stmt


def _gecerlilik_kaynagi():
    """Plan + belge geçerlilik satırları (birleşik alt sorgu).

    Plan: kursun `yenileme_ay`'ı doluysa kişi+kurs için EN SON tamamlanan
    planın `completed_on + yenileme_ay ay`'ı. Belge: iptal edilmemiş ve bitişi
    olan elle girilmiş belge. `yenileme_ay` NULL ve belge yoksa satır yok →
    uyarı 0 (K14).
    """
    son_plan = (
        select(
            literal("PLAN").label("kaynak"),
            TrainingPlan.id.label("kayit_id"),
            TrainingPlan.user_id,
            TrainingPlan.course_id,
            TrainingCourse.baslik.label("ad"),
            TrainingPlan.completed_on.label("baslangic"),
            cast(
                TrainingPlan.completed_on + func.make_interval(0, TrainingCourse.yenileme_ay), Date
            ).label("bitis"),
        )
        .join(TrainingCourse, TrainingCourse.id == TrainingPlan.course_id)
        .where(
            TrainingPlan.status == "TAMAMLANDI",
            TrainingPlan.is_deleted.is_(False),
            TrainingCourse.yenileme_ay.is_not(None),
            TrainingCourse.is_active.is_(True),
            TrainingCourse.is_deleted.is_(False),
        )
        .distinct(TrainingPlan.user_id, TrainingPlan.course_id)
        .order_by(
            TrainingPlan.user_id,
            TrainingPlan.course_id,
            TrainingPlan.completed_on.desc(),
            TrainingPlan.id.desc(),
        )
        .subquery("son_plan")
    )
    # DISTINCT ON + ORDER BY'lı sorgu UNION'a ancak alt sorgu olarak girer.
    plan_satirlari = select(*son_plan.c)
    belge = select(
        literal("BELGE").label("kaynak"),
        PersonnelCertificate.id.label("kayit_id"),
        PersonnelCertificate.user_id,
        PersonnelCertificate.course_id,
        PersonnelCertificate.belge_adi.label("ad"),
        PersonnelCertificate.verilis_tarihi.label("baslangic"),
        PersonnelCertificate.gecerlilik_bitis.label("bitis"),
    ).where(
        PersonnelCertificate.cancelled_at.is_(None),
        PersonnelCertificate.gecerlilik_bitis.is_not(None),
    )
    return union_all(plan_satirlari, belge).subquery("gecerlilik")


def gecerlilik_sorgusu(
    user: User,
    clock: Clock,
    *,
    pencere_gun: int = 30,
    durum: str | None = None,
    birim: str | None = None,
    kisi_id: int | None = None,
) -> Select:
    """Plan + belge geçerliliği tek fonksiyon (uyarı, liste, KPI aynı sayı)."""
    bugun = yerel_bugun(clock)
    g = _gecerlilik_kaynagi()
    durum_ifadesi = case(
        (g.c.bitis < bugun, literal("DOLDU")),
        (g.c.bitis <= bugun + timedelta(days=pencere_gun), literal("DOLACAK")),
        else_=literal("GECERLI"),
    ).label("durum")
    stmt = (
        select(
            g.c.kaynak,
            g.c.kayit_id,
            g.c.user_id,
            User.full_name.label("kisi"),
            g.c.course_id,
            g.c.ad,
            g.c.baslangic,
            g.c.bitis,
            durum_ifadesi,
        )
        .join(User, User.id == g.c.user_id)
        .where(calisan_kosulu())
        .order_by(g.c.bitis, g.c.kaynak, g.c.kayit_id)
    )
    stmt = _kapsamli(stmt, user, g.c.user_id, birim)
    if durum:
        if durum not in GECERLILIK_DURUMLARI:
            from app.services.teknik_servis.egitim import EgitimGirdiHatasi

            raise EgitimGirdiHatasi(f"Bilinmeyen geçerlilik durumu: {durum}")
        stmt = stmt.where(durum_ifadesi == durum)
    if kisi_id is not None:
        stmt = stmt.where(g.c.user_id == kisi_id)
    return stmt


# --- KPI tanımları (TS-153) -------------------------------------------------------------


@dataclass(frozen=True)
class KpiTanimi:
    """`KpiKutusu`'nun beslendiği tanım; `liste` + `suzgec` tıklanınca açılan
    listenin sorgusudur (sayı = liste)."""

    kod: str
    baslik: str
    tanim: str
    sekme: str
    liste: str  # planlar | gozlemler | faaliyetler | takipler | belgeler | matris
    suzgec: dict[str, Any] = field(default_factory=dict)
    vurgu: str = "normal"


KPI_TANIMLARI: dict[str, KpiTanimi] = {
    t.kod: t
    for t in (
        KpiTanimi(
            "plan_acik",
            "Açık plan",
            "Seçili yılın tamamlanmamış (planlandı/ertelendi/tekrar) planları",
            "plan",
            "planlar",
            {"acik": True},
        ),
        KpiTanimi(
            "plan_geciken",
            "Geciken plan",
            "Hedef tarihi geçmiş ve hâlâ açık planlar",
            "plan",
            "planlar",
            {"geciken": True},
            "kritik",
        ),
        KpiTanimi(
            "plan_tamamlanan",
            "Tamamlanan plan",
            "Seçili yılda tamamlanan planlar",
            "plan",
            "planlar",
            {"durum": "TAMAMLANDI"},
        ),
        KpiTanimi(
            "gozlem_basarili",
            "Başarılı gözlem",
            "Seçili yılın iptal edilmemiş BAŞARILI sonuçlu saha gözlemleri",
            "gozlem",
            "gozlemler",
            {"sonuc": "BASARILI"},
        ),
        KpiTanimi(
            "gozlem_kritik",
            "Kritik gözlem",
            "Kritik maddede uygunsuzluk bulunan gözlemler (ortalamadan bağımsız)",
            "gozlem",
            "gozlemler",
            {"sonuc": "KRITIK"},
            "kritik",
        ),
        KpiTanimi(
            "faaliyet_acik",
            "Açık düzeltici faaliyet",
            "Kritik İSG uygunsuzluğu için açık düzeltici faaliyetler",
            "faaliyet",
            "faaliyetler",
            {"durum": "ACIK"},
            "uyari",
        ),
        KpiTanimi(
            "faaliyet_geciken",
            "Termini geçen faaliyet",
            "Termini geçmiş açık düzeltici faaliyetler",
            "faaliyet",
            "faaliyetler",
            {"gecikmis": True},
            "kritik",
        ),
        KpiTanimi(
            "takip_geciken",
            "Geciken 30/60/90",
            "Vadesi geçmiş ve gözlemi yapılmamış 30/60/90. gün takipleri",
            "takip",
            "takipler",
            {"durumlar": ("GECIKTI",)},
            "kritik",
        ),
        KpiTanimi(
            "belge_doldu",
            "Süresi dolan",
            "Geçerliliği dolmuş eğitim/belge",
            "belge",
            "belgeler",
            {"durum": "DOLDU"},
            "kritik",
        ),
        KpiTanimi(
            "belge_dolacak",
            "Süresi dolacak",
            "Geçerliliği uyarı penceresi içinde dolacak eğitim/belge",
            "belge",
            "belgeler",
            {"durum": "DOLACAK"},
            "uyari",
        ),
        KpiTanimi(
            "yetkinlik_hedef_alti",
            "Hedefin altında yetkinlik",
            "Güncel seviyesi hedefin altında olan kişi × yetkinlik",
            "yetkinlik",
            "matris",
            {"hedef_alti": True},
        ),
        KpiTanimi(
            "yetkinlik_kritik_alti",
            "Kritik yetkinlik açığı",
            "Kritik yetkinlikte hedefin altında kalan kişi × yetkinlik",
            "yetkinlik",
            "matris",
            {"hedef_alti": True, "yalniz_kritik": True},
            "kritik",
        ),
    )
}


async def _pencereler(db: AsyncSession) -> tuple[int, int]:
    return (
        int(await ayar_svc.get(db, "egitim_takip_pencere_gun")),
        int(await ayar_svc.get(db, "egitim_belge_uyari_gun")),
    )


async def kpi_sorgusu(
    db: AsyncSession,
    user: User,
    kod: str,
    clock: Clock,
    *,
    yil: int | None = None,
    birim: str | None = None,
) -> Select:
    """KPI kodunun LİSTE sorgusu (liste ucu `?kpi=` ile bunu çağırır)."""
    from app.services.teknik_servis.egitim import EgitimGirdiHatasi

    tanim = KPI_TANIMLARI.get(kod)
    if tanim is None:
        raise EgitimGirdiHatasi(f"Bilinmeyen KPI: {kod}")
    bugun = yerel_bugun(clock)
    takip_pencere, belge_pencere = await _pencereler(db)
    if tanim.liste == "planlar":
        return plan_sorgusu(user, PlanSuzgeci(yil=yil, birim=birim, **tanim.suzgec), bugun=bugun)
    if tanim.liste == "gozlemler":
        return gozlem_sorgusu(user, GozlemSuzgeci(yil=yil, birim=birim, **tanim.suzgec))
    if tanim.liste == "faaliyetler":
        return faaliyet_sorgusu(user, FaaliyetSuzgeci(birim=birim, **tanim.suzgec), bugun=bugun)
    if tanim.liste == "takipler":
        return takip_sorgusu(user, clock, pencere_gun=takip_pencere, birim=birim, **tanim.suzgec)
    if tanim.liste == "belgeler":
        return gecerlilik_sorgusu(
            user, clock, pencere_gun=belge_pencere, birim=birim, **tanim.suzgec
        )
    return matris_sorgusu(user, birim=birim, **tanim.suzgec)


async def say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def _kaynak_var_mi(db: AsyncSession, liste: str) -> bool:
    """ "Henüz gelmemiş kutu gösterilmez ('0' değil)": belge kutuları yenilemeli
    kurs ya da belge yokken, yetkinlik kutuları değerlendirme yokken çizilmez."""
    from app.models import CompetencyAssessment

    if liste == "belgeler":
        kurs = await db.scalar(
            select(TrainingCourse.id).where(TrainingCourse.yenileme_ay.is_not(None)).limit(1)
        )
        belge = await db.scalar(select(PersonnelCertificate.id).limit(1))
        return kurs is not None or belge is not None
    if liste == "matris":
        return (await db.scalar(select(CompetencyAssessment.id).limit(1))) is not None
    return True


async def ozet(
    db: AsyncSession, user: User, clock: Clock, *, yil: int, birim: str | None = None
) -> dict[str, Any]:
    """Eğitim Yönetim Özeti: kutular (sayı = liste), yıllık gerçekleşme,
    gözlem başarı oranı (ortalama ikincil), birim ilerlemesi."""
    kutular = []
    for t in KPI_TANIMLARI.values():
        if not await _kaynak_var_mi(db, t.liste):
            continue
        stmt = await kpi_sorgusu(db, user, t.kod, clock, yil=yil, birim=birim)
        parametre = f"&yil={yil}" + (f"&birim={birim}" if birim else "")
        kutular.append(
            {
                "kod": t.kod,
                "baslik": t.baslik,
                "tanim": t.tanim,
                "deger": await say(db, stmt),
                "yol": f"/egitim?sekme={t.sekme}&kpi={t.kod}{parametre}",
                "vurgu": t.vurgu,
            }
        )

    # Yıllık gerçekleşme: iptal dışı planlar; zamanında/geç/açık.
    planlar = plan_sorgusu(
        user, PlanSuzgeci(yil=yil, birim=birim, iptaller_dahil=False), bugun=yerel_bugun(clock)
    ).subquery()
    satir = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(planlar.c.status == "TAMAMLANDI"),
                func.count().filter(
                    and_(
                        planlar.c.status == "TAMAMLANDI",
                        planlar.c.completed_on <= planlar.c.hedef_tarih,
                    )
                ),
            ).select_from(planlar)
        )
    ).one()
    toplam, tamam, zamaninda = (int(x or 0) for x in satir)
    gerceklesme = {
        "toplam": toplam,
        "tamamlanan": tamam,
        "zamaninda": zamaninda,
        "gec": tamam - zamaninda,
        "acik": toplam - tamam,
        "yuzde": round(100 * tamam / toplam, 1) if toplam else None,
    }

    gozlemler = gozlem_sorgusu(user, GozlemSuzgeci(yil=yil, birim=birim)).subquery()
    g = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(gozlemler.c.sonuc == "BASARILI"),
                func.avg(gozlemler.c.puan),
            ).select_from(gozlemler)
        )
    ).one()
    gozlem_toplam = int(g[0] or 0)
    gozlem = {
        "toplam": gozlem_toplam,
        "basarili": int(g[1] or 0),
        "basari_orani": round(100 * int(g[1] or 0) / gozlem_toplam, 1) if gozlem_toplam else None,
        "ortalama_puan": round(float(g[2]), 2) if g[2] is not None else None,
    }

    birim_ilerleme = []
    for b in ("GUVENLIK", "HABERLESME", "POC", "MOBILITE", "ARAC_TAKIP"):
        if birim and b != birim:
            continue
        alt = plan_sorgusu(
            user, PlanSuzgeci(yil=yil, birim=b, iptaller_dahil=False), bugun=yerel_bugun(clock)
        ).subquery()
        bt, btam = (
            await db.execute(
                select(func.count(), func.count().filter(alt.c.status == "TAMAMLANDI")).select_from(
                    alt
                )
            )
        ).one()
        if bt:
            birim_ilerleme.append({"birim": b, "toplam": int(bt), "tamamlanan": int(btam or 0)})
    return {
        "yil": yil,
        "kutular": kutular,
        "gerceklesme": gerceklesme,
        "gozlem": gozlem,
        "birim_ilerleme": birim_ilerleme,
    }


# --- Uyarılar (TS-159; plan §1.11 kayıt defteri) ---------------------------------------


async def egitim_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Eğitim uyarıları — her sayı liste sorgusunun kendisinden (sayı = liste).

    Birim süzmesi sorgunun içinde (`kapsam_personel`); birimsiz şefte 0;
    ayrılan personel, pasif kurs ve iptal kayıtlar dışarıda.
    """
    bugun = yerel_bugun(clock)
    takip_pencere, belge_pencere = await _pencereler(db)
    plan_gun = int(await ayar_svc.get(db, "egitim_plan_uyari_gun"))
    vadeli = plan_sorgusu(user, PlanSuzgeci(vade_gun=plan_gun), bugun=bugun)
    takip = takip_sorgusu(
        user, clock, pencere_gun=takip_pencere, durumlar=("GECIKTI", "ZAMANI_GELDI")
    )
    acik = faaliyet_sorgusu(user, FaaliyetSuzgeci(durum="ACIK"), bugun=bugun)
    geciken = faaliyet_sorgusu(user, FaaliyetSuzgeci(gecikmis=True), bugun=bugun)
    doldu = gecerlilik_sorgusu(user, clock, pencere_gun=belge_pencere, durum="DOLDU")
    dolacak = gecerlilik_sorgusu(user, clock, pencere_gun=belge_pencere, durum="DOLACAK")
    return [
        Uyari(
            kod="egitim.plan_vadesi",
            baslik="Hedef tarihi yaklaşan/geçen eğitim planı",
            adet=await say(db, vadeli),
            yol="/egitim?sekme=plan&vade=1",
            onem="uyari",
        ),
        Uyari(
            kod="egitim.takip",
            baslik="Zamanı gelen 30/60/90 saha gözlemi",
            adet=await say(db, takip),
            yol="/egitim?sekme=takip&vadesi_gelen=1",
            onem="uyari",
        ),
        Uyari(
            kod="egitim.duzeltici",
            baslik="Açık düzeltici faaliyet (kritik İSG)",
            adet=await say(db, acik),
            yol="/egitim?sekme=faaliyet&kpi=faaliyet_acik",
            onem="uyari",
        ),
        Uyari(
            kod="egitim.duzeltici_gecikti",
            baslik="Termini geçen düzeltici faaliyet",
            adet=await say(db, geciken),
            yol="/egitim?sekme=faaliyet&kpi=faaliyet_geciken",
            onem="kritik",
        ),
        Uyari(
            kod="egitim.belge_bitiyor",
            baslik="Geçerliliği dolacak eğitim/belge",
            adet=await say(db, dolacak),
            yol="/egitim?sekme=belge&kpi=belge_dolacak",
            onem="uyari",
        ),
        Uyari(
            kod="egitim.belge_doldu",
            baslik="Geçerliliği dolan eğitim/belge",
            adet=await say(db, doldu),
            yol="/egitim?sekme=belge&kpi=belge_doldu",
            onem="kritik",
        ),
    ]


ts_uyarilari_kaydi = ts_uyarilar.kaydet("egitim", "egitim.gor", egitim_uyarilari)
