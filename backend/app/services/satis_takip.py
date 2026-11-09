"""Satış takibi: keşif isteği, satış sonrası servis işleri, Tekliflerim ve
Satışlarımın durumu (KARARLAR 2026-11-09 S2.2, S2.3, S3, S4.1, S4.2).

**Satış rolü servis işi AÇMAZ** (S3.1): yalnız tekliften keşif ister
(`teklif.kesif_iste`) ve kabul edilen teklif/siparişten kurulum ya da
teslimat işi açar (`teklif.servis_isi_ac`). İş her zaman PLANLAMADA doğar;
planlamayı birim şefi normal planlama ekranında yapar (ayrı ekran yok).
Öncelik yalnız NORMAL/YUKSEK: satıştan gelen iş arızanın önüne geçmez
(KRITIK yok); türler PROJE kategorisindedir, SLA ölçülmez.

**Aşama (S4.2)** servis işi durumundan türetilir; satışçıya iş durumunun
ayrıntısı değil anlaşılır aşaması gösterilir. Maliyet hiçbir çıktıda YOK
(`maliyet.gor` gerekmez çünkü hiç taşınmaz).

**Kapsam:** teklif `quotes.teklif_al` (okuma/yazma kapsamı), sipariş
`orders` ekranının kuralıyla (KENDI_MUSTERILERI → yalnız kendi siparişi).
Bağlı işin satışçıya gösterilen özeti teklif/sipariş kapsamından okunur:
satışçının servis işleri ekranında o işi görmesi gerekmez.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select

from app.clock import Clock
from app.models import (
    Account,
    Address,
    Attachment,
    Order,
    Quote,
    QuoteVersion,
    SatisIsBagi,
    ServiceHold,
    ServiceHoldReason,
    ServiceOrder,
    ServicePlan,
    ServiceResult,
    User,
)
from app.models.quote import KAYIP_NEDENLERI
from app.models.rbac import BIRIM_KODLARI
from app.permissions import BIRIMLER, SCOPE_OWN_CUSTOMERS
from app.services import audit, sirketler
from app.services import quotes as teklif_svc
from app.services import settings as ayar_svc
from app.services.quotes import (
    TeklifGirdiHatasi,
    TeklifKapsamDisi,
    TeklifKuralHatasi,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# --- Sözlükler ---------------------------------------------------------------------

# S3.1: teklifte birim yoksa satışçı bu ikisinden birini seçer.
KESIF_BIRIMLERI = ("HABERLESME", "GUVENLIK")
# S3.2: KRITIK seçilemez.
SATIS_ONCELIKLERI = ("NORMAL", "YUKSEK")
SATIS_IS_TURLERI = ("KURULUM", "TESLIMAT")
KESIF_VARSAYILAN_IS_GUNU = 5
# Keşif teklif hâlâ hazırlanırken/müşteri yanıtı beklenirken istenir.
KESIF_ISTENEBILIR = (
    "TASLAK",
    "ONAY_BEKLIYOR",
    "ONAYLANDI",
    "GONDERILDI",
    "GORUNTULENDI",
    "REVIZE_EDILDI",
)
TEKLIF_KABUL = ("KABUL", "SIPARISE_DONUSTU")
SIPARIS_IS_ACILABILIR = ("ONAYLANDI", "REZERVE", "KISMI_SEVK", "SEVK_EDILDI", "TAMAMLANDI")
_KAPALI_IS = ("TAMAMLANDI", "KAPATILDI", "IPTAL")

# S4.2 aşamaları. Karar metnindeki beşe (Planlandı, Yolda, Sahada, Tamamlandı,
# Askıda) iki zorunlu ek: henüz planlanmamış iş ve iptal edilen iş.
ASAMA_ADLARI = {
    "PLANLAMA_BEKLIYOR": "Planlama bekliyor",
    "PLANLANDI": "Planlandı",
    "YOLDA": "Yolda",
    "SAHADA": "Sahada",
    "ASKIDA": "Askıda",
    "TAMAMLANDI": "Tamamlandı",
    "IPTAL": "İptal",
}
_DURUM_ASAMA = {
    "MUSTERI_TALEBI": "PLANLAMA_BEKLIYOR",
    "PLANLAMADA": "PLANLAMA_BEKLIYOR",
    "TEKRAR_ACILDI": "PLANLAMA_BEKLIYOR",
    "PLANLANDI": "PLANLANDI",
    "YOLA_CIKILDI": "YOLDA",
    "SAHADA": "SAHADA",
    "ISLEMDE": "SAHADA",
    "ATOLYEDE": "SAHADA",
    "BEKLEMEDE": "ASKIDA",
    "TAMAMLANDI": "TAMAMLANDI",
    "KAPATILDI": "TAMAMLANDI",
    "IPTAL": "IPTAL",
}
BAG_ADLARI = {
    "KESIF": "Keşif",
    "KURULUM": "Kurulum",
    "TESLIMAT": "Teslimat",
    "TEKLIF_ISI": "Teklifin işi",
}


def asama(durum: str) -> str:
    return _DURUM_ASAMA.get(durum, "PLANLAMA_BEKLIYOR")


def is_gunu_ekle(gun: date, adet: int) -> date:
    from app.services.teknik_servis.maliyet import is_gunu_ekle as _ekle

    return _ekle(gun, adet)


def kesif_hedef_tarihi(bugun: date, gecerlilik: date | None) -> date:
    """S3.2: varsayılan 5 iş günü; teklifin geçerliliği daha erkense o gün
    (keşif teklif geçerliyken bitsin). Geçmiş geçerlilik varsayılanı bozmaz."""
    varsayilan = is_gunu_ekle(bugun, KESIF_VARSAYILAN_IS_GUNU)
    if gecerlilik is not None and bugun < gecerlilik < varsayilan:
        return gecerlilik
    return varsayilan


# --- Bağlı işler (S4.2) ------------------------------------------------------------


async def _is_ozetleri(
    db: AsyncSession, satirlar: list[tuple[int, str, Any]]
) -> list[dict[str, Any]]:
    """(so_id, bag_turu, hedef_tarih) → satışçıya gösterilen iş özeti (fiyatsız)."""
    if not satirlar:
        return []
    idler = list(dict.fromkeys(s[0] for s in satirlar))
    isler = {
        so.id: so
        for so in (
            await db.scalars(
                select(ServiceOrder).where(
                    ServiceOrder.id.in_(idler), ServiceOrder.is_deleted.is_(False)
                )
            )
        ).all()
    }
    planlar = dict(
        (
            await db.execute(
                select(ServicePlan.service_order_id, ServicePlan.plan_date).where(
                    ServicePlan.service_order_id.in_(idler),
                    ServicePlan.is_active.is_(True),
                    ServicePlan.is_deleted.is_(False),
                )
            )
        ).all()
    )
    beklemeler = {
        so_id: f"{ad}: {aciklama}" if aciklama else ad
        for so_id, ad, aciklama in (
            await db.execute(
                select(ServiceHold.service_order_id, ServiceHoldReason.ad, ServiceHold.aciklama)
                .join(ServiceHoldReason, ServiceHoldReason.kod == ServiceHold.neden)
                .where(ServiceHold.service_order_id.in_(idler), ServiceHold.released_at.is_(None))
            )
        ).all()
    }
    from app.services.teknik_servis.is_emirleri import DURUM_ADLARI, TUR_ADLARI

    sonuc = []
    goruldu: set[int] = set()
    for so_id, bag_turu, hedef in satirlar:
        so = isler.get(so_id)
        if so is None or so_id in goruldu:
            continue
        goruldu.add(so_id)
        a = asama(so.status)
        sonuc.append(
            {
                "service_order_id": so.id,
                "so_no": so.so_no,
                "bag_turu": bag_turu,
                "bag_adi": BAG_ADLARI.get(bag_turu, bag_turu),
                "tur": so.tur,
                "tur_adi": TUR_ADLARI.get(so.tur, so.tur),
                "birim": so.birim,
                "birim_adi": BIRIMLER.get(so.birim, so.birim),
                "oncelik": so.oncelik,
                "durum": so.status,
                "durum_adi": DURUM_ADLARI.get(so.status, so.status),
                "asama": a,
                "asama_adi": ASAMA_ADLARI[a],
                "askida_nedeni": beklemeler.get(so.id) if a == "ASKIDA" else None,
                "plan_tarihi": planlar.get(so.id),
                "hedef_tarih": hedef,
                "tamamlanma": so.completed_at,
                "acilis": so.created_at,
            }
        )
    return sonuc


async def teklif_bagli_isler(db: AsyncSession, t: Quote) -> list[dict[str, Any]]:
    """Teklife bağlı TÜM işler: bağ tablosu (keşif, kurulum, teslimat; teklifin
    siparişinden açılanlar dahil) + eski tek bağ `quotes.service_order_id`."""
    satirlar: list[tuple[int, str, Any]] = []
    if t.service_order_id:
        satirlar.append((t.service_order_id, "TEKLIF_ISI", None))
    for b in (
        await db.scalars(
            select(SatisIsBagi).where(SatisIsBagi.quote_id == t.id).order_by(SatisIsBagi.id)
        )
    ).all():
        satirlar.append((b.service_order_id, b.bag_turu, b.hedef_tarih))
    return await _is_ozetleri(db, satirlar)


async def siparis_bagli_isler(db: AsyncSession, s: Order) -> list[dict[str, Any]]:
    """Siparişe bağlı işler + siparişin teklifinden açılmış işler (keşif dahil)."""
    kosul = SatisIsBagi.order_id == s.id
    if s.quote_id:
        kosul = or_(kosul, SatisIsBagi.quote_id == s.quote_id)
    satirlar = [
        (b.service_order_id, b.bag_turu, b.hedef_tarih)
        for b in (await db.scalars(select(SatisIsBagi).where(kosul).order_by(SatisIsBagi.id))).all()
    ]
    if s.quote_id:
        t = await db.get(Quote, s.quote_id)
        if t is not None and t.service_order_id:
            satirlar.insert(0, (t.service_order_id, "TEKLIF_ISI", None))
    return await _is_ozetleri(db, satirlar)


# --- Sipariş kapsamı (orders ekranının kuralı) -----------------------------------------


async def siparis_al(db: AsyncSession, siparis_id: int, user: User) -> Order:
    s = await db.get(Order, siparis_id)
    if s is None or s.is_deleted:
        raise TeklifKapsamDisi("Sipariş bulunamadı")
    if user.role is not None and user.role.scope == SCOPE_OWN_CUSTOMERS and s.owner_id != user.id:
        raise TeklifKapsamDisi("Sipariş bulunamadı")
    return s


# --- İş açma ortak kuralları ----------------------------------------------------------


def _oncelik(oncelik: str) -> str:
    if oncelik not in SATIS_ONCELIKLERI:
        raise TeklifGirdiHatasi("Öncelik yalnız Normal ya da Yüksek olabilir (Kritik seçilemez)")
    return oncelik


def _hedef(hedef: date | None, bugun: date) -> date | None:
    if hedef is not None and hedef < bugun:
        raise TeklifGirdiHatasi("Hedef tarih geçmiş bir gün olamaz")
    return hedef


async def _adres(db: AsyncSession, customer_id: int, address_id: int | None) -> int | None:
    if address_id is None:
        return None
    a = await db.get(Address, address_id)
    if a is None or a.account_id != customer_id:
        raise TeklifGirdiHatasi("Adres bu müşteriye ait değil")
    return address_id


@dataclass
class IsIstegi:
    birim: str | None
    oncelik: str = "NORMAL"
    hedef_tarih: date | None = None
    aciklama: str | None = None
    address_id: int | None = None


async def _is_ac(
    db: AsyncSession,
    *,
    tur: str,
    birim: str,
    customer_id: int,
    address_id: int | None,
    contact_id: int | None,
    oncelik: str,
    konu: str,
    aciklama: str,
    user: User,
    clock: Clock,
) -> ServiceOrder:
    from app.services.teknik_servis import is_emirleri
    from app.services.teknik_servis.kancalar import ServisGirdiHatasi

    try:
        return await is_emirleri.olustur(
            db,
            is_emirleri.ServisIsiGirdisi(
                birim=birim,
                tur=tur,
                konu=konu[:200],
                customer_id=customer_id,
                address_id=address_id,
                contact_id=contact_id,
                oncelik=oncelik,
                talep_kanali="DIGER",
                aciklama=aciklama,
            ),
            user=user,
            clock=clock,
            baslangic_durumu="PLANLAMADA",
        )
    except ServisGirdiHatasi as exc:
        raise TeklifGirdiHatasi(str(exc)) from exc


def _aciklama(kaynak: str, hedef: date | None, ek: str | None) -> str:
    satirlar = [kaynak]
    if hedef is not None:
        satirlar.append(f"Hedef tarih: {hedef:%d.%m.%Y}")
    if ek and ek.strip():
        satirlar.append(ek.strip())
    return "\n".join(satirlar)


async def _bag_yaz(
    db: AsyncSession,
    *,
    so: ServiceOrder,
    bag_turu: str,
    hedef: date | None,
    user: User,
    quote_id: int | None = None,
    order_id: int | None = None,
) -> SatisIsBagi:
    bag = SatisIsBagi(
        quote_id=quote_id,
        order_id=order_id,
        service_order_id=so.id,
        bag_turu=bag_turu,
        hedef_tarih=hedef,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(bag)
    await db.flush()
    return bag


# --- S3.1: Keşif iste -------------------------------------------------------------


async def kesif_iste(
    db: AsyncSession, t: Quote, istek: IsIstegi, *, user: User, clock: Clock
) -> ServiceOrder:
    """Tekliften bağlı KESIF işi açar (PLANLAMADA, SLA yok, KRITIK yok)."""
    if t.status not in KESIF_ISTENEBILIR:
        raise TeklifKuralHatasi(
            f"'{teklif_svc.DURUM_ADLARI.get(t.status, t.status)}' durumundaki teklif için "
            "keşif istenemez"
        )
    if t.birim is not None:
        if istek.birim is not None and istek.birim != t.birim:
            raise TeklifGirdiHatasi("Keşif teklifin birimine açılır; başka birim seçilemez")
        birim = t.birim
    else:
        if istek.birim not in KESIF_BIRIMLERI:
            raise TeklifGirdiHatasi("Keşif için birim seçin: Haberleşme ya da Güvenlik")
        birim = istek.birim
    oncelik = _oncelik(istek.oncelik)
    bugun = teklif_svc.bugun_yerel(clock)
    hedef = _hedef(istek.hedef_tarih, bugun)
    if hedef is None:
        v = await db.get(QuoteVersion, t.current_version_id) if t.current_version_id else None
        hedef = kesif_hedef_tarihi(bugun, v.valid_until if v else None)
    acik = await db.scalar(
        select(ServiceOrder.so_no)
        .join(SatisIsBagi, SatisIsBagi.service_order_id == ServiceOrder.id)
        .where(
            SatisIsBagi.quote_id == t.id,
            SatisIsBagi.bag_turu == "KESIF",
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.status.not_in(_KAPALI_IS),
        )
        .limit(1)
    )
    if acik is not None:
        raise TeklifKuralHatasi(f"Bu teklifin açık keşif işi var: {acik}")
    adres = await _adres(db, t.customer_id, istek.address_id or t.address_id)
    so = await _is_ac(
        db,
        tur="KESIF",
        birim=birim,
        customer_id=t.customer_id,
        address_id=adres,
        contact_id=t.contact_id,
        oncelik=oncelik,
        konu=f"Keşif: {t.title or t.quote_no}",
        aciklama=_aciklama(f"Teklif {t.quote_no} için keşif isteği", hedef, istek.aciklama),
        user=user,
        clock=clock,
    )
    await _bag_yaz(db, so=so, bag_turu="KESIF", hedef=hedef, user=user, quote_id=t.id)
    await _olay(db, so, f"Keşif istendi: teklif {t.quote_no}", user, clock, t.id, t.quote_no)
    await audit.log(
        db,
        "quotes",
        "kesif_iste",
        entity_id=t.id,
        new_value={
            "so_id": so.id,
            "so_no": so.so_no,
            "birim": birim,
            "oncelik": oncelik,
            "hedef_tarih": hedef.isoformat() if hedef else None,
        },
        user_id=user.id,
    )
    return so


async def _olay(
    db: AsyncSession,
    so: ServiceOrder,
    ozet: str,
    user: User,
    clock: Clock,
    teklif_id: int | None,
    no: str,
    siparis_id: int | None = None,
) -> None:
    from app.services.teknik_servis import gecmis

    await gecmis.olay_yaz(
        db,
        so,
        "TEKLIF",
        ozet,
        user=user,
        clock=clock,
        veri={"teklif_id": teklif_id, "siparis_id": siparis_id, "no": no},
    )


# --- S4.1: Kurulum / teslimat işi ---------------------------------------------------


def _satis_turu(tur: str) -> str:
    if tur not in SATIS_IS_TURLERI:
        raise TeklifGirdiHatasi("İş türü Kurulum ya da Teslimat olmalı")
    return tur


def _birim(birim: str | None) -> str:
    if birim is None or birim not in BIRIM_KODLARI:
        raise TeklifGirdiHatasi("İşin açılacağı birimi seçin")
    return birim


async def tekliften_is_ac(
    db: AsyncSession, t: Quote, tur: str, istek: IsIstegi, *, user: User, clock: Clock
) -> ServiceOrder:
    """Kabul edilen tekliften kurulum/teslimat işi (birden çok olabilir)."""
    _satis_turu(tur)
    if t.status not in TEKLIF_KABUL:
        raise TeklifKuralHatasi("Kurulum/teslimat işi yalnız kabul edilen tekliften açılır")
    birim = t.birim or _birim(istek.birim)
    if t.birim is not None and istek.birim not in (None, t.birim):
        raise TeklifGirdiHatasi("İş teklifin birimine açılır; başka birim seçilemez")
    oncelik = _oncelik(istek.oncelik)
    hedef = _hedef(istek.hedef_tarih, teklif_svc.bugun_yerel(clock))
    adres = await _adres(db, t.customer_id, istek.address_id or t.address_id)
    ad = "Kurulum" if tur == "KURULUM" else "Teslimat"
    so = await _is_ac(
        db,
        tur=tur,
        birim=birim,
        customer_id=t.customer_id,
        address_id=adres,
        contact_id=t.contact_id,
        oncelik=oncelik,
        konu=f"{ad}: {t.title or t.quote_no}",
        aciklama=_aciklama(f"Kabul edilen teklif {t.quote_no}", hedef, istek.aciklama),
        user=user,
        clock=clock,
    )
    await _bag_yaz(db, so=so, bag_turu=tur, hedef=hedef, user=user, quote_id=t.id)
    await _olay(db, so, f"{ad} işi teklif {t.quote_no} için açıldı", user, clock, t.id, t.quote_no)
    await audit.log(
        db,
        "quotes",
        "servis_isi_ac",
        entity_id=t.id,
        new_value={"so_id": so.id, "so_no": so.so_no, "tur": tur, "birim": birim},
        user_id=user.id,
    )
    return so


async def siparisten_is_ac(
    db: AsyncSession, s: Order, tur: str, istek: IsIstegi, *, user: User, clock: Clock
) -> ServiceOrder:
    """Onaylanmış siparişten kurulum/teslimat işi (D2.2; birden çok olabilir)."""
    _satis_turu(tur)
    if s.status not in SIPARIS_IS_ACILABILIR:
        raise TeklifKuralHatasi("Kurulum/teslimat işi yalnız onaylanmış siparişten açılır")
    t = await db.get(Quote, s.quote_id) if s.quote_id else None
    birim = (t.birim if t is not None and t.birim else None) or _birim(istek.birim)
    oncelik = _oncelik(istek.oncelik)
    hedef = _hedef(istek.hedef_tarih, teklif_svc.bugun_yerel(clock))
    if hedef is None and s.requested_date and s.requested_date >= teklif_svc.bugun_yerel(clock):
        hedef = s.requested_date
    adres = await _adres(
        db, s.customer_id, istek.address_id or (t.address_id if t is not None else None)
    )
    ad = "Kurulum" if tur == "KURULUM" else "Teslimat"
    so = await _is_ac(
        db,
        tur=tur,
        birim=birim,
        customer_id=s.customer_id,
        address_id=adres,
        contact_id=t.contact_id if t is not None else None,
        oncelik=oncelik,
        konu=f"{ad}: sipariş {s.order_no}",
        aciklama=_aciklama(f"Sipariş {s.order_no}", hedef, istek.aciklama),
        user=user,
        clock=clock,
    )
    await _bag_yaz(
        db, so=so, bag_turu=tur, hedef=hedef, user=user, quote_id=s.quote_id, order_id=s.id
    )
    await _olay(
        db, so, f"{ad} işi sipariş {s.order_no} için açıldı", user, clock, s.quote_id,
        s.order_no, s.id,
    )  # fmt: skip
    await audit.log(
        db,
        "orders",
        "servis_isi_ac",
        entity_id=s.id,
        new_value={"so_id": so.id, "so_no": so.so_no, "tur": tur, "birim": birim},
        user_id=user.id,
    )
    return so


# --- S3.3: Keşif sonucu ve raporu ----------------------------------------------------


async def bagli_is_al(db: AsyncSession, t: Quote, so_id: int) -> ServiceOrder:
    """Teklife BAĞLI iş (bağ tablosu ya da eski tek bağ); değilse 404."""
    bagli = t.service_order_id == so_id or (
        await db.scalar(
            select(SatisIsBagi.id).where(
                SatisIsBagi.service_order_id == so_id,
                or_(
                    SatisIsBagi.quote_id == t.id,
                    SatisIsBagi.order_id.in_(select(Order.id).where(Order.quote_id == t.id)),
                ),
            )
        )
        is not None
    )
    so = await db.get(ServiceOrder, so_id) if bagli else None
    if so is None or so.is_deleted:
        raise TeklifKapsamDisi("Servis işi bulunamadı")
    return so


async def _gecerli_sonuc(db: AsyncSession, so_id: int) -> ServiceResult | None:
    return await db.scalar(
        select(ServiceResult)
        .where(ServiceResult.service_order_id == so_id, ServiceResult.gecersiz_at.is_(None))
        .order_by(ServiceResult.id.desc())
        .limit(1)
    )


async def is_ekleri(db: AsyncSession, so_id: int) -> list[Attachment]:
    return list(
        (
            await db.scalars(
                select(Attachment)
                .where(Attachment.entity == "service_orders", Attachment.entity_id == so_id)
                .order_by(Attachment.id)
            )
        ).all()
    )


async def is_sonucu(db: AsyncSession, so: ServiceOrder) -> dict[str, Any]:
    """Teklif ekranındaki keşif sonucu: teknisyen raporu + fotoğraf/belge listesi."""
    from app.services import storage as depo
    from app.services.teknik_servis.onay import SONUC_ADLARI

    sonuc = await _gecerli_sonuc(db, so.id)
    ekler = await is_ekleri(db, so.id)
    return {
        "tamamlandi": so.status in ("TAMAMLANDI", "KAPATILDI"),
        "rapor": sonuc.yapilan_islem if sonuc is not None else None,
        "sonuc": SONUC_ADLARI.get(sonuc.sonuc, sonuc.sonuc) if sonuc is not None else None,
        "rapor_tarihi": sonuc.created_at if sonuc is not None else None,
        "ekler": [
            {
                "id": e.id,
                "dosya_adi": e.file_name,
                "tur": e.kind,
                "mime_type": e.mime_type,
                "gorsel": e.mime_type in depo.GORSEL_TIPLERI,
                "boyut": e.size_bytes,
            }
            for e in ekler
        ],
    }


async def kesif_raporu_baglami(
    db: AsyncSession, t: Quote, so: ServiceOrder, *, clock: Clock
) -> dict[str, Any]:
    """`templates/kesif_raporu.html` (FİYATSIZ; fotoğraflar gömülü)."""
    from app.services import belgeler
    from app.services import storage as depo
    from app.services.teknik_servis.is_emirleri import DURUM_ADLARI, TUR_ADLARI
    from app.services.teknik_servis.onay import SONUC_ADLARI
    from app.services.teknik_servis.yerel_zaman import yerel_an, yerel_bugun

    musteri = await db.get(Account, so.customer_id) if so.customer_id else None
    adres = await db.get(Address, so.address_id) if so.address_id else None
    sonuc = await _gecerli_sonuc(db, so.id)
    bag = await db.scalar(select(SatisIsBagi).where(SatisIsBagi.service_order_id == so.id))
    isteyen = await db.get(User, bag.created_by) if bag and bag.created_by else None
    teknisyen = await db.get(User, sonuc.created_by) if sonuc and sonuc.created_by else None
    fotograflar = []
    belgeler_ = []
    for e in await is_ekleri(db, so.id):
        if e.mime_type in depo.GORSEL_TIPLERI and e.mime_type != "image/heic":
            try:
                icerik = depo.yol(e.storage_path).read_bytes()
            except (depo.DepoHatasi, OSError):
                continue
            fotograflar.append(
                {
                    "ad": e.file_name,
                    "not": e.notes,
                    "veri": f"data:{e.mime_type};base64,{base64.b64encode(icerik).decode()}",
                }
            )
        else:
            belgeler_.append(e.file_name)

    def _an(d) -> str | None:
        return yerel_an(d).strftime("%d.%m.%Y %H:%M") if d else None

    return {
        "firma": belgeler.firma_bilgisi(await belgeler.ayar_haritasi(db)),
        "belge_tarihi": yerel_bugun(clock).strftime("%d.%m.%Y"),
        "teklif_no": t.quote_no,
        "teklif_baslik": t.title,
        "so_no": so.so_no,
        "birim": BIRIMLER.get(so.birim, so.birim),
        "tur": TUR_ADLARI.get(so.tur, so.tur),
        "durum": DURUM_ADLARI.get(so.status, so.status),
        "musteri": musteri.title if musteri else so.customer_name_raw,
        "lokasyon": (
            " — ".join(p for p in (adres.site_name, adres.line) if p) if adres else so.location_raw
        ),
        "il_ilce": (" / ".join(p for p in (adres.district, adres.city) if p) if adres else None),
        "isteyen": isteyen.full_name if isteyen else None,
        "istek_tarihi": _an(bag.created_at) if bag else None,
        "hedef_tarih": bag.hedef_tarih.strftime("%d.%m.%Y") if bag and bag.hedef_tarih else None,
        "aciklama": so.aciklama,
        "tamamlanma": _an(so.completed_at),
        "teknisyen": teknisyen.full_name if teknisyen else None,
        "sonuc": SONUC_ADLARI.get(sonuc.sonuc, sonuc.sonuc) if sonuc else None,
        "rapor": sonuc.yapilan_islem if sonuc else None,
        "fotograflar": fotograflar,
        "diger_ekler": belgeler_,
    }


async def kesif_raporu_pdf(db: AsyncSession, t: Quote, so: ServiceOrder, *, clock: Clock) -> bytes:
    from app.services.pdf import pdf_uret_async

    return await pdf_uret_async(
        "kesif_raporu.html", **await kesif_raporu_baglami(db, t, so, clock=clock)
    )


# --- S2.2: Tekliflerim ------------------------------------------------------------

ACIK_DURUMLAR = KESIF_ISTENEBILIR
OZET_VARSAYILAN_GUN = 90


def _oran(pay: int, payda: int) -> float | None:
    return round(pay / payda * 100, 1) if payda else None


def _metrikler(sayilar: dict[str, int]) -> dict[str, Any]:
    acik = sum(sayilar.get(d, 0) for d in ACIK_DURUMLAR)
    kazanilan = sum(sayilar.get(d, 0) for d in TEKLIF_KABUL)
    kaybedilen = sayilar.get("RED", 0)
    suresi_dolan = sayilar.get("SURESI_DOLDU", 0)
    iptal = sayilar.get("IPTAL", 0)
    karara = kazanilan + kaybedilen + suresi_dolan
    return {
        "toplam": sum(sayilar.values()),
        "acik": acik,
        "kazanilan": kazanilan,
        "kaybedilen": kaybedilen,
        "suresi_dolan": suresi_dolan,
        "iptal": iptal,
        # Oranlar sonuçlanan teklife göre (açık teklif paydaya girmez — teklif
        # dönüşüm raporuyla aynı kural).
        "kazanma_orani": _oran(kazanilan, karara),
        "kayip_orani": _oran(kaybedilen, karara),
        "sure_dolma_orani": _oran(suresi_dolan, karara),
    }


async def tekliflerim(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    tarih_bas: date | None,
    tarih_bit: date | None,
    tur: str | None = None,
    ekip: bool = False,
    hazirlayan_id: int | None = None,
) -> dict[str, Any]:
    """S2.2: satışçının kendi teklifleri (açık/kazanılan/kaybedilen/süresi
    dolan, oranlar, nedene göre kayıp). `ekip` (teklif.ekip_ozet) satışçı
    kırılımını da verir. Dönem teklifin oluşturulma tarihine göredir;
    "süresi doldu" hesaplanır (`etkin_durum`). Kapsam `teklif_kapsami`."""
    from app.services.teknik_servis.yerel_zaman import yerel_gun_araligi

    bugun = teklif_svc.bugun_yerel(clock)
    bit = tarih_bit or bugun
    bas = tarih_bas or (bit - timedelta(days=OZET_VARSAYILAN_GUN))
    if bas > bit:
        raise TeklifGirdiHatasi("Başlangıç tarihi bitişten sonra olamaz")
    if tur not in (None, "SATIS", "SERVIS"):
        raise TeklifGirdiHatasi("Tür SATIS ya da SERVIS olmalı")
    durum = teklif_svc.etkin_durum_ifadesi(bugun).label("etkin")
    stmt = (
        select(Quote.owner_id, durum, Quote.lost_reason_kod)
        .outerjoin(QuoteVersion, QuoteVersion.id == Quote.current_version_id)
        .where(
            Quote.is_deleted.is_(False),
            Quote.created_at >= yerel_gun_araligi(bas)[0],
            Quote.created_at < yerel_gun_araligi(bit)[1],
        )
    )
    stmt = teklif_svc.teklif_kapsami(stmt, user)
    if tur == "SATIS":
        stmt = stmt.where(Quote.birim.is_(None))
    elif tur == "SERVIS":
        stmt = stmt.where(Quote.birim.is_not(None))
    if not ekip:
        stmt = stmt.where(Quote.owner_id == user.id)
    elif hazirlayan_id is not None:
        stmt = stmt.where(Quote.owner_id == hazirlayan_id)
    satirlar = (await db.execute(stmt)).all()

    toplam: dict[str, int] = {}
    kisi: dict[int | None, dict[str, int]] = {}
    nedenler: dict[str, int] = {}
    for owner_id, etkin, kod in satirlar:
        toplam[etkin] = toplam.get(etkin, 0) + 1
        k = kisi.setdefault(owner_id, {})
        k[etkin] = k.get(etkin, 0) + 1
        if etkin == "RED":
            kod = kod or "DIGER"
            nedenler[kod] = nedenler.get(kod, 0) + 1
    sonuc: dict[str, Any] = {
        "tarih_bas": bas,
        "tarih_bit": bit,
        "ozet": _metrikler(toplam),
        "kayip_nedenleri": [
            {"kod": k, "neden": KAYIP_NEDENLERI.get(k, k), "adet": a}
            for k, a in sorted(nedenler.items(), key=lambda x: (-x[1], x[0]))
        ],
        "satiscilar": [],
    }
    if ekip:
        adlar = await teklif_svc.kullanici_adlari(db, set(kisi))
        sonuc["satiscilar"] = sorted(
            (
                {
                    "owner_id": oid,
                    "ad": adlar.get(oid) if oid else "Sahipsiz",
                    **_metrikler(say),
                }
                for oid, say in kisi.items()
            ),
            key=lambda r: (-r["toplam"], r["ad"] or ""),
        )
    return sonuc


# --- S4.2: Satışlarımın durumu ----------------------------------------------------


async def satislarim(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    ekip: bool = False,
    hazirlayan_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Kabul edilen teklifler ve siparişler, bağlı işleriyle ve aşamalarıyla.

    Satışçı kendi kayıtlarını görür (`owner_id`); `ekip` (teklif.ekip_ozet)
    kapsamındaki tümünü ya da seçilen satışçınınkini görür. Sipariş satırları
    yalnız mobilite şirketi etkinken (sipariş ekranının kapısı) gelir.
    Kapsamdaki teklif, siparişe dönmüşse siparişin satırında anlatılır.
    """
    sahip = None if ekip else user.id
    if ekip and hazirlayan_id is not None:
        sahip = hazirlayan_id
    satirlar: list[dict[str, Any]] = []
    siparisli_teklifler: set[int] = set()

    if sirketler.mobilite_acik_mi(user) and user.has("siparis.gor"):
        stmt = select(Order).where(Order.is_deleted.is_(False), Order.status != "IPTAL")
        if sahip is not None:
            stmt = stmt.where(Order.owner_id == sahip)
        if user.role is not None and user.role.scope == SCOPE_OWN_CUSTOMERS:
            stmt = stmt.where(Order.owner_id == user.id)
        for s in (await db.scalars(stmt.order_by(Order.id.desc()).limit(limit))).all():
            if s.quote_id:
                siparisli_teklifler.add(s.quote_id)
            satirlar.append(
                {
                    "kaynak": "SIPARIS",
                    "id": s.id,
                    "no": s.order_no,
                    "customer_id": s.customer_id,
                    "durum": s.status,
                    "tarih": s.order_date,
                    "owner_id": s.owner_id,
                    "isler": await siparis_bagli_isler(db, s),
                }
            )

    stmt = select(Quote).where(Quote.is_deleted.is_(False), Quote.status.in_(TEKLIF_KABUL))
    stmt = teklif_svc.teklif_kapsami(stmt, user)
    if sahip is not None:
        stmt = stmt.where(Quote.owner_id == sahip)
    for t in (await db.scalars(stmt.order_by(Quote.id.desc()).limit(limit))).all():
        if t.id in siparisli_teklifler:
            continue
        satirlar.append(
            {
                "kaynak": "TEKLIF",
                "id": t.id,
                "no": t.quote_no,
                "customer_id": t.customer_id,
                "durum": t.status,
                "tarih": t.updated_at.date(),
                "owner_id": t.owner_id,
                "isler": await teklif_bagli_isler(db, t),
            }
        )
    musteriler = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(
                    Account.id.in_({r["customer_id"] for r in satirlar} or {0})
                )
            )
        ).all()
    )
    adlar = await teklif_svc.kullanici_adlari(db, {r["owner_id"] for r in satirlar})
    for r in satirlar:
        r["musteri"] = musteriler.get(r["customer_id"])
        r["satisci"] = adlar.get(r["owner_id"]) if r["owner_id"] else None
        asamalar = [i["asama"] for i in r["isler"]]
        if not asamalar:
            r["genel_asama"] = "IS_YOK"
            r["genel_asama_adi"] = "İş açılmadı"
        elif all(a in ("TAMAMLANDI", "IPTAL") for a in asamalar):
            r["genel_asama"] = "TAMAMLANDI"
            r["genel_asama_adi"] = "Tamamlandı"
        elif "ASKIDA" in asamalar:
            r["genel_asama"] = "ASKIDA"
            r["genel_asama_adi"] = "Askıda"
        else:
            r["genel_asama"] = "DEVAM"
            r["genel_asama_adi"] = "Devam ediyor"
    satirlar.sort(key=lambda r: r["tarih"] or date.min, reverse=True)
    return satirlar[:limit]


