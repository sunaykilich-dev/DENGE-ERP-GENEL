"""`dengemobil-fora.xlsx` — firma bazlı cihaz listesini ERP'ye alır.

    uv run --with openpyxl python -m app.migration.fora <dosya.xlsx>
    uv run --with openpyxl python -m app.migration.fora <dosya.xlsx> --uygula

Sütunlar: FirmName | Plate | DeviceNo | Cihaz tipi | GsmNo (teyit edildi).
`DeviceNo` 17 hane ve IMEI DEĞİL — ilk 15 hane IMEI (3.445/3.451 Luhn tutuyor),
son iki hane yazılım sürümü; `arac_kayit.imei_cikar` ile çözülür.

**Kullanıcı kuralı (23 Eyl 2026): "firma adında Denge dışında bir şey
yazıyorsa müşteridedir."** Yani `DENGEMOBİL ADMİN` ve `DENGEMOBİL TEST`
altındaki 148 cihaz Denge'nin kendi stoğu (STOKTA / MERKEZ_DEPO), kalan
3.303'ü müşteride (AKTIF / MUSTERI).

**Hesap eşleştirme kuralı da kullanıcınındır** (fleet göçünde konuldu):
benzerlik ≥0.95 ise mevcut hesapla birleşir, altındaysa yeni hesap açılır.
Aynı `fleet_cihaz._adaylari_bul` kullanılır — puanlama ayrışsaydı "0.95"
iki dosyada farklı şey demek olurdu.

**Ürün: etikete değil TAC'a bakılır.** "Cihaz tipi" sütunu yalnız üreticiyi
söylüyor (armoli/teltonika), model yok. IMEI'nin ilk 8 hanesi (TAC) modeli
belirler; ERP'de aynı TAC'ı taşıyan cihazlar TEK ürüne işaret ediyorsa o ürün
kullanılır. Teltonika'nın TAC'ları FMB920'ye düşüyor — 52 satırda "armoli"
yazmasına rağmen TAC Teltonika; etiket değil TAC kazanır.

Armoli TAC'larının hiçbiri tekil değil (her biri L300 / L300-GO / L300-PRO
karışımı, ~%85 L300). Çoğunluğa bakıp L300 yazmak yüzlerce cihaza yanlış model
yazmak olurdu; bunun yerine **`ARMOLI-BELIRSIZ` yer tutucu ürünü** açılır.
Bilmediğimizi söylemek, yanlış bilmekten iyidir — model sonradan toplu
düzeltilebilir.

**Cihaz–araç bağı KURULMAZ.** Dosyada plaka var ama TARİH YOK; cihaz–araç
dönemi tarihsiz açılamaz (garanti başlangıcı ve zaman çizelgesi ondan gelir).
Araç kaydı sahibiyle birlikte açılır, bağ sonraki bir kaynağa bırakılır
(bkz. `stok_raporu` — orada aktivasyon zamanı vardı).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import RealClock
from app.db import get_session_factory
from app.migration.arac_kayit import imei_cikar, plaka_ayikla
from app.migration.esleme import kaynak_ref
from app.migration.fleet_cihaz import _adaylari_bul
from app.models import Account, Device, Product, Vehicle
from app.models.vehicle import plaka_anahtari
from app.services import stock as stok_svc
from app.services.normalize import tr_normkey

KAYNAK = "fora"
ESIK = 0.95

# Model bilinmediğinde kullanılan yer tutucu ürünler.
YER_TUTUCU = {
    "armoli": ("ARMOLI-BELIRSIZ", "Armoli (model belirsiz)", "Armoli"),
    "teltonika": ("TELTONIKA-BELIRSIZ", "Teltonika (model belirsiz)", "Teltonika"),
}


@dataclass
class Satir:
    firma: str
    imei: str
    plaka: str | None
    tip: str


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: Counter = field(default_factory=Counter)


def denge_mi(firma: str) -> bool:
    """Kullanıcı kuralı: adında Denge geçmiyorsa cihaz müşteridedir."""
    return "denge" in firma.lower()


def oku(yol: Path) -> Sonuc:
    from openpyxl import load_workbook

    ws = load_workbook(yol, read_only=True, data_only=True)["Sayfa1"]
    sonuc = Sonuc()
    for ham in ws.iter_rows(min_row=2, values_only=True):
        if not ham or not ham[0] or not ham[2]:
            continue
        imei = imei_cikar(str(ham[2]))
        if imei is None:
            sonuc.karantina["imei_cozulmedi"] += 1
            continue
        plaka, _ = plaka_ayikla(str(ham[1] or ""))
        if ham[1] and plaka is None:
            sonuc.karantina["plaka_bicimi_tutmuyor"] += 1
        sonuc.satirlar.append(
            Satir(
                firma=str(ham[0]).strip(),
                imei=imei,
                plaka=plaka,
                tip=str(ham[3] or "").strip().lower(),
            )
        )
    return sonuc


async def _tac_urunleri(db: AsyncSession) -> dict[str, int]:
    """TAC (IMEI ilk 8) → ürün; yalnız TEK ürüne işaret eden TAC'lar."""
    sayim: dict[str, Counter] = defaultdict(Counter)
    for imei, urun_id in (
        await db.execute(select(Device.imei, Device.product_id).where(Device.imei.is_not(None)))
    ).all():
        sayim[imei[:8]][urun_id] += 1
    return {t: c.most_common(1)[0][0] for t, c in sayim.items() if len(c) == 1}


