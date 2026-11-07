"""Kurulu ekipman kütüğü uçları (TS-050…057).

Kurallar (plan §2.2 E03, §4.5):

- **Okuma `ekipman.gor`, yazma `ekipman.yaz`, Excel `ekipman.gor` +
  `servis_rapor.disaaktar`** (KD-06: servis rollerine `rapor.disaaktar`
  verilmez).
- **Kapsam:** her uç birim + müşteri kapsamından geçer; liste, KPI özeti,
  Excel, öneri ve arama AYNI sorgudan (`ekipman.liste_sorgusu`). `{ekipman_id}`
  uçlarında kapsam dışı kayıt 404 ve hiçbir yazma yapılmaz (kontrol önce).
- **Statik yollar** (`/ozet`, `/oneri`, `/liste.xlsx`, `/toplu-durum`,
  `/garanti/...`) `/{ekipman_id}` yolundan ÖNCE tanımlanır.
- Fiziksel silme ucu YOK: pasife alma var (kayıt geçmişi ve sözleşme bağı
  ekipmana bağlı kalır).
- Gövde modelleri `json_schema_extra` örneği taşır: uç taraması
  (`test_router_kapsam_taramasi`) geçerli gövdeyle 404'ü sınayabilsin.
"""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.api.search import AramaSonucu, arayici_kaydet
from app.models import Account, Address, Contact, ServiceEquipment, User
from app.services import audit, kvkk
from app.services import export as export_svc
from app.services.normalize import normalize_seri
from app.services.statemachine import SERVIS_EKIPMANI
from app.services.teknik_servis import ekipman as svc
from app.services.teknik_servis.ana_veri import AnaVeriHatasi
from app.services.teknik_servis.ekipman import (
    EkipmanBulunamadi,
    EkipmanGirdisi,
    EkipmanHatasi,
    EkipmanSuzgeci,
)
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun

router = APIRouter(prefix="/api/teknik-servis/ekipman", tags=["servis-ekipman"])

Okuyucu = Annotated[User, Depends(require_permission("ekipman.gor"))]
Yazici = Annotated[User, Depends(require_permission("ekipman.yaz"))]
Aktarici = Annotated[User, Depends(require_permission("ekipman.gor", "servis_rapor.disaaktar"))]

_HATALAR = (EkipmanBulunamadi, AnaVeriHatasi, ServisHatasi, ServisGirdiHatasi)


def _hata(exc: Exception) -> HTTPException:
    """Servis hatasını HTTP'ye çevirir: 404 kapsam/yok, 400 girdi, 409 kural."""
    if isinstance(exc, EkipmanBulunamadi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc) or "Ekipman bulunamadı")
    if isinstance(exc, AnaVeriHatasi):
        if exc.veri:
            return HTTPException(exc.kod, {"mesaj": exc.mesaj, **exc.veri})
        return HTTPException(exc.kod, exc.mesaj)
    if isinstance(exc, EkipmanHatasi) and exc.veri:
        return HTTPException(status.HTTP_409_CONFLICT, {"mesaj": exc.mesaj, **exc.veri})
    if isinstance(exc, ServisGirdiHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


# --- Şemalar ---------------------------------------------------------------------


class EkipmanIn(BaseModel):
    birim: str = Field(max_length=20)
    equipment_type: str = Field(max_length=30)
    account_id: int
    address_id: int | None = None
    contact_id: int | None = None
    contact_name_raw: str | None = Field(default=None, max_length=120)
    product_id: int | None = None
    brand: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    serial_no: str | None = Field(default=None, max_length=200)
    zone: str | None = Field(default=None, max_length=120)
    delivery_date: date | None = None
    install_date: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    warranty_source: str | None = None
    lifecycle_status: str = "BILINMIYOR"
    duplicate_ack_reason: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "birim": "GUVENLIK",
                    "equipment_type": "XRAY",
                    "account_id": 1,
                    "brand": "Smiths",
                    "model": "HI-SCAN 6040",
                    "serial_no": "00123/A-7",
                }
            ]
        }
    }


