"""Vergi levhası PDF/PNG'lerinden müşteri künyesi çıkarır.

GİB'in ürettiği levhada **VKN metin katmanında YOKTUR** — barkod görüntüsü
olarak basılır, altındaki rakamlar da o görüntünün parçasıdır. Bu yüzden
alanların bir kısmı metinden, VKN ve onay kodu BARKODDAN okunur.

Unvan, adres ve vergi dairesi metin katmanından gelir; levha iki sütunlu bir
form olduğu için düzen (layout) kipinde okunup sütun sınırından bölünür.

PDF okuma ve barkod çözme bağımlılıkları yalnız bu betik için gerekli; ana
uygulamaya yük olmasınlar diye `--with` ile geçici kurulur:

    uv run --with pypdf --with zxing-cpp --with pillow \
        python -m app.migration.vergi_levhasi <dizin>            # ÖNİZLEME
    uv run --with pypdf --with zxing-cpp --with pillow \
        python -m app.migration.vergi_levhasi <dizin> --uygula   # yazar

Yazma kuralı: **dolu alanın üzerine yazılmaz.** Levha resmî kaynaktır ama
ekibin elle düzelttiği bir kaydı geri almak, düzeltmeyi boşa çıkarırdı.
Çakışma varsa raporlanır, karar insana kalır.
"""

import argparse
import asyncio
import difflib
import io
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import Account
from app.services.normalize import normalize_tax_no, tr_normkey

# Levhanın sol sütunundaki etiketler. Sağ sütun ayrı ele alınır.
SOL_ETIKETLER = {
    "ADI SOYADI": "ad_soyad",
    "TİCARET ÜNVANI": "unvan",
    "İŞ YERİ ADRESİ": "adres",
    "VERGİ TÜRÜ": "vergi_turu",
}
# Sağ sütunda etiket iki satıra bölünüyor ve DEĞER bazen birinci, bazen
# ikinci satırda duruyor: "VERGİ ... KALE" / "DAİRESİ" ama
# "İŞE BAŞLAMA" / "TARİHİ ... 25.07.2005". Bu yüzden her satır parçası
# ayrı ayrı eşlenir. Sıra ÖNEMLİ: "VERGİ KİMLİK" daha uzun, önce bakılır —
# yoksa "VERGİ" ön ekiyle eşleşip vergi dairesine "KİMLİK" eklenir.
SAG_ETIKETLER: tuple[tuple[str, str | None], ...] = (
    ("VERGİ KİMLİK", None),  # değeri barkodda
    ("TC KİMLİK NO", None),
    ("VERGİ", "vergi_dairesi"),
    ("DAİRESİ", "vergi_dairesi"),
    ("İŞE BAŞLAMA", "ise_baslama"),
    ("TARİHİ", "ise_baslama"),
    ("NO", None),
)
# METİN KATMANI OLMAYAN levhalar. Bu dört dosya taranmış görüntü; ne pypdf
# ne pdfium metin çıkarabiliyor, yalnız barkod çözülüyor. Alanlar sayfa
# görüntüsünden ELLE okundu ve buraya yazıldı — tahmin değil, okunan değer.
# VKN'ler barkoddan çözülenle birebir aynı, yani okuma doğrulandı.
ELLE_OKUNAN: dict[str, dict[str, str]] = {
    "AKÇADAĞ VERGİ LEVHASI.pdf": {
        "unvan": "AKÇADAĞ İNŞAAT ENERJİ MADENCİLİK ANONİM ŞİRKETİ",
        "adres": "YENİŞEHİR MAH. LİSE CAD. FIRAT APARTMANI NO: 20 İÇ KAPI NO: 14 "
        "YENİŞEHİR/ DİYARBAKIR",
        "vergi_dairesi": "SÜLEYMANNAZİF",
        "vkn": "0180825365",
    },
    "veramobil vergi levhası.pdf": {
        "unvan": "VERA MOBİL ARAÇ TAKİP SİSTEMLERİ VE DANIŞMANLIK LİMİTED ŞİRKETİ",
        "adres": "MERKEZEFENDİ MAH. MEVLANA CAD. PANORAMA SİTESİ C BLOK NO: 102 C "
        "ZEYTİNBURNU/ İSTANBUL",
        "vergi_dairesi": "DAVUTPAŞA",
        "vkn": "9240674659",
    },
    "VERGİ LEVHASI.pdf": {
        "unvan": "NİCOMEDYA TURİZM SANAYİ TİCARET LİMİTED ŞİRKETİ",
        "adres": "AKARCA MAH. YERGUZLAR (FCA) CAD. NO: 18 İÇ KAPI NO: 3 FETHİYE/ MUĞLA",
        "vergi_dairesi": "FETHİYE",
        "vkn": "6311495141",
    },
    "METAL OTO 2022 VERGİ LEVHASI.png": {
        "unvan": "METAL OTO TİCARET ANONİM ŞİRKETİ",
        "adres": "KÜÇÜKBAKKALKÖY MAH. IŞIKLAR CAD. NO: 30 İÇ KAPI NO: 5 ATAŞEHİR/ İSTANBUL",
        "vergi_dairesi": "KOZYATAĞI",
        "vkn": "6190833982",
    },
}

