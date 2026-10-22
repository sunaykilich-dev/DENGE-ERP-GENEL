"""Müşteri/lokasyon eşleştirmesi Faz 2 aday Excel'i (TS-208, E14-09 Faz 2) — HİÇBİR ŞEY YAZMAZ.

    uv run python -m app.migration.ana_veri_faz2 --kaynak servis_isi|ekipman_diger --cikti x.xlsx
    make goc-ana-veri-faz2 FAZ2=servis_isi

Faz 1 (sözleşme + Güvenlik ekipmanı) Ana Veri Kalitesi ekranından indirilir.
Faz 2 kaynakları (göçle gelmiş servis işleri ve Güvenlik dışı ekipman) bu
araçla alınır; dosya Faz 1 ile AYNI şablondadır (`veri_kalitesi.ADAY_BASLIKLARI`)
ve aynı `musteri_eslestirme` profiliyle İçe Aktarma'dan yüklenir (yalnız
`Onay=E` satırlar yazılır, ham metin korunur, idempotent). Müşteri ve
lokasyon metni boş kayıtlar ayrı sayfadadır.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx
from app.services.imports.musteri_eslestirme import FAZ2_KAYNAKLARI, faz2_adaylari
from app.services.teknik_servis import veri_kalitesi


def aday_xlsx(satirlar: list[dict]) -> bytes:
    basliklar = list(veri_kalitesi.ADAY_BASLIKLARI)
    return cok_sayfali_xlsx(
        {
            "Adaylar": Sayfa(
                basliklar, [veri_kalitesi.aday_satiri(r) for r in satirlar if not r["musterisiz"]]
            ),
            "Musterisi Bos": Sayfa(
                basliklar, [veri_kalitesi.aday_satiri(r) for r in satirlar if r["musterisiz"]]
            ),
        }
    )


async def _calistir(args: argparse.Namespace) -> int:
    from app.db import get_engine, get_session_factory

    engine = get_engine()
    try:
        async with get_session_factory()() as db:
            satirlar = await faz2_adaylari(db, args.kaynak)
            await db.rollback()
    finally:
        await engine.dispose()
    args.cikti.write_bytes(aday_xlsx(satirlar))
    bos = sum(1 for r in satirlar if r["musterisiz"])
    print(f"Faz 2 adayları ({args.kaynak}): {len(satirlar) - bos} aday, {bos} müşterisi boş")
    print(f"Dosya: {args.cikti}  (İçe Aktarma → musteri_eslestirme profili)")
    return 0


def komut_satiri(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Eşleştirme Faz 2 aday Excel'i (salt okunur)")
    ayr.add_argument("--kaynak", choices=tuple(FAZ2_KAYNAKLARI), required=True)
    ayr.add_argument("--cikti", type=Path, required=True)
    args = ayr.parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_calistir(args))


if __name__ == "__main__":
    sys.exit(komut_satiri())
