"""Dosya ekleri — tek bir uç, bütün modüller için.

Ek mekanizması İŞ EMRİNE ÖZEL DEĞİL (bkz. models/attachment.py): montaj
fotoğrafı, ürün görseli, broşür, ruhsat, gümrük evrakı ve sözleşme aynı
tablodan beslenir. Bu yüzden yetki de sahip kayda göre belirlenir: ürün
ekini yönetmek `urun.yaz`, cihaz ekini yönetmek `cihaz.yaz` ister.
"""

import unicodedata
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import text as sa_text

from app.api.deps import DbDep, client_ip, current_user, scope_filter
from app.models import Attachment, User
from app.models.attachment import EK_SAHIPLERI, EK_TURLERI
from app.services import audit
from app.services import storage as depo

router = APIRouter(prefix="/api/ekler", tags=["ekler"])

Kullanici = Annotated[User, Depends(current_user)]

# Sahip kayıt türü → o kaydı değiştirmek için gereken izin. Ek yüklemek
# kaydı değiştirmektir; görmek için okuma izni yeterlidir.
SAHIP_IZNI: dict[str, tuple[str, str]] = {
    "accounts": ("hesap.gor", "hesap.yaz"),
    "products": ("urun.gor", "urun.yaz"),
    "devices": ("cihaz.gor", "cihaz.yaz"),
    "vehicles": ("arac.gor", "arac.yaz"),
    "sim_cards": ("hat.gor", "hat.yaz"),
    "work_orders": ("isemri.gor", "isemri.yaz"),
    "quotes": ("teklif.gor", "teklif.yaz"),
    "contracts": ("abonelik.gor", "abonelik.yaz"),
    "settlements": ("hakedis.gor", "hakedis.yaz"),
    "import_files": ("satinalma.gor", "satinalma.yaz"),
}


class EkOut(BaseModel):
    id: int
    entity: str
    entity_id: int
    kind: str
    file_name: str
    mime_type: str
    size_bytes: int
    gorsel: bool
    notes: str | None
    uploaded_at: datetime
    uploaded_by: int | None

    @classmethod
    def of(cls, e: Attachment) -> "EkOut":
        return cls(
            id=e.id,
            entity=e.entity,
            entity_id=e.entity_id,
            kind=e.kind,
            file_name=e.file_name,
            mime_type=e.mime_type,
            size_bytes=e.size_bytes,
            gorsel=e.mime_type in depo.GORSEL_TIPLERI,
            notes=e.notes,
            uploaded_at=e.uploaded_at,
            uploaded_by=e.uploaded_by,
        )


def _sahip_dogrula(entity: str) -> tuple[str, str]:
    if entity not in EK_SAHIPLERI or entity not in SAHIP_IZNI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen kayıt türü: {entity}")
    return SAHIP_IZNI[entity]


async def _kapsam(db, entity: str, entity_id: int, user: User) -> None:
    """Kayıt bazlı kapsamı ek uçlarında da uygular (plan §3.4).

    Ek uçları yalnız MODÜL iznine bakıyordu: `hesap.gor` izni olan satış
    temsilcisi, portföyü dışındaki bir hesabın vergi levhasını listeliyor,
    indiriyor ve silebiliyordu. Ek kimlikleri sıralı olduğu için bu, tüm
    belge arşivinin taranabilmesi demekti.

    Kapsam bugün yalnız `accounts` için tanımlı; başka bir kayıt türüne
    kapsam geldiğinde kontrol buraya eklenir.
    """
    if entity != "accounts" or scope_filter(user) is None:
        return
    from app.models import Account

    var = await db.scalar(
        select(Account.id).where(
            Account.id == entity_id,
            Account.is_deleted.is_(False),
            Account.sales_rep_id == user.id,
        )
    )
    if var is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kayıt bulunamadı")


def _izin(user: User, kod: str) -> None:
    """İzin sahip kayda göre değiştiği için `require_permission` bağımlılığı
    kullanılamıyor; kontrol gövdede ama kuralı aynı."""
    if not user.has(kod):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Bu işlem için yetkiniz yok ({kod})")