# Sağ sütunun başladığı kolon SABİT DEĞİL: unvan uzunluğu sayfa düzenini
# kaydırıyor. Bu çapa etiketlerinin en soldaki konumu sınır kabul edilir.
SAG_CAPALAR = ("TC KİMLİK NO", "VERGİ KİMLİK", "İŞE BAŞLAMA", "DAİRESİ")


@dataclass
class Levha:
    dosya: str
    unvan: str | None = None
    ad_soyad: str | None = None
    adres: str | None = None
    vergi_dairesi: str | None = None
    vergi_turu: str | None = None
    ise_baslama: str | None = None
    vkn: str | None = None
    tckn: str | None = None
    onay_kodu: str | None = None
    uyarilar: list[str] = field(default_factory=list)

    @property
    def baslik(self) -> str:
        return self.unvan or self.ad_soyad or ""


def _temiz(metin: str) -> str:
    return re.sub(r"\s+", " ", metin).strip()


def _sag_sutun_baslangici(duzen: str) -> int:
    """Sağ sütunun kolon numarası — çapa etiketlerinin EN SIK konumu.

    En küçüğü alınamaz: uzun bir unvan sağ sütunun üstüne taşabiliyor
    ("…ANONİMVERGİ KİMLİK") ve o tek satır sınırı sola çekip bütün sayfayı
    yanlış böler.
    """
    konumlar = Counter(
        satir.index(capa)
        for satir in duzen.splitlines()
        for capa in SAG_CAPALAR
        if capa in satir and satir.index(capa) > 20
    )
    return konumlar.most_common(1)[0][0] if konumlar else 77


def _metni_ayristir(duzen: str, levha: Levha) -> None:
    """İki sütunlu formu etiketlere göre çözer."""
    sag_sutun = _sag_sutun_baslangici(duzen)
    sol_alan = sag_alan = None
    sol: dict[str, list[str]] = {}
    sag: dict[str, list[str]] = {}

    for ham in duzen.splitlines():
        solu, sagi = ham[:sag_sutun], ham[sag_sutun:]

        # --- sol sütun ---
        govde = solu.rstrip()
        if govde.strip():
            etiket = next((e for e in SOL_ETIKETLER if govde.startswith(e)), None)
            if etiket:
                sol_alan = SOL_ETIKETLER[etiket]
                sol.setdefault(sol_alan, []).append(govde[len(etiket) :])
            elif govde.startswith(" ") and sol_alan:
                sol[sol_alan].append(govde)
            else:
                sol_alan = None  # başlık ya da tablo satırı

        # --- sağ sütun ---
        gov2 = sagi.rstrip()
        if gov2.strip():
            eslesen = next((e for e, a in SAG_ETIKETLER if gov2.startswith(e)), None)
            if eslesen is not None:
                alan = dict(SAG_ETIKETLER)[eslesen]
                sag_alan = alan
                if alan:
                    sag.setdefault(alan, []).append(gov2[len(eslesen) :])
            elif gov2.startswith(" ") and sag_alan:
                sag[sag_alan].append(gov2)
            else:
                sag_alan = None

    for alan, parcalar in {**sol, **sag}.items():
        deger = _temiz(" ".join(parcalar))
        # Taşan satırda sağ sütun etiketi sol değere yapışıyor; sonundan at.
        for capa in SAG_CAPALAR + ("VERGİ",):
            if deger.endswith(capa):
                deger = deger[: -len(capa)].strip()
        if deger:
            setattr(levha, alan, deger)


