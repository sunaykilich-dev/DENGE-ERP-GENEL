"""Teknik servisin müşteri/lokasyon ana veri uçları (TS-014, TS-015).

Servis personeli müşteriyi canlı Hesaplar ekranından değil buradan seçer:

- **Hafif arama** (`servis.gor`): yalnız ad + il + doğrulama rozeti. VKN,
  IBAN, telefon, e-posta ve irtibat DÖNMEZ — teknisyende `hesap.gor` yok
  (KD-09) ve olmamalı; müşteri bilgisi ona iş detayında gömülü gelir.
- **Hızlı ekleme** (`servis.yaz` + `hesap.kart_yaz`|`hesap.yaz`): yalnız ad +
  il (+ tesis); kayıt doğrulanmamış doğar, mali alanlar hiç açılmaz (KD-07).
  G10.2 (KARARLAR 2026-10-28): müşteri KARTINI yalnız Müşteri İlişkileri /
  satış destek / muhasebe / yöneticiler açar; eskiden kapı `lokasyon.yaz`
  idi ve bütün TS saha/operasyon rollerinde vardı. TS operasyon müşteriyi
  listeden seçer, yoksa kart talebi bırakır.
- **Servis tarafı müşteri düzenleme** (`hesap.kart_yaz`|`hesap.yaz`): servis
  rollerinde `hesap.yaz` yok; unvan/il/telefon/e-posta/cari kodu düzeltmesi buradan,
  mobilite rolü taşıyan hesapta 409 (montaj noktası künyesi hak edişindir,
  E14-D01).
- **Takma ad** (`hesap.birlestir`): eski yazımların tek hedefe bağlanması.
- **Saha önerisi**: plan/servis formunun tesis ön dolumu (E14-16).

Uç başına izin `require_permission` ile (hepsi gerekli); "biri yeterli"
kuralı gereken tek uçta gövdede `_herhangi` ile kontrol edilir.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
)
from app.models import AccountAlias, User
from app.services import audit, kvkk
from app.services.teknik_servis import ana_veri
from app.services.teknik_servis.ana_veri import AnaVeriHatasi

router = APIRouter(prefix="/api/teknik-servis/ana-veri", tags=["teknik-servis-ana-veri"])

Arayici = Annotated[User, Depends(require_permission("servis.gor"))]
HizliEkleyici = Annotated[User, Depends(require_permission("servis.yaz"))]
# Müşteri kartı açma/düzeltme (G10.2): TS'ye özel `hesap.kart_yaz` ya da
# mobilite Hesaplar ekranının `hesap.yaz`'ı — biri yeter.
KartYazici = Annotated[User, Depends(require_any_permission("hesap.kart_yaz", "hesap.yaz"))]
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
    payload: HizliMusteriIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: HizliEkleyici,
    _kart: KartYazici,
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
    # Faz A (TS-200, M5.1): müşteri sözleşmesinin SLA takvimi; null = politikanın.
    sla_takvim_turu: Literal["7_24", "MESAI"] | None = None
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
    sla_takvim_turu: str | None = None
    is_verified: bool
    version: int

    model_config = {"from_attributes": True}


# Mobilite hesabında yalnız bu alan servis tarafından yazılabilir (künye değil).
_SERVIS_SOZLESME_ALANLARI = frozenset({"sla_takvim_turu"})


@router.patch("/musteriler/{hesap_id}", response_model=MusteriOut)
async def musteri_guncelle(
    hesap_id: int, payload: MusteriPatch, request: Request, db: DbDep, user: KartYazici
) -> MusteriOut:
    """Servis personelinin müşteri düzeltmesi (E14-D01 madde 3).

    Yalnız `title, region, phone, email, dis_referans`. VKN/IBAN/rol/bayi bu
    uçta YOK. Hesap mobilite rolü (bayi/montaj noktası/tedarikçi) taşıyorsa
    409: montaj noktasının unvanı ve telefonu hak ediş dökümünün künyesidir,
    Hesaplar ekranından (`hesap.yaz`) düzenlenir.

    `sla_takvim_turu` (Faz A, TS-200): müşteri sözleşmesinin SLA takvimi
    (`7_24` / `MESAI` / null = politikanın). Künye değil, servis sözleşmesi
    alanıdır; bu yüzden yalnız bu alanı değiştiren istek mobilite rolü taşıyan
    MÜŞTERİDE de kabul edilir (ör. kendi montajını yapan filo). Açık işlerin
    hedefi değişmez (takvim açılışta işe dondurulur).
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
    veri: dict[str, Any] = payload.model_dump(exclude_unset=True, exclude={"version"})
    if set(veri) - _SERVIS_SOZLESME_ALANLARI and any(
        getattr(hesap, r) for r in ana_veri.MOBILITE_ROLLERI
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu hesap mobilite hesabı (bayi / montaj noktası / tedarikçi); "
            "Hesaplar ekranından düzenlenir.",
        )
    if not hesap.is_musteri:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hesap müşteri değil.")

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
    if not oneri:
        return {}
    # TS-034: lokasyonun bütün irtibatları (birincil önce) — form listeden seçer.
    from sqlalchemy import select

    from app.models import Address, Contact

    adres = await db.get(Address, lokasyon_id)
    kisiler = (
        await db.scalars(
            select(Contact)
            .where(Contact.address_id == lokasyon_id, Contact.account_id == adres.account_id)
            .order_by(Contact.full_name, Contact.id)
        )
    ).all()
    birincil = (oneri["irtibat"] or {}).get("id")
    oneri["irtibatlar"] = sorted(
        ({"id": k.id, "ad": k.full_name, "unvan": k.title, "telefon": k.phone} for k in kisiler),
        key=lambda k: k["id"] != birincil,
    )
    if not user.has("servis.yaz"):
        for kisi in [oneri["irtibat"], *oneri["irtibatlar"]]:
            if kisi:
                kisi["telefon"] = kvkk.maskele(kisi["telefon"])
    return oneri