async def _yer_tutucu_urun(db: AsyncSession, tip: str, *, yaz: bool) -> int | None:
    veri = YER_TUTUCU.get(tip)
    if veri is None:
        return None
    kod, ad, marka = veri
    urun = await db.scalar(select(Product).where(Product.code == kod))
    if urun is not None:
        return urun.id
    if not yaz:
        return -1  # önizlemede "açılacak" demek
    urun = Product(
        code=kod,
        name=ad,
        brand=marka,
        identity_kind="IMEI",
        source_system=KAYNAK,
        source_ref=f"urun:{kod}",
    )
    db.add(urun)
    await db.flush()
    return urun.id


async def _hesaplari_coz(
    db: AsyncSession, firmalar: list[str], *, yaz: bool
) -> tuple[dict[str, int], Counter, list[tuple[str, str]]]:
    hesaplar = (await db.scalars(select(Account).where(Account.is_deleted.is_(False)))).all()
    anahtar = {h.title_key: h for h in hesaplar}
    anahtarlar = list(anahtar)

    eslesme: dict[str, int] = {}
    sayac: Counter = Counter()
    acilanlar: list[tuple[str, str]] = []
    for firma in firmalar:
        k = tr_normkey(firma)
        hedef = anahtar.get(k)
        yol = "birebir"
        if hedef is None:
            adaylar = _adaylari_bul(k, anahtar, anahtarlar)
            ust = adaylar[0] if adaylar else None
            if ust and ust["benzerlik"] >= ESIK:
                hedef = next(h for h in hesaplar if h.id == ust["id"])
                yol = "benzerlik"
        if hedef is not None:
            eslesme[firma] = hedef.id
            sayac[f"hesap_{yol}"] += 1
            continue
        sayac["hesap_acildi"] += 1
        acilanlar.append((firma, ""))
        if not yaz:
            # Önizlemede hesap açılmıyor; yine de bu firmanın satırları
            # sayılsın diye yer tutucu kimlik konur (yazılmaz).
            eslesme[firma] = -1
            continue
        ref = kaynak_ref("hesap", firma)
        var = await db.scalar(
            select(Account).where(Account.source_system == KAYNAK, Account.source_ref == ref)
        )
        if var is None:
            var = Account(
                title=firma,
                title_key=k,
                is_musteri=True,
                source_system=KAYNAK,
                source_ref=ref,
            )
            db.add(var)
            await db.flush()
        eslesme[firma] = var.id
    return eslesme, sayac, acilanlar


