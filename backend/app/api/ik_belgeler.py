"""İK "Bordro ve Belgeler" uçları (KARARLAR_2026-10-28 §11).

İK tarafı (`/api/ik/...`): kapı `bordro.yonet` VEYA `ik_belge.yonet`; gövdede
türün izni ayrıca denetlenir (BORDRO → `bordro.yonet`, diğerleri
`ik_belge.yonet`). Bordro izni olmayan, bordro gönderimini listede bile görmez
(varlığı sızmaz; tekil istek 404).

Personel tarafı (`/api/ik/belgelerim/...`): izin değil KİMLİK: oturumdaki
kişi yalnız kendi belgesini görür; başkasının belgesi 404. Rolü ne olursa olsun
herkes kendi bordrosunu görebilmeli (İş K. md. 37).
"""

import json
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from app.api.attachments import _dosya_adi_basligi
from app.api.deps import ClockDep, CurrentUser, DbDep, client_ip, require_any_permission
from app.models import IkBelge, IkBelgeOlayi, IkBelgeSablonu, IkGonderim, User
from app.models.ik_belge import BELGE_TURLERI, SABLON_TURLERI
from app.services import audit, kvkk
from app.services import ik_belge as svc
from app.services import storage as depo

router = APIRouter(prefix="/api/ik", tags=["ik-belgeler"])

IkYonetici = Annotated[User, Depends(require_any_permission(svc.IZIN_BORDRO, svc.IZIN_BELGE))]

PDF = "application/pdf"
MAKS_DOSYA = 500  # tek gönderimde en çok bu kadar kişi/dosya


def _hata(exc: svc.IkBelgeHatasi) -> HTTPException:
    return HTTPException(exc.durum, str(exc))


def _izin(user: User, kod: str) -> None:
    if not user.has(kod):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Bu işlem için yetkiniz yok ({kod})")