def _dosya_adi_basligi(ad: str) -> str:
    """`Content-Disposition` için dosya adı — RFC 5987.

    HTTP başlıkları **latin-1** ile kodlanır; Türkçe bir dosya adındaki `İ`
    başlığı yazarken `UnicodeEncodeError` atıp indirmeyi 500 yapıyordu
    ("GÜNCEL VERGİ LEVHASI.pdf" tam olarak böyle patladı). Türkçe bir ERP'de
    dosya adlarının çoğu bu durumda.

    İki biçim birden yazılır: eski istemciler için latin-1'e indirgenmiş
    `filename`, modern tarayıcılar için UTF-8 `filename*` (o kazanır).
    """
    yedek = unicodedata.normalize("NFKD", ad).encode("ascii", "ignore").decode() or "dosya"
    yedek = yedek.replace('"', "")
    return f"filename=\"{yedek}\"; filename*=UTF-8''{quote(ad)}"


@router.get("/dosya/{ek_id}")
async def indir(ek_id: int, db: DbDep, user: Kullanici) -> Response:
    ek = await db.get(Attachment, ek_id)
    if ek is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ek bulunamadı")
    okuma, _ = _sahip_dogrula(ek.entity)
    _izin(user, okuma)
    await _kapsam(db, ek.entity, ek.entity_id, user)
    try:
        yol = depo.yol(ek.storage_path)
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    # `inline` yalnız görsel ve PDF'te: tarayıcının başka bir türü kendi
    # bağlamımızda açması istenmez.
    icerde = ek.mime_type in depo.GORSEL_TIPLERI or ek.mime_type == "application/pdf"
    yerlesim = "inline" if icerde else "attachment"
    return Response(
        content=yol.read_bytes(),
        media_type=ek.mime_type,
        headers={
            "Content-Disposition": f"{yerlesim}; {_dosya_adi_basligi(ek.file_name)}",
            # ÖNBELLEĞE ALINMAZ. Eskiden `private, max-age=604800` ile bir
            # HAFTA saklanıyordu: içerik değişmez olduğu için mantıklı
            # görünüyordu, ama bu dosyalar vergi levhası, sözleşme ve montaj
            # fotoğrafı — KVKK kapsamında kişisel veri. Ortak kullanılan bir
            # ofis bilgisayarında oturum kapandıktan SONRA da tarayıcı
            # önbelleğinden açılabiliyordu. Yetki kontrolü her indirmede
            # yeniden koşmalı.
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )


@router.get("/{entity}/{entity_id}", response_model=list[EkOut])
async def listele(entity: str, entity_id: int, db: DbDep, user: Kullanici) -> list[EkOut]:
    okuma, _ = _sahip_dogrula(entity)
    _izin(user, okuma)
    await _kapsam(db, entity, entity_id, user)
    kayitlar = (
        await db.scalars(
            select(Attachment)
            .where(Attachment.entity == entity, Attachment.entity_id == entity_id)
            .order_by(Attachment.id.desc())
        )
    ).all()
    return [EkOut.of(e) for e in kayitlar]


# Sahip kayıt türü → o kaydı tutan tablo. Ek yüklenmeden önce kaydın
# GERÇEKTEN var olduğu doğrulanır.
_SAHIP_TABLOSU = {
    "accounts": "accounts",
    "products": "products",
    "devices": "devices",
    "vehicles": "vehicles",
    "work_orders": "work_orders",
    "quotes": "quotes",
    "partner_settlements": "partner_settlements",
    "rma_cases": "rma_cases",
    "purchase_orders": "purchase_orders",
    "import_files": "import_files",
}


async def _sahip_var_mi(db, entity: str, entity_id: int) -> bool:
    tablo = _SAHIP_TABLOSU.get(entity)
    if tablo is None:
        return True  # tür zaten _sahip_dogrula'da elendi
    sonuc = await db.execute(
        sa_text(f"select 1 from {tablo} where id = :id limit 1"),  # noqa: S608
        {"id": entity_id},
    )
    return sonuc.first() is not None


@router.post("/{entity}/{entity_id}", response_model=EkOut, status_code=status.HTTP_201_CREATED)
async def yukle(
    entity: str,
    entity_id: Annotated[int, Path(ge=1, le=9_223_372_036_854_775_807)],
    file: UploadFile,
    request: Request,
    db: DbDep,
    user: Kullanici,
    kind: str = "DIGER",
    notes: Annotated[str | None, Query(max_length=500)] = None,
) -> EkOut:
    _, yazma = _sahip_dogrula(entity)
    _izin(user, yazma)
    await _kapsam(db, entity, entity_id, user)
    if kind not in EK_TURLERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen ek türü: {kind}")
    if not await _sahip_var_mi(db, entity, entity_id):
        # Olmayan kayda ek bağlanırsa dosya diskte yer tutar ama hiçbir
        # ekranda görünmez: sessizce büyüyen çöp.
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{entity} kaydı bulunamadı: {entity_id}")

    try:
        icerik = await depo.sinirli_oku(file)
        mime = depo.mime_coz(file.content_type or "", file.filename or "")
        kayit = depo.yaz(icerik, mime_type=mime)
    except depo.DepoHatasi as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    ek = Attachment(
        entity=entity,
        entity_id=entity_id,
        kind=kind,
        file_name=depo.temiz_ad(file.filename or "dosya"),
        storage_path=kayit.storage_path,
        mime_type=kayit.mime_type,
        size_bytes=kayit.size_bytes,
        sha256=kayit.sha256,
        notes=notes,
        uploaded_by=user.id,
    )
    db.add(ek)
    await db.flush()

    # Ürünün ilk görseli kapak olur: katalog listesi küçük resmi tek sorguda
    # göstersin diye ürün kartında kapak ek kimliği duruyor. Kullanıcıya
    # "şimdi de kapak seç" dedirtmenin bir karşılığı yoktu.
    if entity == "products" and ek.mime_type in depo.GORSEL_TIPLERI:
        from app.models import Product

        urun = await db.get(Product, entity_id)
        if urun is not None and urun.cover_attachment_id is None:
            urun.cover_attachment_id = ek.id

    await audit.log(
        db,
        entity,
        "ek.yukle",
        entity_id=entity_id,
        new_value={"ek_id": ek.id, "dosya": ek.file_name, "tur": kind},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return EkOut.of(ek)


@router.delete("/{ek_id}", status_code=status.HTTP_204_NO_CONTENT)
async def sil(ek_id: int, request: Request, db: DbDep, user: Kullanici) -> None:
    ek = await db.get(Attachment, ek_id)
    if ek is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ek bulunamadı")
    _, yazma = _sahip_dogrula(ek.entity)
    _izin(user, yazma)
    await _kapsam(db, ek.entity, ek.entity_id, user)

    # Ürün kapak görseli siliniyorsa bağ da kopar; FK SET NULL bunu yapar ama
    # aynı transaction içinde açıkça yapmak niyeti görünür kılıyor.
    if ek.entity == "products":
        from app.models import Product

        urun = await db.get(Product, ek.entity_id)
        if urun is not None and urun.cover_attachment_id == ek.id:
            urun.cover_attachment_id = None

    bilgi = {"dosya": ek.file_name, "tur": ek.kind}
    entity, entity_id = ek.entity, ek.entity_id
    await db.delete(ek)
    await db.flush()

    # Dosya BURADA SİLİNMEZ. Eşzamanlı bir yükleme aynı içeriği paylaşıyorsa
    # referans sayımı onun henüz commit edilmemiş satırını göremez ve dosyayı
    # kaldırırdı; yükleme 201 döner, belge indirilemezdi (8 denemenin 4'ünde
    # yaşandı). Artan dosyaları gece çalışan çöp toplama işi kaldırır.

    await audit.log(
        db,
        entity,
        "ek.sil",
        entity_id=entity_id,
        old_value=bilgi,
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
