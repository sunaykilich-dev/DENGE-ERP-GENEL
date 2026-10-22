"""Ek (dosya) uçlarında kayıt bazlı kapsamın kayıt defteri (plan §1.11, E01-07).

**Neden:** `api/attachments.py` bütün modüllerin eklerine tek uçtan hizmet
ediyor ve kapsamı bugüne kadar yalnız `accounts` için elle yazılmış bir
`if` ile uyguluyordu. Ek kimlikleri sıralı olduğu için kapsamı olmayan her
sahip türü, belge arşivinin kimlik taramasıyla gezilebilmesi demektir.
Teknik servis dokuz yeni sahip türü getiriyor (servis işi, ekipman, bakım
sözleşmesi, lokasyon, kiralama, eğitim kayıtları); her biri kendi
modülünde, kendi birim/iş kapsamıyla kontrol edilmeli. Bu dosya o
kontrollerin TEK kayıt noktasıdır: `SAHIP_KAPSAMLARI[entity] = fn`.

**Fail-closed:** `KAPSAM_ZORUNLU` kümesindeki bir sahip türü için fonksiyon
kayıtlı değilse (ör. Dalga 1 dosyası henüz yüklenmedi) erişim REDDEDİLİR.
"Fonksiyon yoksa serbest" demek, modül yayına çıkmadan önce eklerinin
kapsamsız açılması olurdu.

Sözleşme: `async fn(db, user, entity_id, yazma) -> bool` — True: erişebilir.
Kayıt yoksa True döner (varlık kontrolü API'nin işi, `_sahip_var_mi`);
kapsam dışıysa False → API 404 (kimlik taranamasın diye 403 değil, KD-05).

Kayıt yeri (plan §4.2): `service_orders` dalı D1-C, `service_equipment`
fonksiyonu D1-E (`ekipman.py`), `maintenance_contracts` D1-F; kiralama/atölye
dalları D2-S, eğitim dalları D2-F. Modüller bu dosyayı DEĞİŞTİRMEZ,
kendi dosyalarının sonunda `kaydet(...)` çağırır.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.permissions import SCOPE_OWN_CUSTOMERS
from app.services.storage import DepoHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User

KapsamFn = Callable[["AsyncSession", "User", int, bool], Awaitable[bool]]

# Teknik servisin ek sahibi türleri (plan §1.11, kümülatif liste). Bunlarda
# kapsam fonksiyonu ZORUNLUDUR ve içerik (magic-byte) doğrulaması açıktır.
# `models/attachment.EK_SAHIPLERI`'ne yalnız tablosu VAR olanlar eklenir
# (Dalga 0/1); kiralama ve eğitim türleri kendi dalgalarında oraya da girer.
KAPSAM_ZORUNLU: frozenset[str] = frozenset(
    {
        "service_orders",
        "service_equipment",
        "maintenance_contracts",
        "addresses",
        "rentals",
        "rental_assets",
        "training_observations",
        "training_corrective_actions",
        "personnel_certificates",
    }
)

SAHIP_KAPSAMLARI: dict[str, KapsamFn] = {}


def kaydet(entity: str, fn: KapsamFn) -> KapsamFn:
    """Sahip türüne kapsam fonksiyonu bağlar. Aynı tür iki kez kaydedilemez:
    iki modülün aynı türü farklı kuralla koruması sessiz bir çelişki olurdu."""
    if entity in SAHIP_KAPSAMLARI and SAHIP_KAPSAMLARI[entity] is not fn:
        raise ValueError(f"'{entity}' için ek kapsamı zaten kayıtlı")
    SAHIP_KAPSAMLARI[entity] = fn
    return fn


async def erisebilir_mi(
    db: AsyncSession, user: User, entity: str, entity_id: int, yazma: bool
) -> bool:
    """Ek uçlarının tek kapsam kapısı.

    Kayıtlı fonksiyon varsa o karar verir. Yoksa: teknik servis türüyse RED
    (fail-closed), değilse kapsam tanımsız canlı tür (ürün, cihaz, araç...) →
    bugünkü davranış: yalnız modül izni yeterli.
    """
    fn = SAHIP_KAPSAMLARI.get(entity)
    if fn is not None:
        return await fn(db, user, entity_id, yazma)
    return entity not in KAPSAM_ZORUNLU


# --- Canlı dal: hesaplar (birebir korunur) --------------------------------------


async def _hesap_kapsami(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    """`accounts` dalı — eski `api/attachments._kapsam` davranışının AYNISI.

    Satış temsilcisi (KENDI_MUSTERILERI) yalnız kendi portföyündeki hesabın
    eklerini görür; silinmiş hesap da kapsam dışı sayılır. Diğer kapsamlar
    (TUMU ve teknik servisin birim kapsamları) canlı modüllerde filtresizdir
    (plan §1.2: mevcut yardımcılar değişmez).
    """
    if user.role.scope != SCOPE_OWN_CUSTOMERS:
        return True
    from app.models import Account

    var = await db.scalar(
        select(Account.id).where(
            Account.id == entity_id,
            Account.is_deleted.is_(False),
            Account.sales_rep_id == user.id,
        )
    )
    return var is not None


async def _lokasyon_kapsami(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    """`addresses` (tesis) dalı — lokasyon carinin kapsamını taşır.

    Tesis fotoğrafı/krokisi carinin bir parçasıdır: hesabı göremeyen
    temsilci onun tesislerinin eklerini de göremez.
    """
    from app.models import Address
    from app.services.accounts import kapsam_disinda_mi

    hesap_id = await db.scalar(select(Address.account_id).where(Address.id == entity_id))
    if hesap_id is None:
        return True  # kayıt yok: varlık kontrolü API'de (404)
    return not await kapsam_disinda_mi(db, user, hesap_id)


kaydet("accounts", _hesap_kapsami)
kaydet("addresses", _lokasyon_kapsami)


# --- İçerik doğrulama (magic byte) ---------------------------------------------

# Beyan edilen MIME ile dosyanın ilk baytları uyuşmalı. Sahadan telefonla
# yüklenen servis fotoğrafları ve imzalı formlar müşteri ekranında açılıyor;
# uzantısı .jpg ama içi HTML olan bir dosya tarayıcıda farklı yorumlanabilirdi.
# Yalnız teknik servis türlerinde açılır: canlı türlerde mevcut davranış
# (yalnız MIME beyaz listesi) değişmesin.
_OFIS_IMZASI = b"PK\x03\x04"
_HEIC_MARKALARI = {b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"}


def _uyusuyor(icerik: bytes, mime: str) -> bool:
    bas = icerik[:16]
    if mime == "image/jpeg":
        return bas.startswith(b"\xff\xd8\xff")
    if mime == "image/png":
        return bas.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/webp":
        return bas[:4] == b"RIFF" and bas[8:12] == b"WEBP"
    if mime == "image/heic":
        return bas[4:8] == b"ftyp" and bas[8:12] in _HEIC_MARKALARI
    if mime == "application/pdf":
        return bas.startswith(b"%PDF-")
    if mime in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return bas.startswith(_OFIS_IMZASI)
    if mime in ("text/csv", "text/plain"):
        # Metin dosyasında NUL baytı olmaz; varsa ikili dosya metin diye yükleniyor.
        return b"\x00" not in icerik[:4096]
    return False


class IcerikUyusmazligi(DepoHatasi):
    """Dosyanın baytları beyan edilen türle uyuşmuyor.

    `durum`: API'nin döneceği HTTP kodu. Servis işi eklerinde 400 (plan
    TS-032: istemci yanlış dosya gönderdi, girdi hatası); diğer teknik servis
    türlerinde Dalga 0 davranışı (422) korunur.
    """

    def __init__(self, mesaj: str, durum: int = 422) -> None:
        super().__init__(mesaj)
        self.durum = durum


# İçerik uyuşmazlığında 400 dönen sahip türleri (plan §2.2 TS-032).
_ICERIK_HATASI_400 = frozenset({"service_orders"})


def icerik_dogrula(entity: str, icerik: bytes, mime: str) -> None:
    """Teknik servis eklerinde içerik beyanla uyuşmuyorsa `IcerikUyusmazligi`."""
    if entity not in KAPSAM_ZORUNLU:
        return
    if not _uyusuyor(icerik, mime):
        raise IcerikUyusmazligi(
            "Dosya içeriği türüyle uyuşmuyor; dosya bozuk ya da uzantısı yanlış",
            400 if entity in _ICERIK_HATASI_400 else 422,
        )


# --- Sahip türüne özgü ek kuralları (yükleme/silme kancaları) -------------------
#
# Kapsam "kim görebilir"i söyler; bazı sahiplerin ayrıca "ne zaman eklenir /
# silinir" kuralı ve geçmiş kaydı vardır (servis işi: kapalı işe ek yalnız
# `servis.kapat` ile, silme 24 saat içinde, her yükleme/silme olay geçmişine).
# `api/attachments.py` bu kuralları sahip türünden bağımsız çağırır; kuralı
# olmayan türde hiçbir şey değişmez (canlı davranış korunur).


class EkKuralHatasi(ValueError):
    """Ek iş kuralı ihlali → 409 (Türkçe mesaj)."""


@dataclass(frozen=True)
class EkKurali:
    """Bir sahip türünün yükleme/silme kancaları; hepsi isteğe bağlı.

    `yukleme_oncesi(db, user, entity_id, clock)` ve `silme_oncesi(db, user,
    ek, clock)` kural ihlalinde `EkKuralHatasi` atar ve HİÇBİR ŞEY yazmaz.
    `yuklendi(db, user, ek, clock)` / `silindi(db, user, ek_bilgisi, clock)`
    aynı transaction'da, commit'ten önce çağrılır (olay geçmişi).
    """

    yukleme_oncesi: Callable[..., Awaitable[None]] | None = None
    yuklendi: Callable[..., Awaitable[None]] | None = None
    silme_oncesi: Callable[..., Awaitable[None]] | None = None
    silindi: Callable[..., Awaitable[None]] | None = None


EK_KURALLARI: dict[str, EkKurali] = {}


def kural_kaydet(entity: str, kural: EkKurali) -> EkKurali:
    if entity in EK_KURALLARI and EK_KURALLARI[entity] is not kural:
        raise ValueError(f"'{entity}' için ek kuralı zaten kayıtlı")
    EK_KURALLARI[entity] = kural
    return kural


def kural(entity: str) -> EkKurali | None:
    return EK_KURALLARI.get(entity)


# --- Servis işi dalı (TS-032, E01-07; plan §4.2: D1-C) ---------------------------


async def servis_isi_erisimi(db: AsyncSession, user: User, so, *, yazma: bool) -> bool:
    """Servis işine (ve bağlılarına: ek, onay) erişim — tek kural.

    Okuma: `kapsam.is_erisimi_yok_mu` (birim / kendi işi / müşteri; liste ile
    AYNI koşul). Yazma: KENDI_ISLERI kapsamında yalnız işe AKTİF ATAMASI olan
    (plan üyeliği okuma için yeterli, yazma için değil — E01-07 revised:
    "okuma birim+kendi işi, yazma aktif atama"). Silinmiş iş kapsam dışıdır.
    """
    from app.models import ServiceOrderAssignment
    from app.permissions import SCOPE_OWN_JOBS
    from app.services.teknik_servis import kapsam

    if so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        return False
    if yazma and user.role is not None and user.role.scope == SCOPE_OWN_JOBS:
        atama = await db.scalar(
            select(ServiceOrderAssignment.id).where(
                ServiceOrderAssignment.service_order_id == so.id,
                ServiceOrderAssignment.user_id == user.id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
        return atama is not None
    return True


async def _servis_isi_kapsami(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    from app.models import ServiceOrder

    so = await db.get(ServiceOrder, entity_id)
    if so is None:
        return True  # kayıt yok: varlık kontrolü API'de (404)
    return await servis_isi_erisimi(db, user, so, yazma=yazma)


kaydet("service_orders", _servis_isi_kapsami)


def _kapali_mi(so) -> bool:
    from app.models.teknik_servis import DURUM_GRUPLARI

    return so.status in DURUM_GRUPLARI["KAPALI"]


async def _servis_eki_yukleme_oncesi(db: AsyncSession, user: User, entity_id: int, clock) -> None:
    """Kapalı işe (TAMAMLANDI/KAPATILDI/IPTAL) ek yalnız `servis.kapat` ile (K19).

    Kapanmış işin kanıtı sonradan sessizce değişmesin; düzeltme yetkisi
    kapanışı verenlerdedir."""
    from app.models import ServiceOrder

    so = await db.get(ServiceOrder, entity_id)
    if so is not None and _kapali_mi(so) and not user.has("servis.kapat"):
        raise EkKuralHatasi(
            "Kapalı servis işine ek yalnız kapatma yetkisi (servis.kapat) olan kişi ekleyebilir."
        )


async def _servis_eki_yuklendi(db: AsyncSession, user: User, ek, clock) -> None:
    """EK olayı: 24 saat kuralının saati bu olayın Clock zamanıdır (B9)."""
    from app.models import ServiceOrder

    so = await db.get(ServiceOrder, ek.entity_id)
    await _olay(
        db,
        so,
        "EK",
        "Ek yüklendi",
        ek.file_name,
        user=user,
        clock=clock,
        veri={"ek_id": ek.id, "tur": ek.kind, "dosya": ek.file_name, "sha256": ek.sha256},
    )


async def _olay(db, so, tur: str, baslik: str, dosya: str, *, user, clock, veri: dict) -> None:
    """Olay özetine dosya adı yazılır; ad işin irtibat adını/telefonunu
    içeriyorsa (ör. "Ahmet Bey imza.png") özet adsız yazılır — olay geçmişi
    kişisel veri taşıyamaz (tetikleyici yüzünden anonimleştirilemez)."""
    from app.services.teknik_servis import gecmis

    try:
        await gecmis.olay_yaz(
            db, so, tur, f"{baslik}: {dosya[:200]}", user=user, clock=clock, veri=veri
        )
    except gecmis.KisiselVeriHatasi:
        guvenli = {k: v for k, v in veri.items() if k != "dosya"}
        await gecmis.olay_yaz(
            db, so, tur, f"{baslik} ({veri.get('tur')})", user=user, clock=clock, veri=guvenli
        )


async def ek_yukleme_ani(db: AsyncSession, ek):
    """Ekin yüklenme anı: EK olayının `olusma_zamani` (Clock); olay yoksa
    (göçle gelen ek) `uploaded_at`."""
    from app.models import ServiceOrderEvent

    an = await db.scalar(
        select(ServiceOrderEvent.olusma_zamani)
        .where(
            ServiceOrderEvent.service_order_id == ek.entity_id,
            ServiceOrderEvent.olay_turu == "EK",
            ServiceOrderEvent.veri["ek_id"].as_integer() == ek.id,
        )
        .order_by(ServiceOrderEvent.id)
        .limit(1)
    )
    return an or ek.uploaded_at


async def _servis_eki_silme_oncesi(db: AsyncSession, user: User, ek, clock) -> None:
    """Silme kuralları (K19, B9):

    - Onaya bağlı ek (imza, basılı form) SİLİNEMEZ — onay değişmez kayıttır.
    - Kapalı işte silme yalnız `servis.kapat`.
    - Açık işte yükleyen kişi `servis_ek_silme_saat` (24) içinde siler;
      süre dolmuşsa ya da başkasının ekiyse yalnız `servis.kapat`.
    """
    from datetime import timedelta

    from app.models import ServiceApproval, ServiceOrder
    from app.services import settings as ayar_svc

    bagli = await db.scalar(select(ServiceApproval.id).where(ServiceApproval.ek_id == ek.id))
    if bagli is not None:
        raise EkKuralHatasi(
            "Bu ek bir müşteri onayına bağlı (imza/basılı form); onay kaydı değişmez olduğu "
            "için ek silinemez."
        )
    so = await db.get(ServiceOrder, ek.entity_id)
    if user.has("servis.kapat"):
        return
    if so is not None and _kapali_mi(so):
        raise EkKuralHatasi(
            "Kapalı servis işinin eki yalnız kapatma yetkisi (servis.kapat) olan kişi silebilir."
        )
    saat = int(await ayar_svc.get(db, "servis_ek_silme_saat"))
    an = await ek_yukleme_ani(db, ek)
    if ek.uploaded_by != user.id or clock.now() - an > timedelta(hours=saat):
        raise EkKuralHatasi(
            f"Ek yalnız yükleyen kişi tarafından {saat} saat içinde silinebilir; "
            "sonrası için kapatma yetkisi (servis.kapat) gerekir."
        )


async def _servis_eki_silindi(db: AsyncSession, user: User, bilgi: dict, clock) -> None:
    """EK_SIL olayı dosya adı ve sha256'yı tutar: dosya gitse de iz kalır (K19)."""
    from app.models import ServiceOrder

    so = await db.get(ServiceOrder, bilgi["entity_id"])
    await _olay(
        db,
        so,
        "EK_SIL",
        "Ek silindi",
        bilgi["dosya"],
        user=user,
        clock=clock,
        veri={
            "ek_id": bilgi["ek_id"],
            "tur": bilgi["tur"],
            "dosya": bilgi["dosya"],
            "sha256": bilgi["sha256"],
        },
    )


kural_kaydet(
    "service_orders",
    EkKurali(
        yukleme_oncesi=_servis_eki_yukleme_oncesi,
        yuklendi=_servis_eki_yuklendi,
        silme_oncesi=_servis_eki_silme_oncesi,
        silindi=_servis_eki_silindi,
    ),
)
