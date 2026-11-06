"""FORA dışa aktarımından TARİHSİZ cihaz–SIM eşleştirmesi.

    uv run --with openpyxl python -m app.migration.fora_cihaz_hat <dosya.xlsx> [--uygula]

**Neden ayrı bir betik:** `cihaz_sim_iccid.py` platformun ICCID sütununu
okuyordu. FORA dosyasında ICCID yok; eşleşme **IMEI ↔ GSM numarası** üzerinden
kuruluyor ve dosya, ERP'nin hiç görmediği numaralar getiriyor. Ölçüm
(28 Eyl 2026, 3.451 satır):

    kullanılabilir satır ............ 3.421
    IMEI'si ERP'de bulunan .......... 3.415
    numarası ERP'de zaten var ......... 702
    numarası ERP'de HİÇ YOK ......... 2.697

**DeviceNo 17 HANE (IMEISV).** Son iki hane yazılım sürümü; IMEI ilk 15
hanedir. Ham değerle aranırsa hiçbir cihaz bulunamaz — dosyadaki 3.451
satırın tamamı bu biçimde.

**Numarası ERP'de olmayan hat AÇILIR.** Sistemdeki 6.501 hat zaten bu yolla
açılmış: ICCID bilinmediğinde `MSISDN:<numara>` yer tutucusu yazılır ve
`field_sources.iccid = "EKSIK"` ile işaretlenir. Aksi halde cihazın hattı
"biliniyor ama kaydedilemiyor" durumunda kalırdı.

**Tarih YAZILMAZ.** Dosyada aktivasyon anı yok; uydurulmuş bir tarih garanti
başlangıcını ve hat maliyeti dönemlerini sessizce yanlışlar (bu bir kez
yapıldı ve kullanıcı kararıyla geri alındı). `valid_from` NULL bırakılır:
satır "bu hat bu cihazda" der, "ne zamandan beri" demez.

**Mevcut eşleşmeye DOKUNULMAZ.** Cihazın açık bir hat dönemi varsa satır
atlanır: tarihli gerçek bir kayıt tarihsiz bir tahminle değiştirilmez.

**Aynı numara birden çok IMEI'de görünüyorsa SATIR ALINMAZ.** Bir numara aynı
anda iki cihazda olamaz; hangisinin doğru olduğu buradan bilinemez.

Plaka ve firma sütunları OKUNUR ama YAZILMAZ — cihaz–araç eşleştirmesi ayrı
bir karar (dosyadaki 3.414 plakanın 535'i ERP'de yok).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.migration.arac_kayit import imei_cikar
from app.models import Device, SimCard, SimDeviceHistory
from app.services.normalize import normalize_msisdn

KAYNAK = "fora-cihaz-hat"

# Dosya düzeni: FirmName | Plate | DeviceNo | Cihat tipi | GsmNo
SUTUN_PLAKA = 1
SUTUN_IMEI = 2
SUTUN_GSM = 4

# Santralin "numara yok" yerine yazdığı değer; gerçek abone numarası değil.
_YER_TUTUCU = "+905555555555"


def _numara(ham: object) -> str | None:
    metin = str(ham or "").strip()
    if not metin:
        return None
    try:
        return normalize_msisdn(metin)
    except ValueError:
        return None


@dataclass
class Satir:
    imei: str
    msisdn: str | None
    plaka: str = ""


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: Counter = field(default_factory=Counter)
    cok_cihazli_numara: set[str] = field(default_factory=set)


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
        if not ham or len(ham) <= SUTUN_GSM:
            continue
        # `imei_cikar` 17 haneli IMEISV'den ilk 15 haneyi alır ve Luhn'u
        # doğrular — cihaz kayıtları da bu helper'la açıldı; ayrı bir kural
        # yazmak iki dosyada iki farklı "IMEI" tanımı demek olurdu.
        imei = imei_cikar(ham[SUTUN_IMEI])
        # Sıfır IMEI'li 30 satır: firma alanı "DENGEMOBİL TEST/ADMİN", plaka
        # alanında ise IMEI ya da "MONTAJDA" yazıyor — satır düzeni bozuk,
        # tahminle düzeltilmez. Sıfır dizisi Luhn'dan GEÇER (toplam 0), bu
        # yüzden ayrıca elenir.
        if not imei or set(imei) == {"0"}:
            sonuc.karantina["imei_gecersiz"] += 1
            continue
        numara = _numara(ham[SUTUN_GSM])
        if numara == _YER_TUTUCU:
            sonuc.karantina["numara_yer_tutucu"] += 1
            numara = None
        elif ham[SUTUN_GSM] and numara is None:
            sonuc.karantina["numara_cozulemedi"] += 1
        plaka = re.sub(r"[^A-Z0-9]", "", str(ham[SUTUN_PLAKA] or "").upper())
        ham_satirlar.append(Satir(imei=imei, msisdn=numara, plaka=plaka))
    wb.close()

    numara_imei: dict[str, set[str]] = defaultdict(set)
    for s in ham_satirlar:
        if s.msisdn:
            numara_imei[s.msisdn].add(s.imei)
    sonuc.cok_cihazli_numara = {m for m, i in numara_imei.items() if len(i) > 1}

    for s in ham_satirlar:
        if s.msisdn and s.msisdn in sonuc.cok_cihazli_numara:
            sonuc.karantina["numara_birden_cok_cihazda"] += 1
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
    hatlar = {h.msisdn: h for h in (await db.scalars(select(SimCard))).all() if h.msisdn}
    acik = (
        await db.scalars(select(SimDeviceHistory).where(SimDeviceHistory.valid_to.is_(None)))
    ).all()
    bagli_cihazlar = {h.device_id for h in acik}
    bagli_hatlar = {h.sim_id for h in acik}

    for satir in sonuc.satirlar:
        cihaz = cihazlar.get(satir.imei)
        if cihaz is None:
            sayac["cihaz_erpde_yok"] += 1
            continue
        if cihaz.id in bagli_cihazlar:
            sayac["cihazin_zaten_hatti_var"] += 1
            continue
        if not satir.msisdn:
            sayac["numarasiz_satir"] += 1
            continue

        hat = hatlar.get(satir.msisdn)
        if hat is None:
            sayac["yeni_hat"] += 1
            if yaz:
                hat = SimCard(
                    # ICCID bilinmiyor; sistemdeki 6.501 hattın kullandığı
                    # yer tutucu. `field_sources` bunun gerçek değer OLMADIĞINI
                    # söyler, yoksa rapor onu ICCID sanardı.
                    iccid=f"MSISDN:{satir.msisdn}",
                    msisdn=satir.msisdn,
                    # Cihazın içinde takılı: depoda değil. Operatör tek
                    # operatör varsayımıyla yazılır, doğrulanmadığı işaretli.
                    status="AKTIF",
                    operator="TURK_TELEKOM",
                    source_system=KAYNAK,
                    source_ref=satir.msisdn,
                    field_sources={"iccid": "EKSIK", "operator": "VARSAYILAN"},
                )
                db.add(hat)
                await db.flush()
                hatlar[satir.msisdn] = hat
        else:
            sayac["mevcut_hat"] += 1
            if hat.id in bagli_hatlar:
                sayac["hat_baska_cihazda"] += 1
                continue

        if yaz and hat is not None:
            db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
            bagli_cihazlar.add(cihaz.id)
            bagli_hatlar.add(hat.id)
        sayac["eslesme"] += 1

    return dict(sayac)


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FORA dosyasından tarihsiz cihaz–SIM eşleştirmesi")
    ap.add_argument("dosya", type=Path)
    ap.add_argument("--uygula", action="store_true", help="Yazar; verilmezse yalnız önizler.")
    args = ap.parse_args(argv)

    sonuc = oku(args.dosya)
    print("=" * 66)
    print("FORA CİHAZ–HAT EŞLEŞTİRMESİ" + ("" if args.uygula else " — ÖNİZLEME"))
    print("=" * 66)
    print(f"  kullanılabilir satır       : {len(sonuc.satirlar)}")
    print(f"  numarası birden çok cihazda: {len(sonuc.cok_cihazli_numara)} numara")
    for neden, adet in sorted(sonuc.karantina.items()):
        print(f"  karantina · {neden:26}: {adet}")

    async with get_session_factory()() as db:
        sayac = await uygula(db, sonuc, yaz=args.uygula)
        print()
        for ad, adet in sorted(sayac.items()):
            print(f"  {ad:28}: {adet}")
        if args.uygula:
            await db.commit()
            print("\nUYGULANDI. Tarihsiz eşleşmeler yazıldı (valid_from = NULL).")
        else:
            print("\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
