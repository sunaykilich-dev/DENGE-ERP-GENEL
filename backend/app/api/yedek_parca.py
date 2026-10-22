"""Yedek parça ve servis stoğu uçları (TS-130…138).

Kurallar (plan §2.3, §4.5, E11):

- **İzinler:** `parca.gor` okuma; `parca.kullan` açık servis işine çıkış,
  iade ve parça talebi; `parca.yonet` giriş, transfer, zayi, ters kayıt,
  sayım/onay, açılış stoğu, parça kartı. Excel `parca.gor` +
  `servis_rapor.disaaktar` (KD-06). Servis deposu tanımı `sistem.ayar` (K15).
- **Maliyet:** `unit_cost` girişte `parca.yonet` ile YAZILIR; yanıtta
  `unit_cost` / `tutar` anahtarları YALNIZ `maliyet.gor` (sees_cost) sahibine
  eklenir — görmeyenin yanıtında anahtar YOKTUR (null da değil).
- **Kapsam:** depo kümesi `parca.depo_kosulu`; servis işi `kapsam.is_erisimi_yok_mu`.
  URL'deki ya da gövdedeki kapsam dışı depo/iş/hareket/sayım/talep → 404 ve
  hiçbir yazma yapılmaz (kontrol yazmadan ÖNCE).
- **Hata kodları:** kural ihlali 409 (makine okunur ek alanlarla), girdi 400,
  şema 422 (`extra="forbid"`: giriş gövdesinde `service_order_id` 422 — E11-03).
- Statik yollar (`/stok/ozet`, `/stok.xlsx`, `/hareketler.xlsx`) kimlikli
  yollardan ÖNCE tanımlanır. Gövde modelleri `json_schema_extra` örneği taşır
  (uç taraması geçerli gövdeyle 404'ü sınasın).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala, sees_cost
from app.models import (
    Product,
    ServiceOrder,
    ServicePartRequest,
    StockCount,
    StockCountLine,
    StockMovement,
    User,
    Warehouse,
)
from app.models.catalog import OLCU_BIRIMLERI
from app.models.stock import KONUM_TIPLERI
from app.permissions import BIRIMLER
from app.services import audit
from app.services import export as export_svc
from app.services.teknik_servis import kapsam
from app.services.teknik_servis import parca as svc
from app.services.teknik_servis.is_emirleri import IsEmriYetkiHatasi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.parca import ParcaBulunamadi, ParcaHatasi, Satir
from app.services.teknik_servis.yerel_zaman import yerel_an

router = APIRouter(prefix="/api/teknik-servis/parca", tags=["yedek-parca"])

Okuyucu = Annotated[User, Depends(require_permission("parca.gor"))]
Kullanici = Annotated[User, Depends(require_permission("parca.kullan"))]
Yonetici = Annotated[User, Depends(require_permission("parca.yonet"))]
Aktarici = Annotated[User, Depends(require_permission("parca.gor", "servis_rapor.disaaktar"))]
IsOkuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
DepoTanimci = Annotated[User, Depends(require_permission("sistem.ayar"))]

EXCEL_UST_SINIR = 20_000
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _hata(exc: Exception) -> HTTPException:
    """Servis hatasını HTTP'ye çevirir: 404 yok/kapsam dışı, 400 girdi, 409 kural."""
    if isinstance(exc, ParcaBulunamadi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc) or "Kayıt bulunamadı")
    if isinstance(exc, IsEmriYetkiHatasi):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, ServisGirdiHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, ParcaHatasi) and exc.veri:
        return HTTPException(status.HTTP_409_CONFLICT, {"mesaj": exc.mesaj, **exc.veri})
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


_HATALAR = (ParcaBulunamadi, ServisHatasi, ServisGirdiHatasi)


def _zaman(an: datetime | None) -> str:
    return yerel_an(an).strftime("%d.%m.%Y %H:%M") if an else ""


def _maliyet_ekle(cikti: dict[str, Any], user: User, maliyet: Decimal | None, adet: int) -> None:
    """Maliyet anahtarları YALNIZ `maliyet.gor` sahibine (yoksa anahtar hiç yok)."""
    if not sees_cost(user):
        return
    cikti["unit_cost"] = float(maliyet) if maliyet is not None else None
    cikti["tutar"] = float(maliyet * abs(adet)) if maliyet is not None else None


# --- Şemalar ---------------------------------------------------------------------------


class _Kati(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SatirIn(_Kati):
    product_id: int
    # Tam sayı: 1.5 → 422 (E11-11). Birim (METRE...) yalnız gösterimdir.
    adet: int = Field(gt=0, le=1_000_000)


class GirisSatiriIn(SatirIn):
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)


class GirisIn(_Kati):
    """Servis deposuna giriş. `service_order_id` YOK: iş emirli giriş = örtük
    iade hatası yeni sistemde oluşmaz (E11-03; alan gelirse 422)."""

    depo_id: int
    document_no: str | None = Field(default=None, max_length=svc.BELGE_UZUNLUGU)
    notes: str | None = Field(default=None, max_length=svc.NOT_UZUNLUGU)
    satirlar: list[GirisSatiriIn] = Field(min_length=1, max_length=svc.TOPLU_SATIR_UST_SINIR)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "depo_id": 1,
                    "document_no": "IRS-2026-001",
                    "satirlar": [{"product_id": 1, "adet": 10}],
                }
            ]
        },
    )


class IsHareketiIn(_Kati):
    service_order_id: int
    depo_id: int
    notes: str | None = Field(default=None, max_length=svc.NOT_UZUNLUGU)
    satirlar: list[SatirIn] = Field(min_length=1, max_length=svc.TOPLU_SATIR_UST_SINIR)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"service_order_id": 1, "depo_id": 1, "satirlar": [{"product_id": 1, "adet": 1}]}
            ]
        },
    )


