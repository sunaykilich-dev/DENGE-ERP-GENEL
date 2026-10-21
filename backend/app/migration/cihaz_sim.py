"""Cihaz–SIM eşleştirmesini kurar.

    uv run --with openpyxl python -m app.migration.cihaz_sim <dosya.xlsx> \\
        [--aktivasyon "genel stok raporu.xlsx"] [--uygula]

Kaynak: platformun "Cihaz seçim dışa aktar" çıktısı — yalnız IMEI ve SIM
numarası. 13.517 IMEI'nin **hepsi** ERP'de; 6.421'inde SIM numarası var.

Neden gerekiyor: `sim_device_history` tablosu BOŞTU. 17.350 cihazın hiçbirinde
"bu cihazın hattı ne" sorusu cevaplanamıyordu — oysa bu, kabul kriteri 1'in
(«Bu IMEI şu an nerede, kimde, hangi araçta, **hattı ne**») bir parçası.

**Eksik hatlar açılır.** Dosyadaki 6.364 benzersiz numaranın yalnız 545'i
ERP'de kayıtlı; kalanı sahada çalışıyor ama sistemde yok. Yeni hat kaydı
projenin mevcut kuralıyla açılır: ICCID bilinmediğinde `MSISDN:<numara>` yer
tutucusu ve `field_sources.iccid = "EKSIK"` (hak ediş göçü 1.356 hattı böyle
açmıştı). Operatör alanı NOT NULL olduğu için varsayılan yazılır ve
`field_sources.operator = "VARSAYILAN"` ile işaretlenir — **uydurulmuş
değil, doğrulanmamış** demek.

**Tarih uydurulmaz, iki kaynaktan gelir:**

1. Genel stok raporundaki *aktivasyon zamanı* (6.421 satırın 4.312'sinde var)
   — gerçek geçmiş, `is_inferred=False`.
2. Yoksa satır ALINMAZ. Dosyanın dışa aktarım anını başlangıç saymak
   ("23 Eyl sabahı bu cihazda bu hat vardı") bir gözlemdir, ölçüm değil;
   kullanıcı kararı (23 Eyl 2026) bu satırların **gerçek tarihleri gelene
   kadar beklemesi** yönünde. Yine de gerekirse `--gozlem-tarihini-kullan`
   ile açılabilir; o zaman `is_inferred=True` yazılır.

**Bir SIM aynı anda tek cihazda olur.** Dosyada 29 numara birden çok cihazda
görünüyor; hangisinin doğru olduğu buradan bilinemez, hepsi karantinaya
düşer.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import RealClock
from app.db import get_session_factory
from app.models import Device, SimCard
from app.services import devices as cihaz_svc
from app.services.normalize import normalize_msisdn

KAYNAK = "cihaz-sim"
# Dosya adındaki damga: Cihaz+seçim+dışa+aktar20260923073928.xlsx
_DAMGA = re.compile(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


@dataclass
class Satir:
    imei: str
    msisdn: str


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: Counter = field(default_factory=Counter)
    cok_cihazli: set[str] = field(default_factory=set)


def disa_aktarim_ani(yol: Path) -> datetime:
    """Dosya adındaki damga; yoksa dosyanın değiştirilme zamanı.

    Bu an "gözlem zamanı" olarak kullanılır — aktivasyon tarihi bilinmeyen
    eşleşmelerin başlangıcı. `clock.now()` kullanmak yanlış olurdu: göç bir
    ay sonra koşulsa eşleşmeler bir ay sonra başlamış görünürdü.
    """
    if m := _DAMGA.search(yol.name):
        yil, ay, gun, sa, dk, sn = (int(x) for x in m.groups())
        return datetime(yil, ay, gun, sa, dk, sn, tzinfo=UTC)
    return datetime.fromtimestamp(yol.stat().st_mtime, tz=UTC)


def oku(yol: Path) -> Sonuc:
    from openpyxl import load_workbook

    wb = load_workbook(yol, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    sonuc = Sonuc()
    sim_cihaz: dict[str, set[str]] = defaultdict(set)

    for ham in ws.iter_rows(min_row=2, values_only=True):
        if not ham or not ham[0]:
            continue
        imei = str(ham[0]).strip()
        sim = str(ham[1] or "").strip()
        if not sim:
            sonuc.karantina["sim_bos"] += 1
            continue
        try:
            msisdn = normalize_msisdn(sim)
        except ValueError:
            sonuc.karantina["numara_cozulmedi"] += 1
            continue
        sim_cihaz[msisdn].add(imei)
        sonuc.satirlar.append(Satir(imei=imei, msisdn=msisdn))

    sonuc.cok_cihazli = {s for s, c in sim_cihaz.items() if len(c) > 1}
    return sonuc


def aktivasyon_tarihleri(yol: Path) -> dict[str, datetime]:
    """Genel stok raporundan IMEI → aktivasyon zamanı."""
    from openpyxl import load_workbook

    wb = load_workbook(yol, read_only=True, data_only=True)
    ws = wb["0"] if "0" in wb.sheetnames else wb[wb.sheetnames[-1]]
    tarihler: dict[str, datetime] = {}
    for ham in ws.iter_rows(min_row=2, values_only=True):
        if not ham or not ham[1] or not ham[7]:
            continue
        ham_tarih = ham[7]
        if isinstance(ham_tarih, datetime):
            tarihler[str(ham[1]).strip()] = ham_tarih.replace(tzinfo=UTC)
            continue
        try:
            tarihler[str(ham[1]).strip()] = datetime.strptime(
                str(ham_tarih)[:19], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=UTC)
        except ValueError:
            continue
    return tarihler


async def uygula(
    db: AsyncSession,
    sonuc: Sonuc,
    *,
    gozlem_ani: datetime,
    aktivasyon: dict[str, datetime],
    gozlem_kullan: bool,
    yaz: bool,
) -> Counter:
    clock = RealClock()
    cihazlar = {
        d.imei: d for d in (await db.scalars(select(Device).where(Device.imei.is_not(None)))).all()
    }
    hatlar = {h.msisdn: h for h in (await db.scalars(select(SimCard))).all() if h.msisdn}
    bagli_cihaz = set()
    for k in (await db.scalars(select(cihaz_svc.SimDeviceHistory))).all():
        if k.valid_to is None:
            bagli_cihaz.add(k.device_id)

    sayac: Counter = Counter()
    for satir in sonuc.satirlar:
        if satir.msisdn in sonuc.cok_cihazli:
            sayac["sim_birden_cok_cihazda"] += 1
            continue
        cihaz = cihazlar.get(satir.imei)
        if cihaz is None:
            sayac["cihaz_erpde_yok"] += 1
            continue
        if cihaz.id in bagli_cihaz:
            sayac["zaten_hatli"] += 1
            continue

        if satir.imei not in aktivasyon and not gozlem_kullan:
            # Hat kaydını da açma: bağlanmayacak bir hattı şimdi açmak,
            # gerçek veri gelince ikinci bir kayıt riski doğurur.
            sayac["tarih_yok_beklemede"] += 1
            continue

        hat = hatlar.get(satir.msisdn)
        if hat is None:
            sayac["hat_acildi"] += 1
            if not yaz:
                # Önizlemede hat yazılmaz; bağlantı sayısı doğru çıksın diye
                # yer tutucu konur ve akış devam eder.
                hatlar[satir.msisdn] = SimCard(msisdn=satir.msisdn)
                hat = hatlar[satir.msisdn]
            else:
                hat = SimCard(
                    iccid=f"MSISDN:{satir.msisdn}",
                    msisdn=satir.msisdn,
                    status="AKTIF",
                    field_sources={"iccid": "EKSIK", "operator": "VARSAYILAN"},
                    source_system=KAYNAK,
                    source_ref=f"msisdn:{satir.msisdn}",
                )
                db.add(hat)
                await db.flush()
                hatlar[satir.msisdn] = hat

        an = aktivasyon.get(satir.imei)
        tahmini = an is None
        an = an or gozlem_ani
        sayac["tarih_gozlemden" if tahmini else "tarih_aktivasyondan"] += 1

        if not yaz:
            sayac["baglanacak"] += 1
            bagli_cihaz.add(cihaz.id)
            continue
        try:
            await cihaz_svc.hat_tak(
                db, device_id=cihaz.id, sim_id=hat.id, clock=clock, an=an, is_inferred=tahmini
            )
        except cihaz_svc.EslemeHatasi:
            sayac["baglanamadi"] += 1
            continue
        bagli_cihaz.add(cihaz.id)
        sayac["baglandi"] += 1

    if yaz:
        await db.flush()
    return sayac


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Cihaz–SIM eşleştirmesi")
    ayristirici.add_argument("dosya", type=Path)
    ayristirici.add_argument(
        "--aktivasyon", type=Path, help="Genel stok raporu (aktivasyon zamanları için)"
    )
    ayristirici.add_argument(
        "--gozlem-tarihini-kullan",
        action="store_true",
        help="Aktivasyon tarihi bilinmeyen satırları dosyanın dışa aktarım anıyla yaz "
        "(is_inferred). Varsayılan KAPALI — gerçek tarih beklenir.",
    )
    ayristirici.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    args = ayristirici.parse_args(argv)

    if not args.dosya.is_file():
        print(f"Dosya yok: {args.dosya}", file=sys.stderr)
        return 1

    sonuc = oku(args.dosya)
    gozlem = disa_aktarim_ani(args.dosya)
    aktivasyon = aktivasyon_tarihleri(args.aktivasyon) if args.aktivasyon else {}

    print("=" * 70)
    print(f"CİHAZ–SIM — {len(sonuc.satirlar)} numaralı satır")
    print(f"  gözlem anı (dosya damgası): {gozlem:%d.%m.%Y %H:%M}")
    print(f"  aktivasyon tarihi bilinen : {len(aktivasyon)} cihaz")
    print("=" * 70)

    async with get_session_factory()() as db:
        sayac = await uygula(
            db,
            sonuc,
            gozlem_ani=gozlem,
            aktivasyon=aktivasyon,
            gozlem_kullan=args.gozlem_tarihini_kullan,
            yaz=args.uygula,
        )
        if args.uygula:
            await db.commit()

    for anahtar, adet in sorted(sayac.items()):
        print(f"  {anahtar:26s} {adet:6d}")
    if sonuc.karantina or sonuc.cok_cihazli:
        print("\nALINMAYAN:")
        for anahtar, adet in sonuc.karantina.most_common():
            print(f"  {anahtar:26s} {adet:6d}")
        if sonuc.cok_cihazli:
            print(f"  {'birden cok cihazda SIM':26s} {len(sonuc.cok_cihazli):6d}")

    print("\nUYGULANDI." if args.uygula else "\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