# --- Serbest metin eşleştirme (TS-171, E14-09 Faz 1) ---------------------------------
#
# Aday listesi yalnız OKUR (kabul 1); karar `musteri_eslestirme` içe aktarma
# profiliyle verilir. İkisi de `hesap.birlestir` ister (bağ kurmak birleştirme
# yetkisidir); izinsiz kullanıcı 403.


@router.get("/eslestirme/ozet")
async def eslestirme_ozeti(db: DbDep, user: Birlestirici) -> dict[str, dict[str, int]]:
    """Kaynak başına eşleşmemiş / hesapsız / müşterisiz / belirsiz sayıları.

    Sayılar indirilen aday listesinin satırlarıyla AYNI listeden sayılır.
    """
    from app.services.teknik_servis import veri_kalitesi

    return await veri_kalitesi.eslestirme_ozeti(db, user)


@router.get("/eslestirme/adaylar.xlsx")
async def eslestirme_adaylari_xlsx(
    db: DbDep,
    user: Birlestirici,
    kaynak: Annotated[
        str, Query(pattern="^(sozlesme|ekipman|servis_isi|ekipman_diger)$")
    ] = "sozlesme",
) -> Response:
    """Eşleşmemiş kayıtların aday Excel'i (`musteri_eslestirme` profil şablonu).

    Müşterisi ve lokasyonu boş kayıtlar ayrı sayfadadır (kabul 4). Hiçbir
    şey yazmaz; ham metin kişisel veri taşımaz (irtibat adı yok).

    Faz 2 kaynakları (`servis_isi`, `ekipman_diger`; TS-208) birim kapsamı
    olmayan göç listesidir: yalnız `sistem.goc` sahibine açılır (aksi 403).
    """
    from app.services import export
    from app.services.imports import musteri_eslestirme
    from app.services.teknik_servis import veri_kalitesi

    if kaynak in musteri_eslestirme.FAZ2_KAYNAKLARI:
        if not user.has("sistem.goc"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Faz 2 aday listesi için yetkiniz yok (sistem.goc)"
            )
        satirlar = await musteri_eslestirme.faz2_adaylari(db, kaynak)
    else:
        satirlar = await veri_kalitesi.eslestirme_adaylari(db, user, kaynak)
    adaylar = [veri_kalitesi.aday_satiri(r) for r in satirlar if not r["musterisiz"]]
    bos = [veri_kalitesi.aday_satiri(r) for r in satirlar if r["musterisiz"]]
    icerik = await export.sayfalari_xlsx_async(
        [
            export.Sayfa("Adaylar", list(veri_kalitesi.ADAY_BASLIKLARI), adaylar),
            export.Sayfa("Musterisi Bos", list(veri_kalitesi.ADAY_BASLIKLARI), bos),
        ]
    )
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="eslestirme-{kaynak}.xlsx"'},
    )


# --- Müşteri kartı servis sekmesi ve kapsam bilgisi (TS-192, E14-07/E14-17) -----------

KartOkuyucu = Annotated[User, Depends(require_permission("hesap.gor", "servis.gor"))]


