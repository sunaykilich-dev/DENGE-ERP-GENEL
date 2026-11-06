"""Servis işleri, panel, tanımlar (arıza/bekleme nedenleri) uçları (TS-020…037).

- Okuma `servis.gor`; açılış, not, saha durumu, bekleme, seri, bağlı yeni
  iş `servis.yaz`; sonuç `servis.tamamla`; kapat/iptal `servis.kapat`;
  kalite onayı `servis.kalite_onay`. Kapanmış iş YENİDEN AÇILMAZ (M1.7):
  eski `yeniden-ac` ucu 409 ile "bağlı yeni iş"e yönlendirir. Atama ve
  toplu atama `servis.planla`; açılışta çözüldü `servis.yaz` +
  `servis.uzaktan_coz`; arıza nedeni kataloğu `servis.tanim`; bekleme nedeni
  kataloğu `operasyon.yonet`; Excel `servis.gor` + `servis_rapor.disaaktar`
  (KD-06: servis rollerine `rapor.disaaktar` verilmez).
- Kapsam: liste SQL'de (`kapsam.kapsam_isler`), tek kayıt `_kapsamli_is` ile
  — kapsam dışı iş 404 ve HİÇBİR yazma yapılmaz (kapsam yazmadan ÖNCE
  çözülür; `test_router_kapsam_taramasi` her `{so_id}` ucunu tarar).
- Telefon: `servis.yaz` ya da `servis.irtibat_gor` olmayana `kvkk.maskele`
  ile maskeli döner (liste, detay, Excel — K11).
- Hata kodları: kural 409, girdi 400, izin 403, kapsam/yok 404, toplu sınır
  422. Servis katmanı commit etmez; denetim izi commit'ten ÖNCE yazılır.
- Panel/onay/PDF uçları D1-C'nin servis fonksiyonlarına (`s/panel.py`,
  `s/onay.py`) devreder; uç ve kapsam burada, iş kuralı orada.

Statik yollar (`/isler/form-verileri`, `/isler/toplu-atama` ...) `{so_id}`
yollarından ÖNCE tanımlanır.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
    sayfala,
)
from app.api.search import AramaSonucu, arayici_kaydet
from app.models import (
    ServiceApproval,
    ServiceFaultReason,
    ServiceHoldReason,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceResult,
    User,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import (
    COZUM_KANALLARI,
    DURUM_GRUPLARI,
    ONCELIKLER,
    SERVIS_DURUMLARI,
    SERVIS_SONUCLARI,
    TALEP_KANALLARI,
)
from app.models.teknik_servis import durum_grubu as durum_grubu_hesapla
from app.permissions import BIRIMLER
from app.services import audit, kvkk, sirketler
from app.services import export as export_svc
from app.services.accounts import kapsam_disinda_mi as hesap_kapsam_disinda_mi
from app.services.pdf import PdfUretilemedi
from app.services.teknik_servis import (
    atama,
    bekletme,
    cihaz_bilgisi,
    gecmis,
    is_emirleri,
    kapsam,
    role_montaj,
    sonuc,
)
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teknik-servis", tags=["teknik-servis"])

Okuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
Yazici = Annotated[User, Depends(require_permission("servis.yaz"))]
# İş açılışı: `servis.yaz` (her tür) ya da yalnız KURULUM açan satış destek
# (`servis.kurulum_ac`, rol testi B3); tür kuralı `_acilis_on_kontrol`'de.
IsAcici = Annotated[User, Depends(require_any_permission("servis.yaz", "servis.kurulum_ac"))]
# Sözlük (form verileri): servis ekranları ve Servis Maliyet raporu (Finans,
# `maliyet.gor`; rol testi 2/B-07) — yalnız katalog, kayıt yok.
SozlukOkuyucu = Annotated[User, Depends(require_any_permission("servis.gor", "maliyet.gor"))]
Tamamlayici = Annotated[User, Depends(require_permission("servis.tamamla"))]
Kapatici = Annotated[User, Depends(require_permission("servis.kapat"))]
Planlayici = Annotated[User, Depends(require_permission("servis.planla"))]
KaliteOnaylayici = Annotated[User, Depends(require_permission("servis.gor", "servis.kalite_onay"))]
UzaktanCozucu = Annotated[User, Depends(require_permission("servis.yaz", "servis.uzaktan_coz"))]
Aktarici = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.disaaktar"))]
Tanimci = Annotated[User, Depends(require_permission("servis.tanim"))]
BeklemeTanimci = Annotated[User, Depends(require_permission("operasyon.yonet"))]

EXCEL_UST_SINIR = 20_000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --- Şemalar ------------------------------------------------------------------------


class IsAcIn(BaseModel):
    """Ekrandan servis işi açılışı (E01-02/09). Sözlük doğrulaması serviste (400)."""

    birim: str = Field(min_length=1, max_length=20)
    tur: str = Field(min_length=1, max_length=20)
    konu: str = Field(min_length=1, max_length=200)
    customer_id: int
    address_id: int | None = None
    contact_id: int | None = None
    oncelik: str = Field(default="NORMAL", max_length=10)
    talep_kanali: str | None = Field(default=None, max_length=20)
    reported_at: datetime | None = None
    iletisim_ad: str | None = Field(default=None, max_length=120)
    iletisim_telefon: str | None = Field(default=None, max_length=20)
    proje: str | None = Field(default=None, max_length=120)
    sistem: str | None = Field(default=None, max_length=120)
    aciklama: str | None = Field(default=None, max_length=4000)
    seriler: list[str] = Field(default_factory=list, max_length=50)
    iliskili_is_id: int | None = None
    iliski_turu: str | None = Field(default=None, max_length=20)
    # Açık işte aynı seri varsa 409; kullanıcı uyarıyı görüp geçerse true.
    mukerrer_gec: bool = False
    # Geçiş/içe aktarma kaydı (rol testi B5; `servis.gecis_kaydi`): asıl
    # bildirim tarihi 7 günden eski olabilir, SLA ölçülmez (`sla_kaynak=GECIS`).
    # Haberleşme saha işinde zorunlu, çoktan seçmeli (KARARLAR §10).
    nitelikler: list[str] | None = Field(default=None, max_length=8)
    gecis_kaydi: bool = False
    gecis_gerekcesi: str | None = Field(default=None, max_length=500)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "birim": "GUVENLIK",
                    "tur": "ARIZA",
                    "konu": "Kamera görüntü vermiyor",
                    "customer_id": 1,
                    "talep_kanali": "TELEFON",
                    "iletisim_ad": "Saha Yetkilisi",
                }
            ]
        }
    }


class UzaktanIn(IsAcIn):
    """Açılışta telefonla/uzaktan çözüldü (TS-024): açılış + sonuç tek istekte."""

    cozum_kanali: Literal["TELEFON", "UZAKTAN"]
    yapilan_islem: str = Field(min_length=1, max_length=4000)
    ariza_nedeni_id: int | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "birim": "GUVENLIK",
                    "tur": "DESTEK",
                    "konu": "Parola sıfırlama",
                    "customer_id": 1,
                    "talep_kanali": "TELEFON",
                    "iletisim_ad": "Saha Yetkilisi",
                    "cozum_kanali": "TELEFON",
                    "yapilan_islem": "Telefonla yönlendirildi",
                }
            ]
        }
    }


class IsPatch(BaseModel):
    """Temel bilgi düzeltme (TS-031). `version` ZORUNLU (iyimser kilit)."""

    version: int
    gerekce: str | None = Field(default=None, max_length=500)
    konu: str | None = Field(default=None, max_length=200)
    aciklama: str | None = Field(default=None, max_length=4000)
    oncelik: str | None = Field(default=None, max_length=10)
    tur: str | None = Field(default=None, max_length=20)
    # Yalnız `servis.kapat` + gerekçe (E01-16); PB/PLANLI_BAKIM 409.
    kategori: str | None = Field(default=None, max_length=20)
    proje: str | None = Field(default=None, max_length=120)
    sistem: str | None = Field(default=None, max_length=120)
    nitelikler: list[str] | None = Field(default=None, max_length=8)
    talep_kanali: str | None = Field(default=None, max_length=20)
    reported_at: datetime | None = None
    iletisim_ad: str | None = Field(default=None, max_length=120)
    iletisim_telefon: str | None = Field(default=None, max_length=20)
    customer_id: int | None = None
    address_id: int | None = None
    contact_id: int | None = None
    birim: str | None = Field(default=None, max_length=20)

    model_config = {"json_schema_extra": {"examples": [{"version": 1, "konu": "Düzeltilmiş konu"}]}}


class SerilerIn(BaseModel):
    seriler: list[str] = Field(default_factory=list, max_length=50)
    gerekce: str | None = Field(default=None, max_length=500)

    model_config = {"json_schema_extra": {"examples": [{"seriler": ["SN-1"]}]}}


class BagliIsIn(BaseModel):
    """Kapanmış işe bağlı yeni iş (M1.7). Verilmeyen alan önceki işten
    kopyalanır (müşteri, lokasyon, irtibat, cihaz, konu); açılış kuralları
    (talep eden kişi + telefon, lokasyon, tek cihaz) aynen uygulanır."""

    konu: str | None = Field(default=None, max_length=200)
    aciklama: str | None = Field(default=None, max_length=4000)
    tur: str | None = Field(default=None, max_length=20)
    oncelik: str | None = Field(default=None, max_length=10)
    talep_kanali: str | None = Field(default=None, max_length=20)
    reported_at: datetime | None = None
    iletisim_ad: str | None = Field(default=None, max_length=120)
    iletisim_telefon: str | None = Field(default=None, max_length=20)
    address_id: int | None = None
    contact_id: int | None = None
    # None = önceki işin aktif serileri; [] = cihazsız.
    seriler: list[str] | None = Field(default=None, max_length=50)
    mukerrer_gec: bool = False
    # Rol testi tur 2 (5_teknisyen B8): bağın türü (iliskili_is_id = önceki iş).
    # Verilmezse yalnız `onceki_is_id` bağı kurulur (eski davranış).
    iliski_turu: Literal["TEKRAR_ARIZA", "BAKIM_BULGUSU", "DEVAM"] | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "konu": "Arıza tekrarladı",
                    "talep_kanali": "TELEFON",
                    "iliski_turu": "TEKRAR_ARIZA",
                }
            ]
        }
    }


class KaliteOnayIn(BaseModel):
    version: int
    not_: str | None = Field(default=None, max_length=500, alias="not")

    model_config = {"populate_by_name": True, "json_schema_extra": {"examples": [{"version": 1}]}}


class KaliteRedIn(BaseModel):
    """Kalite reddi (rol testi tur 2): gerekçe ≥10 karakter; `hedef` ISLEMDE
    (kayıt/sonuç düzeltmesi) ya da PLANLAMADA (yeniden ziyaret, varsayılan)."""

    version: int
    gerekce: str = Field(max_length=500)
    hedef: Literal["ISLEMDE", "PLANLAMADA"] = "PLANLAMADA"

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"version": 3, "gerekce": "Etiket eksik, fotoğraf yok", "hedef": "ISLEMDE"}
            ]
        }
    }


class KaliteTopluSatir(BaseModel):
    id: int
    version: int


class KaliteTopluIn(BaseModel):
    """Toplu kalite onayı: her iş kendi `version`'ıyla (iyimser kilit)."""

    isler: list[KaliteTopluSatir] = Field(min_length=1, max_length=200)
    not_: str | None = Field(default=None, max_length=500, alias="not")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {"examples": [{"isler": [{"id": 1, "version": 4}]}]},
    }


class YolaCikisGeriAlIn(BaseModel):
    """Yönetici yola çıkışı geri alır (YOLA_CIKILDI → PLANLANDI); gerekçe ≥10."""

    version: int
    gerekce: str = Field(min_length=10, max_length=500)

    model_config = {
        "json_schema_extra": {"examples": [{"version": 5, "gerekce": "Yanlış işe basıldı"}]}
    }


class IliskiIn(BaseModel):
    iliskili_is_id: int | None = None
    iliski_turu: Literal["MUKERRER", "TEKRAR_ARIZA", "DEVAM"] | None = None

    model_config = {"json_schema_extra": {"examples": [{"iliskili_is_id": None}]}}


