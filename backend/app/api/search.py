"""Genel arama — tek kutudan IMEI, plaka, ICCID, şase, firma, ürün.

Brief bunu ayrı bir gereksinim olarak yazmamış ama kabul kriteri 1'in kendisi
bu ve mevcut uygulamada en çok kullanılan özellik. Modüller geldikçe
`ARAYICILAR` kayıt defterine yeni kaynak eklenir; arayüz değişmez.

**Kayıt defteri (teknik servis plan §1.11):** yeni modül arayıcısını KENDİ
API dosyasından `arayici_kaydet("servis.gor")` dekoratörüyle ekler (ör.
`_servis_ara`: servis işi no + `seri_norm`; `_ekipman_ara`). Bu dosya her
modülde yeniden düzenlenmez. Her arayıcı kendi iznini VE kapsamını uygular;
sonuç sayısı da bir sızıntıdır.
"""

from collections.abc import Callable
from typing import Annotated, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbDep
from app.models import Account, Device, Product, SimCard, User, Vehicle
from app.services import accounts as hesap_svc
from app.services import sirket_kapsami, sirketler
from app.services.normalize import tr_normkey

router = APIRouter(prefix="/api/arama", tags=["arama"])


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


# Sıra = sonuç listesindeki sıra. Yeni arayıcılar SONA eklenir.
ARAYICILAR: list[Arayici] = []


def arayici_kaydet(izin: str) -> Callable[[Callable], Arayici]:
    """Arayıcıyı kayıt defterine ekleyen dekoratör.

    `izin` arayıcının kendi okuma iznidir; genel arama kapısı "kayıtlı
    arayıcılardan en az birinin iznine sahip olma"dır. Böylece `hesap.gor`'u
    olmayan servis teknisyeni (KD-09) yalnız kendi göreceği servis işlerini
    arayabilir, hesap sonucu görmez.
    """

    def _kaydet(fn: Callable) -> Arayici:
        fn.izin = izin  # type: ignore[attr-defined]
        if fn not in ARAYICILAR:
            ARAYICILAR.append(fn)  # type: ignore[arg-type]
        return fn  # type: ignore[return-value]

    return _kaydet


class _AramaIzinleri:
    """Kapının izin listesi kayıt defterinden CANLI okunur: yeni arayıcı
    sonradan kaydolduğunda (modül import sırası) liste kendiliğinden genişler.
    Yetki matrisi de bunu `izinler_herhangi` olarak okur."""

    def __iter__(self):
        return iter(dict.fromkeys(a.izin for a in ARAYICILAR))


async def _arama_kullanicisi(user: CurrentUser) -> User:
    izinler = tuple(_AramaIzinleri())
    if not any(user.has(i) for i in izinler):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Bu işlem için yetkiniz yok ({' veya '.join(izinler)})"
        )
    return user


_arama_kullanicisi.izinler_herhangi = _AramaIzinleri()  # type: ignore[attr-defined]

# Arama, kullanıcının zaten görebileceği kayıtları döndürür; her arayıcı
# kendi iznini ve kapsamını uygular.
Kullanici = Annotated[User, Depends(_arama_kullanicisi)]


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
    # Şirket bazlı katalog (fcl000000001): ortak + etkin şirketin ürünleri.
    stmt = sirket_kapsami.uygula(stmt, sirket_kapsami.urun_kosulu(user))
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
    # Kapsam (TS-217): cihaz listesi ve kartıyla aynı kural; arama yan yoldu.
    stmt = hesap_svc.kapsam_musteri(stmt, user, Device.current_customer_id)
    # Şirket bazlı (fcl000000001): cihaz listesiyle aynı kural (ürünün şirketi).
    stmt = sirket_kapsami.uygula(stmt, sirket_kapsami.urun_kosulu(user))
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
    # Kapsam (TS-217): araç listesiyle aynı kural (`/api/araclar`).
    stmt = hesap_svc.kapsam_musteri(stmt, user, Vehicle.customer_id)
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
    # Şirket bazlı (fcl000000001): hat listesiyle aynı kural.
    stmt = sirket_kapsami.uygula(stmt, sirket_kapsami.hat_kosulu(user))
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


def _yalniz_mobilite(arayici: Callable) -> Callable:
    """Mobilite modülü arayıcısı yalnız DENGE MOBİLİTE etkinken sonuç verir
    (KARARLAR 2026-11-04 §1): ekranı 403 olan kaydın aramada çıkması kapıyı
    yan yoldan açardı. Arayıcının kendisi değişmez; hesap ortaktır. Cihaz ve
    hat artık şirket bazlıdır (fcl000000001): arayıcıları kendi içinde süzülür,
    bu sargı yalnız araç arayıcısında kalır."""

    async def _sarili(db: AsyncSession, user: User, terim: str, limit: int):
        if not sirketler.mobilite_acik_mi(user):
            return []
        return await arayici(db, user, terim, limit)

    _sarili.__name__ = arayici.__name__
    return _sarili


# Canlı arayıcılar — sıra eskisiyle aynı (cihaz, araç, hat, hesap, ürün).
# Teknik servis arayıcıları kendi API dosyalarından SONRA kaydolur.
for _izin, _arayici in (
    ("cihaz.gor", _cihaz_ara),
    ("arac.gor", _yalniz_mobilite(_arac_ara)),
    ("hat.gor", _hat_ara),
    ("hesap.gor", _hesap_ara),
    ("urun.gor", _urun_ara),
):
    arayici_kaydet(_izin)(_arayici)


@router.get("", response_model=list[AramaSonucu])
async def ara(
    db: DbDep,
    user: Kullanici,
    q: str = Query(min_length=2, description="IMEI, plaka, ICCID, şase, firma veya ürün"),
    limit: int = Query(default=8, ge=1, le=25),
) -> list[AramaSonucu]:
    sonuclar: list[AramaSonucu] = []
    for arayici in ARAYICILAR:
        # İzin burada da sorulur (derinlemesine savunma): arayıcı kendi
        # kontrolünü unutsa bile izinsiz kullanıcıya sonuç dönmez.
        if not user.has(arayici.izin):
            continue
        sonuclar.extend(await arayici(db, user, q, limit))
    return sonuclar[: limit * 2]
