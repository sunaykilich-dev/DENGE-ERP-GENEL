"""Atölye uçları (TS-090…101).

**Adresleme:** atölye kaydı servis işiyle 1:1'dir (`uq_atolye_servis_isi`);
tek kayıt uçları kaydı SERVİS İŞİ kimliğiyle adresler (`/{so_id}`). Böylece
kapsam tek yerden (`kapsam.is_erisimi_yok_mu`) çözülür, ekran bağlantısı
(`/atolye/{so_id}`) servis işi ekranıyla aynı kimliği taşır ve uç taraması
(`test_router_kapsam_taramasi`) atölye uçlarını servis işi hedefiyle sınar.

İzinler (plan §1.3): `atolye.gor` okuma, `atolye.yaz` yazma; iptal ve geri
alma ayrıca `servis.kapat` (gövdede, 403); atama `atolye.yaz` + `servis.planla`;
Excel `atolye.gor` + `servis_rapor.disaaktar` (KD-06). `repair_amount` yalnız
`maliyet.gor`: yanıtta/Excel'de/PDF'te anahtar olarak YOK, gönderilen tutar
sessizce yok sayılır. Her `{so_id}` ucunda kapsam dışı → 404 ve hiçbir yazma
yapılmaz (kontrol yazmadan ÖNCE). Denetim izi commit'ten önce; servis katmanı
commit etmez.

Statik yollar (`/ozet`, `/disaaktar`, `/seri-gecmisi`, `/form-verileri`,
`/toplu-kabul`, `/toplu-ata`, `/kabul-grubu-fisi.pdf`) `/{so_id}`'den ÖNCE.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
    sayfala,
    sees_cost,
)
from app.models import (
    Account,
    ServiceEquipment,
    ServiceFaultReason,
    ServiceHoldReason,
    ServiceOrder,
    User,
    WorkshopRecord,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.servis_atolye import (
    AKSESUAR_TURLERI,
    ATOLYE_DURUMLARI,
    ATOLYE_GARANTI_DURUMLARI,
    ATOLYE_MARKALARI,
    ATOLYE_ONARIM_KATEGORILERI,
    ATOLYE_ONAY_KANALLARI,
    ATOLYE_ONAY_KARARLARI,
    ATOLYE_SERVIS_TURLERI,
    ATOLYE_TESLIM_TIPLERI,
    ATOLYE_TEST_SONUCLARI,
)
from app.models.servis_ekipman import EKIPMAN_TIPLERI
from app.models.teknik_servis import ONCELIKLER
from app.services import audit
from app.services import export as export_svc
from app.services.pdf import PdfUretilemedi
from app.services.teknik_servis import (
    atama,
    atolye,
    atolye_rapor,
    bekletme,
    gecmis,
    is_emirleri,
    kapsam,
    sonuc,
    zaman,
)
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teknik-servis/atolye", tags=["atolye"])

Okuyucu = Annotated[User, Depends(require_permission("atolye.gor"))]
Yazici = Annotated[User, Depends(require_permission("atolye.yaz"))]
# Kabul (tekli/toplu): atölye ustası (`atolye.yaz`) ya da yalnız kabul yetkili
# operasyon (`atolye.kabul`, rol testi B4). Teşhis/onarım/teslim Yazici'da kalır.
Kabulcu = Annotated[User, Depends(require_any_permission("atolye.yaz", "atolye.kabul"))]
Atayici = Annotated[User, Depends(require_permission("atolye.yaz", "servis.planla"))]
Aktarici = Annotated[User, Depends(require_permission("atolye.gor", "servis_rapor.disaaktar"))]

EXCEL_UST_SINIR = 20_000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TELSIZ_TIPLERI = ("TELSIZ", "ROLE_TEKRARLAYICI", "TELSIZ_DIGER")
# Rol testi tur 2 (B12): atölye kabulünde birime göre tip ve marka listesi.
TELSIZ_BIRIMLERI = frozenset({"HABERLESME", "POC"})
BIRIM_EKIPMAN_TIPLERI: dict[str, tuple[str, ...]] = {
    "HABERLESME": TELSIZ_TIPLERI,
    "POC": TELSIZ_TIPLERI,
    "GUVENLIK": ("XRAY", "KAPI_DEDEKTORU", "EL_DEDEKTORU", "DIGER_GUVENLIK", "DIGER"),
}


# --- Şemalar ---------------------------------------------------------------------------


class EkipmanIn(BaseModel):
    """Kabul edilen cihaz: kütükten `ekipman_id` ya da tip + marka + seri (bul-veya-aç)."""

    ekipman_id: int | None = None
    # None: kabul biriminin varsayılan tipi (`BIRIM_EKIPMAN_TIPLERI` ilk öğe).
    tip: Literal[EKIPMAN_TIPLERI] | None = None  # type: ignore[valid-type]
    # Telsiz birimlerinde (HABERLESME/POC) `ATOLYE_MARKALARI` sözlüğünden; diğer
    # birimlerde serbest metin (rol testi tur 2 B12: güvenlik cihazı kabulünde
    # yalnız telsiz markaları vardı).
    marka: str | None = Field(default=None, max_length=60)
    # Marka "DIGER" ise gerçek marka adı (kütükte serbest metin).
    marka_diger: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    seri: str | None = Field(default=None, max_length=200)
    warranty_start: date | None = None
    warranty_end: date | None = None
    mukerrer_gerekce: str | None = Field(default=None, max_length=300)


class AksesuarIn(BaseModel):
    kind: Literal[AKSESUAR_TURLERI]  # type: ignore[valid-type]
    qty: int = 1
    description: str | None = Field(default=None, max_length=120)


class KabulOrtakIn(BaseModel):
    # None: kullanıcının birimi (birincil birim ya da görebildiği tek birim; rol
    # testi tur 2 B12 — eskiden sabit HABERLESME'ydi). Belirsizse 400.
    birim: str | None = Field(default=None, min_length=1, max_length=20)
    customer_id: int
    address_id: int | None = None
    contact_id: int | None = None
    service_type: Literal[ATOLYE_SERVIS_TURLERI]  # type: ignore[valid-type]
    receive_type: Literal[ATOLYE_TESLIM_TIPLERI]  # type: ignore[valid-type]
    customer_complaint: str = Field(min_length=1, max_length=4000)
    oncelik: Literal[ONCELIKLER] = "NORMAL"  # type: ignore[valid-type]
    physical_condition: str | None = Field(default=None, max_length=2000)
    estimated_finish_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    logo_form_no: str | None = Field(default=None, max_length=80)
    logo_main_service_no: str | None = Field(default=None, max_length=80)
    integration_company: str | None = Field(default=None, max_length=150)
    project_name: str | None = Field(default=None, max_length=150)


class KabulIn(KabulOrtakIn):
    """Kabul. Gövdede `status` / `received_at` gelse de YOK SAYILIR (şemada yok)."""

    ekipman: EkipmanIn
    aksesuarlar: list[AksesuarIn] = Field(default_factory=list, max_length=50)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "customer_id": 1,
                    "service_type": "ARIZA_ONARIMI",
                    "receive_type": "ELDEN",
                    "customer_complaint": "Cihaz açılmıyor",
                    "ekipman": {"tip": "TELSIZ", "marka": "HYTERA", "model": "PD785", "seri": "1"},
                    "aksesuarlar": [{"kind": "BATARYA", "qty": 1}],
                }
            ]
        }
    }


class TopluCihazIn(EkipmanIn):
    aksesuarlar: list[AksesuarIn] = Field(default_factory=list, max_length=50)
    customer_complaint: str | None = Field(default=None, max_length=4000)


class TopluKabulIn(KabulOrtakIn):
    cihazlar: list[TopluCihazIn] = Field(min_length=1, max_length=atolye.TOPLU_KABUL_UST_SINIR)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "customer_id": 1,
                    "service_type": "ARIZA_ONARIMI",
                    "receive_type": "ELDEN",
                    "customer_complaint": "Toplu arıza",
                    "cihazlar": [{"tip": "TELSIZ", "marka": "HYTERA", "seri": "1"}],
                }
            ]
        }
    }


class KayitPatch(BaseModel):
    """Veri alanları düzeltme. `version` ZORUNLU. Durum ve sunucu zamanları bu uçtan
    değişmez (gönderilse de şemada olmadığı için yok sayılır)."""

    version: int
    customer_complaint: str | None = Field(default=None, max_length=4000)
    physical_condition: str | None = Field(default=None, max_length=2000)
    estimated_finish_date: date | None = None
    fault_reason_id: int | None = None
    diagnosis_note: str | None = Field(default=None, max_length=4000)
    is_repairable: bool | None = None
    repair_category: Literal[ATOLYE_ONARIM_KATEGORILERI] | None = None  # type: ignore[valid-type]
    repair_note: str | None = Field(default=None, max_length=4000)
    test_result: Literal[ATOLYE_TEST_SONUCLARI] | None = None  # type: ignore[valid-type]
    approval_decision: Literal[ATOLYE_ONAY_KARARLARI] | None = None  # type: ignore[valid-type]
    approval_channel: Literal[ATOLYE_ONAY_KANALLARI] | None = None  # type: ignore[valid-type]
    approved_by_name: str | None = Field(default=None, max_length=120)
    approval_note: str | None = Field(default=None, max_length=2000)
    repair_amount: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    external_vendor_id: int | None = None
    external_rma_no: str | None = Field(default=None, max_length=60)
    external_sent_at: date | None = None
    external_returned_at: date | None = None
    logo_form_no: str | None = Field(default=None, max_length=80)
    logo_main_service_no: str | None = Field(default=None, max_length=80)
    integration_company: str | None = Field(default=None, max_length=150)
    project_name: str | None = Field(default=None, max_length=150)
    notes: str | None = Field(default=None, max_length=4000)

    model_config = {"json_schema_extra": {"examples": [{"version": 1, "notes": "Not"}]}}


class AksesuarlarIn(BaseModel):
    version: int
    aksesuarlar: list[AksesuarIn] = Field(default_factory=list, max_length=50)

    model_config = {"json_schema_extra": {"examples": [{"version": 1, "aksesuarlar": []}]}}


class EkipmanDuzeltIn(BaseModel):
    marka: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    seri: str | None = Field(default=None, max_length=200)
    gerekce: str = Field(min_length=1, max_length=500)

    model_config = {
        "json_schema_extra": {"examples": [{"seri": "SN-2", "gerekce": "Seri yanlış girilmiş"}]}
    }


class AksesuarIadeIn(BaseModel):
    id: int
    returned: bool
    not_: str | None = Field(default=None, max_length=300, alias="not")

    model_config = {"populate_by_name": True}


class TeslimIn(BaseModel):
    teslim_alan: str | None = Field(default=None, max_length=120)
    teslim_tipi: Literal[ATOLYE_TESLIM_TIPLERI] | None = None  # type: ignore[valid-type]
    kargo_firmasi: str | None = Field(default=None, max_length=60)
    takip_no: str | None = Field(default=None, max_length=60)
    aksesuar_iade: list[AksesuarIadeIn] = Field(default_factory=list, max_length=50)
    aciklama: str | None = Field(default=None, max_length=2000)
    # KARARLAR 2026-11-20 §4: telsizde kargo/teslim öncesi okutulan seriler.
    okutulan_seriler: list[str] | None = Field(default=None, max_length=50)
    seri_aciklama: str | None = Field(default=None, max_length=500)


class DurumIn(BaseModel):
    hedef: Literal[ATOLYE_DURUMLARI]  # type: ignore[valid-type]
    gerekce: str | None = Field(default=None, max_length=500)
    # İki sekme yarışı: ekranın gördüğü durum değişmişse 409.
    beklenen_durum: Literal[ATOLYE_DURUMLARI] | None = None  # type: ignore[valid-type]
    teslim: TeslimIn | None = None
    sure_eksik_onay: bool = False

    model_config = {"json_schema_extra": {"examples": [{"hedef": "TESHISTE"}]}}


class AtamaSatiriIn(BaseModel):
    user_id: int
    rol: Literal["SEF", "TEKNISYEN"] = "TEKNISYEN"
    is_lead: bool = False


class AtaIn(BaseModel):
    atamalar: list[AtamaSatiriIn] = Field(default_factory=list, max_length=30)

    model_config = {"json_schema_extra": {"examples": [{"atamalar": []}]}}


class TopluAtaIn(BaseModel):
    so_idler: list[int] = Field(min_length=1, max_length=1000)
    atamalar: list[AtamaSatiriIn] = Field(default_factory=list, max_length=30)
    mod: Literal["EKLE", "DEGISTIR"] = "DEGISTIR"

    model_config = {"json_schema_extra": {"examples": [{"so_idler": [1], "atamalar": []}]}}


# --- Yardımcılar ----------------------------------------------------------------------------


def _hata(exc: Exception) -> HTTPException:
    """Servis hatasını HTTP'ye çevirir (alt sınıf önce)."""
    if isinstance(exc, atolye.AtolyeBulunamadi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc) or "Bulunamadı")
    if isinstance(exc, atolye.AtolyeYetkiHatasi | is_emirleri.IsEmriYetkiHatasi):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, atama.AtamaKapsamDisi | is_emirleri.IsEmriKapsamDisi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, atama.AtamaSinirHatasi):
        return HTTPException(422, str(exc))
    if isinstance(exc, ServisGirdiHatasi | gecmis.KisiselVeriHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, atolye.AtolyeHatasi) and exc.veri:
        return HTTPException(status.HTTP_409_CONFLICT, {"mesaj": exc.mesaj, **exc.veri})
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


