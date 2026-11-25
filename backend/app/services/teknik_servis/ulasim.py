"""Saha işinde ulaşım ve araç km (KARARLAR 2026-11-20 §1).

GÜVENLİK ve HABERLEŞME birimlerinin saha işleri (kategori ATÖLYE değil):

- İşleme alırken (İŞLEMDE) ulaşım türü zorunlu; şirket aracında plaka da
  zorunlu. Plaka havuzdan seçilir ya da elle yazılır (KARARLAR 2026-11-25);
  havuzdaki bir plakayla eşleşen metin o araca bağlanır.
- Araç km (başlangıç, yerinde tamamlamada son km) `servis_saha_km_zorunlu`
  açıksa zorunludur; varsayılan KAPALI (2026-11-25: "km şimdilik zorunlu
  istenmesin"). Girildiyse son km başlangıçtan küçük olamaz.
- Son km havuzdaki aracın `son_km`'si olur; sonraki işte başlangıç önerisidir.

Kural `servis_saha_ulasim_zorunlu` ayarıyla açılır/kapanır (varsayılan açık)
ve yalnız bundan sonraki geçişlerde uygulanır; sistem (worker) geçişleri
denetlenmez.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServiceOrder, User
from app.models.servis_planlama import ServicePlan, ServiceVehicle
from app.services import audit
from app.services import settings as ayar_svc
from app.services.teknik_servis.kancalar import ServisGirdiHatasi

ULASIM_TURLERI = ("SIRKET_ARACI", "UCAK", "METRO", "OTOBUS")
ULASIM_ADLARI = {
    "SIRKET_ARACI": "Şirket aracı",
    "UCAK": "Uçak",
    "METRO": "Metro",
    "OTOBUS": "Otobüs",
}
ULASIM_BIRIMLERI = frozenset({"GUVENLIK", "HABERLESME"})
AZAMI_KM = 9_999_999


def kapsamda(so: ServiceOrder) -> bool:
    return so.birim in ULASIM_BIRIMLERI and so.kategori != "ATOLYE"


async def zorunlu_mu(db: AsyncSession, so: ServiceOrder) -> bool:
    return kapsamda(so) and bool(await ayar_svc.get(db, "servis_saha_ulasim_zorunlu"))


async def km_zorunlu_mu(db: AsyncSession) -> bool:
    return bool(await ayar_svc.get(db, "servis_saha_km_zorunlu"))


def plaka_temizle(plaka: str | None) -> str | None:
    """Büyük harf, tek boşluk; boşsa None."""
    p = re.sub(r"\s+", " ", (plaka or "").strip()).upper()
    if not p:
        return None
    if len(p) > 20:
        raise ServisGirdiHatasi("Plaka en çok 20 karakter olabilir")
    return p


async def _havuzdaki_arac(db: AsyncSession, plaka: str) -> ServiceVehicle | None:
    anahtar = plaka.replace(" ", "")
    return await db.scalar(
        select(ServiceVehicle)
        .where(
            func.upper(func.replace(ServiceVehicle.plate, " ", "")) == anahtar,
            ServiceVehicle.is_deleted.is_(False),
            ServiceVehicle.is_active.is_(True),
        )
        .limit(1)
    )


async def _plan_araci(db: AsyncSession, so: ServiceOrder) -> int | None:
    return await db.scalar(
        select(ServicePlan.vehicle_id)
        .where(
            ServicePlan.service_order_id == so.id,
            ServicePlan.is_active.is_(True),
            ServicePlan.vehicle_id.is_not(None),
        )
        .order_by(ServicePlan.id.desc())
        .limit(1)
    )


async def _arac(db: AsyncSession, arac_id: int) -> ServiceVehicle:
    arac = await db.get(ServiceVehicle, arac_id)
    if arac is None or arac.is_deleted or not arac.is_active:
        raise ServisGirdiHatasi("Araç bulunamadı ya da pasif; listeden seçin")
    return arac


def _km(deger: int | None, ad: str) -> int | None:
    if deger is None:
        return None
    if deger < 0 or deger > AZAMI_KM:
        raise ServisGirdiHatasi(f"{ad} 0 ile {AZAMI_KM} arasında olmalı")
    return deger


async def ozet(db: AsyncSession, so: ServiceOrder) -> dict[str, Any]:
    """Ekran için: kayıtlı bilgi + plan aracı önerisi + aracın son km'si."""
    arac_id = so.servis_arac_id or await _plan_araci(db, so)
    arac = await db.get(ServiceVehicle, arac_id) if arac_id else None
    return {
        "zorunlu": await zorunlu_mu(db, so),
        "km_zorunlu": await km_zorunlu_mu(db),
        "ulasim_turu": so.ulasim_turu,
        "servis_arac_id": so.servis_arac_id,
        "plaka": so.arac_plaka,
        "baslangic_km": so.baslangic_km,
        "bitis_km": so.bitis_km,
        "oneri_arac_id": arac.id if arac is not None else None,
        "oneri_plaka": arac.plate if arac is not None else None,
        "oneri_baslangic_km": arac.son_km if arac is not None else None,
    }


