"""Excel dışa aktarım — muhasebe programına göre şablonlanabilir kolon düzeni.

Muhasebe **Logo**; kolon adları ve sırası `settings.muhasebe_sablonu` ile
değiştirilebilir, koda gömülü değil (brief §6.5).
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

BASLIK_DOLGU = PatternFill("solid", fgColor="E8E4DB")
BASLIK_YAZI = Font(bold=True, color="3C4657")


def _hucre(deger: Any) -> Any:
    if isinstance(deger, Decimal):
        return float(deger)
    return deger


def _formulu_metne_cevir(hucre) -> None:
    """`=` ile başlayan metni FORMÜL olarak değil METİN olarak yazdırır.

    Eski çözüm başına tek tırnak ekliyordu ("Excel tırnağı göstermez" diye).
    Bu XLSX'te DOĞRU DEĞİL: tırnak ancak hücrenin `quotePrefix` stili varsa
    gizlenir, düz metne eklendiğinde METNİN PARÇASI olur. Sonucu ölçtük —
    KVKK veri dökümündeki her telefon `'+905321112233` olarak çıkıyordu
    (ERP tüm numaraları `+90…` biçimine getirdiği için istisnasız hepsi),
    `-` ya da `@` ile başlayan her unvan ve açıklama da öyle.

    XLSX'te metin hücresi Excel tarafından zaten değerlendirilmez; tek risk
    openpyxl'in `=` ile başlayan metni formül hücresine çevirmesidir. Hücre
    tipini metne sabitlemek hem enjeksiyonu keser hem değeri aynen korur
    (dosyada `t="inlineStr"`).
    """
    if hucre.data_type == "f":
        hucre.data_type = "s"


async def satirlari_xlsx_async(
    basliklar: list[str], satirlar: list[list[Any]], sayfa_adi: str = "Sayfa1"
) -> bytes:
    """Excel'i AYRI BİR İŞ PARÇACIĞINDA üretir.

    openpyxl saf CPU işidir; olay döngüsünde koşarsa üretim süresince TÜM
    istekler bekler (ölçüldü: 25 KB'lık KVKK dökümü sırasında `/auth/me`
    9 ms yerine 143 ms). Satır sayısı büyüdükçe bu doğrusal artar.
    """
    return await asyncio.to_thread(satirlari_xlsx, basliklar, satirlar, sayfa_adi)


async def sablonla_async(sablon: str, kayitlar: list[dict], sayfa_adi: str) -> bytes:
    return await asyncio.to_thread(sablonla, sablon, kayitlar, sayfa_adi)


def satirlari_xlsx(
    basliklar: list[str], satirlar: list[list[Any]], sayfa_adi: str = "Sayfa1"
) -> bytes:
    """Genel amaçlı tablo → xlsx. Başlık koyu, sütun genişlikleri otomatik."""
    wb = Workbook()
    ws = wb.active
    ws.title = sayfa_adi[:31]
    ws.append(basliklar)
    for h in ws[1]:
        h.fill, h.font = BASLIK_DOLGU, BASLIK_YAZI
        h.alignment = Alignment(vertical="center")
    for satir in satirlar:
        ws.append([_hucre(x) for x in satir])
        for h in ws[ws.max_row]:
            _formulu_metne_cevir(h)

    for i, baslik in enumerate(basliklar, start=1):
        en = (
            max(len(str(baslik)), *(len(str(s[i - 1])) for s in satirlar))
            if satirlar
            else len(str(baslik))
        )
        ws.column_dimensions[get_column_letter(i)].width = min(max(en + 2, 10), 48)
    ws.freeze_panes = "A2"

    tampon = BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


# --- Çok sayfalı, tipli dışa aktarım (teknik servis, TS-026 / E12-06) ---------------
#
# `satirlari_xlsx` DEĞİŞMEZ (mobilite raporları ona bağlı). Teknik servis
# Excel'leri çok sayfalı olabilir ve hücre tipi SÜTUN ŞEMASINDAN gelir: seri
# no, iş no, telefon her zaman METİN (`0012345` ve 19 haneli seri sayıya
# dönüşüp bozulmasın), tarih gerçek tarih hücresi (Türkiye günü, `DD.MM.YYYY`).

SUTUN_TIPLERI = ("metin", "tarih", "zaman", "tamsayi", "ondalik")


@dataclass(frozen=True)
class Sutun:
    """Sütun şeması: başlık + hücre tipi (`SUTUN_TIPLERI`)."""

    baslik: str
    tip: str = "metin"

    def __post_init__(self) -> None:
        if self.tip not in SUTUN_TIPLERI:
            raise ValueError(f"Bilinmeyen sütun tipi: {self.tip}")


@dataclass
class Sayfa:
    """Bir çalışma sayfası. `sutunlar` düz başlık listesi de olabilir (tip = otomatik)."""

    ad: str
    sutunlar: list[Sutun | str]
    satirlar: list[list[Any]] = field(default_factory=list)
    # Servis raporları (TS-182/TS-201): başlıkta otomatik filtre; ya da adlı
    # Excel Tablosu (pivot şablonu yokken "tipli tablo yedeği"). Varsayılanlar
    # mevcut çıktıları değiştirmez.
    otomatik_filtre: bool = False
    tablo_adi: str | None = None
    # Başlık satırından ÖNCE yazılan açıklama satırları (dönem, kapsam, not).
    ust_bilgi: list[list[Any]] = field(default_factory=list)


_TR = ZoneInfo("Europe/Istanbul")


def _tipli(deger: Any, tip: str | None) -> tuple[Any, str | None]:
    """(hücre değeri, number_format). Saat dilimli an Türkiye saatine çevrilir;
    Excel saat dilimi taşımadığı için hücreye naif yerel değer yazılır."""
    if deger is None or deger == "":
        return None, None
    if tip == "metin":
        return str(deger), "@"
    if tip in ("tarih", "zaman"):
        if isinstance(deger, datetime):
            if deger.tzinfo is not None:
                deger = deger.astimezone(_TR).replace(tzinfo=None)
            if tip == "tarih":
                return deger.date(), "DD.MM.YYYY"
            return deger, "DD.MM.YYYY HH:MM"
        if isinstance(deger, date):
            return deger, "DD.MM.YYYY"
        return str(deger), "@"
    if tip == "tamsayi":
        return int(deger), "0"
    if tip == "ondalik":
        return float(deger), "#,##0.00"
    return _hucre(deger), None


def sayfalari_xlsx(sayfalar: list[Sayfa]) -> bytes:
    """Çok sayfalı xlsx. Şemalı sütunda tip şemadan; formül enjeksiyonu kapalı."""
    wb = Workbook()
    wb.remove(wb.active)
    for sayfa in sayfalar:
        ws = wb.create_sheet(title=(sayfa.ad or "Sayfa")[:31])
        sema = [s if isinstance(s, Sutun) else None for s in sayfa.sutunlar]
        basliklar = [s.baslik if isinstance(s, Sutun) else str(s) for s in sayfa.sutunlar]
        for bilgi in sayfa.ust_bilgi:
            ws.append([_hucre(x) for x in bilgi])
            for h in ws[ws.max_row]:
                _formulu_metne_cevir(h)
        ws.append(basliklar)
        baslik_satiri = ws.max_row
        for h in ws[baslik_satiri]:
            h.fill, h.font = BASLIK_DOLGU, BASLIK_YAZI
            h.alignment = Alignment(vertical="center")
        genislik = [len(b) for b in basliklar]
        satirlar = sayfa.satirlar
        if sayfa.tablo_adi and not satirlar:
            # Excel Tablosu en az bir veri satırı ister; boş sonuç açıkça yazılır.
            satirlar = [["Kayıt yok"]]
        for satir in satirlar:
            ws.append([None] * len(basliklar))
            r = ws.max_row
            for i, deger in enumerate(satir[: len(basliklar)]):
                tip = sema[i].tip if sema[i] is not None else None
                hucre_degeri, bicim = _tipli(deger, tip)
                hucre = ws.cell(row=r, column=i + 1)
                hucre.value = hucre_degeri
                if bicim:
                    hucre.number_format = bicim
                if tip == "metin" and hucre_degeri is not None:
                    hucre.data_type = "s"
                _formulu_metne_cevir(hucre)
                genislik[i] = max(genislik[i], len(str(deger)) if deger is not None else 0)
        for i, en in enumerate(genislik, start=1):
            ws.column_dimensions[get_column_letter(i)].width = min(max(en + 2, 10), 48)
        ws.freeze_panes = f"A{baslik_satiri + 1}"
        alan = f"A{baslik_satiri}:{get_column_letter(len(basliklar))}{ws.max_row}"
        if sayfa.tablo_adi:
            tablo = Table(displayName=sayfa.tablo_adi, ref=alan)
            tablo.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            ws.add_table(tablo)
        elif sayfa.otomatik_filtre:
            ws.auto_filter.ref = alan
    tampon = BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def sayfalari_xlsx_async(sayfalar: list[Sayfa]) -> bytes:
    """`sayfalari_xlsx`'i ayrı iş parçacığında üretir (bkz. `satirlari_xlsx_async`)."""
    return await asyncio.to_thread(sayfalari_xlsx, sayfalar)


