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


def icerik_dogrula(entity: str, icerik: bytes, mime: str) -> None:
    """Teknik servis eklerinde içerik beyanla uyuşmuyorsa `DepoHatasi` (→ 422)."""
    if entity not in KAPSAM_ZORUNLU:
        return
    if not _uyusuyor(icerik, mime):
        raise DepoHatasi("Dosya içeriği türüyle uyuşmuyor; dosya bozuk ya da uzantısı yanlış")
