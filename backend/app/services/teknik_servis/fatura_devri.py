"""Servis işlerinin "Faturaya iletildi" devir işareti (E07-26, TS-197).

**Logo entegrasyonu DEĞİLDİR.** Muhasebe devri bir işarettir: kabul edilmiş
birimli teklifi olan ya da elle/sözleşme/teklif kaynaklı geliri (> 0) olan
kapanmış (Tamamlandı/Kapatıldı) servis işi "bekleyen" listesine düşer;
`tahsilat.yaz` sahibi işaretleyince `service_order_financials.fatura_iletildi_at/by`
yazılır ve iş listeden düşer, "İletilenler"de kim/ne zaman bilgisiyle görünür.

**Gelir kilidi (E07-D04):** işaretten sonra gelir, diğer maliyet ve teklif
gelir aktarımı `maliyet._kilit` ile 409'dur (kural `maliyet.py`'de, burada
yalnız işaret yazılır). Geri alma gerekçe ister ve denetime yazılır.

**Toplu işaret bütündür:** bir kimlik kapsam dışı ya da uygun değilse
istek TAMAMEN 409 ile reddedilir ve sorunlu kimlikler yazılır; hiçbir satır
işaretlenmez (kısmi işaret muhasebede çift faturaya yol açardı).

**Kapsam:** servis işi kapsamı (`kapsam_isler`) — liste, sayı ve Excel aynı
sorgudan. Tutar anahtarı yalnız `teklif.gor` ya da `maliyet.gor` sahibine
döner (yoksa anahtar YOK).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, exists, func, or_, select

from app.models import Account, Quote, QuoteLine, ServiceOrder, User
from app.models.rbac import BIRIM_KODLARI
from app.models.servis_maliyet import ServiceOrderFinancial
from app.models.teknik_servis import DURUM_GRUPLARI
from app.services import audit
from app.services.teknik_servis import kapsam
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_gun, yerel_gun_araligi

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

DEVIR_DURUMLARI = ("bekleyen", "iletildi")
GELIR_KAYNAKLARI_DEVIR = ("ELLE", "SOZLESME", "TEKLIF")
AZAMI_TOPLU = 200
NOT_UZUNLUGU = 300
_COZULDU = sorted(DURUM_GRUPLARI["COZULDU"])


class FaturaDevriHatasi(ServisHatasi):
    """Uygun olmayan / kapsam dışı iş içeren toplu işaret, işaretsiz geri alma → 409."""

    def __init__(self, mesaj: str, *, sorunlu: list[int] | None = None) -> None:
        super().__init__(mesaj)
        self.sorunlu = sorunlu or []


def tutar_gorur_mu(user: User) -> bool:
    return user.has("teklif.gor") or user.has("maliyet.gor")


def _kapanis_ani():
    return func.coalesce(ServiceOrder.completed_at, ServiceOrder.closed_at)


def _kabul_teklif_var():
    """İşe bağlı (doğrudan ya da güncel sürüm kalemiyle) KABUL birimli teklif."""
    return exists().where(
        Quote.is_deleted.is_(False),
        Quote.birim.is_not(None),
        Quote.status == "KABUL",
        or_(
            Quote.service_order_id == ServiceOrder.id,
            exists().where(
                QuoteLine.version_id == Quote.current_version_id,
                QuoteLine.service_order_id == ServiceOrder.id,
            ),
        ),
    )


def _gelirli():
    return and_(
        ServiceOrderFinancial.gelir.is_not(None),
        ServiceOrderFinancial.gelir > 0,
        ServiceOrderFinancial.gelir_kaynagi.in_(GELIR_KAYNAKLARI_DEVIR),
    )


def uygun_kosulu():
    """Devre uygun iş: kapanmış ve (kabul teklifli ya da gelirli)."""
    return and_(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.status.in_(_COZULDU),
        or_(_kabul_teklif_var(), _gelirli()),
    )


@dataclass
class DevirSuzgeci:
    durum: str = "bekleyen"
    donem: str | None = None  # YYYY-AA: bekleyende kapanış ayı, iletildide devir ayı
    birim: str | None = None
    musteri_id: int | None = None


def _donem_araligi(donem: str) -> tuple[Any, Any]:
    try:
        yil, ay = (int(p) for p in donem.split("-"))
        bas = date(yil, ay, 1)
    except (ValueError, TypeError) as exc:
        raise ServisGirdiHatasi("Dönem YYYY-AA biçiminde olmalı") from exc
    sonraki = (bas + timedelta(days=32)).replace(day=1)
    return yerel_gun_araligi(bas)[0], yerel_gun_araligi(sonraki)[0]


def liste_sorgusu(user: User, s: DevirSuzgeci) -> Select:
    """Bekleyen ya da iletilen işler (kapsamlı; açık ORDER BY)."""
    if s.durum not in DEVIR_DURUMLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen devir durumu: {s.durum}")
    if s.birim and s.birim not in BIRIM_KODLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {s.birim}")
    iletti = User.__table__.alias("iletti")
    stmt = (
        select(
            ServiceOrder,
            Account.title.label("musteri"),
            ServiceOrderFinancial.gelir,
            ServiceOrderFinancial.gelir_kaynagi,
            ServiceOrderFinancial.fatura_iletildi_at,
            ServiceOrderFinancial.fatura_notu,
            iletti.c.full_name.label("iletti"),
            _kapanis_ani().label("kapanis"),
        )
        .outerjoin(Account, Account.id == ServiceOrder.customer_id)
        .outerjoin(ServiceOrderFinancial, ServiceOrderFinancial.service_order_id == ServiceOrder.id)
        .outerjoin(iletti, iletti.c.id == ServiceOrderFinancial.fatura_iletildi_by)
        .where(uygun_kosulu())
    )
    if s.durum == "bekleyen":
        stmt = stmt.where(ServiceOrderFinancial.fatura_iletildi_at.is_(None)).order_by(
            _kapanis_ani(), ServiceOrder.id
        )
        zaman = _kapanis_ani()
    else:
        stmt = stmt.where(ServiceOrderFinancial.fatura_iletildi_at.is_not(None)).order_by(
            ServiceOrderFinancial.fatura_iletildi_at.desc(), ServiceOrder.id
        )
        zaman = ServiceOrderFinancial.fatura_iletildi_at
    if s.donem:
        bas, bit = _donem_araligi(s.donem)
        stmt = stmt.where(zaman >= bas, zaman < bit)
    if s.birim:
        stmt = stmt.where(ServiceOrder.birim == s.birim)
    if s.musteri_id is not None:
        stmt = stmt.where(ServiceOrder.customer_id == s.musteri_id)
    return kapsam.kapsam_isler(stmt, user, ServiceOrder.id)


async def _teklif_nolari(db: AsyncSession, so_idler: list[int]) -> dict[int, list[str]]:
    if not so_idler:
        return {}
    sonuc: dict[int, list[str]] = {}
    dogrudan = select(Quote.service_order_id, Quote.quote_no).where(
        Quote.is_deleted.is_(False),
        Quote.birim.is_not(None),
        Quote.status == "KABUL",
        Quote.service_order_id.in_(so_idler),
    )
    kalem = (
        select(QuoteLine.service_order_id, Quote.quote_no)
        .join(Quote, Quote.current_version_id == QuoteLine.version_id)
        .where(
            Quote.is_deleted.is_(False),
            Quote.birim.is_not(None),
            Quote.status == "KABUL",
            QuoteLine.service_order_id.in_(so_idler),
        )
    )
    for so_id, no in [*(await db.execute(dogrudan)).all(), *(await db.execute(kalem)).all()]:
        liste = sonuc.setdefault(so_id, [])
        if no not in liste:
            liste.append(no)
    return sonuc


async def satirlar(db: AsyncSession, user: User, kayitlar: list[Any]) -> list[dict[str, Any]]:
    """Liste satırları. Tutar anahtarı yalnız `teklif.gor`/`maliyet.gor` ile."""
    nolar = await _teklif_nolari(db, [r[0].id for r in kayitlar])
    tutar = tutar_gorur_mu(user)
    sonuc = []
    for r in kayitlar:
        so: ServiceOrder = r[0]
        d: dict[str, Any] = {
            "so_id": so.id,
            "so_no": so.so_no,
            "birim": so.birim,
            "tur": so.tur,
            "status": so.status,
            "musteri": r.musteri,
            "kapanis_tarihi": yerel_gun(r.kapanis).isoformat() if r.kapanis else None,
            "gelir_kaynagi": r.gelir_kaynagi,
            "teklifler": nolar.get(so.id, []),
            "fatura_iletildi_at": r.fatura_iletildi_at,
            "iletti": r.iletti,
            "fatura_notu": r.fatura_notu,
        }
        if tutar:
            d["tutar"] = Decimal(str(r.gelir)) if r.gelir is not None else None
        sonuc.append(d)
    return sonuc


async def _finans_ac(db: AsyncSession, so_id: int, user_id: int) -> ServiceOrderFinancial:
    fin = await db.scalar(
        select(ServiceOrderFinancial)
        .where(ServiceOrderFinancial.service_order_id == so_id)
        .with_for_update()
    )
    if fin is None:
        fin = ServiceOrderFinancial(service_order_id=so_id, created_by=user_id, updated_by=user_id)
        db.add(fin)
        await db.flush()
    return fin


def _not(deger: str | None) -> str | None:
    metin = (deger or "").strip() or None
    if metin is not None and len(metin) > NOT_UZUNLUGU:
        raise ServisGirdiHatasi(f"Not en çok {NOT_UZUNLUGU} karakter olabilir")
    return metin


async def isaretle(
    db: AsyncSession,
    user: User,
    is_idler: list[int],
    *,
    not_: str | None,
    clock: Clock,
    ip: str | None = None,
) -> list[int]:
    """Toplu "Faturaya iletildi" işareti. Bir kimlik bile uygun/kapsamda
    değilse tamamı 409 (`FaturaDevriHatasi.sorunlu`); hiçbir satır yazılmaz."""
    idler = sorted({int(i) for i in is_idler})
    if not idler:
        raise ServisGirdiHatasi("En az bir iş seçilmeli")
    if len(idler) > AZAMI_TOPLU:
        raise ServisGirdiHatasi(f"Tek seferde en çok {AZAMI_TOPLU} iş işaretlenebilir")
    metin = _not(not_)
    uygunlar = set(
        (
            await db.scalars(
                liste_sorgusu(user, DevirSuzgeci(durum="bekleyen"))
                .with_only_columns(ServiceOrder.id)
                .where(ServiceOrder.id.in_(idler))
                .order_by(None)
            )
        ).all()
    )
    sorunlu = [i for i in idler if i not in uygunlar]
    if sorunlu:
        raise FaturaDevriHatasi(
            "Seçilen işlerin bazıları faturaya iletilmeye uygun değil ya da bulunamadı; "
            "hiçbiri işaretlenmedi",
            sorunlu=sorunlu,
        )
    simdi = clock.now()
    for so_id in idler:
        fin = await _finans_ac(db, so_id, user.id)
        if fin.fatura_iletildi_at is not None:  # eşzamanlı işaret
            raise FaturaDevriHatasi("İş bu arada faturaya iletildi; yenileyin", sorunlu=[so_id])
        fin.fatura_iletildi_at = simdi
        fin.fatura_iletildi_by = user.id
        fin.fatura_notu = metin
        fin.updated_by = user.id
        await audit.log_change(db, fin, "fatura.iletildi", user_id=user.id, ip=ip)
    await db.flush()
    return idler


async def geri_al(
    db: AsyncSession,
    user: User,
    so: ServiceOrder,
    *,
    gerekce: str,
    ip: str | None = None,
) -> ServiceOrderFinancial:
    """Devri geri alır (gerekçe zorunlu, 400). İşaretsiz iş → 409."""
    metin = _not(gerekce)
    if metin is None:
        raise ServisGirdiHatasi("Geri alma gerekçesi zorunlu")
    fin = await db.scalar(
        select(ServiceOrderFinancial)
        .where(ServiceOrderFinancial.service_order_id == so.id)
        .with_for_update()
    )
    if fin is None or fin.fatura_iletildi_at is None:
        raise FaturaDevriHatasi("İş faturaya iletilmemiş", sorunlu=[so.id])
    eski = {
        "fatura_iletildi_at": fin.fatura_iletildi_at.isoformat(),
        "fatura_iletildi_by": fin.fatura_iletildi_by,
        "fatura_notu": fin.fatura_notu,
    }
    fin.fatura_iletildi_at = None
    fin.fatura_iletildi_by = None
    fin.fatura_notu = None
    fin.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        "service_order_financials",
        "fatura.geri_al",
        entity_id=fin.id,
        old_value=eski,
        new_value={"so_id": so.id, "gerekce": metin},
        user_id=user.id,
        ip=ip,
    )
    return fin
