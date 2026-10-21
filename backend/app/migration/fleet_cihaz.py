"""Takip platformu cihaz dışa aktarımını ERP'ye alır.

Kaynak: platformun "Cihaz seçim dışa aktar" Excel'i (13.517 satır).
Sütunlar: Cihaz modeli, IMEI, SIM kart numarası, Kullanım durumu, ICCID,
Cihaz adı, Sinyal zamanı, Üst hesap.

**`Üst hesap` cihazın kimde olduğunu söyler.** `StormAdmin` = Denge'nin kendi
stoğu; geri kalan 293 ad müşteri/bayi hesaplarıdır.

Bu betik ŞİMDİLİK YALNIZ StormAdmin satırlarını alır. Gerekçe: diğer 293 adın
236'sı ERP'de yok ve bir kısmı mevcut hesapların yazım farklısı —
`ÇAMKIRAN OTOMOTİV` (dosyada 3.458 cihaz) ile ERP'deki `ÇAMKIRAN OTOMATİV`
gibi. Otomatik açmak 3.458 cihazı mükerrer bir hesaba bağlardı; plan §6'nın
kuralı burada da geçerli: **otomatik benzerlik yalnız aday üretir, birleştirme
kararını insan verir.**

Yan kazanç: dosyada ICCID var. ERP'deki hatların HEPSİ göçten `MSISDN:+90…`
yer tutucusuyla gelmişti; numarası eşleşenlerin gerçek ICCID'si buradan
yazılır.

    uv run python -m app.migration.fleet_cihaz <dosya.xlsx>            # ÖNİZLEME
    uv run python -m app.migration.fleet_cihaz <dosya.xlsx> --uygula   # Denge stoğunu yazar

Müşteri cihazları için iki adım:

    ... --hesap-listesi hesaplar.xlsx        # karar sayfası üretir (yazmaz)
    ... --kararlar hesaplar.xlsx --uygula    # doldurulmuş sayfaya göre aktarır
"""

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import RealClock
from app.db import get_session_factory
from app.migration.esleme import kaynak_ref
from app.models import Device, Product, SimCard
from app.services import stock as stok_svc
from app.services.normalize import (
    normalize_iccid,
    normalize_msisdn,
    tr_normkey,
    validate_imei,
)

KAYNAK = "fleet-export"
DENGE_HESABI = "StormAdmin"

# Platformdaki model adı → ERP ürün kodu. Aynı cihaz iki yerde farklı adla
# anılıyor (ERP'de "GS900 / DM900", platformda "GS900"); eşleme elle yazılır
# çünkü otomatik benzerlik GS900 ile GS910'u karıştırabilir.
MODEL_URUN = {
    "GS900": "GS900",
    "GS12": "GS12",
    "H20P": "H20P",
    "FMB920": "FMB920",
    "GS910": "GS910",
    "GS10G": "GS10G",
    "H18P": "H18P",
    "L300Pro": "L300-PRO",
    "S204G": "S204G",
}

# Katalogda olmayan modeller. Marka bilinmiyor — platform yalnız model adı
# veriyor — uydurulmaz, boş bırakılır (bkz. ürün kartı "markasız" rozeti).
YENI_URUNLER = {
    "GS910": {"name": "GS910 Araç Takip", "model": "GS910", "family": "GS900"},
    "GS10G": {"name": "GS10G Araç Takip", "model": "GS10G", "family": "GS10G"},
    "H18P": {"name": "H18P ADAS+DMS Kamera", "model": "H18P", "family": "H20P"},
    "L300-PRO": {
        "name": "Armoli L300 Pro",
        "model": "L300-PRO",
        "family": "L300",
        "brand": "Armoli",
    },
    "S204G": {"name": "S204G Araç Takip", "model": "S204G", "family": "S204G"},
}


def _s(deger) -> str:
    return "" if deger is None else str(deger).strip()


@dataclass
class Satir:
    satir_no: int
    imei: str
    model: str
    ust_hesap: str
    cihaz_adi: str
    kullanim: str
    iccid: str | None
    msisdn: str | None