@router.get("/musteriler/{hesap_id}/servis-karti")
async def servis_karti(
    hesap_id: int, db: DbDep, clock: ClockDep, user: KartOkuyucu
) -> dict[str, Any]:
    """Hesap kartının Lokasyonlar/Servis sekmeleri (canlı `/kart` DEĞİŞMEZ).

    Açık iş sayısı = `/isler?musteri_id=<id>&durum_grubu=ACIK` `X-Toplam-Kayit`.
    Tutar alanı yalnız `maliyet.gor` sahibinde anahtar olarak bulunur.
    """
    try:
        hesap = await ana_veri.kapsamli_hesap(db, user, hesap_id)
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    return await ana_veri.servis_karti(db, user, hesap, clock)


@router.get("/kapsam-bilgisi")
async def kapsam_bilgisi(
    db: DbDep,
    clock: ClockDep,
    user: Arayici,
    hesap_id: int | None = None,
    lokasyon_id: int | None = None,
    ekipman_id: int | None = None,
) -> dict[str, Any]:
    """Servis işi formunun kapsam kutusu (E14-17): aktif sözleşmeler, garanti,
    son işler, kapsam durumu. **Tutar YOK** (maliyet.gor olsa bile).
    Kapsam dışı hesap/lokasyon/ekipman 404."""
    try:
        if hesap_id is not None:
            await ana_veri.kapsamli_hesap(db, user, hesap_id)
        if lokasyon_id is not None:
            adres = await ana_veri.kapsamli_lokasyon(db, user, lokasyon_id)
            if hesap_id is not None and adres.account_id != hesap_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lokasyon bu müşteriye ait değil")
    except AnaVeriHatasi as exc:
        raise _hata(exc) from exc
    if ekipman_id is not None:
        from app.services.teknik_servis import ekipman as ekipman_svc

        try:
            await ekipman_svc.kapsamli_ekipman(db, user, ekipman_id)
        except ekipman_svc.EkipmanBulunamadi as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ekipman bulunamadı") from exc
    return await ana_veri.kapsam_bilgisi(
        db,
        customer_id=hesap_id,
        address_id=lokasyon_id,
        equipment_id=ekipman_id,
        clock=clock,
        user=user,
    )


# --- Hesap / lokasyon birleştirme (TS-192, E14-12) -----------------------------------


class BirlestirmeIn(BaseModel):
    tur: str = Field(pattern="^(HESAP|LOKASYON)$")
    kaynak_id: int
    hedef_id: int

    model_config = {
        "json_schema_extra": {"examples": [{"tur": "HESAP", "kaynak_id": 2, "hedef_id": 1}]}
    }


class BirlestirmeUygulaIn(BirlestirmeIn):
    gerekce: str = Field(min_length=1, max_length=1000)
    # Önizlemede görülen `tasinacak` sayıları; güncel önizlemeyle aynı olmalı.
    beklenen: dict[str, int]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tur": "HESAP",
                    "kaynak_id": 2,
                    "hedef_id": 1,
                    "gerekce": "Aynı firma iki kayıtta",
                    "beklenen": {},
                }
            ]
        }
    }


def _birlestirme_hatasi(exc) -> HTTPException:
    if exc.veri:
        return HTTPException(exc.kod, {"mesaj": exc.mesaj, **exc.veri})
    return HTTPException(exc.kod, exc.mesaj)


@router.post("/birlestirme/onizle")
async def birlestirme_onizle(
    payload: BirlestirmeIn, db: DbDep, user: Birlestirici
) -> dict[str, Any]:
    """Birleştirme önizlemesi — DB'ye YAZMAZ. Engeller (hak ediş referansı,
    hedefte aynı adlı tesis) ve taşınacak satır sayıları döner."""
    from app.services import hesap_birlestir

    try:
        return await hesap_birlestir.onizle(
            db, payload.tur, payload.kaynak_id, payload.hedef_id, user=user
        )
    except hesap_birlestir.BirlestirmeHatasi as exc:
        raise _birlestirme_hatasi(exc) from exc