async def bilgi_yaz(
    db: AsyncSession,
    so: ServiceOrder,
    *,
    ulasim_turu: str,
    servis_arac_id: int | None,
    baslangic_km: int | None,
    bitis_km: int | None,
    user: User,
    plaka: str | None = None,
    ip: str | None = None,
) -> None:
    if ulasim_turu not in ULASIM_TURLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen ulaşım türü: {ulasim_turu}")
    plaka_metni: str | None = None
    if ulasim_turu != "SIRKET_ARACI":
        servis_arac_id = baslangic_km = bitis_km = None
    else:
        plaka_metni = plaka_temizle(plaka)
        if plaka_metni is not None:
            # Elle yazılan plaka; havuzda varsa o araca bağlanır.
            havuz = await _havuzdaki_arac(db, plaka_metni.replace(" ", ""))
            servis_arac_id = havuz.id if havuz is not None else None
            if havuz is not None:
                plaka_metni = havuz.plate
        else:
            if servis_arac_id is None:
                servis_arac_id = await _plan_araci(db, so)
            if servis_arac_id is None:
                raise ServisGirdiHatasi("Şirket aracında plaka seçilmeli ya da yazılmalı")
            plaka_metni = (await _arac(db, servis_arac_id)).plate
        baslangic_km = _km(baslangic_km, "Başlangıç km")
        bitis_km = _km(bitis_km, "Son km")
        if bitis_km is not None and baslangic_km is None:
            raise ServisGirdiHatasi("Son km için önce başlangıç km girilmeli")
        if bitis_km is not None and baslangic_km is not None and bitis_km < baslangic_km:
            raise ServisGirdiHatasi("Son km başlangıç km'den küçük olamaz")
    so.ulasim_turu = ulasim_turu
    so.servis_arac_id = servis_arac_id
    so.arac_plaka = plaka_metni
    so.baslangic_km = baslangic_km
    so.bitis_km = bitis_km
    so.updated_by = user.id
    if servis_arac_id is not None and bitis_km is not None:
        arac = await _arac(db, servis_arac_id)
        if arac.son_km is None or bitis_km >= arac.son_km:
            arac.son_km = bitis_km
    await db.flush()
    await audit.log(
        db,
        "service_orders",
        "servis.ulasim",
        entity_id=so.id,
        new_value={
            "ulasim_turu": ulasim_turu,
            "servis_arac_id": servis_arac_id,
            "plaka": plaka_metni,
            "baslangic_km": baslangic_km,
            "bitis_km": bitis_km,
        },
        user_id=user.id,
        ip=ip,
    )


async def islem_dogrula(db: AsyncSession, so: ServiceOrder) -> None:
    """İşleme alma (İŞLEMDE) öncesi."""
    if not await zorunlu_mu(db, so):
        return
    if so.ulasim_turu is None:
        raise ServisGirdiHatasi(
            "İşleme almadan önce ulaşım bilgisi girilmeli (araç ya da toplu ulaşım)"
        )
    if so.ulasim_turu != "SIRKET_ARACI":
        return
    if so.servis_arac_id is None and not so.arac_plaka:
        raise ServisGirdiHatasi("Şirket aracıyla gidilen işte plaka zorunlu")
    if so.baslangic_km is None and await km_zorunlu_mu(db):
        raise ServisGirdiHatasi("Şirket aracıyla gidilen işte araç km zorunlu")


async def tamamlama_dogrula(db: AsyncSession, so: ServiceOrder, cozum_kanali: str) -> None:
    """Yerinde çözülerek tamamlanırken."""
    if cozum_kanali != "YERINDE" or not await zorunlu_mu(db, so):
        return
    await islem_dogrula(db, so)
    if so.ulasim_turu == "SIRKET_ARACI" and so.bitis_km is None and await km_zorunlu_mu(db):
        raise ServisGirdiHatasi("İşi tamamlamadan önce aracın son km'si girilmeli")
