"""Eğitim ve gelişim uçları (TS-150…160).

İzinler (plan §1.3): `egitim.gor` özet/katalog, `egitim.detay` kişisel ayrıntı,
`egitim.yaz` katalog/plan/oturum/katılım/belge, `egitim.gozlem` gözlem/değerlendirme,
`egitim.kendim` Gelişim Kartım. Excel `egitim.gor` + `servis_rapor.disaaktar`
(KD-06: servis rollerine `rapor.disaaktar` verilmez). Eğitimde fiyat/maliyet alanı
YOKTUR (K20).

**Yol sözleşmesi:** kişiye ait kayıtlar (plan, gözlem, faaliyet, belge) kişinin
altında adreslenir: `/kisiler/{personel_id}/...`. Önce KİŞİ kapsamı sınanır —
kapsam dışı kişi 404 ve hiçbir yazma yapılmaz; kayıt o kişiye ait değilse de 404.
Böylece uç taraması (`test_router_kapsam_taramasi`) bu uçları kendiliğinden kapsar.
Katalog öğeleri (kurs, kriter, oturum, yetkinlik) gizli değildir; kimlikleri
gövdede taşınır ve başka birimin öğesine yazma 403'tür (K4).

**İki katmanlı çıktı (E08-20, TS-154):** gözlem notu, madde puanları, aksiyon
planı, yetkinlik kanıtı, belge no/açıklama ve faaliyet kanıtı YALNIZ
`egitim.detay` sahibine döner — diğerlerinde anahtar YOK (`null` değil). YONETIM
yalnız özet görür. Kişi kartı açılışı KVKK erişim loguna (`entity="users"`,
`amac="egitim.kart"`) yazılır; her xlsx denetim izine kişisel veri olarak yazılır.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
    sayfala,
)
from app.models import (
    Competency,
    PersonnelCertificate,
    TrainingAttendance,
    TrainingCorrectiveAction,
    TrainingCourse,
    TrainingCriterion,
    TrainingObservation,
    TrainingObservationRating,
    TrainingPlan,
    TrainingSession,
    User,
)
from app.services import audit, kvkk
from app.services import export as export_svc
from app.services.teknik_servis import egitim as svc
from app.services.teknik_servis import egitim_gozlem as gozlem_svc
from app.services.teknik_servis import egitim_rapor as rapor
from app.services.teknik_servis import egitim_yetkinlik as yetkinlik_svc
from app.services.teknik_servis import personel as personel_svc
from app.services.teknik_servis.egitim import EgitimHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun

router = APIRouter(prefix="/api/egitim", tags=["egitim"])

Okuyucu = Annotated[User, Depends(require_permission("egitim.gor"))]
Yazici = Annotated[User, Depends(require_permission("egitim.yaz"))]
Gozlemci = Annotated[User, Depends(require_permission("egitim.gozlem"))]
Kendim = Annotated[User, Depends(require_permission("egitim.kendim"))]
Aktarici = Annotated[User, Depends(require_permission("egitim.gor", "servis_rapor.disaaktar"))]
GozlemIptalci = Annotated[User, Depends(require_any_permission("egitim.gozlem", "egitim.yaz"))]

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]

_SURUM_MESAJI = (
    "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin."
)


def _hata(exc: EgitimHatasi) -> HTTPException:
    if exc.satir is not None:
        return HTTPException(exc.kod, {"satir": exc.satir, "mesaj": exc.mesaj})
    return HTTPException(exc.kod, exc.mesaj)


def _surum(kayit: Any, version: int | None) -> None:
    if version is not None and version != kayit.version:
        raise HTTPException(status.HTTP_409_CONFLICT, _SURUM_MESAJI)


def _detay(user: User) -> bool:
    return user.has("egitim.detay")


# --- Şemalar -----------------------------------------------------------------------------


class KursIn(BaseModel):
    kod: str = Field(min_length=1, max_length=30)
    baslik: str = Field(min_length=1, max_length=200)
    kategori: str = Field(max_length=20)
    birim: str | None = Field(default=None, max_length=20)
    sure_saat: Decimal = Field(ge=Decimal("0.5"), le=24)
    zorunlu: bool = False
    neden: str | None = Field(default=None, max_length=4000)
    hedef_davranis: str | None = Field(default=None, max_length=4000)
    basari_olcutu: str | None = Field(default=None, max_length=4000)
    gozlem_esik_yuzde: Decimal | None = Field(default=None, ge=0, le=100)
    sinav_gecme_puani: int | None = Field(default=None, ge=0, le=100)
    yenileme_ay: int | None = Field(default=None, ge=1, le=120)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"kod": "ISG-01", "baslik": "Yüksekte Çalışma", "kategori": "ISG", "sure_saat": 4}
            ]
        }
    }


class KursPatch(BaseModel):
    id: int
    version: int
    kod: str | None = Field(default=None, min_length=1, max_length=30)
    baslik: str | None = Field(default=None, min_length=1, max_length=200)
    kategori: str | None = Field(default=None, max_length=20)
    birim: str | None = Field(default=None, max_length=20)
    sure_saat: Decimal | None = Field(default=None, ge=Decimal("0.5"), le=24)
    zorunlu: bool | None = None
    neden: str | None = Field(default=None, max_length=4000)
    hedef_davranis: str | None = Field(default=None, max_length=4000)
    basari_olcutu: str | None = Field(default=None, max_length=4000)
    gozlem_esik_yuzde: Decimal | None = Field(default=None, ge=0, le=100)
    sinav_gecme_puani: int | None = Field(default=None, ge=0, le=100)
    yenileme_ay: int | None = Field(default=None, ge=1, le=120)
    is_active: bool | None = None

    model_config = {
        "json_schema_extra": {"examples": [{"id": 1, "version": 1, "is_active": False}]}
    }


class KursOut(BaseModel):
    id: int
    kod: str
    baslik: str
    kategori: str
    birim: str | None
    sure_saat: Decimal
    zorunlu: bool
    neden: str | None
    hedef_davranis: str | None
    basari_olcutu: str | None
    gozlem_esik_yuzde: Decimal | None
    sinav_gecme_puani: int | None
    yenileme_ay: int | None
    is_active: bool
    version: int

    model_config = {"from_attributes": True}


class KriterIn(BaseModel):
    kurs_id: int
    metin: str = Field(min_length=1, max_length=300)
    is_critical: bool = False

    model_config = {
        "json_schema_extra": {"examples": [{"kurs_id": 1, "metin": "Emniyet kemeri takılı"}]}
    }


class KriterPatch(BaseModel):
    id: int
    version: int
    metin: str | None = Field(default=None, min_length=1, max_length=300)
    is_critical: bool | None = None
    is_active: bool | None = None

    model_config = {
        "json_schema_extra": {"examples": [{"id": 1, "version": 1, "is_active": False}]}
    }


class KriterOut(BaseModel):
    id: int
    course_id: int
    sira: int
    metin: str
    is_critical: bool
    is_active: bool
    version: int

    model_config = {"from_attributes": True}


class TopluPlanIn(BaseModel):
    course_id: int
    plan_yili: int = Field(ge=2020, le=2100)
    hedef_tarih: date | None = None
    gelisim_hedefi: str | None = Field(default=None, max_length=2000)
    user_ids: list[int] = Field(min_length=1, max_length=1000)

    model_config = {
        "json_schema_extra": {"examples": [{"course_id": 1, "plan_yili": 2026, "user_ids": [1]}]}
    }


class ErteleIn(BaseModel):
    yeni_tarih: date
    gerekce: str = Field(max_length=500)
    version: int | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"yeni_tarih": "2026-12-20", "gerekce": "Saha yoğunluğu"}]
        }
    }


class GerekceIn(BaseModel):
    gerekce: str = Field(max_length=500)
    version: int | None = None

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "Hatalı kayıt"}]}}


class OturumIn(BaseModel):
    course_id: int
    oturum_tarihi: date
    egitmen_ad: str | None = Field(default=None, max_length=120)
    egitmen_user_id: int | None = None
    sure_saat: Decimal | None = Field(default=None, ge=Decimal("0.5"), le=24)
    yer: str | None = Field(default=None, max_length=200)
    notlar: str | None = Field(default=None, max_length=4000)

    model_config = {
        "json_schema_extra": {"examples": [{"course_id": 1, "oturum_tarihi": "2026-01-15"}]}
    }


class OturumPatch(BaseModel):
    id: int
    version: int
    oturum_tarihi: date | None = None
    egitmen_ad: str | None = Field(default=None, max_length=120)
    egitmen_user_id: int | None = None
    sure_saat: Decimal | None = Field(default=None, ge=Decimal("0.5"), le=24)
    yer: str | None = Field(default=None, max_length=200)
    notlar: str | None = Field(default=None, max_length=4000)

    model_config = {"json_schema_extra": {"examples": [{"id": 1, "version": 1, "yer": "Merkez"}]}}


class OturumSilIn(BaseModel):
    id: int
    version: int

    model_config = {"json_schema_extra": {"examples": [{"id": 1, "version": 1}]}}


class OturumOut(BaseModel):
    id: int
    course_id: int
    kurs: str | None = None
    oturum_tarihi: date
    egitmen_ad: str | None
    egitmen_user_id: int | None
    sure_saat: Decimal
    yer: str | None
    notlar: str | None
    katilimci: int = 0
    version: int


class KatilimIn(BaseModel):
    oturum_id: int
    user_id: int
    katildi: bool = True
    on_puan: int | None = Field(default=None, ge=0, le=100)
    son_puan: int | None = Field(default=None, ge=0, le=100)
    notlar: str | None = Field(default=None, max_length=1000)

    model_config = {
        "json_schema_extra": {"examples": [{"oturum_id": 1, "user_id": 1, "katildi": True}]}
    }


class KatilimSatiriIn(BaseModel):
    user_id: int
    katildi: bool = True
    on_puan: int | None = Field(default=None, ge=0, le=100)
    son_puan: int | None = Field(default=None, ge=0, le=100)
    notlar: str | None = Field(default=None, max_length=1000)


class TopluKatilimIn(BaseModel):
    oturum_id: int
    satirlar: list[KatilimSatiriIn] = Field(min_length=1, max_length=svc.TOPLU_KATILIM_UST_SINIR)

    model_config = {
        "json_schema_extra": {
            "examples": [{"oturum_id": 1, "satirlar": [{"user_id": 1, "katildi": True}]}]
        }
    }


class MaddePuaniIn(BaseModel):
    criterion_id: int
    puan: int = Field(ge=-1, le=2)
    gozlenmedi_gerekcesi: str | None = Field(default=None, max_length=300)


class GozlemIn(BaseModel):
    user_id: int
    course_id: int
    asama: int
    gozlem_tarihi: date
    plan_id: int | None = None
    service_order_id: int | None = None
    puanlar: list[MaddePuaniIn] = Field(min_length=1, max_length=200)
    notlar: str | None = Field(default=None, max_length=4000)
    aksiyon_plani: str | None = Field(default=None, max_length=4000)
    sonraki_izleme: date | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": 1,
                    "course_id": 1,
                    "asama": 0,
                    "gozlem_tarihi": "2026-01-15",
                    "puanlar": [{"criterion_id": 1, "puan": 2}],
                }
            ]
        }
    }


class GordumIn(BaseModel):
    gozlem_id: int
    yorum: str | None = Field(default=None, max_length=900)

    model_config = {"json_schema_extra": {"examples": [{"gozlem_id": 1, "yorum": "Okudum"}]}}


class KanitIn(BaseModel):
    kanit: str = Field(max_length=4000)
    version: int | None = None

    model_config = {"json_schema_extra": {"examples": [{"kanit": "Eğitim tekrarlandı"}]}}


class BelgeIn(BaseModel):
    user_id: int
    course_id: int | None = None
    belge_adi: str = Field(min_length=1, max_length=200)
    verilis_tarihi: date
    gecerlilik_bitis: date | None = None
    belge_no: str | None = Field(default=None, max_length=60)
    aciklama: str | None = Field(default=None, max_length=2000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"user_id": 1, "belge_adi": "Yüksekte Çalışma", "verilis_tarihi": "2026-01-15"}
            ]
        }
    }


class YetkinlikIn(BaseModel):
    kod: str = Field(min_length=1, max_length=20)
    ad: str = Field(min_length=1, max_length=150)
    birim: str | None = Field(default=None, max_length=20)
    onerilen_hedef: int = Field(default=3, ge=1, le=4)
    is_critical: bool = False

    model_config = {
        "json_schema_extra": {"examples": [{"kod": "XR", "ad": "X-Ray bakım", "onerilen_hedef": 3}]}
    }


class YetkinlikPatch(BaseModel):
    id: int
    version: int
    kod: str | None = Field(default=None, min_length=1, max_length=20)
    ad: str | None = Field(default=None, min_length=1, max_length=150)
    birim: str | None = Field(default=None, max_length=20)
    onerilen_hedef: int | None = Field(default=None, ge=1, le=4)
    is_critical: bool | None = None
    is_active: bool | None = None

    model_config = {
        "json_schema_extra": {"examples": [{"id": 1, "version": 1, "is_active": False}]}
    }


class YetkinlikOut(BaseModel):
    id: int
    kod: str
    ad: str
    birim: str | None
    onerilen_hedef: int
    is_critical: bool
    is_active: bool
    version: int

    model_config = {"from_attributes": True}


class DegerlendirmeIn(BaseModel):
    user_id: int
    competency_id: int
    mevcut_seviye: int = Field(ge=1, le=4)
    hedef_seviye: int | None = Field(default=None, ge=1, le=4)
    degerlendirme_tarihi: date | None = None
    kanit: str | None = Field(default=None, max_length=4000)
    observation_id: int | None = None
    sonraki_degerlendirme: date | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"user_id": 1, "competency_id": 1, "mevcut_seviye": 2, "kanit": "Saha"}]
        }
    }


# --- Çıktı yardımcıları -------------------------------------------------------------------


def _plan_satiri(p: TrainingPlan, ad: str, kurs_kod: str, kurs: str, bugun: date) -> dict:
    acik = p.status in svc.ACIK_PLAN_DURUMLARI
    return {
        "id": p.id,
        "user_id": p.user_id,
        "ad": ad,
        "course_id": p.course_id,
        "kurs_kod": kurs_kod,
        "kurs": kurs,
        "plan_yili": p.plan_yili,
        "hedef_tarih": p.hedef_tarih,
        "onceki_hedef_tarih": p.onceki_hedef_tarih,
        "status": p.status,
        "durum_gerekcesi": p.durum_gerekcesi,
        "gelisim_hedefi": p.gelisim_hedefi,
        "completed_on": p.completed_on,
        "completed_session_id": p.completed_session_id,
        "gec": p.completed_on is not None and p.completed_on > p.hedef_tarih,
        "geciken": acik and p.hedef_tarih < bugun,
        "sonraki_durumlar": sorted(svc.EGITIM_PLANI.sonraki(p.status)),
        "version": p.version,
    }


async def _madde_puanlari(db, gozlem_idler: list[int]) -> dict[int, list[dict]]:
    if not gozlem_idler:
        return {}
    satirlar = (
        await db.execute(
            select(TrainingObservationRating, TrainingCriterion)
            .join(TrainingCriterion, TrainingCriterion.id == TrainingObservationRating.criterion_id)
            .where(TrainingObservationRating.observation_id.in_(gozlem_idler))
            .order_by(TrainingCriterion.sira, TrainingCriterion.id)
        )
    ).all()
    sonuc: dict[int, list[dict]] = {}
    for r, k in satirlar:
        sonuc.setdefault(r.observation_id, []).append(
            {
                "criterion_id": k.id,
                "sira": k.sira,
                "metin": k.metin,
                "kritik": k.is_critical,
                "puan": r.puan,
                "gozlenmedi_gerekcesi": r.gozlenmedi_gerekcesi,
            }
        )
    return sonuc


async def _gozlem_ciktilari(
    db, satirlar: list[tuple[TrainingObservation, str, str]], *, detay: bool
) -> list[dict]:
    """Özet her zaman; detay alanları yalnız `detay` ise ANAHTAR olarak eklenir."""
    maddeler = await _madde_puanlari(db, [g.id for g, _, _ in satirlar]) if detay else {}
    cikti = []
    for g, ad, kurs in satirlar:
        d: dict[str, Any] = {
            "id": g.id,
            "user_id": g.user_id,
            "ad": ad,
            "course_id": g.course_id,
            "kurs": kurs,
            "plan_id": g.plan_id,
            "asama": g.asama,
            "gozlem_tarihi": g.gozlem_tarihi,
            "puan": g.puan,
            "sonuc": g.sonuc,
            "kritik": g.kritik,
            "observer_user_id": g.observer_user_id,
            "gozlemci_ad": g.gozlemci_ad,
            "service_order_id": g.service_order_id,
            "birim": g.birim,
            "gordu_at": g.gordu_at,
            "cancelled_at": g.cancelled_at,
            "cancel_reason": g.cancel_reason,
            "version": g.version,
        }
        if detay:
            d.update(
                notlar=g.notlar,
                aksiyon_plani=g.aksiyon_plani,
                sonraki_izleme=g.sonraki_izleme,
                personel_yorumu=g.personel_yorumu,
                maddeler=maddeler.get(g.id, []),
            )
        cikti.append(d)
    return cikti


def _faaliyet_satiri(
    f: TrainingCorrectiveAction, ad, kurs, gozlem_tarihi, iptal_at, bugun: date, *, detay: bool
) -> dict:
    d: dict[str, Any] = {
        "id": f.id,
        "observation_id": f.observation_id,
        "user_id": f.user_id,
        "ad": ad,
        "course_id": f.course_id,
        "kurs": kurs,
        "gozlem_tarihi": gozlem_tarihi,
        "gozlem_iptal": iptal_at is not None,
        "sorumlu_user_id": f.sorumlu_user_id,
        "termin": f.termin,
        "status": f.status,
        "gecikmis": f.status == "ACIK" and f.termin < bugun,
        "kapanis_turu": f.kapanis_turu,
        "closing_observation_id": f.closing_observation_id,
        "closed_at": f.closed_at,
        "version": f.version,
    }
    if detay:
        d["kapanis_kaniti"] = f.kapanis_kaniti
    return d


async def _gecerlilik_ciktilari(db, satirlar, *, detay: bool) -> list[dict]:
    belge_idler = [r.kayit_id for r in satirlar if r.kaynak == "BELGE"]
    belgeler: dict[int, PersonnelCertificate] = {}
    if detay and belge_idler:
        belgeler = {
            b.id: b
            for b in (
                await db.scalars(
                    select(PersonnelCertificate).where(PersonnelCertificate.id.in_(belge_idler))
                )
            ).all()
        }
    cikti = []
    for r in satirlar:
        d: dict[str, Any] = {
            "kaynak": r.kaynak,
            "kayit_id": r.kayit_id,
            "user_id": r.user_id,
            "kisi": r.kisi,
            "course_id": r.course_id,
            "ad": r.ad,
            "baslangic": r.baslangic,
            "bitis": r.bitis,
            "durum": r.durum,
        }
        if detay:
            b = belgeler.get(r.kayit_id) if r.kaynak == "BELGE" else None
            d["belge_no"] = b.belge_no if b is not None else None
            d["aciklama"] = b.aciklama if b is not None else None
        cikti.append(d)
    return cikti


def _matris_satiri(r) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "ad": r.ad,
        "competency_id": r.competency_id,
        "kod": r.kod,
        "yetkinlik": r.yetkinlik,
        "kritik": r.is_critical,
        "birim": r.birim,
        "mevcut_seviye": r.mevcut_seviye,
        "hedef_seviye": r.hedef_seviye,
        "hedef_alti": r.mevcut_seviye < r.hedef_seviye,
        "degerlendirme_tarihi": r.degerlendirme_tarihi,
        "sonraki_degerlendirme": r.sonraki_degerlendirme,
        "kaynak": r.kaynak,
    }


async def _oturum_ciktisi(db, o: TrainingSession) -> OturumOut:
    from sqlalchemy import func

    kurs = await db.get(TrainingCourse, o.course_id)
    adet = await db.scalar(
        select(func.count())
        .select_from(TrainingAttendance)
        .where(TrainingAttendance.session_id == o.id, TrainingAttendance.katildi.is_(True))
    )
    return OturumOut(
        id=o.id,
        course_id=o.course_id,
        kurs=kurs.baslik if kurs is not None else None,
        oturum_tarihi=o.oturum_tarihi,
        egitmen_ad=o.egitmen_ad,
        egitmen_user_id=o.egitmen_user_id,
        sure_saat=o.sure_saat,
        yer=o.yer,
        notlar=o.notlar,
        katilimci=int(adet or 0),
        version=o.version,
    )


# --- Yönetim özeti (TS-153) -------------------------------------------------------------


@router.get("/ozet", response_model=None)
async def ozet(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    yil: Annotated[int | None, Query(ge=2020, le=2100)] = None,
    birim: str | None = None,
) -> dict:
    """Tıklanabilir KPI kutuları (sayı = listenin `X-Toplam-Kayit`'ı), yıllık
    gerçekleşme, gözlem başarı oranı (ortalama ikincil), birim ilerlemesi."""
    try:
        return await rapor.ozet(
            db, user, clock, yil=yil or yerel_bugun(clock).year, birim=birim or None
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc


@router.get("/kpi-tanimlari", response_model=None)
async def kpi_tanimlari(user: Okuyucu) -> list[dict]:
    return [
        {"kod": t.kod, "baslik": t.baslik, "tanim": t.tanim, "sekme": t.sekme}
        for t in rapor.KPI_TANIMLARI.values()
    ]


# --- Katalog (TS-150 / TS-152) ------------------------------------------------------------


@router.get("/kurslar", response_model=list[KursOut])
async def kurslar(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    aktif: bool | None = None,
    kategori: str | None = None,
    birim: str | None = None,
    q: str | None = None,
    limit: Limit = 200,
    offset: Offset = 0,
) -> list[KursOut]:
    """Katalog. Pasif kurs plan/oturum seçiminde `aktif=true` ile süzülür."""
    stmt = (
        select(TrainingCourse)
        .where(TrainingCourse.is_deleted.is_(False))
        .order_by(TrainingCourse.kod)
    )
    if aktif is not None:
        stmt = stmt.where(TrainingCourse.is_active.is_(aktif))
    if kategori:
        stmt = stmt.where(TrainingCourse.kategori == kategori)
    if birim:
        stmt = stmt.where(TrainingCourse.birim == birim)
    if q:
        desen = f"%{q.strip()}%"
        stmt = stmt.where(TrainingCourse.baslik.ilike(desen) | TrainingCourse.kod.ilike(desen))
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [KursOut.model_validate(r[0]) for r in satirlar]


@router.post("/kurslar", response_model=KursOut, status_code=status.HTTP_201_CREATED)
async def kurs_olustur(payload: KursIn, request: Request, db: DbDep, user: Yazici) -> KursOut:
    try:
        kurs = await svc.kurs_olustur(db, payload.model_dump(), user=user, ip=client_ip(request))
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(kurs)
    return KursOut.model_validate(kurs)


@router.patch("/kurslar", response_model=KursOut)
async def kurs_guncelle(payload: KursPatch, request: Request, db: DbDep, user: Yazici) -> KursOut:
    """Kurs düzenleme/pasifleme (kimlik gövdede; katalog gizli değildir)."""
    try:
        kurs = await svc.kurs_getir(db, payload.id)
        svc.kurs_birimi_dogrula(user, kurs.birim)
        _surum(kurs, payload.version)
        await svc.kurs_guncelle(
            db,
            kurs,
            payload.model_dump(exclude_unset=True, exclude={"id", "version"}),
            user=user,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(kurs)
    return KursOut.model_validate(kurs)


@router.get("/kriterler", response_model=list[KriterOut])
async def kriterler(db: DbDep, user: Okuyucu, kurs_id: int) -> list[KriterOut]:
    """Kursun gözlem maddeleri (pasifler dahil; formda yalnız aktifler seçilir)."""
    return [KriterOut.model_validate(k) for k in await gozlem_svc.kurs_kriterleri(db, kurs_id)]


@router.post("/kriterler", response_model=KriterOut, status_code=status.HTTP_201_CREATED)
async def kriter_ekle(payload: KriterIn, request: Request, db: DbDep, user: Yazici) -> KriterOut:
    try:
        kurs = await svc.kurs_getir(db, payload.kurs_id)
        kriter = await svc.kriter_ekle(
            db,
            kurs,
            metin=payload.metin,
            is_critical=payload.is_critical,
            user=user,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(kriter)
    return KriterOut.model_validate(kriter)


@router.patch("/kriterler", response_model=KriterOut)
async def kriter_guncelle(
    payload: KriterPatch, request: Request, db: DbDep, user: Yazici
) -> KriterOut:
    """Silme ucu YOK; puanlanmış madde pasife alınır, eski gözlemin puanı değişmez."""
    kriter = await db.get(TrainingCriterion, payload.id)
    if kriter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gözlem maddesi bulunamadı")
    try:
        kurs = await svc.kurs_getir(db, kriter.course_id)
        svc.kurs_birimi_dogrula(user, kurs.birim)
        _surum(kriter, payload.version)
        await svc.kriter_guncelle(
            db,
            kriter,
            payload.model_dump(exclude_unset=True, exclude={"id", "version"}),
            user=user,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(kriter)
    return KriterOut.model_validate(kriter)


# --- Yıllık plan (TS-150 / TS-152) ----------------------------------------------------------


def _plan_suzgeci(yil, birim, kurs_id, durum, kisi_id, q, geciken, vade_gun) -> rapor.PlanSuzgeci:
    return rapor.PlanSuzgeci(
        yil=yil,
        birim=birim or None,
        kurs_id=kurs_id,
        durum=durum or None,
        kisi_id=kisi_id,
        q=q or None,
        geciken=geciken,
        vade_gun=vade_gun,
    )


async def _plan_stmt(db, user, clock, s: rapor.PlanSuzgeci, kpi: str | None):
    if kpi:
        tanim = rapor.KPI_TANIMLARI.get(kpi)
        if tanim is None or tanim.liste != "planlar":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {kpi}")
        return await rapor.kpi_sorgusu(db, user, kpi, clock, yil=s.yil, birim=s.birim)
    return rapor.plan_sorgusu(user, s, bugun=yerel_bugun(clock))


@router.get("/planlar", response_model=None)
async def planlar(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    yil: Annotated[int | None, Query(ge=2020, le=2100)] = None,
    birim: str | None = None,
    kurs_id: int | None = None,
    durum: str | None = None,
    kisi_id: int | None = None,
    q: str | None = None,
    geciken: bool = False,
    vade: bool = False,
    kpi: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict]:
    """Yıllık plan listesi (kapsamlı). `kpi=` ile KPI kutusunun AYNI süzgeci;
    `vade=1` uyarı merkezinin "hedefi yaklaşan/geçen" süzgeci."""
    from app.services import settings as ayar_svc

    vade_gun = int(await ayar_svc.get(db, "egitim_plan_uyari_gun")) if vade else None
    try:
        stmt = await _plan_stmt(
            db,
            user,
            clock,
            _plan_suzgeci(yil, birim, kurs_id, durum, kisi_id, q, geciken, vade_gun),
            kpi,
        )
        satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    bugun = yerel_bugun(clock)
    return [_plan_satiri(r[0], r.ad, r.kurs_kod, r.kurs, bugun) for r in satirlar]


_PLAN_EXCEL_SUTUNLARI = [
    export_svc.Sutun("Personel"),
    export_svc.Sutun("Eğitim"),
    export_svc.Sutun("Yıl", "tamsayi"),
    export_svc.Sutun("Hedef Tarih", "tarih"),
    export_svc.Sutun("Durum"),
    export_svc.Sutun("Tamamlanma", "tarih"),
    export_svc.Sutun("Son Sınav", "tamsayi"),
]
EXCEL_UST_SINIR = 20_000


@router.get("/plan.xlsx")
async def plan_xlsx(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Aktarici,
    yil: Annotated[int | None, Query(ge=2020, le=2100)] = None,
    birim: str | None = None,
    kurs_id: int | None = None,
    durum: str | None = None,
    kisi_id: int | None = None,
    q: str | None = None,
    geciken: bool = False,
    kpi: str | None = None,
) -> Response:
    """Ekrandaki süzgecin AYNI satırları (kapsam dışı personel YOK); denetime
    kişisel veri olarak yazılır (E08-D04)."""
    try:
        stmt = await _plan_stmt(
            db,
            user,
            clock,
            _plan_suzgeci(yil, birim, kurs_id, durum, kisi_id, q, geciken, None),
            kpi,
        )
        toplam = await rapor.say(db, stmt)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    if toplam > EXCEL_UST_SINIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{toplam} satır var; Excel en çok {EXCEL_UST_SINIR} satır alır. Süzgeci daraltın.",
        )
    satirlar = (await db.execute(stmt)).all()
    oturumlar = {r[0].completed_session_id for r in satirlar if r[0].completed_session_id}
    puanlar: dict[tuple[int, int], int | None] = {}
    if oturumlar:
        for a in (
            await db.scalars(
                select(TrainingAttendance).where(TrainingAttendance.session_id.in_(oturumlar))
            )
        ).all():
            puanlar[(a.session_id, a.user_id)] = a.son_puan
    tablo = [
        [
            r.ad,
            r.kurs,
            r[0].plan_yili,
            r[0].hedef_tarih,
            r[0].status.replace("_", " "),
            r[0].completed_on,
            puanlar.get((r[0].completed_session_id, r[0].user_id))
            if r[0].completed_session_id
            else None,
        ]
        for r in satirlar
    ]
    await audit.log(
        db,
        "training_plans",
        "disaaktar",
        new_value={
            "filtre": {
                k: v
                for k, v in {
                    "yil": yil,
                    "birim": birim,
                    "kurs_id": kurs_id,
                    "durum": durum,
                    "kisi_id": kisi_id,
                    "kpi": kpi,
                }.items()
                if v not in (None, "")
            },
            "satir": len(tablo),
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    icerik = await export_svc.sayfalari_xlsx_async(
        [export_svc.Sayfa("Plan", list(_PLAN_EXCEL_SUTUNLARI), tablo)]
    )
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="egitim-plan.xlsx"'},
    )


@router.post("/planlar/toplu", response_model=None)
async def toplu_plan(
    payload: TopluPlanIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict:
    """Toplu yıllık plan; mevcut kişi+kurs+yıl atlanır (`olusan/atlanan`)."""
    try:
        sonuc = await svc.toplu_plan(
            db,
            svc.TopluPlanGirdisi(**payload.model_dump()),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return sonuc


async def _plan_ciktisi(db, p: TrainingPlan, clock) -> dict:
    kisi = await db.get(User, p.user_id)
    kurs = await db.get(TrainingCourse, p.course_id)
    return _plan_satiri(p, kisi.full_name, kurs.kod, kurs.baslik, yerel_bugun(clock))


@router.post("/kisiler/{personel_id}/planlar/{plan_id}/ertele", response_model=None)
async def plan_ertele(
    personel_id: int,
    plan_id: int,
    payload: ErteleIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict:
    try:
        plan = await svc.plan_getir(db, user, personel_id, plan_id)
        _surum(plan, payload.version)
        await svc.plan_ertele(
            db,
            plan,
            yeni_tarih=payload.yeni_tarih,
            gerekce=payload.gerekce,
            user=user,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(plan)
    return await _plan_ciktisi(db, plan, clock)


@router.post("/kisiler/{personel_id}/planlar/{plan_id}/iptal", response_model=None)
async def plan_iptal(
    personel_id: int,
    plan_id: int,
    payload: GerekceIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict:
    try:
        plan = await svc.plan_getir(db, user, personel_id, plan_id)
        _surum(plan, payload.version)
        await svc.plan_iptal(db, plan, gerekce=payload.gerekce, user=user, ip=client_ip(request))
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(plan)
    return await _plan_ciktisi(db, plan, clock)


# --- Oturum ve katılım (TS-150 / TS-151 / TS-158) -----------------------------------------


@router.get("/oturumlar", response_model=list[OturumOut])
async def oturumlar(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    yil: Annotated[int | None, Query(ge=2020, le=2100)] = None,
    kurs_id: int | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[OturumOut]:
    stmt = (
        select(TrainingSession)
        .where(TrainingSession.is_deleted.is_(False))
        .order_by(TrainingSession.oturum_tarihi.desc())
    )
    if yil is not None:
        stmt = stmt.where(
            TrainingSession.oturum_tarihi >= date(yil, 1, 1),
            TrainingSession.oturum_tarihi < date(yil + 1, 1, 1),
        )
    if kurs_id is not None:
        stmt = stmt.where(TrainingSession.course_id == kurs_id)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [await _oturum_ciktisi(db, r[0]) for r in satirlar]


@router.post("/oturumlar", response_model=OturumOut, status_code=status.HTTP_201_CREATED)
async def oturum_olustur(
    payload: OturumIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> OturumOut:
    """İleri tarihli oturum 400; pasif kurs 400; başka birimin kursu 403."""
    try:
        o = await svc.oturum_olustur(
            db, payload.model_dump(), user=user, clock=clock, ip=client_ip(request)
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(o)
    return await _oturum_ciktisi(db, o)


@router.patch("/oturumlar", response_model=OturumOut)
async def oturum_guncelle(
    payload: OturumPatch, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> OturumOut:
    """Tarih düzeltmesi bağlı planların tamamlanma tarihini de düzeltir;
    katılımlı oturumda yıl değişikliği 409."""
    try:
        o = await svc.oturum_getir(db, user, payload.id)
        _surum(o, payload.version)
        await svc.oturum_guncelle(
            db,
            o,
            payload.model_dump(exclude_unset=True, exclude={"id", "version"}),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(o)
    return await _oturum_ciktisi(db, o)


@router.post("/oturumlar/sil", status_code=status.HTTP_204_NO_CONTENT)
async def oturum_sil(
    payload: OturumSilIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> None:
    """Katılımsız oturum yumuşak silinir; katılımlı oturum 409."""
    try:
        o = await svc.oturum_getir(db, user, payload.id)
        _surum(o, payload.version)
        await svc.oturum_sil(db, o, user=user, clock=clock, ip=client_ip(request))
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()


@router.get("/oturumlar/katilimcilar", response_model=None)
async def katilimcilar(db: DbDep, user: Okuyucu, oturum_id: int) -> list[dict]:
    """Toplu katılım tablosu: kursun o yıl açık planı olan kapsamdaki kişiler
    önce gelir; mevcut katılım satırları da listelenir."""
    o = await db.get(TrainingSession, oturum_id)
    if o is None or o.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Oturum bulunamadı")
    return await svc.aday_katilimcilar(db, o, user)


@router.post("/oturumlar/katilim", response_model=None)
async def katilim(
    payload: KatilimIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict:
    """Tek kişilik katılım (toplu uçla AYNI kural: `katilim_isle`)."""
    try:
        o = await svc.oturum_getir(db, user, payload.oturum_id)
        k = await svc.katilim_isle(
            db,
            o,
            svc.KatilimSatiri(**payload.model_dump(exclude={"oturum_id"})),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"id": k.id, "user_id": k.user_id, "katildi": k.katildi, "version": k.version}


@router.put("/oturumlar/katilim/toplu", response_model=None)
async def toplu_katilim(
    payload: TopluKatilimIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict:
    """Toplu katılım; ilk hatada 400 `{satir, mesaj}` ve HİÇBİR satır yazılmaz
    (commit edilmez). Şema hatası (puan 120) 422 + `loc` satır indeksi."""
    try:
        o = await svc.oturum_getir(db, user, payload.oturum_id)
        kayitlar = await svc.katilim_kaydet(
            db,
            o,
            [svc.KatilimSatiri(**s.model_dump()) for s in payload.satirlar],
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        await db.rollback()
        raise _hata(exc) from exc
    await db.commit()
    return {"yazilan": len(kayitlar)}


# --- Saha gözlemi (TS-151 / TS-152 / TS-155 / TS-156) --------------------------------------


@router.get("/gozlemler", response_model=None)
async def gozlemler(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    yil: Annotated[int | None, Query(ge=2020, le=2100)] = None,
    birim: str | None = None,
    kisi_id: int | None = None,
    kurs_id: int | None = None,
    asama: int | None = None,
    sonuc: str | None = None,
    service_order_id: int | None = None,
    iptaller: bool = False,
    kpi: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict]:
    """Gözlem listesi. Yıl verilmezse (servis işi ya da kişi süzgeci yoksa)
    bu yıl ± 1 ile sınırlıdır (M08-16 özü). Detay alanları yalnız `egitim.detay`."""
    try:
        if kpi:
            tanim = rapor.KPI_TANIMLARI.get(kpi)
            if tanim is None or tanim.liste != "gozlemler":
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {kpi}"
                )
            stmt = await rapor.kpi_sorgusu(db, user, kpi, clock, yil=yil, birim=birim or None)
        else:
            stmt = rapor.gozlem_sorgusu(
                user,
                rapor.GozlemSuzgeci(
                    yil=yil,
                    birim=birim or None,
                    kisi_id=kisi_id,
                    kurs_id=kurs_id,
                    asama=asama,
                    sonuc=sonuc or None,
                    service_order_id=service_order_id,
                    iptaller_dahil=iptaller,
                ),
            )
            if yil is None and service_order_id is None and kisi_id is None:
                bu_yil = yerel_bugun(clock).year
                stmt = stmt.where(
                    TrainingObservation.gozlem_tarihi >= date(bu_yil - 1, 1, 1),
                    TrainingObservation.gozlem_tarihi < date(bu_yil + 2, 1, 1),
                )
        satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    return await _gozlem_ciktilari(db, [(r[0], r.ad, r.kurs) for r in satirlar], detay=_detay(user))


@router.post("/gozlemler", response_model=None, status_code=status.HTTP_201_CREATED)
async def gozlem_kaydet(
    payload: GozlemIn, request: Request, db: DbDep, clock: ClockDep, user: Gozlemci
) -> dict:
    """Sonuç ve puan SUNUCUDA hesaplanır; gözlemci oturumdaki kullanıcıdır.
    Kritik maddede 0 → düzeltici faaliyet aynı transaction'da açılır."""
    try:
        g, uyarilar, faaliyet = await gozlem_svc.gozlem_kaydet(
            db,
            gozlem_svc.GozlemGirdisi(
                **payload.model_dump(exclude={"puanlar"}),
                puanlar=[gozlem_svc.MaddePuani(**p.model_dump()) for p in payload.puanlar],
            ),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(g)
    kisi = await db.get(User, g.user_id)
    kurs = await db.get(TrainingCourse, g.course_id)
    cikti = await _gozlem_ciktilari(db, [(g, kisi.full_name, kurs.baslik)], detay=_detay(user))
    return {
        "gozlem": cikti[0],
        "uyarilar": uyarilar,
        "faaliyet_id": faaliyet.id if faaliyet is not None else None,
    }


@router.get("/kisiler/{personel_id}/gozlemler/{gozlem_id}", response_model=None)
async def gozlem_getir(personel_id: int, gozlem_id: int, db: DbDep, user: Okuyucu) -> dict:
    try:
        g = await gozlem_svc.gozlem_getir(db, user, personel_id, gozlem_id)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    kisi = await db.get(User, g.user_id)
    kurs = await db.get(TrainingCourse, g.course_id)
    return (await _gozlem_ciktilari(db, [(g, kisi.full_name, kurs.baslik)], detay=_detay(user)))[0]


@router.post("/kisiler/{personel_id}/gozlemler/{gozlem_id}/iptal", response_model=None)
async def gozlem_iptal(
    personel_id: int,
    gozlem_id: int,
    payload: GerekceIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: GozlemIptalci,
) -> dict:
    """Gözlemci kendi gözlemini (`egitim.gozlem`), diğerleri `egitim.yaz` ile."""
    try:
        g = await gozlem_svc.gozlem_getir(db, user, personel_id, gozlem_id)
        _surum(g, payload.version)
        await gozlem_svc.gozlem_iptal(
            db, g, gerekce=payload.gerekce, user=user, clock=clock, ip=client_ip(request)
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(g)
    kisi = await db.get(User, g.user_id)
    kurs = await db.get(TrainingCourse, g.course_id)
    return (await _gozlem_ciktilari(db, [(g, kisi.full_name, kurs.baslik)], detay=_detay(user)))[0]


# --- 30/60/90 takip (TS-159) -----------------------------------------------------------


@router.get("/takipler", response_model=None)
async def takipler(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    vadesi_gelen: bool = False,
    birim: str | None = None,
    kisi_id: int | None = None,
    kpi: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict]:
    """Takip listesi; uyarı `egitim.takip` = `vadesi_gelen=1` listesinin toplamı."""
    from app.services import settings as ayar_svc

    try:
        if kpi:
            tanim = rapor.KPI_TANIMLARI.get(kpi)
            if tanim is None or tanim.liste != "takipler":
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {kpi}"
                )
            stmt = await rapor.kpi_sorgusu(db, user, kpi, clock, birim=birim or None)
        else:
            durumlar = rapor.TAKIP_DURUMLARI
            if vadesi_gelen:
                durumlar = ("GECIKTI", "ZAMANI_GELDI")
            elif durum:
                if durum not in rapor.TAKIP_DURUMLARI:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen durum: {durum}")
                durumlar = (durum,)
            stmt = rapor.takip_sorgusu(
                user,
                clock,
                pencere_gun=int(await ayar_svc.get(db, "egitim_takip_pencere_gun")),
                durumlar=durumlar,
                birim=birim or None,
                kisi_id=kisi_id,
            )
        satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    return [dict(r._mapping) for r in satirlar]


# --- Düzeltici faaliyet (TS-155) --------------------------------------------------------


@router.get("/duzeltici-faaliyetler", response_model=None)
async def faaliyetler(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    gecikmis: bool = False,
    birim: str | None = None,
    kisi_id: int | None = None,
    kpi: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict]:
    bugun = yerel_bugun(clock)
    try:
        if kpi:
            tanim = rapor.KPI_TANIMLARI.get(kpi)
            if tanim is None or tanim.liste != "faaliyetler":
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {kpi}"
                )
            stmt = await rapor.kpi_sorgusu(db, user, kpi, clock, birim=birim or None)
        else:
            stmt = rapor.faaliyet_sorgusu(
                user,
                rapor.FaaliyetSuzgeci(
                    durum=durum or None, gecikmis=gecikmis, birim=birim or None, kisi_id=kisi_id
                ),
                bugun=bugun,
            )
        satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    detay = _detay(user)
    return [
        _faaliyet_satiri(r[0], r.ad, r.kurs, r.gozlem_tarihi, r.gozlem_iptal_at, bugun, detay=detay)
        for r in satirlar
    ]


@router.post(
    "/kisiler/{personel_id}/duzeltici-faaliyetler/{faaliyet_id}/kapat", response_model=None
)
async def faaliyet_kapat(
    personel_id: int,
    faaliyet_id: int,
    payload: KanitIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict:
    """Manuel kapanış: `egitim.yaz` + kanıt (boş → 400). Gözlemci (şef)
    `egitim.yaz` taşımadığı için kendi faaliyetini elle kapatamaz; yalnız yeni
    gözlemle otomatik kapanır (K10, bilinçli)."""
    try:
        f = await gozlem_svc.faaliyet_getir(db, user, personel_id, faaliyet_id)
        _surum(f, payload.version)
        await gozlem_svc.faaliyet_kapat(
            db, f, kanit=payload.kanit, user=user, clock=clock, ip=client_ip(request)
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(f)
    g = await db.get(TrainingObservation, f.observation_id)
    kisi = await db.get(User, f.user_id)
    kurs = await db.get(TrainingCourse, f.course_id)
    return _faaliyet_satiri(
        f,
        kisi.full_name,
        kurs.baslik,
        g.gozlem_tarihi,
        g.cancelled_at,
        yerel_bugun(clock),
        detay=_detay(user),
    )


# --- Geçerlilik ve belgeler (TS-159) -------------------------------------------------------


@router.get("/belgeler", response_model=None)
async def belgeler(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    birim: str | None = None,
    kisi_id: int | None = None,
    kpi: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict]:
    """Eğitim (yenileme periyotlu) ve belge geçerliliği — uyarı ve KPI ile aynı sorgu.

    `durum`: DOLDU | DOLACAK | GECERLI (pencere `egitim_belge_uyari_gun`)."""
    from app.services import settings as ayar_svc

    try:
        if kpi:
            tanim = rapor.KPI_TANIMLARI.get(kpi)
            if tanim is None or tanim.liste != "belgeler":
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {kpi}"
                )
            stmt = await rapor.kpi_sorgusu(db, user, kpi, clock, birim=birim or None)
        else:
            stmt = rapor.gecerlilik_sorgusu(
                user,
                clock,
                pencere_gun=int(await ayar_svc.get(db, "egitim_belge_uyari_gun")),
                durum=durum or None,
                birim=birim or None,
                kisi_id=kisi_id,
            )
        satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    return await _gecerlilik_ciktilari(db, satirlar, detay=_detay(user))


@router.post("/belgeler", response_model=None, status_code=status.HTTP_201_CREATED)
async def belge_olustur(payload: BelgeIn, request: Request, db: DbDep, user: Yazici) -> dict:
    try:
        b = await svc.belge_olustur(db, payload.model_dump(), user=user, ip=client_ip(request))
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(b)
    return {"id": b.id, "user_id": b.user_id, "belge_adi": b.belge_adi, "version": b.version}


@router.post("/kisiler/{personel_id}/belgeler/{belge_id}/iptal", response_model=None)
async def belge_iptal(
    personel_id: int,
    belge_id: int,
    payload: GerekceIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict:
    try:
        b = await svc.belge_getir(db, user, personel_id, belge_id)
        _surum(b, payload.version)
        await svc.belge_iptal(
            db, b, gerekce=payload.gerekce, user=user, clock=clock, ip=client_ip(request)
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"id": b.id, "iptal": True}


# --- Yetkinlik (TS-150 / TS-160) -------------------------------------------------------------


@router.get("/yetkinlikler", response_model=list[YetkinlikOut])
async def yetkinlikler(db: DbDep, user: Okuyucu, aktif: bool | None = None) -> list[YetkinlikOut]:
    stmt = select(Competency).where(Competency.is_deleted.is_(False)).order_by(Competency.kod)
    if aktif is not None:
        stmt = stmt.where(Competency.is_active.is_(aktif))
    return [YetkinlikOut.model_validate(y) for y in (await db.scalars(stmt)).all()]


@router.post("/yetkinlikler", response_model=YetkinlikOut, status_code=status.HTTP_201_CREATED)
async def yetkinlik_olustur(
    payload: YetkinlikIn, request: Request, db: DbDep, user: Yazici
) -> YetkinlikOut:
    """Başka birimin yetkinliği 403 (yalnız TUMU dışı istisnalı yazıcıda oluşur)."""
    try:
        y = await yetkinlik_svc.yetkinlik_olustur(
            db, payload.model_dump(), user=user, ip=client_ip(request)
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(y)
    return YetkinlikOut.model_validate(y)


@router.patch("/yetkinlikler", response_model=YetkinlikOut)
async def yetkinlik_guncelle(
    payload: YetkinlikPatch, request: Request, db: DbDep, user: Yazici
) -> YetkinlikOut:
    try:
        y = await yetkinlik_svc.yetkinlik_getir(db, payload.id)
        svc.kurs_birimi_dogrula(user, y.birim)
        _surum(y, payload.version)
        await yetkinlik_svc.yetkinlik_guncelle(
            db,
            y,
            payload.model_dump(exclude_unset=True, exclude={"id", "version"}),
            user=user,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(y)
    return YetkinlikOut.model_validate(y)


@router.get("/yetkinlik-matrisi", response_model=None)
async def yetkinlik_matrisi(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    birim: str | None = None,
    kisi_id: int | None = None,
    competency_id: int | None = None,
    hedef_alti: bool = False,
    kpi: str | None = None,
    limit: Limit = 200,
    offset: Offset = 0,
) -> list[dict]:
    """Güncel seviyeler (DISTINCT ON); sıralama açıkça tekil."""
    try:
        if kpi:
            tanim = rapor.KPI_TANIMLARI.get(kpi)
            if tanim is None or tanim.liste != "matris":
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {kpi}"
                )
            stmt = await rapor.kpi_sorgusu(db, user, kpi, clock, birim=birim or None)
        else:
            stmt = yetkinlik_svc.matris_sorgusu(
                user,
                birim=birim or None,
                kisi_id=kisi_id,
                competency_id=competency_id,
                hedef_alti=hedef_alti,
            )
        satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    return [_matris_satiri(r) for r in satirlar]


@router.post("/yetkinlik-degerlendirmeleri", response_model=None, status_code=201)
async def degerlendirme_ekle(
    payload: DegerlendirmeIn, request: Request, db: DbDep, clock: ClockDep, user: Gozlemci
) -> dict:
    """Yalnız ekleme; değerlendiren sunucuda (`user`). Öz-değerlendirme 409."""
    try:
        kayit, uyarilar = await yetkinlik_svc.degerlendirme_ekle(
            db,
            yetkinlik_svc.DegerlendirmeGirdisi(**payload.model_dump()),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {
        "id": kayit.id,
        "user_id": kayit.user_id,
        "competency_id": kayit.competency_id,
        "mevcut_seviye": kayit.mevcut_seviye,
        "hedef_seviye": kayit.hedef_seviye,
        "degerlendirme_tarihi": kayit.degerlendirme_tarihi,
        "assessed_by_user_id": kayit.assessed_by_user_id,
        "uyarilar": uyarilar,
    }


def _gecmis_satiri(a, c, *, detay: bool) -> dict:
    d = {
        "id": a.id,
        "competency_id": c.id,
        "kod": c.kod,
        "yetkinlik": c.ad,
        "kritik": c.is_critical,
        "mevcut_seviye": a.mevcut_seviye,
        "hedef_seviye": a.hedef_seviye,
        "degerlendirme_tarihi": a.degerlendirme_tarihi,
        "assessed_by_user_id": a.assessed_by_user_id,
        "assessed_by_ad": a.assessed_by_ad,
        "kaynak": a.kaynak,
        "observation_id": a.observation_id,
        "sonraki_degerlendirme": a.sonraki_degerlendirme,
    }
    if detay:
        d["kanit"] = a.kanit
    return d


@router.get("/kisiler/{personel_id}/yetkinlik-gecmisi", response_model=None)
async def yetkinlik_gecmisi(personel_id: int, db: DbDep, user: Okuyucu) -> list[dict]:
    try:
        await svc.kisi_getir(db, user, personel_id)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    detay = _detay(user)
    return [
        _gecmis_satiri(a, c, detay=detay) for a, c in await yetkinlik_svc.gecmis(db, personel_id)
    ]


# --- Kişiler ve kişi kartı (TS-150 / TS-154) --------------------------------------------------


@router.get("/kisiler", response_model=None)
async def kisiler(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    q: str | None = None,
    birim: str | None = None,
    ayrilanlar: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict]:
    """Kapsamlı personel listesi (E13 `personel_sorgusu`; birimsiz personel
    yalnız TUMU'ya görünür)."""
    try:
        stmt = personel_svc.personel_sorgusu(
            user, q=q or None, birim=birim or None, durum=None if ayrilanlar else "CALISIYOR"
        )
    except personel_svc.PersonelGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [
        {
            "id": k.id,
            "ad": k.full_name,
            "unvan": k.unvan,
            "saha_rolu": k.saha_rolu,
            "birimler": k.birim_kodlari,
            "birincil_birim": k.birincil_birim,
            "calisiyor": k.is_active and k.ayrilis_tarihi is None,
            "giris_acik": k.giris_acik,
        }
        for (k,) in satirlar
    ]


async def _kart(db, kisi: User, clock, *, detay: bool, kendi: bool = False) -> dict:
    """Kişi kartı (yönetici görünümü ya da Gelişim Kartım)."""
    bugun = yerel_bugun(clock)
    planlar = (
        await db.execute(
            select(TrainingPlan, TrainingCourse.kod, TrainingCourse.baslik)
            .join(TrainingCourse, TrainingCourse.id == TrainingPlan.course_id)
            .where(TrainingPlan.user_id == kisi.id, TrainingPlan.is_deleted.is_(False))
            .order_by(TrainingPlan.plan_yili.desc(), TrainingPlan.hedef_tarih, TrainingPlan.id)
        )
    ).all()
    katilimlar = (
        await db.execute(
            select(TrainingAttendance, TrainingSession, TrainingCourse.baslik)
            .join(TrainingSession, TrainingSession.id == TrainingAttendance.session_id)
            .join(TrainingCourse, TrainingCourse.id == TrainingSession.course_id)
            .where(TrainingAttendance.user_id == kisi.id, TrainingSession.is_deleted.is_(False))
            .order_by(TrainingSession.oturum_tarihi.desc(), TrainingSession.id.desc())
        )
    ).all()
    gozlemler = (
        await db.execute(
            select(TrainingObservation, TrainingCourse.baslik)
            .join(TrainingCourse, TrainingCourse.id == TrainingObservation.course_id)
            .where(
                TrainingObservation.user_id == kisi.id, TrainingObservation.is_deleted.is_(False)
            )
            .order_by(TrainingObservation.gozlem_tarihi.desc(), TrainingObservation.id.desc())
        )
    ).all()
    faaliyetler = (
        await db.execute(
            select(
                TrainingCorrectiveAction,
                TrainingCourse.baslik,
                TrainingObservation.gozlem_tarihi,
                TrainingObservation.cancelled_at,
            )
            .join(TrainingCourse, TrainingCourse.id == TrainingCorrectiveAction.course_id)
            .join(
                TrainingObservation,
                TrainingObservation.id == TrainingCorrectiveAction.observation_id,
            )
            .where(TrainingCorrectiveAction.user_id == kisi.id)
            .order_by(TrainingCorrectiveAction.termin.desc(), TrainingCorrectiveAction.id.desc())
        )
    ).all()
    from app.services import settings as ayar_svc

    pencere = int(await ayar_svc.get(db, "egitim_belge_uyari_gun"))
    gecerlilik = (await db.execute(_gecerlilik_kisi(kisi, clock, pencere))).all()
    belgeler = (
        await db.scalars(
            select(PersonnelCertificate)
            .where(PersonnelCertificate.user_id == kisi.id)
            .order_by(PersonnelCertificate.verilis_tarihi.desc(), PersonnelCertificate.id.desc())
        )
    ).all()
    seviyeler = await yetkinlik_svc.guncel_seviyeler(db, [kisi.id])
    yetkinlikler = (
        {
            y.id: y
            for y in (
                await db.scalars(
                    select(Competency).where(
                        Competency.id.in_([s.competency_id for s in seviyeler])
                    )
                )
            ).all()
        }
        if seviyeler
        else {}
    )
    return {
        "kisi": {
            "id": kisi.id,
            "ad": kisi.full_name,
            "unvan": kisi.unvan,
            "saha_rolu": kisi.saha_rolu,
            "birimler": kisi.birim_kodlari,
            "birincil_birim": kisi.birincil_birim,
            "calisiyor": kisi.is_active and kisi.ayrilis_tarihi is None,
        },
        "kendi": kendi,
        "planlar": [_plan_satiri(p, kisi.full_name, kod, ad, bugun) for p, kod, ad in planlar],
        "katilimlar": [
            {
                "id": a.id,
                "session_id": o.id,
                "kurs": kurs,
                "oturum_tarihi": o.oturum_tarihi,
                "katildi": a.katildi,
                "on_puan": a.on_puan,
                "son_puan": a.son_puan,
            }
            for a, o, kurs in katilimlar
        ],
        "gozlemler": await _gozlem_ciktilari(
            db, [(g, kisi.full_name, kurs) for g, kurs in gozlemler], detay=detay
        ),
        "faaliyetler": [
            _faaliyet_satiri(f, kisi.full_name, kurs, gt, iptal, bugun, detay=detay)
            for f, kurs, gt, iptal in faaliyetler
        ],
        "gecerlilik": [dict(r._mapping) for r in gecerlilik],
        "belgeler": [
            {
                "id": b.id,
                "belge_adi": b.belge_adi,
                "course_id": b.course_id,
                "verilis_tarihi": b.verilis_tarihi,
                "gecerlilik_bitis": b.gecerlilik_bitis,
                "cancelled_at": b.cancelled_at,
                "cancel_reason": b.cancel_reason,
                **({"belge_no": b.belge_no, "aciklama": b.aciklama} if detay else {}),
            }
            for b in belgeler
        ],
        "yetkinlikler": [
            {
                "competency_id": s.competency_id,
                "kod": yetkinlikler[s.competency_id].kod,
                "yetkinlik": yetkinlikler[s.competency_id].ad,
                "kritik": yetkinlikler[s.competency_id].is_critical,
                "mevcut_seviye": s.mevcut_seviye,
                "hedef_seviye": s.hedef_seviye,
                "degerlendirme_tarihi": s.degerlendirme_tarihi,
                "sonraki_degerlendirme": s.sonraki_degerlendirme,
            }
            for s in seviyeler
            if s.competency_id in yetkinlikler
        ],
    }


def _gecerlilik_kisi(kisi: User, clock, pencere: int):
    """Kişinin kendi geçerlilik satırları (kapsam süzgeci olmadan: kart zaten
    kapsam kontrolünden geçti ya da kişinin kendisi)."""
    from types import SimpleNamespace

    from app.permissions import SCOPE_ALL

    tumu = SimpleNamespace(role=SimpleNamespace(scope=SCOPE_ALL), birimler=[])
    return rapor.gecerlilik_sorgusu(tumu, clock, pencere_gun=pencere, kisi_id=kisi.id)  # type: ignore[arg-type]


@router.get("/kisiler/{personel_id}/kart", response_model=None)
async def kisi_karti(
    personel_id: int, request: Request, db: DbDep, clock: ClockDep, user: Okuyucu
) -> dict:
    """Kişi kartı; açılış KVKK erişim loguna yazılır (`entity="users"`)."""
    try:
        kisi = await svc.kisi_getir(db, user, personel_id)
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    kart = await _kart(db, kisi, clock, detay=_detay(user))
    await kvkk.erisim_kaydet(
        db,
        entity="users",
        entity_id=kisi.id,
        amac="egitim.kart",
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return kart


# --- Gelişim Kartım (TS-157) -----------------------------------------------------------------


@router.get("/kendim", response_model=None)
async def kendim(db: DbDep, clock: ClockDep, user: Kendim) -> dict:
    """Yalnız oturumdaki kullanıcının verisi (kişi kimliği parametre ALMAZ).
    Kişi kendi gözleminin notunu, madde puanlarını ve aksiyon planını görür (K12)."""
    kisi = await db.get(User, user.id)
    kart = await _kart(db, kisi, clock, detay=True, kendi=True)
    kart["bos"] = not any(
        kart[k] for k in ("planlar", "katilimlar", "gozlemler", "belgeler", "yetkinlikler")
    )
    return kart


@router.post("/kendim/gordum", response_model=None)
async def gordum(
    payload: GordumIn, request: Request, db: DbDep, clock: ClockDep, user: Kendim
) -> dict:
    """ "Gördüm" onayı: başkasının gözlemi 404, ikinci onay 409 (geri alınamaz)."""
    try:
        g = await gozlem_svc.gordum(
            db,
            payload.gozlem_id,
            yorum=payload.yorum,
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except EgitimHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"id": g.id, "gordu_at": g.gordu_at, "personel_yorumu": g.personel_yorumu}
