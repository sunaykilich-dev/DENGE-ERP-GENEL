"""Teknik servisin müşteri/lokasyon ana veri uçları (TS-014, TS-015).

Servis personeli müşteriyi canlı Hesaplar ekranından değil buradan seçer:

- **Hafif arama** (`servis.gor`): yalnız ad + il + doğrulama rozeti. VKN,
  IBAN, telefon, e-posta ve irtibat DÖNMEZ — teknisyende `hesap.gor` yok
  (KD-09) ve olmamalı; müşteri bilgisi ona iş detayında gömülü gelir.
- **Hızlı ekleme** (`servis.yaz` + `lokasyon.yaz`): yalnız ad + il (+ tesis);
  kayıt doğrulanmamış doğar, mali alanlar hiç açılmaz (KD-07).
- **Servis tarafı müşteri düzenleme** (`lokasyon.yaz`): servis rollerinde
  `hesap.yaz` yok; unvan/il/telefon/e-posta/cari kodu düzeltmesi buradan,
  mobilite rolü taşıyan hesapta 409 (montaj noktası künyesi hak edişindir,
  E14-D01).
- **Takma ad** (`hesap.birlestir`): eski yazımların tek hedefe bağlanması.
- **Saha önerisi**: plan/servis formunun tesis ön dolumu (E14-16).

Uç başına izin `require_permission` ile (hepsi gerekli); "biri yeterli"
kuralı gereken tek uçta gövdede `_herhangi` ile kontrol edilir.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import AccountAlias, User
from app.services import audit, kvkk
from app.services.teknik_servis import ana_veri
from app.services.teknik_servis.ana_veri import AnaVeriHatasi

router = APIRouter(prefix="/api/teknik-servis/ana-veri", tags=["teknik-servis-ana-veri"])

Arayici = Annotated[User, Depends(require_permission("servis.gor"))]
HizliEkleyici = Annotated[User, Depends(require_permission("servis.yaz", "lokasyon.yaz"))]
LokasyonYazici = Annotated[User, Depends(require_permission("lokasyon.yaz"))]
Birlestirici = Annotated[User, Depends(require_permission("hesap.birlestir"))]


def _hata(exc: AnaVeriHatasi) -> HTTPException:
    if exc.veri:
        return HTTPException(exc.kod, {"mesaj": exc.mesaj, **exc.veri})
    return HTTPException(exc.kod, exc.mesaj)


def _herhangi(user: User, *kodlar: str) -> None:
    """İzinlerden en az biri yeterli (`api/attachments._izin` kalıbı)."""
    if not any(user.has(k) for k in kodlar):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Bu işlem için yetkiniz yok ({' / '.join(kodlar)})"
        )


# --- Hafif arama -----------------------------------------------------------------


class MusteriSatiri(BaseModel):
    id: int
    unvan: str
    il: str | None
    dogrulandi: bool
    eslesen: str


class LokasyonSatiri(BaseModel):
    id: int
    hesap_id: int
    tesis_adi: str | None
    ilce: str | None
    il: str | None
    aktif: bool
    dogrulandi: bool


@router.get("/musteri-ara", response_model=list[MusteriSatiri])
async def musteri_ara(
    db: DbDep,
    user: Arayici,
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=ana_veri.HAFIF_ARAMA_UST_SINIR, ge=1, le=50),
) -> list[MusteriSatiri]:
    """Seçicinin müşteri araması: unvan, takma ad, tesis adı, VKN başı."""
    return [MusteriSatiri(**s) for s in await ana_veri.musteri_ara(db, user, q, limit=limit)]


@router.get("/lokasyon-ara", response_model=list[LokasyonSatiri])
async def lokasyon_ara(
    db: DbDep,
    user: Arayici,
    hesap_id: int,
    q: str | None = Query(default=None, max_length=100),
    pasif_dahil: bool = False,
) -> list[LokasyonSatiri]:
    """Seçili müşterinin tesisleri. Kapsam dışı müşteri 404."""
    try:
        await ana_veri.kapsamli_hesap(db, user, hesap_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    return [
        LokasyonSatiri(**s)
        for s in await ana_veri.lokasyon_ara(db, hesap_id, q, pasif_dahil=pasif_dahil)
    ]


# --- Hızlı ekleme ----------------------------------------------------------------


class HizliMusteriIn(BaseModel):
    """Yalnız ad + il (+ tesis). `is_verified` gibi alanlar şemada YOK; gövdede
    gelse de Pydantic yok sayar — kayıt her durumda doğrulanmamış doğar."""

    unvan: str = Field(min_length=2, max_length=200)
    il: str = Field(min_length=2, max_length=60)
    tesis_adi: str | None = Field(default=None, max_length=200)
    onay_benzer: bool = False

    @field_validator("unvan", "il", mode="before")
    @classmethod
    def _kirp(cls, v: object) -> object:
        # Boşluk-only unvan 422 olmalı (M14-D01 özü): kırpma doğrulamadan ÖNCE.
        return v.strip() if isinstance(v, str) else v


class HizliMusteriOut(BaseModel):
    hesap: MusteriSatiri
    lokasyon: LokasyonSatiri | None


@router.post("/hizli-musteri", response_model=HizliMusteriOut, status_code=201)
async def hizli_musteri(
    payload: HizliMusteriIn, request: Request, db: DbDep, clock: ClockDep, user: HizliEkleyici
) -> HizliMusteriOut:
    """Servis ekranından müşteri (+ tesis) açar; benzer kayıt varsa 409 + adaylar."""
    try:
        hesap, tesis = await ana_veri.hizli_musteri(
            db,
            ana_veri.HizliMusteriGirdisi(
                unvan=payload.unvan,
                il=payload.il,
                tesis_adi=payload.tesis_adi,
                onay_benzer=payload.onay_benzer,
            ),
            user=user,
            clock=clock,
        )
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc

    await audit.log(
        db,
        "accounts",
        "hesap.hizli_olustur",
        entity_id=hesap.id,
        new_value={
            "title": hesap.title,
            "il": hesap.region,
            "tesis": tesis.id if tesis else None,
            "benzer_onaylandi": payload.onay_benzer,
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    if tesis is not None:
        await audit.log(
            db,
            "addresses",
            "lokasyon.olustur",
            entity_id=tesis.id,
            new_value={"hesap": hesap.id, "tur": "TESIS", "tesis_adi": tesis.site_name},
            user_id=user.id,
            ip=client_ip(request),
            is_personal_data=True,
        )
    await db.commit()
    return HizliMusteriOut(
        hesap=MusteriSatiri(**ana_veri.musteri_satiri(hesap, "unvan")),
        lokasyon=LokasyonSatiri(**ana_veri.lokasyon_satiri(tesis)) if tesis else None,
    )


# --- Servis tarafı müşteri düzenleme -----------------------------------------------


class MusteriPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    region: str | None = Field(default=None, max_length=60)
    phone: str | None = None
    email: str | None = Field(default=None, max_length=160)
    dis_referans: str | None = Field(default=None, max_length=40)
    version: int

    @field_validator("title", mode="before")
    @classmethod
    def _kirp(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def _tel(cls, v: str | None) -> str | None:
        from app.services.normalize import normalize_msisdn

        return normalize_msisdn(v) if v else None


class MusteriOut(BaseModel):
    id: int
    title: str
    region: str | None
    phone: str | None
    email: str | None
    dis_referans: str | None
    is_verified: bool
    version: int

    model_config = {"from_attributes": True}


@router.patch("/musteriler/{hesap_id}", response_model=MusteriOut)
async def musteri_guncelle(
    hesap_id: int, payload: MusteriPatch, request: Request, db: DbDep, user: LokasyonYazici
) -> MusteriOut:
    """Servis personelinin müşteri düzeltmesi (E14-D01 madde 3).

    Yalnız `title, region, phone, email, dis_referans`. VKN/IBAN/rol/bayi bu
    uçta YOK. Hesap mobilite rolü (bayi/montaj noktası/tedarikçi) taşıyorsa
    409: montaj noktasının unvanı ve telefonu hak ediş dökümünün künyesidir,
    Hesaplar ekranından (`hesap.yaz`) düzenlenir.
    """
    try:
        hesap = await ana_veri.kapsamli_hesap(db, user, hesap_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    if payload.version != hesap.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )
    if any(getattr(hesap, r) for r in ana_veri.MOBILITE_ROLLERI):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu hesap mobilite hesabı (bayi / montaj noktası / tedarikçi); "
            "Hesaplar ekranından düzenlenir.",
        )
    if not hesap.is_musteri:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hesap müşteri değil.")

    veri: dict[str, Any] = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "title" in veri and not veri["title"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unvan boş olamaz")
    if "region" in veri:
        try:
            veri["region"] = ana_veri.il_dogrula(veri["region"])
        except AnaVeriHatasi as exc:
            raise _hata(exc) from exc
    for alan, deger in veri.items():
        setattr(hesap, alan, deger)
    hesap.updated_by = user.id
    await audit.log_change(
        db,
        hesap,
        "servis.musteri.guncelle",
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    await db.refresh(hesap)
    return MusteriOut.model_validate(hesap)


# --- Takma adlar -------------------------------------------------------------------


class TakmaAdIn(BaseModel):
    hesap_id: int
    metin: str = Field(min_length=2, max_length=250)
    lokasyon_id: int | None = None
    kaynak_tablo: str | None = Field(default=None, max_length=40)


class TakmaAdOut(BaseModel):
    id: int
    hesap_id: int
    lokasyon_id: int | None
    metin: str
    anahtar: str
    kaynak: str
    kaynak_tablo: str | None
    created_at: datetime | None


@router.get("/takma-adlar", response_model=list[TakmaAdOut])
async def takma_adlar(hesap_id: int, db: DbDep, user: Birlestirici) -> list[TakmaAdOut]:
    try:
        await ana_veri.kapsamli_hesap(db, user, hesap_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    satirlar = (
        await db.scalars(
            select(AccountAlias)
            .where(AccountAlias.account_id == hesap_id)
            .order_by(AccountAlias.alias_text, AccountAlias.id)
        )
    ).all()
    return [TakmaAdOut(**ana_veri.takma_ad_satiri(t)) for t in satirlar]


@router.post("/takma-adlar", response_model=TakmaAdOut, status_code=201)
async def takma_ad_ekle(
    payload: TakmaAdIn, request: Request, db: DbDep, user: Birlestirici
) -> TakmaAdOut:
    """Elle takma ad. Yazım başka hedefe bağlıysa 409 + mevcut hedef."""
    try:
        await ana_veri.kapsamli_hesap(db, user, payload.hesap_id)
        takma = await ana_veri.takma_ad_ekle(
            db,
            account_id=payload.hesap_id,
            alias_text=payload.metin,
            address_id=payload.lokasyon_id,
            kaynak="ELLE",
            kaynak_tablo=payload.kaynak_tablo,
            user_id=user.id,
        )
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    await audit.log(
        db,
        "account_aliases",
        "takma_ad.ekle",
        entity_id=takma.id,
        new_value={
            "hesap": takma.account_id,
            "lokasyon": takma.address_id,
            "metin": takma.alias_text,
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    await db.refresh(takma)
    return TakmaAdOut(**ana_veri.takma_ad_satiri(takma))


@router.delete("/takma-adlar/{takma_ad_id}", status_code=status.HTTP_204_NO_CONTENT)
async def takma_ad_sil(takma_ad_id: int, request: Request, db: DbDep, user: Birlestirici) -> None:
    """Takma ad silinir (kayıt değiştirilmez, yalnız eklenir/silinir); denetime yazılır."""
    takma = await db.get(AccountAlias, takma_ad_id)
    if takma is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Takma ad bulunamadı")
    try:
        await ana_veri.kapsamli_hesap(db, user, takma.account_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    eski = {"hesap": takma.account_id, "lokasyon": takma.address_id, "metin": takma.alias_text}
    await db.delete(takma)
    await audit.log(
        db,
        "account_aliases",
        "takma_ad.sil",
        entity_id=takma_ad_id,
        old_value=eski,
        new_value={"hesap": eski["hesap"]},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()


# --- Saha önerisi ------------------------------------------------------------------


@router.get("/saha-onerisi")
async def saha_onerisi(lokasyon_id: int, db: DbDep, user: Arayici) -> dict[str, Any]:
    """Plan/servis formunun tesis ön dolumu (E14-16) — yalnız `addresses`'ten.

    Lokasyon kimliğiyle doğrudan okuma irtibat (kişisel veri) taşıdığı için
    `servis.gor`'a ek olarak lokasyonu zaten görebilen izin ister (`hesap.gor`
    ya da `lokasyon.yaz`); aksi halde `KENDI_ISLERI` teknisyeni kimlik
    tarayarak her tesisin irtibatını okuyabilirdi. İş üzerinden öneri (atanan
    teknisyen) işin kendi ucundadır (TS-047). Telefon `servis.yaz` olmayana
    maskeli döner.
    """
    _herhangi(user, "hesap.gor", "lokasyon.yaz")
    try:
        await ana_veri.kapsamli_lokasyon(db, user, lokasyon_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    oneri = await ana_veri.saha_onerisi_kaynak(db, lokasyon_id)
    if oneri and oneri["irtibat"] and not user.has("servis.yaz"):
        oneri["irtibat"]["telefon"] = kvkk.maskele(oneri["irtibat"]["telefon"])
    return oneri or {}
