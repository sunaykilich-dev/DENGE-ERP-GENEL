"""FORA dosyasından TARİHSİZ cihaz–araç eşleştirmesi.

    uv run --with openpyxl python -m app.migration.fora_cihaz_arac <dosya.xlsx> [--uygula]

`fora.py` göçü araç kayıtlarını sahibiyle birlikte AÇMIŞTI ama cihaz–araç
bağını kurmamıştı; gerekçe dosyanın başında yazılı: "dosyada plaka var ama
tarih yok; cihaz–araç dönemi tarihsiz açılamaz". O zaman şema buna izin
vermiyordu. `8c41d2b7e903` ile izin veriyor — cihaz–hat tarafında verilen
kararın (`5d1a029e1a46`) aynısı.

Ölçüm (28 Eyl 2026, 3.451 satır):

    araca bağlanabilir ........... 2.783
    cihazın zaten aracı var .........  287
    plaka çözülemedi ................  375   ("MONTAJDA", plaka yerine IMEI)
    IMEI çözülemedi .................    6

**Her plaka ERP'de zaten var** — `fora.py` onları açmıştı. Bu betik ARAÇ
AÇMAZ: açsaydı, plakası bozuk bir satır sessizce yeni bir araç üretirdi.

**Tarih YAZILMAZ** (`valid_from = NULL`). Satır "bu cihaz bu araçta" der,
"ne zamandan beri" demez.

**Mevcut döneme DOKUNULMAZ.** Cihazın açık bir araç dönemi varsa satır
atlanır: tarihli gerçek kayıt, tarihsiz tahminle değiştirilmez.

**Müşteri dosyadan DEĞİL cihazdan alınır.** `devices.current_customer_id`
`fora.py` göçünde hesap eşleştirme kuralıyla (benzerlik ≥0.95) yazıldı;
firma adını burada ikinci kez yorumlamak iki dosyada iki farklı sonuç
üretirdi.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.migration.arac_kayit import imei_cikar, plaka_ayikla
from app.models import Device, DeviceVehicleAssignment, Vehicle
from app.models.vehicle import plaka_anahtari

KAYNAK = "fora-cihaz-arac"

# Dosya düzeni: FirmName | Plate | DeviceNo | Cihat tipi | GsmNo
SUTUN_PLAKA = 1
SUTUN_IMEI = 2


@dataclass
class Satir:
    imei: str
    plaka: str


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: Counter = field(default_factory=Counter)
    cok_araclı_imei: set[str] = field(default_factory=set)


def oku(yol: Path) -> Sonuc:
    from openpyxl import load_workbook

    wb = load_workbook(yol, read_only=True, data_only=True)
    # Dosyada pivot sayfaları da var; veri sayfası başlığından bulunur.
    ws = None
    for ad in wb.sheetnames:
        basliklar = [str(h or "").strip().lower() for h in next(wb[ad].iter_rows(values_only=True))]
        if "deviceno" in basliklar:
            ws = wb[ad]
            break
    if ws is None:
        raise SystemExit("Veri sayfası bulunamadı: 'DeviceNo' başlıklı sayfa yok.")

    sonuc = Sonuc()
    ham_satirlar: list[Satir] = []
    for ham in ws.iter_rows(min_row=2, values_only=True):
        if not ham or len(ham) <= SUTUN_IMEI:
            continue
        # Sıfır dizisi Luhn'dan GEÇER (toplam 0); düzeni bozuk 30 satır
        # oradan sızardı.
        imei = imei_cikar(ham[SUTUN_IMEI])
        if not imei or set(imei) == {"0"}:
            sonuc.karantina["imei_cozulemedi"] += 1
            continue
        # "MONTAJDA", plaka yerine yazılmış IMEI, firma eki taşıyan plaka…
        plaka, _ek = plaka_ayikla(str(ham[SUTUN_PLAKA] or ""))
        if not plaka:
            sonuc.karantina["plaka_cozulemedi"] += 1
            continue
        ham_satirlar.append(Satir(imei=imei, plaka=plaka))
    wb.close()

    # Aynı IMEI iki farklı plakada görünüyorsa hangisinin doğru olduğu
    # buradan bilinemez; bir cihaz aynı anda tek araçta olabilir.
    imei_plaka: dict[str, set[str]] = defaultdict(set)
    for s in ham_satirlar:
        imei_plaka[s.imei].add(plaka_anahtari(s.plaka))
    sonuc.cok_araclı_imei = {i for i, p in imei_plaka.items() if len(p) > 1}

    for s in ham_satirlar:
        if s.imei in sonuc.cok_araclı_imei:
            sonuc.karantina["imei_birden_cok_plakada"] += 1
            continue
        sonuc.satirlar.append(s)
    return sonuc


async def uygula(db: AsyncSession, sonuc: Sonuc, *, yaz: bool) -> dict[str, int]:
    sayac: Counter = Counter()

    cihazlar = {
        c.imei: c
        for c in (await db.scalars(select(Device).where(Device.imei.is_not(None)))).all()
        if c.imei
    }
    araclar = {v.plate_key: v for v in (await db.scalars(select(Vehicle))).all() if v.plate_key}
    bagli_cihazlar = {
        a.device_id
        for a in (
            await db.scalars(
                select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.valid_to.is_(None))
            )
        ).all()
    }

    for satir in sonuc.satirlar:
        cihaz = cihazlar.get(satir.imei)
        if cihaz is None:
            sayac["cihaz_erpde_yok"] += 1
            continue
        if cihaz.id in bagli_cihazlar:
            sayac["cihazin_zaten_araci_var"] += 1
            continue
        arac = araclar.get(plaka_anahtari(satir.plaka))
        if arac is None:
            # Araç AÇILMAZ: plakası bozuk bir satır sessizce araç üretmesin.
            sayac["arac_erpde_yok"] += 1
            continue

        if yaz:
            db.add(
                DeviceVehicleAssignment(
                    device_id=cihaz.id,
                    vehicle_id=arac.id,
                    # Müşteri cihazdan gelir; firma adı burada ikinci kez
                    # yorumlanmaz.
                    customer_id=cihaz.current_customer_id,
                    valid_from=None,
                    # `is_inferred` TARİH tahmini demek; burada tahmin yok,
                    # tarih hiç yok. Ayrımı korumak için işaretlenmez.
                    is_inferred=False,
                )
            )
            bagli_cihazlar.add(cihaz.id)
        sayac["eslesme"] += 1

    return dict(sayac)


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FORA dosyasından tarihsiz cihaz–araç eşleştirmesi")
    ap.add_argument("dosya", type=Path)
    ap.add_argument("--uygula", action="store_true", help="Yazar; verilmezse yalnız önizler.")
    args = ap.parse_args(argv)

    sonuc = oku(args.dosya)
    print("=" * 66)
    print("FORA CİHAZ–ARAÇ EŞLEŞTİRMESİ" + ("" if args.uygula else " — ÖNİZLEME"))
    print("=" * 66)
    print(f"  kullanılabilir satır      : {len(sonuc.satirlar)}")
    print(f"  IMEI'si birden çok plakada: {len(sonuc.cok_araclı_imei)} IMEI")
    for neden, adet in sorted(sonuc.karantina.items()):
        print(f"  karantina · {neden:24}: {adet}")

    async with get_session_factory()() as db:
        sayac = await uygula(db, sonuc, yaz=args.uygula)
        print()
        for ad, adet in sorted(sayac.items()):
            print(f"  {ad:26}: {adet}")
        if args.uygula:
            await db.commit()
            print("\nUYGULANDI. Tarihsiz eşleşmeler yazıldı (valid_from = NULL).")
        else:
            print("\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
