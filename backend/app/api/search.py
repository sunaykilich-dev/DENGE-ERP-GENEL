"""Genel arama — tek kutudan IMEI, plaka, ICCID, şase, firma, ürün.

Brief bunu ayrı bir gereksinim olarak yazmamış ama kabul kriteri 1'in kendisi
bu ve mevcut uygulamada en çok kullanılan özellik. Modüller geldikçe
`ARAYICILAR` listesine yeni kaynak eklenir; arayüz değişmez.
"""

from typing import Annotated, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, require_permission
from app.models import Account, Device, Product, SimCard, User, Vehicle
from app.services import accounts as hesap_svc
from app.services.normalize import tr_normkey

router = APIRouter(prefix="/api/arama", tags=["arama"])

# Arama, kullanıcının zaten görebileceği kayıtları döndürür; her arayıcı
# kendi iznini ve kapsamını uygular.
Kullanici = Annotated[User, Depends(require_permission("hesap.gor"))]


class AramaSonucu(BaseModel):
    tur: str  # HESAP | URUN | CIHAZ | ARAC | HAT …
    id: int
    baslik: str
    alt_baslik: str | None = None
    etiketler: list[str] = []
    yol: str  # arayüzde gidilecek adres


class Arayici(Protocol):
    izin: str

    async def __call__(
        self, db: AsyncSession, user: User, terim: str, limit: int
    ) -> list[AramaSonucu]: ...


async def _hesap_ara(db: AsyncSession, user: User, terim: str, limit: int) -> list[AramaSonucu]:
    if not user.has("hesap.gor"):
        return []
    stmt = select(Account).where(Account.is_deleted.is_(False)).limit(limit)
    stmt = hesap_svc.kapsam_uygula(hesap_svc.arama_filtresi(stmt, terim), user)
    return [
        AramaSonucu(
            tur="HESAP",
            id=h.id,
            baslik=h.title,
            alt_baslik=h.tax_no or h.region,
            etiketler=h.roller,
            yol=f"/hesaplar/{h.id}",
        )
        for h in (await db.scalars(stmt)).all()
    ]


async def _urun_ara(db: AsyncSession, user: User, terim: str, limit: int) -> list[AramaSonucu]:
    if not user.has("urun.gor"):
        return []
    anahtar = tr_normkey(terim)
    stmt = (
        select(Product)
        .where(
            Product.is_deleted.is_(False),
            Product.name_key.contains(anahtar) | Product.code.ilike(f"%{terim}%"),
        )
        .limit(limit)
    )
    return [
        AramaSonucu(
            tur="URUN",
            id=u.id,
            baslik=u.name,
            alt_baslik=u.code,
            etiketler=[u.type, u.identity_kind],
            yol=f"/urunler/{u.id}",
        )
        for u in (await db.scalars(stmt)).all()
    ]


async def _cihaz_ara(db: AsyncSession, user: User, terim: str, limit: int) -> list[AramaSonucu]:
    if not user.has("cihaz.gor"):
        return []
    stmt = (
        select(Device, Product)
        .join(Product, Product.id == Device.product_id)
        .where(
            Device.is_deleted.is_(False),
            Device.imei.startswith(terim) | Device.serial_no.ilike(f"%{terim}%"),
        )
        .limit(limit)
    )
    return [
        AramaSonucu(
            tur="CIHAZ",
            id=c.id,
            baslik=c.kimlik,
            alt_baslik=u.name,
            etiketler=[c.status] + (["kimlik geçici"] if c.is_identity_provisional else []),
            yol=f"/cihazlar/{c.kimlik}",
        )
        for c, u in (await db.execute(stmt)).all()
    ]


async def _arac_ara(db: AsyncSession, user: User, terim: str, limit: int) -> list[AramaSonucu]:
    if not user.has("arac.gor"):
        return []
    anahtar = tr_normkey(terim).replace(" ", "")
    stmt = (
        select(Vehicle)
        .where(
            Vehicle.is_deleted.is_(False),
            Vehicle.plate_key.contains(anahtar)
            | Vehicle.chassis_no.ilike(f"%{terim}%")
            | Vehicle.registration_no.ilike(f"%{terim}%"),
        )
        .limit(limit)
    )
    return [
        AramaSonucu(
            tur="ARAC",
            id=a.id,
            baslik=a.plate,
            alt_baslik=" ".join(filter(None, [a.brand, a.chassis_no])) or None,
            etiketler=[] if a.is_plate_verified else ["plaka doğrulanmadı"],
            # Araç ve hat için DETAY EKRANI yok; `/araclar/{id}` yolu
            # tanımlıydı ama sayfa parametreyi hiç okumuyordu: genel aramada
            # araç sonucuna tıklayan kullanıcı filtresiz listeye düşüyordu.
            # Listeyi o kayda filtreleyen yol, kullanıcıyı doğru yere götürür.
            yol=f"/araclar?q={quote(a.plate or str(a.id))}",
        )
        for a in (await db.scalars(stmt)).all()
    ]


async def _hat_ara(db: AsyncSession, user: User, terim: str, limit: int) -> list[AramaSonucu]:
    if not user.has("hat.gor"):
        return []
    rakam = "".join(ch for ch in terim if ch.isdigit())
    if not rakam:
        return []
    stmt = (
        select(SimCard)
        .where(
            SimCard.is_deleted.is_(False),
            SimCard.iccid.contains(rakam) | SimCard.msisdn.contains(rakam),
        )
        .limit(limit)
    )
    return [
        AramaSonucu(
            tur="HAT",
            id=h.id,
            baslik=h.msisdn or h.iccid,
            alt_baslik=h.plan_name or h.operator,
            etiketler=[h.status],
            yol=f"/hatlar?q={quote(h.iccid or h.msisdn or str(h.id))}",
        )
        for h in (await db.scalars(stmt)).all()
    ]


# Yeni modül geldikçe buraya eklenir: iş emri, teklif, hak ediş dökümü.
ARAYICILAR = (_cihaz_ara, _arac_ara, _hat_ara, _hesap_ara, _urun_ara)


@router.get("", response_model=list[AramaSonucu])
async def ara(
    db: DbDep,
    user: Kullanici,
    q: str = Query(min_length=2, description="IMEI, plaka, ICCID, şase, firma veya ürün"),
    limit: int = Query(default=8, ge=1, le=25),
) -> list[AramaSonucu]:
    sonuclar: list[AramaSonucu] = []
    for arayici in ARAYICILAR:
        sonuclar.extend(await arayici(db, user, q, limit))
    return sonuclar[: limit * 2]
