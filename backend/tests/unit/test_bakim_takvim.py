"""Bakım takvimi: dönem hedef tarihleri ve döngü (TS-061, E04-05).

**Neden:** eski sistem "yapılan dönem" sayacını saklıyor ve sıradaki dönemi
`CompletedCount + 1` ile seçiyordu; yıl devrinde sayaç sıfırlanmayınca ya da
tek cihaz açık kalınca bütün yıl kilitleniyordu. Yeni modelde dönemler
sözleşme döngüsünden (takvim yılı DEĞİL) saf fonksiyonla hesaplanır.
"""

from datetime import UTC, date, datetime

import pytest

from app.services.teknik_servis.bakim import (
    ay_ekle,
    donem_plani,
    dongu_baslangiclari,
    guncel_dongu,
    hedef_tarihler,
)
from app.services.teknik_servis.kancalar import ServisGirdiHatasi


def test_esit_aralik_frekans_3() -> None:
    assert hedef_tarihler(date(2026, 6, 1), 3, None) == [
        date(2026, 6, 1),
        date(2026, 10, 1),
        date(2027, 2, 1),
    ]


def test_sabit_aylar_dongu_icindeki_ilk_karsilik() -> None:
    # 01.06 başlangıç, "5. ve 11. ayda": kasım bu döngüde, mayıs ertesi yıl.
    assert hedef_tarihler(date(2026, 6, 1), 2, [5, 11]) == [date(2026, 11, 1), date(2027, 5, 1)]


def test_ay_sonu_kirpma() -> None:
    assert ay_ekle(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert ay_ekle(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert hedef_tarihler(date(2026, 8, 31), 2, None) == [date(2026, 8, 31), date(2027, 2, 28)]


def test_29_subat_sonraki_yillarda_28_subat() -> None:
    assert dongu_baslangiclari(date(2028, 2, 29), date(2031, 1, 1)) == [
        date(2028, 2, 29),
        date(2029, 2, 28),
        date(2030, 2, 28),
    ]


def test_bitis_sonrasi_donem_uretilmez() -> None:
    # 01.06.2026–01.12.2026, frekans 3: 01.02.2027 hedefi bitişten sonra.
    plan = donem_plani(date(2026, 6, 1), date(2026, 12, 1), 3, None)
    assert [h for _, _, h in plan] == [date(2026, 6, 1), date(2026, 10, 1)]


def test_iki_yillik_sozlesme_iki_dongu() -> None:
    plan = donem_plani(date(2026, 1, 1), date(2028, 1, 1), 2, None)
    assert [(d, s) for d, s, _ in plan] == [
        (date(2026, 1, 1), 1),
        (date(2026, 1, 1), 2),
        (date(2027, 1, 1), 1),
        (date(2027, 1, 1), 2),
    ]


def test_yil_devri_dongu_takvim_yili_degildir() -> None:
    """E04-05 kabul 1: 01.06.2026 başlangıçlı sözleşmede 02.01.2027 hâlâ ilk
    döngüdür; 01.01.2026 başlangıçlıda 02.01.2027 ikinci döngüdür (sayaç
    yeni döngüde 0'dan sayılır — saklanmadığı için sıfırlanması gerekmez)."""
    an = datetime(2027, 1, 2, 9, tzinfo=UTC)
    haziran = [datetime(2026, 6, 1, tzinfo=UTC), datetime(2027, 6, 1, tzinfo=UTC)]
    assert guncel_dongu(haziran, an) == haziran[0]
    ocak = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)]
    assert guncel_dongu(ocak, an) == ocak[1]


@pytest.mark.parametrize("frekans", [0, 13])
def test_frekans_sinir_disi(frekans: int) -> None:
    with pytest.raises(ServisGirdiHatasi):
        hedef_tarihler(date(2026, 1, 1), frekans, None)


def test_frekans_12_her_ay() -> None:
    tarihler = hedef_tarihler(date(2026, 1, 15), 12, None)
    assert len(tarihler) == 12
    assert tarihler[-1] == date(2026, 12, 15)