@dataclass
class Sonuc:
    satirlar: list[Satir] = field(default_factory=list)
    karantina: list[tuple[int, str, str]] = field(default_factory=list)
    modeller: Counter = field(default_factory=Counter)
    # ICCID eşleşmesi TÜM dosyadan toplanır, yalnız Denge stoğundan değil:
    # bir hattın ICCID'si, takılı olduğu cihazın kimde olduğundan bağımsız
    # bir olgudur. Müşteri cihazlarını almasak da hattın numarası ERP'de
    # kayıtlıysa gerçek ICCID'si buradan tamamlanabilir.
    hat_iccid: dict[str, str] = field(default_factory=dict)
    # Platformun ICCID sütunu GÜVENİLİR DEĞİL: 80 ICCID birden çok numaraya
    # bağlı görünüyor, biri 85 numaraya. Muhtemelen bir parti cihaza aynı
    # değer kopyalanmış. Böyle bir ICCID hiçbir hatta yazılmaz — yanlış
    # ICCID, eksik ICCID'den kötüdür; ikincisi "eksik" diye görünür, ilki
    # doğru sanılır.
    supheli_iccid: set[str] = field(default_factory=set)
    # StormAdmin DIŞINDAKİ satırlar: hesap kararı verilene kadar yazılmaz.
    musteri_satirlari: list[Satir] = field(default_factory=list)


def oku(yol: Path) -> tuple[Sonuc, Counter]:
    """Dosyayı okur; yalnız Denge stoğu satırlarını ayıklar."""
    ws = load_workbook(yol, read_only=True, data_only=True)[
        load_workbook(yol, read_only=True).sheetnames[0]
    ]
    ham = list(ws.iter_rows(values_only=True))
    basliklar = [_s(h) for h in ham[0]]
    gerekli = {"Cihaz modeli", "IMEI", "Üst hesap"}
    if not gerekli <= set(basliklar):
        raise SystemExit(f"Beklenen sütunlar yok: {sorted(gerekli - set(basliklar))}")

    sonuc = Sonuc()
    hesap_dagilimi: Counter = Counter()
    iccid_ms: defaultdict[str, set[str]] = defaultdict(set)

    for sira, satir in enumerate(ham[1:], start=2):
        kayit = dict(zip(basliklar, satir, strict=False))
        ust = _s(kayit.get("Üst hesap"))
        hesap_dagilimi[ust or "(boş)"] += 1

        # Hat eşleşmesi her satırdan toplanır (bkz. Sonuc.hat_iccid).
        if (ham_ms := _s(kayit.get("SIM kart numarası"))) and (ham_ic := _s(kayit.get("ICCID"))):
            try:
                iccid_ms[normalize_iccid(ham_ic)].add(normalize_msisdn(ham_ms))
            except ValueError:
                pass  # bozuk numara/ICCID sessizce atlanır; cihaz akışı ayrı doğruluyor

        try:
            imei = validate_imei(_s(kayit.get("IMEI")))
        except ValueError as exc:
            sonuc.karantina.append((sira, "IMEI", str(exc)))
            continue

        model = _s(kayit.get("Cihaz modeli"))
        if model not in MODEL_URUN:
            sonuc.karantina.append((sira, "Model", f"Bilinmeyen model: {model}"))
            continue

        iccid = None
        if ham_iccid := _s(kayit.get("ICCID")):
            try:
                iccid = normalize_iccid(ham_iccid)
            except ValueError as exc:
                sonuc.karantina.append((sira, "ICCID", f"{exc} (cihaz yine alındı)"))

        msisdn = None
        if ham_ms := _s(kayit.get("SIM kart numarası")):
            try:
                msisdn = normalize_msisdn(ham_ms)
            except ValueError as exc:
                sonuc.karantina.append((sira, "MSISDN", f"{exc} (cihaz yine alındı)"))

        kayit_satiri = Satir(
            satir_no=sira,
            imei=imei,
            model=model,
            ust_hesap=ust,
            cihaz_adi=_s(kayit.get("Cihaz adı")),
            kullanim=_s(kayit.get("Kullanım durumu")),
            iccid=iccid,
            msisdn=msisdn,
        )
        if ust == DENGE_HESABI:
            sonuc.modeller[model] += 1
            sonuc.satirlar.append(kayit_satiri)
        else:
            sonuc.musteri_satirlari.append(kayit_satiri)

    # Yalnız TEK numaraya bağlı ICCID'ler kullanılır.
    for iccid, numaralar in iccid_ms.items():
        if len(numaralar) == 1:
            sonuc.hat_iccid[next(iter(numaralar))] = iccid
        else:
            sonuc.supheli_iccid.add(iccid)

    return sonuc, hesap_dagilimi


