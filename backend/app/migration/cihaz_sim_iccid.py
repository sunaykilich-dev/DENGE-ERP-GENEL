"""ICCID'den TARİHSİZ cihaz–SIM eşleştirmesi.

    uv run --with openpyxl python -m app.migration.cihaz_sim_iccid <dosya.xlsx> [--uygula]

**Neden ayrı bir betik:** `cihaz_sim.py` yalnız *SIM numarası* sütununu
okuyordu. Kaynak dosyada numarası olan 6.421 cihaz var ama **ICCID'si olan
7.948** — yani 1.527 cihazın hattı biliniyor olmasına rağmen hiç denenmemişti.
Ölçüm (25 Eyl 2026):

    kaynaktaki tekil IMEI ............ 13.517
    SIM numarası dolu ................  6.421
    ICCID dolu .......................  7.948
    ICCID'si olup ERP'de eşleşmesi yok  2.803
      ICCID tekil (bağlanabilir) .....  2.446
      ICCID birden çok cihazda .......    357   (88 ICCID; biri 93 cihazda)

**Tarih YAZILMAZ.** Dosyada aktivasyon anı yok ve uydurulmuş bir tarih
(dosyanın dışa aktarım anı gibi) garanti başlangıcını ve hat maliyeti
dönemlerini sessizce yanlışlar — bu bir kez yapıldı ve kullanıcı kararıyla
geri alındı. `sim_device_history.valid_from` NULL bırakılır: satır "bu hat bu
cihazda" der, "ne zamandan beri" demez. Şema bunu kaldırır (bkz. migration
`5d1a029e1a46`): EXCLUDE kısıtları yalnız tarihli satırlara uygulanır, açık
dönem tekilliği kısmi tekil indekslerle korunur.

**Aynı ICCID birden çok cihazda görünüyorsa SATIR ALINMAZ.** Platformun ICCID
alanı bu kayıtlarda güvenilmez (bir değer 93 cihaza yazılmış); hangisinin
doğru olduğu buradan bilinemez.

**Mevcut eşleşmeye DOKUNULMAZ.** Cihazın açık bir hat dönemi varsa satır
atlanır: tarihli gerçek bir kayıt, tarihsiz bir tahminle değiştirilmez.
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
from app.models import Device, SimCard, SimDeviceHistory
from app.services.normalize import normalize_msisdn

KAYNAK = "cihaz-sim-iccid"

# Dosya düzeni: modeli | IMEI | SIM no | kullanım | ICCID | ad | sinyal | üst hesap
SUTUN_IMEI = 1
SUTUN_SIM = 2
SUTUN_ICCID = 4


def _numara(ham: str) -> str | None:
    """Numarayı E.164'e çevirir; çözülemezse None."""
    if not ham:
        return None
    try:
        return normalize_msisdn(ham)
    except ValueError:
        return None


@dataclass
class Satir:
    imei: str
    iccid: str
    msisdn: str = ""


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: Counter = field(default_factory=Counter)
    cok_cihazli: set[str] = field(default_factory=set)