@router.post("/birlestirme/uygula", status_code=201)
async def birlestirme_uygula(
    payload: BirlestirmeUygulaIn, request: Request, db: DbDep, clock: ClockDep, user: Birlestirici
) -> dict[str, Any]:
    """Tek transaction'da birleştirir; `beklenen` güncel önizlemeyle uyuşmazsa
    409 "veri değişti, yeniden önizleyin". Hak ediş referanslı hesap 409."""
    from app.services import hesap_birlestir

    try:
        kayit = await hesap_birlestir.uygula(
            db,
            payload.tur,
            payload.kaynak_id,
            payload.hedef_id,
            gerekce=payload.gerekce,
            beklenen=payload.beklenen,
            user=user,
            clock=clock,
        )
    except hesap_birlestir.BirlestirmeHatasi as exc:
        await db.rollback()
        raise _birlestirme_hatasi(exc) from exc
    await audit.log(
        db,
        "accounts" if payload.tur == "HESAP" else "addresses",
        "hesap.birlestir" if payload.tur == "HESAP" else "lokasyon.birlestir",
        entity_id=payload.kaynak_id,
        new_value={
            "hedef": payload.hedef_id,
            "gerekce": payload.gerekce,
            "tasinan": kayit.tasinan,
            "kayit": kayit.id,
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(kayit)
    return hesap_birlestir.kayit_satiri(kayit)


@router.get("/birlestirmeler")
async def birlestirmeler(
    db: DbDep,
    user: Birlestirici,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Birleştirme kayıtları (salt okunur; `account_merges`)."""
    from app.api.deps import sayfala
    from app.models import AccountMerge
    from app.services import hesap_birlestir

    stmt = select(AccountMerge).order_by(AccountMerge.id.desc())
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [hesap_birlestir.kayit_satiri(k) for (k,) in satirlar]


# --- Veri Kalitesi (TS-188, E12-16 / E14-18) -----------------------------------------
#
# Salt okuma. Kutu sayısı = liste toplamı (`X-Toplam-Kayit`) = Excel satırı.
# Kontrol başına ek izin gövdede sınanır (servis işleri `servis.gor`, hesap
# kontrolleri `hesap.gor`, sözleşme `bakim.gor`); kapsam her listede aynı.

KaliteOkuyucu = Annotated[User, Depends(require_permission("servis_rapor.gor"))]
KaliteAktarici = Annotated[
    User, Depends(require_permission("servis_rapor.gor", "servis_rapor.disaaktar"))
]


def _kalite_kontrolu(user: User, kod: str):
    from app.services.teknik_servis import rapor_kalite

    try:
        k = rapor_kalite.kontrol_getir(kod)
    except rapor_kalite.KaliteHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    eksik = [i for i in k.izinler if not user.has(i)]
    if eksik:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Bu işlem için yetkiniz yok ({', '.join(eksik)})"
        )
    return k


@router.get("/veri-kalitesi")
async def veri_kalitesi(db: DbDep, clock: ClockDep, user: KaliteOkuyucu) -> dict[str, Any]:
    """Kontrol sayıları (kullanıcının görebildikleri). Ekipman kontrolleri
    `ekipman.gor` ile gelir ve Ekipman Kütüğü listesine gider."""
    from app.services.teknik_servis import rapor_kalite

    kontroller = await rapor_kalite.ozet(db, user, clock)
    payda = await rapor_kalite.is_paydasi(db, user) if user.has("servis.gor") else None
    return {
        "gruplar": [{"kod": k, "ad": a} for k, a in rapor_kalite.GRUPLAR.items()],
        "kontroller": kontroller,
        "is_paydasi": payda,
    }


@router.get("/veri-kalitesi/liste")
async def veri_kalitesi_liste(
    db: DbDep,
    user: KaliteOkuyucu,
    response: Response,
    kontrol: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Kontrolün satırları (sayfalı); `X-Toplam-Kayit` = kutudaki sayı."""
    from app.services.teknik_servis import rapor_kalite

    k = _kalite_kontrolu(user, kontrol)
    toplam, satirlar = await rapor_kalite.listele(db, user, k.kod, limit=limit, offset=offset)
    response.headers["X-Toplam-Kayit"] = str(toplam)
    return satirlar


@router.get("/veri-kalitesi/liste.xlsx")
async def veri_kalitesi_xlsx(
    request: Request,
    db: DbDep,
    user: KaliteAktarici,
    kontrol: str = Query(min_length=1, max_length=40),
) -> Response:
    """Kontrol listesinin Excel'i (aynı satırlar); dışa aktarım denetime yazılır."""
    from app.services import export
    from app.services.teknik_servis import rapor_kalite

    k = _kalite_kontrolu(user, kontrol)
    toplam, satirlar = await rapor_kalite.listele(db, user, k.kod)
    if toplam > 20_000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{toplam} satır var; Excel en çok 20000 satır alır."
        )
    sutunlar = [export.Sutun(b, t) for b, _, t in k.sutunlar]
    tablo = [[r.get(a) for _, a, _ in k.sutunlar] for r in satirlar]
    icerik = await export.sayfalari_xlsx_async([export.Sayfa(k.baslik[:31], sutunlar, tablo)])
    await audit.log(
        db,
        "veri_kalitesi",
        "ana_veri.disaaktar",
        new_value={"kontrol": k.kod, "satir": len(tablo)},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=k.grup == "ana_veri",
    )
    await db.commit()
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="veri-kalitesi-{k.kod}.xlsx"'},
    )