class ZayiIn(_Kati):
    depo_id: int
    gerekce: str = Field(min_length=3, max_length=svc.NOT_UZUNLUGU)
    satirlar: list[SatirIn] = Field(min_length=1, max_length=svc.TOPLU_SATIR_UST_SINIR)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"depo_id": 1, "gerekce": "Kırık", "satirlar": [{"product_id": 1, "adet": 1}]}
            ]
        },
    )


class TransferIn(_Kati):
    kaynak_depo_id: int
    hedef_depo_id: int
    notes: str | None = Field(default=None, max_length=svc.NOT_UZUNLUGU)
    satirlar: list[SatirIn] = Field(min_length=1, max_length=svc.TOPLU_SATIR_UST_SINIR)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "kaynak_depo_id": 1,
                    "hedef_depo_id": 2,
                    "satirlar": [{"product_id": 1, "adet": 1}],
                }
            ]
        },
    )


class GerekceIn(_Kati):
    gerekce: str = Field(min_length=3, max_length=svc.NOT_UZUNLUGU)

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"gerekce": "Yanlış depoya girildi"}]}
    )


class AcilisSatiriIn(_Kati):
    product_id: int
    depo_id: int
    adet: int = Field(gt=0, le=1_000_000)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    notes: str | None = Field(default=None, max_length=svc.NOT_UZUNLUGU)


class AcilisIn(_Kati):
    satirlar: list[AcilisSatiriIn] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"satirlar": [{"product_id": 1, "depo_id": 1, "adet": 5}]}]
        },
    )


class SayimIn(_Kati):
    depo_id: int
    notes: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"depo_id": 1}]})


class SayimSatiriIn(_Kati):
    product_id: int
    sayilan_adet: int | None = Field(default=None, ge=0, le=1_000_000)


class SayimSatirlariIn(_Kati):
    satirlar: list[SayimSatiriIn] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"satirlar": [{"product_id": 1, "sayilan_adet": 3}]}]},
    )


class SayimOnayIn(_Kati):
    gerekce: str = Field(min_length=3, max_length=500)
    degisimi_kabul: bool = False

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"gerekce": "Yıl sonu sayımı"}]}
    )


class TalepIn(_Kati):
    service_order_id: int
    product_id: int
    adet: int = Field(gt=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=500)
    isi_beklet: bool = False

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"service_order_id": 1, "product_id": 1, "adet": 1}]},
    )


class TalepIptalIn(_Kati):
    neden: str = Field(min_length=3, max_length=200)

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"neden": "Müşteri vazgeçti"}]}
    )


class KartIn(_Kati):
    """Yedek parça kartı (E11-12): `type='AKSESUAR'`, `identity_kind='YOK'`,
    `yedek_parca=true`; FİYAT ALANI YOK (`urun.yaz` olmadan kart açılabilsin)."""

    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    brand: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    supplier_code: str | None = Field(default=None, max_length=60)
    birim: str | None = Field(default=None, max_length=10)
    min_stok: int | None = Field(default=None, ge=0, le=1_000_000)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"code": "YP-KABLO-01", "name": "Koaksiyel kablo"}]},
    )


class KartPatch(_Kati):
    """Yalnız stok alanları + iyimser kilit; ad/kod/aktiflik katalogdan
    (`urun.yaz`). `is_active` gelirse 422 (E11-12 kabul 4)."""

    product_id: int
    version: int
    yedek_parca: bool | None = None
    birim: str | None = Field(default=None, max_length=10)
    min_stok: int | None = Field(default=None, ge=0, le=1_000_000)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"product_id": 1, "version": 1, "min_stok": 5}]},
    )


class DepoIn(_Kati):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=100)
    birim: str | None = Field(default=None, max_length=20)
    location_type: str = Field(default="BOLGE_DEPO", max_length=20)
    # Teknisyen araç deposu: location_type='TEKNISYEN' + user_id.
    user_id: int | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"code": "SRV-GUV", "name": "Güvenlik Servis Deposu"}]},
    )


class DepoPatch(_Kati):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    birim: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    user_id: int | None = None

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"name": "Yeni ad"}]})


# --- Yardımcılar ---------------------------------------------------------------------------


def _satirlar(girdi: list[SatirIn] | list[GirisSatiriIn]) -> list[Satir]:
    return [Satir(s.product_id, s.adet, getattr(s, "unit_cost", None)) for s in girdi]


async def _depo(db: DbDep, user: User, depo_id: int) -> Warehouse:
    try:
        return await svc.depo_getir(db, user, depo_id)
    except ParcaBulunamadi as exc:
        raise _hata(exc) from exc


async def _is(db: DbDep, user: User, so_id: int) -> ServiceOrder:
    try:
        return await svc.is_getir(db, user, so_id)
    except ParcaBulunamadi as exc:
        raise _hata(exc) from exc


async def _hareket_ciktilari(
    db: DbDep, user: User, hareketler: list[StockMovement]
) -> list[dict[str, Any]]:
    urunler = {
        u.id: u
        for u in (
            await db.scalars(
                select(Product).where(Product.id.in_({h.product_id for h in hareketler}))
            )
        ).all()
    }
    sonuc = []
    for h in hareketler:
        u = urunler.get(h.product_id)
        cikti: dict[str, Any] = {
            "id": h.id,
            "tur": h.hareket_turu,
            "product_id": h.product_id,
            "kod": u.code if u else None,
            "depo_id": h.warehouse_id,
            "adet": h.qty,
            "service_order_id": h.service_order_id,
            "transfer_grup": str(h.transfer_grup) if h.transfer_grup else None,
        }
        _maliyet_ekle(cikti, user, h.unit_cost, h.qty)
        sonuc.append(cikti)
    return sonuc


