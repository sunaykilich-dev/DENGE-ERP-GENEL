"""Montaj noktası tarifelerini "servis listesi ve ücretler" dosyasından yazar.

    uv run --with openpyxl python -m app.migration.tarife <dosya.xlsx>
    uv run --with openpyxl python -m app.migration.tarife <dosya.xlsx> --uygula

Bu, projenin en uzun süre açık kalan boşluğu: canlı uygulamada 44 montaj
noktasının tarifesinin **hepsi 0**'dı, bu yüzden yeni iş girişi fiyat
üretemiyordu (plan §8 madde 1).

**Tasarım: genel tarife + istisna.** Dosyadaki 35 fiyatlı satırın 29'u birebir
aynı (ATS 350 / Dashcam 1.000 / Harici 250). Bunları 29 ayrı noktaya tek tek
yazmak hem gereksiz hem kırılgan olurdu: ad eşleşmesi tutmayan her nokta
sessizce fiyatsız kalırdı. Bunun yerine **genel varsayılan** (`partner_id
NULL`) yazılır — `tariffs.tarife_bul` noktaya özel tarifeyi genelin üstünde
tutar, yani istisna koymak yetiyor. Böylece adı eşleşmeyen bir nokta bile
doğru fiyatı alır.

**OBD/ATS 150 TL olarak alınır.** Plan §2 #13'te bu kalem "canlı veride hiç
kullanılmamış" (ATS 706 / Dashcam 433 / Harici 96 / OBD 0) diye çıkarılmıştı;
kullanıcı 23 Eyl 2026'da geri istedi. Karşılığı yeni bir cihaz rolü:
`OBD_TAKIP` → `OBD_ATS_MONTAJ`. Kablolama olmadığı için ATS'nin yarısından
ucuz — iş emri girişinde rol seçilince fiyat kendiliğinden 150'ye düşer.

**Yürürlük tarihi dosyada yok.** `YURURLUK` ile içinde bulunulan dönemin
başından başlatılır; geçmiş hak edişler zaten satır bazında donmuş fiyat
taşıdığı için etkilenmez. Fiyatlar daha eski bir tarihten beri geçerliyse
bu sabit değiştirilip betik yeniden koşulmalıdır.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import Account, PartnerTariff

YURURLUK = datetime(2026, 9, 1, tzinfo=UTC)

# Dosyadaki sütun → ERP iş tipi.
SUTUN_IS_TIPI = {
    2: "ATS_MONTAJ",
    3: "OBD_ATS_MONTAJ",
    4: "DASHCAM_MONTAJ",
    5: "HARICI_KAMERA_MONTAJ",
}

# 35 fiyatlı satırın 29'unda geçerli olan fiyatlar.
STANDART = {
    "ATS_MONTAJ": Decimal("350"),
    "OBD_ATS_MONTAJ": Decimal("150"),
    "DASHCAM_MONTAJ": Decimal("1000"),
    "HARICI_KAMERA_MONTAJ": Decimal("250"),
}

# Standarttan sapan satırların ERP karşılığı — ELLE doğrulandı (23 Eyl 2026).
# Otomatik benzerlik burada aday bile üretmiyor: karar insanın.
ELLE_ESLESME = {
    "Beylikdüzü Hopa Elektronik – Gencay Genç": 309,
    "Tekirdağ Zfr": 330,
    "EMM Aaraç Takip": 323,
}


@dataclass
class Fiyatlar:
    ad: str
    il: str
    fiyat: dict[str, Decimal] = field(default_factory=dict)

    @property
    def standart_mi(self) -> bool:
        return self.fiyat == STANDART


def _para(deger: object) -> Decimal | None:
    if deger is None:
        return None
    metin = str(deger).strip().replace(".", "").replace(",", ".")
    if not metin:
        return None
    try:
        tutar = Decimal(metin)
    except Exception:
        return None
    return tutar if tutar > 0 else None


def oku(yol: Path) -> list[Fiyatlar]:
    from openpyxl import load_workbook

    ws = load_workbook(yol, read_only=True, data_only=True)["Sayfa1"]
    satirlar: list[Fiyatlar] = []
    for sira, ham in enumerate(ws.iter_rows(values_only=True)):
        if sira < 3 or not ham or not ham[0]:
            continue
        kayit = Fiyatlar(ad=str(ham[0]).strip(), il=str(ham[1] or "").strip())
        for sutun, is_tipi in SUTUN_IS_TIPI.items():
            tutar = _para(ham[sutun] if sutun < len(ham) else None)
            if tutar is not None:
                kayit.fiyat[is_tipi] = tutar
        if kayit.fiyat:
            satirlar.append(kayit)
    return satirlar


async def _tarife_yaz(
    db: AsyncSession, *, partner_id: int | None, is_tipi: str, fiyat: Decimal, not_metni: str
) -> str:
    """Aynı (nokta, iş tipi) için açık tarife varsa DOKUNMAZ; EXCLUDE kısıtı da
    zaten çakışmaya izin vermezdi. Var olanı kapatıp yenisini açmak fiyat
    değişikliğidir ve ayrı bir karardır."""
    mevcut = await db.scalar(
        select(PartnerTariff).where(
            PartnerTariff.partner_id.is_(None)
            if partner_id is None
            else PartnerTariff.partner_id == partner_id,
            PartnerTariff.work_type == is_tipi,
            PartnerTariff.product_group == "*",
            PartnerTariff.valid_to.is_(None),
        )
    )
    if mevcut is not None:
        return "zaten_var"
    db.add(
        PartnerTariff(
            partner_id=partner_id,
            work_type=is_tipi,
            product_group="*",
            unit_price=fiyat,
            valid_from=YURURLUK,
            notes=not_metni,
        )
    )
    return "yazildi"


async def uygula(db: AsyncSession, satirlar: list[Fiyatlar], *, yaz: bool) -> tuple[Counter, list]:
    sayac: Counter = Counter()
    cozulmeyen: list[Fiyatlar] = []

    if yaz:
        for is_tipi, fiyat in STANDART.items():
            sonuc = await _tarife_yaz(
                db,
                partner_id=None,
                is_tipi=is_tipi,
                fiyat=fiyat,
                not_metni="servis listesi ve ücretler — genel varsayılan",
            )
            sayac[f"genel_{sonuc}"] += 1
    else:
        sayac["genel_yazilacak"] = len(STANDART)

    hesaplar = {
        h.id: h.title
        for h in (await db.scalars(select(Account).where(Account.is_deleted.is_(False)))).all()
    }

    for satir in satirlar:
        if satir.standart_mi:
            sayac["standart_genelden_gelir"] += 1
            continue
        hesap_id = ELLE_ESLESME.get(satir.ad)
        if hesap_id is None or hesap_id not in hesaplar:
            cozulmeyen.append(satir)
            sayac["nokta_cozulmedi"] += 1
            continue
        for is_tipi, fiyat in satir.fiyat.items():
            if STANDART.get(is_tipi) == fiyat:
                continue  # genel tarifeyle aynı; ayrıca yazmaya gerek yok
            if yaz:
                sonuc = await _tarife_yaz(
                    db,
                    partner_id=hesap_id,
                    is_tipi=is_tipi,
                    fiyat=fiyat,
                    not_metni=f"servis listesi ve ücretler — {satir.ad}",
                )
                sayac[f"nokta_{sonuc}"] += 1
            else:
                sayac["nokta_yazilacak"] += 1
        sayac["istisna_nokta"] += 1

    if yaz:
        await db.flush()
    return sayac, cozulmeyen


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Montaj noktası tarifeleri")
    ayristirici.add_argument("dosya", type=Path)
    ayristirici.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    args = ayristirici.parse_args(argv)

    if not args.dosya.is_file():
        print(f"Dosya yok: {args.dosya}", file=sys.stderr)
        return 1

    satirlar = oku(args.dosya)
    print("=" * 70)
    print(f"TARİFE — {len(satirlar)} fiyatlı satır, yürürlük {YURURLUK:%d.%m.%Y}")
    print("=" * 70)
    for is_tipi, fiyat in STANDART.items():
        print(f"  genel  {is_tipi:22s} {fiyat:>8,.2f} ₺")

    async with get_session_factory()() as db:
        sayac, cozulmeyen = await uygula(db, satirlar, yaz=args.uygula)
        if args.uygula:
            await db.commit()

    print()
    for anahtar, adet in sorted(sayac.items()):
        print(f"  {anahtar:26s} {adet:4d}")

    if cozulmeyen:
        print(f"\nÇÖZÜLMEYEN İSTİSNA ({len(cozulmeyen)}) — ERP karşılığı belirsiz:")
        for s in cozulmeyen:
            fiyatlar = ", ".join(f"{k.split('_')[0]} {v:,.0f}" for k, v in s.fiyat.items())
            print(f"  {s.ad[:42]:42s} ({s.il[:18]}) → {fiyatlar}")
        print("  Bu noktalar GENEL tarifeden fiyatlanır; farklı olmalıysa hesap no verin.")

    print("\nUYGULANDI." if args.uygula else "\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