async def urunleri_hazirla(db: AsyncSession, kodlar: set[str], *, yaz: bool) -> dict[str, int]:
    """Eksik ürünleri açar; kod → id döndürür."""
    mevcut = {
        u.code: u.id
        for u in (await db.scalars(select(Product).where(Product.is_deleted.is_(False)))).all()
    }
    for kod in sorted(kodlar):
        if kod in mevcut:
            continue
        veri = YENI_URUNLER.get(kod)
        if veri is None:
            raise SystemExit(f"'{kod}' katalogda yok ve tanımı da yok.")
        if not yaz:
            mevcut[kod] = -1
            continue
        urun = Product(
            code=kod,
            type="CIHAZ_SERILI",
            identity_kind="IMEI",
            source_system=KAYNAK,
            source_ref=f"urun:{kod}",
            **veri,
        )
        db.add(urun)
        await db.flush()
        mevcut[kod] = urun.id
    return mevcut


async def uygula(db: AsyncSession, sonuc: Sonuc) -> dict[str, int]:
    """Cihazları stoğa alır, eşleşen hatların ICCID'sini tamamlar."""
    clock = RealClock()
    an = datetime.now(UTC)
    sayac = Counter()

    urun_id = await urunleri_hazirla(db, {MODEL_URUN[s.model] for s in sonuc.satirlar}, yaz=True)

    mevcut_cihaz = {
        c.imei: c for c in (await db.scalars(select(Device).where(Device.imei.is_not(None)))).all()
    }

    for satir in sonuc.satirlar:
        cihaz = mevcut_cihaz.get(satir.imei)
        if cihaz is not None:
            # Zaten kayıtlı: durumuna DOKUNULMAZ. Sahada aktif bir cihazı
            # "stokta" diye işaretlemek, ERP'nin bildiği gerçeği platformun
            # eski bir kaydıyla ezmek olurdu.
            sayac["zaten_vardi"] += 1
            continue

        cihaz = Device(
            product_id=urun_id[MODEL_URUN[satir.model]],
            identity_kind="IMEI",
            imei=satir.imei,
            status="STOKTA",
            notes=f"Platform cihaz adı: {satir.cihaz_adi}" if satir.cihaz_adi else None,
            source_system=KAYNAK,
            source_ref=f"imei:{satir.imei}",
        )
        db.add(cihaz)
        await db.flush()
        # Denge'nin kendi malı, merkez depoda. Konum geçmişi olmadan cihaz
        # "nerede" sorusuna cevap veremez ve stok raporunda konumsuz görünür.
        await stok_svc.konum_ata(
            db,
            device_id=cihaz.id,
            location_type="MERKEZ_DEPO",
            ownership="DENGE",
            clock=clock,
            an=an,
            notes="Takip platformu dışa aktarımı",
        )
        sayac["cihaz"] += 1

    sayac.update(await iccid_tamamla(db, sonuc))
    return dict(sayac)


async def iccid_tamamla(db: AsyncSession, sonuc: Sonuc) -> Counter:
    """Numarası eşleşen ERP hatlarının yer tutucu ICCID'sini gerçeğiyle değiştirir.

    Göç, ICCID bilinmeyen hatta `MSISDN:+90…` yazmıştı ve `field_sources`'a
    `EKSIK` işaretlemişti. Burada yalnız O işaretli olanlar güncellenir; elle
    düzeltilmiş bir ICCID'nin üzerine yazılmaz.
    """
    sayac: Counter = Counter()
    if not sonuc.hat_iccid:
        return sayac

    hatlar = (
        await db.scalars(select(SimCard).where(SimCard.msisdn.in_(list(sonuc.hat_iccid))))
    ).all()
    kullanilan = {h.iccid for h in hatlar}

    for hat in hatlar:
        yeni_iccid = sonuc.hat_iccid[hat.msisdn]
        if (hat.field_sources or {}).get("iccid") != "EKSIK":
            # Ya elle girilmiş ya da önceki koşuda bu dosyadan tamamlanmış.
            sayac["iccid_zaten_doluydu"] += 1
            continue
        if yeni_iccid in kullanilan and yeni_iccid != hat.iccid:
            # ICCID tekil: aynı değeri iki hatta yazmak kısıta çarpar. Platform
            # dosyasında 146 ICCID birden çok cihazda görünüyor (SIM sökülüp
            # başka cihaza takılmış); ilk gelen yazılır, ikincisi raporlanır.
            sayac["iccid_cakisti"] += 1
            continue
        hat.iccid = yeni_iccid
        hat.field_sources = {**(hat.field_sources or {}), "iccid": KAYNAK}
        kullanilan.add(yeni_iccid)
        sayac["iccid_tamamlandi"] += 1
    await db.flush()
    return sayac