class DurumIn(BaseModel):
    """Genel saha durumu (PLANLAMADA/YOLA_CIKILDI/SAHADA/ISLEMDE/ATOLYEDE).

    Diğer hedefler kendi uçlarındadır: PLANLANDI planlama, BEKLEMEDE bekleme,
    TAMAMLANDI sonuç, KAPATILDI/IPTAL kapat/iptal (400). TEKRAR_ACILDI'ya
    hiçbir uçtan geçilmez (M1.7).
    """

    hedef: Literal[SERVIS_DURUMLARI]  # type: ignore[valid-type]
    beklenen_durum: Literal[SERVIS_DURUMLARI] | None = None  # type: ignore[valid-type]
    gerekce: str | None = Field(default=None, max_length=500)

    model_config = {"json_schema_extra": {"examples": [{"hedef": "ISLEMDE"}]}}


class KapatIn(BaseModel):
    beklenen_durum: Literal[SERVIS_DURUMLARI] | None = None  # type: ignore[valid-type]
    gerekce: str | None = Field(default=None, max_length=500)

    model_config = {"json_schema_extra": {"examples": [{}]}}


class GerekceIn(BaseModel):
    gerekce: str = Field(min_length=3, max_length=500)
    beklenen_durum: Literal[SERVIS_DURUMLARI] | None = None  # type: ignore[valid-type]

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "Müşteri vazgeçti"}]}}


class BeklemeIn(BaseModel):
    neden: str = Field(min_length=1, max_length=30)
    aciklama: str | None = Field(default=None, max_length=500)
    beklenen_bitis_at: datetime | None = None

    model_config = {"json_schema_extra": {"examples": [{"neden": "MALZEME"}]}}


class BeklemeBitirIn(BaseModel):
    not_: str | None = Field(default=None, max_length=200, alias="not")

    model_config = {"populate_by_name": True, "json_schema_extra": {"examples": [{}]}}


class SonucIn(BaseModel):
    sonuc: Literal[SERVIS_SONUCLARI]  # type: ignore[valid-type]
    cozum_kanali: Literal[COZUM_KANALLARI]  # type: ignore[valid-type]
    yapilan_islem: str = Field(min_length=1, max_length=4000)
    ariza_nedeni_id: int | None = None
    saha_seri_no: str | None = Field(default=None, max_length=200)
    saha_bolge: str | None = Field(default=None, max_length=120)
    sure_eksik_onay: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"sonuc": "COZULDU", "cozum_kanali": "YERINDE", "yapilan_islem": "Kablo yenilendi"}
            ]
        }
    }


class NotIn(BaseModel):
    metin: str = Field(min_length=1, max_length=500)

    model_config = {"json_schema_extra": {"examples": [{"metin": "Müşteri aranacak"}]}}


class AtamaSatiriIn(BaseModel):
    user_id: int
    rol: Literal["SEF", "TEKNISYEN"] = "TEKNISYEN"
    is_lead: bool = False


class AtamaIn(BaseModel):
    atamalar: list[AtamaSatiriIn] = Field(default_factory=list, max_length=30)

    model_config = {"json_schema_extra": {"examples": [{"atamalar": []}]}}


class TopluAtamaIn(BaseModel):
    is_idler: list[int] = Field(min_length=1, max_length=1000)
    atamalar: list[AtamaSatiriIn] = Field(default_factory=list, max_length=30)
    mod: Literal["EKLE", "DEGISTIR"] = "DEGISTIR"


class ArizaNedeniIn(BaseModel):
    """Arıza nedeni ekle (`id` yok) / güncelle (`id` + `version`)."""

    id: int | None = None
    birim: str = Field(min_length=1, max_length=20)
    ad: str = Field(min_length=1, max_length=80)
    sira: int = Field(default=0, ge=0, le=999)
    is_active: bool = True
    version: int | None = None


class BeklemeNedeniIn(BaseModel):
    """Bekleme nedeni ekle/güncelle (kod anahtar; var olanda `version`)."""

    kod: str = Field(min_length=2, max_length=30)
    ad: str = Field(min_length=1, max_length=80)
    sla_durdurur: bool = False
    aciklama_zorunlu: bool = False
    sira: int = Field(default=0, ge=0, le=999)
    is_active: bool = True
    version: int | None = None


class OnayIn(BaseModel):
    tur: Literal["IMZA", "SOZLU", "BASILI_FORM", "ALINAMADI"]
    imzalayan_ad: str | None = Field(default=None, max_length=120)
    imzalayan_unvan: str | None = Field(default=None, max_length=80)
    ek_id: int | None = None
    eksik_nedeni: str | None = Field(default=None, max_length=300)

    model_config = {
        "json_schema_extra": {"examples": [{"tur": "ALINAMADI", "eksik_nedeni": "Yetkili yok"}]}
    }


class ZiyaretOnayIn(OnayIn):
    is_idler: list[int] = Field(min_length=1, max_length=100)


class EkipmandanIsIn(BaseModel):
    """Kütükten toplu "Servis işi aç" (E03-11 toplu işlem): seçili her ekipman
    için bir iş. Birim/müşteri/lokasyon/seri/irtibat ekipmandan gelir."""

    ekipman_idler: list[int] = Field(min_length=1, max_length=1000)
    tur: str = Field(default="ARIZA", min_length=1, max_length=20)
    konu: str = Field(min_length=1, max_length=200)
    talep_kanali: str = Field(min_length=1, max_length=20)
    oncelik: str = Field(default="NORMAL", max_length=10)
    aciklama: str | None = Field(default=None, max_length=4000)
    reported_at: datetime | None = None
    # Ekipmanın kayıtlı irtibatı yoksa kullanılır (talep eden kişi).
    iletisim_ad: str | None = Field(default=None, max_length=120)
    iletisim_telefon: str | None = Field(default=None, max_length=20)
    mukerrer_gec: bool = False
    # Geçiş/içe aktarma kaydı (KARARLAR 2026-11-05 §9.8): `servis.gecis_kaydi` +
    # gerekçe; kaynakta talep eden yoksa ad/telefon aranmaz, SLA ölçülmez.
    gecis_kaydi: bool = False
    gecis_gerekcesi: str | None = Field(default=None, max_length=500)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ekipman_idler": [1],
                    "konu": "Yıllık kontrol talebi",
                    "talep_kanali": "TELEFON",
                    "iletisim_ad": "Saha Yetkilisi",
                }
            ]
        }
    }


# --- Yardımcılar ----------------------------------------------------------------------


def _hata(exc: Exception) -> HTTPException:
    """Servis hatalarını HTTP koduna çevirir (00 §1.4; alt sınıf önce)."""
    if isinstance(exc, is_emirleri.IsEmriYetkiHatasi):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, is_emirleri.IsEmriKapsamDisi | atama.AtamaKapsamDisi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, atama.AtamaSinirHatasi):
        return HTTPException(422, str(exc))
    if isinstance(exc, ServisGirdiHatasi | gecmis.KisiselVeriHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, ServisHatasi):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


_HATALAR = (ServisHatasi, ServisGirdiHatasi, atama.AtamaSinirHatasi, gecmis.KisiselVeriHatasi)


def _hazir_degil(exc: NotImplementedError) -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"Bu işlev henüz hazır değil ({exc})")


async def _kapsamli_is(db, so_id: int, user: User) -> ServiceOrder:
    """İşi KAPSAM SÜZGECİ uygulanarak getirir; yoksa 404 (yazmadan önce)."""
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    return so


def _irtibat_tam(user: User) -> bool:
    return user.has("servis.yaz") or user.has("servis.irtibat_gor")


def _telefon(user: User, deger: str | None) -> str | None:
    return deger if _irtibat_tam(user) else kvkk.maskele(deger)


def _beklenen(so: ServiceOrder, beklenen: str | None) -> None:
    if beklenen is not None and so.status != beklenen:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"İşin durumu değişmiş ({is_emirleri.DURUM_ADLARI[so.status]}); sayfayı yenileyin",
        )


async def _kisi_adlari(db, kimlikler: set[int]) -> dict[int, str]:
    kimlikler = {k for k in kimlikler if k is not None}
    if not kimlikler:
        return {}
    satirlar = await db.execute(select(User.id, User.full_name).where(User.id.in_(kimlikler)))
    return dict(satirlar.all())


async def _ekipler(db, so_idler: list[int]) -> dict[int, list[ServiceOrderAssignment]]:
    sonuc: dict[int, list[ServiceOrderAssignment]] = {i: [] for i in so_idler}
    if not so_idler:
        return sonuc
    for a in (
        await db.scalars(
            select(ServiceOrderAssignment)
            .where(
                ServiceOrderAssignment.service_order_id.in_(so_idler),
                ServiceOrderAssignment.removed_at.is_(None),
            )
            .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id)
        )
    ).all():
        sonuc[a.service_order_id].append(a)
    return sonuc


async def _satirlar(db, sos: list[ServiceOrder], user: User) -> list[dict[str, Any]]:
    """Liste satırları (toplu sorgularla)."""
    idler = [s.id for s in sos]
    musteriler = await is_emirleri.musteri_ozetleri(
        db, {s.customer_id for s in sos if s.customer_id}
    )
    lokasyonlar = await is_emirleri.lokasyon_ozetleri(
        db, {s.address_id for s in sos if s.address_id}
    )
    ekipler = await _ekipler(db, idler)
    adlar = await _kisi_adlari(db, {a.user_id for e in ekipler.values() for a in e})
    beklemeler = await is_emirleri.aktif_bekleme_nedenleri(db, idler)
    satirlar = []
    for s in sos:
        ekip = ekipler.get(s.id, [])
        sorumlu = next((a for a in ekip if a.is_lead), None)
        satirlar.append(
            {
                "id": s.id,
                "so_no": s.so_no,
                "birim": s.birim,
                "tur": s.tur,
                "kategori": s.kategori,
                "status": s.status,
                "durum_grubu": durum_grubu_hesapla(s.status),
                "oncelik": s.oncelik,
                "musteri": musteriler.get(s.customer_id) if s.customer_id else None,
                "customer_name_raw": s.customer_name_raw,
                "lokasyon": lokasyonlar.get(s.address_id) if s.address_id else None,
                "konu": s.konu,
                "seriler": [x.seri_no for x in s.seriler if x.is_active],
                "talep_kanali": s.talep_kanali,
                "reported_at": s.reported_at,
                "created_at": s.created_at,
                "completed_at": s.completed_at,
                "closed_at": s.closed_at,
                "sorumlu": (
                    {"id": sorumlu.user_id, "ad": adlar.get(sorumlu.user_id)} if sorumlu else None
                ),
                "ekip_sayisi": len(ekip),
                "iletisim_ad": s.iletisim_ad,
                "iletisim_telefon": _telefon(user, s.iletisim_telefon),
                "aktif_bekleme": beklemeler.get(s.id),
                "reopen_count": s.reopen_count,
                "onceki_is_id": s.onceki_is_id,
                "kalite_onay_at": s.kalite_onay_at,
                "version": s.version,
            }
        )
    return satirlar


