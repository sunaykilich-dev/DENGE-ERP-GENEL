"""Ad eşleme göç komutları (TS-170, E13-08).

    uv run python -m app.migration.servis_ad_esleme oner --kaynak <döküm> --cikti oneriler.xlsx
    uv run python -m app.migration.servis_ad_esleme uygula

`oner`: eski dökümdeki ad metinlerini (atama, zaman kaydı, mola oturumu)
sayar; `personnel_name_maps`'e ÖNERİ satırı açar/günceller (verilmiş karar
ezilmez) ve `ad_esleme` içe aktarma profilinin şablonunda öneri Excel'i yazar.
Excel kişisel veri içerir (ad): yalnız İK ile paylaşılır.

`uygula`: onaylanmış eşlemeyi göçle gelmiş, kişisi boş zaman kayıtlarına
işler (`ad_esleme.uygula`); iki kez koşunca ikincisi 0 satır değiştirir.
Atamalar `goc-servis-uygula` yeniden koşulunca tamamlanır.

**Önce yedek** (`deploy/KURULUM.md` göç bölümü): `uygula` göç tablolarına yazar.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock, RealClock
from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx
from app.migration.servis_kaynak import KaynakDizini, KaynakHatasi, metin
from app.models import PersonnelNameMap, User
from app.services.imports.ad_esleme import SUTUNLAR
from app.services.teknik_servis import ad_esleme

# (kaynak tablo, ad kolonu, kaynak alan)
AD_KAYNAKLARI = (
    ("WorkOrderAssignments", "AssignedName", ad_esleme.ALAN_ATAMA),
    ("WorkOrderTimeLogs", "TechnicianName", ad_esleme.ALAN_ZAMAN),
    ("WorkOrderLiveSessions", "TechnicianName", ad_esleme.ALAN_CANLI_OTURUM),
)


def eski_adlar(dizin: KaynakDizini) -> list[tuple[str, str]]:
    """(kaynak alan, ham ad) — her geçiş bir eleman (sayı = kayıt adedi)."""
    sonuc: list[tuple[str, str]] = []
    for tablo, kolon, alan in AD_KAYNAKLARI:
        for s in dizin.tablo(tablo, zorunlu=False):
            ad = metin(s.get(kolon))
            if ad:
                sonuc.append((alan, ad))
    return sonuc


async def oneri_tablosu(db: AsyncSession) -> list[list[Any]]:
    """Profil sütun sırasıyla öneri/karar satırları (kayıt sayısına göre azalan)."""
    adlar = dict((await db.execute(select(User.id, User.full_name))).tuples().all())
    satirlar = (
        await db.scalars(
            select(PersonnelNameMap)
            .where(PersonnelNameMap.kaynak_sistem == ad_esleme.KAYNAK_SISTEM)
            .order_by(PersonnelNameMap.kayit_sayisi.desc(), PersonnelNameMap.normal_ad)
        )
    ).all()
    tablo: list[list[Any]] = []
    for m in satirlar:
        karar = {"ONAYLANDI": "E", "REDDEDILDI": "H", "ESLESMEDI": "ESLESMEDI"}.get(m.durum, "")
        tablo.append(
            [
                m.kaynak_alan,
                m.kaynak_ad,
                m.normal_ad,
                m.kayit_sayisi,
                m.onerilen_user_id,
                adlar.get(m.onerilen_user_id),
                karar,
                m.onaylanan_user_id,
                None,
            ]
        )
    return tablo


async def oner(db: AsyncSession, dizin: KaynakDizini, cikti: Path | None) -> dict[str, int]:
    sayac = await ad_esleme.oneri_kaydet(db, eski_adlar(dizin))
    if cikti is not None:
        cikti.write_bytes(
            cok_sayfali_xlsx(
                {"Ad Eşleme": Sayfa([s.baslik for s in SUTUNLAR], await oneri_tablosu(db))}
            )
        )
    return sayac


async def _calistir(args: argparse.Namespace, clock: Clock) -> int:
    from app.db import get_engine, get_session_factory

    engine = get_engine()
    try:
        async with get_session_factory()() as db:
            if args.komut == "oner":
                sayac = await oner(db, KaynakDizini(args.kaynak), args.cikti)
            else:
                sayac = await ad_esleme.uygula(db, clock=clock)
            await db.commit()
    finally:
        await engine.dispose()
    for k, v in sayac.items():
        print(f"  {k:20s} {v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Göç: personel ad eşleme")
    alt = ayr.add_subparsers(dest="komut", required=True)
    o = alt.add_parser("oner", help="Öneri üret ve Excel'e dök")
    o.add_argument("--kaynak", type=Path, required=True)
    o.add_argument("--cikti", type=Path)
    alt.add_parser("uygula", help="Onaylı eşlemeyi göç tablolarına işle")
    args = ayr.parse_args(argv)
    try:
        return asyncio.run(_calistir(args, RealClock()))
    except KaynakHatasi as exc:
        print(f"Kaynak okunamadı: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())