async def _denetim(
    db: DbDep,
    request: Request,
    user: User,
    eylem: str,
    hareketler: list[StockMovement],
    **ek: Any,
) -> None:
    """Denetim izi commit'ten ÖNCE, aynı transaction'da (maliyet yazılmaz)."""
    await audit.log(
        db,
        "stock_movements",
        f"parca.{eylem}",
        entity_id=hareketler[0].id if hareketler else None,
        new_value={
            "hareketler": [
                {
                    "id": h.id,
                    "tur": h.hareket_turu,
                    "product_id": h.product_id,
                    "depo_id": h.warehouse_id,
                    "adet": h.qty,
                    "service_order_id": h.service_order_id,
                }
                for h in hareketler
            ],
            **ek,
        },
        user_id=user.id,
        ip=client_ip(request),
    )


# --- Depolar (TS-131) ------------------------------------------------------------------------


def _depo_cikti(w: Warehouse, user: User) -> dict[str, Any]:
    return {
        "id": w.id,
        "code": w.code,
        "name": w.name,
        "birim": w.birim,
        "location_type": w.location_type,
        "user_id": w.user_id,
        "is_active": w.is_active,
        "kendi_araci": w.location_type == "TEKNISYEN" and w.user_id == user.id,
    }


@router.get("/depolar")
async def depolar(db: DbDep, user: Okuyucu, pasifler: bool = False) -> list[dict[str, Any]]:
    """Kullanıcının erişebildiği servis depoları (teknisyende kendi araç deposu
    `kendi_araci=true`; çıkış formunda varsayılan)."""
    stmt = select(Warehouse).where(svc.depo_kosulu(user)).order_by(Warehouse.name)
    if not pasifler:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return [_depo_cikti(w, user) for w in (await db.scalars(stmt)).all()]


def _birim_dogrula(birim: str | None) -> None:
    if birim is not None and birim not in BIRIMLER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {birim}")


async def _arac_sahibi_dogrula(db: DbDep, user_id: int | None, location_type: str) -> None:
    if location_type not in KONUM_TIPLERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Konum tipi geçersiz: {location_type}")
    if location_type == "TEKNISYEN" and user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Araç deposunda teknisyen seçilmeli")
    if user_id is not None and await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")