def _istek(request: Request, clock) -> svc.Istek:
    return svc.Istek(
        an=clock.now(),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


async def _pdf_oku(dosya: UploadFile) -> tuple[depo.Kayit, str]:
    """Yalnız PDF: imzalanan belgenin her cihazda aynı görünmesi ve özetinin
    değişmez bir dosyaya ait olması için (Word belgesi açıldığı yere göre
    farklı görünür)."""
    try:
        icerik = await depo.sinirli_oku(dosya)
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    ad = depo.temiz_ad(dosya.filename or "belge.pdf")
    if not icerik.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Yalnız PDF kabul edilir: {ad}")
    try:
        return depo.yaz(icerik, mime_type=PDF), ad
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _dosya_yaniti(storage_path: str, mime: str, ad: str) -> Response:
    try:
        yol = depo.yol(storage_path)
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(
        content=yol.read_bytes(),
        media_type=mime,
        headers={
            "Content-Disposition": f"inline; {_dosya_adi_basligi(ad)}",
            # Bordro kişisel veri: paylaşılan bilgisayarda önbellekten açılmasın.
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )


# --- Şemalar --------------------------------------------------------------------------


class AliciOut(BaseModel):
    id: int
    ad: str
    sicil_no: str | None
    birim: str | None
    eposta_var: bool


class EslestirIn(BaseModel):
    dosya_adlari: list[str] = Field(min_length=1, max_length=MAKS_DOSYA)


class EslesmeOut(BaseModel):
    dosya_adi: str
    user_id: int | None
    ad: str | None
    yontem: Literal["SICIL", "AD", "BELIRSIZ", "YOK"]


class SablonOut(BaseModel):
    id: int
    ad: str
    tur: str
    aciklama: str | None
    aktif: bool
    dosya_adi: str
    sha256: str
    version: int


class SablonPatch(BaseModel):
    ad: str | None = Field(default=None, min_length=2, max_length=150)
    aciklama: str | None = Field(default=None, max_length=2000)
    aktif: bool | None = None
    version: int


class GonderimIn(BaseModel):
    """Çok parçalı istekte `veri` alanı (JSON). BORDRO: `dosyalar[i]` ↔
    `alicilar[i]`. Diğer türler: tek dosya ya da `sablon_id`, herkese aynı."""

    tur: Literal["BORDRO", "FORM", "TALIMAT", "TAAHHUTNAME", "KVKK", "DIGER"]
    baslik: str = Field(min_length=3, max_length=200)
    donem: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    aciklama: str | None = Field(default=None, max_length=2000)
    son_tarih: date | None = None
    sablon_id: int | None = None
    alicilar: list[int] = Field(min_length=1, max_length=MAKS_DOSYA)
    bildir: bool = True


class GonderimOzet(BaseModel):
    id: int
    tur: str
    baslik: str
    donem: str | None
    son_tarih: date | None
    created_at: datetime
    gonderen: str | None
    toplam: int
    sayilar: dict[str, int]


class BelgeSatiri(BaseModel):
    id: int
    user_id: int
    ad: str
    sicil_no: str | None
    durum: str
    gonderildi_at: datetime
    goruldu_at: datetime | None
    yanit_at: datetime | None
    itiraz_gerekcesi: str | None
    hatirlatma_sayisi: int
    son_hatirlatma_at: datetime | None
    gecikti: bool


class GonderimDetay(GonderimOzet):
    aciklama: str | None
    belgeler: list[BelgeSatiri]


class GonderimSonucu(BaseModel):
    gonderim: GonderimOzet
    bildirilen: int


class HatirlatIn(BaseModel):
    belge_idleri: list[int] | None = Field(default=None, max_length=MAKS_DOSYA)


class HatirlatOut(BaseModel):
    hatirlatilan: int
    bildirilen: int


class GeriAlIn(BaseModel):
    gerekce: str = Field(min_length=5, max_length=500)


class OlayOut(BaseModel):
    id: int
    olay: str
    kisi: str | None
    at: datetime
    ip: str | None
    user_agent: str | None
    dogrulama: str | None
    belge_ozeti: str
    aciklama: str | None
    kayit_ozeti: str


class KanitOut(BaseModel):
    belge_id: int
    belge_ozeti: str
    zincir_gecerli: bool
    olaylar: list[OlayOut]


class BelgemOut(BaseModel):
    id: int
    tur: str
    tur_adi: str
    baslik: str
    donem: str | None
    aciklama: str | None
    son_tarih: date | None
    durum: str
    gonderildi_at: datetime
    goruldu_at: datetime | None
    yanit_at: datetime | None
    itiraz_gerekcesi: str | None
    dosya_adi: str
    belge_ozeti: str


class BelgelerimOzet(BaseModel):
    bekleyen: int


class DogrulamaIn(BaseModel):
    parola: str | None = Field(default=None, max_length=200)
    kod: str | None = Field(default=None, max_length=10)


class ItirazIn(DogrulamaIn):
    gerekce: str = Field(min_length=5, max_length=2000)


# --- Yardımcılar ------------------------------------------------------------------------


def _gorunur_turler(user: User) -> list[str]:
    return [t for t in BELGE_TURLERI if svc.yonetebilir_mi(user, t)]


async def _gonderim(db, gonderim_id: int, user: User) -> IkGonderim:
    g = await db.get(IkGonderim, gonderim_id)
    # Bordro izni olmayan bordro gönderiminin varlığını öğrenmez.
    if g is None or not svc.yonetebilir_mi(user, g.tur):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gönderim bulunamadı")
    return g


async def _ik_belgesi(db, belge_id: int, user: User) -> tuple[IkBelge, IkGonderim]:
    b = await db.get(IkBelge, belge_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belge bulunamadı")
    g = await _gonderim(db, b.gonderim_id, user)
    return b, g


async def _benim_belgem(db, belge_id: int, user: User) -> tuple[IkBelge, IkGonderim]:
    b = await db.get(IkBelge, belge_id)
    if b is None or b.user_id != user.id or b.durum == "GERI_ALINDI":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belge bulunamadı")
    return b, await db.get(IkGonderim, b.gonderim_id)


async def _ozetler(db, gonderimler: list[IkGonderim]) -> list[GonderimOzet]:
    sayilar = await svc.durum_sayilari(db, [g.id for g in gonderimler])
    gonderen_idleri = {g.created_by for g in gonderimler if g.created_by}
    adlar = {}
    if gonderen_idleri:
        adlar = dict(
            (
                await db.execute(
                    select(User.id, User.full_name).where(User.id.in_(gonderen_idleri))
                )
            ).all()
        )
    return [
        GonderimOzet(
            id=g.id,
            tur=g.tur,
            baslik=g.baslik,
            donem=g.donem,
            son_tarih=g.son_tarih,
            created_at=g.created_at,
            gonderen=adlar.get(g.created_by),
            toplam=sum(sayilar[g.id].values()),
            sayilar=sayilar[g.id],
        )
        for g in gonderimler
    ]


def _belgem(b: IkBelge, g: IkGonderim) -> BelgemOut:
    return BelgemOut(
        id=b.id,
        tur=g.tur,
        tur_adi=svc.TUR_ADLARI[g.tur],
        baslik=g.baslik,
        donem=g.donem,
        aciklama=g.aciklama,
        son_tarih=g.son_tarih,
        durum=b.durum,
        gonderildi_at=b.gonderildi_at,
        goruldu_at=b.goruldu_at,
        yanit_at=b.yanit_at,
        itiraz_gerekcesi=b.itiraz_gerekcesi,
        dosya_adi=b.dosya_adi,
        belge_ozeti=b.sha256,
    )


# --- İK: alıcılar, eşleştirme, şablonlar -------------------------------------------------


@router.get("/alicilar", response_model=list[AliciOut])
async def alicilar(db: DbDep, _: IkYonetici) -> list[AliciOut]:
    return [
        AliciOut(
            id=k.id,
            ad=k.full_name,
            sicil_no=k.sicil_no,
            birim=k.birincil_birim,
            eposta_var=bool(k.email),
        )
        for k in await svc.alici_adaylari(db)
    ]


@router.post("/eslestir", response_model=list[EslesmeOut])
async def eslestir(govde: EslestirIn, db: DbDep, user: IkYonetici) -> list[dict[str, Any]]:
    """Toplu bordro: dosya adlarından kişi önerisi (sicil no, sonra ad soyad)."""
    _izin(user, svc.IZIN_BORDRO)
    return svc.eslestir(govde.dosya_adlari, await svc.alici_adaylari(db))


def _sablon_out(s: IkBelgeSablonu) -> SablonOut:
    return SablonOut(
        id=s.id,
        ad=s.ad,
        tur=s.tur,
        aciklama=s.aciklama,
        aktif=s.aktif,
        dosya_adi=s.dosya_adi,
        sha256=s.sha256,
        version=s.version,
    )


@router.get("/sablonlar", response_model=list[SablonOut])
async def sablonlar(db: DbDep, user: IkYonetici, yalniz_aktif: bool = False) -> list[SablonOut]:
    _izin(user, svc.IZIN_BELGE)
    q = select(IkBelgeSablonu).order_by(IkBelgeSablonu.tur, IkBelgeSablonu.ad)
    if yalniz_aktif:
        q = q.where(IkBelgeSablonu.aktif.is_(True))
    return [_sablon_out(s) for s in (await db.scalars(q)).all()]


@router.post("/sablonlar", response_model=SablonOut, status_code=status.HTTP_201_CREATED)
async def sablon_ekle(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IkYonetici,
    ad: Annotated[str, Form(min_length=2, max_length=150)],
    tur: Annotated[str, Form()],
    dosya: Annotated[UploadFile, File()],
    aciklama: Annotated[str | None, Form(max_length=2000)] = None,
) -> SablonOut:
    _izin(user, svc.IZIN_BELGE)
    if tur not in SABLON_TURLERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Geçersiz şablon türü: {tur}")
    kayit, dosya_adi = await _pdf_oku(dosya)
    s = IkBelgeSablonu(
        ad=ad.strip(),
        tur=tur,
        aciklama=(aciklama or "").strip() or None,
        dosya_adi=dosya_adi,
        storage_path=kayit.storage_path,
        mime_type=kayit.mime_type,
        size_bytes=kayit.size_bytes,
        sha256=kayit.sha256,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(s)
    await db.flush()
    await audit.log(
        db,
        "ik_sablon",
        "ekle",
        entity_id=s.id,
        new_value={"tur": tur},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(s)
    return _sablon_out(s)


@router.patch("/sablonlar/{sablon_id}", response_model=SablonOut)
async def sablon_duzelt(
    sablon_id: int, govde: SablonPatch, request: Request, db: DbDep, user: IkYonetici
) -> SablonOut:
    """Dosya değişmez (gönderilmiş belgenin özeti ona bağlı); yeni dosya =
    yeni şablon. Pasif şablon listede seçilmez, geçmiş gönderimler kalır."""
    _izin(user, svc.IZIN_BELGE)
    s = await db.get(IkBelgeSablonu, sablon_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Şablon bulunamadı")
    if s.version != govde.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "Şablon başkası tarafından değiştirildi")
    if govde.ad is not None:
        s.ad = govde.ad.strip()
    if govde.aciklama is not None:
        s.aciklama = govde.aciklama.strip() or None
    if govde.aktif is not None:
        s.aktif = govde.aktif
    s.updated_by = user.id
    await audit.log_change(db, s, "ik_sablon.duzelt", user_id=user.id, ip=client_ip(request))
    await db.commit()
    await db.refresh(s)
    return _sablon_out(s)


@router.get("/sablonlar/{sablon_id}/dosya")
async def sablon_dosyasi(sablon_id: int, db: DbDep, user: IkYonetici) -> Response:
    _izin(user, svc.IZIN_BELGE)
    s = await db.get(IkBelgeSablonu, sablon_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Şablon bulunamadı")
    return _dosya_yaniti(s.storage_path, s.mime_type, s.dosya_adi)


# --- İK: gönderim ve takip ------------------------------------------------------------------


@router.post("/gonderimler", response_model=GonderimSonucu, status_code=status.HTTP_201_CREATED)
async def gonderim_olustur(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IkYonetici,
    veri: Annotated[str, Form()],
    dosyalar: Annotated[list[UploadFile] | None, File()] = None,
) -> GonderimSonucu:
    try:
        g_in = GonderimIn.model_validate(json.loads(veri))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, f"Geçersiz gönderim: {exc}") from exc
    _izin(user, svc.tur_izni(g_in.tur))
    dosyalar = dosyalar or []

    alicilar: list[svc.Alici] = []
    if g_in.tur == "BORDRO":
        if g_in.sablon_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bordro şablondan gönderilmez")
        if len(dosyalar) != len(g_in.alicilar):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Bordroda her kişiye bir PDF eşleşmeli (dosya sayısı = kişi sayısı)",
            )
        for uid, dosya in zip(g_in.alicilar, dosyalar, strict=True):
            kayit, ad = await _pdf_oku(dosya)
            alicilar.append(svc.Alici(user_id=uid, dosya=kayit, dosya_adi=ad))
    else:
        if g_in.sablon_id is not None:
            if dosyalar:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Şablon ya da dosya: ikisi birden olmaz"
                )
            s = await db.get(IkBelgeSablonu, g_in.sablon_id)
            if s is None or not s.aktif:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Şablon bulunamadı")
            kayit = depo.Kayit(
                storage_path=s.storage_path,
                sha256=s.sha256,
                size_bytes=s.size_bytes,
                mime_type=s.mime_type,
            )
            ad = s.dosya_adi
        else:
            if len(dosyalar) != 1:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Tek bir PDF yükleyin ya da şablon seçin"
                )
            kayit, ad = await _pdf_oku(dosyalar[0])
        alicilar = [svc.Alici(user_id=uid, dosya=kayit, dosya_adi=ad) for uid in g_in.alicilar]

    try:
        g = await svc.gonder(
            db,
            tur=g_in.tur,
            baslik=g_in.baslik,
            donem=g_in.donem,
            aciklama=g_in.aciklama,
            son_tarih=g_in.son_tarih,
            sablon_id=g_in.sablon_id,
            alicilar=alicilar,
            gonderen=user,
            istek=_istek(request, clock),
        )
    except svc.IkBelgeHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    bildirilen = 0
    if g_in.bildir:
        kisiler = (await db.scalars(select(User).where(User.id.in_(g_in.alicilar)))).all()
        bildirilen = await svc.bildir(db, kisiler, g=g, hatirlatma=False)
    await db.refresh(g)
    return GonderimSonucu(gonderim=(await _ozetler(db, [g]))[0], bildirilen=bildirilen)


@router.get("/gonderimler", response_model=list[GonderimOzet])
async def gonderimler(
    db: DbDep,
    user: IkYonetici,
    tur: str | None = None,
    donem: str | None = None,
    limit: int = 200,
) -> list[GonderimOzet]:
    turler = _gorunur_turler(user)
    if tur is not None:
        if tur not in turler:
            return []
        turler = [tur]
    q = select(IkGonderim).where(IkGonderim.tur.in_(turler))
    if donem:
        q = q.where(IkGonderim.donem == donem)
    q = q.order_by(IkGonderim.id.desc()).limit(max(1, min(limit, 1000)))
    return await _ozetler(db, list((await db.scalars(q)).all()))


@router.get("/gonderimler/{gonderim_id}", response_model=GonderimDetay)
async def gonderim_detay(
    gonderim_id: int, db: DbDep, clock: ClockDep, user: IkYonetici
) -> GonderimDetay:
    g = await _gonderim(db, gonderim_id, user)
    satirlar = (
        await db.execute(
            select(IkBelge, User.full_name, User.sicil_no)
            .join(User, User.id == IkBelge.user_id)
            .where(IkBelge.gonderim_id == g.id)
            .order_by(User.full_name)
        )
    ).all()
    bugun = clock.now().date()
    ozet = (await _ozetler(db, [g]))[0]
    return GonderimDetay(
        **ozet.model_dump(),
        aciklama=g.aciklama,
        belgeler=[
            BelgeSatiri(
                id=b.id,
                user_id=b.user_id,
                ad=ad,
                sicil_no=sicil,
                durum=b.durum,
                gonderildi_at=b.gonderildi_at,
                goruldu_at=b.goruldu_at,
                yanit_at=b.yanit_at,
                itiraz_gerekcesi=b.itiraz_gerekcesi,
                hatirlatma_sayisi=b.hatirlatma_sayisi,
                son_hatirlatma_at=b.son_hatirlatma_at,
                gecikti=bool(
                    g.son_tarih and bugun > g.son_tarih and b.durum in svc.BEKLEYEN_DURUMLAR
                ),
            )
            for b, ad, sicil in satirlar
        ],
    )


@router.post("/gonderimler/{gonderim_id}/hatirlat", response_model=HatirlatOut)
async def hatirlat(
    gonderim_id: int,
    govde: HatirlatIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: IkYonetici,
) -> HatirlatOut:
    g = await _gonderim(db, gonderim_id, user)
    belgeler = await svc.hatirlat(
        db, g, belge_idleri=govde.belge_idleri, yapan=user, istek=_istek(request, clock)
    )
    await db.commit()
    kisiler = []
    if belgeler:
        kisiler = (
            await db.scalars(select(User).where(User.id.in_([b.user_id for b in belgeler])))
        ).all()
    bildirilen = await svc.bildir(db, kisiler, g=g, hatirlatma=True)
    return HatirlatOut(hatirlatilan=len(belgeler), bildirilen=bildirilen)


@router.post("/belgeler/{belge_id}/geri-al", status_code=status.HTTP_204_NO_CONTENT)
async def geri_al(
    belge_id: int, govde: GeriAlIn, request: Request, db: DbDep, clock: ClockDep, user: IkYonetici
) -> None:
    b, _ = await _ik_belgesi(db, belge_id, user)
    try:
        await svc.geri_al(db, b, gerekce=govde.gerekce, yapan=user, istek=_istek(request, clock))
    except svc.IkBelgeHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()


@router.get("/belgeler/{belge_id}/dosya")
async def ik_belge_dosyasi(
    belge_id: int, request: Request, db: DbDep, user: IkYonetici
) -> Response:
    b, g = await _ik_belgesi(db, belge_id, user)
    if g.tur == "BORDRO":
        # KVKK: bordroyu kimin açtığı ayrıca loglanır (kişinin kendisi hariç).
        await kvkk.erisim_kaydet(
            db,
            entity="ik_belge",
            entity_id=b.id,
            amac="bordro_goruntuleme",
            user_id=user.id,
            ip=client_ip(request),
        )
        await db.commit()
    return _dosya_yaniti(b.storage_path, b.mime_type, b.dosya_adi)


@router.get("/belgeler/{belge_id}/kanit", response_model=KanitOut)
async def kanit(belge_id: int, db: DbDep, user: IkYonetici) -> KanitOut:
    b, _ = await _ik_belgesi(db, belge_id, user)
    satirlar = (
        await db.execute(
            select(IkBelgeOlayi, User.full_name)
            .outerjoin(User, User.id == IkBelgeOlayi.user_id)
            .where(IkBelgeOlayi.belge_id == b.id)
            .order_by(IkBelgeOlayi.id)
        )
    ).all()
    olaylar = [o for o, _ in satirlar]
    return KanitOut(
        belge_id=b.id,
        belge_ozeti=b.sha256,
        zincir_gecerli=svc.zincir_dogrula(olaylar, b.sha256),
        olaylar=[
            OlayOut(
                id=o.id,
                olay=o.olay,
                kisi=ad,
                at=o.at,
                ip=o.ip,
                user_agent=o.user_agent,
                dogrulama=o.dogrulama,
                belge_ozeti=o.belge_ozeti,
                aciklama=o.aciklama,
                kayit_ozeti=o.kayit_ozeti,
            )
            for o, ad in satirlar
        ],
    )


# --- Personel: Belgelerim -------------------------------------------------------------------


@router.get("/belgelerim", response_model=list[BelgemOut])
async def belgelerim(db: DbDep, user: CurrentUser) -> list[BelgemOut]:
    satirlar = (
        await db.execute(
            select(IkBelge, IkGonderim)
            .join(IkGonderim, IkGonderim.id == IkBelge.gonderim_id)
            .where(IkBelge.user_id == user.id, IkBelge.durum != "GERI_ALINDI")
            .order_by(IkBelge.gonderildi_at.desc(), IkBelge.id.desc())
        )
    ).all()
    return [_belgem(b, g) for b, g in satirlar]


@router.get("/belgelerim/ozet", response_model=BelgelerimOzet)
async def belgelerim_ozet(db: DbDep, user: CurrentUser) -> BelgelerimOzet:
    adet = await db.scalar(
        select(func.count())
        .select_from(IkBelge)
        .where(IkBelge.user_id == user.id, IkBelge.durum.in_(svc.BEKLEYEN_DURUMLAR))
    )
    return BelgelerimOzet(bekleyen=adet or 0)


@router.get("/belgelerim/{belge_id}/dosya")
async def belgem_dosyasi(
    belge_id: int, request: Request, db: DbDep, clock: ClockDep, user: CurrentUser
) -> Response:
    """Belgeyi açmak "görüldü" kaydıdır (ilk açılışta, IP ve tarayıcıyla)."""
    b, _ = await _benim_belgem(db, belge_id, user)
    await svc.goruldu(db, b, user, _istek(request, clock))
    await db.commit()
    return _dosya_yaniti(b.storage_path, b.mime_type, b.dosya_adi)


async def _yanitla(
    belge_id: int,
    request: Request,
    db,
    clock,
    user: User,
    *,
    onay: bool,
    govde: DogrulamaIn,
    gerekce: str | None,
) -> BelgemOut:
    b, g = await _benim_belgem(db, belge_id, user)
    istek = _istek(request, clock)
    try:
        svc.yanit_kontrol(b)
        yol = await svc.kimlik_dogrula(db, user, parola=govde.parola, kod=govde.kod, clock=clock)
        await svc.yanitla(db, b, user, onay=onay, gerekce=gerekce, dogrulama=yol, istek=istek)
    except svc.DogrulamaHatasi as exc:
        await db.commit()  # hatalı deneme sayacı kalıcı olsun
        raise _hata(exc) from exc
    except svc.IkBelgeHatasi as exc:
        raise _hata(exc) from exc
    await db.commit()
    await db.refresh(b)
    return _belgem(b, g)


@router.post("/belgelerim/{belge_id}/onayla", response_model=BelgemOut)
async def belgemi_onayla(
    belge_id: int,
    govde: DogrulamaIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: CurrentUser,
) -> BelgemOut:
    return await _yanitla(belge_id, request, db, clock, user, onay=True, govde=govde, gerekce=None)


@router.post("/belgelerim/{belge_id}/itiraz", response_model=BelgemOut)
async def belgeme_itiraz(
    belge_id: int, govde: ItirazIn, request: Request, db: DbDep, clock: ClockDep, user: CurrentUser
) -> BelgemOut:
    return await _yanitla(
        belge_id, request, db, clock, user, onay=False, govde=govde, gerekce=govde.gerekce
    )