# --- S2.3 / S1.4 / S3.3: hatırlatma ve bildirimler (uyarı merkezi) --------------------


async def uyarilar(db: AsyncSession, clock: Clock, user: User) -> list:
    """Satış uyarıları (`services/uyarilar.topla`; saklanmaz, hesaplanır)."""
    from app.services import iskonto
    from app.services.uyarilar import Uyari

    sonuc: list[Uyari] = []
    if not user.has("teklif.gor"):
        return sonuc
    bugun = teklif_svc.bugun_yerel(clock)
    takip = int(await ayar_svc.get(db, "teklif_takip_uyari_gun"))

    async def _say(stmt) -> int:
        return int(
            await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        )

    benim = teklif_svc.TeklifFiltresi(hazirlayan_id=user.id)
    # S2.3: süresi dolmak üzere ve yanıt bekleyen tekliflerim.
    yaklasan = await _say(
        teklif_svc.liste_sorgusu(
            user,
            teklif_svc.TeklifFiltresi(hazirlayan_id=user.id, kpi="suresi_yaklasan"),
            bugun,
            takip,
        )
    )
    sonuc.append(
        Uyari(
            kod="satis.teklif_suresi_yaklasan",
            baslik=f"Süresi {takip} gün içinde dolacak teklifim",
            adet=yaklasan,
            yol="/teklifler?kpi=suresi_yaklasan&benim=1",
            onem="uyari",
            aciklama="Müşteri yanıtı bekleniyor; geçerlilik bitmeden arayın.",
        )
    )
    yanit = await _say(
        teklif_svc.liste_sorgusu(user, benim, bugun, takip).where(
            Quote.status.in_(teklif_svc.KARAR_BEKLEYEN),
            or_(QuoteVersion.valid_until.is_(None), QuoteVersion.valid_until >= bugun),
            QuoteVersion.sent_at.is_not(None),
            QuoteVersion.sent_at < clock.now() - timedelta(days=takip),
        )
    )
    sonuc.append(
        Uyari(
            kod="satis.teklif_yanit_bekleyen",
            baslik=f"{takip} günden uzun süredir yanıt bekleyen teklifim",
            adet=yanit,
            yol="/teklifler?kpi=musteri_yaniti_bekleyen&benim=1",
            aciklama="Gönderildi, müşteri henüz kabul ya da ret bildirmedi.",
        )
    )
    # S3.3: keşfi tamamlanan ve teklifi hâlâ hazırlanan teklifler (satışçıya).
    kesif = await _say(
        select(Quote.id)
        .join(SatisIsBagi, SatisIsBagi.quote_id == Quote.id)
        .join(ServiceOrder, ServiceOrder.id == SatisIsBagi.service_order_id)
        .where(
            Quote.owner_id == user.id,
            Quote.is_deleted.is_(False),
            Quote.status.in_(("TASLAK", "ONAY_BEKLIYOR", "ONAYLANDI", "REVIZE_EDILDI")),
            SatisIsBagi.bag_turu == "KESIF",
            ServiceOrder.status.in_(("TAMAMLANDI", "KAPATILDI")),
        )
        .distinct()
    )
    sonuc.append(
        Uyari(
            kod="satis.kesif_tamamlandi",
            baslik="Keşfi tamamlanan teklifim",
            adet=kesif,
            yol="/teklifler?benim=1&kesif=TAMAMLANDI",
            aciklama="Keşif raporu ve fotoğraflar teklif ekranında.",
        )
    )
    # S1.4: onayı bana düşen limit üstü iskontolu satış teklifleri.
    if user.has(iskonto.ONAY_IZNI) or user.has(iskonto.UST_ONAY_IZNI):
        tablo = await iskonto.rol_limitleri(db)
        stmt = teklif_svc.teklif_kapsami(
            select(Quote, QuoteVersion)
            .join(QuoteVersion, QuoteVersion.id == Quote.current_version_id)
            .where(
                Quote.is_deleted.is_(False),
                Quote.birim.is_(None),
                Quote.status == "ONAY_BEKLIYOR",
                QuoteVersion.discount_approved_at.is_(None),
            ),
            user,
        )
        satirlar = (await db.execute(stmt)).all()
        sahipler = await iskonto.hazirlayanlar(db, [t for t, _ in satirlar])
        adet = 0
        for t, v in satirlar:
            d = iskonto.durum_hesapla(v, sahipler.get(t.owner_id or 0), tablo)
            if d.onay_bekliyor and iskonto.onaylayabilir_mi(user, d.oran, tablo):
                adet += 1
        sonuc.append(
            Uyari(
                kod="satis.iskonto_onay_bekleyen",
                baslik="İskonto onayımı bekleyen teklif",
                adet=adet,
                yol="/teklifler?kpi=onay_bekleyen&tur=SATIS",
                onem="uyari",
                aciklama="Hazırlayanın iskonto limitini aşan teklif; onaysız gönderilemez.",
            )
        )
    return sonuc


def kesif_filtresi(durum: str):
    """Liste süzgeci: teklifin keşif işi tamamlanmış/açık (`kesif=`)."""
    kapali = ("TAMAMLANDI", "KAPATILDI")
    kosul = (
        ServiceOrder.status.in_(kapali)
        if durum == "TAMAMLANDI"
        else ServiceOrder.status.not_in(_KAPALI_IS)
    )
    return Quote.id.in_(
        select(SatisIsBagi.quote_id)
        .join(ServiceOrder, ServiceOrder.id == SatisIsBagi.service_order_id)
        .where(and_(SatisIsBagi.bag_turu == "KESIF", kosul))
    )
