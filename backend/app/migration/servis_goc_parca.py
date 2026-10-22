"""Servis göçü eki: eski serbest metin parça kayıtları → iş NOT olayı (TS-208, E11-21).

V1.20.1 servis parçasını stok hareketiyle değil SERBEST METİNLE tutuyordu:
bakım cihaz satırında `MaintenanceDeviceItems.SpareParts`, atölye kaydında
`WorkshopTickets.RepairInfo`. Bu metinler göç edilmiş servis işinin olay
geçmişine **NOT olayı** olarak taşınır:

- Metin **karakter karakter** korunur: tam hâli olay `veri.parca_metni`'nde;
  `ozet` ekranda görünen ilk 500 karakterdir (olay özeti sınırı).
- Göç **hiçbir** `stock_movements` satırı üretmez (E11-21 kararı: eski parça
  hareketi stok defterine girmez; açılış stoğu fiziksel sayımla gelir, TS-134).
- Yalnız göç edilmiş işe bağlanır; işi aktarılmamış satır (ör. planlı bakım,
  atölye işi) KARANTİNADA kalır, metin kaybolmaz (uzlaşma raporunda görünür).
- Olay zamanı kaynaktaki an (`CompletedAt` / `UpdatedAt`), yoksa işin açılış
  anıdır; tarih uydurulmaz.
- İdempotent: kimlik `veri.kaynak='<Tablo>:<Id>'` (`veri.goc='DENGEERP_V1'`);
  ikinci koşu aynı satırı bulur ve yazmaz. Olay tablosu salt eklemedir
  (`trg_soe_salt_ekleme`); kişisel veri anahtarı yazılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration.servis_kaynak import (
    GOC_SISTEMI,
    OLAY_HEDEFI,
    AdimSonucu,
    KaynakDizini,
    kaynak_ref,
    mevcut_olay_refleri,
    tamsayi,
    yerel_an,
)
from app.migration.servis_plan import goc_isleri
from app.models import ServiceOrder, ServiceOrderEvent
from app.services import audit

OZET_SINIRI = 500
# (kaynak tablo, kimlik kolonu, metin kolonu, zaman kolonu, etiket)
PARCA_KAYNAKLARI = (
    ("MaintenanceDeviceItems", "MaintenanceDeviceItemId", "SpareParts", "CompletedAt", "Bakım"),
    ("WorkshopTickets", "WorkshopTicketId", "RepairInfo", "UpdatedAt", "Atölye"),
)


@dataclass
class ParcaNotu:
    ref: str
    is_ref: str
    alan: str
    etiket: str
    metin: str
    an: datetime | None


def hazirla(dizin: KaynakDizini, isler: dict[str, dict[str, Any]]) -> list[AdimSonucu]:
    """Kaynak = metni DOLU satırlar (boş parça alanı kayıt değildir). Hiçbir şey yazmaz."""
    sonuclar: list[AdimSonucu] = []
    for tablo, kimlik_kolonu, alan, zaman_kolonu, etiket in PARCA_KAYNAKLARI:
        satirlar = [
            s
            for s in dizin.tablo(tablo, zorunlu=False)
            if s.get(alan) is not None and str(s.get(alan)).strip()
        ]
        sonuc = AdimSonucu(tablo, OLAY_HEDEFI, kaynak=len(satirlar))
        gorulen: set[str] = set()
        for sira, s in enumerate(satirlar, start=1):
            kimlik = tamsayi(s.get(kimlik_kolonu))
            if kimlik is None:
                sonuc.reddet(f"{tablo} satır {sira}", f"{kimlik_kolonu} yok")
                continue
            ref = kaynak_ref(tablo, kimlik)
            if ref in gorulen:
                sonuc.reddet(ref, "dökümde aynı kimlik iki kez")
                continue
            gorulen.add(ref)
            is_id = tamsayi(s.get("WorkOrderId"))
            if is_id is None:
                sonuc.karantinaya(ref, "İş emri bağı yok (metin raporda korunur)")
                continue
            is_ref = kaynak_ref("WorkOrders", is_id)
            if is_ref not in isler:
                sonuc.karantinaya(ref, f"İşi aktarılmamış ({is_ref})")
                continue
            try:
                an = yerel_an(s.get(zaman_kolonu))
            except ValueError:
                an = None
                sonuc.uyar(ref, "TARIH_OKUNAMADI", str(s.get(zaman_kolonu)))
            # Metin olduğu gibi (strip YOK: karakter karakter aynı kalmalı).
            sonuc.aktarilacak.append(
                ParcaNotu(ref, is_ref, f"{tablo}.{alan}", etiket, str(s.get(alan)), an)
            )
        sonuclar.append(sonuc)
    return sonuclar


async def hazirla_db(db: AsyncSession, dizin: KaynakDizini) -> list[AdimSonucu]:
    sonuclar = hazirla(dizin, await goc_isleri(db))
    for sonuc in sonuclar:
        var = await mevcut_olay_refleri(db, sonuc.kaynak_tablo)
        sonuc.mevcut = sum(1 for t in sonuc.aktarilacak if t.ref in var)
        sonuc.yeni = len(sonuc.aktarilacak) - sonuc.mevcut
    return sonuclar


def ozet_metni(etiket: str, metin: str) -> str:
    ozet = f"Eski sistem parça kaydı ({etiket}): {metin}"
    return ozet if len(ozet) <= OZET_SINIRI else ozet[: OZET_SINIRI - 1] + "…"


async def yukle(
    db: AsyncSession, sonuclar: list[AdimSonucu], *, user_id: int | None = None
) -> list[AdimSonucu]:
    isler = await goc_isleri(db)
    for sonuc in sonuclar:
        var = await mevcut_olay_refleri(db, sonuc.kaynak_tablo)
        eklenen = 0
        for t in sonuc.aktarilacak:
            if t.ref in var or t.is_ref not in isler:
                continue
            so_id = isler[t.is_ref]["id"]
            an = t.an
            if an is None:
                so = await db.get(ServiceOrder, so_id)
                an = so.created_at
            await db.execute(
                insert(ServiceOrderEvent.__table__).values(
                    service_order_id=so_id,
                    olay_turu="NOT",
                    ozet=ozet_metni(t.etiket, t.metin),
                    veri={
                        "goc": GOC_SISTEMI,
                        "kaynak": t.ref,
                        "alan": t.alan,
                        "parca_metni": t.metin,
                    },
                    user_id=user_id,
                    olusma_zamani=an,
                )
            )
            var.add(t.ref)
            eklenen += 1
        sonuc.yeni = eklenen
        sonuc.mevcut = len(sonuc.aktarilacak) - eklenen
        await audit.log(
            db,
            "service_order_events",
            "goc.servis_parca_metni",
            new_value=sonuc.ozet(),
            user_id=user_id,
        )
    return sonuclar