# Muhasebe şablonları: kolon başlığı → değer anahtarı.
# Logo Tiger/Go'nun beklediği düzen; yeni program geldiğinde buraya eklenir.
SABLONLAR: dict[str, list[tuple[str, str]]] = {
    "logo": [
        ("Cari Kodu", "cari_kodu"),
        ("Cari Ünvanı", "unvan"),
        ("VKN/TCKN", "vkn"),
        ("Belge Tipi", "belge_tipi"),
        ("Belge No", "belge_no"),
        ("Belge Tarihi", "belge_tarihi"),
        ("Dönem", "donem"),
        ("Brüt Tutar", "brut"),
        ("Kesinti", "kesinti"),
        ("Matrah", "matrah"),
        ("KDV", "kdv"),
        ("Stopaj", "stopaj"),
        ("Damga Vergisi", "damga"),
        ("Net Ödenecek", "net"),
        ("IBAN", "iban"),
        ("Açıklama", "aciklama"),
    ],
    "genel": [
        ("Montaj Noktası", "unvan"),
        ("Dönem", "donem"),
        ("Brüt", "brut"),
        ("Kesinti", "kesinti"),
        ("Net", "net"),
        ("IBAN", "iban"),
    ],
}


def sablonla(sablon: str, kayitlar: list[dict], sayfa_adi: str) -> bytes:
    duzen = SABLONLAR.get(sablon, SABLONLAR["genel"])
    basliklar = [b for b, _ in duzen]
    satirlar = [[k.get(anahtar, "") for _, anahtar in duzen] for k in kayitlar]
    return satirlari_xlsx(basliklar, satirlar, sayfa_adi)