def _barkodlari_oku(gorseller, levha: Levha) -> None:
    """VKN/TCKN ve onay kodu barkoddan çözülür."""
    import zxingcpp
    from PIL import Image

    for ham in gorseller:
        try:
            resim = Image.open(io.BytesIO(ham)).convert("L")
        except Exception as exc:  # noqa: BLE001 - bozuk görüntü levhayı düşürmesin
            print(f"  ! görüntü açılamadı: {exc}", file=sys.stderr)
            continue
        # Taranmış levhada çubuklar tek piksel kalınlığında kalıyor ve çözücü
        # okuyamıyor; iki kat büyütmek yetiyor.
        adaylar = [resim]
        if min(resim.size) < 600:
            adaylar.append(resim.resize((resim.width * 2, resim.height * 2), Image.LANCZOS))
        for aday in adaylar:
            for sonuc in zxingcpp.read_barcodes(aday):
                metin = sonuc.text.strip()
                if metin.isdigit() and len(metin) == 10:
                    levha.vkn = metin
                elif metin.isdigit() and len(metin) == 11:
                    levha.tckn = metin
                elif metin:
                    levha.onay_kodu = metin


def levhayi_oku(yol: Path) -> Levha:
    levha = Levha(dosya=yol.name)
    if yol.suffix.lower() == ".png" or yol.suffix.lower() in (".jpg", ".jpeg"):
        # Taranmış levha: metin katmanı yok, yalnız barkod okunabilir.
        _barkodlari_oku([yol.read_bytes()], levha)
        _elle_tamamla(levha)
        if not levha.baslik:
            levha.uyarilar.append("Görüntü dosyası — unvan/adres okunamadı")
        return levha

    from pypdf import PdfReader

    try:
        sayfa = PdfReader(yol).pages[0]
    except Exception as exc:  # noqa: BLE001
        levha.uyarilar.append(f"PDF okunamadı: {exc}")
        return levha

    _metni_ayristir(sayfa.extract_text(extraction_mode="layout") or "", levha)
    _barkodlari_oku([im.data for im in sayfa.images], levha)

    _elle_tamamla(levha)
    if not levha.baslik:
        levha.uyarilar.append("Unvan/ad bulunamadı")
    if not (levha.vkn or levha.tckn):
        levha.uyarilar.append("VKN/TCKN barkodu çözülemedi")
    return levha


def _elle_tamamla(levha: Levha) -> None:
    """Metin katmanı olmayan levhaların elle okunan alanlarını yerleştirir.

    Barkoddan çözülen VKN ile tablodaki VKN tutmuyorsa yazılmaz ve uyarı
    düşülür: yanlış dosyaya yanlış künye yazmak sessiz bir hatadır.
    """
    veri = ELLE_OKUNAN.get(levha.dosya)
    if not veri:
        return
    if levha.vkn and veri.get("vkn") and levha.vkn != veri["vkn"]:
        levha.uyarilar.append(
            f"Elle okunan VKN ({veri['vkn']}) barkodla ({levha.vkn}) uyuşmuyor — atlandı"
        )
        return
    for alan, deger in veri.items():
        if not getattr(levha, alan, None):
            setattr(levha, alan, deger)
    levha.uyarilar.append("Alanlar sayfa görüntüsünden elle okundu")


def dizini_oku(dizin: Path) -> list[Levha]:
    dosyalar = sorted(
        p for p in dizin.iterdir() if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg")
    )
    return [levhayi_oku(p) for p in dosyalar]


# Elle doğrulanmış eşleşmeler. Otomatik yol bunları tutturamıyor ve tutturmaya
# zorlanmamalı; karar insanın, gerekçe yanında duruyor (bkz. esleme.ELLE_ESLEME).
ELLE_ESLESME = {
    # Kullanıcı 23.09.2026'da #339 ile #408'i birleştirme kararı verdi — levha
    # bu firmanın tüzel kişiliği. ERP'deki ad yazım hatalı: OTOMATİV.
    "Vergi Levhası 2024 otomotiv.pdf": 408,
    # "TİC." = TİCARET, "A.Ş." = ANONİM ŞİRKETİ. Platformdan gelen 1.699
    # cihazlık #684 ile levhadaki unvan yalnız bu kısaltmalarda ayrılıyor.
    "METAL OTO 2022 VERGİ LEVHASI.png": 684,
}


# --- ERP eşleştirme ---------------------------------------------------------

# Şirket türü ekleri; iki adı karşılaştırırken gürültüden başka bir şey değiller.
AD_EKLERI = frozenset(
    "ANONIM SIRKETI SIRKET LIMITED LTD STI AS VE TICARET TIC SANAYI SANAYII SAN IC DIS".split()
)


