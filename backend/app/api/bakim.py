"""Planlı bakım: sözleşme, dönem, PB üretimi, eşleştirme, dijital form uçları (TS-060…069).

Kurallar (plan §2.2, E04):

- **İzinler:** okuma `bakim.gor`; sözleşme/kapsam/üretim/hedef tarih/eşleştirme
  `bakim.yaz`; kapsam dışı kararı ve uygunsuzluk aksiyonu `bakim.onayla`.
  PB formu servis işidir: okuma `servis.gor`, taslak `servis.yaz`, tamamlama
  `servis.tamamla` + iş erişimi (`is_erisimi_yok_mu`; atanmamış teknisyen 404).
  Yeniden açma E01'in `POST /isler/{id}/yeniden-ac` (`servis.kapat`) ucudur;
  bakım tarafı kancayla tepki verir.
- **Kapsam:** sözleşme = birim + müşteri kapsamı; URL'deki kayıt kapsam
  dışıysa 404 ve hiçbir yazma yapılmaz. Yol parametre adları kapsam
  taramasının sözleşmesidir (`sozlesme_id`/`{id}`, `so_id`, `ekipman_id`);
  dönem, aksiyon ve talep kimlikleri hep bir üst kaydın ALTINDA durur ki
  üst kaydın kapsamı önce sorulsun.
- **Ücret:** yalnız `sees_cost` (maliyet.gor) ile görünür, anahtar olarak
  yoktur; yazma ayrı uç (`maliyet.gor ∧ bakim.yaz`). Sözleşme gövdesinde
  ücret gönderen, ücret görmeyen kullanıcı 403 alır.
- **Hata kodları:** kural 409, girdi 400, yetki 403, yok/kapsam dışı 404.
  Kural ihlalinin ek verisi (çakışan sözleşmeler, açık PB'ler) 409 gövdesinde
  `{"mesaj", "kod", ...}` olarak döner.
- Denetim izi servis katmanında, aynı transaction'da; commit burada.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala, sees_cost
from app.models import (
    Account,
    Address,
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenanceExclusionRequest,
    MaintenanceForm,
    MaintenanceGenerationRun,
    MaintenanceNonconformity,
    MaintenancePeriod,
    MaintenanceVisit,
    ServiceEquipment,
    ServiceOrder,
    ServiceOrderSerial,
    User,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.permissions import SCOPE_ALL
from app.services import accounts as hesap_svc
from app.services import audit
from app.services import settings as ayar_svc
from app.services.normalize import tr_normkey
from app.services.statemachine import IzinsizGecis
from app.services.teknik_servis import (
    bakim,
    bakim_formu,
    bakim_raporlari,
    bakim_sablonlari,
    bakim_uretim,
    kapsam,
)
from app.services.teknik_servis.ana_veri import AnaVeriHatasi
from app.services.teknik_servis.bakim import BakimHatasi, BakimKapsamDisi
from app.services.teknik_servis.bakim_raporlari import BakimRaporFiltresi, BakimRaporHatasi
from app.services.teknik_servis.gecmis import KisiselVeriHatasi
from app.services.teknik_servis.is_emirleri import IsEmriKapsamDisi, IsEmriYetkiHatasi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun

router = APIRouter(prefix="/api/teknik-servis/bakim", tags=["bakim"])

Okuyucu = Annotated[User, Depends(require_permission("bakim.gor"))]
Yazici = Annotated[User, Depends(require_permission("bakim.yaz"))]
Onaylayici = Annotated[User, Depends(require_permission("bakim.onayla"))]
UcretYazici = Annotated[User, Depends(require_permission("bakim.yaz", "maliyet.gor"))]
ArizaAcan = Annotated[User, Depends(require_permission("bakim.onayla", "servis.yaz"))]
ServisOkuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
FormYazici = Annotated[User, Depends(require_permission("servis.yaz"))]
FormTamamlayici = Annotated[User, Depends(require_permission("servis.tamamla"))]
# Bakım Excel'i: KD-06 — servis rollerine `rapor.disaaktar` verilmez.
Aktarici = Annotated[User, Depends(require_permission("bakim.gor", "servis_rapor.disaaktar"))]

_ACIK = DURUM_GRUPLARI["ACIK"]
_COZULDU = DURUM_GRUPLARI["COZULDU"]
_UCRET_GIRDI = ("fee_per_visit", "contract_total")


# --- Hata eşleme -------------------------------------------------------------------


def _hata(exc: Exception) -> HTTPException:
    if isinstance(exc, BakimRaporHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, BakimKapsamDisi | IsEmriKapsamDisi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError | IsEmriYetkiHatasi):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, KisiselVeriHatasi):
        return HTTPException(
            status.HTTP_400_BAD_REQUEST, "Metne irtibat adı veya telefonu yazılamaz"
        )
    if isinstance(exc, AnaVeriHatasi):
        return HTTPException(exc.kod, exc.mesaj)
    if isinstance(exc, ServisGirdiHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, BakimHatasi) and exc.veri:
        return HTTPException(status.HTTP_409_CONFLICT, {"mesaj": str(exc), **exc.veri})
    if isinstance(exc, ServisHatasi | IzinsizGecis):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, NotImplementedError):
        # Bağımlı paketin (D1-B/D1-C) servis fonksiyonu henüz yok.
        return HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "Bağlı servis işi altyapısı henüz hazır değil"
        )
    raise exc


_HATALAR = (
    BakimRaporHatasi,
    KisiselVeriHatasi,
    BakimKapsamDisi,
    PermissionError,
    AnaVeriHatasi,
    ServisGirdiHatasi,
    ServisHatasi,
    IzinsizGecis,
    NotImplementedError,
)


async def _cagir(aw):
    try:
        return await aw
    except _HATALAR as exc:
        raise _hata(exc) from exc


async def _sozlesme(db, user: User, sozlesme_id: int, *, kilitle: bool = False):
    return await _cagir(bakim.kapsamli_sozlesme(db, user, sozlesme_id, kilitle=kilitle))


async def _pb(db, user: User, so_id: int) -> ServiceOrder:
    """URL'deki servis işi: yok/silinmiş/kapsam dışı → 404 (yazma yok)."""
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    if so.tur != "PB":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bu iş planlı bakım işi değil")
    return so


def _surum(kayit, version: int | None) -> None:
    if version is not None and kayit.version != version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyin.",
        )


# --- Şemalar ------------------------------------------------------------------------

_ORNEK_SOZLESME = {
    "birim": "GUVENLIK",
    "account_id": 1,
    "address_id": None,
    "baslangic": "2026-01-01",
    "bitis": "2027-01-01",
    "annual_frequency": 2,
    "kapsam": {"XRAY": 1, "KAPI_DEDEKTORU": 1},
}


class SozlesmeIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [_ORNEK_SOZLESME]})

    birim: str = Field(default="GUVENLIK", max_length=20)
    account_id: int
    address_id: int | None = None
    contact_id: int | None = None
    responsible_user_id: int | None = None
    baslangic: date | None = None
    bitis: date | None = None
    annual_frequency: int | None = Field(default=None, ge=1, le=12)
    fixed_months: list[int] | None = Field(default=None, max_length=12)
    kapsam: dict[str, int] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=4000)
    cakisma_onayi: bool = False
    cakisma_gerekcesi: str | None = Field(default=None, max_length=500)
    # Ücret (yalnız maliyet.gor): gönderen ücret görmeyen kullanıcı 403 alır.
    fee_per_visit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    contract_total: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class SozlesmePatch(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"version": 1, "notes": "not"}]})

    version: int
    birim: str | None = Field(default=None, max_length=20)
    account_id: int | None = None
    address_id: int | None = None
    contact_id: int | None = None
    responsible_user_id: int | None = None
    baslangic: date | None = None
    bitis: date | None = None
    annual_frequency: int | None = Field(default=None, ge=1, le=12)
    fixed_months: list[int] | None = Field(default=None, max_length=12)
    notes: str | None = Field(default=None, max_length=4000)
    cakisma_onayi: bool = False
    cakisma_gerekcesi: str | None = Field(default=None, max_length=500)
    fee_per_visit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    contract_total: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class DurumIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"hedef": "AKTIF"}]})

    hedef: str = Field(max_length=20)
    cakisma_onayi: bool = False
    cakisma_gerekcesi: str | None = Field(default=None, max_length=500)


class KapsamIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"kapsam": {"XRAY": 1}}]})

    kapsam: dict[str, int]
    version: int | None = None


class UcretIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"fee_per_visit": "1000.00", "currency": "TRY"}]}
    )

    fee_per_visit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    contract_total: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="TRY", pattern=r"^[A-Z]{3}$")
    version: int | None = None


class EslesmeSatiri(BaseModel):
    kalem_id: int
    equipment_id: int | None = None


class EslestirIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"eslesmeler": [{"kalem_id": 1, "equipment_id": 1}]}]}
    )

    eslesmeler: list[EslesmeSatiri] = Field(max_length=500)


class HedefTarihIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"hedef_tarih": "2026-03-01", "gerekce": "Müşteri"}]}
    )

    hedef_tarih: date
    gerekce: str = Field(min_length=1, max_length=500)


class OtomatikUretimIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"acik": False}]})

    acik: bool


class KontrolIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kod: str = Field(max_length=30)
    sonuc: str = Field(max_length=20)
    not_: str | None = Field(default=None, alias="not", max_length=2000)


class FormIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={"examples": [{"version": 1, "zone": "Giriş"}]},
    )

    version: int | None = None
    zone: str | None = Field(default=None, max_length=120)
    seri_no: str | None = Field(default=None, max_length=200)
    performed_work: str | None = Field(default=None, max_length=4000)
    technician_note: str | None = Field(default=None, max_length=4000)
    parts_text: str | None = Field(default=None, max_length=2000)
    bakim_sonucu: str | None = Field(default=None, max_length=20)
    kontroller: list[KontrolIn] = Field(default_factory=list, max_length=50)
    # Yalnız tamamlamada: süre kaydı eksik olduğu bilinerek kapatılıyor (TS-076).
    sure_eksik_onay: bool = False


class OnayIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"tur": "ALINAMADI", "eksik_nedeni": "Yetkili yok"}]}
    )

    tur: str = Field(max_length=12)
    imzalayan_ad: str | None = Field(default=None, max_length=120)
    imzalayan_unvan: str | None = Field(default=None, max_length=80)
    ek_id: int | None = None
    eksik_nedeni: str | None = Field(default=None, max_length=300)


class KapsamDisiIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"neden": "SOKULMUS", "aciklama": "Cihaz sökülmüş"}]}
    )

    neden: str = Field(max_length=16)
    aciklama: str = Field(min_length=1, max_length=2000)


class KararIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, json_schema_extra={"examples": [{"onay": False, "not": "Red"}]}
    )

    onay: bool
    not_: str | None = Field(default=None, alias="not", max_length=1000)


class UygunsuzlukPatch(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"version": 1}]})

    version: int
    action_type: str | None = Field(default=None, max_length=20)
    responsible_user_id: int | None = None
    due_date: date | None = None


class KapatIn(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, json_schema_extra={"examples": [{"not": "Giderildi"}]}
    )

    not_: str = Field(alias="not", min_length=1, max_length=2000)


# --- Yardımcılar ---------------------------------------------------------------------


def _ucret_yetkisi(user: User, govde: dict[str, Any]) -> dict[str, Any]:
    """Gövdedeki ücret alanlarını ayırır; ücret görmeyen gönderirse 403."""
    ucret = {k: govde.pop(k) for k in _UCRET_GIRDI if k in govde}
    gonderilen = {k: v for k, v in ucret.items() if v is not None}
    if gonderilen and not sees_cost(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Ücret alanı için yetkiniz yok (maliyet.gor)"
        )
    return ucret if sees_cost(user) else {}


def _takvim_girdisi(govde: dict[str, Any]) -> dict[str, Any]:
    """`baslangic`/`bitis` (yerel gün) → `valid_from`/`valid_to` (yerel gece yarısı)."""
    for ad, kolon in (("baslangic", "valid_from"), ("bitis", "valid_to")):
        if ad in govde:
            gun = govde.pop(ad)
            govde[kolon] = bakim.yerel_gece(gun) if gun is not None else None
    return govde


async def _sozlesme_ciktisi(
    db, sozlesme: MaintenanceContract, user: User, clock, *, ayrinti: bool = False
) -> dict[str, Any]:
    musteri = await db.get(Account, sozlesme.account_id) if sozlesme.account_id else None
    tesis = await db.get(Address, sozlesme.address_id) if sozlesme.address_id else None
    satir = bakim.sozlesme_satiri(
        sozlesme, musteri=musteri, tesis=tesis, clock=clock, maliyet=sees_cost(user)
    )
    kalemler = await bakim.acik_kalemler(db, sozlesme.id)
    satir["kapsam"] = bakim.kapsam_ozeti(kalemler)
    satir["eslesen_kalem"] = sum(1 for k in kalemler if k.equipment_id)
    satir["toplam_kalem"] = len(kalemler)
    satir["sayac"] = await bakim.donem_sayaci(db, sozlesme, clock)
    if ayrinti:
        sorumlu = (
            await db.get(User, sozlesme.responsible_user_id)
            if sozlesme.responsible_user_id
            else None
        )
        satir["sorumlu"] = sorumlu.full_name if sorumlu else None
        satir["acik_pb"] = await bakim.pb_sayisi(db, sozlesme.id, yalniz_acik=True)
        satir["toplam_pb"] = await bakim.pb_sayisi(db, sozlesme.id)
    return satir


# =============================================================================
# Sözleşmeler (TS-060)
# =============================================================================