@router.post("/depolar", status_code=status.HTTP_201_CREATED)
async def depo_olustur(
    payload: DepoIn, request: Request, db: DbDep, user: DepoTanimci
) -> dict[str, Any]:
    """Servis deposu tanımı (`sistem.ayar`, K15). Kiralama deposu olamaz
    (`ck_warehouse_tur_tekil`); mobilite uçları bu depoyu görmez."""
    _birim_dogrula(payload.birim)
    if kapsam.birim_disinda_mi(user, payload.birim):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Birim bulunamadı")
    await _arac_sahibi_dogrula(db, payload.user_id, payload.location_type)
    if await db.scalar(select(Warehouse.id).where(Warehouse.code == payload.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu depo kodu zaten kayıtlı.")
    depo = Warehouse(**payload.model_dump(), servis_deposu=True, kiralama_deposu=False)
    db.add(depo)
    await db.flush()
    await audit.log(
        db,
        "warehouses",
        "parca.depo_olustur",
        entity_id=depo.id,
        new_value=payload.model_dump(),
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _depo_cikti(depo, user)


@router.patch("/depolar/{depo_id}")
async def depo_guncelle(
    depo_id: int, payload: DepoPatch, request: Request, db: DbDep, user: DepoTanimci
) -> dict[str, Any]:
    depo = await _depo(db, user, depo_id)
    degisen = payload.model_dump(exclude_unset=True)
    if "birim" in degisen:
        _birim_dogrula(degisen["birim"])
        if kapsam.birim_degisimi_yasak_mi(user, depo.birim, degisen["birim"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Depo bulunamadı")
    if "user_id" in degisen:
        await _arac_sahibi_dogrula(db, degisen["user_id"], depo.location_type)
    for alan, deger in degisen.items():
        setattr(depo, alan, deger)
    await audit.log_change(db, depo, "parca.depo_guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    return _depo_cikti(depo, user)


# --- Parça kartı (TS-135) ---------------------------------------------------------------------


def _kart_cikti(u: Product) -> dict[str, Any]:
    return {
        "id": u.id,
        "code": u.code,
        "name": u.name,
        "brand": u.brand,
        "model": u.model,
        "supplier_code": u.supplier_code,
        "birim": u.birim,
        "min_stok": u.min_stok,
        "yedek_parca": u.yedek_parca,
        "is_active": u.is_active,
        "version": u.version,
    }


def _olcu_birimi(birim: str | None) -> None:
    if birim is not None and birim not in OLCU_BIRIMLERI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Ölçü birimi {', '.join(OLCU_BIRIMLERI)} içinden olmalı"
        )


@router.get("/parcalar")
async def parca_secenekleri(
    db: DbDep,
    user: Okuyucu,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Formlardaki parça seçicisi: aktif yedek parça kartları (sayısal kimlik
    yazdırılmaz; kod/ad/marka ile aranır)."""
    stmt = svc.stok_sorgusu(user, svc.StokSuzgeci(q=q)).limit(limit)
    return [
        {"id": u.id, "code": u.code, "name": u.name, "birim": u.birim or "ADET", "toplam": int(t)}
        for u, t, _d in (await db.execute(stmt)).all()
    ]


@router.post("/kartlar", status_code=status.HTTP_201_CREATED)
async def kart_olustur(
    payload: KartIn, request: Request, db: DbDep, user: Yonetici
) -> dict[str, Any]:
    _olcu_birimi(payload.birim)
    if await db.scalar(select(Product.id).where(Product.code == payload.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu parça kodu zaten kayıtlı.")
    urun = Product(
        **payload.model_dump(),
        type="AKSESUAR",
        identity_kind="YOK",
        yedek_parca=True,
        created_by=user.id,
    )
    db.add(urun)
    await db.flush()
    await audit.log(
        db,
        "products",
        "parca.kart_olustur",
        entity_id=urun.id,
        new_value={"code": urun.code, "name": urun.name, "birim": urun.birim},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(urun)
    return _kart_cikti(urun)


@router.patch("/kartlar")
async def kart_guncelle(
    payload: KartPatch, request: Request, db: DbDep, user: Yonetici
) -> dict[str, Any]:
    """Parça kartının stok alanları (`yedek_parca`, `birim`, `min_stok`).

    Ürün katalog kaydıdır (birimsiz, ortak) — kapsamı yoktur; kimlik gövdede.
    """
    urun = await db.get(Product, payload.product_id)
    if urun is None or urun.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parça bulunamadı")
    if payload.version != urun.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    degisen = payload.model_dump(exclude_unset=True, exclude={"product_id", "version"})
    if "birim" in degisen:
        _olcu_birimi(degisen["birim"])
    if degisen.get("yedek_parca") and urun.identity_kind != "YOK":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{urun.code} seri numarasıyla izleniyor; yedek parça olarak adetle izlenemez.",
        )
    if degisen.get("yedek_parca") is False:
        servis_hareketi = await db.scalar(
            select(func.count()).where(
                StockMovement.product_id == urun.id, StockMovement.hareket_turu.is_not(None)
            )
        )
        if servis_hareketi:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Servis deposunda hareketi olan parçanın yedek parça işareti kaldırılamaz.",
            )
    for alan, deger in degisen.items():
        setattr(urun, alan, deger)
    urun.updated_by = user.id
    await audit.log_change(db, urun, "parca.kart_guncelle", user_id=user.id, ip=client_ip(request))
    await db.commit()
    await db.refresh(urun)
    return _kart_cikti(urun)


# --- Stok (TS-135, 136) ----------------------------------------------------------------------


def _suzgec(
    q: Annotated[str | None, Query(max_length=80)] = None,
    depo_id: int | None = None,
    durum: Annotated[str | None, Query(max_length=10)] = None,
    esikli: bool = False,
    pasifler: bool = False,
) -> svc.StokSuzgeci:
    return svc.StokSuzgeci(q=q, depo_id=depo_id, durum=durum, esikli=esikli, pasifler=pasifler)


StokSuzgec = Annotated[svc.StokSuzgeci, Depends(_suzgec)]


async def _stok_satirlari(
    db: DbDep, user: User, satirlar: list[Any], depo_id: int | None
) -> list[dict[str, Any]]:
    idler = [u.id for u, _t, _d in satirlar]
    depolar = {
        w.id: w
        for w in (await db.scalars(select(Warehouse).where(svc.depo_kosulu(user)))).all()
        if depo_id is None or w.id == depo_id
    }
    kirilim = await svc.bakiyeler(db, depo_idler=list(depolar), product_idler=idler)
    sonuc = []
    for u, toplam, durum in satirlar:
        sonuc.append(
            {
                "product_id": u.id,
                "kod": u.code,
                "ad": u.name,
                "marka": u.brand,
                "model": u.model,
                "birim": u.birim or "ADET",
                "min_stok": u.min_stok,
                "is_active": u.is_active,
                "version": u.version,
                "toplam": int(toplam),
                "durum": durum,
                "depolar": [
                    {
                        "depo_id": w,
                        "depo_kodu": depolar[w].code,
                        "depo_adi": depolar[w].name,
                        "adet": adet,
                    }
                    for (p, w), adet in sorted(kirilim.items(), key=lambda x: x[0][1])
                    if p == u.id
                ],
            }
        )
    return sonuc


@router.get("/stok")
async def stok_listesi(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    s: StokSuzgec,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Parça başına toplam (erişilebilir servis depoları) + depo kırılımı."""
    try:
        stmt = svc.stok_sorgusu(user, s)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _stok_satirlari(db, user, list(satirlar), s.depo_id)


@router.get("/stok/ozet")
async def stok_ozeti(db: DbDep, clock: ClockDep, user: Okuyucu) -> dict[str, int]:
    """KPI kutuları: Az stok, Stok yok, Açık talep, Açık sayım, Bugünkü çıkış —
    her biri tıklanınca açılan listenin `X-Toplam-Kayit` değeriyle aynı sorgu."""
    return await svc.ozet(db, user, clock)


@router.get("/stok.xlsx")
async def stok_excel(db: DbDep, user: Aktarici, s: StokSuzgec) -> Response:
    try:
        stmt = svc.stok_sorgusu(user, s)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    if await svc.say(db, stmt) > EXCEL_UST_SINIR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Süzgeci daraltın; satır sayısı çok fazla")
    tablo = [
        [
            u.code,
            u.name,
            u.brand or "",
            u.model or "",
            u.birim or "ADET",
            u.min_stok if u.min_stok is not None else "",
            int(t),
            svc.STOK_DURUM_ADLARI.get(d, d),
        ]
        for u, t, d in (await db.execute(stmt)).all()
    ]
    return Response(
        content=await export_svc.satirlari_xlsx_async(
            ["Kod", "Ad", "Marka", "Model", "Birim", "Asgari", "Toplam", "Durum"],
            tablo,
            "Yedek Parça Stoğu",
        ),
        media_type=_XLSX,
        headers={"Content-Disposition": 'attachment; filename="yedek-parca-stok.xlsx"'},
    )


# --- Hareketler (TS-136) -----------------------------------------------------------------------


def _hareket_suzgeci(
    product_id: int | None = None,
    depo_id: int | None = None,
    tur: Annotated[str | None, Query(max_length=20)] = None,
    so_no: Annotated[str | None, Query(max_length=30)] = None,
    belge: Annotated[str | None, Query(max_length=60)] = None,
    bas: date | None = None,
    bit: date | None = None,
) -> svc.HareketSuzgeci:
    return svc.HareketSuzgeci(
        product_id=product_id, depo_id=depo_id, tur=tur, so_no=so_no, belge=belge, bas=bas, bit=bit
    )


HareketSuzgec = Annotated[svc.HareketSuzgeci, Depends(_hareket_suzgeci)]


async def _kullanici_adlari(db: DbDep, idler: set[int]) -> dict[int, str]:
    if not idler:
        return {}
    return dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(idler)))).all())


async def _hareket_satirlari(db: DbDep, user: User, satirlar: list[Any]) -> list[dict[str, Any]]:
    adlar = await _kullanici_adlari(db, {h.created_by for h, *_ in satirlar if h.created_by})
    sonuc = []
    for h, u, w, so_no, ters_var in satirlar:
        cikti: dict[str, Any] = {
            "id": h.id,
            "created_at": h.created_at,
            "tur": h.hareket_turu,
            "tur_adi": svc.HAREKET_TURU_ADLARI.get(h.hareket_turu, h.hareket_turu),
            "product_id": h.product_id,
            "kod": u.code,
            "ad": u.name,
            "birim": u.birim or "ADET",
            "depo_id": h.warehouse_id,
            "depo_kodu": w.code,
            "depo_adi": w.name,
            "adet": h.qty,
            "document_no": h.document_no,
            "notes": h.notes,
            "service_order_id": h.service_order_id,
            "so_no": so_no,
            "reversal_of_id": h.reversal_of_id,
            "ters_kaydi_var": bool(ters_var),
            "transfer_grup": str(h.transfer_grup) if h.transfer_grup else None,
            "stock_count_id": h.stock_count_id,
            "part_request_id": h.part_request_id,
            "kullanici": adlar.get(h.created_by) if h.created_by else None,
        }
        _maliyet_ekle(cikti, user, h.unit_cost, h.qty)
        sonuc.append(cikti)
    return sonuc


@router.get("/hareketler")
async def hareketler(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    s: HareketSuzgec,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Servis defteri: en yeni önce (created_at, id). Yalnız erişilebilir
    depolar ve kapsam içi işler; maliyet anahtarı yalnız `maliyet.gor`."""
    try:
        stmt = svc.hareket_sorgusu(user, s)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    return await _hareket_satirlari(
        db, user, list(await sayfala(db, response, stmt, limit=limit, offset=offset))
    )


@router.get("/hareketler.xlsx")
async def hareketler_excel(db: DbDep, user: Aktarici, s: HareketSuzgec) -> Response:
    """Ekrandaki süzgecin aynı satırları; formül enjeksiyonu korumalı (not
    `=HYPERLINK(...)` metin kalır); maliyet sütunu yalnız `maliyet.gor`."""
    try:
        stmt = svc.hareket_sorgusu(user, s)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    if await svc.say(db, stmt) > EXCEL_UST_SINIR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Süzgeci daraltın; satır sayısı çok fazla")
    satirlar = await _hareket_satirlari(db, user, list((await db.execute(stmt)).all()))
    maliyetli = sees_cost(user)
    basliklar = [
        "Tarih",
        "Tür",
        "Kod",
        "Parça",
        "Depo",
        "Adet",
        "Servis işi",
        "Belge no",
        "Not",
        "Kullanıcı",
    ] + (["Birim maliyet", "Tutar"] if maliyetli else [])
    tablo = []
    for r in satirlar:
        satir = [
            _zaman(r["created_at"]),
            r["tur_adi"],
            r["kod"],
            r["ad"],
            r["depo_adi"],
            r["adet"],
            r["so_no"] or "",
            r["document_no"] or "",
            r["notes"] or "",
            r["kullanici"] or "",
        ]
        if maliyetli:
            satir += [r["unit_cost"] or "", r["tutar"] or ""]
        tablo.append(satir)
    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, tablo, "Parça Hareketleri"),
        media_type=_XLSX,
        headers={"Content-Disposition": 'attachment; filename="parca-hareketleri.xlsx"'},
    )


# --- Yazma uçları (TS-130…134, 137) ----------------------------------------------------------


@router.post("/giris", status_code=status.HTTP_201_CREATED)
async def giris(
    payload: GirisIn, request: Request, db: DbDep, clock: ClockDep, user: Yonetici
) -> list[dict[str, Any]]:
    depo = await _depo(db, user, payload.depo_id)
    try:
        hareketler = await svc.hareket_yaz(
            db,
            tur="GIRIS",
            satirlar=_satirlar(payload.satirlar),
            user=user,
            clock=clock,
            warehouse_id=depo.id,
            document_no=payload.document_no,
            notes=payload.notes,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _denetim(db, request, user, "giris", hareketler, belge=payload.document_no)
    await db.commit()
    return await _hareket_ciktilari(db, user, hareketler)


@router.post("/cikis", status_code=status.HTTP_201_CREATED)
async def cikis(
    payload: IsHareketiIn, request: Request, db: DbDep, clock: ClockDep, user: Kullanici
) -> list[dict[str, Any]]:
    """Açık servis işine toplu çıkış (tek transaction). Kapalı iş 409; stok
    yetersiz 409 ve hiçbir satır yazılmaz; kapsam dışı iş/depo 404."""
    so = await _is(db, user, payload.service_order_id)
    depo = await _depo(db, user, payload.depo_id)
    try:
        hareketler = await svc.cikis_yap(
            db,
            so=so,
            depo=depo,
            satirlar=_satirlar(payload.satirlar),
            user=user,
            clock=clock,
            notes=payload.notes,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _denetim(db, request, user, "cikis", hareketler, so_no=so.so_no)
    await db.commit()
    return await _hareket_ciktilari(db, user, hareketler)


@router.post("/iade", status_code=status.HTTP_201_CREATED)
async def iade(
    payload: IsHareketiIn, request: Request, db: DbDep, clock: ClockDep, user: Kullanici
) -> list[dict[str, Any]]:
    """İşten depoya iade; net çıkışla sınırlı (aşarsa 409). Kapalı işte serbest."""
    so = await _is(db, user, payload.service_order_id)
    depo = await _depo(db, user, payload.depo_id)
    try:
        hareketler = await svc.iade_al(
            db,
            so=so,
            depo=depo,
            satirlar=_satirlar(payload.satirlar),
            user=user,
            clock=clock,
            notes=payload.notes,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _denetim(db, request, user, "iade", hareketler, so_no=so.so_no)
    await db.commit()
    return await _hareket_ciktilari(db, user, hareketler)


@router.post("/zayi", status_code=status.HTTP_201_CREATED)
async def zayi(
    payload: ZayiIn, request: Request, db: DbDep, clock: ClockDep, user: Yonetici
) -> list[dict[str, Any]]:
    depo = await _depo(db, user, payload.depo_id)
    try:
        hareketler = await svc.hareket_yaz(
            db,
            tur="ZAYI",
            satirlar=_satirlar(payload.satirlar),
            user=user,
            clock=clock,
            warehouse_id=depo.id,
            notes=payload.gerekce,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _denetim(db, request, user, "zayi", hareketler, gerekce=payload.gerekce)
    await db.commit()
    return await _hareket_ciktilari(db, user, hareketler)


@router.post("/transfer", status_code=status.HTTP_201_CREATED)
async def transfer(
    payload: TransferIn, request: Request, db: DbDep, clock: ClockDep, user: Yonetici
) -> dict[str, Any]:
    kaynak = await _depo(db, user, payload.kaynak_depo_id)
    hedef = await _depo(db, user, payload.hedef_depo_id)
    try:
        grup, hareketler = await svc.transfer_yap(
            db,
            kaynak=kaynak,
            hedef=hedef,
            satirlar=_satirlar(payload.satirlar),
            user=user,
            clock=clock,
            notes=payload.notes,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _denetim(db, request, user, "transfer", hareketler, transfer_grup=str(grup))
    await db.commit()
    return {
        "transfer_grup": str(grup),
        "hareketler": await _hareket_ciktilari(db, user, hareketler),
    }


async def _hareket_getir(db: DbDep, user: User, hareket_id: int) -> StockMovement:
    """Kapsam içi servis defteri satırı; değilse 404 (yazma yok)."""
    hareket = await db.scalar(
        select(StockMovement).where(StockMovement.id == hareket_id, svc.hareket_kapsami(user))
    )
    if hareket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hareket bulunamadı")
    return hareket


@router.post("/hareketler/{hareket_id}/ters-kayit", status_code=status.HTTP_201_CREATED)
async def ters_kayit(
    hareket_id: int,
    payload: GerekceIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yonetici,
) -> list[dict[str, Any]]:
    """Tek seferlik ters kayıt (gerekçe zorunlu). Transfer bacağında grubun iki
    bacağı birlikte; ters kaydın ters kaydı, sayım farkı ve kapalı işteki
    iadenin ters kaydı 409."""
    hareket = await _hareket_getir(db, user, hareket_id)
    try:
        hareketler = await svc.ters_kayit(
            db, hareket=hareket, gerekce=payload.gerekce, user=user, clock=clock
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _denetim(db, request, user, "ters_kayit", hareketler, orijinal=hareket.id)
    await db.commit()
    return await _hareket_ciktilari(db, user, hareketler)


@router.post("/acilis", status_code=status.HTTP_201_CREATED)
async def acilis(
    payload: AcilisIn, request: Request, db: DbDep, clock: ClockDep, user: Yonetici
) -> dict[str, Any]:
    """Açılış stoğu (hepsi-ya-hiç). Hatalı satır varsa 409 + satır numaraları;
    hiçbir hareket yazılmaz. Excel'den yükleme İçe Aktarma ekranında
    (`parca_acilis` profili) aynı servis fonksiyonunu çağırır."""
    satirlar = [
        svc.AcilisSatiri(
            satir_no=i,
            product_id=s.product_id,
            depo_id=s.depo_id,
            adet=s.adet,
            unit_cost=s.unit_cost,
            notes=s.notes,
        )
        for i, s in enumerate(payload.satirlar, start=1)
    ]
    try:
        hareketler = await svc.acilis_yukle(db, satirlar, user=user, clock=clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _denetim(db, request, user, "acilis", hareketler, satir=len(hareketler))
    await db.commit()
    return {"yazilan": len(hareketler)}


# --- Servis işinin parçaları (TS-133) ----------------------------------------------------------


@router.get("/isler/{so_id}/parcalar")
async def is_parcalari(so_id: int, db: DbDep, user: IsOkuyucu) -> dict[str, Any]:
    """Servis işi / PB formu / atölye detayındaki "Kullanılan Parçalar" (aynı
    bileşen). Net adet parça başına; açık talepler; maliyet yalnız
    `maliyet.gor`. Servis işi kapsamı uygulanır (kapsam dışı 404)."""
    so = await _is(db, user, so_id)
    satirlar = (
        await db.execute(
            select(StockMovement, Product, Warehouse)
            .join(Product, Product.id == StockMovement.product_id)
            .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
            .where(StockMovement.service_order_id == so.id)
            .order_by(StockMovement.created_at, StockMovement.id)
        )
    ).all()
    adlar = await _kullanici_adlari(db, {h.created_by for h, _u, _w in satirlar if h.created_by})
    tersler = {h.reversal_of_id for h, _u, _w in satirlar if h.reversal_of_id}
    hareket_listesi = []
    net: dict[int, dict[str, Any]] = {}
    for h, u, w in satirlar:
        cikti: dict[str, Any] = {
            "id": h.id,
            "created_at": h.created_at,
            "tur": h.hareket_turu,
            "tur_adi": svc.HAREKET_TURU_ADLARI.get(h.hareket_turu, h.hareket_turu),
            "product_id": u.id,
            "kod": u.code,
            "ad": u.name,
            "birim": u.birim or "ADET",
            "depo_id": w.id,
            "depo_adi": w.name,
            "adet": h.qty,
            "ters_kaydi_var": h.id in tersler,
            "kullanici": adlar.get(h.created_by) if h.created_by else None,
        }
        _maliyet_ekle(cikti, user, h.unit_cost, h.qty)
        hareket_listesi.append(cikti)
        ozet = net.setdefault(
            u.id,
            {"product_id": u.id, "kod": u.code, "ad": u.name, "birim": u.birim or "ADET", "net": 0},
        )
        ozet["net"] -= h.qty
        if sees_cost(user):
            ozet.setdefault("tutar", 0.0)
            ozet.setdefault("maliyet_eksik", False)
            if h.unit_cost is None:
                ozet["maliyet_eksik"] = True
            else:
                ozet["tutar"] -= float(h.unit_cost * h.qty)
    talepler = (
        await db.execute(
            select(ServicePartRequest, Product)
            .join(Product, Product.id == ServicePartRequest.product_id)
            .where(
                ServicePartRequest.service_order_id == so.id,
                ServicePartRequest.is_deleted.is_(False),
            )
            .order_by(ServicePartRequest.id.desc())
        )
    ).all()
    return {
        "service_order_id": so.id,
        "so_no": so.so_no,
        "acik": so.status not in svc.KAPALI_SERVIS_DURUMLARI,
        "hareketler": hareket_listesi,
        "ozet": [o for o in net.values() if o["net"] != 0 or "tutar" in o],
        "talepler": [_talep_cikti(t, u, so.so_no) for t, u in talepler],
    }


# --- Parça talepleri (TS-138) -------------------------------------------------------------------


def _talep_cikti(t: ServicePartRequest, u: Product, so_no: str | None) -> dict[str, Any]:
    return {
        "id": t.id,
        "service_order_id": t.service_order_id,
        "so_no": so_no,
        "product_id": t.product_id,
        "kod": u.code,
        "ad": u.name,
        "adet": t.adet,
        "durum": t.durum,
        "notes": t.notes,
        "iptal_nedeni": t.iptal_nedeni,
        "karsilanma_at": t.karsilanma_at,
        "beklemeye_bagli": t.hold_id is not None,
        "created_at": t.created_at,
        "created_by": t.created_by,
        "version": t.version,
    }


@router.get("/talepler")
async def talepler(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    durum: Annotated[str | None, Query(max_length=12)] = None,
    service_order_id: int | None = None,
    benim: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    stmt = (
        svc.talep_sorgusu(user)
        .add_columns(Product, ServiceOrder.so_no)
        .join(Product, Product.id == ServicePartRequest.product_id)
        .join(ServiceOrder, ServiceOrder.id == ServicePartRequest.service_order_id)
        .order_by(ServicePartRequest.created_at.desc(), ServicePartRequest.id.desc())
    )
    if durum:
        stmt = stmt.where(ServicePartRequest.durum == durum)
    if service_order_id is not None:
        stmt = stmt.where(ServicePartRequest.service_order_id == service_order_id)
    if benim:
        stmt = stmt.where(ServicePartRequest.created_by == user.id)
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [_talep_cikti(t, u, so_no) for t, u, so_no in satirlar]


@router.post("/talepler", status_code=status.HTTP_201_CREATED)
async def talep_ac(
    payload: TalepIn, request: Request, db: DbDep, clock: ClockDep, user: Kullanici
) -> dict[str, Any]:
    """Açık işe parça talebi; `isi_beklet` ile MALZEME beklemesi. İş + parça
    başına tek açık talep (409)."""
    so = await _is(db, user, payload.service_order_id)
    try:
        talep = await svc.talep_ac(
            db,
            so=so,
            product_id=payload.product_id,
            adet=payload.adet,
            user=user,
            clock=clock,
            notes=payload.notes,
            isi_beklet=payload.isi_beklet,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_part_requests",
        "parca.talep_ac",
        entity_id=talep.id,
        new_value={
            "service_order_id": so.id,
            "product_id": talep.product_id,
            "adet": talep.adet,
            "isi_beklet": payload.isi_beklet,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    urun = await db.get(Product, talep.product_id)
    return _talep_cikti(talep, urun, so.so_no)


async def _talep_getir(db: DbDep, user: User, talep_id: int) -> ServicePartRequest:
    talep = await db.scalar(svc.talep_sorgusu(user).where(ServicePartRequest.id == talep_id))
    if talep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Talep bulunamadı")
    return talep


@router.post("/talepler/{talep_id}/iptal")
async def talep_iptal(
    talep_id: int,
    payload: TalepIptalIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Kullanici,
) -> dict[str, Any]:
    talep = await _talep_getir(db, user, talep_id)
    try:
        await svc.talep_iptal(db, talep, neden=payload.neden, user=user, clock=clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "service_part_requests",
        "parca.talep_iptal",
        entity_id=talep.id,
        new_value={"neden": payload.neden},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    urun = await db.get(Product, talep.product_id)
    so = await db.get(ServiceOrder, talep.service_order_id)
    return _talep_cikti(talep, urun, so.so_no if so else None)


# --- Sayım (TS-137) ------------------------------------------------------------------------------


async def _sayim_cikti(db: DbDep, sayim: StockCount, ayrinti: bool = False) -> dict[str, Any]:
    depo = await db.get(Warehouse, sayim.warehouse_id)
    cikti: dict[str, Any] = {
        "id": sayim.id,
        "count_no": sayim.count_no,
        "depo_id": sayim.warehouse_id,
        "depo_adi": depo.name if depo else None,
        "durum": sayim.durum,
        "baslangic_at": sayim.baslangic_at,
        "onay_at": sayim.onay_at,
        "onaylayan_id": sayim.onaylayan_id,
        "gerekce": sayim.gerekce,
        "notes": sayim.notes,
        "version": sayim.version,
    }
    if ayrinti:
        satirlar = (
            await db.execute(
                select(StockCountLine, Product)
                .join(Product, Product.id == StockCountLine.product_id)
                .where(StockCountLine.stock_count_id == sayim.id)
                .order_by(Product.code)
            )
        ).all()
        cikti["satirlar"] = [
            {
                "product_id": u.id,
                "kod": u.code,
                "ad": u.name,
                "birim": u.birim or "ADET",
                "sistem_adet": s.sistem_adet,
                "sayilan_adet": s.sayilan_adet,
                "onay_anindaki_adet": s.onay_anindaki_adet,
                "fark": (s.sayilan_adet - s.sistem_adet) if s.sayilan_adet is not None else None,
            }
            for s, u in satirlar
        ]
    return cikti


async def _sayim_getir(db: DbDep, user: User, sayim_id: int) -> StockCount:
    sayim = await db.scalar(svc.sayim_sorgusu(user).where(StockCount.id == sayim_id))
    if sayim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sayım bulunamadı")
    return sayim


@router.get("/sayimlar")
async def sayimlar(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    durum: Annotated[str | None, Query(max_length=12)] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    stmt = svc.sayim_sorgusu(user).order_by(StockCount.id.desc())
    if durum:
        stmt = stmt.where(StockCount.durum == durum)
    return [
        await _sayim_cikti(db, s)
        for (s,) in await sayfala(db, response, stmt, limit=limit, offset=offset)
    ]


@router.post("/sayimlar", status_code=status.HTTP_201_CREATED)
async def sayim_ac(
    payload: SayimIn, request: Request, db: DbDep, clock: ClockDep, user: Yonetici
) -> dict[str, Any]:
    depo = await _depo(db, user, payload.depo_id)
    try:
        sayim = await svc.sayim_ac(db, depo=depo, user=user, clock=clock, notes=payload.notes)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "stock_counts",
        "sayim.ac",
        entity_id=sayim.id,
        new_value={"count_no": sayim.count_no, "depo_id": depo.id},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _sayim_cikti(db, sayim, ayrinti=True)


@router.get("/sayimlar/{sayim_id}")
async def sayim_detay(sayim_id: int, db: DbDep, user: Okuyucu) -> dict[str, Any]:
    return await _sayim_cikti(db, await _sayim_getir(db, user, sayim_id), ayrinti=True)


@router.put("/sayimlar/{sayim_id}/satirlar")
async def sayim_satirlari(
    sayim_id: int, payload: SayimSatirlariIn, request: Request, db: DbDep, user: Yonetici
) -> dict[str, Any]:
    sayim = await _sayim_getir(db, user, sayim_id)
    try:
        await svc.sayim_satirlari_yaz(
            db, sayim, [(s.product_id, s.sayilan_adet) for s in payload.satirlar]
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "stock_counts",
        "sayim.satir",
        entity_id=sayim.id,
        new_value={"satir": len(payload.satirlar)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _sayim_cikti(db, sayim, ayrinti=True)


@router.post("/sayimlar/{sayim_id}/onayla")
async def sayim_onayla(
    sayim_id: int,
    payload: SayimOnayIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yonetici,
) -> dict[str, Any]:
    """Onay (gerekçe zorunlu). Açılıştan sonra stok değiştiyse ve
    `degisimi_kabul` yoksa 409 + `sapmalar`; onaysız fark hiçbir şey değiştirmez."""
    sayim = await _sayim_getir(db, user, sayim_id)
    try:
        hareketler = await svc.sayim_onayla(
            db,
            sayim,
            gerekce=payload.gerekce,
            degisimi_kabul=payload.degisimi_kabul,
            user=user,
            clock=clock,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "stock_counts",
        "sayim.onayla",
        entity_id=sayim.id,
        new_value={
            "gerekce": payload.gerekce,
            "degisimi_kabul": payload.degisimi_kabul,
            "hareketler": [h.id for h in hareketler],
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _sayim_cikti(db, sayim, ayrinti=True)


@router.post("/sayimlar/{sayim_id}/iptal")
async def sayim_iptal(
    sayim_id: int, payload: GerekceIn, request: Request, db: DbDep, user: Yonetici
) -> dict[str, Any]:
    sayim = await _sayim_getir(db, user, sayim_id)
    try:
        await svc.sayim_iptal(db, sayim, gerekce=payload.gerekce, user=user)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "stock_counts",
        "sayim.iptal",
        entity_id=sayim.id,
        new_value={"gerekce": payload.gerekce},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _sayim_cikti(db, sayim)
