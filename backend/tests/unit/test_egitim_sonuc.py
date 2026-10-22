"""Gözlem sonucunun sunucuda hesaplanması (TS-151, E08-05; K7, R-84).

Eski sistemde sonuç istemcide hesaplanıp kaydediliyordu: kritik maddede
"yapmadı" işaretlenen bir gözlem yüksek ortalama yüzünden "başarılı"
görünebiliyordu. Sıra KESİN: KRITIK → EKSIK_GOZLEM → BASARILI (≥ eşik) →
GELISIM_GEREKLI; -1 (gözlenmedi) paydaya girmez.
"""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.services.teknik_servis.egitim import EgitimGirdiHatasi
from app.services.teknik_servis.egitim_gozlem import MaddePuani, sonuc_hesapla


@dataclass
class K:
    id: int
    is_critical: bool = False
    is_active: bool = True


KRITERLER = [K(1, is_critical=True), K(2), K(3), K(4)]


def _p(*degerler: int, gerekce: str | None = "görülmedi") -> list[MaddePuani]:
    return [MaddePuani(i + 1, d, gerekce if d == -1 else None) for i, d in enumerate(degerler)]


def test_r84_formulu_gozlenmedi_paydaya_girmez() -> None:
    puan, sonuc = sonuc_hesapla(_p(2, 2, 1, -1), KRITERLER, 85)
    assert puan == Decimal("83.33")
    assert sonuc == "GELISIM_GEREKLI"


def test_esik_ve_ustu_basarili() -> None:
    assert sonuc_hesapla(_p(2, 2, 2, 1), KRITERLER, 85) == (Decimal("87.50"), "BASARILI")
    assert sonuc_hesapla(_p(2, 2, 2, 1), KRITERLER, 90)[1] == "GELISIM_GEREKLI"


def test_kritik_sifir_ortalamadan_bagimsiz_kritik() -> None:
    puan, sonuc = sonuc_hesapla(_p(0, 2, 2, 2), [K(1, True), K(2), K(3), K(4)], 50)
    assert sonuc == "KRITIK"
    assert puan == Decimal("75.00")


def test_kritik_gozlenmedi_gerekceli_eksik_gozlem() -> None:
    _, sonuc = sonuc_hesapla(_p(-1, 2, 2, 2), KRITERLER, 85)
    assert sonuc == "EKSIK_GOZLEM"


def test_kritik_once_eksik_gozlemden() -> None:
    kriterler = [K(1, True), K(2, True), K(3), K(4)]
    assert sonuc_hesapla(_p(0, -1, 2, 2), kriterler, 85)[1] == "KRITIK"


@pytest.mark.parametrize(
    ("puanlar", "kriterler"),
    [
        (_p(-1, -1, -1, -1), KRITERLER),  # hiçbir madde gözlenmedi
        (_p(-1, 2, 2, 2, gerekce=None), KRITERLER),  # gerekçesiz -1
        ([MaddePuani(99, 2), MaddePuani(1, 2)], KRITERLER),  # kursa ait değil
        (_p(2, 2), [K(1, True), K(2, is_active=False)]),  # pasif madde
        ([MaddePuani(1, 2), MaddePuani(1, 1)], KRITERLER),  # aynı madde iki kez
        ([MaddePuani(2, 2)], KRITERLER),  # kritik madde cevaplanmamış
        ([MaddePuani(1, 3)], KRITERLER),  # katalog dışı puan
    ],
)
def test_gecersiz_girdi_400(puanlar, kriterler) -> None:
    with pytest.raises(EgitimGirdiHatasi):
        sonuc_hesapla(puanlar, kriterler, 85)


def test_pasif_kritik_madde_zorunlu_degil() -> None:
    kriterler = [K(1, True, is_active=False), K(2), K(3)]
    assert sonuc_hesapla([MaddePuani(2, 2), MaddePuani(3, 2)], kriterler, 85)[1] == "BASARILI"
