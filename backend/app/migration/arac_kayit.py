"""Araç kayıt dosyasından mevcut araçları tamamlar.

    uv run --with openpyxl python -m app.migration.arac_kayit <dosya.xlsx>
    uv run --with openpyxl python -m app.migration.arac_kayit <dosya.xlsx> --uygula

Kaynak: takip platformundan alınan "Rapor" sayfası — plaka, sürücü, GsmNo,
DeviceNo ve araç künyesi (marka, model, tip, yıl, şase, renk, yakıt).

**Bu betik YENİ ARAÇ AÇMAZ.** Dosyada müşteri sütunu yok; 1.645 yeni plakanın
yalnız 27'sinin sahibi cihaz üzerinden türetilebiliyor, kalan 1.618'i sahipsiz
doğardı. Sahipsiz araç, sahipsiz cihazdan daha kötüdür: iş emri, hak ediş ve
abonelik hep müşteriye bağlanır. Karar insana ait (bkz. fleet_cihaz).

Yapılan iş: ERP'de ZATEN VAR OLAN araçların BOŞ alanlarını doldurmak.
Bugün `vehicles.model` 1.458 aracın **hiçbirinde** dolu değil, `vehicle_type`
da öyle; marka 495'inde var. Bu dosya bunları getiriyor.

Alınmayan alanlar ve nedenleri:

* **Sürücü adı.** Kişisel veri; ERP'de karşılığı olan bir alan yok ve bu
  dosyanın amacı araç künyesi. Amaç dışı kişisel veri taşınmaz (KVKK).
* **Renk, yakıt, motor, vites, depo.** `vehicles` şemasında karşılıkları yok;
  uydurma bir nota sıkıştırmak veriyi aranamaz hale getirir.

**Sütun başlıkları yanıltıcı (kullanıcı uyarısı, 23 Eyl 2026):** "Motor No"
başlığının altında ŞASE (VIN), "Şase No" başlığının altında RUHSAT seri no
var. Ölçümle doğrulandı: [10] sütunundaki 2.015 değerin 1.740'ı VIN biçiminde
ve ERP'de şasesi zaten dolu olan 332 aracın **317'siyle birebir aynı**;
[11] sütunundaki değerlerin 1.499'u Türk ruhsat biçiminde (2 harf + 6 rakam)
ve ERP şasesiyle yalnız 1 tanesi tutuyor. Başlığa güvenilseydi her araca
ruhsat numarası şase diye yazılacaktı.

DeviceNo 17 hanelidir ve IMEI DEĞİLDİR: ilk 15 hane IMEI (2.074/2.075'te Luhn
tutuyor), son iki hane yazılım sürümü ('17' ya da '19'). Doğrudan yazılsa her
cihaz yanlış kimlikle açılırdı.

Yazma kuralı: **dolu alanın üzerine yazılmaz.** Çakışma raporlanır.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import Vehicle
from app.models.vehicle import plaka_anahtari
from app.services.normalize import normalize_plate

KAYNAK = "arac-kayit"

# Kaynaktaki tip adları → ERP enum'u (ck_vehicles_tip).
TIP_ESLEME = {
    "OTOMOBIL": "BINEK",
    "SUV": "BINEK",  # SUV ayrı bir tip değil; ERP'de binek araç
    "KAMYONET": "KAMYONET",
    "KAMYON": "KAMYON",
    "TIR": "KAMYON",
    "MINIBUS": "MINIBUS",
    "OTOBUS": "OTOBUS",
    "IS MAKINESI": "IS_MAKINESI",
    "MOTORSIKLET": "MOTOSIKLET",
    "MOTOSIKLET": "MOTOSIKLET",
}

SUTUNLAR = {
    "plaka": 0,
    "gsm": 2,
    "device_no": 3,
    "tip": 4,
    "marka": 5,
    "model": 6,
    "yil": 8,
    # DİKKAT: başlıklar ters. "Motor No" → şase, "Şase No" → ruhsat.
    "sase": 10,
    "ruhsat": 11,
}

# VIN 17 karakterdir ve I, O, Q harflerini İÇERMEZ (1/0 ile karışmasın diye).
_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
# Türk ruhsat belge seri no: iki harf + altı rakam.
_RUHSAT = re.compile(r"^[A-Z]{2}\d{6}$")

EN_ESKI_YIL = 1990

# Plaka hücresine not yapışmış: "34KSY994 SEDAT ÖZBAY", "58AEC247-SÖKÜLEN CİHAZ",
# "34DPY729 ANKARA BÖLGE İKAME". Plakanın kendisi geçerli; arkasındaki metin
# sürücü adı ya da durum notu. Baştaki plaka kalıbı ayrıştırılır, gerisi atılır.
_BASTAKI_PLAKA = re.compile(r"^\s*(\d{2}\s*[A-Za-zÇĞİÖŞÜçğıöşü]{1,3}\s*\d{2,5})(?![0-9A-Za-z])")


def plaka_ayikla(ham: str) -> tuple[str | None, str | None]:
    """(plaka, atılan_ek) döner. Plaka çıkmazsa (None, None)."""
    try:
        return normalize_plate(ham), None
    except ValueError:
        pass
    eslesme = _BASTAKI_PLAKA.match(ham)
    if not eslesme:
        return None, None
    try:
        plaka = normalize_plate(eslesme.group(1))
    except ValueError:
        return None, None
    return plaka, ham[eslesme.end() :].strip(" -\u2013") or None


@dataclass
class Satir:
    plaka: str
    imei: str | None
    marka: str | None
    model: str | None
    yil: int | None
    tip: str | None
    sase: str | None
    ruhsat: str | None


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: list[tuple[str, str]] = field(default_factory=list)
    # Plaka hücresinden ayıklanıp ATILAN ekler; ne kaybettiğimiz görünsün.
    ayiklanan: list[tuple[str, str]] = field(default_factory=list)


def _metin(deger: object) -> str:
    return "" if deger is None else str(deger).strip()


def _luhn_tutuyor(rakamlar: str) -> bool:
    toplam = 0
    for i, ch in enumerate(reversed(rakamlar)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        toplam += d
    return toplam % 10 == 0


def imei_cikar(device_no: str) -> str | None:
    """17 haneli DeviceNo'dan IMEI. Luhn tutmuyorsa None — uydurulmaz."""
    ham = device_no.replace(" ", "")
    if not ham.isdigit() or len(ham) < 15:
        return None
    aday = ham[:15]
    return aday if _luhn_tutuyor(aday) else None