def _cekirdek(ad: str) -> str:
    """Unvandan şirket türü eklerini atar. Levhadaki unvan resmî ve uzun,
    ERP'deki ad kısa yazılmış oluyor — kıyas ancak çekirdek üzerinden anlamlı."""
    return " ".join(k for k in ad.split() if k not in AD_EKLERI)


def _benzerleri_bul(k: str, anahtar: dict[str, Account]) -> list[Account]:
    """Ada göre aday üretir; ASLA seçmez.

    Başlangıç eşleşmesi tek harf farkta kopuyor: levhadaki "ÇAMKIRAN OTOMOTİV"
    ile ERP'deki "ÇAMKIRAN OTOMATİV" böyle ıskalanıyordu. Bu kadar yakın iki ad
    aynı firma da olabilir başka firma da; karar insanın.
    """
    cekirdek = _cekirdek(k)
    ilk = cekirdek.split()[0] if cekirdek else ""
    if len(ilk) < 4:  # "D VE D" gibi kısa başlangıçlar her adı tutturuyor
        ilk = ""

    puanli: list[tuple[float, int, Account]] = []
    for aday_anahtar, hesap in anahtar.items():
        aday = _cekirdek(aday_anahtar)
        puan = difflib.SequenceMatcher(None, cekirdek, aday).ratio()
        if ilk and aday.split()[:1] == [ilk]:
            puan = max(puan, 0.90)
        if puan >= 0.80:
            puanli.append((puan, hesap.id, hesap))
    puanli.sort(key=lambda t: (-t[0], t[1]))
    return [h for _, _, h in puanli[:3]]


async def eslestir(db: AsyncSession, levhalar: list[Levha]) -> list[dict]:
    """Levhaları ERP hesaplarıyla eşler.

    Önce VKN (kesin), sonra unvan anahtarı, sonra unvanın BAŞLANGICI —
    platform ve ERP kısa/uzun ad tutabiliyor (bkz. fleet_cihaz).
    """
    hesaplar = (await db.scalars(select(Account).where(Account.is_deleted.is_(False)))).all()
    vkn_ile = {h.tax_no: h for h in hesaplar if h.tax_no}
    anahtar = {h.title_key: h for h in hesaplar}

    satirlar = []
    for levha in levhalar:
        hesap, yol = None, None
        if (elle_id := ELLE_ESLESME.get(levha.dosya)) is not None:
            hesap = next((h for h in hesaplar if h.id == elle_id), None)
            yol = "elle" if hesap else None
            if hesap is None:
                levha.uyarilar.append(f"elle eşleşme #{elle_id} bulunamadı")

        if hesap is None and levha.vkn:
            hesap = vkn_ile.get(levha.vkn)
            yol = "VKN" if hesap else None

        if hesap is None and levha.baslik:
            k = tr_normkey(levha.baslik)
            hesap = anahtar.get(k)
            if hesap:
                yol = "unvan"
            else:
                adaylar = [
                    h
                    for a, h in anahtar.items()
                    if len(k) >= 6 and (a.startswith(k[:20]) or k.startswith(a))
                ]
                if len(adaylar) == 1:
                    hesap, yol = adaylar[0], "başlangıç"
                elif adaylar:
                    levha.uyarilar.append(
                        f"{len(adaylar)} hesap adayı: "
                        + ", ".join(f"#{a.id} {a.title}" for a in adaylar[:3])
                    )
                else:
                    benzer = _benzerleri_bul(k, anahtar)
                    if benzer:
                        levha.uyarilar.append(
                            f"{len(benzer)} benzer hesap (ad benzerliği, kesin değil): "
                            + ", ".join(f"#{h.id} {h.title}" for h in benzer)
                        )

        satirlar.append({"levha": levha, "hesap": hesap, "yol": yol})
    return satirlar


def _degisiklikler(levha: Levha, hesap: Account) -> dict[str, str]:
    """Yalnız BOŞ alanlar doldurulur; dolu alan asla ezilmez."""
    aday = {
        "tax_no": levha.vkn or levha.tckn,
        "tax_office": levha.vergi_dairesi,
    }
    return {a: d for a, d in aday.items() if d and not getattr(hesap, a)}