_HATALAR = (
    ServisHatasi,
    ServisGirdiHatasi,
    atolye.AtolyeBulunamadi,
    atama.AtamaSinirHatasi,
    gecmis.KisiselVeriHatasi,
)


async def _kapsamli(db, user: User, so_id: int) -> tuple[ServiceOrder, WorkshopRecord]:
    try:
        return await atolye.kapsamli_kayit(db, user, so_id)
    except atolye.AtolyeBulunamadi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _marka(e: EkipmanIn, birim: str) -> str | None:
    marka = (e.marka or "").strip() or None
    if marka == "DIGER":
        if not (e.marka_diger or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "'Diğer' markada marka adı zorunlu")
        return e.marka_diger.strip()
    if marka is not None and birim in TELSIZ_BIRIMLERI and marka not in ATOLYE_MARKALARI:
        raise HTTPException(
            422,
            f"Bilinmeyen marka: {marka} (listede yoksa 'DIGER' seçip marka adını yazın)",
        )
    return marka


def _secim(e: EkipmanIn, birim: str) -> atolye.EkipmanSecimi:
    return atolye.EkipmanSecimi(
        ekipman_id=e.ekipman_id,
        tip=e.tip or BIRIM_EKIPMAN_TIPLERI.get(birim, ("DIGER",))[0],
        marka=_marka(e, birim) if e.ekipman_id is None else None,
        model=e.model,
        seri=e.seri,
        warranty_start=e.warranty_start,
        warranty_end=e.warranty_end,
        mukerrer_gerekce=e.mukerrer_gerekce,
    )