def _anlamli(deger: str, *, en_az: int = 2) -> str | None:
    """Tek karakterden ibaret ya da tek harfin tekrarı olan değerleri eler.

    Kaynakta 'XXXXXXXXXXXX', 'CVCVCVCV', '1' gibi doldurmalar var; bunlar
    boş bırakılmış alanlar, veri değil.
    """
    t = deger.strip()
    if len(t) < en_az or len(set(t.upper())) == 1:
        return None
    return t


def _bicime_uyan(deger: str, kalip: re.Pattern[str]) -> str | None:
    """Biçime uymayan değer YAZILMAZ. Kaynakta '1', 'XXXXXXXX' gibi doldurmalar
    var; bunları şase diye yazmak alanı aranamaz hale getirirdi."""
    t = deger.strip().upper().replace(" ", "")
    return t if kalip.match(t) else None


def oku(yol: Path) -> Sonuc:
    from openpyxl import load_workbook

    wb = load_workbook(yol, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    sonuc = Sonuc()
    bu_yil = datetime.now(UTC).year

    for sira, ham in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(ham):
            continue
        plaka_ham = _metin(ham[SUTUNLAR["plaka"]])
        if not plaka_ham:
            sonuc.karantina.append((f"satır {sira}", "plaka boş"))
            continue
        plaka, ek = plaka_ayikla(plaka_ham)
        if plaka is None:
            sonuc.karantina.append((plaka_ham[:36], "plaka biçimi tutmuyor"))
            continue
        if ek:
            sonuc.ayiklanan.append((plaka, ek))

        imei = imei_cikar(_metin(ham[SUTUNLAR["device_no"]]))
        if _metin(ham[SUTUNLAR["device_no"]]) and imei is None:
            sonuc.karantina.append((plaka, "DeviceNo'dan geçerli IMEI çıkmadı"))

        yil_ham = ham[SUTUNLAR["yil"]]
        yil = yil_ham if isinstance(yil_ham, int) and EN_ESKI_YIL <= yil_ham <= bu_yil + 1 else None

        tip_ham = _metin(ham[SUTUNLAR["tip"]]).upper().replace("İ", "I").replace("Ü", "U")
        sonuc.satirlar.append(
            Satir(
                plaka=plaka,
                imei=imei,
                marka=_anlamli(_metin(ham[SUTUNLAR["marka"]])),
                model=_anlamli(_metin(ham[SUTUNLAR["model"]])),
                yil=yil,
                tip=TIP_ESLEME.get(tip_ham),
                sase=_bicime_uyan(_metin(ham[SUTUNLAR["sase"]]), _VIN),
                ruhsat=_bicime_uyan(_metin(ham[SUTUNLAR["ruhsat"]]), _RUHSAT),
            )
        )
    return sonuc


ALANLAR = ("brand", "model", "model_year", "vehicle_type", "chassis_no", "registration_no")


def _degisiklikler(satir: Satir, arac: Vehicle) -> dict[str, object]:
    aday = {
        "brand": satir.marka,
        "model": satir.model,
        "model_year": satir.yil,
        "vehicle_type": satir.tip,
        "chassis_no": satir.sase,
        "registration_no": satir.ruhsat,
    }
    return {a: d for a, d in aday.items() if d and not getattr(arac, a)}


def _catismalar(satir: Satir, arac: Vehicle) -> list[str]:
    """ERP'de DOLU olan alan dosyadakinden farklıysa bildirilir; ezilmez."""
    catisma = []
    if satir.sase and arac.chassis_no and satir.sase != arac.chassis_no.strip().upper():
        catisma.append(f"şase ERP={arac.chassis_no} dosya={satir.sase}")
    return catisma


async def uygula(
    db: AsyncSession, sonuc: Sonuc, *, yaz: bool
) -> tuple[Counter, list[str], list[str]]:
    araclar = {a.plate_key: a for a in (await db.scalars(select(Vehicle))).all() if a.plate_key}
    # Şase 17 karakterse TEKİLDİR (uq_vehicles_sase). Aynı şaseyi ikinci bir
    # araca yazmak kısıta çarpar; hangi aracın doğru olduğunu betik bilemez.
    sase_sahibi = {
        a.chassis_no.strip().upper(): a.plate
        for a in araclar.values()
        if a.chassis_no and len(a.chassis_no.strip()) == 17
    }

    sayac: Counter = Counter()
    yeni_plakalar: list[str] = []
    catismalar: list[str] = []
    for satir in sonuc.satirlar:
        arac = araclar.get(plaka_anahtari(satir.plaka))
        if arac is None:
            sayac["arac_erpde_yok"] += 1
            yeni_plakalar.append(satir.plaka)
            continue
        for c in _catismalar(satir, arac):
            catismalar.append(f"{satir.plaka}: {c}")
        degisen = _degisiklikler(satir, arac)
        if "chassis_no" in degisen:
            sahip = sase_sahibi.get(satir.sase or "")
            if sahip and sahip != arac.plate:
                catismalar.append(f"{satir.plaka}: şase {satir.sase} zaten {sahip} aracında")
                del degisen["chassis_no"]
                sayac["sase_baska_aracta"] += 1
            elif satir.sase:
                sase_sahibi[satir.sase] = arac.plate
        if not degisen:
            sayac["degisiklik_yok"] += 1
            continue
        for alan, deger in degisen.items():
            sayac[f"yazilan_{alan}"] += 1
            if yaz:
                setattr(arac, alan, deger)
        sayac["guncellenen_arac"] += 1
    if yaz:
        await db.flush()
    return sayac, yeni_plakalar, catismalar


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Araç kayıt dosyasından künye tamamlama")
    ayristirici.add_argument("dosya", type=Path)
    ayristirici.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    args = ayristirici.parse_args(argv)

    if not args.dosya.is_file():
        print(f"Dosya yok: {args.dosya}", file=sys.stderr)
        return 1

    sonuc = oku(args.dosya)
    print("=" * 68)
    print(f"ARAÇ KAYIT — {len(sonuc.satirlar)} okunabilir satır")
    print("=" * 68)

    async with get_session_factory()() as db:
        sayac, yeni, catismalar = await uygula(db, sonuc, yaz=args.uygula)
        if args.uygula:
            await db.commit()

    for anahtar, adet in sorted(sayac.items()):
        print(f"  {anahtar:24s} {adet:5d}")

    if catismalar:
        print(f"\nÇAKIŞMA ({len(catismalar)}) — ERP'deki dolu şase dosyadakinden FARKLI, ezilmedi:")
        for c in catismalar[:8]:
            print(f"  {c}")
        if len(catismalar) > 8:
            print(f"  … {len(catismalar) - 8} tane daha")

    if sonuc.ayiklanan:
        print(f"\nPLAKA HÜCRESİNDEN AYIKLANAN EK ({len(sonuc.ayiklanan)}) — atıldı:")
        for plaka, ek in sonuc.ayiklanan[:6]:
            print(f"  {plaka:12s} ← «{ek[:40]}»")
        if len(sonuc.ayiklanan) > 6:
            print(f"  … {len(sonuc.ayiklanan) - 6} tane daha")

    if sonuc.karantina:
        print(f"\nKARANTİNA ({len(sonuc.karantina)}) — bu satırlar okunmadı:")
        for anahtar, neden in sonuc.karantina[:10]:
            print(f"  {anahtar:14s} {neden}")
        if len(sonuc.karantina) > 10:
            print(f"  … {len(sonuc.karantina) - 10} satır daha")

    if yeni:
        print(f"\nERP'DE OLMAYAN PLAKA: {len(yeni)} — bu betik AÇMAZ (müşterisi bilinmiyor).")
        print(f"  örnek: {', '.join(yeni[:6])}")

    print("\nUYGULANDI." if args.uygula else "\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
