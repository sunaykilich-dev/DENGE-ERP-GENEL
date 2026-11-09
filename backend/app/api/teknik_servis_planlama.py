"""Planlama takvimi, havuz, plan/toplu plan/yeniden plan, araç havuzu uçları (TS-040…049).

Kurallar (plan §1.2, §4.5):

- Her uç `require_permission` ile korunur: okuma `servis.gor`, plan yazımı
  (ekip ataması, geri alma, çakışmayı gerekçeyle geçme dahil) `servis.planla`
  (E01 K23: ayrı `servis.ata` izni yok), araç havuzu yazımı `servis.arac_yaz`,
  Excel `servis.gor` + `servis_rapor.disaaktar` (KD-06).
- `{is_id}` uçlarında kapsam dışı iş → 404 ve hiçbir yazma yapılmaz
  (kontrol YAZMADAN önce). Gövdedeki iş kimliği kapsam dışıysa da 404.
- Kural ihlali 409 (gövde `{detail, kod, ...}`), girdi hatası 400, şema dışı
  422 (Pydantic; ör. 151 iş, 10 dk süre).
- Çakışma 409 gövdesi `{detail, kod: 'PLAN_CAKISMA', cakismalar}` —
  `HTTPException(detail=dict)` kullanılmaz, istemci dict `detail`'i okuyamaz.
- Servis yalnız flush eder; commit burada, tek transaction.
- Araç güncellemesinde kimlik GÖVDEDEDİR (`PATCH /araclar`): kapsam taraması
  yol parametrelerini tanınmış adlarla eşler ve `arac_id` o sözleşmede yok
  (talep raporda); kapsam kontrolü yine yazmadan önce yapılır.
"""

from datetime import date, datetime, time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import TOPLAM_BASLIGI, ClockDep, DbDep, client_ip, require_permission
from app.models import ServiceOrder, ServicePlan, ServiceVehicle, User, Vehicle
from app.models.rbac import BIRIM_KODLARI
from app.models.vehicle import plaka_anahtari
from app.services import audit
from app.services import export as export_svc
from app.services.teknik_servis import atama, cakisma, kapsam, planlama, takvim
from app.services.teknik_servis.atama import AtamaKapsamDisi, AtamaSatiri
from app.services.teknik_servis.is_emirleri import IsEmriYetkiHatasi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun

router = APIRouter(prefix="/api/teknik-servis/planlama", tags=["teknik-servis-planlama"])

Okuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
# Ekip yönetimi ekranları (2026-11-09): saha teknisyeninde `takip.gor` yok.
TakipOkuyucu = Annotated[User, Depends(require_permission("servis.gor", "takip.gor"))]
TakipAktarici = Annotated[
    User, Depends(require_permission("servis.gor", "takip.gor", "servis_rapor.disaaktar"))
]
Planlayici = Annotated[User, Depends(require_permission("servis.planla"))]
AracYazici = Annotated[User, Depends(require_permission("servis.arac_yaz"))]
Aktarici = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.disaaktar"))]

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --- Hata eşlemesi -----------------------------------------------------------------


def _hata_yaniti(exc: Exception) -> JSONResponse:
    if isinstance(exc, cakisma.PlanCakismasi):
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=exc.govde())
    if isinstance(exc, planlama.GecmisTarihHatasi):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "kod": "GECMIS_TARIH", "is_nolari": exc.is_nolari},
        )
    if isinstance(exc, planlama.PlanlamaHatasi):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "kod": "PLAN_KURAL", "is_nolari": exc.is_nolari},
        )
    if isinstance(exc, IsEmriYetkiHatasi):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})
    if isinstance(exc, AtamaKapsamDisi):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})
    if isinstance(exc, ServisHatasi):
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})
    if isinstance(exc, ServisGirdiHatasi):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})
    if isinstance(exc, planlama.PlanlamaBulunamadi | takvim.TakvimKapsamDisi):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})
    raise exc  # pragma: no cover


_HATALAR = (
    ServisHatasi,
    ServisGirdiHatasi,
    planlama.PlanlamaBulunamadi,
    takvim.TakvimKapsamDisi,
)


async def _kapsamli_is(db, user: User, is_id: int) -> ServiceOrder:
    """Kapsam dışı ya da yok → 404 (yazmadan ÖNCE)."""
    so = await db.get(ServiceOrder, is_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    return so


def _birim(birim: str | None) -> str | None:
    if birim in (None, ""):
        return None
    if birim not in BIRIM_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {birim}")
    return birim


def _tarih(ham: str | None, alan: str) -> date | None:
    """Boş dize = verilmedi (V1.20 dersi: boş tarih 422 üretmemeli, E02-19)."""
    if ham is None or not ham.strip():
        return None
    try:
        return date.fromisoformat(ham.strip())
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{alan} YYYY-AA-GG biçiminde olmalı"
        ) from None