def rapor(sonuc: Sonuc, hesaplar: Counter) -> str:
    satirlar = [
        "=" * 64,
        f"TAKİP PLATFORMU DIŞA AKTARIMI — {sum(hesaplar.values())} satır",
        "=" * 64,
        "",
        f"Denge stoğu ({DENGE_HESABI})      : {len(sonuc.satirlar)}",
        f"Başka hesaplarda (alınmıyor)  : "
        f"{sum(v for k, v in hesaplar.items() if k != DENGE_HESABI)}"
        f"  ({len([k for k in hesaplar if k != DENGE_HESABI])} hesap)",
        "",
        "Model dağılımı (Denge stoğu):",
    ]
    for model, adet in sonuc.modeller.most_common():
        satirlar.append(f"  {model:10} {adet:6}  → {MODEL_URUN[model]}")

    iccidli = sum(1 for s in sonuc.satirlar if s.iccid)
    numarali = sum(1 for s in sonuc.satirlar if s.msisdn)
    satirlar += [
        "",
        f"ICCID'si olan   : {iccidli}",
        f"Numarası olan   : {numarali}",
        "",
        f"Tüm dosyadan güvenilir numara–ICCID eşleşmesi : {len(sonuc.hat_iccid)}",
        "  (ERP'de numarası kayıtlı hatların yer tutucu ICCID'si tamamlanır)",
        f"Kullanılmayan şüpheli ICCID : {len(sonuc.supheli_iccid)}"
        "  (birden çok numaraya bağlı — platform verisi hatalı)",
    ]
    if sonuc.karantina:
        satirlar += ["", f"KARANTİNA ({len(sonuc.karantina)} satır):"]
        for no, alan, mesaj in sonuc.karantina[:20]:
            satirlar.append(f"  satır {no:6} [{alan}] {mesaj}")
        if len(sonuc.karantina) > 20:
            satirlar.append(f"  … {len(sonuc.karantina) - 20} satır daha")
    return "\n".join(satirlar)


async def _hesap_listesi_uret(sonuc: Sonuc, cikti: Path) -> int:
    from app.models import Account

    async with get_session_factory()() as db:
        adaylar = await hesap_adaylari(db, sonuc)
        hesaplar = [
            (h.id, h.title, ", ".join(h.roller))
            for h in (
                await db.scalars(
                    select(Account).where(Account.is_deleted.is_(False)).order_by(Account.title)
                )
            ).all()
        ]

    hesap_listesi_yaz(cikti, adaylar, hesaplar)
    tam = sum(1 for a in adaylar if a["durum"] == "TAM EŞLEŞME")
    aday = sum(1 for a in adaylar if a["durum"] == "ADAY VAR")
    yok = sum(1 for a in adaylar if a["durum"] == "EŞLEŞME YOK")
    print(f"{cikti} yazıldı.")
    print(f"  platform hesabı      : {len(adaylar)}  ({sum(a['cihaz'] for a in adaylar)} cihaz)")
    print(f"  tam eşleşme (dolduruldu): {tam}")
    print(f"  adayı olan (bakılacak)  : {aday}")
    print(f"  eşleşmesi olmayan       : {yok}")
    print("\nKARAR sütununu doldurup şu komutla aktarın:")
    print(f"  uv run python -m app.migration.fleet_cihaz <dosya.xlsx> --kararlar {cikti} --uygula")
    return 0


