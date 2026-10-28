"""Kiralama ve kiralık envanter uçları (TS-110…122, TS-102 kiralama tarafı).

İzinler (plan §1.3): `kiralama.gor` okuma, `kiralama.yaz` talep/kalem/irtibat/
planla/iptal/kapat, `kiralama.envanter` envanter/tahsis/kontrol/katalog,
`kiralama.asama` sevk/iade/aşama/geri alma; servis işi açma ek olarak
`servis.yaz`; Excel `kiralama.gor` + `servis_rapor.disaaktar` (KD-06).

- Her `{kiralama_id}` / `{kiralik_id}` / `{katalog_id}` ucunda kayıt ÖNCE
  kapsamla alınır: kapsam dışı → 404 ve hiçbir yazma yapılmaz.
- Statik yollar (`/ozet`, `/envanter/...`, `/katalog`) `{kiralama_id}`'den
  ÖNCE tanımlanır.
- Fiyat/maliyet alanı YOK (K13): kiralama bedeli ERP'de tutulmaz.
- Durum yalnız aşama uçlarıyla; PUT durum/birim kabul etmez (400, 422 değil:
  alanlar şemada isteğe bağlıdır ve doluysa servis 400 döner — E06-18).
- Hareket defteri için PUT/PATCH/DELETE ucu YOKTUR (ekleme-yalnız).
- Gövde modelleri `json_schema_extra` örneği taşır (kapsam taraması).
"""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import (
    Account,
    Address,
    Contact,
    Product,
    Rental,
    RentalAsset,
    RentalCatalogItem,
    RentalContact,
    RentalEvent,
    RentalInventoryMovement,
    User,
    Warehouse,
)
from app.permissions import BIRIMLER
from app.services import audit
from app.services import export as export_svc
from app.services.accounts import kapsam_disinda_mi
from app.services.pdf import PdfUretilemedi
from app.services.statemachine import KIRALAMA, IzinsizGecis
from app.services.teknik_servis import kiralama as svc
from app.services.teknik_servis import kiralama_raporlar as rapor_svc
from app.services.teknik_servis import kiralama_tahsis as tahsis_svc
from app.services.teknik_servis import kiralik_envanter as envanter_svc
from app.services.teknik_servis import kiralik_sayim as sayim_svc
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.kiralik_envanter import KiralamaHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun

router = APIRouter(prefix="/api/kiralama", tags=["kiralama"])

Okuyucu = Annotated[User, Depends(require_permission("kiralama.gor"))]
Yazici = Annotated[User, Depends(require_permission("kiralama.yaz"))]
Envanterci = Annotated[User, Depends(require_permission("kiralama.envanter"))]
Asamaci = Annotated[User, Depends(require_permission("kiralama.asama"))]
IsAcici = Annotated[User, Depends(require_permission("kiralama.yaz", "servis.yaz"))]
Aktarici = Annotated[User, Depends(require_permission("kiralama.gor", "servis_rapor.disaaktar"))]

MAKS_DOSYA = 10 * 1024 * 1024
EXCEL_UST_SINIR = 20_000
_HATA_KODU = {"GIRDI": 400, "YOK": 404, "YASAK": 403}
_KILIT_MESAJI = (
    "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin."
)


def _hata(exc: Exception) -> HTTPException:
    """Servis hatasını HTTP'ye çevirir: 400 girdi, 403 katalog, 404 kapsam/yok, 409 kural."""
    if isinstance(exc, tahsis_svc.CakismaUyarisi):
        # M10.1: yapılandırılmış uyarı — arayüz çakışan kiralamaları listeler,
        # gerekçe ister ve `cakisma_onay` + `cakisma_gerekcesi` ile yeniden yollar.
        return HTTPException(status.HTTP_409_CONFLICT, {"mesaj": exc.mesaj, **exc.veri})
    if isinstance(exc, KiralamaHatasi):
        return HTTPException(_HATA_KODU.get(exc.kod, 409), exc.mesaj)
    if isinstance(exc, ServisGirdiHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


_HATALAR = (KiralamaHatasi, IzinsizGecis, ServisHatasi, ServisGirdiHatasi)


class CakismaOnayiIn(BaseModel):
    """M10.1 (KARARLAR 2026-10-28 §7 Faz A/4): seri cihazın tarih çakışması
    (çifte rezervasyon) engel değil UYARIDIR. İlk istek 409 +
    `kod=KIRALAMA_CAKISMA` + `cakismalar` alır; kullanıcı `cakisma_onay=true`
    ve boş olmayan `cakisma_gerekcesi` ile yeniden yollarsa kayıt yapılır ve
    gerekçe denetim izine (`kiralama.cakisma_onay`) yazılır."""

    cakisma_onay: bool = False
    cakisma_gerekcesi: str | None = Field(default=None, max_length=500)


def _cakisma_onayi(payload: CakismaOnayiIn) -> tahsis_svc.CakismaOnayi | None:
    if not payload.cakisma_onay:
        return None
    gerekce = (payload.cakisma_gerekcesi or "").strip()
    if not gerekce:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Çakışmayı onaylamak için gerekçe yazılmalı"
        )
    return tahsis_svc.CakismaOnayi(gerekce=gerekce)


async def _cakisma_denetimi(
    db: AsyncSession,
    k: Rental,
    onay: tahsis_svc.CakismaOnayi | None,
    *,
    islem: str,
    user: User,
    request: Request,
) -> None:
    """Gerçekten geçilen çakışma varsa gerekçesiyle denetim izine (commit'ten önce)."""
    if onay is None or not onay.gecilenler:
        return
    await audit.log(
        db,
        svc.ENTITY,
        "kiralama.cakisma_onay",
        entity_id=k.id,
        new_value={
            "islem": islem,
            "kiralama_no": k.rental_no,
            "gerekce": onay.gerekce,
            "cakismalar": onay.gecilenler,
        },
        user_id=user.id,
        ip=client_ip(request),
    )


# --- Şemalar ------------------------------------------------------------------------


class KalemIn(BaseModel):
    """Kalem: ürün + adet. Seri alanı YOKTUR (seri tahsisten türetilir);
    gövdede gelen fazla alan (ör. `seri_listesi`) yok sayılır."""

    id: int | None = None
    product_id: int
    qty: int
    note: str | None = Field(default=None, max_length=300)


class IrtibatIn(BaseModel):
    id: int | None = None
    contact_id: int
    rol: str = Field(max_length=20)


class KiralamaIn(BaseModel):
    birim: str = Field(max_length=20)
    # None kabul edilir ki eksik müşteri 422 değil servis doğrulamasıyla 400 olsun (K12).
    customer_id: int | None = None
    address_id: int | None = None
    lokasyon_metni: str | None = Field(default=None, max_length=300)
    proje_adi: str | None = Field(default=None, max_length=200)
    baslangic: date
    bitis: date
    sorumlu_user_id: int | None = None
    quote_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)
    kalemler: list[KalemIn] = Field(default_factory=list, max_length=200)
    irtibatlar: list[IrtibatIn] = Field(default_factory=list, max_length=50)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "birim": "GUVENLIK",
                    "customer_id": 1,
                    "baslangic": "2026-11-01",
                    "bitis": "2026-11-05",
                    "kalemler": [{"product_id": 1, "qty": 2}],
                }
            ]
        }
    }


class KiralamaPut(CakismaOnayiIn):
    """Başlık + kalem + irtibat tek işlem. `status/durum/birim` doluysa 400.
    Tarih değişikliği seri cihazı başka kiralamayla çakıştırırsa M10.1 uyarısı."""

    version: int
    customer_id: int | None = None
    address_id: int | None = None
    lokasyon_metni: str | None = Field(default=None, max_length=300)
    proje_adi: str | None = Field(default=None, max_length=200)
    baslangic: date | None = None
    bitis: date | None = None
    sorumlu_user_id: int | None = None
    quote_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)
    kalemler: list[KalemIn] | None = Field(default=None, max_length=200)
    irtibatlar: list[IrtibatIn] | None = Field(default=None, max_length=50)
    status: str | None = None
    durum: str | None = None
    birim: str | None = None

    model_config = {"json_schema_extra": {"examples": [{"version": 1, "proje_adi": "Fuar"}]}}


class TahsisSatirIn(BaseModel):
    kalem_id: int
    kiralik_idler: list[int] | None = Field(default=None, max_length=500)
    depo_id: int | None = None
    adet: int | None = None


class TahsisIn(CakismaOnayiIn):
    satirlar: list[TahsisSatirIn] = Field(min_length=1, max_length=200)

    model_config = {
        "json_schema_extra": {
            "examples": [{"satirlar": [{"kalem_id": 1, "depo_id": 1, "adet": 1}]}]
        }
    }


class SevkSatirIn(BaseModel):
    tahsis_id: int
    adet: int | None = None


