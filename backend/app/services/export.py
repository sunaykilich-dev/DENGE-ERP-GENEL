"""Excel dışa aktarım — muhasebe programına göre şablonlanabilir kolon düzeni.

Muhasebe **Logo**; kolon adları ve sırası `settings.muhasebe_sablonu` ile
değiştirilebilir, koda gömülü değil (brief §6.5).
"""

import asyncio
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

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