async def _detay(db, so: ServiceOrder, user: User, clock) -> dict[str, Any]:
    """Tek iş çıktısı (gömülü müşteri/lokasyon/irtibat — teknisyende `hesap.gor` yok)."""
    from app.models import Contact

    await db.refresh(so)
    (satir,) = await _satirlar(db, [so], user)
    ekip = await atama.aktif_ekip(db, so)
    kisiler = await db.execute(
        select(User.id, User.full_name, User.giris_acik).where(
            User.id.in_({a.user_id for a in ekip} or {0})
        )
    )
    kisi_harita = {i: (ad, giris) for i, ad, giris in kisiler.all()}
    irtibat = None
    if so.contact_id is not None:
        kisi = await db.get(Contact, so.contact_id)
        if kisi is not None:
            irtibat = {
                "id": kisi.id,
                "full_name": kisi.full_name,
                "unvan": kisi.title,
                "telefon": _telefon(user, kisi.phone),
            }
    aktif = await bekletme.aktif_bekleme(db, so)
    bekleme = None
    if aktif is not None:
        neden = await db.scalar(
            select(ServiceHoldReason).where(ServiceHoldReason.kod == aktif.neden)
        )
        bekleme = {
            "id": aktif.id,
            "neden": aktif.neden,
            "neden_adi": neden.ad if neden else aktif.neden,
            "aciklama": aktif.aciklama,
            "onceki_durum": aktif.onceki_durum,
            "started_at": aktif.started_at,
            "beklenen_bitis_at": aktif.beklenen_bitis_at,
            "sla_durdurur": aktif.sla_durdurur,
        }
    gecerli = await sonuc.gecerli_sonuc(db, so)
    sonuc_cikti = None
    if gecerli is not None:
        neden_adi = None
        if gecerli.ariza_nedeni_id is not None:
            ariza = await db.get(ServiceFaultReason, gecerli.ariza_nedeni_id)
            neden_adi = ariza.ad if ariza else None
        sonuc_cikti = {
            "id": gecerli.id,
            "sonuc": gecerli.sonuc,
            "cozum_kanali": gecerli.cozum_kanali,
            "yapilan_islem": gecerli.yapilan_islem,
            "ariza_nedeni_id": gecerli.ariza_nedeni_id,
            "ariza_nedeni": neden_adi,
            "saha_seri_no": gecerli.saha_seri_no,
            "saha_bolge": gecerli.saha_bolge,
            "created_at": gecerli.created_at,
        }
    bekleme_dk = await bekletme.toplam_bekleme_dk(db, [so.id], clock)
    satir.update(
        {
            "address_id": so.address_id,
            "customer_id": so.customer_id,
            "contact_id": so.contact_id,
            "irtibat": irtibat,
            "proje": so.proje,
            "sistem": so.sistem,
            "nitelikler": so.nitelikler,
            "nitelik_sorulur": role_montaj.nitelik_sorulur_mu(so.birim, so.tur),
            "role_montaj_eksik": await role_montaj.eksikler(db, so),
            "cihaz_bilgisi_kurali": cihaz_bilgisi.kural(so),
            "cihaz_bilgisi_eksik": await cihaz_bilgisi.eksikler(db, so),
            "aciklama": so.aciklama,
            "seriler": [
                {"id": x.id, "seri_no": x.seri_no, "seri_norm": x.seri_norm}
                for x in await is_emirleri.aktif_seriler(db, so)
            ],
            "ekip": [
                {
                    "user_id": a.user_id,
                    "ad": kisi_harita.get(a.user_id, ("?", True))[0],
                    "giris_acik": kisi_harita.get(a.user_id, ("?", True))[1],
                    "rol": a.rol,
                    "is_lead": a.is_lead,
                    "assigned_at": a.assigned_at,
                }
                for a in ekip
            ],
            "bekleme": bekleme,
            "bekleme_dk_toplam": bekleme_dk.get(so.id, 0),
            "sonuc": sonuc_cikti,
            "first_completed_at": so.first_completed_at,
            "cancelled_at": so.cancelled_at,
            "cancel_reason": so.cancel_reason,
            "equipment_id": so.equipment_id,
            "iliskili_isler": await is_emirleri.bagli_isler(db, user, so),
            "kalite": await is_emirleri.kalite_durumu(db, so, user),
            "sure_durumu": await _sure_durumu(db, so),
            "sonraki_durumlar": is_emirleri.sonraki_durumlar(so),
            "gecisler": is_emirleri.gecis_secenekleri(so, user),
            "updated_at": so.updated_at,
        }
    )
    return satir


async def _sure_durumu(db, so: ServiceOrder) -> str:
    """Süre özeti durumu (TAM/KISMI/EKSIK/BEKLENMIYOR) — kapanmış işte
    "süre eksik" işareti için (M1.10/M9.4: kayıt yoksa EKSIK, 0 değil)."""
    from app.services.teknik_servis import zaman

    return (await zaman.sure_ozeti(db, so.id)).sure_durumu


def _girdi(payload: IsAcIn) -> is_emirleri.ServisIsiGirdisi:
    return is_emirleri.ServisIsiGirdisi(
        birim=payload.birim,
        tur=payload.tur,
        konu=payload.konu,
        customer_id=payload.customer_id,
        address_id=payload.address_id,
        contact_id=payload.contact_id,
        oncelik=payload.oncelik,
        talep_kanali=payload.talep_kanali,
        reported_at=payload.reported_at,
        iletisim_ad=payload.iletisim_ad,
        iletisim_telefon=payload.iletisim_telefon,
        proje=payload.proje,
        sistem=payload.sistem,
        aciklama=payload.aciklama,
        seriler=list(payload.seriler),
        iliskili_is_id=payload.iliskili_is_id,
        iliski_turu=payload.iliski_turu,
        gecis_kaydi=payload.gecis_kaydi,
        nitelikler=payload.nitelikler,
        nitelik_zorunlu=True,
    )


GECIS_GEREKCE_ALT = 10


def _acilis_yetkisi(payload: IsAcIn, user: User) -> None:
    """Tür ve geçiş kaydı yetkisi (rol testi B3/B5).

    `servis.yaz` olmayan (yalnız `servis.kurulum_ac`) kullanıcı yalnız KURULUM
    açar. Geçiş kaydı `servis.gecis_kaydi` ve gerekçe ister: SLA ölçülmediği
    için gerekçesiz/izinsiz kullanılırsa SLA'dan kaçış yolu olurdu.
    """
    if not user.has("servis.yaz") and payload.tur != "KURULUM":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Yalnız Kurulum işi açabilirsiniz (servis.kurulum_ac)",
        )
    _gecis_dogrula(payload.gecis_kaydi, payload.gecis_gerekcesi, user)


def _gecis_dogrula(gecis: bool, gerekce: str | None, user: User) -> None:
    if not gecis:
        return
    if not user.has("servis.gecis_kaydi"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Geçiş kaydı için yetkiniz yok (servis.gecis_kaydi)"
        )
    if len((gerekce or "").strip()) < GECIS_GEREKCE_ALT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Geçiş kaydında gerekçe zorunlu (en az {GECIS_GEREKCE_ALT} karakter)",
        )


async def _talep_bilgisi_dogrula(
    db,
    address_id: int | None,
    contact_id: int | None,
    iletisim_ad: str | None,
    iletisim_telefon: str | None,
    *,
    gecis: bool = False,
) -> None:
    """M1.2 (Faz A): ekrandan açılan işte lokasyon ve talep eden kişinin adı
    + telefonu zorunlu. Ad/telefon elle girilir ya da seçilen irtibat
    kişisinin kaydından gelir. PB ve sistem açılışları (bakım üretimi,
    atölye kabulü, kiralama, bakım bulgusu) bu kapıdan geçmez.

    Geçiş kaydında (`servis.gecis_kaydi` + gerekçe; KARARLAR 2026-11-05 §9.8)
    kaynak listede talep eden kişi yoksa ad/telefon aranmaz; lokasyon yine
    zorunludur. Kişi sahada/ilk aramada işin irtibatına girilir."""
    from app.models import Contact

    eksik = []
    if address_id is None:
        eksik.append("lokasyon")
    kisi = await db.get(Contact, contact_id) if contact_id is not None else None
    ad = (iletisim_ad or "").strip() or (kisi.full_name if kisi is not None else "")
    telefon = (iletisim_telefon or "").strip() or ((kisi.phone or "") if kisi is not None else "")
    if not gecis and not (ad or "").strip():
        eksik.append("talep eden kişinin adı")
    if not gecis and not telefon.strip():
        eksik.append("talep eden kişinin telefonu")
    if eksik:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Zorunlu alan eksik: " + ", ".join(eksik))


async def _acilis_on_kontrol(db, payload: IsAcIn, user: User) -> list[dict[str, Any]]:
    """Ekran açılışının ortak kuralları (TS-020/029). Uyarı listesini döner.

    Kapsam: hedef birim kullanıcının birimlerinde olmalı (TUMU her birime
    açar) → aksi 404; müşteri temsilcisinin kapsamı dışındaki hesap 404.
    """
    _acilis_yetkisi(payload, user)
    if payload.birim not in BIRIM_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {payload.birim}")
    # Şirket ayrımı (KARARLAR 2026-11-04 §1): birim etkin şirketin değilse 403 +
    # makine okunur kod (birim bilinen bir katalog öğesi; gizlemenin anlamı yok).
    # Kapsam kontrolünden ÖNCE: TUMU yönetici de yanlış şirkette iş açamaz.
    if not sirketler.birim_etkin_sirkette_mi(user, payload.birim):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"kod": "SIRKET_DISI_BIRIM", "mesaj": sirketler.sirket_disi_mesaji(user)},
        )
    if kapsam.birim_disinda_mi(user, payload.birim, birimsiz_gorunur=False):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Birim bulunamadı")
    if payload.tur not in is_emirleri.TUR_KURALLARI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bilinmeyen servis işi türü: {payload.tur}"
        )
    if is_emirleri.TUR_KURALLARI[payload.tur].yalniz_sistem:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{is_emirleri.TUR_ADLARI[payload.tur]}' işi bu ekrandan açılamaz",
        )
    if payload.talep_kanali is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Talep kanalı zorunlu")
    if payload.talep_kanali not in TALEP_KANALLARI or payload.talep_kanali == "BAKIM_OTOMATIK":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Geçersiz talep kanalı: {payload.talep_kanali}"
        )
    if await hesap_kapsam_disinda_mi(db, user, payload.customer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Müşteri bulunamadı")
    await _talep_bilgisi_dogrula(
        db,
        payload.address_id,
        payload.contact_id,
        payload.iletisim_ad,
        payload.iletisim_telefon,
        gecis=payload.gecis_kaydi,
    )
    if (
        payload.iliski_turu is not None
        and payload.iliski_turu not in is_emirleri.EKRAN_ILISKI_TURLERI
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bu ilişki türü ekrandan seçilemez")
    try:
        mukerrer, kapsam_disi = await is_emirleri.mukerrer_adaylari(db, user, payload.seriler)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    if (mukerrer or kapsam_disi) and not payload.mukerrer_gec:
        mesaj = "Aynı seri numarasıyla açık servis işi var"
        if mukerrer:
            mesaj += ": " + ", ".join(m["so_no"] for m in mukerrer)
        elif kapsam_disi:
            mesaj += " (başka birimde açık kayıt var)"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "kod": "MUKERRER",
                "mesaj": mesaj,
                "mevcut_isler": mukerrer,
                "kapsam_disi_var": kapsam_disi,
            },
        )
    uyarilar = []
    for m in mukerrer:
        uyarilar.append({"kod": "MUKERRER_GECILDI", "so_no": m["so_no"], "id": m["id"]})
    # Aynı lokasyondaki açık işler TEK uyarıda toplanır (rol testi B9): 1 cihaz
    # = 1 iş kuralıyla aynı tesiste 6 bakım açılırken 6. işte 5 ayrı uyarı
    # çıkıyordu. `so_no`/`id` ilk iş (geri uyum); hepsi `isler`'de.
    ayni = await is_emirleri.ayni_lokasyon_acik_isler(
        db, user, payload.customer_id, payload.address_id
    )
    if ayni:
        uyarilar.append(
            {
                "kod": "AYNI_LOKASYON",
                "so_no": ayni[0]["so_no"],
                "id": ayni[0]["id"],
                "adet": len(ayni),
                "isler": [{"id": a["id"], "so_no": a["so_no"]} for a in ayni],
            }
        )
    return uyarilar


async def _acilis_denetimi(db, so: ServiceOrder, user: User, request: Request, eylem: str) -> None:
    await audit.log(
        db,
        "service_orders",
        eylem,
        entity_id=so.id,
        new_value={"so_no": so.so_no, "birim": so.birim, "tur": so.tur, "status": so.status},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=bool(so.iletisim_ad or so.iletisim_telefon),
    )


# --- Form verileri, mükerrer kontrolü ------------------------------------------------


@router.get("/isler/kutuk-cihazlari", response_model=None)
async def kutuk_cihazlari(
    db: DbDep,
    user: Okuyucu,
    birim: str = Query(max_length=20),
    musteri_id: int = Query(),
    adres_id: int | None = None,
) -> list[dict[str, Any]]:
    """İş açma formu: müşterinin (tesisin) kütükteki cihazları ve kayıtlı
    frekansları (KARARLAR §12). Kapsam ekipman listesiyle aynı."""
    return await cihaz_bilgisi.musteri_cihazlari(
        db, user, birim=birim, musteri_id=musteri_id, adres_id=adres_id
    )


