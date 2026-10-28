"""MESAI takvimli SLA aritmetiği — DB'siz (Faz A, TS-200; M5.1/M5.4).

Kural: hafta içi (Pzt–Cum) 08:30–18:00 Europe/Istanbul; resmî/dinî tatiller
FARK ETMEZ. SQL karşılığı (`servis_mesai_dk`) ile eşitlik PG gerektirir:
`tests/integration/test_servis_sla_mesai.py`.

Takvim (Ekim 2026): 23 Cuma, 24 Cumartesi, 25 Pazar, 26 Pazartesi; 29 Ekim
Perşembe (Cumhuriyet Bayramı — tatil sayılmaz).
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.teknik_servis import SLA_TAKVIM_TURLERI
from app.services import settings as ayar
from app.services.teknik_servis import sla, sla_takvim
from app.services.teknik_servis.sla_takvim import MesaiTakvimi, is_saati_ekle, takvim_dakika
from app.services.teknik_servis.yerel_zaman import YEREL


def y(gun: int, saat: int, dakika: int = 0, saniye: int = 0, ay: int = 10) -> datetime:
    """Ekim 2026'da yerel (İstanbul) an."""
    return datetime(2026, ay, gun, saat, dakika, saniye, tzinfo=YEREL)


M = "MESAI"


# --- is_saati_ekle -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bas", "dk", "beklenen"),
    [
        # Görev tanımındaki örnek: Cuma 17:00 + 120 dk → Pazartesi 09:30.
        (y(23, 17), 120, y(26, 9, 30)),
        # Tam mesai bitişine düşen hedef o an döner (Pazartesi 08:30 değil).
        (y(23, 17), 60, y(23, 18)),
        (y(23, 17), 61, y(26, 8, 31)),
        # Cumartesi / Pazar açılan iş Pazartesi 08:30'dan sayar.
        (y(24, 10), 30, y(26, 9)),
        (y(25, 23, 59), 1, y(26, 8, 31)),
        # Mesai öncesi aynı gün: 08:30'dan sayar.
        (y(26, 7), 30, y(26, 9)),
        # Gece yarısını aşan: Salı 22:00 → Çarşamba 08:30'dan.
        (y(20, 22), 60, y(21, 9, 30)),
        # Mesai içinde, gün sonunu aşan: Salı 17:30 + 60 → Çarşamba 09:00.
        (y(20, 17, 30), 60, y(21, 9)),
        # Tam bir mesai haftası (5 × 570 dk) Pzt 08:30 → Cum 18:00.
        (y(26, 8, 30), 5 * 570, y(30, 18)),
        (y(26, 8, 30), 5 * 570 + 1, y(2, 8, 31, ay=11)),
        # Resmî tatil (29 Ekim Perşembe) FARK ETMEZ: Çarşamba 17:00 + 120 → Perşembe 09:30.
        (y(28, 17), 120, y(29, 9, 30)),
        # 0 dk hedefi oynatmaz (mesai dışında bile).
        (y(24, 10), 0, y(24, 10)),
    ],
)
def test_mesai_ekle(bas: datetime, dk: int, beklenen: datetime) -> None:
    assert is_saati_ekle(bas, dk, M) == beklenen


def test_mesai_ekle_utc_girdi_ve_cikti_dilimi_korunur() -> None:
    bas = y(23, 17).astimezone(UTC)  # 14:00 UTC
    hedef = is_saati_ekle(bas, 120, M)
    assert hedef.tzinfo == UTC
    assert hedef == y(26, 9, 30)
    assert hedef.hour == 6 and hedef.minute == 30


def test_mesai_ekle_hatalari() -> None:
    with pytest.raises(ValueError):
        is_saati_ekle(y(23, 17), -1, M)
    with pytest.raises(ValueError):
        is_saati_ekle(datetime(2026, 10, 23, 17), 10, M)  # saat dilimsiz


def test_7_24_davranisi_degismedi() -> None:
    assert is_saati_ekle(y(23, 17), 120) == y(23, 19)
    assert is_saati_ekle(y(23, 17), 120, "7_24") == y(23, 19)
    assert takvim_dakika(y(23, 17), y(26, 9, 30)) == 64 * 60 + 30


# --- takvim_dakika -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bas", "bit", "beklenen"),
    [
        (y(23, 17), y(26, 9, 30), 120),  # hafta sonu sayılmaz
        (y(24, 0), y(26, 0), 0),  # yalnız hafta sonu
        (y(20, 7), y(20, 20), 570),  # tam gün (mesai dışı uçlar kesilir)
        (y(20, 9), y(20, 9, 1, 59), 1),  # tam dakika, alttan
        (y(20, 22), y(21, 9), 30),  # gece yarısını aşan
        (y(20, 12), y(20, 11), 0),  # ters aralık → 0
        (y(20, 12), y(20, 12), 0),
        (y(28, 8, 30), y(29, 18), 1140),  # 29 Ekim tatil sayılmaz
        (y(26, 8, 30), y(2, 8, 30, ay=11), 5 * 570),  # bir hafta
    ],
)
def test_mesai_dakika(bas: datetime, bit: datetime, beklenen: int) -> None:
    assert takvim_dakika(bas, bit, M) == beklenen


def test_ekle_ve_dakika_birbirinin_tersi() -> None:
    """Herhangi bir başlangıç + n çalışma dakikası → aradaki çalışma dakikası n."""
    baslar = [y(g, s, d) for g in (20, 23, 24, 25) for s in (0, 8, 12, 17, 23) for d in (0, 31)]
    for bas in baslar:
        for dk in (1, 29, 60, 569, 570, 571, 1200, 3000):
            assert takvim_dakika(bas, is_saati_ekle(bas, dk, M), M) == dk, (bas, dk)