class SevkIn(BaseModel):
    at: datetime | None = None
    # Boş: bütün tahsislerin kalanı (yalnız ilk sevkte).
    satirlar: list[SevkSatirIn] | None = Field(default=None, max_length=500)
    not_: str | None = Field(default=None, max_length=300, alias="not")

    model_config = {"populate_by_name": True, "json_schema_extra": {"examples": [{}]}}


class AsamaIn(BaseModel):
    asama: str = Field(max_length=20)
    at: datetime | None = None
    service_order_id: int | None = None
    not_: str | None = Field(default=None, max_length=500, alias="not")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {"examples": [{"asama": "KURULUM_YAPILDI"}]},
    }


class IadeSatirIn(BaseModel):
    tahsis_id: int
    sonuc: str = Field(max_length=20)
    adet: int | None = None
    depo_id: int | None = None
    not_: str | None = Field(default=None, max_length=300, alias="not")

    model_config = {"populate_by_name": True}


class IadeIn(BaseModel):
    at: datetime | None = None
    satirlar: list[IadeSatirIn] = Field(min_length=1, max_length=500)

    model_config = {
        "json_schema_extra": {
            "examples": [{"satirlar": [{"tahsis_id": 1, "sonuc": "IADE_ALINDI", "depo_id": 1}]}]
        }
    }


class GerekceIn(BaseModel):
    # None kabul edilir: boş gerekçe 422 değil 400 (servis doğrulaması).
    gerekce: str | None = Field(default=None, max_length=500)

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "Müşteri vazgeçti"}]}}


class GeriAlIn(BaseModel):
    gerekce: str | None = Field(default=None, max_length=500)
    # Verilirse yalnız SON aşama olayı olmalı (409).
    olay_id: int | None = None

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "Yanlış iade girildi"}]}}


class ServisIsiIn(BaseModel):
    tur: str = Field(max_length=20)

    model_config = {"json_schema_extra": {"examples": [{"tur": "KURULUM"}]}}


class KatalogIn(BaseModel):
    product_id: int
    birim: str = Field(max_length=20)
    kategori: str | None = Field(default=None, max_length=40)
    sira: int = 0

    model_config = {"json_schema_extra": {"examples": [{"product_id": 1, "birim": "GUVENLIK"}]}}


class KatalogPatch(BaseModel):
    version: int | None = None
    birim: str | None = Field(default=None, max_length=20)
    kategori: str | None = Field(default=None, max_length=40)
    sira: int | None = None
    is_active: bool | None = None

    model_config = {"json_schema_extra": {"examples": [{"is_active": False}]}}


class GirisIn(BaseModel):
    product_id: int
    depo_id: int
    durum: str = "HAZIR"
    seriler: list[str] | None = Field(default=None, max_length=2000)
    adet: int | None = None
    not_: str | None = Field(default=None, max_length=300, alias="not")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {"examples": [{"product_id": 1, "depo_id": 1, "adet": 1}]},
    }


class CihazPatch(BaseModel):
    """Yalnız seri/eksik notu/not; durum, depo, ürün, birim doluysa 400 (E06-18)."""

    version: int
    serial_no: str | None = Field(default=None, max_length=200)
    eksik_notu: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=4000)
    durum: str | None = None
    warehouse_id: int | None = None
    product_id: int | None = None
    birim: str | None = None

    model_config = {"json_schema_extra": {"examples": [{"version": 1, "notes": "Kutu eksik"}]}}


class TransferIn(BaseModel):
    hedef_depo_id: int
    kiralik_idler: list[int] | None = Field(default=None, max_length=500)
    product_id: int | None = None
    kaynak_depo_id: int | None = None
    adet: int | None = None
    durum: str = "HAZIR"
    not_: str | None = Field(default=None, max_length=300, alias="not")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {"examples": [{"hedef_depo_id": 1, "kiralik_idler": [1]}]},
    }


class KontrolSatirIn(BaseModel):
    sonuc: str = Field(max_length=10)
    kiralik_id: int | None = None
    product_id: int | None = None
    depo_id: int | None = None
    adet: int | None = None
    kaynak_durum: str = "KONTROLDE"
    aciklama: str | None = Field(default=None, max_length=500)
    rental_id: int | None = None
    atolye_kaydi_ac: bool = False


class KontrolIn(BaseModel):
    satirlar: list[KontrolSatirIn] = Field(min_length=1, max_length=500)

    model_config = {
        "json_schema_extra": {"examples": [{"satirlar": [{"kiralik_id": 1, "sonuc": "UYGUN"}]}]}
    }


class BulunduIn(BaseModel):
    gerekce: str | None = Field(default=None, max_length=300)
    depo_id: int
    kiralik_id: int | None = None
    product_id: int | None = None
    adet: int | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"gerekce": "Müşteride bulundu", "depo_id": 1, "kiralik_id": 1}]
        }
    }


class HurdaIn(BaseModel):
    gerekce: str | None = Field(default=None, max_length=300)
    kiralik_id: int | None = None
    product_id: int | None = None
    depo_id: int | None = None
    kaynak_durum: str = "HAZIR_DEGIL"
    adet: int | None = None

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "Onarılamaz", "kiralik_id": 1}]}}


# --- Çıktı ---------------------------------------------------------------------------


class KiralamaSatiri(BaseModel):
    id: int
    rental_no: str
    birim: str
    customer_id: int
    musteri: str | None
    proje_adi: str | None
    lokasyon_metni: str | None
    baslangic: date
    bitis: date
    status: str
    kalem_ozeti: list[str]
    kalem_adet: int
    tahsis_adet: int
    iade_gosterimi: str
    geciken: bool
    version: int


class KalemOut(BaseModel):
    id: int
    product_id: int
    urun_kodu: str | None
    urun_adi: str | None
    seri_takipli: bool
    qty: int
    note: str | None
    tahsisli: int
    sevk: int
    iade: int
    kayip: int


class TahsisOut(BaseModel):
    id: int
    rental_item_id: int
    product_id: int
    urun_kodu: str | None
    kiralik_id: int | None
    seri: str | None
    depo_id: int
    depo_adi: str | None
    qty: int
    sevk_adet: int
    iade_adet: int
    kayip_adet: int
    musteride: int
    durum: str
    shipped_at: datetime | None
    replaced_allocation_id: int | None


class IrtibatOut(BaseModel):
    id: int
    contact_id: int
    ad: str | None
    unvan: str | None
    rol: str


class BagliIs(BaseModel):
    id: int
    so_no: str
    tur: str
    status: str


class KiralamaKarti(KiralamaSatiri):
    address_id: int | None
    lokasyon: str | None
    sorumlu_user_id: int | None
    sorumlu_adi: str | None
    quote_id: int | None
    notes: str | None
    iptal_gerekcesi: str | None
    kapanis_at: datetime | None
    created_at: datetime
    kalemler: list[KalemOut]
    tahsisler: list[TahsisOut]
    # İrtibat yalnız yazan/aşama sahibine ya da `servis.irtibat_gor`'e (KVKK).
    irtibatlar: list[IrtibatOut] | None = None
    sonraki_durumlar: list[str]
    servis_isleri: list[BagliIs]
    onerilen_asama: str | None
    geri_alinabilir_olay_id: int | None


class OlayOut(BaseModel):
    id: int
    at: datetime
    tur: str
    onceki_durum: str | None
    yeni_durum: str | None
    alan: str | None
    eski: dict | None
    yeni: dict | None
    service_order_id: int | None
    ekip_user_ids: list[int] | None
    gerekce: str | None
    geri_alinan_event_id: int | None
    geri_alindi: bool
    kullanici: str | None


class KpiOut(BaseModel):
    kod: str
    baslik: str
    tanim: str
    deger: int


class CihazSatiri(BaseModel):
    id: int
    product_id: int
    urun_kodu: str | None
    urun_adi: str | None
    serial_no: str
    birim: str
    depo_id: int | None
    depo_adi: str | None
    durum: str
    eksik_notu: str | None
    notes: str | None
    kiralama_id: int | None
    kontrolde_gun: int | None
    version: int


class HareketOut(BaseModel):
    id: int
    at: datetime
    kind: str
    product_id: int
    kiralik_id: int | None
    qty: int
    from_depo_id: int | None
    to_depo_id: int | None
    from_depo: str | None
    to_depo: str | None
    from_durum: str | None
    to_durum: str | None
    rental_id: int | None
    rental_no: str | None
    allocation_id: int | None
    check_id: int | None
    reverses_id: int | None
    note: str | None


class CihazKarti(CihazSatiri):
    hareketler: list[HareketOut]


class KatalogOut(BaseModel):
    id: int
    product_id: int
    urun_kodu: str | None
    urun_adi: str | None
    seri_takipli: bool
    birim: str
    kategori: str | None
    sira: int
    is_active: bool
    version: int