@router.get("/sozlesmeler")
async def sozlesme_listesi(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    birim: str | None = None,
    musteri_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    suresi_doluyor: bool = False,
    eslesme_eksik: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    stmt = select(MaintenanceContract).where(MaintenanceContract.is_deleted.is_(False))
    stmt = bakim.sozlesme_kapsami(stmt, user)
    if durum:
        stmt = stmt.where(MaintenanceContract.status == durum)
    if birim:
        stmt = stmt.where(MaintenanceContract.birim == birim)
    if musteri_id is not None:
        stmt = stmt.where(MaintenanceContract.account_id == musteri_id)
    if q:
        anahtar = f"%{tr_normkey(q)}%"
        stmt = stmt.where(
            or_(
                MaintenanceContract.contract_no.ilike(f"%{q.strip()}%"),
                MaintenanceContract.account_id.in_(
                    select(Account.id).where(Account.title_key.like(anahtar))
                ),
            )
        )
    if suresi_doluyor:
        simdi = clock.now()
        gun = await bakim.bitis_uyari_gun(db)
        stmt = stmt.where(
            MaintenanceContract.status == "AKTIF",
            MaintenanceContract.valid_to > simdi,
            MaintenanceContract.valid_to <= simdi + timedelta(days=gun),
        )
    if eslesme_eksik:
        stmt = stmt.where(
            exists().where(
                MaintenanceContractItem.contract_id == MaintenanceContract.id,
                MaintenanceContractItem.is_deleted.is_(False),
                MaintenanceContractItem.valid_to.is_(None),
                MaintenanceContractItem.pb_uygun.is_(True),
                MaintenanceContractItem.equipment_id.is_(None),
            )
        )
    stmt = stmt.order_by(MaintenanceContract.contract_no.desc())
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [await _sozlesme_ciktisi(db, s, user, clock) for (s,) in satirlar]


@router.post("/sozlesmeler", status_code=status.HTTP_201_CREATED)
async def sozlesme_ekle(
    payload: SozlesmeIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    govde = payload.model_dump()
    ucret = _ucret_yetkisi(user, govde)
    govde = _takvim_girdisi(govde)
    girdi = bakim.SozlesmeGirdisi(**govde)
    sozlesme = await _cagir(
        bakim.sozlesme_olustur(db, girdi, user=user, clock=clock, ip=client_ip(request))
    )
    if any(v is not None for v in ucret.values()):
        await _cagir(
            bakim.ucret_guncelle(
                db,
                sozlesme,
                {k: v for k, v in ucret.items() if v is not None},
                user=user,
                ip=client_ip(request),
            )
        )
    await db.commit()
    return await _sozlesme_ciktisi(db, sozlesme, user, clock, ayrinti=True)


@router.get("/sozlesmeler/{id}")
async def sozlesme_detay(id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, id)
    return await _sozlesme_ciktisi(db, sozlesme, user, clock, ayrinti=True)


@router.patch("/sozlesmeler/{id}")
async def sozlesme_duzenle(
    id: int, payload: SozlesmePatch, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, id)
    govde = payload.model_dump(exclude_unset=True)
    _surum(sozlesme, govde.pop("version"))
    ucret = _ucret_yetkisi(user, govde)
    govde = _takvim_girdisi(govde)
    await _cagir(
        bakim.sozlesme_guncelle(db, sozlesme, govde, user=user, clock=clock, ip=client_ip(request))
    )
    if ucret:
        await _cagir(bakim.ucret_guncelle(db, sozlesme, ucret, user=user, ip=client_ip(request)))
    await db.commit()
    return await _sozlesme_ciktisi(db, sozlesme, user, clock, ayrinti=True)


@router.post("/sozlesmeler/{id}/durum")
async def sozlesme_durum(
    id: int, payload: DurumIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, id)
    sonuc = await _cagir(
        bakim.durum_degistir(
            db,
            sozlesme,
            payload.hedef,
            user=user,
            clock=clock,
            cakisma_onayi=payload.cakisma_onayi,
            cakisma_gerekcesi=payload.cakisma_gerekcesi,
            ip=client_ip(request),
        )
    )
    await db.commit()
    cikti = await _sozlesme_ciktisi(db, sozlesme, user, clock, ayrinti=True)
    cikti["acik_pb_isleri"] = sonuc.acik_pb_isleri
    return cikti


@router.put("/sozlesmeler/{id}/kapsam")
async def sozlesme_kapsam(
    id: int, payload: KapsamIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, id, kilitle=True)
    _surum(sozlesme, payload.version)
    yeni = await _cagir(
        bakim.kapsam_guncelle(
            db, sozlesme, payload.kapsam, user=user, clock=clock, ip=client_ip(request)
        )
    )
    await db.commit()
    return {"kapsam": yeni}


@router.put("/sozlesmeler/{id}/ucret")
async def sozlesme_ucret(
    id: int, payload: UcretIn, request: Request, db: DbDep, clock: ClockDep, user: UcretYazici
) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, id)
    govde = payload.model_dump(exclude_unset=True)
    _surum(sozlesme, govde.pop("version", None))
    await _cagir(bakim.ucret_guncelle(db, sozlesme, govde, user=user, ip=client_ip(request)))
    await db.commit()
    return await _sozlesme_ciktisi(db, sozlesme, user, clock, ayrinti=True)


# --- Eşleştirme (TS-063) ---------------------------------------------------------------


@router.get("/sozlesmeler/{id}/eslestirme")
async def eslestirme(id: int, db: DbDep, user: Okuyucu) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, id)
    kalemler = await bakim.eslestirme_onerileri(db, sozlesme, user)
    uygun = [k for k in kalemler if k["pb_uygun"]]
    eslesen = sum(1 for k in uygun if k["equipment_id"])
    return {
        "oran": {
            "toplam": len(uygun),
            "eslesen": eslesen,
            "yuzde": 100.0 if not uygun else round(100.0 * eslesen / len(uygun), 1),
        },
        "kalemler": kalemler,
        "tur_adlari": bakim_sablonlari.CIHAZ_TURU_ADLARI,
    }