# --- Şemalar ----------------------------------------------------------------------


class EkipIn(BaseModel):
    """Ekip: şefler (yalnız `sahaya_giden_sefler` sahaya gider ve çakışmaya
    girer), teknisyenler (her zaman sahada), tek sorumlu.

    Sorumlu ekipteki bir teknisyen ya da şef olur (rol testi B1). Verilmezse
    ilk teknisyen; teknisyen yoksa sahaya giden ilk şef (Set Bariyer: şef tek
    başına sahada → iş tayinli ve sorumlulu görünür)."""

    sef_idler: list[int] = Field(default_factory=list, max_length=5)
    sahaya_giden_sefler: list[int] = Field(default_factory=list, max_length=5)
    teknisyen_idler: list[int] = Field(default_factory=list, max_length=30)
    sorumlu_id: int | None = None

    def satirlar(self) -> list[AtamaSatiri]:
        sorumlu = self.sorumlu_id
        if sorumlu is None and self.teknisyen_idler:
            sorumlu = self.teknisyen_idler[0]
        if sorumlu is None:
            sorumlu = next((u for u in self.sahaya_giden_sefler if u in self.sef_idler), None)
        if (
            sorumlu is not None
            and sorumlu not in self.teknisyen_idler
            and sorumlu not in self.sef_idler
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Sorumlu, ekipteki bir teknisyen ya da şef olmalı"
            )
        return [
            AtamaSatiri(user_id=u, rol="SEF", is_lead=(u == sorumlu)) for u in self.sef_idler
        ] + [
            AtamaSatiri(user_id=u, rol="TEKNISYEN", is_lead=(u == sorumlu))
            for u in self.teknisyen_idler
        ]


class PlanIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"plan_tarihi": "2026-01-15", "sure_dk": 60}]}
    )

    plan_tarihi: date
    baslangic_saati: time | None = None
    sure_dk: int = Field(ge=15, le=1440)
    ekip: EkipIn | None = None
    arac_id: int | None = None
    saha_bolgesi: str | None = Field(default=None, max_length=200)
    saha_notu: str | None = Field(default=None, max_length=500)
    plan_notu: str | None = Field(default=None, max_length=1000)
    degisim_nedeni: str | None = Field(default=None, max_length=24)
    degisim_notu: str | None = Field(default=None, max_length=500)
    cakisma_gerekcesi: str | None = Field(default=None, max_length=500)
    # Geçmiş tarihe plan gerekçesi (rol testi B6): yoksa 409 `GECMIS_TARIH`.
    gecmis_tarih_gerekcesi: str | None = Field(default=None, max_length=500)
    # Tekli planda istemcinin gördüğü aktif plan (iyimser kilit); yoksa null.
    beklenen_aktif_plan_id: int | None = None

    def girdi(self) -> planlama.PlanGirdisi:
        return planlama.PlanGirdisi(
            plan_date=self.plan_tarihi,
            duration_min=self.sure_dk,
            start_time=self.baslangic_saati,
            ekip=self.ekip.satirlar() if self.ekip is not None else None,
            sahaya_giden_sefler=(
                list(self.ekip.sahaya_giden_sefler) if self.ekip is not None else None
            ),
            vehicle_id=self.arac_id,
            site_area=self.saha_bolgesi,
            site_note=self.saha_notu,
            plan_note=self.plan_notu,
            change_reason=self.degisim_nedeni or None,
            change_note=self.degisim_notu,
            conflict_override_note=self.cakisma_gerekcesi or None,
            beklenen_aktif_plan_id=self.beklenen_aktif_plan_id,
            gecmis_tarih_gerekcesi=self.gecmis_tarih_gerekcesi or None,
        )


class TopluPlanIn(PlanIn):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "is_idler": [1],
                    "plan_tarihi": "2026-01-15",
                    "sure_dk": 60,
                    "ekip": {"teknisyen_idler": [1]},
                    "degisim_nedeni": "MUSTERI_TALEBI",
                }
            ]
        }
    )

    # 151 → 422 (plan §1.9 `servis_toplu_atama_ust_sinir`; servis ayrıca ayarı uygular).
    is_idler: list[int] = Field(min_length=1, max_length=150)


class GeriAlIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"examples": [{"neden": "MUSTERI_TALEBI"}]},
    )

    neden: str | None = Field(default=None, max_length=24)
    not_: str | None = Field(default=None, alias="not", max_length=500)


class KontrolIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"plan_tarihi": "2026-01-15", "baslangic_saati": "09:00", "sure_dk": 60}]
        }
    )

    plan_tarihi: date
    baslangic_saati: time | None = None
    sure_dk: int = Field(ge=15, le=1440)
    kisi_idler: list[int] = Field(default_factory=list, max_length=40)
    arac_id: int | None = None
    haric_is_idler: list[int] = Field(default_factory=list, max_length=150)
    ziyaret_id: int | None = None


class AracIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"plaka": "34 TST 001"}]})

    plaka: str = Field(min_length=4, max_length=20)
    birim: str | None = Field(default=None, max_length=20)
    zimmetli_id: int | None = None
    mobilite_arac_id: int | None = None
    notlar: str | None = Field(default=None, max_length=1000)


class AracPatch(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"version": 1}]})

    version: int
    plaka: str | None = Field(default=None, min_length=4, max_length=20)
    birim: str | None = Field(default=None, max_length=20)
    ortak_havuz: bool = False  # True → birim NULL (birim alanı yok sayılır)
    zimmetli_id: int | None = None
    zimmet_kaldir: bool = False
    mobilite_arac_id: int | None = None
    notlar: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


# --- Çıktı yardımcıları ------------------------------------------------------------


async def _plan_cikti(db, plan: ServicePlan) -> dict[str, Any]:
    uyeler = (await planlama.plan_uyeleri(db, [plan.id])).get(plan.id, [])
    adlar = dict(
        (
            await db.execute(
                select(User.id, User.full_name).where(User.id.in_([u.user_id for u in uyeler]))
            )
        ).all()
    )
    yapan = await db.get(User, plan.created_by) if plan.created_by else None
    return {
        "id": plan.id,
        "is_id": plan.service_order_id,
        "aktif": plan.is_active,
        "ziyaret_id": plan.visit_id,
        "plan_tarihi": plan.plan_date.isoformat(),
        "baslangic_saati": plan.start_time.strftime("%H:%M") if plan.start_time else None,
        "sure_dk": plan.duration_min,
        "arac_id": plan.vehicle_id,
        "saha_bolgesi": plan.site_area,
        "saha_notu": plan.site_note,
        "plan_notu": plan.plan_note,
        "degisim": plan.change_type,
        "degisim_nedeni": plan.change_reason,
        "degisim_notu": plan.change_note,
        "cakisma_gerekcesi": plan.conflict_override_note,
        "iptal_at": plan.cancelled_at.isoformat() if plan.cancelled_at else None,
        "iptal_nedeni": plan.cancel_reason,
        "iptal_notu": plan.cancel_note,
        "olusturma": plan.created_at.isoformat() if plan.created_at else None,
        "planlayan": yapan.full_name if yapan else None,
        "ekip": [
            {
                "user_id": u.user_id,
                "ad": adlar.get(u.user_id),
                "rol": u.rol,
                "sahaya_gidiyor": u.sahaya_gidiyor,
            }
            for u in uyeler
        ],
    }


async def _arac_cikti(db, arac: ServiceVehicle) -> dict[str, Any]:
    zimmetli = await db.get(User, arac.assigned_user_id) if arac.assigned_user_id else None
    return {
        "id": arac.id,
        "plaka": arac.plate,
        "birim": arac.birim,
        "zimmetli_id": arac.assigned_user_id,
        "zimmetli": zimmetli.full_name if zimmetli else None,
        "mobilite_arac_id": arac.vehicle_id,
        "notlar": arac.notes,
        "is_active": arac.is_active,
        "version": arac.version,
    }


# --- Takvim, havuz, KPI -------------------------------------------------------------


@router.get("/takvim", response_model=None)
async def takvim_getir(
    db: DbDep,
    clock: ClockDep,
    user: TakipOkuyucu,
    baslangic: date,
    bitis: date,
    birim: str | None = None,
    tur: str | None = None,
) -> Any:
    """Aralıktaki (≤62 gün) plan satırları; kart anahtarı ziyaret ya da iş."""
    try:
        return await takvim.takvim(db, user, clock, baslangic, bitis, birim=_birim(birim), tur=tur)
    except _HATALAR as exc:
        return _hata_yaniti(exc)


