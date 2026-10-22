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

from app.api.deps import ClockDep, DbDep, client_ip, current_user
from app.models import Attachment, User
from app.models.attachment import EK_SAHIPLERI, EK_TURLERI
from app.services import audit
from app.services import storage as depo
from app.services.teknik_servis import ek_kapsam

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
    # --- Teknik servis (plan §1.11) ---
    "service_orders": ("servis.gor", "servis.yaz"),
    "service_equipment": ("ekipman.gor", "ekipman.yaz"),
    "maintenance_contracts": ("bakim.gor", "bakim.yaz"),
    # Tesis eki carinin parçası: okuma hesap.gor, yükleme lokasyon.yaz.
    "addresses": ("hesap.gor", "lokasyon.yaz"),
    # --- Dalga 2 kiralama dalları (D2-S iskelet; kapsam fonksiyonunu D2-C
    # kendi dosyasında `ek_kapsam.kaydet` ile bağlar — o zamana dek
    # fail-closed). İmzalı teslim tutanağını sevkte depo yükler (E06 §2.2/4).
    "rentals": ("kiralama.gor", "kiralama.asama"),
    "rental_assets": ("kiralama.gor", "kiralama.envanter"),
    # --- Dalga 2 eğitim dalları (D2-F). Kişisel performans eki: okuma
    # `egitim.detay` (YONETIM özet izniyle göremez, E08-20); kapsam
    # `egitim_gozlem` içindeki kayıtlı fonksiyonda (personel kapsamı).
    "training_observations": ("egitim.detay", "egitim.gozlem"),
    "training_corrective_actions": ("egitim.detay", "egitim.yaz"),
    "personnel_certificates": ("egitim.detay", "egitim.yaz"),
}

