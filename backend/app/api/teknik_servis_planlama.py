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

from datetime import date, time
from typing import Annotated, Any

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
from app.services.teknik_servis import cakisma, kapsam, planlama, takvim
from app.services.teknik_servis.atama import AtamaKapsamDisi, AtamaSatiri
from app.services.teknik_servis.is_emirleri import IsEmriYetkiHatasi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun

router = APIRouter(prefix="/api/teknik-servis/planlama", tags=["teknik-servis-planlama"])

Okuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
Planlayici = Annotated[User, Depends(require_permission("servis.planla"))]
AracYazici = Annotated[User, Depends(require_permission("servis.arac_yaz"))]
Aktarici = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.disaaktar"))]

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --- Hata eşlemesi -----------------------------------------------------------------


def _hata_yaniti(exc: Exception) -> JSONResponse:
    if isinstance(exc, cakisma.PlanCakismasi):
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=exc.govde())
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
    """Ekip: şefler (sorumlu; yalnız `sahaya_giden_sefler` sahaya gider ve
    çakışmaya girer), teknisyenler (her zaman sahada), tek sorumlu teknisyen."""

    sef_idler: list[int] = Field(default_factory=list, max_length=5)
    sahaya_giden_sefler: list[int] = Field(default_factory=list, max_length=5)
    teknisyen_idler: list[int] = Field(default_factory=list, max_length=30)
    sorumlu_id: int | None = None

    def satirlar(self) -> list[AtamaSatiri]:
        sorumlu = self.sorumlu_id
        if sorumlu is None and self.teknisyen_idler:
            sorumlu = self.teknisyen_idler[0]
        if sorumlu is not None and sorumlu not in self.teknisyen_idler:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Sorumlu, ekipteki bir teknisyen olmalı"
            )
        return [AtamaSatiri(user_id=u, rol="SEF") for u in self.sef_idler] + [
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
    user: Okuyucu,
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
    user: Okuyucu,
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
    user: Okuyucu,
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
    user: Okuyucu,
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
    user: Aktarici,
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
    """Kayıt yapmadan çakışma önizlemesi (yazma uçlarıyla aynı motor)."""
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
        plan = await planlama.planla(db, so, girdi, user=user, clock=clock)
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    so = await db.get(ServiceOrder, is_id)
    return {"plan": await _plan_cikti(db, plan), "durum": so.status if so else None}


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
    }


@router.post("/yeniden-plan", response_model=None)
async def yeniden_plan(payload: TopluPlanIn, db: DbDep, clock: ClockDep, user: Planlayici) -> Any:
    """Ziyaret kartındaki seçili işleri tek işlemde taşır (yalnız gönderilenler)."""
    try:
        planlar = await planlama.yeniden_planla(
            db, payload.is_idler, payload.girdi(), user=user, clock=clock
        )
    except _HATALAR as exc:
        return _hata_yaniti(exc)
    await db.commit()
    return {"plan_idler": [p.id for p in planlar], "ziyaret_id": planlar[0].visit_id}


# --- Servis araç havuzu (TS-048) ------------------------------------------------------


@router.get("/araclar", response_model=None)
async def araclar(
    db: DbDep,
    user: Okuyucu,
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
