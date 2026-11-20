"""Kiralamada barkod/karekod okutma (KARARLAR 2026-11-20 §2–3).

- İade kontrolü: dönen cihazlar okutulur; sevk edilmiş ve dönmemiş seri
  cihazlarla karşılaştırılır. Seri numarasız ek ekipman için gelen adet
  girilir. Eksik/fazla varsa açıklama zorunlu; sonuç kiralama geçmişine
  (KONTROL olayı) ve denetim izine sayılarla yazılır. İade penceresi bu
  sonuçla doldurulur (okunan "iade alındı", okunmayan "müşteride" önerisi; kayıp kararı kullanıcının).
- Etiket: her kiralık cihaza değişmez bir etiket kodu; karekod ERP'deki
  etiket sayfasını açar.
- Teslim okutma: etiket sayfasından "gidişte / dönüşte teslim alındı"
  damgası tahsis satırına ve geçmişe yazılır.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Product, Rental, RentalAllocation, RentalAsset, User
from app.services import audit
from app.services.normalize import normalize_seri
from app.services.teknik_servis import kiralama_tahsis as tahsis_svc
from app.services.teknik_servis.kiralik_envanter import bulunamadi, girdi, KiralamaHatasi


@dataclass
class IadeKontrolGirdisi:
    okutulan_seriler: list[str]
    adetler: dict[int, int]
    aciklama: str | None = None
    kaydet: bool = False


async def _urun_adlari(db: AsyncSession, product_idler: set[int]) -> dict[int, str]:
    if not product_idler:
        return {}
    satirlar = await db.execute(
        select(Product.id, Product.name).where(Product.id.in_(product_idler))
    )
    return {i: ad for i, ad in satirlar.all()}


async def iade_kontrol(
    db: AsyncSession,
    kiralama: Rental,
    g: IadeKontrolGirdisi,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> dict[str, Any]:
    tahsisler = [t for t in await tahsis_svc.tahsisler(db, kiralama.id) if tahsis_svc.disarida(t) > 0]
    if not tahsisler:
        raise KiralamaHatasi("Müşteride iadesi beklenen cihaz yok")
    seri_tahsis = {t.asset_id: t for t in tahsisler if t.asset_id is not None}
    cihazlar = (
        {
            c.id: c
            for c in (
                await db.scalars(select(RentalAsset).where(RentalAsset.id.in_(seri_tahsis)))
            ).all()
        }
        if seri_tahsis
        else {}
    )
    adlar = await _urun_adlari(db, {t.product_id for t in tahsisler})
    anahtar_tahsis = {cihazlar[a].serial_key: t for a, t in seri_tahsis.items() if a in cihazlar}

    okunan: dict[str, str] = {}
    for s in g.okutulan_seriler:
        s = (s or "").strip()
        if s:
            okunan.setdefault(normalize_seri(s), s)

    satirlar: list[dict[str, Any]] = []
    eksik_seri = 0
    adet_eksik = 0
    for t in tahsisler:
        beklenen = tahsis_svc.disarida(t)
        if t.asset_id is not None:
            c = cihazlar.get(t.asset_id)
            seri = c.serial_no if c is not None else None
            geldi = c is not None and c.serial_key in okunan
            if not geldi:
                eksik_seri += 1
            satirlar.append(
                {
                    "tahsis_id": t.id,
                    "urun": adlar.get(t.product_id, ""),
                    "seri": seri,
                    "beklenen": beklenen,
                    "gelen": beklenen if geldi else 0,
                    "oneri_sonuc": "IADE_ALINDI" if geldi else "MUSTERIDE",
                }
            )
        else:
            gelen = max(0, int(g.adetler.get(t.id, 0)))
            if gelen < beklenen:
                adet_eksik += beklenen - gelen
            satirlar.append(
                {
                    "tahsis_id": t.id,
                    "urun": adlar.get(t.product_id, ""),
                    "seri": None,
                    "beklenen": beklenen,
                    "gelen": min(gelen, beklenen),
                    "oneri_sonuc": "IADE_ALINDI" if gelen > 0 else "MUSTERIDE",
                }
            )
    fazla = [orijinal for k, orijinal in okunan.items() if k not in anahtar_tahsis]
    sorun = bool(eksik_seri or adet_eksik or fazla)
    aciklama = (g.aciklama or "").strip() or None
    sonuc = {
        "satirlar": satirlar,
        "eksik_seri": eksik_seri,
        "eksik_adet": adet_eksik,
        "fazla": fazla,
        "tam": not sorun,
        "kaydedildi": False,
    }
    if not g.kaydet:
        return sonuc
    if sorun and not aciklama:
        raise girdi("Eksik ya da yanlış cihaz var; açıklama zorunlu")
    sayilar = {
        "okunan": len(okunan),
        "eksik_seri": eksik_seri,
        "eksik_adet": adet_eksik,
        "fazla": len(fazla),
    }
    await tahsis_svc.olay_yaz(
        db,
        kiralama,
        "KONTROL",
        user=user,
        clock=clock,
        alan="IADE_OKUTMA",
        yeni=sayilar,
        gerekce=aciklama,
    )
    await audit.log(
        db,
        "rentals",
        "kiralama.iade_okutma",
        entity_id=kiralama.id,
        new_value=sayilar,
        user_id=user.id,
        ip=ip,
    )
    sonuc["kaydedildi"] = True
    return sonuc


# --- Etiket (karekod) ------------------------------------------------------------------


async def etiket_kodu_ver(db: AsyncSession, cihaz: RentalAsset, *, user: User) -> str:
    """Yoksa değişmez etiket kodu üretir (tahmin edilemez, 12 karakter)."""
    if cihaz.etiket_kodu:
        return cihaz.etiket_kodu
    while True:
        kod = secrets.token_urlsafe(9)
        if await db.scalar(select(RentalAsset.id).where(RentalAsset.etiket_kodu == kod)) is None:
            break
    cihaz.etiket_kodu = kod
    cihaz.updated_by = user.id
    await db.flush()
    return kod


async def etiketten_cihaz(db: AsyncSession, kod: str) -> RentalAsset:
    cihaz = await db.scalar(
        select(RentalAsset).where(RentalAsset.etiket_kodu == kod, RentalAsset.is_deleted.is_(False))
    )
    if cihaz is None:
        raise bulunamadi("Etiket bulunamadı")
    return cihaz


async def son_tahsis(db: AsyncSession, cihaz: RentalAsset) -> RentalAllocation | None:
    """Cihazın sevk edilmiş son tahsisi (teslim okutması buna yazılır)."""
    return await db.scalar(
        select(RentalAllocation)
        .where(RentalAllocation.asset_id == cihaz.id, RentalAllocation.shipped_at.is_not(None))
        .order_by(RentalAllocation.id.desc())
        .limit(1)
    )


TESLIM_YONLERI = ("GIDIS", "DONUS")


async def teslim_okut(
    db: AsyncSession,
    kiralama: Rental,
    tahsis: RentalAllocation,
    yon: str,
    *,
    user: User,
    clock: Clock,
    not_: str | None = None,
    ip: str | None = None,
) -> RentalAllocation:
    if yon not in TESLIM_YONLERI:
        raise girdi(f"Bilinmeyen yön: {yon}")
    simdi = clock.now()
    if yon == "GIDIS":
        if tahsis.gidis_teslim_at is not None:
            raise KiralamaHatasi("Gidiş teslimi zaten okutulmuş")
        tahsis.gidis_teslim_at, tahsis.gidis_teslim_by = simdi, user.id
    else:
        if tahsis.donus_teslim_at is not None:
            raise KiralamaHatasi("Dönüş teslimi zaten okutulmuş")
        tahsis.donus_teslim_at, tahsis.donus_teslim_by = simdi, user.id
    tahsis.updated_by = user.id
    await db.flush()
    await tahsis_svc.olay_yaz(
        db,
        kiralama,
        "KONTROL",
        user=user,
        clock=clock,
        alan=f"TESLIM_{yon}",
        yeni={"tahsis_id": tahsis.id, "asset_id": tahsis.asset_id},
        gerekce=(not_ or "").strip() or None,
    )
    await audit.log(
        db,
        "rental_allocations",
        f"kiralama.teslim_{yon.lower()}",
        entity_id=tahsis.id,
        new_value={"rental_id": kiralama.id, "asset_id": tahsis.asset_id},
        user_id=user.id,
        ip=ip,
    )
    return tahsis
