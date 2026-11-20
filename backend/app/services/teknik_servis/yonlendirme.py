"""Satış/kiralama talebinin teknik servis müdürüne ve birime yönlendirilmesi.

KARARLAR 2026-11-20 §5–6:

- Onaylı satıştan açılan kurulum/teslimat işi ve onaylanan kiralama talebi
  teknik servis müdürüne düşer (MUDURDE).
- Müdür (`servis.yonlendir`) birimin yöneticisine/şefine yönlendirir
  (BIRIMDE). Hedef kişi o birimin üyesi olmalı ve `servis.planla` iznine
  sahip olmalı.
- Planlama kilitlenmez (G1.9). İş PLANLAMADA'dan çıkınca ya da kiralama
  TALEP'ten çıkınca kayıt "planlandı" sayılır ve açık listeden düşer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, Rental, ServiceOrder, ServisYonlendirme, User, UserUnit
from app.services import audit, sirketler
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

YONLENDIRME_IZNI = "servis.yonlendir"
_IS_BEKLEYEN = ("MUSTERI_TALEBI", "PLANLAMADA")


class YonlendirmeBulunamadi(ServisHatasi):
    pass


def _bos(x: str | None) -> str | None:
    return (x or "").strip() or None


async def is_icin_olustur(
    db: AsyncSession,
    so: ServiceOrder,
    *,
    sozlesme_detay: str | None,
    talep_notu: str | None,
    user: User | None,
) -> ServisYonlendirme:
    kayit = ServisYonlendirme(
        kaynak="SATIS",
        service_order_id=so.id,
        birim=so.birim,
        sozlesme_detay=_bos(sozlesme_detay),
        talep_notu=_bos(talep_notu),
        created_by=user.id if user is not None else None,
    )
    db.add(kayit)
    await db.flush()
    return kayit


async def kiralama_icin_olustur(
    db: AsyncSession,
    kiralama: Rental,
    *,
    sozlesme_detay: str | None,
    talep_notu: str | None,
    user: User,
    ip: str | None = None,
) -> ServisYonlendirme:
    """Kiralama talebini onaylayıp teknik servise yönlendirir (bir kez)."""
    if kiralama.status in ("IPTAL", "KAPANDI"):
        raise ServisHatasi("Kapanmış ya da iptal edilmiş kiralama yönlendirilemez")
    var = await db.scalar(
        select(ServisYonlendirme.id).where(ServisYonlendirme.rental_id == kiralama.id)
    )
    if var is not None:
        raise ServisHatasi("Bu kiralama talebi zaten onaylanıp teknik servise yönlendirildi")
    kayit = ServisYonlendirme(
        kaynak="KIRALAMA",
        rental_id=kiralama.id,
        birim=kiralama.birim,
        sozlesme_detay=_bos(sozlesme_detay),
        talep_notu=_bos(talep_notu),
        created_by=user.id,
    )
    db.add(kayit)
    await db.flush()
    await audit.log(
        db,
        "rentals",
        "kiralama.talep_onay",
        entity_id=kiralama.id,
        new_value={"yonlendirme_id": kayit.id},
        user_id=user.id,
        ip=ip,
    )
    return kayit


def _planlandi(kayit: ServisYonlendirme, so: ServiceOrder | None, k: Rental | None) -> bool:
    if so is not None:
        return so.status not in _IS_BEKLEYEN
    if k is not None:
        return k.status != "TALEP"
    return False


@dataclass
class Suzgec:
    acik: bool = True


async def liste(db: AsyncSession, user: User, s: Suzgec) -> list[dict[str, Any]]:
    """Müdür hepsini (etkin şirketin birimleri), şef kendisine yönlendirilenleri görür."""
    stmt = (
        select(ServisYonlendirme, ServiceOrder, Rental)
        .outerjoin(ServiceOrder, ServiceOrder.id == ServisYonlendirme.service_order_id)
        .outerjoin(Rental, Rental.id == ServisYonlendirme.rental_id)
        .order_by(ServisYonlendirme.id.desc())
    )
    if not user.has(YONLENDIRME_IZNI):
        stmt = stmt.where(ServisYonlendirme.hedef_user_id == user.id)
    birimler = sirketler.etkin_birimler(user)
    if birimler is not None:
        stmt = stmt.where(ServisYonlendirme.birim.in_(birimler))
    if s.acik:
        stmt = stmt.where(
            or_(
                and_(
                    ServisYonlendirme.service_order_id.is_not(None),
                    ServiceOrder.status.in_(_IS_BEKLEYEN),
                ),
                and_(ServisYonlendirme.rental_id.is_not(None), Rental.status == "TALEP"),
            )
        )
    satirlar = (await db.execute(stmt.limit(500))).all()
    hesap_idler = {x.customer_id for _, so, k in satirlar for x in (so, k) if x is not None}
    kisi_idler = {y.hedef_user_id for y, _, _ in satirlar if y.hedef_user_id}
    hesaplar = (
        dict(
            (
                await db.execute(
                    select(Account.id, Account.title).where(Account.id.in_(hesap_idler))
                )
            ).all()
        )
        if hesap_idler
        else {}
    )
    kisiler = (
        dict(
            (await db.execute(select(User.id, User.full_name).where(User.id.in_(kisi_idler)))).all()
        )
        if kisi_idler
        else {}
    )
    cikti = []
    for y, so, k in satirlar:
        kaynak = so if so is not None else k
        cikti.append(
            {
                "id": y.id,
                "version": y.version,
                "kaynak": y.kaynak,
                "birim": y.birim,
                "durum": y.durum,
                "planlandi": _planlandi(y, so, k),
                "service_order_id": y.service_order_id,
                "so_no": so.so_no if so is not None else None,
                "is_durumu": so.status if so is not None else None,
                "rental_id": y.rental_id,
                "rental_no": k.rental_no if k is not None else None,
                "kiralama_durumu": k.status if k is not None else None,
                "konu": so.konu if so is not None else (k.proje_adi if k is not None else None),
                "musteri": hesaplar.get(kaynak.customer_id) if kaynak is not None else None,
                "sozlesme_detay": y.sozlesme_detay,
                "talep_notu": y.talep_notu,
                "hedef_user_id": y.hedef_user_id,
                "hedef_ad": kisiler.get(y.hedef_user_id) if y.hedef_user_id else None,
                "mudur_notu": y.mudur_notu,
                "yonlendirme_at": y.yonlendirme_at,
                "created_at": y.created_at,
            }
        )
    return cikti


async def adaylar(db: AsyncSession, birim: str) -> list[dict[str, Any]]:
    """Birimin üyesi ve planlama yetkili aktif kişiler (şef / birim yöneticisi)."""
    kisiler = (
        (
            await db.scalars(
                select(User)
                .join(UserUnit, UserUnit.user_id == User.id)
                .where(UserUnit.birim == birim, User.is_active.is_(True), User.giris_acik.is_(True))
                .order_by(User.full_name)
            )
        )
        .unique()
        .all()
    )
    sonuc = []
    for u in kisiler:
        await db.refresh(u, ["role", "izin_istisnalari"])
        if u.has("servis.planla"):
            sonuc.append({"id": u.id, "ad": u.full_name, "unvan": u.unvan})
    return sonuc


async def yonlendir(
    db: AsyncSession,
    kayit: ServisYonlendirme,
    hedef_user_id: int,
    *,
    not_: str | None,
    version: int,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServisYonlendirme:
    if kayit.version != version:
        raise ServisHatasi("Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin")
    if hedef_user_id not in {a["id"] for a in await adaylar(db, kayit.birim)}:
        raise ServisGirdiHatasi(
            "Seçilen kişi bu birimin yöneticisi/şefi değil "
            "(birim üyeliği ve planlama yetkisi gerekir)"
        )
    kayit.hedef_user_id = hedef_user_id
    kayit.durum = "BIRIMDE"
    kayit.yonlendiren_id = user.id
    kayit.yonlendirme_at = clock.now()
    kayit.mudur_notu = _bos(not_)
    kayit.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        "servis_yonlendirmeleri",
        "servis.yonlendir",
        entity_id=kayit.id,
        new_value={"hedef_user_id": hedef_user_id, "birim": kayit.birim},
        user_id=user.id,
        ip=ip,
    )
    return kayit


async def kapsamli(db: AsyncSession, user: User, kayit_id: int) -> ServisYonlendirme:
    kayit = await db.get(ServisYonlendirme, kayit_id)
    birimler = sirketler.etkin_birimler(user)
    if kayit is None or (birimler is not None and kayit.birim not in birimler):
        raise YonlendirmeBulunamadi("Yönlendirme bulunamadı")
    return kayit


async def is_icin(db: AsyncSession, so_id: int) -> ServisYonlendirme | None:
    return await db.scalar(
        select(ServisYonlendirme).where(ServisYonlendirme.service_order_id == so_id)
    )