def test_ozel_mesai_penceresi() -> None:
    m = MesaiTakvimi.metinden("09:00", "17:00")
    assert m.gunluk_dk == 480 and m.metin() == "hafta içi 09:00–17:00"
    assert is_saati_ekle(y(23, 16), 120, M, mesai=m) == y(26, 10)
    assert takvim_dakika(y(23, 16), y(26, 10), M, mesai=m) == 120
    # Varsayılan pencere ayar varsayılanıyla aynı.
    assert (
        MesaiTakvimi.metinden(
            ayar.DEFAULTS["servis_mesai_baslangic"], ayar.DEFAULTS["servis_mesai_bitis"]
        )
        == sla_takvim.VARSAYILAN_MESAI
    )
    with pytest.raises(ValueError):
        MesaiTakvimi.metinden("18:00", "08:30")


def test_mesai_ayar_dogrulamasi() -> None:
    assert ayar.ayar_dogrula("servis_mesai_baslangic", "07:45") == "07:45"
    with pytest.raises(ayar.AyarHatasi):
        ayar.ayar_dogrula("servis_mesai_bitis", "25:00")


def test_takvim_sozlugu_ve_migration_ayni() -> None:
    import importlib.util
    from pathlib import Path

    yol = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "e1a000000002_sla_mesai_takvimi.py"
    )
    spec = importlib.util.spec_from_file_location("e1a000000002", yol)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SLA_TAKVIM_TURLERI == SLA_TAKVIM_TURLERI
    assert set(sla_takvim.TAKVIM_ADLARI) == set(SLA_TAKVIM_TURLERI)


# --- Bekleme kayması tutarlılığı ------------------------------------------------------


@pytest.mark.parametrize(
    ("bas", "bit", "kayma"),
    [
        (y(23, 17, 30), y(26, 9), 60),  # Cuma son yarım saat + Pazartesi ilk yarım saat
        (y(24, 9), y(25, 20), 0),  # hafta sonu beklemesi SLA'yı kaydırmaz
        (y(20, 19), y(21, 8), 0),  # gece beklemesi
        (y(20, 10), y(20, 11, 30), 90),
    ],
)
def test_bekleme_kaymasi_mesai(bas: datetime, bit: datetime, kayma: int) -> None:
    """`_bekleme_kaymasi_isle`: kayma = takvim_dakika, hedef = is_saati_ekle(hedef, kayma)."""
    assert takvim_dakika(bas, bit, M) == kayma
    hedef = y(26, 10)
    yeni = is_saati_ekle(hedef, kayma, M)
    assert takvim_dakika(hedef, yeni, M) == kayma
    if kayma == 0:
        assert yeni == hedef


# --- Risk oranı (Python tarafı; SQL ile eşitlik entegrasyon testinde) -------------------


def _is(tur: str, bas: datetime, hedef: datetime):
    return SimpleNamespace(
        tur="ARIZA",
        kategori="GUNLUK_SERVIS",
        status="ISLEMDE",
        sla_sonuc=None,
        sla_baslangic_at=bas,
        cozum_hedef_at=hedef,
        cozum_hedef_ilk_at=hedef,
        mudahale_hedef_at=None,
        ilk_mudahale_at=None,
        sla_takvim_turu=tur,
        sla_durdurulan_dk=None,
        sla_kaynak="CANLI",
        gecikme_nedeni=None,
    )


def test_risk_mesai_calisma_dakikasiyla_olculur() -> None:
    # Cuma 17:00 + 600 çalışma dk → Pazartesi 17:30.
    bas = y(23, 17)
    hedef = is_saati_ekle(bas, 600, M)
    assert hedef == y(26, 17, 30)
    so = _is(M, bas, hedef)
    # Pazartesi 08:00: duvar saatiyle %87 geçmiş olurdu; çalışılan 60/600 = %10.
    assert sla.sla_durumu(so, None, y(26, 8), 80).durum == "ZAMANINDA"
    # %80 = 480 dk → Pazartesi 08:30 + 420 dk = 15:30 tam sınır.
    assert sla.sla_durumu(so, None, y(26, 15, 30), 80).durum == "RISKTE"
    assert sla.sla_durumu(so, None, y(26, 15, 29), 80).durum == "ZAMANINDA"
    assert sla.sla_durumu(so, None, y(26, 17, 30), 80).durum == "ASILDI"
    # Aynı iş 7/24 olsaydı Pazartesi 08:00 riskte sayılırdı.
    assert sla.sla_durumu(_is("7_24", bas, hedef), None, y(26, 8), 80).durum == "RISKTE"


def test_sla_blogu_takvim_adi() -> None:
    so = _is(M, y(23, 17), y(26, 9, 30))
    blok = sla.sla_blogu(so, None, y(23, 17, 30), 80)
    assert blok["takvim_turu"] == "MESAI"
    assert blok["takvim_adi"] == "Mesai (hafta içi 08:30–18:00)"
    assert sla.takvim_adi("7_24") == "7/24"
    assert sla.takvim_adi(None) is None
    ozel = MesaiTakvimi.metinden("09:00", "17:30")
    assert sla.takvim_adi("MESAI", ozel) == "Mesai (hafta içi 09:00–17:30)"
    # kalan_dk hedef ANINA kalan duvar saatidir (takvimden bağımsız).
    assert blok["kalan_dk"] == int((y(26, 9, 30) - y(23, 17, 30)).total_seconds() // 60)


def test_timedelta_yardimci_kontrol() -> None:
    """Yardımcı `y()` yerel saati doğru kurar (UTC+3)."""
    assert y(23, 17).utcoffset() == timedelta(hours=3)