def _aksesuarlar(satirlar: list[AksesuarIn]) -> list[atolye.AksesuarGirdisi]:
    return [
        atolye.AksesuarGirdisi(kind=a.kind, qty=a.qty, description=a.description) for a in satirlar
    ]


def varsayilan_birim(user: User, birim: str | None) -> str:
    """Kabul/form birimi: verilen birim; yoksa kullanıcının birincil birimi (görebildiği
    birimlerdeyse), görebildiği tek birim ya da (geri uyum) HABERLESME. Belirsizse 400."""
    if birim:
        if birim not in BIRIM_KODLARI:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {birim}")
        return birim
    gorunur = kapsam.gorunur_birimler(user)
    if user.birincil_birim and user.birincil_birim in gorunur:
        return user.birincil_birim
    if len(gorunur) == 1:
        return gorunur[0]
    if "HABERLESME" in gorunur:
        return "HABERLESME"
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kabul birimini seçin")


def _ortak(p: KabulOrtakIn, birim: str) -> atolye.KabulGirdisi:
    return atolye.KabulGirdisi(
        customer_id=p.customer_id,
        service_type=p.service_type,
        receive_type=p.receive_type,
        customer_complaint=p.customer_complaint,
        birim=birim,
        address_id=p.address_id,
        contact_id=p.contact_id,
        oncelik=p.oncelik,
        physical_condition=p.physical_condition,
        estimated_finish_date=p.estimated_finish_date,
        notes=p.notes,
        logo_form_no=p.logo_form_no,
        logo_main_service_no=p.logo_main_service_no,
        integration_company=p.integration_company,
        project_name=p.project_name,
    )