async def _kararlara_gore_aktar(sonuc: Sonuc, karar_dosyasi: Path, *, yaz: bool) -> int:
    if not karar_dosyasi.is_file():
        print(f"Karar dosyası yok: {karar_dosyasi}", file=sys.stderr)
        return 1
    kararlar, hatalar, roller = kararlari_oku(karar_dosyasi)

    adet = Counter(s.ust_hesap for s in sonuc.musteri_satirlari)
    yeni = [a for a, k in kararlar.items() if k == KARAR_YENI]
    atla = [a for a, k in kararlar.items() if k == KARAR_ATLA]
    mevcut = [a for a, k in kararlar.items() if k not in (KARAR_YENI, KARAR_ATLA)]
    alinacak = sum(adet[a] for a in kararlar if kararlar[a] != KARAR_ATLA)

    print("=" * 64)
    print("HESAP KARARLARI")
    print("=" * 64)
    print(f"  mevcut hesaba bağlanan : {len(mevcut)} hesap")
    print(f"  yeni açılacak          : {len(yeni)} hesap")
    print(f"  atlanan                : {len(atla)} hesap")
    print(f"  aktarılacak cihaz      : {alinacak}")
    if hatalar:
        print(f"\nEKSİK/HATALI KARAR ({len(hatalar)}) — bu hesapların cihazları ALINMAZ:")
        for h in hatalar[:20]:
            print(f"  {h}")
        if len(hatalar) > 20:
            print(f"  … {len(hatalar) - 20} satır daha")

    if not yaz:
        print("\nÖNİZLEME — hiçbir şey yazılmadı. Yazmak için --uygula ekleyin.")
        return 0

    async with get_session_factory()() as db:
        sayac = await musteri_cihazlarini_yaz(db, sonuc, kararlar, roller)
        await db.commit()
    print("\n" + "=" * 64)
    print("UYGULANDI")
    for ad, deger in sorted(sayac.items()):
        print(f"  {ad:28} {deger}")
    return 0


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Takip platformu cihaz aktarımı")
    ayristirici.add_argument("dosya", type=Path)
    ayristirici.add_argument(
        "--uygula", action="store_true", help="Değişiklikleri YAZ (yoksa yalnız önizleme)"
    )
    ayristirici.add_argument(
        "--hesap-listesi",
        type=Path,
        metavar="CIKTI.xlsx",
        help="Müşteri hesapları için karar sayfası üretir (hiçbir şey yazmaz)",
    )
    ayristirici.add_argument(
        "--kararlar",
        type=Path,
        metavar="KARAR.xlsx",
        help="Doldurulmuş karar sayfası; müşteri cihazları buna göre aktarılır",
    )
    args = ayristirici.parse_args(argv)

    if not args.dosya.is_file():
        print(f"Dosya yok: {args.dosya}", file=sys.stderr)
        return 1

    sonuc, hesaplar = oku(args.dosya)

    if args.hesap_listesi:
        return await _hesap_listesi_uret(sonuc, args.hesap_listesi)
    if args.kararlar:
        return await _kararlara_gore_aktar(sonuc, args.kararlar, yaz=args.uygula)

    print(rapor(sonuc, hesaplar))

    if not args.uygula:
        print("\nÖNİZLEME — hiçbir şey yazılmadı. Yazmak için --uygula ekleyin.")
        return 0

    async with get_session_factory()() as db:
        sayac = await uygula(db, sonuc)
        await db.commit()

    print("\n" + "=" * 64)
    print("UYGULANDI")
    for ad, adet in sorted(sayac.items()):
        print(f"  {ad:32} {adet}")
    return 0


# --- Hesap eşleştirme -------------------------------------------------------

# Adında bunlardan biri geçen hesap bayi sayılır — "İZMİR KARDEŞLER (BAYİİ)",
# "EVA ARAÇ TAKİP (G.ANTEP BAYİ)" gibi. Öneri olarak sunulur, karar insanın.
BAYI_IPUCLARI = ("BAYI", "BAYII", "BAYİ", "BAYİİ")

KARAR_YENI = "YENİ"
KARAR_ATLA = "ATLA"


def _bayi_mi(ad: str) -> bool:
    buyuk = ad.upper()
    return any(ipucu in buyuk for ipucu in BAYI_IPUCLARI)


def _adaylari_bul(anahtar_metin: str, anahtar: dict, anahtarlar: list[str]) -> list[dict]:
    """Üç kaynaktan aday toplar; en güçlüsü başa gelecek şekilde sıralar."""
    import difflib

    bulunan: dict[str, tuple[float, str]] = {}

    def _ekle(a: str, puan: float, tur: str) -> None:
        if a not in bulunan:
            bulunan[a] = (puan, tur)

    # 1) Biri diğerinin BAŞLANGICI — kısa ad ↔ resmî unvan.
    if len(anahtar_metin) >= 5:
        for a in anahtarlar:
            if a.startswith(anahtar_metin) or anahtar_metin.startswith(a):
                _ekle(a, 0.99, "başlangıç")
    # 2) Biri diğerinin içinde geçiyor.
    if len(anahtar_metin) >= 6:
        for a in anahtarlar:
            if anahtar_metin in a or a in anahtar_metin:
                _ekle(a, 0.9, "içerir")
    # 3) Harf benzerliği.
    for a in difflib.get_close_matches(anahtar_metin, anahtarlar, n=3, cutoff=0.6):
        _ekle(a, round(difflib.SequenceMatcher(None, anahtar_metin, a).ratio(), 3), "benzerlik")

    siralı = sorted(bulunan.items(), key=lambda x: -x[1][0])[:3]
    return [
        {"id": anahtar[a].id, "unvan": anahtar[a].title, "benzerlik": puan, "tur": tur}
        for a, (puan, tur) in siralı
    ]