@router.get("/isler/form-verileri", response_model=None)
async def form_verileri(db: DbDep, user: SozlukOkuyucu) -> dict[str, Any]:
    """Açılış/filtre formu sözlükleri (tek kaynak: model tuple'ları ve kataloglar)."""
    # TUMU: etkin şirketin bütün birimleri; diğerleri kendi birimleri (kesişim).
    birimler = kapsam.gorunur_birimler(user)
    nedenler = await bekletme.neden_katalogu(db)
    return {
        "birimler": [{"kod": b, "ad": BIRIMLER[b]} for b in birimler],
        "turler": [
            {
                "kod": t,
                "ad": is_emirleri.TUR_ADLARI[t],
                "kategori": k.kategori,
                "seri_zorunlu": k.seri_zorunlu,
                "ekrandan": not k.yalniz_sistem,
            }
            for t, k in is_emirleri.TUR_KURALLARI.items()
        ],
        "kategoriler": [{"kod": k, "ad": a} for k, a in is_emirleri.KATEGORI_ADLARI.items()],
        "durumlar": [{"kod": d, "ad": is_emirleri.DURUM_ADLARI[d]} for d in SERVIS_DURUMLARI],
        "durum_gruplari": {g: sorted(v) for g, v in DURUM_GRUPLARI.items()},
        "oncelikler": list(ONCELIKLER),
        "talep_kanallari": [{"kod": k, "ad": a} for k, a in is_emirleri.KANAL_ADLARI.items()],
        "iliski_turleri": [
            {"kod": k, "ad": is_emirleri.ILISKI_ADLARI[k]} for k in is_emirleri.EKRAN_ILISKI_TURLERI
        ],
        "sonuclar": [{"kod": k, "ad": sonuc.SONUC_ADLARI[k]} for k in SERVIS_SONUCLARI],
        "cozum_kanallari": [{"kod": k, "ad": sonuc.KANAL_ADLARI[k]} for k in COZUM_KANALLARI],
        "bekleme_nedenleri": [
            {"kod": n.kod, "ad": n.ad, "aciklama_zorunlu": n.aciklama_zorunlu} for n in nedenler
        ],
        "olay_turleri": [{"kod": k, "ad": a} for k, a in gecmis.OLAY_ADLARI.items()],
    }


@router.get("/isler/mukerrer-kontrol", response_model=None)
async def mukerrer_kontrol(
    db: DbDep,
    user: Okuyucu,
    seri: Annotated[list[str] | None, Query(max_length=50)] = None,
    musteri_id: int | None = None,
    adres_id: int | None = None,
    haric_id: int | None = None,
) -> dict[str, Any]:
    """Form canlı uyarısı: açık işte aynı seri (kapsam dışı numara verilmez) ve
    aynı müşteri + lokasyonda açık iş (yalnız uyarı)."""
    try:
        mukerrer, kapsam_disi = await is_emirleri.mukerrer_adaylari(
            db, user, seri or [], haric_id=haric_id
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    ayni = []
    if musteri_id is not None and not await hesap_kapsam_disinda_mi(db, user, musteri_id):
        ayni = await is_emirleri.ayni_lokasyon_acik_isler(
            db, user, musteri_id, adres_id, haric_id=haric_id
        )
    return {"mukerrer": mukerrer, "kapsam_disi_var": kapsam_disi, "ayni_lokasyon": ayni}


# --- Liste ve Excel (TS-026) ------------------------------------------------------------


def _filtre(
    birim, kategori, tur, durum, durum_grubu_, oncelik, musteri_id, adres_id, teknisyen_id,
    atanmamis, bas, bit, q, kapali_dahil, kpi, donem, siralama, kalite=None, sef_id=None,
    sonuc_=None,
) -> is_emirleri.ListeFiltresi:  # fmt: skip
    return is_emirleri.ListeFiltresi(
        birim=birim,
        kategori=kategori,
        tur=tur,
        durum=list(durum or []),
        durum_grubu=durum_grubu_,
        oncelik=oncelik,
        musteri_id=musteri_id,
        adres_id=adres_id,
        teknisyen_id=teknisyen_id,
        atanmamis=atanmamis,
        bas=bas,
        bit=bit,
        q=q,
        kapali_dahil=kapali_dahil,
        kpi=kpi,
        donem=donem,
        siralama=siralama,
        kalite=kalite,
        sef_id=sef_id,
        sonuc=sonuc_,
    )


def _sorgu(user: User, f: is_emirleri.ListeFiltresi, clock):
    try:
        return is_emirleri.liste_sorgusu(user, f, clock)
    except NotImplementedError as exc:
        raise _hazir_degil(exc) from exc
    except (ValueError, KeyError) as exc:
        if isinstance(exc, ServisHatasi):
            raise _hata(exc) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/isler", response_model=None)
async def listele(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    response: Response,
    birim: str | None = None,
    kategori: str | None = None,
    tur: str | None = None,
    durum: Annotated[list[str] | None, Query()] = None,
    durum_grubu: str | None = None,
    oncelik: str | None = None,
    musteri_id: int | None = None,
    adres_id: int | None = None,
    teknisyen_id: int | None = None,
    atanmamis: bool = False,
    bas: date | None = None,
    bit: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    kapali_dahil: bool = False,
    kpi: str | None = Query(default=None, max_length=40),
    donem: str | None = Query(default=None, max_length=20),
    siralama: str = "yeni",
    kalite: str | None = Query(default=None, max_length=10),
    sef_id: int | None = None,
    sonuc_: Annotated[str | None, Query(alias="sonuc", max_length=20)] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Servis işleri (sunucu süzgeci, SQL'de kapsam, sayfalı; `X-Toplam-Kayit`).

    Parametresiz: açık işler + son 90 günde kapananlar. `kpi=<kod>` panel
    kutusunun AYNI süzgecidir (sayı = liste). `kalite=BEKLEYEN` kalite onayı
    bekleyen tamamlanmış işler (Faz A). `sonuc=TEKLIF_SUNULACAK` geçerli sonucu
    "teklif sunulacak" olan işler (rol testi tur 2, satış destek listesi).
    """
    f = _filtre(
        birim, kategori, tur, durum, durum_grubu, oncelik, musteri_id, adres_id, teknisyen_id,
        atanmamis, bas, bit, q, kapali_dahil, kpi, donem, siralama, kalite, sef_id, sonuc_,
    )  # fmt: skip
    stmt = _sorgu(user, f, clock)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _satirlar(db, [s for (s,) in satirlar], user)


_EXCEL_SUTUNLARI = [
    export_svc.Sutun("İş No", "metin"),
    export_svc.Sutun("Birim"),
    export_svc.Sutun("Tür"),
    export_svc.Sutun("Kategori"),
    export_svc.Sutun("Durum"),
    export_svc.Sutun("Durum Grubu"),
    export_svc.Sutun("Öncelik"),
    export_svc.Sutun("Müşteri"),
    export_svc.Sutun("Lokasyon"),
    export_svc.Sutun("İl"),
    export_svc.Sutun("Konu"),
    export_svc.Sutun("Seri No", "metin"),
    export_svc.Sutun("Talep Kanalı"),
    export_svc.Sutun("Bildirim", "zaman"),
    export_svc.Sutun("Açılış", "zaman"),
    export_svc.Sutun("Tamamlanma", "zaman"),
    export_svc.Sutun("Kapanış", "zaman"),
    export_svc.Sutun("Sorumlu"),
    export_svc.Sutun("Ekip"),
    export_svc.Sutun("İrtibat"),
    export_svc.Sutun("Telefon", "metin"),
    export_svc.Sutun("Yapılan İşlem"),
    export_svc.Sutun("Arıza Nedeni"),
    export_svc.Sutun("Sonuç"),
    export_svc.Sutun("Çözüm Kanalı"),
    export_svc.Sutun("Bekleme (dk)", "tamsayi"),
    export_svc.Sutun("Yeniden Açılma", "tamsayi"),
]


@router.get("/isler.xlsx")
async def disa_aktar(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Aktarici,
    birim: str | None = None,
    kategori: str | None = None,
    tur: str | None = None,
    durum: Annotated[list[str] | None, Query()] = None,
    durum_grubu: str | None = None,
    oncelik: str | None = None,
    musteri_id: int | None = None,
    adres_id: int | None = None,
    teknisyen_id: int | None = None,
    atanmamis: bool = False,
    bas: date | None = None,
    bit: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    kapali_dahil: bool = False,
    kpi: str | None = Query(default=None, max_length=40),
    donem: str | None = Query(default=None, max_length=20),
    siralama: str = "yeni",
    kalite: str | None = Query(default=None, max_length=10),
    sonuc_: Annotated[str | None, Query(alias="sonuc", max_length=20)] = None,
) -> Response:
    """Ekrandaki süzgecin AYNISIYLA Excel (Servis İşleri + Durum Özeti).

    `X-Toplam-Kayit` = Excel satır sayısı = liste toplamı. Seri/iş no/telefon
    METİN, tarihler Türkiye saatiyle gerçek tarih hücresi. Telefon kurala göre
    maskeli. Kişisel veri dışa aktarımı olarak denetime yazılır.
    """
    f = _filtre(
        birim, kategori, tur, durum, durum_grubu, oncelik, musteri_id, adres_id, teknisyen_id,
        atanmamis, bas, bit, q, kapali_dahil, kpi, donem, siralama, kalite, sonuc_=sonuc_,
    )  # fmt: skip
    stmt = _sorgu(user, f, clock)
    toplam = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    if (toplam or 0) > EXCEL_UST_SINIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{toplam} kayıt var; Excel en çok {EXCEL_UST_SINIR} satır alır, süzgeci daraltın",
        )
    sos = list((await db.scalars(stmt.order_by(ServiceOrder.id))).all())
    satirlar = await _satirlar(db, sos, user)
    idler = [s.id for s in sos]
    ekipler = await _ekipler(db, idler)
    adlar = await _kisi_adlari(db, {a.user_id for e in ekipler.values() for a in e})
    sonuclar: dict[int, ServiceResult] = {}
    if idler:
        for r in (
            await db.scalars(
                select(ServiceResult)
                .where(
                    ServiceResult.service_order_id.in_(idler), ServiceResult.gecersiz_at.is_(None)
                )
                .order_by(ServiceResult.id)
            )
        ).all():
            sonuclar[r.service_order_id] = r
    nedenler = {
        n.id: n.ad
        for n in (
            await db.scalars(
                select(ServiceFaultReason).where(
                    ServiceFaultReason.id.in_(
                        {r.ariza_nedeni_id for r in sonuclar.values() if r.ariza_nedeni_id} or {0}
                    )
                )
            )
        ).all()
    }
    bekleme_dk = await bekletme.toplam_bekleme_dk(db, idler, clock)
    tablo = []
    ozet: dict[str, dict[str, int]] = {}
    for s, satir in zip(sos, satirlar, strict=True):
        r = sonuclar.get(s.id)
        ekip = ekipler.get(s.id, [])
        lok = satir["lokasyon"] or {}
        tablo.append(
            [
                s.so_no,
                BIRIMLER.get(s.birim, s.birim),
                is_emirleri.TUR_ADLARI.get(s.tur, s.tur),
                is_emirleri.KATEGORI_ADLARI.get(s.kategori, s.kategori),
                is_emirleri.DURUM_ADLARI.get(s.status, s.status),
                durum_grubu_hesapla(s.status),
                s.oncelik,
                (satir["musteri"] or {}).get("title") or s.customer_name_raw,
                lok.get("ad"),
                lok.get("il"),
                s.konu,
                ", ".join(satir["seriler"]),
                is_emirleri.KANAL_ADLARI.get(s.talep_kanali or "", s.talep_kanali),
                s.reported_at,
                s.created_at,
                s.completed_at,
                s.closed_at,
                (satir["sorumlu"] or {}).get("ad"),
                ", ".join(adlar.get(a.user_id, "?") for a in ekip),
                s.iletisim_ad,
                satir["iletisim_telefon"],
                r.yapilan_islem if r else None,
                nedenler.get(r.ariza_nedeni_id) if r and r.ariza_nedeni_id else None,
                sonuc.SONUC_ADLARI.get(r.sonuc) if r else None,
                sonuc.KANAL_ADLARI.get(r.cozum_kanali) if r else None,
                bekleme_dk.get(s.id, 0),
                s.reopen_count,
            ]
        )
        ozet.setdefault(s.birim, {})
        ozet[s.birim][s.status] = ozet[s.birim].get(s.status, 0) + 1
    ozet_basliklar = ["Birim", *(is_emirleri.DURUM_ADLARI[d] for d in SERVIS_DURUMLARI), "Toplam"]
    ozet_satirlar = []
    toplamlar = dict.fromkeys(SERVIS_DURUMLARI, 0)
    for b in BIRIM_KODLARI:
        if b not in ozet:
            continue
        sayilar = [ozet[b].get(d, 0) for d in SERVIS_DURUMLARI]
        for d in SERVIS_DURUMLARI:
            toplamlar[d] += ozet[b].get(d, 0)
        ozet_satirlar.append([BIRIMLER[b], *sayilar, sum(sayilar)])
    ozet_satirlar.append(["Toplam", *toplamlar.values(), sum(toplamlar.values())])
    icerik = await export_svc.sayfalari_xlsx_async(
        [
            export_svc.Sayfa("Servis İşleri", list(_EXCEL_SUTUNLARI), tablo),
            export_svc.Sayfa(
                "Durum Özeti",
                [export_svc.Sutun(ozet_basliklar[0])]
                + [export_svc.Sutun(b, "tamsayi") for b in ozet_basliklar[1:]],
                ozet_satirlar,
            ),
        ]
    )
    await audit.log(
        db,
        "service_orders",
        "servis.disa_aktar",
        new_value={"satir": len(tablo), "kpi": kpi, "q": q, "birim": birim},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return Response(
        content=icerik,
        media_type=XLSX,
        headers={
            "Content-Disposition": 'attachment; filename="servis-isleri.xlsx"',
            "X-Toplam-Kayit": str(len(tablo)),
        },
    )


# --- Açılış (TS-020/024/029) -------------------------------------------------------------


@router.post("/isler", status_code=status.HTTP_201_CREATED, response_model=None)
async def olustur(
    payload: IsAcIn, request: Request, db: DbDep, clock: ClockDep, user: IsAcici
) -> dict[str, Any]:
    """Servis işi açar. Mükerrer seri 409 (`mukerrer_gec` ile geçilir);
    aynı müşteri+lokasyonda açık iş yalnız `uyarilar`'da döner."""
    uyarilar = await _acilis_on_kontrol(db, payload, user)
    try:
        so = await is_emirleri.olustur(db, _girdi(payload), user=user, clock=clock)
        if any(u["kod"] == "MUKERRER_GECILDI" for u in uyarilar):
            await gecmis.olay_yaz(
                db,
                so,
                "NOT",
                "Mükerrer seri uyarısı geçildi: "
                + ", ".join(u["so_no"] for u in uyarilar if u["kod"] == "MUKERRER_GECILDI"),
                user=user,
                clock=clock,
                veri={
                    "mukerrer_gecildi": [
                        u["id"] for u in uyarilar if u["kod"] == "MUKERRER_GECILDI"
                    ]
                },
            )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    if payload.gecis_kaydi:
        await gecmis.olay_yaz(
            db,
            so,
            "NOT",
            "Geçiş/içe aktarma kaydı: bildirim tarihi kaynaktan korundu, SLA ölçülmez. "
            f"Gerekçe: {(payload.gecis_gerekcesi or '').strip()}",
            user=user,
            clock=clock,
            veri={"gecis_kaydi": True},
        )
    await _acilis_denetimi(db, so, user, request, "olustur")
    await db.commit()
    cikti = await _detay(db, so, user, clock)
    cikti["uyarilar"] = uyarilar
    return cikti


@router.post("/isler/uzaktan-cozuldu", status_code=status.HTTP_201_CREATED, response_model=None)
async def uzaktan_cozuldu(
    payload: UzaktanIn, request: Request, db: DbDep, clock: ClockDep, user: UzaktanCozucu
) -> dict[str, Any]:
    """Açılışta telefonla/uzaktan çözüldü: tek istekte açılış + TAMAMLANDI.
    İş kapanmaz; şef ayrıca kapatır."""
    uyarilar = await _acilis_on_kontrol(db, payload, user)
    try:
        so = await sonuc.uzaktan_coz(
            db,
            _girdi(payload),
            sonuc.SonucGirdisi(
                sonuc="COZULDU",
                cozum_kanali=payload.cozum_kanali,
                yapilan_islem=payload.yapilan_islem,
                ariza_nedeni_id=payload.ariza_nedeni_id,
            ),
            user=user,
            clock=clock,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _acilis_denetimi(db, so, user, request, "uzaktan_coz")
    await db.commit()
    cikti = await _detay(db, so, user, clock)
    cikti["uyarilar"] = uyarilar
    return cikti


EkipmandanAcici = Annotated[
    User, Depends(require_any_permission("servis.yaz", "servis.kurulum_ac"))
]
EkipmanOkuyucu = Annotated[User, Depends(require_permission("ekipman.gor"))]


@router.post("/isler/ekipmandan", status_code=status.HTTP_201_CREATED, response_model=None)
async def ekipmandan_ac(
    payload: EkipmandanIsIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: EkipmandanAcici,
    _ekipman: EkipmanOkuyucu,
) -> dict[str, Any]:
    """Kütükten seçili ekipmanlara toplu servis işi (tek transaction).

    Kurallar: üst sınır `servis_toplu_atama_ust_sinir` (aşılırsa 422);
    kapsam dışı/bulunamayan ekipman 404 (hangisi söylenmez); pasif ya da
    müşterisiz ekipman 409 + liste; irtibat yoksa (ekipmanın kayıtlı irtibatı
    da yoksa) 400; açık işte aynı seri 409 `MUKERRER` (`mukerrer_gec` ile
    geçilir). Herhangi bir ihlalde HİÇBİR iş açılmaz.
    """
    from app.services import settings as ayar_svc
    from app.services.teknik_servis import ekipman as ekipman_svc

    idler = list(dict.fromkeys(payload.ekipman_idler))
    ust = int(await ayar_svc.get(db, "servis_toplu_atama_ust_sinir"))
    if len(idler) > ust:
        raise HTTPException(422, f"Tek seferde en çok {ust} ekipman için iş açılabilir")
    if payload.tur not in is_emirleri.TUR_KURALLARI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bilinmeyen servis işi türü: {payload.tur}"
        )
    if is_emirleri.TUR_KURALLARI[payload.tur].yalniz_sistem:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{is_emirleri.TUR_ADLARI[payload.tur]}' işi bu ekrandan açılamaz",
        )
    if not user.has("servis.yaz") and payload.tur != "KURULUM":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Yalnız Kurulum işi açabilirsiniz (servis.kurulum_ac)",
        )
    _gecis_dogrula(payload.gecis_kaydi, payload.gecis_gerekcesi, user)
    if payload.talep_kanali not in TALEP_KANALLARI or payload.talep_kanali == "BAKIM_OTOMATIK":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Geçersiz talep kanalı: {payload.talep_kanali}"
        )
    ekipmanlar = []
    for eid in idler:
        try:
            ekipmanlar.append(await ekipman_svc.kapsamli_ekipman(db, user, eid))
        except ekipman_svc.EkipmanBulunamadi as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Seçilen ekipmanlardan biri bulunamadı"
            ) from exc
    for e in ekipmanlar:
        if kapsam.birim_disinda_mi(user, e.birim, birimsiz_gorunur=False):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Seçilen ekipmanlardan biri bulunamadı")

    def _etiket(e) -> str:
        return f"#{e.id}" + (f" ({e.serial_no})" if e.serial_no else "")

    sorunlu = [_etiket(e) for e in ekipmanlar if not e.is_active or e.account_id is None]
    if sorunlu:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Pasif ya da müşterisi olmayan ekipmana servis işi açılamaz: " + ", ".join(sorunlu),
        )
    irtibat_var = any((x or "").strip() for x in (payload.iletisim_ad, payload.iletisim_telefon))
    # M1.2 (Faz A): her işte lokasyon + talep eden kişinin adı ve telefonu.
    lokasyonsuz = [_etiket(e) for e in ekipmanlar if e.address_id is None]
    if lokasyonsuz:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Lokasyonu kayıtlı olmayan ekipmana servis işi açılamaz: " + ", ".join(lokasyonsuz),
        )
    irtibatsiz = []
    for e in ekipmanlar:
        try:
            await _talep_bilgisi_dogrula(
                db,
                e.address_id,
                e.contact_id,
                payload.iletisim_ad if e.contact_id is None else None,
                payload.iletisim_telefon if e.contact_id is None else None,
                gecis=payload.gecis_kaydi,
            )
        except HTTPException:
            irtibatsiz.append(_etiket(e))
    if irtibatsiz:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Talep eden kişinin adı ve telefonu eksik (ekipmanın irtibatında telefon yoksa "
            "ad/telefon girin): " + ", ".join(irtibatsiz),
        )
    seriler = [e.serial_no for e in ekipmanlar if e.serial_no]
    mukerrer: list[dict[str, Any]] = []
    kapsam_disi = False
    try:
        # `mukerrer_adaylari` tek işin seri sınırını (50) uygular: parça parça sorulur.
        for i in range(0, len(seriler), is_emirleri.SERI_UST_SINIR):
            m, k = await is_emirleri.mukerrer_adaylari(
                db, user, seriler[i : i + is_emirleri.SERI_UST_SINIR]
            )
            mukerrer.extend(x for x in m if x["id"] not in {y["id"] for y in mukerrer})
            kapsam_disi = kapsam_disi or k
    except _HATALAR as exc:
        raise _hata(exc) from exc
    if (mukerrer or kapsam_disi) and not payload.mukerrer_gec:
        mesaj = "Aynı seri numarasıyla açık servis işi var"
        if mukerrer:
            mesaj += ": " + ", ".join(m["so_no"] for m in mukerrer)
        elif kapsam_disi:
            mesaj += " (başka birimde açık kayıt var)"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"kod": "MUKERRER", "mesaj": mesaj, "mevcut_isler": mukerrer,
             "kapsam_disi_var": kapsam_disi},
        )  # fmt: skip
    acilan: list[ServiceOrder] = []
    try:
        for e in ekipmanlar:
            so = await is_emirleri.olustur(
                db,
                is_emirleri.ServisIsiGirdisi(
                    birim=e.birim,
                    tur=payload.tur,
                    konu=payload.konu,
                    customer_id=e.account_id,
                    address_id=e.address_id,
                    contact_id=e.contact_id,
                    oncelik=payload.oncelik,
                    talep_kanali=payload.talep_kanali,
                    reported_at=payload.reported_at,
                    iletisim_ad=payload.iletisim_ad if e.contact_id is None else None,
                    iletisim_telefon=payload.iletisim_telefon if e.contact_id is None else None,
                    aciklama=payload.aciklama,
                    seriler=[e.serial_no] if e.serial_no else [],
                    equipment_id=e.id,
                    gecis_kaydi=payload.gecis_kaydi,
                ),
                user=user,
                clock=clock,
            )
            if payload.gecis_kaydi:
                await gecmis.olay_yaz(
                    db,
                    so,
                    "NOT",
                    "Geçiş/içe aktarma kaydı: SLA ölçülmez; talep eden kaynakta yoksa "
                    f"sonradan girilir. Gerekçe: {(payload.gecis_gerekcesi or '').strip()}",
                    user=user,
                    clock=clock,
                    veri={"gecis_kaydi": True},
                )
            acilan.append(so)
    except _HATALAR as exc:
        await db.rollback()
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_orders",
        "ekipmandan_ac",
        new_value={
            "ekipman_idler": idler,
            "is_idler": [s.id for s in acilan],
            "tur": payload.tur,
            "mukerrer_gecildi": bool(mukerrer),
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=irtibat_var,
    )
    await db.commit()
    return {
        "acilan": len(acilan),
        "isler": [{"id": s.id, "so_no": s.so_no, "equipment_id": s.equipment_id} for s in acilan],
    }


