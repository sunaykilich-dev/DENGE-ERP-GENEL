"""Genel stok raporundan cihaz–araç bağını kurar.

    uv run --with openpyxl python -m app.migration.stok_raporu <dosya.xlsx>
    uv run --with openpyxl python -m app.migration.stok_raporu <dosya.xlsx> --uygula

Fleet cihaz göçünde (bkz. `fleet_cihaz`) dosyada **plaka yoktu**, bu yüzden
12.934 cihaz müşteriye bağlandı ama araca bağlanamadı; cihaz–araç dönemi
uydurulamazdı. Bu rapor o eksik halkayı getiriyor: aynı cihazların IMEI'si
(12.204'ünün **hepsi** ERP'de) yanında plaka ve aktivasyon zamanı var.

**Sahip cihazdan gelir, dosyadan değil.** Raporun "Hesap" sütunu platform
kullanıcı adı ('cevat.ekinci', 'odaklojistik'); fleet dosyasındaki firma
adlarıyla aynı değil ve 208 değer için ikinci bir eşleştirme kararı
gerektirirdi. Gerek yok: cihazın müşterisi ERP'de zaten belli, araç da o
müşteriye açılır. Böylece 3.516 araç **sahibiyle birlikte** doğuyor —
`arac_kayit` dosyasında 1.618 araç sahipsiz kalacağı için açılmamıştı.

**Tarih uydurulmaz.** Dönem başlangıcı aktivasyon zamanıdır; yoksa satış
zamanı (o zaman `is_inferred` işaretlenir); ikisi de yoksa satır karantinaya
düşer. `clock.now()` yazmak garanti başlangıcını kaydın girildiği güne
kaydırırdı — bu hata bu projede bir kez yapıldı ve düzeltildi.

Açık dönemi olan cihaza DOKUNULMAZ: hak ediş göçünden gelen 470 montaj
kaydı bu raporun anlık görüntüsünden daha güvenilir, çünkü iş emrine dayanıyor.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import RealClock
from app.db import get_session_factory
from app.migration.arac_kayit import plaka_ayikla
from app.models import Device, DeviceVehicleAssignment, Vehicle
from app.models.vehicle import plaka_anahtari
from app.services import assignments as atama_svc

KAYNAK = "stok-raporu"

SUTUN = {"hesap": 0, "imei": 1, "model": 3, "aktivasyon": 7, "satis": 8, "plaka": 10}


@dataclass
class Satir:
    imei: str
    plaka: str
    an: datetime
    tahmini: bool


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: Counter = field(default_factory=Counter)


def _tarih(deger: object) -> datetime | None:
    if deger is None:
        return None
    if isinstance(deger, datetime):
        return deger if deger.tzinfo else deger.replace(tzinfo=UTC)
    metin = str(deger).strip()
    if not metin:
        return None
    try:
        return datetime.strptime(metin[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def oku(yol: Path) -> Sonuc:
    from openpyxl import load_workbook

    wb = load_workbook(yol, read_only=True, data_only=True)
    ws = wb["0"] if "0" in wb.sheetnames else wb[wb.sheetnames[-1]]
    sonuc = Sonuc()
    for ham in ws.iter_rows(min_row=2, values_only=True):
        if not ham or not ham[SUTUN["imei"]]:
            continue
        plaka_ham = str(ham[SUTUN["plaka"]] or "").strip()
        if not plaka_ham:
            sonuc.karantina["plakasiz"] += 1
            continue
        plaka, _ = plaka_ayikla(plaka_ham)
        if plaka is None:
            sonuc.karantina["plaka_bicimi_tutmuyor"] += 1
            continue
        an = _tarih(ham[SUTUN["aktivasyon"]])
        tahmini = False
        if an is None:
            an = _tarih(ham[SUTUN["satis"]])
            tahmini = True
        if an is None:
            sonuc.karantina["tarih_yok"] += 1
            continue
        sonuc.satirlar.append(
            Satir(imei=str(ham[SUTUN["imei"]]).strip(), plaka=plaka, an=an, tahmini=tahmini)
        )
    return sonuc


async def uygula(db: AsyncSession, sonuc: Sonuc, *, yaz: bool) -> Counter:
    clock = RealClock()
    cihazlar = {
        d.imei: d for d in (await db.scalars(select(Device).where(Device.imei.is_not(None)))).all()
    }
    araclar = {v.plate_key: v for v in (await db.scalars(select(Vehicle))).all() if v.plate_key}
    # Yalnız AÇIK dönemi kontrol etmek yetmiyor: hak ediş göçünden gelen
    # KAPALI bir dönem de yeni açık dönemle çakışabilir (cihaz 1646'da oldu —
    # rapor 16 Ocak diyor, ERP'de 15 Ocak–4 Şubat dönemi var). Yeni dönem
    # [an, ∞) olduğu için, biten zamanı `an`'dan SONRA olan her dönem çakışır.
    donemler: dict[int, list[tuple[datetime, datetime | None]]] = {}
    for a in (await db.scalars(select(DeviceVehicleAssignment))).all():
        donemler.setdefault(a.device_id, []).append((a.valid_from, a.valid_to))

    sayac: Counter = Counter()
    for satir in sonuc.satirlar:
        cihaz = cihazlar.get(satir.imei)
        if cihaz is None:
            sayac["cihaz_erpde_yok"] += 1
            continue
        cakisan = [(f, t) for f, t in donemler.get(cihaz.id, ()) if t is None or t > satir.an]
        if cakisan:
            # İş emrine dayanan geçmiş, bu raporun anlık görüntüsünden güvenilir.
            sayac["mevcut_donemle_cakisiyor"] += 1
            continue
        if cihaz.current_customer_id is None:
            sayac["cihazin_musterisi_yok"] += 1
            continue

        anahtar = plaka_anahtari(satir.plaka)
        arac = araclar.get(anahtar)
        if arac is None:
            sayac["arac_acildi"] += 1
            if not yaz:
                araclar[anahtar] = Vehicle(plate=satir.plaka)  # önizlemede tekrar saymamak için
                continue
            arac = Vehicle(
                plate=satir.plaka,
                customer_id=cihaz.current_customer_id,
                source_system=KAYNAK,
                source_ref=f"plaka:{anahtar}",
            )
            db.add(arac)
            await db.flush()
            araclar[anahtar] = arac
        elif arac.customer_id is None and yaz:
            arac.customer_id = cihaz.current_customer_id
            sayac["aracin_musterisi_dolduruldu"] += 1

        if not yaz:
            sayac["baglanacak"] += 1
            continue
        try:
            await atama_svc.tak(
                db,
                device_id=cihaz.id,
                vehicle_id=arac.id,
                customer_id=cihaz.current_customer_id,
                clock=clock,
                an=satir.an,
                is_inferred=satir.tahmini,
            )
        except atama_svc.AtamaHatasi as exc:
            # Çakışma önceden eleniyor; buraya düşen satır beklenmedik bir
            # durumdur ve gerekçesiyle görünmeli.
            sayac["baglanamadi"] += 1
            sonuc.karantina[f"atama: {exc}"] += 1
            continue
        donemler.setdefault(cihaz.id, []).append((satir.an, None))
        sayac["baglandi"] += 1

    if yaz:
        await db.flush()
    return sayac


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Genel stok raporu → cihaz–araç bağı")
    ayristirici.add_argument("dosya", type=Path)
    ayristirici.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    args = ayristirici.parse_args(argv)

    if not args.dosya.is_file():
        print(f"Dosya yok: {args.dosya}", file=sys.stderr)
        return 1

    sonuc = oku(args.dosya)
    print("=" * 70)
    print(f"STOK RAPORU — {len(sonuc.satirlar)} plakalı ve tarihli satır")
    print("=" * 70)

    async with get_session_factory()() as db:
        sayac = await uygula(db, sonuc, yaz=args.uygula)
        if args.uygula:
            await db.commit()

    for anahtar, adet in sorted(sayac.items()):
        print(f"  {anahtar:30s} {adet:6d}")
    if sonuc.karantina:
        print("\nALINMAYAN SATIRLAR:")
        for anahtar, adet in sonuc.karantina.most_common():
            print(f"  {anahtar:30s} {adet:6d}")

    print("\nUYGULANDI." if args.uygula else "\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