class DegisimIn(CakismaOnayiIn):
    """Sahada cihaz değişimi (E06-20): eski tahsis → yeni seri cihaz; eski cihaz
    iade deposuna KONTROLDE döner. Yeni cihaz tarih çakışırsa M10.1 uyarısı."""

    eski_tahsis_id: int
    yeni_kiralik_id: int
    iade_depo_id: int
    not_: str | None = Field(default=None, alias="not", max_length=300)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "examples": [
                {"eski_tahsis_id": 1, "yeni_kiralik_id": 2, "iade_depo_id": 1, "not": "Arızalı"}
            ]
        },
    }


class SayimAcIn(BaseModel):
    depo_id: int
    notes: str | None = Field(default=None, max_length=2000)

    model_config = {"json_schema_extra": {"examples": [{"depo_id": 1}]}}


class SayimSatiriIn(BaseModel):
    product_id: int
    seri: str | None = Field(default=None, max_length=200)
    adet: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=300)


class SayimSatirlariIn(BaseModel):
    sayim_id: int
    satirlar: list[SayimSatiriIn] = Field(default_factory=list, max_length=2000)

    model_config = {
        "json_schema_extra": {
            "examples": [{"sayim_id": 1, "satirlar": [{"product_id": 1, "adet": 3}]}]
        }
    }


class SayimOnayIn(BaseModel):
    sayim_id: int
    kararlar: list[str] = Field(default_factory=list, max_length=5000)
    gerekce: str | None = Field(default=None, max_length=300)
    degisimi_kabul: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [{"sayim_id": 1, "kararlar": ["T:1"], "gerekce": "Yıl sonu"}]
        }
    }


class SayimIptalIn(BaseModel):
    sayim_id: int
    gerekce: str = Field(max_length=500)

    model_config = {"json_schema_extra": {"examples": [{"sayim_id": 1, "gerekce": "Vazgeçildi"}]}}


class DepoOut(BaseModel):
    id: int
    code: str
    name: str
    birim: str | None


# --- Yardımcılar -----------------------------------------------------------------------


async def _kiralama(
    db: AsyncSession, user: User, kiralama_id: int, *, kilit: bool = False
) -> Rental:
    try:
        return await svc.kapsamli_kiralama(db, user, kiralama_id, kilit=kilit)
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc


async def _cihaz(db: AsyncSession, user: User, kiralik_id: int) -> RentalAsset:
    try:
        return await envanter_svc.kapsamli_kiralik(db, user, kiralik_id)
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc


def _irtibat_gorur(user: User) -> bool:
    return user.has("kiralama.yaz") or user.has("kiralama.asama") or user.has("servis.irtibat_gor")


async def _satirlar(db: AsyncSession, kayitlar: list, clock) -> list[KiralamaSatiri]:
    idler = [r[0].id for r in kayitlar]
    ekler = await svc.satir_ekleri(db, idler)
    bugun = yerel_bugun(clock)
    geciken = set()
    if idler:
        geciken = set(
            (
                await db.scalars(
                    select(Rental.id).where(Rental.id.in_(idler), svc.kpi_kosulu("geciken", bugun))
                )
            ).all()
        )
    sonuc = []
    for k, unvan in kayitlar:
        e = ekler.get(k.id, {})
        sonuc.append(
            KiralamaSatiri(
                id=k.id,
                rental_no=k.rental_no,
                birim=k.birim,
                customer_id=k.customer_id,
                musteri=unvan,
                proje_adi=k.proje_adi,
                lokasyon_metni=k.lokasyon_metni,
                baslangic=k.baslangic,
                bitis=k.bitis,
                status=k.status,
                kalem_ozeti=e.get("kalem_ozeti", []),
                kalem_adet=e.get("kalem_adet", 0),
                tahsis_adet=e.get("tahsis_adet", 0),
                iade_gosterimi=e.get("iade_gosterimi", "YOK"),
                geciken=k.id in geciken,
                version=k.version,
            )
        )
    return sonuc


async def _kart(db: AsyncSession, k: Rental, user: User, clock) -> KiralamaKarti:
    hesap = await db.get(Account, k.customer_id)
    satir = (await _satirlar(db, [(k, hesap.title if hesap else None)], clock))[0]
    adres = await db.get(Address, k.address_id) if k.address_id else None
    kalemler = await tahsis_svc.kalemler(db, k.id)
    tahsisler = await tahsis_svc.tahsisler(db, k.id)
    urun_idler = {x.product_id for x in kalemler} | {t.product_id for t in tahsisler}
    urunler = {
        u.id: u
        for u in (
            await db.scalars(select(Product).where(Product.id.in_(list(urun_idler) or [0])))
        ).all()
    }
    depolar = {
        d.id: d
        for d in (
            await db.scalars(
                select(Warehouse).where(
                    Warehouse.id.in_([t.from_warehouse_id for t in tahsisler] or [0])
                )
            )
        ).all()
    }
    seriler = await tahsis_svc.ozet_seriler(db, tahsisler)
    kalem_out = []
    for x in kalemler:
        ilgili = [t for t in tahsisler if t.rental_item_id == x.id and t.durum != "COZULDU"]
        urun = urunler.get(x.product_id)
        kalem_out.append(
            KalemOut(
                id=x.id,
                product_id=x.product_id,
                urun_kodu=urun.code if urun else None,
                urun_adi=urun.name if urun else None,
                seri_takipli=bool(urun and urun.identity_kind == "SERI_NO"),
                qty=x.qty,
                note=x.note,
                tahsisli=sum(t.qty for t in ilgili if t.durum == "AKTIF"),
                sevk=sum(t.sevk_adet for t in ilgili),
                iade=sum(t.iade_adet for t in ilgili),
                kayip=sum(t.kayip_adet for t in ilgili),
            )
        )
    tahsis_out = [
        TahsisOut(
            id=t.id,
            rental_item_id=t.rental_item_id,
            product_id=t.product_id,
            urun_kodu=urunler[t.product_id].code if t.product_id in urunler else None,
            kiralik_id=t.asset_id,
            seri=seriler.get(t.id),
            depo_id=t.from_warehouse_id,
            depo_adi=depolar[t.from_warehouse_id].name if t.from_warehouse_id in depolar else None,
            qty=t.qty,
            sevk_adet=t.sevk_adet,
            iade_adet=t.iade_adet,
            kayip_adet=t.kayip_adet,
            musteride=tahsis_svc.disarida(t),
            durum=t.durum,
            shipped_at=t.shipped_at,
            replaced_allocation_id=t.replaced_allocation_id,
        )
        for t in tahsisler
    ]
    irtibatlar = None
    if _irtibat_gorur(user):
        satirlar = (
            await db.execute(
                select(RentalContact, Contact.full_name, Contact.title)
                .join(Contact, Contact.id == RentalContact.contact_id)
                .where(RentalContact.rental_id == k.id)
                .order_by(RentalContact.id)
            )
        ).all()
        irtibatlar = [
            IrtibatOut(id=r.id, contact_id=r.contact_id, ad=ad, unvan=unvan, rol=r.rol)
            for r, ad, unvan in satirlar
        ]
    sorumlu = await db.get(User, k.sorumlu_user_id) if k.sorumlu_user_id else None
    isler = await svc.bagli_isler(db, k.id)
    geri_al = await svc.son_geri_alinabilir_olay(db, k.id)
    return KiralamaKarti(
        **satir.model_dump(),
        address_id=k.address_id,
        lokasyon=" · ".join(
            filter(
                None,
                [
                    (adres.site_name or adres.label) if adres else None,
                    adres.city if adres else None,
                ],
            )
        )
        or None,
        sorumlu_user_id=k.sorumlu_user_id,
        sorumlu_adi=sorumlu.full_name if sorumlu else None,
        quote_id=k.quote_id,
        notes=k.notes,
        iptal_gerekcesi=k.iptal_gerekcesi,
        kapanis_at=k.kapanis_at,
        created_at=k.created_at,
        kalemler=kalem_out,
        tahsisler=tahsis_out,
        irtibatlar=irtibatlar,
        sonraki_durumlar=sorted(KIRALAMA.sonraki(k.status)),
        servis_isleri=[BagliIs(id=s.id, so_no=s.so_no, tur=s.tur, status=s.status) for s in isler],
        onerilen_asama=svc.onerilen_asama(k, isler),
        geri_alinabilir_olay_id=geri_al.id
        if geri_al is not None and k.status not in svc.KAPALI_DURUMLAR
        else None,
    )


async def _kart_yanit(db: AsyncSession, k: Rental, user: User, clock) -> KiralamaKarti:
    await db.refresh(k)
    return await _kart(db, k, user, clock)


def _suzgec(
    q: str | None = None,
    durum: str | None = None,
    birim: str | None = None,
    musteri: int | None = Query(default=None, description="Müşteri (hesap) kimliği"),
    kpi: str | None = None,
    ids: str | None = Query(default=None, description="Virgülle ayrılmış kimlikler"),
) -> svc.KiralamaSuzgeci:
    idler = None
    if ids:
        try:
            idler = [int(p) for p in ids.split(",") if p.strip()]
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçersiz kimlik listesi") from exc
    return svc.KiralamaSuzgeci(
        q=q, durum=durum, birim=birim, musteri_id=musteri, kpi=kpi, idler=idler
    )