async def uygula(
    db: AsyncSession, eslesmeler: list[dict], *, dizin: Path | None = None
) -> dict[str, int]:
    sayac: Counter = Counter()
    for satir in eslesmeler:
        levha, hesap = satir["levha"], satir["hesap"]
        if hesap is None:
            sayac["hesap_bulunamadi"] += 1
            continue
        degisen = _degisiklikler(levha, hesap)
        if not degisen:
            sayac["degisiklik_yok"] += 1
            continue
        for alan, deger in degisen.items():
            if alan == "tax_no":
                try:
                    deger = normalize_tax_no(deger)
                except ValueError:
                    sayac["vkn_gecersiz"] += 1
                    continue
            setattr(hesap, alan, deger)
            sayac[f"yazilan_{alan}"] += 1
        sayac["guncellenen_hesap"] += 1

    if dizin is not None:
        sayac.update(await _levhalari_ekle(db, eslesmeler, dizin))
    await db.flush()
    return dict(sayac)


async def _levhalari_ekle(db: AsyncSession, eslesmeler: list[dict], dizin: Path) -> Counter:
    """Levha dosyasını hesabın ekine koyar.

    Künyeyi yazmak yetmiyor: "bu VKN nereden geldi" sorusunun cevabı belgenin
    kendisi. Aynı içerik iki kez yüklenmez (depo sha256 ile tekilleştiriyor),
    bu yüzden betik tekrar çalıştırılabilir.
    """
    from app.models import Attachment
    from app.services import storage as depo

    sayac: Counter = Counter()
    for satir in eslesmeler:
        hesap, levha = satir["hesap"], satir["levha"]
        if hesap is None:
            continue
        yol = dizin / levha.dosya
        if not yol.is_file():
            continue
        icerik = yol.read_bytes()
        tip = "application/pdf" if yol.suffix.lower() == ".pdf" else "image/png"
        try:
            kayit = depo.yaz(icerik, mime_type=tip)
        except depo.DepoHatasi:
            sayac["ek_reddedildi"] += 1
            continue
        var = await db.scalar(
            select(Attachment).where(
                Attachment.entity == "accounts",
                Attachment.entity_id == hesap.id,
                Attachment.sha256 == kayit.sha256,
            )
        )
        if var is not None:
            sayac["ek_zaten_vardi"] += 1
            continue
        db.add(
            Attachment(
                entity="accounts",
                entity_id=hesap.id,
                kind="VERGI_LEVHASI",
                file_name=depo.temiz_ad(levha.dosya),
                storage_path=kayit.storage_path,
                mime_type=kayit.mime_type,
                size_bytes=kayit.size_bytes,
                sha256=kayit.sha256,
                notes=f"Vergi dairesi: {levha.vergi_dairesi or '—'}",
            )
        )
        sayac["ek_yuklendi"] += 1
    return sayac


def rapor(eslesmeler: list[dict]) -> str:
    satirlar = ["=" * 78, f"VERGİ LEVHASI — {len(eslesmeler)} dosya", "=" * 78, ""]
    for satir in eslesmeler:
        levha, hesap, yol = satir["levha"], satir["hesap"], satir["yol"]
        kimlik = levha.vkn or levha.tckn or "—"
        satirlar.append(f"{levha.dosya[:38]:40} {kimlik:>12}  {levha.baslik[:44]}")
        if hesap is not None:
            degisen = _degisiklikler(levha, hesap)
            durum = ", ".join(f"{a}←{d}" for a, d in degisen.items()) or "değişiklik yok"
            satirlar.append(f"{'':40} → ERP #{hesap.id} {hesap.title[:34]} ({yol}) · {durum}")
        else:
            satirlar.append(f"{'':40} → ERP'de EŞLEŞME YOK")
        for uyari in levha.uyarilar:
            satirlar.append(f"{'':40}   ! {uyari[:70]}")
    return "\n".join(satirlar)


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Vergi levhası aktarımı")
    ayristirici.add_argument("dizin", type=Path)
    ayristirici.add_argument("--uygula", action="store_true", help="Değişiklikleri YAZ")
    args = ayristirici.parse_args(argv)

    if not args.dizin.is_dir():
        print(f"Dizin yok: {args.dizin}", file=sys.stderr)
        return 1

    levhalar = dizini_oku(args.dizin)
    async with get_session_factory()() as db:
        eslesmeler = await eslestir(db, levhalar)
        print(rapor(eslesmeler))

        if not args.uygula:
            print("\nÖNİZLEME — hiçbir şey yazılmadı. Yazmak için --uygula ekleyin.")
            return 0

        sayac = await uygula(db, eslesmeler, dizin=args.dizin)
        await db.commit()

    print("\n" + "=" * 78)
    print("UYGULANDI")
    for ad, adet in sorted(sayac.items()):
        print(f"  {ad:26} {adet}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