# --- Toplu atama, ziyaret onayı/formu (statik yollar) ---------------------------------------


@router.put("/isler/toplu-atama", response_model=None)
async def toplu_atama(
    payload: TopluAtamaIn, request: Request, db: DbDep, clock: ClockDep, user: Planlayici
) -> dict[str, Any]:
    """Çok işe aynı ekip (tek transaction). Üst sınır `servis_toplu_atama_ust_sinir`
    (aşılırsa 422); kapsam dışı iş 404; kapalı/karışık birim 409 — hiçbir iş değişmez."""
    try:
        with atama.uyari_toplayici() as uyarilar:
            isler = await atama.toplu_ata(
                db,
                payload.is_idler,
                [atama.AtamaSatiri(a.user_id, a.rol, a.is_lead) for a in payload.atamalar],
                mod=payload.mod,
                user=user,
                clock=clock,
            )
    except _HATALAR as exc:
        await db.rollback()
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_orders",
        "toplu_atama",
        new_value={
            "is_idler": [s.id for s in isler],
            "mod": payload.mod,
            "ekip": [a.model_dump() for a in payload.atamalar],
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {
        "guncellenen": len(isler),
        "isler": [{"id": s.id, "so_no": s.so_no} for s in isler],
        "uyarilar": uyarilar,
    }


@router.post("/isler/toplu-kalite-onayi", response_model=None)
async def toplu_kalite_onayi(
    payload: KaliteTopluIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: KaliteOnaylayici,
) -> dict[str, Any]:
    """Toplu kalite onayı (rol testi tur 2 O3, G1.9). Her iş tekli onayın
    kuralıyla (iyimser kilit, görevler ayrılığı, tamamlanmış iş) ayrı ayrı
    sınanır; uygun olanlar onaylanır, olmayanlar nedeniyle `atlanan`da döner
    (kısmi sonuç bilinçli: kalite onayı mali işaret değildir, bir işin engeli
    diğer 44 işi bekletmesin). Kapsam dışı/bulunamayan iş "bulunamadı" olarak
    atlanır (iş no verilmez). Her onay ayrı denetim satırıdır."""
    onaylanan: list[dict[str, Any]] = []
    atlanan: list[dict[str, Any]] = []
    for satir in {s.id: s for s in payload.isler}.values():
        so = await db.get(ServiceOrder, satir.id)
        if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
            atlanan.append({"id": satir.id, "so_no": None, "neden": "Servis işi bulunamadı"})
            continue
        try:
            async with db.begin_nested():
                await is_emirleri.kalite_onayla(
                    db, so, user=user, clock=clock, version=satir.version, notu=payload.not_
                )
        except _HATALAR as exc:
            await db.refresh(so)
            atlanan.append({"id": so.id, "so_no": so.so_no, "neden": str(exc)})
            continue
        await audit.log(
            db,
            "service_orders",
            "kalite_onayi",
            entity_id=so.id,
            new_value={
                "kalite_onay_at": so.kalite_onay_at.isoformat(),
                "not": so.kalite_notu,
                "toplu": True,
            },
            user_id=user.id,
            ip=client_ip(request),
        )
        onaylanan.append({"id": so.id, "so_no": so.so_no})
    await db.commit()
    return {"onaylanan": onaylanan, "atlanan": atlanan}


async def _onay_isleri(db, user: User, is_idler: list[int]) -> list[ServiceOrder]:
    isler = []
    for so_id in dict.fromkeys(is_idler):
        isler.append(await _kapsamli_is(db, so_id, user))
    return isler


def _onay_cikti(o: ServiceApproval, user: User) -> dict[str, Any]:
    return {
        "id": o.id,
        "service_order_id": o.service_order_id,
        "tur": o.tur,
        "imzalayan_ad": o.imzalayan_ad if _irtibat_tam(user) else None,
        "imzalayan_unvan": o.imzalayan_unvan,
        "ek_id": o.ek_id,
        "eksik_nedeni": o.eksik_nedeni,
        "gecersiz_kilan_id": o.gecersiz_kilan_id,
        "onay_grubu": str(o.onay_grubu) if o.onay_grubu else None,
        "approved_at": o.approved_at,
    }


def _onay_girdisi(payload: OnayIn):
    from app.services.teknik_servis import onay

    return onay.OnayGirdisi(
        tur=payload.tur,
        imzalayan_ad=payload.imzalayan_ad,
        imzalayan_unvan=payload.imzalayan_unvan,
        ek_id=payload.ek_id,
        eksik_nedeni=payload.eksik_nedeni,
    )


@router.post("/isler/ziyaret-onayi", status_code=status.HTTP_201_CREATED, response_model=None)
async def ziyaret_onayi(
    payload: ZiyaretOnayIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> list[dict[str, Any]]:
    """Aynı müşteri + adres + gündeki işlere tek onay (`onay_grubu`, TS-036).
    Kapsam dışı iş 404 (hiçbiri yazılmaz); kural `s/onay.py`'de (D1-C)."""
    from app.services.teknik_servis import onay

    isler = await _onay_isleri(db, user, payload.is_idler)
    try:
        onaylar = await onay.ziyaret_onayi(
            db, [s.id for s in isler], _onay_girdisi(payload), user=user, clock=clock
        )
    except NotImplementedError as exc:
        raise _hazir_degil(exc) from exc
    except _HATALAR as exc:
        await db.rollback()
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_approvals",
        "ziyaret_onayi",
        new_value={"is_idler": [s.id for s in isler], "tur": payload.tur},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=bool(payload.imzalayan_ad),
    )
    await db.commit()
    return [_onay_cikti(o, user) for o in onaylar]


@router.get("/isler/ziyaret-formu.pdf")
async def ziyaret_formu(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    is_id: Annotated[list[int], Query(min_length=1, max_length=100)],
) -> Response:
    """Ziyaret toplu servis formu PDF'i (fiyatsız; bağlam `s/onay.py`, D1-C)."""
    from app.services.teknik_servis import onay

    isler = await _onay_isleri(db, user, is_id)
    try:
        icerik = await onay.ziyaret_formu_pdf(db, [s.id for s in isler], clock=clock)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except NotImplementedError as exc:
        raise _hazir_degil(exc) from exc
    except _HATALAR as exc:
        raise _hata(exc) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="ziyaret-formu.pdf"'},
    )