@router.get("/havuz", response_model=None)
async def havuz(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: TakipOkuyucu,
    gruplama: str = "lokasyon",
    birim: str | None = None,
    tur: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Plansız açık işler (sayfalı, `X-Toplam-Kayit`); grup anahtarı sunucuda."""
    try:
        toplam, satirlar = await takvim.havuz(
            db,
            user,
            clock,
            gruplama=gruplama,
            birim=_birim(birim),
            tur=tur,
            q=q,
            limit=limit,
            offset=offset,
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    response.headers[TOPLAM_BASLIGI] = str(toplam)
    return satirlar


@router.get("/kpi", response_model=None)
async def kpi(
    db: DbDep,
    clock: ClockDep,
    user: TakipOkuyucu,
    gun: date | None = None,
    birim: str | None = None,
    tur: str | None = None,
) -> Any:
    """Planlama KPI'ları; her kutu `/kpi-liste?kod=` ile aynı sorgudan sayılır."""
    try:
        return await takvim.planlama_kpi(
            db, user, clock, gun or yerel_bugun(clock), birim=_birim(birim), tur=tur
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)


@router.get("/kpi-liste", response_model=None)
async def kpi_liste(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: TakipOkuyucu,
    kod: str = Query(max_length=40),
    gun: date | None = None,
    birim: str | None = None,
    tur: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    try:
        toplam, satirlar = await takvim.kpi_listesi(
            db,
            user,
            clock,
            kod,
            gun or yerel_bugun(clock),
            birim=_birim(birim),
            tur=tur,
            limit=limit,
            offset=offset,
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    response.headers[TOPLAM_BASLIGI] = str(toplam)
    return satirlar


@router.get("/takvim.xlsx", response_model=None)
async def takvim_excel(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: TakipAktarici,
    baslangic: str | None = None,
    bitis: str | None = None,
    birim: str | None = None,
    tur: str | None = None,
) -> Any:
    """Takvim Excel'i — ekranla AYNI fonksiyon ve süzgeç. Tarih boşsa bu hafta."""
    bas = _tarih(baslangic, "Başlangıç") or yerel_bugun(clock)
    bit = _tarih(bitis, "Bitiş") or bas.fromordinal(bas.toordinal() + 6)
    try:
        satirlar = await takvim.takvim(db, user, clock, bas, bit, birim=_birim(birim), tur=tur)
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    irtibatli = user.has("servis.irtibat_gor")
    basliklar, tablo = takvim.excel_satirlari(satirlar, irtibatli=irtibatli)
    await audit.log(
        db,
        "service_plans",
        "takvim.disa_aktar",
        new_value={
            "satir": len(tablo),
            "baslangic": bas.isoformat(),
            "bitis": bit.isoformat(),
            "birim": birim,
            "tur": tur,
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=irtibatli,
    )
    await db.commit()
    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, tablo, "Servis Planı"),
        media_type=_XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="servis-plani-{bas:%Y%m%d}.xlsx"',
            TOPLAM_BASLIGI: str(len(tablo)),
        },
    )


# --- Çakışma önizlemesi -------------------------------------------------------------


@router.post("/kontrol", response_model=None)
async def kontrol(payload: KontrolIn, db: DbDep, user: Planlayici) -> Any:
    """Kayıt yapmadan çakışma önizlemesi (yazma uçlarıyla aynı motor).

    Kişi ve araç planlayıcının kapsamında olmalı (rol testi B3): başka
    şirketin (ya da birimin) personelinin/aracının doluluk takvimi kimlik
    sayarak okunamasın. Kapsam dışı ya da olmayan kaynak → 404.
    """
    for kisi_id in dict.fromkeys(payload.kisi_idler):
        if await kapsam.personel_disinda_mi(db, user, kisi_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Personel bulunamadı (#{kisi_id})")
    if payload.arac_id is not None:
        arac = await db.get(ServiceVehicle, payload.arac_id)
        if arac is None or arac.is_deleted or kapsam.birim_disinda_mi(user, arac.birim):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis aracı bulunamadı")
    bas, bit = planlama.saat_araligi(payload.plan_tarihi, payload.baslangic_saati, payload.sure_dk)
    bulunan = await cakisma.cakismalari_bul(
        db,
        payload.kisi_idler,
        bas,
        bit,
        goren=user,
        arac_id=payload.arac_id,
        haric_so_idler=payload.haric_is_idler,
        visit_id=payload.ziyaret_id,
    )
    return {
        "saat_belirsiz": bas is None,
        "cakismalar": [c.sozluk() for c in bulunan],
    }


# --- Plan yazımı (tek iş) ------------------------------------------------------------


@router.put("/isler/{is_id}/plan", response_model=None)
async def plan_yaz(
    is_id: int, payload: PlanIn, request: Request, db: DbDep, clock: ClockDep, user: Planlayici
) -> Any:
    """Tekli plan + ekip (tek transaction). Ekip gönderilmezse mevcut ekip korunur."""
    so = await _kapsamli_is(db, user, is_id)
    try:
        girdi = payload.girdi()
        with atama.uyari_toplayici() as uyarilar:  # TS-198: yetkinlik uyarısı, engellemez
            plan = await planlama.planla(db, so, girdi, user=user, clock=clock)
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    so = await db.get(ServiceOrder, is_id)
    return {
        "plan": await _plan_cikti(db, plan),
        "durum": so.status if so else None,
        "uyarilar": uyarilar,
    }


@router.delete("/isler/{is_id}/plan", response_model=None)
async def plan_geri_al(
    is_id: int, payload: GeriAlIn, db: DbDep, clock: ClockDep, user: Planlayici
) -> Any:
    """Planı geri alır (neden zorunlu). PLANLANDI → PLANLAMADA; diğer durumlar korunur."""
    so = await _kapsamli_is(db, user, is_id)
    try:
        plan = await planlama.plani_geri_al(
            db, so, payload.neden, not_=payload.not_, user=user, clock=clock
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    so = await db.get(ServiceOrder, is_id)
    return {"plan": await _plan_cikti(db, plan), "durum": so.status if so else None}


@router.get("/isler/{is_id}/plan", response_model=None)
async def aktif_plan_getir(is_id: int, db: DbDep, user: Okuyucu) -> Any:
    """İşin aktif planı (yoksa `plan: null`) — plan penceresinin ön dolumu."""
    so = await _kapsamli_is(db, user, is_id)
    plan = await planlama.aktif_plan(db, so.id)
    return {
        "is_id": so.id,
        "so_no": so.so_no,
        "birim": so.birim,
        "durum": so.status,
        "kapali": so.status in planlama.KAPALI,
        "plan": await _plan_cikti(db, plan) if plan else None,
    }


@router.get("/isler/{is_id}/plan-gecmisi", response_model=None)
async def plan_gecmisi(is_id: int, db: DbDep, user: Okuyucu) -> Any:
    """Aktif ve pasif bütün plan satırları (planlayan, neden, not ile)."""
    so = await _kapsamli_is(db, user, is_id)
    return [await _plan_cikti(db, p) for p in await planlama.plan_gecmisi(db, so)]


@router.get("/isler/{is_id}/saha-onerisi", response_model=None)
async def saha_onerisi(is_id: int, db: DbDep, user: Planlayici) -> Any:
    """Aynı müşteri + lokasyonun son planından / tesis kaydından saha önerisi."""
    so = await _kapsamli_is(db, user, is_id)
    return await planlama.saha_onerisi(db, so, user)


# --- Toplu ve yeniden plan ------------------------------------------------------------


@router.post("/toplu-plan", response_model=None, status_code=status.HTTP_201_CREATED)
async def toplu_plan(payload: TopluPlanIn, db: DbDep, clock: ClockDep, user: Planlayici) -> Any:
    """Aynı birim + müşteri + lokasyondaki plansız işler → tek ziyaret, iş başına plan."""
    try:
        with atama.uyari_toplayici() as uyarilar:
            ziyaret = await planlama.toplu_planla(
                db, payload.is_idler, payload.girdi(), user=user, clock=clock
            )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    return {
        "ziyaret_id": ziyaret.id,
        "ziyaret_no": ziyaret.visit_no,
        "is_sayisi": len(set(payload.is_idler)),
        "uyarilar": uyarilar,
    }


@router.post("/yeniden-plan", response_model=None)
async def yeniden_plan(payload: TopluPlanIn, db: DbDep, clock: ClockDep, user: Planlayici) -> Any:
    """Ziyaret kartındaki seçili işleri tek işlemde taşır (yalnız gönderilenler)."""
    try:
        with atama.uyari_toplayici() as uyarilar:
            planlar = await planlama.yeniden_planla(
                db, payload.is_idler, payload.girdi(), user=user, clock=clock
            )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    return {
        "plan_idler": [p.id for p in planlar],
        "ziyaret_id": planlar[0].visit_id,
        "uyarilar": uyarilar,
    }


# --- Servis araç havuzu (TS-048) ------------------------------------------------------


@router.get("/araclar", response_model=None)
async def araclar(
    db: DbDep,
    user: TakipOkuyucu,
    birim: str | None = None,
    aktif: bool | None = None,
) -> Any:
    """Kapsamdaki birimlerin ve ortak havuzun (birim NULL) araçları."""
    stmt = kapsam.kapsam_birim(
        select(ServiceVehicle).where(ServiceVehicle.is_deleted.is_(False)),
        user,
        ServiceVehicle.birim,
        birimsiz_gorunur=True,
    )
    if birim := _birim(birim):
        stmt = stmt.where((ServiceVehicle.birim == birim) | ServiceVehicle.birim.is_(None))
    if aktif is not None:
        stmt = stmt.where(ServiceVehicle.is_active.is_(aktif))
    satirlar = (await db.scalars(stmt.order_by(ServiceVehicle.plate_key, ServiceVehicle.id))).all()
    return [await _arac_cikti(db, a) for a in satirlar]


async def _arac_referanslari(db, zimmetli_id: int | None, mobilite_id: int | None) -> None:
    if zimmetli_id is not None:
        kisi = await db.get(User, zimmetli_id)
        if kisi is None or not kisi.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Zimmetli personel bulunamadı")
    if mobilite_id is not None and await db.get(Vehicle, mobilite_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mobilite aracı bulunamadı")


async def _plaka_kullanimda(db, plaka: str, haric_id: int | None = None) -> bool:
    stmt = select(ServiceVehicle.id).where(
        ServiceVehicle.plate_key == plaka_anahtari(plaka), ServiceVehicle.is_deleted.is_(False)
    )
    if haric_id is not None:
        stmt = stmt.where(ServiceVehicle.id != haric_id)
    return (await db.scalar(stmt)) is not None


@router.post("/araclar", response_model=None, status_code=status.HTTP_201_CREATED)
async def arac_ekle(payload: AracIn, request: Request, db: DbDep, user: AracYazici) -> Any:
    """Araç ekler. Birim NULL = ortak havuz (yalnız TUMU kapsamı açabilir)."""
    birim = _birim(payload.birim)
    if kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Birim bulunamadı")
    plaka = payload.plaka.strip().upper()
    if await _plaka_kullanimda(db, plaka):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Bu plaka servis araç havuzunda zaten kayıtlı"
        )
    await _arac_referanslari(db, payload.zimmetli_id, payload.mobilite_arac_id)
    arac = ServiceVehicle(
        plate=plaka,
        birim=birim,
        assigned_user_id=payload.zimmetli_id,
        vehicle_id=payload.mobilite_arac_id,
        notes=(payload.notlar or "").strip() or None,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(arac)
    await db.flush()
    await audit.log(
        db,
        "service_vehicles",
        "olustur",
        entity_id=arac.id,
        new_value={"plaka": plaka, "birim": birim, "zimmetli_id": payload.zimmetli_id},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(arac)
    return await _arac_cikti(db, arac)


@router.patch("/araclar/{arac_id}", response_model=None)
async def arac_guncelle(
    arac_id: int, payload: AracPatch, request: Request, db: DbDep, user: AracYazici
) -> Any:
    """Araç günceller. Kapsam dışı araç ya da hedef birim → 404 (yazmadan önce;
    `arac_id` kapsam taramasında)."""
    arac = await db.get(ServiceVehicle, arac_id)
    if arac is None or arac.is_deleted or kapsam.birim_disinda_mi(user, arac.birim):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Araç bulunamadı")
    yeni_birim = None if payload.ortak_havuz else (_birim(payload.birim) or arac.birim)
    if kapsam.birim_degisimi_yasak_mi(user, arac.birim, yeni_birim):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Birim bulunamadı")
    if payload.version != arac.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    if payload.plaka is not None:
        plaka = payload.plaka.strip().upper()
        if await _plaka_kullanimda(db, plaka, haric_id=arac.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Bu plaka servis araç havuzunda zaten kayıtlı"
            )
        arac.plate = plaka
    await _arac_referanslari(db, payload.zimmetli_id, payload.mobilite_arac_id)
    arac.birim = yeni_birim
    if payload.zimmet_kaldir:
        arac.assigned_user_id = None
    elif payload.zimmetli_id is not None:
        arac.assigned_user_id = payload.zimmetli_id
    if payload.mobilite_arac_id is not None:
        arac.vehicle_id = payload.mobilite_arac_id
    if payload.notlar is not None:
        arac.notes = payload.notlar.strip() or None
    if payload.is_active is not None:
        arac.is_active = payload.is_active
    arac.updated_by = user.id
    await audit.log_change(db, arac, "guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    await db.refresh(arac)
    return await _arac_cikti(db, arac)


# --- Planlama P3 (TS-190): müsaitlik, kaynak görünümü, plan uyumu, bölge önerisi ---
#
# - Müsaitlik yazımı `servis.planla` (E02 kontrol: ayrı `servis.musaitlik`
#   izni AÇILMAZ); kişi kapsam dışıysa 404 ve yazma yok. Silme yolu
#   `personel_id` taşır ki kapsam taraması onu hedefleyebilsin.
# - Plan uyumu bir rapordur: ekran `servis_rapor.gor`, Excel
#   `servis_rapor.disaaktar` (KD-06; mobilite `rapor.*` değil); yetkisiz birim
#   parametresi 403; kişi kırılımı yalnız `servis_rapor.personel`.

RaporOkuyucu = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.gor"))]


class MusaitlikIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "kisi_id": 1,
                    "baslangic": "2026-01-15T09:00:00+03:00",
                    "bitis": "2026-01-15T18:00:00+03:00",
                    "tur": "IZIN",
                }
            ]
        },
    )

    kisi_id: int
    baslangic: datetime
    bitis: datetime
    tur: Literal["IZIN", "EGITIM", "OFIS", "DIGER"]
    # ≤200 (plan TS-190 kabulü; kolon 300 ama sağlık/kişisel ayrıntıya yer yok).
    not_: str | None = Field(default=None, alias="not", max_length=200)


def _rapor_birimi(user: User, birim: str | None) -> str | None:
    birim = _birim(birim)
    if birim and kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu birimin verisini göremezsiniz")
    return birim


@router.get("/musaitlik", response_model=None)
async def musaitlik_listesi(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    kisi_id: int | None = None,
) -> Any:
    """Aralıkla örtüşen bloklar (planlayıcı: kapsamındaki personel; diğerleri
    kendi blokları). Not yalnız planlayıcıya ve kişinin kendisine."""
    bas = baslangic or yerel_bugun(clock)
    bit = bitis or bas.fromordinal(bas.toordinal() + 6)
    try:
        return await planlama.musaitlik_listesi(
            db, user, bas, bit, birim=_birim(birim), kisi_id=kisi_id
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)


@router.post("/musaitlik", response_model=None, status_code=status.HTTP_201_CREATED)
async def musaitlik_ekle(
    payload: MusaitlikIn, request: Request, db: DbDep, user: Planlayici
) -> Any:
    """Blok açar (aynı gün kilidiyle). Örtüşen blok 409; not sağlık bilgisi
    içeriyorsa 400. Yanıt aynı aralıktaki planları `plan_uyarilari`nda verir
    (planlar çakışmalı bayrağı alır, blok yine yazılır)."""
    if await kapsam.personel_disinda_mi(db, user, payload.kisi_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    try:
        blok, planlar = await planlama.musaitlik_ekle(
            db,
            kisi_id=payload.kisi_id,
            baslangic=payload.baslangic,
            bitis=payload.bitis,
            tur=payload.tur,
            not_=payload.not_,
            user=user,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    return {
        "id": blok.id,
        "version": blok.version,
        "user_id": blok.user_id,
        "baslangic": blok.starts_at.isoformat(),
        "bitis": blok.ends_at.isoformat(),
        "tur": blok.tur,
        "not": blok.note,
        "plan_uyarilari": [c.sozluk() for c in planlar],
    }


@router.delete("/musaitlik/personel/{personel_id}/bloklar/{blok_id}", response_model=None)
async def musaitlik_sil(
    personel_id: int,
    blok_id: int,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Planlayici,
) -> Any:
    """Bloğu yumuşak siler; kişi kapsam dışı ya da blok o kişinin değilse 404."""
    from app.models import ServiceUnavailability

    if await kapsam.personel_disinda_mi(db, user, personel_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    blok = await db.scalar(
        select(ServiceUnavailability)
        .where(
            ServiceUnavailability.id == blok_id,
            ServiceUnavailability.user_id == personel_id,
        )
        .with_for_update()
    )
    if blok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Müsaitlik bloğu bulunamadı")
    try:
        await planlama.musaitlik_sil(db, blok, user=user, clock=clock, ip=client_ip(request))
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    return {"id": blok.id, "silindi": True}


@router.get("/kaynak-gorunumu", response_model=None)
async def kaynak_gorunumu(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    hafta: date | None = None,
    birim: str | None = None,
) -> Any:
    """Personel × gün: "plan" dakikası (gerçek süre değil), ziyaret sayısı,
    çakışma, müsaitlik ve eğitim oturumu blokları (salt okunur). Planlayıcı
    olmayan yalnız kendi satırını alır."""
    try:
        return await takvim.kaynak_gorunumu(
            db, user, clock, hafta or yerel_bugun(clock), birim=_birim(birim)
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)


@router.get("/plan-uyumu", response_model=None)
async def plan_uyumu(
    db: DbDep,
    clock: ClockDep,
    user: RaporOkuyucu,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    tur: str | None = None,
) -> Any:
    """Plan uyumu (E02-22). Varsayılan: son 30 gün. Eksik paydaya girmez."""
    bit = bitis or yerel_bugun(clock)
    bas = baslangic or bit.fromordinal(bit.toordinal() - 29)
    try:
        return await takvim.plan_uyumu(
            db,
            user,
            clock,
            bas,
            bit,
            birim=_rapor_birimi(user, birim),
            tur=tur,
            personel=user.has("servis_rapor.personel"),
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)


@router.get("/plan-uyumu/ayrinti", response_model=None)
async def plan_uyumu_ayrinti(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: RaporOkuyucu,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    tur: str | None = None,
    sinif: Literal["UYUMLU", "KAYDI", "EKSIK"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Ziyaret satırları; `sinif=` ile özet kutusunun listesi (sayı = `X-Toplam-Kayit`)."""
    bit = bitis or yerel_bugun(clock)
    bas = baslangic or bit.fromordinal(bit.toordinal() - 29)
    try:
        satirlar = await takvim.plan_uyumu_ayrinti(
            db,
            user,
            clock,
            bas,
            bit,
            birim=_rapor_birimi(user, birim),
            tur=tur,
            sinif=sinif,
            personel=user.has("servis_rapor.personel"),
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    response.headers[TOPLAM_BASLIGI] = str(len(satirlar))
    return satirlar[offset : offset + limit]


@router.get("/plan-uyumu.xlsx", response_model=None)
async def plan_uyumu_excel(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Aktarici,
    baslangic: str | None = None,
    bitis: str | None = None,
    birim: str | None = None,
    tur: str | None = None,
) -> Any:
    """Plan uyumu Excel'i — ekranla AYNI fonksiyon. Tarih boşsa son 30 gün."""
    bit = _tarih(bitis, "Bitiş") or yerel_bugun(clock)
    bas = _tarih(baslangic, "Başlangıç") or bit.fromordinal(bit.toordinal() - 29)
    personel = user.has("servis_rapor.personel")
    birim_ = _rapor_birimi(user, birim)
    try:
        rapor = await takvim.plan_uyumu(
            db, user, clock, bas, bit, birim=birim_, tur=tur, personel=personel
        )
        ayrinti = await takvim.plan_uyumu_ayrinti(
            db, user, clock, bas, bit, birim=birim_, tur=tur, personel=personel
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    o = rapor["ozet"]
    sayi = export_svc.Sutun
    sayfalar = [
        export_svc.Sayfa(
            "Özet",
            [sayi("Gösterge"), sayi("Değer", "ondalik")],
            [
                ["Plana uyumlu ziyaret", o["uyumlu"]],
                ["Kaydı (başka gün) ziyaret", o["kaydi"]],
                ["Süre kaydı eksik ziyaret (paydaya girmez)", o["eksik"]],
                ["Uyum oranı (%)", o["oran"]],
                ["Ziyaret sayısı", o["ziyaret_sayisi"]],
                ["İş sayısı", o["is_sayisi"]],
                ["Ziyaret başına iş", o["ziyaret_basina_is"]],
                [f"{takvim.TEKRAR_ZIYARET_GUN} günde tekrar ziyaret", o["tekrar_ziyaret_30"]],
                ["Erteleme sayısı", rapor["erteleme"]["toplam"]],
            ],
        ),
        export_svc.Sayfa(
            "Kırılımlar",
            [
                sayi("Kırılım"),
                sayi("Değer"),
                sayi("Uyumlu", "tamsayi"),
                sayi("Kaydı", "tamsayi"),
                sayi("Eksik", "tamsayi"),
                sayi("Oran (%)", "ondalik"),
            ],
            [
                [ad, r["etiket"], r["uyumlu"], r["kaydi"], r["eksik"], r["oran"]]
                for ad, satirlar in rapor["kirilimlar"].items()
                for r in satirlar
            ],
        ),
        export_svc.Sayfa(
            "Ayrıntı",
            [
                sayi("Ziyaret / İş"),
                sayi("İş Noları"),
                sayi("Plan Tarihi", "tarih"),
                sayi("İlk Kayıt Günü", "tarih"),
                sayi("Sınıf"),
                sayi("Birim"),
                sayi("Tür"),
                sayi("İl"),
            ]
            + ([sayi("Şef"), sayi("Teknisyenler")] if personel else []),
            [
                [
                    r["ziyaret"],
                    ", ".join(r["is_nolari"]),
                    date.fromisoformat(r["plan_tarihi"]),
                    date.fromisoformat(r["ilk_kayit_gunu"]) if r["ilk_kayit_gunu"] else None,
                    takvim.UYUM_ADLARI[r["sinif"]],
                    r["birim"],
                    "Bakım" if r["tur"] == "BAKIM" else "Servis",
                    r["il"],
                ]
                + ([", ".join(r["sefler"]), ", ".join(r["teknisyenler"])] if personel else [])
                for r in ayrinti
            ],
        ),
        export_svc.Sayfa(
            "Erteleme",
            [sayi("Neden"), sayi("Adet", "tamsayi")],
            [[n["ad"], n["adet"]] for n in rapor["erteleme"]["nedenler"]],
        ),
        export_svc.Sayfa(
            "Bekleyen Yaşı",
            [sayi("Aralık"), sayi("Adet", "tamsayi")],
            [[b["aralik"], b["adet"]] for b in rapor["bekleyen_yasi"]],
        ),
    ]
    icerik = await export_svc.sayfalari_xlsx_async(sayfalar)
    await audit.log(
        db,
        "service_plans",
        "plan_uyumu.disa_aktar",
        new_value={
            "baslangic": bas.isoformat(),
            "bitis": bit.isoformat(),
            "birim": birim_,
            "tur": tur,
            "satir": len(ayrinti),
            "kisi_kirilimi": personel,
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=personel,
    )
    await db.commit()
    return Response(
        content=icerik,
        media_type=_XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="plan-uyumu-{bas:%Y%m%d}.xlsx"',
            TOPLAM_BASLIGI: str(len(ayrinti)),
        },
    )


@router.get("/bolge-onerisi", response_model=None)
async def bolge_onerisi(
    db: DbDep,
    clock: ClockDep,
    user: Planlayici,
    is_id: int,
    tarih: date | None = None,
) -> Any:
    """Aynı ilçedeki plansız işler ve ±N gün aynı ilçe ziyaretleri (E02-16).
    Seçilen iş ayrı tekli plan olarak (`PUT /isler/{id}/plan`) kaydedilir."""
    so = await _kapsamli_is(db, user, is_id)
    return await takvim.bolge_onerisi(db, user, clock, so, tarih or yerel_bugun(clock))