async def hesap_adaylari(db: AsyncSession, sonuc: Sonuc) -> list[dict]:
    """Platform hesap adlarını ERP hesaplarıyla eşleştirme adayları üretir.

    Otomatik birleştirme YAPILMAZ. Kaynak veride `ÇAMKIRAN OTOMOTİV` ile
    `ÇAMKIRAN OTOMATİV` aynı firma (3.458 cihaz), ama `CEYLON FİLO` ile
    `LYON FİLO` FARKLI firmalar. Benzerlik ikisini de yüksek skorla döndürür;
    bu yüzden liste yalnız aday üretir, kararı insan verir (plan §6).

    Üç aday kaynağı birlikte kullanılır. Tek başına harf benzerliği yetmiyor:
    platform kısa ad tutuyor (`KURT YAPİ`), ERP resmî unvanı
    (`KURT YAPI HAF. İNŞ. VE GIDA SAN. TİC. LTD. ŞTİ.`) — ikisinin harf
    benzerliği düşük ama biri diğerinin BAŞLANGICI.
    """

    from app.models import Account

    hesaplar = (await db.scalars(select(Account).where(Account.is_deleted.is_(False)))).all()
    anahtar = {h.title_key: h for h in hesaplar}
    anahtarlar = list(anahtar)

    adet = Counter(s.ust_hesap for s in sonuc.musteri_satirlari)
    satirlar: list[dict] = []
    for ad, cihaz in adet.most_common():
        k = tr_normkey(ad)
        tam = anahtar.get(k)
        adaylar: list[dict] = []

        if tam is None:
            adaylar = _adaylari_bul(k, anahtar, anahtarlar)

        satirlar.append(
            {
                "platform_hesabi": ad,
                "cihaz": cihaz,
                "durum": "TAM EŞLEŞME" if tam else ("ADAY VAR" if adaylar else "EŞLEŞME YOK"),
                "erp_id": tam.id if tam else None,
                "erp_unvan": tam.title if tam else None,
                "adaylar": adaylar,
                "rol_onerisi": "BAYİ" if _bayi_mi(ad) else "MÜŞTERİ",
            }
        )
    return satirlar


def _hucre(deger):
    """Excel formül kaçışı — bkz. services/export._hucre.

    Bu sayfadaki adlar takip platformundan geliyor ve dosyayı insan açıyor.
    """
    from app.services.export import _hucre as kacir

    return kacir(deger)


