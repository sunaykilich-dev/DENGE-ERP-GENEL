"""Görev panosu — pano, kolon, kart, yorum (izin: gorev.gor / gorev.yaz).

**Kart ERP kaydına bağlanabilir ama zorunlu değil** (kullanıcı kararı,
30 Eyl 2026). Bağlantı polimorfik; çözümlemesi `services/gorevler.py`'de.

**Kapsam filtresi UYGULANMAZ** (kullanıcı kararı: "yetkisi olan herkes").
Yani `KENDI_MUSTERILERI` kapsamındaki bir satış temsilcisi, başkasının
müşterisine bağlı bir kartı da görür. Buna karşılık karttan o kayda GİTMEK
serbest değil: kayıt uçlarının kendi kapsam kontrolü yerinde duruyor, tıklayan
kişi yetkisi yoksa kaydı açamaz. Kartın başlığı görünür, kaydın içi görünmez.

**Sıralama tam sayı ve taşımada yeniden numaralanır.** Kesirli konum (Trello
deseni) kayan noktada zamanla çözünürlük kaybediyor; kolon başına kart sayısı
onlarla ölçülen bir panoda yeniden numaralamak hem ucuz hem kesin.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import (
    Board,
    BoardColumn,
    BoardLabel,
    Card,
    CardComment,
    CardLabel,
    CardMember,
    User,
)
from app.models.gorev import ONCELIKLER
from app.services import audit
from app.services import gorevler as svc

router = APIRouter(prefix="/api/gorevler", tags=["gorevler"])

Okuyucu = Annotated[User, Depends(require_permission("gorev.gor"))]
Yazici = Annotated[User, Depends(require_permission("gorev.yaz"))]

# Yeni panoya konan hazır renkler (AntD etiket paleti).
VARSAYILAN_ETIKET_RENKLERI = ("green", "gold", "orange", "red", "purple", "blue")


# --- Şemalar -----------------------------------------------------------------


class EtiketOut(BaseModel):
    id: int
    ad: str | None
    renk: str
    sira: int

    model_config = {"from_attributes": True}


class UyeOut(BaseModel):
    id: int
    ad: str


class KolonOut(BaseModel):
    id: int
    title: str
    sira: int
    bitis_mi: bool
    wip_limit: int | None

    model_config = {"from_attributes": True}


class PanoOut(BaseModel):
    id: int
    title: str
    description: str | None
    sira: int
    arsivlendi: bool
    version: int
    kolonlar: list[KolonOut] = []
    etiketler: list[EtiketOut] = []
    kart_sayisi: int = 0

    model_config = {"from_attributes": True}


class BaglantiOut(BaseModel):
    entity: str
    entity_id: int
    ad: str
    etiket: str
    yol: str
    var: bool


class KartOut(BaseModel):
    id: int
    board_id: int
    column_id: int
    title: str
    description: str | None
    sira: int
    uyeler: list[UyeOut] = []
    etiketler: list[EtiketOut] = []
    due_date: date | None
    oncelik: str
    tamamlandi_at: object | None = None
    version: int
    baglanti: BaglantiOut | None = None
    yorum_sayisi: int = 0

    model_config = {"from_attributes": True}


class PanoIn(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    # Boş bırakılırsa panoda hiç kolon olmaz ve kart açılamaz; yeni pano
    # kullanılamaz halde doğmasın diye varsayılan üçlü verilir.
    kolonlar: list[str] = ["Yapılacak", "Devam ediyor", "Bitti"]


class PanoPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    arsivlendi: bool | None = None
    version: int | None = None


class KolonIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    bitis_mi: bool = False
    wip_limit: int | None = Field(default=None, ge=1, le=999)


class KolonPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=60)
    bitis_mi: bool | None = None
    wip_limit: int | None = Field(default=None, ge=1, le=999)
    sira: int | None = None


class KartIn(BaseModel):
    column_id: int
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    uyeler: list[int] = []
    etiketler: list[int] = []
    due_date: date | None = None
    oncelik: str = "NORMAL"
    entity: str | None = None
    entity_id: int | None = None


class KartPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    uyeler: list[int] | None = None
    etiketler: list[int] | None = None
    due_date: date | None = None
    oncelik: str | None = None
    entity: str | None = None
    entity_id: int | None = None
    version: int | None = None


class EtiketIn(BaseModel):
    ad: str | None = Field(default=None, max_length=40)
    renk: str = Field(min_length=3, max_length=20)


class TasimaIn(BaseModel):
    column_id: int
    # Hedef kolondaki 0 tabanlı yeni konum.
    sira: int = Field(ge=0)


class YorumIn(BaseModel):
    metin: str = Field(min_length=1, max_length=4000)


# --- Yardımcılar -------------------------------------------------------------


async def _pano(db, board_id: int) -> Board:
    pano = await db.get(Board, board_id)
    if pano is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pano bulunamadı")
    return pano


async def _kart(db, card_id: int) -> Card:
    kart = await db.get(Card, card_id)
    if kart is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kart bulunamadı")
    return kart


def _baglantiyi_dogrula(entity: str | None, entity_id: int | None) -> None:
    if (entity is None) != (entity_id is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Bağlantı için hem kayıt tipi hem kimlik gerekir."
        )
    if entity is not None and svc.tip(entity) is None:
        gecerli = ", ".join(t.kod for t in svc.KAYIT_TIPLERI)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bilinmeyen kayıt tipi: {entity}. Geçerli: {gecerli}"
        )


async def _kartlari_zenginlestir(db, kartlar: list[Card]) -> list[KartOut]:
    """Atanan adı, bağlantı etiketi ve yorum sayısını TOPLU çözer.

    Kart başına sorgu, elli kartlık bir panoda elli gidiş geliş demekti.
    """
    cikti = [KartOut.model_validate(k) for k in kartlar]
    if not kartlar:
        return cikti

    kimlikler = [k.id for k in kartlar]

    # Üye ve etiket bağları İLİŞKİ ÜZERİNDEN OKUNMAZ, açık sorguyla gelir.
    # Yeni eklenmiş bir kartta ilişkiye dokunmak tembel yükleme tetikliyor ve
    # asenkron bağlamda `MissingGreenlet` ile patlıyor.
    uye_satirlari = (
        await db.execute(select(CardMember).where(CardMember.card_id.in_(kimlikler)))
    ).scalars()
    karta_uye: dict[int, list[int]] = {}
    for u in uye_satirlari:
        karta_uye.setdefault(u.card_id, []).append(u.user_id)

    etiket_satirlari = (
        await db.execute(select(CardLabel).where(CardLabel.card_id.in_(kimlikler)))
    ).scalars()
    karta_etiket: dict[int, list[int]] = {}
    for e in etiket_satirlari:
        karta_etiket.setdefault(e.card_id, []).append(e.label_id)

    kisi_kimlikleri = {k for v in karta_uye.values() for k in v}
    adlar: dict[int, str] = {}
    if kisi_kimlikleri:
        adlar = {
            u.id: u.full_name
            for u in (await db.scalars(select(User).where(User.id.in_(kisi_kimlikleri)))).all()
        }

    etiket_kimlikleri = {e for v in karta_etiket.values() for e in v}
    etiketler: dict[int, BoardLabel] = {}
    if etiket_kimlikleri:
        etiketler = {
            e.id: e
            for e in (
                await db.scalars(select(BoardLabel).where(BoardLabel.id.in_(etiket_kimlikleri)))
            ).all()
        }

    ciftler = {(k.entity, k.entity_id) for k in kartlar if k.entity and k.entity_id}
    baglantilar = await svc.baglanti_cozumle(db, ciftler) if ciftler else {}

    sayimlar = dict(
        (
            await db.execute(
                select(CardComment.card_id, func.count())
                .where(CardComment.card_id.in_([k.id for k in kartlar]))
                .group_by(CardComment.card_id)
            )
        ).all()
    )

    for kart, out in zip(kartlar, cikti, strict=True):
        out.uyeler = [UyeOut(id=k, ad=adlar[k]) for k in karta_uye.get(kart.id, []) if k in adlar]
        out.etiketler = sorted(
            (
                EtiketOut.model_validate(etiketler[e])
                for e in karta_etiket.get(kart.id, [])
                if e in etiketler
            ),
            key=lambda e: e.sira,
        )
        out.yorum_sayisi = sayimlar.get(kart.id, 0)
        if kart.entity and kart.entity_id:
            b = baglantilar.get((kart.entity, kart.entity_id))
            if b:
                out.baglanti = BaglantiOut(
                    entity=kart.entity,
                    entity_id=kart.entity_id,
                    **b,  # type: ignore[arg-type]
                )
    return cikti


async def _uyeleri_yaz(db, kart: Card, kimlikler: list[int]) -> None:
    """Kartın ilgili kişilerini istenen kümeye EŞİTLER.

    Var olmayan kullanıcı sessizce atlanmaz, reddedilir: silinmiş bir
    kullanıcıyı karta yazmak, ekranda adsız bir rozet üretirdi.
    """
    istenen = set(kimlikler)
    if istenen:
        bulunan = set((await db.scalars(select(User.id).where(User.id.in_(istenen)))).all())
        if eksik := istenen - bulunan:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Bulunamayan kullanıcı: {', '.join(str(k) for k in sorted(eksik))}",
            )
    var_olan = set(
        (await db.scalars(select(CardMember.user_id).where(CardMember.card_id == kart.id))).all()
    )
    if fazla := var_olan - istenen:
        await db.execute(
            delete(CardMember).where(CardMember.card_id == kart.id, CardMember.user_id.in_(fazla))
        )
    for yeni in istenen - var_olan:
        db.add(CardMember(card_id=kart.id, user_id=yeni))


async def _etiketleri_yaz(db, kart: Card, kimlikler: list[int]) -> None:
    """Kartın etiketlerini eşitler. Etiket KARTIN PANOSUNA ait olmalı.

    Başka panonun etiketi yapıştırılabilseydi, o pano silindiğinde buradaki
    kart etiketsiz kalırdı ve sebebi görünmezdi.
    """
    istenen = set(kimlikler)
    if istenen:
        bulunan = set(
            (
                await db.scalars(
                    select(BoardLabel.id).where(
                        BoardLabel.id.in_(istenen), BoardLabel.board_id == kart.board_id
                    )
                )
            ).all()
        )
        if eksik := istenen - bulunan:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Bu panoya ait olmayan etiket: {', '.join(str(k) for k in sorted(eksik))}",
            )
    var_olan = set(
        (await db.scalars(select(CardLabel.label_id).where(CardLabel.card_id == kart.id))).all()
    )
    if fazla := var_olan - istenen:
        await db.execute(
            delete(CardLabel).where(CardLabel.card_id == kart.id, CardLabel.label_id.in_(fazla))
        )
    for yeni in istenen - var_olan:
        db.add(CardLabel(card_id=kart.id, label_id=yeni))


async def _kolonu_yeniden_numarala(db, column_id: int, *, haric: int | None = None) -> None:
    kartlar = (
        await db.scalars(
            select(Card).where(Card.column_id == column_id).order_by(Card.sira, Card.id)
        )
    ).all()
    n = 0
    for k in kartlar:
        if k.id == haric:
            continue
        k.sira = n
        n += 1


# --- Kayıt tipleri -----------------------------------------------------------


@router.get("/kayit-tipleri")
async def kayit_tipleri(_: Okuyucu) -> list[dict[str, str]]:
    """Karta bağlanabilecek ERP kayıt tipleri — arayüz seçenekleri buradan."""
    return [{"kod": t.kod, "ad": t.ad} for t in svc.KAYIT_TIPLERI]


# --- Panolar -----------------------------------------------------------------


@router.get("/panolar", response_model=list[PanoOut])
async def panolari_listele(
    db: DbDep,
    _: Okuyucu,
    arsiv: Annotated[bool, Query(description="Arşivlenmiş panoları da getir")] = False,
) -> list[PanoOut]:
    sorgu = select(Board).order_by(Board.sira, Board.id)
    if not arsiv:
        sorgu = sorgu.where(Board.arsivlendi.is_(False))
    panolar = (await db.scalars(sorgu)).all()
    sayimlar = dict(
        (await db.execute(select(Card.board_id, func.count()).group_by(Card.board_id))).all()
    )
    cikti = []
    for p in panolar:
        out = PanoOut.model_validate(p)
        out.kart_sayisi = sayimlar.get(p.id, 0)
        cikti.append(out)
    return cikti


@router.post("/panolar", response_model=PanoOut, status_code=status.HTTP_201_CREATED)
async def pano_olustur(payload: PanoIn, request: Request, db: DbDep, user: Yazici) -> PanoOut:
    # Kolonsuz pano KULLANILAMAZ: karta kolon gerekiyor ve ekranda "ne yapacağım"
    # sorusunun cevabı yok. Varsayılan üçlü var ama istemci boş liste
    # gönderebiliyordu; canlıda bir pano bu şekilde kolonsuz doğdu.
    if not payload.kolonlar:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pano en az bir kolonla açılmalı.")
    sonraki = (await db.scalar(select(func.coalesce(func.max(Board.sira), -1)))) + 1
    pano = Board(
        title=payload.title,
        description=payload.description,
        sira=sonraki,
        created_by=user.id,
    )
    db.add(pano)
    await db.flush()
    # Trello gibi: yeni pano ADSIZ altı renkle gelir. Ad zorunlu olsaydı hızlı
    # bir işaretleme için önce isim düşünmek gerekirdi; isteyen sonra adlandırır.
    for i, renk in enumerate(VARSAYILAN_ETIKET_RENKLERI):
        db.add(BoardLabel(board_id=pano.id, ad=None, renk=renk, sira=i))
    for i, ad in enumerate(payload.kolonlar):
        db.add(
            BoardColumn(
                board_id=pano.id,
                title=ad,
                sira=i,
                # Son kolon varsayılan olarak "bitiş"; üç kolonlu şablonda
                # "Bitti" oraya düşüyor ve kullanıcı elle işaretlemek zorunda
                # kalmıyor. Yanlışsa kolon ayarından değiştirilir.
                bitis_mi=(i == len(payload.kolonlar) - 1 and len(payload.kolonlar) > 1),
            )
        )
    await audit.log(
        db,
        "boards",
        "olustur",
        entity_id=pano.id,
        new_value={"ad": pano.title, "kolon": len(payload.kolonlar)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(pano)
    return PanoOut.model_validate(pano)


@router.patch("/panolar/{board_id}", response_model=PanoOut)
async def pano_guncelle(
    board_id: int, payload: PanoPatch, request: Request, db: DbDep, user: Yazici
) -> PanoOut:
    pano = await _pano(db, board_id)
    if payload.version is not None and payload.version != pano.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Bu kaydı siz görüntülerken başka biri değiştirdi."
        )
    eski = {"ad": pano.title, "arsiv": pano.arsivlendi}
    if payload.title is not None:
        pano.title = payload.title
    if payload.description is not None:
        pano.description = payload.description
    if payload.arsivlendi is not None:
        pano.arsivlendi = payload.arsivlendi
    pano.updated_by = user.id
    await audit.log(
        db,
        "boards",
        "guncelle",
        entity_id=pano.id,
        old_value=eski,
        new_value={"ad": pano.title, "arsiv": pano.arsivlendi},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(pano)
    return PanoOut.model_validate(pano)


@router.delete("/panolar/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def pano_sil(board_id: int, request: Request, db: DbDep, user: Yazici) -> None:
    """Yalnız BOŞ pano silinir.

    Kartlı pano silmek, o işlerin geçmişini de siler. Bitmiş bir pano için
    doğru hareket arşivlemektir; arşiv listeden kaldırır, kaydı korur.
    """
    pano = await _pano(db, board_id)
    adet = await db.scalar(select(func.count()).select_from(Card).where(Card.board_id == board_id))
    if adet:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Panoda {adet} kart var; silmek yerine arşivleyin ya da kartları taşıyın.",
        )
    await audit.log(
        db,
        "boards",
        "sil",
        entity_id=pano.id,
        old_value={"ad": pano.title},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.delete(pano)
    await db.commit()


# --- Kolonlar ----------------------------------------------------------------


@router.post(
    "/panolar/{board_id}/kolonlar", response_model=KolonOut, status_code=status.HTTP_201_CREATED
)
async def kolon_ekle(board_id: int, payload: KolonIn, db: DbDep, user: Yazici) -> KolonOut:
    await _pano(db, board_id)
    sonraki = (
        await db.scalar(
            select(func.coalesce(func.max(BoardColumn.sira), -1)).where(
                BoardColumn.board_id == board_id
            )
        )
    ) + 1
    kolon = BoardColumn(
        board_id=board_id,
        title=payload.title,
        sira=sonraki,
        bitis_mi=payload.bitis_mi,
        wip_limit=payload.wip_limit,
    )
    db.add(kolon)
    await db.commit()
    await db.refresh(kolon)
    return KolonOut.model_validate(kolon)


@router.patch("/kolonlar/{column_id}", response_model=KolonOut)
async def kolon_guncelle(column_id: int, payload: KolonPatch, db: DbDep, user: Yazici) -> KolonOut:
    kolon = await db.get(BoardColumn, column_id)
    if kolon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kolon bulunamadı")
    if payload.title is not None:
        kolon.title = payload.title
    if payload.bitis_mi is not None:
        kolon.bitis_mi = payload.bitis_mi
    if payload.wip_limit is not None or "wip_limit" in payload.model_fields_set:
        kolon.wip_limit = payload.wip_limit
    if payload.sira is not None:
        kolon.sira = payload.sira
    await db.commit()
    await db.refresh(kolon)
    return KolonOut.model_validate(kolon)


@router.delete("/kolonlar/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def kolon_sil(column_id: int, db: DbDep, user: Yazici) -> None:
    kolon = await db.get(BoardColumn, column_id)
    if kolon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kolon bulunamadı")
    adet = await db.scalar(
        select(func.count()).select_from(Card).where(Card.column_id == column_id)
    )
    if adet:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kolonda {adet} kart var; önce başka bir kolona taşıyın.",
        )
    await db.delete(kolon)
    await db.commit()


# --- Etiketler ---------------------------------------------------------------


@router.post(
    "/panolar/{board_id}/etiketler", response_model=EtiketOut, status_code=status.HTTP_201_CREATED
)
async def etiket_ekle(board_id: int, payload: EtiketIn, db: DbDep, user: Yazici) -> EtiketOut:
    await _pano(db, board_id)
    sonraki = (
        await db.scalar(
            select(func.coalesce(func.max(BoardLabel.sira), -1)).where(
                BoardLabel.board_id == board_id
            )
        )
    ) + 1
    etiket = BoardLabel(board_id=board_id, ad=payload.ad or None, renk=payload.renk, sira=sonraki)
    db.add(etiket)
    await db.commit()
    await db.refresh(etiket)
    return EtiketOut.model_validate(etiket)


@router.patch("/etiketler/{label_id}", response_model=EtiketOut)
async def etiket_guncelle(label_id: int, payload: EtiketIn, db: DbDep, user: Yazici) -> EtiketOut:
    etiket = await db.get(BoardLabel, label_id)
    if etiket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Etiket bulunamadı")
    etiket.ad = payload.ad or None
    etiket.renk = payload.renk
    await db.commit()
    await db.refresh(etiket)
    return EtiketOut.model_validate(etiket)


@router.delete("/etiketler/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def etiket_sil(label_id: int, db: DbDep, user: Yazici) -> None:
    """Etiket silinince kartlardan da düşer (CASCADE) — kart silinmez."""
    etiket = await db.get(BoardLabel, label_id)
    if etiket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Etiket bulunamadı")
    await db.delete(etiket)
    await db.commit()


# --- Kartlar -----------------------------------------------------------------


@router.get("/panolar/{board_id}/kartlar", response_model=list[KartOut])
async def kartlari_listele(board_id: int, db: DbDep, _: Okuyucu) -> list[KartOut]:
    await _pano(db, board_id)
    kartlar = list(
        (
            await db.scalars(
                select(Card).where(Card.board_id == board_id).order_by(Card.column_id, Card.sira)
            )
        ).all()
    )
    return await _kartlari_zenginlestir(db, kartlar)


@router.get("/kayit/{entity}/{entity_id}", response_model=list[KartOut])
async def kaydin_kartlari(entity: str, entity_id: int, db: DbDep, _: Okuyucu) -> list[KartOut]:
    """Bir ERP kaydına bağlı kartlar — kayıt ekranındaki "Görevler" paneli."""
    _baglantiyi_dogrula(entity, entity_id)
    kartlar = list(
        (
            await db.scalars(
                select(Card)
                .where(Card.entity == entity, Card.entity_id == entity_id)
                .order_by(Card.created_at.desc())
            )
        ).all()
    )
    return await _kartlari_zenginlestir(db, kartlar)


@router.post(
    "/panolar/{board_id}/kartlar", response_model=KartOut, status_code=status.HTTP_201_CREATED
)
async def kart_olustur(
    board_id: int, payload: KartIn, request: Request, db: DbDep, user: Yazici
) -> KartOut:
    await _pano(db, board_id)
    kolon = await db.get(BoardColumn, payload.column_id)
    if kolon is None or kolon.board_id != board_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kolon bu panoya ait değil")
    if payload.oncelik not in ONCELIKLER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Geçersiz öncelik: {payload.oncelik}")
    _baglantiyi_dogrula(payload.entity, payload.entity_id)

    sonraki = (
        await db.scalar(
            select(func.coalesce(func.max(Card.sira), -1)).where(Card.column_id == kolon.id)
        )
    ) + 1
    kart = Card(
        board_id=board_id,
        column_id=kolon.id,
        title=payload.title,
        description=payload.description,
        sira=sonraki,
        due_date=payload.due_date,
        oncelik=payload.oncelik,
        entity=payload.entity,
        entity_id=payload.entity_id,
        created_by=user.id,
    )
    db.add(kart)
    await db.flush()
    await _uyeleri_yaz(db, kart, payload.uyeler)
    await _etiketleri_yaz(db, kart, payload.etiketler)
    await db.flush()
    await audit.log(
        db,
        "cards",
        "olustur",
        entity_id=kart.id,
        new_value={"baslik": kart.title, "pano": board_id},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(kart)
    return (await _kartlari_zenginlestir(db, [kart]))[0]


@router.patch("/kartlar/{card_id}", response_model=KartOut)
async def kart_guncelle(
    card_id: int, payload: KartPatch, request: Request, db: DbDep, user: Yazici
) -> KartOut:
    kart = await _kart(db, card_id)
    if payload.version is not None and payload.version != kart.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Bu kaydı siz görüntülerken başka biri değiştirdi."
        )
    if payload.oncelik is not None and payload.oncelik not in ONCELIKLER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Geçersiz öncelik: {payload.oncelik}")

    alanlar = payload.model_fields_set
    yeni_entity = payload.entity if "entity" in alanlar else kart.entity
    yeni_entity_id = payload.entity_id if "entity_id" in alanlar else kart.entity_id
    _baglantiyi_dogrula(yeni_entity, yeni_entity_id)

    eski = {
        "baslik": kart.title,
        "uye": sorted(
            (
                await db.scalars(select(CardMember.user_id).where(CardMember.card_id == kart.id))
            ).all()
        ),
    }
    for ad in ("title", "description", "due_date", "oncelik"):
        if ad in alanlar:
            setattr(kart, ad, getattr(payload, ad))
    if payload.uyeler is not None:
        await _uyeleri_yaz(db, kart, payload.uyeler)
    if payload.etiketler is not None:
        await _etiketleri_yaz(db, kart, payload.etiketler)
    kart.entity, kart.entity_id = yeni_entity, yeni_entity_id
    kart.updated_by = user.id

    await audit.log(
        db,
        "cards",
        "guncelle",
        entity_id=kart.id,
        old_value=eski,
        new_value={
            "baslik": kart.title,
            "uye": sorted(
                (
                    await db.scalars(
                        select(CardMember.user_id).where(CardMember.card_id == kart.id)
                    )
                ).all()
            ),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(kart)
    return (await _kartlari_zenginlestir(db, [kart]))[0]


@router.post("/kartlar/{card_id}/tasi", response_model=KartOut)
async def kart_tasi(
    card_id: int, payload: TasimaIn, db: DbDep, user: Yazici, clock: ClockDep
) -> KartOut:
    """Kartı bir kolondan diğerine ya da kolon içinde taşır.

    İyimser kilitleme UYGULANMAZ: taşıma sık ve düşük riskli bir hareket,
    sürüm çakışmasıyla reddetmek panoyu kullanılmaz yapardı. Çakışan iki
    taşımada son yazan kazanır — kaybolan şey yalnız sıra.
    """
    kart = await _kart(db, card_id)
    hedef = await db.get(BoardColumn, payload.column_id)
    if hedef is None or hedef.board_id != kart.board_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kolon bu panoya ait değil")

    kaynak_kolon = kart.column_id
    kart.column_id = hedef.id
    kart.updated_by = user.id

    # Bitiş kolonuna İLK gelişte damgala; geri alınsa da damga kalır.
    if hedef.bitis_mi and kart.tamamlandi_at is None:
        kart.tamamlandi_at = clock.now()

    # Hedef kolonu, taşınan kart hariç sırala; sonra araya yerleştir.
    await _kolonu_yeniden_numarala(db, hedef.id, haric=kart.id)
    await db.flush()
    diger = [
        k
        for k in (
            await db.scalars(
                select(Card)
                .where(Card.column_id == hedef.id, Card.id != kart.id)
                .order_by(Card.sira, Card.id)
            )
        ).all()
    ]
    konum = min(payload.sira, len(diger))
    for i, k in enumerate(diger[:konum]):
        k.sira = i
    kart.sira = konum
    for i, k in enumerate(diger[konum:], start=konum + 1):
        k.sira = i

    if kaynak_kolon != hedef.id:
        await db.flush()
        await _kolonu_yeniden_numarala(db, kaynak_kolon)

    await db.commit()
    await db.refresh(kart)
    return (await _kartlari_zenginlestir(db, [kart]))[0]


@router.delete("/kartlar/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def kart_sil(card_id: int, request: Request, db: DbDep, user: Yazici) -> None:
    kart = await _kart(db, card_id)
    kolon = kart.column_id
    await audit.log(
        db,
        "cards",
        "sil",
        entity_id=kart.id,
        old_value={"baslik": kart.title},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.delete(kart)
    await db.flush()
    await _kolonu_yeniden_numarala(db, kolon)
    await db.commit()


# --- Yorumlar ----------------------------------------------------------------


class YorumOut(BaseModel):
    id: int
    user_id: int | None
    yazan: str | None = None
    metin: str
    created_at: object

    model_config = {"from_attributes": True}


@router.get("/kartlar/{card_id}/yorumlar", response_model=list[YorumOut])
async def yorumlari_listele(card_id: int, db: DbDep, _: Okuyucu) -> list[YorumOut]:
    await _kart(db, card_id)
    yorumlar = (
        await db.scalars(
            select(CardComment)
            .where(CardComment.card_id == card_id)
            .order_by(CardComment.created_at)
        )
    ).all()
    kisiler = {y.user_id for y in yorumlar if y.user_id}
    adlar = (
        {
            u.id: u.full_name
            for u in (await db.scalars(select(User).where(User.id.in_(kisiler)))).all()
        }
        if kisiler
        else {}
    )
    cikti = []
    for y in yorumlar:
        o = YorumOut.model_validate(y)
        o.yazan = adlar.get(y.user_id) if y.user_id else None
        cikti.append(o)
    return cikti


@router.post(
    "/kartlar/{card_id}/yorumlar", response_model=YorumOut, status_code=status.HTTP_201_CREATED
)
async def yorum_ekle(card_id: int, payload: YorumIn, db: DbDep, user: Yazici) -> YorumOut:
    await _kart(db, card_id)
    yorum = CardComment(card_id=card_id, user_id=user.id, metin=payload.metin)
    db.add(yorum)
    await db.commit()
    await db.refresh(yorum)
    out = YorumOut.model_validate(yorum)
    out.yazan = user.full_name
    return out
