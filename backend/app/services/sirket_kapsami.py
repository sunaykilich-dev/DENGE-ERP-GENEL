"""Şirket bazlı ürün / cihaz / depo / hat görünürlüğü (migration fcl000000001).

Sahip kararı (2026-11-23): her şirket yalnız kendi kalemlerini görür. Kurallar:

- **Ürün:** `products.sirket` NULL = ORTAK (her şirkette görünür); dolu ise
  yalnız o şirket etkinken görünür.
- **Cihaz:** ayrı sütunu yoktur; şirketi ÜRÜNÜNÜN şirketidir (ortak ürünün
  cihazı herkese görünür).
- **Depo:** şirketi biriminin şirketidir (`birim_sirketleri`); birimsiz depo
  ortaktır. Etkin şirketin birimleri `sirketler.etkin_birimler`'den gelir.
- **Hat:** `sim_cards.sirket` — yalnız etkin şirketin hatları görünür.

Süzgeç kaynağı `sirketler.etkin_birimler` / `sirketler.aktif_sirket`'tir ve
MODÜL ÖZNİTELİĞİ olarak çağrılır (testler conftest'te süzgeçsiz sürüme
çevirir). `etkin_birimler(user) is None` = bilinçli süzgeçsiz kullanıcı →
koşul yok (`None`). Bağlanmamış / şirketsiz kullanıcı fail-closed: yalnız
ortak ürün/cihaz/depo görünür, hiçbir hat görünmez.

Koşul fonksiyonları `None` (süzgeç yok) ya da SQL ifadesi döner; `..._mi`
fonksiyonları tek kayıt içindir (başka şirketin kaydı yokmuş gibi 404).
"""

from sqlalchemy import ColumnElement, exists, false, or_, select

from app.models import Device, Product, SimCard, User, Warehouse
from app.services import sirketler


def _suzgec_yok(user: User) -> bool:
    return sirketler.etkin_birimler(user) is None


def _aktif(user: User) -> str | None:
    return sirketler.aktif_sirket(user)


# --- Ürün ---------------------------------------------------------------------


def urun_kosulu(user: User, sutun=Product.sirket) -> ColumnElement[bool] | None:
    """Ortak ürün ya da etkin şirketin ürünü."""
    if _suzgec_yok(user):
        return None
    aktif = _aktif(user)
    if aktif is None:
        return sutun.is_(None)
    return or_(sutun.is_(None), sutun == aktif)


def urun_gorunur_mu(user: User, sirket: str | None) -> bool:
    if _suzgec_yok(user) or sirket is None:
        return True
    return sirket == _aktif(user)


# --- Cihaz (ürünün şirketi) ---------------------------------------------------


def cihaz_kosulu(user: User) -> ColumnElement[bool] | None:
    """Cihaz sorgusuna eklenecek koşul (Product join'i GEREKMEZ: EXISTS)."""
    kosul = urun_kosulu(user)
    if kosul is None:
        return None
    return exists(select(Product.id).where(Product.id == Device.product_id, kosul))


async def cihaz_gorunur_mu(db, user: User, cihaz: Device | None) -> bool:
    if cihaz is None:
        return False
    if _suzgec_yok(user):
        return True
    sirket = await db.scalar(select(Product.sirket).where(Product.id == cihaz.product_id))
    return urun_gorunur_mu(user, sirket)


# --- Depo (birimin şirketi) ---------------------------------------------------


def depo_kosulu(user: User, sutun=Warehouse.birim) -> ColumnElement[bool] | None:
    """Ortak (birimsiz) depo ya da etkin şirketin birim deposu."""
    birimler = sirketler.etkin_birimler(user)
    if birimler is None:
        return None
    if not birimler:
        return sutun.is_(None)
    return or_(sutun.is_(None), sutun.in_(sorted(birimler)))


def depo_gorunur_mu(user: User, depo: Warehouse | None) -> bool:
    if depo is None:
        return False
    birimler = sirketler.etkin_birimler(user)
    if birimler is None or depo.birim is None:
        return True
    return depo.birim in birimler


def depo_id_kosulu(user: User, sutun) -> ColumnElement[bool] | None:
    """Depo kimliği taşıyan sütun için: NULL (depo seçilmemiş) ya da görünür depo."""
    kosul = depo_kosulu(user)
    if kosul is None:
        return None
    return or_(sutun.is_(None), sutun.in_(select(Warehouse.id).where(kosul)))


# --- Hat ----------------------------------------------------------------------


def hat_kosulu(user: User, sutun=SimCard.sirket) -> ColumnElement[bool] | None:
    """Yalnız etkin şirketin hatları; şirketsiz kullanıcı hiçbir hat görmez."""
    if _suzgec_yok(user):
        return None
    aktif = _aktif(user)
    if aktif is None:
        return false()
    return sutun == aktif


def hat_gorunur_mu(user: User, hat: SimCard | None) -> bool:
    if hat is None:
        return False
    if _suzgec_yok(user):
        return True
    aktif = _aktif(user)
    return aktif is not None and hat.sirket == aktif


def yeni_hat_sirketi(user: User) -> str | None:
    """Yeni hatta yazılacak şirket: etkin şirket. Süzgeçsiz kullanıcıda etkin
    şirket yoksa model varsayılanı (MOBİLİTE) kalır."""
    return _aktif(user)


def uygula(stmt, *kosullar: ColumnElement[bool] | None):
    """`None` olmayan koşulları sorguya ekler."""
    for kosul in kosullar:
        if kosul is not None:
            stmt = stmt.where(kosul)
    return stmt