class EkipmanPatch(BaseModel):
    birim: str | None = Field(default=None, max_length=20)
    equipment_type: str | None = Field(default=None, max_length=30)
    account_id: int | None = None
    address_id: int | None = None
    contact_id: int | None = None
    contact_name_raw: str | None = Field(default=None, max_length=120)
    product_id: int | None = None
    brand: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    serial_no: str | None = Field(default=None, max_length=200)
    zone: str | None = Field(default=None, max_length=120)
    delivery_date: date | None = None
    install_date: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    warranty_source: str | None = None
    duplicate_ack_reason: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)
    # Kayıtlı frekans (yalnız Haberleşme; alanlar `cihaz_bilgisi.FREKANS_ALANLARI`).
    frekans: dict[str, Any] | None = None
    version: int

    model_config = {"json_schema_extra": {"examples": [{"version": 1, "zone": "B Kapısı Giriş"}]}}


class GerekceIn(BaseModel):
    gerekce: str = Field(max_length=500)

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "Hatalı açılmış kayıt"}]}}


class AktifIn(BaseModel):
    gerekce: str = Field(max_length=500)
    # Aktifleşen kayıt başka aktif kayıtla aynı seriyi taşıyorsa "farklı cihaz" onayı.
    mukerrer_gerekcesi: str | None = Field(default=None, max_length=1000)

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "Yanlışlıkla pasife alındı"}]}}


class DurumIn(BaseModel):
    hedef: str = Field(max_length=20)
    gerekce: str | None = Field(default=None, max_length=500)
    tarih: date | None = None

    model_config = {
        "json_schema_extra": {"examples": [{"hedef": "KURULU", "gerekce": "Kurulum tamamlandı"}]}
    }


class TopluDurumIn(BaseModel):
    idler: list[int] = Field(min_length=1, max_length=svc.TOPLU_UST_SINIR)
    hedef: str = Field(max_length=20)
    gerekce: str | None = Field(default=None, max_length=500)

    model_config = {
        "json_schema_extra": {
            "examples": [{"idler": [1], "hedef": "DEVRE_DISI", "gerekce": "Tesis kapandı"}]
        }
    }


class TopluGarantiIn(BaseModel):
    # Boşsa kapsamdaki bütün garantisi bilinmeyen kayıtlar.
    idler: list[int] | None = None
    birim: str | None = None

    model_config = {"json_schema_extra": {"examples": [{"idler": [1]}]}}


class SozlesmeBagi(BaseModel):
    kalem_id: int
    sozlesme_id: int
    sozlesme_no: str


class EkipmanSatiri(BaseModel):
    id: int
    birim: str
    equipment_type: str
    brand: str | None
    model: str | None
    serial_no: str | None
    seri_eksik: bool
    account_id: int | None
    hesap_unvan: str | None
    address_id: int | None
    lokasyon_adi: str | None
    il: str | None
    zone: str | None
    lifecycle_status: str
    is_active: bool
    install_date: date | None
    warranty_end: date | None
    garanti_durumu: str
    serviste: bool
    sozlesme_sayisi: int
    version: int


class EkipmanKarti(EkipmanSatiri):
    product_id: int | None
    product_raw: str | None
    customer_name_raw: str | None
    location_raw: str | None
    # İrtibat yalnız `servis.irtibat_gor` ya da `ekipman.yaz` olana (KVKK en az erişim).
    irtibat_adi: str | None = None
    contact_id: int | None = None
    contact_name_raw: str | None = None
    delivery_date: date | None
    delivery_date_raw: str | None
    warranty_start: date | None
    warranty_source: str | None
    duplicate_ack_reason: str | None
    notes: str | None
    frekans: dict[str, Any] | None = None
    merged_into_id: int | None
    sonraki_durumlar: list[str]
    aktif_sozlesmeler: list[SozlesmeBagi]
    ek_sayisi: int
    acik_is_sayisi: int
    created_at: datetime
    updated_at: datetime
    uyarilar: list[str] = []


class KpiOut(BaseModel):
    kod: str
    baslik: str
    tanim: str
    deger: int


