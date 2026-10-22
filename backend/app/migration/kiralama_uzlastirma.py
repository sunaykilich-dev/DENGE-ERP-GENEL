"""Kiralama pilot verisi uzlaştırma raporu — SALT OKUNUR (TS-205, E06-09).

    uv run python -m app.migration.kiralama_uzlastirma --kaynak <döküm> [--cikti x.xlsx]
    make goc-kiralama-uzlastirma KAYNAK=<döküm>

Yalnız döküm dosyalarını okur; veritabanına BAĞLANMAZ. İki çıktı üretir:

- uzlaştırma raporu (dört uyumsuzluk türünün sayısı ve satır listesi,
  kiralama bazında hesaplanan yeni durum);
- `<cikti>_kiralik_envanter.xlsx` — `kiralik_envanter_goc` profil şablonunda
  karar dosyası. Göç sorumlusu `Depo Id` ve gerekirse `Durum`'u doldurup İçe
  Aktarma'dan yükler; "Uyumsuzluk" sütunu dolu satırlar yalnız açık kararla
  yazılır (kural ve gerekçe: `services/imports/kiralama_goc.py`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx
from app.migration.servis_kaynak import KaynakDizini, KaynakHatasi
from app.services.imports import kiralama_goc


def karar_xlsx(dizin: KaynakDizini, u: kiralama_goc.KiralamaUzlastirma) -> bytes:
    return cok_sayfali_xlsx(
        {
            "Kiralik Envanter": Sayfa(
                kiralama_goc.KARAR_BASLIKLARI, kiralama_goc.envanter_karar_satirlari(dizin, u)
            )
        }
    )


def komut_satiri(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Kiralama pilot verisi uzlaştırma (salt okunur)")
    ayr.add_argument("--kaynak", type=Path, required=True, help="CSV döküm dizini")
    ayr.add_argument("--cikti", type=Path, help="Uzlaştırma raporu xlsx")
    args = ayr.parse_args(argv)
    try:
        dizin = KaynakDizini(args.kaynak)
        u = kiralama_goc.uzlastirma(dizin)
    except KaynakHatasi as exc:
        print(f"Kaynak okunamadı: {exc}", file=sys.stderr)
        return 1
    print("=" * 72)
    print("KİRALAMA PİLOT UZLAŞTIRMASI (SALT OKUNUR — HİÇBİR ŞEY YAZILMADI)")
    print("=" * 72)
    for tablo, adet in u.kaynak_sayilari.items():
        print(f"  {tablo:28s}{adet:>8}")
    for kod, ad in kiralama_goc.UYUMSUZLUK_TURLERI:
        print(f"  {ad:46s}{u.sayilar[kod]:>6}")
    if args.cikti:
        args.cikti.write_bytes(kiralama_goc.uzlastirma_xlsx(u))
        karar = args.cikti.with_name(args.cikti.stem + "_kiralik_envanter.xlsx")
        karar.write_bytes(karar_xlsx(dizin, u))
        print(f"\nRapor: {args.cikti}\nKarar dosyası (kiralik_envanter_goc profili): {karar}")
    return 0


if __name__ == "__main__":
    sys.exit(komut_satiri())
