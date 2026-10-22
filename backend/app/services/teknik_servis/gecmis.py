"""Servis işinin silinemez olay geçmişi ve iş notu (E01-04, TS-022).

`service_order_events` yalnız eklenir (DB tetikleyicisi `trg_soe_salt_ekleme`
UPDATE/DELETE'i reddeder). `ozet` ve `veri` KİŞİSEL VERİ İÇERMEZ: tetikleyici
yüzünden KVKK anonimleştirmesi bu satırları temizleyemez. `olay_yaz`
irtibat adı/telefonu ve imzalayan adı taşıyan anahtarları reddeder; ayrıca
işin kendi irtibat adı/telefonu özet metninde geçiyorsa yazmaz (serbest
metne yanlışlıkla kopyalanan değer de kalıcı olurdu).

Olay geçmişi denetim izinin YERİNİ ALMAZ: kritik işlemler (açılış, kapat,
iptal, yeniden aç, düzeltme, atama) API katmanında ayrıca `audit.log` ile
aynı transaction'da yazılır (E01 K25).

Kişi adları (personel) olaya METİN olarak değil kimlik olarak yazılır
(`veri` içinde `user_id` listeleri); geçmiş okunurken ad çözülür. Böylece
adı değişen ya da anonimleştirilen kişi geçmişte eski adıyla kalmaz.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models import ServiceOrderEvent
from app.models.teknik_servis import OLAY_TURLERI

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, User

# `veri` sözlüğünde YASAK anahtarlar (kişisel veri).
KISISEL_VERI_ANAHTARLARI = frozenset(
    {"iletisim_ad", "iletisim_telefon", "imzalayan_ad", "imzalayan_unvan", "telefon", "ad_soyad"}
)

OZET_UZUNLUGU = 500
NOT_UZUNLUGU = 500

# Ekranda gösterilen olay türü adları (filtre ve zaman çizelgesi).
OLAY_ADLARI: dict[str, str] = {
    "OLUSTUR": "Açılış",
    "DURUM": "Durum",
    "ATAMA": "Atama",
    "PLAN": "Plan",
    "BEKLEME": "Bekleme",
    "BEKLEME_BITTI": "Bekleme bitti",
    "SONUC": "Sonuç",
    "NOT": "Not",
    "EK": "Ek",
    "EK_SIL": "Ek silindi",
    "ONAY": "Müşteri onayı",
    "DUZELTME": "Düzeltme",
    "SERI": "Seri",
    "ILISKI": "Bağlı iş",
    "PARCA": "Parça",
    "ATOLYE": "Atölye",
    "TEKLIF": "Teklif",
    "SLA": "SLA",
}


class KisiselVeriHatasi(ValueError):
    """Olay geçmişine kişisel veri yazma girişimi (programlama hatası)."""


def _yasak_anahtarlar(veri: Any) -> set[str]:
    """İç içe sözlük/listelerde yasak anahtar arar."""
    bulunan: set[str] = set()
    if isinstance(veri, dict):
        for anahtar, deger in veri.items():
            if str(anahtar).lower() in KISISEL_VERI_ANAHTARLARI:
                bulunan.add(str(anahtar))
            bulunan |= _yasak_anahtarlar(deger)
    elif isinstance(veri, list | tuple):
        for deger in veri:
            bulunan |= _yasak_anahtarlar(deger)
    return bulunan


def _kisisel_degerler(so: ServiceOrder) -> list[str]:
    """İşin kendi irtibat değerleri (özet metninde geçmemeli)."""
    degerler = []
    for deger in (so.iletisim_ad, so.iletisim_telefon):
        if deger and len(deger.strip()) >= 3:
            degerler.append(deger.strip().casefold())
    return degerler


async def olay_yaz(
    db: AsyncSession,
    so: ServiceOrder,
    olay_turu: str,
    ozet: str,
    *,
    user: User | None,
    clock: Clock,
    eski_durum: str | None = None,
    yeni_durum: str | None = None,
    veri: dict[str, Any] | None = None,
) -> ServiceOrderEvent:
    """Olay ekler (`olusma_zamani = clock.now()`); kişisel veri → KisiselVeriHatasi.

    Sözlük dışı tür programlama hatasıdır (ValueError) — CHECK ihlali
    kullanıcıya 409 olarak dönseydi hatanın kaynağı gizlenirdi.
    """
    if olay_turu not in OLAY_TURLERI:
        raise ValueError(f"Bilinmeyen olay türü: {olay_turu}")
    yasak = _yasak_anahtarlar(veri)
    if yasak:
        raise KisiselVeriHatasi(
            f"Olay geçmişine kişisel veri yazılamaz ({', '.join(sorted(yasak))})"
        )
    metin = (ozet or "").strip() or OLAY_ADLARI[olay_turu]
    kucuk = metin.casefold()
    if any(d in kucuk for d in _kisisel_degerler(so)):
        raise KisiselVeriHatasi("Olay özetinde irtibat adı/telefonu geçemez")
    if len(metin) > OZET_UZUNLUGU:
        metin = metin[: OZET_UZUNLUGU - 1] + "…"
    olay = ServiceOrderEvent(
        service_order_id=so.id,
        olay_turu=olay_turu,
        eski_durum=eski_durum,
        yeni_durum=yeni_durum,
        ozet=metin,
        veri=veri,
        user_id=user.id if user is not None else None,
        olusma_zamani=clock.now(),
    )
    db.add(olay)
    await db.flush()
    return olay


async def not_ekle(
    db: AsyncSession, so: ServiceOrder, metin: str, *, user: User, clock: Clock
) -> ServiceOrderEvent:
    """İş notu = NOT olayı. Durumu ve sürümü DEĞİŞTİRMEZ (E01-04 kabul 2).

    Not serbest metindir; iş kaydının irtibat değerleri nota yazılamaz
    (olay satırı anonimleştirilemez). Boş not 400.
    """
    from app.services.teknik_servis.kancalar import ServisGirdiHatasi

    temiz = (metin or "").strip()
    if not temiz:
        raise ServisGirdiHatasi("Not boş olamaz")
    if len(temiz) > NOT_UZUNLUGU:
        raise ServisGirdiHatasi(f"Not en çok {NOT_UZUNLUGU} karakter olabilir")
    try:
        return await olay_yaz(db, so, "NOT", temiz, user=user, clock=clock)
    except KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi(
            "Nota müşteri irtibat adı veya telefonu yazılamaz (olay geçmişi silinemez)"
        ) from exc


async def gecmis_listesi(
    db: AsyncSession, so: ServiceOrder, *, turler: Iterable[str] | None = None
) -> list[ServiceOrderEvent]:
    """Olaylar zaman sırasıyla (eşit zamanda ekleme sırası)."""
    stmt = select(ServiceOrderEvent).where(ServiceOrderEvent.service_order_id == so.id)
    secili = [t for t in (turler or ()) if t]
    if secili:
        stmt = stmt.where(ServiceOrderEvent.olay_turu.in_(secili))
    stmt = stmt.order_by(ServiceOrderEvent.olusma_zamani, ServiceOrderEvent.id)
    return list((await db.scalars(stmt)).all())
