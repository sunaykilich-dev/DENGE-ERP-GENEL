"""Çakışma motorunun saf katmanı (TS-045, E02-10/15) — DB'siz.

Örtüşme yarı açık aralıktır; aynı ziyaretin işleri birbiriyle çakışmaz; saati
belirsiz plan çakışmaya girmez; şef yalnız sahaya gidiyorsa kişi kümesindedir
(küme çağıran tarafından `sahaya_gidiyor` ile kurulur); araç ve müsaitlik
bloğu da çakışmadır; gece yarısını aşan plan iki günü kilitler.
"""

from datetime import UTC, date, datetime

from app.services.teknik_servis.cakisma import (
    Aday,
    dokunulan_gunler,
    gerekce_gecerli_mi,
    ortusen_planlar,
    ortusur,
)


def _an(saat: int, dakika: int = 0, gun: int = 15) -> datetime:
    return datetime(2026, 1, gun, saat, dakika, tzinfo=UTC)


def _aday(pid, bas, bit, kisiler=(), *, ziyaret=None, arac=None) -> Aday:
    return Aday(
        plan_id=pid,
        baslangic=bas,
        bitis=bit,
        visit_id=ziyaret,
        sahadakiler=frozenset(kisiler),
        arac_id=arac,
    )


def test_yari_acik_aralik() -> None:
    assert ortusur(_an(10), _an(12), _an(11), _an(13))
    assert not ortusur(_an(10), _an(11), _an(11), _an(12))  # uç uca


def test_ortak_kisi_cakisir_farkli_kisi_cakismaz() -> None:
    a = _aday(1, _an(7), _an(9), {5})
    b = _aday(2, _an(8), _an(10), {5, 6})
    c = _aday(3, _an(8), _an(10), {7})
    assert ortusen_planlar([a, b, c]) == {1, 2}


def test_ayni_ziyaret_cakismaz() -> None:
    a = _aday(1, _an(7), _an(9), {5}, ziyaret=10)
    b = _aday(2, _an(7), _an(9), {5}, ziyaret=10)
    assert ortusen_planlar([a, b]) == set()


def test_saat_belirsiz_aday_degil() -> None:
    a = _aday(1, None, None, {5})
    b = _aday(2, _an(7), _an(9), {5})
    assert ortusen_planlar([a, b]) == set()


def test_sef_sahada_degilse_kumede_yok() -> None:
    # Şef (9) A işinde sorumlu, sahaya gitmiyor → kümede yok; B'de teknisyen.
    a = _aday(1, _an(7), _an(9), {5})
    b = _aday(2, _an(8), _an(10), {9})
    assert ortusen_planlar([a, b]) == set()
    a_sahada = _aday(1, _an(7), _an(9), {5, 9})
    assert ortusen_planlar([a_sahada, b]) == {1, 2}


def test_arac_ve_musaitlik() -> None:
    a = _aday(1, _an(7), _an(9), {5}, arac=3)
    b = _aday(2, _an(8), _an(10), {6}, arac=3)
    assert ortusen_planlar([a, b]) == {1, 2}
    c = _aday(3, _an(12), _an(13), {7})
    assert ortusen_planlar([c], [(7, _an(12, 30), _an(14))]) == {3}
    assert ortusen_planlar([c], [(8, _an(12, 30), _an(14))]) == set()


def test_gece_yarisini_asan_plan_iki_gun_kilitler() -> None:
    # 2026-01-15 22:00 İstanbul = 19:00 UTC; 4 saat → 16 Ocak 02:00 İstanbul.
    gunler = dokunulan_gunler(_an(19), _an(23), date(2026, 1, 15))
    assert gunler == [date(2026, 1, 15), date(2026, 1, 16)]
    # Tam gece yarısında biten plan ertesi günü kilitlemez (21:00 UTC = 00:00 İst.).
    assert dokunulan_gunler(_an(19), _an(21), date(2026, 1, 15)) == [date(2026, 1, 15)]
    assert dokunulan_gunler(None, None, date(2026, 1, 15)) == [date(2026, 1, 15)]


def test_gerekce_en_az_on_karakter() -> None:
    assert not gerekce_gecerli_mi("tamam")
    assert not gerekce_gecerli_mi("          ")
    assert gerekce_gecerli_mi("Acil müşteri talebi")