# --- Tek iş (TS-020/027) -----------------------------------------------------------------


@router.get("/isler/{so_id}", response_model=None)
async def getir(so_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> dict[str, Any]:
    so = await _kapsamli_is(db, so_id, user)
    return await _detay(db, so, user, clock)


@router.patch("/isler/{so_id}", response_model=None)
async def guncelle(
    so_id: int, payload: IsPatch, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Temel bilgi / müşteri-lokasyon düzeltme (TS-031). Eski `version` 409;
    kapalı işte `servis.kapat` + gerekçe; açık işte müşteri `servis.planla`;
    PB'de müşteri/tür 409; teknisyen 403; birim 400."""
    so = await _kapsamli_is(db, so_id, user)
    degisiklik = payload.model_dump(exclude_unset=True)
    degisiklik["version"] = payload.version
    try:
        await is_emirleri.guncelle(db, so, degisiklik, user=user, clock=clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, user, clock)


@router.put("/isler/{so_id}/seriler", response_model=None)
async def seriler(
    so_id: int, payload: SerilerIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Seri listesini eşitler (eski satır pasiflenir). PB 409; kapalı işte
    `servis.kapat` + gerekçe."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await is_emirleri.serileri_yaz(
            db, so, payload.seriler, user=user, clock=clock, gerekce=payload.gerekce
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_orders",
        "seri_degistir",
        entity_id=so.id,
        new_value={"seriler": payload.seriler, "gerekce": payload.gerekce},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _detay(db, so, user, clock)


@router.post(
    "/isler/{so_id}/bagli-yeni-is", status_code=status.HTTP_201_CREATED, response_model=None
)
async def bagli_yeni_is(
    so_id: int, payload: BagliIsIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Kapanmış işe bağlı YENİ iş (M1.7; yeniden açmanın yerine). Açık işte
    409; açılış kuralları ekran açılışıyla aynıdır (birim/müşteri kapsamı,
    talep eden kişi + telefon, lokasyon, tek cihaz, mükerrer seri 409)."""
    onceki = await _kapsamli_is(db, so_id, user)
    if onceki.status not in is_emirleri.BAGLI_IS_KAYNAK_DURUMLARI:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "İş henüz kapanmadı; bağlı yeni iş yalnız kapanmış işten açılır",
        )
    if onceki.customer_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Müşterisi eşleşmemiş (göç) işe bağlı iş açılamaz"
        )
    varsayilan = is_emirleri.bagli_is_girdisi(
        onceki, [s.seri_no for s in await is_emirleri.aktif_seriler(db, onceki)]
    )
    degerler = payload.model_dump(exclude_unset=True, by_alias=False)
    degerler.pop("mukerrer_gec", None)
    try:
        acilis = _bagli_acilis(varsayilan, degerler, payload)
    except ValidationError as exc:
        hata = exc.errors()[0]
        alan = ".".join(str(x) for x in hata.get("loc", ()))
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Geçersiz alan ({alan}): {hata.get('msg')}"
        ) from exc
    uyarilar = await _acilis_on_kontrol(db, acilis, user)
    girdi = _girdi(acilis)
    girdi.equipment_id = varsayilan.equipment_id
    if payload.iliski_turu is not None:
        girdi.iliskili_is_id = onceki.id
        girdi.iliski_turu = payload.iliski_turu
    try:
        so = await is_emirleri.bagli_yeni_is(db, onceki, girdi, user=user, clock=clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _acilis_denetimi(db, so, user, request, "bagli_yeni_is")
    await audit.log(
        db,
        "service_orders",
        "bagli_is_acildi",
        entity_id=onceki.id,
        new_value={"sonraki_is_id": so.id, "so_no": so.so_no},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    cikti = await _detay(db, so, user, clock)
    cikti["uyarilar"] = uyarilar
    return cikti


def _bagli_acilis(
    varsayilan: is_emirleri.ServisIsiGirdisi, degerler: dict[str, Any], payload: BagliIsIn
) -> IsAcIn:
    """Önceki işin kopyası + gövdede verilen alanlar → ekran açılış gövdesi."""
    return IsAcIn(
        birim=varsayilan.birim,
        tur=degerler.get("tur") or varsayilan.tur,
        konu=degerler.get("konu") or varsayilan.konu,
        customer_id=varsayilan.customer_id,
        address_id=degerler.get("address_id", varsayilan.address_id),
        contact_id=degerler.get("contact_id", varsayilan.contact_id),
        oncelik=degerler.get("oncelik") or varsayilan.oncelik,
        talep_kanali=degerler.get("talep_kanali") or varsayilan.talep_kanali,
        reported_at=degerler.get("reported_at"),
        iletisim_ad=degerler.get("iletisim_ad", varsayilan.iletisim_ad),
        iletisim_telefon=degerler.get("iletisim_telefon", varsayilan.iletisim_telefon),
        proje=varsayilan.proje,
        sistem=varsayilan.sistem,
        aciklama=degerler.get("aciklama"),
        seriler=varsayilan.seriler if payload.seriler is None else list(payload.seriler),
        mukerrer_gec=payload.mukerrer_gec,
    )


@router.post("/isler/{so_id}/kalite-onayi", response_model=None)
async def kalite_onayi(
    so_id: int,
    payload: KaliteOnayIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: KaliteOnaylayici,
) -> dict[str, Any]:
    """Tamamlanan işe kalite onayı (D3.4, G4.6). İşte tayinli/süre kaydı
    olan ya da sonucu giren kişi 403 (görevler ayrılığı); tamamlanmamış iş,
    verilmiş onay ya da eski `version` 409."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await is_emirleri.kalite_onayla(
            db, so, user=user, clock=clock, version=payload.version, notu=payload.not_
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_orders",
        "kalite_onayi",
        entity_id=so.id,
        new_value={"kalite_onay_at": so.kalite_onay_at.isoformat(), "not": so.kalite_notu},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _detay(db, so, user, clock)


class RoleMontajIn(BaseModel):
    """Röle montaj bilgileri (tümü; gönderilmeyen alan silinir). İlk kayıtta
    `version` boş, sonrakilerde son okunan `version` (iyimser kilit)."""

    degerler: dict[str, Any]
    version: int | None = None


@router.get("/isler/{so_id}/role-montaj", response_model=None)
async def role_montaj_getir(so_id: int, db: DbDep, user: Okuyucu) -> dict[str, Any]:
    """Haberleşme kurulum/montaj işinin röle montaj bilgileri: alan tanımları,
    değerler (kayıt yoksa işten öneriler), kapanışı engelleyen eksikler."""
    so = await _kapsamli_is(db, so_id, user)
    cikti = await role_montaj.durum(db, so, user)
    if not _irtibat_tam(user):
        tel = cikti["degerler"].get("sorumlu_telefon")
        if tel:
            cikti["degerler"]["sorumlu_telefon"] = kvkk.maskele(tel)
    return cikti


@router.put("/isler/{so_id}/role-montaj", response_model=None)
async def role_montaj_kaydet(
    so_id: int,
    payload: RoleMontajIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict[str, Any]:
    """Kısmi kayıt serbest; eksik zorunlu alan yalnız kapanışı engeller (409)."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        kayit = await role_montaj.kaydet(
            db, so, payload.degerler, version=payload.version, user=user, clock=clock
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_role_montaj",
        "kaydet",
        entity_id=kayit.id,
        new_value=role_montaj.denetim_degeri(kayit.alanlar),
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await role_montaj.durum(db, so, user)


class CihazBilgisiIn(BaseModel):
    """Teknisyen girişi: Güvenlik arızasında seri no; Haberleşme arızasında
    frekans alanları (+ işte seri yoksa seri no). İlk kayıtta `version` boş."""

    seri_no: str | None = Field(default=None, max_length=200)
    frekans: dict[str, Any] | None = None
    version: int | None = None


@router.get("/isler/{so_id}/cihaz-bilgisi", response_model=None)
async def cihaz_bilgisi_getir(so_id: int, db: DbDep, user: Okuyucu) -> dict[str, Any]:
    """Arıza işinin kütükten gelen / girilen cihaz bilgisi ve kapanış eksikleri."""
    so = await _kapsamli_is(db, so_id, user)
    return await cihaz_bilgisi.durum(db, so)


@router.put("/isler/{so_id}/cihaz-bilgisi", response_model=None)
async def cihaz_bilgisi_kaydet(
    so_id: int,
    payload: CihazBilgisiIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> dict[str, Any]:
    """Kütükte olmayan seri/frekansı teknisyen girer; eksik yalnız kapanışı engeller."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await cihaz_bilgisi.kaydet(
            db,
            so,
            seri_no=payload.seri_no,
            frekans=payload.frekans,
            version=payload.version,
            user=user,
            clock=clock,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    cikti = await cihaz_bilgisi.durum(db, so)
    await audit.log(
        db,
        "service_frekans_bilgisi",
        "kaydet",
        entity_id=so.id,
        new_value={"kural": cikti["kural"], "seri_no": cikti["seri_no"], **cikti["frekans"]},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return cikti


@router.post("/isler/{so_id}/kalite-reddi", response_model=None)
async def kalite_reddi(
    so_id: int,
    payload: KaliteRedIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: KaliteOnaylayici,
) -> dict[str, Any]:
    """Kalite reddi / geri gönderme (rol testi tur 2 Y5, KARARLAR 2026-11-04 §7.3).

    Tamamlanmış (kapatılmamış) işi gerekçeyle (≥10 karakter, 400) İŞLEMDE ya da
    PLANLAMADA'ya döndürür; sonuç geçersizleşir, bakım formu taslağa döner. Zilde
    `kalite_reddedilen` uyarısı ekibe/şefe düşer. Görevler ayrılığı onayla aynı
    (403); eski `version`, onaylı/faturalanmış/atölye işi 409."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await is_emirleri.kalite_reddet(
            db,
            so,
            user=user,
            clock=clock,
            version=payload.version,
            gerekce=payload.gerekce,
            hedef=payload.hedef,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_orders",
        "kalite_reddi",
        entity_id=so.id,
        new_value={"hedef": payload.hedef, "gerekce": so.kalite_red_gerekcesi},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _detay(db, so, user, clock)


@router.post("/isler/{so_id}/yola-cikis-geri-al", response_model=None)
async def yola_cikis_geri_al(
    so_id: int,
    payload: YolaCikisGeriAlIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Planlayici,
) -> dict[str, Any]:
    """Yönetici/şef yanlış "Yola Çıktım"ı geri alır (rol testi tur 2 Y6): iş
    YOLA_CIKILDI → PLANLANDI, ekibin bu işteki açık YOL sayaçları gerekçeyle
    iptal edilir (kişi-saate girmez). Gerekçe zorunlu (≥10), eski `version` 409,
    yola çıkılmamış iş 409. Denetim izine ve iş geçmişine yazılır."""
    so = await _kapsamli_is(db, so_id, user)
    if payload.version != so.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin"
        )
    if so.status != "YOLA_CIKILDI":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Yola çıkış yalnız 'Yola Çıkıldı' durumundaki işte geri alınır",
        )
    from app.services.teknik_servis import zaman

    try:
        iptaller = await zaman.yola_cikisi_geri_al(
            db, so, gerekce=payload.gerekce, user=user, clock=clock
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_orders",
        "yola_cikis_geri_al",
        entity_id=so.id,
        old_value={"status": "YOLA_CIKILDI"},
        new_value={"status": so.status, "gerekce": payload.gerekce, "iptal_bolum": iptaller},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _detay(db, so, user, clock)


@router.put("/isler/{so_id}/iliski", response_model=None)
async def iliski(
    so_id: int, payload: IliskiIn, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Tek üst bağ kurar/kaldırır (TS-030). Bağlanan iş kapsam dışıysa 404."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await is_emirleri.iliski_kur(
            db,
            so,
            payload.iliskili_is_id,
            payload.iliski_turu,
            user=user,
            clock=clock,
            kapsam_user=user,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, user, clock)


# --- Durum (TS-021) --------------------------------------------------------------------


async def _durum_ucu(
    db, clock, user: User, so_id: int, hedef: str, kaynak: str, beklenen, gerekce, request
) -> dict[str, Any]:
    so = await _kapsamli_is(db, so_id, user)
    _beklenen(so, beklenen)
    onceki = so.status
    try:
        await is_emirleri.durum_degistir(
            db, so, hedef, kaynak=kaynak, user=user, clock=clock, gerekce=gerekce
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    if kaynak in ("kapat", "iptal"):
        await audit.log(
            db,
            "service_orders",
            f"durum.{kaynak}",
            entity_id=so.id,
            old_value={"status": onceki},
            new_value={"status": hedef, "gerekce": gerekce},
            user_id=user.id,
            ip=client_ip(request),
        )
    await db.commit()
    return await _detay(db, so, user, clock)


@router.post("/isler/{so_id}/durum", response_model=None)
async def durum(
    so_id: int, payload: DurumIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Genel saha ilerlemesi. Bu uçtan PLANLANDI/BEKLEMEDE/TAMAMLANDI/KAPATILDI/
    IPTAL/TEKRAR_ACILDI istenirse 400 ("ilgili ucu kullanın")."""
    if payload.hedef == "TEKRAR_ACILDI":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, is_emirleri.YENIDEN_ACMA_YOK)
    if payload.hedef not in is_emirleri.UC_HEDEFLERI["genel"]:
        uc = is_emirleri._HEDEF_UCU.get(payload.hedef, ("", ""))[0]
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{is_emirleri.DURUM_ADLARI[payload.hedef]}' durumu bu uçtan verilemez; "
            f"ilgili işlemi kullanın ({uc})",
        )
    return await _durum_ucu(
        db, clock, user, so_id, payload.hedef, "genel", payload.beklenen_durum,
        payload.gerekce, request,
    )  # fmt: skip


@router.post("/isler/{so_id}/kapat", response_model=None)
async def kapat(
    so_id: int, payload: KapatIn, request: Request, db: DbDep, clock: ClockDep, user: Kapatici
) -> dict[str, Any]:
    """TAMAMLANDI → KAPATILDI (yalnız `servis.kapat`)."""
    return await _durum_ucu(
        db, clock, user, so_id, "KAPATILDI", "kapat", payload.beklenen_durum,
        payload.gerekce, request,
    )  # fmt: skip


@router.post("/isler/{so_id}/iptal", response_model=None)
async def iptal(
    so_id: int, payload: GerekceIn, request: Request, db: DbDep, clock: ClockDep, user: Kapatici
) -> dict[str, Any]:
    """İptal (gerekçe zorunlu; terminal)."""
    return await _durum_ucu(
        db, clock, user, so_id, "IPTAL", "iptal", payload.beklenen_durum,
        payload.gerekce, request,
    )  # fmt: skip


@router.post("/isler/{so_id}/yeniden-ac", response_model=None)
async def yeniden_ac(so_id: int, payload: GerekceIn, db: DbDep, user: Kapatici) -> dict[str, Any]:
    """KALDIRILDI (M1.7, Faz A): kapanmış iş yeniden açılmaz. Eski istemci
    için uç 409 döner ve `bagli-yeni-is` ucuna yönlendirir; kapsam dışı iş
    yine 404 (varlık sızdırılmaz). Hiçbir şey yazılmaz."""
    await _kapsamli_is(db, so_id, user)
    raise HTTPException(status.HTTP_409_CONFLICT, is_emirleri.YENIDEN_ACMA_YOK)


# --- Bekleme (TS-023) -----------------------------------------------------------------------


def _bekleme_cikti(h, adlar: dict[str, str]) -> dict[str, Any]:
    return {
        "id": h.id,
        "neden": h.neden,
        "neden_adi": adlar.get(h.neden, h.neden),
        "aciklama": h.aciklama,
        "onceki_durum": h.onceki_durum,
        "started_at": h.started_at,
        "beklenen_bitis_at": h.beklenen_bitis_at,
        "released_at": h.released_at,
        "sure_dk": h.sure_dk,
        "sla_durdurur": h.sla_durdurur,
        "otomatik_kapandi": h.otomatik_kapandi,
        "kapanis_notu": h.kapanis_notu,
    }


async def _neden_adlari(db) -> dict[str, str]:
    return dict((await db.execute(select(ServiceHoldReason.kod, ServiceHoldReason.ad))).all())


@router.post("/isler/{so_id}/bekleme", response_model=None)
async def bekleme_baslat(
    so_id: int, payload: BeklemeIn, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """İşi bekletir. Katalog dışı/pasif/sistem nedeni 400; DIGER açıklamasız
    400; aktif bekleme varken 409; kapalı iş 409."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await bekletme.beklet(
            db,
            so,
            payload.neden,
            user=user,
            clock=clock,
            aciklama=payload.aciklama,
            beklenen_bitis_at=payload.beklenen_bitis_at,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, user, clock)


@router.post("/isler/{so_id}/bekleme/bitir", response_model=None)
async def bekleme_bitir(
    so_id: int, payload: BeklemeBitirIn, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """Beklemeyi bitirir; iş önceki durumuna döner (dönülemiyorsa PLANLAMADA)."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await bekletme.beklemeyi_bitir(db, so, user=user, clock=clock, not_=payload.not_)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, user, clock)


@router.get("/isler/{so_id}/beklemeler", response_model=None)
async def beklemeler(so_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> dict[str, Any]:
    """Bekleme geçmişi ve toplam süre (dk)."""
    so = await _kapsamli_is(db, so_id, user)
    adlar = await _neden_adlari(db)
    liste = await bekletme.bekleme_gecmisi(db, so)
    toplam = await bekletme.toplam_bekleme_dk(db, [so.id], clock)
    return {
        "beklemeler": [_bekleme_cikti(h, adlar) for h in liste],
        "toplam_dk": toplam.get(so.id, 0),
    }


# --- Sonuç (TS-024) ------------------------------------------------------------------------


@router.post("/isler/{so_id}/sonuc", response_model=None)
async def sonuc_gir(
    so_id: int, payload: SonucIn, db: DbDep, clock: ClockDep, user: Tamamlayici
) -> dict[str, Any]:
    """Sonuç girer: COZULDU/COZULEMEDI → TAMAMLANDI; TEKRAR_GIDILECEK iş açık
    kalır; TEKLIF_SUNULACAK → TEKLIF beklemesi. Kanal zorunlu."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        await sonuc.sonuc_gir(
            db,
            so,
            sonuc.SonucGirdisi(
                sonuc=payload.sonuc,
                cozum_kanali=payload.cozum_kanali,
                yapilan_islem=payload.yapilan_islem,
                ariza_nedeni_id=payload.ariza_nedeni_id,
                saha_seri_no=payload.saha_seri_no,
                saha_bolge=payload.saha_bolge,
                sure_eksik_onay=payload.sure_eksik_onay,
            ),
            user=user,
            clock=clock,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _detay(db, so, user, clock)


# --- Geçmiş ve not (TS-022) ---------------------------------------------------------------


@router.get("/isler/{so_id}/gecmis", response_model=None)
async def gecmis_listesi(
    so_id: int,
    db: DbDep,
    user: Okuyucu,
    tur: Annotated[list[str] | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Olay zaman çizelgesi (silinemez). Kişi adları okunurken çözülür."""
    so = await _kapsamli_is(db, so_id, user)
    olaylar = await gecmis.gecmis_listesi(db, so, turler=tur)
    kimlikler: set[int] = {o.user_id for o in olaylar if o.user_id}
    for o in olaylar:
        if o.olay_turu == "ATAMA" and o.veri:
            for anahtar in ("eklenen", "cikan", "degisen"):
                kimlikler |= set(o.veri.get(anahtar) or [])
            if o.veri.get("sorumlu"):
                kimlikler.add(o.veri["sorumlu"])
    adlar = await _kisi_adlari(db, kimlikler)
    sonuc_ = []
    for o in olaylar:
        kisiler = None
        if o.olay_turu == "ATAMA" and o.veri:
            kisiler = {
                anahtar: [adlar.get(i, "?") for i in o.veri.get(anahtar) or []]
                for anahtar in ("eklenen", "cikan", "degisen")
            }
            kisiler["sorumlu"] = adlar.get(o.veri.get("sorumlu")) if o.veri.get("sorumlu") else None
        sonuc_.append(
            {
                "id": o.id,
                "olay_turu": o.olay_turu,
                "olay_adi": gecmis.OLAY_ADLARI.get(o.olay_turu, o.olay_turu),
                "eski_durum": o.eski_durum,
                "yeni_durum": o.yeni_durum,
                "ozet": o.ozet,
                "veri": o.veri,
                "kisiler": kisiler,
                "kullanici": {"id": o.user_id, "ad": adlar.get(o.user_id)} if o.user_id else None,
                "olusma_zamani": o.olusma_zamani,
            }
        )
    return sonuc_


@router.post("/isler/{so_id}/notlar", status_code=status.HTTP_201_CREATED, response_model=None)
async def not_ekle(
    so_id: int, payload: NotIn, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    """İş notu (NOT olayı); durum ve sürüm değişmez."""
    so = await _kapsamli_is(db, so_id, user)
    try:
        olay = await gecmis.not_ekle(db, so, payload.metin, user=user, clock=clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"id": olay.id, "olay_turu": olay.olay_turu, "ozet": olay.ozet,
            "olusma_zamani": olay.olusma_zamani}  # fmt: skip


# --- Ekip / atama (TS-025) -----------------------------------------------------------------


async def _ekip_cikti(db, so: ServiceOrder) -> list[dict[str, Any]]:
    ekip = await atama.aktif_ekip(db, so)
    satirlar = await db.execute(
        select(User.id, User.full_name, User.giris_acik, User.saha_rolu).where(
            User.id.in_({a.user_id for a in ekip} or {0})
        )
    )
    harita = {i: (ad, giris, rol) for i, ad, giris, rol in satirlar.all()}
    return [
        {
            "user_id": a.user_id,
            "ad": harita.get(a.user_id, ("?", True, None))[0],
            "giris_acik": harita.get(a.user_id, ("?", True, None))[1],
            "saha_rolu": harita.get(a.user_id, ("?", True, None))[2],
            "rol": a.rol,
            "is_lead": a.is_lead,
            "assigned_at": a.assigned_at,
        }
        for a in ekip
    ]


@router.get("/isler/{so_id}/ekip", response_model=None)
async def ekip(so_id: int, db: DbDep, user: Okuyucu) -> list[dict[str, Any]]:
    so = await _kapsamli_is(db, so_id, user)
    return await _ekip_cikti(db, so)


@router.put("/isler/{so_id}/atama", response_model=None)
async def ata(
    so_id: int,
    payload: AtamaIn,
    request: Request,
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Planlayici,
) -> list[dict[str, Any]]:
    """Ekibi verilen listeye eşitler. Ayrılmış kişi 400; başka birimin kişisi 409;
    ikinci sorumlu 409; kapalı iş 409; açık sayaçlı kişiyi çıkarmak 409."""
    so = await _kapsamli_is(db, so_id, user)
    onceki = [(a.user_id, a.rol, a.is_lead) for a in await atama.aktif_ekip(db, so)]
    try:
        with atama.uyari_toplayici() as uyarilar:
            await atama.ata(
                db,
                so,
                [atama.AtamaSatiri(a.user_id, a.rol, a.is_lead) for a in payload.atamalar],
                user=user,
                clock=clock,
            )
        # Yanıt gövdesi canlı sözleşmede liste (ekip); yetkinlik uyarıları (TS-198,
        # atamayı engellemez) başlıkta yüzde kodlu JSON olarak taşınır.
        if uyarilar:
            response.headers["X-Atama-Uyarilari"] = quote(json.dumps(uyarilar, ensure_ascii=False))
    except _HATALAR as exc:
        await db.rollback()
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_orders",
        "atama",
        entity_id=so.id,
        old_value={"ekip": [list(x) for x in onceki]},
        new_value={"ekip": [a.model_dump() for a in payload.atamalar]},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _ekip_cikti(db, so)


# --- Müşteri onayı ve servis formu (TS-036; iş kuralı D1-C `s/onay.py`) -----------------------


@router.get("/isler/{so_id}/onaylar", response_model=None)
async def onaylar(so_id: int, db: DbDep, user: Okuyucu) -> list[dict[str, Any]]:
    so = await _kapsamli_is(db, so_id, user)
    liste = (
        await db.scalars(
            select(ServiceApproval)
            .where(ServiceApproval.service_order_id == so.id)
            .order_by(ServiceApproval.approved_at, ServiceApproval.id)
        )
    ).all()
    return [_onay_cikti(o, user) for o in liste]


@router.post("/isler/{so_id}/onay", status_code=status.HTTP_201_CREATED, response_model=None)
async def onay_al(
    so_id: int, payload: OnayIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> dict[str, Any]:
    from app.services.teknik_servis import onay

    so = await _kapsamli_is(db, so_id, user)
    try:
        kayit = await onay.onay_al(db, so, _onay_girdisi(payload), user=user, clock=clock)
    except NotImplementedError as exc:
        raise _hazir_degil(exc) from exc
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_approvals",
        "onay",
        entity_id=so.id,
        new_value={"tur": payload.tur},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=bool(payload.imzalayan_ad),
    )
    await db.commit()
    return _onay_cikti(kayit, user)


@router.get("/isler/{so_id}/servis-formu.pdf")
async def servis_formu(so_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> Response:
    """Fiyatsız Türkçe servis formu (bağlam `s/onay.servis_formu_baglami`)."""
    from app.services.teknik_servis import onay

    so = await _kapsamli_is(db, so_id, user)
    try:
        icerik = await onay.servis_formu_pdf(db, so, clock=clock)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except NotImplementedError as exc:
        raise _hazir_degil(exc) from exc
    except _HATALAR as exc:
        raise _hata(exc) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{so.so_no}.pdf"'},
    )


# --- Panel (TS-035; iş kuralı D1-C `s/panel.py`) ---------------------------------------------


@router.get("/panel", response_model=None)
async def panel(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    donem: str | None = Query(default=None, max_length=20),
    birim: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    """KPI kutuları; her kutu sayısı = `/isler?kpi=<kod>` `X-Toplam-Kayit`.
    Bilinmeyen dönem/birim 400; kapsam dışı birim 403 (`s/panel.py`)."""
    from app.services.teknik_servis import panel as panel_svc

    try:
        return await panel_svc.panel_ozeti(db, user, clock, donem=donem, birim=birim)
    except NotImplementedError as exc:
        raise _hazir_degil(exc) from exc
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except _HATALAR as exc:
        raise _hata(exc) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


# --- Genel arama (TS-037; plan §1.11 kayıt noktası) ------------------------------------------


@arayici_kaydet("servis.gor")
async def _servis_ara(db, user: User, terim: str, limit: int) -> list[AramaSonucu]:
    """İş no / seri ile servis işi araması — kapsamlı (`s/panel.servis_ara`)."""
    from app.services.teknik_servis import panel as panel_svc

    if not user.has("servis.gor"):
        return []
    return [AramaSonucu(**s) for s in await panel_svc.servis_ara(db, user, terim, limit)]


# --- Tanımlar: arıza nedeni (servis.tanim) ve bekleme nedeni (operasyon.yonet) -----------------


def _ariza_cikti(n: ServiceFaultReason) -> dict[str, Any]:
    return {
        "id": n.id,
        "birim": n.birim,
        "ad": n.ad,
        "sira": n.sira,
        "is_active": n.is_active,
        "version": n.version,
    }


@router.get("/tanimlar/ariza-nedenleri", response_model=None)
async def ariza_nedenleri(
    db: DbDep, user: Okuyucu, birim: str | None = None, tumu: bool = False
) -> list[dict[str, Any]]:
    """Birim bazlı arıza nedenleri. Birim kapsamlı kullanıcıya yalnız kendi
    birimleri; `tumu=true` pasifleri de getirir."""
    try:
        liste = await sonuc.ariza_nedenleri(db, birim, yalniz_aktif=not tumu)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    # Aynı kural tek kayıtta da: birim kapsamı + etkin şirket (TUMU dahil).
    liste = [n for n in liste if not kapsam.birim_disinda_mi(user, n.birim)]
    return [_ariza_cikti(n) for n in liste]


@router.put("/tanimlar/ariza-nedenleri", response_model=None)
async def ariza_nedeni_kaydet(
    payload: ArizaNedeniIn, request: Request, db: DbDep, user: Tanimci
) -> dict[str, Any]:
    """Ekle (`id` yok) / düzenle (`id` + `version`). Başka birimin kataloğu 403."""
    if kapsam.katalog_birim_yasak_mi(user, payload.birim):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu birimin kataloğunu düzenleyemezsiniz")
    try:
        satir, eski, yeni = await sonuc.ariza_nedeni_kaydet(
            db,
            id=payload.id,
            birim=payload.birim,
            ad=payload.ad,
            sira=payload.sira,
            is_active=payload.is_active,
            version=payload.version,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_fault_reasons",
        "tanim.ekle" if not eski else "tanim.duzelt",
        entity_id=satir.id,
        old_value=eski or None,
        new_value=yeni,
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(satir)
    return _ariza_cikti(satir)


def _neden_cikti(n: ServiceHoldReason) -> dict[str, Any]:
    return {
        "kod": n.kod,
        "ad": n.ad,
        "sla_durdurur": n.sla_durdurur,
        "aciklama_zorunlu": n.aciklama_zorunlu,
        "sadece_sistem": n.sadece_sistem,
        "sira": n.sira,
        "is_active": n.is_active,
        "version": n.version,
    }


@router.get("/tanimlar/bekleme-nedenleri", response_model=None)
async def bekleme_nedenleri(db: DbDep, user: Okuyucu, tumu: bool = False) -> list[dict[str, Any]]:
    """Seçilebilir bekleme nedenleri; `tumu=true` sistem ve pasif nedenleri de getirir."""
    return [_neden_cikti(n) for n in await bekletme.neden_katalogu(db, yalniz_secilebilir=not tumu)]


@router.put("/tanimlar/bekleme-nedenleri", response_model=None)
async def bekleme_nedeni_kaydet(
    payload: BeklemeNedeniIn, request: Request, db: DbDep, user: BeklemeTanimci
) -> dict[str, Any]:
    """Ekle / düzenle (kod anahtar). `sadece_sistem` ekrandan değişmez."""
    try:
        satir, eski, yeni = await bekletme.neden_kaydet(
            db,
            kod=payload.kod,
            ad=payload.ad,
            sla_durdurur=payload.sla_durdurur,
            aciklama_zorunlu=payload.aciklama_zorunlu,
            sira=payload.sira,
            is_active=payload.is_active,
            version=payload.version,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_hold_reasons",
        "tanim.ekle" if not eski else "tanim.duzelt",
        entity_id=satir.kod,
        old_value=eski or None,
        new_value=yeni,
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(satir)
    return _neden_cikti(satir)


# --- Seri → mobilite cihaz kütüğü bağı (TS-193, E01-10; D3-C — yalnız okuma) ---------
#
# Cihaz kartının "Servis İşleri" sekmesi ve servis işinin cihaz eşleşmesi.
# `devices`'a ve `service_order_serials.device_id`'ye YAZILMAZ; eşleşme okuma
# anında kurulur (`is_emirleri.cihaz_servis_isleri_sorgusu`). Cihaz kapsamı
# canlı cihaz kartı kuralıdır (mevcut davranış); iş listesi `kapsam_isler` ile.

CihazOkuyucu = Annotated[User, Depends(require_permission("servis.gor", "cihaz.gor"))]


@router.get("/cihaz-servis-isleri", response_model=None)
async def cihaz_servis_isleri(
    db: DbDep,
    user: CihazOkuyucu,
    response: Response,
    cihaz_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Mobilite cihazının (IMEI/seri) MOBILITE/ARAC_TAKIP servis işleri; sayfalı."""
    from app.models import Device

    cihaz = await db.get(Device, cihaz_id)
    if cihaz is None or cihaz.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cihaz bulunamadı")
    stmt = is_emirleri.cihaz_servis_isleri_sorgusu(user, cihaz.imei, cihaz.serial_no)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _satirlar(db, [s for (s,) in satirlar], user)


@router.get("/isler/{so_id}/cihaz-eslesmeleri", response_model=None)
async def cihaz_eslesmeleri(so_id: int, db: DbDep, user: CihazOkuyucu) -> list[dict[str, Any]]:
    """İşin serilerinin cihaz kütüğü karşılığı (TEK / BELIRSIZ / KUTUKTE_YOK)."""
    so = await _kapsamli_is(db, so_id, user)
    return await is_emirleri.seri_cihaz_eslesmeleri(db, so)