class GecmisOlayi(BaseModel):
    tarih: datetime
    tur: str
    baslik: str
    durum: str | None = None
    kaynak: str
    kaynak_id: int
    sure_dakika: int | None = None
    sure_eksik: bool = False
    eslesme: str = "KIMLIK"
    # `maliyet` anahtarı yalnız `maliyet.gor` olana ve yalnız kaynak verirse
    # eklenir (response_model_exclude_unset ile anahtar hiç yazılmaz).
    maliyet: float | None = None


class Degisiklik(BaseModel):
    id: int
    zaman: datetime
    eylem: str
    etiket: str
    kullanici_id: int | None
    kullanici: str | None
    kisisel: bool
    eski: dict[str, Any]
    yeni: dict[str, Any]


class OneriOut(BaseModel):
    durum: str
    ekipman: EkipmanSatiri | None = None


# --- Yardımcılar -----------------------------------------------------------------


def _irtibat_gorur(user: User) -> bool:
    return user.has("servis.irtibat_gor") or user.has("ekipman.yaz")


def _satir(
    e: ServiceEquipment,
    unvan: str | None,
    tesis: str | None,
    il: str | None,
    *,
    bugun: date,
    serviste: set[int],
    sozlesmeler: dict[int, list[dict[str, Any]]],
) -> EkipmanSatiri:
    return EkipmanSatiri(
        id=e.id,
        birim=e.birim,
        equipment_type=e.equipment_type,
        brand=e.brand,
        model=e.model,
        serial_no=e.serial_no,
        seri_eksik=e.serial_key is None,
        account_id=e.account_id,
        hesap_unvan=unvan,
        address_id=e.address_id,
        lokasyon_adi=tesis,
        il=il,
        zone=e.zone,
        lifecycle_status=e.lifecycle_status,
        is_active=e.is_active,
        install_date=e.install_date,
        warranty_end=e.warranty_end,
        garanti_durumu=svc.garanti_durumu(e, bugun),
        serviste=e.id in serviste,
        sozlesme_sayisi=len(sozlesmeler.get(e.id, [])),
        version=e.version,
    )


async def _satirlar(db: AsyncSession, kayitlar: list, clock) -> list[EkipmanSatiri]:
    idler = [r[0].id for r in kayitlar]
    serviste = await svc.servistekiler(db, idler)
    sozlesmeler = await svc.aktif_sozlesmeler(db, idler, clock.now())
    bugun = yerel_bugun(clock)
    return [
        _satir(e, u, t, il, bugun=bugun, serviste=serviste, sozlesmeler=sozlesmeler)
        for e, u, t, il in kayitlar
    ]


async def _kart(
    db: AsyncSession, e: ServiceEquipment, user: User, clock, *, uyarilar: list[str] | None = None
) -> EkipmanKarti:
    hesap = await db.get(Account, e.account_id) if e.account_id else None
    adres = await db.get(Address, e.address_id) if e.address_id else None
    satir = (
        await _satirlar(
            db,
            [
                (
                    e,
                    hesap.title if hesap else None,
                    adres.site_name if adres else None,
                    adres.city if adres else None,
                )
            ],
            clock,
        )
    )[0]
    sozlesmeler = (await svc.aktif_sozlesmeler(db, [e.id], clock.now())).get(e.id, [])
    irtibat_adi = None
    if _irtibat_gorur(user):
        if e.contact_id:
            kisi = await db.get(Contact, e.contact_id)
            irtibat_adi = kisi.full_name if kisi else None
        irtibat_adi = irtibat_adi or e.contact_name_raw
    yazabilir = user.has("ekipman.yaz")
    return EkipmanKarti(
        **satir.model_dump(),
        product_id=e.product_id,
        product_raw=e.product_raw,
        customer_name_raw=e.customer_name_raw,
        location_raw=e.location_raw,
        irtibat_adi=irtibat_adi,
        contact_id=e.contact_id if yazabilir else None,
        contact_name_raw=e.contact_name_raw if yazabilir else None,
        delivery_date=e.delivery_date,
        delivery_date_raw=e.delivery_date_raw,
        warranty_start=e.warranty_start,
        warranty_source=e.warranty_source,
        duplicate_ack_reason=e.duplicate_ack_reason,
        notes=e.notes,
        frekans=e.frekans,
        merged_into_id=e.merged_into_id,
        sonraki_durumlar=sorted(SERVIS_EKIPMANI.sonraki(e.lifecycle_status)),
        aktif_sozlesmeler=[SozlesmeBagi(**s) for s in sozlesmeler],
        ek_sayisi=await svc.ek_sayisi(db, e.id),
        acik_is_sayisi=await svc.acik_is_sayisi(db, e.id),
        created_at=e.created_at,
        updated_at=e.updated_at,
        uyarilar=uyarilar or [],
    )