def _filtre(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items() if k in atolye_rapor.FILTRE_ANAHTARLARI}


async def _adlar(db, kimlikler: set[int | None]) -> dict[int, str]:
    temiz = {k for k in kimlikler if k is not None}
    if not temiz:
        return {}
    return dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(temiz)))).all())


async def _detay(db, so: ServiceOrder, kayit: WorkshopRecord, user: User, clock) -> dict[str, Any]:
    """Tek kayıt çıktısı: kayıt + servis işi özeti + aksesuar + olaylar + parça/süre (salt
    okunur) + geçerli sonraki durumlar. `repair_amount` yalnız `maliyet.gor`."""
    await db.refresh(kayit)
    await db.refresh(so)
    gorur = sees_cost(user)
    (satir,) = await atolye_rapor.satirlar(db, [kayit], clock, maliyet_gorur=gorur)
    e = await db.get(ServiceEquipment, kayit.equipment_id)
    olaylar = await gecmis.gecmis_listesi(db, so)
    adlar = await _adlar(
        db,
        {o.user_id for o in olaylar} | {kayit.received_by, kayit.diagnosed_by, kayit.tested_by},
    )
    aktif = await bekletme.aktif_bekleme(db, so)
    bekleme = None
    if aktif is not None:
        neden = await db.scalar(
            select(ServiceHoldReason).where(ServiceHoldReason.kod == aktif.neden)
        )
        bekleme = {
            "neden": aktif.neden,
            "neden_adi": neden.ad if neden else aktif.neden,
            "started_at": aktif.started_at,
        }
    ozet = await zaman.sure_ozeti(db, so.id)
    tedarikci = (
        await db.get(Account, kayit.external_vendor_id) if kayit.external_vendor_id else None
    )
    gecerli = await sonuc.gecerli_sonuc(db, so)
    satir.update(
        {
            "customer_id": so.customer_id,
            "address_id": so.address_id,
            "contact_id": kayit.contact_id,
            "ekipman": {
                "id": e.id,
                "tip": e.equipment_type,
                "marka": e.brand,
                "model": e.model,
                "seri": e.serial_no,
                "warranty_start": e.warranty_start,
                "warranty_end": e.warranty_end,
            },
            "receive_type": kayit.receive_type,
            "received_by": {"id": kayit.received_by, "ad": adlar.get(kayit.received_by)},
            "customer_complaint": kayit.customer_complaint,
            "physical_condition": kayit.physical_condition,
            "warranty_end_snapshot": kayit.warranty_end_snapshot,
            "fault_reason_id": kayit.fault_reason_id,
            "diagnosis_note": kayit.diagnosis_note,
            "diagnosed_by": adlar.get(kayit.diagnosed_by),
            "diagnosed_at": kayit.diagnosed_at,
            "is_repairable": kayit.is_repairable,
            "repair_note": kayit.repair_note,
            "tested_by": adlar.get(kayit.tested_by),
            "tested_at": kayit.tested_at,
            "approval_decision": kayit.approval_decision,
            "approval_channel": kayit.approval_channel,
            "approved_by_name": kayit.approved_by_name,
            "approval_at": kayit.approval_at,
            "approval_note": kayit.approval_note,
            "delivery_type": kayit.delivery_type,
            "cargo_company": kayit.cargo_company,
            "cargo_tracking_no": kayit.cargo_tracking_no,
            "cargo_sent_at": kayit.cargo_sent_at,
            "delivered_to_name": kayit.delivered_to_name,
            "delivery_note": kayit.delivery_note,
            "external_vendor": (
                {"id": tedarikci.id, "title": tedarikci.title} if tedarikci else None
            ),
            "external_rma_no": kayit.external_rma_no,
            "external_sent_at": kayit.external_sent_at,
            "external_returned_at": kayit.external_returned_at,
            "logo_form_no": kayit.logo_form_no,
            "logo_main_service_no": kayit.logo_main_service_no,
            "integration_company": kayit.integration_company,
            "project_name": kayit.project_name,
            "notes": kayit.notes,
            "rental_asset_id": kayit.rental_asset_id,
            "aksesuarlar": [
                {
                    "id": a.id,
                    "kind": a.kind,
                    "description": a.description,
                    "qty": a.qty,
                    "returned": a.returned,
                    "return_note": a.return_note,
                }
                for a in await atolye.aksesuarlar(db, kayit)
            ],
            "bekleme": bekleme,
            "sonuc": (
                {"sonuc": gecerli.sonuc, "cozum_kanali": gecerli.cozum_kanali} if gecerli else None
            ),
            "olaylar": [
                {
                    "id": o.id,
                    "olay_turu": o.olay_turu,
                    "alt_tur": (o.veri or {}).get("alt_tur"),
                    "ozet": o.ozet,
                    "kullanici": adlar.get(o.user_id),
                    "zaman": o.olusma_zamani,
                }
                for o in olaylar
            ],
            "parcalar": await atolye.parcalar(db, so, maliyet_gorur=gorur),
            "sure": {
                "kisi_saat_dk": ozet.kisi_saat_dk,
                "sure_durumu": ozet.sure_durumu,
                "sure_eksik": ozet.sure_eksik,
                "mola_dk": ozet.mola_dk,
                "faaliyet_kirilimi": ozet.faaliyet_kirilimi,
                "acik_bolum_sayisi": ozet.acik_bolum_sayisi,
            },
            "teklifler": await atolye.teklifler(db, so),
            "tekrar_gelis": (
                await atolye.son_onarim(db, kayit.equipment_id, clock, haric_id=kayit.id)
            )
            is not None,
            "sonraki_durumlar": await atolye.sonraki_durumlar(db, so, kayit, user),
            "updated_at": kayit.updated_at,
        }
    )
    return satir