def hesap_listesi_yaz(yol: Path, adaylar: list[dict], hesaplar: list[tuple[int, str, str]]) -> None:
    """Doldurulacak karar sayfasını üretir.

    Tam eşleşenlerin KARAR sütunu önceden doldurulur; kullanıcı yalnız
    kalanlara bakar. Böylece 293 satırın 57'si zaten kapanmış olur.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Eşleştirme"
    basliklar = [
        "Platform hesabı",
        "Cihaz",
        "Durum",
        "KARAR (ERP id / YENİ / ATLA)",
        "Rol (yeni hesapsa)",
        "Aday 1 — ERP id",
        "Aday 1 — unvan",
        "Benzerlik",
        "Aday 2 — ERP id",
        "Aday 2 — unvan",
        "Aday 3 — ERP id",
        "Aday 3 — unvan",
    ]
    ws.append(basliklar)
    koyu = PatternFill("solid", fgColor="11417F")
    for h in ws[1]:
        h.fill, h.font = koyu, Font(color="FFFFFF", bold=True)
        h.alignment = Alignment(vertical="center", wrap_text=True)

    sari = PatternFill("solid", fgColor="FFF3CD")
    for a in adaylar:
        satir = [
            a["platform_hesabi"],
            a["cihaz"],
            a["durum"],
            a["erp_id"] if a["erp_id"] else "",
            a["rol_onerisi"],
        ]
        for i in range(3):
            aday = a["adaylar"][i] if i < len(a["adaylar"]) else None
            satir += [aday["id"] if aday else "", aday["unvan"] if aday else ""]
            if i == 0:
                satir.append(aday["benzerlik"] if aday else "")
        # Aday 1'in benzerliği 8. sütunda; sıralamayı başlıklarla hizala.
        duzen = satir[:5] + [satir[5], satir[6], satir[7], satir[8], satir[9], satir[10], satir[11]]
        ws.append([_hucre(x) for x in duzen])
        if not a["erp_id"]:
            ws.cell(row=ws.max_row, column=4).fill = sari

    genislik = [34, 8, 14, 26, 18, 12, 30, 11, 12, 30, 12, 30]
    for i, en in enumerate(genislik, start=1):
        ws.column_dimensions[get_column_letter(i)].width = en
    ws.freeze_panes = "A2"

    ref = wb.create_sheet("ERP hesapları")
    ref.append(["ERP id", "Unvan", "Roller"])
    for h in ref[1]:
        h.fill, h.font = koyu, Font(color="FFFFFF", bold=True)
    for hid, unvan, roller in hesaplar:
        ref.append([hid, unvan, roller])
    ref.column_dimensions["A"].width = 10
    ref.column_dimensions["B"].width = 46
    ref.column_dimensions["C"].width = 30
    ref.freeze_panes = "A2"

    yonerge = wb.create_sheet("Nasıl doldurulur")
    for metin in [
        "KARAR sütununu doldurun. Üç seçenek var:",
        "",
        "  • ERP hesap id'si  → bu platform hesabı ERP'deki O hesaptır.",
        "                       Aday sütunlarındaki id'yi kopyalayabilir ya da",
        "                       'ERP hesapları' sayfasından arayabilirsiniz.",
        f"  • {KARAR_YENI}              → ERP'de yok, yeni hesap açılsın.",
        f"  • {KARAR_ATLA}              → bu hesabın cihazları şimdilik alınmasın.",
        "",
        "Sarı hücreler karar bekliyor. Tam eşleşenler önceden dolduruldu,",
        "ama yine de gözden geçirin — ad aynı olsa da farklı firma olabilir.",
        "",
        "'Rol' sütunu yalnız YENİ hesaplarda kullanılır (MÜŞTERİ ya da BAYİ).",
        "",
        "DİKKAT: benzerlik yalnız ADAY üretir. Gerçek veride",
        "  'ÇAMKIRAN OTOMOTİV' ile 'ÇAMKIRAN OTOMATİV' AYNI firma,",
        "  'CEYLON FİLO' ile 'LYON FİLO' FARKLI firmalar.",
        "İkisi de yüksek benzerlik veriyor; kararı ancak siz verebilirsiniz.",
    ]:
        yonerge.append([metin])
    yonerge.column_dimensions["A"].width = 80

    wb.save(yol)


def kararlari_oku(yol: Path) -> tuple[dict[str, str], list[str], dict[str, str]]:
    """Doldurulmuş karar sayfasını okur → (kararlar, hatalar, roller)."""
    ws = load_workbook(yol, read_only=True, data_only=True)["Eşleştirme"]
    ham = list(ws.iter_rows(values_only=True))
    basliklar = [_s(h) for h in ham[0]]
    try:
        ad_i = basliklar.index("Platform hesabı")
        karar_i = next(i for i, b in enumerate(basliklar) if b.startswith("KARAR"))
        rol_i = next(i for i, b in enumerate(basliklar) if b.startswith("Rol"))
    except (ValueError, StopIteration) as exc:
        raise SystemExit(f"Karar sayfasının sütunları tanınmadı: {exc}") from exc

    kararlar: dict[str, str] = {}
    roller: dict[str, str] = {}
    hatalar: list[str] = []
    for sira, satir in enumerate(ham[1:], start=2):
        ad = _s(satir[ad_i])
        if not ad:
            continue
        karar = _s(satir[karar_i]).upper()
        if not karar:
            hatalar.append(f"satır {sira}: '{ad}' için KARAR boş")
            continue
        if karar in (KARAR_YENI, KARAR_ATLA):
            kararlar[ad] = karar
        elif karar.replace(".0", "").isdigit():
            kararlar[ad] = karar.replace(".0", "")
        else:
            hatalar.append(f"satır {sira}: '{ad}' kararı anlaşılmadı: {karar}")
            continue
        roller[ad] = _s(satir[rol_i]).upper() or "MÜŞTERİ"
    return kararlar, hatalar, roller


async def musteri_cihazlarini_yaz(
    db: AsyncSession, sonuc: Sonuc, kararlar: dict[str, str], roller: dict[str, str]
) -> dict[str, int]:
    """Karar verilmiş hesapların cihazlarını ERP'ye alır.

    Cihazlar MÜŞTERİDE sayılır (konum MUSTERI, sahiplik MUSTERI_SATILDI) ve
    durum AKTIF olur: platformda bir hesabın altındaysa saha cihazıdır. Ama
    ARAÇ BAĞLANMAZ — dosyada plaka yok; cihaz–araç dönemi uydurulamaz, o bağ
    montaj kaydı ya da `cihaz_arac` içe aktarımıyla kurulur.
    """
    from app.models import Account

    clock = RealClock()
    an = datetime.now(UTC)
    sayac: Counter = Counter()

    urun_id = await urunleri_hazirla(
        db, {MODEL_URUN[s.model] for s in sonuc.musteri_satirlari}, yaz=True
    )
    mevcut = {
        c.imei: c for c in (await db.scalars(select(Device).where(Device.imei.is_not(None)))).all()
    }

    hesap_id: dict[str, int] = {}
    for ad, karar in kararlar.items():
        if karar == KARAR_ATLA:
            continue
        if karar == KARAR_YENI:
            # Tekrar koşuda aynı hesabı ikinci kez AÇMA (plan §6: göç idempotent).
            ref = kaynak_ref("hesap", ad)
            hesap = await db.scalar(
                select(Account).where(Account.source_system == KAYNAK, Account.source_ref == ref)
            )
            if hesap is None:
                hesap = Account(
                    title=ad,
                    title_key=tr_normkey(ad),
                    is_musteri=roller.get(ad) != "BAYİ",
                    is_bayi=roller.get(ad) == "BAYİ",
                    source_system=KAYNAK,
                    source_ref=ref,
                )
                db.add(hesap)
                await db.flush()
                sayac["hesap_acildi"] += 1
            else:
                sayac["hesap_zaten_vardi"] += 1
            hesap_id[ad] = hesap.id
        else:
            var = await db.get(Account, int(karar))
            if var is None:
                sayac["hesap_bulunamadi"] += 1
                continue
            hesap_id[ad] = var.id

    for satir in sonuc.musteri_satirlari:
        karar = kararlar.get(satir.ust_hesap)
        if karar is None:
            sayac["kararsiz_atlandi"] += 1
            continue
        if karar == KARAR_ATLA or satir.ust_hesap not in hesap_id:
            sayac["atlandi"] += 1
            continue
        var_cihaz = mevcut.get(satir.imei)
        if var_cihaz is not None:
            sayac["zaten_vardi"] += 1
            # Cihaz ERP'de var ama ZİMMETİ boş olabilir: hak ediş göçünde
            # sahiplik bilgisi yoktu (yalnız iş emri vardı), bu dosyada var.
            # Boş olanı doldururuz, DOLU olana dokunmayız — çakışma raporlanır.
            acik = await stok_svc.acik_konum(db, var_cihaz.id)
            if acik is None:
                var_cihaz.current_customer_id = hesap_id[satir.ust_hesap]
                await stok_svc.konum_ata(
                    db,
                    device_id=var_cihaz.id,
                    location_type="MUSTERI",
                    account_id=hesap_id[satir.ust_hesap],
                    ownership="MUSTERI_SATILDI",
                    clock=clock,
                    an=an,
                    notes="Takip platformu dışa aktarımı",
                )
                sayac["zimmet_yazildi"] += 1
            elif acik.account_id != hesap_id[satir.ust_hesap]:
                sayac["zimmet_catismasi"] += 1
            continue

        cihaz = Device(
            product_id=urun_id[MODEL_URUN[satir.model]],
            identity_kind="IMEI",
            imei=satir.imei,
            status="AKTIF",
            current_customer_id=hesap_id[satir.ust_hesap],
            notes=f"Platform cihaz adı: {satir.cihaz_adi}" if satir.cihaz_adi else None,
            source_system=KAYNAK,
            source_ref=f"imei:{satir.imei}",
        )
        db.add(cihaz)
        await db.flush()
        await stok_svc.konum_ata(
            db,
            device_id=cihaz.id,
            location_type="MUSTERI",
            account_id=hesap_id[satir.ust_hesap],
            ownership="MUSTERI_SATILDI",
            clock=clock,
            an=an,
            notes="Takip platformu dışa aktarımı",
        )
        mevcut[satir.imei] = cihaz
        sayac["cihaz"] += 1

    return dict(sayac)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