async def _ekipman(db: AsyncSession, user: User, ekipman_id: int) -> ServiceEquipment:
    try:
        return await svc.kapsamli_ekipman(db, user, ekipman_id)
    except EkipmanBulunamadi as exc:
        raise _hata(exc) from exc


def _suzgec(
    q: str | None = None,
    birim: str | None = None,
    tip: str | None = None,
    marka: str | None = None,
    model: str | None = None,
    durum: str | None = None,
    hesap_id: int | None = None,
    lokasyon_id: int | None = None,
    sozlesme_id: int | None = None,
    garanti: str | None = Query(default=None, description="GECERLI | BITTI | BILINMIYOR"),
    seri_eksik: bool | None = None,
    lokasyonsuz: bool = False,
    sozlesmesiz: bool = False,
    serviste: bool | None = None,
    pasifler_dahil: bool = False,
    kpi: str | None = None,
    kalite: str | None = Query(default=None, description="Veri kalitesi listesi (TS-188)"),
    ids: str | None = Query(default=None, description="Virgülle ayrılmış ekipman kimlikleri"),
) -> EkipmanSuzgeci:
    idler: list[int] | None = None
    if ids:
        try:
            idler = [int(p) for p in ids.split(",") if p.strip()]
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçersiz kimlik listesi") from exc
    return EkipmanSuzgeci(
        q=q,
        birim=birim,
        tip=tip,
        marka=marka,
        model=model,
        durum=durum,
        hesap_id=hesap_id,
        lokasyon_id=lokasyon_id,
        sozlesme_id=sozlesme_id,
        garanti=garanti,
        seri_eksik=seri_eksik,
        lokasyonsuz=lokasyonsuz,
        sozlesmesiz=sozlesmesiz,
        serviste=serviste,
        pasifler_dahil=pasifler_dahil,
        kpi=kpi,
        idler=idler,
        kalite=kalite,
    )


async def _esikli_suzgec(db: DbDep, s: Annotated[EkipmanSuzgeci, Depends(_suzgec)]):
    """Analitik KPI eşikleri ayardan yüklenir (liste, özet ve Excel aynı eşik)."""
    if s.kalite is not None and s.kalite not in svc.KALITE_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen kalite kodu: {s.kalite}")
    if s.kpi is not None and s.kpi not in svc.KPI_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen KPI kodu: {s.kpi}")
    s.esikler = await svc.kpi_esikleri(db)
    return s


Suzgec = Annotated[EkipmanSuzgeci, Depends(_esikli_suzgec)]


def _sorgu(user: User, s: EkipmanSuzgeci, clock):
    try:
        return svc.liste_sorgusu(user, s, bugun=yerel_bugun(clock), an=clock.now())
    except _HATALAR as exc:
        raise _hata(exc) from exc


# --- Liste, özet, Excel, öneri (statik yollar) ------------------------------------