def oku(yol: Path) -> Sonuc:
    from openpyxl import load_workbook

    wb = load_workbook(yol, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    sonuc = Sonuc()
    iccid_cihaz: dict[str, set[str]] = defaultdict(set)
    ham_satirlar: list[Satir] = []

    for ham in ws.iter_rows(min_row=2, values_only=True):
        if not ham or len(ham) <= SUTUN_ICCID or not ham[SUTUN_IMEI]:
            continue
        imei = str(ham[SUTUN_IMEI]).strip()
        iccid = str(ham[SUTUN_ICCID] or "").strip()
        if not iccid:
            sonuc.karantina["iccid_bos"] += 1
            continue
        if not iccid.isdigit() or not (18 <= len(iccid) <= 20):
            sonuc.karantina["iccid_bicimsiz"] += 1
            continue
        iccid_cihaz[iccid].add(imei)
        ham_satirlar.append(Satir(imei=imei, iccid=iccid, msisdn=str(ham[SUTUN_SIM] or "").strip()))
    wb.close()

    sonuc.cok_cihazli = {i for i, c in iccid_cihaz.items() if len(c) > 1}

    # AYNI NUMARA BİRDEN ÇOK ICCID'DE görünüyorsa numara güvenilmez: bir
    # telefon numarası aynı anda iki SIM'de olamaz. Dosyada 22 numara böyle.
    # ICCID tekil olduğu için EŞLEŞME KORUNUR, yalnız numara yazılmaz —
    # aksi halde `uq_sim_msisdn` ihlali göçü tamamen durduruyordu.
    numara_iccid: dict[str, set[str]] = defaultdict(set)
    for s in ham_satirlar:
        if (m := _numara(s.msisdn)) is not None:
            numara_iccid[m].add(s.iccid)
    supheli_numara = {m for m, ic in numara_iccid.items() if len(ic) > 1}

    for s in ham_satirlar:
        if s.iccid in sonuc.cok_cihazli:
            sonuc.karantina["iccid_birden_cok_cihazda"] += 1
            continue
        if (m := _numara(s.msisdn)) is not None and m in supheli_numara:
            sonuc.karantina["numara_birden_cok_iccidde"] += 1
            s.msisdn = ""  # eşleşme kalır, numara yazılmaz
        sonuc.satirlar.append(s)
    return sonuc


async def uygula(db: AsyncSession, sonuc: Sonuc, *, yaz: bool) -> dict[str, int]:
    sayac: Counter = Counter()

    cihazlar = {
        c.imei: c
        for c in (await db.scalars(select(Device).where(Device.imei.is_not(None)))).all()
        if c.imei
    }
    tum_hatlar = (await db.scalars(select(SimCard))).all()
    hatlar = {h.iccid: h for h in tum_hatlar}
    # NUMARADAN da aranır. Göç, ICCID'si bilinmeyen hatları `MSISDN:<numara>`
    # yer tutucusuyla açmıştı (7.148 hat). Yalnız ICCID'ye bakılsaydı bunların
    # 647'si İKİNCİ KEZ açılırdı — aynı fiziksel SIM iki kayıt olurdu.
    # Bulunanın ICCID'si gerçek değerle DOLDURULUR: eksik veri kapanır.
    numarali = {h.msisdn: h for h in tum_hatlar if h.msisdn}
    bagli_cihazlar = {
        h.device_id
        for h in (
            await db.scalars(select(SimDeviceHistory).where(SimDeviceHistory.valid_to.is_(None)))
        ).all()
    }
    bagli_hatlar = {
        h.sim_id
        for h in (
            await db.scalars(select(SimDeviceHistory).where(SimDeviceHistory.valid_to.is_(None)))
        ).all()
    }

    for satir in sonuc.satirlar:
        cihaz = cihazlar.get(satir.imei)
        if cihaz is None:
            sayac["cihaz_erpde_yok"] += 1
            continue
        if cihaz.id in bagli_cihazlar:
            # Tarihli gerçek kayıt tarihsiz tahminle değiştirilmez.
            sayac["cihazin_zaten_hatti_var"] += 1
            continue

        hat = hatlar.get(satir.iccid)
        if hat is None and (m := _numara(satir.msisdn)) and m in numarali:
            # Hat ERP'de var, ICCID'si yer tutucu. Gerçek ICCID yazılır.
            hat = numarali[m]
            sayac["iccid_dolduruldu"] += 1
            if yaz:
                kaynaklar = dict(hat.field_sources or {})
                kaynaklar["iccid"] = KAYNAK
                hat.iccid = satir.iccid
                hat.field_sources = kaynaklar
                hatlar[satir.iccid] = hat
        elif hat is None:
            sayac["yeni_hat"] += 1
            if yaz:
                hat = SimCard(
                    iccid=satir.iccid,
                    msisdn=_numara(satir.msisdn),
                    # Bu satır cihazın İÇİNDEKİ hattı anlatıyor: depoda değil.
                    # Durum yazılmadığı ilk koşuda 2.413 hat veritabanı
                    # varsayılanıyla "STOKTA" kaldı ve "kaç boş hattımız var"
                    # raporunu o kadar şişirdi.
                    status="AKTIF",
                    source_system=KAYNAK,
                    source_ref=satir.iccid,
                    # Operatör NOT NULL; doğrulanmamış olduğu işaretlenir.
                    field_sources={"operator": "VARSAYILAN"},
                )
                db.add(hat)
                await db.flush()
                hatlar[satir.iccid] = hat
                if hat.msisdn:
                    # Koşu İÇİNDE açılan numara da takip edilir; yoksa aynı
                    # numarayı taşıyan ikinci satır mükerrer kayıt açardı.
                    numarali[hat.msisdn] = hat
        else:
            sayac["mevcut_hat"] += 1

        if hat is not None and hat.id in bagli_hatlar:
            sayac["hat_baska_cihazda"] += 1
            continue

        if yaz and hat is not None:
            # valid_from YOK: eşleşme biliniyor, başlangıcı bilinmiyor.
            db.add(SimDeviceHistory(sim_id=hat.id, device_id=cihaz.id, valid_from=None))
            bagli_cihazlar.add(cihaz.id)
            bagli_hatlar.add(hat.id)
        sayac["eslesme"] += 1

    return dict(sayac)


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ICCID'den tarihsiz cihaz–SIM eşleştirmesi")
    ap.add_argument("dosya", type=Path)
    ap.add_argument("--uygula", action="store_true", help="Yazar; verilmezse yalnız önizler.")
    args = ap.parse_args(argv)

    sonuc = oku(args.dosya)
    print("=" * 66)
    print("ICCID EŞLEŞTİRMESİ" + ("" if args.uygula else " — ÖNİZLEME"))
    print("=" * 66)
    print(f"  okunan satır            : {len(sonuc.satirlar)}")
    print(f"  ICCID'si birden çok cihazda: {len(sonuc.cok_cihazli)} ICCID")
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