@router.put("/sozlesmeler/{id}/eslestirme")
async def eslestirme_onayla(
    id: int, payload: EslestirIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, id, kilitle=True)
    await _cagir(
        bakim.eslestir(
            db,
            sozlesme,
            [(s.kalem_id, s.equipment_id) for s in payload.eslesmeler],
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    )
    await db.commit()
    return await eslestirme(id, db, user)


# =============================================================================
# Dönemler (TS-061)
# =============================================================================


def _pb_sayilari_sorgusu(donem_idleri: list[int]):
    so = ServiceOrder
    return (
        select(
            so.maintenance_period_id,
            func.count(so.id),
            func.count(case((so.status.in_(sorted(_ACIK)), 1))),
            func.count(case((so.status.in_(sorted(_COZULDU)), 1))),
            func.count(case((so.status == "IPTAL", 1))),
        )
        .where(
            so.tur == "PB",
            so.is_deleted.is_(False),
            so.maintenance_period_id.in_(donem_idleri),
        )
        .group_by(so.maintenance_period_id)
    )


async def _donem_satirlari(
    db, donemler: list[tuple[MaintenancePeriod, MaintenanceContract, str | None]], clock
) -> list[dict[str, Any]]:
    idler = [d.id for d, _, _ in donemler]
    sayilar = {}
    if idler:
        q = _pb_sayilari_sorgusu(idler)
        for pid, toplam, acik, cozulen, iptal in (await db.execute(q)).all():
            sayilar[pid] = (toplam, acik, cozulen, iptal)
    bugun = yerel_bugun(clock)
    tolerans = int(await ayar_svc.get(db, "bakim_tolerans_gun") or 0)
    satirlar = []
    for d, s, musteri in donemler:
        toplam, acik, cozulen, iptal = sayilar.get(d.id, (0, 0, 0, 0))
        satirlar.append(
            {
                "id": d.id,
                "contract_id": s.id,
                "contract_no": s.contract_no,
                "musteri": musteri,
                "birim": s.birim,
                "dongu_baslangici": yerel_gun(d.cycle_start).isoformat(),
                "sequence_no": d.sequence_no,
                "frekans": s.annual_frequency,
                "target_date": d.target_date.isoformat(),
                "target_manual": d.target_manual,
                "target_change_reason": d.target_change_reason,
                "closed_at": d.closed_at,
                "closing_kind": d.closing_kind,
                "gecikmis": d.closed_at is None
                and d.target_date < bugun - timedelta(days=tolerans),
                "pb_toplam": toplam,
                "pb_acik": acik,
                "pb_tamamlanan": cozulen,
                "pb_iptal": iptal,
                "version": d.version,
            }
        )
    return satirlar


@router.get("/donemler")
async def donem_listesi(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    sozlesme_id: int | None = None,
    gecikmis: bool = False,
    vadesi_gelen: bool = False,
    acik: bool = False,
    ay: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    sorumlu_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Dönem listesi. `gecikmis`: açık ve hedef + tolerans geçmiş (uyarıyla aynı
    koşul); `vadesi_gelen`: açık ve hedef ≤ bugün."""
    stmt = (
        select(MaintenancePeriod, MaintenanceContract, Account.title)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .outerjoin(Account, Account.id == MaintenanceContract.account_id)
        .where(
            MaintenancePeriod.is_deleted.is_(False),
            MaintenanceContract.is_deleted.is_(False),
        )
    )
    stmt = bakim.donem_kapsami(stmt, user)
    bugun = yerel_bugun(clock)
    if sozlesme_id is not None:
        stmt = stmt.where(MaintenanceContract.id == sozlesme_id)
    if gecikmis:
        tolerans = int(await ayar_svc.get(db, "bakim_tolerans_gun") or 0)
        stmt = stmt.where(
            MaintenanceContract.status == "AKTIF", bakim.gecikme_kosulu(bugun, tolerans)
        )
    if vadesi_gelen:
        stmt = stmt.where(
            MaintenanceContract.status == "AKTIF",
            MaintenancePeriod.closed_at.is_(None),
            MaintenancePeriod.target_date <= bugun,
        )
    if acik:
        stmt = stmt.where(MaintenancePeriod.closed_at.is_(None))
    if ay:
        yil, ay_no = int(ay[:4]), int(ay[5:])
        bas = date(yil, ay_no, 1)
        stmt = stmt.where(
            MaintenancePeriod.target_date >= bas,
            MaintenancePeriod.target_date < bakim.ay_ekle(bas, 1),
        )
    if sorumlu_id is not None:
        stmt = stmt.where(MaintenanceContract.responsible_user_id == sorumlu_id)
    stmt = stmt.order_by(MaintenancePeriod.target_date, MaintenanceContract.contract_no)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _donem_satirlari(db, [tuple(r) for r in satirlar], clock)


@router.get("/sozlesmeler/{sozlesme_id}/donemler")
async def sozlesme_donemleri(
    sozlesme_id: int, db: DbDep, clock: ClockDep, user: Okuyucu
) -> list[dict[str, Any]]:
    sozlesme = await _sozlesme(db, user, sozlesme_id)
    musteri = await db.get(Account, sozlesme.account_id) if sozlesme.account_id else None
    donemler = (
        await db.scalars(
            select(MaintenancePeriod)
            .where(
                MaintenancePeriod.contract_id == sozlesme.id,
                MaintenancePeriod.is_deleted.is_(False),
            )
            .order_by(MaintenancePeriod.cycle_start, MaintenancePeriod.sequence_no)
        )
    ).all()
    return await _donem_satirlari(
        db, [(d, sozlesme, musteri.title if musteri else None) for d in donemler], clock
    )


@router.get("/sozlesmeler/{sozlesme_id}/donemler/{donem_id}/cihazlar")
async def donem_cihazlari(
    sozlesme_id: int, donem_id: int, db: DbDep, user: Okuyucu
) -> list[dict[str, Any]]:
    """Dönemin cihaz PB tablosu (toplu planlama seçimi buradan yapılır)."""
    sozlesme = await _sozlesme(db, user, sozlesme_id)
    donem = await _cagir(bakim.kapsamli_donem(db, sozlesme, donem_id))
    talep = aliased(MaintenanceExclusionRequest)
    satirlar = (
        await db.execute(
            select(ServiceOrder, MaintenanceContractItem, MaintenanceForm, talep.status)
            .join(
                MaintenanceContractItem,
                MaintenanceContractItem.id == ServiceOrder.contract_item_id,
            )
            .outerjoin(MaintenanceForm, MaintenanceForm.service_order_id == ServiceOrder.id)
            .outerjoin(
                talep,
                and_(
                    talep.service_order_id == ServiceOrder.id,
                    talep.status == "TALEP",
                    talep.is_deleted.is_(False),
                ),
            )
            .where(
                ServiceOrder.maintenance_period_id == donem.id,
                ServiceOrder.tur == "PB",
                ServiceOrder.is_deleted.is_(False),
            )
            .order_by(MaintenanceContractItem.equipment_type, MaintenanceContractItem.sira)
        )
    ).all()
    sonuc = []
    for so, kalem, form, talep_durumu in satirlar:
        seri = await db.scalar(
            select(ServiceOrderSerial.seri_no)
            .where(
                ServiceOrderSerial.service_order_id == so.id,
                ServiceOrderSerial.is_active.is_(True),
            )
            .order_by(ServiceOrderSerial.id.desc())
            .limit(1)
        )
        sonuc.append(
            {
                "so_id": so.id,
                "so_no": so.so_no,
                "status": so.status,
                "kapali": so.status not in _ACIK,
                "equipment_type": kalem.equipment_type,
                "sira": kalem.sira,
                "serial_no": seri,
                "zone": form.zone if form else None,
                "form_durumu": form.status if form else None,
                "kapsam_disi_talebi": talep_durumu is not None,
                "address_id": so.address_id,
            }
        )
    return sonuc


@router.patch("/sozlesmeler/{sozlesme_id}/donemler/{donem_id}/hedef-tarih")
async def donem_hedef_tarih(
    sozlesme_id: int,
    donem_id: int,
    payload: HedefTarihIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict[str, Any]:
    sozlesme = await _sozlesme(db, user, sozlesme_id)
    donem = await _cagir(bakim.kapsamli_donem(db, sozlesme, donem_id))
    await _cagir(
        bakim.hedef_tarih_degistir(
            db, donem, payload.hedef_tarih, payload.gerekce, user=user, ip=client_ip(request)
        )
    )
    await db.commit()
    musteri = await db.get(Account, sozlesme.account_id) if sozlesme.account_id else None
    return (
        await _donem_satirlari(db, [(donem, sozlesme, musteri.title if musteri else None)], clock)
    )[0]


def _uretim_ciktisi(sonuc: bakim_uretim.UretimSonucu) -> dict[str, Any]:
    return {
        "run_id": sonuc.run.id,
        "generated": sonuc.run.generated_count,
        "uretilen": [u["so_no"] for u in sonuc.uretilen],
        "skipped": sonuc.atlanan,
    }


@router.post("/sozlesmeler/{sozlesme_id}/donemler/{donem_id}/eksik-pb")
async def donem_eksik_pb(
    sozlesme_id: int,
    donem_id: int,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict[str, Any]:
    """Dönemin eksik cihaz PB'lerini idempotent tamamlar (ikinci çağrı 0)."""
    sozlesme = await _sozlesme(db, user, sozlesme_id)
    donem = await _cagir(bakim.kapsamli_donem(db, sozlesme, donem_id))
    sonuc = await _cagir(
        bakim_uretim.uret_ayrintili(
            db, clock, user, "EKSIK_TAMAMLA", sozlesme_id=sozlesme.id, donem_id=donem.id
        )
    )
    await audit.log(
        db,
        "maintenance_generation_runs",
        "bakim.uret",
        entity_id=sonuc.run.id,
        new_value={"tetik": "EKSIK_TAMAMLA", "donem_id": donem.id, "uretilen": len(sonuc.uretilen)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _uretim_ciktisi(sonuc)


# =============================================================================
# PB üretimi (TS-062)
# =============================================================================


@router.post("/uretim/onizleme")
async def uretim_onizleme(db: DbDep, clock: ClockDep, user: Yazici) -> dict[str, Any]:
    """DB'ye yazmaz (aynı `uret()` SAVEPOINT'te koşar ve geri alınır)."""
    sonuc = await _cagir(bakim_uretim.onizle(db, clock, user))
    await db.rollback()
    return sonuc


@router.post("/uretim")
async def uretim(request: Request, db: DbDep, clock: ClockDep, user: Yazici) -> dict[str, Any]:
    sonuc = await _cagir(bakim_uretim.uret_ayrintili(db, clock, user, "ELLE"))
    await audit.log(
        db,
        "maintenance_generation_runs",
        "bakim.uret",
        entity_id=sonuc.run.id,
        new_value={"tetik": "ELLE", "uretilen": len(sonuc.uretilen), "atlanan": len(sonuc.atlanan)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _uretim_ciktisi(sonuc)


@router.get("/uretim-kayitlari")
async def uretim_kayitlari(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Üretim turları. Atlanan listesi kullanıcının kapsamına süzülür (başka
    birimin sözleşme numarası/müşterisi görünmez)."""
    stmt = select(MaintenanceGenerationRun).order_by(MaintenanceGenerationRun.id.desc())
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    # Şirket ayrımı: TUMU kapsamı da etkin şirketle sınırlı; genel sayı ve
    # süzülmemiş atlanan listesi yalnız şirket süzgeci olmayan kullanıcıda.
    tum = kapsam.tum_kayitlar_mi(user)
    gorunur: set[int] | None = None
    if not tum:
        gorunur = set(
            (await db.scalars(bakim.sozlesme_kapsami(select(MaintenanceContract.id), user))).all()
        )
    sonuc = []
    for (run,) in satirlar:
        atlanan = run.skipped or []
        if gorunur is not None:
            atlanan = [a for a in atlanan if a.get("contract_id") in gorunur]
        sonuc.append(
            {
                "id": run.id,
                "tetik": run.tetik,
                "created_at": run.created_at,
                "created_by": run.created_by,
                "generated_count": run.generated_count if tum else None,
                "skipped": atlanan,
            }
        )
    return sonuc


@router.get("/otomatik-uretim")
async def otomatik_uretim_durumu(db: DbDep, user: Okuyucu) -> dict[str, Any]:
    # Bilinçli olarak ROL kapsamı (şirket değil): otomatik üretim GENEL bir
    # ayardır ve kapısı (`bakim.otomatik_uretim_ayarla`) genel eşleştirme
    # oranına bakar; TUMU kullanıcıya gösterilen oran kapıyla aynı olmalı.
    # Yalnız toplam/eşleşen SAYISIDIR, kayıt ayrıntısı içermez.
    tum = user.role is not None and user.role.scope == SCOPE_ALL
    return {
        "acik": bool(await ayar_svc.get(db, "bakim_otomatik_uretim")),
        "oran": await bakim.eslestirme_orani(db, None if tum else user),
        "degistirebilir": tum and user.has("bakim.yaz"),
    }


@router.put("/otomatik-uretim")
async def otomatik_uretim_ayarla(
    payload: OtomatikUretimIn, request: Request, db: DbDep, user: Yazici
) -> dict[str, Any]:
    """`bakim_otomatik_uretim` eşleştirme %100 olmadan açılamaz (409)."""
    sonuc = await _cagir(
        bakim.otomatik_uretim_ayarla(db, payload.acik, user=user, ip=client_ip(request))
    )
    await db.commit()
    return sonuc


# =============================================================================
# Özet (KPI) — her kutu sayısı = açtığı listenin `X-Toplam-Kayit`'i
# =============================================================================


@router.get("/ozet")
async def ozet(db: DbDep, clock: ClockDep, user: Okuyucu) -> dict[str, Any]:
    """KPI kutuları (E04-18 adım 1 + E04-19 adım 2) — tanım ve hesap tek yerde
    (`bakim_raporlari.KPI_TANIMLARI` / `kpi_degerleri`); para alanı yok."""
    return {
        "kutular": await bakim_raporlari.kpi_degerleri(db, user, clock),
        "eslestirme": await bakim.eslestirme_orani(db, user),
    }


# =============================================================================
# Bakım raporları (TS-185: E12-12 dönem tamamlama, E04-18/19 KPI listeleri, Excel)
# =============================================================================


def _rapor_filtresi(
    user: User,
    baslangic: date | None,
    bitis: date | None,
    birim: str | None,
    sozlesme_id: int | None,
    musteri_id: int | None,
    kpi: str | None,
) -> BakimRaporFiltresi:
    """Süzgeç doğrulaması: tarih sırası / 24 ay / bilinmeyen birim-KPI 400,
    yetkisiz birim 403 (E12-08 kuralları)."""
    f = BakimRaporFiltresi(
        baslangic=baslangic,
        bitis=bitis,
        birim=birim or None,
        sozlesme_id=sozlesme_id,
        musteri_id=musteri_id,
        kpi=kpi or None,
    )
    try:
        return bakim_raporlari.filtre_dogrula(f, user)
    except (BakimRaporHatasi, PermissionError) as exc:
        raise _hata(exc) from exc


@router.get("/raporlar/donem-tamamlama")
async def donem_tamamlama_raporu(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    sozlesme_id: int | None = None,
    musteri_id: int | None = None,
    kpi: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Planlı bakım tamamlama raporu (E12-12): sözleşme dönemi satırları,
    `%oran (tamamlanan/PB) — durum`. `kpi=UYUM_ORANI` uyum paydasını açar
    (sayısı = kutunun `payda`sı). Para alanı yoktur."""
    f = _rapor_filtresi(user, baslangic, bitis, birim, sozlesme_id, musteri_id, kpi)
    if f.kpi and f.kpi not in bakim_raporlari.DONEM_KPILERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {f.kpi}")
    bugun = yerel_bugun(clock)
    tolerans = await bakim_raporlari.tolerans_gun(db)
    stmt = bakim_raporlari.donem_tamamlama_sorgusu(user, f, bugun=bugun, tolerans=tolerans)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [bakim_raporlari.donem_satiri(r, bugun=bugun, tolerans=tolerans) for r in satirlar]


@router.get("/raporlar/pb-isleri")
async def pb_isleri_raporu(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    sozlesme_id: int | None = None,
    musteri_id: int | None = None,
    kpi: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """PB işi listesi; `kpi=` ile KPI kutusunun AYNI süzgeci (sayı = liste).
    Süre kaydı yoksa `kisi_saat_dk` null ("eksik") döner — 0 yazılmaz."""
    f = _rapor_filtresi(user, baslangic, bitis, birim, sozlesme_id, musteri_id, kpi)
    if f.kpi and f.kpi not in bakim_raporlari.PB_KPILERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bu listede bilinmeyen KPI: {f.kpi}")
    stmt = bakim_raporlari.pb_isleri_sorgusu(user, f)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await bakim_raporlari.pb_satirlari(db, list(satirlar))


@router.get("/raporlar/uygunsuzluk")
async def uygunsuzluk_raporu(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    sozlesme_id: int | None = None,
    musteri_id: int | None = None,
) -> dict[str, Any]:
    """KPI adım 2 (E04-19): uygunsuzluk oranı, en sık 5 madde, açık aksiyon
    yaşı (kovalar), onaysız kapanış."""
    f = _rapor_filtresi(user, baslangic, bitis, birim, sozlesme_id, musteri_id, None)
    return await _cagir(bakim_raporlari.uygunsuzluk_analizi(db, user, clock, f))


def _iso_filtre(f: BakimRaporFiltresi) -> dict[str, Any]:
    return {
        k: (v.isoformat() if isinstance(v, date) else v)
        for k, v in f.__dict__.items()
        if v not in (None, "")
    }


@router.get("/raporlar/bakim.xlsx")
async def bakim_raporu_xlsx(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Aktarici,
    baslangic: date | None = None,
    bitis: date | None = None,
    birim: str | None = None,
    sozlesme_id: int | None = None,
    musteri_id: int | None = None,
) -> Response:
    """Bakım raporu kitabı (Dönem Tamamlama, Geciken, En Sık Uygunsuzluk, Açık
    Aksiyonlar, Tanımlar). Ekrandaki AYNI fonksiyonlar; kapsam dışı dönem yok;
    para kolonu yok. İndirme denetime yazılır (filtreler ISO)."""
    from app.services import export as export_svc

    f = _rapor_filtresi(user, baslangic, bitis, birim, sozlesme_id, musteri_id, None)
    sayfalar, toplam = await _cagir(bakim_raporlari.excel_sayfalari(db, user, clock, f))
    from app.services.teknik_servis import rapor_excel

    # Tek denetim yardımcısı (D3-A `rapor_excel`); kişisel sayfa yok.
    await rapor_excel.disa_aktarim_denetimi(
        db,
        user=user,
        ip=client_ip(request),
        rapor="bakim",
        filtreler=_iso_filtre(f),
        satir_sayisi=toplam,
        kapsam=user.role.scope if user.role is not None else "",
        kisisel_sayfalar=[],
    )
    await db.commit()
    icerik = await export_svc.sayfalari_xlsx_async(sayfalar)
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="bakim-raporu.xlsx"'},
    )


# =============================================================================
# Uygunsuzluk ve kapsam dışı listeleri
# =============================================================================


@router.get("/uygunsuzluklar")
async def uygunsuzluk_listesi(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: str | None = None,
    sorumlu_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    bagli = aliased(ServiceOrder)
    stmt = (
        select(MaintenanceNonconformity, ServiceOrder.so_no, bagli.so_no)
        .join(ServiceOrder, ServiceOrder.id == MaintenanceNonconformity.service_order_id)
        .outerjoin(bagli, bagli.id == MaintenanceNonconformity.linked_service_order_id)
        .where(MaintenanceNonconformity.is_deleted.is_(False))
    )
    stmt = kapsam.kapsam_isler(stmt, user, MaintenanceNonconformity.service_order_id)
    if durum:
        stmt = stmt.where(MaintenanceNonconformity.status == durum)
    if sorumlu_id is not None:
        stmt = stmt.where(MaintenanceNonconformity.responsible_user_id == sorumlu_id)
    stmt = stmt.order_by(MaintenanceNonconformity.id.desc())
    bugun = yerel_bugun(clock)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [
        {
            "id": n.id,
            "so_id": n.service_order_id,
            "so_no": so_no,
            "check_code": n.check_code,
            "check_label": n.check_label,
            "description": n.description,
            "action_type": n.action_type,
            "responsible_user_id": n.responsible_user_id,
            "due_date": n.due_date,
            "linked_service_order_id": n.linked_service_order_id,
            "linked_so_no": bagli_no,
            "status": n.status,
            "closing_note": n.closing_note,
            "yas_gun": (bugun - yerel_gun(n.created_at)).days,
            "version": n.version,
        }
        for n, so_no, bagli_no in satirlar
    ]


@router.get("/kapsam-disi")
async def kapsam_disi_listesi(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    durum: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    talep_eden = aliased(User)
    stmt = (
        select(MaintenanceExclusionRequest, ServiceOrder.so_no, talep_eden.full_name)
        .join(ServiceOrder, ServiceOrder.id == MaintenanceExclusionRequest.service_order_id)
        .join(talep_eden, talep_eden.id == MaintenanceExclusionRequest.requested_by)
        .where(MaintenanceExclusionRequest.is_deleted.is_(False))
    )
    stmt = kapsam.kapsam_isler(stmt, user, MaintenanceExclusionRequest.service_order_id)
    if durum:
        stmt = stmt.where(MaintenanceExclusionRequest.status == durum)
    stmt = stmt.order_by(MaintenanceExclusionRequest.id.desc())
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [
        {
            "id": t.id,
            "so_id": t.service_order_id,
            "so_no": so_no,
            "reason_code": t.reason_code,
            "description": t.description,
            "requested_by": t.requested_by,
            "talep_eden": ad,
            "kendi_talebi": t.requested_by == user.id,
            "status": t.status,
            "decided_by": t.decided_by,
            "decided_at": t.decided_at,
            "decision_note": t.decision_note,
            "created_at": t.created_at,
        }
        for t, so_no, ad in satirlar
    ]


# =============================================================================
# Dijital bakım formu (TS-064…068) — kayıt = PB servis işi (`so_id`)
# =============================================================================


async def _form_ciktisi(db, so: ServiceOrder) -> dict[str, Any]:
    form = await _cagir(bakim_formu.form_getir(db, so))
    musteri = await db.get(Account, so.customer_id) if so.customer_id else None
    tesis = await db.get(Address, so.address_id) if so.address_id else None
    kalem = await db.get(MaintenanceContractItem, so.contract_item_id)
    sozlesme = await db.get(MaintenanceContract, kalem.contract_id) if kalem else None
    donem = await db.get(MaintenancePeriod, so.maintenance_period_id)
    seri = await db.scalar(
        select(ServiceOrderSerial.seri_no)
        .where(ServiceOrderSerial.service_order_id == so.id, ServiceOrderSerial.is_active.is_(True))
        .order_by(ServiceOrderSerial.id.desc())
        .limit(1)
    )
    ekipman = await db.get(ServiceEquipment, so.equipment_id) if so.equipment_id else None
    onay = await bakim_formu.gecerli_onay(db, so.id)
    uygunsuzluklar = (
        await db.scalars(
            select(MaintenanceNonconformity)
            .where(
                MaintenanceNonconformity.service_order_id == so.id,
                MaintenanceNonconformity.is_deleted.is_(False),
            )
            .order_by(MaintenanceNonconformity.id)
        )
    ).all()
    talepler = (
        await db.scalars(
            select(MaintenanceExclusionRequest)
            .where(
                MaintenanceExclusionRequest.service_order_id == so.id,
                MaintenanceExclusionRequest.is_deleted.is_(False),
            )
            .order_by(MaintenanceExclusionRequest.id)
        )
    ).all()
    zorunlu = await ayar_svc.get(db, "servis_onay_zorunlu_turler") or []
    return {
        "so": {
            "id": so.id,
            "so_no": so.so_no,
            "status": so.status,
            "birim": so.birim,
            "konu": so.konu,
            "musteri": musteri.title if musteri else None,
            "tesis": (tesis.site_name or tesis.label) if tesis else None,
            "il": tesis.city if tesis else None,
            "ilce": tesis.district if tesis else None,
            "adres": tesis.line if tesis else None,
            "version": so.version,
        },
        "sozlesme": {"id": sozlesme.id, "contract_no": sozlesme.contract_no} if sozlesme else None,
        "donem": {
            "id": donem.id,
            "target_date": donem.target_date.isoformat(),
            "closing_kind": donem.closing_kind,
        }
        if donem
        else None,
        "ekipman": {
            "id": ekipman.id,
            "equipment_type": ekipman.equipment_type,
            "brand": ekipman.brand,
            "model": ekipman.model,
            "serial_no": ekipman.serial_no,
        }
        if ekipman
        else None,
        "form": {
            "id": form.id,
            "status": form.status,
            "template_code": form.template_code,
            "template_version": form.template_version,
            "baslik": "DİJİTAL TEKNİK SERVİS / PLANLI BAKIM FORMU",
            "seri_no": seri,
            "zone": form.zone,
            "performed_work": form.performed_work,
            "technician_note": form.technician_note,
            "parts_text": form.parts_text,
            "bakim_sonucu": form.bakim_sonucu,
            "kutuk_fark_durumu": form.kutuk_fark_durumu,
            "completed_at": form.completed_at,
            "completed_by": form.completed_by,
            "version": form.version,
        },
        "maddeler": [
            {
                "kod": m.check_code,
                "etiket": m.label,
                "sira": m.sira,
                "sonuc": m.result,
                "not": m.note,
                "checked_by": m.checked_by,
                "checked_at": m.checked_at,
            }
            for m in await bakim_formu.form_maddeleri(db, form.id)
        ],
        "ziyaretler": [
            bakim_formu.ziyaret_satiri(z) for z in await bakim_formu.ziyaretler(db, form.id)
        ],
        "uygunsuzluklar": [
            {
                "id": n.id,
                "check_code": n.check_code,
                "check_label": n.check_label,
                "description": n.description,
                "action_type": n.action_type,
                "responsible_user_id": n.responsible_user_id,
                "due_date": n.due_date,
                "linked_service_order_id": n.linked_service_order_id,
                "status": n.status,
                "closing_note": n.closing_note,
                "version": n.version,
            }
            for n in uygunsuzluklar
        ],
        "kapsam_disi": [
            {
                "id": t.id,
                "reason_code": t.reason_code,
                "description": t.description,
                "status": t.status,
                "requested_by": t.requested_by,
                "decision_note": t.decision_note,
            }
            for t in talepler
        ],
        # İmzalayan adı (kişisel veri) burada dönmez; yalnız onayın varlığı.
        "onay": {"id": onay.id, "tur": onay.tur, "approved_at": onay.approved_at} if onay else None,
        "onay_zorunlu": "PB" in zorunlu,
    }


def _form_girdisi(payload: FormIn) -> dict[str, Any]:
    govde = payload.model_dump(
        exclude_unset=True, exclude={"version", "kontroller", "sure_eksik_onay"}
    )
    if payload.kontroller:
        govde["kontroller"] = [
            {"kod": k.kod, "sonuc": k.sonuc, "not_": k.not_} for k in payload.kontroller
        ]
    return govde


@router.get("/formlar/{so_id}")
async def form_detay(so_id: int, db: DbDep, user: ServisOkuyucu) -> dict[str, Any]:
    so = await _pb(db, user, so_id)
    return await _form_ciktisi(db, so)


@router.put("/formlar/{so_id}")
async def form_kaydet(
    so_id: int, payload: FormIn, db: DbDep, clock: ClockDep, user: FormYazici
) -> dict[str, Any]:
    """Taslak kaydı; ziyaret kaydı OLUŞTURMAZ."""
    so = await _pb(db, user, so_id)
    form = await _cagir(bakim_formu.form_getir(db, so))
    _surum(form, payload.version)
    await _cagir(
        bakim_formu.form_kaydet(db, form, _form_girdisi(payload), so=so, user=user, clock=clock)
    )
    await db.commit()
    return await _form_ciktisi(db, so)


@router.post("/formlar/{so_id}/tamamla")
async def form_tamamla(
    so_id: int,
    db: DbDep,
    clock: ClockDep,
    user: FormTamamlayici,
    payload: FormIn | None = None,
) -> dict[str, Any]:
    """Doğrulama + ziyaret + (uygunsuzlukta aksiyon ve bekleme | PB TAMAMLANDI)."""
    so = await _pb(db, user, so_id)
    form = await _cagir(bakim_formu.form_getir(db, so))
    if payload is not None:
        _surum(form, payload.version)
        girdi = _form_girdisi(payload)
        if girdi:
            await _cagir(bakim_formu.form_kaydet(db, form, girdi, so=so, user=user, clock=clock))
    sonuc = await _cagir(
        bakim_formu.tamamla(
            db,
            form,
            so=so,
            user=user,
            clock=clock,
            sure_eksik_onay=bool(payload and payload.sure_eksik_onay),
        )
    )
    await db.commit()
    cikti = await _form_ciktisi(db, so)
    cikti["uyarilar"] = sonuc.uyarilar
    cikti["acilan_uygunsuzluk"] = sonuc.acilan_uygunsuzluklar
    return cikti


@router.post("/formlar/{so_id}/onay", status_code=status.HTTP_201_CREATED)
async def form_onay(
    so_id: int, payload: OnayIn, db: DbDep, clock: ClockDep, user: FormYazici
) -> dict[str, Any]:
    """Müşteri onayı — E01 onay servisine (`onay.onay_al`, D1-C) devreder."""
    from app.services.teknik_servis import onay as onay_svc

    so = await _pb(db, user, so_id)
    girdi = onay_svc.OnayGirdisi(**payload.model_dump())
    await _cagir(onay_svc.onay_al(db, so, girdi, user=user, clock=clock))
    await db.commit()
    return await _form_ciktisi(db, so)


@router.post("/formlar/{so_id}/kapsam-disi", status_code=status.HTTP_201_CREATED)
async def kapsam_disi_talep(
    so_id: int, payload: KapsamDisiIn, db: DbDep, clock: ClockDep, user: FormYazici
) -> dict[str, Any]:
    so = await _pb(db, user, so_id)
    await _cagir(
        bakim_formu.kapsam_disi_talep(
            db, so, payload.neden, payload.aciklama, user=user, clock=clock
        )
    )
    await db.commit()
    return await _form_ciktisi(db, so)


@router.post("/formlar/{so_id}/kapsam-disi/{talep_id}/karar")
async def kapsam_disi_karar(
    so_id: int, talep_id: int, payload: KararIn, db: DbDep, clock: ClockDep, user: Onaylayici
) -> dict[str, Any]:
    so = await _pb(db, user, so_id)
    talep = await db.get(MaintenanceExclusionRequest, talep_id)
    if talep is None or talep.is_deleted or talep.service_order_id != so.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kapsam dışı talebi bulunamadı")
    await _cagir(
        bakim_formu.kapsam_disi_karar(
            db, talep, payload.onay, not_=payload.not_, user=user, clock=clock
        )
    )
    await db.commit()
    return await _form_ciktisi(db, so)


async def _uygunsuzluk(db, so: ServiceOrder, uygunsuzluk_id: int) -> MaintenanceNonconformity:
    kayit = await db.get(MaintenanceNonconformity, uygunsuzluk_id)
    if kayit is None or kayit.is_deleted or kayit.service_order_id != so.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Uygunsuzluk kaydı bulunamadı")
    return kayit


@router.patch("/formlar/{so_id}/uygunsuzluklar/{uygunsuzluk_id}")
async def uygunsuzluk_duzenle(
    so_id: int,
    uygunsuzluk_id: int,
    payload: UygunsuzlukPatch,
    db: DbDep,
    clock: ClockDep,
    user: Onaylayici,
) -> dict[str, Any]:
    so = await _pb(db, user, so_id)
    kayit = await _uygunsuzluk(db, so, uygunsuzluk_id)
    govde = payload.model_dump(exclude_unset=True)
    _surum(kayit, govde.pop("version"))
    if govde.get("responsible_user_id") is not None and await kapsam.personel_disinda_mi(
        db, user, govde["responsible_user_id"]
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sorumlu personel bulunamadı")
    await _cagir(bakim_formu.uygunsuzluk_guncelle(db, kayit, govde, user=user, clock=clock))
    await db.commit()
    return await _form_ciktisi(db, so)


@router.post("/formlar/{so_id}/uygunsuzluklar/{uygunsuzluk_id}/ariza-isi")
async def uygunsuzluk_ariza_isi(
    so_id: int, uygunsuzluk_id: int, db: DbDep, clock: ClockDep, user: ArizaAcan
) -> dict[str, Any]:
    so = await _pb(db, user, so_id)
    kayit = await _uygunsuzluk(db, so, uygunsuzluk_id)
    ariza = await _cagir(bakim_formu.uygunsuzluk_ariza_isi(db, kayit, user=user, clock=clock))
    await db.commit()
    cikti = await _form_ciktisi(db, so)
    cikti["ariza_isi"] = {"id": ariza.id, "so_no": ariza.so_no}
    return cikti


@router.post("/formlar/{so_id}/uygunsuzluklar/{uygunsuzluk_id}/kapat")
async def uygunsuzluk_kapat(
    so_id: int,
    uygunsuzluk_id: int,
    payload: KapatIn,
    db: DbDep,
    clock: ClockDep,
    user: Onaylayici,
) -> dict[str, Any]:
    so = await _pb(db, user, so_id)
    kayit = await _uygunsuzluk(db, so, uygunsuzluk_id)
    await _cagir(bakim_formu.uygunsuzluk_kapat(db, kayit, payload.not_, user=user, clock=clock))
    await db.commit()
    return await _form_ciktisi(db, so)


# =============================================================================
# Ekipman kartının bakım geçmişi (E04-17)
# =============================================================================


@router.get("/ekipman/{ekipman_id}/bakim-gecmisi")
async def ekipman_bakim_gecmisi(
    ekipman_id: int, db: DbDep, user: ServisOkuyucu
) -> list[dict[str, Any]]:
    ekipman = await db.get(ServiceEquipment, ekipman_id)
    if (
        ekipman is None
        or ekipman.is_deleted
        or kapsam.birim_disinda_mi(user, ekipman.birim, birimsiz_gorunur=False)
        or await hesap_svc.kapsam_disinda_mi(db, user, ekipman.account_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ekipman bulunamadı")
    stmt = (
        select(MaintenanceVisit, ServiceOrder.so_no, MaintenancePeriod.target_date)
        .join(ServiceOrder, ServiceOrder.id == MaintenanceVisit.service_order_id)
        .join(MaintenancePeriod, MaintenancePeriod.id == ServiceOrder.maintenance_period_id)
        .where(ServiceOrder.equipment_id == ekipman.id, ServiceOrder.is_deleted.is_(False))
        .order_by(MaintenanceVisit.visited_at.desc())
    )
    stmt = kapsam.kapsam_isler(stmt, user, MaintenanceVisit.service_order_id)
    return [
        {**bakim_formu.ziyaret_satiri(z), "so_no": so_no, "hedef": hedef.isoformat()}
        for z, so_no, hedef in (await db.execute(stmt)).all()
    ]