Suzgec = Annotated[svc.KiralamaSuzgeci, Depends(_suzgec)]


def _sorgu(user: User, s: svc.KiralamaSuzgeci, clock):
    try:
        return svc.liste_sorgusu(user, s, bugun=yerel_bugun(clock))
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc


async def _hareket_satirlari(
    db: AsyncSession, hareketler: list[RentalInventoryMovement]
) -> list[HareketOut]:
    depo_idler = {h.from_warehouse_id for h in hareketler} | {h.to_warehouse_id for h in hareketler}
    depo_idler.discard(None)
    depolar = {
        d.id: d.name
        for d in (
            await db.scalars(select(Warehouse).where(Warehouse.id.in_(list(depo_idler) or [0])))
        ).all()
    }
    kiralama_idler = {h.rental_id for h in hareketler if h.rental_id}
    numaralar = {
        r.id: r.rental_no
        for r in (
            await db.scalars(select(Rental).where(Rental.id.in_(list(kiralama_idler) or [0])))
        ).all()
    }
    return [
        HareketOut(
            id=h.id,
            at=h.at,
            kind=h.kind,
            product_id=h.product_id,
            kiralik_id=h.asset_id,
            qty=h.qty,
            from_depo_id=h.from_warehouse_id,
            to_depo_id=h.to_warehouse_id,
            from_depo=depolar.get(h.from_warehouse_id),
            to_depo=depolar.get(h.to_warehouse_id),
            from_durum=h.from_durum,
            to_durum=h.to_durum,
            rental_id=h.rental_id,
            rental_no=numaralar.get(h.rental_id),
            allocation_id=h.allocation_id,
            check_id=h.check_id,
            reverses_id=h.reverses_id,
            note=h.note,
        )
        for h in hareketler
    ]


async def _cihaz_satirlari(db: AsyncSession, kayitlar: list, clock) -> list[CihazSatiri]:
    idler = [r[0].id for r in kayitlar]
    gun = await envanter_svc.kontrolde_gun(db, idler, clock.now())
    tahsis = await envanter_svc.aktif_tahsis_kiralamalari(db, idler)
    return [
        CihazSatiri(
            id=c.id,
            product_id=c.product_id,
            urun_kodu=kod,
            urun_adi=ad,
            serial_no=c.serial_no,
            birim=c.birim,
            depo_id=c.warehouse_id,
            depo_adi=depo,
            durum=c.durum,
            eksik_notu=c.eksik_notu,
            notes=c.notes,
            kiralama_id=tahsis.get(c.id),
            kontrolde_gun=gun.get(c.id) if c.durum == "KONTROLDE" else None,
            version=c.version,
        )
        for c, kod, ad, depo in kayitlar
    ]


async def _cihaz_karti(db: AsyncSession, c: RentalAsset, user: User, clock) -> CihazKarti:
    stmt = envanter_svc.envanter_sorgusu(user, envanter_svc.EnvanterSuzgeci()).where(
        RentalAsset.id == c.id
    )
    satir = (await _cihaz_satirlari(db, list((await db.execute(stmt)).all()), clock))[0]
    hareketler = await envanter_svc.cihaz_hareketleri(db, c.id)
    return CihazKarti(**satir.model_dump(), hareketler=await _hareket_satirlari(db, hareketler))


def _xlsx(baslik: str, dosya: str, basliklar: list[str], tablo: list[list[Any]]):
    async def _uret() -> Response:
        return Response(
            content=await export_svc.satirlari_xlsx_async(basliklar, tablo, baslik),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{dosya}"'},
        )

    return _uret()


# --- Liste, özet, Excel, müsaitlik, depolar (statik) ----------------------------------


@router.get("", response_model=list[KiralamaSatiri])
async def listele(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    response: Response,
    s: Suzgec,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KiralamaSatiri]:
    """Kiralama listesi; toplam `X-Toplam-Kayit`. `?kpi=<kod>` KPI kutusunun listesi."""
    kayitlar = await sayfala(db, response, _sorgu(user, s, clock), limit=limit, offset=offset)
    return await _satirlar(db, list(kayitlar), clock)


@router.get("/ozet", response_model=list[KpiOut])
async def ozet(db: DbDep, clock: ClockDep, user: Okuyucu) -> list[dict[str, Any]]:
    """KPI kutuları; her sayı = `?kpi=<kod>` listesinin `X-Toplam-Kayit`'ı."""
    return await svc.ozet(db, user, clock)


_LISTE_BASLIKLARI = [
    "Kiralama No",
    "Birim",
    "Müşteri",
    "Proje",
    "Yer",
    "Başlangıç",
    "Bitiş (iade)",
    "Durum",
    "Kalemler",
    "Kalem adedi",
    "Tahsisli",
    "İade",
    "Geciken",
]