async def uygula(db: AsyncSession, sonuc: Sonuc, *, yaz: bool) -> tuple[Counter, list]:
    clock = RealClock()
    an = datetime.now(UTC)

    firmalar = sorted({s.firma for s in sonuc.satirlar})
    hesap_id, sayac, acilanlar = await _hesaplari_coz(db, firmalar, yaz=yaz)

    tac_urun = await _tac_urunleri(db)
    yer_tutucu: dict[str, int | None] = {}
    mevcut = {
        d.imei for d in (await db.scalars(select(Device).where(Device.imei.is_not(None)))).all()
    }
    araclar = {v.plate_key: v for v in (await db.scalars(select(Vehicle))).all() if v.plate_key}

    for satir in sonuc.satirlar:
        denge = denge_mi(satir.firma)
        sahip = None if denge else hesap_id.get(satir.firma)
        if not denge and sahip is None:
            sayac["hesap_cozulmedi"] += 1
            continue
        if sahip == -1:  # önizleme yer tutucusu
            sahip = None

        # Araç: sahibi biliniyorsa açılır; cihaz–araç BAĞI kurulmaz (tarih yok).
        if satir.plaka and sahip is not None:
            anahtar = plaka_anahtari(satir.plaka)
            if anahtar not in araclar:
                sayac["arac_acildi"] += 1
                if yaz:
                    arac = Vehicle(
                        plate=satir.plaka,
                        customer_id=sahip,
                        source_system=KAYNAK,
                        source_ref=f"plaka:{anahtar}",
                    )
                    db.add(arac)
                    araclar[anahtar] = arac
                else:
                    araclar[anahtar] = Vehicle(plate=satir.plaka)

        if satir.imei in mevcut:
            sayac["cihaz_zaten_vardi"] += 1
            continue

        urun_id = tac_urun.get(satir.imei[:8])
        if urun_id is not None:
            sayac["urun_tacten"] += 1
        else:
            if satir.tip not in yer_tutucu:
                yer_tutucu[satir.tip] = await _yer_tutucu_urun(db, satir.tip, yaz=yaz)
            urun_id = yer_tutucu[satir.tip]
            if urun_id is None:
                sayac["urun_bilinmiyor"] += 1
                continue
            sayac["urun_yer_tutucu"] += 1

        if not yaz:
            sayac["cihaz_acilacak"] += 1
            mevcut.add(satir.imei)
            continue

        cihaz = Device(
            product_id=urun_id,
            identity_kind="IMEI",
            imei=satir.imei,
            status="STOKTA" if denge else "AKTIF",
            current_customer_id=sahip,
            source_system=KAYNAK,
            source_ref=f"imei:{satir.imei}",
        )
        db.add(cihaz)
        await db.flush()
        await stok_svc.konum_ata(
            db,
            device_id=cihaz.id,
            location_type="MERKEZ_DEPO" if denge else "MUSTERI",
            account_id=sahip,
            ownership="DENGE" if denge else "MUSTERI_SATILDI",
            clock=clock,
            an=an,
            notes="dengemobil-fora listesi",
        )
        mevcut.add(satir.imei)
        sayac["cihaz_acildi"] += 1

    if yaz:
        await db.flush()
    return sayac, acilanlar


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="dengemobil-fora cihaz listesi")
    ayristirici.add_argument("dosya", type=Path)
    ayristirici.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    args = ayristirici.parse_args(argv)

    if not args.dosya.is_file():
        print(f"Dosya yok: {args.dosya}", file=sys.stderr)
        return 1

    sonuc = oku(args.dosya)
    denge = sum(1 for s in sonuc.satirlar if denge_mi(s.firma))
    print("=" * 70)
    musteride = len(sonuc.satirlar) - denge
    print(f"FORA — {len(sonuc.satirlar)} satır ({denge} Denge stoğu, {musteride} müşteride)")
    print("=" * 70)

    async with get_session_factory()() as db:
        sayac, acilanlar = await uygula(db, sonuc, yaz=args.uygula)
        if args.uygula:
            await db.commit()

    for anahtar, adet in sorted(sayac.items()):
        print(f"  {anahtar:24s} {adet:6d}")
    if sonuc.karantina:
        print("\nALINMAYAN:")
        for anahtar, adet in sonuc.karantina.most_common():
            print(f"  {anahtar:24s} {adet:6d}")
    if acilanlar:
        print(f"\nYENİ HESAP ({len(acilanlar)}):")
        for firma, _ in acilanlar[:12]:
            print(f"  {firma[:60]}")
        if len(acilanlar) > 12:
            print(f"  … {len(acilanlar) - 12} tane daha")

    print("\nUYGULANDI." if args.uygula else "\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