# Okuma izni yoksa KENDİ kaydının ekini görmeye yeten izin (E08 K12, kontrol
# §2/10): teknisyen kendi gözlem fotoğrafını/belgesini `egitim.kendim` ile
# görür. "Kendi kaydı mı" kararını kapsam fonksiyonu verir; başkasınınki 404.
KENDI_OKUMA_IZNI: dict[str, str] = {
    "training_observations": "egitim.kendim",
    "training_corrective_actions": "egitim.kendim",
    "personnel_certificates": "egitim.kendim",
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


async def _kapsam(db, entity: str, entity_id: int, user: User, *, yazma: bool = False) -> None:
    """Kayıt bazlı kapsamı ek uçlarında da uygular (plan §3.4).

    Ek uçları yalnız MODÜL iznine bakıyordu: `hesap.gor` izni olan satış
    temsilcisi, portföyü dışındaki bir hesabın vergi levhasını listeliyor,
    indiriyor ve silebiliyordu. Ek kimlikleri sıralı olduğu için bu, tüm
    belge arşivinin taranabilmesi demekti.

    Kural sahip türüne göre `services/teknik_servis/ek_kapsam.py` kayıt
    defterinden gelir (`accounts` dalı orada birebir korunur). Teknik servis
    türünde kayıtlı kural yoksa erişim reddedilir (fail-closed). Kapsam
    dışı → 404: kimlik taramasında "var ama göremezsin" bilgisi sızmasın.
    """
    if not await ek_kapsam.erisebilir_mi(db, user, entity, entity_id, yazma):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kayıt bulunamadı")


def _izin(user: User, kod: str) -> None:
    """İzin sahip kayda göre değiştiği için `require_permission` bağımlılığı
    kullanılamıyor; kontrol gövdede ama kuralı aynı."""
    if not user.has(kod):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Bu işlem için yetkiniz yok ({kod})")


def _okuma_izni(user: User, entity: str, okuma: str) -> None:
    """Okuma izni; yoksa `KENDI_OKUMA_IZNI` (yalnız kendi kaydı — kapsam
    fonksiyonu başkasınınkine 404 verir)."""
    kendi = KENDI_OKUMA_IZNI.get(entity)
    if user.has(okuma) or (kendi is not None and user.has(kendi)):
        return
    _izin(user, okuma)


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
    _okuma_izni(user, ek.entity, okuma)
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
    _okuma_izni(user, entity, okuma)
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
    "service_orders": "service_orders",
    "service_equipment": "service_equipment",
    "maintenance_contracts": "maintenance_contracts",
    "addresses": "addresses",
    "rentals": "rentals",
    "rental_assets": "rental_assets",
    "training_observations": "training_observations",
    "training_corrective_actions": "training_corrective_actions",
    "personnel_certificates": "personnel_certificates",
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
    clock: ClockDep,
    kind: str = "DIGER",
    notes: Annotated[str | None, Query(max_length=500)] = None,
) -> EkOut:
    _, yazma = _sahip_dogrula(entity)
    _izin(user, yazma)
    await _kapsam(db, entity, entity_id, user, yazma=True)
    if kind not in EK_TURLERI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen ek türü: {kind}")
    if not await _sahip_var_mi(db, entity, entity_id):
        # Olmayan kayda ek bağlanırsa dosya diskte yer tutar ama hiçbir
        # ekranda görünmez: sessizce büyüyen çöp.
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{entity} kaydı bulunamadı: {entity_id}")
    # Sahip türüne özgü kural (ör. kapalı servis işine ek yalnız servis.kapat).
    kurali = ek_kapsam.kural(entity)
    if kurali is not None and kurali.yukleme_oncesi is not None:
        try:
            await kurali.yukleme_oncesi(db, user, entity_id, clock)
        except ek_kapsam.EkKuralHatasi as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    try:
        icerik = await depo.sinirli_oku(file)
        mime = depo.mime_coz(file.content_type or "", file.filename or "")
        # Teknik servis eklerinde içerik beyanla uyuşmalı (magic byte).
        ek_kapsam.icerik_dogrula(entity, icerik, mime)
        kayit = depo.yaz(icerik, mime_type=mime)
    except ek_kapsam.IcerikUyusmazligi as exc:
        raise HTTPException(exc.durum, str(exc)) from exc
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
    if kurali is not None and kurali.yuklendi is not None:
        await kurali.yuklendi(db, user, ek, clock)
    await db.commit()
    return EkOut.of(ek)


@router.delete("/{ek_id}", status_code=status.HTTP_204_NO_CONTENT)
async def sil(ek_id: int, request: Request, db: DbDep, clock: ClockDep, user: Kullanici) -> None:
    ek = await db.get(Attachment, ek_id)
    if ek is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ek bulunamadı")
    _, yazma = _sahip_dogrula(ek.entity)
    _izin(user, yazma)
    await _kapsam(db, ek.entity, ek.entity_id, user, yazma=True)
    kurali = ek_kapsam.kural(ek.entity)
    if kurali is not None and kurali.silme_oncesi is not None:
        try:
            await kurali.silme_oncesi(db, user, ek, clock)
        except ek_kapsam.EkKuralHatasi as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # Ürün kapak görseli siliniyorsa bağ da kopar; FK SET NULL bunu yapar ama
    # aynı transaction içinde açıkça yapmak niyeti görünür kılıyor.
    if ek.entity == "products":
        from app.models import Product

        urun = await db.get(Product, ek.entity_id)
        if urun is not None and urun.cover_attachment_id == ek.id:
            urun.cover_attachment_id = None

    bilgi = {"dosya": ek.file_name, "tur": ek.kind}
    entity, entity_id = ek.entity, ek.entity_id
    silinen = {
        "ek_id": ek.id,
        "entity_id": entity_id,
        "dosya": ek.file_name,
        "tur": ek.kind,
        "sha256": ek.sha256,
    }
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
    if kurali is not None and kurali.silindi is not None:
        await kurali.silindi(db, user, silinen, clock)
    await db.commit()