@router.get("/liste.xlsx")
async def liste_xlsx(
    request: Request, db: DbDep, clock: ClockDep, user: Aktarici, s: Suzgec
) -> Response:
    """Ekrandaki süzgecin AYNI satırları; fiyat sütunu YOK."""
    stmt = _sorgu(user, s, clock)
    toplam = await svc.say(db, stmt)
    if toplam > EXCEL_UST_SINIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{toplam} satır var; Excel en çok {EXCEL_UST_SINIR} satır alır. Süzgeci daraltın.",
        )
    satirlar = await _satirlar(db, list((await db.execute(stmt)).all()), clock)
    tablo = [
        [
            r.rental_no,
            BIRIMLER.get(r.birim, r.birim),
            r.musteri or "",
            r.proje_adi or "",
            r.lokasyon_metni or "",
            r.baslangic,
            r.bitis,
            tahsis_svc.DURUM_ADLARI[r.status],
            ", ".join(r.kalem_ozeti),
            r.kalem_adet,
            r.tahsis_adet,
            {"YOK": "", "KISMI": "Kısmi iade", "TAM": "Tam"}[r.iade_gosterimi],
            "Evet" if r.geciken else "",
        ]
        for r in satirlar
    ]
    await audit.log(
        db,
        svc.ENTITY,
        "disaaktar",
        new_value={
            "filtre": {k: v for k, v in vars(s).items() if v not in (None, False)},
            "satir": len(tablo),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _xlsx("Kiralamalar", "kiralamalar.xlsx", _LISTE_BASLIKLARI, tablo)


@router.get("/musaitlik")
async def musaitlik(
    db: DbDep,
    user: Okuyucu,
    product_id: int,
    baslangic: date,
    bitis: date,
    haric_kiralama: int | None = None,
) -> dict[str, Any]:
    """Tarih bazlı müsaitlik (`[baslangic, bitis)`); KONTROLDE ayrı sütunda."""
    try:
        if bitis <= baslangic:
            raise envanter_svc.girdi("Bitiş tarihi başlangıçtan sonra olmalı")
        urun = envanter_svc.urun_dogrula(await db.get(Product, product_id))
        profil = await envanter_svc.aktif_katalog(db, urun.id)
        if envanter_svc.katalog_birim_yasak_mi(user, profil.birim):
            raise KiralamaHatasi("Bu ürün başka bir birimin kiralama kataloğunda", "YASAK")
        sonuc = await tahsis_svc.musaitlik(
            db, product_id, baslangic, bitis, user=user, haric_rental_id=haric_kiralama
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    return {**sonuc, "urun_kodu": urun.code, "seri_takipli": urun.identity_kind == "SERI_NO"}


@router.get("/depolar", response_model=list[DepoOut])
async def depolar(db: DbDep, user: Okuyucu) -> list[DepoOut]:
    """Aktif kiralama depoları (`kiralama_deposu=true`), birim kapsamlı."""
    return [
        DepoOut(id=d.id, code=d.code, name=d.name, birim=d.birim)
        for d in await envanter_svc.kiralama_depolari(db, user)
    ]


@router.get("/musteri-irtibatlari")
async def musteri_irtibatlari(
    db: DbDep, user: Yazici, musteri_id: int = Query()
) -> list[dict[str, Any]]:
    """Kiralama formu için müşterinin irtibat kişileri (ad + unvan; telefon YOK)."""
    if await kapsam_disinda_mi(db, user, musteri_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Müşteri bulunamadı")
    kisiler = (
        await db.scalars(
            select(Contact).where(Contact.account_id == musteri_id).order_by(Contact.full_name)
        )
    ).all()
    return [{"id": c.id, "ad": c.full_name, "unvan": c.title} for c in kisiler]


# --- Katalog (TS-118) -------------------------------------------------------------------


def _katalog_out(p: RentalCatalogItem, urun: Product | None) -> KatalogOut:
    return KatalogOut(
        id=p.id,
        product_id=p.product_id,
        urun_kodu=urun.code if urun else None,
        urun_adi=urun.name if urun else None,
        seri_takipli=bool(urun and urun.identity_kind == "SERI_NO"),
        birim=p.birim,
        kategori=p.kategori,
        sira=p.sira,
        is_active=p.is_active,
        version=p.version,
    )


@router.get("/katalog", response_model=list[KatalogOut])
async def katalog(
    db: DbDep, user: Okuyucu, birim: str | None = None, aktif: bool | None = None
) -> list[KatalogOut]:
    """Kiralama kataloğu (profil); ürün kartı canlı katalogdadır."""
    stmt = (
        select(RentalCatalogItem, Product)
        .join(Product, Product.id == RentalCatalogItem.product_id)
        .where(RentalCatalogItem.is_deleted.is_(False))
    )
    if birim:
        stmt = stmt.where(RentalCatalogItem.birim == birim)
    if aktif is not None:
        stmt = stmt.where(RentalCatalogItem.is_active.is_(aktif))
    stmt = envanter_svc.katalog_kosulu(stmt, user).order_by(
        RentalCatalogItem.birim, RentalCatalogItem.sira, Product.code
    )
    return [_katalog_out(p, u) for p, u in (await db.execute(stmt)).all()]


@router.post("/katalog", response_model=KatalogOut, status_code=status.HTTP_201_CREATED)
async def katalog_ekle(
    payload: KatalogIn, request: Request, db: DbDep, user: Envanterci
) -> KatalogOut:
    """Ürünü kiralama kataloğuna ekler. IMEI'li ürün 400; mobilite birimleri 400."""
    try:
        p = await envanter_svc.katalog_ekle(
            db,
            user,
            product_id=payload.product_id,
            birim=payload.birim,
            kategori=payload.kategori,
            sira=payload.sira,
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(p)
    return _katalog_out(p, await db.get(Product, p.product_id))


@router.patch("/katalog/{katalog_id}", response_model=KatalogOut)
async def katalog_guncelle(
    katalog_id: int, payload: KatalogPatch, request: Request, db: DbDep, user: Envanterci
) -> KatalogOut:
    """Profil düzenleme / pasifleştirme (kayıt silinmez). Envanterli üründe birim 409."""
    try:
        p = await envanter_svc.kapsamli_katalog(db, user, katalog_id)
        if payload.version is not None and payload.version != p.version:
            raise HTTPException(status.HTTP_409_CONFLICT, _KILIT_MESAJI)
        await envanter_svc.katalog_guncelle(
            db,
            user,
            p,
            payload.model_dump(exclude_unset=True, exclude={"version"}),
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(p)
    return _katalog_out(p, await db.get(Product, p.product_id))


# --- Kiralık envanter (TS-111, 115, 121, 102) -------------------------------------------


def _envanter_suzgeci(
    q: str | None = None,
    durum: str | None = None,
    depo_id: int | None = None,
    product_id: int | None = None,
    birim: str | None = None,
    uzun: bool = False,
) -> envanter_svc.EnvanterSuzgeci:
    return envanter_svc.EnvanterSuzgeci(
        q=q, durum=durum, depo_id=depo_id, product_id=product_id, birim=birim, uzun=uzun
    )


EnvSuzgec = Annotated[envanter_svc.EnvanterSuzgeci, Depends(_envanter_suzgeci)]


async def _uzun_gun(db: AsyncSession) -> int:
    from app.services.teknik_servis.kiralama_raporlar import kontrol_esigi

    return await kontrol_esigi(db)


@router.get("/envanter", response_model=list[CihazSatiri])
async def envanter(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    response: Response,
    s: EnvSuzgec,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CihazSatiri]:
    """Seri kiralık cihazlar; `uzun=1` uzun süredir KONTROLDE olanlar (uyarının listesi)."""
    stmt = envanter_svc.envanter_sorgusu(user, s, an=clock.now(), uzun_gun=await _uzun_gun(db))
    kayitlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _cihaz_satirlari(db, list(kayitlar), clock)


@router.get("/envanter/bakiyeler")
async def bakiyeler(db: DbDep, user: Okuyucu) -> list[dict[str, Any]]:
    """Depo × ürün × durum adetleri (seri + toplu); depo kartları ve sayaçlar."""
    return await envanter_svc.bakiye_tablosu(db, user)


@router.get("/envanter/hareketler", response_model=list[HareketOut])
async def toplu_hareketler(
    db: DbDep,
    user: Okuyucu,
    response: Response,
    product_id: int | None = None,
    depo_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[HareketOut]:
    """Toplu (seri takipsiz) ürün hareket defteri; değiştirme ucu YOK."""
    stmt = envanter_svc.toplu_hareket_sorgusu(user, product_id=product_id, depo_id=depo_id)
    kayitlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _hareket_satirlari(db, [r[0] for r in kayitlar])


_ENVANTER_BASLIKLARI = ["Ürün Kodu", "Ürün", "Seri No", "Birim", "Depo", "Durum", "Eksik", "Not"]


@router.get("/envanter/liste.xlsx")
async def envanter_xlsx(
    request: Request, db: DbDep, clock: ClockDep, user: Aktarici, s: EnvSuzgec
) -> Response:
    """Ekrandaki envanter süzgeci; seri METİN, fiyat yok."""
    stmt = envanter_svc.envanter_sorgusu(user, s, an=clock.now(), uzun_gun=await _uzun_gun(db))
    if await svc.say(db, stmt) > EXCEL_UST_SINIR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Satır çok fazla; süzgeci daraltın")
    satirlar = await _cihaz_satirlari(db, list((await db.execute(stmt)).all()), clock)
    tablo = [
        [
            r.urun_kodu or "",
            r.urun_adi or "",
            str(r.serial_no),
            BIRIMLER.get(r.birim, r.birim),
            r.depo_adi or "",
            envanter_svc.DURUM_ETIKETLERI[r.durum],
            r.eksik_notu or "",
            r.notes or "",
        ]
        for r in satirlar
    ]
    await audit.log(
        db,
        envanter_svc.ENTITY_KIRALIK,
        "disaaktar",
        new_value={"satir": len(tablo)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return await _xlsx("Kiralik Envanter", "kiralik-envanter.xlsx", _ENVANTER_BASLIKLARI, tablo)


@router.get("/envanter/sablon.xlsx")
async def toplu_sablon(user: Envanterci) -> Response:
    """Toplu giriş şablonu: ürün kodu, seri no, adet, depo kodu, durum, not."""
    return Response(
        content=envanter_svc.toplu_sablon(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="kiralik-envanter-sablon.xlsx"'},
    )


async def _dosya_oku(dosya: UploadFile) -> bytes:
    icerik = await dosya.read(MAKS_DOSYA + 1)
    if len(icerik) > MAKS_DOSYA:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dosya 10 MB sınırını aşıyor")
    return icerik


@router.post("/envanter/toplu/onizleme")
async def toplu_onizleme(
    db: DbDep, user: Envanterci, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """Toplu giriş önizlemesi: HİÇBİR ŞEY YAZMAZ; satır hataları + dosya özeti (sha256)."""
    icerik = await _dosya_oku(file)
    try:
        return await envanter_svc.toplu_onizleme(db, user, file.filename or "", icerik)
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc


@router.post("/envanter/toplu/onayla")
async def toplu_onayla(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Envanterci,
    file: Annotated[UploadFile, File()],
    sha256: Annotated[str, Form(max_length=64)],
) -> dict[str, Any]:
    """Onay: dosya yeniden doğrulanır; önizleme özeti tutmazsa 409. Yalnız hatasız
    satırlar `GIRIS` hareketiyle yazılır."""
    icerik = await _dosya_oku(file)
    try:
        sonuc = await envanter_svc.toplu_onayla(
            db, user, clock, file.filename or "", icerik, sha256, ip=client_ip(request)
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return sonuc


@router.post("/envanter", status_code=status.HTTP_201_CREATED)
async def giris(
    payload: GirisIn, request: Request, db: DbDep, clock: ClockDep, user: Envanterci
) -> dict[str, Any]:
    """Envanter girişi (`GIRIS`). Durum yalnız HAZIR/KONTROLDE/HAZIR_DEGIL; IMEI ürün 400."""
    try:
        sonuc = await envanter_svc.giris(
            db,
            user,
            clock,
            product_id=payload.product_id,
            depo_id=payload.depo_id,
            durum=payload.durum,
            seriler=payload.seriler,
            adet=payload.adet,
            note=payload.not_,
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {
        "adet": sonuc.adet,
        "kiralik_idler": [c.id for c in sonuc.cihazlar],
        "hareket_idler": [h.id for h in sonuc.hareketler],
    }


@router.post("/envanter/transfer")
async def transfer(
    payload: TransferIn, request: Request, db: DbDep, clock: ClockDep, user: Envanterci
) -> dict[str, Any]:
    """Depo değişimi yalnız transferle; durum korunur. Tahsisli cihaz 409."""
    try:
        hareketler = await envanter_svc.transfer(
            db,
            user,
            clock,
            hedef_depo_id=payload.hedef_depo_id,
            cihaz_idler=payload.kiralik_idler,
            product_id=payload.product_id,
            kaynak_depo_id=payload.kaynak_depo_id,
            adet=payload.adet,
            durum=payload.durum,
            note=payload.not_,
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"hareket_idler": [h.id for h in hareketler], "adet": sum(h.qty for h in hareketler)}


@router.post("/envanter/kontrol")
async def kontrol(
    payload: KontrolIn, request: Request, db: DbDep, clock: ClockDep, user: Envanterci
) -> dict[str, Any]:
    """Dönüş kontrolü (toplu, tek istek): UYGUN → HAZIR; EKSIK/ARIZALI → HAZIR_DEGIL."""
    try:
        kayitlar = await envanter_svc.kontrol(
            db,
            user,
            clock,
            [envanter_svc.KontrolSatiri(**s.model_dump()) for s in payload.satirlar],
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {
        "kontroller": [
            {
                "id": k.id,
                "kiralik_id": k.asset_id,
                "sonuc": k.sonuc,
                "at": k.at,
                "kontrol_eden": user.full_name,
                "workshop_record_id": k.workshop_record_id,
            }
            for k in kayitlar
        ]
    }


@router.post("/envanter/bulundu")
async def bulundu(
    payload: BulunduIn, request: Request, db: DbDep, clock: ClockDep, user: Envanterci
) -> dict[str, Any]:
    """KAYIP → (depo, KONTROLDE); gerekçe zorunlu."""
    try:
        h = await envanter_svc.bulundu(
            db,
            user,
            clock,
            gerekce=payload.gerekce or "",
            depo_id=payload.depo_id,
            kiralik_id=payload.kiralik_id,
            product_id=payload.product_id,
            adet=payload.adet,
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"hareket_id": h.id}


@router.post("/envanter/hurda")
async def hurda(
    payload: HurdaIn, request: Request, db: DbDep, clock: ClockDep, user: Envanterci
) -> dict[str, Any]:
    """Envanterden gerekçeli çıkış (HURDA); kayıt silinmez."""
    try:
        h = await envanter_svc.hurda(
            db,
            user,
            clock,
            gerekce=payload.gerekce or "",
            kiralik_id=payload.kiralik_id,
            product_id=payload.product_id,
            depo_id=payload.depo_id,
            kaynak_durum=payload.kaynak_durum,
            adet=payload.adet,
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"hareket_id": h.id}


@router.get("/envanter/{kiralik_id}", response_model=CihazKarti)
async def cihaz_getir(kiralik_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> CihazKarti:
    c = await _cihaz(db, user, kiralik_id)
    return await _cihaz_karti(db, c, user, clock)


@router.get("/envanter/{kiralik_id}/hareketler", response_model=list[HareketOut])
async def cihaz_hareketleri(kiralik_id: int, db: DbDep, user: Okuyucu) -> list[HareketOut]:
    """Cihazın bütün hareketleri (`at`, `id` sırasıyla)."""
    c = await _cihaz(db, user, kiralik_id)
    return await _hareket_satirlari(db, await envanter_svc.cihaz_hareketleri(db, c.id))


@router.patch("/envanter/{kiralik_id}", response_model=CihazKarti)
async def cihaz_guncelle(
    kiralik_id: int,
    payload: CihazPatch,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Envanterci,
) -> CihazKarti:
    """Seri/eksik notu/not. Durum/depo/ürün/birim 400; tahsisli cihazın serisi 409."""
    c = await _cihaz(db, user, kiralik_id)
    if payload.version != c.version:
        raise HTTPException(status.HTTP_409_CONFLICT, _KILIT_MESAJI)
    try:
        await envanter_svc.cihaz_guncelle(
            db,
            user,
            clock,
            c,
            payload.model_dump(exclude_unset=True, exclude={"version"}),
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(c)
    return await _cihaz_karti(db, c, user, clock)


# --- Kiralama: oluşturma ------------------------------------------------------------------


# --- Raporlar (TS-195, E06-21) — `servis_rapor.gor + kiralama.gor` ----------------------

Raporcu = Annotated[User, Depends(require_permission("kiralama.gor", "servis_rapor.gor"))]
RaporAktarici = Annotated[
    User,
    Depends(require_permission("kiralama.gor", "servis_rapor.gor", "servis_rapor.disaaktar")),
]


async def _rapor_denetimi(request: Request, db: AsyncSession, user: User, rapor: str, satir: int):
    await audit.log(
        db,
        svc.ENTITY,
        "rapor.disaaktar",
        new_value={"rapor": rapor, "satir": satir},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()


@router.get("/raporlar/depo-durumu")
async def rapor_depo_durumu(db: DbDep, user: Raporcu) -> dict[str, Any]:
    """Depo × ürün × durum adetleri (REZERVE = sevk edilmemiş AKTİF tahsis); fiyat yok."""
    return await rapor_svc.depo_durumu(db, user)


_DEPO_BASLIKLARI = [
    "Depo",
    "Ürün Kodu",
    "Ürün",
    "Hazır",
    "Rezerve",
    "Serbest",
    "Kirada",
    "Kontrolde",
    "Hazır Değil",
    "Kayıp",
    "Atölyede",
]


@router.get("/raporlar/depo-durumu.xlsx")
async def rapor_depo_durumu_xlsx(request: Request, db: DbDep, user: RaporAktarici) -> Response:
    r = await rapor_svc.depo_durumu(db, user)
    tablo = [
        [s["depo_adi"], s["urun_kodu"], s["urun_adi"], *(s[k] for k in rapor_svc.DEPO_SUTUNLARI)]
        for s in r["satirlar"]
    ]
    await _rapor_denetimi(request, db, user, "depo-durumu", len(tablo))
    return await _xlsx("Depo Durumu", "kiralama-depo-durumu.xlsx", _DEPO_BASLIKLARI, tablo)


@router.get("/raporlar/geciken-iade")
async def rapor_geciken_iade(
    db: DbDep, clock: ClockDep, user: Raporcu, response: Response
) -> list[dict[str, Any]]:
    """Geciken iadeler — sayı, `GET /api/kiralama?kpi=geciken` listesinin toplamıdır."""
    satirlar = await rapor_svc.geciken_iade(db, user, clock)
    response.headers["X-Toplam-Kayit"] = str(len(satirlar))
    return satirlar


_ASAMA_ADI = {"IS_YOK": "İş yok", "EKSIK": "Eksik"}


def _asama_metni(a: dict[str, Any] | None) -> str:
    if not a:
        return ""
    if a["dk"] is None:
        return _ASAMA_ADI.get(a["durum"], "Eksik")
    return f"{a['dk']} dk"


@router.get("/raporlar/geciken-iade.xlsx")
async def rapor_geciken_iade_xlsx(
    request: Request, db: DbDep, clock: ClockDep, user: RaporAktarici
) -> Response:
    satirlar = await rapor_svc.geciken_iade(db, user, clock)
    tablo = [
        [
            s["rental_no"],
            BIRIMLER.get(s["birim"], s["birim"]),
            s["musteri"] or "",
            s["proje_adi"] or "",
            s["bitis"],
            s["gecikme_gun"],
            s["musteride_adet"],
            ", ".join(s["seriler"]),
            _asama_metni(s["asama_sureleri"].get("KURULUM")),
            _asama_metni(s["asama_sureleri"].get("TOPLAMA")),
        ]
        for s in satirlar
    ]
    await _rapor_denetimi(request, db, user, "geciken-iade", len(tablo))
    return await _xlsx(
        "Geciken Iade",
        "kiralama-geciken-iade.xlsx",
        [
            "Kiralama No",
            "Birim",
            "Müşteri",
            "Proje",
            "Bitiş (iade)",
            "Gecikme (gün)",
            "Müşterideki Adet",
            "Seriler",
            "Kurulum Süresi",
            "Toplama Süresi",
        ],
        tablo,
    )


@router.get("/raporlar/kontrolde-bekleme")
async def rapor_kontrolde_bekleme(db: DbDep, clock: ClockDep, user: Raporcu) -> dict[str, Any]:
    """KONTROLDE bekleyen cihaz/ürünler ve bekleme günü (seri sayısı = envanter listesi)."""
    return await rapor_svc.kontrolde_bekleme(db, user, clock)


@router.get("/raporlar/kontrolde-bekleme.xlsx")
async def rapor_kontrolde_bekleme_xlsx(
    request: Request, db: DbDep, clock: ClockDep, user: RaporAktarici
) -> Response:
    r = await rapor_svc.kontrolde_bekleme(db, user, clock)
    tablo = [
        [
            s["urun_kodu"] or "",
            s["urun_adi"] or "",
            str(s["serial_no"]),
            1,
            s["depo_adi"] or "",
            s["giris_at"],
            s["bekleme_gun"],
        ]
        for s in r["seri"]
    ] + [
        [
            s["urun_kodu"] or "",
            s["urun_adi"] or "",
            "",
            s["adet"],
            s["depo_adi"] or "",
            s["son_giris_at"],
            s["bekleme_gun"],
        ]
        for s in r["toplu"]
    ]
    await _rapor_denetimi(request, db, user, "kontrolde-bekleme", len(tablo))
    S = export_svc.Sutun
    icerik = await export_svc.sayfalari_xlsx_async(
        [
            export_svc.Sayfa(
                "Kontrolde Bekleme",
                [
                    S("Ürün Kodu"),
                    S("Ürün"),
                    S("Seri No"),
                    S("Adet", "tamsayi"),
                    S("Depo"),
                    S("Kontrole Giriş", "zaman"),
                    S("Bekleme (gün)", "tamsayi"),
                ],
                tablo,
            )
        ]
    )
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="kiralama-kontrolde-bekleme.xlsx"'},
    )


# --- Depo sayımı (TS-195, E06-22 b) -----------------------------------------------------
# Sayım kimliği sorguda/gövdede: yol parametresi `{sayim_id}` uç taramasının
# sözleşmesinde yok; kapsam kontrolü yine yazmadan ÖNCE yapılır (404).


async def _sayim(db: AsyncSession, user: User, sayim_id: int, *, kilit: bool = False):
    try:
        return await sayim_svc.kapsamli_sayim(db, user, sayim_id, kilit=kilit)
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc


def _sayim_hatasi(exc: Exception) -> HTTPException:
    if isinstance(exc, KiralamaHatasi) and exc.veri and exc.kod == "KURAL":
        return HTTPException(status.HTTP_409_CONFLICT, {"mesaj": exc.mesaj, **exc.veri})
    return _hata(exc)


@router.get("/sayimlar")
async def sayimlar(
    db: DbDep,
    user: Okuyucu,
    response: Response,
    durum: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Kapsamdaki kiralama depolarının sayımları (`X-Toplam-Kayit`)."""
    stmt = sayim_svc.sayim_sorgusu(user)
    if durum:
        from app.models.servis_kiralama import KIRALIK_SAYIM_DURUMLARI

        if durum not in KIRALIK_SAYIM_DURUMLARI:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen durum: {durum}")
        from app.models import RentalCount

        stmt = stmt.where(RentalCount.durum == durum)
    kayitlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [await sayim_svc.ozet_ciktisi(db, s) for s, _ in kayitlar]


@router.post("/sayimlar", status_code=status.HTTP_201_CREATED)
async def sayim_ac(
    payload: SayimAcIn, request: Request, db: DbDep, clock: ClockDep, user: Envanterci
) -> dict[str, Any]:
    """Depoda sayım başlatır; aynı depoda ikinci açık sayım 409. Hiçbir bakiye değişmez."""
    try:
        sayim = await sayim_svc.sayim_ac(
            db, user, clock, depo_id=payload.depo_id, notes=payload.notes, ip=client_ip(request)
        )
    except KiralamaHatasi as exc:
        raise _sayim_hatasi(exc) from exc
    await db.commit()
    return await sayim_svc.ozet_ciktisi(db, sayim, ayrinti=True)


@router.get("/sayim")
async def sayim_detay(sayim_id: int, db: DbDep, user: Okuyucu) -> dict[str, Any]:
    return await sayim_svc.ozet_ciktisi(db, await _sayim(db, user, sayim_id), ayrinti=True)


@router.put("/sayim/satirlar")
async def sayim_satirlari(
    payload: SayimSatirlariIn, request: Request, db: DbDep, user: Envanterci
) -> dict[str, Any]:
    """Sayılan seri/adetler (satırların tamamı). Onaysız sayım hiçbir şeyi değiştirmez."""
    sayim = await _sayim(db, user, payload.sayim_id, kilit=True)
    try:
        await sayim_svc.satirlari_yaz(
            db,
            user,
            sayim,
            [sayim_svc.SayimSatiri(**s.model_dump()) for s in payload.satirlar],
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _sayim_hatasi(exc) from exc
    await db.commit()
    return await sayim_svc.ozet_ciktisi(db, sayim, ayrinti=True)


@router.get("/sayim/fark")
async def sayim_farki(sayim_id: int, db: DbDep, user: Okuyucu) -> dict[str, Any]:
    """Sistemde olup sayılmayan, sayılıp sistemde olmayan ve adet farkı satırları."""
    sayim = await _sayim(db, user, sayim_id)
    return await sayim_svc.fark(db, user, sayim)


@router.post("/sayim/onayla")
async def sayim_onayla(
    payload: SayimOnayIn, request: Request, db: DbDep, clock: ClockDep, user: Envanterci
) -> dict[str, Any]:
    """Yalnız seçilen fark satırları `SAYIM` hareketi yazar (eksik seri → KAYIP)."""
    sayim = await _sayim(db, user, payload.sayim_id, kilit=True)
    try:
        hareketler = await sayim_svc.onayla(
            db,
            user,
            clock,
            sayim,
            kararlar=payload.kararlar,
            gerekce=payload.gerekce,
            degisimi_kabul=payload.degisimi_kabul,
            ip=client_ip(request),
        )
    except KiralamaHatasi as exc:
        raise _sayim_hatasi(exc) from exc
    await db.commit()
    cikti = await sayim_svc.ozet_ciktisi(db, sayim, ayrinti=True)
    cikti["hareketler"] = [h.id for h in hareketler]
    return cikti


@router.post("/sayim/iptal")
async def sayim_iptal(
    payload: SayimIptalIn, request: Request, db: DbDep, user: Envanterci
) -> dict[str, Any]:
    sayim = await _sayim(db, user, payload.sayim_id, kilit=True)
    try:
        await sayim_svc.iptal(db, user, sayim, gerekce=payload.gerekce, ip=client_ip(request))
    except KiralamaHatasi as exc:
        raise _sayim_hatasi(exc) from exc
    await db.commit()
    return await sayim_svc.ozet_ciktisi(db, sayim)


def _kalem_girdisi(k: KalemIn) -> svc.KalemGirdisi:
    return svc.KalemGirdisi(product_id=k.product_id, qty=k.qty, note=k.note, id=k.id)


def _irtibat_girdisi(i: IrtibatIn) -> svc.IrtibatGirdisi:
    return svc.IrtibatGirdisi(contact_id=i.contact_id, rol=i.rol, id=i.id)


@router.post("", response_model=KiralamaKarti, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: KiralamaIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> KiralamaKarti:
    """Başlık + kalem + irtibat tek işlem. Müşteri `is_musteri` değil/yok → 400."""
    try:
        k = await svc.olustur(
            db,
            svc.KiralamaGirdisi(
                birim=payload.birim,
                customer_id=payload.customer_id,
                baslangic=payload.baslangic,
                bitis=payload.bitis,
                address_id=payload.address_id,
                lokasyon_metni=payload.lokasyon_metni,
                proje_adi=payload.proje_adi,
                sorumlu_user_id=payload.sorumlu_user_id,
                quote_id=payload.quote_id,
                notes=payload.notes,
                kalemler=[_kalem_girdisi(x) for x in payload.kalemler],
                irtibatlar=[_irtibat_girdisi(x) for x in payload.irtibatlar],
            ),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _kart_yanit(db, k, user, clock)


# --- Kiralama: tek kayıt ------------------------------------------------------------------


@router.get("/{kiralama_id}", response_model=KiralamaKarti)
async def getir(kiralama_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> KiralamaKarti:
    k = await _kiralama(db, user, kiralama_id)
    return await _kart(db, k, user, clock)


@router.get("/{kiralama_id}/gecmis", response_model=list[OlayOut])
async def gecmis(kiralama_id: int, db: DbDep, user: Okuyucu) -> list[OlayOut]:
    """Olay geçmişi (ekleme-yalnız); geri alınan olaylar işaretli."""
    k = await _kiralama(db, user, kiralama_id)
    olaylar = (
        await db.execute(
            select(RentalEvent, User.full_name)
            .outerjoin(User, User.id == RentalEvent.created_by)
            .where(RentalEvent.rental_id == k.id)
            .order_by(RentalEvent.at, RentalEvent.id)
        )
    ).all()
    geri = {o.geri_alinan_event_id for o, _ in olaylar if o.geri_alinan_event_id}
    return [
        OlayOut(
            id=o.id,
            at=o.at,
            tur=o.tur,
            onceki_durum=o.onceki_durum,
            yeni_durum=o.yeni_durum,
            alan=o.alan,
            eski=o.eski,
            yeni=o.yeni,
            service_order_id=o.service_order_id,
            ekip_user_ids=o.ekip_user_ids,
            gerekce=o.gerekce,
            geri_alinan_event_id=o.geri_alinan_event_id,
            geri_alindi=o.id in geri,
            kullanici=ad,
        )
        for o, ad in olaylar
    ]


@router.put("/{kiralama_id}", response_model=KiralamaKarti)
async def guncelle(
    kiralama_id: int,
    payload: KiralamaPut,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> KiralamaKarti:
    """Başlık, kalem ve irtibat tek işlemde; eski `version` 409; durum/birim 400."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    if payload.version != k.version:
        raise HTTPException(status.HTTP_409_CONFLICT, _KILIT_MESAJI)
    onay = _cakisma_onayi(payload)
    alanlar = payload.model_dump(
        exclude_unset=True, exclude={"version", "cakisma_onay", "cakisma_gerekcesi"}
    )
    if payload.kalemler is not None:
        alanlar["kalemler"] = [_kalem_girdisi(x) for x in payload.kalemler]
    if payload.irtibatlar is not None:
        alanlar["irtibatlar"] = [_irtibat_girdisi(x) for x in payload.irtibatlar]
    try:
        await svc.guncelle(
            db, k, alanlar, user=user, clock=clock, ip=client_ip(request), cakisma_onayi=onay
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await _cakisma_denetimi(db, k, onay, islem="tarih", user=user, request=request)
    await db.commit()
    return await _kart_yanit(db, k, user, clock)


async def _islem(db: AsyncSession, k: Rental, user: User, clock, fn) -> KiralamaKarti:
    try:
        await fn()
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return await _kart_yanit(db, k, user, clock)


@router.post("/{kiralama_id}/planla", response_model=KiralamaKarti)
async def planla(kiralama_id: int, db: DbDep, clock: ClockDep, user: Yazici) -> KiralamaKarti:
    """TALEP → PLANLANDI; tarih bazlı müsaitlik yetmezse 409 ("X adet eksik")."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    return await _islem(db, k, user, clock, lambda: svc.planla(db, k, user=user, clock=clock))


@router.post("/{kiralama_id}/tahsis", response_model=KiralamaKarti)
async def tahsis(
    kiralama_id: int,
    payload: TahsisIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Envanterci,
) -> KiralamaKarti:
    """Kalem → depo/cihaz tahsisi; kalem toplamı aşılamaz. Seri cihazın başka
    kiralamayla tarih çakışması 409 UYARI (M10.1): onay + gerekçeyle geçilir."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    onay = _cakisma_onayi(payload)
    satirlar = [tahsis_svc.TahsisSatiri(**s.model_dump()) for s in payload.satirlar]

    async def _tahsis() -> None:
        await tahsis_svc.tahsis_et(db, k, satirlar, user=user, clock=clock, cakisma_onayi=onay)
        await _cakisma_denetimi(db, k, onay, islem="tahsis", user=user, request=request)

    return await _islem(db, k, user, clock, _tahsis)


@router.post("/{kiralama_id}/tahsis/{tahsis_id}/coz", response_model=KiralamaKarti)
async def tahsis_coz(
    kiralama_id: int, tahsis_id: int, db: DbDep, clock: ClockDep, user: Envanterci
) -> KiralamaKarti:
    """Sevk edilmemiş tahsisi çözer (`TAHSIS_COZ`)."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)

    async def _coz():
        t = await tahsis_svc.kapsamli_tahsis(db, k, tahsis_id)
        await tahsis_svc.tahsis_coz(db, k, t, user=user, clock=clock)

    return await _islem(db, k, user, clock, _coz)


@router.post("/{kiralama_id}/sevk", response_model=KiralamaKarti)
async def sevk(
    kiralama_id: int, payload: SevkIn, db: DbDep, clock: ClockDep, user: Asamaci
) -> KiralamaKarti:
    """İlk sevk: her kalem tamamen tahsisli olmalı (400 + eksik listesi); sonrası ek sevk."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    satirlar = (
        None
        if payload.satirlar is None
        else [tahsis_svc.SevkSatiri(**s.model_dump()) for s in payload.satirlar]
    )
    return await _islem(
        db,
        k,
        user,
        clock,
        lambda: tahsis_svc.sevk_et(
            db, k, satirlar, at=payload.at, user=user, clock=clock, note=payload.not_
        ),
    )


@router.post("/{kiralama_id}/degisim", response_model=KiralamaKarti)
async def degisim(
    kiralama_id: int,
    payload: DegisimIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Asamaci,
) -> KiralamaKarti:
    """Sahada seri cihaz değişimi: yeni tahsis + sevk + eski cihazın iadesi (tek işlem).
    Hazır olmayan yeni cihaz 409; başka kiralamaya tarih çakışırsa 409 UYARI
    (M10.1, onay + gerekçeyle geçilir)."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    onay = _cakisma_onayi(payload)

    async def _degisim() -> None:
        await tahsis_svc.degisim(
            db,
            k,
            eski_tahsis_id=payload.eski_tahsis_id,
            yeni_kiralik_id=payload.yeni_kiralik_id,
            iade_depo_id=payload.iade_depo_id,
            user=user,
            clock=clock,
            note=payload.not_,
            cakisma_onayi=onay,
        )
        await _cakisma_denetimi(db, k, onay, islem="degisim", user=user, request=request)

    return await _islem(db, k, user, clock, _degisim)


@router.post("/{kiralama_id}/asama", response_model=KiralamaKarti)
async def asama(
    kiralama_id: int, payload: AsamaIn, db: DbDep, clock: ClockDep, user: Asamaci
) -> KiralamaKarti:
    """Kurulum yapıldı / devreye alındı / toplandı (aynı aşama tekrarı 409)."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    return await _islem(
        db,
        k,
        user,
        clock,
        lambda: svc.asama_ilerlet(
            db,
            k,
            payload.asama,
            user=user,
            clock=clock,
            at=payload.at,
            service_order_id=payload.service_order_id,
            note=payload.not_,
        ),
    )


@router.post("/{kiralama_id}/iade", response_model=KiralamaKarti)
async def iade(
    kiralama_id: int, payload: IadeIn, db: DbDep, clock: ClockDep, user: Asamaci
) -> KiralamaKarti:
    """İade: depoya (KONTROLDE), kayıp ya da müşteride (not). Tamamlanınca DEPOYA_ALINDI."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    satirlar = [
        tahsis_svc.IadeSatiri(
            tahsis_id=s.tahsis_id, sonuc=s.sonuc, adet=s.adet, depo_id=s.depo_id, note=s.not_
        )
        for s in payload.satirlar
    ]
    return await _islem(
        db,
        k,
        user,
        clock,
        lambda: tahsis_svc.iade_al(db, k, satirlar, at=payload.at, user=user, clock=clock),
    )


@router.post("/{kiralama_id}/geri-al", response_model=KiralamaKarti)
async def geri_al(
    kiralama_id: int,
    payload: GeriAlIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Asamaci,
) -> KiralamaKarti:
    """Son aşamayı gerekçeyle geri alır (ters hareket; kayıt silinmez)."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    return await _islem(
        db,
        k,
        user,
        clock,
        lambda: svc.asama_geri_al(
            db,
            k,
            payload.gerekce,
            user=user,
            clock=clock,
            olay_id=payload.olay_id,
            ip=client_ip(request),
        ),
    )


@router.post("/{kiralama_id}/iptal", response_model=KiralamaKarti)
async def iptal(
    kiralama_id: int,
    payload: GerekceIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> KiralamaKarti:
    """İptal: gerekçe zorunlu (400); sevk edilmişse 409; tahsisler çözülür."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    return await _islem(
        db,
        k,
        user,
        clock,
        lambda: svc.iptal(db, k, payload.gerekce, user=user, clock=clock, ip=client_ip(request)),
    )


@router.post("/{kiralama_id}/kapat", response_model=KiralamaKarti)
async def kapat(
    kiralama_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> KiralamaKarti:
    """DEPOYA_ALINDI → KAPANDI; müşteride cihaz varsa 409."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    return await _islem(
        db, k, user, clock, lambda: svc.kapat(db, k, user=user, clock=clock, ip=client_ip(request))
    )


@router.post("/{kiralama_id}/servis-isi", status_code=status.HTTP_201_CREATED)
async def servis_isi(
    kiralama_id: int,
    payload: ServisIsiIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IsAcici,
) -> dict[str, Any]:
    """Kurulum/toplama servis işi (PLANLAMADA doğar); aynı türde ikinci açık iş 409."""
    k = await _kiralama(db, user, kiralama_id, kilit=True)
    try:
        so = await svc.servis_isi_ac(
            db, k, payload.tur, user=user, clock=clock, ip=client_ip(request)
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"id": so.id, "so_no": so.so_no, "tur": so.tur, "status": so.status}


@router.get("/{kiralama_id}/tutanak.pdf")
async def tutanak(
    kiralama_id: int,
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    tur: str = Query(default="TESLIM", pattern="^(TESLIM|IADE)$"),
) -> Response:
    """Teslim/iade tutanağı (fiyatsız; sevk öncesi TASLAK filigranı)."""
    k = await _kiralama(db, user, kiralama_id)
    try:
        icerik = await svc.tutanak_pdf(db, k, tur=tur, clock=clock)
    except PdfUretilemedi as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except KiralamaHatasi as exc:
        raise _hata(exc) from exc
    return Response(
        content=icerik,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{k.rental_no}-{tur.lower()}-tutanagi.pdf"'
        },
    )
