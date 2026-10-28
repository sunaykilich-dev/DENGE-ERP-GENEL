"""Servis lokasyonu (tesis) ve lokasyon irtibatı uçları (TS-015, E14-02).

Ayrı `sites` tablosu yok: lokasyon = `addresses` satırı (`kind='TESIS'` gidilen
yer; MERKEZ/FATURA/SEVK carinin diğer adresleri). Kurallar:

- **Okuma `hesap.gor`, yazma `lokasyon.yaz`.** Lokasyon kartı irtibat (kişisel
  veri) taşır; `servis.gor` ile yalnız hafif arama açıktır
  (`/api/teknik-servis/ana-veri/lokasyon-ara`), kart değil (KD-09).
- **Kapsam hesabın kapsamıdır:** liste `kapsam_musteri(Address.account_id)`,
  tek kayıt hesabın kapsamı dışındaysa 404 — kontrol YAZMADAN önce yapılır
  (`test_kapsam_guvenligi` kalıbı). Müşteri kaydı birime bağlı değildir (K9).
- **Silme ucu YOK** (405): servis geçmişi lokasyona bağlı kalır; pasifleme var.
- **Hesap değiştirilemez** (400): tesisi başka cariye taşımak yalnız
  birleştirmeyle yapılır, aksi halde bağlı servis kayıtları yabancı hesabın
  tesisine düşerdi.
- `version` zorunlu (iyimser kilit); uyuşmazlık 409.
- Denetim izi aynı transaction'da; adres ve irtibat kişisel veri sayılır
  (bireysel müşterinin tesisi evidir) → `is_personal_data=True`, KVKK
  anonimleştirmesi bu satırları maskeler (TS-016).
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import Account, Address, Contact, User
from app.models.account import ADRES_TURLERI
from app.services import accounts as hesap_svc
from app.services import audit, kvkk
from app.services.normalize import normalize_msisdn
from app.services.teknik_servis import ana_veri
from app.services.teknik_servis.ana_veri import AnaVeriHatasi

router = APIRouter(prefix="/api", tags=["lokasyonlar"])

Okuyucu = Annotated[User, Depends(require_permission("hesap.gor"))]
Yazici = Annotated[User, Depends(require_permission("lokasyon.yaz"))]
Dogrulayici = Annotated[User, Depends(require_permission("hesap.birlestir"))]


def _hata(exc: AnaVeriHatasi) -> HTTPException:
    if exc.veri:
        return HTTPException(exc.kod, {"mesaj": exc.mesaj, **exc.veri})
    return HTTPException(exc.kod, exc.mesaj)


# --- Şemalar ---------------------------------------------------------------------


class LokasyonIn(BaseModel):
    hesap_id: int
    kind: str = "TESIS"
    label: str | None = Field(default=None, max_length=40)
    site_name: str | None = Field(default=None, max_length=200)
    line: str | None = Field(default=None, max_length=1000)
    district: str | None = Field(default=None, max_length=60)
    city: str | None = Field(default=None, max_length=60)
    access_note: str | None = Field(default=None, max_length=2000)
    primary_contact_id: int | None = None
    is_primary: bool = False
    # Lokasyona özel SLA takvimi (M12.2, Faz A); null = müşterinin / politikanın.
    sla_takvim_turu: Literal["7_24", "MESAI"] | None = None

    @field_validator("kind")
    @classmethod
    def _tur(cls, v: str) -> str:
        if v not in ADRES_TURLERI:
            raise ValueError(f"Adres türü {ADRES_TURLERI} içinden olmalı")
        return v

    @field_validator("site_name", "line", "district", "access_note", "label")
    @classmethod
    def _kirp(cls, v: str | None) -> str | None:
        return (v.strip() or None) if isinstance(v, str) else v


class LokasyonPatch(BaseModel):
    # `hesap_id` gönderilirse ve farklıysa 400 — taşıma yalnız birleştirmeyle.
    hesap_id: int | None = None
    label: str | None = Field(default=None, max_length=40)
    site_name: str | None = Field(default=None, max_length=200)
    line: str | None = Field(default=None, max_length=1000)
    district: str | None = Field(default=None, max_length=60)
    city: str | None = Field(default=None, max_length=60)
    access_note: str | None = Field(default=None, max_length=2000)
    primary_contact_id: int | None = None
    is_primary: bool | None = None
    # Açık işlerin hedefi değişmez: takvim iş açılışında dondurulur.
    sla_takvim_turu: Literal["7_24", "MESAI"] | None = None
    version: int

    @field_validator("site_name", "line", "district", "access_note", "label")
    @classmethod
    def _kirp(cls, v: str | None) -> str | None:
        return (v.strip() or None) if isinstance(v, str) else v


class IrtibatOut(BaseModel):
    id: int
    ad: str
    gorev: str | None
    telefon: str | None
    eposta: str | None
    lokasyon_id: int | None
    birincil: bool


class LokasyonOut(BaseModel):
    id: int
    account_id: int
    hesap_unvan: str | None = None
    kind: str
    label: str
    site_name: str | None
    line: str | None
    district: str | None
    city: str | None
    access_note: str | None
    primary_contact_id: int | None
    is_primary: bool
    is_active: bool
    is_verified: bool
    sla_takvim_turu: str | None = None
    version: int
    irtibatlar: list[IrtibatOut] | None = None

    model_config = {"from_attributes": True}


class IrtibatIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    title: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=160)
    notes: str | None = None
    # İşaretliyse lokasyonun birincil irtibatı olur (`addresses.primary_contact_id`).
    # Hesap düzeyindeki tek-birincil kuralına (`contacts.is_primary`) dokunmaz.
    lokasyon_birincil: bool = False


# --- Yardımcılar -----------------------------------------------------------------


def _irtibat_cikti(kisi: Contact, birincil_id: int | None) -> IrtibatOut:
    return IrtibatOut(
        id=kisi.id,
        ad=kisi.full_name,
        gorev=kisi.title,
        telefon=kisi.phone,
        eposta=kisi.email,
        lokasyon_id=kisi.address_id,
        birincil=kisi.id == birincil_id,
    )


async def _cikti(db, adres: Address, *, irtibatlarla: bool = False) -> LokasyonOut:
    out = LokasyonOut.model_validate(adres)
    hesap = await db.get(Account, adres.account_id)
    out.hesap_unvan = hesap.title if hesap else None
    if irtibatlarla:
        kisiler = (
            await db.scalars(
                select(Contact)
                .where(Contact.address_id == adres.id)
                .order_by(Contact.full_name, Contact.id)
            )
        ).all()
        out.irtibatlar = [_irtibat_cikti(k, adres.primary_contact_id) for k in kisiler]
    return out


async def _lokasyon(db, user: User, lokasyon_id: int) -> Address:
    try:
        return await ana_veri.kapsamli_lokasyon(db, user, lokasyon_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc


async def _birincil_irtibat_dogrula(db, account_id: int, kisi_id: int | None) -> None:
    if kisi_id is None:
        return
    kisi = await db.get(Contact, kisi_id)
    if kisi is None or kisi.account_id != account_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Birincil irtibat bu hesaba ait değil")


def _il(ham: str | None) -> str | None:
    try:
        return ana_veri.il_dogrula(ham)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc


def _tesis_kurali(kind: str, site_name: str | None, line: str | None, city: str | None) -> None:
    """Şema CHECK'lerinin (ck_addresses_tesis_adi / ck_addresses_satir) Türkçe 400'ü."""
    if kind == "TESIS":
        if not site_name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tesis adı zorunlu")
        if not city:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tesisin ili zorunlu")
    elif not line:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Adres satırı zorunlu")


async def _tesis_cakisma_kontrolu(
    db, account_id: int, site_name: str | None, haric_id: int | None
) -> None:
    mevcut = await ana_veri.tesis_cakismasi(db, account_id, site_name, haric_id=haric_id)
    if mevcut is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "mesaj": "Bu hesapta aynı adlı aktif bir tesis zaten var.",
                "mevcut": ana_veri.lokasyon_satiri(mevcut),
            },
        )


# --- Liste ve kart ---------------------------------------------------------------


@router.get("/lokasyonlar", response_model=list[LokasyonOut])
async def listele(
    db: DbDep,
    user: Okuyucu,
    response: Response,
    hesap_id: int | None = None,
    q: str | None = None,
    tur: str | None = Query(default=None, description="MERKEZ | FATURA | SEVK | TESIS"),
    aktif: bool | None = None,
    dogrulanmamis: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[LokasyonOut]:
    """Lokasyon listesi; hesabın kapsamından geçer (`kapsam_musteri`)."""
    stmt = (
        select(Address)
        .join(Account, Account.id == Address.account_id)
        .where(Account.is_deleted.is_(False))
        .order_by(Address.site_name, Address.id)
    )
    stmt = hesap_svc.kapsam_musteri(stmt, user, Address.account_id)
    if hesap_id is not None:
        stmt = stmt.where(Address.account_id == hesap_id)
    if tur:
        if tur not in ADRES_TURLERI:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen adres türü: {tur}")
        stmt = stmt.where(Address.kind == tur)
    if aktif is not None:
        stmt = stmt.where(Address.is_active.is_(aktif))
    if dogrulanmamis:
        stmt = stmt.where(Address.is_verified.is_(False))
    if q:
        anahtar = ana_veri.unvan_anahtari(q)
        kosullar = [Address.line.ilike(f"%{q.strip()}%")]
        if anahtar:
            kosullar.append(Address.site_key.contains(anahtar))
        stmt = stmt.where(or_(*kosullar))
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [await _cikti(db, a) for (a,) in satirlar]


@router.get("/hesaplar/{hesap_id}/lokasyonlar", response_model=list[LokasyonOut])
async def hesap_lokasyonlari(hesap_id: int, db: DbDep, user: Okuyucu) -> list[LokasyonOut]:
    """Hesap kartının "Lokasyonlar" sekmesi: carinin bütün adresleri."""
    try:
        await ana_veri.kapsamli_hesap(db, user, hesap_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    adresler = (
        await db.scalars(
            select(Address)
            .where(Address.account_id == hesap_id)
            .order_by(Address.is_active.desc(), Address.kind, Address.site_name, Address.id)
        )
    ).all()
    return [await _cikti(db, a) for a in adresler]


@router.get("/lokasyonlar/{lokasyon_id}", response_model=LokasyonOut)
async def getir(lokasyon_id: int, request: Request, db: DbDep, user: Okuyucu) -> LokasyonOut:
    """Lokasyon kartı (irtibatlarla). Açılış kişisel veri erişimi olarak loglanır."""
    adres = await _lokasyon(db, user, lokasyon_id)
    out = await _cikti(db, adres, irtibatlarla=True)
    await kvkk.erisim_kaydet(
        db,
        entity="addresses",
        entity_id=adres.id,
        amac="lokasyon.kart",
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return out


# --- Yazma -----------------------------------------------------------------------


@router.post("/lokasyonlar", response_model=LokasyonOut, status_code=status.HTTP_201_CREATED)
async def olustur(payload: LokasyonIn, request: Request, db: DbDep, user: Yazici) -> LokasyonOut:
    try:
        hesap = await ana_veri.kapsamli_hesap(db, user, payload.hesap_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc

    il = _il(payload.city)
    _tesis_kurali(payload.kind, payload.site_name, payload.line, il)
    await _birincil_irtibat_dogrula(db, hesap.id, payload.primary_contact_id)
    if payload.kind == "TESIS":
        await _tesis_cakisma_kontrolu(db, hesap.id, payload.site_name, None)

    adres = Address(
        account_id=hesap.id,
        kind=payload.kind,
        label=payload.label or ("Tesis" if payload.kind == "TESIS" else "Merkez"),
        site_name=payload.site_name,
        line=payload.line,
        district=payload.district,
        city=il,
        access_note=payload.access_note,
        primary_contact_id=payload.primary_contact_id,
        is_primary=payload.is_primary,
        sla_takvim_turu=payload.sla_takvim_turu,
        created_by=user.id,
    )
    db.add(adres)
    await db.flush()
    await audit.log(
        db,
        "addresses",
        "lokasyon.olustur",
        entity_id=adres.id,
        new_value={
            "hesap": hesap.id,
            "tur": adres.kind,
            "tesis_adi": adres.site_name,
            "adres": adres.line,
            "il": adres.city,
            "sla_takvim_turu": adres.sla_takvim_turu,
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return await _cikti(db, adres, irtibatlarla=True)


@router.patch("/lokasyonlar/{lokasyon_id}", response_model=LokasyonOut)
async def guncelle(
    lokasyon_id: int, payload: LokasyonPatch, request: Request, db: DbDep, user: Yazici
) -> LokasyonOut:
    adres = await _lokasyon(db, user, lokasyon_id)
    if payload.version != adres.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    if payload.hesap_id is not None and payload.hesap_id != adres.account_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Lokasyonun hesabı değiştirilemez; taşıma yalnız birleştirmeyle yapılır.",
        )

    veri: dict[str, Any] = payload.model_dump(exclude_unset=True, exclude={"version", "hesap_id"})
    if "city" in veri:
        veri["city"] = _il(veri["city"])
    if "is_primary" in veri and veri["is_primary"] is None:
        veri.pop("is_primary")
    if "primary_contact_id" in veri:
        await _birincil_irtibat_dogrula(db, adres.account_id, veri["primary_contact_id"])

    site_name = veri.get("site_name", adres.site_name)
    _tesis_kurali(adres.kind, site_name, veri.get("line", adres.line), veri.get("city", adres.city))
    if adres.kind == "TESIS" and adres.is_active and "site_name" in veri:
        await _tesis_cakisma_kontrolu(db, adres.account_id, site_name, adres.id)

    for alan, deger in veri.items():
        setattr(adres, alan, deger)
    adres.updated_by = user.id
    await audit.log_change(
        db,
        adres,
        "lokasyon.guncelle",
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    await db.refresh(adres)
    return await _cikti(db, adres, irtibatlarla=True)


async def _aktiflik(lokasyon_id: int, aktif: bool, request: Request, db, user: User) -> LokasyonOut:
    adres = await _lokasyon(db, user, lokasyon_id)
    if adres.is_active == aktif:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Lokasyon zaten aktif." if aktif else "Lokasyon zaten pasif.",
        )
    if aktif and adres.kind == "TESIS":
        # Pasifken aynı adla yeni tesis açılmış olabilir; ikisi birden aktif olamaz.
        await _tesis_cakisma_kontrolu(db, adres.account_id, adres.site_name, adres.id)
    adres.is_active = aktif
    adres.updated_by = user.id
    await audit.log(
        db,
        "addresses",
        "lokasyon.aktif" if aktif else "lokasyon.pasif",
        entity_id=adres.id,
        new_value={"hesap": adres.account_id, "aktif": aktif},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(adres)
    return await _cikti(db, adres, irtibatlarla=True)


@router.post("/lokasyonlar/{lokasyon_id}/pasif", response_model=LokasyonOut)
async def pasiflestir(lokasyon_id: int, request: Request, db: DbDep, user: Yazici) -> LokasyonOut:
    """Lokasyonu pasifler: yeni kayıtta seçilemez, bağlı eski kayıtlar bozulmaz."""
    return await _aktiflik(lokasyon_id, False, request, db, user)


@router.post("/lokasyonlar/{lokasyon_id}/aktif", response_model=LokasyonOut)
async def aktiflestir(lokasyon_id: int, request: Request, db: DbDep, user: Yazici) -> LokasyonOut:
    return await _aktiflik(lokasyon_id, True, request, db, user)


@router.post("/lokasyonlar/{lokasyon_id}/dogrula", response_model=LokasyonOut)
async def dogrula(
    lokasyon_id: int, request: Request, db: DbDep, clock: ClockDep, user: Dogrulayici
) -> LokasyonOut:
    """Hızlı eklenen tesisi doğrular (`hesap.birlestir`, E14 K7)."""
    adres = await _lokasyon(db, user, lokasyon_id)
    if adres.is_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Lokasyon zaten doğrulanmış.")
    adres.is_verified = True
    adres.updated_by = user.id
    await audit.log(
        db,
        "addresses",
        "lokasyon.dogrula",
        entity_id=adres.id,
        new_value={"hesap": adres.account_id, "dogrulama_ani": clock.now().isoformat()},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(adres)
    return await _cikti(db, adres, irtibatlarla=True)


# --- Lokasyon irtibatı -------------------------------------------------------------


def _telefon(ham: str | None) -> str | None:
    if not ham:
        return None
    try:
        return normalize_msisdn(ham)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post(
    "/lokasyonlar/{lokasyon_id}/kisiler",
    response_model=IrtibatOut,
    status_code=status.HTTP_201_CREATED,
)
async def irtibat_ekle(
    lokasyon_id: int, payload: IrtibatIn, request: Request, db: DbDep, user: Yazici
) -> IrtibatOut:
    """Lokasyon irtibatı: `contacts` satırı, `address_id` dolu (E14 §3.3)."""
    adres = await _lokasyon(db, user, lokasyon_id)
    kisi = Contact(
        account_id=adres.account_id,
        address_id=adres.id,
        full_name=payload.full_name.strip(),
        title=payload.title,
        phone=_telefon(payload.phone),
        email=payload.email,
        notes=payload.notes,
    )
    db.add(kisi)
    await db.flush()
    if payload.lokasyon_birincil:
        adres.primary_contact_id = kisi.id
        adres.updated_by = user.id
    await audit.log(
        db,
        "contacts",
        "olustur",
        entity_id=kisi.id,
        new_value={"hesap": adres.account_id, "lokasyon": adres.id, "ad": kisi.full_name},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return _irtibat_cikti(kisi, adres.primary_contact_id)


@router.patch("/lokasyonlar/kisiler/{kisi_id}", response_model=IrtibatOut)
async def irtibat_guncelle(
    kisi_id: int, payload: IrtibatIn, request: Request, db: DbDep, user: Yazici
) -> IrtibatOut:
    """Lokasyon irtibatını düzenler. Hesap geneli kişi (`address_id` boş) bu
    uçtan değil, Hesaplar ekranından (`hesap.yaz`) düzenlenir → 404."""
    kisi = await db.get(Contact, kisi_id)
    if kisi is None or kisi.address_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lokasyon irtibatı bulunamadı")
    adres = await _lokasyon(db, user, kisi.address_id)

    eski = _irtibat_izi(kisi)
    kisi.full_name = payload.full_name.strip()
    kisi.title = payload.title
    kisi.phone = _telefon(payload.phone)
    kisi.email = payload.email
    kisi.notes = payload.notes
    if payload.lokasyon_birincil:
        adres.primary_contact_id = kisi.id
    elif adres.primary_contact_id == kisi.id:
        adres.primary_contact_id = None
    yeni = _irtibat_izi(kisi)
    degisen = sorted(k for k in yeni if yeni[k] != eski[k])
    if degisen:
        await audit.log(
            db,
            "contacts",
            "guncelle",
            entity_id=kisi.id,
            old_value={"hesap": kisi.account_id, **{k: eski[k] for k in degisen}},
            new_value={"hesap": kisi.account_id, **{k: yeni[k] for k in degisen}},
            user_id=user.id,
            ip=client_ip(request),
            is_personal_data=True,
        )
    await db.commit()
    return _irtibat_cikti(kisi, adres.primary_contact_id)


def _irtibat_izi(kisi: Contact) -> dict[str, Any]:
    """Denetime yazılan irtibat görüntüsü — telefon MASKELİ (son 3 hane).

    Değişikliğin olduğu, kimin ve ne zaman yaptığı izlenebilir kalır; tam
    numara denetim ekranından okunamaz (E14-03 kabul 1).
    """
    return {
        "ad": kisi.full_name,
        "gorev": kisi.title,
        "telefon": kvkk.maskele(kisi.phone),
        "eposta": kisi.email,
    }
