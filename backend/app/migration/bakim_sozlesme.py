"""Bakım sözleşmesi göçü, adım 1: eski döküm → ayrıştırılmış TEYİT Excel'i (TS-173).

    uv run python -m app.migration.bakim_sozlesme --kaynak <döküm dizini> \\
        --cikti bakim_teyit.xlsx [--ucret]

Eski `MaintenanceContracts` satırlarında dönem, adet ve frekans serbest
metindir ("01.01.2026 - 31.12.2026", "9 X-RAY + 8 KAPI DEDEKTÖRÜ"). Bu betik
yalnız GÜVENLE ayrıştırılabileni doldurur; ayrıştırılamayan alan BOŞ kalır ve
sözleşme `TEYIT_BEKLIYOR` + gerekçe ile listelenir (tarih/adet uydurulmaz).
Çıktı `bakim_sozlesme` içe aktarma profilinin şablonudur: `SERVIS_YONETICI`
eksikleri doldurup İçe Aktarma ekranından yükler (adım 2).

**Ücret kolonları varsayılan olarak YAZILMAZ** (E04-D03): teyit listesi ücret
görmeyen servis yöneticisine gider. `--ucret` yalnız `maliyet.gor` sahibine
verilecek dosya için kullanılır.

Betik hiçbir veritabanına yazmaz; DB'ye bağlanmaz.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx
from app.migration.servis_kaynak import KaynakDizini, KaynakHatasi, bit, kaynak_ref, metin, tamsayi
from app.services.imports.bakim_sozlesme import SUTUNLAR, UCRET_SUTUNLARI
from app.services.normalize import tr_normkey

KAYNAK_TABLO = "MaintenanceContracts"
_NO = re.compile(r"^BAKIM-\d{4,}$")
_TARIH = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")
# "9 X-RAY", "X-RAY: 9", "X RAY (9)" — sayı tür adına bitişik olmalı.
_TUR_DESENLERI = {
    "xray": r"x\s*-?\s*ray",
    "kapi": r"kapi(?:\s+tipi)?(?:\s+metal)?\s+dedektor\w*|kapi",
}


def urun_adetleri(ham: str | None) -> dict[str, int | None]:
    """Ürün metninden tür başına adet. Bulunamayan tür None (0 DEĞİL)."""
    k = tr_normkey(ham)
    sonuc: dict[str, int | None] = {"xray": None, "kapi": None}
    if not k:
        return sonuc
    for tur, desen in _TUR_DESENLERI.items():
        once = re.search(rf"(\d+)\s*(?:adet\s*)?(?:{desen})", k)
        sonra = re.search(rf"(?:{desen})\s*[:(x]?\s*(\d+)", k)
        bulunan = once or sonra
        if bulunan:
            sonuc[tur] = int(bulunan.group(1))
    return sonuc


def donem_coz(ham: str | None) -> tuple[date | None, date | None]:
    """ "GG.AA.YYYY - GG.AA.YYYY" → (başlangıç, bitiş); tek/bozuk tarih → (None, None)."""
    bulunan = _TARIH.findall(ham or "")
    if len(bulunan) != 2:
        return None, None
    try:
        bas, bit_ = (date(int(y), int(a), int(g)) for g, a, y in bulunan)
    except ValueError:
        return None, None
    if bit_ < bas:
        return None, None
    return bas, bit_


def teyit_satirlari(
    kaynak: list[dict[str, Any]], *, ucret: bool = False
) -> tuple[list[list[Any]], list[list[Any]]]:
    """(profil satırları, reddedilen satırlar). Başlık sırası = profil sütunları."""
    sutunlar = [s for s in SUTUNLAR if ucret or s.alan not in UCRET_SUTUNLARI]
    satirlar: list[list[Any]] = []
    reddedilen: list[list[Any]] = []
    for sira, s in enumerate(kaynak, start=1):
        try:
            kimlik = tamsayi(s.get("MaintenanceContractId"))
        except ValueError:
            kimlik = None
        if kimlik is None:
            reddedilen.append([sira, "MaintenanceContractId yok"])
            continue
        bas, bit_ = donem_coz(s.get("PeriodText"))
        adetler = urun_adetleri(s.get("ProductsText"))
        frekans = tamsayi(s.get("AnnualFrequency")) or None
        if frekans is not None and not 1 <= frekans <= 12:
            frekans = None
        eksik = [
            ad
            for ad, deger in (
                ("dönem", bas),
                ("frekans", frekans),
                ("X-Ray adedi", adetler["xray"]),
                ("kapı adedi", adetler["kapi"]),
            )
            if deger is None
        ]
        aktif = bit(s.get("IsActive"), varsayilan=True)
        kaynak_no = (metin(s.get("SourceKey")) or "").upper()
        notlar = metin(s.get("CurrentAddress"))
        degerler = {
            "kaynak": kaynak_ref(KAYNAK_TABLO, kimlik),
            "sozlesme_no": kaynak_no if _NO.match(kaynak_no) else None,
            "birim": "GUVENLIK",
            "musteri": metin(s.get("CustomerName")),
            # V1'de sözleşmenin "müşteri"si çoğu kez gidilen tesistir (AVM adı).
            "tesis": metin(s.get("CustomerName")),
            "hesap_id": None,
            "lokasyon_id": None,
            "baslangic": bas.strftime("%d.%m.%Y") if bas else None,
            "bitis": bit_.strftime("%d.%m.%Y") if bit_ else None,
            "frekans": frekans,
            "xray": adetler["xray"],
            "kapi": adetler["kapi"],
            "durum": "TEYIT_BEKLIYOR" if aktif else "PASIF",
            "teyit_gerekcesi": (
                "Göç: teyit bekliyor" + (" (eksik: " + ", ".join(eksik) + ")" if eksik else "")
            ),
            "eski_urun": metin(s.get("ProductsText")),
            "eski_donem": metin(s.get("PeriodText")),
            "eski_frekans": metin(s.get("FrequencyText")),
            "eski_tamamlanan": tamsayi(s.get("CompletedCount")),
            "notlar": f"Eski adres: {notlar}" if notlar else None,
            "ucret_ziyaret": None,
            "ucret_toplam": metin(s.get("ContractTotal")),
            "ucret_metin": metin(s.get("MaintenanceFeeText")),
        }
        satirlar.append([degerler[c.alan] for c in sutunlar])
    return satirlar, reddedilen


def main(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Bakım sözleşmesi teyit Excel'i (yazmaz)")
    ayr.add_argument("--kaynak", type=Path, required=True, help="CSV döküm dizini")
    ayr.add_argument("--cikti", type=Path, required=True, help="xlsx teyit listesi")
    ayr.add_argument(
        "--ucret", action="store_true", help="Ücret kolonlarını ekle (yalnız maliyet.gor sahibine)"
    )
    args = ayr.parse_args(argv)
    try:
        kaynak = KaynakDizini(args.kaynak).tablo(KAYNAK_TABLO)
    except KaynakHatasi as exc:
        print(f"Kaynak okunamadı: {exc}", file=sys.stderr)
        return 1
    satirlar, reddedilen = teyit_satirlari(kaynak, ucret=args.ucret)
    sutunlar = [s for s in SUTUNLAR if args.ucret or s.alan not in UCRET_SUTUNLARI]
    sayfalar = {"Teyit": Sayfa([s.baslik for s in sutunlar], satirlar)}
    if reddedilen:
        sayfalar["Reddedilen"] = Sayfa(["Kaynak Satır", "Neden"], reddedilen)
    args.cikti.write_bytes(cok_sayfali_xlsx(sayfalar))
    print(
        f"{len(kaynak)} kaynak satırı: {len(satirlar)} teyit listesine, "
        f"{len(reddedilen)} reddedildi. Dosya: {args.cikti}"
    )
    print("Ücret kolonları: " + ("EKLENDİ" if args.ucret else "yok (varsayılan)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