@router.get("", response_model=list[EkipmanSatiri])
async def listele(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    response: Response,
    s: Suzgec,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[EkipmanSatiri]:
    """Kütük listesi; sunucu süzgeci + sayfalama, toplam `X-Toplam-Kayit`'ta."""
    kayitlar = await sayfala(db, response, _sorgu(user, s, clock), limit=limit, offset=offset)
    return await _satirlar(db, list(kayitlar), clock)


@router.get("/ozet", response_model=list[KpiOut])
async def ozet(db: DbDep, clock: ClockDep, user: Okuyucu) -> list[dict[str, Any]]:
    """KPI kutuları. Her sayı = `?kpi=<kod>` listesinin `X-Toplam-Kayit`'ı."""
    return await svc.ozet(db, user, clock)


_EXCEL_BASLIKLARI = [
    "ID",
    "Birim",
    "Tip",
    "Marka",
    "Model",
    "Seri No",
    "Müşteri",
    "Lokasyon",
    "İl",
    "Bölge",
    "Durum",
    "Kayıt",
    "Kurulum",
    "Garanti Bitiş",
    "Garanti",
    "Serviste",
]


@router.get("/liste.xlsx")
async def disa_aktar(
    request: Request, db: DbDep, clock: ClockDep, user: Aktarici, s: Suzgec
) -> Response:
    """Ekrandaki süzgecin AYNI satırları; seri no METİN hücre, maliyet sütunu yok."""
    stmt = _sorgu(user, s, clock)
    toplam = await svc.say(db, stmt)
    if toplam > svc.EXCEL_UST_SINIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{toplam} satır var; Excel en çok {svc.EXCEL_UST_SINIR} satır alır. Süzgeci daraltın.",
        )
    satirlar = await _satirlar(db, list((await db.execute(stmt)).all()), clock)
    tablo = [
        [
            r.id,
            r.birim,
            r.equipment_type,
            r.brand or "",
            r.model or "",
            str(r.serial_no) if r.serial_no is not None else "",
            r.hesap_unvan or "",
            r.lokasyon_adi or "",
            r.il or "",
            r.zone or "",
            svc.DURUM_ETIKETLERI.get(r.lifecycle_status, r.lifecycle_status),
            "Aktif" if r.is_active else "Pasif",
            r.install_date,
            r.warranty_end,
            r.garanti_durumu,
            "Evet" if r.serviste else "",
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
    return Response(
        content=await export_svc.satirlari_xlsx_async(_EXCEL_BASLIKLARI, tablo, "Ekipman Kütüğü"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="ekipman-kutugu.xlsx"'},
    )


@router.get("/oneri", response_model=OneriOut)
async def oneri(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    seri: str = Query(min_length=1, max_length=200),
    hesap_id: int | None = None,
) -> OneriOut:
    """Seri no ile lokasyon önerisi (TS-054): yalnız kapsam içi TEK eşleşmede dolu."""
    eslesme = await svc.seri_ile_bul(db, seri, account_id=hesap_id, user=user)
    if eslesme.durum != "TEK":
        return OneriOut(durum=eslesme.durum)
    e = await db.get(ServiceEquipment, eslesme.ekipman_id)
    hesap = await db.get(Account, e.account_id) if e.account_id else None
    adres = await db.get(Address, e.address_id) if e.address_id else None
    satir = (
        await _satirlar(
            db,
            [
                (
                    e,
                    hesap.title if hesap else None,
                    adres.site_name if adres else None,
                    adres.city if adres else None,
                )
            ],
            clock,
        )
    )[0]
    return OneriOut(durum="TEK", ekipman=satir)


@router.post("/toplu-durum", response_model=list[EkipmanSatiri])
async def toplu_durum(
    payload: TopluDurumIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> list[EkipmanSatiri]:
    """Seçili ekipmanların durumu tek gerekçeyle — hepsi ya da hiçbiri (TS-053 T2)."""
    try:
        kayitlar = await svc.toplu_durum_degistir(
            db,
            payload.idler,
            payload.hedef,
            gerekce=payload.gerekce,
            clock=clock,
            user=user,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    stmt = svc.liste_sorgusu(
        user,
        EkipmanSuzgeci(idler=[e.id for e in kayitlar], pasifler_dahil=True),
        bugun=yerel_bugun(clock),
        an=clock.now(),
    )
    return await _satirlar(db, list((await db.execute(stmt)).all()), clock)


@router.post("/garanti/toplu-hesapla")
async def toplu_garanti(
    payload: TopluGarantiIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
    uygula: bool = False,
) -> dict[str, Any]:
    """Garanti bitişi boş kayıtlar için önizleme (`uygula=false`) ya da uygulama.

    İkisi aynı fonksiyondan geçer: önizlemedeki satır sayısı uygulananla aynı.
    `BELGE` kaynaklı kayda dokunulmaz.
    """
    try:
        sonuc = await svc.toplu_garanti(
            db,
            user,
            clock,
            idler=payload.idler,
            birim=payload.birim,
            uygula=uygula,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    if uygula:
        await db.commit()
    return sonuc


# --- Veri kalitesi, mükerrer gruplar, saha farkları (TS-188, TS-191) ---------------


class KaliteOut(BaseModel):
    kod: str
    baslik: str
    tanim: str
    liste: str
    deger: int


@router.get("/veri-kalitesi", response_model=list[KaliteOut])
async def veri_kalitesi(db: DbDep, clock: ClockDep, user: Okuyucu) -> list[dict[str, Any]]:
    """Ekipman veri kalitesi sayıları (salt okuma). `liste='liste'` olan kod
    `GET /ekipman?kalite=<kod>`'a, `mukerrer` `/mukerrer-gruplar`'a, `saha`
    `/saha-farklari`'na gider; her sayı o listenin `X-Toplam-Kayit`'ıdır."""
    return await svc.kalite_ozeti(db, user, clock)


@router.get("/mukerrer-gruplar")
async def mukerrer_gruplar(
    db: DbDep,
    user: Okuyucu,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Mükerrer seri grupları (sayfalı); `X-Toplam-Kayit` = grup sayısı."""
    toplam, gruplar = await svc.mukerrer_gruplari(db, user, limit=limit, offset=offset)
    response.headers["X-Toplam-Kayit"] = str(toplam)
    return gruplar


@router.get("/saha-farklari")
async def saha_farklari(
    db: DbDep,
    user: Okuyucu,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Sahadan gelen, karar bekleyen kütük farkları (işin kapsamıyla süzülür)."""
    satirlar = await sayfala(
        db, response, svc.saha_farklari_sorgusu(user), limit=limit, offset=offset
    )
    return await svc.saha_farki_satirlari(db, list(satirlar))


async def _is(db: AsyncSession, so_id: int):
    from app.models import ServiceOrder

    so = await db.get(ServiceOrder, so_id)
    if so is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    return so


@router.post("/saha-farklari/{so_id}/uygula", response_model=EkipmanKarti)
async def saha_farki_uygula(
    so_id: int, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> EkipmanKarti:
    """Sahadaki seri/bölgeyi kütüğe yazar. Hedef seri başka aktif kayıttaysa 409."""
    so = await _is(db, so_id)
    try:
        e = await svc.saha_farki_uygula(db, so, user=user, ip=client_ip(request))
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(e)
    return await _kart(db, e, user, clock)


@router.post("/saha-farklari/{so_id}/yoksay", status_code=status.HTTP_204_NO_CONTENT)
async def saha_farki_yoksay(
    so_id: int, payload: GerekceIn, request: Request, db: DbDep, user: Yazici
) -> None:
    """Farkı gerekçeyle kapatır; kütük değişmez, gerekçe geçmişe yazılır."""
    so = await _is(db, so_id)
    try:
        await svc.saha_farki_yoksay(db, so, payload.gerekce, user=user, ip=client_ip(request))
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()


# --- Yazma -----------------------------------------------------------------------


@router.post("", response_model=EkipmanKarti, status_code=status.HTTP_201_CREATED)
async def olustur(
    payload: EkipmanIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> EkipmanKarti:
    """Yeni ekipman. Aynı tip+marka+seri ile aktif kayıt varsa 409 (gerekçeyle geçilir)."""
    try:
        e = await svc.olustur(
            db,
            EkipmanGirdisi(**payload.model_dump()),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(e)
    return await _kart(db, e, user, clock)


# --- Tek kayıt -------------------------------------------------------------------


@router.get("/{ekipman_id}", response_model=EkipmanKarti)
async def getir(
    ekipman_id: int, request: Request, db: DbDep, clock: ClockDep, user: Okuyucu
) -> EkipmanKarti:
    """Ekipman kartı (TS-052). İrtibat gösterildiyse erişim KVKK loguna yazılır."""
    e = await _ekipman(db, user, ekipman_id)
    kart = await _kart(db, e, user, clock)
    if kart.irtibat_adi:
        await kvkk.erisim_kaydet(
            db,
            entity=svc.ENTITY,
            entity_id=e.id,
            amac="ekipman.kart",
            user_id=user.id,
            ip=client_ip(request),
        )
        await db.commit()
    return kart


@router.patch("/{ekipman_id}", response_model=EkipmanKarti)
async def guncelle(
    ekipman_id: int,
    payload: EkipmanPatch,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> EkipmanKarti:
    e = await _ekipman(db, user, ekipman_id)
    if payload.version != e.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    try:
        await svc.guncelle(
            db,
            e,
            payload.model_dump(exclude_unset=True, exclude={"version"}),
            user=user,
            clock=clock,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(e)
    return await _kart(db, e, user, clock)


@router.post("/{ekipman_id}/pasif", response_model=EkipmanKarti)
async def pasiflestir(
    ekipman_id: int, payload: GerekceIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> EkipmanKarti:
    """Kaydı pasife alır (hatalı/mükerrer kayıt). Fiziksel durum DEĞİŞMEZ."""
    e = await _ekipman(db, user, ekipman_id)
    try:
        await svc.pasife_al(db, e, payload.gerekce, user=user, ip=client_ip(request))
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(e)
    return await _kart(db, e, user, clock)


@router.post("/{ekipman_id}/aktif", response_model=EkipmanKarti)
async def aktiflestir(
    ekipman_id: int, payload: AktifIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> EkipmanKarti:
    e = await _ekipman(db, user, ekipman_id)
    try:
        await svc.aktife_al(
            db,
            e,
            payload.gerekce,
            user=user,
            ip=client_ip(request),
            mukerrer_gerekcesi=payload.mukerrer_gerekcesi,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(e)
    return await _kart(db, e, user, clock)


@router.post("/{ekipman_id}/durum", response_model=EkipmanKarti)
async def durum(
    ekipman_id: int, payload: DurumIn, request: Request, db: DbDep, clock: ClockDep, user: Yazici
) -> EkipmanKarti:
    """Yaşam döngüsü (TS-055): gerekçe zorunlu (400), kural dışı geçiş 409.

    DEVRE_DISI/HURDA'da açık servis işleri silinmez; yanıt `uyarilar` taşır.
    """
    e = await _ekipman(db, user, ekipman_id)
    try:
        await svc.durum_degistir(
            db,
            e,
            payload.hedef,
            gerekce=payload.gerekce,
            tarih=payload.tarih,
            clock=clock,
            user=user,
            ip=client_ip(request),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(e)
    return await _kart(db, e, user, clock, uyarilar=await svc.acik_is_uyarilari(db, e))


class BirlestirIn(BaseModel):
    ana_id: int
    gerekce: str = Field(max_length=500)

    model_config = {
        "json_schema_extra": {"examples": [{"ana_id": 1, "gerekce": "Aynı cihaz iki kez açılmış"}]}
    }


@router.get("/{ekipman_id}/birlestirme-engelleri")
async def birlestirme_engelleri(
    ekipman_id: int, db: DbDep, clock: ClockDep, user: Okuyucu
) -> dict[str, list]:
    """Birleştirme penceresinin ön kontrolü: ikincile bağlı açık bağlar (salt okuma)."""
    e = await _ekipman(db, user, ekipman_id)
    return await svc.birlestirme_engelleri(db, e, clock.now())


@router.post("/{ekipman_id}/birlestir", response_model=EkipmanKarti)
async def birlestir(
    ekipman_id: int,
    payload: BirlestirIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yazici,
) -> EkipmanKarti:
    """`ekipman_id` (ikincil) kaydı `ana_id`'ye birleştirir (TS-191, E03-13).

    İkincile bağlı açık sözleşme kalemi / servis işi / atölye kaydı varsa 409 +
    liste ve hiçbir şey değişmez. Yanıt ANA kaydın kartıdır.
    """
    e = await _ekipman(db, user, ekipman_id)
    try:
        ana = await svc.birlestir(
            db, e, payload.ana_id, payload.gerekce, user=user, clock=clock, ip=client_ip(request)
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(ana)
    return await _kart(db, ana, user, clock)


@router.get(
    "/{ekipman_id}/gecmis", response_model=list[GecmisOlayi], response_model_exclude_unset=True
)
async def gecmis(ekipman_id: int, db: DbDep, user: Okuyucu) -> list[GecmisOlayi]:
    """Birleşik geçmiş: servis işleri (kimlik + seri metni), bakım ziyaretleri, kütük."""
    e = await _ekipman(db, user, ekipman_id)
    return [GecmisOlayi(**o) for o in await svc.gecmis(db, e, user)]


@router.get("/{ekipman_id}/degisiklikler", response_model=list[Degisiklik])
async def degisiklikler(ekipman_id: int, db: DbDep, user: Okuyucu) -> list[dict[str, Any]]:
    """Kütük değişiklik geçmişi (TS-051). Yalnız okuma: PATCH/DELETE ucu yoktur."""
    e = await _ekipman(db, user, ekipman_id)
    return await svc.degisiklikler(db, e)


class IrtibatImhaIn(BaseModel):
    gerekce: str = Field(min_length=1, max_length=500)

    model_config = {"json_schema_extra": {"examples": [{"gerekce": "KVKK başvurusu #12"}]}}


KvkkYonetici = Annotated[User, Depends(require_permission("kvkk.yonet"))]


@router.post("/{ekipman_id}/irtibat-imha")
async def irtibat_imha(
    ekipman_id: int, payload: IrtibatImhaIn, request: Request, db: DbDep, user: KvkkYonetici
) -> dict[str, Any]:
    """KVKK (TS-057): ekipmandaki irtibat adını siler, geçmiş denetim
    satırlarındaki irtibat değerlerini maskeler. Hesabı olmayan (göç) kayıt
    için tek yol; GERİ ALINAMAZ. Kapsam dışı ekipman 404."""
    e = await _ekipman(db, user, ekipman_id)
    try:
        maskelenen = await svc.irtibat_imha(
            db, e, gerekce=payload.gerekce, user=user, ip=client_ip(request)
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await db.commit()
    return {"ekipman_id": e.id, "maskelenen_denetim_satiri": maskelenen}


# --- Genel arama (TS-057) ----------------------------------------------------------


@arayici_kaydet("ekipman.gor")
async def _ekipman_ara(db: AsyncSession, user: User, terim: str, limit: int) -> list[AramaSonucu]:
    """Genel arama: seri no (normalize) ile, kapsam içi; müşteri adı dönmez."""
    if not user.has("ekipman.gor"):
        return []
    anahtar = normalize_seri(terim)
    if len(anahtar) < 2:
        return []
    stmt = select(ServiceEquipment).where(
        ServiceEquipment.is_deleted.is_(False),
        ServiceEquipment.serial_key.contains(anahtar),
    )
    stmt = svc.ekipman_kosulu(user)(stmt).order_by(ServiceEquipment.id).limit(limit)
    return [
        AramaSonucu(
            tur="EKIPMAN",
            id=e.id,
            baslik=e.serial_no or f"Ekipman #{e.id}",
            alt_baslik=" ".join(filter(None, [e.brand, e.model])) or e.equipment_type,
            etiketler=[e.equipment_type, svc.DURUM_ETIKETLERI.get(e.lifecycle_status, "")]
            + ([] if e.is_active else ["pasif"]),
            yol=f"/servis-ekipman/{e.id}",
        )
        for e in (await db.scalars(stmt)).all()
    ]