# --- Liste, özet, Excel ------------------------------------------------------------------


@router.get("", response_model=None)
async def liste(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    durum: Annotated[list[str] | None, Query()] = None,
    durum_grubu: str | None = None,
    birim: str | None = None,
    teknisyen_id: int | None = None,
    marka: str | None = Query(default=None, max_length=60),
    servis_turu: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    yas: str | None = None,
    geciken: bool = False,
    kabul_grubu: int | None = None,
    musteri_id: int | None = None,
    teslim_alinmayan: bool = False,
    dis_servis: bool = False,
    tedarikci_id: int | None = None,
    sure_eksik: bool = False,
    tamamlanma_bas: date | None = None,
    tamamlanma_bit: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Sunucu süzgeçli ve sayfalı liste (`X-Toplam-Kayit`); kapsam SQL'de."""
    f = _filtre(**locals())
    try:
        stmt = atolye_rapor.filtreli_sorgu(
            user, f, clock, teslim_esik_gun=await atolye_rapor.teslim_esigi(db)
        )
    except ServisGirdiHatasi as exc:
        raise _hata(exc) from exc
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await atolye_rapor.satirlar(
        db, [r[0] for r in satirlar], clock, maliyet_gorur=sees_cost(user)
    )


@router.get("/ozet", response_model=None)
async def ozet(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    birim: str | None = None,
    teknisyen_id: int | None = None,
    marka: str | None = Query(default=None, max_length=60),
    servis_turu: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    kabul_grubu: int | None = None,
    musteri_id: int | None = None,
) -> list[dict[str, Any]]:
    """Tıklanabilir KPI kutuları: sayı, kutunun açtığı listeyle AYNI sorgudan."""
    try:
        return await atolye_rapor.ozet(db, user, _filtre(**locals()), clock)
    except ServisGirdiHatasi as exc:
        raise _hata(exc) from exc


@router.get("/disaaktar")
async def disaaktar(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Aktarici,
    durum: Annotated[list[str] | None, Query()] = None,
    durum_grubu: str | None = None,
    birim: str | None = None,
    teknisyen_id: int | None = None,
    marka: str | None = Query(default=None, max_length=60),
    servis_turu: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    yas: str | None = None,
    geciken: bool = False,
    kabul_grubu: int | None = None,
    musteri_id: int | None = None,
    teslim_alinmayan: bool = False,
    dis_servis: bool = False,
    tedarikci_id: int | None = None,
    sure_eksik: bool = False,
    tamamlanma_bas: date | None = None,
    tamamlanma_bit: date | None = None,
) -> Response:
    """Ekrandaki süzgecin AYNISIYLA Excel. Tamir bedeli sütunu yalnız `maliyet.gor`."""
    f = _filtre(**locals())
    try:
        stmt = atolye_rapor.filtreli_sorgu(
            user, f, clock, teslim_esik_gun=await atolye_rapor.teslim_esigi(db)
        )
    except ServisGirdiHatasi as exc:
        raise _hata(exc) from exc
    toplam = await atolye_rapor.say(db, stmt)
    if toplam > EXCEL_UST_SINIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{toplam} kayıt var; Excel en çok {EXCEL_UST_SINIR} satır alır, süzgeci daraltın",
        )
    kayitlar = list((await db.scalars(stmt)).all())
    gorur = sees_cost(user)
    satirlar = await atolye_rapor.satirlar(db, kayitlar, clock, maliyet_gorur=gorur)
    icerik = await export_svc.sayfalari_xlsx_async(
        [
            export_svc.Sayfa(
                "Atölye",
                atolye_rapor.excel_sutunlari(gorur),
                [atolye_rapor.excel_satiri(s, maliyet_gorur=gorur) for s in satirlar],
            )
        ]
    )
    await audit.log(
        db,
        "workshop_records",
        "atolye.disa_aktar",
        new_value={"satir": len(satirlar), "q": q, "durum": durum},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return Response(
        content=icerik,
        media_type=XLSX,
        headers={
            "Content-Disposition": 'attachment; filename="atolye.xlsx"',
            "X-Toplam-Kayit": str(len(satirlar)),
        },
    )


# --- KPI raporu (TS-194) ------------------------------------------------------------------

Raporcu = Annotated[User, Depends(require_permission("atolye.gor", "servis_rapor.gor"))]
RaporAktarici = Annotated[
    User,
    Depends(require_permission("atolye.gor", "servis_rapor.gor", "servis_rapor.disaaktar")),
]


@router.get("/raporlar/kpi", response_model=None)
async def kpi_raporu(
    db: DbDep,
    clock: ClockDep,
    user: Raporcu,
    bas: date | None = None,
    bit: date | None = None,
    birim: str | None = None,
    servis_turu: str | None = None,
    marka: str | None = Query(default=None, max_length=60),
    teknisyen_id: int | None = None,
    musteri_id: int | None = None,
    tedarikci_id: int | None = None,
) -> dict[str, Any]:
    """Çevrim / dış servis / işçilik KPI'ları; dönem = ilk teslime hazır anı (Türkiye
    günü). Tarih sırası ya da 24 ayı aşan dönem 400; bilinmeyen süzgeç değeri 400."""
    f = _filtre(**locals())
    try:
        return await atolye_rapor.kpi_raporu(db, user, f, clock, bas=bas, bit=bit)
    except ServisGirdiHatasi as exc:
        raise _hata(exc) from exc


@router.get("/raporlar/kpi.xlsx")
async def kpi_raporu_xlsx(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: RaporAktarici,
    bas: date | None = None,
    bit: date | None = None,
    birim: str | None = None,
    servis_turu: str | None = None,
    marka: str | None = Query(default=None, max_length=60),
    teknisyen_id: int | None = None,
    musteri_id: int | None = None,
    tedarikci_id: int | None = None,
) -> Response:
    """KPI raporunun Excel'i (göstergeler, servis türü kırılımı, dönem kayıtları).
    Fiyat sütunu yok; denetim satırı süzgeçleri ISO biçiminde taşır."""
    f = _filtre(**locals())
    try:
        rapor = await atolye_rapor.kpi_raporu(db, user, f, clock, bas=bas, bit=bit)
        donem = rapor["donem"]
        kayitlar = await atolye_rapor.donem_satirlari(
            db, user, f, clock, bas=donem["bas"], bit=donem["bit"]
        )
    except ServisGirdiHatasi as exc:
        raise _hata(exc) from exc
    if len(kayitlar) > EXCEL_UST_SINIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{len(kayitlar)} kayıt var; Excel en çok {EXCEL_UST_SINIR} satır alır",
        )
    icerik = await export_svc.sayfalari_xlsx_async(
        atolye_rapor.kpi_excel_sayfalari(rapor, kayitlar)
    )
    await audit.log(
        db,
        "workshop_records",
        "atolye.kpi_disa_aktar",
        new_value={
            "bas": donem["bas"].isoformat(),
            "bit": donem["bit"].isoformat(),
            "filtre": {k: v for k, v in f.items() if v not in (None, False, "", [])},
            "satir": len(kayitlar),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return Response(
        content=icerik,
        media_type=XLSX,
        headers={
            "Content-Disposition": 'attachment; filename="atolye-kpi.xlsx"',
            "X-Toplam-Kayit": str(len(kayitlar)),
        },
    )


@router.get("/seri-gecmisi", response_model=None)
async def seri_gecmisi(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    ekipman_id: int | None = None,
    tip: str | None = None,
    marka: str | None = Query(default=None, max_length=60),
    seri: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    """Aynı cihazın önceki kayıtları + tekrar geliş uyarısı (kapsam içi)."""
    try:
        return await atolye.seri_gecmisi(
            db, user, clock, ekipman_id=ekipman_id, tip=tip, marka=marka, seri=seri
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/form-verileri", response_model=None)
async def form_verileri(db: DbDep, user: Okuyucu, birim: str | None = None) -> dict[str, Any]:
    """Sözlükler + birimin arıza nedeni kataloğu (tek kaynak: model sabitleri).

    Rol testi tur 2 (B12): `birim` verilmezse kullanıcının birimi (kabul ile aynı
    kural, yanıtta `birim`); marka ve ekipman tipi listesi birime göre: telsiz
    birimlerinde marka sözlüğü, diğerlerinde birimin kütüğündeki markalar + DIGER."""
    birim = varsayilan_birim(user, birim)
    if birim in TELSIZ_BIRIMLERI:
        markalar = list(ATOLYE_MARKALARI)
    else:
        kutuk = (
            await db.scalars(
                select(ServiceEquipment.brand)
                .where(
                    ServiceEquipment.birim == birim,
                    ServiceEquipment.is_deleted.is_(False),
                    ServiceEquipment.brand.is_not(None),
                )
                .group_by(ServiceEquipment.brand)
                .order_by(func.count().desc(), ServiceEquipment.brand)
                .limit(50)
            )
        ).all()
        markalar = [m for m in kutuk if m and m != "DIGER"] + ["DIGER"]
    nedenler = (
        await db.scalars(
            select(ServiceFaultReason)
            .where(ServiceFaultReason.birim == birim, ServiceFaultReason.is_active.is_(True))
            .order_by(ServiceFaultReason.sira, ServiceFaultReason.ad)
        )
    ).all()
    return {
        "durumlar": [{"kod": d, "ad": atolye_rapor.DURUM_ADLARI[d]} for d in ATOLYE_DURUMLARI],
        "servis_turleri": [
            {"kod": t, "ad": atolye_rapor.SERVIS_TURU_ADLARI[t]} for t in ATOLYE_SERVIS_TURLERI
        ],
        "birim": birim,
        "markalar": markalar,
        "ekipman_tipleri": list(BIRIM_EKIPMAN_TIPLERI.get(birim, ("DIGER",))),
        "teslim_tipleri": [
            {"kod": t, "ad": atolye.TESLIM_TIPI_ADLARI[t]} for t in ATOLYE_TESLIM_TIPLERI
        ],
        "aksesuar_turleri": [{"kod": t, "ad": atolye.AKSESUAR_ADLARI[t]} for t in AKSESUAR_TURLERI],
        "onarim_kategorileri": [
            {"kod": t, "ad": atolye.ONARIM_ADLARI[t]} for t in ATOLYE_ONARIM_KATEGORILERI
        ],
        "test_sonuclari": list(ATOLYE_TEST_SONUCLARI),
        "onay_kararlari": list(ATOLYE_ONAY_KARARLARI),
        "onay_kanallari": list(ATOLYE_ONAY_KANALLARI),
        "garanti_durumlari": [
            {"kod": g, "ad": atolye_rapor.GARANTI_ADLARI[g]} for g in ATOLYE_GARANTI_DURUMLARI
        ],
        "ariza_nedenleri": [{"id": n.id, "ad": n.ad} for n in nedenler],
        "yas_kovalari": list(atolye_rapor.YAS_KOVALARI),
    }


# --- Kabul (TS-090/096/097/100) ---------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
async def kabul(
    payload: KabulIn, request: Request, db: DbDep, clock: ClockDep, user: Kabulcu
) -> dict[str, Any]:
    """Cihaz kabulü: servis işi (ATOLYE) + atölye kaydı + aksesuarlar tek transaction."""
    birim = varsayilan_birim(user, payload.birim)
    veri = _ortak(payload, birim)
    veri.ekipman = _secim(payload.ekipman, birim)
    veri.aksesuarlar = _aksesuarlar(payload.aksesuarlar)
    try:
        kayit = await atolye.kabul(db, veri, user=user, clock=clock, ip=client_ip(request))
    except _HATALAR as exc:
        raise _hata(exc) from exc
    so = await db.get(ServiceOrder, kayit.service_order_id)
    await db.commit()
    return await _detay(db, so, kayit, user, clock)


@router.post("/toplu-kabul", status_code=status.HTTP_201_CREATED, response_model=None)
async def toplu_kabul(
    payload: TopluKabulIn, request: Request, db: DbDep, clock: ClockDep, user: Kabulcu
) -> dict[str, Any]:
    """N cihaz → N kayıt + N servis işi, ortak kabul grubu; hepsi ya da hiçbiri."""
    birim = varsayilan_birim(user, payload.birim)
    ortak = _ortak(payload, birim)
    cihazlar = [
        (_secim(c, birim), _aksesuarlar(c.aksesuarlar), c.customer_complaint)
        for c in payload.cihazlar
    ]
    try:
        kayitlar = await atolye.toplu_kabul(
            db, ortak, cihazlar, user=user, clock=clock, ip=client_ip(request)
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    satirlar = await atolye_rapor.satirlar(db, kayitlar, clock, maliyet_gorur=sees_cost(user))
    return {"kabul_grubu": kayitlar[0].intake_group_no, "kayitlar": satirlar}


@router.post("/toplu-ata", response_model=None)
async def toplu_ata(
    payload: TopluAtaIn, db: DbDep, clock: ClockDep, user: Atayici
) -> dict[str, Any]:
    """Seçili kayıtların servis işlerine aynı ekip (E01 tek atama kaynağı); hepsi ya da hiçbiri."""
    try:
        isler = await atolye.toplu_ata(
            db,
            payload.so_idler,
            [atama.AtamaSatiri(a.user_id, a.rol, a.is_lead) for a in payload.atamalar],
            mod=payload.mod,
            user=user,
            clock=clock,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"guncellenen": len(isler)}


@router.get("/kabul-grubu-fisi.pdf")
async def kabul_grubu_fisi(db: DbDep, user: Okuyucu, grup_no: int) -> Response:
    """Toplu kabulün tek fişi (yalnız kapsam içi kayıtlar; hiçbiri yoksa 404)."""
    stmt = (
        select(WorkshopRecord)
        .where(WorkshopRecord.intake_group_no == grup_no, WorkshopRecord.is_deleted.is_(False))
        .order_by(WorkshopRecord.id)
    )
    stmt = kapsam.kapsam_isler(stmt, user, WorkshopRecord.service_order_id)
    kayitlar = list((await db.scalars(stmt)).all())
    if not kayitlar:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kabul grubu bulunamadı")
    baglam = atolye.grup_fisi_baglami([await atolye.belge_verisi(db, k) for k in kayitlar])
    return await _pdf("atolye_kabul_fisi.html", baglam, f"kabul-grubu-{grup_no}.pdf")


async def _pdf(sablon: str, baglam: dict[str, Any], dosya: str) -> Response:
    from app.services.pdf import pdf_uret_async

    try:
        icerik = await pdf_uret_async(sablon, **baglam)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{dosya}"'},
    )


# --- Tek kayıt ----------------------------------------------------------------------------


@router.get("/{so_id}", response_model=None)
async def detay(so_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> dict[str, Any]:
    so, kayit = await _kapsamli(db, user, so_id)
    return await _detay(db, so, kayit, user, clock)


@router.patch("/{so_id}", response_model=None)
async def guncelle(
    so_id: int, payload: KayitPatch, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Teşhis/onarım/test/onay/dış servis/genel alanlar; `version` uyuşmazlığı 409.
    `repair_amount` `maliyet.gor` olmadan DOLU gönderilirse 403 (rol testi tur 2
    B11; bakım ücreti kuralıyla aynı — eskiden sessizce yok sayılıyordu)."""
    so, kayit = await _kapsamli(db, user, so_id)
    degisiklik = payload.model_dump(exclude_unset=True)
    degisiklik.pop("version", None)
    if degisiklik.get("repair_amount") is not None and not sees_cost(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Tamir bedeli alanı için yetkiniz yok (maliyet.gor)"
        )
    try:
        await atolye.guncelle(
            db,
            kayit,
            so,
            degisiklik,
            version=payload.version,
            user=user,
            clock=clock,
            maliyet_gorur=sees_cost(user),
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, kayit, user, clock)


@router.put("/{so_id}/aksesuarlar", response_model=None)
async def aksesuarlar(
    so_id: int,
    payload: AksesuarlarIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict[str, Any]:
    """Aksesuar listesinin tamamını değiştirir; teslimden sonra 409."""
    so, kayit = await _kapsamli(db, user, so_id)
    try:
        await atolye.aksesuarlari_yaz(
            db,
            kayit,
            so,
            _aksesuarlar(payload.aksesuarlar),
            version=payload.version,
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, kayit, user, clock)


@router.put("/{so_id}/ekipman", response_model=None)
async def ekipman_duzelt(
    so_id: int,
    payload: EkipmanDuzeltIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict[str, Any]:
    """Seri/marka/model düzeltmesi tek kaynakta (kütük + işin seri satırı) + olay."""
    so, kayit = await _kapsamli(db, user, so_id)
    try:
        await atolye.ekipman_duzelt(
            db,
            kayit,
            so,
            marka=payload.marka,
            model=payload.model,
            seri=payload.seri,
            gerekce=payload.gerekce,
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, kayit, user, clock)


@router.post("/{so_id}/durum", response_model=None)
async def durum(
    so_id: int, payload: DurumIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Tek atölye durum ucu. Yanıt: güncel detay + `uyarilar` (ör. eksik aksesuar)."""
    so, kayit = await _kapsamli(db, user, so_id)
    if payload.beklenen_durum is not None and kayit.status != payload.beklenen_durum:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Kaydın durumu başka bir kullanıcı tarafından değiştirildi; yenileyin",
        )
    teslim = None
    if payload.teslim is not None:
        teslim = atolye.TeslimGirdisi(
            teslim_alan=payload.teslim.teslim_alan,
            teslim_tipi=payload.teslim.teslim_tipi,
            kargo_firmasi=payload.teslim.kargo_firmasi,
            takip_no=payload.teslim.takip_no,
            aksesuar_iade=[
                atolye.AksesuarIadesi(id=a.id, returned=a.returned, not_=a.not_)
                for a in payload.teslim.aksesuar_iade
            ],
            aciklama=payload.teslim.aciklama,
            okutulan_seriler=payload.teslim.okutulan_seriler,
            seri_aciklama=payload.teslim.seri_aciklama,
        )
    try:
        uyarilar = await atolye.durum_degistir(
            db,
            kayit,
            payload.hedef,
            user=user,
            clock=clock,
            gerekce=payload.gerekce,
            teslim=teslim,
            sure_eksik_onay=payload.sure_eksik_onay,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    cikti = await _detay(db, so, kayit, user, clock)
    cikti["uyarilar"] = uyarilar
    return cikti


@router.post("/{so_id}/ata", response_model=None)
async def ata(
    so_id: int, payload: AtaIn, db: DbDep, clock: ClockDep, user: Atayici
) -> dict[str, Any]:
    """Servis işinin ekibi (E01 `atama.ata`; atölye kaydı atama alanı tutmaz)."""
    so, kayit = await _kapsamli(db, user, so_id)
    try:
        await atolye.ata(
            db,
            so,
            [atama.AtamaSatiri(a.user_id, a.rol, a.is_lead) for a in payload.atamalar],
            user=user,
            clock=clock,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "workshop_records",
        "atolye.ata",
        entity_id=kayit.id,
        new_value={"ekip": [a.user_id for a in payload.atamalar]},
        user_id=user.id,
    )
    await db.commit()
    return await _detay(db, so, kayit, user, clock)


@router.get("/{so_id}/kabul-fisi.pdf")
async def kabul_fisi(so_id: int, db: DbDep, user: Okuyucu) -> Response:
    """Kabul fişi (tamir bedeli yalnız `maliyet.gor`; imzalı tarama `IMZA` eki olarak)."""
    _, kayit = await _kapsamli(db, user, so_id)
    baglam = atolye.kabul_fisi_baglami(
        await atolye.belge_verisi(db, kayit), goster_bedel=sees_cost(user)
    )
    return await _pdf("atolye_kabul_fisi.html", baglam, f"{kayit.atolye_no}-kabul.pdf")


@router.get("/{so_id}/teslim-tutanagi.pdf")
async def teslim_tutanagi(so_id: int, db: DbDep, user: Okuyucu) -> Response:
    """Teslim tutanağı (aynı tutar kuralı)."""
    _, kayit = await _kapsamli(db, user, so_id)
    baglam = atolye.teslim_tutanagi_baglami(
        await atolye.belge_verisi(db, kayit), goster_bedel=sees_cost(user)
    )
    return await _pdf("atolye_teslim_tutanagi.html", baglam, f"{kayit.atolye_no}-teslim.pdf")
