"""Planlama P3 ve zaman takibi saf kuralları (TS-189, TS-190) — DB'siz.

- Plan uyumu = aynı İSTANBUL günü (UTC günü değil); kayıt yok → EKSIK.
- Oran paydası 0 → None ("%0" değil); eksik paydaya girmez.
- Müsaitlik notu ≤200 ve sağlık bilgisi içermez (KVKK m.6, E02 K-11).
- Tekrar ziyaret yalnız müşteri+lokasyonu bilinen ziyaretlerde sayılır.
"""

from datetime import UTC, date, datetime

import pytest

from app.services.teknik_servis import planlama, takvim, zaman


def test_uyum_sinifi_istanbul_gunu() -> None:
    gun = date(2026, 1, 15)
    # 14.01 21:30 UTC = 15.01 00:30 TR → aynı gün.
    assert takvim.uyum_sinifi(gun, datetime(2026, 1, 14, 21, 30, tzinfo=UTC)) == "UYUMLU"
    # 15.01 22:30 UTC = 16.01 01:30 TR → başka gün.
    assert takvim.uyum_sinifi(gun, datetime(2026, 1, 15, 22, 30, tzinfo=UTC)) == "KAYDI"
    assert takvim.uyum_sinifi(gun, None) == "EKSIK"


def test_uyum_orani_eksik_paydada_yok() -> None:
    assert takvim.uyum_orani(2, 1) == 66.7
    assert takvim.uyum_orani(0, 0) is None
    assert takvim.uyum_orani(0, 3) == 0.0


def test_tekrar_ziyaret_sayisi() -> None:
    a = (1, 10)
    ziyaretler = [
        (a, date(2026, 1, 1)),
        (a, date(2026, 1, 31)),  # 30 gün → tekrar
        (a, date(2026, 3, 15)),  # 43 gün → değil
        ((2, 20), date(2026, 1, 2)),
        (None, date(2026, 1, 3)),  # lokasyonu bilinmeyen sayılmaz
        (None, date(2026, 1, 4)),
    ]
    assert takvim.tekrar_ziyaret_sayisi(ziyaretler) == 1


def test_canli_orani_bos_payda() -> None:
    assert zaman.canli_orani_hesapla(7200, 10800) == 66.7
    assert zaman.canli_orani_hesapla(None, 3600) == 0.0
    assert zaman.canli_orani_hesapla(None, None) is None
    assert zaman.canli_orani_hesapla(0, 0) is None


@pytest.mark.parametrize(
    "metin",
    ["Hastanede", "HASTALIK izni", "sağlık raporu", "İLAÇ tedavisi", "Ameliyat", "doktor kontrolü"],
)
def test_saglik_bilgisi_reddedilir(metin: str) -> None:
    assert planlama.saglik_bilgisi_var_mi(metin)
    with pytest.raises(planlama.PlanlamaGirdiHatasi):
        planlama.musaitlik_notu_dogrula(metin)


def test_musaitlik_notu_siniri() -> None:
    assert planlama.musaitlik_notu_dogrula("  ") is None
    assert planlama.musaitlik_notu_dogrula("Yıllık izin") == "Yıllık izin"
    assert planlama.musaitlik_notu_dogrula("x" * 200) == "x" * 200
    with pytest.raises(planlama.PlanlamaGirdiHatasi):
        planlama.musaitlik_notu_dogrula("x" * 201)


def test_zaman_kpi_kodlari_tutarli() -> None:
    """Her KPI ya bölüm listesi, ya iş listesi açar ya da oran KPI'sıdır."""
    kodlar = set(zaman.ZAMAN_KPI_TANIMLARI)
    liste = set(zaman.KAYIT_KPI_KODLARI) | set(zaman.IS_KPI_KODLARI)
    assert liste <= kodlar and kodlar - liste == {"canli_orani"}
    assert not set(zaman.KAYIT_KPI_KODLARI) & set(zaman.IS_KPI_KODLARI)
